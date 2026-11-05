"""cloud/ledger.py —— 云端 GPU 时长/成本台账（`<工作区>/台账/cloud-cost.jsonl`）

为什么必须单列一列「钱」
------------------------
`run_ledger.py` 记的是本机「生成段数 / 耗时」—— 本机是 ￥0，只有时间账。上云之后
钱是真的在流：同样是 30 集，用哪档卡、跑了几小时、中间忘了停多久，全都要能对出来。
没有这一列，做过一部剧就说不清钱花在哪，下一部也没法比价。

三条口径（与 `run_ledger.py` 一致）
----------------------------------
1. **追加写，不改历史**：jsonl 一行一条，出错就补一行「冲销」，不修旧行。
2. **时间用本地时区带偏移**：`2026-11-05T14:32:00+08:00` —— 跨时区协作时不会错 8 小时。
3. **未定价如实写 0**：仙宫云单价未确认（文档附录 C），不臆造数字；
   `price_per_hour=0` 时 `cost` 记 0 且 `priced=False`，读的人一眼看出「这是没定价，不是免费」。
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib

LEDGER_DIR = "台账"
LEDGER_NAME = "cloud-cost.jsonl"


def workspace(ws=None) -> pathlib.Path:
    """台账所在工作区：参数 > SOLODRAMA_WORKSPACE > 当前目录。

    不抛异常是刻意的：台账是**旁路记录**，不该因为工作区没配好而让出片流程失败。
    """
    cand = ws
    if not cand:
        cand = (os.environ.get("SOLODRAMA_WORKSPACE") or os.environ.get("DRAMA_WORKSPACE")
                or os.getcwd())
    return pathlib.Path(cand).expanduser().resolve()


def ledger_path(ws=None) -> pathlib.Path:
    return workspace(ws) / LEDGER_DIR / LEDGER_NAME


def _now() -> str:
    return _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def record(inst, started_at: float, stopped_at: float, gpu_price_per_hour: float,
           note: str = "", ws=None, project: str = "", episodes=0, segments: int = 0) -> dict:
    """写一行成本记录并返回它（调用方可以直接打印/断言）。

    `started_at` / `stopped_at` 用 epoch 秒（`time.time()`），与本机台账同一口径；
    落盘时换算成带时区的 ISO 时间，两者都留 —— 人能读、机器能算。
    """
    hours = max(0.0, (float(stopped_at) - float(started_at)) / 3600.0)
    price = float(gpu_price_per_hour or 0.0)
    row = {
        "at": _now(),
        "instance": str(getattr(inst, "id", "") or ""),
        "gpu": str(getattr(inst, "gpu", "") or ""),
        "started_at": _iso(started_at),
        "stopped_at": _iso(stopped_at),
        "hours": round(hours, 3),
        "price_per_hour": round(price, 4),
        "priced": price > 0,
        "cost": round(hours * price, 2),
        "project": project or _project_name(),
        "episodes": int(episodes or 0),
        "segments": int(segments or 0),
        "note": note or "",
    }
    p = ledger_path(ws)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8", newline="") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def _iso(ts) -> str:
    try:
        return _dt.datetime.fromtimestamp(float(ts)).astimezone().replace(
            microsecond=0).isoformat()
    except (TypeError, ValueError, OSError):
        return ""


def _project_name() -> str:
    """项目名：`brief.json` / `project.json` 有就用，否则用工作区目录名。"""
    ws = workspace()
    for name in ("brief.json", "project.json"):
        try:
            d = json.loads((ws / name).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        if isinstance(d, dict):
            for k in ("title", "name", "drama", "project"):
                if str(d.get(k) or "").strip():
                    return str(d[k]).strip()
    return ws.name


def read_all(ws=None) -> list:
    """读全部记录（坏行跳过 —— 一行损坏不该让整本台账读不出来）。"""
    p = ledger_path(ws)
    rows = []
    try:
        with open(p, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return []
    return rows


def day_hours(day=None, ws=None) -> float:
    """某个自然日（默认今天）的累计 GPU 小时数 —— 成本护栏读这个。"""
    day = day or _dt.date.today()
    total = 0.0
    for r in read_all(ws):
        at = str(r.get("at") or "")
        if at[:10] == day.isoformat():
            total += float(r.get("hours") or 0)
    return round(total, 3)


def day_cost(day=None, ws=None) -> float:
    day = day or _dt.date.today()
    return round(sum(float(r.get("cost") or 0) for r in read_all(ws)
                     if str(r.get("at") or "")[:10] == day.isoformat()), 2)


def summary(ws=None) -> dict:
    """全部记录的小计（CLI 与报表共用）。"""
    rows = read_all(ws)
    return {
        "rows": len(rows),
        "hours": round(sum(float(r.get("hours") or 0) for r in rows), 2),
        "cost": round(sum(float(r.get("cost") or 0) for r in rows), 2),
        "today_hours": day_hours(ws=ws),
        "today_cost": day_cost(ws=ws),
        "unpriced_rows": sum(1 for r in rows if not r.get("priced")),
        "path": str(ledger_path(ws)),
    }
