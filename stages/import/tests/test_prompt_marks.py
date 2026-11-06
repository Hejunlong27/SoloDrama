#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_prompt_marks.py —— 台词标记 `<d>[语种] …</d>` 的判据与兜底

守的是 2026-11-06 实测出来的那条硬事实：

    裸写在引号里的中文，H3 会当成「画面中应当出现的文字」，**直接烧成画面字幕**；
    出片后无法去除，只能重跑。改成 `<d>[Chinese] …</d>`（语音事件）就不烧。

所以这里三条最硬：

1. **幂等**：二次转换不能变成 `<d><d>` —— 转换器可能被重复跑（`--only` 单跑、断点续跑）。
2. **只动提示词，不动 dialogue**：`dialogue[].text` 是字幕对齐用的纯文本，
   套上标记会让字幕里出现 `<d>[Chinese]`（见 `test_md2pack` 的对应用例）。
3. **宁少改不多改**：招牌/标语里的引号中文（`招牌写着："营业中"`）**不自动包** ——
   把它改成台词是另一种错。这类只由门禁告警，交给人判断。
"""
from __future__ import annotations

import json
import pathlib
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import pack_spec as S      # noqa: E402
import prompt_marks as PM  # noqa: E402

FIXTURE = HERE / "fixtures" / "mini_pack"


# ---------------------------------------------------------------------------
# [A] 归一化：两种高置信写法
# ---------------------------------------------------------------------------
def test_wraps_speech_verb_quote():
    out, n = PM.normalize_dialogue('画面：中景。何暖把合同放到桌上，说："一年，互不干涉。"')
    assert n == 1, out
    assert "<d>[Chinese] 一年，互不干涉。</d>" in out, out
    assert '"' not in out, out


def test_wraps_lipsync_bare_form():
    """旧模板教出来的写法：`时小满口型对齐台词"…"`。"""
    out, n = PM.normalize_dialogue('约束：时小满口型对齐台词"这个箱子周三之前不许开"；周叙闭口。')
    assert n == 1, out
    assert "时小满 说：<d>[Chinese] 这个箱子周三之前不许开。</d>" in out, out
    assert "周叙闭口" in out, "只改台词，不动同段的其他约束"


def test_adds_sentence_end_when_missing():
    out, n = PM.normalize_dialogue('画面：他说："走"')
    assert n == 1
    assert "<d>[Chinese] 走。</d>" in out, out


def test_keeps_existing_sentence_end():
    for tail in ("？", "！", "…"):
        out, _ = PM.normalize_dialogue('画面：他问："还来%s"' % tail)
        assert "还来%s</d>" % tail in out, out


def test_lang_is_configurable():
    out, _ = PM.normalize_dialogue('画面：他说："Vamos."', lang="Spanish")
    assert "<d>[Spanish] Vamos.</d>" in out, out


# ---------------------------------------------------------------------------
# [B] 幂等与「不误改」
# ---------------------------------------------------------------------------
def test_idempotent():
    src = '画面：周然笑着说："念念，这件真好看。"许念说："这婚，我不结了。"'
    once, n1 = PM.normalize_dialogue(src)
    twice, n2 = PM.normalize_dialogue(once)
    assert n1 == 2 and n2 == 0, (n1, n2, once)
    assert twice == once, twice


def test_does_not_double_wrap_existing_mark():
    src = "画面：何暖说：<d>[Chinese] 一年，互不干涉。</d>"
    out, n = PM.normalize_dialogue(src)
    assert n == 0 and out == src, out
    assert out.count("<d>") == 1, out


def test_sign_text_not_auto_wrapped_but_flagged():
    """招牌/标语是「后期合成」范畴，自动改成台词会更错 —— 只报不改。"""
    src = '画面：招牌写着："营业中"，陈默推门进来。'
    out, n = PM.normalize_dialogue(src)
    assert n == 0 and out == src, out
    assert PM.find_bare(out), "至少要让门禁看见它"


def test_find_bare_ignores_marked_and_english():
    assert PM.find_bare("画面：何暖说：<d>[Chinese] 一年。</d>") == []
    assert PM.find_bare('sign reading "EXIT"') == []
    assert PM.find_bare('约束：口型对齐台词"不许开"'), "裸引号中文必须报"


# ---------------------------------------------------------------------------
# [C] 门禁 SHOT018：只告警，不阻断
# ---------------------------------------------------------------------------
def _copy_pack(tmp_path) -> pathlib.Path:
    dst = tmp_path / "pack"
    shutil.copytree(FIXTURE, dst)
    return dst


def test_gate_warns_but_does_not_block(tmp_path):
    p = _copy_pack(tmp_path)
    ep = p / "episodes" / "ep01.json"
    doc = json.loads(ep.read_text(encoding="utf-8"))
    doc["shots"][0]["video_prompt"] += '\n画面：何暖说："一年，互不干涉。"'
    ep.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    _pack, _assets, _eps, rep = S.load_pack(p)
    assert rep.ok, "裸引号台词只是写法风险，不该阻断导入：\n%s" % rep.render()
    assert "SHOT018" in {w["code"] for w in rep.warnings}, rep.render()


def test_gate_silent_when_marked(tmp_path):
    p = _copy_pack(tmp_path)
    ep = p / "episodes" / "ep01.json"
    doc = json.loads(ep.read_text(encoding="utf-8"))
    doc["shots"][0]["video_prompt"] += "\n画面：何暖说：<d>[Chinese] 一年，互不干涉。</d>"
    ep.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    _pack, _assets, _eps, rep = S.load_pack(p)
    assert "SHOT018" not in {w["code"] for w in rep.warnings}, rep.render()


# ---------------------------------------------------------------------------
# [D] 老项目迁移 CLI
# ---------------------------------------------------------------------------
def test_migrate_rewrites_h3_prompts_with_backup(tmp_path):
    ws = tmp_path / "proj"
    d = ws / "06-提示词" / "ep01"
    d.mkdir(parents=True)
    hp = d / "h3_prompts.json"
    hp.write_text(json.dumps({
        "shot_001": {"prompt": '画面：何暖说："一年，互不干涉。"', "duration": 6},
        "shot_002": {"prompt": "画面：何暖沉默。", "duration": 6},
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    dry = PM.migrate(ws)
    assert dry["wrapped"] == 1 and not dry["backups"], dry
    before = json.loads(hp.read_text(encoding="utf-8"))
    assert before["shot_001"]["prompt"] == '画面：何暖说："一年，互不干涉。"', "干跑不许写盘"

    res = PM.migrate(ws, apply=True)
    assert res["wrapped"] == 1 and len(res["backups"]) == 1, res
    doc = json.loads(hp.read_text(encoding="utf-8"))
    assert "<d>[Chinese] 一年，互不干涉。</d>" in doc["shot_001"]["prompt"], doc
    assert doc["shot_002"]["prompt"] == "画面：何暖沉默。", "没有台词的镜不该被动"
    assert pathlib.Path(res["backups"][0]).is_file(), "必须先落 .bak 再写回"
