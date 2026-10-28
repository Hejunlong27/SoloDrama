# -*- coding: utf-8 -*-
"""health.py —— 环境体检 + 一键修复

为什么单独一个模块
------------------
`tools/env_check.py` 只负责**诊断**（`--fix` 还只是打印命令）。产品里用户要的是
「点一下就修好」，但这件事故意不能做大：

    能安全自动化的  = 装 Python 包到引擎解释器 / 建 Studio 自己的运行时目录 / 清掉指向空文件的配置
    不能自动化的    = winget 装 ffmpeg（要 UAC）、启动 ComfyUI（外部 GUI 进程）、填 Key（只能人来给）

把后者也做成「一键」的后果是：按钮转两圈、然后告诉你「装好了」，实际什么也没发生 ——
这比没有这个按钮更糟。所以本模块把每一项都标成 `auto` / `manual` / `page`，**如实区分**。

三条纪律
--------
1. **动作白名单在服务端**：接口只接受 `fix_id`，命令由本模块现算；前端永远传不进一条命令。
2. **修完必复检**：`pip` 退出码 0 不等于「现在能 import」，一律重跑 env_check 取同一项的真实状态。
3. **留痕**：每次修复追加一行到 `web/var/health-fixes.jsonl`（时间/动作/命令/rc/耗时/结果）。
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

from . import jsonout, paths, runner

LOG_FILE = paths.VAR_DIR / "health-fixes.jsonl"
LOG_KEEP = 200

# env_check.py 的检查项 → 本页的 id / 修复方式
_ENV_FIX = {
    "Python": ("rt.python", {"kind": "manual"}),
    "虚拟环境": ("rt.venv", {"kind": "manual"}),
    "当前解释器": ("rt.interp", {"kind": "none"}),
    "Pillow": ("dep.pillow", {"kind": "pip", "dist": "Pillow"}),
    "httpx": ("dep.httpx", {"kind": "pip", "dist": "httpx"}),
    "ffmpeg": ("bin.ffmpeg", {"kind": "manual"}),
    "ffprobe": ("bin.ffprobe", {"kind": "manual"}),
    "whisper-cli": ("bin.whisper", {"kind": "manual"}),
    "RUNNINGHUB_API_KEY": ("cfg.rh_key", {"kind": "page", "page": "#/connections"}),
    "RUNNINGHUB_BASE_URL": ("cfg.rh_base", {"kind": "page", "page": "#/connections"}),
    "ComfyUI 本地端口": ("svc.comfy", {"kind": "manual"}),
    "manifest.sha256": ("repo.manifest", {"kind": "manual"}),
}

_GROUP_ORDER = ["运行时", "Python 依赖", "外部程序", "本机服务", "数据目录", "配置", "完整性"]

# 「不能自动修」也要说清为什么 —— 否则用户只会看到一句「需人工」，等于没说
_MANUAL_WHY = {
    "外部程序": "装外部程序要管理员权限（UAC），Studio 不替你弹授权框 —— 复制命令自己跑一次",
    "完整性": "仓库文件被改动过（或清单过期）：确认这些改动是你要的，再重建清单",
    "本机服务": "ComfyUI 是独立的 GUI 程序，Studio 不替你拉起外部进程 —— 自己启动后回来重测",
    "运行时": "需要你先装好对应运行时；Studio 不会替换系统里的 Python",
}


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def _pins() -> dict:
    """requirements.txt 里的精确版本 → {小写包名: "Pillow==12.2.0"}。

    只认这一份清单：它是本仓库验证过的版本，别处不要再抄一遍（会漂）。
    """
    out = {}
    f = paths.REPO_ROOT / "requirements.txt"
    try:
        text = f.read_text(encoding="utf-8-sig")
    except OSError:
        return out
    for line in text.splitlines():
        s = line.split("#", 1)[0].strip()
        if not s or s.startswith("-"):
            continue
        name = re.split(r"[=<>!~\[; ]", s, 1)[0].strip()
        if name:
            out[name.lower()] = s.replace(" ", "")
    return out


def _env_report() -> tuple:
    """跑一次 env_check.py --json → (data, err)。用**引擎解释器**跑，口径才和出片一致。"""
    script = paths.TOOLS_DIR / "env_check.py"
    if not script.is_file():
        return None, "找不到 tools/env_check.py（仓库不完整）"
    r = runner.run_stream([paths.engine_python(), str(script), "--json"], timeout=180)
    data = jsonout.extract_json("\n".join(r["lines"]))
    if not isinstance(data, dict):
        tail = "\n".join(r["lines"][-6:])
        return None, "env_check 未返回 JSON（rc=%s）：%s" % (r["rc"], tail[:300])
    return data, ""


def _writable(d: Path) -> tuple:
    """目录存在且可写。**不在这里建目录** —— 体检是只读的（GET 不该有副作用），
    建目录交给 `_do_mkdir`，否则「检查」会顺手把问题修掉，用户永远看不到它。"""
    if not d.exists():
        return False, "%s 不存在" % d
    if not d.is_dir():
        return False, "%s 不是目录" % d
    if not os.access(str(d), os.W_OK):
        return False, "%s 存在但不可写（权限不足）" % d
    return True, str(d)


def _fmt_cmd(argv) -> str:
    """给界面看的命令串（只用于显示/复制；执行走 argv，不解析这串）。"""
    out = []
    for a in argv:
        s = str(a)
        out.append('"%s"' % s if (" " in s or "\\" in s) else s)
    return " ".join(out)


def _settings_python() -> str:
    """配置里显式指定的 python（环境变量优先，其次 settings.json）。"""
    cand = os.environ.get("SOLODRAMA_PYTHON") or ""
    if cand:
        return cand
    try:
        d = paths.read_json(paths.SETTINGS_FILE, default={}) or {}
    except Exception:  # noqa: BLE001
        return ""
    return str(d.get("python") or "") if isinstance(d, dict) else ""


# ---------------------------------------------------------------------------
# 采集
# ---------------------------------------------------------------------------
def collect(ws: str | None = None) -> dict:
    t0 = time.time()
    items = []

    env, env_err = _env_report()
    if env:
        for it in env.get("items") or []:
            name = str(it.get("name") or "")
            fid, fix = _ENV_FIX.get(name, ("env.%s" % re.sub(r"[^a-z0-9]+", "_", name.lower()),
                                           {"kind": "none"}))
            group = str(it.get("group") or "其它")
            group = {"依赖": "Python 依赖"}.get(group, group)
            if group == "配置" and name == "ComfyUI 本地端口":
                group = "本机服务"
            item = {
                "id": fid,
                "group": group,
                "name": name,
                "required": bool(it.get("required")),
                "ok": bool(it.get("ok")),
                "detail": str(it.get("detail") or ""),
                "hint": str(it.get("hint") or ""),
                "source": "env_check",
            }
            item["fix"] = _fix_spec(item, fix)
            items.append(item)

    # ---- Studio 自己的运行时目录（引擎不关心，但 Studio 会写作业库/日志/凭据） ----
    for fid, label, d in (("dir.var", "运行时目录 web/var", paths.VAR_DIR),
                          ("dir.llm", "模型凭据目录 web/var/llm", paths.VAR_DIR / "llm")):
        good, detail = _writable(d)
        item = {
            "id": fid, "group": "数据目录", "name": label, "required": True,
            "ok": good, "detail": ("可写 · " + detail) if good else detail,
            "hint": "" if good else "新建该目录并给写权限（一键修复会直接创建）",
            "source": "studio",
        }
        item["fix"] = {
            "kind": "mkdir", "auto": True, "label": "创建目录",
            "cmd": "", "note": "只建 Studio 自己的运行时目录，不碰你的项目文件",
            "page": "",
        }
        items.append(item)

    # ---- 引擎解释器：配置指向不存在的文件时 engine_python() 会静默回落，用户无从发现 ----
    cfg_py = _settings_python()
    engine_py = paths.engine_python()
    bad_cfg = bool(cfg_py) and not Path(cfg_py).is_file()
    from_env = bool(os.environ.get("SOLODRAMA_PYTHON"))
    item = {
        "id": "rt.engine_py", "group": "运行时", "name": "引擎解释器",
        "required": True, "ok": not bad_cfg,
        "detail": ("正在使用 " + engine_py) if not bad_cfg
                  else "配置里写的是 %s（不存在），已静默回落到 %s" % (cfg_py, engine_py),
        "hint": "" if not bad_cfg else ("改环境变量 SOLODRAMA_PYTHON 后重开终端"
                                        if from_env else "清掉 configs/settings.json 里的 python"),
        "source": "studio",
    }
    item["fix"] = ({"kind": "none", "auto": False, "label": "",
                    "cmd": "setx SOLODRAMA_PYTHON \"\"", "note": "",
                    "page": ""} if from_env else
                   {"kind": "config", "auto": True, "label": "清掉这条失效配置",
                    "cmd": "", "note": "会先备份 configs/settings.json；清掉后回落到本机默认 venv",
                    "page": ""}) if bad_cfg else {"kind": "none", "auto": False, "label": "",
                                                  "cmd": "", "note": "", "page": ""}
    items.append(item)

    # ---- 排序：组内「需要处理的」在前 ----
    order = {g: i for i, g in enumerate(_GROUP_ORDER)}
    items.sort(key=lambda x: (order.get(x["group"], 99), x["ok"], x["name"]))

    fails = [i for i in items if not i["ok"] and i["required"]]
    warns = [i for i in items if not i["ok"] and not i["required"]]
    autos = [i for i in items if not i["ok"] and (i["fix"] or {}).get("auto")]
    return {
        "ok": not fails,
        "items": items,
        "counts": {
            "total": len(items),
            "fail": len(fails),
            "warn": len(warns),
            "auto_fixable": len(autos),
        },
        "interpreters": {"server": sys.executable, "engine": engine_py},
        "env_error": env_err,
        "platform": (env or {}).get("platform") or "",
        "checked_at": time.time(),
        "elapsed": round(time.time() - t0, 2),
    }


def _fix_spec(item: dict, fix: dict) -> dict:
    """把 env_check 的文字提示，翻成「能不能自动修 + 会执行什么」。"""
    kind = fix.get("kind") or "none"
    spec = {"kind": kind, "auto": False, "label": "", "cmd": "", "note": "", "page": ""}

    if kind == "pip":
        dist = fix.get("dist") or item["name"]
        spec_line = _pins().get(dist.lower(), dist)
        argv = [paths.engine_python(), "-m", "pip", "install",
                "--disable-pip-version-check", "--no-input", spec_line]
        spec.update({
            "auto": True, "label": "装到引擎解释器", "cmd": _fmt_cmd(argv),
            "note": "只装进 %s，不动系统 Python；装完会自动复检" % paths.engine_python(),
            "argv": argv,
        })
    elif kind == "manual":
        spec.update({"auto": False, "label": "复制命令" if item.get("hint") else "",
                     "cmd": item.get("hint") or "",
                     "note": _MANUAL_WHY.get(item.get("group") or "") or "这一项只能人工处理"})
    elif kind == "page":
        spec.update({"auto": False, "label": "去填写", "page": fix.get("page") or "",
                     "note": "Key 不走环境变量：填一次就存进连接中心，之后所有命令自动带上"})
    return spec


# ---------------------------------------------------------------------------
# 修复
# ---------------------------------------------------------------------------
def _do_mkdir(item: dict) -> dict:
    targets = [paths.VAR_DIR] if item["id"] == "dir.var" else [paths.VAR_DIR / "llm"]
    made = []
    for d in targets:
        d.mkdir(parents=True, exist_ok=True)
        made.append(str(d))
    return {"ok": True, "rc": 0, "lines": ["已创建：%s" % "、".join(made)], "cmd": ""}


def _do_config(item: dict) -> dict:
    """清掉 configs/settings.json 里指向空文件的 python 键（先备份）。"""
    cfg = paths.read_json(paths.SETTINGS_FILE, default={}) or {}
    if not isinstance(cfg, dict):
        return {"ok": False, "rc": 1, "lines": ["configs/settings.json 不是对象，拒绝改写"], "cmd": ""}
    if "python" not in cfg:
        return {"ok": True, "rc": 0, "lines": ["配置里已经没有 python 键，无需改动"], "cmd": ""}
    bak = None
    try:
        bak = paths.SETTINGS_FILE.with_suffix(".json.bak_%d" % int(time.time()))
        bak.write_text(paths.SETTINGS_FILE.read_text(encoding="utf-8"), encoding="utf-8")
    except OSError:
        bak = None
    old = cfg.pop("python", "")
    paths.write_json(paths.SETTINGS_FILE, cfg)
    return {"ok": True, "rc": 0, "cmd": "",
            "lines": ["已移除 python = %s" % old,
                      ("已备份：%s" % bak) if bak else "（原文件不存在，无需备份）"]}


def _do_pip(item: dict) -> dict:
    argv = (item.get("fix") or {}).get("argv") or []
    if not argv:
        return {"ok": False, "rc": 1, "lines": ["修复命令为空（内部错误）"], "cmd": ""}
    r = runner.run_stream(argv, timeout=300, cwd=str(paths.REPO_ROOT))
    lines = list(r["lines"])
    return {"ok": r["rc"] == 0, "rc": r["rc"], "lines": lines,
            "elapsed": r["elapsed"], "cmd": _fmt_cmd(argv)}


_FIXERS = {"mkdir": _do_mkdir, "config": _do_config, "pip": _do_pip}


def _log(rec: dict) -> None:
    try:
        paths.VAR_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8", newline="") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        # 只留最近 LOG_KEEP 行，避免无限长
        lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
        if len(lines) > LOG_KEEP:
            LOG_FILE.write_text("\n".join(lines[-LOG_KEEP:]) + "\n", encoding="utf-8", newline="")
    except OSError:
        pass


def fix(fix_id: str, ws: str | None = None) -> dict:
    """执行一个修复动作。`fix_id` 必须在**本次现算**的清单里且标了 auto。

    返回 {ok, id, cmd, rc, lines, verified, item, before}
    """
    before = collect(ws)
    item = next((i for i in before["items"] if i["id"] == fix_id), None)
    if item is None:
        return {"ok": False, "reason": "unknown_item", "id": fix_id,
                "detail": "没有这个体检项（清单是现算的，刷新后重试）"}
    fx = item.get("fix") or {}
    if not fx.get("auto"):
        return {"ok": False, "reason": "not_auto", "id": fix_id, "item": item,
                "detail": "这一项不能自动修：%s" % (fx.get("note") or item.get("hint") or "见详情"),
                "cmd": fx.get("cmd") or "", "page": fx.get("page") or ""}

    fn = _FIXERS.get(fx.get("kind") or "")
    if fn is None:
        return {"ok": False, "reason": "no_fixer", "id": fix_id, "item": item,
                "detail": "没有可执行的动作（内部错误）"}

    t0 = time.time()
    res = fn(item)
    elapsed = round(time.time() - t0, 2)

    # 复检：不看退出码，看这一项现在到底过不过
    after = collect(ws)
    now = next((i for i in after["items"] if i["id"] == fix_id), None)
    verified = bool(now and now["ok"])
    rec = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "id": fix_id, "name": item["name"],
        "kind": fx.get("kind"), "cmd": res.get("cmd") or "", "rc": res.get("rc"),
        "ok": bool(res.get("ok")), "verified": verified, "elapsed": elapsed,
    }
    _log(rec)
    return {
        "ok": bool(res.get("ok")) and verified,
        "id": fix_id, "name": item["name"], "kind": fx.get("kind"),
        "cmd": res.get("cmd") or "", "rc": res.get("rc"),
        "lines": (res.get("lines") or [])[-40:],
        "elapsed": elapsed, "verified": verified,
        "item": now, "before": item,
        "detail": "" if verified else "命令跑完了，但这一项复检仍未通过 —— 看下面的输出",
    }


def history(limit: int = 30) -> dict:
    try:
        lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    out = []
    for ln in lines[-max(1, min(int(limit or 30), 200)):]:
        try:
            out.append(json.loads(ln))
        except (json.JSONDecodeError, ValueError):
            continue
    out.reverse()
    return {"items": out, "total": len(lines)}
