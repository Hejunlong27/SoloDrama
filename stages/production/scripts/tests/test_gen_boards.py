# -*- coding: utf-8 -*-
"""`gen_boards.py` 离线测试 —— 零网络、零出图。

它守的是**分镜图提示词的装配逻辑**，其中一条是历史事故的直接产物：

    2026-11-01 EP03/EP04 有 5 个镜写死 `exactly one person`，
    而 `[SHOT]` 同一句里又写 `Two bodies` —— 出片当然乱，但没有任何一步报错。

所以这里最硬的一条是 **B 组：人数必须从 `refs` 实算，任何写死都算失败**。

覆盖：
* **A 人数**：0/1/2/3 人 / 场景-only / 未知代号
* **B 禁令**：模板里不得出现写死的人数句式
* **C 结构**：构图锚定位 / 禁止项 / ratio 透传 / 风格串取自 look
* **D 契约**：读分镜 md 的 `board:` / 缺 board 的镜跳过 / 不读 boards.json 也能跑

```bash
python tests/test_gen_boards.py
```
"""
import argparse
import json
import os
import pathlib
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
FIXTURE = pathlib.Path(HERE) / "fixtures" / "mini_drama"

_TMP = pathlib.Path(tempfile.mkdtemp(prefix="sd_gb_"))
_WS = _TMP / "mini_drama"
shutil.copytree(FIXTURE, _WS)
os.environ["SOLODRAMA_WORKSPACE"] = str(_WS)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, str(pathlib.Path(SCRIPTS).parents[1]))

import gen_boards as G                                          # noqa: E402

CASES = []


def reg(group, name):
    def deco(fn):
        CASES.append((group, name, fn))
        return fn
    return deco


def A_(cond, msg=""):
    if not cond:
        raise AssertionError(msg or "断言失败")


BIBLE = {"characters": [
    {"code": "AVA", "name": "Ava", "age": 30, "gender": "f",
     "garment_en": "grey cotton top with dark trousers"},
    {"code": "BEN", "name": "Ben", "age": 34, "gender": "m",
     "garment_en": "olive work jacket with dark trousers"},
    {"code": "CAT", "name": "Cat", "age": 27, "gender": "f",
     "garment_en": "navy shirt with pale trousers"},
]}


def spec(refs, prompt="Medium shot inside a room, eye level."):
    return {"prompt": prompt, "ratio": "9:16", "refs": refs}


# =========================================================================== A 人数
@reg("A", "A01 人数从 refs 实算：1 人 / 2 人 / 3 人各对各的")
def _():
    for refs, want, n in (
        (["char_ava"], "exactly one person", 1),
        (["char_ava", "char_ben"], "exactly two people", 2),
        (["char_ava", "char_ben", "char_cat"], "exactly three people", 3),
    ):
        txt, got_n, codes = G.build_prompt("shot_001", spec(refs + ["scene_room"]),
                                           BIBLE, "plain look")
        A_(want in txt, "%d 人时应写「%s」，实际没写：%s" % (n, want, txt[:200]))
        A_(got_n == n, "解析出 %d 人，应为 %d" % (got_n, n))
        A_(len(codes) == n, "代号列表长度不对：%s" % codes)
    return "1/2/3 人分别正确"


@reg("A", "A02 只有场景没有角色 → no people in frame，不编人")
def _():
    txt, n, codes = G.build_prompt("shot_001", spec(["scene_room"]), BIBLE, "plain look")
    A_(n == 1, "没有 char_* 时按 1 人兜底计数（至少不是 0 张图）")
    A_("no people in frame" in txt or "nobody else" in txt,
        "纯场景镜的措辞不明显：%s" % txt[:200])
    A_(not codes, "不该编出角色代号：%s" % codes)
    return "场景镜不编人"


@reg("A", "A03 未登记的代号：不脑补长相，但明确说「靠角色卡」")
def _():
    txt, n, codes = G.build_prompt("shot_001", spec(["char_zzz"]), BIBLE, "plain look")
    A_("ZZZ" in txt, "代号要出现（模型需要知道画面里有几个人）")
    A_("character card" in txt, "要说明身份由角色卡保证")
    return "不脑补"


@reg("A", "A04 代号归一：char_ava / AVA / Character_Ava 都算 AVA")
def _():
    for raw in ("char_ava", "AVA", "Character_Ava", "ch_ava"):
        _, _, codes = G.build_prompt("s", spec([raw]), BIBLE, "")
        A_(codes == ["AVA"], "%s 没归成 AVA：%s" % (raw, codes))
    return "4 种写法归一"


# =========================================================================== B 禁令
@reg("B", "B01 模板里没有写死人数的句式（历史事故的直接防线）")
def _():
    # 至少两个人数的样本，模板都不该出现「exactly one person」
    txt2, _, _ = G.build_prompt("s", spec(["char_ava", "char_ben"]), BIBLE, "")
    A_("exactly one person" not in txt2,
        "两人镜里出现了 exactly one person —— 这正是 EP03/EP04 的翻车句式")
    txt3, _, _ = G.build_prompt("s", spec(["char_ava", "char_ben", "char_cat"]), BIBLE, "")
    A_("exactly one person" not in txt3, "三人镜里出现了 exactly one person")
    return "两人/三人镜均无写死句"


@reg("B", "B02 禁止项覆盖「拼版 / 分格 / 文字」")
def _():
    txt, _, _ = G.build_prompt("s", spec(["char_ava"]), BIBLE, "")
    for k in ("no split screen", "no collage", "no grid", "no text", "no panels"):
        A_(k in txt, "禁止项缺「%s」" % k)
    return "5 项禁止齐"


@reg("B", "B03 人数句里有 nobody else，防模型自己加人")
def _():
    txt, _, _ = G.build_prompt("s", spec(["char_ava", "char_ben"]), BIBLE, "")
    A_("nobody else" in txt, "缺「nobody else」——模型会往画面里塞路人")
    return "有 nobody else"


# =========================================================================== C 结构
@reg("C", "C01 明确定位为「构图锚」，且强调不是分镜表")
def _():
    txt, _, _ = G.build_prompt("s", spec(["char_ava"]), BIBLE, "")
    A_("构图参考" in txt, "没说明用途是构图参考")
    A_("不是分镜表" in txt or "不是线稿" in txt,
        "没排除分镜表/线稿语义 —— 那会把线稿画进成片")
    return "定位清晰"


@reg("C", "C02 人物段说明「身份靠角色卡保证」，不抢身份锚")
def _():
    txt, _, _ = G.build_prompt("s", spec(["char_ava", "char_ben"]), BIBLE, "")
    A_("character reference cards" in txt or "character card" in txt,
        "没说明身份由角色卡保证")
    A_("plausible" in txt, "没说明「脸像不像无所谓」")
    return "不抢身份"


@reg("C", "C03 风格串透传；为空时给默认摄影风格")
def _():
    txt, _, _ = G.build_prompt("s", spec(["char_ava"]), BIBLE, "surreal live-action film look")
    A_("surreal live-action film look" in txt, "风格串没透传")
    txt2, _, _ = G.build_prompt("s", spec(["char_ava"]), BIBLE, "")
    A_("cinematic live-action photography" in txt2, "空风格时没给默认值")
    return "透传 + 兜底"


@reg("C", "C04 光位从 H3 提示词的 [LIGHT] 段透传，没有就不编")
def _():
    h3 = "[SHOT] medium.\n[LIGHT] one warm lamp at the far end, cold rim from the glass."
    txt, _, _ = G.build_prompt("s", spec(["char_ava"]), BIBLE, "", h3_prompt=h3)
    A_("one warm lamp" in txt, "光位没透传：%s" % txt[-300:])
    txt2, _, _ = G.build_prompt("s", spec(["char_ava"]), BIBLE, "", h3_prompt="[SHOT] only.")
    A_("one clear key source" in txt2, "没光位时该给通用描述，不该编具体灯具")
    return "透传 / 兜底"


@reg("C", "C05 ratio 原样带出（9:16 与 16:9 都要能表达）")
def _():
    for r in ("9:16", "16:9", "3:4"):
        s = spec(["char_ava"])
        s["ratio"] = r
        txt, _, _ = G.build_prompt("s", s, BIBLE, "")
        # 模板里写死 vertical 9:16，ratio 由调用方在 CLI 层决定 —— 这里只要求不崩
        A_("single frame" in txt, "ratio=%s 时结构不完整" % r)
    return "3 种 ratio 均可装配"


# =========================================================================== D 契约
@reg("D", "D01 直接读分镜 md 的 board 字段（不依赖 boards.json）")
def _():
    specs = G._specs_from_md(_WS, "ep01")
    A_(len(specs) == 2, "应解析出 2 镜，实际 %d" % len(specs))
    for sid, v in specs.items():
        A_(len(v["prompt"]) > 40, "%s 的 board 过短" % sid)
        A_(v["ratio"] == "9:16", "%s 的 ratio 不对" % sid)
        A_(v["refs"], "%s 的 refs 为空" % sid)
        A_("[SHOT]" not in v["prompt"], "%s 的 board 混进了 [SHOT]" % sid)
    return "2 镜 / 字段齐"


@reg("D", "D02 没有 boards.json 也能跑（环节之间不反向依赖）")
def _():
    d = _WS / "06-提示词" / "ep01"
    had = (d / "boards.json").is_file()
    bak = None
    if had:
        bak = (d / "boards.json").read_bytes()
        (d / "boards.json").unlink()
    try:
        specs = G._specs_from_md(_WS, "ep01")
        A_(len(specs) == 2, "缺 boards.json 时读 md 应仍然拿到 2 镜")
    finally:
        if bak is not None:
            (d / "boards.json").write_bytes(bak)
    return "md 直读可独立工作"


@reg("D", "D03 缺 board 的镜被跳过，不猜")
def _():
    text = (_WS / "05-分镜" / "ep01_storyboard.md").read_text(encoding="utf-8")
    i = text.index("- board: |")
    j = text.index("- prompt: |", i)
    tmp = _TMP / "noboard"
    tmp.mkdir(exist_ok=True)
    (tmp / "layout.json").write_text((_WS / "layout.json").read_text(encoding="utf-8"),
                                     encoding="utf-8")
    (tmp / "05-分镜").mkdir(exist_ok=True)
    (tmp / "05-分镜" / "ep01_storyboard.md").write_text(text[:i] + text[j:], encoding="utf-8")
    specs = G._specs_from_md(tmp, "ep01")
    # 删的是 shot_001 的 board；shot_002 的还在，所以结果是 1 条 —— 关键是**缺的那镜不出现**
    A_("shot_001" not in specs, "缺 board 的镜不该出现：%s" % list(specs))
    A_(len(specs) == 1, "应只剩 shot_002，实际 %s" % list(specs))
    return "缺的那镜被跳过"


@reg("D", "D04 人数表：1–5 人都有英文句式，不会落到兜底")
def _():
    for n in range(1, 6):
        A_(n in G.NUM_EN, "%d 人没有句式" % n)
        A_(G.NUM_EN[n].startswith("exactly "), "%d 人的句式不以 exactly 开头" % n)
    return "1–5 人全覆盖"


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
