#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""离线测试：画风库门禁（style_gate，四维）

零网络、零计费、零第三方依赖。
    python stages/production/scripts/tests/test_style_gate.py
"""
from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
SCRIPTS = HERE.parent
sys.path.insert(0, str(SCRIPTS))

import style_gate as SG            # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))


def _ws(tmp):
    ws = pathlib.Path(tmp)
    (ws / "05-分镜").mkdir(parents=True, exist_ok=True)
    return ws


def main():
    tmp = tempfile.mkdtemp(prefix="solodrama_style_")
    try:
        ws = _ws(tmp)

        # --- 风格库的边界：look 只放视觉，不许承载轨道/叙事/交付 ---
        #   这不是文档约定，是这次四维拆分的**机器判据**：
        #   一旦有人往 looks.json 里塞 track / delivery_stop，换 look 又会连带换规格，
        #   整轮整改就白做了。所以放在最前面，任何一次跑测试都会核对。
        looks_raw = json.loads((SG._CFG_DIR / "looks.json").read_text(encoding="utf-8-sig"))
        banned = ("track", "narrative", "delivery_stop", "narration_max_chars", "narration")
        offenders = []
        for it in looks_raw.get("looks") or []:
            hit = [k for k in it if k in banned]
            if hit:
                offenders.append("%s(%s)" % (it.get("id"), "/".join(hit)))
        check("looks.json 不含轨道/叙事字段", not offenders, "、".join(offenders))
        check("looks.json 至少 13 条", len(looks_raw.get("looks") or []) >= 13,
              "实际 %d" % len(looks_raw.get("looks") or []))
        check("每条 look 都有 prompt",
              all((it.get("prompt") or "").strip() for it in looks_raw.get("looks") or []))

        # --- 门禁：未确认 ---
        st = SG.gate_state(ws)
        check("未确认时 gate_state.confirmed=False", st["confirmed"] is False)
        ok, msg = SG.require(ws)
        check("未确认时 require 不放行", ok is False and "尚未确认画风" in msg, msg)

        # --- set 3d_manhua ---
        rc = SG._do_set(ws, "3d_manhua", None)
        check("set 3d_manhua 返回 0", rc == 0, "rc=%s" % rc)
        p = json.loads((ws / SG.PLAN_NAME).read_text(encoding="utf-8"))
        check("确认单写入且子模式取默认",
              p["style"]["choice"] == "3d_manhua" and p["style"]["sub_mode"] == "guoman-3d-render")
        check("3D 规格：三视图+辅卡必须", p["style"]["spec"]["assets"]["character_3view"] == 1
              and p["style"]["spec"]["assets"]["scene_aux"] == 1)
        check("3D 规格：单镜 6-10 秒", p["style"]["spec"]["shot_duration"]["min"] == 6.0
              and p["style"]["spec"]["shot_duration"]["max"] == 10.0)

        # --- 非法子模式被拒 ---
        rc = SG._do_set(ws, "3d_manhua", "nope")
        check("非法子模式返回 2", rc == 2, "rc=%s" % rc)

        # --- require 与 expect 不符则拦下 ---
        ok, msg = SG.require(ws, expect="2d_animation")
        check("画风不符时 require 不放行", ok is False and "已确认画风" in msg, msg)
        ok, msg = SG.require(ws, expect="3d_manhua")
        check("画风相符时放行", ok is True, msg)

        # --- 2D 规格差异 ---
        SG._do_set(ws, "2d_animation", None)
        s2 = SG.STYLES["2d_animation"]
        check("2D 不要三视图/辅卡", s2["assets"]["character_3view"] == 0 and s2["assets"]["scene_aux"] == 0)
        # ★ 2026-11-01 口径变更（整改方案 v2 §二）：
        #   ① 2D 也是短剧，交付到成片 —— 旧的「止于旁白交接」是半解说技能族的遗产；
        #   ② 真人轨分镜从「三格拼版」改为「一镜一张单帧」，三格本身就是 P21 实测的雷同源头。
        check("2D 交付到成片（不再是旁白交接）", s2["delivery_stop"] == "final_video")
        check("真人一镜一张单帧分镜", SG.STYLES["live_action"]["storyboard_topology"] == "one_frame_per_clip")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("=" * 62)
    print("style_gate 画风库门禁离线测试")
    print("=" * 62)
    n_fail = 0
    for name, ok, detail in RESULTS:
        print("  %s %s%s" % ("[OK]  " if ok else "[FAIL]", name, "" if ok else "  <- %s" % detail))
        n_fail += 0 if ok else 1
    print("-" * 62)
    print("共 %d 例，通过 %d，失败 %d" % (len(RESULTS), len(RESULTS) - n_fail, n_fail))
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
