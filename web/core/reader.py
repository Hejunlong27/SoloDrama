# -*- coding: utf-8 -*-
"""reader.py —— 只读聚合器（「整剧一屏」的数据来源）

两条数据通道：
  ① **文件通道**：工作区里的 JSON / 目录（唯一真源）—— 布局解析一律走 `stages/_layout.py`；
  ② **CLI 只读通道**：`drama.py status --json` / `models status --json` / `style status --json`
     —— 门禁判定带业务语义，**不在 Web 层复刻**，直接问引擎。

本模块只读，不写工作区任何文件。
"""
from __future__ import annotations

import time

from . import jsonout, paths, runner

_CACHE: dict = {}


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


# ---------------------------------------------------------------------------
# 布局
# ---------------------------------------------------------------------------
def _layout_mod():
    return paths.ensure_layout_importable()


def workspace_info(ws) -> dict:
    L = _layout_mod()
    if L is None:
        return {"ok": False, "error": "无法载入 stages/_layout.py（仓库结构异常）", "ws": str(ws)}
    w = str(ws)
    try:
        lay = L.load(w)
        stages = L.all_stage_dirs(w)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "布局解析失败：%s" % exc, "ws": w}
    out = []
    for key, p in stages.items():
        try:
            files = sum(1 for _ in p.rglob("*") if _.is_file()) if p.exists() else 0
        except OSError:
            files = 0
        out.append({"key": key, "dir": p.name, "path": str(p),
                    "exists": p.exists(), "files": files})
    return {
        "ok": True,
        "ws": w,
        "is_new_layout": not lay.get("_fallback", True),
        "layout_version": lay.get("layout_version"),
        "engine_root": str(L.engine_root(w)),
        "data_dir": str(L.data_dir(w)),
        "out_dir": str(L.out_dir(w)),
        "stages": out,
    }


# ---------------------------------------------------------------------------
# 引擎 CLI（只读）
# ---------------------------------------------------------------------------
def _extract_json(text):
    """从 CLI 输出里抽 JSON（实现已收编到 `core/jsonout.py`，本函数保留为兼容别名）。

    ★ 历史坑（2026-10-17）：
      ① `drama.py style status --json` 会把子脚本输出以 `  | ` 前缀逐行回显；
      ② 人读区里还有**行内**小 JSON，按「首个 { 到末个 }」切片会报 Extra data。
    现在统一由 `jsonout.extract_json` 处理：剥行首标记 → 每个 `{` raw_decode → 取跨度最大者。
    """
    return jsonout.extract_json(text)


def _cli_json(args: list, ws, ttl=4, timeout=120):
    def run():
        argv = [paths.engine_python(), str(paths.PROD_SCRIPTS / "drama.py")] + args
        rc, text, _ = runner.capture(argv, ws=ws, timeout=timeout)
        return {"rc": rc, "data": _extract_json(text), "text": text, "exit": runner.exit_meaning(rc)}

    return _cached("cli:%s:%s" % (ws, " ".join(args)), ttl, run)


def status(ws) -> dict:
    r = _cli_json(["status", "--json"], ws, ttl=5)
    if r["data"]:
        # 去掉可能内嵌的超长 base64 / data URI，避免把二进制塞给浏览器
        for ref in r["data"].get("refs", []) or []:
            if isinstance(ref, dict) and isinstance(ref.get("file"), str) and len(ref["file"]) > 120:
                ref["file"] = ref["file"][:60] + "…(omitted)"
        r["data"]["keys"] = {k: runner.mask_text(str(v)) for k, v in (r["data"].get("keys") or {}).items()}
    return r


def style_gate(ws) -> dict:
    return _cli_json(["style", "status", "--json"], ws, ttl=5)


def model_gate(ws) -> dict:
    return _cli_json(["models", "status", "--json"], ws, ttl=5)


def norm_style(ws) -> dict:
    """把 `style status --json` 的原始结构规整成 UI 可用的形状。

    注意：这里**只读引擎自己写下的确认记录**（`confirmed` / `label`），
    不在 Web 层复刻门禁判定 —— 判定仍在 `style_gate.py` 里。
    """
    raw = style_gate(ws).get("data") or {}
    plan = raw.get("plan") if isinstance(raw.get("plan"), dict) else raw
    st = (plan or {}).get("style")
    if isinstance(st, dict):
        return {"confirmed": bool(st.get("confirmed")), "label": st.get("label") or st.get("style") or "",
                "choice": st.get("style"), "sub_mode": st.get("sub_mode"),
                "confirmed_at": st.get("confirmed_at"), "raw": raw}
    if isinstance(st, str):
        return {"confirmed": True, "label": st, "choice": st, "raw": raw}
    return {"confirmed": False, "label": "", "choice": None, "raw": raw}


def norm_models(ws) -> dict:
    """规整 `models status --json`：image / video 两类通道 + 执行依据齐备性。"""
    raw = model_gate(ws).get("data") or {}
    plan = raw.get("plan") if isinstance(raw.get("plan"), dict) else raw
    models = (plan or {}).get("models") or {}

    def one(k):
        d = models.get(k) or {}
        return {"confirmed": bool(d.get("confirmed")), "choice": d.get("choice"),
                "label": d.get("label"), "cost": d.get("cost"),
                "evidence_ok": d.get("evidence_ok"), "missing_evidence": d.get("missing_evidence") or [],
                "detail": d.get("detail") or {}}

    im, vi = one("image"), one("video")
    return {"image": im, "video": vi, "confirmed": bool(im["confirmed"] and vi["confirmed"]), "raw": raw}


# ---------------------------------------------------------------------------
# 15 环节看板
# ---------------------------------------------------------------------------
ROUNDS = [
    ("-1", "画风确认", "style"),
    ("0", "通道确认", "model"),
    ("1", "榜单调研", "research"),
    ("2", "爆款拆解", "research"),
    ("3", "选题定位", "topic"),
    ("3.5", "剧本转译", "script"),
    ("3.6", "题材公式", "script"),
    ("4", "剧本改写", "script"),
    ("5", "台词时长审计", "script"),
    ("6", "资产出图", "assets"),
    ("7", "参考图接线", "assets"),
    ("8", "分镜与提示词", "storyboard"),
    ("9", "转换 + 入门口禁", "prompts"),
    ("10", "批量出片", "film"),
    ("11", "拼接 / 2K / 字幕", "film"),
    ("12", "验收与结账", "film"),
    ("13", "合规与发行", "compliance"),
]

# (环节, 该环节的「完成证据」候选相对路径 —— 命中任一即视为完成)
EVIDENCE = {
    "1": ["market-data.json", "market/market-data.json", "市场数据.json"],
    "2": ["hit-breakdown.md", "breakdown.md"],
    "3": ["candidates.json", "raw-candidates.json", "positioning.json"],
    "3.5": ["source-script.es.md", "translation-brief.md", "glossary.json"],
    "3.6": ["genre-plan.json"],
    "4": ["blueprint.json", "blueprint.md"],
    "5": ["台词时长审计.md", "timing-audit.md"],
    "6": ["refs.json", "assets-manifest.json"],
    "7": ["refs.json"],
    "8": ["storyboard.json"],
    "9": ["data/shots.json", "data/h3_prompts.json"],
    "10": [],
    "11": [],
    "12": [],
    "13": [],
}


def pipeline(ws) -> dict:
    info = workspace_info(ws)
    if not info.get("ok"):
        return info
    L = _layout_mod()
    st = status(ws).get("data") or {}
    sg = norm_style(ws)
    mg = norm_models(ws)

    rounds = []
    batches = st.get("batches") or []
    for no, title, stage_key in ROUNDS:
        state, detail = "todo", ""
        if no == "-1":
            state, detail = ("done", "已确认：" + (sg.get("label") or "")) if sg["confirmed"] else ("blocked", "未确认（G-1，退出码 4）")
        elif no == "0":
            state, detail = ("done", "已确认：出图 %s / 出片 %s" % (mg["image"].get("choice"), mg["video"].get("choice"))) if mg["confirmed"] else ("blocked", "未确认（G0，退出码 4）")
        elif no in ("10", "11", "12", "13"):
            if no == "10":
                tot = sum((b.get("totals") or {}).get("total", 0) for b in batches)
                ok = sum((b.get("totals") or {}).get("success", 0) for b in batches)
                fail = sum((b.get("totals") or {}).get("failed", 0) for b in batches)
                # ★ 「建了批次」≠「出片完成」：只有全部成功才算 done，否则最多 doing
                if tot and ok == tot:
                    state, detail = "done", "累计 %d 段全部成功" % tot
                elif ok or fail:
                    state, detail = "doing", "累计 %d 段：成功 %d / 失败 %d" % (tot, ok, fail)
                elif tot:
                    state, detail = "todo", "已有批次但尚无成功段（%d 段待跑）" % tot
            elif no == "11":
                subs = _count_files(info["out_dir"], "subs")
                state, detail = ("done", "字幕目录 %d 个文件" % subs) if subs else ("todo", "")
            elif no == "12":
                led = st.get("ledger") or {}
                if led.get("files"):
                    state, detail = "done", "台账 %d 份 / 消耗 %.0f RH币" % (led.get("files", 0), led.get("rh_coins", 0) or 0)
            else:
                pass
        else:
            ev = EVIDENCE.get(no) or []
            if ev:
                for rel in ev:
                    if _stage_has(L, ws, stage_key, rel):
                        state, detail = "done", rel
                        break
        rounds.append({"no": no, "title": title, "stage": stage_key, "state": state, "detail": detail})

    return {"ok": True, "rounds": rounds, "layout": info}


def _stage_has(L, ws, stage_key, rel) -> bool:
    try:
        p = L.stage_dir(ws, stage_key) / rel
        return p.exists()
    except Exception:  # noqa: BLE001
        return False


def _count_files(root, sub) -> int:
    try:
        base = paths.Path(root) / sub
        if not base.exists():
            return 0
        return sum(1 for p in base.rglob("*") if p.is_file())
    except OSError:
        return 0


def next_actions(ws) -> list:
    """给出「下一步建议」（纯提示，不执行）。"""
    pl = pipeline(ws)
    if not pl.get("ok"):
        return []
    out = []
    for r in pl["rounds"]:
        if r["state"] == "blocked":
            out.append({"level": "warn", "round": r["no"],
                        "text": "环节 %s %s：%s" % (r["no"], r["title"], r["detail"])})
    st = status(ws).get("data") or {}
    miss_c = st.get("assets", {}).get("missing_characters") or []
    miss_s = st.get("assets", {}).get("missing_scenes") or []
    if miss_c or miss_s:
        out.append({"level": "info", "round": "6",
                    "text": "缺资产：人物 %d / 场景 %d → drama.py assets --engine local（干跑）" % (len(miss_c), len(miss_s))})
    over = [r for r in (st.get("refs") or []) if r.get("h3_over_limit")]
    if over:
        out.append({"level": "warn", "round": "7",
                    "text": "有 %d 张参考图超过 H3 上限 5760px，必须先瘦身：drama.py refs --apply" % len(over)})
    h3 = st.get("h3") or {}
    if h3 and not h3.get("ready"):
        out.append({"level": "warn", "round": "10",
                    "text": "G2 未就绪：h3 工作流 ID / 节点映射缺失（用 run.py probe → configure.py apply-nodes 回填）"})
    for b in (st.get("batches") or [])[:3]:
        t = b.get("totals") or {}
        if t.get("failed"):
            out.append({"level": "warn", "round": "10",
                        "text": "批次 %s 有 %d 段失败 → 用「续跑」而非全量重跑" % (b.get("batch"), t.get("failed"))})
    return out


def overview(ws) -> dict:
    info = workspace_info(ws)
    st = status(ws)
    pl = pipeline(ws)
    return {
        "workspace": info,
        "status": st.get("data"),
        "status_raw": None if st.get("data") else runner.mask_text((st.get("text") or "")[-1500:]),
        "status_exit": st.get("exit"),
        "gates": {"style": norm_style(ws), "models": norm_models(ws)},
        "style_gate": norm_style(ws),
        "model_gate": norm_models(ws),
        "pipeline": pl.get("rounds"),
        "next_actions": next_actions(ws),
    }
