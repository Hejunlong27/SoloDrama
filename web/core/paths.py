# -*- coding: utf-8 -*-
"""paths.py —— Web 层的路径与运行时常量（唯一真源）

设计约束：
  * 本模块只做「定位」，不做任何业务判断；
  * 工作区目录布局一律问 `stages/_layout.py`（仓库真源），本层不复刻布局逻辑。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = WEB_DIR.parent

STAGES_DIR = REPO_ROOT / "stages"
PROD_SCRIPTS = STAGES_DIR / "production" / "scripts"
CREATION_SCRIPTS = STAGES_DIR / "creation" / "scripts"
ASSETS_SCRIPTS = STAGES_DIR / "assets" / "scripts"
COMIFY_SCRIPTS = STAGES_DIR / "assets" / "comfyui"
VIDEO_SCRIPTS = STAGES_DIR / "video" / "workflow" / "scripts"
SUBTITLE_SCRIPTS = STAGES_DIR / "subtitle" / "scripts"
TOOLS_DIR = REPO_ROOT / "tools"
CONFIGS_DIR = REPO_ROOT / "configs"

VAR_DIR = WEB_DIR / "var"
LOGS_DIR = VAR_DIR / "logs"
REGISTRY_FILE = VAR_DIR / "registry.json"
JOBS_DB = VAR_DIR / "jobs.db"
SETTINGS_FILE = CONFIGS_DIR / "settings.json"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8788

_FALLBACK_PYTHON = Path.home() / ".workbuddy" / "binaries" / "python" / "envs" / "default" / "Scripts" / "python.exe"


def ensure_var_dirs() -> None:
    """运行时目录（作业库 / 日志）—— 位于仓库内 web/var/，已在 .gitignore 中排除。"""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)


def _settings() -> dict:
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8-sig")) or {}
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def engine_python() -> str:
    """执行引擎脚本用的解释器（需带 httpx / Pillow）。

    优先级：环境变量 SOLODRAMA_PYTHON → configs/settings.json 的 python →
    本机默认 venv → 当前解释器（并给出告警）。
    """
    cand = os.environ.get("SOLODRAMA_PYTHON") or ""
    if not cand:
        cand = str(_settings().get("python") or "")
    if cand and Path(cand).is_file():
        return cand
    if _FALLBACK_PYTHON.is_file():
        return str(_FALLBACK_PYTHON)
    return sys.executable


def ensure_layout_importable():
    """把仓库 `stages/` 加进 sys.path 并返回 `_layout` 模块（失败返回 None）。

    ★ 为什么不自己实现一遍布局解析：`stages/_layout.py` 是工作区目录的唯一真源，
      本仓库已存在「subtitle / upscale / tools.cli 三处轻量复刻」的历史包袱，
      Web 层再复刻一份就会变成第四处。
    """
    s = str(STAGES_DIR)
    if s not in sys.path:
        sys.path.insert(0, s)
    try:
        import _layout  # noqa: PLC0415
        return _layout
    except Exception:  # noqa: BLE001
        return None


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, ValueError):
        return default


def write_json(path, data) -> None:
    """统一以 UTF-8 / LF 写盘（Windows 上 write_text 默认会写 CRLF，必须显式指定）。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
