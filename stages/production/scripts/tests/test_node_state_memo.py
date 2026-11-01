#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_node_state_memo.py —— 节点状态「不重复求值、也不拿旧结论」（离线）

两个断言，对应两件真实事故：

  A. **不重复求值**：`node_state` 递归查上游，原来 23 个节点会算成 553 次调用，
     其中 `cmd:` 判据被真跑 62 次（每次起一个 Python 子进程）——
     实测 `drama nodes --json` 要 22 秒，Studio 的流程页/项目详情首屏 22–25 秒。
     现在 `evaluate()` 传一份局部备忘录，**每个节点最多判一次**。

  B. **不拿旧结论**：备忘录如果挂在 `Ctx` 上，`Ctx` 被复用（测试里改完文件再判一次、
     或者同进程里连着跑两步）就会返回上一轮的结论 —— 那是「笑着骗人」的错。
     现在只有 `evaluate()` 显式传 memo，直接调 `node_state()` 永远重新读盘。
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
SCRIPTS = HERE.parent
sys.path.insert(0, str(SCRIPTS))

import nodes as N   # noqa: E402

FAILS = []
LAYOUT = {
    "layout_version": 1, "engine_root": "video-pipeline",
    "stages": {"research": "01-调研", "topic": "02-选题", "script": "03-剧本",
               "assets": "04-资产", "storyboard": "05-分镜", "prompts": "06-提示词",
               "film": "07-成片", "compliance": "08-合规", "release": "09-发行"},
    "data_rel": "../06-提示词", "out_rel": "../07-成片", "assets_rel": "../04-资产",
}


def check(cond, msg):
    print(("  [PASS] " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAILS.append(msg)


def test_each_node_judged_once():
    print("\n[A] 一次评估里每个节点最多判一次")
    ws = HERE / "fixtures" / "mini_drama"
    ctx = N.Ctx(ws.resolve(), "ep01")

    calls = {}
    real = N.check_node

    def counting(c, node):
        calls[node["id"]] = calls.get(node["id"], 0) + 1
        return real(c, node)

    N.check_node = counting
    try:
        N.evaluate(ctx)
    finally:
        N.check_node = real

    total = sum(calls.values())
    worst = max(calls.values()) if calls else 0
    top = max(calls.items(), key=lambda kv: kv[1]) if calls else ("-", 0)
    check(worst <= 1, "单节点最多判 1 次（最多的是 %s=%d）" % (top[0], top[1]))
    check(total <= len(N.NODES), "判据总调用 %d ≤ 节点数 %d" % (total, len(N.NODES)))
    print("      （真正跑到判据的节点 %d 个，其余被上游/产物挡住）" % len(calls))


def test_no_stale_result():
    print("\n[B] 直接调用不缓存（Ctx 复用时不会拿上一轮结论）")
    ws = (HERE / "fixtures" / "mini_drama").resolve()
    ctx = N.Ctx(ws, "ep01")
    node = N.NODE_BY_ID["research.market"]

    n = {"hit": 0}
    real = N._node_state_uncached

    def counting(c, nd, memo=None):
        n["hit"] += 1
        return real(c, nd, memo)

    N._node_state_uncached = counting
    try:
        N.node_state(ctx, node)
        N.node_state(ctx, node)
    finally:
        N._node_state_uncached = real

    # 不带 memo 时每次都要重新读盘；如果这里变成 1，说明缓存又挂回 Ctx 了
    check(n["hit"] == 2, "直接调两次 → 真判两次（实际 %d 次）" % n["hit"])

    # 反过来：evaluate 内部必须只判一次（同一次评估共享 memo）
    n2 = {"hit": 0}

    def counting2(c, nd, memo=None):
        n2["hit"] += 1
        return real(c, nd, memo)

    N._node_state_uncached = counting2
    try:
        N.evaluate(ctx)
    finally:
        N._node_state_uncached = real
    check(n2["hit"] <= len(N.NODES),
          "一次评估里真判 %d 次 ≤ 节点数 %d（备忘录生效）" % (n2["hit"], len(N.NODES)))


def main():
    test_each_node_judged_once()
    test_no_stale_result()
    print("\n" + "=" * 70)
    if FAILS:
        print("[FAIL] %d 项未通过" % len(FAILS))
        return 1
    print("[OK] 节点状态求值纪律全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
