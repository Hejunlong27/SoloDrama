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
        text = str(v.get("prompt") or "")
        labels = _parse_order(text)
        out[str(sid)] = {
            "dur": v.get("duration"),
            "chars": len(text),
            # 参考图张数按提示词算（不含分镜图）。旧口径读 shots.json 的 cast，
            # 而旧项目根本没有这个字段 → 格子显示「0 张参考图」，实际挂了 3 张。
            "refs": (len(labels) - 1) if labels else None,
        }
    return out


# ---------------------------------------------------------------------------
# 参考图顺序：**以提示词为真源**（P3，2026-11-04）
# ---------------------------------------------------------------------------
# 为什么不能信 shots.json 的 character_refs + scene_refs：
#   `pack_import` 把它们按「角色在前、场景在后」拆成两个数组，道具还混在
#   character_refs 里。于是 `character_refs=[P02, D11] + scene_refs=[S01]`
#   拼出来是 P02,D11,S01，而提示词写的是 P02,S01,D11 —— **顺序错了**。
#   `ingest_check` 只查「数量够不够、编号连续」，查不出顺序，所以这种错
#   能一路跑到出片：第 4 张图本该是道具，实际喂的是场景。
#
# 唯一的顺序真源是提示词里这一行（制作包写作规范要求每个镜头都有）：
#   上传顺序：Mixed 1＝F02 分镜图｜Mixed 2＝P02 LOOK-A｜Mixed 3＝S01｜Mixed 4＝D11
_ORDER_LINE = re.compile(r"^[^\n]*上传顺序[^\n]*$", re.M)
_ORDER_ITEM = re.compile(r"(?:Mixed|Picture)\s*(\d+)\s*[＝=]\s*([^｜|\n]+)")
# 引用的两种写法都要认（与 ingest_check.PIC 同源，但不 import 它 —— web 层不依赖引擎脚本）
_PIC_REF = re.compile(r"<Picture\s+(\d+)\s*>|\{\{\s*(?:Mixed|Picture)\s*(\d+)\s*\}\}")

DUR_MIN, DUR_MAX = 4, 15        # H3 单段硬限
PIC_MAX = 6                     # H3 图片槽硬限


def _parse_order(prompt: str):
    """从提示词取上传顺序 → ['F02 分镜图', 'P02 LOOK-A', ...]（按编号升序）。

    没有这一行返回 `None`（不是空列表：空列表表示「有行但没图」，
    两者对「能不能改顺序」的结论完全不同）。
    """
    line = _ORDER_LINE.search(str(prompt or ""))
    if not line:
        return None
    items = []
    for m in _ORDER_ITEM.finditer(line.group(0)):
        try:
            n = int(m.group(1))
        except ValueError:
            continue
        items.append((n, m.group(2).strip()))
    if not items:
        return None
    items.sort(key=lambda x: x[0])
    # 编号必须从 1 起连续 —— 断了就不知道第 2 张是哪个，宁可不改
    if [n for n, _ in items] != list(range(1, len(items) + 1)):
        return None
    return [label for _, label in items]


def _reorder_prompt(prompt: str, new_labels: list) -> tuple:
    """按新顺序重写「上传顺序」行与全文的图号引用。

    返回 `(新提示词, 映射, 错误)`。映射是 `{旧编号: 新编号}`，界面用来显示
    「Mixed 2 ↔ Mixed 3 换了」这种可核对的对照。

    ★ 只重写编号数字，不动任何其他文字。顺序变化本质上就是编号的重排：
      第 i 张换成第 j 张，所以所有指向第 i 张的 `{{Mixed i}}` 都要改成 `{{Mixed j}}`。
      理解语义是多余的，而且容易改错描述本身。
    """
    old = _parse_order(prompt)
    if not old:
        return prompt, {}, ("这镜的提示词里没有可用的「上传顺序」行（或编号不连续），"
                            "无法判断第几张是哪个参考图。先按制作包规范补上这一行。")
    if len(new_labels) != len(old):
        return prompt, {}, "新顺序 %d 项，原来 %d 项 —— 数量不一致" % (len(new_labels), len(old))
    if sorted(new_labels) != sorted(old):
        miss = [x for x in old if x not in new_labels]
        extra = [x for x in new_labels if x not in old]
        return prompt, {}, ("新顺序不是原来的重排。缺：%s；多：%s"
                            % ("、".join(miss) or "无", "、".join(extra) or "无"))
    if len(set(old)) != len(old):
        return prompt, {}, "上传顺序里有重复项，无法确定对应关系（%s）" % "、".join(old)

    mapping = {}
    for i, lab in enumerate(old, 1):
        mapping[i] = new_labels.index(lab) + 1
    if all(k == v for k, v in mapping.items()):
        return prompt, mapping, ""          # 没变

    text = str(prompt)

    # ① 重写定义行（它本身不是「引用」，不会被 ② 命中）
    def _relabel(m):
        prefix = m.group(1)
        parts = ["Mixed %d＝%s" % (i + 1, lab) for i, lab in enumerate(new_labels)]
        return prefix + "｜".join(parts)

    # 保留原行的前缀与分隔符风格（全角｜/半角|）
    line_m = _ORDER_LINE.search(text)
    line = line_m.group(0)
    head_m = re.match(r"^([^\n]*?[：:]\s*)", line)
    prefix = head_m.group(1) if head_m else "上传顺序："
    sep = "｜" if "｜" in line else "|"
    rebuilt = prefix + sep.join("Mixed %d＝%s" % (i + 1, lab)
                                for i, lab in enumerate(new_labels))
    text = text[:line_m.start()] + rebuilt + text[line_m.end():]

    # ② 全文替换引用
    def _renum(m):
        if m.group(1) is not None:
            n = int(m.group(1))
            return "<Picture %d>" % mapping.get(n, n)
        n = int(m.group(2))
        return m.group(0).replace(str(n), str(mapping.get(n, n)))

    text = _PIC_REF.sub(_renum, text)
    return text, mapping, ""


def _label_to_key(label: str, chars: dict, scenes: dict) -> str:
    """提示词里的标签 → 资产 key。

    `P02 LOOK-A` → `P02@LOOK-A`（制作包用空格，资产表用 @）。
    三级回退：原样 → 空格换 @ → 取第一个词。都找不到就返回空串，
    界面显示占位而不是猜一个错的。
    """
    s = str(label or "").strip()
    if not s:
        return ""
    s = re.sub(r"\s*分镜图\s*$", "", s).strip()
    for cand in (s, s.replace(" ", "@"), s.split(" ")[0], s.split("　")[0]):
        if cand in chars or cand in scenes:
            return cand
    # 再试「去掉 @ 后缀」的前缀匹配：`P02 LOOK-A` 对 `P02@LOOK-A`
    for k in list(chars) + list(scenes):
        if k.replace("@", " ") == s:
            return k
    return ""


def _cast_from_prompt(prompt: str, chars: dict, scenes: dict) -> list:
    """按提示词的顺序给出参考图列表（**不含**分镜图，界面单独处理它）。"""
    labels = _parse_order(prompt)
    if not labels:
        return []
    out = []
    for lab in labels[1:]:              # 第 1 张是分镜图，固定不动
        out.append({"label": lab, "key": _label_to_key(lab, chars, scenes)})
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
            _refs_n = (h3.get(sid) or {}).get("refs")
            cells.append({
                "shot_id": sid, "n": i + 1, "state": state,
                "board": bpath, "seg": _rel(ws, seg) if seg else "",
                "ratio": s.get("ratio") or "",
                # 张数按提示词算；提示词里没有上传顺序行时才退回 shots.json
                "cast": _refs_n if _refs_n is not None else len(s.get("cast") or []),
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

    ptext = (h3 or {}).get("prompt") or ""
    labels = _parse_order(ptext)

    # ★ 顺序以提示词为准（理由见 _cast_from_prompt）。旧项目没有上传顺序行时，
    #   退回 shots.json 的 cast；再没有就退回两张分表的拼接顺序 —— 并在返回里
    #   标 order_source，让界面能说清「这个顺序不是提示词给的」。
    cast = []
    order_source = ""
    from_prompt = _cast_from_prompt(ptext, chars, scenes)
    if from_prompt:
        order_source = "prompt"
        for it in from_prompt:
            ref = chars.get(it["key"]) or scenes.get(it["key"]) or ""
            cast.append({
                "key": it["key"] or it["label"],
                "label": it["label"],
                "missing": not it["key"],
                "rel": _resolve_ref(ws, d, assets, ref) if ref else "",
            })
    else:
        keys = list((row or {}).get("cast") or [])
        if not keys:
            keys = list((row or {}).get("character_refs") or []) + \
                   list((row or {}).get("scene_refs") or [])
            order_source = "refs" if keys else ""
        else:
            order_source = "cast"
        for key in keys:
            ref = chars.get(key) or scenes.get(key) or ""
            cast.append({"key": key, "label": key, "missing": False,
                         "rel": _resolve_ref(ws, d, assets, ref) if ref else ""})

    return {
        "ok": True,
        "ep": ep, "shot_id": shot_id,
        "n": (row or {}).get("n") or 0,
        "ratio": (row or {}).get("ratio") or "",
        "board_ref": (row or {}).get("board_ref") or "",
        "board": {"rel": bpath, "prompt": (bprompt or {}).get("prompt") or ""},
        "prompt": {
            "text": ptext,
            "duration": (h3 or {}).get("duration"),
            "ratio": (h3 or {}).get("ratio") or "",
        },
        # 上传顺序（含分镜图第一项）；`order_editable` 决定界面上能不能拖
        "order": labels or [],
        "order_source": order_source,
        "order_editable": bool(labels) and len(labels) > 2,
        "video": {
            "rel": _rel(ws, seg) if seg else "",
            "bytes": int(seg.stat().st_size) if seg else 0,
        },
        "cast": cast,
        "files": str(d).replace("\\", "/"),
    }


# ---------------------------------------------------------------------------
# 写回（P3）：改时长 / 改提示词 / 调参考图顺序
# ---------------------------------------------------------------------------
# 三条纪律，都是「画布上点了保存之后，磁盘不该出现半成品」推导出来的：
#   1. **先校验再写**。任何一条不过就整体不写 —— 时长改了但提示词没改，
#      比不改更糟：下次出片用的是一套自相矛盾的参数。
#   2. **写前备份**。`*.bak.<时间戳>`，保留最近 5 份。这不是保险，是回滚的唯一手段：
#      提示词是几十行中文，用户改错了没有 diff 可看。
#   3. **原子替换**。临时文件 + `os.replace`。直接 `write_text` 在断电/崩溃时
#      会留下半个 JSON，而引擎读它的时候只会报「解析失败」，说不出是哪一步。
_BAK_KEEP = 5


def _backup(p: Path) -> str:
    """备份一个文件，只保留最近若干份。返回备份路径（失败返回空串）。

    ★ 时间戳必须带微秒。只到秒的话，同一秒内的两次保存会算出同一个文件名，
      后一次把前一次覆盖掉 —— 而「连点两下保存」恰恰是最需要回滚的时候。
      实测踩过：改 4→5→4 之后，备份里留着的是 5，回滚拿到的不是原始值。
    """
    if not p.is_file():
        return ""
    now = time.time()                       # 只取一次：两次调用可能跨秒，拼出不一致的戳
    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(now)) + "_%04d" % (int(now * 10000) % 10000)
    bak = p.with_name("%s.bak.%s" % (p.name, stamp))
    try:
        bak.write_bytes(p.read_bytes())
    except OSError:
        return ""
    olds = sorted(p.parent.glob("%s.bak.*" % p.name))
    for old in olds[:-_BAK_KEEP]:
        try:
            old.unlink()
        except OSError:
            pass
    return str(bak)


def _write_json(p: Path, data) -> None:
    """原子写 JSON，**沿用原文件的换行风格与 BOM**。

    ★ 为什么计较这个：这个项目的 `06-提示词/*.json` 是 CRLF（制作包在 Windows
      上生成）。用默认的 LF 重写，语义一字不差，但 git diff 会显示「整个文件
      都改了」—— 下次有人看历史，找不到真正的改动是哪一行。
      同理保留 BOM：本仓库读的是 `utf-8-sig`，去掉 BOM 不会出错，但会让
      所有含中文的旧文件在 diff 里变成两行差异（首行 + 编码标记）。
    """
    raw = p.read_bytes() if p.is_file() else b""
    nl = "\r\n" if b"\r\n" in raw[:8192] else "\n"
    bom = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
    text = json.dumps(data, ensure_ascii=False, indent=1)
    if nl != "\n":
        text = text.replace("\n", nl)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_bytes(bom + (text + nl).encode("utf-8"))
    os.replace(tmp, p)


def _content_seconds(prompt: str):
    """提示词里写的「内容时长」。

    两种写法都认：`0-5秒` / `[Shot 1] At 0:05`。取最大值 —— 它代表这段画面
    自己以为有多长。改 duration 不改它，画面描述的时间轴就和实际时长对不上，
    而这种不一致不会让任何校验器报错，只会在成片里表现为「话说完了画面还在
    空转」或者「台词被截断」。
    """
    nums = []
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*[-–~]\s*(\d+(?:\.\d+)?)\s*秒", prompt or ""):
        try:
            nums.append(float(m.group(2)))
        except (TypeError, ValueError):
            continue
    for m in re.finditer(r"\[Shot\s+\d+\]\s*At\s+(\d{1,2}):(\d{2})", prompt or ""):
        nums.append(int(m.group(1)) * 60 + int(m.group(2)))
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*秒", prompt or ""):
        try:
            nums.append(float(m.group(1)))
        except (TypeError, ValueError):
            continue
    return max(nums) if nums else None


def _validate(sid: str, prompt: str, duration, n_refs: int, has_board: bool) -> list:
    """保存前自检。只查「这次改动可能破坏」的那几条，与 ingest_check 同口径。

    不做完整校验（参考图文件是否存在、资产是否登记）—— 那些与本次改动无关，
    每次保存都跑一遍会让保存变慢，而且报的错用户改不了（要先去出图）。
    界面另给「完整校验」入口跑 ingest_check。
    """
    errs = []
    if not str(prompt or "").strip():
        errs.append("提示词不能为空")
        return errs

    if duration is not None:
        try:
            d = float(duration)
        except (TypeError, ValueError):
            errs.append("时长不是数字：%r" % (duration,))
            d = None
        if d is not None and not (DUR_MIN <= d <= DUR_MAX):
            errs.append("时长 %.1f 秒超出 H3 单段范围（%d–%d 秒）" % (d, DUR_MIN, DUR_MAX))

    first = 2 if has_board else 1
    nums = []
    for m in _PIC_REF.finditer(prompt):
        try:
            nums.append(int(m.group(1) or m.group(2)))
        except (TypeError, ValueError):
            continue
    nums = sorted(set(nums))
    if nums:
        if nums != list(range(first, max(nums) + 1)):
            errs.append("图号不连续 %s（应从 %d 起连续）" % (nums, first))
        if max(nums) > PIC_MAX:
            errs.append("图号最大 %d 超过 H3 图片槽上限 %d" % (max(nums), PIC_MAX))
        total = n_refs + (1 if has_board else 0)
        if total < max(nums):
            errs.append("提示词点到第 %d 张，实际只有 %d 张参考图" % (max(nums), total))
    return errs


def save_shot(ws: str, ep: str, shot_id: str, *, duration=None, prompt=None,
              order=None) -> dict:
    """写回一镜。`order` 是**完整**的上传顺序标签列表（含分镜图第一项）。

    返回 `{ok, changed:[...], warnings:[...], errors:[...], backup:[...]}`。
    只要有一处错误就整体不写 —— 半套修改比不改更难查。
    """
    if not (_safe_name(ep) and _safe_name(shot_id)):
        return {"ok": False, "errors": ["集号或镜号不合法"]}
    ep = _ep_key(ep) or ep
    data = studio.data_dir(ws)
    d = _pack_dir(data, ep)
    if d is None:
        return {"ok": False, "errors": ["这一集没有制作包（%s/%s/shots.json 缺失）" % (data, ep)]}

    prompts_p = d / "h3_prompts.json"
    shots_p = d / "shots.json"
    prompts = _read_json(prompts_p)
    shots = _read_json(shots_p)
    if not isinstance(prompts, dict) or not isinstance(prompts.get(shot_id), dict):
        return {"ok": False, "errors": ["h3_prompts.json 里没有 %s" % shot_id]}
    if isinstance(shots, dict):
        shots = shots.get("shots") or []
    if not isinstance(shots, list):
        return {"ok": False, "errors": ["shots.json 结构不对（应为数组）"]}

    cur = prompts[shot_id]
    row = next((s for s in shots if str(s.get("shot_id")) == shot_id), None)
    if row is None:
        return {"ok": False, "errors": ["shots.json 里没有 %s" % shot_id]}

    has_board = bool(str(row.get("board_ref") or "").strip())
    old_prompt = str(cur.get("prompt") or "")
    new_prompt = old_prompt if prompt is None else str(prompt)
    old_dur = cur.get("duration")
    new_dur = old_dur if duration is None else duration

    changes, warnings = [], []
    mapping = {}
    new_order = None

    # ---- 参考图顺序：先重排提示词，再取新顺序 ----
    if order is not None:
        old_labels = _parse_order(new_prompt)
        if not old_labels:
            return {"ok": False, "errors": [
                "这一镜的提示词里没有可用的「上传顺序」行，无法改顺序。"
                "先按制作包规范补上（Mixed 1＝… 分镜图｜Mixed 2＝…）。"]}
        if len(order) != len(old_labels):
            return {"ok": False, "errors": ["新顺序 %d 项，原来 %d 项" % (len(order), len(old_labels))]}
        if old_labels and order and old_labels[0] != order[0]:
            return {"ok": False, "errors": [
                "第 1 张必须是分镜图（%s），它固定在 <Picture 1> 槽位，挪不动。"
                % old_labels[0]]}
        new_prompt, mapping, err = _reorder_prompt(new_prompt, list(order))
        if err:
            return {"ok": False, "errors": [err]}
        changed_pairs = [{"from": k, "to": v} for k, v in sorted(mapping.items()) if k != v]
        if changed_pairs:
            changes.append("参考图顺序：%s" % "，".join(
                "Mixed %d→%d" % (x["from"], x["to"]) for x in changed_pairs))
            new_order = list(order)
        elif [x for x in (order or [])] != old_labels:
            new_order = list(order)

    # ---- 时长 ----
    if duration is not None:
        try:
            nd = float(duration)
        except (TypeError, ValueError):
            return {"ok": False, "errors": ["时长不是数字：%r" % (duration,)]}
        if str(old_dur) != str(duration) and old_dur != nd:
            new_dur = int(nd) if nd == int(nd) else round(nd, 2)
            changes.append("时长：%s 秒 → %s 秒" % (old_dur if old_dur is not None else "—", new_dur))
            cs = _content_seconds(new_prompt)
            if cs is not None and abs(cs - nd) > 0.01:
                warnings.append(
                    "提示词里写的时间轴是 %.0f 秒，你改成了 %s 秒。"
                    "画面描述不会自动跟着改 —— 需要的话在「提示词」里手动调。" % (cs, new_dur))

    # ---- 提示词 ----
    if prompt is not None and new_prompt != old_prompt:
        changes.append("提示词：%d 字 → %d 字" % (len(old_prompt), len(new_prompt)))

    if not changes:
        return {"ok": True, "changed": [], "warnings": [], "errors": [],
                "detail": "没有任何改动", "backup": []}

    # ---- 自检 ----
    n_refs = 0
    labels = _parse_order(new_prompt)
    if labels:
        n_refs = len(labels) - 1
    else:
        n_refs = len(row.get("cast") or []) or (
            len(row.get("character_refs") or []) + len(row.get("scene_refs") or []))
    errs = _validate(shot_id, new_prompt, new_dur, n_refs, has_board)
    if errs:
        return {"ok": False, "errors": errs, "changed": changes, "warnings": warnings}

    # ---- 写盘（先备份，两个文件一起改）----
    baks = [b for b in (_backup(prompts_p), _backup(shots_p)) if b]

    new_cur = dict(cur)
    new_cur["prompt"] = new_prompt
    if new_dur is not None:
        new_cur["duration"] = new_dur
    prompts[shot_id] = new_cur
    _write_json(prompts_p, prompts)

    if new_order is not None:
        chars = _read_json(d / "characters.json") or {}
        scenes = _read_json(d / "scenes.json") or {}
        keys = [_label_to_key(lab, chars, scenes) for lab in new_order[1:]]
        keys = [k for k in keys if k]
        new_row = dict(row)
        # cast 是「完整且有序」的列表（P2 契约）；两张分表保留给旧引擎
        new_row["cast"] = keys
        new_row["character_refs"] = [k for k in keys if k not in scenes]
        new_row["scene_refs"] = [k for k in keys if k in scenes]
        shots = [new_row if str(s.get("shot_id")) == shot_id else s for s in shots]
        _write_json(shots_p, shots)

    clear_cache()
    return {
        "ok": True, "changed": changes, "warnings": warnings, "errors": [],
        "backup": [str(Path(b).name) for b in baks],
        "order": new_order or labels or [],
        "duration": new_dur,
        "prompt": new_prompt,
    }
