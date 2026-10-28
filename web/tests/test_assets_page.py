#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_assets_page.py —— 资产中心的两个「静默坏掉」路径（离线）

为什么单独盯这两条：它们都不报错，只是「看起来没有图片 / 点了没反应」。

1. **目录清单的 rel 必须是「工作区相对」**
   曾经返回 `characters/x.png`（相对子目录），而 /media 按工作区相对解析 →
   整页图片 404，但接口本身 200，日志里什么都没有。这条测试直接比对
   `list_dir` 返回的 rel 能不能被 `safe_rel` 解析回同一个文件。

2. **资产命令必须能注入 SOLODRAMA_ASSET_MD**
   引擎的 `gen_assets_local.py` 只认这个环境变量（没有命令行参数）。
   命令声明了 `env` 映射后，`env_for(values)` 必须把它算出来——算不出来的话，
   网页上所有出图/体检按钮都会失败，还会被翻译成「ComfyUI 没开」误导人。
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB))

from core import artifacts, commands as CMD, studio  # noqa: E402

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("  [NG] %s" % msg)
    return cond


def section(name):
    print("\n[%s]" % name)


def _ws():
    ws = Path(tempfile.mkdtemp(prefix="assets-ws-"))
    # safe_root() 要求「像一个工作区」：至少要有一个标记文件
    (ws / "layout.json").write_text('{"layout_version": 1}', encoding="utf-8")
    d = ws / "04-资产" / "characters"
    d.mkdir(parents=True)
    (d / "char_01_角色 A_四联设定板_00.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    (ws / "04-资产" / "资产提示词.md").write_text("# 角色\n\n## char_01\n提示词……\n", encoding="utf-8")
    (ws / "04-资产" / "design").mkdir()
    (ws / "04-资产" / "design" / "角色差异化矩阵.md").write_text("# 矩阵\n", encoding="utf-8")
    return ws


def test_rel_is_workspace_relative():
    section("1 目录清单 rel 口径")
    ws = _ws()
    data = artifacts.list_dir(ws, "04-资产/characters")
    imgs = [it for it in data["items"] if it["kind"] == "image"]
    check(len(imgs) == 1, "应找到 1 张图，实际 %d" % len(imgs))
    rel = imgs[0]["rel"]
    check(rel == "04-资产/characters/char_01_角色 A_四联设定板_00.png",
          "rel 必须是工作区相对：%r" % rel)
    check("/" in rel and "\\" not in rel, "rel 用正斜杠：%r" % rel)

    # 关键断言：拿 rel 去解析，必须回到同一个文件（/media 就是这么用的）
    resolved = artifacts.safe_rel(ws, rel)
    check(resolved.is_file(), "safe_rel(rel) 应命中文件：%s" % resolved)
    check(resolved.parent.name == "characters", "应落在 characters/ 下")

    # 目录字段仍然相对工作区根
    check(data["dir"].replace("\\", "/") == "04-资产/characters",
          "dir 应为 04-资产/characters：%r" % data["dir"])


def test_asset_env_injection():
    section("2 资产命令的环境变量注入")
    md = str(Path(tempfile.mkdtemp(prefix="md-")) / "资产提示词.md")
    vals = {"kind": "all", "submit": True, "asset_md": md, "only": ""}

    for cid in ("assets.local", "assets.check", "assets.rh", "assets.gen_char", "assets.gen_scene"):
        c = CMD.get(cid)
        if not check(c is not None, "%s 应在白名单里" % cid):
            continue
        check(c.env.get("SOLODRAMA_ASSET_MD") == "asset_md",
              "%s 应声明 SOLODRAMA_ASSET_MD → asset_md" % cid)
        got = c.env_for(vals)
        check(got.get("SOLODRAMA_ASSET_MD") == md, "%s 应注入 md 路径：%r" % (cid, got))

    # 空值不注入（否则会把「没选」变成一个空字符串变量，引擎仍会当成已设置）
    c = CMD.get("assets.local")
    check(c.env_for({"asset_md": ""}) == {}, "空 asset_md 不注入")
    check(c.env_for({}) == {}, "缺 asset_md 不注入")

    # 参数必须能通过校验（否则前端传了也会 422）
    v = c.validate({"kind": "all", "submit": True, "asset_md": md})
    check(v["ok"] is True, "带 asset_md 的参数应通过校验：%r" % (v.get("errors"),))
    check(v["values"]["asset_md"] == md, "校验后应保留 asset_md")


def test_asset_md_detection():
    section("3 资产提示词 md 探测")
    ws = _ws()
    d = studio.asset_mds(ws)
    check(d["ok"] is True, "探测应成功")
    names = [it["name"] for it in d["items"]]
    check("资产提示词.md" in names, "应枚举到 04-资产/资产提示词.md：%r" % names)
    check("角色差异化矩阵.md" in names, "设计子目录的 md 也应列出（低优先级）：%r" % names)
    check(d["suggested"].endswith("资产提示词.md"),
          "建议值应优先「资产提示词」：%r" % d["suggested"])
    check(all("/" in it["rel"] and "\\" not in it["rel"] for it in d["items"]),
          "rel 用正斜杠")

    empty = Path(tempfile.mkdtemp(prefix="assets-empty-"))
    (empty / "layout.json").write_text("{}", encoding="utf-8")
    d2 = studio.asset_mds(empty)
    check(d2["suggested"] == "", "没有 md 时不给建议")
    check("没有找到" in d2["note"], "没有 md 时应说明后果：%r" % d2["note"])


def main() -> int:
    print("=" * 60)
    print("资产中心路径测试（离线，零写入真实工作区）")
    print("=" * 60)
    test_rel_is_workspace_relative()
    test_asset_env_injection()
    test_asset_md_detection()
    print("\n" + "-" * 60)
    if FAILS:
        print("[NG] %d 项未通过" % len(FAILS))
        return 1
    print("[OK] 资产中心路径全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
