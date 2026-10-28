#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_llm_gateway.py —— LLM 服务层离线测试（零网络、零计费）

守住 6.9 要求的四类能力：
  1. **协议适配**：正常响应 / 鉴权失败 / 超时 / 限流 / 连接错误 / 解析失败 / Schema 失败；
  2. **安全边界**：Key 打码与脱敏、SSRF 地址校验、序列化不泄露 Key；
  3. **配置持久化**：保存后重启仍在、Key 与配置分文件、能力不满足时拒发请求；
  4. **创作闭环**：草稿保存 → 人工编辑 → 确认落盘；失败绝不覆盖正式产物。

不连任何真实端点：全部走 `MockProvider` 注入。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB))

from core.llm import drafts, gateway, providers, safety, schema, store, templates  # noqa: E402
from core.llm.errors import LLMError  # noqa: E402

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("  [NG] %s" % msg)
    return cond


def section(name):
    print("\n[%s]" % name)


TMP = Path(tempfile.mkdtemp(prefix="llm-test-"))
store.use_dir(TMP / "llm")


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------
def episode_payload(ep=1, shots=8, dur=8):
    return {
        "episode": ep,
        "title": "雨夜的门",
        "cold_open": "整碗汤泼在她围裙上",
        "core_conflict": "她要保住这份工作",
        "reversal": "男人当众叫她妻子，经理立刻改口称她 señora",
        "hook": "门外黑色轿车停下，车窗降下一半",
        "hook_type": "身份悬念",
        "shots": [
            {
                "no": i, "shot": "中景, 固定", "location": "DINER", "time": "夜",
                "char": "CAMILA", "action": "她把手里的托盘放下，抬眼看向门口那个湿透的男人",
                "dialog": "无", "vo": "无", "sfx": "雨声", "dur": dur,
            }
            for i in range(1, shots + 1)
        ],
    }


def setup_provider(*, caps=("json",), enabled=True, retries=0, local=True, kind="openai",
                   base_url="http://mock.local", purpose="script.generate"):
    # ★ kind 必须是 openai/ollama，才能测到「协议适配器 + 工厂注入」这条真实路径；
    #   mock 通道另有 test_mock_channel() 专门覆盖（它不走工厂，只替换网络那一段）。
    cfg = {
        "version": 1,
        "providers": [{
            "id": "p1", "name": "Mock", "kind": kind, "base_url": base_url,
            "default_model": "mock-1", "models": ["mock-1"], "capabilities": list(caps),
            "local": local, "timeout_s": 30, "max_retries": retries,
            "env_var": "", "enabled": enabled,
        }],
        "purposes": {purpose: {"provider_id": "p1", "model": "mock-1"}},
    }
    store.save_config(cfg)
    return cfg


def mk_gateway(script):
    """box['calls'] = 构造次数；box['attempts'] = 实际调用提供商次数。"""
    box = {"script": list(script), "calls": 0, "attempts": 0, "inst": None}

    def factory(cfg, key):
        box["calls"] += 1
        inst = providers.MockProvider(cfg, key, script=box["script"])
        box["inst"] = inst
        return inst

    gw = gateway.Gateway(factory=factory)
    _orig = gw.complete

    def wrapped(*a, **kw):
        out = _orig(*a, **kw)
        box["attempts"] = len(box["inst"]._calls) if box["inst"] else 0
        return out

    gw.complete = wrapped
    return gw, box


def complete(script, **kw):
    gw, box = mk_gateway(script)
    res = gw.complete(kw.pop("purpose", "script.generate"), kw.pop("variables", {
        "blueprint_row": {"ep": 1, "hook_type": "身份悬念"},
        "style_lock": "photorealistic live-action",
        "char_header": "CAMILA: 26 岁", "scene_header": "DINER: 海边餐馆",
        "ep_seconds": 60, "shot_count": 8,
    }), **kw)
    return res, box


# ---------------------------------------------------------------------------
# 1. Schema 校验器
# ---------------------------------------------------------------------------
def test_schema():
    section("1 Schema 校验器")
    ok = schema.validate({"a": 1, "b": ["x"]}, {
        "type": "object", "required": ["a", "b"],
        "properties": {"a": {"type": "integer", "minimum": 0},
                       "b": {"type": "array", "minItems": 1, "items": {"type": "string"}}},
    })
    check(ok == [], "合法对象应通过，实际 %r" % (ok,))

    errs = schema.validate({"a": -1, "b": []}, {
        "type": "object", "required": ["a", "b"],
        "properties": {"a": {"type": "integer", "minimum": 0},
                       "b": {"type": "array", "minItems": 1, "items": {"type": "string"}}},
    })
    check(len(errs) == 2, "应报 2 处错误（最小值 + 空数组），实际 %d：%r" % (len(errs), errs))
    check(any("a" == e["path"] for e in errs), "错误路径应指向 a：%r" % (errs,))

    errs = schema.validate({"x": 1}, {"type": "object", "required": ["y"]})
    check(any("y" in e["path"] for e in errs), "缺必填应报 y")

    errs = schema.validate(4.0, {"type": "integer"})
    check(len(errs) == 1, "4.0 不应算 integer")

    errs = schema.validate({"m": "x"}, {"type": "object", "properties": {"m": {"type": "string", "enum": ["a"]}}})
    check(len(errs) == 1, "枚举外取值应报错")

    errs = schema.validate({"z": 1}, {"type": "object", "additionalProperties": False})
    check(len(errs) == 1, "additionalProperties=false 应拒绝额外字段")

    deep = schema.validate({"shots": [{"no": "x"}]}, {
        "type": "object", "properties": {"shots": {"type": "array", "items": {
            "type": "object", "properties": {"no": {"type": "integer"}}}}}})
    check(len(deep) == 1 and "shots[0].no" in deep[0]["path"], "嵌套路径应形如 shots[0].no：%r" % (deep,))


# ---------------------------------------------------------------------------
# 2. 安全：打码 / 脱敏 / SSRF
# ---------------------------------------------------------------------------
def test_safety():
    section("2 安全边界")
    check(safety.mask_key("sk-abcdef1234567890") == "sk-a…7890", "打码格式")
    check(safety.mask_key("short") == "…", "过短只回省略号")
    check(safety.mask_key("") == "", "空值回空")

    scrubbed = safety.scrub("401 invalid key sk-abcdef1234567890 in header")
    check("sk-abcdef" not in scrubbed, "scrub 必须清掉 Key：%r" % scrubbed)
    check("[已隐藏]" in scrubbed, "scrub 应留占位")

    for bad, why in [("ftp://x.com/v1", "协议"), ("file:///etc/passwd", "协议"),
                     ("http://169.254.169.254/latest", "元数据"),
                     ("http://127.0.0.1:11434", "回环"),
                     ("http://192.168.1.9/v1", "私网"),
                     ("http://user:pass@api.x.com/v1", "内嵌口令")]:
        try:
            safety.check_base_url(bad)
            check(False, "应拒绝 %s（%s）" % (bad, why))
        except LLMError as exc:
            check(exc.kind in ("blocked", "config"), "%s 应被拒绝，实际 %s" % (bad, exc.kind))

    check(safety.check_base_url("http://127.0.0.1:11434", allow_local=True)
          == "http://127.0.0.1:11434", "本地服务勾选后应放行")
    try:
        safety.check_base_url("http://169.254.169.254/v1", allow_local=True)
        check(False, "元数据地址即便 allow_local 也必须拒绝")
    except LLMError as exc:
        check(exc.kind == "blocked", "元数据地址应为 blocked")

    check(safety.check_base_url("https://api.openai.com/v1/") == "https://api.openai.com/v1",
          "尾部斜杠应归一")


# ---------------------------------------------------------------------------
# 3. 配置持久化与 Key 隔离
# ---------------------------------------------------------------------------
def test_store():
    section("3 配置持久化 / Key 隔离")
    store.use_dir(TMP / "llm-store")
    prov = store.upsert_provider({
        "id": "acc1", "name": "Acc", "kind": "openai",
        "base_url": "https://api.example.com/v1", "default_model": "m1",
        "models": ["m1", "m2"], "capabilities": ["json"], "api_key": "sk-secret-123456",
    })
    check(prov["has_key"] is True, "保存后应报告有 Key")
    check("api_key" not in prov, "对外结构不得包含 api_key 字段")
    check(prov["key_hint"] == "sk-s…3456", "Key 必须打码：%r" % prov["key_hint"])

    raw_cfg = json.loads(Path(store.CONFIG_FILE).read_text(encoding="utf-8"))
    check("sk-secret-123456" not in json.dumps(raw_cfg, ensure_ascii=False),
          "config.json 里绝不能出现明文 Key")
    check(Path(store.KEYS_FILE).is_file(), "Key 应落在独立保险箱文件")

    reloaded = store.list_providers()
    check(len(reloaded) == 1 and reloaded[0]["id"] == "acc1", "重启后配置应仍在")
    check(store.resolve_key(store.get_provider("acc1", with_key=True)) == "sk-secret-123456",
          "后端应能取到原值")

    store.set_purpose("script.generate", {"provider_id": "acc1"})
    p = store.get_purpose("script.generate")
    check(p["provider_id"] == "acc1" and p["model"] == "m1", "绑定用途应自动带默认模型")

    try:
        store.set_purpose("script.generate", {"model": "不存在"})
        check(False, "不在列表内的模型应被拒绝")
    except LLMError as exc:
        check(exc.kind == "config", "应为 config 错误，实际 %s" % exc.kind)

    out = store.delete_provider("acc1")
    check(out["unbound_purposes"] == ["script.generate"], "删除后应解绑用途：%r" % (out,))
    check(store.list_providers() == [], "删除后列表应为空")
    check(not (store.KEYS_FILE.is_file() and "acc1" in Path(store.KEYS_FILE).read_text(encoding="utf-8")),
          "删除后保险箱不应残留该 Key")


# ---------------------------------------------------------------------------
# 4. 网关：成功路径
# ---------------------------------------------------------------------------
def test_proxy_default():
    """代理开关的默认值：云端走系统代理，本地服务直连（本机只能经代理出网，硬绕会超时）。"""
    section("3b 代理默认值")
    store.use_dir(TMP / "llm-proxy")
    cloud = store.upsert_provider({
        "id": "cloud1", "name": "云端", "kind": "openai",
        "base_url": "https://api.example.com/v1", "default_model": "m1",
        "local": False,
    })
    check(cloud["trust_env"] is True, "云端默认继承系统代理")
    local = store.upsert_provider({
        "id": "local1", "name": "本地", "kind": "openai",
        "base_url": "http://127.0.0.1:8080/v1", "default_model": "m1",
        "local": True,
    })
    check(local["trust_env"] is False, "本地服务默认直连（不被代理劫走）")
    forced = store.upsert_provider({
        "id": "local1", "name": "本地", "kind": "openai",
        "base_url": "http://127.0.0.1:8080/v1", "default_model": "m1",
        "local": True, "trust_env": True,
    })
    check(forced["trust_env"] is True, "显式指定的开关优先于默认值")


def test_success():
    section("4 正常响应")
    store.use_dir(TMP / "llm-ok")
    setup_provider()
    res, box = complete([episode_payload()])
    check(res.get("ok") is True, "应成功：%r" % (res.get("error"),))
    check(len((res.get("data") or {}).get("shots") or []) == 8, "应解析出 8 个镜头")
    check((res.get("usage") or {}).get("input_tokens") == 100, "应记录输入 token")
    check(res.get("cost", {}).get("usd") is None, "供应商没给金额时必须为未知")
    check(box["calls"] == 1, "只应构造一次提供商")
    check(res.get("request_id"), "应返回 request_id")

    row = store.usage(limit=10)["items"][0]
    check(row["ok"] is True and row.get("prompt_sha"), "用量日志应记录且不含正文")
    check("messages" not in json.dumps(row), "用量日志不得包含提示词正文")

    # 代码围栏与前后寒暄都要能解析
    fenced = "好的，结果如下：\n```json\n" + json.dumps(episode_payload(), ensure_ascii=False) + "\n```\n以上。"
    res, _ = complete([fenced])
    check(res.get("ok") is True, "带围栏的输出应能解析：%r" % (res.get("error"),))


# ---------------------------------------------------------------------------
# 5. 网关：错误分类与重试策略
# ---------------------------------------------------------------------------
def test_errors():
    section("5 错误分类 / 重试策略")
    store.use_dir(TMP / "llm-err")

    cases = [
        ("auth", LLMError("auth", "Key 无效"), 0, False),
        ("timeout", LLMError("timeout", "超时"), 1, False),
        ("rate_limit", LLMError("rate_limit", "限流"), 1, False),
        ("network", LLMError("network", "连不上"), 1, False),
    ]
    for kind, exc, retries, expect_ok in cases:
        setup_provider(retries=retries)
        script = [exc] * (retries + 3)
        res, box = complete(script)
        check(res.get("ok") is expect_ok, "%s 应失败" % kind)
        check((res.get("error") or {}).get("kind") == kind,
              "%s 分类错误：%r" % (kind, (res.get("error") or {}).get("kind")))
        check(box["calls"] == 1, "%s 不应重复构造提供商" % kind)

    # 不可重试的鉴权错误：即便配了 3 次重试，也只调用一次
    setup_provider(retries=3)
    gw, box = mk_gateway([LLMError("auth", "Key 无效")] * 5)
    res = gw.complete("script.generate", _vars())
    check(res.get("ok") is False and box["attempts"] == 1,
          "鉴权失败不得重试：实际调用 %d 次（应 1）" % box["attempts"])
    check("sk-" not in json.dumps(res, ensure_ascii=False) or "[已隐藏]" in json.dumps(res, ensure_ascii=False),
          "错误返回不得带明文 Key")

    # 可重试的超时：配 1 次重试 → 消耗 2 条脚本
    setup_provider(retries=1)
    gw, box = mk_gateway([LLMError("timeout", "超时")] * 3)
    res = gw.complete("script.generate", _vars())
    check(res.get("ok") is False and box["attempts"] == 2,
          "超时应重试 1 次（共 2 次调用），实际 %d" % box["attempts"])

    # 解析失败 / Schema 失败
    setup_provider()
    res, _ = complete(["这不是 JSON，我是散文"])
    check((res.get("error") or {}).get("kind") == "parse", "非 JSON 应报 parse：%r" % (res.get("error"),))

    bad = episode_payload(shots=3)
    res, _ = complete([bad])
    check((res.get("error") or {}).get("kind") == "schema", "镜头数不足应报 schema")
    check(len(res.get("schema_errors") or []) >= 1, "应给出结构化 schema_errors")

    # 能力不足：不构造提供商、不发请求
    setup_provider(caps=("tools",))
    res, box = complete([episode_payload()])
    check((res.get("error") or {}).get("kind") == "unsupported",
          "缺 json 能力应报 unsupported：%r" % (res.get("error"),))
    check(box["calls"] == 0, "能力不足时不应构造提供商（省一次失败）")

    # 未绑定用途
    store.save_config({"version": 1, "providers": [], "purposes": {}})
    res, _ = complete([episode_payload()])
    check((res.get("error") or {}).get("kind") == "config", "未绑定应报 config")
    check("AI 模型中心" in (res.get("error") or {}).get("message", ""), "应指引去模型中心绑定")

    # 停用
    setup_provider(enabled=False)
    res, _ = complete([episode_payload()])
    check((res.get("error") or {}).get("kind") == "config", "停用的提供商应拒绝")

    # 未知用途
    res, box = complete([episode_payload()], purpose="not.a.purpose")
    check((res.get("error") or {}).get("kind") == "not_found", "未知用途应报 not_found")
    check(box["calls"] == 0, "未知用途不应构造提供商")


def _vars():
    return {
        "blueprint_row": {"ep": 1}, "style_lock": "x", "char_header": "A: b",
        "scene_header": "C: d", "ep_seconds": 60, "shot_count": 8,
    }


# ---------------------------------------------------------------------------
# 6. 模板
# ---------------------------------------------------------------------------
def test_templates():
    section("6 模板与用途")
    all_t = templates.all_templates()
    check(len(all_t) == 7, "应有 7 个模板，实际 %d" % len(all_t))
    check(all(t["ok"] for t in all_t), "模板正文都应能读到：%r"
          % [t["id"] for t in all_t if not t["ok"]])
    check(all(t["body_sha"] for t in all_t), "每个模板都应有指纹")

    s = templates.describe("s3-script-rewrite")
    check("剧本" in s["body"], "应读到仓库原文")
    check(s["schema_id"] == "script.episode", "应绑定单集 Schema")

    system, user = templates.render_parts("s3-script-rewrite", _vars())
    check("## 本次输入" in user and "## 输出契约" in user, "user 段应含输入与契约")
    check("本次输入" not in system, "system 段只放方法论，不混入输入")
    check('"shots"' in user, "输出契约应内嵌 Schema")

    try:
        templates.render_parts("s3-script-rewrite", {"style_lock": "x"})
        check(False, "缺变量应报错")
    except LLMError as exc:
        check(exc.kind == "config", "缺变量应为 config，实际 %s" % exc.kind)

    check(len(templates.PURPOSES) == 7, "应有 7 个业务用途")
    check(templates.PURPOSE_MAP["script.generate"]["requires"] == ["json"], "剧本生成应要求 json 能力")


# ---------------------------------------------------------------------------
# 7. 创作闭环
# ---------------------------------------------------------------------------
def _ws(fixture=True):
    ws = Path(tempfile.mkdtemp(prefix="ws-"))
    if fixture:
        bp = {
            "title": "失忆的总裁", "total_ep": 3, "ep_seconds": 60, "platform": "ReelShort",
            "style_lock": "photorealistic live-action cinematography",
            "episodes": [
                {"ep": 1, "act": "起", "cold_open": "汤泼在她围裙上",
                 "core_conflict": "她要保住工作", "reversal": "男人当众叫她妻子",
                 "hook_type": "身份悬念", "hook": "门外轿车停下"},
                {"ep": 2, "act": "承", "cold_open": "她被叫进办公室",
                 "core_conflict": "经理要辞退她", "reversal": "男人出示结婚证",
                 "hook_type": "危机逼近", "hook": "闪光灯亮起"},
                {"ep": 3, "act": "转", "cold_open": "记者堵在门口",
                 "core_conflict": "身份被公开", "reversal": "她想起了一切",
                 "hook_type": "秘密揭露", "hook": "她拿起电话"},
            ],
        }
        (ws / "creation" / "03-script").mkdir(parents=True)
        (ws / "creation" / "03-script" / "blueprint.json").write_text(
            json.dumps(bp, ensure_ascii=False, indent=2), encoding="utf-8")
        (ws / "creation" / "03-script" / "diagnosis.json").write_text(
            json.dumps({"structure_confirmed": True, "A_diagnosis": {"hook": "x"}},
                       ensure_ascii=False), encoding="utf-8")
        (ws / "bible").mkdir(parents=True)
        (ws / "bible" / "world-bible.json").write_text(json.dumps({
            "characters": [{"code": "CAMILA", "name": "卡米拉", "visual_anchor": "方圆过渡", "palette": "#365F63"},
                           {"code": "ADRIAN", "name": "阿德里安", "visual_anchor": "长椭圆", "palette": "#7B3C32"}],
            "scenes": [{"code": "DINER", "desc": "海边小餐馆,深夜"}, {"code": "STREET", "desc": "雨夜街道"}],
        }, ensure_ascii=False), encoding="utf-8")
    return ws


def test_mock_channel():
    """离线演练通道：不发网络请求，但下游（解析→Schema→草稿→落盘闸门）全部真实执行。"""
    section("7b 离线演练通道（Mock）")
    store.use_dir(TMP / "llm-mock")

    prov = store.upsert_provider({
        "id": "mk", "name": "离线演练", "kind": "mock",
        "default_model": "mock-episode", "capabilities": ["json"], "enabled": True,
        "api_key": "sk-should-be-dropped",
    })
    check(prov["base_url"] == "mock://local", "演练通道地址固定为 mock://local")
    check(prov["has_key"] is False, "演练通道不保存 Key（传了也丢弃）")
    check(prov["local"] is True, "演练通道视为本地服务")

    store.set_purpose("script.generate", {"provider_id": "mk"})
    gw = gateway.Gateway(factory=lambda cfg, key: (_ for _ in ()).throw(AssertionError("mock 不应构造适配器")))
    res = gw.complete("script.generate", {
        # cold_open 用真实长度：Schema 要求 >=4，演练输出会照抄 blueprint 的字段
        "blueprint_row": {"ep": 2, "hook_type": "危机逼近", "cold_open": "汤泼在她围裙上"},
        "style_lock": "photorealistic", "char_header": "# CHAR: CAMILA: a; ADRIAN: b",
        "scene_header": "# SCENE: DINER: c", "ep_seconds": 60, "shot_count": 8,
    })
    check(res.get("ok") is True, "演练生成应成功：%r" % (res.get("error"),))
    check(res.get("simulated") is True, "必须标注 simulated=true")
    shots = (res.get("data") or {}).get("shots") or []
    check(len(shots) == 8, "应产出 8 镜（按 shot_count）")
    check(all(4 <= int(s["dur"]) <= 15 for s in shots), "每镜 DUR 落在 4-15")
    check(shots[0]["char"] == "CAMILA", "角色代号取自 HEADER")
    check(shots[0]["location"] == "DINER", "场景代号取自 HEADER")
    check((res.get("cost") or {}).get("usd") is None, "演练不产生金额")

    row = store.usage(limit=5)["items"][0]
    check(row.get("simulated") is True, "用量记录带 simulated 标记")
    check((res.get("data") or {}).get("hook_type") == "危机逼近", "钩子类型沿用 blueprint 规划")

    # 演练草稿默认不能落盘
    ws = _ws()
    d = drafts.generate(ws, 1, gateway=gw)["draft"]
    check(d.get("simulated") is True, "草稿应带 simulated 标记")
    try:
        drafts.confirm(ws, d["id"])
        check(False, "演练草稿默认必须被拒绝落盘")
    except LLMError as exc:
        check("演练" in exc.text, "拒绝理由应说明是演练草稿：%r" % exc.text)
    check(not (ws / "script" / "ep_01.md").exists(), "被拒绝时不得写文件")
    out = drafts.confirm(ws, d["id"], allow_simulated=True)
    check(out.get("ok") is True and out.get("simulated") is True, "显式放行后可落盘且标注 simulated")
    check((ws / "script" / "ep_01.md").is_file(), "落盘文件存在")

    # 测试连接不应联网
    t = gw.test_provider("mk")
    check(t.get("ok") is True and t.get("mode") == "mock", "演练通道连接测试直接通过")


def test_drafts():
    section("7 创作闭环（草稿 → 编辑 → 确认）")
    store.use_dir(TMP / "llm-draft")
    setup_provider()
    ws = _ws()

    g = drafts.gates(ws)
    check(g["ok"] is True, "前置齐备时应放行：%r" % (g["items"],))
    check(g["ep_count"] == 3, "应读到 3 集")

    ctx = drafts.context(ws, 1)
    check(ctx["header_source"] == "blueprint", "无正式剧本时 HEADER 来自 blueprint")
    check("CAMILA" in "\n".join(ctx["header"]), "HEADER 应含 world-bible 的角色代号")
    check(ctx["target"].endswith("ep_01.md"), "落点应为 ep_01.md：%s" % ctx["target"])

    gw, _ = mk_gateway([episode_payload()])
    out = drafts.generate(ws, 1, gateway=gw)
    check(out.get("ok") is True, "生成应成功：%r" % (out.get("error"),))
    d = out["draft"]
    check(d["status"] == "draft", "初始状态应为 draft")
    check("[SC-01]" in d["md"] and "DUR: 8" in d["md"], "应渲染成 FFS 格式")
    check(d["md"].startswith("# TITLE: 失忆的总裁"), "HEADER 应置顶")
    check(d["checks"][0]["ok"] is True, "自检应通过")

    listed = drafts.list_drafts(ws)["items"]
    check(len(listed) == 1 and listed[0]["ep"] == 1, "草稿列表应有 1 条")

    target = Path(ctx["target"])
    check(not target.exists(), "生成阶段绝不能写正式文件")

    # 人工编辑（改 md）
    upd = drafts.update_draft(ws, d["id"], {"md": d["md"].replace("失忆的总裁", "失忆的总裁（人工改）")})
    check("（人工改）" in upd["draft"]["md"], "编辑应生效")

    res = drafts.confirm(ws, d["id"])
    check(res.get("ok") is True, "确认应成功：%r" % (res,))
    check(target.is_file(), "确认后应写出正式文件")
    text = target.read_text(encoding="utf-8")
    check("（人工改）" in text, "落盘内容应包含人工修改")
    check("\r\n" not in text, "必须写 LF，不能 CRLF")
    check(drafts.get_draft(ws, d["id"])["draft"]["status"] == "confirmed", "状态应转 confirmed")

    # 幂等
    again = drafts.confirm(ws, d["id"])
    check(again.get("already") is True, "重复确认应幂等")

    # 覆盖保护
    gw2, _ = mk_gateway([episode_payload()])
    out2 = drafts.generate(ws, 1, gateway=gw2)
    d2 = out2["draft"]
    try:
        drafts.confirm(ws, d2["id"])
        check(False, "目标已存在且未勾选覆盖时必须拒绝")
    except LLMError as exc:
        check(exc.kind == "config" and "覆盖" in exc.text, "应明确要求覆盖确认：%r" % exc.text)

    res3 = drafts.confirm(ws, d2["id"], overwrite=True)
    check(res3.get("ok") is True and res3.get("backup"), "覆盖前必须留备份")
    check(Path(res3["backup"]).is_file(), "备份文件应存在")

    # 指纹不符 → 拒绝
    gw3, _ = mk_gateway([episode_payload()])
    d3 = drafts.generate(ws, 1, gateway=gw3)["draft"]
    try:
        drafts.confirm(ws, d3["id"], overwrite=True, expected_sha="deadbeef")
        check(False, "指纹不符时应拒绝覆盖")
    except LLMError as exc:
        check("指纹" in exc.text, "应说明指纹不一致：%r" % exc.text)


def test_draft_failure_is_safe():
    section("8 生成失败不碰正式产物 / 门禁")
    store.use_dir(TMP / "llm-safe")
    ws = _ws()
    formal = ws / "script" / "ep_01.md"
    formal.parent.mkdir(parents=True)
    original = "# TITLE: 人工写的旧版\n# EP: 01/3\n# PLATFORM: ReelShort\n# STYLE LOCK: x\n# CHAR: CAMILA: a\n# SCENE: DINER: b\n"
    formal.write_text(original, encoding="utf-8")

    setup_provider()
    gw, _ = mk_gateway([LLMError("auth", "Key 无效")])
    out = drafts.generate(ws, 1, gateway=gw)
    check(out.get("ok") is False, "生成失败应返回 ok=false")
    check(formal.read_text(encoding="utf-8") == original, "生成失败绝不能改动正式剧本")

    # 超口径的输出（镜头数 3）应被拦下且不产生草稿
    gw2, _ = mk_gateway([episode_payload(shots=3)])
    out2 = drafts.generate(ws, 1, gateway=gw2)
    check(out2.get("ok") is False, "超口径输出应被拒绝")
    check(len(drafts.list_drafts(ws)["items"]) == 0, "被拒绝时不应当作草稿保存")

    # 诊断卡未确认 → 拒绝落盘（与 build --emit 的退出码 4 同口径）
    (ws / "creation" / "03-script" / "diagnosis.json").write_text(
        json.dumps({"structure_confirmed": False}), encoding="utf-8")
    g = drafts.gates(ws)
    check(g["ok"] is False and g["blocking"] is True, "未确认诊断卡应阻塞")
    gw3, _ = mk_gateway([episode_payload()])
    d = drafts.generate(ws, 1, gateway=gw3)["draft"]
    try:
        drafts.confirm(ws, d["id"])
        check(False, "诊断卡未确认时不得落盘")
    except LLMError as exc:
        check("诊断" in exc.text, "应提示先确认诊断卡：%r" % exc.text)

    # 越界集号
    try:
        drafts.context(ws, 99)
        check(False, "越界集号应报错")
    except LLMError as exc:
        check(exc.kind == "config", "越界集号应为 config")


# ---------------------------------------------------------------------------
def main() -> int:
    t0 = time.time()
    print("=" * 62)
    print("LLM 服务层离线测试（零网络 / 零计费）")
    print("临时目录：%s" % TMP)
    print("=" * 62)
    test_schema()
    test_safety()
    test_store()
    test_proxy_default()
    test_success()
    test_errors()
    test_templates()
    test_mock_channel()
    test_drafts()
    test_draft_failure_is_safe()

    print("\n" + "-" * 62)
    if FAILS:
        print("[NG] %d 项未通过：" % len(FAILS))
        for f in FAILS[:40]:
            print("  - %s" % f)
        return 1
    print("[OK] LLM 服务层全部通过（%.2fs）" % (time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
