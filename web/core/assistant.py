# -*- coding: utf-8 -*-
"""assistant.py —— 对话模式（把一句话变成「回答 + 一个白名单动作」）

设计上刻意只做两件事
--------------------
1. **读**：把当前工作台状态压成一段短上下文喂给模型；
2. **提案**：模型可以建议「跳到某个页面」或「执行某条命令」，但**服务端不执行任何东西**。

为什么要这么分：让模型直接调接口看起来更"智能"，但一次幻觉就可能删文件或花钱。
现在的边界是——模型只能**说**，按键永远由人来按（前端弹确认，走的是原有那套门禁）。

引导也在这层
------------
* `welcome()`：打开抽屉时的问候 + 可点的下一步（**不调模型**，按状态拼）；
* `goto_hint()`：按「第一个未完成环节」推一个「去 XX」—— 模型只回答时用户也有路可走；
* `suggestions`：模型给的「接着问」候选，服务端归一化后由前端画成 chips。

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
from .llm import store as llm_store

ROUTES = [
    "workbench", "projects", "overview", "pipeline", "creation", "assets",
    "storyboard", "post", "release", "tasks", "cost", "models",
    "connections", "health", "settings",
]

# 页面 → 中文名（引导语与「带我去 X」按钮都用这一份，避免前端各写一套）
PAGE_LABEL = {
    "workbench": "工作台", "projects": "项目管理", "overview": "项目详情",
    "pipeline": "流水线", "creation": "创作中心", "assets": "资产中心",
    "storyboard": "分镜与视频", "post": "后期制作", "release": "发行中心",
    "tasks": "任务中心", "cost": "成本中心", "models": "AI 模型中心",
    "connections": "连接中心", "health": "环境体检", "settings": "系统设置",
}

# 环节 → 该去的页面（模型报「卡在哪」时要能顺手带路）
STAGE_PAGE = {
    "S1": "creation", "S2": "creation", "S3": "assets", "S4": "assets",
    "S5": "storyboard", "S6": "storyboard", "S7": "release",
    "S8": "post", "S9": "post", "S10": "post", "S11": "release",
}

# 项目级页面：没有打开项目时不可用，引导时要说明
PROJECT_ROUTES = {"overview", "pipeline", "creation", "assets",
                  "storyboard", "post", "release"}


def allowed_commands() -> list:
    """只开放流水线里那些「免费且语义明确」的命令。

    刻意**不含** `assets.rh` / `video.run` 之类计费命令：它们要预算与二次确认，
    不适合由一句话触发。想跑这些，走流水线页面的按钮。
    """
    return sorted({str(spec["cmd"]) for spec in pipeline.STAGE_MAP.values()})


def _model_brief() -> dict:
    """对话现在用的是谁（给模型看的 context 和给用户看的页脚共用一份判断）。"""
    try:
        spec = llm_store.get_purpose("assistant.chat")
        pid = str(spec.get("provider_id") or "")
        if not pid:
            return {"name": "", "kind": "", "simulated": True, "label": "未接模型"}
        prov = llm_store.get_provider(pid) or {}
        kind = str(prov.get("kind") or "")
        name = str(spec.get("provider_name") or pid)
        if kind == "mock":
            return {"name": name, "kind": kind, "simulated": True, "label": "%s（离线演练）" % name}
        return {"name": name, "kind": kind, "simulated": False,
                "label": "%s（%s）" % (name, "本地模型" if prov.get("local") else "云端")}
    except Exception as exc:                                    # noqa: BLE001
        return {"name": "", "kind": "", "simulated": True, "label": "状态读不到：%s" % exc}


def _llm_line() -> str:
    """当前对话走的是真模型还是离线演练 —— 模型自己该知道，否则会假装很聪明。"""
    b = _model_brief()
    if b["simulated"]:
        return ("对话模型：%s。请引导用户去「AI 模型中心」接一个真模型，"
                "并且不要假装能给出精确分析。" % b["label"])
    return "对话模型：%s" % b["label"]


def _summarize(ws) -> str:
    lines = [_llm_line()]
    if not ws:
        lines.append("当前没有选中项目（用户还没打开任何剧）。")
        lines.append("项目级页面现在不可用：%s；引导时先让他打开或新建一部剧。"
                     % "、".join(PAGE_LABEL[r] for r in
                                [r for r in ROUTES if r in PROJECT_ROUTES]))
        lines.append("可执行命令：无（要先打开项目）")
        return "\n".join(lines)
    p = Path(ws)
    lines.append("当前项目：%s（%s）" % (p.name, ws))
    try:
        wf = adapters.norm_workflow(adapters.workflow_status(ws))
        stages = wf.get("stages") or []
        done = [s for s in stages if s.get("ok")]
        cur = wf.get("current") or "未知"
        lines.append("流程：%d/%d 环节已完成；当前停在 %s（对应页面：%s）"
                     % (len(done), len(stages), cur,
                        PAGE_LABEL.get(STAGE_PAGE.get(str(cur), ""), "项目详情")))
        nxt = next((s for s in stages if not s.get("ok")), None)
        if nxt:
            why = (nxt.get("reason") or "").strip()
            sid = str(nxt.get("id") or "")
            lines.append("下一步：%s%s（对应页面：%s）"
                         % (nxt.get("label") or nxt.get("name") or "",
                            ("（缺：%s）" % why[:60]) if why else "",
                            PAGE_LABEL.get(STAGE_PAGE.get(sid), "项目详情")))
        todo = [s.get("label") or s.get("name") for s in stages if not s.get("ok")]
        if todo:
            lines.append("未完成环节：%s" % "、".join([str(x) for x in todo[:6]]))
    except Exception as exc:                                    # noqa: BLE001
        lines.append("流程状态读不到：%s" % exc)
    lines.append("可执行命令（仅这些能出现在 action.command 里）：%s"
                 % "、".join("%s %s（%s）" % (sid, spec["cmd"], spec.get("mode_text") or "")
                            for sid, spec in sorted(pipeline.STAGE_MAP.items())
                            if spec.get("cmd") in allowed_commands()))
    return "\n".join(lines)


def _strip_fence(text: str) -> str:
    t = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    return (m.group(1) if m else t).strip()


def _norm_suggestions(raw, limit: int = 3) -> list:
    """模型给的「接着问」候选：去空、去重、限长。不合法就返回空（由调用方兜底）。"""
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return []
    out = []
    for x in raw:
        t = str(x or "").strip().replace("\n", " ")
        if not t or len(t) > 40 or t in out:
            continue
        out.append(t)
    return out[:limit]


def _stage_suggestions(ws) -> list:
    """按当前卡点生成「接着问」候选 —— 模型不给 suggestions 时用这组兜底。"""
    base = ["现在卡在哪一步？"]
    if not ws:
        return ["怎么新建一部剧？", "我的环境有什么问题？", "出片大概要花多少钱？"]
    try:
        wf = adapters.norm_workflow(adapters.workflow_status(ws))
        stages = wf.get("stages") or []
        nxt = next((s for s in stages if not s.get("ok")), None)
        if nxt:
            name = str(nxt.get("label") or nxt.get("name") or "")
            if name:
                base.append("「%s」要准备什么？" % name[:12])
        else:
            base.append("发布前还要检查什么？")
    except Exception:                                           # noqa: BLE001
        base.append("下一步该做什么？")
    base.append("哪一步要花钱？")
    return base[:3]


def welcome(ws=None) -> dict:
    """助手打开时的引导语（不发模型、不花钱）。

    为什么要单独一条：新用户拉开抽屉看到一片空白只会问「你能干啥」。
    这里的每一句都按**当前状态**生成，点一下就能继续，用户不用想怎么提问。
    """
    proj = Path(ws).name if ws else ""
    tips = [
        "我只读状态、只给建议；花钱和写盘的按钮永远由你按。",
        "问「现在到哪一步」「下一步做什么」最省事，也可以让我带你去某个页面。",
    ]
    if not ws:
        greeting = "我在这儿。现在还没有打开剧 —— 可以先建一部，或者让我看看你的机器准备得怎么样。"
    else:
        greeting = "《%s》已经打开了。想知道卡在哪、下一步点哪，直接问。" % proj
        try:
            wf = adapters.norm_workflow(adapters.workflow_status(ws))
            stages = wf.get("stages") or []
            done = len([s for s in stages if s.get("ok")])
            nxt = next((s for s in stages if not s.get("ok")), None)
            if nxt:
                greeting = ("《%s》已完成 %d/%d，停在 %s。要我看看缺什么吗？"
                            % (proj, done, len(stages),
                               str(nxt.get("label") or nxt.get("name") or "")))
            elif stages:
                greeting = "《%s》%d 个环节都过了。要检查发行资料、还是看成本？" % (proj, done)
        except Exception:                                       # noqa: BLE001
            pass
    sugg = _stage_suggestions(ws)
    model = _model_brief()
    if model.get("simulated"):
        sugg = ["怎么接一个大模型？"] + [s for s in sugg if "模型" not in s][:2]
        tips.append("现在跑的是离线演练，回答是模板；去「AI 模型中心」接上真模型才准。")
    return {"greeting": greeting, "tips": tips, "suggestions": sugg,
            "project": proj, "model": model.get("label") or "",
            "pages": [{"id": r, "label": PAGE_LABEL[r]} for r in ROUTES]}


def _normalize_action(raw, cmds) -> dict:
    """把模型给的动作收进白名单；不合法就退化成 none（并在 why 里说明）。"""
    if not isinstance(raw, dict):
        return {"type": "none"}
    t = str(raw.get("type") or "none").lower()
    if t == "navigate":
        route = str(raw.get("route") or "").strip().lstrip("#/")
        if route in ROUTES:
            return {"type": "navigate", "route": route, "label": PAGE_LABEL.get(route, route),
                    "why": str(raw.get("why") or "")[:120]}
        return {"type": "none", "why": "模型建议跳到未知页面 %r，已忽略" % route}
    if t == "run":
        cmd = str(raw.get("command") or "").strip()
        if cmd in cmds:
            stage = next((sid for sid, spec in pipeline.STAGE_MAP.items()
                          if spec["cmd"] == cmd), "")
            spec = pipeline.STAGE_MAP.get(stage) or {}
            return {"type": "run", "command": cmd, "stage": stage,
                    "label": spec.get("mode_text") or cmd,
                    "args": raw.get("args") if isinstance(raw.get("args"), dict) else {},
                    "why": str(raw.get("why") or "")[:120]}
        return {"type": "none", "why": "模型建议执行未授权命令 %r，已忽略" % cmd}
    return {"type": "none"}


def goto_hint(ws) -> dict:
    """按状态推一个「去 XX」按钮 —— 不靠模型，也就不会幻觉。

    为什么需要：用户问「现在卡在哪」时，按规则模型不该给动作（只回答）。
    但产品上这句话的下一个动作永远是明确的：去卡住的那个页面。
    这一条由服务端算，模型给不给动作都不影响用户有路可走。
    """
    if not ws:
        return {"route": "projects", "label": PAGE_LABEL["projects"],
                "why": "还没有打开项目"}
    try:
        wf = adapters.norm_workflow(adapters.workflow_status(ws))
        stages = wf.get("stages") or []
        if not stages:
            return {}                       # 状态读不到就别硬指路
        nxt = next((s for s in stages if not s.get("ok")), None)
        if not nxt:
            return {"route": "release", "label": PAGE_LABEL["release"],
                    "why": "环节都过了，剩下发行资料与定稿"}
        sid = str(nxt.get("id") or "")
        route = STAGE_PAGE.get(sid) or "pipeline"
        name = str(nxt.get("label") or nxt.get("name") or sid)
        return {"route": route, "label": PAGE_LABEL[route],
                "why": "卡在「%s」" % name}
    except Exception:                                           # noqa: BLE001
        return {}


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
                "action": {"type": "none"}, "goto": goto_hint(ws),
                "suggestions": _stage_suggestions(ws),
                "error": res.get("error"), "simulated": bool(res.get("simulated"))}

    raw = _strip_fence(res.get("text") or "")
    data = None
    try:
        data = json.loads(raw)
    except ValueError:
        # 模型没按 JSON 回：整段当回答，不做动作（宁愿少做）
        return {"ok": True, "reply": raw[:1200] or "（模型没有返回内容）",
                "action": {"type": "none"}, "parsed": False, "goto": goto_hint(ws),
                "suggestions": _stage_suggestions(ws),
                "simulated": bool(res.get("simulated")), "usage": res.get("usage")}

    reply = str(data.get("reply") or "").strip()[:2000]
    action = _normalize_action(data.get("action"), cmds)
    suggestions = _norm_suggestions(data.get("suggestions")) or _stage_suggestions(ws)
    return {"ok": True, "reply": reply or "（模型没有给出说明）", "action": action,
            "goto": goto_hint(ws), "suggestions": suggestions,
            "parsed": True, "simulated": bool(res.get("simulated")),
            "provider": res.get("provider"), "usage": res.get("usage"),
            "request_id": res.get("request_id")}
