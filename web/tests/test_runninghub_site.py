#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_runninghub_site.py —— 连接中心「站点」口径（离线）

为什么单独盯这一条：
  引擎从 2026-10-29 起**不再读** `RUNNINGHUB_BASE_URL`，站点真源是
  `configs/channels.json`（`_site.project_site`）。而连接中心一直在让人选站点、
  存进 `connections.json`、再注进环境 —— 于是三处各说各话：

    · 界面显示 `runninghub.ai`
    · 连接测试打 `runninghub.ai`（余额 13687）
    · 引擎出片打 `runninghub.cn`（余额 32689）

  **两个站是两套账户**，测通的站点和花钱的站点不是同一个 —— 这条错了不会报错，
  只会在出片时余额不足、或者账单对不上。

本测试钉三件事：
  1. `_engine_site()` 拿得到站点与来源；
  2. `overview()` 只在 runninghub 上暴露 `effective`，且与 `_engine_site()` 一致；
  3. `_test_runninghub()` 打的是 **effective**，不是 `connections.json` 里那份。
"""
from __future__ import annotations

import sys
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB))

from core import connections as C   # noqa: E402

FAILS = []


def check(cond, msg):
    print(("  [PASS] " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAILS.append(msg)


def test_engine_site():
    print("\n[1] 站点真源")
    url, src, ignored = C._engine_site()
    check(bool(url), "拿到站点：%r" % url)
    check(url.startswith("http"), "是 http(s) 地址")
    check(bool(src), "带来源说明：%s" % str(src)[:60])


def test_overview_shape():
    print("\n[2] overview 只对 runninghub 暴露 effective")
    ov = C.overview()
    items = {it["kind"]: it for it in ov["items"]}
    rh = items["runninghub"]
    check(isinstance(rh.get("effective"), dict), "runninghub 有 effective 块")
    check((rh.get("effective") or {}).get("base_url") == C._engine_site()[0],
          "effective.base_url 与 _engine_site 一致")
    check((rh.get("effective") or {}).get("source") is not None, "effective 带来源")
    for k in ("llm", "comfyui"):
        check(items[k].get("effective") is None, "%s 不该有 effective" % k)


def test_probe_uses_engine_site():
    print("\n[3] 连接测试打的是引擎站点")
    eff = "https://engine.example"
    stored = "https://stored.example"
    seen = {}

    real = {n: getattr(C, n) for n in ("_engine_site", "load", "get_key", "_json_post", "_rh_site_ok")}
    try:
        C._engine_site = lambda: (eff, "configs/channels.json", stored)
        C.load = lambda: {"runninghub": {"base_url": stored, "kind": "workflow"}}
        C.get_key = lambda kind: "k" * 8
        C._rh_site_ok = lambda u: True

        def fake_post(url, body):
            seen["url"] = url
            return 200, {"code": 0, "data": {"remainCoins": "1", "remainMoney": "0.1"}}
        C._json_post = fake_post

        res = C._test_runninghub()
    finally:
        for n, fn in real.items():
            setattr(C, n, fn)

    check(seen.get("url", "").startswith(eff), "请求打到引擎站点（实际 %r）" % seen.get("url"))
    site = (res.get("runninghub") or {}).get("site") or {}
    check(site.get("used") == eff, "结果里标注实际站点：%r" % site.get("used"))
    check(site.get("stored_ignored") is True, "标出「界面存的那份被忽略」")


def main():
    test_engine_site()
    test_overview_shape()
    test_probe_uses_engine_site()
    print("\n" + "=" * 70)
    if FAILS:
        print("[FAIL] %d 项未通过" % len(FAILS))
        return 1
    print("[OK] RunningHub 站点口径全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
