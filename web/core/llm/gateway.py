# -*- coding: utf-8 -*-
"""统一 LLM 网关

一切文本生成都从这里走：解析用途 → 取提供商 → 渲染模板 → 调用 → 解析 JSON →
Schema 校验 → 记用量。业务层（路由 / 创作闭环）不直接碰 httpx，也不各自拼提示词。

六条硬规则：
  1. **能力先校验**：用途要求 `json` 而模型不支持，直接拒绝，不发请求（省一次失败与一次计费）。
  2. **重试只针对确定的失败**：仅 `errors.RETRYABLE` 里的类别重试；鉴权/参数/协议错误不重试，
     避免"网络错误后无条件重发可能已执行的生成请求"。
  3. **Schema 硬校验**：不通过就是失败，不把半结构化文本当成功。
  4. **用量必记**：成功与失败都写 `usage.jsonl`；不记提示词与生成正文（只记哈希与长度）。
  5. **金额只认供应商返回**：没有就是 `unknown`，绝不按 token 单价编一个数字。
  6. **错误文本过 `scrub`**：上游回显的 Key 不会流到前端或日志。
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid

from .. import jsonout
from . import providers, safety, schema as schema_mod, store, templates
from .errors import LLMError

_FENCE = re.compile(r"```(?:json|JSON)?\s*\n(.*?)```", re.S)

# 允许的重试退避（秒）；2 次尝试足够，别把用户挂太久
_BACKOFF = (0, 1.5, 4.0)


def parse_json_text(text):
    """从模型输出里取 JSON。容忍 ```json 围栏、前后寒暄、BOM。"""
    s = (text or "").strip().lstrip("\ufeff")
    if not s:
        raise LLMError("parse", "模型没有返回任何内容")
    m = _FENCE.search(s)
    if m:
        s = m.group(1).strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    obj = jsonout.extract_json(text or "")
    if obj is None:
        raise LLMError("parse", "输出中找不到合法的 JSON 对象")
    return obj


def _sha(text) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def _cost_of(usage) -> dict:
    """金额：只认供应商返回的 cost 字段（OpenRouter 等会带）。"""
    u = usage or {}
    raw = u.get("raw") if isinstance(u.get("raw"), dict) else {}
    for key in ("cost", "total_cost", "cost_usd"):
        v = raw.get(key) if key in raw else u.get(key)
        if isinstance(v, (int, float)):
            return {"usd": round(float(v), 6), "source": "provider"}
    return {"usd": None, "source": "unknown"}


class Gateway:
    def __init__(self, factory=None):
        # 工厂可注入，测试里替换成 Mock
        self._factory = factory or providers.build

    # ------------------------------------------------------------------
    # 连接测试（用户主动触发，默认 0 费用）
    # ------------------------------------------------------------------
    def test_provider(self, pid: str, *, deep: bool = False) -> dict:
        t0 = time.time()
        try:
            prov = store.get_provider(pid, with_key=True)
        except LLMError as exc:
            return {"ok": False, "kind": exc.kind, "message": exc.text}

        if prov.get("kind") == "mock":
            out = {"ok": True, "mode": "mock", "model_count": 1,
                   "models": [prov.get("default_model") or "mock-episode"],
                   "elapsed_ms": int((time.time() - t0) * 1000),
                   "note": "离线演练通道：不联网、不计费；只验证链路是否连通"}
            store.record_test(pid, out)
            return out

        base_url = prov.get("base_url") or ""
        try:
            safety.check_base_url(base_url, allow_local=bool(prov.get("local")))
            safety.check_resolved(_host_of(base_url), allow_local=bool(prov.get("local")))
        except LLMError as exc:
            return {"ok": False, "kind": exc.kind, "message": exc.text,
                    "elapsed_ms": int((time.time() - t0) * 1000)}

        key = prov.get("_key") or ""
        if not key and not prov.get("local") and not prov.get("env_var"):
            return {"ok": False, "kind": "config",
                    "message": "还没有配置 API Key（可写环境变量名，或在本页保存到本机）"}

        try:
            p = self._factory(prov, key)
        except LLMError as exc:
            return {"ok": False, "kind": exc.kind, "message": exc.text}

        # 先做只读的模型列表探测
        models = []
        try:
            # 走代理时首包可能偏慢：给到 30 秒上限（只读请求，不会产生生成费用）
            models = p.list_models(timeout_s=min(float(prov.get("timeout_s") or 60), 30))
        except LLMError as exc:
            if not deep:
                msg = exc.text
                if exc.kind == "protocol":
                    msg += "（该端点可能不支持模型列表；可勾选「最小生成测试」再试）"
                out = {"ok": False, "kind": exc.kind, "message": msg,
                       "elapsed_ms": int((time.time() - t0) * 1000)}
                # 失败也要留痕：否则界面永远显示「还没测试过」，用户重复踩同一个坑
                store.record_test(pid, out)
                return out
            # deep 模式下列表失败不致命，继续做一次最小生成

        if deep:
            try:
                res = p.chat(
                    [{"role": "system", "content": "你是连通性探针。"},
                     {"role": "user", "content": "只回复 JSON：{\"ping\": true}"}],
                    model=prov.get("default_model"), max_tokens=16, json_mode=False, timeout_s=30,
                )
                out = {"ok": True, "mode": "generate", "sample": (res.text or "")[:80],
                       "elapsed_ms": int((time.time() - t0) * 1000),
                       "models": models, "note": "本次为真实调用，可能产生少量费用"}
                store.record_test(pid, out)
                return out
            except LLMError as exc:
                out = {"ok": False, "kind": exc.kind, "message": exc.text,
                       "elapsed_ms": int((time.time() - t0) * 1000)}
                store.record_test(pid, out)
                return out

        out = {"ok": True, "mode": "list", "models": models, "model_count": len(models),
               "elapsed_ms": int((time.time() - t0) * 1000), "note": "只读探测，未产生生成费用"}
        store.record_test(pid, out)
        return out

    # ------------------------------------------------------------------
    # 提示词预览（不调用模型）
    # ------------------------------------------------------------------
    def preview(self, purpose: str, variables: dict) -> dict:
        spec = templates.PURPOSE_MAP.get(purpose)
        if not spec:
            raise LLMError("not_found", "未知用途：%s" % purpose)
        tid = spec["template_id"]
        system, user = templates.render_parts(tid, variables)
        return {
            "ok": True,
            "purpose": purpose,
            "template_id": tid,
            "template_sha": templates.body_sha(tid),
            "schema_id": spec.get("schema_id") or "",
            "requires": spec.get("requires") or [],
            "system_chars": len(system),
            "user_chars": len(user),
            "system": system,
            "user": user,
        }

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def complete(self, purpose, variables=None, *, provider_id=None, model=None,
                 timeout_s=None, job_id=None, cancel=None, temperature=None,
                 max_tokens=None, template_id=None, validate_schema=True,
                 project=None) -> dict:
        """生成一次。**不抛业务错误**：返回 `{ok: bool, ...}`，保证前端拿到分类信息。

        失败也写用量；`error` 里只有分类与人话。
        """
        rid = uuid.uuid4().hex[:12]
        t0 = time.time()
        spec = templates.PURPOSE_MAP.get(purpose)
        if not spec:
            return {"ok": False, "request_id": rid,
                    "error": {"kind": "not_found", "message": "未知用途：%s" % purpose,
                              "retryable": False}}

        tid = template_id or spec["template_id"]
        pid = provider_id or store.get_purpose(purpose).get("provider_id")

        base = {
            "request_id": rid, "purpose": purpose, "template_id": tid,
            "template_sha": templates.body_sha(tid), "job_id": job_id or "",
            "provider": "", "provider_name": "", "model": "",
        }

        def fail(exc: LLMError, extra=None):
            rec = {**base, "ok": False, "at": time.time(), "elapsed_ms": int((time.time() - t0) * 1000),
                   "simulated": base.get("simulated", False),
                   "error_kind": exc.kind, "error": safety.scrub(exc.text)[:300],
                   "usage": {}, "cost": {"usd": None, "source": "unknown"},
                   "prompt_sha": "", "output_sha": "", **(extra or {})}
            store.append_usage(rec)
            return {"ok": False, "request_id": rid, "purpose": purpose, "template_id": tid,
                    "elapsed_ms": rec["elapsed_ms"],
                    "error": {"kind": exc.kind, "message": safety.scrub(exc.text),
                              "retryable": exc.retryable, "status": exc.status}}

        if not pid:
            return fail(LLMError("config", "用途「%s」还没有绑定提供商，请先到「AI 模型中心」指定"
                                 % spec["label"]))

        try:
            prov = store.get_provider(pid, with_key=True)
        except LLMError as exc:
            return fail(exc)

        base["provider"] = prov.get("id")
        base["provider_name"] = prov.get("name")
        base["model"] = model or store.get_purpose(purpose).get("model") or prov.get("default_model")

        if not prov.get("enabled"):
            return fail(LLMError("config", "提供商「%s」已停用" % prov.get("name")))

        # 每次调用都复核地址（配置可能被手工改过）；DNS 解析只在连接测试时做，
        # 避免给每次生成加一次解析延迟——这一点在文档里写清楚。
        simulated = prov.get("kind") == "mock"
        base["simulated"] = simulated
        if not simulated:
            try:
                safety.check_base_url(prov.get("base_url"), allow_local=bool(prov.get("local")))
            except LLMError as exc:
                return fail(exc)

        # 能力校验（发请求之前）
        need = list(spec.get("requires") or [])
        have = list(prov.get("capabilities") or [])
        lack = [c for c in need if c not in have]
        if lack:
            return fail(LLMError("unsupported",
                                 "提供商「%s」未声明能力 %s（该用途要求 %s）；"
                                 "请在提供商配置里勾选对应能力，或换一个支持的模型"
                                 % (prov.get("name"), "、".join(lack), "、".join(need))))

        key = prov.get("_key") or ""
        if not key and not prov.get("local") and not simulated:
            return fail(LLMError("config", "提供商「%s」缺少 API Key（环境变量 %s 未设置）"
                                 % (prov.get("name"), prov.get("env_var") or "未指定")))

        # 渲染
        try:
            system, user = templates.render_parts(tid, variables or {})
        except FileNotFoundError:
            return fail(LLMError("config", "模板文件缺失：%s" % templates.body_path(tid)))
        except LLMError as exc:
            return fail(exc)

        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        base["prompt_sha"] = _sha(system + "\n" + user)

        if not simulated:
            try:
                p = self._factory(prov, key)
            except LLMError as exc:
                return fail(exc)

        temp = temperature if temperature is not None else store.get_purpose(purpose).get("temperature")
        mtok = max_tokens or store.get_purpose(purpose).get("max_tokens")
        retries = int(prov.get("max_retries") or 0)
        attempt = 0
        res = None
        last = None

        while attempt <= retries:
            if cancel is not None and getattr(cancel, "is_set", None) and cancel.is_set():
                return fail(LLMError("canceled", "已取消"), {"attempts": attempt})
            try:
                if simulated:
                    # ★ 只替换「网络那一段」：输出仍走同一条 解析 → Schema → 草稿 路径
                    res = providers.ProviderResult(
                        text=templates.mock_payload(purpose, variables or {}),
                        model=base["model"],
                        usage={"input_tokens": None, "output_tokens": None, "total_tokens": None, "raw": None},
                        raw_status=200)
                else:
                    res = p.chat(messages, model=base["model"], temperature=temp, max_tokens=mtok,
                                 json_mode=(prov.get("kind") in ("openai", "ollama") and "json" in have),
                                 timeout_s=timeout_s, cancel=cancel)
                break
            except LLMError as exc:
                last = exc
                attempt += 1
                if not exc.retryable or attempt > retries:
                    return fail(exc, {"attempts": attempt})
                time.sleep(_BACKOFF[min(attempt, len(_BACKOFF) - 1)])
            except Exception as exc:  # noqa: BLE001 - 适配器没包住的意外
                return fail(LLMError("network", safety.scrub(str(exc))[:200]), {"attempts": attempt + 1})

        elapsed_ms = int((time.time() - t0) * 1000)
        usage = res.usage or {}
        cost = _cost_of(usage)
        out = {
            "ok": True, "request_id": rid, "purpose": purpose, "template_id": tid,
            "template_sha": base["template_sha"], "provider": prov.get("id"),
            "provider_name": prov.get("name"), "model": res.model or base["model"],
            "text": res.text, "elapsed_ms": elapsed_ms, "attempts": attempt + 1,
            "usage": {"input_tokens": usage.get("input_tokens"),
                      "output_tokens": usage.get("output_tokens"),
                      "total_tokens": usage.get("total_tokens")},
            "cost": cost,
            "simulated": simulated,
        }

        # 结构化解析 + Schema 校验
        sch = templates.SCHEMAS.get(spec.get("schema_id") or "") if validate_schema else None
        if sch:
            try:
                data = parse_json_text(res.text)
            except LLMError as exc:
                return fail(exc, {"attempts": attempt + 1, "elapsed_ms": elapsed_ms,
                                  "usage": out["usage"], "cost": cost,
                                  "output_sha": _sha(res.text), "output_chars": len(res.text or "")})
            errs = schema_mod.validate(data, sch)
            if errs:
                shown = "；".join("%s %s" % (e["path"], e["message"]) for e in errs[:6])
                exc = LLMError("schema", "输出未通过 Schema 校验：%s" % shown,
                               detail=json.dumps(errs[:20], ensure_ascii=False))
                r = fail(exc, {"attempts": attempt + 1, "elapsed_ms": elapsed_ms,
                               "usage": out["usage"], "cost": cost,
                               "output_sha": _sha(res.text), "output_chars": len(res.text or "")})
                r["schema_errors"] = errs[:20]
                return r
            out["data"] = data
        elif validate_schema:
            # 无 Schema 的用途：不假装结构化
            out["data"] = None
            out["note"] = "该用途没有机器可校验的 Schema，输出仅供人工复核"

        store.append_usage({
            **base, "ok": True, "at": time.time(), "elapsed_ms": elapsed_ms,
            "simulated": simulated,
            "attempts": attempt + 1, "usage": out["usage"], "cost": cost,
            "output_sha": _sha(res.text), "output_chars": len(res.text or ""),
            "error_kind": "", "error": "",
        })
        _ = project  # 预留：按项目分别统计用量
        return out

    # ------------------------------------------------------------------
    # 用量汇总
    # ------------------------------------------------------------------
    def usage(self, limit=200, purpose=None, provider=None) -> dict:
        return store.usage(limit=limit, purpose=purpose, provider=provider)


def _host_of(url: str) -> str:
    try:
        from urllib.parse import urlsplit
        return (urlsplit(url).hostname or "").strip("[]")
    except ValueError:
        return ""


_global = None
_glock = threading.Lock()


def get_gateway() -> Gateway:
    global _global
    with _glock:
        if _global is None:
            _global = Gateway()
        return _global


def set_gateway(gw) -> None:
    """测试注入用。"""
    global _global
    with _glock:
        _global = gw
