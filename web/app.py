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
import mimetypes
import os
import re
import time
import urllib.parse
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from core import (adapters, artifacts, commands as CMD, connections, generators,
                    health as health_mod, inventory, jobs, paths, pipeline, reader, runner,
                    studio, ux)
from core.llm import drafts as llm_drafts, gateway as llm_gateway, store as llm_store
from core.llm import templates as llm_templates
from core.llm.errors import LLMError

# ★ 静态资源的 MIME 必须显式钉住：Windows 上 mimetypes 会读注册表，
#   历史机器可能把 .js 报成 text/plain —— 浏览器会拒绝加载 ES module。
for _ext, _type in ((".js", "text/javascript"), (".mjs", "text/javascript"),
                    (".css", "text/css"), (".svg", "image/svg+xml"),
                    (".json", "application/json"), (".woff2", "font/woff2"),
                    (".webmanifest", "application/manifest+json"), (".ico", "image/x-icon")):
    mimetypes.add_type(_type, _ext)

app = FastAPI(title="SoloDrama 控制台", version="0.2.0",
              description="AI 短剧批量生产引擎的本地操控台（观察者 + 调度者）")

READONLY_MODE = os.environ.get("SOLODRAMA_CONSOLE_READONLY", "") not in ("", "0", "false")

# ---------------------------------------------------------------------------
# 访问保护（Studio 阶段新增）
# ---------------------------------------------------------------------------
# 策略（默认值见 web/STUDIO.md「配置」一节）：
#   * 只允许回环 Host（127.0.0.1 / localhost / ::1）访问；其它 Host 一律 403 —— 防 DNS rebinding；
#   * 跨站来源的**写请求**拒绝（Origin / Sec-Fetch-Site 双判据）；
#   * 非本机客户端（局域网）必须带 `X-Console-Token`，且服务端必须配置了
#     `SOLODRAMA_CONSOLE_TOKEN`；没配 token 就**不允许**局域网访问（宁可不可用，也不裸奔）。
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1", "0.0.0.0")
_ALLOWED_HOSTS = set(LOOPBACK_HOSTS)
for _h in (os.environ.get("SOLODRAMA_CONSOLE_ALLOWED_HOSTS") or "").split(","):
    if _h.strip():
        _ALLOWED_HOSTS.add(_h.strip().lower())

CONSOLE_TOKEN = (os.environ.get("SOLODRAMA_CONSOLE_TOKEN") or "").strip()


def _is_loopback(host: str) -> bool:
    h = (host or "").strip().lower()
    return h in ("127.0.0.1", "::1", "localhost", "testclient")


def _host_ok(host: str) -> bool:
    return (host or "").split(":")[0].strip().lower() in _ALLOWED_HOSTS


def _origin_ok(request) -> bool:
    """写请求的来源校验：无 Origin（同源导航/命令行）放行，跨站一律拒绝。"""
    origin = request.headers.get("origin")
    if origin:
        try:
            from urllib.parse import urlparse
            oh = (urlparse(origin).hostname or "").lower()
        except ValueError:
            return False
        if not _host_ok(oh):
            return False
    site = (request.headers.get("sec-fetch-site") or "").lower()
    if site and site not in ("same-origin", "none"):
        return False
    return True


@app.middleware("http")
async def _access_guard(request, call_next):
    host = request.headers.get("host") or ""
    if not _host_ok(host):
        return JSONResponse({"detail": "Host 不被允许（仅限本机访问）"}, status_code=403)
    client = getattr(request.client, "host", "") or ""
    if not _is_loopback(client):
        # 局域网/远程：必须显式开启 token，否则一律拒绝
        if not CONSOLE_TOKEN:
            return JSONResponse({"detail": "非本机访问已禁用（未配置 SOLODRAMA_CONSOLE_TOKEN）"},
                                status_code=403)
        if request.headers.get("x-console-token") != CONSOLE_TOKEN:
            return JSONResponse({"detail": "缺少或错误的访问令牌"}, status_code=401)
    if request.method not in ("GET", "HEAD", "OPTIONS") and not _origin_ok(request):
        return JSONResponse({"detail": "跨站请求被拒绝"}, status_code=403)
    return await call_next(request)


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
        # ★ 兜底也必须挑「真实存在」的那一个：登记表里常年混着已删除/已改名的旧路径
        #   （实测 `D:\剧本\海外剧\3`），拿 items[0] 兜底会把用户直接送进一个不存在的目录。
        live = [it for it in data["items"] if Path(it.get("path") or "").is_dir()]
        data["current"] = (live or data["items"])[0]["path"]
    return data


def _i_workspaces() -> dict:
    reg = _registry()
    known = {it["path"] for it in reg["items"]}
    # ★ 2026-10-28：**不再**把「当前工作区」硬塞进 items。
    #   旧逻辑 `for extra in (reg.get("current"),)` 会把一个已删除的目录伪造成项目卡片
    #   （exists=false），既污染清单又参与排序。当前目录是否可用改由 `current_exists` 表达，
    #   无效时下面会自愈到真实项目。
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
            it["loose"] = s.get("loose", 0)
            it["yuan"] = s["yuan"]
            it["has_output"] = s["has_output"]
            it["updated_text"] = s["updated_text"]
    reg["items"].sort(key=lambda x: ((x.get("images") or 0) + (x.get("loose") or 0),
                                     x.get("added_at") or 0), reverse=True)

    # ---- 当前工作区自愈：绝不把用户留在死路径上 ----
    cur = str(reg.get("current") or "")
    replaced = ""
    if not (cur and Path(cur).is_dir()):
        live = [it for it in reg["items"] if it["exists"]]
        pick = next((it for it in live if it.get("is_workspace")), live[0] if live else None)
        reg["current"] = pick["path"] if pick else ""
        replaced = cur
        if pick:                                  # 只在真的换成了可用目录时才落盘
            paths.write_json(paths.REGISTRY_FILE, _registry_clean(reg))
    reg["current_exists"] = bool(reg.get("current")) and Path(reg["current"]).is_dir()
    reg["stale"] = [it["path"] for it in reg["items"] if not it["exists"]]
    if replaced:
        # 只用于界面上解释「为什么当前项目变了」，不写入注册表
        reg["current_replaced"] = replaced
    return reg


# 这些是 `_i_workspaces()` **算出来**的字段，不属于注册表。落盘时必须剥掉：
# 一旦写回去，下次读到的「注册表」就混着上次的扫描结果（images/loose 会越写越旧），
# 而且 `exists` 会变成过期快照 —— 用户删了目录，卡片却还显示存在。
_REG_COMPUTED = {"exists", "is_workspace", "images", "loose", "yuan", "has_output",
                 "updated_text", "current_exists", "stale", "current_replaced"}


def _registry_clean(reg: dict) -> dict:
    """只保留注册表该有的字段（写盘前统一过一遍）。"""
    out = {k: v for k, v in reg.items() if k not in _REG_COMPUTED}
    out["items"] = [{k: v for k, v in (it or {}).items() if k not in _REG_COMPUTED}
                    for it in (reg.get("items") or [])]
    return out


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


@app.get("/api/health/checks")
def health_checks(ws: str = Query(default="")):
    """环境体检（现算，不读缓存）。只读：跑 env_check + 探本地目录写入。

    ⚠ 函数名不能叫 `health`：本文件上面已有 `/api/health` 的处理函数 `health()`，
    同名会在模块级覆盖 `core.health` 模块（和 pipeline 那次同一个坑）。
    """
    return health_mod.collect(str(ws or "").strip() or None)


@app.post("/api/health/fix")
def health_run_fix(payload: dict = Body(...)):
    """执行一个修复动作。只接受体检清单里标了 auto 的 id，命令由服务端现算。"""
    _write_guard()
    fid = str(payload.get("id") or "").strip()
    if not fid:
        raise HTTPException(status_code=400, detail="缺少要修复的项 id")
    ws = str(payload.get("ws") or "").strip() or None
    return health_mod.fix(fid, ws)


@app.get("/api/health/fixes")
def health_fixes(limit: int = 30):
    """修复历史（谁在什么时候改了什么、复检过没过）。"""
    return health_mod.history(limit)


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
    paths.write_json(paths.REGISTRY_FILE, _registry_clean(reg))
    reader.clear_cache()
    return _i_workspaces()


@app.post("/api/projects/create")
def project_create(payload: dict = Body(...)):
    """新建剧项目：调用引擎真实的脚手架（`creation.py scaffold`），然后自动登记。

    ★ 为什么不能走 `/api/run`：那条路要求 `ws` 已存在，而脚手架本身就是**建目录**。
    安全：只读模式拦截；目标必须是绝对路径；已存在且非空的目录一律拒绝（不覆盖任何东西）。
    """
    _write_guard()
    target = str(payload.get("target") or "").strip()
    slug = str(payload.get("slug") or "").strip().lower()
    title = str(payload.get("title") or "").strip()
    if not target:
        raise HTTPException(status_code=400, detail="缺少目标目录")
    p = Path(target).expanduser()
    if not p.is_absolute():
        raise HTTPException(status_code=400, detail="目标目录必须是绝对路径（如 D:/剧本/我的新剧）")
    p = Path(os.path.normpath(str(p)))
    if p.exists():
        if not p.is_dir():
            raise HTTPException(status_code=400, detail="目标路径已存在且不是目录")
        if any(p.iterdir()):
            raise HTTPException(status_code=409,
                                detail="目标目录已存在且非空；请换一个空目录，控制台不覆盖已有文件")
    if not re.match(r"^[a-z0-9][a-z0-9_-]{1,40}$", slug):
        raise HTTPException(status_code=400, detail="短标识只允许小写字母/数字/连字符，2-40 位")
    if not title:
        raise HTTPException(status_code=400, detail="缺少剧名")
    if any(ch in title for ch in "\r\n\t"):
        raise HTTPException(status_code=400, detail="剧名不允许换行")

    try:
        ep = int(payload.get("ep") or 30)
        sec = int(payload.get("sec") or 60)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="集数/秒数必须是整数") from None
    if not (1 <= ep <= 200):
        raise HTTPException(status_code=400, detail="集数应在 1-200")
    if sec not in (60, 70, 90):
        raise HTTPException(status_code=400, detail="单集秒数只支持 60 / 70 / 90")
    platform = str(payload.get("platform") or "ReelShort").strip()[:40] or "ReelShort"

    cmd = CMD.get("project.scaffold")
    values = {"target": str(p), "slug": slug, "title": title,
              "platform": platform, "ep": ep, "sec": sec}
    argv = cmd.build_argv(values, None)
    res = runner.run_stream(argv, ws=None, timeout=180)
    ok = res["rc"] == 0
    text = runner.mask_text("\n".join(res["lines"][-200:]))

    registered = False
    if ok and p.is_dir():
        reg = _registry()
        if not any(it["path"] == str(p) for it in reg["items"]):
            reg["items"].insert(0, {"path": str(p), "title": title, "added_at": time.time()})
        reg["current"] = str(p)
        paths.write_json(paths.REGISTRY_FILE, _registry_clean(reg))
        reader.clear_cache()
        registered = True

    jobs.record_audit(str(p), "project.scaffold", ["--workspace", str(p), "--slug", slug],
                      res["rc"], note=title, actor="studio")
    return {
        "ok": ok, "rc": res["rc"], "elapsed": res["elapsed"],
        "argv_display": " ".join(str(a) for a in argv[1:]),
        "stdout": text,
        "friendly": None if ok else ux.friendly_error(res["rc"], text),
        "target": str(p), "title": title, "registered": registered,
    }


@app.post("/api/workspaces/current")
def set_current(payload: dict = Body(...)):
    p = _require_ws(payload.get("path"))
    reg = _registry()
    reg["current"] = str(p)
    paths.write_json(paths.REGISTRY_FILE, _registry_clean(reg))
    reader.clear_cache()
    return _i_workspaces()


@app.post("/api/workspaces/prune")
def prune_workspaces():
    """清掉登记表里已不存在的目录（只动注册表，**不删任何磁盘文件**）。

    为什么需要：项目列表经年累积会混进已删除/已改名的路径，界面上表现为
    「登记了 N 个、只显示 M 个」（前端过滤 exists），数字对不上又无从清理。
    """
    _write_guard()
    reg = _registry()
    keep, gone = [], []
    for it in reg["items"]:
        (keep if Path(it.get("path") or "").is_dir() else gone).append(it)
    if gone:
        reg["items"] = keep
        cur = str(reg.get("current") or "")
        if cur and not Path(cur).is_dir():
            reg["current"] = keep[0]["path"] if keep else ""
        paths.write_json(paths.REGISTRY_FILE, _registry_clean(reg))
        reader.clear_cache()
    return {"ok": True, "removed": [it["path"] for it in gone], "kept": len(keep),
            **_i_workspaces()}


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
    """按集汇总（真源：<out>/<批次>/summary.json 的 shots[]，跨批次按镜头去重）。

    ★ 2026-10-22 修复：旧实现读 `drama.py status --json` 的 `batch["shots"]`，
      而该字段并不存在（batches 只给 totals/usage/elapsed/fuse），因此**恒返回空数组**。
    """
    w = str(_require_ws(ws))
    items = studio.episodes(w)
    for e in items:
        e["state_text"] = {"done": "已完成", "doing": "进行中", "fail": "有失败", "todo": "还没开始"}[e["state"]]
    return {"items": items, "count": len(items)}


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
def legacy_pipeline(ws: str = Query(...)):
    # ★ 函数名不能叫 pipeline：那会在模块级覆盖 core.pipeline 模块，
    #   导致下面 /api/pipeline/plan 里的 pipeline.plan 变成「函数对象没有 plan」→ 500。
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
    res = runner.run_stream(argv, ws=w, timeout=int(payload.get("timeout") or 180),
                            extra_env=cmd.env_for(values))
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
# Studio 只读接口（结构化优先；拿不到 JSON 时返回明确原因，不伪造数据）
# ---------------------------------------------------------------------------
CAPABILITIES = {
    "workflow": {"ok": True, "source": "workflow.py status --json（S1–S11 + probes）"},
    "episodes": {"ok": True, "source": "<out>/<批次>/summary.json 的 shots[]（跨批次按镜头去重）"},
    "shots": {"ok": True, "source": "同上，含每镜产物与错误"},
    "artifacts": {"ok": True, "source": "工作区相对路径白名单"},
    "media": {"ok": True, "source": "本地文件流（Range 支持，仅媒体 6 类）"},
    "cost": {"ok": True, "source": "ledger/runs/*.json 的 attempts[].usage"},
    "env": {"ok": True, "source": "tools/env_check.py --json"},
    "setup": {"ok": True, "source": "project_setup.py show --json（G-0 九项）"},
    "storyboard_edit": {"ok": False, "reason": "分镜与提示词由创作阶段产出，控制台只读展示，不提供在线编辑"},
    "script_edit": {"ok": False, "reason": "剧本正文由 AI 助手按四段法产出并落 03-剧本/，控制台不提供编辑器"},
    "bgm": {"ok": False, "reason": "bgm.py 尚未纳入命令白名单（需先补白名单与门禁口径）"},
    "character_audit": {"ok": False, "reason": "character_design.py 尚未纳入命令白名单"},
    "release_check": {"ok": False, "reason": "release_check.py 会写 09-发行/release-manifest.json，属写操作，下一批接入"},
    "release_export": {"ok": False, "reason": "release_export.py 尚未纳入命令白名单（默认干跑，需二次确认）"},
    "llm": {"ok": True, "source": "core/llm 统一网关（OpenAI 兼容 / Ollama；Key 只在后端）"},
    "llm_script_draft": {"ok": True, "source": "script.generate → 草稿 → 人工编辑 → confirm 落 03-剧本/"},
    "llm_usage": {"ok": True, "source": "web/var/llm/usage.jsonl（供应商返回的 usage，金额缺失即未知）"},
    "llm_stream": {"ok": False, "reason": "网关当前为非流式：SSE 逐字返回需要异步链路，下一批做"},
    "multi_user": {"ok": False, "reason": "当前只有「只读模式」，没有账号与权限体系"},
}


@app.get("/api/studio/capabilities")
def studio_capabilities():
    return {"items": CAPABILITIES, "readonly": READONLY_MODE}


@app.post("/api/studio/refresh")
def studio_refresh(ws: str = Query(default="")):
    studio.clear_cache()
    reader.clear_cache()
    return {"ok": True, "at": time.time()}


@app.get("/api/studio/overview")
def studio_overview(ws: str = Query(...)):
    return studio.overview(str(_require_ws(ws)))


@app.get("/api/studio/workflow")
def studio_workflow(ws: str = Query(...)):
    return adapters.norm_workflow(adapters.workflow_status(str(_require_ws(ws))))


@app.get("/api/studio/setup")
def studio_setup(ws: str = Query(...)):
    return adapters.norm_setup(adapters.setup_show(str(_require_ws(ws))))


@app.get("/api/studio/shots")
def studio_shots(ws: str = Query(...), ep: str = Query(default="")):
    w = str(_require_ws(ws))
    data = studio.shots(w)
    if ep:
        data = dict(data)
        data["items"] = [s for s in data["items"] if s["shot_id"].startswith(ep + "_")]
    return data


@app.get("/api/studio/episodes")
def studio_episodes(ws: str = Query(...)):
    w = str(_require_ws(ws))
    items = studio.episodes(w)
    for e in items:
        e["state_text"] = {"done": "已完成", "doing": "进行中", "fail": "有失败", "todo": "还没开始"}[e["state"]]
    return {"items": items, "count": len(items)}


@app.get("/api/studio/prompt")
def studio_prompt(ws: str = Query(...), shot: str = Query(...)):
    return studio.prompt_of(str(_require_ws(ws)), shot)


@app.get("/api/studio/cost")
def studio_cost(ws: str = Query(...)):
    return studio.cost(str(_require_ws(ws)))


@app.get("/api/studio/env")
def studio_env():
    res = adapters.env_check()
    return {"ok": res.get("ok"), "rc": res.get("rc"),
            "data": res.get("data"), "reason": res.get("reason"),
            "text_tail": res.get("text_tail") if not res.get("ok") else ""}


# ---------------------------------------------------------------------------
# 连接中心：LLM / ComfyUI / RunningHub 的配置、注入与只读探测
# 纪律：保存是写操作但不计费；测试一律只读（0 费用），不产生作业。
# ---------------------------------------------------------------------------
@app.get("/api/connections")
def connections_overview():
    return connections.overview()


@app.post("/api/connections/{kind}")
def connections_save(kind: str, payload: dict = Body(...)):
    k = str(kind or "").strip().lower()
    if k not in connections.KINDS:
        raise HTTPException(status_code=404, detail="未知通道：%s" % kind)
    if READONLY_MODE:
        raise HTTPException(status_code=403, detail="只读模式（demo）：连接配置不可修改")
    body = payload or {}
    patch = {k: {kk: vv for kk, vv in body.items() if kk not in ("api_key", "key", "apiKey")}}
    connections.save(patch)
    key = body.get("api_key")
    if key is not None:
        # 空串 = 清除；未传 = 保持不变。避免「只改地址」把 Key 抹掉。
        connections.set_key(k, key if str(key).strip() else None)
    return connections.overview()


@app.post("/api/connections/{kind}/test")
def connections_test(kind: str):
    k = str(kind or "").strip().lower()
    if k not in connections.KINDS:
        raise HTTPException(status_code=404, detail="未知通道：%s" % kind)
    return connections.test(k)


@app.get("/api/studio/asset-md")
def studio_asset_md(ws: str = Query(...)):
    """候选「资产提示词 md」（出图命令要把它注入 SOLODRAMA_ASSET_MD）。"""
    return studio.asset_mds(str(_require_ws(ws)))


@app.post("/api/generators/rh")
def api_generators_rh(payload: dict = Body(...)):
    """把「云端工作流出图」的四个关键值写进项目配置（t2i / i2i 分开）。

    为什么需要它：`config.local.json` 里 `image_providers` 的节点映射手写极易出错，
    而**写错的表现是「提交成功、钱扣了、图不对」**。这里只接受四个最小必要值，
    并做三件事：① 只改这一条 provider，其余键原样保留；② 写前备份；
    ③ 图生图必须同时给参考图节点，否则拒绝（不然就是白花钱）。
    """
    _write_guard()
    ws = _require_ws(payload.get("ws"))
    name = str(payload.get("provider") or "studio").strip()[:40] or "studio"
    t2i = str(payload.get("t2i_id") or "").strip()
    i2i = str(payload.get("i2i_id") or "").strip()
    prompt_node = str(payload.get("prompt_node") or "").strip()
    image_node = str(payload.get("image_node") or "").strip()
    if not prompt_node.isdigit():
        raise HTTPException(status_code=400, detail="提示词节点必须是数字节点 id")
    if i2i and not image_node.isdigit():
        raise HTTPException(status_code=400,
                            detail="填了图生图工作流就必须给「加载图像」节点 id，否则参考图不会被用上")
    if not (t2i or i2i):
        raise HTTPException(status_code=400, detail="至少要填一个工作流 ID（文生图或图生图）")

    cfg_path = ws / "video-pipeline" / "config.local.json"
    cfg = paths.read_json(cfg_path, default=None) or {}
    if not isinstance(cfg, dict):
        raise HTTPException(status_code=400, detail="config.local.json 不是对象，拒绝覆盖")
    bak = None
    if cfg_path.is_file():
        bak = cfg_path.with_suffix(".json.bak_%d" % int(time.time()))
        bak.write_text(cfg_path.read_text(encoding="utf-8"), encoding="utf-8")
    provs = cfg.setdefault("image_providers", {})
    cur = provs.get(name) if isinstance(provs.get(name), dict) else {}
    nodes = dict(cur.get("nodes") or {})
    nodes["prompt"] = {"nodeId": prompt_node, "fieldName": (nodes.get("prompt") or {}).get("fieldName", "value")}
    if image_node.isdigit():
        nodes["image"] = {"nodeId": image_node, "fieldName": (nodes.get("image") or {}).get("fieldName", "image")}
    item = dict(cur)
    item.update({"kind": cur.get("kind") or "workflow",
                 "id": t2i or cur.get("id", ""),
                 "id_i2i": i2i or cur.get("id_i2i", ""),
                 "nodes": nodes})
    provs[name] = item
    cfg["active_image_provider"] = name
    paths.write_json(cfg_path, cfg)
    reader.clear_cache()
    generators._CACHE.clear()
    return {"ok": True, "config_path": str(cfg_path), "provider": name,
            "backup": str(bak) if bak else "",
            **generators.channels(str(ws))}


@app.get("/api/pipeline/plan")
def api_pipeline_plan(ws: str = Query(...), budget: float = Query(default=0.0)):
    """流水线计划：11 个环节哪些能自动、哪些要人、哪些被前置挡住。只读。"""
    return pipeline.plan(str(_require_ws(ws)), budget=float(budget or 0))


@app.post("/api/pipeline/run")
def api_pipeline_run(payload: dict = Body(...)):
    """按计划推进（默认 dry_run：只回报会跑什么）。

    计费环节遵循「预算内自动放行」：`est_coins` 已知且不超预算才自动跑，
    估不出来就停下来问 —— 不猜金额。
    """
    ws = str(_require_ws(payload.get("ws")))
    budget = float(payload.get("budget") or 0)
    until = str(payload.get("until") or "").strip()
    try:
        max_steps = int(payload.get("max_steps") or 6)
    except (TypeError, ValueError):
        max_steps = 6
    dry_run = payload.get("dry_run", True)
    if not dry_run:
        _write_guard()
    return pipeline.run(ws, budget=budget, until=until,
                        max_steps=max(1, min(max_steps, 12)), dry_run=bool(dry_run))


@app.get("/api/generators")
def api_generators(ws: str = Query(default="")):
    """图像 / 视频 生成通道台账：能用哪条、缺什么、花不花钱。

    只读，不提交任务、不写配置；ComfyUI 只访问 /system_stats 与 /object_info。
    """
    return generators.channels(str(ws or "").strip() or None)


@app.get("/api/artifacts/loose")
def artifacts_loose(ws: str = Query(...)):
    """标准资产目录之外的图片（只读）。

    真实项目的图常在剧目录根下，资产页只读 `04-资产/` 会显示「空」——
    用户会以为产品不认识他的文件。这里只报告位置，不做任何移动。
    """
    return artifacts.loose_images(str(_require_ws(ws)))


@app.get("/api/artifacts")
def api_artifacts(ws: str = Query(...), dir: str = Query(default="")):
    w = str(_require_ws(ws))
    try:
        data = artifacts.list_dir(w, dir)
    except artifacts.PathDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    for it in data["items"]:
        if it["servable"]:
            it["url"] = "/media?ws=%s&rel=%s" % (urllib.parse.quote(w), urllib.parse.quote(it["rel"]))
    return data


@app.get("/api/file")
def api_file(ws: str = Query(...), rel: str = Query(...)):
    w = str(_require_ws(ws))
    try:
        data = artifacts.read_text(w, rel)
    except artifacts.PathDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    data["text"] = runner.mask_text(data.get("text") or "")
    return data


@app.get("/api/studio/media-info")
def api_media_info(ws: str = Query(...), rel: str = Query(...)):
    return studio.media_info(str(_require_ws(ws)), rel)


@app.get("/media")
def media_stream(request: Request, ws: str = Query(...), rel: str = Query(...)):
    """媒体流（支持 Range）。

    安全：只服务工作区内的 6 类媒体扩展名；路径经 `artifacts.safe_rel` 做 realpath 校验。
    """
    w = str(_require_ws(ws))
    try:
        p = artifacts.safe_rel(w, rel)
        mt = artifacts.media_type(p)
    except artifacts.PathDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    if not p.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    size = p.stat().st_size
    mtime = int(p.stat().st_mtime)
    etag = '"%d-%d"' % (mtime, size)
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    rng = artifacts.parse_range(request.headers.get("range") or "", size)
    common = {"Accept-Ranges": "bytes", "ETag": etag, "Cache-Control": "private, max-age=60"}
    if rng is None:
        return StreamingResponse(artifacts.iter_range(p, 0, size - 1), media_type=mt,
                                 headers={**common, "Content-Length": str(size)})
    start, end = rng
    if end < start:
        return Response(status_code=416, headers={"Content-Range": "bytes */%d" % size})
    return StreamingResponse(artifacts.iter_range(p, start, end), status_code=206,
                             media_type=mt,
                             headers={**common,
                                      "Content-Range": "bytes %d-%d/%d" % (start, end, size),
                                      "Content-Length": str(end - start + 1)})


# ---------------------------------------------------------------------------
# LLM 服务层：AI 模型中心 + 创作闭环
# ---------------------------------------------------------------------------
# 安全口径（与引擎的计费门禁同构）：
#   * 所有写操作先过只读模式；跨站写请求已由 `_access_guard` 拦掉；
#   * **会产生真实调用的接口必须带 confirm**（否则 428），与 /api/run 的计费确认同一种表达；
#   * Key 只进不出：任何响应里都不出现明文，只给 has_key / key_hint。
def _write_guard():
    if READONLY_MODE:
        raise HTTPException(status_code=403,
                            detail="只读模式：写操作被拒绝（SOLODRAMA_CONSOLE_READONLY=1）")


def _llm_err(exc: LLMError, status=400):
    raise HTTPException(status_code=status,
                        detail={"kind": exc.kind, "message": exc.text, "retryable": exc.retryable})


@app.get("/api/llm/meta")
def llm_meta():
    cfg = llm_store.load_config()
    return {
        "kinds": llm_store.KINDS,
        "capabilities": llm_store.CAPABILITIES,
        "presets": llm_store.PRESETS,
        "store_dir": str(llm_store.LLM_DIR),
        "provider_count": len(cfg.get("providers") or []),
        "purpose_count": len(llm_templates.PURPOSES),
        "template_count": len(llm_templates.TEMPLATES),
        "readonly": READONLY_MODE,
        "note": "Key 只存在后端：环境变量优先，其次本机保险箱；接口只回打码状态",
    }


@app.get("/api/llm/providers")
def llm_providers():
    return {"items": llm_store.list_providers(), "readonly": READONLY_MODE}


@app.post("/api/llm/providers")
def llm_provider_save(payload: dict = Body(...)):
    _write_guard()
    try:
        prov = llm_store.upsert_provider(payload)
    except LLMError as exc:
        _llm_err(exc)
    jobs.record_audit(payload.get("ws") or "", "llm.provider.save", [prov["id"], prov["kind"]], 0,
                      note=prov["name"], actor="studio")
    return {"ok": True, "provider": prov}


@app.delete("/api/llm/providers/{pid}")
def llm_provider_delete(pid: str, ws: str = Query(default="")):
    _write_guard()
    try:
        out = llm_store.delete_provider(pid)
    except LLMError as exc:
        _llm_err(exc, 404)
    jobs.record_audit(ws, "llm.provider.delete", [pid], 0, actor="studio")
    return out


@app.post("/api/llm/providers/{pid}/test")
def llm_provider_test(pid: str, deep: int = Query(default=0), confirm: int = Query(default=0)):
    """连接测试：默认只读模型列表（0 费用）；deep=1 会做一次最小生成，需 confirm=1。"""
    _write_guard()
    if deep and not confirm:
        raise HTTPException(status_code=428, detail={
            "need_confirm": True,
            "reason": "「最小生成测试」会向端点发起一次真实调用（可能产生少量费用）",
            "cmd": "llm.test", "args": {"provider_id": pid, "deep": True},
        })
    return llm_gateway.get_gateway().test_provider(pid, deep=bool(deep))


@app.get("/api/llm/purposes")
def llm_purposes():
    return {"items": llm_store.list_purposes(), "readonly": READONLY_MODE}


@app.post("/api/llm/purposes/{pid}")
def llm_purpose_save(pid: str, payload: dict = Body(...)):
    _write_guard()
    try:
        out = llm_store.set_purpose(pid, payload or {})
    except LLMError as exc:
        _llm_err(exc, 404 if exc.kind == "not_found" else 400)
    return {"ok": True, "purpose": out}


@app.get("/api/llm/templates")
def llm_templates_list():
    items = []
    for t in llm_templates.all_templates():
        items.append({k: v for k, v in t.items() if k != "body"})
    return {"items": items}


@app.get("/api/llm/templates/{tid}")
def llm_template_one(tid: str):
    d = llm_templates.describe(tid)
    if not d.get("ok"):
        raise HTTPException(status_code=404, detail="模板不存在或正文缺失：%s" % tid)
    return d


@app.post("/api/llm/preview")
def llm_preview(payload: dict = Body(...)):
    """只渲染提示词，不调用模型、不计费。"""
    try:
        return llm_gateway.get_gateway().preview(payload.get("purpose") or "", payload.get("variables") or {})
    except LLMError as exc:
        _llm_err(exc, 404 if exc.kind == "not_found" else 400)
    except KeyError:
        _llm_err(LLMError("not_found", "未知模板"))


@app.post("/api/llm/complete")
def llm_complete(payload: dict = Body(...)):
    """直接调用（可能计费）。必须显式 confirm。"""
    _write_guard()
    if not payload.get("confirm"):
        raise HTTPException(status_code=428, detail={
            "need_confirm": True,
            "reason": "该调用会向所选模型发起真实请求，可能产生费用",
            "cmd": "llm.complete", "args": {"purpose": payload.get("purpose")},
        })
    res = llm_gateway.get_gateway().complete(
        payload.get("purpose") or "", payload.get("variables") or {},
        provider_id=payload.get("provider_id") or None,
        model=payload.get("model") or None,
    )
    jobs.record_audit(payload.get("ws") or "", "llm.complete",
                      [payload.get("purpose") or ""], 0 if res.get("ok") else 1,
                      estimate="LLM 调用（金额见用量）", actor="studio")
    return res


@app.get("/api/llm/usage")
def llm_usage(limit: int = Query(default=100), purpose: str = Query(default=None),
              provider: str = Query(default=None)):
    return llm_gateway.get_gateway().usage(limit=limit, purpose=purpose, provider=provider)


# ---- 创作闭环：剧本草稿 -----------------------------------------------------
@app.get("/api/studio/script/gates")
def script_gates(ws: str = Query(...)):
    return llm_drafts.gates(str(_require_ws(ws)))


@app.get("/api/studio/script/context")
def script_context(ws: str = Query(...), ep: int = Query(...)):
    try:
        return llm_drafts.context(str(_require_ws(ws)), int(ep))
    except LLMError as exc:
        _llm_err(exc)


@app.get("/api/studio/drafts")
def drafts_list(ws: str = Query(...)):
    return llm_drafts.list_drafts(str(_require_ws(ws)))


@app.get("/api/studio/drafts/{did}")
def drafts_get(did: str, ws: str = Query(...)):
    try:
        return llm_drafts.get_draft(str(_require_ws(ws)), did)
    except LLMError as exc:
        _llm_err(exc, 404)


@app.post("/api/studio/drafts/{did}/save")
def drafts_save(did: str, payload: dict = Body(...), ws: str = Query(...)):
    _write_guard()
    try:
        return llm_drafts.update_draft(str(_require_ws(ws)), did, payload or {})
    except LLMError as exc:
        _llm_err(exc, 404 if exc.kind == "not_found" else 400)


@app.post("/api/studio/drafts/{did}/confirm")
def drafts_confirm(did: str, payload: dict = Body(default=None), ws: str = Query(...)):
    _write_guard()
    body = payload or {}
    if not body.get("confirm"):
        raise HTTPException(status_code=428, detail={
            "need_confirm": True,
            "reason": "确认后会把草稿写成正式剧本（03-剧本/ep_NN.md）；已有文件会被备份后覆盖",
            "cmd": "llm.script.confirm", "args": {"draft_id": did},
        })
    try:
        return llm_drafts.confirm(str(_require_ws(ws)), did,
                                  overwrite=bool(body.get("overwrite")),
                                  expected_sha=body.get("expected_sha") or None,
                                  allow_simulated=bool(body.get("allow_simulated")))
    except LLMError as exc:
        _llm_err(exc, 404 if exc.kind == "not_found" else 400)


@app.post("/api/studio/script/generate")
def script_generate(payload: dict = Body(...), ws: str = Query(...)):
    _write_guard()
    if not payload.get("confirm"):
        raise HTTPException(status_code=428, detail={
            "need_confirm": True,
            "reason": "生成剧本正文会向所选模型发起真实请求，可能产生费用",
            "cmd": "llm.script.generate", "args": {"ep": payload.get("ep")},
        })
    w = str(_require_ws(ws))
    try:
        res = llm_drafts.generate(w, int(payload.get("ep") or 0),
                                  gateway=llm_gateway.get_gateway(),
                                  provider_id=payload.get("provider_id") or None,
                                  model=payload.get("model") or None,
                                  timeout_s=payload.get("timeout_s") or None)
    except LLMError as exc:
        _llm_err(exc)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="集号不合法") from None
    return res


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

# Studio（新工作台）：独立目录、独立样式与 ES module，删掉 /studio 即回滚，旧的两张脸不受影响
STUDIO_DIR = UI_DIR / "studio"
if STUDIO_DIR.is_dir():
    app.mount("/studio", StaticFiles(directory=str(STUDIO_DIR), html=True), name="studio")


@app.get("/")
def root(request: Request):
    """根路径跳 Studio（没有 Studio 时跳旧控制台）。

    ★ 必须把查询串一起带过去：`/?ws=<剧目录>` 是深链/书签的唯一写法，
      而 307 到 `/studio/` 不带 query 的话，工作区会静默退回「上次用过的项目」——
      用户以为打开的是 A，看到的却是 B（本机实测：书签里的 ?ws 从来没生效过）。
    """
    target = "/studio/" if STUDIO_DIR.is_dir() else "/ui/"
    qs = request.url.query
    return RedirectResponse(target + (("?" + qs) if qs else ""))
