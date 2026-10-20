#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_script_continuity.py —— 剧本 ↔ 分镜 ↔ H3 提示词 连续性门禁 离线测试

覆盖：
  解析    FFS 剧本（镜头块 / 台词 / HEADER 人物登记）、三种产物形态探测
  检查    镜数（丢镜 / 拆镜）、台词逐字、人物（换人 / 主角零参考 / 未登记代号）、时长、首尾承接
  降级    跨语种（blueprint 中文 vs 剧本外语）→ WARN 不 FAIL；句库元指令 → WARN 不 FAIL
  门禁    无产物不空转通过（退出码 4）

用法：python test_script_continuity.py
"""
from __future__ import annotations

import contextlib
import io
import json
import pathlib
import shutil
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))          # stages/production/scripts
sys.path.insert(0, str(HERE))

import script_continuity as SC  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))


def _w(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8", newline="")


def _wj(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="")


SCRIPT = """# TITLE: 她把股权带回了葬礼
# EP: 01/40
# PLATFORM: TikTok
# STYLE LOCK: live_action
# CHAR: VALERIA: 女主, 29; ROSA: 母亲, 54; HECTOR: 父亲, 56
# SCENE: PUERTA: 走廊; SALA: 客厅

---
[SC-01]
SHOT: 中景, 固定
LOCATION: PUERTA
TIME: 日
CHAR: VALERIA, ROSA
ACTION: VALERIA 推开门，ROSA 站在走廊尽头。
DIALOG: 无
VO: NARR: Abrí la puerta y había ocho personas.
SFX: 门铃
DUR: 7

---
[SC-02]
SHOT: 近景, 缓推
LOCATION: SALA
TIME: 夜
CHAR: VALERIA, HECTOR
ACTION: VALERIA 把遗嘱放在桌上，HECTOR 后退半步。
DIALOG: "你该行礼了。"
VO: NARR: Nadie se sentó donde debía.
SFX: 纸张声
DUR: 8
"""


def _prompt(no, chars, dur, extra=""):
    pics = "\n".join("Picture %d = %s, 29, grey shirt — face reference (Character)." % (i, c)
                     for i, c in enumerate(chars, 1))
    return ("subject_definitions\n%s\n\nsummary\n"
            "[reference generation] A single %d-second live-action vertical-drama shot, EP01 SC%02d.\n"
            "Staging and action: %s\n%s\n" % (pics, dur, no, extra or "…", ""))


def mk_ws(eps=None, prompts=None, bp=None):
    ws = pathlib.Path(tempfile.mkdtemp(prefix="s3cont_"))
    for k in ("03-剧本", "05-分镜", "06-提示词"):
        (ws / k).mkdir(parents=True, exist_ok=True)
    _w(ws / "03-剧本" / "ep_01.md", eps if eps is not None else SCRIPT)
    for no, body in (prompts or {}).items():
        _w(ws / "06-提示词" / ("ep01_sc%02d_prompt.txt" % no), body)
    if bp is not None:
        _wj(ws / "03-剧本" / "blueprint.json", bp)
    return ws


GOOD_PROMPTS = {
    1: _prompt(1, ["Valeria", "Rosa"], 7, "Abrí la puerta y había ocho personas."),
    2: _prompt(2, ["Valeria", "Héctor"], 8, "你该行礼了。 Nadie se sentó donde debía."),
}


def test_parse_script():
    ws = mk_ws()
    sc = SC.parse_script(ws / "03-剧本" / "ep_01.md")
    check("解析出 2 个镜头块", len(sc["shots"]) == 2, str(len(sc["shots"])))
    check("DUR 解析", [s["dur"] for s in sc["shots"]] == [7.0, 8.0], str([s["dur"] for s in sc["shots"]]))
    check("台词典抽取（DIALOG 一句 + VO 两句）",
          sum(len(s["lines"]) for s in sc["shots"]) == 3,
          str([s["lines"] for s in sc["shots"]]))
    check("HEADER 人物登记解析",
          {"valeria", "rosa", "hector"} <= (sc["registered"] or set()), str(sc["registered"]))
    shutil.rmtree(ws, ignore_errors=True)


def test_pictures_split():
    body = ("Picture 1 = Valeria, 29 (Character).\n"
            "Picture 2 = narrow corridor (Environment).\n"
            "Picture 3 = last frame of the previous shot (Continuity).\n")
    chars, envs = SC._pictures(body)
    check("场景不被当人物", chars == ["Valeria"], str(chars))
    check("末帧参考不计人物", len(envs) == 2, str(envs))
    check("重音归一化", SC._key("Héctor") == SC._key("HECTOR") == "hector")


def test_good():
    ws = mk_ws(prompts=GOOD_PROMPTS)
    r = SC.check_episode(ws, 1)
    check("镜数/台词/人物/时长全对齐时通过", r["status"] == "ok", str(r["fail"]))
    check("产物形态识别为 prompt-txt", r["kind"] == "prompt-txt", str(r.get("kind")))
    check("台词命中 3/3", r["lines"] == "3/3", str(r["lines"]))
    shutil.rmtree(ws, ignore_errors=True)


def test_lost_shot():
    ws = mk_ws(prompts={1: GOOD_PROMPTS[1]})
    r = SC.check_episode(ws, 1)
    check("丢镜判 FAIL", r["status"] == "bad" and any("丢镜" in f for f in r["fail"]), str(r["fail"]))
    shutil.rmtree(ws, ignore_errors=True)


def test_line_missing():
    p = dict(GOOD_PROMPTS)
    p[2] = _prompt(2, ["Valeria", "Héctor"], 8, "Staging and action: she puts the will on the table.")
    ws = mk_ws(prompts=p)
    r = SC.check_episode(ws, 1)
    check("台词未落产物判 FAIL",
          r["status"] == "bad" and any("台词" in f for f in r["fail"]), str(r["fail"]))
    shutil.rmtree(ws, ignore_errors=True)


def test_char_swapped():
    p = dict(GOOD_PROMPTS)
    p[2] = _prompt(2, ["Valeria", "Marta"], 8, "你该行礼了。 Nadie se sentó donde debía.")
    ws = mk_ws(prompts=p)
    r = SC.check_episode(ws, 1)
    check("换人（HECTOR→Marta）被判出",
          any("HECTOR" in w or "Marta" in w for w in r["warn"] + r["fail"]),
          str(r["warn"] + r["fail"]))
    shutil.rmtree(ws, ignore_errors=True)


def test_duration_dev():
    p = dict(GOOD_PROMPTS)
    p[2] = _prompt(2, ["Valeria", "Héctor"], 20, "你该行礼了。 Nadie se sentó donde debía.")
    ws = mk_ws(prompts=p)
    r = SC.check_episode(ws, 1)
    check("时长偏差过大判 FAIL",
          any("时长" in f for f in r["fail"]), str(r["fail"]))
    shutil.rmtree(ws, ignore_errors=True)


def test_unregistered_code():
    eps = SCRIPT.replace("CHAR: VALERIA, HECTOR", "CHAR: VALERIA, AGENTE")
    ws = mk_ws(eps=eps, prompts=GOOD_PROMPTS)
    r = SC.check_episode(ws, 1)
    check("未登记代号只告警不判死",
          r["status"] == "ok" and any("未在 HEADER" in w for w in r["warn"]),
          str(r["warn"]) + str(r["fail"]))
    shutil.rmtree(ws, ignore_errors=True)


def test_hook_meta_and_crosslang():
    bp = {"episodes": [{"ep": 1,
                        "cold_open": "★黄金 3 秒：把全剧最高冲突前置到开场（禁止背景铺垫）",
                        "core_conflict": "中文剧情节点", "reversal": "中文反转",
                        "hook": "中文钩子：母亲躲在人群最后"}]}
    ws = mk_ws(prompts=GOOD_PROMPTS, bp=bp)
    r = SC.check_episode(ws, 1)
    check("句库元指令不判 FAIL", r["status"] == "ok", str(r["fail"]))
    check("元指令给出明确告警", any("元指令" in w for w in r["warn"]), str(r["warn"]))
    check("跨语种降级为告警", any("跨语种" in w for w in r["warn"]), str(r["warn"]))
    shutil.rmtree(ws, ignore_errors=True)


def test_hook_really_broken():
    """全中文产物，才能测「承接」而不是被跨语种降级跳过。"""
    def cn(no, chars, dur, body):
        pics = "\n".join("Picture %d = %s（人物参考图）" % (i, c) for i, c in enumerate(chars, 1))
        return "%s\n时长 %d 秒，第 %02d 镜。\n%s\n" % (pics, dur, no, body)

    bp = {"episodes": [{"ep": 1, "cold_open": "灵堂门口被保安扯掉孝布",
                        "core_conflict": "继母宣读伪造遗嘱", "reversal": "她亮出专利编号",
                        "hook": "继母撕碎复印件，说原件早就烧了"}]}
    p = {1: cn(1, ["Valeria", "Rosa"], 7, "厨房里水烧开了，没有人说话。"),
         2: cn(2, ["Valeria", "Héctor"], 8, "你该行礼了。 没有人坐在该坐的位置上。")}
    ws = mk_ws(prompts=p, bp=bp)
    r = SC.check_episode(ws, 1)
    check("首镜真跑偏判 FAIL",
          any("cold_open" in f for f in r["fail"]), str(r["fail"]))
    check("末镜没接住 hook 也判 FAIL",
          any("hook" in f for f in r["fail"]), str(r["fail"]))
    shutil.rmtree(ws, ignore_errors=True)


def test_no_product():
    ws = mk_ws(prompts={})
    r = SC.check_episode(ws, 1)
    check("无产物返回 no-product", r["status"] == "no-product", r["status"])
    rc, out = _quiet(SC.main, ["--workspace", str(ws), "--ep", "1"])
    check("无产物不空转通过（退出码 4）", rc == 4, "rc=%d %s" % (rc, out[-80:]))
    shutil.rmtree(ws, ignore_errors=True)


def test_data_h3_form():
    ws = mk_ws(prompts={})
    _wj(ws / "06-提示词" / "data" / "h3_prompts.json", {
        "01": {"prompt": "Abrí la puerta y había ocho personas. Valeria Rosa", "duration": 7},
        "02": {"prompt": "你该行礼了。 Nadie se sentó donde debía. Valeria Héctor", "duration": 8},
    })
    r = SC.check_episode(ws, 1)
    check("识别 data/h3_prompts.json 形态", r["kind"] == "data-h3", str(r.get("kind")))
    check("data 形态镜数对齐", r.get("product_shots") == 2, str(r.get("product_shots")))
    shutil.rmtree(ws, ignore_errors=True)


def _quiet(fn, argv):
    buf, old = io.StringIO(), sys.argv
    sys.argv = ["script_continuity.py"] + argv
    try:
        with contextlib.redirect_stdout(buf):
            rc = fn()
    finally:
        sys.argv = old
    return rc, buf.getvalue()


def main() -> int:
    for fn in (test_parse_script, test_pictures_split, test_good, test_lost_shot,
               test_line_missing, test_char_swapped, test_duration_dev,
               test_unregistered_code, test_hook_meta_and_crosslang,
               test_hook_really_broken, test_no_product, test_data_h3_form):
        try:
            fn()
        except Exception as e:                                     # noqa: BLE001
            check("%s 抛异常" % fn.__name__, False, repr(e))
    ok = sum(1 for _, c, _ in RESULTS if c)
    for name, cond, detail in RESULTS:
        if not cond:
            print("[FAIL] %s%s" % (name, ("｜" + detail) if detail else ""))
    print("\n%s  %d/%d 通过" % ("[OK]" if ok == len(RESULTS) else "[NG]", ok, len(RESULTS)))
    return 0 if ok == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
