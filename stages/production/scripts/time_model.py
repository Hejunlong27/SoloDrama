#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""time_model.py —— 出片**耗时**估算（成本口径已从「钱」改为「时间」）

为什么不再算钱
--------------
2026-11-04 起本仓库只支持本地 ComfyUI：出图、出片、放大全部跑在本机。
没有按次计费的平台，也就没有「币 / 美元 / 人民币」这层账 —— 剩下的唯一稀缺资源是
**本机 GPU 时间**。一集要跑 1 小时还是 8 小时，决定了这件事能不能当产能用，
比「￥0」有意义得多。

口径
----
每个阶段都算成「秒」，再折算成人话：

    资产出图   张数 × 每张秒数
    分镜图     镜数 × 每张秒数
    出片       镜数 × (每秒成片秒数 × 镜长 + 每镜固定开销)   ← 占大头
    剪辑       拼接 + 放大 + 对齐 + 烧录 + 导出

`DEFAULTS` 里的系数是**可校准的**：`--calibrate` 会读 `video-pipeline/ledger/` 的真实
`wall_elapsed_s`，按阶段取中位数反推系数，写进 `<ws>/time-model.json`。
没实测过的项目就用默认值 —— 默认值标注了来源，不假装精确。

设计纪律
--------
* 纯标准库、零网络、零依赖。
* **只估算、不承诺**：输出带 `confidence`（measured / estimated），界面上要显示出来。
  一个「预计 76 分钟」如果没注明是估的，人就会拿它排期。
* 系数全部集中在这一处。别在 CLI / Web / 文档里各写一份 —— 那种分叉最后一定会对不上。
"""
from __future__ import annotations

import json
import pathlib
import statistics

# ===========================================================================
# 默认系数（本机 RTX 4060 Laptop 8G / 16G RAM）
# ===========================================================================
# 来源标注：
#   [实测] = 本仓库真跑过的数据（能力卡或台账）
#   [估]   = 按同类模型在 4060 上的经验值，**未在本机实测**，第一次真跑后应校准
DEFAULTS: dict = {
    "_hardware": "RTX 4060 Laptop 8G",

    # —— 出图（Qwen Image 2.1 turbo，2MP，8 步）——
    "image_sec": 50,                 # [实测] 能力卡 comfy.qwen21_t2i_hq.v1 的 wall_sec_per_image
    "board_sec": 50,                 # [估] 分镜图与资产图同模型同尺寸，取同值

    # —— 出片（Minimax H3，10 步固定 sigmas，1344×1792 量级）——
    # 这个系数决定整条产线的时间量级，是最需要实测的一个。
    # 估算依据：H3 在 4090 级上约 30–40 秒/秒成片；4060 约 1/4 算力 → 120–160。
    # 取 140（略保守）。首次真跑后用 `time_model.py --calibrate` 覆盖。
    "video_sec_per_out_sec": 140,    # [估] 每 1 秒成片需要多少秒 GPU
    "video_overhead_sec": 45,        # [估] 每镜固定开销：上传参考图 + 排队 + 解码 + 落盘
    "video_max_seconds": 12,         # [实测] 8G 卡上的时长上限（再长会 OOM）

    # —— 剪辑（纯 CPU/ffmpeg，与视频总长成正比）——
    "concat_sec_per_min": 12,        # [估] 母版拼接（含帧数校验）
    "upscale_sec_per_min": 180,      # [估] Topaz 本地超分（不开放大时为 0）
    "align_sec_per_min": 30,         # [估] whisper / CTC 强制对齐
    "burn_sec_per_min": 25,          # [估] 烧字幕 + 交付规格归一
    "export_sec": 15,                # [估] 导出发布版（remux，不重编码）

    # —— 别的 ——
    "pack_import_sec": 5,            # [实测] 导入 30 集约 2 秒
    "overhead_ratio": 0.12,          # [估] 重跑/修补的期望损耗（一次通过的镜约占 88%）
}

# 阶段显示名与顺序
PHASES = [
    ("import", "导入"),
    ("assets", "资产出图"),
    ("boards", "分镜图"),
    ("video", "出片"),
    ("edit", "剪辑"),
]

CONF_MEASURED = "measured"
CONF_ESTIMATED = "estimated"


# ===========================================================================
# 参数
# ===========================================================================
def load_params(ws=None) -> dict:
    """读参数：仓库默认 < `<ws>/time-model.json`（校准结果）。"""
    p = dict(DEFAULTS)
    if ws:
        f = pathlib.Path(ws) / "time-model.json"
        try:
            d = json.loads(f.read_text(encoding="utf-8-sig"))
            if isinstance(d, dict):
                p.update({k: v for k, v in d.items() if k in DEFAULTS})
                if d.get("_calibrated_at"):
                    p["_calibrated_at"] = d["_calibrated_at"]
        except (OSError, json.JSONDecodeError, ValueError):
            pass
    return p


def write_params(ws, params: dict) -> pathlib.Path:
    p = pathlib.Path(ws) / "time-model.json"
    out = {k: v for k, v in params.items() if k in DEFAULTS}
    out["_note"] = "由 time_model.py --calibrate 从台账实测反推；删掉本文件即回到仓库默认值"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8", newline="")
    return p


# ===========================================================================
# 人话
# ===========================================================================
def human(sec: float) -> str:
    """秒 → 「1 小时 16 分」/「7 分 30 秒」/「45 秒」。"""
    try:
        s = int(round(float(sec)))
    except (TypeError, ValueError):
        return "—"
    if s < 60:
        return "%d 秒" % s
    m, s = divmod(s, 60)
    if m < 60:
        return ("%d 分" % m) if s < 30 else ("%d 分 %d 秒" % (m, s))
    h, m = divmod(m, 60)
    return ("%d 小时 %d 分" % (h, m)) if m else ("%d 小时" % h)


# ===========================================================================
# 估算
# ===========================================================================
def estimate_episode(n_shots: int, avg_shot_sec: float, n_images: int, *,
                     n_boards: int | None = None,
                     upscale: bool = False,
                     params: dict | None = None) -> dict:
    """一集的耗时分解。

    n_shots        本集镜头数
    avg_shot_sec   平均每镜秒数（4–15）
    n_images       本集用到的资产图张数（人/场/道的变体数之和）
    n_boards       分镜图张数（默认 = n_shots）
    upscale        是否开超分（本地 Topaz，很吃时间）
    """
    p = params or DEFAULTS
    n_boards = n_shots if n_boards is None else n_boards
    total_video = max(0.0, float(n_shots) * float(avg_shot_sec))

    raw = {
        "import": float(p["pack_import_sec"]),
        "assets": float(n_images) * float(p["image_sec"]),
        "boards": float(n_boards) * float(p["board_sec"]),
        "video": float(n_shots) * (float(p["video_sec_per_out_sec"]) * float(avg_shot_sec)
                                   + float(p["video_overhead_sec"])),
        "edit": 0.0,
    }
    mins = total_video / 60.0
    raw["edit"] = (mins * float(p["concat_sec_per_min"])
                   + (mins * float(p["upscale_sec_per_min"]) if upscale else 0.0)
                   + mins * float(p["align_sec_per_min"])
                   + mins * float(p["burn_sec_per_min"])
                   + float(p["export_sec"]))

    # 重跑损耗：一次通过的镜只占 88%，剩下的要再跑一遍
    loss = sum(raw.values()) * float(p["overhead_ratio"])

    details = {
        "import": "1 次",
        "assets": "%d 张 × %ds" % (n_images, int(p["image_sec"])),
        "boards": "%d 张 × %ds" % (n_boards, int(p["board_sec"])),
        "video": "%d 镜 × (%.0f × %.1fs + %ds)"
                 % (n_shots, p["video_sec_per_out_sec"], avg_shot_sec, int(p["video_overhead_sec"])),
        "edit": "%.1f 分钟素材 · 拼接%s + 对齐 + 烧录" % (mins, " + 超分" if upscale else ""),
    }

    phases = []
    for key, label in PHASES:
        phases.append({"key": key, "label": label, "sec": round(raw[key], 1),
                       "human": human(raw[key]), "detail": details[key]})
    phases.append({"key": "retry", "label": "重跑余量",
                   "sec": round(loss, 1), "human": human(loss),
                   "detail": "按 %.0f%% 的补跑率预留" % (p["overhead_ratio"] * 100)})

    total = sum(x["sec"] for x in phases)
    return {
        "shots": n_shots, "avg_shot_sec": avg_shot_sec, "video_sec": round(total_video, 1),
        "images": n_images, "boards": n_boards, "upscale": bool(upscale),
        "phases": phases,
        "total_sec": round(total, 1),
        "total_human": human(total),
        "confidence": CONF_ESTIMATED if not p.get("_calibrated_at") else CONF_MEASURED,
        "hardware": p.get("_hardware"),
        "bottleneck": max(phases[:-1], key=lambda x: x["sec"])["label"],
    }


def estimate_season(per_ep: dict, n_eps: int, *, parallel: int = 1) -> dict:
    """整季 = 单集 × 集数 ÷ 并行度。本地通道并行恒为 1（单卡 8G）。"""
    par = max(1, int(parallel))
    sec = float(per_ep["total_sec"]) * int(n_eps) / par
    return {"episodes": int(n_eps), "parallel": par,
            "total_sec": round(sec, 1), "total_human": human(sec),
            "per_ep_human": per_ep["total_human"],
            "note": ("本地单卡并发固定 1：第二个任务进来就 OOM，所以这里不做并行加速"
                     if par == 1 else "并行 %d（仅在多卡/多机时成立）" % par)}


# ===========================================================================
# 校准
# ===========================================================================
def iter_records(ws) -> list:
    """读台账里所有 run 记录（`video-pipeline/ledger/runs/**/*.json`）。"""
    root = pathlib.Path(ws) / "video-pipeline" / "ledger" / "runs"
    out = []
    if not root.is_dir():
        return out
    for f in root.rglob("*.json"):
        try:
            d = json.loads(f.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if isinstance(d, dict):
            d["_file"] = f.name
            out.append(d)
    return out


def _median(xs):
    xs = [float(x) for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def calibrate(records: list, params: dict | None = None) -> dict:
    """从真实耗时反推系数。

    只反推**能反推的**三个：
      * image_sec          ← stage=image 的 wall_elapsed_s 中位数
      * video_overhead_sec ← stage=h3-video 的 wall 中位数 − 系数 × 时长（若时长可读）
      * video_sec_per_out_sec ← 用 (wall − overhead) / 时长 的比值中位数
    剪辑类阶段样本太少，不动 —— 宁可留默认值，也不要拿两条样本拟合一条直线。
    """
    p = dict(params or DEFAULTS)
    got: dict = {}
    samples: dict = {}

    for r in records:
        stage = str(r.get("stage") or r.get("kind") or "")
        w = r.get("wall_elapsed_s")
        try:
            w = float(w)
        except (TypeError, ValueError):
            continue
        if w <= 0:
            continue
        samples.setdefault(stage, []).append((w, r))

    img = _median([w for w, _ in samples.get("image", [])])
    if img and img > 1:
        p["image_sec"] = round(img, 1)
        p["board_sec"] = round(img, 1)
        got["image_sec"] = p["image_sec"]

    vid = samples.get("h3-video") or samples.get("video") or []
    ratios, overheads = [], []
    for w, r in vid:
        dur = r.get("duration_s") or (r.get("extra") or {}).get("duration")
        try:
            dur = float(dur)
        except (TypeError, ValueError):
            dur = 0.0
        if dur > 0 and w > dur:
            # w = overhead + k × dur  →  k = (w − overhead) / dur
            overheads.append(w - float(p["video_sec_per_out_sec"]) * dur)
            ratios.append((w - float(p["video_overhead_sec"])) / dur)
    med_v, med_o = _median(ratios), _median(overheads)
    if med_v and med_v > 1:
        p["video_sec_per_out_sec"] = round(med_v, 1)
        got["video_sec_per_out_sec"] = p["video_sec_per_out_sec"]
    if med_o is not None and med_o >= 0:
        p["video_overhead_sec"] = round(med_o, 1)
        got["video_overhead_sec"] = p["video_overhead_sec"]

    return {"params": p, "applied": got,
            "samples": {k: len(v) for k, v in samples.items()},
            "enough": bool(got)}


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="出片耗时估算（成本口径 = 时间）")
    ap.add_argument("--workspace", default=None)
    ap.add_argument("--episodes", type=int, default=1, help="算几集（默认 1）")
    ap.add_argument("--shots", type=int, default=8, help="每集镜头数（默认 8）")
    ap.add_argument("--shot-seconds", dest="shot_seconds", type=float, default=6.0,
                    help="平均每镜秒数（默认 6）")
    ap.add_argument("--images", type=int, default=12, help="每集资产图张数（默认 12）")
    ap.add_argument("--upscale", action="store_true", help="计入本地超分耗时")
    ap.add_argument("--calibrate", action="store_true", help="从台账实测反推系数并写回")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    ws = a.workspace
    if not ws:
        import os
        ws = os.environ.get("SOLODRAMA_WORKSPACE") or os.environ.get("DRAMA_WORKSPACE")

    if a.calibrate:
        if not ws:
            print("[FAIL] --calibrate 需要 --workspace（或 SOLODRAMA_WORKSPACE）")
            return 2
        recs = iter_records(ws)
        r = calibrate(recs, load_params(ws))
        if not r["enough"]:
            print("[FAIL] 台账里还没有可用的实测样本（样本：%s）" % (r["samples"] or "无"))
            print("       先真跑几条（出图 + 出片），再回来校准。")
            return 3
        f = write_params(ws, r["params"])
        print("[OK] 已用实测校准：%s" % json.dumps(r["applied"], ensure_ascii=False))
        print("     样本数：%s" % json.dumps(r["samples"], ensure_ascii=False))
        print("     写入：%s" % f)
        return 0

    p = load_params(ws)
    ep = estimate_episode(a.shots, a.shot_seconds, a.images, upscale=a.upscale, params=p)
    print("=" * 74)
    print("出片耗时估算（%s）" % (ep["hardware"] or "本机"))
    print("=" * 74)
    print("  输入：%d 镜 × %.1fs ｜ 资产图 %d 张 ｜ %s"
          % (ep["shots"], ep["avg_shot_sec"], ep["images"], "含超分" if ep["upscale"] else "不超分"))
    print("-" * 74)
    for ph in ep["phases"]:
        print("  %-10s %-12s %s" % (ph["label"], ph["human"], ph["detail"]))
    print("-" * 74)
    print("  单集合计：%s ｜ 瓶颈：%s" % (ep["total_human"], ep["bottleneck"]))
    if ep["confidence"] != CONF_MEASURED:
        print("  [注意] 系数是经验值，未在本机实测。首次真跑后执行：")
        print("         python stages/production/scripts/time_model.py --calibrate --workspace <ws>")
    if a.episodes and a.episodes > 1:
        s = estimate_season(ep, a.episodes)
        print("  %d 集合计：%s（%s）" % (s["episodes"], s["total_human"], s["note"]))
    if a.json:
        print(json.dumps({"episode": ep,
                          "season": estimate_season(ep, a.episodes) if a.episodes > 1 else None},
                         ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
