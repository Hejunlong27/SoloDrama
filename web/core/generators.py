# -*- coding: utf-8 -*-
"""generators.py —— 「图像 / 视频 生成通道」的统一台账（界面与命令共用一份口径）

为什么单独一层
--------------
到 2026-10-29 为止，生成能力散在四个地方，各有各的说法：
  * 本地出图      `stages/assets/comfyui/comfy_client.py`（Qwen-Image 2.1）
  * 出片          `stages/video/comfyui`（本地 ComfyUI H3）
用户在界面上根本看不出「我这部片子到底能用哪条通道、缺什么、要花多少钱」。
更要紧的是**文生图与图生图是两个不同的工作流**（图生图多一个加载图像节点），
混用一个 id 会出现「传了参考图但出来还是纯文生图」这种花钱买错东西的情况。

本模块只做一件事：把每条通道的**真实状态**算出来，并写清缺什么、下一步做什么。
不做提交、不写配置、不联网产生费用（ComfyUI 只用只读接口）。
"""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

from . import paths

def _comfy_base() -> str:
    """ComfyUI 地址取连接中心，**不再硬编码 8188**。

    硬编码的后果很具体：用户在界面上把地址改成 9000，这里仍探 8188 ——
    生成通道说「未启动」，实际出图脚本（走 COMFYUI_URL）却能跑；两套口径比没有更糟。
    """
    try:
        from . import connections
        base = str((connections.load().get("comfyui") or {}).get("base_url") or "").strip()
    except Exception:      # noqa: BLE001
        base = ""
    return (base or "http://127.0.0.1:8188").rstrip("/")

_CACHE: dict = {}
_TTL_PROBE = 30.0        # 在线探测
_TTL_INFO = 300.0        # object_info 很大，缓存久一点

IMAGE_LOCAL_WF = paths.STAGES_DIR / "assets" / "comfyui" / "workflow_qwen_image21.json"
VIDEO_LOCAL_WF = paths.STAGES_DIR / "video" / "comfyui" / "workflow_h3_local.json"

ENGINE_TEXT = {"local": "本地 ComfyUI"}
STATUS_TEXT = {"ready": "可用", "config": "待配置", "offline": "未启动", "missing": "缺文件",
               "no_ws": "未选项目", "unsupported": "不支持"}


def _json_url(url: str, timeout: float = 3.0):
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # 本机服务，绕开系统代理
    with op.open(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _comfy() -> dict:
    """ComfyUI 在线状态（只读 /system_stats，不占 GPU、不产生费用）。"""
    now = time.time()
    hit = _CACHE.get("comfy")
    if hit and now - hit[0] < _TTL_PROBE:
        return hit[1]
    out = {"online": False, "version": "", "vram_free_gb": 0.0, "reason": ""}
    try:
        st = _json_url(_comfy_base() + "/system_stats", 2.5)
        dev = (st.get("devices") or [{}])[0]
        out.update({"online": True,
                    "version": str((st.get("system") or {}).get("comfyui_version") or ""),
                    "vram_free_gb": round(int(dev.get("vram_free") or 0) / (1024 ** 3), 1)})
    except Exception as exc:  # noqa: BLE001
        out["reason"] = "%s（没启动：出图时会自动拉起后台实例）" % type(exc).__name__
    _CACHE["comfy"] = (now, out)
    return out


def _comfy_info() -> dict:
    now = time.time()
    hit = _CACHE.get("info")
    if hit and now - hit[0] < _TTL_INFO:
        return hit[1]
    try:
        d = _json_url(_comfy_base() + "/object_info", 20.0)
    except Exception:  # noqa: BLE001
        d = {}
    _CACHE["info"] = (now, d)
    return d


def _model_opts(info: dict, node: str, key: str) -> list:
    try:
        v = info[node]["input"]["required"][key][0]
        return v if isinstance(v, list) else []
    except Exception:  # noqa: BLE001
        return []


def _wf_models(wf: dict) -> list:
    """从 API 格式工作流里抽出所有要加载的模型文件名（用于「缺哪个」）。"""
    out = []
    for nid, node in (wf or {}).items():
        if not isinstance(node, dict):
            continue
        cls, ins = node.get("class_type"), (node.get("inputs") or {})
        for f in ("unet_name", "clip_name", "vae_name", "lora_name", "ckpt_name"):
            if f in ins and isinstance(ins[f], str):
                out.append((nid, cls, f, ins[f]))
    return out


def _local_wf_state(path: Path, info: dict) -> dict:
    """本地工作流：文件在不在 + 节点类齐不齐 + 模型文件齐不齐。"""
    if not path.is_file():
        return {"ok": False, "status": "missing", "detail": "工作流文件不存在：%s" % path.name,
                "missing": [], "nodes": 0}
    try:
        wf = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status": "missing", "detail": "工作流不是合法 JSON（%s）" % type(exc).__name__,
                "missing": [], "nodes": 0}
    if not info:
        return {"ok": False, "status": "offline", "detail": "ComfyUI 未启动，无法核对节点与模型",
                "missing": [], "nodes": len(wf)}
    miss_cls = sorted({v.get("class_type") for v in wf.values()} - set(info))
    miss_models = []
    for nid, cls, field, name in _wf_models(wf):
        probe = {"unet_name": ("UNETLoader", "unet_name"),
                 "clip_name": ("CLIPLoader", "clip_name"),
                 "vae_name": ("VAELoader", "vae_name"),
                 "lora_name": ("LoraLoaderModelOnly", "lora_name")}.get(field)
        have = _model_opts(info, *probe) if probe else []
        if name not in have:
            miss_models.append("%s(#%s) 缺 %s" % (cls, nid, name))
    if miss_cls:
        return {"ok": False, "status": "missing", "nodes": len(wf), "missing": miss_cls + miss_models,
                "detail": "缺自定义节点：%s" % "、".join(miss_cls[:3])}
    if miss_models:
        return {"ok": False, "status": "missing", "nodes": len(wf), "missing": miss_models,
                "detail": "缺模型文件 %d 个（首个：%s）" % (len(miss_models), miss_models[0])}
    return {"ok": True, "status": "ready", "nodes": len(wf), "missing": [],
            "detail": "%d 节点 / 模型齐全" % len(wf)}


def _project_cfg(ws) -> tuple:
    if not ws:
        return {}, ""
    p = Path(str(ws)) / "video-pipeline" / "config.local.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")), str(p)
    except Exception:  # noqa: BLE001
        return {}, str(p)
def channels(ws=None) -> dict:
    """返回所有生成通道的真实状态。只读，不产生任何费用。"""
    comfy = _comfy()
    info = _comfy_info() if comfy["online"] else {}
    cfg, cfg_path = _project_cfg(ws)

    img_local_t2i = _local_wf_state(IMAGE_LOCAL_WF, info)
    vid_local = _local_wf_state(VIDEO_LOCAL_WF, info)

    items = [
        {"id": "image.local.t2i", "kind": "image", "engine": "local", "mode": "t2i",
         "label": "本地 ComfyUI · 文生图", "model_text": "Qwen-Image 2.1（int8 + 4step turbo）",
         "workflow": str(IMAGE_LOCAL_WF), "billing": "free", "cost_text": "￥0",
         "command": "assets.local",
         "detail": ("ComfyUI v%s · 空闲 %.1fG ｜ " % (comfy["version"], comfy["vram_free_gb"])
                    if comfy["online"] else comfy["reason"])
                   + (img_local_t2i["detail"] if comfy["online"] else ""),
         "status": ("ready" if img_local_t2i["ok"] and comfy["online"]
                    else ("offline" if not comfy["online"] else img_local_t2i["status"])),
         "missing": img_local_t2i.get("missing") or [],
         "next": "" if img_local_t2i["ok"] and comfy["online"] else "启动 ComfyUI 或补齐工作流/模型"},

        {"id": "image.local.i2i", "kind": "image", "engine": "local", "mode": "i2i",
         "label": "本地 ComfyUI · 图生图", "model_text": "（未内置）",
         "workflow": "", "billing": "free", "cost_text": "￥0", "command": "",
         "status": "unsupported",
         "detail": "本机还没有带参考图输入的 Qwen-Image 工作流；现用的 workflow_qwen_image21.json 是纯文生图",
         "missing": [], "next": "导出含 LoadImage 的图生图工作流放到 stages/assets/comfyui/，再登记节点映射"},

        {"id": "video.local.i2v", "kind": "video", "engine": "local", "mode": "i2v",
         "label": "本地 ComfyUI · 图生视频", "model_text": "MiniMax H3（fl2va w4a8 + turbo 4step LoRA）",
         "workflow": str(VIDEO_LOCAL_WF), "billing": "free", "cost_text": "￥0",
         "command": "video.local",
         "detail": ("ComfyUI v%s · 空闲 %.1fG ｜ " % (comfy["version"], comfy["vram_free_gb"])
                    if comfy["online"] else comfy["reason"]) + (vid_local["detail"] if comfy["online"] else ""),
         "status": ("ready" if vid_local["ok"] and comfy["online"]
                    else ("offline" if not comfy["online"] else vid_local["status"])),
         "missing": vid_local.get("missing") or [],
         "next": "" if vid_local["ok"] and comfy["online"] else "启动 ComfyUI 或补齐工作流/模型"},

    ]

    for it in items:
        it["kind_text"] = "图像" if it["kind"] == "image" else "视频"
        it["engine_text"] = ENGINE_TEXT.get(it["engine"], it["engine"])
        it["mode_text"] = {"t2i": "文生图", "i2i": "图生图", "i2v": "图生视频"}.get(it["mode"], it["mode"])
        it["status_text"] = STATUS_TEXT.get(it["status"], it["status"])

    counts = {}
    for k in ("image", "video"):
        sub = [x for x in items if x["kind"] == k]
        counts[k] = {"total": len(sub), "ready": len([x for x in sub if x["status"] == "ready"])}
    return {"items": items, "counts": counts, "comfy": comfy,
            "ws": str(ws or ""), "config_path": cfg_path}
