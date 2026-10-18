#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_inventory.py —— 产出与消耗聚合测试（离线、零网络、零计费）

背景（真实的统计缺陷）：资产走云端工作流出图时，用量落在
`output/assets/<kind>/_wf/result_*.json`，**统一台账可能没有收录**。
只读台账 ⇒ 界面上显示「花了多少钱 = ¥0」，而钱其实已经花了。

本测试用合成工作区守住四条口径：
  1. 云端生成记录的用量必须被算进去；
  2. **失败任务不计费**；
  3. 台账与工作流记录**按 taskId 去重**，不重复计；
  4. 产出统计（角色/场景/道具/参考图/成片）准确，且「有没有产出」判定正确。
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
if str(WEB) not in sys.path:
    sys.path.insert(0, str(WEB))

from core import inventory  # noqa: E402

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("  [NG] %s" % msg)
    return cond


def _mkfile(p: Path, content: str = "x"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _make_ws(root: Path) -> Path:
    ws = root / "剧A"
    vp = ws / "video-pipeline"
    # 资产图：角色 3 / 场景 2 / 道具 1
    for i in range(3):
        _mkfile(vp / "output" / "assets" / "characters" / ("char_%02d_00.png" % i))
    for i in range(2):
        _mkfile(vp / "output" / "assets" / "scenes" / ("scene_%02d_00.png" % i))
    _mkfile(vp / "output" / "assets" / "props" / "prop_01_00.png")
    for i in range(4):
        _mkfile(vp / "data" / "refs" / ("char_%02d_four_00.png" % i))
    # 工作流记录：2 条成功（各 17 点）+ 1 条失败（0 点）
    for i, (st, coins) in enumerate((("SUCCESS", 17), ("SUCCESS", 17), ("FAILED", 17))):
        _mkfile(vp / "output" / "assets" / "characters" / "_wf" / ("result_char_%02d.json" % i),
                json.dumps({"taskId": "T%d" % i, "status": st, "usage": {"consumeCoins": coins}}))
    # 台账：收录了 T0（同任务，不得重复计）
    _mkfile(vp / "ledger" / "runs" / "run_1.json",
            json.dumps({"task_id": "T0", "status": "SUCCESS",
                        "usage": {"consumeCoins": 17, "consumeMoney": 0}}))
    return ws


def main():
    root = Path(tempfile.mkdtemp(prefix="solodrama-inv-"))
    try:
        ws = _make_ws(root)
        inv = inventory.inventory(str(ws))
        print("[1] 产出统计")
        check(inv["images"]["characters"] == 3, "角色图统计错误：%s" % inv["images"])
        check(inv["images"]["scenes"] == 2, "场景图统计错误：%s" % inv["images"])
        check(inv["images"]["props"] == 1, "道具图统计错误：%s" % inv["images"])
        check(inv["images"]["total"] == 6, "资产图总数错误：%s" % inv["images"])
        check(inv["refs"] == 4, "参考图统计错误：%s" % inv["refs"])
        check(inv["has_output"] is True, "有产出却判定为无")
        print("     %s" % inv["images"])

        print("[2] 金额口径：成功计费 + 失败不计费 + 按 taskId 去重")
        sp = inv["spend"]
        # T0（台账+工作流都有，去重记 1 次）+ T1（成功）= 34
        check(sp["coins"] == 34, "累计点数应为 34（去重 + 失败不计），实际 %s" % sp["coins"])
        check(sp["source"] == "mixed", "来源应标为 mixed，实际 %s" % sp["source"])
        check(bool(sp["source_text"]), "兜底来源必须带说明文字")

        print("[3] 无产出工作区")
        empty = root / "空剧"
        (empty / "video-pipeline").mkdir(parents=True)
        inv2 = inventory.inventory(str(empty))
        check(inv2["has_output"] is False, "空工作区被判定为有产出")
        check(inv2["spend"]["coins"] == 0, "空工作区金额非零")
        check(inv2["spend"]["source"] == "none", "空工作区来源应为 none")

        print("[4] 项目发现（应至少找到刚才那部剧）")
        import os
        os.environ["SOLODRAMA_SCAN_ROOTS"] = str(root)
        inventory._CACHE.clear()
        d = inventory.discover(refresh=True)
        names = [x["name"] for x in d["items"]]
        check("剧A" in names, "发现列表未包含剧A：%s" % names)
        hit = [x for x in d["items"] if x["name"] == "剧A"][0]
        check(hit["images"] == 10, "发现里的图片数应为 6+4=10，实际 %s" % hit["images"])
        check(hit["coins"] == 34, "发现里的点数应为 34，实际 %s" % hit["coins"])
    finally:
        shutil.rmtree(str(root), ignore_errors=True)


if __name__ == "__main__":
    main()
    print("-" * 60)
    if FAILS:
        print("[FAIL] %d 项未通过" % len(FAILS))
        sys.exit(1)
    print("[OK] 产出与消耗聚合契约全部通过")
