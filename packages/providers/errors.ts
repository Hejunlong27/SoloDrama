export type ProviderErrorCode =
  | "NETWORK_UNREACHABLE"
  | "DNS_FAILED"
  | "TLS_FAILED"
  | "AUTH_INVALID"
  | "MODEL_NOT_FOUND"
  | "RATE_LIMITED"
  | "QUOTA_EXCEEDED"
  | "REQUEST_TIMEOUT"
  | "INVALID_RESPONSE"
  | "CAPABILITY_UNSUPPORTED"
  | "UPSTREAM_FAILED"
  | "UNKNOWN";

export type ProviderSubmissionState = "submitting" | "submitted" | "accepted" | "unknown";

export type ProviderErrorDetails = {
  providerCode: ProviderErrorCode;
  status: number;
  retryable: boolean;
};

const providerErrorCodes = new Set<ProviderErrorCode>([
  "NETWORK_UNREACHABLE",
  "DNS_FAILED",
  "TLS_FAILED",
  "AUTH_INVALID",
  "MODEL_NOT_FOUND",
  "RATE_LIMITED",
  "QUOTA_EXCEEDED",
  "REQUEST_TIMEOUT",
  "INVALID_RESPONSE",
  "CAPABILITY_UNSUPPORTED",
  "UPSTREAM_FAILED",
  "UNKNOWN",
]);

const messages: Record<ProviderErrorCode, string> = {
  NETWORK_UNREACHABLE: "无法连接到供应商服务，请检查地址、网络和代理配置",
  DNS_FAILED: "供应商域名解析失败，请检查地址或 DNS 配置",
  TLS_FAILED: "供应商 TLS 证书或加密连接验证失败",
  AUTH_INVALID: "供应商鉴权失败，请检查 API Key 或访问权限",
  MODEL_NOT_FOUND: "供应商未找到所选模型或资源",
  RATE_LIMITED: "供应商请求过于频繁，请稍后重试",
  QUOTA_EXCEEDED: "供应商额度或余额不足",
  REQUEST_TIMEOUT: "供应商请求超时，结果可能尚未确认",
  INVALID_RESPONSE: "供应商返回了无法识别的响应",
  CAPABILITY_UNSUPPORTED: "供应商不支持当前请求的能力或参数",
  UPSTREAM_FAILED: "供应商服务执行失败，请稍后重试",
  UNKNOWN: "供应商请求失败",
};

type FailureShape = {
  name?: unknown;
  message?: unknown;
  code?: unknown;
  status?: unknown;
  retryable?: unknown;
  providerCode?: unknown;
  upstreamCode?: unknown;
  cause?: unknown;
};

function text(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

function statusFromMessage(message: string) {
  const match = /\b(?:HTTP|status(?:\s+code)?)\s*[:：]?\s*([45]\d\d)\b/i.exec(message);
  return match ? Number(match[1]) : 0;
}

function shapeOf(value: unknown): FailureShape {
  return value && typeof value === "object" ? value as FailureShape : {};
}

export function isProviderErrorCode(value: unknown): value is ProviderErrorCode {
  return typeof value === "string" && providerErrorCodes.has(value as ProviderErrorCode);
}

export function classifyProviderError(cause: unknown, safeMessage = ""): ProviderErrorDetails {
  const source = shapeOf(cause);
  const nested = shapeOf(source.cause);
  const code = text(source.code).toUpperCase();
  const name = text(source.name);
  const message = [safeMessage, text(source.message), text(nested.message)].filter(Boolean).join("\n");
  const rawStatus = Number(source.status ?? nested.status);
  const status = Number.isInteger(rawStatus) && rawStatus >= 400 && rawStatus <= 599 ? rawStatus : statusFromMessage(message);
  const matches = (pattern: RegExp) => pattern.test(message);

  if (isProviderErrorCode(source.providerCode)) {
    return { providerCode: source.providerCode, status: status || providerStatus(source.providerCode), retryable: source.retryable === true };
  }
  if (code === "ETIMEDOUT" || code === "UND_ERR_CONNECT_TIMEOUT" || name === "TimeoutError" || status === 408 || status === 504 || matches(/timed?\s*out|timeout|超时/i)) {
    return { providerCode: "REQUEST_TIMEOUT", status: 504, retryable: true };
  }
  if (["ENOTFOUND", "EAI_AGAIN"].includes(code) || matches(/\b(?:dns|getaddrinfo|name resolution)\b|域名解析/i)) {
    return { providerCode: "DNS_FAILED", status: 502, retryable: true };
  }
  if (/^(?:CERT_|ERR_TLS_|UNABLE_TO_VERIFY_|DEPTH_ZERO_|SELF_SIGNED_)/.test(code)
    || matches(/\b(?:tls|certificate|x509)\b|证书|加密连接/i)) {
    return { providerCode: "TLS_FAILED", status: 502, retryable: false };
  }
  if (["ECONNREFUSED", "ECONNRESET", "EHOSTUNREACH", "ENETUNREACH", "EPIPE", "UND_ERR_SOCKET"].includes(code)
    || (name === "TypeError" && matches(/fetch failed|network|连接失败/i))
    || matches(/network unreachable|connection refused|fetch failed|无法连接|连接失败/i)) {
    return { providerCode: "NETWORK_UNREACHABLE", status: 502, retryable: true };
  }
  if (status === 401 || status === 403 || matches(/\b(?:unauthori[sz]ed|forbidden|invalid api key|authentication)\b|鉴权失败|密钥无效|缺少.*api key/i)) {
    return { providerCode: "AUTH_INVALID", status: status === 403 ? 403 : 401, retryable: false };
  }
  if (status === 402 || matches(/quota|insufficient (?:balance|quota|credits)|余额不足|额度不足|额度已用尽/i)) {
    return { providerCode: "QUOTA_EXCEEDED", status: 402, retryable: false };
  }
  if (status === 429 || matches(/rate limit|too many requests|请求过于频繁|限流/i)) {
    return { providerCode: "RATE_LIMITED", status: 429, retryable: true };
  }
  if (status === 404 && matches(/model|模型|not found|不存在/i)) {
    return { providerCode: "MODEL_NOT_FOUND", status: 404, retryable: false };
  }
  if (matches(/unsupported|not supported|capability|不支持|能力不足/i)) {
    return { providerCode: "CAPABILITY_UNSUPPORTED", status: 422, retryable: false };
  }
  if (name === "SyntaxError" || matches(/invalid json|unexpected token|invalid response|响应格式|缺少.*(?:taskId|prompt_id|结果)/i)) {
    return { providerCode: "INVALID_RESPONSE", status: 502, retryable: false };
  }
  if (status >= 500 || matches(/upstream|server error|internal server error|服务端错误|供应商服务失败/i)) {
    return { providerCode: "UPSTREAM_FAILED", status: status >= 500 ? status : 502, retryable: true };
  }
  return { providerCode: "UNKNOWN", status: status || 500, retryable: false };
}

function providerStatus(code: ProviderErrorCode) {
  if (code === "AUTH_INVALID") return 401;
  if (code === "MODEL_NOT_FOUND") return 404;
  if (code === "RATE_LIMITED") return 429;
  if (code === "QUOTA_EXCEEDED") return 402;
  if (code === "REQUEST_TIMEOUT") return 504;
  if (code === "CAPABILITY_UNSUPPORTED") return 422;
  if (code === "UNKNOWN") return 500;
  return 502;
}

export function providerErrorMessage(code: ProviderErrorCode) {
  return messages[code];
}

/** Keep existing domain codes such as MEDIA_TASK_FAILED while adding safe Provider diagnostics. */
export function annotateProviderError(cause: unknown, safeMessage = ""): Error {
  const details = classifyProviderError(cause, safeMessage);
  const source = shapeOf(cause);
  const error = cause instanceof Error ? cause : new Error(safeMessage || providerErrorMessage(details.providerCode), { cause });
  if (safeMessage) error.message = safeMessage;
  else if (!error.message) error.message = providerErrorMessage(details.providerCode);
  const target = error as Error & {
    code?: string;
    providerCode?: ProviderErrorCode;
    status?: number;
    retryable?: boolean;
    upstreamCode?: string;
  };
  if (typeof source.code === "string") target.code ??= source.code;
  target.providerCode ??= details.providerCode;
  target.status ??= details.status;
  target.retryable ??= typeof source.retryable === "boolean" ? source.retryable : details.retryable;
  const upstreamCode = text(source.upstreamCode) || text(source.code);
  if (upstreamCode && !isProviderErrorCode(upstreamCode)) target.upstreamCode ??= upstreamCode;
  return target;
}