"""tests/test_length_wiring.py —— 帧数必须是 INT 字面量，不能是连线

来源：4090 镜像实测（ComfyUI 0.43.2）。
工作流里 `length` 常接 `ComfyMathExpression`（秒数 × 24 吸附 17 倍数），它输出 FLOAT；
0.43.2 起提交前类型校验会以 `return_type_mismatch` 拒绝**整张图**。本地 0.42.1 会隐式转，
所以「本机能跑、上云 400」。

修法是 Python 侧算好写成字面量，靠 map 里的 `_length_node` 声明「哪个节点收帧数」。

★ 本文件还钉住一个更隐蔽的 bug（2026-11-05 抓到）：
  `load_map()` 原先把映射文件里的键按 `MAP_KEYS` 白名单过滤，
  而 `_length_node` / `_preview_node` 不在白名单里 —— 声明了也被静默丢弃，
  于是「按秒数算帧数」从未生效（改 `--seconds` 出片长度不变，且不报错）。
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import comfy_local_video as V        # noqa: E402


def test_length_node_survives_map_filter(tmp_path) -> None:
    """声明的 `_length_node` 必须能读回来 —— 这是本文件存在的首要理由。"""
    wf = tmp_path / "w.json"
    wf.write_text(json.dumps({"1": {"class_type": "MiniMaxH3ReferenceToVideo",
                                    "inputs": {"length": ["9", 1]}}}), encoding="utf-8")
    (tmp_path / "w.map.json").write_text(json.dumps({
        "prompt": "1", "_length_node": "1", "_preview_node": "1"}), encoding="utf-8")

    m, _src = V.load_map(str(wf), "")
    assert m["_length_node"] == "1"
    assert m["_preview_node"] == "1"


def test_rewire_still_passes_through(tmp_path) -> None:
    """透传白名单不能把原来的 `_rewire` / `_substitute` 弄丢。"""
    wf = tmp_path / "w.json"
    wf.write_text("{}", encoding="utf-8")
    (tmp_path / "w.map.json").write_text(json.dumps({
        "prompt": "30", "_rewire": {"5": {"inputs": {"a": ["7", 0]}}},
        "_substitute": {"UNETLoader": {"m.safetensors": "n.safetensors"}}}), encoding="utf-8")
    m, _ = V.load_map(str(wf), "")
    assert m["_rewire"]["5"]["inputs"]["a"] == ["7", 0]
    assert m["_substitute"]["UNETLoader"]["m.safetensors"] == "n.safetensors"


def test_apply_nodes_writes_int_literal(tmp_path) -> None:
    """连线被字面量覆盖，且类型是 int —— 0.43.2 只认这个。"""
    wf = {"35": {"class_type": "MiniMaxH3ReferenceToVideo",
                 "inputs": {"length": ["13", 1], "prompt": ["30", 0]}},
          "30": {"class_type": "PrimitiveString", "inputs": {"value": ""}},
          "10": {"class_type": "RandomNoise", "inputs": {"noise_seed": 1}},
          "4": {"class_type": "SaveVideo", "inputs": {"filename_prefix": "x"}}}
    m = {"prompt": "30", "seed": "10", "prefix": "4", "_length_node": "35"}

    out = V.apply_nodes(json.loads(json.dumps(wf)), m, prompt="hi", ref_names=["r.png"],
                        seconds=5, steps=None, seed=7, aspect="", mp=None, prefix="t")
    length = out["35"]["inputs"]["length"]
    assert length == V.frames_for(5) == 124
    assert isinstance(length, int) and not isinstance(length, bool)


def test_preview_frames_follow_length(tmp_path) -> None:
    """预览帧数必须跟成片同步，否则人按预览判断时长会被误导。"""
    wf = {"136": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {"length": 1008}},
          "150": {"class_type": "ModelPreviewOverrideKJ", "inputs": {"preview_frames": 48}},
          "30": {"class_type": "PrimitiveString", "inputs": {"value": ""}},
          "10": {"class_type": "RandomNoise", "inputs": {"noise_seed": 1}},
          "4": {"class_type": "SaveVideo", "inputs": {"filename_prefix": "x"}}}
    m = {"prompt": "30", "seed": "10", "prefix": "4",
         "_length_node": "136", "_preview_node": "150"}

    out = V.apply_nodes(json.loads(json.dumps(wf)), m, prompt="hi", ref_names=["r.png"],
                        seconds=10, steps=None, seed=7, aspect="", mp=None, prefix="t")
    assert out["136"]["inputs"]["length"] == 243
    assert out["150"]["inputs"]["preview_frames"] == 243


def test_check_warns_when_length_is_wired(tmp_path) -> None:
    """连线还在、map 又没声明 → 体检必须说出来（否则上云才发现 400）。"""
    wf = {"35": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {"length": ["13", 1]}}}
    lines = V.check_length_wiring(wf, {})
    assert lines and "0.43.2" in " ".join(lines) and "_length_node" in " ".join(lines)


def test_check_silent_when_declared() -> None:
    wf = {"35": {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": {"length": ["13", 1]}}}
    assert V.check_length_wiring(wf, {"_length_node": "35"}) == []


def test_repo_workflows_are_clean() -> None:
    """仓库自带的两份工作流都要能通过这道体检（否则说明 map 忘了声明）。"""
    for name in ("workflow_h3_local", "workflow_h3_minimax_canvas"):
        wf = V.load_workflow(name + ".json")
        m, _src = V.load_map(name + ".json", "")
        assert m.get("_length_node"), "%s.map.json 缺 _length_node" % name
        assert V.check_length_wiring(wf, m) == [], name
