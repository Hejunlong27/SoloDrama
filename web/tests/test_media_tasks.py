# -*- coding: utf-8 -*-
"""通用媒体任务状态与 task ID 持久化的离线测试。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB))

import pytest  # noqa: E402

from core import media_tasks  # noqa: E402


def test_create_quote_and_list(tmp_path):
    rec = media_tasks.create(
        tmp_path, kind="video", model="zhenzhen-video-muse", provider_id="zzai",
        request={"prompt": "rain", "duration": 5},
        purpose="video.batch", episode="ep01", shot_id="shot_001",
    )
    assert rec["status"] == "planned"
    assert rec["request_sha"]
    rec = media_tasks.set_estimate(
        tmp_path, rec["id"],
        {"estimate_available": True, "amount": 0.09, "currency": "CNY"},
        max_cost=0.10,
    )
    assert rec["status"] == "estimated"
    items = media_tasks.list_tasks(tmp_path, kind="video")
    assert [x["id"] for x in items] == [rec["id"]]
    assert items[0]["max_cost"] == 0.10


def test_submit_is_authorized_and_idempotent(tmp_path):
    rec = media_tasks.create(tmp_path, kind="image",
                              model="zhenzhen-image-g-v2.6-lowprice")
    with pytest.raises(media_tasks.MediaTaskError, match="显式授权"):
        media_tasks.mark_submitted(tmp_path, rec["id"], "task_1")
    rec = media_tasks.mark_submitted(tmp_path, rec["id"], "task_1", authorized=True)
    assert rec["remote_task_id"] == "task_1"
    assert rec["submissions"] == 1
    same = media_tasks.mark_submitted(tmp_path, rec["id"], "task_1", authorized=True)
    assert same["submissions"] == 1
    with pytest.raises(media_tasks.MediaTaskError, match="拒绝重复提交"):
        media_tasks.mark_submitted(tmp_path, rec["id"], "task_2", authorized=True)


def test_poll_update_terminal_cost_and_resume(tmp_path):
    rec = media_tasks.create(tmp_path, kind="video", model="zhenzhen-video-muse")
    rec = media_tasks.mark_submitted(tmp_path, rec["id"], "remote_9", authorized=True)
    rec = media_tasks.update_remote(
        tmp_path, rec["id"], raw_status="IN_PROGRESS", progress="50%")
    assert rec["status"] == "running"
    rec = media_tasks.update_remote(
        tmp_path, rec["id"], raw_status="SUCCESS", progress="100%",
        usage={"amount": 0, "currency": "CNY"},
        artifacts=[".drama/media/result.mp4"],
    )
    assert rec["status"] == "succeeded"
    assert rec["actual_cost"] is None
    assert rec["provider_usage_cost"] == {"amount": 0, "currency": "CNY"}
    assert rec["cost_status"] == "provisional"
    assert rec["cost_source"] == "unknown"
    info = media_tasks.resume_info(tmp_path, rec["id"])
    assert info["terminal"] is True
    assert info["needs_poll"] is False
    assert info["can_resubmit"] is False


def test_task_file_never_persists_secret_fields(tmp_path):
    rec = media_tasks.create(
        tmp_path, kind="image", model="zhenzhen-image-g-v2.6-lowprice",
        request={"prompt": "x", "api_key": "sk-secret", "nested": {"token": "secret"}},
        estimate={"amount": 1, "authorization": "Bearer secret"},
    )
    raw = (media_tasks.root(tmp_path) / (rec["id"] + ".json")).read_text(encoding="utf-8")
    data = json.loads(raw)
    assert "sk-secret" not in raw
    assert "Bearer secret" not in raw
    assert data["request"] == {"prompt": "x", "nested": {}}
    assert data["estimate"] == {"amount": 1}


def test_status_normalization():
    assert media_tasks.normalize_status("NOT_START") == "queued"
    assert media_tasks.normalize_status("in_progress") == "running"
    assert media_tasks.normalize_status("completed") == "succeeded"
    assert media_tasks.normalize_status("FAILURE") == "failed"
    assert media_tasks.normalize_status("whatever") == "unknown"


def test_media_task_read_api(tmp_path):
    from fastapi.testclient import TestClient
    from app import app

    rec = media_tasks.create(tmp_path, kind="video", model="zhenzhen-video-muse",
                              request={"prompt": "rain", "duration": 5})
    client = TestClient(app, base_url="http://127.0.0.1")
    res = client.get("/api/media/tasks", params={"ws": str(tmp_path)})
    assert res.status_code == 200
    assert [x["id"] for x in res.json()["items"]] == [rec["id"]]
    one = client.get("/api/media/tasks/" + rec["id"], params={"ws": str(tmp_path)})
    assert one.status_code == 200 and one.json()["id"] == rec["id"]


def test_settlement_keeps_provider_usage_separate(tmp_path):
    rec = media_tasks.create(tmp_path, kind="video", model="minimax-h3-comfyui-max")
    rec = media_tasks.mark_submitted(tmp_path, rec["id"], "remote_1", authorized=True)
    rec = media_tasks.update_remote(
        tmp_path, rec["id"], raw_status="SUCCESS", progress="100%",
        usage={"amount": 0.1785, "currency": "CNY"},
    )
    assert rec["actual_cost"] is None
    assert rec["provider_usage_cost"] == {"amount": 0.1785, "currency": "CNY"}
    rec = media_tasks.record_settlement(
        tmp_path, rec["id"], 0.21, "CNY", source="provider_backend",
        note="backend invoice: 0.21 CNY",
    )
    assert rec["actual_cost"] == {"amount": 0.21, "currency": "CNY"}
    assert rec["settled_cost"] == {"amount": 0.21, "currency": "CNY"}
    assert rec["provider_usage_cost"] == {"amount": 0.1785, "currency": "CNY"}
    assert rec["cost_status"] == "settled"
    assert rec["cost_source"] == "provider_backend"
    info = media_tasks.resume_info(tmp_path, rec["id"])
    assert info["settled_cost"] == {"amount": 0.21, "currency": "CNY"}
    assert info["provider_usage_cost"] == {"amount": 0.1785, "currency": "CNY"}
    assert info["cost_status"] == "settled"


def test_legacy_provider_usage_is_not_promoted_to_actual_cost(tmp_path):
    rec = media_tasks.create(tmp_path, kind="video", model="zhenzhen-video-muse")
    p = media_tasks.root(tmp_path) / (rec["id"] + ".json")
    data = json.loads(p.read_text(encoding="utf-8"))
    data["usage"] = {"amount": 0.1785, "currency": "CNY"}
    data["actual_cost"] = {"amount": 0.1785, "currency": "CNY"}
    data["cost_source"] = "provider"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    out = media_tasks.get(tmp_path, rec["id"])
    assert out["actual_cost"] is None
    assert out["provider_usage_cost"] == {"amount": 0.1785, "currency": "CNY"}
    assert out["cost_status"] == "provisional"


def test_settlement_rejects_invalid_amounts(tmp_path):
    rec = media_tasks.create(tmp_path, kind="video", model="zhenzhen-video-muse")
    with pytest.raises(media_tasks.MediaTaskError, match="结算金额"):
        media_tasks.record_settlement(tmp_path, rec["id"], -0.01, "CNY")
