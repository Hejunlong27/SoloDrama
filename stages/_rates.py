# -*- coding: utf-8 -*-
"""_rates.py —— 币种换算的**唯一真源**（纯常量，零依赖，任何层都能 import）

为什么单独成文件
----------------
「1 RH 币值多少人民币 / 1 美元值多少人民币」这两个数此前散在五处，且其中两处互相矛盾：

    web/core/ux.py                 0.0025 / 7.2
    web/core/studio.py             0.0025 / 7.2（另一行又写了一遍）
    web/core/inventory.py          0.0025
    web/ui/studio/js/ui.js         0.0025 / 7.2
    stages/.../cost_ledger.py      0.0025，注释说「隐含 USD/CNY ≈ 6.865」

后果不是崩溃，是**同一笔钱在两个页面上折出两个数字** —— 用户会拿它们互相印证，
一对不上就再也不信任何金额。

选哪个口径
----------
以**用户明确给定过的两个锚点**为准（它们是输入，不是估计）：

    1 美元 = 2746 RH 币   （用户 2026-09-19 确认）
    1 RH 币 = ¥0.0025     （用户 2026-09-18 确认）
    ⇒ 1 美元 = 6.865 元   （**派生值**，不要再手写一份）

`7.2` 是早期按市价随手填的近似值，与上面两个锚点不自洽 —— 已统一到 6.865。
这个汇率只用于**展示折算**，不参与任何计费判断；真实金额永远以平台 usage 为准。
"""
from __future__ import annotations

# —— 两个锚点（用户给定，改这里等于改口径，改完要跑 test_rates）——
RH_PER_USD = 2746.0
CNY_PER_RH = 0.0025

# —— 派生值（不要手写）——
CNY_PER_USD = RH_PER_USD * CNY_PER_RH          # 6.865

# 前端拿不到这个模块（JS），它那份副本在 web/ui/studio/js/ui.js；
# 两边必须一致，`web/tests/test_rates.py` 会逐字比对。
JS_RATE_FILE = "web/ui/studio/js/ui.js"


def cny(coins=0.0, usd=0.0) -> float:
    """把「RH 币 + 美元钱包」合成人民币总额（展示用，四舍五入交给调用方）。"""
    try:
        return float(coins or 0.0) * CNY_PER_RH + float(usd or 0.0) * CNY_PER_USD
    except (TypeError, ValueError):
        return 0.0
