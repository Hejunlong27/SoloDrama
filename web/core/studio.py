# -*- coding: utf-8 -*-
"""studio.py —— Studio 的只读聚合层（Episodes / Shots / Cost / Overview）

为什么单独一层
--------------
`reader.py` 是「旧控制台」的聚合（17 环节自造判据），Studio 必须改用引擎真源：

  流程   → `workflow.py status --json`（S1–S11，带 probes）
  集/镜  → `<out>/<批次>/summary.json` 的 `shots[]`（引擎自己写的逐镜结果）
  后期   → `<out>/subs/<ep>/` 的真实产物名（master / master_WxH / mix / subbed）
  发行   → `09-发行/剧集/EpisodeNN.mp4`
  成本   → `ledger/runs/*.json` 的 `attempts[].usage`（只认平台用量）

口径纪律（与项目一致，不放宽）
------------------------------
1. 批次目录只认 `YYYYmmdd_HHMMSS` 形状，避免把 `chain_epNN` 这类派生目录当批次；
2. **同一镜头多批次出现时按优先级去重**：成功 > 有状态 > 无状态，同级取最新批次，
   否则返工批次会把旧的成功覆盖成「未跑」；
3. 金额只累加 `usage.consumeCoins / usage.consumeMoney`，失败不计费；
4. 拿不到就是 `None`，不用 0 假装有数据（UI 会显示「未接入」）。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from . import adapters, artifacts, inventory, paths, runner

BATCH_RE = re.compile(r"^\d{8}_\d{6}$")
_EP_RE = re.compile(r"^(ep\d+)$", re.I)
_CACHE: dict = {}
_TTL = 6


def _cached(key, ttl, fn):
    now = time.time()
    hit = _CACHE.get(key)
    if hit and (now - hit[0]) < ttl:
        return hit[1]
    val = fn()
    _CACHE[key] = (now, val)
    return val


def clear_cache() -> None:
    _CACHE.clear()
    adapters.clear_cache()
    inventory._CACHE.clear()          # 同包内部缓存，切项目后必须失效


def _layout():
    return paths.ensure_layout_importable()


def out_dir(ws) -> Path:
    L = _layout()
    if L is None:
        return Path(ws) / "video-pipeline" / "output"
    try:
        return Path(L.out_dir(str(ws)))
    except Exception:  # noqa: BLE001
        return Path(ws) / "video-pipeline" / "output"


def data_dir(ws) -> Path:
    L = _layout()
    if L is None:
        return Path(ws) / "video-pipeline" / "data"
    try:
        return Path(L.data_dir(str(ws)))
    except Exception:  # noqa: BLE001
        return Path(ws) / "video-pipeline" / "data"


def assets_dir(ws) -> Path:
    """资产目录（布局真源 `_layout.stage_dir(ws, "assets")`）。"""
    L = _layout()
    if L is not None:
        try:
            return Path(L.stage_dir(str(ws), "assets"))
        except Exception:  # noqa: BLE001
            pass
    return Path(ws) / "04-资产"


def asset_mds(ws) -> dict:
    """找候选「资产提示词 md」——引擎据此生成资产清单（环境变量 SOLODRAMA_ASSET_MD）。

    为什么要在网页里找它：`gen_assets_local.py` **没有命令行参数**，只认这个环境变量；
    用户不知道要设它会得到「[FAIL] 未设置 SOLODRAMA_ASSET_MD」，于是以为「网页不能出图」。
    """
    base = assets_dir(ws)
    cands = []
    for d in (base, base / "design"):
        if not d.is_dir():
            continue
        try:
            for p in d.glob("*.md"):
                if p.name.lower().startswith("readme"):
                    continue
                try:
                    st = p.stat()
                except OSError:
                    continue
                score = 0
                if "资产提示词" in p.name:
                    score += 3
                elif "提示词" in p.name:
                    score += 2
                elif "asset" in p.name.lower():
                    score += 1
                cands.append({
                    "path": str(p), "name": p.name, "bytes": int(st.st_size),
                    "mtime": int(st.st_mtime), "score": score,
                    "rel": str(p.relative_to(Path(ws))).replace("\\", "/"),
                })
        except OSError:
            continue
    cands.sort(key=lambda c: (-c["score"], -c["mtime"]))
    best = cands[0] if cands and cands[0]["score"] > 0 else (cands[0] if cands else None)
    return {
        "ok": True,
        "assets_dir": str(base),
        "items": cands[:20],
        "suggested": (best or {}).get("path") or "",
        "note": ("引擎只认环境变量 SOLODRAMA_ASSET_MD；选中后会随命令注入，不需要手动设环境变量"
                 if cands else
                 "没有找到资产提示词 md。先在 04-资产/ 放一份（或从资产卡 md 生成），否则出图会报「未设置 SOLODRAMA_ASSET_MD」"),
    }


def engine_root(ws) -> Path:
    L = _layout()
    if L is None:
        return Path(ws) / "video-pipeline"
    try:
        return Path(L.engine_root(str(ws)))
    except Exception:  # noqa: BLE001
        return Path(ws) / "video-pipeline"


def release_dir(ws) -> Path:
    L = _layout()
    if L is None:
        return Path(ws) / "09-发行" / "剧集"
    try:
        return Path(L.release_episode_dir(str(ws)))
    except Exception:  # noqa: BLE001
        return Path(ws) / "09-发行" / "剧集"


def _read_json(p: Path):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _rel(ws, p) -> str:
    """绝对路径 → 工作区相对路径（不越界就返回空串）。"""
    try:
        return str(Path(p).resolve().relative_to(Path(ws).resolve())).replace("\\", "/")
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------------------
# 批次与镜头
# ---------------------------------------------------------------------------
def batches(ws) -> list:
    """所有出片批次（新→旧）。字段直接取自 summary.json，不重算。"""
    out = out_dir(ws)
    rows = []
    if not out.is_dir():
        return rows
    try:
        dirs = [d for d in out.iterdir() if d.is_dir() and BATCH_RE.match(d.name)]
    except OSError:
        return rows
    for d in dirs:
        s = _read_json(d / "summary.json")
        if not isinstance(s, dict):
            continue
        try:
            mtime = int((d / "summary.json").stat().st_mtime)
        except OSError:
            mtime = 0
        fuse = s.get("fuse") or {}
        rows.append({
            "batch": d.name,
            "mtime": mtime,
            "totals": s.get("totals") or {},
            "usage": s.get("usage") or {},
            "elapsed": s.get("elapsed_seconds"),
            "dry_run": bool(s.get("dry_run")),
            "resumed": bool(s.get("resumed")),
            "fuse": {"blown": bool(fuse.get("blown")), "reason": fuse.get("reason") or ""},
            "finished_at": s.get("finished_at") or "",
        })
    rows.sort(key=lambda r: r["mtime"], reverse=True)
    return rows


def _priority(status: str) -> int:
    st = (status or "").upper()
    if st in ("SUCCESS", "SUCCEEDED", "OK"):
        return 2
    return 1 if st else 0


def shots(ws) -> dict:
    """逐镜头的最终状态（跨批次去重）。返回 {items, batches, totals, updated_at}。"""
    def go():
        bl = batches(ws)
        merged = {}
        for b in reversed(bl):                     # 旧 → 新
            s = _read_json(out_dir(ws) / b["batch"] / "summary.json") or {}
            for sh in s.get("shots") or []:
                sid = sh.get("shot_id") or ""
                if not sid:
                    continue
                cand = {
                    "shot_id": sid,
                    "status": (sh.get("video_status") or "").upper(),
                    "image_status": sh.get("image_status"),
                    "error": sh.get("error"),
                    "task_id": sh.get("video_task_id") or sh.get("image_task_id"),
                    "final_mp4": sh.get("final_mp4"),
                    "rel": _rel(ws, sh.get("final_mp4")) if sh.get("final_mp4") else "",
                    "batch": b["batch"],
                    "mtime": b["mtime"],
                }
                cur = merged.get(sid)
                if cur is None or _priority(cand["status"]) >= _priority(cur["status"]):
                    merged[sid] = cand
        eps = {}
        for it in merged.values():
            ep = it["shot_id"].split("_")[0]
            e = eps.setdefault(ep, {"ep": ep, "total": 0, "ok": 0, "fail": 0, "pending": 0})
            e["total"] += 1
            p = _priority(it["status"])
            if p == 2:
                e["ok"] += 1
            elif it["status"]:
                e["fail"] += 1
            else:
                e["pending"] += 1
        newest = bl[0] if bl else None
        return {
            "ok": True,
            "items": sorted(merged.values(), key=lambda x: x["shot_id"]),
            "batches": bl,
            "episodes": [eps[k] for k in sorted(eps)],
            "totals": (newest or {}).get("totals") or {},
            "latest_batch": (newest or {}).get("batch"),
            "updated_at": (newest or {}).get("mtime") or 0,
        }
    return _cached("shots:%s" % ws, _TTL, go)


# ---------------------------------------------------------------------------
# 集级聚合（母版 / 放大 / 字幕 / 发布版）
# ---------------------------------------------------------------------------
_SUFFIX = [("master", "_master.mp4"), ("upscaled", "_master_1080x1920.mp4"),
           ("mix", "_mix.mp4"), ("subbed", "_subbed.mp4"), ("ass", ".ass")]


def _ep_artifacts(ws, ep: str) -> dict:
    d = out_dir(ws) / "subs" / ep
    out = {}
    for key, suffix in _SUFFIX:
        p = d / ("%s%s" % (ep, suffix))
        out[key] = _rel(ws, p) if p.is_file() else ""
    # 放大产物可能不是 1080x1920（换过目标分辨率），按前缀兜底
    if not out["upscaled"] and d.is_dir():
        for p in sorted(d.glob("%s_master_*x*.mp4" % ep)):
            out["upscaled"] = _rel(ws, p)
            break
    return out


def _release_index(ep: str):
    m = re.match(r"^ep(\d+)$", ep, re.I)
    return int(m.group(1)) if m else None


def episodes(ws) -> list:
    """按集汇总：镜头进度 + 四类产物 + 发布版。"""
    sh = shots(ws)
    rel_dir = release_dir(ws)
    rel_map = {}
    if rel_dir.is_dir():
        for p in rel_dir.glob("Episode*.mp4"):
            m = re.search(r"(\d+)", p.stem)
            if m:
                rel_map[int(m.group(1))] = p.name
    out = []
    for e in sh.get("episodes") or []:
        ep = e["ep"]
        art = _ep_artifacts(ws, ep)
        idx = _release_index(ep)
        out.append({
            "ep": ep,
            "total": e["total"], "ok": e["ok"], "fail": e["fail"], "pending": e["pending"],
            "state": ("done" if e["ok"] == e["total"] and e["total"] else
                      ("fail" if e["fail"] else ("doing" if e["ok"] else "todo"))),
            "master": art["master"], "upscaled": art["upscaled"],
            "mix": art["mix"], "subbed": art["subbed"], "ass": art["ass"],
            "release": rel_map.get(idx, "") if idx is not None else "",
        })
    return out


# ---------------------------------------------------------------------------
# 成本（只认平台 usage）
# ---------------------------------------------------------------------------
def _attempts(ws):
    """台账里的全部尝试（含失败，失败由调用方过滤金额）。"""
    lr = engine_root(ws) / "ledger" / "runs"
    if not lr.is_dir():
        return []
    rows = []
    for f in sorted(lr.glob("*.json")):
        d = _read_json(f)
        if not isinstance(d, dict):
            continue
        for a in d.get("attempts") or []:
            u = a.get("usage") or {}
            try:
                coins = float(u.get("consumeCoins") or 0)
            except (TypeError, ValueError):
                coins = 0.0
            try:
                money = float(u.get("consumeMoney") or 0)
            except (TypeError, ValueError):
                money = 0.0
            rows.append({
                "shot_id": d.get("shot_id"), "episode": d.get("episode") or "",
                "stage": d.get("stage") or "", "status": (a.get("status") or "").upper(),
                "billed": bool(a.get("billed")),
                "coins": coins, "money": money,
                "task_id": str(a.get("task_id") or ""),
                "at": a.get("started_at") or d.get("created_at") or "",
                "error_class": a.get("error_class") or "",
                "error": (a.get("error") or "")[:200],
            })
    return rows


def cost(ws) -> dict:
    """成本明细：台账逐条 + 按阶段/按集汇总 + inventory 口径徽标。"""
    inv = inventory.inventory(ws)
    rows = _attempts(ws)
    usd_cny = 7.2
    by_stage, by_ep = {}, {}
    total_coins = total_usd = 0.0
    for r in rows:
        if r["status"] not in ("SUCCESS", "SUCCEEDED", "OK"):
            continue
        total_coins += r["coins"]
        total_usd += r["money"]
        st = r["stage"] or "其他"
        by_stage[st] = by_stage.get(st, 0.0) + r["coins"]
        if r["episode"]:
            by_ep[r["episode"]] = by_ep.get(r["episode"], 0.0) + r["coins"]
    coin_to_cny = 0.0025
    # ★ 口径：台账（ledger attempts）是本模块的**主源**；inventory 只作资产云端用量补充。
    #   旧 inventory 读的是 ledger 顶层的 usage，而真实 ledger 把用量放在 attempts[] 里，
    #   因此它会低估成 0 —— 这里不能拿它当总额，否则会出现「花了钱显示 ¥0」。
    if total_coins or total_usd:
        source, source_text = "ledger", "来自平台用量台账（逐次尝试）"
    elif inv["spend"]["workflow_hits"]:
        source, source_text = "workflow", "金额来自云端生成记录，系统账单明细尚未收录"
    else:
        source, source_text = "none", ""
    return {
        "ok": True,
        "source": source,
        "source_text": source_text,
        "ledger": {
            "coins": round(total_coins, 2),
            "usd": round(total_usd, 4),
            "cny": round(total_coins * coin_to_cny + total_usd * usd_cny, 4),
            "attempts": len(rows),
        },
        "assets_usage": {"coins": inv["spend"]["coins"], "tasks": inv["spend"]["tasks"],
                         "workflow_hits": inv["spend"]["workflow_hits"],
                         "note": "资产云端出图的独立记录，可能尚未进台账"},
        "by_stage": [{"stage": k, "coins": round(v, 2)} for k, v in
                     sorted(by_stage.items(), key=lambda kv: kv[1], reverse=True)],
        "by_episode": [{"ep": k, "coins": round(v, 2)} for k, v in sorted(by_ep.items())],
        "rows": sorted(rows, key=lambda r: r["at"], reverse=True)[:200],
        "rate": {"coin_to_cny": coin_to_cny, "usd_to_cny": usd_cny},
        "updated_at": time.time(),
    }


# ---------------------------------------------------------------------------
# 一屏聚合
# ---------------------------------------------------------------------------
def overview(ws) -> dict:
    """Studio 首屏：项目元信息 + 流程 + 九项 + 双门禁 + 计数 + 花费。"""
    def go():
        wf = adapters.norm_workflow(adapters.workflow_status(ws))
        setup = adapters.norm_setup(adapters.setup_show(ws))
        st = adapters.drama_status(ws)
        sty = adapters.style_status(ws)
        mod = adapters.models_status(ws)
        sh = shots(ws)
        eps = episodes(ws)
        inv = inventory.inventory(ws)

        style = {}
        raw = (sty.get("data") or {}).get("plan") if isinstance(sty.get("data"), dict) else None
        raw = raw if isinstance(raw, dict) else (sty.get("data") or {})
        s = raw.get("style") if isinstance(raw.get("style"), dict) else None
        if s:
            style = {"confirmed": bool(s.get("confirmed")), "choice": s.get("choice"),
                     "label": s.get("label") or s.get("choice") or ""}

        models = {}
        mraw = (mod.get("data") or {}).get("plan") if isinstance(mod.get("data"), dict) else None
        mraw = mraw if isinstance(mraw, dict) else (mod.get("data") or {})
        mm = mraw.get("models") or {}
        for k in ("image", "video"):
            d = mm.get(k) or {}
            models[k] = {"confirmed": bool(d.get("confirmed")), "choice": d.get("choice"),
                         "label": d.get("label"), "evidence_ok": d.get("evidence_ok"),
                         "missing": d.get("missing_evidence") or []}

        d = st.get("data") or {}
        counts = {
            "shots": (d.get("data") or {}).get("shots"),
            "prompts": (d.get("data") or {}).get("prompts"),
            "images": inv["images"],
            "clips": inv["clips"],
            "renders": inv["renders"],
            "refs": inv["refs"],
        }
        h3 = d.get("h3") or {}
        assets = d.get("assets") or {}
        refs_over = [r for r in (d.get("refs") or []) if r.get("h3_over_limit")]
        return {
            "ok": True,
            "workflow": wf,
            "setup": setup,
            "style": style,
            "models": models,
            "h3": h3,
            "assets": {
                "missing_characters": assets.get("missing_characters") or [],
                "missing_scenes": assets.get("missing_scenes") or [],
                "char_generated": len(assets.get("char_generated") or []),
                "scene_generated": len(assets.get("scene_generated") or []),
                "local_generated": assets.get("local_generated") or 0,
            },
            "refs_over": [{"key": r.get("key"), "size": r.get("size")} for r in refs_over],
            "counts": counts,
            "episodes": eps,
            "batches": sh["batches"][:5],
            "latest_batch": sh["latest_batch"],
            "spend": {"cny": inv["spend"]["coins"] * 0.0025 + inv["spend"]["usd"] * 7.2,
                      "coins": inv["spend"]["coins"], "usd": inv["spend"]["usd"],
                      "source": inv["spend"]["source"],
                      "source_text": inv["spend"]["source_text"]},
            "status_exit": st.get("exit"),
            "adapters": {"workflow": wf.get("reason") or "ok",
                         "setup": "ok" if setup.get("ok") else setup.get("reason"),
                         "status": "ok" if st.get("ok") else st.get("reason")},
            "updated_at": time.time(),
        }
    return _cached("overview:%s" % ws, _TTL, go)


def prompt_of(ws, shot: str) -> dict:
    """单镜提示词（读 06-提示词/h3_prompts.json，只取这一条）。

    不把整个文件下发给浏览器：240 镜的提示词有几百 KB，且没必要暴露全部。
    """
    if not shot or "/" in shot or "\\" in shot or ".." in shot:
        return {"ok": False, "reason": "bad_shot", "shot": shot}
    d = _read_json(data_dir(ws) / "h3_prompts.json")
    if not isinstance(d, dict):
        return {"ok": False, "reason": "no_prompts", "shot": shot}
    v = d.get(shot)
    if not isinstance(v, dict):
        return {"ok": False, "reason": "not_found", "shot": shot}
    return {"ok": True, "shot": shot, "duration": v.get("duration"),
            "ratio": v.get("ratio"), "voice": v.get("voice"),
            "prompt": v.get("prompt") or ""}


def media_info(ws, rel: str) -> dict:
    """给前端一个「这个文件能不能播」的判定，避免 404 反复试探。"""
    try:
        p = artifacts.safe_rel(ws, rel)
        if not p.is_file():
            return {"ok": False, "reason": "missing"}
        return {"ok": True, "rel": rel, "bytes": p.stat().st_size,
                "kind": artifacts.kind_of(p)}
    except artifacts.PathDenied as exc:
        return {"ok": False, "reason": "denied", "detail": str(exc)}
