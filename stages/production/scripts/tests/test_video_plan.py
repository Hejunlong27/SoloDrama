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
