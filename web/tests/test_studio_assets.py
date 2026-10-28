#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_studio_assets.py —— Studio 界面资产契约（离线）

与 `test_ui_assets.py` 同一套纪律，但作用于 `web/ui/studio/` 子树：
  1. **类名不漏**：HTML/JS 里用到的静态 class，必须在 tokens.css / app.css 里有规则；
  2. **离线优先**：不得引用任何外部资源（无 CDN、无 http(s) 资源、无 @import url(http)）；
  3. **不用 emoji**：跨机器渲染不一致；
  4. **入口与视图齐备**：index.html、外壳模块、11 个视图模块都在，且每个视图导出 render()；
  5. **图标链路不悬空**：index.html 引用的 favicon / apple-touch / manifest 必须真实存在，
     manifest 里登记的每个图标也要存在（这类错浏览器不报错，只是默默用默认图标）。

为什么单独一个文件而不是改 test_ui_assets：
  旧测试只 glob `ui/*.html` / `ui/*.js`（**不递归**），把 Studio 放进 `ui/studio/` 后
  它既不会被误判、也拿不到覆盖；本文件把这份纪律延续到新子树，两边互不干扰。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
STUDIO = WEB / "ui" / "studio"

FAILS = []

# 语义钩子 / 由 JS 动态切换 / 由父级控制，允许没有独立规则
WHITELIST = {
    "active", "disabled", "hidden", "hide", "sel", "on", "clickable", "spacer",
    "mono", "small", "muted", "dim", "tiny", "right", "nowrap", "flex1", "row",
    "col", "stack", "grid", "g2", "g3", "g4", "g21", "g12", "tight", "shell-collapsed",
    "row-sub", "empty-t", "empty-h", "ph-icon", "mtile-ph", "log", "no", "ln",
}

EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\U0001F1E6-\U0001F1FF\uFE0F\u20E3]")
EXTERNAL_RE = re.compile(r"""(?:src|href)\s*=\s*["']https?://|@import\s+url\(\s*["']?https?://""")

VIEWS = ["workbench", "projects", "overview", "pipeline", "creation", "assets",
         "storyboard", "post", "release", "tasks", "cost", "models", "generators",
         "connections", "health", "settings"]


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("  [NG] %s" % msg)
    return cond


def _static_classes(text: str) -> set:
    out = set()
    for m in re.finditer(r'class="([A-Za-z][A-Za-z0-9_\- ]*)"', text):
        for c in m.group(1).split():
            out.add(c)
    # JS 里也有 class="a b" 的模板片段，上面的正则同样能命中
    return out


def _files(pattern: str) -> list:
    return sorted(STUDIO.rglob(pattern))


def test_entries():
    print("[1] 入口与视图模块齐备")
    for name in ("index.html", "js/main.js", "js/api.js", "js/ui.js",
                 "js/store.js", "js/action.js", "css/tokens.css", "css/app.css"):
        check((STUDIO / name).is_file(), "缺少文件 %s" % name)
    for v in VIEWS:
        p = STUDIO / "js" / "views" / ("%s.js" % v)
        check(p.is_file(), "缺少视图 %s.js" % v)
        if p.is_file():
            txt = p.read_text(encoding="utf-8")
            check(re.search(r"export\s+async\s+function\s+render", txt) is not None,
                  "%s.js 未导出 async render()" % v)
    idx = (STUDIO / "index.html").read_text(encoding="utf-8")
    check('type="module"' in idx, "index.html 必须以 ES module 方式加载外壳")
    check("js/main.js" in idx, "index.html 未加载 js/main.js")


def test_css_covers_classes():
    print("[2] 用到的类必须在样式表里有规则")
    css = ""
    for name in ("tokens.css", "app.css"):
        css += (STUDIO / "css" / name).read_text(encoding="utf-8")
    defined = set(re.findall(r"\.([A-Za-z][\w-]*)", css))
    used = set()
    for f in _files("*.html") + _files("*.js"):
        used |= _static_classes(f.read_text(encoding="utf-8"))
    missing = sorted(c for c in used if c not in defined and c not in WHITELIST)
    for c in missing:
        check(False, "样式表缺少 .%s 的规则" % c)
    print("     静态类 %d 个，样式表定义 %d 个，缺失 %d 个"
          % (len(used), len(defined), len(missing)))


def test_offline_first():
    print("[3] 离线优先：不得引用外部资源")
    for f in _files("*.html") + _files("*.css") + _files("*.js"):
        text = f.read_text(encoding="utf-8")
        m = EXTERNAL_RE.search(text)
        check(m is None, "%s 引用了外部资源：%s" % (f.name, (m.group(0)[:60] if m else "")))
        check("cdn." not in text and "unpkg" not in text and "jsdelivr" not in text,
              "%s 出现 CDN 域名" % f.name)


def test_no_emoji():
    print("[4] 不得使用 emoji")
    for f in _files("*.html") + _files("*.css") + _files("*.js"):
        text = f.read_text(encoding="utf-8")
        m = EMOJI_RE.search(text)
        check(m is None, "%s 出现 emoji：%r" % (f.name, m.group(0) if m else ""))


def test_no_secret_or_shell():
    print("[5] 前端不得出现密钥字段 / 命令拼接")
    for f in _files("*.js"):
        text = f.read_text(encoding="utf-8")
        for bad in ("RUNNINGHUB_API_KEY", "RH_API_KEY", "child_process", "execSync"):
            check(bad not in text, "%s 出现 %s" % (f.name, bad))
    # 前端只能通过 /api/* 与 /media 取数，不允许出现 file:// 或绝对盘符请求
    for f in _files("*.js"):
        text = f.read_text(encoding="utf-8")
        check("file://" not in text, "%s 出现 file:// 请求" % f.name)


def test_brand_assets():
    print("[6] 图标：引用的文件必须存在，manifest 必须自洽")
    img = STUDIO / "img"
    need = ["logo.svg", "logo-mark.svg", "logo-mark-light.svg", "logo-square.svg",
            "logo-maskable.svg", "icon-192.png", "icon-512.png", "icon-maskable-512.png",
            "apple-touch-icon.png", "favicon-16.png", "favicon-32.png", "favicon.ico"]
    for n in need:
        p = img / n
        check(p.is_file(), "缺少图标文件 img/%s" % n)
        if p.is_file():
            check(p.stat().st_size > 100, "img/%s 太小（%d B），可能是坏文件" % (n, p.stat().st_size))

    idx = (STUDIO / "index.html").read_text(encoding="utf-8")
    links = re.findall(r'<link[^>]+href="([^"]+)"[^>]*>', idx)
    brand_links = [h for h in links if h.startswith("img/") or h.endswith(".webmanifest")]
    check(len(brand_links) >= 4, "index.html 里的图标/清单声明太少：%s" % brand_links)
    for href in brand_links:
        check((STUDIO / href).is_file(), "index.html 引用了不存在的 %s" % href)

    mf = STUDIO / "manifest.webmanifest"
    check(mf.is_file(), "缺少 manifest.webmanifest")
    if mf.is_file():
        try:
            data = json.loads(mf.read_text(encoding="utf-8"))
        except ValueError as exc:
            data = {}
            check(False, "manifest.webmanifest 不是合法 JSON：%s" % exc)
        icons = data.get("icons") or []
        check(len(icons) >= 3, "manifest 至少要有 3 个图标，实际 %d" % len(icons))
        check(any("maskable" in str(i.get("purpose") or "") for i in icons),
              "manifest 缺少 maskable 图标（Android 主屏会被裁掉边）")
        for it in icons:
            src = str(it.get("src") or "")
            check((STUDIO / src).is_file(), "manifest 里的图标不存在：%s" % src)
        for k in ("name", "short_name", "start_url", "display", "theme_color"):
            check(bool(data.get(k)), "manifest 缺字段 %s" % k)

    # 品牌区必须用正式图标，不能再退回「SD」文字占位
    check("brand-mark" in idx, "index.html 里没有 .brand-mark")
    check('<img src="img/logo.svg"' in idx, "品牌区应使用 img/logo.svg（不要退回文字占位）")

    # 图标主色必须与设计 Token 的品牌色一致，否则侧栏图标会「偏色」
    tokens = (STUDIO / "css" / "tokens.css").read_text(encoding="utf-8")
    m = re.search(r"--accent://s*#([0-9a-fA-F]{6})", tokens)
    logo = (img / "logo.svg").read_text(encoding="utf-8")
    if m:
        check("#" + m.group(1).lower() in logo.lower(),
              "logo.svg 的主色应与 tokens.css 的 --accent（#%s）一致" % m.group(1))
    check('viewBox="0 0 64 64"' in logo, "logo.svg 应为 1:1 的 64 视口（方图标）")


if __name__ == "__main__":
    for fn in (test_entries, test_css_covers_classes, test_offline_first,
               test_no_emoji, test_no_secret_or_shell, test_brand_assets):
        fn()
    print("-" * 60)
    if FAILS:
        print("[FAIL] %d 项未通过" % len(FAILS))
        sys.exit(1)
    print("[OK] Studio 界面资产契约全部通过")
