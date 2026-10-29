#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_workflow_store.py —— 工作流上传/切换 + 画风目录（离线）

守什么
------
1. **上传只认 API 格式**：界面导出的「带 nodes/links」那种必须被挡住，并说清怎么导出；
   没有输出节点的工作流也要拒 —— 跑完不出东西比报错更浪费时间。
2. **自动映射只给起点**：能识别的是加分，识别不了的必须列出来（`missing_optional`），
   不能静默塞个空字符串让出片时「参数没生效但任务成功」。
3. **不覆盖内置**：同名再上传要留 `.bak_*`，内置那份永远在清单里且只读。
4. **画风目录**：3 条轨道都要能列出，6 个官方风格必须落在正确轨道上（选错轨道会连带
   资产数量与单镜时长一起错）。
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB))

from core import comfy_store, styles  # noqa: E402

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("  [NG] %s" % msg)
    return cond


def section(name):
    print("\n[%s]" % name)


def wf(slots=2, out=True):
    d = {
        "10": {"class_type": "PrimitiveStringMultiline", "inputs": {"value": "p"}},
        "20": {"class_type": "BasicScheduler", "inputs": {"steps": 4}},
        "50": {"class_type": "MiniMaxH3ReferenceToVideo",
               "inputs": {"prompt": ["10", 0], "steps": ["20", 0]}},
    }
    for i in range(slots):
        nid = str(100 + i)
        d[nid] = {"class_type": "LoadImage", "inputs": {"image": "a.png"}}
        d["50"]["inputs"]["ref_images.ref_image_%d" % i] = [nid, 0]
    if out:
        d["60"] = {"class_type": "SaveVideo", "inputs": {"filename_prefix": "x", "video": ["50", 0]}}
    return d


def main():
    tmp = Path(tempfile.mkdtemp()) / "comfy"
    real_dir, real_index = comfy_store.DIR, comfy_store.INDEX
    comfy_store.DIR, comfy_store.INDEX = tmp, tmp / "index.json"
    try:
        section("1. 上传合法工作流：自动映射 + 容量")
        r = comfy_store.save("my-h3", json.dumps(wf(3)))
        check(r["ok"] is True, "合法工作流应保存成功")
        check(r["capacity"] == 3, "容量应识别为 3，实际 %s" % r["capacity"])
        check(r["map"].get("prompt") == "10", "提示词节点应映射到 10，实际 %s" % r["map"].get("prompt"))
        check(len(r["map"].get("images") or []) == 3, "图片槽应列出 3 个")
        check("steps" in r["map"], "步数应识别到（BasicScheduler）")

        section("2. 拒绝非 API 格式 / 无输出节点")
        try:
            comfy_store.save("ui-export", json.dumps({"nodes": [], "links": []}))
            check(False, "界面格式（nodes/links）必须被拒绝")
        except ValueError as exc:
            check("API" in str(exc), "拒绝理由要提到 API 格式：%s" % exc)
        try:
            comfy_store.save("no-out", json.dumps(wf(2, out=False)))
            check(False, "没有输出节点的工作流必须被拒绝")
        except ValueError as exc:
            check("输出" in str(exc), "拒绝理由要提到输出节点：%s" % exc)

        section("3. 同名再上传留备份，不覆盖")
        (tmp / "my-h3.json").write_text("{\"old\": 1}", encoding="utf-8")
        comfy_store.save("my-h3", json.dumps(wf(1)))
        baks = list(tmp.glob("my-h3.bak_*.json"))
        check(len(baks) == 1, "应留下 1 个 .bak 文件，实际 %s" % [b.name for b in baks])

        section("4. 清单与切换：内置永远在、当前项唯一")
        lst = comfy_store.list_all()
        ids = [it["id"] for it in lst["items"]]
        check(comfy_store.BUILTIN_ID in ids, "内置工作流必须一直在清单里")
        cur_after_save = lst["current"]
        check(cur_after_save == comfy_store.BUILTIN_ID,
              "上传新文件不该自动切换当前项（要先让用户确认），实际 %s" % cur_after_save)
        comfy_store.set_current("my-h3")
        lst2 = comfy_store.list_all()
        check(lst2["current"] == "my-h3", "切换后 current 应为 my-h3")
        check(sum(1 for it in lst2["items"] if it["current"]) == 1, "当前项应当且只有一个")
        try:
            comfy_store.set_current("nope")
            check(False, "切换不存在的工作流必须报错")
        except KeyError:
            pass

        section("5. 映射文件落盘，且能被读回")
        mp = tmp / "my-h3.map.json"
        check(mp.is_file(), "映射文件应写在同目录")
        m = json.loads(mp.read_text(encoding="utf-8"))
        check("prompt" in m and "images" in m, "映射里应有 prompt 与 images")
    finally:
        comfy_store.DIR, comfy_store.INDEX = real_dir, real_index
        shutil.rmtree(tmp.parent, ignore_errors=True)

    section("6. 画风目录：轨道齐全、官方风格落在正确轨道")
    cat = styles.catalog()
    check(cat.get("ok") is True, "画风目录应能读出：%s" % cat.get("reason"))
    tracks = {t["id"]: t for t in cat.get("tracks") or []}
    for tid in ("3d_manhua", "2d_animation", "live_action"):
        check(tid in tracks, "缺少轨道 %s" % tid)
    lib = {s["id"]: s for s in cat.get("styles") or []}
    expect = {
        "cinematic": "live_action", "magical-realism": "live_action",
        "jp-youth-film": "live_action", "short-form-drama": "live_action",
        "cel-shading": "2d_animation", "cn-anime-style": "2d_animation",
    }
    for sid, track in expect.items():
        check(sid in lib, "风格库里缺少 %s" % sid)
        if sid in lib:
            check(lib[sid].get("track") == track, "%s 应在 %s 轨道" % (sid, track))
            check(bool(lib[sid].get("prompt")), "%s 应有提示词原文" % sid)
            check(sid in (tracks.get(track, {}).get("sub_modes") or []) or
                  any(x["id"] == sid for x in tracks.get(track, {}).get("sub_modes") or []),
                  "%s 应出现在 %s 的子模式里（否则引擎不接受这个画风）" % (sid, track))
    check(len(cat.get("presets", {}).get("resolution") or []) >= 3, "应有分辨率预设")

    print("\n" + "-" * 62)
    if FAILS:
        print("[FAIL] %d 项未通过" % len(FAILS))
        return 1
    print("[OK] 工作流存储与画风目录全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
