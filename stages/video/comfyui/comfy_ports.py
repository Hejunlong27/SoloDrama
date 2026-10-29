# -*- coding: utf-8 -*-
"""comfy_ports.py —— 从 ComfyUI「API 格式」工作流里认出可喂值的端口，并按需裁掉没用的分支

★ 本文件是**唯一实现**（纯标准库，可独立运行）。`web/core/comfy_ports.py` 只是按路径加载它，
  反过来依赖会让引擎脚本必须 import `web.*`，那样脚本就没法脱离控制台跑了。

为什么需要它
------------
工作流是别人（或上个项目）配好的，图省事会把 6 个参考图槽全接上。这次只有 2 张参考图时：

* **本地**：6 个 `LoadImage` 仍然会执行，多出来的槽还带着上次的文件名 → 串景；显存白占。
* **云端（RunningHub）**：`nodeInfoList` 是**覆盖表**，没发的节点沿用保存值 —— 这就是
  「只覆盖 3 个槽、结果 H3 拿 6 张图串景/爆显存」的根因（已在 V0.7.x 记过账）。

所以这里做两件事：
1. `describe()`：把工作流翻译成人能看懂的端口清单（谁是提示词、谁是图片槽、几个槽、输出在哪）；
2. `prune()`：**真的改图** —— 删掉多出来的图片槽节点、删掉指向它们的边，再按输出节点做可达性剪枝。

边界（刻意不做的事）
--------------------
* 不猜语义：只认已知节点类与字段名，认不出就标 `unknown`，不硬套。
* 不动工作流的「必需」连接：只有当消费者有 `image1..imageN` 这一族字段（说明多槽可选）时才删，
  单个 `image` 字段的节点一律保留 —— 删了工作流直接跑不起来。
* 云端没有图可改：`plan_slots()` 只给「该喂哪几张」，多余的槽由调用方按策略处理（见 generators）。
"""
from __future__ import annotations

import copy
import re

# 输出节点：有它才算「有产物」，可达性剪枝从这里反向走
OUTPUT_CLASSES = {
    "SaveVideo", "SaveAnimatedWEBP", "SaveImage", "VHS_VideoCombine", "SaveWEBM",
    "SaveAudio", "PreviewImage", "PreviewAudio", "CreateVideo",
}

# 输入端口识别表：(角色, 节点类集合, 字段名集合)
ROLE_RULES = [
    ("image", {"LoadImage"}, {"image"}),
    ("prompt", {"PrimitiveStringMultiline", "PrimitiveString"}, {"value", "string", "text"}),
    ("text", {"CLIPTextEncode", "TextEncodeQwenImage21", "TextEncodeQwenImageEdit"},
     {"text", "prompt", "clip_l"}),
    ("steps", {"BasicScheduler", "KSampler", "KSamplerAdvanced", "SamplerCustomAdvanced"},
     {"steps"}),
    ("seed", {"RandomNoise", "KSampler", "KSamplerAdvanced", "Seed (rgthree)"},
     {"noise_seed", "seed"}),
    ("aspect", {"ResolutionSelector"}, {"aspect_ratio"}),
    ("megapixels", {"ResolutionSelector"}, {"megapixels"}),
    ("seconds", {"PrimitiveFloat", "PrimitiveInt"}, {"value"}),
    ("int", {"INTConstant", "PrimitiveInt"}, {"value"}),
    ("filename", {"SaveVideo", "VHS_VideoCombine", "SaveImage", "SaveAnimatedWEBP"},
     {"filename_prefix"}),
]

# 槽字段的两种写法都要认：
#   image1 / image_2 / img3            （扁平的）
#   ref_images.ref_image_0             （H3 多参节点用的带点动态输入）
# 判据是「字段名里含 image/img/ref/reference，末尾跟序号」。
_SLOT_TAIL = re.compile(r"^([a-z_.]*?(?:image|img|ref|reference)[a-z_.]*?)[._-]?(\d+)$", re.I)


def _slot_key(field: str):
    """→ (族名, 序号) 或 None。族名保留前缀（含点），避免 image1 与 ref_image_0 混成一家。"""
    if not isinstance(field, str):
        return None
    m = _SLOT_TAIL.match(field)
    if not m:
        return None
    return (field[:len(field) - len(m.group(2))].rstrip("._-"), int(m.group(2)))


def _is_workflow(wf) -> bool:
    return isinstance(wf, dict) and bool(wf) and all(
        isinstance(v, dict) and "class_type" in v for v in wf.values())


def _node_id_key(k: str) -> tuple:
    """节点 id 排序：数字优先按数值，其余按字符串，保证「image1/2/3」顺序稳定。"""
    return (0, int(k)) if str(k).isdigit() else (1, str(k))


def describe(wf: dict) -> dict:
    """→ {ports, slots, groups, outputs, unreachable, node_count}

    `slots` 是**按下标排好序**的图片槽节点 id 列表（裁剪就按这个顺序保留前 N 个）。
    `groups` 记录「一个节点上有一族 imageN 字段」的情况（H3 多参节点就是这样）。
    """
    if not _is_workflow(wf):
        raise ValueError("不是 ComfyUI API 格式工作流（应为 {nodeId: {class_type, inputs}}）")

    ports = []
    for nid in sorted(wf, key=_node_id_key):
        node = wf[nid]
        cls = str(node.get("class_type") or "")
        ins = node.get("inputs") or {}
        for role, classes, fields in ROLE_RULES:
            if cls not in classes:
                continue
            for f in fields:
                if f in ins and not isinstance(ins[f], list):     # list = 连线，不是值
                    ports.append({"node": nid, "class_type": cls, "field": f,
                                  "role": role, "value": ins[f]})
            break

    # 图片槽：所有 LoadImage
    slots = [p["node"] for p in ports if p["role"] == "image"]
    slots.sort(key=_node_id_key)

    # 多槽消费者：同一节点上有 image1/image2/... 一族字段
    groups = []
    for nid, node in wf.items():
        ins = node.get("inputs") or {}
        fam = {}
        for k in ins:
            sk = _slot_key(str(k))
            if sk:
                fam.setdefault(sk[0], []).append((sk[1], k))
        for prefix, pairs in fam.items():
            if len(pairs) < 2:
                continue          # 只有一个字段的叫「普通输入」，不是多槽
            pairs.sort()
            groups.append({"node": nid, "class_type": node.get("class_type"),
                           "prefix": prefix, "fields": [k for _i, k in pairs],
                           "indices": [i for i, _k in pairs]})

    outputs = [nid for nid, n in wf.items() if str(n.get("class_type")) in OUTPUT_CLASSES]
    reach = reachable(wf, outputs)
    # 「能接几张参考图」= 加载器数量与多槽字段数量的较大值（两者不一定相等）
    capacity = max([len(slots)] + [len(g["fields"]) for g in groups] or [0])
    return {
        "ports": ports,
        "slots": slots,
        "capacity": capacity,
        "groups": groups,
        "outputs": sorted(outputs, key=_node_id_key),
        "unreachable": sorted(set(wf) - reach, key=_node_id_key),
        "node_count": len(wf),
    }


def _refs(node: dict):
    """一条节点引用（连线）在 API 格式里是 [上游id, 输出序号]。"""
    for k, v in (node.get("inputs") or {}).items():
        if isinstance(v, list) and len(v) == 2 and str(v[0]) in ("", None):
            continue
        if isinstance(v, list) and len(v) == 2:
            yield k, str(v[0])


def reachable(wf: dict, outputs) -> set:
    """从输出节点反向走，返回可达节点集合（ComfyUI 只执行可达节点）。"""
    keep, stack = set(), [str(o) for o in outputs if str(o) in wf]
    while stack:
        nid = stack.pop()
        if nid in keep:
            continue
        keep.add(nid)
        for _k, up in _refs(wf.get(nid) or {}):
            if up in wf and up not in keep:
                stack.append(up)
    return keep


def prune_for_refs(wf: dict, want_images) -> tuple:
    """按参考图数量裁掉多余的图片槽。

    → (新工作流, 报告)
    报告：{"before": 6, "after": 2, "dropped_nodes": [...], "dropped_edges": [...], "reason": ""}

    规则（保守）：
      1. 多槽节点的 `ref_image_3..N` 这类字段：保留前 want 个，其余**删字段**；
      2. `LoadImage` 加载器：保留前 want 个，其余**删节点**；
      3. 删完做一次可达性剪枝，把因此孤立的节点一起清掉（不然它们仍会执行、仍占显存）；
      4. 单槽 `image` 字段一律不动 —— 删了工作流直接跑不起来。
    """
    info = describe(wf)
    capacity = int(info.get("capacity") or 0)
    if want_images is None or int(want_images) < 1:
        return wf, {"before": capacity, "after": None, "dropped_nodes": [],
                    "dropped_edges": [], "reason": "未指定参考图数量，保持原样"}
    want = int(want_images)
    if capacity <= want:
        return wf, {"before": capacity, "after": capacity, "dropped_nodes": [],
                    "dropped_edges": [], "reason": ""}

    out = copy.deepcopy(wf)
    drop_loaders = set(info["slots"][want:])
    edges, drop_nodes = [], set(drop_loaders)

    # 1) 多槽字段：保留前 want 个，其余删掉（这是「关掉多余槽位」的正解）
    for g in info["groups"]:
        nid = g["node"]
        for field in g["fields"][want:]:
            if nid in out and field in (out[nid].get("inputs") or {}):
                up = out[nid]["inputs"].pop(field)
                edges.append("%s.%s <- %s" % (nid, field, (up or ["?"])[0]))

    # 2) 删加载器；同时清掉任何仍在指向它们、且属于同族的边
    for nid in drop_loaders:
        out.pop(nid, None)
    for nid, node in list(out.items()):
        for key in list((node.get("inputs") or {})):
            v = node["inputs"][key]
            if isinstance(v, list) and len(v) == 2 and str(v[0]) in drop_loaders:
                node["inputs"].pop(key, None)
                edges.append("%s.%s <- %s" % (nid, key, v[0]))

    # 3) 可达性剪枝
    reach = reachable(out, [n for n in out if str(out[n].get("class_type")) in OUTPUT_CLASSES])
    orphan = sorted(set(out) - reach, key=_node_id_key)
    for nid in orphan:
        out.pop(nid, None)
        drop_nodes.add(nid)

    return out, {
        "before": capacity,
        "after": want,
        "dropped_nodes": sorted(drop_nodes, key=_node_id_key),
        "dropped_edges": edges,
        "reason": "",
    }


def plan_slots(info: dict, have: int) -> dict:
    """云端用：算「该喂哪几个槽、多出来的怎么处理」。

    云端不能删节点（只覆盖值），所以这里只给方案，执行策略由调用方决定：
      * `use`  本次要写的槽（前 have 个）
      * `rest` 多余的槽，按 policy 处理（repeat=复用最后一张 / blank=空串 / off=写 off_value）
    """
    slots = list(info.get("slots") or [])
    groups = info.get("groups") or []
    slots_in_group = []
    for g in groups:
        slots_in_group.extend(g.get("fields") or [])
    return {
        "loader_slots": slots,
        "group_fields": slots_in_group,
        "use": slots[:have],
        "rest": slots[have:],
        "short": max(0, have - len(slots)),
    }
