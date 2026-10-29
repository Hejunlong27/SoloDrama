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

    section("5. 开场引导（不调模型）")
    w = assistant.welcome(None)
    for k in ("greeting", "tips", "suggestions", "pages", "model"):
        check(k in w, "welcome 必须有 %s 字段" % k)
    check(2 <= len(w["suggestions"]) <= 3, "没项目时也要给 2–3 条可点的下一步")
    check("剧" in w["greeting"] and "建" in w["greeting"],
          "没项目时应引导去新建/打开项目，实际：%s" % w["greeting"])
    # 假路径：状态读不到也不能抛（否则抽屉一打开就 500）
    w2 = assistant.welcome(str(WEB / "_不存在的剧"))
    check(bool(w2.get("greeting")), "状态读不到时仍要有兜底问候语")
    check(set(p["id"] for p in w2["pages"]) == set(assistant.ROUTES),
          "welcome.pages 必须与 ROUTES 完全一致（前端靠它显示页面名）")

    section("6. suggestions 归一化")
    check(assistant._norm_suggestions("现在卡在哪？") == ["现在卡在哪？"], "字符串应包成单元素数组")
    check(assistant._norm_suggestions(["a", "a", "b"]) == ["a", "b"], "重复项应去重")
    check(len(assistant._norm_suggestions(["1", "2", "3", "4"])) == 3, "最多 3 条（chips 放不下）")
    check(assistant._norm_suggestions(["x" * 60]) == [], "过长的一条应丢弃")
    check(assistant._norm_suggestions(None) == [], "None 应返回空列表")

    section("7. 提示词与代码不漂移")
    prompt = (WEB.parent / "stages" / "creation" / "prompts" / "assistant-chat.md").read_text("utf-8")
    for route in assistant.ROUTES:
        check(("`%s`" % route) in prompt,
              "提示词里没有 route `%s` —— 新增页面必须同步 assistant-chat.md" % route)
    check("suggestions" in prompt, "提示词要说明 suggestions 字段，否则引导永远是兜底文案")
    for cmd in assistant.allowed_commands():
        check(cmd in prompt or "可执行命令" in prompt, "提示词应说明可用命令来自状态")

    section("8. 状态推导的「去 XX」")
    g0 = assistant.goto_hint(None)
    check(g0.get("route") == "projects", "没项目时应指向项目管理，实际 %r" % g0.get("route"))
    check(bool(g0.get("label")), "按钮要有中文名（前端直接显示，不能是 route id）")
    check(assistant.goto_hint(str(WEB / "_不存在的剧")) == {},
          "状态读不到时不要硬指路（宁可没有按钮）")
    # 模型给的动作要带中文名：前端不再自己维护一份 route→中文 映射
    a1 = assistant._normalize_action({"type": "navigate", "route": "creation"}, cmds)
    check(a1.get("label") == "创作中心", "navigate 动作必须带 label，实际 %r" % a1.get("label"))
    a2 = assistant._normalize_action({"type": "run", "command": "convert.apply"}, cmds)
    check(a2.get("label") == "转分镜提示词", "run 动作要带环节说明，实际 %r" % a2.get("label"))

    print("\n" + "-" * 62)
    if FAILS:
        print("[FAIL] %d 项未通过" % len(FAILS))
        return 1
    print("[OK] 助手白名单边界全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
