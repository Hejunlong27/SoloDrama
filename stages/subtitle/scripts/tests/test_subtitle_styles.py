# -*- coding: utf-8 -*-
"""test_subtitle_styles.py —— 三语字幕规范（en/zh/es）的回归测试（离线、零计费、零 ffmpeg）

锁死的是**视觉参数**，所以这里的断言全部是「读产出的 ASS / 读度量」而不是「读意图」：

  A. 三语各自的字号 / 字体 / 行宽与 `configs/subtitle-styles.json` 完全一致
  B. 三语落点同一条线（1080×1920 上 y=1152，即 6:4 视觉中心）—— 换语言字幕不许上下跳
  C. 平台安全区：文本框 ≤70% 宽、文字块下沿距底 ≥200px
  D. 换画布等比缩放：2160×3840 上字号正好是 1080×1920 的 2 倍（视觉比例恒定）
  E. 规范写错（字号×行宽超安全区）必须**报错**，不许静默缩字
  F. 没有样式表时**明确报错**（不回退百分比 —— 两套口径比失败更危险）

跑法：python stages/subtitle/scripts/tests/test_subtitle_styles.py
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
SCRIPTS = HERE.parent
REPO = SCRIPTS.parents[2]           # stages/subtitle/scripts → 仓库根
sys.path.insert(0, str(SCRIPTS))

import subtitle as S          # noqa: E402

SHEET = json.loads((REPO / "configs" / "subtitle-styles.json").read_text(encoding="utf-8"))
EXAMPLE = json.loads((REPO / "stages" / "subtitle" / "assets" /
                      "config.subtitle.example.json").read_text(encoding="utf-8-sig"))


def _cfg(lang="zh", with_sheet=True):
    cfg = json.loads(json.dumps(EXAMPLE))
    cfg["default_language"] = lang
    if with_sheet:
        cfg = S.apply_style_sheet(cfg, SHEET)
    return cfg


class TestLockedMetrics(unittest.TestCase):
    def test_all_three_languages_locked(self):
        """A：三语都有自己的锁定值，且字体/字号/行宽来自样式表。"""
        for lang in ("zh", "en", "es"):
            st = SHEET["styles"][lang]
            m = S.style_metrics(_cfg(lang), lang, (1080, 1920))
            self.assertEqual(m["font_size"], st["font_px"], "%s 字号未锁定" % lang)
            self.assertTrue(m["font_size_by"].startswith("locked("), "%s 没走锁定口径" % lang)
            cfg = _cfg(lang)
            self.assertEqual(cfg["languages"][lang]["font"], st["font"])
            self.assertEqual(cfg["languages"][lang]["max_line_chars"], st["max_line_chars"])

    def test_same_anchor_line(self):
        """B：三语落点必须同一条线 —— 换语言字幕上下跳是明确的返工项。"""
        ys = {lang: S.style_metrics(_cfg(lang), lang, (1080, 1920))["center_y"]
              for lang in ("zh", "en", "es")}
        self.assertEqual(set(ys.values()), {1152}, "落点不一致：%s" % ys)

    def test_safe_area(self):
        """C：文本框 ≤70%、下沿距底 ≥200px。"""
        for lang in ("zh", "en", "es"):
            m = S.style_metrics(_cfg(lang), lang, (1080, 1920))
            self.assertLessEqual(m["text_w_pct"], 70.0 + 1e-6, "%s 文本框超宽" % lang)
            self.assertGreaterEqual(m["bottom_px"], 200, "%s 下沿进 UI 区" % lang)
            need = (S.lc_get(_cfg(lang), lang, "max_line_chars", 12)
                    * S.lc_get(_cfg(lang), lang, "char_width_em", 1.0)
                    * m["font_size"])
            self.assertLessEqual(need, m["usable_w"] + 0.5, "%s 一行字装不下" % lang)

    def test_scales_with_canvas(self):
        """D：2160×3840 上字号 = 1080×1920 的两倍（等比，不是另一套规则）。"""
        base = S.style_metrics(_cfg("zh"), "zh", (1080, 1920))["font_size"]
        big = S.style_metrics(_cfg("zh"), "zh", (2160, 3840))["font_size"]
        self.assertEqual(big, base * 2)
        self.assertEqual(S.style_metrics(_cfg("zh"), "zh", (2160, 3840))["center_y"], 2304)

    def test_full_ass_and_qa(self):
        """A+B+C 的产物级验证：真写一份 ASS，再用 qa_safe_area 回读判。"""
        cues = [{"start": 0.5, "end": 2.5, "lines": ["你为什么要", "这么做？"], "text": "x"}]
        with tempfile.TemporaryDirectory() as td:
            for lang in ("zh", "en", "es"):
                cfg = _cfg(lang)
                p = pathlib.Path(td) / ("%s.ass" % lang)
                info = S.write_ass(cues, cfg, str(p), canvas=(1080, 1920))
                qa = S.qa_safe_area(str(p), cfg)
                self.assertTrue(qa["pass"], "%s 安全区断言失败：%s" % (lang, qa["failures"]))
                self.assertEqual(info["font_size_px"], SHEET["styles"][lang]["font_px"])
                body = p.read_text(encoding="utf-8")
                self.assertIn("\\an5\\pos(540,1152)", body, "%s 没用 an5 锁定落点" % lang)


class TestLoudFailure(unittest.TestCase):
    def test_overflow_is_an_error_not_a_shrink(self):
        """E：规范写错要报错 —— 静默缩字正是「同一份规范在不同剧里长得不一样」的根因。"""
        bad = json.loads(json.dumps(SHEET))
        bad["styles"]["zh"]["font_px"] = 90          # 12 字 × 90 = 1080 > 756
        cfg = S.apply_style_sheet(json.loads(json.dumps(EXAMPLE)), bad)
        with self.assertRaises(SystemExit) as ctx:
            S.style_metrics(cfg, "zh", (1080, 1920))
        self.assertIn("超出可用宽度", str(ctx.exception))

    def test_anchor_too_low_is_an_error(self):
        """E：落点进 UI 区要报错，不许静默上顶（上顶会让 qa 判过、偏差被藏起来）。"""
        bad = json.loads(json.dumps(SHEET))
        bad["placement"]["anchor_top"] = 0.95
        cfg = S.apply_style_sheet(json.loads(json.dumps(EXAMPLE)), bad)
        with self.assertRaises(SystemExit) as ctx:
            S.style_metrics(cfg, "zh", (1080, 1920))
        self.assertIn("下沿距底", str(ctx.exception))


class TestFallback(unittest.TestCase):
    def test_no_sheet_is_an_error(self):
        """F：没有样式表时**明确报错**，不回退旧口径（V0.7.43 起删掉了回退）。

        回退的代价是「同一份规范在不同剧里长得不一样」，且 qa 会按两套口径分别判过 ——
        比直接失败危险得多。
        """
        cfg = _cfg("zh", with_sheet=False)
        with self.assertRaises(SystemExit) as ctx:
            S.style_metrics(cfg, "zh", (1080, 1920))
        self.assertIn("font_px", str(ctx.exception))

    def test_sheet_found_from_repo(self):
        """样式表能被自动找到 —— 找不到会静默回退，等于规范不生效。"""
        import tempfile as tf
        with tf.TemporaryDirectory() as td:
            ws = pathlib.Path(td)
            (ws / "video-pipeline").mkdir(parents=True, exist_ok=True)
            sheet = S.load_style_sheet(str(ws), {})
            self.assertIsNotNone(sheet, "仓库真源没被找到（上溯层数错？）")
            self.assertEqual(set(sheet["styles"]), {"zh", "en", "es"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
