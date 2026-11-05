#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_pack_import.py —— 制作包规范的校验与转换（离线，零网络零计费）

为什么这些用例值得写
--------------------
导入器是整条链上**唯一**把「创作侧的自由度」收敛成「引擎的确定性」的地方。
它漏放一条越界，代价不是报错，是：
  * duration 3 秒 → 提交到平台被拒 → 这一镜的钱白花（批次缺口，退出码 3）；
  * cast 引用了不存在的资产 → 出片时 `characters.json 里找不到 key` → 整集停在那；
  * style_lock 空着 → 出一批没有风格的图 → 全季作废，且**不会报错**。

所以下面每个 FAIL 用例，都对应一次真实会发生的钱或工期损失。
"""
from __future__ import annotations

import json
import pathlib
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import pack_spec as S  # noqa: E402

FIXTURE = HERE / "fixtures" / "mini_pack"


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _copy(tmp_path) -> pathlib.Path:
    dst = tmp_path / "pack"
    shutil.copytree(FIXTURE, dst)
    return dst


def _edit(p: pathlib.Path, fn) -> None:
    doc = json.loads(p.read_text(encoding="utf-8"))
    fn(doc)
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def _codes(rep) -> set:
    return {e["code"] for e in rep.errors}


# ---------------------------------------------------------------------------
# [A] 合法包
# ---------------------------------------------------------------------------
def test_valid_pack_loads():
    pack, assets, eps, rep = S.load_pack(FIXTURE)
    assert rep.ok, rep.render()
    assert pack["title"] == "最小测试剧"
    assert pack["delivery"]["episode_count"] == 1
    assert set(assets) == {"character", "scene", "prop"}
    assert len(assets["character"]) == 2
    assert len(assets["scene"]) == 1
    assert len(assets["prop"]) == 2
    assert list(eps) == [1]
    assert len(eps[1]["shots"]) == 3


def test_aspect_defaults_filled():
    pack, assets, _eps, rep = S.load_pack(FIXTURE)
    assert rep.ok, rep.render()
    # 变体没写 aspect → 落 kind 默认
    p01 = assets["character"]["P01"]
    # 人物/场景默认 9:16（与出片画幅一致；16:9 参考喂 9:16 输出会拉伸，见 pack_spec 注释）
    assert p01["variants"][0]["aspect"] == "9:16"
    assert assets["prop"]["D01"]["variants"][0]["aspect"] == "1:1"
    assert pack["aspect"]["video"] == "9:16"


def test_fx_is_post_only():
    _pack, assets, _eps, rep = S.load_pack(FIXTURE)
    assert rep.ok, rep.render()
    assert assets["prop"]["FX01"]["post_only"] is True
    assert assets["prop"]["D01"]["post_only"] is False


def test_shot_cast_normalised():
    _pack, _assets, eps, rep = S.load_pack(FIXTURE)
    assert rep.ok, rep.render()
    s1 = eps[1]["shots"][0]
    assert [c["key"] for c in s1["cast"]] == ["P01@LOOK-A", "P02@LOOK-A", "S01", "D01"]
    assert [c["kind"] for c in s1["cast"]] == ["character", "character", "scene", "prop"]


def test_default_variant_when_omitted():
    _pack, _assets, eps, rep = S.load_pack(FIXTURE)
    assert rep.ok, rep.render()
    s3 = eps[1]["shots"][2]
    # S01 只有一个变体「空景」，cast 没写 variant → 取第一个
    assert s3["cast"][0]["key"] in ("S01", "S01@空景")


# ---------------------------------------------------------------------------
# [B] 会被拦下的错误
# ---------------------------------------------------------------------------
def test_empty_style_lock_blocks(tmp_path):
    """风格锁为空必须阻断 —— 否则会出一整批没风格的图，且事后无法分辨。"""
    p = _copy(tmp_path)
    _edit(p / "pack.json", lambda d: d.update({"style_lock": ""}))
    pack, _a, _e, rep = S.load_pack(p)
    assert not rep.ok
    assert "STYLE001" in _codes(rep)


def test_duration_out_of_range_blocks(tmp_path):
    p = _copy(tmp_path)
    _edit(p / "episodes" / "ep01.json",
          lambda d: d["shots"][0].update({"duration": 3}))
    _pk, _a, eps, rep = S.load_pack(p)
    assert not rep.ok
    assert "SHOT005" in _codes(rep)
    assert len(eps[1]["shots"]) == 2          # 坏的那镜被剔除，其余照常


def test_duration_over_max_blocks(tmp_path):
    p = _copy(tmp_path)
    _edit(p / "episodes" / "ep01.json",
          lambda d: d["shots"][0].update({"duration": 16}))
    _pk, _a, _eps, rep = S.load_pack(p)
    assert not rep.ok
    assert "SHOT005" in _codes(rep)


def test_missing_cast_asset_blocks(tmp_path):
    p = _copy(tmp_path)
    _edit(p / "episodes" / "ep01.json",
          lambda d: d["shots"][0]["cast"].append({"asset": "P99"}))
    _pk, _a, _eps, rep = S.load_pack(p)
    assert not rep.ok
    assert "SHOT010" in _codes(rep)


def test_unknown_variant_blocks(tmp_path):
    p = _copy(tmp_path)
    _edit(p / "episodes" / "ep01.json",
          lambda d: d["shots"][0]["cast"][0].update({"variant": "LOOK-Z"}))
    _pk, _a, _eps, rep = S.load_pack(p)
    assert not rep.ok
    assert "SHOT011" in _codes(rep)


def test_id_prefix_kind_mismatch_blocks(tmp_path):
    """P01 写进 scenes.json 必须报错 —— 否则出图会落到 scenes/ 目录、参考表串表。"""
    p = _copy(tmp_path)
    _edit(p / "assets" / "scenes.json",
          lambda d: d["items"].append({"id": "P09", "name": "错位",
                                       "variants": [{"code": "base", "prompt": "x"}]}))
    _pk, _a, _eps, rep = S.load_pack(p)
    assert not rep.ok
    assert "ASSET009" in _codes(rep)


def test_bad_id_format_blocks(tmp_path):
    p = _copy(tmp_path)
    _edit(p / "assets" / "characters.json",
          lambda d: d["items"].append({"id": "何暖", "name": "何暖",
                                       "variants": [{"code": "base", "prompt": "x"}]}))
    _pk, _a, _eps, rep = S.load_pack(p)
    assert not rep.ok
    assert "ASSET008" in _codes(rep)


def test_duplicate_variant_code_blocks(tmp_path):
    p = _copy(tmp_path)
    _edit(p / "assets" / "characters.json",
          lambda d: d["items"][0]["variants"].append(
              {"code": "LOOK-A", "prompt": "重复代号"}))
    _pk, _a, _eps, rep = S.load_pack(p)
    assert not rep.ok
    assert "ASSET014" in _codes(rep)


def test_empty_prompt_blocks(tmp_path):
    p = _copy(tmp_path)
    _edit(p / "assets" / "characters.json",
          lambda d: d["items"][0]["variants"][0].update({"prompt": "  "}))
    _pk, _a, _eps, rep = S.load_pack(p)
    assert not rep.ok
    assert "ASSET015" in _codes(rep)


def test_mixed_number_overflow_blocks(tmp_path):
    """video_prompt 引用了第 7 张参考图，但 cast 只有 4 项 —— 平台会串图。"""
    p = _copy(tmp_path)
    _edit(p / "episodes" / "ep01.json",
          lambda d: d["shots"][0].update(
              {"video_prompt": "参考图是 {{Mixed 7}}，请照做。"}))
    _pk, _a, _eps, rep = S.load_pack(p)
    assert not rep.ok
    assert "SHOT016" in _codes(rep)


def test_missing_video_prompt_blocks(tmp_path):
    p = _copy(tmp_path)
    _edit(p / "episodes" / "ep01.json",
          lambda d: d["shots"][0].pop("video_prompt"))
    _pk, _a, _eps, rep = S.load_pack(p)
    assert not rep.ok
    assert "SHOT015" in _codes(rep)


def test_wrong_spec_blocks(tmp_path):
    p = _copy(tmp_path)
    _edit(p / "pack.json", lambda d: d.update({"spec": "solodrama-pack/2"}))
    _pk, _a, _eps, rep = S.load_pack(p)
    assert not rep.ok
    assert "PACK003" in _codes(rep)


def test_episode_file_name_mismatch_blocks(tmp_path):
    p = _copy(tmp_path)
    _edit(p / "episodes" / "ep01.json", lambda d: d.update({"episode": 2}))
    _pk, _a, _eps, rep = S.load_pack(p)
    assert not rep.ok
    assert "EP007" in _codes(rep)


# ---------------------------------------------------------------------------
# [C] 只告警、不阻断
# ---------------------------------------------------------------------------
def test_missing_board_prompt_warns(tmp_path):
    p = _copy(tmp_path)
    _edit(p / "episodes" / "ep01.json",
          lambda d: d["shots"][0].pop("board_prompt"))
    _pk, _a, eps, rep = S.load_pack(p)
    assert rep.ok, rep.render()
    assert "SHOT014" in {w["code"] for w in rep.warnings}
    assert len(eps[1]["shots"]) == 3


def test_episode_count_mismatch_warns(tmp_path):
    p = _copy(tmp_path)
    _edit(p / "pack.json", lambda d: d["delivery"].update({"episode_count": 3}))
    _pk, _a, _eps, rep = S.load_pack(p)
    assert rep.ok
    assert "EP009" in {w["code"] for w in rep.warnings}


def test_dialogue_outside_cast_ignored(tmp_path):
    p = _copy(tmp_path)

    def _add(d):
        d["shots"][1]["dialogue"] = [{"asset": "P02", "text": "不在本镜",
                                      "start": 0, "end": 1}]

    _edit(p / "episodes" / "ep01.json", _add)
    _pk, _a, eps, rep = S.load_pack(p)
    assert rep.ok
    assert eps[1]["shots"][1]["dialogue"] == []


# ---------------------------------------------------------------------------
# [D] 转换结果
# ---------------------------------------------------------------------------
def test_build_files_shape():
    import pack_import as PI
    pack, assets, eps, rep = S.load_pack(FIXTURE)
    assert rep.ok, rep.render()
    files = PI.build_episode_files(pack, assets, eps[1], {}, {})
    assert set(files) == {"shots.json", "boards.json", "h3_prompts.json",
                          "characters.json", "scenes.json"}
    shots = files["shots.json"]
    assert len(shots) == 3
    assert shots[0] == {
        "shot_id": "shot_001",
        "ratio": "9:16",
        "crop": {"rows": 1, "cols": 1},
        "board_ref": "board_ep01_shot_001",
        # cast 是**完整有序**的参考图列表（2026-11-04 新增）：本地通道按它顺序提交，
        # 与提示词里的 {{Mixed n}} 逐位对应。分表（character_refs / scene_refs）保留给引擎兼容。
        "cast": ["P01@LOOK-A", "P02@LOOK-A", "S01", "D01"],
        "character_refs": ["P01@LOOK-A", "P02@LOOK-A", "D01"],
        "scene_refs": ["S01"],
    }
    assert files["boards.json"]["shot_001"]["prompt"].startswith("办公室。")
    assert files["h3_prompts.json"]["shot_001"]["duration"] == 12
    # FX 归入 character_refs（引擎只认两张表）
    assert "FX01" in shots[2]["character_refs"] or "FX01@base" in shots[2]["character_refs"]


def test_char_table_filtered_by_episode():
    """本集没用到的资产不进本集参考表 —— 表越小越好查。"""
    import pack_import as PI
    pack, assets, eps, _rep = S.load_pack(FIXTURE)
    chars = {"P01@LOOK-A": "a.png", "P01@LOOK-B": "b.png", "P99@base": "z.png"}
    scenes = {"S01@空景": "s.png", "S09@空景": "z.png"}
    files = PI.build_episode_files(pack, assets, eps[1], chars, scenes)
    assert "P99@base" not in files["characters.json"]
    assert "S09@空景" not in files["scenes.json"]


# ---------------------------------------------------------------------------
# [E] 纯函数
# ---------------------------------------------------------------------------
def test_ep_index_of():
    assert S.ep_index_of("ep01") == 1
    assert S.ep_index_of("ep01.json") == 1
    assert S.ep_index_of("1") == 1
    assert S.ep_index_of("第12集") == 12
    assert S.ep_index_of("ep100") == 100
    assert S.ep_index_of("乱写") is None


def test_ep_key():
    assert S.ep_key(1) == "ep01"
    assert S.ep_key(12) == "ep12"
    assert S.ep_key(100) == "ep100"


def test_variant_key():
    assert S.variant_key("P01", "") == "P01"
    assert S.variant_key("P01", "base") == "P01"
    assert S.variant_key("S01", "空景") == "S01"
    assert S.variant_key("P01", "LOOK-A") == "P01@LOOK-A"


def test_kind_of():
    assert S.kind_of("P01") == "character"
    assert S.kind_of("S12") == "scene"
    assert S.kind_of("D03") == "prop"
    assert S.kind_of("FX01") == "prop"
    assert S.kind_of("X01") is None
    assert S.kind_of("p01") is None


# ---------------------------------------------------------------------------
# [F] 真实样例：总裁甜宠 Skill → 制作包
# ---------------------------------------------------------------------------
def test_tianchong_demo_pack():
    """`fixtures/tianchong_demo/` 是「总裁甜宠」导演手册经转换提示词转出来的包。

    它存在的意义不是覆盖解析逻辑，而是**给规范钉一个活样本**：
    以后改 `pack_spec.py` 的校验规则时，如果这个包导不进来，说明规则与文档已经分叉。
    """
    demo = HERE / "fixtures" / "tianchong_demo" / "pack"
    pack, assets, eps, rep = S.load_pack(demo)
    assert rep.ok, rep.render()
    assert pack["skill"]["name"] == "tianchong-manju"
    assert pack["style_lock"].startswith("美式复古影视风格")
    assert set(assets) == {"character", "scene", "prop"}
    s1 = eps[1]["shots"][0]
    # cast 顺序 = 参考图上传顺序 = video_prompt 里 Mixed 2..5 的顺序
    assert [c["key"] for c in s1["cast"]] == ["P01@LOOK-A", "P02@LOOK-A", "S01", "D01"]
    assert s1["duration"] == 6
    assert "{{Mixed 5}}" in s1["video_prompt"]
    assert s1["board_prompt"].startswith("参考：STYLE01")
    # 台词只保留能定位到本镜 cast 的条目
    assert [d["text"] for d in s1["dialogue"]] == ["一年，互不干涉。", "三个月。"]


# ---------------------------------------------------------------------------
# [F] 真实样例：总裁甜宠 Skill → 制作包
# ---------------------------------------------------------------------------
def test_tianchong_demo_pack():
    """`fixtures/tianchong_demo/` 是「总裁甜宠」导演手册经转换提示词转出来的包。

    它存在的意义不是覆盖解析逻辑，而是**给规范钉一个活样本**：
    以后改 `pack_spec.py` 的校验规则时，如果这个包导不进来，说明规则与文档已经分叉。
    """
    demo = HERE / "fixtures" / "tianchong_demo" / "pack"
    pack, assets, eps, rep = S.load_pack(demo)
    assert rep.ok, rep.render()
    assert pack["skill"]["name"] == "tianchong-manju"
    assert pack["style_lock"].startswith("美式复古影视风格")
    assert set(assets) == {"character", "scene", "prop"}
    s1 = eps[1]["shots"][0]
    # cast 顺序 = 参考图上传顺序 = video_prompt 里 Mixed 2..5 的顺序
    assert [c["key"] for c in s1["cast"]] == ["P01@LOOK-A", "P02@LOOK-A", "S01", "D01"]
    assert s1["duration"] == 6
    assert "{{Mixed 5}}" in s1["video_prompt"]
    assert s1["board_prompt"].startswith("参考：STYLE01")
    # 台词只保留能定位到本镜 cast 的条目
    assert [d["text"] for d in s1["dialogue"]] == ["一年，互不干涉。", "三个月。"]
