#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_model_gate.py —— 模型选择门禁的离线测试（零网络、零计费、零第三方依赖）

覆盖：
  1. 未确认时 gate_state.confirmed=False，require() 拦截
  2. set 后 confirmed=True，require() 放行
  3. 通道不一致（确认 local 却跑 rh）被拦下
  4. reset 后回到未确认状态
  5. 确认单读写往返一致、history 记录正确
  6. 三种选项 id 与 MODEL_OPTIONS 定义一致
  7. 菜单/确认请求渲染非空且包含全部选项标签

用法：python test_model_gate.py       （全绿退出码 0；有失败退出码 1）
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import shutil
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
GATE_PATH = HERE.parent / "model_gate.py"


def _load_gate():
    spec = importlib.util.spec_from_file_location("model_gate", GATE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _mk_ws() -> pathlib.Path:
    ws = pathlib.Path(tempfile.mkdtemp(prefix="drama-gate-test-"))
    (ws / "video-pipeline" / "data").mkdir(parents=True, exist_ok=True)
    (ws / "video-pipeline" / "data" / "shots.json").write_text("[]", encoding="utf-8")
    return ws


RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(cond), detail))


def main() -> int:
    mg = _load_gate()
    ws = _mk_ws()
    try:
        # 1. 未确认
        st = mg.gate_state(ws, "image")
        check("未确认时 image 未确认", st["confirmed"] is False, json.dumps(st, ensure_ascii=False))
        ok, msg = mg.require(ws, "image", expected_engine="local")
        check("未确认时 require 拦截", ok is False, msg)

        # 2. set 后放行
        mg.cmd_set(_ns(workspace=str(ws), pairs=["image=local_comfyui"], detail=None))
        st = mg.gate_state(ws, "image")
        check("set 后 image 已确认", st["confirmed"] is True and st["choice"] == "local_comfyui",
              json.dumps(st, ensure_ascii=False))
        ok, msg = mg.require(ws, "image", expected_engine="local")
        check("确认 local 后 require(local) 放行", ok is True, msg)

        # 3. 通道不一致被拦
        ok, msg = mg.require(ws, "image", expected_engine="rh")
        check("确认 local 却跑 rh 被拦", ok is False, msg[:80])

        # 4. video 独立（未确认）
        ok, _ = mg.require(ws, "video", expected_engine="workflow")
        check("video 尚未确认被拦", ok is False)

        # 5. 两条一起 set + 读写往返
        mg.cmd_set(_ns(workspace=str(ws), pairs=["video=runninghub"], detail="workflow_id=demo"))
        plan = mg.load_plan(ws)
        check("确认单落盘且可读回", plan["models"]["video"]["choice"] == "runninghub")
        check("detail 已记录", (plan["models"]["video"].get("detail") or {}).get("workflow_id") == "demo",
              json.dumps(plan["models"]["video"].get("detail"), ensure_ascii=False))
        ok, _ = mg.require(ws, "video", expected_engine="workflow")
        check("确认 runninghub 后 require(workflow) 放行", ok is True)

        # 6. reset
        mg.cmd_reset(_ns(workspace=str(ws), kind="image"))
        st = mg.gate_state(ws, "image")
        check("reset 后回到未确认", st["confirmed"] is False)
        check("reset 不清除 video", mg.gate_state(ws, "video")["confirmed"] is True)
        check("history 记录了 image 的清除前后",
              any(h["kind"] == "image" and h["from"] == "local_comfyui" and h["to"] is None
                  for h in mg.load_plan(ws)["history"]))

        # 7. 非法选项被拒（cmd_set 返回退出码 2）
        rc = mg.cmd_set(_ns(workspace=str(ws), pairs=["image=nonsense"], detail=None))
        check("非法选项返回码 2", rc == 2, "rc=%s" % rc)

        # 8. 选项 id 与清单一致（★ 2026-10-16 gate v2：加入「云端 ComfyUI」；视频再加「RH AI 应用」）
        for kind in ("image", "video"):
            ids = [o["id"] for o in mg.MODEL_OPTIONS[kind]]
            # ★ 2026-11-01：图片侧的 `runninghub`（AI 应用）已删，图片云端只有
            #   `runninghub_workflow`；视频侧仍是 `runninghub`（工作流出片）。两者都算「有 RH」。
            check("%s 选项含本地/云端 ComfyUI 与 RH" % kind,
                  ids[:2] == ["local_comfyui", "cloud_comfyui"]
                  and any(x.startswith("runninghub") for x in ids),
                  str(ids))
            check("%s 每项都有 requires 字段" % kind,
                  all("requires" in o for o in mg.MODEL_OPTIONS[kind]))

        # 8b. ★ 执行依据门禁：Cloud ComfyUI 缺 URL / 缺工作流文件 → 必须拦下
        # ★ 2026-11-05（云端接入）：出片侧的执行器已补齐，工作流随仓库交付，
        #   所以 video 的云端只强制 **地址**；image 仍要求工作流文件（出图工作流由用户选）。
        WANT = {"image": {"comfy_url", "comfy_workflow"}, "video": {"comfy_url"}}
        for kind in ("image", "video"):
            miss = mg.missing_evidence(kind, "cloud_comfyui", {})
            check("%s 云端ComfyUI 缺依据被识别" % kind,
                  set(miss) == WANT[kind], str(miss))
            miss2 = mg.missing_evidence(kind, "cloud_comfyui",
                                        {"comfy_url": "https://x", "comfy_workflow": str(ws / "nope.json")})
            check("%s 不存在的 ComfyUI 工作流文件被识别" % kind,
                  len(miss2) == (1 if kind == "image" else 0)
                  and (kind != "image" or "路径不存在" in miss2[0]), str(miss2))
            wf = ws / "wf.json"
            wf.write_text("{}", encoding="utf-8")
            check("%s 依据齐备时不报缺" % kind,
                  mg.missing_evidence(kind, "cloud_comfyui",
                                      {"comfy_url": "https://x", "comfy_workflow": str(wf)}) == [])

        # 8b-2. ★ 2026-11-05：出片侧云端通道必须**有执行器**且方向是 cloud ——
        #   这两条是「功能缺口」的守门断言：删掉执行器、或把 engine_arg 改回 None，
        #   都会让 `drama video run --engine cloud` 变成一条跑不通的路。
        vopt = [o for o in mg.MODEL_OPTIONS["video"] if o["id"] == "cloud_comfyui"][0]
        check("video/cloud_comfyui 有执行器", bool(vopt.get("executor")), str(vopt))
        check("video/cloud_comfyui 通道标识为 cloud", vopt.get("engine_arg") == "cloud", str(vopt))
        check("video/cloud_comfyui 执行器指向 comfy_local_video",
              "comfy_local_video.py" in str(vopt.get("executor")), str(vopt))
        # 门禁放行链路：确认云端 + 给地址 → require 必须过
        rc_set = mg.cmd_set(_ns(workspace=str(ws), pairs=["video=cloud_comfyui"],
                                detail=None, comfy_url="https://abc-8188.container.x-gpu.com",
                                comfy_workflow=None, app_url=None, app_id=None,
                                workflow_id=None))
        ok_cloud, msg_cloud = mg.require(ws, "video", expected_engine="cloud")
        check("确认云端+地址后 video 门禁放行", rc_set == 0 and ok_cloud, msg_cloud)
        ok_wrong, _ = mg.require(ws, "video", expected_engine="local")
        check("确认云端却用 local 通道被拦", ok_wrong is False)
        mg.cmd_set(_ns(workspace=str(ws), pairs=["video=local_comfyui"], detail=None,
                       comfy_url=None, comfy_workflow=None, app_url=None, app_id=None,
                       workflow_id=None))

        # 8b-3. ★ 确认单即执行依据：detail 里的地址要能被回灌成环境变量
        mg.cmd_set(_ns(workspace=str(ws), pairs=["video=cloud_comfyui"], detail=None,
                       comfy_url="https://abc-8188.container.x-gpu.com", comfy_workflow=None,
                       app_url=None, app_id=None, workflow_id=None))
        import os as _os
        old = _os.environ.pop("COMFYUI_URL", None)
        try:
            applied = mg.apply_env(ws, "video")
            check("apply_env 注入 COMFYUI_URL",
                  applied.get("COMFYUI_URL") == "https://abc-8188.container.x-gpu.com",
                  str(applied))
            _os.environ["COMFYUI_URL"] = "http://127.0.0.1:8188"
            check("apply_env 不覆盖已有环境变量", mg.apply_env(ws, "video") == {})
        finally:
            _os.environ.pop("COMFYUI_URL", None)
            if old is not None:
                _os.environ["COMFYUI_URL"] = old
        mg.cmd_set(_ns(workspace=str(ws), pairs=["video=local_comfyui"], detail=None,
                       comfy_url=None, comfy_workflow=None, app_url=None, app_id=None,
                       workflow_id=None))

        # 8c. ★ 本地 ComfyUI 不强制要工作流文件（有仓库默认工作流），但选了云端就必须给
        check("本地ComfyUI 生图无强制依据", mg.missing_evidence("image", "local_comfyui", {}) == [])
        # ★ 2026-11-01：图片侧的「RH AI 应用」通道已删（引擎无 provider，与工作流通道重复），
        #   这条断言随之取消；图片云端只剩 runninghub_workflow（要工作流文件）。
        check("RH 工作流 生图必须给工作流文件",
              mg.missing_evidence("image", "runninghub_workflow", {}) == ["comfy_workflow"])

        # 9. 渲染非空且含全部标签
        for kind in ("image", "video"):
            menu = mg.render_menu(kind)
            req = mg.render_confirm_request(kind, ws)
            check("%s 菜单含全部标签" % kind,
                  all(o["label"] in menu for o in mg.MODEL_OPTIONS[kind]))
            check("%s 确认请求含选项与命令" % kind,
                  "请选择本项目的" in req and "models" in req)

        # 10. ★ 2026-11-06（用户实测反馈）：`cost` 会被写进 model-plan.json 并显示给用户，
        #    所以它**不能带单价或预估金额** —— 内置单价低报约 4 倍，任何预估价都会被当预算依据。
        #    此前 video/runninghub 写的是「约 78-209 币/段（按帧数）」。
        import re as _re
        bad = _re.compile(r"(币\s*/\s*(段|秒|张|次)|\d+\s*[-–]\s*\d+\s*币|"
                          r"￥\s*\d+(\.\d+)?\s*/\s*(时|段|张)|元\s*/\s*(时|段|张))")
        for kind, opts in mg.MODEL_OPTIONS.items():
            for o in opts:
                for field in ("cost", "label", "desc"):
                    m = bad.search(str(o.get(field) or ""))
                    check("%s/%s 的 %s 不含单价（%s）" % (kind, o["id"], field, m.group(0) if m else ""),
                          m is None, "%s/%s.%s = %r" % (kind, o["id"], field, o.get(field)))
    finally:
        shutil.rmtree(ws, ignore_errors=True)

    print("=" * 62)
    print("model_gate 离线测试")
    print("=" * 62)
    n_fail = 0
    for name, ok, detail in RESULTS:
        print("  %s %s%s" % ("[OK]  " if ok else "[FAIL]", name,
                             "" if ok else "  <- %s" % detail))
        n_fail += 0 if ok else 1
    print("-" * 62)
    print("共 %d 例，通过 %d，失败 %d" % (len(RESULTS), len(RESULTS) - n_fail, n_fail))
    return 1 if n_fail else 0


def _ns(**kw):
    class _O:
        def __init__(self, d):
            self.__dict__.update(d)
    return _O(kw)


if __name__ == "__main__":
    sys.exit(main())
