"""tests/test_ref_ratio.py —— 参考图比例必须与出片画幅匹配

来源：2026-11-05 云端实测反馈（仙宫云 4090 镜像）。
`ref_image_size='match'` 只保证**参考图自身**不变形，不保证它与目标画幅匹配。
3:4 参考 → 9:16 输出，纵向拉伸 22%（脸型明显变长）；16:9 参考更糟（横向压 44%）。
这种变形会沿着「出图 → 当参考 → 出片」一路传下去，事后只能重出全套资产。

所以这里钉三件事：
  1. 尺寸解析必须是纯标准库（云端只有 ComfyUI 环境，没有 Pillow）；
  2. 偏差算的是**目标画幅**的比例，不是两个数的差；
  3. 只告警不抛错 —— 方图道具做竖幅特写是合理用法。
"""
from __future__ import annotations

import pathlib
import struct
import sys
import zlib

import pytest

HERE = pathlib.Path(__file__).resolve().parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "stages"))

import comfy_local_video as V            # noqa: E402


def _png(path: pathlib.Path, w: int, h: int) -> pathlib.Path:
    """写一个最小的合法 PNG（1×1 像素数据，但 IHDR 里声明目标宽高）。

    尺寸校验只读头部，所以像素内容不重要；但文件必须是结构合法的 PNG。
    """
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    raw = b"\x00" + b"\x00\x00\x00"          # 一个 RGB 像素
    idat = zlib.compress(raw)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                     + chunk(b"IDAT", idat) + chunk(b"IEND", b""))
    return path


def _jpeg(path: pathlib.Path, w: int, h: int) -> pathlib.Path:
    """写一个只有 SOI + SOF0 + EOI 的 JPEG 骨架（足够让尺寸解析读到宽高）。"""
    sof = (b"\xff\xc0" + struct.pack(">H", 17) + b"\x08"
           + struct.pack(">H", h) + struct.pack(">H", w)
           + b"\x03" + b"\x01\x11\x00" + b"\x02\x11\x01" + b"\x03\x11\x01")
    path.write_bytes(b"\xff\xd8" + sof + b"\xff\xd9")
    return path


def test_png_size(tmp_path) -> None:
    f = _png(tmp_path / "a.png", 1080, 1920)
    assert V._image_size(str(f)) == (1080, 1920)


def test_jpeg_size(tmp_path) -> None:
    f = _jpeg(tmp_path / "a.jpg", 896, 1184)
    assert V._image_size(str(f)) == (896, 1184)


def test_non_image_returns_none(tmp_path) -> None:
    f = tmp_path / "x.bin"
    f.write_bytes(b"not an image at all")
    assert V._image_size(str(f)) is None
    assert V._image_size(str(tmp_path / "missing.png")) is None


def test_same_ratio_no_warning(tmp_path) -> None:
    f = _png(tmp_path / "ok.png", 1080, 1920)          # 0.5625 = 9:16
    assert V.check_ref_ratio([str(f)], "9:16 (Portrait Widescreen)") == []


def test_landscape_ref_warns(tmp_path) -> None:
    """16:9 参考喂 9:16 输出 —— 这是本项目以前默认配置踩的坑。"""
    f = _png(tmp_path / "wide.png", 1920, 1080)        # 1.778 vs 0.5625
    lines = V.check_ref_ratio([str(f)], "9:16 (Portrait Widescreen)")
    assert len(lines) == 1
    assert "偏差" in lines[0] and "拉伸" in lines[0]


def test_deviation_is_relative_to_target(tmp_path) -> None:
    """偏差按目标比例算，不是两个比例的差。

    1080×2160（0.5）vs 9:16（0.5625）：|0.5-0.5625|/0.5625 = 11.1% → 应当告警。
    若错算成绝对值 0.0625（6.25%），仍会告警，所以再取一个刚好在边界内的例子区分：
    1000×1800（0.5556）vs 0.5625 → 1.2%，不告警。
    """
    near = _png(tmp_path / "near.png", 1000, 1800)
    assert V.check_ref_ratio([str(near)], "9:16 (Portrait Widescreen)") == []
    off = _png(tmp_path / "off.png", 1080, 2160)
    assert len(V.check_ref_ratio([str(off)], "9:16 (Portrait Widescreen)")) == 1


def test_no_aspect_means_no_check(tmp_path) -> None:
    """没指定画幅（沿用工作流默认）时不能瞎猜，直接跳过。"""
    f = _png(tmp_path / "wide.png", 1920, 1080)
    assert V.check_ref_ratio([str(f)], "") == []
    assert V.check_ref_ratio([str(f)], "工作流默认") == []


def test_multiple_refs_report_each(tmp_path) -> None:
    a = _png(tmp_path / "a.png", 1920, 1080)
    b = _png(tmp_path / "b.png", 1080, 1920)
    lines = V.check_ref_ratio([str(a), str(b)], "9:16")
    assert len(lines) == 1                 # 只报不合规的那张


def test_square_prop_tolerated(tmp_path) -> None:
    """1:1 道具当 9:16 参考：偏差 78% —— 会告警，但**不能抛异常**（不阻断流水线）。"""
    f = _png(tmp_path / "prop.png", 1440, 1440)
    lines = V.check_ref_ratio([str(f)], "9:16 (Portrait Widescreen)")
    assert len(lines) == 1
