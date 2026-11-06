#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_h3_prompt.py —— 视频提示词「必须是 H3 多参六段式」的判据

这套用例守的是一件事：**参考图必须被点名**。

2026-11-06 的实测结论：老格式把图号写成 `{{Mixed 2}}`，H3 不认识这个写法，
于是它被当成正文读进去 —— 参考图是上传了，但模型不知道哪张图是谁，
人物一集一个样。判据的价值不在「格式好看」，而在这条绑定关系不能断。

用例分四组：
  A 正常与归一化（合法样例 0 错；`{{Mixed n}}` 会被机械换成 `<Picture n>`）
  B 结构阻断（缺段 / 顺序 / `<Video N>` / 任务类型前缀）
  C 标签阻断（Subject 缺失、图号悬空或空号、retention 缺行或缺标记词）
  D 质量告警（正文过短、缺 [Shot 1]、时间越界、缺 (Sx)、配乐留空）
"""
from __future__ import annotations

import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import h3_prompt as H                                              # noqa: E402


def good() -> str:
    """一条合规样例：2 个人物 + 1 个场景，2 个镜内切点，1 句台词。"""
    return """subject_definitions:
<Picture 1> 是本镜分镜图（首帧构图锚点）：中景，何暖居左、靳衍居右，合约在桌面中央。
<Subject 1> 是 <Picture 2> 中的何暖：二十七八岁，黑色低马尾，炭灰西装外套。
<Subject 2> 是 <Picture 3> 中的靳衍：三十岁上下，深灰三件套，袖口银色腕表。
<Subject 3> 是 <Picture 4> 中的会议室：玻璃幕墙、深色长桌、冷白顶灯。

summary:
[reference generation] 目标视频呈现 <Subject 1> 把合约推到 <Subject 2> 面前的一拍，参考图提供两人形象与 <Subject 3> 的空间结构。

retention_analysis:
<Subject 1>（出现于 [Shot 1]）：fully_preserved - 保留低马尾、炭灰西装与面部。
<Subject 2>（出现于 [Shot 1]）：fully_preserved - 保留深灰三件套与银色腕表。
<Subject 3>（出现于 [Shot 1]）：fully_preserved - 保留幕墙、长桌与顶灯。
<Picture 1>（[Shot 1] 首帧）：partially_preserved - 保留机位与左右站位。

detailed_description:
目标视频为冷调写实的现代职场质感：玻璃幕墙把窗外的天光折成条状高光，冷白顶灯压住整体色温，画面低饱和偏灰蓝，暗部保留细节，镜头语言克制，不使用炫技运镜。
[Shot 1] 中景，平视机位，<Subject 1> 坐在长桌左侧，右手把合约沿桌面推向对面，指尖在纸角停住；<Subject 2> 坐在右侧，身体略前倾，垂眼看向封面，左手搭在桌沿。镜头固定，带极轻微的手持呼吸感，背景的幕墙反光缓慢移动。<Subject 1>（S1）说：<d>[Chinese] 一年，互不干涉。</d>
[Shot 2] At 00:05.000，镜头沿桌面缓推到两人之间，景别收到近景，<Subject 2> 抬眼看向她，右手食指在桌面轻敲两下，指节与木面接触时停顿半拍。

overall_soundscape:
空调低鸣，纸张在桌面摩擦的沙沙声，椅脚轻响。

non_diegetic_music:
N/A
"""


def codes(items) -> set:
    return {c[1] for c in items}


# --------------------------------------------------------------------------- A
def test_good_prompt_is_clean():
    err, warn = H.lint(good(), duration=12, n_cast=3)
    assert not err and not warn, "合规样例不该报任何问题：%s" % (err + warn)


def test_sections_parsed_in_order():
    sec, order, dup = H.split_sections(good())
    assert order == list(H.SECTIONS), order
    assert not dup
    assert sec["summary"].startswith("[reference generation]")


def test_placeholder_normalised_to_picture_label():
    """`{{Mixed 2}}` 是我们自己的历史占位符，H3 不认 —— 必须机械换成 `<Picture 2>`。"""
    raw = good().replace("<Picture 2>", "{{Mixed 2}}")
    out = H.normalize(raw)
    assert "{{Mixed" not in out
    assert "<Picture 2>" in out
    err, _warn = H.lint(raw, duration=12, n_cast=3)
    assert not err, "归一化之后不该再报占位符：%s" % err


def test_normalize_is_idempotent_and_drops_upload_order_line():
    raw = "上传顺序：Mixed 1＝shot_001 分镜图｜Mixed 2＝P01\n" + good()
    once = H.normalize(raw)
    assert "上传顺序" not in once, "这行会被画进画面，必须删掉"
    assert H.normalize(once) == once


def test_legacy_prompt_is_rejected_with_actionable_codes():
    legacy = (
        "上传顺序：Mixed 1＝shot_001 分镜图｜Mixed 2＝P01\n\n"
        "资产图锚定：\n角色 何暖 的参考图是 {{Mixed 2}}\n\n"
        "0-4秒：\n画面：中景。何暖把合约放到桌上。\n约束：何暖闭口。\n"
    )
    err, warn = H.lint(legacy, duration=10, n_cast=1)
    assert "H3-E01" in codes(err) and "H3-E05" in codes(err), err
    # 段都不存在时不再叠质量告警：E01 已经说明问题了，多报只会淹掉真因
    assert not warn, warn


# --------------------------------------------------------------------------- B
def test_missing_section_blocks():
    raw = good().replace("overall_soundscape:\n空调低鸣，纸张在桌面摩擦的沙沙声，椅脚轻响。\n\n", "")
    err, _warn = H.lint(raw)
    assert "H3-E01" in codes(err)
    assert any("overall_soundscape" in m for _b, _c, m in err)


def test_wrong_section_order_blocks():
    raw = good()
    raw = raw.replace("summary:", "@@TMP@@:").replace("retention_analysis:", "summary:")
    raw = raw.replace("@@TMP@@:", "retention_analysis:")
    err, _warn = H.lint(raw)
    assert "H3-E01" in codes(err)
    assert any("顺序" in m for _b, _c, m in err)


def test_video_label_blocks():
    raw = good().replace("<Picture 1> 是本镜分镜图", "<Video 1> 是本镜的源视频；<Picture 1> 是本镜分镜图")
    err, _warn = H.lint(raw)
    assert "H3-E03" in codes(err)


def test_summary_requires_known_task_type():
    raw = good().replace("[reference generation]", "[magic]")
    err, _warn = H.lint(raw)
    assert "H3-E04" in codes(err)

    raw2 = good().replace("[reference generation] ", "")
    err2, _warn2 = H.lint(raw2)
    assert "H3-E04" in codes(err2)


# --------------------------------------------------------------------------- C
def test_no_subject_definition_blocks():
    """没有 `<Subject n>` = 参考图没署名，这是最要命的一条。"""
    raw = "\n".join(l for l in good().splitlines()
                    if not l.startswith("<Subject"))
    err, _warn = H.lint(raw, duration=12, n_cast=3)
    assert "H3-E05" in codes(err)


def test_subject_without_picture_blocks():
    raw = good().replace("<Subject 1> 是 <Picture 2> 中的何暖", "<Subject 1> 是何暖")
    err, _warn = H.lint(raw, duration=12, n_cast=3)
    assert "H3-E06" in codes(err)


def test_picture_gap_blocks():
    """图号必须从 1 起连续：空号会让后面每张参考图错位。"""
    raw = good().replace("<Picture 4>", "<Picture 6>").replace("<Picture 3>", "<Picture 4>")
    err, _warn = H.lint(raw, duration=12, n_cast=4)
    assert "H3-E06" in codes(err)
    assert any("空号" in m for _b, _c, m in err)


def test_picture_beyond_cast_blocks():
    raw = good()
    err, _warn = H.lint(raw, duration=12, n_cast=1)          # 只挂了 1 张图，却点到 4 号
    assert "H3-E06" in codes(err)


def test_retention_missing_row_blocks():
    raw = "\n".join(l for l in good().splitlines() if not l.startswith("<Subject 2>（"))
    err, _warn = H.lint(raw, duration=12, n_cast=3)
    assert "H3-E07" in codes(err)


def test_retention_marker_must_be_from_enum():
    raw = good().replace("fully_preserved - 保留低马尾", "mostly_kept - 保留低马尾")
    err, _warn = H.lint(raw, duration=12, n_cast=3)
    assert "H3-E07" in codes(err)


# --------------------------------------------------------------------------- D
def test_short_body_warns_only():
    """正文写成提纲 → 只告警，不阻断：写得薄仍能出片，只是不像。"""
    head, sep, rest = good().partition("detailed_description:")
    _body, sep2, tail = rest.partition("\n\noverall_soundscape:")
    raw = (head + sep + "\n写实质感，冷调。\n"
           "[Shot 1] 中景，<Subject 1> 推合约。\n"
           "[Shot 2] At 00:05.000，<Subject 2> 抬眼。" + sep2 + tail)
    err, warn = H.lint(raw, duration=12, n_cast=3)
    assert not err, err
    assert "H3-W04" in codes(warn)


def test_missing_shot1_warns():
    raw = good().replace("[Shot 1] ", "").replace("[Shot 2] ", "")
    _err, warn = H.lint(raw, duration=12, n_cast=3)
    assert "H3-W01" in codes(warn)


def test_shot_without_timestamp_warns():
    raw = good().replace("[Shot 2] At 00:05.000，", "[Shot 2] ")
    _err, warn = H.lint(raw, duration=12, n_cast=3)
    assert "H3-W02" in codes(warn)


def test_timestamp_beyond_duration_warns():
    raw = good().replace("At 00:05.000", "At 00:20.000")
    _err, warn = H.lint(raw, duration=12, n_cast=3)
    assert "H3-W06" in codes(warn)


def test_dialogue_needs_speaker_id_and_closing_punctuation():
    raw = good().replace("<Subject 1>（S1）说：", "<Subject 1> 说：").replace(
        "<d>[Chinese] 一年，互不干涉。</d>", "<d>[Chinese] 一年，互不干涉</d>")
    _err, warn = H.lint(raw, duration=12, n_cast=3)
    assert "H3-W05" in codes(warn)
    assert "H3-W03" in codes(warn)


def test_empty_music_warns():
    raw = good().replace("non_diegetic_music:\nN/A", "non_diegetic_music:")
    _err, warn = H.lint(raw, duration=12, n_cast=3)
    assert "H3-W07" in codes(warn)


def test_summary_line_buckets():
    assert H.summary_line([]) == "OK"
    assert H.summary_line([("struct", "x", ""), ("label", "y", ""), ("quality", "z", ""),
                           ("quality", "w", "")]) == "结构1 / 标签1 / 质量2"


# ---------------------------------------------------------------------------
# 与门禁的接线：结构错必须阻断，质量项只许告警
# ---------------------------------------------------------------------------
def test_gate_blocks_and_warns_through_pack_spec(tmp_path):
    import json
    import shutil

    import pack_spec as S

    src = HERE / "fixtures" / "mini_pack"
    dst = tmp_path / "pack"
    shutil.copytree(src, dst)
    ep = dst / "episodes" / "ep01.json"
    doc = json.loads(ep.read_text(encoding="utf-8"))

    # 删掉六段里的两段 → 必须阻断（SHOT019）
    doc["shots"][1]["video_prompt"] = "\n\n".join(
        doc["shots"][1]["video_prompt"].split("\n\n")[:2])
    ep.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    _p, _a, _e, rep = S.load_pack(dst)
    assert not rep.ok
    assert "SHOT019" in {x["code"] for x in rep.errors}, rep.render()

    # 结构完整、只是配乐留空 → 只告警（SHOT021），不阻断。
    # 用「留空」而不是「正文写短」：夹具本身就不长，后者会假通过。
    doc = json.loads((src / "episodes" / "ep01.json").read_text(encoding="utf-8"))
    doc["shots"][1]["video_prompt"] = doc["shots"][1]["video_prompt"].replace(
        "non_diegetic_music:\nN/A", "non_diegetic_music:")
    ep.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    _p, _a, _e, rep2 = S.load_pack(dst)
    assert rep2.ok, rep2.render()
    assert any(x["code"] == "SHOT021" and "non_diegetic_music" in x["msg"]
               for x in rep2.warnings), rep2.render()
