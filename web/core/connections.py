# -*- coding: utf-8 -*-
"""连接中心 —— 三类外部通道的配置、注入与探测（产品层唯一真源）。

为什么要这一层
--------------
引擎脚本各自认环境变量（`COMFYUI_URL` / `RUNNINGHUB_API_KEY` / `RUNNINGHUB_BASE_URL`），
用户在界面上根本看不到它们；不设就得到「连不上 ComfyUI」「未设置 RUNNINGHUB_API_KEY」，
看起来像产品坏了。这里把「连接」变成一个可以配置、可以验证、可以解释的对象：

* 存：`web/var/connections.json`（非密钥）+ `web/var/connections.keys.json`（密钥，0600）
  `web/var/` 已在 .gitignore；**响应体永远不含明文**，只给 `hint`（长度 + 末 4 位）。
* 注：`runner.base_env()` 每次把连接值合并进子进程环境，用户不需要设任何环境变量。
* 测：全部是只读探测，0 费用、不产生作业。

与「密钥不落盘」纪律的关系：该纪律约束的是仓库与日志（不进 git、不进日志、不进 prompt）。
本地运行态需要持久化，落 gitignored 的 `web/var/` 是等价实现；仍然禁止写进任何会被提交
或被注入上下文的文件。
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

VAR_DIR = Path(__file__).resolve().parent.parent / "var"
CFG_PATH = VAR_DIR / "connections.json"
KEY_PATH = VAR_DIR / "connections.keys.json"

KINDS = ("llm", "comfyui", "runninghub")

LABELS = {
    "llm": "大模型",
    "comfyui": "本地出图（ComfyUI）",
    "runninghub": "云端出片（RunningHub）",
}

DEFAULTS: dict[str, dict] = {
    "llm": {},
    # autostart：出图前发现 8188 没服务时，由 Studio 起一个 headless 实例
    # （真源 `stages/assets/comfyui/comfy_boot.py`）。默认开 —— 关掉它等于把
    # 「先点开桌面版」这道手工步骤还回去。
    # launch：手动指定安装（python + main_py）。留空则自动读 ComfyUI Desktop 的
    # installations.json，换机器、换实例都不用改代码。
    "comfyui": {"base_url": "http://127.0.0.1:8188", "autostart": True, "launch": {}},
    "runninghub": {"base_url": "https://www.runninghub.ai", "kind": "workflow",
                   "workflow_id": "", "ai_app_id": ""},
}

# 站点只认 .ai / .cn —— 引擎侧同样校验，这里提前拦住，避免「Key 明明对却 401」
RH_SITES = ("runninghub.ai", "runninghub.cn")

PROBE_TIMEOUT = 5.0


# ---------------------------------------------------------------------------
# 存储
# ---------------------------------------------------------------------------
def _ensure() -> None:
    VAR_DIR.mkdir(parents=True, exist_ok=True)


def _read(path: Path, default):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _write(path: Path, data) -> None:
    _ensure()
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    try:                       # POSIX 下有意义；Windows 上是 no-op，不必特判
        os.chmod(path, 0o600)
    except OSError:
        pass


def load() -> dict:
    """读出配置（已合并默认值，**不含密钥**）。"""
    raw = _read(CFG_PATH, {})
    out: dict[str, dict] = {}
    for k in KINDS:
        base = dict(DEFAULTS.get(k) or {})
        cur = raw.get(k) if isinstance(raw.get(k), dict) else {}
        base.update({kk: vv for kk, vv in cur.items() if kk != "api_key"})
        out[k] = base
    return out


def _invalidate(cfg: dict, kind: str) -> None:
    """配置一改，旧探测结果就作废。

    为什么必须作废：用户把地址从 8188 改成 9000，界面还挂着「已连接（2 分钟前）」，
    他会相信一个已经不存在的状态。宁可回到「待验证」。
    """
    cur = cfg.get(kind)
    if isinstance(cur, dict):
        for k in ("last_ok", "last_detail", "last_next", "last_test"):
            cur.pop(k, None)


def save(patch: dict) -> dict:
    """合并保存（只允许已知键；密钥单独落盘）。改了就作废旧探测结果。"""
    cfg = load()
    for k in KINDS:
        cur = patch.get(k)
        if not isinstance(cur, dict):
            continue
        changed = False
        for kk, vv in cur.items():
            if kk in ("api_key", "key", "apiKey"):
                continue
            if kk in DEFAULTS.get(k, {}) or kk in ("model", "note", "label"):
                # `autostart` 是策略开关，不影响「现在连不连得上」。
                # 勾一下就把「已连接」打回「待验证」，会让用户以为服务掉了。
                if cfg[k].get(kk) != vv and kk != "autostart":
                    changed = True
                cfg[k][kk] = vv
        if changed:
            _invalidate(cfg, k)
    _write(CFG_PATH, cfg)
    return cfg


def _keys() -> dict:
    d = _read(KEY_PATH, {})
    return d if isinstance(d, dict) else {}


def set_key(kind: str, key: str | None) -> None:
    d = _keys()
    if key in (None, ""):
        d.pop(kind, None)
    else:
        d[kind] = str(key).strip()
    _write(KEY_PATH, d)
    try:                       # 换 Key / 清 Key 同样让旧结论失效
        cfg = load()
        _invalidate(cfg, kind)
        _write(CFG_PATH, cfg)
    except Exception:          # noqa: BLE001
        pass


ENV_NAMES = {"runninghub": "RUNNINGHUB_API_KEY", "llm": "", "comfyui": ""}


def _reg_get(name: str) -> str:
    """读 HKCU\\Environment（用户级环境变量）——与引擎 `hydrate_env()` 同一个来源。

    为什么要有这一步：用户可能早就在系统里配好了 Key（`setx`），产品却显示「没填」，
    于是用户以为坏了。**界面必须反映真实可用的凭据**，所以三个来源都要看。
    """
    try:
        import winreg
    except ImportError:
        return ""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            val, _ = winreg.QueryValueEx(k, name)
            return str(val or "")
    except (OSError, FileNotFoundError):
        return ""


def resolve_key(kind: str) -> tuple[str, str]:
    """按「产品内配置 > 进程环境 > 用户级环境变量」解析，返回 (key, 来源)。"""
    if kind == "comfyui":
        return "", ""
    v = str(_keys().get(kind) or "").strip()
    if v:
        return v, "file"
    name = ENV_NAMES.get(kind) or ""
    if not name:
        return "", ""
    v = str(os.environ.get(name) or "").strip()
    if v:
        return v, "env"
    v = _reg_get(name).strip()
    if v:
        return v, "registry"
    return "", ""


def get_key(kind: str) -> str:
    return resolve_key(kind)[0]


def hint(key: str) -> str:
    """只回指纹：长度 + 末 4 位。短 Key 连末 4 位也不给，避免等于回显。"""
    k = str(key or "")
    if not k:
        return ""
    if len(k) <= 8:
        return "已保存（%d 位）" % len(k)
    return "%s…%s（%d 位）" % (k[:3], k[-4:], len(k))


# ---------------------------------------------------------------------------
# 注入
# ---------------------------------------------------------------------------
def env_for() -> dict:
    """给子进程的环境变量。空值不注入，避免把默认值覆盖成空串。"""
    cfg = load()
    out: dict[str, str] = {}
    comfy_cfg = cfg.get("comfyui", {}) or {}
    comfy = (comfy_cfg.get("base_url") or "").strip()
    if comfy:
        out["COMFYUI_URL"] = comfy
    # 自动启动开关也要下发：CLI / agent 直接跑出图脚本时，判断依据必须和界面一致，
    # 否则「界面关掉了自动启动，命令行却照旧拉起一个实例」——两套口径，用户没法解释。
    out["SOLODRAMA_COMFY_AUTOSTART"] = "0" if comfy_cfg.get("autostart") is False else "1"
    rh = cfg.get("runninghub", {}) or {}
    key = get_key("runninghub").strip()
    if key:
        out["RUNNINGHUB_API_KEY"] = key
    base = (rh.get("base_url") or "").strip()
    if base:
        out["RUNNINGHUB_BASE_URL"] = base
    return out


# ---------------------------------------------------------------------------
# 探测
# ---------------------------------------------------------------------------
def _now() -> float:
    return time.time()


def _note_test(kind: str, ok: bool, detail: str, nxt: str = "") -> None:
    """把「最近一次探测」写进非密钥配置，供界面显示时间戳（失败不抛）。

    连 `next` 一起存：刷新页面后，用户仍然能看到「下一步该干什么」，而不是只剩一个红点。
    """
    try:
        cfg = load()
        cur = cfg.setdefault(kind, {})
        cur["last_test"] = _now()
        cur["last_ok"] = bool(ok)
        cur["last_detail"] = str(detail or "")[:200]
        cur["last_next"] = str(nxt or "")[:300]
        _write(CFG_PATH, cfg)
    except Exception:      # noqa: BLE001
        pass


def _json_get(url: str, timeout: float = PROBE_TIMEOUT) -> tuple[int, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        try:
            return resp.status, json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            return resp.status, raw[:400].decode("utf-8", "replace")


def _json_post(url: str, body: dict, timeout: float = PROBE_TIMEOUT) -> tuple[int, Any]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        try:
            return resp.status, json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            return resp.status, raw[:400].decode("utf-8", "replace")


def _gpu_of(payload: dict) -> dict:
    dev = (payload.get("devices") or [{}])[0] if isinstance(payload, dict) else {}
    sysd = (payload.get("system") or {}) if isinstance(payload, dict) else {}
    ver = (sysd.get("comfyui_version") or payload.get("comfyui_version")
           or (payload.get("system") or {}).get("version") or "")
    vtotal = dev.get("vram_total") or 0
    vfree = dev.get("vram_free") or 0
    return {
        "version": str(ver or ""),
        "device": str(dev.get("name") or ""),
        "vram_total_gb": round(float(vtotal) / (1024 ** 3), 1) if vtotal else 0,
        "vram_free_gb": round(float(vfree) / (1024 ** 3), 1) if vfree else 0,
        "python": str(sysd.get("python_version") or ""),
    }


def _test_comfyui() -> dict:
    cfg = load()["comfyui"]
    base = (cfg.get("base_url") or "").strip().rstrip("/")
    if not base:
        return {"ok": False, "reason": "no_url",
                "detail": "还没填 ComfyUI 地址", "next": "默认是 http://127.0.0.1:8188"}
    if not base.startswith(("http://", "https://")):
        base = "http://" + base
    try:
        status, payload = _json_get(base + "/system_stats")
    except urllib.error.HTTPError as e:
        return {"ok": False, "reason": "http_%s" % e.code,
                "detail": "地址有响应但不是 ComfyUI（HTTP %s）" % e.code,
                "next": "确认端口是 ComfyUI 的（默认 8188），而不是别的服务"}
    except urllib.error.URLError as e:
        msg = str(getattr(e, "reason", e))
        refused = "refused" in msg.lower() or "10061" in msg
        loopback = _is_loopback(base)
        nxt = ("ComfyUI 没启动：出图时会自动拉起一个后台实例（也可以在连接中心点「启动」）"
               if (refused and loopback) else
               ("检查地址/端口/防火墙；远程机器要允许 8188 入站" if not loopback else
                "确认地址/端口；本机 8188 被别的程序占用时换一个端口"))
        return {"ok": False, "reason": "refused" if refused else "unreachable",
                "detail": "连不上 %s（%s）" % (base, msg[:120]),
                "next": nxt, "can_start": bool(refused and loopback)}
    except (TimeoutError, OSError) as e:
        return {"ok": False, "reason": "timeout", "detail": "5 秒内没有响应（%s）" % type(e).__name__,
                "next": "ComfyUI 可能在启动中，或负载过高；稍后重试"}
    if not isinstance(payload, dict) or "system" not in payload:
        return {"ok": False, "reason": "not_comfyui",
                "detail": "返回的不是 ComfyUI 的 system_stats", "next": "确认地址指向 ComfyUI 根路径"}
    info = _gpu_of(payload)
    bits = [b for b in (info.get("version") and "v" + info["version"], info.get("device")) if b]
    if info.get("vram_free_gb"):
        bits.append("空闲 %.1fG / %.1fG" % (info["vram_free_gb"], info.get("vram_total_gb") or 0))
    return {"ok": True, "reason": "ok", "detail": "ComfyUI 在线" + (" · " + " · ".join(bits) if bits else ""),
            "comfyui": dict(info, base_url=base),
            "next": ""}


def _is_loopback(base: str) -> bool:
    """本机地址才允许自动启动实例（远程地址只探测）。"""
    try:
        host = (urllib.parse.urlparse(base if "://" in base else "http://" + base).hostname or "").lower()
    except ValueError:
        return False
    return host in ("127.0.0.1", "localhost", "::1", "0.0.0.0")


def _rh_site_ok(base: str) -> bool:
    try:
        host = (urllib.parse.urlparse(base).hostname or "").lower()
    except ValueError:
        return False
    return any(host == s or host.endswith("." + s) for s in RH_SITES)


def _test_runninghub() -> dict:
    cfg = load()["runninghub"]
    base = (cfg.get("base_url") or "").strip().rstrip("/")
    key = get_key("runninghub").strip()
    if not base:
        return {"ok": False, "reason": "no_url", "detail": "还没填 RunningHub 站点",
                "next": "国内填 https://www.runninghub.cn，海外填 https://www.runninghub.ai"}
    if not _rh_site_ok(base):
        return {"ok": False, "reason": "bad_site",
                "detail": "站点只支持 runninghub.ai / runninghub.cn",
                "next": "把地址改成 https://www.runninghub.ai 或 https://www.runninghub.cn"}
    if not key:
        return {"ok": False, "reason": "no_key", "detail": "还没填 API Key",
                "next": "RunningHub 控制台 → 个人中心 → API（Key 只存本机，不会回显）"}

    # 第一步：验证 Key 本身（只读，0 费用）。这一步不需要工作流 ID —— 否则用户会被
    # 「必须先填 ID 才能测 Key」卡住，而他只是想知道 Key 对不对。
    try:
        status, payload = _json_post(base + "/uc/openapi/accountStatus", {"apikey": key})
    except urllib.error.HTTPError as e:
        return _rh_http_error(e)
    except urllib.error.URLError as e:
        return {"ok": False, "reason": "unreachable", "detail": "连不上站点（%s）" % str(e.reason)[:120],
                "next": "检查网络或代理；站点选错也会连不上"}
    except (TimeoutError, OSError):
        return {"ok": False, "reason": "timeout", "detail": "5 秒内没有响应", "next": "稍后重试"}
    if not isinstance(payload, dict):
        return {"ok": False, "reason": "not_json", "detail": "账户接口返回的不是 JSON",
                "next": "站点地址可能不对（应指向 RunningHub 根路径）"}
    if payload.get("code") not in (0, "0", None, ""):
        msg = payload.get("msg") or payload.get("message") or ""
        return {"ok": False, "reason": "bad_key",
                "detail": "Key 无效或站点不匹配：%s" % str(msg)[:140],
                "next": "确认 Key 与站点同属一个区（.ai 的 Key 不能用在 .cn）；重新复制一遍"}

    d = payload.get("data") or {}
    acct = {
        "coins": d.get("remainCoins"),
        "cash": d.get("remainMoney"),
        "currency": d.get("currency") or "",
        "running": d.get("currentTaskCounts"),
        "base_url": base,
    }

    # 第二步：如果填了工作流/AI 应用，顺便确认它在这个账号下可读（仍然 0 费用）。
    kind = (cfg.get("kind") or "workflow").strip().lower()
    target = str(cfg.get("ai_app_id") if kind in ("ai-app", "ai_app", "app", "webapp")
                 else cfg.get("workflow_id") or "").strip()
    target_info = {"checked": False, "ok": None, "detail": ""}
    if target:
        got = _rh_target_probe(base, key, kind, target)
        target_info = dict(got, checked=True)

    ok = target_info["ok"] is not False
    detail = "已连接 · 余额 %s RH币" % (acct.get("coins") if acct.get("coins") is not None else "?")
    if acct.get("running") not in (None, 0, "0"):
        detail += " · %s 个任务在跑" % acct.get("running")
    if target_info["checked"]:
        detail += " · 目标%s" % ("可读" if target_info["ok"] else "不可读")
    return {"ok": ok, "reason": "ok" if ok else "target_bad", "detail": detail,
            "runninghub": dict(acct, target=target_info),
            "next": "" if ok else "工作流 ID 可能不属于这个账号，或已被删除"}


def _rh_target_probe(base: str, key: str, kind: str, target: str) -> dict:
    try:
        if kind in ("ai-app", "ai_app", "app", "webapp"):
            url = "%s/api/webapp/apiCallDemo?apiKey=%s&webappId=%s" % (
                base, urllib.parse.quote(key), urllib.parse.quote(target))
            _, payload = _json_get(url)
        else:
            _, payload = _json_post(base + "/api/openapi/getJsonApiFormat",
                                    {"apiKey": key, "workflowId": target})
    except Exception as e:      # noqa: BLE001
        return {"ok": False, "detail": "%s: %s" % (type(e).__name__, str(e)[:100])}
    if not isinstance(payload, dict):
        return {"ok": False, "detail": "目标接口返回非 JSON"}
    if payload.get("code") not in (0, "0", None, ""):
        msg = payload.get("msg") or payload.get("message") or ""
        return {"ok": False, "detail": str(msg)[:140]}
    data = payload.get("data") or {}
    n = len(data.get("nodeInfoList") or []) if isinstance(data, dict) else 0
    return {"ok": True, "detail": "%s 个可编辑输入" % n}


def _rh_http_error(e: urllib.error.HTTPError) -> dict:
    if e.code in (401, 403):
        return {"ok": False, "reason": "bad_key",
                "detail": "Key 无效或没有权限（HTTP %s）" % e.code,
                "next": "重新复制 API Key；确认站点与 Key 所属站点一致（.ai 的 Key 不能用在 .cn）"}
    return {"ok": False, "reason": "http_%s" % e.code,
            "detail": "站点返回 HTTP %s" % e.code, "next": "稍后重试或检查站点地址"}


def _rh_verdict(payload: Any, what: str) -> dict:
    if not isinstance(payload, dict):
        return {"ok": False, "reason": "not_json", "detail": "返回的不是 JSON",
                "next": "站点地址可能不对（应指向 RunningHub 根路径）"}
    code = payload.get("code")
    if code in (0, "0", None, ""):
        data = payload.get("data") or {}
        n = len((data.get("nodeInfoList") or []) if isinstance(data, dict) else []) or \
            len((data.get("prompt") or {})) if isinstance(data, dict) else 0
        return {"ok": True, "reason": "ok", "detail": "Key 有效，%s 可读（%s 个可编辑输入）" % (what, n or "?"),
                "next": ""}
    msg = payload.get("msg") or payload.get("message") or payload.get("error") or ""
    return {"ok": False, "reason": "biz_error", "detail": "%s 读取失败：%s" % (what, str(msg)[:160]),
            "next": "确认工作流 ID 属于这个账号；或到 RunningHub 网页打开该工作流确认它还在"}


# 探测只发一句 1 token 的话。它是**连通性体检**，不是内容生成：
# 内容一律走 gateway.complete(purpose) + stages/creation/prompts/*.md 原文，
# 这里不绕开网关做创作，只验证「地址 + Key + 模型名 + 网络」四件事能不能通。
_LLM_PROBE_MSG = [{"role": "user", "content": "只回复：可用"}]
_LLM_PROBE_TIMEOUT = 20.0
_LLM_PROBE_MAX = 2          # 最多实测两个提供商：多测一个就多一次计费
# ★ 额度不能太小：DeepSeek flash / v4-pro 这类**推理模型**会把思考也算进 max_tokens，
#   给 8 个 token 时思考就吃光了，回包 content 为空。探针要的是「能不能调通」，
#   64 个 token 足够它想完并吐一句「可用」，成本仍可忽略。
_LLM_PROBE_TOKENS = 64

_LLM_NEXT = {
    "auth": "Key 无效或已过期：回控制台重新复制一次（不同站点/平台之间的 Key 不通用）",
    "model_not_found": "模型名不被这个 Key 接受：核对默认模型；base_url 少了 /v1 也会这样",
    "quota": "账户余额或额度不足，充值后再点测试",
    "rate_limit": "被限流了，等一分钟再点测试",
    "timeout": "超时：多为网络或代理问题；本地服务请确认端口已监听",
    "network": "连不上端点：检查 base_url 是否要带 /v1、以及本机网络/代理",
    "protocol": "端点不像 OpenAI 兼容接口：地址应指向 /v1，而不是控制台首页",
    "blocked": "地址被本地安全策略拒绝（只允许 http/https 与常见端口）",
    "config": "提供商配置不完整：补上 base_url 与默认模型",
    # 推理模型（DeepSeek flash / v4-pro 等）最常见的两种「HTTP 200 但没内容」
    "truncated": "额度给了但被思考吃光：把该用途的 max_tokens 调大（探针本身用 64 tokens 就够）",
    "empty": "回包为空：确认模型名可用；若提示被拦截，换个说法或换模型",
}


def _test_llm() -> dict:
    """大模型通道体检：**真的发一次最小请求**。

    为什么不能只看「有没有 Key」：Key 过期、模型改名、base_url 少了 /v1、
    代理把请求拦下来，这四种情况的配置看起来都是「齐了」，但一用就失败。
    产品必须能区分「配置齐了」和「真的能调」，否则用户会在写剧本时才发现。
    """
    try:
        from .llm import providers as llm_providers
        from .llm import store as llm_store
        from .llm.errors import LLMError
    except Exception as e:      # noqa: BLE001
        return {"ok": False, "reason": "import", "detail": "读不到模型配置（%s）" % type(e).__name__,
                "next": "到 AI 模型中心检查提供商配置"}

    allprovs = llm_store.list_providers() or []
    provs = [x for x in allprovs if x.get("enabled", True)]
    if not allprovs:
        return {"ok": False, "reason": "no_provider", "detail": "还没添加任何模型提供商",
                "next": "到 AI 模型中心添加一个 OpenAI 兼容服务（DeepSeek / 通义 / 本地 Ollama 都行）"}
    if not provs:
        return {"ok": False, "reason": "all_disabled",
                "detail": "有 %d 个提供商，但都处于停用状态" % len(allprovs),
                "next": "到 AI 模型中心启用其中一个，或新建一个"}

    ready = [x for x in provs if _prov_has_key(x)]
    if not ready:
        no_key = [x.get("name") or x.get("id") for x in provs]
        return {"ok": False, "reason": "no_key",
                "detail": "%d 个提供商都没有可用 Key（%s）" % (len(provs), "、".join(no_key[:3])),
                "next": "在 AI 模型中心填入 Key（只进不出、不回显），再点一次测试"}

    # ★ 真实通道优先排队：探针有名额（_LLM_PROBE_MAX），名额不能被 Mock 占掉。
    #   否则「配了云端 Key 但界面上写 Mock 可调用」，看起来就像没接通。
    def _rank(p):
        if (p.get("kind") or "") == "mock":
            return 2
        return 1 if p.get("local") else 0
    ready.sort(key=_rank)

    probes = []
    for x in ready[:_LLM_PROBE_MAX]:
        pid = x.get("id")
        name = x.get("name") or pid
        try:
            cfg = llm_store.get_provider(pid, with_key=True)
        except Exception as e:      # noqa: BLE001
            probes.append({"id": pid, "name": name, "ok": False, "kind": "config",
                           "provider_kind": x.get("kind"),
                           "detail": "读不到该提供商的完整配置（%s）" % type(e).__name__,
                           "next": _LLM_NEXT["config"]})
            continue
        model = str(cfg.get("default_model") or "")
        started = time.time()
        try:
            prov = llm_providers.build(cfg, cfg.get("_key") or "")
            res = prov.chat(_LLM_PROBE_MSG, model=model or None, max_tokens=_LLM_PROBE_TOKENS,
                            timeout_s=_LLM_PROBE_TIMEOUT)
        except LLMError as e:
            probes.append({"id": pid, "name": name, "model": model or "(未填)",
                           "ok": False, "kind": e.kind, "status": e.status,
                           "provider_kind": x.get("kind"),
                           "detail": e.text, "next": _LLM_NEXT.get(e.kind, "按提示修正后重试"),
                           "ms": int((time.time() - started) * 1000)})
            continue
        except Exception as e:      # noqa: BLE001
            probes.append({"id": pid, "name": name, "model": model or "(未填)",
                           "ok": False, "kind": "exception", "provider_kind": x.get("kind"),
                           "detail": "%s: %s" % (type(e).__name__, str(e)[:120]),
                           "next": "把这段原文发给开发者", "ms": int((time.time() - started) * 1000)})
            continue
        got = str(getattr(res, "text", "") or "").strip()
        toks = (getattr(res, "usage", None) or {}).get("total_tokens")
        probes.append({"id": pid, "name": name, "model": model or "(未填)", "ok": True,
                       "provider_kind": x.get("kind"),
                       "detail": ("可调用（回包「%s」）" % got[:16] if got
                                  else "可调用，但回包为空（已用 %s tokens）" % (toks or "?")),
                       "ms": int((time.time() - started) * 1000)})

    good = [x for x in probes if x["ok"]]
    if good:
        # ★ 头条只认真实通道：Mock 永远能用，把它写在标题里等于告诉用户「还是没接通」。
        headline = ([x for x in good if (x.get("provider_kind") or "") != "mock"] or good)[0]
        bad = [x for x in probes if not x["ok"]]
        tail_txt = ""
        if bad:
            tail_txt = "；%s 不可用：%s" % (bad[0].get("name"), bad[0].get("detail"))
        skipped = len(ready) - len(probes)
        if skipped > 0:
            tail_txt += "；另有 %d 个提供商本次未测（每次最多测 %d 个，避开重复计费）" % (skipped, _LLM_PROBE_MAX)
        return {"ok": True, "reason": "ok",
                "detail": "%s 可调用 · 实测 %d/%d%s" % (headline.get("name"), len(good), len(probes), tail_txt),
                "providers": probes, "next": (bad[0].get("next") or "") if bad else ""}

    first = probes[0] if probes else {}
    return {"ok": False, "reason": first.get("kind") or "probe_failed",
            "detail": "%s：%s" % (first.get("name") or "提供商", first.get("detail") or "实测失败"),
            "next": first.get("next") or "按提示修正后重试",
            "providers": probes}


TESTERS = {"comfyui": _test_comfyui, "runninghub": _test_runninghub, "llm": _test_llm}


def test(kind: str) -> dict:
    kind = str(kind or "").strip().lower()
    fn = TESTERS.get(kind)
    if fn is None:
        return {"ok": False, "reason": "unknown_kind", "detail": "未知通道：%s" % kind}
    try:
        res = fn()
    except Exception as e:      # noqa: BLE001
        res = {"ok": False, "reason": "exception",
               "detail": "%s: %s" % (type(e).__name__, str(e)[:160]),
               "next": "把这段原文发给开发者；同时可在终端手工验证一次"}
    res["kind"] = kind
    res["checked_at"] = _now()
    _note_test(kind, bool(res.get("ok")), res.get("detail") or "", res.get("next") or "")
    return res


# ---------------------------------------------------------------------------
# 聚合
# ---------------------------------------------------------------------------
def overview() -> dict:
    cfg = load()
    items = []
    for kind in KINDS:
        c = dict(cfg.get(kind) or {})
        k, src = resolve_key(kind)
        items.append({
            "kind": kind,
            "label": LABELS[kind],
            "fields": c,
            "has_key": bool(k),
            "key_source": src,
            "key_hint": hint(k or ""),
            "last_test": c.get("last_test") or 0,
            "last_ok": c.get("last_ok"),
            "last_detail": c.get("last_detail") or "",
            "last_next": c.get("last_next") or "",
            "doc": _DOC.get(kind, ""),
            "providers": _llm_providers() if kind == "llm" else None,
        })
    return {
        "ok": True,
        "items": items,
        "env": sorted(env_for().keys()),
        "store": str(CFG_PATH),
        "note": "连接是机器级配置：同一台机器上的所有项目共用。Key 只存本机，接口不回显明文。",
    }


def _prov_has_key(p: dict) -> bool:
    """提供商有没有可用凭据。

    ⚠️ 坑：`store.public_provider()` 会 `out.update(key_status(prov))`，也就是把
    `{"has_key": ...}` **摊平**到顶层，而不是留在 `key_status` 里。读
    `p["key_status"]["has_key"]` 恒为 None → 界面永远显示「缺 Key」，
    用户填了 Key 也被告知没填。这里两种形态都兼容。
    """
    # 顺序要紧：本地/演练类别**根本不需要 Key**，必须先判，
    # 否则会被顶层 has_key=False 一票否决（表现为「mock 也说没 Key」）。
    if (p.get("kind") or p.get("type")) in ("ollama", "mock"):
        return True
    ks = p.get("key_status")
    if isinstance(ks, dict) and "has_key" in ks:
        return bool(ks.get("has_key"))
    return bool(p.get("has_key"))


def _llm_providers() -> list:
    """给界面看的最小集合：谁配了、什么模型、有没有 Key。读不到就空列表，不抛。"""
    try:
        from .llm import store as llm_store
        return [{"id": p.get("id"), "name": p.get("name") or p.get("id"),
                 "model": p.get("default_model") or "",
                 "kind": p.get("kind"), "has_key": _prov_has_key(p),
                 "enabled": p.get("enabled", True)}
                for p in (llm_store.list_providers() or [])]
    except Exception:      # noqa: BLE001
        return []


_DOC = {
    "llm": "用途路由在「AI 模型中心」——同一个模型可以只负责剧本，另一个只负责分镜。",
    "comfyui": "本地出图 ￥0，只占 GPU。地址默认 http://127.0.0.1:8188；"
               "没启动时 Studio 会自动拉起一个后台实例（约 30–90 秒），不需要先开桌面版。",
    "runninghub": "云端出片按次计费（27 币/段 + 1 币/秒）。这里只做只读验证，不产生任务。",
}
