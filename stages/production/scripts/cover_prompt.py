#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""cover_prompt.py —— 封面提示词编译器（AI 直出带字封面，纯标准库）

设计前提（2026-10-20 用户决策）
------------------------------
**封面由 AI 一次画出来，不用程序叠字。** 上一版 `cover_forge.py`（底图 + PIL 排版）
被否决，降级为「AI 拼错字且 inpaint 修不好」时的兜底工具。

本脚本只做三件事，都不碰像素：
  1. 把 brief（剧名/副标/市场/题材/风格锚/人物关系）编译成**五段式提示词**；
  2. 按尺寸档生成可直接喂通道的清单：
       * 本地 ComfyUI → `comfyui_manifest.json`（配 `stages/assets/comfyui/comfy_client.py --spec`）
       * RunningHub 工作流 → `rh_plan.json`（nodeInfoList 计划，nodeId 必须由 probe 提供）
  3. 做**出图前体检**：标题行数/每行字符数/文字块数量/风格锚缺失/尺寸合法性。

为什么标题要自动断行：AI 写字是「画区域」，一行塞 45 个字符必然错字漏字；
拆成 2–3 行、每行 ≤18 字符（西语）是实测成功率最高的形态（见
`stages/production/references/cover/prompt-guide.md` §四）。

用法
----
    # 只打印提示词（人看/贴到任意模型）
    python cover_prompt.py --brief cover_brief.json --print

    # 生成提交清单（默认写当前目录）
    python cover_prompt.py --brief cover_brief.json --emit comfy  --out-dir ./covers
    python cover_prompt.py --brief cover_brief.json --emit rh     --out-dir ./covers

    # 体检（不出文件、不联网）
    python cover_prompt.py --brief cover_brief.json --check

    # 没有 brief 文件时，最小参数直接生成
    python cover_prompt.py --title "ME CASÉ CON UN MULTIMILLONARIO AMNÉSICO" \
        --subtitle "UNA HISTORIA DE AMOR Y MEMORIAS PERDIDAS" --style latam-rain-night --print

brief 字段（全部可选，缺省有合理回落）
-------------------------------------
    market / language      目标市场与语言（只影响提示词里的服装/场景措辞与字符上限）
    style                  风格锚 id（见 prompt-guide.md §三）或直接给 style_anchor 全文
    title / subtitle       标题（必填）、副标
    top_strip              顶部三栏小字，如 ["PAREDO BENYIDON","DRAMA MEXICO CITY","ROSTAR PAUL WATER"]
    credits                底部演职员表/虚构声明一行
    subjects               人物与关系（英文，2–3 句）
    scene                  场景与光位（英文，1–2 句）
    conflict_prop          可指认的冲突物（抓手③），如 "a divorce envelope"
    sizes                  需要哪些档位，如 ["9x16","3x4","16x9"]，缺省 9x16+3x4
    max_chars_per_line     西语默认 18
    negative               追加负面词（会与内置负面词合并去重）
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

# ---------------------------------------------------------------------------
# 风格锚（与 references/cover/prompt-guide.md §三 一致；改这里要同步文档）
# ---------------------------------------------------------------------------
STYLE_ANCHORS = {
    "latam-rain-night": (
        "Cinematic telenovela key art, hyper-realistic photography, 85mm f/1.4, rain-soaked "
        "night street seen through a glass window, warm tungsten practicals against cold blue "
        "neon bokeh, subtle 35mm grain, glossy magazine finish"),
    "latam-mansion-gold": (
        "Luxury drama key art, warm amber chandelier light, marble and dark wood interior, gold "
        "accents, rich shadows, editorial fashion photography, medium format look, elegant and "
        "oppressive"),
    "office-revenge": (
        "Modern revenge drama poster, cold glass-and-steel office at dusk, hard side light through "
        "blinds, desaturated teal palette with one crimson accent, sharp corporate styling, "
        "high contrast"),
    "suspense-noir": (
        "Neo-noir thriller poster, single hard key light, deep blacks, wet asphalt reflections, "
        "smoke haze, anamorphic flare, muted palette, unsettling stillness"),
    "family-estate": (
        "Prestige family saga key art, late-afternoon golden hour, old estate courtyard, dust in "
        "the air, warm earth tones, painterly realism, dignified composition"),
    # ---- 以下对应 style-presets.md 的 P1/P4/P5/P6（补齐六套预设，全部可用 --style 直选）----
    "revenge-cold": (
        "High-end revenge drama key art, cold desaturated steel-blue grade with a single deep "
        "crimson accent, hard directional side light, tailored dark clothing, glossy corporate "
        "interior, restrained and oppressive, editorial photography"),
    "fantasy-violet": (
        "Dark fantasy key art, deep violet and midnight palette with pale moonlight rim, low fog, "
        "subtle supernatural glow, ornate textures, cinematic chiaroscuro, elegant otherworldly mood"),
    "urban-clean": (
        "Contemporary urban romance poster, clean daylight, soft window light, muted teal and "
        "warm skin tones, minimal modern interior, airy negative space, editorial lifestyle "
        "photography"),
    "east-period-gold": (
        "Chinese period drama key art, deep vermilion and antique gold palette, candlelit interior, "
        "carved wood and silk textures, solemn symmetrical composition, painterly realism"),
}

# 尺寸档（宽, 高, 通道用的画幅字符串）
SIZE_PRESETS = {
    "9x16": (1080, 1920, "9:16"),
    "3x4": (1080, 1440, "3:4"),
    "16x9": (1920, 1080, "16:9"),
    "1x1": (1080, 1080, "1:1"),
}
DEFAULT_SIZES = ["9x16", "3x4"]

BASE_NEGATIVE = (
    "gibberish text, misspelled words, extra words, duplicated words, watermark, logo, signature, "
    "extra limbs, deformed hands, extra fingers, duplicate faces, collage, split screen, "
    "picture frame border, cartoon, 3d render, plastic skin, oversaturated")

# 中文字符上限（汉字信息密度高，6 字≈西语 18 字符的视觉宽度）
CJK_RE = re.compile(r"[\u4e00-\u9fff]")

PROMPT_SECTIONS = ("STYLE", "SUBJECTS", "SCENE & LIGHT", "COMPOSITION & TYPOGRAPHY", "TECH")


# ---------------------------------------------------------------------------
# 标题断行：让 AI 少写错字的关键一步
# ---------------------------------------------------------------------------
def max_chars_per_line(brief: dict) -> int:
    if brief.get("max_chars_per_line"):
        return int(brief["max_chars_per_line"])
    return 6 if CJK_RE.search(str(brief.get("title") or "")) else 18


def lines_needed(title: str, limit: int) -> tuple:
    """按「每行 ≤limit」贪心装箱，返回 (需要几行, 最长单行字符数)。

    ★ 为什么不用 split_headline 的结果判断：DP 在「最大行宽相同」时会取行数更少的方案，
      所以 `len(lines)` 可能小于 3，但**仍然放不进 3 行**（每行都超）。验收必须看这个函数。
    """
    raw = str(title or "").strip()
    if not raw:
        return 0, 0
    if CJK_RE.search(raw) and " " not in raw:
        need = -(-len(raw) // limit)
        return need, min(limit, len(raw)) if need <= 1 else limit
    words = raw.split()
    n, cur, longest = 1, 0, 0
    for w in words:
        add = len(w) if cur == 0 else len(w) + 1
        if cur + add <= limit or cur == 0:
            cur += add
        else:
            n += 1
            cur = len(w)
        longest = max(longest, len(w))
    return n, longest


def split_headline(title: str, limit: int = 18, max_lines: int = 3) -> list:
    """把标题切成 ≤max_lines 行、每行尽量 ≤limit 字符，且**词不拆开**。

    做法：k 从 1 到 max_lines，取「最大行宽最小」的那种切法；若存在 ≤limit 的方案就直接用，
    否则退到最窄的 k=max_lines（并在 check 里告警）。
    """
    raw = str(title or "").strip()
    if not raw:
        return [""]
    # 中文没有空格：按字符均分（每行 ≤limit），不按词
    if CJK_RE.search(raw) and " " not in raw:
        n = len(raw)
        k = max(1, min(max_lines, -(-n // limit)))       # ceil(n/limit)
        per = -(-n // k)                                  # ceil(n/k)
        return [raw[i:i + per] for i in range(0, n, per)]
    words = raw.split()
    if not words:
        return [""]
    best = None
    for k in range(1, min(max_lines, len(words)) + 1):
        # DP：把 words 连续切成 k 段，最小化最大段长
        n = len(words)
        prefix = [0]
        for w in words:
            prefix.append(prefix[-1] + len(w) + 1)      # +1 空格

        def seg_len(i, j):
            return prefix[j] - prefix[i] - 1            # 去掉尾部空格

        INF = float("inf")
        dp = [[INF] * (k + 1) for _ in range(n + 1)]
        cut = [[0] * (k + 1) for _ in range(n + 1)]
        dp[0][0] = 0
        for j in range(1, k + 1):
            for i in range(1, n + 1):
                for p in range(j - 1, i):
                    if dp[p][j - 1] == INF:
                        continue
                    val = max(dp[p][j - 1], seg_len(p, i))
                    if val < dp[i][j]:
                        dp[i][j] = val
                        cut[i][j] = p
        if dp[n][k] == INF:
            continue
        lines, i = [], n
        for j in range(k, 0, -1):
            p = cut[i][j]
            lines.append(" ".join(words[p:i]))
            i = p
        lines.reverse()
        cand = (dp[n][k], lines)
        if best is None or cand[0] < best[0]:
            best = cand
        if cand[0] <= limit:
            return lines
    return best[1] if best else [title]


# ---------------------------------------------------------------------------
# 提示词编译
# ---------------------------------------------------------------------------
def _norm_brief(brief: dict) -> dict:
    b = dict(brief or {})
    b.setdefault("market", "es-LATAM")
    b.setdefault("language", "es")
    b.setdefault("style", "latam-rain-night")
    b.setdefault("top_strip", [])
    b.setdefault("credits", "FICTIONAL DRAMA POSTER · UNA PRODUCCIÓN ORIGINAL")
    b.setdefault("sizes", list(DEFAULT_SIZES))
    b.setdefault("subjects", "")
    b.setdefault("scene", "")
    b.setdefault("conflict_prop", "")
    return b


def style_anchor_text(brief: dict) -> str:
    if brief.get("style_anchor"):
        return str(brief["style_anchor"]).strip()
    sid = str(brief.get("style") or "")
    if sid in STYLE_ANCHORS:
        return STYLE_ANCHORS[sid]
    # 允许直接传一段自描述（不是 id 就当成锚句）
    return sid.strip() or STYLE_ANCHORS["latam-rain-night"]


def _typo_block(brief: dict, lines: list) -> str:
    """生成 TYPOGRAPHY 段：逐条写出**确切字符串**，不留「电影标题」这种空话。"""
    title = str(brief.get("title") or "").strip()
    n = len(lines)
    line_desc = {1: "one line", 2: "two balanced lines", 3: "three balanced lines"}.get(n, "%d lines" % n)
    out = ["Typography — render this text exactly, correctly spelled, no extra words:"]
    strip = [str(x).strip() for x in (brief.get("top_strip") or []) if str(x).strip()]
    if strip:
        quoted = "  ".join('"%s"' % s for s in strip)
        out.append('- Top strip: three small caps labels in thin white sans-serif, evenly spaced '
                   'along the top edge: %s.' % quoted)
    out.append('- Headline: "%s" in elegant high-contrast serif capitals, champagne-gold with a '
               'subtle bevel and soft drop shadow, centered in the upper third, broken into %s, '
               'wide letter spacing.' % (title, line_desc))
    if brief.get("subtitle"):
        out.append('- Subtitle: "%s" in cream serif, smaller, centered just above the bottom edge, '
                   'generous tracking.' % str(brief["subtitle"]).strip())
    if brief.get("credits"):
        out.append('- Bottom credits: one line of tiny condensed sans-serif, low contrast, at the '
                   'very bottom: "%s".' % str(brief["credits"]).strip())
    out.append("Text must be fully inside the frame, never cropped, never overlapping faces.")
    if n > 1:
        out.append("Break the headline exactly as these lines, in this order: %s."
                   % " / ".join('"%s"' % ln for ln in lines))
    return "\n".join(out)


def _composition(brief: dict, size_key: str, lines: list) -> str:
    w, h, _ = SIZE_PRESETS[size_key]
    vertical = h >= w
    framing = ("Vertical %dx%d poster. Chest-up two-shot, both faces occupying the middle "
               "two-thirds, the upper third kept dark and empty for type." % (w, h)) if vertical else \
              ("Horizontal %dx%d key art. Two-shot placed on the right two-thirds, the left third "
               "kept dark and empty for type." % (w, h))
    parts = [framing]
    if brief.get("conflict_prop"):
        parts.append("A clearly identifiable conflict object is visible between them: %s."
                     % str(brief["conflict_prop"]).strip())
    parts.append(_typo_block(brief, lines))
    return "\n".join(parts)


def build_prompt(brief: dict, size_key: str) -> dict:
    """编译单档提示词，返回 {size, width, height, aspect, prompt, negative, sections}。"""
    b = _norm_brief(brief)
    if size_key not in SIZE_PRESETS:
        raise KeyError("未知尺寸档 %s（可选 %s）" % (size_key, "/".join(SIZE_PRESETS)))
    w, h, aspect = SIZE_PRESETS[size_key]
    lines = split_headline(str(b.get("title") or ""), max_chars_per_line(b), 3)

    style = "[① STYLE]\n%s." % style_anchor_text(b).rstrip(".")
    subjects = "[② SUBJECTS]\n%s" % (str(b.get("subjects") or "").strip() or
                                    "Two leads, chest-up, eyes locked, minimal physical contact, "
                                    "real skin texture, no glamour retouching.")
    scene = "[③ SCENE & LIGHT]\n%s" % (str(b.get("scene") or "").strip() or
                                       "Night interior behind rain-streaked glass; warm practical "
                                       "key from one side, cold blue spill filling the negative "
                                       "space; shallow depth of field.")
    comp = "[④ COMPOSITION & TYPOGRAPHY]\n%s" % _composition(b, size_key, lines)
    tech = "[⑤ TECH]\n%dx%d, photorealistic, natural skin, filmic color grade." % (w, h)
    prompt = "\n\n".join([style, subjects, scene, comp, tech])

    neg = BASE_NEGATIVE
    if b.get("negative"):
        extra = [x.strip() for x in re.split(r"[,，]", str(b["negative"])) if x.strip()]
        have = {x.strip().lower() for x in neg.split(",")}
        neg = ", ".join([neg] + [x for x in extra if x.lower() not in have])

    return {"size": size_key, "width": w, "height": h, "aspect": aspect,
            "headline_lines": lines, "prompt": prompt, "negative": neg,
            "sections": {"style": style, "subjects": subjects, "scene": scene,
                         "composition": comp, "tech": tech}}


def build_all(brief: dict) -> dict:
    b = _norm_brief(brief)
    items = [build_prompt(b, s) for s in b.get("sizes") or DEFAULT_SIZES]
    return {"brief": {k: v for k, v in b.items() if k != "style_anchor"},
            "style_anchor": style_anchor_text(b),
            "items": items}


# ---------------------------------------------------------------------------
# 出图前体检
# ---------------------------------------------------------------------------
def check_brief(brief: dict) -> tuple:
    """返回 (errors, warnings)。规则来自 prompt-guide.md §四/§九。"""
    b = _norm_brief(brief)
    errs, warns = [], []
    title = str(b.get("title") or "").strip()
    if not title:
        errs.append("缺 title（封面必须有标题）")
    limit = max_chars_per_line(b)
    if title:
        lines = split_headline(title, limit, 3)
        need, longest_word = lines_needed(title, limit)
        if need > 3:
            errs.append("标题放不进 3 行 × %d 字符（按行宽需要 %d 行）：请缩短标题或减少文字块"
                        % (limit, need))
        for ln in lines:
            if len(ln) > limit:
                warns.append("标题行「%s」%d 字符 > %d：拼错概率升高，建议再拆一行或缩短"
                             % (ln, len(ln), limit))
        if len(title) > 45:
            warns.append("标题共 %d 字符，偏长；建议压到 ≤45（3 行 × 15）" % len(title))
        longest_word = max(title.split(), key=len) if title.split() else ""
        if len(longest_word) > limit:
            errs.append("存在超长单词「%s」(%d)，无法断行且必错；请拆分或换词"
                        % (longest_word, len(longest_word)))
    blocks = 1 + (1 if (b.get("top_strip") or []) else 0) + (1 if b.get("subtitle") else 0) \
        + (1 if b.get("credits") else 0)
    if blocks > 4:
        warns.append("文字块 %d 个（>4）：块越多错字概率越高，建议砍掉一块" % blocks)
    if not b.get("subjects"):
        warns.append("缺 subjects：模型会自行编人物，跨图一致性差")
    if not b.get("scene"):
        warns.append("缺 scene：光位不可控，夜景可能拍成白天（反馈 P2-9 同类问题）")
    if CJK_RE.search(title) and len(title) > 12:
        warns.append("中文标题 %d 字，超过 6 字/行的可读性上限（多行也不行），建议重写" % len(title))
    for s in b.get("sizes") or []:
        if s not in SIZE_PRESETS:
            errs.append("未知尺寸档 %s（可选 %s）" % (s, "/".join(SIZE_PRESETS)))
    if not any(str(x).strip() for x in (b.get("top_strip") or [])):
        warns.append("缺 top_strip（顶部三栏假演职员表）：少一块「正规发行海报」的视觉信号")
    return errs, warns


# ---------------------------------------------------------------------------
# 通道清单
# ---------------------------------------------------------------------------
def comfyui_manifest(bundle: dict) -> dict:
    """喂 `stages/assets/comfyui/comfy_client.py --spec` 的清单。

    kind 用 `cover` → client 的 KIND_DIR 里没有这一项，因此产物直接落 `--out` 根目录，
    文件名前缀 = `cover_<ratio>`，正好符合 release_check 的命名识别。
    """
    assets = []
    for it in bundle["items"]:
        assets.append({"id": "cover_%s" % it["size"], "kind": "cover",
                       "prefix": "cover_%s" % it["size"],
                       "name": "封面 %s" % it["size"],
                       "aspect": it["aspect"], "count": 1,
                       "prompt": it["prompt"] + "\n\nNegative prompt: " + it["negative"]})
    return {"_note": "AI 直出封面清单（提示词已含排版指令）；本文件不含任何图像处理",
            "style_lock": "", "aspect": "",
            "assets": assets}


def rh_plan(bundle: dict) -> dict:
    """RunningHub 工作流提交计划。

    **不猜 nodeId**：这里只给出「哪个尺寸对应哪组值」，节点映射由
    `python stages/video/workflow/scripts/run.py probe --kind workflow --id <id>` 得到后回填。
    """
    items = []
    for it in bundle["items"]:
        items.append({
            "size": it["size"], "aspect": it["aspect"],
            "width": it["width"], "height": it["height"],
            "node_values": {
                "prompt": it["prompt"],
                "negative": it["negative"],
                "aspect_ratio": it["aspect"],
                "width": it["width"], "height": it["height"],
            },
        })
    return {"_note": "RunningHub 工作流提交计划；nodeId/fieldName 必须先 probe，禁止凭猜填写",
            "kind": "workflow", "workflow_id": "",
            "aspect_value_map": {"9:16": "9:16 (Portrait Widescreen)",
                                 "3:4": "3:4 (Portrait)", "16:9": "16:9 (Widescreen)",
                                 "1:1": "1:1 (Square)"},
            "items": items}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _load_brief(a) -> dict:
    if a.brief:
        p = pathlib.Path(a.brief).expanduser()
        if not p.is_file():
            raise SystemExit("[FAIL] brief 不存在：%s" % p)
        return json.loads(p.read_text(encoding="utf-8-sig"))
    brief = {}
    for k in ("title", "subtitle", "market", "style", "subjects", "scene",
              "conflict_prop", "credits", "style_anchor"):
        v = getattr(a, k, None)
        if v:
            brief[k] = v
    if a.top_strip:
        brief["top_strip"] = [x.strip() for x in a.top_strip.split("|") if x.strip()]
    if a.sizes:
        brief["sizes"] = [x.strip() for x in a.sizes.split(",") if x.strip()]
    return brief


def main() -> int:
    ap = argparse.ArgumentParser(description="封面提示词编译器（AI 直出带字封面）")
    ap.add_argument("--brief", help="brief JSON 路径（给了就以它为准）")
    ap.add_argument("--title"), ap.add_argument("--subtitle")
    ap.add_argument("--market", default=None)
    ap.add_argument("--style", default=None)
    ap.add_argument("--subjects"), ap.add_argument("--scene")
    ap.add_argument("--conflict-prop", dest="conflict_prop", default=None)
    ap.add_argument("--credits"), ap.add_argument("--style-anchor", dest="style_anchor", default=None)
    ap.add_argument("--top-strip", dest="top_strip", default=None,
                    help='顶部三栏，用 | 分隔："PAREDO BENYIDON|DRAMA MEXICO CITY|ROSTAR PAUL WATER"')
    ap.add_argument("--sizes", default=None, help="逗号分隔，如 9x16,3x4,16x9")
    ap.add_argument("--emit", choices=("comfy", "rh", "prompts"), default="prompts",
                    help="comfy=本地 ComfyUI 清单；rh=RunningHub 计划；prompts=仅提示词 JSON")
    ap.add_argument("--out-dir", dest="out_dir", default=".")
    ap.add_argument("--print", dest="do_print", action="store_true", help="把提示词打到 stdout")
    ap.add_argument("--check", action="store_true", help="只体检，不写文件")
    a = ap.parse_args()

    brief = _load_brief(a)
    errs, warns = check_brief(brief)
    for w in warns:
        print("[WARN] %s" % w)
    if errs:
        for e in errs:
            print("[ERR] %s" % e)
        return 1

    bundle = build_all(brief)
    if a.do_print or a.check:
        for it in bundle["items"]:
            print("\n" + "=" * 74)
            print("尺寸 %s（%dx%d，画幅 %s）｜标题断行：%s"
                  % (it["size"], it["width"], it["height"], it["aspect"],
                     " / ".join(it["headline_lines"])))
            print("=" * 74)
            print(it["prompt"])
        if a.check:
            print("\n[OK] 体检通过" + ("（%d 条告警）" % len(warns) if warns else ""))
            return 0

    if a.emit == "comfy":
        payload, name = comfyui_manifest(bundle), "comfyui_manifest.json"
    elif a.emit == "rh":
        payload, name = rh_plan(bundle), "rh_plan.json"
    else:
        payload, name = bundle, "cover_prompts.json"

    out = pathlib.Path(a.out_dir).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    p = out / name
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8", newline="\n")
    print("\n[OK] 已写出 %s（%d 档）" % (p, len(bundle["items"])))
    if a.emit == "comfy":
        print("     下一步（本地 ComfyUI）：")
        print("       python stages/assets/comfyui/comfy_client.py --spec \"%s\" --out \"%s\""
              % (p, out))
    elif a.emit == "rh":
        print("     下一步（RunningHub）：先 probe 拿 nodeId，再按 rh_plan.items[].node_values 组装 nodeInfoList")
        print("       python stages/video/workflow/scripts/run.py probe --kind workflow --id <workflowId>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
