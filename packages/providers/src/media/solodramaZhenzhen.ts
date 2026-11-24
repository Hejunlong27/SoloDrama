/**
 * SoloDrama 真真 AI Provider
 *
 * 真真 AI 图片、Muse Video 与 MiniMax H3 ComfyUI Max 共用异步任务协议。
 * 不依赖 SoloDrama 内部模块，可由「设置 → 媒体模型 → 添加自定义供应商」直接导入。
 */

type MediaType = "image" | "video" | "audio";
type ProviderFormRule = {
  type: string;
  field: string;
  title: string;
  value: unknown;
  props?: Record<string, unknown>;
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
type Context = {
  config: {
    apiKey?: string;
    baseUrl?: string;
    pollIntervalSeconds?: number;
    timeoutMinutes?: number;
  };
  signal?: AbortSignal;
  saveTaskData?: (data: ProviderTaskData) => Promise<void>;
  tool: {
    fetch: typeof fetch;
    errorMessage(value: unknown): string;
  };
};
type ZhenzhenTaskData = {
  kind: "solodramaZhenzhen";
  mediaType: "image" | "video";
  taskId: string;
  deadline: number;
  usage?: ProviderTaskValue;
};
type Estimate = { amount: number | null; currency: string; raw: Record<string, unknown> };
type PollResult = {
  status: "queued" | "running" | "succeeded" | "failed" | "canceled" | "unknown";
  taskId: string;
  progress?: unknown;
  urls: string[];
  usage?: ProviderTaskValue;
  error: string;
  raw: Record<string, unknown>;
};

const DEFAULT_BASE_URL = "https://api.seedance.nz";
const DEFAULT_POLL_SECONDS = 3;
const DEFAULT_TIMEOUT_MINUTES = 30;

const rules = [
  {
    type: "input",
    field: "apiKey",
    title: "真真 AI API Key",
    value: "",
    props: { type: "password", showPassword: true, autocomplete: "off" },
  },
  {
    type: "input",
    field: "baseUrl",
    title: "API 地址",
    value: "https://api.seedance.nz",
    props: { placeholder: "https://api.seedance.nz" },
  },
  {
    type: "inputNumber",
    field: "pollIntervalSeconds",
    title: "轮询间隔（秒）",
    value: 3,
    props: { min: 1, max: 30, step: 1 },
  },
  {
    type: "inputNumber",
    field: "timeoutMinutes",
    title: "任务等待上限（分钟）",
    value: 30,
    props: { min: 1, max: 240, step: 1 },
  },
] as const;

function keyOf(context: Context): string {
  const key = typeof context.config.apiKey === "string" ? context.config.apiKey.trim().replace(/^Bearer\s+/i, "") : "";
  if (!key) throw new Error("请先在供应商配置中填写真真 AI API Key");
  return key;
}

function baseUrlOf(context: Context): string {
  const raw = typeof context.config.baseUrl === "string" && context.config.baseUrl.trim() ? context.config.baseUrl.trim() : DEFAULT_BASE_URL;
  const url = new URL(raw);
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) throw new Error("真真 AI API 地址必须是无内嵌凭据的 HTTP(S) URL");
  return url.toString().replace(/\/+$/, "");
}

function headersOf(context: Context, json = true, maxCost?: number): Record<string, string> {
  return {
    Authorization: "Bearer " + keyOf(context),
    Accept: "application/json",
    ...(json ? { "Content-Type": "application/json" } : {}),
    ...(maxCost !== undefined && Number.isFinite(maxCost) ? { "X-Max-Cost": String(maxCost) } : {}),
  };
}

function pollMs(context: Context): number {
  const value = Number(context.config.pollIntervalSeconds);
  return Math.round((Number.isFinite(value) && value >= 1 ? Math.min(30, value) : DEFAULT_POLL_SECONDS) * 1000);
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

async function upload(context: Context, input: MediaInput): Promise<string> {
  const media = await mediaBytes(input, context);
  const extension = media.mimeType.split("/")[1]?.replace("jpeg", "jpg").replace(/[^a-z0-9]/gi, "") || "bin";
  const name = (media.name || "reference").replace(/\.[^.]+$/, "").replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 80) || "reference";
  const form = new FormData();
  form.append("file", new Blob([media.data.slice().buffer as ArrayBuffer], { type: media.mimeType }), name + "." + extension);
  const response = await context.tool.fetch(baseUrlOf(context) + "/v1/files/upload", {
    method: "POST", headers: headersOf(context, false), body: form, signal: context.signal, redirect: "error",
  });
  const payload = await response.json().catch(() => ({})) as Record<string, unknown>;
  if (!response.ok) throw new Error("真真 AI 参考图上传失败：HTTP " + response.status);
  const url = typeof payload.url === "string" ? payload.url : "";
  if (!/^https?:\/\//i.test(url)) throw new Error("真真 AI 上传响应缺少 url");
  return url;
}

async function imageUrls(context: Context, request: ImageRequest | VideoRequest): Promise<string[]> {
  const inputs = request.images?.length ? request.images : "firstFrame" in request && request.firstFrame ? [request.firstFrame, ...(request.lastFrame ? [request.lastFrame] : [])] : [];
  const urls: string[] = [];
  for (const input of inputs) urls.push(await upload(context, input));
  return urls;
}

function imagePayload(request: ImageRequest, images: string[]): Record<string, unknown> {
  return {
    model: request.model,
    prompt: request.prompt,
    images,
    ...(request.size ? { size: request.size } : {}),
    ...(request.ratio ? { aspect_ratio: request.ratio } : {}),
    ...(request.quality ? { quality: request.quality } : {}),
    ...(request.outputFormat ? { output_format: request.outputFormat } : {}),
    n: Number.isSafeInteger(request.n) && request.n! > 0 ? request.n : 1,
  };
}

function videoPayload(request: VideoRequest, images: string[]): Record<string, unknown> {
  return {
    model: request.model,
    prompt: request.prompt,
    images,
    ...(request.duration !== undefined ? { duration: request.duration } : {}),
    ...(request.resolution ? { resolution: request.resolution } : {}),
    ...(request.ratio ? { aspect_ratio: request.ratio } : {}),
    ...(request.generateAudio !== undefined ? { generate_audio: request.generateAudio } : {}),
  };
}

function payloadFor(context: Context, request: ImageRequest | VideoRequest, mediaType: "image" | "video", images: string[]): Record<string, unknown> {
  void context;
  return mediaType === "image" ? imagePayload(request as ImageRequest, images) : videoPayload(request as VideoRequest, images);
}

async function requestJson(context: Context, method: "GET" | "POST", path: string, body?: Record<string, unknown>, maxCost?: number): Promise<Record<string, unknown>> {
  const response = await context.tool.fetch(baseUrlOf(context) + path, {
    method, headers: headersOf(context, body !== undefined, maxCost), body: body === undefined ? undefined : JSON.stringify(body), signal: context.signal, redirect: "error",
  });
  const payload = await response.json().catch(() => ({})) as Record<string, unknown>;
  if (!response.ok) {
    const message = context.tool.errorMessage(payload) || "真真 AI 请求失败 HTTP " + response.status;
    throw Object.assign(new Error(message), { status: response.status, retryable: response.status === 429 || response.status >= 500 });
  }
  return payload;
}

function taskIdOf(payload: Record<string, unknown>): string {
  const data = payload.data && typeof payload.data === "object" ? payload.data as Record<string, unknown> : {};
  const taskId = payload.id ?? payload.task_id ?? data.id ?? data.task_id;
  if (typeof taskId !== "string" && typeof taskId !== "number") throw new Error("真真 AI 提交响应缺少 task_id");
  return String(taskId);
}

function amountOf(payload: Record<string, unknown>): Estimate {
  const data = payload.data && typeof payload.data === "object" ? payload.data as Record<string, unknown> : payload;
  const amount = Number(data.amount ?? data.price ?? data.cost);
  const currency = typeof data.currency === "string" && data.currency ? data.currency : "CNY";
  return { amount: Number.isFinite(amount) ? amount : null, currency, raw: payload };
}

async function estimate(context: Context, mediaType: "image" | "video", payload: Record<string, unknown>): Promise<Estimate> {
  return amountOf(await requestJson(context, "POST", "/v1/" + mediaType + "/generations/estimate", { ...payload, images: [] }));
}

function statusText(payload: Record<string, unknown>): string {
  const data = payload.data && typeof payload.data === "object" ? payload.data as Record<string, unknown> : {};
  const task = payload.task && typeof payload.task === "object" ? payload.task as Record<string, unknown> : {};
  return String(payload.status ?? data.status ?? task.status ?? "").trim().toLowerCase().replace(/[-\s]+/g, "_");
}

function normalizeStatus(value: string): PollResult["status"] {
  if (["not_start", "submitted", "queued"].includes(value)) return "queued";
  if (["in_progress", "running", "processing"].includes(value)) return "running";
  if (["success", "succeeded", "completed"].includes(value)) return "succeeded";
  if (["failure", "failed", "error"].includes(value)) return "failed";
  if (["canceled", "cancelled"].includes(value)) return "canceled";
  return "unknown";
}

function urlsOf(payload: Record<string, unknown>): string[] {
  const data = payload.data && typeof payload.data === "object" ? payload.data as Record<string, unknown> : {};
  const metadata = payload.metadata && typeof payload.metadata === "object" ? payload.metadata as Record<string, unknown> : {};
  const nestedMetadata = data.metadata && typeof data.metadata === "object" ? data.metadata as Record<string, unknown> : {};
  const content = data.content && typeof data.content === "object" ? data.content as Record<string, unknown> : {};
  const topContent = payload.content && typeof payload.content === "object" ? payload.content as Record<string, unknown> : {};
  const values: unknown[] = [payload.result_url, data.result_url, metadata.url, nestedMetadata.url, content.image_url, topContent.image_url];
  for (const key of ["image_urls", "video_urls", "audio_urls"]) if (Array.isArray(topContent[key])) values.push(...topContent[key] as unknown[]);
  for (const key of ["image_urls", "video_urls", "audio_urls"]) if (Array.isArray(content[key])) values.push(...content[key] as unknown[]);
  return [...new Set(values.filter((value): value is string => typeof value === "string" && /^https?:\/\//i.test(value)))];
}

function usageOf(payload: Record<string, unknown>): ProviderTaskValue | undefined {
  const data = payload.data && typeof payload.data === "object" ? payload.data as Record<string, unknown> : {};
  const task = payload.task && typeof payload.task === "object" ? payload.task as Record<string, unknown> : {};
  const usage = payload.usage ?? data.usage ?? task.usage;
  return usage && typeof usage === "object" && !Array.isArray(usage)
    ? JSON.parse(JSON.stringify(usage)) as ProviderTaskValue
    : undefined;
}

function errorText(payload: Record<string, unknown>, context: Context): string {
  const data = payload.data && typeof payload.data === "object" ? payload.data as Record<string, unknown> : {};
  return context.tool.errorMessage(payload) || context.tool.errorMessage(data) || "真真 AI 任务失败";
}

async function pollOnce(context: Context, mediaType: "image" | "video", taskId: string): Promise<PollResult> {
  const raw = await requestJson(context, "GET", "/v1/" + mediaType + "/generations/" + encodeURIComponent(taskId));
  const data = raw.data && typeof raw.data === "object" ? raw.data as Record<string, unknown> : {};
  return {
    status: normalizeStatus(statusText(raw)),
    taskId,
    progress: raw.progress ?? data.progress,
    urls: urlsOf(raw),
    usage: usageOf(raw),
    error: normalizeStatus(statusText(raw)) === "failed" ? errorText(raw, context) : "",
    raw,
  };
}

async function submitOnce(context: Context, mediaType: "image" | "video", payload: Record<string, unknown>, maxCost: number): Promise<string> {
  const payloadResponse = await requestJson(context, "POST", "/v1/" + mediaType + "/generations", payload, maxCost);
  return taskIdOf(payloadResponse);
}

async function awaitResult(context: Context, data: ZhenzhenTaskData): Promise<MediaAsset[]> {
  const deadline = Number.isFinite(data.deadline) ? data.deadline : deadlineOf(context);
  while (Date.now() <= deadline) {
    context.signal?.throwIfAborted();
    const result = await pollOnce(context, data.mediaType, data.taskId);
    if (result.status === "failed" || result.status === "canceled") {
      throw Object.assign(new Error("真真 AI 任务终止：" + (result.error || result.status)), { code: "MEDIA_TASK_FAILED" });
    }
    if (result.status === "succeeded") {
      if (!result.urls.length) throw Object.assign(new Error("真真 AI 任务成功但没有结果地址"), { code: "MEDIA_TASK_FAILED" });
      const checkpoint: ZhenzhenTaskData = { ...data };
      if (result.usage !== undefined) checkpoint.usage = result.usage;
      await context.saveTaskData?.(checkpoint);
      const asset = await download(context, result.urls[0]!, data.mediaType);
      return [asset];
    }
    await wait(context, pollMs(context));
  }
  throw Object.assign(new Error("真真 AI 任务等待超时；taskId 已保存，可恢复继续查询"), { retryable: true });
}

async function download(context: Context, url: string, mediaType: "image" | "video"): Promise<MediaAsset> {
  const response = await context.tool.fetch(url, {
    headers: { Accept: mediaType === "image" ? "image/*,*/*;q=0.8" : "video/*,*/*;q=0.8", "User-Agent": "Mozilla/5.0 SoloDrama/1.0" },
    signal: context.signal, redirect: "follow",
  });
  if (!response.ok) throw new Error("真真 AI 产物下载失败：HTTP " + response.status);
  return {
    mediaType,
    type: "binary",
    data: new Uint8Array(await response.arrayBuffer()),
    mimeType: response.headers.get("content-type") || (mediaType === "image" ? "image/png" : "video/mp4"),
  };
}

function confirmedMaxCost(request: ImageRequest | VideoRequest, mediaType: "image" | "video"): number {
  const value = Number(request.other?.confirmedMaxCost);
  if (!Number.isFinite(value) || value <= 0) {
    throw new Error("这是付费任务。请先在当前模型设置中填写本次单任务 CNY 费用上限；未设置上限不会提交。");
  }
  if (mediaType === "image" && value > 100) throw new Error("图片单任务 CNY 上限过高，请核对后重试");
  if (mediaType === "video" && value > 10_000) throw new Error("视频单任务 CNY 上限过高，请核对后重试");
  return value;
}

async function generate(context: Context, request: ImageRequest | VideoRequest, mediaType: "image" | "video"): Promise<MediaAsset[]> {
  const maxCost = confirmedMaxCost(request, mediaType);
  const images = await imageUrls(context, request);
  const payload = payloadFor(context, request, mediaType, images);
  const quote = await estimate(context, mediaType, payload);
  if (quote.amount === null) throw new Error("真真 AI 未返回可核验的预估金额；费用未知，禁止提交");
  if (quote.amount > maxCost) throw new Error("预估 " + quote.currency + " " + quote.amount.toFixed(4) + " 超过本次上限 " + maxCost.toFixed(4) + "，未提交");
  const data: ZhenzhenTaskData = { kind: "solodramaZhenzhen", mediaType, taskId: await submitOnce(context, mediaType, payload, maxCost), deadline: deadlineOf(context) };
  await context.saveTaskData?.(data);
  return awaitResult(context, data);
}

export default {
  id: "solodramaZhenzhen",
  label: "真真 AI",
  version: "1.0.0",
  icon: "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCA2NCA2NCI+PHJlY3QgeD0iNCIgeT0iNCIgd2lkdGg9IjU2IiBoZWlnaHQ9IjU2IiByeD0iMTQiIGZpbGw9IiMxMDE3MjgiLz48cGF0aCBkPSJNMTggMjJoMjh2MjBIMTh6IiBmaWxsPSJub25lIiBzdHJva2U9IiNmZjg2NjQiIHN0cm9rZS13aWR0aD0iNCIvPjxjaXJjbGUgY3g9IjMyIiBjeT0iMzIiIHI9IjYiIGZpbGw9IiM1M2RjYzQiLz48L3N2Zz4=",
  readme: "真真 AI 先调用 estimate，再核对模型设置中的单任务 CNY 上限；报价缺失或超过上限都不会提交。Muse Video 按公开异步视频协议处理；MiniMax H3 ComfyUI Max 按图片参考顺序传入 images。任务接单后保存 taskId，取消只停止本地等待，重新打开节点可通过 taskId 继续查询。",
  rules,
  models: [
    {
      id: "zhenzhen-image-g-v2.6-lowprice",
      label: "真真图片 G v2.6（低价版）",
      type: "image",
      mode: ["text", "multiReference"],
      imageSizes: ["1k", "2k", "4k"],
      imageRatios: ["1:1", "4:3", "3:4", "16:9", "9:16", "3:2", "2:3"],
      rules: [{ type: "inputNumber", field: "confirmedMaxCost", title: "本次单图 CNY 上限（必须大于 0）", value: 0, props: { min: 0, max: 100, step: 0.01 } }],
    },
    {
      id: "zhenzhen-video-muse",
      label: "真真 Muse Video",
      type: "video",
      mode: ["text", "singleImage"],
      audio: true,
      imageRatios: ["adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"],
      durationResolutionMap: [{ duration: [2, 3, 4, 5, 6, 7, 8, 9, 10], resolution: ["720P", "1080P", "1088P"] }],
      rules: [{ type: "inputNumber", field: "confirmedMaxCost", title: "本次单镜头 CNY 上限（必须大于 0）", value: 0, props: { min: 0, max: 10000, step: 0.01 } }],
    },
    {
      id: "minimax-h3-comfyui-max",
      label: "MiniMax H3 ComfyUI Max（图片参考顺序）",
      type: "video",
      mode: ["text", "singleImage", ["imageReference:6"]],
      audio: true,
      imageRatios: ["adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"],
      durationResolutionMap: [{ duration: [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30], resolution: ["480P", "768P", "1080P", "1088P", "2K", "4K"] }],
      rules: [{ type: "inputNumber", field: "confirmedMaxCost", title: "本次单镜头 CNY 上限（必须大于 0）", value: 0, props: { min: 0, max: 10000, step: 0.01 } }],
    },
  ] satisfies ProviderModel[],
  async getPrice(this: Context, request: { type: "image" | "video" | "audio"; model: string; prompt?: string; images?: unknown[]; duration?: number; ratio?: string; resolution?: string; size?: string; quality?: string; n?: number; other?: Record<string, unknown> }) {
    if (request.type === "audio") return { price: "未知", tips: "真真 AI 当前未配置音频模型。" };
    const payload = request.type === "image"
      ? imagePayload({ model: request.model, prompt: request.prompt || "", size: request.size, ratio: request.ratio, quality: request.quality, n: request.n, other: request.other }, [])
      : videoPayload({ model: request.model, prompt: request.prompt || "", duration: request.duration, resolution: request.resolution, ratio: request.ratio, other: request.other }, []);
    try {
      const quote = await estimate(this, request.type, payload);
      return quote.amount === null
        ? { price: "未知", tips: "真真 AI 报价响应未返回 amount，不会显示为 0。" }
        : { price: quote.currency + " " + quote.amount.toFixed(4), tips: "来自 /v1/" + request.type + "/generations/estimate；提交前仍会按节点中的 CNY 上限复核。" };
    } catch (error) {
      return { price: "未知", tips: this.tool.errorMessage(error) || "报价暂时不可用，不会显示为 0。" };
    }
  },
  async getBalance(this: Context) {
    const payload = await requestJson(this, "GET", "/api/usage/wallet/");
    const data = payload.data && typeof payload.data === "object" ? payload.data as Record<string, unknown> : payload;
    const amount = Number(data.amount ?? data.balance);
    if (!Number.isFinite(amount)) throw new Error("真真 AI 钱包响应未返回余额");
    return { balance: amount, unit: typeof data.currency === "string" && data.currency ? data.currency : "CNY" };
  },
  async generateImage(this: Context, request: ImageRequest): Promise<MediaAsset[]> {
    return generate(this, request, "image");
  },
  async generateVideo(this: Context, request: VideoRequest): Promise<MediaAsset[]> {
    return generate(this, request, "video");
  },
  async resumeTask(this: Context, data: ProviderTaskData): Promise<MediaAsset[]> {
    if (data.kind !== "solodramaZhenzhen" || typeof data.taskId !== "string" || !data.taskId
      || (data.mediaType !== "image" && data.mediaType !== "video") || typeof data.deadline !== "number" || !Number.isFinite(data.deadline)) {
      throw new Error("真真 AI 任务恢复数据无效");
    }
    return awaitResult(this, data as ZhenzhenTaskData);
  },
};