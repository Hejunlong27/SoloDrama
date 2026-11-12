# -*- coding: utf-8 -*-
"""统一 LLM 记账框架的离线测试。

覆盖四件事：
  1. 中转站 usage 里的 cost/input_tokens 等字段不能被适配器丢掉；
  2. Gateway.chat() 的多轮调用必须写 project 与未知金额状态；
  3. 已知/未知金额汇总不能互相污染；
  4. 制片助手必须走 Gateway，不能绕过记账。
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB))

from core import agent  # noqa: E402
from core.llm import gateway, providers, store  # noqa: E402
from core.llm.errors import LLMError  # noqa: E402


class LlmStoreSandbox:
    def __enter__(self):
        self.old = (store.LLM_DIR, store.CONFIG_FILE, store.KEYS_FILE, store.USAGE_FILE)
        self.tmp = Path(tempfile.mkdtemp(prefix="llm-framework-"))
        store.use_dir(self.tmp)
        return self.tmp

    def __exit__(self, *exc):
        store.LLM_DIR, store.CONFIG_FILE, store.KEYS_FILE, store.USAGE_FILE = self.old
        return False


def test_usage_normalization_preserves_provider_cost():
    usage = providers._usage_of({
        "input_tokens": 12,
        "output_tokens": 34,
        "cost": 0.0042,
        "currency": "USD",
    })
    assert usage["input_tokens"] == 12
    assert usage["output_tokens"] == 34
    assert usage["total_tokens"] == 46
    assert usage["raw"]["cost"] == 0.0042
    assert usage["raw"]["currency"] == "USD"
    assert gateway._cost_of(usage) == {"usd": 0.0042, "source": "provider"}


def test_gateway_chat_logs_project_and_unknown_cost():
    with LlmStoreSandbox():
        store.upsert_provider({
            "id": "mock-agent", "name": "Mock Agent", "kind": "mock",
            "default_model": "mock-1", "models": ["mock-1"],
            "capabilities": ["text", "json"], "local": True,
        })

        res = gateway.Gateway().chat(
            [{"role": "user", "content": "只回复 JSON"}],
            purpose="agent.chat", provider_id="mock-agent", project="D:/drama-a",
        )
        assert res["ok"] is True
        assert res["provider"] == "mock-agent"
        assert res["cost"] == {"usd": None, "source": "unknown"}

        data = store.usage(project="D:/drama-a")
        assert data["total"] == 1
        rec = data["items"][0]
        assert rec["kind"] == "chat"
        assert rec["project"] == "D:/drama-a"
        assert rec["cost"]["usd"] is None
        assert data["summary"]["cost_usd_known"] is None
        assert data["summary"]["cost_records"] == 0
        assert data["summary"]["cost_unknown_records"] == 1
        assert data["summary"]["cost_status"] == "unknown"


def test_usage_summary_keeps_known_and_unknown_separate():
    with LlmStoreSandbox():
        store.append_usage({
            "ok": True, "usage": {"input_tokens": 1, "output_tokens": 2},
            "cost": {"usd": 0.12, "source": "provider"}, "project": "p1",
        })
        store.append_usage({
            "ok": True, "usage": {"input_tokens": 3, "output_tokens": 4},
            "cost": {"usd": None, "source": "unknown"}, "project": "p1",
        })

        summary = store.usage(project="p1")["summary"]
        assert summary["cost_usd_known"] == 0.12
        assert summary["cost_records"] == 1
        assert summary["cost_unknown_records"] == 1
        assert summary["cost_status"] == "mixed"


def test_gateway_chat_logs_provider_returned_cost():
    class CostProvider:
        def chat(self, messages, **kwargs):
            return providers.ProviderResult(
                text="ok", model="cost-model",
                usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
                       "raw": {"cost": 0.003, "currency": "USD"}},
            )

    with LlmStoreSandbox():
        store.upsert_provider({
            "id": "cost-local", "name": "Cost Local", "kind": "openai",
            "base_url": "http://127.0.0.1:9/v1", "default_model": "cost-model",
            "models": ["cost-model"], "capabilities": ["text"], "local": True,
        })
        res = gateway.Gateway(factory=lambda prov, key: CostProvider()).chat(
            [{"role": "user", "content": "hi"}],
            provider_id="cost-local", project="D:/drama-c",
        )
        assert res["ok"] is True
        assert res["cost"] == {"usd": 0.003, "source": "provider"}
        summary = store.usage(project="D:/drama-c")["summary"]
        assert summary["cost_usd_known"] == 0.003
        assert summary["cost_records"] == 1
        assert summary["cost_unknown_records"] == 0
        assert summary["cost_status"] == "known"


def test_agent_endpoint_requires_confirm():
    from fastapi.testclient import TestClient
    from app import app

    client = TestClient(app, base_url="http://127.0.0.1")
    res = client.post("/api/agent/chat", json={
        "ws": "x", "messages": [{"role": "user", "content": "hi"}],
    })
    assert res.status_code == 428
    assert res.json()["detail"]["cmd"] == "agent.chat"


def test_agent_chat_uses_gateway(monkeypatch):
    seen = {}

    class FakeGateway:
        def chat(self, messages, **kwargs):
            seen["messages"] = messages
            seen.update(kwargs)
            return {
                "ok": True, "text": '{"say":"完成","done":true}',
                "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
                "provider": "fake", "model": "fake-model", "cost": {"usd": None, "source": "unknown"},
            }

    monkeypatch.setattr(agent.gw, "get_gateway", lambda: FakeGateway())
    out = agent._chat("D:/drama-b", "fake-model", [{"role": "user", "content": "继续"}])
    assert out["ok"] is True
    assert seen["purpose"] == "agent.chat"
    assert seen["route_purpose"] == "create.plan"
    assert seen["project"] == "D:/drama-b"
    assert seen["model"] == "fake-model"

def test_route_chain_keeps_primary_and_fallback():
    with LlmStoreSandbox():
        for pid in ("p1", "p2"):
            store.upsert_provider({
                "id": pid, "name": pid, "kind": "mock",
                "default_model": "mock-1", "models": ["mock-1"],
                "capabilities": ["text"], "local": True,
            })
        out = store.set_purpose("create.plan", {"routes": [
            {"provider_id": "p1", "model": "mock-1"},
            {"provider_id": "p2", "model": "mock-1", "id": "backup"},
        ]})
        assert out["provider_id"] == "p1"
        assert out["fallback_count"] == 1
        assert [r["provider_id"] for r in out["routes"]] == ["p1", "p2"]
        assert out["routes"][1]["id"] == "backup"

        # 旧单路由写法仍兼容，并清除历史 routes，避免两个真源并存。
        old = store.set_purpose("create.plan", {"provider_id": "p2"})
        assert old["provider_id"] == "p2"
        assert len(old["routes"]) == 1


def test_gateway_chat_falls_back_only_on_safe_errors():
    with LlmStoreSandbox():
        for pid in ("primary", "backup"):
            store.upsert_provider({
                "id": pid, "name": pid, "kind": "mock",
                "default_model": "mock-1", "models": ["mock-1"],
                "capabilities": ["text"], "local": True,
            })
        store.set_purpose("create.plan", {"routes": [
            {"provider_id": "primary", "model": "mock-1", "id": "primary"},
            {"provider_id": "backup", "model": "mock-1", "id": "backup"},
        ]})

        def factory(prov, key):
            if prov["id"] == "primary":
                return providers.MockProvider(prov, key, script=[LLMError("auth", "bad key")])
            return providers.MockProvider(prov, key)

        res = gateway.Gateway(factory=factory).chat(
            [{"role": "user", "content": "hi"}], route_purpose="create.plan",
            purpose="agent.chat", project="D:/route-test",
        )
        assert res["ok"] is True
        assert res["provider"] == "backup"
        assert [x["error_kind"] for x in res["route_attempts"]] == ["auth", ""]
        usage = store.usage(project="D:/route-test")
        assert usage["total"] == 2
        assert {x["provider"] for x in usage["items"]} == {"primary", "backup"}
        assert {x["route_id"] for x in usage["items"]} == {"primary", "backup"}


def test_gateway_chat_does_not_fallback_on_schema_error():
    with LlmStoreSandbox():
        for pid in ("primary", "backup"):
            store.upsert_provider({
                "id": pid, "name": pid, "kind": "mock",
                "default_model": "mock-1", "models": ["mock-1"],
                "capabilities": ["text"], "local": True,
            })
        store.set_purpose("create.plan", {"routes": [
            {"provider_id": "primary", "model": "mock-1", "id": "primary"},
            {"provider_id": "backup", "model": "mock-1", "id": "backup"},
        ]})

        def factory(prov, key):
            if prov["id"] == "primary":
                return providers.MockProvider(prov, key, script=[LLMError("schema", "bad json")])
            return providers.MockProvider(prov, key)

        res = gateway.Gateway(factory=factory).chat(
            [{"role": "user", "content": "hi"}], route_purpose="create.plan",
            purpose="agent.chat", project="D:/no-fallback",
        )
        assert res["ok"] is False
        assert res["error"]["kind"] == "schema"
        assert len(res["route_attempts"]) == 1
        assert store.usage(project="D:/no-fallback")["total"] == 1

def test_gateway_complete_uses_same_route_chain():
    with LlmStoreSandbox():
        for pid in ("primary", "backup"):
            store.upsert_provider({
                "id": pid, "name": pid, "kind": "openai",
                "base_url": "http://127.0.0.1:9/v1",
                "default_model": "mock-1", "models": ["mock-1"],
                "capabilities": ["text"], "local": True,
            })
        store.set_purpose("create.plan", {"routes": [
            {"provider_id": "primary", "model": "mock-1", "id": "primary"},
            {"provider_id": "backup", "model": "mock-1", "id": "backup"},
        ]})

        def factory(prov, key):
            if prov["id"] == "primary":
                return providers.MockProvider(prov, key, script=[LLMError("quota", "no balance")])
            return providers.MockProvider(prov, key, script=[{"text": "backup output"}])

        res = gateway.Gateway(factory=factory).complete(
            "create.plan",
            {"skill_prompt": "x", "idea": "y", "episodes": 1,
             "seconds": 60, "style_lock": "cinematic"},
            project="D:/complete-route",
        )
        assert res["ok"] is True
        assert res["provider"] == "backup"
        assert [x["error_kind"] for x in res["route_attempts"]] == ["quota", ""]
        assert store.usage(project="D:/complete-route")["total"] == 2

def test_provider_health_reports_cooling_and_blocked():
    with LlmStoreSandbox():
        store.upsert_provider({
            "id": "cool", "name": "Cool", "kind": "mock",
            "default_model": "mock-1", "models": ["mock-1"], "local": True,
        })
        store.append_usage({"provider": "cool", "ok": False, "at": time.time(),
                            "error_kind": "rate_limit", "usage": {}, "cost": {}})
        cooling = store.provider_health("cool")
        assert cooling["state"] == "cooling"
        assert cooling["cooling"] is True
        assert cooling["last_error_kind"] == "rate_limit"
        listed = {x["id"]: x for x in store.list_providers()}["cool"]
        assert listed["health"]["state"] == "cooling"

        store.append_usage({"provider": "blocked", "ok": False, "at": time.time(),
                            "error_kind": "quota", "usage": {}, "cost": {}})
        blocked = store.provider_health("blocked")
        assert blocked["state"] == "blocked"
        assert blocked["cooling"] is False


def test_gateway_skips_cooling_primary_when_backup_is_available():
    with LlmStoreSandbox():
        for pid in ("primary", "backup"):
            store.upsert_provider({
                "id": pid, "name": pid, "kind": "mock",
                "default_model": "mock-1", "models": ["mock-1"],
                "capabilities": ["text"], "local": True,
            })
        store.set_purpose("create.plan", {"routes": [
            {"provider_id": "primary", "model": "mock-1", "id": "primary"},
            {"provider_id": "backup", "model": "mock-1", "id": "backup"},
        ]})
        store.append_usage({"provider": "primary", "ok": False, "at": time.time(),
                            "error_kind": "rate_limit", "usage": {}, "cost": {}})
        calls = []

        def factory(prov, key):
            calls.append(prov["id"])
            assert prov["id"] != "primary", "冷却中的主路由不应被调用"
            return providers.MockProvider(prov, key)

        res = gateway.Gateway(factory=factory).chat(
            [{"role": "user", "content": "hi"}], route_purpose="create.plan",
            purpose="agent.chat", project="D:/cooldown",
        )
        assert res["ok"] is True
        assert res["provider"] == "backup"
        assert calls == ["backup"]


def test_models_ui_exposes_route_chain_editor():
    text = (WEB / "ui" / "studio" / "js" / "views" / "models.js").read_text(encoding="utf-8")
    assert "data-proute" in text
    assert "openRouteEditor" in text
    assert "routeSave" in text
    assert "fallback_count" in text
