"""cloud/tests/test_pull.py —— 云端产物回传：拉得回来、不重复拉、缺了能看见

这一层对应三类真实场景：

  1. **任务成功、下载失败** → 本地没文件，但云上有。停机前必须补上，否则只能重跑再花钱。
  2. **同一集跑了两遍** → 回传必须幂等，不能把人工修过的产物冲掉。
  3. **history 被清空**（实例重启） → 只剩 `--file` 按名取这一条路，要能走通。

测试**真的走 HTTP**：下载到底有没有发出去、发到哪个地址，只有假服务端记的 hits 能证明。
"""
from __future__ import annotations

import json
import pathlib
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from cloud import pull as PULL             # noqa: E402


class FakeComfy:
    """最小的 ComfyUI 替身：只实现 /history 与 /view。"""

    history: dict = {}
    files: dict = {}
    hits: list = []

    @classmethod
    def reset(cls, history=None, files=None):
        cls.history = history or {}
        cls.files = files or {}
        cls.hits = []


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):                                      # noqa: N802
        u = urlsplit(self.path)
        FakeComfy.hits.append(u.path)
        if u.path == "/history":
            body = json.dumps(FakeComfy.history).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if u.path == "/view":
            fn = (parse_qs(u.query).get("filename") or [""])[0]
            data = FakeComfy.files.get(fn, b"")
            if not data:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_error(404)

    def log_message(self, *a):                             # noqa: D401
        pass


@pytest.fixture(scope="module")
def comfy():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield "http://127.0.0.1:%d" % srv.server_port
    srv.shutdown()


@pytest.fixture(autouse=True)
def _clean():
    FakeComfy.reset()
    yield
    FakeComfy.reset()


HISTORY = {
    "pid-1": {"outputs": {"9": {"gifs": [
        {"filename": "h3_shot_001_111.mp4", "subfolder": "", "type": "output"}]}}},
    # 同一个文件同时出现在 gifs / videos 时只能算一条（去重）
    "pid-2": {"outputs": {"9": {"gifs": [
        {"filename": "h3_shot_002_222.mp4", "subfolder": "", "type": "output"}],
        "videos": [
        {"filename": "h3_shot_002_222.mp4", "subfolder": "", "type": "output"}]}}},
    "pid-3": {"outputs": {"12": {"images": [
        {"filename": "board_001.png", "subfolder": "boards", "type": "output"}]}}},
    # 非媒体产物一律忽略（否则会把预览图当成成片）
    "pid-4": {"outputs": {"3": {"text": [{"filename": "note.txt"}]}}},
}


def _ws(tmp_path: pathlib.Path) -> pathlib.Path:
    """造一个旧布局工作区：`video-pipeline/output/<ep>/shot_NNN/final.mp4`。

    不用 layout.json —— 缺文件时 `_layout` 会自动退回旧布局，正好也是真项目的兜底路径。
    """
    d = tmp_path / "ws"
    (d / "video-pipeline" / "output" / "ep01" / "shot_001").mkdir(parents=True)
    return d


def test_discover_dedupes_and_filters(comfy) -> None:
    FakeComfy.reset(history=HISTORY)
    items = PULL.discover(comfy)
    names = sorted(x["filename"] for x in items)
    assert names == ["board_001.png", "h3_shot_001_111.mp4", "h3_shot_002_222.mp4"], names
    assert all("note.txt" != n for n in names)


def test_pull_places_into_shot_dir(comfy, tmp_path) -> None:
    ws = _ws(tmp_path)
    FakeComfy.reset(history=HISTORY,
                    files={"h3_shot_001_111.mp4": b"x" * 2048,
                           "h3_shot_002_222.mp4": b"y" * 1024,
                           "board_001.png": b"z" * 512})

    res = PULL.pull(str(ws), ep="ep01", url=comfy)
    assert res["ok"], res
    assert res["found"] == 3

    # 有同名镜目录 → 归位成 final.mp4（不是堆在下载目录）
    got = sorted(x["path"] for x in res["downloaded"])
    shot1 = ws / "video-pipeline" / "output" / "ep01" / "shot_001" / "final.mp4"
    assert shot1.is_file() and shot1.stat().st_size == 2048
    assert any(p.endswith("final.mp4") for p in got)
    # 没有镜目录的不新建结构，进暂存区
    assert any("_cloud_pull" in p for p in got)
    assert len(res["downloaded"]) == 3
    assert res["index"] and pathlib.Path(res["index"]).is_file()


def test_pull_is_idempotent(comfy, tmp_path) -> None:
    ws = _ws(tmp_path)
    FakeComfy.reset(history=HISTORY,
                    files={"h3_shot_001_111.mp4": b"x" * 2048,
                           "h3_shot_002_222.mp4": b"y" * 1024,
                           "board_001.png": b"z" * 512})
    PULL.pull(str(ws), ep="ep01", url=comfy)
    FakeComfy.hits.clear()

    res = PULL.pull(str(ws), ep="ep01", url=comfy)
    assert res["downloaded"] == [], res
    assert len(res["skipped"]) == 3
    # 幂等的判据必须是「没有发出下载请求」，不能只看返回值
    assert "/history" in FakeComfy.hits
    assert "/view" not in FakeComfy.hits


def test_pull_by_filename_when_history_empty(comfy, tmp_path) -> None:
    ws = _ws(tmp_path)
    FakeComfy.reset(history={}, files={"h3_shot_001_999.mp4": b"z" * 4096})

    res = PULL.pull(str(ws), ep="ep01", url=comfy, filename="h3_shot_001_999.mp4")
    assert res["ok"], res
    assert res["found"] == 1
    shot1 = ws / "video-pipeline" / "output" / "ep01" / "shot_001" / "final.mp4"
    assert shot1.is_file() and shot1.stat().st_size == 4096


def test_pull_reports_missing_file(comfy, tmp_path) -> None:
    ws = _ws(tmp_path)
    FakeComfy.reset(history={}, files={})
    res = PULL.pull(str(ws), ep="ep01", url=comfy, filename="gone.mp4")
    assert not res["ok"]
    assert len(res["failed"]) == 1
    assert "404" in res["failed"][0]["error"] or "HTTP" in res["failed"][0]["error"]


def test_pull_dry_run_writes_nothing(comfy, tmp_path) -> None:
    ws = _ws(tmp_path)
    FakeComfy.reset(history=HISTORY,
                    files={"h3_shot_001_111.mp4": b"x" * 2048})
    res = PULL.pull(str(ws), ep="ep01", url=comfy, dry_run=True)
    assert res["found"] == 3
    assert all(x.get("dry_run") for x in res["downloaded"])
    shot1 = ws / "video-pipeline" / "output" / "ep01" / "shot_001" / "final.mp4"
    assert not shot1.exists()
    assert "/view" not in FakeComfy.hits


def test_local_gaps(tmp_path) -> None:
    ws = _ws(tmp_path)
    base = ws / "video-pipeline" / "output" / "ep01"
    (base / "shot_002").mkdir(parents=True)
    (base / "shot_003").mkdir(parents=True)
    (base / "shot_001" / "final.mp4").write_bytes(b"ok")
    (base / "shot_002" / "final.mp4").write_bytes(b"")        # 空文件 = 没成片

    gap = PULL.local_gaps(str(ws), "ep01")
    assert gap["have"] == ["shot_001"]
    assert gap["missing"] == ["shot_002", "shot_003"]
    assert not gap["complete"]


def test_no_url_is_an_explicit_failure(tmp_path) -> None:
    """没地址时必须明确失败，不能悄悄下到当前目录（那会让人以为成功了）。"""
    import os
    old = os.environ.pop("COMFYUI_URL", None)
    try:
        res = PULL.pull(str(tmp_path), ep="ep01", url="")
        assert not res["ok"]
        assert "地址" in res["reason"]
    finally:
        if old is not None:
            os.environ["COMFYUI_URL"] = old
