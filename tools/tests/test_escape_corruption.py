# -*- coding: utf-8 -*-
"""转义损坏扫描 —— 抓「正则里的 `\\s` 被写成 `//s`」这类事故。

为什么要有这个测试
------------------
这个仓库里同一条坑**踩了四次**：

    2026-10-31  `subtitle.py` 的段内对齐正则被写成 `//s` → 匹配不到 → 函数静默返回 0
    2026-11-01  `prompt_gate.py` 的 refs 解析被写成 `refs://s*` → 全部判成「CHAR 0 人」
    2026-11-01  `nodes.py` 的 argparse 报错解析被写成 `arguments://s*` → 自适应失效
    2026-11-01  `gen_boards.py` 的 board 块解析整段被破坏 → 靠 boards.json 回退才没炸

共同点：**都不报错，函数静默返回空/不匹配**，症状看起来像「数据有问题」或「工作流坏了」，
排查会绕很远。人肉记忆靠不住（记了三次还是踩），所以必须换成机器判据。

成因：用 heredoc / 多层字符串拼接过正则时，反斜杠被吃掉一层。
纪律：**正则不经过 heredoc 写盘，用直接编辑**；这份测试是兜底。

判据
----
扫 `stages/ tools/ web/` 下所有 `.py`，逐行找「看起来像被破坏的正则转义」：

    //s  //S  //d  //D  //w  //W  //n  //N  //t  //T  //r  //R  //b  //B  //Z  //|

并且该行必须**同时含 `re.`**（限定在正则上下文里，避免误报普通字符串与 URL）。

排除：`http://` / `https://` 之后的内容；纯注释行里的 Windows 路径举例。

```bash
python tools/tests/test_escape_corruption.py
```
"""
import argparse
import os
import pathlib
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                                # noqa: BLE001
    pass

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCAN_DIRS = ("stages", "tools", "web")

# 被破坏的转义：`//` + 一个在正则里有意义的字母 / 竖线
BROKEN = re.compile(r"//(?:[sSdDwWnNtTrRbBZz])")
# 合法的双斜杠：URL、协议相对路径、注释里的路径举例
ALLOW = ("http://", "https://", "file://", "//!", "////")

CASES = []


def reg(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


def A_(cond, msg=""):
    if not cond:
        raise AssertionError(msg or "断言失败")


def scan(root: pathlib.Path = ROOT) -> list:
    """→ [(相对路径, 行号, 行内容)]。只报「同一行有 re.」的可疑行。"""
    hits = []
    for d in SCAN_DIRS:
        base = root / d
        if not base.is_dir():
            continue
        for p in base.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            if p.name == "test_escape_corruption.py":
                continue          # 本文件的自测样本故意是坏的，不能自己报自己
            try:
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for i, ln in enumerate(lines, 1):
                if "re." not in ln and "regex" not in ln:
                    continue
                if any(a in ln for a in ALLOW):
                    # URL 与文档举例：把允许的片段先摘掉再判
                    probe = ln
                    for a in ALLOW:
                        probe = probe.replace(a, "\x00")
                else:
                    probe = ln
                if BROKEN.search(probe):
                    hits.append((str(p.relative_to(root)), i, ln.strip()[:120]))
    return hits


# ===========================================================================
@reg("E01 仓库里没有「正则转义被破坏」的行")
def _():
    hits = scan()
    if hits:
        msg = ["发现 %d 处可疑（`//s` 这类，通常是 heredoc 吃掉了一层反斜杠）：" % len(hits)]
        for f, i, ln in hits[:12]:
            msg.append("  %s:%d  %s" % (f, i, ln))
        raise AssertionError("\n".join(msg))
    return "0 处"


@reg("E02 扫描器自己能抓到破坏（自测，防止它永远返回空）")
def _():
    import tempfile
    d = pathlib.Path(tempfile.mkdtemp(prefix="esc_"))
    try:
        (d / "stages").mkdir()
        (d / "stages" / "bad.py").write_text(
            'import re\nP = re.compile(r"(?m)^-\\\\s*board://s*//|//s*//n(.*?)")\n',
            encoding="utf-8")
        (d / "stages" / "good.py").write_text(
            'import re\nP = re.compile(r"(?m)^-\\\\s*board:\\\\s*\\\\|\\\\s*\\\\n(.*?)")\n'
            'U = "https://example.com/a?b=1"\n', encoding="utf-8")
        hits = scan(d)
        files = {h[0] for h in hits}
        A_(any("bad.py" in f for f in files), "扫描器没抓到坏文件：%s" % hits)
        A_(not any("good.py" in f for f in files), "扫描器误报了正常文件：%s" % hits)
        return "抓到 1 / 误报 0"
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


@reg("E03 已知的四次事故模式都被 BROKEN 覆盖")
def _():
    samples = ["board://s*", "refs://s*", "arguments://s*", "//s*//n", "//Z)", "//d+"]
    for s in samples:
        A_(BROKEN.search(s), "覆盖不到：%s" % s)
    # 不能误伤的正常写法
    for s in ('r"a\\.b"', "https://x", "a // b", "r'(?m)^-\\s*'"):
        probe = s.replace("https://", "")
        A_(not BROKEN.search(probe), "误报：%s" % s)
    return "%d 个模式全覆盖" % len(samples)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", default="")
    args = ap.parse_args()
    passed = failed = 0
    for name, fn in CASES:
        try:
            note = fn() or ""
            print("  [PASS] %-52s %s" % (name, note))
            passed += 1
        except AssertionError as e:
            print("  [FAIL] %-52s %s" % (name, e))
            failed += 1
        except Exception as e:                                  # noqa: BLE001
            print("  [ERR ] %-52s %s: %s" % (name, type(e).__name__, e))
            failed += 1
    print("=" * 84)
    print("合计 %d 例 ｜ 通过 %d ｜ 失败 %d" % (passed + failed, passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
