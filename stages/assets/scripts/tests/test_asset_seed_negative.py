# -*- coding: utf-8 -*-
"""逐条种子 + 负向词通道 —— 两条「人物越长越像同一个人」的机械成因，钉住不许回退。

背景（2026-11-07 实测）
----------------------
1. **种子**：manifest 里一条 `seed` 都没有，`comfy_client.build()` 的
   `if seed is not None` 永远为假 ⇒ 所有资产沿用工作流里写死的 `noise_seed`。
   实测 9 张图（3 角色 + 6 场景）拿到同一个种子；配合 90% 同构的提示词骨架，
   模型先验一直锁在「平均脸」附近。
2. **负向词**：卡片末尾的 `EXCLUDE:` / `人物负面：` 段被**原样当正向提示词**提交
   （工作流 `negative_prompt` 为空、`cfg=1`）。等于在提示词里反复说
   「网红脸、削尖下颌、放大眼裂」。

本文件守三件事：种子逐条不同且可复现 · 否定块不进正向 · 负向词写进真负向节点。
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
SCRIPTS = HERE.parent                       # …/stages/assets/scripts
COMFY = SCRIPTS.parent / "comfyui"
sys.path.insert(0, str(SCRIPTS))

import asset_md as AM                        # noqa: E402


def _client():
    """按路径加载 comfy_client（它 import 期会套预设、读端口表，都是纯本地动作）。"""
    spec = importlib.util.spec_from_file_location("_cc_for_test", COMFY / "comfy_client.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SAMPLE = """# 一、角色资产库

## 1. 时小满（女主·26岁）
**基础造型**
```
写实电影感，时小满，圆脸短狼尾，芥末黄连帽卫衣。EXCLUDE: beauty face, narrowed jaw
```

## 2. 周叙（男主·29岁）
**基础造型**
```
写实电影感，周叙，窄长脸寸头，深灰夹克。
人物负面：网红脸，锥子脸
```

## 3. 陶桃（女配·27岁）
**基础造型**
```
写实电影感，陶桃，方脸长卷发。
```
"""


def _write_md(tmp_path: pathlib.Path) -> pathlib.Path:
    p = tmp_path / "assets.md"
    p.write_text(SAMPLE, encoding="utf-8")
    return p


# ---------------------------------------------------------------- 拆词
def test_split_negative_ascii_marker_mid_line():
    pos, neg = AM.split_negative("画面描述。EXCLUDE: beauty face, narrowed jaw")
    assert pos == "画面描述。"
    assert neg == "beauty face, narrowed jaw"


def test_split_negative_chinese_marker():
    pos, neg = AM.split_negative("画面描述。\n人物负面：网红脸，锥子脸")
    assert pos == "画面描述。"
    assert "网红脸" in neg


def test_split_negative_no_marker_is_noop():
    src = "普通提示词，没有否定块"
    assert AM.split_negative(src) == (src, "")


def test_split_negative_empty_block_keeps_prompt():
    """写了 `EXCLUDE:` 但后面什么都没有 —— 不能把正向提示词整段吃掉。"""
    pos, neg = AM.split_negative("正面描述\nEXCLUDE:")
    assert pos == "正面描述" and neg == ""


def test_merge_negative_dedupes_and_orders():
    got = AM.merge_negative("a, b", "B, c", "  ")
    assert got == "a, b, c", got


# ---------------------------------------------------------------- 种子
def test_derive_seed_stable_and_distinct():
    a = AM.derive_seed("char_01")
    assert a == AM.derive_seed("char_01"), "同一 id 必须永远同一颗种子"
    ids = ["char_%02d" % i for i in range(1, 13)] + ["scene_01", "prop_01"]
    seeds = {AM.derive_seed(i) for i in ids}
    assert len(seeds) == len(ids), "不同资产撞同一颗种子 = 回到「同一张脸」"


def test_derive_seed_follows_base():
    base = 20261106
    assert AM.derive_seed("char_01", base + 1) == AM.derive_seed("char_01", base) + 1


# ---------------------------------------------------------------- 清单
def test_to_assets_splits_negative_and_assigns_seeds(tmp_path):
    entries = AM.parse_md(_write_md(tmp_path))
    assets = AM.to_assets(entries)
    assert len(assets) == 3
    by_id = {a["id"]: a for a in assets}
    assert "EXCLUDE" not in by_id["char_01"]["prompt"].upper()
    assert "beauty face" in by_id["char_01"]["negative"]
    assert "网红脸" in by_id["char_02"]["negative"]
    assert by_id["char_03"]["negative"] == ""
    assert len({a["seed"] for a in assets}) == 3


def test_build_manifest_records_seed_base_and_hash_covers_negative(tmp_path):
    md = _write_md(tmp_path)
    assets = AM.to_assets(AM.parse_md(md))
    man = AM.build_manifest(md, assets, seed_base=42)
    assert man["seed_base"] == 42
    assert all(isinstance(a["seed"], int) and a["seed"] >= 42 for a in man["assets"])

    # 只改负向词也要让 _prompts_sha 变化（否则 --diff 看不见这类改动）
    before = man["_prompts_sha256_16"]
    for a in assets:
        a["negative"] = ""
    after = AM.build_manifest(md, assets, seed_base=42)["_prompts_sha256_16"]
    assert before != after


# ---------------------------------------------------------------- 客户端
def test_client_writes_negative_to_negative_node(tmp_path):
    C = _client()
    base = json.loads((COMFY / "workflow_qwen21_t2i_hq.json").read_text(encoding="utf-8"))
    nid = C.neg_node_of(base)
    assert nid, "工作流里应有 negative_prompt 节点"
    wf = C.build(base, "a woman", "P01_x", seed=7, negative="beauty face")
    assert wf[nid]["inputs"]["negative_prompt"] == "beauty face"
    assert wf[C.SEED_NODE]["inputs"]["noise_seed"] == 7
    # 不许改到原文件的那份内存对象
    assert base[nid]["inputs"]["negative_prompt"] == "" or base[nid]["inputs"]["negative_prompt"] != "beauty face"


def test_client_min_cfg_flags_turbo_workflow():
    """默认出图工作流是 cfg=1：负向词物理无效。这条断言是「别把无效当修好」。"""
    C = _client()
    base = json.loads((COMFY / "workflow_qwen21_t2i_hq.json").read_text(encoding="utf-8"))
    assert C._min_cfg(base) == 1
    base9 = json.loads((COMFY / "workflow_qwen21_t2i_hq_9x16.json").read_text(encoding="utf-8"))
    assert C._min_cfg(base9) >= 2, "9x16 那份是 cfg=2，负向才真的生效"
