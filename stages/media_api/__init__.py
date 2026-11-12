# -*- coding: utf-8 -*-
"""外部媒体 API 适配器（引擎侧，Web 不 import）。"""

from .zzai import ZZAIClient, ZZAIError  # noqa: F401

__all__ = ["ZZAIClient", "ZZAIError"]
