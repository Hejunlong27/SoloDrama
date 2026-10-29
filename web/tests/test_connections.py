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
4. **凭据判定要认「摊平」形态**：`store.public_provider()` 把 `key_status` 摊平到顶层，
   读 `p["key_status"]["has_key"]` 恒为 None → 用户填了 Key 仍被告知「缺 Key」。
5. **用途不绑定也要能跑**：新用户只加了一个提供商，却要手动绑 10 个用途，
   否则每次生成都报「还没有绑定提供商」。自动选路一旦失效，产品等于不可用。
6. **探测必须真发请求**：只看「有没有 Key」区分不出「Key 过期 / 模型改名 /
   base_url 少了 /v1 / 代理拦截」——这四种配置看起来都是齐的。

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


class LlmSandbox:
    """把 `core.llm.store` 的配置指到临时目录（模型配置是真实机器状态，不能直接改）。"""

    def __enter__(self):
        from core.llm import store as S
        self.S = S
        self.tmp = Path(tempfile.mkdtemp(prefix="llm-"))
        self._cfg, self._keys = S.CONFIG_FILE, S.KEYS_FILE
        S.CONFIG_FILE = self.tmp / "config.json"
        S.KEYS_FILE = self.tmp / "keys.json"
        return self

    def __exit__(self, *exc):
        self.S.CONFIG_FILE, self.S.KEYS_FILE = self._cfg, self._keys
        return False

    def add(self, **kw):
        self.S.upsert_provider(kw)

    def set_enabled(self, pid, val):
        cfg = self.S.load_config()
        p = [x for x in cfg["providers"] if x.get("id") == pid][0]
        pl = {k: p.get(k) for k in ("id", "name", "kind", "base_url", "default_model",
                                    "models", "capabilities", "local", "timeout_s",
                                    "max_retries", "env_var")}
        pl["enabled"] = val
        self.S.upsert_provider(pl)


def _mock(sb, enabled=True):
    sb.add(id="m1", name="离线演练（Mock）", kind="mock", default_model="mock-episode",
           models=["mock-episode"], capabilities=["json"], enabled=enabled)


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


def test_autostart_toggle():
    section("2b 自动启动开关：改策略不该把「已连接」打回待验证")
    with Sandbox():
        CONN.save({"comfyui": {"base_url": "http://127.0.0.1:8188", "autostart": True}})
        CONN._note_test("comfyui", True, "ComfyUI 在线", "")
        check(CONN.load()["comfyui"].get("last_ok") is True, "先造一个「已连接」状态")
        # 关掉自动启动：这是策略，不是连通性变化
        CONN.save({"comfyui": {"autostart": False}})
        check(CONN.load()["comfyui"].get("last_ok") is True,
              "只切开关不该作废 last_ok（否则用户以为服务掉了）")
        check(CONN.load()["comfyui"]["autostart"] is False, "开关要真的存下来")
        # 改地址：必须作废（旧结论对不上新地址）
        CONN.save({"comfyui": {"base_url": "http://127.0.0.1:9999"}})
        check(CONN.load()["comfyui"].get("last_ok") is None, "改地址必须把旧结论清掉")
        check(CONN.load()["comfyui"]["autostart"] is False, "改地址不该把开关重置")


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
    with Sandbox(), LlmSandbox():
        r = CONN.test("llm")
        check(r["ok"] is False, "没有可用提供商时 ok 必须为 False")
        check(r["reason"] in ("no_provider", "all_disabled", "no_key"),
              "reason 必须是可解释的枚举，实际 %r" % r["reason"])
        check(bool(r.get("next")), "失败必须给下一步")


def test_prov_has_key_shapes():
    section("7 凭据判定要兼容「摊平」形态（曾导致填了 Key 仍显示缺 Key）")
    check(CONN._prov_has_key({"kind": "openai", "has_key": True}), "顶层 has_key=True 必须认")
    check(not CONN._prov_has_key({"kind": "openai", "has_key": False}), "顶层 has_key=False 必须认")
    check(CONN._prov_has_key({"kind": "openai", "key_status": {"has_key": True}}), "嵌套形态也要兼容")
    check(CONN._prov_has_key({"kind": "mock", "has_key": False}), "Mock 不需要 Key")
    check(CONN._prov_has_key({"kind": "ollama"}), "Ollama 不需要 Key")
    # 回归：真的走一遍 store 的输出形态
    with LlmSandbox() as sb:
        sb.add(id="d1", name="DeepSeek", kind="openai", base_url="https://api.deepseek.com/v1",
               default_model="deepseek-chat", models=["deepseek-chat"], enabled=True,
               api_key="sk-test-not-real-0001")
        pub = sb.S.list_providers()[0]
        check(pub.get("key_status") is None,
              "store 应把 key_status 摊平（若将来改回嵌套，这里会提醒同步改 _prov_has_key）")
        check(CONN._prov_has_key(pub) is True, "填了 Key 之后必须判定为有凭据")
        blob = json.dumps(pub, ensure_ascii=False)
        check("sk-test-not-real-0001" not in blob, "提供商视图不能含明文 Key")


def test_auto_provider():
    section("8 自动选路：真模型优先于演练，且尊重能力与停用")
    with LlmSandbox() as sb:
        _mock(sb)
        check(sb.S.auto_provider("script.generate").get("id") == "m1", "只有 Mock 时应选 Mock")
        sb.add(id="d1", name="DeepSeek", kind="openai", base_url="https://api.deepseek.com/v1",
               default_model="deepseek-chat", models=["deepseek-chat"], enabled=True,
               api_key="sk-test-not-real-0002")
        check(sb.S.auto_provider("script.generate").get("id") == "d1", "真模型应优先于 Mock")
        sb.set_enabled("d1", False)
        check(sb.S.auto_provider("script.generate").get("id") == "m1", "真模型停用后应回落到 Mock")
        # 没有 Key 的云端不能被选中（否则「就绪」却一用就 401）
        sb.add(id="n1", name="无 Key 的云端", kind="openai",
               base_url="https://api.example.com/v1", default_model="x", enabled=True)
        sb.set_enabled("d1", False)
        check(sb.S.auto_provider("script.generate").get("id") != "n1", "没 Key 的云端不能被自动选中")
        # 能力不满足 → 不选
        sb.S.templates.PURPOSE_MAP["__t_vision__"] = {"id": "__t_vision__", "label": "t",
                                                      "requires": ["vision"]}
        try:
            check(sb.S.auto_provider("__t_vision__") == {}, "能力不满足时不应自动选路")
        finally:
            sb.S.templates.PURPOSE_MAP.pop("__t_vision__", None)


def test_purposes_auto_ready():
    section("9 用途未显式绑定也应就绪，且与网关取到同一个提供商")
    with LlmSandbox() as sb:
        _mock(sb)
        items = sb.S.list_purposes()
        check(bool(items), "应有用途定义")
        check(all(x["ready"] for x in items), "全部用途应因自动选路而就绪")
        check(all(x["auto"] for x in items), "应标记为自动")
        check(not any(x["bound"] for x in items), "bound 必须仍为 False：自动 ≠ 用户显式绑定")
        g = sb.S.get_purpose("script.generate")
        check(g["provider_id"] == "m1", "网关取到的 provider 应为自动选中的那个")
        check(g["auto"] is True, "get_purpose 应标明这是自动选路")


def test_llm_probe_calls_model():
    section("10 大模型探测必须真的发一次请求")
    # ★ 必须同时沙箱 connections：`test()` 会把 last_ok/last_detail 写回连接配置。
    #   只沙箱模型配置的话，假探针结果会污染真实机器的「大模型：未接通」。
    with Sandbox(), LlmSandbox() as sb:
        _mock(sb)
        r = CONN.test("llm")
        check(r["ok"] is True, "Mock 应被真实调用并通过，实际 %r" % (r.get("reason"),))
        probes = r.get("providers") or []
        check(bool(probes) and probes[0]["ok"] is True, "应返回逐提供商的实测结果")
        # 负例：地址能解析但端口没人监听 → 必须是 network/timeout，且给下一步
        sb.set_enabled("m1", False)
        sb.add(id="bad", name="连不上的端点", kind="openai", base_url="http://127.0.0.1:9/v1",
               default_model="x", models=["x"], enabled=True, local=True, trust_env=False,
               api_key="sk-test-not-real-0003")
        r2 = CONN.test("llm")
        check(r2["ok"] is False, "连不上时 ok 必须为 False")
        kinds = {x.get("kind") for x in (r2.get("providers") or [])}
        check(bool(kinds & {"network", "timeout"}), "应归类为 network/timeout，实际 %s" % kinds)
        check(bool(r2.get("next")), "失败必须给下一步")


def main() -> int:
    print("=" * 60)
    print("连接中心测试（离线，不联网、不写真实配置）")
    print("=" * 60)
    test_hint()
    test_save_keeps_key()
    test_autostart_toggle()
    test_overview_masked()
    test_env_injection()
    test_site_and_unknown()
    test_llm_no_key_is_explicit()
    test_prov_has_key_shapes()
    test_auto_provider()
    test_purposes_auto_ready()
    test_llm_probe_calls_model()
    print("\n" + "-" * 60)
    if FAILS:
        print("[NG] %d 项未通过" % len(FAILS))
        return 1
    print("[OK] 连接中心全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
