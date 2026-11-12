# -*- coding: utf-8 -*-
"""生成模型的参数能力目录加载与校验。

真源：`configs/generation-models.json`。Web 与后续媒体执行器共享同一份参数契约，
避免 UI 说支持 1080p、执行器却只认 720p 这类分叉。

模型能力按 model 维度维护，不能只看 provider。同一个中转站下不同模型的参数完全不同；
Muse 的 720p/2–10 秒限制属于模型本身，不能写成全局视频规则。
"""
from __future__ import annotations

import copy
import json
import re

from . import paths

PROFILES_FILE = paths.CONFIGS_DIR / "generation-models.json"


class ModelProfileError(ValueError):
    """参数不在模型允许范围内；给 UI 直接展示，不提交外部任务。"""


def _load() -> dict:
    try:
        data = json.loads(PROFILES_FILE.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise ModelProfileError("模型能力目录缺失：%s" % PROFILES_FILE) from exc
    except json.JSONDecodeError as exc:
        raise ModelProfileError("模型能力目录不是合法 JSON：%s" % exc) from exc
    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, dict) or not models:
        raise ModelProfileError("模型能力目录缺少 models 对象")
    return models


def list_profiles(kind=None):
    """返回模型能力目录副本，可按 image / video 过滤。"""
    k = str(kind or "").strip().lower()
    return [copy.deepcopy(p) for p in _load().values() if not k or p.get("kind") == k]


def get_profile(model_id: str) -> dict:
    model = str(model_id or "").strip()
    profile = _load().get(model)
    if not profile:
        raise ModelProfileError("未登记的生成模型：%s" % (model or "（空）"))
    return copy.deepcopy(profile)


def _enum(values, value, default, label):
    raw = default if value is None or value == "" else value
    normalized = str(raw).strip().lower()
    allowed = [str(v).lower() for v in values]
    if normalized not in allowed:
        raise ModelProfileError("%s %s 不支持；可选：%s" % (label, raw, "、".join(values)))
    return normalized


def _boolean(value, default, label):
    if value is None or value == "":
        return bool(default)
    if isinstance(value, bool):
        return value
    raw = str(value).strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    raise ModelProfileError("%s 必须是 true / false" % label)


def _duration(value, spec):
    raw = spec["default"] if value is None or value == "" else value
    if isinstance(raw, bool) or not re.fullmatch(r"\d+", str(raw).strip()):
        raise ModelProfileError("时长必须是整数秒")
    seconds = int(str(raw).strip())
    if seconds < int(spec["min"]) or seconds > int(spec["max"]):
        raise ModelProfileError("时长 %s 秒超出范围：%s–%s 秒"
                                % (seconds, spec["min"], spec["max"]))
    return seconds


def normalize_params(model_id: str, values=None, *, has_references=False) -> dict:
    """校验用户参数并映射为平台请求字段。

    返回的 `api` 只包含生成控制参数；prompt、images 等由调用方补充。
    """
    profile = get_profile(model_id)
    vals = values if isinstance(values, dict) else {}
    params = profile.get("parameters") or {}
    normalized = {}
    api = {}

    if profile["kind"] == "image":
        normalized["resolution"] = _enum(
            params["resolution"]["values"], vals.get("resolution"),
            params["resolution"]["default"], "分辨率")
        normalized["aspect_ratio"] = _enum(
            params["aspect_ratio"]["values"], vals.get("aspect_ratio"),
            params["aspect_ratio"]["default"], "宽高比")
        normalized["quality"] = _enum(
            params["quality"]["values"], vals.get("quality"),
            params["quality"]["default"], "质量")
        normalized["output_format"] = _enum(
            params["output_format"]["values"], vals.get("output_format"),
            params["output_format"]["default"], "输出格式")
        normalized["gif_mode"] = _boolean(
            vals.get("gif_mode"), params["gif_mode"]["default"], "GIF 模式")
        if normalized["gif_mode"]:
            normalized["output_format"] = "gif"
            normalized["aspect_ratio"] = "auto"
            if has_references:
                raise ModelProfileError("GIF 模式仅支持文生图，不能传参考图")
        elif normalized["output_format"] == "svg" and has_references:
            raise ModelProfileError("SVG 模式仅支持文生图，不能传参考图")
        api.update({
            "resolution": normalized["resolution"],
            "size": normalized["aspect_ratio"],
            "quality": normalized["quality"],
            "output_format": normalized["output_format"],
            "n": 1,
        })
        if normalized["output_format"] == "svg":
            api["svg"] = {"model": "gpt-5.4-mini"}

    elif profile["kind"] == "video":
        normalized["aspect_ratio"] = _enum(
            params["aspect_ratio"]["values"], vals.get("aspect_ratio"),
            params["aspect_ratio"]["default"], "宽高比")
        normalized["resolution"] = _enum(
            params["resolution"]["values"], vals.get("resolution"),
            params["resolution"]["default"], "分辨率")
        normalized["duration"] = _duration(vals.get("duration"), params["duration"])
        api.update({
            "resolution": normalized["resolution"],
            "duration": normalized["duration"],
            "audio": True,
        })
        if normalized["aspect_ratio"] == "auto":
            api["size"] = "auto"
        else:
            api["aspect_ratio"] = normalized["aspect_ratio"]

    return {
        "ok": True,
        "model": profile["id"],
        "kind": profile["kind"],
        "protocol": profile["protocol"],
        "profile": profile,
        "values": normalized,
        "api": api,
    }
