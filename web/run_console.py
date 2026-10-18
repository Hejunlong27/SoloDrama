#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""run_console.py —— 启动 SoloDrama 控制台（默认仅本机 127.0.0.1:8788）

用法：
    python web/run_console.py                      # 默认本机
    python web/run_console.py --port 8799
    SOLODRAMA_CONSOLE_READONLY=1 python web/run_console.py   # 只读模式（禁止一切写操作）

安全说明：
  * 默认只绑定回环地址；如需局域网访问（P4），必须自行加认证 —— 控制台能触发计费动作；
  * 控制台不接触、不转发任何 API Key；日志与接口返回统一过打码层。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))


def main() -> int:
    ap = argparse.ArgumentParser(description="SoloDrama Web 控制台")
    ap.add_argument("--host", default=os.environ.get("SOLODRAMA_CONSOLE_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("SOLODRAMA_CONSOLE_PORT", "8788")))
    ap.add_argument("--reload", action="store_true", help="开发用热重载")
    a = ap.parse_args()

    import uvicorn  # noqa: PLC0415

    print("[OK] SoloDrama 控制台：http://%s:%d/ui/" % (a.host, a.port))
    print("     只读模式：%s" % ("开" if os.environ.get("SOLODRAMA_CONSOLE_READONLY") else "关"))
    uvicorn.run("app:app", host=a.host, port=a.port, reload=a.reload,
                app_dir=str(WEB_DIR), log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
