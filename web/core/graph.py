# -*- coding: utf-8 -*-
"""graph.py —— 节点画布（可连线的生产图）

它和 `pipeline.py` 的分工
------------------------
`pipeline.py` 回答「按顺序跑下一步」；这里回答「**我的片子长什么样、卡在哪、我要怎么摆**」。
同一份事实（`drama nodes --json` 的节点与判据）画成一张图，所以不存在两套口径。

两种模式，一张图
----------------
* **流水线模式**：节点按依赖自动排成左→右的列，连线就是引擎依赖（带锁）。
* **精细化模式**：节点可以拖到任意位置，用户可以加自己的连线表达「我习惯这样走」。
  自由连线是**编排意图**（虚线），不改变引擎的强制依赖 —— 引擎只认 `reads`，
  改了也没用。这一点必须写在界面上，否则用户会以为「连了线就会按我连的跑」。

为什么允许自由连线但不让它改执行顺序
------------------------------------
出片链路上每一步都有硬前置（没有分镜图就出片 = 白烧 GPU）。让画布改依赖，
等于把「顺序错了要 10 分钟后才发现」的坑重新挖开。所以：
  · 依赖边（实线，带锁）不可删；
  · 自由边（虚线）可加可删，只表达意图与分组；
  · 运行按钮永远按引擎顺序报「还缺什么」，不按画布。

落盘
----
`<ws>/canvas.json`：`{version, view, pos, extra_edges, hidden_edges}`。
放工作区而不是 localStorage：换机器、换浏览器，摆好的位置还在。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from . import adapters, canvas, creation, generators as GEN, paths, studio

_EP_RE = re.compile(r"^(?:ep)?[_-]?(\d{1,3})$")
_CACHE: dict = {}
_TTL = 6

GRAPH_FILE = "canvas.json"
VERSION = 2

# 节点类型：只影响观感与「能不能连」，不影响执行。
KINDS = {
    "skill":    {"label": "创作模板", "tone": "create"},
    "idea":     {"label": "灵感", "tone": "create"},
    "plan":     {"label": "企划案", "tone": "create"},
    "design":   {"label": "资产库（创作）", "tone": "create"},
    "script":   {"label": "剧本", "tone": "create"},
    "storyboard": {"label": "导演手册", "tone": "create"},
    "pack":     {"label": "导入契约", "tone": "exec"},
    "asset":    {"label": "资产图", "tone": "exec"},
    "bind":     {"label": "回填参考表", "tone": "exec"},
    "board":    {"label": "分镜图", "tone": "board"},
    "gate":     {"label": "入门口禁", "tone": "exec"},
    "video":    {"label": "出片", "tone": "exec"},
    "edit":     {"label": "剪辑", "tone": "edit"},
    "release":  {"label": "发行", "tone": "edit"},
}

# 引擎节点 id → 画布类型
_KIND_BY_ID = {
    "import.pack": "pack",
    "asset.render": "asset",
    "import.bind": "bind",
    "board.frame": "board",
    "import.gate": "gate",
    "video.resolve": "video",
    "video.batch": "video",
    "video.audit": "video",
    "edit.master": "edit",
    "edit.upscale": "edit",
    "edit.subtitle": "edit",
    "edit.draft": "edit",
    "edit.release": "release",
}

# 引擎节点 id → 可运行的命令（commands.py 的 spec id）。空 = 只有判据没有动作。
_CMD_BY_ID = {
    "import.pack": "pack.import",
    "asset.render": "assets.local",
    "import.bind": "pack.import",
    "board.frame": "board.frame",
    "import.gate": "ingest.check",
    "video.resolve": "video.local.check",
    "video.batch": "video.run",
    "video.audit": "video.local.check",
    "edit.master": "media.master",
    "edit.upscale": "media.upscale",
    "edit.subtitle": "media.render",
    "edit.draft": "media.draft",
    "edit.release": "release.export",
}

# 引擎节点的中文短名（`nodes.py` 里只有 id，画布上要给人看）
_TITLE = {
    "import.pack": "导入制作包",
    "asset.render": "资产出图",
    "import.bind": "回填参考表",
    "board.frame": "分镜图",
    "import.gate": "入门口禁",
    "video.resolve": "通道检查",
    "video.batch": "批量出片",
    "video.audit": "逐段体检",
    "edit.master": "母版拼接",
    "edit.upscale": "高清放大",
    "edit.subtitle": "字幕烧录",
    "edit.draft": "剪映工程",
    "edit.release": "导出发布版",
}

HINT = {
    "import.pack": "把制作包翻成 06-提示词 契约，提示词逐字搬",
    "asset.render": "人/场/道参考图，本机出图 ￥0",
    "import.bind": "出完图重跑导入，回填 characters/scenes",
    "board.frame": "每镜一张 9:16 首帧，出片的第一张参考图",
    "import.gate": "缺图/缺字段在这里拦住，别带病出片",
    "video.resolve": "工作流与模型就绪才允许提交",
    "video.batch": "逐段出片，退出码 3 = 批次缺口",
    "video.audit": "存在/时长/分辨率/音轨",
    "edit.master": "拼接前校验帧数，不足会重编码",
    "edit.upscale": "1080×1920 交付规格",
    "edit.subtitle": "字幕时间只认对齐结果",
    "edit.draft": "剪映草稿：逐镜+字幕+BGM，与成片同源",
    "edit.release": "EpisodeNN.mp4 落 09-发行/剧集/",
}

# 创作侧 6 个节点（顺序即默认列序）
_CREATION = [
    ("skill", "storyboard_lock", "创作模板", "题材套路与阶段划分（新建项目时选）"),
    ("idea", "spark", "灵感", "一句话 + 集数与时长"),
    ("plan", "list", "企划案", "故事、人物、关系"),
    ("design", "image", "资产库", "人物/场景/道具的提示词卡"),
    ("script", "film", "剧本", "分集台词"),
    ("storyboard", "layers", "导演手册", "分镜与视频提示词原文"),
]
_CREATION_IDS = ["skill", "idea", "plan", "design", "script", "storyboard"]


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
# 落盘的布局
# ---------------------------------------------------------------------------
def _file(ws) -> Path:
    return Path(str(ws)) / GRAPH_FILE


def layout_of(ws) -> dict:
    raw = paths.read_json(_file(ws), default=None)
    if not isinstance(raw, dict):
        return {"version": VERSION, "view": {"x": 40, "y": 40, "scale": 1},
                "pos": {}, "extra_edges": [], "hidden_edges": []}
    view = raw.get("view") if isinstance(raw.get("view"), dict) else {}
    return {
        "version": VERSION,
        "view": {"x": float(view.get("x") or 40), "y": float(view.get("y") or 40),
                 "scale": min(2.0, max(0.35, float(view.get("scale") or 1)))},
        "pos": {str(k): v for k, v in (raw.get("pos") or {}).items()
                if isinstance(v, dict) and "x" in v and "y" in v},
        "extra_edges": [e for e in (raw.get("extra_edges") or [])
                        if isinstance(e, list) and len(e) == 2],
        "hidden_edges": [e for e in (raw.get("hidden_edges") or [])
                         if isinstance(e, list) and len(e) == 2],
    }


def save_layout(ws, *, pos=None, view=None) -> dict:
    """只写位置与视口。不校验节点 id 是否存在 —— 画布可能比引擎旧一版，
    删掉的节点留个孤儿坐标无害，删了反而会在换回旧版时全丢。"""
    doc = layout_of(ws)
    if isinstance(pos, dict):
        for k, v in pos.items():
            if not isinstance(v, dict):
                continue
            try:
                doc["pos"][str(k)] = {"x": round(float(v["x"]), 1), "y": round(float(v["y"]), 1)}
            except (KeyError, TypeError, ValueError):
                continue
    if isinstance(view, dict):
        try:
            doc["view"] = {"x": round(float(view.get("x", doc["view"]["x"])), 1),
                           "y": round(float(view.get("y", doc["view"]["y"])), 1),
                           "scale": min(2.0, max(0.35, float(view.get("scale", doc["view"]["scale"]))))}
        except (TypeError, ValueError):
            pass
    doc["updated_at"] = time.time()
    paths.write_json(_file(ws), doc)
    clear_cache()
    return {"ok": True, "view": doc["view"], "pos_count": len(doc["pos"])}


def reset_layout(ws) -> dict:
    p = _file(ws)
    if p.is_file():
        p.unlink()
    clear_cache()
    return {"ok": True, "detail": "布局已重置为自动排列"}


def add_edge(ws, src: str, dst: str) -> dict:
    s, d = str(src or "").strip(), str(dst or "").strip()
    if not s or not d or s == d:
        return {"ok": False, "detail": "连线两端不能是同一个节点，也不能为空"}
    doc = layout_of(ws)
    if [s, d] in doc["extra_edges"]:
        return {"ok": True, "already": True}
    doc["extra_edges"].append([s, d])
    doc["hidden_edges"] = [e for e in doc["hidden_edges"] if e != [s, d]]
    doc["updated_at"] = time.time()
    paths.write_json(_file(ws), doc)
    clear_cache()
    return {"ok": True, "detail": "已加一条编排连线（虚线，不改变执行顺序）"}


def remove_edge(ws, src: str, dst: str, *, locked: bool = False) -> dict:
    s, d = str(src or "").strip(), str(dst or "").strip()
    if locked:
        return {"ok": False, "locked": True,
                "detail": "这条是引擎的强制依赖（没有上游产物就会白跑），不能删。"
                          "要表达别的顺序请加虚线，执行顺序仍以引擎为准。"}
    doc = layout_of(ws)
    doc["extra_edges"] = [e for e in doc["extra_edges"] if e != [s, d]]
    if [s, d] not in doc["hidden_edges"]:
        doc["hidden_edges"].append([s, d])
    doc["updated_at"] = time.time()
    paths.write_json(_file(ws), doc)
    clear_cache()
    return {"ok": True}


# ---------------------------------------------------------------------------
# 磁盘进度（状态只认磁盘 —— 与剧集画布同一口径）
# ---------------------------------------------------------------------------
def _progress(ws, ep: str) -> dict:
    """每个节点的「做完了几个 / 一共几个」。取不到的给 None，不编 0。"""
    eps = studio.episodes(ws)
    row = next((e for e in eps if e.get("ep") == ep), {}) if ep else {}
    shots_n = None
    d = studio.data_dir(ws) / ep
    if ep and (d / "shots.json").is_file():
        raw = paths.read_json(d / "shots.json", default=None)
        if isinstance(raw, dict):
            raw = raw.get("shots") or []
        shots_n = len(raw) if isinstance(raw, list) else None

    boards = 0
    bd = studio.assets_dir(ws) / "boards" / ep
    if bd.is_dir():
        boards = len([p for p in bd.glob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")])

    segs = 0
    if ep:
        # 段可能落在布局指定的 out，也可能还在旧的 `<engine_root>/output`（迁移期的项目两种都有）
        idx = dict(canvas._walk_segments(studio.engine_root(ws) / "output"))   # noqa: SLF001
        idx.update(canvas._walk_segments(studio.out_dir(ws)))                  # noqa: SLF001
        for name in idx:
            if re.match(r"^(?:%s_)?shot_" % ep, name):
                segs += 1

    bind = None
    if ep:
        ch = paths.read_json(d / "characters.json", default=None)
        sc = paths.read_json(d / "scenes.json", default=None)
        if isinstance(ch, dict) or isinstance(sc, dict):
            filled = bool((ch or {})) or bool((sc or {}))
            bind = {"done": 1 if filled else 0, "total": 1}

    def pair(done, total=None):
        """→ {done, total}；两个都是 0 时返回 None（＝这一集还没东西，不显示 0/0）。"""
        n = int(done or 0)
        t = int(total) if total else n
        if not t:
            return None
        return {"done": min(n, t), "total": t}

    def has(*pats):
        out = studio.out_dir(ws)
        for p in pats:
            try:
                if next(out.glob(p), None) is not None:
                    return True
            except OSError:
                continue
        return False

    # 命名有两套：引擎写 `_master` / `_subbed`，早期人工跑的项目写 `_final` / `_sub`。
    # 只认前者会让「剪辑明明做完了」显示成没做（UNTIL-DECEMBER 就是这样）。
    master = bool(row.get("master")) or has("%s_final.mp4" % ep, "%s_master*.mp4" % ep)
    subbed = bool(row.get("subbed")) or has("%s_sub.mp4" % ep, "%s_subbed*.mp4" % ep)
    upsc = bool(row.get("upscaled")) or has("%s_master_*x*.mp4" % ep)
    return {
        "import.pack": pair(1 if shots_n else 0, 1),
        "asset.render": None,
        "import.bind": bind,
        "board.frame": pair(boards, shots_n or boards),
        "import.gate": pair(min(boards, shots_n) if shots_n else boards, shots_n or boards),
        "video.resolve": None,
        "video.batch": pair(segs, shots_n or segs),
        "video.audit": pair(segs, shots_n or segs),
        "edit.master": pair(1 if master else 0, 1),
        "edit.upscale": pair(1 if upsc else 0, 1),
        "edit.subtitle": pair(1 if subbed else 0, 1),
        "edit.draft": pair(1 if row.get("draft") else 0, 1),
        "edit.release": pair(1 if row.get("release") else 0, 1),
    }


def _assets_pairs(ws):
    """资产图：refs.json 的 key 数 vs 三张目录里真实存在的图。"""
    a = studio.assets_dir(ws)
    refs = paths.read_json(a / "refs.json", default={}) or {}
    keys = {}
    for kind in ("characters", "scenes", "props"):
        if isinstance(refs.get(kind), dict):
            keys.update(refs[kind])
    n = 0
    for sub in ("characters", "scenes", "props"):
        d = a / sub
        if d.is_dir():
            n += len([p for p in d.glob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")])
    if not keys and not n:
        return None
    return {"done": n, "total": len(keys) or n}


# ---------------------------------------------------------------------------
# 主聚合
# ---------------------------------------------------------------------------
def state(ws, ep: str = "") -> dict:
    return _cached("graph:%s:%s" % (ws, ep), lambda: _build(str(ws), ep))


def _norm_ep(raw: str) -> str:
    m = _EP_RE.fullmatch(str(raw or "").strip())
    return ("ep%02d" % int(m.group(1))) if m else "ep01"


# 哪些节点会因为「项目确认了云端」而换成另一条命令
_CLOUD_SWAP = {
    "asset.render": ("image", "assets.cloud"),
    "video.batch": ("video", "video.cloud"),
}


def _cmd_for(ws: str, nid: str) -> str:
    """节点上「运行」按钮该跑哪条命令 —— 按模型确认单选，与流水线/命令层同一条口径。

    ★ 写死本地命令的后果：云端项目里点「资产出图」会被门禁拦（expected_engine=local），
      而用户看到的是「按钮没反应」。
    """
    swap = _CLOUD_SWAP.get(nid)
    if swap and GEN.plan_choice(ws, swap[0]) == "cloud_comfyui":
        return swap[1]
    return _CMD_BY_ID.get(nid, "")


def _build(ws: str, ep: str) -> dict:
    ep = _norm_ep(ep)
    wf = adapters.norm_workflow(adapters.workflow_status(ws))
    cre = creation.state(ws)
    prog = _progress(ws, ep)
    prog["asset.render"] = _assets_pairs(ws)

    nodes: list = []
    edges: list = []

    # ---- 创作侧 ----
    sk = 0
    try:
        from . import skills as _skills
        sk = len(_skills.installed(ws).get("items") or [])
    except Exception:                                          # noqa: BLE001
        sk = 0
    # 阶段 id（plan/assets/script/director）→ 画布节点 id，映射只在这里写一次
    stage_to_node = {"plan": "plan", "assets": "design", "script": "script", "director": "storyboard"}
    stage_row = {s.get("id"): s for s in (cre.get("stages") or [])}
    done_of = {"skill": sk > 0, "idea": cre["idea"]["state"] == "done"}
    chars_of = {"skill": sk, "idea": len(cre["idea"].get("idea") or "")}
    for sid, nid in stage_to_node.items():
        s = stage_row.get(sid) or {}
        done_of[nid] = s.get("state") == "done"
        chars_of[nid] = int(s.get("chars") or 0)
    # 制作包已导入 = 导演手册在别处写过（真实项目常常把创作文档放在工作区外）
    if (cre.get("pack") or {}).get("state") == "done":
        done_of["storyboard"] = True
        chars_of["storyboard"] = chars_of.get("storyboard") or len(
            (cre["pack"].get("episodes") or []))

    for nid, _ico, title, hint in _CREATION:
        done = bool(done_of.get(nid))
        nodes.append({
            "id": nid, "kind": nid,
            "title": title, "hint": hint,
            "stage": "create",
            "state": "done" if done else "todo",
            "gate": "",
            "detail": (("%d 份模板" % sk) if nid == "skill" else
                       ("%d 字" % chars_of.get(nid, 0)) if chars_of.get(nid) else
                       ("已完成" if done else "空")),
            "progress": None,
            "cmd": "", "create_stage": ({"storyboard": "director"}.get(nid, nid)
                                       if nid in ("plan", "design", "script", "storyboard") else ""),
            "ep": False, "locked": False,
        })

    # 创作侧依赖：`needs` 由 creation.STAGES 给，不另写一份
    edges.append({"from": "skill", "to": "plan", "kind": "dep", "locked": True})
    edges.append({"from": "idea", "to": "plan", "kind": "dep", "locked": True})
    need_map = {"plan": "plan", "assets": "design", "script": "script", "director": "storyboard"}
    for s in cre.get("stages") or []:
        to = need_map.get(s["id"])
        if not to:
            continue
        for need in s.get("needs") or []:
            src = {"skill": "skill", "plan": "plan", "assets": "design"}.get(need)
            if src and [src, to] not in [[e["from"], e["to"]] for e in edges]:
                edges.append({"from": src, "to": to, "kind": "dep", "locked": True})

    # ---- 引擎侧 ----
    idx_nodes = {n.get("id"): n for n in (wf.get("nodes") or [])}
    for n in (wf.get("nodes") or []):
        nid = n.get("id") or ""
        kind = _KIND_BY_ID.get(nid, "edit")
        p = prog.get(nid)
        st = n.get("state") or "absent"
        gate_ok = st in ("passed", "skipped")
        # ★ 状态以**磁盘产物**为准，门禁只作为备注：
        #   真实项目常常是「人工跑过、产物都在，但没有 `_done/*.json` 标记」，
        #   这时按门禁画会整片红，人会以为片子没做。产物齐了就画成完成，
        #   再用 `gate_ok` 标一句「判据未过」——两件事，不合并。
        disk_done = bool(p and p.get("total") and p["done"] >= p["total"])
        done = gate_ok or disk_done
        nodes.append({
            "id": nid, "kind": kind,
            "title": _TITLE.get(nid, nid),
            "hint": HINT.get(nid, ""),
            "stage": n.get("stage") or "",
            "state": "done" if done else ("doing" if st == "stale" else "todo"),
            "gate": st,
            "gate_ok": gate_ok,
            "note": ("" if gate_ok or not disk_done
                     else "产物已齐；引擎判据未过（缺 _done 标记或上游顺序不同）"),
            "detail": n.get("detail") or "",
            "progress": p,
            "cmd": _cmd_for(ws, nid),
            "create_stage": "",
            "ep": bool(n.get("ep")),
            "locked": False,
        })
        for up in (n.get("reads") or []):
            edges.append({"from": up, "to": nid, "kind": "dep", "locked": True})
    # 导演手册 → 制作包（制作包是 Skill 产物，不是引擎产物，但它决定导入能否开始）
    if "import.pack" in idx_nodes:
        edges.append({"from": "storyboard", "to": "import.pack", "kind": "dep", "locked": True})

    # 去重
    seen, base = set(), []
    for e in edges:
        k = (e["from"], e["to"])
        if k in seen:
            continue
        seen.add(k)
        base.append(e)

    # ---- 叠加用户布局 ----
    lay = layout_of(ws)
    hidden = {(e[0], e[1]) for e in lay["hidden_edges"]}
    edges = [e for e in base if (e["from"], e["to"]) not in hidden]
    for a, b in lay["extra_edges"]:
        if (a, b) in seen:
            continue
        seen.add((a, b))
        edges.append({"from": a, "to": b, "kind": "user", "locked": False})

    ids = [n["id"] for n in nodes]
    edges = [e for e in edges if e["from"] in ids and e["to"] in ids]

    # ---- 自动布局（缺坐标的节点才补）----
    auto = _auto_layout(nodes, edges)
    for n in nodes:
        p = lay["pos"].get(n["id"]) or auto.get(n["id"]) or {"x": 0, "y": 0}
        n["x"], n["y"] = round(float(p["x"])), round(float(p["y"]))

    counts = {"total": len(nodes),
              "done": sum(1 for n in nodes if n["state"] == "done"),
              "doing": sum(1 for n in nodes if n["state"] == "doing"),
              "todo": sum(1 for n in nodes if n["state"] == "todo")}
    return {
        "ok": True,
        "ws": str(ws), "ep": ep,
        "nodes": nodes, "edges": edges,
        "view": lay["view"],
        "kinds": KINDS,
        "counts": counts,
        "note": "实线 = 引擎强制依赖（不可删）；虚线 = 你的编排意图（不影响执行顺序）。"
                "节点状态只认磁盘产物，不看「跑过没」。",
        "updated_at": time.time(),
        "workflow_ok": bool(wf.get("ok")),
        "workflow_reason": wf.get("reason") or "",
    }


# 自动排布：按「生产链的语义列」摆，不按最长路径。
# 为什么不用拓扑分层：本图基本是一条链（18 节点 17 条边），纯拓扑分层会把它们排成
# 一行 18 列（4500px 宽），缩到 35% 才能看全 —— 字全糊，等于没有画布。
# 语义列是人和引擎都认的分组（创作 / 导入资产 / 分镜图 / 出片 / 剪辑），一眼能读。
_COL = {
    "skill": 0, "idea": 0,
    "plan": 1, "design": 1, "script": 1, "storyboard": 1,
    "import.pack": 2, "asset.render": 2, "import.bind": 2,
    "board.frame": 3,
    "import.gate": 4, "video.resolve": 4, "video.batch": 4, "video.audit": 4,
    "edit.master": 5, "edit.upscale": 5, "edit.subtitle": 5, "edit.release": 5,
}
_ROW_ORDER = ["skill", "idea", "plan", "design", "script", "storyboard",
              "import.pack", "asset.render", "import.bind", "board.frame",
              "import.gate", "video.resolve", "video.batch", "video.audit",
              "edit.master", "edit.upscale", "edit.subtitle", "edit.release"]
_COL_W = 244
_ROW_H = 108


def _auto_layout(nodes, edges) -> dict:
    """语义列 + 列内按生产顺序排行。没有显式列的节点退回 `stage` 分列。"""
    stage_col = {"create": 0, "import": 2, "asset": 2, "board": 3, "video": 4, "edit": 5}
    order = {nid: i for i, nid in enumerate(_ROW_ORDER)}
    cols: dict = {}
    for n in nodes:
        c = _COL.get(n["id"], stage_col.get(n.get("stage") or "", 0))
        cols.setdefault(c, []).append(n["id"])
    pos = {}
    for c, members in cols.items():
        members.sort(key=lambda x: order.get(x, 99))
        for r, nid in enumerate(members):
            pos[nid] = {"x": 40 + c * _COL_W, "y": 40 + r * _ROW_H}
    return pos
