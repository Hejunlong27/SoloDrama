"""cloud/tests/test_session.py —— 任务级启停：**要跑才开，跑完就关**

这一层的每条语义都对应一类真实事故，所以逐条测：

  1. 跑完不停       → 一台 4090 开一夜是 ￥38（1.59×24）
  2. 异常不停       → 出片失败时更没人想起停机
  3. 停错别人的机器 → 复用别人正在跑的实例，跑完替人关掉
  4. 干跑就开机     → 还没确认就先把机器开起来，白烧几分钟

测试用本地假上游（与 test_cloud.py 同一套形状），并**真的**走 HTTP：
停机到底有没有发出去，只有服务端记的 hits 能证明。
"""
from __future__ import annotations

import json
import pathlib
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from cloud import config as CFG             # noqa: E402
from cloud import ledger as LEDGER          # noqa: E402
from cloud.provisioner import Instance      # noqa: E402
from cloud.session import CloudNotReady, Lease   # noqa: E402

TOKEN = "xgy_test_token_session_0001"


class _Up(BaseHTTPRequestHandler):
    calls: list = []
    _addr = ("127.0.0.1", 0)

    @classmethod
    def server_addr(cls):
        return cls._addr
    instances: list = []
    ready: bool = False          # ComfyUI 探活是否就绪

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n).decode() or "{}") if n else {}
        except ValueError:
            return {}

    def do_GET(self):
        p = self.path.split("?")[0]
        _Up.calls.append(("GET", p))
        if p == "/api/list":
            return self._json({"list": _Up.instances, "total": len(_Up.instances)})
        if p == "/system_stats":
            if not _Up.ready:
                return self._json({"error": "starting"}, 503)
            return self._json({"system": {"comfyui_version": "0.42.1"},
                               "devices": [{"name": "RTX 4090", "vram_free": 20 * 1024 ** 3}]})
        if p == "/object_info":
            return self._json({})
        return self._json({"error": "nf"}, 404)

    def do_POST(self):
        p = self.path.split("?")[0]
        payload = self._body()
        _Up.calls.append(("POST", p))
        if p == "/api/create":
            host, port = self.server.server_address[0], self.server.server_address[1]
            inst = {"id": "i-new", "name": payload.get("name") or "auto", "status": "creating",
                    # 新建实例的直连地址就指回本测试服务：探活才走得到 /system_stats
                    "web_url": "http://%s:%d" % (host, port),
                    "ssh_domain": "h", "ssh_port": "22", "price_per_hour": 1.59}
            _Up.instances.append(inst)
            return self._json(inst)
        if p == "/api/start":
            return self._json({"id": "i-old", "status": "starting"})
        if p == "/api/stop":
            return self._json({"ok": True})
        return self._json({"error": "nf"}, 404)


@pytest.fixture()
def up():
    _Up.calls, _Up.instances, _Up.ready = [], [], False
    srv = HTTPServer(("127.0.0.1", 0), _Up)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _Up._addr = srv.server_address
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    yield base
    srv.shutdown()


def _cfg(base: str, **cloud) -> dict:
    cfg = json.loads(json.dumps(CFG.DEFAULTS))
    cfg["cloud"].update({
        "api_base": base + "/api/",
        "endpoints": {"create": "create", "list": "list", "start": "start",
                      "stop": "stop", "destroy": "destroy", "detail": "detail"},
        "price_per_hour": 1.59, "max_hours_per_day": 8,
        "ready_timeout_min": 0.01, "poll_seconds": 0.01,
    })
    cfg["cloud"].update(cloud)
    return cfg


def _stops() -> int:
    return sum(1 for c in _Up.calls if c == ("POST", "/api/stop"))


def test_borrowed_instance_is_not_stopped(up, tmp_path, monkeypatch):
    """给了地址 = 借别人在跑的机器 → 跑完**不许**替他关。"""
    monkeypatch.setenv("XGY_TOKEN", TOKEN)
    _Up.ready = True
    with Lease(_cfg(up), ws=tmp_path, url=up, name="任务A") as lease:
        assert lease.http_url == up
        assert lease.owned is False
    assert _stops() == 0, "借来的实例被停机了 —— 会把别人的任务掐掉"


def test_owned_instance_stops_on_exit(up, tmp_path, monkeypatch):
    """自己建/开的机器 → 退出即停（正常路径）。"""
    monkeypatch.setenv("XGY_TOKEN", TOKEN)
    _Up.ready = True
    lease = Lease(_cfg(up), ws=tmp_path, name="任务B")
    with lease:
        assert lease.owned is True
        lease.usage(episodes=1, segments=8)
    assert _stops() == 1
    rows = LEDGER.read_all(tmp_path)
    assert rows and rows[-1]["instance"] == "i-new"
    assert rows[-1]["episodes"] == 1 and rows[-1]["segments"] == 8
    assert rows[-1]["price_per_hour"] == 1.59 and rows[-1]["priced"] is True


def test_owned_instance_stops_on_exception(up, tmp_path, monkeypatch):
    """★ 出片抛异常时更该停 —— 那时没人会想起来。"""
    monkeypatch.setenv("XGY_TOKEN", TOKEN)
    _Up.ready = True
    with pytest.raises(RuntimeError):
        with Lease(_cfg(up), ws=tmp_path, name="任务C"):
            raise RuntimeError("批次失败")
    assert _stops() == 1


def test_not_ready_owned_is_stopped_and_raises(up, tmp_path, monkeypatch):
    """建好了但 ComfyUI 起不来 → 停机 + 抛 CloudNotReady（不留空转机器）。"""
    monkeypatch.setenv("XGY_TOKEN", TOKEN)
    _Up.ready = False                       # /system_stats 一直 503
    with pytest.raises(CloudNotReady):
        with Lease(_cfg(up), ws=tmp_path, name="任务D"):
            pass
    assert _stops() >= 1, "未就绪却没有停机"


def test_keep_leaves_instance_running(up, tmp_path, monkeypatch):
    """显式 keep → 不停（连续批次场景），但必须打印「仍在计费」。"""
    monkeypatch.setenv("XGY_TOKEN", TOKEN)
    _Up.ready = True
    logs = []
    with Lease(_cfg(up), ws=tmp_path, name="任务E", keep=True,
               log=lambda *a: logs.append(" ".join(map(str, a)))):
        pass
    assert _stops() == 0
    assert any("仍在计费" in x for x in logs), logs


def test_reuse_stopped_instance_via_start(up, tmp_path, monkeypatch):
    """同名但已停机 → 走 start（比重建省一块数据盘），且记为我们开的。"""
    monkeypatch.setenv("XGY_TOKEN", TOKEN)
    _Up.ready = True
    host, port = _Up.server_addr()
    _Up.instances = [{"id": "i-old", "name": "任务F", "status": "stopped",
                      "web_url": "http://%s:%d" % (host, port), "ssh_port": "22"}]
    lease = Lease(_cfg(up), ws=tmp_path, name="任务F")
    with lease:
        assert lease.instance.id == "i-old" and lease.owned is True
    assert any(c == ("POST", "/api/start") for c in _Up.calls), "没有调用开机"
    assert _stops() == 1, "开机后用完要关"


def test_reuse_running_instance_is_borrowed(up, tmp_path, monkeypatch):
    """同名在跑 → 复用但不算自己开的；本地记录里能查到它。"""
    monkeypatch.setenv("XGY_TOKEN", TOKEN)
    _Up.ready = True
    _Up.instances = [{"id": "i-run", "name": "任务G", "status": "running",
                      "web_url": up, "ssh_port": "22"}]
    with Lease(_cfg(up), ws=tmp_path, name="任务G") as lease:
        assert lease.instance.id == "i-run"
        assert lease.owned is False
    assert _stops() == 0


def test_no_url_no_endpoints_gives_actionable_error(tmp_path, monkeypatch):
    """既没地址也没端点 → 报错要说清两条出路，而不是一个 KeyError。"""
    monkeypatch.setenv("XGY_TOKEN", TOKEN)
    cfg = _cfg("http://127.0.0.1:9")
    cfg["cloud"]["endpoints"] = {"create": "", "list": "", "stop": ""}
    with pytest.raises(Exception) as ei:
        with Lease(cfg, ws=tmp_path, name="任务H"):
            pass
    msg = str(ei.value)
    assert "comfy-url" in msg or "endpoints" in msg, msg


def test_reap_stops_only_idle_instances(up, tmp_path, monkeypatch):
    """空闲回收：只停「很久没动」的，正在跑的不动。"""
    monkeypatch.setenv("XGY_TOKEN", TOKEN)
    lease = Lease(_cfg(up), ws=tmp_path, name="任务I")
    prov = lease.prov
    stale = Instance(id="i-stale", name="old", state="running", owned=True)
    fresh = Instance(id="i-fresh", name="new", state="running", owned=True)
    prov.state.put(stale, started_at=time.time() - 7200, last_used_at=time.time() - 3600)
    prov.state.put(fresh, started_at=time.time() - 60, last_used_at=time.time() - 10)

    out = prov.reap(idle_min=15, dry=True)
    assert [r["id"] for r in out] == ["i-stale"] and out[0]["action"] == "would_stop"
    assert _stops() == 0, "干跑不许真停"

    out = prov.reap(idle_min=15)
    assert [r["id"] for r in out] == ["i-stale"] and out[0]["action"] == "stopped"
    assert _stops() == 1
    assert prov.state.load()["i-fresh"]["state"] == "running"


def test_usage_updates_last_used(up, tmp_path, monkeypatch):
    """`usage()` 兼作活跃心跳：连续批次不会被 reap 误杀。"""
    monkeypatch.setenv("XGY_TOKEN", TOKEN)
    _Up.ready = True
    with Lease(_cfg(up), ws=tmp_path, name="任务J", keep=True) as lease:
        before = lease.prov.state.get(lease.instance.id).get("last_used_at") or 0
        time.sleep(0.01)
        lease.usage(episodes=2, segments=12)
        after = lease.prov.state.get(lease.instance.id).get("last_used_at") or 0
    assert after > before
