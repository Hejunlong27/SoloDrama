#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_health.py —— 环境体检 / 一键修复的边界（离线、不装任何东西）

这个功能的风险不在「装不上」，而在**装上了却谎报成功**：
pip 退出码 0 只说明 pip 自己没崩，不说明这个解释器现在能 import；
`winget install ffmpeg` 更是经常「跑完了但 PATH 里还是没有」。

所以这里的断言几乎全在守边界：
  1. 每一项都必须带 `fix.kind`，且**能自动修的只允许 pip / mkdir / config 三类**；
  2. 修复动作的命令由服务端现算：pip 必须打在**引擎解释器**上，不许 `--user`
     （那会装到用户目录，引擎进程不一定读得到）、不许 `--break-system-packages`；
  3. 非自动项（winget / 外部 GUI / 填 Key）调 fix 必须被拒，**且不产生任何执行**；
  4. 修完必须复检：即使命令成功，只要复检不过就返回 ok=False；
  5. 修复留痕可读回。
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB))

from core import health, paths  # noqa: E402

FAILS = []
AUTO_KINDS = {"pip", "mkdir", "config"}
ALL_KINDS = AUTO_KINDS | {"manual", "page", "none"}


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("  [NG] %s" % msg)
    return cond


def section(name):
    print("\n[%s]" % name)


# ---------------------------------------------------------------------------
def test_shape():
    section("1. 清单形状：每项都要能说清「怎么修 / 能不能自动修」")
    d = health.collect()
    items = d.get("items") or []
    check(len(items) >= 10, "体检项应有 10 项以上，实际 %d" % len(items))
    check("counts" in d and "fail" in d["counts"], "缺少 counts.fail")
    check(d["interpreters"].get("engine"), "缺少引擎解释器信息")
    bad = []
    for it in items:
        for k in ("id", "group", "name", "required", "ok", "detail", "fix"):
            if k not in it:
                bad.append("%s 缺 %s" % (it.get("name"), k))
        fx = it.get("fix") or {}
        if fx.get("kind") not in ALL_KINDS:
            bad.append("%s 的 fix.kind=%r 不合法" % (it.get("name"), fx.get("kind")))
        if fx.get("kind") in AUTO_KINDS and not fx.get("auto"):
            bad.append("%s 是 %s 却没标 auto" % (it.get("name"), fx.get("kind")))
        if fx.get("kind") in ("manual", "page", "none") and fx.get("auto"):
            bad.append("%s 是 %s 却标了 auto（会骗用户点）" % (it.get("name"), fx.get("kind")))
    check(not bad, "；".join(bad[:6]))
    # id 不能重复：前端按 id 找项
    ids = [i["id"] for i in items]
    check(len(ids) == len(set(ids)), "id 有重复：%s" % [x for x in ids if ids.count(x) > 1][:4])
    print("     共 %d 项，可一键修复 %d 项，缺失 %d 项"
          % (len(items), d["counts"]["auto_fixable"], d["counts"]["fail"]))


def test_pip_command():
    section("2. pip 动作：只打引擎解释器、用锁定版本、不带 --user")
    d = health.collect()
    pip_items = [i for i in d["items"] if (i.get("fix") or {}).get("kind") == "pip"]
    check(bool(pip_items), "没找到 pip 类动作（Pillow/httpx 应各有一条）")
    pins = health._pins()
    for it in pip_items:
        fx = it["fix"]
        argv = fx.get("argv") or []
        check(argv[:1] == [paths.engine_python()],
              "%s 必须用引擎解释器执行，实际 %s" % (it["name"], argv[:1]))
        joined = " ".join(str(a) for a in argv)
        for bad in ("--user", "--break-system-packages", "--target"):
            check(bad not in joined, "%s 的命令里出现了 %s（会装到引擎读不到的地方）" % (it["name"], bad))
        dist = it["name"].lower()
        check(dist in pins, "requirements.txt 里应有 %s 的锁定版本" % it["name"])
        check(pins.get(dist, "") in joined,
              "%s 应装锁定版本 %s，实际命令 %s" % (it["name"], pins.get(dist), joined))
        check("复检" in (fx.get("note") or ""), "%s 的说明里要写清「装完会复检」" % it["name"])


def test_refuse_non_auto():
    section("3. 非自动项必须被拒，且不能借机执行任何命令")
    d = health.collect()
    manual = [i for i in d["items"] if (i.get("fix") or {}).get("kind") in ("manual", "page", "none")]
    check(bool(manual), "没有非自动项可测")
    for it in manual[:3]:
        r = health.fix(it["id"])
        check(r.get("ok") is False, "%s 是非自动项，fix 必须返回 False" % it["name"])
        check(r.get("reason") == "not_auto", "%s 应返回 reason=not_auto，实际 %r" % (it["name"], r.get("reason")))
        check(not r.get("lines"), "%s 被拒时不应有执行输出" % it["name"])
    r = health.fix("no.such.item")
    check(r.get("reason") == "unknown_item", "未知 id 应返回 unknown_item，实际 %r" % r.get("reason"))


def test_mkdir_fix():
    section("4. 建目录：真建 + 复检通过")
    tmp = Path(tempfile.mkdtemp()) / "var"
    real_var, real_log = paths.VAR_DIR, health.LOG_FILE
    paths.VAR_DIR = tmp
    health.LOG_FILE = tmp.parent / "health-fixes.jsonl"
    try:
        before = [i for i in health.collect()["items"] if i["id"] == "dir.var"][0]
        check(before["ok"] is False, "目录不存在时应判不通过")
        r = health.fix("dir.var")
        check(r["ok"] is True, "建目录后应 ok=True，实际 ok=%r detail=%s" % (r.get("ok"), r.get("detail")))
        check(r["verified"] is True, "建目录后复检应通过")
        check(tmp.is_dir(), "目录没真的建出来：%s" % tmp)
        check((tmp / ".write_probe").exists() is False, "探针文件应被清掉")
    finally:
        paths.VAR_DIR, health.LOG_FILE = real_var, real_log
        shutil.rmtree(tmp.parent, ignore_errors=True)


def test_config_fix():
    section("5. 失效的 python 配置：清掉并备份，不动其它键")
    tmp = Path(tempfile.mkdtemp()) / "settings.json"
    tmp.write_text(json.dumps({"python": "D:/no/such/python.exe", "other": 1}), encoding="utf-8")
    real = paths.SETTINGS_FILE
    paths.SETTINGS_FILE = tmp
    try:
        it = [i for i in health.collect()["items"] if i["id"] == "rt.engine_py"][0]
        check(it["ok"] is False, "配置指向空文件时应判不通过")
        check(it["fix"].get("auto") is True, "这一项应可一键修（清掉失效键）")
        r = health.fix("rt.engine_py")
        check(r["ok"] is True and r["verified"] is True, "清理后应通过，实际 %r" % r.get("detail"))
        left = json.loads(tmp.read_text(encoding="utf-8"))
        check("python" not in left, "python 键应被移除，实际 %s" % left)
        check(left.get("other") == 1, "其它键必须原样保留，实际 %s" % left)
        baks = list(tmp.parent.glob("settings.json.bak_*"))
        check(bool(baks), "改写配置前必须备份")
    finally:
        paths.SETTINGS_FILE = real
        shutil.rmtree(tmp.parent, ignore_errors=True)


def test_verify_is_honest():
    section("6. 复检才是结论：命令成功但项仍不过 → ok 必须是 False")
    tmp = Path(tempfile.mkdtemp())
    fake = {"ok": False, "items": [{
        "id": "dep.fake", "group": "Python 依赖", "name": "Fake", "required": True,
        "ok": False, "detail": "未装", "hint": "", "source": "test",
        "fix": {"kind": "pip", "auto": True, "label": "", "cmd": "pip install fake",
                "note": "装完会复检", "page": "", "argv": ["x"]},
    }], "counts": {"total": 1, "fail": 1, "warn": 0, "auto_fixable": 1},
        "interpreters": {"engine": "x", "server": "x"}, "checked_at": 0, "elapsed": 0}

    real_collect, real_fixers, real_log = health.collect, dict(health._FIXERS), health.LOG_FILE
    health.LOG_FILE = tmp / "log.jsonl"
    health.collect = lambda ws=None: json.loads(json.dumps(fake))     # 永远不过
    health._FIXERS = dict(real_fixers)
    health._FIXERS["pip"] = lambda item: {"ok": True, "rc": 0, "lines": ["Successfully installed"], "cmd": "pip install fake"}
    try:
        r = health.fix("dep.fake")
        check(r["ok"] is False, "复检不过时 ok 必须是 False（不能拿退出码 0 当成功）")
        check(r["verified"] is False, "verified 必须是 False")
        check("复检" in (r.get("detail") or ""), "应说清「命令跑完但复检没过」，实际 %r" % r.get("detail"))
    finally:
        health.collect, health._FIXERS, health.LOG_FILE = real_collect, real_fixers, real_log
        shutil.rmtree(tmp, ignore_errors=True)


def test_history():
    section("7. 修复留痕可读回")
    tmp = Path(tempfile.mkdtemp())
    real_log = health.LOG_FILE
    health.LOG_FILE = tmp / "health-fixes.jsonl"
    try:
        health.LOG_FILE.write_text(
            json.dumps({"at": "2026-10-29T01:00:00", "id": "dep.pillow", "name": "Pillow",
                        "kind": "pip", "cmd": "pip install Pillow", "rc": 0,
                        "ok": True, "verified": True, "elapsed": 3}, ensure_ascii=False) + "\n",
            encoding="utf-8")
        h = health.history(10)
        check(h["total"] == 1, "应读到 1 条记录，实际 %s" % h["total"])
        check(h["items"][0]["verified"] is True, "记录里的 verified 应保留")
        check(h["items"][0]["name"] == "Pillow", "记录里的 name 应保留")
    finally:
        health.LOG_FILE = real_log
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    for fn in (test_shape, test_pip_command, test_refuse_non_auto, test_mkdir_fix,
               test_config_fix, test_verify_is_honest, test_history):
        fn()
    print("\n" + "-" * 62)
    if FAILS:
        print("[FAIL] %d 项未通过" % len(FAILS))
        sys.exit(1)
    print("[OK] 环境体检 / 一键修复边界全部通过")
