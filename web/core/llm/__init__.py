# -*- coding: utf-8 -*-
"""LLM 服务层（统一网关 + 配置存储 + 创作闭环）

对外只需要三个入口：
    from core.llm import gateway, store, drafts
    gw = gateway.get_gateway()
    res = gw.complete("script.generate", {...})

分层：
  errors    错误分类（kind + 是否可重试）
  schema    极简 JSON Schema 校验
  safety    Key 打码 / SSRF / 文本脱敏
  store     配置、密钥保险箱、用量日志
  templates 仓库提示词的注册表 + 用途路由 + 输出 Schema
  providers 协议适配（OpenAI 兼容 / Ollama / Mock）
  gateway   编排：能力校验 → 渲染 → 调用 → 解析 → 校验 → 记用量
  drafts    剧本草稿 → 人工编辑 → 确认落盘
"""
from . import drafts, gateway, providers, schema, store, templates  # noqa: F401
from .errors import LLMError  # noqa: F401

__all__ = ["drafts", "gateway", "providers", "schema", "store", "templates", "LLMError"]
