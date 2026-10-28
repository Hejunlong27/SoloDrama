#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_llm_e2e.py —— HTTP 端到端集成测试（本地伪造上游，零费用）

为什么要有这一层：
  `test_llm_gateway.py` 验的是网关逻辑（Mock 注入）；这里验的是**真实链路**——
  HTTP 路由 → 提供商适配器（真 httpx 请求）→ 网关 → 草稿 → 确认落盘 → 磁盘字节。
  上游是一个本地伪造的 OpenAI 兼容服务（127.0.0.1 随机端口），不发一个外网请求、不花一分钱。

运行（需要 fastapi/httpx，用 Web 的 venv）：
    <python-envs>/solodrama-web/Scripts/python.exe web/tests/test_llm_e2e.py

覆盖：
  * 安全：SSRF 拒绝、Key 不回显、跨站写请求、计费接口缺 confirm → 428、只读模式；
  * 配置：新建/绑定/持久化；
  * 闭环：预览 → 生成草稿 → 人工改 → 确认落盘（含备份与幂等）；
  * 失败：上游 401 / 烂 JSON / Schema 不符时的分类。
"""
from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB))

try:
    from fastapi.testclient import TestClient  # noqa: PLC0415
except Exception as exc:  # noqa: BLE001
    print("[SKIP] 需要 fastapi + httpx（用 web/requirements-web.txt 的 venv 运行）：%s" % exc)
    sys.exit(0)

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("  [NG] %s" % msg)
    return cond


def section(name):
    print("\n[%s]" % name)


# ---------------------------------------------------------------------------
# 伪造上游：兼容 OpenAI 的最小实现
# ---------------------------------------------------------------------------
STATE = {"reply": "", "status": 200, "models": ["mock-a", "mock-b"], "hits": []}


def episode_payload(ep=1, shots=8, dur=8):
    return {
        "episode": ep, "title": "雨夜的门",
        "cold_open": "整碗汤泼在她围裙上", "core_conflict": "她要保住这份工作",
        "reversal": "男人当众叫她妻子，经理立刻改口", "hook": "门外黑色轿车停下",
        "hook_type": "身份悬念",
        "shots": [{"no": i, "shot": "中景, 固定", "location": "DINER", "time": "夜",
                   "char": "CAMILA", "action": "她把手里的托盘放下，抬眼看向门口那个湿透的男人",
                   "dialog": "无", "vo": "无", "sfx": "雨声", "dur": dur}
                  for i in range(1, shots + 1)],
    }


class FakeUpstream(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # 静音
        pass

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        STATE["hits"].append(("GET", self.path, dict(self.headers)))
        if self.path.rstrip("/").endswith("/models"):
            return self._json(200, {"data": [{"id": m} for m in STATE["models"]]})
        return self._json(404, {"error": {"message": "not found"}})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        STATE["hits"].append(("POST", self.path, dict(self.headers)))
        if STATE["status"] != 200:
            return self._json(STATE["status"], {"error": {"message": STATE["reply"] or "upstream error"}})
        return self._json(200, {
            "id": "chatcmpl-fake", "object": "chat.completion", "model": "mock-a",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": STATE["reply"]},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1234, "completion_tokens": 567, "total_tokens": 1801},
        })


def start_upstream():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    srv = HTTPServer(("127.0.0.1", port), FakeUpstream)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://127.0.0.1:%d/v1" % port


# ---------------------------------------------------------------------------
# 临时工作区（形状与真实项目一致：creation/03-script + bible + script/）
# ---------------------------------------------------------------------------
def make_ws(confirmed=True, total=3):
    ws = Path(tempfile.mkdtemp(prefix="e2e-ws-"))
    (ws / "creation" / "03-script").mkdir(parents=True)
    bp = {"title": "失忆的总裁", "total_ep": total, "ep_seconds": 60, "platform": "ReelShort",
          "style_lock": "photorealistic live-action cinematography",
          "episodes": [{"ep": i, "act": "起", "cold_open": "汤泼在她围裙上",
                        "core_conflict": "她要保住工作", "reversal": "男人当众叫她妻子",
                        "hook_type": "身份悬念", "hook": "门外轿车停下"} for i in range(1, total + 1)]}
    (ws / "creation" / "03-script" / "blueprint.json").write_text(
        json.dumps(bp, ensure_ascii=False, indent=2), encoding="utf-8")
    (ws / "creation" / "03-script" / "diagnosis.json").write_text(
        json.dumps({"structure_confirmed": confirmed}), encoding="utf-8")
    (ws / "bible").mkdir()
    (ws / "bible" / "world-bible.json").write_text(json.dumps({
        "characters": [{"code": "CAMILA", "name": "卡米拉", "visual_anchor": "方圆过渡", "palette": "#365F63"}],
        "scenes": [{"code": "DINER", "desc": "海边小餐馆,深夜"}],
    }, ensure_ascii=False), encoding="utf-8")
    return ws


def main() -> int:
    t0 = time.time()
    srv, base = start_upstream()
    tmp = Path(tempfile.mkdtemp(prefix="e2e-store-"))
    os.environ["SOLODRAMA_LLM_DIR"] = str(tmp / "llm")
    os.environ["SOLODRAMA_CONSOLE_READONLY"] = "0"

    import app as appmod  # noqa: PLC0415
    from core.llm import store as llm_store  # noqa: PLC0415

    llm_store.use_dir(tmp / "llm")
    ws = make_ws()

    print("=" * 62)
    print("HTTP 端到端测试（伪造上游 %s）" % base)
    print("临时工作区 %s" % ws)
    print("=" * 62)

    with TestClient(appmod.app, base_url="http://127.0.0.1") as c:
        # ---------------- 1 安全边界 ----------------
        section("1 安全边界")
        for bad, why in [("ftp://x.com/v1", "协议"), ("http://169.254.169.254/v1", "云元数据")]:
            r = c.post("/api/llm/providers", json={"name": "x", "kind": "openai",
                                                   "base_url": bad, "default_model": "m"})
            check(r.status_code == 400, "%s 应被拒绝，实际 %d" % (bad, r.status_code))
            detail = r.json().get("detail") or {}
            check(isinstance(detail, dict) and detail.get("kind") == "blocked",
                  "%s 应报 blocked：%r" % (bad, detail))

        r = c.post("/api/llm/providers", json={"name": "内网", "kind": "openai",
                                               "base_url": "http://127.0.0.1:9/v1", "default_model": "m"})
        check(r.status_code == 400, "未声明本地服务时，回环地址应被拒绝")

        r = c.post("/api/llm/providers", json={"name": "x", "kind": "nope",
                                               "base_url": "https://a.com/v1", "default_model": "m"})
        check(r.status_code == 400, "未知协议类型应被拒绝")

        r = c.post("/api/llm/providers", json={"name": "x", "kind": "openai", "base_url": base,
                                               "default_model": "mock-a", "local": True},
                   headers={"Origin": "http://evil.example"})
        check(r.status_code == 403, "跨站写请求应被拒绝，实际 %d" % r.status_code)

        r = c.post("/api/studio/script/generate?ws=%s" % ws.as_posix(), json={"ep": 1})
        check(r.status_code == 428, "生成缺 confirm 应 428，实际 %d" % r.status_code)
        r = c.post("/api/studio/drafts/none/confirm?ws=%s" % ws.as_posix(), json={})
        check(r.status_code == 428, "落盘缺 confirm 应 428，实际 %d" % r.status_code)

        # ---------------- 2 配置 ----------------
        section("2 提供商配置与持久化")
        r = c.post("/api/llm/providers", json={
            "id": "fake", "name": "本地伪造上游", "kind": "openai", "base_url": base,
            "default_model": "mock-a", "models": ["mock-a", "mock-b"],
            "capabilities": ["json"], "local": True, "timeout_s": 20, "max_retries": 0,
            "api_key": "sk-e2e-secret-0001",
        })
        check(r.status_code == 200, "创建提供商应 200，实际 %d：%s" % (r.status_code, r.text[:200]))
        prov = r.json().get("provider") or {}
        check(prov.get("has_key") is True, "应报告已配置 Key")
        check("api_key" not in prov, "响应不得含 api_key 字段")
        check("sk-e2e-secret-0001" not in r.text, "响应不得出现明文 Key")
        check(prov.get("key_hint") == "sk-e…0001", "Key 应打码：%r" % prov.get("key_hint"))

        raw_cfg = (llm_store.CONFIG_FILE).read_text(encoding="utf-8")
        check("sk-e2e-secret-0001" not in raw_cfg, "config.json 不得出现明文 Key")

        r = c.get("/api/llm/providers")
        check(r.status_code == 200 and len(r.json()["items"]) == 1, "列表应有 1 个提供商")
        check("sk-e2e-secret-0001" not in r.text, "列表接口不得回显 Key")

        # ---------------- 3 连接测试 ----------------
        section("3 连接测试（只读，0 费用）")
        BEFORE = len(STATE["hits"])
        r = c.post("/api/llm/providers/fake/test")
        check(r.status_code == 200, "测试接口应 200，实际 %d" % r.status_code)
        j = r.json()
        check(j.get("ok") is True, "应连通：%r" % (j,))
        check(j.get("model_count") == 2, "应读到 2 个模型：%r" % (j.get("models"),))
        new_hits = STATE["hits"][BEFORE:]
        check(all(h[0] == "GET" for h in new_hits), "只读测试不得发起生成请求：%r" % (new_hits,))
        check(any("Bearer sk-e2e-secret-0001" == h[2].get("Authorization") for h in new_hits),
              "请求应带上 Authorization 头")

        r = c.post("/api/llm/providers/fake/test?deep=1")
        check(r.status_code == 428, "deep 测试缺 confirm 应 428")

        # ---------------- 4 用途绑定与预览 ----------------
        section("4 用途绑定 / 提示词预览")
        r = c.get("/api/llm/purposes")
        check(r.status_code == 200, "用途列表应 200")
        gen = [p for p in r.json()["items"] if p["id"] == "script.generate"][0]
        check(gen["bound"] is False, "初始应为未绑定")

        # ★ 契约变更（2026-10-28）：未显式绑定不再直接报 config，而是**自动选路**。
        #   旧行为要求新用户手动绑定 10 个用途，否则每次生成都失败——那不是配置，是刁难。
        #   这里守住三条：① 不能 500；② 不能因「没绑定」失败；③ 状态要如实标为自动。
        r = c.post("/api/studio/script/generate?ws=%s" % ws.as_posix(), json={"ep": 1, "confirm": True})
        check(r.status_code == 200, "未绑定时应返回业务结果而非 500")
        _b = r.json()
        _err = _b.get("error") or {}
        check(not (_b.get("ok") is False and _err.get("kind") == "config"),
              "未绑定时不应再要求手动绑定（应自动选路）：%r" % (_err,))
        _gen = [p for p in c.get("/api/llm/purposes").json()["items"]
                if p["id"] == "script.generate"][0]
        check(_gen["auto"] is True and _gen["ready"] is True,
              "未显式绑定时应标记为自动选路且可用：%r" % ({k: _gen.get(k) for k in
                                                     ("auto", "ready", "bound", "auto_provider_id")},))

        r = c.post("/api/llm/purposes/script.generate", json={"provider_id": "fake"})
        check(r.status_code == 200, "绑定应成功：%s" % r.text[:160])
        check(r.json()["purpose"]["model"] == "mock-a", "应自动带默认模型")
        check(r.json()["purpose"]["ready"] is True, "绑定后应 ready")

        r = c.get("/api/studio/script/context?ws=%s&ep=1" % ws.as_posix())
        cx = r.json()
        check(r.status_code == 200, "上下文应 200：%s" % r.text[:160])
        check(cx["target"].endswith("ep_01.md"), "落点应为 ep_01.md：%s" % cx.get("target"))
        check(any("CAMILA" in ln for ln in cx["header"]), "HEADER 应含角色代号")

        variables = {
            "blueprint_row": cx["blueprint_row"], "style_lock": cx["style_lock"],
            "char_header": cx["header"][4], "scene_header": cx["header"][5],
            "ep_seconds": cx["ep_seconds"], "shot_count": cx["shot_count"],
        }
        r = c.post("/api/llm/preview", json={"purpose": "script.generate", "variables": variables})
        check(r.status_code == 200, "预览应 200：%s" % r.text[:200])
        pv = r.json()
        check(len(pv["system"]) > 500 and "shots" in pv["user"], "预览应含仓库原文与 Schema")

        # ---------------- 5 生成草稿 ----------------
        section("5 生成草稿（真实 HTTP 调用）")
        STATE["reply"] = json.dumps(episode_payload(), ensure_ascii=False)
        r = c.post("/api/studio/script/generate?ws=%s" % ws.as_posix(), json={"ep": 1, "confirm": True})
        check(r.status_code == 200, "生成应 200：%s" % r.text[:200])
        out = r.json()
        check(out.get("ok") is True, "生成应成功：%r" % (out.get("error"),))
        d = out["draft"]
        check(d["status"] == "draft", "应为草稿状态")
        check("[SC-01]" in d["md"] and "DUR: 8" in d["md"], "应渲染成 FFS 格式")
        check(not (ws / "script" / "ep_01.md").exists(), "生成阶段绝不能写正式文件")

        r = c.get("/api/studio/drafts?ws=%s" % ws.as_posix())
        check(len(r.json()["items"]) == 1, "草稿列表应有 1 条")

        r = c.get("/api/llm/usage?limit=10")
        u = r.json()
        check(u["summary"]["ok"] >= 1, "应记录成功调用：%r" % (u["summary"],))
        check((u["items"][0]["cost"] or {}).get("usd") is None, "上游没给金额时必须为未知")
        check(u["items"][0]["usage"]["input_tokens"] == 1234, "应记录上游 usage")

        # ---------------- 6 人工编辑 + 确认落盘 ----------------
        section("6 人工编辑 / 确认落盘")
        r = c.post("/api/studio/drafts/%s/save?ws=%s" % (d["id"], ws.as_posix()),
                   json={"md": d["md"].replace("失忆的总裁", "失忆的总裁（人工改）")})
        check(r.status_code == 200, "保存修改应 200：%s" % r.text[:200])

        r = c.post("/api/studio/drafts/%s/confirm?ws=%s" % (d["id"], ws.as_posix()),
                   json={"confirm": True})
        check(r.status_code == 200, "确认应 200：%s" % r.text[:260])
        res = r.json()
        check(res.get("ok") is True, "落盘应成功：%r" % (res,))
        target = ws / "script" / "ep_01.md"
        check(target.is_file(), "应写出正式文件")
        text = target.read_text(encoding="utf-8")
        check("（人工改）" in text, "落盘内容应含人工修改")
        check("\r\n" not in text, "必须 LF")

        r = c.post("/api/studio/drafts/%s/confirm?ws=%s" % (d["id"], ws.as_posix()),
                   json={"confirm": True})
        check(r.json().get("already") is True, "重复确认应幂等")

        # ---------------- 7 上游失败分类 ----------------
        section("7 上游失败分类")
        STATE["status"] = 401
        STATE["reply"] = "invalid api key sk-e2e-secret-0001"
        r = c.post("/api/studio/script/generate?ws=%s" % ws.as_posix(), json={"ep": 2, "confirm": True})
        out = r.json()
        check(out.get("ok") is False, "上游 401 应失败")
        check(out["error"]["kind"] == "auth", "应归类 auth：%r" % (out.get("error"),))
        check("sk-e2e-secret-0001" not in json.dumps(out, ensure_ascii=False),
              "错误信息不得回显 Key")

        STATE["status"] = 200
        STATE["reply"] = "好的，这是剧本：{\"not\": \"valid\"}"
        r = c.post("/api/studio/script/generate?ws=%s" % ws.as_posix(), json={"ep": 2, "confirm": True})
        out = r.json()
        check(out.get("ok") is False and out["error"]["kind"] in ("schema", "parse"),
              "非契约输出应被拦下：%r" % (out.get("error"),))
        check(not (ws / "script" / "ep_02.md").exists(), "失败不得产生正式文件")

        # ---------------- 8 门禁：诊断卡未确认 ----------------
        section("8 门禁：诊断卡未确认时拒绝落盘")
        ws2 = make_ws(confirmed=False)
        STATE["reply"] = json.dumps(episode_payload(), ensure_ascii=False)
        c.post("/api/llm/providers", json={
            "id": "fake", "name": "本地伪造上游", "kind": "openai", "base_url": base,
            "default_model": "mock-a", "models": ["mock-a"], "capabilities": ["json"],
            "local": True, "timeout_s": 20, "max_retries": 0})
        c.post("/api/llm/purposes/script.generate", json={"provider_id": "fake"})
        r = c.post("/api/studio/script/generate?ws=%s" % ws2.as_posix(), json={"ep": 1, "confirm": True})
        check(r.json().get("ok") is True, "草稿阶段允许生成：%r" % (r.json().get("error"),))
        did = r.json()["draft"]["id"]
        r = c.post("/api/studio/drafts/%s/confirm?ws=%s" % (did, ws2.as_posix()), json={"confirm": True})
        check(r.status_code == 400, "未确认诊断卡应拒绝落盘，实际 %d" % r.status_code)
        detail = r.json().get("detail") or {}
        check("诊断" in (detail.get("message") if isinstance(detail, dict) else str(detail)),
              "应提示先确认诊断卡：%r" % (detail,))
        check(not (ws2 / "script" / "ep_01.md").exists(), "门禁拦下时不得写文件")

        # ---------------- 9 页面可达 ----------------
        section("9 页面与静态资源")
        for p in ("/studio/", "/studio/js/views/models.js", "/studio/js/views/creation.js",
                  "/studio/css/tokens.css"):
            r = c.get(p)
            check(r.status_code == 200, "%s 应 200，实际 %d" % (p, r.status_code))
        r = c.get("/api/studio/capabilities")
        caps = r.json()["items"]
        check(caps.get("llm", {}).get("ok") is True, "能力表应标 llm 已接入")
        check(caps.get("llm_stream", {}).get("ok") is False, "未做的能力必须诚实标注")

        # ---------------- 10 离线演练通道：HTTP 全链路（不需要任何外部服务） ----------------
        section("10 离线演练通道：从 HTTP 走完整条链路")
        ws3 = make_ws()
        r = c.post("/api/llm/providers", json={
            "id": "mock1", "name": "离线演练", "kind": "mock",
            "default_model": "mock-episode", "capabilities": ["json"],
            "api_key": "sk-must-be-dropped",
        })
        check(r.status_code == 200, "演练通道可创建：%s" % r.text[:160])
        mp = r.json().get("provider") or {}
        check(mp.get("base_url") == "mock://local", "演练地址固定")
        check(mp.get("has_key") is False, "演练通道不落 Key")

        r = c.post("/api/llm/providers/mock1/test")
        check(r.status_code == 200 and r.json().get("mode") == "mock", "演练连接测试通过")
        check(r.json().get("ok") is True, "演练连接测试 ok=true")

        r = c.post("/api/llm/purposes/script.generate", json={"provider_id": "mock1"})
        check(r.status_code == 200 and r.json()["purpose"]["ready"] is True, "用途已绑定演练通道")

        r = c.post("/api/studio/script/generate?ws=%s" % ws3.as_posix(),
                   json={"ep": 1, "confirm": True})
        out = r.json()
        check(out.get("ok") is True, "演练生成成功：%r" % (out.get("error"),))
        md = out.get("draft") or {}
        check(md.get("simulated") is True, "草稿标注 simulated")
        check(len((md.get("data") or {}).get("shots") or []) == 8, "产出 8 镜")
        check(not (ws3 / "script" / "ep_01.md").exists(), "生成阶段不写正式文件")

        did = md["id"]
        r = c.post("/api/studio/drafts/%s/confirm?ws=%s" % (did, ws3.as_posix()),
                   json={"confirm": True})
        check(r.status_code == 400, "演练草稿默认拒绝落盘，实际 %d" % r.status_code)
        d = r.json().get("detail") or {}
        check("演练" in (d.get("message") if isinstance(d, dict) else str(d)),
              "拒绝理由应说明是演练草稿：%r" % (d,))
        check(not (ws3 / "script" / "ep_01.md").exists(), "被拒绝时不得产生文件")

        r = c.post("/api/studio/drafts/%s/confirm?ws=%s" % (did, ws3.as_posix()),
                   json={"confirm": True, "allow_simulated": True})
        check(r.status_code == 200 and r.json().get("ok") is True,
              "显式 allow_simulated 后可落盘：%s" % r.text[:200])
        check(r.json().get("simulated") is True, "落盘结果带 simulated 标注")
        check((ws3 / "script" / "ep_01.md").is_file(), "正式文件已生成")

        u = c.get("/api/llm/usage?limit=5").json()
        check(u["items"][0].get("simulated") is True, "用量记录标注了演练")

    srv.shutdown()
    print("\n" + "-" * 62)
    if FAILS:
        print("[NG] %d 项未通过：" % len(FAILS))
        for f in FAILS[:40]:
            print("  - %s" % f)
        return 1
    print("[OK] 端到端集成测试全部通过（%.2fs）" % (time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
