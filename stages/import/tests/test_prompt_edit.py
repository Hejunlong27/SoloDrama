# -*- coding: utf-8 -*-
"""`stages/import/prompt_edit.py` 的行为测试（夹具式，不碰任何真实项目）。

守的是三条会静默出错的约定：

1. **`shot_001` 每集都有** —— 不给 `--ep` 时必须报 `ambiguous` 并列出候选，
   绝不能默默取第一份（那会把 A 集的词改到 B 集去）。
2. **结构/标签级错误默认拒绝落盘** —— 否则「参考图喂错位」的提示词会被存进工程，
   而出片时只表现为「不像」，没人能追到是哪一次保存引入的。
3. **写之前必须备份、写之后必须复检** —— 提示词是纯文本资产，没有版本控制兜底。
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve()
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / "stages"))
sys.path.insert(0, str(ROOT / "stages" / "import"))

import prompt_edit  # noqa: E402

# 六段的**段头必须独占一行**：`summary: [x]` 这种行内写法会让段体取到空串
# （h3_prompt.split_sections 的实现与它自己的 docstring 不一致，见 test_inline_body_hint）
SIX = """subject_definitions:
<Picture 1> 是本镜分镜图：中景，何暖居左。
<Subject 1> 是 <Picture 2> 中的何暖：二十七八岁，黑色低马尾。

summary:
[reference generation] 参考图提供人物形象与空间结构。

retention_analysis:
<Subject 1>（出现于 [Shot 1]）：fully_preserved - 保留低马尾与面部。
<Picture 1>（[Shot 1] 首帧）：partially_preserved - 保留机位与左右站位。

detailed_description:
[Shot 1] 中景，平视机位，<Subject 1> 坐在长桌左侧，右手把合约沿桌面推向对面。<Subject 1>（S1）说：<d>[Chinese] 一年，互不干涉。</d>

overall_soundscape:
走廊尽头有空调低频嗡鸣。

non_diegetic_music:
N/A
"""

LEGACY = """资产图锚定：
分镜图 的参考图是 {{Mixed 1}}
角色 的参考图是 {{Mixed 2}}
0-4秒：她抬头。
"""


@pytest.fixture()
def ws(tmp_path):
    """一个最小可用工作区：layout.json 的 data_rel 指向 06-提示词（与真实项目同构）。"""
    w = tmp_path / "剧"
    (w / "video-pipeline").mkdir(parents=True)
    (w / "06-提示词" / "ep01").mkdir(parents=True)
    (w / "06-提示词" / "ep02").mkdir(parents=True)
    (w / "layout.json").write_text(json.dumps({
        "layout_version": 2, "engine_root": "video-pipeline",
        "data_rel": "../06-提示词", "out_rel": "../07-成片",
        "stages": {"script": "03-剧本", "assets": "04-资产", "storyboard": "05-分镜",
                   "prompts": "06-提示词", "film": "07-成片",
                   "compliance": "08-合规", "release": "09-发行"},
    }, ensure_ascii=False), encoding="utf-8")
    for ep in ("ep01", "ep02"):
        (w / "06-提示词" / ep / "h3_prompts.json").write_text(json.dumps(
            {"shot_001": {"prompt": LEGACY, "duration": 4, "ratio": "9:16"}},
            ensure_ascii=False, indent=2), encoding="utf-8")
    return w


def _run(capsys, *argv):
    rc = prompt_edit.main(list(argv))
    out = capsys.readouterr().out
    try:
        return rc, json.loads(out)
    except ValueError:
        raise AssertionError("输出不是 JSON：%r" % out[:400])


def _read(capsys, ws, shot="shot_001", ep="ep01"):
    args = ["read", "--workspace", str(ws), "--shot", shot, "--json"]
    if ep:
        args += ["--ep", ep]
    return _run(capsys, *args)


def _text(tmp_path, body):
    p = tmp_path / "candidate.txt"
    p.write_text(body, encoding="utf-8")
    return str(p)


def test_read_resolves_ep_level_file(capsys, ws):
    """修回归：`<ep>` 那一层不能少。少了就永远 no_prompts（这就是线上那个静默 bug）。"""
    rc, d = _read(capsys, ws)
    assert rc == 0 and d["ok"] is True
    assert d["rel"].endswith("06-提示词/ep01/h3_prompts.json")
    assert d["ep"] == "ep01"


def test_ambiguous_without_ep(capsys, ws):
    rc, d = _read(capsys, ws, ep="")
    assert rc == 2 and d["ok"] is False
    assert d["reason"] == "ambiguous"
    assert sorted(d["candidates"]) == ["ep01", "ep02"]


def test_inline_body_hint(capsys, ws):
    """行内段体（`summary: [x]`）会被判缺段 —— 报错必须说清「换行写」，而不是让人去查写没写。"""
    inline = ("subject_definitions: <Subject 1> 女主" + chr(10)
              + "summary: [reference generation]" + chr(10))
    (ws / "06-提示词" / "ep01" / "h3_prompts.json").write_text(
        json.dumps({"shot_001": {"prompt": inline, "duration": 4}}, ensure_ascii=False),
        encoding="utf-8")
    rc, d = _read(capsys, ws)
    keys = [h[0] for h in d.get("inline_hints") or []]
    assert "summary" in keys, "没有指出行内写法这个真实原因：%s" % d.get("inline_hints")


def test_missing_shot(capsys, ws):
    rc, d = _read(capsys, ws, shot="shot_999")
    assert rc == 2 and d["reason"] == "not_found"


def test_read_flags_legacy_prompt(capsys, ws):
    rc, d = _read(capsys, ws)
    assert d["structured"] is False
    assert len(d["missing"]) == 6
    assert d["blocking"], "旧格式（无六段）必须被判为阻断级问题"


def test_save_blocked_by_lint_keeps_file(capsys, ws, tmp_path):
    before = (ws / "06-提示词" / "ep01" / "h3_prompts.json").read_bytes()
    rc, d = _run(capsys, "save", "--workspace", str(ws), "--shot", "shot_001",
                 "--ep", "ep01", "--text-file", _text(tmp_path, LEGACY), "--json")
    assert rc == 3 and d["ok"] is False and d["reason"] == "blocked_by_lint"
    assert (ws / "06-提示词" / "ep01" / "h3_prompts.json").read_bytes() == before


def test_save_force_writes_and_backups(capsys, ws, tmp_path):
    rc, d = _run(capsys, "save", "--workspace", str(ws), "--shot", "shot_001",
                 "--ep", "ep01", "--text-file", _text(tmp_path, SIX), "--json")
    assert rc == 0 and d["ok"] is True and d["changed"] is True
    assert d["backup"].endswith(".bak-" + d["backup"].split(".bak-")[1])
    assert (ws / d["backup"]).is_file(), "备份文件没有真的落盘"

    saved = json.loads((ws / "06-提示词" / "ep01" / "h3_prompts.json").read_text(encoding="utf-8"))
    assert "{{Mixed" not in saved["shot_001"]["prompt"], "占位符没有被归一"
    assert saved["shot_001"]["duration"] == 4, "写回不应改动同镜的其他字段"


def test_save_unchanged_is_noop(capsys, ws, tmp_path):
    (ws / "06-提示词" / "ep01" / "h3_prompts.json").write_text(json.dumps(
        {"shot_001": {"prompt": SIX, "duration": 4}}, ensure_ascii=False), encoding="utf-8")
    rc, d = _run(capsys, "save", "--workspace", str(ws), "--shot", "shot_001",
                 "--ep", "ep01", "--text-file", _text(tmp_path, SIX), "--json")
    assert rc == 0 and d["changed"] is False
    assert not list((ws / "06-提示词" / "ep01").glob("*.bak-*")), "没改动就不该留备份"


def test_bad_shot_rejected(capsys, ws):
    rc, d = _run(capsys, "read", "--workspace", str(ws), "--shot", "../../etc/passwd", "--json")
    assert rc == 2 and d["reason"] == "bad_shot"


def test_bad_ep_rejected(capsys, ws):
    rc, d = _run(capsys, "read", "--workspace", str(ws), "--shot", "shot_001",
                 "--ep", "../x", "--json")
    assert rc == 2 and d["reason"] == "bad_ep"
