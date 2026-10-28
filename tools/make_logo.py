#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""make_logo.py —— 生成品牌图标（SVG 源 + 各尺寸 PNG + favicon.ico）

为什么用脚本生成而不是手工存图
------------------------------
1. 圆角矩形的 path 用手写极易差一个端点（图形闭合不严，渲染出毛刺）；
2. 各尺寸 PNG 必须与 SVG **同一几何**，否则 favicon 与侧栏图标看起来不是同一个东西；
3. 换品牌色 / 调比例时只改下面四个常量，跑一遍即可，不会出现「改了 SVG 忘了 PNG」。

几何（viewBox 0 0 64 64）
    tile    64×64，圆角 14（21.9%，接近 iOS squircle）
    frame   竖屏画幅 28×52，圆角 7，居中 (18,6)-(46,58) —— 短剧就是竖屏
    play    三角 (25,20)-(41,32)-(25,44)，`fill-rule=evenodd` 挖空，
            四周留 5–7px 琥珀边（缩到 16px 才不糊成一坨）

产物（默认写 web/ui/studio/img/）
    logo.svg              主图标（含琥珀底，侧栏 / favicon 共用）
    logo-mark.svg         透明底、深墨 mark（浅色背景用）
    logo-mark-light.svg   透明底、琥珀 mark（深色背景用）
    logo-square.svg       满幅方底（iOS 主屏图标用，系统自己裁圆角）
    logo-maskable.svg     满幅方底 + 20% 安全区（PWA maskable）
    icon-192/512.png      常规应用图标（透明圆角）
    icon-maskable-512.png maskable
    apple-touch-icon.png  180×180 实心方底（透明角在 iOS 上会被填黑）
    favicon-16/32.png     标签页
    favicon.ico           16/32/48/64 多尺寸打包

用法
----
    python tools/make_logo.py                 # 生成并自检
    python tools/make_logo.py --out /tmp/x    # 换个目录
    SOLODRAMA_CHROME="C:/.../chrome.exe" python tools/make_logo.py

依赖：Chrome/Edge 任一（栅格化 SVG）+ Pillow（只为打 .ico）。都不联网。
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "web" / "ui" / "studio" / "img"

# 品牌色与底色：必须与 web/ui/studio/css/tokens.css 的 --accent / ink 一致
AMBER = "#E0A458"
INK = "#171A1F"

# 几何常量（改这里就够，别去手改 SVG）
FRAME = (18, 6, 28, 52, 7)          # x, y, w, h, r
PLAY = (25, 20, 41, 32, 25, 44)     # x1,y1, x2,y2, x3,y3

CHROME_CANDIDATES = [
    os.environ.get("SOLODRAMA_CHROME") or "",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
]


def rrect(x: float, y: float, w: float, h: float, r: float) -> str:
    """圆角矩形 → path（顺时针，从左上角弧后起笔）。"""
    return ("M%g %gH%gA%g %g 0 0 1 %g %gV%gA%g %g 0 0 1 %g %gH%g"
            "A%g %g 0 0 1 %g %gV%gA%g %g 0 0 1 %g %gZ"
            % (x + r, y, x + w - r, r, r, x + w, y + r,
               y + h - r, r, r, x + w - r, y + h,
               x + r, r, r, x, y + h - r,
               y + r, r, r, x + r, y))


def _path() -> str:
    return "%s M%g %gL%g %gL%g %gZ" % (rrect(*FRAME), PLAY[0], PLAY[1],
                                        PLAY[2], PLAY[3], PLAY[4], PLAY[5])


def _head(label: str) -> str:
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" '
            'width="64" height="64"\n     role="img" aria-label="%s">\n'
            "  <title>%s</title>\n" % (label, label))


def svg_tile(label: str = "SoloDrama") -> str:
    """主图标：琥珀圆角底 + 深墨 mark（播放三角是挖空的，透出底色）。"""
    return (_head(label)
            + '  <rect width="64" height="64" rx="14" fill="%s"/>\n' % AMBER
            + '  <path fill="%s" fill-rule="evenodd" d="%s"/>\n' % (INK, _path())
            + "</svg>\n")


def svg_mark(fill: str, label: str = "SoloDrama") -> str:
    """透明底 mark（单色，用于浅底/深底两种场合）。"""
    return (_head(label)
            + '  <path fill="%s" fill-rule="evenodd" d="%s"/>\n' % (fill, _path())
            + "</svg>\n")


def svg_square(scale: float, label: str = "SoloDrama") -> str:
    """满幅方底（无透明角）。iOS 主屏图标由系统裁圆角；maskable 要留安全区。"""
    t = ""
    if scale != 1:
        off = 32 * (1 - scale)
        t = ' transform="translate(%.4f %.4f) scale(%.4f)"' % (off, off, scale)
    return (_head(label)
            + '  <rect width="64" height="64" fill="%s"/>\n' % AMBER
            + '  <g%s><path fill="%s" fill-rule="evenodd" d="%s"/></g>\n' % (t, INK, _path())
            + "</svg>\n")


def find_chrome() -> str:
    for c in CHROME_CANDIDATES:
        if c and Path(c).is_file():
            return c
    got = shutil.which("chrome") or shutil.which("chromium") or shutil.which("msedge")
    if got:
        return got
    raise SystemExit("[FAIL] 找不到 Chrome/Edge（用于把 SVG 栅格化）。"
                     "设 SOLODRAMA_CHROME 指向浏览器可执行文件。")


def render_png(chrome: str, svg_file: Path, size: int, out: Path) -> None:
    """透明底栅格化：body 边距清零、窗口正好等于目标尺寸，像素尺寸才精确。"""
    html = ('<!DOCTYPE html><html><head><meta charset="utf-8"><style>'
            "html,body{margin:0;padding:0;background:transparent}"
            "img{display:block;width:%dpx;height:%dpx}"
            '</style></head><body><img src="%s"></body></html>' % (size, size, svg_file.as_uri()))
    with tempfile.TemporaryDirectory() as td:
        page = Path(td) / "p.html"
        page.write_text(html, encoding="utf-8")
        subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                        "--force-device-scale-factor=1",
                        "--default-background-color=00000000",
                        "--window-size=%d,%d" % (size, size),
                        "--virtual-time-budget=1500",
                        "--screenshot=%s" % out, page.as_uri()],
                       capture_output=True, check=False)
    if not out.is_file() or out.stat().st_size < 100:
        raise SystemExit("[FAIL] 没生成 %s（浏览器栅格化失败）" % out)


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 SoloDrama 图标资产")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="输出目录（默认 web/ui/studio/img）")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    chrome = find_chrome()

    svgs = {
        "logo.svg": svg_tile(),
        "logo-mark.svg": svg_mark(INK),
        "logo-mark-light.svg": svg_mark(AMBER),
        "logo-square.svg": svg_square(1.0),
        "logo-maskable.svg": svg_square(0.8),
    }
    for name, text in svgs.items():
        p = out / name
        p.write_text(text, encoding="utf-8", newline="")
        print("svg  %-24s %5d B" % (name, p.stat().st_size))

    jobs = (
        ("logo.svg", 512, "icon-512.png"),
        ("logo.svg", 192, "icon-192.png"),
        ("logo.svg", 32, "favicon-32.png"),
        ("logo.svg", 16, "favicon-16.png"),
        ("logo-square.svg", 180, "apple-touch-icon.png"),      # iOS：实心方底
        ("logo-maskable.svg", 512, "icon-maskable-512.png"),   # PWA：留安全区
    )
    for src, size, name in jobs:
        p = out / name
        render_png(chrome, out / src, size, p)
        print("png  %-24s %5d B  %dx%d" % (name, p.stat().st_size, size, size))

    from PIL import Image  # noqa: PLC0415
    big = Image.open(out / "icon-512.png")
    if big.mode != "RGBA":
        big = big.convert("RGBA")
    ico = out / "favicon.ico"
    big.save(ico, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
    print("ico  %-24s %5d B" % (ico.name, ico.stat().st_size))

    # ---- 自检：尺寸、透明底、iOS/maskable 满幅 ----
    for name, size in (("icon-512.png", 512), ("icon-192.png", 192),
                       ("favicon-32.png", 32), ("favicon-16.png", 16)):
        im = Image.open(out / name).convert("RGBA")
        if im.size != (size, size):
            raise SystemExit("[FAIL] %s 尺寸 %s != %d" % (name, im.size, size))
        # 16px 圆角抗锯齿会留 alpha=1~12 的残值，不能死等 0
        if im.getpixel((0, 0))[3] > 32:
            raise SystemExit("[FAIL] %s 左上角不透明（应为透明底）" % name)
    for name, size in (("apple-touch-icon.png", 180), ("icon-maskable-512.png", 512)):
        im = Image.open(out / name).convert("RGBA")
        for pt in ((0, 0), (size - 1, 0), (0, size - 1), (size - 1, size - 1)):
            if im.getpixel(pt)[3] != 255:
                raise SystemExit("[FAIL] %s 角落必须不透明（%s）" % (name, pt))
    print("[OK] 尺寸与透明底自检通过 -> %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
