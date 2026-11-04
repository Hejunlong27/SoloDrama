# -*- coding: utf-8 -*-
"""profile.py —— 项目单一档案 `drama.json` 的唯一读写实现

为什么要有它：整改前，同一个项目的「用了什么画风 / 走哪个通道 / 几集多长」散在
`style-plan.json`、`model-plan.json`、`project-setup.json` 三个文件里，外加
`video-pipeline/config.local.json` 才是真正生效的那份 —— 没有任何一处能回答
「这次到底用哪个参数」。四份不一致时，谁也说不清该信谁。

现在：**一个 `<ws>/drama.json` 说清楚四维**（形态 / 视觉 / 叙事 / 通道），
其余文件只在过渡期保留，读的时候按「drama.json 优先 → 旧文件回退」处理。

四维的定义（互不绑定，任一项可单独改）：
    format.track      形态：3d_manhua | 2d_animation | live_action   （configs/tracks.json）
    format.look       视觉：looks.json 里的 id                        （configs/looks.json）
    format.narrative  叙事：dialogue | narration                      （configs/narratives.json）
    channel.*         通道：image / video，各挂一张能力卡              （configs/capabilities/）
"""
from __future__ import annotations

import datetime as _dt
import json
import pathlib

PROFILE_NAME = "drama.json"
SCHEMA = "drama-profile/2"

# 过渡期还要读的旧文件（只读；写一律写 drama.json）
LEGACY_STYLE = "style-plan.json"
LEGACY_MODELS = "model-plan.json"
LEGACY_SETUP = "project-setup.json"


def _now() -> str:
    return _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def path_of(ws) -> pathlib.Path:
    return pathlib.Path(ws) / PROFILE_NAME


def _read(p: pathlib.Path) -> dict:
    try:
        d = json.loads(p.read_text(encoding="utf-8-sig"))
        return d if isinstance(d, dict) else {}
    except Exception:                                          # noqa: BLE001
        return {}


def blank(slug: str = "") -> dict:
    """空档案：只保证结构齐全，值全空。"""
    return {
        "schema": SCHEMA,
        "slug": slug,
        "format": {"track": "", "look": "", "narrative": "dialogue", "aspect": "9:16"},
        "episodes": {"count": 0, "seconds": 0, "shots": [0, 0]},
        "channel": {
            "image": {"engine": "", "capability": ""},
            "video": {"engine": "", "capability": ""},
        },
        "delivery": {"resolution": "", "subs": "burn", "upscaler": ""},
        "loop": {"l0": 2, "l1": 3, "l2": 1, "budget_coins": 0},
        "confirmed": {"format_at": "", "channel_at": ""},
    }


def load(ws) -> dict | None:
    """读 drama.json；不存在返回 None（调用方据此回退旧文件）。"""
    p = path_of(ws)
    if not p.is_file():
        return None
    d = _read(p)
    if not d:
        return None
    d.setdefault("schema", SCHEMA)
    for k, v in blank(d.get("slug") or "").items():
        if k not in d:
            d[k] = v
        elif isinstance(v, dict):
            for kk, vv in v.items():
                d[k].setdefault(kk, vv)
    return d


def save(ws, d: dict) -> pathlib.Path:
    p = path_of(ws)
    p.parent.mkdir(parents=True, exist_ok=True)
    d["schema"] = SCHEMA
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def from_legacy(ws) -> dict:
    """把三份旧文件推导成一份档案（不落盘）。

    只做**可判定的映射**，不猜：
      * track   ← style-plan.style.choice
      * look    ← style-plan.style.look；老档案把题材风格写在 sub_mode 里，
                  那个值如果命中 looks.json 就认作 look
      * narrative ← style-plan.style.narrative，缺省 dialogue
      * channel.image.engine ← model-plan.models.image.choice（只剩 local_comfyui / cloud_comfyui）
      * episodes / delivery ← project-setup
    """
    ws = pathlib.Path(ws)
    style = _read(ws / LEGACY_STYLE)
    models = _read(ws / LEGACY_MODELS)
    setup = _read(ws / LEGACY_SETUP)

    d = blank(str((setup.get("slug") or style.get("slug") or "")))
    st = style.get("style") or {}
    fmt = d["format"]
    fmt["track"] = str(st.get("choice") or "")

    look = str(st.get("look") or "").strip()
    if not look:
        # 老档案：sub_mode 可能是渲染流，也可能是题材风格（历史遗留的混装）
        sub = str(st.get("sub_mode") or "").strip()
        try:
            looks = {x.get("id") for x in
                     json.loads((pathlib.Path(__file__).resolve().parents[3] /
                                 "configs" / "looks.json").read_text(encoding="utf-8-sig"))["looks"]}
        except Exception:                                      # noqa: BLE001
            looks = set()
        look = sub if sub in looks else ""
    fmt["look"] = look
    fmt["narrative"] = str(st.get("narrative") or "dialogue")
    if st.get("confirmed") and st.get("confirmed_at"):
        d["confirmed"]["format_at"] = str(st["confirmed_at"])

    eps = setup.get("episodes") or {}
    if eps:
        d["episodes"] = {
            "count": int(eps.get("count") or 0),
            "seconds": int(eps.get("seconds") or 0),
            "shots": [int(eps.get("shots_min") or 0), int(eps.get("shots_max") or 0)],
        }
    res = (setup.get("resolution") or {}).get("deliver")
    if res:
        d["delivery"]["resolution"] = str(res)

    img = ((models.get("models") or {}).get("image") or {})
    if img.get("choice"):
        d["channel"]["image"]["engine"] = str(img["choice"])

    # 视频通道：旧三份里没有（model-plan 只登记了 image），真源在引擎侧。
    #   engine 一律写 local_comfyui —— 迁移后的档案不能指回一条无法执行的通道。
    eng = _read(ws / "video-pipeline" / "config.local.json")
    h3 = eng.get("h3") or {}
    legacy_id = str(h3.get("id") or "").strip()
    wf = str(h3.get("workflow") or "").strip()
    comfy_url = str(h3.get("comfy_url") or eng.get("comfy_url") or "").strip()
    d["channel"]["video"]["engine"] = "local_comfyui"
    if wf:
        d["channel"]["video"]["workflow"] = wf
    if comfy_url:
        d["channel"]["video"]["comfy_url"] = comfy_url
    if legacy_id:
        d["channel"]["video"]["workflow_id_note"] = (
            "旧档案里的工作流 ID %s（2026-11-04 起不再使用）" % legacy_id)
    return d


def effective(ws) -> dict:
    """实际生效的档案：有 drama.json 用它，否则从旧文件推导。"""
    d = load(ws)
    return d if d is not None else from_legacy(ws)


def merge_patch(ws, patch: dict) -> dict:
    """按点路径写档案（如 {"format.look": "cinematic"}），返回新档案。"""
    d = effective(ws)
    for k, v in (patch or {}).items():
        cur = d
        parts = k.split(".")
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = v
    return d


def fmt_line(d: dict) -> str:
    """一行摘要，给 status / 日志用。"""
    f = d.get("format") or {}
    c = d.get("channel") or {}
    e = d.get("episodes") or {}
    return ("track=%s｜look=%s｜narrative=%s｜aspect=%s｜%s集×%ss｜image=%s｜video=%s"
            % (f.get("track") or "-", f.get("look") or "-", f.get("narrative") or "-",
               f.get("aspect") or "-", e.get("count") or "-", e.get("seconds") or "-",
               (c.get("image") or {}).get("engine") or "-",
               (c.get("video") or {}).get("engine") or "-"))
