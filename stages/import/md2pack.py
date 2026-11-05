#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""md2pack.py —— 把创作层产物（资产库 / 导演手册）机械转成引擎制作包

**它不创作**：不改台词、不改提示词、不补写、不翻译。只做三件事：
识别（structure）→ 映射（字段）→ 报缺（report）。

为什么需要它
------------
模板（Skill）产出的是**人读的 Markdown**，引擎吃的是 **pack JSON**（`solodrama-pack/1`）。
这中间以前只有一份「给大模型看的提示词」（`prompts/convert_to_pack.md`），没有确定性代码：
每次转换结果都不一样，出错也说不清是哪一步。本文件把「机械可判」的部分固定下来。

三条硬规则
----------
1. **没提示词就不出条目**：宁可少一条并在报告里点名，也不要拿别的卡的提示词顶上。
2. **台词按名字认人**：手册写「崔昭：…」，引擎只认 `P01`。对不上就丢，并记 `DLG-UNMAPPED`。
3. **不完整的镜头不写进 pack**：缺 A 段或 B 段（常见于输出被截断）→ 跳过 + 报告，
   否则导入会被 `SHOT015` 阻断，而错误信息指不到「截断」这个真因。

用法
----
    python stages/import/md2pack.py --workspace <剧目录> [--out <dir>] [--ep 1] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
for p in (HERE, HERE.parents[1] / "production" / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import pack_spec as S  # noqa: E402

ID_RE = re.compile(r"\b(P\d{2}|S\d{2}|D\d{2}|FX\d{2})\b")
FENCE = re.compile(r"```[a-zA-Z]*\n(.*?)\n```", re.S)
H3_SHOT = re.compile(r"^###\s*镜\s*(\d+)\s*$", re.M)
LOOK_ROW = re.compile(r"^\|\s*(LOOK-[A-Z0-9]+)\s*\|\s*([^|]*)\|", re.M)

KIND_OF_PREFIX = {"P": "character", "S": "scene", "D": "prop", "F": "effect"}
ASSET_FILE = {"character": "characters.json", "scene": "scenes.json", "prop": "props.json"}


# ---------------------------------------------------------------------------
# 资产库
# ---------------------------------------------------------------------------
def _blocks(text: str):
    """按 `### <代号> …` 切块。兼容 `P01 名称` 与 `P01｜名称` 两种写法。"""
    out, cur = [], None
    for line in text.splitlines():
        m = re.match(r"^###\s+(.+)$", line)
        if m:
            hit = ID_RE.search(m.group(1))
            if hit:
                cur = {"id": hit.group(1), "head": m.group(1), "lines": []}
                out.append(cur)
            else:
                cur = None
            continue
        if cur is not None:
            cur["lines"].append(line)
    return out


def _field(body: str, *names) -> str:
    for n in names:
        m = re.search(r"\|\s*%s\s*\|\s*([^|]+)\|" % re.escape(n), body)
        if m:
            return m.group(1).strip()
    return ""


def _fence_after(body: str, *labels) -> str:
    """取「某个标签之后的第一段围栏」。标签如 三视图 / 表情 / 服装卡提示词。"""
    for lb in labels:
        m = re.search(re.escape(lb) + r"[^\n]*\n[\s\S]{0,400}?```[a-zA-Z]*\n(.*?)\n```", body)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return ""


def _name_of(head: str) -> str:
    h = head
    for sep in ("｜", "|", " "):
        if sep in h:
            h = h.split(sep, 1)[1]
            break
    return re.sub(r"[（(].*?[)）]", "", h).strip() or head.strip()


def parse_assets(text: str) -> tuple:
    """→ (assets_by_kind, gaps)

    assets_by_kind: {"character": [{id,name,role,anchors,variants:[{code,label,kind,prompt}]}]}
    gaps: [{id, code, reason}] —— 只记「本该有但拿不到提示词」的项
    """
    out = {"character": [], "scene": [], "prop": [], "effect": []}
    gaps = []
    for b in _blocks(text):
        body = "\n".join(b["lines"])
        aid = b["id"]
        kind = KIND_OF_PREFIX.get(aid[0], "prop")
        if kind == "effect":
            continue                      # 特效层不进首批出图（没有独立资产卡）
        looks = LOOK_ROW.findall(body)
        variants = []

        turnaround = _fence_after(body, "三视图", "turnaround")
        if turnaround:
            variants.append({"code": "VIEW", "label": "三视图",
                             "kind": "turnaround", "prompt": turnaround})
        expr = _fence_after(body, "表情四态", "表情")
        if expr:
            variants.append({"code": "EXP", "label": "表情四态",
                             "kind": "expression", "prompt": expr})
        # 逐个造型的提示词：模板的写法不统一 —— 有的是「服装卡提示词」一段，
        # 有的是 `**LOOK-A 立绘提示词**` / `**LOOK-D 状态卡提示词**` 一段一条。
        # 这里两种都认，只产出**真有提示词**的那些；其余记进 gaps，不套用别人的提示词。
        single = _fence_after(body, "服装卡提示词")
        if single and looks:
            code, label = looks[0][0], (looks[0][1] or "").strip()
            variants.append({"code": code, "label": label or code,
                             "kind": "look", "prompt": single})
        for code, label in looks:
            if any(v["code"] == code for v in variants):
                continue
            m = re.search(r"\*\*[^*\n]*" + re.escape(code) + r"[^*\n]*\*\*[\s\S]{0,200}?"
                          r"```[a-zA-Z]*\n(.*?)\n```", body)
            if not m or len(m.group(1).strip()) < 40:
                gaps.append({"id": aid, "code": code,
                             "reason": "模板没给这条造型的提示词（需按服装描述补写）"})
                continue
            lb = (label or "").strip()
            mk = re.search(r"\*\*([^*\n]*" + re.escape(code) + r"[^*\n]*)\*\*", body)
            head = mk.group(1) if mk else ""
            variants.append({"code": code, "label": lb or code,
                             "kind": "state" if "状态" in head else "look",
                             "prompt": m.group(1).strip()})
        if not variants:
            # 没有分层标签时，退回「第一段围栏」= 主卡/空景卡
            fences = [f.strip() for f in FENCE.findall(body) if len(f.strip()) > 40]
            if fences:
                variants.append({"code": "BASE", "label": "主卡",
                                 "kind": "base", "prompt": fences[0]})
            else:
                gaps.append({"id": aid, "code": "BASE", "reason": "整块没有任何提示词围栏"})
                continue
        out[kind].append({
            "id": aid, "name": _name_of(b["head"]),
            "role": _field(body, "身份", "用途", "设定"),
            "anchors": [x.strip() for x in re.split(r"[①②③④⑤、；;]", _field(body, "一致性锚点", "锚点"))
                        if x.strip()][:6],
            "variants": variants,
        })
    return out, gaps


# ---------------------------------------------------------------------------
# 导演手册
# ---------------------------------------------------------------------------
def _timeline(md: str) -> dict:
    """读时间轴表：| 镜号 | 镜头名 | 时间 | 时长 | …"""
    out = {}
    for line in md.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4 or not cells[0].isdigit():
            continue
        m = re.search(r"(\d+(?:\.\d+)?)\s*s", cells[3])
        if m:
            out[cells[0]] = {"title": cells[1], "duration": float(m.group(1))}
    return out


def _cast_of(body: str) -> list:
    """参考图行 → cast（顺序即上传顺序，必须与 {{Mixed n}} 一致）。"""
    m = re.search(r"\*\*参考图\*\*[：:]\s*(.+)", body)
    if not m:
        return []
    cast = []
    for seg in re.split(r"[｜|]", m.group(1)):
        hit = ID_RE.search(seg)
        if not hit:
            continue
        code = "BASE"
        vm = re.search(r"(LOOK-[A-Z0-9]+)", seg)
        if vm:
            code = vm.group(1)
        elif "三视图" in seg:
            code = "VIEW"
        cast.append({"asset": hit.group(1), "variant": code})
    return cast


def _dialogue(body: str, name2id: dict, cast: list) -> tuple:
    """台词 → [{asset,text,start,end}]；认不出人就丢，并回报。"""
    m = re.search(r"\*\*台词\*\*[：:]\s*([\s\S]*?)(?:\n\*\*|\n###|\Z)", body)
    if not m:
        return [], []
    out, dropped = [], []
    cast_ids = {c["asset"] for c in cast}
    t = 0.3
    for line in m.group(1).splitlines():
        mm = re.match(r"\s*([^\s：:（(]{1,12})(?:[（(][^）)]*[)）])?[：:]\s*(.+)", line)
        if not mm:
            continue
        who, text = mm.group(1).strip(), mm.group(2).strip()
        aid = name2id.get(who) or next((v for k, v in name2id.items() if k and k in who), "")
        if not aid:
            dropped.append({"who": who, "text": text, "reason": "名字对不上任何资产"})
            continue
        if aid not in cast_ids:
            dropped.append({"who": who, "text": text,
                            "reason": "该角色不在本镜参考图里（cast 没有 %s）" % aid})
            continue
        dur = max(0.8, len(text) / 4.0)
        out.append({"asset": aid, "text": text, "start": round(t, 1), "end": round(t + dur, 1)})
        t = round(t + dur + 0.2, 1)
    return out, dropped


def _strip_dropped(text: str, dropped_ids, allowed: int) -> str:
    """摘掉「被丢弃的参考图」相关行：按代号命中，以及越界的 `{{Mixed n}}`。

    只在「参考图被丢弃」时用。两个判据都要，缺一种就会漏：
      · 按代号：`场景 S09 的参考图是 {{Mixed 2}}` 这行即使图号合法，也指向一张不存在的图；
      · 按图号：有的模板只写 `{{Mixed 3}}`，不写代号。
    """
    ids = {str(x) for x in (dropped_ids or [])}
    out = []
    for line in str(text or "").splitlines():
        if ids and any(re.search(r"\b%s\b" % re.escape(i), line) for i in ids):
            continue
        nums = [int(x) for x in re.findall(r"\{\{Mixed\s*(\d+)\}\}", line)]
        if nums and max(nums) > allowed:
            continue
        out.append(line)
    txt = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", txt).strip()


def parse_episode(md: str, ep: int, ratio: str, name2id: dict,
                  known: set | None = None, strict_cast: bool = True,
                  variants_of: dict | None = None) -> tuple:
    """→ (episode_dict, gaps)。缺 A/B 段的镜头跳过并记入 gaps。"""
    timeline = _timeline(md)
    chunks = H3_SHOT.split(md)
    shots, gaps = [], []
    for i in range(1, len(chunks) - 1, 2):
        no, body = chunks[i], chunks[i + 1]
        sid = "shot_%03d" % int(no)
        a = re.search(r"\*\*A段[：:][^*]*\*\*\s*```[a-zA-Z]*\n(.*?)\n```", body, re.S)
        b = re.search(r"\*\*B段[：:][^*]*\*\*\s*```[a-zA-Z]*\n(.*?)\n```", body, re.S)
        if not (a and b):
            gaps.append({"shot": sid, "reason": "缺 A/B 段提示词（常见于输出被截断）"})
            continue
        dur = timeline.get(no, {}).get("duration")
        if dur is None:
            m = re.search(r"\*\*时长\*\*[：:]\s*(\d+(?:\.\d+)?)\s*s", body)
            dur = float(m.group(1)) if m else 0
        if not (4 <= dur <= 15):
            gaps.append({"shot": sid, "reason": "时长 %.0fs 超出 4–15 秒" % dur})
            continue
        cast = _cast_of(body)
        dropped_cast = []
        if known is not None and not strict_cast:
            # 参考图引用了 pack 里没有的资产（典型：资产库只出了人物批）：
            # 留着会让导入直接阻断（SHOT010），丢掉只降低一致性 —— 后者能跑，前者不能。
            # 但必须逐条记进报告，并把提示词里对应的 {{Mixed n}} 一起摘掉（见下）。
            keep = []
            for c in cast:
                (keep if c["asset"] in known else dropped_cast).append(c)
            if dropped_cast:
                gaps.append({"shot": sid,
                             "reason": "参考图缺资产，已从 cast 移除：%s"
                                       % "、".join(c["asset"] for c in dropped_cast)})
            cast = keep
        if variants_of:
            # 镜头点名 LOOK-B，而资产库只给了三视图：不能直接阻断（SHOT011），
            # 回落到该资产**实际有的第一个变体**，并记进报告 —— 画面会少一层造型区分，
            # 但链路能跑；这比「整包导入不了」更接近用户想要的结果。
            fixed = []
            for c in cast:
                have = variants_of.get(c["asset"]) or []
                if have and c["variant"] not in have:
                    gaps.append({"shot": sid, "reason": "%s 没有 %s，回落 %s"
                                 % (c["asset"], c["variant"], have[0])})
                    c = dict(c, variant=have[0])
                fixed.append(c)
            cast = fixed
        dlg, dropped = _dialogue(body, name2id, cast)
        for d in dropped:
            gaps.append({"shot": sid, "reason": "台词未采用：%s（%s）" % (d["text"][:12], d["reason"])})
        vp = b.group(1).strip()
        if dropped_cast:
            # 丢了参考图就必须把对应挂载点一起摘掉：留着既过不了 SHOT016，
            # 真出片时模型也在等一张没上传的图。allowed 按**实际 cast 数**算（分镜图不进 Mixed）。
            vp = _strip_dropped(vp, [c["asset"] for c in dropped_cast], len(cast))
        shots.append({
            "id": sid, "duration": int(round(dur)), "ratio": ratio,
            "cast": cast,
            "board_prompt": a.group(1).strip(),
            "video_prompt": vp,
            "dialogue": dlg,
        })
    total = sum(s["duration"] for s in shots)
    return {"spec": "solodrama-episode/1", "episode": ep, "title": "第%02d集" % ep,
            "duration_total": total, "shots": shots}, gaps


# ---------------------------------------------------------------------------
# 组装
# ---------------------------------------------------------------------------
def _all_ids(assets: dict) -> set:
    return {it["id"] for bucket in assets.values() for it in bucket}


def _name_map(assets: dict) -> dict:
    """名字 → 代号。台词里只会出现名字。"""
    out = {}
    for bucket in assets.values():
        for it in bucket:
            nm = str(it.get("name") or "").strip()
            if nm:
                out[nm] = it["id"]
                out.setdefault(nm.replace(" ", ""), it["id"])
    return out


def convert(ws, *, out_dir=None, eps=None, title="", slug="", style_lock="",
            strict_cast: bool = True) -> dict:
    ws = pathlib.Path(ws)
    src = ws / "00-创作"
    assets_md = src / "02-资产库.md"
    if not assets_md.is_file():
        raise SystemExit("[FAIL] 没有 %s —— 先写资产库" % assets_md)
    assets, asset_gaps = parse_assets(assets_md.read_text(encoding="utf-8", errors="replace"))

    # 项目元信息
    meta = {}
    pj = ws / "project.json"
    if pj.is_file():
        try:
            meta = (json.loads(pj.read_text(encoding="utf-8-sig")).get("meta") or {})
        except (OSError, ValueError):
            meta = {}
    style = style_lock or str(meta.get("style_lock") or "")

    pack_dir = pathlib.Path(out_dir) if out_dir else (ws / "pack")
    (pack_dir / "assets").mkdir(parents=True, exist_ok=True)
    (pack_dir / "episodes").mkdir(parents=True, exist_ok=True)

    pack = {
        "spec": "solodrama-pack/1",
        "title": title or meta.get("title") or ws.name,
        "slug": slug or meta.get("slug") or re.sub(r"[^a-z0-9-]+", "-", ws.name.lower()),
        "logline": "",
        "skill": {"name": meta.get("skill") or "", "version": "2026-11-05"},
        "delivery": {"width": 1080, "height": 1920, "fps": 24,
                     "episode_count": int(meta.get("total_ep") or 1),
                     "target_duration": int(meta.get("ep_seconds") or 60)},
        "style_lock": style,
        "negative": "text, watermark, extra fingers, distorted face",
        "aspect": {"character": "16:9", "scene": "16:9", "prop": "1:1",
                   "board": "9:16", "video": "9:16"},
    }
    (pack_dir / "pack.json").write_text(json.dumps(pack, ensure_ascii=False, indent=2),
                                        encoding="utf-8", newline="")
    for kind, fname in ASSET_FILE.items():
        (pack_dir / "assets" / fname).write_text(json.dumps({
            "spec": "solodrama-assets/1", "kind": kind, "items": assets.get(kind) or [],
        }, ensure_ascii=False, indent=2), encoding="utf-8", newline="")

    name2id = _name_map(assets)
    dir_dir = src / "04-导演手册"
    ep_gaps, written = [], []
    # ⚠ 排除 `.bak_时间戳.md`：它和正式文件同后缀，混进来会被当成「另一集」，
    #   于是同一集被写两遍（后一个覆盖前一个），而且分集数翻倍（2026-11-05 实测撞到）。
    for f in sorted(x for x in dir_dir.glob("*.md") if ".bak_" not in x.name)             if dir_dir.is_dir() else []:
        m = re.search(r"第\s*(\d+)\s*集", f.name)
        idx = int(m.group(1)) if m else 0
        if not idx:
            continue
        if eps and idx not in eps:
            continue
        doc, gaps = parse_episode(f.read_text(encoding="utf-8", errors="replace"),
                                  idx, pack["aspect"]["video"], name2id,
                                  known=_all_ids(assets),
                                  strict_cast=strict_cast,
                                  variants_of={it["id"]: [v["code"] for v in it["variants"]]
                                               for bucket in assets.values() for it in bucket})
        if not doc["shots"]:
            ep_gaps.append({"file": f.name, "reason": "没解析到任何完整镜头"})
            continue
        (pack_dir / "episodes" / ("ep%02d.json" % idx)).write_text(
            json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8", newline="")
        written.append((idx, len(doc["shots"]), doc["duration_total"]))
        ep_gaps += [dict(g, file=f.name) for g in gaps]

    # 校验（与导入同一条判据）：load_pack 不抛异常，问题都在 report 里
    _pack, _assets, _episodes, rep = S.load_pack(pack_dir)

    lines = ["# 转换报告（md2pack）", "",
             "源：`%s`" % assets_md, "输出：`%s`" % pack_dir, ""]
    for kind, bucket in assets.items():
        if bucket:
            lines.append("- %s：%d 条（%s）" % (
                kind, len(bucket),
                "、".join("%s(%d变体)" % (b["id"], len(b["variants"])) for b in bucket)))
    if written:
        lines.append("- 分集：" + "、".join("ep%02d(%d镜/%ds)" % w for w in written))
    if asset_gaps:
        lines += ["", "## 资产缺口（%d）" % len(asset_gaps), ""]
        lines += ["- %s / %s：%s" % (g["id"], g["code"], g["reason"]) for g in asset_gaps]
    if ep_gaps:
        lines += ["", "## 分镜缺口（%d）" % len(ep_gaps), ""]
        lines += ["- %s %s：%s" % (g.get("file", ""), g.get("shot", ""), g["reason"]) for g in ep_gaps]
    if not rep.ok:
        lines += ["", "## 校验未通过（阻断）", "", "```", rep.render().strip(), "```"]
    (pack_dir / "_import_report.md").write_text("\n".join(lines) + "\n",
                                                encoding="utf-8", newline="")
    return {"ok": True, "pack": str(pack_dir), "assets": {k: len(v) for k, v in assets.items()},
            "episodes": written, "asset_gaps": asset_gaps, "ep_gaps": ep_gaps,
            "report": str(pack_dir / "_import_report.md")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="创作层 Markdown → 引擎制作包（机械转换，不创作）")
    ap.add_argument("--workspace", default=None, help="剧目录（含 00-创作/）")
    ap.add_argument("--out", default=None, help="输出目录（默认 <workspace>/pack）")
    ap.add_argument("--ep", default="", help="只转这些集（逗号分隔，如 1,2）")
    ap.add_argument("--drop-missing-cast", action="store_true",
                    help="资产库还没补齐时，把缺失的参考图从 cast 移除（会连 {{Mixed n}} 一起摘）")
    ap.add_argument("--dry-run", action="store_true", help="只解析并报告，不写文件")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    # 与其它引擎脚本一致：参数 > 环境变量（Studio 的 runner 会注入 workspace）
    ws = (a.workspace or os.environ.get("SOLODRAMA_WORKSPACE")
          or os.environ.get("DRAMA_WORKSPACE") or "")
    if not ws:
        print("[FAIL] 需要 --workspace（剧目录），或设 SOLODRAMA_WORKSPACE")
        return 2
    if a.dry_run:
        src = pathlib.Path(ws) / "00-创作" / "02-资产库.md"
        if not src.is_file():
            print("[FAIL] 没有 %s" % src)
            return 2
        assets, gaps = parse_assets(src.read_text(encoding="utf-8", errors="replace"))
        n = sum(len(v) for v in assets.values())
        print("识别资产：%d 条（%s）" % (n, "、".join("%s %d" % (k, len(v)) for k, v in assets.items() if v)))
        for g in gaps:
            print("  [缺] %s / %s：%s" % (g["id"], g["code"], g["reason"]))
        return 0

    eps = [int(x) for x in re.split(r"[,\s]+", a.ep) if x.strip().isdigit()] or None
    res = convert(ws, out_dir=a.out, eps=eps,
                  strict_cast=not a.drop_missing_cast)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    print("输出：%s" % res["pack"])
    print("资产：%s" % "、".join("%s %d" % kv for kv in res["assets"].items() if kv[1]))
    if res["episodes"]:
        print("分集：%s" % "、".join("ep%02d(%d镜/%ds)" % e for e in res["episodes"]))
    if res["asset_gaps"]:
        print("资产缺口 %d 项（见报告）" % len(res["asset_gaps"]))
    if res["ep_gaps"]:
        print("分镜缺口 %d 项（见报告）" % len(res["ep_gaps"]))
    print("报告：%s" % res["report"])
    return 0 if res["episodes"] else 1


if __name__ == "__main__":
    sys.exit(main())
