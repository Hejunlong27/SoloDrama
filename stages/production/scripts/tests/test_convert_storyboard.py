# -*- coding: utf-8 -*-
"""`convert_storyboard.py` 离线测试 —— 零网络、零计费。

它守的是**数据契约**，坏了会连环炸：
分镜字段 → 五文件 → 出片槽位，任何一环错位都不会报错，只会让成片「人不对/景不对」。

覆盖：
* **A 解析**：5 字段 / `board: |` 块标量 / 不吞掉后面的 `prompt:` / 死字段识别
* **B Picture 重排**：整体 +1 / 分镜图说明插在 `[REFS]` 首 / 编号与图片数一致
* **C 五文件**：board_ref / crop 1×1 / characters 与 scenes 原样透传
* **D 健壮性**：缺 board / 缺 prompt / shot_id 重复

```bash
python tests/test_convert_storyboard.py
```
"""
import argparse
import json
import os
import pathlib
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
FIXTURE = pathlib.Path(HERE) / "fixtures" / "mini_drama"

_TMP = pathlib.Path(tempfile.mkdtemp(prefix="sd_cv_"))
_WS = _TMP / "mini_drama"
shutil.copytree(FIXTURE, _WS)
# 强制覆盖：环境里可能残留一个指向已删目录的旧值，setdefault 不会改它
os.environ["SOLODRAMA_WORKSPACE"] = str(_WS)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, str(pathlib.Path(SCRIPTS).parents[1]))

import convert_storyboard as C                                  # noqa: E402

CASES = []


def reg(group, name):
    def deco(fn):
        CASES.append((group, name, fn))
        return fn
    return deco


def A_(cond, msg=""):
    if not cond:
        raise AssertionError(msg or "断言失败")


def md_text() -> str:
    return (_WS / "05-分镜" / "ep01_storyboard.md").read_text(encoding="utf-8")


def parsed():
    return C.parse_md(md_text())


def built():
    return C.build(parsed(), _WS, ep="ep01")


# =========================================================================== A 解析
@reg("A", "A01 5 字段全部解析出来，board 不是字面量")
def _():
    rows = parsed()
    A_(len(rows) == 2, "应解析出 2 镜，实际 %d" % len(rows))
    f = rows[0]["fields"]
    for k in ("duration", "ratio", "refs", "board"):
        A_(k in f, "缺字段 %s" % k)
    A_(f["board"] not in ("|", "|-"), "board 被解析成块标记了：%r" % f["board"])
    A_(len(f["board"]) > 40, "board 内容过短（%d 字）" % len(f["board"]))
    A_(rows[0]["prompt"].startswith("[Shot 1]"), "prompt 没解析出来")
    return "%d 镜 / board %d 字" % (len(rows), len(f["board"]))


@reg("A", "A02 board 块不会吞掉后面的 prompt 块")
def _():
    rows = parsed()
    b = rows[0]["fields"]["board"]
    A_("[SHOT]" not in b, "board 里混进了 [SHOT] —— 块解析越界了")
    A_("[REFS]" not in b, "board 里混进了 [REFS]")
    A_("[SUBJECT]" not in b, "board 里混进了 [SUBJECT]")
    A_("[SHOT]" in rows[0]["prompt"], "prompt 反而被挤掉了")
    return "board 干净 / prompt 完整"


@reg("A", "A03 已删字段（banana_prompt / time / crop）被识别为死字段")
def _():
    text = md_text().replace(
        "- ratio: 9:16\n", "- ratio: 9:16\n- banana_prompt: 旧的九宫格提示词\n", 1)
    rows = C.parse_md(text)
    dead = rows[0]["fields"].get("_dead")
    A_(dead, "banana_prompt 没被归成死字段：%s" % rows[0]["fields"])
    A_("banana_prompt" in dead, "死字段要记**原名**（否则用户不知道该删哪行）：%s" % dead)
    return "死字段可识别"


@reg("A", "A04 没写 `board: |` 的镜，board 为空（不猜）")
def _():
    text = md_text()
    i = text.index("- board: |")
    j = text.index("- prompt: |", i)
    rows = C.parse_md(text[:i] + text[j:])
    A_(not rows[0]["fields"].get("board"), "缺 board 时应为空，实际：%r"
        % rows[0]["fields"].get("board"))
    return "缺 board 留空"


# =========================================================================== B Picture 重排
@reg("B", "B01 编号整体 +1，且分镜图说明插在 [REFS] 之后")
def _():
    txt = "[REFS] <Picture 1> AVA — a woman. <Picture 2> the room only."
    out, mx = C.renumber_pictures(txt, has_board=True)
    A_(mx == 3, "最大编号应为 3，实际 %d" % mx)
    A_("<Picture 1> this frame itself" in out, "分镜图说明没插进去")
    A_("<Picture 2> AVA" in out, "AVA 应变成 2")
    A_("<Picture 3> the room only" in out, "场景应变成 3")
    # 说明必须在 AVA 之前
    A_(out.index("this frame itself") < out.index("AVA"), "说明没排在角色前面")
    return "1→分镜图，2/3 顺移"


@reg("B", "B02 没有分镜图时只平移，不插说明（不硬造结构）")
def _():
    txt = "[REFS] <Picture 1> AVA."
    out, mx = C.renumber_pictures(txt, has_board=False)
    A_("this frame itself" not in out, "不该插分镜图说明")
    A_(mx == 1, "最大编号应保持 1")
    return "无 board 不平移"


@reg("B", "B03 编号必须闭合到「分镜图 + 角色 + 场景」的张数")
def _():
    files, problems, stats = built()
    h3 = files["h3_prompts.json"]
    shots = {s["shot_id"]: s for s in files["shots.json"]}
    for sid, v in h3.items():
        nums = [int(x) for x in C._PIC_RE.findall(v["prompt"])]
        s = shots[sid]
        n_img = (1 if s.get("board_ref") else 0) + len(s.get("character_refs") or []) \
            + len(s.get("scene_refs") or [])
        A_(max(nums) == n_img, "%s：编号最大 %d ≠ 图片数 %d" % (sid, max(nums), n_img))
        A_(sorted(set(nums)) == list(range(1, n_img + 1)), "%s：编号不连续 %s" % (sid, nums))
    return "2 镜编号闭合"


@reg("B", "B04 同一份 md 重复构建结果一致（可重入）")
def _():
    a = json.dumps(built()[0], ensure_ascii=False, sort_keys=True)
    b = json.dumps(built()[0], ensure_ascii=False, sort_keys=True)
    A_(a == b, "两次构建结果不同")
    return "逐字节一致"


# =========================================================================== C 五文件
@reg("C", "C01 输出恰好五个文件，键名固定")
def _():
    files, _, _ = built()
    A_(set(files) == {"shots.json", "boards.json", "h3_prompts.json",
                      "characters.json", "scenes.json"},
        "文件集合不对：%s" % sorted(files))
    return "5 文件"


@reg("C", "C02 shots.json：board_ref 带集号、crop 1×1")
def _():
    files, _, _ = built()
    s = files["shots.json"][0]
    A_(s["board_ref"] == "board_ep01_shot_001", "board_ref 不对：%s" % s["board_ref"])
    A_(s["crop"] == {"rows": 1, "cols": 1}, "crop 应是 1×1（分镜图整张不切）：%s" % s["crop"])
    A_(s["character_refs"] == ["char_ava"], "角色顺序变了：%s" % s["character_refs"])
    A_(s["scene_refs"] == ["scene_room"], "场景没分流出来：%s" % s.get("scene_refs"))
    return "board_ref / crop / 分流 正确"


@reg("C", "C03 boards.json：每镜一条，prompt 非空、refs 原样")
def _():
    files, _, _ = built()
    bd = files["boards.json"]
    A_(len(bd) == 2, "应 2 条，实际 %d" % len(bd))
    for sid, v in bd.items():
        A_(len(v["prompt"]) > 40, "%s 的 board 提示词过短" % sid)
        A_(v["ratio"] == "9:16", "%s 的 ratio 不对" % sid)
        A_(isinstance(v["refs"], list) and v["refs"], "%s 的 refs 为空" % sid)
    return "2 条 / 内容非空"


@reg("C", "C04 characters / scenes 原样透传，不改一个字")
def _():
    files, _, _ = built()
    rj = json.loads((_WS / "04-资产" / "refs.json").read_text(encoding="utf-8"))
    A_(files["characters.json"] == (rj.get("characters") or {}), "characters 被改写了")
    A_(files["scenes.json"] == (rj.get("scenes") or {}), "scenes 被改写了")
    return "原样透传"


@reg("C", "C05 h3_prompts：带 duration / ratio / voice")
def _():
    files, _, _ = built()
    v = files["h3_prompts.json"]["shot_001"]
    A_(v.get("duration") == 6.0, "duration 不对：%s" % v.get("duration"))
    A_(v.get("ratio") == "9:16", "ratio 不对")
    A_(v.get("voice") in ("h3", "external", "mute"), "voice 取值非法：%s" % v.get("voice"))
    return "duration=6 / voice=%s" % v.get("voice")


# =========================================================================== D 健壮性
@reg("D", "D01 缺 board 只记统计，不报错（老项目还能跑）")
def _():
    text = md_text()
    i = text.index("- board: |")
    j = text.index("- prompt: |", i)
    files, problems, stats = C.build(C.parse_md(text[:i] + text[j:]), _WS, ep="ep01")
    A_(stats.get("board_missing"), "缺 board 没被记进统计")
    A_("shot_001" in stats["board_missing"], "没点名是哪一镜")
    A_(not [p for p in problems if "board" in p], "缺 board 不该算 problem")
    return "记统计不报错"


@reg("D", "D02 缺 prompt 是硬问题（引擎会直接 FAILED）")
def _():
    text = md_text()
    i = text.index("- prompt: |")
    j = text.index("## shot_002")
    files, problems, stats = C.build(C.parse_md(text[:i] + text[j:]), _WS, ep="ep01")
    A_(any("缺 prompt" in p for p in problems), "缺 prompt 没被报出来：%s" % problems)
    return "报硬问题"


@reg("D", "D03 shot_id 重复被拦下，不会静默取后者")
def _():
    text = md_text().replace("## shot_002", "## shot_001")
    files, problems, stats = C.build(C.parse_md(text), _WS, ep="ep01")
    A_(any("重复" in p for p in problems), "重复没被拦：%s" % problems)
    A_(len(files["shots.json"]) == 1, "重复的镜不该进 shots.json")
    return "拦下重复"


@reg("D", "D04 死字段出现时记统计（告诉用户「你写的没用了」）")
def _():
    text = md_text().replace("- ratio: 9:16\n",
                             "- ratio: 9:16\n- banana_prompt: 旧字段\n", 1)
    files, problems, stats = C.build(C.parse_md(text), _WS, ep="ep01")
    A_(stats.get("dead_fields"), "死字段没被记录")
    return "记 %d 段" % len(stats["dead_fields"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", default="")
    args = ap.parse_args()
    groups = [args.group.upper()] if args.group else ["A", "B", "C", "D"]
    passed = failed = 0
    try:
        for g in groups:
            sel = [c for c in CASES if c[0] == g]
            if not sel:
                continue
            print("【%s 组】%d 例" % (g, len(sel)))
            print("=" * 84)
            for _, name, fn in sel:
                try:
                    note = fn() or ""
                    print("  [PASS] %-52s %s" % (name, note))
                    passed += 1
                except AssertionError as e:
                    print("  [FAIL] %-52s %s" % (name, e))
                    failed += 1
                except Exception as e:                          # noqa: BLE001
                    print("  [ERR ] %-52s %s: %s" % (name, type(e).__name__, e))
                    failed += 1
            print()
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)
    print("=" * 84)
    print("合计 %d 例 ｜ 通过 %d ｜ 失败 %d" % (passed + failed, passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
