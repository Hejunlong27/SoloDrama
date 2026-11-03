#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_skill_library.py —— 模板库：内置清单 / 用户上传 / 批量装载（离线）

为什么这三件事要钉
------------------
1. **内置模板必须随仓库来。** 之前只认 `D:/整合包/...` 这一个外部路径，
   换机器、换人接手就「一份模板都没有」，而界面只会说「可用 0 份」。
2. **上传的判据要严，但不能严到没人能用。** 只校验「像不像一份 Skill」
   （frontmatter + name + 正文），不猜内容好坏 —— 它是给模型看的文本，不是代码。
3. **批量装载要能部分失败。** 新建项目时选 3 个模板，其中一个 id 打错了，
   不该让另外两个也装不上（那样用户得从头再来一次）。
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB))

import pytest  # noqa: E402

from core import skills   # noqa: E402

FAILS = []

GOOD = """---
name: test-template
description: 测试用模板，验证上传与装载通道
---

# 测试模板

这是测试正文，长度足够通过最低校验。
"""


def check(cond, msg):
    if cond:
        print("  [PASS] " + msg)
    else:
        print("  [FAIL] " + msg)
        FAILS.append(msg)


@pytest.fixture
def clean_user():
    d = skills.user_dir()
    made = not d.exists()
    yield d
    # 只清理测试自己造的那一份；别删用户上传的真实模板
    t = d / "test-template"
    if t.exists():
        shutil.rmtree(t, ignore_errors=True)
    if made and d.exists() and not any(d.iterdir()):
        d.rmdir()


def test_bundled_presets(clean_user):
    print("\n[1] 内置模板清单")
    p = skills.presets()
    check(p["count"] >= 20, "内置 + 上传的模板 ≥ 20 份，实际 %d" % p["count"])
    ids = [i["id"] for i in p["items"]]
    check("tianchong-manju" in ids, "内置的天虫模板在清单里")
    one = next(i for i in p["items"] if i["id"] == "tianchong-manju")
    check(one["bundled"] is True and one["origin"] == "内置", "标了「内置」")
    check(one["chars"] > 1000, "正文读得到（%d 字）" % one["chars"])


def test_upload(clean_user):
    print("\n[2] 上传用户模板")
    bad = skills.upload("这不是一份模板，只是一段普通文字，长度也许够了但结构不对。")
    check(bad["ok"] is False, "没有 frontmatter 的上传被拒")
    check("frontmatter" in bad["detail"], "拒绝理由说清了缺什么")
    r = skills.upload(GOOD, "test.md")
    check(r["ok"] is True, "正常模板上传成功")
    f = Path(r["path"])
    check(f.is_file() and f.parent.name == "test-template", "落点 web/var/skills-user/<id>/SKILL.md")
    again = skills.upload(GOOD, "test.md")
    check(again.get("already") is True, "同名不覆盖时返回 already")
    over = skills.upload(GOOD, "test.md", overwrite=True)
    check(over["ok"] is True and not over.get("already"), "勾了覆盖才重写")
    check("test-template" in [i["id"] for i in skills.presets()["items"]], "上传后出现在模板库清单里")


def test_install_many(clean_user):
    print("\n[3] 批量装载（允许部分失败）")
    ws = Path(tempfile.mkdtemp(prefix="sklib_"))
    try:
        skills.upload(GOOD, "test.md")
        r = skills.install_many(str(ws), ["tianchong-manju", "test-template", "no-such-template"])
        check(len(r["installed"]) == 2, "装上了 2 份，实际 %d" % len(r["installed"]))
        check(len(r["failed"]) == 1, "失败的单独列出，不拖累其它两份")
        check((ws / "skills" / "tianchong-manju.md").is_file(), "文件落在 <ws>/skills/<id>.md")
        reg = json.loads((ws / "skills.json").read_text(encoding="utf-8"))
        check(len(reg["items"]) == 2, "skills.json 登记 2 条")
        check(not r["ok"], "有失败时 ok=False（界面要能区分「全成」与「部分成」）")
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def test_prompt_compose_needs_skill():
    print("\n[4] 没有模板时不能拼指令")
    ws = Path(tempfile.mkdtemp(prefix="sklib2_"))
    try:
        try:
            skills.compose_prompt(str(ws))
            check(False, "空项目应当拒绝拼指令")
        except ValueError as exc:
            check("模板" in str(exc), "报错说清是没装模板：%s" % exc)
    finally:
        shutil.rmtree(ws, ignore_errors=True)


def main():
    d = skills.user_dir()
    made = not d.exists()
    try:
        test_bundled_presets(d)
        test_upload(d)
        test_install_many(d)
        test_prompt_compose_needs_skill()
    finally:
        t = d / "test-template"
        if t.exists():
            shutil.rmtree(t, ignore_errors=True)
        if made and d.exists() and not any(d.iterdir()):
            d.rmdir()
    print("-" * 60)
    if FAILS:
        print("[FAIL] %d 项未通过" % len(FAILS))
        return 1
    print("[OK] 模板库口径全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
