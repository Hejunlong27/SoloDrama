#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_commands.py —— 命令目录契约测试（离线、零网络、零计费）

覆盖：
  1. id 唯一、分组齐全（15 环节 + 门禁 + 诊断）
  2. 每条命令指向的脚本文件真实存在
  3. 参数校验：必填 / 枚举 / 非法前缀
  4. argv 构造：首元素是解释器、次元素是脚本、无 shell 拼接
  5. 危险命令必须带门禁或计费标记
  6. Agent 提示词可复制（含工作区与命令）
"""
from __future__ import annotations

import sys
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
if str(WEB) not in sys.path:
    sys.path.insert(0, str(WEB))

from core import commands as CMD  # noqa: E402
from core import paths  # noqa: E402

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("  [NG] %s" % msg)
    return cond


def test_catalog():
    print("[1] 目录基本约束")
    ids = [c.id for c in CMD.COMMANDS]
    check(len(ids) == len(set(ids)), "命令 id 存在重复")
    check(len(ids) >= 50, "命令数量过少（应覆盖全部环节），实际 %d" % len(ids))
    for c in CMD.COMMANDS:
        check(c.script.is_file(), "%s 指向的脚本不存在：%s" % (c.id, c.script))
        check(bool(c.title) and bool(c.group), "%s 缺少标题或分组" % c.id)
        if c.danger == CMD.DANGER and not c.gate and c.billing != CMD.PAID:
            check(False, "%s 标记为危险操作但没有门禁或计费标记" % c.id)
        if c.billing == CMD.PAID:
            check(bool(c.resources), "%s 是计费命令但没有声明资源占用" % c.id)
    print("     命令总数：%d，分组数：%d" % (len(ids), len(CMD.groups())))


def test_rounds_coverage():
    print("[2] 环节覆盖度（生产流程总纲 15 环节）")
    must = ["-1 画风确认", "0 通道确认", "1 调研", "2 拆解", "3 选题", "3.5 转译",
            "3.6 题材公式", "4 剧本", "5 台词审计", "6 资产", "7 参考图",
            "8 分镜提示词", "9 入门口禁", "10 出片", "11 拼接字幕", "12 验收结账", "13 合规发行"]
    groups = set(CMD.groups())
    for g in must:
        check(g in groups, "缺少分组：%s" % g)
    print("     分组：%s" % "、".join(CMD.groups()))


def test_validate():
    print("[3] 参数校验")
    c = CMD.get("style.set")
    v = c.validate({})
    check(not v["ok"] and any("画风" in e for e in v["errors"]), "必填缺失未报错")
    v = c.validate({"choice": "3d_manhua"})
    check(v["ok"] and v["values"]["choice"] == "3d_manhua", "合法枚举被拒")
    v = c.validate({"choice": "nope"})
    check(not v["ok"], "非法枚举未报错")
    v = c.validate({"choice": "--evil"})
    check(not v["ok"], "以 - 开头的值未报错")

    c2 = CMD.get("video.run")
    v = c2.validate({"limit": "abc"})
    check(not v["ok"], "整数参数未校验")
    v = c2.validate({"limit": "3", "yes": True})
    check(v["ok"] and v["values"]["limit"] == 3 and v["values"]["yes"] is True, "整数/布尔解析失败")


def test_argv():
    print("[4] argv 构造")
    c = CMD.get("video.run")
    argv = c.build_argv({"limit": 2, "yes": True, "resume": "20261017_120000"})
    check(argv[0] == paths.engine_python(), "argv[0] 不是引擎解释器")
    check(str(argv[1]).endswith("drama.py"), "argv[1] 不是 drama.py")
    check(argv[2:4] == ["video", "run"], "子命令顺序错误：%s" % argv[2:4])
    check("--yes" in argv and "--limit" in argv and "2" in argv, "布尔/数值参数未拼入")
    check("--resume" in argv and "20261017_120000" in argv, "续跑参数未拼入")
    for a in argv:
        check(not any(ch in str(a) for ch in (";", "|", "&", ">", "<")), "argv 含 shell 元字符：%s" % a)

    c = CMD.get("ingest.check")
    argv = c.build_argv({"ep": "ep03"})
    check(argv[-2:] == ["--ep", "ep03"], "ingest 参数顺序异常：%s" % argv)

    c = CMD.get("layout.show")
    argv = c.build_argv({"ws": None})
    check(len(argv) == 2, "空参数应只留解释器+脚本：%s" % argv)


def test_workspace_passing():
    print("[4b] 工作区传参（两种并存：环境变量 / --workspace）")
    ws = r"D:\剧本\海外剧\1013新建"
    # 自带 --workspace 的脚本：显式传参，且位置正确
    a = CMD.get("ingest.check").build_argv({"ep": "ep03"}, ws)
    check(a[-2:] == ["--workspace", ws], "ingest 未在末尾传 --workspace：%s" % a)
    a = CMD.get("project.status").build_argv({}, ws)
    check(a[2:4] == ["--workspace", ws], "creation.py 的 --workspace 必须放在子命令之前：%s" % a)
    a = CMD.get("media.render").build_argv({"ep": "ep01"}, ws)
    check("--workspace" in a, "subtitle.py 未传 --workspace")
    # drama.py 没有全局 --workspace，只能靠环境变量；传了会 argparse 报错
    for cid in ("video.plan", "style.status", "assets.local", "cost.checkpoint", "refs.report"):
        a = CMD.get(cid).build_argv({}, ws)
        check("--workspace" not in a, "%s 不应给 drama.py 传 --workspace（会报 unrecognized arguments）" % cid)
    # 未给工作区时不得凭空加参数
    a = CMD.get("ingest.check").build_argv({"ep": "ep03"}, None)
    check("--workspace" not in a, "未提供工作区时不应注入 --workspace")


def test_agent_prompt():
    print("[5] Agent 提示词")
    for c in CMD.COMMANDS:
        p = c.agent_prompt(r"D:\剧本\海外剧\1013新建", {})
        check("工作区" in p and "python" in p, "%s 的提示词缺关键信息" % c.id)
        if c.billing == CMD.PAID:
            check("计费" in p and "确认" in p, "%s 的计费提示词缺确认要求" % c.id)
        if c.gate:
            check(c.gate in p, "%s 的提示词未提示门禁" % c.id)
    d = CMD.get("compliance.ep").as_dict()
    check("agent_prompt" in d and "argv_preview" in d, "as_dict 缺字段")
    print("     示例：\n%s" % CMD.get("video.plan").agent_prompt("<ws>", {}))


if __name__ == "__main__":
    for fn in (test_catalog, test_rounds_coverage, test_validate, test_argv,
               test_workspace_passing, test_agent_prompt):
        fn()
    print("-" * 60)
    if FAILS:
        print("[FAIL] %d 项未通过" % len(FAILS))
        sys.exit(1)
    print("[OK] 命令目录契约全部通过")
