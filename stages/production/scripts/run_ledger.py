#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""run_ledger.py —— 运行台账（**薄壳**；实现见 `stages/_ledger_core.py`）

这个文件曾经是一份 216 行的独立实现，与
`stages/video/workflow/scripts/engine/run_ledger.py` **逐字重复**（diff 只有三行注释）。
两份同名模块靠 `sys.path` 顺序决定用哪一份 —— `gen_assets_local.py` 把 engine 目录插在
最前面，所以出图走 engine 那份，而 `gen_assets_rh_workflow.py` 走这一份。
任何一边单独改动，另一条链路就静默分叉。2026-11-06 合并为单一实现。

保留这个文件（而不是删掉、让调用方改 import）的理由：三个调用点写的是
`from run_ledger import RunLedger`，且各自的 `sys.path` 装配与引擎目录绑定，
改 import 路径等于同时改三处路径逻辑 —— 收益为零，风险不小。

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
