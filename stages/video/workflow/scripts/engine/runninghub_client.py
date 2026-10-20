# -*- coding: utf-8 -*-
"""
runninghub_client.py —— RunningHub OpenAPI 协议层（async httpx）

只负责「跟 RunningHub 说话」，不含任何分镜业务逻辑。

已由本机既有代码验证过的契约：
  上传    POST /openapi/v2/media/upload/binary   multipart 字段名 = file
          -> data.{fileName, download_url, type, size}
  建任务  POST /openapi/v2/run/workflow/{workflowId}   ← 官方现行通道（Bearer）
          body {addMetadata, nodeInfoList, instanceType, usePersonalQueue[, retainSeconds]}
          -> {taskId, status, errorCode, errorMessage, clientId, promptTips}
          ★ 注意：本通道错误字段是 errorCode/errorMessage，不是 code/msg。
          ★ 前置条件：该 workflowId 必须先在 RunningHub 网页端「保存并运行过一次」，
            否则返回 810 WORKFLOW_NOT_SAVED_OR_NOT_RUNNING；编号不存在返回 380。
  建任务  POST /task/openapi/create              {apiKey, workflowId, nodeInfoList} -> data.taskId
          （legacy 通道，v2 路由不可用时才退回）
          POST /task/openapi/ai-app/run          {apiKey, webappId,  nodeInfoList} -> data.taskId
  查任务  POST /openapi/v2/query                 {taskId}
          -> { status, results:[{url, outputType, text, nodeId}], usage:{...} }
          status: CREATE/QUEUED/RUNNING 非终态 | SUCCESS 成功 | FAILED/CANCEL 失败
  兼容通道 POST /task/openapi/status              {apiKey, taskId}  —— 字段名未验证，做了容错解析

重试纪律：只对「瞬时错误」（网络超时、429、5xx、限流）标记可重试；
确定性错误（401/403、余额不足、内容策略、参数缺失）一律不重试，避免浪费额度。
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence
from urllib.parse import urlparse

import httpx

# ---------------------------------------------------------------------------
# 状态词
# ---------------------------------------------------------------------------
STATUS_OK = "SUCCESS"
STATUS_FAIL = {"FAILED", "FAIL", "CANCEL", "CANCELLED", "ERROR"}
STATUS_NON_TERMINAL = {"CREATE", "CREATED", "QUEUED", "QUEUE", "RUNNING", "PENDING", "WAITING", "PROCESSING"}
TERMINAL = {STATUS_OK} | STATUS_FAIL

# 限流类关键词（出现在业务 msg 里 -> 判定为可重试）
# ★ 2026-10-20（反馈 P2-10）：补上「单账号并发上限」。实测三线程并行、两条链落到同一账号时，
#   第二次提交返回 `errorCode 421 / api queue limit reached`，此前被当**确定性失败**直接放弃，
#   整链中断（本项目 SC03 因此漏跑）。这类错误本质是「排队满了」，属瞬时错误，应当退避重试。
_RETRY_HINT_WORDS = ("too many", "rate limit", "限流", "频率", "繁忙", "busy", "try again",
                     "稍后", "queue limit", "queue is full", "并发上限", "队列已满")

# 队列满时的退避（秒）。平台排队一般 1–3 分钟，5/15/45 太短会连撞三次全失败。
QUEUE_FULL_BACKOFF = (30, 60, 120)

# OOM（显存不足）识别关键词（反馈 P1-13）
_OOM_WORDS = ("outofmemory", "out of memory", "vram grow failed", "显存不足",
              "cudamalloc", "allocation on device", "memory allocation")


def is_oom_error(value: Any) -> bool:
    """判断一个异常或错误文本是否属于「显存不足」（可降级重试，且平台不计费）。

    实测（2026-10-19）：12 秒 + 6 参考图在 default(24G) 实例上，
    `errorCode 805` + `failedReason: VRAM grow failed: 658215936 bytes` 或
    `torch.OutOfMemoryError【显存不足告警】`。usage=null，不计费，但整镜白等。
    """
    if isinstance(value, BaseException):
        text = " ".join([str(getattr(value, "message", "") or ""), str(value)])
        code = str(getattr(value, "code", "") or "")
    else:
        text, code = str(value or ""), ""
    low = text.lower()
    if code in ("805",):
        return True
    return any(w in low for w in _OOM_WORDS)


def truncate(text: Any, limit: int = 200) -> str:
    """把错误信息截断，避免把整个堆栈/响应体写进 state.json。"""
    s = str(text or "").replace("\n", " ").strip()
    return s if len(s) <= limit else s[: limit - 3] + "..."


class RunningHubError(Exception):
    """统一异常。retriable=True 表示「瞬时错误，值得重试」。"""

    def __init__(self, message: str, *, code: Any = None, http_status: Optional[int] = None,
                 retriable: bool = False, response: Any = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.http_status = http_status
        self.retriable = retriable
        self.response = response
        self.short = truncate(message, 200)

    def __str__(self) -> str:  # pragma: no cover - 便于日志
        return self.short


def normalize_status(raw: Any) -> str:
    s = str(raw or "").strip().upper()
    if s in ("SUCCEED", "SUCCEEDED", "OK", "DONE", "COMPLETED", "COMPLETE"):
        return STATUS_OK
    if s in ("FAILURE", "FAILED", "ERROR"):
        return "FAILED"
    return s or "UNKNOWN"


def _first_present(d: Dict[str, Any], keys: Iterable[str]) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, "", [], {}):
            return d[k]
    return None


def _v2_route_missing(err: "RunningHubError") -> bool:
    """判断 v2 提交路由是否「压根不存在」（老网关/站点未上线）。

    只有这种情况下才值得退回 legacy 通道；810/380 是业务结论，退回没有意义。
    """
    code = str(getattr(err, "code", "") or "")
    txt = str(getattr(err, "message", "") or "").lower()
    return code == "1001" or "invalid url" in txt


# ---------------------------------------------------------------------------
# 客户端
# ---------------------------------------------------------------------------
class RunningHubClient:
    """异步 RunningHub 客户端。建议用 `async with RunningHubClient(...) as c:` 使用。"""

    def __init__(self, api_key: str, base_url: str, timeout: float = 60.0,
                 channel: str = "auto"):
        if not api_key or not api_key.strip():
            raise RunningHubError(
                "未设置 RUNNINGHUB_API_KEY。Windows 下请先执行： set RUNNINGHUB_API_KEY=你的key"
            )
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        # auto    = 优先 /openapi/v2/query，结构不符时自动降级 /task/openapi/status
        # v2      = 只用 /openapi/v2/query（已验证，推荐）
        # status  = 只用 /task/openapi/status（字段名未验证，保留给你实测）
        self.channel = channel
        self._client: Optional[httpx.AsyncClient] = None

    # ---------- 生命周期 ----------
    async def __aenter__(self) -> "RunningHubClient":
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout,
                                         follow_redirects=True)
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("客户端未初始化：请用 `async with RunningHubClient(...) as c:`")
        return self._client

    def _headers(self, with_json: bool = True) -> Dict[str, str]:
        h = {"Authorization": f"Bearer {self.api_key}"}
        if with_json:
            h["Content-Type"] = "application/json"
        return h

    # ---------- 底层请求 ----------
    async def _request(self, method: str, path: str, *, json_body: Optional[dict] = None,
                       data: Optional[dict] = None, files: Optional[dict] = None,
                       timeout: Optional[float] = None, context: str = "") -> Dict[str, Any]:
        """发请求 + 统一错误分类。返回解析后的 JSON dict。"""
        url = path
        try:
            resp = await self.client.request(
                method, url,
                headers=self._headers(with_json=json_body is not None),
                json=json_body, data=data, files=files,
                timeout=timeout or self.timeout,
            )
        except (httpx.TimeoutException, httpx.NetworkError, httpx.TransportError) as e:
            raise RunningHubError(f"{context or '请求'}网络异常: {type(e).__name__}: {e}",
                                  retriable=True) from e

        if resp.status_code >= 400:
            body_text = truncate(resp.text, 300)
            retriable = resp.status_code == 429 or resp.status_code >= 500
            raise RunningHubError(
                f"{context or '请求'} HTTP {resp.status_code}: {body_text}",
                http_status=resp.status_code, retriable=retriable,
            )

        try:
            payload = resp.json()
        except (json.JSONDecodeError, ValueError) as e:
            raise RunningHubError(f"{context or '请求'}返回的不是合法 JSON: {truncate(resp.text, 300)}",
                                  retriable=True) from e
        return payload if isinstance(payload, dict) else {"data": payload}

    def _raise_business(self, payload: Dict[str, Any], context: str = "") -> None:
        """HTTP 200 不代表业务成功：code 非 0 时抛错，并按 msg 判定是否可重试。"""
        code = payload.get("code")
        if code in (0, None, "", "0"):
            return
        msg = payload.get("msg") or payload.get("message") or payload.get("error") or ""
        low = str(msg).lower()
        retriable = any(w in low for w in _RETRY_HINT_WORDS)
        err = RunningHubError(f"{context}失败: {msg} (code={code})", code=code,
                              retriable=retriable, response=payload)
        if retriable and any(w in low for w in ("queue limit", "queue is full", "并发上限", "队列已满")):
            # 提示上层用更长的退避（见 retry_async）
            err.retry_after = QUEUE_FULL_BACKOFF          # type: ignore[attr-defined]
        raise err

    # ---------- 上传 ----------
    async def upload_bytes(self, data: bytes, filename: str,
                           content_type: str = "application/octet-stream") -> Dict[str, Any]:
        payload = await self._request(
            "POST", "/openapi/v2/media/upload/binary",
            files={"file": (filename, data, content_type)},   # multipart 字段名必须是 file
            timeout=self.timeout * 3, context="上传文件",
        )
        self._raise_business(payload, "上传文件")
        d = payload.get("data") or {}
        if not d.get("download_url"):
            raise RunningHubError(f"上传返回缺少 download_url: {truncate(payload, 300)}", response=payload)
        return {"fileName": d.get("fileName"), "download_url": d.get("download_url"),
                "type": d.get("type"), "size": d.get("size")}

    async def upload_file(self, local_path: str) -> Dict[str, Any]:
        p = Path(local_path)
        if not p.is_file():
            raise RunningHubError(f"待上传文件不存在: {local_path}")
        suffix = p.suffix.lower()
        ct = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
              ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp",
              ".mp4": "video/mp4", ".zip": "application/zip"}.get(suffix, "application/octet-stream")
        return await self.upload_bytes(p.read_bytes(), p.name, ct)

    # ---------- 提交任务 ----------
    @staticmethod
    def build_node_list(pairs: Sequence[tuple]) -> List[Dict[str, str]]:
        """把 [(nodeId, fieldName, value), ...] 转成官方 nodeInfoList（自动丢弃空节点）。"""
        out: List[Dict[str, str]] = []
        for item in pairs:
            node_id, field_name, value = item
            if node_id in (None, "") or field_name in (None, ""):
                continue
            if value is None:
                continue
            out.append({"nodeId": str(node_id), "fieldName": str(field_name),
                        "fieldValue": value if isinstance(value, str)
                        else json.dumps(value, ensure_ascii=False)})
        return out

    async def create_workflow(self, workflow_id: str, node_info_list: List[Dict[str, Any]],
                              instance_type: Optional[str] = None) -> str:
        body: Dict[str, Any] = {"apiKey": self.api_key, "workflowId": str(workflow_id),
                                "nodeInfoList": node_info_list}
        if instance_type:
            body["instanceType"] = instance_type
        payload = await self._request("POST", "/task/openapi/create", json_body=body,
                                      context="提交工作流任务")
        self._raise_business(payload, "提交工作流任务")
        task_id = (payload.get("data") or {}).get("taskId") or payload.get("taskId")
        if not task_id:
            raise RunningHubError(f"提交成功但响应缺少 taskId: {truncate(payload, 300)}", response=payload)
        return str(task_id)

    async def create_workflow_v2(self, workflow_id: str, node_info_list: List[Dict[str, Any]],
                                 instance_type: Optional[str] = None,
                                 use_personal_queue: bool = False,
                                 add_metadata: bool = False,
                                 retain_seconds: Optional[int] = None) -> str:
        """官方现行通道：POST /openapi/v2/run/workflow/{workflowId}。

        失败字段走 errorCode/errorMessage：
          810 = 该工作流在平台侧没有「已保存并运行」的记录，取不到 API 快照；
          380 = workflowId 不存在。
        """
        body: Dict[str, Any] = {
            "addMetadata": bool(add_metadata),
            "nodeInfoList": node_info_list,
            "instanceType": instance_type or "default",
            "usePersonalQueue": "true" if use_personal_queue else "false",
        }
        if retain_seconds:
            body["retainSeconds"] = int(retain_seconds)
        payload = await self._request(
            "POST", f"/openapi/v2/run/workflow/{str(workflow_id).strip()}",
            json_body=body, context="提交工作流任务(v2)",
        )
        err = str(payload.get("errorCode") or "").strip()
        if err:
            msg = str(payload.get("errorMessage") or "")
            hint = ""
            if err == "810":
                hint = ("｜该工作流从未在 RunningHub 网页端保存并运行过，平台没有生成 API 快照。"
                        "请登录后打开该工作流页面点一次「运行」；若它是别人的公开工作流，"
                        "先「另存到我的工作流」，再用新编号调用。")
            elif err == "380":
                hint = "｜平台上不存在这个工作流编号，请核对 workflowId。"
            elif err == "421":
                hint = ("｜同一账号的并发队列已满（单账号 ≤5 / 或账号被多链共用）。"
                        "引擎会按 30/60/120 秒退避重试；要根治请把账号分给不同 worker。")
            low_msg = msg.lower()
            retriable = err in ("421", "429") or any(w in low_msg for w in _RETRY_HINT_WORDS)
            exc = RunningHubError(f"提交工作流任务(v2)失败: {msg} (errorCode={err}){hint}",
                                  code=err, retriable=retriable, response=payload)
            if retriable and err == "421":
                exc.retry_after = QUEUE_FULL_BACKOFF      # type: ignore[attr-defined]
            raise exc
        task_id = payload.get("taskId") or (payload.get("data") or {}).get("taskId")
        if not task_id:
            raise RunningHubError(
                f"提交成功但响应缺少 taskId: {truncate(payload, 300)}", response=payload)
        return str(task_id)

    async def create_ai_app(self, webapp_id: Any, node_info_list: List[Dict[str, Any]],
                            instance_type: Optional[str] = None) -> str:
        body: Dict[str, Any] = {"apiKey": self.api_key, "webappId": int(webapp_id),
                                "nodeInfoList": node_info_list}
        if instance_type:
            body["instanceType"] = instance_type
        payload = await self._request("POST", "/task/openapi/ai-app/run", json_body=body,
                                      context="提交AI应用任务")
        self._raise_business(payload, "提交AI应用任务")
        task_id = (payload.get("data") or {}).get("taskId") or payload.get("taskId")
        if not task_id:
            raise RunningHubError(f"提交成功但响应缺少 taskId: {truncate(payload, 300)}", response=payload)
        return str(task_id)

    async def create_task(self, kind: str, target_id: Any, node_info_list: List[Dict[str, Any]],
                          instance_type: Optional[str] = None) -> str:
        k = (kind or "workflow").strip().lower()
        if k in ("workflow", "wf", "comfy"):
            # 官方现行通道优先；只有该路由不存在时才退回 legacy，避免把 810/380 当兼容问题重试。
            try:
                return await self.create_workflow_v2(str(target_id), node_info_list, instance_type)
            except RunningHubError as e:
                if not _v2_route_missing(e):
                    raise
                return await self.create_workflow(str(target_id), node_info_list, instance_type)
        if k in ("ai-app", "ai_app", "app", "webapp"):
            return await self.create_ai_app(target_id, node_info_list, instance_type)
        raise RunningHubError(f"不支持的 kind='{kind}'（可选 workflow / ai-app）")

    # ---------- 查询 ----------
    async def query_v2(self, task_id: str) -> Dict[str, Any]:
        """主通道（已验证）：POST /openapi/v2/query {taskId}"""
        payload = await self._request("POST", "/openapi/v2/query", json_body={"taskId": str(task_id)},
                                      context="查询任务(v2)")
        self._raise_business(payload, "查询任务(v2)")
        return payload

    async def query_status_v1(self, task_id: str) -> Dict[str, Any]:
        """/task/openapi/status 兼容通道。

        ⚠️ TODO 字段名未实测。这里对 taskStatus / status / task_status，以及
        fileList / file_list / results / outputs，以及 fileUrl / url / outputUrl
        做了候选容错解析。等你实测后，把真实字段名固定下来即可。
        """
        body = {"apiKey": self.api_key, "taskId": str(task_id)}
        payload = await self._request("POST", "/task/openapi/status", json_body=body,
                                      context="查询任务(status)")
        self._raise_business(payload, "查询任务(status)")
        d = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        raw_status = _first_present(d, ("taskStatus", "task_status", "status", "state"))
        files = _first_present(d, ("fileList", "file_list", "results", "outputs")) or []
        results: List[Dict[str, Any]] = []
        if isinstance(files, list):
            for item in files:
                if not isinstance(item, dict):
                    continue
                url = _first_present(item, ("fileUrl", "file_url", "url", "outputUrl", "output_url"))
                if url:
                    results.append({"url": url,
                                    "outputType": _first_present(item, ("fileType", "file_type",
                                                                        "outputType", "type")),
                                    "text": item.get("text"), "nodeId": item.get("nodeId")})
        return {"status": normalize_status(raw_status), "results": results,
                "usage": payload.get("usage") or {}, "raw": payload, "_channel": "status"}

    async def query_once(self, task_id: str) -> Dict[str, Any]:
        """按配置通道查一次，返回归一化结构 {status, results, usage, raw, _channel}。"""
        if self.channel == "status":
            return await self.query_status_v1(task_id)
        if self.channel == "v2":
            return self._normalize_v2(await self.query_v2(task_id))

        # auto：优先 v2；若返回结构完全无法识别，降级 status 并记住该决定
        try:
            norm = self._normalize_v2(await self.query_v2(task_id))
        except RunningHubError:
            raise
        if norm["status"] == "UNKNOWN" and not norm["results"]:
            try:
                alt = await self.query_status_v1(task_id)
            except RunningHubError:
                return norm
            if alt["status"] != "UNKNOWN":
                self.channel = "status"
                return alt
        return norm

    @staticmethod
    def _normalize_v2(payload: Dict[str, Any]) -> Dict[str, Any]:
        d = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        results: List[Dict[str, Any]] = []
        for item in (d.get("results") or []):
            if not isinstance(item, dict):
                continue
            url = item.get("url") or item.get("outputUrl")
            if url:
                results.append({"url": url, "outputType": item.get("outputType"),
                                "text": item.get("text"), "nodeId": item.get("nodeId")})
        return {"status": normalize_status(d.get("status")), "results": results,
                "usage": d.get("usage") or {}, "raw": payload, "_channel": "v2"}

    # ---------- 轮询 ----------
    async def poll_until_done(self, task_id: str, *, timeout_min: float, interval: float,
                              on_poll=None, max_transient_errors: int = 5) -> Dict[str, Any]:
        """轮询到终态。

        容错策略（对齐官方「轮询容少量瞬时失败、绝不无限轮询」纪律）：
        - 少量瞬时错误（网络抖动、单次 5xx）最多容忍 max_transient_errors 次连续失败；
        - 超时或连续失败过多则抛错（retriable=True，上层会复用同一 taskId 再轮询，不重复提交）。
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_min * 60
        last: Dict[str, Any] = {}
        transient = 0
        while True:
            try:
                last = await self.query_once(str(task_id))
                transient = 0
            except RunningHubError as e:
                if not e.retriable:
                    raise
                transient += 1
                if transient > max_transient_errors:
                    raise RunningHubError(
                        f"任务 {task_id} 连续 {max_transient_errors} 次查询失败，放弃本轮轮询：{e.short}",
                        retriable=True) from e
                if on_poll:
                    on_poll(str(task_id), f"QUERY_ERROR({transient})")
                await asyncio.sleep(interval)
                continue

            if on_poll:
                on_poll(str(task_id), last["status"])
            if last["status"] in TERMINAL:
                return last
            if loop.time() >= deadline:
                raise RunningHubError(
                    f"任务 {task_id} 轮询超时（{timeout_min} 分钟），最后状态 {last['status']}。"
                    f"任务可能仍在服务端执行，重跑会复用该 taskId 继续轮询，不会重复扣费。",
                    retriable=True,
                )
            await asyncio.sleep(interval)

    # ---------- 下载 ----------
    _DOWNLOAD_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")

    async def download(self, url: str, dest_path: str, retries: int = 3,
                       backoff: Sequence[float] = (3, 8, 20)) -> str:
        """下载产物（★ 2026-10-20 反馈 P1-7：带重试 + 原子落盘）。

        实测故障：AI 站 8 秒任务 SUCCESS（36 币已扣），下载阶段
        `ConnectionResetError [WinError 10054]`，脚本直接抛异常退出，**产物未落盘**。
        钱已花、文件没了 —— 批量跑就是几十段白跑。这里做三件事：
          ① 重试 `retries` 次（退避 backoff），只对网络类错误重试；
          ② 先写 `*.part` 再 `os.replace`，避免留下半截 mp4 被当成可用产物；
          ③ 全部失败时抛 retriable=True，由上层写 `pending_download.json` 供补下载。
        """
        dest = Path(dest_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        # 2026-10-17：账号3（.cn）产物落在 volces.com/TOS，直链会拒绝带 Authorization
        # 或非浏览器 UA 的请求（实测 HTTP 400，手动 curl 同一 URL 返回 200）。
        # 因此直链下载默认只带浏览器 UA + Referer；仅 RunningHub 自家域名才附鉴权头。
        host = (urlparse(url).netloc or "").lower()
        headers = {"User-Agent": self._DOWNLOAD_UA, "Referer": self.base_url + "/"}
        if "runninghub" in host:
            headers["Authorization"] = f"Bearer {self.api_key}"

        tmp = dest.with_name(dest.name + ".part")
        last: Optional[Exception] = None
        for attempt in range(max(0, int(retries)) + 1):
            try:
                async with self.client.stream("GET", url, headers=headers,
                                              timeout=self.timeout * 3) as resp:
                    if resp.status_code >= 400:
                        raise RunningHubError(
                            f"下载失败 HTTP {resp.status_code}: {truncate(url, 120)}",
                            http_status=resp.status_code,
                            retriable=resp.status_code >= 500 or resp.status_code == 429,
                        )
                    with open(tmp, "wb") as f:
                        async for chunk in resp.aiter_bytes(1 << 16):
                            if chunk:
                                f.write(chunk)
                if tmp.stat().st_size == 0:
                    raise RunningHubError(f"下载得到空文件: {dest}", retriable=True)
                os.replace(tmp, dest)
                return str(dest)
            except (httpx.TimeoutException, httpx.NetworkError, httpx.TransportError) as e:
                last = RunningHubError(f"下载网络异常: {type(e).__name__}: {e}", retriable=True)
            except RunningHubError as e:
                last = e
            except OSError as e:                       # 磁盘/句柄问题：重试无益
                raise RunningHubError(f"下载写盘失败: {type(e).__name__}: {e}",
                                      retriable=False) from e
            if last is not None and not getattr(last, "retriable", False):
                raise last
            try:
                tmp.unlink(missing_ok=True)            # type: ignore[call-arg]
            except (OSError, TypeError):
                pass
            if attempt < int(retries):
                await asyncio.sleep(backoff[min(attempt, len(backoff) - 1)])
        raise RunningHubError(
            f"下载连续 {int(retries) + 1} 次失败，产物未落盘（任务本身可能已成功计费）：{last}",
            retriable=True) from last

    # ---------- 节点发现（给 --probe 用） ----------
    async def get_webapp_nodes(self, webapp_id: Any) -> List[Dict[str, Any]]:
        path = f"/api/webapp/apiCallDemo?apiKey={self.api_key}&webappId={webapp_id}"
        payload = await self._request("GET", path, context="获取AI应用节点")
        self._raise_business(payload, "获取AI应用节点")
        return list((payload.get("data") or {}).get("nodeInfoList") or [])

    async def get_workflow_nodes(self, workflow_id: str) -> Dict[str, Any]:
        payload = await self._request(
            "POST", "/api/openapi/getJsonApiFormat",
            json_body={"apiKey": self.api_key, "workflowId": str(workflow_id)},
            context="获取工作流节点",
        )
        self._raise_business(payload, "获取工作流节点")
        data = payload.get("data") or {}
        raw = data.get("prompt") or "{}"
        try:
            prompt = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            prompt = {}
        return {"prompt": prompt, "data": data}

    async def get_nodes(self, kind: str, target_id: Any) -> List[Dict[str, Any]]:
        """统一节点发现：workflow 从 prompt 图里抽可编辑输入；ai-app 直接返回 nodeInfoList。"""
        k = (kind or "workflow").strip().lower()
        if k in ("ai-app", "ai_app", "app", "webapp"):
            return await self.get_webapp_nodes(target_id)
        got = await self.get_workflow_nodes(str(target_id))
        prompt = got.get("prompt") or {}
        nodes: List[Dict[str, Any]] = []
        for node_id, spec in prompt.items():
            if not isinstance(spec, dict):
                continue
            class_type = spec.get("class_type") or spec.get("type") or ""
            inputs = spec.get("inputs") or {}
            for field_name, value in inputs.items():
                if isinstance(value, (list, dict)):
                    continue
                nodes.append({"nodeId": str(node_id), "fieldName": str(field_name),
                              "fieldValue": value, "classType": class_type})
        return nodes


# ---------------------------------------------------------------------------
# 便捷入口
# ---------------------------------------------------------------------------
def pick_output_url(result: Dict[str, Any], want: str = "any") -> Optional[str]:
    """从轮询结果里挑一个产物 URL。

    want: "image" 找 png/jpg/webp | "video" 找 mp4/webm | "any" 取第一个
    """
    results = result.get("results") or []
    if want == "any":
        return results[0]["url"] if results else None
    ext_map = {"image": (".png", ".jpg", ".jpeg", ".webp", ".bmp"),
               "video": (".mp4", ".webm", ".mov", ".mkv")}
    exts = ext_map.get(want, ())
    for item in results:
        url = (item.get("url") or "").lower()
        otype = str(item.get("outputType") or "").lower()
        if url.split("?")[0].endswith(exts) or otype in [e.lstrip(".") for e in exts]:
            return item["url"]
    for item in results:  # 退化：outputType 标注为 video/image 的
        if str(item.get("outputType") or "").lower().startswith(want):
            return item.get("url")
    return None


def extract_usage(result: Dict[str, Any]) -> Dict[str, Any]:
    u = result.get("usage") or {}
    return {k: u.get(k) for k in ("consumeMoney", "consumeCoins", "taskCostTime",
                                  "thirdPartyConsumeMoney") if k in u}
