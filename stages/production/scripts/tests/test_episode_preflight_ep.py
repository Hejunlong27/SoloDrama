#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_episode_preflight_ep.py —— 集级前置体检的「集号」口径（离线）

两件事，都是真实踩过的：

  A. **集号写法**：`--ep ep01` 与 `--ep 1` 都要认。
     原来只 `int(e)`，Studio 里选出来的是 `ep01` → `ValueError: invalid literal
     for int() with base 10: 'ep01'`，而界面上那个按钮叫「集级前置体检」。
     （同类问题在 `script_continuity` 也犯过一次。）

  B. **镜头 id 归属**：`shot_001` 这种**不带集号前缀**的 shot_id 必须算进本集。
     原来严格要求 `ep01_` 前缀，于是真实项目恒报「段数 0 / 没有缺口」——
     看起来一切正常，其实一个镜头都没查。那比报错更危险。
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
SCRIPTS = HERE.parent
sys.path.insert(0, str(SCRIPTS))

import episode_preflight as P   # noqa: E402

FAILS = []


def check(cond, msg):
    print(("  [PASS] " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAILS.append(msg)


def test_belongs():
    print("\n[A] 镜头归属于哪一集")
    check(P._belongs("shot_001", "ep01") is True, "无集号的 shot_001 算任何一集")
    check(P._belongs("ep01_shot_01", "ep01") is True, "ep01_shot_01 → ep01")
    check(P._belongs("ep02_shot_01", "ep01") is False, "ep02_shot_01 不算 ep01")
    check(P._belongs("shot_ep02_01", "ep02") is True, "shot_ep02_01 → ep02")
    check(P._belongs("", "ep01") is False, "空 id 不算")
    check(P._belongs(None, "ep01") is False, "None 不算")


def test_analyze_counts():
    print("\n[B] 段数统计（analyze）")
    shots = [{"shot_id": "shot_%03d" % i, "character_refs": []} for i in range(1, 4)]
    prompts = {}
    rep = P.analyze("ep01", shots, prompts, {}, {})
    check(rep["n"] == 3, "无前缀的 3 个镜头都算进 ep01，实际 %d" % rep["n"])

    mixed = [{"shot_id": "ep01_shot_01"}, {"shot_id": "ep02_shot_01"}]
    rep2 = P.analyze("ep01", mixed, {}, {}, {})
    check(rep2["n"] == 1, "带前缀时只收本集，实际 %d" % rep2["n"])


def test_cli_accepts_ep_names():
    print("\n[C] 命令行同时接受 ep01 与 1")
    fx = (HERE / "fixtures" / "mini_drama").resolve()
    env = {"SOLODRAMA_WORKSPACE": str(fx), "PATH": "/usr/bin:/bin"}
    for arg in ("ep01", "1"):
        r = subprocess.run([sys.executable, str(SCRIPTS / "episode_preflight.py"), arg, "--json"],
                           capture_output=True, text=True, env={**env, "SYSTEMROOT": "C:\\Windows"})
        ok = r.returncode == 0
        detail = ""
        if ok:
            try:
                body = r.stdout[r.stdout.index("{"):]
                detail = "eps=%d" % len(json.loads(body).get("eps") or [])
            except (ValueError, json.JSONDecodeError):
                ok, detail = False, "输出不是 JSON"
        else:
            detail = (r.stdout or r.stderr).strip().splitlines()[-1][:90] if (r.stdout or r.stderr) else ""
        check(ok, "`%s` 能跑通（%s）" % (arg, detail))


def main():
    test_belongs()
    test_analyze_counts()
    test_cli_accepts_ep_names()
    print("\n" + "=" * 70)
    if FAILS:
        print("[FAIL] %d 项未通过" % len(FAILS))
        return 1
    print("[OK] 前置体检集号口径全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
