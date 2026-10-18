#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""离线测试：资产迁移到 04-资产（migrate_assets）

零网络、零计费、零第三方依赖。
    python stages/production/scripts/tests/test_migrate_assets.py
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
SCRIPT = SCRIPTS / "migrate_assets.py"
sys.path.insert(0, str(SCRIPTS.parent.parent))          # stages/（_layout.py）

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))


def png(path: pathlib.Path, w=64, h=64):
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    chunk = b"IHDR" + ihdr
    body = struct.pack(">I", len(ihdr)) + chunk + struct.pack(">I", binascii.crc32(chunk) & 0xFFFFFFFF)
    iend = b"\x00\x00\x00\x00IEND" + struct.pack(">I", binascii.crc32(b"IEND") & 0xFFFFFFFF)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + body + iend)


def build(ws: pathlib.Path):
    """旧项目：layout.json 无 assets_rel，资产在 <out>/assets（out_rel=output）。"""
    (ws / "video-pipeline" / "output").mkdir(parents=True, exist_ok=True)
    (ws / "video-pipeline" / "data").mkdir(parents=True, exist_ok=True)
    (ws / "layout.json").write_text(json.dumps({
        "layout_version": 1, "engine_root": "video-pipeline", "stages": {},
        "data_rel": "data", "out_rel": "output"}), encoding="utf-8", newline="\n")
    legacy = ws / "video-pipeline" / "output" / "assets"
    data = ws / "video-pipeline" / "data"
    files = {"characters/char_01_A.png": "char_01", "scenes/scene_01_B.png": "scene_01"}
    for rel in files:
        p = legacy / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        png(p)
    (data / "char_assets_manifest.json").write_text(json.dumps({
        "_note": "t", "items": [{"kind": "char", "key": "char_01",
                                 "files": [{"file": str(legacy / "characters" / "char_01_A.png"),
                                            "role": "asset"}]}]}, ensure_ascii=False),
        encoding="utf-8", newline="\n")
    (data / "scene_assets_manifest.json").write_text(json.dumps({
        "_note": "t", "items": [{"kind": "scene", "key": "scene_01",
                                 "files": [{"file": str(legacy / "scenes" / "scene_01_B.png"),
                                            "role": "asset"}]}]}, ensure_ascii=False),
        encoding="utf-8", newline="\n")
    return legacy, data


def run(ws: pathlib.Path, *args):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run([sys.executable, str(SCRIPT), "--workspace", str(ws), *args],
                       capture_output=True, text=True, encoding="utf-8", env=env)
    return p.returncode, p.stdout + p.stderr


def main() -> int:
    import _layout as L
    tmp = tempfile.mkdtemp(prefix="sd_migrate_")
    try:
        ws = pathlib.Path(tmp) / "proj"
        legacy, data = build(ws)

        # ---- 1. 迁移前：assets_dir 走旧位置（零迁移兼容） ----
        check("迁移前 assets_dir() = 旧位置", L.assets_dir(ws) == legacy, str(L.assets_dir(ws)))

        # ---- 2. 干跑不改盘 ----
        rc, out = run(ws)
        check("干跑通过（退出码 0）", rc == 0, out[-200:])
        check("干跑不移动文件", (legacy / "characters" / "char_01_A.png").is_file())
        check("干跑不改 manifest",
              json.loads((data / "char_assets_manifest.json").read_text(encoding="utf-8-sig"))
              ["items"][0]["files"][0]["file"].startswith(str(legacy)))
        check("干跑报出待迁移 2 个", "待迁移 : 2" in out, out[-300:])

        # ---- 3. 真搬 ----
        rc, out = run(ws, "--apply")
        check("真搬（退出码 0）", rc == 0, out[-300:])
        check("图片已落 04-资产", (ws / "04-资产" / "characters" / "char_01_A.png").is_file()
              and (ws / "04-资产" / "scenes" / "scene_01_B.png").is_file())
        check("旧位置已清空", not (legacy / "characters" / "char_01_A.png").exists())
        man_file = json.loads((data / "char_assets_manifest.json").read_text(encoding="utf-8-sig"))["items"][0]["files"][0]["file"]
        check("manifest 绝对路径已改写",
              "04-资产" in man_file.replace("\\", "/") and str(legacy) not in man_file, man_file)
        check("layout.json 补上 assets_rel",
              json.loads((ws / "layout.json").read_text(encoding="utf-8-sig")).get("assets_rel") == "../04-资产")
        check("迁移后 assets_dir() = 04-资产",
              L.assets_dir(ws) == ws / "04-资产", str(L.assets_dir(ws)))
        check("已建备份", list((ws / "video-pipeline" / "output").glob("_assets_backup_*")))
        check("assets_dir_note 不再提示", L.assets_dir_note(ws) == "", L.assets_dir_note(ws)[:80])

        # ---- 4. 幂等：再跑一次无待迁移 ----
        rc, out = run(ws)
        check("幂等（无待迁移，退出码 0）", rc == 0 and "无需迁移" in out, out[-200:])

        # ---- 5. --copy 保留旧位置 ----
        ws2 = pathlib.Path(tmp) / "proj2"
        legacy2, _d2 = build(ws2)
        rc, out = run(ws2, "--apply", "--copy", "--no-backup")
        check("--copy 保留旧位置且新位置有文件", rc == 0
              and (legacy2 / "characters" / "char_01_A.png").is_file()
              and (ws2 / "04-资产" / "characters" / "char_01_A.png").is_file(), out[-200:])

        # ---- 6. 无 layout.json → 明确拒绝 ----
        ws3 = pathlib.Path(tmp) / "old"
        (ws3 / "video-pipeline" / "output" / "assets" / "characters").mkdir(parents=True)
        png(ws3 / "video-pipeline" / "output" / "assets" / "characters" / "x.png")
        rc, out = run(ws3, "--apply")
        check("旧布局（无 layout.json）被拒绝", rc != 0 and "没有 layout.json" in out, out[-200:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("=" * 62)
    print("migrate_assets 离线测试")
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
