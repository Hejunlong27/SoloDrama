#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""comfy_batch_video.py —— 按集批量出片（本地 ComfyUI，￥0）

为什么单独一个脚本，而不是给 `comfy_local_video.py` 加循环
---------------------------------------------------------
后者是**单条**工具：一次一个 prompt、一组参考图，用来调参数、试风格。
批量出片要处理的是另一类问题：从 `data/<ep>/` 读契约、按 cast 顺序铺参考图、
产物落到 `07-成片/<ep>/<shot>/final.mp4`、断点续跑、以及「这一镜为什么没出」。

把两者混在一起的结果是：单条工具被批量逻辑污染（参数爆炸），
而批量逻辑又受单条工具的 CLI 形状限制（--ref 一个一个敲）。

输入（与 RH 通道共用同一份契约）
--------------------------------
    <ws>/06-提示词/<ep>/shots.json        shot_id / board_ref / cast / character_refs / scene_refs
    <ws>/06-提示词/<ep>/h3_prompts.json   prompt / duration / ratio
    <ws>/06-提示词/<ep>/characters.json   key → 图片路径
    <ws>/06-提示词/<ep>/scenes.json       同上
    <ws>/04-资产/boards/<ep>/<shot>.png   分镜图（首帧，占第 1 张参考位）

输出
----
    <ws>/07-成片/<ep>/<shot_id>/final.mp4    与 RH 通道同落点，`video.audit` 判据直接可用
    <ws>/07-成片/<ep>/_batch_local.json      本次批次的逐镜状态（失败原因写在这）

用法
----
    python comfy_batch_video.py --workspace "D:/剧/x" --ep ep01                 # 干跑
    python comfy_batch_video.py --workspace "D:/剧/x" --ep ep01 --submit       # 真跑（占 GPU）
    python comfy_batch_video.py --workspace "D:/剧/x" --ep ep01 --submit --only shot_003
    python comfy_batch_video.py --workspace "D:/剧/x" --ep ep01 --submit --force   # 已出的也重跑

退出码：0 全部有产物 / 3 有缺口（与引擎一致的批次缺口语义）
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]                       # stages/video/comfyui → 仓库根
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "stages"))
sys.path.insert(0, str(ROOT / "stages" / "production" / "scripts"))
sys.path.insert(0, str(ROOT / "stages" / "video" / "workflow" / "scripts" / "engine"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[union-attr]
except Exception:                                                # noqa: BLE001
    pass

import comfy_local_video as V                # noqa: E402  单条出片的实现，这里复用
import _layout as L                          # noqa: E402

IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")


# ---------------------------------------------------------------------------
# 输入
# ---------------------------------------------------------------------------
def load_json(p: pathlib.Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, ValueError):
        return default


def load_episode(ws: pathlib.Path, ep: str) -> tuple:
    """读一集的四份契约 → (shots, prompts, ref_table, board_dir, problems)。"""
    data = L.data_dir(ws) / ep
    problems: list = []
    shots = load_json(data / "shots.json", None)
    prompts = load_json(data / "h3_prompts.json", None)
    if shots is None:
        problems.append("缺 shots.json：%s（先跑 pack import）" % (data / "shots.json"))
        shots = []
    if not isinstance(shots, list):
        shots = (shots or {}).get("shots") or []
    if prompts is None:
        problems.append("缺 h3_prompts.json：%s" % (data / "h3_prompts.json"))
        prompts = {}

    table: dict = {}
    for name in ("characters.json", "scenes.json"):
        d = load_json(data / name, {}) or {}
        if isinstance(d, dict):
            table.update({k: v for k, v in d.items() if isinstance(v, str)})
    if not table:
        problems.append("characters/scenes.json 都是空的 —— 资产图还没出，或导入后没重跑回填")

    board_dir = L.assets_dir(ws) / "boards" / ep
    return shots, prompts, table, board_dir, problems


def resolve_refs(shot: dict, table: dict, board_dir: pathlib.Path,
                 data_dir: pathlib.Path, max_slots: int) -> tuple:
    """一镜 → (参考图绝对路径列表, 说明列表)。

    顺序口径（**这就是提示词里 {{Mixed n}} 的 n**）：
        cast（制作包里的完整有序列表）
        → 缺 cast 时回落到 character_refs + scene_refs（老 data 的写法）
    分镜图若存在，插到最前面当第 1 张 —— 与 RH 通道 `<Picture 1>` 的位置一致。
    """
    notes: list = []
    keys = shot.get("cast")
    if not isinstance(keys, list) or not keys:
        keys = list(shot.get("character_refs") or []) + list(shot.get("scene_refs") or [])

    paths: list = []
    sid = str(shot.get("shot_id") or "")

    # 分镜图（可选）
    bp = board_dir / (sid + ".png")
    if bp.is_file():
        paths.append(str(bp))
        notes.append("分镜图 %s" % bp.name)
    else:
        notes.append("无分镜图（退化为纯资产参考）")

    for key in keys:
        raw = table.get(str(key))
        if not raw:
            notes.append("key=%s 未登记（跳过）" % key)
            continue
        p = pathlib.Path(raw)
        if not p.is_absolute():
            p = (data_dir / raw).resolve()
        if not p.is_file():
            notes.append("key=%s 指向的文件不存在（跳过）" % key)
            continue
        if str(p) in paths:
            notes.append("key=%s 与前面的图重复（去重）" % key)
            continue
        paths.append(str(p))

    if max_slots and len(paths) > max_slots:
        notes.append("参考图 %d 张超过槽位 %d，多余的丢弃：%s"
                     % (len(paths), max_slots, ", ".join(os.path.basename(x) for x in paths[max_slots:])))
        paths = paths[:max_slots]
    return paths, notes


def max_image_slots(wf: dict, m: dict) -> int:
    """工作流最多能接几张参考图 = 映射里登记的 LoadImage 数 + 其余 LoadImage。"""
    ids = [x for x in (m.get("images") or []) if str(x) in wf] if isinstance(m.get("images"), list) else []
    extra = [nid for nid, n in wf.items()
             if str(n.get("class_type")) == "LoadImage" and nid not in ids]
    return len(ids) + len(extra)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="按集批量出片（本地 ComfyUI，￥0；默认干跑）")
    ap.add_argument("--workspace", default=None)
    ap.add_argument("--ep", required=True, help="集号（ep01 / 1）")
    ap.add_argument("--workflow", default="", help="API 格式工作流（默认 comfy_local_video 的默认值）")
    ap.add_argument("--map", default="")
    ap.add_argument("--only", default="", help="只做这些镜（shot_001,shot_003）")
    ap.add_argument("--limit", type=int, default=0, help="最多做几个（0 = 全部）")
    ap.add_argument("--force", action="store_true", help="已有产物也重跑")
    ap.add_argument("--submit", action="store_true", help="真的提交（占 GPU，不花钱）")
    ap.add_argument("--timeout-min", type=float, default=20.0)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    # 集号归一（ep01 / 1 / 第1集 → ep01）
    ep_raw = a.ep.strip()
    digits = "".join(ch for ch in ep_raw if ch.isdigit())
    if not digits:
        print("[FAIL] 认不出集号：%r（写 ep01 或 1）" % a.ep)
        return 2
    ep = "ep%02d" % int(digits)

    ws_raw = a.workspace or os.environ.get("SOLODRAMA_WORKSPACE") or os.environ.get("DRAMA_WORKSPACE")
    if not ws_raw:
        print("[FAIL] 需要 --workspace（或 SOLODRAMA_WORKSPACE）")
        return 2
    ws = pathlib.Path(ws_raw).expanduser().resolve()

    shots, prompts, table, board_dir, problems = load_episode(ws, ep)
    if problems:
        for p in problems:
            print("[FAIL] %s" % p)
        return 2
    if not shots:
        print("[FAIL] %s 里没有 shots" % ep)
        return 2

    wf = V.load_workflow(a.workflow)
    m, map_src = V.load_map(a.workflow, a.map)
    slots = max_image_slots(wf, m)

    # 逐镜计划
    want = {x.strip() for x in a.only.split(",") if x.strip()} if a.only else None
    out_root = L.out_dir(ws) / ep
    plan, skipped = [], []
    for s in shots:
        sid = str(s.get("shot_id") or "")
        if not sid:
            continue
        if want and sid not in want:
            continue
        meta = prompts.get(sid) or {}
        prompt = str(meta.get("prompt") or "").strip()
        if not prompt:
            skipped.append((sid, "h3_prompts.json 里没有这一镜的 prompt"))
            continue
        dur = meta.get("duration") or s.get("duration")
        refs, notes = resolve_refs(s, table, board_dir, L.data_dir(ws) / ep, slots)
        dest = out_root / sid / "final.mp4"
        plan.append({"sid": sid, "prompt": prompt, "seconds": dur,
                     "refs": refs, "notes": notes, "dest": dest,
                     "exists": dest.is_file()})
    if a.limit:
        plan = plan[: a.limit]

    todo = [p for p in plan if a.force or not p["exists"]]
    print("=" * 78)
    print("本地 ComfyUI 批量出片%s：%s" % ("（干跑）" if not a.submit else "", ep))
    print("=" * 78)
    print("  工作区  ：%s" % ws)
    print("  工作流  ：%s" % (a.workflow or V.DEFAULT_WORKFLOW))
    print("  映射    ：%s" % map_src)
    print("  参考槽  ：%d 张" % slots)
    print("  计划    ：%d 镜（待跑 %d，已有产物 %d，跳过 %d）"
          % (len(plan), len(todo), len(plan) - len(todo), len(skipped)))
    print("-" * 78)
    for p in plan:
        mark = "跳过" if (p["exists"] and not a.force) else "待跑"
        print("  %-10s %5ss  %s  参考图 %d 张" %
              (p["sid"], (p["seconds"] or "?"), mark, len(p["refs"])))
        for n in p["notes"]:
            print("               · %s" % n)
    for sid, why in skipped:
        print("  %-10s 跳过：%s" % (sid, why))
    print("-" * 78)

    if not a.submit:
        print("干跑结束。加 --submit 真跑（占 GPU，约 2–6 分钟/镜，视显存与时长）。")
        if a.json:
            print(json.dumps({"ok": True, "dry_run": True,
                              "plan": [{"shot": p["sid"], "refs": len(p["refs"])} for p in plan],
                              "skipped": skipped}, ensure_ascii=False, indent=2))
        return 0

    # ---- 真跑 ----------------------------------------------------------
    if not todo:
        print("[OK] 没有待跑的镜（已有产物）。要重跑加 --force。")
        return 0

    results = []
    t_all = time.time()
    for i, p in enumerate(todo, 1):
        sid = p["sid"]
        print("\n[%d/%d] %s ｜ %.0fs ｜ 参考图 %d 张"
              % (i, len(todo), sid, p["seconds"] or 0, len(p["refs"])))
        row = {"shot": sid, "status": "FAILED", "file": "", "error": "", "wall_s": 0}
        t0 = time.time()
        try:
            # 上传参考图（ComfyUI 需要先落到它的 input 目录）
            names = [V.upload_image(x) for x in p["refs"]] if p["refs"] else []
            wf2 = V.apply_nodes(json.loads(json.dumps(wf)), m,
                                prompt=p["prompt"], ref_names=names,
                                seconds=p["seconds"], steps=None,
                                seed=int(time.time()) % 2_000_000_000,
                                aspect=None, mp=None, prefix="h3_%s" % sid)
            res = V.submit_and_wait(wf2, timeout_min=a.timeout_min)
            files = res.get("files") or []
            if not files:
                raise RuntimeError("任务成功但没有产物文件")
            # 保持真实扩展名：VHS_VideoCombine 正常给 .mp4，给 .webm 说明 pix_fmt 被改过，
            # 这时不要硬改名成 .mp4（下游 ffmpeg 会读不出来），原样存并告警。
            ext = os.path.splitext(str(files[0].get("filename") or ""))[1].lower() or ".mp4"
            p["dest"].parent.mkdir(parents=True, exist_ok=True)
            saved = V.download(files[0], str(p["dest"].parent), "final" + ext)
            if ext != ".mp4":
                print("      [WARN] 产物是 %s，剪辑环节只认 final.mp4 —— 需要转码" % ext)
            row.update({"status": "SUCCESS", "file": str(saved)})
            print("      → %s" % saved)
        except Exception as exc:                              # noqa: BLE001
            row["error"] = "%s: %s" % (type(exc).__name__, exc)
            print("      [FAIL] %s" % row["error"])
        row["wall_s"] = round(time.time() - t0, 1)
        results.append(row)

    ok = [r for r in results if r["status"] == "SUCCESS"]
    wall = round(time.time() - t_all, 1)
    summary = {"episode": ep, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "channel": "comfyui-local", "billed": False,
               "totals": {"total": len(results), "success": len(ok),
                          "failed": len(results) - len(ok)},
               "wall_s": wall, "items": results}
    (out_root).mkdir(parents=True, exist_ok=True)
    sp = out_root / "_batch_local.json"
    sp.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                  encoding="utf-8", newline="")

    print("\n" + "=" * 78)
    print("完成：%d/%d 成功（墙钟 %.1fs，费用 ￥0）" % (len(ok), len(results), wall))
    print("批次记录：%s" % sp)
    if len(ok) < len(results):
        for r in results:
            if r["status"] != "SUCCESS":
                print("  [缺口] %s：%s" % (r["shot"], r["error"]))
        print("★ 有缺口时不要改提示词重跑，直接再跑同一条命令（默认只补缺）。")
    if a.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if len(ok) == len(results) else 3


if __name__ == "__main__":
    sys.exit(main())
