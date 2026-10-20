#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_cover_forge.py —— 封面引擎收编 + 反馈 P1-9/10/11 的离线回归

覆盖：
  1. 收编后仍能出图（三条布局各一张，尺寸正确）
  2. P1-9 色条按**真实字形底边**定位：色条 y 必须大于 bbox 底边，
     且必须大于旧的「1.12em 经验值」位置（旧公式恰好落在逗号降部上）
  3. P1-10 副标自动收缩：长副标在窄画幅下字号变小、右侧不被裁
  4. P1-11 `--check` 对「窄源图 → 宽幅」主动告警
  5. `--workspace` 未写 out_dir 时默认落 `<工作区>/<发行目录>/封面/`
  6. 缺源图 / 缺字段 → 退出码 1

用法：python test_cover_forge.py     （全绿退出码 0）
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
SCRIPT = HERE.parent / "cover_forge.py"

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  [%s] %s%s" % ("OK  " if ok else "FAIL", name, "" if ok else "  <- %s" % str(detail)[:220]))


def load():
    spec = importlib.util.spec_from_file_location("cover_forge_t", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["cover_forge_t"] = mod
    spec.loader.exec_module(mod)          # type: ignore[union-attr]
    return mod


def run(args):
    p = subprocess.run([sys.executable, str(SCRIPT)] + args,
                       capture_output=True, text=True, encoding="utf-8")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def make_sources(d: pathlib.Path):
    from PIL import Image, ImageDraw
    v = Image.new("RGB", (600, 1200), (40, 45, 60))
    ImageDraw.Draw(v).ellipse([180, 200, 430, 700], fill=(200, 170, 150))
    v.save(d / "base_vertical.png")
    w = Image.new("RGB", (1600, 900), (30, 34, 48))
    ImageDraw.Draw(w).ellipse([900, 150, 1400, 750], fill=(190, 160, 140))
    w.save(d / "base_wide.png")


SPEC = {
    "palette": {"accent": "#8A1538", "accent2": "#E9C79C"},
    "fonts": {"title": ["georgiab.ttf"], "body": ["georgia.ttf"], "sans": ["seguisb.ttf"]},
    "text": {"tag": "VENGANZA FAMILIAR", "title": "5,8 MILLONES",
             "sub1": "ME LLAMARON LA PRIMA POBRE",
             "sub2": "AHORA SOY LA DUEÑA DE TODO",
             "kicker": "60 EPISODIOS", "badge": "ESPAÑOL · 18-44"},
    "covers": [
        {"src": "base_vertical.png", "size": [900, 1600], "name": "cover_9x16", "focus": 0.12},
        {"src": "base_vertical.png", "size": [900, 1200], "name": "cover_3x4", "focus": 0.12},
        {"src": "base_wide.png", "size": [1920, 1080], "name": "cover_16x9", "focus": 0.2, "side": 0.58},
    ],
    "export": {"png": True, "jpg": False, "preview": False},
}


def t_band_geometry():
    m = load()
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (900, 1600))
    d = ImageDraw.Draw(im)
    fp = m.resolve_family(["georgiab.ttf"], "title")
    fb = m.fit_font(fp, "5,8 MILLONES", 156, 802)
    y = 1187
    bb = d.textbbox((49, y), "5,8 MILLONES", font=fb)
    by, bottom = m.band_y(d, fb, "5,8 MILLONES", 49, y)
    old = y + int(fb.size * 1.12)
    check("P1-9 色条在真实字形底边之下", by > bb[3], "band=%s bbox_bottom=%s" % (by, bb[3]))
    check("P1-9 色条比旧经验值更低（旧值落在降部内）", by > old, "band=%s old=%s" % (by, old))
    check("P1-9 底边包含逗号降部（底边 > 顶部+0.9em）",
          bb[3] > y + int(fb.size * 0.9), "bbox_bottom=%s size=%s" % (bb[3], fb.size))
    check("P1-9 band_y 与 bbox 底边间距 = 0.16em",
          abs((by - bb[3]) - fb.size * 0.16) <= 1, (by - bb[3], fb.size))


def t_sub_fit():
    m = load()
    fp = m.resolve_family(["georgia.ttf"], "body")
    T = {"sub1": "ME LLAMARON LA PRIMA POBRE", "sub2": "AHORA SOY LA DUEÑA DE TODO"}
    base, usable = 53, 802
    fs = m._sub_font(fp, T, base, usable)
    check("P1-10 长副标自动收缩", fs.size < base, "base=%s -> %s" % (base, fs.size))
    check("P1-10 收缩后不超可用宽",
          fs.getlength(max(T.values(), key=len)) <= usable,
          fs.getlength(max(T.values(), key=len)))
    short = m._sub_font(fp, {"sub1": "HI", "sub2": ""}, base, usable)
    check("P1-10 短副标不缩（保持目标字号）", short.size == base, short.size)


def t_end_to_end():
    d = pathlib.Path(tempfile.mkdtemp(prefix="sd_cover_"))
    make_sources(d)
    spec = json.loads(json.dumps(SPEC))
    spec["out_dir"] = "out"
    p = d / "spec.json"
    p.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")

    rc, out = run(["--spec", str(p)])
    outs = sorted((d / "out").glob("*.png"))
    check("端到端：三档全部出图（退出码 0）", rc == 0 and len(outs) == 3, (rc, outs))

    from PIL import Image
    for f, want in ((d / "out" / "cover_9x16.png", (900, 1600)),
                    (d / "out" / "cover_3x4.png", (900, 1200)),
                    (d / "out" / "cover_16x9.png", (1920, 1080))):
        got = Image.open(f).size if f.is_file() else None
        check("端到端：%s 尺寸 %s" % (f.name, want), got == want, got)

    # P1-10 硬证据：文字像素不得触到右边缘
    import numpy as np
    im = Image.open(d / "out" / "cover_3x4.png").convert("L")
    a = np.array(im)
    bright = a > 190
    right_touch = bright[:, -2:].sum()
    check("P1-10 副标未触右边缘（无裁字）", right_touch <= 2, "右边缘亮像素 %s" % right_touch)


def t_check_warn():
    d = pathlib.Path(tempfile.mkdtemp(prefix="sd_cover2_"))
    make_sources(d)
    spec = json.loads(json.dumps(SPEC))
    spec["out_dir"] = "out"
    spec["covers"] = [
        {"src": "base_vertical.png", "size": [1920, 1080], "name": "wide_from_vertical"},
    ]
    p = d / "spec.json"
    p.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    rc, out = run(["--spec", str(p), "--check"])
    check("P1-11 窄源图转宽幅被 --check 告警",
          rc == 0 and ("更窄" in out and "横版底图" in out), out[:200])
    check("P1-10 --check 行内报出副标实际字号", "sub=" in out, out[:200])


def t_workspace_outdir():
    d = pathlib.Path(tempfile.mkdtemp(prefix="sd_cover3_"))
    make_sources(d)
    ws = d / "proj"
    (ws / "机构目录").mkdir(parents=True)
    (ws / "layout.json").write_text(json.dumps({"stages": {"release": "机构目录"}}), encoding="utf-8")
    spec = json.loads(json.dumps(SPEC))
    spec.pop("out_dir", None)
    spec["covers"] = [{"src": str(d / "base_wide.png"), "size": [1920, 1080], "name": "c1"}]
    p = d / "spec.json"
    p.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    rc, out = run(["--spec", str(p), "--check", "--workspace", str(ws)])
    check("--workspace 时输出目录落 <发行目录>/封面",
          "机构目录" in out and "封面" in out, out[-200:])


def t_errors():
    d = pathlib.Path(tempfile.mkdtemp(prefix="sd_cover4_"))
    spec = {"covers": [{"src": "nope.png", "size": [900, 1600]}], "text": {"title": "X"}}
    p = d / "spec.json"
    p.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    rc, out = run(["--spec", str(p), "--check"])
    check("缺源图 → 退出码 1 且说明原因", rc == 1 and "源图不存在" in out, (rc, out[:160]))


def main():
    print("=" * 62)
    print("cover_forge 收编回归（P1-9 / P1-10 / P1-11）")
    print("=" * 62)
    for fn in (t_band_geometry, t_sub_fit, t_end_to_end, t_check_warn,
               t_workspace_outdir, t_errors):
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
