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
    ("RUNNINGHUB_BASE_URL", "必须显式 https://www.runninghub.ai，否则上传报「API Key 不存在」"),
]

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

    # 3) 外部程序
    for name, why, req, how in BINS:
        got = shutil.which(name)
        items.append({
            "group": "外部程序", "name": name, "ok": bool(got), "required": req,
            "detail": (got or "未在 PATH 找到") + "　·　" + why,
            "hint": "" if got else how,
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
    items.append({
        "group": "配置", "name": "ComfyUI 本地端口",
        "ok": _port_open("127.0.0.1", 8188), "required": False,
        "detail": "127.0.0.1:8188 " + ("可达" if _port_open("127.0.0.1", 8188) else "未监听（出图时会自动启动）"),
        "hint": "本地出图默认￥0；没启动时 Studio 会拉起一个后台实例，不用先开桌面版",
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
