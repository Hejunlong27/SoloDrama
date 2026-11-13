#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""zzai_video.py —— 用真真AI 视频 API（minimax-h3-comfyui-max）按集批量出片

它接的是哪一段
--------------
引擎原本只有三条出片通道：本地/云端 ComfyUI（`comfy_batch_video.py`）与
RunningHub（`stages/video/workflow/scripts/run.py`）。真真AI 这条是第四个通道：
**不占本机 GPU、不依赖 ComfyUI 工作流文件**，按秒计费，适合「本机显卡不够 / 想跑量」。

产物落点与其余三条**完全一致**：
    07-成片/<ep>/<shot_id>/final.mp4
    07-成片/<ep>/_batch_zzai.json       本批次逐镜状态（失败原因写在这）
所以字幕、母版拼接、合规检查这些下游环节一行都不用改。

参考图顺序（与提示词里的 <Picture n> 对齐，这条错一位画面就换脸）
----------------------------------------------------------------
    1. 分镜图 `04-资产/boards/<ep>/<shot>.png`（若存在）
    2. shots.json 的 cast 顺序（角色卡 → 场景卡）
这条口径与 `comfy_batch_video.resolve_refs()` 相同，本文件里重写了一份而不是 import
对方 —— 那个模块 import 期就会去解析 ComfyUI 客户端与环境，纯 API 通道不该背着这份依赖。

用法
----
    python zzai_video.py --workspace "D:/剧本/海外剧/10" --ep ep01                 # 干跑+报价
    python zzai_video.py --workspace "..." --ep ep01 --yes --max-cost 0.30         # 真出
    python zzai_video.py --workspace "..." --ep ep01 --yes --max-cost 0.30 --only shot_003
    python zzai_video.py --workspace "..." --ep ep01 --limit 1 --yes --max-cost 0.30  # 先出小样

退出码：0 该集全部有产物 / 3 有缺口 / 4 闸门未过（缺 --yes 或 --max-cost）/ 2 参数或环境错误
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import pathlib
import sys
import threading
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")     # type: ignore[union-attr]
except Exception:                                                  # noqa: BLE001
    pass

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]                                             # stages/media_api → 仓库根
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "stages"))
sys.path.insert(0, str(ROOT / "stages" / "production" / "scripts"))

import _layout as L                                                # noqa: E402
from stages.media_api import zzai_batch as ZB                       # noqa: E402
from stages.media_api.zzai import ZZAIError                         # noqa: E402

DEFAULT_MODEL = "minimax-h3-comfyui-max"
RESOLUTIONS = ("480p", "1088p")
DUR_MIN, DUR_MAX = 3, 15   # 2026-11-13 实测：提交侧只接受 3–15 的整数秒（estimate 更宽松，别信它）


def _json(p: pathlib.Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, ValueError):
        return default


def load_episode(ws: pathlib.Path, ep: str) -> tuple:
    """→ (shots, prompts, ref_table, board_dir, problems)。口径与 comfy_batch_video 一致。"""
    data = L.data_dir(ws) / ep
    problems: list = []
    shots = _json(data / "shots.json", None)
    prompts = _json(data / "h3_prompts.json", None)
    if shots is None:
        problems.append("缺 shots.json：%s（先跑 drama do import.pack）" % (data / "shots.json"))
        shots = []
    if not isinstance(shots, list):
        shots = (shots or {}).get("shots") or []
    if prompts is None:
        problems.append("缺 h3_prompts.json：%s" % (data / "h3_prompts.json"))
        prompts = {}
    table: dict = {}
    for name in ("characters.json", "scenes.json"):
        d = _json(data / name, {}) or {}
        if isinstance(d, dict):
            table.update({k: v for k, v in d.items() if isinstance(v, str)})
    if not table:
        problems.append("characters/scenes.json 都是空的 —— 资产图还没出，或出完没重跑导入回填")
    return shots, prompts, table, L.assets_dir(ws) / "boards" / ep, problems


def resolve_refs(shot: dict, table: dict, board_dir: pathlib.Path,
                 data_dir: pathlib.Path, max_slots: int = 9) -> tuple:
    """一镜 → (参考图路径列表, 说明列表)。分镜图占第 1 位，随后按 cast 顺序。"""
    notes: list = []
    keys = shot.get("cast")
    if not isinstance(keys, list) or not keys:
        keys = list(shot.get("character_refs") or []) + list(shot.get("scene_refs") or [])
    sid = str(shot.get("shot_id") or "")
    paths: list = []
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
        notes.append("参考图 %d 张超过上限 %d，多余的丢弃" % (len(paths), max_slots))
        paths = paths[:max_slots]
    return paths, notes


def _duration_of(prompts: dict, sid: str, shots_meta: dict) -> tuple:
    """→ (秒数, 说明)。模型只吃 3–15 的整秒；超出就报错而不是悄悄截断。"""
    raw = (prompts.get(sid) or {}).get("duration")
    if raw in (None, ""):
        raw = shots_meta.get("duration")
    try:
        f = float(raw)
    except (TypeError, ValueError):
        return None, "缺时长（h3_prompts 与 shots.json 都没有 duration）"
    sec = int(round(f))
    if sec < DUR_MIN:
        return DUR_MIN, "时长 %.1fs 低于模型下限，按 %ds 提交" % (f, DUR_MIN)
    if sec > DUR_MAX:
        return None, "时长 %.1fs 超过模型上限 %ds：需要拆镜（本通道不替你截断）" % (f, DUR_MAX)
    return sec, ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="真真AI 视频通道：按集批量出片")
    ap.add_argument("--workspace", default=None)
    ap.add_argument("--ep", required=True, help="集号，如 ep01")
    ap.add_argument("--only", default="", help="只做指定 shot_id，逗号分隔")
    ap.add_argument("--limit", type=int, default=0, help="只做前 N 镜")
    ap.add_argument("--force", action="store_true", help="已有 final.mp4 也重跑")
    ap.add_argument("--yes", action="store_true", help="真实提交确认（计费）")
    ap.add_argument("--max-cost", dest="max_cost", type=float, default=None,
                    help="单镜 CNY 上限；真实提交必填")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--resolution", default="1088p", choices=RESOLUTIONS)
    ap.add_argument("--concurrency", type=int, default=1,
                    help="同时在飞的镜数（默认 1 串行；服务端是异步队列，实测可并行）")
    ap.add_argument("--poll-seconds", dest="poll_seconds", type=float, default=5.0)
    ap.add_argument("--timeout-min", dest="timeout_min", type=float, default=30.0)
    ap.add_argument("--json", action="store_true", help="机器可读汇总")
    a = ap.parse_args(argv)

    ws = pathlib.Path(a.workspace).expanduser().resolve() if a.workspace else pathlib.Path(
        os.environ.get("SOLODRAMA_WORKSPACE") or ".").resolve()
    data_dir = L.data_dir(ws) / a.ep
    out_dir = L.out_dir(ws) / a.ep
    shots, prompts, table, board_dir, problems = load_episode(ws, a.ep)

    print("=" * 74)
    print("真真AI 出片 · %s" % a.ep)
    print("=" * 74)
    print("  工作区 : %s" % ws)
    print("  模型   : %s @%s" % (a.model, a.resolution))
    print("  契约   : %s（%d 镜）" % (data_dir, len(shots)))
    print("  落点   : %s/<shot_id>/final.mp4" % out_dir)
    for p in problems:
        print("  [WARN] %s" % p)

    want = {s.strip() for s in a.only.replace("，", ",").split(",") if s.strip()}
    picked = [s for s in shots if isinstance(s, dict) and (not want or s.get("shot_id") in want)]
    if a.limit:
        picked = picked[: a.limit]
    if not picked:
        print("\n[WARN] 没有要出的镜（--only / --limit 可能写错）")
        return 0

    client = ZB.client_from_env()
    up = ZB.Uploader(client)
    units = []
    for s in picked:
        sid = str(s.get("shot_id") or "")
        dst = out_dir / sid / "final.mp4"
        if dst.is_file() and not a.force:
            print("[skip] %s 已有成片" % sid)
            continue
        pr = prompts.get(sid) or {}
        prompt = str(pr.get("prompt") or "")
        if not prompt.strip():
            print("[FAIL] %s 没有 h3 提示词，跳过（先补齐 06-提示词/%s/h3_prompts.json）" % (sid, a.ep))
            continue
        sec, note = _duration_of(prompts, sid, s)
        if sec is None:
            print("[FAIL] %s %s" % (sid, note))
            continue
        if note:
            print("  [提示] %s %s" % (sid, note))
        refs, notes = resolve_refs(s, table, board_dir, data_dir)
        if not refs:
            print("[FAIL] %s 一张参考图都解析不到（分镜图与资产图都不在位）" % sid)
            continue
        ratio = str(s.get("ratio") or pr.get("ratio") or "9:16")
        units.append({"sid": sid, "prompt": prompt, "refs": refs, "notes": notes,
                      "duration": sec, "ratio": ratio, "dst": dst})
    if not units:
        print("\n没有需要出片的镜。")
        return 0

    # 报价：先估后传图（estimate 免费），金额信息先给用户看
    quotes, total = [], 0.0
    for u in units:
        payload = {"model": a.model, "prompt": u["prompt"], "images": [],
                   "duration": u["duration"], "resolution": a.resolution,
                   "aspect_ratio": u["ratio"]}
        u["payload"] = payload
        try:
            est = ZB.quote(client, "video", payload)
        except ZZAIError as exc:
            est = {"estimate_available": False, "error": str(exc)}
        u["estimate"] = est
        if isinstance(est.get("amount"), (int, float)):
            total += float(est["amount"])
        quotes.append(u)

    for u in quotes:
        amt = u["estimate"].get("amount")
        print("  %-10s %2ds %-5s 参考图 %d 张  →  %s" % (
            u["sid"], u["duration"], u["ratio"], len(u["refs"]),
            ("¥%.4f" % amt) if isinstance(amt, (int, float)) else "报价不可用"))
    print("\n预估合计：¥%.4f（%d 镜，%s）" % (total, len(quotes), a.resolution))

    # 钱包余额提示（不阻断：余额是账号侧状态，可能刚充值）
    try:
        w = client.wallet() or {}
        bal = ((w.get("data") or {}).get("amount"))
        if isinstance(bal, (int, float)):
            print("钱包余额：¥%.2f%s" % (bal, "" if bal >= total else
                                       "  ⚠ 不足以覆盖本次全部镜头，建议先 --limit 跑小样或先充值"))
    except Exception:                                              # noqa: BLE001
        pass

    ok_gate, why = ZB.guard(yes=a.yes, max_cost=a.max_cost,
                            amounts_single=[u["estimate"].get("amount") for u in quotes])
    if not ok_gate:
        print("[闸门] %s" % why)
        print("       参考命令：python %s --workspace \"%s\" --ep %s --yes --max-cost %.2f"
              % (pathlib.Path(__file__).name, ws, a.ep,
                 round(max(0.05, (total / max(1, len(quotes))) * 1.5), 3)))
        return 4

    out_dir.mkdir(parents=True, exist_ok=True)
    batch = {"episode": a.ep, "model": a.model, "resolution": a.resolution,
             "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "shots": {}}
    ok = fail = 0
    lock = threading.Lock()

    # 参考图先统一上传（进程内缓存，串行只为避免并发写同一个 cache 键；
    # 179 镜里同一张角色卡要复用上百次，实际只在每个项目开头慢一次）。
    for u in quotes:
        try:
            u["payload"]["images"] = up.urls(u["refs"])
        except ZZAIError as exc:
            u["upload_error"] = str(exc)

    def _one(idx_u):
        nonlocal ok, fail
        i, u = idx_u
        sid = u["sid"]
        amt = u["estimate"].get("amount")
        if isinstance(amt, (int, float)) and float(amt) > float(a.max_cost):
            print("[%d/%d] %s 预估 ¥%.4f 超过 --max-cost ¥%.2f，跳过"
                  % (i, len(quotes), sid, amt, a.max_cost))
            with lock:
                batch["shots"][sid] = {"status": "blocked", "reason": "over max-cost"}
                fail += 1
            return
        if u.get("upload_error"):
            print("[%d/%d] %s 参考图上传失败：%s" % (i, len(quotes), sid, u["upload_error"]))
            with lock:
                batch["shots"][sid] = {"status": "failed", "reason": u["upload_error"]}
                fail += 1
            return
        u["dst"].parent.mkdir(parents=True, exist_ok=True)
        print("[%d/%d] %s → 提交（%ds / %s / 参考图 %d）" % (
            i, len(quotes), sid, u["duration"], a.resolution, len(u["refs"])))
        good, msg = ZB.run_one(ws, client, kind="video", model=a.model,
                               payload=u["payload"], estimate=u["estimate"],
                               max_cost=a.max_cost, purpose="video.shot", dest=u["dst"],
                               ep=a.ep, shot_id=sid, poll_seconds=a.poll_seconds,
                               timeout_s=float(a.timeout_min) * 60,
                               quiet=(a.concurrency > 1))
        with lock:
            batch["shots"][sid] = {"status": "succeeded" if good else "failed",
                                   "artifact": str(u["dst"]) if good else "",
                                   "reason": "" if good else msg,
                                   "estimate": u["estimate"].get("amount")}
            if good:
                ok += 1
                print("        → %s" % u["dst"].relative_to(ws))
            else:
                fail += 1
                print("        [FAIL] %-10s %s" % (sid, msg))

    pairs = list(enumerate(quotes, 1))
    if a.concurrency and a.concurrency > 1:
        print("（并发 %d 条在飞）" % a.concurrency)
        with concurrent.futures.ThreadPoolExecutor(max_workers=int(a.concurrency)) as ex:
            list(ex.map(_one, pairs))
    else:
        for pair in pairs:
            _one(pair)

    batch["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    batch["ok"], batch["fail"] = ok, fail
    (out_dir / "_batch_zzai.json").write_text(
        json.dumps(batch, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\n完成：成功 %d / 失败 %d（共 %d 镜）｜批次 %s"
          % (ok, fail, len(quotes), out_dir / "_batch_zzai.json"))
    if a.json:
        print(json.dumps({"ok": ok, "fail": fail}, ensure_ascii=False))
    return 0 if fail == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
