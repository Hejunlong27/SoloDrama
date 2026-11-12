# -*- coding: utf-8 -*-
"""Runner 离线测试：只验证调度、journal 与干跑，不执行真实生成。"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from stages.agent import journal, runner

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "stages" / "production" / "scripts" / "tests" / "fixtures" / "mini_drama"


def _workspace(tmp_path):
    ws = tmp_path / "mini_drama"
    shutil.copytree(FIXTURE, ws)
    os.environ["SOLODRAMA_WORKSPACE"] = str(ws)
    os.environ["DRAMA_WORKSPACE"] = str(ws)
    return ws


def test_status_reads_disk_state(tmp_path):
    ws = _workspace(tmp_path)
    out = runner.status(str(ws), "ep01")
    assert out["ok"] is True
    assert out["complete"] is False
    assert out["next"]["id"] == "import.pack"
    assert len(out["nodes"]) == 13


def test_dry_run_executes_one_node_and_stops(tmp_path):
    ws = _workspace(tmp_path)
    out = runner.run(str(ws), "ep01", apply=False, yes=False, max_steps=6)
    assert out["ok"] is True
    assert out["dry_run"] is True
    assert out["stopped"] == "dry_run"
    assert len(out["steps"]) == 1
    assert out["steps"][0]["node"] == "import.pack"
    # 干跑不改变磁盘判据，下一步仍然是 import.pack。
    assert runner.status(str(ws), "ep01")["next"]["id"] == "import.pack"


def test_journal_is_append_only_and_resumable(tmp_path):
    ws = _workspace(tmp_path)
    assert runner.run(str(ws), "ep01", apply=False, max_steps=1)["ok"] is True
    first = journal.recent(str(ws), 100)
    assert [x["event"] for x in first] == [
        "run_start", "node_start", "node_end", "run_end"]
    assert runner.run(str(ws), "ep01", apply=False, max_steps=1)["ok"] is True
    second = journal.recent(str(ws), 100)
    assert len(second) == len(first) * 2
    assert second[-1]["event"] == "run_end"


def test_unknown_only_is_rejected_without_journal_write(tmp_path):
    ws = _workspace(tmp_path)
    out = runner.run(str(ws), "ep01", only="not.a.node")
    assert out["ok"] is False
    assert "未知节点" in out["error"]
    assert journal.recent(str(ws), 10) == []

def test_active_lock_rejects_second_runner_without_touching_state(tmp_path):
    ws = _workspace(tmp_path)
    lock = runner._acquire_lock(str(ws), "test-holder")
    try:
        out = runner.run(str(ws), "ep01", apply=False, max_steps=1)
        assert out["ok"] is False
        assert out["rc"] == 4
        assert "已有调度任务" in out["error"]
        assert runner.status(str(ws), "ep01")["next"]["id"] == "import.pack"
    finally:
        runner._release_lock(lock)
    assert runner.lock_status(str(ws))["busy"] is False


def test_dry_run_result_exposes_steps_and_summary(tmp_path):
    ws = _workspace(tmp_path)
    out = runner.run(str(ws), "ep01", apply=False, yes=False, max_steps=3)
    assert out["dry_run"] is True
    assert out["summary"]["next"]["id"] == "import.pack"
    assert out["steps"][0]["state_before"] == "absent"
    assert out["steps"][0]["state_after"] == "absent"
def test_prescan_keeps_valid_env_when_argv_is_mojibaked(tmp_path, monkeypatch):
    ws = _workspace(tmp_path)
    monkeypatch.setenv("SOLODRAMA_WORKSPACE", str(ws))
    monkeypatch.setenv("DRAMA_WORKSPACE", str(ws))
    bad = str(ws) + "\\\ufffd"
    runner._prescan_workspace(["--workspace", bad])
    assert os.environ["SOLODRAMA_WORKSPACE"] == str(ws)
    assert os.environ["DRAMA_WORKSPACE"] == str(ws)