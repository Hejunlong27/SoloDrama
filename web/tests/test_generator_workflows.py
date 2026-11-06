#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_generator_workflows.py —— 「界面/预检核的那份」必须就是「真跑提交的那份」

起因（2026-11-06 复盘）：出图默认工作流有两套真源且指向**不同的文件**——

    执行器 comfy_client.DEFAULT_WORKFLOW      → workflow_qwen21_t2i_hq.json（11-02，turbo 融合）
    预配置卡 configs/presets/*.json → t2i      → workflow_qwen21_t2i_hq.json
    界面   generators.IMAGE_LOCAL_WF          → workflow_qwen_image21.json（10-16，4step LoRA）
    预检   gen_preflight.DEFAULT_WF["image"]  → workflow_qwen_image21.json

没有确认单的项目，预检会去核一张**根本不会提交**的图：报「缺模型」→ 人去删告警；
或者反过来全绿 → 真跑发现缺件。视频那条 2026-11-05 已经踩过一次，这里是同一个坑的另一半。

视频侧已有 `stages/video/comfyui/tests/test_workflow_defaults.py` 守；
本文件守**出图**侧，只断言一件事：三处取到的文件名相同，且文件真的在。
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

WEB = pathlib.Path(__file__).resolve().parents[1]
ROOT = WEB.parent
SCRIPTS = ROOT / "stages" / "production" / "scripts"
for p in (str(WEB), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from core import generators as GEN  # noqa: E402
import gen_preflight as GP          # noqa: E402


def _comfy_client_default() -> str:
    """执行器的默认出图工作流（用 importlib 直载，避免把整条链的副作用引进来）。"""
    path = ROOT / "stages" / "assets" / "comfyui" / "comfy_client.py"
    spec = importlib.util.spec_from_file_location("_cc_probe", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)      # type: ignore[union-attr]
    return str(getattr(mod, "DEFAULT_WORKFLOW", ""))


def test_image_default_is_same_file_everywhere():
    names = {
        "执行器 comfy_client": pathlib.Path(_comfy_client_default()).name,
        "预检 gen_preflight": pathlib.Path(str(GP.default_workflow("image"))).name,
        "界面 generators": pathlib.Path(str(GEN.IMAGE_LOCAL_WF)).name,
    }
    distinct = set(names.values())
    assert len(distinct) == 1, "出图默认工作流不是同一个文件：%s" % names
    assert (ROOT / "stages" / "assets" / "comfyui" / distinct.pop()).is_file()


def test_presets_point_to_that_same_file():
    """预配置卡会把这几个键写进模型确认单 —— 它们也必须指同一份，否则「配完就变味」。"""
    import json
    p = ROOT / "configs" / "presets" / "local-comfyui-all.json"
    d = json.loads(p.read_text(encoding="utf-8-sig"))
    t2i = pathlib.Path(str(((d.get("image") or {}).get("workflows") or {}).get("t2i") or "")).name
    assert t2i == pathlib.Path(str(GEN.IMAGE_LOCAL_WF)).name, \
        "预配置卡的 t2i=%r 与界面默认 %r 不一致" % (t2i, GEN.IMAGE_LOCAL_WF.name)
