#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_rates.py —— 汇率只有一个真源，金额只有一处聚合

起因（2026-11-06 复盘 B5 / R3）
------------------------------
同一笔钱在三处折出两个数字：`ux` / `studio` / `ui.js` 用 `USD 1 = ¥7.2`，
而 `cost_ledger` 的锚点（2746 RH币/美元 × ¥0.0025/币）隐含 **6.865**。
更糟的是 `studio` 里同一个页面上有两套口径：
`time_summary().ledger.coins`（按台账 attempt 求和）与 `studio().spend.coins`（inventory 去重）。

现在：真源 `stages/_rates.py`（两个用户给定锚点 + 派生汇率）→ `web/core/fx.py` →
`inventory.spend.cny`（唯一聚合）→ 其余层只读。本文件钉住这条链。
"""
from __future__ import annotations

import pathlib
import sys

WEB = pathlib.Path(__file__).resolve().parents[1]
ROOT = WEB.parent
for p in (str(WEB), str(ROOT / "stages")):
    if p not in sys.path:
        sys.path.insert(0, p)

import _rates  # noqa: E402
from core import fx, inventory, ux  # noqa: E402

FIXTURE = ROOT / "stages" / "production" / "scripts" / "tests" / "fixtures" / "mini_drama"


def test_single_source_constants():
    """展示层拿到的必须就是锚点派生值，不能是各自手抄的一份。"""
    assert fx.COIN_TO_CNY == _rates.CNY_PER_RH == 0.0025
    assert fx.USD_TO_CNY == _rates.CNY_PER_USD
    assert abs(fx.USD_TO_CNY - 6.865) < 1e-9, "1 美元 = 2746 × 0.0025 = 6.865"


def test_ux_constants_follow_fx():
    """`ux` 保留这两个名字只为兼容；值必须跟 fx 走（谁再把 7.2 写回来，这条就红）。"""
    assert ux.COIN_TO_CNY == fx.COIN_TO_CNY
    assert ux.USD_TO_CNY == fx.USD_TO_CNY


def test_inventory_is_the_only_aggregator():
    """`inventory.spend.cny` 必须存在，且等于按同一组汇率算出来的值。"""
    inv = inventory.inventory(str(FIXTURE))
    sp = inv["spend"]
    assert "cny" in sp, "inventory 没给出 cny —— 那别处就又会各自算一遍"
    assert abs(sp["cny"] - round(fx.cny(sp["coins"], sp["usd"]), 2)) <= 0.01, sp


def test_no_hardcoded_rate_arithmetic():
    """代码里不许再出现「字面量 × 汇率」的算式（注释里的数字不算）。

    用 AST 找 BinOp 里的浮点常量：`x * 0.0025` / `x * 7.2` / `x * 6.865` 都算违规。
    比 grep 可靠 —— 这几个数在解释性注释里还会出现，grep 会误报，人就会去删告警。
    """
    import ast

    offenders = []
    for name in ("ux.py", "studio.py", "inventory.py"):
        path = WEB / "core" / name
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Mult):
                continue
            for side in (node.left, node.right):
                if isinstance(side, ast.Constant) and isinstance(side.value, float) \
                        and abs(side.value) in (0.0025, 7.2, 6.865):
                    offenders.append("%s:%d" % (name, node.lineno))
    assert not offenders, "这些位置还在手写汇率：%s（改读 fx / inventory.spend.cny）" % offenders
