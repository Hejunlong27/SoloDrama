# -*- coding: utf-8 -*-
"""文档引用守卫 —— 抓「文档里写着已经不存在的脚本/子命令」。

为什么要有这个测试
------------------
2026-11 的重构删掉了整个创作层（`script_rewrite.py`、`character_design.py`、
`convert_storyboard.py`、`workflow.py`、`project_setup.py` …），但十几份文档还在教人跑它们。
后果不是报错那么简单：Agent 照着文档跑 → `No such file` → 它开始即兴发挥，
**而用户以为流程在按文档走**。

这类腐烂只能靠机器抓：写的时候都对，删的时候没人回头改文档。

判据
----
只扫「会被人照着执行」的文档（README + docs，排除归档/事故记录/整改方案这类历史材料）。
命中的引用要么**文件真的存在**，要么同一行带「已移除 / 已删除 / 退役 / 历史」的标记，
否则失败 —— 逼作者在写的同时说清楚它已经没了。

```bash
python -m pytest tools/tests/test_doc_refs.py -q
```
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]

# 历史材料：它们**就该**保留旧脚本名（事故复盘、归档回灌包、版本记录）。
SKIP_DIRS = ("docs/archive", "docs/patches", "docs/reform", "docs/复盘-", "docs/showcase")
SKIP_FILES = ("VERSIONS.md", "docs/BRANCH-ENGINE.md", "docs/operations/已退役脚本.md")

# 内容已整体声明为历史稿：整份放行（文首已有「已降级 / 历史稿」横幅）。
LEGACY_DOCS = (
    "docs/orchestration/标准作业流程.md",
    "docs/orchestration/生产流程总纲.md",
)

# 已删除的 CLI 子命令：出现即算失效引用（`drama.py workflow check` 这类写法最坑）。
DEAD_SUBCOMMANDS = ("setup", "pipeline", "workflow", "halfcheck")

MARKERS = ("移除", "已删除", "退役", "历史稿", "已降级", "不再存在", "不要调用")

PY_REF = re.compile(r"([A-Za-z0-9_\-]+\.py)")
DEAD_SUB = re.compile(r"drama\.py\s+(%s)\b" % "|".join(DEAD_SUBCOMMANDS))


def _docs() -> list:
    out = []
    readme = ROOT / "README.md"
    if readme.is_file():
        out.append(readme)
    for p in (ROOT / "docs").rglob("*.md"):
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        if any(rel.startswith(d) for d in SKIP_DIRS) or rel in SKIP_FILES:
            continue
        if re.search(r"\d{8}", p.name):          # 带日期的对账/记录：历史材料
            continue
        out.append(p)
    return out


def _existing_py() -> set:
    names = set()
    for p in ROOT.rglob("*.py"):
        s = str(p).replace("\\", "/")
        if "/.git/" in s or "__pycache__" in s:
            continue
        names.add(p.name)
    return names


def scan() -> list:
    """→ [(文件, 行号, 命中的引用, 原因)]；空列表 = 干净。"""
    have = _existing_py()
    bad = []
    for doc in _docs():
        rel = str(doc.relative_to(ROOT)).replace("\\", "/")
        if rel in LEGACY_DOCS:
            continue
        text = doc.read_text(encoding="utf-8", errors="replace")
        # 文首有退役横幅的文件：读者在第一条命令之前就被警告过，整份放行。
        if "已退役脚本与现行入口" in "\n".join(text.splitlines()[:14]):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if any(m in line for m in MARKERS):
                continue
            for m in PY_REF.finditer(line):
                if m.group(1) not in have:
                    bad.append((rel, i, m.group(1), "脚本不存在"))
            for m in DEAD_SUB.finditer(line):
                bad.append((rel, i, "drama.py " + m.group(1), "子命令已删除"))
    return bad


def test_no_stale_refs():
    bad = scan()
    detail = "\n".join("  %s:%d  %s（%s）" % b for b in bad[:20])
    assert not bad, (
        "以下文档引用了已不存在的东西：\n%s\n"
        "修法：换成现行入口（见 docs/operations/已退役脚本.md），"
        "或在该行标注「已移除」。" % detail)


def test_scan_can_see_known_retired():
    """自检：守卫本身不能是空转 —— 拿一个确定退役的名字喂它，必须能抓到。"""
    have = _existing_py()
    assert "script_rewrite.py" not in have, "script_rewrite.py 又回来了？请更新本测试"
    assert PY_REF.search("跑 `script_rewrite.py diagnose`") is not None
    assert DEAD_SUB.search("drama.py setup ask") is not None


if __name__ == "__main__":
    bad = scan()
    for rel, ln, name, why in bad:
        print("  [NG] %-56s :%-4d %-28s %s" % (rel, ln, name, why))
    print("失效引用 %d 处" % len(bad))
    raise SystemExit(1 if bad else 0)
