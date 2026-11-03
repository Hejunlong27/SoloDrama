# -*- coding: utf-8 -*-
"""comfy_probe.py —— Web 侧连 ComfyUI 的唯一通道（探活 / 队列 / 在线校验）

**实现不在这里**：真源是 `stages/_comfy_http.py`（引擎脚本要能独立跑，不能反向依赖
web 包）。这里只按路径加载，理由与 `comfy_ports.py` 相同 —— 同一套重试与错误分类
维护两份，一定会漂，而漂的表现是「界面上说在线、跑起来连不上」。

★ 为什么要缓存
--------------
`/api/comfy/status` 会被前端每隔几秒轮询，而 ComfyUI 在跑长任务时 `/system_stats`
本身就会变慢。不缓存的话，看板越刷越慢，最后像是「界面卡死」而其实是自己把服务问累了。
缓存 3 秒，并提供 `fresh=True` 绕过（用户点「重新检测」时用它）。
"""
from __future__ import annotations

import importlib.util
import threading
import time
from pathlib import Path

from . import paths

_ENGINE_FILE = paths.STAGES_DIR / "_comfy_http.py"
_mod = None
_lock = threading.Lock()

# 探活缓存：`(时间戳, 结果)`，只缓存成功/失败都算「刚刚问过」
_CACHE: dict = {"at": 0.0, "data": {}}
TTL = 3.0


def _load():
    global _mod
    if _mod is not None:
        return _mod
    if not _ENGINE_FILE.is_file():
        raise ImportError("找不到 HTTP 共享层：%s" % _ENGINE_FILE)
    spec = importlib.util.spec_from_file_location("_comfy_http_web", str(_ENGINE_FILE))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _mod = mod
    return mod


# ---------------------------------------------------------------------------
# 探活
# ---------------------------------------------------------------------------
def probe(fresh: bool = False) -> dict:
    """{online, version, device, vram_free_gb, latency_ms, error, ...}"""
    now = time.time()
    with _lock:
        if not fresh and _CACHE["data"] and (now - _CACHE["at"]) < TTL:
            d = dict(_CACHE["data"])
            d["cached"] = True
            d["age_s"] = round(now - _CACHE["at"], 1)
            return d
    try:
        d = _load().probe()
    except Exception as exc:                     # noqa: BLE001
        d = {"online": False, "version": "", "latency_ms": None,
             "error": "探活模块加载失败：%s" % exc, "kind": "engine", "checked_at": now}
    with _lock:
        _CACHE["at"] = now
        _CACHE["data"] = d
    out = dict(d)
    out["cached"] = False
    out["age_s"] = 0.0
    return out


def invalidate() -> None:
    """启动/停止服务后清缓存 —— 不然点完「启动」还要等 3 秒才看到状态变化。"""
    with _lock:
        _CACHE["at"] = 0.0
        _CACHE["data"] = {}


def queue() -> dict:
    """队列快照；离线时返回 ok=False 而不是抛异常（调用方是状态面板）。"""
    try:
        q = _load().queue_state()
        return {"ok": True, **q}
    except Exception as exc:                     # noqa: BLE001
        return {"ok": False, "reason": str(exc).splitlines()[0][:160],
                "running_count": 0, "pending_count": 0}


# ---------------------------------------------------------------------------
# 在线校验：这份工作流现在跑得动吗
# ---------------------------------------------------------------------------
def object_info(fresh: bool = False) -> dict:
    """缓存 object_info —— 它有几 MB，每次校验都拉一遍不合适。"""
    global _OBJ
    if not fresh and _OBJ.get("data"):
        return _OBJ["data"]
    d = _load().get_json("/object_info", timeout=60, retries=2, tag="object_info")
    _OBJ["data"] = d
    _OBJ["at"] = time.time()
    return d


_OBJ: dict = {"data": {}, "at": 0.0}


def apply_map_patches(wf: dict, mp: dict) -> dict:
    """把 map 的 `_substitute` / `_rewire` 应用到工作流（原地改）。

    ★ 校验必须用**运行时的样子**，不是文件里的样子。
      内置工作流里存的是作者机器上的模型名（`..._bf16.safetensors`），
      而本机实际跑的是 map 里 `_substitute` 指定的量化版。拿文件原值去校验，
      会报一堆「本机没有这个模型」—— 而真跑是通的。这类误报比漏报更糟：
      用户会去改一个不该改的地方，改完发现没用，从此不信校验结果。
    """
    for nid, patch in (mp.get("_substitute") or {}).items():
        if nid in wf and isinstance(patch, dict):
            wf[nid].setdefault("inputs", {}).update(patch)
    for nid, patch in (mp.get("_rewire") or {}).items():
        if nid in wf and isinstance(patch, dict):
            wf[nid].setdefault("inputs", {}).update(patch)
    return wf


def validate(wf: dict, mp: dict | None = None) -> dict:
    """静态 + 在线校验。返回 {ok, errors[], warns[], online}。

      errors：跑起来**一定**失败（节点类不存在 / 必需输入缺失）
      warns ：可能失败（模型文件本机没有 / 输出节点缺失）

    `mp` 是同名 map（有就传）：校验前会先应用它的覆盖，与运行时同口径。
    """
    import copy as _copy

    errors, warns = [], []
    wf = _copy.deepcopy(wf)
    if mp:
        apply_map_patches(wf, mp)
    try:
        ports = _load_ports().describe(wf)
    except Exception as exc:                     # noqa: BLE001
        return {"ok": False, "errors": ["端口识别失败：%s" % exc], "warns": [],
                "online": False}

    if not ports.get("outputs"):
        errors.append("没有输出节点（SaveVideo / SaveImage / VHS_VideoCombine），跑完不产出文件")

    online = True
    try:
        oi = object_info()
    except Exception as exc:                     # noqa: BLE001
        online = False
        warns.append("连不上 ComfyUI，跳过节点类与模型校验（%s）"
                     % str(exc).splitlines()[0][:100])
        oi = {}

    missing_cls = []
    missing_models = []
    if oi:
        for nid, node in wf.items():
            if not isinstance(node, dict):
                continue
            cls = str(node.get("class_type") or "")
            if cls not in oi:
                missing_cls.append("%s（%s）" % (cls, nid))
                continue
            req = ((oi[cls] or {}).get("input") or {}).get("required") or {}
            ins = node.get("inputs") or {}
            for field, spec in req.items():
                # 有些节点的输入是「动态字段组」：要求里写 `values`，实际键叫 `values.a`。
                # 精确匹配会把这类节点全判成「缺输入」，而它们跑得好好的。
                if field not in ins and not any(
                        str(k).startswith(field + ".") for k in ins):
                    errors.append("节点 %s（%s）缺必需输入 %s" % (nid, cls, field))
                    continue
                if field not in ins:
                    continue          # values.a 这种：值在子键上，跳过取值核对
                got = ins[field]
                # 只有「加载模型」这类下拉字段才值得核对文件名
                if isinstance(got, str) and isinstance(spec, list) and spec and isinstance(spec[0], list):
                    if got and got not in spec[0] and field.endswith(("_name", "name", "ckpt")):
                        missing_models.append("%s（节点 %s）" % (got, nid))
        if missing_cls:
            errors.append("本机 ComfyUI 没有这些节点类：%s（缺自定义节点包）"
                          % "、".join(missing_cls[:6]))

    if missing_models:
        warns.append("本机没有这些模型文件：%s" % "、".join(missing_models[:6]))

    return {"ok": not errors, "errors": errors, "warns": warns, "online": online,
            "node_count": ports.get("node_count"), "capacity": ports.get("capacity"),
            "outputs": ports.get("outputs") or [],
            "checked_at": time.time()}


def validate_path(path) -> dict:
    """按文件路径校验（自动带上同名 map）。接口层只调这一个。"""
    from pathlib import Path as _P

    p = _P(str(path))
    wf = {}
    try:
        import json as _json
        wf = _json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:                     # noqa: BLE001
        return {"ok": False, "errors": ["工作流读不出来：%s" % exc], "warns": [],
                "online": False}
    if not isinstance(wf, dict):
        return {"ok": False, "errors": ["不是 API 格式工作流"], "warns": [], "online": False}
    mp = {}
    side = p.with_suffix(".map.json")
    if side.is_file():
        try:
            import json as _json
            mp = _json.loads(side.read_text(encoding="utf-8")) or {}
        except Exception:                        # noqa: BLE001
            mp = {}
    out = validate(wf, mp)
    out["has_map"] = side.is_file()
    return out


def _load_ports():
    from . import comfy_ports
    return comfy_ports._load()


# ---------------------------------------------------------------------------
# 动作（用户点「停」/ 换工作流前释放显存）
# ---------------------------------------------------------------------------
def interrupt() -> dict:
    try:
        _load().interrupt()
        return {"ok": True, "detail": "已请求中断当前任务"}
    except Exception as exc:                     # noqa: BLE001
        return {"ok": False, "reason": str(exc).splitlines()[0][:160]}


def free_memory() -> dict:
    try:
        _load().free_memory()
        return {"ok": True, "detail": "已请求释放显存"}
    except Exception as exc:                     # noqa: BLE001
        return {"ok": False, "reason": str(exc).splitlines()[0][:160]}
