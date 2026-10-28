#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_studio_assets.py —— Studio 界面资产契约（离线）

与 `test_ui_assets.py` 同一套纪律，但作用于 `web/ui/studio/` 子树：
  1. **类名不漏**：HTML/JS 里用到的静态 class，必须在 tokens.css / app.css 里有规则；
  2. **离线优先**：不得引用任何外部资源（无 CDN、无 http(s) 资源、无 @import url(http)）；
  3. **不用 emoji**：跨机器渲染不一致；
  4. **入口与视图齐备**：index.html、外壳模块、11 个视图模块都在，且每个视图导出 render()。

为什么单独一个文件而不是改 test_ui_assets：
  旧测试只 glob `ui/*.html` / `ui/*.js`（**不递归**），把 Studio 放进 `ui/studio/` 后
  它既不会被误判、也拿不到覆盖；本文件把这份纪律延续到新子树，两边互不干扰。
"""
from __future__ import annotations

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

VIEWS = ["workbench", "projects", "overview", "creation", "assets",
         "storyboard", "post", "release", "tasks", "cost", "models", "settings"]


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


if __name__ == "__main__":
    for fn in (test_entries, test_css_covers_classes, test_offline_first,
               test_no_emoji, test_no_secret_or_shell):
        fn()
    print("-" * 60)
    if FAILS:
        print("[FAIL] %d 项未通过" % len(FAILS))
        sys.exit(1)
    print("[OK] Studio 界面资产契约全部通过")
