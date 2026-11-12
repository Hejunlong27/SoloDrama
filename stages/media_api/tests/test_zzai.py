# -*- coding: utf-8 -*-
"""ZZAI 媒体客户端的本地 Mock 测试（零外网、零费用）。"""
from __future__ import annotations

import json

import httpx
import pytest

from stages.media_api.zzai import ZZAIClient, ZZAIError


def client(handler):
    return ZZAIClient(base_url="http://127.0.0.1:9", key="sk-test-secret",
                      transport=httpx.MockTransport(handler), timeout=5)


def test_wallet_models_and_estimate_paths():
    calls = []

    def handler(req):
        calls.append(req)
        assert req.headers["authorization"] == "Bearer sk-test-secret"
        if req.url.path == "/api/usage/wallet/":
            return httpx.Response(200, json={"data": {"amount": 3.0, "display_type": "CNY"}})
        if req.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "zhenzhen-video-muse"}]})
        if req.url.path == "/v1/video/generations/estimate":
            return httpx.Response(200, json={"object": "price_estimate", "amount": 0.1,
                                             "currency": "CNY", "estimate_available": True})
        return httpx.Response(404, json={"message": "not found"})

    c = client(handler)
    assert c.wallet()["data"]["amount"] == 3.0
    assert c.models()["data"][0]["id"] == "zhenzhen-video-muse"
    est = c.estimate("video", {"model": "zhenzhen-video-muse", "duration": 5})
    assert est["amount"] == 0.1
    assert [x.url.path for x in calls] == [
        "/api/usage/wallet/", "/v1/models", "/v1/video/generations/estimate"]


def test_upload_reference_image(tmp_path):
    seen = {}

    def handler(req):
        seen["path"] = req.url.path
        seen["auth"] = req.headers.get("authorization")
        seen["ctype"] = req.headers.get("content-type")
        return httpx.Response(200, json={"url": "https://cdn.example/ref.png",
                                         "file_type": "image", "size": 3})

    p = tmp_path / "ref.png"
    p.write_bytes(b"png")
    out = client(handler).upload(p)
    assert out == "https://cdn.example/ref.png"
    assert seen["path"] == "/v1/files/upload"
    assert seen["auth"] == "Bearer sk-test-secret"
    assert seen["ctype"].startswith("multipart/form-data; boundary=")


def test_submit_requires_authorization_and_sends_max_cost():
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(200, json={"id": "task_1", "status": "queued"})

    c = client(handler)
    with pytest.raises(ZZAIError, match="authorized=True"):
        c.submit("video", {"model": "zhenzhen-video-muse"})
    assert calls == []

    out = c.submit("video", {"model": "zhenzhen-video-muse", "duration": 5},
                   max_cost=0.2, authorized=True)
    assert out["task_id"] == "task_1"
    assert out["status"] == "queued"
    assert calls[0].headers["x-max-cost"] == "0.2"
    assert calls[0].url.path == "/v1/video/generations"


def test_poll_video_success_and_cost():
    def handler(req):
        return httpx.Response(200, json={
            "id": "task_1", "status": "completed", "progress": 100,
            "metadata": {"url": "https://cdn.example/out.mp4"},
            "usage": {"amount": 1.23, "currency": "CNY"},
        })

    out = client(handler).poll("video", "task_1")
    assert out["status"] == "succeeded"
    assert out["result_url"] == "https://cdn.example/out.mp4"
    assert out["usage"]["amount"] == 1.23


def test_poll_image_success_and_failure_refund():
    state = {"status": "SUCCESS"}

    def handler(req):
        if state["status"] == "SUCCESS":
            return httpx.Response(200, json={"code": "success", "data": {
                "status": "SUCCESS", "progress": "100%",
                "result_url": "https://cdn.example/out.png",
                "usage": {"amount": 0.044, "currency": "CNY"},
            }})
        return httpx.Response(200, json={"code": "success", "data": {
            "status": "FAILURE", "fail_reason": "upstream failed",
            "usage": {"amount": 0.0, "currency": "CNY"},
        }})

    c = client(handler)
    ok = c.poll("image", "img_1")
    assert ok["status"] == "succeeded"
    assert ok["result_urls"] == ["https://cdn.example/out.png"]
    state["status"] = "FAILURE"
    bad = c.poll("image", "img_1")
    assert bad["status"] == "failed"
    assert bad["error"] == "upstream failed"
    assert bad["usage"]["amount"] == 0


def test_download_writes_file(tmp_path):
    def handler(req):
        assert req.url.host == "cdn.example"
        return httpx.Response(200, content=b"fake-mp4-bytes")

    out = client(handler).download("https://cdn.example/out.mp4", tmp_path / "out.mp4")
    assert out["bytes"] == len(b"fake-mp4-bytes")
    assert (tmp_path / "out.mp4").read_bytes() == b"fake-mp4-bytes"


def test_error_does_not_echo_key():
    def handler(req):
        return httpx.Response(401, json={"error": {"message": "bad key sk-test-secret"}})

    with pytest.raises(ZZAIError) as exc:
        client(handler).wallet()
    assert "sk-test-secret" not in str(exc.value)
    assert "[已隐藏]" in str(exc.value)
