"""test_comfy_http.py —— 共享 HTTP 层的行为回归（重试口径 / 原子下载 / 错误分类）

为什么要单独测这一层
--------------------
它决定了「一次网络抖动要不要作废一整镜」。三条纪律里任何一条写反了，
后果都不是崩，而是**悄悄做错事**：

  · GET 不重试 → 偶发 ConnectionReset 直接废掉 5–10 分钟的成果
  · POST 重试   → 一次出片变两次，两个文件、两倍时间，而且都「成功」
  · 下载不原子  → 留下半截 mp4，下游拼进去，画面从中间断掉且不报错

所以这里用真 HTTP 服务（`http.server`）测，不打桩：
打桩只能证明代码按我想的写，证明不了它对真实 socket 的行为。
"""

import json
import pathlib
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = pathlib.Path(__file__).resolve()
STAGES = HERE.parents[3]
ROOT = HERE.parents[4]
sys.path.insert(0, str(STAGES))

import _comfy_http as Q  # noqa: E402


class _Handler(BaseHTTPRequestHandler):
    """可编排的假 ComfyUI：按路径决定返回码与次数记录。"""

    hits: dict = {}
    plan: dict = {}          # path -> [status, ...]  依次返回；用完后重复最后一项

    def log_message(self, *a):           # 静音：测试输出不该被 access log 污染
        pass

    def _serve(self):
        p = self.path.split("?")[0]
        _Handler.hits[p] = _Handler.hits.get(p, 0) + 1
        seq = _Handler.plan.get(p) or [503, 200]
        idx = min(_Handler.hits[p] - 1, len(seq) - 1)
        status = seq[idx]
        if p == "/blob":
            body = b"x" * 64 if status == 200 else b""
        elif p == "/empty":
            body = b""
            status = 200
        else:
            body = json.dumps({"ok": status == 200, "path": p,
                               "hit": _Handler.hits[p]}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = _serve
    do_POST = _serve


def _serve():
    """起一个临时服务，返回 (base_url, server, 关闭函数)。"""
    Q._BACKOFF = (0.01, 0.01, 0.01)      # 测试不等真实退避
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return "http://127.0.0.1:%d" % port, srv


def test_get_retries_then_succeeds(monkeypatch):
    """GET 打两次 503 后成功：应该自己扛过去，不该抛。"""
    base, srv = _serve()
    try:
        _Handler.hits, _Handler.plan = {}, {"/stats": [503, 503, 200]}
        monkeypatch.setenv("COMFYUI_URL", base)
        d = Q.get_json("/stats", timeout=5, retries=3)
        assert d.get("ok") is True, d
        assert _Handler.hits["/stats"] == 3, "应重试到第 3 次成功，实际 %d 次" % _Handler.hits["/stats"]
    finally:
        srv.shutdown()


def test_get_gives_up_on_404(monkeypatch):
    """4xx 不重试：它不会自己好起来，重试只是浪费时间。"""
    base, srv = _serve()
    try:
        _Handler.hits, _Handler.plan = {}, {"/nope": [404]}
        monkeypatch.setenv("COMFYUI_URL", base)
        try:
            Q.get_json("/nope", timeout=5, retries=3)
        except Q.ComfyHTTPError as e:
            assert e.status == 404
        else:
            raise AssertionError("404 应该抛 ComfyHTTPError")
        assert _Handler.hits["/nope"] == 1, "404 不应重试，实际 %d 次" % _Handler.hits["/nope"]
    finally:
        srv.shutdown()


def test_post_never_retries(monkeypatch):
    """★ 最重要的一条：/prompt 失败后**不许**自动重发。

    重发的代价不是多一次请求，而是多出一份视频/一张图 —— 而且两份都算成功，
    磁盘上出现两份产物、时间翻倍，事后完全看不出发生过什么。
    """
    base, srv = _serve()
    try:
        _Handler.hits, _Handler.plan = {}, {"/prompt": [500]}
        monkeypatch.setenv("COMFYUI_URL", base)
        try:
            Q.post_json("/prompt", {"prompt": {}}, timeout=5)   # 默认 retries=0
        except Q.ComfyHTTPError as e:
            assert e.status == 500
        else:
            raise AssertionError("500 应该抛 ComfyHTTPError")
        assert _Handler.hits["/prompt"] == 1, \
            "POST /prompt 被重发了 %d 次 —— 会重复出片" % _Handler.hits["/prompt"]
    finally:
        srv.shutdown()


def test_download_is_atomic(monkeypatch, tmp_path):
    """下载成功才出现目标文件，失败不留半截。"""
    base, srv = _serve()
    try:
        _Handler.hits, _Handler.plan = {}, {"/blob": [200]}
        monkeypatch.setenv("COMFYUI_URL", base)
        dst = tmp_path / "a.mp4"
        n = Q.download("/blob", str(dst), timeout=5)
        assert n == 64 and dst.is_file()
        assert not (tmp_path / "a.mp4.part").exists(), "成功后会留下 .part"
    finally:
        srv.shutdown()


def test_download_rejects_empty(monkeypatch, tmp_path):
    """0 字节不能当成功 —— 否则下游会拿一个空文件去拼接。"""
    base, srv = _serve()
    try:
        _Handler.hits, _Handler.plan = {}, {"/empty": [200]}
        monkeypatch.setenv("COMFYUI_URL", base)
        dst = tmp_path / "b.mp4"
        try:
            Q.download("/empty", str(dst), timeout=5)
        except Q.ComfyError:
            pass
        else:
            raise AssertionError("0 字节应该报错")
        assert not dst.exists(), "0 字节不该留下目标文件"
        assert not (tmp_path / "b.mp4.part").exists(), "临时文件也应清掉"
    finally:
        srv.shutdown()


def test_offline_hint_has_three_actions():
    """连不上时的提示必须给「怎么办」，不能只给一个 WinError 号码。"""
    msg = Q._offline_hint(ConnectionRefusedError("拒绝"), "probe")
    for kw in ("服务没起", "端口不对", "刚重启"):
        assert kw in msg, "提示缺少「%s」这条出路：\n%s" % (kw, msg)


def test_probe_never_raises(monkeypatch):
    """probe 是给状态面板用的：它要一句话，不要异常。"""
    monkeypatch.setenv("COMFYUI_URL", "http://127.0.0.1:9")   # 必然拒绝
    d = Q.probe(timeout=1)
    assert d["online"] is False
    assert d["kind"] == "offline"
    assert d["error"], "必须带原因"


def test_probe_ok_against_live(monkeypatch):
    """在线时返回版本/延迟，且延迟是数字（面板要显示它判断服务是否被压垮）。"""
    base, srv = _serve()
    try:
        _Handler.hits, _Handler.plan = {}, {"/system_stats": [200]}
        monkeypatch.setenv("COMFYUI_URL", base)
        d = Q.probe(timeout=5)
        assert d["online"] is True
        assert isinstance(d["latency_ms"], int)
    finally:
        srv.shutdown()


if __name__ == "__main__":
    import os
    import tempfile
    import traceback

    class _MP:
        def setenv(self, k, v):
            os.environ[k] = v

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="comfyhttp_"))
    fails = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        args = [_MP()]
        if "tmp_path" in fn.__code__.co_varnames[:fn.__code__.co_argcount]:
            args.append(tmp)
        try:
            fn(*args)
            print("[OK  ] %s" % name)
        except Exception as e:                                    # noqa: BLE001
            fails += 1
            print("[FAIL] %s\n       %s" % (name, e))
            traceback.print_exc()
    print("\n%d 失败" % fails)
    sys.exit(1 if fails else 0)
