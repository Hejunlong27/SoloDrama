#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_new_actions.py —— 三个「从命令行搬进界面」的动作，契约不能漂（离线）

背景：这三件事原来在页面上都只写着「未开放 / 用命令行」。
接进界面时必须把**危险级别与参数拼装**钉住，否则以后改命令表很容易变成：

  · 把写盘动作标成 danger=READ（点了就直接覆盖，没有确认单）
  · 把计费动作标成 free（用户以为免费）
  · 参数名改了但视图没跟（点了报「缺少必填参数」）

被钉住的三个：
  1. `release.export` —— 导出发布版（写 09-发行/剧集/EpisodeNN.mp4）
  2. `refs.apply`     —— 参考图瘦身（写 06-提示词/refs_h3/，原图不动）
  3. `video.resume`   —— 分镜续跑（★计费，复用批次只补失败段）
"""
from __future__ import annotations

import sys
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB))

from core import commands as C   # noqa: E402

FAILS = []


def check(cond, msg):
    print(("  [PASS] " if cond else "  [FAIL] ") + msg)
    if not cond:
        FAILS.append(msg)


def argv_of(cid, values, ws="D:/proj/x"):
    cmd = C.get(cid)
    v = cmd.validate(values)
    return v, [str(x).replace("\\", "/") for x in cmd.build_argv(v["values"], ws=ws)]


def test_release_export():
    print("\n[1] release.export —— 写盘、免费、命名 EpisodeNN")
    cmd = C.get("release.export")
    check(cmd is not None, "命令已注册")
    if not cmd:
        return
    check(cmd.danger == C.WRITE, "标为写操作（页面必须给确认单）：danger=%r" % cmd.danger)
    check(cmd.billing == C.FREE, "免费（本地复制）：billing=%r" % cmd.billing)
    v, argv = argv_of("release.export", {"all": True, "apply": True, "target": "1080x1920", "digits": 2})
    check(v["ok"], "参数校验通过：%s" % (v["errors"] or ""))
    joined = " ".join(argv)
    check("release_export.py" in joined, "指向 release_export.py")
    check("--apply" in argv, "--apply 才会真写")
    check("--all" in argv, "默认导出全部")
    check("--workspace" in argv, "必须带 --workspace（脚本不认 cwd）")
    check(not any("--ep" == a for a in argv), "留空 ep 时不要传 --ep")


def test_refs_apply():
    print("\n[2] refs.apply —— 写盘、走 drama.py refs")
    cmd = C.get("refs.apply")
    check(cmd is not None, "命令已注册")
    if not cmd:
        return
    check(cmd.danger == C.WRITE, "标为写操作：danger=%r" % cmd.danger)
    v, argv = argv_of("refs.apply", {"apply": True, "write_config": True})
    check(v["ok"], "参数校验通过：%s" % (v["errors"] or ""))
    check("drama.py" in " ".join(argv), "转发给 drama.py")
    check("refs" in argv, "子命令 refs")
    check("--apply" in argv, "写盘开关")
    # 只体检时不能带 --apply
    v2, argv2 = argv_of("refs.apply", {"apply": False})
    check("--apply" not in argv2, "只体检不写盘")


def test_video_resume():
    print("\n[3] video.resume —— ★计费、必须 --yes、只补指定段")
    cmd = C.get("video.resume")
    check(cmd is not None, "命令已注册")
    if not cmd:
        return
    check(cmd.billing == C.PAID, "标为计费：billing=%r" % cmd.billing)
    check(cmd.danger == C.DANGER, "最高风险级（页面要二次确认）：danger=%r" % cmd.danger)
    v, argv = argv_of("video.resume", {"resume": "EP01", "only": "shot_001", "yes": True})
    check(v["ok"], "参数校验通过：%s" % (v["errors"] or ""))
    joined = " ".join(argv)
    check("video run" in joined, "子命令是 video run（resume 是它的开关）")
    check("--resume" in argv and "EP01" in argv, "带批次号")
    check("--only" in argv and "shot_001" in argv, "带要补的段（原始目录名）")
    check("--yes" in argv, "带计费确认")
    v2 = cmd.validate({"resume": "", "only": "shot_001", "yes": True})
    check(not v2["ok"], "批次号为空必须报错：%s" % (v2["errors"] or "没报错"))


def main():
    test_release_export()
    test_refs_apply()
    test_video_resume()
    print("\n" + "=" * 70)
    if FAILS:
        print("[FAIL] %d 项未通过" % len(FAILS))
        return 1
    print("[OK] 三个新动作的契约全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
