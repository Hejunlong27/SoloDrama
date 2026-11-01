# -*- coding: utf-8 -*-
"""契约测试：分镜 refs 分流 / FFS 规则 / 发行版本选取（零网络、零计费）

原本与 setup / workflow / pipeline 三套旧编排的测试混在一个文件里。
2026-11-01 删掉那三套（能力清单 S2 / S6，以及同属旧编排的 pipeline.py）之后，
这里只保留仍然有效的契约：

  * `convert_storyboard` 的 refs 分流 —— 角色/场景**只在顺序不变时**才拆，交错不拆不猜
  * `tools/core/validate` 的 FFS 规则 —— 西语断句、拉丁上限、总时长容差
  * `release_export` 的同集多版本选取 —— 取 mtime 最新，不静默交付旧版

跑法：
    python stages/production/scripts/tests/test_convert_ffs_release.py
"""
import os
import pathlib
import sys
import tempfile
import types
import time
import unittest


def _repo_root() -> pathlib.Path:
    """向上找带 stages/_layout.py 的仓库根（不数 parents[N]，这个坑犯过六次）。"""
    for up in pathlib.Path(__file__).resolve().parents[:7]:
        if (up / "stages" / "_layout.py").is_file():
            return up
    raise SystemExit("仓库根定位失败")


HERE = pathlib.Path(__file__).resolve().parent
ROOT = _repo_root()
SCRIPTS = HERE.parent
sys.path.insert(0, str(SCRIPTS))

# convert_storyboard 在导入期就会解析工作区，先给一个存在的临时目录
os.environ["SOLODRAMA_WORKSPACE"] = tempfile.mkdtemp(prefix="sd_ws_")

import convert_storyboard as CS          # noqa: E402

sys.path.insert(0, str(ROOT / "tools"))  # noqa: E402
import core.validate as V                # noqa: E402


class TestConvertRefsSplit(unittest.TestCase):
    """反馈 9.3：character_refs / scene_refs 必须分流，且**只在顺序不变时**才拆。"""

    def _split(self, refs, chars=("JUEZA", "SERGIO"), scenes=("JUZGADO",)):
        return CS._split_refs(list(refs), set(chars), set(scenes), "shot_01", {})

    def test_60_all_characters(self):
        c, s = self._split(["JUEZA", "SERGIO"])
        self.assertEqual(c, ["JUEZA", "SERGIO"])
        self.assertEqual(s, [])

    def test_61_scene_after_characters(self):
        c, s = self._split(["JUEZA", "JUZGADO"])
        self.assertEqual(c, ["JUEZA"])
        self.assertEqual(s, ["JUZGADO"])

    def test_62_interleaved_not_split(self):
        st = {}
        c, s = CS._split_refs(["JUEZA", "JUZGADO", "SERGIO"], {"JUEZA", "SERGIO"},
                              {"JUZGADO"}, "shot_01", st)
        self.assertEqual(s, [])
        self.assertEqual(c, ["JUEZA", "JUZGADO", "SERGIO"])
        self.assertEqual(st.get("refs_interleaved"), ["shot_01"])

    def test_63_unknown_key_recorded(self):
        st = {}
        CS._split_refs(["JUEZA", "sb_ep01_sc01"], {"JUEZA"}, set(), "shot_02", st)
        self.assertEqual(st.get("refs_unknown"), ["shot_02(sb_ep01_sc01)"])


class TestFfsRules(unittest.TestCase):
    """反馈 2.1 / 2.2 / 4.x / 4.y：西语断句、拉丁上限、总时长容差。"""

    def _ep(self, dialog):
        return types.SimpleNamespace(shots=[types.SimpleNamespace(
            sc_id="SC-01", dialog=dialog, est_sec=6)])

    def test_70_spanish_period_splits(self):
        issues = V._check_dialog(self._ep("“Es prueba. Está firmada.”"))
        self.assertEqual([i.code for i in issues], [])

    def test_71_latin_long_sentence_allowed(self):
        line = "“Necesito saber quien firmo este documento ayer.”"     # 47 字符
        issues = V._check_dialog(self._ep(line))
        self.assertEqual([i.code for i in issues], [], "西语 55 字符以内应放行")

    def test_72_latin_char_cap_removed(self):
        # 2026-10-31：取消拉丁语系 55 字符单句上限，改由「词/秒 × 本镜时长」兜底
        line = "“" + "a" * 60 + "”"
        issues = V._check_dialog(self._ep(line))
        self.assertEqual([i.code for i in issues], [], "长单句不再按字符判死")

    def test_72b_latin_word_budget_enforced(self):
        line = "“" + " ".join(["word"] * 30) + "”"      # 30 词 > 6s × 3.8 = 22 词
        issues = V._check_dialog(self._ep(line))
        self.assertTrue(any("22 词" in i.message for i in issues), "超出本镜语速预算必须报错")

    def test_72c_latin_four_sentences_allowed(self):
        issues = V._check_dialog(self._ep("“One. Two. Three. Four.”"))
        self.assertEqual([i.code for i in issues], [], "高密度对白允许单镜 4 句")

    def test_72d_latin_five_sentences_rejected(self):
        issues = V._check_dialog(self._ep("“One. Two. Three. Four. Five.”"))
        self.assertTrue(any("4 句上限" in i.message for i in issues))

    def test_73_chinese_still_20(self):
        issues = V._check_dialog(self._ep("“" + "字" * 25 + "”"))
        self.assertTrue(any("20 字" in i.message for i in issues))

    def test_74_total_duration_tolerance(self):
        shots = [types.SimpleNamespace(sc_id="SC-%02d" % i, est_sec=12) for i in range(1, 6)]
        ep = types.SimpleNamespace(shots=shots, total_sec=59)
        self.assertEqual([i.code for i in V._check_duration(ep)], [],
                         "59 秒在 60 秒档的 ±2s 容差内")


class TestReleasePickLatest(unittest.TestCase):
    """反馈 10.8：同集多版本时取 mtime 最新，不静默交付旧版。"""

    def test_80_same_rank_prefers_newer(self):
        import release_export as RE
        with tempfile.TemporaryDirectory() as td:
            d = pathlib.Path(td)
            old = d / "ep01_1080p_sub.mp4"          # 旧：字幕错位
            new = d / "ep01_final.mp4"              # 新：ASR 校时（同为 encoded rank）
            old.write_bytes(b"x")
            time.sleep(0.02)
            new.write_bytes(b"y")
            found = RE._scan(d)
            self.assertIn(1, found)
            self.assertEqual(found[1][1].name, "ep01_final.mp4")


if __name__ == "__main__":
    unittest.main(verbosity=2)
