# -*- coding: utf-8 -*-
"""pipeline.py —— 全流程连跑（「流水线模式」的后端）

它解决什么
----------
Studio 原本只有「环节状态展示」：11 个环节各做各的页面，每步都要人点。
本模块把它们串成一条可执行的线：**按引擎环节顺序推进，能自动的自动跑，
需要人工或超出预算的停下来并把原因说清楚**。

三条硬纪律
----------
1. **不猜**：只有明确登记了命令的环节才「可自动」。没登记的（如资产设计要人看画风）
   一律标 `manual` 并指向该去的页面 —— 假装能全自动，比不给这个功能更糟。
2. **计费必须可估才放行**：`est_coins` 已知且「累计 + 本步 ≤ 预算」才自动跑；
   估不出来就停（停下来问，不是猜一个数）。
3. **只在引擎说「就绪」的环节动手**：环节自带 probes（`found/need`），
   未满足就停在该环节，不跳过、不硬跑。

前端只是这层的显示器：`GET /api/pipeline` 拿计划，`POST /api/pipeline/run` 跑一步或跑一段。
"""
from __future__ import annotations

import time
from pathlib import Path

from . import adapters, commands as CMD, paths, runner, studio

# ---------------------------------------------------------------------------
# 环节 → 命令（只登记**确实存在且语义等价**的；没登记的按人工处理）
# ---------------------------------------------------------------------------
# mode: job=入队(长任务) / sync=直接执行；est: 每步预估 RH 币（None = 估不出来，必须停下来问）
STAGE_MAP = {
    "S1": {"cmd": "market.template", "mode": "sync", "mode_text": "生成调研模板",
           "note": "模板生成后需要人补市场数据（榜单/竞品），补齐才过 probes"},
    "S2": {"cmd": "script.plan", "mode": "sync", "mode_text": "剧本编排",
           "note": "按 blueprint 生成分集骨架；正文由 AI/人工在创作中心写"},
    "S4": {"cmd": "assets.local", "mode": "sync", "mode_text": "本地出图（￥0）",
           "note": "本机 ComfyUI 出图，不花钱但占 GPU；需要「资产提示词 md」"},
    "S5": {"cmd": "convert.apply", "mode": "sync", "mode_text": "转分镜提示词",
           "note": "把剧本转成 H3 六段式提示词"},
    "S6": {"cmd": "video.plan", "mode": "sync", "mode_text": "出片计划与成本预估",
           "note": "只算钱不提交；真正出片是下一步 video.run（计费）"},
    "S8": {"cmd": "media.assemble", "mode": "sync", "mode_text": "拼接",
           "note": "把镜头段拼成整集母版，会校验帧数"},
    "S9": {"cmd": "media.master", "mode": "sync", "mode_text": "放大母版",
           "note": "按 model-plan 放大到发布分辨率"},
    "S10": {"cmd": "media.render", "mode": "sync", "mode_text": "烧字幕/音频",
            "note": "字幕时间来自真对齐，不来自剧本估算"},
}

# 明确「要人」的环节：给出该去的页面，而不是让人对着灰按钮猜
MANUAL_HINT = {
    "S3": ("资产设计", "asset", "画风/角色差异化需要人判断，去「资产中心」确认设定卡"),
    "S7": ("发行资料准备", "release", "封面/文案/版权资料要人过一遍，去「发行中心」"),
    "S11": ("定稿输出", "release", "发布版命名与导出要人确认，去「发行中心」"),
}

PAID_STAGES = {"S6b"}          # 预留：真出片（video.run）单独作为一步


def _values_for(sid: str, ws: str) -> dict:
    """这一步需要的参数值。取不到就抛 ValueError（由上层判成「需要人指定输入」）。

    为什么不给空值硬跑：`assets.local` 没有 `SOLODRAMA_ASSET_MD` 会直接 rc=1，
    看起来像「ComfyUI 没开」，会把流水线停在一个假故障上。
    """
    if sid == "S4":
        try:
            cands = (studio.asset_mds(ws) or {}).get("candidates") or []
        except Exception:  # noqa: BLE001
            cands = []
        if not cands:
            raise ValueError("没找到「资产提示词 md」，先在资产中心确认/生成一份")
        return {"asset_md": cands[0]["path"]}
    return {}


def _stage_cmd(cid: str):
    try:
        return CMD.get(cid)
    except Exception:  # noqa: BLE001
        return None


def _cmd_meta(cmd) -> dict:
    if cmd is None:
        return {"billing": "free", "danger": "read", "exists": False}
    return {"billing": cmd.billing, "danger": cmd.danger, "exists": True,
            "title": cmd.title, "group": cmd.group}


def plan(ws: str, *, budget: float = 0.0) -> dict:
    """生成流水线计划。**只读**：不执行任何命令、不写文件、不花钱。"""
    ws = str(ws)
    wf = adapters.norm_workflow(adapters.workflow_status(ws))
    stages = wf.get("stages") or []
    spent = 0.0
    out = []
    stopped_at = ""
    for i, st in enumerate(stages, start=1):
        sid = st.get("id") or ("S%d" % i)
        name = st.get("name") or sid
        probes = st.get("probes") or []
        ready = all(p.get("ok") for p in probes) if probes else True
        blocked = [p.get("label") for p in probes if not p.get("ok")]

        if sid in MANUAL_HINT:
            label, page, why = MANUAL_HINT[sid]
            out.append({"id": sid, "name": name, "state": st.get("state"),
                        "action": "manual", "action_text": "需人工", "page": page,
                        "cmd": "", "billing": "free", "est_coins": None,
                        "detail": why, "blocked": blocked, "ready": ready})
            continue

        spec = STAGE_MAP.get(sid)
        if not spec:
            out.append({"id": sid, "name": name, "state": st.get("state"),
                        "action": "manual", "action_text": "未登记命令", "page": "overview",
                        "cmd": "", "billing": "free", "est_coins": None,
                        "detail": "这一环节还没有可自动执行的命令；去项目详情看该环节要求",
                        "blocked": blocked, "ready": ready})
            continue

        cmd = _stage_cmd(spec["cmd"])
        meta = _cmd_meta(cmd)
        paid = meta["billing"] == "paid"
        est = spec.get("est")
        # 预算裁决：只有「估得出来」且不超预算才自动放行
        if paid:
            if est is None:
                verdict, why = "ask", "这一步会计费但估不出金额 —— 需要你确认后再跑"
            elif spent + est > budget:
                verdict, why = "ask", ("累计 %.0f + 本步 %.0f 超过预算 %.0f RH币"
                                       % (spent, est, budget))
            else:
                verdict, why = "auto", "预算内（本步 %.0f RH币）" % est
                spent += est
        else:
            verdict, why = "auto", ("￥0" if meta["billing"] == "gpu" else "免费")

        if not ready:
            verdict, why = "blocked", ("前置未齐：%s" % "、".join(blocked[:3])) if blocked else "前置未齐"
            if not stopped_at:
                stopped_at = sid
        if verdict == "auto":
            try:
                _values_for(sid, ws)
            except ValueError as exc:
                verdict, why = "ask", str(exc)

        out.append({"id": sid, "name": name, "state": st.get("state"),
                    "action": verdict, "action_text": spec["mode_text"],
                    "page": "", "cmd": spec["cmd"], "billing": meta["billing"],
                    "est_coins": est, "detail": spec["note"] + "；" + why,
                    "blocked": blocked, "ready": ready, "paid": paid})

    auto_n = len([x for x in out if x["action"] == "auto"])
    return {
        "ok": True, "ws": ws, "stages": out,
        "budget": budget, "est_total": round(spent, 2),
        "counts": {"total": len(out), "auto": auto_n,
                   "manual": len([x for x in out if x["action"] == "manual"]),
                   "ask": len([x for x in out if x["action"] == "ask"]),
                   "blocked": len([x for x in out if x["action"] == "blocked"])},
        "stopped_at": stopped_at,
        "current": wf.get("current"), "complete": wf.get("complete"),
    }


def run(ws: str, *, budget: float = 0.0, until: str = "", max_steps: int = 6,
        dry_run: bool = True) -> dict:
    """按计划推进。默认 dry_run=True：只回报「会跑什么」，不动手。

    `until` 给环节 id（如 S5）表示「跑到这一步之前停下」（含该步）。
    `max_steps` 兜底，防止一次点下去跑飞。
    """
    ws = str(ws)
    steps = plan(ws, budget=budget)["stages"]
    ran, skipped = [], []
    for st in steps:
        if st["state"] == "done" and st["action"] != "manual":
            skipped.append({"id": st["id"], "why": "已完成"})
            continue
        if st["action"] != "auto":
            skipped.append({"id": st["id"], "why": st["detail"]})
            if st["action"] in ("blocked", "ask"):
                break
            continue
        if st["action"] == "manual":
            break
        if len(ran) >= max_steps:
            skipped.append({"id": st["id"], "why": "达到本次步数上限 %d" % max_steps})
            break

        cmd = _stage_cmd(st["cmd"])
        if cmd is None:
            skipped.append({"id": st["id"], "why": "命令未注册"})
            break
        try:
            vals = _values_for(st["id"], ws)
        except ValueError as exc:
            skipped.append({"id": st["id"], "why": str(exc)})
            break
        checked = cmd.validate(vals)
        if not checked.get("ok"):
            skipped.append({"id": st["id"], "why": "参数不合规：%s" % "；".join(checked.get("errors") or [])})
            break
        argv = cmd.build_argv(checked["values"], ws)
        env = cmd.env_for(checked["values"])
        rec = {"id": st["id"], "name": st["name"], "cmd": st["cmd"],
               "argv": " ".join(str(a) for a in argv[2:])}
        if dry_run:
            rec["rc"] = None
            rec["dry_run"] = True
            ran.append(rec)
        else:
            t0 = time.time()
            res = runner.run_stream(argv, ws=ws, timeout=1800, extra_env=env)
            rec.update({"rc": res["rc"], "elapsed": round(time.time() - t0, 1),
                        "tail": (res["lines"] or [])[-8:]})
            ran.append(rec)
            if res["rc"] != 0:
                rec["failed"] = True
                break
        if until and st["id"] == until:
            break

    ok = all(r.get("rc") in (0, None) for r in ran)
    return {"ok": ok, "dry_run": dry_run, "ran": ran, "skipped": skipped,
            "budget": budget, "plan": steps}
