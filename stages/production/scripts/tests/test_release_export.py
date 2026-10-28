#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""离线测试：发布版成片导出命名（release_export）

零网络、零计费、零第三方依赖。
    python stages/production/scripts/tests/test_release_export.py
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
SCRIPTS = HERE.parent
SCRIPT = SCRIPTS / "release_export.py"

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))


def run(ws: pathlib.Path, *args):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["SOLODRAMA_WORKSPACE"] = str(ws)
    p = subprocess.run([sys.executable, str(SCRIPT), "--workspace", str(ws), "--json", *args],
                       capture_output=True, text=True, encoding="utf-8", env=env)
    try:
        return p.returncode, json.loads(p.stdout)
    except (json.JSONDecodeError, ValueError):
        return p.returncode, {"stdout": p.stdout, "stderr": p.stderr}


def build(ws: pathlib.Path) -> None:
    """造一个带成片的剧工作区（含发布版 / subs 两种来源 + 一个杂项文件）。"""
    (ws / "video-pipeline").mkdir(parents=True, exist_ok=True)
    (ws / "layout.json").write_text(json.dumps(
        {"layout_version": 1, "engine_root": "video-pipeline", "stages": {},
         "data_rel": "../06-提示词", "out_rel": "../07-成片", "assets_rel": "../04-资产"}),
        encoding="utf-8", newline="\n")
    pub = ws / "07-成片" / "发布版1080p_es"
    pub.mkdir(parents=True, exist_ok=True)
    for i in (1, 2, 3):
        (pub / ("EP%02d_1080p_ES.mp4" % i)).write_bytes(b"\x00" * 32)
    subs = ws / "07-成片" / "subs"
    (subs / "ep04").mkdir(parents=True, exist_ok=True)
    (subs / "ep04" / "ep04_subbed.mp4").write_bytes(b"\x00" * 32)
    (subs / "ep05").mkdir(parents=True, exist_ok=True)
    (subs / "ep05" / "ep05_master_2k.mp4").write_bytes(b"\x00" * 32)
    (pub / "readme.txt").write_text("not a video\n", encoding="utf-8", newline="\n")


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="sd_rel_exp_")
    try:
        # ---- 1. 自动探测来源 + 干跑不改盘 ----
        ws = pathlib.Path(tmp) / "proj"
        build(ws)
        rc, out = run(ws, "--all")
        check("干跑通过（退出码 0）", rc == 0, "rc=%s fails=%s" % (rc, out.get("fails")))
        check("自动探测到发布版目录（且在候选首位）",
              (out.get("src_dirs") or [""])[0].endswith("发布版1080p_es"), out.get("src_dirs"))
        names = [pathlib.Path(p["dst"]).name for p in out.get("plans", [])]
        check("干跑不改盘（剧集目录未创建）", not (ws / "09-发行" / "剧集").exists(), str(names))
        check("命名映射为 EpisodeNN", names[:3] == ["Episode01.mp4", "Episode02.mp4", "Episode03.mp4"], str(names))

        # ---- 2. 真写 ----
        rc, out = run(ws, "--all", "--apply")
        d = ws / "09-发行" / "剧集"
        got = sorted(f.name for f in d.glob("*.mp4"))
        check("真写产出 EpisodeNN.mp4", rc == 0 and got == ["Episode%02d.mp4" % i for i in (1, 2, 3, 4, 5)],
              "rc=%s got=%s" % (rc, got))
        check("写剧集清单.json", (d / "剧集清单.json").is_file())

        # ---- 3. 目标目录里的杂名被拦 ----
        (d / "EP09_1080p_ES.mp4").write_bytes(b"\x00" * 32)
        rc, out = run(ws, "--all")
        check("目标目录杂名被拦下", rc == 2 and any("不符合命名" in x for x in out.get("fails", [])),
              str(out.get("fails"))[:200])
        (d / "EP09_1080p_ES.mp4").unlink()

        # ---- 4. --ep 指定 + 缺集 → 退出码 2 ----
        rc, out = run(ws, "--ep", "ep01")
        check("--ep 单集导出", rc == 0 and len(out.get("plans", [])) == 1, str(out.get("plans")))
        rc, out = run(ws, "--ep", "ep99")
        check("--ep 集不存在 → 退出码 2", rc == 2 and any("找不到第 99 集" in x for x in out.get("fails", [])),
              str(out.get("fails"))[:200])

        # ---- 5. 未识别集号的来源目录 → 拦 ----
        ws2 = pathlib.Path(tmp) / "proj2"
        build(ws2)
        junk = ws2 / "07-成片" / "junk"
        junk.mkdir(parents=True, exist_ok=True)
        (junk / "最终版.mp4").write_bytes(b"\x00" * 32)
        rc, out = run(ws2, "--from", str(junk), "--all")
        check("来源目录无可识别集号 → 拦", rc == 2 and any("没有任何可识别集号" in x for x in out.get("fails", [])),
              str(out.get("fails"))[:200])

        # ---- 6. --link 硬链接 ----
        ws3 = pathlib.Path(tmp) / "proj3"
        build(ws3)
        rc, out = run(ws3, "--all", "--apply", "--link")
        a = ws3 / "07-成片" / "发布版1080p_es" / "EP01_1080p_ES.mp4"
        b = ws3 / "09-发行" / "剧集" / "Episode01.mp4"
        same = a.is_file() and b.is_file() and os.path.samefile(a, b)
        check("--link 走硬链接（同一文件）", rc == 0 and same, "rc=%s same=%s" % (rc, same))

        # ---- 7. 命名函数（三位数、超两位） ----
        sys.path.insert(0, str(SCRIPTS.parent.parent))     # stages/（_layout.py 所在）
        import _layout as L
        check("Episode01 / Episode40 命名",
              L.release_episode_name(1) == "Episode01.mp4" and L.release_episode_name(40) == "Episode40.mp4",
              L.release_episode_name(40))
        check("≥100 集自动加位", L.release_episode_name(100) == "Episode100.mp4", L.release_episode_name(100))

        # ---- 8. 放大母版正名优先（★ 2026-10-22） ----
        # 旧名 `_master_2k` 把 1080P 写成 2k；两者同时存在时必须选带真实分辨率的那份。
        ws4 = pathlib.Path(tmp) / "proj4"
        (ws4 / "07-成片" / "subs" / "ep07").mkdir(parents=True, exist_ok=True)
        d7 = ws4 / "07-成片" / "subs" / "ep07"
        (d7 / "ep07_master.mp4").write_bytes(b"\x00" * 32)
        (d7 / "ep07_master_2k.mp4").write_bytes(b"\x00" * 32)
        (d7 / "ep07_master_1080x1920.mp4").write_bytes(b"\x00" * 32)
        rc, out = run(ws4, "--all")
        src = next((p["src"] for p in out.get("plans", []) if "Episode07" in p["dst"]), "")
        check("放大母版优先取带分辨率的新名（_master_1080x1920）",
              "1080x1920" in src, src)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("=" * 62)
    print("release_export 离线测试")
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
