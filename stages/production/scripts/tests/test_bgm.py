# -*- coding: utf-8 -*-
"""test_bgm.py —— BGM 库 / 铺排计划 / 门禁 / 混音（离线）

覆盖 2026-10-21 新增的配乐链路：
  * 库：项目库 + 共享库合并、缺文件、`--scan` 补时长
  * 计划：按情绪取默认增益、整集一首、无曲目时的错误
  * 门禁：license 缺失 / AI 生成缺 note / 增益过高 / 覆盖不足 / voice=h3 关 ducking
  * 混音：filter graph 结构（ducking、循环、视频直通）+（有 ffmpeg 时）真混一条并验时长
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import bgm as B          # noqa: E402

HAS_FFMPEG = bool(shutil.which("ffmpeg"))


def quiet(fn, *a, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn(*a, **kw)
    return r, buf.getvalue()


def write(p: pathlib.Path, obj) -> pathlib.Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


class Base(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.ws = pathlib.Path(self._td.name)
        self.libdir = self.ws / "04-资产" / "bgm"
        self.libdir.mkdir(parents=True, exist_ok=True)
        self.subs = self.ws / "video-pipeline" / "output" / "subs" / "ep01"
        self.subs.mkdir(parents=True, exist_ok=True)
        # ★ 测试必须与仓库里的**真共享库**隔离：仓库自带 12 首预置曲目（CC BY），
        #   否则每个用例都会读到它们，断言全乱。这里是"库为空"的干净世界。
        self._shared_orig = B.shared_lib_dir
        B.shared_lib_dir = lambda: self.ws / "_shared_bgm_absent"
        self.addCleanup(self._restore_shared)

    def _restore_shared(self):
        B.shared_lib_dir = self._shared_orig

    def tearDown(self):
        self._td.cleanup()

    def track(self, tid="tension_low_01", **kw):
        t = {"id": tid, "file": "%s.mp3" % tid, "moods": ["tension"], "bpm": 88,
             "duration": 120.0, "loop": True, "license": "licensed",
             "source": "测试", "license_note": "可商用", "gain_db": -22}
        t.update(kw)
        return t

    def lib(self, tracks):
        return write(self.libdir / "bgm-library.json", {"version": 1, "tracks": tracks})

    def touch_audio(self, name="tension_low_01.mp3"):
        p = self.libdir / name
        p.write_bytes(b"ID3fake")
        return p

    def touch_master(self, seconds=60.0, name="ep01_master_2k.mp4"):
        """不需要真视频 —— ep_duration 只读 ffprobe，读不到就回落到 h3_prompts。"""
        write(self.ws / "06-提示词" / "data" / "h3_prompts.json", {
            "ep01_shot_01": {"duration": seconds / 2, "prompt": "x"},
            "ep01_shot_02": {"duration": seconds / 2, "prompt": "x"},
        })
        return self.subs / name


class TestLibrary(Base):
    def test_01_empty_library_hint(self):
        lib = B.load_library(self.ws)
        self.assertEqual(lib["tracks"], [])
        txt = B.render_library(lib, self.ws)
        self.assertIn("库里没有曲目", txt)
        self.assertIn("library --scan", txt)

    def test_02_project_overrides_shared(self):
        self.lib([self.track("tension_low_01", source="项目库")])
        shared = B.shared_lib_dir()
        lib = B.load_library(self.ws)
        hit = [t for t in lib["tracks"] if t["id"] == "tension_low_01"]
        self.assertEqual(len(hit), 1, "同名 id 只应留一条（项目库覆盖共享库）")
        self.assertIn("04-资产", hit[0]["_root"].replace("\\", "/"))

    def test_03_missing_file_flagged_in_scan(self):
        self.lib([self.track()])
        got = B.scan(self.ws)
        self.assertTrue(got["failed"])
        self.assertIn("文件不存在", got["failed"][0]["error"])

    def test_04_json_output_shape(self):
        self.lib([self.track()])
        self.touch_audio()
        lib = B.load_library(self.ws)
        self.assertEqual(len(lib["tracks"]), 1)
        self.assertTrue(B.track_file(lib["tracks"][0]).is_file())


class TestPlan(Base):
    def test_10_plan_single_track_full_episode(self):
        self.lib([self.track()])
        self.touch_audio()
        self.touch_master(60.0)
        plan = B.make_plan(self.ws, "ep01", mood="tension")
        self.assertEqual(len(plan["segments"]), 1)
        seg = plan["segments"][0]
        self.assertEqual(seg["start"], 0.0)
        self.assertAlmostEqual(seg["end"], 60.0, places=1)
        self.assertEqual(seg["gain_db"], -22.0)
        self.assertTrue(plan["ducking"]["enabled"])

    def test_11_mood_changes_gain(self):
        t = self.track(moods=["revenge"])
        t.pop("gain_db")          # 曲目没写建议值时才走情绪默认表
        self.lib([t])
        self.touch_audio()
        self.touch_master(30.0)
        plan = B.make_plan(self.ws, "ep01", mood="revenge")
        self.assertEqual(plan["segments"][0]["gain_db"], -20.0)

    def test_12_no_tracks_returns_error(self):
        self.touch_master(30.0)
        plan = B.make_plan(self.ws, "ep01")
        self.assertEqual(plan["segments"], [])
        self.assertIn("库里没有可用曲目", plan["_error"])

    def test_13_segments_split(self):
        self.lib([self.track()])
        self.touch_audio()
        self.touch_master(30.0)
        plan = B.make_plan(self.ws, "ep01", segments=3)
        self.assertEqual(len(plan["segments"]), 3)
        self.assertEqual(plan["segments"][0]["start"], 0.0)
        self.assertAlmostEqual(plan["segments"][-1]["end"], 30.0, places=1)

    def test_14_voice_from_setup(self):
        write(self.ws / "project-setup.json", {"video_options": {"voice": "external"}})
        self.assertEqual(B.ep_voice(self.ws), "external")

    def test_15_duration_from_h3_prompts(self):
        self.touch_master(42.0)
        self.assertAlmostEqual(B.ep_duration(self.ws, "ep01"), 42.0, places=1)


class TestCheck(Base):
    def _plan(self, **over):
        self.touch_audio()
        self.touch_master(60.0)
        plan = B.make_plan(self.ws, "ep01", mood="tension")
        plan.update(over)
        return plan

    def codes(self, plan):
        return [i["code"] for i in B.check_plan(self.ws, plan)]

    def test_20_clean_plan_passes(self):
        self.lib([self.track()])
        self.assertEqual(self.codes(self._plan()), [])

    def test_21_missing_license(self):
        self.lib([self.track(license="")])
        self.assertIn("B004", self.codes(self._plan()))

    def test_22_generated_needs_note(self):
        self.lib([self.track(license="generated", license_note="")])
        self.assertIn("B005", self.codes(self._plan()))

    def test_23_gain_too_high(self):
        self.lib([self.track()])
        plan = self._plan()
        plan["segments"][0]["gain_db"] = -3        # 手工改高（模拟人工把 BGM 拉满）
        self.assertIn("B009", self.codes(plan))

    def test_23b_track_gain_overrides_mood_default(self):
        """库条目自己写了 gain_db 时应优先于情绪默认表（授权时按曲目登记的最稳）。"""
        self.lib([self.track(gain_db=-26)])
        self.touch_audio()
        self.touch_master(30.0)
        plan = B.make_plan(self.ws, "ep01", mood="tension")
        self.assertEqual(plan["segments"][0]["gain_db"], -26.0)

    def test_24_coverage_short(self):
        self.lib([self.track()])
        plan = self._plan()
        plan["segments"][0]["end"] = 30.0
        self.assertIn("B012", self.codes(plan))

    def test_25_ducking_required_when_voice_h3(self):
        self.lib([self.track()])
        plan = self._plan(voice="h3", ducking={"enabled": False})
        self.assertIn("B013", self.codes(plan))

    def test_26_unknown_track(self):
        self.lib([self.track()])
        plan = self._plan()
        plan["segments"][0]["track"] = "no_such_track"
        self.assertIn("B002", self.codes(plan))

    def test_27_end_before_start(self):
        self.lib([self.track()])
        plan = self._plan()
        plan["segments"][0]["end"] = 0.0
        self.assertIn("B007", self.codes(plan))

    def test_28_missing_file(self):
        self.lib([self.track()])   # 不放音频文件
        self.touch_master(60.0)
        plan = B.make_plan(self.ws, "ep01")
        self.assertIn("B003", self.codes(plan))


class TestMixCommand(Base):
    def test_30_graph_has_ducking_and_copy(self):
        self.lib([self.track()])
        self.touch_audio()
        self.touch_master(20.0)
        plan = B.make_plan(self.ws, "ep01", mood="tension")
        cmd = B.build_mix_cmd(self.ws, plan, self.subs / "ep01_master_2k.mp4",
                              self.subs / "ep01_mix.mp4")
        line = " ".join(cmd)
        self.assertIn("sidechaincompress", line)
        self.assertIn("-c:v copy", line)
        self.assertIn("volume=-22.0dB", line)
        self.assertIn("afade=t=in", line)

    def test_31_loop_adds_stream_loop(self):
        self.lib([self.track(loop=True)])
        self.touch_audio()
        self.touch_master(20.0)
        plan = B.make_plan(self.ws, "ep01")
        cmd = B.build_mix_cmd(self.ws, plan, self.subs / "m.mp4", self.subs / "o.mp4")
        self.assertIn("-stream_loop", cmd)

    def test_32_no_ducking_path(self):
        self.lib([self.track()])
        self.touch_audio()
        self.touch_master(20.0)
        plan = B.make_plan(self.ws, "ep01", )
        plan["voice"] = "external"
        plan["ducking"] = {"enabled": False}
        cmd = B.build_mix_cmd(self.ws, plan, self.subs / "m.mp4", self.subs / "o.mp4")
        self.assertNotIn("sidechaincompress", " ".join(cmd))

    def test_33_mix_blocks_on_hard_issue(self):
        self.lib([self.track(license="")])
        self.touch_audio()
        self.touch_master(20.0)
        plan = B.make_plan(self.ws, "ep01")
        res = B.mix_episode(self.ws, plan, apply=False)
        self.assertFalse(res["ok"])
        self.assertIn("license", res["error"])


@unittest.skipUnless(HAS_FFMPEG, "需要 ffmpeg")
class TestMixReal(Base):
    """真混一条：2 秒小视频 + 2 秒正弦，断言时长一致、音频流存在。"""

    def _gen(self, out: pathlib.Path, sec=2, audio_hz=880):
        subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y",
                        "-f", "lavfi", "-i", "color=c=gray:s=96x160:d=%d:r=8" % sec,
                        "-f", "lavfi", "-i", "sine=frequency=%d:duration=%d" % (audio_hz, sec),
                        "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "128k", str(out)], check=True)

    def test_40_mix_produces_playable_video(self):
        self.lib([self.track(loop=True)])
        self._gen(self.libdir / "tension_low_01.m4a", sec=6, audio_hz=220)
        (self.libdir / "bgm-library.json").write_text(json.dumps({
            "version": 1,
            "tracks": [self.track(file="tension_low_01.m4a", duration=6.0)]},
            ensure_ascii=False), encoding="utf-8")
        master = self.subs / "ep01_master_2k.mp4"
        self._gen(master, sec=2)
        plan = {"ep": "ep01", "total_s": 2.0, "voice": "h3", "mood": "tension",
                "ducking": {"enabled": True, "threshold": 0.05, "ratio": 6,
                            "attack": 20, "release": 350},
                "segments": [{"track": "tension_low_01", "start": 0.0, "end": 2.0,
                              "gain_db": -22, "fade_in": 0.3, "fade_out": 0.3,
                              "loop": True}]}
        res = B.mix_episode(self.ws, plan, base=master, apply=True)
        self.assertTrue(res.get("ok"), res.get("error"))
        out = pathlib.Path(res["out"])
        self.assertTrue(out.is_file())
        self.assertAlmostEqual(float(res["duration"]), 2.0, delta=0.2)
        probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                "stream=codec_type", "-of", "csv=p=0", str(out)],
                               capture_output=True, text=True)
        self.assertIn("audio", probe.stdout)
        self.assertIn("video", probe.stdout)


class TestSelectionAndCredits(Base):
    def test_60_lru_avoids_repeating_last_track(self):
        """相邻集不重复：ep01 用过 A 之后，ep02 应优先选从未用过的 B。"""
        self.lib([self.track("tension_a"), self.track("tension_b")])
        self.touch_audio("tension_a.mp3")
        self.touch_audio("tension_b.mp3")
        self.touch_master(30.0)
        p1 = B.make_plan(self.ws, "ep01", mood="tension")
        self.assertEqual(p1["segments"][0]["track"], "tension_a")
        # 把 ep01 的计划落盘（LRU 靠计划文件记录使用情况）
        write(self.subs / "ep01_bgm-plan.json", p1)
        p2 = B.make_plan(self.ws, "ep02", mood="tension")
        self.assertEqual(p2["segments"][0]["track"], "tension_b")

    def test_61_credits_lists_attribution(self):
        self.lib([dict(self.track("tension_a"), artist="Kevin MacLeod",
                       title="Impending Boom", license_name="CC BY 3.0",
                       attribution="Kevin MacLeod — “Impending Boom”（CC BY 3.0，via Wikimedia Commons）")])
        self.touch_audio("tension_a.mp3")
        self.touch_master(30.0)
        write(self.subs / "ep01_bgm-plan.json", B.make_plan(self.ws, "ep01", mood="tension"))
        rc, out = quiet(B.cmd_credits, argparse.Namespace(
            workspace=str(self.ws), ep="ep01", json=False))
        txt = "".join(out)
        self.assertEqual(rc, 0)
        self.assertIn("需署名", txt)
        self.assertIn("Impending Boom", txt)
        self.assertIn("Music:", txt)

    def test_62_credits_without_plan(self):
        rc, _ = quiet(B.cmd_credits, argparse.Namespace(
            workspace=str(self.ws), ep="ep99", json=False))
        self.assertEqual(rc, B.EXIT_NOT_READY)


class TestSubtitleHook(Base):
    """subtitle.py 的 `_try_bgm()`：无计划/禁用时**必须原样返回底片**，不能阻塞出片。"""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(HERE.parents[2] / "subtitle" / "scripts"))
        import subtitle                     # noqa: F401
        cls.sub = subtitle

    def test_50_disabled_returns_base(self):
        base = str(self.subs / "ep01_master_2k.mp4")
        got, msg = self.sub._try_bgm(str(self.ws), "ep01", base, disabled=True)
        self.assertEqual(got, base)
        self.assertEqual(msg, "")

    def test_51_no_plan_returns_base(self):
        base = str(self.subs / "ep01_master_2k.mp4")
        got, msg = self.sub._try_bgm(str(self.ws), "ep01", base)
        self.assertEqual(got, base)
        self.assertEqual(msg, "")

    def test_52_plan_present_no_base_returns_base(self):
        """有计划但还没有母版时也不能崩（S10 之前的正常状态）。"""
        write(self.subs / "ep01_bgm-plan.json", {"ep": "ep01", "total_s": 1.0, "segments": []})
        got, msg = self.sub._try_bgm(str(self.ws), "ep01", None)
        self.assertIsNone(got)


if __name__ == "__main__":
    unittest.main(verbosity=2)
