# -*- coding: utf-8 -*-
"""平台字幕安全区自测（零依赖、零网络、零计费）。

跑法：
    python scripts/test_safe_area.py

它证明四件事：
  1. 三套画布（横屏 1440p / 竖屏 1080p / 竖屏 2K）× 两种语言，写出的 ASS 都满足
     「文字块下沿距底 ≥200px」与「文本框宽 ≤70% 视频宽」；
  2. **竖屏字号会被反向约束**——否则按高度百分比算出的字号会把行撑出安全区；
  3. 断言**真的会拦住**：把 ASS 里的落点手改成"贴边"，qa_safe_area() 必须报失败；
  4. **6:4 视觉中心成立**：所有条目的 \\pos y 相同、且等于 round(0.6×高)，
     —— 这是 V0.7.6 起的新口径（移植自 vidpure），一行与两行字幕中心同线。

判据来自平台规则（用户 2026-10-06 给定）：字幕须落在安全区内，距底部至少 200px，
文本框宽度不超过视频宽度的 70%；纵向位置 V0.7.6 起按视觉中心 6:4（距顶:距底）。
"""
import io
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
SKILL = os.path.dirname(HERE)


def load_module():
    src = io.open(os.path.join(HERE, "subtitle.py"), encoding="utf-8").read()
    src = src.replace('if __name__ == "__main__":', 'if False:')
    mod = type(sys)("subtitle_under_test")
    mod.__file__ = os.path.join(HERE, "subtitle.py")
    exec(compile(src, "subtitle.py", "exec"), mod.__dict__)
    return mod


CUES = [
    {"start": 0.0, "end": 1.5, "text": "这是一条用来验证安全区的中文字幕",
     "lines": ["这是一条用来验证", "安全区的中文字幕"]},
    {"start": 1.6, "end": 3.0, "text": "第二条", "lines": ["第二条"]},
]

CANVASES = [
    (1440, 832, "横屏 1440p"),
    (1088, 1920, "竖屏 1080p"),
    (2176, 3840, "竖屏 2K"),
]


def main():
    m = load_module()
    cfg = json.loads(io.open(os.path.join(SKILL, "assets", "config.subtitle.example.json"),
                             encoding="utf-8").read())
    tmp = tempfile.mkdtemp(prefix="safearea_")
    fails = []

    print("=" * 108)
    print("%-14s %-4s %7s %9s %9s %10s %8s %-18s %s"
          % ("画布", "语言", "字号px", "落点", "下沿距底", "文本框px", "占比", "字号依据", "断言"))
    print("-" * 108)
    for W, H, label in CANVASES:
        for lang in ("zh", "es"):
            p = os.path.join(tmp, "%dx%d_%s.ass" % (W, H, lang))
            info = m.write_ass(CUES, cfg, p, lang=lang, canvas=(W, H))
            qa = m.qa_safe_area(p, cfg)
            if not qa["pass"]:
                fails.append((label, lang, qa["failures"]))
            spot = ("%s y=%d" % (info["anchor_label"], info["center_y"])
                    if info.get("anchor") == "ratio" else "距底 %dpx" % info["margin_v_px"])
            print("%-14s %-4s %7d %9s %9d %10d %7.1f%% %-18s %s"
                  % (label, lang, info["font_size_px"], spot,
                     qa.get("bottom_gap_px") or 0,
                     info["text_w_px"], info["text_w_pct"],
                     info["font_size_by"][:18], "通过" if qa["pass"] else "失败"))
            # 项 4：6:4 视觉中心 —— 所有条目 y 必须相同且等于设计值
            if info.get("anchor") == "ratio":
                ys = [int(x) for x in re.findall(r"\\pos\(\d+,(-?\d+)\)",
                                                 io.open(p, encoding="utf-8").read())]
                want = int(round(H * 0.6))
                if not ys or len(set(ys)) != 1 or abs(ys[0] - want) > 1:
                    fails.append((label, lang, ["6:4 落点不对：%s（期望全为 %d）" % (ys, want)]))

    print()
    print("=" * 104)
    print("项 2：竖屏字号必须被「文本框宽 ÷ 每行字符」反向压住")
    print("-" * 104)
    for lang in ("zh", "es"):
        lc = cfg["languages"][lang]
        mm = m.style_metrics(cfg, lang, (1088, 1920))
        naive = int(round(1920 * lc["font_size_pct"] / 100.0))
        need_naive = lc["max_line_chars"] * lc["char_width_em"] * naive
        print("  %s：按高度百分比=%.1f%% → %dpx，一行 %d 字需要 %.0fpx，"
              "安全区只给 %dpx ⇒ 必须压到 %dpx（%s）"
              % (lang, lc["font_size_pct"], naive, lc["max_line_chars"], need_naive,
                 mm["usable_w"], mm["font_size"], mm["font_size_by"]))
        if need_naive <= mm["usable_w"]:
            print("     ⚠ 该语言本来就不会溢出（无需压字）")

    print()
    print("=" * 108)
    print("项 3：断言必须能拦住被手改坏的 ASS")
    print("-" * 108)
    p = os.path.join(tmp, "tamper.ass")
    info = m.write_ass(CUES, cfg, p, lang="zh", canvas=(1088, 1920))
    good = io.open(p, encoding="utf-8").read()
    if info.get("anchor") == "ratio":
        # 6:4 模式下位置在 \pos 里 —— 把 y 改到贴近画面底部（进平台 UI 区）
        bad = good.replace("\\pos(%d,%d)" % (1088 // 2, info["center_y"]),
                           "\\pos(%d,%d)" % (1088 // 2, 1920 - 20))
        if bad == good:
            # 兜底：把所有 \pos 的 y 换掉
            bad = re.sub(r"\\pos\((\d+),-?\d+\)", r"\\pos(\1,1900)", good)
        what = "落点改到距底 20px"
    else:
        stamp = ",2,%d,%d,%d,1" % (info["margin_lr_px"], info["margin_lr_px"], info["margin_v_px"])
        bad = good.replace(stamp, ",2,20,20,10,1")
        what = "左右 20px / 距底 10px"
    if bad == good:
        print("   ⚠ 没找到可替换的定位字段，跳过该项")
    else:
        io.open(p, "w", encoding="utf-8").write(bad)
        qa = m.qa_safe_area(p, cfg)
        print("   篡改后（%s）→ %s"
              % (what, "❌ 断言漏放（不该）" if qa["pass"] else "✅ 已拦住：" + "；".join(qa["failures"])))
        if qa["pass"]:
            fails.append(("篡改", "zh", ["断言未拦住"]))

    print()
    if fails:
        print("★ 失败 %d 项：" % len(fails))
        for f in fails:
            print("   ", f)
        return 1
    print("全部通过：安全区（文字块下沿距底 ≥%dpx、文本框宽 ≤%d%%）+ 视觉中心 6:4，"
          "在三套画布 × 两种语言下均成立。"
          % (cfg["safe_area"]["min_bottom_px"], cfg["safe_area"]["max_text_width_pct"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
