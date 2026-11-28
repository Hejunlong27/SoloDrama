import { randomUUID } from "node:crypto";
import type { ProviderTaskData } from "@solodrama/providers";
import { assertProviderUrl } from "@/utils/media/providerUrl";
import { cancelQueuedPrompt, probeInstance, queueLoad, submitWorkflow, uploadImage, waitForResult } from "./connector";
import { comfyHubStore, type RuntimeComfyInstance, type RuntimeComfyWorkflow } from "./store";

type Target = [string, string] | { nodeId: string; field: string };
type Mapping = Record<string, unknown> & {
  prompt?: Target | Target[];
  negativePrompt?: Target | Target[];
  images?: Target[];
  width?: Target;
  height?: Target;
  size?: Target;
  ratio?: Target;
  duration?: Target;
  steps?: Target;
  seed?: Target;
  prefix?: Target;
  extra?: Record<string, Target | Target[]>;
};
type HubTaskData = { kind: "solodramaComfyHub"; promptId: string; instanceId: string; baseUrl: string; mediaType: "image" | "video" | "audio"; deadline: number };
type HubRequest = {
  model: string;
  prompt?: string;
  text?: string;
  images?: MediaInput[];
  videos?: MediaInput[];
  audios?: MediaInput[];
  firstFrame?: MediaInput;
  lastFrame?: MediaInput;
  ratio?: string;
  size?: string;
  resolution?: string;
  duration?: number;
  generateAudio?: boolean;
  other?: Record<string, unknown>;
};

const healthCache = new Map<string, { expires: number; nodes: Set<string>; online: boolean; queue: number }>();

function targets(value: unknown): Target[] {
  if (value === undefined) return [];
  if (!Array.isArray(value)) throw new Error("工作流映射目标必须是 [nodeId, fieldName] 或目标数组");
  if (value.length === 2 && typeof value[0] === "string" && typeof value[1] === "string") return [[value[0], value[1]]];
  return value.map(item => {
    if (!Array.isArray(item) || item.length !== 2 || typeof item[0] !== "string" || typeof item[1] !== "string") throw new Error("工作流映射目标必须是 [nodeId, fieldName]");
    return [item[0], item[1]] as Target;
  });
}
function applyTarget(workflow: Record<string, unknown>, target: Target, value: unknown) {
  const nodeId = Array.isArray(target) ? target[0] : target.nodeId;
  const field = Array.isArray(target) ? target[1] : target.field;
  const node = workflow[nodeId];
  if (!node || typeof node !== "object" || Array.isArray(node)) throw new Error(`工作流缺少节点 ${nodeId}`);
  const inputs = (node as Record<string, unknown>).inputs;
  if (!inputs || typeof inputs !== "object" || Array.isArray(inputs)) throw new Error(`工作流节点 ${nodeId} 缺少 inputs`);
  (inputs as Record<string, unknown>)[field] = value;
}
function applyTargets(workflow: Record<string, unknown>, targetValue: unknown, value: unknown) {
  for (const target of targets(targetValue)) applyTarget(workflow, target, value);
}
function mappingOf(workflow: RuntimeComfyWorkflow): Mapping {
  try {
    const value: unknown = JSON.parse(workflow.mapping || "{}");
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error();
    return value as Mapping;
  } catch { throw new Error("工作流参数映射不是有效 JSON 对象"); }
}
async function mediaBytes(input: MediaInput, signal: AbortSignal) {
  if (input.type === "binary") return { data: input.data, mimeType: input.mimeType, name: input.name || "reference" };
  if (input.type === "base64") return { data: Uint8Array.from(Buffer.from(input.data.replace(/^data:[^;]+;base64,/, ""), "base64")), mimeType: input.mimeType, name: input.name || "reference" };
  assertProviderUrl(input.url);
  const response = await fetch(input.url, { redirect: "error", signal });
  if (!response.ok) throw Object.assign(new Error(`读取参考素材失败（HTTP ${response.status}）`), { status: response.status });
  return { data: new Uint8Array(await response.arrayBuffer()), mimeType: response.headers.get("content-type") || input.mimeType || "application/octet-stream", name: input.name || "reference" };
}
async function prepareImages(workflow: Record<string, unknown>, mapping: Mapping, inputs: MediaInput[] | undefined, instance: RuntimeComfyInstance, signal: AbortSignal) {
  const slots = targets(mapping.images);
  if (!slots.length || !inputs?.length) return;
  for (let index = 0; index < slots.length; index++) {
    const input = inputs[Math.min(index, inputs.length - 1)]!;
    signal.throwIfAborted();
    const media = await mediaBytes(input, signal);
    applyTarget(workflow, slots[index]!, await uploadImage(instance, media.data, media.mimeType, media.name));
  }
}
async function evaluateInstance(instance: RuntimeComfyInstance, requiredNodes: string[]) {
  const cached = healthCache.get(instance.id);
  if (cached && cached.expires > Date.now()) return requiredNodes.every(node => cached.nodes.has(node)) ? cached : undefined;
  try {
    const probe = await probeInstance(instance);
    await comfyHubStore.updateHealth(instance.id, probe.health);
    const queue = await queueLoad(instance);
    const value = { expires: Date.now() + 15000, nodes: new Set(probe.nodeNames), online: probe.health.status !== "offline", queue: queue.running + queue.pending };
    healthCache.set(instance.id, value);
    return requiredNodes.every(node => value.nodes.has(node)) ? value : undefined;
  } catch {
    healthCache.set(instance.id, { expires: Date.now() + 5000, nodes: new Set(), online: false, queue: 0 });
    return undefined;
  }
}
async function selectInstance(request: HubRequest, workflow: RuntimeComfyWorkflow) {
  if (workflow.requiredModels.length) throw new Error(`当前实例缺少工作流要求的模型：${workflow.requiredModels.join("、")}`);
  const instances = (await comfyHubStore.listRuntimeInstances()).filter(item => item.enabled);
  const requestedId = typeof request.other?.instanceId === "string" ? request.other.instanceId : "";
  const candidates = requestedId ? instances.filter(item => item.id === requestedId) : instances;
  if (!candidates.length) throw new Error(requestedId ? "指定实例不存在或已禁用" : "没有可用的 ComfyUI 实例");
  const evaluated = [] as { instance: RuntimeComfyInstance; queue: number }[];
  for (const instance of candidates) {
    const value = await evaluateInstance(instance, workflow.requiredNodes);
    if (value?.online) evaluated.push({ instance, queue: value.queue });
  }
  if (!evaluated.length) throw new Error(`当前实例缺少以下节点，无法运行该工作流：${workflow.requiredNodes.join("、") || "实例离线"}`);
  evaluated.sort((left, right) => right.instance.priority - left.instance.priority || left.queue - right.queue || left.instance.name.localeCompare(right.instance.name));
  return evaluated[0]!.instance;
}
function buildWorkflow(workflow: RuntimeComfyWorkflow, request: HubRequest, instance: RuntimeComfyInstance, signal: AbortSignal) {
  let parsed: Record<string, unknown>;
  try {
    const value: unknown = JSON.parse(workflow.apiWorkflow);
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error();
    parsed = JSON.parse(JSON.stringify(value)) as Record<string, unknown>;
  } catch { throw new Error("工作流 API JSON 无效"); }
  const mapping = mappingOf(workflow);
  const prompt = request.prompt ?? request.text ?? "";
  if (!prompt.trim()) throw new Error("请输入提示词");
  applyTargets(parsed, mapping.prompt, prompt);
  if (typeof request.other?.negativePrompt === "string") applyTargets(parsed, mapping.negativePrompt, request.other.negativePrompt);
  if (request.ratio) applyTargets(parsed, mapping.ratio, request.ratio);
  if (request.duration !== undefined) applyTargets(parsed, mapping.duration, request.duration);
  const seed = Number(request.other?.seed);
  applyTargets(parsed, mapping.seed, Number.isFinite(seed) ? seed : Math.floor(Math.random() * 2_147_483_647));
  const steps = Number(request.other?.steps);
  if (Number.isFinite(steps) && steps > 0) applyTargets(parsed, mapping.steps, Math.round(steps));
  applyTargets(parsed, mapping.prefix, `solodrama_${Date.now().toString(36)}`);
  if (request.size && mapping.width && mapping.height) {
    const match = /^(\d+)x(\d+)$/i.exec(request.size);
    if (match) { applyTarget(parsed, targets(mapping.width)[0]!, Number(match[1])); applyTarget(parsed, targets(mapping.height)[0]!, Number(match[2])); }
  }
  if (mapping.extra && typeof mapping.extra === "object") for (const [field, target] of Object.entries(mapping.extra)) if (Object.hasOwn(request.other || {}, field)) applyTargets(parsed, target, request.other![field]);
  return { workflow: parsed, mapping, images: request.images?.length ? request.images : request.firstFrame ? [request.firstFrame, ...(request.lastFrame ? [request.lastFrame] : [])] : [] };
}

export function createComfyHubProviderTools(saveTaskData?: (data: ProviderTaskData) => Promise<void>) {
  return {
    async generate(mediaType: "image" | "video" | "audio", input: Record<string, unknown>, signal?: AbortSignal) {
      const request = input as HubRequest;
      const workflow = await comfyHubStore.getWorkflow(request.model, typeof request.other?.workflowVersion === "number" ? request.other.workflowVersion : undefined);
      const selected = await selectInstance(request, workflow);
      const deadline = Date.now() + Math.max(1, Number(request.other?.timeoutMinutes) || 30) * 60000;
      const prepared = buildWorkflow(workflow, request, selected, signal ?? new AbortController().signal);
      const activeSignal = signal ?? new AbortController().signal;
      await prepareImages(prepared.workflow, prepared.mapping, prepared.images, selected, activeSignal);
      let promptId = "";
      const taskData: HubTaskData = { kind: "solodramaComfyHub", promptId: "", instanceId: selected.id, baseUrl: selected.endpoint, mediaType, deadline };
      try {
        promptId = await submitWorkflow(selected, workflow, prepared.workflow);
        taskData.promptId = promptId;
        await saveTaskData?.(taskData);
        return await waitForResult(selected, promptId, deadline, mediaType, activeSignal);
      } catch (error) {
        if (activeSignal.aborted && promptId) await cancelQueuedPrompt(selected, promptId).catch(() => {});
        throw error;
      }
    },
    async resume(data: ProviderTaskData, signal?: AbortSignal) {
      if (data.kind !== "solodramaComfyHub" || typeof data.promptId !== "string" || typeof data.instanceId !== "string"
        || !["image", "video", "audio"].includes(String(data.mediaType)) || typeof data.deadline !== "number") throw new Error("云端 ComfyUI 任务恢复数据无效");
      const task = data as HubTaskData;
      const instance = await comfyHubStore.getRuntimeInstance(task.instanceId);
      if (!instance) throw new Error("原 ComfyUI 实例已被删除，无法恢复任务");
      return waitForResult(instance, task.promptId, task.deadline, task.mediaType, signal);
    },
    async capability(workflowId: string, instanceId?: string) {
      const workflow = await comfyHubStore.getWorkflow(workflowId);
      const instances = (await comfyHubStore.listRuntimeInstances()).filter(item => item.enabled && (!instanceId || item.id === instanceId));
      const results = [];
      for (const instance of instances) {
        const value = await evaluateInstance(instance, workflow.requiredNodes);
        results.push({ instanceId: instance.id, compatible: !!value?.online, queue: value?.queue });
      }
      return results;
    },
  };
}

export function newHubTaskId() { return randomUUID(); }