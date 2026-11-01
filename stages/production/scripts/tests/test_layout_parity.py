# -*- coding: utf-8 -*-
"""四份「布局解析」实现的口径一致性测试（离线、零依赖、零计费）。

为什么需要：`stages/_layout.py` 是布局唯一真源，但另外三处**刻意**各带一份轻量复刻
（`_ws.py` / `subtitle.py` / `upscale.py`）—— 因为后两者可能被拷进 Skill 包单独运行，
那时仓库的 `_layout.py` 不在 sys.path 上。

复刻本身没问题，"四份各说各话"才是问题：症状是**同一个工作区，不同脚本认到不同目录**
（历史上踩过：母版落在 A 目录、字幕去 B 目录找，报的却是"母版不存在"）。
所以这里不合并实现，而是把口径**钉进测试** —— 任何一份漂移，立刻红。

跑法：python stages/production/scripts/tests/test_layout_parity.py
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
PROD = HERE.parent                       # stages/production/scripts
ROOT = PROD.parents[2]                   # stages/production/scripts → 仓库根
FIX = HERE / "fixtures" / "mini_drama"

sys.path.insert(0, str(PROD))
sys.path.insert(0, str(ROOT / "stages"))

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("  [NG] %s" % msg)
    return cond


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ws = str(FIX)
    print("=" * 78)
    print("布局解析口径一致性 · %s" % ws)
    print("-" * 78)

    import _layout as L

    rows = {}
    rows["_layout.data_dir"] = str(L.data_dir(pathlib.Path(ws)))
    rows["_layout.out_dir"] = str(L.out_dir(pathlib.Path(ws)))
    rows["_layout.assets_dir"] = str(L.assets_dir(pathlib.Path(ws)))

    # _ws 在 import 期解析环境变量 —— 先设好再导入
    os.environ["SOLODRAMA_WORKSPACE"] = ws
    for m in [m for m in list(sys.modules) if m in ("_ws",)]:
        del sys.modules[m]
    import _ws as W
    rows["_ws.DATA"] = str(W.DATA)
    rows["_ws.OUT"] = str(W.OUT)

    sub = _load(ROOT / "stages" / "subtitle" / "scripts" / "subtitle.py", "sub_parity")
    up = _load(ROOT / "stages" / "subtitle" / "scripts" / "upscale.py", "up_parity")
    for tag, fn in (("subtitle", sub._layout_paths), ("upscale", up._layout_paths)):
        eng, data, out = fn(ws)
        rows["%s.engine" % tag] = str(eng)
        rows["%s.data" % tag] = str(data)
        rows["%s.out" % tag] = str(out)

    for k, v in rows.items():
        print("  %-18s %s" % (k, v))
    print("-" * 78)

    def same(keys, label):
        vals = {rows[k] for k in keys if k in rows}
        check(len(vals) == 1, "%s 四份实现不一致：%s"
              % (label, {k: rows[k] for k in keys if k in rows}))

    same(["_layout.data_dir", "_ws.DATA", "subtitle.data", "upscale.data"], "data 目录")
    same(["_layout.out_dir", "_ws.OUT", "subtitle.out", "upscale.out"], "out 目录")
    same(["_layout.assets_dir",
          str(L.assets_dir(pathlib.Path(ws)))], "assets 目录（自身幂等）")

    # 关键：data/out 不能相同（历史上出现过两者都被解析成同一个目录）
    check(rows["_layout.data_dir"] != rows["_layout.out_dir"], "data 与 out 不能是同一个目录")

    print("=" * 78)
    if FAILS:
        print("[FAIL] %d 项不一致" % len(FAILS))
        return 1
    print("[OK] 四份实现口径一致（data / out / assets）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
