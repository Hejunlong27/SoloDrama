#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""run_ledger.py —— 运行台账（**薄壳**；实现见 `stages/_ledger_core.py`）

这份是 RunningHub 引擎那侧的入口。它曾经与
`stages/production/scripts/run_ledger.py` 逐字重复（216/217 行，diff 只有三行注释：
把 `sec_per_frame` 写成 `rh_per_frame`）。2026-11-06 合并为单一实现。

⚠ 保留文件名与 import 路径是刻意的：`engine/main.py`、`engine/pipeline.py`、
   `gen_assets_local.py` 都是 `from run_ledger import RunLedger`，其中
   `gen_assets_local.py` 把本目录插在 `sys.path` 最前面 —— 改路径等于同时改三处装配。

用法不变：
    from run_ledger import RunLedger
"""
from __future__ import annotations

import pathlib as _pathlib
import sys as _sys

# 定位仓库的 `stages/`（实现所在），不依赖调用方当前 sys.path 里有什么。
_p = _pathlib.Path(__file__).resolve().parent
while _p.name != "stages":
    if _p.parent == _p:
        raise ImportError("run_ledger: 找不到仓库的 stages/ 目录（%s）" % __file__)
    _p = _p.parent
if str(_p) not in _sys.path:
    _sys.path.insert(0, str(_p))

from _ledger_core import (                     # noqa: E402,F401
    DEFAULT_CNY_PER_RH_COIN,
    RunLedger,
    classify_error,
    frames_for,
    normalize,
)

__all__ = ["RunLedger", "normalize", "frames_for", "classify_error",
           "DEFAULT_CNY_PER_RH_COIN"]
