#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_workspaces.py —— 项目登记表的两类「不会报错，但一定出事」的缺陷（离线）

背景（2026-10-28 实测，真实机器上的登记表）
-------------------------------------------
    items  : D:\\剧本\\海外剧\\3                    ← 目录早已删除
             D:\\剧本\\海外剧\\2                    ← 目录早已删除
             D:\\剧本\\海外剧\\2、母亲之路
             D:\\剧本\\海外剧\\《离婚后，四个大佬哥哥接我回家》
    current: D:\\剧本\\海外剧\\3                    ← 指着死路径

1. **当前工作区不能是死路径**
   旧实现把 `current` 无条件塞进 `items`（伪造成一张卡片），并且前端 `loadProjects()`
   直接采信 `current` ⇒ 整个应用带着一个不存在的目录去请求所有接口，用户一进来就是空页。

2. **失效登记项必须能被清理**
   前端只渲染 `exists` 为真的项，于是「登记了 4 个、只显示 2 个」，而界面上没有任何
   入口能把这 2 个死条目去掉。prune 只动注册表，**绝不碰磁盘**。

本测试全部在临时目录里跑，不读写真实的 `web/var/registry.json`。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB))

from core import paths  # noqa: E402

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("  [NG] %s" % msg)
    return cond


def section(name):
    print("\n[%s]" % name)


def _mk_drama(root: Path, name: str) -> Path:
    ws = root / name
    (ws / "video-pipeline").mkdir(parents=True, exist_ok=True)
    return ws


def main():
    root = Path(tempfile.mkdtemp(prefix="solodrama-ws-"))
    real_registry = paths.REGISTRY_FILE
    try:
        # 扫描根指向临时目录，避免 discover() 去扫真实的 D:\剧本
        os.environ["SOLODRAMA_SCAN_ROOTS"] = str(root)
        reg_file = root / "_registry.json"
        paths.REGISTRY_FILE = reg_file

        import app  # noqa: E402 —— 依赖 fastapi，用 envs/solodrama-web 的解释器跑
        from core import inventory  # noqa: E402
        inventory._CACHE.clear()

        a = _mk_drama(root, "活着的剧")
        b = root / "已经删掉的剧"          # 只登记，不建目录

        print("[1] 当前工作区是死路径 → 必须自愈，且不能把死路径伪造成项目卡片")
        reg_file.write_text(json.dumps({
            "items": [{"path": str(b), "title": "已经删掉的剧", "added_at": 1},
                      {"path": str(a), "title": "活着的剧", "added_at": 2}],
            "current": str(b),
        }, ensure_ascii=False), encoding="utf-8")
        d = app._i_workspaces()
        check(d["current"] != str(b), "当前工作区仍指向已删除目录：%s" % d["current"])
        check(d["current"] == str(a), "当前工作区应自愈到唯一活着的项目，实际 %s" % d["current"])
        check(d.get("current_exists") is True, "current_exists 应为 True")
        check(d.get("current_replaced") == str(b), "应记录被替换掉的死路径（便于界面解释）")
        check(str(b) in (d.get("stale") or []), "失效目录应出现在 stale 里：%s" % d.get("stale"))
        persisted = json.loads(reg_file.read_text(encoding="utf-8"))
        check(persisted["current"] == str(a), "自愈结果必须落盘，否则下次启动又回到死路径")
        check("current_replaced" not in persisted, "current_replaced 只用于本次响应，不该写进注册表")

        print("[2] current 指向未登记的死目录 → 不许凭空变成一张卡片")
        reg_file.write_text(json.dumps({
            "items": [{"path": str(a), "title": "活着的剧", "added_at": 1}],
            "current": str(root / "幽灵剧"),
        }, ensure_ascii=False), encoding="utf-8")
        d = app._i_workspaces()
        ghost = [it for it in d["items"] if it["path"] == str(root / "幽灵剧")]
        check(not ghost, "未登记的当前目录被伪造成了项目条目：%s" % ghost)
        check(d["current"] == str(a), "应回落到真实存在的项目，实际 %s" % d["current"])

        print("[3] 一个可用项目都没有时 → current 置空，而不是留个死路径")
        # 扫描根换成空目录：否则 discover() 会把磁盘上真实存在的剧再补回来，
        # 就测不到「全盘皆死」这一支了。
        empty_root = root / "空扫描区"
        empty_root.mkdir(exist_ok=True)
        os.environ["SOLODRAMA_SCAN_ROOTS"] = str(empty_root)
        inventory._CACHE.clear()
        reg_file.write_text(json.dumps({
            "items": [{"path": str(b), "title": "已经删掉的剧", "added_at": 1}],
            "current": str(b),
        }, ensure_ascii=False), encoding="utf-8")
        d = app._i_workspaces()
        check(d["current"] in ("", None), "没有可用项目时 current 应为空，实际 %r" % d["current"])
        check(d.get("current_exists") is False, "current_exists 应为 False")
        os.environ["SOLODRAMA_SCAN_ROOTS"] = str(root)
        inventory._CACHE.clear()

        print("[4] prune 只清注册表，绝不碰磁盘")
        reg_file.write_text(json.dumps({
            "items": [{"path": str(b), "title": "已经删掉的剧", "added_at": 1},
                      {"path": str(a), "title": "活着的剧", "added_at": 2}],
            "current": str(b),
        }, ensure_ascii=False), encoding="utf-8")
        r = app.prune_workspaces()
        check(r["removed"] == [str(b)], "应只移除失效的一条，实际 %s" % r["removed"])
        check(r["kept"] == 1, "应保留 1 条，实际 %s" % r["kept"])
        check(a.is_dir() and (a / "video-pipeline").is_dir(), "prune 不得删除任何磁盘目录")
        persisted = json.loads(reg_file.read_text(encoding="utf-8"))
        check([it["path"] for it in persisted["items"]] == [str(a)], "注册表里应只剩活着的项目")
        check(persisted["current"] == str(a), "prune 后 current 应指向活着的项目")
        r2 = app.prune_workspaces()
        check(r2["removed"] == [], "已清理干净后再跑一次应无事可做，实际 %s" % r2["removed"])
    finally:
        paths.REGISTRY_FILE = real_registry
        os.environ.pop("SOLODRAMA_SCAN_ROOTS", None)
        shutil.rmtree(str(root), ignore_errors=True)

    print("\n" + ("全部通过" if not FAILS else "失败 %d 项" % len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
