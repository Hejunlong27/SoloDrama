# -*- coding: utf-8 -*-
"""generators.py —— 「图像 / 视频 生成通道」的统一台账（界面与命令共用一份口径）

为什么单独一层
--------------
到 2026-10-29 为止，生成能力散在四个地方，各有各的说法：
  * 本地出图      `stages/assets/comfyui/comfy_client.py`（Qwen-Image 2.1）
  * 云端出图·工作流 `gen_assets_rh_workflow.py`（nodeInfoList，文生图 / 图生图）
  * 出片          `stages/video/workflow`（RunningHub H3）
用户在界面上根本看不出「我这部片子到底能用哪条通道、缺什么、要花多少钱」。
更要紧的是**文生图与图生图是两个不同的工作流**（图生图多一个加载图像节点），
混用一个 id 会出现「传了参考图但出来还是纯文生图」这种花钱买错东西的情况。

本模块只做一件事：把每条通道的**真实状态**算出来，并写清缺什么、下一步做什么。
不做提交、不写配置、不联网产生费用（ComfyUI 只用只读接口）。
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

from . import generation_models, paths

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

# ★ 2026-11-06：改成与**执行器**同一个文件。此前这里（和预检）指向 `workflow_qwen_image21.json`
#   （10-16 的旧图：qwen_image_2.1_int8 + 4step LoRA），而 `comfy_client.DEFAULT_WORKFLOW`
#   与全部预配置卡用的是 `workflow_qwen21_t2i_hq.json`（11-02：turbo 融合版）。
#   后果和视频那条一样 —— 没有确认单的项目，界面/预检核的是 A，真跑提交的是 B。
IMAGE_LOCAL_WF = paths.STAGES_DIR / "assets" / "comfyui" / "workflow_qwen21_t2i_hq.json"
# ★ 必须与执行器同源：默认工作流的真源是 `stages/video/comfyui/workflow_defaults.py`。
#   历史上这里写死过 `workflow_h3_local.json`，而执行器已换 canvas —— 于是「界面核对 A、
#   真跑提交 B」。2026-11-06 起视频默认值还**按通道分**（本机 canvas / 云端 pika），
#   所以走 `_video_wf(cloud)`，别再在这一层拼文件名。
def _video_wf(cloud: bool = False) -> Path:
    d = paths.STAGES_DIR / "video" / "comfyui"
    try:
        if str(d) not in sys.path:
            sys.path.insert(0, str(d))
        import workflow_defaults as WD                       # noqa: PLC0415
        return Path(WD.video_path(cloud))
    except Exception:                                        # noqa: BLE001
        return d / "workflow_h3_minimax_audio.json"


VIDEO_LOCAL_WF = Path(os.environ.get("COMFYUI_VIDEO_WORKFLOW") or _video_wf(False))
VIDEO_CLOUD_WF = _video_wf(True)

ENGINE_TEXT = {"local": "本地 ComfyUI", "cloud": "云端 ComfyUI",
               "rh": "RunningHub 工作流"}
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
    # ★ 模型替换必须应用：`_substitute` 把云端/作者机器的文件名换成本机现有的量化版，
    #   不应用就会拿**原始文件名**去核对，报一堆「缺模型」而实际能跑（告警一旦失信就没人看）。
    side = path.with_name(path.stem + ".map.json")
    if side.is_file():
        try:
            mm = json.loads(side.read_text(encoding="utf-8"))
            for tid, patch in (mm.get("_substitute") or {}).items():
                if tid in wf and isinstance(patch, dict):
                    ins = wf[tid].setdefault("inputs", {})
                    for k, v in patch.items():
                        if k in ins:
                            ins[k] = v
        except Exception:                              # noqa: BLE001 —— 映射坏了不该拖垮页面
            pass
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


def image_channel(ws) -> dict:
    """资产出图**这一次会走哪条通道** —— 唯一依据是项目自己的 `model-plan.json`。

    为什么不让 UI 自己选「本地/云端」：`drama.py` 的 `_model_gate()` 会拿
    `engine_arg` 与确认单比对，选错就退出码 4（「确认了云端却用 local」）。
    界面若自己给一个默认值，用户点下去只会看到「按钮没反应」——
    `graph._cmd_for()` 已经踩过这个坑，这里沿用同一条口径。

    返回的 `spec` 就是该跑的 web 命令 id；`paid` 直接取命令元数据的 billing，
    不在 UI 里另判一次「这个要不要钱」。
    """
    from . import commands as CMDS            # 局部导入：避免模块级循环依赖

    choice = plan_choice(ws, "image")
    det = _plan_detail(ws, "image")
    url = str(det.get("comfy_url") or "")
    wf = str(det.get("comfy_workflow") or "")

    # model-plan 里的 label / cost 是「模型确认单」写入的原文，直接用它，
    # 不在 UI 里另编一套文案 —— 否则确认单说「计费」而按钮说「免费」。
    label, cost_text = "", ""
    try:
        d = json.loads((Path(str(ws)) / "model-plan.json").read_text(encoding="utf-8-sig"))
        node = (((d.get("models") or {}).get("image")) or {})
        label = str(node.get("label") or "")
        cost_text = str(node.get("cost") or "")
        confirmed = bool(node.get("confirmed"))
    except (OSError, ValueError):
        confirmed = False

    if choice == "cloud_comfyui":
        spec = "assets.cloud"
    elif choice in ("runninghub", "rh"):
        spec = "assets.rh_wf"
    else:
        spec = "assets.local"

    cmd = CMDS.get(spec)
    paid = bool(cmd and getattr(cmd, "billing", "") == "paid")

    # 「本机地址 + 选云端」= 假云端，引擎会直接拦。提前说出来，别等点了才报错。
    fake_cloud = bool(choice == "cloud_comfyui" and url and _is_loopback(url))
    return {
        "ok": True,
        "choice": choice or "",
        "label": label or (getattr(cmd, "title", "") if cmd else ""),
        "cost": cost_text,
        "spec": spec,
        "paid": paid,
        "url": url,
        "workflow": wf,
        "confirmed": confirmed,
        "fake_cloud": fake_cloud,
        "backup": spec != "assets.rh_wf",   # RH 工作流通道不经过本地落盘，无法备份旧图
    }


def board_channel(ws) -> dict:
    """分镜图当前会走哪条下游生图通道。"""
    choice = plan_choice(ws, "board")
    det = _plan_detail(ws, "board")
    label, cost_text, confirmed = "", "", False
    try:
        d = json.loads((Path(str(ws)) / "model-plan.json").read_text(encoding="utf-8-sig"))
        node = (((d.get("models") or {}).get("board")) or {})
        label = str(node.get("label") or "")
        cost_text = str(node.get("cost") or "")
        confirmed = bool(node.get("confirmed"))
    except (OSError, ValueError):
        pass
    engine = {"local_comfyui": "local", "cloud_comfyui": "cloud",
              "zzai_image_api": "zzai", "runninghub_workflow": "rh",
              "closed_source": "manual"}.get(choice, "local")
    return {
        "ok": True,
        "choice": choice or "",
        "engine": engine,
        "label": label or ("本地 ComfyUI（￥0）" if engine == "local" else choice),
        "cost": cost_text,
        "paid": engine in ("cloud", "zzai", "rh"),
        "confirmed": confirmed,
        "url": str(det.get("comfy_url") or ""),
        "workflow": str(det.get("comfy_workflow") or ""),
        "fallback_local": not confirmed,
    }


def _is_loopback(url: str) -> bool:
    """地址是否指回本机。与 `drama._is_loopback_url` 同一条判据（含 0.0.0.0 / 内网段）。"""
    u = str(url or "").lower()
    for host in ("127.0.0.1", "localhost", "0.0.0.0", "::1", "[::1]", "192.168.", "10.", "172.16."):
        if host in u:
            return True
    return False


def _plan_detail(ws, kind: str) -> dict:
    """项目模型确认单里这一类的 detail（读不到就空 dict）。

    云端通道的地址与工作流**只认确认单**：它同时是执行期的依据（`model_gate.apply_env`
    会把同一个 comfy_url 灌进 COMFYUI_URL），界面上显示的必须与真跑一致。
    """
    if not ws:
        return {}
    try:
        d = json.loads((Path(str(ws)) / "model-plan.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    det = ((((d.get("models") or {}).get(kind)) or {}).get("detail") or {})
    return det if isinstance(det, dict) else {}


def plan_choice(ws, kind: str) -> str:
    """项目在模型确认单里为这一类选的通道（`local_comfyui` / `cloud_comfyui` / `runninghub`…）。

    ★ 公开而非私有：流水线调度（`pipeline.py`）与画布（`graph.py`）也要按它选命令。
      三处各写一份「读 model-plan.json」的结果，必然是有的地方看到云端、有的地方看到本地，
      然后「流水线跑本地、界面说云端」—— 这类不一致比功能缺失更难查。
    """
    if not ws:
        return ""
    try:
        d = json.loads((Path(str(ws)) / "model-plan.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return ""
    return str((((d.get("models") or {}).get(kind)) or {}).get("choice") or "")


# 旧名保留：模块内已有调用点，改名不改语义
_plan_choice = plan_choice


def cloud_selected(ws, kind: str) -> bool:
    """这一类是否**确认了云端 ComfyUI**（只认确认单，不看环境变量与界面缓存）。"""
    return plan_choice(ws, kind) == "cloud_comfyui"


def _is_loopback(url: str) -> bool:
    h = (url or "").split("//")[-1].split("/")[0].split(":")[0].lower()
    return h in ("127.0.0.1", "localhost", "::1", "")


_CLOUD_CACHE: dict = {}


def _cloud_probe(url: str) -> tuple:
    """云端实例的 (在线状态, object_info)。只读；失败归类成 reason，不抛。"""
    now = time.time()
    hit = _CLOUD_CACHE.get(url)
    if hit and now - hit["at"] < 30:
        return hit["st"], hit["info"]
    st = {"online": False, "version": "", "vram_free_gb": 0.0, "reason": ""}
    info: dict = {}
    try:
        s = _json_url(url + "/system_stats", timeout=8)
        dev = (s.get("devices") or [{}])[0]
        st = {"online": True,
              "version": str((s.get("system") or {}).get("comfyui_version") or ""),
              "vram_free_gb": round(float(dev.get("vram_free") or 0) / (1024 ** 3), 1),
              "reason": ""}
        info = _json_url(url + "/object_info", timeout=40)
    except Exception as exc:                       # noqa: BLE001
        st["reason"] = "连不上 %s（%s）" % (url, type(exc).__name__)
    _CLOUD_CACHE[url] = {"at": now, "st": st, "info": info}
    return st, info


def _local_wf(ws, kind: str) -> Path:
    """本地实际会提交的工作流：确认单 > 环境变量 > 仓库默认。

    ★ 与 `gen_preflight.resolve()` 同一条口径。这里长期只看仓库常量，于是
      「项目确认单指向 hq 版」时页面核对的是默认版 —— 报缺节点，而真跑其实是通的。
    """
    det = _plan_detail(ws, kind)
    wf = str(det.get("comfy_workflow") or "").strip()
    if wf and Path(wf).is_file():
        return Path(wf)
    return VIDEO_LOCAL_WF if kind == "video" else IMAGE_LOCAL_WF


def _cloud_target(ws, kind: str) -> dict:
    """云端通道的 (url, workflow)；没确认云端或没有地址就返回 {}（= 这条通道不显示）。

    ★ 不能只看 detail 里有没有 comfy_url：项目确认「本地 ComfyUI」时也会把
      `http://127.0.0.1:8188` 记进 detail（那是本地地址，不是云端）。只看地址会把
      本地项目错判出一条「云端可用」，然后它去探 127.0.0.1 —— 假绿灯比红灯更糟。
    """
    choice = _plan_choice(ws, kind)
    if choice and choice != "cloud_comfyui":
        return {}
    det = _plan_detail(ws, kind)
    url = str(det.get("comfy_url") or "").strip()
    if url and _is_loopback(url) and choice != "cloud_comfyui":
        url = ""
    via = "确认单"
    if not url:
        base = _comfy_base()
        if not _is_loopback(base):
            url, via = base, "连接中心/环境变量"
    if not url:
        return {}
    # 云端出图仍走 `gen_assets_local`（同一客户端）；工作流取确认单，缺就用仓库默认
    if kind == "video":
        # ★ 云端的仓库默认是**另一份**（pika 极速版），不是本机那份 canvas —— 见 `_video_wf`
        default_wf = VIDEO_CLOUD_WF
        wf = str(det.get("comfy_workflow") or "").strip() or str(default_wf)
    else:
        wf = str(det.get("comfy_workflow") or "").strip() or str(IMAGE_LOCAL_WF)
        default_wf = IMAGE_LOCAL_WF
    if not Path(wf).is_file():
        wf = str(default_wf)
    return {"url": url.rstrip("/"), "workflow": wf, "via": via}


def _project_cfg(ws) -> tuple:
    if not ws:
        return {}, ""
    p = Path(str(ws)) / "video-pipeline" / "config.local.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")), str(p)
    except Exception:  # noqa: BLE001
        return {}, str(p)


def _rh_image(ws, cfg: dict, mode: str) -> dict:
    name = str(cfg.get("active_image_provider") or "").strip()
    provs = cfg.get("image_providers") or {}
    if not name:
        return {"ok": False, "status": "config", "detail": "config.local.json 未指定 active_image_provider",
                "next": "在项目里选一条 image_providers 并写成 active_image_provider"}
    prov = provs.get(name) or {}
    if not prov:
        return {"ok": False, "status": "config", "detail": "image_providers 里没有「%s」" % name,
                "next": "检查 config.local.json 的 image_providers 段"}
    wid = str(prov.get("id_i2i") or (prov.get("i2i") or {}).get("id") or "").strip() \
        if mode == "i2i" else str(prov.get("id") or "").strip()
    nodes = prov.get("nodes") or {}
    if mode == "i2i":
        if not wid:
            return {"ok": False, "status": "config", "detail": "图生图工作流 ID 未填（id_i2i）",
                    "next": "在图生图工作流页面运行一次拿到 API 快照 ID，填到 image_providers[\"%s\"].id_i2i" % name}
        if not (nodes.get("image") or {}).get("nodeId"):
            return {"ok": False, "status": "config", "detail": "图生图缺参考图节点（nodes.image.nodeId）",
                    "next": "把工作流里「加载图像」节点的 id 填到 nodes.image.nodeId"}
        return {"ok": True, "status": "ready", "detail": "工作流 %s · 参考图节点 #%s"
                % (wid, nodes["image"]["nodeId"]), "workflow_id": wid}
    if not wid:
        return {"ok": False, "status": "config", "detail": "文生图工作流 ID 未填（id）",
                "next": "在文生图工作流页面运行一次拿到 API 快照 ID，填到 image_providers[\"%s\"].id" % name}
    if not (nodes.get("prompt") or {}).get("nodeId"):
        return {"ok": False, "status": "config", "detail": "文生图缺提示词节点（nodes.prompt.nodeId）",
                "next": "把工作流里「字符串」节点的 id 填到 nodes.prompt.nodeId"}
    return {"ok": True, "status": "ready", "detail": "工作流 %s · 提示词节点 #%s"
            % (wid, nodes["prompt"]["nodeId"]), "workflow_id": wid}


def _rh_video(cfg: dict) -> dict:
    h3 = cfg.get("h3") or {}
    nodes = h3.get("nodes") or {}
    if not h3:
        return {"ok": False, "status": "config", "detail": "config.local.json 里没有 h3（云端出片）段",
                "next": "用 video/workflow/scripts/configure.py node --target h3 写入节点映射"}
    if not str(h3.get("id") or "").strip():
        return {"ok": False, "status": "config", "detail": "云端出片工作流 ID 未填（h3.id）",
                "next": "在 H3 工作流页面运行一次拿到 API 快照 ID"}
    return {"ok": bool(nodes), "status": "ready" if nodes else "config",
            "detail": "工作流 %s · 已映射 %d 个节点" % (h3.get("id"), len(nodes)),
            "next": "" if nodes else "补 nodes 映射（prompt / length / 参考图槽位）"}


def channels(ws=None) -> dict:
    """返回所有生成通道的真实状态。只读，不产生任何费用。"""
    comfy = _comfy()
    info = _comfy_info() if comfy["online"] else {}
    cfg, cfg_path = _project_cfg(ws)

    img_wf = _local_wf(ws, "image")
    vid_wf = _local_wf(ws, "video")
    img_local_t2i = _local_wf_state(img_wf, info)
    vid_local = _local_wf_state(vid_wf, info)
    rh_t2i = _rh_image(ws, cfg, "t2i") if ws else {"ok": False, "status": "no_ws", "detail": "先选项目"}
    rh_i2i = _rh_image(ws, cfg, "i2i") if ws else {"ok": False, "status": "no_ws", "detail": "先选项目"}
    rh_vid = _rh_video(cfg) if ws else {"ok": False, "status": "no_ws", "detail": "先选项目"}

    items = [
        {"id": "image.local.t2i", "kind": "image", "engine": "local", "mode": "t2i",
         "label": "本地 ComfyUI · 文生图", "model_text": "Qwen-Image 2.1（int8 + 4step turbo）",
         "workflow": str(img_wf), "billing": "free", "cost_text": "￥0",
         "command": "assets.local",
         "detail": ("ComfyUI v%s · 空闲 %.1fG ｜ " % (comfy["version"], comfy["vram_free_gb"])
                    if comfy["online"] else comfy["reason"])
                   + (img_local_t2i["detail"] if comfy["online"] else ""),
         "status": ("ready" if img_local_t2i["ok"] and comfy["online"]
                    else ("offline" if not comfy["online"] else img_local_t2i["status"])),
         "missing": img_local_t2i.get("missing") or [],
         "next": "" if img_local_t2i["ok"] and comfy["online"] else "启动 ComfyUI 或补齐工作流/模型"},

        # ★ 2026-11-05：能力早就有了（`comfy_client --image` + `workflow_qwen21_edit.json`
        #   + `COMFYUI_NODE_LOADIMAGE`），只是 `drama assets` 批量入口没接参考图。
        #   写成「未内置工作流」会让人去重新导一份已经存在的文件 —— 那是错的方向。
        {"id": "image.local.i2i", "kind": "image", "engine": "local", "mode": "i2i",
         "label": "本地 ComfyUI · 图生图", "model_text": "Qwen-Image 2.1 edit（两个 LoadImage）",
         "workflow": str(paths.STAGES_DIR / "assets" / "comfyui" / "workflow_qwen21_edit.json"),
         "billing": "free", "cost_text": "￥0", "command": "",
         "status": "unsupported",
         "detail": "客户端已支持（comfy_client --image 参考图 + workflow_qwen21_edit.json）；"
                   "但 drama assets 批量入口尚未接 --ref，只能逐张/按 spec 出图",
         "missing": [], "next": "验证：comfy_client.py --workflow workflow_qwen21_edit.json "
                                 "--image a.png --prompt \"...\" --submit（批量入口待接）"},

        {"id": "image.rh.t2i", "kind": "image", "engine": "rh", "mode": "t2i",
         "label": "RunningHub 工作流 · 文生图", "model_text": "项目自定义工作流（nodeInfoList）",
         "workflow": "", "billing": "paid", "cost_text": "按 RH 点数（每张计费）",
         "command": "assets.rh_wf",
         "status": ("unsupported" if rh_t2i.get("status") == "no_ws"
                    else ("ready" if rh_t2i["ok"] else rh_t2i["status"])),
         "detail": rh_t2i.get("detail", ""), "missing": [],
         "next": rh_t2i.get("next") or ("先选项目" if rh_t2i.get("status") == "no_ws" else "")},

        {"id": "image.rh.i2i", "kind": "image", "engine": "rh", "mode": "i2i",
         "label": "RunningHub 工作流 · 图生图", "model_text": "项目自定义工作流（带参考图）",
         "workflow": "", "billing": "paid", "cost_text": "按 RH 点数（每张计费）",
         "command": "assets.rh_wf",
         "status": ("unsupported" if rh_i2i.get("status") == "no_ws"
                    else ("ready" if rh_i2i["ok"] else rh_i2i["status"])),
         "detail": rh_i2i.get("detail", ""), "missing": [],
         "next": rh_i2i.get("next") or ("先选项目" if rh_i2i.get("status") == "no_ws" else "")},

        {"id": "video.local.i2v", "kind": "video", "engine": "local", "mode": "i2v",
         "label": "本地 ComfyUI · 图生视频", "model_text": "MiniMax H3（fl2va w4a8 + turbo 4step LoRA）",
         "workflow": str(vid_wf), "billing": "free", "cost_text": "￥0",
         "command": "video.local",
         "detail": ("ComfyUI v%s · 空闲 %.1fG ｜ " % (comfy["version"], comfy["vram_free_gb"])
                    if comfy["online"] else comfy["reason"]) + (vid_local["detail"] if comfy["online"] else ""),
         "status": ("ready" if vid_local["ok"] and comfy["online"]
                    else ("offline" if not comfy["online"] else vid_local["status"])),
         "missing": vid_local.get("missing") or [],
         "next": "" if vid_local["ok"] and comfy["online"] else "启动 ComfyUI 或补齐工作流/模型"},

        {"id": "video.rh.workflow", "kind": "video", "engine": "rh", "mode": "i2v",
         "label": "RunningHub 工作流 · 出片（H3）", "model_text": "项目自定义 H3 工作流",
         "workflow": "", "billing": "paid", "cost_text": "按平台 usage 结算",
         "command": "shots.gen",
         "status": ("unsupported" if rh_vid.get("status") == "no_ws"
                    else ("ready" if rh_vid["ok"] else rh_vid["status"])),
         "detail": rh_vid.get("detail", ""), "missing": [],
         "next": rh_vid.get("next") or ("先选项目" if rh_vid.get("status") == "no_ws" else "")},
    ]

    # —— 云端 ComfyUI：只有解析出地址才出现（没地址 = 这条通道此刻不存在）——
    # 与本地行同构：同一个执行器、同一份工作流判据，只是地址指向实例。
    for _kind, _id, _label, _cmd in (
            # ★ 命令列必须是**云端命令**：此前写的是 assets.local / video.local，
            #   于是界面告诉你「去跑本地出图」—— 那是另一台机器，还绕过了计费确认。
            ("image", "image.cloud.t2i", "云端 ComfyUI · 文生图", "assets.cloud"),
            ("video", "video.cloud.i2v", "云端 ComfyUI · 图生视频", "video.cloud")):
        t = _cloud_target(ws, _kind)
        if not t:
            continue
        st, info = _cloud_probe(t["url"])
        if st["online"]:
            wfst = _local_wf_state(Path(t["workflow"]), info)
            detail = "ComfyUI v%s · 空闲 %.1fG ｜ %s" % (st["version"] or "?",
                                                        st["vram_free_gb"], wfst["detail"])
        else:
            wfst = {"ok": False, "status": "offline", "missing": []}
            detail = st["reason"] or "连不上"
        items.append({
            "id": _id, "kind": _kind, "engine": "cloud",
            "mode": "t2i" if _kind == "image" else "i2v",
            "label": _label, "model_text": "镜像内的 H3 / Qwen-Image（随镜像交付）",
            "workflow": t["workflow"], "billing": "paid",
            # 不写死单价：实例价由上游返回，兜底值只用于闸门。界面显示真实单价没有意义——
            # 用户要看的是「这台机器开了多久、花了多少」，那在 `cloud cost` 台账里。
            "cost_text": "按云主机时长结算",
            "command": _cmd, "detail": detail,
            "missing": wfst.get("missing") or [],
            "status": ("ready" if wfst["ok"] and st["online"] else
                       ("offline" if not st["online"] else wfst["status"])),
            "next": "" if wfst["ok"] and st["online"] else
                    ("启动实例（python -m cloud up / attach）或检查地址：%s" % t["url"]),
            "endpoint": t["url"], "endpoint_via": t["via"],
        })

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
            "model_catalog": generation_models.list_profiles(),
            "board_channel": board_channel(ws) if ws else {"choice": "", "engine": "local"},
            "ws": str(ws or ""), "config_path": cfg_path}
