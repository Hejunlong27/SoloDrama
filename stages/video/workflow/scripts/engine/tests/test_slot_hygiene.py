# -*- coding: utf-8 -*-
"""图片槽位卫生（unused_slots）回归测试 —— 零依赖、零网络、零计费。

跑法：
    python stages/video/workflow/scripts/engine/tests/test_slot_hygiene.py

要证明的事（每一条都对应一次真实事故或一个真实风险）：

  1. **认得出图片槽**：`LoadImage` 类节点算，`filename_prefix` / `aspect_ratio` 不算。
  2. **找得全未使用的槽**：工作流 6 个槽、配置覆盖 3 个 ⇒ 另外 3 个必须被点出来。
     （事故：H3 的 ref_image_0…5，项目只覆盖 3 个，剩下 3 个一直在送同一张遗留图。）
  3. **一定顶得掉**：blank 模式要给出填充值；keep 模式必须显式写理由。
  4. **不会盖掉真实值**：填充值与真实参考图撞 nodeId 时，先到先得（配置优先）。
  5. **空字符串不被误丢**：empty 模式是有意发空值，不能被当成「空节点」过滤掉。
  6. **预演可复现**：--dry-run 不联网，靠落盘的槽位快照也能算出「哪几个会被顶掉」。
"""
import asyncio
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent
sys.path.insert(0, str(ENGINE))

import config as C                                               # noqa: E402
import pipeline as P                                             # noqa: E402
from runninghub_client import RunningHubClient, RunningHubError   # noqa: E402


def _nodes_from_prompt(prompt):
    """把 getJsonApiFormat 的 prompt 图摊平成 get_nodes() 那种「可填节点」列表。"""
    out = []
    for nid, spec in (prompt or {}).items():
        if not isinstance(spec, dict):
            continue
        ct = spec.get("class_type") or spec.get("type") or ""
        for fn, v in (spec.get("inputs") or {}).items():
            if isinstance(v, (list, dict)):
                continue
            out.append({"nodeId": str(nid), "fieldName": fn,
                        "fieldValue": v, "classType": ct})
    return out


# 与线上 H3 工作流同构的最小样本：6 个 LoadImage + 若干非图片节点
H3_PROMPT = {
    "136": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {
        "ref_image_size": "match", "length": ["131", 1],
        "ref_images.ref_image_0": ["137", 0], "ref_images.ref_image_1": ["139", 0],
        "ref_images.ref_image_2": ["146", 0], "ref_images.ref_image_3": ["159", 0],
        "ref_images.ref_image_4": ["160", 0], "ref_images.ref_image_5": ["161", 0]}},
    "137": {"class_type": "LoadImage", "inputs": {"image": "leftover.png"}},
    "139": {"class_type": "LoadImage", "inputs": {"image": "leftover.png"}},
    "146": {"class_type": "LoadImage", "inputs": {"image": "leftover.png"}},
    "159": {"class_type": "LoadImage", "inputs": {"image": "leftover.png"}},
    "160": {"class_type": "LoadImage", "inputs": {"image": "leftover.png"}},
    "161": {"class_type": "LoadImage", "inputs": {"image": "leftover.png"}},
    "138": {"class_type": "PrimitiveString", "inputs": {"value": "prompt"}},
    "132": {"class_type": "PrimitiveFloat", "inputs": {"value": 5.0}},
    "115": {"class_type": "ResolutionSelector", "inputs": {"aspect_ratio": "9:16"}},
    "156": {"class_type": "VHS_VideoCombine", "inputs": {"filename_prefix": "LQ-",
                                                         "frame_rate": 24}},
}

# 与项目 config.local.json 同构的覆盖映射：137=角色，139/159=场景（占两个槽）
COVER_NODES = {
    "prompt": {"nodeId": "138", "fieldName": "value"},
    "char_ref": {"nodeId": "137", "fieldName": "image"},
    "scene_ref": {"slots": [{"nodeId": "139", "fieldName": "image"},
                            {"nodeId": "159", "fieldName": "image"}]},
    "duration": {"nodeId": "132", "fieldName": "value"},
    "ratio": {"nodeId": "115", "fieldName": "aspect_ratio"},
}


class FakeUploads:
    async def get_or_upload_detail(self, client, path):
        return {"fileName": "openapi/fake.png",
                "url": "https://rh.example/input/openapi/fake.png"}

    async def get_or_upload(self, client, path):
        return "https://rh.example/input/openapi/fake.png"


class FakeCtx:
    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.client = None
        self.uploads = FakeUploads()
        self.logs = []
        self.slot_guards = {}

    def log(self, msg):
        self.logs.append(str(msg))

    def slot_fill(self, key):
        g = self.slot_guards.get(key)
        return g.fill_pairs() if g else []


def _spec(mode="blank", discover=True, slot_ids=None, reason="", value_form="url"):
    return {"unused_slots": {"mode": mode, "discover": discover,
                             "slot_ids": slot_ids or [], "reason": reason,
                             "value_form": value_form}}


# ---------------------------------------------------------------- A. 槽位识别
class TestSlotDetection(unittest.TestCase):
    def test_01_loadimage_is_slot(self):
        self.assertTrue(P.is_image_slot({"classType": "LoadImage", "fieldName": "image"}))

    def test_02_non_image_not_slot(self):
        for n in ({"classType": "VHS_VideoCombine", "fieldName": "filename_prefix"},
                  {"classType": "ResolutionSelector", "fieldName": "aspect_ratio"},
                  {"classType": "PrimitiveFloat", "fieldName": "value"}):
            self.assertFalse(P.is_image_slot(n), n)

    def test_03_ai_app_field_name_fallback(self):
        """AI 应用通道没有 classType，只能按字段名认（image / image1 / imageUrls）。"""
        for fn in ("image", "image1", "image_6", "imageUrls", "images"):
            self.assertTrue(P.is_image_slot({"fieldName": fn}), fn)

    def test_04_dedup_by_node_id(self):
        slots = P.image_slot_nodes([
            {"nodeId": "137", "fieldName": "image", "classType": "LoadImage"},
            {"nodeId": "137", "fieldName": "image", "classType": "LoadImage"},
            {"nodeId": "139", "fieldName": "image", "classType": "LoadImage"}])
        self.assertEqual([s["nodeId"] for s in slots], ["137", "139"])

    def test_05_real_prompt_shape_yields_six(self):
        slots = P.image_slot_nodes(_nodes_from_prompt(H3_PROMPT))
        self.assertEqual(sorted(s["nodeId"] for s in slots),
                         ["137", "139", "146", "159", "160", "161"])


# ---------------------------------------------------------------- B. 覆盖判定
class TestCovered(unittest.TestCase):
    def test_10_single_and_slots_both_count(self):
        cov = P.covered_slot_ids(COVER_NODES)
        self.assertEqual(cov, {"138", "137", "139", "159", "132", "115"})

    def test_11_unused_is_exactly_the_three(self):
        """事故复现：6 个槽、覆盖 3 个 ⇒ 必须点出 146/160/161。"""
        slots = P.image_slot_nodes(_nodes_from_prompt(H3_PROMPT))
        covered = P.covered_slot_ids(COVER_NODES)
        unused = [s["nodeId"] for s in slots if s["nodeId"] not in covered]
        self.assertEqual(sorted(unused), ["146", "160", "161"])


# ---------------------------------------------------------------- C. 占位图
class TestPlaceholder(unittest.TestCase):
    def test_20_creates_readable_png(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            p = P.placeholder_png(Path(tmp) / "blank.png")
            self.assertTrue(p.is_file())
            with Image.open(p) as im:
                self.assertEqual(im.size, (P.SLOT_BLANK_PX, P.SLOT_BLANK_PX))
                # 中性灰：三通道相等，且不偏黑白
                self.assertEqual(len(set(im.convert("RGB").getpixel((0, 0)))), 1)

    def test_21_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = P.placeholder_png(Path(tmp) / "b.png")
            mtime = os.path.getmtime(p)
            p2 = P.placeholder_png(Path(tmp) / "b.png")
            self.assertEqual(mtime, os.path.getmtime(p2), "重复调用不应重写文件")

    def test_22_size_not_tiny(self):
        """尺寸不能太小：有工作流对 ref_image 有尺寸下限（曾是 64px 的隐患）。"""
        self.assertGreaterEqual(P.SLOT_BLANK_PX, 512)


# ---------------------------------------------------------------- D. 填充策略
class TestFillPairs(unittest.TestCase):
    def _g(self, **kw):
        return P.SlotGuard(unused=[{"nodeId": "146", "fieldName": "image"},
                                   {"nodeId": "160", "fieldName": "image"}],
                           blank_file="openapi/fake.png",
                           blank_url="https://rh.example/fake.png", **kw)

    def test_30_blank_prefers_url(self):
        """默认形态是 url —— 项目历史 30 集的参考图提交就是 download_url。"""
        self.assertEqual(self._g(mode="blank").fill_pairs(),
                         [("146", "image", "https://rh.example/fake.png"),
                          ("160", "image", "https://rh.example/fake.png")])

    def test_31_blank_can_use_file_name(self):
        got = self._g(mode="blank", value_form="fileName").fill_pairs()
        self.assertEqual(got[0][2], "openapi/fake.png")

    def test_32_empty_mode_sends_empty_string(self):
        got = self._g(mode="empty").fill_pairs()
        self.assertEqual([v for _, _, v in got], ["", ""])

    def test_33_keep_mode_fills_nothing(self):
        self.assertEqual(self._g(mode="keep").fill_pairs(), [])

    def test_34_blank_without_upload_fills_nothing(self):
        """没上传成功就宁可什么都不发，也不要发 None 冒充值。"""
        g = P.SlotGuard(unused=[{"nodeId": "146", "fieldName": "image"}], mode="blank")
        self.assertEqual(g.fill_pairs(), [])

    def test_35_summary_mentions_each_unused(self):
        txt = self._g(total=6, covered_images=4, probed=True).summary()
        for nid in ("146", "160"):
            self.assertIn(nid, txt)


# ---------------------------------------------------------------- E. 提交列表
class TestBuildNodeList(unittest.TestCase):
    def test_40_dedup_keeps_first(self):
        """真实值在前、填充值在后 ⇒ 配置永远赢。"""
        got = RunningHubClient.build_node_list([
            ("137", "image", "real-char.png"),
            ("160", "image", "blank.png"),
            ("137", "image", "SHOULD-NOT-WIN.png")])
        self.assertEqual(len(got), 2)
        self.assertEqual(got[0]["fieldValue"], "real-char.png")

    def test_41_none_dropped_but_empty_kept(self):
        got = RunningHubClient.build_node_list([
            ("137", "image", None),          # 没值 → 丢（否则平台收到 "None"）
            ("160", "image", "")])           # 有意空值 → 保留
        self.assertEqual(got, [{"nodeId": "160", "fieldName": "image", "fieldValue": ""}])

    def test_42_h3_list_contains_all_six_slots(self):
        """端到端：真实 nodeInfoList 里 6 个图片槽都要出现，且无重复。"""
        guard = P.SlotGuard(unused=[{"nodeId": "146", "fieldName": "image"},
                                    {"nodeId": "160", "fieldName": "image"},
                                    {"nodeId": "161", "fieldName": "image"}],
                            blank_url="https://rh.example/blank.png")
        saved = C.H3
        C.H3 = dict(C.H3)
        C.H3["nodes"] = COVER_NODES
        try:
            nl = P.build_h3_node_list(
                prompt="p", frame_url=None, char_values=["char.png"],
                scene_values=["s1.png", "s2.png"], grid_url=None,
                duration=5, ratio="9:16", slot_fill=guard.fill_pairs())
        finally:
            C.H3 = saved
        ids = [n["nodeId"] for n in nl]
        self.assertEqual(len(ids), len(set(ids)), "同一 nodeId 不许发两次")
        img_ids = {n["nodeId"] for n in nl if n["fieldName"] == "image"}
        self.assertEqual(img_ids, {"137", "139", "159", "146", "160", "161"})

    def test_43_no_leftover_reference_survives(self):
        """最关键的一条：残留图的文件名绝不允许出现在提交列表里。"""
        guard = P.SlotGuard(unused=[{"nodeId": "146", "fieldName": "image"},
                                    {"nodeId": "160", "fieldName": "image"},
                                    {"nodeId": "161", "fieldName": "image"}],
                            blank_url="https://rh.example/blank.png")
        saved = C.H3
        C.H3 = dict(C.H3)
        C.H3["nodes"] = COVER_NODES
        try:
            nl = P.build_h3_node_list(
                prompt="p", frame_url=None, char_values=["char.png"],
                scene_values=["s1.png", "s2.png"], grid_url=None,
                duration=5, ratio="9:16", slot_fill=guard.fill_pairs())
        finally:
            C.H3 = saved
        self.assertFalse(any("leftover.png" in str(n["fieldValue"]) for n in nl))


# ---------------------------------------------------------------- F. 配置校验
class TestSlotConfig(unittest.TestCase):
    def test_50_defaults(self):
        got = P._slot_cfg({})
        self.assertEqual(got["mode"], "blank")
        self.assertTrue(got["discover"])
        self.assertEqual(got["value_form"], "url")

    def test_51_bad_mode_raises(self):
        with self.assertRaises(RunningHubError):
            P._slot_cfg(_spec(mode="drop"))

    def test_52_keep_without_reason_raises(self):
        with self.assertRaises(RunningHubError):
            P._slot_cfg(_spec(mode="keep", reason=""))
        self.assertEqual(P._slot_cfg(_spec(mode="keep", reason="确知残留图无害"))["mode"], "keep")

    def test_53_config_warn_degrades_keep(self):
        """overlay 校验层不崩整批：keep 缺理由 → 警告 + 回退 blank。"""
        cfg = {"mode": "keep", "reason": ""}
        C._validate_slots("h3", cfg)
        self.assertEqual(cfg["mode"], "blank")

    def test_54_config_warn_bad_value_form(self):
        cfg = {"value_form": "base64"}
        C._validate_slots("h3", cfg)
        self.assertEqual(cfg["value_form"], "url")

    def test_55_config_normalizes_slot_ids(self):
        cfg = {"slot_ids": [146, " 160 ", "", None]}
        C._validate_slots("h3", cfg)
        self.assertEqual(cfg["slot_ids"], ["146", "160"])


# ---------------------------------------------------------------- G. 探测与预演
class TestMakeGuard(unittest.TestCase):
    def _ws(self, tmp):
        return Path(tmp)

    def test_60_real_run_writes_cache(self):
        """真实运行：探测一次 → 算出未使用 3 个 + 写缓存。"""
        class Client:
            async def get_nodes(self, kind, tid):
                return _nodes_from_prompt(H3_PROMPT)

        with tempfile.TemporaryDirectory() as tmp:
            ctx = FakeCtx(dry_run=False)
            ctx.client = Client()
            g = asyncio.run(P.make_slot_guard(ctx, _spec(), COVER_NODES,
                                              "workflow", "wf1", self._ws(tmp), key="h3"))
            self.assertEqual(g.total, 6)
            self.assertEqual(g.covered_images, 3)
            self.assertEqual(sorted(s["nodeId"] for s in g.unused), ["146", "160", "161"])
            self.assertTrue((Path(tmp) / "slots_h3.json").is_file(), "应落快照供预演用")
            self.assertEqual(g.blank_url, "https://rh.example/input/openapi/fake.png")

    def test_61_dry_run_reads_cache_without_network(self):
        """预演不联网：缓存有就用缓存，也能算出「哪几个会被顶掉」。"""
        with tempfile.TemporaryDirectory() as tmp:
            real = FakeCtx(dry_run=False)
            real.client = type("C", (), {"get_nodes": staticmethod(
                lambda kind, tid: asyncio.sleep(0, result=_nodes_from_prompt(H3_PROMPT)))})()
            asyncio.run(P.make_slot_guard(real, _spec(), COVER_NODES, "workflow",
                                          "wf1", self._ws(tmp), key="h3"))
            # 预演 ctx 的 client 是 None：一调就炸，证明它没有联网
            dry = FakeCtx(dry_run=True)
            g = asyncio.run(P.make_slot_guard(dry, _spec(), COVER_NODES, "workflow",
                                              "wf1", self._ws(tmp), key="h3"))
            self.assertEqual(sorted(s["nodeId"] for s in g.unused), ["146", "160", "161"])
            self.assertIn("将上传", g.blank_url)

    def test_62_dry_run_without_cache_is_honest(self):
        """没有快照就明说没预演到，不许假装做过。"""
        with tempfile.TemporaryDirectory() as tmp:
            ctx = FakeCtx(dry_run=True)
            g = asyncio.run(P.make_slot_guard(ctx, _spec(), COVER_NODES, "workflow",
                                              "wf1", self._ws(tmp), key="h3"))
            self.assertFalse(g.probed)
            self.assertTrue(any("没有缓存快照" in x for x in ctx.logs), ctx.logs)

    def test_63_probe_failure_degrades_loudly(self):
        """探测失败不能静默：必须告诉用户「本轮未使用槽位会沿用工作流里的图」。"""
        class Broken:
            async def get_nodes(self, kind, tid):
                raise RuntimeError("network down")

        with tempfile.TemporaryDirectory() as tmp:
            ctx = FakeCtx(dry_run=False)
            ctx.client = Broken()
            g = asyncio.run(P.make_slot_guard(ctx, _spec(), COVER_NODES,
                                              "workflow", "wf1", self._ws(tmp), key="h3"))
            self.assertEqual(g.unused, [])
            self.assertTrue(any("探测失败" in x and "沿用工作流里保存的图" in x
                                for x in ctx.logs), ctx.logs)

    def test_64_ghost_detected(self):
        """配置指向工作流里不存在的槽位 ⇒ 报 ghost（工作流被改过的信号）。"""
        class Client:
            async def get_nodes(self, kind, tid):
                return _nodes_from_prompt(H3_PROMPT)

        bad_nodes = dict(COVER_NODES)
        bad_nodes["char_ref"] = {"nodeId": "999", "fieldName": "image"}
        with tempfile.TemporaryDirectory() as tmp:
            ctx = FakeCtx(dry_run=False)
            ctx.client = Client()
            g = asyncio.run(P.make_slot_guard(ctx, _spec(), bad_nodes,
                                              "workflow", "wf1", self._ws(tmp), key="h3"))
            self.assertIn("999", g.ghost)

    def test_65_manual_slot_ids_when_discover_off(self):
        """discover=false 时靠手工 slot_ids 兜（老工作流/接口不通时的后备）。"""
        with tempfile.TemporaryDirectory() as tmp:
            ctx = FakeCtx(dry_run=False)
            g = asyncio.run(P.make_slot_guard(
                ctx, _spec(discover=False, slot_ids=["146", "160", "161"]),
                COVER_NODES, "workflow", "wf1", self._ws(tmp), key="h3"))
            self.assertEqual(sorted(s["nodeId"] for s in g.unused), ["146", "160", "161"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
