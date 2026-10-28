# -*- coding: utf-8 -*-
"""jobs.py —— 作业队列 + 资源锁 + 事件流 + 审计（stdlib sqlite3，零新增依赖）

为什么必须作业化（而不是让 HTTP 请求等命令跑完）：
  * 出片 / 放大 / 字幕是分钟~小时级任务，浏览器一刷新就会断；
  * 本机资源有限：GPU 同时只能跑一个（Topaz 独占）、RunningHub 单账号并发 ≤5；
  * 计费动作必须留痕：谁、何时、执行了什么、预估多少、实际消耗多少。

状态语义与引擎退出码对齐（见 runner.EXIT_MEANING）：
  queued → running → done / gate(2) / fuse(3) / confirm(4) / interrupted(130) / failed / canceled
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from . import paths, runner

DB_LOCK = threading.Lock()
_STARTED = False
_WORKERS: dict = {}          # job_id -> {"pid": int, "thread": Thread}
_RUNNING_JOBS: dict = {}     # job_id -> runner 进程句柄（用于取消）

RH_SLOTS = 5                 # RunningHub 单账号并发硬限（平台硬限，不可调优）
GPU_SLOTS = 1                # 本机 GPU 独占
CPU_MEDIA_SLOTS = 1

RESOURCE_TOKENS = []
for _i in range(GPU_SLOTS):
    RESOURCE_TOKENS.append("GPU-%d" % (_i + 1))
for _i in range(RH_SLOTS):
    RESOURCE_TOKENS.append("RH-%d" % (_i + 1))
for _i in range(CPU_MEDIA_SLOTS):
    RESOURCE_TOKENS.append("MEDIA-1")


def _q(a) -> str:
    a = str(a)
    return '"%s"' % a if " " in a else a


def _conn():
    paths.ensure_var_dirs()
    c = sqlite3.connect(str(paths.JOBS_DB), timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_db() -> None:
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            ws TEXT, spec_id TEXT, title TEXT, group_name TEXT,
            argv_json TEXT, params_json TEXT,
            status TEXT, exit_code INTEGER,
            gate TEXT, billing TEXT, danger INTEGER, resources TEXT,
            estimate TEXT, note TEXT,
            created_at REAL, started_at REAL, ended_at REAL,
            log_path TEXT, cancel_requested INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS events (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT, ts REAL, kind TEXT, text TEXT
        );
        CREATE TABLE IF NOT EXISTS audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL, ws TEXT, spec_id TEXT, argv TEXT,
            exit_code INTEGER, estimate TEXT, note TEXT, actor TEXT
        );
        CREATE TABLE IF NOT EXISTS locks (
            token TEXT PRIMARY KEY, job_id TEXT, acquired_at REAL
        );
        CREATE INDEX IF NOT EXISTS idx_events_job ON events(job_id, seq);
        CREATE INDEX IF NOT EXISTS idx_jobs_ws ON jobs(ws, created_at);
        """)
    _sweep_stale()


def _sweep_stale() -> None:
    """进程重启后：把「running」且已无对应进程的作业标记为 interrupted，并释放其占用的锁。

    ★ 这是防重复扣费的第一道闸：宁可让用户手工续跑，也不能自动重提交。
    """
    with _conn() as c:
        rows = c.execute("SELECT id FROM jobs WHERE status='running'").fetchall()
        for r in rows:
            c.execute("UPDATE jobs SET status='interrupted', ended_at=? WHERE id=?",
                      (time.time(), r["id"]))
            c.execute("INSERT INTO events(job_id, ts, kind, text) VALUES(?,?,?,?)",
                      (r["id"], time.time(), "system", "[WARN] 控制台重启，此作业状态未知，已标记为「中断」；续跑请使用 --resume 或对应的续跑命令。"))
        c.execute("DELETE FROM locks")
        c.execute("UPDATE jobs SET status='queued' WHERE status='running'")


# ---------------------------------------------------------------------------
# 资源锁
# ---------------------------------------------------------------------------
def _acquire(c, need: list, job_id: str) -> list:
    """按需申请资源（全有或全无）。need 里用 "GPU" / "RH" 这类族名。"""
    if not need:
        return []
    want = []
    for fam in need:
        free = [t for t in RESOURCE_TOKENS if t.startswith(fam + "-")
                and not c.execute("SELECT 1 FROM locks WHERE token=?", (t,)).fetchone()]
        if not free:
            return None
        want.append(free[0])
    now = time.time()
    for t in want:
        c.execute("INSERT OR IGNORE INTO locks(token, job_id, acquired_at) VALUES(?,?,?)",
                  (t, job_id, now))
    return want


def _release(job_id: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM locks WHERE job_id=?", (job_id,))


def lock_status() -> dict:
    with _conn() as c:
        rows = c.execute("SELECT token, job_id, acquired_at FROM locks").fetchall()
    used = {r["token"]: r["job_id"] for r in rows}
    return {
        "tokens": RESOURCE_TOKENS,
        "used": used,
        "summary": {
            "gpu": "%d/%d" % (sum(1 for t in RESOURCE_TOKENS if t.startswith("GPU-") and t in used), GPU_SLOTS),
            "rh": "%d/%d" % (sum(1 for t in RESOURCE_TOKENS if t.startswith("RH-") and t in used), RH_SLOTS),
        },
    }


# ---------------------------------------------------------------------------
# 作业 CRUD
# ---------------------------------------------------------------------------
def create_job(ws, cmd, argv, values, estimate="", note="", actor="console") -> dict:
    jid = "%s-%s" % (time.strftime("%Y%m%d-%H%M%S"), uuid.uuid4().hex[:6])
    now = time.time()
    meta = {
        "id": jid, "ws": str(ws), "spec_id": cmd.id, "title": cmd.title,
        "group_name": cmd.group, "argv": argv, "values": values,
        "status": "queued", "exit_code": None, "gate": cmd.gate, "billing": cmd.billing,
        "danger": cmd.danger, "resources": cmd.resources, "estimate": estimate, "note": note,
        "created_at": now, "started_at": None, "ended_at": None, "log_path": None,
    }
    with _conn() as c:
        c.execute("""INSERT INTO jobs(id, ws, spec_id, title, group_name, argv_json, params_json, status,
                     gate, billing, danger, resources, estimate, note, created_at)
                     VALUES(:id,:ws,:spec_id,:title,:group_name,:argv_json,:params_json,:status,
                     :gate,:billing,:danger,:resources,:estimate,:note,:created_at)""",
                  {**meta, "argv_json": json.dumps(argv, ensure_ascii=False),
                   "params_json": json.dumps(values, ensure_ascii=False),
                   "resources": json.dumps(cmd.resources, ensure_ascii=False)})
    append_event(jid, "queued", "已入队：%s" % " ".join(_q(a) for a in argv[1:]))
    return meta


def append_event(job_id: str, kind: str, text: str) -> None:
    with _conn() as c:
        c.execute("INSERT INTO events(job_id, ts, kind, text) VALUES(?,?,?,?)",
                  (job_id, time.time(), kind, runner.mask_text(text)))


def events(job_id, after=0, limit=2000) -> list:
    with _conn() as c:
        rows = c.execute("SELECT seq, ts, kind, text FROM events WHERE job_id=? AND seq>? "
                         "ORDER BY seq LIMIT ?", (job_id, int(after or 0), limit)).fetchall()
    return [dict(r) for r in rows]


def events_since(after=0, limit=500) -> list:
    with _conn() as c:
        rows = c.execute("SELECT seq, job_id, ts, kind, text FROM events WHERE seq>? "
                         "ORDER BY seq LIMIT ?", (int(after or 0), limit)).fetchall()
    return [dict(r) for r in rows]


def _row_to_job(r) -> dict:
    d = dict(r)
    for src, dst in (("argv_json", "argv"), ("params_json", "values"), ("resources", "resources")):
        try:
            d[dst] = json.loads(d.get(src) or "null")
        except (TypeError, ValueError):
            pass
        if src != dst:
            d.pop(src, None)
    if d.get("argv"):
        d["argv_display"] = " ".join(d["argv"][1:])
    d["exit"] = runner.exit_meaning(d.get("exit_code")) if d.get("exit_code") is not None else None
    return d


def get_job(job_id) -> dict:
    with _conn() as c:
        r = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return _row_to_job(r) if r else None


def list_jobs(ws=None, limit=50) -> list:
    with _conn() as c:
        if ws:
            rows = c.execute("SELECT * FROM jobs WHERE ws=? ORDER BY created_at DESC LIMIT ?",
                             (str(ws), int(limit))).fetchall()
        else:
            rows = c.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                             (int(limit),)).fetchall()
    return [_row_to_job(r) for r in rows]


def record_audit(ws, spec_id, argv=None, exit_code=None, estimate="", note="", actor="studio") -> None:
    """写一条审计（Studio 的写操作也留痕：谁、对哪个工作区、做了什么、结果如何）。

    与作业路径共用同一张 `audit` 表，所以前端「审计」卡片能一起看到。
    """
    try:
        with _conn() as c:
            c.execute("""INSERT INTO audit(ts, ws, spec_id, argv, exit_code, estimate, note, actor)
                         VALUES(?,?,?,?,?,?,?,?)""",
                      (time.time(), str(ws or ""), str(spec_id or ""),
                       json.dumps(argv or [], ensure_ascii=False),
                       exit_code, estimate or "", note or "", actor))
    except sqlite3.Error:
        pass  # 审计失败不能阻塞业务


def audit_log(limit=100) -> list:
    with _conn() as c:
        rows = c.execute("SELECT * FROM audit ORDER BY ts DESC LIMIT ?", (int(limit),)).fetchall()
    return [dict(r) for r in rows]


def request_cancel(job_id) -> dict:
    with _conn() as c:
        c.execute("UPDATE jobs SET cancel_requested=1 WHERE id=?", (job_id,))
    handle = _RUNNING_JOBS.get(job_id)
    if handle is not None:
        runner.kill_tree(handle)
        append_event(job_id, "system", "已请求取消：正在终止子进程树")
        return {"ok": True, "running": True}
    append_event(job_id, "system", "已请求取消（作业尚未开始或已结束）")
    return {"ok": True, "running": False}


# ---------------------------------------------------------------------------
# 调度器
# ---------------------------------------------------------------------------
def start_scheduler() -> None:
    global _STARTED
    if _STARTED:
        return
    _STARTED = True
    t = threading.Thread(target=_loop, name="solodrama-scheduler", daemon=True)
    t.start()


def _loop() -> None:
    while True:
        try:
            _tick()
        except Exception as exc:  # noqa: BLE001
            try:
                with _conn() as c:
                    c.execute("INSERT INTO events(job_id, ts, kind, text) VALUES(?,?,?,?)",
                              ("-", time.time(), "system", "[WARN] 调度器异常：%s" % exc))
            except Exception:  # noqa: BLE001
                pass
        time.sleep(0.6)


def _tick() -> None:
    with _conn() as c:
        queued = c.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at").fetchall()
        for r in queued:
            job = _row_to_job(r)
            need = job.get("resources") or []
            tokens = _acquire(c, need, job["id"])
            if tokens is None:
                continue
            if job.get("cancel_requested"):
                c.execute("UPDATE jobs SET status='canceled', ended_at=? WHERE id=?",
                          (time.time(), job["id"]))
                continue
            c.execute("UPDATE jobs SET status='running', started_at=? WHERE id=?",
                      (time.time(), job["id"]))
            c.execute("INSERT INTO events(job_id, ts, kind, text) VALUES(?,?,?,?)",
                      (job["id"], time.time(), "start",
                       "开始执行（占用：%s）" % (",".join(tokens) or "无")))
            th = threading.Thread(target=_execute, args=(job, tokens), daemon=True)
            th.start()


def _execute(job: dict, tokens: list) -> None:
    spec = job.get("spec_id")
    argv = job.get("argv") or []
    log_path = paths.LOGS_DIR / ("%s.log" % job["id"])
    rc = None
    try:
        proc_holder = {}

        def on_line(line):
            append_event(job["id"], "log", line)

        # 有些引擎脚本**只认环境变量**（如 gen_assets_local.py 要 SOLODRAMA_ASSET_MD）。
        # 命令自己声明了 env 映射，这里在 fork 前解析好注入，浏览器永远碰不到命令拼接。
        extra_env = None
        try:
            from . import commands as _CMD          # 延迟导入，避免与 app 的导入顺序耦合
            _c = _CMD.get(spec)
            if _c is not None:
                extra_env = _c.env_for(job.get("values") or {})
        except Exception:                            # noqa: BLE001
            extra_env = None

        # run_stream 内部会 Popen；为支持取消，这里自行启动并注册句柄。
        p = runner._popen(argv, ws=job["ws"], extra_env=extra_env)
        proc_holder["pid"] = p.pid
        _RUNNING_JOBS[job["id"]] = p.pid
        with open(log_path, "w", encoding="utf-8", newline="") as fh:
            fh.write("# job %s\n# cmd %s\n" % (job["id"], " ".join(argv)))
            if extra_env:
                # 只记键名，不记值（值可能是路径，但保持日志干净）
                fh.write("# env %s\n" % ", ".join(sorted(extra_env)))
            for raw in p.stdout:                                  # type: ignore[union-attr]
                line = runner.mask_text(raw.rstrip("\r\n"))
                fh.write(line + "\n")
                fh.flush()
                append_event(job["id"], "log", line)
            p.wait()
            rc = p.returncode
    except Exception as exc:  # noqa: BLE001
        append_event(job["id"], "system", "[FAIL] 作业执行异常：%s" % exc)
        rc = runner.EXIT_ERROR
    finally:
        _RUNNING_JOBS.pop(job["id"], None)

    if rc is None:
        rc = runner.EXIT_ERROR
    meaning = runner.exit_meaning(rc)
    status = {"ok": "done", "gate": "gate", "fuse": "fuse", "confirm": "confirm",
              "interrupted": "interrupted"}.get(meaning["kind"], "failed")
    with _conn() as c:
        cancel = c.execute("SELECT cancel_requested FROM jobs WHERE id=?", (job["id"],)).fetchone()
        if cancel and cancel["cancel_requested"] and status == "failed":
            status = "canceled"
        c.execute("UPDATE jobs SET status=?, exit_code=?, ended_at=?, log_path=? WHERE id=?",
                  (status, rc, time.time(), str(log_path), job["id"]))
        c.execute("""INSERT INTO audit(ts, ws, spec_id, argv, exit_code, estimate, note, actor)
                     VALUES(?,?,?,?,?,?,?,?)""",
                  (time.time(), job["ws"], spec, json.dumps(argv, ensure_ascii=False),
                   rc, job.get("estimate") or "", job.get("note") or "", "console"))
    append_event(job["id"], "end", "结束：退出码 %s（%s）" % (rc, meaning["text"]))
    _release(job["id"])
