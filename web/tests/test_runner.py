#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_runner.py —— 执行器契约测试（离线、零网络、零计费）

覆盖：打码、环境注入（工作区只能走 env，见 web/README.md 第 1 条）、退出码语义、
      以及对「HTTP 接口不得直通 shell」的结构性断言。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
if str(WEB) not in sys.path:
    sys.path.insert(0, str(WEB))

from core import runner  # noqa: E402

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("  [NG] %s" % msg)
    return cond


def test_mask():
    print("[1] 打码")
    check(runner.mask("") == "(未设置)", "空串打码异常")
    check(runner.mask("short") == "****", "短串打码异常")
    long = "abcdefghijklmnop"
    check(long not in runner.mask(long) and "****" in runner.mask(long), "长串打码异常")

    os.environ["RUNNINGHUB_API_KEY"] = "TESTKEY0123456789ABCDEF"
    t = runner.mask_text("调用失败：key=TESTKEY0123456789ABCDEF 请检查")
    check("TESTKEY0123456789ABCDEF" not in t, "真实密钥未被抹掉")
    b64 = "A" * 200
    t2 = runner.mask_text("data:image/png;base64," + b64)
    check(b64 not in t2, "超长 base64 未被抹掉")
    print("     %s" % t)


def test_env():
    print("[2] 环境注入")
    ws = r"D:\剧本\海外剧\1013新建"
    env = runner.base_env(ws)
    check(env["SOLODRAMA_WORKSPACE"] == str(Path(ws)), "未注入 SOLODRAMA_WORKSPACE")
    check(env["DRAMA_WORKSPACE"] == str(Path(ws)), "未注入旧名 DRAMA_WORKSPACE")
    check(env["PYTHONUTF8"] == "1", "未设置 PYTHONUTF8（中文输出会乱码）")
    check("VIDEO_PIPELINE_WORKSPACE" in env, "未注入引擎目录指针")
    check(env["RUNNINGHUB_BASE_URL"].startswith("https://www.runninghub.ai"),
          "未兜底国际站 base_url（缺失会导致上传报 API Key 不存在）")

    # ★ 本机 SOLODRAMA_WORKSPACE 是用户级环境变量（全局继承），
    #   所以「换工作区」必须能**覆盖**它，而不是 setdefault 让旧值胜出。
    other = r"D:\剧本\海外剧\另一部剧"
    env2 = runner.base_env(other)
    check(env2["SOLODRAMA_WORKSPACE"] == str(Path(other)),
          "切换工作区时未覆盖继承来的环境变量（会导致命令跑错剧）")
    check(env2["SOLODRAMA_WORKSPACE"] != env["SOLODRAMA_WORKSPACE"], "两次注入结果相同，覆盖失效")


def test_exit_codes():
    print("[3] 退出码语义")
    for code, kind in ((0, "ok"), (2, "gate"), (3, "fuse"), (4, "confirm"), (130, "interrupted")):
        m = runner.exit_meaning(code)
        check(m["kind"] == kind, "退出码 %d 语义错误：%s" % (code, m["kind"]))
        check(bool(m["text"]), "退出码 %d 缺中文说明" % code)
    check(runner.exit_meaning(99)["kind"] == "unknown", "未知退出码未兜底")


def test_no_shell():
    print("[4] 结构性断言：不得走 shell")
    src = (WEB / "core" / "runner.py").read_text(encoding="utf-8")
    check("shell=True" not in src, "runner.py 出现 shell=True")
    check("CREATE_NO_WINDOW" in src, "Windows 下未抑制控制台窗口（会闪黑框）")
    src_app = (WEB / "app.py").read_text(encoding="utf-8")
    check("os.system" not in src_app, "app.py 出现 os.system")
    check("shell=True" not in src_app, "app.py 出现 shell=True")


if __name__ == "__main__":
    for fn in (test_mask, test_env, test_exit_codes, test_no_shell):
        fn()
    print("-" * 60)
    if FAILS:
        print("[FAIL] %d 项未通过" % len(FAILS))
        sys.exit(1)
    print("[OK] 执行器契约全部通过")
