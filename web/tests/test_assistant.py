#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_assistant.py —— 对话控制的白名单边界（离线，不调模型）

这个功能的危险在于「一句话就动手」。所以这里不测模型回答得好不好，只测**边界**：

1. 路由白名单：模型说跳到 `../../etc` 或未知页面 → 必须退化成 none；
2. 命令白名单：只允许流水线里登记的那几条，`assets.rh` 这类计费命令必须被拒；
3. 解析兜底：模型不按 JSON 回（带代码围栏、或者根本是散文）→ 当回答用，动作置空；
4. 空输入不烧 token。
"""
from __future__ import annotations

import sys
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB))

from core import assistant  # noqa: E402

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("  [NG] %s" % msg)
    return cond


def section(name):
    print("\n[%s]" % name)


def main():
    cmds = assistant.allowed_commands()

    section("1. 路由白名单")
    ok = assistant._normalize_action({"type": "navigate", "route": "assets"}, cmds)
    check(ok["type"] == "navigate" and ok["route"] == "assets", "合法路由应通过")
    for bad in ("../../etc", "admin", "", "assets?x=1"):
        r = assistant._normalize_action({"type": "navigate", "route": bad}, cmds)
        check(r["type"] == "none", "非法路由 %r 必须退化成 none，实际 %s" % (bad, r.get("type")))
    r = assistant._normalize_action({"type": "navigate", "route": "#/pipeline"}, cmds)
    check(r.get("route") == "pipeline", "带 #/ 前缀的路由应被规范化")

    section("2. 命令白名单")
    check("convert.apply" in cmds, "转换分镜应在白名单里（流水线已登记）")
    check("assets.rh" not in cmds, "计费命令 assets.rh 绝不能进白名单")
    r = assistant._normalize_action({"type": "run", "command": "convert.apply"}, cmds)
    check(r["type"] == "run", "合法命令应通过")
    check(r.get("stage") == "S5", "应带上环节 id 供前端精确执行，实际 %s" % r.get("stage"))
    for bad in ("assets.rh", "rm -rf /", "release_export", ""):
        r = assistant._normalize_action({"type": "run", "command": bad}, cmds)
        check(r["type"] == "none", "未授权命令 %r 必须退化成 none" % bad)

    section("3. 解析兜底")
    check(assistant._strip_fence('```json\n{"a":1}\n```') == '{"a":1}', "应剥掉 json 代码围栏")
    check(assistant._strip_fence('{"a":1}') == '{"a":1}', "纯 JSON 不该被改")
    r = assistant._normalize_action("不是字典", cmds)
    check(r["type"] == "none", "动作不是对象时必须退化成 none")
    r = assistant._normalize_action({"type": "delete_everything"}, cmds)
    check(r["type"] == "none", "未知动作类型必须退化成 none")

    section("4. 空输入不烧 token")
    r = assistant.chat("   ")
    check(r["ok"] is False, "空输入应直接拒绝（不调用模型）")
    check(r["action"]["type"] == "none", "空输入不该带动作")
    r2 = assistant.chat("x" * 3000)
    check(r2["ok"] is False, "超长输入应被拦住")

    print("\n" + "-" * 62)
    if FAILS:
        print("[FAIL] %d 项未通过" % len(FAILS))
        return 1
    print("[OK] 助手白名单边界全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
