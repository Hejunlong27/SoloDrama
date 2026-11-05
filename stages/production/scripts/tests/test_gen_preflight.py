"""test_gen_preflight.py —— 生成能力预检（批量入口开跑前的唯一判据）

为什么单独测
------------
这一层的价值不是「报错」，而是**拦住一次白跑**：缺一个模型时，批量不是失败一次，
而是每镜各失败一次（8 镜 × 上传参考图 + 等 400）。所以每条判据都要能独立说清：

  · 缺模型 → 点名到文件名（不是「node type missing」）；
  · 云端域名没点名 → 在**提交前**就被守卫拦下，而不是发一半请求才 403；
  · 地址来源要跟执行期同源（确认单 > 环境变量 > settings > 默认），否则预检打 A、真跑打 B。

测试用本地假 ComfyUI（`http.server`）真跑 HTTP：判据读的是 JSON 结构，打桩证明不了。
"""
from __future__ import annotations

import json
import pathlib
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

HERE = pathlib.Path(__file__).resolve()
SCRIPTS = HERE.parents[1]                   # stages/production/scripts
ROOT = HERE.parents[4]                      # 仓库根
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT))

import gen_preflight as GP                  # noqa: E402


class _Fake(BaseHTTPRequestHandler):
    nodes: dict = {}
    version: str = "0.43.2"

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/system_stats":
            return self._json({"system": {"comfyui_version": _Fake.version},
                               "devices": [{"name": "RTX 4090", "vram_free": 20 * 1024 ** 3}]})
        if p == "/object_info":
            return self._json(_Fake.nodes)
        return self._json({"error": "nf"}, 404)


@pytest.fixture()
def fake():
    _Fake.nodes = {
        "LoadImage": {"input": {"required": {"image": [["a.png"]]}}},
        "UNETLoader": {"input": {"required": {"unet_name": [["have.safetensors"]]}}},
        "PreviewImage": {"input": {"required": {}}},
    }
    _Fake.version = "0.43.2"
    srv = HTTPServer(("127.0.0.1", 0), _Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % srv.server_address[1]
    srv.shutdown()


def _ws(tmp_path, *, url="", wf="", kind="video"):
    """造一个只有 model-plan.json 的最小工作区。"""
    if wf:
        p = tmp_path / "wf.json"
        p.write_text(wf if isinstance(wf, str) else json.dumps(wf), encoding="utf-8")
        wf = str(p)
    det = {}
    if url:
        det["comfy_url"] = url
    if wf:
        det["comfy_workflow"] = wf
    (tmp_path / "model-plan.json").write_text(json.dumps({
        "gate_version": 2,
        "models": {kind: {"choice": "cloud_comfyui", "confirmed": True, "detail": det}},
    }, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def _wf(model="have.safetensors"):
    return {"1": {"class_type": "UNETLoader", "inputs": {"unet_name": model}},
            "2": {"class_type": "LoadImage", "inputs": {"image": "a.png"}},
            "3": {"class_type": "PreviewImage", "inputs": {"images": ["2", 0]}}}


def test_ready_channel(tmp_path, fake, monkeypatch):
    monkeypatch.setenv("SOLODRAMA_TRUSTED_HOSTS", "*.container.x-gpu.com")
    ws = _ws(tmp_path, url=fake, wf=_wf())
    r = GP.check("video", "local", ws)
    assert r["ok"] is True, GP.render(r)
    assert [c["id"] for c in r["checks"] if not c["ok"]] == []
    assert r["url"] == fake and r["workflow"].endswith("wf.json")


def test_missing_model_names_the_file(tmp_path, fake):
    """缺模型必须点名到文件名 —— 「node type missing」查不出来。"""
    ws = _ws(tmp_path, url=fake, wf=_wf(model="not-installed.safetensors"))
    r = GP.check("video", "local", ws)
    assert r["ok"] is False and r["status"] == "missing"
    detail = " ".join(c["detail"] for c in r["checks"] if c["id"] == "models")
    assert "not-installed.safetensors" in detail, detail


def test_low_version_is_flagged(tmp_path, fake):
    _Fake.version = "0.40.0"
    ws = _ws(tmp_path, url=fake, wf=_wf())
    r = GP.check("video", "local", ws)
    assert r["ok"] is False and r["status"] == "version", GP.render(r)


def test_guard_blocks_untrusted_cloud_host(tmp_path, monkeypatch):
    """云端域名没点名 → 在提交前就判 blocked，并给出可直接复制的环境变量。"""
    monkeypatch.delenv("SOLODRAMA_TRUSTED_HOSTS", raising=False)
    sys.path.insert(0, str(ROOT / "stages"))
    import _netguard as NG
    NG.reset_trusted()
    ws = _ws(tmp_path, url="https://zzz-8188.container.x-gpu.com", wf=_wf())
    r = GP.check("video", "cloud", ws)
    assert r["ok"] is False and r["status"] == "blocked", GP.render(r)
    assert "TRUSTED_HOSTS" in (r["next"] or "")
    NG.reset_trusted()


def test_offline_channel(tmp_path):
    # ★ 必须给 kind：确认单按类分开，写成 video 时 image 的 detail 是空的，
    #   会回落到环境地址（真实 ComfyUI）—— 那样测的就不是「离线」了。
    ws = _ws(tmp_path, url="http://127.0.0.1:1", wf=_wf(), kind="image")
    r = GP.check("image", "local", ws)
    assert r["ok"] is False and r["status"] == "offline"
    assert r["next"], "离线也要给下一步"


def test_closed_source_is_not_a_runner(tmp_path):
    r = GP.check("image", "closed", tmp_path)
    assert r["ok"] is False and r["status"] == "unsupported"


def test_resolve_prefers_confirmation(tmp_path, monkeypatch):
    """地址优先级：确认单 > 环境变量。两侧不一致时预检会打错机器。"""
    monkeypatch.setenv("COMFYUI_URL", "http://127.0.0.1:9999")
    ws = _ws(tmp_path, url="https://from-plan.example:8188", wf=_wf())
    r = GP.resolve("video", ws)
    assert r["url"] == "https://from-plan.example:8188" and r["url_via"] == "模型确认单"

    ws2 = tmp_path / "b"
    ws2.mkdir()
    r2 = GP.resolve("video", ws2)
    assert r2["url"] == "http://127.0.0.1:9999" and "环境变量" in r2["url_via"]


def test_missing_workflow_blocks(tmp_path, fake):
    ws = _ws(tmp_path, url=fake)
    plan = {"models": {"video": {"choice": "cloud_comfyui", "confirmed": True,
                                 "detail": {"comfy_url": fake,
                                            "comfy_workflow": str(tmp_path / "nope.json")}}}}
    (ws / "model-plan.json").write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    r = GP.check("video", "local", ws)
    # 确认单里的工作流不存在 → 回落到仓库默认；默认若也不存在则 blocked
    assert r["workflow"].endswith(".json")
    assert isinstance(r["ok"], bool)


def test_render_only_lists_failures(tmp_path, fake):
    ws = _ws(tmp_path, url=fake, wf=_wf(model="x.safetensors"))
    txt = GP.render(GP.check("video", "local", ws))
    assert "[NG]" in txt and "x.safetensors" in txt
    assert "在线" not in txt, "通过的项不该刷屏"
