# -*- coding: utf-8 -*-
"""canvas.py —— 剧集画布的数据聚合（只读）

它回答一个问题
--------------
「30 集做到哪了？」—— 现在要知道这个答案得翻四个目录：
`06-提示词/<ep>/shots.json`（有几镜）、`04-资产/boards/<ep>/`（有没有分镜图）、
`07-成片/<批次>/<shot>/final.mp4`（有没有出片）、`09-发行/剧集/`（发没发）。
翻完还要自己在脑子里对齐。这张格子表把四件事压进一屏：**横向是镜号，纵向是集号**。

口径纪律（与 studio.py 保持一致，不另立一套）
--------------------------------------------
1. **格子状态只认磁盘**，不认「任务跑过没」：
     done   = `<out>/*/<shot>/final.mp4` 存在且 > 2KB
     board  = `<assets>/boards/<ep>/<shot>.png` 存在
     todo   = 两者都没有
   为什么不用 `summary.json` 的 `video_status`：那是**某一次运行**的记录，
   而画布要表达的是「现在磁盘上有没有这段画面」。续跑、换批次、人工换过文件之后，
   台账会过期，磁盘不会。
2. **`shots.json` 是镜数与镜序的唯一来源**（制作包导入时写成契约）。没有它时退化为
   「按分镜图/段目录的名字去重列举」，并在行上标 `no_pack`，让人知道这一集的顺序
   不是契约给的 —— 不假装有。
3. **缺口用「没有」表达，不用 0 假装**：拿不到的时长返回 `None`，前端显示 `—`。

性能
----
一屏最多 99 集 × 60 镜。逐镜 glob 会是几千次系统调用，所以段索引**只走一遍**
`<out>`（深度 3），分镜图每个集目录 `scandir` 一次。30 集的项目整页 < 60ms。
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from . import studio

_TTL = 5
_CACHE: dict = {}

_EP_RE = re.compile(r"^(?:ep|Ep|EP)?[_-]?(\d{1,3})$")
_SHOT_EP_RE = re.compile(r"^(?:ep0*(\d+)[_-])", re.I)
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")

# 出片目录里不是「批次」的子目录（与 studio._NOT_BATCH 同源；这里额外排除母版/字幕层）
_SKIP = {"subs", "logs", "_gen", "_preview", "images", "video", "cache", "tmp",
         "assets", "ledger", "state", "refs_h3"}

MAX_EP = 99          # 剧集画布的纵向上限：超过 99 集该分季，不是一个画布能表达的
MAX_SHOT = 60        # 单集镜数上限（60s 档 5–10 镜，留足余量）


def clear_cache() -> None:
    _CACHE.clear()


def _cached(key, fn):
    now = time.time()
    hit = _CACHE.get(key)
    if hit and (now - hit[0]) < _TTL:
        return hit[1]
    val = fn()
    _CACHE[key] = (now, val)
    return val


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def _read_json(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def _ep_key(name) -> str:
    """目录名 → `epNN`。`EP1` / `ep_01` / `01` / `ep01` 都认；认不出返回空串。"""
    m = _EP_RE.fullmatch(str(name or "").strip())
    if not m:
        return ""
    try:
        n = int(m.group(1))
    except ValueError:
        return ""
    return ("ep%02d" % n) if 0 < n <= MAX_EP else ""


def _ep_num(ep: str) -> int:
    m = re.search(r"(\d+)", ep or "")
    return int(m.group(1)) if m else 0


def _rel(ws, p) -> str:
    try:
        return str(Path(p).resolve().relative_to(Path(ws).resolve())).replace("\\", "/")
    except Exception:                                    # noqa: BLE001
        return ""


def _safe_name(s: str) -> bool:
    return bool(s) and "/" not in s and "\\" not in s and ".." not in s


# ---------------------------------------------------------------------------
# 段索引：<out>/<批次>/<shot>/final.mp4（旧工程多一层 <out>/<引擎>/<批次>/<shot>/）
# ---------------------------------------------------------------------------
def _walk_segments(out: Path) -> dict:
    """段索引：`<shot 目录名> → (final.mp4, mtime)`，同名取最新。

    两种历史落点都要认：`<批次>/<shot>/final.mp4` 与 `<批次>/<shot>/video/final.mp4`
    （与 `studio._shot_videos` 同口径；只认前一种会把「引擎换了目录层级」的段全判成没出片）。
    """
    idx: dict = {}

    def scan(d: Path, depth: int) -> None:
        try:
            entries = list(os.scandir(d))
        except OSError:
            return
        for e in entries:
            try:
                if not e.is_dir():
                    continue
            except OSError:
                continue
            if e.name.lower() in _SKIP or e.name.startswith(("_", ".")):
                continue
            hit = None
            for cand in (Path(e.path) / "final.mp4", Path(e.path) / "video" / "final.mp4"):
                try:
                    if cand.is_file() and cand.stat().st_size > 2048:
                        hit = cand
                        break
                except OSError:
                    continue
            if hit is not None:
                try:
                    mt = hit.stat().st_mtime
                except OSError:
                    continue
                cur = idx.get(e.name)
                if cur is None or mt > cur[1]:
                    idx[e.name] = (hit, mt)
                continue        # 这一支到底了，别再往下钻
            if depth > 0:
                scan(Path(e.path), depth - 1)

    if out.is_dir():
        scan(out, 2)
    return idx


def _seg_of(idx: dict, ep: str, shot_id: str):
    """一个镜头 → 段文件。承认三种目录名：`shot_001` / `ep01_shot_001` / `shot_ep01_001`。"""
    for key in (shot_id, "%s_%s" % (ep, shot_id), shot_id.replace("shot_", "shot_%s_" % ep, 1)):
        hit = idx.get(key)
        if hit:
            return hit[0]
    return None


def _board_files(d: Path, ws) -> dict:
    """分镜图目录 → {shot_id: 相对路径}。名字按 `<shot_id>.<ext>`；多余的变体忽略。"""
    out = {}
    try:
        entries = list(os.scandir(d))
    except OSError:
        return out
    for e in entries:
        try:
            if not e.is_file():
                continue
        except OSError:
            continue
        p = Path(e.path)
        if p.suffix.lower() not in IMG_EXT:
            continue
        key = p.stem
        if key in out:      # 同名不同扩展：取先出现的那个，不猜哪个「更好」
            continue
        out[key] = _rel(ws, p)
    return out


def _pack_dir(data: Path, ep: str):
    """一集的数据目录（含 shots.json）。

    新布局 `data/<ep>/`；旧单集布局直接用 `data/` 根；目录名大小写/下划线不一
    （`EP01` / `ep_01`）时按 `_ep_key` 归一后再认 —— 只按 `data/ep` 拼路径会在
    「引擎写 EP01、界面上是 ep01」的项目里静默返回空。
    """
    d = data / ep
    if (d / "shots.json").is_file():
        return d
    if data.is_dir():
        try:
            for sub in data.iterdir():
                if sub.is_dir() and (sub / "shots.json").is_file() and _ep_key(sub.name) == ep:
                    return sub
        except OSError:
            pass
    if (data / "shots.json").is_file() and ep in ("ep01", ""):
        return data
    return None


def _shots_of(d: Path) -> list:
    """`shots.json` → [{shot_id, board_ref, cast_len, ...}]（保持文件顺序 = 叙事顺序）。"""
    raw = _read_json(d / "shots.json")
    if isinstance(raw, dict):
        raw = raw.get("shots") or []
    if not isinstance(raw, list):
        return []
    rows = []
    for i, s in enumerate(raw):
        if not isinstance(s, dict) or not s.get("shot_id"):
            continue
        rows.append({
            "shot_id": str(s.get("shot_id")),
            "n": i + 1,
            "board_ref": str(s.get("board_ref") or ""),
            "cast": list(s.get("cast") or []),
            "ratio": s.get("ratio") or "",
        })
    return rows[:MAX_SHOT]


def _prompts_of(d: Path) -> dict:
    """`h3_prompts.json` → {shot_id: {dur, chars}}。只为格子的悬浮提示与时长条服务。"""
    raw = _read_json(d / "h3_prompts.json")
    if not isinstance(raw, dict):
        return {}
    out = {}
    for sid, v in raw.items():
        if not isinstance(v, dict):
            continue
        out[str(sid)] = {
            "dur": v.get("duration"),
            "chars": len(str(v.get("prompt") or "")),
        }
    return out


# ---------------------------------------------------------------------------
# 主聚合
# ---------------------------------------------------------------------------
def series(ws: str) -> dict:
    """剧集画布：{rows:[{ep, shots:[{state,...}], counts}], axis, totals}。"""
    return _cached("series:%s" % ws, lambda: _build(str(ws)))


def _build(ws: str) -> dict:
    ws_p = Path(ws)
    data = studio.data_dir(ws)
    out = studio.out_dir(ws)
    assets = studio.assets_dir(ws)

    boards_root = assets / "boards"
    if not boards_root.is_dir():
        alt = ws_p / "04-资产" / "boards"
        if alt.is_dir():
            boards_root = alt

    segs = _walk_segments(out)

    # ---- 三种「这一集存在」的证据，取并集 ----
    packs: dict = {}            # ep → 数据目录（有 shots.json）
    boards: dict = {}           # ep → {shot_id: rel}
    if data.is_dir():
        try:
            for d in sorted(data.iterdir()):
                if d.is_dir() and (d / "shots.json").is_file():
                    ep = _ep_key(d.name)
                    if ep:
                        packs[ep] = d
        except OSError:
            pass
    if boards_root.is_dir():
        try:
            for d in sorted(boards_root.iterdir()):
                if d.is_dir():
                    ep = _ep_key(d.name)
                    if ep:
                        boards[ep] = _board_files(d, ws)
        except OSError:
            pass

    # ---- 发布版（`09-发行/剧集/EpisodeNN.mp4`）----
    releases: dict = {}
    rel_dir = studio.release_dir(ws)
    if rel_dir.is_dir():
        try:
            for p in rel_dir.glob("Episode*.mp4"):
                m = re.search(r"(\d+)", p.stem)
                if m:
                    releases[int(m.group(1))] = p.name
        except OSError:
            pass

    # ---- 集号轴：已有 + 目标集数（缺口也占一行，否则「哪几集没动」看不出来）----
    have = set(packs) | set(boards)
    try:
        expected = int((studio._ep_meta(ws) or {}).get("total") or 0)      # noqa: SLF001
    except Exception:                                    # noqa: BLE001
        expected = 0
    top = max([_ep_num(e) for e in have] + [min(expected, MAX_EP), 1])
    all_eps = ["ep%02d" % i for i in range(1, top + 1)]

    rows = []
    col_counts = [{"done": 0, "board": 0, "todo": 0} for _ in range(MAX_SHOT)]
    for ep in all_eps:
        d = packs.get(ep)
        shots = _shots_of(d) if d else []
        h3 = _prompts_of(d) if d else {}
        no_pack = not shots

        if no_pack:
            # 退化：按分镜图与段目录的名字列举，顺序按镜号排序（不是契约给的顺序）
            keys = set(boards.get(ep) or {})
            for name in segs:
                m = _SHOT_EP_RE.match(name)
                if m and _ep_key(m.group(0).rstrip("_-")) == ep:
                    keys.add(re.sub(r"^ep\d+[_-]", "", name, flags=re.I))
            shots = [{"shot_id": k, "n": i + 1, "board_ref": "", "cast": [], "ratio": ""}
                     for i, k in enumerate(sorted(keys))]
            # 视频可能被命名成 `ep01_shot_001`，按展示名对齐
            for s in shots:
                s["seg_name"] = "%s_%s" % (ep, s["shot_id"])

        cells = []
        counts = {"total": len(shots), "done": 0, "board": 0, "todo": 0}
        for i, s in enumerate(shots):
            sid = s["shot_id"]
            seg = _seg_of(segs, ep, s.get("seg_name") or sid)
            bmap = boards.get(ep) or {}
            bpath = bmap.get(sid) or bmap.get(s.get("board_ref") or "") or ""
            if not bpath and s.get("board_ref"):
                # 分镜图命名有 `<shot_id>.png` 与 `<board_ref>.png` 两种历史用法
                bpath = bmap.get(str(s["board_ref"]).replace("board_%s_" % ep, ""), "")
            state = "done" if seg else ("board" if bpath else "todo")
            counts[state] += 1
            if i < MAX_SHOT:
                col_counts[i][state] += 1
            cells.append({
                "shot_id": sid, "n": i + 1, "state": state,
                "board": bpath, "seg": _rel(ws, seg) if seg else "",
                "ratio": s.get("ratio") or "",
                "cast": len(s.get("cast") or []),
                "board_ref": s.get("board_ref") or "",
                "dur": (h3.get(sid) or {}).get("dur"),
                "chars": (h3.get(sid) or {}).get("chars") or 0,
            })

        durs = []
        for c in cells:
            try:
                if c.get("dur") is not None:
                    durs.append(float(c["dur"]))
            except (TypeError, ValueError):
                pass

        rows.append({
            "ep": ep,
            "num": _ep_num(ep),
            "has_pack": bool(d),
            "no_pack": no_pack,
            "shots": cells,
            "counts": counts,
            "duration": round(sum(durs), 1) if durs else None,
            "progress": round(counts["done"] / counts["total"], 3) if counts["total"] else 0.0,
            "release": releases.get(_ep_num(ep), ""),
            "subs": (out / "subs" / ep).is_dir(),
        })

    axis = max([len(r["shots"]) for r in rows] + [0])
    totals = {
        "episodes": len([r for r in rows if r["counts"]["total"]]),
        "rows": len(rows),
        "with_pack": len([r for r in rows if r["has_pack"]]),
        "shots": sum(r["counts"]["total"] for r in rows),
        "done": sum(r["counts"]["done"] for r in rows),
        "board": sum(r["counts"]["board"] for r in rows),
        "todo": sum(r["counts"]["todo"] for r in rows),
        "released": len(releases),
        "expected_ep": expected,
    }
    totals["percent"] = round(totals["done"] / totals["shots"], 3) if totals["shots"] else 0.0

    return {
        "ok": True,
        "ws": str(ws_p),
        "axis": axis,
        "rows": rows,
        "col_counts": col_counts[:axis],
        "totals": totals,
        "sources": {
            "data": str(data), "out": str(out), "boards": str(boards_root),
        },
        "updated_at": time.time(),
    }


# ---------------------------------------------------------------------------
# 单镜详情（点开一格用）
# ---------------------------------------------------------------------------
def _resolve_ref(ws, data: Path, assets: Path, rel: str) -> str:
    """参考图引用 → 工作区相对路径（三种历史基准：工作区 / data / 资产目录）。"""
    s = str(rel or "").strip()
    if not s:
        return ""
    if s.startswith(("http://", "https://", "data:")):
        return ""
    p = Path(s)
    cands = [p] if p.is_absolute() else [Path(ws) / s, data / s, assets / s]
    for c in cands:
        try:
            if c.is_file():
                return _rel(ws, c)
        except OSError:
            continue
    return ""


def shot(ws: str, ep: str, shot_id: str) -> dict:
    """一镜的四段链：参考图 → 提示词 → 生成参数 → 产物。只读。"""
    if not (_safe_name(ep) and _safe_name(shot_id)):
        return {"ok": False, "reason": "bad_arg", "detail": "集号或镜号不合法"}
    ep = _ep_key(ep) or ep
    ws_p = Path(ws)
    data = studio.data_dir(ws)
    out = studio.out_dir(ws)
    assets = studio.assets_dir(ws)
    d = _pack_dir(data, ep)
    if d is None:
        return {"ok": False, "reason": "no_pack",
                "detail": "这一集还没有制作包（%s/%s/shots.json 缺失）" % (data, ep)}

    shots = _shots_of(d)
    row = next((s for s in shots if s["shot_id"] == shot_id), None)
    boards = _read_json(d / "boards.json") or {}
    prompts = _read_json(d / "h3_prompts.json") or {}
    chars = _read_json(d / "characters.json") or {}
    scenes = _read_json(d / "scenes.json") or {}
    bprompt = boards.get(shot_id) if isinstance(boards, dict) else None
    h3 = prompts.get(shot_id) if isinstance(prompts, dict) else None

    # 分镜图：`<shot_id>.png` 优先，其次 `<board_ref>.png`（历史两种都出现过）
    bpath = ""
    bdir = assets / "boards" / ep
    if not bdir.is_dir():
        bdir = ws_p / "04-资产" / "boards" / ep
    for stem in (shot_id, str((row or {}).get("board_ref") or "").replace("board_%s_" % ep, "")):
        if not stem:
            continue
        for ext in IMG_EXT:
            p = bdir / (stem + ext)
            if p.is_file():
                bpath = _rel(ws, p)
                break
        if bpath:
            break

    segs = _walk_segments(out)
    seg = _seg_of(segs, ep, shot_id)

    cast = []
    for key in ((row or {}).get("cast") or []):
        ref = chars.get(key) or scenes.get(key) or ""
        cast.append({"key": key, "rel": _resolve_ref(ws, d, assets, ref) if ref else ""})

    return {
        "ok": True,
        "ep": ep, "shot_id": shot_id,
        "n": (row or {}).get("n") or 0,
        "ratio": (row or {}).get("ratio") or "",
        "board_ref": (row or {}).get("board_ref") or "",
        "board": {"rel": bpath, "prompt": (bprompt or {}).get("prompt") or ""},
        "prompt": {
            "text": (h3 or {}).get("prompt") or "",
            "duration": (h3 or {}).get("duration"),
            "ratio": (h3 or {}).get("ratio") or "",
        },
        "video": {
            "rel": _rel(ws, seg) if seg else "",
            "bytes": int(seg.stat().st_size) if seg else 0,
        },
        "cast": cast,
        "files": str(d).replace("\\", "/"),
    }
