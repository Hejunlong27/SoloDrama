# -*- coding: utf-8 -*-
"""清单可复现性 —— 抓「工作区行尾 ≠ 仓库字节，导致清单在别人机器上必然对不上」。

为什么要有这个测试
------------------
`manifest.sha256` 哈希的是**工作区原始字节**，而 git 提交的是**归一化后的字节**。
两者不一致时：

* `git status` 常常显示干净（它先按 `.gitattributes` 归一化再比对）；
* `manifest --check` 却报「哈希不符」，而且指不出原因 —— 人只会去怀疑「是不是谁改过内容」。

2026-11-06 实际踩过：11 个文件（`configs/capabilities/*.json`、`docs/archive/回灌包_20261031/*`）
磁盘上是 CRLF、仓库里是 LF，清单长期记着 CRLF 的哈希。当时没人跑 `--check`，所以一直没暴露；
一旦换台机器 clone，清单必然全红。

判据：`git ls-files --eol` 的 `i/…` 与 `w/…` 必须一致（显式 `eol=crlf` 的除外）。
这条比「比对哈希」更早、更准 —— 它直接说「工作区不是 clone 会得到的样子」。

用法：`python -m pytest tools/tests/test_manifest_eol.py -q`
"""
from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))          # tools/

import rebuild_manifest as M  # noqa: E402


# --------------------------------------------------------------------------- 解析器
def test_no_drift_when_index_and_worktree_agree():
    raw = ("i/lf    w/lf    attr/text=auto eol=lf \tREADME.md\n"
           "i/crlf  w/crlf  attr/text=auto eol=lf \tstart.cmd\n")
    assert M.parse_eol(raw) == []


def test_detects_crlf_in_worktree():
    """正是 2026-11-06 那个形态：仓库 LF、磁盘 CRLF。"""
    raw = "i/lf    w/crlf  attr/text=auto eol=lf \tconfigs/capabilities/x.json\n"
    assert M.parse_eol(raw) == [("configs/capabilities/x.json", "lf", "crlf")]


def test_detects_reverse_drift_too():
    """反过来（仓库 CRLF、磁盘 LF）同样是漂移，不能只防一个方向。"""
    raw = "i/crlf  w/lf    attr/text=auto \tfoo.txt\n"
    assert M.parse_eol(raw) == [("foo.txt", "crlf", "lf")]


def test_ignores_binary():
    """二进制两侧都是 -text，不该被当成行尾问题。"""
    raw = ("i/-text w/-text attr/text=auto eol=lf \tdocs/showcase/01-assets.jpg\n"
           "i/-text w/-text attr/text=auto eol=lf \tweb/ui/studio/img/favicon.ico\n")
    assert M.parse_eol(raw) == []


def test_ignores_explicit_crlf_attribute():
    """`.cmd` 若显式声明 `eol=crlf`，磁盘是 CRLF 才是**正确**结果，不许误报。"""
    raw = "i/lf    w/crlf  attr/text eol=crlf \tstart.cmd\n"
    assert M.parse_eol(raw) == []


def test_skips_lines_without_tab():
    """`ls-files --eol` 的正常输出一定有 TAB；没有的是被截断/别的命令混进来。"""
    assert M.parse_eol("i/lf    w/crlf  attr/text=auto eol=lf\n") == []


# --------------------------------------------------------------------------- 真实仓库
def test_repo_has_no_eol_drift():
    """仓库当前必须 0 漂移：否则 `manifest.sha256` 换台机器就对不上。

    失败时先跑 `python tools/rebuild_manifest.py --fix-eol`，再 `--apply`。
    """
    drift = M.eol_drift()
    assert drift == [], "行尾漂移 %d 个：%s" % (
        len(drift), "、".join("%s（%s→%s）" % d for d in drift[:5]))


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("  [OK] %s" % name)
            except AssertionError as e:                       # noqa: PERF203
                fails += 1
                print("  [NG] %s —— %s" % (name, e))
    print("失败 %d" % fails)
    sys.exit(1 if fails else 0)
