#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_connections.py —— 连接中心（离线，不联网、不写真实 web/var）

盯三条「静默坏掉」路径：

1. **密钥不能回显**：`hint()` / `overview()` 的返回值里不能出现明文 Key。
   这条一旦坏了不会报错，只会悄悄把 Key 打到浏览器和日志里。
2. **保存不能抹掉 Key**：只改地址不传 `api_key` 时，Key 必须保留；
   `api_key=""` 才是「清除」。否则用户改一下端口就被登出。
3. **注入必须真的落到子进程环境**：`runner.base_env()` 要带上
   `COMFYUI_URL` / `RUNNINGHUB_API_KEY` / `RUNNINGHUB_BASE_URL`。
   没注入的话，界面显示"已连接"，出图脚本仍然报「未设置环境变量」。

全部用临时目录，不碰真实配置。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB))

from core import connections as CONN  # noqa: E402
from core import runner  # noqa: E402

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("  [NG] %s" % msg)
    return cond


def section(name):
    print("\n[%s]" % name)


class Sandbox:
    """把模块里的两个路径重定向到临时目录，并在结束后还原 + 还原环境变量。"""

    def __enter__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="conn-"))
        self._cfg, self._key = CONN.CFG_PATH, CONN.KEY_PATH
        CONN.CFG_PATH = self.tmp / "connections.json"
        CONN.KEY_PATH = self.tmp / "connections.keys.json"
        self._env = {k: os.environ.get(k) for k in
                     ("RUNNINGHUB_API_KEY", "RUNNINGHUB_BASE_URL", "COMFYUI_URL")}
        for k in self._env:
            os.environ.pop(k, None)
        # 注册表是机器状态：本机确实存在 RUNNINGHUB_API_KEY。测试要可复现，
        # 就把「用户级环境变量」这一层屏蔽掉（真实运行时它是第三优先级兜底）。
        self._reg = CONN._reg_get
        CONN._reg_get = lambda name: ""
        return self

    def __exit__(self, *exc):
        CONN.CFG_PATH, CONN.KEY_PATH = self._cfg, self._key
        CONN._reg_get = self._reg
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return False


def test_hint():
    section("1 指纹不泄露明文")
    for raw in ("sk-abcdefghijklmnop", "x" * 64):
        h = CONN.hint(raw)
        check(raw not in h, "hint 不能包含明文：%r" % h)
        check(raw[-4:] in h, "hint 应保留末 4 位便于核对：%r" % h)
    check(CONN.hint("") == "", "空 Key 的 hint 必须是空串")
    short = CONN.hint("abcdef")
    check("abcdef" not in short, "短 Key 也不能回显：%r" % short)


def test_save_keeps_key():
    section("2 保存语义：不传=保留，空串=清除")
    with Sandbox():
        CONN.save({"runninghub": {"base_url": "https://www.runninghub.cn", "workflow_id": "123"}})
        CONN.set_key("runninghub", "sk-test-key-1234567890")
        # 只改地址 → Key 必须还在
        CONN.save({"runninghub": {"base_url": "https://www.runninghub.ai"}})
        check(CONN.get_key("runninghub") == "sk-test-key-1234567890", "只改地址不应抹掉 Key")
        # api_key 不许被 save 写进非密钥文件
        CONN.save({"runninghub": {"api_key": "leaked", "workflow_id": "999"}})
        raw = CONN.CFG_PATH.read_text(encoding="utf-8")
        check("leaked" not in raw, "api_key 不能写进 connections.json")
        check(CONN.load()["runninghub"]["workflow_id"] == "999", "普通字段应正常合并")
        # 清除
        CONN.set_key("runninghub", "")
        check("runninghub" not in CONN._keys(), "空串应把 Key 从本机文件里删掉")
        check(CONN.get_key("runninghub") == "", "没有其它来源时 get_key 应为空")


def test_overview_masked():
    section("3 概览：三条通道，且无明文")
    with Sandbox():
        CONN.set_key("runninghub", "sk-very-secret-value-0001")
        ov = CONN.overview()
        kinds = [i["kind"] for i in ov["items"]]
        check(kinds == ["llm", "comfyui", "runninghub"], "通道顺序应为 llm/comfyui/runninghub，实际 %s" % kinds)
        blob = json.dumps(ov, ensure_ascii=False)
        check("sk-very-secret-value-0001" not in blob, "概览响应体不能含明文 Key")
        rh = [i for i in ov["items"] if i["kind"] == "runninghub"][0]
        check(rh["has_key"] is True, "存了 Key 应标记 has_key")
        check(rh["key_source"] == "file", "来源应为 file，实际 %r" % rh["key_source"])
        check("0001" in rh["key_hint"], "指纹应含末 4 位")


def test_env_injection():
    section("4 runner.base_env 必须注入")
    with Sandbox():
        CONN.save({"comfyui": {"base_url": "http://127.0.0.1:9999"}})
        CONN.set_key("runninghub", "sk-inject-abcdefgh")
        env = runner.base_env(None)
        check(env.get("COMFYUI_URL") == "http://127.0.0.1:9999",
              "COMFYUI_URL 应来自连接配置，实际 %r" % env.get("COMFYUI_URL"))
        check(env.get("RUNNINGHUB_API_KEY") == "sk-inject-abcdefgh",
              "RUNNINGHUB_API_KEY 应被注入")
        check(env.get("RUNNINGHUB_BASE_URL"), "RUNNINGHUB_BASE_URL 必须有值")
        # 命令级 extra 优先级最高（不能反过来被连接配置覆盖）
        env2 = runner.base_env(None, {"COMFYUI_URL": "http://127.0.0.1:1111"})
        check(env2["COMFYUI_URL"] == "http://127.0.0.1:1111", "命令级 extra 应覆盖连接配置")


def test_site_and_unknown():
    section("5 站点校验与未知通道")
    check(CONN._rh_site_ok("https://www.runninghub.ai"), ".ai 应通过")
    check(CONN._rh_site_ok("https://www.runninghub.cn"), ".cn 应通过")
    check(not CONN._rh_site_ok("https://evil.com"), "其它域名必须拒绝")
    check(not CONN._rh_site_ok("http://runninghub.ai.evil.com"), "后缀伪装必须拒绝")
    r = CONN.test("nope")
    check(r["ok"] is False and r["reason"] == "unknown_kind", "未知通道应明确报错")


def test_llm_no_key_is_explicit():
    section("6 大模型未接通时必须给原因")
    with Sandbox():
        r = CONN.test("llm")
        check(r["ok"] is False, "没有可用提供商时 ok 必须为 False")
        check(r["reason"] in ("no_provider", "all_disabled", "no_key"),
              "reason 必须是可解释的枚举，实际 %r" % r["reason"])
        check(bool(r.get("next")), "失败必须给下一步")


def main() -> int:
    print("=" * 60)
    print("连接中心测试（离线，不联网、不写真实配置）")
    print("=" * 60)
    test_hint()
    test_save_keeps_key()
    test_overview_masked()
    test_env_injection()
    test_site_and_unknown()
    test_llm_no_key_is_explicit()
    print("\n" + "-" * 60)
    if FAILS:
        print("[NG] %d 项未通过" % len(FAILS))
        return 1
    print("[OK] 连接中心全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
