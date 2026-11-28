/**
 * SoloDrama RunningHub Provider
 *
 * 仅使用 RunningHub AI App 协议；一个通道可配置多个独立 AI 应用。
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
};
type ProviderModel = {
  id: string;
  label: string;
  type: "text" | "image" | "video" | "audio";
  mode?: (string | string[])[];
  audio?: "optional" | boolean;
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
  ratio?: string;
  size?: string;
  other?: Record<string, unknown>;
};
type VideoRequest = {
  model: string;
  prompt: string;
  images?: MediaInput[];
  firstFrame?: MediaInput;
  lastFrame?: MediaInput;
  duration?: number;
  ratio?: string;
  resolution?: string;
  generateAudio?: boolean;
  other?: Record<string, unknown>;
};
type AudioRequest = {
  model: string;
  prompt: string;
  images?: MediaInput[];
  audios?: MediaInput[];
  voice?: string;
  language?: string;
  format?: string;
  sampleRate?: number;
  speed?: number;
  volume?: number;
  pitch?: number;
  other?: Record<string, unknown>;
};
type Target = { nodeId: string; fieldName: string };
type InputMapping = Record<string, Target | Target[] | undefined> & {
  prompt?: Target | Target[];
  negativePrompt?: Target | Target[];
  images?: Target | Target[];
  duration?: Target | Target[];
  ratio?: Target | Target[];
  resolution?: Target | Target[];
  generateAudio?: Target | Target[];
  extra?: Record<string, Target | Target[]>;
};
type OutputMapping = {
  resultIndex?: number | null;
  outputType?: string;
  nodeId?: string;
  urlKey?: string;
  typeKey?: string;
};
type AiAppRoute = {
  id: string;
  label: string;
  type: "image" | "video" | "audio";
  webappId: string;
  nodeInfoList?: string;
  inputMapping?: string;
  outputMapping?: string;
  imageValue?: "fileName" | "url";
};
type Context = {
  config: {
    apiKey?: string;
    site?: string;
    baseUrl?: string;
    aiApps?: string;
    imageValue?: string;
    pollIntervalSeconds?: number;
    timeoutMinutes?: number;
    estimateText?: string;
    estimateTips?: string;
  };
  signal?: AbortSignal;
  saveTaskData?: (data: ProviderTaskData) => Promise<void>;
  tool: {
    fetch: typeof fetch;
    errorMessage(value: unknown): string;
  };
};
type RunningHubTaskData = {
  kind: "solodramaRunningHub";
  taskId: string;
  routeId: string;
  mediaType: "image" | "video" | "audio";
  deadline: number;
};
type QueryResult = { status: string; results: { url: string; outputType?: string; nodeId?: string }[]; usage?: Record<string, unknown>; raw: Record<string, unknown> };
class RunningHubRequestError extends Error {
  status: number;
  code: string;
  constructor(message: string, status = 0, code = "") {
    super(message);
    this.name = "RunningHubRequestError";
    this.status = status;
    this.code = code;
  }
}

const DEFAULT_POLL_SECONDS = 5;
const DEFAULT_TIMEOUT_MINUTES = 30;
const SITES: Record<string, string> = {
  cn: "https://www.runninghub.cn",
  ai: "https://www.runninghub.ai",
};
const DEFAULT_AI_APPS = JSON.stringify([
  {
    id: "rhAiAppImage",
    label: "RunningHub AI App · 图片",
    type: "image",
    webappId: "",
    nodeInfoList: "[]",
    inputMapping: `{
  "prompt": [],
  "images": [],
  "ratio": [],
  "extra": {}
}`,
    outputMapping: "{}",
    imageValue: "fileName",
  },
  {
    id: "rhAiAppVideo",
    label: "RunningHub AI App · 视频",
    type: "video",
    webappId: "",
    nodeInfoList: "[]",
    inputMapping: `{
  "prompt": [],
  "images": [],
  "duration": [],
  "ratio": [],
  "resolution": [],
  "generateAudio": [],
  "extra": {}
}`,
    outputMapping: "{}",
    imageValue: "fileName",
  },
], null, 2);

const rules = [
  {
    type: "input",
    field: "apiKey",
    title: "RunningHub API Key",
    value: "",
    props: { type: "password", showPassword: true, autocomplete: "off" },
  },
  {
    type: "select",
    field: "site",
    title: "站点",
    value: "cn",
    options: [
      { label: "国内站 .cn", value: "cn" },
      { label: "国际站 .ai", value: "ai" },
    ],
  },
  {
    type: "input",
    field: "baseUrl",
    title: "自定义 API 地址（可选）",
    value: "",
    props: { placeholder: "留空使用站点选择；测试或代理环境可填写完整 HTTP(S) 地址" },
  },
  {
    type: "textarea",
    field: "aiApps",
    title: "AI 应用通道",
    value: `[{"id":"rhAiAppImage","label":"RunningHub AI App · 图片","type":"image","webappId":"","nodeInfoList":[],"inputMapping":{"prompt":[],"images":[],"ratio":[],"extra":{}},"outputMapping":{},"imageValue":"fileName"},{"id":"rhAiAppVideo","label":"RunningHub AI App · 视频","type":"video","webappId":"","nodeInfoList":[],"inputMapping":{"prompt":[],"images":[],"duration":[],"ratio":[],"resolution":[],"generateAudio":[],"extra":{}},"outputMapping":{},"imageValue":"fileName"},{"id":"rhAiAppAudio","label":"RunningHub AI App · 音频","type":"audio","webappId":"","nodeInfoList":[],"inputMapping":{"prompt":[],"extra":{}},"outputMapping":{},"imageValue":"fileName"}]`,
    props: { rows: 10, placeholder: "由 AI 应用通道编辑器维护" },
  },
  {
    type: "select",
    field: "imageValue",
    title: "参考图写入默认值",
    value: "fileName",
    options: [
      { label: "上传后的 fileName", value: "fileName" },
      { label: "上传后的下载 URL", value: "url" },
    ],
  },
  {
    type: "inputNumber",
    field: "pollIntervalSeconds",
    title: "轮询间隔（秒）",
    value: 5,
    props: { min: 1, max: 60, step: 1 },
  },
  {
    type: "inputNumber",
    field: "timeoutMinutes",
    title: "任务等待上限（分钟）",
    value: 30,
    props: { min: 1, max: 240, step: 1 },
  },
  {
    type: "input",
    field: "estimateText",
    title: "可选预估价格文本",
    value: "",
    props: { placeholder: "RunningHub 无公开 estimate API；留空时显示“未知”，不会显示为 0" },
  },
  {
    type: "input",
    field: "estimateTips",
    title: "预估价格说明",
    value: "RunningHub 未返回金额；以平台实际结算为准。",
  },
] as const;

function apiKeyOf(context: Context): string {
  const key = typeof context.config.apiKey === "string" ? context.config.apiKey.trim().replace(/^Bearer\s+/i, "") : "";
  if (!key) throw new Error("请先在供应商配置中填写 RunningHub API Key");
  return key;
}

function baseUrlOf(context: Context): string {
  const custom = typeof context.config.baseUrl === "string" ? context.config.baseUrl.trim().replace(/\/+$/, "") : "";
  if (custom) {
    const url = new URL(custom);
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) throw new Error("RunningHub 自定义 API 地址必须是无内嵌凭据的 HTTP(S) URL");
    return url.toString().replace(/\/+$/, "");
  }
  const site = typeof context.config.site === "string" ? context.config.site.trim().toLowerCase() : "cn";
  return SITES[site] || SITES.cn!;
}

function headersOf(context: Context, json = false): Record<string, string> {
  return { Authorization: "Bearer " + apiKeyOf(context), Accept: "application/json", ...(json ? { "Content-Type": "application/json" } : {}) };
}

function pollMs(context: Context): number {
  const value = Number(context.config.pollIntervalSeconds);
  return Math.round((Number.isFinite(value) && value >= 1 ? Math.min(60, value) : DEFAULT_POLL_SECONDS) * 1000);
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

function parseObject(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "string" || !value.trim()) return {};
  try {
    const parsed: unknown = JSON.parse(value);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("必须是 JSON 对象");
    return parsed as Record<string, unknown>;
  } catch (error) {
    throw new Error(label + " 无效：" + (error instanceof Error ? error.message : String(error)));
  }
}

function appsOf(context: Context): AiAppRoute[] {
  const raw = context.config.aiApps;
  let parsed: unknown;
  try { parsed = JSON.parse(typeof raw === "string" && raw.trim() ? raw : DEFAULT_AI_APPS); }
  catch (error) { throw new Error("AI 应用通道 JSON 无效：" + (error instanceof Error ? error.message : String(error))); }
  if (!Array.isArray(parsed)) throw new Error("AI 应用通道必须是 JSON 数组");
  return parsed.map((item, index) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) throw new Error(`第 ${index + 1} 个 AI 应用通道格式无效`);
    const value = item as Record<string, unknown>;
    const id = typeof value.id === "string" ? value.id.trim() : "";
    const label = typeof value.label === "string" ? value.label.trim() : "";
    const type = value.type;
    const webappId = typeof value.webappId === "string" ? value.webappId.trim() : String(value.webappId ?? "").trim();
    if (!id || !label) throw new Error(`第 ${index + 1} 个 AI 应用通道缺少 ID 或名称`);
    if (!["image", "video", "audio"].includes(String(type))) throw new Error(`AI 应用通道“${label}”的类型无效`);
    if (!/^\d+$/.test(webappId)) throw new Error(`AI 应用通道“${label}”的 webappId / appId 必须是数字`);
    return {
      id, label, type: type as AiAppRoute["type"], webappId,
      ...(value.nodeInfoList !== undefined ? { nodeInfoList: typeof value.nodeInfoList === "string" ? value.nodeInfoList : JSON.stringify(value.nodeInfoList) } : {}),
      ...(value.inputMapping !== undefined ? { inputMapping: typeof value.inputMapping === "string" ? value.inputMapping : JSON.stringify(value.inputMapping) } : {}),
      ...(value.outputMapping !== undefined ? { outputMapping: typeof value.outputMapping === "string" ? value.outputMapping : JSON.stringify(value.outputMapping) } : {}),
      imageValue: value.imageValue === "url" ? "url" : "fileName",
    };
  });
}

function appFor(context: Context, model: string, expected: AiAppRoute["type"]): AiAppRoute {
  const app = appsOf(context).find(item => item.id === model);
  if (!app) throw new Error(`AI 应用通道不存在：${model}`);
  if (app.type !== expected) throw new Error(`AI 应用通道“${app.label}”不是${expected === "image" ? "图片" : expected === "video" ? "视频" : "音频"}模型`);
  return app;
}

function normalizeTarget(value: unknown, label: string): Target | undefined {
  if (value === undefined || value === null || Array.isArray(value)) return undefined;
  if (!value || typeof value !== "object") throw new Error(label + " 必须填写 nodeId 和 fieldName");
  const item = value as Record<string, unknown>;
  if (typeof item.nodeId !== "string" || !item.nodeId.trim() || typeof item.fieldName !== "string" || !item.fieldName.trim()) {
    throw new Error(label + " 必须填写非空 nodeId 和 fieldName");
  }
  return { nodeId: item.nodeId.trim(), fieldName: item.fieldName.trim() };
}

function targetList(value: unknown, label: string): Target[] {
  if (value === undefined) return [];
  if (Array.isArray(value)) return value.map((item, index) => normalizeTarget(item, label + "[" + index + "]")!).filter(Boolean);
  const item = normalizeTarget(value, label);
  return item ? [item] : [];
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

async function upload(context: Context, input: MediaInput): Promise<{ fileName: string; url: string }> {
  const media = await mediaBytes(input, context);
  const extension = media.mimeType.split("/")[1]?.replace("jpeg", "jpg").replace(/[^a-z0-9]/gi, "") || "bin";
  const name = (media.name || "reference").replace(/\.[^.]+$/, "").replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 80) || "reference";
  const form = new FormData();
  form.append("file", new Blob([media.data.slice().buffer as ArrayBuffer], { type: media.mimeType }), name + "." + extension);
  const response = await context.tool.fetch(baseUrlOf(context) + "/openapi/v2/media/upload/binary", {
    method: "POST", headers: headersOf(context), body: form, signal: context.signal, redirect: "error",
  });
  const payload = await response.json().catch(() => ({})) as Record<string, unknown>;
  if (!response.ok) throw new Error("RunningHub 文件上传失败：HTTP " + response.status);
  const data = payload.data && typeof payload.data === "object" ? payload.data as Record<string, unknown> : payload;
  const fileName = typeof data.fileName === "string" ? data.fileName : "";
  const url = typeof data.download_url === "string" ? data.download_url : typeof data.url === "string" ? data.url : "";
  if (!fileName && !url) throw new Error("RunningHub 上传响应缺少 fileName/download_url");
  return { fileName, url };
}

function dedupeNodes(nodes: { nodeId?: unknown; fieldName?: unknown; fieldValue?: unknown; value?: unknown }[]) {
  const seen = new Set<string>();
  const result: { nodeId: string; fieldName: string; fieldValue: string }[] = [];
  for (const node of nodes) {
    const nodeId = typeof node.nodeId === "string" ? node.nodeId.trim() : "";
    const fieldName = typeof node.fieldName === "string" ? node.fieldName.trim() : "";
    if (!nodeId || !fieldName) continue;
    const key = nodeId + "\0" + fieldName;
    if (seen.has(key)) continue;
    seen.add(key);
    const value = node.fieldValue !== undefined ? node.fieldValue : node.value;
    if (value === undefined) continue;
    result.push({ nodeId, fieldName, fieldValue: typeof value === "string" ? value : JSON.stringify(value) });
  }
  return result;
}

function findNodeInfoList(value: unknown, depth = 0): unknown[] | undefined {
  if (depth > 8 || value === null || value === undefined) return undefined;
  if (Array.isArray(value)) {
    if (value.some(item => item && typeof item === "object" && !Array.isArray(item)
      && typeof (item as Record<string, unknown>).nodeId === "string"
      && typeof (item as Record<string, unknown>).fieldName === "string")) return value;
    for (const item of value) {
      const found = findNodeInfoList(item, depth + 1);
      if (found) return found;
    }
    return undefined;
  }
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (!trimmed || !/^[\[{]/.test(trimmed)) return undefined;
    try { return findNodeInfoList(JSON.parse(trimmed), depth + 1); }
    catch { return undefined; }
  }
  if (typeof value !== "object") return undefined;
  const record = value as Record<string, unknown>;
  if (Array.isArray(record.nodeInfoList)) return record.nodeInfoList;
  for (const item of Object.values(record)) {
    const found = findNodeInfoList(item, depth + 1);
    if (found) return found;
  }
  return undefined;
}

async function fetchApiCallDemo(context: Context, app: AiAppRoute): Promise<unknown[]> {
  const url = new URL(baseUrlOf(context) + "/api/webapp/apiCallDemo");
  url.searchParams.set("apiKey", apiKeyOf(context));
  url.searchParams.set("webappId", app.webappId);
  const response = await context.tool.fetch(url, { headers: headersOf(context), signal: context.signal, redirect: "error" });
  const payload = await response.json().catch(() => ({})) as Record<string, unknown>;
  if (!response.ok) throw new RunningHubRequestError("读取 RunningHub AI 应用字段失败：HTTP " + response.status + "：" + context.tool.errorMessage(payload), response.status);
  const code = payload.code ?? payload.errorCode;
  if (code !== undefined && !["0", "200"].includes(String(code))) {
    throw new RunningHubRequestError(friendly(code, String(payload.msg ?? payload.message ?? "读取 AI 应用字段失败")), response.status, String(code));
  }
  const nodes = findNodeInfoList(payload);
  if (!nodes?.length) throw new Error(`RunningHub AI 应用“${app.label}”没有返回可调用的字段配置`);
  return nodes;
}

function isImageUploadField(node: Record<string, unknown>) {
  const fieldName = String(node.fieldName ?? "").toLowerCase();
  const nodeName = String(node.nodeName ?? "").toLowerCase();
  const fieldData = typeof node.fieldData === "string" ? node.fieldData.toLowerCase() : JSON.stringify(node.fieldData ?? {}).toLowerCase();
  return fieldData.includes("image_upload")
    || nodeName.includes("loadimage")
    || /^(image|image_\d+|reference_image|start_image|end_image|init_image)$/.test(fieldName);
}

function isPromptField(node: Record<string, unknown>) {
  const fieldName = String(node.fieldName ?? "").toLowerCase();
  const nodeName = String(node.nodeName ?? "").toLowerCase();
  const description = String(node.description ?? "");
  if (/negative|负面|负向/.test(fieldName + " " + nodeName + " " + description)) return false;
  return ["text", "prompt", "positive_prompt", "positiveprompt"].includes(fieldName)
    || (nodeName.includes("cliptextencode") && fieldName === "text")
    || (/提示词|正向提示/.test(description) && !isImageUploadField(node));
}

async function autoNodeInfoListOf(context: Context, app: AiAppRoute, request: ImageRequest | VideoRequest) {
  const template = await fetchApiCallDemo(context, app);
  const nodes = template.flatMap(item => item && typeof item === "object" && !Array.isArray(item) ? [{ ...(item as Record<string, unknown>) }] : []);
  const promptFields = nodes.filter(isPromptField);
  for (const node of promptFields) node.fieldValue = request.prompt;
  const imageFields = nodes.filter(isImageUploadField);
  const images = request.images?.length ? request.images : "firstFrame" in request && request.firstFrame
    ? [request.firstFrame, ...(request.lastFrame ? [request.lastFrame] : [])] : [];
  if (images.length && !imageFields.length) throw new Error(`RunningHub AI 应用“${app.label}”没有可用的参考图字段`);
  for (let index = 0; index < Math.min(images.length, imageFields.length); index++) {
    const uploaded = await upload(context, images[index]!);
    const value = (app.imageValue ?? context.config.imageValue) === "url" ? uploaded.url : uploaded.fileName;
    if (!value) throw new Error("RunningHub 上传结果缺少所选 reference 写入值");
    imageFields[index]!.fieldValue = value;
  }
  return dedupeNodes(nodes);
}

async function nodeInfoListOf(context: Context, app: AiAppRoute, request: ImageRequest | VideoRequest): Promise<ReturnType<typeof dedupeNodes>> {
  const hasLegacyMapping = !!(app.nodeInfoList?.trim() || app.inputMapping?.trim());
  if (!hasLegacyMapping) return autoNodeInfoListOf(context, app, request);
  const mapping = parseObject(app.inputMapping, `AI 应用通道“${app.label}”输入映射`) as InputMapping;
  const dynamic: { nodeId?: unknown; fieldName?: unknown; fieldValue?: unknown }[] = [];
  const add = (targetValue: unknown, value: unknown, label: string) => {
    if (value === undefined || value === null || value === "") return;
    for (const target of targetList(targetValue, label)) dynamic.push({ ...target, fieldValue: value });
  };
  add(mapping.prompt, request.prompt, "prompt");
  add(mapping.negativePrompt, request.other?.negativePrompt, "negativePrompt");
  if ("duration" in request) add(mapping.duration, request.duration, "duration");
  add(mapping.ratio, request.ratio, "ratio");
  if ("resolution" in request) add(mapping.resolution, request.resolution, "resolution");
  if ("generateAudio" in request) add(mapping.generateAudio, request.generateAudio, "generateAudio");
  if (mapping.extra && typeof mapping.extra === "object") {
    for (const [field, targetValue] of Object.entries(mapping.extra)) {
      if (Object.hasOwn(request.other || {}, field)) add(targetValue, request.other![field], "extra." + field);
    }
  }
  const images = request.images?.length ? request.images : "firstFrame" in request && request.firstFrame ? [request.firstFrame, ...(request.lastFrame ? [request.lastFrame] : [])] : [];
  const imageTargets = targetList(mapping.images, "images");
  for (let index = 0; index < Math.min(images.length, imageTargets.length); index++) {
    const uploaded = await upload(context, images[index]!);
    const value = (app.imageValue ?? context.config.imageValue) === "url" ? uploaded.url : uploaded.fileName;
    if (!value) throw new Error("RunningHub 上传结果缺少所选 reference 写入值");
    dynamic.push({ ...imageTargets[index]!, fieldValue: value });
  }
  let parsedStatic: unknown = [];
  if (app.nodeInfoList?.trim()) {
    try { parsedStatic = JSON.parse(app.nodeInfoList); }
    catch (error) { throw new Error(`AI 应用通道“${app.label}”固定 nodeInfoList JSON 无效：` + (error instanceof Error ? error.message : String(error))); }
  }
  if (!Array.isArray(parsedStatic)) throw new Error(`AI 应用通道“${app.label}”固定 nodeInfoList 必须是 JSON 数组`);
  return dedupeNodes([...dynamic, ...parsedStatic as Record<string, unknown>[]]);
}

function friendly(code: unknown, message: string): string {
  const value = String(code ?? "");
  const hints: Record<string, string> = {
    "421": "单账号并发队列已满，请稍后重试；不要重复创建新任务。",
    "805": "显存不足，任务未完成。",
    "1014": "该 API 类型不接收当前 Key，请检查消费级/企业级 Key 类型。",
    "1602": "查询请求缺少 Bearer API Key。",
  };
  return [message, hints[value]].filter(Boolean).join("\n");
}

async function requestJson(context: Context, path: string, body: Record<string, unknown>, json = true, signal: AbortSignal | null = context.signal ?? null): Promise<Record<string, unknown>> {
  const response = await context.tool.fetch(baseUrlOf(context) + path, {
    method: "POST", headers: headersOf(context, json), body: JSON.stringify(body), signal, redirect: "error",
  });
  const payload = await response.json().catch(() => ({})) as Record<string, unknown>;
  if (!response.ok) throw new RunningHubRequestError("RunningHub HTTP " + response.status + "：" + context.tool.errorMessage(payload), response.status);
  const code = payload.code ?? payload.errorCode;
  if (code !== undefined && !["0", "200"].includes(String(code))) {
    throw new RunningHubRequestError(friendly(code, String(payload.msg ?? payload.message ?? payload.errorMessage ?? "RunningHub 请求失败")), response.status, String(code));
  }
  return payload;
}

function taskIdOf(payload: Record<string, unknown>): string {
  const data = payload.data && typeof payload.data === "object" ? payload.data as Record<string, unknown> : {};
  const taskId = payload.taskId ?? data.taskId;
  if (typeof taskId !== "string" && typeof taskId !== "number") throw new Error("RunningHub 提交响应缺少 taskId");
  return String(taskId);
}

async function submit(context: Context, app: AiAppRoute, nodes: ReturnType<typeof dedupeNodes>): Promise<string> {
  const payload = await requestJson(context, "/task/openapi/ai-app/run", {
    apiKey: apiKeyOf(context),
    webappId: Number(app.webappId),
    nodeInfoList: nodes,
  });
  return taskIdOf(payload);
}

async function query(context: Context, taskId: string): Promise<QueryResult> {
  let payload: Record<string, unknown>;
  try {
    payload = await requestJson(context, "/openapi/v2/query", { taskId });
  } catch (error) {
    if (!(error instanceof RunningHubRequestError) || ![404, 405].includes(error.status)) throw error;
    payload = await requestJson(context, "/task/openapi/outputs", { apiKey: apiKeyOf(context), taskId });
  }
  const data = Array.isArray(payload.data)
    ? { outputs: payload.data, status: "SUCCESS" }
    : payload.data && typeof payload.data === "object" ? payload.data as Record<string, unknown> : payload;
  const status = String(data.status ?? data.taskStatus ?? (Array.isArray(payload.data) ? "SUCCESS" : "UNKNOWN")).toUpperCase();
  const rawResults = Array.isArray(data.results) ? data.results : Array.isArray(data.fileList) ? data.fileList : Array.isArray(data.outputs) ? data.outputs : [];
  const results = rawResults.flatMap(item => {
    if (typeof item === "string" && /^https?:\/\//i.test(item)) return [{ url: item }];
    if (!item || typeof item !== "object" || Array.isArray(item)) return [];
    const record = item as Record<string, unknown>;
    const url = record.url ?? record.outputUrl ?? record.fileUrl;
    if (typeof url !== "string" || !/^https?:\/\//i.test(url)) return [];
    return [{ url, outputType: typeof record.outputType === "string" ? record.outputType : typeof record.fileType === "string" ? record.fileType : undefined, nodeId: typeof record.nodeId === "string" ? record.nodeId : undefined }];
  });
  return { status, results, usage: data.usage && typeof data.usage === "object" ? data.usage as Record<string, unknown> : {}, raw: payload };
}

function inferType(result: { outputType?: string; url: string }, expected: MediaType): boolean {
  const type = (result.outputType || "").toLowerCase();
  const url = result.url.toLowerCase();
  if (expected === "video") return type.startsWith("video") || type === "mp4" || /\.(mp4|webm|mov|mkv)(?:$|\?)/.test(url);
  if (expected === "audio") return type.startsWith("audio") || type === "mp3" || /\.(mp3|wav|flac|ogg|m4a|opus)(?:$|\?)/.test(url);
  return type.startsWith("image") || type === "png" || type === "jpg" || /\.(png|jpe?g|webp|gif|avif|bmp)(?:$|\?)/.test(url);
}

async function download(context: Context, url: string, expected: MediaType): Promise<MediaAsset> {
  const host = new URL(url).hostname.toLowerCase();
  const headers: Record<string, string> = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0 Safari/537.36",
    Referer: baseUrlOf(context) + "/",
    Accept: expected === "image" ? "image/*,*/*;q=0.8" : expected === "video" ? "video/*,*/*;q=0.8" : "audio/*,*/*;q=0.8",
  };
  if (host.includes("runninghub")) headers.Authorization = "Bearer " + apiKeyOf(context);
  const response = await context.tool.fetch(url, { headers, signal: context.signal, redirect: "follow" });
  if (!response.ok) throw new Error("RunningHub 输出下载失败：HTTP " + response.status);
  return {
    mediaType: expected, type: "binary", data: new Uint8Array(await response.arrayBuffer()),
    mimeType: response.headers.get("content-type") || (expected === "image" ? "image/png" : expected === "video" ? "video/mp4" : "audio/mpeg"),
  };
}

async function awaitResult(context: Context, data: RunningHubTaskData): Promise<MediaAsset[]> {
  const app = appsOf(context).find(item => item.id === data.routeId);
  if (!app) throw new Error("RunningHub AI 应用通道已删除，无法恢复任务");
  const outputMapping = parseObject(app.outputMapping, `AI 应用通道“${app.label}”输出映射`) as OutputMapping;
  const deadline = Number.isFinite(data.deadline) ? data.deadline : deadlineOf(context);
  let lastStatus = "UNKNOWN";
  while (Date.now() <= deadline) {
    context.signal?.throwIfAborted();
    const result = await query(context, data.taskId);
    lastStatus = result.status;
    if (["FAILED", "FAIL", "CANCEL", "CANCELLED", "ERROR", "REJECTED", "EXPIRED"].includes(result.status)) {
      throw Object.assign(new Error("RunningHub 任务失败：" + (context.tool.errorMessage(result.raw) || lastStatus)), { code: "MEDIA_TASK_FAILED" });
    }
    if (["SUCCESS", "SUCCEEDED", "COMPLETED"].includes(result.status)) {
      let matches = result.results.filter(item => inferType(item, data.mediaType));
      if (outputMapping.outputType) matches = matches.filter(item => item.outputType === outputMapping.outputType);
      if (outputMapping.nodeId) matches = matches.filter(item => item.nodeId === outputMapping.nodeId);
      if (!matches.length) throw Object.assign(new Error("RunningHub 任务完成但没有返回可下载的输出 URL"), { code: "MEDIA_TASK_FAILED" });
      if (typeof outputMapping.resultIndex === "number") matches = [matches[outputMapping.resultIndex]].filter(Boolean) as typeof matches;
      return Promise.all(matches.slice(0, 8).map(item => download(context, item.url, data.mediaType)));
    }
    await wait(context, pollMs(context));
  }
  throw Object.assign(new Error("RunningHub 任务等待超时；taskId 已保存，可稍后恢复查询"), { retryable: true });
}

async function cancel(context: Context, taskId: string) {
  try {
    await requestJson(context, "/task/openapi/cancel", { apiKey: apiKeyOf(context), taskId }, true, null);
  } catch { /* 取消是尽力而为；不覆盖最初的 AbortError。 */ }
}

export default {
  id: "solodramaRunningHub",
  label: "RunningHub 工作流",
  icon: "data:image/x-icon;base64,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",
  version: "3.0.0",
  readme: "**获取 API Key**\n\n- [RunningHub 国内站](https://www.runninghub.cn?inviteCode=cn-v1122)\n- [RunningHub 国际站](https://www.runninghub.ai/zh-cn?inviteCode=rh-v1727) **宽审核**\n\nRunningHub 工作流通道使用 AI App 协议。一个通道可配置多个 AI 应用；每个应用只需填写自定义名称、类型和 webappId / appId。生成时会自动调用官方 apiCallDemo 读取字段，自动写入提示词和参考图，无需手动维护 nodeInfoList、输入映射或输出映射。保存后对应模型会同步出现在画布图片、视频或音频生成节点中。RunningHub 未返回可核验金额时显示“未知”，不会回退成 0。",
  rules,
  models: [
    {
      id: "rhAiAppImage", label: "RunningHub 工作流 · 图片", type: "image",
      mode: ["text", "singleImage", "multiReference"], imageRatios: ["1:1", "4:3", "3:4", "16:9", "9:16"],
      rules: [{ type: "switch", field: "allowUnknownCostSubmit", title: "费用未知时仍允许提交", value: false }],
    },
    {
      id: "rhAiAppVideo", label: "RunningHub 工作流 · 视频", type: "video",
      mode: ["text", "singleImage", "endFrameOptional", ["imageReference:6"]], audio: "optional",
      imageRatios: ["adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"],
      durationResolutionMap: [{ duration: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30], resolution: ["480P", "720P", "1080P"] }],
      rules: [{ type: "switch", field: "allowUnknownCostSubmit", title: "费用未知时仍允许提交", value: false }],
    },
    {
      id: "rhAiAppAudio", label: "RunningHub 工作流 · 音频", type: "audio",
      mode: ["text"],
      rules: [{ type: "switch", field: "allowUnknownCostSubmit", title: "费用未知时仍允许提交", value: false }],
    },
  ] satisfies ProviderModel[],
  async getPrice(this: Context) {
    const price = typeof this.config.estimateText === "string" ? this.config.estimateText.trim() : "";
    return price
      ? { price, tips: typeof this.config.estimateTips === "string" ? this.config.estimateTips : "以平台实际结算为准。" }
      : { price: "未知", tips: "RunningHub 没有公开 estimate 金额接口；费用不会显示为 0。" };
  },
  async getBalance(this: Context) {
    const payload = await requestJson(this, "/uc/openapi/accountStatus", { apikey: apiKeyOf(this) });
    const data = payload.data && typeof payload.data === "object" ? payload.data as Record<string, unknown> : payload;
    const money = Number(data.remainMoney);
    const coins = Number(data.remainCoins);
    if (Number.isFinite(money)) return { balance: money, unit: typeof data.currency === "string" && data.currency ? data.currency : "CNY", ...(Number.isFinite(coins) ? { keyBalance: coins } : {}) };
    if (Number.isFinite(coins)) return { balance: coins, unit: "RH币" };
    throw new Error("RunningHub accountStatus 未返回余额");
  },
  async generateImage(this: Context, request: ImageRequest): Promise<MediaAsset[]> {
    const app = appFor(this, request.model, "image");
    if (request.other?.allowUnknownCostSubmit !== true) throw new Error("RunningHub 费用未知；请先在当前模型设置中明确允许提交");
    const data: RunningHubTaskData = { kind: "solodramaRunningHub", taskId: "", routeId: app.id, mediaType: "image", deadline: deadlineOf(this) };
    try {
      data.taskId = await submit(this, app, await nodeInfoListOf(this, app, request));
      await this.saveTaskData?.(data);
      return await awaitResult(this, data);
    } catch (error) {
      if (this.signal?.aborted && data.taskId) await cancel(this, data.taskId);
      throw error;
    }
  },
  async generateVideo(this: Context, request: VideoRequest): Promise<MediaAsset[]> {
    const app = appFor(this, request.model, "video");
    if (request.other?.allowUnknownCostSubmit !== true) throw new Error("RunningHub 费用未知；请先在当前模型设置中明确允许提交");
    const data: RunningHubTaskData = { kind: "solodramaRunningHub", taskId: "", routeId: app.id, mediaType: "video", deadline: deadlineOf(this) };
    try {
      data.taskId = await submit(this, app, await nodeInfoListOf(this, app, request));
      await this.saveTaskData?.(data);
      return await awaitResult(this, data);
    } catch (error) {
      if (this.signal?.aborted && data.taskId) await cancel(this, data.taskId);
      throw error;
    }
  },
  async generateAudio(this: Context, request: AudioRequest): Promise<MediaAsset[]> {
    const app = appFor(this, request.model, "audio");
    if (request.other?.allowUnknownCostSubmit !== true) throw new Error("RunningHub 费用未知；请先在当前模型设置中明确允许提交");
    const data: RunningHubTaskData = { kind: "solodramaRunningHub", taskId: "", routeId: app.id, mediaType: "audio", deadline: deadlineOf(this) };
    try {
      data.taskId = await submit(this, app, await nodeInfoListOf(this, app, request as ImageRequest | VideoRequest));
      await this.saveTaskData?.(data);
      return await awaitResult(this, data);
    } catch (error) {
      if (this.signal?.aborted && data.taskId) await cancel(this, data.taskId);
      throw error;
    }
  },
  async resumeTask(this: Context, data: ProviderTaskData): Promise<MediaAsset[]> {
    if (data.kind !== "solodramaRunningHub" || typeof data.taskId !== "string" || !data.taskId
      || typeof data.routeId !== "string" || !data.routeId
      || !["image", "video", "audio"].includes(String(data.mediaType))
      || typeof data.deadline !== "number" || !Number.isFinite(data.deadline)) {
      throw new Error("RunningHub 任务恢复数据无效");
    }
    return awaitResult(this, data as RunningHubTaskData);
  },
};
