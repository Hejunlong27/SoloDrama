# -*- coding: utf-8 -*-
"""ingest_check 的图片槽位编号回归。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
FIXTURE = HERE / "fixtures" / "mini_drama"
os.environ["SOLODRAMA_WORKSPACE"] = str(FIXTURE)
sys.path.insert(0, str(SCRIPTS))

import ingest_check as I  # noqa: E402


def test_board_picture_one_and_asset_picture_two_is_valid():
    prompt = (
        "subject_definitions:\n"
        "<Picture 1> 是本镜分镜图。\n"
        "<Subject 1> 是 <Picture 2> 中的 P01。\n"
        "summary: [reference generation] test\n"
        "retention_analysis:\n"
        "<Picture 1> partially_preserved\n"
        "<Subject 1> fully_preserved\n"
        "detailed_description: [Shot 1] test"
    )
    errs, _warns = I.check_shot("shot_001", prompt, 4, ["__board__", "P01@VIEW"], FIXTURE)
    assert not any("图号不连续" in e for e in errs), errs


def test_asset_picture_gap_is_still_rejected():
    prompt = (
        "subject_definitions:\n"
        "<Picture 1> 是本镜分镜图。\n"
        "<Subject 1> 是 <Picture 3> 中的 P01。\n"
        "summary: [reference generation] test\n"
        "retention_analysis:\n"
        "<Picture 1> partially_preserved\n"
        "<Subject 1> fully_preserved\n"
        "detailed_description: [Shot 1] test"
    )
    errs, _warns = I.check_shot("shot_001", prompt, 4, ["__board__", "P01@VIEW", "P02@VIEW"], FIXTURE)
    assert any("资产图号不连续" in e for e in errs), errs
