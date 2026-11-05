"""_comfy_http.py —— 连本机 ComfyUI 的唯一 HTTP 层：重试、错误分类、原子落盘。

为什么要有这一层
----------------
出图客户端（`stages/assets/comfyui/comfy_client.py`）与出片客户端
（`stages/video/comfyui/comfy_local_video.py`）各自写过一份 urllib 调用，
两边超时、重试、错误文案都不一样 —— 同一件「ComfyUI 没开」在两处显示成两种原因，
用户要分别排查。更实际的问题是：**两边都没有重试**。

8G 显存跑长任务时，偶发的 `ConnectionResetError` / 读超时是常态而不是异常。
零重试意味着一次抖动就作废一整镜（5–10 分钟），这是最贵的一种失败。

三条纪律
--------
1. **GET 幂等 → 重试**；**`POST /prompt` 绝不重试**。重发会真的再出一遍图或视频，
   比失败更糟 —— 账单上是时间，产物上是重复文件。只有「连接都没建立」（请求肯定
   没发出去）才允许重发一次。
2. **绕开系统代理**。本机服务被塞进 `HTTPS_PROXY` 会得到 502，而现场极难看懂
   （实测：`HTTP Error 502: Bad Gateway` 指向一个用户从没配过的东西）。
3. **下载先写 `.part` 再改名**。中断留下半个 mp4 比没有更危险 —— 下游会把它当
   完整产物继续拼接。

★ 与 `stages/_netguard.py` 的关系：
  这一层自己不做任何出口判定，连哪台机器完全由 `COMFYUI_URL` 决定；守卫在 socket /
  urllib / httpx 三个入口按主机放行。默认只放本机与内网，**云端镜像要逐条点名**：
  `SOLODRAMA_TRUSTED_HOSTS="*.container.x-gpu.com"`。这条设计不变 —— 它不是拦
  「用云端」，而是拦「没人声明过的域名」。
"""

from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_URL = "http://127.0.0.1:8188"

# 重试只对「可能自己好起来」的错误生效
_RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}
# 退避：0.4 → 1.2 → 3.0（总等待 < 5 秒，不把小抖动放大成卡顿）
_BACKOFF = (0.4, 1.2, 3.0)

# 空代理 opener：与系统代理环境变量彻底解耦
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class ComfyError(RuntimeError):
    """所有 ComfyUI 通信错误的基类。"""


class ComfyOffline(ComfyError):
    """连不上：服务没起、端口不通、连接被重置。"""


class ComfyHTTPError(ComfyError):
    """服务在线但返回了错误状态码。"""

    def __init__(self, status: int, url: str, body: str = ""):
        self.status = status
        self.url = url
        self.body = (body or "")[:400]
        super().__init__("HTTP %d · %s%s" % (status, url, (" · " + self.body) if self.body else ""))


class ComfyBusy(ComfyError):
    """队列里已有任务。不是错误，是「要排队」——调用方决定等还是放弃。"""


# ---------------------------------------------------------------------------
# 地址
# ---------------------------------------------------------------------------
def base_url() -> str:
    v = (os.environ.get("COMFYUI_URL") or os.environ.get("COMFY_URL") or DEFAULT_URL).strip()
    return v.rstrip("/")


def host_port() -> tuple:
    u = urllib.parse.urlsplit(base_url())
    return (u.hostname or "127.0.0.1", u.port or 8188)


# ---------------------------------------------------------------------------
# 底层请求（含重试）
# ---------------------------------------------------------------------------
def _one(url: str, *, data: bytes | None, headers: dict, timeout: float):
    req = urllib.request.Request(url, data=data, headers=headers or {},
                                 method="POST" if data is not None else "GET")
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as exc:
        # ★ urllib 在 4xx/5xx 时**抛异常**而不是返回状态码。不在这里转换的话，
        #   HTTPError 会被当成普通网络错误：404 会被重试 4 次（它永远不会自己好），
        #   500 会被误报成「通信中断、请求可能已被处理」（它其实明确失败了）。
        #   两者的提示都是错的，而错的方向正好相反 —— 一个让你白等，一个让你去查不存在的事。
        body = b""
        try:
            body = exc.read()
        except Exception:                                  # noqa: BLE001
            pass
        raise ComfyHTTPError(exc.code, url, body.decode("utf-8", "replace")) from exc


def _is_connect_failure(exc: BaseException) -> bool:
    """区分「请求没发出去」与「发出去了但坏了」。

    只有前者可以安全重发 POST —— 后者可能已经让 ComfyUI 开始出图，
    再发一次就是两份产物、两倍时间。
    """
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        return isinstance(reason, (ConnectionRefusedError, socket.gaierror))
    return isinstance(exc, (ConnectionRefusedError, socket.gaierror))


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, ComfyHTTPError):
        return exc.status in _RETRY_STATUS
    if isinstance(exc, (ComfyOffline, TimeoutError, socket.timeout, ConnectionResetError,
                        ConnectionAbortedError, urllib.error.URLError)):
        return True
    return False


def request(url: str, *, data: bytes | None = None, headers: dict | None = None,
            timeout: float = 60, retries: int = 3, tag: str = "") -> bytes:
    """发一个请求并返回 body 字节。`retries` 是**额外**尝试次数（总次数 = retries+1）。"""
    attempts = max(0, int(retries)) + 1
    last: BaseException | None = None
    for i in range(attempts):
        try:
            status, body = _one(url, data=data, headers=headers or {}, timeout=timeout)
            if status and status >= 400:
                raise ComfyHTTPError(status, url, body.decode("utf-8", "replace"))
            return body
        except ComfyHTTPError as exc:
            last = exc
            if exc.status not in _RETRY_STATUS or i == attempts - 1:
                raise
        except Exception as exc:                                   # noqa: BLE001
            last = exc
            # POST 只在「肯定没发出去」时重试；其余一律立即可见地失败
            if data is not None and not _is_connect_failure(exc):
                raise ComfyOffline("ComfyUI 通信中断（%s）：%s\n"
                                   "  · 请求可能已被服务端处理，**不要盲目重跑**，先查 ComfyUI 队列/历史"
                                   % (type(exc).__name__, str(exc)[:200])) from exc
            if not _retryable(exc) or i == attempts - 1:
                raise ComfyOffline(_offline_hint(exc, tag)) from exc
        if i < attempts - 1:
            time.sleep(_BACKOFF[min(i, len(_BACKOFF) - 1)])
    raise ComfyOffline(_offline_hint(last, tag))                  # pragma: no cover


def _offline_hint(exc: BaseException | None, tag: str = "") -> str:
    hp = host_port()
    where = ("（%s）" % tag) if tag else ""
    return ("连不上 ComfyUI http://%s:%d%s\n"
            "  原因：%s\n"
            "  · 服务没起 → 连接中心点「启动」，或开 ComfyUI 桌面版\n"
            "  · 端口不对 → 改 COMFYUI_URL（当前 %s）\n"
            "  · 刚重启 → 首次加载模型要 30–90 秒，稍等再点一次"
            % (hp[0], hp[1], where, str(exc)[:180] if exc else "未知错误", base_url()))


# ---------------------------------------------------------------------------
# 语义化封装
# ---------------------------------------------------------------------------
def get_json(path: str, *, timeout: float = 30, retries: int = 3, tag: str = "") -> dict:
    raw = request(base_url() + path, timeout=timeout, retries=retries, tag=tag or path)
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ComfyError("ComfyUI 返回的不是 JSON（%s）：%s" % (path, raw[:160])) from exc


def post_json(path: str, payload, *, timeout: float = 120, retries: int = 0,
              tag: str = "") -> dict:
    """POST。**默认不重试** —— 见模块说明第 1 条。"""
    data = json.dumps(payload).encode("utf-8")
    raw = request(base_url() + path, data=data, timeout=timeout, retries=retries,
                  headers={"Content-Type": "application/json"}, tag=tag or path)
    return json.loads(raw.decode("utf-8")) if raw else {}


def post_multipart(path: str, body: bytes, boundary: str, *, timeout: float = 180,
                   tag: str = "upload") -> dict:
    raw = request(base_url() + path, data=body, timeout=timeout, retries=1,
                  headers={"Content-Type": "multipart/form-data; boundary=" + boundary},
                  tag=tag)
    return json.loads(raw.decode("utf-8")) if raw else {}


def download(path_with_query: str, dst: str, *, timeout: float = 300, retries: int = 3,
             resume: bool = True) -> int:
    """下载到 dst。先写 `dst.part`，成功后改名 —— 半截文件不许冒充完整产物。

    断点续传（2026-11-05，云端接入）
    --------------------------------
    本机产物 1–40 MB，失败重下代价可接受；云端 1080p 交付件可能上百 MB，而云端链路
    比本机更容易断（弹性 IP / 隧道 / 镜像限速）。所以这里用 `Range: bytes=N-` 接着下：

      · 服务端给 **206** → 追加写 `.part`；给 **200** → 它不支持 Range，截断重写。
      · 服务端给 **416**（区间越界）→ `.part` 已经完整，直接收尾，不重下。
      · `resume=False` 时行为与旧版一致（每次从 0 写）。

    ★ 为什么不复用 `request()`：那一层返回的是**整个 body 的 bytes**，续传要么在内存里
      拼、要么把 Range 语义塞进 GET 的公共路径。下载是唯一需要流式写盘的调用点，
      单独一条实现比给公共层加开关更清楚。
    """
    os.makedirs(os.path.dirname(os.path.abspath(dst)) or ".", exist_ok=True)
    tmp = dst + ".part"
    url = base_url() + path_with_query
    attempts = max(0, int(retries)) + 1
    last: BaseException | None = None

    for i in range(attempts):
        got = os.path.getsize(tmp) if (resume and os.path.exists(tmp)) else 0
        headers = {"Range": "bytes=%d-" % got} if got else {}
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with _OPENER.open(req, timeout=timeout) as r:
                status = getattr(r, "status", 200) or 200
                # 206 = 按区间续写；200 = 服务端无视 Range，必须截断重写，
                # 否则前一次残留的字节会和新内容拼成「看起来完整、其实错位」的文件。
                mode = "ab" if (status == 206 and got) else "wb"
                with open(tmp, mode) as fh:
                    while True:
                        chunk = r.read(1 << 20)
                        if not chunk:
                            break
                        fh.write(chunk)
            break
        except urllib.error.HTTPError as exc:
            if exc.code == 416 and got:
                # 断点已经到最后了：服务端没有可发的东西，说明 .part 就是全量
                break
            if exc.code not in _RETRY_STATUS or i == attempts - 1:
                raise ComfyHTTPError(exc.code, url, "") from exc
            last = exc
        except Exception as exc:                                   # noqa: BLE001
            last = exc
            if not _retryable(exc) or i == attempts - 1:
                raise ComfyOffline(_offline_hint(exc, "download")) from exc
        if i < attempts - 1:
            time.sleep(_BACKOFF[min(i, len(_BACKOFF) - 1)])
    else:                                                          # pragma: no cover
        raise ComfyOffline(_offline_hint(last, "download"))

    # 大小校验：0 字节说明服务端给了空响应，不能当成功
    if not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise ComfyError("下载到 0 字节（%s）—— 产物可能已被清理" % path_with_query[:80])
    if os.path.exists(dst):
        os.remove(dst)
    os.replace(tmp, dst)
    return os.path.getsize(dst)


# ---------------------------------------------------------------------------
# 探活 / 队列
# ---------------------------------------------------------------------------
def probe(timeout: float = 2.5) -> dict:
    """一次探活。返回 {online, version, latency_ms, error}，**从不抛异常**。

    为什么不吃异常：调用方是状态面板，它需要「为什么不在线」这句话，
    而不是一个要自己 try 的异常。
    """
    t0 = time.time()
    try:
        st = get_json("/system_stats", timeout=timeout, retries=0, tag="probe")
    except Exception as exc:                                      # noqa: BLE001
        # 已经是 ComfyOffline 的消息里已含「怎么办」，别再包一层 —— 否则提示会
        # 出现两遍相同的三行建议，看起来像两个不同的错误。
        msg = str(exc) if isinstance(exc, ComfyError) else _offline_hint(exc, "探活")
        return {"online": False, "version": "", "latency_ms": None,
                "error": msg, "kind": _kind(exc), "checked_at": time.time()}
    dev = (st.get("devices") or [{}])[0]
    try:
        vram_free = float(dev.get("vram_free") or 0) / (1024 ** 3)
        vram_total = float(dev.get("vram_total") or 0) / (1024 ** 3)
    except (TypeError, ValueError):
        vram_free = vram_total = 0.0
    return {
        "online": True,
        "version": str((st.get("system") or {}).get("comfyui_version") or ""),
        "device": str(dev.get("name") or ""),
        "vram_free_gb": round(vram_free, 1),
        "vram_total_gb": round(vram_total, 1),
        "latency_ms": int((time.time() - t0) * 1000),
        "error": "",
        "kind": "",
        "checked_at": time.time(),
    }


def _kind(exc: BaseException) -> str:
    """把人话错误归类，供界面决定给「启动」还是给「重试」按钮。"""
    if isinstance(exc, ComfyHTTPError):
        return "http"
    if isinstance(exc, ComfyOffline):
        return "offline"
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "timeout"
    return "unknown"


def queue_state() -> dict:
    """队列快照：{running: [...], pending: [...], running_count, pending_count}。"""
    q = get_json("/queue", timeout=10, retries=1, tag="queue")
    run = q.get("queue_running") or []
    pend = q.get("queue_pending") or []
    return {"running": run, "pending": pend,
            "running_count": len(run), "pending_count": len(pend)}


def pid_running(pid: str) -> bool:
    """该 prompt 是否在跑或在排队。用于判断「任务是不是被清掉了」。"""
    try:
        q = queue_state()
    except ComfyError:
        return True            # 查不到就别急着判死，宁可多等一轮
    for item in list(q["running"]) + list(q["pending"]):
        # ComfyUI 队列项形状：[number, prompt_id, prompt, extra_data, outputs]
        if isinstance(item, (list, tuple)) and len(item) > 1 and str(item[1]) == str(pid):
            return True
    return False


def interrupt() -> dict:
    """打断当前任务（用户点「停」时用）。不影响队列中其余项。"""
    return post_json("/interrupt", {}, timeout=10, retries=0, tag="interrupt")


def free_memory(unload_models: bool = True, free_memory: bool = True) -> dict:
    """释放显存。8G 卡换工作流前调一次，能避免「明明没任务却 OOM」。"""
    return post_json("/free", {"unload_models": bool(unload_models),
                              "free_memory": bool(free_memory)}, timeout=30, retries=0, tag="free")


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    p = probe()
    print("ComfyUI  %s" % base_url())
    if p["online"]:
        print("  [OK] 在线 v%s · %s · 空闲 %.1f/%.1fG · %dms"
              % (p["version"], p["device"] or "?", p["vram_free_gb"], p["vram_total_gb"],
                 p["latency_ms"]))
        try:
            q = queue_state()
            print("  队列   运行 %d / 排队 %d" % (q["running_count"], q["pending_count"]))
        except ComfyError as e:
            print("  队列   读不到：%s" % str(e)[:120])
        sys.exit(0)
    print("  [NG] 离线")
    print(p["error"])
    sys.exit(1)
