# -*- coding: utf-8 -*-
"""creation.py —— 创作链的产物管理（企划案 / 资产库 / 剧本 / 导演手册）

分层，别混
----------
    00-创作/        ← 这里：人和模型写的东西（Markdown，可改、可推翻）
    pack/           ← 制作包：把上面的东西压成引擎能吃的契约（JSON）
    04-资产/ 06-提示词/ 07-成片/   ← 引擎产物（图片、视频，不该手改）

为什么单独一个目录
------------------
Skill 的约定是 `片名/01-企划案.md`、`02-资产库.md`…… 而引擎工作区已有
`03-剧本/`、`05-分镜/` 这些带语义的目录。两者混在一起会出现「剧本有两个版本、
不知道哪个是引擎在读」。

所以定死：**创作产物进 `00-创作/`，引擎只读 `06-提示词/` 的契约**。
转换那一步（pack.convert）负责把 `00-创作/04-导演手册/*.md` 翻成 JSON。
这条分工让「改剧本」和「改提示词」永远不冲突 —— 改前者要重跑转换，改后者只影响出片。

状态判据
--------
每个阶段只报三种状态：`empty` / `draft` / `done`。
`done` 的判据是「文件存在且非空」，不是字数阈值 —— 编一个阈值只会让人为了过线灌水。
"""

from __future__ import annotations

import time
from pathlib import Path

from . import paths

DIR_NAME = "00-创作"

# 顺序即流水线顺序。`file` 相对 `00-创作/`。
STAGES = [
    {"id": "plan", "file": "01-企划案.md", "label": "企划案",
     "desc": "片名、一句话故事、人物关系、阻力结构、集数时长",
     "needs": ["brief"]},
    {"id": "assets", "file": "02-资产库.md", "label": "资产库",
     "desc": "人物 / 场景 / 道具，每条都要能独立出图",
     "needs": ["plan"]},
    {"id": "script", "file": "03-分集剧本.md", "label": "分集剧本",
     "desc": "对白驱动，60 秒 ≥ 10 句",
     "needs": ["plan"]},
    {"id": "director", "file": "04-导演手册", "label": "导演手册",
     "desc": "分镜 + 视频提示词；单镜 4–15 秒",
     "needs": ["assets", "script"], "multi": True},
]


def cdir(ws) -> Path:
    return Path(str(ws)) / DIR_NAME


def _rel(ws, p: Path) -> str:
    try:
        return str(p.relative_to(Path(str(ws)))).replace("\\", "/")
    except ValueError:
        return str(p)


def state(ws) -> dict:
    """创作链的完整状态：灵感 → 4 个产物 → 制作包 → 引擎。"""
    ws = Path(str(ws))
    d = cdir(ws)

    # ---- 灵感：brief.json（一句话 + 市场 + 题材方向）----
    brief = paths.read_json(ws / "brief.json", default=None) or {}
    proj = paths.read_json(ws / "project.json", default=None) or {}
    meta = proj.get("meta") or {}
    idea = {
        "state": "done" if brief else "empty",
        # 原文要带上：界面上「灵感」框要能让用户看到自己写过什么、接着改。
        # 只给标题不给原文，用户会以为灵感丢了，然后重写一遍 —— 同一句话写两遍。
        # 老项目的 brief.json 只有 title / genre_directions，没有 idea 字段。
        # 直接留空会让人以为「灵感丢了」，然后重写一句已经存在的话。
        "idea": str(brief.get("idea") or _idea_fallback(brief))[:2000],
        "title": brief.get("title") or meta.get("title") or "",
        "market": brief.get("market_label") or brief.get("market") or "",
        "platform": brief.get("platform") or meta.get("platform") or "",
        "audience": brief.get("audience") or "",
        "genres": brief.get("genre_directions") or [],
        "ep_total": brief.get("ep_total") or meta.get("total_ep") or 0,
        "ep_seconds": meta.get("ep_seconds") or 0,
        "style_lock": (meta.get("style_lock") or "")[:160],
        "slug": brief.get("slug") or meta.get("slug") or "",
    }

    # ---- 四个产物 ----
    stages = []
    for s in STAGES:
        p = d / s["file"]
        item = {"id": s["id"], "label": s["label"], "desc": s["desc"],
                "needs": s["needs"], "multi": bool(s.get("multi"))}
        if s.get("multi"):
            files = sorted(p.glob("*.md")) if p.is_dir() else []
            item.update({"state": "done" if files else "empty",
                         "files": [{"name": f.name, "rel": _rel(ws, f),
                                    "chars": len(f.read_text(encoding="utf-8", errors="replace")),
                                    "mtime": f.stat().st_mtime} for f in files],
                         "path": _rel(ws, p)})
            item["chars"] = sum(x["chars"] for x in item["files"])
        else:
            ok = p.is_file() and p.stat().st_size > 0
            # ★ 字数要按**字符**数，不是字节数。中文一个字 3 字节，
            #   用 st_size 会把 440 字显示成「952 字」—— 用户会以为生成了两倍内容，
            #   而真相只是编码差异。这种错不影响功能，但会让人对整页数字失去信任。
            n = len(p.read_text(encoding="utf-8", errors="replace")) if ok else 0
            item.update({"state": "done" if ok else "empty",
                         "path": _rel(ws, p),
                         "chars": n,
                         "mtime": p.stat().st_mtime if ok else 0})
        stages.append(item)

    # ---- 制作包：有没有导入成 data 契约 ----
    data_dir = paths.read_json(ws / "layout.json", default={}) or {}
    prom = (data_dir.get("stages") or {}).get("prompts") or "06-提示词"
    dd = ws / prom
    eps = [x.name for x in dd.iterdir() if x.is_dir() and (x / "shots.json").is_file()] if dd.is_dir() else []
    pack = {"state": "done" if eps else "empty", "episodes": sorted(eps),
            "dir": prom, "path": _rel(ws, ws / "pack")}

    # ---- 引擎产物：资产图 / 分镜图 ----
    st = data_dir.get("stages") or {}
    assets_dir = ws / (st.get("assets") or "04-资产")
    def _count(sub):
        p = assets_dir / sub
        if not p.is_dir():
            return 0
        return len([x for x in p.rglob("*") if x.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")])
    engine = {
        "characters": _count("characters"), "scenes": _count("scenes"),
        "props": _count("props"), "boards": _count("boards"),
        "dir": _rel(ws, assets_dir),
    }

    done = sum(1 for s in stages if s["state"] == "done")
    return {
        "ok": True, "dir": _rel(ws, d), "dir_exists": d.is_dir(),
        "idea": idea, "stages": stages,
        "progress": {"done": done, "total": len(stages)},
        "pack": pack, "engine": engine,
        "next": _next(stages, pack),
        "note": "创作产物在 %s/，引擎只读 %s/ 的契约 —— 改前者要重跑「转制作包」，改后者只影响出片" % (DIR_NAME, prom),
    }


def _next(stages, pack) -> dict:
    """下一步该做什么。只给一条 —— 给三条等于没给。"""
    for s in stages:
        if s["state"] != "done":
            return {"stage": s["id"], "label": "先写「%s」" % s["label"],
                    "why": s["desc"]}
    if pack["state"] != "done":
        return {"stage": "pack", "label": "把它转成制作包",
                "why": "引擎要的是 JSON 契约，不是 Markdown"}
    return {"stage": "run", "label": "开始出图 / 出片",
            "why": "契约齐了，剩下的交给引擎"}


# ---------------------------------------------------------------------------
# 读写产物
# ---------------------------------------------------------------------------
_STAGE_BY_ID = {s["id"]: s for s in STAGES}


def read(ws, stage: str) -> dict:
    s = _STAGE_BY_ID.get(stage)
    if not s:
        raise KeyError(stage)
    p = cdir(ws) / s["file"]
    if s.get("multi"):
        items = []
        if p.is_dir():
            for f in sorted(p.glob("*.md")):
                items.append({"name": f.name,
                              "text": f.read_text(encoding="utf-8", errors="replace")})
        return {"ok": True, "stage": stage, "items": items,
                "text": "\n\n---\n\n".join(x["text"] for x in items)}
    text = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""
    return {"ok": True, "stage": stage, "text": text, "path": str(p)}


def write(ws, stage: str, text: str, *, name: str = "", backup: bool = True) -> dict:
    """把产物写进 `00-创作/`。**不覆盖已有的不同内容而不留备份**。

    为什么留备份：这些是模型写的、人要改的文本。一次「重新生成」把改了三小时的东西
    冲掉，是这类工具最容易造成的不可逆损失。
    """
    s = _STAGE_BY_ID.get(stage)
    if not s:
        raise KeyError(stage)
    ws = Path(str(ws))
    text = (text or "").strip()
    if not text:
        raise ValueError("内容为空：不写空文件（空文件会让状态显示「已完成」）")
    d = cdir(ws)
    d.mkdir(parents=True, exist_ok=True)

    if s.get("multi"):
        sub = d / s["file"]
        sub.mkdir(parents=True, exist_ok=True)
        fn = (name or "第01集").strip()
        if not fn.endswith(".md"):
            fn += ".md"
        p = sub / Path(fn).name                 # 只取文件名，防目录穿越
    else:
        p = d / s["file"]

    bak = ""
    if backup and p.is_file() and p.stat().st_size > 0:
        old = p.read_text(encoding="utf-8", errors="replace")
        if old.strip() != text:
            b = p.with_name("%s.bak_%d%s" % (p.stem, int(time.time()), p.suffix))
            b.write_text(old, encoding="utf-8", newline="")
            bak = str(b)
    p.write_text(text, encoding="utf-8", newline="")
    rel = _rel(ws, p)
    return {"ok": True, "stage": stage, "path": str(p), "rel": rel,
            "chars": len(text), "backup": bak,
            "detail": "已写入 %s（%d 字）%s"
                      % (rel, len(text), "；旧版备份为 %s" % Path(bak).name if bak else "")}


def save_idea(ws, payload: dict) -> dict:
    """写灵感（brief.json）。这是整条链的起点，也是唯一需要人「说一句话」的地方。"""
    ws = Path(str(ws))
    cur = paths.read_json(ws / "brief.json", default=None) or {}
    idea = str(payload.get("idea") or "").strip()
    if idea:
        cur["idea"] = idea
        if not cur.get("title"):
            cur["title"] = idea[:24]
    for k in ("title", "market", "market_label", "platform", "audience", "form"):
        if payload.get(k) is not None and str(payload.get(k)).strip():
            cur[k] = str(payload.get(k)).strip()
    if payload.get("ep_total"):
        try:
            cur["ep_total"] = int(payload["ep_total"])
        except (TypeError, ValueError):
            pass
    if payload.get("genres"):
        g = payload["genres"]
        cur["genre_directions"] = [g] if isinstance(g, str) else list(g)
    cur["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    paths.write_json(ws / "brief.json", cur)
    return {"ok": True, "brief": cur, "detail": "灵感已保存"}


# ---------------------------------------------------------------------------
# 组装给模型的输入（从已有产物里取）
# ---------------------------------------------------------------------------
def _idea_fallback(brief: dict) -> str:
    """没有 `idea` 字段时，用「片名 + 题材方向」拼一句。

    为什么不一味报错：老项目的 brief.json 是旧结构（title / genre_directions），
    它表达的就是同一件事。要求用户把已经写在标题里的东西再手打一遍，
    只会让人以为工具不认自己的数据。
    """
    b = brief or {}
    bits = [str(b.get("title") or "").strip()]
    g = b.get("genre_directions") or []
    if isinstance(g, str):
        g = [g]
    if g:
        bits.append("、".join(str(x).strip() for x in g if str(x).strip()))
    if b.get("audience"):
        bits.append("面向 " + str(b["audience"]).strip())
    return "；".join(x for x in bits if x)


def _excerpt(text: str, limit: int = 12000) -> str:
    """截断过长的上下文。留着开头比截中间好 —— 章节结构都在开头。"""
    t = text or ""
    if len(t) <= limit:
        return t
    return t[:limit] + "\n\n…（以下省略 %d 字）" % (len(t) - limit)


def vars_for(ws, purpose: str, extra: dict | None = None) -> dict:
    """按用途组装 gateway 需要的 variables。缺就抛，并说清缺什么。"""
    from . import skills as SKILLS

    ws = Path(str(ws))
    extra = extra or {}
    style = ""
    try:
        pj = paths.read_json(ws / "project.json", default=None) or {}
        style = ((pj.get("meta") or {}).get("style_lock") or "").strip()
    except Exception:                                        # noqa: BLE001
        style = ""
    if not style:
        raise ValueError("本项目还没定画风（project.json 的 style_lock 为空）："
                         "先到「系统设置」选一个画风，再生成 —— 画风由项目定，不由 Skill 定")
    skill_prompt = SKILLS.compose_prompt(ws, style_lock=style)

    brief = paths.read_json(ws / "brief.json", default=None) or {}
    idea = str(extra.get("idea") or brief.get("idea") or _idea_fallback(brief)).strip()
    plan_text = read(ws, "plan")["text"]

    v = {"skill_prompt": _excerpt(skill_prompt, 20000), "style_lock": style}
    if purpose == "create.plan":
        if not idea:
            raise ValueError("还没写灵感：先在上面填一句话（一句话就够，不要写大纲）")
        v.update({"idea": idea,
                  "episodes": extra.get("episodes") or brief.get("ep_total") or 30,
                  "seconds": extra.get("seconds") or 60})
    elif purpose == "create.assets":
        if not plan_text.strip():
            raise ValueError("还没有企划案：先生成「企划案」，资产库是从它拆出来的")
        v["plan"] = _excerpt(plan_text)
    elif purpose == "create.script":
        if not plan_text.strip():
            raise ValueError("还没有企划案：先生成「企划案」")
        v.update({"plan": _excerpt(plan_text),
                  "episodes_range": str(extra.get("episodes_range") or "1-3")})
    elif purpose == "create.director":
        assets_text = read(ws, "assets")["text"]
        if not assets_text.strip():
            raise ValueError("还没有资产库：导演手册要引用资产代号（P01/S01/D01）")
        v.update({"assets": _excerpt(assets_text),
                  "script_ep": _excerpt(str(extra.get("script_ep") or ""), 12000)})
        if not str(extra.get("script_ep") or "").strip():
            raise ValueError("还没指定要拆哪一集的剧本：把那一集的剧本贴进来，或先在「分集剧本」里生成")
    return v
