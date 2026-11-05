#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_assets_manifest.py —— 资产产物清单必须是「累计事实」

为什么单独守这一条
------------------
2026-11-05 用本地 ComfyUI 实跑时抓到：工具自己打印的建议就是
「建议先只出一张看风格：--only D01」，而出完那一张，项目状态从「24 张」掉成「1 项」——
因为清单是**整份覆盖**的。文件都还在磁盘上，但台账里其余条目消失了。
这类问题的杀伤力在于「看起来正常」：没人会为一个数字变少去查台账，直到发行对不上账。

所以这里钉两条：
1. 单条重跑（`--only`）不得抹掉其它条目；
2. 同一条重跑要**覆盖**旧记录（不能出现两条同 key 的重复），总数不虚增。
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

# 本文件在 stages/production/scripts/tests/ 下 → parents[1] 就是 scripts 目录
PROD = Path(__file__).resolve().parents[1]


def _load():
    # 该模块在导入期就解析工作区（`_ws`），没有 layout.json 会直接 SystemExit ——
    # 这里给一个临时工作区，测的是清单合并，不依赖真实项目。
    _ws = Path(tempfile.mkdtemp(prefix="assetws_"))
    (_ws / "layout.json").write_text("{}", encoding="utf-8")
    os.environ.setdefault("SOLODRAMA_WORKSPACE", str(_ws))
    spec = importlib.util.spec_from_file_location("_gen_assets_ut", str(PROD / "gen_assets_local.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_gen_assets_ut"] = mod
    spec.loader.exec_module(mod)
    return mod


def _item(key, kind="prop", variant="BASE", files=True):
    return {"key": key, "kind": kind, "variant": variant, "name": key,
            "files": ([{"file": "%s.png" % key, "role": "asset"}] if files else [])}


def test_manifest_merges_instead_of_overwriting(tmp_path):
    mod = _load()
    mod.PROD_MANIFEST = tmp_path / "comfyui_assets_manifest.json"

    # 第一次：三张
    mod._write_prod_manifest([_item("D01"), _item("D02"), _item("D03")], {})
    d = json.loads(mod.PROD_MANIFEST.read_text(encoding="utf-8"))
    assert d["totals"]["items"] == 3, d["totals"]

    # 第二次：只跑一张（模拟 --only D01）—— 另外两张不能被抹掉
    mod._write_prod_manifest([_item("D01")], {})
    d = json.loads(mod.PROD_MANIFEST.read_text(encoding="utf-8"))
    keys = [i["key"] for i in d["items"]]
    assert sorted(keys) == ["D01", "D02", "D03"], keys
    assert d["totals"]["items"] == 3


def test_manifest_same_key_overwrites_without_duplicating(tmp_path):
    mod = _load()
    mod.PROD_MANIFEST = tmp_path / "comfyui_assets_manifest.json"

    mod._write_prod_manifest([_item("P01", kind="char", variant="LOOK-A")], {})
    # 同一条重跑：换成本次的文件描述
    newer = _item("P01", kind="char", variant="LOOK-A")
    newer["files"] = [{"file": "P01_new.png", "role": "asset"}]
    mod._write_prod_manifest([newer], {})
    d = json.loads(mod.PROD_MANIFEST.read_text(encoding="utf-8"))
    assert len(d["items"]) == 1, d["items"]
    assert d["items"][0]["files"][0]["file"] == "P01_new.png", "重跑应覆盖旧记录"


def test_manifest_survives_corrupt_file(tmp_path):
    """旧清单坏掉时不能连累本次出图 —— 从空表重建即可。"""
    mod = _load()
    mod.PROD_MANIFEST = tmp_path / "comfyui_assets_manifest.json"
    mod.PROD_MANIFEST.write_text("{ not json", encoding="utf-8")
    mod._write_prod_manifest([_item("D01")], {})
    d = json.loads(mod.PROD_MANIFEST.read_text(encoding="utf-8"))
    assert d["totals"]["items"] == 1
