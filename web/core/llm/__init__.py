# -*- coding: utf-8 -*-
"""LLM 服务层（统一网关 + 配置存储）

★ 2026-11-02（分支 feat/pack-engine）：创作闭环已移出引擎。
  `drafts`（剧本草稿 → 人工编辑 → 确认落盘）随 `stages/creation/` 一起删除；
  `templates` 只保留一个用途 `pack.convert`（把 Skill 产物转成制作包）。

对外入口：
    from core.llm import gateway, store
    gw = gateway.get_gateway()
    res = gw.complete("pack.convert", {"source_dir": ..., "output_dir": ...})

分层：
  errors    错误分类（kind + 是否可重试）
  schema    极简 JSON Schema 校验
  safety    Key 打码 / SSRF / 文本脱敏
  store     配置、密钥保险箱、用量日志
  templates 提示词注册表（只剩 pack.convert）
  providers 协议适配（OpenAI 兼容 / Ollama / Mock）
  gateway   编排：能力校验 → 渲染 → 调用 → 解析 → 校验 → 记用量
"""
from . import gateway, providers, schema, store, templates  # noqa: F401
from .errors import LLMError  # noqa: F401

__all__ = ["gateway", "providers", "schema", "store", "templates", "LLMError"]
