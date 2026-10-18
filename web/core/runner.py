# -*- coding: utf-8 -*-
"""runner.py —— 白名单命令执行器（Web 层唯一的「写」通道）

职责边界（重要）：
  * 本模块**不实现任何业务逻辑**，只做四件事：拼 argv、注入环境、流转输出、翻译退出码；
  * 命令一律以 argv 数组交给 subprocess（不使用 shell），因此没有注入面；
  * 所有文本（stdout / 日志 / 返回值）出境前过一遍 `mask_text()`，密钥不外传。

关键实测结论（2026-10-17）：
  `stages/production/scripts/drama.py` **没有全局 `--workspace` 参数**，
  工作区只能通过环境变量 `SOLODRAMA_WORKSPACE` 传入（`_ws.resolve()` 第 ② 优先级）。
  因此「按工作区执行命令」= 在子进程环境里注入工作区变量 —— 本模块的 `base_env()` 是唯一出口。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import paths

# ---------------------------------------------------------------------------
# 退出码语义（引擎契约，UI 状态机的唯一依据）
# ---------------------------------------------------------------------------
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_GATE_BLOCKED = 2
EXIT_FUSE = 3
EXIT_WAIT_CONFIRM = 4
EXIT_INTERRUPTED = 130

EXIT_MEANING = {
    EXIT_OK: ("ok", "成功"),
    EXIT_ERROR: ("error", "执行出错"),
    EXIT_GATE_BLOCKED: ("gate", "门禁/校验未过"),
    EXIT_FUSE: ("fuse", "熔断或检测到计费（已停止，请先排障）"),
    EXIT_WAIT_CONFIRM: ("confirm", "等待用户确认"),
    EXIT_INTERRUPTED: ("interrupted", "被中断"),
}

SECRET_ENV_NAMES = (
    "RUNNINGHUB_API_KEY", "RUNNINGHUB_API_KEY_2",
    "RUNNINGHUB_ENT_API_KEY", "RUNNINGHUB_ENT_API_KEY_2",
    "RH_API_KEY", "SOLODRAMA_PAT", "GITHUB_PAT",
    "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY",
)

_B64_RE = re.compile(r"(base64,)[A-Za-z0-9+/=]{80,}")
_PATH_SECRET_RE = re.compile(r"(sk-|Bearer\s+)[A-Za-z0-9_\-]{12,}")


def exit_meaning(code) -> dict:
    key, zh = EXIT_MEANING.get(code, ("unknown", "未知退出码 %s" % code))
    return {"code": code, "kind": key, "text": zh}


# ---------------------------------------------------------------------------
# 打码
# ---------------------------------------------------------------------------
def _registry_secrets() -> list:
    """从用户级环境变量取真实密钥值（仅内存使用，绝不落盘/外传）。"""
    names = set(SECRET_ENV_NAMES)
    vals = []
    for n in names:
        v = os.environ.get(n)
        if v and len(v) > 6:
            vals.append(v)
    if os.name == "nt":
        try:
            import winreg  # noqa: PLC0415

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                for n in names:
                    try:
                        v, _ = winreg.QueryValueEx(k, n)
                    except FileNotFoundError:
                        continue
                    if v and len(str(v)) > 6:
                        vals.append(str(v))
        except Exception:  # noqa: BLE001
            pass
    return sorted(set(vals), key=len, reverse=True)


def mask(v: str) -> str:
    """与 `drama.py` 同口径的短串打码。"""
    v = (v or "").strip()
    if not v:
        return "(未设置)"
    return (v[:6] + "****" + v[-4:]) if len(v) > 10 else "****"


def mask_text(text: str) -> str:
    """把文本里的密钥与超长 base64 抹掉（日志流 / 接口返回统一入口）。"""
    if not text:
        return text
    out = text
    for s in _registry_secrets():
        if s in out:
            out = out.replace(s, mask(s))
    out = _B64_RE.sub(r"\1<omitted>", out)
    out = _PATH_SECRET_RE.sub(lambda m: m.group(1) + "****", out)
    return out


# ---------------------------------------------------------------------------
# 环境与执行
# ---------------------------------------------------------------------------
def base_env(ws=None) -> dict:
    """构造子进程环境：工作区 + UTF-8 + 引擎目录指针。

    ★ `SOLODRAMA_WORKSPACE` 必须由本层显式注入 —— 引擎 CLI 没有 `--workspace` 全局参数。
    """
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.setdefault("SOLODRAMA_PYTHON", paths.engine_python())
    env.setdefault("RUNNINGHUB_BASE_URL", "https://www.runninghub.ai")
    if ws:
        w = str(Path(ws).expanduser().resolve())
        env["SOLODRAMA_WORKSPACE"] = w
        env["DRAMA_WORKSPACE"] = w          # 旧名兼容
        lay = paths.ensure_layout_importable()
        if lay is not None:
            try:
                env["VIDEO_PIPELINE_WORKSPACE"] = str(lay.engine_root(w))
            except Exception:  # noqa: BLE001
                pass
    return env


def _popen(argv, ws=None, cwd=None):
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(
        [str(a) for a in argv],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        cwd=str(cwd or paths.REPO_ROOT),
        env=base_env(ws),
        **kwargs,
    )


def run_stream(argv, ws=None, cwd=None, on_line=None, timeout=None):
    """流式执行；返回 dict(rc, lines, elapsed)。

    `on_line(str)` 每行回调一次（作业层用来入库 + 推送 SSE）。
    """
    t0 = time.time()
    proc = _popen(argv, ws=ws, cwd=cwd)
    lines = []
    try:
        for raw in proc.stdout:                                  # type: ignore[union-attr]
            line = mask_text(raw.rstrip("\r\n"))
            lines.append(line)
            if on_line is not None:
                try:
                    on_line(line)
                except Exception:  # noqa: BLE001
                    pass
            if timeout and (time.time() - t0) > timeout:
                kill_tree(proc.pid)
                lines.append("[WARN] 超过本地看护超时，已终止子进程")
                break
        proc.wait()
    finally:
        try:
            if proc.stdout is not None:
                proc.stdout.close()
        except Exception:  # noqa: BLE001
            pass
    return {"rc": proc.returncode, "lines": lines, "elapsed": round(time.time() - t0, 1)}


def capture(argv, ws=None, timeout=120) -> tuple:
    """一次性捕获（用于只读聚合）。返回 (rc, stdout, stderr合并)。"""
    r = run_stream(argv, ws=ws, timeout=timeout)
    return r["rc"], "\n".join(r["lines"]), r["elapsed"]


def kill_tree(pid: int) -> None:
    """Windows 下连子孙一起杀（引擎会再 spawn 子进程）。"""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, check=False)
        else:
            os.kill(pid, 9)
    except Exception:  # noqa: BLE001
        pass


RUN_LOCK = threading.Lock()


def python_exe() -> str:
    return paths.engine_python() or sys.executable
