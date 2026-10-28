#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""launcher.py —— SoloDrama Studio 启动器（双击 start.cmd 就会走到这里）

它替你处理五件最容易「一启动就报错」的事：
  1. **找对解释器**：当前这个缺 fastapi/uvicorn 时，自动换一个装了的（并说明换了哪个）；
  2. **查依赖**：都没有就给出可复制的安装命令，或问你一句「要不要现在建环境」；
  3. **挑引擎解释器**：字幕/出图那些脚本需要 Pillow + httpx，自动找一个装了的；
  4. **找端口**：8788 被占就从 8789 往后找，不会一启动就 address in use；
  5. **起服务 + 开浏览器**：健康检查通过后才开页面，不会打开一个白屏。

用法：
    python web/launcher.py                 # 默认 127.0.0.1:8788，自动开浏览器
    python web/launcher.py --port 9000
    python web/launcher.py --readonly      # 只读模式：拒绝一切写操作与计费
    python web/launcher.py --no-browser    # 不自动开浏览器
    python web/launcher.py --init          # 只建环境装依赖，不启动

停止：在这个窗口按 Ctrl+C，或直接关掉窗口。
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

WEB = Path(__file__).resolve().parent
REPO = WEB.parent
sys.path.insert(0, str(WEB))

MIN_PY = (3, 10)
DEPS_MODULE = "fastapi, uvicorn, httpx"
DEFAULT_PORT = 8788
PORT_SCAN = 12
VENV_DIR = REPO / "envs" / "solodrama-web"


# ---------------------------------------------------------------------------
# 输出（Windows 控制台默认不是 UTF-8）
# ---------------------------------------------------------------------------
def _fix_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass


def say(msg=""):
    print(msg, flush=True)


def ok(msg):
    print("  [OK]  %s" % msg, flush=True)


def info(msg):
    print("  [--]  %s" % msg, flush=True)


def warn(msg):
    print("  [!!]  %s" % msg, flush=True)


def bad(msg):
    print("  [NG]  %s" % msg, flush=True)


def rule(ch="─", n=66):
    say(ch * n)


def banner():
    say("")
    rule("═")
    say("  SoloDrama Studio · 本地短剧生产工作台")
    rule("═")
    say("")


# ---------------------------------------------------------------------------
# 解释器与依赖
# ---------------------------------------------------------------------------
def has_deps(py) -> bool:
    """这个解释器能不能直接跑控制台。"""
    try:
        r = subprocess.run([str(py), "-c", "import %s" % DEPS_MODULE],
                           capture_output=True, timeout=40)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def venv_python():
    for rel in ("Scripts/python.exe", "bin/python"):
        p = VENV_DIR / rel
        if p.is_file():
            return p
    return None


def runtime_candidates():
    """按「最可能是用户想要的那个」排序。"""
    out = [Path(sys.executable)]
    v = venv_python()
    if v:
        out.append(v)
    for rel in (".venv/Scripts/python.exe", "venv/Scripts/python.exe"):
        p = REPO / rel
        if p.is_file():
            out.append(p)
    # 本机共享的环境目录（WorkBuddy 托管的解释器就在这里）
    root = Path.home() / ".workbuddy" / "binaries" / "python" / "envs"
    if root.is_dir():
        for sub in sorted(root.iterdir()):
            for rel in ("Scripts/python.exe", "bin/python"):
                p = sub / rel
                if p.is_file():
                    out.append(p)
    seen, uniq = set(), []
    for p in out:
        key = str(p).lower()
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    return uniq


def pip_install_cmd(py) -> str:
    return '"%s" -m pip install -r "%s"' % (py, WEB / "requirements-web.txt")


def bootstrap() -> int:
    """建 <repo>/envs/solodrama-web 并装依赖。返回 0 表示成功。"""
    say("")
    info("准备创建专用环境：%s" % VENV_DIR)
    info("用当前解释器：%s" % sys.executable)
    say("")
    rc = subprocess.call([sys.executable, "-m", "venv", str(VENV_DIR)])
    if rc != 0:
        bad("创建 venv 失败（退出码 %d）。可手动执行：" % rc)
        say('       "%s" -m venv "%s"' % (sys.executable, VENV_DIR))
        return 6
    py = venv_python()
    if not py:
        bad("venv 建好了但找不到 python")
        return 6
    info("安装依赖（首次需要联网，约 1 分钟）...")
    rc = subprocess.call([str(py), "-m", "pip", "install", "--disable-pip-version-check",
                          "-r", str(WEB / "requirements-web.txt")])
    if rc != 0:
        bad("装依赖失败（退出码 %d）。可重试：" % rc)
        say("       %s" % pip_install_cmd(py))
        return 7
    ok("专用环境已就绪：%s" % py)
    return 0


def _ask_yes(question: str) -> bool:
    try:
        if not sys.stdin or not sys.stdin.isatty():
            return False
    except (AttributeError, ValueError):
        return False
    try:
        ans = input("  %s [Y/n] " % question).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return ans in ("", "y", "yes")


def ensure_runtime(argv) -> int:
    """保证「即将运行的控制台」有依赖。返回 0 = 可以继续（必要时已换解释器重跑）。"""
    if has_deps(sys.executable):
        return 0

    for p in runtime_candidates():
        if Path(p).resolve() == Path(sys.executable).resolve():
            continue
        if has_deps(p):
            warn("当前解释器缺少依赖，换用已装好的：%s" % p)
            return subprocess.call([str(p), str(Path(__file__).resolve())] + list(argv))

    # 一个都没有：说明白缺什么，给两条路
    bad("没有找到可用的运行环境（缺 fastapi / uvicorn / httpx）")
    say("")
    info("当前解释器：%s" % sys.executable)
    say("")
    info("两条路，任选一条：")
    say("")
    say("    A. 自动装（一次就好）：")
    say('       "%s" "%s" --init' % (sys.executable, Path(__file__).resolve()))
    say("")
    say("    B. 手动装：")
    say("       %s" % pip_install_cmd(sys.executable))
    say("")
    if _ask_yes("要现在就自动创建环境并安装依赖吗？"):
        rc = bootstrap()
        if rc != 0:
            return rc
        py = venv_python()
        if py:
            return subprocess.call([str(py), str(Path(__file__).resolve())] + list(argv))
        return 6
    return 3


# ---------------------------------------------------------------------------
# 引擎解释器（字幕/出图需要 Pillow + httpx）
# ---------------------------------------------------------------------------
def _usable_engine_python(path) -> bool:
    p = Path(str(path))
    if not p.is_file():
        return False
    try:
        r = subprocess.run([str(p), "-c", "import PIL, httpx; print('ok')"],
                           capture_output=True, text=True, timeout=25)
        return r.returncode == 0 and "ok" in (r.stdout or "")
    except (OSError, subprocess.SubprocessError):
        return False


def pick_engine_python():
    env = (os.environ.get("SOLODRAMA_PYTHON") or "").strip()
    if env and _usable_engine_python(env):
        return env, "环境变量 SOLODRAMA_PYTHON"

    cfg = REPO / "configs" / "settings.json"
    try:
        configured = str(json.loads(cfg.read_text(encoding="utf-8-sig")).get("python") or "").strip()
    except (OSError, json.JSONDecodeError, ValueError):
        configured = ""
    if configured and _usable_engine_python(configured):
        return configured, "configs/settings.json"

    for c in runtime_candidates():
        if _usable_engine_python(c):
            return str(c), "自动探测"
    return "", "未找到"


# ---------------------------------------------------------------------------
# 端口
# ---------------------------------------------------------------------------
def port_free(port: int, host="127.0.0.1") -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def pick_port(start: int):
    for p in range(start, start + PORT_SCAN):
        if port_free(p):
            return p, (p != start)
    return 0, False


# ---------------------------------------------------------------------------
# 开浏览器（健康检查通过后再开）
# ---------------------------------------------------------------------------
def _open_when_ready(url_health: str, url_page: str, stop: threading.Event, timeout=45):
    import urllib.error
    import urllib.request

    t0 = time.time()
    while time.time() - t0 < timeout and not stop.is_set():
        try:
            with urllib.request.urlopen(url_health, timeout=2) as r:
                if r.status == 200:
                    webbrowser.open(url_page)
                    return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.4)
    if not stop.is_set():
        say("  （服务没在 %d 秒内就绪，请手动打开：%s）" % (timeout, url_page))


# ---------------------------------------------------------------------------
def main() -> int:
    _fix_stdio()
    ap = argparse.ArgumentParser(description="SoloDrama Studio 启动器")
    ap.add_argument("--host", default=os.environ.get("SOLODRAMA_CONSOLE_HOST", "127.0.0.1"),
                    help="监听地址（默认只监听本机回环）")
    ap.add_argument("--port", type=int, default=int(os.environ.get("SOLODRAMA_CONSOLE_PORT", DEFAULT_PORT)))
    ap.add_argument("--readonly", action="store_true", help="只读模式：拒绝一切写操作与计费动作")
    ap.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    ap.add_argument("--reload", action="store_true", help="开发用：改代码自动重载")
    ap.add_argument("--init", action="store_true", help="只创建专用环境并装依赖，不启动")
    a = ap.parse_args()

    if sys.version_info < MIN_PY:
        banner()
        bad("需要 Python %d.%d+，当前是 %s" % (MIN_PY[0], MIN_PY[1], sys.version.split()[0]))
        return 2

    if a.init:
        banner()
        if venv_python() is not None:
            ok("环境已存在：%s" % venv_python())
            return 0
        return bootstrap()

    # 解释器与依赖（必要时会换解释器重跑自己；提示由本函数打印，先于横幅）
    rc = ensure_runtime(list(sys.argv[1:]))
    if rc != 0:
        return rc

    banner()
    ok("Python %s" % sys.version.split()[0])
    ok("依赖齐备（fastapi / uvicorn / httpx）")

    eng, src = pick_engine_python()
    if eng:
        ok("引擎解释器：%s（%s）" % (eng, src))
        os.environ["SOLODRAMA_PYTHON"] = eng
    else:
        warn("引擎解释器：%s —— 字幕 / 放大 / 本地出图会失败，其余页面正常" % src)
        warn("  修法：在装给引擎的那个 Python 里执行 pip install -r requirements.txt")

    if a.readonly:
        os.environ["SOLODRAMA_CONSOLE_READONLY"] = "1"
        warn("只读模式：写操作、计费动作、模型配置变更都会被拒绝")
    else:
        ok("可写模式（计费动作仍需在页面上二次确认）")

    port, moved = pick_port(a.port)
    if not port:
        bad("从 %d 起连续 %d 个端口都被占用，换一个 --port 再试" % (a.port, PORT_SCAN))
        return 4
    if moved:
        warn("端口 %d 被占用，改用 %d" % (a.port, port))
    ok("端口 %d" % port)

    cur = ""
    try:
        cur = str(json.loads((WEB / "var" / "registry.json").read_text(encoding="utf-8-sig"))
                  .get("current") or "").strip()
    except (OSError, json.JSONDecodeError, ValueError):
        cur = ""
    shown = cur or (os.environ.get("SOLODRAMA_WORKSPACE") or "").strip()
    if shown and Path(shown).is_dir():
        ok("默认项目：%s" % shown)
    elif shown:
        warn("上次的项目已不存在：%s —— 启动后在顶栏「切换项目」重新选" % shown)
    else:
        info("还没有选择项目 —— 启动后点顶栏「切换项目」扫描或登记")

    base = "http://%s:%d" % (a.host, port)
    say("")
    rule()
    say("  工作台   %s/studio/" % base)
    say("  旧控制台 %s/ui/    （命令面板 / 审计）" % base)
    say("")
    say("  停止服务：在这个窗口按 Ctrl+C，或直接关掉窗口。")
    rule()
    say("")

    stop = threading.Event()
    if not a.no_browser:
        threading.Thread(target=_open_when_ready,
                         args=(base + "/api/health", base + "/studio/", stop),
                         daemon=True).start()

    import uvicorn  # noqa: PLC0415

    try:
        uvicorn.run("app:app", host=a.host, port=port, reload=a.reload,
                    app_dir=str(WEB), log_level="warning", access_log=False)
    except KeyboardInterrupt:
        pass
    except OSError as exc:
        stop.set()
        say("")
        bad("启动失败：%s" % exc)
        if "10048" in str(exc) or "in use" in str(exc).lower():
            say("     端口被占用：换一个 --port，或先关掉已在运行的控制台窗口。")
        return 5
    finally:
        stop.set()

    say("")
    say("  已停止。")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        say("")
        say("  已停止。")
