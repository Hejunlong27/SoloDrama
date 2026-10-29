# -*- coding: utf-8 -*-
"""styles.py —— 画风目录（轨道 + 风格 + 画幅/分辨率预设）

**真源有两层**，这里只做汇总，不复制规则：
  * 轨道规格（3d_manhua / 2d_animation / live_action）在 `stages/production/scripts/style_gate.py`：
    它决定资产数、单镜时长、旁白字数、交付终点 —— 选错轨道，后面全错；
  * 具体风格（提示词）在 `configs/styles.json`：官方库条目，可增补。

为什么用 importlib 按路径加载 style_gate：引擎脚本必须能脱离 web 独立运行，
所以 web 反过来依赖它（而不是让它 import web.*）。同一套规则只维护一份。
"""
from __future__ import annotations

import importlib.util

from . import paths

_GATE_FILE = paths.STAGES_DIR / "production" / "scripts" / "style_gate.py"
_LIB_FILE = paths.CONFIGS_DIR / "styles.json"
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
    """→ {tracks, styles, presets, note}；引擎不可用时给 ok=False 与原因。"""
    try:
        g = _load_gate()
    except Exception as exc:                                     # noqa: BLE001
        return {"ok": False, "reason": "画风引擎不可用：%s" % exc,
                "tracks": [], "styles": [], "presets": {}}

    lib = g.style_lib()
    conf = paths.read_json(_LIB_FILE, default={}) or {}
    tracks = []
    for tid in g.ORDER:
        s = g.STYLES[tid]
        subs = []
        for sid, label in (s.get("sub_modes") or {}).items():
            it = lib.get(sid) or {}
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
    return {
        "ok": True,
        "tracks": tracks,
        "styles": list(lib.values()),
        "presets": conf.get("presets") or {},
        "source": conf.get("source") or "",
    }
