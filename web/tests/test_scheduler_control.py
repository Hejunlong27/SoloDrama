# -*- coding: utf-8 -*-
"""调度控制面 API 契约：只读状态、默认干跑、真跑二次确认。"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
if str(WEB) not in sys.path:
    sys.path.insert(0, str(WEB))

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "stages" / "production" / "scripts" / "tests" / "fixtures" / "mini_drama"


def _ws(tmp_path):
    ws = tmp_path / "mini_drama"
    shutil.copytree(FIXTURE, ws)
    return str(ws)


def _client():
    from fastapi.testclient import TestClient
    import app as appmod

    return appmod, TestClient(appmod.app, base_url="http://127.0.0.1")


def test_scheduler_commands_are_registered():
    from core import commands as CMD

    status = CMD.get("scheduler.status")
    run = CMD.get("scheduler.run")
    assert status is not None and status.mode == "sync"
    assert run is not None and run.danger == CMD.WRITE
    argv = run.build_argv({"apply": True, "max_steps": 2}, r"D:\剧\测试")
    assert argv[1].endswith("runner_cli.py")
    assert argv[-2:] == ["--workspace", r"D:\剧\测试"]


def test_status_route_reads_engine_json(tmp_path):
    appmod, client = _client()
    with client:
        r = client.get("/api/scheduler/status", params={"ws": _ws(tmp_path), "ep": "ep01", "limit": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["next"]["id"] == "import.pack"
    assert len(body["nodes"]) == 13


def test_run_route_defaults_to_dry_run(monkeypatch, tmp_path):
    appmod, client = _client()
    captured = {}

    def fake_create(ws, cmd, argv, values, **kwargs):
        captured.update({"ws": ws, "cmd": cmd.id, "argv": argv, "values": values})
        return {"id": "fake-job", "status": "queued"}

    monkeypatch.setattr(appmod.jobs, "create_job", fake_create)
    with client:
        r = client.post("/api/scheduler/run", json={
            "ws": _ws(tmp_path), "params": {"ep": "ep01", "max_steps": 1}
        })
    assert r.status_code == 202
    assert captured["cmd"] == "scheduler.run"
    assert captured["values"]["apply"] is False
    assert captured["values"]["yes"] is False


def test_apply_requires_ack_and_gpu_confirmation(monkeypatch, tmp_path):
    appmod, client = _client()
    monkeypatch.setattr(appmod.jobs, "create_job", lambda *a, **k: {"id": "fake", "status": "queued"})
    body = {"ws": _ws(tmp_path), "params": {"ep": "ep01", "apply": True}}
    with client:
        no_ack = client.post("/api/scheduler/run", json=body)
        gpu_missing = client.post("/api/scheduler/run", json={
            **body, "confirm": {"ack": True}
        })
        safe_apply = client.post("/api/scheduler/run", json={
            **body, "confirm": {"ack": True, "gpu": True}
        })
    assert no_ack.status_code == 428
    assert gpu_missing.status_code == 202
    assert safe_apply.status_code == 202


def test_yes_requires_separate_gpu_ack(monkeypatch, tmp_path):
    appmod, client = _client()
    monkeypatch.setattr(appmod.jobs, "create_job", lambda *a, **k: {"id": "fake", "status": "queued"})
    body = {"ws": _ws(tmp_path), "params": {"ep": "ep01", "apply": True, "yes": True},
            "confirm": {"ack": True}}
    with client:
        r = client.post("/api/scheduler/run", json=body)
    assert r.status_code == 428
    assert r.json()["detail"]["need_gpu_yes"] is True