# -*- coding: utf-8 -*-
"""assistant.py —— 对话模式（把一句话变成「回答 + 一个白名单动作」）

设计上刻意只做两件事
--------------------
1. **读**：把当前工作台状态压成一段短上下文喂给模型；
2. **提案**：模型可以建议「跳到某个页面」或「执行某条命令」，但**服务端不执行任何东西**。

为什么要这么分：让模型直接调接口看起来更"智能"，但一次幻觉就可能删文件或花钱。
现在的边界是——模型只能**说**，按键永远由人来按（前端弹确认，走的是原有那套门禁）。

安全边界
--------
* route 白名单写死在前端页面清单里，模型给别的就丢弃；
* command 只允许**流水线已登记的无计费命令**（`pipeline.STAGE_MAP` 里那些），
  计费/写盘的一律不进白名单 —— 不是靠提示词约束，是代码里过滤；
* 模型输出不是 JSON 也不报错：整段当回复，动作置空（宁可少做，不要瞎做）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import adapters, paths, pipeline
from .llm import gateway as llm_gateway

ROUTES = [
    "workbench", "projects", "overview", "pipeline", "creation", "assets",
    "storyboard", "post", "release", "tasks", "cost", "models",
    "connections", "health", "settings",
]


def allowed_commands() -> list:
    """只开放流水线里那些「免费且语义明确」的命令。

    刻意**不含** `assets.rh` / `video.run` 之类计费命令：它们要预算与二次确认，
    不适合由一句话触发。想跑这些，走流水线页面的按钮。
    """
    return sorted({str(spec["cmd"]) for spec in pipeline.STAGE_MAP.values()})


def _summarize(ws) -> str:
    lines = []
    if not ws:
        lines.append("当前没有选中项目（用户可能还没打开任何剧）。")
        return "\n".join(lines)
    p = Path(ws)
    lines.append("当前项目：%s（%s）" % (p.name, ws))
    try:
        wf = adapters.norm_workflow(adapters.workflow_status(ws))
        stages = wf.get("stages") or []
        done = [s for s in stages if s.get("ok")]
        lines.append("流程：%d/%d 环节已完成；当前停在 %s"
                     % (len(done), len(stages), wf.get("current") or "未知"))
        nxt = next((s for s in stages if not s.get("ok")), None)
        if nxt:
            why = (nxt.get("reason") or "").strip()
            lines.append("下一步：%s%s" % (nxt.get("label") or nxt.get("name") or "",
                                          ("（缺：%s）" % why[:60]) if why else ""))
        todo = [s.get("label") or s.get("name") for s in stages if not s.get("ok")]
        if todo:
            lines.append("未完成环节：%s" % "、".join([str(x) for x in todo[:6]]))
    except Exception as exc:                                    # noqa: BLE001
        lines.append("流程状态读不到：%s" % exc)
    lines.append("可执行命令（仅这些能出现在 action.command 里）：%s"
                 % "、".join(allowed_commands()))
    return "\n".join(lines)


def _strip_fence(text: str) -> str:
    t = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    return (m.group(1) if m else t).strip()


def _normalize_action(raw, cmds) -> dict:
    """把模型给的动作收进白名单；不合法就退化成 none（并在 why 里说明）。"""
    if not isinstance(raw, dict):
        return {"type": "none"}
    t = str(raw.get("type") or "none").lower()
    if t == "navigate":
        route = str(raw.get("route") or "").strip().lstrip("#/")
        if route in ROUTES:
            return {"type": "navigate", "route": route, "why": str(raw.get("why") or "")[:120]}
        return {"type": "none", "why": "模型建议跳到未知页面 %r，已忽略" % route}
    if t == "run":
        cmd = str(raw.get("command") or "").strip()
        if cmd in cmds:
            stage = next((sid for sid, spec in pipeline.STAGE_MAP.items()
                          if spec["cmd"] == cmd), "")
            return {"type": "run", "command": cmd, "stage": stage,
                    "args": raw.get("args") if isinstance(raw.get("args"), dict) else {},
                    "why": str(raw.get("why") or "")[:120]}
        return {"type": "none", "why": "模型建议执行未授权命令 %r，已忽略" % cmd}
    return {"type": "none"}


def chat(message: str, *, ws=None, history=None) -> dict:
    msg = str(message or "").strip()
    if not msg:
        return {"ok": False, "reply": "说点什么吧。", "action": {"type": "none"}}
    if len(msg) > 2000:
        return {"ok": False, "reply": "这句话太长了（超过 2000 字），拆成几问吧。",
                "action": {"type": "none"}}

    hist = []
    for h in (history or [])[-6:]:
        if isinstance(h, dict) and h.get("role") in ("user", "assistant"):
            hist.append("%s：%s" % ("用户" if h["role"] == "user" else "你",
                                    str(h.get("text") or "")[:300]))
    cmds = allowed_commands()

    res = llm_gateway.get_gateway().complete("assistant.chat", {
        "context": _summarize(ws),
        "history": "\n".join(hist) or "（无）",
        "message": msg,
    }, project=ws)

    if not res.get("ok"):
        err = (res.get("error") or {}).get("message") or "模型调用失败"
        return {"ok": False, "reply": "现在问不了模型：%s" % err,
                "action": {"type": "none"},
                "error": res.get("error"), "simulated": bool(res.get("simulated"))}

    raw = _strip_fence(res.get("text") or "")
    data = None
    try:
        data = json.loads(raw)
    except ValueError:
        # 模型没按 JSON 回：整段当回答，不做动作（宁愿少做）
        return {"ok": True, "reply": raw[:1200] or "（模型没有返回内容）",
                "action": {"type": "none"}, "parsed": False,
                "simulated": bool(res.get("simulated")), "usage": res.get("usage")}

    reply = str(data.get("reply") or "").strip()[:2000]
    action = _normalize_action(data.get("action"), cmds)
    return {"ok": True, "reply": reply or "（模型没有给出说明）", "action": action,
            "parsed": True, "simulated": bool(res.get("simulated")),
            "provider": res.get("provider"), "usage": res.get("usage"),
            "request_id": res.get("request_id")}
