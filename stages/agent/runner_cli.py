# -*- coding: utf-8 -*-
"""`stages.agent.runner` 的脚本入口。

Web 命令白名单只能执行 Python 文件，不能执行 `python -m ...`；这个薄包装
负责先把仓库根目录加入 sys.path，再复用包内的 Runner。调度逻辑仍只有
runner.py 一份，不在 Web 层复制。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stages.agent.runner import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())