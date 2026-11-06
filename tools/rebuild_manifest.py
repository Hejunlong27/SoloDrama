#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""rebuild_manifest.py —— 重建仓库完整性清单 `manifest.sha256`

为什么要有脚本
--------------
规范（`docs/operations/开发者路线.md` ⑤）要求「任何文件改动都要重建 manifest」，
但重建方式一直是手写的，于是：

* 2026-11-06 实测：清单 432 条，磁盘上已跟踪文件 474 个 —— **42 个文件从没登记过**
  （整个 `cloud/` 包、`md2pack.py`、`prompt_marks.py`…），另有 74 条哈希已过期；
* 旧清单的排序规则也无法复现（既不是路径序，也不是整行序），说明当初是某个
  带 locale 的 `sort` 随手出来的 —— 这种东西没法靠人眼复核。

所以把它脚本化，并把规则写死成可复现的一条：**按路径的 UTF-8 字节序排序**。

规则（与规范一致，逐条可查）
----------------------------
1. 文件集 = `git -c core.quotePath=false ls-files`（受管文件），**排除 manifest.sha256 自身**。
   用 git 的索引而不是 `os.walk`：`.gitignore` 排除的产物/密钥本来就不该进清单。
2. 格式：`<sha256>  *<相对路径>`（两个空格 + 星号 = `sha256sum` 的二进制模式，跨平台一致）。
3. 排序：路径的 UTF-8 字节序（固定，不受 locale 影响）。
4. 编码：UTF-8 无 BOM；行尾 LF。

为什么还要查「行尾漂移」
------------------------
清单哈希的是**工作区原始字节**，而 git 提交的是**归一化后的字节**。两者一旦不一致，
清单就会在别人 clone 之后必然对不上 —— 而 `git status` 还显示干净（它先归一化再比对），
表现为「11 个文件哈希不符，但看不出哪里改过」，极难诊断（2026-11-06 实际踩过）。

判定：`git ls-files --eol` 里 `i/…` 与 `w/…` 不同即漂移；显式 `eol=crlf` 的文件不报
（那种情况磁盘本该是 CRLF）。修法是把文件按索引重写一遍（`--fix-eol`）。

用法
----
    python tools/rebuild_manifest.py --check     # 报差异 + 行尾漂移；有任一问题退出码 1
    python tools/rebuild_manifest.py --apply     # 重写 manifest.sha256
    python tools/rebuild_manifest.py --fix-eol   # 把漂移的文件按索引重写（git checkout --）
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "manifest.sha256"


def _tracked() -> list:
    out = subprocess.check_output(
        ["git", "-c", "core.quotePath=false", "ls-files"],
        cwd=str(ROOT), text=True, encoding="utf-8")
    files = [x for x in out.splitlines() if x.strip()]
    return sorted((f for f in files if f != MANIFEST.name),
                  key=lambda s: s.encode("utf-8"))


def _digest(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def build() -> dict:
    """→ {相对路径: sha256}（按 UTF-8 字节序）。"""
    return {rel: _digest(rel) for rel in _tracked() if (ROOT / rel).is_file()}


def read_current() -> dict:
    if not MANIFEST.is_file():
        return {}
    out = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, _, rest = line.partition("  ")
        out[rest.lstrip("*").strip()] = digest
    return out


def diff(want: dict, have: dict) -> dict:
    return {
        "added": [k for k in want if k not in have],
        "missing": [k for k in have if k not in want],
        "stale": [k for k in want if k in have and want[k] != have[k]],
    }


def parse_eol(raw: str) -> list:
    """解析 `git ls-files --eol` → [(路径, 索引行尾, 工作区行尾)]，只留**漂移**的。

    输出形如：`i/lf    w/crlf  attr/text=auto eol=lf<TAB>路径`
    * `i/-text w/-text`（二进制）两侧一致 → 不算漂移；
    * `attr/... eol=crlf` 的文件磁盘本就该是 CRLF → 跳过（否则会误报所有 .cmd）；
    * 其余只要 `i/` 与 `w/` 不同，就是「工作区字节 ≠ 别人 clone 下来的字节」。
    """
    drift = []
    for line in raw.splitlines():
        meta, _, path = line.partition("\t")
        if not path:
            continue
        toks = meta.split()
        idx = next((t[2:] for t in toks if t.startswith("i/")), "")
        wt = next((t[2:] for t in toks if t.startswith("w/")), "")
        attr = " ".join(t for t in toks if not t.startswith(("i/", "w/")))
        if not idx or not wt or idx == wt:
            continue
        if "eol=crlf" in attr:
            continue
        drift.append((path, idx, wt))
    return drift


def eol_drift() -> list:
    out = subprocess.check_output(
        ["git", "-c", "core.quotePath=false", "ls-files", "--eol"],
        cwd=str(ROOT), text=True, encoding="utf-8", errors="replace")
    return parse_eol(out)


def fix_eol(drift: list) -> int:
    """按索引重写漂移文件。**只动这些文件**，不做全仓 checkout。"""
    if not drift:
        return 0
    paths = [p for p, _, _ in drift]
    subprocess.check_call(["git", "checkout", "--"] + paths, cwd=str(ROOT))
    return len(paths)


def write(want: dict) -> None:
    text = "".join("%s  *%s\n" % (want[k], k) for k in want)
    MANIFEST.write_text(text, encoding="utf-8", newline="")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="重建 manifest.sha256（完整性清单）")
    ap.add_argument("--apply", action="store_true", help="重写清单（默认只检查）")
    ap.add_argument("--check", action="store_true", help="只报差异；有差异退出码 1")
    ap.add_argument("--fix-eol", action="store_true",
                    help="把行尾漂移的文件按索引重写（git checkout --），修完请重跑 --apply")
    a = ap.parse_args(argv)

    drift = eol_drift()
    if a.fix_eol and drift:
        n = fix_eol(drift)
        print("[OK] 已按索引重写 %d 个行尾漂移文件；请重跑 --apply 重建清单" % n)
        drift = eol_drift()
        if drift:
            print("[WARN] 仍有 %d 个漂移：%s" % (len(drift), "、".join(p for p, _, _ in drift[:5])))

    want, have = build(), read_current()
    d = diff(want, have)
    print("受管文件 %d ｜ 清单现有 %d" % (len(want), len(have)))
    for key, cn in (("added", "未登记"), ("missing", "清单有但磁盘无"), ("stale", "哈希不符")):
        items = d[key]
        print("  %-12s %d%s" % (cn, len(items), "" if not items else "：" + "、".join(items[:5])))
    print("  %-12s %d%s" % ("行尾漂移", len(drift),
                            "" if not drift else "：" + "、".join(
                                "%s（%s→%s）" % (p, i, w) for p, i, w in drift[:5])))

    if a.apply:
        write(want)
        print("[OK] 已重写 %s（%d 条，按路径 UTF-8 字节序）" % (MANIFEST.relative_to(ROOT), len(want)))
        if drift:
            # 清单哈希的是工作区字节；工作区若与索引不同，别人 clone 下来必然对不上。
            print("[WARN] 仍有 %d 个行尾漂移：清单记的是**工作区**字节，换台机器会 mismatch。"
                  "先跑 --fix-eol 再 --apply。" % len(drift))
        return 0
    if any(d.values()) or drift:
        print("[FAIL] 清单与磁盘不一致 —— 确认后跑 --apply 重建")
        if drift and not any(d.values()):
            print("       注意：哈希本身是对得上的，是**行尾漂移**让清单不可复现；"
                  "建议先 --fix-eol 再 --apply")
        return 1
    print("[OK] 清单与磁盘一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
