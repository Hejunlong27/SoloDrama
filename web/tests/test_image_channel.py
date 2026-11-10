#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""资产出图的通道判定 —— 单张重出必须与引擎门禁同一条口径。

界面自己给一个「默认本地/云端」，用户点下去只会看到「按钮没反应」：
`drama.py` 的 `_model_gate()` 会拿 `engine_arg` 跟确认单比对，不一致就退出码 4。
`graph._cmd_for()` 已经踩过这个坑，`generators.image_channel()` 是同一个口径的第三个调用者。

这组测试钉四件事：
1. 选云端 ComfyUI → `assets.cloud` 且 `paid=True`（不能显示成免费）
2. 确认单里没有这一类 → 回落 `assets.local` 且 `paid=False`
3. 「选云端但地址是本机」= 假云端，必须提前标出来（否则点了才报错）
4. RunningHub 通道 `backup=False`（它不经过本地落盘，没有旧图可备份）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "web"))

from core import generators  # noqa: E402


def _ws(tmp_path, node=None):
    ws = tmp_path / "剧"
    ws.mkdir()
    (ws / "layout.json").write_text("{}", encoding="utf-8")
    if node is not None:
        (ws / "model-plan.json").write_text(json.dumps(
            {"models": {"image": node}}, ensure_ascii=False), encoding="utf-8")
    return ws


def test_cloud_choice_maps_to_cloud_command_and_is_paid(tmp_path):
    ws = _ws(tmp_path, {
        "choice": "cloud_comfyui", "label": "云端 ComfyUI（★计费/自建）",
        "cost": "按云主机/平台计费（自建或租用）", "confirmed": True,
        "detail": {"comfy_url": "https://abc-8188.container.x-gpu.com"},
    })
    d = generators.image_channel(ws)
    assert d["spec"] == "assets.cloud", d
    assert d["paid"] is True, "计费通道被标成免费，用户会以为不花钱：%s" % d
    assert d["fake_cloud"] is False, d
    assert "★计费" in d["label"], "label 应沿用确认单原文（含计费标记）"
    assert d["url"].startswith("https://"), d


def test_no_plan_falls_back_to_local_and_free(tmp_path):
    ws = _ws(tmp_path, None)
    d = generators.image_channel(ws)
    assert d["spec"] == "assets.local", d
    assert d["paid"] is False, d
    assert d["confirmed"] is False, "没有确认单时要如实说没确认"


def test_cloud_with_loopback_url_is_flagged_fake(tmp_path):
    """选云端、地址却是本机 —— 引擎会直接拦，界面得先说出来。"""
    ws = _ws(tmp_path, {
        "choice": "cloud_comfyui", "label": "云端 ComfyUI（★计费/自建）",
        "confirmed": True, "detail": {"comfy_url": "http://127.0.0.1:8188"},
    })
    d = generators.image_channel(ws)
    assert d["spec"] == "assets.cloud"
    assert d["fake_cloud"] is True, d


def test_runninghub_has_no_backup(tmp_path):
    """RH 工作流不经过本地落盘（没有 `comfy_client` 的那一步），无法备份旧图。"""
    ws = _ws(tmp_path, {"choice": "runninghub", "label": "RunningHub 工作流",
                        "confirmed": True, "detail": {}})
    d = generators.image_channel(ws)
    assert d["spec"] == "assets.rh_wf", d
    assert d["backup"] is False, "RH 通道不该声称能备份旧图"
    assert d["paid"] is True, d


# ---------------------------------------------------------------------------
# 提交时的 argv：三个开关少一个，功能就是「点了没反应」
# ---------------------------------------------------------------------------
def test_regen_argv_carries_only_force_backup():
    """前端提交的 params → CLI argv。三个开关一个都不能掉。

    * `--only`   不带就整批出图（连带别的角色全重跑）
    * `--force`  不带引擎会 `--skip-existing` 跳过已有产物 —— 点了等于什么都没做，
                 而且**不报错**，用户只会觉得按钮坏了
    * `--backup` 不带就覆盖旧图，重出更差时无法退回
    """
    from core import commands as CMDS

    cmd = CMDS.get("assets.local")
    assert cmd is not None, "找不到 assets.local 命令"
    argv = cmd.build_argv({
        "only": "P01@LOOK-B", "force": True, "submit": True, "backup": True,
    }, ws=None)
    joined = " ".join(argv)
    for flag in ("--only P01@LOOK-B", "--force", "--submit", "--backup"):
        assert flag in joined, "缺少 %s：%s" % (flag, joined)
    assert argv[0] == sys.executable or "python" in argv[0].lower(), argv[:1]

