#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_preset_apply.py —— 预配置卡不得变成「静默选通道」的后门

为什么单独守这一条
------------------
2026-11-06 用户实测：新建项目后**什么都没选**，项目就跑到了 RunningHub（平台计费）上。
两个成因同时存在：

1. `preset_apply.py` 的兜底写的是 `vid.get("choice") or "runninghub"` ——
   预配置卡只要漏一个 `video.choice`，通道就被静默设成计费通道；
2. 界面层的选项值写错了（`runninghub` / `closed_model` 不是引擎的 id），
   那条由 `web/tests/test_ux.py` 守。

这里的判据只有一条：**预配置卡必须显式声明 image/video 的通道**，
且取值必须是 `model_gate.MODEL_OPTIONS` 里真实存在的 id。
显式声明 = 兜底永远不会被触发 = 不可能再「默认跑到计费通道」。
"""
from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(ROOT / "stages" / "production" / "scripts"))

import model_gate as M  # noqa: E402

PRESETS = ROOT / "configs" / "presets"


def _ids(kind: str) -> set:
    return {o["id"] for o in M.MODEL_OPTIONS[kind]}


def test_every_preset_declares_both_channels():
    files = sorted(PRESETS.glob("*.json"))
    assert files, "configs/presets/ 里没有任何预配置卡"
    for p in files:
        d = json.loads(p.read_text(encoding="utf-8-sig"))
        for kind in ("image", "video"):
            choice = str(((d.get(kind) or {}).get("choice") or "")).strip()
            assert choice, "%s 没有声明 %s.choice —— 会走到兜底逻辑" % (p.name, kind)
            assert choice in _ids(kind), (
                "%s 的 %s.choice=%r 不是引擎的通道 id（可选 %s）"
                % (p.name, kind, choice, sorted(_ids(kind))))


def test_fallback_is_free_channel():
    """兜底必须是「不花钱、不需要额外依据」的那一档。

    直接读源码字符串是有意的：这条兜底不在任何函数边界上，跑不到它就只能读它。
    比它更重要的是上一条 —— 预配置卡都显式声明了，兜底本来就不该被触发。
    """
    src = (HERE.parent / "preset_apply.py").read_text(encoding="utf-8")
    assert 'vid.get("choice") or "local_comfyui"' in src, \
        "preset_apply 的出片通道兜底不再是 local_comfyui（会被静默设成计费通道）"
    assert 'img.get("choice") or "local_comfyui"' in src, \
        "preset_apply 的出图通道兜底不再是 local_comfyui"


def test_local_choice_needs_no_evidence():
    """本机通道必须是「零执行依据」的 —— 否则点它也会被门禁拦下（等于没得选）。"""
    for kind in ("image", "video"):
        opt = next(o for o in M.MODEL_OPTIONS[kind] if o["id"] == "local_comfyui")
        assert not (opt.get("requires") or []), "%s/local_comfyui 要求执行依据：%s" % (kind, opt["requires"])
        assert opt.get("executor"), "%s/local_comfyui 没有执行器，选了也跑不通" % kind
