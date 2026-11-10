# -*- coding: utf-8 -*-
"""按集评估（`workflow?ep=`）的链路守卫。

为什么需要这条测试
------------------
`nodes status --ep ep03` 是否真的被调用，肉眼看不出来：本机**没有任何项目**建立了
`data/<ep>/` 契约层（实测扫全部登记项目，0 个命中），于是一个「按集评估」的界面
在真机上切换任何集都会得到同一份结果 —— 看起来像功能坏了，其实是数据层没有。

所以这里不依赖任何项目，直接把链路钉死：
  1. 适配器必须把 `--ep` 拼进子进程参数；
  2. 不传 ep 时**不得**拼 `--ep`（否则会把「不指定」变成「指定 ep01」，
     掩盖「这个项目到底有没有第 N 集」）；
  3. 两种情况的缓存键必须不同（缓存键含 args，靠这条防止退化）。

```bash
python -m pytest web/tests/test_studio_ep.py -q
```
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.core import adapters  # noqa: E402


def _capture(monkeypatch):
    """拦住真正的子进程，只记 argv。"""
    calls = []

    def fake(script_key, args, ws, **kw):
        calls.append({"script": script_key, "args": list(args), "ws": ws, "kw": kw})
        return {"ok": True, "rc": 0, "data": {"nodes": [], "stages": []},
                "reason": "", "text_tail": "", "elapsed": 0.0}

    monkeypatch.setattr(adapters, "run_json", fake)
    return calls


def test_ep_is_forwarded(monkeypatch):
    calls = _capture(monkeypatch)
    adapters.workflow_status("D:/tmp/剧", "ep03")
    assert calls, "没有调用 run_json"
    args = calls[0]["args"]
    assert "--ep" in args, "ep 没有透传给引擎：%s" % args
    assert args[args.index("--ep") + 1] == "ep03", "ep 值不对：%s" % args


def test_empty_ep_means_unspecified(monkeypatch):
    calls = _capture(monkeypatch)
    adapters.workflow_status("D:/tmp/剧")
    adapters.workflow_status("D:/tmp/剧", "")
    for c in calls:
        assert "--ep" not in c["args"], (
            "空 ep 不应该拼 --ep —— 那会把「不指定」变成「指定 ep01」，"
            "掩盖项目是否真的有这一集。实际参数：%s" % c["args"])


def test_cache_key_differs_by_ep(monkeypatch):
    """缓存键必须区分集号，否则切集后拿到的还是上一集的结果。

    这条不能靠假 run_json 验证：假函数一装，`_cached` 就根本不执行了。
    所以要往下沉一层 —— 拦住真正的子进程（runner.run_stream），让 run_json 的
    取键逻辑跑完整。
    """
    adapters._CACHE.clear()
    monkeypatch.setattr(adapters.runner, "run_stream",
                        lambda argv, **kw: {"lines": ['{"x":1}'], "rc": 0, "elapsed": 0.0})
    monkeypatch.setattr(adapters.jsonout, "extract_json", lambda text: {"x": 1})

    adapters.workflow_status("D:/tmp/剧", "ep01")
    adapters.workflow_status("D:/tmp/剧", "ep02")
    keys = [k for k in adapters._CACHE if "nodes" in k]
    adapters._CACHE.clear()
    assert len(keys) == 2, "ep01 与 ep02 没生成两个缓存键，切集会读到旧结果：%s" % keys
    assert any("ep01" in k for k in keys) and any("ep02" in k for k in keys), keys
