import { BlockList, isIP } from "node:net";

const blockedV4 = new BlockList();
blockedV4.addSubnet("169.254.0.0", 16, "ipv4");
const blockedV6 = new BlockList();
blockedV6.addSubnet("fe80::", 10, "ipv6");
const blockedHosts = new Set([
  "metadata.google.internal",
  "metadata.google.internal.",
  "metadata.oraclecloud.com",
  "instance-data",
  "instance-data.",
]);

function requestUrl(input: string | URL | Request) {
  if (input instanceof URL) return input;
  if (input instanceof Request) return new URL(input.url);
  return new URL(String(input));
}

export function assertProviderUrl(input: string | URL | Request) {
  const url = requestUrl(input);
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) {
    throw Object.assign(new Error("供应商请求必须使用不含账号密码的 HTTP(S) 地址"), { status: 403, providerCode: "NETWORK_UNREACHABLE", retryable: false });
  }
  const host = url.hostname.replace(/^\[|\]$/g, "").toLowerCase();
  const family = isIP(host);
  if (blockedHosts.has(host) || (family === 4 && blockedV4.check(host, "ipv4")) || (family === 6 && blockedV6.check(host, "ipv6"))) {
    throw Object.assign(new Error("供应商请求不能访问链路本地或云元数据地址"), { status: 403, providerCode: "NETWORK_UNREACHABLE", retryable: false });
  }
  return url;
}