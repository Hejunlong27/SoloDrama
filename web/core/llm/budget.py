# -*- coding: utf-8 -*-
"""budget.py —— 单集时长/镜数口径的**唯一入口**（提示词与校验器共用）

为什么单拎一个模块
------------------
「60 秒档 = 5-10 镜、总时长 60-80 秒」这条口径有两个消费者：
  * `drafts.py` 在生成后**复算**并拒收超界产物；
  * `templates.py` 在**提示词**里告诉模型边界是多少。
如果两边各写一份常量，迟早漂移 —— 表现为「提示词说 60-80，校验器说 65-85」，
模型永远无法通过。所以真源放这里，两边都从这里取。

数值本身不在这里发明：优先问引擎 `script_rewrite.py` 的 `bounds_for()`，
引擎不可用（比如只装了 Web 层）才退回本地副本。
"""
from __future__ import annotations

import sys

from .. import paths

# 引擎不可用时的兜底副本（与 `stages/creation/scripts/script_rewrite.py` 保持一致）
_SECONDS = {60: (5, 10, 60, 80), 70: (5, 12, 70, 95), 90: (6, 15, 90, 120)}


def _engine():
    try:
        s = str(paths.CREATION_SCRIPTS)
        if s not in sys.path:
            sys.path.insert(0, s)
        import script_rewrite  # noqa: PLC0415
        return script_rewrite
    except Exception:  # noqa: BLE001
        return None


def bounds_for(ep_seconds):
    """返回 (镜数下限, 镜数上限, 总时长下限, 总时长上限)。"""
    eng = _engine()
    if eng is not None:
        try:
            return eng.bounds_for(ep_seconds)
        except Exception:  # noqa: BLE001
            pass
    sec = int(ep_seconds or 60)
    return _SECONDS[min(_SECONDS, key=lambda s: abs(s - sec))]
