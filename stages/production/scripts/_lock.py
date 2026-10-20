#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""_lock.py —— 长驻任务的单例锁（纯标准库）

为什么有它（反馈 P2-14）
----------------------
两条真实事故：
1. 批处理脚本放在 `%TEMP%`，被系统清理后进程**静默停摆 50 分钟**（脚本文件已消失）；
2. 同一脚本被重复启动两次，两条 lane 变四条，**同一镜重复生成，浪费约 2,400 币**。

本模块只解决第 2 条（第 1 条是「脚本别放 %TEMP%」，属于部署纪律，写进文档）：
启动即写 `<工作区>/.locks/<name>.lock`（PID + 时间戳 + 命令行），
检测到**有效**锁就直接拒绝启动；持有者进程已死则视为陈旧锁，接管并告警。

判定「进程是否还活着」：
* Windows：`OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` + `GetExitCodeProcess`
  （不能用 `os.kill(pid, 0)` —— Windows 上它可能真的终止进程）。
* POSIX：`os.kill(pid, 0)`。

用法：
    from _lock import single_instance
    with single_instance("video_run", WS):
        ...   # 独占执行
"""
from __future__ import annotations

import contextlib
import json
import os
import pathlib
import sys
import time

LOCK_DIR = ".locks"
_STALE_AFTER_S = 24 * 3600       # 超过 24h 且进程已死 ⇒ 一定是陈旧锁


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            k32 = ctypes.windll.kernel32
            h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
            if not h:
                return False
            try:
                code = wintypes.DWORD()
                if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                    return False
                return code.value == STILL_ACTIVE
            finally:
                k32.CloseHandle(h)
        except Exception:                                          # noqa: BLE001
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def lock_path(ws, name: str) -> pathlib.Path:
    return pathlib.Path(ws) / LOCK_DIR / ("%s.lock" % name)


@contextlib.contextmanager
def single_instance(name: str, ws, *, takeover_stale: bool = True):
    """单例上下文；被占用时抛 SystemExit(4)（与「等待用户确认」同档，便于上层区分）。"""
    p = lock_path(ws, name)
    p.parent.mkdir(parents=True, exist_ok=True)

    if p.is_file():
        try:
            info = json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            info = {}
        pid = int(info.get("pid") or 0)
        started = float(info.get("started_ts") or 0)
        age = (time.time() - started) if started else _STALE_AFTER_S + 1
        if _pid_alive(pid) and age < _STALE_AFTER_S:
            print("[BLOCK] 已经有一个同名任务在跑（单例锁），拒绝重复启动：", file=sys.stderr)
            print("        lock : %s" % p, file=sys.stderr)
            print("        pid  : %s（启动于 %s）" % (pid, info.get("started_at") or "?"), file=sys.stderr)
            print("        cmd  : %s" % (info.get("cmd") or "?"), file=sys.stderr)
            print("        重复启动会让同一镜被生成两次、**重复计费**（实测浪费约 2400 币）。",
                  file=sys.stderr)
            print("        确认旧进程已死再重跑：删掉上面这个 lock 文件。", file=sys.stderr)
            raise SystemExit(4)
        if takeover_stale:
            print("[WARN] 发现陈旧锁（pid %s 已不在），接管：%s" % (pid or "?", p), file=sys.stderr)

    payload = {"pid": os.getpid(), "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
               "started_ts": time.time(), "cmd": " ".join(sys.argv)[:400], "name": name}
    tmp = p.with_suffix(".lock.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)
    try:
        yield p
    finally:
        try:
            cur = json.loads(p.read_text(encoding="utf-8-sig"))
            if int(cur.get("pid") or 0) == os.getpid():
                p.unlink()
        except (OSError, json.JSONDecodeError, ValueError):
            pass
