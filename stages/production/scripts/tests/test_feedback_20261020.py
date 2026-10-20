#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_feedback_20261020.py —— 2026-10-19/20 实跑反馈单的回归测试（离线）

覆盖（每条对应反馈单里的一个 ID）：
  P0-2  只读探针的判定分类（不联网：把 post 打桩）
  P0-3  剧名从工作区推导（不再出现「七大姑催婚」）
  P0-6  发行门禁分层判定：物料齐、只差成片 → ready_for_export
  P1-1  没有执行器的模型选项不允许确认
  P1-7/P0-7  在途任务 / 待补下载两份台账
  P1-13 OOM 三级重试计划 + 时长下移
  P2-1/6/7  成本口径：固定+变动、tier 差异、GPU 秒、台账自校准
  P2-2  workflowId 反查（三种页面形态）
  P2-3  人工拆解表解析
  P2-4/P2-5  字段行写法统一 + 非法字段行告警
  P2-9  TIME → 光位短语
  P1-14 字幕滤镜探测（无 libass 时给两遍法提示）
  P2-13 单一字幕模板校验
  P2-10 421 视为可重试
  P2-14 单例锁

用法：python test_feedback_20261020.py      （全绿退出码 0）
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
PROD = HERE.parent                          # stages/production/scripts
REPO = PROD.parents[1]                      # <repo>/stages
ROOT = REPO.parent                          # <repo>

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print("  [%s] %s%s" % ("OK  " if ok else "FAIL", name,
                           "" if ok else "  <- %s" % str(detail)[:200]))


def load(path: pathlib.Path, name: str):
    """按文件路径加载模块（脚本不在包内，且有同名 config）。"""
    for p in (str(path.parent), str(REPO), str(PROD)):
        if p not in sys.path:
            sys.path.insert(0, p)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    # dataclass 需要能通过 sys.modules 找到所属模块（否则 __module__ 解析失败）
    sys.modules[name] = mod
    spec.loader.exec_module(mod)          # type: ignore[union-attr]
    return mod


# `_ws` 是在**导入期**求值 `WS = resolve()` 的：测试里先准备一个合法工作区并写回环境变量，
# 否则任何 `import _ws`（convert_storyboard 顶部的依赖）都会直接 SystemExit。
_FAKE_WS = pathlib.Path(tempfile.mkdtemp(prefix="sd_test_ws_"))
(_FAKE_WS / "video-pipeline" / "data").mkdir(parents=True, exist_ok=True)
os.environ["SOLODRAMA_WORKSPACE"] = str(_FAKE_WS)
os.environ["DRAMA_WORKSPACE"] = str(_FAKE_WS)


# ---------------------------------------------------------------- P0-2
def t_probe_readonly() -> None:
    doc = load(PROD / "rh_doctor.py", "rh_doctor_t")
    cases = [
        (200, {"code": 0, "msg": "ok"}, "ok"),
        (200, {"code": "1", "msg": "API Key不存在"}, "bad_key"),
        (200, {"code": 1007, "msg": "任务不存在"}, "ok"),
        (404, None, "route_missing"),
        (0, None, "network"),
    ]
    for status, payload, want in cases:
        doc.post = lambda *a, **k: (status, payload, "raw")      # 打桩：零网络
        got = doc.probe_readonly("https://www.runninghub.cn", "k")
        check("P0-2 探针判定 %s -> %s" % (payload, want), got["verdict"] == want, got)


# ---------------------------------------------------------------- P0-3
def t_drama_name() -> None:
    ws = pathlib.Path(tempfile.mkdtemp(prefix="sd_name_"))
    check("P0-3 无 brief/project 时回落目录名",
          load(PROD / "_ws.py", "_ws_t1").drama_name(ws) == ws.name, ws.name)
    (ws / "brief.json").write_text(json.dumps({"title": "Loteria 580"}, ensure_ascii=False),
                                   encoding="utf-8")
    check("P0-3 brief.json 的 title 优先",
          load(PROD / "_ws.py", "_ws_t2").drama_name(ws) == "Loteria 580")
    # 注释里可以提到事故本身，但**代码行**不许再把剧名当默认值
    src = (PROD / "cost_ledger.py").read_text(encoding="utf-8")
    code_lines = [ln for ln in src.splitlines()
                  if "DRAMA_DEFAULT =" in ln and not ln.lstrip().startswith("#")]
    check("P0-3 默认剧名不再是硬编码字面量",
          code_lines == ["DRAMA_DEFAULT = drama_name(WS)"], code_lines)


# ---------------------------------------------------------------- P0-6
def _mk_release_ws(with_episode: bool) -> pathlib.Path:
    ws = pathlib.Path(tempfile.mkdtemp(prefix="sd_rel_"))
    rel = ws / "09-发行"
    (rel / "剧集").mkdir(parents=True)
    (rel / "文案").mkdir()
    def png(w: int, h: int) -> bytes:
        return (b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + w.to_bytes(4, "big")
                + h.to_bytes(4, "big") + b"\x00" * 40)

    for tag, (w, h) in (("9x16", (900, 1600)), ("3x4", (900, 1200))):
        (rel / ("cover_%s.png" % tag)).write_bytes(png(w, h))
    png = png(1400, 900)
    (rel / "文案" / "copy.json").write_text("{}", encoding="utf-8")
    (rel / "发布清单.md").write_text("# x", encoding="utf-8")
    (rel / "版权资料").mkdir()
    (rel / "版权资料" / "版权资料清单.md").write_text("# x", encoding="utf-8")
    for pfx in ("ai-process", "source-file"):
        for n in (1, 2, 3, 4):
            (rel / "版权资料" / ("%s-%02d-x.png" % (pfx, n))).write_bytes(png)
    if with_episode:
        (rel / "剧集" / "Episode01.mp4").write_bytes(b"\x00" * 64)
    return ws


def t_release_verdict() -> None:
    ws = _mk_release_ws(False)
    p = subprocess.run([sys.executable, str(PROD / "release_check.py"),
                        "--workspace", str(ws), "--json"],
                       capture_output=True, text=True, encoding="utf-8")
    out = json.loads(p.stdout or "{}")
    check("P0-6 物料齐、成片缺 → ready_for_export",
          out.get("verdict") == "ready_for_export", out.get("verdict"))
    check("P0-6 成片缺项单独归入 downstream",
          out.get("downstream") and not out.get("material_fails"), out.get("downstream"))
    p2 = subprocess.run([sys.executable, str(PROD / "release_check.py"),
                         "--workspace", str(ws), "--json", "--material-only"],
                        capture_output=True, text=True, encoding="utf-8")
    out2 = json.loads(p2.stdout or "{}")
    check("P0-6 --material-only 时成片不再阻断（退出码 0）",
          p2.returncode == 0 and out2.get("verdict") == "ok", p2.returncode)


# ---------------------------------------------------------------- P1-1
def t_model_gate_executor() -> None:
    gate = load(PROD / "model_gate.py", "model_gate_t")
    ws = pathlib.Path(tempfile.mkdtemp(prefix="sd_gate_"))
    wf = ws / "wf.json"
    wf.write_text("{}", encoding="utf-8")
    doc = gate.MODEL_OPTIONS["video"]
    local = next(o for o in doc if o["id"] == "local_comfyui")
    check("P1-1 video=local_comfyui 标注为无执行器",
          local.get("executor") is None and not local.get("manual"), local)
    check("P1-1 菜单显式写「暂无执行器」",
          "暂无执行器" in gate.render_menu("video"))
    rc = gate._do_set(ws, "video", "local_comfyui", {"comfy_workflow": str(wf)})
    check("P1-1 无执行器的选项被拦下（退出码 4）", rc == 4, rc)
    ok, msg = gate.require(ws, "video", expected_engine="workflow")
    check("P1-1 未确认时门禁不放行", not ok)


# ---------------------------------------------------------------- P1-7 / P0-7
def t_inflight_pending() -> None:
    import asyncio
    eng = ROOT / "stages" / "video" / "workflow" / "scripts" / "engine"
    mod = load(eng / "inflight.py", "inflight_t")
    d = pathlib.Path(tempfile.mkdtemp(prefix="sd_inf_"))

    async def run():
        inf = mod.Inflight(d)
        await inf.add("shot_001", "T1", duration_s=8)
        await inf.add("shot_002", "T2")
        got = inf.load()
        await inf.remove("shot_001")
        return got, inf.load()

    got, left = asyncio.run(run())
    check("P0-7 提交即落 inflight", set(got) == {"shot_001", "shot_002"}, got)
    check("P0-7 终态后移除 inflight", list(left) == ["shot_002"], left)

    async def run2():
        pd = mod.PendingDownloads(d)
        await pd.add(shot_id="shot_003", task_id="T3", url="http://x/a.mp4",
                     dest=str(d / "a.mp4"), error="reset")
        await pd.add(shot_id="shot_003", task_id="T3", url="http://x/a.mp4",
                     dest=str(d / "a.mp4"), error="reset again")
        n = len(pd.load())
        await pd.remove("shot_003")
        return n, pd.load()

    n, left2 = asyncio.run(run2())
    check("P1-7 同一段重复记录不产生多条", n == 1, n)
    check("P1-7 补下载后可清除记录", left2 == [], left2)


# ---------------------------------------------------------------- P1-13
def t_oom_plan() -> None:
    eng = ROOT / "stages" / "video" / "workflow" / "scripts" / "engine"
    pipeline = load(eng / "pipeline.py", "pipeline_t")
    plan = pipeline._oom_retry_plan()
    check("P1-13 OOM 三级重试（原实例 → 升实例 → 升实例+降时长）",
          len(plan) == 3 and plan[1][0] != plan[0][0] and plan[2][1] < 0, plan)
    check("P1-13 时长下移不小于 2 秒", pipeline._shift_duration(3, -2) == 2.0,
          pipeline._shift_duration(3, -2))
    rc = load(eng / "runninghub_client.py", "rhc_t")
    check("P1-13 OOM 文本识别（errorCode 805 / VRAM grow / 中文告警）",
          rc.is_oom_error("errorCode 805 VRAM grow failed") and
          rc.is_oom_error("torch.OutOfMemoryError【显存不足告警】") and
          not rc.is_oom_error("内容策略拦截"), "")
    check("P2-10 421 queue limit 归为可重试关键词",
          any("queue limit" in w for w in rc._RETRY_HINT_WORDS), rc._RETRY_HINT_WORDS)


# ---------------------------------------------------------------- P2-1/6/7
def t_cost_model() -> None:
    cm = load(PROD / "cost_model.py", "cost_model_t")
    p = cm.load_params(None)
    c5 = cm.estimate([5], tier="consumer", params=p)
    check("P2-1 消费级 5 秒 = 27+5 = 32 币", abs(c5["coins"] - 32) < 0.01, c5["coins"])
    e5 = cm.estimate([5], tier="ent_shared", params=p)
    check("P2-6 企业级 5 秒 ≈ ¥0.147", abs(e5["cny"] - 0.147) < 0.006, e5["cny"])
    check("P2-6 两个 tier 用不同的计价货币",
          c5["currency"] == "RH币" and e5["currency"] == "money",
          (c5["currency"], e5["currency"]))
    check("P2-7 同时给出 GPU 运行秒口径",
          c5["gpu_seconds"] > 0 and abs(c5["gpu_model_coins"] - 0.205 * c5["gpu_seconds"]) < 1,
          (c5["gpu_seconds"], c5["gpu_model_coins"]))
    recs = [{"duration_s": d, "coins": 27 + d, "money": None, "task_cost_time": 100 + 7 * d}
            for d in (5, 8, 10, 12)]
    cal = cm.calibrate(recs, p)
    check("P2-7 用台账校准出币/运行秒与固定+变动",
          cal["fitted"] and abs(cal["fitted"].get("consumer_fixed", 0) - 27) < 0.5,
          cal["fitted"])
    empty = cm.calibrate([], p)
    check("P2-7 样本不足时不臆造（fitted 为空）", not empty["fitted"], empty["fitted"])


# ---------------------------------------------------------------- P2-2
def t_workflow_id() -> None:
    m = load(PROD / "rh_workflow_id.py", "rwid_t")
    a = m.extract('var x = {workflowId: "2110380691388194818"}')
    check("P2-2 明文形态可解", a["strong"] == ["2110380691388194818"], a)
    arr = ["app", {"workflowId": 3, "name": 4}, 7, "2110380691388194818", "demo"]
    html = '<script id="__NUXT_DATA__" type="application/json">%s</script>' % json.dumps(arr)
    b = m.extract(html)
    check("P2-2 __NUXT_DATA__ 形态可解", b["nuxt"] == ["2110380691388194818"], b)
    c = m.extract("<html>nothing</html>")
    check("P2-2 找不到时不猜", not (c["strong"] or c["nuxt"]), c)


# ---------------------------------------------------------------- P2-3
def t_outline() -> None:
    m = load(ROOT / "stages" / "creation" / "scripts" / "script_rewrite.py", "sr_t")
    p = pathlib.Path(tempfile.mkdtemp(prefix="sd_out_")) / "o.md"
    p.write_text("| 集 | 开场 | 冲突 | 反转 | 钩子 |\n|---|---|---|---|---|\n"
                 "| EP01 | 被赶出家门 | 家族夺产 | 亮出股权书 | 门口站着生父 |\n"
                 "EP02: 前夫带新欢上门\n", encoding="utf-8")
    rows, warns = m.parse_outline(p)
    check("P2-3 四列表格解析成四件套",
          rows[1]["cold_open"] == "被赶出家门" and rows[1]["hook"] == "门口站着生父", rows)
    check("P2-3 冒号单行写法落到核心冲突",
          rows[2] == {"core_conflict": "前夫带新欢上门"}, rows)
    check("P2-3 解析无告警", warns == [], warns)


# ---------------------------------------------------------------- P2-4 / P2-5
def t_lint() -> None:
    tools_dir = ROOT / "tools"
    sys.path.insert(0, str(ROOT))
    from tools.core import validate as v                 # 相对导入，必须按包导入
    check("P2-4 字段行正则容忍缩进",
          bool(v.FIELD_LINE_LOOSE_RE.match("    DUR: 8")), "")
    md = "\n".join([
        "SC-01", "SHOT: 1", "LOCATION: 客厅", "TIME: 夜", "CHAR: LIN_A",
        "ACTION: 她把钥匙放下", "MOOD: 紧张", "    DIALOG: “你走吧”",
        "SC-02", "SHOT: 2", "ACTION: 他站着不动",
    ])
    issues = v._check_stray_field_lines(md)
    where = [i.where for i in issues]
    check("P2-5 行首非法字段行被告警", where == ["L7"], where)
    check("P2-5 缩进续行不误报", all(i.level == "WARN" for i in issues), issues)


# ---------------------------------------------------------------- P2-9
def t_light() -> None:
    m = load(PROD / "convert_storyboard.py", "cs_t")
    check("P2-9 夜→单灯深影", "lamp" in m.light_phrase("夜"), m.light_phrase("夜"))
    check("P2-9 日→窗光柔补", "daylight" in m.light_phrase("白天"), m.light_phrase("白天"))
    check("P2-9 黄昏优先于日（避免子串误判）",
          "low warm side light" in m.light_phrase("黄昏"), m.light_phrase("黄昏"))
    check("P2-9 认不出不猜", m.light_phrase("未来") == "", m.light_phrase("未来"))


# ---------------------------------------------------------------- P1-14 / P2-13
def t_subtitle_template() -> None:
    sub = load(ROOT / "stages" / "subtitle" / "scripts" / "subtitle.py", "sub_t")
    cfg = json.loads((ROOT / "stages" / "subtitle" / "assets"
                      / "config.subtitle.example.json").read_text(encoding="utf-8"))
    errs, warns = sub.check_single_template(cfg)
    check("P2-13 官方示例配置只有单套模板", errs == [] and warns == [], (errs, warns))
    bad = dict(cfg)
    bad["narrator"] = {"margin_v_pct": 4, "font_size_pct": 5}
    errs2, _ = sub.check_single_template(bad)
    check("P2-13 出现按角色的第二套纵向坐标 → 报错", len(errs2) == 1, errs2)
    up = load(ROOT / "stages" / "subtitle" / "scripts" / "upscale.py", "up_t")
    note = up.burn_subtitle_note({"ffmpeg": ""})
    check("P1-14 无 ffmpeg 时不强行提示", note == "", note)


# ---------------------------------------------------------------- P2-14
def t_lock() -> None:
    m = load(PROD / "_lock.py", "lock_t")
    ws = pathlib.Path(tempfile.mkdtemp(prefix="sd_lock_"))
    blocked = False
    with m.single_instance("job", ws):
        try:
            with m.single_instance("job", ws):
                pass
        except SystemExit as e:
            blocked = (e.code == 4)
    check("P2-14 重复启动被拦下（退出码 4）", blocked)
    check("P2-14 退出后锁被释放", not m.lock_path(ws, "job").exists())


# ---------------------------------------------------------------- P1-2
def t_workflow_validate() -> None:
    m = load(ROOT / "stages" / "assets" / "comfyui" / "comfy_client.py", "cc_t")
    wf = json.loads((ROOT / "stages" / "assets" / "comfyui"
                     / "workflow_qwen_image21.json").read_text(encoding="utf-8"))
    check("P1-2 仓库默认工作流自检通过", m.validate_workflow(wf) == [], m.validate_workflow(wf))
    bad = {"1": {"class_type": "VAEDecode", "inputs": {"samples": ["99", 0]}},
           "2": {"class_type": "LoadImage", "inputs": {"image": ""}}}
    probs = m.validate_workflow(bad)
    check("P1-2 抓出悬空连线", any("不存在的节点 99" in p for p in probs), probs)
    check("P1-2 抓出模板未填的输入", any("为空" in p for p in probs), probs)


def main() -> int:
    print("=" * 62)
    print("反馈单修复 · 离线回归（2026-10-20）")
    print("=" * 62)
    for fn in (t_probe_readonly, t_drama_name, t_release_verdict, t_model_gate_executor,
               t_inflight_pending, t_oom_plan, t_cost_model, t_workflow_id, t_outline,
               t_lint, t_light, t_subtitle_template, t_lock, t_workflow_validate):
        try:
            fn()
        except BaseException as e:                                # noqa: BLE001
            check("%s 未预期异常" % fn.__name__, False, "%s: %s" % (type(e).__name__, e))
    print("-" * 62)
    print("共 %d 例，通过 %d，失败 %d" % (len(PASS) + len(FAIL), len(PASS), len(FAIL)))
    if FAIL:
        for f in FAIL:
            print("  失败：%s" % f)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
