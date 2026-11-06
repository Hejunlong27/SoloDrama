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

用法
----
    python tools/rebuild_manifest.py --check     # 只报差异（新增/缺失/哈希不符），退出码 1 = 有差异
    python tools/rebuild_manifest.py --apply     # 重写 manifest.sha256
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


def write(want: dict) -> None:
    text = "".join("%s  *%s\n" % (want[k], k) for k in want)
    MANIFEST.write_text(text, encoding="utf-8", newline="")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="重建 manifest.sha256（完整性清单）")
    ap.add_argument("--apply", action="store_true", help="重写清单（默认只检查）")
    ap.add_argument("--check", action="store_true", help="只报差异；有差异退出码 1")
    a = ap.parse_args(argv)

    want, have = build(), read_current()
    d = diff(want, have)
    print("受管文件 %d ｜ 清单现有 %d" % (len(want), len(have)))
    for key, cn in (("added", "未登记"), ("missing", "清单有但磁盘无"), ("stale", "哈希不符")):
        items = d[key]
        print("  %-12s %d%s" % (cn, len(items), "" if not items else "：" + "、".join(items[:5])))

    if a.apply:
        write(want)
        print("[OK] 已重写 %s（%d 条，按路径 UTF-8 字节序）" % (MANIFEST.relative_to(ROOT), len(want)))
        return 0
    if any(d.values()):
        print("[FAIL] 清单与磁盘不一致 —— 确认后跑 --apply 重建")
        return 1
    print("[OK] 清单与磁盘一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
