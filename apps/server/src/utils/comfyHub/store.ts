import { randomUUID } from "node:crypto";
import { dirname, join } from "node:path";
import { lstat, mkdir, readFile, writeAtomic } from "@solodrama/file";
import { parseComfyJsonWithReport } from "@solodrama/providers/comfyWorkflow";
import { z } from "zod";
import conf from "@/utils/conf";
import { createComfyHubSecret } from "./secret";

const idSchema = z.uuid();
const urlSchema = z.string().trim().min(1).max(4096).refine(value => {
  try {
    const url = new URL(value);
    return ["http:", "https:", "ws:", "wss:"].includes(url.protocol) && !url.username && !url.password && !url.hash;
  } catch { return false; }
}, "请输入不含账号密码的有效地址");
const httpUrlSchema = urlSchema.refine(value => /^https?:/i.test(value), "请输入 HTTP(S) 地址");
const timeoutSchema = z.number().int().min(1000).max(300000);
const stringList = z.array(z.string().trim().min(1).max(200)).max(200);

const instanceInputSchema = z.strictObject({
  id: idSchema.optional(),
  name: z.string().trim().min(1).max(120),
  platformLabel: z.string().trim().min(1).max(120),
  endpoint: httpUrlSchema,
  websocketEndpoint: urlSchema.optional(),
  authMode: z.enum(["none", "bearer", "header"]).default("none"),
  authHeaderName: z.string().trim().max(128).optional(),
  token: z.string().max(16384).optional(),
  customHeaders: z.record(z.string().max(128), z.string().max(4096)).optional(),
  allowPrivateNetwork: z.boolean().default(false),
  connectionTimeoutMs: timeoutSchema.default(15000),
  priority: z.number().int().min(-1000).max(1000).default(0),
  enabled: z.boolean().default(true),
  favorite: z.boolean().default(false),
  group: z.string().trim().max(120).optional(),
  tags: stringList.default([]),
  note: z.string().max(4000).optional(),
  expectedRevision: z.number().int().min(0).max(2147483647),
});

const instanceHealthSchema = z.object({
  status: z.enum(["online", "offline", "degraded", "unknown"]),
  checkedAt: z.number().finite().nonnegative(),
  latency: z.number().finite().nonnegative().optional(),
  version: z.string().max(200).optional(),
  system: z.record(z.string(), z.unknown()).optional(),
  features: stringList.optional(),
  nodeCount: z.number().int().nonnegative().optional(),
  queueRunning: z.number().int().nonnegative().optional(),
  queuePending: z.number().int().nonnegative().optional(),
  websocket: z.enum(["connected", "unavailable", "unknown"]).optional(),
  error: z.string().max(2000).optional(),
});
const instanceRecordSchema = instanceInputSchema.omit({ token: true, customHeaders: true, expectedRevision: true }).extend({
  id: idSchema,
  secretCipher: z.string().optional(),
  health: instanceHealthSchema.optional(),
  createdAt: z.number().finite().nonnegative(),
  updatedAt: z.number().finite().nonnegative(),
});
const instanceStateSchema = z.object({ revision: z.number().int().min(0), items: z.array(instanceRecordSchema) });

const workflowInputSchema = z.strictObject({
  id: idSchema.optional(),
  name: z.string().trim().min(1).max(160),
  description: z.string().max(4000).default(""),
  category: z.string().trim().max(120).default("通用"),
  type: z.enum(["image", "video", "audio"]),
  workflow: z.string().min(2).max(5 * 1024 * 1024),
  mapping: z.string().max(1024 * 1024).default("{}"),
  requiredModels: stringList.default([]),
  thumbnail: z.string().max(1024 * 1024).optional(),
  sourceType: z.enum(["local", "http", "git", "s3", "market"]).default("local"),
  sourceRef: z.string().max(4096).optional(),
  sourceConfig: z.record(z.string(), z.json()).optional(),
  expectedRevision: z.number().int().min(0).max(2147483647),
});
const workflowVersionSchema = z.object({
  version: z.number().int().positive(),
  apiWorkflow: z.string().min(2).max(5 * 1024 * 1024),
  sourceWorkflow: z.string().min(2).max(5 * 1024 * 1024).optional(),
  mapping: z.string().max(1024 * 1024),
  createdAt: z.number().finite().nonnegative(),
});
const workflowRecordSchema = z.object({
  id: idSchema,
  name: z.string(),
  description: z.string(),
  category: z.string(),
  type: z.enum(["image", "video", "audio"]),
  format: z.enum(["api", "ui"]),
  apiWorkflow: z.string(),
  sourceWorkflow: z.string().optional(),
  mapping: z.string(),
  requiredNodes: stringList,
  requiredModels: stringList,
  thumbnail: z.string().optional(),
  sourceType: z.enum(["local", "http", "git", "s3", "market"]),
  sourceRef: z.string().optional(),
  sourceConfig: z.record(z.string(), z.json()).optional(),
  version: z.number().int().positive(),
  versions: z.array(workflowVersionSchema).max(20),
  createdAt: z.number().finite().nonnegative(),
  updatedAt: z.number().finite().nonnegative(),
});
const workflowStateSchema = z.object({ revision: z.number().int().min(0), items: z.array(workflowRecordSchema) });

type InstanceInput = z.infer<typeof instanceInputSchema>;
type InstanceRecord = z.infer<typeof instanceRecordSchema>;
type InstanceHealth = z.infer<typeof instanceHealthSchema>;
type WorkflowInput = z.infer<typeof workflowInputSchema>;
type WorkflowRecord = z.infer<typeof workflowRecordSchema>;

export type PublicComfyInstance = Omit<InstanceRecord, "secretCipher"> & { hasCredential: boolean; headerNames: string[] };
export type PublicComfyWorkflow = Omit<WorkflowRecord, "apiWorkflow" | "versions"> & { nodeCount: number };
export type RuntimeComfyInstance = InstanceRecord & { token: string; customHeaders: Record<string, string> };
export type RuntimeComfyWorkflow = WorkflowRecord;

function invalid(message: string, status = 400): never { throw Object.assign(new Error(message), { status }); }
function directory() { return join(dirname(conf.path), "comfyHub"); }
function normalizedEndpoint(value: string) { return value.trim().replace(/\/+$/, ""); }
function derivedNodes(workflow: Record<string, unknown>) {
  const types = new Set<string>();
  for (const node of Object.values(workflow)) {
    if (!node || typeof node !== "object" || Array.isArray(node)) continue;
    const type = (node as Record<string, unknown>).class_type;
    if (typeof type === "string" && type.trim()) types.add(type.trim());
  }
  return [...types].sort();
}
function parseWorkflow(value: string) {
  const parsed = parseComfyJsonWithReport(value);
  return { ...parsed, requiredNodes: derivedNodes(parsed.workflow), apiWorkflow: JSON.stringify(parsed.workflow, null, 2) };
}

export function createComfyHubStore() {
  const secret = createComfyHubSecret(directory());
  let queue = Promise.resolve();
  const health = new Map<string, InstanceHealth>();
  function serial<T>(action: () => Promise<T>): Promise<T> {
    const current = queue.then(action);
    queue = current.then(() => {}, () => {});
    return current;
  }
  async function ensureDirectory() {
    await mkdir(directory(), { recursive: true, mode: 0o700 });
    const info = await lstat(directory());
    if (!info.isDirectory() || info.isSymbolicLink()) invalid("云端算力数据目录必须是普通目录", 503);
  }
  async function readState<T>(name: string, schema: z.ZodType<T>, fallback: T): Promise<T> {
    const path = join(directory(), name);
    const info = await lstat(path).catch((cause: NodeJS.ErrnoException) => {
      if (cause.code === "ENOENT") return null;
      throw cause;
    });
    if (!info) return fallback;
    if (!info.isFile() || info.isSymbolicLink() || info.size > 32 * 1024 * 1024) invalid("云端算力配置文件无效", 503);
    try { return schema.parse(JSON.parse(await readFile(path, "utf8"))); }
    catch { invalid("云端算力配置文件损坏，请检查后恢复备份", 503); }
  }
  async function writeState(name: string, value: unknown) {
    await ensureDirectory();
    await writeAtomic(join(directory(), name), JSON.stringify(value, null, 2), { mode: 0o600 });
  }
  async function instancesState() { return readState("instances.json", instanceStateSchema, { revision: 0, items: [] }); }
  async function workflowsState() { return readState("workflows.json", workflowStateSchema, { revision: 0, items: [] }); }
  async function publicInstance(record: InstanceRecord): Promise<PublicComfyInstance> {
    const { secretCipher, ...value } = record;
    const credentials = secretCipher ? await secret.open(secretCipher) : {};
    const headers = credentials.customHeaders && typeof credentials.customHeaders === "object" && !Array.isArray(credentials.customHeaders)
      ? credentials.customHeaders as Record<string, unknown> : {};
    return { ...value, health: health.get(record.id) ?? record.health, hasCredential: typeof credentials.token === "string" && !!credentials.token, headerNames: Object.keys(headers) };
  }
  async function runtimeInstance(record: InstanceRecord): Promise<RuntimeComfyInstance> {
    const credentials = record.secretCipher ? await secret.open(record.secretCipher) : {};
    return {
      ...record,
      token: typeof credentials.token === "string" ? credentials.token : "",
      customHeaders: credentials.customHeaders && typeof credentials.customHeaders === "object" && !Array.isArray(credentials.customHeaders)
        ? Object.fromEntries(Object.entries(credentials.customHeaders).filter((entry): entry is [string, string] => typeof entry[1] === "string")) : {},
    };
  }
  function publicWorkflow(record: WorkflowRecord): PublicComfyWorkflow {
    const { apiWorkflow, versions, ...value } = record;
    return { ...value, nodeCount: Object.keys(parseComfyJsonWithReport(apiWorkflow).workflow).length };
  }
  return {
    async listInstances() {
      const state = await instancesState();
      return { revision: state.revision, items: await Promise.all(state.items.map(publicInstance)) };
    },
    async listRuntimeInstances() {
      const state = await instancesState();
      return Promise.all(state.items.map(runtimeInstance));
    },
    async getRuntimeInstance(id: string) {
      const state = await instancesState();
      const found = state.items.find(item => item.id === id);
      return found ? runtimeInstance(found) : undefined;
    },
    saveInstance(inputValue: unknown) {
      const input = instanceInputSchema.parse(inputValue);
      return serial(async () => {
        const state = await instancesState();
        if (input.expectedRevision !== state.revision) invalid("实例配置已更新，请刷新后重试", 409);
        const now = Date.now();
        const existing = input.id ? state.items.find(item => item.id === input.id) : undefined;
        if (input.id && !existing) invalid("实例不存在", 404);
        if (input.token !== undefined || input.customHeaders !== undefined) await ensureDirectory();
        let secretCipher = existing?.secretCipher;
        if (input.token !== undefined || input.customHeaders !== undefined) {
          const previous = secretCipher ? await secret.open(secretCipher) : {};
          const token = input.token === undefined ? previous.token : input.token;
          const customHeaders = input.customHeaders === undefined ? previous.customHeaders : input.customHeaders;
          secretCipher = token || customHeaders && Object.keys(customHeaders).length ? await secret.seal({ token: token ?? "", customHeaders: customHeaders ?? {} }) : undefined;
        }
        if (input.authMode === "header" && !input.authHeaderName?.trim()) invalid("Header 鉴权必须填写 Header 名称");
        const record: InstanceRecord = {
          id: existing?.id ?? randomUUID(), name: input.name, platformLabel: input.platformLabel,
          endpoint: normalizedEndpoint(input.endpoint), websocketEndpoint: input.websocketEndpoint?.trim() || undefined,
          authMode: input.authMode, authHeaderName: input.authHeaderName?.trim() || undefined,
          allowPrivateNetwork: input.allowPrivateNetwork, connectionTimeoutMs: input.connectionTimeoutMs,
          priority: input.priority, enabled: input.enabled, favorite: input.favorite, group: input.group?.trim() || undefined,
          tags: [...new Set(input.tags)], note: input.note?.trim() || undefined, secretCipher,
          health: health.get(existing?.id ?? "") ?? existing?.health, createdAt: existing?.createdAt ?? now, updatedAt: now,
        };
        const items = existing ? state.items.map(item => item.id === existing.id ? record : item) : [...state.items, record];
        await writeState("instances.json", { revision: state.revision + 1, items } satisfies z.infer<typeof instanceStateSchema>);
        return publicInstance(record);
      });
    },
    deleteInstance(id: string, expectedRevision: number) {
      idSchema.parse(id);
      return serial(async () => {
        const state = await instancesState();
        if (state.revision !== expectedRevision) invalid("实例配置已更新，请刷新后重试", 409);
        if (!state.items.some(item => item.id === id)) invalid("实例不存在", 404);
        health.delete(id);
        await writeState("instances.json", { revision: state.revision + 1, items: state.items.filter(item => item.id !== id) });
      });
    },
    async updateHealth(id: string, status: InstanceHealth) {
      return serial(async () => {
        const state = await instancesState();
        const record = state.items.find(item => item.id === id);
        if (!record) invalid("实例不存在", 404);
        const checked = instanceHealthSchema.parse(status);
        health.set(id, checked);
        await writeState("instances.json", { ...state, items: state.items.map(item => item.id === id ? { ...item, health: checked } : item) });
        return checked;
      });
    },
    async listWorkflows() {
      const state = await workflowsState();
      return { revision: state.revision, items: state.items.map(publicWorkflow) };
    },
    async getWorkflow(id: string, version?: number) {
      idSchema.parse(id);
      const state = await workflowsState();
      const record = state.items.find(item => item.id === id);
      if (!record) invalid("工作流不存在", 404);
      if (version !== undefined) {
        const snapshot = record.versions.find(item => item.version === version);
        if (!snapshot) invalid("工作流版本不存在", 404);
        return { ...record, version, apiWorkflow: snapshot.apiWorkflow, sourceWorkflow: snapshot.sourceWorkflow, mapping: snapshot.mapping, requiredNodes: derivedNodes(parseComfyJsonWithReport(snapshot.apiWorkflow).workflow) };
      }
      return record;
    },
    saveWorkflow(inputValue: unknown) {
      const input = workflowInputSchema.parse(inputValue);
      return serial(async () => {
        const state = await workflowsState();
        if (input.expectedRevision !== state.revision) invalid("工作流配置已更新，请刷新后重试", 409);
        const parsed = parseWorkflow(input.workflow);
        const now = Date.now();
        const existing = input.id ? state.items.find(item => item.id === input.id) : undefined;
        if (input.id && !existing) invalid("工作流不存在", 404);
        const record: WorkflowRecord = existing ? {
          ...existing, name: input.name, description: input.description, category: input.category, type: input.type,
          format: parsed.format, apiWorkflow: parsed.apiWorkflow, sourceWorkflow: input.workflow, mapping: input.mapping,
          requiredNodes: parsed.requiredNodes, requiredModels: [...new Set(input.requiredModels)], thumbnail: input.thumbnail,
          sourceType: input.sourceType, sourceRef: input.sourceRef, sourceConfig: input.sourceConfig, version: existing.version + 1,
          versions: [{ version: existing.version, apiWorkflow: existing.apiWorkflow, sourceWorkflow: existing.sourceWorkflow, mapping: existing.mapping, createdAt: existing.updatedAt }, ...existing.versions].slice(0, 20),
          updatedAt: now,
        } : {
          id: randomUUID(), name: input.name, description: input.description, category: input.category, type: input.type,
          format: parsed.format, apiWorkflow: parsed.apiWorkflow, sourceWorkflow: input.workflow, mapping: input.mapping,
          requiredNodes: parsed.requiredNodes, requiredModels: [...new Set(input.requiredModels)], thumbnail: input.thumbnail,
          sourceType: input.sourceType, sourceRef: input.sourceRef, sourceConfig: input.sourceConfig, version: 1, versions: [], createdAt: now, updatedAt: now,
        };
        const items = existing ? state.items.map(item => item.id === existing.id ? record : item) : [...state.items, record];
        await writeState("workflows.json", { revision: state.revision + 1, items } satisfies z.infer<typeof workflowStateSchema>);
        return { workflow: publicWorkflow(record), warnings: parsed.warnings };
      });
    },
    deleteWorkflow(id: string, expectedRevision: number) {
      idSchema.parse(id);
      return serial(async () => {
        const state = await workflowsState();
        if (state.revision !== expectedRevision) invalid("工作流配置已更新，请刷新后重试", 409);
        if (!state.items.some(item => item.id === id)) invalid("工作流不存在", 404);
        await writeState("workflows.json", { revision: state.revision + 1, items: state.items.filter(item => item.id !== id) });
      });
    },
    async models() {
      const state = await workflowsState();
      return state.items.map(item => ({ providerId: "solodramaComfyHub" as const, providerLabel: "云端 ComfyUI", modelId: item.id, label: item.name, type: item.type,
        supportsPrice: true, mode: item.type === "video" ? ["text", "singleImage", "endFrameOptional", ["imageReference:6"]] : ["text", "singleImage", "multiReference"],
        imageRatios: ["1:1", "4:3", "3:4", "16:9", "9:16"] }));
    },
  };
}

export const comfyHubStore = createComfyHubStore();