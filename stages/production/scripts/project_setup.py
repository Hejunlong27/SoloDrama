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
# 文件读写
# ---------------------------------------------------------------------------
def _now() -> str:
    return _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def setup_path(ws: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(ws) / SETUP_NAME


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
                if k in ("episodes", "resolution", "video_options", "pipeline") and isinstance(v, dict):
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
            "missing": list(miss), "manual": bool(opt.get("manual"))}


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
    """七项状态 + 派生值（每集镜数 / 单段币价 / 预算建议 / ETA）。"""
    ws = pathlib.Path(ws)
    d = load(ws)
    style = _style_state(ws)
    image = _model_state(ws, "image")
    video = _model_state(ws, "video")

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
    "resolution": 'drama.py setup set --resolution 1080x1920',
    "video_options": 'drama.py setup set --steps 4 --megapixels 0.8 --voice h3 --concurrency 2',
    "pipeline": 'drama.py setup set --pipeline on --budget-coins 9000（或 --pipeline off）',
}
ITEM_LABELS = {
    "style": "画风", "episodes": "剧集长度与每集时长", "image_model": "生图模型",
    "video_model": "视频模型", "resolution": "画面分辨率",
    "video_options": "视频功能选项", "pipeline": "流水线模式",
}


def require(ws: pathlib.Path) -> tuple:
    """门禁：七项全齐 → (True, 摘要)；否则 (False, 缺失清单文本)。"""
    st = collect(ws)
    if st["ok"]:
        it = st["items"]
        return True, ("前置条件 7/7 已确认：%s｜%d 集 × %d 秒｜生图=%s｜视频=%s｜%s｜流水线=%s"
                      % (it["style"]["value"], int(it["episodes"]["count"]),
                         int(it["episodes"]["seconds"]), it["image_model"]["choice"],
                         it["video_model"]["choice"], it["resolution"]["deliver"],
                         "开" if it["pipeline"]["enabled"] else "关"))
    lines = ["前置条件未齐（%d/%d）：" % (7 - len(st["missing"]), 7)]
    for k in st["missing"]:
        detail = st["items"][k]
        extra = ""
        if k in ("image_model", "video_model") and detail.get("missing"):
            extra = "（缺 %s）" % "、".join(str(x) for x in detail["missing"])
        lines.append("  - %s%s → %s" % (ITEM_LABELS.get(k, k), extra, FIX_HINTS.get(k, "")))
    return False, "\n".join(lines)


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------
def render(st: dict) -> str:
    it, dv = st["items"], st["derived"]
    L = ["=" * 72, "开工前置条件（7 项）", "=" * 72]
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
    vo = it["video_options"]
    L.append("%s4 视频模型    : %s" % (mark(vm["ok"]),
                                       ("%s（%s）" % (vm["choice"], vm.get("label")))
                                       if vm["ok"] else ("未确认" if not vm["choice"]
                                                         else "执行依据不全：%s" % "、".join(map(str, vm["missing"])))))
    L.append("%s5 功能选项    : %s 步 / %s MP / 声音=%s / 并发 %s%s"
             % (mark(vo["ok"]), vo.get("steps"), vo.get("megapixels"), vo.get("voice"),
                vo.get("concurrency"),
                "" if vo["ok"] else "   ← 非法"))
    r = it["resolution"]
    L.append("%s6 画面分辨率  : %s%s" % (mark(r["ok"]), r.get("deliver") or "未确认",
                                         "（源 %.2f MP）" % r["source_megapixels"]
                                         if r.get("deliver") else ""))
    p = it["pipeline"]
    L.append("%s7 流水线模式  : %s" % (mark(p["ok"]),
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
    L = ["=" * 72, "开工前需要你拍板 7 件事（其余我按默认值走，不反复问）", "=" * 72, ""]
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
    L.append("6. 画面分辨率：%s（平台下限，源 0.8MP 必须超分）" % RESOLUTION_DEFAULT)
    L.append("7. 是否开启流水线模式：开 → 必须同时给**预算上限**；确认后不再逐步问你")
    L.append("")
    L.append("-" * 72)
    L.append(render(st))
    L.append("-" * 72)
    L.append("用户答完后一次性写单：")
    L.append("  drama.py setup set --style live_action --episodes 30 --ep-seconds 60 \\")
    L.append("      --image-model local_comfyui --video-model runninghub --workflow-id <id> \\")
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

    # ⑥ 流水线模式 + 预算
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
        msgs.append("[OK] 前置条件 7/7 已就绪，可以开工")
    else:
        msgs.append("[BLOCK] 还缺：%s（退出码 %d）"
                    % ("、".join(ITEM_LABELS[k] for k in st["missing"]), EXIT_WAIT_CONFIRM))
        if rc == 0:
            rc = EXIT_WAIT_CONFIRM
    return rc, msgs


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
    ap = argparse.ArgumentParser(description="开工前置条件确认单（7 项）")
    ap.add_argument("--workspace", default=None)
    sub = ap.add_subparsers(dest="cmd")

    for name in ("show", "ask", "require", "reset"):
        q = sub.add_parser(name)
        q.add_argument("--workspace", default=argparse.SUPPRESS)
        if name == "show" or name == "require":
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
    q.add_argument("--resolution", default=None, help="交付画幅，如 1080x1920")
    q.add_argument("--steps", type=int, default=None, help="视频采样步数（turbo 常 4）")
    q.add_argument("--megapixels", type=float, default=None, help="视频源像素（0.8 / 1.0）")
    q.add_argument("--voice", default=None, choices=VOICE_CHOICES, help="声音归属")
    q.add_argument("--concurrency", type=int, default=None, help="平台并发（实测建议 2）")
    q.add_argument("--pipeline", default=None, choices=("on", "off"), help="是否流水线模式")
    q.add_argument("--budget-coins", dest="budget_coins", type=int, default=None)

    a = ap.parse_args()
    fn = {"show": cmd_show, "ask": cmd_ask, "require": cmd_require,
          "set": cmd_set, "reset": cmd_reset}.get(a.cmd)
    if not fn:
        print(render(collect(_resolve_ws(a.workspace))))
        return 0
    return fn(a)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
