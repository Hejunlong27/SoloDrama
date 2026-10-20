#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_cover_prompt.py —— 封面提示词编译器（AI 直出带字）的离线回归

覆盖：
  1. 标题断行：西语 ≤18 字符、中文 ≤6 字、词不拆开、最多 3 行
  2. 提示词含**确切标题字符串**与完整负面词（AI 出字的唯一硬约束）
  3. 体检能拦住真会毁图的写法（无标题 / 超长单词 / 超 3 行）
  4. 通道清单：ComfyUI 清单可被 comfy_client 消费；RH 计划不猜 nodeId
  5. 九套风格锚全部可解析；未知 id 当作自定义锚句
  6. CLI 端到端：--emit comfy 写出合法 JSON

用法：python test_cover_prompt.py     （全绿退出码 0）
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
SCRIPT = HERE.parent / "cover_prompt.py"

PASS, FAIL = [], []

REF_TITLE = "ME CASÉ CON UN MULTIMILLONARIO AMNÉSICO"
REF_SUB = "UNA HISTORIA DE AMOR Y MEMORIAS PERDIDAS"


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  [%s] %s%s" % ("OK  " if ok else "FAIL", name, "" if ok else "  <- %s" % str(detail)[:220]))


def load():
    spec = importlib.util.spec_from_file_location("cover_prompt_t", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cover_prompt_t"] = mod
    spec.loader.exec_module(mod)      # type: ignore[union-attr]
    return mod


BRIEF = {
    "market": "es-MX", "language": "es", "style": "latam-rain-night",
    "title": REF_TITLE, "subtitle": REF_SUB,
    "top_strip": ["PAREDO BENYIDON", "DRAMA MEXICO CITY", "ROSTAR PAUL WATER"],
    "credits": "FICTIONAL DRAMA POSTER · UNA PRODUCCIÓN ORIGINAL",
    "subjects": "Man in navy pinstripe suit on the left; woman in black off-shoulder dress on the right; "
                "profile, eyes locked, her hand on his chest.",
    "scene": "Rain-streaked glass, warm sconce key, cold blue bokeh.",
    "conflict_prop": "his wedding ring in her palm",
    "sizes": ["9x16", "3x4", "16x9"],
}


def t_split_headline():
    m = load()
    lines = m.split_headline(REF_TITLE, 18, 3)
    check("标题切成 3 行", len(lines) == 3, lines)
    check("每行 ≤18 字符", all(len(x) <= 18 for x in lines), lines)
    check("词不拆开（拼回等于原文）", " ".join(lines) == REF_TITLE, lines)

    zh = m.split_headline("我的前夫是我老板", 6, 3)
    check("中文按 6 字上限断行", all(len(x) <= 6 for x in zh) and "".join(zh) == "我的前夫是我老板", zh)

    check("单词标题保持一行", m.split_headline("AMNÉSICO", 18, 3) == ["AMNÉSICO"])


def t_prompt_content():
    m = load()
    it = m.build_prompt(BRIEF, "9x16")
    p = it["prompt"]
    check("提示词含确切标题", REF_TITLE in p, p[:120])
    check("提示词含确切副标", REF_SUB in p)
    check("提示词含顶条三栏", all(x in p for x in BRIEF["top_strip"]))
    check("提示词要求逐字渲染", "correctly spelled" in p and "no extra words" in p)
    check("提示词含断行指令", "ME CASÉ CON UN" in p and "MULTIMILLONARIO" in p, it["headline_lines"])
    check("负面词含关键项", all(k in it["negative"] for k in ("watermark", "misspelled", "extra words")))
    check("九段式齐全（五段标记）",
          all(tag in p for tag in ("[① STYLE]", "[② SUBJECTS]", "[③ SCENE & LIGHT]",
                                   "[④ COMPOSITION & TYPOGRAPHY]", "[⑤ TECH]")))
    check("尺寸写进 TECH", "1080x1920" in p, p[-80:])


def t_check_brief():
    m = load()
    errs, warns = m.check_brief(BRIEF)
    check("合规 brief 无错误", errs == [], errs)
    check("缺 top_strip 只告警", any("top_strip" in w for w in warns) is False, warns)  # 本例有 top_strip

    errs2, _ = m.check_brief({})
    check("缺标题 → 错误", any("title" in e for e in errs2), errs2)

    long_word = {"title": "SUPERCALIFRAGILISTICEXPIALIDOCIOUS", "sizes": ["9x16"]}
    errs3, _ = m.check_brief(long_word)
    check("超长单词（无法断行）→ 错误", any("超长单词" in e for e in errs3), errs3)

    # 4 个 18 字符的单词：3 行无论如何放不下（每行至少会超）
    too_long = {"title": " ".join(["ABCDEFGHIJKLMNOPQR"] * 4), "sizes": ["9x16"]}
    errs4, _ = m.check_brief(too_long)
    check("3 行放不下 → 错误", any("3 行" in e for e in errs4), errs4)


def t_channels():
    m = load()
    bundle = m.build_all(BRIEF)
    comfy = m.comfyui_manifest(bundle)
    check("ComfyUI 清单：三档三条", len(comfy["assets"]) == 3, len(comfy["assets"]))
    check("ComfyUI 清单：前缀/画幅正确",
          all(a["prefix"] == "cover_" + a["id"].split("_", 1)[1] and a["aspect"] for a in comfy["assets"]),
          comfy["assets"][0])
    check("ComfyUI 清单：提示词内含负面词",
          all("Negative prompt:" in a["prompt"] for a in comfy["assets"]))

    rh = m.rh_plan(bundle)
    check("RH 计划：不猜 workflowId", rh["workflow_id"] == "", rh["workflow_id"])
    check("RH 计划：每档给 node_values", all("node_values" in i and i["node_values"]["prompt"] for i in rh["items"]))
    check("RH 计划：画幅映射含 9:16", "9:16" in rh["aspect_value_map"])


def t_styles():
    m = load()
    ids = list(m.STYLE_ANCHORS)
    check("风格锚 ≥8 条（六预设 + 两条题材）", len(ids) >= 8, len(ids))
    for sid in ("revenge-cold", "latam-mansion-gold", "suspense-noir",
                "fantasy-violet", "urban-clean", "east-period-gold",
                "latam-rain-night", "family-estate"):
        ok = sid in m.STYLE_ANCHORS and len(m.STYLE_ANCHORS[sid]) > 40
        check("锚 %s 可用" % sid, ok)
    custom = m.style_anchor_text({"style_anchor": "Hand-painted gouache poster, 1950s"})
    check("自定义锚句原样透传", custom.startswith("Hand-painted gouache"), custom)


def t_cli():
    d = pathlib.Path(tempfile.mkdtemp(prefix="sd_coverprompt_"))
    bp = d / "brief.json"
    bp.write_text(json.dumps(BRIEF, ensure_ascii=False), encoding="utf-8")
    p = subprocess.run([sys.executable, str(SCRIPT), "--brief", str(bp),
                        "--emit", "comfy", "--out-dir", str(d)],
                       capture_output=True, text=True, encoding="utf-8")
    out = d / "comfyui_manifest.json"
    ok = p.returncode == 0 and out.is_file()
    check("CLI --emit comfy 端到端", ok, (p.returncode, p.stdout[-200:], p.stderr[-200:]))
    if ok:
        data = json.loads(out.read_text(encoding="utf-8"))
        check("产出的清单可解析且含 assets", isinstance(data.get("assets"), list) and len(data["assets"]) == 3)

    p2 = subprocess.run([sys.executable, str(SCRIPT), "--brief", str(bp), "--check"],
                        capture_output=True, text=True, encoding="utf-8")
    check("CLI --check 通过（退出码 0）", p2.returncode == 0, p2.returncode)
    p3 = subprocess.run([sys.executable, str(SCRIPT), "--title", "X" * 60, "--check"],
                        capture_output=True, text=True, encoding="utf-8")
    check("CLI 对超长单词报错（退出码 1）", p3.returncode == 1, p3.returncode)


def main():
    print("=" * 62)
    print("cover_prompt 回归（AI 直出带字封面）")
    print("=" * 62)
    for fn in (t_split_headline, t_prompt_content, t_check_brief, t_channels, t_styles, t_cli):
        try:
            fn()
        except BaseException as e:                                # noqa: BLE001
            check("%s 未预期异常" % fn.__name__, False, "%s: %s" % (type(e).__name__, e))
    print("-" * 62)
    print("共 %d 例，通过 %d，失败 %d" % (len(PASS) + len(FAIL), len(PASS), len(FAIL)))
    for f in FAIL:
        print("  失败：%s" % f)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
