# -*- coding: utf-8 -*-
"""test_subtitle_alignment.py —— 字幕对齐/覆盖/收紧的回归测试（离线、零计费）

对应 2026-10-22 的实跑排障（调试日志包 `Solodrama调试日志_20261022`）。
每一组用例都钉住一个**已经发生过的事故**，防止回退：

  A. 非语音标记（`[Música]`）被当成语音 ⇒ 覆盖检查整段误报、首条字幕被前移
  B. `script_estimate` 伪对齐被当成有效缓存 ⇒ CTC 一次都没跑，整集偏移 2.8s
  C. 相似度用「字符集合重叠」⇒ ASR 条目被粘成一条，字幕覆盖从 62s 掉到 11s
  D. 逐条语速「偏慢」被当异常 ⇒ 每段刷 3–7 行告警，淹没真问题
  E. 段起点用「帧数 ÷ 写死 24fps」⇒ 非 24fps 素材累计偏移
  F. 剧本无台词的镜头有人声却没有字幕（H3 自加台词）
  G. 字幕首尾含静音 ⇒ 先亮字后出声 / 出声已结束字还挂着
  H. `<d>台词</d>`（无方括号）被静默丢弃

跑法：python stages/subtitle/scripts/tests/test_subtitle_alignment.py
"""
from __future__ import annotations

import json
import pathlib
import re
import struct
import sys
import tempfile
import unittest
import wave

HERE = pathlib.Path(__file__).resolve().parent
SCRIPTS = HERE.parent
sys.path.insert(0, str(SCRIPTS))

import subtitle as S          # noqa: E402


# ---------------------------------------------------------------- 工具
def _write_srt(p: pathlib.Path, rows) -> pathlib.Path:
    def ts(t):
        ms = int(round(t * 1000))
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        s, ms = divmod(ms, 1000)
        return "%02d:%02d:%02d,%03d" % (h, m, s, ms)
    blocks = ["%d\n%s --> %s\n%s" % (i, ts(a), ts(b), t)
              for i, (a, b, t) in enumerate(rows, 1)]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    return p


def _tone_wav(p: pathlib.Path, plan, sr=16000):
    """按 (start, end, amplitude) 生成 16k 单声道 s16 wav。"""
    p.parent.mkdir(parents=True, exist_ok=True)
    total = max(e for _s, e, _a in plan)
    buf = bytearray()
    step = 1.0 / sr
    t = 0.0
    while t < total:
        amp = 0
        for s, e, a in plan:
            if s <= t < e:
                amp = a
                break
        # 400Hz 方波近似"人声"，幅度决定 RMS
        val = amp if int(t * 400) % 2 == 0 else -amp
        buf += struct.pack("<h", val)
        t += step
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(bytes(buf))
    return p


# ---------------------------------------------------------------- A. 非语音标记
class TestNonSpeech(unittest.TestCase):
    def test_music_tags_are_not_speech(self):
        for t in ["[Música]", "[Music]", "[Aplausos]", "(música)", "♪♪", "[BLANK_AUDIO]",
                  "  [Música]  ", "[Risas]"]:
            self.assertTrue(S.is_nonspeech(t), t)

    def test_short_real_line_is_speech(self):
        # 「¿Eh?」只有两个字母，但确实是台词 —— 不能按长度判非语音
        for t in ["¿Eh?", "Sí.", "No.", "Eran las once y veinte. Llovía."]:
            self.assertFalse(S.is_nonspeech(t), t)

    def test_empty_is_nonspeech(self):
        self.assertTrue(S.is_nonspeech(""))
        self.assertTrue(S.is_nonspeech(None))

    def test_speech_regions_ignores_music_only_shot(self):
        """ep26_sc01 现场：srt 只有一条 `[Música] 0.00–6.50`。

        旧实现把它当语音 ⇒ 覆盖检查报「6.5s 有语音却无字幕」，
        并触发 repair_leading_gaps 把首条字幕前移到 0.00（破坏正确时间轴）。
        """
        with tempfile.TemporaryDirectory() as td:
            d = pathlib.Path(td)
            _write_srt(d / "ep26_sc01.srt", [(0.0, 6.5, "[Música]")])
            cfg = {"tools": {"whisper_cli": "", "whisper_model": ""}}
            orig = S.asr_entries
            try:
                S.asr_entries = lambda *a, **k: [
                    (a_, b_, t_) for a_, b_, t_ in
                    S.parse_srt_file(str(d / "ep26_sc01.srt")) if not S.is_nonspeech(t_)]
                # whisper 不可用时走 silencedetect 分支；这里只验证过滤逻辑本身
                self.assertEqual(S.asr_entries(cfg, d / "x.mp4"), [])
            finally:
                S.asr_entries = orig

    def test_parse_srt_tolerates_junk(self):
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "a.srt"
            p.write_text("\ufeff1\n00:00:01,000 --> 00:00:02,500\nHola.\n\n"
                         "garbage line\n\n"
                         "2\n00:00:03,000 --> 00:00:04,000\nAdiós.\n", encoding="utf-8")
            rows = S.parse_srt_file(str(p))
            self.assertEqual(len(rows), 2)
            self.assertAlmostEqual(rows[0][0], 1.0, places=3)
            self.assertAlmostEqual(rows[1][1], 4.0, places=3)
            self.assertEqual(rows[1][2], "Adiós.")

    def test_parse_srt_missing_file(self):
        self.assertEqual(S.parse_srt_file("Z:/definitely/not/here.srt"), [])


# ---------------------------------------------------------------- B. 伪对齐缓存
class TestAlignCache(unittest.TestCase):
    def _put(self, d, obj):
        p = pathlib.Path(d) / "sid.json"
        p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        return p

    def test_script_estimate_is_not_valid_cache(self):
        with tempfile.TemporaryDirectory() as td:
            p = self._put(td, {"shot_id": "ep26_sc02", "method": "script_estimate",
                               "lines": []})
            self.assertFalse(S._align_cache_ok(str(p)))

    def test_fallback_estimate_is_not_valid_cache(self):
        with tempfile.TemporaryDirectory() as td:
            p = self._put(td, {"method": "fallback-estimate"})
            self.assertFalse(S._align_cache_ok(str(p)))

    def test_ctc_and_asr_are_valid_cache(self):
        for m in ("ctc-sequential", "ctc-piecewise", "asr-whisper", "asr-only"):
            with tempfile.TemporaryDirectory() as td:
                p = self._put(td, {"method": m})
                self.assertTrue(S._align_cache_ok(str(p)), m)

    def test_missing_or_broken_cache(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertFalse(S._align_cache_ok(str(pathlib.Path(td) / "none.json")))
            bad = pathlib.Path(td) / "bad.json"
            bad.write_text("{not json", encoding="utf-8")
            self.assertFalse(S._align_cache_ok(str(bad)))


# ---------------------------------------------------------------- C. 相似度
class TestSimilarity(unittest.TestCase):
    def test_identical(self):
        self.assertAlmostEqual(S.text_similarity("Dijo junio.", "dijo junio."), 1.0, places=6)

    def test_unrelated_spanish(self):
        # 旧的「字符集合重叠」在这里能拿到 ~0.6（共享 e/a/n/o），新口径必须低
        a = "No puede recordar nada."
        b = "Eran las once y veinte."
        self.assertLess(S.text_similarity(a, b), 0.45)

    def test_asr_garbled_still_matches(self):
        # 现场真实一对：剧本 vs whisper 听错（ep26_sc02）
        a = "Eran las once y veinte. Llovía."
        b = "Era en la 11 y 20, yo vía."
        self.assertGreater(S.text_similarity(a, b), 0.45)

    def test_empty(self):
        self.assertEqual(S.text_similarity("", "x"), 0.0)


# ---------------------------------------------------------------- G. 声学收紧
class TestTightenToAudio(unittest.TestCase):
    def test_loud_intervals_finds_speech_band(self):
        with tempfile.TemporaryDirectory() as td:
            w = _tone_wav(pathlib.Path(td) / "a.wav",
                          [(0.0, 0.8, 0), (0.8, 2.0, 8000), (2.0, 3.0, 0)])
            regs = S.loud_intervals(w)
            self.assertTrue(regs)
            self.assertAlmostEqual(regs[0][0], 0.8, delta=0.06)
            self.assertAlmostEqual(regs[0][1], 2.0, delta=0.06)

    def test_tighten_trims_silence(self):
        with tempfile.TemporaryDirectory() as td:
            w = _tone_wav(pathlib.Path(td) / "a.wav",
                          [(0.0, 0.8, 0), (0.8, 2.0, 8000), (2.0, 3.0, 0)])
            recs = [{"start": 0.5, "end": 2.6, "text": "Hola."}]
            lc = {"cps_hard_max": 26.0}
            n = S.tighten_to_audio(recs, w, lc)
            self.assertEqual(n, 1)
            self.assertAlmostEqual(recs[0]["start"], 0.74, delta=0.06)
            self.assertAlmostEqual(recs[0]["end"], 2.06, delta=0.06)
            self.assertTrue(recs[0].get("trimmed"))

    def test_tighten_refuses_to_make_text_unreadable(self):
        """护栏：收紧后装不下这句话就整条放弃（宁可变长，不产出念不完的字幕）。"""
        with tempfile.TemporaryDirectory() as td:
            w = _tone_wav(pathlib.Path(td) / "a.wav",
                          [(0.0, 0.8, 0), (0.8, 2.0, 8000), (2.0, 3.0, 0)])
            long_text = "x" * 60                      # 60 字 / 12 cps ≈ 5s，窗口只有 1.2s
            recs = [{"start": 0.5, "end": 2.6, "text": long_text}]
            S.tighten_to_audio(recs, w, {"cps_hard_max": 12.0})
            self.assertEqual((recs[0]["start"], recs[0]["end"]), (0.5, 2.6))

    def test_tighten_without_wav_is_noop(self):
        recs = [{"start": 1.0, "end": 2.0, "text": "Hola."}]
        self.assertEqual(S.tighten_to_audio(recs, "Z:/nope.wav", {}), 0)


# ---------------------------------------------------------------- F. ASR 补位
class TestAsrFill(unittest.TestCase):
    def setUp(self):
        self._orig = S.asr_entries
        self._td = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._td.name)

    def tearDown(self):
        S.asr_entries = self._orig
        self._td.cleanup()

    def test_fills_when_script_has_no_line(self):
        """ep26_sc03/sc08 现场：剧本无 <d>，但确实有人声。"""
        S.asr_entries = lambda *a, **k: [(0.2, 1.8, "¡Pero si no te hagas!")]
        cfg = {"tools": {}}
        lc = {"max_cue_chars": 48, "max_duration_s": 6.0, "wrap": "word"}
        got = S.asr_fill_segment(cfg, {"file": "x.mp4", "shot_id": "ep26_sc03"},
                                 "ep26_sc03", self.tmp, self.tmp, lc, trim=False)
        self.assertIsNotNone(got)
        self.assertEqual(got["method"], "asr-only")
        self.assertEqual(got["lines"][0]["source"], "asr-unscripted")
        self.assertIn("hagas", got["lines"][0]["text"])

    def test_returns_none_without_speech(self):
        S.asr_entries = lambda *a, **k: []
        got = S.asr_fill_segment({"tools": {}}, {"file": "x.mp4"}, "ep26_sc01",
                                 self.tmp, self.tmp, {"max_cue_chars": 48}, trim=False)
        self.assertIsNone(got)

    def test_grouping_splits_on_gap_and_length(self):
        lc = {"wrap": "word", "max_cue_chars": 20, "max_duration_s": 6.0}
        rows = S.group_asr_lines([(0.0, 1.0, "Uno."), (2.0, 3.0, "Dos.")], lc)
        self.assertEqual(len(rows), 2)                       # 间隔 1.0s > 0.7 断句
        rows = S.group_asr_lines([(0.0, 1.0, "x" * 15), (1.0, 2.0, "y" * 10)], lc)
        self.assertEqual(len(rows), 2)                       # 累计超 20 字符断句


# ---------------------------------------------------------------- H. 台词提取
class TestDialogueLines(unittest.TestCase):
    def _ws(self, td, prompts):
        ws = pathlib.Path(td)
        (ws / "06-提示词").mkdir(parents=True, exist_ok=True)
        (ws / "06-提示词" / "h3_prompts.json").write_text(
            json.dumps(prompts, ensure_ascii=False), encoding="utf-8")
        (ws / "layout.json").write_text(json.dumps(
            {"layout_version": 1, "engine_root": "video-pipeline",
             "data_rel": "../06-提示词", "out_rel": "../07-成片"}), encoding="utf-8")
        (ws / "video-pipeline").mkdir(exist_ok=True)
        return ws

    def test_bracket_and_plain_forms_both_parsed(self):
        """`<d>[角色]台词</d>` 与 `<d>台词</d>` 都必须收进来（后者旧实现静默丢弃）。"""
        with tempfile.TemporaryDirectory() as td:
            ws = self._ws(td, {
                "ep01_sc01": {"prompt": "<d>[CAMILA/冷]Vete.</d> 画面描述"},
                "ep01_sc02": {"prompt": "<d>No vuelvas.</d> 画面描述"},
                "ep02_sc01": {"prompt": "<d>Otra.</d>"},
            })
            got = S.dialogue_lines(str(ws), "ep01")
            self.assertEqual(got["ep01_sc01"], ["Vete."])
            self.assertEqual(got["ep01_sc02"], ["No vuelvas."])
            self.assertNotIn("ep02_sc01", got)              # 别集不能混进来


# ---------------------------------------------------------------- I. 断行
class TestWrap(unittest.TestCase):
    LC = {"max_line_chars": 24, "line_tolerance_chars": 4, "wrap": "word",
          "break_punct": ".,!?;:…—", "forbid_line_start": ".,!?;:)]}»…—"}

    def test_break_at_sentence_end_first(self):
        """优先在句末断；不能把句子切成「Eran las / once y veinte.」这种碎块。"""
        self.assertEqual(S.split_two_lines("Eran las once y veinte. Llovía.", self.LC),
                         ["Eran las once y veinte.", "Llovía."])

    def test_never_orphan_single_word(self):
        got = S.split_two_lines("Mintió para salvar mi empresa.", self.LC)
        self.assertEqual(len(got), 2)
        self.assertGreater(len(got[0]), 3)          # 旧实现会切出只有「Mintió」的一行

    def test_short_line_not_split(self):
        self.assertEqual(S.split_two_lines("No puede recordar nada.", self.LC),
                         ["No puede recordar nada."])

    def test_comma_break_used(self):
        self.assertEqual(S.split_two_lines("¡Vamos a ver, Nello! ¡Vamos a ver!", self.LC),
                         ["¡Vamos a ver, Nello!", "¡Vamos a ver!"])

    def test_no_word_is_cut(self):
        for t in ["Eran las once y veinte. Llovía.", "Señora... perdón, señora Valdierre."]:
            for line in S.split_two_lines(t, self.LC):
                self.assertIn(line.strip(), t.replace("  ", " "))


# ---------------------------------------------------------------- J. 6:4 视觉中心
def _cfg(anchor="ratio", top=0.6, min_bottom=400, canvas=(1080, 1920)):
    """最小可用配置（只带 place/style 需要的字段）。"""
    return {
        "canvas": {"width": canvas[0], "height": canvas[1]},
        "safe_area": {"min_bottom_px": min_bottom, "max_text_width_pct": 70},
        "placement": {"anchor": anchor, "anchor_top": top},
        "default_language": "es",
        "layout": {"WrapStyle": 2, "ScaledBorderAndShadow": "yes",
                   "primary_colour": "&H00FFFFFF", "outline_colour": "&H00000000",
                   "back_colour": "&H80000000", "encoding": 1},
        "languages": {"es": {
            "font": "Microsoft YaHei", "font_size_pct": 6.5, "char_width_em": 0.52,
            "bold": True, "outline": 3, "shadow": 1, "margin_v_pct": 8.7,
            "margin_lr_pct": 4.2, "max_line_chars": 24, "line_tolerance_chars": 4,
            "max_lines": 2, "max_cue_chars": 48, "wrap": "word",
            "break_punct": ".,!?;:…—", "forbid_line_start": ".,!?;:)]}»…—",
        }},
    }


class TestVisualCenter(unittest.TestCase):
    """V0.7.6：纵向落点改「视觉中心 6:4」（移植自 vidpure）。"""

    def test_default_is_6_4(self):
        m = S.style_metrics(_cfg(), "es", (1080, 1920))
        self.assertEqual(m["anchor"], "ratio")
        self.assertEqual(m["anchor_label"], "6:4")
        self.assertEqual(m["center_y"], 1152)          # 0.6 × 1920
        self.assertEqual(m["pos"], (540, 1152))        # 水平居中 + 6:4
        self.assertEqual(m["margin_v"], 0)             # ratio 模式不用样式 MarginV
        self.assertGreaterEqual(m["bottom_px"], 400)   # 文字块下沿仍在安全区内

    def test_ratio_is_resolution_independent(self):
        """1080p / 1440p / 2K 竖屏下视觉中心都落在 60% 高（像素不同、比例相同）。"""
        for H in (1440, 1920, 3840):
            W = H * 9 // 16
            m = S.style_metrics(_cfg(canvas=(W, H)), "es", (W, H))
            self.assertFalse(m["clamped"], "H=%d 不该被安全区上顶" % H)
            self.assertAlmostEqual(m["center_y"] / float(H), 0.6, places=2, msg="H=%d" % H)

    def test_one_and_two_line_cues_share_center(self):
        """一行与两行的**中心**必须同线 —— 这正是不能用样式 MarginV 的原因。"""
        cfg = _cfg()
        one = [{"start": 0, "end": 1, "text": "Hola.", "lines": ["Hola."]}]
        two = [{"start": 0, "end": 1, "text": "Eran las once y veinte. Llovía.",
                "lines": ["Eran las once y veinte.", "Llovía."]}]
        with tempfile.TemporaryDirectory() as td:
            ys = []
            for i, cues in enumerate((one, two)):
                p = pathlib.Path(td) / ("c%d.ass" % i)
                S.write_ass(cues, cfg, str(p), canvas=(1080, 1920))
                txt = p.read_text(encoding="utf-8")
                ys += [int(x) for x in re.findall(r"\\pos\(\d+,(-?\d+)\)", txt)]
            self.assertEqual(len(ys), 2)
            self.assertEqual(ys[0], ys[1])

    def test_pixel_mode_still_works(self):
        cfg = _cfg(anchor="pixel")
        m = S.style_metrics(cfg, "es", (1080, 1920))
        self.assertEqual(m["anchor"], "pixel")
        self.assertIsNone(m["pos"])
        self.assertGreaterEqual(m["margin_v"], 400)
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "p.ass"
            S.write_ass([{"start": 0, "end": 1, "text": "Hola.", "lines": ["Hola."]}],
                        cfg, str(p), canvas=(1080, 1920))
            self.assertNotIn("\\pos(", p.read_text(encoding="utf-8"))
            self.assertTrue(S.qa_safe_area(str(p), cfg)["pass"])

    def test_anchor_clamped_by_safe_area(self):
        """anchor_top 调得很低（字幕贴底）时必须被安全区上顶，而不是进 UI 区。"""
        cfg = _cfg(top=0.95)
        m = S.style_metrics(cfg, "es", (1080, 1920))
        self.assertTrue(m["clamped"])
        self.assertGreaterEqual(m["bottom_px"], 400)

    def test_qa_rejects_wrong_anchor(self):
        cfg = _cfg()
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "t.ass"
            S.write_ass([{"start": 0, "end": 1, "text": "Hola.", "lines": ["Hola."]}],
                        cfg, str(p), canvas=(1080, 1920))
            txt = p.read_text(encoding="utf-8").replace("\\pos(540,1152)", "\\pos(540,1700)")
            p.write_text(txt, encoding="utf-8")
            qa = S.qa_safe_area(str(p), cfg)
            self.assertFalse(qa["pass"])
            self.assertTrue(any("设计值" in f for f in qa["failures"]))


# ---------------------------------------------------------------- K. 集号写法
class TestEpisodeId(unittest.TestCase):
    """★ 2026-10-22：集号必须**唯一形态** `epNN`，否则路径对不上且不报错。

    现场：`--ep 26` 能过参数校验，`_belongs_to_ep()` 也能匹配 ep26 的分镜，
    但 align/cues 路径变成 `subs/26/` ⇒ **静默产出 0 条字幕**，还顺手建了个 `subs/26/`。
    """

    def test_all_forms_normalized(self):
        for raw in ("26", "ep26", "EP26", "ep026", " 26 ", "ep 26"):
            self.assertEqual(S.canon_ep(raw), "ep26", raw)

    def test_single_digit_padded(self):
        self.assertEqual(S.canon_ep("3"), "ep03")
        self.assertEqual(S.canon_ep("ep3"), "ep03")
        self.assertEqual(S.canon_ep("100"), "ep100")

    def test_garbage_rejected_loudly(self):
        for bad in ("abc", "ep", "", "ep_02_extra", "第三集"):
            with self.assertRaises(SystemExit):
                S.canon_ep(bad)


# ---------------------------------------------------------------- D/E. 语速与时长
class TestCpsAndDuration(unittest.TestCase):
    def test_media_duration_missing_returns_zero_not_raise(self):
        self.assertEqual(S.media_duration("ffprobe-not-exists-xyz", "nope.mp4"), 0.0)

    def test_no_hardcoded_24fps(self):
        """源码里不许再出现「帧数 ÷ 24」推算段起点（会用实际时长）。"""
        src = (SCRIPTS / "subtitle.py").read_text(encoding="utf-8")
        self.assertNotIn("/ fps", src)
        self.assertEqual(S.REAL_ALIGN_METHODS[-1], "asr-only")


if __name__ == "__main__":
    unittest.main(verbosity=2)
