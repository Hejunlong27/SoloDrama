# -*- coding: utf-8 -*-
"""`gen_boards.py` 离线测试 —— 零网络、零出图。

它守的是**分镜图提示词的装配逻辑**，其中一条是历史事故的直接产物：

    2026-11-01 EP03/EP04 有 5 个镜写死 `exactly one person`，
    而 `[SHOT]` 同一句里又写 `Two bodies` —— 出片当然乱，但没有任何一步报错。

所以这里最硬的一条是 **B 组：人数必须从 `refs` 实算，任何写死都算失败**。

覆盖：
* **A 人数**：0/1/2/3 人 / 场景-only / 未知代号
* **B 禁令**：模板里不得出现写死的人数句式
* **C 结构**：构图锚定位 / 禁止项 / ratio 透传 / 风格串取自 look
* **D 契约**：读分镜 md 的 `board:` / 缺 board 的镜跳过 / 不读 boards.json 也能跑

```bash
python tests/test_gen_boards.py
```
"""
import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
FIXTURE = pathlib.Path(HERE) / "fixtures" / "mini_drama"

_TMP = pathlib.Path(tempfile.mkdtemp(prefix="sd_gb_"))
_WS = _TMP / "mini_drama"
shutil.copytree(FIXTURE, _WS)
os.environ["SOLODRAMA_WORKSPACE"] = str(_WS)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, str(pathlib.Path(SCRIPTS).parents[1]))

import gen_boards as G                                          # noqa: E402

CASES = []


def reg(group, name):
    def deco(fn):
        CASES.append((group, name, fn))
        return fn
    return deco


def A_(cond, msg=""):
    if not cond:
        raise AssertionError(msg or "断言失败")


BIBLE = {"characters": [
    {"code": "AVA", "name": "Ava", "age": 30, "gender": "f",
     "garment_en": "grey cotton top with dark trousers"},
    {"code": "BEN", "name": "Ben", "age": 34, "gender": "m",
     "garment_en": "olive work jacket with dark trousers"},
    {"code": "CAT", "name": "Cat", "age": 27, "gender": "f",
     "garment_en": "navy shirt with pale trousers"},
]}


def spec(refs, prompt="Medium shot inside a room, eye level."):
    return {"prompt": prompt, "ratio": "9:16", "refs": refs}


# =========================================================================== A 人数
@reg("A", "A01 人数从 refs 实算：1 人 / 2 人 / 3 人各对各的")
def _():
    for refs, want, n in (
        (["char_ava"], "exactly one person", 1),
        (["char_ava", "char_ben"], "exactly two people", 2),
        (["char_ava", "char_ben", "char_cat"], "exactly three people", 3),
    ):
        txt, got_n, codes = G.build_prompt("shot_001", spec(refs + ["scene_room"]),
                                           BIBLE, "plain look")
        A_(want in txt, "%d 人时应写「%s」，实际没写：%s" % (n, want, txt[:200]))
        A_(got_n == n, "解析出 %d 人，应为 %d" % (got_n, n))
        A_(len(codes) == n, "代号列表长度不对：%s" % codes)
    return "1/2/3 人分别正确"


@reg("A", "A02 只有场景没有角色 → no people in frame，不编人")
def _():
    txt, n, codes = G.build_prompt("shot_001", spec(["scene_room"]), BIBLE, "plain look")
    A_(n == 0, "纯场景镜人数应为 0，实际 %s" % n)
    A_("no people in frame" in txt,
        "纯场景镜的措辞不明显：%s" % txt[:200])
    A_("exactly one person" not in txt, "纯场景镜不能写成一人")
    A_(not codes, "不该编出角色代号：%s" % codes)
    return "场景镜不编人"


@reg("A", "A03 未登记的代号：不脑补长相，但明确说「靠角色卡」")
def _():
    txt, n, codes = G.build_prompt("shot_001", spec(["char_zzz"]), BIBLE, "plain look")
    A_("ZZZ" in txt, "代号要出现（模型需要知道画面里有几个人）")
    A_("character card" in txt, "要说明身份由角色卡保证")
    return "不脑补"


@reg("A", "A04 代号归一：char_ava / AVA / Character_Ava 都算 AVA")
def _():
    for raw in ("char_ava", "AVA", "Character_Ava", "ch_ava"):
        _, _, codes = G.build_prompt("s", spec([raw]), BIBLE, "")
        A_(codes == ["AVA"], "%s 没归成 AVA：%s" % (raw, codes))
    A_(G._codes(["P01@LOOK-A"], ["P01", "P02"]) == ["P01"],
       "P01@LOOK-A 应归一为 P01")
    return "4 种写法归一"


@reg("A", "A05 没有 character-bible 时，裸代号 P01 也算角色（否则双人镜写死 1 人）")
def _():
    # 2026-11-06 实测：横屏项目没建 04-资产/design/character-bible.json，
    # known 为空 → 裸代号不算角色 → 人数算成 0 兜底成 1 → 双人镜写成 exactly one person。
    txt, n, codes = G.build_prompt("s", spec(["P01", "P02", "S01"]), {}, "")
    assert n == 2, "裸代号应算出 2 个人，实际 %d（codes=%s）" % (n, codes)
    assert "exactly two people" in txt, txt[:300]
    assert codes == ["P01", "P02"], codes


# =========================================================================== B 禁令
@reg("B", "B01 模板里没有写死人数的句式（历史事故的直接防线）")
def _():
    # 至少两个人数的样本，模板都不该出现「exactly one person」
    txt2, _, _ = G.build_prompt("s", spec(["char_ava", "char_ben"]), BIBLE, "")
    A_("exactly one person" not in txt2,
        "两人镜里出现了 exactly one person —— 这正是 EP03/EP04 的翻车句式")
    txt3, _, _ = G.build_prompt("s", spec(["char_ava", "char_ben", "char_cat"]), BIBLE, "")
    A_("exactly one person" not in txt3, "三人镜里出现了 exactly one person")
    return "两人/三人镜均无写死句"


@reg("B", "B02 禁止项覆盖「拼版 / 分格 / 文字」")
def _():
    txt, _, _ = G.build_prompt("s", spec(["char_ava"]), BIBLE, "")
    for k in ("no split screen", "no collage", "no grid", "no text", "no panels"):
        A_(k in txt, "禁止项缺「%s」" % k)
    return "5 项禁止齐"


@reg("B", "B03 人数句里有 nobody else，防模型自己加人")
def _():
    txt, _, _ = G.build_prompt("s", spec(["char_ava", "char_ben"]), BIBLE, "")
    A_("nobody else" in txt, "缺「nobody else」——模型会往画面里塞路人")
    return "有 nobody else"


# =========================================================================== C 结构
@reg("C", "C01 明确定位为「构图锚」，且强调不是分镜表")
def _():
    txt, _, _ = G.build_prompt("s", spec(["char_ava"]), BIBLE, "")
    A_("构图参考" in txt, "没说明用途是构图参考")
    A_("不是分镜表" in txt or "不是线稿" in txt,
        "没排除分镜表/线稿语义 —— 那会把线稿画进成片")
    return "定位清晰"


@reg("C", "C02 人物段说明「身份靠角色卡保证」，不抢身份锚")
def _():
    txt, _, _ = G.build_prompt("s", spec(["char_ava", "char_ben"]), BIBLE, "")
    A_("character reference cards" in txt or "character card" in txt,
        "没说明身份由角色卡保证")
    A_("plausible" in txt, "没说明「脸像不像无所谓」")
    return "不抢身份"


@reg("C", "C03 风格串透传；为空时给默认摄影风格")
def _():
    txt, _, _ = G.build_prompt("s", spec(["char_ava"]), BIBLE, "surreal live-action film look")
    A_("surreal live-action film look" in txt, "风格串没透传")
    txt2, _, _ = G.build_prompt("s", spec(["char_ava"]), BIBLE, "")
    A_("cinematic live-action photography" in txt2, "空风格时没给默认值")
    return "透传 + 兜底"


@reg("C", "C04 光位从 H3 提示词的 [LIGHT] 段透传，没有就不编")
def _():
    h3 = "[SHOT] medium.\n[LIGHT] one warm lamp at the far end, cold rim from the glass."
    txt, _, _ = G.build_prompt("s", spec(["char_ava"]), BIBLE, "", h3_prompt=h3)
    A_("one warm lamp" in txt, "光位没透传：%s" % txt[-300:])
    txt2, _, _ = G.build_prompt("s", spec(["char_ava"]), BIBLE, "", h3_prompt="[SHOT] only.")
    A_("one clear key source" in txt2, "没光位时该给通用描述，不该编具体灯具")
    return "透传 / 兜底"


@reg("C", "C05 画幅跟 spec.ratio 走：竖屏写 vertical、横屏写 horizontal")
def _():
    # 2026-11-06：模板里曾写死 `vertical 9:16`，横屏项目（16:9）的分镜图仍是竖构图，
    # 出片时构图被裁 —— 而且不报错。现在画幅由 ratio 参数/ spec 决定，两个方向都要能表达。
    for r, cn, en in (("9:16", "竖版", "vertical"), ("16:9", "横版", "horizontal"),
                      ("3:4", "竖版", "vertical")):
        s = spec(["char_ava"])
        s["ratio"] = r
        txt, _, _ = G.build_prompt("s", s, BIBLE, "")
        assert "%s %s" % (cn, r) in txt, "ratio=%s 时任务行没写成「%s %s」：%s" % (r, cn, r, txt[:120])
        assert "single frame, %s %s" % (en, r) in txt, "ratio=%s 时英文画幅串不对" % r
        assert "single frame" in txt, "ratio=%s 时结构不完整" % r
    # 显式参数优先于 spec
    txt, _, _ = G.build_prompt("s", spec(["char_ava"]), BIBLE, "", ratio="16:9")
    assert "横版 16:9" in txt, "显式 ratio 应覆盖 spec：%s" % txt[:120]
    return "3 种 ratio + 参数覆盖"


# =========================================================================== D 契约
@reg("D", "D01 直接读分镜 md 的 board 字段（不依赖 boards.json）")
def _():
    specs = G._specs_from_md(_WS, "ep01")
    A_(len(specs) == 2, "应解析出 2 镜，实际 %d" % len(specs))
    for sid, v in specs.items():
        A_(len(v["prompt"]) > 40, "%s 的 board 过短" % sid)
        A_(v["ratio"] == "9:16", "%s 的 ratio 不对" % sid)
        A_(v["refs"], "%s 的 refs 为空" % sid)
        A_("[SHOT]" not in v["prompt"], "%s 的 board 混进了 [SHOT]" % sid)
    return "2 镜 / 字段齐"


@reg("D", "D02 没有 boards.json 也能跑（环节之间不反向依赖）")
def _():
    d = _WS / "06-提示词" / "ep01"
    had = (d / "boards.json").is_file()
    bak = None
    if had:
        bak = (d / "boards.json").read_bytes()
        (d / "boards.json").unlink()
    try:
        specs = G._specs_from_md(_WS, "ep01")
        A_(len(specs) == 2, "缺 boards.json 时读 md 应仍然拿到 2 镜")
    finally:
        if bak is not None:
            (d / "boards.json").write_bytes(bak)
    return "md 直读可独立工作"


@reg("D", "D03 缺 board 的镜被跳过，不猜")
def _():
    text = (_WS / "05-分镜" / "ep01_storyboard.md").read_text(encoding="utf-8")
    i = text.index("- board: |")
    j = text.index("- prompt: |", i)
    tmp = _TMP / "noboard"
    tmp.mkdir(exist_ok=True)
    (tmp / "layout.json").write_text((_WS / "layout.json").read_text(encoding="utf-8"),
                                     encoding="utf-8")
    (tmp / "05-分镜").mkdir(exist_ok=True)
    (tmp / "05-分镜" / "ep01_storyboard.md").write_text(text[:i] + text[j:], encoding="utf-8")
    specs = G._specs_from_md(tmp, "ep01")
    # 删的是 shot_001 的 board；shot_002 的还在，所以结果是 1 条 —— 关键是**缺的那镜不出现**
    A_("shot_001" not in specs, "缺 board 的镜不该出现：%s" % list(specs))
    A_(len(specs) == 1, "应只剩 shot_002，实际 %s" % list(specs))
    return "缺的那镜被跳过"


@reg("D", "D04 人数表：1–5 人都有英文句式，不会落到兜底")
def _():
    for n in range(1, 6):
        A_(n in G.NUM_EN, "%d 人没有句式" % n)
        A_(G.NUM_EN[n].startswith("exactly "), "%d 人的句式不以 exactly 开头" % n)
    return "1–5 人全覆盖"


# =========================================================================== E 通道选择
def _write_board_plan(ws, choice=None, detail=None):
    ws.mkdir(parents=True, exist_ok=True)
    models = {}
    if choice:
        models["board"] = {"choice": choice, "confirmed": True,
                           "detail": detail or {}}
    (ws / "model-plan.json").write_text(
        json.dumps({"gate_version": 2, "models": models}, ensure_ascii=False),
        encoding="utf-8")


@reg("E", "E01 无 board 确认时 auto 回落本地，不破坏老项目")
def _():
    ws = _TMP / "board_auto_empty"
    ws.mkdir(exist_ok=True)
    engine, note = G._resolve_engine(ws, "auto")
    A_(engine == "local", "无确认应回 local，实际 %r" % engine)
    A_("未确认" in note, "应说明回落原因：%s" % note)
    return "auto → local"


@reg("E", "E02 board=zzai_image_api 能解析到 ZZAI 执行器")
def _():
    ws = _TMP / "board_auto_zzai"
    _write_board_plan(ws, "zzai_image_api")
    engine, note = G._resolve_engine(ws, "auto")
    A_(engine == "zzai", "应解析为 zzai，实际 %r" % engine)
    A_("已确认" in note, "门禁应放行：%s" % note)
    return "board → zzai"


@reg("E", "E03 board=cloud_comfyui 缺地址时被门禁拦下")
def _():
    ws = _TMP / "board_auto_cloud_missing"
    _write_board_plan(ws, "cloud_comfyui", {})
    engine, note = G._resolve_engine(ws, "auto")
    A_(engine == "", "缺地址不应解析出执行器")
    A_("comfy_url" in note, "错误应点名 comfy_url：%s" % note)
    return "缺 comfy_url → block"


@reg("E", "E04 board=cloud_comfyui 有地址时解析到 cloud")
def _():
    ws = _TMP / "board_auto_cloud"
    _write_board_plan(ws, "cloud_comfyui",
                      {"comfy_url": "https://abc-8188.container.x-gpu.com"})
    engine, _ = G._resolve_engine(ws, "auto")
    A_(engine == "cloud", "应解析为 cloud，实际 %r" % engine)
    return "board → cloud"


@reg("E", "E05 未实现/人工通道不静默回落本地")
def _():
    ws = _TMP / "board_auto_manual"
    _write_board_plan(ws, "closed_source")
    engine, note = G._resolve_engine(ws, "auto")
    A_(engine == "", "closed_source 不应回落到 local")
    A_("没有内置执行器" in note, "应明确说明没有执行器：%s" % note)
    return "manual → block"


@reg("E", "E06 board=RunningHub 工作流时解析到 rh")
def _():
    ws = _TMP / "board_auto_rh"
    _write_board_plan(ws, "runninghub_workflow",
                      {"workflow_id_i2i": "rh-i2i-id", "workflow_id_t2i": "rh-t2i-id"})
    engine, note = G._resolve_engine(ws, "auto")
    A_(engine == "rh", "应解析为 rh，实际 %r" % engine)
    A_("已确认" in note, "门禁应放行：%s" % note)
    A_(G._rh_workflow_preset(ws, "i2i") == "rh-i2i-id", "i2i workflowId 读取错误")
    return "board → RH i2i"


@reg("E", "E07 ComfyUI 预设区分 t2i / i2i，board 读取 i2i")
def _():
    ws = _TMP / "board_comfy_presets"
    _write_board_plan(ws, "local_comfyui", {
        "comfy_workflow_t2i": "D:/wf/t2i.json",
        "comfy_workflow_i2i": "D:/wf/i2i.json",
    })
    A_(G._workflow_preset(ws, "t2i") == "D:/wf/t2i.json", "t2i 预设读错")
    A_(G._workflow_preset(ws, "i2i") == "D:/wf/i2i.json", "i2i 预设读错")
    return "t2i / i2i 分离"


@reg("E", "E08 RunningHub i2i 节点映射包含 prompt / image / aspect")
def _():
    detail = {"runninghub_nodes_i2i": {
        "prompt": {"nodeId": "6", "fieldName": "text"},
        "images": [{"nodeId": "12", "fieldName": "image"},
                   {"nodeId": "13", "fieldName": "image"}],
        "aspect": {"nodeId": "20", "fieldName": "aspect_ratio"},
    }}
    pairs, err = G._rh_pairs(detail, "board prompt", "9:16", ["a.png", "b.png"])
    A_(not err, "节点映射不应报错：%s" % err)
    A_(pairs[0] == ("6", "text", "board prompt"), "prompt 节点映射错误：%s" % (pairs,))
    A_(("12", "image", "a.png") in pairs and ("13", "image", "b.png") in pairs,
       "参考图节点映射错误：%s" % (pairs,))
    A_(pairs[-1] == ("20", "aspect_ratio", "9:16"), "aspect 节点映射错误：%s" % (pairs,))
    return "prompt + 2 refs + aspect"


# =========================================================================== F ZZAI Mock
@reg("F", "F01 ZZAI 分镜图 estimate → submit → poll → download 全链 Mock")
def _():
    import stages.media_api.zzai as Z

    class FakeClient:
        def upload(self, path):
            A_(pathlib.Path(path).is_file(), "上传的参考图必须存在")
            return "https://cdn.example/ref.png"

        def estimate(self, kind, payload):
            A_(kind == "image", "estimate kind 应为 image")
            A_(payload["size"] == "9:16", "宽高比应映射为 size")
            A_(payload.get("images") == ["https://cdn.example/ref.png"], "图生图参考图未透传")
            return {"estimate_available": True, "amount": 0.05,
                    "currency": "CNY", "confidence": "high"}

        def submit(self, kind, payload, *, max_cost=None, authorized=False):
            A_(authorized is True, "真实提交必须 authorized=True")
            A_(max_cost == 0.1, "max_cost 未透传")
            return {"task_id": "task_board_1", "status": "queued"}

        def poll(self, kind, task_id):
            return {"task_id": task_id, "status": "succeeded", "progress": "100%",
                    "result_url": "https://cdn.example/board.png",
                    "result_urls": ["https://cdn.example/board.png"],
                    "usage": {"amount": 0.04, "currency": "CNY"}, "error": ""}

        def download(self, url, dest, **_kw):
            pathlib.Path(dest).parent.mkdir(parents=True, exist_ok=True)
            pathlib.Path(dest).write_bytes(b"png")
            return {"ok": True, "path": str(dest), "bytes": 3}

    ws = _TMP / "board_zzai_mock"
    out = ws / "04-资产" / "boards" / "ep01"
    ws.mkdir(parents=True, exist_ok=True)
    assets = G.L.assets_dir(ws)
    ref = assets / "characters" / "P01.png"
    ref.parent.mkdir(parents=True, exist_ok=True)
    ref.write_bytes(b"png")
    (assets / "refs.json").write_text(
        json.dumps({"characters": {"P01": str(ref)}, "scenes": {}},
                   ensure_ascii=False), encoding="utf-8")
    args = argparse.Namespace(
        with_refs=False, model="zhenzhen-image-g-v2.6-lowprice",
        resolution="1k", quality="high", yes=True, max_cost=0.1,
        force=False, poll_seconds=0.01, ep="ep01",
    )
    plan = [("shot_001", "A cinematic still frame", 1, ["P01"],
             {"ratio": "9:16", "refs": ["P01"]})]
    with mock.patch.object(Z, "ZZAIClient", FakeClient):
        rc = G._run_zzai(ws, args, plan, out)
    A_(rc == 0, "ZZAI Mock 全链应成功，实际 rc=%s" % rc)
    A_((out / "shot_001.png").is_file(), "分镜图未落盘")
    task_files = list((ws / ".drama" / "media").glob("mt_*.json"))
    A_(len(task_files) == 1, "应写 1 条媒体任务，实际 %d" % len(task_files))
    rec = json.loads(task_files[0].read_text(encoding="utf-8"))
    A_(rec["status"] == "succeeded", "任务状态应 succeeded：%s" % rec["status"])
    A_(rec["remote_task_id"] == "task_board_1", "远端 task ID 未保存")
    A_(rec["actual_cost"]["amount"] == 0.04, "实际金额未保存：%s" % rec.get("actual_cost"))
    return "ZZAI Mock 全链"


@reg("F", "F02 没有参考图时拒绝生成，不退化成文生图")
def _():
    ws = _TMP / "board_zzai_no_refs"
    ws.mkdir(parents=True, exist_ok=True)
    args = argparse.Namespace(
        with_refs=True, model="zhenzhen-image-g-v2.6-lowprice",
        resolution="1k", quality="high", yes=True, max_cost=0.1,
        force=False, poll_seconds=0.01, ep="ep01",
    )
    with mock.patch("stages.media_api.zzai.ZZAIClient") as cls:
        rc = G._run_zzai(ws, args, [("shot_001", "x", 1, [], {"ratio": "9:16", "refs": []})],
                         ws / "04-资产" / "boards" / "ep01")
        A_(not cls.called, "无参考图时不应创建 API 客户端")
    A_(rc == 2, "无参考图应返回配置错误 2，实际 %s" % rc)
    return "no refs → block"


# =========================================================================== G 本地/云端 i2i
@reg("G", "G01 本地通道固定使用 edit 工作流并传参考图")
def _():
    ws = _TMP / "board_local_i2i"
    shutil.copytree(FIXTURE, ws)
    ref = ws / "characters" / "char_ava_00.png"
    ref.parent.mkdir(parents=True, exist_ok=True)
    ref.write_bytes(b"png")
    scene_ref = ws / "scenes" / "scene_room_00.png"
    scene_ref.parent.mkdir(parents=True, exist_ok=True)
    scene_ref.write_bytes(b"png")
    captured = []

    def fake_run(cmd, **kwargs):
        captured.append((cmd, kwargs))
        tmp = pathlib.Path(cmd[cmd.index("--out") + 1])
        tmp.mkdir(parents=True, exist_ok=True)
        prefix = cmd[cmd.index("--prefix") + 1]
        (tmp / ("%s_00.png" % prefix)).write_bytes(b"png")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    argv = ["gen_boards.py", "--workspace", str(ws), "--ep", "ep01",
            "--engine", "local", "--apply", "--force", "--limit", "1"]
    with mock.patch.object(sys, "argv", argv), mock.patch.object(subprocess, "run", fake_run):
        rc = G.main()
    A_(rc == 0, "本地 Mock 出图应成功，实际 %s" % rc)
    A_(len(captured) == 1, "应只提交 1 次本地任务，实际 %d" % len(captured))
    cmd, kwargs = captured[0]
    A_("workflow_qwen21_edit.json" in " ".join(cmd), "本地分镜图必须走 edit 工作流")
    A_("--image" in cmd, "本地图生图必须传参考图")
    A_(kwargs.get("env", {}).get("COMFYUI_URL", "") in ("", os.environ.get("COMFYUI_URL", "")),
       "本地通道不应被误写成远端地址")
    return "local → edit + refs"


@reg("G", "G02 4 图 i2i 工作流识别出 4 个 LoadImage 槽")
def _():
    import importlib.util
    wf = G.ROOT / "stages" / "assets" / "comfyui" / "workflow_qwen21_i2i_turbo_4ref.json"
    A_(wf.is_file(), "4 图工作流预置不存在：%s" % wf)
    A_(G._load_image_slots(wf) == 4, "应识别出 4 个 LoadImage，实际 %d" % G._load_image_slots(wf))
    spec = importlib.util.spec_from_file_location("comfy_client_test", G.COMFY_CLIENT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    A_(mod.preset_key_for(str(wf)) == "edit4", "4 图工作流应命中 edit4 预设")
    mod.apply_preset(str(wf))
    A_(len(mod.LOAD_NODES) == 4, "edit4 预设应配置 4 个 LoadImage 节点：%s" % mod.LOAD_NODES)
    return "4 slots / edit4"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", default="")
    args = ap.parse_args()
    groups = [args.group.upper()] if args.group else ["A", "B", "C", "D", "E", "F", "G"]
    passed = failed = 0
    try:
        for g in groups:
            sel = [c for c in CASES if c[0] == g]
            if not sel:
                continue
            print("【%s 组】%d 例" % (g, len(sel)))
            print("=" * 84)
            for _, name, fn in sel:
                try:
                    note = fn() or ""
                    print("  [PASS] %-52s %s" % (name, note))
                    passed += 1
                except AssertionError as e:
                    print("  [FAIL] %-52s %s" % (name, e))
                    failed += 1
                except Exception as e:                          # noqa: BLE001
                    print("  [ERR ] %-52s %s: %s" % (name, type(e).__name__, e))
                    failed += 1
            print()
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)
    print("=" * 84)
    print("合计 %d 例 ｜ 通过 %d ｜ 失败 %d" % (passed + failed, passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
