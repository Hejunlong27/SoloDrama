#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_studio_episodes.py —— Studio 的「集/批次/产物」识别口径（离线）

为什么单独一个文件：
  这一组判据决定「后期制作 / 分镜与视频 / 发行中心」三页**有没有东西可显示**。
  它们全部靠扫盘，而真实项目的目录形态比契约稳定得多 —— 出过两次事故：

    ① `batches()` 只认 `^\\d{8}_\\d{6}$` 目录名 **且** 必须有 summary.json。
       而引擎支持 `--batch-id EP01`，真实项目里就是 `07-成片/EP01/shot_001/final.mp4`。
       结果：磁盘上 8 个段都在，三页全显示「还没有集」。
    ② 产物名写死 `_subbed.mp4` / `_master_1080x1920.mp4`，而烧字幕的实际产物是
       `ep01_subbed_1080p.mp4`（烧完再归一化）。于是「字幕明明烧了」显示未生成。

  这两类错**都不报错**，只是页面空着 —— 所以必须用测试钉住。
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

from core import studio   # noqa: E402

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


def build_ws(root: Path):
    """造一个「引擎用 --batch-id EP01 出的片」的项目（没有 summary.json）。"""
    (root / "layout.json").write_text(json.dumps(LAYOUT, ensure_ascii=False), encoding="utf-8")
    for k in ("01-调研", "02-选题", "03-剧本", "04-资产", "05-分镜", "06-提示词",
              "08-合规", "09-发行"):
        (root / k).mkdir(parents=True, exist_ok=True)
    out = root / "07-成片"
    for n in (1, 2, 3):
        d = out / "EP01" / ("shot_%03d" % n)
        d.mkdir(parents=True, exist_ok=True)
        (d / "final.mp4").write_bytes(b"0" * 4096)
    # 只有字幕、没有批次的集（早期出片）
    subs = out / "subs" / "ep02"
    subs.mkdir(parents=True, exist_ok=True)
    (subs / "ep02_subbed_1080p.mp4").write_bytes(b"0" * 4096)
    (subs / "ep02.ass").write_text("dummy", encoding="utf-8")
    # ep01 的母版/放大/字幕（验证产物 glob）
    s1 = out / "subs" / "ep01"
    s1.mkdir(parents=True, exist_ok=True)
    for name in ("ep01_master.mp4", "ep01_master_1080x1920.mp4", "ep01_subbed_1080p.mp4"):
        (s1 / name).write_bytes(b"0" * 4096)
    (s1 / "ep01.ass").write_text("dummy", encoding="utf-8")


@pytest.fixture
def root():
    """造一个临时工作区并交给用例。

    ★ 2026-11-02：这个 fixture 此前**不存在** —— 两个用例签名写着 `root`，
      于是每次跑都 `fixture 'root' not found`，而 `-k` 过滤时看起来像「没有这组测试」。
      一个永远 ERROR 的用例比没有用例更糟：它给人「有覆盖」的错觉。
    """
    d = Path(tempfile.mkdtemp(prefix="studio_ep_"))
    build_ws(d)
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_batches_by_content(root):
    print("\n[1] 批次按内容识别（不靠目录名 + summary.json）")
    bl = studio.batches(str(root))
    names = [b["batch"] for b in bl]
    check("EP01" in names, "EP01 被认成批次：%s" % names)
    b = next((x for x in bl if x["batch"] == "EP01"), {})
    check(b.get("ep") == "ep01", "目录名归一成集号 ep01，实际 %r" % b.get("ep"))
    check(b.get("segments") == 3, "扫到 3 个段，实际 %r" % b.get("segments"))
    check(b.get("synthetic") is True, "没有 summary.json 时标 synthetic")
    check((b.get("totals") or {}).get("ok") == 3, "totals 现场数出来：%r" % b.get("totals"))
    check("subs" not in names and "_gen" not in names, "subs/_gen 不被当批次：%s" % names)


def test_shots_and_episodes(root):
    print("\n[2] 逐镜状态与集列表")
    sh = studio.shots(str(root))
    check(len(sh["items"]) == 3, "逐镜 3 条，实际 %d" % len(sh["items"]))
    check(all(s["shot_id"].startswith("ep01_") for s in sh["items"]),
          "无集前缀的 shot 目录要补上集号：%s" % [s["shot_id"] for s in sh["items"]])
    eps = studio.episodes(str(root))
    got = {e["ep"]: e for e in eps}
    check(set(got) >= {"ep01", "ep02"}, "集列表含 ep01 与 ep02：%s" % sorted(got))
    check(got["ep01"]["master"].endswith("ep01_master.mp4"), "ep01 识别到母版")
    check(got["ep01"]["upscaled"].endswith("ep01_master_1080x1920.mp4"), "ep01 识别到放大件")
    check(got["ep01"]["subbed"].endswith("ep01_subbed_1080p.mp4"),
          "ep01 识别到 _subbed_1080p.mp4（不是写死的 _subbed.mp4）")
    check(got["ep02"]["subbed"].endswith("ep02_subbed_1080p.mp4"), "ep02 只有字幕也要列出来")
    check(got["ep02"]["state"] == "done", "只有字幕的集状态为 done，实际 %r" % got["ep02"]["state"])


def test_ep_name():
    print("\n[3] 目录名 → 集号")
    for raw, want in (("EP01", "ep01"), ("ep1", "ep01"), ("ep_01", "ep01"),
                      ("01", "ep01"), ("20261101_210000", ""), ("_gen", "")):
        got = studio._ep_from_name(raw)
        check(got == want, "%r → %r（期望 %r）" % (raw, got, want))


def main():
    tmp = Path(tempfile.mkdtemp(prefix="studio_ep_"))
    try:
        build_ws(tmp)
        test_batches_by_content(tmp)
        test_shots_and_episodes(tmp)
        test_ep_name()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("-" * 60)
    if FAILS:
        print("[FAIL] %d 项未通过" % len(FAILS))
        return 1
    print("[OK] Studio 集/批次/产物识别全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
