# -*- coding: utf-8 -*-
"""仓库根路径判据 —— 抓「`ROOT = HERE.parents[N]` 的 N 数错一层」。

为什么要有这个测试
------------------
这个仓库里同一类错误出现过**五次**，每次症状都不是「找不到模块」这么直白：

    2026-11-01  gen_boards.py     ROOT=parents[1] → 指向 stages/，looks.json 读不到，静默用默认风格
    2026-11-01  nodes.py          ROOT=parents[1] → 检查器路径拼成 stages/stages/...，报「can't open file」
    2026-11-01  main.py(engine)   parents[3]      → 指向 stages/video，_layout 导入失败，分镜图 0 张
    2026-11-01  init_project.py   parents[1]      → ModuleNotFoundError: _layout
    2026-11-01  test_init_project ROOT=parents[1] → 同 ModuleNotFoundError

共同点：**代码不报「路径写错了」，而是报一个看起来无关的错**（文件不存在 / 模块找不到 /
数值为空），排查会先怀疑数据，绕很远才回到这一行。

人肉记忆靠不住（写了四次注释还是错），所以换成机器判据：
用 AST 静态解析，算出每个 `ROOT = …parents[N]` 到底指向哪，与仓库根比对。
不 import、不执行，零副作用。

```bash
python tools/tests/test_repo_paths.py
```
"""
import argparse
import ast
import os
import pathlib
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                                # noqa: BLE001
    pass

ROOT = pathlib.Path(__file__).resolve().parents[2]
assert (ROOT / "stages" / "_layout.py").is_file(), "测试自身定位失败：%s" % ROOT

SCAN_DIRS = ("stages", "tools", "web")
CASES = []


def reg(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


def A_(cond, msg=""):
    if not cond:
        raise AssertionError(msg or "断言失败")


def _const_str(node):
    """从 ast 节点里取字符串字面量（支持 `Path(__file__).resolve().parent` 这类不取值）。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _root_assignments(tree: ast.AST):
    """→ [(行号, 基准表达式描述, N)]，找 `NAME = <base>.parents[N]`。"""
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        tgt = node.targets[0]
        if not isinstance(tgt, ast.Name):
            continue
        if not re.fullmatch(r"[A-Z_]*(ROOT|REPO|BASE)[A-Z_]*", tgt.id):
            continue
        v = node.value
        # 形如 X.parents[N]
        if isinstance(v, ast.Subscript) and isinstance(v.value, ast.Attribute) \
                and v.value.attr == "parents":
            n = None
            sl = v.slice
            if isinstance(sl, ast.Constant) and isinstance(sl.value, int):
                n = sl.value
            if n is not None:
                out.append((node.lineno, tgt.id, ast.unparse(v.value.value), n))
    return out


def _here_base(tree: ast.AST) -> dict:
    """同文件里 `X = pathlib.Path(__file__)...parent` 这类基准，返回 {名字: 'file'}。"""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            src = ast.unparse(node.value)
            if "__file__" in src:
                out[node.targets[0].id] = src
    return out


def scan(root: pathlib.Path = ROOT) -> list:
    """→ [(相对路径, 行号, 变量名, 实际指向, 是否=仓库根)]"""
    rows = []
    for d in SCAN_DIRS:
        base = root / d
        if not base.is_dir():
            continue
        for p in base.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            try:
                tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"), filename=str(p))
            except SyntaxError:
                continue
            here = _here_base(tree)
            for lineno, name, baseexpr, n in _root_assignments(tree):
                # 只关心「以本文件位置为基准」的写法
                if baseexpr not in here:
                    continue
                # HERE = <file>.parent  ⇒  HERE.parents[n] = <file>.parents[n+1]
                target = p.parents[n + 1] if n + 1 < len(p.parents) + 1 else None
                if target is None:
                    rows.append((str(p.relative_to(root)).replace(os.sep, "/"), lineno, name, "(越界)", False))
                    continue
                rows.append((str(p.relative_to(root)).replace(os.sep, "/"), lineno, name,
                             str(target), target.resolve() == root.resolve()))
    return rows


# ===========================================================================
@reg("P01 所有「以本文件为基准」的 ROOT 都必须指向仓库根")
def _():
    rows = scan()
    bad = [r for r in rows if not r[4]]
    if bad:
        msg = ["%d 处 ROOT 指错（多一层或少一层）：" % len(bad)]
        for f, ln, name, got, _ok in bad[:10]:
            msg.append("  %s:%d  %s → %s（应为 %s）" % (f, ln, name, got, ROOT))
        raise AssertionError("\n".join(msg))
    return "%d 处全部指向仓库根" % len(rows)


@reg("P02 扫描器不是空转（能认出写错的那一行）")
def _():
    import tempfile
    d = pathlib.Path(tempfile.mkdtemp(prefix="rp_"))
    try:
        (d / "stages").mkdir()
        (d / "stages" / "_layout.py").write_text("# marker\n", encoding="utf-8")
        # 本文件在 <root>/stages/ 下 ⇒ HERE=<root>/stages ⇒ 正确的 ROOT 是 parents[0]。
        # 所以 bad 写 parents[1]（多退一层），good 写 parents[0]。
        (d / "stages" / "bad.py").write_text(
            "import pathlib\n"
            "HERE = pathlib.Path(__file__).resolve().parent\n"
            "ROOT = HERE.parents[1]\n",          # 多退一层 → 指到 root 的父
            encoding="utf-8")
        (d / "stages" / "good.py").write_text(
            "import pathlib\n"
            "HERE = pathlib.Path(__file__).resolve().parent\n"
            "ROOT = HERE.parents[0]\n",          # 正确
            encoding="utf-8")
        rows = scan(d)
        files = {(r[0], r[4]) for r in rows}
        A_(("stages/bad.py", False) in files, "没抓到写错的文件：%s" % rows)
        A_(("stages/good.py", True) in files, "把写对的也判错了：%s" % rows)
        return "抓到 1 / 误报 0"
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


@reg("P03 关键模块的 ROOT 下确实有 stages/_layout.py")
def _():
    """文件级不 import、只做路径断言 —— 防止「改了 ROOT 但忘了自检」。"""
    must = [
        "stages/production/scripts/nodes.py",
        "stages/production/scripts/gen_boards.py",
        "stages/production/scripts/init_project.py",
        "stages/video/workflow/scripts/engine/main.py",
    ]
    miss = [m for m in must if not (ROOT / m).is_file()]
    A_(not miss, "清单里的文件不存在（改名了就更新这份清单）：%s" % miss)
    return "%d 个模块在册" % len(must)


def main():
    ap = argparse.ArgumentParser()
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
