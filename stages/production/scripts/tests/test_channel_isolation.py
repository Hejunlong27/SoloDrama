"""test_channel_isolation.py —— 「图像接本地、视频接云端」这条拼凑方案能不能站得住

为什么必须测隔离
----------------
`COMFYUI_URL` 只有**一个**环境变量，而图像与视频是两类任务、可以各走各的通道：

    图像 → 本地 ComfyUI（￥0）      视频 → 云端镜像（★计费，1.59 元/时）

拼凑本身是产品诉求（本机出图快、云端出片强）。但它有个安静的失效方式：
**上一个任务留下的地址被下一个任务继承**。表现是「图像明明配了本地，却跑到云端出图」——
不报错、不崩，只是账和产物都不是你以为的那台机器。

所以这里守三条：

  1. 按类解析：`resolve('image')` 与 `resolve('video')` 各回各的地址，互不覆盖；
  2. 确认单优先于全局环境变量：确认单里写了本地，就不能被残留的云端地址盖掉；
  3. 缺依据时不猜：确认单没写地址就保留环境变量（那是用户显式设的），不要擅自改写。
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve()
SCRIPTS = HERE.parents[1]                   # stages/production/scripts
ROOT = HERE.parents[4]
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT))

import gen_preflight as GP                  # noqa: E402

LOCAL = "http://127.0.0.1:8188"
CLOUD = "https://abc-8188.container.x-gpu.com"


def _plan(tmp_path, image=None, video=None) -> pathlib.Path:
    """造一个带 layout.json 的最小工作区（`_ws.resolve` 认这个标志物）。"""
    (tmp_path / "layout.json").write_text("{}", encoding="utf-8")
    models = {}
    for kind, det in (("image", image), ("video", video)):
        if det is None:
            continue
        models[kind] = {"choice": det.get("choice", "local_comfyui"), "confirmed": True,
                        "detail": {k: v for k, v in det.items() if k != "choice"}}
    (tmp_path / "model-plan.json").write_text(
        json.dumps({"gate_version": 2, "models": models}, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def test_resolve_is_per_kind(tmp_path, monkeypatch):
    """两条线各回各的地址 —— 拼凑方案的前提。"""
    ws = _plan(tmp_path,
               image={"choice": "local_comfyui", "comfy_url": LOCAL},
               video={"choice": "cloud_comfyui", "comfy_url": CLOUD})
    monkeypatch.delenv("COMFYUI_URL", raising=False)
    assert GP.resolve("image", ws)["url"] == LOCAL
    assert GP.resolve("video", ws)["url"] == CLOUD
    assert GP.resolve("image", ws)["url_via"] == "模型确认单"


def test_image_env_not_polluted_by_cloud(tmp_path, monkeypatch):
    """★ 核心：先把 env 污染成云端，再注入图像依据，必须回到本地并标注原值。"""
    ws = _plan(tmp_path, image={"choice": "local_comfyui", "comfy_url": LOCAL})
    monkeypatch.setenv("SOLODRAMA_WORKSPACE", str(ws))
    monkeypatch.setenv("COMFYUI_URL", CLOUD)
    for m in ("gen_assets_local", "_ws"):
        sys.modules.pop(m, None)
    try:
        import gen_assets_local as G                     # noqa: PLC0415
        applied = G._apply_model_plan_env()
        assert os.environ["COMFYUI_URL"] == LOCAL, "确认单的本地地址被残留的云端地址盖掉了"
        assert "原" in applied.get("COMFYUI_URL", ""), "覆盖要留痕（否则没人查得出为什么换了机器）"
    finally:
        sys.modules.pop("gen_assets_local", None)


def test_no_detail_keeps_env(tmp_path, monkeypatch):
    """确认单没写地址时不许擅自改写环境变量 —— 那是用户显式设的。"""
    ws = _plan(tmp_path, image={"choice": "local_comfyui"})
    monkeypatch.setenv("SOLODRAMA_WORKSPACE", str(ws))
    monkeypatch.setenv("COMFYUI_URL", "http://127.0.0.1:9000")
    for m in ("gen_assets_local", "_ws"):
        sys.modules.pop(m, None)
    try:
        import gen_assets_local as G                     # noqa: PLC0415
        G._apply_model_plan_env()
        assert os.environ["COMFYUI_URL"] == "http://127.0.0.1:9000"
    finally:
        sys.modules.pop("gen_assets_local", None)


def test_cloud_engine_with_local_address_is_refused(tmp_path):
    """通道=cloud 但地址是本机 → 判「待配置」，不冒充可用。"""
    ws = _plan(tmp_path, image={"choice": "cloud_comfyui", "comfy_url": LOCAL})
    r = GP.check("image", "cloud", ws)
    assert r["ok"] is False and r["status"] == "config", GP.render(r)
    assert "models set image=cloud_comfyui" in (r["next"] or "")


def test_assets_has_cloud_route():
    """结构断言：`drama assets` 必须接受 --engine cloud（否则图像云端只能确认、不能跑）。"""
    src = (SCRIPTS / "drama.py").read_text(encoding="utf-8")
    assert "choices=('local', 'cloud', 'wf', 'rh')" in src, "图像云端通道没有入口"
    assert "expected_engine=engine" in src, "出图门禁没有按实际通道比对"
    assert "'--comfy-url', url" in src, "云端出图没有把地址显式传给子进程"


def test_video_local_passes_explicit_url():
    """结构断言：本机出片也要显式传地址，不能吃进程里残留的 COMFYUI_URL。

    ★ 2026-11-06：断言从「逐字匹配调用串」改成「匹配前缀 + 语义」——
      那天给云端补默认工作流（`wf_from_plan or _video_wf_default(cloud=True)`）时，
      这条逐字匹配无谓地红了。逐字断言守不住语义，只会挡住正常改动。
    """
    src = (SCRIPTS / "drama.py").read_text(encoding="utf-8")
    assert "_run_batch(args, ep, url," in src, "本机出片没有显式传地址"
    assert "def _video_wf_default(" in src, "缺少「默认工作流按通道分」的入口"
    # 云端必须能落到 pika 那份，而本机保持 canvas —— 两条都要有人管
    assert "_video_wf_default(cloud=True)" in src, "云端分支没有指定云端默认工作流"
