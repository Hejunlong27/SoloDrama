#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""env_check.py —— 开工前的环境自检（零网络、零第三方依赖、可离线跑）

为什么要它
----------
本项目最常见的坑不是「没装依赖」，而是**装了但装给了另一个解释器**：

    实测 2026-10-20：Pillow 12.2.0 装在 WorkBuddy 托管 venv
    `~/.workbuddy/binaries/python/envs/default/`，
    而 `python` 命令指向 `~/.workbuddy/binaries/python/versions/3.13.12/`（base）。
    结果：6 个封面测试全红、OOM 测试报 `ModuleNotFoundError: No module named 'PIL'`
    —— **代码没坏，环境错配**，但报错信息完全看不出这一点，会让人去改代码。

本脚本只做一件事：**以当前解释器为准**，把「缺什么、装到哪、怎么装」说清楚。

检查分三层
----------
    必需（创作/出片主链路）  Python ≥3.10、Pillow、ffmpeg、ffprobe
    可选（云端/放大/识别）   httpx、whisper-cli、Topaz、ComfyUI 端口、RunningHub Key
    完整性                   manifest.sha256 自校验（抽查全部受管文件）

用法
----
    python tools/env_check.py              # 人读报告
    python tools/env_check.py --json       # 机器读（CI / Agent）
    python tools/env_check.py --quiet      # 只列未通过的项
    python tools/env_check.py --fix        # 额外打印逐条修复命令（不执行任何安装）

退出码：0 = 必需项齐备｜2 = 有必需项缺失（**不要在这个状态下往下走**）
"""
from __future__ import annotations

import argparse
import glob
import importlib.util
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path

MIN_PY = (3, 10)
ROOT = Path(__file__).resolve().parents[1]

# (import 名, 包名, 用途, 是否必需)
LIBS = [
    ("PIL", "Pillow", "封面排版/叠字兜底（cover_forge）、图像体检", True),
    ("httpx", "httpx", "RunningHub 云端通道", False),
]

# (可执行名, 用途, 是否必需, 缺失时的安装提示)
BINS = [
    ("ffmpeg", "拼接 / 2K 放大 / 字幕烧录", True,
     "winget install Gyan.FFmpeg（macOS: brew install ffmpeg）"),
    ("ffprobe", "媒体时长与像素验收", True,
     "随 ffmpeg 一起安装（winget install Gyan.FFmpeg）"),
    ("whisper-cli", "字幕识别（可选，也可用平台字幕）", False,
     "见 stages/subtitle/references/：whisper.cpp release 或自行编译；不装也能用平台字幕"),
]

ENV_KEYS = [
    ("RUNNINGHUB_API_KEY", "云端出片通道（缺了只能走本地 ComfyUI）"),
]

# 这些变量的坑不在「有没有设置」，而在「设了但当前进程读不到」——
# 进程环境是**启动快照**：改完用户级变量不重开终端，永远读到旧值。
# 症状千奇百怪（装了说没装、改了站点说 Key 错、工作区说找不到），唯独不像变量过期。
#
# 站点（RUNNINGHUB_BASE_URL）已从本表移除：2026-11-01 起它是**死变量**，
# 真源是 configs/channels.json，不再读它 —— 对一个不生效的变量做「有没有设」的检查，
# 只会让「设了但没生效」继续冒充「配置正常」。
SNAPSHOT_KEYS = ("RUNNINGHUB_API_KEY", "SOLODRAMA_WORKSPACE")

IS_WIN = os.name == "nt"
EXE = "python.exe" if IS_WIN else "python3"


# ---------------------------------------------------------------------------
def _lib_state(name: str) -> tuple:
    """当前解释器里能否导入 → (bool, 版本号或'')。"""
    if importlib.util.find_spec(name) is None:
        return False, ""
    try:
        mod = __import__(name)
        return True, str(getattr(mod, "__version__", "") or "")
    except Exception:                                            # noqa: BLE001
        return False, ""


def _dist_version(dist: str) -> str:
    try:
        from importlib.metadata import version
        return version(dist)
    except Exception:                                            # noqa: BLE001
        return ""


def _alt_interpreters() -> list:
    """同机上可能装了依赖的其他解释器（**只用来提示，不切换**）。

    返回**原始大小写**的路径，`envs/default` 排在最前（本项目约定的项目环境）。
    """
    import glob
    home = Path.home()
    patterns = [
        str(home / ".workbuddy" / "binaries" / "python" / "envs" / "*" / "Scripts" / EXE),
        str(home / ".workbuddy" / "binaries" / "python" / "envs" / "*" / "bin" / EXE),
        str(home / ".workbuddy" / "binaries" / "python" / "versions" / "*" / EXE),
        "C:/Python3*/" + EXE,
        str(home / "anaconda3" / EXE),
        str(home / "miniconda3" / EXE),
        "/usr/bin/python3",
        "/usr/local/bin/python3",
    ]
    found, seen = [], {str(Path(sys.executable).resolve()).casefold()}
    for pat in patterns:
        for hit in glob.glob(pat):
            try:
                key = str(Path(hit).resolve()).casefold()
            except OSError:
                continue
            if key in seen:
                continue
            seen.add(key)
            found.append(hit)
    found.sort(key=lambda s: 0 if ("envs\\default\\" in s.lower()
                                   or "envs/default/" in s.lower()) else 1)
    return found


def _probe_alt(py: str, module: str) -> tuple:
    """在另一个解释器里探测模块 → (bool, 版本号)。超时或失败都算没有。"""
    code = ("import importlib.util,sys;"
            "sys.exit(0) if importlib.util.find_spec(%r) is None else "
            "print(getattr(__import__(%r),'__version__',''))" % (module, module))
    try:
        r = subprocess.run([py, "-c", code], capture_output=True, text=True,
                           timeout=6, encoding="utf-8", errors="replace")
        return r.returncode == 0 and bool((r.stdout or "").strip()), (r.stdout or "").strip()
    except Exception:                                            # noqa: BLE001
        return False, ""


def _bin_candidates(name: str) -> list:
    """常见安装位置候选（Windows 为主，其它平台返回 PATH 之外的空列表）。"""
    if not IS_WIN:
        return []
    exe = name if name.lower().endswith(".exe") else name + ".exe"
    home = Path.home()
    la = os.environ.get("LOCALAPPDATA") or str(home / "AppData" / "Local")
    cands = [
        # winget 安装的可执行文件实际落在这里，但只有**新开**的终端才在 PATH 里
        Path(la) / "Microsoft" / "WinGet" / "Links" / exe,
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
    ]
    out = [str(p) for p in cands if str(p).lower().endswith(".exe") and Path(p).is_file()]
    # 用户目录下的常见解压式安装（whisper-cli / ffmpeg 静态包等）
    for pat in (str(home / name / "**" / exe), str(home / "*" / name / "**" / exe)):
        out += glob.glob(pat, recursive=True)[:5]
    # 项目自带的 envs/ 与同级工具目录
    for pat in (str(ROOT / "envs" / "*" / exe), str(ROOT / "tools" / "bin" / exe),
                str(ROOT / "vendor" / "**" / exe)):
        out += glob.glob(pat, recursive=True)[:5]
    # Program Files 下两层内（ffmpeg 常是 <PF>\ffmpeg\bin\ffmpeg.exe）
    # ⚠ 这里曾经写成 `r"C://Program Files"` —— 反斜杠被写盘过程吃成斜杠，
    #   而这几个路径**永远不会命中**，于是「装在 Program Files 里的工具」被判成没装。
    #   正是「明明装了却说没装」的又一条来源，且不报错、不告警。
    for base in (r"C:\Program Files", r"C:\Program Files (x86)", r"D:\Program Files"):
        out += glob.glob(os.path.join(base, "*", "**", exe), recursive=True)[:5]
    # 去重保序
    seen, uniq = set(), []
    for p in out:
        k = p.lower()
        if k not in seen and Path(p).is_file():
            seen.add(k)
            uniq.append(p)
    return uniq


def _resolved_site() -> tuple:
    """→ (站点, 来源, 被忽略的旧环境变量值)。实现在 `stages/production/scripts/_site.py`。

    体检不自己算站点：算第二份就一定会有两份不一致，而「三方各说各话」正是这次要收掉的东西。
    """
    try:
        scripts = ROOT / "stages" / "production" / "scripts"
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        from _site import runtime_site
        return runtime_site()
    except Exception as exc:                                   # noqa: BLE001
        return ("", "站点真源读取失败（%s）" % type(exc).__name__, "")


def _persisted_env(name: str) -> tuple:
    """→ (值, 作用域)。读 Windows 注册表里的**持久化**用户/机器环境变量。

    为什么需要它：`os.environ` 只是**本进程启动时的快照**。用户 `setx` 之后，
    已经开着的终端、Studio、以及由它们派生的子进程全都读不到新值。
    只有同时拿到「进程值」和「持久化值」，才能区分「没设」与「设了但本进程没读到」——
    这两件事的修法完全相反（一个去填值，一个去重开终端）。
    """
    if not IS_WIN:
        return ("", "")
    try:
        import winreg
    except Exception:                                          # noqa: BLE001
        return ("", "")
    for scope, root, path in (
            ("User", winreg.HKEY_CURRENT_USER, "Environment"),
            ("Machine", winreg.HKEY_LOCAL_MACHINE,
             r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
        try:
            with winreg.OpenKey(root, path) as h:
                v, _ = winreg.QueryValueEx(h, name)
                if v not in (None, ""):
                    return (str(v), scope)
        except OSError:
            continue
    return ("", "")


def _probe_bin(name: str) -> tuple:
    """→ (state, path, 来源说明)。state ∈ present / found_elsewhere / missing。"""
    got = shutil.which(name)
    if got:
        return "present", got, "PATH"
    for p in _bin_candidates(name):
        return "found_elsewhere", p, "不在 PATH，按安装位置找到"
    return "missing", "", ""


def _port_open(host: str, port: int, timeout: float = 0.8) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _manifest_state() -> tuple:
    """manifest.sha256 自校验 → (总条数, 不符条数, 是否存在)。"""
    import hashlib
    mf = ROOT / "manifest.sha256"
    if not mf.is_file():
        return 0, 0, False      # 不在仓库根（例如被 scaffold 拷进项目后）—— 属正常
    total = bad = 0
    for line in mf.read_text(encoding="utf-8").splitlines():
        if "  *" not in line:
            continue
        digest, _, rel = line.partition("  *")
        total += 1
        f = ROOT / rel
        if not f.is_file():
            bad += 1
            continue
        try:
            if hashlib.sha256(f.read_bytes()).hexdigest() != digest:
                bad += 1
        except OSError:
            bad += 1
    return total, bad, True


# ---------------------------------------------------------------------------
def collect() -> dict:
    items = []

    # 1) 运行时
    v = sys.version_info
    items.append({
        "group": "运行时", "name": "Python",
        "ok": (v.major, v.minor) >= MIN_PY, "required": True,
        "detail": "%d.%d.%d" % (v.major, v.minor, v.micro),
        "hint": "需要 %d.%d+（本项目实测 3.13）：https://www.python.org/downloads/"
                % MIN_PY,
    })
    items.append({
        "group": "运行时", "name": "当前解释器", "ok": True, "required": True,
        "detail": sys.executable, "hint": "",
    })
    items.append({
        "group": "运行时", "name": "虚拟环境",
        "ok": sys.prefix != getattr(sys, "base_prefix", sys.prefix),
        "required": False,
        "detail": ("是：" + sys.prefix) if sys.prefix != getattr(sys, "base_prefix", sys.prefix)
                  else "否（直接用系统/托管解释器）",
        "hint": "建议用独立 venv，避免依赖互相污染",
    })

    # 2) Python 依赖
    for mod, dist, why, req in LIBS:
        ok, ver = _lib_state(mod)
        items.append({
            "group": "依赖", "name": dist, "ok": ok, "required": req,
            "detail": (("已装 " + (ver or _dist_version(dist) or "未知版本")) if ok
                       else "未在当前解释器安装") + "　·　" + why,
            "hint": "" if ok else "pip install -r requirements.txt",
        })

    # 3) 外部程序 —— 三态：present / found_elsewhere / missing
    #    为什么不能只 shutil.which：
    #      E1 装了但不在 PATH（whisper-cli 常在 C:\Users\<u>\whisper-cli\...）；
    #      E2 PATH 是进程启动快照，装完不重开终端就永远找不到（winget 的 Links 目录最典型）；
    #      E3 依赖装在另一个解释器里（_probe_alt 找到了，却只写成 hint）。
    #    以前这三种都归成「未安装」，于是「明明装了却说没装」。
    for name, why, req, how in BINS:
        state, got, src = _probe_bin(name)
        ok = state in ("present", "found_elsewhere")
        if state == "present":
            detail = "%s　·　%s" % (got, why)
            hint = ""
        elif state == "found_elsewhere":
            detail = "%s（%s）　·　%s" % (got, src, why)
            hint = "已安装，只是不在 PATH；加入 PATH 后其它工具也能直接用"
        else:
            detail = "未找到（PATH 与常见安装目录都查过）　·　" + why
            hint = how
        items.append({
            "group": "外部程序", "name": name, "ok": ok, "required": req,
            "state": state, "path": got, "detail": detail, "hint": hint,
        })

    # 4) 配置
    for key, why in ENV_KEYS:
        val = os.environ.get(key)
        items.append({
            "group": "配置", "name": key, "ok": bool(val), "required": False,
            "detail": ("已设置 " + (val[:4] + "…" if val and len(val) > 4 else "…")) if val
                      else "未设置（" + why + "）",
            "hint": "" if val else "setx %s \"<值>\"  然后重开终端" % key,
        })

    # 站点：真源是 configs/channels.json，不看环境变量（旧变量已废弃）
    site_url, site_src, site_dead = _resolved_site()
    items.append({
        "group": "配置", "name": "RunningHub 站点",
        "ok": bool(site_url), "required": False,
        "detail": ("%s（来源：%s）" % (site_url, site_src)) if site_url
                  else "取不到（%s）" % site_src,
        "hint": ("环境变量里还留着 %s —— 已不生效，建议删掉，免得下次 `echo` 到旧值又排查一轮"
                 % site_dead) if site_dead else "",
    })
    items.append({
        "group": "配置", "name": "ComfyUI 本地端口",
        "ok": _port_open("127.0.0.1", 8188), "required": False,
        "detail": "127.0.0.1:8188 " + ("可达" if _port_open("127.0.0.1", 8188) else "未监听（出图时会自动启动）"),
        "hint": "本地出图默认￥0；没启动时 Studio 会拉起一个后台实例，不用先开桌面版",
    })

    # 4.5) 环境快照 —— 治「设了但当前进程没读到」这类假阴性
    #      以前这些全被归成「未设置 / 不存在」，于是同样的现象反复被当成新问题排查。
    for key in SNAPSHOT_KEYS:
        proc = os.environ.get(key) or ""
        pers, scope = _persisted_env(key)

        def _fmt(v: str) -> str:
            if not v:
                return "（空）"
            if "KEY" in key:
                return "长度 %d / 前 4 位 %s…" % (len(v), v[:4])
            return v

        dangling = []
        if key == "SOLODRAMA_WORKSPACE":
            for label, val in (("进程", proc), ("持久化", pers)):
                if val and not Path(val).expanduser().is_dir():
                    dangling.append("%s:%s" % (label, val))

        if not proc and not pers:
            state, ok = "missing", True
            detail = "未设置（不带 --workspace 时才需要；也可以一直显式传）"
            hint = ""
        elif proc and pers and proc == pers:
            state, ok = "present", True
            detail = "进程与持久化一致：%s" % _fmt(proc)
            hint = ""
        elif pers and not proc:
            state, ok = "stale", False
            detail = "持久化有（%s）：%s，但**本进程没读到**" % (scope, _fmt(pers))
            hint = "关掉所有终端 / Studio 重开 —— 进程环境是启动快照，setx 只对**新**进程生效"
        elif proc and not pers:
            state, ok = "process_only", True
            detail = "仅当前进程有效：%s（没有持久化值）" % _fmt(proc)
            hint = "这是临时 export，重开终端就丢；要长期生效请 setx"
        else:
            state, ok = "stale", False
            detail = "进程=%s ｜ 持久化(%s)=%s" % (_fmt(proc), scope, _fmt(pers))
            hint = "重开终端让持久化值生效；若持久化那个才是旧的，就改它"

        if dangling:
            ok = False
            state = "dangling"
            detail += "；目录不存在（%s）" % "、".join(dangling)
            hint = ("这个变量指向的项目已删除/改名 —— 每次不带 --workspace 都会落到死路径，"
                    "而报错看起来像「找不到剧本」。改指向真实项目，或删掉它（推荐：显式传 --workspace）")

        items.append({
            "group": "环境快照", "name": key, "ok": ok, "required": False,
            "state": state, "detail": detail, "hint": hint,
        })

    # 5) 仓库完整性
    total, bad, found = _manifest_state()
    if not found:
        items.append({
            "group": "完整性", "name": "manifest.sha256", "ok": True, "required": False,
            "detail": "未找到清单（被拷进项目后属正常，跳过）", "hint": "",
        })
    else:
        items.append({
            "group": "完整性", "name": "manifest.sha256",
            "ok": bad == 0, "required": False,
            "detail": ("%d 条受管文件，%d 条不符" % (total, bad)) if bad
                      else "%d 条受管文件全部一致" % total,
            "hint": "" if bad == 0 else "仓库文件被改动过（或清单过期），重跑重建脚本",
        })

    # 6) 解释器错配检测（本脚本的核心价值）
    missing_libs = [d for m, d, _w, r in LIBS if r and not _lib_state(m)[0]]
    alt_found = {}
    if missing_libs:
        for py in _alt_interpreters():
            got = {}
            for mod, dist, _w, _r in LIBS:
                if dist in missing_libs:
                    ok, ver = _probe_alt(py, mod)
                    if ok:
                        got[dist] = ver or "已装"
            if got:
                alt_found[py] = got

    return {
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "platform": "%s %s" % (platform.system(), platform.release()),
        "items": items,
        "alt_interpreters": alt_found,
        "ok": all(i["ok"] for i in items if i["required"]),
    }


# ---------------------------------------------------------------------------
def render(rep: dict, only_failed: bool = False) -> str:
    L = ["=" * 74,
         "SoloDrama 环境自检　Python %s　%s" % (rep["python"], rep["platform"]),
         "=" * 74,
         "  当前解释器：%s" % rep["executable"], ""]
    groups = {}
    for it in rep["items"]:
        groups.setdefault(it["group"], []).append(it)
    for g, rows in groups.items():
        shown = [r for r in rows if (not only_failed or not r["ok"])]
        if not shown:
            continue
        L.append("[%s]" % g)
        for r in shown:
            tag = "OK  " if r["ok"] else ("FAIL" if r["required"] else "WARN")
            if r["ok"] and r["name"] == "当前解释器":
                continue
            L.append("  [%s] %-22s %s" % (tag, r["name"], r["detail"]))
            if not r["ok"] and r["hint"]:
                L.append("         → %s" % r["hint"])
        L.append("")

    if rep["alt_interpreters"]:
        L += ["=" * 74, "★ 依赖装在别的解释器里（这是最常踩的坑）", "=" * 74]
        for py, got in rep["alt_interpreters"].items():
            L.append("  %s" % py)
            L.append("     已装：%s" % "、".join("%s %s" % (k, v) for k, v in got.items()))
        L += ["",
              "  两种修法（**推荐 A**，不装任何东西）：",
              "    A) 用这个解释器跑本项目：",
              "       \"%s\" tools/env_check.py" % list(rep["alt_interpreters"])[0],
              "    B) 给当前解释器补装依赖：",
              "       \"%s\" -m pip install -r requirements.txt" % rep["executable"],
              ""]

    fails = [i for i in rep["items"] if not i["ok"] and i["required"]]
    warns = [i for i in rep["items"] if not i["ok"] and not i["required"]]
    L.append("-" * 74)
    if fails:
        L.append("[NG] %d 项必需条件未满足：%s" % (len(fails), "、".join(i["name"] for i in fails)))
        L.append("     修好再往下走 —— 否则会在中途（出片/字幕/封面）才报错，且报错信息通常指错方向。")
    else:
        L.append("[OK] 必需项齐备%s。可以开工。" % ("（%d 项可选未就绪）" % len(warns) if warns else ""))
    return "\n".join(L)


def render_fix(rep: dict) -> str:
    L = ["=" * 74, "逐条修复命令（**只打印，不执行**）", "=" * 74]
    n = 0
    for it in rep["items"]:
        if it["ok"] or not it["hint"]:
            continue
        n += 1
        L.append("%d) %s —— %s" % (n, it["name"], it["detail"]))
        L.append("   %s" % it["hint"])
    if rep["alt_interpreters"]:
        L += ["", "或直接用已装好依赖的解释器："]
        for py in rep["alt_interpreters"]:
            L.append("   \"%s\" tools/env_check.py" % py)
    if not n and not rep["alt_interpreters"]:
        L.append("没有需要修的项目。")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="SoloDrama 环境自检")
    ap.add_argument("--json", action="store_true", help="输出 JSON（给 CI / Agent 用）")
    ap.add_argument("--quiet", action="store_true", help="只列未通过的项")
    ap.add_argument("--fix", action="store_true", help="额外打印修复命令（不执行）")
    a = ap.parse_args()

    rep = collect()
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print(render(rep, only_failed=a.quiet))
        if a.fix:
            print()
            print(render_fix(rep))
    return 0 if rep["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
