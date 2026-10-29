# -*- coding: utf-8 -*-
"""comfy_launcher.py —— 「本地 ComfyUI 按需启动」的 Web 入口

实现不在这里
------------
真源是 `stages/assets/comfyui/comfy_boot.py`：引擎脚本（`gen_assets_local.py`）
要能脱离 Web 层独立跑，不能反向 import `web.core`。这里只做三件事：

1. 按路径加载引擎模块（与 `comfy_ports.py` 同一套做法，避免两套规则漂移）；
2. 把连接中心里的配置喂给它（地址 / 是否允许自动启动 / 手动指定的安装）；
3. 把「启动」变成**有状态的后台动作** —— 起一个线程去等就绪，接口立刻返回，
   前端轮询 `GET /api/comfy/status` 看进度。否则一个请求要阻塞 30–120 秒，
   uvicorn 单进程会被它卡住，页面连「正在启动」都刷不出来。

为什么不等就绪再返回
--------------------
ComfyUI 冷启动（torch + cu130 + 自定义节点）实测 30–90 秒。同步等待会让
「启动」按钮变成一次长达一分半的无响应请求，用户会以为点坏了。
"""
from __future__ import annotations

import importlib.util
import threading
import time

from . import connections, paths

_ENGINE_FILE = paths.STAGES_DIR / "assets" / "comfyui" / "comfy_boot.py"
_mod = None

_START_LOCK = threading.Lock()
_TASK = {
    "state": "idle",            # idle / starting / ok / failed
    "started_at": 0.0,
    "finished_at": 0.0,
    "elapsed": 0.0,
    "action": "",               # attached / started / failed / refused
    "detail": "",
    "next": "",
    "reason": "",
    "pid": 0,
    "lines": [],
}
_TASK_MAX_LINES = 20


def _load():
    global _mod
    if _mod is not None:
        return _mod
    if not _ENGINE_FILE.is_file():
        raise ImportError("找不到引擎侧启动模块：%s" % _ENGINE_FILE)
    spec = importlib.util.spec_from_file_location("_comfy_boot_engine", str(_ENGINE_FILE))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _mod = mod
    return mod


def _cfg() -> dict:
    """连接中心里 comfyui 段的三个相关键（其余键与这里无关）。"""
    try:
        c = (connections.load() or {}).get("comfyui") or {}
    except Exception:      # noqa: BLE001
        c = {}
    return {
        "base_url": str(c.get("base_url") or "http://127.0.0.1:8188").strip(),
        "autostart": c.get("autostart", True) is not False,
        "launch": c.get("launch") if isinstance(c.get("launch"), dict) else {},
    }


def _note(msg: str) -> None:
    """收集进度行（前端显示「正在做什么」）。"""
    rows = _TASK.setdefault("lines", [])
    rows.append("%s %s" % (time.strftime("%H:%M:%S"), str(msg)[:200]))
    if len(rows) > _TASK_MAX_LINES:
        del rows[:-_TASK_MAX_LINES]
    _TASK["elapsed"] = round(time.time() - (_TASK["started_at"] or time.time()), 1)


def busy() -> bool:
    return _TASK["state"] == "starting"


def task() -> dict:
    out = dict(_TASK)
    if out["state"] == "starting" and out["started_at"]:
        out["elapsed"] = round(time.time() - out["started_at"], 1)
    return out


def _finish(res: dict) -> dict:
    _TASK.update({
        "state": "ok" if res.get("ok") else "failed",
        "finished_at": time.time(),
        "elapsed": float(res.get("elapsed") or _TASK.get("elapsed") or 0.0),
        "action": str(res.get("action") or ""),
        "detail": str(res.get("detail") or ""),
        "next": str(res.get("next") or ""),
        "reason": str(res.get("reason") or ""),
        "pid": int(res.get("pid") or 0),
    })
    return res


def status() -> dict:
    """一屏状态，供连接中心 / 体检页显示。**不启动任何东西。**"""
    cfg = _cfg()
    try:
        st = _load().status(cfg["base_url"], cfg["launch"])
    except Exception as e:      # noqa: BLE001
        return {"ok": False, "reason": "engine", "detail": "读不到启动模块：%s" % type(e).__name__,
                "online": False, "base_url": cfg["base_url"], "can_start": False,
                "autostart": cfg["autostart"], "task": task()}
    st["autostart"] = bool(cfg["autostart"]) and bool(st.get("autostart"))
    st["can_start"] = bool(st.get("can_start")) and bool(cfg["autostart"])
    st["task"] = task()
    return st


def ensure_sync(wait_s: int = 120, log=None) -> dict:
    """同步版：真的等它起来（体检页的一键修复需要「修完复检」，不能异步）。"""
    cfg = _cfg()
    _TASK.update({"state": "starting", "started_at": time.time(), "finished_at": 0.0,
                  "elapsed": 0.0, "action": "", "detail": "", "next": "", "reason": "",
                  "pid": 0, "lines": []})
    try:
        res = _load().ensure(cfg["base_url"], autostart=cfg["autostart"],
                             wait_s=wait_s, log=log, launch_cfg=cfg["launch"])
    except Exception as e:      # noqa: BLE001
        res = {"ok": False, "action": "failed", "reason": "exception",
               "detail": "%s: %s" % (type(e).__name__, str(e)[:200]),
               "next": "把这段原文发给开发者"}
    return _finish(res)


def _worker(wait_s: int) -> None:
    try:
        ensure_sync(wait_s=wait_s, log=_note)
    finally:
        if _TASK["state"] == "starting":
            _finish({"ok": False, "action": "failed", "detail": "启动线程异常结束"})


def start_async(wait_s: int = 180) -> dict:
    """起一个后台线程去启动 / 等待就绪，接口立刻返回。重复点击不会起第二个实例。"""
    if busy():
        return {"ok": True, "action": "starting", "detail": "已经在启动了", "elapsed": _TASK["elapsed"]}
    st = status()
    if st.get("online"):
        _TASK.update({"state": "ok", "action": "attached", "detail": st.get("detail") or "已在线",
                      "started_at": time.time(), "finished_at": time.time(), "elapsed": 0.0,
                      "pid": int(st.get("pid") or 0), "next": "", "reason": ""})
        return {"ok": True, "action": "attached", "detail": st.get("detail") or "ComfyUI 已在线"}
    if not st.get("can_start"):
        reason = ("autostart_off" if not _cfg()["autostart"]
                  else ("remote" if not st.get("loopback", True) else "no_install"))
        detail = {
            "autostart_off": "自动启动已关闭：到「连接中心 → 本地出图」打开开关",
            "remote": "地址指向的是远程机器，不在本机启动",
            "no_install": "没找到本机 ComfyUI 安装：在连接中心填解释器与 main.py，或先用桌面版启动一次",
        }[reason]
        _TASK.update({"state": "failed", "action": "refused", "reason": reason,
                      "detail": detail, "started_at": time.time(), "finished_at": time.time()})
        return {"ok": False, "action": "refused", "reason": reason, "detail": detail}

    with _START_LOCK:
        if busy():
            return {"ok": True, "action": "starting", "detail": "已经在启动了"}
        _TASK.update({"state": "starting", "started_at": time.time(), "finished_at": 0.0,
                      "elapsed": 0.0, "action": "", "detail": "正在启动 ComfyUI…", "next": "",
                      "reason": "", "pid": 0, "lines": []})
        _note("请求启动（%s）" % _cfg()["base_url"])
        threading.Thread(target=_worker, args=(wait_s,), name="comfy-boot", daemon=True).start()
    return {"ok": True, "action": "starting", "detail": "正在启动，通常 30–90 秒"}


def stop() -> dict:
    """只停 Studio 自己启动的实例（引擎侧会核对「这个 pid 是否正在监听该端口」）。"""
    if busy():
        return {"ok": False, "reason": "busy", "detail": "正在启动中，等它结束再停"}
    try:
        res = _load().stop()
    except Exception as e:      # noqa: BLE001
        res = {"ok": False, "reason": "exception", "detail": "%s: %s" % (type(e).__name__, str(e)[:160])}
    if res.get("ok"):
        _TASK.update({"state": "idle", "action": res.get("action") or "stopped",
                      "detail": res.get("detail") or "已停止"})
    return res


def tail(lines: int = 20) -> str:
    try:
        return _load().log_tail(lines)
    except Exception:      # noqa: BLE001
        return ""
