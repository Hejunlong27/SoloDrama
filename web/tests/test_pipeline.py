#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_pipeline.py —— 流水线的三条裁决（离线，不执行任何引擎命令）

守什么
------
「流水线模式」最容易做成一个骗人的按钮：点下去看起来在跑，实际要么跳过前置、
要么把花钱的步骤也一路跑完。所以这里只守三条硬规则：

1. **前置未齐就停**（引擎 probes 未过 → blocked，不许硬跑）；
2. **需人工的环节标 manual**，不许假装自动；
3. **计费环节按预算裁决**：估得出来且不超预算 → auto；估不出来或超预算 → ask。

执行路径本身不在这里测（那要跑真实引擎），由 `run(dry_run=True)` 验证「会跑哪几步、按什么顺序」。
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB))

from core import pipeline  # noqa: E402

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("  [NG] %s" % msg)
    return cond


def _stage(sid, name, probes_ok=True, state="todo"):
    return {"id": sid, "name": name, "state": state,
            "probes": [{"label": "前置物", "ok": probes_ok, "found": 1 if probes_ok else 0, "need": 1}]}


def main():
    fake = {"ok": True, "current": "S1", "complete": False,
            "stages": [_stage("S1", "调研"), _stage("S2", "剧本", probes_ok=False),
                       _stage("S3", "资产设计"), _stage("S4", "资产生成")]}
    real_wf, real_norm = pipeline.adapters.workflow_status, pipeline.adapters.norm_workflow
    real_map = pipeline.STAGE_MAP
    try:
        # 计划里是 `norm_workflow(workflow_status(ws))` 两层：喂进去的已经是规范化结果，
        # 所以两个都要替换，否则 norm 会把假数据再"规整"一遍导致 stages 为空。
        pipeline.adapters.workflow_status = lambda ws: copy.deepcopy(fake)
        pipeline.adapters.norm_workflow = lambda raw: raw
        # 用一个**故意加了计费步**的映射来测预算裁决（生产映射里目前全是免费/gpu）
        m = dict(pipeline.STAGE_MAP)
        m["S1"] = {"cmd": "market.template", "mode": "sync", "mode_text": "生成模板", "note": ""}
        m["S4"] = {"cmd": "assets.rh", "mode": "sync", "mode_text": "云端出图", "note": "", "est": 54}
        pipeline.STAGE_MAP = m
        # S4 需要资产 md，测计划时让它可解析
        pipeline._values_for = lambda sid, ws: {} if sid != "S4" else {"asset_md": "x.md"}

        print("[1] 前置未齐 → blocked，且不许把它当可自动")
        d = pipeline.plan("/tmp/ws", budget=100)
        s2 = [x for x in d["stages"] if x["id"] == "S2"][0]
        check(s2["action"] == "blocked", "S2 应为 blocked，实际 %s（%s）" % (s2["action"], s2["detail"]))
        check("前置齐" not in s2["detail"] and "前置未齐" in s2["detail"], "说明要写清「前置未齐」")

        print("[2] 需人工的环节必须标 manual，并指向页面")
        s3 = [x for x in d["stages"] if x["id"] == "S3"][0]
        check(s3["action"] == "manual", "S3 应为 manual，实际 %s" % s3["action"])
        check(bool(s3.get("page")), "manual 环节要给 page（该去哪个页面）")

        print("[3] 预算内放行 / 超预算要问 / 估不出来也要问")
        d2 = pipeline.plan("/tmp/ws", budget=100)
        s4 = [x for x in d2["stages"] if x["id"] == "S4"][0]
        check(s4["action"] == "auto", "54 ≤ 100 应自动放行，实际 %s（%s）" % (s4["action"], s4["detail"]))
        check(d2["est_total"] == 54, "预计花费应累计为 54，实际 %s" % d2["est_total"])

        d3 = pipeline.plan("/tmp/ws", budget=10)
        s4b = [x for x in d3["stages"] if x["id"] == "S4"][0]
        check(s4b["action"] == "ask", "54 > 10 应转为需确认，实际 %s" % s4b["action"])
        check("预算" in s4b["detail"], "要说明是预算不够：%s" % s4b["detail"])

        m2 = dict(pipeline.STAGE_MAP)
        m2["S4"] = {"cmd": "assets.rh", "mode": "sync", "mode_text": "云端出图", "note": "", "est": None}
        pipeline.STAGE_MAP = m2
        d4 = pipeline.plan("/tmp/ws", budget=1000)
        s4c = [x for x in d4["stages"] if x["id"] == "S4"][0]
        check(s4c["action"] == "ask", "估不出金额时必须停下来问，实际 %s" % s4c["action"])

        print("[4] dry-run 只回报「会跑什么」，且遇 blocked 停")
        pipeline.STAGE_MAP = m
        r = pipeline.run("/tmp/ws", budget=100, dry_run=True)
        ids = [x["id"] for x in r["ran"]]
        check(r["dry_run"] is True, "应是 dry_run")
        check(ids and ids[0] == "S1", "第一步应是 S1，实际 %s" % ids)
        check(all(x.get("rc") is None for x in r["ran"]), "dry_run 不得真的执行（rc 应为 None）")
        check("S2" not in ids, "S2 被前置挡住，不该出现在已跑列表")
        check(any(x["id"] == "S2" for x in r["skipped"]), "S2 应出现在 skipped 里并说明原因")
    finally:
        pipeline.adapters.workflow_status = real_wf
        pipeline.adapters.norm_workflow = real_norm
        pipeline.STAGE_MAP = real_map

    print("\n" + ("全部通过" if not FAILS else "失败 %d 项" % len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
