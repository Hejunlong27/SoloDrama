#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""zzai_season.py —— 真真AI 全季批处理：分镜 → 出片，逐集落盘、可断点续跑

为什么需要它
------------
把 30 集拆成 30 次手敲命令，代价不是打字，而是**中途断掉后不知道从哪继续**：
出片单镜要 1–3 分钟，全季 179 镜是小时级，任何一次终端关闭都要求「重新判断哪几集好了」。
本脚本把判断交给产物本身（`04-资产/boards/<ep>/<shot>.png` 与 `07-成片/<ep>/<shot>/final.mp4`），
已有的直接跳过，因此同一条命令可以反复跑。

它不做的事
----------
* 不重新生成已有的分镜图/成片（`--force` 才重跑）；产物才是唯一真相。
* 不猜预算：`--budget` 只是「再花不超过这么多钱就停」，不去动账号侧。
* 不并行：图片接口并发未知，视频单任务 1–3 分钟，串行最稳，也最不容易踩限流。

用法
----
    # 全季分镜（四宫格由 model-plan.json 的 board.detail.grid 决定）
    python zzai_season.py --workspace "D:/剧本/海外剧/10" --stage boards --yes --max-cost 0.06

    # 全季出片（先 EP01 一集；确认后再放开）
    python zzai_season.py --workspace "..." --stage video --eps ep01 --yes --max-cost 0.30
    python zzai_season.py --workspace "..." --stage video --eps ep02-ep30 --yes --max-cost 0.30

    # 只算钱，不提交
    python zzai_season.py --workspace "..." --stage video --dry-run
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")     # type: ignore[union-attr]
except Exception:                                                  # noqa: BLE001
    pass

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "stages"))

import _layout as L                                                # noqa: E402

BOARDS_PY = ROOT / "stages" / "production" / "scripts" / "gen_boards.py"
VIDEO_PY = ROOT / "stages" / "media_api" / "zzai_video.py"


def _eps(arg: str, ws: pathlib.Path) -> list:
    """`ep01` / `ep01-ep05` / 省略=全部（按 06-提示词 下已导入的集）。"""
    have = sorted(p.name for p in (L.data_dir(ws)).glob("ep*") if p.is_dir())
    if not arg:
        return have
    m = re.fullmatch(r"ep(\d{2})-ep(\d{2})", arg.strip())
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        return [e for e in have if lo <= int(e[2:]) <= hi]
    out = []
    for part in re.split(r"[,，\s]+", arg):
        if not part:
            continue
        out.append(part if part.startswith("ep") else "ep%02d" % int(part))
    return out


def _run(cmd: list, log: pathlib.Path) -> int:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as fh:
        fh.write("\n$ %s\n" % " ".join(str(c) for c in cmd))
        fh.flush()
        p = subprocess.run([str(c) for c in cmd], stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True,
                           encoding="utf-8", errors="replace")
        fh.write(p.stdout or "")
    tail = [ln for ln in (p.stdout or "").splitlines() if ln.strip()][-1:]
    print("      %s" % (tail[0] if tail else "（无输出）"))
    return p.returncode


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="真真AI 全季批处理（分镜 / 出片）")
    ap.add_argument("--workspace", default=None)
    ap.add_argument("--stage", required=True, choices=("boards", "video", "both"))
    ap.add_argument("--eps", default="", help="ep01 / ep01-ep10 / 1,2,3；省略=全部已导入集")
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--max-cost", dest="max_cost", type=float, default=None,
                    help="单任务 CNY 上限（分镜单张 / 出片单镜）")
    ap.add_argument("--budget", type=float, default=0.0,
                    help="本批次预算上限（¥）；各集累计报价超过即停")
    ap.add_argument("--dry-run", action="store_true", help="只跑干跑（报价），不提交")
    ap.add_argument("--limit", type=int, default=0, help="每集只做前 N 镜（验证用）")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--concurrency", type=int, default=1,
                    help="出片并发（仅 video 阶段；实测 3 条在飞约 1.9 倍吞吐，成本不变）")
    a = ap.parse_args(argv)

    ws = pathlib.Path(a.workspace).expanduser().resolve() if a.workspace else pathlib.Path(
        __import__("os").environ.get("SOLODRAMA_WORKSPACE") or ".").resolve()
    eps = _eps(a.eps, ws)
    if not eps:
        print("[FAIL] 没有可处理的集（检查 --eps 或先跑 pack 导入）")
        return 2

    log = ws / "07-成片" / "logs" / ("zzai_season_%s.log" % time.strftime("%Y%m%d_%H%M%S"))
    print("=" * 74)
    print("真真AI 全季批处理 · %s" % a.stage)
    print("=" * 74)
    print("  工作区 : %s" % ws)
    print("  集数   : %d（%s … %s）" % (len(eps), eps[0], eps[-1]))
    print("  日志   : %s" % log)
    if a.dry_run:
        print("  模式   : 干跑（只报价）")
    print()

    spent = 0.0
    results = []
    for i, ep in enumerate(eps, 1):
        print("[%d/%d] %s" % (i, len(eps), ep))
        stages = ["boards", "video"] if a.stage == "both" else [a.stage]
        for st in stages:
            script = BOARDS_PY if st == "boards" else VIDEO_PY
            cmd = [sys.executable, script, "--workspace", ws, "--ep", ep]
            if st == "boards":
                if a.force:
                    cmd += ["--force"]
                if a.limit:
                    cmd += ["--limit", a.limit]
                if not a.dry_run:
                    cmd += ["--apply"]
                if a.yes and not a.dry_run:
                    cmd += ["--yes"]
                if a.max_cost is not None:
                    cmd += ["--max-cost", a.max_cost]
            else:
                if a.force:
                    cmd += ["--force"]
                if a.limit:
                    cmd += ["--limit", a.limit]
                if a.yes and not a.dry_run:
                    cmd += ["--yes"]
                if a.max_cost is not None:
                    cmd += ["--max-cost", a.max_cost]
                if a.concurrency and a.concurrency > 1:
                    cmd += ["--concurrency", str(a.concurrency)]
            rc = _run(cmd, log)
            # 预算闸门：从本集日志里抓「预估合计：¥x」累计
            try:
                txt = log.read_text(encoding="utf-8", errors="replace")[-4000:]
                m = re.findall(r"预估合计：¥([\d.]+)", txt)
                if m:
                    spent = float(m[-1])
            except OSError:
                pass
            results.append((ep, st, rc))
            if a.budget and spent > a.budget:
                print("\n[预算] 本批次累计报价 ¥%.2f 已超过 --budget ¥%.2f，停止。"
                      % (spent, a.budget))
                return 0 if all(r[2] == 0 for r in results) else 3
            if rc not in (0,):
                print("      [注意] %s %s 退出码 %s（见日志）" % (ep, st, rc))

    bad = [r for r in results if r[2] != 0]
    print("\n汇总：%d 个任务，成功 %d，异常 %d" % (len(results), len(results) - len(bad), len(bad)))
    for ep, st, rc in bad[:10]:
        print("  - %s %s → %s" % (ep, st, rc))
    return 0 if not bad else 3


if __name__ == "__main__":
    raise SystemExit(main())
