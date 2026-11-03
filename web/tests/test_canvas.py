#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_canvas.py —— 剧集画布的格子口径（离线）

这张图的价值全在「格子说的是不是真的」。三类错都会让它变成装饰品：

  ① **状态取错源**：用 `summary.json` 的 `video_status` 而不是磁盘上的段文件 →
     续跑/换批次/人工换过文件之后，格子还停在旧状态，人看着「已完成」去发行，
     结果发行脚本报「缺段」。
  ② **集号轴按已有集生成**：只画有制作包的那几集 → 「30 集里哪 27 集还没动」
     这件事又得回去翻目录，画布等于没做。
  ③ **退化顺序被当成契约**：没有 `shots.json` 时按目录名列举，却仍声称「第 1 镜」
     —— 那个顺序可能跟剧本完全不同。必须标 `no_pack`，让人知道这不是契约给的。
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB))

import pytest  # noqa: E402

from core import canvas   # noqa: E402

FAILS = []


def check(cond, msg):
    if cond:
        print("  [PASS] " + msg)
    else:
        print("  [FAIL] " + msg)
        FAILS.append(msg)


LAYOUT = {
    "layout_version": 1, "engine_root": "video-pipeline",
    "stages": {"research": "01-调研", "topic": "02-选题", "script": "03-剧本",
               "assets": "04-资产", "storyboard": "05-分镜", "prompts": "06-提示词",
               "film": "07-成片", "compliance": "08-合规", "release": "09-发行"},
    "data_rel": "../06-提示词", "out_rel": "../07-成片", "assets_rel": "../04-资产",
}

SHOTS = [
    {"shot_id": "shot_%03d" % i, "ratio": "9:16", "board_ref": "board_ep01_shot_%03d" % i,
     "cast": ["P01", "S01"], "character_refs": ["P01"], "scene_refs": ["S01"]}
    for i in range(1, 9)
]
PROMPTS = {
    "shot_%03d" % i: {"prompt": "[SUBJECT] 第 %d 镜的六段式提示词" % i + "x" * 60,
                      "duration": 6, "ratio": "9:16"}
    for i in range(1, 9)
}


def build_ws(root: Path):
    (root / "layout.json").write_text(json.dumps(LAYOUT, ensure_ascii=False), encoding="utf-8")
    # 目标集数写在 drama.json：画布要按它补齐「还没动的集」
    (root / "drama.json").write_text(json.dumps(
        {"episodes": {"count": 10, "seconds": 60}}), encoding="utf-8")

    data = root / "06-提示词" / "ep01"
    data.mkdir(parents=True)
    (data / "shots.json").write_text(json.dumps(SHOTS, ensure_ascii=False), encoding="utf-8")
    (data / "h3_prompts.json").write_text(json.dumps(PROMPTS, ensure_ascii=False), encoding="utf-8")
    (data / "boards.json").write_text(json.dumps(
        {"shot_001": {"prompt": "构图 A", "ratio": "9:16", "refs": ["P01"]}},
        ensure_ascii=False), encoding="utf-8")
    (data / "characters.json").write_text(json.dumps({"P01": "../../04-资产/refs/P01.png"}),
                                          encoding="utf-8")
    (data / "scenes.json").write_text(json.dumps({}), encoding="utf-8")

    # ep01：8 张分镜图
    b1 = root / "04-资产" / "boards" / "ep01"
    b1.mkdir(parents=True)
    for i in range(1, 9):
        (b1 / ("shot_%03d.png" % i)).write_bytes(b"png")
    # ep02：没有制作包，只有分镜图 + 一个段（考退化分支）
    b2 = root / "04-资产" / "boards" / "ep02"
    b2.mkdir(parents=True)
    for i in (1, 2):
        (b2 / ("shot_%03d.png" % i)).write_bytes(b"png")
    (root / "04-资产" / "refs").mkdir(parents=True)
    (root / "04-资产" / "refs" / "P01.png").write_bytes(b"png")

    out = root / "07-成片" / "20261104_020000"
    # 001–005 用无集前缀的目录名，006 用带集前缀的：两种历史写法都要认
    for i in range(1, 6):
        d = out / ("shot_%03d" % i)
        d.mkdir(parents=True)
        (d / "final.mp4").write_bytes(b"0" * 4096)
    d6 = out / "ep01_shot_006"
    d6.mkdir(parents=True)
    (d6 / "final.mp4").write_bytes(b"0" * 4096)
    # 小于 2KB 的文件不算出片（半截文件）
    d7 = out / "shot_007"
    d7.mkdir(parents=True)
    (d7 / "final.mp4").write_bytes(b"0" * 100)
    # 段落在 <shot>/video/final.mp4（引擎换过目录层级，studio._shot_videos 两种都认）
    d8 = out / "shot_008" / "video"
    d8.mkdir(parents=True)
    (d8 / "final.mp4").write_bytes(b"0" * 4096)

    d2 = root / "07-成片" / "20261104_030000" / "ep02_shot_001"
    d2.mkdir(parents=True)
    (d2 / "final.mp4").write_bytes(b"0" * 4096)

    rel = root / "09-发行" / "剧集"
    rel.mkdir(parents=True)
    (rel / "Episode01.mp4").write_bytes(b"0" * 4096)


@pytest.fixture
def root():
    d = Path(tempfile.mkdtemp(prefix="canvas_"))
    build_ws(d)
    canvas.clear_cache()
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_axis_and_cells(root):
    print("\n[1] 集号轴与格子状态")
    s = canvas.series(str(root))
    check(s["ok"] is True, "series 返回 ok")
    check(len(s["rows"]) == 10, "按 drama.json 的 10 集补齐轴，实际 %d 行" % len(s["rows"]))
    check([r["ep"] for r in s["rows"]][:3] == ["ep01", "ep02", "ep03"], "集号从 ep01 起连续")
    ep1 = s["rows"][0]
    check(ep1["counts"]["total"] == 8, "ep01 8 镜，实际 %r" % ep1["counts"])
    check(ep1["counts"]["done"] == 7, "ep01 出片 7 段（含 ep01_shot_006 与 video/ 子目录），实际 %r" % ep1["counts"]["done"])
    check(ep1["counts"]["board"] == 1, "ep01 只剩 1 镜有分镜图没出片，实际 %r" % ep1["counts"]["board"])
    check(s["axis"] == 8, "横轴 8 列，实际 %r" % s["axis"])
    check(ep1["shots"][6]["state"] == "board", "第 7 镜只有 100 字节的残段 → 不算出片")
    check(ep1["shots"][7]["state"] == "done", "第 8 镜的段在 <shot>/video/final.mp4 也要认")
    check(ep1["shots"][5]["seg"].endswith("ep01_shot_006/final.mp4"), "带集前缀的段目录也能认")
    check(ep1["duration"] == 48.0, "ep01 总时长 48 秒，实际 %r" % ep1["duration"])
    check(ep1["release"] == "Episode01.mp4", "识别到发布版")


def test_no_pack_row(root):
    print("\n[2] 没有制作包的集：退化列举 + 明确标记")
    s = canvas.series(str(root))
    ep2 = s["rows"][1]
    check(ep2["has_pack"] is False, "ep02 标 no_pack")
    check(ep2["counts"]["total"] == 2, "ep02 按分镜图列举出 2 镜，实际 %r" % ep2["counts"])
    check(ep2["counts"]["done"] == 1, "ep02 第 1 镜认出出片段")
    check(ep2["shots"][1]["state"] == "board", "ep02 第 2 镜只有分镜图")
    ep3 = s["rows"][2]
    check(ep3["counts"]["total"] == 0, "ep03 什么都没做 → 0 镜")
    check(ep3["no_pack"] is True, "空集也标 no_pack（不是「已完成 0/0」）")


def test_totals_and_foot(root):
    print("\n[3] 合计与列缺口")
    s = canvas.series(str(root))
    t = s["totals"]
    check(t["episodes"] == 2, "有镜头的集 2 个（ep01 8 镜 + ep02 2 镜），实际 %r" % t["episodes"])
    check(t["shots"] == 10, "总镜数 8+2，实际 %r" % t["shots"])
    check(t["done"] == 8, "总出片 7+1，实际 %r" % t["done"])
    check(t["rows"] == 10, "总行数 10，实际 %r" % t["rows"])
    col1 = s["col_counts"][0]
    check(col1["done"] == 2, "第 1 列两集都出片了，实际 %r" % col1)
    col8 = s["col_counts"][7]
    check(col8["done"] == 1 and col8["board"] == 0, "第 8 列 ep01 已出片、ep02 无此镜，实际 %r" % col8)


def test_shot_detail(root):
    print("\n[4] 单镜详情（四段链）")
    d = canvas.shot(str(root), "ep01", "shot_003")
    check(d["ok"] is True, "读得到 shot_003")
    check(d["n"] == 3, "第 3 镜，实际 %r" % d["n"])
    check(d["prompt"]["duration"] == 6, "时长 6 秒")
    check("第 3 镜" in d["prompt"]["text"], "提示词原文取到")
    check(d["board"]["rel"].endswith("04-资产/boards/ep01/shot_003.png"), "分镜图相对路径")
    check(d["video"]["rel"].endswith("shot_003/final.mp4"), "成片相对路径")
    check(d["video"]["bytes"] == 4096, "成片大小")
    check(len(d["cast"]) == 2 and d["cast"][0]["key"] == "P01", "cast 两路参考图")
    check(d["cast"][0]["rel"].endswith("refs/P01.png"), "参考图路径按三种基准之一解析出来")
    check(d["cast"][1]["rel"] == "", "scenes.json 没登记 S01 → 空（不编路径）")


def test_bad_args(root):
    print("\n[5] 坏参数不抛异常")
    for ep, sid in (("..", "shot_001"), ("ep01", "../x"), ("", "")):
        d = canvas.shot(str(root), ep, sid)
        check(d["ok"] is False, "%r/%r 被拒" % (ep, sid))
    d = canvas.shot(str(root), "ep09", "shot_001")
    check(d["ok"] is False and d["reason"] == "no_pack", "没有制作包时给 no_pack，不是 500")


def main():
    tmp = Path(tempfile.mkdtemp(prefix="canvas_"))
    try:
        build_ws(tmp)
        canvas.clear_cache()
        test_axis_and_cells(tmp)
        test_no_pack_row(tmp)
        test_totals_and_foot(tmp)
        test_shot_detail(tmp)
        test_bad_args(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("-" * 60)
    if FAILS:
        print("[FAIL] %d 项未通过" % len(FAILS))
        return 1
    print("[OK] 剧集画布口径全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
