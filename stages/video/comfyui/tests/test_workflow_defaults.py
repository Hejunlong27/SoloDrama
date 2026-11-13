#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_workflow_defaults.py —— 「默认工作流按通道分」这件事必须只有一份真源

为什么单独一条
--------------
2026-11-06 起本机与云端**不再共用同一个默认工作流**：

    本机 ComfyUI（4060 8G） → workflow_h3_minimax_canvas.json（6 参考槽 + fl2v turbo 8step）
    云端镜像（4090 24G）    → workflow_h3_pika_8g.json      （pika 极速版：2 槽 + lcm + SigmaShift）

这是本仓库最容易漂的一类改动的**升级版**：以前只有「A 还是 B」一份，漂了是「核 A 跑 B」；
现在有两份，漂了会变成「本机跑云端模型 / 云端跑本机模型」——两边都可能缺件或 OOM，
而且都不在提交前报错。历史上已经踩过两次同源问题（2026-11-04 界面 canvas 而执行器旧版；
2026-11-05 干跑 canvas 而真跑替代版），所以这里守四条。
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
COMFY = HERE.parent
STAGES = COMFY.parents[1]
for p in (str(COMFY), str(STAGES / "production" / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import workflow_defaults as WD  # noqa: E402

WORKFLOWS = sorted({WD.LOCAL_VIDEO, WD.CLOUD_VIDEO})


def test_local_and_cloud_share_requested_default():
    """两份必须是不同的文件 —— 若哪天又合并成一份，下面「按通道」的逻辑就是假的。"""
    assert WD.video_name(False) == WD.video_name(True) == "workflow_h3_minimax_audio.json"


@pytest.mark.parametrize("name", WORKFLOWS)
def test_default_workflow_is_api_format_and_has_map(name):
    wf_path = COMFY / name
    assert wf_path.is_file(), "默认工作流不存在：%s" % wf_path
    doc = json.loads(wf_path.read_text(encoding="utf-8-sig"))
    assert doc and all(isinstance(v, dict) and "class_type" in v for v in doc.values()), \
        "%s 不是 API 格式（界面格式不能提交）" % name
    assert (COMFY / (wf_path.stem + ".map.json")).is_file(), "%s 缺同名映射" % name


def test_executor_follows_single_source():
    """执行器的默认值必须就是 `workflow_defaults` 给的那两个（不自带第二份字面量）。"""
    import comfy_local_video as V  # noqa: PLC0415

    assert pathlib.Path(V.DEFAULT_WORKFLOW).name == WD.video_name(False)
    assert pathlib.Path(V.DEFAULT_WORKFLOW_CLOUD).name == WD.video_name(True)


def test_preflight_follows_single_source():
    """预检核的必须是**将要提交的那一份** —— 云端就核 pika，本机就核 canvas。"""
    import gen_preflight as GP  # noqa: PLC0415

    assert GP.default_workflow("video", cloud=False).name == WD.video_name(False)
    assert GP.default_workflow("video", cloud=True).name == WD.video_name(True)
    # 图像不分通道：两处必须指同一个文件
    assert GP.default_workflow("image", cloud=False) == GP.default_workflow("image", cloud=True)


def test_cloud_default_has_six_ref_slots():
    """pika 版只有 2 个参考槽 —— 这条记下来，是因为它会让多角色的镜头少一致性。

    断言「槽数 = 2」不是迷信数字，而是防止有人改了工作流却以为还是 6 槽：
    槽位变少是**静默的**（多余的参考图会被 `apply_nodes` 规则重复最后一张填槽）。
    """
    doc = json.loads((COMFY / WD.CLOUD_VIDEO).read_text(encoding="utf-8-sig"))
    loads = [k for k, v in doc.items() if v.get("class_type") == "LoadImage"]
    assert len(loads) == 6, "默认工作流的参考图槽变成了 %d 个：%s" % (len(loads), loads)


def test_default_video_resolution_is_08mp():
    doc = json.loads((COMFY / WD.LOCAL_VIDEO).read_text(encoding="utf-8-sig"))
    nodes = [v for v in doc.values() if v.get("class_type") == "ResolutionSelector"]
    assert nodes, "默认视频工作流没有 ResolutionSelector"
    assert all(v.get("inputs", {}).get("megapixels") == 0.8 for v in nodes), nodes
