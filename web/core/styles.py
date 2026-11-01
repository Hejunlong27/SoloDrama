# -*- coding: utf-8 -*-
"""styles.py —— 画风目录（形态 + 视觉库 + 渲染流 + 预设）

**真源有三层**，这里只做汇总，不复制规则：

  * 形态（track）`configs/tracks.json`：资产数、单镜时长、分镜拓扑、交付终点、渲染流菜单
  * 视觉（look）`configs/looks.json`：**风格库本体**（surreal-cinema / cel-shading / …），纯 prompt
  * 叙事（narrative）`configs/narratives.json`：旁白配额与台词密度
  * 画幅/分辨率预设 `configs/render-presets.json`（原 `styles.json`，已更名 —— 它不含风格）

为什么用 importlib 按路径加载 style_gate：引擎脚本必须能脱离 web 独立运行，
所以 web 反过来依赖它（而不是让它 import web.*）。同一套规则只维护一份。

⚠ 2026-11-01 修：`catalog()` 曾把 `style_lib()`（渲染流）当成「风格库」返回，
于是 Studio 只看到 6 条渲染手法（guoman-3d-render / cel-anime / …），
而 13 条真正的风格（surreal-cinema / cel-shading / cinematic / …）**一条都看不到**。
原因是 V0.7.32 把 `style_lib()` 的语义从「题材风格」改成了「轨道渲染流」，
调用方没跟着改。现在 `looks` 是风格库，`render_styles` 单独给。
"""
from __future__ import annotations

import importlib.util

from . import paths

_GATE_FILE = paths.STAGES_DIR / "production" / "scripts" / "style_gate.py"
_PRESET_FILE = paths.CONFIGS_DIR / "render-presets.json"
_gate = None


def _load_gate():
    global _gate
    if _gate is not None:
        return _gate
    if not _GATE_FILE.is_file():
        raise ImportError("找不到引擎侧画风门禁：%s" % _GATE_FILE)
    spec = importlib.util.spec_from_file_location("_style_gate_engine", str(_GATE_FILE))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _gate = mod
    return mod


def catalog() -> dict:
    """→ {ok, tracks, looks, styles, render_styles, presets, source}

    `styles` 与 `looks` **同源**（视觉库），保留 `styles` 只为兼容既有调用方；
    新代码请读 `looks`。`render_styles` 是各轨的渲染手法，不是风格库。
    """
    try:
        g = _load_gate()
    except Exception as exc:                                     # noqa: BLE001
        return {"ok": False, "reason": "画风引擎不可用：%s" % exc,
                "tracks": [], "looks": [], "styles": [], "render_styles": [], "presets": {}}

    render_all = g.style_lib()

    tracks = []
    for tid in g.ORDER:
        s = g.STYLES[tid]
        subs = []
        for sid, label in (s.get("sub_modes") or {}).items():
            it = render_all.get(sid) or {}
            subs.append({"id": sid, "label": it.get("name") or label,
                         "label_full": label,
                         "tags": it.get("tags") or [],
                         "prompt": it.get("prompt") or "",
                         "official": bool(it)})
        tracks.append({
            "id": tid, "label": s["label"], "desc": s["desc"],
            "default_sub_mode": s.get("default_sub_mode"),
            "visual_style_lock": s.get("visual_style_lock"),
            "spec": {k: s.get(k) for k in ("shot_duration", "narration_max_chars",
                                           "storyboard_topology", "delivery_stop")},
            "sub_modes": subs,
        })

    looks = []
    for lid, it in (g.looks_lib() or {}).items():
        looks.append({
            "id": lid,
            "name": it.get("name") or lid,
            "name_en": it.get("name_en") or "",
            "prompt": it.get("prompt") or "",
            "tags": it.get("tags") or [],
            "source": it.get("source") or "",
            # 只是推荐，不是绑定：同一条 look 可以在三条轨上都设进去
            "recommended_for": it.get("recommended_for") or [],
        })

    render_styles = [{"id": rid, "name": it.get("name") or rid,
                      "prompt": it.get("prompt") or "",
                      "track": it.get("track") or ""}
                     for rid, it in render_all.items()]

    conf = paths.read_json(_PRESET_FILE, default={}) or {}
    return {
        "ok": True,
        "tracks": tracks,
        "looks": looks,
        "styles": looks,          # 兼容：旧调用方把「风格库」叫 styles
        "render_styles": render_styles,
        "presets": conf.get("presets") or {},
        "source": conf.get("source") or "",
    }
