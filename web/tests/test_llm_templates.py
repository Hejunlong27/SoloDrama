#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_llm_templates.py —— 提示词模板注册表（导入 1 条 + 创作 4 条）

为什么这个测试还在
------------------
`main` 上有 8 个创作用途和 600 行网关测试；创作移出引擎后那些用例随功能一起删了。
但「模板能渲染」这件事仍然必须被测 —— 它是 Studio 里「AI 导入制作包」的唯一入口，
坏了的表现是：点一下就 500，日志里只有 `FileNotFoundError`，看不出是提示词文件丢了。

覆盖四件事：
  1. 提示词正文能被读到（文件存在且非空）；
  2. 变量齐全时能渲染出 system + user 两段；
  3. 缺必需变量时明确报错（不能渲染出一份缺输入的空提示词）；
  4. 演练 payload 的结构与真实产物一致（否则离线验证没有意义）。
"""
from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
WEB = HERE.parent
sys.path.insert(0, str(WEB))

from core.llm import templates as T  # noqa: E402

FAILS = []


def check(cond, msg):
    print(("  [PASS] " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAILS.append(msg)


def test_prompt_file_present():
    print("\n[A] 提示词正文")
    p = T.body_path("convert-to-pack")
    check(p is not None and p.is_file(), "提示词文件存在：%s" % p)
    body = T.body_text("convert-to-pack")
    check(len(body) > 500, "正文非空且不像占位（%d 字）" % len(body))
    check("solodrama-pack/1" in body, "正文写明了 pack spec")
    check("逐字保留" in body or "不要改写" in body, "正文强调不改写提示词")
    check(len(T.body_sha("convert-to-pack")) == 16, "指纹 16 位")


def test_purposes_shrunk():
    print("\n[B] 用途表")
    ids = [p["id"] for p in T.PURPOSES]
    # ★ 2026-11-04：新增创作链 4 条。顺序是**流水线顺序**，不是字母序 ——
    #   界面按这张表的顺序摆按钮，顺序错了「下一步该点哪个」就得靠猜。
    check(ids == ["pack.convert", "create.plan", "create.assets",
                  "create.script", "create.director"],
          "用途表应为 导入 + 创作四步：%s" % ids)
    check(T.PURPOSE_MAP.get("pack.convert"), "PURPOSE_MAP 可查")
    # 创作类必须 output=text：写文件是 pack.convert 的事
    for pid in ("create.plan", "create.assets", "create.script", "create.director"):
        tid = T.PURPOSE_MAP[pid]["template_id"]
        check(T.TEMPLATE_MAP[tid].get("output") == "text",
              "%s 的输出类型应是 text（实际 %r）" % (tid, T.TEMPLATE_MAP[tid].get("output")))
    check(not T.SCHEMAS, "Schema 留空（结构校验在 pack_spec 里做，不重复）")


def test_render():
    print("\n[C] 渲染")
    system, user = T.render_parts("convert-to-pack", {
        "source_dir": "D:/剧/x",
        "output_dir": "D:/剧/x/pack",
        "style_hint": "美式复古影视风格",
    })
    check(len(system) > 400 and "## 本次输入" not in system, "system 是纯方法论")
    check("D:/剧/x/pack" in user, "user 带上了输出目录")
    check("## 输出契约" in user, "user 带输出契约")
    check("美式复古" in user, "style_hint 可选、给了就带上")


def test_render_missing_var():
    print("\n[D] 缺变量必须报错")
    try:
        T.render_parts("convert-to-pack", {"source_dir": "D:/剧/x"})
    except Exception as exc:                                  # noqa: BLE001
        check("output_dir" in str(exc) or getattr(exc, "kind", "") == "config",
              "报错里点名缺哪个变量：%s" % exc)
    else:
        check(False, "缺 output_dir 竟然渲染成功了")


def test_style_hint_optional():
    print("\n[E] style_hint 可省略")
    system, user = T.render_parts("convert-to-pack", {
        "source_dir": "D:/剧/x", "output_dir": "D:/剧/x/pack"})
    check(len(system) > 0 and "## 本次输入" in user, "省略 style_hint 仍能渲染")


def test_mock_payload():
    print("\n[F] 演练输出结构")
    m = T.mock_payload("pack.convert", {})
    check(m.get("simulated") is True, "带 simulated 标记（不许冒充真实生成）")
    files = m.get("files") or {}
    check("pack.json" in files, "有 pack.json")
    check(any(k.startswith("assets/") for k in files), "有 assets/*.json")
    check(any(k.startswith("episodes/") for k in files), "有 episodes/epNN.json")
    check(files["pack.json"].get("spec") == "solodrama-pack/1", "spec 与真实规范一致")


def test_field_hint():
    print("\n[G] 字段提示")
    check("4–15" in T.field_hint("shots.0.duration"), "duration 有取值范围提示")
    check(T.field_hint("") == "", "空路径不编提示")


def main():
    test_prompt_file_present()
    test_purposes_shrunk()
    test_render()
    test_render_missing_var()
    test_style_hint_optional()
    test_mock_payload()
    test_field_hint()
    print("\n" + ("全部通过" if not FAILS else "失败 %d 项" % len(FAILS)))
    return 0 if not FAILS else 1


def test_all():
    """pytest 入口：把上面的检查跑一遍，有失败就 assert。"""
    rc = main()
    assert rc == 0, "见上方 [FAIL] 明细"


if __name__ == "__main__":
    sys.exit(main())
