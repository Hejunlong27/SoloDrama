const referralCodes = {
  xiangongyun: "PNLH4L",
  compshare: "2UZNw7j4pcEExqFlumDrU",
  runningHubCn: "cn-v1122",
  runningHubAi: "rh-v1727",
} as const;

function appendQuery(url: URL, key: string, value: string) {
  url.searchParams.set(key, value);
  return url;
}

/** 所有受支持平台的外部地址统一附加对应邀请码，且不覆盖原有查询参数。 */
export function withReferralCode(raw: string): string {
  let url: URL;
  try { url = new URL(raw.startsWith("//") ? `https:${raw}` : raw); }
  catch { return raw; }
  const host = url.hostname.toLowerCase();
  if (host === "xiangongyun.com" || host.endsWith(".xiangongyun.com")) {
    if (url.pathname === "/register" || url.pathname.startsWith("/register/")) url.pathname = `/register/${referralCodes.xiangongyun}`;
    else appendQuery(url, "inviteCode", referralCodes.xiangongyun);
  } else if (host === "compshare.cn" || host.endsWith(".compshare.cn")) {
    appendQuery(url, "referral_code", referralCodes.compshare);
  } else if (host === "runninghub.cn" || host.endsWith(".runninghub.cn")) {
    appendQuery(url, "inviteCode", referralCodes.runningHubCn);
  } else if (host === "runninghub.ai" || host.endsWith(".runninghub.ai")) {
    appendQuery(url, "inviteCode", referralCodes.runningHubAi);
  }
  return url.href;
}