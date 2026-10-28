# -*- coding: utf-8 -*-
"""LLM 层的安全工具：Key 打码、Base URL 校验（SSRF）、文本脱敏

三条硬规则：
  1. **原始 Key 永远不出后端**。对外只给 `mask_key()` 的结果与 `has_key` 布尔。
  2. **Base URL 必须校验协议与目标**。默认禁止内网/回环；用户显式勾选「本地服务」
     才放行（本地 Ollama / LM Studio / vLLM 是正当用法）。云元数据地址**一律拒绝**，
     不论是否本地——那是 SSRF 最经典的落点。
  3. **报错文本过 `scrub`**。上游可能把 Key 回显在 401 的 body 里。
"""
from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlsplit

from .errors import LLMError

# 常见密钥形态：OpenAI 系、Bearer 头、以及本项目的平台 Key
_KEY_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{6,}\b"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs)_[A-Za-z0-9]{10,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{8,}", re.I),
    re.compile(r"(?i)\b(api[_-]?key|token|secret)\b\s*[:=]\s*[\"']?([A-Za-z0-9._\-]{8,})"),
]

# 云元数据端点（IPv4 / IPv6 / 主机名）—— 任何情况下都不许请求
_METADATA_HOSTS = {
    "metadata.google.internal",
    "metadata.goog",
    "instance-data",
    "metadata",
}
_METADATA_IPS = {ipaddress.ip_address("169.254.169.254"), ipaddress.ip_address("fd00:ec2::254")}


def mask_key(key) -> str:
    """`sk-abcdef1234567890` → `sk-a…7890`；太短则只回 `…`。"""
    s = str(key or "")
    if not s:
        return ""
    if len(s) <= 8:
        return "…"
    head = s[:4]
    tail = s[-4:]
    return "%s…%s" % (head, tail)


def scrub(text) -> str:
    """把文本里疑似密钥的片段替换成 `[已隐藏]`。日志与前端错误提示都必须过它。"""
    out = str(text or "")
    for pat in _KEY_PATTERNS:
        out = pat.sub(lambda m: (m.group(1) + "=[已隐藏]") if m.lastindex and m.group(1) else "[已隐藏]", out)
    return out


def _host_is_private(ip) -> bool:
    return (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified)


def check_base_url(url, *, allow_local=False, field="base_url") -> str:
    """校验并归一化 Base URL（去掉尾部 `/`）。不合规抛 `LLMError('blocked'|'config')`。

    allow_local=False 时拒绝回环/私网/链路本地/保留地址；True 时只额外拒绝云元数据。
    """
    raw = str(url or "").strip()
    if not raw:
        raise LLMError("config", "Base URL 不能为空")
    if len(raw) > 500:
        raise LLMError("config", "Base URL 过长")
    if any(ch in raw for ch in ("\n", "\r", "\t", " ")):
        raise LLMError("config", "Base URL 不允许包含空白字符")

    try:
        u = urlsplit(raw)
    except ValueError as exc:
        raise LLMError("config", "Base URL 无法解析：%s" % exc) from None

    if u.scheme not in ("http", "https"):
        raise LLMError("blocked", "Base URL 只允许 http / https（当前 %s）" % (u.scheme or "空"))
    if u.username or u.password:
        raise LLMError("blocked", "Base URL 不允许内嵌用户名口令，请用独立的 Key 字段")
    host = (u.hostname or "").strip()
    if not host:
        raise LLMError("config", "Base URL 缺少主机名")

    low = host.lower().rstrip(".")
    if low in _METADATA_HOSTS:
        raise LLMError("blocked", "拒绝访问云元数据地址（%s）" % low)

    # IP 字面量直接判段
    try:
        ip = ipaddress.ip_address(low.strip("[]"))
    except ValueError:
        ip = None
    if ip is not None:
        if ip in _METADATA_IPS or (ip.version == 4 and ip == ipaddress.ip_address("169.254.169.254")):
            raise LLMError("blocked", "拒绝访问云元数据地址")
        if _host_is_private(ip) and not allow_local:
            raise LLMError("blocked", "目标是内网/回环地址（%s）；如确为本地服务，请勾选「本地服务」后再保存" % ip)
    elif not allow_local and (low == "localhost" or low.endswith(".localhost") or low.endswith(".local")):
        raise LLMError("blocked", "目标是本地主机名（%s）；如确为本地服务，请勾选「本地服务」" % low)

    path = (u.path or "").rstrip("/")
    return "%s://%s%s%s" % (u.scheme, u.netloc, path, "")


def resolved_ips(host, *, timeout=2.0):
    """解析主机名（配置保存时**不**调用，只在连接测试时用于二次核对）。

    返回 IP 列表；解析失败返回空列表（由调用方按网络错误处理）。
    """
    try:
        socket.setdefaulttimeout(timeout)
        infos = socket.getaddrinfo(host, None)
    except (OSError, UnicodeError):
        return []
    out = []
    for info in infos:
        try:
            out.append(ipaddress.ip_address(info[4][0].split("%")[0]))
        except ValueError:
            continue
    return out


def check_resolved(host, *, allow_local=False) -> None:
    """DNS 解析后再核一次（防 DNS rebinding 把公网域名指向内网）。"""
    for ip in resolved_ips(host):
        if ip in _METADATA_IPS:
            raise LLMError("blocked", "域名解析到云元数据地址，已拒绝")
        if _host_is_private(ip) and not allow_local:
            raise LLMError("blocked", "域名解析到内网地址（%s），已拒绝；本地服务请勾选「本地服务」" % ip)
