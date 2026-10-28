# -*- coding: utf-8 -*-
"""LLM 配置与用量存储

落盘位置（都在 `web/var/llm/`，已在 .gitignore 覆盖范围 `web/var/` 内）：
  config.json   —— 提供商配置 + 用途路由（**不含任何明文 Key**）
  keys.json     —— 密钥保险箱（仅当用户选择「保存到本机」时写入；尽力设 0600）
  usage.jsonl   —— 每次调用的用量与结果（**不含提示词正文与返回正文**，只记哈希与长度）

为什么 Key 分文件：把 config.json 交给前端/写进日志/贴进 issue 都不会带出密钥。
读取顺序：`env_var` 指定的环境变量 → keys.json 里的本机保存值。
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

from .. import paths
from . import safety, templates
from .errors import LLMError

# 新增配置：SOLODRAMA_LLM_DIR（默认 <repo>/web/var/llm）——测试与多实例隔离用
LLM_DIR = Path(os.environ.get("SOLODRAMA_LLM_DIR") or (paths.VAR_DIR / "llm"))
CONFIG_FILE = LLM_DIR / "config.json"
KEYS_FILE = LLM_DIR / "keys.json"
USAGE_FILE = LLM_DIR / "usage.jsonl"


def use_dir(path) -> None:
    """切换存储根目录（测试隔离用；生产不改）。"""
    global LLM_DIR, CONFIG_FILE, KEYS_FILE, USAGE_FILE
    LLM_DIR = Path(path)
    CONFIG_FILE = LLM_DIR / "config.json"
    KEYS_FILE = LLM_DIR / "keys.json"
    USAGE_FILE = LLM_DIR / "usage.jsonl"

_LOCK = threading.RLock()

# 能力词表（前端下拉与网关校验共用）
CAPABILITIES = {
    "json": "JSON 输出模式（response_format / format=json）",
    "tools": "函数调用",
    "stream": "流式输出",
    "vision": "图片输入",
}

KINDS = {
    "openai": "OpenAI 兼容（/chat/completions）",
    "ollama": "本地 Ollama（/api/chat）",
    # 离线演练：不发任何网络请求，只用来验证「配置 → 测试 → 生成 → 校验 → 草稿 → 落盘」整条链路。
    # 它的输出会被标记 simulated，界面与用量都会显示「演练」，且默认不允许写入正式剧本。
    "mock": "离线演练（Mock，不调用任何模型，0 费用）",
}

# 快速新建用的预置（只是**表单初值**，不会自动落盘成「已配置」）
PRESETS = [
    {
        "id": "preset-openai", "name": "OpenAI 兼容", "kind": "openai",
        "base_url": "https://api.openai.com/v1", "default_model": "gpt-4o-mini",
        "models": ["gpt-4o-mini"], "capabilities": ["json"], "local": False,
        "env_var": "OPENAI_API_KEY", "note": "任何兼容 /chat/completions 的服务都可用同一形态",
    },
    {
        "id": "preset-deepseek", "name": "DeepSeek", "kind": "openai",
        "base_url": "https://api.deepseek.com/v1", "default_model": "deepseek-chat",
        "models": ["deepseek-chat"], "capabilities": ["json"], "local": False,
        "env_var": "DEEPSEEK_API_KEY", "note": "OpenAI 兼容通道",
    },
    {
        "id": "preset-mock", "name": "离线演练（Mock）", "kind": "mock",
        "base_url": "mock://local", "default_model": "mock-episode",
        "models": ["mock-episode"], "capabilities": ["json"], "local": True,
        "env_var": "", "note": "不联网、不计费；用于在没有凭据时验证整条创作链路",
    },
    {
        "id": "preset-ollama", "name": "本地 Ollama", "kind": "ollama",
        "base_url": "http://127.0.0.1:11434", "default_model": "qwen2.5:7b",
        "models": ["qwen2.5:7b"], "capabilities": ["json"], "local": True,
        "env_var": "", "note": "本地服务，不需要云端 Key；数据不出局域网",
    },
]


# ---------------------------------------------------------------------------
# 基础读写
# ---------------------------------------------------------------------------
def _ensure() -> None:
    LLM_DIR.mkdir(parents=True, exist_ok=True)


def _read(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, ValueError):
        return default


def _write(path, data) -> None:
    """原子写：先写临时文件再 replace，避免半截文件把配置打坏。"""
    _ensure()
    p = Path(path)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, p)


def default_config() -> dict:
    return {
        "version": 1,
        "providers": [],
        "purposes": {},           # purpose_id -> {provider_id, model, temperature, max_tokens}
        "created_at": time.time(),
    }


def load_config() -> dict:
    cfg = _read(CONFIG_FILE, None)
    if not isinstance(cfg, dict) or "providers" not in cfg:
        return default_config()
    cfg.setdefault("purposes", {})
    return cfg


def save_config(cfg: dict) -> None:
    with _LOCK:
        _write(CONFIG_FILE, cfg)


def _keys() -> dict:
    d = _read(KEYS_FILE, {})
    return d if isinstance(d, dict) else {}


def _save_keys(d: dict) -> None:
    _write(KEYS_FILE, d)
    try:  # 尽力收紧权限（Windows 上 chmod 语义有限，失败不影响功能）
        os.chmod(KEYS_FILE, 0o600)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Key 管理
# ---------------------------------------------------------------------------
def resolve_key(prov: dict) -> str:
    """取密钥：环境变量优先（推荐），其次本机保险箱。"""
    env = str(prov.get("env_var") or "").strip()
    if env:
        val = os.environ.get(env, "")
        if val:
            return val.strip()
    return str(_keys().get(prov.get("id")) or "")


def key_status(prov: dict) -> dict:
    """对外只给「有没有」「从哪来」「打码后是什么」。"""
    env = str(prov.get("env_var") or "").strip()
    from_env = bool(env and os.environ.get(env))
    key = resolve_key(prov)
    src = "env" if from_env else ("file" if key else "none")
    return {
        "has_key": bool(key),
        "key_source": src,
        "key_hint": safety.mask_key(key) if key else "",
        "env_var": env,
        "env_present": from_env,
    }


def set_key(pid: str, key) -> None:
    with _LOCK:
        d = _keys()
        if key:
            d[pid] = str(key).strip()
        else:
            d.pop(pid, None)
        _save_keys(d)


# ---------------------------------------------------------------------------
# 提供商 CRUD
# ---------------------------------------------------------------------------
def _clean_id(raw, fallback="p"):
    s = "".join(ch for ch in str(raw or "") if ch.isalnum() or ch in "-_").strip()
    return s[:40] or ("%s-%s" % (fallback, uuid.uuid4().hex[:6]))


def public_provider(prov: dict) -> dict:
    """脱敏后的提供商（可直接下发给前端）。"""
    out = {k: v for k, v in prov.items() if k not in ("api_key", "key")}
    out.update(key_status(prov))
    out["kind_text"] = KINDS.get(prov.get("kind"), prov.get("kind") or "")
    return out


def list_providers() -> list:
    cfg = load_config()
    return [public_provider(p) for p in cfg.get("providers") or []]


def get_provider(pid: str, *, with_key=False) -> dict:
    cfg = load_config()
    for p in cfg.get("providers") or []:
        if p.get("id") == pid:
            if with_key:
                q = dict(p)
                q["_key"] = resolve_key(p)
                return q
            return public_provider(p)
    raise LLMError("not_found", "找不到提供商：%s" % pid)


def upsert_provider(payload: dict) -> dict:
    """新建或更新。`api_key` 若出现则只入保险箱，永不回显、不写 config.json。"""
    if not isinstance(payload, dict):
        raise LLMError("config", "缺少提供商配置")
    cfg = load_config()
    provs = cfg.setdefault("providers", [])

    pid = _clean_id(payload.get("id"))
    kind = str(payload.get("kind") or "openai").strip()
    if kind not in KINDS:
        raise LLMError("config", "不支持的提供商类型：%s（可选 %s）" % (kind, "、".join(KINDS)))

    name = str(payload.get("name") or "").strip()[:60] or KINDS[kind]
    if kind == "mock":
        # 演练通道没有真实端点：固定占位地址，跳过 URL 校验（它不会被联网访问）
        local, base_url = True, "mock://local"
    else:
        local = bool(payload.get("local")) or kind == "ollama"
        base_url = safety.check_base_url(payload.get("base_url"), allow_local=local)

    model = str(payload.get("default_model") or "").strip()[:120]
    models = payload.get("models")
    if isinstance(models, str):
        models = [m.strip() for m in models.replace(",", "\n").splitlines() if m.strip()]
    models = [str(m)[:120] for m in (models or [])]
    if model and model not in models:
        models.insert(0, model)
    if not model and models:
        model = models[0]
    if not model:
        raise LLMError("config", "必须至少填一个模型 ID")

    caps = payload.get("capabilities")
    caps = [c for c in (caps or ["json"]) if c in CAPABILITIES] or ["json"]
    if kind == "ollama" and "json" not in caps:
        caps.append("json")  # Ollama 原生支持 format=json

    timeout_s = _num(payload.get("timeout_s"), 60, lo=5, hi=600, integer=True)
    max_retries = _num(payload.get("max_retries"), 1, lo=0, hi=3, integer=True)
    env_var = str(payload.get("env_var") or "").strip()[:80]
    if env_var and not env_var.replace("_", "").isalnum():
        raise LLMError("config", "环境变量名只允许字母数字与下划线")

    item = {
        "id": pid,
        "name": name,
        "kind": kind,
        "base_url": base_url,
        "default_model": model,
        "models": models[:20],
        "capabilities": caps,
        "local": local,
        "timeout_s": timeout_s,
        "max_retries": max_retries,
        "env_var": env_var,
        # 云端默认走系统代理，本地服务默认直连（详见 providers.BaseProvider 的注释）
        "trust_env": bool(payload.get("trust_env", not local)),
        "enabled": bool(payload.get("enabled", True)),
        "updated_at": time.time(),
    }

    idx = next((i for i, p in enumerate(provs) if p.get("id") == pid), None)
    if idx is None:
        item["created_at"] = time.time()
        # 第一个提供商默认启用
        provs.append(item)
    else:
        kept = {k: provs[idx].get(k) for k in ("created_at", "last_test") if provs[idx].get(k) is not None}
        provs[idx] = {**item, **kept}

    save_config(cfg)

    key = payload.get("api_key")
    if kind == "mock":
        key = ""      # 演练通道永不保存 Key
    if isinstance(key, str) and key.strip():
        set_key(pid, key.strip())
    elif payload.get("clear_key"):
        set_key(pid, "")
    return get_provider(pid)


def delete_provider(pid: str) -> dict:
    cfg = load_config()
    before = len(cfg.get("providers") or [])
    cfg["providers"] = [p for p in (cfg.get("providers") or []) if p.get("id") != pid]
    if len(cfg["providers"]) == before:
        raise LLMError("not_found", "找不到提供商：%s" % pid)
    # 解绑引用它的用途，避免留下悬空配置
    unbound = []
    for key, val in (cfg.get("purposes") or {}).items():
        if val.get("provider_id") == pid:
            val.pop("provider_id", None)
            val.pop("model", None)
            unbound.append(key)
    save_config(cfg)
    set_key(pid, "")
    return {"ok": True, "id": pid, "unbound_purposes": unbound}


def record_test(pid: str, result: dict) -> None:
    cfg = load_config()
    for p in cfg.get("providers") or []:
        if p.get("id") == pid:
            p["last_test"] = {
                "at": time.time(),
                "ok": bool(result.get("ok")),
                "kind": result.get("kind") or ("ok" if result.get("ok") else "protocol"),
                "message": safety.scrub(result.get("message") or "")[:300],
                "elapsed_ms": result.get("elapsed_ms"),
                "models": (result.get("models") or [])[:20],
            }
            break
    save_config(cfg)


# ---------------------------------------------------------------------------
# 用途路由
# ---------------------------------------------------------------------------
def get_purpose(pid: str) -> dict:
    spec = templates.PURPOSE_MAP.get(pid)
    if not spec:
        raise LLMError("not_found", "未知用途：%s" % pid)
    cfg = load_config()
    bound = (cfg.get("purposes") or {}).get(pid) or {}
    provs = {p.get("id"): p for p in (cfg.get("providers") or [])}
    prov = provs.get(bound.get("provider_id")) or {}
    out = dict(spec)
    out.update({k: bound.get(k) for k in ("provider_id", "model", "temperature", "max_tokens") if k in bound})
    out["provider_id"] = bound.get("provider_id") or ""
    out["provider_name"] = prov.get("name") or ""
    out["bound"] = bool(bound.get("provider_id"))
    out["auto"] = False
    if not out["provider_id"]:
        # 没显式绑定 → 走同一套自动选路（与 list_purposes 同一个函数，
        # 保证「界面说会用谁」和「网关实际用了谁」永远一致）。
        picked = auto_provider(pid, cfg)
        if picked:
            out["provider_id"] = picked.get("id") or ""
            out["provider_name"] = picked.get("name") or ""
            out["auto"] = True
    # ready 与 list_purposes 同口径：绑定 + 提供商启用
    out["ready"] = bool(bound.get("provider_id") and prov.get("enabled"))
    return out


def key_ready(prov: dict) -> bool:
    """这个提供商现在能不能真的发请求：有 Key，或本地/演练（不需要 Key）。"""
    kind = str(prov.get("kind") or "")
    if kind in ("ollama", "mock"):
        return True
    return bool(resolve_key(prov)) or bool(prov.get("local"))


def auto_provider(spec_id: str, cfg: dict | None = None) -> dict:
    """给某个用途挑一个能跑起来的提供商（用户没显式绑定时的兜底）。

    为什么需要：新用户只加了一个提供商，却要手动给每个用途逐个绑定，
    否则每次生成都报「用途 X 还没有绑定提供商」。10 个用途要绑 10 次，
    这不是配置，是刁难。**显式绑定永远优先**，这只是兜底。

    排序：有 Key 的云端 > 本地已部署 > 离线演练（Mock）。
    Mock 排最后——它能跑通链路，但输出是假的，不该抢在真模型前面。
    """
    spec = templates.PURPOSE_MAP.get(spec_id)
    if not spec:
        return {}
    cfg = cfg if cfg is not None else load_config()
    need = list(spec.get("requires") or [])
    best, best_rank = None, 0
    for prov in cfg.get("providers") or []:
        if not prov.get("enabled", True):
            continue
        have = list(prov.get("capabilities") or [])
        if any(c not in have for c in need):
            continue
        if not key_ready(prov):
            continue
        kind = str(prov.get("kind") or "")
        rank = 1 if kind == "mock" else (2 if prov.get("local") else 3)
        if rank > best_rank:
            best, best_rank = prov, rank
    return best or {}


def list_purposes() -> list:
    cfg = load_config()
    provs = {p.get("id"): p for p in (cfg.get("providers") or [])}
    out = []
    for spec in templates.PURPOSES:
        bound = (cfg.get("purposes") or {}).get(spec["id"]) or {}
        p = provs.get(bound.get("provider_id")) or {}
        explicit = bool(bound.get("provider_id") and p.get("enabled"))
        picked = {} if explicit else auto_provider(spec["id"], cfg)
        out.append({
            **spec,
            "provider_id": bound.get("provider_id") or "",
            "provider_name": p.get("name") or "",
            "model": bound.get("model") or "",
            "temperature": bound.get("temperature"),
            "max_tokens": bound.get("max_tokens"),
            "bound": bool(bound.get("provider_id")),
            # 自动选路：界面要能显示「未指定 → 实际会用谁」，否则用户不知道钱花在哪
            "auto_provider_id": picked.get("id") or "",
            "auto_provider_name": picked.get("name") or "",
            "auto": bool(picked),
            "ready": bool(explicit or picked),
        })
    return out


def set_purpose(pid: str, patch: dict) -> dict:
    if pid not in templates.PURPOSE_MAP:
        raise LLMError("not_found", "未知用途：%s" % pid)
    cfg = load_config()
    provs = {p.get("id"): p for p in (cfg.get("providers") or [])}
    slot = cfg.setdefault("purposes", {}).setdefault(pid, {})

    if "provider_id" in patch:
        v = str(patch.get("provider_id") or "").strip()
        if v and v not in provs:
            raise LLMError("not_found", "找不到提供商：%s" % v)
        if v:
            slot["provider_id"] = v
            if patch.get("model") in (None, ""):
                slot["model"] = provs[v].get("default_model") or ""
        else:
            slot.pop("provider_id", None)
            slot.pop("model", None)
            # 解绑后不留空壳：{} 会让配置文件看起来像「有一条没配完的路由」
            if not slot:
                cfg.get("purposes", {}).pop(pid, None)
                save_config(cfg)
                return get_purpose(pid)

    if "model" in patch and patch.get("model"):
        p = provs.get(slot.get("provider_id"))
        if p and patch["model"] not in (p.get("models") or []):
            raise LLMError("config", "模型 %s 不在该提供商的模型列表里" % patch["model"])
        slot["model"] = str(patch["model"])[:120]

    for key, lo, hi, integer in (("temperature", 0, 2, False), ("max_tokens", 64, 64000, True)):
        if key in patch and patch[key] is not None and patch[key] != "":
            slot[key] = _num(patch[key], None, lo=lo, hi=hi, integer=integer)

    save_config(cfg)
    return get_purpose(pid)


def _num(v, default, *, lo, hi, integer=False):
    if v is None or v == "":
        return default
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise LLMError("config", "数值不合法：%r" % (v,)) from None
    if f < lo or f > hi:
        raise LLMError("config", "数值越界：%s（应在 %s-%s）" % (f, lo, hi))
    return int(round(f)) if integer else round(f, 3)


# ---------------------------------------------------------------------------
# 用量日志
# ---------------------------------------------------------------------------
def append_usage(rec: dict) -> None:
    _ensure()
    line = json.dumps(rec, ensure_ascii=False) + "\n"
    with _LOCK:
        with open(USAGE_FILE, "a", encoding="utf-8", newline="") as fh:
            fh.write(line)


def usage(limit=200, purpose=None, provider=None) -> dict:
    """读最近 N 条（倒序）。文件不存在返回空，不报错。"""
    rows = []
    try:
        with open(USAGE_FILE, "r", encoding="utf-8", errors="replace") as fh:
            for ln in fh:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    d = json.loads(ln)
                except json.JSONDecodeError:
                    continue
                if purpose and d.get("purpose") != purpose:
                    continue
                if provider and d.get("provider") != provider:
                    continue
                rows.append(d)
    except OSError:
        return {"items": [], "total": 0, "summary": _summary([])}
    total = len(rows)
    rows = rows[-int(limit):][::-1]
    return {"items": rows, "total": total, "summary": _summary(rows)}


def _summary(rows) -> dict:
    ok = sum(1 for r in rows if r.get("ok"))
    tin = sum(int((r.get("usage") or {}).get("input_tokens") or 0) for r in rows)
    tout = sum(int((r.get("usage") or {}).get("output_tokens") or 0) for r in rows)
    usd = [r.get("cost", {}).get("usd") for r in rows if isinstance(r.get("cost"), dict)]
    known = [x for x in usd if isinstance(x, (int, float))]
    return {
        "calls": len(rows),
        "ok": ok,
        "failed": len(rows) - ok,
        "input_tokens": tin,
        "output_tokens": tout,
        "cost_usd_known": round(sum(known), 6) if known else None,
        "cost_records": len(known),
        "cost_note": ("金额仅来自供应商返回的 usage；缺失即为未知，不做估算"
                      if len(known) else "供应商未返回金额，全部为未知"),
    }
