# -*- coding: utf-8 -*-
"""LLM 层的错误分类（唯一真源）

设计约束：
  * 前端只看到**分类 + 人话**，看不到堆栈与原始请求；
  * 每类都带 `retryable`，网关的重试决策只读这个标志，不在调用点各自判断；
  * 报错文本一律过 `safety.scrub`，防止服务端把 Key 回显进错误体。
"""
from __future__ import annotations

# kind -> (人话, 是否可重试)
KINDS = {
    "config": ("配置不完整或不可用", False),
    "auth": ("鉴权失败：Key 无效、过期或无权限", False),
    "model_not_found": ("模型不存在，或当前 Key 无权访问该模型", False),
    "rate_limit": ("触发限流，请稍后再试", True),
    "quota": ("额度或余额不足", False),
    "timeout": ("请求超时", True),
    "network": ("无法连接到服务端点", True),
    "server": ("服务端错误", True),
    "protocol": ("端点响应不符合预期协议（可能不是 OpenAI 兼容接口）", False),
    "bad_request": ("请求参数不被该模型接受", False),
    "unsupported": ("当前模型能力不满足该用途的要求", False),
    # ★ 2026-10-28 新增两类：推理模型（DeepSeek flash/pro 等）把「思考」也算进 max_tokens，
    #   额度给小了会表现为「HTTP 200 但 content 为空」。旧口径会把这种情况报成
    #   parse（「输出不是合法 JSON」），用户完全不知道该调大额度。
    "truncated": ("输出被 max_tokens 截断（推理模型的思考过程也占额度），请把 max_tokens 调大后重试", False),
    "empty": ("模型返回了空内容：可能是额度被思考吃光，或被服务端内容策略拦截", False),
    "schema": ("输出未通过 Schema 校验", False),
    "parse": ("输出不是合法 JSON", False),
    "blocked": ("目标地址被本地安全策略拒绝", False),
    "canceled": ("已取消", False),
    "not_found": ("找不到对象", False),
}

# 允许重试的 kind（★ 只有「确定没产生内容/明确可重复」的才在这里）
RETRYABLE = {"rate_limit", "timeout", "network", "server"}


class LLMError(Exception):
    """LLM 层的统一异常。

    `kind` ∈ KINDS；`status` 是上游 HTTP 状态码（有则记）；`detail` 只进日志不进前端。
    """

    def __init__(self, kind, message="", *, status=None, retryable=None, detail=None):
        self.kind = kind if kind in KINDS else "protocol"
        self.status = status
        self.detail = detail
        self.text = message or KINDS[self.kind][0]
        self.retryable = (self.kind in RETRYABLE) if retryable is None else bool(retryable)
        super().__init__(self.text)

    def to_dict(self):
        return {
            "kind": self.kind,
            "message": self.text,
            "retryable": self.retryable,
            "status": self.status,
        }

    def __repr__(self):  # pragma: no cover - 调试用
        return "LLMError(%s, %r)" % (self.kind, self.text)


def classify_status(status, body=""):
    """HTTP 状态 + 响应体 → 错误分类。

    ★ 为什么还要看 body：不少兼容端点把「模型不存在」和「Key 无效」都回 400/404，
      只按状态码会误判，用户按提示去改 Key 也修不好。
    """
    low = (body or "").lower()
    if status in (401, 403):
        return "auth"
    if status == 429:
        if "quota" in low or "insufficient" in low or "balance" in low:
            return "quota"
        return "rate_limit"
    if status == 404:
        if "model" in low:
            return "model_not_found"
        return "protocol"
    if status in (400, 422):
        if "model" in low and ("not found" in low or "does not exist" in low or "unknown" in low):
            return "model_not_found"
        if "api key" in low or "unauthorized" in low or "authentication" in low:
            return "auth"
        if "does not support" in low or "unsupported" in low:
            return "unsupported"
        return "bad_request"
    if status and status >= 500:
        return "server"
    return "protocol"
