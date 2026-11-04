"""系统资源快照：显存 / 内存 / 磁盘。

为什么不用 psutil
----------------
跑服务的解释器（workbuddy 自带的 3.13）里没有 psutil。为了一个监控条去加一个
带 C 扩展的依赖，等于给「普通用户零门槛」加一道坎，而这个项目本来就没有这个依赖。

三项都有 stdlib 解，不需要装任何东西：

| 项 | 来源 |
|---|---|
| 显存 | `nvidia-smi`（NVIDIA 驱动自带，随驱动安装，不需要 Python 包） |
| 内存 | Windows: `GlobalMemoryStatusEx`（ctypes）；Linux: `/proc/meminfo` |
| 磁盘 | `shutil.disk_usage` |

口径说明
--------
* **GiB 而不是 GB**：`/1024³`。资源管理器、任务管理器都按 1024，写 1000 会让人
  对不上号（「我这里明明显示 7.9G」）。
* **显存与内存的「已用」都包含缓存**：Windows 的内存本身就会尽量用满（这才是设计），
  所以长期 70–85% 是正常的，不是「要爆了」。真正危险的是**可用量接近 0**
  （开始换页）。这一点写进前端提示里，免得用户天天看着黄条焦虑。
* **磁盘取「工作区所在盘」+「仓库所在盘」**：只看 C: 没意义 —— 成片落 D:，
  卡住的永远是 D:。同盘去重，否则两个 100% 一样的条会让人以为是两块盘。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import paths

CACHE_TTL = 1.2          # 秒。多标签页同时开着时，不要每个都去 fork 一次 nvidia-smi
_HIST_KEEP = 0           # 历史留在前端，服务端只给当前快照（保持接口无状态）

_CACHE: dict = {}
_SMI: str | None = None
_SMI_TRIED = False

# Windows 下不弹黑框：服务是后台进程，每 3 秒闪一个 cmd 窗口是灾难
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

GiB = 1024.0 ** 3
MiB = 1024.0 ** 2


def _round(v: float, n: int = 1) -> float:
    try:
        return round(float(v), n)
    except (TypeError, ValueError):
        return 0.0


def _pct(used: float, total: float) -> float:
    if not total or total <= 0:
        return 0.0
    return max(0.0, min(1.0, float(used) / float(total)))


# ---------------------------------------------------------------------------
# GPU
# ---------------------------------------------------------------------------
def _find_smi() -> str:
    global _SMI, _SMI_TRIED
    if _SMI_TRIED:
        return _SMI or ""
    _SMI_TRIED = True
    cand = []
    w = shutil.which("nvidia-smi")
    if w:
        cand.append(w)
    if sys.platform == "win32":
        cand += [r"C:\Windows\System32\nvidia-smi.exe",
                 r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"]
    _SMI = next((c for c in cand if c and Path(c).is_file()), "")
    return _SMI


def gpu() -> dict:
    smi = _find_smi()
    if not smi:
        return {"ok": False, "reason": "没找到 nvidia-smi（非 NVIDIA 显卡，或驱动没装）"}

    cmd = [smi,
           "--query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu",
           "--format=csv,noheader,nounits"]
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=2.5,
                            creationflags=_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "nvidia-smi 超时（>2.5s，驱动可能卡住）"}
    except OSError as e:
        return {"ok": False, "reason": "nvidia-smi 起不来：%s" % e}

    if cp.returncode != 0:
        tail = (cp.stderr or cp.stdout or "").strip().splitlines()
        return {"ok": False, "reason": "nvidia-smi 返回 %s：%s"
                                       % (cp.returncode, tail[-1] if tail else "")}

    lines = [ln for ln in (cp.stdout or "").splitlines() if ln.strip()]
    if not lines:
        return {"ok": False, "reason": "nvidia-smi 没有输出（驱动异常）"}

    # 型号名里可能带逗号，所以从右往左取 4 个数字字段
    parts = [p.strip() for p in lines[0].split(",")]
    if len(parts) < 5:
        return {"ok": False, "reason": "nvidia-smi 输出格式不认识：%r" % lines[0][:80]}
    try:
        used = float(parts[-4]) * MiB
        total = float(parts[-3]) * MiB
        util = float(parts[-2])
        temp = float(parts[-1])
    except ValueError:
        return {"ok": False, "reason": "nvidia-smi 数值解析失败：%r" % lines[0][:80]}

    return {
        "ok": True,
        "name": ",".join(parts[:-4]).strip(),
        "used": used, "total": total, "pct": _pct(used, total),
        "used_gib": _round(used / GiB), "total_gib": _round(total / GiB),
        "util": _round(util, 0), "temp": _round(temp, 0),
        "count": len(lines),
    }


# ---------------------------------------------------------------------------
# 内存
# ---------------------------------------------------------------------------
def _mem_windows() -> dict:
    import ctypes

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    st = MEMORYSTATUSEX()
    st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
        raise OSError("GlobalMemoryStatusEx 调用失败")
    total = float(st.ullTotalPhys)
    avail = float(st.ullAvailPhys)
    return {"total": total, "avail": avail,
            "used": max(0.0, total - avail),
            "page_total": float(st.ullTotalPageFile),
            "page_avail": float(st.ullAvailPageFile)}


def _mem_linux() -> dict:
    vals = {}
    with open("/proc/meminfo", "r", encoding="utf-8") as f:
        for line in f:
            k, _, v = line.partition(":")
            n = v.strip().split()
            if n and n[0].isdigit():
                vals[k] = float(n[0]) * 1024.0        # kB → B
    total = vals.get("MemTotal", 0.0)
    avail = vals.get("MemAvailable", vals.get("MemFree", 0.0))
    return {"total": total, "avail": avail, "used": max(0.0, total - avail),
            "page_total": total + vals.get("SwapTotal", 0.0),
            "page_avail": avail + vals.get("SwapFree", 0.0)}


def mem() -> dict:
    try:
        if sys.platform == "win32":
            r = _mem_windows()
        elif Path("/proc/meminfo").is_file():
            r = _mem_linux()
        else:
            return {"ok": False, "reason": "这个系统还没有取内存的实现"}
    except Exception as e:                                  # noqa: BLE001
        return {"ok": False, "reason": "读内存失败：%s" % e}

    total, used = r["total"], r["used"]
    return {
        "ok": True,
        "used": used, "total": total, "pct": _pct(used, total),
        "used_gib": _round(used / GiB), "total_gib": _round(total / GiB),
        "avail_gib": _round(r["avail"] / GiB),
        # 提交量（含页面文件）：真正「要爆」的信号在可用量，不在百分比
        "commit_pct": _pct(r["page_total"] - r["page_avail"], r["page_total"]),
    }


# ---------------------------------------------------------------------------
# 磁盘
# ---------------------------------------------------------------------------
def _disk_root(p: str) -> str:
    """路径 → 盘根。Windows 取 `D:`，POSIX 取 `/` 或挂载点（用路径本身）。"""
    if not p:
        return ""
    path = Path(str(p))
    if sys.platform == "win32":
        drive = path.drive or (Path.cwd().drive)
        return (drive + "\\") if drive else ""
    while not path.exists() and path != path.parent:
        path = path.parent
    return str(path)


def disk(targets) -> list:
    out, seen = [], set()
    for label, p in targets:
        if not p:
            continue
        root = _disk_root(p)
        if not root:
            continue
        key = root.lower() if sys.platform == "win32" else root
        if key in seen:
            continue
        seen.add(key)
        try:
            u = shutil.disk_usage(root)
        except OSError as e:
            out.append({"ok": False, "label": label, "mount": root,
                        "reason": "读不到：%s" % e})
            continue
        out.append({
            "ok": True, "label": label, "mount": root,
            "used": float(u.used), "total": float(u.total), "free": float(u.free),
            "pct": _pct(u.used, u.total),
            "used_gib": _round(u.used / GiB, 1), "total_gib": _round(u.total / GiB, 1),
            "free_gib": _round(u.free / GiB, 1),
        })
    return out


# ---------------------------------------------------------------------------
# 快照
# ---------------------------------------------------------------------------
def snapshot(ws: str = "", *, ttl: float = CACHE_TTL) -> dict:
    key = str(ws or "")
    now = time.time()
    hit = _CACHE.get(key)
    if hit and (now - hit[0]) < ttl:
        return hit[1]

    t0 = time.perf_counter()
    disks = disk([("工作区", key), ("仓库", str(paths.REPO_ROOT))])
    val = {
        "ok": True,
        "ts": now,
        "gpu": gpu(),
        "mem": mem(),
        "disk": disks,
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
    }
    _CACHE[key] = (now, val)
    if len(_CACHE) > 8:                       # 换过很多工作区时别无限攒
        for k in sorted(_CACHE, key=lambda k: _CACHE[k][0])[:-8]:
            _CACHE.pop(k, None)
    return val


def clear_cache() -> None:
    _CACHE.clear()
