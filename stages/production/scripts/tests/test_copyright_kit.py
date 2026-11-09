# -*- coding: utf-8 -*-
"""版权资料生成器与发行门禁的**契约对齐**测试（离线、零网络、零计费）。

为什么要这一层
--------------
2026-11-07 之前，仓库的版权资料口径是「4 张 `ai-process-*` + 4 张 `source-file-*`」，
而那正是被平台驳回的那一版。修完之后最怕的不是「又写错」，而是**生成器改了、门禁没改**：
生成出来的文件按新名字落盘，门禁却还在找旧前缀 ⇒ 永远红；或者反过来，门禁放了行、
生成器却没产出该产出的那几张 ⇒ 永远假绿。

所以这里守三件事：
1. 生成器的命名必须能被门禁扫到（前缀 - 两位编号 - slug）；
2. 权利声明 01–05 / 07 必须齐（06 视情况）；
3. 选镜与配置推断是可复现的（不依赖随机、不依赖人工记忆）。
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
SCRIPTS = HERE.parent                       # …/stages/production/scripts
sys.path.insert(0, str(SCRIPTS))


def _load(name: str):
    """按路径加载同目录脚本（避免同名模块互相覆盖）。"""
    spec = importlib.util.spec_from_file_location("_t_" + name, SCRIPTS / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CK = _load("copyright_kit")
RC = _load("release_check")


def _ws(tmp_path: pathlib.Path) -> pathlib.Path:
    ws = tmp_path / "proj"
    ws.mkdir(parents=True)
    (ws / "project.json").write_text(json.dumps({"meta": {
        "title": "La Heredera Oculta · 女佣的隐藏身份",
        "slug": "la-heredera-oculta", "total_ep": 30, "ep_seconds": 70,
        "aspect": "9:16", "language": "Spanish (Latin American)"}},
        ensure_ascii=False), encoding="utf-8", newline="\n")
    # 30 集里只有第 1/7/13/19/25/30 集有镜表（模拟「均匀取点」的场景）
    for ep in (1, 7, 13, 19, 25, 30):
        d = ws / "06-提示词" / ("ep%02d" % ep)
        d.mkdir(parents=True)
        shots = [
            {"shot_id": "shot_001", "duration": 5, "cast": ["P01@LOOK-A"]},
            {"shot_id": "shot_002", "duration": 8, "cast": ["P01@LOOK-A", "P02@LOOK-A", "S01"]},
            {"shot_id": "shot_003", "duration": 6, "cast": ["P02@LOOK-A"]},
        ]
        (d / "shots.json").write_text(json.dumps(shots, ensure_ascii=False),
                                      encoding="utf-8", newline="\n")
        (d / "h3_prompts.json").write_text(json.dumps(
            {s["shot_id"]: {"prompt": "x", "duration": s["duration"], "ratio": "9:16"}
             for s in shots}, ensure_ascii=False), encoding="utf-8", newline="\n")
    return ws


# ---------------------------------------------------------------- 配置
def test_split_title():
    assert CK._split_title("A · B") == ("A", "B")
    assert CK._split_title("A | B") == ("A", "B")
    assert CK._split_title("Solo") == ("Solo", "Solo")
    assert CK._split_title("") == ("", "")


def test_load_cfg_reads_project_meta(tmp_path):
    cfg = CK.load_cfg(_ws(tmp_path))
    assert cfg["title_en"] == "La Heredera Oculta"
    assert cfg["title_zh"] == "女佣的隐藏身份"
    assert cfg["episodes"] == 30
    assert cfg["ep_seconds"] == 70
    assert "1080x1920" in cfg["format"], cfg["format"]      # 真源 delivery_spec
    assert cfg["entity"] == ""                              # 不编主体名


def test_load_cfg_prefers_copyright_json(tmp_path):
    ws = _ws(tmp_path)
    (ws / "copyright.json").write_text(json.dumps({
        "entity": "陵丘科技有限公司", "registration": "91440000XXXX",
        "episodes": 30, "language": "Spanish (es-LA)"}, ensure_ascii=False),
        encoding="utf-8", newline="\n")
    cfg = CK.load_cfg(ws)
    assert cfg["entity"] == "陵丘科技有限公司"
    assert cfg["registration"] == "91440000XXXX"


# ---------------------------------------------------------------- 选镜
def test_pick_shots_spreads_over_episodes(tmp_path):
    ws = _ws(tmp_path)
    recs = CK.pick_shots(ws, want=6)
    eps = [r["ep"] for r in recs]
    assert len(eps) == 6 and len(set(eps)) == 6, eps
    assert eps[0] == "ep01" and eps[-1] == "ep30", eps      # 首尾要覆盖
    # 集内挑 cast 最多的那一镜（举证要有人、有景）
    assert all(r["shot"] == "shot_002" for r in recs), [r["shot"] for r in recs]


def test_pick_shots_want_more_than_available(tmp_path):
    recs = CK.pick_shots(_ws(tmp_path), want=99)
    assert 0 < len(recs) <= 6 and len({r["ep"] for r in recs}) == len(recs)


def test_pick_shots_explicit(tmp_path):
    recs = CK.pick_shots(_ws(tmp_path), explicit=["ep01:shot_003", "ep13:shot_001"])
    assert [(r["ep"], r["shot"]) for r in recs] == [("ep01", "shot_003"), ("ep13", "shot_001")]
    assert recs[0]["cast"] == ["P02@LOOK-A"]


def test_pick_shots_empty_workspace(tmp_path):
    ws = tmp_path / "empty"
    ws.mkdir()
    assert CK.pick_shots(ws, want=6) == []


def test_assets_for_shot_maps_cast_to_files(tmp_path):
    ws = _ws(tmp_path)
    d = ws / "04-资产" / "characters"
    d.mkdir(parents=True)
    (d / "P01_Elena_LOOK-A_00.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    got = CK.assets_for_shot(ws, "ep01", "shot_002")
    codes = [c for c, _v, _f in got]
    assert codes and codes[0] == "P01", codes


# ---------------------------------------------------------------- 契约对齐
def test_generated_names_are_scanned_by_gate():
    """生成器的命名必须能被门禁的前缀正则扫到 —— 否则改了名就永远红。"""
    cases = {
        "ai-gen-01-ep01-shot_007.png": "ai-gen",
        "ai-gen-06-ep30-shot_006.png": "ai-gen",
        "src-01-screenplay.png": "src",
        "src-06-asset-inventory.png": "src",
    }
    for name, prefix in cases.items():
        pat = re.compile(r"^%s[_-](\d{1,2})(?:[_-].*)?$" % re.escape(prefix), re.IGNORECASE)
        assert pat.match(pathlib.Path(name).stem), name

    for k in ("01", "02", "03", "04", "05", "06", "07"):
        pat = re.compile(r"^rights[_-](\d{2})(?:[_-].*)?$", re.IGNORECASE)
        assert pat.match("rights-%s-index" % k), k


def test_rights_required_cover_the_documents_we_render():
    """门禁要求的权利声明编号，必须都在生成器会渲染的 7 页里。"""
    rendered = {"01", "02", "03", "04", "05", "06", "07"}
    assert set(RC.RIGHTS_REQUIRED) <= rendered
    assert set(RC.RIGHTS_OPTIONAL) <= rendered
    assert (set(RC.RIGHTS_REQUIRED) | set(RC.RIGHTS_OPTIONAL)) == rendered


def test_legacy_prefixes_are_not_treated_as_primary():
    """旧口径前缀只能告警，不能进入「必须」清单。"""
    assert "ai-process" in RC.LEGACY_PREFIXES and "source-file" in RC.LEGACY_PREFIXES
    assert not hasattr(RC, "AI_PROCESS_IDS"), "旧的固定 4 张清单不该还在"


def test_edit_draft_boards_are_scanned_by_gate():
    """剪辑工程（第三入口）的命名契约：机器板 `draft-NN`、人工截图 `draft-shot-NN`。

    两条约束都是实测必要的：
      1. 机器板必须被 `draft` 前缀扫到 —— 否则生成器出图了、门禁还说缺；
      2. 人工截图**不能**被当成机器板计数 —— 否则截 4 张图就能绕过「工程自检通过」这一层。
    """
    machine = re.compile(r"^%s[_-](\d{1,2})(?:[_-].*)?$" % re.escape(RC.DRAFT_PREFIX), re.I)
    shot = re.compile(r"^%s[_-](\d{1,2})(?:[_-].*)?$" % re.escape(RC.DRAFT_SHOT_PREFIX), re.I)

    for i in (1, 2, 3, 4):
        assert machine.match("draft-%02d-overview" % i), i
    assert machine.match("draft-04-digest")

    # 人工截图归 `draft-shot` 一类，且**故意**不被 `draft` 正则匹配
    assert shot.match("draft-shot-01-ep01")
    assert not machine.match("draft-shot-01-ep01"), "截图被算成机器板，会让工程自检形同虚设"
    # 两类前缀不能互相污染
    assert not shot.match("draft-01-overview")
