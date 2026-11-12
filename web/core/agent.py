# -*- coding: utf-8 -*-
"""agent.py —— 会动手的助手：对话 → 工具调用 → 真的把片子做出来

为什么要它
----------
页面上每个按钮都能点，但「整部片子」是一条 10 步的路：灵感 → 企划 → 资产 → 剧本 →
导演手册 → 制作包 → 分镜图 → 出片 → 剪辑 → 发行。人得记住每一步在哪一页、缺什么参数。
这个模块把这条路交给模型：它读状态、调工具、汇报，人只需要说「继续」或「第 3 集重来」。

设计取舍
--------
* **不是自由 agent**：工具是白名单（本文件 `TOOLS`），没有 shell、没有任意路径写。
  模型只能调这些函数；每个函数内部再走引擎既有的校验。
* **一轮一动作**：模型每次只回一个 JSON（`tool` + `args` 或 `done`），我们执行完把结果
  回填，再让它决定下一步。比「一次吐一大段计划」可靠：错了能立刻停。
* **写盘只到创作层**：`write_doc` 走 `creation.write`（有备份、有阶段白名单）；
  引擎输入契约 `06-提示词/` **模型碰不到** —— 出片稳定性不交给模型的自觉。
* **GPU 与云端模型要人点头**：`run()` 遇到计费/占 GPU 的命令，除非调用方明确
  `allow_gpu=True`，否则只返回「需要确认」；API 入口还要求 `confirm=true`，避免助手
  在用户不知情时连续调用云端模型。

模型契约（每次回复必须是这个 JSON）
----------------------------------
    {"say": "给用户看的一句话",
     "tool": "run", "args": {"spec_id": "board.frame", "params": {"ep": "ep01"}}}
或
    {"say": "做完了，汇报……", "done": true}
"""
from __future__ import annotations

import json
import re
import time
from . import canvas, commands as CMD, creation, jobs, runner, skills
from .llm import gateway as gw
from .llm.errors import LLMError

MAX_STEPS = 12
MAX_TOKENS = 2400          # 推理模型的思考也计入额度，给小了会「200 + 空内容」

SYSTEM = """你是 SoloDrama 的制片助手。你面对的是一个「AI 短剧批量生产引擎」：
创作层由题材模板（Skill）产出企划案/资产库/剧本/导演手册，引擎负责出图/出片/剪辑/发行。

你的任务：用最少的往返，把用户想要的推进到底（做一步 → 汇报 → 继续），而不是只给建议。

可用工具（只能调这些）：
1. state()                      读当前项目状态：灵感/企划/资产/剧本/导演手册/制作包/各环节产物与通道
2. read_doc(stage)              读创作层产物的全文。stage ∈ plan|assets|script|director
3. write_doc(stage, text)       改写创作层产物（会备份旧版）。**只用于人明确要求改稿时**
4. generate(stage)              让大模型生成该段（企划/资产/剧本/导演手册），成功后自动落盘
5. run(spec_id, params)         执行一条引擎命令（出图/分镜图/出片/剪辑/发行等）
6. job(job_id)                  查后台作业的进度与末几行输出
7. episodes()                   每一集做到哪一步（镜头数/分镜图/段/母版）
8. boards(ep)                   某一集的分镜图情况（缺哪几镜）
9. skills()                     本项目已装的题材模板
10. install_skill(id)           给本项目装一个题材模板（单选，会替换现有的）
11. set_idea(idea, ep_total, ep_seconds)   写一句话灵感（企划案的前置）
12. set_style(text)             写画风锁（style_lock）。只写创作层用的画风描述，
                                正式的三轨规格仍要到「系统设置」确认
13. commands(group)             列可用引擎命令（id / 标题 / 是否占 GPU）

硬规则：
- 回答必须是**一个 JSON 对象**，不要 Markdown、不要代码块围栏。
- 需要动手：{"say":"...","tool":"工具名","args":{...}}
- 收尾：{"say":"汇报（做了什么、结果、下一步）","done":true}
- **不要编造提示词或台词**：内容由模板与大模型产出，你只负责调度与检查。
- 06-提示词/ 下的契约文件由制作包导入生成，你没有任何工具能直接改它。
- 用户没要求时不要一次跑很多步；每步做完说清结果再继续。
- 涉及出片（占 GPU、几十分钟）前，先说清将跑几镜、预计多久。
"""

# 工具说明只给模型看名字与参数，真正执行在 _dispatch
TOOL_DOC = {
    "state": {},
    "set_idea": {"idea": "一句话灵感", "ep_total": "集数（可选）", "ep_seconds": "单集秒数（可选）"},
    "set_style": {"text": "画风描述（写进 project.json 的 style_lock）"},
    "commands": {"group": "可选：只看某一组"},
    "read_doc": {"stage": "plan|assets|script|director"},
    "write_doc": {"stage": "plan|assets|script|director", "text": "全文"},
    "generate": {"stage": "plan|assets|script|director", "extra": "可选：episodes_range / script_ep"},
    "run": {"spec_id": "命令 id（用 state 或列表里看到的）", "params": "对象"},
    "job": {"job_id": "作业 id"},
    "episodes": {},
    "boards": {"ep": "ep01"},
    "skills": {},
    "install_skill": {"id": "模板 id"},
}

# 不允许 agent 调的命令：会改项目结构或删东西
_DENY_SPECS = {"project.scaffold", "graph.reset", "skills.upload"}


# ---------------------------------------------------------------------------
# 模型通道
# ---------------------------------------------------------------------------
def _chat(ws, model, messages, *, max_tokens=MAX_TOKENS) -> dict:
    """所有助手模型调用必须经过 Gateway。

    旧实现直接 `providers.build()`，调用不会进入 usage.jsonl，因而无法按项目
    统计成本、无法做模型对比，也无法统一重试/熔断。这里保留一个薄函数，
    只是把 Agent 的多轮 messages 转交给 Gateway。
    """
    res = gw.get_gateway().chat(
        messages, purpose="agent.chat", route_purpose="create.plan",
        model=model, project=ws, max_tokens=max_tokens, temperature=0.3,
    )
    if not res.get("ok"):
        err = res.get("error") or {}
        raise LLMError(err.get("kind") or "network", err.get("message") or "模型调用失败")
    return res


# ---------------------------------------------------------------------------
# 工具实现
# ---------------------------------------------------------------------------
def _compact_state(ws) -> dict:
    cre = creation.state(ws)
    wf = None
    try:
        from . import adapters
        wf = adapters.norm_workflow(adapters.workflow_status(ws))
    except Exception:                                          # noqa: BLE001
        wf = {"ok": False, "nodes": []}
    inst = skills.installed(ws).get("items") or []
    eps = []
    try:
        s = canvas.series(ws)
        eps = [{"ep": r["ep"], "shots": r["counts"]["total"], "done": r["counts"]["done"],
                "board": r["counts"]["board"], "todo": r["counts"]["todo"]}
               for r in (s.get("rows") or []) if r["counts"]["total"]][:8]
    except Exception:                                          # noqa: BLE001
        eps = []
    comfy = {}
    try:
        from . import comfy_probe
        r = comfy_probe.probe()
        comfy = {"online": bool(r.get("online")), "version": r.get("version") or "",
                 "reason": r.get("reason") or ""}
    except Exception:                                          # noqa: BLE001
        comfy = {"online": None}
    return {
        "idea": {"state": cre["idea"]["state"], "title": cre["idea"].get("title") or "",
                 "eps": cre["idea"].get("ep_total") or 0,
                 "seconds": cre["idea"].get("ep_seconds") or 0,
                 "style_lock": (cre["idea"].get("style_lock") or "")[:60]},
        "docs": [{"stage": s["id"], "state": s["state"], "chars": s.get("chars") or 0}
                 for s in cre.get("stages") or []],
        "pack": {"state": cre["pack"]["state"], "episodes": cre["pack"].get("episodes") or []},
        "skills": [x.get("id") for x in inst],
        "nodes": [{"id": n.get("id"), "state": n.get("state"), "detail": (n.get("detail") or "")[:60]}
                  for n in (wf.get("nodes") or [])],
        "current": wf.get("current"),
        "episodes": eps,
        "comfy": comfy,
    }


def _set_style(ws, text: str) -> dict:
    """写画风锁（创作层口径）。

    只动 `project.json` 的 `meta.style_lock` —— 这是大模型写作时唯一会读的画风字段。
    三轨规格（track/look/交付）不在助手权限内：那决定生产参数，改了要重新过 G-1 门禁。
    """
    import json as _json
    from pathlib import Path as _Path
    txt = (text or "").strip()
    if len(txt) < 6:
        return {"ok": False, "detail": "画风描述太短，至少给一句能落地的话（光线/色彩/质感）"}
    p = _Path(str(ws)) / "project.json"
    doc = {}
    if p.is_file():
        try:
            doc = _json.loads(p.read_text(encoding="utf-8-sig")) or {}
        except (OSError, ValueError):
            doc = {}
    doc.setdefault("meta", {})["style_lock"] = txt[:400]
    if p.is_file():
        bak = p.with_suffix(".json.bak")
        try:
            bak.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
        except OSError:
            pass
    p.write_text(_json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="")
    return {"ok": True, "style_lock": doc["meta"]["style_lock"],
            "detail": "画风锁已写入 project.json（旧文件备份为 project.json.bak）。"
                      "正式的三轨规格仍要到「系统设置」确认"}


def _do_generate(ws, stage: str, extra: dict) -> dict:
    """复用 /api/create/generate 的同一套逻辑（模板 + 画风锁 + 落盘）。"""
    from .llm import gateway as gw
    purpose = {"plan": "create.plan", "assets": "create.assets",
               "script": "create.script", "director": "create.director"}.get(stage)
    if not purpose:
        return {"ok": False, "detail": "stage 只能是 plan / assets / script / director"}
    try:
        variables = creation.vars_for(ws, purpose, {k: v for k, v in (extra or {}).items()
                                                    if k in ("idea", "episodes", "seconds",
                                                             "episodes_range", "script_ep")})
    except ValueError as exc:
        return {"ok": False, "detail": str(exc)}
    res = gw.get_gateway().complete(purpose, variables, project=ws)
    if not res.get("ok"):
        return {"ok": False, "detail": (res.get("error") or {}).get("message") or "生成失败"}
    text = res.get("text") or res.get("content") or ""
    if not str(text).strip():
        return {"ok": False, "detail": "模型返回为空（%s）：多为 max_tokens 太小"
                                       % (res.get("finish_reason") or "未知")}
    saved = creation.write(ws, stage, text, name=str((extra or {}).get("name") or ""))
    return {"ok": True, "stage": stage, "chars": len(text), "file": saved.get("rel") or saved.get("path"),
            "usage": res.get("usage"), "detail": saved.get("detail") or "已生成并落盘"}


def _do_run(ws, spec_id: str, params: dict, *, allow_gpu: bool) -> dict:
    if spec_id in _DENY_SPECS:
        return {"ok": False, "detail": "这条命令不允许由助手执行：%s" % spec_id}
    cmd = CMD.get(spec_id)
    if cmd is None:
        return {"ok": False, "detail": "没有这条命令：%s（可用 state 里的节点 id 或让我列命令）" % spec_id}
    if cmd.billing in (CMD.PAID, CMD.EXTERNAL):
        return {"ok": False, "detail": "这条命令会产生站外费用，助手不会替你花钱：%s" % spec_id}
    if spec_id == "scheduler.run" and (params or {}).get("apply"):
        return {"ok": False, "need_confirm": True,
                "detail": "调度器真实执行必须由用户在 Studio 的调度页确认；助手只能先干跑"}
    if cmd.billing == CMD.GPU and not allow_gpu:
        return {"ok": False, "need_confirm": True,
                "detail": "这条会占本机 GPU（可能几十分钟）。先跟用户确认，"
                          "让他打开「允许占用 GPU」再执行：%s" % spec_id}
    v = cmd.validate(params or {})
    if not v["ok"]:
        return {"ok": False, "detail": "参数不对：" + "；".join(v["errors"]),
                "params": [p.as_dict() for p in cmd.params]}
    argv = cmd.build_argv(v["values"], ws)
    # 长任务（GPU）一律进作业队列：同步等 20 分钟会把浏览器与单进程 uvicorn 一起拖死
    if cmd.billing == CMD.GPU or spec_id in ("video.run", "assets.local", "board.frame"):
        job = jobs.create_job(ws, cmd, argv, v["values"],
                              estimate=cmd.billing_label, note="agent", actor="agent")
        return {"ok": True, "job": job.get("id"), "mode": "job",
                "detail": "已入队：%s；可用 job(job_id) 查进度" % job.get("id")}
    res = runner.run_stream(argv, ws=ws, timeout=600)
    tail = "\n".join(res["lines"][-12:])
    jobs.record_audit(ws, spec_id, argv, res["rc"], estimate=cmd.billing_label, actor="agent")
    return {"ok": res["rc"] == 0, "rc": res["rc"], "tail": tail,
            "detail": "退出码 %d" % res["rc"]}


def _dispatch(ws, name: str, args: dict, *, allow_gpu: bool) -> dict:
    a = args or {}
    try:
        if name == "state":
            return {"ok": True, "state": _compact_state(ws)}
        if name == "set_idea":
            r = creation.save_idea(ws, {"idea": str(a.get("idea") or ""),
                                        "ep_total": a.get("ep_total") or 0,
                                        "ep_seconds": a.get("ep_seconds") or 0})
            return {"ok": bool(r.get("ok", True)), "detail": r.get("detail") or "灵感已保存"}
        if name == "set_style":
            return _set_style(ws, str(a.get("text") or ""))
        if name == "commands":
            grp = str(a.get("group") or "")
            items = [{"id": c.id, "title": c.title, "group": c.group,
                      "gpu": c.billing == CMD.GPU}
                     for c in CMD.catalog()]
            if grp:
                items = [x for x in items if grp in x["group"]]
            return {"ok": True, "items": items[:60]}
        if name == "read_doc":
            d = creation.read(ws, str(a.get("stage") or ""))
            return {"ok": True, "stage": a.get("stage"), "text": (d.get("text") or "")[:12000]}
        if name == "write_doc":
            r = creation.write(ws, str(a.get("stage") or ""), str(a.get("text") or ""))
            return {"ok": True, "detail": r.get("detail"), "rel": r.get("rel")}
        if name == "generate":
            return _do_generate(ws, str(a.get("stage") or ""), a.get("extra") or {})
        if name == "run":
            return _do_run(ws, str(a.get("spec_id") or ""), a.get("params") or {},
                           allow_gpu=allow_gpu)
        if name == "job":
            j = jobs.get_job(str(a.get("job_id") or ""))
            if not j:
                return {"ok": False, "detail": "没有这个作业"}
            ev = jobs.events(j["id"], limit=2000)
            tail = "\n".join((e.get("text") or "") for e in ev[-8:])
            return {"ok": True, "status": j.get("status"), "rc": j.get("rc"), "tail": tail[-1200:]}
        if name == "episodes":
            s = canvas.series(ws)
            return {"ok": True, "episodes": [{"ep": r["ep"], **r["counts"]}
                                             for r in (s.get("rows") or []) if r["counts"]["total"]]}
        if name == "boards":
            ep = str(a.get("ep") or "ep01")
            d = canvas.shot(ws, ep, "shot_001")
            s = canvas.series(ws)
            row = next((r for r in s.get("rows") or [] if r["ep"] == ep), None)
            if row is None:
                return {"ok": False, "detail": "没有这一集：%s" % ep}
            miss = [c["shot_id"] for c in row["shots"] if not c["board"]]
            return {"ok": True, "ep": ep, "shots": row["counts"]["total"],
                    "with_board": row["counts"]["total"] - len(miss), "missing": miss[:20],
                    "has_prompt": bool(d.get("ok"))}
        if name == "skills":
            return {"ok": True, "installed": [x.get("id") for x in skills.installed(ws).get("items") or []],
                    "available": [i["id"] for i in skills.presets().get("items") or []][:60]}
        if name == "install_skill":
            r = skills.install(ws, str(a.get("id") or ""))
            return {"ok": bool(r.get("ok")), "detail": r.get("detail")}
        return {"ok": False, "detail": "未知工具：%s" % name}
    except Exception as exc:                                   # noqa: BLE001
        return {"ok": False, "detail": "%s: %s" % (type(exc).__name__, str(exc)[:300])}


# ---------------------------------------------------------------------------
# 解析模型回复
# ---------------------------------------------------------------------------
def _first_json(s: str) -> dict | None:
    r"""从文本里取**第一个括号配平**的 JSON 对象。

    ★ 不能用 `re.search(r"\{.*\}")`：模型经常在 JSON 后面继续「自问自答」——
      实测吐成 `{"tool":"state"}` 再跟一段伪造的「工具返回…」，正则贪婪匹配会把两段
      粘成一个非法 JSON，于是整轮退化成「收尾发言」。更糟的是那段伪造数据看起来
      像真的（它编了一部根本不存在的剧），人会信。
    """
    text = s or ""
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        depth, instr, esc = 0, False, False
        for j in range(i, len(text)):
            c = text[j]
            if instr:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    instr = False
                continue
            if c == '"':
                instr = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        d = json.loads(text[i:j + 1])
                    except (json.JSONDecodeError, ValueError):
                        break
                    if isinstance(d, dict):
                        return d
                    break
    return None


def _parse(text: str) -> dict:
    """尽量从回复里抠出 JSON。模型偶尔会包 ```json 或加前言，这里都要能认。"""
    s = (text or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"```\s*$", "", s).strip()
    d = _first_json(s)
    if isinstance(d, dict) and ("tool" in d or "done" in d or "say" in d):
        return d
    # 彻底不是 JSON：当成收尾发言，避免死循环
    return {"say": s[:1500] or "（模型没有返回内容）", "done": True, "_unparsed": True}


# ---------------------------------------------------------------------------
# 主循环
# ---------------------------------------------------------------------------
def run(ws, messages, *, auto: bool = False, allow_gpu: bool = False,
        model: str | None = None, max_steps: int = MAX_STEPS) -> dict:
    ws = str(ws)
    hist = [{"role": "system", "content": SYSTEM}]
    for m in messages or []:
        if m.get("role") in ("user", "assistant") and m.get("content"):
            hist.append({"role": m["role"], "content": str(m["content"])[:8000]})

    steps, usage_sum = [], {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    reply, done, err, out = "", False, "", {}
    t_all = time.time()

    for i in range(max_steps):
        try:
            out = _chat(ws, model, hist)
        except LLMError as exc:
            err = "%s: %s" % (exc.kind, exc.text)
            break
        except Exception as exc:                               # noqa: BLE001
            err = "%s: %s" % (type(exc).__name__, exc)
            break
        u = out.get("usage") or {}
        for k in usage_sum:
            try:
                usage_sum[k] += int(u.get(k) or 0)
            except (TypeError, ValueError):
                pass
        act = _parse(out["text"])
        say = str(act.get("say") or "").strip()
        if say:
            reply = say
        tool = act.get("tool")
        if act.get("done") or not tool:
            hist.append({"role": "assistant", "content": out["text"][:4000]})
            done = True
            break
        args = act.get("args") if isinstance(act.get("args"), dict) else {}
        t0 = time.time()
        res = _dispatch(ws, str(tool), args, allow_gpu=allow_gpu)
        ms = int((time.time() - t0) * 1000)
        steps.append({"n": i + 1, "tool": tool, "args": args, "say": say,
                      "result": res, "ms": ms})
        # 回填给模型：只给结果摘要，不把整份文档再塞回去
        obs = json.dumps(res, ensure_ascii=False)
        if len(obs) > 4000:
            obs = obs[:4000] + "…（已截断）"
        hist.append({"role": "assistant", "content": out["text"][:2000]})
        hist.append({"role": "user", "content": "（系统）%s 的真实返回，JSON：\n%s\n\n"
                                                "只输出下一个 JSON 对象，不要复述这段返回。" % (tool, obs)})
        if res.get("need_confirm") and not auto:
            done = True
            reply = (say + "\n\n" if say else "") + "需要你确认才能继续：" + str(res.get("detail") or "")
            break

    return {
        "ok": not err,
        "error": err,
        "reply": reply or ("已到达步数上限" if not done else ""),
        "done": done,
        "steps": steps,
        "usage": usage_sum,
        "model": out.get("model") if steps or reply else (model or ""),
        "provider": out.get("provider") or "",
        "elapsed": round(time.time() - t_all, 1),
    }


def tools_doc() -> dict:
    return {"items": [{"name": k, "args": v} for k, v in TOOL_DOC.items()],
            "max_steps": MAX_STEPS,
            "note": "助手只能调这些工具；06-提示词 契约不在其中（只能由制作包导入生成）。"}
