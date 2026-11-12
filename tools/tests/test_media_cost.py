# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import media_cost  # noqa: E402
from web.core import media_tasks  # noqa: E402


def test_settle_cli_writes_backend_cost(tmp_path, capsys):
    rec = media_tasks.create(
        tmp_path, kind="video", model="minimax-h3-comfyui-max",
        provider_id="zzai", request={"duration": 8},
    )
    rc = media_cost.main([
        "--workspace", str(tmp_path), "settle", rec["id"],
        "--amount", "0.21", "--currency", "CNY", "--note", "backend invoice",
    ])
    assert rc == 0, capsys.readouterr()
    out = media_tasks.get(tmp_path, rec["id"])
    assert out["actual_cost"] == {"amount": 0.21, "currency": "CNY"}
    assert out["settled_cost"] == {"amount": 0.21, "currency": "CNY"}
    assert out["cost_status"] == "settled"
    assert out["cost_source"] == "provider_backend"


def test_settle_cli_rejects_unknown_task(tmp_path):
    rc = media_cost.main([
        "--workspace", str(tmp_path), "settle", "mt_does_not_exist",
        "--amount", "0.21", "--currency", "CNY",
    ])
    assert rc == 2
