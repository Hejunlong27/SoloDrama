# -*- coding: utf-8 -*-
"""app.py —— SoloDrama Web 控制台（FastAPI）

分层纪律（重要）：
  * 本层是「观察者 + 调度者」，不是「实现者」：
      - 读 → 工作区 JSON（真源）或引擎 CLI 的 `--json`；
      - 写 → 只走白名单 CLI 子进程（`core/runner.py`）；
      - 判断 → 退出码（0/2/3/4/130），**不解析人类文本判成败**。
  * 引擎侧零改动；删掉 web/ 即完全回滚。

启动：python web/run_console.py   （默认 http://127.0.0.1:8788）
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from core import commands as CMD
from core import inventory, jobs, paths, reader, runner, ux

app = FastAPI(title="SoloDrama 控制台", version="0.1.0",
              description="AI 短剧批量生产引擎的本地操控台（观察者 + 调度者）")

READONLY_MODE = os.environ.get("SOLODRAMA_CONSOLE_READONLY", "") not in ("", "0", "false")


# ---------------------------------------------------------------------------
# 剧项目注册表
# ---------------------------------------------------------------------------
MARKERS = ("layout.json", "model-plan.json", "video-pipeline")


def _registry() -> dict:
    data = paths.read_json(paths.REGISTRY_FILE, default=None) or {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("items", [])
    if not data.get("current"):
        env_ws = os.environ.get("SOLODRAMA_WORKSPACE") or os.environ.get("DRAMA_WORKSPACE")
        if env_ws and Path(env_ws).is_dir():
            data["current"] = str(Path(env_ws).resolve())
    if not data.get("current") and data["items"]:
        data["current"] = data["items"][0]["path"]
    return data


def _i_workspaces() -> dict:
    reg = _registry()
    known = {it["path"] for it in reg["items"]}
    for extra in (reg.get("current"),):
        if extra and extra not in known:
            reg["items"].insert(0, {"path": extra, "title": Path(extra).name,
                                    "added_at": time.time()})
            known.add(extra)
    # 合并「本机扫描」结果：把有产出的剧补进来，并给每一项标注产出与花费
    scanned = {}
    try:
        for it in inventory.discover().get("items") or []:
            scanned[str(Path(it["path"]).resolve())] = it
            if it["path"] not in known:
                reg["items"].append({"path": it["path"], "title": it["name"],
                                     "added_at": time.time(), "discovered": True})
                known.add(it["path"])
    except Exception:  # noqa: BLE001
        pass
    for it in reg["items"]:
        p = Path(it["path"])
        it["exists"] = p.is_dir()
        it["is_workspace"] = any((p / m).exists() for m in MARKERS)
        it["title"] = it.get("title") or p.name
        s = scanned.get(str(p.resolve())) if it["exists"] else None
        if s:
            it["images"] = s["images"]
            it["yuan"] = s["yuan"]
            it["has_output"] = s["has_output"]
            it["updated_text"] = s["updated_text"]
    reg["items"].sort(key=lambda x: (x.get("images") or 0, x.get("added_at") or 0), reverse=True)
    return reg


def _require_ws(ws: str) -> Path:
    if not ws:
        raise HTTPException(status_code=400, detail="缺少 ws（剧项目工作区路径）")
    p = Path(ws).expanduser()
    if not p.is_dir():
        raise HTTPException(status_code=400, detail="工作区不存在：%s" % p)
    return p.resolve()


# ---------------------------------------------------------------------------
# 基础
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {
        "ok": True,
        "time": time.time(),
        "python": paths.engine_python(),
        "repo": str(paths.REPO_ROOT),
        "readonly": READONLY_MODE,
        "locks": jobs.lock_status(),
    }


@app.get("/api/workspaces")
def workspaces():
    return _i_workspaces()


@app.get("/api/workspaces/discover")
def discover_workspaces(refresh: int = 0):
    """扫描本机候选目录，列出所有短剧项目及产出摘要（解决「在 A 里找 B 的图」）。"""
    return inventory.discover(refresh=bool(refresh))


@app.post("/api/workspaces")
def register_workspace(payload: dict = Body(...)):
    p = _require_ws(payload.get("path"))
    reg = _registry()
    hit = [it for it in reg["items"] if it["path"] == str(p)]
    if not hit:
        reg["items"].insert(0, {"path": str(p), "title": payload.get("title") or p.name,
                                "added_at": time.time()})
    reg["current"] = str(p)
    paths.write_json(paths.REGISTRY_FILE, reg)
    reader.clear_cache()
    return _i_workspaces()


@app.post("/api/workspaces/current")
def set_current(payload: dict = Body(...)):
    p = _require_ws(payload.get("path"))
    reg = _registry()
    reg["current"] = str(p)
    paths.write_json(paths.REGISTRY_FILE, reg)
    reader.clear_cache()
    return _i_workspaces()


# ---------------------------------------------------------------------------
# 用户端接口（面向「做短剧的人」：只有人话，没有命令 / 退出码 / 门禁代号）
# ---------------------------------------------------------------------------
@app.get("/api/home")
def home(ws: str = Query(...)):
    """一屏回答：这部剧现在怎么样、今天该做什么、花了多少、有什么卡住。"""
    return ux.home(str(_require_ws(ws)))


@app.get("/api/tasks")
def tasks(ws: str = Query(default=None)):
    w = str(_require_ws(ws)) if ws else None
    return {
        "items": [t.as_dict() for t in ux.TASKS],
        "next": ux.next_task(w) if w else None,
        "note": "用户端只暴露「要做什么」，命令与参数在开发者端（/ui/advanced.html）",
    }


@app.get("/api/tasks/{task_id}")
def task_detail(task_id: str, ws: str = Query(...)):
    return ux.task_detail(str(_require_ws(ws)), task_id)


@app.get("/api/episodes")
def episodes(ws: str = Query(...)):
    w = str(_require_ws(ws))
    st = reader.status(w).get("data") or {}
    return {"items": ux.episodes(st, None)}


@app.get("/api/glossary")
def glossary():
    return {"items": [{"term": t, "meaning": m} for t, m in ux.GLOSSARY]}


@app.post("/api/help")
def help_prompt(payload: dict = Body(...)):
    """「把问题交给 AI 助手」——用户不用写提示词，系统拼好给他复制。"""
    w = str(_require_ws(payload.get("ws")))
    return ux.help_prompt(w, (payload.get("topic") or "").strip())


# ---------------------------------------------------------------------------
# 开发者端接口（命令目录 / 作业 / 审计 / 锁）
# ---------------------------------------------------------------------------
@app.get("/api/commands")
def commands(ws: str = Query(default=None)):
    return {
        "groups": CMD.groups(),
        "items": CMD.catalog(ws),
        "readonly": READONLY_MODE,
        "ws": ws,
        "note": "工作区通过环境变量 SOLODRAMA_WORKSPACE 注入子进程（引擎 CLI 无 --workspace 全局参数）",
    }


# ---------------------------------------------------------------------------
# 只读聚合
# ---------------------------------------------------------------------------
@app.get("/api/overview")
def overview(ws: str = Query(...)):
    return reader.overview(_require_ws(ws))


@app.get("/api/pipeline")
def pipeline(ws: str = Query(...)):
    return reader.pipeline(_require_ws(ws))


@app.get("/api/gates")
def gates(ws: str = Query(...)):
    w = _require_ws(ws)
    return {"style": reader.style_gate(w), "models": reader.model_gate(w)}


@app.get("/api/locks")
def locks():
    return jobs.lock_status()


@app.get("/api/audit")
def audit(limit: int = 100):
    return {"items": jobs.audit_log(limit)}


# ---------------------------------------------------------------------------
# 执行：同步（只读/快命令）
# ---------------------------------------------------------------------------
def _prepare(spec_id: str, params: dict, ws: str):
    cmd = CMD.get(spec_id)
    if cmd is None:
        raise HTTPException(status_code=404, detail="未知命令：%s" % spec_id)
    v = cmd.validate(params or {})
    if not v["ok"]:
        raise HTTPException(status_code=422, detail={"errors": v["errors"], "params": [p.as_dict() for p in cmd.params]})
    w = _require_ws(ws)
    argv = cmd.build_argv(v["values"], w)
    return cmd, v["values"], argv, str(w)


def _guard(cmd, values, payload) -> None:
    """危险操作闸门：只读模式 / 计费确认 / 危险确认。"""
    if READONLY_MODE and cmd.danger > CMD.READ:
        raise HTTPException(status_code=423, detail="控制台处于只读模式（SOLODRAMA_CONSOLE_READONLY=1）")
    if cmd.billing == CMD.PAID:
        conf = payload.get("confirm") or {}
        if not conf.get("ack"):
            raise HTTPException(status_code=428, detail={
                "need_confirm": True,
                "reason": "本命令★计费，必须在控制台显式确认后才可提交",
                "cmd": cmd.id, "title": cmd.title, "gate": cmd.gate,
                "argv_preview": " ".join(cmd.build_argv(values)[1:]),
            })
        resume = values.get("resume")
        if resume and str(conf.get("batch") or "").strip() != str(resume):
            raise HTTPException(status_code=428, detail={
                "need_confirm": True,
                "reason": "续跑必须回填批次号以二次确认（防止误触发全量重跑造成重复扣费）",
                "expect_batch": resume,
            })


@app.post("/api/run")
def run_sync(payload: dict = Body(...)):
    spec_id = payload.get("spec_id") or ""
    cmd, values, argv, w = _prepare(spec_id, payload.get("params") or {}, payload.get("ws"))
    _guard(cmd, values, payload)

    if cmd.mode == "job":
        job = jobs.create_job(w, cmd, argv, values, estimate=payload.get("estimate") or "",
                              note=payload.get("note") or "")
        return JSONResponse({"mode": "job", "job": job}, status_code=202)

    t0 = time.time()
    res = runner.run_stream(argv, ws=w, timeout=int(payload.get("timeout") or 180))
    out = {
        "mode": "sync",
        "spec_id": cmd.id, "title": cmd.title,
        "argv_display": " ".join(argv[1:]),
        "rc": res["rc"], "exit": runner.exit_meaning(res["rc"]),
        "elapsed": res["elapsed"],
        "stdout": "\n".join(res["lines"][-400:]),
    }
    out["friendly"] = ux.friendly_error(res["rc"], out["stdout"])
    with jobs._conn() as c:                                        # noqa: SLF001
        c.execute("""INSERT INTO audit(ts, ws, spec_id, argv, exit_code, estimate, note, actor)
                     VALUES(?,?,?,?,?,?,?,?)""",
                  (time.time(), w, cmd.id, json.dumps(argv, ensure_ascii=False),
                   res["rc"], "免费（只读/快命令）", payload.get("note") or "", "console"))
    return out


# ---------------------------------------------------------------------------
# 作业
# ---------------------------------------------------------------------------
@app.get("/api/jobs")
def list_jobs(ws: str = Query(default=None), limit: int = 50):
    return {"items": jobs.list_jobs(ws, limit), "locks": jobs.lock_status()}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, after: int = 0):
    j = jobs.get_job(job_id)
    if not j:
        raise HTTPException(status_code=404, detail="作业不存在")
    evs = jobs.events(job_id, after=after)
    tail = "\n".join(e["text"] for e in jobs.events(job_id)[-40:])
    friendly = None
    if j["status"] not in ("queued", "running"):
        friendly = ux.friendly_error(j.get("exit_code"), tail)
    start = j.get("started_at") or j.get("created_at") or time.time()
    end = j.get("ended_at") or time.time()
    return {"job": j, "events": evs, "friendly": friendly,
            "elapsed_sec": max(0, int(end - start))}


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    if not jobs.get_job(job_id):
        raise HTTPException(status_code=404, detail="作业不存在")
    return jobs.request_cancel(job_id)


def _sse(gen):
    return StreamingResponse(gen, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _sse_pack(seq, kind, text, job_id=None) -> str:
    data = json.dumps({"seq": seq, "kind": kind, "text": text, "job_id": job_id},
                      ensure_ascii=False)
    return "id: %s\ndata: %s\n\n" % (seq, data)


@app.get("/api/jobs/{job_id}/stream")
async def stream_job(job_id: str, after: int = Query(default=0)):
    async def gen():
        cursor = int(after or 0)
        idle = 0
        yield "retry: 3000\n\n"
        while True:
            evs = jobs.events(job_id, after=cursor)
            for e in evs:
                cursor = e["seq"]
                idle = 0
                yield _sse_pack(e["seq"], e["kind"], e["text"], job_id)
            j = jobs.get_job(job_id)
            if not evs:
                idle += 1
                if idle % 20 == 0:
                    yield ": keep-alive\n\n"
            if j and j["status"] not in ("queued", "running") and not evs:
                yield _sse_pack(cursor, "closed", j["status"])
                return
            await asyncio.sleep(0.5)
    return _sse(gen())


@app.get("/api/events/stream")
async def stream_all(after: int = Query(default=0)):
    async def gen():
        cursor = int(after or 0)
        yield "retry: 3000\n\n"
        while True:
            evs = jobs.events_since(cursor)
            for e in evs:
                cursor = e["seq"]
                yield _sse_pack(e["seq"], e["kind"], e["text"], e.get("job_id"))
            yield ": keep-alive\n\n"
            await asyncio.sleep(2.0)
    return _sse(gen())


# ---------------------------------------------------------------------------
# 启动钩子与静态资源
# ---------------------------------------------------------------------------
@app.on_event("startup")
def _startup():
    paths.ensure_var_dirs()
    jobs.init_db()
    jobs.start_scheduler()


UI_DIR = paths.WEB_DIR / "ui"
if UI_DIR.is_dir():
    app.mount("/ui", StaticFiles(directory=str(UI_DIR), html=True), name="ui")


@app.get("/")
def root():
    return RedirectResponse("/ui/")
