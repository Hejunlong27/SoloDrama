import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { mkdtemp, readFile, rm } from "@solodrama/file";
import { isAbsolute, relative, resolve } from "node:path";
import { tmpdir } from "node:os";
import { probeInstance, queueLoad, verifyWorkflow } from "./connector";
import { comfyHubStore } from "./store";
import { createComfyHubProviderTools } from "./runtime";
import { remoteAddress } from "@/utils/workspace/download";

export { comfyHubStore } from "./store";
export { createComfyHubProviderTools } from "./runtime";
export { getCloudLifecycleAdapter, listCloudLifecycleAdapters, registerCloudLifecycleAdapter } from "./lifecycle";
export type { CloudLifecycleAdapter, CloudLifecycleAction } from "./lifecycle";
export type { PublicComfyInstance, PublicComfyWorkflow } from "./store";

const execFileAsync = promisify(execFile);
const maxWorkflowBytes = 5 * 1024 * 1024;

export async function testInstance(id: string) {
  const instance = await comfyHubStore.getRuntimeInstance(id);
  if (!instance) throw Object.assign(new Error("实例不存在"), { status: 404 });
  const probe = await probeInstance(instance);
  await comfyHubStore.updateHealth(id, probe.health);
  return probe;
}

export async function verifyInstanceWorkflow(workflowId: string, instanceId: string) {
  const workflow = await comfyHubStore.getWorkflow(workflowId);
  const instance = await comfyHubStore.getRuntimeInstance(instanceId);
  if (!instance) throw Object.assign(new Error("实例不存在"), { status: 404 });
  return verifyWorkflow(instance, workflow);
}

export async function instanceCapabilities(id: string) {
  const instance = await comfyHubStore.getRuntimeInstance(id);
  if (!instance) throw Object.assign(new Error("实例不存在"), { status: 404 });
  const probe = await probeInstance(instance);
  await comfyHubStore.updateHealth(id, probe.health);
  return {
    id,
    health: probe.health,
    nodeCount: probe.nodeNames.length,
    nodes: probe.nodeNames,
    features: probe.features,
    queue: await queueLoad(instance),
  };
}

async function fetchText(url: string, sourceType: "http" | "s3") {
  const normalized = remoteAddress(url, sourceType === "s3");
  const bytes = await (await import("@/utils/workspace/download")).downloadPublicFile(normalized.href, {
    signal: AbortSignal.timeout(30000), maxBytes: maxWorkflowBytes, label: "ComfyUI 工作流", httpsOnly: sourceType === "s3",
  });
  return bytes.toString("utf8");
}

async function readGitWorkflow(input: { url: string; filePath: string; branch?: string }) {
  const url = remoteAddress(input.url, true);
  if (!input.filePath.trim() || isAbsolute(input.filePath) || input.filePath.split(/[\\/]/).includes("..")) throw Object.assign(new Error("Git 工作流文件路径必须是仓库内的相对路径"), { status: 400 });
  const directory = await mkdtemp(resolve(tmpdir(), "solodrama-comfy-workflow-"));
  try {
    const args = ["clone", "--depth", "1", "--single-branch"];
    if (input.branch?.trim()) args.push("--branch", input.branch.trim());
    args.push("--", url.href, directory);
    await execFileAsync("git", args, { windowsHide: true, timeout: 60000, maxBuffer: 2 * 1024 * 1024 });
    const target = resolve(directory, input.filePath);
    const offset = relative(directory, target);
    if (!offset || offset === ".." || offset.startsWith("..\\") || offset.startsWith("../") || isAbsolute(offset)) throw Object.assign(new Error("Git 工作流路径越界"), { status: 403 });
    const info = await import("@solodrama/file").then(module => module.stat(target));
    if (!info.isFile() || info.size > maxWorkflowBytes) throw Object.assign(new Error("Git 工作流文件无效或超过 5 MB"), { status: 400 });
    return await readFile(target, "utf8");
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}

export async function readWorkflowSource(input: {
  sourceType: "local" | "http" | "git" | "s3" | "market";
  content?: string;
  url?: string;
  filePath?: string;
  branch?: string;
}) {
  if (input.sourceType === "local") {
    if (!input.content?.trim()) throw Object.assign(new Error("请粘贴或选择本地工作流 JSON"), { status: 400 });
    return input.content;
  }
  if ((input.sourceType === "http" || input.sourceType === "s3") && input.url?.trim()) return fetchText(input.url.trim(), input.sourceType);
  if (input.sourceType === "git" && input.url?.trim() && input.filePath?.trim()) return readGitWorkflow({ url: input.url.trim(), filePath: input.filePath.trim(), branch: input.branch });
  if (input.sourceType === "market") throw Object.assign(new Error("当前实例或平台未提供经过确认的工作流市场扩展接口"), { status: 501 });
  throw Object.assign(new Error("工作流来源参数不完整"), { status: 400 });
}

export async function importWorkflow(input: Record<string, unknown>) {
  const sourceType = input.sourceType;
  if (!["local", "http", "git", "s3", "market"].includes(String(sourceType))) throw Object.assign(new Error("工作流来源无效"), { status: 400 });
  const content = await readWorkflowSource({
    sourceType: sourceType as "local" | "http" | "git" | "s3" | "market",
    content: typeof input.content === "string" ? input.content : undefined,
    url: typeof input.url === "string" ? input.url : undefined,
    filePath: typeof input.filePath === "string" ? input.filePath : undefined,
    branch: typeof input.branch === "string" ? input.branch : undefined,
  });
  return comfyHubStore.saveWorkflow({
    name: input.name, description: input.description, category: input.category, type: input.type,
    workflow: content, mapping: input.mapping, requiredModels: input.requiredModels,
    sourceType, sourceRef: typeof input.url === "string" ? input.url : input.sourceType === "local" ? "本地导入" : undefined,
    sourceConfig: typeof input.url === "string" ? { url: input.url, ...(typeof input.filePath === "string" ? { filePath: input.filePath } : {}), ...(typeof input.branch === "string" ? { branch: input.branch } : {}) } : undefined,
    expectedRevision: input.expectedRevision,
  });
}

export async function syncWorkflowSource(input: { id: string; sourceType: "http" | "s3" | "git" | "market"; url: string; filePath?: string; branch?: string; expectedRevision: number }) {
  const existing = await comfyHubStore.getWorkflow(input.id);
  const content = await readWorkflowSource({ ...input });
  return comfyHubStore.saveWorkflow({
    id: existing.id, name: existing.name, description: existing.description, category: existing.category, type: existing.type,
    workflow: content, mapping: existing.mapping, requiredModels: existing.requiredModels,
    sourceType: input.sourceType, sourceRef: input.url, sourceConfig: { url: input.url, ...(input.filePath ? { filePath: input.filePath } : {}), ...(input.branch ? { branch: input.branch } : {}) }, expectedRevision: input.expectedRevision,
  });
}