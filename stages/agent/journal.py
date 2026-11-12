# -*- coding: utf-8 -*-
"""调度 journal：仅追加 JSONL，作为 Runner 重启后的执行轨迹。"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

_LOCK = threading.RLock()


def path(ws) -> Path:
    return Path(ws).resolve() / ".drama" / "agent" / "journal.jsonl"


def append(ws, event: dict) -> dict:
    rec = {"schema_version": 1, "at": time.time(), **event}
    p = path(ws)
    p.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        with p.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
            fh.flush()
    return rec


def recent(ws, limit=50) -> list:
    p = path(ws)
    if not p.is_file():
        return []
    out = []
    try:
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(d, dict):
                out.append(d)
    except OSError:
        return []
    return out[-max(1, int(limit)):]
