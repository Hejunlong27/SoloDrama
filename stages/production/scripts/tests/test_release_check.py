#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""离线测试：发行资料齐全度门禁（release_check）

零网络、零计费、零第三方依赖。
    python stages/production/scripts/tests/test_release_check.py

夹具说明：为不引入 Pillow，测试用「合法的 PNG/JPEG 文件头」（含正确 IHDR/SOF0 与 CRC）
构造图片，因为 release_check 只从文件头读尺寸、不解码像素。
"""
from __future__ import annotations

import binascii
import json
import os
import pathlib
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
SCRIPTS = HERE.parent
SCRIPT = SCRIPTS / "release_check.py"

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))


# ---------------------------------------------------------------- 图片夹具
def png(path: pathlib.Path, w: int, h: int) -> None:
    """写一个带合法 IHDR（含 CRC）的 PNG 头 + IEND。"""
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    chunk = b"IHDR" + ihdr
    body = struct.pack(">I", len(ihdr)) + chunk + struct.pack(">I", binascii.crc32(chunk) & 0xFFFFFFFF)
    iend = b"\x00\x00\x00\x00IEND" + struct.pack(">I", binascii.crc32(b"IEND") & 0xFFFFFFFF)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + body + iend)


def jpeg(path: pathlib.Path, w: int, h: int) -> None:
    """写一个带 JFIF APP0 + SOF0（含真实宽高）的最小 JPEG 头。"""
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof0 = b"\xff\xc0" + struct.pack(">H", 17) + b"\x08" + struct.pack(">HH", h, w) + b"\x03" + b"\x01\x11\x00" * 3
    path.write_bytes(b"\xff\xd8" + app0 + sof0 + b"\xff\xd9")


def run(ws: pathlib.Path):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"        # 子进程管道不走 GBK，否则 JSON 解析失败
    p = subprocess.run([sys.executable, str(SCRIPT), "--workspace", str(ws), "--json"],
                       capture_output=True, text=True, encoding="utf-8", env=env)
    try:
        return p.returncode, json.loads(p.stdout)
    except (json.JSONDecodeError, ValueError):
        return p.returncode, {"stdout": p.stdout, "stderr": p.stderr}


# ---------------------------------------------------------------- 场景
def build_full(ws: pathlib.Path) -> pathlib.Path:
    """造一套齐备的发行资料（含发布版成片 EpisodeNN.mp4）。"""
    rel = ws / "09-发行"
    (rel / "封面").mkdir(parents=True, exist_ok=True)
    (rel / "文案").mkdir(parents=True, exist_ok=True)
    (rel / "版权资料").mkdir(parents=True, exist_ok=True)
    (rel / "剧集").mkdir(parents=True, exist_ok=True)
    for i in (1, 2, 3):                                   # 发布版：严格 EpisodeNN.mp4
        (rel / "剧集" / ("Episode%02d.mp4" % i)).write_bytes(b"\x00" * 64)
    png(rel / "封面" / "cover_9x16.png", 1080, 1920)
    png(rel / "封面" / "cover_3x4.png", 900, 1200)
    jpeg(rel / "封面" / "cover_16x9.jpg", 1920, 1080)
    for n in (1, 2, 3, 4):
        png(rel / "版权资料" / ("ai-process-%02d-step.png" % n), 1600, 900)
        png(rel / "版权资料" / ("source-file-%02d-info.png" % n), 1600, 900)
    (rel / "版权资料" / "版权资料清单.md").write_text("# 清单\n", encoding="utf-8", newline="\n")
    (rel / "文案" / "copy.json").write_text(
        json.dumps({"title": "离婚后我成了首富", "tags": ["逆袭"]}, ensure_ascii=False),
        encoding="utf-8", newline="\n")
    (rel / "发布清单.md").write_text("# 发布清单\n", encoding="utf-8", newline="\n")
    # ★ 2026-10-30：画面侧合规记录是**硬门禁**（release_export 先拦、release_check 再举证），
    #   所以齐备的工作区必须带一份 ok 记录，否则「资料齐」也会被判下游未完成。
    comp = ws / "08-合规"
    comp.mkdir(parents=True, exist_ok=True)
    (comp / "画面合规_20261030_120000.json").write_text(
        json.dumps({"at": "2026-10-30T12:00:00+08:00", "target": "1080x1920",
                    "verdict": "ok", "results": []}, ensure_ascii=False),
        encoding="utf-8", newline="\n")
    (ws / "layout.json").write_text(
        json.dumps({"layout_version": 1, "engine_root": "video-pipeline", "stages": {}, "data_rel": "data", "out_rel": "output"}),
        encoding="utf-8", newline="\n")
    return rel


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="sd_release_")
    try:
        # ---- 1. 空工作区：应拦下 ----
        ws1 = pathlib.Path(tmp) / "empty"
        ws1.mkdir(parents=True)
        rc, out = run(ws1)
        check("空工作区被拦下（退出码 2）", rc == 2, "rc=%s" % rc)
        check("报缺发行目录", any("发行目录不存在" in x for x in out.get("fails", [])), str(out)[:200])

        # ---- 2. 齐备：应通过 ----
        ws2 = pathlib.Path(tmp) / "full"
        ws2.mkdir(parents=True)
        build_full(ws2)
        rc, out = run(ws2)
        check("齐备发行资料通过（退出码 0）", rc == 0, "rc=%s fails=%s" % (rc, out.get("fails")))
        check("封面识别到 3 档", set(out.get("found", {}).get("covers", [])) >= {"9x16", "3x4", "16x9"},
              str(out.get("found")))
        check("版权资料识别 4 + 4", out.get("found", {}).get("ai_process") == [1, 2, 3, 4]
              and out.get("found", {}).get("source_file") == [1, 2, 3, 4], str(out.get("found")))

        # ---- 3. 缺一张 source-file-03 ----
        ws3 = pathlib.Path(tmp) / "miss_src"
        ws3.mkdir(parents=True)
        rel3 = build_full(ws3)
        (rel3 / "版权资料" / "source-file-03-info.png").unlink()
        rc, out = run(ws3)
        check("缺 source-file-03 被拦下", rc == 2 and any("source-file" in x for x in out.get("fails", [])),
              str(out.get("fails")))

        # ---- 4. 封面比例与档位不符 ----
        ws4 = pathlib.Path(tmp) / "bad_ratio"
        ws4.mkdir(parents=True)
        rel4 = build_full(ws4)
        (rel4 / "封面" / "cover_9x16.png").unlink()
        png(rel4 / "封面" / "cover_9x16.png", 1200, 1200)     # 1:1 冒充 9:16
        rc, out = run(ws4)
        check("封面比例不符被拦下", rc == 2 and any("比例与档位不符" in x for x in out.get("fails", [])),
              str(out.get("fails")))

        # ---- 5. 版权资料长边过小 ----
        ws5 = pathlib.Path(tmp) / "small_img"
        ws5.mkdir(parents=True)
        rel5 = build_full(ws5)
        (rel5 / "版权资料" / "ai-process-02-step.png").unlink()
        png(rel5 / "版权资料" / "ai-process-02-step.png", 800, 500)   # 长边 800 < 1200
        rc, out = run(ws5)
        check("版权资料长边过小被拦下",
              rc == 2 and any("长边仅" in x for x in out.get("fails", [])), str(out.get("fails")))

        # ---- 6. 缺文案 / 发布清单 / 版权清单 ----
        ws6 = pathlib.Path(tmp) / "miss_docs"
        ws6.mkdir(parents=True)
        rel6 = build_full(ws6)
        (rel6 / "文案" / "copy.json").unlink()
        (rel6 / "发布清单.md").unlink()
        (rel6 / "版权资料" / "版权资料清单.md").unlink()
        rc, out = run(ws6)
        fs = " ".join(out.get("fails", []))
        check("缺文案/发布清单/版权清单各自被拦",
              rc == 2 and "缺文案" in fs and "发布清单" in fs and "版权资料清单" in fs, fs)

        # ---- 7. 仅 JPEG 形式也能读尺寸（cover_9x16 用 jpg） ----
        ws7 = pathlib.Path(tmp) / "jpg_only"
        ws7.mkdir(parents=True)
        rel7 = build_full(ws7)
        (rel7 / "封面" / "cover_9x16.png").unlink()
        jpeg(rel7 / "封面" / "cover_9x16.jpg", 1080, 1920)
        rc, out = run(ws7)
        check("JPEG 头可解析且比例通过", rc == 0, "rc=%s fails=%s" % (rc, out.get("fails")))

        # ---- 8. manifest 落痕 ----
        check("落痕 release-manifest.json", (rel7 / "release-manifest.json").is_file())

        # ---- 9. 发布版命名：杂名被拦 ----
        ws9 = pathlib.Path(tmp) / "bad_name"
        ws9.mkdir(parents=True)
        rel9 = build_full(ws9)
        for f in (rel9 / "剧集").iterdir():
            f.unlink()
        (rel9 / "剧集" / "EP01_1080p_ES.mp4").write_bytes(b"\x00" * 64)      # 即兴命名
        (rel9 / "剧集" / "ep02_拼接_11段_672x1216.mp4").write_bytes(b"\x00" * 64)
        rc, out = run(ws9)
        check("发布版杂名被拦下", rc == 2 and any("命名不符合规范" in x for x in out.get("fails", [])),
              str(out.get("fails"))[:200])

        # ---- 10. 缺发布版成片被拦 ----
        ws10 = pathlib.Path(tmp) / "no_episodes"
        ws10.mkdir(parents=True)
        rel10 = build_full(ws10)
        for f in (rel10 / "剧集").iterdir():
            f.unlink()
        rc, out = run(ws10)
        check("缺发布版成片被拦下", rc == 2 and any("缺发布版成片" in x for x in out.get("fails", [])),
              str(out.get("fails"))[:200])

        # ---- 11. 集号不连续 → 只告警不拦 ----
        ws11 = pathlib.Path(tmp) / "gap"
        ws11.mkdir(parents=True)
        rel11 = build_full(ws11)
        (rel11 / "剧集" / "Episode02.mp4").unlink()
        rc, out = run(ws11)
        check("集号不连续只告警",
              rc == 0 and any("集号不连续" in x for x in out.get("warns", [])), str(out.get("warns"))[:200])

        # ---- 12. EpisodeNN 命名被正确识别 ----
        rc, out = run(ws2)
        check("发布版 EpisodeNN 被识别",
              out.get("found", {}).get("episodes") == ["Episode01.mp4", "Episode02.mp4", "Episode03.mp4"],
              str(out.get("found")))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("=" * 62)
    print("release_check 离线测试")
    print("=" * 62)
    n_fail = 0
    for name, ok, detail in RESULTS:
        print("  %s %s%s" % ("[OK]  " if ok else "[FAIL]", name, "" if ok else "  <- %s" % detail))
        n_fail += 0 if ok else 1
    print("-" * 62)
    print("共 %d 例，通过 %d，失败 %d" % (len(RESULTS), len(RESULTS) - n_fail, n_fail))
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
