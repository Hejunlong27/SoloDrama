#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""单变体重出（资产）—— 两条必须守住的边界。

## 一、旧图必须能找回

`comfy_client` 落盘是 `os.replace(tmp, final)`：**直接覆盖、不留旧版**。
整批出图时这没问题（一次跑完整套），但「单张重出」是用来修一张不满意的图的 ——
重出来更难看时，原图已经没了。所以 `--backup` 会在覆盖前把旧图复制到 `_bak/`。

备份名必须带 `.bak` 后缀，这不是洁癖，两处真实后果：

* `_scan_outputs()` 用 `iterdir()` + `startswith(prefix + '_')` 判产物；
* `pack_import._scan_asset_images()` 是 **rglob**，会递归进 `_bak/`。
  若备份还是 `.png`，它的 stem 会被解析成 `P01` + `LOOK-B`，**和真产物抢**参考图。

用 `.bak` 两处天然跳过。下面第 2、3 条测试就是钉这两个点。

## 二、分镜提示词门禁不该阻断资产出图

资产卡天生早于分镜提示词定稿：出资产图时 episodes 里要么还没写提示词、
要么仍是旧格式（`{{Mixed n}}` + 「资产图锚定」）。把 `SHOT019/020` 当阻断，
结果是**本机任何项目都出不了资产图** —— 而它们与资产卡本身毫无关系。

第 4 条测试用一份「资产全对、分镜全错」的夹具钉住：资产照样出，但错误要打出来。
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

PROD = Path(__file__).resolve().parents[1]


def _load():
    """该模块导入期就解析工作区（`_ws`），没有 layout.json 会 SystemExit —— 给个临时工作区。"""
    ws = Path(tempfile.mkdtemp(prefix="regen_ws_"))
    (ws / "layout.json").write_text("{}", encoding="utf-8")
    os.environ.setdefault("SOLODRAMA_WORKSPACE", str(ws))
    spec = importlib.util.spec_from_file_location("_gen_assets_regen", str(PROD / "gen_assets_local.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_gen_assets_regen"] = mod
    spec.loader.exec_module(mod)
    return mod


def _asset(prefix, kind="char"):
    return {"id": prefix.split("_", 1)[0], "kind": kind, "name": "X", "prefix": prefix,
            "section": 1, "prompt": "p", "aspect": "9:16", "code": "LOOK-A"}


# ---------------------------------------------------------------------------
# 一、备份
# ---------------------------------------------------------------------------
def test_backup_writes_bak_suffix_outside_output_match(tmp_path):
    """备份落在 `_bak/` 且后缀是 `.bak` —— 不能被 `iterdir` 的产物判定捞出来。"""
    mod = _load()
    mod.OUT_DIR = tmp_path
    mod.SUBDIR = {"char": "characters"}

    d = tmp_path / "characters"
    d.mkdir()
    old = d / "P01_Elena_LOOK-B_00.png"
    old.write_bytes(b"OLD")

    a = _asset("P01_Elena_LOOK-B")
    saved = mod._backup_existing([a])
    assert len(saved) == 1, saved

    bak = Path(saved[0])
    assert bak.parent.name == "_bak", bak
    assert bak.name.endswith(".bak"), bak.name
    assert bak.read_bytes() == b"OLD", "备份内容与被覆盖前不一致"
    assert old.read_bytes() == b"OLD", "备份不应改动原文件"

    # 关键：`_scan_outputs` 的同款判定不能再把备份认成产物
    hits = [f for f in d.iterdir()
            if f.is_file() and f.suffix.lower() in mod.EXTS
            and (f.name.startswith(a["prefix"] + "_") or f.stem == a["prefix"])]
    assert [h.name for h in hits] == ["P01_Elena_LOOK-B_00.png"], hits


def test_backup_is_recursive_scan_proof(tmp_path):
    """`pack_import._scan_asset_images` 是 rglob 会进 `_bak/` —— 备份必须是不可识别为图的扩展名。"""
    mod = _load()
    mod.OUT_DIR = tmp_path
    mod.SUBDIR = {"char": "characters"}
    d = tmp_path / "characters"
    d.mkdir()
    (d / "P01_Elena_LOOK-B_00.png").write_bytes(b"OLD")
    saved = mod._backup_existing([_asset("P01_Elena_LOOK-B")])

    bak = Path(saved[0])
    # 图片扫描认的扩展名（与 pack_import.IMG_EXT 同集合）
    assert bak.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"), (
        "备份用了图片扩展名，会被 rglob 扫到并抢走参考图：%s" % bak.name)


def test_backup_skips_already_backed_up(tmp_path):
    """二次重出不该把上一次的备份又备份一遍（否则每重出一次多一层垃圾）。"""
    mod = _load()
    mod.OUT_DIR = tmp_path
    mod.SUBDIR = {"char": "characters"}
    d = tmp_path / "characters"
    d.mkdir()
    (d / "P01_Elena_LOOK-B_00.png").write_bytes(b"OLD")
    a = _asset("P01_Elena_LOOK-B")

    first = mod._backup_existing([a])
    second = mod._backup_existing([a])
    assert len(first) == 1 and len(second) == 1, (first, second)
    assert len(list((d / "_bak").iterdir())) == 2, "第二次应新增一份，而不是把备份再复制一遍"


def test_no_backup_when_nothing_would_be_overwritten(tmp_path):
    """首次出图（还没有产物）时不该凭空造出备份目录。"""
    mod = _load()
    mod.OUT_DIR = tmp_path
    mod.SUBDIR = {"char": "characters"}
    (tmp_path / "characters").mkdir()

    assert mod._backup_existing([_asset("P02_X_VIEW")]) == []
    assert not (tmp_path / "characters" / "_bak").exists()


# ---------------------------------------------------------------------------
# 二、分镜级门禁不阻断资产出图
# ---------------------------------------------------------------------------
SIX = """subject_definitions:
<Picture 1> 是本镜分镜图。
<Subject 1> 是 <Picture 2> 中的 Elena：二十七八岁。

summary:
[reference generation] 参考图提供人物形象。

retention_analysis:
<Subject 1>（[Shot 1]）：fully_preserved - 保留低马尾。
<Picture 1>（[Shot 1] 首帧）：partially_preserved - 保留机位。

detailed_description:
[Shot 1] 中景，<Subject 1> 坐在桌前。

overall_soundscape:
空调低频嗡鸣。

non_diegetic_music:
N/A
"""


def _mk_pack(root: Path, video_prompt: str) -> Path:
    """最小制作包：资产卡合规，分镜提示词由参数决定。"""
    pk = root / "pack"
    (pk / "assets").mkdir(parents=True)
    (pk / "episodes").mkdir(parents=True)
    # spec 字面量、字段名都照真实包（`solodrama-pack/1`、`items[]`、`episode`）——
    # 夹具自造一套格式，测的就不是真契约了。
    (pk / "pack.json").write_text(json.dumps({
        "spec": "solodrama-pack/1", "title": "T",
        "style_lock": "cinematic still, 35mm",
        "aspect": {"char": "9:16", "scene": "16:9", "prop": "1:1"},
    }, ensure_ascii=False), encoding="utf-8")
    (pk / "assets" / "characters.json").write_text(json.dumps({
        "spec": "solodrama-assets/1",
        "items": [{"id": "P01", "name": "Elena", "role": "主角", "anchors": [],
                   "variants": [{"code": "LOOK-A", "label": "造型A", "kind": "look",
                                 "prompt": "a woman, grey coat"}]}],
    }, ensure_ascii=False), encoding="utf-8")
    (pk / "assets" / "scenes.json").write_text(
        json.dumps({"spec": "solodrama-assets/1", "items": []}), encoding="utf-8")
    (pk / "assets" / "props.json").write_text(
        json.dumps({"spec": "solodrama-assets/1", "items": []}), encoding="utf-8")
    (pk / "episodes" / "ep01.json").write_text(json.dumps({
        "spec": "solodrama-episode/1", "episode": 1,
        "shots": [{"id": "shot_001", "duration": 4, "ratio": "9:16",
                   "cast": [{"id": "P01", "code": "LOOK-A"}],
                   "video_prompt": video_prompt, "dialogue": ""}],
    }, ensure_ascii=False), encoding="utf-8")
    return pk


def test_shot_lint_does_not_block_asset_render(tmp_path, capsys):
    """分镜提示词不合规（旧格式）时，资产出图仍要能拿到清单。

    这是 2026-11-10 修的一个真实阻断：`assets_from_pack` 原来对 `rep.ok` 全量判断，
    而 30 集旧格式提示词会让 SHOT019/020 全红 —— 于是**本机任何项目都出不了资产图**，
    尽管资产卡本身完全合规。
    """
    mod = _load()
    pk = _mk_pack(tmp_path, "资产图锚定：\n分镜图 的参考图是 {{Mixed 1}}\n")  # 旧格式，必然触发 SHOT019/020

    assets = mod.assets_from_pack(pk)
    assert len(assets) == 1, assets
    assert assets[0]["id"] == "P01@LOOK-A", assets[0]

    out = capsys.readouterr().out
    assert "分镜提示词问题" in out, "绕过了门禁却没说 —— 必须让人知道绕过了什么：\n%s" % out
    assert "SHOT0" in out or "SHOT" in out, out


def test_asset_level_error_still_blocks(tmp_path):
    """资产级错误（style_lock 为空）照旧阻断 —— 放过的只能是分镜级。"""
    mod = _load()
    pk = _mk_pack(tmp_path, SIX)
    (pk / "pack.json").write_text(json.dumps({
        "spec": "solodrama.pack/1", "title": "T", "style_lock": "",
        "aspect": {"char": "9:16"},
    }, ensure_ascii=False), encoding="utf-8")

    try:
        mod.assets_from_pack(pk)
    except SystemExit as exc:
        assert int(exc.code or 0) != 0, "资产级错误必须以非零退出"
        return
    raise AssertionError("style_lock 为空却没被阻断")
