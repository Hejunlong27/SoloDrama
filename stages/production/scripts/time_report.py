#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""time_report.py —— 耗时台账与报表（替代已删除的 cost_ledger）

口径变更
--------
2026-11-04 起本仓库只跑本地 ComfyUI：没有按次计费，就没有「RH币 / 美元」这层账。
剩下的唯一稀缺资源是**本机 GPU 时间**，所以这张表回答的问题从
「这次花了多少钱」变成「这一集花了多久、时间花在哪个阶段」。

数据源：`<ws>/video-pipeline/ledger/runs/**/*.json`
  由 `run_ledger.RunLedger` 在每次真跑后写一条，字段里已有 `wall_elapsed_s`。
  本脚本只做**汇总与呈现**，不重新测量 —— 测量的唯一发生地在执行侧。

用法
----
    python time_report.py --workspace "D:/剧/x"                 # 全部集
    python time_report.py --workspace "D:/剧/x" --ep ep01
    python time_report.py --workspace "D:/剧/x" --json
    python time_report.py --workspace "D:/剧/x" --per-shot      # 逐镜明细

退出码：0 有数据 / 3 台账为空（还没真跑过）
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[union-attr]
except Exception:                                                # noqa: BLE001
    pass

STAGE_CN = {
    "image": "资产出图",
    "board": "分镜图",
    "h3-video": "出片",
    "video": "出片",
    "concat": "母版拼接",
    "upscale": "放大",
    "align": "字幕对齐",
    "render": "烧字幕",
    "export": "导出",
    "import": "导入",
}


def human(sec: float) -> str:
    try:
        s = int(round(float(sec)))
    except (TypeError, ValueError):
        return "—"
    if s < 60:
        return "%d 秒" % s
    m, s = divmod(s, 60)
    if m < 60:
        return "%d 分" % m if s < 30 else "%d 分 %d 秒" % (m, s)
    h, m = divmod(m, 60)
    return "%d 小时 %d 分" % (h, m) if m else "%d 小时" % h


def _ep_of(rec: dict) -> str:
    """从记录里认集号：优先 ep 字段，其次 batch_id / shot_id 里的 epNN 或 EP01。"""
    import re
    for k in ("ep", "episode"):
        v = str(rec.get(k) or "").strip()
        if v:
            return v.lower()
    for k in ("batch_id", "shot_id", "key"):
        v = str(rec.get(k) or "")
        m = re.search(r"(?i)\bep[_-]?(\d{1,3})\b", v)
        if m:
            return "ep%02d" % int(m.group(1))
    return "—"


def collect(ws: pathlib.Path) -> dict:
    """读全部 run 记录 → 汇总结构。"""
    root = ws / "video-pipeline" / "ledger" / "runs"
    recs: list = []
    if root.is_dir():
        for f in root.rglob("*.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError, ValueError):
                continue
            if isinstance(d, dict):
                d["_file"] = str(f.relative_to(root)).replace("\\", "/")
                recs.append(d)

    by_ep: dict = {}
    by_stage: dict = {}
    per_shot: dict = {}
    tot_sec = 0.0
    ok = fail = 0

    for r in recs:
        st = str(r.get("stage") or "?")
        status = str(r.get("status") or "").upper()
        try:
            wall = float(r.get("wall_elapsed_s") or 0)
        except (TypeError, ValueError):
            wall = 0.0
        if status in ("SUCCESS", "OK", "SUCCEEDED"):
            ok += 1
        elif status:
            fail += 1
        tot_sec += wall

        ep = _ep_of(r)
        e = by_ep.setdefault(ep, {"ep": ep, "sec": 0.0, "items": 0, "ok": 0, "fail": 0, "stages": {}})
        e["sec"] += wall
        e["items"] += 1
        if status in ("SUCCESS", "OK", "SUCCEEDED"):
            e["ok"] += 1
        elif status:
            e["fail"] += 1
        e["stages"][st] = e["stages"].get(st, 0.0) + wall

        s = by_stage.setdefault(st, {"stage": st, "label": STAGE_CN.get(st, st),
                                     "sec": 0.0, "items": 0})
        s["sec"] += wall
        s["items"] += 1

        sid = str(r.get("shot_id") or r.get("key") or "")
        if sid:
            k = (ep, sid)
            p = per_shot.setdefault(k, {"ep": ep, "shot": sid, "sec": 0.0, "items": 0,
                                        "status": status, "stages": {}})
            p["sec"] += wall
            p["items"] += 1
            p["stages"][st] = p["stages"].get(st, 0.0) + wall
            if status and status not in ("SUCCESS", "OK", "SUCCEEDED"):
                p["status"] = status

    for e in by_ep.values():
        e["human"] = human(e["sec"])
        e["avg_shot_sec"] = round(e["sec"] / e["ok"], 1) if e["ok"] else 0

    return {
        "ok": bool(recs),
        "root": str(root),
        "records": len(recs), "success": ok, "failed": fail,
        "total_sec": round(tot_sec, 1), "total_human": human(tot_sec),
        "episodes": sorted(by_ep.values(), key=lambda x: x["ep"]),
        "stages": sorted(by_stage.values(), key=lambda x: -x["sec"]),
        "shots": sorted(per_shot.values(), key=lambda x: (x["ep"], x["shot"])),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def render_text(d: dict, *, per_shot: bool = False, ep: str = "") -> str:
    L = []
    L.append("=" * 76)
    L.append("耗时台账%s" % ("（%s）" % ep if ep else ""))
    L.append("=" * 76)
    if not d["ok"]:
        L.append("  还没有任何真跑记录：%s" % d["root"])
        L.append("  跑一次出图或出片后会在这里出现记录。")
        return "\n".join(L)

    L.append("  记录 %d 条 ｜ 成功 %d ｜ 失败 %d ｜ 累计 %s"
             % (d["records"], d["success"], d["failed"], d["total_human"]))
    L.append("-" * 76)

    if d["episodes"]:
        L.append("  按集")
        for e in d["episodes"]:
            L.append("    %-6s %-14s 成功 %-3d 失败 %-3d 平均 %s/次"
                     % (e["ep"], e["human"], e["ok"], e["fail"],
                        human(e["avg_shot_sec"]) if e["avg_shot_sec"] else "—"))
        L.append("-" * 76)

    if d["stages"]:
        total = d["total_sec"] or 1
        L.append("  按阶段（占比）")
        for s in d["stages"]:
            pct = s["sec"] / total * 100
            bar = "█" * max(1, int(pct / 4))
            L.append("    %-10s %-12s %5.1f%%  %-20s %d 次"
                     % (s["label"], human(s["sec"]), pct, bar, s["items"]))
        L.append("-" * 76)

    if per_shot:
        L.append("  逐镜（前 30 条）")
        for p in d["shots"][:30]:
            L.append("    %-6s %-12s %-12s %-10s %s"
                     % (p["ep"], p["shot"], human(p["sec"]), p["status"] or "—",
                        "、".join("%s %s" % (STAGE_CN.get(k, k), human(v))
                                 for k, v in sorted(p["stages"].items(), key=lambda x: -x[1]))))
        if len(d["shots"]) > 30:
            L.append("    …（其余 %d 条见 --json）" % (len(d["shots"]) - 30))
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="耗时台账（成本口径 = 时间）")
    ap.add_argument("--workspace", default=None)
    ap.add_argument("--ep", default="", help="只看这一集（ep01）")
    ap.add_argument("--per-shot", dest="per_shot", action="store_true", help="逐镜明细")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    ws_raw = a.workspace or os.environ.get("SOLODRAMA_WORKSPACE") or os.environ.get("DRAMA_WORKSPACE")
    if not ws_raw:
        print("[FAIL] 需要 --workspace（或 SOLODRAMA_WORKSPACE）")
        return 2
    ws = pathlib.Path(ws_raw).expanduser().resolve()
    if not ws.is_dir():
        print("[FAIL] 工作区不存在：%s" % ws)
        return 2

    d = collect(ws)
    if a.ep:
        ep = a.ep.strip().lower()
        digits = "".join(ch for ch in ep if ch.isdigit())
        if digits:
            ep = "ep%02d" % int(digits)
        d["episodes"] = [e for e in d["episodes"] if e["ep"] == ep]
        d["shots"] = [p for p in d["shots"] if p["ep"] == ep]
        picked = [r for r in d["stages"]]
        d["stages"] = [s for s in picked
                       if any(s["stage"] in e["stages"] for e in d["episodes"])]
        d["total_sec"] = round(sum(e["sec"] for e in d["episodes"]), 1)
        d["total_human"] = human(d["total_sec"])

    if a.json:
        print(json.dumps(d, ensure_ascii=False, indent=2))
    else:
        print(render_text(d, per_shot=a.per_shot, ep=a.ep))
    return 0 if d["ok"] else 3


if __name__ == "__main__":
    sys.exit(main())
