# -*- coding: utf-8 -*-
"""_util.py —— 同层（stages/production/scripts）共用的小工具。

只放**同一份实现、多处复制**的东西；一旦某个脚本需要不同行为，就不要往这里塞参数，
而是留在原地并注明差异。当前两项：

  · `harden_stdio()` —— 中文 Windows 控制台是 GBK(cp936)，而管道/重定向按 UTF-8 读：
    在控制台里必须用控制台代码页（否则中文乱码），被捕获必须 UTF-8（否则读出来是乱码）。
    按 `isatty()` 分流，并把 errors 放宽成 replace（防 GBK 装不下的字符直接抛异常）。
  · `read_json(path, default)` —— 读 JSON，坏文件/缺失都返回 default，不抛。

为什么不放 `_ws.py`：那个模块在 import 期就解析工作区，任何「只要编码加固」的调用方
都会被拖去校验工作区（`_qa_subtitle_frame` 时代踩过）。
"""
from __future__ import annotations

import json
import os
import sys


def harden_stdio() -> None:
    try:
        enc = "utf-8"
        if sys.stdout.isatty() and os.name == "nt":
            import ctypes
            cp = ctypes.windll.kernel32.GetConsoleOutputCP()
            if cp:
                enc = "cp%d" % cp
        for s in (sys.stdout, sys.stderr):
            try:
                s.reconfigure(encoding=enc, errors="replace")
            except Exception:                                  # noqa: BLE001
                pass
    except Exception:                                          # noqa: BLE001
        pass


def read_json(path, default=None):
    """读 JSON；文件不存在 / 解析失败都返回 default（调用方不必包 try）。"""
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, obj) -> None:
    """写 JSON（LF、UTF-8、缩进 2）—— 与全仓库的落盘口径一致。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")
