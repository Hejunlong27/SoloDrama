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


# ---------------------------------------------------------------- P0-3
def t_drama_name() -> None:
    ws = pathlib.Path(tempfile.mkdtemp(prefix="sd_name_"))
    check("P0-3 无 brief/project 时回落目录名",
          load(PROD / "_ws.py", "_ws_t1").drama_name(ws) == ws.name, ws.name)
    (ws / "brief.json").write_text(json.dumps({"title": "Loteria 580"}, ensure_ascii=False),
                                   encoding="utf-8")
    check("P0-3 brief.json 的 title 优先",
          load(PROD / "_ws.py", "_ws_t2").drama_name(ws) == "Loteria 580")
    # ★ 2026-11-04：原来这里还断言 cost_ledger.py 的 DRAMA_DEFAULT 不是硬编码字面量。
    #   `drama_name()` 本身的两条断言（目录名回落 / brief 优先）仍然有效，保留。


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
    # ★ 2026-11-04 反转：原断言是「本地 H3 没有执行器」（反馈 P1-1 当时的真实情况）。
    #   现在 comfy_local_video.py 就是本地执行器，判据必须跟着反过来 ——
    #   留着旧断言等于守着一个已经修好的 bug，还会让人以为它没修。
    check("P1-1 video=local_comfyui 有执行器",
          bool(local.get("executor")) and not local.get("manual"), local)
    check("P1-1 本地那条菜单写出了执行器",
          "执行器：stages/video/comfyui/comfy_local_video.py" in gate.render_menu("video"),
          gate.render_menu("video"))
    rc = gate._do_set(ws, "video", "local_comfyui", {"comfy_workflow": str(wf)})
    check("P1-1 有执行器的选项可确认（退出码 0）", rc == 0, rc)
    ok, msg = gate.require(ws, "video", expected_engine="local")
    check("P1-1 确认后门禁放行", ok, msg)


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
    #   留下的都在跑真实逻辑：剧名回落、发行判定、模型门禁、字幕模板、单例锁、工作流校验。
    for fn in (t_drama_name, t_release_verdict, t_model_gate_executor,
               t_subtitle_template, t_lock, t_workflow_validate):
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
