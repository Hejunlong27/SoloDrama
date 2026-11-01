#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""离线测试：参考图瘦身的唯一实现点 `prepare_refs.thin_one`

零网络、零计费。需要 Pillow（与生产脚本一致）。

为什么要这个测试：
    「缩放 + 转码」此前在 `prepare_refs.py` 与 `wire_new_assets.py` 里各写了一遍，
    连常量都靠注释互相抄（`# 与 prepare_refs.py 的 DEFAULT_MAX_EDGE 一致`）。
    2026-11-02 收口成 `thin_one()` 之后，用本测试钉住四件事：
      ① 只缩不放、长边不超过上限、边取偶数；
      ② 原图一个字节都不动（这是对外承诺）；
      ③ jpg / png 两种落盘都认；
      ④ 两个调用方共用同一实现（常量不许再各自抄一份数字）。
"""
from __future__ import annotations

import hashlib
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
SCRIPTS = HERE.parent
sys.path.insert(0, str(SCRIPTS))

from PIL import Image  # noqa: E402

import prepare_refs as PR  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(("  [OK] " if ok else "  [NG] ") + name + (("  ← " + detail) if detail and not ok else ""))


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def make(path: pathlib.Path, size, color=(30, 90, 160)) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path


def test_scale_down():
    print("\n[A] 超限图：缩到长边上限，边取偶数，只缩不放")
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td)
        src = make(d / "big.png", (6001, 301))     # 故意都取奇数
        before = sha(src)
        dst = d / "out" / "big.jpg"
        nw, nh = PR.thin_one(src, dst, max_edge=2048, quality=92)

        check("返回值 = 落盘尺寸", (nw, nh) == Image.open(dst).size, "%r vs %r" % ((nw, nh), Image.open(dst).size))
        check("长边不超过上限", max(nw, nh) <= 2048, "%dx%d" % (nw, nh))
        check("长边正好是上限（不是缩多了）", max(nw, nh) == 2048, "%dx%d" % (nw, nh))
        check("两边都是偶数", nw % 2 == 0 and nh % 2 == 0, "%dx%d" % (nw, nh))
        # 偶数取整会让短边差 1px（301 * 2048/6001 = 102.72 → 102），比例因此有 ~0.7% 偏差，
        # 所以按「短边离理想值不超过 1px」判，而不是按比例。
        ideal_h = 301 * 2048 / 6001
        check("短边离理想值 ≤1px（偶数取整的代价）", abs(nh - ideal_h) <= 1,
              "nh=%d ideal=%.2f" % (nh, ideal_h))
        check("产物是 JPEG", dst.read_bytes()[:2] == b"\xff\xd8", dst.name)
        check("**原图一个字节都没动**", sha(src) == before, "sha 变了")


def test_no_upscale():
    print("\n[B] 小图：只缩不放（尺寸原样保留）")
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td)
        src = make(d / "small.png", (320, 480))
        dst = d / "small.jpg"
        nw, nh = PR.thin_one(src, dst, max_edge=2048)
        check("尺寸不变", (nw, nh) == (320, 480), "%dx%d" % (nw, nh))
        check("仍然产出文件", dst.is_file() and dst.stat().st_size > 0)


def test_png_passthrough():
    print("\n[C] fmt=png：落盘仍是 PNG（透明通道不丢）")
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td)
        src = d / "a.png"
        Image.new("RGBA", (3000, 1000), (0, 0, 0, 0)).save(src)
        dst = d / "a_out.png"
        nw, nh = PR.thin_one(src, dst, max_edge=1024, fmt="png")
        check("PNG 魔数", dst.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", dst.name)
        check("长边缩到 1024", max(nw, nh) == 1024, "%dx%d" % (nw, nh))


def test_single_source():
    print("\n[D] 单一实现：两个调用方不许各自再写一份")
    src = (SCRIPTS / "wire_new_assets.py").read_text(encoding="utf-8")
    check("wire_new_assets 不再自带 thin()", "def thin(" not in src)
    check("wire_new_assets 用的是 thin_one", "thin_one(" in src)
    check("常量取自 prepare_refs，不是抄数字",
          "MAX_EDGE = DEFAULT_MAX_EDGE" in src and "QUALITY = DEFAULT_QUALITY" in src,
          "仍是硬编码")
    check("缩放只此一处实现",
          (SCRIPTS / "prepare_refs.py").read_text(encoding="utf-8").count("Image.LANCZOS") == 1,
          "prepare_refs 里出现多次 resize")
    check("wire_new_assets 里没有 resize", "resize(" not in src)


def main() -> int:
    print("=" * 78)
    print("thin_one：参考图瘦身的唯一实现点")
    print("=" * 78)
    test_scale_down()
    test_no_upscale()
    test_png_passthrough()
    test_single_source()

    bad = [r for r in RESULTS if not r[1]]
    print("\n" + "-" * 78)
    print("共 %d 项，失败 %d 项%s" % (len(RESULTS), len(bad), "" if not bad else "：" + ", ".join(b[0] for b in bad)))
    print("-" * 78)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
