type MediaInput =
  | { type: "url"; url: string; mimeType?: string; name?: string }
  | { type: "base64"; data: string; mimeType: string; name?: string }
  | { type: "binary"; data: Uint8Array; mimeType: string; name?: string };
type MediaAsset = MediaInput & { mediaType: "image" | "video" };
type ImageRequest = {
  model: string;
  prompt: string;
  images?: MediaInput[];
  ratio?: string;
  size?: string;
  quality?: string;
  other?: Record<string, unknown>;
};
type ReferenceOrderItem =
  | { type: "text" }
  | { type: "firstFrame" | "lastFrame" }
  | { type: "image" | "video" | "audio"; index: number };
type VideoRequest = {
  model: string;
  prompt: string;
  mode?: string | string[];
  images?: MediaInput[];
  videos?: MediaInput[];
  audios?: MediaInput[];
  firstFrame?: MediaInput;
  lastFrame?: MediaInput;
  referenceOrder?: ReferenceOrderItem[];
  duration?: number;
  ratio?: string;
  resolution?: string;
  generateAudio?: boolean;
  watermark?: boolean;
  other?: Record<string, unknown>;
};
type Context = {
  config: {
    site?: string;
    apiKey?: string;
    pollIntervalSeconds?: number;
    timeoutMinutes?: number;
    estimateText?: string;
    estimateTips?: string;
  };
  signal?: AbortSignal;
  saveTaskData?: (data: ProviderTaskData) => Promise<void>;
  tool: { fetch: typeof fetch; errorMessage(value: unknown): string };
};
type ImageRoute = { id: string; textEndpoint: string; editEndpoint: string };
type VideoRoute = {
  id: string;
  variant: "v25" | "v20";
  textEndpoint: string;
  imageEndpoint: string;
  multimodalEndpoint: string;
  minDuration: number;
  maxDuration: number;
  maxImages: number;
  maxVideos: number;
  maxAudios: number;
  resolutions: string[];
};
type TaskData = {
  kind: "solodramaRunningHubClosed";
  taskId: string;
  mediaType: "image" | "video";
  model: string;
  endpoint: string;
  deadline: number;
};
type QueryResult = { status: string; results: { url: string; outputType?: string }[]; usage?: Record<string, unknown>; raw: Record<string, unknown> };

const SITES: Record<string, string> = { cn: "https://www.runninghub.cn", ai: "https://www.runninghub.ai" };
const IMAGE_ROUTES: Record<string, ImageRoute> = {
  gptImage26Flare: {
    id: "gptImage26Flare",
    textEndpoint: "/openapi/v2/rhart-image-g-2.6-official-token/flare/text-to-image",
    editEndpoint: "/openapi/v2/rhart-image-g-2.6-official-token/flare/image-to-image",
  },
};
const VIDEO_ROUTES: Record<string, VideoRoute> = {
  seedance25Flash: {
    id: "seedance25Flash",
    variant: "v25",
    textEndpoint: "/openapi/v2/bytedance/seedance-2.5-flash-token/text-to-video",
    imageEndpoint: "/openapi/v2/bytedance/seedance-2.5-flash-token/image-to-video",
    multimodalEndpoint: "/openapi/v2/bytedance/seedance-2.5-flash-token/multimodal-video",
    minDuration: 4,
    maxDuration: 30,
    maxImages: 10,
    maxVideos: 5,
    maxAudios: 5,
    resolutions: ["480p", "720p"],
  },
  seedance25: {
    id: "seedance25",
    variant: "v25",
    textEndpoint: "/openapi/v2/bytedance/seedance-2.5-token/text-to-video",
    imageEndpoint: "/openapi/v2/bytedance/seedance-2.5-token/image-to-video",
    multimodalEndpoint: "/openapi/v2/bytedance/seedance-2.5-token/multimodal-video",
    minDuration: 4,
    maxDuration: 30,
    maxImages: 30,
    maxVideos: 10,
    maxAudios: 10,
    resolutions: ["480p", "720p", "native1080p", "1080p", "2k", "4k"],
  },
  seedance20: {
    id: "seedance20",
    variant: "v20",
    textEndpoint: "/openapi/v2/rhart-video/sparkvideo-2.0/text-to-video",
    imageEndpoint: "/openapi/v2/rhart-video/sparkvideo-2.0/image-to-video",
    multimodalEndpoint: "/openapi/v2/rhart-video/sparkvideo-2.0/multimodal-video",
    minDuration: 4,
    maxDuration: 15,
    maxImages: 9,
    maxVideos: 3,
    maxAudios: 3,
    resolutions: ["480p", "720p", "native1080p", "native4k", "1080p", "2k", "4k"],
  },
};
const DEFAULT_POLL_SECONDS = 5;
const DEFAULT_TIMEOUT_MINUTES = 30;
const frameModes = new Set(["singleImage", "startEndRequired", "endFrameOptional", "startFrameOptional"]);

class RunningHubClosedError extends Error {
  status: number;
  code: string;
  constructor(message: string, status = 0, code = "") { super(message); this.name = "RunningHubClosedError"; this.status = status; this.code = code; }
}

function friendly(code: unknown, message: string) {
  const value = String(code ?? "");
  const hints: Record<string, string> = {
    "421": "单账号并发队列已满，请稍后重试；不要重复创建新任务。",
    "805": "显存不足，任务未完成。",
    "1014": "该 API 类型不接收当前 Key，请检查消费级/企业级 Key 类型。",
    "1501": "内容审核未通过，请调整提示词或参考素材。",
    "1602": "请求缺少 Bearer API Key，请检查当前站点的 API Key。",
  };
  return [message, hints[value]].filter(Boolean).join("\n");
}

function siteOf(context: Context) { return ["cn", "zh"].includes(String(context.config.site).toLowerCase()) ? "cn" : "ai"; }
function baseUrlOf(context: Context) { return SITES[siteOf(context)]!; }
function apiKeyOf(context: Context) {
  const key = context.config.apiKey?.trim().replace(/^Bearer\s+/i, "") ?? "";
  if (!key) throw new Error("请先在 RunningHub 闭源模型供应商配置中填写 API Key");
  return key;
}
function headersOf(context: Context, json = false) {
  return { Authorization: `Bearer ${apiKeyOf(context)}`, Accept: "application/json", ...(json ? { "Content-Type": "application/json" } : {}) };
}
function deadlineOf(context: Context) { return Date.now() + Math.max(1, context.config.timeoutMinutes ?? DEFAULT_TIMEOUT_MINUTES) * 60000; }
function imageRouteOf(model: string) {
  const route = IMAGE_ROUTES[model];
  if (!route) throw new Error(`未知 RunningHub 闭源图片模型：${model}`);
  return route;
}
function videoRouteOf(model: string) {
  const route = VIDEO_ROUTES[model];
  if (!route) throw new Error(`未知 RunningHub 闭源视频模型：${model}`);
  return route;
}
function stringValue(value: unknown) { return typeof value === "string" ? value.trim() : ""; }
function numberValue(value: unknown) { const number = Number(value); return Number.isFinite(number) ? number : undefined; }
function recordValue(value: unknown) { return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {}; }

async function requestJson(context: Context, path: string, body: Record<string, unknown>, signal: AbortSignal | null = context.signal ?? null) {
  const response = await context.tool.fetch(baseUrlOf(context) + path, {
    method: "POST", headers: headersOf(context, true), body: JSON.stringify(body), signal, redirect: "error",
  });
  const payload = await response.json().catch(() => ({})) as Record<string, unknown>;
  if (!response.ok) throw new RunningHubClosedError(`RunningHub 请求失败（HTTP ${response.status}）：${context.tool.errorMessage(payload) || "请求失败"}`, response.status);
  const code = payload.code ?? payload.errorCode;
  if (code !== undefined && !["0", "200"].includes(String(code))) {
    throw new RunningHubClosedError(friendly(code, String(payload.msg ?? payload.message ?? payload.errorMessage ?? "RunningHub 请求失败")), response.status, String(code));
  }
  return payload;
}

function taskIdOf(payload: Record<string, unknown>) {
  const data = recordValue(payload.data);
  const taskId = payload.taskId ?? payload.task_id ?? data.taskId ?? data.task_id;
  if (typeof taskId !== "string" && typeof taskId !== "number") throw new Error("RunningHub 提交响应缺少 taskId");
  return String(taskId);
}

function mediaBytes(context: Context, input: MediaInput): Promise<{ data: Uint8Array; mimeType: string; name: string }> {
  if (input.type === "binary") return Promise.resolve({ data: input.data, mimeType: input.mimeType, name: input.name || "reference" });
  if (input.type === "base64") return Promise.resolve({ data: Uint8Array.from(Buffer.from(input.data.replace(/^data:[^;]+;base64,/, ""), "base64")), mimeType: input.mimeType, name: input.name || "reference" });
  return context.tool.fetch(input.url, { signal: context.signal, redirect: "error" }).then(async response => {
    if (!response.ok) throw new Error(`读取参考素材失败：HTTP ${response.status}`);
    return { data: new Uint8Array(await response.arrayBuffer()), mimeType: response.headers.get("content-type") || input.mimeType || "application/octet-stream", name: input.name || "reference" };
  });
}

const extensions: Record<string, string> = {
  "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif", "image/avif": "avif",
  "video/mp4": "mp4", "video/quicktime": "mov", "video/webm": "webm",
  "audio/mpeg": "mp3", "audio/wav": "wav", "audio/x-wav": "wav", "audio/mp4": "m4a", "audio/ogg": "ogg", "audio/flac": "flac",
};

async function upload(context: Context, input: MediaInput) {
  const media = await mediaBytes(context, input);
  const extension = extensions[media.mimeType.split(";")[0].trim().toLowerCase()] || "bin";
  const name = (media.name || "reference").replace(/\.[^.]+$/, "").replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 80) || "reference";
  const form = new FormData();
  form.append("file", new Blob([media.data.slice().buffer as ArrayBuffer], { type: media.mimeType }), `${name}.${extension}`);
  const response = await context.tool.fetch(baseUrlOf(context) + "/openapi/v2/media/upload/binary", { method: "POST", headers: headersOf(context), body: form, signal: context.signal, redirect: "error" });
  const payload = await response.json().catch(() => ({})) as Record<string, unknown>;
  if (!response.ok) throw new Error(`RunningHub 参考素材上传失败（HTTP ${response.status}）：${context.tool.errorMessage(payload)}`);
  const code = payload.code ?? payload.errorCode;
  if (code !== undefined && !["0", "200"].includes(String(code))) throw new Error(friendly(code, String(payload.msg ?? payload.message ?? "RunningHub 参考素材上传失败")));
  const data = recordValue(payload.data);
  const url = typeof data.download_url === "string" ? data.download_url : typeof data.url === "string" ? data.url : "";
  if (!url) throw new Error("RunningHub 上传响应缺少素材 URL");
  if (/^https?:\/\//i.test(url)) return url;
  if (url.startsWith("/")) return baseUrlOf(context) + url;
  return `${baseUrlOf(context)}/view?filename=${encodeURIComponent(url)}&type=input`;
}

function gptSize(ratio: string | undefined) {
  return ratio === "2:3" || ratio === "9:16" ? "1024x1536" : ratio === "3:2" || ratio === "16:9" ? "1536x1024" : "1024x1024";
}

function buildImageBody(request: ImageRequest, imageUrls: string[], editing: boolean) {
  const other = request.other ?? {};
  const prompt = request.prompt.trim();
  if (!prompt) throw new Error("请输入图片提示词");
  return {
    prompt,
    ...(editing && imageUrls.length ? { imageUrls } : {}),
    size: stringValue(request.size) || stringValue(other.size) || gptSize(request.ratio),
    background: stringValue(other.background) || "auto",
    quality: stringValue(other.quality) || stringValue(request.quality) || "auto",
    ...(numberValue(other.frameCount) !== undefined ? { frameCount: numberValue(other.frameCount) } : {}),
    ...(numberValue(other.frameDurationMs) !== undefined ? { frameDurationMs: numberValue(other.frameDurationMs) } : {}),
    ...(numberValue(other.outputCompression) !== undefined ? { outputCompression: Math.max(0, Math.min(100, numberValue(other.outputCompression)!)) } : {}),
    outputFormat: stringValue(other.outputFormat) || "png",
  };
}

function referencePrompt(request: VideoRequest) {
  return request.prompt.trim().replace(/\{\{ref (\d+)\}\}/g, (_marker, value: string) => {
    const reference = request.referenceOrder?.[Number(value) - 1];
    if (!reference) return `参考 ${value}`;
    if (reference.type === "text") return "参考文本";
    if (reference.type === "firstFrame") return "首帧";
    if (reference.type === "lastFrame") return "尾帧";
    if (!("index" in reference)) return "参考素材";
    const labels = { image: "图片", video: "视频", audio: "音频" };
    return `参考${labels[reference.type]}${reference.index + 1}`;
  });
}

function selectedVideoEndpoint(route: VideoRoute, request: VideoRequest) {
  if (request.firstFrame || request.lastFrame || frameModes.has(String(request.mode))) return { endpoint: route.imageEndpoint, kind: "frame" };
  if (Array.isArray(request.mode) || request.images?.length || request.videos?.length || request.audios?.length) return { endpoint: route.multimodalEndpoint, kind: "multimodal" };
  return { endpoint: route.textEndpoint, kind: "text" };
}

function normalizedResolution(route: VideoRoute, value: unknown) {
  const normalized = stringValue(value).toLowerCase();
  return route.resolutions.includes(normalized) ? normalized : route.resolutions[0];
}

function normalizedDuration(route: VideoRoute, value: unknown) {
  const duration = Math.round(numberValue(value) ?? 5);
  return String(Math.max(route.minDuration, Math.min(route.maxDuration, duration)));
}

async function buildVideoBody(context: Context, route: VideoRoute, request: VideoRequest, kind: string) {
  const other = request.other ?? {};
  const body: Record<string, unknown> = {
    prompt: referencePrompt(request),
    resolution: normalizedResolution(route, request.resolution),
    duration: normalizedDuration(route, request.duration),
    ratio: ["adaptive", "16:9", "4:3", "1:1", "3:4", "9:16", "21:9"].includes(stringValue(request.ratio)) ? stringValue(request.ratio) : "adaptive",
    generateAudio: request.generateAudio !== false,
    seed: numberValue(other.seed) ?? -1,
    realPersonMode: other.realPersonMode !== false,
  };
  const conversionSlots = Array.isArray(other.conversionSlots) ? other.conversionSlots.filter(value => typeof value === "string") : undefined;
  if (conversionSlots?.length) body.conversionSlots = conversionSlots;
  if (other.returnLastFrame === true) body.returnLastFrame = true;
  if (route.variant === "v25") {
    body.watermark = request.watermark === true || other.watermark === true;
    body.bitrateMode = stringValue(other.bitrateMode) === "high" ? "high" : "standard";
    body.outputFormat = stringValue(other.outputFormat) === "mov" ? "mov" : "mp4";
    if (other.draft === true) body.draft = true;
  }
  if (kind === "frame") {
    const firstFrame = request.firstFrame ?? request.images?.[0];
    if (!firstFrame) throw new Error("Seedance 图生视频模式需要首帧图片");
    body.firstFrameUrl = await upload(context, firstFrame);
    if (request.lastFrame) body.lastFrameUrl = await upload(context, request.lastFrame);
    return body;
  }
  if (kind === "multimodal") {
    const imageUrls: string[] = [];
    const videoUrls: string[] = [];
    const audioUrls: string[] = [];
    for (const image of request.images ?? []) imageUrls.push(await upload(context, image));
    for (const video of request.videos ?? []) videoUrls.push(await upload(context, video));
    for (const audio of request.audios ?? []) audioUrls.push(await upload(context, audio));
    if (imageUrls.length) body.imageUrls = imageUrls;
    if (videoUrls.length) body.videoUrls = videoUrls;
    if (audioUrls.length) body.audioUrls = audioUrls;
  }
  return body;
}

async function query(context: Context, taskId: string): Promise<QueryResult> {
  const payload = await requestJson(context, "/openapi/v2/query", { taskId });
  const rawData = Array.isArray(payload.data) || (payload.data && typeof payload.data === "object") ? payload.data : payload;
  const data = Array.isArray(rawData) ? { results: rawData, status: "SUCCESS" } : recordValue(rawData);
  const status = String(data.status ?? data.taskStatus ?? (Array.isArray(rawData) ? "SUCCESS" : "UNKNOWN")).toUpperCase();
  const rawResults = Array.isArray(data.results) ? data.results : Array.isArray(data.fileList) ? data.fileList : Array.isArray(data.outputs) ? data.outputs : [];
  const results = rawResults.flatMap(item => {
    if (typeof item === "string" && /^https?:\/\//i.test(item)) return [{ url: item }];
    if (!item || typeof item !== "object" || Array.isArray(item)) return [];
    const record = item as Record<string, unknown>;
    const url = record.url ?? record.outputUrl ?? record.fileUrl;
    if (typeof url !== "string" || !/^https?:\/\//i.test(url)) return [];
    return [{ url, outputType: typeof record.outputType === "string" ? record.outputType : typeof record.fileType === "string" ? record.fileType : undefined }];
  });
  return { status, results, usage: recordValue(data.usage), raw: payload };
}

function outputMatches(item: { url: string; outputType?: string }, mediaType: "image" | "video") {
  const value = `${item.outputType ?? ""} ${item.url}`.toLowerCase();
  return mediaType === "video"
    ? /(?:video|\.mp4(?:$|\?)|\.mov(?:$|\?)|\.webm(?:$|\?))/.test(value)
    : /(?:image|\.png(?:$|\?)|\.jpe?g(?:$|\?)|\.webp(?:$|\?))/.test(value);
}

async function download(context: Context, url: string, mediaType: "image" | "video"): Promise<MediaAsset> {
  const headers: Record<string, string> = { Referer: baseUrlOf(context) + "/", Accept: mediaType === "video" ? "video/*,*/*;q=0.8" : "image/*,*/*;q=0.8" };
  try { if (new URL(url).hostname.toLowerCase().includes("runninghub")) headers.Authorization = `Bearer ${apiKeyOf(context)}`; } catch { /* URL already validated by query. */ }
  const response = await context.tool.fetch(url, { headers, signal: context.signal, redirect: "follow" });
  if (!response.ok) throw new Error(`RunningHub ${mediaType === "video" ? "视频" : "图片"}下载失败：HTTP ${response.status}`);
  const contentType = response.headers.get("content-type") || "";
  const fallback = mediaType === "video" ? "video/mp4" : "image/png";
  return { mediaType, type: "binary", data: new Uint8Array(await response.arrayBuffer()), mimeType: contentType.startsWith(`${mediaType}/`) ? contentType : fallback };
}

async function awaitResult(context: Context, data: TaskData): Promise<MediaAsset[]> {
  const interval = Math.max(1, context.config.pollIntervalSeconds ?? DEFAULT_POLL_SECONDS) * 1000;
  while (Date.now() <= data.deadline) {
    context.signal?.throwIfAborted();
    const result = await query(context, data.taskId);
    if (["SUCCESS", "SUCCEEDED", "COMPLETED"].includes(result.status)) {
      const matches = result.results.filter(item => outputMatches(item, data.mediaType));
      const outputs = matches.length ? matches : result.results;
      if (!outputs.length) throw Object.assign(new Error(`RunningHub 任务完成但没有输出${data.mediaType === "video" ? "视频" : "图片"}`), { code: "MEDIA_TASK_FAILED" });
      context.signal?.throwIfAborted();
      return Promise.all(outputs.map(item => download(context, item.url, data.mediaType)));
    }
    if (["FAILED", "FAIL", "CANCEL", "CANCELLED", "ERROR", "REJECTED", "EXPIRED"].includes(result.status)) {
      const reason = friendly(result.raw.errorCode, context.tool.errorMessage(result.raw) || result.status);
      throw Object.assign(new Error(`RunningHub 闭源模型任务失败：${reason}`), { code: "MEDIA_TASK_FAILED" });
    }
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(resolve, interval);
      const abort = () => { clearTimeout(timer); reject(context.signal?.reason || new Error("任务已取消")); };
      context.signal?.addEventListener("abort", abort, { once: true });
    });
  }
  throw Object.assign(new Error("RunningHub 闭源模型等待超时；taskId 已保存，可稍后恢复查询"), { retryable: true });
}

async function cancel(context: Context, taskId: string) {
  try { await requestJson(context, "/task/openapi/cancel", { apiKey: apiKeyOf(context), taskId }, null); } catch { /* 取消是尽力而为；不覆盖最初的 AbortError。 */ }
}

async function runTask(context: Context, mediaType: "image" | "video", model: string, endpoint: string, body: Record<string, unknown>) {
  const payload = await requestJson(context, endpoint, body);
  const taskId = taskIdOf(payload);
  const data: TaskData = { kind: "solodramaRunningHubClosed", taskId, mediaType, model, endpoint, deadline: deadlineOf(context) };
  try {
    await context.saveTaskData?.(data);
    return await awaitResult(context, data);
  } catch (error) {
    if (context.signal?.aborted) await cancel(context, taskId);
    throw error;
  }
}


export default {
  id: "solodramaRunningHubClosed",
  label: "RunningHub 闭源模型",
  icon: "data:image/x-icon;base64,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",
  version: "2.0.0",
  readme: `**获取 API Key**

- [RunningHub 国内站](https://www.runninghub.cn?inviteCode=cn-v1122)
- [RunningHub 国际站](https://www.runninghub.ai/zh-cn?inviteCode=rh-v1727) **宽审核**

视频模型支持 Seedance 2.5 Flash、Seedance 2.5、Seedance 2.0，并按生成模式分别调用文生视频、图生视频或多模态参考端点。图像模型只提供 AI 站 GPT Image 2.6 Flare 低价版，包含文生图和图像编辑；若站点选为国内站，图像模型会明确阻止提交。

参考图片、视频和音频会先上传到 RunningHub。任务通过 /openapi/v2/query 轮询，并保存 taskId 支持恢复。闭源模型没有可核验金额时显示“未知”，真实提交前必须显式开启“费用未知时仍允许提交”。`,
  rules: [
    { type: "select", field: "site", title: "视频调用站点", value: "ai", options: [{ label: "RunningHub 国内站（zh / .cn）", value: "cn" }, { label: "RunningHub 国际站（宽审核 / .ai）", value: "ai" }] },
    { type: "input", field: "apiKey", title: "API Key", value: "", props: { type: "password", showPassword: true, autocomplete: "off" } },
    { type: "inputNumber", field: "pollIntervalSeconds", title: "轮询间隔（秒）", value: 5, props: { min: 1, max: 60, step: 1 } },
    { type: "inputNumber", field: "timeoutMinutes", title: "任务超时（分钟）", value: 30, props: { min: 1, max: 180, step: 1 } },
    { type: "input", field: "estimateText", title: "自定义估价文本（可选）", value: "" },
    { type: "input", field: "estimateTips", title: "估价说明（可选）", value: "" },
  ],
  models: [
    {
      id: "seedance25Flash", label: "Seedance 2.5 Flash", type: "video" as const,
      mode: ["text", "singleImage", "startEndRequired", "endFrameOptional", ["imageReference:10", "videoReference:5", "audioReference:5"]],
      audio: "optional", imageRatios: ["adaptive", "16:9", "4:3", "1:1", "3:4", "9:16", "21:9"],
      durationResolutionMap: [{ duration: [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30], resolution: ["480p", "720p"] }],
      rules: [
        { type: "switch", field: "allowUnknownCostSubmit", title: "费用未知时仍允许提交", value: false },
        { type: "inputNumber", field: "seed", title: "种子", value: -1, props: { min: -1, max: 2147483647, step: 1 } },
        { type: "switch", field: "realPersonMode", title: "真人素材资产化", value: true },
        { type: "switch", field: "returnLastFrame", title: "同时返回尾帧", value: false },
        { type: "select", field: "bitrateMode", title: "画质码率", value: "standard", options: [{ label: "标准", value: "standard" }, { label: "高画质", value: "high" }] },
        { type: "select", field: "outputFormat", title: "输出格式", value: "mp4", options: [{ label: "MP4", value: "mp4" }, { label: "MOV", value: "mov" }] },
      ],
    },
    {
      id: "seedance25", label: "Seedance 2.5", type: "video" as const,
      mode: ["text", "singleImage", "startEndRequired", "endFrameOptional", ["imageReference:30", "videoReference:10", "audioReference:10"]],
      audio: "optional", imageRatios: ["adaptive", "16:9", "4:3", "1:1", "3:4", "9:16", "21:9"],
      durationResolutionMap: [{ duration: [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30], resolution: ["480p", "720p", "native1080p", "1080p", "2k", "4k"] }],
      rules: [
        { type: "switch", field: "allowUnknownCostSubmit", title: "费用未知时仍允许提交", value: false },
        { type: "inputNumber", field: "seed", title: "种子", value: -1, props: { min: -1, max: 2147483647, step: 1 } },
        { type: "switch", field: "realPersonMode", title: "真人素材资产化", value: true },
        { type: "switch", field: "returnLastFrame", title: "同时返回尾帧", value: false },
        { type: "select", field: "bitrateMode", title: "画质码率", value: "standard", options: [{ label: "标准", value: "standard" }, { label: "高画质", value: "high" }] },
        { type: "select", field: "outputFormat", title: "输出格式", value: "mp4", options: [{ label: "MP4", value: "mp4" }, { label: "MOV", value: "mov" }] },
      ],
    },
    {
      id: "seedance20", label: "Seedance 2.0", type: "video" as const,
      mode: ["text", "singleImage", "startEndRequired", "endFrameOptional", ["imageReference:9", "videoReference:3", "audioReference:3"]],
      audio: "optional", imageRatios: ["adaptive", "16:9", "4:3", "1:1", "3:4", "9:16", "21:9"],
      durationResolutionMap: [{ duration: [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15], resolution: ["480p", "720p", "native1080p", "native4k", "1080p", "2k", "4k"] }],
      rules: [
        { type: "switch", field: "allowUnknownCostSubmit", title: "费用未知时仍允许提交", value: false },
        { type: "inputNumber", field: "seed", title: "种子", value: -1, props: { min: -1, max: 2147483647, step: 1 } },
        { type: "switch", field: "realPersonMode", title: "真人素材资产化", value: true },
        { type: "switch", field: "returnLastFrame", title: "同时返回尾帧", value: false },
      ],
    },
    {
      id: "gptImage26Flare", label: "GPT Image 2.6 Flare（AI 站低价版）", type: "image" as const,
      mode: ["text", "singleImage", "multiReference"],
      imageRatios: ["1:1", "2:3", "3:2", "4:3", "3:4", "16:9", "9:16"],
      imageSizes: ["auto", "1024x1024", "1536x1024", "1024x1536"],
      rules: [
        { type: "switch", field: "allowUnknownCostSubmit", title: "费用未知时仍允许提交", value: false },
        { type: "select", field: "quality", title: "质量", value: "auto", options: [{ label: "自动", value: "auto" }, { label: "低", value: "low" }, { label: "中", value: "medium" }, { label: "高", value: "high" }, { label: "极高", value: "xhigh" }, { label: "最高", value: "max" }] },
        { type: "select", field: "background", title: "背景", value: "auto", options: [{ label: "自动", value: "auto" }, { label: "透明", value: "transparent" }, { label: "不透明", value: "opaque" }] },
        { type: "select", field: "outputFormat", title: "输出格式", value: "png", options: [{ label: "PNG", value: "png" }, { label: "JPEG", value: "jpeg" }, { label: "WebP", value: "webp" }] },
        { type: "inputNumber", field: "outputCompression", title: "输出压缩（0-100）", value: 95, props: { min: 0, max: 100, step: 1 } },
      ],
    },
  ],
  async generateImage(this: Context, request: ImageRequest): Promise<MediaAsset[]> {
    if (request.other?.allowUnknownCostSubmit !== true) throw new Error("RunningHub 闭源模型费用未知；请先在当前模型规则中明确允许提交");
    if (siteOf(this) !== "ai") throw new Error("GPT Image 2.6 Flare 低价版仅支持 RunningHub AI 站，请将视频调用站点切换为国际站后再生成图片");
    const route = imageRouteOf(request.model);
    if ((request.images?.length ?? 0) > 16) throw new Error("GPT Image 2.6 Flare 最多支持 16 张参考图");
    const imageUrls: string[] = [];
    for (const image of request.images ?? []) imageUrls.push(await upload(this, image));
    const endpoint = imageUrls.length ? route.editEndpoint : route.textEndpoint;
    return runTask(this, "image", request.model, endpoint, buildImageBody(request, imageUrls, imageUrls.length > 0));
  },
  async generateVideo(this: Context, request: VideoRequest): Promise<MediaAsset[]> {
    if (request.other?.allowUnknownCostSubmit !== true) throw new Error("RunningHub 闭源模型费用未知；请先在当前模型规则中明确允许提交");
    const route = videoRouteOf(request.model);
    if ((request.images?.length ?? 0) > route.maxImages) throw new Error(`${request.model} 最多支持 ${route.maxImages} 张参考图`);
    if ((request.videos?.length ?? 0) > route.maxVideos) throw new Error(`${request.model} 最多支持 ${route.maxVideos} 段参考视频`);
    if ((request.audios?.length ?? 0) > route.maxAudios) throw new Error(`${request.model} 最多支持 ${route.maxAudios} 段参考音频`);
    const selected = selectedVideoEndpoint(route, request);
    return runTask(this, "video", request.model, selected.endpoint, await buildVideoBody(this, route, request, selected.kind));
  },
  getPrice(this: Context) {
    const price = typeof this.config.estimateText === "string" ? this.config.estimateText.trim() : "";
    return Promise.resolve(price
      ? { price, tips: typeof this.config.estimateTips === "string" && this.config.estimateTips.trim() ? this.config.estimateTips.trim() : "以 RunningHub 实际结算为准。" }
      : { price: "未知", tips: "RunningHub 闭源模型没有公开 estimate 金额接口；费用不会显示为 0。" });
  },
  async getBalance(this: Context) {
    const payload = await requestJson(this, "/uc/openapi/accountStatus", { apikey: apiKeyOf(this) });
    const data = recordValue(payload.data);
    const money = Number(data.remainMoney);
    const coins = Number(data.remainCoins);
    if (Number.isFinite(money)) return { balance: money, unit: typeof data.currency === "string" && data.currency ? data.currency : "CNY", ...(Number.isFinite(coins) ? { keyBalance: coins } : {}) };
    if (Number.isFinite(coins)) return { balance: coins, unit: "RH币" };
    throw new Error("RunningHub accountStatus 未返回余额");
  },
  async resumeTask(this: Context, data: ProviderTaskData) {
    if (data.kind !== "solodramaRunningHubClosed" || typeof data.taskId !== "string" || !data.taskId
      || !["image", "video"].includes(String(data.mediaType)) || typeof data.model !== "string" || !data.model
      || typeof data.endpoint !== "string" || !data.endpoint || typeof data.deadline !== "number" || !Number.isFinite(data.deadline)) {
      throw new Error("RunningHub 闭源模型任务恢复数据无效");
    }
    return awaitResult(this, data as TaskData);
  },
};
