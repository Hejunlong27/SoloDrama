#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_llm_modes.py —— 长文用途不该被塞 json_object（离线，不联网）

事故复盘（2026-11-04）
---------------------
`gateway` 原来按「提供商声明了 json 能力」就开 `response_format=json_object`。
DeepSeek 两条线上模型（flash / chat）收到 json_object + 一份「写企划案」的长提示词时，
直接返回 `content=""`（finish_reason=stop，completion_tokens 却是几千）。

界面上的表现是：**点生成没反应 / 生成失败**，看起来像「大模型没接通」。
真因是请求形态错了，与网络、Key、模型都无关。

判据改成「看模板自己的输出类型（text / json）」之后，企划案 22 秒写出 5110 字。
"""
from __future__ import annotations

import sys
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB))

import pytest  # noqa: E402

from core.llm import templates  # noqa: E402
from core.llm.gateway import want_json_mode  # noqa: E402

FAILS = []


def check(cond, msg):
    if cond:
        print("  [PASS] " + msg)
    else:
        print("  [FAIL] " + msg)
        FAILS.append(msg)


def test_text_templates_never_json():
    print("\n[1] 长文模板一律不开 json_mode")
    for pid in ("create.plan", "create.assets", "create.script", "create.director"):
        spec = templates.PURPOSE_MAP.get(pid) or {}
        tspec = templates.TEMPLATE_MAP.get(spec.get("template_id") or "") or {}
        check(want_json_mode(spec, tspec) is False,
              "%s（output=%s）不开 json_mode" % (pid, tspec.get("output")))


def test_pack_convert_is_json():
    print("\n[2] 搬运类模板才开 json_mode")
    spec = templates.PURPOSE_MAP.get("pack.convert") or {}
    tspec = templates.TEMPLATE_MAP.get(spec.get("template_id") or "") or {}
    check(want_json_mode(spec, tspec) is True, "pack.convert 需要 json 输出")


def test_schema_forces_json():
    print("\n[3] 声明了 schema 的一律 json")
    check(want_json_mode({"schema_id": "x"}, {}) is True, "spec.schema_id → True")
    check(want_json_mode({}, {"schema_id": "x"}) is True, "template.schema_id → True")
    check(want_json_mode({}, {"output": "json"}) is True, "output=json → True")
    check(want_json_mode({}, {"format": "markdown"}) is False, "format=markdown → False")


def test_provider_cap_does_not_decide():
    print("\n[4] 提供商有 json 能力也不影响判定")
    # 传一个「看起来很想开 json」的 spec：除了 requires 什么都没声明
    check(want_json_mode({"requires": ["text", "json"]}, {"output": "text", "format": "markdown"}) is False,
          "requires 里有 json 也不算数（那时能力门禁，不是输出格式）")


def main():
    test_text_templates_never_json()
    test_pack_convert_is_json()
    test_schema_forces_json()
    test_provider_cap_does_not_decide()
    print("-" * 60)
    if FAILS:
        print("[FAIL] %d 项未通过" % len(FAILS))
        return 1
    print("[OK] json_mode 判据全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
