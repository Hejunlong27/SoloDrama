# -*- coding: utf-8 -*-
"""fx.py —— 汇率/金额换算的 Web 层入口（真源在 `stages/_rates.py`）

为什么还要这一层
----------------
`stages/_rates.py` 是零依赖的纯常量模块，Web 层（`ux` / `studio` / `inventory`）都该读它。
但 Web 代码不该各自 `sys.path.insert` 再 import —— 那样又多出三份「怎么找 stages」。
这里收一次：路径装配 + 缺文件时的兜底。

历史问题（2026-11-06 复盘 B5）
------------------------------
同一笔钱在三处折出两个数字：`ux` / `studio` / `ui.js` 用 `USD 1 = ¥7.2`，
而 `cost_ledger` 的锚点（2746 RH币/美元 × ¥0.0025/币）隐含 **6.865**。
现在统一走锚点派生值；`ui.js` 那份副本是死代码，已删。
"""
from __future__ import annotations

from . import paths

try:
    paths.ensure_layout_importable()          # 顺带把仓库 stages/ 加进 sys.path
    import _rates as _R                        # noqa: PLC0415
except Exception:                              # noqa: BLE001 —— 打包/裁剪环境兜底
    class _R:                                  # type: ignore[no-redef]
        RH_PER_USD, CNY_PER_RH, CNY_PER_USD = 2746.0, 0.0025, 6.865
        @staticmethod
        def cny(coins=0.0, usd=0.0):
            return float(coins or 0) * 0.0025 + float(usd or 0) * 6.865

# 对外只暴露这三个名字（其余模块不要再写 0.0025 / 7.2 / 6.865）
COIN_TO_CNY = _R.CNY_PER_RH          # 1 RH 币 → 人民币
USD_TO_CNY = _R.CNY_PER_USD          # 1 美元 → 人民币（派生：2746 × 0.0025）


def cny(coins=0.0, usd=0.0) -> float:
    """把「RH 币 + 美元钱包」合成人民币总额。**展示用**，不参与任何计费判断。"""
    return _R.cny(coins, usd)
