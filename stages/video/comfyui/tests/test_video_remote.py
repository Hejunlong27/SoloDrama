"""test_video_remote.py —— 出片侧「云端执行器」的三处差异（离线，不连任何服务）

背景
----
2026-11-05 之前，`model_gate` 把 `video=cloud_comfyui` 标成 `executor: None`（暂无执行器），
门禁就拦住了 —— 所以「出片能走远端」其实一直没打通过。补齐之后，本机与远端走**同一份
客户端**（`comfy_local_video.py`），只差三件事，这三件事都必须可测：

  1. **超时档位**：远端放宽（多一层网络/排队），本地保持原值（5–10 分钟/段是实测事实）；
  2. **提交前释放显存**：云端两条工作流同时驻留会 OOM，而云端 OOM 表现为「任务消失」；
  3. **断点续传**：云端产物更大、链路更容易断。

守的另一件事：**本机行为完全不变** —— 这是本次改造唯一的回滚承诺。
"""
from __future__ import annotations

import inspect
import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve()
COMFY_DIR = HERE.parents[1]                 # stages/video/comfyui
sys.path.insert(0, str(COMFY_DIR))

import comfy_local_video as V               # noqa: E402


@pytest.fixture(autouse=True)
def _restore():
    old = (V.COMFY, V.Q)
    yield
    V.COMFY, V.Q = old


# ---------------------------------------------------------------------------
# 链路识别
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("url,loop", [
    ("http://127.0.0.1:8188", True),
    ("http://localhost:8188", True),
    ("https://abc-8188.container.x-gpu.com", False),
    ("http://192.168.1.9:8188", False),      # 内网也是远端：走网络、会排队
])
def test_is_loopback(url, loop):
    assert V._is_loopback(url) is loop


# ---------------------------------------------------------------------------
# 超时档位
# ---------------------------------------------------------------------------
def test_timeout_local_is_unchanged(monkeypatch):
    """★ 本地必须还是 20 分钟。文档里写的「本地 3.0」与实测冲突（5–10 分钟/段），
    这里以实测为准 —— 把本地压到 3 分钟等于用新功能换旧回归。"""
    monkeypatch.delenv("SOLODRAMA_VIDEO_TIMEOUT_MIN", raising=False)
    V.COMFY = "http://127.0.0.1:8188"
    assert V._default_timeout_min() == 20.0


def test_timeout_remote_is_wider(monkeypatch):
    monkeypatch.delenv("SOLODRAMA_VIDEO_TIMEOUT_MIN", raising=False)
    V.COMFY = "https://abc-8188.container.x-gpu.com"
    assert V._default_timeout_min() == 30.0
    assert V._default_timeout_min() > 20.0, "远端不该比本地更短"


def test_timeout_env_override(monkeypatch):
    monkeypatch.setenv("SOLODRAMA_VIDEO_TIMEOUT_MIN", "7.5")
    assert V._default_timeout_min() == 7.5


def test_timeout_env_garbage_falls_back(monkeypatch):
    monkeypatch.setenv("SOLODRAMA_VIDEO_TIMEOUT_MIN", "半小时")
    V.COMFY = "http://127.0.0.1:8188"
    assert V._default_timeout_min() == 20.0


def test_submit_and_wait_accepts_none():
    """`timeout_min=None` 必须合法（批量/CLI 靠它走自动档）。"""
    sig = inspect.signature(V.submit_and_wait)
    assert sig.parameters["timeout_min"].default is None


# ---------------------------------------------------------------------------
# 提交前释放显存（远端专属）
# ---------------------------------------------------------------------------
class _FakeQ:
    """够用的假 HTTP 层：只回答 submit_and_wait 真正问到的四个接口。"""

    class ComfyError(RuntimeError):
        pass

    ComfyError = ComfyError

    def __init__(self):
        self.calls = []

    def free_memory(self, **kw):
        self.calls.append(("free", kw))
        return {}

    def queue_state(self):
        return {"running": [], "pending": [], "running_count": 0, "pending_count": 0}

    def post_json(self, path, payload, **kw):
        self.calls.append(("post", path))
        return {"prompt_id": "p-1"}

    def get_json(self, path, **kw):
        return {"p-1": {"outputs": {"148": {"gifs": [{"filename": "a.mp4", "type": "output"}]}},
                        "status": {"status_str": "success"}}}


@pytest.fixture()
def fake(monkeypatch):
    fq = _FakeQ()
    monkeypatch.setattr(V, "Q", fq)
    monkeypatch.setattr(V.time, "sleep", lambda *_: None)     # 别真等 1 秒
    return fq


def test_remote_frees_vram_before_submit(fake):
    V.COMFY = "https://abc-8188.container.x-gpu.com"
    res = V.submit_and_wait({}, timeout_min=1)
    assert [c for c in fake.calls if c[0] == "free"], "远端提交前必须请求 /free"
    assert res["files"][0]["filename"] == "a.mp4"


def test_local_does_not_touch_free(fake):
    """本机不调 /free：本机 8G 上那会清掉刚加载的模型，下一镜要重新 offload（更慢）。"""
    V.COMFY = "http://127.0.0.1:8188"
    V.submit_and_wait({}, timeout_min=1)
    assert not [c for c in fake.calls if c[0] == "free"]


def test_free_failure_does_not_block_submit(fake, monkeypatch):
    """释放显存只是优化，不是前置条件 —— 它失败不该让整批停下。"""
    def boom(**kw):
        raise RuntimeError("HTTP 500")
    monkeypatch.setattr(fake, "free_memory", boom)
    V.COMFY = "https://abc-8188.container.x-gpu.com"
    res = V.submit_and_wait({}, timeout_min=1)
    assert res["files"]


# ---------------------------------------------------------------------------
# 门禁与分派（结构断言：命令面真的接上了）
# ---------------------------------------------------------------------------
def test_drama_accepts_cloud_engine():
    """`drama video run --engine` 必须接受 cloud（与本机同一条执行分支）与 auto（按确认单）。

    这里不比对整行字符串：加一个取值就断的断言守不住行为，只会让人去改断言。
    解析 choices 元组，再断言「必须有的都在」。
    """
    import re

    src = (COMFY_DIR.parents[2] / "stages" / "production" / "scripts" / "drama.py").read_text(
        encoding="utf-8")
    # 注意：`assets` 与 `video run` 各有一个 --engine（前者是 local/cloud/wf/rh），
    # 所以这里找**所有**声明，再挑出视频的那一个 —— 别取第一个就断言。
    found = re.findall(r"add_argument\(\s*['\"]--engine['\"]\s*,\s*choices=\(([^)]*)\)", src)
    assert found, "找不到 --engine 的 choices 声明"
    sets = [{c.strip().strip("'\"") for c in g.split(",") if c.strip()} for g in found]
    video = [s for s in sets if "workflow" in s]
    assert video, "video run 的 --engine 必须接受 workflow（RunningHub 通道）：%s" % sets
    choices = video[0]
    assert {"local", "cloud"} <= choices, choices
    assert "auto" in choices, "节点模板用 --engine auto 按模型确认单选通道（V0.7.71）"
    assert "in ('local', 'cloud')" in src, "cloud 应与 local 走同一条执行分支"
    assert "--comfy-url" in src


def test_model_gate_video_cloud_has_executor():
    sys.path.insert(0, str(COMFY_DIR.parents[2] / "stages" / "production" / "scripts"))
    import model_gate as MG
    opt = [o for o in MG.MODEL_OPTIONS["video"] if o["id"] == "cloud_comfyui"][0]
    assert opt["engine_arg"] == "cloud"
    assert "comfy_local_video.py" in opt["executor"]
    assert opt["requires"] == ["comfy_url"], "工作流随仓库交付，只强制地址"
