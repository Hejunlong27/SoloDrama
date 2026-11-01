# -*- coding: utf-8 -*-
"""平台字幕安全区自测（零依赖、零网络、零计费）。

跑法：
    python stages/subtitle/scripts/tests/test_safe_area.py

它证明四件事：
  1. 三种画布（竖屏 1080p / 竖屏 2K / 横屏 1440p）× 三种语言，写出的 ASS 都满足
     「文字块下沿距底 ≥200px」与「文本框宽 ≤70% 视频宽」；
  2. 字号恒等于 `configs/subtitle-styles.json` 的锁定值 × `min(W/1080, H/1920)` ——
     不再有「按百分比算再被行宽压小」这条路径（2026-11-01 删除）；
  3. 断言**真的会拦住**：把 ASS 里的落点手改成"贴边"，`qa_safe_area()` 必须报失败；
  4. 三语落点同一条线（6:4 视觉中心），一行与两行字幕中心不跳。

判据来自平台规则（用户 2026-10-06 给定）：字幕须落在安全区内，距底部至少 200px，
文本框宽度不超过视频宽度的 70%；纵向位置按视觉中心 6:4（距顶:距底）。
"""
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)                 # tests → scripts
REPO = os.path.dirname(os.path.dirname(os.path.dirname(SCRIPTS)))  # → 仓库根
sys.path.insert(0, SCRIPTS)

import subtitle as S          # noqa: E402

CUES = [
    {"start": 0.0, "end": 1.5, "text": "这是一条用来验证安全区的中文字幕",
     "lines": ["这是一条用来验证", "安全区的中文字幕"]},
    {"start": 1.6, "end": 3.0, "text": "第二条", "lines": ["第二条"]},
]

CANVASES = [
    (1080, 1920, "竖屏 1080p"),
    (2160, 3840, "竖屏 2K"),
    (1440, 832, "横屏 1440p"),
]

LANGS = ["zh", "en", "es"]


def _sheet():
    with open(os.path.join(REPO, "configs", "subtitle-styles.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _cfg(lang):
    with open(os.path.join(SCRIPTS, "..", "assets", "config.subtitle.example.json"),
              encoding="utf-8-sig") as fh:
        cfg = json.load(fh)
    cfg["default_language"] = lang
    return S.apply_style_sheet(cfg, _sheet())


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="safearea_")
    sheet = _sheet()
    base_w, base_h = sheet["base"]["width"], sheet["base"]["height"]
    fails = []

    print("=" * 104)
    print("%-10s %-4s %8s %8s %9s %9s %10s %8s"
          % ("画布", "语种", "字号", "期望", "块高", "下沿距底", "文本宽%", "落点y"))
    print("-" * 104)

    for (W, H, label) in CANVASES:
        scale = min(W / float(base_w), H / float(base_h))
        ys = set()
        for lang in LANGS:
            cfg = _cfg(lang)
            p = os.path.join(tmp, "%s_%dx%d.ass" % (lang, W, H))
            info = S.write_ass(CUES, cfg, p, canvas=(W, H))
            qa = S.qa_safe_area(p, cfg)
            want = int(round(sheet["styles"][lang]["font_px"] * scale))
            if info["font_size_px"] != want:
                fails.append("%s/%s 字号 %d ≠ 锁定值 %d"
                             % (label, lang, info["font_size_px"], want))
            if not qa["pass"]:
                fails.append("%s/%s 安全区：%s" % (label, lang, "；".join(qa["failures"])))
            m = re.search(r"\\pos\(\d+,(-?\d+)\)", open(p, encoding="utf-8").read())
            if m:
                ys.add(int(m.group(1)))
            print("%-10s %-4s %6dpx %6dpx %7dpx %8dpx %9.2f%% %8s"
                  % (label, lang, info["font_size_px"], want, info["block_h_px"],
                     info["bottom_px"], info["text_w_pct"],
                     (m.group(1) if m else "-")))
        if len(ys) != 1:
            fails.append("%s 三语落点不一致：%s" % (label, sorted(ys)))

    # 3. 断言真的会拦住：把落点改成贴底（y = 1900）
    cfg = _cfg("zh")
    bad = os.path.join(tmp, "bad.ass")
    S.write_ass(CUES, cfg, bad, canvas=(1080, 1920))
    txt = open(bad, encoding="utf-8").read()
    txt = re.sub(r"\\pos\(\d+,\d+\)", r"\\pos(540,1900)", txt)
    open(bad, "w", encoding="utf-8").write(txt)
    qa = S.qa_safe_area(bad, cfg)
    if qa["pass"]:
        fails.append("把落点改到 1900 仍判通过 —— 断言失效")
    print("-" * 104)
    print("反向用例（落点改到 y=1900）：%s" % ("✅ 被拦住" if not qa["pass"] else "❌ 未拦住"))

    # 4. 一行 / 两行中心同线
    one = os.path.join(tmp, "one.ass")
    two = os.path.join(tmp, "two.ass")
    S.write_ass([{"start": 0, "end": 1, "text": "好。", "lines": ["好。"]}], cfg, one,
                canvas=(1080, 1920))
    S.write_ass([{"start": 0, "end": 1, "text": "一二三四五六七八九十一二",
                  "lines": ["一二三四五六七八九十一二"]}], cfg, two, canvas=(1080, 1920))
    y1 = re.findall(r"\\pos\(\d+,(-?\d+)\)", open(one, encoding="utf-8").read())
    y2 = re.findall(r"\\pos\(\d+,(-?\d+)\)", open(two, encoding="utf-8").read())
    if y1 != y2:
        fails.append("一行/两行落点不同线：%s vs %s" % (y1, y2))
    print("一行/两行落点：%s / %s %s" % (y1, y2, "✅" if y1 == y2 else "❌"))

    print("=" * 104)
    if fails:
        for f in fails:
            print("[FAIL] %s" % f)
        return 1
    print("[OK] 三画布 × 三语全部通过（字号=锁定值×scale，下沿≥200px，文本宽≤70%，落点同线）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
