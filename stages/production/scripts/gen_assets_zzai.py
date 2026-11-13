#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""gen_assets_zzai.py —— 用真真AI 图片 API 出「角色 / 场景 / 道具」资产卡

它补的是哪条断链
----------------
2026-11 之前资产出图只有两条通道：本地 ComfyUI（`gen_assets_local.py`）与
RunningHub 工作流（`gen_assets_rh_workflow.py`）。`gen_boards.py` 早在就把
`zzai_image_api` 接进分镜图，**资产侧却一直空着** —— 于是「图片模型统一用
zhenzhen-image-g-v2.6-lowprice」这句配置只能在分镜环节兑现，资产还得另开一台 GPU。

本脚本把资产侧补齐，并且**复用** `gen_assets_local.assets_from_pack()` 的出图清单：
文件名主干（`<ID>_<剧名>[_<造型码>]`）、变体层别排序、seed 派生全部照旧，
唯一的差别是「谁来画」。这条复用是刻意的 —— 产物命名是 `pack_import._pick_image`
回填 `refs.json` 的唯一依据，另写一套必错。

产物
----
    04-资产/characters/<prefix>.png
    04-资产/scenes/<prefix>.png
    04-资产/props/<prefix>.png
    .drama/media/mt_*.json              每张一条任务记录（成本/usage/状态）

用法
----
    # 干跑：只列清单与逐张报价，不提交
    python gen_assets_zzai.py --workspace "D:/剧本/海外剧/10" --pack "D:/剧本/海外剧/10/pack"

    # 真出（--yes 与 --max-cost 缺一不可）
    python gen_assets_zzai.py --workspace "..." --pack "..." --yes --max-cost 0.06

    # 只补某类 / 某几张
    python ... --kind char --only P01,P02 --yes --max-cost 0.06
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import pathlib
import re
import sys
import threading

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")     # type: ignore[union-attr]
except Exception:                                                  # noqa: BLE001
    pass

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "stages"))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "stages" / "import"))


def _prescan_workspace() -> None:
    """`--workspace` 必须在 import `_ws` / `gen_assets_local` 之前落到环境变量。"""
    for i, arg in enumerate(sys.argv):
        if arg == "--workspace" and i + 1 < len(sys.argv):
            os.environ["SOLODRAMA_WORKSPACE"] = sys.argv[i + 1]
            os.environ["DRAMA_WORKSPACE"] = sys.argv[i + 1]
        elif arg.startswith("--workspace="):
            v = arg.split("=", 1)[1]
            os.environ["SOLODRAMA_WORKSPACE"] = v
            os.environ["DRAMA_WORKSPACE"] = v


_prescan_workspace()

import _layout as L                                                   # noqa: E402
from stages.media_api import zzai_batch as ZB                         # noqa: E402
from stages.media_api.zzai import ZZAIError                           # noqa: E402

SUBDIR = {"char": "characters", "scene": "scenes", "prop": "props"}
KIND_CN = {"char": "人物", "scene": "场景", "prop": "道具"}

# 资产卡默认画幅：人物/场景竖版（与 pack_spec 一致），道具方图。
DEFAULT_ASPECT = {"char": "16:9", "scene": "16:9", "prop": "16:9"}


def _load_items(ws: pathlib.Path, pack_dir: pathlib.Path) -> list:
    """复用 local 通道的出图清单（唯一真源是 `assets_from_pack`）。"""
    import gen_assets_local as GAL                                    # 延迟导入：依赖 WS
    if not pack_dir or not (pack_dir / "pack.json").is_file():
        raise SystemExit("[FAIL] 需要 --pack 指向含 pack.json 的制作包目录")
    return GAL.assets_from_pack(pack_dir)


def _asset_id(item: dict) -> str:
    """`P01@LOOK-A` → `P01`；`S03` → `S03`。"""
    return str(item.get("id") or "").split("@", 1)[0]


def _base_file(items: list, out_root: pathlib.Path, item: dict):
    """非基础造型优先拿本资产的「基础卡 / 三视图」当身份锚（图生图）。

    为什么这么做：只看提示词重画一套衣服，脸会漂；有基础卡当参考，
    同一角色的 LOOK-A/LOOK-B 才是「同一个人换了衣服」。
    """
    aid = _asset_id(item)
    sub = out_root / SUBDIR[item["kind"]]
    for other in items:
        if other is item or _asset_id(other) != aid:
            continue
        if str(other.get("vkind")) in ("base", "turnaround"):
            p = sub / ("%s.png" % other["prefix"])
            if p.is_file():
                return p
    return None


def _prompt_of(item: dict, negative_global: str = "") -> str:
    pos = str(item.get("prompt") or "").strip()
    neg = str(item.get("negative") or "").strip()
    if negative_global and negative_global not in neg:
        neg = (neg + ", " + negative_global).strip(", ")
    # 真真AI 图片接口没有独立负向字段：用一句明确的「不要出现」收口。
    # 不写这句时，资产卡最容易长出文字水印与多余手指（实测最常见的两类废图）。
    if neg:
        return pos + "\n\nDo not include: %s." % neg
    return pos


def main() -> int:
    ap = argparse.ArgumentParser(description="真真AI 资产卡出图（角色/场景/道具）")
    ap.add_argument("--workspace", default=None)
    ap.add_argument("--pack", default=None, help="制作包目录（含 pack.json）")
    ap.add_argument("--kind", default="all", choices=("all", "char", "scene", "prop"))
    ap.add_argument("--only", default="", help="只做这些资产 ID（逗号分隔，如 P01,S03）")
    ap.add_argument("--limit", type=int, default=0, help="只做前 N 张")
    ap.add_argument("--force", action="store_true", help="已存在也重出")
    ap.add_argument("--yes", action="store_true", help="真实提交确认（计费）")
    ap.add_argument("--max-cost", dest="max_cost", type=float, default=None,
                    help="单张 CNY 上限；真实提交必填")
    ap.add_argument("--model", default="zhenzhen-image-g-v2.6-lowprice")
    ap.add_argument("--resolution", default="1k", choices=("1k", "2k", "4k"))
    ap.add_argument("--quality", default="high",
                    choices=("auto", "low", "medium", "high", "xhigh", "max"))
    ap.add_argument("--concurrency", type=int, default=1,
                    help="并发提交数（默认 1 串行；实测 3 不触发限流）")
    ap.add_argument("--poll-seconds", dest="poll_seconds", type=float, default=3.0)
    ap.add_argument("--timeout-min", dest="timeout_min", type=float, default=15.0)
    a = ap.parse_args()

    ws = pathlib.Path(a.workspace).expanduser().resolve() if a.workspace else pathlib.Path(
        os.environ.get("SOLODRAMA_WORKSPACE") or ".").resolve()
    pack = pathlib.Path(a.pack).expanduser().resolve() if a.pack else ws / "pack"
    out_root = L.assets_dir(ws)

    items = _load_items(ws, pack)
    want_kinds = {"char", "scene", "prop"} if a.kind == "all" else {a.kind}
    only = {s.strip().upper() for s in re.split(r"[,，\s]+", a.only) if s.strip()}
    picked = []
    for it in items:
        if it["kind"] not in want_kinds:
            continue
        if only and _asset_id(it).upper() not in only:
            continue
        picked.append(it)
    if a.limit:
        picked = picked[: a.limit]

    # 负向词：包级 + 卡级（assets_from_pack 已合并到 item['negative']）
    try:
        pack_meta = json.loads((pack / "pack.json").read_text(encoding="utf-8-sig"))
    except Exception:                                                 # noqa: BLE001
        pack_meta = {}
    global_neg = str(pack_meta.get("negative") or "").strip()

    print("=" * 74)
    print("真真AI 资产卡出图")
    print("=" * 74)
    print("  工作区 : %s" % ws)
    print("  制作包 : %s" % pack)
    print("  模型   : %s @%s / quality=%s" % (a.model, a.resolution, a.quality))
    print("  清单   : %d 张（清单真源 gen_assets_local.assets_from_pack）" % len(picked))
    if not picked:
        print("\n[WARN] 没有要出的资产卡（--kind / --only 可能写错）")
        return 0

    todo, skip = [], 0
    for it in picked:
        dst = out_root / SUBDIR[it["kind"]] / ("%s.png" % it["prefix"])
        if dst.is_file() and not a.force:
            skip += 1
            continue
        todo.append((it, dst))
    print("  跳过   : %d 张（已存在；--force 可重出）" % skip)
    if not todo:
        print("\n全部已出，无需提交。")
        return 0

    client = ZB.client_from_env()
    up = ZB.Uploader(client)
    quotes, total = [], 0.0
    for it, dst in todo:
        # ★ 参考图在**提交时**才算（见下方循环）：报价阶段基础卡可能还没出，
        #   批量跑时若在这里定死 refs，全部变体会退化成 t2i，同一角色每套造型都像新人。
        payload = {
            "model": a.model,
            "prompt": _prompt_of(it, global_neg),
            "images": [],                      # 上传后回填
            "size": str(it.get("aspect") or DEFAULT_ASPECT[it["kind"]]),
            "resolution": a.resolution,
            "quality": a.quality,
            "output_format": "png",
            "n": 1,
        }
        quotes.append({"item": it, "dest": dst, "payload": payload, "estimate": None})
    # 报价（estimate 是免费的；先报后传图，省上传流量）
    fail_quote = 0
    for q in quotes:
        try:
            q["estimate"] = ZB.quote(client, "image", q["payload"])
        except ZZAIError as exc:
            q["estimate"] = {"estimate_available": False, "error": str(exc)}
            fail_quote += 1
        amt = q["estimate"].get("amount")
        if isinstance(amt, (int, float)):
            total += float(amt)
    print("\n报价：合计 ¥%.4f（%d 张；%d 张报价失败）"
          % (total, len(quotes), fail_quote))

    ok_gate, why = ZB.guard(yes=a.yes, max_cost=a.max_cost,
                            amounts_single=[q["estimate"].get("amount") for q in quotes])
    if not ok_gate:
        print("[闸门] %s" % why)
        print("       参考命令：python %s --workspace \"%s\" --pack \"%s\" --yes --max-cost %.2f"
              % (pathlib.Path(__file__).name, ws, pack, (max_cost_hint(total, len(quotes)))))
        return 4

    # 提交：默认串行（最稳）；--concurrency>1 时并发提交。
    # 为什么给并发：真真AI 单张要 40–90 秒，73 张串行要一个多小时；
    # 实测并发 3 不触发限流，单张耗时不变，总时长降到约 1/3。
    ok = fail = 0
    lock = threading.Lock()

    def _one(idx_q):
        nonlocal ok, fail
        i, q = idx_q
        it, dst = q["item"], q["dest"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        base = _base_file(items, out_root, it)                 # 提交时再看一眼基础卡在不在
        refs = [base] if base is not None else []
        try:
            q["payload"]["images"] = up.urls(refs) if refs else []
        except ZZAIError as exc:
            print("[%d/%d] %s 参考图上传失败：%s" % (i, len(quotes), it["prefix"], exc))
            with lock:
                fail += 1
            return
        print("[%d/%d] %-42s %s" % (i, len(quotes), it["prefix"],
                                    "refs=%d" % len(refs) if refs else "t2i"))
        good, msg = ZB.run_one(ws, client, kind="image", model=a.model,
                               payload=q["payload"], estimate=q["estimate"],
                               max_cost=a.max_cost, purpose="asset.card", dest=dst,
                               poll_seconds=a.poll_seconds,
                               timeout_s=float(a.timeout_min) * 60, quiet=(a.concurrency > 1))
        with lock:
            if good:
                ok += 1
                print("        → %s" % pathlib.Path(msg).name)
            else:
                fail += 1
                print("        [FAIL] %-40s %s" % (it["prefix"], msg))

    pairs = list(enumerate(quotes, 1))
    if a.concurrency and a.concurrency > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=int(a.concurrency)) as ex:
            list(ex.map(_one, pairs))
    else:
        for pair in pairs:
            _one(pair)
    print("\n完成：成功 %d / 失败 %d（共 %d 张）" % (ok, fail, len(quotes)))
    if ok:
        print("下一步：重跑 pack 导入回填 04-资产/refs.json 与 06-提示词/*/characters.json")
    return 0 if fail == 0 else 3


def max_cost_hint(total: float, n: int) -> float:
    """给闸门提示一个够用的 --max-cost（不替用户省钱，只保证不卡在单张上限）。"""
    per = (total / n) if n else 0.0
    return round(max(0.05, per * 1.6), 3)


if __name__ == "__main__":
    raise SystemExit(main())
