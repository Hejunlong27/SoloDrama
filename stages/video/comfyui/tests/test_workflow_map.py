#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_workflow_map.py —— 本地出片「换工作流」的映射校验（离线，不连 ComfyUI）

守什么
------
换一份 ComfyUI 工作流时，最容易错的是**节点 id 对不上**：脚本照样提交、GPU 照样跑，
但参数全落在没人读的节点上 —— 出来的是默认参数的片，白等几分钟。
`--map-check` 就是为了在**花 GPU 之前**把这类错 100% 抓出来。

另外守两条口径：
  * 映射默认读**同名 sidecar**（`xxx.json` → `xxx.map.json`），换工作流不用改代码；
  * `--list-nodes` 必须能离线跑（用户没有映射时靠它查 id）。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]          # stages/video/comfyui
SCRIPT = HERE / "comfy_local_video.py"
WF = HERE / "workflow_h3_local.json"
MAP = HERE / "workflow_h3_local.map.json"

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("  [NG] %s" % msg)
    return cond


def run(*args):
    p = subprocess.run([sys.executable, str(SCRIPT), *args],
                       capture_output=True, text=True, encoding="utf-8", cwd=str(HERE))
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main():
    try:
        print("[1] 仓库自带的工作流与映射必须对得上")
        check(WF.is_file(), "缺工作流文件 %s" % WF.name)
        check(MAP.is_file(), "缺映射文件 %s（约定：<工作流>.map.json）" % MAP.name)
        rc, out = run("--map-check")
        check(rc == 0, "--map-check 应该通过，实际 rc=%s：%s" % (rc, out[-300:]))
        for role in ("prompt", "images", "seconds", "steps", "seed", "aspect", "prefix"):
            check(role in out, "输出里应列出角色 %s" % role)
        check("同名 sidecar" in out, "应说明映射来自 sidecar，实际：%s" % out[:160])

        print("[2] 映射 id 写错时必须判失败（否则会白跑 GPU）")
        tmp = Path(tempfile.mkdtemp(prefix="solodrama-map-"))
        try:
            bad_map = tmp / "bad.map.json"
            bad_map.write_text(json.dumps({"prompt": "999", "images": ["24"]}), encoding="utf-8")
            rc2, out2 = run("--map-check", "--map", str(bad_map))
            check(rc2 != 0, "节点 id 不存在时必须返回非零，实际 rc=%s" % rc2)
            check("不存在" in out2, "要明确说「不存在」：%s" % out2[-300:])

            print("[3] 换工作流：sidecar 按文件名自动识别（不用改代码/环境变量）")
            alt = tmp / "another.json"
            alt.write_text(WF.read_text(encoding="utf-8"), encoding="utf-8")
            alt_map = tmp / "another.map.json"
            # 故意把 steps 指到 RandomNoise（类型不对）→ 应给 [OK]? 不，类型不符给 [? ]，但 id 存在不算失败
            alt_map.write_text(json.dumps({
                "prompt": "30", "images": ["24"], "seconds": "15",
                "steps": "14", "seed": "10", "aspect": "14", "prefix": "4",
            }, ensure_ascii=False), encoding="utf-8")
            rc3, out3 = run("--map-check", "--workflow", str(alt))
            check(rc3 == 0, "id 都存在时应通过（类型不符只提醒），实际 rc=%s" % rc3)
            check("another.map.json" in out3, "应自动读到同目录 sidecar：%s" % out3[:200])
            check("[? ]" in out3, "类型不符的 role 应给 [? ] 提醒")

            print("[4] 界面导出的工作流（非 API 格式）要被挡住")
            ui_wf = tmp / "ui_format.json"
            ui_wf.write_text(json.dumps({"nodes": [], "links": []}), encoding="utf-8")
            rc4, out4 = run("--map-check", "--workflow", str(ui_wf))
            check(rc4 != 0, "非 API 格式应返回非零")
            check("API 格式" in out4, "要告诉用户该用「导出 API」：%s" % out4[-200:])

            print("[5] --list-nodes 必须离线可用（用户靠它查 id）")
            rc5, out5 = run("--list-nodes")
            check(rc5 == 0, "--list-nodes 应成功，实际 rc=%s" % rc5)
            check("PrimitiveStringMultiline" in out5 and "LoadImage" in out5,
                  "应列出关键节点类：%s" % out5[:200])
            check("可作" in out5, "未映射的节点要给「可作 xx」的建议")
        finally:
            shutil.rmtree(str(tmp), ignore_errors=True)
    finally:
        pass

    print("\n" + ("全部通过" if not FAILS else "失败 %d 项" % len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
