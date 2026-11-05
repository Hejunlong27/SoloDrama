"""tests/test_cost_observed.py —— 费用展示只能报「实跑数据」，不许再报预估价

背景（2026-11-05）
------------------
`cost_model` 的内置参数（27 币/任务 + 1 币/秒）来自 2026-10-19 某一个档位的实测；
真实项目台账 307 条记录的中位数是 **45 币/段、6.07 币/秒**，比内置值高约 4 倍。

更糟的是**它从来没被校准过**：`iter_ledger_records` 读 `<ws>/ledger/runs`，
而引擎写台账到 `<ws>/video-pipeline/ledger/runs` —— 两个路径不是同一个地方，
于是 `--calibrate` 在真实项目里永远「样本不足」并且不报错。

所以这里钉三件事：
  1. 两处台账都要读得到（否则校准永远失效）；
  2. `observed()` 只报事实，样本不足时给 None 而不是 0（0 会被读成「免费」）；
  3. 面向用户的文案里不许再出现预估价（回归防线：改了实现忘了改文案 = 用户仍看到错的数）。
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

PROD = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROD))

import cost_model as CM                      # noqa: E402


def _write_runs(root: pathlib.Path, rows) -> None:
    """按引擎真实格式写台账：`<dir>/<ts>__<shot>.json`，attempts[].usage。"""
    root.mkdir(parents=True, exist_ok=True)
    for i, r in enumerate(rows):
        doc = {"shot_id": r.get("shot_id") or "shot_%03d" % (i + 1),
               "attempts": [{"status": "SUCCESS",
                             "duration_s": r.get("duration_s"),
                             "usage": {"consumeCoins": r.get("coins"),
                                       "thirdPartyConsumeMoney": r.get("money"),
                                       "taskCostTime": r.get("gpu")}}]}
        (root / ("20261105_%06d__%s.json" % (i, doc["shot_id"]))).write_text(
            json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def test_reads_engine_ledger_path(tmp_path) -> None:
    """引擎写在 `video-pipeline/ledger/runs` —— 只读 `<ws>/ledger/runs` 会永远 0 样本。"""
    ws = tmp_path / "ws"
    _write_runs(ws / "video-pipeline" / "ledger" / "runs",
                [{"duration_s": 5, "coins": 124, "gpu": 169}])
    recs = CM.iter_ledger_records(ws)
    assert len(recs) == 1, recs
    assert recs[0]["coins"] == 124


def test_reads_both_paths(tmp_path) -> None:
    ws = tmp_path / "ws"
    _write_runs(ws / "ledger" / "runs", [{"duration_s": 5, "coins": 100}])
    _write_runs(ws / "video-pipeline" / "ledger" / "runs",
                [{"duration_s": 7, "coins": 140}])
    assert len(CM.iter_ledger_records(ws)) == 2


def test_observed_medians(tmp_path) -> None:
    ws = tmp_path / "ws"
    _write_runs(ws / "video-pipeline" / "ledger" / "runs", [
        {"duration_s": 5, "coins": 100, "gpu": 150},
        {"duration_s": 5, "coins": 120, "gpu": 160},
        {"duration_s": 7, "coins": 140, "gpu": 200},
    ])
    o = CM.observed(ws)
    assert o["samples"] == 3
    assert o["coins_per_shot"] == 120          # 中位
    assert o["coin_range"] == (100, 140)
    assert o["coins_per_second"] == pytest.approx(20.0)   # 每条各自 币/秒 后的中位数 = 20
    assert o["shot_seconds_median"] == 5.0
    assert o["gpu_seconds_per_second"] == pytest.approx(30.0)


def test_observed_pairs_ratio_per_row(tmp_path) -> None:
    """币/秒必须一条记录内部相除，不能拿 A 的币除 B 的秒。

    构造：短段贵、长段便宜。若错用「总币/总秒」，结果会是 240/17≈14.1；
    正确做法是各算各的再取中位 = (20+10)/2 = 15。
    """
    ws = tmp_path / "ws"
    _write_runs(ws / "video-pipeline" / "ledger" / "runs", [
        {"duration_s": 5, "coins": 100},        # 20 币/秒
        {"duration_s": 12, "coins": 120},       # 10 币/秒
    ])
    o = CM.observed(ws)
    assert o["coins_per_second"] == pytest.approx(15.0), o["coins_per_second"]


def test_observed_empty_is_none_not_zero(tmp_path) -> None:
    """没有记录时必须给 None —— 0 会被界面读成「免费」。"""
    o = CM.observed(tmp_path / "empty")
    assert o["samples"] == 0
    assert o["coins_per_shot"] is None
    assert o["coins_per_second"] is None
    assert o["coin_range"] is None


def test_observed_respects_last(tmp_path) -> None:
    """`last` 是「只看最近 N 条」—— 故意混入一个异常值，验证窗口真的在截断。

    注意：中位数对单个异常值不敏感（这正是用它的理由），所以断言看的是
    「窗口长度」和「异常值是否进了窗口」，而不是让中位数等于那个异常值。
    """
    ws = tmp_path / "ws"
    _write_runs(ws / "video-pipeline" / "ledger" / "runs",
                [{"duration_s": 5, "coins": 10}] * 30 + [{"duration_s": 5, "coins": 999}])
    o = CM.observed(ws, last=5)
    assert o["samples"] == 5
    assert o["coin_range"][1] == 999            # 异常值在窗口内
    assert o["coins_per_shot"] == 10            # 但中位数不跟着跑（5 个值里 4 个是 10）

    # 窗口缩到 1 条时，只剩那个异常值 —— 证明截断的方向是「从尾部取」
    assert CM.observed(ws, last=1)["coins_per_shot"] == 999


def test_no_price_estimate_in_user_facing_text() -> None:
    """回归防线：文案里不许再出现预估价。

    这一条测的是「话术」，看起来不技术，但它防的正是最坏的情形 ——
    实现改成了实测，界面却还在说「预估 32 RH币」。
    """
    src = (PROD / "drama.py").read_text(encoding="utf-8")
    for bad in ("两段式预估", "GPU 秒口径  : %.0f 运行秒 × 0.205",
                "预估 %d RH币", "CHAR_RH_PER_IMAGE", "CNY_PER_RH"):
        assert bad not in src, "预估价文案仍在：%s" % bad
    # 替换后的口径必须在
    assert "实测参考" in src
    assert "按实测推算" in src
