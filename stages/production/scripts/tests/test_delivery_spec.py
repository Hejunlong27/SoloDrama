#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""离线测试：交付规格判定与归一化（delivery_spec）

零网络、零 ffmpeg 依赖 —— 只测纯函数（判据 / 滤镜串 / 目标解析）。
    python stages/production/scripts/tests/test_delivery_spec.py
"""
from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
SCRIPTS = HERE.parent
sys.path.insert(0, str(SCRIPTS))

import delivery_spec as DS          # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))


def fake(w, h, sar="1:1", pix_fmt="yuv420p"):
    """造一条 probe 结果（不读文件）。"""
    n, d = (int(x) for x in sar.split(":"))
    dw = w * (float(n) / float(d))
    return {"path": "x.mp4", "width": w, "height": h, "sar": sar,
            "sar_n": n, "sar_d": d, "dar": "",
            "display_w": round(dw, 2), "display_ratio": round(dw / float(h), 6),
            "pix_ratio": round(w / float(h), 6), "pix_fmt": pix_fmt,
            "fps": 24.0, "frames": 100}


def main() -> int:
    # ---- 1. 目标规格解析 ----
    s = DS.target_from_str("720x1280")
    check("target_from_str 换尺寸", (s["width"], s["height"]) == (720, 1280)
          and abs(s["ratio"] - 0.5625) < 1e-9, str(s))
    check("target_from_str 缺省用 SPEC", DS.target_from_str(None)["width"] == 1080)
    try:
        DS.target_from_str("1080p")
        check("非法写法应报错", False, "没有抛异常")
    except ValueError:
        check("非法写法应报错", True)

    # ---- 2. 合规样本放行 ----
    ok = fake(1080, 1920, "1:1")
    check("1080×1920 SAR 1:1 判合规", DS.judge(ok) == [], str(DS.judge(ok)))

    # ---- 3. 黑边真实成因：SAR 59:60 ----
    bad_sar = fake(1080, 1920, "59:60")
    v = DS.judge(bad_sar)
    check("SAR 59:60 被判不合规", len(v) >= 2 and any("SAR" in x for x in v), str(v))
    check("SAR 59:60 显示比例被算成 0.5531",
          abs(bad_sar["display_ratio"] - 0.553125) < 1e-5, str(bad_sar["display_ratio"]))

    # ---- 4. 1062×1920（RH 按源比例吸附）被判不合规 ----
    v = DS.judge(fake(1062, 1920))
    check("1062×1920 被判不合规", any("显示比例" in x for x in v))
    check("1062×1920 偏差约 1.67%",
          any("1.6" in x or "1.7" in x for x in v), str(v))

    # ---- 5. 672×1216（0.8MP + 32 对齐）被判不合规 ----
    v = DS.judge(fake(672, 1216))
    check("672×1216 被判不合规", any("显示比例" in x for x in v))

    # ---- 6. 10bit 被拦 ----
    v = DS.judge(fake(1080, 1920, pix_fmt="yuv420p10le"))
    check("yuv420p10le 被拦", any("像素格式" in x for x in v), str(v))

    # ---- 7. 容差边界：比例容差只放宽「比例」，不放宽「像素尺寸」----
    #   1078×1920 = 0.5614（比例偏差 0.19%，在 0.3% 容差内）⇒ 只报尺寸，不报比例
    near = fake(1078, 1920)
    v = DS.judge(near)
    check("0.2% 比例偏差不报「显示比例」", not any("显示比例" in x for x in v), str(v))
    check("但像素尺寸仍须精确 1080×1920", any("像素尺寸" in x for x in v), str(v))
    #   1070×1920 = 0.5573（偏差 0.93%）⇒ 比例也报
    check("0.9% 偏差报「显示比例」", any("显示比例" in x for x in DS.judge(fake(1070, 1920))))

    # ---- 8. 归一化滤镜：绝不出现 pad ----
    vf = DS.build_normalize_vf()
    check("归一化滤镜不含 pad", "pad" not in vf, vf)
    check("归一化含 force_original_aspect_ratio=increase", "increase" in vf, vf)
    check("归一化含 crop 与 setsar", "crop=1080:1920" in vf and "setsar=1" in vf, vf)
    check("归一化先按 SAR 还原显示宽度", "iw*sar" in vf, vf)
    check("横屏目标可用", "crop=1920:1080" in DS.build_normalize_vf(DS.target_from_str("1920x1080")))

    # ---- 9. SAR 解析容错 ----
    check("_parse_ratio 认 N/A", DS._parse_ratio("N/A") == (1, 1))
    check("_parse_ratio 认 59:60", DS._parse_ratio("59:60") == (59, 60))
    check("_parse_ratio 认 1/1", DS._parse_ratio("1/1") == (1, 1))

    print("=" * 62)
    print("delivery_spec 离线测试")
    print("=" * 62)
    n_fail = 0
    for name, ok_, detail in RESULTS:
        print("  %s %s%s" % ("[OK]  " if ok_ else "[FAIL]", name, "" if ok_ else "  <- %s" % detail))
        n_fail += 0 if ok_ else 1
    print("-" * 62)
    print("共 %d 例，通过 %d，失败 %d" % (len(RESULTS), len(RESULTS) - n_fail, n_fail))
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
