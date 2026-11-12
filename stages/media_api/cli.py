# -*- coding: utf-8 -*-
"""ZZAI 只读 CLI：钱包、模型列表、公开价格和免费 estimate。

刻意不提供 submit 子命令。真实生成必须由后续受控执行器调用，并且先完成报价与授权。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .zzai import DEFAULT_BASE_URL, ZZAIClient, ZZAIError


def _payload(args):
    if args.payload:
        return json.loads(Path(args.payload).read_text(encoding="utf-8-sig"))
    if args.payload_json:
        return json.loads(args.payload_json)
    if not sys.stdin.isatty():
        raw = sys.stdin.read().strip()
        if raw:
            return json.loads(raw)
    raise ZZAIError("config", "estimate 需要 --payload <file> 或 --payload-json '<json>'")


def main(argv=None):
    p = argparse.ArgumentParser(description="ZZAI 只读接口")
    p.add_argument("--base-url", default=DEFAULT_BASE_URL)
    p.add_argument("--key", default=None, help="不推荐；优先用环境变量")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("wallet")
    sub.add_parser("models")
    sub.add_parser("pricing")
    est = sub.add_parser("estimate")
    est.add_argument("--kind", choices=("image", "video"), required=True)
    est.add_argument("--payload", default="")
    est.add_argument("--payload-json", default="")
    args = p.parse_args(argv)
    try:
        c = ZZAIClient(base_url=args.base_url, key=args.key)
        if args.cmd == "wallet":
            out = c.wallet()
        elif args.cmd == "models":
            out = c.models()
        elif args.cmd == "pricing":
            out = c.pricing()
        else:
            out = c.estimate(args.kind, _payload(args))
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    except (ZZAIError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
