#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_video_plan.py —— `drama video plan` 的免费分支不许崩

这一条是被真实崩溃逼出来的：

    $ drama video plan --save-calibration
    NameError: name 'cal' is not defined

`--save-calibration` 写在它自己的 help、也在 VERSIONS 的说明里，但函数里读的是一个
从未赋值的局部变量 `cal`（校准结果其实挂在 `estimate_video()` 返回值的 `_calibrate` 上）。
它之所以一直没被发现：**没人跑过这条命令**，而单测只覆盖了 `cost_model` 的纯函数。

所以这里用子进程**真的跑一遍**，判据是「退出码 0 且输出里没有 Traceback」——
比断言某个变量名可靠，也不怕以后重构。
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
SCRIPTS = HERE.parent
FIXTURE = HERE / "fixtures" / "mini_drama"


def _run(*args) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["SOLODRAMA_WORKSPACE"] = str(FIXTURE)
    return subprocess.run([sys.executable, str(SCRIPTS / "drama.py"), "video", "plan", *args],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env=env, cwd=str(SCRIPTS), timeout=120)


def test_plan_runs_clean():
    r = _run()
    assert r.returncode == 0, r.stdout[-800:] + r.stderr[-800:]
    assert "Traceback" not in (r.stdout + r.stderr)


def test_save_calibration_without_calibrate_warns_not_crashes():
    """只给 --save-calibration 时应给出「要和 --calibrate 一起用」的提示，而不是崩。"""
    r = _run("--save-calibration")
    out = r.stdout + r.stderr
    assert r.returncode == 0, out[-800:]
    assert "Traceback" not in out
    assert "--calibrate" in out, "没有提示两个参数要一起用"


def test_save_calibration_with_calibrate_is_graceful():
    """样本不足时只告警不写盘（不臆造单价），且不崩。"""
    r = _run("--calibrate", "--save-calibration")
    out = r.stdout + r.stderr
    assert r.returncode == 0, out[-800:]
    assert "Traceback" not in out


# ---------------------------------------------------------------------------
# B3（2026-11-06 复盘）：--resume / --concurrency 在 local/cloud 上必须「说清楚」
# ---------------------------------------------------------------------------
def _run_video(*args) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["SOLODRAMA_WORKSPACE"] = str(FIXTURE)
    return subprocess.run([sys.executable, str(SCRIPTS / "drama.py"), "video", "run", *args],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env=env, cwd=str(SCRIPTS), timeout=120)


def test_concurrency_gt1_is_rejected_on_local():
    """本机 ComfyUI 是单实例，--concurrency >1 兑现不了 —— 必须拒绝，不能假装接受。

    旧行为：参数被静默吞掉，用户以为在并发，其实一直串行。
    """
    r = _run_video("--engine", "local", "--concurrency", "4")
    out = r.stdout + r.stderr
    assert r.returncode == 2, out[-600:]
    assert "RunningHub" in out, "拒绝时要指出哪条通道支持并发"


def test_concurrency_1_is_accepted():
    """给了 1（等价于默认）就别拦 —— 脚本里统一带上 --concurrency 1 不该报错。"""
    r = _run_video("--engine", "local", "--concurrency", "1")
    out = r.stdout + r.stderr
    assert "兑现不了" not in out, out[-600:]


def test_resume_is_explained_not_silently_eaten():
    """--resume 在本机上语义等价（重跑即续跑），但必须**说出来**，不能静默忽略。"""
    r = _run_video("--engine", "local", "--resume", "batch_20260101")
    out = r.stdout + r.stderr
    assert "已忽略" in out and "重跑" in out, out[-600:]


# ---------------------------------------------------------------------------
# `--engine auto`：通道只从模型确认单读一次（2026-11-06）
# ---------------------------------------------------------------------------
def _drama_for(ws):
    """在指定工作区下拿一个新鲜的 drama 模块（它 import 期就解析工作区）。"""
    os.environ["SOLODRAMA_WORKSPACE"] = str(ws)
    for m in [k for k in list(sys.modules) if k in ("_ws", "_layout", "drama", "model_gate")]:
        sys.modules.pop(m, None)
    for p in (str(SCRIPTS), str(SCRIPTS.parents[1])):
        if p not in sys.path:
            sys.path.insert(0, p)
    import drama as D                                            # noqa: PLC0415
    return D


def _plan(ws, choice, confirmed=True):
    (ws / "model-plan.json").write_text(json.dumps(
        {"models": {"video": {"choice": choice, "confirmed": confirmed}}},
        ensure_ascii=False), encoding="utf-8")


def test_engine_map_covers_all_options():
    """新增通道却没同步映射表 → 这里报警。否则 auto 会静默落回「未知通道」。"""
    D = _drama_for(FIXTURE)          # 先把 SCRIPTS 放进 sys.path
    import model_gate as M                                       # noqa: PLC0415
    ids = {o["id"] for o in M.MODEL_OPTIONS["video"]}
    missing = ids - set(D.VIDEO_ENGINE_OF_CHOICE)
    assert not missing, "MODEL_OPTIONS 里有映射表没覆盖的通道：%s" % sorted(missing)


def test_auto_without_plan_falls_back_to_local(tmp_path):
    """没有确认单 → 本机（￥0），并说明原因；不许静默、也不许报错卡住。"""
    D = _drama_for(tmp_path)
    eng, note = D._resolve_video_engine()
    assert eng == "local", eng
    assert "未找到模型确认单" in note, note


def test_auto_reads_cloud_from_plan(tmp_path):
    """确认单选了云端 → auto 必须给出 cloud（这是 pika 工作流能被调到的前提）。"""
    _plan(tmp_path, "cloud_comfyui")
    D = _drama_for(tmp_path)
    eng, note = D._resolve_video_engine()
    assert eng == "cloud", (eng, note)
    assert "cloud_comfyui" in note


def test_auto_reads_runninghub_from_plan(tmp_path):
    _plan(tmp_path, "runninghub")
    D = _drama_for(tmp_path)
    eng, note = D._resolve_video_engine()
    assert eng == "workflow", (eng, note)


def test_auto_rejects_unconfirmed_plan(tmp_path):
    """有确认单但没确认 → 回落本机，而不是按 choice 偷跑计费通道。"""
    _plan(tmp_path, "cloud_comfyui", confirmed=False)
    D = _drama_for(tmp_path)
    eng, note = D._resolve_video_engine()
    assert eng == "local" and "尚未确认" in note, (eng, note)


def test_auto_refuses_channel_without_executor(tmp_path):
    """闭源模型没有内置执行器 → 返回空串，让调用方退出，不假装能跑。"""
    _plan(tmp_path, "closed_source")
    D = _drama_for(tmp_path)
    eng, note = D._resolve_video_engine()
    assert eng == "" and "没有内置执行器" in note, (eng, note)


def test_video_batch_node_uses_auto():
    """节点模板必须写 auto：写死 local 就等于「确认单选云端、节点跑本机」。"""
    src = (SCRIPTS / "nodes.py").read_text(encoding="utf-8")
    assert "video run --engine auto" in src
    assert "video run --engine local" not in src


def test_runninghub_video_command_forwards_episode():
    """workflow 通道必须把 --ep 传给引擎；否则它会去找根目录 shots.json。"""
    src = (SCRIPTS / "drama.py").read_text(encoding="utf-8")
    marker = "cmd = [sys.executable, RUN_PY, '--video-only']"
    i = src.index(marker)
    block = src[i:i + 500]
    assert "cmd += ['--ep', str(args.ep)]" in block, block
