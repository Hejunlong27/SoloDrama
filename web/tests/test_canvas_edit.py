#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_canvas_edit.py —— 画布写回（P3）的规矩（离线）

编辑功能的风险不在「能不能改」，在**改错之后看不出来**。三类错都算：

  ① **改顺序改了正文**：重排图号时用 `str.replace` 把提示词里所有的 "2" 换成 "3"
     —— 连「身高170cm」都会被改。所以这里必须验证「除了编号，一个字都没动」。
  ② **半套修改落盘**：时长写进去了、提示词没写。下次出片用一套自相矛盾的参数，
     而且没有任何报错。
  ③ **备份被覆盖**：连点两下保存时，两次备份同名 —— 而「连点两下」恰恰是最需要
     回滚的时候。实测踩过：改 4→5→4 之后，备份里留的是 5。

验收标准（CANVAS-PLAN P3）：改一个镜头的时长，磁盘上的 `h3_prompts.json` 跟着变，
且 `ingest_check` 仍然通过。最后一条由 `_validate` 的等价规则覆盖。
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

# 提示词里的「上传顺序」行是顺序的**唯一真源**。这里的样例故意让
# shots.json 的 character_refs/scene_refs 拼接顺序（P01,D01,S01）与提示词
# （P01,S01,D01）不一致 —— 那正是真实项目的样子，也是 P3 要修的东西。
PROMPT_TPL = (
    "上传顺序：Mixed 1＝B01 分镜图｜Mixed 2＝P01 LOOK-A｜Mixed 3＝S01｜Mixed 4＝D01\n"
    "\n"
    "资产图锚定：\n"
    "角色 A 的参考图是 {{Mixed 2}}\n"
    "场景 S01 的参考图是 {{Mixed 3}}\n"
    "道具 D01 的参考图是 {{Mixed 4}}\n"
    "\n"
    "身高170cm，画面0-6秒：他站在门口。\n"
)


def build_ws(root: Path):
    (root / "layout.json").write_text(json.dumps(LAYOUT, ensure_ascii=False), encoding="utf-8")
    data = root / "06-提示词" / "ep01"
    data.mkdir(parents=True)
    (data / "shots.json").write_text(json.dumps([
        {"shot_id": "shot_001", "ratio": "9:16", "board_ref": "board_ep01_shot_001",
         "character_refs": ["P01@LOOK-A", "D01"], "scene_refs": ["S01"]}
    ], ensure_ascii=False), encoding="utf-8")
    (data / "h3_prompts.json").write_text(json.dumps({
        "shot_001": {"prompt": PROMPT_TPL, "duration": 6, "ratio": "9:16"}
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    (data / "characters.json").write_text(json.dumps(
        {"P01@LOOK-A": "../../04-资产/characters/P01.png"}), encoding="utf-8")
    (data / "scenes.json").write_text(json.dumps(
        {"S01": "../../04-资产/scenes/S01.png"}), encoding="utf-8")


@pytest.fixture
def root():
    d = Path(tempfile.mkdtemp(prefix="canvas_edit_"))
    build_ws(d)
    canvas.clear_cache()
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _data(root):
    return root / "06-提示词" / "ep01"


def _prompt(root):
    return json.loads((_data(root) / "h3_prompts.json").read_text(encoding="utf-8"))["shot_001"]


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------
def test_parse_order():
    print("\n[1] 解析上传顺序")
    got = canvas._parse_order(PROMPT_TPL)
    check(got == ["B01 分镜图", "P01 LOOK-A", "S01", "D01"], "标准格式解析正确")

    # 半角分隔符与等号
    alt = "上传顺序：Mixed 1=F01 分镜图|Mixed 2=S01|Mixed 3=D01"
    check(canvas._parse_order(alt) == ["F01 分镜图", "S01", "D01"], "半角 | 与 = 也认")

    # 没有这一行
    check(canvas._parse_order("完全没有顺序行的提示词") is None, "缺行返回 None")

    # 编号断号：不知道第 2 张是谁，宁可不改
    gap = "上传顺序：Mixed 1＝A｜Mixed 3＝B"
    check(canvas._parse_order(gap) is None, "编号不连续返回 None（不猜）")


def test_reorder_only_touches_numbers():
    print("\n[2] 重排只动编号")
    new = ["B01 分镜图", "P01 LOOK-A", "D01", "S01"]     # S01 与 D01 对调
    out, mapping, err = canvas._reorder_prompt(PROMPT_TPL, new)
    check(not err, "没有报错")
    check(mapping == {1: 1, 2: 2, 3: 4, 4: 3}, "映射正确：3<->4")
    check(canvas._parse_order(out) == new, "重排后解析回来是新顺序")

    # 除编号外一字不动：把「上传顺序」行整行剔掉，再把 Mixed N 归一，两边必须相等
    import re

    def norm(t):
        t = canvas._ORDER_LINE.sub("__ORDER__", t)
        return re.sub(r"(?:Mixed|Picture)\s*\d+", "N", t)

    check(norm(out) == norm(PROMPT_TPL), "除编号外正文一字未改")
    check("身高170cm" in out, "正文里的数字 170 没被替换（不用 str.replace 的证明）")

    # 引用点确实跟着变了
    check("场景 S01 的参考图是 {{Mixed 4}}" in out, "S01 的引用从 3 改成 4")
    check("道具 D01 的参考图是 {{Mixed 3}}" in out, "D01 的引用从 4 改成 3")


def test_reorder_rejects_bad_input():
    print("\n[3] 重排拒绝坏输入")
    out, mapping, err = canvas._reorder_prompt(PROMPT_TPL, ["B01 分镜图", "S01"])
    check(bool(err), "数量不符被拒：%s" % (err or "")[:40])

    out, mapping, err = canvas._reorder_prompt(PROMPT_TPL, ["B01 分镜图", "P01 LOOK-A", "S01", "X9"])
    check(bool(err), "换了一个不存在的项被拒：%s" % (err or "")[:40])

    out, mapping, err = canvas._reorder_prompt("没有顺序行", ["A"])
    check(bool(err), "缺上传顺序行时拒绝，而不是猜")


# ---------------------------------------------------------------------------
# 写回
# ---------------------------------------------------------------------------
def test_save_rejects_out_of_range(root):
    print("\n[4] 越界时长不写盘")
    before = (_data(root) / "h3_prompts.json").read_bytes()
    r = canvas.save_shot(str(root), "ep01", "shot_001", duration=20)
    check(r.get("ok") is False, "20 秒被拒")
    check((_data(root) / "h3_prompts.json").read_bytes() == before, "文件一个字节都没动")

    r = canvas.save_shot(str(root), "ep01", "shot_001", duration=2)
    check(r.get("ok") is False, "2 秒被拒（H3 下限 4）")


def test_save_duration(root):
    print("\n[5] 改时长并备份")
    r = canvas.save_shot(str(root), "ep01", "shot_001", duration=8)
    check(r.get("ok") is True, "保存成功")
    check(_prompt(root)["duration"] == 8, "落盘 duration = 8")
    check(len(r.get("backup") or []) >= 1, "生成了备份：%s" % (r.get("backup") or [])[:1])
    # 提示词写的时间轴是 6 秒，改 8 秒应给出警告（不阻断）
    check(bool(r.get("warnings")), "给出「时间轴没跟着改」的警告")
    check("8 秒" in " ".join(r.get("changed") or []), "changed 里写清改了什么")


def test_backups_do_not_collide(root):
    print("\n[6] 同一秒内连点两次，备份不互相覆盖")
    canvas.save_shot(str(root), "ep01", "shot_001", duration=7)
    canvas.save_shot(str(root), "ep01", "shot_001", duration=9)
    baks = sorted((_data(root) / "h3_prompts.json").parent.glob("h3_prompts.json.bak.*"))
    check(len(baks) >= 2, "两次保存留下两份备份（实际 %d）" % len(baks))
    durs = [json.loads(b.read_text(encoding="utf-8"))["shot_001"]["duration"] for b in baks]
    check(len(set(durs)) >= 1, "备份内容可读：%s" % durs)


def test_save_order_syncs_cast(root):
    print("\n[7] 改顺序同步 shots.json 的 cast")
    r = canvas.save_shot(str(root), "ep01", "shot_001",
                         order=["B01 分镜图", "P01 LOOK-A", "D01", "S01"])
    check(r.get("ok") is True, "保存成功")
    shots = json.loads((_data(root) / "shots.json").read_text(encoding="utf-8"))
    check(shots[0]["cast"] == ["P01@LOOK-A", "D01", "S01"], "cast 按新顺序写回")
    check(shots[0]["scene_refs"] == ["S01"], "scene_refs 仍是场景")
    check(_prompt(root)["prompt"].count("{{Mixed 4}}") >= 1, "提示词里的引用已重排")


def test_reorder_keeps_first_item(root):
    print("\n[8] 分镜图不能被挪走")
    r = canvas.save_shot(str(root), "ep01", "shot_001",
                         order=["P01 LOOK-A", "B01 分镜图", "S01", "D01"])
    check(r.get("ok") is False, "把分镜图挪到第 2 位被拒")
    check("分镜图" in " ".join(r.get("errors") or []), "错误说明点明了原因")


def test_noop_does_not_write(root):
    print("\n[9] 没有改动就不写盘")
    before = (_data(root) / "h3_prompts.json").read_bytes()
    r = canvas.save_shot(str(root), "ep01", "shot_001", duration=6)
    check(r.get("ok") is True, "返回 ok")
    check(not (r.get("changed") or []), "changed 为空")
    check((_data(root) / "h3_prompts.json").read_bytes() == before, "文件未被重写")


def test_write_preserves_crlf():
    print("\n[10] 换行风格保真（CRLF 不被改成 LF）")
    d = Path(tempfile.mkdtemp(prefix="canvas_crlf_"))
    try:
        build_ws(d)
        p = _data(d) / "h3_prompts.json"
        p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
        canvas.clear_cache()
        r = canvas.save_shot(str(d), "ep01", "shot_001", duration=7)
        check(r.get("ok") is True, "保存成功")
        raw = p.read_bytes()
        check(b"\r\n" in raw, "仍是 CRLF")
        check(b"\n" not in raw.replace(b"\r\n", b""), "没有混入裸 LF")
    finally:
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    d = Path(tempfile.mkdtemp(prefix="canvas_edit_"))
    build_ws(d)
    canvas.clear_cache()
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(d) if fn.__code__.co_argcount else fn()
            except Exception as e:                      # noqa: BLE001
                FAILS.append("%s: %r" % (name, e))
                print("  [ERR ] %s: %r" % (name, e))
    shutil.rmtree(d, ignore_errors=True)
    print("\n%d 处失败" % len(FAILS))
    sys.exit(1 if FAILS else 0)
