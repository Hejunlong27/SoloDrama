# -*- coding: utf-8 -*-
"""comfy_ports.py —— 端口识别 / 槽位裁剪（Web 侧入口）

**实现不在这里**：真源是 `stages/video/comfyui/comfy_ports.py`（引擎脚本要能独立跑，
不能反向依赖 web 包）。这里只按路径加载，避免同一套规则维护两份 —— 两份一定会漂。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from . import paths

_ENGINE_FILE = paths.STAGES_DIR / "video" / "comfyui" / "comfy_ports.py"
_mod = None


def _load():
    global _mod
    if _mod is not None:
        return _mod
    if not _ENGINE_FILE.is_file():
        raise ImportError("找不到引擎侧端口模块：%s" % _ENGINE_FILE)
    spec = importlib.util.spec_from_file_location("_comfy_ports_engine", str(_ENGINE_FILE))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _mod = mod
    return mod


def describe(wf: dict) -> dict:
    return _load().describe(wf)


def prune_for_refs(wf: dict, want_images):
    return _load().prune_for_refs(wf, want_images)


def reachable(wf: dict, outputs) -> set:
    return _load().reachable(wf, outputs)


def plan_slots(info: dict, have: int) -> dict:
    return _load().plan_slots(info, have)


def is_workflow(wf) -> bool:
    return _load()._is_workflow(wf)
