import type {
  Provider,
  ProviderDiagnosticCheck,
  ProviderDiagnosticCheckStatus,
  ProviderDiagnosticResult,
} from "@solodrama/providers";
import { classifyProviderError, providerErrorMessage } from "@solodrama/providers/errors";
import type { z } from "zod";
import { getProviderBaseUrl, providerSchema } from "@/utils/ai/provider";
import { loadMediaProviderSource } from "@/utils/media/provider";
import { requestNetwork } from "@/utils/network";

type MediaDiagnosticInput = {
  source: string;
  config: Record<string, unknown>;
  providerId: string;
  providerType?: string;
  signal?: AbortSignal;
};

type CheckResult = ProviderDiagnosticCheck & { latency?: number };

const secretFieldPattern = /api.?key|secret|token|password|authorization|cookie|credential|private.?key|access.?key|signature/i;

function check(name: string, status: ProviderDiagnosticCheckStatus, message?: string, errorCode?: string, latency?: number): CheckResult {
  return { name, status, ...(message ? { message } : {}), ...(errorCode ? { errorCode } : {}), ...(latency !== undefined ? { latency } : {}) };
}

function resultStatus(checks: ProviderDiagnosticCheck[]): ProviderDiagnosticResult["status"] {
  if (checks.some(item => item.status === "failed")) return "unhealthy";
  if (checks.some(item => item.status === "warning")) return "degraded";
  return checks.length ? "healthy" : "unknown";
}

function safeError(error: unknown) {
  const details = classifyProviderError(error);
  return { errorCode: details.providerCode, message: providerErrorMessage(details.providerCode) };
}

function mediaBaseUrl(provider: Provider, config: Record<string, unknown>) {
  const candidates = [config.apiUrl, config.baseUrl, provider.apiUrl, provider.modelsUrl];
  const routes = typeof config.routes === "string" ? config.routes : "";
  if (routes.trim()) {
    try {
      const parsed: unknown = JSON.parse(routes);
      if (Array.isArray(parsed)) candidates.push(...parsed.flatMap(item => item && typeof item === "object" && typeof (item as Record<string, unknown>).baseUrl === "string" ? [(item as Record<string, unknown>).baseUrl] : []));
    } catch { /* ACT: 路由格式错误由生成路径负责提示，诊断只记录无法探测地址。 */ }
  }
  for (const value of candidates) {
    if (typeof value !== "string" || !value.trim()) continue;
    try {
      const url = new URL(value.trim());
      if (/^https?:$/.test(url.protocol) && !url.username && !url.password) return url;
    } catch { return new URL("invalid:"); }
  }
  return undefined;
}

function requiredSecretFields(provider: Provider) {
  return (provider.rules ?? []).flatMap(rule => typeof rule.field === "string" && secretFieldPattern.test(rule.field) ? [rule.field] : []);
}

function capabilitiesOf(provider: Provider) {
  const types = new Set(provider.models.map(model => model.type));
  return [
    ...["image", "video", "audio", "text"].filter(type => types.has(type as Provider["models"][number]["type"])),
    ...(provider.getPrice ? ["price"] : []),
    ...(provider.getBalance ? ["balance"] : []),
    ...(provider.resumeTask ? ["resume"] : []),
  ];
}

export async function diagnoseMediaProvider(input: MediaDiagnosticInput): Promise<ProviderDiagnosticResult> {
  const startedAt = performance.now();
  const signal = input.signal ? AbortSignal.any([input.signal, AbortSignal.timeout(30000)]) : AbortSignal.timeout(30000);
  let provider: Awaited<ReturnType<typeof loadMediaProviderSource>>;
  try {
    provider = await loadMediaProviderSource(input.source, input.config, signal);
  } catch (error) {
    const failure = safeError(error);
    return {
      providerId: input.providerId, providerType: input.providerType ?? "media", status: "unhealthy",
      checks: [check("provider", "failed", failure.message, failure.errorCode, Math.round(performance.now() - startedAt))],
      latency: Math.round(performance.now() - startedAt), checkedAt: Date.now(),
    };
  }

  const checks: CheckResult[] = [];
  const secretFields = requiredSecretFields(provider);
  const missingSecrets = secretFields.filter(field => typeof input.config[field] !== "string" || !input.config[field].trim());
  const authName = typeof provider.config.authHeaderName === "string" ? provider.config.authHeaderName.trim() : "";
  const authValue = typeof provider.config.authHeaderValue === "string" ? provider.config.authHeaderValue.trim() : "";
  const authHeaderInvalid = !!authName !== !!authValue;
  checks.push(check("configuration", missingSecrets.length || authHeaderInvalid ? "failed" : "passed",
    missingSecrets.length ? `缺少配置：${missingSecrets.join("、")}` : authHeaderInvalid ? "鉴权 Header 名称和值必须同时填写" : "供应商配置已加载",
    missingSecrets.length ? "AUTH_INVALID" : authHeaderInvalid ? "INVALID_RESPONSE" : undefined));

  const url = mediaBaseUrl(provider, provider.config);
  let authFailed = false;
  if (!url) {
    checks.push(check("connectivity", "skipped", "供应商未声明可探测的 HTTP 地址"));
    checks.push(check("authentication", missingSecrets.length || authHeaderInvalid ? "failed" : secretFields.length ? "passed" : "skipped",
      missingSecrets.length || authHeaderInvalid ? "配置不完整" : secretFields.length ? "所需凭据已填写" : "未声明独立鉴权字段"));
  } else if (url.protocol === "invalid:") {
    checks.push(check("connectivity", "failed", "供应商地址格式无效", "INVALID_RESPONSE"));
    checks.push(check("authentication", "skipped", "无法探测无效地址"));
  } else {
    const requestStarted = performance.now();
    try {
      const response = await provider.tool.fetch(url, { method: "GET", redirect: "manual", signal });
      await response.body?.cancel();
      const latency = Math.round(performance.now() - requestStarted);
      authFailed = response.status === 401 || response.status === 403;
      if (authFailed) checks.push(check("connectivity", "passed", `服务可达，HTTP ${response.status}`, undefined, latency));
      else if (response.status >= 500) checks.push(check("connectivity", "warning", `服务可达但返回 HTTP ${response.status}`, "UPSTREAM_FAILED", latency));
      else checks.push(check("connectivity", "passed", `服务可达，HTTP ${response.status}`, undefined, latency));
      checks.push(check("authentication", authFailed ? "failed" : missingSecrets.length || authHeaderInvalid ? "failed" : secretFields.length ? "passed" : "skipped",
        authFailed ? "供应商拒绝了当前鉴权" : missingSecrets.length || authHeaderInvalid ? "配置不完整" : secretFields.length ? "鉴权请求已通过基础可达性检查" : "未声明独立鉴权字段",
        authFailed ? "AUTH_INVALID" : missingSecrets.length ? "AUTH_INVALID" : authHeaderInvalid ? "INVALID_RESPONSE" : undefined, latency));
    } catch (error) {
      const failure = safeError(error);
      checks.push(check("connectivity", "failed", failure.message, failure.errorCode, Math.round(performance.now() - requestStarted)));
      checks.push(check("authentication", "skipped", "连接失败，无法完成鉴权探测"));
    }
  }

  checks.push(check("models", provider.models.length ? "passed" : "failed", provider.models.length ? `已配置 ${provider.models.length} 个模型` : "供应商未声明模型", provider.models.length ? undefined : "MODEL_NOT_FOUND"));
  const capabilities = capabilitiesOf(provider);
  checks.push(check("capabilities", capabilities.length ? "passed" : "warning", capabilities.length ? capabilities.join("、") : "未声明可执行能力", capabilities.length ? undefined : "CAPABILITY_UNSUPPORTED"));

  if (provider.getBalance) {
    const balanceStarted = performance.now();
    try {
      const balance = await provider.getBalance.call(provider);
      checks.push(check("balance", "passed", `${balance.balance} ${balance.unit}`, undefined, Math.round(performance.now() - balanceStarted)));
    } catch (error) {
      const failure = safeError(error);
      checks.push(check("balance", "warning", failure.message, failure.errorCode, Math.round(performance.now() - balanceStarted)));
    }
  }

  checks.push(check("generation", "skipped", "实际生成测试需由用户在测试面板主动触发"));
  return {
    providerId: provider.id,
    providerType: input.providerType ?? "media",
    status: resultStatus(checks),
    checks,
    latency: Math.round(performance.now() - startedAt),
    checkedAt: Date.now(),
    capabilities,
  };
}

export async function diagnoseLanguageProvider(config: unknown, signal?: AbortSignal): Promise<ProviderDiagnosticResult> {
  const startedAt = performance.now();
  const parsed = providerSchema.safeParse(config);
  if (!parsed.success) {
    return {
      providerId: "unknown", providerType: "language", status: "unhealthy",
      checks: [check("configuration", "failed", "文本供应商配置无效", "INVALID_RESPONSE", Math.round(performance.now() - startedAt))],
      latency: Math.round(performance.now() - startedAt), checkedAt: Date.now(),
    };
  }
  const provider = parsed.data;
  const checks: CheckResult[] = [check("configuration", "passed", "供应商配置已加载")];
  const requestStarted = performance.now();
  const timeout = signal ? AbortSignal.any([signal, AbortSignal.timeout(30000)]) : AbortSignal.timeout(30000);
  const headers: Record<string, string> = { ...provider.headers };
  if (provider.protocol === "anthropic-messages") {
    if (provider.apiKey) headers["x-api-key"] = provider.apiKey;
    headers["anthropic-version"] ??= "2023-06-01";
  } else if (provider.apiKey) headers.Authorization = `Bearer ${provider.apiKey}`;
  try {
    const response = await requestNetwork(getProviderBaseUrl(provider.apiUrl, provider.protocol), { method: "GET", headers, signal: timeout, redirect: "manual" });
    await response.body?.cancel();
    const latency = Math.round(performance.now() - requestStarted);
    const authFailed = response.status === 401 || response.status === 403;
    checks.push(check("authentication", authFailed ? "failed" : "passed", authFailed ? "供应商拒绝了当前鉴权" : `鉴权请求可发送，HTTP ${response.status}`, authFailed ? "AUTH_INVALID" : undefined, latency));
    checks.push(check("connectivity", response.status >= 500 ? "warning" : "passed", response.status >= 500 ? `服务可达但返回 HTTP ${response.status}` : `服务可达，HTTP ${response.status}`, response.status >= 500 ? "UPSTREAM_FAILED" : undefined, latency));
  } catch (error) {
    const failure = safeError(error);
    checks.push(check("authentication", "skipped", "连接失败，无法完成鉴权探测"));
    checks.push(check("connectivity", "failed", failure.message, failure.errorCode, Math.round(performance.now() - requestStarted)));
  }
  checks.push(check("models", provider.models.length ? "passed" : "failed", provider.models.length ? `已配置 ${provider.models.length} 个模型` : "供应商未配置模型", provider.models.length ? undefined : "MODEL_NOT_FOUND"));
  const capabilities = ["text", provider.protocol];
  checks.push(check("capabilities", "passed", capabilities.join("、")));
  checks.push(check("generation", "skipped", "实际生成测试需由用户主动触发"));
  return { providerId: "language", providerType: "language", status: resultStatus(checks), checks, latency: Math.round(performance.now() - startedAt), checkedAt: Date.now(), capabilities };
}