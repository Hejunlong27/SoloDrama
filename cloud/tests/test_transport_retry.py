"""cloud/tests/test_transport_retry.py —— SSH 搬运的退避重试

来源：2026-11-05 云端实测。
仙宫云的 sshd 在**磁盘 IO 饱和**时握手会被重置（`kex_exchange_identification:
Connection reset by peer`），此时端口通、进程在 —— 看起来像网络断了，其实是系统资源问题。
另外连续几十次连接会触发**限流**，恢复窗口约 60 秒。

所以 scp 必须：只对连接类错误重试、退避要够长、对「文件不存在」这类错误立刻失败
（重试只是在浪费 78 秒）。
"""
from __future__ import annotations

import subprocess
import sys
import types

import pytest

ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from cloud import transport as T          # noqa: E402


class _Proc:
    def __init__(self, rc=0, err=""):
        self.returncode = rc
        self.stdout = ""
        self.stderr = err


@pytest.fixture()
def fake_scp(monkeypatch):
    """把 scp 二进制与 subprocess.run 都换掉，并记录 sleep。"""
    monkeypatch.setattr(T, "_bin", lambda name: "scp")
    monkeypatch.setattr(T, "_size_of", lambda p: 1)
    sleeps: list = []
    monkeypatch.setattr(T.time, "sleep", lambda s: sleeps.append(s))
    return sleeps


def test_retries_on_connection_reset(fake_scp, monkeypatch) -> None:
    calls = {"n": 0}

    def run(cmd, **kw):
        calls["n"] += 1
        if calls["n"] < 3:
            return _Proc(1, "ssh: connect to host x port 22: Connection reset by peer")
        return _Proc(0, "")

    monkeypatch.setattr(subprocess, "run", run)
    res = T._scp("/local/a", "root@h:/root/a", port=22)
    assert res["ok"] is True
    assert calls["n"] == 3
    # 退避 3 → 15（第二次失败后睡 3，第三次前睡 15 之前还有一次）
    assert fake_scp[0] == 3


def test_kex_reset_is_retryable(fake_scp, monkeypatch) -> None:
    calls = {"n": 0}

    def run(cmd, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return _Proc(255, "kex_exchange_identification: read: Connection reset by peer")
        return _Proc(0, "")

    monkeypatch.setattr(subprocess, "run", run)
    assert T._scp("a", "b:c", port=22)["ok"] is True
    assert calls["n"] == 2


def test_no_retry_on_missing_file(fake_scp, monkeypatch) -> None:
    """`No such file or directory` 重试三次只会白等 78 秒。"""
    calls = {"n": 0}

    def run(cmd, **kw):
        calls["n"] += 1
        return _Proc(1, "scp: /local/a: No such file or directory")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(T.TransportError) as ei:
        T._scp("/local/a", "root@h:/root/a", port=22)
    assert calls["n"] == 1
    assert "No such file" in str(ei.value)
    assert fake_scp == []                  # 一次都没等


def test_gives_up_with_actionable_message(fake_scp, monkeypatch) -> None:
    monkeypatch.setattr(subprocess, "run",
                        lambda cmd, **kw: _Proc(1, "Connection timed out"))
    with pytest.raises(T.TransportError) as ei:
        T._scp("a", "b:c", port=22)
    msg = str(ei.value)
    assert "3/15/60" in msg                 # 说明退避策略
    assert "假死" in msg and "限流" in msg  # 说明两种根因
    assert len(fake_scp) == 3               # 3 → 15 → 60
    assert fake_scp == [3, 15, 60]


def test_timeout_is_reported(fake_scp, monkeypatch) -> None:
    def run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd="scp", timeout=1)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(T.TransportError) as ei:
        T._scp("a", "b:c", port=22, timeout=1)
    # 超时不在「连接类」词表里 → 立即失败，不重试
    assert "超时" in str(ei.value)
