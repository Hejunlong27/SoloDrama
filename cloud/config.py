"""cloud/config.py —— 云端与 ComfyUI 地址的配置解析（环境变量 > settings.json > 内置默认）

为什么要单独一层
----------------
现有引擎读的是**环境变量**（`COMFYUI_URL` / `COMFYUI_WORKFLOW` / `COMFYUI_NODE_*`），
而 `settings.example.json` 的 `comfyui` 段一直只作留档。接了云端之后，「打哪台机器」
变成一件会花钱、会跨机器的事，配置散在两个地方就一定会对不上：

    在 settings.json 里改了地址，脚本看不到（它只读环境变量）；
    在命令行设了环境变量，界面上显示的又是 settings 里的旧值。

所以这里把优先级定死成**环境变量 > settings.json > 内置默认**，并提供
`hydrate_env()` 把 settings 的值**补进**环境变量（不覆盖已有的），
让「只有一份真源」与「兼容既有读法」同时成立。

设计约束
--------
* **只读、不改盘**：`hydrate_env()` 只动 `os.environ`，不写 settings.json。
* **密钥不进来**：`XGY_TOKEN` / `XGY_SSH_PASSWORD` 永远只从环境变量读，
  `effective()` 的返回值里**不含**任何密钥字段（下游也不用担心日志泄露）。
* **零第三方依赖**：纯标准库。
"""
from __future__ import annotations

import json
import os
import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIGS_DIR = REPO_ROOT / "configs"

# 内置默认（settings.json 缺段时的兜底）。改这里 = 改所有未配置机器的行为。
DEFAULTS = {
    "comfyui": {
        "base_url": "http://127.0.0.1:8188",
        "mode": "local",                    # local | ssh_tunnel | direct
        "ssh": {"host": "", "port": 22, "user": "root", "local_port": 18188, "key_path": ""},
        # 云端镜像的域名逐条点名；不写就一个远端都出不去（守卫在 _netguard 里）
        "trusted_hosts": [],
        "timeout": {"submit": 120, "poll": 1.5, "video_min": 0},
    },
    "cloud": {
        "provider": "xiangongyun",
        "image_id": "",
        "gpu": "4090",
        "disk_gb": 100,
        "mount_cloud": True,
        "max_hours_per_day": 8,
        "auto_stop_after_idle_min": 15,
        # 单价：优先用上游每台实例返回的 price_per_hour（见 field_map）；
        # 这里只是**未取到**时的兜底。用户 2026-11-05 给定 1.59 元/时。
        "price_per_hour": 1.59,
        "api_base": "https://api.xiangongyun.com/api/",
        "token_env": "XGY_TOKEN",
        "auth_header": "Authorization",
        "auth_scheme": "Bearer",
        # 上游请求体里「实例 ID」的键名（待核对）
        "id_field": "instance_id",
        # ⚠ 端点名待核对（文档附录 C）。填相对路径，如 "instance/create"。
        "endpoints": {"create": "", "list": "", "start": "", "stop": "",
                      "destroy": "", "detail": ""},
        # 字段映射：从响应 JSON 取值的点路径（`a.b.0.c` 支持数组下标）。
        # 2026-11-05 按官方 API Playground「获取实例列表」响应的真实字段名校准；
        # 响应是否包在 `data` 层取决于网关，所以写成**候选列表**，按序尝试、命中即用。
        "field_map": {
            "id": ["data.id", "id"],
            "name": ["data.name", "name"],
            "http_url": ["data.web_url", "web_url"],
            "ssh_host": ["data.ssh_domain", "ssh_domain"],
            "ssh_port": ["data.ssh_port", "ssh_port"],
            "state": ["data.status", "status"],
            "price_per_hour": ["data.price_per_hour", "price_per_hour"],
            "retain": ["data.retain", "retain"],
            "retain_price": ["data.retain_price", "retain_price"],
        },
        "ssh": {"host": "", "port": 22, "user": "root"},
        "workspace_root": "/root/cloud",    # 实例内的工作区根（transport 用）
        "ready_timeout_min": 8,
    },
}


def settings_path() -> pathlib.Path:
    """settings.json 的位置（`SOLODRAMA_SETTINGS` 可覆盖，便于一机多环境）。"""
    env = (os.environ.get("SOLODRAMA_SETTINGS") or "").strip()
    return pathlib.Path(env).expanduser() if env else (CONFIGS_DIR / "settings.json")


def load_settings() -> dict:
    """读 settings.json；不存在或坏了都返回 {}（配置缺失不该拖垮任何只读流程）。"""
    p = settings_path()
    try:
        d = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        elif k.startswith("_") or v is None:
            continue                      # `_desc` 之类的注释键不参与合并
        else:
            out[k] = v
    return out


def _env_float(name: str):
    v = (os.environ.get(name) or "").strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _env_hosts() -> list:
    raw = (os.environ.get("SOLODRAMA_TRUSTED_HOSTS")
           or os.environ.get("DRAMA_TRUSTED_HOSTS") or "").strip()
    return [h.strip() for h in raw.split(",") if h.strip()]


def effective() -> dict:
    """合并后的有效配置（**不含密钥**）。环境变量 > settings.json > 内置默认。"""
    cfg = _merge(DEFAULTS, load_settings())

    # —— ComfyUI 地址 ——
    url = (os.environ.get("COMFYUI_URL") or os.environ.get("COMFY_URL") or "").strip()
    if url:
        cfg["comfyui"]["base_url"] = url.rstrip("/")
    elif cfg["comfyui"].get("base_url"):
        cfg["comfyui"]["base_url"] = str(cfg["comfyui"]["base_url"]).rstrip("/")

    # —— 受信域名：环境变量整段覆盖文件里的列表（不是相加）——
    # 为什么覆盖：环境变量是「这一次运行要用哪几家」，相加会让「临时放开一条」
    # 变成「永久保留上一条」，名单只会越来越宽。
    hosts = _env_hosts()
    if hosts:
        cfg["comfyui"]["trusted_hosts"] = hosts

    # —— 超时 ——
    vmin = _env_float("SOLODRAMA_VIDEO_TIMEOUT_MIN")
    if vmin and vmin > 0:
        cfg["comfyui"]["timeout"]["video_min"] = vmin

    # —— 云端 ——
    c = cfg["cloud"]
    for env, key, cast in (("SOLODRAMA_CLOUD_MAX_HOURS", "max_hours_per_day", float),
                           ("SOLODRAMA_CLOUD_PRICE_PER_HOUR", "price_per_hour", float),
                           ("SOLODRAMA_CLOUD_READY_MIN", "ready_timeout_min", float),
                           ("XGY_GPU", "gpu", str),
                           ("XGY_IMAGE_ID", "image_id", str),
                           ("XGY_API_BASE", "api_base", str)):
        raw = (os.environ.get(env) or "").strip()
        if not raw:
            continue
        try:
            c[key] = cast(raw)
        except ValueError:
            pass
    return cfg


def hydrate_env() -> dict:
    """把 settings.json 的值补进环境变量（**不覆盖**已有环境变量）。返回实际写入项。

    这一步是给「子进程」用的：`drama.py` 派生的出片脚本只认环境变量，而用户可能
    只在 settings.json 里配了地址。补进去之后父子进程看到的是同一台机器。
    """
    cfg = effective()
    applied = {}

    def _set(env: str, value: str) -> None:
        if not value or os.environ.get(env):
            return
        os.environ[env] = value
        applied[env] = value

    _set("COMFYUI_URL", cfg["comfyui"]["base_url"])
    hosts = cfg["comfyui"].get("trusted_hosts") or []
    if isinstance(hosts, str):
        hosts = [h.strip() for h in hosts.split(",") if h.strip()]
    _set("SOLODRAMA_TRUSTED_HOSTS", ",".join(str(h) for h in hosts))
    vmin = (cfg["comfyui"].get("timeout") or {}).get("video_min")
    if vmin:
        _set("SOLODRAMA_VIDEO_TIMEOUT_MIN", str(vmin))
    return applied


def token() -> str:
    """上游 API Token（只从环境变量读；调用方负责脱敏，绝不打印原值）。"""
    cfg = effective()["cloud"]
    return (os.environ.get(str(cfg.get("token_env") or "XGY_TOKEN")) or "").strip()


def mask(secret: str) -> str:
    """日志/界面里展示凭据的唯一方式：前 3 后 2，中间固定 `***`。"""
    s = str(secret or "")
    if not s:
        return "(未设置)"
    if len(s) <= 6:
        return "***"
    return s[:3] + "***" + s[-2:]
