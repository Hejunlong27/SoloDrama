# -*- coding: utf-8 -*-
"""模型级生成参数目录的离线测试。"""
from __future__ import annotations

import sys
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB))

import pytest  # noqa: E402

from core import generation_models  # noqa: E402


def test_catalog_contains_only_requested_models():
    items = generation_models.list_profiles()
    ids = {x["id"] for x in items}
    assert ids == {"zhenzhen-image-g-v2.6-lowprice", "zhenzhen-video-muse", "minimax-h3-comfyui-max"}


def test_image_defaults_and_custom_controls():
    defaults = generation_models.normalize_params("zhenzhen-image-g-v2.6-lowprice")
    assert defaults["values"] == {
        "resolution": "1k", "aspect_ratio": "auto", "quality": "auto",
        "output_format": "png", "gif_mode": False,
    }
    assert defaults["api"]["size"] == "auto"
    assert defaults["api"]["n"] == 1

    custom = generation_models.normalize_params(
        "zhenzhen-image-g-v2.6-lowprice",
        {"resolution": "2K", "aspect_ratio": "9:16", "quality": "high",
         "output_format": "webp"},
    )
    assert custom["api"] == {
        "resolution": "2k", "size": "9:16", "quality": "high",
        "output_format": "webp", "n": 1,
    }


def test_image_gif_mode_is_text_only_and_forces_auto():
    result = generation_models.normalize_params(
        "zhenzhen-image-g-v2.6-lowprice",
        {"gif_mode": True, "aspect_ratio": "9:16"},
    )
    assert result["api"]["output_format"] == "gif"
    assert result["api"]["size"] == "auto"
    with pytest.raises(generation_models.ModelProfileError, match="仅支持文生图"):
        generation_models.normalize_params(
            "zhenzhen-image-g-v2.6-lowprice", {"gif_mode": True}, has_references=True)


def test_video_defaults_and_adjustable_duration_resolution():
    defaults = generation_models.normalize_params("zhenzhen-video-muse")
    assert defaults["values"] == {
        "aspect_ratio": "auto", "resolution": "720p", "duration": 10,
    }
    assert defaults["api"] == {"resolution": "720p", "duration": 10,
                               "audio": True, "size": "auto"}

    custom = generation_models.normalize_params(
        "zhenzhen-video-muse", {"aspect_ratio": "9:16", "resolution": "720p", "duration": 5})
    assert custom["api"] == {"resolution": "720p", "duration": 5,
                             "audio": True, "aspect_ratio": "9:16"}


def test_video_rejects_out_of_range_values():
    with pytest.raises(generation_models.ModelProfileError, match="2–10"):
        generation_models.normalize_params("zhenzhen-video-muse", {"duration": 11})
    with pytest.raises(generation_models.ModelProfileError, match="720p"):
        generation_models.normalize_params("zhenzhen-video-muse", {"resolution": "1080p"})


def test_model_params_endpoint_is_read_only():
    from fastapi.testclient import TestClient
    from app import app

    client = TestClient(app, base_url="http://127.0.0.1")
    res = client.post("/api/generators/model-params", json={
        "model": "zhenzhen-video-muse",
        "params": {"aspect_ratio": "9:16", "resolution": "720p", "duration": 5},
    })
    assert res.status_code == 200
    body = res.json()
    assert body["api"] == {"resolution": "720p", "duration": 5,
                           "audio": True, "aspect_ratio": "9:16"}


def test_minimax_h3_defaults_and_limits():
    defaults = generation_models.normalize_params("minimax-h3-comfyui-max")
    assert defaults["values"] == {"aspect_ratio": "9:16", "resolution": "1088p", "duration": 6}
    assert defaults["api"] == {"resolution": "1088p", "duration": 6,
                               "audio": True, "aspect_ratio": "9:16"}
    custom = generation_models.normalize_params(
        "minimax-h3-comfyui-max", {"resolution": "480p", "duration": 15})
    assert custom["api"]["resolution"] == "480p"
    assert custom["api"]["duration"] == 15
    with pytest.raises(generation_models.ModelProfileError, match="3\u201315"):
        generation_models.normalize_params("minimax-h3-comfyui-max", {"duration": 16})
