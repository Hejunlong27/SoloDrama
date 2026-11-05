"""test_workflow_hygiene.py —— 随仓库交付的工作流必须「结构干净」

为什么单独一条
--------------
2026-11-05 真机踩到：`workflow_h3_minimax_canvas.json` 里有一个**不可达**的节点
`"200": {"class_type": "忽略多组孤海"}`（界面转 API 时留下的垃圾）。它在画布上不连任何东西，
本地也没人注意，但云端 ComfyUI 0.43.2 直接整份拒收：

    HTTP 400 · missing_node_type · Node '忽略多组孤海' not found

也就是说：**死节点不是无害的**。ComfyUI 会 Validate 整份 prompt，不只看执行路径。
本机之所以「看起来能跑」，很可能只是因为本地那份 ComfyUI 版本宽松/或没人提交过这条链。

所以这里守三条静态不变量（不需要 GPU、不需要 ComfyUI）：

  1. `class_type` 必须是**可打印 ASCII** —— 中文名属于 `_meta.title`（给人看），
     出现在 `class_type` 里基本都是导出时的数据损坏。
     ★ 注意不能要求「纯标识符」：rgthree / LayerUtility 的类名本来就带空格括号
     （`Seed (rgthree)`、`LayerUtility: ImageScaleByAspectRatio V2`），那些是合法的。
  2. 节点间的连线必须指向**存在的节点**（悬空引用会变成 400 或静默不执行）；
  3. 每份工作流旁边要有同名 `.map.json`（换工作流不改代码的前提）。
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

HERE = pathlib.Path(__file__).resolve().parent
COMFY_DIR = HERE.parent
# 只挑工作流本体：`workflow_x.map.json` 是映射文件，结构完全不同
WORKFLOWS = sorted(p for p in COMFY_DIR.glob("workflow_*.json")
                   if not p.name.endswith(".map.json"))
# 可打印 ASCII（拒绝中文/控制字符/空串）；不要求「纯标识符」，见文件头说明
ASCII_OK = re.compile(r"^[ -~]+$")


def _load(p: pathlib.Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8-sig"))


def test_workflows_found():
    assert WORKFLOWS, "没找到任何 workflow_*.json —— 测试路径写错了？"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_class_type_is_ascii(path):
    wf = _load(path)
    bad = {str(n.get("class_type")) for n in wf.values()
           if isinstance(n, dict) and not ASCII_OK.match(str(n.get("class_type") or ""))}
    assert not bad, (
        "%s 里有非法 class_type：%s\n"
        "  这类名字（中文/空格/乱码）通常是界面转 API 时的残留节点；\n"
        "  ComfyUI 会 Validate 整份 prompt，**即使节点不可达也会整份拒收**（HTTP 400 missing_node_type）。\n"
        "  修法：删掉该节点（先确认没有别的节点引用它）。" % (path.name, sorted(bad)))


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_links_point_to_existing_nodes(path):
    wf = _load(path)
    ids = {str(k) for k in wf}
    dangling = []
    for nid, node in wf.items():
        for field, val in ((node or {}).get("inputs") or {}).items():
            if isinstance(val, list) and len(val) == 2 and str(val[0]) not in ("", None):
                if str(val[0]) not in ids:
                    dangling.append("#%s.%s -> #%s" % (nid, field, val[0]))
    assert not dangling, "%s 有悬空连线：%s" % (path.name, dangling[:8])


def test_every_workflow_has_sidecar_map():
    missing = [p.name for p in WORKFLOWS
               if not (COMFY_DIR / (p.stem + ".map.json")).is_file()]
    assert not missing, "以下工作流缺同名 .map.json（换工作流就不能不改代码了）：%s" % missing
