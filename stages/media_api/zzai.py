# -*- coding: utf-8 -*-
"""ZZAI / Seedance 站的媒体 API 客户端。

边界：
* 文本 LLM 仍走 `web/core/llm`；
* 本模块只实现图片/视频的异步任务协议；
* `submit()` 默认拒绝执行，必须显式传 `authorized=True`；
* 不在异常文本、任务文件或日志里保留 API Key。

支持的协议（2026-11-12 文档核对）：
  * 钱包：GET /api/usage/wallet/
  * 模型：GET /v1/models
  * 图片：POST /v1/image/generations[/estimate]
          GET  /v1/image/generations/{task_id}
  * 视频：POST /v1/video/generations[/estimate]
          GET  /v1/video/generations/{task_id}
"""
from __future__ import annotations

import os
import time
import re
import mimetypes
from pathlib import Path
from urllib.parse import urlsplit

import httpx

DEFAULT_BASE_URL = "https://api.seedance.nz"
_KEY_ENVS = ("SEEDANCE_API_KEY", "ZZAI_API_KEY")
_STATUS = {
    "not_start": "queued", "submitted": "queued", "queued": "queued",
    "in_progress": "running", "running": "running", "processing": "running",
    "success": "succeeded", "succeeded": "succeeded", "completed": "succeeded",
    "failure": "failed", "failed": "failed", "error": "failed",
    "canceled": "canceled", "cancelled": "canceled",
}


class ZZAIError(RuntimeError):
    def __init__(self, kind: str, message: str, *, status: int | None = None,
                 retryable: bool = False):
        self.kind = str(kind or "protocol")
        self.status = status
        self.retryable = bool(retryable)
        self.message = str(message or "")
        super().__init__(self.message)


def normalize_status(raw: str) -> str:
    key = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    return _STATUS.get(key, "unknown")


def _key_files() -> list:
    """密钥文件的候选路径（都不存在时返回空，由调用方报「缺少 API Key」）。"""
    from pathlib import Path as _P
    out = []
    ws = os.environ.get("SOLODRAMA_WORKSPACE") or os.environ.get("DRAMA_WORKSPACE") or ""
    if ws:
        out.append(_P(ws) / ".secrets" / "zzai.key")
    out.append(_P(__file__).resolve().parents[2] / "configs" / "zzai.key")
    return out


def _status_of(data: dict):
    if not isinstance(data, dict):
        return "", None
    nested = data.get("data") if isinstance(data.get("data"), dict) else {}
    task = data.get("task") if isinstance(data.get("task"), dict) else {}
    status = data.get("status") or nested.get("status") or task.get("status") or ""
    progress = (data.get("progress") if "progress" in data else
                nested.get("progress") if "progress" in nested else
                task.get("progress"))
    return str(status or ""), progress


def _message_of(data) -> str:
    if not isinstance(data, dict):
        return str(data or "")
    err = data.get("error")
    if isinstance(err, dict):
        return str(err.get("message") or err.get("code") or "")
    if err:
        return str(err)
    nested = data.get("data") if isinstance(data.get("data"), dict) else {}
    return str(data.get("message") or data.get("fail_reason") or
               nested.get("fail_reason") or nested.get("message") or "")


def _task_id_of(data) -> str:
    if not isinstance(data, dict):
        return ""
    nested = data.get("data") if isinstance(data.get("data"), dict) else {}
    return str(data.get("id") or data.get("task_id") or nested.get("id") or
               nested.get("task_id") or "")


def _usage_of(data):
    if not isinstance(data, dict):
        return None
    nested = data.get("data") if isinstance(data.get("data"), dict) else {}
    task = data.get("task") if isinstance(data.get("task"), dict) else {}
    for candidate in (data.get("usage"), nested.get("usage"), task.get("usage")):
        if isinstance(candidate, dict):
            return candidate
    return None


def _urls_of(data):
    if not isinstance(data, dict):
        return []
    nested = data.get("data") if isinstance(data.get("data"), dict) else {}
    meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    nested_meta = nested.get("metadata") if isinstance(nested.get("metadata"), dict) else {}
    content = nested.get("content") if isinstance(nested.get("content"), dict) else {}
    out = []
    for value in (data.get("result_url"), nested.get("result_url"),
                  meta.get("url"), nested_meta.get("url")):
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            out.append(value)
    for key in ("image_urls", "video_urls", "audio_urls"):
        values = content.get(key)
        if isinstance(values, list):
            out.extend(str(x) for x in values if str(x).startswith(("http://", "https://")))
    image_url = content.get("image_url")
    if isinstance(image_url, str) and image_url.startswith(("http://", "https://")):
        out.append(image_url)
    return list(dict.fromkeys(out))


class ZZAIClient:
    def __init__(self, *, base_url: str = DEFAULT_BASE_URL, key: str | None = None,
                 timeout: float = 30.0, transport=None, trust_env: bool | None = None):
        self.base_url = str(base_url or DEFAULT_BASE_URL).rstrip("/")
        self.key = str(key if key is not None else self._env_key() or "").strip()
        self.timeout = float(timeout or 30.0)
        self.transport = transport
        self.trust_env = True if trust_env is None else bool(trust_env)
        host = (urlsplit(self.base_url).hostname or "").lower()
        if host in ("127.0.0.1", "localhost", "::1"):
            self.trust_env = False

    @staticmethod
    def _env_key() -> str:
        for name in _KEY_ENVS:
            if os.environ.get(name):
                return os.environ[name]
        # ★ 2026-11-13：环境变量之外补一条**文件回落**。
        #   起因：WorkBuddy / 编辑器里的子进程不会 source ~/.bashrc，注册表里的用户变量
        #   也要重开终端才生效 —— 症状是「明明设过 Key，脚本还是报缺少 API Key」。
        #   顺序：工作区 `.secrets/zzai.key` → 仓库 `configs/zzai.key`（`.gitignore` 已含 `*.key`）。
        for cand in _key_files():
            try:
                if cand.is_file():
                    v = cand.read_text(encoding="utf-8-sig").strip().splitlines()
                    if v and v[0].strip():
                        return v[0].strip()
            except OSError:
                continue
        return ""

    def _safe(self, text) -> str:
        out = str(text or "")
        if self.key:
            out = out.replace(self.key, "[已隐藏]")
        out = re.sub(r"Bearer\s+[A-Za-z0-9._\-]{8,}", "Bearer [已隐藏]", out, flags=re.I)
        return out[:600]

    def _client(self):
        return httpx.Client(timeout=httpx.Timeout(self.timeout), follow_redirects=False,
                            trust_env=self.trust_env, transport=self.transport)

    def _headers(self, extra=None):
        if not self.key:
            raise ZZAIError("config", "缺少 API Key：请设置 SEEDANCE_API_KEY 或 ZZAI_API_KEY")
        headers = {"Authorization": "Bearer " + self.key, "Accept": "application/json"}
        headers.update(extra or {})
        return headers

    def _request(self, method: str, path: str, *, body=None, extra_headers=None):
        url = self.base_url + path
        try:
            with self._client() as client:
                res = client.request(method, url, headers=self._headers(extra_headers), json=body)
        except ZZAIError:
            raise
        except httpx.TimeoutException as exc:
            raise ZZAIError("timeout", "ZZAI 请求超时", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ZZAIError("network", self._safe(exc), retryable=True) from exc

        try:
            data = res.json()
        except ValueError:
            data = {}
        if res.status_code >= 400:
            text = _message_of(data) or res.text
            kind = "auth" if res.status_code in (401, 403) else (
                "rate_limit" if res.status_code == 429 else
                "server" if res.status_code >= 500 else "bad_request")
            retryable = res.status_code == 429 or res.status_code >= 500
            raise ZZAIError(kind, self._safe(text), status=res.status_code,
                            retryable=retryable)
        if not isinstance(data, dict):
            raise ZZAIError("protocol", "ZZAI 响应不是 JSON 对象")
        return data

    # ---------------- 只读 ----------------
    def wallet(self):
        return self._request("GET", "/api/usage/wallet/")

    def upload(self, path):
        """上传一张本地参考图，返回 24 小时有效的公网 URL（上传免费）。"""
        p = Path(path)
        if not p.is_file():
            raise ZZAIError("config", "参考图不存在：%s" % p)
        url = self.base_url + "/v1/files/upload"
        mime = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
        try:
            with self._client() as client:
                with p.open("rb") as fh:
                    res = client.post(url, headers=self._headers(),
                                      files={"file": (p.name, fh, mime)})
        except httpx.TimeoutException as exc:
            raise ZZAIError("timeout", "参考图上传超时", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ZZAIError("network", self._safe(exc), retryable=True) from exc
        try:
            data = res.json()
        except ValueError:
            data = {}
        if res.status_code >= 400:
            raise ZZAIError("bad_request", self._safe(_message_of(data) or res.text),
                            status=res.status_code, retryable=res.status_code >= 500)
        got = str((data or {}).get("url") or "").strip()
        if not got.startswith(("http://", "https://")):
            raise ZZAIError("protocol", "参考图上传响应缺少 url")
        return got

    def models(self):
        return self._request("GET", "/v1/models")

    def pricing(self):
        """公开价格目录；若站点要求鉴权则自动带 Key。"""
        url = self.base_url + "/api/pricing"
        headers = {"Authorization": "Bearer " + self.key} if self.key else {}
        try:
            with self._client() as client:
                res = client.get(url, headers=headers)
            res.raise_for_status()
            data = res.json()
        except httpx.TimeoutException as exc:
            raise ZZAIError("timeout", "价格目录请求超时", retryable=True) from exc
        except httpx.HTTPStatusError as exc:
            raise ZZAIError("protocol", "价格目录 HTTP %d" % exc.response.status_code,
                            status=exc.response.status_code) from exc
        except Exception as exc:  # noqa: BLE001
            raise ZZAIError("network", self._safe(exc), retryable=True) from exc
        if not isinstance(data, dict):
            raise ZZAIError("protocol", "价格目录响应不是 JSON 对象")
        return data

    def estimate(self, kind: str, payload: dict):
        k = str(kind or "").lower()
        if k not in ("image", "video"):
            raise ZZAIError("config", "estimate kind 只能是 image / video")
        return self._request("POST", "/v1/%s/generations/estimate" % k, body=payload)

    # ---------------- 生成任务 ----------------
    def submit(self, kind: str, payload: dict, *, max_cost=None, authorized=False):
        if not authorized:
            raise ZZAIError("config", "提交生成任务必须显式 authorized=True")
        k = str(kind or "").lower()
        if k not in ("image", "video"):
            raise ZZAIError("config", "submit kind 只能是 image / video")
        extra = {}
        if max_cost is not None:
            extra["X-Max-Cost"] = str(max_cost)
        data = self._request("POST", "/v1/%s/generations" % k, body=payload,
                             extra_headers=extra)
        task_id = _task_id_of(data)
        if not task_id:
            raise ZZAIError("protocol", "提交成功但响应缺少 task_id")
        status, progress = _status_of(data)
        return {"task_id": task_id, "raw_status": status or "submitted",
                "status": normalize_status(status or "submitted"),
                "progress": progress, "response": data}

    def poll(self, kind: str, task_id: str):
        k = str(kind or "").lower()
        if k not in ("image", "video"):
            raise ZZAIError("config", "poll kind 只能是 image / video")
        ident = str(task_id or "").strip()
        if not ident:
            raise ZZAIError("config", "poll 需要 task_id")
        data = self._request("GET", "/v1/%s/generations/%s" % (k, ident))
        status, progress = _status_of(data)
        normalized = normalize_status(status)
        usage = _usage_of(data)
        urls = _urls_of(data)
        error = _message_of(data) if normalized == "failed" else ""
        return {
            "task_id": ident,
            "raw_status": status,
            "status": normalized,
            "progress": progress,
            "result_url": urls[0] if urls else "",
            "result_urls": urls,
            "usage": usage,
            "error": error,
            "response": data,
        }

    def download(self, url: str, dest, *, max_bytes=512 * 1024 * 1024):
        """下载结果文件。

        ★ 2026-11-13 实测修正：原来走 `client.stream("GET") + iter_bytes()`，
          在真真AI 的 CDN（xbuddy.si）上**只回响应头、不回响应体** ——
          进程挂住不动、`read` 超时也不触发，3 秒样片能卡到 90 秒以上被杀。
          同一 URL 用普通 GET 只要 5 秒，curl 也正常 ⇒ 问题在流式读取这条路径。
          现在改成「整取 + 大小闸门」：文件是单镜 2–20 秒的 mp4，几 MB 量级，整取无压力。
        """
        target = Path(dest)
        if not str(url).startswith(("http://", "https://")):
            raise ZZAIError("config", "下载地址必须是 http(s)")
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".part")
        # ★ CDN 首次命中有 20–40 秒才吐字节的情况（实测同一 URL 4.4s / 19s / >30s 都出现过）。
        #   所以下载用**独立的宽超时 + 重试**，不沿用 API 的 30 秒短超时 ——
        #   任务是按秒计费的真金白银，不能因为 CDN 慢就把成功的结果丢掉。
        last = None
        for attempt in range(3):
            try:
                with httpx.Client(timeout=httpx.Timeout(connect=15.0, read=180.0,
                                                        write=60.0, pool=30.0),
                                  follow_redirects=True, trust_env=self.trust_env) as client:
                    res = client.get(url, headers={"Accept": "*/*"})
                    res.raise_for_status()
                    data = res.content
                    if not data:
                        raise ZZAIError("protocol", "下载到 0 字节")
                    if len(data) > max_bytes:
                        raise ZZAIError("protocol", "下载超过大小上限（%d 字节）" % len(data))
                    tmp.write_bytes(data)
                os.replace(tmp, target)
                return {"ok": True, "path": str(target), "bytes": len(data),
                        "attempts": attempt + 1}
            except ZZAIError:
                raise
            except Exception as exc:  # noqa: BLE001
                last = exc
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
        raise ZZAIError("network", self._safe(last), retryable=True)
