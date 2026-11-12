# -*- coding: utf-8 -*-
"""13 节点受控 Runner。

边界：
* 只调用 `nodes.py` 的 next / state / run_node，不在 Web 或调度层重写判据；
* 默认干跑，真实执行必须 `--apply`；
* `video.batch` / `board.frame` 真实执行必须再给 `--yes`；
* 每次推进写 `.drama/agent/journal.jsonl`，重启后仍从磁盘状态继续；
* 同一工作区已有活跃 Runner 时拒绝启动，防止两个进程同时改状态；
* 不在本层自动修改提示词、判据或计费数据。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from . import journal

ROOT = Path(__file__).resolve().parents[2]


def _set_workspace(value: str) -> None:
    """设置工作区；只有路径真实存在时才覆盖已有值。

    Windows 终端可能用错误代码页把中文路径送进 sys.argv。Web 作业层已经在
    `base_env` 里注入了正确的 Unicode 路径，因此不能用损坏的 argv 反向覆盖它。
    """
    try:
        if not Path(value).expanduser().is_dir():
            current = os.environ.get("SOLODRAMA_WORKSPACE") or os.environ.get("DRAMA_WORKSPACE")
            if current:
                try:
                    if Path(current).expanduser().is_dir():
                        return
                except OSError:
                    pass
    except OSError:
        pass
    os.environ["SOLODRAMA_WORKSPACE"] = value
    os.environ["DRAMA_WORKSPACE"] = value


def _prescan_workspace(argv) -> None:
    for i, arg in enumerate(argv):
        if arg == "--workspace" and i + 1 < len(argv):
            _set_workspace(argv[i + 1])
        elif arg.startswith("--workspace="):
            _set_workspace(arg.split("=", 1)[1])

def _load_nodes():
    scripts = ROOT / "stages" / "production" / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import nodes  # noqa: PLC0415

    return nodes


def _summary(nodes, ctx) -> dict:
    ev = nodes.evaluate(ctx)
    nxt = nodes.next_node(ctx)
    return {
        "workspace": str(ctx.ws),
        "ep": ctx.ep,
        "complete": nxt is None,
        "next": ({"id": nxt["node"]["id"], "state": nxt["state"],
                  "detail": nxt["detail"]} if nxt else None),
        "counts": ev.get("counts") or {},
        "nodes": ev.get("nodes") or [],
    }


# ---------------------------------------------------------------------------
# 单写者锁：Web 作业队列之外，直接运行 CLI 也必须互斥
# ---------------------------------------------------------------------------
def _lock_path(ws) -> Path:
    return journal.path(ws).parent / "run.lock"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes  # noqa: PLC0415

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, int(pid))
            if not handle:
                return False
            kernel32.CloseHandle(handle)
            return True
        except Exception:  # noqa: BLE001
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _read_lock(ws) -> dict:
    p = _lock_path(ws)
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _lock_pid(doc: dict) -> int:
    try:
        return int(doc.get("pid") or 0)
    except (TypeError, ValueError):
        return 0

def lock_status(ws) -> dict:
    doc = _read_lock(ws)
    if not doc:
        return {"busy": False}
    pid = _lock_pid(doc)
    return {"busy": _pid_alive(pid), "run_id": doc.get("run_id") or "",
            "pid": pid, "started_at": doc.get("started_at")}


def _acquire_lock(ws, run_id: str):
    p = _lock_path(ws)
    p.parent.mkdir(parents=True, exist_ok=True)
    doc = {"run_id": run_id, "pid": os.getpid(), "started_at": time.time()}
    for _ in range(2):
        try:
            fd = os.open(str(p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            old = _read_lock(ws)
            old_pid = _lock_pid(old)
            if old_pid and _pid_alive(old_pid):
                return None
            try:
                p.unlink()
            except FileNotFoundError:
                pass
            continue
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(doc, ensure_ascii=False, sort_keys=True) + "\n")
        return {"path": p, "run_id": run_id}
    return None


def _release_lock(lock) -> None:
    if not lock:
        return
    p = lock["path"]
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return
    if doc.get("run_id") == lock["run_id"] and _lock_pid(doc) == os.getpid():
        try:
            p.unlink()
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------------------
# 查询与推进
# ---------------------------------------------------------------------------
def status(ws, ep="", limit=50) -> dict:
    nodes = _load_nodes()
    ctx = nodes.Ctx(Path(ws), ep)
    out = _summary(nodes, ctx)
    out["ok"] = True
    out["journal"] = journal.recent(ws, limit)
    out["lock"] = lock_status(ws)
    return out


def run(ws, ep="", *, apply=False, yes=False, max_steps=6,
        only="", until="", run_id="") -> dict:
    nodes = _load_nodes()
    ctx = nodes.Ctx(Path(ws), ep)
    dry_run = not apply
    run_id = run_id or ("run_" + time.strftime("%Y%m%d_%H%M%S"))
    if only and only not in nodes.NODE_BY_ID:
        return {"ok": False, "error": "未知节点：%s" % only, "run_id": run_id}
    if until and until not in nodes.NODE_BY_ID:
        return {"ok": False, "error": "未知节点：%s" % until, "run_id": run_id}
    if yes and not apply:
        return {"ok": False, "error": "--yes 只能和 --apply 一起使用", "run_id": run_id}

    lock = _acquire_lock(ws, run_id)
    if lock is None:
        out = {"ok": False, "run_id": run_id, "rc": 4,
               "error": "该工作区已有调度任务正在运行，拒绝并发执行"}
        journal.append(ws, {"event": "run_rejected", "run_id": run_id,
                            "reason": out["error"]})
        return out

    started = time.time()
    journal.append(ws, {"event": "run_start", "run_id": run_id, "ep": ep,
                        "dry_run": dry_run, "yes": bool(yes), "only": only,
                        "until": until, "max_steps": max(1, int(max_steps))})
    steps = []
    rc = 0
    stopped = ""
    error = ""
    try:
        for i in range(max(1, int(max_steps))):
            if only:
                node = nodes.NODE_BY_ID[only]
                st = nodes.node_state(ctx, node)
                if st["state"] in ("passed", "skipped"):
                    stopped = "already_done"
                    break
                nxt = {"node": node, "state": st["state"], "detail": st["detail"]}
            else:
                nxt = nodes.next_node(ctx)
            if nxt is None:
                stopped = "complete"
                break

            node = nxt["node"]
            nid = node["id"]
            state_before = nxt["state"]
            t0 = time.time()
            journal.append(ws, {"event": "node_start", "run_id": run_id, "step": i + 1,
                                "node": nid, "state_before": state_before,
                                "detail_before": nxt.get("detail", ""),
                                "dry_run": dry_run})
            try:
                rc = nodes.run_node(ctx, nid, dry_run=dry_run, yes=yes)
                after = nodes.node_state(ctx, node)
                rec = {"step": i + 1, "node": nid, "rc": rc,
                       "state_before": state_before, "state_after": after["state"],
                       "detail_after": after.get("detail", ""),
                       "elapsed": round(time.time() - t0, 3), "dry_run": dry_run}
            except Exception as exc:  # noqa: BLE001
                rc = 1
                rec = {"step": i + 1, "node": nid, "rc": rc,
                       "state_before": state_before, "state_after": "failed",
                       "detail_after": "%s: %s" % (type(exc).__name__, exc),
                       "elapsed": round(time.time() - t0, 3), "dry_run": dry_run}
                error = rec["detail_after"]
            steps.append(rec)
            journal.append(ws, {"event": "node_end", "run_id": run_id, **rec})
            if rc != 0:
                stopped = "node_rc_%s" % rc
                break
            if dry_run:
                stopped = "dry_run"
                break
            if rec["state_after"] not in ("passed", "skipped"):
                stopped = "criterion_not_passed"
                rc = 2
                break
            if until and nid == until:
                stopped = "until"
                break
        else:
            stopped = "max_steps"
            rc = 4
    finally:
        summary = {"workspace": str(ctx.ws), "ep": ctx.ep, "complete": False,
                   "next": None, "counts": {}, "nodes": []}
        try:
            summary = _summary(nodes, ctx)
        except Exception as exc:  # noqa: BLE001
            error = error or "状态汇总失败：%s: %s" % (type(exc).__name__, exc)
        try:
            journal.append(ws, {"event": "run_end", "run_id": run_id, "rc": rc,
                                "stopped": stopped, "steps": len(steps),
                                "elapsed": round(time.time() - started, 3)})
        finally:
            _release_lock(lock)

    out = {"ok": rc == 0, "run_id": run_id, "dry_run": dry_run,
           "rc": rc, "stopped": stopped, "steps": steps, "summary": summary}
    if error:
        out["error"] = error
    return out


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    _prescan_workspace(argv)
    p = argparse.ArgumentParser(description="SoloDrama 13 节点受控 Runner")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("status", "run"):
        q = sub.add_parser(name)
        q.add_argument("--workspace", required=True)
        q.add_argument("--ep", default="")
        q.add_argument("--json", action="store_true")
        if name == "status":
            q.add_argument("--limit", type=int, default=50)
        if name == "run":
            q.add_argument("--apply", action="store_true", help="真实执行；默认只干跑")
            q.add_argument("--yes", action="store_true", help="允许 GPU/计费节点真实执行")
            q.add_argument("--max-steps", dest="max_steps", type=int, default=6)
            q.add_argument("--only", default="")
            q.add_argument("--until", default="")
            q.add_argument("--run-id", dest="run_id", default="")
    a = p.parse_args(argv)
    try:
        if a.cmd == "status":
            out = status(a.workspace, a.ep, limit=a.limit)
        else:
            out = run(a.workspace, a.ep, apply=a.apply, yes=a.yes,
                      max_steps=a.max_steps, only=a.only, until=a.until,
                      run_id=a.run_id)
    except Exception as exc:  # noqa: BLE001
        out = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
        if getattr(a, "json", False):
            print(json.dumps(out, ensure_ascii=False, indent=2))
        else:
            print("[FAIL] %s" % out["error"])
        return 2
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        if "counts" in out:
            print(json.dumps(out.get("counts") or {}, ensure_ascii=False))
        print("run_id=%s complete=%s next=%s" % (
            out.get("run_id", "-"), out.get("complete"),
            (out.get("next") or {}).get("id", "") if isinstance(out.get("next"), dict) else ""))
    return 0 if out.get("ok") else int(out.get("rc") or 2)


if __name__ == "__main__":
    raise SystemExit(main())