import { randomUUID } from "node:crypto";
import { remoteAddress } from "@/utils/workspace/download";
import { assertProviderUrl } from "@/utils/media/providerUrl";
import type { RuntimeComfyInstance, RuntimeComfyWorkflow } from "./store";

export type ComfyHealth = {
  status: "online" | "offline" | "degraded" | "unknown";
  checkedAt: number;
  latency?: number;
  version?: string;
  system?: Record<string, unknown>;
  features?: string[];
  nodeCount?: number;
  queueRunning?: number;
  queuePending?: number;
  websocket?: "connected" | "unavailable" | "unknown";
  error?: string;
};

export type ConnectionProbe = { health: ComfyHealth; nodeNames: string[]; features: string[] };

function endpointUrl(instance: RuntimeComfyInstance, path: string) {
  const url = new URL(path, instance.endpoint.endsWith("/") ? instance.endpoint : `${instance.endpoint}/`);
  if (!instance.allowPrivateNetwork) remoteAddress(url.href);
  else assertProviderUrl(url);
  return url;
}

function websocketUrl(instance: RuntimeComfyInstance) {
  if (instance.websocketEndpoint) {
    const url = new URL(instance.websocketEndpoint);
    if (!["ws:", "wss:"].includes(url.protocol) || url.username || url.password) throw Object.assign(new Error("WebSocket 地址无效"), { status: 400 });
    return url;
  }
  const url = new URL(instance.endpoint);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = `${url.pathname.replace(/\/+$/, "")}/ws`;
  url.search = `?clientId=${encodeURIComponent(`solodrama-${randomUUID()}`)}`;
  url.hash = "";
  if (!instance.allowPrivateNetwork) remoteAddress(url.href.replace(/^ws/, "http"));
  else assertProviderUrl(url.href.replace(/^ws/, "http"));
  return url;
}

function headers(instance: RuntimeComfyInstance, json = false) {
  const token = instance.token.trim().replace(/^Bearer\s+/i, "");
  const result: Record<string, string> = { Accept: "application/json", ...instance.customHeaders };
  if (json) result["Content-Type"] = "application/json";
  if (instance.authMode === "bearer" && token) result.Authorization = `Bearer ${token}`;
  if (instance.authMode === "header" && instance.authHeaderName && token) result[instance.authHeaderName] = instance.token.trim();
  return result;
}

async function request(instance: RuntimeComfyInstance, path: string, init: RequestInit = {}) {
  const url = endpointUrl(instance, path);
  const signal = init.signal ?? AbortSignal.timeout(instance.connectionTimeoutMs);
  return fetch(url, { ...init, headers: { ...headers(instance, !!init.body), ...(init.headers as Record<string, string> | undefined) }, redirect: "error", signal });
}

async function json(response: Response, limit = 32 * 1024 * 1024): Promise<Record<string, unknown>> {
  const length = Number(response.headers.get("content-length"));
  if (length > limit) throw Object.assign(new Error("ComfyUI 响应超过大小限制"), { status: 502 });
  const text = await response.text();
  if (Buffer.byteLength(text, "utf8") > limit) throw Object.assign(new Error("ComfyUI 响应超过大小限制"), { status: 502 });
  try {
    const value: unknown = JSON.parse(text);
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error();
    return value as Record<string, unknown>;
  } catch { throw Object.assign(new Error("ComfyUI 返回了无效 JSON"), { status: 502 }); }
}

function errorForStatus(status: number) {
  if (status === 401 || status === 403) return "鉴权失败，请检查 Token 或自定义 Header";
  if (status === 404) return "ComfyUI 接口不存在，请检查服务地址和版本";
  if (status === 429) return "ComfyUI 请求过于频繁";
  if (status >= 500) return `ComfyUI 服务异常（HTTP ${status}）`;
  return `ComfyUI 请求失败（HTTP ${status}）`;
}

async function optionalJson(instance: RuntimeComfyInstance, path: string) {
  const response = await request(instance, path);
  if (!response.ok) throw Object.assign(new Error(errorForStatus(response.status)), { status: response.status });
  return json(response);
}

function queueCounts(payload: Record<string, unknown>) {
  const running = Array.isArray(payload.queue_running) ? payload.queue_running.length : 0;
  const pending = Array.isArray(payload.queue_pending) ? payload.queue_pending.length : 0;
  return { running, pending };
}

function featureNames(value: Record<string, unknown>) {
  return Object.keys(value).filter(key => value[key] !== false && value[key] != null).sort();
}

async function websocketProbe(instance: RuntimeComfyInstance) {
  const url = websocketUrl(instance);
  return new Promise<"connected" | "unavailable">(resolve => {
    let settled = false;
    let socket: WebSocket | undefined;
    const finish = (value: "connected" | "unavailable") => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      try { socket?.close(); } catch { /* 探测连接关闭失败不影响结果。 */ }
      resolve(value);
    };
    const timer = setTimeout(() => finish("unavailable"), Math.min(5000, instance.connectionTimeoutMs));
    try {
      socket = new WebSocket(url);
      socket.onopen = () => finish("connected");
      socket.onerror = () => finish("unavailable");
      socket.onclose = () => finish("unavailable");
    } catch { finish("unavailable"); }
  });
}

export async function probeInstance(instance: RuntimeComfyInstance): Promise<ConnectionProbe> {
  const startedAt = performance.now();
  let system: Record<string, unknown>;
  try {
    system = await optionalJson(instance, "system_stats");
  } catch (error) {
    return { health: { status: "offline", checkedAt: Date.now(), latency: Math.round(performance.now() - startedAt), error: error instanceof Error ? error.message : "无法连接 ComfyUI" }, nodeNames: [], features: [] };
  }
  let nodeNames: string[] = [];
  let features: string[] = [];
  let queueRunning: number | undefined;
  let queuePending: number | undefined;
  let degraded = false;
  try { nodeNames = Object.keys(await optionalJson(instance, "object_info")).sort(); }
  catch { degraded = true; }
  try { const counts = queueCounts(await optionalJson(instance, "queue")); queueRunning = counts.running; queuePending = counts.pending; }
  catch { degraded = true; }
  try { features = featureNames(await optionalJson(instance, "features")); }
  catch { /* features 是可选扩展，不降低基础可用性。 */ }
  const websocket = await websocketProbe(instance).catch(() => "unavailable" as const);
  if (websocket !== "connected") degraded = true;
  const versionValue = system.system && typeof system.system === "object" ? (system.system as Record<string, unknown>).comfyui_version : undefined;
  return {
    health: {
      status: degraded ? "degraded" : "online", checkedAt: Date.now(), latency: Math.round(performance.now() - startedAt),
      version: typeof versionValue === "string" ? versionValue : undefined, system, features, nodeCount: nodeNames.length,
      queueRunning, queuePending, websocket,
    },
    nodeNames, features,
  };
}

export async function verifyWorkflow(instance: RuntimeComfyInstance, workflow: RuntimeComfyWorkflow) {
  const probe = await probeInstance(instance);
  if (probe.health.status === "offline") return { compatible: false, missingNodes: workflow.requiredNodes, missingModels: workflow.requiredModels, health: probe.health, nodeNames: [] as string[] };
  const available = new Set(probe.nodeNames);
  const missingNodes = workflow.requiredNodes.filter(node => !available.has(node));
  return {
    compatible: missingNodes.length === 0 && workflow.requiredModels.length === 0,
    missingNodes, missingModels: workflow.requiredModels, health: probe.health, nodeNames: probe.nodeNames,
  };
}

export async function submitWorkflow(instance: RuntimeComfyInstance, workflow: RuntimeComfyWorkflow, prompt: Record<string, unknown>) {
  const response = await request(instance, "prompt", {
    method: "POST", body: JSON.stringify({ prompt, client_id: `solodrama-${randomUUID()}` }),
  });
  if (!response.ok) throw Object.assign(new Error(errorForStatus(response.status)), { status: response.status });
  const payload = await json(response);
  if (typeof payload.prompt_id !== "string" || !payload.prompt_id) throw Object.assign(new Error("ComfyUI 提交响应缺少 prompt_id"), { status: 502, code: "MEDIA_TASK_FAILED" });
  return payload.prompt_id;
}

export async function uploadImage(instance: RuntimeComfyInstance, data: Uint8Array, mimeType: string, name: string) {
  const extension = mimeType.split("/")[1]?.replace("jpeg", "jpg").replace(/[^a-z0-9]/gi, "") || "png";
  const safeName = name.replace(/\.[^.]+$/, "").replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 48) || "reference";
  const unique = `solodrama_${randomUUID().replaceAll("-", "")}_${safeName}`;
  const form = new FormData();
  form.append("image", new Blob([data.slice().buffer as ArrayBuffer], { type: mimeType }), `${unique}.${extension}`);
  form.append("overwrite", "false");
  const response = await request(instance, "upload/image", { method: "POST", body: form });
  if (!response.ok) throw Object.assign(new Error(errorForStatus(response.status)), { status: response.status });
  const payload = await json(response);
  if (typeof payload.name !== "string" || !payload.name) throw Object.assign(new Error("ComfyUI 上传响应缺少 name"), { status: 502 });
  return typeof payload.subfolder === "string" && payload.subfolder ? `${payload.subfolder.replace(/^\/+|\/+$/g, "")}/${payload.name}` : payload.name;
}

export async function cancelQueuedPrompt(instance: RuntimeComfyInstance, promptId: string) {
  const queue = await optionalJson(instance, "queue");
  const pending = Array.isArray(queue.queue_pending) ? queue.queue_pending : [];
  if (!pending.some(item => Array.isArray(item) && item[1] === promptId)) return false;
  const response = await request(instance, "queue", { method: "POST", body: JSON.stringify({ delete: [promptId] }) });
  return response.ok;
}

function outputFiles(history: Record<string, unknown>, instance: RuntimeComfyInstance) {
  const outputs = history.outputs && typeof history.outputs === "object" && !Array.isArray(history.outputs) ? history.outputs as Record<string, unknown> : {};
  const files: { url: URL; mediaType: "image" | "video" | "audio"; filename: string; mimeType?: string }[] = [];
  for (const output of Object.values(outputs)) {
    if (!output || typeof output !== "object" || Array.isArray(output)) continue;
    for (const [key, entries] of Object.entries(output as Record<string, unknown>)) {
      if (!Array.isArray(entries)) continue;
      for (const entry of entries) {
        if (!entry || typeof entry !== "object" || Array.isArray(entry)) continue;
        const value = entry as Record<string, unknown>;
        const filename = typeof value.filename === "string" ? value.filename : "";
        const direct = typeof value.url === "string" ? value.url : "";
        const mediaType = /audio|\.mp3|\.wav|\.flac|\.ogg|\.m4a|\.opus/i.test(`${key} ${filename} ${direct}`) ? "audio"
          : /video|\.mp4|\.webm|\.mov|\.mkv/i.test(`${key} ${filename} ${direct}`) ? "video"
          : /image|\.png|\.jpe?g|\.webp|\.gif|\.avif|\.bmp/i.test(`${key} ${filename} ${direct}`) ? "image" : undefined;
        if (!mediaType) continue;
        const url = direct && /^https?:/i.test(direct) ? new URL(direct) : endpointUrl(instance, `view?${new URLSearchParams({
          filename, subfolder: typeof value.subfolder === "string" ? value.subfolder : "", type: typeof value.type === "string" ? value.type : "output",
        })}`);
        if (direct && /^https?:/i.test(direct)) {
          if (instance.allowPrivateNetwork) assertProviderUrl(url);
          else remoteAddress(url.href);
        }
        files.push({ url, mediaType, filename });
      }
    }
  }
  return files;
}

export async function waitForResult(instance: RuntimeComfyInstance, promptId: string, deadline: number, expected: "image" | "video" | "audio", signal?: AbortSignal) {
  const wsUrl = websocketUrl(instance);
  const ws = new WebSocket(wsUrl);
  let wake: (() => void) | undefined;
  let socketError: unknown;
  ws.onmessage = event => {
    try {
      const message = JSON.parse(String(event.data)) as Record<string, unknown>;
      if (["executed", "execution_error", "execution_interrupted"].includes(String(message.type ?? ""))) wake?.();
    } catch { /* 忽略非 JSON 扩展事件，最终以 history 为准。 */ }
  };
  ws.onerror = event => { socketError = event; wake?.(); };
  ws.onclose = () => wake?.();
  try {
    while (Date.now() <= deadline) {
      signal?.throwIfAborted();
      try {
        const response = await request(instance, `history/${encodeURIComponent(promptId)}`, { signal });
        if (response.ok) {
          const payload = await json(response);
          const raw = payload[promptId];
          const history = raw && typeof raw === "object" && !Array.isArray(raw) ? raw as Record<string, unknown> : undefined;
          const status = history?.status && typeof history.status === "object" ? history.status as Record<string, unknown> : {};
          if (status.status_str === "error") throw Object.assign(new Error("ComfyUI 任务执行失败"), { code: "MEDIA_TASK_FAILED" });
          if (status.completed === true) {
            const files = outputFiles(history!, instance).filter(file => file.mediaType === expected).slice(0, 8);
            if (!files.length) throw Object.assign(new Error("ComfyUI 任务完成但没有返回可用媒体"), { code: "MEDIA_TASK_FAILED" });
            const assets: MediaAsset[] = [];
            for (const file of files) {
              const downloaded = await fetch(file.url, { headers: headers(instance), redirect: "error", signal });
              if (!downloaded.ok) throw Object.assign(new Error(errorForStatus(downloaded.status)), { status: downloaded.status });
              assets.push({ mediaType: expected, type: "binary", data: new Uint8Array(await downloaded.arrayBuffer()), mimeType: downloaded.headers.get("content-type") || `${expected}/octet-stream`, name: file.filename });
            }
            return assets;
          }
        }
      } catch (error) {
        if (signal?.aborted) throw error;
      }
      await Promise.race([
        new Promise<void>(resolve => setTimeout(resolve, 1500)),
        new Promise<void>(resolve => { wake = resolve; }),
      ]).finally(() => { wake = undefined; });
    }
    if (socketError) throw Object.assign(new Error("ComfyUI WebSocket 和 HTTP 查询均未完成任务"), { retryable: true });
    throw Object.assign(new Error("ComfyUI 任务等待超时；任务可能仍在执行"), { retryable: true });
  } finally {
    try { ws.close(); } catch { /* 已经断开。 */ }
  }
}

export async function queueLoad(instance: RuntimeComfyInstance) {
  try { return queueCounts(await optionalJson(instance, "queue")); }
  catch { return { running: 0, pending: 0 }; }
}