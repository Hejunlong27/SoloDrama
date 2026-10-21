#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""project_setup.py —— 开工前的「前置条件确认单」（项目级唯一真源）

为什么需要它
------------
2026-10-20 / 10-21 两轮实跑的共同教训：开工前那几个决定（画风 / 集数 / 每集时长 /
生图模型 / 视频模型与功能选项 / 画面分辨率 / 是否流水线）**分散在三个文件、五条命令**里：

  * 画风   → `<ws>/style-plan.json`（`style_gate.py`）
  * 通道   → `<ws>/model-plan.json`（`model_gate.py`）
  * 集数时长 → `project.json` / `creation-brief.json`（散落）

于是「到底确认没确认」只有人记得；漏一项就一路跑到报价或出片才炸。本模块把七项收成
**一张确认单** `<ws>/project-setup.json`，并给出**单一门禁** `require()`：
七项不齐 → 退出码 4，不许开工。

七项（顺序即开工顺序）
----------------------
  1. 画风（三轨之一；**不可事后更换**）
  2. 剧集长度（集数）
  3. 每集时长（秒）
  4. 生图模型（通道 + 执行依据）
  5. 视频模型（通道 + 执行依据）与功能选项（步数 / 像素 / 声音归属 / 并发）
  6. 画面分辨率（交付 + 源像素）
  7. 流水线模式（开 / 关；开则**必须**给预算上限）

设计纪律
--------
* **不另立真源**：画风仍写 `style-plan.json`、通道仍写 `model-plan.json`；
  本文件只做「汇总 + 未齐判定」，并留一份开工快照（改了什么、何时改）。
  这样既有一张单子可查，又不会和现有门禁打架（改画风仍必须走 `style_gate`）。
* **只读兼容**：上游确认单缺字段时不崩，按「未确认」算。
* **默认不猜**：`set` 不收未知值；`require` 缺什么就报什么，并给出可照抄的命令。

命令
----
    python project_setup.py show [--json]                 看七项状态（零网络）
    python project_setup.py ask                           打印给用户的确认清单（Agent 照它问）
    python project_setup.py set --style live_action --episodes 30 --ep-seconds 60 \\
        --image-model local_comfyui --video-model runninghub --video-workflow-id <id> \\
        --resolution 1080x1920 --pipeline on --budget-coins 9000
    python project_setup.py require                       门禁（未过退出码 4）
    python project_setup.py reset [--keep-style]          清空确认单（不动画风/通道确认单）
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import style_gate as SG          # noqa: E402  画风唯一真源
import model_gate as MG          # noqa: E402  通道唯一真源

SETUP_NAME = "project-setup.json"
SETUP_VERSION = 1
EXIT_WAIT_CONFIRM = 4

EP_SECONDS_CHOICES = (60, 70, 90)
SHOTS_PER_EP_DEFAULT = {"min": 5, "max": 10}

# 视频功能选项默认值。
# ★ 依据 2026-10-20/21 实跑：4 步 turbo LoRA + 0.8MP 实测 31–34 RH币/段（旧口径 145 偏高 4–5 倍）。
VIDEO_DEFAULTS = {"steps": 4, "megapixels": 0.8, "voice": "h3", "concurrency": 2}
VOICE_CHOICES = ("h3", "external", "mute")
VOICE_NOTES = {
    "h3": "由 H3 自带音轨发声（实测语音位置由模型自决，字幕必须走 ASR 校时）",
    "external": "H3 只出画面，另配 TTS/配音（位置完全可控，需先确认 H3 可静音）",
    "mute": "音轨整体后配（画面 + 独立音效 + 配音，代价最大）",
}

RESOLUTION_DEFAULT = "1080x1920"      # 竖屏 1080P = TikTok Drama Center 下限
RESOLUTION_NOTES = {
    "1080x1920": "竖屏 1080P（≈2.07MP）：平台发布下限，源图 0.8MP 必须超分",
    "720x1280": "竖屏 720P：仅试片用，不可发布",
    "2160x3840": "竖屏 4K：可发布但超分耗时翻倍",
}

# 单段币价参考（与 megapixels 挂钩；真实消耗只认平台 usage）
COINS_PER_SHOT_BY_MP = {0.8: 34, 1.0: 40}

# 每集各环节实测耗时（分钟；2026-10-20/21 两轮实跑口径）
DEFAULT_MINUTES = {"assets": 6.0, "video_per_ep": 11.0, "post_per_ep": 4.0}


# ---------------------------------------------------------------------------
# 工作流 API 与账号 API Key（★ 2026-10-21 用户补充：这两项必须显式确认）
# ---------------------------------------------------------------------------
# 为什么必须问：
#   * **工作流 API** 决定「用哪条工作流出片」。同一个 workflowname 在平台上可以存在多份，
#     换错 workflowId = 换了一个模型/分辨率/步数，成片风格会整体漂移，而且**不会报错**。
#   * **账号 API Key** 决定「花谁的钱、出图带谁的水印」。实测事故：确认时用的是 A 账号，
#     跑的时候环境变量被改成 B 账号 —— 钱花了、产物带 B 的水印，事后极难追溯。
#     所以这里登记的不是 Key 本身，而是**可核对的指纹**：真跑之前比对，不一致就停。
WORKFLOW_KINDS = {
    "runninghub_workflow": "RunningHub 工作流（workflowId + 站点）",
    "runninghub_ai_app": "RunningHub AI 应用（应用地址 + 站点）",
    "cloud_comfyui": "云端 ComfyUI（服务地址 + 工作流 API 文件）",
    "local_comfyui": "本地 ComfyUI（工作流 API 文件，￥0，无需账号）",
    "closed_source": "闭源模型（人工出图后落盘，无 API）",
}
RH_KINDS = ("runninghub", "runninghub_workflow", "runninghub_ai_app")
COMFY_KINDS = ("local_comfyui", "cloud_comfyui")

# Key / 站点的读取来源（顺序即优先级）。**只登记来源与指纹，Key 本体永不落盘。**
KEY_ENV_NAMES = ("RUNNINGHUB_API_KEY", "RH_API_KEY")
SITE_ENV_NAMES = ("RUNNINGHUB_BASE_URL", "RH_BASE_URL")
KNOWN_SITES = ("https://www.runninghub.ai", "https://www.runninghub.cn")


# ---------------------------------------------------------------------------
# 文件读写
# ---------------------------------------------------------------------------
def _now() -> str:
    return _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def setup_path(ws: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(ws) / SETUP_NAME


# ---------------------------------------------------------------------------
# Key / 站点探测（只读；不落盘 Key 本体）
# ---------------------------------------------------------------------------
def _read_env_value(names) -> tuple:
    """按优先级读一个环境值：**进程环境变量 → HKCU\\Environment**（用户级持久变量）。

    返回 `(值, 来源描述)`；取不到返回 `('', '')`。
    ★ 为什么要读注册表：本机 Key 都配在用户级持久变量里（`setx` 写入），
      而当前进程不一定继承得到 —— 只读 `os.environ` 会误判成「没配 Key」。
    """
    import os
    for n in names:
        v = (os.environ.get(n) or "").strip()
        if v:
            return v, "进程环境变量 %s" % n
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                for n in names:
                    try:
                        v, _ = winreg.QueryValueEx(k, n)
                    except OSError:
                        continue
                    v = str(v or "").strip()
                    if v:
                        return v, "HKCU\\Environment:%s" % n
        except OSError:
            pass
    return "", ""


def _key_fingerprint(key: str) -> str:
    """Key 指纹：`sha256 前 8 位 + 后 4 位`。**足以核对、不足以复原**。"""
    import hashlib
    k = (key or "").strip()
    if not k:
        return ""
    return "%s…%s" % (hashlib.sha256(k.encode("utf-8")).hexdigest()[:8], k[-4:])


def live_key() -> dict:
    """当前环境里的 RunningHub Key 与站点（只读）。→ {key, source, fingerprint, site}"""
    key, src = _read_env_value(KEY_ENV_NAMES)
    site, _ = _read_env_value(SITE_ENV_NAMES)
    return {"key": key, "source": src, "fingerprint": _key_fingerprint(key),
            "site": site.strip().rstrip("/")}


def _channels(image: dict, video: dict) -> list:
    return [c for c in ((image or {}).get("choice"), (video or {}).get("choice")) if c]


def _workflow_api_state(image: dict, video: dict, wa: dict) -> dict:
    """第 8 项：工作流 API（用哪条工作流 / 哪个服务地址）。

    * 两条通道都是「闭源人工落盘」→ 无需（不算缺项）；
    * 有 RunningHub 通道 → 必须给 `workflowId`（或应用地址）+ 站点；
    * 有云端 ComfyUI → 必须给服务地址 + 工作流 API 文件。
    """
    chans = _channels(image, video)
    rh = [c for c in chans if c in RH_KINDS]
    comfy = [c for c in chans if c in COMFY_KINDS]
    if not rh and not comfy:
        return {"ok": True, "required": False, "kind": None, "ref": None, "site": None,
                "missing": [], "note": "通道均为闭源人工落盘，不调 API"}
    # 纯本地 ComfyUI：服务地址默认 127.0.0.1:8188、工作流缺省用仓库内置 Qwen-Image 2.1
    #   → 不强制确认（换工作流是可选优化，不是开工前提）
    if not rh and all(c == "local_comfyui" for c in comfy):
        return {"ok": True, "required": False, "kind": "local_comfyui",
                "ref": (wa or {}).get("comfy_workflow") or "仓库内置 Qwen-Image 2.1",
                "site": None, "missing": [],
                "note": "本地 ComfyUI：服务地址 127.0.0.1:8188，工作流缺省用仓库内置"}
    kind = (wa or {}).get("kind")
    missing = []
    if rh:
        want = rh[0]
        if kind not in RH_KINDS:
            missing.append("未指定工作流 API（--workflow-api %s）" % want)
        if want == "runninghub_ai_app":
            if not (wa or {}).get("app_url"):
                missing.append("缺应用地址（--app-url）")
        elif not (wa or {}).get("workflow_id"):
            missing.append("缺工作流 ID（--workflow-id）")
        if not (wa or {}).get("site"):
            missing.append("缺站点（--site，须为 %s 之一）" % " / ".join(KNOWN_SITES))
    elif comfy:
        if kind != "cloud_comfyui":
            missing.append("未指定云端 ComfyUI（--workflow-api cloud_comfyui）")
        if not (wa or {}).get("comfy_url"):
            missing.append("缺服务地址（--comfy-url）")
        if not (wa or {}).get("comfy_workflow"):
            missing.append("缺工作流 API 文件（--comfy-workflow）")
    ref = ((wa or {}).get("workflow_id") or (wa or {}).get("app_url")
           or (wa or {}).get("comfy_url") or None)
    return {"ok": not missing, "required": True, "kind": kind, "ref": ref,
            "site": (wa or {}).get("site"), "missing": missing, "note": ""}


def _account_state(image: dict, video: dict, acct: dict) -> dict:
    """第 9 项：账号 API Key（花谁的额度）。登记指纹，**真跑前比对**。"""
    chans = _channels(image, video)
    rh = [c for c in chans if c in RH_KINDS]
    if not rh:
        return {"ok": True, "required": False, "alias": None, "fingerprint": None,
                "source": None, "site": None, "missing": [],
                "note": "无云端计费通道，不花任何账号额度"}
    acct = acct or {}
    missing = []
    if not acct.get("alias"):
        missing.append("未指定账号（--account <别名>）")
    if not acct.get("key_fingerprint"):
        missing.append("未读到 API Key（%s）" % " / ".join(KEY_ENV_NAMES))
    if not acct.get("site"):
        missing.append("缺站点（--site）")
    drift = ""
    live = live_key()
    if live["fingerprint"] and acct.get("key_fingerprint") \
            and live["fingerprint"] != acct["key_fingerprint"]:
        drift = ("当前环境 Key（%s）与确认的账号（%s：%s）不一致 —— 会花错账号的钱"
                 % (live["fingerprint"], acct.get("alias"), acct["key_fingerprint"]))
        missing.append(drift)
    return {"ok": not missing, "required": True, "alias": acct.get("alias"),
            "fingerprint": acct.get("key_fingerprint"), "source": acct.get("key_source"),
            "site": acct.get("site"), "live_fingerprint": live["fingerprint"],
            "drift": drift, "missing": missing, "note": ""}


def _blank() -> dict:
    return {
        "setup_version": SETUP_VERSION,
        "created_at": None,
        "updated_at": None,
        "episodes": {"count": None, "seconds": None,
                     "shots_min": SHOTS_PER_EP_DEFAULT["min"],
                     "shots_max": SHOTS_PER_EP_DEFAULT["max"]},
        "resolution": {"deliver": None,
                       "source_megapixels": VIDEO_DEFAULTS["megapixels"]},
        "video_options": dict(VIDEO_DEFAULTS),
        # ★ 2026-10-21：工作流 API 与账号 Key（只登记"用哪个"，Key 本体永不落盘）
        "workflow_api": {"kind": None, "workflow_id": None, "app_url": None,
                         "comfy_url": None, "comfy_workflow": None,
                         "site": None, "confirmed": None},
        "account": {"alias": None, "key_source": None, "key_fingerprint": None,
                    "site": None, "confirmed": None},
        "pipeline": {"enabled": None, "budget_cap_coins": None,
                     "budget_cap_cny": None, "eta_minutes": None},
        "history": [],
    }


def load(ws: pathlib.Path) -> dict:
    """读确认单；缺文件/坏文件一律返回空单（不抛异常，由 require 判未齐）。"""
    p = setup_path(ws)
    d = _blank()
    if p.is_file():
        try:
            raw = json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError, ValueError):
            raw = None
        if isinstance(raw, dict):
            for k, v in raw.items():
                if k in ("episodes", "resolution", "video_options", "pipeline",
                         "workflow_api", "account") and isinstance(v, dict):
                    d[k].update(v)
                elif k == "history" and isinstance(v, list):
                    d[k] = v
                elif k in ("created_at", "updated_at", "setup_version"):
                    d[k] = v
    return d


def save(ws: pathlib.Path, d: dict) -> pathlib.Path:
    d["updated_at"] = _now()
    if not d.get("created_at"):
        d["created_at"] = d["updated_at"]
    p = setup_path(ws)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8", newline="")
    return p


def _note(d: dict, field: str, before, after) -> None:
    if before == after:
        return
    d.setdefault("history", []).append(
        {"at": _now(), "field": field, "from": before, "to": after})


# ---------------------------------------------------------------------------
# 七项状态汇总
# ---------------------------------------------------------------------------
def _model_state(ws: pathlib.Path, kind: str) -> dict:
    """读 model-plan.json（不写），返回 {ok, choice, label, engine_arg, missing[]}。"""
    try:
        plan = MG.load_plan(pathlib.Path(ws))
    except Exception:                                            # noqa: BLE001
        plan = {}
    m = ((plan or {}).get("models") or {}).get(kind) or {}
    if not (m.get("confirmed") and m.get("choice")):
        return {"ok": False, "choice": None, "label": None,
                "engine_arg": None, "missing": ["未确认"], "manual": False}
    choice = str(m["choice"])
    detail = m.get("detail") or {}
    try:
        miss = MG.missing_evidence(kind, choice, detail)
    except Exception:                                            # noqa: BLE001
        miss = m.get("missing_evidence") or []
    opt = MG._find_option(kind, choice) or {}                    # noqa: SLF001
    return {"ok": not miss, "choice": choice, "label": m.get("label") or opt.get("label"),
            "engine_arg": m.get("engine_arg") or opt.get("engine_arg"),
            "missing": list(miss), "manual": bool(opt.get("manual")),
            "detail": dict(detail)}


def _style_state(ws: pathlib.Path) -> dict:
    try:
        st = SG.gate_state(pathlib.Path(ws))
    except Exception:                                            # noqa: BLE001
        st = {"confirmed": False, "choice": None, "sub_mode": None}
    if not st.get("confirmed"):
        return {"ok": False, "choice": None, "sub_mode": None}
    try:
        label = (SG.STYLES.get(st["choice"]) or {}).get("label")
    except Exception:                                            # noqa: BLE001
        label = None
    return {"ok": True, "choice": st["choice"], "sub_mode": st.get("sub_mode"), "label": label}


def _parse_resolution(s: str) -> tuple:
    txt = str(s or "").lower().replace("*", "x").replace("×", "x").strip()
    if "x" not in txt:
        raise ValueError("分辨率要写成 WxH（例 1080x1920），收到：%r" % s)
    w, h = txt.split("x", 1)
    return int(w), int(h)


def collect(ws: pathlib.Path) -> dict:
    """九项状态 + 派生值（每集镜数 / 单段币价 / 预算建议 / ETA）。"""
    ws = pathlib.Path(ws)
    d = load(ws)
    style = _style_state(ws)
    image = _model_state(ws, "image")
    video = _model_state(ws, "video")

    # 工作流 API：优先用 setup 里显式确认的；没有则从模型确认单的「执行依据」推断
    # （用户已经在 `models set --workflow-id` 里给过，不该让他再抄一遍；但站点与类型仍要能核对）
    wa_eff = dict(d.get("workflow_api") or {})
    if not wa_eff.get("kind"):
        for m in (video, image):
            det = (m or {}).get("detail") or {}
            if det.get("workflow_id"):
                wa_eff.update({"kind": m.get("choice"), "workflow_id": det["workflow_id"]})
                break
            if det.get("app_url"):
                wa_eff.update({"kind": m.get("choice"), "app_url": det["app_url"]})
                break
            if det.get("comfy_url"):
                wa_eff.update({"kind": m.get("choice"), "comfy_url": det["comfy_url"],
                               "comfy_workflow": det.get("comfy_workflow")})
                break
    if not wa_eff.get("site"):
        _site, _ = _read_env_value(SITE_ENV_NAMES)
        if _site:
            wa_eff["site"] = _site.strip().rstrip("/")

    ep = d.get("episodes") or {}
    eps_ok = bool(ep.get("count") and ep.get("seconds") and
                  int(ep.get("seconds")) in EP_SECONDS_CHOICES)
    res = d.get("resolution") or {}
    res_ok = False
    res_val = None
    if res.get("deliver"):
        try:
            w, h = _parse_resolution(res["deliver"])
            res_val = [w, h]
            res_ok = w > 0 and h > 0
        except (ValueError, TypeError):
            res_ok = False

    vo = d.get("video_options") or {}
    vo_ok = (str(vo.get("voice")) in VOICE_CHOICES
             and int(vo.get("steps") or 0) > 0
             and float(vo.get("megapixels") or 0) > 0
             and int(vo.get("concurrency") or 0) >= 1)
    pipe = d.get("pipeline") or {}
    pipe_ok = pipe.get("enabled") is not None
    if pipe.get("enabled") and not (pipe.get("budget_cap_coins") or 0) > 0:
        pipe_ok = False

    mp = float(vo.get("megapixels") or VIDEO_DEFAULTS["megapixels"])
    coins_per_shot = COINS_PER_SHOT_BY_MP.get(round(mp, 1), 34)
    shots_avg = (int(ep.get("shots_min") or 5) + int(ep.get("shots_max") or 10)) / 2.0
    count = int(ep.get("count") or 0)
    est_coins = round(count * shots_avg * coins_per_shot) if count else None
    est_minutes = (round(DEFAULT_MINUTES["assets"] + count *
                         (DEFAULT_MINUTES["video_per_ep"] + DEFAULT_MINUTES["post_per_ep"]))
                   if count else None)

    items = {
        "style": {"ok": style["ok"], "value": style.get("choice"),
                  "label": style.get("label"), "sub_mode": style.get("sub_mode")},
        "episodes": {"ok": eps_ok, "count": ep.get("count"), "seconds": ep.get("seconds"),
                     "shots_min": ep.get("shots_min"), "shots_max": ep.get("shots_max")},
        "image_model": image,
        "video_model": video,
        "workflow_api": _workflow_api_state(image, video, wa_eff),
        "account": _account_state(image, video, d.get("account") or {}),
        "resolution": {"ok": res_ok, "deliver": res.get("deliver"), "parsed": res_val,
                       "source_megapixels": mp},
        "video_options": {"ok": vo_ok, **{k: vo.get(k) for k in
                                          ("steps", "megapixels", "voice", "concurrency")}},
        "pipeline": {"ok": pipe_ok, "enabled": pipe.get("enabled"),
                     "budget_cap_coins": pipe.get("budget_cap_coins"),
                     "budget_cap_cny": pipe.get("budget_cap_cny"),
                     "eta_minutes": pipe.get("eta_minutes")},
    }
    missing = [k for k, v in items.items() if not v["ok"]]
    return {
        "items": items,
        "missing": missing,
        "ok": not missing,
        "derived": {"coins_per_shot": coins_per_shot, "shots_avg": shots_avg,
                    "est_total_coins": est_coins,
                    "est_cny": round(est_coins * 0.0025, 2) if est_coins else None,
                    "est_minutes": est_minutes,
                    "est_hours": round(est_minutes / 60.0, 1) if est_minutes else None},
    }


# 缺项 → 可照抄的修法
FIX_HINTS = {
    "style": 'drama.py style set 3d_manhua|2d_animation|live_action [--sub-mode ...]',
    "episodes": 'drama.py setup set --episodes 30 --ep-seconds 60',
    "image_model": 'drama.py models set image=local_comfyui（或 runninghub / closed_source）',
    "video_model": 'drama.py models set video=runninghub --workflow-id <id>',
    "workflow_api": ('drama.py setup set --workflow-api runninghub_workflow '
                     '--workflow-id <id> --site https://www.runninghub.ai'),
    "account": 'drama.py setup set --account "账号别名"（用当前环境 Key 登记指纹）',
    "resolution": 'drama.py setup set --resolution 1080x1920',
    "video_options": 'drama.py setup set --steps 4 --megapixels 0.8 --voice h3 --concurrency 2',
    "pipeline": 'drama.py setup set --pipeline on --budget-coins 9000（或 --pipeline off）',
}
ITEM_LABELS = {
    "style": "画风", "episodes": "剧集长度与每集时长", "image_model": "生图模型",
    "video_model": "视频模型", "workflow_api": "工作流 API",
    "account": "账号 API Key", "resolution": "画面分辨率",
    "video_options": "视频功能选项", "pipeline": "流水线模式",
}


def require(ws: pathlib.Path) -> tuple:
    """门禁：九项全齐 → (True, 摘要)；否则 (False, 缺失清单文本)。"""
    st = collect(ws)
    total = len(st["items"])
    if st["ok"]:
        it = st["items"]
        return True, ("前置条件 %d/%d 已确认：%s｜%d 集 × %d 秒｜生图=%s｜视频=%s｜"
                      "工作流=%s｜账号=%s｜%s｜流水线=%s"
                      % (total, total, it["style"]["value"], int(it["episodes"]["count"]),
                         int(it["episodes"]["seconds"]), it["image_model"]["choice"],
                         it["video_model"]["choice"],
                         (it["workflow_api"].get("ref") or "无需"),
                         (it["account"].get("alias") or "无需"),
                         it["resolution"]["deliver"],
                         "开" if it["pipeline"]["enabled"] else "关"))
    lines = ["前置条件未齐（%d/%d）：" % (total - len(st["missing"]), total)]
    for k in st["missing"]:
        detail = st["items"][k]
        extra = ""
        if k in ("image_model", "video_model", "workflow_api", "account") \
                and detail.get("missing"):
            extra = "（%s）" % "；".join(str(x) for x in detail["missing"])
        lines.append("  - %s%s → %s" % (ITEM_LABELS.get(k, k), extra, FIX_HINTS.get(k, "")))
    return False, "\n".join(lines)


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------
def render(st: dict) -> str:
    it, dv = st["items"], st["derived"]
    n = len(it)
    L = ["=" * 72, "开工前置条件（%d 项）" % n, "=" * 72]
    mark = lambda ok: "[OK]  " if ok else "[ 缺] "                     # noqa: E731

    s = it["style"]
    L.append("%s1 画风        : %s%s" % (mark(s["ok"]), s.get("value") or "未确认",
                                         "（%s）" % s["label"] if s.get("label") else ""))
    e = it["episodes"]
    L.append("%s2 集数        : %s" % (mark(e["ok"]), ("%s 集" % e["count"]) if e["ok"] else "未确认"))
    L.append("%s3 每集时长    : %s" % (mark(e["ok"]),
                                       ("%s 秒（每集 %s–%s 镜）"
                                        % (e["seconds"], e["shots_min"], e["shots_max"]))
                                       if e["ok"] else "未确认（只支持 60 / 70 / 90 秒档）"))
    im, vm = it["image_model"], it["video_model"]
    L.append("%s4 生图模型    : %s" % (mark(im["ok"]),
                                       ("%s（%s）" % (im["choice"], im.get("label")))
                                       if im["ok"] else ("未确认" if not im["choice"]
                                                         else "执行依据不全：%s" % "、".join(map(str, im["missing"])))))
    L.append("%s5 视频模型    : %s" % (mark(vm["ok"]),
                                       ("%s（%s）" % (vm["choice"], vm.get("label")))
                                       if vm["ok"] else ("未确认" if not vm["choice"]
                                                         else "执行依据不全：%s" % "、".join(map(str, vm["missing"])))))
    vo = it["video_options"]
    L.append("       功能选项    : %s 步 / %s MP / 声音=%s / 并发 %s%s"
             % (vo.get("steps"), vo.get("megapixels"), vo.get("voice"), vo.get("concurrency"),
                "" if vo["ok"] else "   ← 非法"))

    wa = it["workflow_api"]
    if not wa.get("required"):
        wa_txt = "无需 —— %s%s" % (wa.get("note", ""),
                                  "（%s）" % wa.get("ref") if wa.get("ref") else "")
    elif wa["ok"]:
        wa_txt = "%s｜%s%s" % (wa.get("kind"), wa.get("ref"),
                              "｜%s" % wa.get("site") if wa.get("site") else "")
    else:
        wa_txt = "未确认：" + "；".join(map(str, wa["missing"]))
    L.append("%s6 工作流 API  : %s" % (mark(wa["ok"]), wa_txt))

    ac = it["account"]
    if not ac.get("required"):
        ac_txt = "无需 —— %s" % ac.get("note", "")
    elif ac["ok"]:
        ac_txt = "%s｜%s｜%s" % (ac.get("alias"), ac.get("fingerprint"), ac.get("source"))
    elif ac.get("drift"):
        ac_txt = "★ 账号漂移：%s" % ac["drift"]
    else:
        ac_txt = "未确认：" + "；".join(map(str, ac["missing"]))
    L.append("%s7 账号 API Key: %s" % (mark(ac["ok"]), ac_txt))

    r = it["resolution"]
    L.append("%s8 画面分辨率  : %s%s" % (mark(r["ok"]), r.get("deliver") or "未确认",
                                         "（源 %.2f MP）" % r["source_megapixels"]
                                         if r.get("deliver") else ""))
    p = it["pipeline"]
    L.append("%s9 流水线模式  : %s" % (mark(p["ok"]),
                                       ("开（预算上限 %s RH币 ≈ ￥%s）"
                                        % (p.get("budget_cap_coins"), p.get("budget_cap_cny")))
                                       if p.get("enabled") else
                                       ("关" if p.get("enabled") is False else "未确认")))
    L.append("-" * 72)
    if dv.get("est_total_coins"):
        L.append("参考预算    : 单段 %s RH币 × 每集约 %.1f 段 × %d 集 ≈ %s RH币 ≈ ￥%s"
                 % (dv["coins_per_shot"], dv["shots_avg"], int(e["count"] or 0),
                    dv["est_total_coins"], dv["est_cny"]))
    if dv.get("est_minutes"):
        L.append("参考工期    : 约 %s 小时（资产 %.1f 分 + 每集 %.1f 分 × %d 集）"
                 % (dv["est_hours"], DEFAULT_MINUTES["assets"],
                    DEFAULT_MINUTES["video_per_ep"] + DEFAULT_MINUTES["post_per_ep"],
                    int(e["count"] or 0)))
    L.append("门禁        : %s" % ("全部就绪，可开工" if st["ok"]
                                   else "未就绪（退出码 %d），缺：%s"
                                   % (EXIT_WAIT_CONFIRM, "、".join(ITEM_LABELS[k] for k in st["missing"]))))
    return "\n".join(L)


def render_ask(ws: pathlib.Path) -> str:
    st = collect(ws)
    live = live_key()
    L = ["=" * 72, "开工前需要你拍板 9 件事（其余我按默认值走，不反复问）", "=" * 72, ""]
    L.append("1. 画风（不可事后更换，改 = 已出素材作废）")
    L.append("   3d_manhua（3D 漫剧）/ 2d_animation（2D 动画）/ live_action（真人写实）")
    L.append("2. 剧集长度：集数（默认 30）")
    L.append("3. 每集时长：60 / 70 / 90 秒（默认 60，成片口径 60–80 秒）")
    L.append("4. 生图模型：local_comfyui（￥0）/ runninghub（★计费）/ closed_source（人工落盘）")
    L.append("5. 视频模型：runninghub（★计费）/ closed_source（人工落盘）")
    L.append("   功能选项：步数 %s / 像素 %s MP / 声音归属 %s / 并发 %s"
             % (VIDEO_DEFAULTS["steps"], VIDEO_DEFAULTS["megapixels"],
                VIDEO_DEFAULTS["voice"], VIDEO_DEFAULTS["concurrency"]))
    L.append("   声音归属：h3=模型自带音轨（字幕须 ASR 校时）/ external=另配 TTS / mute=全后配")
    L.append("6. **用哪条工作流 API**（走 RunningHub 时必须明确）")
    L.append("   工作流 ID（workflowId）/ AI 应用地址（appUrl）/ 云端 ComfyUI 服务地址 + 工作流文件，")
    L.append("   并指明站点：%s" % " 或 ".join(KNOWN_SITES))
    L.append("   ⚠ 同名工作流在平台上可能有多份，选错 = 换模型/换步数，成片风格整体漂移且不报错。")
    L.append("7. **用哪个账号的 API Key**（花谁的额度、带谁的水印）")
    L.append("   请给我一个**账号别名**（例：主账号 A / 小号 B），我用当前环境里的 Key 算指纹登记：")
    if live["fingerprint"]:
        L.append("   当前检测到：%s（来源 %s，站点 %s）—— 是不是这一把？"
                 % (live["fingerprint"], live["source"], live["site"] or "未设 RUNNINGHUB_BASE_URL"))
    else:
        L.append("   ★ 当前**没检测到** RUNNINGHUB_API_KEY（进程环境与 HKCU\\Environment 都没有）")
    L.append("   ⚠ 换 Key 后确认单会失效：真跑前会比对指纹，不一致直接停（防止花错账号的钱）。")
    L.append("8. 画面分辨率：%s（平台下限，源 0.8MP 必须超分）" % RESOLUTION_DEFAULT)
    L.append("9. 是否开启流水线模式：开 → 必须同时给**预算上限**；确认后不再逐步问你")
    L.append("")
    L.append("-" * 72)
    L.append(render(st))
    L.append("-" * 72)
    L.append("用户答完后一次性写单：")
    L.append("  drama.py setup set --style live_action --episodes 30 --ep-seconds 60 \\")
    L.append("      --image-model local_comfyui --video-model runninghub \\")
    L.append("      --workflow-api runninghub_workflow --workflow-id <id> \\")
    L.append("      --site https://www.runninghub.ai --account \"主账号 A\" \\")
    L.append("      --resolution 1080x1920 --pipeline on --budget-coins 9000")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# 命令
# ---------------------------------------------------------------------------
def cmd_show(a) -> int:
    ws = _resolve_ws(a.workspace)
    st = collect(ws)
    if a.json:
        print(json.dumps(st, ensure_ascii=False, indent=2))
    else:
        print(render(st))
    return 0


def cmd_ask(a) -> int:
    print(render_ask(_resolve_ws(a.workspace)))
    return 0


def cmd_require(a) -> int:
    ws = _resolve_ws(a.workspace)
    ok, msg = require(ws)
    st = collect(ws)
    if a.json:
        print(json.dumps({"ok": ok, "missing": st["missing"],
                          "items": {k: v.get("ok") for k, v in st["items"].items()}},
                         ensure_ascii=False, indent=2))
    else:
        print(("[OK] " if ok else "[BLOCK] ") + msg)
    return 0 if ok else EXIT_WAIT_CONFIRM


def cmd_set(a) -> int:
    ws = _resolve_ws(a.workspace)
    rc, msgs = apply_set(ws, a)
    for m in msgs:
        print(m)
    return rc


def apply_set(ws: pathlib.Path, a) -> tuple:
    """把 argparse 命名空间里的显式参数写进确认单（供测试复用）。"""
    ws = pathlib.Path(ws)
    d = load(ws)
    msgs = []
    rc = 0

    # ① 画风：转发给 style_gate（唯一真源）
    if getattr(a, "style", None):
        before = _style_state(ws).get("choice")
        _quiet = _capture()
        with _quiet:
            r = SG._do_set(ws, a.style, getattr(a, "sub_mode", None), source="setup")  # noqa: SLF001
        if r:
            msgs.append("[FAIL] 画风写入失败（退出码 %s）：%s" % (r, _quiet.text.strip()))
            return r, msgs
        _note(d, "style", before, a.style)
        msgs.append("[OK] 画风 = %s" % a.style)

    # ② 集数 / 每集时长
    if getattr(a, "episodes", None) is not None:
        n = int(a.episodes)
        if n < 1:
            msgs.append("[FAIL] 集数必须 ≥1")
            return 2, msgs
        _note(d, "episodes.count", d["episodes"].get("count"), n)
        d["episodes"]["count"] = n
    if getattr(a, "ep_seconds", None) is not None:
        s = int(a.ep_seconds)
        if s not in EP_SECONDS_CHOICES:
            msgs.append("[FAIL] 每集时长只支持 %s 秒档（收到 %s）"
                        % ("/".join(map(str, EP_SECONDS_CHOICES)), s))
            return 2, msgs
        _note(d, "episodes.seconds", d["episodes"].get("seconds"), s)
        d["episodes"]["seconds"] = s

    # ③ 生图 / 视频模型：转发给 model_gate（唯一真源）
    for kind, flag, detail_flags in (
        ("image", "image_model", {"comfy_url": "image_comfy_url",
                                  "comfy_workflow": "image_workflow",
                                  "app_url": "image_app_url",
                                  "app_id": "image_app_id"}),
        ("video", "video_model", {"comfy_url": "video_comfy_url",
                                  "comfy_workflow": "video_workflow",
                                  "app_url": "video_app_url",
                                  "app_id": "video_app_id",
                                  "workflow_id": "video_workflow_id"}),
    ):
        choice = getattr(a, flag, None)
        if not choice:
            continue
        detail = {}
        for mkey, akey in detail_flags.items():
            v = getattr(a, akey, None)
            if v:
                detail[mkey] = v
        # ★ 2026-10-21：`--workflow-id` / `--app-url` / `--comfy-*` 是「工作流 API」的通用写法，
        #   同时也要回填到 model-plan 的执行依据里 —— 否则用户要抄两遍，且两处可能抄成不同的值。
        for mkey, akey in (("workflow_id", "workflow_id"), ("app_url", "app_url"),
                           ("comfy_url", "comfy_url"), ("comfy_workflow", "comfy_workflow")):
            if not detail.get(mkey) and getattr(a, akey, None):
                detail[mkey] = getattr(a, akey)
        _quiet = _capture()
        with _quiet:
            r = MG._do_set(ws, kind, choice, detail, source="setup")   # noqa: SLF001
        tag = "[OK] " if r == 0 else ("[BLOCK] " if r == EXIT_WAIT_CONFIRM else "[FAIL] ")
        msgs.append("%s%s模型 = %s" % (tag, {"image": "生图", "video": "视频"}[kind], choice))
        if r == EXIT_WAIT_CONFIRM:
            tail = _quiet.text.strip().splitlines()
            for ln in tail[-6:]:
                msgs.append("      " + ln.strip())
            rc = EXIT_WAIT_CONFIRM
        elif r:
            return r, msgs

    # ④ 分辨率
    if getattr(a, "resolution", None):
        try:
            w, h = _parse_resolution(a.resolution)
        except ValueError as e:
            msgs.append("[FAIL] %s" % e)
            return 2, msgs
        _note(d, "resolution.deliver", d["resolution"].get("deliver"), "%dx%d" % (w, h))
        d["resolution"]["deliver"] = "%dx%d" % (w, h)

    # ⑤ 视频功能选项
    for key, flag, cast in (("steps", "steps", int), ("megapixels", "megapixels", float),
                            ("concurrency", "concurrency", int), ("voice", "voice", str)):
        v = getattr(a, flag, None)
        if v is None:
            continue
        if key == "voice" and v not in VOICE_CHOICES:
            msgs.append("[FAIL] 声音归属只支持 %s（收到 %s）" % ("/".join(VOICE_CHOICES), v))
            return 2, msgs
        v = cast(v)
        if key == "megapixels" and v <= 0:
            msgs.append("[FAIL] megapixels 必须 >0")
            return 2, msgs
        _note(d, "video_options.%s" % key, d["video_options"].get(key), v)
        d["video_options"][key] = v
    if getattr(a, "megapixels", None) is not None:
        d["resolution"]["source_megapixels"] = float(a.megapixels)

    # ⑥ 工作流 API（用哪条工作流 / 哪个服务地址）
    wa = d["workflow_api"]
    if getattr(a, "workflow_api", None):
        kind = str(a.workflow_api).strip()
        if kind not in WORKFLOW_KINDS:
            msgs.append("[FAIL] 未知工作流 API 类型：%s（可选 %s）"
                        % (kind, " / ".join(WORKFLOW_KINDS)))
            return 2, msgs
        _note(d, "workflow_api.kind", wa.get("kind"), kind)
        wa["kind"] = kind
    for key, flag in (("workflow_id", "workflow_id"), ("app_url", "app_url"),
                      ("comfy_url", "comfy_url"), ("comfy_workflow", "comfy_workflow"),
                      ("site", "site")):
        v = getattr(a, flag, None)
        if not v:
            continue
        v = str(v).strip()
        if key == "site":
            v = v.rstrip("/")
            if v not in KNOWN_SITES:
                msgs.append("[FAIL] 站点只支持 %s（收到 %s）—— 站点错会导致上传报「API Key 不存在」"
                            % (" / ".join(KNOWN_SITES), v))
                return 2, msgs
        if key == "comfy_workflow":
            p = pathlib.Path(v).expanduser()
            p = p if p.is_absolute() else (ws / p)
            if not p.is_file():
                msgs.append("[WARN] 工作流 API 文件不存在：%s（先核对路径）" % p)
            v = str(p)
        _note(d, "workflow_api.%s" % key, wa.get(key), v)
        wa[key] = v
    if wa.get("kind") or any(wa.get(k) for k in ("workflow_id", "app_url", "comfy_url")):
        wa["confirmed"] = True
        wa["confirmed_at"] = _now()
        if not wa.get("site"):
            _s, _ = _read_env_value(SITE_ENV_NAMES)
            if _s:
                wa["site"] = _s.strip().rstrip("/")

    # ⑦ 账号 API Key（只登记「用哪个账号」+ 指纹，Key 本体永不落盘）
    ac = d["account"]
    if getattr(a, "account", None) or getattr(a, "account_source", None):
        alias = str(getattr(a, "account", None) or "").strip() or "未命名账号"
        src_flag = getattr(a, "account_source", None)
        names = (src_flag,) if src_flag else KEY_ENV_NAMES
        key, src = _read_env_value(names)
        if not key:
            msgs.append("[BLOCK] 没读到 API Key（来源：%s）。请先配好用户级持久变量，"
                        "或用 --account-source <变量名> 指定" % " / ".join(names))
            return EXIT_WAIT_CONFIRM, msgs
        fp = _key_fingerprint(key)
        site, _ = _read_env_value(SITE_ENV_NAMES)
        _note(d, "account.alias", ac.get("alias"), alias)
        _note(d, "account.key_fingerprint", ac.get("key_fingerprint"), fp)
        ac.update({"alias": alias, "key_source": src, "key_fingerprint": fp,
                   "site": (site.strip().rstrip("/") or wa.get("site")),
                   "confirmed": True, "confirmed_at": _now()})
        msgs.append("[OK] 账号 = %s（指纹 %s，来源 %s）" % (alias, fp, src))

    # ⑧ 流水线模式 + 预算
    if getattr(a, "pipeline", None):
        on = str(a.pipeline).lower() in ("on", "1", "true", "yes", "开")
        _note(d, "pipeline.enabled", d["pipeline"].get("enabled"), on)
        d["pipeline"]["enabled"] = on
    if getattr(a, "budget_coins", None) is not None:
        coins = int(a.budget_coins)
        if coins <= 0:
            msgs.append("[FAIL] 预算上限必须 >0 RH币")
            return 2, msgs
        _note(d, "pipeline.budget_cap_coins", d["pipeline"].get("budget_cap_coins"), coins)
        d["pipeline"]["budget_cap_coins"] = coins
        d["pipeline"]["budget_cap_cny"] = round(coins * 0.0025, 2)

    st = collect(ws)
    # 预算/ETA 回填（供流水线一次跑完前预告）
    if d["episodes"].get("count"):
        d["pipeline"]["eta_minutes"] = st["derived"]["est_minutes"]
        if d["pipeline"].get("budget_cap_coins") is None and d["pipeline"].get("enabled"):
            d["pipeline"]["budget_cap_coins"] = st["derived"]["est_total_coins"]
            d["pipeline"]["budget_cap_cny"] = st["derived"]["est_cny"]

    p = save(ws, d)
    st = collect(ws)
    msgs.append("[写到] %s" % p)
    if st["ok"]:
        msgs.append("[OK] 前置条件 %d/%d 已就绪，可以开工"
                    % (len(st["items"]), len(st["items"])))
    else:
        msgs.append("[BLOCK] 还缺：%s（退出码 %d）"
                    % ("、".join(ITEM_LABELS[k] for k in st["missing"]), EXIT_WAIT_CONFIRM))
        if rc == 0:
            rc = EXIT_WAIT_CONFIRM
    return rc, msgs


def _key_entries(ws: pathlib.Path) -> list:
    """可选的账号清单：`<ws>/keys.json`（`{"keys":[{account,site,tier,env}]}` 或顶层数组）。

    只写**环境变量名**，Key 本体不进清单、不进确认单、不进任何日志。
    """
    kp = pathlib.Path(ws) / "keys.json"
    if not kp.is_file():
        return []
    try:
        raw = json.loads(kp.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, ValueError):
        return []
    items = raw.get("keys") if isinstance(raw, dict) else raw
    return [e for e in (items or []) if isinstance(e, dict)]


def cmd_accounts(a) -> int:
    """列出「这台机器上能用的账号」+ 当前确认的是哪一个（只显示指纹）。"""
    ws = _resolve_ws(a.workspace)
    d = load(ws)
    ac = d.get("account") or {}
    live = live_key()

    rows = []
    if live["fingerprint"]:
        rows.append({"account": "（默认环境变量）", "env": ", ".join(KEY_ENV_NAMES),
                     "site": live["site"], "tier": "", "fingerprint": live["fingerprint"],
                     "usable": True, "origin": "环境变量"})
    for e in _key_entries(ws):
        env = str(e.get("env") or "").strip()
        key, _src = _read_env_value((env,)) if env else ("", "")
        rows.append({"account": str(e.get("account") or "（未命名）"), "env": env or "（未指定 env）",
                     "site": str(e.get("site") or ""), "tier": str(e.get("tier") or ""),
                     "fingerprint": _key_fingerprint(key) if key else "（未设）",
                     "usable": bool(key), "origin": "keys.json"})

    if a.json:
        print(json.dumps({"confirmed": ac, "candidates": rows,
                          "live": {"fingerprint": live["fingerprint"], "site": live["site"]}},
                         ensure_ascii=False, indent=2))
        return 0

    L = ["=" * 72, "可用账号（只显示指纹，Key 本体不落盘）", "=" * 72]
    if not rows:
        L.append("★ 没有探测到任何 API Key：")
        L.append("  进程环境变量与 HKCU\\Environment 都没有 %s" % " / ".join(KEY_ENV_NAMES))
        L.append("  配法（PowerShell，用户级持久变量，新开终端生效）：")
        L.append("    setx RUNNINGHUB_API_KEY \"<你的 Key>\"")
        L.append("    setx RUNNINGHUB_BASE_URL \"https://www.runninghub.ai\"")
    else:
        L.append("%-16s %-26s %-22s %-14s %s" % ("账号", "Key 来源（环境变量）", "站点", "指纹", "可用"))
        L.append("-" * 72)
        for r in rows:
            L.append("%-16s %-26s %-22s %-14s %s"
                     % (r["account"][:16], r["env"][:26], (r["site"] or "-")[:22],
                        r["fingerprint"], "是" if r["usable"] else "否"))
        L.append("")
        if len(rows) > 1:
            L.append("★ 多账号：用 `--account <别名> --account-source <环境变量名>` 指定用哪一个。")
        L.append("当前确认：%s" % (
            ("%s（指纹 %s）" % (ac.get("alias"), ac.get("key_fingerprint")))
            if ac.get("alias") else "未确认"))
        if ac.get("key_fingerprint") and live["fingerprint"] \
                and ac["key_fingerprint"] != live["fingerprint"]:
            L.append("★★ 漂移警告：当前环境 Key（%s）≠ 确认的账号（%s）"
                     % (live["fingerprint"], ac["key_fingerprint"]))
            L.append("   若确实要换账号，重新跑 setup set --account \"<别名>\" 覆盖确认单。")
    L.append("=" * 72)
    print("\n".join(L))
    return 0


def cmd_reset(a) -> int:
    ws = _resolve_ws(a.workspace)
    p = setup_path(ws)
    if p.is_file():
        try:
            p.unlink()
            print("[OK] 已删除确认单 %s" % p)
        except OSError as e:
            print("[FAIL] 删除失败：%s" % e)
            return 2
    else:
        print("（确认单不存在，无需清除）")
    if not getattr(a, "keep_style", False):
        print("提示：画风与模型通道的确认单（style-plan.json / model-plan.json）未动；"
              "要换画风请用 style reset。")
    return 0


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
class _capture:
    """临时吞掉被转发模块的 stdout（只把它当返回值用，不打两遍）。"""

    def __init__(self):
        import io
        self.buf = io.StringIO()

    @property
    def text(self) -> str:
        return self.buf.getvalue()

    def __enter__(self):
        import contextlib
        self._ctx = contextlib.redirect_stdout(self.buf)
        self._ctx.__enter__()
        return self

    def __exit__(self, *exc):
        return self._ctx.__exit__(*exc)


def _resolve_ws(explicit) -> pathlib.Path:
    if explicit:
        p = pathlib.Path(explicit).expanduser()
        if p.is_dir():
            return p.resolve()
    import os
    env = os.environ.get("SOLODRAMA_WORKSPACE") or os.environ.get("DRAMA_WORKSPACE")
    if env:
        p = pathlib.Path(env).expanduser()
        if p.is_dir():
            return p.resolve()
    sys.exit("[FAIL] 找不到短剧工作区：给 --workspace 或设 SOLODRAMA_WORKSPACE")


def main() -> int:
    ap = argparse.ArgumentParser(description="开工前置条件确认单（9 项）")
    ap.add_argument("--workspace", default=None)
    sub = ap.add_subparsers(dest="cmd")

    for name in ("show", "ask", "require", "reset", "accounts"):
        q = sub.add_parser(name)
        q.add_argument("--workspace", default=argparse.SUPPRESS)
        if name in ("show", "require", "accounts"):
            q.add_argument("--json", action="store_true")
        if name == "reset":
            q.add_argument("--keep-style", dest="keep_style", action="store_true")

    q = sub.add_parser("set")
    q.add_argument("--workspace", default=argparse.SUPPRESS)
    q.add_argument("--style", default=None, choices=("3d_manhua", "2d_animation", "live_action"))
    q.add_argument("--sub-mode", dest="sub_mode", default=None)
    q.add_argument("--episodes", type=int, default=None)
    q.add_argument("--ep-seconds", dest="ep_seconds", type=int, default=None)
    q.add_argument("--image-model", dest="image_model", default=None)
    q.add_argument("--image-workflow", dest="image_workflow", default=None)
    q.add_argument("--image-comfy-url", dest="image_comfy_url", default=None)
    q.add_argument("--image-app-url", dest="image_app_url", default=None)
    q.add_argument("--image-app-id", dest="image_app_id", default=None)
    q.add_argument("--video-model", dest="video_model", default=None)
    q.add_argument("--video-workflow", dest="video_workflow", default=None)
    q.add_argument("--video-workflow-id", dest="video_workflow_id", default=None)
    q.add_argument("--video-comfy-url", dest="video_comfy_url", default=None)
    q.add_argument("--video-app-url", dest="video_app_url", default=None)
    q.add_argument("--video-app-id", dest="video_app_id", default=None)
    # ★ 2026-10-21：工作流 API 与账号 Key（必须显式确认"用哪条工作流 / 哪个账号"）
    q.add_argument("--workflow-api", dest="workflow_api", default=None,
                   choices=tuple(WORKFLOW_KINDS),
                   help="用哪类工作流 API：%s" % " / ".join(WORKFLOW_KINDS))
    q.add_argument("--workflow-id", dest="workflow_id", default=None,
                   help="RunningHub workflowId（不是 API 导出的 json 文件名）")
    q.add_argument("--app-url", dest="app_url", default=None, help="RunningHub AI 应用地址")
    q.add_argument("--comfy-url", dest="comfy_url", default=None, help="云端 ComfyUI 服务地址")
    q.add_argument("--comfy-workflow", dest="comfy_workflow", default=None,
                   help="工作流 API 文件（*_api.json）")
    q.add_argument("--site", default=None,
                   help="站点：%s" % " / ".join(KNOWN_SITES))
    q.add_argument("--account", default=None,
                   help="账号别名（花谁的额度）；用当前环境 Key 登记指纹，Key 本体不落盘")
    q.add_argument("--account-source", dest="account_source", default=None,
                   help="从哪个环境变量读 Key（默认 %s）" % " / ".join(KEY_ENV_NAMES))
    q.add_argument("--resolution", default=None, help="交付画幅，如 1080x1920")
    q.add_argument("--steps", type=int, default=None, help="视频采样步数（turbo 常 4）")
    q.add_argument("--megapixels", type=float, default=None, help="视频源像素（0.8 / 1.0）")
    q.add_argument("--voice", default=None, choices=VOICE_CHOICES, help="声音归属")
    q.add_argument("--concurrency", type=int, default=None, help="平台并发（实测建议 2）")
    q.add_argument("--pipeline", default=None, choices=("on", "off"), help="是否流水线模式")
    q.add_argument("--budget-coins", dest="budget_coins", type=int, default=None)

    a = ap.parse_args()
    fn = {"show": cmd_show, "ask": cmd_ask, "require": cmd_require,
          "set": cmd_set, "reset": cmd_reset, "accounts": cmd_accounts}.get(a.cmd)
    if not fn:
        print(render(collect(_resolve_ws(a.workspace))))
        return 0
    return fn(a)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
