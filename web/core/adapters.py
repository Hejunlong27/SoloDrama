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

import time
from pathlib import Path

from . import jsonout, paths, runner

# 只读子命令的脚本位置（与 commands.SCRIPTS 同一批文件，这里只挑读类）
SCRIPTS = {
    "workflow": paths.PROD_SCRIPTS / "workflow.py",
    "setup": paths.PROD_SCRIPTS / "project_setup.py",
    "drama": paths.PROD_SCRIPTS / "drama.py",
    "env": paths.TOOLS_DIR / "env_check.py",
    "cost_ledger": paths.PROD_SCRIPTS / "cost_ledger.py",
    "continuity": paths.PROD_SCRIPTS / "script_continuity.py",
    "release_check": paths.PROD_SCRIPTS / "release_check.py",
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
    """S1–S11 流程状态（唯一真源：workflow.py，带 probes 判据）。"""
    return run_json("workflow", ["status", "--workspace", ws, "--json"], ws, ttl=5)


def setup_show(ws) -> dict:
    """开工前置九项（G-0）。"""
    return run_json("setup", ["show", "--workspace", ws, "--json"], ws, ttl=10)


def style_status(ws) -> dict:
    return run_json("drama", ["style", "status", "--json"], ws, ttl=10)


def models_status(ws) -> dict:
    return run_json("drama", ["models", "status", "--json"], ws, ttl=10)


def drama_status(ws) -> dict:
    """全盘状态：分镜/提示词/参考图/资产缺口/H3 就绪/批次/台账。"""
    return run_json("drama", ["status", "--json"], ws, ttl=5)


def env_check() -> dict:
    """环境自检（零网络）。不依赖工作区。"""
    return run_json("env", ["--json"], None, ttl=30)


def cost_ledger(ws, *, balance: bool = False) -> dict:
    args = ["--json", "--no-write"]
    if balance:
        args.append("--balance")
    return run_json("cost_ledger", args, ws, ttl=20, timeout=120)


def continuity(ws) -> dict:
    return run_json("continuity", ["--json"], ws, ttl=10)


def workflow_check(ws, stage: str) -> dict:
    """G10 顺序门禁。rc=4 表示前置未完成（不是错误）。"""
    return run_json("workflow", ["check", "--stage", stage, "--workspace", ws], ws)


# ---------------------------------------------------------------------------
# 归一化：把引擎结构整理成 UI 可直接渲染的形状（只搬字段，不重新判定）
# ---------------------------------------------------------------------------
STATE_OF = {True: "done", False: "todo"}


def norm_workflow(res: dict) -> dict:
    """workflow status → {ok, current, complete, ctx, stages[], reason}"""
    if not res.get("ok") or not isinstance(res.get("data"), dict):
        return {"ok": False, "reason": res.get("reason") or "no_json",
                "stages": [], "current": None, "complete": False, "ctx": {},
                "text_tail": res.get("text_tail", "")}
    d = res["data"]
    stages = []
    for s in d.get("stages") or []:
        stages.append({
            "id": s.get("id"), "name": s.get("name"), "kind": s.get("kind"),
            "optional": bool(s.get("optional")), "dir": s.get("dir"),
            "done": bool(s.get("done")),
            "by_artifact": bool(s.get("by_artifact")),
            "by_manual": bool(s.get("by_manual")),
            "skipped": bool(s.get("skipped")),
            "state": "done" if s.get("done") else ("current" if s.get("id") == d.get("current") else "todo"),
            "probes": [{"label": p.get("label"), "ok": bool(p.get("ok")),
                        "found": p.get("found"), "need": p.get("need")}
                       for p in (s.get("probes") or [])],
            "what": s.get("what", ""), "note": s.get("note", ""),
        })
    return {"ok": True, "current": d.get("current"), "complete": bool(d.get("complete")),
            "ctx": d.get("ctx") or {}, "stages": stages, "pending_optional": d.get("pending_optional") or [],
            "reason": ""}


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
