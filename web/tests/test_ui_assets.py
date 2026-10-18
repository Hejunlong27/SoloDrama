#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_ui_assets.py —— 界面资产契约测试（离线）

守住三件事：
  1. **类名不漏**：HTML/JS 里用到的静态 class，样式表里必须有对应规则（防「改了样式但界面塌了」）；
  2. **离线优先**：界面不得引用任何外部资源（不得出现 http/https 的 src/href/@import）——
     控制台要在断网 / 内网环境可用；
  3. **不用 emoji**：跨机器字体渲染不一致，界面一律用 CSS 形状与文字符号。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
UI = WEB / "ui"

FAILS = []

# 允许出现但没有独立样式规则的类（语义钩子 / 由父级控制）
WHITELIST = {"active", "hidden", "clickable", "spacer", "mono", "small", "muted", "user-app"}

# 只认「彩色 emoji」（跨机器渲染不一致）；★ ✓ → 等文字符号属刻意使用，不在此列
EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U0001F1E6-\U0001F1FF\uFE0F\u20E3]"
)

EXTERNAL_RE = re.compile(r"""(?:src|href)\s*=\s*["']https?://|@import\s+url\(\s*["']?https?://""")


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("  [NG] %s" % msg)
    return cond


def _static_classes(text: str) -> set:
    """取 class="..." 里的静态类名。

    只接受「纯类名」写法（字母/数字/下划线/连字符/空格）；含引号、加号、${} 的
    模板拼接串一律跳过，否则会把 JS 表达式误当成类名。
    """
    out = set()
    for m in re.finditer(r'class="([A-Za-z][A-Za-z0-9_\- ]*)"', text):
        for c in m.group(1).split():
            out.add(c)
    return out


# 动态拼接的状态片（`chip ${state}`）会出现的全部取值
DYNAMIC_CHIPS = ["chip done", "chip doing", "chip blocked", "chip todo", "chip amber", "chip info", "chip"]


def test_css_covers_classes():
    print("[1] HTML/JS 用到的类必须在样式表里有规则")
    css = (UI / "styles.css").read_text(encoding="utf-8")
    defined = set(re.findall(r"\.([A-Za-z][\w-]*)", css))
    used = set()
    for f in sorted(UI.glob("*.html")) + sorted(UI.glob("*.js")):
        used |= _static_classes(f.read_text(encoding="utf-8"))
    missing = sorted(c for c in used if c not in defined and c not in WHITELIST)
    for c in missing:
        check(False, "样式表缺少 .%s 的规则" % c)
    print("     静态类 %d 个，样式表定义 %d 个，缺失 %d 个" % (len(used), len(defined), len(missing)))


def test_dynamic_chips():
    print("[2] 动态状态片必须有样式")
    css = (UI / "styles.css").read_text(encoding="utf-8")
    for combo in DYNAMIC_CHIPS:
        sel = "." + combo.replace(" ", ".")
        check(sel in css, "缺少状态片样式 %s" % sel)


def test_offline_first():
    print("[3] 离线优先：不得引用外部资源")
    for f in sorted(UI.glob("*.html")) + sorted(UI.glob("*.css")) + sorted(UI.glob("*.js")):
        text = f.read_text(encoding="utf-8")
        m = EXTERNAL_RE.search(text)
        check(m is None, "%s 引用了外部资源：%s" % (f.name, (m.group(0)[:60] if m else "")))
        check("cdn." not in text and "unpkg" not in text and "jsdelivr" not in text,
              "%s 出现 CDN 域名" % f.name)


def test_no_emoji():
    print("[4] 不得使用 emoji")
    for f in sorted(UI.glob("*.html")) + sorted(UI.glob("*.js")) + sorted(UI.glob("*.css")):
        text = f.read_text(encoding="utf-8")
        m = EMOJI_RE.search(text)
        check(m is None, "%s 出现 emoji：%r" % (f.name, m.group(0) if m else ""))


def test_required_pages():
    print("[5] 两张脸的入口文件齐备")
    for name in ("index.html", "home.js", "advanced.html", "app.js", "styles.css"):
        check((UI / name).is_file(), "缺少界面文件 %s" % name)
    idx = (UI / "index.html").read_text(encoding="utf-8")
    adv = (UI / "advanced.html").read_text(encoding="utf-8")
    check("advanced.html" in idx, "使用端未提供维护者入口链接")
    check("index.html" in adv, "开发者端未提供返回使用端的链接")
    check("home.js" in idx and "app.js" in adv, "两个页面各应加载自己的脚本")


if __name__ == "__main__":
    for fn in (test_css_covers_classes, test_dynamic_chips, test_offline_first,
               test_no_emoji, test_required_pages):
        fn()
    print("-" * 60)
    if FAILS:
        print("[FAIL] %d 项未通过" % len(FAILS))
        sys.exit(1)
    print("[OK] 界面资产契约全部通过")
