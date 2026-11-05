#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_cloud_wiring.py —— WebUI 侧「云端通道」必须真的能跑，不能只显示

守什么
------
引擎侧早已支持 `--engine cloud`（出图 / 出片），但 WebUI 曾经只把云端**显示**出来：
  · 生成通道页把云端行的「命令」写成 assets.local / video.local（点进去跑的是本机）；
  · 流水线的资产环节写死 assets.local（云端项目一跑就被门禁拦，界面却说「已就绪」）；
  · 画布节点的运行按钮同理。

这类不一致的杀伤力在于「看起来有」：用户不会去翻命令行，只会觉得按钮坏了。
所以这里用**结构断言**钉住四件事：命令存在且指向 cloud、流水线会换命令、
画布会换命令、前端确实给了云端入口。
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB))

from core import commands as CMD  # noqa: E402
from core import generators as GEN  # noqa: E402
from core import graph, pipeline  # noqa: E402

JS = WEB / "ui" / "studio" / "js" / "views"


# ---------------------------------------------------------------------------
# 命令层
# ---------------------------------------------------------------------------
def test_cloud_commands_exist():
    """出图 / 出片各有云端命令，且 argv 真的是 --engine cloud。

    只「存在」不够：曾经 video.cloud 这类命令根本不存在，界面就把人导去本地命令。
    """
    a = CMD.get("assets.cloud")
    v = CMD.get("video.cloud")
    assert a is not None and "--engine" in a.argv and "cloud" in a.argv, a
    assert v is not None and "--engine" in v.argv and "cloud" in v.argv, v
    # 计费语义：云端是 PAID（按主机时长），不能被标成 ￥0
    assert a.billing == "paid" and v.billing == "paid"


def test_video_cloud_forwards_lifecycle_and_url():
    """云端出片必须能把「地址 / 启停档 / 实例名」传下去。

    少了其中任何一个，界面就只剩「跑云端」这个笼统动作：
    既不能指定实例，也不能选择跑完是否保留（那是明确的成本差异）。
    """
    v = CMD.get("video.cloud")
    keys = {p.key for p in v.params}
    assert {"comfy_url", "cloud_lifecycle", "cloud_name", "ep"} <= keys, keys
    lc = [p for p in v.params if p.key == "cloud_lifecycle"][0]
    assert lc.default == "auto" and set(lc.choices) == {"auto", "keep", "off"}


def test_preflight_gen_command_targets_only_gen():
    """预检入口必须只跑「生成通道」那一段，不能把整条体检也带上（会多跑几十秒）。"""
    c = CMD.get("preflight.gen")
    assert c is not None
    assert c.argv == ["preflight", "--only", "gen"], c.argv
    assert c.billing == "free" and c.mode == "sync"


def test_cloud_asset_command_keeps_asset_md_env():
    """云端出图仍然要把资产 md 灌进 SOLODRAMA_ASSET_MD（引擎只认环境变量）。"""
    a = CMD.get("assets.cloud")
    assert a.env_for({"asset_md": "x.md"}) == {"SOLODRAMA_ASSET_MD": "x.md"}


# ---------------------------------------------------------------------------
# 流水线 / 画布：按模型确认单换命令
# ---------------------------------------------------------------------------
def _fake_stages():
    return {"ok": True, "current": "asset", "complete": False,
            "stages": [{"id": "asset", "name": "资产", "state": "todo",
                        "probes": [{"label": "资产提示词", "ok": True, "found": 1, "need": 1}]}]}


def test_pipeline_uses_cloud_asset_when_confirmed(monkeypatch):
    monkeypatch.setattr(pipeline.adapters, "workflow_status", lambda ws: copy.deepcopy(_fake_stages()))
    monkeypatch.setattr(pipeline.adapters, "norm_workflow", lambda raw: raw)
    monkeypatch.setattr(pipeline, "_values_for", lambda sid, ws: {"asset_md": "x.md"})
    monkeypatch.setattr(GEN, "plan_choice", lambda ws, kind: "cloud_comfyui")

    d = pipeline.plan("X:/ws", budget=0)
    st = [x for x in d["stages"] if x["id"] == "asset"][0]
    assert st["cmd"] == "assets.cloud", st
    assert st["billing"] == "paid", "云端出图不能标成 ￥0：%s" % st["billing"]
    assert "云端" in st["action_text"], st["action_text"]


def test_pipeline_keeps_local_when_local_confirmed(monkeypatch):
    """确认的是本地时不许被「换」成云端 —— 反方向同样要守。"""
    monkeypatch.setattr(pipeline.adapters, "workflow_status", lambda ws: copy.deepcopy(_fake_stages()))
    monkeypatch.setattr(pipeline.adapters, "norm_workflow", lambda raw: raw)
    monkeypatch.setattr(pipeline, "_values_for", lambda sid, ws: {"asset_md": "x.md"})
    monkeypatch.setattr(GEN, "plan_choice", lambda ws, kind: "local_comfyui")

    d = pipeline.plan("X:/ws", budget=0)
    st = [x for x in d["stages"] if x["id"] == "asset"][0]
    assert st["cmd"] == "assets.local", st
    assert st["billing"] == "gpu"


def test_graph_swaps_node_command(monkeypatch):
    monkeypatch.setattr(GEN, "plan_choice", lambda ws, kind: "cloud_comfyui")
    assert graph._cmd_for("X:/ws", "asset.render") == "assets.cloud"
    assert graph._cmd_for("X:/ws", "video.batch") == "video.cloud"
    monkeypatch.setattr(GEN, "plan_choice", lambda ws, kind: "local_comfyui")
    assert graph._cmd_for("X:/ws", "asset.render") == "assets.local"
    assert graph._cmd_for("X:/ws", "video.batch") == "video.run"


def test_plan_choice_reads_model_plan(tmp_path):
    """确认单是唯一真源：没这一条，上面三个换命令的逻辑就成了猜。"""
    import json
    (tmp_path / "model-plan.json").write_text(json.dumps({
        "gate_version": 2,
        "models": {"image": {"choice": "cloud_comfyui"},
                   "video": {"choice": "local_comfyui"}}}, ensure_ascii=False), encoding="utf-8")
    assert GEN.plan_choice(str(tmp_path), "image") == "cloud_comfyui"
    assert GEN.cloud_selected(str(tmp_path), "image") is True
    assert GEN.cloud_selected(str(tmp_path), "video") is False
    assert GEN.plan_choice(str(tmp_path / "nope"), "image") == ""


# ---------------------------------------------------------------------------
# 前端：确实给了入口（结构断言，防止「后端加了、按钮没加」）
# ---------------------------------------------------------------------------
def test_assets_view_offers_cloud_engine():
    src = (JS / "assets.js").read_text(encoding="utf-8")
    assert 'value="cloud"' in src, "出图抽屉里没有云端镜像这一项"
    assert "assets.cloud" in src, "云端镜像没有对应的命令 id"
    # 不能写「必须跑在 8188」这类断言 —— 地址是可配的，上云之后就是错的。
    # （提「默认 127.0.0.1:8188」是允许的：那是事实，且旁边写明「地址取连接中心」。）
    for wrong in ("需要在 8188 端口运行", "需 8188 在线", "确认 8188 在线"):
        assert wrong not in src, "前端仍把 8188 当成硬前提：%s" % wrong


def test_generators_view_shows_endpoint():
    src = (JS / "generators.js").read_text(encoding="utf-8")
    assert "it.endpoint" in src, "通道页没把实际地址摊开 —— 「核 A 跑 B」就查不出来了"


def test_generators_cloud_rows_point_to_cloud_commands():
    """通道页的「命令」列必须指向云端命令，而不是本地命令。"""
    src = (WEB / "core" / "generators.py").read_text(encoding="utf-8")
    assert '"assets.cloud"' in src and '"video.cloud"' in src
