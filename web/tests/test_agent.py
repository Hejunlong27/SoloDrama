#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_agent.py —— 制片助手的解析与工具闸门（离线）

为什么这两块必须先测
--------------------
① **解析**：模型经常在 JSON 后面自问自答。实测吐成
   `{"tool":"state"}` 之后再跟一段「工具返回：{...}」——那段是它**编的**，
   里面甚至有一部根本不存在的剧。贪婪正则会把两段粘成非法 JSON，于是整轮退化成
   「收尾发言」；更糟的是有人会信那段假数据。所以解析必须只取第一个括号配平的对象。
② **闸门**：助手能跑引擎命令。跑错一条占 GPU 的命令 = 几十分钟白烧；
   碰了 06-提示词 契约 = 出片稳定性失守。这两条不能靠模型自觉。
"""
from __future__ import annotations

import sys
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB))

import pytest  # noqa: E402

from core import agent   # noqa: E402

FAILS = []


def check(cond, msg):
    if cond:
        print("  [PASS] " + msg)
    else:
        print("  [FAIL] " + msg)
        FAILS.append(msg)


def test_parse_first_json():
    print("\n[1] 解析：只取第一个 JSON，不被后面编的内容带跑")
    real = '{"say":"先看状态","tool":"state","args":{}}'
    fake = '\n<system>工具 state 返回：{"project":"《不存在的剧》","shots":24}</system>'
    d = agent._parse(real + fake)
    check(d.get("tool") == "state", "取到真正的 tool，实际 %r" % d.get("tool"))
    check("不存在的剧" not in str(d), "没有把模型编的假数据当成结果")

    d2 = agent._parse('```json\n{"say":"好了","done":true}\n```')
    check(d2.get("done") is True, "```json 围栏能认")

    d3 = agent._parse('{"say":"先读一下","tool":"state"')
    check(d3.get("done") is True and "先读一下" in str(d3.get("say")), "截断 JSON 退化成收尾发言，不死循环")

    d4 = agent._parse("我建议你先做分镜图。")
    check(d4.get("done") is True, "纯文本回复按收尾处理")
    check("分镜图" in str(d4.get("say")), "文字保留给用户看")


def test_parse_strings_with_braces():
    print("\n[2] 字符串里的括号不影响配平")
    s = '{"say":"用 {花括号} 和 \\"引号\\" 都不该断开","tool":"state","args":{}}'
    d = agent._parse(s)
    check(d.get("tool") == "state", "带括号与转义引号的 JSON 也能解析")


def test_run_gates():
    print("\n[3] 闸门：不许 shell、不许花钱、GPU 要点头")
    ws = "."
    r = agent._do_run(ws, "project.scaffold", {}, allow_gpu=True)
    check(r["ok"] is False and "不允许" in r["detail"], "结构类命令被拒")
    r2 = agent._do_run(ws, "not.a.command", {}, allow_gpu=False)
    check(r2["ok"] is False and "没有这条命令" in r2["detail"], "未知命令被拒")
    r3 = agent._do_run(ws, "video.run", {"ep": "ep01", "yes": True}, allow_gpu=False)
    check(r3["ok"] is False and r3.get("need_confirm"), "占 GPU 的命令在未授权时只返回「需确认」")
    check("GPU" in r3["detail"], "提示里说清为什么拦")


def test_bad_params():
    print("\n[4] 参数不合规时不提交")
    r = agent._do_run(".", "board.frame", {}, allow_gpu=True)
    check(r["ok"] is False, "缺必填参数被拒")
    check("参数不对" in r["detail"], "说明是参数问题，不是「跑失败」")


def test_tools_doc_scope():
    print("\n[5] 工具范围写死在文档里")
    d = agent.tools_doc()
    names = [x["name"] for x in d["items"]]
    for n in ("state", "read_doc", "write_doc", "generate", "run", "job", "episodes", "boards"):
        check(n in names, "工具含 %s" % n)
    check("shell" not in names and "exec" not in names, "没有 shell / exec 类工具")
    check("06-提示词" in (d.get("note") or ""), "文档里写明契约不在工具集内")


def main():
    test_parse_first_json()
    test_parse_strings_with_braces()
    test_run_gates()
    test_bad_params()
    test_tools_doc_scope()
    print("-" * 60)
    if FAILS:
        print("[FAIL] %d 项未通过" % len(FAILS))
        return 1
    print("[OK] 助手解析与闸门全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
