# -*- coding: utf-8 -*-
"""LLM 提供商适配器

只做一件事：把「一次文本生成」翻译成具体协议。业务语义（用途、模板、Schema）在网关层。

两种协议覆盖了绝大多数真实场景：
  * `openai` —— POST {base}/chat/completions（OpenAI / DeepSeek / Kimi / Qwen-DashScope 兼容 /
                vLLM / LM Studio / one-api 等全部同一形态）
  * `ollama` —— POST {base}/api/chat（本地，无需云端 Key）

★ 连接测试默认**只读模型列表**（0 费用）；「最小生成测试」需用户显式选择，因为它会产生真实调用。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import httpx

from . import safety
from .errors import LLMError, classify_status


@dataclass
class ProviderResult:
    text: str = ""
    model: str = ""
    usage: dict = field(default_factory=dict)
    raw_status: int = 200
    extra: dict = field(default_factory=dict)


def _content_of(message) -> str:
    """兼容 content 为 str / list（部分网关回 parts 数组）。"""
    c = message.get("content") if isinstance(message, dict) else None
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        out = []
        for part in c:
            if isinstance(part, dict):
                out.append(str(part.get("text") or ""))
            elif isinstance(part, str):
                out.append(part)
        return "".join(out)
    return ""


def _http_error(exc: Exception) -> LLMError:
    if isinstance(exc, httpx.TimeoutException):
        return LLMError("timeout", "请求超时（可在提供商配置里调大超时秒数）")
    if isinstance(exc, httpx.HTTPStatusError):
        body = ""
        try:
            body = exc.response.text[:600]
        except Exception:  # noqa: BLE001
            pass
        kind = classify_status(exc.response.status_code, body)
        return LLMError(kind, "%s（HTTP %d）" % (LLMError(kind).text, exc.response.status_code),
                        status=exc.response.status_code, detail=safety.scrub(body))
    if isinstance(exc, (httpx.ConnectError, httpx.NetworkError, httpx.RemoteProtocolError)):
        return LLMError("network", "无法连接端点：%s" % safety.scrub(str(exc))[:200])
    if isinstance(exc, httpx.InvalidURL):
        return LLMError("blocked", "端点地址不合法")
    return LLMError("network", safety.scrub(str(exc))[:200] or "网络异常")


class BaseProvider:
    kind = ""

    def __init__(self, cfg: dict, key: str = ""):
        self.cfg = cfg or {}
        self.base = str(self.cfg.get("base_url") or "").rstrip("/")
        self.key = key or ""
        self.timeout_s = float(self.cfg.get("timeout_s") or 60)
        self.model = str(self.cfg.get("default_model") or "")
        self.caps = list(self.cfg.get("capabilities") or ["json"])
        # ★ 是否继承系统代理（HTTP_PROXY / HTTPS_PROXY / NO_PROXY）。
        #   为什么不一律 trust_env=False：本机/企业环境常常**只能**经代理出网，
        #   硬绕代理会表现为「请求超时」，用户会误以为是 Key 或模型的问题。
        #   默认：本地服务不走代理（否则 127.0.0.1 的 Ollama 会被代理劫走），云端走代理。
        te = self.cfg.get("trust_env")
        self.trust_env = (not bool(self.cfg.get("local"))) if te is None else bool(te)

    # -- 子类实现 --
    def chat(self, messages, *, model=None, temperature=None, max_tokens=None,
             json_mode=False, timeout_s=None, cancel=None) -> ProviderResult:
        raise NotImplementedError

    def list_models(self, timeout_s=None) -> list:
        raise NotImplementedError

    # -- 共用 --
    def _client(self, timeout_s=None):
        return httpx.Client(timeout=httpx.Timeout(timeout_s or self.timeout_s),
                            follow_redirects=False, trust_env=self.trust_env)

    def _check_cancel(self, cancel):
        if cancel is not None and getattr(cancel, "is_set", None) and cancel.is_set():
            raise LLMError("canceled", "已取消")


# ---------------------------------------------------------------------------
# OpenAI 兼容
# ---------------------------------------------------------------------------
class OpenAICompatible(BaseProvider):
    kind = "openai"

    def _headers(self):
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.key:
            h["Authorization"] = "Bearer " + self.key
        return h

    def chat(self, messages, *, model=None, temperature=None, max_tokens=None,
             json_mode=False, timeout_s=None, cancel=None) -> ProviderResult:
        self._check_cancel(cancel)
        payload = {"model": model or self.model, "messages": messages, "stream": False}
        if temperature is not None:
            payload["temperature"] = float(temperature)
        if max_tokens:
            payload["max_tokens"] = int(max_tokens)
        if json_mode and "json" in self.caps:
            payload["response_format"] = {"type": "json_object"}

        url = self.base + "/chat/completions"
        try:
            with self._client(timeout_s) as c:
                r = c.post(url, headers=self._headers(), json=payload)
                r.raise_for_status()
                data = r.json()
        except Exception as exc:  # noqa: BLE001
            raise _http_error(exc) from None

        if not isinstance(data, dict):
            raise LLMError("protocol", "响应不是 JSON 对象")
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            err = (data.get("error") or {}) if isinstance(data.get("error"), dict) else {}
            raise LLMError("protocol", "响应缺少 choices：%s" % safety.scrub(json.dumps(err, ensure_ascii=False))[:200])

        msg = (choices[0] or {}).get("message") or {}
        text = _content_of(msg)
        u = data.get("usage") or {}
        usage = {
            "input_tokens": u.get("prompt_tokens"),
            "output_tokens": u.get("completion_tokens"),
            "total_tokens": u.get("total_tokens"),
            "raw": {k: v for k, v in u.items() if k in ("prompt_tokens", "completion_tokens", "total_tokens")} or None,
        }
        return ProviderResult(text=text, model=str(data.get("model") or model or self.model),
                              usage=usage, raw_status=200)

    def list_models(self, timeout_s=None) -> list:
        url = self.base + "/models"
        try:
            with self._client(timeout_s) as c:
                r = c.get(url, headers=self._headers())
                r.raise_for_status()
                data = r.json()
        except Exception as exc:  # noqa: BLE001
            raise _http_error(exc) from None
        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise LLMError("protocol", "模型列表格式不符合 OpenAI 约定")
        return sorted({str(it.get("id")) for it in items if isinstance(it, dict) and it.get("id")})


# ---------------------------------------------------------------------------
# 本地 Ollama
# ---------------------------------------------------------------------------
class OllamaProvider(BaseProvider):
    kind = "ollama"
    caps = ["json"]

    def chat(self, messages, *, model=None, temperature=None, max_tokens=None,
             json_mode=False, timeout_s=None, cancel=None) -> ProviderResult:
        self._check_cancel(cancel)
        opts = {}
        if temperature is not None:
            opts["temperature"] = float(temperature)
        if max_tokens:
            opts["num_predict"] = int(max_tokens)
        payload = {"model": model or self.model, "messages": messages, "stream": False}
        if opts:
            payload["options"] = opts
        if json_mode:
            payload["format"] = "json"

        url = self.base + "/api/chat"
        try:
            with self._client(timeout_s) as c:
                r = c.post(url, json=payload)  # Ollama 不需要 Authorization
                r.raise_for_status()
                data = r.json()
        except Exception as exc:  # noqa: BLE001
            raise _http_error(exc) from None

        if not isinstance(data, dict):
            raise LLMError("protocol", "响应不是 JSON 对象")
        if data.get("error"):
            raise LLMError("server", safety.scrub(str(data["error"]))[:200])
        text = _content_of(data.get("message") or {}) or str(data.get("response") or "")
        usage = {
            "input_tokens": data.get("prompt_eval_count"),
            "output_tokens": data.get("eval_count"),
            "total_tokens": (data.get("prompt_eval_count") or 0) + (data.get("eval_count") or 0) or None,
            "raw": None,
        }
        return ProviderResult(text=text, model=str(data.get("model") or model or self.model),
                              usage=usage, raw_status=200)

    def list_models(self, timeout_s=None) -> list:
        url = self.base + "/api/tags"
        try:
            with self._client(timeout_s) as c:
                r = c.get(url)
                r.raise_for_status()
                data = r.json()
        except Exception as exc:  # noqa: BLE001
            raise _http_error(exc) from None
        items = data.get("models") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise LLMError("protocol", "模型列表格式不符合 Ollama 约定")
        return sorted({str(it.get("name") or it.get("model")) for it in items
                       if isinstance(it, dict) and (it.get("name") or it.get("model"))})


# ---------------------------------------------------------------------------
# Mock（测试注入用）
# ---------------------------------------------------------------------------
class MockProvider(BaseProvider):
    """离线测试用。`script` 是「第 n 次调用返回什么」的队列。

    每项可以是 dict（原样作为返回文本的 JSON）或 str（原样返回）；
    也可以是 Exception 实例，用来模拟鉴权失败 / 超时 / 限流。
    """

    kind = "mock"
    calls = []

    def __init__(self, cfg=None, key="", script=None):
        super().__init__(cfg or {"base_url": "http://mock.local", "default_model": "mock-1"}, key)
        self.script = list(script or [])
        self._calls = []

    def chat(self, messages, *, model=None, temperature=None, max_tokens=None,
             json_mode=False, timeout_s=None, cancel=None) -> ProviderResult:
        self._check_cancel(cancel)
        self._calls.append({"messages": messages, "model": model, "json_mode": json_mode,
                            "temperature": temperature, "max_tokens": max_tokens})
        item = self.script.pop(0) if self.script else {"ok": True}
        if isinstance(item, Exception):
            raise item
        text = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
        return ProviderResult(
            text=text, model=model or self.model,
            usage={"input_tokens": 100, "output_tokens": 200, "total_tokens": 300, "raw": None},
            raw_status=200,
        )

    def list_models(self, timeout_s=None) -> list:
        return [self.model]


_KINDS = {
    "openai": OpenAICompatible,
    "ollama": OllamaProvider,
    "mock": MockProvider,
}


def build(cfg: dict, key: str = "") -> BaseProvider:
    kind = str((cfg or {}).get("kind") or "openai")
    cls = _KINDS.get(kind)
    if cls is None:
        raise LLMError("config", "不支持的提供商类型：%s" % kind)
    return cls(cfg, key)
