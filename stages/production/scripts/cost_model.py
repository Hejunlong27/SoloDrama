#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""cost_model.py —— 出片成本口径（唯一真源，纯标准库）

为什么有这个模块（反馈 P2-1 / P2-6 / P2-7）
--------------------------------------------
此前 `drama.py` 里是一条「2 点构造性拟合」的按帧公式：

    coins = 29.24 + 0.3529 × frames

它在 8 秒以上的长段大致可用，但对**短段严重高估**（5 秒段实测 32 RH币，该公式给 ~78）。

2026-10-19 在 ZH / AI 两站、两个 tier 上实测到的事实（证据见
`docs/patches/2026-10-20_反馈单修复记录.md`）：

| 口径 | 实测 |
|---|---|
| 消费级 Key | 固定 **27 RH币/任务** + **1 RH币/秒**（5 s → 32 币）|
| 企业级 Key | 固定 **¥0.117/任务** + **¥0.006/秒**（5 s → ¥0.147）|
| 计价本质 | **按 GPU 运行秒**：四组实测 币/运行秒 = 0.205 / 0.201 / 0.207 / 0.200 |

因此本模块同时给出两种可比的预估，并允许用历史台账自校准：

  ① **两段式**（按视频时长）：`coins = fixed_coins + coins_per_second × duration`
     —— 与平台账单的实际计费结构一致，适合「按段报价」。
  ② **GPU 秒式**（按运行时长）：`coins ≈ coins_per_gpu_s × (cold_start_s + k × duration)`
     —— 解释了「为什么 5 秒与 8 秒差价很小」：冷启动占运行时长的大头。

**口径纪律**：预估只用于闸门判断；真实消耗只认平台按任务返回的 `usage`
（`consumeCoins` / `thirdPartyConsumeMoney` / `taskCostTime`），永不用余额差值倒推。
"""
from __future__ import annotations

import json
import pathlib

# ---------------------------------------------------------------------------
# 默认参数（2026-10-19 实测；可用 <工作区>/cost-model.json 覆盖）
# ---------------------------------------------------------------------------
DEFAULT_PARAMS = {
    "_note": "由实测拟合；字段含义见 stages/production/scripts/cost_model.py 模块文档",
    "_measured_at": "2026-10-19",
    "consumer": {
        "label": "消费级-会员",
        "currency": "RH币",
        "fixed": 27.0,          # RH币/任务
        "per_second": 1.0,      # RH币/视频秒
    },
    "ent_shared": {
        "label": "企业级-共享",
        "currency": "money",    # 走钱包金额（thirdPartyConsumeMoney）
        "fixed": 0.117,         # 元/任务
        "per_second": 0.006,    # 元/视频秒
    },
    "gpu": {
        "coins_per_gpu_second": 0.205,   # 四组实测中位数
        "cold_start_s": 120.0,           # 冷启动固定开销（秒）
        "seconds_per_video_second": 7.2, # 每 1 秒视频带来的运行秒增量
    },
    "fx": {
        "cny_per_rh_coin": 0.0025,       # 1 RH币 ≈ ¥0.0025
    },
    # ★ 2026-10-21（反馈 11.1）：计算量基准 —— 变动成本按「步数 × 像素」相对它线性缩放。
    "work": {
        "base_steps": 4,          # 4 步 turbo LoRA（实测基准）
        "base_megapixels": 0.8,   # 0.8MP ≈ 672×1216（实测 31–34 RH币/段）
    },
}

TIERS = ("consumer", "ent_shared")


def load_params(ws=None) -> dict:
    """默认参数 ← `<ws>/cost-model.json` 覆盖（深合并，缺项回落默认）。"""
    params = json.loads(json.dumps(DEFAULT_PARAMS))     # deep copy
    if ws:
        p = pathlib.Path(ws) / "cost-model.json"
        if p.is_file():
            try:
                patch = json.loads(p.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                patch = {}
            if isinstance(patch, dict):
                for k, v in patch.items():
                    if isinstance(v, dict) and isinstance(params.get(k), dict):
                        params[k].update(v)
                    else:
                        params[k] = v
    return params


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def estimate(durations, tier: str = "consumer", params: dict | None = None,
             steps=None, megapixels=None) -> dict:
    """对一组「视频时长（秒）」估算成本，返回两套口径 + 明细。

    参数
    ----
    durations  : 可迭代的秒数（None / 非法值按 12 s 计，与引擎默认一致）
    tier       : consumer / ent_shared；非法值回落 consumer
    steps      : 采样步数（None = 用 params.work.base_steps）。4 步 turbo 与 20 步全量差 5 倍。
    megapixels : 源像素（None = base_megapixels）。0.8MP ≈ 672×1216，1.0MP ≈ 750×1334。

    ★ 2026-10-21（反馈 11.1）：此前段价被写死成「一个数」，于是无法回答两个必然会问的问题：
      「提分辨率划算还是提步数划算」「换 4 步 turbo 能省多少」。
      现在把**变动部分**按「步数 × 像素」的相对计算量线性缩放，固定部分不变：

          scale = (steps / 基准步数) × (megapixels / 基准像素)
          variable = per_second × 秒 × scale

      线性是物理直觉（采样步数与像素都近似线性作用于计算量），**未做多档实测标定** ——
      所以它只用于「A 方案比 B 方案贵多少」的闸门判断，真实消耗一律以平台 usage 为准。
    """
    p = params or DEFAULT_PARAMS
    tier = tier if tier in TIERS else "consumer"
    cfg = p.get(tier) or p["consumer"]
    gpu = p.get("gpu") or {}
    work = p.get("work") or {}
    cny_per_coin = _f((p.get("fx") or {}).get("cny_per_rh_coin"), 0.0025)

    base_steps = _f(work.get("base_steps"), 4.0) or 4.0
    base_mp = _f(work.get("base_megapixels"), 0.8) or 0.8
    st = _f(steps, base_steps) or base_steps
    mp = _f(megapixels, base_mp) or base_mp
    scale = (st / base_steps) * (mp / base_mp)

    rows = []
    tot_fixed = tot_var = tot_gpu_coins = 0.0
    for i, d in enumerate(durations or []):
        dur = _f(d, 0.0) or 12.0
        fixed = _f(cfg.get("fixed"))
        var = _f(cfg.get("per_second")) * dur * scale
        amount = fixed + var
        gpu_s = _f(gpu.get("cold_start_s"), 120.0) + \
            _f(gpu.get("seconds_per_video_second"), 7.2) * dur * scale
        gpu_coins = _f(gpu.get("coins_per_gpu_second"), 0.205) * gpu_s
        tot_fixed += fixed
        tot_var += var
        tot_gpu_coins += gpu_coins
        rows.append({"index": i, "duration_s": round(dur, 2),
                     "fixed": round(fixed, 4), "variable": round(var, 4),
                     "amount": round(amount, 4),
                     "gpu_seconds": round(gpu_s, 1), "gpu_model_coins": round(gpu_coins, 1)})

    total = tot_fixed + tot_var
    if cfg.get("currency") == "money":
        cny = total
        coins = total / cny_per_coin if cny_per_coin else 0.0
    else:
        coins = total
        cny = total * cny_per_coin

    return {
        "tier": tier,
        "tier_label": cfg.get("label") or tier,
        "currency": cfg.get("currency") or "RH币",
        "segments": len(rows),
        "fixed_total": round(tot_fixed, 4),
        "variable_total": round(tot_var, 4),
        "coins": round(coins, 1),
        "cny": round(cny, 2),
        "gpu_model_coins": round(tot_gpu_coins, 1),
        "gpu_seconds": round(sum(r["gpu_seconds"] for r in rows), 1),
        "assumptions": {"steps": st, "megapixels": mp,
                        "base_steps": base_steps, "base_megapixels": base_mp,
                        "work_scale": round(scale, 3),
                        "note": "变动部分按步数×像素线性缩放（近似，未多档实测）；只作闸门"},
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# 自校准：用历史台账（真实 usage）修正参数
# ---------------------------------------------------------------------------
def iter_ledger_records(ws) -> list:
    """从 `<ws>/ledger/runs/*.json` 取出「有真实 usage 的成功 attempt」。

    返回 [{shot_id, duration_s, coins, money, task_cost_time}, ...]
    （`task_cost_time` = 平台返回的 GPU 运行秒，是 P2-7 的关键量）
    """
    root = pathlib.Path(ws) / "ledger" / "runs"
    out = []
    if not root.is_dir():
        return out
    for f in sorted(root.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        for a in (d.get("attempts") or []):
            u = a.get("usage") or {}
            coins = u.get("consumeCoins")
            money = u.get("thirdPartyConsumeMoney")
            cost_time = u.get("taskCostTime")
            if coins in (None, "") and money in (None, ""):
                continue
            out.append({
                "shot_id": d.get("shot_id") or a.get("shot_id"),
                "duration_s": _f(a.get("duration_s"), 0.0) or _f(
                    (a.get("metrics") or {}).get("video_seconds"), 0.0),
                "coins": _f(coins, 0.0) or None,
                "money": _f(money, 0.0) or None,
                "task_cost_time": _f(cost_time, 0.0) or None,
            })
    return out


def _median(xs):
    xs = sorted(xs)
    if not xs:
        return None
    n = len(xs)
    mid = n // 2
    return xs[mid] if n % 2 else (xs[mid - 1] + xs[mid]) / 2.0


def _fit_linear(points):
    """最小二乘拟合 y = a + b·x。points=[(x,y), ...]；样本 <3 或退化返回 None。"""
    pts = [(x, y) for x, y in points if x is not None and y is not None]
    if len(pts) < 3:
        return None
    n = len(pts)
    sx = sum(x for x, _ in pts)
    sy = sum(y for _, y in pts)
    sxx = sum(x * x for x, _ in pts)
    sxy = sum(x * y for x, y in pts)
    den = n * sxx - sx * sx
    if abs(den) < 1e-9:
        return None
    b = (n * sxy - sx * sy) / den
    if b <= 0:            # 斜率必须为正（时长↑成本↑），否则视为不可用
        return None
    a = (sy - b * sx) / n
    return a, b


def calibrate(records, params: dict | None = None) -> dict:
    """用历史台账拟合参数；样本不足时逐项回落，绝不臆造。"""
    p = json.loads(json.dumps(params or DEFAULT_PARAMS))
    recs = [r for r in (records or []) if r.get("duration_s")]
    fitted, evidence = {}, {"samples": len(recs)}

    # ① GPU 秒口径：币/运行秒（用中位数，抗离群）
    ratios = [r["coins"] / r["task_cost_time"] for r in recs
              if r.get("coins") and r.get("task_cost_time")]
    m = _median(ratios)
    if m:
        p.setdefault("gpu", {})["coins_per_gpu_second"] = round(m, 4)
        fitted["coins_per_gpu_second"] = round(m, 4)
        evidence["gpu_ratio_samples"] = len(ratios)

    # ② 两段式：coins = fixed + per_second × duration（仅对 RH币 计价的记录）
    coin_pts = [(r["duration_s"], r["coins"]) for r in recs if r.get("coins")]
    fit = _fit_linear(coin_pts)
    if fit:
        a, b = fit
        p.setdefault("consumer", {})["fixed"] = round(max(0.0, a), 3)
        p["consumer"]["per_second"] = round(b, 4)
        fitted["consumer_fixed"] = round(max(0.0, a), 3)
        fitted["consumer_per_second"] = round(b, 4)
        evidence["coin_fit_samples"] = len(coin_pts)

    # ③ 企业级（钱包金额）：同样拟合，但只在真的有 money 记录时
    money_pts = [(r["duration_s"], r["money"]) for r in recs if r.get("money")]
    fit_m = _fit_linear(money_pts)
    if fit_m:
        a, b = fit_m
        p.setdefault("ent_shared", {})["fixed"] = round(max(0.0, a), 4)
        p["ent_shared"]["per_second"] = round(b, 5)
        fitted["ent_fixed"] = round(max(0.0, a), 4)
        fitted["ent_per_second"] = round(b, 5)
        evidence["money_fit_samples"] = len(money_pts)

    return {"params": p, "fitted": fitted, "evidence": evidence}


def write_params(ws, params: dict) -> pathlib.Path:
    """把参数写回 `<ws>/cost-model.json`（校准结果的落盘位置）。"""
    p = pathlib.Path(ws) / "cost-model.json"
    p.write_text(json.dumps(params, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p
