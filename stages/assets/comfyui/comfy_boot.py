#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""comfy_boot.py —— 本地 ComfyUI 的「按需启动」守护（零第三方依赖）

为什么需要它
------------
本地出图 ￥0，但前提是 8188 上有一个 ComfyUI 在跑。此前这件事只能由人手点：
`connections._test_comfyui()` 只会说「没启动」，`health._MANUAL_WHY["本机服务"]`
还专门写了「Studio 不替你拉起外部进程」。结果就是每次出图前都要先开一次桌面版。

关键事实（决定了「能不能绕开 GUI」）
------------------------------------
ComfyUI Desktop 只是一个 Electron 外壳：真正的服务是它 spawn 出来的

    <安装目录>\\ComfyUI\\.venv\\Scripts\\python.exe -s ComfyUI\\main.py
        --enable-manager
        --extra-model-paths-config <APPDATA>\\Comfy Desktop\\instance-model-paths\\inst-*.yaml
        --input-directory  <shared>\\input
        --output-directory <shared>\\output

所以**不需要**拉起窗口，直接把这一条命令起起来即可。三个参数不能省：
少了 `--extra-model-paths-config` 会找不到模型（表现为「模型缺失」，极易误判成装坏了），
少了 input/output 目录，产物会落进安装目录而不是桌面版共享目录。

三条纪律
--------
1. **只对 loopback 自动启动**：`127.0.0.1` / `localhost` 之外的地址只探测，绝不在本机起进程。
   用户把地址指向局域网另一台机器时，启动本地实例对他毫无意义，还会白占显存。
2. **在线就 attach，绝不抢端口**：8188 上已经有 ComfyUI（包括他手动开的桌面版）
   就直接复用；桌面版 `portConflict: auto` 会自己让路，不会出现两个实例抢同一端口。
3. **停止只停自己的**：`web/var/comfyui.lock.json` 记 pid，且必须「这个 pid 正在监听这个端口」
   才允许 kill —— 否则 PID 复用会杀掉别人的进程。

调用方（三处，都是同一个 `ensure()`）
-------------------------------------
* `web/core/comfy_launcher.py`（Studio 的连接中心 / 环境体检）
* `stages/production/scripts/gen_assets_local.py`（CLI 与 agent 直接跑出图）
* 任何脚本：`python comfy_boot.py --check | --up | --down`
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_URL = "http://127.0.0.1:8188"
LOCK_NAME = "comfyui.lock.json"
LOG_NAME = "comfyui.log"
LOG_MAX_MB = 5

# Windows 进程创建标志（其余平台为 0）
_DETACHED = 0x00000008
_NEW_GROUP = 0x00000200
_NO_WINDOW = 0x08000000

# 这些是本机 / 局域网服务，必须绕开系统代理（实测本机存在 HTTP_PROXY 时会 502）
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

_START_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def _repo_root() -> Path:
    """.../SoloDrama —— 本文件在 stages/assets/comfyui/ 下，往上三级。"""
    return Path(__file__).resolve().parents[3]


def var_dir() -> Path:
    """运行时目录：环境变量优先，否则仓库 web/var（已被 gitignore）。"""
    for name in ("SOLODRAMA_VAR", "DRAMA_VAR"):
        v = os.environ.get(name)
        if v:
            return Path(v)
    return _repo_root() / "web" / "var"


def _iso(ts: float | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(ts or time.time()))


def _http_json(url: str, timeout: float = 2.5):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with _OPENER.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def parse_url(url: str) -> dict:
    """拆 base_url → {base, host, port, loopback, ok}。不合法时 ok=False。"""
    raw = str(url or "").strip() or DEFAULT_URL
    if "://" not in raw:
        raw = "http://" + raw
    try:
        parts = urllib.request.urlparse(raw)
        port = parts.port or (443 if parts.scheme == "https" else 80)
        host = (parts.hostname or "").lower()
    except ValueError:
        return {"ok": False, "base": raw, "host": "", "port": 0, "loopback": False}
    base = "%s://%s" % (parts.scheme, parts.netloc)
    return {"ok": bool(host), "base": base, "host": host, "port": int(port),
            "loopback": host in ("127.0.0.1", "localhost", "::1", "0.0.0.0")}


def probe(base_url: str = DEFAULT_URL, timeout: float = 2.5) -> dict:
    """只读探测 `/system_stats`（不占 GPU、不产生任务）。"""
    u = parse_url(base_url)
    out = {"online": False, "base_url": u["base"], "version": "", "gpu": "",
           "vram_free_gb": 0.0, "vram_total_gb": 0.0, "reason": ""}
    if not u["ok"]:
        out["reason"] = "bad_url"
        return out
    try:
        st = _http_json(u["base"] + "/system_stats", timeout)
    except urllib.error.HTTPError as e:
        out["reason"] = "http_%s" % e.code
        return out
    except urllib.error.URLError as e:
        msg = str(getattr(e, "reason", e))
        out["reason"] = "refused" if ("refused" in msg.lower() or "10061" in msg) else "unreachable"
        return out
    except (TimeoutError, OSError):
        out["reason"] = "timeout"
        return out
    except ValueError:
        out["reason"] = "not_json"
        return out
    if not isinstance(st, dict) or "system" not in st:
        out["reason"] = "not_comfyui"
        return out
    dev = (st.get("devices") or [{}])[0] or {}
    vtotal = int(dev.get("vram_total") or 0)
    vfree = int(dev.get("vram_free") or 0)
    out.update({
        "online": True,
        "version": str((st.get("system") or {}).get("comfyui_version") or ""),
        "gpu": str(dev.get("name") or ""),
        "vram_total_gb": round(vtotal / 1024 ** 3, 1) if vtotal else 0.0,
        "vram_free_gb": round(vfree / 1024 ** 3, 1) if vfree else 0.0,
    })
    return out


def _port_pids(port: int) -> list:
    """谁在 LISTENING 这个端口 → [pid]。只用于诊断与「停止前的所有权核对」。"""
    try:
        if os.name == "nt":
            r = subprocess.run(["netstat", "-ano"], capture_output=True, timeout=8)
            text = (r.stdout or b"").decode("utf-8", "replace")
            needle = ":%d" % int(port)
            pids = []
            for line in text.splitlines():
                cols = line.split()
                if len(cols) < 5 or cols[3].upper() != "LISTENING":
                    continue
                if cols[1].endswith(needle):
                    try:
                        pids.append(int(cols[4]))
                    except ValueError:
                        continue
            return sorted(set(pids))
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    return []


def pid_alive(pid: int) -> bool:
    try:
        pid = int(pid or 0)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    try:
        r = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/NH"],
                           capture_output=True, timeout=8)
        return str(pid) in (r.stdout or b"").decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return False


# ---------------------------------------------------------------------------
# 发现安装（桌面版登记表 → 显式配置 → 环境变量）
# ---------------------------------------------------------------------------
_SAFE_ARGS = ("--enable-manager", "--enable-assets", "--disable-api-nodes",
              "--disable-metadata", "--preview-method")


def _desktop_dir() -> Path:
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "Comfy Desktop"


def _shared_dirs(install_path: Path) -> tuple:
    """桌面版的共享 input/output：`<桌面数据根>/ComfyUI-Shared`，即安装目录的上上级。"""
    shared = install_path.parent.parent / "ComfyUI-Shared"
    if not shared.is_dir():
        return "", ""
    inp, out = shared / "input", shared / "output"
    return (str(inp) if inp.is_dir() else ""), (str(out) if out.is_dir() else "")


def _model_paths_yaml(inst_id: str) -> str:
    """桌面版为每个实例生成的模型路径 yaml（只读引用，不复制、不修改）。"""
    base = _desktop_dir() / "instance-model-paths"
    exact = base / ("%s.yaml" % inst_id)
    if inst_id and exact.is_file():
        return str(exact)
    if base.is_dir():
        left = sorted(base.glob("*.yaml"))
        if len(left) == 1:
            return str(left[0])
    return ""


def _make_install(name, install_path, comfy_dir, python, source, launch_args="", inst_id=""):
    main_py = comfy_dir / "main.py"
    if not (main_py.is_file() and Path(python).is_file()):
        return None
    args = [a for a in str(launch_args or "").split() if a in _SAFE_ARGS]
    inp, out = _shared_dirs(install_path)
    return {
        "id": inst_id or name,
        "name": name,
        "install_path": str(install_path),
        "comfy_dir": str(comfy_dir),
        "cwd": str(install_path),
        "python": str(python),
        "main_py": str(main_py),
        "source": source,
        "args": args,
        "extra_model_paths": _model_paths_yaml(inst_id) if inst_id else "",
        "input_dir": inp,
        "output_dir": out,
    }


def _venv_python(comfy_dir: Path) -> str:
    cands = [comfy_dir / ".venv" / "Scripts" / "python.exe",
             comfy_dir / ".venv" / "bin" / "python",
             comfy_dir.parent / "standalone-env" / "python.exe"]
    for c in cands:
        if c.is_file():
            return str(c)
    return ""


def discover(launch_cfg: dict | None = None) -> dict:
    """列出可启动的安装。顺序即优先级：显式配置 → 环境变量 → 桌面版登记表。

    返回 {"installs": [...], "desktop": bool, "error": ""}
    """
    out = {"installs": [], "desktop": _desktop_dir().is_dir(), "error": ""}

    cfg = launch_cfg or {}
    if cfg.get("python") and cfg.get("main_py"):
        main_py = Path(str(cfg["main_py"]))
        comfy_dir = Path(str(cfg.get("comfy_dir") or main_py.parent))
        inst = {
            "id": str(cfg.get("install_id") or "config"),
            "name": str(cfg.get("name") or "连接中心指定的安装"),
            "install_path": str(cfg.get("install_path") or comfy_dir.parent),
            "comfy_dir": str(comfy_dir),
            "cwd": str(cfg.get("cwd") or comfy_dir.parent),
            "python": str(cfg["python"]),
            "main_py": str(main_py),
            "source": "config",
            "args": [a for a in (cfg.get("extra_args") or []) if a in _SAFE_ARGS],
            "extra_model_paths": str(cfg.get("extra_model_paths") or ""),
            "input_dir": str(cfg.get("input_dir") or ""),
            "output_dir": str(cfg.get("output_dir") or ""),
        }
        if Path(inst["main_py"]).is_file() and Path(inst["python"]).is_file():
            out["installs"].append(inst)

    home = os.environ.get("COMFYUI_HOME") or ""
    if home:
        h = Path(home)
        for comfy_dir in (h, h / "ComfyUI"):
            py = os.environ.get("COMFYUI_PYTHON") or _venv_python(comfy_dir)
            inst = _make_install("环境变量 COMFYUI_HOME", comfy_dir.parent, comfy_dir,
                                 py, "env") if py else None
            if inst:
                out["installs"].append(inst)
                break

    reg = _desktop_dir() / "installations.json"
    if reg.is_file():
        try:
            entries = json.loads(reg.read_text(encoding="utf-8-sig")) or []
        except (OSError, ValueError) as e:
            out["error"] = "读不了桌面版登记表：%s" % type(e).__name__
            entries = []
        for ent in entries if isinstance(entries, list) else []:
            if str(ent.get("status") or "installed") != "installed":
                continue
            ip = Path(str(ent.get("installPath") or ""))
            comfy_dir = ip / "ComfyUI"
            if not comfy_dir.is_dir():
                continue
            py = _venv_python(comfy_dir)
            inst = _make_install(str(ent.get("name") or ip.name), ip, comfy_dir, py,
                                 "desktop", ent.get("launchArgs") or "", str(ent.get("id") or ""))
            if inst:
                out["installs"].append(inst)

    seen, uniq = set(), []
    for it in out["installs"]:
        key = (it["python"].lower(), it["main_py"].lower())
        if key in seen:
            continue
        seen.add(key)
        uniq.append(it)
    out["installs"] = uniq
    return out


# ---------------------------------------------------------------------------
# 锁文件（谁启动的 / 还能不能停）
# ---------------------------------------------------------------------------
def lock_path() -> Path:
    return var_dir() / LOCK_NAME


def log_path() -> Path:
    return var_dir() / LOG_NAME


def load_lock() -> dict:
    try:
        d = json.loads(lock_path().read_text(encoding="utf-8-sig"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_lock(rec: dict) -> None:
    p = lock_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="") as fh:
            json.dump(rec, fh, ensure_ascii=False, indent=2)
    except OSError:
        pass


def _clear_lock() -> None:
    try:
        lock_path().unlink()
    except OSError:
        pass


def ownership() -> dict:
    """当前锁是否「还算数」。

    ★ 为什么不能只看 pid 存活：两件实测过的事 ——
      ① **监听端口的进程不一定是我们 spawn 的那个**（实测 0.42 起，main.py 会再拉一个
        子进程真正 bind 端口：spawn=23324 而 LISTENING=8792）。所以锁里同时记
         `spawn_pid` 与 `pid`（真正的监听者），就绪时回填后者。
      ② Windows 会复用 PID，会话重启后同一个号可能已经是别的程序。所以要
         「这个 pid 正在监听这个端口」才敢 kill。
    """
    lk = load_lock()
    if not lk:
        return {"owned": False, "reason": "no_lock", "pid": 0, "port": 0}
    spawn_pid = int(lk.get("spawn_pid") or 0)
    pid = int(lk.get("pid") or 0) or spawn_pid
    port = int(lk.get("port") or 0)
    listeners = _port_pids(port) if port else []
    if listeners:
        if pid and pid in listeners:
            return {"owned": True, "reason": "ok", "pid": pid, "spawn_pid": spawn_pid,
                    "port": port, "lock": lk}
        return {"owned": False, "reason": "not_listener", "pid": pid, "spawn_pid": spawn_pid,
                "port": port, "listeners": listeners, "lock": lk}
    if spawn_pid and pid_alive(spawn_pid):
        return {"owned": True, "reason": "booting", "pid": pid or spawn_pid,
                "spawn_pid": spawn_pid, "port": port, "lock": lk}
    return {"owned": False, "reason": "dead", "pid": pid, "spawn_pid": spawn_pid, "port": port}


# ---------------------------------------------------------------------------
# 启动 / 停止
# ---------------------------------------------------------------------------
def build_argv(inst: dict, port: int, host: str = "127.0.0.1") -> list:
    argv = [inst["python"], "-s", inst["main_py"],
            "--port", str(int(port)), "--listen", host]
    # 参数白名单**在这里再过滤一次**：`launch.extra_args` 允许用户手写，
    # 一个笔误（或从桌面版复制来的 --feature-flag）不该把进程起崩。
    argv += [a for a in (inst.get("args") or []) if a in _SAFE_ARGS]
    if inst.get("extra_model_paths"):
        argv += ["--extra-model-paths-config", inst["extra_model_paths"]]
    if inst.get("input_dir"):
        argv += ["--input-directory", inst["input_dir"]]
    if inst.get("output_dir"):
        argv += ["--output-directory", inst["output_dir"]]
    return argv


def _rotate_log(p: Path) -> None:
    try:
        if p.is_file() and p.stat().st_size > LOG_MAX_MB * 1024 * 1024:
            os.replace(str(p), str(p.with_suffix(p.suffix + ".1")))
    except OSError:
        pass


def spawn(inst: dict, port: int, host: str = "127.0.0.1", log: Path | None = None) -> dict:
    """起进程并写锁。**不做就绪等待**（那是 `ensure()` 的事）。"""
    log = log or log_path()
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        _rotate_log(log)
        fh = open(log, "ab")
    except OSError:
        return {"ok": False, "reason": "log_unwritable", "detail": "日志目录不可写：%s" % log}
    flags = 0
    if os.name == "nt":
        flags = _DETACHED | _NEW_GROUP | _NO_WINDOW
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        proc = subprocess.Popen(
            build_argv(inst, port, host),
            cwd=inst.get("cwd") or inst.get("comfy_dir"),
            stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT,
            env=env, creationflags=flags, close_fds=True,
        )
    except (OSError, ValueError) as e:
        fh.close()
        return {"ok": False, "reason": "spawn_failed",
                "detail": "%s: %s" % (type(e).__name__, str(e)[:200])}
    finally:
        try:
            fh.close()
        except OSError:
            pass
    rec = {"pid": int(proc.pid), "spawn_pid": int(proc.pid), "port": int(port),
           "started_at": time.time(),
           "started_iso": _iso(), "install_id": inst.get("id"),
           "install_name": inst.get("name"), "python": inst.get("python"),
           "main_py": inst.get("main_py"), "log": str(log), "url": ""}
    _save_lock(rec)
    return {"ok": True, "pid": int(proc.pid), "lock": rec}


def log_tail(lines: int = 25, log: Path | None = None) -> str:
    p = log or log_path()
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    rows = [r for r in text.splitlines() if r.strip()]
    return "\n".join(rows[-max(1, int(lines)):])


def classify(tail: str) -> tuple:
    """把日志尾巴翻成「人话原因 + 下一步」。判不出就返回空。"""
    low = (tail or "").lower()
    table = [
        ("no module named 'torch'", "torch_missing", "这个环境里没有 torch，ComfyUI 起不来", "用桌面版启动一次让它自检，或重装该实例的依赖"),
        ("out of memory", "oom", "显存不足（OOM）", "关掉其它占显卡的程序，或换低显存工作流"),
        ("cuda", "cuda", "CUDA 初始化失败", "更新显卡驱动；确认没有别的进程占满显存"),
        ("address already in use", "port_busy", "端口已被占用", "换一个端口，或先关掉占用它的程序"),
        ("error while attempting to bind", "port_busy", "端口已被占用", "换一个端口，或先关掉占用它的程序"),
        ("no such file or directory: 'main.py'", "bad_cwd", "工作目录不对，找不到 main.py", "检查安装路径是否完整"),
    ]
    for needle, code, detail, nxt in table:
        if needle in low:
            return code, detail, nxt
    return "", "", ""


def stop() -> dict:
    """只停「Studio 自己启动的」那个实例。

    杀的是**进程树**（spawn_pid 起头）：实测 0.42 的 main.py 会再拉一个子进程去 bind
    端口，只杀监听者会留下父进程空转，只杀父进程又会留下孤儿监听者。
    """
    own = ownership()
    reason = own.get("reason")
    if reason == "no_lock":
        return {"ok": False, "reason": "no_lock",
                "detail": "没有由 Studio 启动的实例（手动打开的请自己关窗口）"}
    port = int(own.get("port") or 0)
    if reason == "dead":
        _clear_lock()
        return {"ok": True, "action": "already_down", "pid": int(own.get("pid") or 0),
                "detail": "进程已经不在了，已清理记录"}
    if not own.get("owned"):
        return {"ok": False, "reason": reason,
                "detail": "端口 %s 上的 ComfyUI 不是 Studio 启动的（监听者 pid=%s），不去动它"
                          % (port, own.get("listeners"))}
    pids = sorted({int(p) for p in (own.get("spawn_pid"), own.get("pid")) if p})
    killed = []
    for pid in pids:
        if not pid_alive(pid):
            continue
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                               capture_output=True, timeout=20)
            else:
                os.kill(pid, 9)
            killed.append(pid)
        except (OSError, subprocess.SubprocessError) as e:
            return {"ok": False, "reason": "kill_failed",
                    "detail": "%s: %s" % (type(e).__name__, str(e)[:160])}
    for _ in range(25):                 # 等端口真正释放，别急着说「已停止」
        if not _port_pids(port):
            break
        time.sleep(0.2)
    left = _port_pids(port)
    if left:
        return {"ok": False, "reason": "still_listening",
                "detail": "已发出停止命令，但端口 %d 仍有监听者 %s（可能是另一个实例）" % (port, left)}
    _clear_lock()
    return {"ok": True, "action": "stopped", "pid": pids[-1] if pids else 0, "killed": killed,
            "detail": "已停止%s" % ("（pid %s）" % "、".join(str(p) for p in killed) if killed else "")}


def _autostart_default() -> bool:
    for name in ("SOLODRAMA_COMFY_AUTOSTART", "DRAMA_COMFY_AUTOSTART"):
        raw = os.environ.get(name)
        if raw is not None and str(raw).strip() != "":
            return str(raw).strip().lower() not in ("0", "false", "no", "off")
    return True


def ensure(base_url: str = DEFAULT_URL, autostart: bool | None = None,
           wait_s: int = 120, log=None, launch_cfg: dict | None = None,
           probe_timeout: float = 2.5) -> dict:
    """确保 base_url 上有一个在线的 ComfyUI；不在线就按需启动并等它就绪。

    返回 {ok, action, detail, next, ...}，action ∈
      attached（复用现有实例）/ started（本次拉起）/ refused（不该启动）/ failed
    幂等：并发调用不会起第二个实例（进程内锁 + 「端口已被监听就不再启动」）。
    """
    say = log or (lambda _m: None)
    u = parse_url(base_url)
    started_at = time.time()

    st = probe(u["base"], probe_timeout)
    if st["online"]:
        return dict(st, ok=True, action="attached", detail=_detail(st),
                    next="", elapsed=0.0, install=None, pid=0)

    if not u["ok"]:
        return {"ok": False, "action": "refused", "reason": "bad_url",
                "base_url": u["base"], "detail": "地址不合法：%s" % base_url,
                "next": "在连接中心填 http://127.0.0.1:8188", "elapsed": 0.0}
    if not u["loopback"]:
        return {"ok": False, "action": "refused", "reason": "remote",
                "base_url": u["base"], "detail": "目标是远程地址 %s，不会在本机启动实例" % u["host"],
                "next": "远程机器请自行保证 ComfyUI 在线；这里只负责探测", "elapsed": 0.0}
    use_auto = _autostart_default() if autostart is None else bool(autostart)
    if not use_auto:
        return {"ok": False, "action": "refused", "reason": "autostart_off",
                "base_url": u["base"], "detail": "自动启动已关闭（SOLODRAMA_COMFY_AUTOSTART=0）",
                "next": "在连接中心打开「自动启动」，或手动开一次 ComfyUI", "elapsed": 0.0}

    with _START_LOCK:
        # 双检：等锁期间可能已经有人拉起来了
        st = probe(u["base"], probe_timeout)
        if st["online"]:
            return dict(st, ok=True, action="attached", detail=_detail(st),
                        next="", elapsed=round(time.time() - started_at, 1), install=None, pid=0)

        own = ownership()
        if own.get("owned") and int(own.get("port") or 0) == u["port"]:
            say("上一次启动的实例还在初始化（pid=%s），继续等它" % own.get("pid"))
            return _wait_ready(u, int(own["pid"]), started_at, wait_s, say, install=None)

        listeners = _port_pids(u["port"])
        if listeners:
            return {"ok": False, "action": "failed", "reason": "port_busy",
                    "base_url": u["base"],
                    "detail": "端口 %d 被 pid=%s 占用，但它不是 ComfyUI（/system_stats 无有效响应）"
                              % (u["port"], listeners),
                    "next": "关掉占用该端口的程序，或在连接中心换一个端口",
                    "elapsed": round(time.time() - started_at, 1)}

        found = discover(launch_cfg)
        installs = found["installs"]
        if not installs:
            why = found.get("error") or "没找到 ComfyUI 安装（桌面版登记表为空，也没配环境变量）"
            return {"ok": False, "action": "failed", "reason": "no_install",
                    "base_url": u["base"], "detail": why,
                    "next": "在连接中心填「解释器路径 + main.py」，或先用桌面版启动一次",
                    "elapsed": round(time.time() - started_at, 1)}
        inst = installs[0]
        say("启动 %s（%s）…" % (inst["name"], inst["python"]))

        got = spawn(inst, u["port"], u["host"])
        if not got.get("ok"):
            return {"ok": False, "action": "failed", "reason": got.get("reason"),
                    "base_url": u["base"], "detail": got.get("detail") or "启动失败",
                    "next": "看 web/var/comfyui.log 的末尾几行",
                    "elapsed": round(time.time() - started_at, 1)}
        rec = load_lock()
        rec["url"] = u["base"]
        _save_lock(rec)
        return _wait_ready(u, got["pid"], started_at, wait_s, say, install=inst)


def _detail(st: dict) -> str:
    bits = [b for b in (st.get("version") and "v" + str(st["version"]), st.get("gpu")) if b]
    if st.get("vram_free_gb"):
        bits.append("空闲 %.1fG / %.1fG" % (st["vram_free_gb"], st.get("vram_total_gb") or 0))
    return "ComfyUI 在线" + (" · " + " · ".join(bits) if bits else "")


def _wait_ready(u: dict, pid: int, started_at: float, wait_s: int, say, install) -> dict:
    """轮询到就绪 / 进程退出 / 超时。每 5 秒回调一次进度。

    ⚠️ 就绪时必须把锁里的 `pid` 换成**真正监听端口的那个进程**：0.42 的 main.py
    会再拉一个子进程 bind 端口。不回填的话「停止」会误判成 not_listener 而拒绝执行。
    """
    deadline = time.time() + max(5, int(wait_s))
    last_note = 0.0
    while time.time() < deadline:
        time.sleep(0.6)
        st = probe(u["base"], 1.5)
        if st["online"]:
            listeners = _port_pids(u["port"])
            rec = load_lock()
            if rec:
                rec["url"] = u["base"]
                rec["ready_at"] = time.time()
                if listeners and listeners[0] != pid:
                    rec["pid"] = listeners[0]
                    rec["spawn_pid"] = pid
                _save_lock(rec)
            return dict(st, ok=True, action="started", detail=_detail(st),
                        next="", elapsed=round(time.time() - started_at, 1),
                        install=_public(install), pid=(listeners[0] if listeners else pid))
        if not pid_alive(pid):
            listeners = _port_pids(u["port"])
            if listeners:                       # 父进程退出、子进程接管：继续等，别误判成失败
                pid = listeners[0]
                continue
            tail = log_tail(12)
            code, detail, nxt = classify(tail)
            return {"ok": False, "action": "failed", "reason": code or "exited",
                    "base_url": u["base"], "pid": pid,
                    "detail": detail or "进程启动后立即退出了",
                    "next": nxt or "看 web/var/comfyui.log 的末尾几行（多半是缺依赖或端口问题）",
                    "elapsed": round(time.time() - started_at, 1), "log_tail": tail}
        now = time.time()
        if now - last_note >= 5:
            last_note = now
            say("等待 ComfyUI 就绪… %ds" % int(now - started_at))
    tail = log_tail(12)
    return {"ok": False, "action": "failed", "reason": "timeout",
            "base_url": u["base"], "pid": pid,
            "detail": "%d 秒内没等到 /system_stats 响应（进程还活着，可能在加载）" % wait_s,
            "next": "再点一次「启动」会继续等；或看 web/var/comfyui.log 卡在哪",
            "elapsed": round(time.time() - started_at, 1), "log_tail": tail}


def _public(inst) -> dict:
    if not inst:
        return {}
    return {k: inst.get(k) for k in ("id", "name", "python", "main_py", "cwd",
                                     "source", "extra_model_paths")}


def status(base_url: str = DEFAULT_URL, launch_cfg: dict | None = None) -> dict:
    """给界面看的一屏状态（不启动任何东西）。"""
    u = parse_url(base_url)
    st = probe(u["base"], 1.2)
    own = ownership()
    lk = load_lock()
    found = discover(launch_cfg)
    return {
        "ok": True,
        "base_url": u["base"], "port": u["port"], "loopback": u["loopback"],
        "online": st["online"], "version": st["version"], "gpu": st["gpu"],
        "vram_free_gb": st["vram_free_gb"], "vram_total_gb": st["vram_total_gb"],
        "reason": st["reason"],
        "autostart": _autostart_default(),
        "owned": bool(own.get("owned")),
        "pid": int(lk.get("pid") or 0),
        "started_at": float(lk.get("started_at") or 0),
        "started_iso": str(lk.get("started_iso") or ""),
        "install": _public(found["installs"][0]) if found["installs"] else {},
        "installs": [_public(i) for i in found["installs"]],
        "can_start": bool(found["installs"]) and u["loopback"],
        "detail": _detail(st) if st["online"] else _why_not(st),
        "log": str(log_path()),
    }


def _why_not(st: dict) -> str:
    if st["reason"] == "refused":
        return "端口没有服务在监听（ComfyUI 没启动）"
    if st["reason"] == "not_comfyui":
        return "端口有响应，但返回的不是 ComfyUI 的 system_stats"
    if st["reason"] == "timeout":
        return "3 秒内没有响应（可能在启动中或负载过高）"
    if st["reason"] == "unreachable":
        return "连不上（检查地址/防火墙）"
    if st["reason"] == "http_404":
        return "地址指向了别的服务（HTTP 404）"
    return "未在线（%s）" % (st["reason"] or "未知")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="本地 ComfyUI 按需启动守护")
    ap.add_argument("--url", default=os.environ.get("COMFYUI_URL") or DEFAULT_URL)
    ap.add_argument("--check", action="store_true", help="只探测，不启动")
    ap.add_argument("--up", action="store_true", help="不在线就启动并等待就绪")
    ap.add_argument("--down", action="store_true", help="停止由本工具启动的实例")
    ap.add_argument("--wait", type=int, default=120, help="就绪等待秒数，默认 120")
    ap.add_argument("--no-autostart", action="store_true", help="禁止自动启动（只探测）")
    ap.add_argument("--discover", action="store_true", help="列出找到的安装")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    if a.discover:
        d = discover()
        print(json.dumps(d, ensure_ascii=False, indent=2))
        return 0 if d["installs"] else 3
    if a.down:
        r = stop()
    elif a.up:
        r = ensure(a.url, autostart=False if a.no_autostart else None, wait_s=a.wait,
                   log=lambda m: (not a.json) and print("  " + m))
    else:
        r = status(a.url)
    print(json.dumps(r, ensure_ascii=False, indent=2) if a.json else
          "%s  %s" % ("[OK]" if r.get("ok") else "[FAIL]", r.get("detail") or r.get("reason")))
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    raise SystemExit(main())
