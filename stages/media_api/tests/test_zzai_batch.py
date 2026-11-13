# -*- coding: utf-8 -*-
from __future__ import annotations

from stages.media_api import zzai_batch as ZB


def test_task_update_keeps_provider_usage_provisional(tmp_path):
    rec = ZB.task_new(
        tmp_path, kind="image", model="zhenzhen-image-g-v2.6-lowprice",
        purpose="test", request={"prompt": "x"}, estimate={"amount": 0.1},
        max_cost=0.2,
    )
    assert rec["settled_cost"] is None
    assert rec["cost_status"] == "unknown"
    ZB.task_update(tmp_path, rec, status="succeeded",
                   usage={"amount": 0.21, "currency": "CNY"},
                   artifact=str(tmp_path / "out.png"))
    assert rec["provider_usage_cost"] == {"amount": 0.21, "currency": "CNY"}
    assert rec["actual_cost"] is None
    assert rec["cost_source"] == "unknown"
    assert rec["cost_status"] == "provisional"
