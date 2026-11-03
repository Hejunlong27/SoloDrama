# -*- coding: utf-8 -*-
"""timing.py —— 全局时间账（工作台用）

为什么单独一层
--------------
`studio.cost(ws)` 是**项目级**的：它还会调 `time_model.py` 子进程做预估（0.3–1 秒）。
工作台要的是「这台机器一共占了多久 GPU、时间花在哪几部剧」，一屏十几个项目，
不能每个都起一个子进程。

所以这里只读台账（`<引擎>/ledger/runs/*.json` 的 attempts），纯文件扫描：
30 个项目也就几十毫秒。预估留在项目页，不在这里假装算得出来。
"""
from __future__ import annotations

import time
from pathlib import Path

from . import paths, studio

_CACHE: dict = {}


def summary(*, ws: str = "", ttl: int = 15) -> dict:
    now = time.time()
    key = "ws:%s" % (ws or "")
    hit = _CACHE.get(key)
    if hit and (now - hit[0]) < ttl:
        return hit[1]
    val = _build(ws)
    _CACHE[key] = (now, val)
    return val


def clear_cache() -> None:
    _CACHE.clear()


def _build(ws: str = "") -> dict:
    reg = paths.read_json(paths.REGISTRY_FILE, default={}) or {}
    items = [dict(it) for it in (reg.get("items") or [])]
    # 当前打开的项目也要算进来：它可能只是深链打开、还没登记进注册表。
    # 「我看着这部片，却看不到它的耗时」是最容易让人以为统计坏了的场景。
    if ws and Path(ws).is_dir() and not any(str(it.get("path")) == str(ws) for it in items):
        items.insert(0, {"path": str(ws), "title": Path(ws).name})
    rows, by_stage = [], {}
    total = {"sec": 0.0, "attempts": 0, "success": 0, "failed": 0, "projects": 0}
    for it in items:
        p = str(it.get("path") or "")
        if not p or not Path(p).is_dir():
            continue
        try:
            att = studio.attempts(p)
        except Exception:                                     # noqa: BLE001
            att = []
        if not att:
            continue
        ok = [a for a in att if a["status"] in ("SUCCESS", "SUCCEEDED", "OK")]
        sec = sum(a["sec"] for a in ok)
        for a in ok:
            k = a["stage"] or "其他"
            by_stage[k] = by_stage.get(k, 0.0) + a["sec"]
        rows.append({
            "path": p, "title": it.get("title") or Path(p).name,
            "sec": round(sec, 1), "human": studio._human_sec(sec),   # noqa: SLF001
            "attempts": len(att), "success": len(ok),
            "failed": len(att) - len(ok),
            "last": att[0]["at"] if att else "",
        })
        total["sec"] += sec
        total["attempts"] += len(att)
        total["success"] += len(ok)
        total["failed"] += len(att) - len(ok)
        total["projects"] += 1

    rows.sort(key=lambda r: r["sec"], reverse=True)
    return {
        "ok": True,
        "unit": "sec",
        "totals": {
            **total,
            "sec": round(total["sec"], 1),
            "human": studio._human_sec(total["sec"]),            # noqa: SLF001
            "avg_shot_sec": round(total["sec"] / total["success"], 1) if total["success"] else 0.0,
        },
        "projects": rows,
        "by_stage": [{"stage": k, "sec": round(v, 1), "human": studio._human_sec(v)}  # noqa: SLF001
                     for k, v in sorted(by_stage.items(), key=lambda kv: kv[1], reverse=True)],
        "source": "台账 ledger/runs/*.json（逐次尝试的实际占用；失败不计入时长）",
        "updated_at": time.time(),
    }
