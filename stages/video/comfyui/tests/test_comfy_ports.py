#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_comfy_ports.py —— 端口识别与「按张数关掉多余图槽」（离线）

守什么
------
「6 个图槽只用 2 张」这件事，做错的方式都很安静：
  * 不裁：多余的 4 个槽继续拿上次的文件跑 → 串景、白占显存，但任务成功；
  * 裁错：把单槽 `image` 也删了 → 工作流直接跑不起来；
  * 留悬空：删了加载器但消费者还指着它 → ComfyUI 报「节点不存在」，看起来像工作流坏了。

所以这里只用合成工作流做断言，不依赖任何真实模型文件。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from comfy_ports import describe, plan_slots, prune_for_refs  # noqa: E402

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("  [NG] %s" % msg)
    return cond


def section(name):
    print("\n[%s]" % name)


def make_wf(slots=6, dotted=True, orphan=True):
    """造一份「多参考图 → H3 → 存视频」的最小工作流。"""
    wf = {
        "10": {"class_type": "PrimitiveStringMultiline", "inputs": {"value": "prompt"}},
        "20": {"class_type": "ResolutionSelector",
               "inputs": {"aspect_ratio": "16:9", "megapixels": 0.6}},
        "30": {"class_type": "BasicScheduler", "inputs": {"steps": 4}},
        "40": {"class_type": "Seed (rgthree)", "inputs": {"seed": 1}},
        "50": {"class_type": "MiniMaxH3ReferenceToVideo",
               "inputs": {"prompt": ["10", 0], "width": ["20", 0], "steps": ["30", 0],
                          "seed": ["40", 0]}},
        "60": {"class_type": "SaveVideo", "inputs": {"filename_prefix": "out",
                                                     "video": ["50", 0]}},
    }
    for i in range(slots):
        nid = str(100 + i)
        wf[nid] = {"class_type": "LoadImage", "inputs": {"image": "ref_%d.png" % i}}
        key = ("ref_images.ref_image_%d" % i) if dotted else ("image%d" % (i + 1))
        wf["50"]["inputs"][key] = [nid, 0]
    if orphan:
        # 普通中间节点（不是输出类），没人消费它 → 应被可达性剪枝清掉
        wf["999"] = {"class_type": "ImageBatch", "inputs": {"image1": ["100", 0]}}
    return wf


def main():
    section("1. 识别：槽数、端口角色、输出节点")
    wf = make_wf(6)
    d = describe(wf)
    check(d["capacity"] == 6, "应识别出 6 个参考图槽，实际 %s" % d["capacity"])
    check(d["slots"] == ["100", "101", "102", "103", "104", "105"],
          "加载器顺序应稳定，实际 %s" % d["slots"])
    check(d["outputs"] == ["60"], "输出节点应为 60，实际 %s" % d["outputs"])
    roles = {p["role"] for p in d["ports"]}
    for r in ("prompt", "image", "steps", "seed", "aspect", "filename"):
        check(r in roles, "端口里缺少角色 %s，实际 %s" % (r, sorted(roles)))
    groups = d["groups"]
    check(len(groups) == 1 and len(groups[0]["fields"]) == 6,
          "应识别出一个 6 字段的多槽节点，实际 %s" % groups)

    section("2. 裁剪 6 → 2：只留前两个，且不留悬空引用")
    out, rep = prune_for_refs(wf, 2)
    check(rep["before"] == 6 and rep["after"] == 2,
          "报告应为 6→2，实际 %s→%s" % (rep["before"], rep["after"]))
    check(out["50"]["inputs"].get("ref_images.ref_image_0") == ["100", 0], "第 1 个槽必须保留")
    check(out["50"]["inputs"].get("ref_images.ref_image_1") == ["101", 0], "第 2 个槽必须保留")
    check("ref_images.ref_image_2" not in out["50"]["inputs"], "第 3 个槽必须删掉")
    left = describe(out)
    check(left["capacity"] == 2, "裁完容量应为 2，实际 %s" % left["capacity"])
    dangling = [(nid, k) for nid, n in out.items() for k, v in (n.get("inputs") or {}).items()
                if isinstance(v, list) and str(v[0]) not in out]
    check(not dangling, "留下了悬空引用：%s" % dangling)
    check(all(nid not in out for nid in ("102", "103", "104", "105")),
          "多余的加载器应被删除，实际仍在：%s" % [n for n in out if n in ("102", "103", "104", "105")])

    section("3. 原工作流不能被改动（深拷贝）")
    check(len(wf["50"]["inputs"]) == 10,
          "原工作流被就地改了：%s（应为 4 个固定输入 + 6 个槽）" % len(wf["50"]["inputs"]))
    check("102" in wf, "原工作流的加载器被删了")

    section("4. 不裁的情况：数量够 / 未指定")
    same, rep2 = prune_for_refs(wf, 6)
    check(rep2["dropped_nodes"] == [], "张数够时不该删任何节点，实际 %s" % rep2["dropped_nodes"])
    same, rep3 = prune_for_refs(wf, None)
    check(rep3["after"] is None, "未指定张数应保持原样并说明原因")

    section("5. 单槽 image 字段绝不能被删")
    wf1 = make_wf(1, dotted=False)
    out1, rep4 = prune_for_refs(wf1, 1)
    check(out1["50"]["inputs"].get("image1") == ["100", 0], "单槽字段被误删了")
    check(rep4["dropped_nodes"] == [], "单槽时不该有节点被删，实际 %s" % rep4["dropped_nodes"])

    section("6. 孤立节点按可达性清掉（仅在真的要裁剪时做）")
    out2, rep5 = prune_for_refs(wf, 2)
    check("999" not in out2, "不可达的 999 应被清掉")
    # 不裁剪时不动图：ComfyUI 本来就不执行不可达节点，没必要为了整洁去改别人的工作流
    same2, _r = prune_for_refs(wf, 6)
    check("999" in same2, "数量够时不该顺手动刀（保持原样）")
    check("999" in rep5["dropped_nodes"], "报告里应列出被清掉的孤立节点")

    section("7. 云端方案：该喂哪几个槽")
    plan = plan_slots(describe(wf), 2)
    check(plan["use"] == ["100", "101"], "应喂前两个槽，实际 %s" % plan["use"])
    check(plan["rest"] == ["102", "103", "104", "105"], "剩余槽应列全，实际 %s" % plan["rest"])
    check(plan["short"] == 0, "张数没超容量时 short 应为 0")

    print("\n" + "-" * 62)
    if FAILS:
        print("[FAIL] %d 项未通过" % len(FAILS))
        return 1
    print("[OK] 端口识别与槽位裁剪全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
