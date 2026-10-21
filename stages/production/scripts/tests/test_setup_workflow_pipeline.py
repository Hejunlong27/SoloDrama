# -*- coding: utf-8 -*-
"""test_setup_workflow_pipeline.py —— 开工前置条件 / 11 环节流程 / 流水线模式（离线 26 例）

覆盖三条新能力（2026-10-21 V0.6）：
  * project_setup ：七项确认单（缺项 → 退出码 4；非法值 → 2；预算换算；改动留痕）
  * workflow      ：11 环节产物判据（花括号展开、动态 min、顺序门禁、跳过留痕）
  * pipeline      ：开工预告（ETA/预算余量）、闸门（--yes / setup / 预算熔断）、停点（agent）
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import pathlib
import sys
import tempfile
import time
import unittest
import types

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

# convert_storyboard 在导入期就要解析工作区（`import _ws` → `WS = resolve()`），
# 所以先给一个已存在的临时目录，否则整个测试文件收集阶段就会 SystemExit。
# ★ 必须**覆盖**而不是 setdefault：本机常驻一条过期的 SOLODRAMA_WORKSPACE
#   （实测指向已不存在的 D:\剧本\海外剧\1013新建），setdefault 会被它顶掉。
os.environ["SOLODRAMA_WORKSPACE"] = tempfile.mkdtemp(prefix="sd_ws_")

import project_setup as PS      # noqa: E402
import workflow as WF           # noqa: E402
import pipeline as PL           # noqa: E402
import convert_storyboard as CS  # noqa: E402

sys.path.insert(0, str(HERE.parents[3] / "tools"))   # noqa: E402
import core.validate as V        # noqa: E402


def quiet(fn, *a, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn(*a, **kw)
    return r, buf.getvalue()


def ns(**kw):
    d = dict(style=None, sub_mode=None, episodes=None, ep_seconds=None,
             image_model=None, image_workflow=None, image_comfy_url=None,
             image_app_url=None, image_app_id=None, video_model=None,
             video_workflow=None, video_workflow_id=None, video_comfy_url=None,
             video_app_url=None, video_app_id=None, resolution=None, steps=None,
             megapixels=None, voice=None, concurrency=None, pipeline=None,
             budget_coins=None)
    d.update(kw)
    return argparse.Namespace(**d)


class Base(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.ws = pathlib.Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    # 造一个七项齐全的工作区
    def set_rc(self, **kw) -> int:
        """apply_set 返回 (rc, msgs)，这里只取 rc。"""
        r, _out = quiet(PS.apply_set, self.ws, ns(**kw))
        return r[0] if isinstance(r, tuple) else r

    def full_setup(self, **over):
        kw = dict(style="live_action", episodes=30, ep_seconds=60,
                  image_model="local_comfyui", video_model="closed_source",
                  resolution="1080x1920", pipeline="on", budget_coins=9000)
        kw.update(over)
        return self.set_rc(**kw)

    def touch(self, rel: str, text: str = "x"):
        p = self.ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p


class TestProjectSetup(Base):
    def test_01_empty_missing_six(self):
        st = PS.collect(self.ws)
        self.assertFalse(st["ok"])
        # 功能选项有实测默认值（4 步 / 0.8MP / h3 / 并发 2），默认即合规 → 不算缺项
        self.assertEqual(len(st["missing"]), 6)
        self.assertNotIn("video_options", st["missing"])

    def test_02_full_ok(self):
        self.assertEqual(self.full_setup(), 0)
        ok, msg = PS.require(self.ws)
        self.assertTrue(ok, msg)
        self.assertIn("7/7", msg)

    def test_03_bad_ep_seconds(self):
        self.assertEqual(self.set_rc(ep_seconds=45), 2)

    def test_04_bad_voice(self):
        # argparse 层已限制 choice，这里直接测校验分支
        self.assertEqual(self.set_rc(voice="robot"), 2)

    def test_05_pipeline_on_without_budget(self):
        # 预算会自动按规模回填；给 0 视为非法 → 2
        self.assertEqual(self.set_rc(pipeline="on", budget_coins=0), 2)

    def test_06_budget_cny(self):
        self.full_setup(budget_coins=10000)
        d = PS.load(self.ws)
        self.assertAlmostEqual(d["pipeline"]["budget_cap_cny"], 25.0, places=2)

    def test_07_history(self):
        quiet(PS.apply_set, self.ws, ns(episodes=30))
        quiet(PS.apply_set, self.ws, ns(episodes=40))
        d = PS.load(self.ws)
        hist = [h for h in d["history"] if h["field"] == "episodes.count"]
        self.assertEqual(len(hist), 2)          # None→30、30→40 各一条
        self.assertEqual(hist[-1]["from"], 30)
        self.assertEqual(hist[-1]["to"], 40)

    def test_08_bad_resolution(self):
        self.assertEqual(self.set_rc(resolution="1080p"), 2)

    def test_09_pipeline_off_ok(self):
        self.assertEqual(self.full_setup(pipeline="off", budget_coins=None), 0)
        self.assertTrue(PS.collect(self.ws)["ok"])

    def test_10_derived_budget(self):
        self.full_setup(episodes=10, megapixels=1.0)
        dv = PS.collect(self.ws)["derived"]
        self.assertEqual(dv["coins_per_shot"], 40)
        self.assertEqual(dv["est_total_coins"], round(10 * 7.5 * 40))

    def test_11_require_json_shape(self):
        st = PS.collect(self.ws)
        self.assertEqual(set(st["items"]), {"style", "episodes", "image_model",
                                            "video_model", "resolution",
                                            "video_options", "pipeline"})

    def test_12_reset(self):
        self.full_setup()
        rc, _ = quiet(PS.cmd_reset, argparse.Namespace(workspace=str(self.ws),
                                                       keep_style=True))
        self.assertEqual(rc, 0)
        self.assertFalse(PS.setup_path(self.ws).is_file())


class TestWorkflow(Base):
    def test_20_ids_sequential(self):
        self.assertEqual(WF.STAGE_IDS, ["S%d" % i for i in range(1, 12)])

    def test_21_empty_current_s1(self):
        self.assertEqual(WF.evaluate(self.ws)["current"], "S1")

    def test_22_s1_done_by_market_json(self):
        self.touch("01-调研/market-data.json", "{}")
        ev = WF.evaluate(self.ws)
        s1 = next(r for r in ev["stages"] if r["id"] == "S1")
        self.assertTrue(s1["done"])
        self.assertEqual(ev["current"], "S2")

    def test_23_order_gate_blocks(self):
        ok, blocking = WF.check_stage(self.ws, "S6")
        self.assertFalse(ok)
        self.assertTrue(any("S1" in b for b in blocking))

    def test_24_skip_requires_reason(self):
        rc, _ = quiet(WF.cmd_skip, argparse.Namespace(
            workspace=str(self.ws), stage="S1", reason=None))
        self.assertEqual(rc, 2)

    def test_25_skip_with_reason(self):
        quiet(WF.cmd_skip, argparse.Namespace(
            workspace=str(self.ws), stage="S1", reason="用户明确要求跳过建组"))
        ev = WF.evaluate(self.ws)
        s1 = next(r for r in ev["stages"] if r["id"] == "S1")
        self.assertTrue(s1["done"])
        self.assertTrue(s1["skipped"])

    def test_26_manual_done(self):
        quiet(WF.cmd_done, argparse.Namespace(
            workspace=str(self.ws), stage="S3", note="圣经已写"))
        ev = WF.evaluate(self.ws)
        s3 = next(r for r in ev["stages"] if r["id"] == "S3")
        self.assertTrue(s3["by_manual"])

    def test_27_brace_glob(self):
        self.touch("04-资产/characters/char_01.png")
        ev = WF.evaluate(self.ws)
        s4 = next(r for r in ev["stages"] if r["id"] == "S4")
        img = next(p for p in s4["probes"] if p["label"] == "人物/场景图")
        self.assertEqual(img["found"], 1)

    def test_28_dynamic_min_episodes(self):
        self.touch("project-setup.json", json.dumps(
            {"episodes": {"count": 3}}))
        self.touch("03-剧本/ep_01.md")
        self.touch("03-剧本/ep_02.md")
        ev = WF.evaluate(self.ws)
        s2 = next(r for r in ev["stages"] if r["id"] == "S2")
        ep = next(p for p in s2["probes"] if p["label"] == "单集剧本")
        self.assertEqual(ep["need"], 3)
        self.assertFalse(ep["ok"])

    def test_29_complete_when_all_present(self):
        self.touch("01-调研/market-data.json", "{}")
        self.touch("02-选题/positioning.json", "{}")
        self.touch("03-剧本/blueprint.json", "{}")
        self.touch("03-剧本/ep_01.md")
        self.touch("04-资产/design/character-bible.json", "{}")
        self.touch("04-资产/design/prompts/char/char_01.txt")
        self.touch("04-资产/characters/char_01.png")
        self.touch("04-资产/refs.json", "{}")
        self.touch("05-分镜/ep01.md")
        self.touch("06-提示词/data/shots.json", "[]")
        self.touch("06-提示词/data/h3_prompts.json", "{}")
        self.touch("07-成片/b1/shot_01/final.mp4")
        self.touch("07-成片/subs/ep01/ep01_master.mp4")
        self.touch("07-成片/subs/ep01/ep01_master_2k.mp4")
        self.touch("07-成片/subs/ep01/ep01_subbed.mp4")
        self.touch("09-发行/剧集/Episode01.mp4")
        ev = WF.evaluate(self.ws)
        # S7 是可选环节，缺它也算 complete
        self.assertTrue(ev["complete"], [r["id"] for r in ev["stages"] if not r["done"]])


class TestPipeline(Base):
    def test_40_forecast_setup_missing(self):
        f = PL.forecast(self.ws)
        self.assertFalse(f["setup_ok"])
        self.assertEqual(len(f["setup_missing"]), 6)

    def test_41_forecast_budget(self):
        self.full_setup(episodes=10, budget_coins=9000)
        f = PL.forecast(self.ws)
        self.assertTrue(f["setup_ok"])
        self.assertEqual(f["budget_cap_coins"], 9000)
        self.assertEqual(f["budget_headroom_coins"], 9000)
        self.assertEqual(f["episodes"], 10)
        self.assertTrue(f["eta_at"])

    def test_42_spent_coins_only_success(self):
        p = self.ws / "video-pipeline" / "ledger" / "runs"
        p.mkdir(parents=True, exist_ok=True)
        (p / "a.json").write_text(json.dumps({"attempts": [
            {"status": "SUCCESS", "usage": {"consumeCoins": 34}},
            {"status": "FAILED", "usage": {"consumeCoins": 99}},
            {"status": "SUCCESS", "usage": {"consumeCoins": 6}},
        ]}), encoding="utf-8")
        self.assertEqual(PL.spent_coins(self.ws)["coins"], 40.0)

    def test_43_run_needs_yes(self):
        rc, out = quiet(PL.cmd_run, argparse.Namespace(
            workspace=str(self.ws), yes=False, from_stage=None, to_stage=None))
        self.assertEqual(rc, 2)
        self.assertIn("--yes", "".join(out))

    def test_44_run_blocked_by_setup(self):
        rc, out = quiet(PL.cmd_run, argparse.Namespace(
            workspace=str(self.ws), yes=True, from_stage=None, to_stage=None))
        self.assertEqual(rc, 4)
        self.assertIn("前置条件未齐", "".join(out))

    def test_45_run_blocked_pipeline_off(self):
        self.full_setup(pipeline="off", budget_coins=None)
        rc, _ = quiet(PL.cmd_run, argparse.Namespace(
            workspace=str(self.ws), yes=True, from_stage=None, to_stage=None))
        self.assertEqual(rc, 4)

    def test_46_run_stops_at_agent(self):
        self.full_setup()
        rc, out = quiet(PL.cmd_run, argparse.Namespace(
            workspace=str(self.ws), yes=True, from_stage=None, to_stage=None))
        self.assertEqual(rc, 4)
        txt = "".join(out)
        self.assertIn("流水线停点", txt)
        self.assertIn("S1", txt)

    def test_47_budget_fuse(self):
        self.full_setup(budget_coins=10)
        # 已花 20 > 上限 10，且 S1-S3 已登记，下一个是 auto 的 S4 → 熔断
        p = self.ws / "video-pipeline" / "ledger" / "runs"
        p.mkdir(parents=True, exist_ok=True)
        (p / "a.json").write_text(json.dumps({"attempts": [
            {"status": "SUCCESS", "usage": {"consumeCoins": 20}}]}), encoding="utf-8")
        for sid in ("S1", "S2", "S3"):
            quiet(WF.cmd_done, argparse.Namespace(workspace=str(self.ws), stage=sid, note="t"))
        rc, out = quiet(PL.cmd_run, argparse.Namespace(
            workspace=str(self.ws), yes=True, from_stage=None, to_stage=None))
        self.assertEqual(rc, 3)
        self.assertIn("BUDGET", "".join(out))

    def test_48_agent_brief_contains_probes(self):
        ev = WF.evaluate(self.ws)
        row = next(r for r in ev["stages"] if r["id"] == "S2")
        txt = PL.render_agent_brief(row)
        self.assertIn("产物判据", txt)
        self.assertIn("mark S2", txt)

    def test_49_mark_advances(self):
        quiet(PL.cmd_mark, argparse.Namespace(workspace=str(self.ws), stage="S1", note="ok"))
        self.assertEqual(WF.evaluate(self.ws)["current"], "S2")


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

    def test_72_latin_over_limit(self):
        line = "“" + "a" * 60 + "”"
        issues = V._check_dialog(self._ep(line))
        self.assertTrue(any(i.code == "E007" for i in issues))

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
