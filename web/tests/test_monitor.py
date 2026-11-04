#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_monitor.py —— 资源监视快照的口径（离线）

这条监控条最容易犯的错是**「看着有数，其实错了」**：

  ① 单位用 GB（/1000³）而不是 GiB（/1024³）→ 和资源管理器对不上，
     用户会以为工具算错了，然后不再相信它；
  ② 磁盘只看 C: → 成片落在 D:，卡住的永远是 D:，监控条却一片绿；
  ③ 同一块盘出现两条（工作区与仓库同盘）→ 两个一模一样的 100% 会让人以为有两块盘；
  ④ 显存取不到就抛异常 → 整个顶栏挂掉，连内存和磁盘也看不到了。

所以这里钉的是：结构稳定、单位一致、同盘去重、取不到时降级而不是崩。
"""
from __future__ import annotations

import sys
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB))

from core import monitor   # noqa: E402

GiB = 1024.0 ** 3


# ---------------------------------------------------------------------------
# 纯函数
# ---------------------------------------------------------------------------
def test_pct_bounds():
    assert monitor._pct(0, 0) == 0.0, "分母为 0 时要给 0，不能 ZeroDivisionError"
    assert monitor._pct(5, 10) == 0.5
    assert monitor._pct(20, 10) == 1.0, "超过总量要夹到 1（驱动偶尔会报增量）"
    assert monitor._pct(-3, 10) == 0.0, "负数夹到 0"


def test_units_are_gib():
    """快照里的 *_gib 必须是 /1024³，和资源管理器一致。"""
    if monitor.sys.platform != "win32":
        return
    d = monitor.snapshot("__unit_probe__", ttl=0)
    m = d["mem"]
    if not m.get("ok"):
        return
    assert abs(m["total_gib"] - m["total"] / GiB) < 0.06, "内存总量换算不是 1024 进制"


def test_disk_root():
    if monitor.sys.platform == "win32":
        assert monitor._disk_root("D:/剧本/海外剧/6/X") == "D:\\"
        assert monitor._disk_root("D:\\a\\b") == "D:\\"


def test_disk_dedup():
    """同一个盘给两个标签，只能出一行（同盘去重）。"""
    repo = str(monitor.paths.REPO_ROOT)
    rows = monitor.disk([("仓库", repo), ("工作区", repo)])
    assert len(rows) == 1, "同一块盘被算了两遍：%r" % [r.get("mount") for r in rows]
    assert rows[0]["ok"] is True
    assert rows[0]["total"] > 0
    assert 0.0 <= rows[0]["pct"] <= 1.0
    # free 与 used 要能对得上，差 1% 以内（两次系统调用之间会被别的进程写一点）
    assert abs((rows[0]["used"] + rows[0]["free"]) - rows[0]["total"]) <= rows[0]["total"] * 0.01


# ---------------------------------------------------------------------------
# 快照结构
# ---------------------------------------------------------------------------
def test_snapshot_shape():
    d = monitor.snapshot("__shape_probe__", ttl=0)
    assert d["ok"] is True
    for k in ("ts", "gpu", "mem", "disk", "elapsed_ms"):
        assert k in d, "缺字段 %s" % k
    assert isinstance(d["disk"], list) and d["disk"], "仓库所在盘必须至少有一条"

    g = d["gpu"]
    assert isinstance(g, dict) and "ok" in g
    if g["ok"]:
        assert g["total"] > 0 and "name" in g
        assert 0.0 <= g["pct"] <= 1.0
    else:
        assert g.get("reason"), "取不到显存必须给理由，不能只有 ok:False"

    m = d["mem"]
    assert isinstance(m, dict) and "ok" in m
    if m["ok"]:
        assert m["total"] > 0
        assert 0.0 <= m["pct"] <= 1.0
        assert m["used"] <= m["total"] + 1


def test_unknown_ws_falls_back():
    """工作区不存在时不能崩：仍然给仓库盘，`ok` 仍为真。"""
    d = monitor.snapshot("Z:/this/path/does/not/exist", ttl=0)
    assert d["ok"] is True
    assert len(d["disk"]) >= 1


def test_cache_same_ws():
    """TTL 内同一个 ws 复用同一个对象：3 秒轮询不该每次都 fork 一次 nvidia-smi。"""
    monitor.clear_cache()
    a = monitor.snapshot("__cache_probe__", ttl=5)
    b = monitor.snapshot("__cache_probe__", ttl=5)
    assert a is b, "缓存没生效"
    c = monitor.snapshot("__cache_probe2__", ttl=0)
    assert c is not a, "不同工作区不能共用缓存（磁盘不一样）"


def test_gpu_missing_is_graceful():
    """没有 nvidia-smi 时只让 gpu 段降级，其余两项照常。"""
    saved, saved_tried = monitor._SMI, monitor._SMI_TRIED
    try:
        monitor._SMI, monitor._SMI_TRIED = "", True     # 伪装成「找不到」
        g = monitor.gpu()
        assert g["ok"] is False
        assert g.get("reason")
        assert "nvidia-smi" in g["reason"]
        d = monitor.snapshot("__nogpu_probe__", ttl=0)
        assert d["ok"] is True, "显存取不到不能拖垮整个快照"
        assert d["mem"].get("ok") or d["mem"].get("reason")
        assert d["disk"], "磁盘段仍然要有数据"
    finally:
        monitor._SMI, monitor._SMI_TRIED = saved, saved_tried


def main():
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("  [PASS] " + name)
            except AssertionError as e:
                fails += 1
                print("  [FAIL] %s：%s" % (name, e))
    print("-" * 60)
    print("[OK] 资源监视口径全部通过" if not fails else "[FAIL] %d 项未通过" % fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
