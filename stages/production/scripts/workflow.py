#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""workflow.py —— 短剧标准作业流程（11 环节）的**唯一真源**

为什么要有它
------------
2026-10-20 / 10-21 两轮实跑暴露的最大浪费不是「某个脚本报错」，而是**顺序失控**：
先出了图才发现画风锁错、先提交了任务才发现提示词没转换、先烧了字幕才发现没放大。
同类事故反复出现，根因是同一条：**流程只写在文档里，没有可执行的机器判据**。

本模块把用户验收过的执行框架固化为 11 个环节，每环节给出：
  * `kind`     —— agent（须产出内容）/ auto（有脚本可全自动）/ gate（只校验）
  * `dir`      —— 产物落点（`stages/_layout.py` 的阶段键）
  * `probes`   —— **完成判据**（产物存在性 + 最少条数；可动态取集数/镜数）
  * `commands` —— 该环节的标准命令（可直接抄）
  * `requires` —— 前置环节（严格按序，除非显式 `--skip` 并留痕）

11 环节（顺序不可调，用户的执行框架）
------------------------------------
  S1 调研 → S2 剧本 → S3 资产设计 → S4 资产生成 → S5 视频提示词 → S6 视频生成
  → S7 发行资料准备（可选，可延后到 S11 前）→ S8 视频拼接 → S9 视频放大
  → S10 字幕烧录 → S11 定稿输出

命令
----
    python workflow.py list                        打印 11 环节表
    python workflow.py status [--json]             各环节完成情况 + 当前应做哪一环
    python workflow.py next                        只输出下一个待办环节（脚本友好）
    python workflow.py check --stage S6            前置环节是否全部完成（未过退出码 4）
    python workflow.py done S3 --note "..."        手工登记（只对 agent/gate 环节；auto 环节以产物为准）
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
import _layout as L                                              # noqa: E402

EXIT_ORDER_VIOLATION = 4          # 与画风/通道门禁同一口径：4 = 停在这里，等人处理
STATE_NAME = "workflow-state.json"

# ---------------------------------------------------------------------------
# 11 环节定义（唯一真源；改这里即改全链路）
# ---------------------------------------------------------------------------
STAGES: list = [
    {
        "id": "S1", "name": "调研", "dir": "research", "kind": "agent",
        "what": "榜单调研 → 爆款拆解 → 多市场对比，产出可支撑选题的事实依据",
        "probes": [{"label": "市场数据", "glob": "market-data.json", "min": 1}],
        "commands": [
            "python stages/creation/scripts/creation.py --workspace <ws> market",
            "python stages/creation/scripts/creation.py --workspace <ws> breakdown",
            "python stages/creation/scripts/creation.py --workspace <ws> hit（多市场对比/选题候选）",
        ],
        "note": "调研结论必须落结构化 JSON（后续选题评分要读），不要只写散文。",
    },
    {
        "id": "S2", "name": "剧本", "dir": "script", "kind": "agent",
        "what": "选题定位（七维评分）→ 四段法（诊断/骨架/正文/观众七问）→ 逐集 FFS",
        "probes": [
            {"label": "定位卡", "stage": "topic", "glob": "positioning.json", "min": 1},
            {"label": "集数规划", "glob": "blueprint.json", "min": 1},
            {"label": "单集剧本", "glob": "ep_*.md", "min": "episodes"},
        ],
        "commands": [
            "python stages/creation/scripts/creation.py --workspace <ws> topic（七维评分 → 定位卡）",
            "python stages/creation/scripts/script_rewrite.py --workspace <ws> diagnose → plan → review",
            "python stages/creation/scripts/script_rewrite.py --workspace <ws> audience --check（观众七问）",
            "python tools/cli.py check --workspace <ws>（FFS 结构自检）",
        ],
        "note": "剧本是唯一事实源；台词、代号、镜号、时长五项锚从这里往下传，改一处罚两处。",
    },
    {
        "id": "S3", "name": "资产设计", "dir": "assets", "kind": "agent",
        "what": "先跑角色差异化 plan（禁逐角色自由手写长相），再产资产卡与出图提示词",
        "probes": [
            {"label": "角色圣经", "glob": "design/character-bible.json", "min": 1},
            {"label": "出图提示词", "glob": "design/prompts/**/*.txt", "min": 1},
        ],
        "commands": [
            "python stages/assets/scripts/character_design.py plan --workspace <ws> --roster <roster.json> --out 04-资产/design",
            "python stages/assets/scripts/character_design.py check --workspace <ws> --bible 04-资产/design/character-bible.json",
            "python stages/assets/scripts/asset_md.py --workspace <ws>（资产卡 → 出图提示词，含英文 garment_en）",
        ],
        "note": "画风锁之后、任何一张图之前。出图后改骨相 = 已产出素材全部作废。",
    },
    {
        "id": "S4", "name": "资产生成", "dir": "assets", "kind": "auto",
        "what": "按确认的通道出图（人/场/道），并接线参考图",
        "probes": [
            {"label": "人物/场景图", "glob": "{characters,scenes,props}/*.{png,jpg,jpeg}", "min": 1},
            {"label": "参考图登记", "glob": "refs.json", "min": 1},
        ],
        "commands": [
            "drama.py assets --engine <local|rh> --submit",
            "drama.py refs --apply --write-config（长边 >5760 必须瘦身）",
        ],
        "note": "一剧一种子：同剧所有资产共用一个 render_seed，否则质感各不相同。",
    },
    {
        "id": "S5", "name": "视频提示词", "dir": "prompts", "kind": "agent",
        "what": "分镜（11 字段）→ H3 六段式提示词 → 转换四文件 → 入门口禁",
        "probes": [
            {"label": "分镜脚本", "stage": "storyboard", "glob": "**/*.md", "min": 1},
            # ★ 用布局真源 `_layout.data_dir()` 而不是硬拼 `06-提示词/data`：
            #   反馈 9.1 的根因就是「三个脚本三个目录」——`convert_storyboard` 写的是
            #   `data_dir()` 解析结果（老项目可能就指 `06-提示词/` 根）。硬拼 `data/` 会把
            #   已经把四文件写在根目录的项目误判成「未生成」。
            {"label": "data/shots.json", "base": "data", "glob": "shots.json", "min": 1},
            {"label": "data/h3_prompts.json", "base": "data", "glob": "h3_prompts.json", "min": 1},
        ],
        "commands": [
            "convert_storyboard.py --workspace <ws> --apply",
            "ingest_check.py --workspace <ws> --ep epNN",
            "script_continuity.py --workspace <ws> --all（五锚：镜号/台词/人物/时长/节点）",
        ],
        "note": "G7 入门口禁必须过：任何提示词错误都要挡在计费之前。",
    },
    {
        "id": "S6", "name": "视频生成", "dir": "film", "kind": "auto",
        "what": "按确认的视频通道批量出片（★计费）；失败一律 --resume 续跑，不重提",
        "probes": [
            {"label": "分段成片", "glob": "**/final.mp4", "min": "shots", "count": "parent"},
        ],
        "commands": [
            "drama.py video plan（免费预估）",
            "drama.py video run --yes --concurrency 2（先 --limit 1 出小样）",
            "drama.py video run --yes --resume <批次>（续跑不重复扣费）",
        ],
        "note": "并发实测建议 2：标称 ≤5，实际 5 会 421 排队。"
                "判据按**镜头**去重（count=parent）：同一镜在多个批次里各有 final.mp4 只算一个，"
                "否则返工留下的旧批次会把缺口盖住。",
    },
    {
        "id": "S7", "name": "发行资料准备", "dir": "release", "kind": "agent",
        "optional": True,
        "what": "封面（多尺寸·抓马六抓手）· 文案 · 发布清单 · 版权资料（4+4）",
        "probes": [
            {"label": "封面", "glob": "封面/*.{png,jpg,jpeg}", "min": 1},
            {"label": "文案", "glob": "文案/*", "min": 1},
            {"label": "发布清单", "glob": "*发布清单*", "min": 1},
            {"label": "版权资料", "glob": "版权资料/*.{png,jpg,jpeg}", "min": 8},
        ],
        "commands": [
            "cover_prompt.py（AI 直出带字，主路径）→ 出图通道",
            "release_check.py --workspace <ws> --material-only（连载期增量验收）",
        ],
        "note": "可选环节：可在 S6 之后任意时刻做，但 S11 之前必须齐（发行门禁会拦）。",
    },
    {
        "id": "S8", "name": "视频拼接", "dir": "film", "kind": "auto",
        "what": "逐段成片按镜序无损拼接成整集母版",
        "probes": [
            {"label": "整集母版", "glob": "**/*_master.mp4", "min": "episodes"},
        ],
        "commands": ["subtitle.py --workspace <ws> --ep epNN --stage master"],
        "note": "母版逐段加 120ms 音频淡入淡出（audio.edge_fade_ms 可关）。",
    },
    {
        "id": "S9", "name": "视频放大", "dir": "film", "kind": "auto",
        "what": "竖屏 1080P 交付硬要求：源 0.8MP 必须超分（Topaz tvai_up）",
        "probes": [
            {"label": "放大母版", "glob": "**/*_master_[0-9]*x[0-9]*.mp4", "min": "episodes",
             "alt": ["**/*_master_2k.mp4", "**/*1080p*.mp4", "**/*_up*.mp4"]},
        ],
        "commands": ["subtitle.py --workspace <ws> --ep epNN --stage upscale"],
        "note": "正名是 `<ep>_master_<W>x<H>.mp4`（竖屏 1080P → _master_1080x1920.mp4）；"
                "旧名 `_master_2k.mp4` 仍识别（老项目不迁移）。"
                "源比例 ≠ 目标比例时先按高度放大再上下对称裁，别直接拉伸（会横向变形）。",
    },
    {
        "id": "S10", "name": "音频与字幕", "dir": "film", "kind": "auto",
        "what": "BGM 混音（有铺排计划时）→ 字幕烧录；字幕时间必须走 ASR 校时",
        "probes": [
            {"label": "字幕成片", "glob": "**/*_subbed.mp4", "min": "episodes",
             "alt": ["**/*_sub.mp4", "**/*softsub*.mp4"]},
        ],
        "commands": [
            "drama.py bgm plan --ep epNN --apply（情绪→增益/淡入淡出→ducking）",
            "drama.py bgm check --ep epNN（版权/覆盖/增益门禁）",
            "subtitle.py --workspace <ws> --ep epNN --stage align"
            "（真对齐：CTC + whisper 校时；估算档会自动重建）",
            "subtitle.py --workspace <ws> --ep epNN --stage render（会自动混 BGM 并烧字幕）",
        ],
        "note": "分工写死：画面与同期声归 H3（提示词里显式禁配乐），BGM 归后期。"
                "字幕时间必须来自真对齐（report 的 align_methods 里不许留 script_estimate）；"
                "渲染完按「帧数与底片一致 + 渲染自检检出字幕带」判成功，不看退出码。",
    },
    {
        "id": "S11", "name": "定稿输出", "dir": "release", "kind": "auto",
        "what": "导出发布版 EpisodeNN.mp4 到 09-发行/剧集/，并过发行齐备度门禁",
        "probes": [
            {"label": "发布版剧集", "stage": "release", "glob": "剧集/Episode*.mp4", "min": "episodes"},
        ],
        "commands": [
            "release_export.py --workspace <ws> --all --apply",
            "release_check.py --workspace <ws>",
        ],
        "note": "发布版命名严格 EpisodeNN.mp4；同集多版本取 mtime 最新，不猜。",
    },
]

STAGE_IDS = [s["id"] for s in STAGES]
BY_ID = {s["id"]: s for s in STAGES}
KIND_LABELS = {"agent": "内容", "auto": "自动", "gate": "校验"}


# ---------------------------------------------------------------------------
def _now() -> str:
    return _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def _stage_dir(ws: pathlib.Path, key: str) -> pathlib.Path:
    return L.stage_dir(ws, key)


def _count_episodes(ws: pathlib.Path) -> int:
    """集数：project-setup → project.json → 03-剧本 里 ep_*.md 的数量。"""
    for fname, keys in (("project-setup.json", ("episodes", "count")),
                        ("project.json", ("total_ep",)),
                        ("creation-brief.json", ("episodes", "total"))):
        p = pathlib.Path(ws) / fname
        if not p.is_file():
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        cur = d
        for k in keys:
            if isinstance(cur, dict):
                cur = cur.get(k)
            else:
                cur = None
                break
        try:
            if int(cur) > 0:
                return int(cur)
        except (TypeError, ValueError):
            pass
    try:
        n = len(list(_stage_dir(ws, "script").glob("ep_*.md")))
    except Exception:                                            # noqa: BLE001
        n = 0
    return n or 0


def _count_shots(ws: pathlib.Path) -> int:
    """镜头数：06-提示词/data/shots.json 的条数。"""
    p = _stage_dir(ws, "prompts") / "data" / "shots.json"
    if not p.is_file():
        p = L.data_dir(ws) / "shots.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8-sig"))
        return len(d) if isinstance(d, list) else 0
    except (OSError, json.JSONDecodeError, ValueError):
        return 0


def _resolve_min(spec, ctx: dict) -> int:
    if isinstance(spec, int):
        return spec
    if spec == "episodes":
        return max(1, ctx.get("episodes") or 1)
    if spec == "shots":
        return max(1, ctx.get("shots") or 1)
    return 1


def _expand_braces(pat: str) -> list:
    """把 `{characters,scenes}` 展开成多条 —— pathlib.glob **不支持**花括号（那是 shell 语法）。

    ★ 2026-10-21：不展开就会静默返回 0 个文件，判据永远「未完成」，且很难看出是语法问题。
    """
    import re as _re
    m = _re.search(r"\{([^{}]*)\}", pat)
    if not m:
        return [pat]
    out = []
    for opt in m.group(1).split(","):
        out.extend(_expand_braces(pat[:m.start()] + opt.strip() + pat[m.end():]))
    return out


def _glob_any(base: pathlib.Path, patterns: list) -> list:
    out = []
    for pat in patterns:
        for one in _expand_braces(pat):
            try:
                out.extend(base.glob(one))
            except (ValueError, OSError):
                pass
    # 去重（同一个文件可能被多个模式命中）
    seen, uniq = set(), []
    for f in out:
        k = str(f).lower()
        if k not in seen and f.is_file():
            seen.add(k)
            uniq.append(f)
    return uniq


def _probe_bases(ws: pathlib.Path, st: dict, p: dict) -> list:
    """一个判据可能对应多个候选目录（兼容历史落点差异，反馈 9.1）。"""
    out = []
    if p.get("base") == "data":
        # 出片引擎输入目录（布局真源）+ 两个常见历史落点
        try:
            out.append(L.data_dir(ws))
        except Exception:                                        # noqa: BLE001
            pass
        try:
            pd = _stage_dir(ws, "prompts")
            out += [pd, pd / "data"]
        except Exception:                                        # noqa: BLE001
            pass
    else:
        try:
            out.append(_stage_dir(ws, p.get("stage") or st["dir"]))
        except Exception:                                        # noqa: BLE001
            pass
    seen, uniq = set(), []
    for b in out:
        k = str(b).lower()
        if k not in seen:
            seen.add(k)
            uniq.append(b)
    return uniq


def probe_stage(ws: pathlib.Path, st: dict, ctx: dict) -> dict:
    """判据求值：所有 probe 都满足才算完成。返回 {done, rows[], found, need}."""
    rows, ok_all = [], True
    for p in st.get("probes", []):
        pats = [p["glob"]] + list(p.get("alt") or [])
        files = []
        bases = _probe_bases(ws, st, p)
        for b in bases:
            files += _glob_any(b, pats)
        # 去重（同一文件可能被多个候选目录/模式命中）
        seen, uniq = set(), []
        for f in files:
            k = str(f).lower()
            if k not in seen:
                seen.add(k)
                uniq.append(f)
        files = uniq
        # ★ 2026-10-22（对账）：`count: "parent"` = 按**父目录名**去重后再计数。
        #   为什么要这个：S6 的判据是「分段成片 ≥ 镜头数(240)」，而 `**/final.mp4` 会把
        #   **每个批次目录**里的同名镜头都算一遍 —— 实测本项目 240 个镜头数出 284 个文件
        #   （返工时新批次没删旧的），于是 20 个镜头没出也能"达标"。
        #   镜头是唯一单位，同一个 shot 的多份产物只算一个。
        if p.get("count") == "parent":
            seen2, uniq2 = set(), []
            for f in files:
                k = f.parent.name.lower()
                if k not in seen2:
                    seen2.add(k)
                    uniq2.append(f)
            files = uniq2
        need = _resolve_min(p.get("min", 1), ctx)
        ok = len(files) >= need
        ok_all = ok_all and ok
        rows.append({"label": p["label"], "ok": ok, "found": len(files),
                     "need": need, "dir": str(bases[0]) if bases else str(ws)})
    return {"done": ok_all, "rows": rows}


def _load_state(ws: pathlib.Path) -> dict:
    p = pathlib.Path(ws) / STATE_NAME
    if p.is_file():
        try:
            d = json.loads(p.read_text(encoding="utf-8-sig"))
            if isinstance(d, dict):
                d.setdefault("manual", {})
                d.setdefault("skipped", {})
                return d
        except (OSError, json.JSONDecodeError, ValueError):
            pass
    return {"manual": {}, "skipped": {}, "history": []}


def _save_state(ws: pathlib.Path, d: dict) -> pathlib.Path:
    p = pathlib.Path(ws) / STATE_NAME
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8", newline="")
    return p


def evaluate(ws: pathlib.Path) -> dict:
    """全部环节的完成情况 + 当前应做环节。"""
    ws = pathlib.Path(ws)
    ctx = {"episodes": _count_episodes(ws), "shots": _count_shots(ws)}
    state = _load_state(ws)
    rows = []
    for i, st in enumerate(STAGES):
        pr = probe_stage(ws, st, ctx)
        manual = state["manual"].get(st["id"]) or {}
        skipped = state["skipped"].get(st["id"]) or {}
        done = pr["done"] or bool(manual) or bool(skipped)
        rows.append({
            "id": st["id"], "name": st["name"], "kind": st["kind"],
            "optional": bool(st.get("optional")), "dir": st["dir"],
            "done": done, "by_artifact": pr["done"],
            "by_manual": bool(manual), "skipped": bool(skipped),
            "probes": pr["rows"],
            "what": st["what"], "note": st["note"], "commands": st["commands"],
            "requires": [s["id"] for s in STAGES[:i]],
        })
    current = None
    for r in rows:
        if not r["done"] and not r["optional"]:
            current = r["id"]
            break
    if current is None:
        pending_optional = [r["id"] for r in rows if not r["done"] and r["optional"]]
        current = pending_optional[0] if pending_optional else None
    return {"ws": str(ws), "ctx": ctx, "stages": rows, "current": current,
            # ★ 可选环节（S7 发行物料）不参与中途完成度判定：它可延后到 S11 前，
            #   真正的齐备性由 release_check.py 独立拦（不在这里假装通过）。
            "complete": all(r["done"] for r in rows if not r["optional"]),
            "pending_optional": [r["id"] for r in rows if r["optional"] and not r["done"]]}


def check_stage(ws: pathlib.Path, sid: str) -> tuple:
    """前置环节是否全部完成（S7 可选，不拦）。返回 (ok, 阻塞清单)。"""
    ev = evaluate(ws)
    idx = STAGE_IDS.index(sid)
    blocking = []
    for r in ev["stages"][:idx]:
        if r["optional"]:
            continue
        if not r["done"]:
            blocking.append("%s %s（%s）" % (r["id"], r["name"],
                                             "、".join("%s %d/%d" % (p["label"], p["found"], p["need"])
                                                      for p in r["probes"] if not p["ok"])
                                             or "未完成"))
    return (not blocking), blocking


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------
def render_list() -> str:
    L_ = ["=" * 78, "短剧标准作业流程（11 环节，顺序不可调）", "=" * 78]
    L_.append("%-4s %-10s %-4s %-6s %s" % ("ID", "环节", "类型", "可选", "产物判据"))
    L_.append("-" * 78)
    for st in STAGES:
        crit = "；".join(p["label"] for p in st["probes"])
        L_.append("%-4s %-10s %-4s %-6s %s"
                  % (st["id"], st["name"], KIND_LABELS.get(st["kind"], st["kind"]),
                     "是" if st.get("optional") else "", crit))
    L_.append("-" * 78)
    L_.append("agent = 需产出内容（Agent 做）；auto = 有脚本可无人值守；gate = 只校验")
    L_.append("跳过必须显式登记（workflow.py skip <ID> --reason ...），会写进状态文件留痕。")
    return "\n".join(L_)


def render_status(ev: dict) -> str:
    ctx = ev["ctx"]
    L_ = ["=" * 78, "流程进度（11 环节）", "=" * 78]
    L_.append("上下文：集数 %s ｜ 镜头数 %s" % (ctx["episodes"] or "?", ctx["shots"] or "?"))
    L_.append("-" * 78)
    for r in ev["stages"]:
        if r["done"]:
            tag = "[OK]  "
        elif r["optional"]:
            tag = "[可选]"
        elif r["id"] == ev["current"]:
            tag = "[→]   "
        else:
            tag = "[  ]  "
        src = ""
        if r["by_manual"]:
            src = "（手工登记）"
        elif r["skipped"]:
            src = "（已跳过）"
        L_.append("%s%s %-10s %-4s %s%s"
                  % (tag, r["id"], r["name"], KIND_LABELS.get(r["kind"], r["kind"]),
                     "｜".join("%s %d/%d" % (p["label"], p["found"], p["need"]) for p in r["probes"]),
                     src))
    L_.append("-" * 78)
    if ev["current"]:
        st = BY_ID[ev["current"]]
        L_.append("当前环节：%s %s —— %s" % (st["id"], st["name"], st["what"]))
        L_.append("注意    ：%s" % st["note"])
        for c in st["commands"]:
            L_.append("  命令  ：%s" % c)
    else:
        L_.append("全部环节已完成。")
    L_.append("=" * 78)
    return "\n".join(L_)


# ---------------------------------------------------------------------------
# 命令
# ---------------------------------------------------------------------------
def cmd_list(a) -> int:
    print(render_list())
    return 0


def cmd_status(a) -> int:
    ev = evaluate(_resolve_ws(a.workspace))
    if a.json:
        print(json.dumps(ev, ensure_ascii=False, indent=2))
    else:
        print(render_status(ev))
    return 0


def cmd_next(a) -> int:
    ev = evaluate(_resolve_ws(a.workspace))
    print(ev["current"] or "")
    return 0


def cmd_check(a) -> int:
    ws = _resolve_ws(a.workspace)
    ok, blocking = check_stage(ws, a.stage)
    if ok:
        print("[OK] 可以进入 %s %s（前置环节已完成）" % (a.stage, BY_ID[a.stage]["name"]))
        return 0
    print("[BLOCK] 不能进入 %s %s，前置环节未完成（退出码 %d）："
          % (a.stage, BY_ID[a.stage]["name"], EXIT_ORDER_VIOLATION))
    for b in blocking:
        print("  - %s" % b)
    print("  先补完，或显式跳过：workflow.py skip <前置ID> --reason \"...\"")
    return EXIT_ORDER_VIOLATION


def cmd_done(a) -> int:
    ws = _resolve_ws(a.workspace)
    if a.stage not in BY_ID:
        print("[FAIL] 未知环节：%s（%s）" % (a.stage, "/".join(STAGE_IDS)))
        return 2
    state = _load_state(ws)
    state["manual"][a.stage] = {"at": _now(), "note": a.note or ""}
    state["history"].append({"at": _now(), "action": "done", "stage": a.stage,
                             "note": a.note or ""})
    p = _save_state(ws, state)
    print("[OK] 已登记 %s %s 完成（依据：%s）" % (a.stage, BY_ID[a.stage]["name"],
                                                 a.note or "人工确认"))
    print("     %s" % p)
    return 0


def cmd_skip(a) -> int:
    ws = _resolve_ws(a.workspace)
    if a.stage not in BY_ID:
        print("[FAIL] 未知环节：%s" % a.stage)
        return 2
    if not a.reason:
        print("[FAIL] 跳过必须给 --reason（用户明确要求跳过才允许）")
        return 2
    state = _load_state(ws)
    state["skipped"][a.stage] = {"at": _now(), "reason": a.reason}
    state["history"].append({"at": _now(), "action": "skip", "stage": a.stage,
                             "reason": a.reason})
    _save_state(ws, state)
    print("[OK] 已跳过 %s %s：%s" % (a.stage, BY_ID[a.stage]["name"], a.reason))
    print("     （留痕在 %s；下游如有门禁依赖该环节，仍会单独拦）" % STATE_NAME)
    return 0


def _resolve_ws(explicit) -> pathlib.Path:
    if explicit:
        p = pathlib.Path(explicit).expanduser()
        if p.is_dir():
            return p.resolve()
    import os
    env = os.environ.get("SOLODRAMA_WORKSPACE") or os.environ.get("DRAMA_WORKSPACE")
    if env:
        p = pathlib.Path(env).expanduser()
        if p.is_dir():
            return p.resolve()
    sys.exit("[FAIL] 找不到短剧工作区：给 --workspace 或设 SOLODRAMA_WORKSPACE")


def main() -> int:
    ap = argparse.ArgumentParser(description="短剧标准作业流程（11 环节）")
    ap.add_argument("--workspace", default=None)
    sub = ap.add_subparsers(dest="cmd")

    for name in ("list", "status", "next"):
        q = sub.add_parser(name)
        q.add_argument("--workspace", default=argparse.SUPPRESS)
        if name == "status":
            q.add_argument("--json", action="store_true")

    q = sub.add_parser("check")
    q.add_argument("--workspace", default=argparse.SUPPRESS)
    q.add_argument("--stage", required=True, choices=STAGE_IDS)

    q = sub.add_parser("done")
    q.add_argument("--workspace", default=argparse.SUPPRESS)
    q.add_argument("stage", choices=STAGE_IDS)
    q.add_argument("--note", default=None)

    q = sub.add_parser("skip")
    q.add_argument("--workspace", default=argparse.SUPPRESS)
    q.add_argument("stage", choices=STAGE_IDS)
    q.add_argument("--reason", default=None)

    a = ap.parse_args()
    fn = {"list": cmd_list, "status": cmd_status, "next": cmd_next,
          "check": cmd_check, "done": cmd_done, "skip": cmd_skip}.get(a.cmd)
    if not fn:
        print(render_list())
        return 0
    return fn(a)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
