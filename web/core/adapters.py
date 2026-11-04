# -*- coding: utf-8 -*-
"""adapters.py —— 结构化 CLI 适配层（只读优先）

定位
----
`runner.py` 负责「把命令跑起来」，本模块负责「把结果变回结构」：

  CLI 脚本 → 退出码 + stdout → （JSON 优先）→ 稳定 dict → 上层聚合

三条纪律
--------
1. **JSON 优先**：所有适配器都带 `--json`。拿不到 JSON 时**不猜**，返回
   `{"ok": False, "reason": "no_json"}`，由上层显示「该能力无结构化输出」。
2. **判成败只看退出码**（0 成功 / 2 门禁 / 3 熔断 / 4 待确认 / 130 中断）。
3. **只读白名单**：本模块只调「读」类子命令（status/show/check/list）；
   写操作一律走 `commands.py` 的声明式白名单 + 作业队列。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import jsonout, paths, runner

# 只读子命令的脚本位置（与 commands.SCRIPTS 同一批文件，这里只挑读类）
SCRIPTS = {
    "drama": paths.PROD_SCRIPTS / "drama.py",
    "env": paths.TOOLS_DIR / "env_check.py",
    "cost_ledger": paths.PROD_SCRIPTS / "cost_ledger.py",
    "release_check": paths.PROD_SCRIPTS / "release_check.py",
    "release_export": paths.PROD_SCRIPTS / "release_export.py",
}

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


def run_json(script_key: str, args: list, ws, *, timeout: int = 90, ttl: int = 0) -> dict:
    """跑一个只读子命令并解析 JSON。

    返回：{"ok": bool, "rc": int, "exit": {...}, "data": dict|None,
           "reason": "", "text_tail": str, "elapsed": float}
    """
    script = SCRIPTS.get(script_key)
    if script is None or not Path(script).is_file():
        return {"ok": False, "rc": None, "exit": None, "data": None,
                "reason": "script_missing", "text_tail": "", "elapsed": 0}

    def go():
        argv = [paths.engine_python(), str(script)] + [str(a) for a in args]
        r = runner.run_stream(argv, ws=ws, timeout=timeout)
        data = jsonout.extract_json("\n".join(r["lines"]))
        return {
            "ok": r["rc"] == 0 and data is not None,
            "rc": r["rc"],
            "exit": runner.exit_meaning(r["rc"]),
            "data": data,
            "reason": "" if data is not None else ("no_json" if r["rc"] == 0 else "nonzero_exit"),
            "text_tail": "\n".join(r["lines"][-40:]),
            "elapsed": r["elapsed"],
        }

    if ttl <= 0:
        return go()
    return _cached("json:%s:%s:%s" % (script_key, ws, " ".join(map(str, args))), ttl, go)


# ---------------------------------------------------------------------------
# 具体适配器（每个都对应一个真实存在的子命令）
# ---------------------------------------------------------------------------
def workflow_status(ws) -> dict:
    """七环节 23 节点状态（唯一真源：`drama nodes --json` → `nodes.py::evaluate`）。

    ★ 2026-11-01：原实现调 `workflow.py status`（S1–S11），而那脚本已在 V0.7.42 删除 ——
      本函数于是长期返回 `script_missing`，连带「流程总览 / 助手上下文 / 流水线推进」
      三块一起静默失效（UI 只显示「未接入」，不报错）。现在接回节点真源。
    """
    return run_json("drama", ["nodes", "--json"], ws, ttl=8)


SETUP_LABELS = (
    ("track", "形态 track"),
    ("look", "视觉 look"),
    ("narrative", "叙事模式"),
    ("episodes", "集数"),
    ("image_engine", "图片通道"),
    ("video_engine", "视频通道"),
)


def setup_show(ws) -> dict:
    """开工前置 6 项：读单一档案 `drama.json`。

    ★ 2026-11-01：原来调 `drama setup show`（`project_setup.py`），该脚本已随 V0.7.42
      删除，函数一直返回 script_missing。现在改为直接读档案，不新增第二个真源。
    """
    p = Path(ws) / "drama.json"
    d = {}
    if p.is_file():
        try:
            d = json.loads(p.read_text(encoding="utf-8-sig")) or {}
        except (OSError, ValueError):
            d = {}
    fmt = d.get("format") or {}
    eps = d.get("episodes") or {}
    ch = d.get("channel") or {}
    raw = {"track": fmt.get("track"), "look": fmt.get("look"),
           "narrative": fmt.get("narrative"), "episodes": eps.get("count"),
           "image_engine": (ch.get("image") or {}).get("engine"),
           "video_engine": (ch.get("video") or {}).get("engine")}
    items, missing = {}, []
    for key, label in SETUP_LABELS:
        v = raw.get(key)
        ok = bool(v)
        items[key] = {"ok": ok, "label": ("%s：%s" % (label, v)) if ok else label,
                      "value": v or "", "missing": [] if ok else [label]}
        if not ok:
            missing.append(label)
    # ★ 顶层 ok 表示「数据取到了」，齐备性在 data.ok —— 两者混用会让「缺 6 项」
    #   被 norm_setup 判成「接口失败」，UI 显示「未接入」而不是「缺这几项」。
    return {"ok": True, "rc": 0, "exit": None, "reason": "",
            "data": {"items": items, "missing": missing, "ok": not missing,
                     "derived": {"source": str(p)}},
            "text_tail": "", "elapsed": 0.0}


def style_status(ws) -> dict:
    return run_json("drama", ["style", "status", "--json"], ws, ttl=10)


def models_status(ws) -> dict:
    return run_json("drama", ["models", "status", "--json"], ws, ttl=10)


def drama_status(ws) -> dict:
    """全盘状态：分镜/提示词/参考图/资产缺口/H3 就绪/批次/台账。"""
    return run_json("drama", ["status", "--json"], ws, ttl=5)


def env_check() -> dict:
    """环境自检（零网络）。不依赖工作区。"""
    return run_json("env", ["--json"], None, ttl=60)


def cost_ledger(ws, *, balance: bool = False) -> dict:
    args = ["--json", "--no-write"]
    if balance:
        args.append("--balance")
    return run_json("cost_ledger", args, ws, ttl=20, timeout=120)


def continuity(ws) -> dict:
    """已下线（2026-11-02，分支 feat/pack-engine）。

    `script_continuity.py` 是**剧作层**的五锚检查（镜号/台词指纹/代号/时长），
    它服务的对象是「引擎自己写剧本」。创作移出引擎后，这套锚点由创作 Skill 保证，
    引擎只校验制作包的结构（`stages/import/pack_spec.py`）。

    保留这个空函数是为了让老调用方拿到「明确的下线结果」而不是 AttributeError ——
    静默消失会让人以为「检查通过了」。
    """
    return {"ok": False, "skipped": True,
            "error": "剧本连续性门禁已随创作层下线（画风/剧本/分镜改由制作包提供）"}


# ---------------------------------------------------------------------------
# 归一化：把引擎结构整理成 UI 可直接渲染的形状（只搬字段，不重新判定）
# ---------------------------------------------------------------------------
STATE_OF = {True: "done", False: "todo"}


NODE_DONE = ("passed", "skipped")


def release_status(ws) -> dict:
    """G9 发行资料齐全度（**只读**：`--no-write` 不落 release-manifest.json）。

    发行页原来写「G9 未接入」，理由是「release_check 会写盘，不当只读接口」。
    这个理由成立，但结论不必是「不接」—— 给脚本加一个 `--no-write` 就行：
    检查结论是纯计算，写盘只是为了留痕。
    """
    return run_json("release_check", ["--json", "--no-write"], ws, ttl=20)


def release_export_preview(ws) -> dict:
    """导出发布版的**干跑**预览（只读：不带 `--apply`，不写 09-发行/剧集/）。

    返回 `plans`（会导出哪几集、从哪来）与 `fails`（被门禁拦下的原因）。
    """
    return run_json("release_export", ["--all", "--json"], ws, ttl=20)


def norm_workflow(res: dict) -> dict:
    """23 节点 → 7 环节视图：`{ok, current, complete, stages[], nodes[]}`。

    每个环节的 state 由**该环节下所有节点**决定：
      · done    —— 全部 passed/skipped
      · current —— 第一个仍有未完成节点的环节
      · todo    —— 其后的环节
    `probes` 放节点明细，前端据此显示「这个环节还差哪几个节点」，而不是一句笼统的「未完成」。

    ★ 2026-11-01：上一版读的是 `workflow.py` 的 S1–S11（脚本已删），且与 `nodes.py` 的
      23 节点是两套模型 —— 同一个「下一步该做什么」在 CLI 与 UI 上给两个答案。现在只有一个。
    """
    if not res.get("ok") or not isinstance(res.get("data"), dict):
        return {"ok": False, "reason": res.get("reason") or "no_json", "stages": [],
                "current": None, "complete": False, "ctx": {}, "nodes": [],
                "text_tail": res.get("text_tail", "")}
    d = res["data"]
    nodes = d.get("nodes") or []
    by_stage = {}
    for n in nodes:
        by_stage.setdefault(n.get("stage") or "?", []).append(n)

    current, stages = None, []
    for sdef in (d.get("stages") or []):
        sid = sdef.get("id")
        items = by_stage.get(sid) or []
        done_n = [n for n in items if n.get("state") in NODE_DONE]
        done = bool(items) and len(done_n) == len(items)
        if not done and current is None:
            current = sid
        stages.append({
            "id": sid, "name": sdef.get("name") or sid, "kind": "", "optional": False,
            "dir": "", "done": done, "by_artifact": False, "by_manual": False,
            "state": "done" if done else ("current" if sid == current else "todo"),
            "probes": [{"label": n.get("id"), "ok": n.get("state") in NODE_DONE,
                        "found": n.get("state"), "need": "passed"} for n in items],
            "what": sdef.get("why") or "",
            "note": ("%d/%d 节点完成" % (len(done_n), len(items))) if items else "无节点",
        })
    return {"ok": True, "current": current,
            "complete": bool(stages) and all(x["done"] for x in stages),
            "ctx": {"counts": d.get("counts") or {}},
            "stages": stages, "nodes": nodes, "pending_optional": [], "reason": ""}


def norm_setup(res: dict) -> dict:
    """setup show → 九项列表（标出缺哪项）。"""
    if not res.get("ok") or not isinstance(res.get("data"), dict):
        return {"ok": False, "reason": res.get("reason") or "no_json", "items": [], "missing": []}
    d = res["data"]
    items = []
    for key, v in (d.get("items") or {}).items():
        if not isinstance(v, dict):
            continue
        items.append({
            "key": key, "ok": bool(v.get("ok")),
            "label": v.get("label") or v.get("value") or v.get("choice") or "",
            "detail": {k: v[k] for k in ("count", "seconds", "shots_min", "shots_max", "engine_arg",
                                         "kind", "ref", "site", "alias", "fingerprint", "source",
                                         "deliver", "source_megapixels", "steps", "megapixels",
                                         "voice", "concurrency", "budget_cap_coins", "budget_cap_cny")
                       if k in v},
            "missing": v.get("missing") or [],
        })
    return {"ok": True, "items": items, "missing": d.get("missing") or [],
            "ready": bool(d.get("ok")), "derived": d.get("derived") or {}}
