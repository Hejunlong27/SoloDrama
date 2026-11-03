# -*- coding: utf-8 -*-
"""updater.py —— 一键下载 / 一键更新（给不想敲命令的人用）

两个按钮，两种语义，不能混
--------------------------
* **一键下载**：把「缺的东西」补上 —— Python 依赖、目录、失效配置、本机 ComfyUI。
  全部走 `health.fix()` 已经验证过的那套（每条修完都会**复检**），不另写一份安装逻辑。
* **一键更新**：把「引擎本身」更新到远端最新，再补依赖、再复检。
  只做 `git pull --ff-only`：绝不 `reset --hard`、绝不丢本地改动。
  拉不动就如实报错（这台机器上 github 直连是被墙的，见 `docs/BRANCH-ENGINE.md`），
  并给出手动路径。

为什么不装第三方包管理器
------------------------
用户机器上已经有 Python 与 pip；再引入 uv/conda 只会多一个失败点。
这里只用 `sys.executable -m pip`，装到**正在跑服务的那个解释器**里 ——
装到别处等于没装（体检会一直红）。

安全边界
--------
* 只跑固定的 argv，不接受任何来自前端的命令字符串；
* `git` 只允许 `pull --ff-only` / `rev-parse` / `log` / `status` 四种只读或快进操作；
* 每一步都有超时；某一步失败不影响「报告」，但不会继续做危险动作。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from . import health, paths

REPO = paths.REPO_ROOT


def _run(argv: list, cwd=None, timeout: int = 180) -> dict:
    t0 = time.time()
    try:
        p = subprocess.run(argv, cwd=str(cwd or REPO), capture_output=True, text=True,
                           timeout=timeout, env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        out = ((p.stdout or "") + (p.stderr or "")).strip()
        return {"ok": p.returncode == 0, "rc": p.returncode,
                "cmd": " ".join(str(x) for x in argv),
                "lines": out.splitlines()[-60:], "elapsed": round(time.time() - t0, 1)}
    except FileNotFoundError:
        return {"ok": False, "rc": 127, "cmd": " ".join(str(x) for x in argv),
                "lines": ["找不到命令：%s" % argv[0]], "elapsed": round(time.time() - t0, 1)}
    except subprocess.TimeoutExpired:
        return {"ok": False, "rc": 124, "cmd": " ".join(str(x) for x in argv),
                "lines": ["超时（%d 秒）：网络或安装卡住了" % timeout],
                "elapsed": round(time.time() - t0, 1)}


# ---------------------------------------------------------------------------
# 现状
# ---------------------------------------------------------------------------
def status() -> dict:
    """引擎版本与依赖现状（只读，不联网）。"""
    git = _run(["git", "rev-parse", "--short", "HEAD"], timeout=20)
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], timeout=20)
    last = _run(["git", "log", "-1", "--pretty=%h %ad %s", "--date=short"], timeout=20)
    dirty = _run(["git", "status", "--porcelain"], timeout=30)
    rep = health.collect(None)
    auto = [i for i in (rep.get("items") or []) if not i.get("ok") and (i.get("fix") or {}).get("auto")]
    manual = [i for i in (rep.get("items") or []) if not i.get("ok") and not (i.get("fix") or {}).get("auto")]
    return {
        "ok": True,
        "repo": str(REPO),
        "is_git": git["ok"],
        "commit": (last["lines"][0] if last["ok"] and last["lines"] else ""),
        "branch": (branch["lines"][0] if branch["ok"] and branch["lines"] else ""),
        "dirty": bool(dirty["ok"] and dirty["lines"]),
        "dirty_files": dirty["lines"][:12] if dirty["ok"] else [],
        "python": sys.executable,
        "requirements": str(REPO / "requirements.txt"),
        "health": {"auto": [i["id"] for i in auto], "manual": [i["name"] for i in manual],
                   "ok": bool(rep.get("ok"))},
        "updated_at": time.time(),
    }


# ---------------------------------------------------------------------------
# 一键下载：补齐缺的东西
# ---------------------------------------------------------------------------
def download_all(ws: str | None = None) -> dict:
    """把当前所有「可自动修」的项跑一遍，每项结束后复检。"""
    before = health.collect(ws)
    targets = [i for i in (before.get("items") or [])
               if not i.get("ok") and (i.get("fix") or {}).get("auto")]
    steps = []
    for it in targets:
        r = health.fix(it["id"], ws)
        steps.append({
            "id": it["id"], "name": it.get("name") or it["id"],
            "action": (it.get("fix") or {}).get("label") or "",
            "ok": bool(r.get("ok")), "verified": bool(r.get("verified")),
            "detail": r.get("detail") or "",
            "lines": (r.get("lines") or [])[-12:],
        })
    after = health.collect(ws)
    left = [i["name"] for i in (after.get("items") or []) if not i.get("ok")]
    return {
        "ok": not left,
        "done": len([s for s in steps if s["ok"]]),
        "total": len(steps),
        "steps": steps,
        "left": left,
        "detail": ("全部就绪：没有未通过的体检项" if not left
                   else "还剩 %d 项没过：%s%s" % (
                       len(left), "、".join(left[:6]),
                       "（其中有些只能人工处理，见「环境体检」）" if any(
                           not (i.get("fix") or {}).get("auto")
                           for i in (after.get("items") or []) if not i.get("ok")) else "")),
        "at": time.time(),
    }


# ---------------------------------------------------------------------------
# 一键更新：拉代码 → 补依赖 → 复检
# ---------------------------------------------------------------------------
def update(ws: str | None = None, *, pip: bool = True) -> dict:
    """`git pull --ff-only` + `pip install -r requirements.txt` + 复检。

    返回逐步结果。**任何一步失败都停下并说清下一步**，不会硬着头皮往下做。
    """
    st = status()
    if not st["is_git"]:
        return {"ok": False, "detail": "这个目录不是 git 仓库，无法一键更新；请重新下载安装包",
                "steps": []}
    steps = []

    pull = _run(["git", "pull", "--ff-only"], timeout=180)
    steps.append({"name": "拉取代码（git pull --ff-only）", **pull})
    if not pull["ok"]:
        tail = "\n".join(pull["lines"][-6:])
        return {
            "ok": False, "steps": steps,
            "detail": ("拉不下来。常见原因：这台机器连不上 github（直连被拒 / 代理只读）、"
                       "或本地有未提交改动挡住了快进。\n"
                       "手动路径：`git pull --ff-only`，或在 GitHub 上重新下载压缩包覆盖。\n"
                       "输出：\n" + tail),
        }

    if pip:
        req = REPO / "requirements.txt"
        if req.is_file():
            r = _run([sys.executable, "-m", "pip", "install", "-q", "-r", str(req)], timeout=600)
            steps.append({"name": "补齐 Python 依赖（pip install -r requirements.txt）", **r})
        else:
            steps.append({"name": "补齐 Python 依赖", "ok": True, "rc": 0,
                          "lines": ["没有 requirements.txt，跳过"], "elapsed": 0})

    after = health.collect(ws)
    left = [i["name"] for i in (after.get("items") or []) if not i.get("ok")]
    steps.append({"name": "复检", "ok": not left, "rc": 0,
                  "lines": (["全部通过"] if not left else ["仍未通过："] + left[:10]), "elapsed": 0})
    return {
        "ok": not left and all(s["ok"] for s in steps[:-1]),
        "steps": steps,
        "left": left,
        "commit": (status().get("commit") or ""),
        "detail": ("已更新到最新，依赖复检通过" if not left
                   else "代码已更新，但还有 %d 项体检未过（多为需要人工处理的项）" % len(left)),
        "at": time.time(),
    }
