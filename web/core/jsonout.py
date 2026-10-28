# -*- coding: utf-8 -*-
"""jsonout.py —— 从 CLI 输出里稳定取出 JSON（唯一实现，reader / adapters 共用）

为什么单独成模块
----------------
引擎有两种输出形态：
  1. 纯 JSON（`workflow.py status --json`、`project_setup.py show --json`）；
  2. 人读回显 + JSON（`drama.py style status --json` 会把子脚本输出以 `  | ` 前缀逐行回显，
     人读区里还有**行内**小 JSON，如 `执行依据: {"workflow_id": "..."}`）。

第 2 种曾导致「首个 `{` 到末个 `}` 切片」报 Extra data，因此必须：
先剥行首 `  | ` 标记 → 再对每个 `{` 位置 raw_decode → 取**跨度最大**的顶层对象。
"""
from __future__ import annotations

import json
import re

_PIPE_PREFIX = re.compile(r"^\s*\|[ ]?")


def extract_json(text: str):
    """返回最大的顶层 dict；找不到返回 None。"""
    if not text:
        return None
    cleaned = "\n".join(_PIPE_PREFIX.sub("", ln) for ln in text.splitlines())
    dec = json.JSONDecoder()
    for src in (cleaned, text):
        best, best_span, idx = None, -1, 0
        while True:
            k = src.find("{", idx)
            if k < 0:
                break
            try:
                obj, end = dec.raw_decode(src[k:])
            except ValueError:
                idx = k + 1
                continue
            if isinstance(obj, dict) and end > best_span:
                best, best_span = obj, end
            idx = k + 1
        if best is not None:
            return best
    return None
