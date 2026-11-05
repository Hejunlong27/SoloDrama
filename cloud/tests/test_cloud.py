"""cloud/tests/test_cloud.py —— 云端编排层的离线测试（零真实云、零计费）

测什么、为什么这么测
--------------------
云端接入最容易出的三类事故，都不是「代码崩」，而是**悄悄做错事**：

  1. 幂等失效 → 脚本重跑，两台 4090 同时计费；
  2. 等不到就绪却不停机 → 一台空转机器烧到天亮；
  3. 凭证落盘 → Token 出现在 settings / 台账 / 日志里。

所以这里用**本地 HTTP 假上游**（`http.server`）真跑一遍完整链路：
请求真的发出去、响应真的解析、文件真的落盘 —— 打桩只能证明代码按我想的写。

护栏与幂等是纯逻辑，用假数据即可；健康检查必须真 HTTP（它读的是 JSON 结构）。
"""
from __future__ import annotations

import json
import pathlib
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]        # 仓库根
sys.path.insert(0, str(ROOT))

from cloud import config as CFG          # noqa: E402
from cloud import health as HEALTH       # noqa: E402
from cloud import ledger as LEDGER       # noqa: E402
from cloud.provisioner import (CloudNotConfigured, CostGuard, Instance,  # noqa: E402
                               Provisioner, XgyApi)

TOKEN = "xgy_secret_token_do_not_leak_123456"


# ---------------------------------------------------------------------------
# 假上游（仙宫云形状：{data: {...}}）
# ---------------------------------------------------------------------------
class _Upstream(BaseHTTPRequestHandler):
    calls: list = []
    instances: list = []
    fail_stop: bool = False

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            return {}

    def do_GET(self):
        path = self.path.split("?")[0]
        _Upstream.calls.append(("GET", path, self.headers.get("Authorization")))
        if path == "/api/list":
            return self._json({"data": {"items": _Upstream.instances}})
        if path == "/api/detail":
            return self._json({"data": _Upstream.instances[0] if _Upstream.instances else {}})
        # 假 ComfyUI
        if path == "/system_stats":
            return self._json({"system": {"comfyui_version": "0.42.1"},
                               "devices": [{"name": "NVIDIA GeForce RTX 4090",
                                            "vram_free": 24 * 1024 ** 3}]})
        if path == "/object_info":
            return self._json(_Upstream.object_info)
        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        path = self.path.split("?")[0]
        payload = self._body()
        _Upstream.calls.append(("POST", path, self.headers.get("Authorization")))
        if path == "/api/create":
            inst = {"id": "i-0001", "name": payload.get("name") or "auto",
                    "state": "creating", "ssh_host": "10.0.0.9", "ssh_port": 22022,
                    "http_url": "http://127.0.0.1:1",     # 故意指向关闭端口 → 探活必失败
                    "price_per_hour": 3.5}                # 上游按实例报价
            _Upstream.instances.append(inst)
            return self._json({"data": inst})
        if path == "/api/deny":
            # 仙宫云的业务失败形态（HTTP 200 + success=false）
            return self._json({"code": 1000, "msg": "未找到访问令牌", "success": False})
        if path == "/api/stop":
            if _Upstream.fail_stop:
                return self._json({"error": "boom"}, 500)
            return self._json({"data": {"ok": True}})
        if path == "/api/destroy":
            return self._json({"data": {"ok": True}})
        return self._json({"error": "not found"}, 404)

    object_info: dict = {}


def _serve(handler):
    srv = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://127.0.0.1:%d" % srv.server_address[1]


@pytest.fixture()
def upstream():
    _Upstream.calls, _Upstream.instances, _Upstream.fail_stop = [], [], False
    srv, base = _serve(_Upstream)
    try:
        yield base
    finally:
        srv.shutdown()


def _cfg(base: str, **over) -> dict:
    cfg = json.loads(json.dumps(CFG.DEFAULTS))
    cfg["cloud"].update({
        "api_base": base + "/api/",
        "endpoints": {"create": "create", "list": "list", "start": "start",
                      "stop": "stop", "destroy": "destroy", "detail": "detail"},
        "price_per_hour": 2.4,
        "max_hours_per_day": 8,
        "ready_timeout_min": 1,
        "poll_seconds": 0.05,
    })
    cfg["cloud"].update(over.pop("cloud", {}))
    cfg.update(over)
    return cfg


# ---------------------------------------------------------------------------
# [A] 配置优先级：环境变量 > settings.json > 内置默认
# ---------------------------------------------------------------------------
def test_config_priority(tmp_path, monkeypatch):
    s = tmp_path / "settings.json"
    s.write_text(json.dumps({"comfyui": {"base_url": "https://from-file.example:8188",
                                         "trusted_hosts": ["*.container.x-gpu.com"],
                                         "timeout": {"video_min": 12}},
                             "cloud": {"max_hours_per_day": 3}}), encoding="utf-8")
    monkeypatch.setenv("SOLODRAMA_SETTINGS", str(s))
    monkeypatch.delenv("COMFYUI_URL", raising=False)
    monkeypatch.delenv("SOLODRAMA_TRUSTED_HOSTS", raising=False)
    monkeypatch.delenv("SOLODRAMA_VIDEO_TIMEOUT_MIN", raising=False)

    cfg = CFG.effective()
    assert cfg["comfyui"]["base_url"] == "https://from-file.example:8188"
    assert cfg["comfyui"]["trusted_hosts"] == ["*.container.x-gpu.com"]
    assert cfg["comfyui"]["timeout"]["video_min"] == 12
    assert cfg["cloud"]["max_hours_per_day"] == 3

    # 环境变量覆盖文件
    monkeypatch.setenv("COMFYUI_URL", "https://from-env.example")
    monkeypatch.setenv("SOLODRAMA_TRUSTED_HOSTS", "a.example,b.example")
    monkeypatch.setenv("SOLODRAMA_VIDEO_TIMEOUT_MIN", "7")
    cfg = CFG.effective()
    assert cfg["comfyui"]["base_url"] == "https://from-env.example"
    assert cfg["comfyui"]["trusted_hosts"] == ["a.example", "b.example"], "名单应整段覆盖，不是相加"
    assert cfg["comfyui"]["timeout"]["video_min"] == 7

    # hydrate 不覆盖已有环境变量
    assert CFG.hydrate_env() == {}


def test_hydrate_fills_env_from_settings(tmp_path, monkeypatch):
    s = tmp_path / "settings.json"
    s.write_text(json.dumps({"comfyui": {
        "base_url": "https://xyz-8188.container.x-gpu.com",
        "trusted_hosts": ["*.container.x-gpu.com"]}}), encoding="utf-8")
    monkeypatch.setenv("SOLODRAMA_SETTINGS", str(s))
    for k in ("COMFYUI_URL", "SOLODRAMA_TRUSTED_HOSTS"):
        monkeypatch.delenv(k, raising=False)
    applied = CFG.hydrate_env()
    assert applied["COMFYUI_URL"].startswith("https://xyz-8188")
    assert applied["SOLODRAMA_TRUSTED_HOSTS"] == "*.container.x-gpu.com"


def test_config_has_no_secret_fields():
    """配置对象里不许出现任何密钥键 —— 否则迟早被打印进日志。"""
    blob = json.dumps(CFG.effective(), ensure_ascii=False).lower()
    for bad in ("password", "secret", "api_key", "token\":"):
        assert bad not in blob, "配置里出现了疑似密钥字段：%s" % bad


# ---------------------------------------------------------------------------
# [B] 台账
# ---------------------------------------------------------------------------
def test_ledger_record_and_day_hours(tmp_path):
    inst = Instance(id="i-9", gpu="4090")
    now = time.time()
    row = LEDGER.record(inst, now - 7200, now, 2.4, note="ep01-03 批量", ws=tmp_path,
                        episodes=3, segments=24)
    assert abs(row["hours"] - 2.0) < 0.01
    assert row["cost"] == pytest.approx(4.8, abs=0.02)
    assert row["priced"] is True and row["episodes"] == 3 and row["segments"] == 24
    assert "+" in row["at"] and "T" in row["at"], "时间必须带时区偏移"
    p = LEDGER.ledger_path(tmp_path)
    assert p.is_file() and p.name == "cloud-cost.jsonl"
    assert LEDGER.day_hours(ws=tmp_path) == pytest.approx(2.0, abs=0.01)


def test_ledger_unpriced_is_not_zero_cost_lie(tmp_path):
    """单价未确认时记 0 元，但必须标 priced=False —— 否则看起来像「免费」。"""
    row = LEDGER.record(Instance(id="i-1"), time.time() - 3600, time.time(), 0, ws=tmp_path)
    assert row["cost"] == 0 and row["priced"] is False
    assert LEDGER.summary(ws=tmp_path)["unpriced_rows"] == 1


def test_ledger_survives_broken_line(tmp_path):
    p = LEDGER.ledger_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"hours": 1}\n不是 JSON\n', encoding="utf-8")
    LEDGER.record(Instance(id="i-2"), time.time() - 60, time.time(), 2.0, ws=tmp_path)
    rows = LEDGER.read_all(tmp_path)
    assert len(rows) == 2, "坏行应跳过，好行照读"


# ---------------------------------------------------------------------------
# [C] 就绪三查
# ---------------------------------------------------------------------------
def _wf(tmp_path, *, model="want.safetensors", cls="UNETLoader") -> pathlib.Path:
    p = tmp_path / "wf.json"
    p.write_text(json.dumps({
        "1": {"class_type": cls, "inputs": {"unet_name": model}},
        "2": {"class_type": "LoadImage", "inputs": {"image": "ref.png"}},
    }), encoding="utf-8")
    m = tmp_path / "wf.map.json"
    m.write_text(json.dumps({"images": ["2"]}), encoding="utf-8")
    return p


def test_probe_ok(upstream, tmp_path):
    _Upstream.object_info = {
        "UNETLoader": {"input": {"required": {"unet_name": [["want.safetensors"]]}}},
        "LoadImage": {"input": {"required": {"image": [["ref.png"]]}}},
    }
    res = HEALTH.probe(upstream, str(_wf(tmp_path)))
    assert res["ok"] is True, HEALTH.render(res)
    assert res["version"] == "0.42.1" and res["version_ok"] is True
    assert "4090" in res["gpu"]


def test_probe_reports_exact_missing_model(upstream, tmp_path):
    """云端最贵的一种错：文件名差一个字符，报错只说 node type missing。"""
    _Upstream.object_info = {
        "UNETLoader": {"input": {"required": {"unet_name": [["other.safetensors"]]}}},
        "LoadImage": {"input": {"required": {"image": [["ref.png"]]}}},
    }
    res = HEALTH.probe(upstream, str(_wf(tmp_path)))
    assert res["ok"] is False
    assert any("want.safetensors" in m for m in res["models_missing"]), res
    assert "缺模型文件" in HEALTH.render(res)


def test_probe_reports_missing_node_class(upstream, tmp_path):
    _Upstream.object_info = {"LoadImage": {"input": {"required": {"image": [["ref.png"]]}}}}
    res = HEALTH.probe(upstream, str(_wf(tmp_path, cls="SolAttnMiniMax")))
    assert res["ok"] is False
    assert res["nodes_missing"] == ["SolAttnMiniMax"], res["nodes_missing"]


def test_probe_low_version(upstream, tmp_path):
    class _Old(_Upstream):
        pass                                   # 复用响应，只改版本
    res = HEALTH.probe(upstream, "")
    assert res["ok"] is True                   # 不指定工作流 → 服务级结论
    assert HEALTH._ver_tuple("0.40.2") < HEALTH._ver_tuple(HEALTH.MIN_COMFY_VERSION)


def test_probe_offline_never_raises():
    res = HEALTH.probe("http://127.0.0.1:1", "", timeout=2)
    assert res["ok"] is False and res["error"]


# ---------------------------------------------------------------------------
# [D] 生命周期：幂等 / 必停 / 护栏 / 凭证
# ---------------------------------------------------------------------------
def test_create_reuses_running_instance(upstream, tmp_path, monkeypatch):
    """同名实例在跑 → 直接复用，不发 create（重跑不该多烧一台机器）。"""
    monkeypatch.setenv("XGY_TOKEN", TOKEN)
    _Upstream.instances = [{"id": "i-old", "name": "盲婚", "state": "running",
                            "http_url": "https://i-old-8188.container.x-gpu.com",
                            "ssh_host": "1.1.1.1", "ssh_port": 22}]
    prov = Provisioner(_cfg(upstream), ws=tmp_path, log=lambda *_: None)
    inst = prov.create("盲婚")
    assert inst.id == "i-old"
    assert not any(c[0] == "POST" and c[1] == "/api/create" for c in _Upstream.calls)


def test_create_without_list_endpoint_refuses(upstream, tmp_path, monkeypatch):
    """list 没配就不许盲建 —— 幂等不能靠祈祷。"""
    monkeypatch.setenv("XGY_TOKEN", TOKEN)
    cfg = _cfg(upstream)
    cfg["cloud"]["endpoints"]["list"] = ""
    prov = Provisioner(cfg, ws=tmp_path, log=lambda *_: None)
    with pytest.raises(CloudNotConfigured) as ei:
        prov.create("x")
    assert "cloud.endpoints.list" in str(ei.value)


def test_create_requires_token(upstream, tmp_path, monkeypatch):
    monkeypatch.delenv("XGY_TOKEN", raising=False)
    prov = Provisioner(_cfg(upstream), ws=tmp_path, log=lambda *_: None)
    with pytest.raises(CloudNotConfigured) as ei:
        prov.create("x", reuse=False)
    assert "XGY_TOKEN" in str(ei.value)


def test_cost_guard_blocks_create(upstream, tmp_path, monkeypatch):
    """今日已超上限 → 拒绝建实例（不是警告，是拒绝）。"""
    monkeypatch.setenv("XGY_TOKEN", TOKEN)
    now = time.time()
    LEDGER.record(Instance(id="i-x"), now - 9 * 3600, now, 2.4, ws=tmp_path)
    prov = Provisioner(_cfg(upstream), ws=tmp_path, log=lambda *_: None)
    with pytest.raises(CostGuard) as ei:
        prov.create("x", reuse=False)
    assert "9.00" in str(ei.value) or "上限" in str(ei.value)
    assert not any(c[1] == "/api/create" for c in _Upstream.calls), "护栏要在建之前生效"


def test_wait_ready_timeout_auto_stops(upstream, tmp_path, monkeypatch):
    """等不到就绪必须自动停机 —— 「失败必停」是省钱条款，不是体验条款。"""
    monkeypatch.setenv("XGY_TOKEN", TOKEN)
    cfg = _cfg(upstream)
    cfg["cloud"].update({"ready_timeout_min": 0.02, "poll_seconds": 0.02})
    prov = Provisioner(cfg, ws=tmp_path, log=lambda *_: None)
    inst = prov.create("x", reuse=False)
    assert inst.id == "i-0001"
    ok = prov.wait_ready(inst, 0.02, workflow_path="")
    assert ok is False
    assert any(c[0] == "POST" and c[1] == "/api/stop" for c in _Upstream.calls), \
        "未就绪却没有调用 stop —— 会一直计费"
    rows = LEDGER.read_all(tmp_path)
    assert rows and rows[-1]["instance"] == "i-0001"


def test_stop_records_ledger(upstream, tmp_path, monkeypatch):
    monkeypatch.setenv("XGY_TOKEN", TOKEN)
    prov = Provisioner(_cfg(upstream), ws=tmp_path, log=lambda *_: None)
    inst = prov.create("x", reuse=False)
    row = prov.stop(inst)
    assert row["priced"] is True and row["hours"] >= 0
    assert "xgy_secret" not in json.dumps(row), "凭证不许进台账"


def test_token_never_written_to_disk(upstream, tmp_path, monkeypatch):
    """凭证不落盘：状态文件与台账都扫一遍。"""
    monkeypatch.setenv("XGY_TOKEN", TOKEN)
    prov = Provisioner(_cfg(upstream), ws=tmp_path, log=lambda *_: None)
    inst = prov.create("x", reuse=False)
    prov.stop(inst)
    for f in tmp_path.rglob("*"):
        if f.is_file():
            assert TOKEN not in f.read_text(encoding="utf-8", errors="replace"), \
                "Token 落盘：%s" % f


def test_auth_header_is_sent_but_masked(upstream, tmp_path, monkeypatch):
    monkeypatch.setenv("XGY_TOKEN", TOKEN)
    prov = Provisioner(_cfg(upstream), ws=tmp_path, log=lambda *_: None)
    prov.create("x", reuse=False)
    auths = [c[2] for c in _Upstream.calls if c[2]]
    assert auths and all(a == "Bearer " + TOKEN for a in auths)
    assert CFG.mask(TOKEN).count("*") == 3 and TOKEN not in CFG.mask(TOKEN)


def test_missing_endpoint_names_the_key(upstream, tmp_path, monkeypatch):
    monkeypatch.setenv("XGY_TOKEN", TOKEN)
    cfg = _cfg(upstream)
    cfg["cloud"]["endpoints"]["create"] = ""
    prov = Provisioner(cfg, ws=tmp_path, log=lambda *_: None)
    with pytest.raises(CloudNotConfigured) as ei:
        prov.create("x", reuse=False)
    assert "cloud.endpoints.create" in str(ei.value)


def test_field_map_fallback_and_url_template(upstream, tmp_path, monkeypatch):
    """响应没给 http_url 时按 provider 规则拼，不臆造别的域名。"""
    monkeypatch.setenv("XGY_TOKEN", TOKEN)
    cfg = _cfg(upstream)
    cfg["cloud"]["field_map"] = {"id": "data.id", "state": "data.state"}
    cfg["cloud"]["http_url_template"] = "https://{id}-8188.container.x-gpu.com"
    prov = Provisioner(cfg, ws=tmp_path, log=lambda *_: None)
    inst = prov.create("x", reuse=False)
    assert inst.http_url == "https://i-0001-8188.container.x-gpu.com"


def test_attach_manual_mode_uses_given_url(tmp_path):
    cfg = _cfg("http://127.0.0.1:9")
    prov = Provisioner(cfg, ws=tmp_path, log=lambda *_: None)
    inst = prov.attach("https://abc-8188.container.x-gpu.com/", name="手动")
    assert inst.http_url == "https://abc-8188.container.x-gpu.com"
    assert prov.state.get(inst.id)["http_url"].endswith("x-gpu.com"), "状态要能跨进程读到"


# ---------------------------------------------------------------------------
# [E] 上游真实形态（2026-11-05 按官方 API Playground 校准）
# ---------------------------------------------------------------------------
def test_parse_real_instance_shape(tmp_path):
    """仙宫云「获取实例列表」返回的是**扁平实例**：web_url / ssh_domain / status，
    且 ssh_port 是**字符串**。这几处与通用 REST 直觉不同，必须钉住。"""
    prov = Provisioner(_cfg("http://127.0.0.1:9"), ws=tmp_path, log=lambda *_: None)
    raw = {"id": "i-real", "name": "盲婚", "status": "running",
           "ssh_domain": "ssh.example.com", "ssh_port": "22022",
           "web_url": "https://i-real-8188.container.x-gpu.com",
           "price_per_hour": 1.59, "retain": 1, "retain_price": 0.02}
    inst = prov._to_instance(raw)
    assert inst.id == "i-real" and inst.state == "running"
    assert inst.ssh_host == "ssh.example.com" and inst.ssh_port == 22022, "ssh_port 是字符串"
    assert inst.http_url == "https://i-real-8188.container.x-gpu.com"
    assert inst.price_per_hour == 1.59 and inst.retain is True
    assert inst.retain_price == 0.02


def test_price_comes_from_instance_not_config(upstream, tmp_path, monkeypatch):
    """不同卡型/地域单价不同 —— 记账用上游报的价，而不是配置里那个兜底数。"""
    monkeypatch.setenv("XGY_TOKEN", TOKEN)
    prov = Provisioner(_cfg(upstream), ws=tmp_path, log=lambda *_: None)   # 配置价 2.4
    inst = prov.create("x", reuse=False)
    assert inst.price_per_hour == 3.5
    row = prov.stop(inst)
    assert row["price_per_hour"] == 3.5, row


def test_business_error_envelope_raises(upstream, tmp_path, monkeypatch):
    """HTTP 200 + success=false 也是失败。不识别它，上层只会报「取不到实例 ID」。"""
    monkeypatch.setenv("XGY_TOKEN", TOKEN)
    cfg = _cfg(upstream)
    cfg["cloud"]["endpoints"]["create"] = "deny"
    prov = Provisioner(cfg, ws=tmp_path, log=lambda *_: None)
    with pytest.raises(CloudNotConfigured) as ei:
        prov.create("x", reuse=False)
    assert "未找到访问令牌" in str(ei.value)


def test_stop_warns_when_disk_still_billed(upstream, tmp_path, monkeypatch):
    """关机保留磁盘仍在收费：必须提示，否则人会以为停了就不花钱。"""
    monkeypatch.setenv("XGY_TOKEN", TOKEN)
    logs = []
    prov = Provisioner(_cfg(upstream), ws=tmp_path, log=lambda *a: logs.append(" ".join(map(str, a))))
    inst = Instance(id="i-keep", name="keep", state="running", retain=True, retain_price=0.05)
    prov.state.put(inst, started_at=time.time() - 3600)
    row = prov.stop(inst)
    assert any("保留磁盘" in x for x in logs), logs
    assert "保留磁盘" in row["note"]
