/** SoloDrama Cloud ComfyUI Hub Provider，由宿主注入统一的云端 ComfyUI Runtime。 */

type MediaType = "image" | "video" | "audio";
type MediaInput =
  | { type: "url"; url: string; mimeType?: string; name?: string }
  | { type: "base64"; data: string; mimeType: string; name?: string }
  | { type: "binary"; data: Uint8Array; mimeType: string; name?: string };
type MediaAsset = MediaInput & { mediaType: MediaType };
type HubRequest = {
  model: string;
  prompt?: string;
  text?: string;
  images?: MediaInput[];
  videos?: MediaInput[];
  audios?: MediaInput[];
  firstFrame?: MediaInput;
  lastFrame?: MediaInput[];
  ratio?: string;
  size?: string;
  resolution?: string;
  duration?: number;
  generateAudio?: boolean;
  other?: Record<string, unknown>;
};
type Context = {
  signal?: AbortSignal;
  saveTaskData?: (data: ProviderTaskData) => Promise<void>;
  tool: {
    comfyHub?: {
      generate(mediaType: MediaType, request: HubRequest, signal?: AbortSignal): Promise<MediaAsset[]>;
      resume(data: ProviderTaskData, signal?: AbortSignal): Promise<MediaAsset[]>;
    };
  };
};

function hub(context: Context) {
  if (!context.tool.comfyHub) throw new Error("云端 ComfyUI Runtime 尚未初始化");
  return context.tool.comfyHub;
}

export default {
  id: "solodramaComfyHub",
  label: "云端 ComfyUI",
  version: "1.0.0",
  readme: "统一连接任意兼容 ComfyUI 标准 API 的本地或云端实例。实例、认证和工作流在「设置 → 云端算力中心」管理。",
  rules: [],
  models: [],
  async getPrice() {
    return { price: "未知", tips: "费用由实例所在云平台结算；SoloDrama 不推定金额。" };
  },
  async generateImage(this: Context, request: HubRequest) {
    return hub(this).generate("image", request, this.signal);
  },
  async generateVideo(this: Context, request: HubRequest) {
    return hub(this).generate("video", request, this.signal);
  },
  async generateAudio(this: Context, request: HubRequest) {
    return hub(this).generate("audio", request, this.signal);
  },
  async resumeTask(this: Context, data: ProviderTaskData) {
    return hub(this).resume(data, this.signal);
  },
};