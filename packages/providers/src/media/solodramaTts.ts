type TtsProtocol = "openai" | "indexTts";
type ProviderFormRule = { type: string; field: string; title: string; value: unknown; props?: Record<string, unknown> };
type MediaInput = { type: "url"; url: string; mimeType?: string; name?: string } | { type: "base64"; data: string; mimeType: string; name?: string } | { type: "binary"; data: Uint8Array; mimeType: string; name?: string };
type MediaAsset = MediaInput & { mediaType: "image" | "video" | "audio" };
type AudioRequest = {
  model: string;
  text?: string;
  prompt?: string;
  audios?: (MediaInput & { text?: string })[];
  voice?: string;
  speed?: number;
  volume?: number;
  pitch?: number;
  emotion?: string;
  language?: string;
  normalizeText?: boolean;
  format?: string;
  sampleRate?: number;
  bitrateKbps?: number;
  other?: Record<string, unknown>;
};
type Context = {
  config: {
    protocol?: TtsProtocol;
    baseUrl?: string;
    apiKey?: string;
    model?: string;
    defaultVoice?: string;
    language?: string;
    format?: string;
    timeoutSeconds?: number;
    extraHeadersJson?: string;
    extraBodyJson?: string;
  };
  signal?: AbortSignal;
  tool: { fetch: typeof fetch; errorMessage(value: unknown): string };
};

function stringValue(value: unknown) { return typeof value === "string" ? value.trim() : ""; }
function numberValue(value: unknown) { const number = Number(value); return Number.isFinite(number) ? number : undefined; }
function localUrl(value: string) { return /^https?:\/\/(?:127\.0\.0\.1|localhost|\[::1\])(?::\d+)?(?:\/|$)/i.test(value); }
function endpointOf(baseUrl: string) {
  const base = (baseUrl || "http://127.0.0.1:8000").replace(/\/+$/, "");
  return /\/v1\/audio\/speech$/i.test(base) ? base : `${base}/v1/audio/speech`;
}
function parseObject(value: unknown, label: string) {
  if (typeof value !== "string" || !value.trim()) return {};
  try {
    const parsed: unknown = JSON.parse(value);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("必须是 JSON 对象");
    return parsed as Record<string, unknown>;
  } catch (error) {
    throw new Error(`${label} JSON 无效：${error instanceof Error ? error.message : String(error)}`);
  }
}
async function generateAudio(this: Context, request: AudioRequest): Promise<MediaAsset[]> {
  const text = (request.text ?? request.prompt ?? "").trim();
  if (!text) throw new Error("请输入待朗读文本或语音提示词");
  const protocol = this.config.protocol ?? "openai";
  const endpoint = endpointOf(this.config.baseUrl ?? "");
  const other = request.other ?? {};
  const voice = stringValue(other.voice) || request.voice || this.config.defaultVoice || (protocol === "indexTts" ? "alice" : "alloy");
  const speed = numberValue(other.speed) ?? request.speed ?? 1;
  const format = request.format || this.config.format || "mp3";
  const language = request.language || this.config.language || "zh-CN";
  const emotion = stringValue(other.emotion) || request.emotion || "";
  const instructions = stringValue(other.instructions);
  const durationFactor = numberValue(other.durationFactor);
  const temperature = numberValue(other.temperature);
  const extraBody = parseObject(this.config.extraBodyJson, "附加请求体");
  const body: Record<string, unknown> = {
    ...extraBody,
    model: this.config.model || request.model || (protocol === "indexTts" ? "indextts" : "tts-1"),
    input: text,
    voice,
    response_format: format,
    speed,
  };
  if (protocol === "indexTts") {
    body.language = language;
    if (emotion) body.emotion = emotion;
    if (instructions) body.instructions = instructions;
    const generation: Record<string, unknown> = {
      ...(extraBody.generation && typeof extraBody.generation === "object" && !Array.isArray(extraBody.generation) ? extraBody.generation as Record<string, unknown> : {}),
      ...(durationFactor !== undefined ? { duration_factor: durationFactor } : {}),
      ...(temperature !== undefined ? { temperature } : {}),
    };
    if (Object.keys(generation).length) body.generation = generation;
  } else if (instructions) {
    body.instructions = instructions;
  }
  const headers: Record<string, string> = { "Content-Type": "application/json", Accept: "audio/*,application/octet-stream", ...parseObject(this.config.extraHeadersJson, "附加请求头") as Record<string, string> };
  if (this.config.apiKey?.trim()) headers.Authorization = `Bearer ${this.config.apiKey.trim().replace(/^Bearer\s+/i, "")}`;
  const timeout = Math.max(10, this.config.timeoutSeconds ?? 300);
  const signal = this.signal ? AbortSignal.any([this.signal, AbortSignal.timeout(timeout * 1000)]) : AbortSignal.timeout(timeout * 1000);
  const response = await this.tool.fetch(endpoint, { method: "POST", headers, body: JSON.stringify(body), signal });
  if (!response.ok) {
    const message = await response.text().catch(() => "");
    throw new Error(`TTS 请求失败（${response.status}）：${this.tool.errorMessage(message) || "供应商未返回可读错误"}`);
  }
  const bytes = new Uint8Array(await response.arrayBuffer());
  if (!bytes.length) throw new Error("TTS 服务返回了空音频");
  const contentType = response.headers.get("content-type")?.toLowerCase() || "";
  const mimeType = contentType.startsWith("audio/") ? contentType.split(";")[0]! : format === "wav" ? "audio/wav" : format === "flac" ? "audio/flac" : "audio/mpeg";
  return [{ type: "binary", data: bytes, mimeType, mediaType: "audio" }];
}
export default {
  id: "solodramaTts",
  label: "SoloDrama TTS",
  icon: "",
  version: "1.0.0",
  readme: `# SoloDrama TTS

支持 OpenAI TTS 兼容接口与本地/自建 IndexTTS 2.5。

- OpenAI 兼容：\`POST {baseUrl}/v1/audio/speech\`
- IndexTTS：额外发送 \`language\`、\`emotion\`、\`instructions\` 和 \`generation.duration_factor\`。
- 本地地址默认成本为 0；第三方地址费用未知时不会显示为 0。
- 音色、语速、情绪、时长系数和采样温度由模型 rules 渲染到音频生成节点。`,
  rules: [
    { type: "select", field: "protocol", title: "接口协议", value: "openai", options: [{ label: "OpenAI TTS 兼容接口", value: "openai" }, { label: "IndexTTS 2.5", value: "indexTts" }] },
    { type: "input", field: "baseUrl", title: "服务地址", value: "http://127.0.0.1:8000", props: { placeholder: "http://127.0.0.1:8000 或第三方 API 根地址" } },
    { type: "input", field: "apiKey", title: "API Key（本地可留空）", value: "", props: { type: "password", showPassword: true, autocomplete: "off" } },
    { type: "input", field: "model", title: "请求模型名", value: "indextts" },
    { type: "input", field: "defaultVoice", title: "默认音色 ID", value: "alice" },
    { type: "input", field: "language", title: "默认语言", value: "zh-CN" },
    { type: "select", field: "format", title: "默认输出格式", value: "mp3", options: [{ label: "MP3", value: "mp3" }, { label: "WAV", value: "wav" }, { label: "FLAC", value: "flac" }, { label: "OPUS", value: "opus" }, { label: "PCM", value: "pcm" }] },
    { type: "inputNumber", field: "timeoutSeconds", title: "请求超时（秒）", value: 300, props: { min: 10, max: 1800, step: 10 } },
    { type: "textarea", field: "extraHeadersJson", title: "附加请求头 JSON", value: "{}", props: { rows: 3 } },
    { type: "textarea", field: "extraBodyJson", title: "附加请求体 JSON", value: "{}", props: { rows: 3 } },
  ],
  models: [
    { id: "indexTts25", label: "IndexTTS 2.5", type: "audio" as const, voices: [{ title: "自定义音色 ID", voice: "alice" }], rules: [
      { type: "input", field: "voice", title: "音色 ID", value: "", props: { placeholder: "例如：alice，或第三方服务支持的声音名称" } },
      { type: "inputNumber", field: "speed", title: "语速倍率", value: 1, props: { min: 0.25, max: 4, step: 0.05 } },
      { type: "input", field: "emotion", title: "情绪提示（可选）", value: "", props: { placeholder: "例如：克制、紧张、温柔" } },
      { type: "input", field: "instructions", title: "表演说明（可选）", value: "" },
      { type: "inputNumber", field: "durationFactor", title: "IndexTTS 时长系数", value: 1, props: { min: 0.5, max: 2, step: 0.05 } },
      { type: "inputNumber", field: "temperature", title: "采样温度（可选）", value: 0.8, props: { min: 0, max: 2, step: 0.05 } },
    ] },
    { id: "openaiTtsCompatible", label: "OpenAI TTS 兼容", type: "audio" as const, voices: [{ title: "自定义音色 ID", voice: "alloy" }], rules: [
      { type: "input", field: "voice", title: "音色 ID", value: "", props: { placeholder: "例如：alloy，或第三方服务支持的声音名称" } },
      { type: "inputNumber", field: "speed", title: "语速倍率", value: 1, props: { min: 0.25, max: 4, step: 0.05 } },
      { type: "input", field: "emotion", title: "情绪提示（可选）", value: "" },
      { type: "input", field: "instructions", title: "表演说明（可选）", value: "" },
      { type: "inputNumber", field: "durationFactor", title: "IndexTTS 时长系数", value: 1, props: { min: 0.5, max: 2, step: 0.05 } },
      { type: "inputNumber", field: "temperature", title: "采样温度（可选）", value: 0.8, props: { min: 0, max: 2, step: 0.05 } },
    ] },
  ],
  generateAudio,
  getPrice(this: Context, request: ProviderPriceRequest) {
    if (request.type !== "audio") return Promise.resolve(null);
    const baseUrl = typeof this.config.baseUrl === "string" ? this.config.baseUrl : "";
    return Promise.resolve(localUrl(baseUrl) ? { price: "0", tips: "本地或自建 TTS 服务，未产生供应商费用" } : null);
  },
};
