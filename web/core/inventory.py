# -*- coding: utf-8 -*-
"""inventory.py —— 「这部剧做出了什么、花了多少」的只读聚合（用户端口径来源）

为什么单独一层
--------------
`drama.py status` 的 `ledger` 字段只统计**统一台账**（`video-pipeline/ledger/runs/*.json`）。
但实测发现：资产出图走云端工作流时，用量记录落在
`output/assets/<kind>/_wf/result_*.json`（引擎自己的原始证据），**台账可能没有收录**。
只读台账 ⇒ 用户端会显示「花了多少钱 = ¥0」，而实际上钱已经花了 —— 这是**统计缺陷**。

口径纪律（与项目一致，不得放宽）
--------------------------------
1. **只认平台 usage**：金额一律取自 `usage.consumeCoins` / `usage.consumeMoney`，
   绝不用余额倒推。
2. **台账优先、工作流兜底、按 taskId 去重**：两处都有同一任务时只算一次。
3. **兜底必须标注来源**：来自工作流记录的金额会在界面上说明「系统账单里尚未收录」，
   不假装它与台账等价。
4. **失败任务不计费**：`status != SUCCESS` 的记录不累加金额（实测失败不扣费）。

另含 `discover()`：扫描本机候选目录，找出所有短剧项目并给出产出摘要 ——
用于解决「用户在 A 项目里找 B 项目的图」这类误判。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from . import paths

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
KINDS = ("characters", "scenes", "props")
_CACHE: dict = {}
_CACHE_TTL = 20
_DISCOVER_TTL = 90


def _count_images(d: Path) -> int:
    if not d.is_dir():
        return 0
    n = 0
    try:
        for p in d.iterdir():
            if p.is_file() and p.suffix.lower() in IMAGE_EXT:
                n += 1
    except OSError:
        return 0
    return n


def _loose_count(ws: Path) -> int:
    """标准资产目录之外的图片数（剧目录根 + 一层子目录）。

    ★ 2026-10-28 实测：真实项目（`D:\\剧本\\海外剧\\2、母亲之路`）把 21 张图直接丢在剧目录
      根下，`04-资产/{characters,scenes,props}` 一个都没有 ⇒ 旧口径单看标准目录，
      项目卡片会写「暂无产出」、资产中心会写「还没有图片」。**用户明明有图**。
      所以计数必须走 `artifacts.loose_images` 这一处真源，与资产页「散图」页签同口径，
      否则两个页面会各说一套。
    """
    try:
        from . import artifacts
        d = artifacts.loose_images(str(ws), limit=2000) or {}
        return len(d.get("items") or [])
    except Exception:  # noqa: BLE001 —— 统计失败不能拖垮整个清单
        return 0


def _read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _usage_of(d: dict) -> tuple:
    """从一条记录里取 (coins, money, task_id, ok)。"""
    if not isinstance(d, dict):
        return 0.0, 0.0, "", False
    u = d.get("usage") or {}
    try:
        coins = float(u.get("consumeCoins") or 0)
    except (TypeError, ValueError):
        coins = 0.0
    try:
        money = float(u.get("consumeMoney") or 0)
    except (TypeError, ValueError):
        money = 0.0
    tid = str(d.get("taskId") or d.get("task_id") or "")
    ok = str(d.get("status") or "").upper() in ("SUCCESS", "SUCCEEDED", "OK")
    return coins, money, tid, ok


def _ledger_records(ws: Path) -> tuple:
    """统一台账（分布在不同布局的 engine_root 下）。"""
    L = paths.ensure_layout_importable()
    roots = []
    if L is not None:
        try:
            roots.append(L.engine_root(str(ws)))
        except Exception:  # noqa: BLE001
            pass
    roots += [ws / "video-pipeline", ws / "orchestrator"]
    seen, out = set(), []
    for r in roots:
        d = r / "ledger" / "runs"
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.json")):
            if f in seen:
                continue
            seen.add(f)
            out.append(f)
    return out


def inventory(ws) -> dict:
    """产出与消耗总览（带缓存，20 秒）。"""
    ws = str(Path(ws).expanduser())
    now = time.time()
    hit = _CACHE.get("inv:" + ws)
    if hit and (now - hit[0]) < _CACHE_TTL:
        return hit[1]
    val = _inventory(Path(ws))
    _CACHE["inv:" + ws] = (now, val)
    return val


def _inventory(ws: Path) -> dict:
    L = paths.ensure_layout_importable()
    try:
        out_dir = Path(L.out_dir(str(ws))) if L else ws / "video-pipeline" / "output"
    except Exception:  # noqa: BLE001
        out_dir = ws / "video-pipeline" / "output"

    # ★ 2026-10-19：资产落点 = 04-资产（老项目未迁移时 assets_dir 会返回旧位置 <out>/assets）
    try:
        assets_dir = Path(L.assets_dir(str(ws))) if L else out_dir / "assets"
    except Exception:  # noqa: BLE001
        assets_dir = out_dir / "assets"

    images = {k: _count_images(assets_dir / k) for k in KINDS}
    images["total"] = sum(images.values())
    # ★ 散图独立一格：不并入 total（`total` 是「已归档资产」的稳定口径，多处断言依赖它），
    #   但在界面与 has_output 里必须算进去，否则「有 21 张图」会被判成「未开工」。
    images["loose"] = _loose_count(ws)
    images["all"] = images["total"] + images["loose"]

    refs = 0
    for cand in (assets_dir / "refs", out_dir / "assets" / "refs", ws / "video-pipeline" / "data" / "refs",
                 ws / "video-pipeline" / "data" / "refs_h3", ws / "04-资产" / "refs"):
        refs = max(refs, _count_images(cand))

    clips = len(list(out_dir.glob("*/**/final.mp4"))) if out_dir.is_dir() else 0
    renders = len(list(out_dir.glob("*/**/*_master*.mp4"))) if out_dir.is_dir() else 0

    # ---- 金额：台账优先，工作流兜底，按 taskId 去重 ----
    ledger_files = _ledger_records(ws)
    coins = money = 0.0
    ledger_tasks, wf_tasks = set(), set()
    ledger_hits = wf_hits = 0
    for f in ledger_files:
        d = _read_json(f)
        if d is None:
            continue
        recs = d if isinstance(d, list) else [d]
        for r in recs:
            c, m, tid, ok = _usage_of(r)
            if not ok and not tid:
                continue
            if c or m:
                coins += c
                money += m
                ledger_hits += 1
            if tid:
                ledger_tasks.add(tid)

    if out_dir.is_dir():
        for f in out_dir.glob("assets/**/_wf/result_*.json"):
            d = _read_json(f)
            c, m, tid, ok = _usage_of(d or {})
            if tid in ledger_tasks and tid:
                continue                     # 台账已收录，避免重复计
            if not ok:
                continue                     # 失败不计费
            if c or m:
                coins += c
                money += m
                wf_hits += 1
            if tid:
                wf_tasks.add(tid)

    if ledger_hits and not wf_hits:
        source, source_text = "ledger", ""
    elif wf_hits and not ledger_hits:
        source = "workflow"
        source_text = "金额来自云端生成记录，系统的账单明细里尚未收录（可能略低于实际）"
    elif wf_hits and ledger_hits:
        source = "mixed"
        source_text = "部分金额来自云端生成记录，系统的账单明细里尚未收录"
    else:
        source, source_text = "none", ""

    newest = 0.0
    for p in (out_dir / "assets").glob("**/*") if (out_dir / "assets").is_dir() else []:
        try:
            if p.is_file():
                newest = max(newest, p.stat().st_mtime)
        except OSError:
            pass

    return {
        "images": images,
        "refs": refs,
        "clips": clips,
        "renders": renders,
        "spend": {
            "coins": round(coins, 2),
            "usd": round(money, 4),
            "tasks": len(ledger_tasks | wf_tasks) or (ledger_hits + wf_hits),
            "ledger_files": len(ledger_files),
            "ledger_hits": ledger_hits,
            "workflow_hits": wf_hits,
            "source": source,
            "source_text": source_text,
        },
        # ★ 散图也算产出：真实项目把图放根目录，只看标准目录会误判成「未开工」。
        "has_output": bool(images["total"] or images["loose"] or refs or clips),
        "updated_at": newest,
        "updated_text": (time.strftime("%m-%d %H:%M", time.localtime(newest)) if newest else ""),
    }


# ---------------------------------------------------------------------------
# 项目发现：本机有哪几部剧、各自做到了什么程度
# ---------------------------------------------------------------------------
def scan_roots() -> list:
    env = os.environ.get("SOLODRAMA_SCAN_ROOTS") or ""
    if env:
        return [r.strip() for r in env.split(";") if r.strip()]
    return [r"D:\剧本", r"D:\AI-Drama"]


def _looks_like_drama(d: Path) -> bool:
    return ((d / "video-pipeline").is_dir() or (d / "layout.json").is_file()
            or (d / "model-plan.json").is_file()) and not d.name.startswith(".")


def discover(refresh: bool = False, max_depth: int = 3, limit: int = 40) -> dict:
    """扫描候选目录，列出所有短剧项目 + 产出摘要（90 秒缓存）。"""
    now = time.time()
    hit = _CACHE.get("discover")
    if hit and not refresh and (now - hit[0]) < _DISCOVER_TTL:
        return hit[1]

    found = []
    roots = scan_roots()
    for root in roots:
        base = Path(root)
        if not base.is_dir():
            continue
        stack = [(base, 0)]
        while stack and len(found) < limit:
            cur, depth = stack.pop()
            if depth > max_depth:
                continue
            try:
                children = [c for c in cur.iterdir() if c.is_dir()]
            except OSError:
                continue
            for c in children:
                if c.name.startswith((".", "_")):
                    continue
                if _looks_like_drama(c):
                    inv = inventory(str(c))
                    found.append({
                        "path": str(c),
                        "name": c.name,
                        # `images` 口径保持「已归档资产 + 参考图」不变（多处断言依赖），
                        # 散图单列 `loose`，由界面自行相加显示。
                        "images": inv["images"]["total"] + inv["refs"],
                        "loose": inv["images"]["loose"],
                        "yuan": round(inv["spend"]["coins"] * 0.0025, 4),
                        "coins": inv["spend"]["coins"],
                        "has_output": inv["has_output"],
                        "updated_at": inv["updated_at"],
                        "updated_text": inv["updated_text"],
                    })
                else:
                    stack.append((c, depth + 1))

    found.sort(key=lambda x: (x["images"], x["updated_at"]), reverse=True)
    val = {"items": found, "roots": roots, "scanned_at": now}
    _CACHE["discover"] = (now, val)
    return val
