/**
 * SoloDrama ComfyUI Provider
 *
 * 本地 / 局域网 ComfyUI Provider。云端实例请使用 solodramaComfyCloud.ts。
 * 不依赖 SoloDrama 内部模块，可由「设置 → 媒体模型 → 添加自定义供应商」直接导入。
 */

type MediaType = "image" | "video" | "audio";
type ProviderFormRule = {
  type: string;
  field: string;
  title: string;
  value: unknown;
  props?: Record<string, unknown>;
  options?: { label: string; value: string }[];
  control?: Record<string, unknown>[];
};
type ProviderModel = {
  id: string;
  label: string;
  type: "text" | "image" | "video" | "audio";
  mode?: (string | string[])[];
  audio?: "optional" | boolean;
  imageSizes?: string[];
  imageRatios?: string[];
  durationResolutionMap?: { duration: number[]; resolution: string[] }[];
  rules?: readonly ProviderFormRule[];
};
type MediaInput =
  | { type: "url"; url: string; mimeType?: string; name?: string }
  | { type: "base64"; data: string; mimeType: string; name?: string }
  | { type: "binary"; data: Uint8Array; mimeType: string; name?: string };
type MediaAsset = MediaInput & { mediaType: MediaType };
type ImageRequest = {
  model: string;
  prompt: string;
  images?: MediaInput[];
  mask?: MediaInput;
  n?: number;
  ratio?: string;
  size?: string;
  quality?: string;
  outputFormat?: string;
  other?: Record<string, unknown>;
};
type VideoRequest = {
  model: string;
  prompt: string;
  mode?: string | string[];
  images?: MediaInput[];
  videos?: MediaInput[];
  audios?: MediaInput[];
  firstFrame?: MediaInput;
  lastFrame?: MediaInput;
  duration?: number;
  ratio?: string;
  resolution?: string;
  generateAudio?: boolean;
  watermark?: boolean;
  other?: Record<string, unknown>;
};
type MediaRoute = {
  id: string;
  label: string;
  kind: "textToImage" | "imageEdit" | "video";
  workflow: string;
  mapping?: string;
  baseUrl?: string;
  authHeaderName?: string;
  authHeaderValue?: string;
};
type Context = {
  config: {
    baseUrl?: string;
    authHeaderName?: string;
    authHeaderValue?: string;
    routes?: string;
    imageWorkflow?: string;
    imageMapping?: string;
    textToImageWorkflow?: string;
    textToImageMapping?: string;
    imageEditWorkflow?: string;
    imageEditMapping?: string;
    videoWorkflow?: string;
    videoMapping?: string;
    pollIntervalSeconds?: number;
    timeoutMinutes?: number;
    cancelRunning?: boolean;
  };
  signal?: AbortSignal;
  saveTaskData?: (data: ProviderTaskData) => Promise<void>;
  tool: {
    fetch: typeof fetch;
    errorMessage(value: unknown): string;
  };
};

type NodeTarget = [string, string] | { nodeId: string; field: string };
type WorkflowMapping = Record<string, unknown> & {
  prompt?: NodeTarget | NodeTarget[];
  negativePrompt?: NodeTarget | NodeTarget[];
  images?: NodeTarget[];
  width?: NodeTarget;
  height?: NodeTarget;
  size?: NodeTarget;
  ratio?: NodeTarget;
  duration?: NodeTarget;
  steps?: NodeTarget;
  seed?: NodeTarget;
  prefix?: NodeTarget;
  extra?: Record<string, NodeTarget | NodeTarget[]>;
};
type ComfyTaskData = {
  kind: "solodramaComfy";
  mediaType: "image" | "video";
  promptId: string;
  deadline: number;
  baseUrl?: string;
};
type OutputFile = {
  filename: string;
  subfolder?: string;
  type?: string;
  mediaType: MediaType;
  url: string;
};

const EMPTY_IMAGE_BASE64 =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZQmcAAAAASUVORK5CYII=";
const DEFAULT_POLL_SECONDS = 2;
const DEFAULT_TIMEOUT_MINUTES = 30;

const defaultRoutes = JSON.stringify([
  {
    id: "solodramaComfyImage",
    label: "ComfyUI 图片工作流",
    kind: "textToImage",
    workflow: "",
    mapping: "",
  },
  {
    id: "solodramaComfyH3",
    label: "ComfyUI H3 视频（六参考图槽）",
    kind: "video",
    workflow: "",
    mapping: `{
  "prompt": ["30", "value"],
  "images": [["24", "image"], ["31", "image"], ["39", "image"], ["36", "image"], ["60", "image"], ["59", "image"]],
  "duration": ["15", "value"],
  "steps": ["9", "steps"],
  "seed": ["10", "seed"],
  "ratio": ["14", "aspect_ratio"],
  "prefix": ["4", "filename_prefix"]
}`,
  },
], null, 2);

const rules = [
  {
    type: "textarea",
    field: "routes",
    title: "工作流通道",
    value: `[{"id":"solodramaComfyImage","label":"ComfyUI 图片工作流","kind":"textToImage","workflow":"","mapping":{}},{"id":"solodramaComfyH3","label":"ComfyUI H3 视频（六参考图槽）","kind":"video","workflow":"","mapping":{"prompt":["30","value"],"images":[["24","image"],["31","image"],["39","image"],["36","image"],["60","image"],["59","image"]],"duration":["15","value"],"steps":["9","steps"],"seed":["10","seed"],"ratio":["14","aspect_ratio"],"prefix":["4","filename_prefix"]}}]`,
    props: { rows: 8, placeholder: "由工作流通道编辑器维护" },
  },
  {
    type: "input",
    field: "baseUrl",
    title: "本地 ComfyUI 地址",
    value: "http://127.0.0.1:8188",
    props: { placeholder: "支持 http://127.0.0.1:8188、局域网 IP 或 .local 域名" },
  },
  {
    type: "inputNumber",
    field: "pollIntervalSeconds",
    title: "轮询间隔（秒）",
    value: 2,
    props: { min: 0.5, max: 30, step: 0.5 },
  },
  {
    type: "inputNumber",
    field: "timeoutMinutes",
    title: "任务等待上限（分钟）",
    value: 30,
    props: { min: 1, max: 240, step: 1 },
  },
  {
    type: "switch",
    field: "cancelRunning",
    title: "取消时精确删除排队任务（不会全局中断）",
    value: true,
    props: { activeText: "精确删除", inactiveText: "仅停止等待" },
  },
] as const;

function normalizeBaseUrl(value: unknown): string {
  const text = typeof value === "string" ? value.trim().replace(/\/+$/, "") : "";
  if (!text) throw new Error("请先在供应商配置中填写 ComfyUI 地址");
  const url = new URL(text);
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) throw new Error("ComfyUI 地址必须是无内嵌凭据的 HTTP(S) URL");
  return url.toString().replace(/\/+$/, "");
}

function authHeaders(context: Context): Record<string, string> {
  const name = typeof context.config.authHeaderName === "string" ? context.config.authHeaderName.trim() : "";
  const value = typeof context.config.authHeaderValue === "string" ? context.config.authHeaderValue.trim() : "";
  if (!name && !value) return {};
  if (!name || !value) throw new Error("鉴权 Header 名称和值必须同时填写");
  if (!/^[!#$%&'*+.^_`|~0-9A-Za-z-]+$/.test(name)) throw new Error("鉴权 Header 名称无效");
  return { [name]: value };
}

function requestHeaders(context: Context, json = false): Record<string, string> {
  return { Accept: "application/json", ...(json ? { "Content-Type": "application/json" } : {}), ...authHeaders(context) };
}

function parseJsonObject(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "string" || !value.trim()) return {};
  let parsed: unknown;
  try { parsed = JSON.parse(value); }
  catch (error) { throw new Error(label + " 不是有效 JSON：" + (error instanceof Error ? error.message : String(error))); }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error(label + " 必须是 JSON 对象");
  return parsed as Record<string, unknown>;
}

function cloneWorkflow(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("工作流必须是 ComfyUI 工作流 JSON 对象");
  return JSON.parse(JSON.stringify(value)) as Record<string, unknown>;
}

function targets(value: unknown): NodeTarget[] {
  if (value === undefined) return [];
  if (!Array.isArray(value)) throw new Error("映射目标必须是 [nodeId, fieldName] 或目标数组");
  if (value.length === 2 && typeof value[0] === "string" && typeof value[1] === "string") return [[value[0], value[1]]];
  return value.map(item => {
    if (!Array.isArray(item) || item.length !== 2 || typeof item[0] !== "string" || typeof item[1] !== "string") {
      throw new Error("映射目标必须是 [nodeId, fieldName]");
    }
    return [item[0], item[1]] as NodeTarget;
  });
}

function applyTarget(workflow: Record<string, unknown>, target: NodeTarget, value: unknown) {
  const nodeId = Array.isArray(target) ? target[0] : target.nodeId;
  const field = Array.isArray(target) ? target[1] : target.field;
  const node = workflow[nodeId];
  if (!node || typeof node !== "object" || Array.isArray(node)) throw new Error("工作流缺少节点 " + nodeId);
  const inputs = (node as Record<string, unknown>).inputs;
  if (!inputs || typeof inputs !== "object" || Array.isArray(inputs)) throw new Error("工作流节点 " + nodeId + " 缺少 inputs");
  (inputs as Record<string, unknown>)[field] = value;
}

function applyTargets(workflow: Record<string, unknown>, targetValue: unknown, value: unknown) {
  for (const target of targets(targetValue)) applyTarget(workflow, target, value);
}

function mediaBytes(input: MediaInput, context: Context): Promise<{ data: Uint8Array; mimeType: string; name: string }> {
  if (input.type === "binary") return Promise.resolve({ data: input.data, mimeType: input.mimeType, name: input.name || "input" });
  if (input.type === "base64") {
    return Promise.resolve({ data: Uint8Array.from(Buffer.from(input.data.replace(/^data:[^;]+;base64,/, ""), "base64")), mimeType: input.mimeType, name: input.name || "input" });
  }
  return context.tool.fetch(input.url, { signal: context.signal, redirect: "error" }).then(async response => {
    if (!response.ok) throw new Error("读取参考素材失败：HTTP " + response.status);
    return { data: new Uint8Array(await response.arrayBuffer()), mimeType: response.headers.get("content-type") || input.mimeType || "application/octet-stream", name: input.name || "input" };
  });
}

async function uploadImage(context: Context, baseUrl: string, input: MediaInput): Promise<string> {
  const media = await mediaBytes(input, context);
  const extension = media.mimeType.split("/")[1]?.replace("jpeg", "jpg").replace(/[^a-z0-9]/gi, "") || "png";
  const name = (media.name || "reference").replace(/\.[^.]+$/, "").replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 48) || "reference";
  const uniqueName = "solodrama_" + crypto.randomUUID().replaceAll("-", "") + "_" + name;
  const form = new FormData();
  form.append("image", new Blob([media.data.slice().buffer as ArrayBuffer], { type: media.mimeType }), uniqueName + "." + extension);
  form.append("overwrite", "false");
  const response = await context.tool.fetch(baseUrl + "/upload/image", {
    method: "POST", headers: authHeaders(context), body: form, signal: context.signal, redirect: "error",
  });
  if (!response.ok) throw new Error("ComfyUI 参考图上传失败：HTTP " + response.status);
  const data = await response.json() as Record<string, unknown>;
  const uploaded = typeof data.name === "string" ? data.name : "";
  if (!uploaded) throw new Error("ComfyUI 上传响应缺少 name");
  return typeof data.subfolder === "string" && data.subfolder ? data.subfolder.replace(/^\/+|\/+$/g, "") + "/" + uploaded : uploaded;
}

function pollMilliseconds(context: Context): number {
  const value = Number(context.config.pollIntervalSeconds);
  return Math.round((Number.isFinite(value) && value >= 0.5 ? value : DEFAULT_POLL_SECONDS) * 1000);
}

function deadlineOf(context: Context): number {
  const value = Number(context.config.timeoutMinutes);
  return Date.now() + (Number.isFinite(value) && value >= 1 ? Math.min(240, value) : DEFAULT_TIMEOUT_MINUTES) * 60_000;
}

function wait(context: Context, ms: number): Promise<void> {
  context.signal?.throwIfAborted();
  return new Promise((resolve, reject) => {
    const abort = () => { clearTimeout(timer); reject(context.signal?.reason || new DOMException("已取消", "AbortError")); };
    const timer = setTimeout(() => { context.signal?.removeEventListener("abort", abort); resolve(); }, ms);
    context.signal?.addEventListener("abort", abort, { once: true });
  });
}

function outputMediaType(value: string, key: string): MediaType | undefined {
  const lower = value.toLowerCase();
  if (key === "audio" || key === "audios" || /\.(mp3|wav|flac|ogg|m4a|opus)(?:$|\?)/.test(lower)) return "audio";
  if (key === "videos" || /\.(mp4|webm|mov|mkv)(?:$|\?)/.test(lower)) return "video";
  if (key === "images" || key === "gifs" || /\.(png|jpe?g|webp|gif|avif|bmp)(?:$|\?)/.test(lower)) return "image";
}

function collectOutputs(history: Record<string, unknown>, baseUrl: string): OutputFile[] {
  const outputs = history.outputs && typeof history.outputs === "object" && !Array.isArray(history.outputs) ? history.outputs as Record<string, unknown> : {};
  const files: OutputFile[] = [];
  const seen = new Set<string>();
  for (const output of Object.values(outputs)) {
    if (!output || typeof output !== "object" || Array.isArray(output)) continue;
    for (const [key, entries] of Object.entries(output as Record<string, unknown>)) {
      if (!Array.isArray(entries)) continue;
      for (const entry of entries) {
        if (!entry || typeof entry !== "object" || Array.isArray(entry)) continue;
        const item = entry as Record<string, unknown>;
        const filename = typeof item.filename === "string" ? item.filename : "";
        const directUrl = typeof item.url === "string" ? item.url : "";
        const mediaType = outputMediaType(filename || directUrl, key);
        if (!mediaType) continue;
        const subfolder = typeof item.subfolder === "string" ? item.subfolder : "";
        const type = typeof item.type === "string" ? item.type : "output";
        const url = directUrl && /^https?:\/\//i.test(directUrl) ? directUrl
          : baseUrl + "/view?" + new URLSearchParams({ filename, subfolder, type }).toString();
        if (seen.has(url)) continue;
        seen.add(url);
        files.push({ filename, subfolder, type, mediaType, url });
      }
    }
  }
  return files;
}

async function readHistory(context: Context, baseUrl: string, promptId: string): Promise<Record<string, unknown> | undefined> {
  const response = await context.tool.fetch(baseUrl + "/history/" + encodeURIComponent(promptId), {
    headers: requestHeaders(context), signal: context.signal, redirect: "error",
  });
  if (!response.ok) throw new Error("ComfyUI 历史查询失败：HTTP " + response.status);
  const payload = await response.json() as Record<string, unknown>;
  const value = payload[promptId];
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
}

async function cancel(context: Context, baseUrl: string, promptId: string) {
  if (context.config.cancelRunning === false) return;
  try {
    // 只用实例公开的队列接口精确删除仍排队的 prompt；运行中任务宁可等待，
    // 也不能发送无 prompt_id 的全局 /interrupt 误伤同实例其他任务。
    const queueResponse = await context.tool.fetch(baseUrl + "/queue", {
      headers: requestHeaders(context), redirect: "error", signal: null,
    });
    if (!queueResponse.ok) return;
    const payload = await queueResponse.json() as Record<string, unknown>;
    const pending = Array.isArray(payload.queue_pending) ? payload.queue_pending : [];
    const queued = pending.some(item => Array.isArray(item) && item[1] === promptId);
    if (!queued) return;
    await context.tool.fetch(baseUrl + "/queue", {
      method: "POST", headers: requestHeaders(context, true), body: JSON.stringify({ delete: [promptId] }), redirect: "error", signal: null,
    });
  } catch { /* 取消是尽力而为；不会因为无法确认远端状态而覆盖最初的 AbortError。 */ }
}

async function awaitResult(context: Context, data: ComfyTaskData, baseUrl: string): Promise<MediaAsset[]> {
  const interval = pollMilliseconds(context);
  let deadline = Number.isFinite(data.deadline) ? data.deadline : deadlineOf(context);
  if (deadline <= Date.now()) deadline = Date.now() + 60_000;
  while (Date.now() <= deadline) {
    context.signal?.throwIfAborted();
    const history = await readHistory(context, baseUrl, data.promptId);
    if (history) {
      const status = history.status && typeof history.status === "object" ? history.status as Record<string, unknown> : {};
      if (status.status_str === "error") throw Object.assign(new Error("ComfyUI 任务执行失败"), { code: "MEDIA_TASK_FAILED" });
      if (status.completed === true) {
        const files = collectOutputs(history, baseUrl);
        const matching = files.filter(file => file.mediaType === data.mediaType);
        if (!matching.length) throw Object.assign(new Error("ComfyUI 任务完成但没有返回" + (data.mediaType === "image" ? "图片" : "视频")), { code: "MEDIA_TASK_FAILED" });
        const result: MediaAsset[] = [];
        for (const file of matching.slice(0, 8)) {
          const response = await context.tool.fetch(file.url, {
            headers: requestHeaders(context), signal: context.signal, redirect: "error",
          });
          if (!response.ok) throw new Error("ComfyUI /view 下载失败：HTTP " + response.status);
          result.push({
            mediaType: file.mediaType,
            type: "binary",
            data: new Uint8Array(await response.arrayBuffer()),
            mimeType: response.headers.get("content-type") || (file.mediaType === "image" ? "image/png" : "video/mp4"),
            name: file.filename || undefined,
          });
        }
        return result;
      }
    }
    await wait(context, interval);
  }
  throw Object.assign(new Error("ComfyUI 任务等待超时，任务可能仍在执行；已保存 promptId，可使用任务恢复继续查询"), { retryable: true });
}

function mediaRoutes(context: Context): MediaRoute[] {
  const raw = context.config.routes;
  if (typeof raw !== "string" || !raw.trim()) return [];
  let value: unknown;
  try { value = JSON.parse(raw); }
  catch (error) { throw new Error("工作流通道 JSON 无效：" + (error instanceof Error ? error.message : String(error))); }
  if (!Array.isArray(value)) throw new Error("工作流通道必须是 JSON 数组");
  return value.map((item, index) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) throw new Error(`第 ${index + 1} 个工作流通道格式无效`);
    const route = item as Record<string, unknown>;
    if (typeof route.id !== "string" || !route.id.trim()) throw new Error(`第 ${index + 1} 个工作流通道缺少模型 ID`);
    if (typeof route.label !== "string" || !route.label.trim()) throw new Error(`第 ${index + 1} 个工作流通道缺少名称`);
    if (!["textToImage", "imageEdit", "video"].includes(String(route.kind))) throw new Error(`第 ${index + 1} 个工作流通道类型无效`);
    return {
      id: route.id.trim(),
      label: route.label.trim(),
      kind: route.kind as MediaRoute["kind"],
      workflow: typeof route.workflow === "string" ? route.workflow : JSON.stringify(route.workflow ?? {}),
      mapping: typeof route.mapping === "string" ? route.mapping : JSON.stringify(route.mapping ?? {}),
      baseUrl: typeof route.baseUrl === "string" ? route.baseUrl : undefined,
      authHeaderName: typeof route.authHeaderName === "string" ? route.authHeaderName : undefined,
      authHeaderValue: typeof route.authHeaderValue === "string" ? route.authHeaderValue : undefined,
    };
  });
}

function routeFor(context: Context, model: string): MediaRoute | undefined {
  return mediaRoutes(context).find(route => route.id === model);
}

function contextForRoute(context: Context, route?: MediaRoute): Context {
  if (!route) return context;
  return {
    ...context,
    config: {
      ...context.config,
      ...(route.baseUrl?.trim() ? { baseUrl: route.baseUrl.trim() } : {}),
      ...(route.authHeaderName?.trim() ? { authHeaderName: route.authHeaderName.trim() } : {}),
      ...(route.authHeaderValue?.trim() ? { authHeaderValue: route.authHeaderValue.trim() } : {}),
    },
  };
}

function workflowForRoute(route: MediaRoute): Record<string, unknown> {
  if (!route.workflow.trim()) throw new Error(`请先为工作流通道“${route.label}”导入 ComfyUI 工作流 JSON`);
  let parsed: unknown;
  try { parsed = JSON.parse(route.workflow); }
  catch (error) { throw new Error(`工作流通道“${route.label}”的 JSON 无效：` + (error instanceof Error ? error.message : String(error))); }
  return cloneWorkflow(parsed);
}

function mappingForRoute(route: MediaRoute): WorkflowMapping {
  return parseJsonObject(route.mapping, `工作流通道“${route.label}”输入映射`) as WorkflowMapping;
}

function workflowFor(kind: "image" | "video", context: Context, imageEdit = false): Record<string, unknown> {
  const raw = kind === "video" ? context.config.videoWorkflow
    : imageEdit ? context.config.imageEditWorkflow || context.config.imageWorkflow
    : context.config.textToImageWorkflow || context.config.imageWorkflow;
  const label = kind === "video" ? "视频模型" : imageEdit ? "图像编辑" : "文生图";
  if (typeof raw !== "string" || !raw.trim()) throw new Error(`请先在供应商配置中填写${label}工作流 JSON`);
  let parsed: unknown;
  try { parsed = JSON.parse(raw); }
  catch (error) { throw new Error(label + "工作流 JSON 无效：" + (error instanceof Error ? error.message : String(error))); }
  return cloneWorkflow(parsed);
}

function mappingFor(kind: "image" | "video", context: Context, imageEdit = false): WorkflowMapping {
  const raw = kind === "video" ? context.config.videoMapping
    : imageEdit ? context.config.imageEditMapping || context.config.imageMapping
    : context.config.textToImageMapping || context.config.imageMapping;
  const label = kind === "video" ? "视频模型输入映射" : imageEdit ? "图像编辑输入映射" : "文生图输入映射";
  return parseJsonObject(raw, label) as WorkflowMapping;
}

function applyCommon(workflow: Record<string, unknown>, mapping: WorkflowMapping, request: ImageRequest | VideoRequest, context: Context) {
  applyTargets(workflow, mapping.prompt, request.prompt);
  const negative = request.other?.negativePrompt;
  if (typeof negative === "string" && negative.trim()) applyTargets(workflow, mapping.negativePrompt, negative);
  if (typeof request.ratio === "string" && request.ratio) applyTargets(workflow, mapping.ratio, request.ratio);
  const seed = Number(request.other?.seed);
  applyTargets(workflow, mapping.seed, Number.isFinite(seed) ? seed : Math.floor(Math.random() * 2_147_483_647));
  const steps = Number(request.other?.steps);
  if (Number.isFinite(steps) && steps > 0) applyTargets(workflow, mapping.steps, Math.round(steps));
  applyTargets(workflow, mapping.prefix, "solodrama_" + Date.now().toString(36));
  if (mapping.extra && typeof mapping.extra === "object") {
    for (const [field, target] of Object.entries(mapping.extra)) {
      if (Object.hasOwn(request.other || {}, field)) applyTargets(workflow, target, request.other![field]);
    }
  }
}

async function submitPrompt(context: Context, baseUrl: string, workflow: Record<string, unknown>): Promise<string> {
  const response = await context.tool.fetch(baseUrl + "/prompt", {
    method: "POST", headers: requestHeaders(context, true), redirect: "error", signal: context.signal,
    body: JSON.stringify({ prompt: workflow, client_id: "solodrama-local-" + crypto.randomUUID() }),
  });
  if (!response.ok) throw new Error("ComfyUI /prompt 提交失败：HTTP " + response.status);
  const payload = await response.json() as Record<string, unknown>;
  const promptId = typeof payload.prompt_id === "string" ? payload.prompt_id : "";
  if (!promptId) throw new Error("ComfyUI /prompt 响应缺少 prompt_id");
  return promptId;
}

function isLocalAddress(baseUrl: string): boolean {
  const host = new URL(baseUrl).hostname.toLowerCase();
  const ipv4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(host);
  const privateIpv4 = !!ipv4 && (
    Number(ipv4[1]) === 10
    || (Number(ipv4[1]) === 172 && Number(ipv4[2]) >= 16 && Number(ipv4[2]) <= 31)
    || (Number(ipv4[1]) === 192 && Number(ipv4[2]) === 168)
  );
  return host === "localhost" || host === "127.0.0.1" || host === "::1" || host.endsWith(".local")
    || privateIpv4 || host.startsWith("fc") || host.startsWith("fd") || host.startsWith("fe80:");
}

async function prepareImages(workflow: Record<string, unknown>, mapping: WorkflowMapping, inputs: MediaInput[] | undefined, context: Context, baseUrl: string, fillEmpty: boolean) {
  const slots = targets(mapping.images);
  if (!slots.length) return;
  const images = inputs?.length ? inputs : fillEmpty ? [{ type: "base64" as const, data: EMPTY_IMAGE_BASE64, mimeType: "image/png", name: "solodrama-empty.png" }] : [];
  if (!images.length) return;
  for (let index = 0; index < slots.length; index++) {
    const input = images[Math.min(index, images.length - 1)]!;
    applyTarget(workflow, slots[index]!, await uploadImage(context, baseUrl, input));
  }
}

export default {
  id: "solodramaComfy",
  label: "本地 ComfyUI",
  version: "3.0.0",
  icon: "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAGAAAABgCAIAAABt+uBvAAAACXBIWXMAABYlAAAWJQFJUiTwAAADXElEQVR42u3b20sUYRgGcP+NoiTNdA+6edjVXXXJ3eywq1m7rnvw1F1mICoilSX9AR0USYqM8qZuvMkiMzvRTeGNRZFGEZkVpWFmdMKieiGIoBJnfHdw3nngud5lf8zO+33PzJeQtCwNmScJIAAQgAAEIAABCEAAQgAEIAABCEAAAhCAEAABCEAAAtDfqQjm9J7ZMHxv2+h4UEUePA1evOIPl+cIBMpIs5y75Hv/I7b4zH6P1VQ5RAFZVpuH729l0fmV23fKRAH1nC5m1KFMfYrKAcrNTJ/5GuMFuvsoIAdob1shrw7lWM96OUADV/3sQJVRuxAg0yoz3S94dSY/RuhjhQBVxRzsl8+FIb+cdRDdLNiBdu8pFAKUvDyN1r7sQIV5Nv0BZadbY2FH3Q7n79TXOc/2bWLXYRzwGgH5irMGb5TQ8p/d4p/pPOrRE1Bjo+vtXFQbGgp917p8m26A6D818007HUpHl1c3dUfKClM8bsDzhO5o9KW6AaqudGhG83CivKkpn2aingqzk72KN+gvZysOHilqbS1YeBoaXKW+rHhcOHEHGnum+P9FP9golavXvVZFDUi9h1GA2g+4lQJRD22g0n7oZqlSoMOdHqMAUcH85ktEKVCgLMcoQNtrc5XqvHgXTllpmOdiKhr4vv7NBnpwOKp8AU3LPKMAFRXYVAz4vCU54OMCtL9dzoCPCxBVP2IGPD+QOck89VnOgOcHqqkWNeD5gU6cEjXg+YFUNGTNzflGAaIyWEXXtWunyyhAbfvUvIPw+FWItv4Lb8haWgpCAXtqokl/QAPXSjTrWEfGAm6nTWdANI+0rOiv39qiM6Anr0NaAtEGJdNs0ROQipZ+kbHbrHoCSk+1qCgSVYc6A/2tg+jJlH9jJnUXf86d/kFfPIBoUSrkRXLaSUxMV7AD1dbkCgGiNcvkhwivDnXe5mSTEKBIyM5++VCpIuesRle3lx2Iajk5QLTqZQeiYlcIkDM7g3/AjwflHIeiNoMd6FCHRw4Q/Rhenecz4SyrVQ5Qfb2TUWd6Lsp4EGxJAK1JNHEdBKPmiF56FHgkk/Zo3ce9xKTulCUNwfOX/bRloXcicGYVh3oBBCAAIQACEIAABCAAAQhACIAABCAAAQhAAAIQgJD/Av0EpG2086d7EQoAAAAASUVORK5CYII=",
  readme: "本地或局域网 ComfyUI 不计模型调用费。一个通道可配置多个命名工作流，分别用于文生图、图像编辑和视频模型；每条通道可直接导入 ComfyUI 界面工作流 JSON（自动转换为 API prompt），也兼容 API JSON，并可独立填写输入映射和实例地址。Krea2、Moss、Pika 加速 H3、H3 图片及 H3 视频等工作流均可使用。",
  rules,
  models: [
    {
      id: "solodramaComfyImage",
      label: "ComfyUI 图片工作流",
      type: "image",
      mode: ["text", "singleImage", "multiReference"],
      imageSizes: ["1024x1024", "1280x720", "720x1280", "1536x1024", "1024x1536"],
      imageRatios: ["1:1", "4:3", "3:4", "16:9", "9:16", "3:2", "2:3"],
    },
    {
      id: "solodramaComfyH3",
      label: "ComfyUI H3 视频（六参考图槽）",
      type: "video",
      mode: ["text", "singleImage", "endFrameOptional", ["imageReference:6"]],
      audio: "optional",
      imageRatios: ["adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"],
      durationResolutionMap: [{ duration: [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30], resolution: ["480P", "768P", "1080P", "2K", "4K"] }],
    },
  ] satisfies ProviderModel[],
  async getPrice(this: Context, request: { type: string; model: string; other?: Record<string, unknown> }) {
    const routeContext = contextForRoute(this, routeFor(this, request.model));
    const baseUrl = normalizeBaseUrl(routeContext.config.baseUrl);
    return isLocalAddress(baseUrl)
      ? { price: "¥0（本地）", tips: "本地 ComfyUI 不计模型调用费；电费和自有设备折旧未计入。" }
      : { price: "未知", tips: "云端 ComfyUI 实例费用取决于服务商，接口未返回金额；不会显示为 0。" };
  },
  async generateImage(this: Context, request: ImageRequest): Promise<MediaAsset[]> {
    const route = routeFor(this, request.model);
    const routeContext = contextForRoute(this, route);
    const baseUrl = normalizeBaseUrl(routeContext.config.baseUrl);
    if (!isLocalAddress(baseUrl) && request.other?.allowUnknownCostSubmit !== true) {
      throw new Error("云端 ComfyUI 费用未知；请先在当前模型设置中明确开启“云端费用未知时仍允许提交”");
    }
    if (route && route.kind === "video") throw new Error(`工作流通道“${route.label}”是视频模型，不能用于图片生成`);
    const imageEdit = route ? route.kind === "imageEdit" : !!(request.images?.length || request.mask);
    const workflow = route ? workflowForRoute(route) : workflowFor("image", routeContext, imageEdit);
    const mapping = route ? mappingForRoute(route) : mappingFor("image", routeContext, imageEdit);
    applyCommon(workflow, mapping, request, routeContext);
    if (request.size && mapping.size) applyTarget(workflow, targets(mapping.size)[0]!, request.size);
    if (request.size && mapping.width && mapping.height) {
      const match = /^(\d+)x(\d+)$/i.exec(request.size);
      if (match) { applyTarget(workflow, targets(mapping.width)[0]!, Number(match[1])); applyTarget(workflow, targets(mapping.height)[0]!, Number(match[2])); }
    }
    await prepareImages(workflow, mapping, request.images, routeContext, baseUrl, false);
    const data: ComfyTaskData = { kind: "solodramaComfy", mediaType: "image", promptId: "", deadline: deadlineOf(routeContext), baseUrl };
    try {
      data.promptId = await submitPrompt(routeContext, baseUrl, workflow);
      await routeContext.saveTaskData?.(data);
      return await awaitResult(routeContext, data, baseUrl);
    } catch (error) {
      if (routeContext.signal?.aborted && data.promptId) await cancel(routeContext, baseUrl, data.promptId);
      throw error;
    }
  },
  async generateVideo(this: Context, request: VideoRequest): Promise<MediaAsset[]> {
    const route = routeFor(this, request.model);
    const routeContext = contextForRoute(this, route);
    const baseUrl = normalizeBaseUrl(routeContext.config.baseUrl);
    if (!isLocalAddress(baseUrl) && request.other?.allowUnknownCostSubmit !== true) {
      throw new Error("云端 ComfyUI 费用未知；请先在当前模型设置中明确开启“云端费用未知时仍允许提交”");
    }
    if (route && route.kind !== "video") throw new Error(`工作流通道“${route.label}”不是视频模型`);
    const workflow = route ? workflowForRoute(route) : workflowFor("video", routeContext);
    const mapping = route ? mappingForRoute(route) : mappingFor("video", routeContext);
    applyCommon(workflow, mapping, request, routeContext);
    if (request.duration !== undefined) applyTargets(workflow, mapping.duration, request.duration);
    if (request.ratio) applyTargets(workflow, mapping.ratio, request.ratio);
    const images = request.images?.length ? request.images : request.firstFrame ? [request.firstFrame, ...(request.lastFrame ? [request.lastFrame] : [])] : [];
    await prepareImages(workflow, mapping, images, routeContext, baseUrl, true);
    const data: ComfyTaskData = { kind: "solodramaComfy", mediaType: "video", promptId: "", deadline: deadlineOf(routeContext), baseUrl };
    try {
      data.promptId = await submitPrompt(routeContext, baseUrl, workflow);
      await routeContext.saveTaskData?.(data);
      return await awaitResult(routeContext, data, baseUrl);
    } catch (error) {
      if (routeContext.signal?.aborted && data.promptId) await cancel(routeContext, baseUrl, data.promptId);
      throw error;
    }
  },
  async resumeTask(this: Context, data: ProviderTaskData): Promise<MediaAsset[]> {
    if (data.kind !== "solodramaComfy" || (data.mediaType !== "image" && data.mediaType !== "video")
      || typeof data.promptId !== "string" || !data.promptId || typeof data.deadline !== "number" || !Number.isFinite(data.deadline)) {
      throw new Error("ComfyUI 任务恢复数据无效");
    }
    const task = data as ComfyTaskData;
    return awaitResult(this, task, normalizeBaseUrl(task.baseUrl || this.config.baseUrl));
  },
};