#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_jobs.py —— 作业库 / 资源锁 / 状态机测试（离线、零网络、零计费）

用临时数据库，不触碰 web/var/jobs.db。
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
if str(WEB) not in sys.path:
    sys.path.insert(0, str(WEB))

from core import jobs, paths  # noqa: E402

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("  [NG] %s" % msg)
    return cond


def _isolate():
    tmp = Path(tempfile.mkdtemp(prefix="solodrama-jobs-"))
    paths.JOBS_DB = tmp / "jobs.db"
    paths.LOGS_DIR = tmp / "logs"
    paths.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    return tmp


def main():
    tmp = _isolate()
    jobs.init_db()

    print("[1] 建库与建作业")
    c = __import__("core.commands", fromlist=["get"]).get("video.plan")
    argv = c.build_argv({"limit": 2})
    job = jobs.create_job("<ws>", c, argv, {"limit": 2}, estimate="预估 290 RH币")
    check(job["id"], "未生成作业 id")
    got = jobs.get_job(job["id"])
    check(got and got["status"] == "queued", "初始状态不是 queued：%s" % (got or {}).get("status"))
    check(got["resources"] == ["RH"] or got["resources"] == [], "资源声明异常：%s" % got["resources"])
    check(bool(got.get("argv_display")), "argv_display 缺失")
    evs = jobs.events(job["id"])
    check(len(evs) >= 1 and evs[0]["kind"] == "queued", "入队事件缺失")

    print("[2] 资源锁（GPU 1 / RH 5）")
    with jobs._conn() as conn:                                    # noqa: SLF001
        t1 = jobs._acquire(conn, ["GPU"], "job-a")                # noqa: SLF001
        check(t1 == ["GPU-1"], "首次申请 GPU 失败：%s" % t1)
        t2 = jobs._acquire(conn, ["GPU"], "job-b")                # noqa: SLF001
        check(t2 is None, "GPU 独占锁被重复占用")
        rh = [jobs._acquire(conn, ["RH"], "job-rh-%d" % i) for i in range(5)]   # noqa: SLF001
        check(all(x for x in rh), "RH 前 5 槽未全部拿到：%s" % rh)
        check(jobs._acquire(conn, ["RH"], "job-rh-6") is None, "RH 第 6 槽应被拒（平台硬限 ≤5）")  # noqa: SLF001
    st = jobs.lock_status()
    check(st["summary"]["gpu"] == "1/1", "GPU 占用量统计错误：%s" % st["summary"])
    check(st["summary"]["rh"] == "5/5", "RH 占用量统计错误：%s" % st["summary"])
    jobs._release("job-a")                                        # noqa: SLF001
    st = jobs.lock_status()
    check(st["summary"]["gpu"] == "0/1", "释放 GPU 后统计未归零：%s" % st["summary"])

    print("[3] 状态机与审计")
    with jobs._conn() as c2:
        c2.execute("UPDATE jobs SET status='running', started_at=? WHERE id=?",
                   (time.time(), job["id"]))
    jobs.init_db()                                                # 触发 _sweep_stale（模拟重启）
    got = jobs.get_job(job["id"])
    check(got["status"] == "interrupted", "重启后未把 running 作业标记为 interrupted：%s" % got["status"])
    check(any("续跑" in e["text"] for e in jobs.events(job["id"])), "重启扫描未写入提示事件")
    check(jobs.lock_status()["summary"]["gpu"] == "0/1", "重启后锁未释放")

    print("[4] 事件隔离")
    c2 = __import__("core.commands", fromlist=["get"]).get("diag.preflight")
    j2 = jobs.create_job("<ws>", c2, c2.build_argv({}), {})
    jobs.append_event(j2["id"], "log", "hello")
    check(len(jobs.events(j2["id"])) == 2, "作业事件数异常")
    check(len(jobs.events(job["id"])) >= 2, "事件串作业了")
    seqs = [e["seq"] for e in jobs.events_since(0)]
    check(seqs == sorted(seqs), "全局事件流顺序异常")
    mask_ev = jobs.events(j2["id"])
    check(all("text" in e for e in mask_ev), "事件缺 text 字段")

    print("[5] 审计表")
    check(isinstance(jobs.audit_log(), list), "审计读取失败")

    import shutil
    shutil.rmtree(str(tmp), ignore_errors=True)


if __name__ == "__main__":
    main()
    print("-" * 60)
    if FAILS:
        print("[FAIL] %d 项未通过" % len(FAILS))
        sys.exit(1)
    print("[OK] 作业库契约全部通过")
