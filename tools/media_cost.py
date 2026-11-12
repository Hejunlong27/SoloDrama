#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Reconcile media task backend settlement costs.

This is a local, no-network control-plane tool. Provider task `usage` remains
provisional; the amount confirmed by the provider backend is written to
`settled_cost` and `actual_cost`.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from web.core import media_tasks  # noqa: E402


def _workspace(raw):
    value = raw or os.environ.get("SOLODRAMA_WORKSPACE") or ""
    if not str(value).strip():
        raise SystemExit("需要 --workspace 或 SOLODRAMA_WORKSPACE")
    path = pathlib.Path(str(value)).expanduser().resolve()
    if not path.is_dir():
        raise SystemExit("工作区不存在：%s" % path)
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="媒体任务后台结算对账")
    ap.add_argument("--workspace", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    settle = sub.add_parser("settle", help="写入供应商后台最终金额")
    settle.add_argument("task_id")
    settle.add_argument("--amount", type=float, required=True)
    settle.add_argument("--currency", default="CNY")
    settle.add_argument("--source", default="provider_backend")
    settle.add_argument("--note", default="")
    show = sub.add_parser("show", help="查看单条任务成本记录")
    show.add_argument("task_id")
    args = ap.parse_args(argv)
    ws = _workspace(args.workspace)
    try:
        if args.cmd == "settle":
            rec = media_tasks.record_settlement(
                ws, args.task_id, args.amount, args.currency,
                source=args.source, note=args.note,
            )
        else:
            rec = media_tasks.get(ws, args.task_id)
    except media_tasks.MediaTaskError as exc:
        print("[FAIL] %s" % exc, file=sys.stderr)
        return 2
    print(json.dumps(rec, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
