# -*- coding: utf-8 -*-
"""创作闭环：AI 草稿 → 校验 → 人工编辑 → 确认落盘

为什么单独一层：这是**唯一**会写正式产物（`03-剧本/ep_NN.md`）的 AI 路径，
必须把「生成」与「写入」彻底分开，并且写入前过引擎的四段法门禁。

落点：
  草稿  <ws>/video-pipeline/llm-drafts/epNN-<id>.json     （随时可删，不进任何门禁）
  备份  <ws>/video-pipeline/llm-drafts/backup/epNN-<ts>.md（覆盖前必留）
  正式  <ws>/03-剧本/ep_NN.md                             （只有 confirm 才写）

三条硬规则：
  1. 生成失败**绝不**触碰正式文件；
  2. 覆盖必须显式 `overwrite=true`，且可校验 `expected_sha`（防覆盖别人刚改的内容）；
  3. 诊断卡未确认时拒绝写入（与 `script_rewrite.py build --emit` 的退出码 4 同口径）。
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from pathlib import Path

from .. import jobs, paths
from . import budget
from .errors import LLMError

# ---- 与引擎同步的常量（引擎可导入时以引擎为准，避免第七份口径）----
FFS_HEADER_ORDER = ["TITLE", "EP", "PLATFORM", "STYLE LOCK", "CHAR", "SCENE"]
FFS_SHOT_FIELDS = ["SHOT", "LOCATION", "TIME", "CHAR", "ACTION", "DIALOG", "VO", "SFX"]
DUR_MIN, DUR_MAX = 4, 15
def bounds_for(ep_seconds):
    """镜数/时长边界。实现见 `budget.py`（提示词与校验器共用同一真源）。"""
    return budget.bounds_for(ep_seconds)


def _layout():
    return paths.ensure_layout_importable()


def stage_path(ws, rel: str) -> Path:
    """逻辑路径 → 真实路径（与引擎 `_common.pdir` 完全同口径）。"""
    L = _layout()
    r = rel
    if L is not None:
        try:
            r = L.stage_rel(str(ws), rel)
        except Exception:  # noqa: BLE001
            r = rel
    return Path(ws) / r


def engine_root(ws) -> Path:
    L = _layout()
    if L is not None:
        try:
            return Path(L.engine_root(str(ws)))
        except Exception:  # noqa: BLE001
            pass
    return Path(ws) / "video-pipeline"


def draft_dir(ws) -> Path:
    return engine_root(ws) / "llm-drafts"


def _read_json(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, ValueError):
        return default


def _write_text(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as fh:   # 强制 LF
        fh.write(text if text.endswith("\n") else text + "\n")
    return p


def _write_json(p: Path, data) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return p


def sha256_file(p) -> str:
    try:
        return hashlib.sha256(Path(p).read_bytes()).hexdigest()
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# 前置条件与上下文
# ---------------------------------------------------------------------------
def gates(ws) -> dict:
    """能不能生成某一集正文：三件事齐了才行。"""
    ws = str(ws)
    bp_path = stage_path(ws, "creation/03-script/blueprint.json")
    dg_path = stage_path(ws, "creation/03-script/diagnosis.json")
    bp = _read_json(bp_path) or {}
    dg = _read_json(dg_path) or {}

    ep_count = int(bp.get("total_ep") or 0) if isinstance(bp, dict) else 0
    ep_seconds = int(bp.get("ep_seconds") or 60)

    items = [
        {"key": "blueprint", "label": "集数规划（blueprint.json）", "ok": bool(ep_count),
         "detail": "%d 集 · 单集 %d 秒" % (ep_count, ep_seconds) if ep_count else "缺少规划",
         "path": str(bp_path)},
        {"key": "diagnosis", "label": "改编诊断已确认（structure_confirmed）",
         "ok": bool(dg.get("structure_confirmed")),
         "detail": ("已确认" if dg.get("structure_confirmed")
                    else ("诊断卡未完成" if dg else "旧项目无诊断卡（仅告警，不拦截）")),
         "path": str(dg_path)},
        {"key": "bible", "label": "世界观/角色代号（world-bible.json）",
         "ok": bool(_read_json(stage_path(ws, "bible/world-bible.json"))),
         "detail": "用于生成 HEADER 的 CHAR/SCENE 代号",
         "path": str(stage_path(ws, "bible/world-bible.json"))},
    ]
    strict = bool(dg) and not dg.get("structure_confirmed")
    return {
        "ok": bool(ep_count) and not strict,
        "blocking": strict,
        "items": items,
        "ep_count": ep_count,
        "ep_seconds": ep_seconds,
        "title": bp.get("title") if isinstance(bp, dict) else None,
        "platform": bp.get("platform") if isinstance(bp, dict) else None,
        "shot_bounds": list(bounds_for(ep_seconds)),
    }


def _chars_header(ws) -> str:
    """CHAR 行：优先 bible/characters.md 的代号表，其次 world-bible.json。"""
    md = stage_path(ws, "bible/characters.md")
    try:
        text = md.read_text(encoding="utf-8")
    except OSError:
        text = ""
    if text:
        codes = re.findall(r"\|\s*`([A-Z_]{2,})`", text)
        if codes:
            return "; ".join("%s: <锚点待补>" % c for c in codes[:6])

    wb = _read_json(stage_path(ws, "bible/world-bible.json")) or {}
    out = []
    for ch in (wb.get("characters") or [])[:6]:
        if not isinstance(ch, dict):
            continue
        code = str(ch.get("code") or "").strip()
        if not code:
            continue
        bits = [str(ch.get("name") or "").strip()]
        if ch.get("visual_anchor"):
            bits.append(str(ch["visual_anchor"]).strip())
        if ch.get("palette"):
            bits.append(str(ch["palette"]).strip())
        out.append("%s: %s" % (code, "｜".join([b for b in bits if b])))
    return "; ".join(out)


def _scenes_header(ws) -> str:
    wb = _read_json(stage_path(ws, "bible/world-bible.json")) or {}
    out = []
    for sc in (wb.get("scenes") or [])[:6]:
        if not isinstance(sc, dict):
            continue
        code = str(sc.get("code") or "").strip()
        if not code:
            continue
        desc = str(sc.get("desc") or sc.get("name") or "").strip()
        out.append("%s: %s" % (code, desc or "<描述待补>"))
    return "; ".join(out)


def header_lines(ws, ep: int) -> tuple:
    """返回 (标题行列表, 来源)。**优先沿用已有文件的 HEADER**，保住人工写的视觉锚点。"""
    target = stage_path(ws, "script/ep_%02d.md" % ep)
    try:
        text = target.read_text(encoding="utf-8")
    except OSError:
        text = ""
    if text:
        got = {}
        for ln in text.splitlines()[:40]:
            m = re.match(r"^#\s*(TITLE|EP|PLATFORM|STYLE LOCK|CHAR|SCENE)\s*:\s*(.*)$", ln)
            if m and m.group(1) not in got:
                got[m.group(1)] = m.group(2).strip()
        if all(got.get(k) for k in FFS_HEADER_ORDER):
            return ["# %s: %s" % (k, got[k]) for k in FFS_HEADER_ORDER], "existing"

    bp = _read_json(stage_path(ws, "creation/03-script/blueprint.json")) or {}
    total = bp.get("total_ep") or 0
    char_line = _chars_header(ws) or "<CHAR 代号>: <锚点>"
    scene_line = _scenes_header(ws) or "<SCENE 代号>: <描述>"
    lines = [
        "# TITLE: %s" % (bp.get("title") or ""),
        "# EP: %02d/%s" % (ep, total or "?"),
        "# PLATFORM: %s" % (bp.get("platform") or ""),
        "# STYLE LOCK: %s" % (bp.get("style_lock") or ""),
        "# CHAR: %s" % char_line,
        "# SCENE: %s" % scene_line,
    ]
    src = "blueprint" if (bp.get("title") and bp.get("style_lock")) else "placeholder"
    return lines, src


def context(ws, ep: int) -> dict:
    """生成某一集所需的全部输入（也给前端显示「会给模型什么」）。"""
    g = gates(ws)
    ep = int(ep)
    if ep < 1 or (g["ep_count"] and ep > g["ep_count"]):
        raise LLMError("config", "集号超出范围：EP%d（本项目共 %d 集）" % (ep, g["ep_count"]))

    bp = _read_json(stage_path(ws, "creation/03-script/blueprint.json")) or {}
    row = next((e for e in (bp.get("episodes") or []) if int(e.get("ep") or 0) == ep), None)
    if not isinstance(row, dict):
        raise LLMError("config", "blueprint.json 里没有 EP%d 的规划行，先跑 script_rewrite.py plan" % ep)

    lines, src = header_lines(ws, ep)
    ep_seconds = int(bp.get("ep_seconds") or 60)
    s_min, s_max, t_min, t_max = bounds_for(ep_seconds)
    shot_count = max(s_min, min(s_max, int(round(ep_seconds / 8.0))))

    warnings = []
    if src != "existing":
        warnings.append("本集还没有正式剧本，HEADER 由 blueprint/world-bible 推导；"
                        "落盘前请确认 CHAR/SCENE 代号与代号对应的视觉锚点。")
    if "<锚点待补>" in "\n".join(lines):
        warnings.append("bible 未登记角色视觉锚点，HEADER 里是占位符，会在下游资产映射时缺图。")
    if g["blocking"]:
        warnings.append("诊断卡未确认（structure_confirmed=false）：可以生成草稿，但不允许落盘。")

    return {
        "ep": ep,
        "ep_seconds": ep_seconds,
        "shot_bounds": [s_min, s_max],
        "total_bounds": [t_min, t_max],
        "shot_count": shot_count,
        "header": lines,
        "header_source": src,
        "warnings": warnings,
        "target": str(stage_path(ws, "script/ep_%02d.md" % ep)),
        "target_exists": stage_path(ws, "script/ep_%02d.md" % ep).is_file(),
        "blueprint_row": row,
        "style_lock": bp.get("style_lock") or "",
        "title": bp.get("title") or "",
        "platform": bp.get("platform") or "",
    }


# ---------------------------------------------------------------------------
# 生成
# ---------------------------------------------------------------------------
def generate(ws, ep, *, gateway, provider_id=None, model=None, timeout_s=None) -> dict:
    ws = str(ws)
    ctx = context(ws, ep)
    if not ctx["style_lock"]:
        raise LLMError("config", "blueprint.json 缺少 style_lock（画风锁），不能生成正文")

    variables = {
        "blueprint_row": ctx["blueprint_row"],
        "style_lock": ctx["style_lock"],
        "char_header": ctx["header"][4] if len(ctx["header"]) > 4 else "",
        "scene_header": ctx["header"][5] if len(ctx["header"]) > 5 else "",
        "ep_seconds": ctx["ep_seconds"],
        "shot_count": ctx["shot_count"],
    }

    res = gateway.complete("script.generate", variables, provider_id=provider_id,
                           model=model, timeout_s=timeout_s, project=ws)
    if not res.get("ok"):
        return {"ok": False, "error": res.get("error"), "request_id": res.get("request_id"),
                "context": _ctx_brief(ctx)}

    data = res.get("data") or {}
    # 引擎口径复核（Schema 已挡一遍，这里再按边界确认，避免与引擎分叉）
    s_min, s_max, t_min, t_max = bounds_for(ctx["ep_seconds"])
    n = len(data.get("shots") or [])
    total = sum(int(s.get("dur") or 0) for s in (data.get("shots") or []))
    problems = []
    if not (s_min <= n <= s_max):
        problems.append("镜头数 %d 不在 %d-%d 之间" % (n, s_min, s_max))
    if not (t_min <= total <= t_max):
        problems.append("总时长 %d 秒不在 %d-%d 之间" % (total, t_min, t_max))
    if problems:
        return {"ok": False, "request_id": res.get("request_id"),
                "error": {"kind": "schema", "message": "超出本剧时长口径：" + "；".join(problems),
                          "retryable": True},
                "context": _ctx_brief(ctx)}

    md = render_md(ctx["header"], data)
    draft = {
        "id": "d-%s-ep%02d-%s" % (time.strftime("%Y%m%d%H%M%S"), int(ep), uuid.uuid4().hex[:4]),
        "ws": ws, "ep": int(ep), "status": "draft",
        "created_at": time.time(), "updated_at": time.time(),
        "purpose": "script.generate", "request_id": res.get("request_id"),
        "provider": res.get("provider"), "provider_name": res.get("provider_name"),
        "model": res.get("model"), "template_id": res.get("template_id"),
        "usage": res.get("usage"), "cost": res.get("cost"),
        "simulated": bool(res.get("simulated")),
        "data": data, "md": md,
        "header_source": ctx["header_source"], "warnings": ctx["warnings"],
        "target": ctx["target"],
        "checks": _self_check(data, ctx),
    }
    _write_json(draft_dir(ws) / ("%s.json" % draft["id"]), draft)
    jobs.record_audit(ws, "llm.script.generate", ["ep=%d" % ep], 0,
                      estimate="", note="AI 草稿 %s" % draft["id"])
    return {"ok": True, "draft": draft, "context": _ctx_brief(ctx)}


def _ctx_brief(ctx) -> dict:
    return {k: ctx[k] for k in ("ep", "ep_seconds", "shot_bounds", "shot_count",
                                "header", "header_source", "warnings", "target",
                                "target_exists", "style_lock")}


def _self_check(data, ctx) -> list:
    """给前端看的本地检查（与 lint 口径一致，但不是 lint 的替代）。"""
    shots = data.get("shots") or []
    total = sum(int(s.get("dur") or 0) for s in shots)
    long_lines = []
    for s in shots:
        for sent in re.findall(r"[“\"']([^”\"']+)[”\"']", str(s.get("dialog") or "")):
            if len(sent.strip()) > 40:
                long_lines.append("SC-%02d 台词 %d 字" % (int(s.get("no") or 0), len(sent.strip())))
    return [
        {"key": "shots", "ok": True, "text": "%d 镜" % len(shots)},
        {"key": "duration", "ok": True, "text": "总时长 %d 秒" % total},
        {"key": "dialog", "ok": not long_lines,
         "text": "台词长度正常" if not long_lines else "；".join(long_lines[:4])},
    ]


def render_md(header, data) -> str:
    """严格按 FFS 格式落 MD（HEADER 六字段 + 镜头八字段 + DUR）。"""
    L = list(header) + [""]
    for i, s in enumerate(data.get("shots") or [], 1):
        no = int(s.get("no") or i)
        dialog = str(s.get("dialog") or "").strip() or "无"
        if dialog != "无" and not re.match(r'^["“\']', dialog):
            dialog = '"%s"' % dialog.strip()
        L += [
            "---",
            "[SC-%02d]" % no,
            "SHOT: %s" % str(s.get("shot") or "").strip(),
            "LOCATION: %s" % str(s.get("location") or "").strip(),
            "TIME: %s" % str(s.get("time") or "").strip(),
            "CHAR: %s" % str(s.get("char") or "无").strip(),
            "ACTION: %s" % str(s.get("action") or "").strip(),
            "DIALOG: %s" % dialog,
            "VO: %s" % (str(s.get("vo") or "").strip() or "无"),
            "SFX: %s" % (str(s.get("sfx") or "").strip() or "无"),
            "DUR: %d" % int(s.get("dur") or 0),
        ]
    L += [
        "---",
        "<!-- 本集核心冲突：%s -->" % (data.get("core_conflict") or ""),
        "<!-- 本集反转：%s -->" % (data.get("reversal") or ""),
        "<!-- 本集钩子（写进最后一个镜头）：[%s] %s -->" % (data.get("hook_type") or "", data.get("hook") or ""),
        "<!-- 由 SoloDrama Studio 生成，确认后落盘；口径见 prompts/s3-script-rewrite.md -->",
    ]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------
# 草稿读写与确认
# ---------------------------------------------------------------------------
def list_drafts(ws) -> dict:
    d = draft_dir(str(ws))
    items = []
    for p in sorted(d.glob("d-*.json"), reverse=True) if d.is_dir() else []:
        j = _read_json(p) or {}
        if not j:
            continue
        items.append({
            "id": j.get("id") or p.stem, "ep": j.get("ep"), "status": j.get("status"),
            "created_at": j.get("created_at"), "updated_at": j.get("updated_at"),
            "provider_name": j.get("provider_name"), "model": j.get("model"),
            "shots": len((j.get("data") or {}).get("shots") or []),
            "target": j.get("target"),
            "usage": j.get("usage"),
        })
    return {"items": items[:100], "dir": str(d)}


def _draft_path(ws, did: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9._-]{4,80}", str(did or "")):
        raise LLMError("config", "草稿 ID 不合法")
    p = draft_dir(str(ws)) / ("%s.json" % did)
    if not p.is_file():
        raise LLMError("not_found", "找不到草稿：%s" % did)
    return p


def get_draft(ws, did: str) -> dict:
    j = _read_json(_draft_path(ws, did)) or {}
    return {"ok": True, "draft": j}


def update_draft(ws, did: str, patch: dict) -> dict:
    """人工编辑：可以改 md 正文，或直接改 data（改 data 时重算 md）。"""
    p = _draft_path(ws, did)
    j = _read_json(p) or {}
    if j.get("status") == "confirmed":
        raise LLMError("config", "该草稿已确认落盘，不能再改；请基于新对话重新生成")
    changed = False
    if isinstance(patch.get("data"), dict) and patch["data"]:
        from .schema import validate
        from . import templates as T
        sch = T.SCHEMAS.get("script.episode") or {}
        errs = validate(patch["data"], sch)
        if errs:
            raise LLMError("schema", "编辑后的内容未通过 Schema：%s"
                           % "；".join("%s %s" % (e["path"], e["message"]) for e in errs[:6]))
        j["data"] = patch["data"]
        hdr = [ln for ln in (j.get("md") or "").splitlines() if ln.startswith("# ")]
        j["md"] = render_md(hdr or [], patch["data"])
        changed = True
    if isinstance(patch.get("md"), str) and patch["md"].strip():
        j["md"] = patch["md"]
        changed = True
    if not changed:
        raise LLMError("config", "没有要修改的内容")
    j["updated_at"] = time.time()
    _write_json(p, j)
    return {"ok": True, "draft": j}


def confirm(ws, did: str, *, overwrite=False, expected_sha=None,
            allow_simulated=False) -> dict:
    """把草稿写成正式剧本。这是整条链唯一写正式文件的地方。

    ★ 演练草稿（Mock 生成）默认**不许**落盘：它没有经过真实模型，写进 `03-剧本/` 就是伪造产物。
      只有显式 `allow_simulated=True`（离线验证脚本 + 临时工作区）才放行，并在结果里标注。
    """
    ws = str(ws)
    p = _draft_path(ws, did)
    j = _read_json(p) or {}
    if j.get("status") == "confirmed" and not overwrite:
        return {"ok": True, "already": True, "target": j.get("target"),
                "note": "该草稿已落盘（幂等）"}

    if j.get("simulated") and not allow_simulated:
        raise LLMError("config",
                       "这是离线演练草稿（Mock 生成，没有经过真实模型），不能写入正式剧本；"
                       "要验证完整链路请在临时工作区用 allow_simulated，或先在「AI 模型中心」配置真实模型再生成")

    # 门禁：诊断卡未确认 → 拒绝写入（与 build --emit 的退出码 4 同口径）
    g = gates(ws)
    if g["blocking"]:
        raise LLMError("config", "改编诊断卡尚未确认（structure_confirmed=false）："
                                 "先跑 script_rewrite.py diagnose --check → --confirm")

    md = str(j.get("md") or "")
    if not md.strip():
        raise LLMError("config", "草稿正文为空，拒绝写入")

    target = Path(j.get("target") or stage_path(ws, "script/ep_%02d.md" % int(j.get("ep") or 0)))
    if target.exists():
        if not overwrite:
            raise LLMError("config", "目标文件已存在：%s。确认覆盖请勾选「覆盖已有剧本」" % target.name)
        if expected_sha and sha256_file(target) != expected_sha:
            raise LLMError("config", "目标文件在编辑期间被改动过（指纹不一致），已拒绝覆盖；"
                                     "请重新读取后再确认")
        backup = draft_dir(ws) / "backup" / ("ep%02d-%s.md" % (int(j.get("ep") or 0),
                                                             time.strftime("%Y%m%d-%H%M%S")))
        _write_text(backup, target.read_text(encoding="utf-8", errors="replace"))
        j["backup"] = str(backup)

    _write_text(target, md)
    j["status"] = "confirmed"
    j["confirmed_at"] = time.time()
    j["target"] = str(target)
    _write_json(p, j)
    jobs.record_audit(ws, "llm.script.confirm", ["ep=%d" % int(j.get("ep") or 0), str(target.name)], 0,
                      note="覆盖" if j.get("backup") else "新建", actor="studio")
    return {"ok": True, "target": str(target), "ep": j.get("ep"),
            "simulated": bool(j.get("simulated")),
            "backup": j.get("backup"), "bytes": len(md.encode("utf-8")),
            "next": ["script_rewrite.py lint --ep %d" % int(j.get("ep") or 1),
                     "tools/cli.py check --ep %d" % int(j.get("ep") or 1)]}
