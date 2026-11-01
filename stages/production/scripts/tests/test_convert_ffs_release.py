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
