# -*- coding: utf-8 -*-
"""view_sheet.py —— 把「角色身份卡」的提示词统一成新规范

背景
----
2026-11-10 用户给出角色设定图规范：**一张 16:9 横构图**，左边 60% 是严格三视图
（正 / 90° 侧 / 背，同人同比例同服装、头顶到鞋底全部入画），右边 40% 是 2×2 表情四宫格
（Neutral / Happy / Shocked / Angry，只换表情不换人）。

而磁盘上的存量提示词是旧口径，实测有三处**结构性**偏差：

| 项 | 旧提示词 | 新规范 |
|---|---|---|
| 画幅 | 9:16 竖构图（实测出图 1088×1920） | 16:9 横构图 |
| 三视图排布 | `stacked vertically`（纵向堆叠） | 横向并排，占左侧 60% |
| 侧面角度 | `three-quarter side view`（3/4 侧） | 严格 90° 侧面 |
| 表情 | 单独一张 9:16 竖图 | 并入同一张图的右侧 40%，2×2 |

为什么需要这个工具而不是「改模板就完事」
----------------------------------------
改 `stages/creation/skills/*/SKILL.md` 只影响**新生成**的资产库 md。
已经写好的 30 个集、12 个角色的提示词仍在磁盘上，重跑一次出图还是旧画幅。
所以要有一个能对存量 md 做「定向改写」的东西，而且必须：

1. **只改 VIEW / EXP 两个变体的提示词块**，不碰造型（LOOK-*）与正文表格；
2. **默认干跑**，`--apply` 才写盘，写前备份 `.bak_<时间戳>`（与 `creation.write` 同口径）；
3. **改写后按结构自检**：画幅比例、三个视图名、90°、2×2、四种表情名是否都在。
   少一项就不写 —— 宁可报错也不要写进去一段"看起来改了其实没改"的提示词。

它不是「LLM 改写」：全部是确定性的字符串重组，输入什么输出什么可复现。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time

# 新规范里的固定措辞。放成常量而不是散在模板串里 —— 改一次就全站一致。
SHEET_16x9 = "16:9 horizontal composition"
LEFT_60 = ("left 60% of the frame: three full-body views of the same character in a row, "
           "equally spaced, identical height and body proportions, "
           "front view, strict 90-degree side profile view, and back view, "
           "full head to shoe soles, no overlap")
RIGHT_40 = ("right 40% of the frame: a strict 2x2 grid of head-and-shoulders portraits of the "
            "same character with identical framing and head orientation, only the expression "
            "changes: top left Neutral calm, top right Happy joyful, bottom left Shocked, "
            "bottom right Angry")
BG = ("plain pure-white to light-grey seamless studio background, soft even studio light, "
      "character fully visible with clean silhouette")
NEG = ("no text, no watermark, no poster layout, no narrative scene, "
       "no decorative props, no complex background")

# 旧提示词里要摘掉的画幅/角度措辞（会被新措辞取代）
_OLD_PATTERNS = [
    r"9:16 vertical[^,.]*",
    r"\bvertical\b",
    r"stacked vertically[^,.]*",
    r"three-quarter side view",
    r"three-quarter side",
    r"\b2x2 grid[^,.]*",
    r"chest-up framing[^,.]*",
    r"head-and-shoulders[^,.]*",
    r"character turnaround sheet[^,.]*",
    r"four-expression[^,.]*",
    r"in one tall 9:16 frame[^,.]*",
]

# 角色身份描述要保留：从旧提示词里把「年龄/肤色/发型/服装/锚点」那段原样带过来。
# 规则：取第一个逗号之后、出现画幅关键词之前的那一段 —— 这段是「这个人是谁」。
_ID_HINT = re.compile(
    r"(?:\d{1,2}-year-old[^.]*?|[Aa]ged \d{1,2}[^.]*?)(?=,|\.)", re.S)


def _strip_old(prompt: str) -> str:
    """去掉旧口径的画幅/角度/排布措辞，留下人物描述。"""
    s = " " + str(prompt or "").replace("\n", " ") + " "
    for pat in _OLD_PATTERNS:
        s = re.sub(pat, " ", s, flags=re.I)
    s = re.sub(r"\s{2,}", " ", s)
    s = re.sub(r"\s+,", ",", s)
    s = re.sub(r",\s*,", ",", s)
    return s.strip(" ,.")


def _identity(prompt: str) -> str:
    """从旧提示词里提取「人物身份 + 外观」的连续片段，用于保留一致性。"""
    m = _ID_HINT.search(str(prompt or ""))
    if not m:
        return ""
    seg = m.group(0).strip(" ,.")
    # 截到「服装/背景」之前：这几类词之后属于造型或布景，不是身份
    cut = re.search(r"\b(wearing|dressed|in a |against|background|lighting)\b", seg, re.I)
    if cut:
        seg = seg[:cut.start()].strip(" ,.")
    return seg


def build_view_prompt(old_view: str, old_exp: str = "", style: str = "", identity: str = "") -> str:
    """旧 VIEW / EXP → 一张 16:9 身份卡的提示词。

    风格词（`style`）放在最前面：它与 `style_lock` 同源，换画风时只换这一段。
    """
    ident = _identity(old_view) or _identity(old_exp) or str(identity or "").strip()
    # 旧 VIEW 里 `wearing …` 之后是这套造型的服装，属于身份卡的一部分（三视图要求同服装）
    wearable = ""
    m = re.search(r"\bwearing ([^,.]*(?:,[^,.]*){0,4})", str(old_view or ""), re.I)
    if m:
        wearable = "wearing " + m.group(1).strip(" ,.")

    parts = []
    if style:
        parts.append(style.strip().rstrip("."))
    parts.append("professional film character design sheet, %s" % SHEET_16x9)
    parts.append(LEFT_60)
    parts.append("the three views must be the same person: identical height and body "
                 "proportions, identical hairstyle, hair color and facial structure, identical "
                 "clothing, shoes and accessories, stationary props preserved, natural standing "
                 "pose, no exaggerated action that hides garment structure")
    parts.append(RIGHT_40)
    parts.append("the four panels must be the same person: identical face shape, facial feature "
                 "proportions, skin tone, hairstyle, apparent age, makeup and distinguishing "
                 "facial marks")
    if ident:
        parts.append(ident)
    if wearable:
        parts.append(wearable)
    parts.append(BG)
    parts.append(NEG)
    return ", ".join(p.strip().strip(",") for p in parts if p and p.strip())


# --- 结构自检：写盘前的硬门槛 -------------------------------------------------
def check(prompt: str) -> list:
    """返回缺失项列表；空列表 = 合格。

    这不是「风格建议」，是**能不能拿去出图**的判据：
    少了 90° 就会出 3/4 侧、少了 2x2 就会出四张竖图、少了表情名就会瞎配。
    """
    p = str(prompt or "").lower()
    need = [
        ("16:9", "16:9" in p),
        ("左侧60%", "left 60%" in p),
        ("右侧40%", "right 40%" in p),
        ("正面视图", "front view" in p),
        ("严格90度侧面", "90-degree side" in p or "90 degree side" in p),
        ("背面视图", "back view" in p),
        ("2x2四宫格", "2x2" in p),
        ("表情Neutral", "neutral" in p),
        ("表情Happy", "happy" in p),
        ("表情Shocked", "shocked" in p),
        ("表情Angry", "angry" in p),
        ("禁止海报式", "no poster layout" in p),
        ("禁止故事场景", "no narrative scene" in p),
    ]
    return [name for name, ok in need if not ok]


# --- 对 md 的定向改写 ---------------------------------------------------------
# `**三视图**` / `**表情四态**` 之后紧跟的围栏块。与 md2pack._fence_after 同口径。
_VIEW_BLOCK = re.compile(
    r"(\*\*三视图\*\*\s*\n+```[a-zA-Z]*\n)(.*?)(\n```)", re.S)
_EXP_BLOCK = re.compile(
    r"(\*\*表情(?:四态)?\*\*\s*\n+```[a-zA-Z]*\n)(.*?)(\n```)", re.S)
_STYLE_RE = re.compile(r"\*\*胶片[：:]\s*(.+?)\*\*")


def _context_identity(text: str, at: int) -> str:
    """从资产块表格取身份/一致性锚点，补足旧提示词里没有年龄的存量卡。"""
    head = text.rfind("\n### ", 0, at)
    if head < 0:
        head = text.rfind("### ", 0, at)
    if head < 0:
        return ""
    context = text[head:at]
    parts = []
    for label in ("身份", "一致性锚点", "用途", "设定"):
        m = re.search(r"^\|\s*%s\s*\|\s*([^|]+)\|" % re.escape(label), context, re.M)
        if not m:
            continue
        value = m.group(1).strip()
        if value and value not in ("参考资产", "待填", "待定", "—", "-"):
            parts.append(value)
    return "；".join(parts)


def rewrite_md(text: str, *, style: str = "") -> tuple:
    """→ (新文本, 改动清单, 自检失败清单)。纯函数，不碰磁盘。"""
    changes = []
    failures = []

    def do_view(m):
        old = m.group(2)
        # 同一角色段内的 EXP 也要拿到；这里先只替换 VIEW 本体，EXP 在下一轮合并
        new = build_view_prompt(old, "", style, identity=_context_identity(text, m.start()))
        miss = check(new)
        if miss:
            failures.append({"code": "VIEW", "missing": miss})
        changes.append({"code": "VIEW", "before": len(old), "after": len(new)})
        return m.group(1) + new + m.group(3)

    def do_exp(m):
        # 新规范把表情并入身份卡 → EXP 不再需要独立出图。
        # 不删块（删了会破坏「四态说明」的语境），而是标注为已合并。
        old = m.group(2)
        new = ("[已并入上一张三视图的右侧 40%：2x2 四宫格 Neutral / Happy / Shocked / Angry。"
               "这一块保留作文案备查，不再单独出图。]\n\n原提示词：\n" + old)
        changes.append({"code": "EXP", "before": len(old), "after": len(new), "merged": True})
        return m.group(1) + new + m.group(3)

    out = _VIEW_BLOCK.sub(do_view, text)
    out = _EXP_BLOCK.sub(do_exp, out)
    return out, changes, failures


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="把角色身份卡提示词统一成 16:9 三视图+表情四宫格")
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--apply", action="store_true", help="写盘（默认只干跑）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    ws = pathlib.Path(args.workspace).expanduser()
    md = ws / "00-创作" / "02-资产库.md"
    if not md.is_file():
        print(json.dumps({"ok": False, "reason": "no_md", "path": str(md)}, ensure_ascii=False))
        return 2

    text = md.read_text(encoding="utf-8")
    style = ""
    sm = _STYLE_RE.search(text)
    if sm:
        style = sm.group(1).strip()

    out, changes, failures = rewrite_md(text, style=style)
    result = {"ok": not failures, "path": str(md), "style": style,
              "changes": changes, "failures": failures,
              "applied": False}

    if failures:
        # 有自检失败就**不写盘**：写进去只会得到一张看着改了、其实缺项的提示词
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 3

    if args.apply:
        if out == text:
            result["reason"] = "no_change"
        else:
            bak = md.with_name("%s.bak_%d%s" % (md.stem, int(time.time()), md.suffix))
            bak.write_text(text, encoding="utf-8", newline="")
            md.write_text(out, encoding="utf-8", newline="")
            result.update({"applied": True, "backup": str(bak)})

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
