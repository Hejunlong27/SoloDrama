#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_graph.py —— 节点画布的图结构与布局口径（离线）

这张图最重要的不是好看，是**不能骗人**。三类错都会让人做错决定：

  ① 状态取门禁而不是磁盘：真实项目常常是人工跑出来的（没有 `_done/*.json` 标记），
     按门禁画会整片红，人会以为片子没做，然后从头再跑一遍（几小时 GPU）。
  ② 让用户删依赖边：删掉「分镜图 → 出片」之后，出片照样会跑，只是白烧 GPU。
  ③ 自由连线改变执行顺序：画布上连一条就改执行，等于把「顺序错了 10 分钟后才发现」的坑挖回来。

所以这里钉的是：状态口径、依赖边锁定、自由边只表达意图。
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

from core import graph   # noqa: E402

FAILS = []


def check(cond, msg):
    if cond:
        print("  [PASS] " + msg)
    else:
        print("  [FAIL] " + msg)
        FAILS.append(msg)


LAYOUT = {
    "layout_version": 1, "engine_root": "video-pipeline",
    "stages": {"script": "03-剧本", "assets": "04-资产", "storyboard": "05-分镜",
               "prompts": "06-提示词", "film": "07-成片", "compliance": "08-合规",
               "release": "09-发行"},
    "data_rel": "../06-提示词", "out_rel": "../07-成片", "assets_rel": "../04-资产",
}


def build_ws(root: Path):
    """一个「人工跑完一半」的项目：有镜、有分镜图、有片段，但没有 `_done` 标记。"""
    (root / "layout.json").write_text(json.dumps(LAYOUT, ensure_ascii=False), encoding="utf-8")
    (root / "drama.json").write_text(json.dumps(
        {"format": {"track": "live_action", "look": "look_a", "aspect": "9:16"},
         "episodes": {"count": 2, "seconds": 60}}, ensure_ascii=False), encoding="utf-8")
    d = root / "06-提示词" / "ep01"
    d.mkdir(parents=True)
    shots = [{"shot_id": "shot_%03d" % i, "ratio": "9:16", "board_ref": "b%d" % i, "cast": []}
             for i in range(1, 4)]
    (d / "shots.json").write_text(json.dumps(shots), encoding="utf-8")
    (d / "h3_prompts.json").write_text(json.dumps(
        {"shot_%03d" % i: {"prompt": "p", "duration": 5} for i in range(1, 4)}), encoding="utf-8")
    b = root / "04-资产" / "boards" / "ep01"
    b.mkdir(parents=True)
    for i in range(1, 4):
        (b / ("shot_%03d.png" % i)).write_bytes(b"png")
    # 段落在旧输出目录（迁移期常见），不是布局里的 07-成片
    for i in range(1, 3):
        sd = root / "video-pipeline" / "output" / "20261101_000000" / ("shot_%03d" % i)
        sd.mkdir(parents=True)
        (sd / "final.mp4").write_bytes(b"0" * 4096)
    # 整集母版/字幕用 `_final` / `_sub` 命名（早期人工跑的写法）
    out = root / "07-成片"
    out.mkdir(parents=True)
    (out / "ep01_final.mp4").write_bytes(b"0" * 4096)
    (out / "ep01_sub.mp4").write_bytes(b"0" * 4096)
    (root / "pack").mkdir()


@pytest.fixture
def root():
    d = Path(tempfile.mkdtemp(prefix="graph_"))
    build_ws(d)
    graph.clear_cache()
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_nodes_and_state(root):
    print("\n[1] 节点与状态（只认磁盘）")
    g = graph.state(str(root), "ep01")
    check(g["ok"] is True, "graph 返回 ok")
    ids = [n["id"] for n in g["nodes"]]
    for want in ("skill", "idea", "plan", "board.frame", "video.batch", "edit.release"):
        check(want in ids, "节点包含 %s" % want)
    by = {n["id"]: n for n in g["nodes"]}
    check(by["board.frame"]["progress"] == {"done": 3, "total": 3}, "分镜图 3/3")
    check(by["board.frame"]["state"] == "done", "分镜图产物齐 → 状态 done（不看门禁）")
    check(by["board.frame"]["gate_ok"] is False, "门禁仍是 blocked（两件事分开显示）")
    check(by["video.batch"]["progress"] == {"done": 2, "total": 3}, "出片 2/3（读旧 output 目录）")
    check(by["edit.master"]["state"] == "done", "`ep01_final.mp4` 也算母版")
    check(by["edit.subtitle"]["state"] == "done", "`ep01_sub.mp4` 也算字幕成片")
    check(by["board.frame"]["kind"] == "board", "分镜图是独立节点类型")
    check(by["board.frame"]["cmd"] == "board.frame", "分镜图节点有可运行命令")


def test_edges_locked(root):
    print("\n[2] 依赖边锁定 / 自由边可加")
    g = graph.state(str(root), "ep01")
    deps = [(e["from"], e["to"]) for e in g["edges"] if e["kind"] == "dep"]
    check(("board.frame", "import.gate") in deps, "分镜图 → 入门口禁 是依赖边")
    check(("import.pack", "asset.render") in deps, "导入 → 资产 是依赖边")
    check(all(e["locked"] for e in g["edges"] if e["kind"] == "dep"), "依赖边全部 locked")
    r = graph.remove_edge(str(root), "board.frame", "import.gate", locked=True)
    check(r["ok"] is False and r.get("locked"), "删依赖边被拒，并说明原因")
    r2 = graph.add_edge(str(root), "skill", "script")
    check(r2["ok"] is True, "自由边能加")
    g2 = graph.state(str(root), "ep01")
    check(("skill", "script") in [(e["from"], e["to"]) for e in g2["edges"]], "自由边出现在图里")
    check(any(e["kind"] == "user" for e in g2["edges"]), "自由边标 kind=user（虚线）")


def test_layout_persist(root):
    print("\n[3] 布局落盘")
    r = graph.save_layout(str(root), pos={"board.frame": {"x": 900, "y": 120}},
                          view={"x": 30, "y": 20, "scale": 0.9})
    check(r["ok"] and r["pos_count"] == 1, "保存 1 个坐标")
    f = root / "canvas.json"
    check(f.is_file(), "canvas.json 落在工作区（换机器位置还在）")
    g = graph.state(str(root), "ep01")
    b = next(n for n in g["nodes"] if n["id"] == "board.frame")
    check((b["x"], b["y"]) == (900, 120), "读回来是保存的坐标")
    check(g["view"]["scale"] == 0.9, "视口也存了")
    r2 = graph.save_layout(str(root), view={"scale": 99})
    check(r2["view"]["scale"] == 2.0, "缩放被夹在 0.35–2.0")
    graph.reset_layout(str(root))
    check(not f.exists(), "重置会删掉 canvas.json")
    g3 = graph.state(str(root), "ep01")
    b3 = next(n for n in g3["nodes"] if n["id"] == "board.frame")
    check((b3["x"], b3["y"]) != (900, 120), "重置后回到自动排布")


def test_bad_edges(root):
    print("\n[4] 坏连线")
    check(graph.add_edge(str(root), "a", "a")["ok"] is False, "自环被拒")
    check(graph.add_edge(str(root), "", "plan")["ok"] is False, "空端点被拒")
    g = graph.state(str(root), "ep01")
    check(len([e for e in g["edges"] if e["from"] == "not-exist"]) == 0,
          "不存在的节点不会凭空长出边")


def main():
    tmp = Path(tempfile.mkdtemp(prefix="graph_"))
    try:
        build_ws(tmp)
        graph.clear_cache()
        test_nodes_and_state(tmp)
        test_edges_locked(tmp)
        test_layout_persist(tmp)
        test_bad_edges(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("-" * 60)
    if FAILS:
        print("[FAIL] %d 项未通过" % len(FAILS))
        return 1
    print("[OK] 节点画布口径全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
