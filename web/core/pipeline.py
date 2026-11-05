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

from . import adapters, commands as CMD, generators as GEN, paths, runner, studio

# ---------------------------------------------------------------------------
# 环节 → 命令（只登记**确实存在且语义等价**的；没登记的按人工处理）
# ---------------------------------------------------------------------------
# 七环节 → 该环节「能自动跑的那一条命令」。
# ★ 2026-11-01：原来按 S1–S11 映射，而 S1–S11 的判据脚本（workflow.py）已删；
#   现在环节 id 与 `nodes.STAGES` 一致，同一环节下的节点由 `drama do <node>` 推进，
#   这里只登记「一条能代表该环节的批处理命令」，没有就标 manual。
STAGE_MAP = {
    "research": {"cmd": "market.template", "mode_text": "生成调研模板",
                 "note": "模板生成后需要人补市场数据（榜单/竞品），补齐才过节点判据"},
    "script": {"cmd": "script.plan", "mode_text": "剧本编排",
               "note": "按 blueprint 生成分集骨架；正文由 AI/人工在创作中心写"},
    # ★ 2026-11-05：项目确认了「云端 ComfyUI」时，跑 assets.local 会被模型门禁
    #   （expected_engine=local）直接拦下 —— 于是流水线在资产环节永远停住，
    #   而界面又说「云端已就绪」。所以这里按**模型确认单**选命令，不写死本地。
    "asset": {"cmd": "assets.local", "mode_text": "本地出图（￥0）",
              "alt": {"cmd": "assets.cloud", "mode_text": "云端出图（★按主机时长）",
                      "when": ("image", "cloud_comfyui"),
                      "note": "云端实例出图，按主机时长计费；跑完请确认实例已停"},
              "note": "本机 ComfyUI 出图，不花钱但占 GPU；需要「资产提示词 md」"},
    "board": {"cmd": "convert.apply", "mode_text": "分镜转 data 五文件",
              "note": "把分镜 md 转成引擎输入（含 <Picture n> 机械重排）"},
    "video": {"cmd": "video.plan", "mode_text": "出片计划与成本预估",
              "note": "只算钱不提交；真正出片是 video.run（计费）"},
    "edit": {"cmd": "media.master", "mode_text": "母版拼接（封面+片段+BGM）",
             "note": "之后依次 高清放大 → 字幕烧录，见「剪辑」页"},
}

# 明确「要人」的环节：给出该去的页面，而不是让人对着灰按钮猜
MANUAL_HINT = {
    "prompt": ("提示词", "storyboard", "六段式提示词由会话/技能装配，装完用 ingest.check 校验（本页只读）"),
}


def _values_for(sid: str, ws: str) -> dict:
    """这一步需要的参数值。取不到就抛 ValueError（由上层判成「需要人指定输入」）。

    为什么不给空值硬跑：`assets.local` 没有 `SOLODRAMA_ASSET_MD` 会直接 rc=1，
    看起来像「ComfyUI 没开」，会把流水线停在一个假故障上。
    """
    if sid == "asset":
        try:
            cands = (studio.asset_mds(ws) or {}).get("candidates") or []
        except Exception:  # noqa: BLE001
            cands = []
        if not cands:
            raise ValueError("没找到「资产提示词 md」，先在资产中心确认/生成一份")
        # 两个资产命令的参数名不同：`assets.local` 走环境变量 `asset_md`，
        # `assets.rh_wf` 走 CLI `--md`。两个键都给，调用方各取所需（多余的会被忽略）。
        return {"md": cands[0]["path"], "asset_md": cands[0]["path"]}
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

        spec_cmd, spec_mode, spec_note = spec["cmd"], spec["mode_text"], spec["note"]
        alt = spec.get("alt") or {}
        if alt and GEN.plan_choice(ws, alt["when"][0]) == alt["when"][1]:
            spec_cmd = alt["cmd"]
            spec_mode = alt.get("mode_text") or spec_mode
            spec_note = alt.get("note") or spec_note
        cmd = _stage_cmd(spec_cmd)
        meta = _cmd_meta(cmd)
        paid = meta["billing"] == "paid"
        est = spec.get("est")
        # 预算裁决：只有「估得出来」且不超预算才自动放行
        if paid:
            if est is None:
                verdict, why = "ask", "这一步会计费但估不出金额 —— 需要你确认后再跑"
            elif spent + est > budget:
                verdict, why = "ask", ("累计 %.0f + 本步 %.0f 超过上限 %.0f"
                                       % (spent, est, budget))
            else:
                verdict, why = "auto", "在上限内（本步 %.0f）" % est
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
                    "action": verdict, "action_text": spec_mode,
                    "page": "", "cmd": spec_cmd, "billing": meta["billing"],
                    "est_coins": est, "detail": spec_note + "；" + why,
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
        dry_run: bool = True, only: str = "") -> dict:
    """按计划推进。默认 dry_run=True：只回报「会跑什么」，不动手。

    `until` 给环节 id（如 S5）表示「跑到这一步之前停下」（含该步）。
    `only`  给环节 id 表示「只跑这一步」，其余一律不碰 —— 页面每一行的「运行此步」用它，
            否则点 S10 会把前面 9 步一起跑一遍。
    `max_steps` 兜底，防止一次点下去跑飞。
    """
    ws = str(ws)
    steps = plan(ws, budget=budget)["stages"]
    ran, skipped = [], []
    for st in steps:
        if only and st["id"] != only:
            continue                      # 只跑指定环节；不算「跳过」，免得日志里刷一堆噪音
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
