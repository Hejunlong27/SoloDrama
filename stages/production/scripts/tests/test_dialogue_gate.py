# -*- coding: utf-8 -*-
"""台词逻辑复核（dialogue_gate）离线测试 —— 零网络、零计费、零依赖。

规则来源：`3d-short-drama-studio/references/dialogue-driven-rules.md`。
这里只测**能机器判**的那几条；「这句有没有功能」这类归内容评审，不进测试。

跑法：
    python stages/production/scripts/tests/test_dialogue_gate.py
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
SCRIPTS = HERE.parent
sys.path.insert(0, str(SCRIPTS))

import dialogue_gate as G          # noqa: E402

CASES = []


def reg(group, name):
    def deco(fn):
        CASES.append((group, name, fn))
        return fn
    return deco


def A_(cond, msg):
    if not cond:
        raise AssertionError(msg)


HEAD = """# TITLE: 测试
# EP: 01/01
# PLATFORM: Test
# CHAR: AVA: 甲; BEN: 乙
"""
HEAD = HEAD.replace("# CHAR: AVA: 甲; BEN: 乙", "# CHAR: AVA, BEN")


def shot(sid, char="AVA", dur=6, dialog="这是第一句台词。", vo="无", action="她走进来。"):
    return """[SC-%s]
SHOT: 中景
CHAR: %s
ACTION: %s
DIALOG: %s
VO: %s
DUR: %d

""" % (sid, char, action, dialog, vo, dur)


def build(shots):
    return HEAD + "\n".join(shots)


def codes(issues):
    return [i["code"] for i in issues if i["level"] == "ERROR"]


def warns(issues):
    return [i["code"] for i in issues if i["level"] == "WARN"]


@reg("D", "D01 合规样本：零硬失败")
def _():
    s = G.parse_script(build([shot("01"), shot("02", dialog="这是第二句台词。")]))
    A_(len(s["shots"]) == 2, "应解析出 2 镜，实际 %d" % len(s["shots"]))
    iss = G.check(s, narration_max=2, lines_per_60s=10)
    A_(not codes(iss), "不应有硬失败：%s" % iss)
    return "2 镜通过"


@reg("D", "D02 E1 单镜超过 2 句台词")
def _():
    s = G.parse_script(build([shot("01", dialog="第一句。第二句。第三句。"), shot("02")]))
    iss = G.check(s, narration_max=2, lines_per_60s=1)
    A_("E1" in codes(iss), "应判 E1：%s" % iss)
    return "E1 命中"


@reg("D", "D03 E2 中式标点长句（CJK > 20 字）")
def _():
    long_cjk = "我从来不曾想过这个家里还有人记得那天夜里发生的事情。"
    s = G.parse_script(build([shot("01", dialog=long_cjk), shot("02")]))
    iss = G.check(s, narration_max=2, lines_per_60s=1)
    A_("E2" in codes(iss), "应判 E2：%s" % iss)
    return "E2 命中（CJK）"


@reg("D", "D04 E2 拉丁长句（> 55 字符）")
def _():
    long_latin = ("Nobody told the night shift, because the notice was posted after "
                  "everyone had already gone home.")
    s = G.parse_script(build([shot("01", dialog=long_latin), shot("02")]))
    iss = G.check(s, narration_max=2, lines_per_60s=1)
    A_("E2" in codes(iss), "应判 E2：%s" % iss)
    return "E2 命中（拉丁）"


@reg("D", "D05 E3 同镜既有旁白又有对白（规则 R3）")
def _():
    s = G.parse_script(build([shot("01", vo="三年后。"), shot("02")]))
    iss = G.check(s, narration_max=2, lines_per_60s=1)
    A_("E3" in codes(iss), "应判 E3：%s" % iss)
    return "E3 命中"


@reg("D", "D06 E4 旁白条数超配额")
def _():
    s = G.parse_script(build([
        shot("01", vo="三年后。"),
        shot("02", dialog=""),
        shot("03", vo="同一时刻。"),
        shot("04", dialog=""),
        shot("05", vo="她不知道。"),
    ]))
    iss = G.check(s, narration_max=2, lines_per_60s=0)
    A_("E4" in codes(iss), "应判 E4：%s" % iss)
    return "E4 命中"


@reg("D", "D07 E5 旁白出现在中段")
def _():
    s = G.parse_script(build([
        shot("01", dialog="开场一句。"),
        shot("02", vo="中段旁白。"),
        shot("03", dialog="收尾一句。"),
    ]))
    iss = G.check(s, narration_max=2, lines_per_60s=1)
    A_("E5" in codes(iss), "应判 E5：%s" % iss)
    return "E5 命中"


@reg("D", "D08 E6 台词密度不足（按实际时长折算）")
def _():
    # 60 秒只有 2 句 → 低于 10 句/60s
    s = G.parse_script(build([
        shot("01", dur=30, dialog="第一句。"),
        shot("02", dur=30, dialog="第二句。"),
    ]))
    iss = G.check(s, narration_max=2, lines_per_60s=10)
    A_("E6" in codes(iss), "应判 E6：%s" % iss)
    # 同样两句但只有 10 秒 → 达标（10 句/60s 折算 2 句）
    s2 = G.parse_script(build([
        shot("01", dur=5, dialog="第一句。"),
        shot("02", dur=5, dialog="第二句。"),
    ]))
    A_("E6" not in codes(G.check(s2, narration_max=2, lines_per_60s=10)), "短集不应误判")
    return "E6 按实际时长折算"


@reg("D", "D09 W1 连续 3 镜零台词（提示，不拦）")
def _():
    s = G.parse_script(build([
        shot("01", dialog=""),
        shot("02", dialog=""),
        shot("03", dialog=""),
    ]))
    iss = G.check(s, narration_max=2, lines_per_60s=0)
    A_("W1" in warns(iss), "应给 W1 提示：%s" % iss)
    A_("W1" not in codes(iss), "W1 不该是硬失败")
    return "W1 只提示"


@reg("D", "D10 W2 空功能台词（词表命中，需人工确认）")
def _():
    s = G.parse_script(build([shot("01", dialog="你好。"), shot("02", dialog="我看到了。")]))
    iss = G.check(s, narration_max=2, lines_per_60s=1)
    A_("W2" in warns(iss), "应给 W2 提示：%s" % iss)
    return "W2 只提示"


@reg("D", "D11 W3 说话人不在本镜 CHAR")
def _():
    s = G.parse_script(build([shot("01", char="AVA", dialog="BEN: 我不在场上。"), shot("02")]))
    iss = G.check(s, narration_max=2, lines_per_60s=1)
    A_("W3" in warns(iss), "应给 W3 提示：%s" % iss)
    return "W3 只提示"


@reg("D", "D12 FFS 空值写法：`无` / 空行都当没有")
def _():
    s = G.parse_script(build([shot("01", vo="无", dialog="一句台词。"), shot("02")]))
    A_(s["shots"][0]["vo"] == "", "`无` 应解析成空旁白，实际 %r" % s["shots"][0]["vo"])
    A_(s["shots"][0]["dialog"] != "", "对白不该被当成空")
    return "空值识别正确"


def main() -> int:
    only = sys.argv[1].upper().lstrip("-") if len(sys.argv) > 1 else ""
    ok = fail = 0
    for group, name, fn in CASES:
        if only and not name.upper().startswith(only):
            continue
        try:
            note = fn()
            ok += 1
            print("[PASS] %s%s" % (name, ("　—— " + note) if note else ""))
        except AssertionError as exc:
            fail += 1
            print("[FAIL] %s\n       %s" % (name, exc))
        except Exception as exc:                                # noqa: BLE001
            fail += 1
            print("[ERR ] %s\n       %s: %s" % (name, type(exc).__name__, exc))
    print("=" * 74)
    print("合计 %d 例 ｜ 通过 %d ｜ 失败 %d" % (ok + fail, ok, fail))
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
