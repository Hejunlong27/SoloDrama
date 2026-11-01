# -*- coding: utf-8 -*-
"""站点真源读取 —— 全仓库唯一实现。

谁需要「运行时用哪个 RunningHub 站点」，都调 `runtime_site()`：
能力卡自检、环境体检、项目初始化向导。

为什么单独拆一个模块：这三处以前各写一份「找引擎目录 + import config」的样板，
很快就会出现「卡说 .cn、体检说 .ai、向导说默认值」的三方不一致 ——
而那正是 2026-11-01 这次环境整改要收掉的东西。规则只留一份，才不会各自漂。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ENGINE_DIR = None


def engine_dir() -> Path:
    """向上找 `stages/video/workflow/scripts/engine`；找不到返回空 Path。"""
    global _ENGINE_DIR
    if _ENGINE_DIR is None:
        _ENGINE_DIR = Path()
        for up in Path(__file__).resolve().parents[:7]:
            cand = up / "stages" / "video" / "workflow" / "scripts" / "engine"
            if (cand / "config.py").is_file():
                _ENGINE_DIR = cand
                break
    return _ENGINE_DIR


def runtime_site() -> tuple:
    """→ (base_url, 来源说明, 被忽略的旧环境变量值)。

    取不到时返回 `("", 原因, "")` —— 调用方按「未知」处理，不要自己编一个默认值。
    """
    eng = engine_dir()
    if not eng.name:
        return ("", "找不到引擎目录", "")
    try:
        if str(eng) not in sys.path:
            sys.path.insert(0, str(eng))
        import config as _C                                    # noqa: E402
        return (str(_C.RH_BASE_URL),
                str(getattr(_C, "RH_SITE_SOURCE", "") or ""),
                str(getattr(_C, "RH_SITE_IGNORED", "") or ""))
    except Exception as exc:                                   # noqa: BLE001
        return ("", "引擎配置导入失败（%s）" % type(exc).__name__, "")


def project_site(vp) -> str:
    """项目级站点：`<引擎工作区>/config.local.json` 的 `runninghub_base_url` 优先，
    否则用仓库真源（`configs/channels.json`）。

    这个函数的存在是为了**删掉三份重复实现**：`gen_char_assets` / `gen_scene_assets` /
    `gen_assets_rh_workflow` 各自写过一次「先读环境变量、再读项目配置、最后用引擎默认」，
    三份都对「优先级」有不同理解 —— 那正是「同一件事三条路」的典型。
    `RUNNINGHUB_BASE_URL` 已废弃，不再读。
    """
    if vp:
        try:
            d = json.loads((Path(vp) / "config.local.json").read_text(encoding="utf-8"))
            v = str(d.get("runninghub_base_url") or "").strip()
            if v:
                return v.rstrip("/")
        except (OSError, ValueError):
            pass
    return runtime_site()[0].rstrip("/")
