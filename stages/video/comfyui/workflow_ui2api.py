#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""workflow_ui2api.py —— ComfyUI「界面格式」工作流 → 「API 格式」（引擎能提交的那种）

为什么需要它
------------
ComfyUI 有两套 JSON，长得像，用途完全不同：

  * **界面格式**（在 ComfyUI 里点「保存」得到的）：`{"nodes": [...], "links": [...], "groups": [...]}`
    —— 给人看的画布，带坐标、颜色、分组框。
  * **API 格式**（点「导出（API）」得到的）：`{"<节点id>": {"class_type": "...", "inputs": {...}}}`
    —— 给 `/prompt` 接口吃的，节点之间用 `["<源节点id>", <输出槽号>]` 引用。

引擎只吃第二种。此前换工作流的流程是「让用户去 ComfyUI 里再点一次导出」，
这一步有三个坑：导出位置容易拿错文件、导出后节点 id 会变、以及**导出会丢掉
被静音（mode=4）节点的信息**，导致「为什么我本地跑得通、引擎跑不通」查不出来。

本脚本做确定性转换，并把「穿了哪些虚拟节点、跳了哪些静音节点」写进报告 ——
转换过程可见，才敢用它当默认工作流。

转换规则（ComfyUI 的既有约定，不是本脚本发明的）
------------------------------------------------
1. `links` 每条是 `[link_id, 源节点, 源槽, 目标节点, 目标槽, 类型]`。
2. 节点 `inputs[i].link` 指向 `link_id`；`has widget` 的输入按出现顺序消费 `widgets_values`。
3. **有连线时连线优先**，widget 值只是画布上的残影（引擎那边也这么判）。
4. `SetNode` / `GetNode` 是虚拟节点：`GetNode(名字)` 的输出 = 同名 `SetNode` 的输入。
   必须穿透，否则 API 里会指向一个不存在的 `GetNode`。
5. `mode == 4` 是「静音」（bypass）：ComfyUI 会在执行时把它的输入**直通**到输出，
   这里按 `Reroute` 处理（穿透到上游）；`mode == 2` 是「禁用」，真正不执行，直接跳过。
6. `MarkdownNote` / `Note` 是画布注释，不进 API。

用法
----
    python workflow_ui2api.py --ui 工作流.json --out api.json
    python workflow_ui2api.py --ui 工作流.json --out api.json --report 转换报告.md
    python workflow_ui2api.py --ui 工作流.json --check      # 只体检，不落盘

退出码：0 转换成功 / 2 输入不合法 / 3 转换后仍有悬空引用
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[union-attr]
except Exception:                                                # noqa: BLE001
    pass

# 画布专用、不进 API 的节点类型
VIRTUAL_TYPES = {"Note", "MarkdownNote", "Reroute", "PrimitiveNode"}
# 名字中转节点：需要穿透
SET_TYPE, GET_TYPE = "SetNode", "GetNode"

MODE_ALWAYS = 0        # 正常
MODE_MUTED = 2         # 从不执行（禁用）
MODE_BYPASS = 4        # 旁路：输入直通输出


class Conv:
    def __init__(self, doc: dict) -> None:
        self.doc = doc
        self.nodes = {int(n["id"]): n for n in doc.get("nodes") or []
                      if isinstance(n, dict) and "id" in n}
        # link_id -> (源节点, 源槽)
        self.links = {}
        for l in doc.get("links") or []:
            if isinstance(l, (list, tuple)) and len(l) >= 5:
                self.links[int(l[0])] = (int(l[1]), int(l[2]))
        # SetNode 名字 -> 节点 id
        self.sets = {}
        for n in self.nodes.values():
            if n.get("type") == SET_TYPE:
                name = self._first_widget(n)
                if name:
                    self.sets[name] = int(n["id"])
        self.notes: list = []
        self.skipped: list = []
        self.bypassed: list = []

    # -- 小工具 ---------------------------------------------------------
    @staticmethod
    def _first_widget(n: dict):
        w = n.get("widgets_values")
        if isinstance(w, (list, tuple)) and w:
            return str(w[0])
        if isinstance(w, str):
            return w
        return ""

    def resolve(self, link_id: int, depth: int = 0):
        """link → (节点 id, 槽号)；穿透 GetNode / Reroute / bypass 节点。"""
        if depth > 64:
            self.notes.append("穿透层数超过 64，疑似循环：link=%s" % link_id)
            return None
        src = self.links.get(int(link_id))
        if not src:
            return None
        nid, slot = src
        n = self.nodes.get(nid)
        if n is None:
            return None
        t = n.get("type")

        if t == GET_TYPE:
            name = self._first_widget(n)
            sid = self.sets.get(name)
            if sid is None:
                self.notes.append("GetNode(%s) 找不到同名 SetNode" % name)
                return None
            ins = self.nodes.get(sid, {}).get("inputs") or []
            if not ins or ins[0].get("link") is None:
                self.notes.append("SetNode(%s) 没有输入，引用 %s 视为缺失" % (name, link_id))
                return None
            return self.resolve(ins[0]["link"], depth + 1)

        if t == SET_TYPE:
            # ★ 实测（2026-11-04）：这份画布里有「连线直接指向 SetNode」的情况
            #   （`#150.preview_frames → #231 SetNode("时长")`，而 231 的输入是空的）。
            #   ComfyUI 的画布能画出这种线，但 SetNode 没有输出，API 里无法表达。
            #   处理：等同于 GetNode —— 穿透到 SetNode 的输入；输入为空则视为「无值」，
            #   让下游节点用自己的默认值，而不是把引用指向一个不存在的节点。
            ins = n.get("inputs") or []
            if not ins or ins[0].get("link") is None:
                self.notes.append("SetNode(%s) 没有输入，引用 %s 视为缺失"
                                  % (self._first_widget(n), link_id))
                return None
            return self.resolve(ins[0]["link"], depth + 1)

        if t == "Reroute" or n.get("mode") == MODE_BYPASS:
            # 旁路的取第一个有连线的输入，直通
            for inp in n.get("inputs") or []:
                if inp.get("link") is not None:
                    if n.get("mode") == MODE_BYPASS:
                        self.bypassed.append((nid, t))
                    return self.resolve(inp["link"], depth + 1)
            return None

        return (nid, slot)

    # -- 主转换 ---------------------------------------------------------
    def convert(self) -> dict:
        api: dict = {}
        for nid, n in self.nodes.items():
            t = n.get("type") or ""
            if t in VIRTUAL_TYPES or t in (SET_TYPE, GET_TYPE):
                continue
            if n.get("mode") in (MODE_MUTED, MODE_BYPASS):
                # 静音节点本身不进 API：它的作用已经通过 resolve() 的穿透完成
                self.skipped.append((nid, t, "muted" if n.get("mode") == MODE_MUTED else "bypass"))
                if n.get("mode") == MODE_MUTED:
                    continue
                # bypass 但仍被下游引用时，下游已在 resolve 里穿透；这里不再输出自己
                continue

            inputs: dict = {}
            widgets = n.get("widgets_values")
            wi = 0
            wlist = widgets if isinstance(widgets, (list, tuple)) else []

            for inp in n.get("inputs") or []:
                if not isinstance(inp, dict):
                    continue
                name = inp.get("name")
                if not name:
                    continue
                link = inp.get("link")
                has_widget = bool(inp.get("widget"))
                if link is not None:
                    src = self.resolve(link)
                    if src:
                        inputs[name] = [str(src[0]), src[1]]
                    elif has_widget and wi < len(wlist):
                        # ★ 连线存在但源头解析不出来（典型：对方的 SetNode 输入被删），
                        #   回落到节点自己的 widget 值 —— 这正是 ComfyUI 的语义：
                        #   widget 值一直在，连线只是覆盖它。不回落的后果是这一镜缺
                        #   `length`/`width` 之类的必需参数，提交时才 400。
                        inputs[name] = wlist[wi]
                        self.notes.append("#%s.%s 连线解析失败，已回落到 widget 值 %r"
                                          % (nid, name, wlist[wi]))
                    if has_widget:
                        wi += 1
                    continue
                if has_widget:
                    if wi < len(wlist):
                        inputs[name] = wlist[wi]
                    wi += 1

            # 有些老节点（如 VHS_VideoCombine）的 widgets_values 是 dict
            if isinstance(widgets, dict):
                for k, v in widgets.items():
                    if k == "videopreview":
                        continue
                    inputs.setdefault(k, v)
            elif isinstance(widgets, (list, tuple)) and wi == 0 and wlist and not (n.get("inputs") or []):
                # 完全没有 inputs 声明的节点：把 widget 值按顺序塞进去（罕见，但存在）
                for i, v in enumerate(wlist):
                    inputs["_w%d" % i] = v

            api[str(nid)] = {
                "class_type": t,
                "inputs": inputs,
                "_meta": {"title": n.get("title") or t},
            }
        return api

    # -- 自检 -----------------------------------------------------------
    def dangling(self, api: dict) -> list:
        """检查每个引用是否指向 API 里真实存在的节点。"""
        bad = []
        for nid, node in api.items():
            for k, v in (node.get("inputs") or {}).items():
                if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) \
                        and v[0].isdigit():
                    if v[0] not in api:
                        bad.append((nid, k, v[0]))
        return bad


def summarize(api: dict) -> dict:
    from collections import Counter
    return {"nodes": len(api),
            "by_class": dict(Counter(n["class_type"] for n in api.values()).most_common())}


def report_md(ui_path, conv: Conv, api: dict, bad: list) -> str:
    lines = ["# 工作流转换报告", "",
             "- 源文件：`%s`" % ui_path,
             "- 界面节点：%d → API 节点：%d" % (len(conv.nodes), len(api)),
             "- 悬空引用：%d" % len(bad), ""]
    s = summarize(api)
    lines += ["## 节点类型分布", "", "| class_type | 数量 |", "|---|---|"]
    lines += ["| `%s` | %d |" % (k, v) for k, v in s["by_class"].items()]
    lines.append("")
    if conv.skipped:
        lines += ["## 未进入 API 的节点", "", "| 节点 | 类型 | 原因 |", "|---|---|---|"]
        lines += ["| %s | `%s` | %s |" % (n, t, w) for n, t, w in conv.skipped]
        lines.append("")
    if conv.notes:
        lines += ["## 转换备注", ""] + ["- %s" % x for x in conv.notes] + [""]
    if bad:
        lines += ["## 悬空引用（必须修）", "", "| 节点 | 输入 | 指向 |", "|---|---|---|"]
        lines += ["| %s | %s | %s |" % b for b in bad]
        lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ComfyUI 界面格式 → API 格式")
    ap.add_argument("--ui", required=True, help="界面格式工作流 JSON")
    ap.add_argument("--out", default=None, help="输出的 API 格式 JSON")
    ap.add_argument("--report", default=None, help="转换报告 Markdown 路径")
    ap.add_argument("--check", action="store_true", help="只体检，不落盘")
    a = ap.parse_args(argv)

    p = pathlib.Path(a.ui).expanduser().resolve()
    if not p.is_file():
        print("[FAIL] 文件不存在：%s" % p)
        return 2
    try:
        doc = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, ValueError) as e:
        print("[FAIL] JSON 解析失败：%s" % e)
        return 2

    if "nodes" not in doc:
        print("[FAIL] 这不是「界面格式」：顶层没有 nodes。")
        print("       若它已经有 class_type（API 格式），直接拿去用，不必转换。")
        return 2

    conv = Conv(doc)
    api = conv.convert()
    bad = conv.dangling(api)
    s = summarize(api)

    print("=" * 76)
    print("工作流转换：界面 %d 节点 → API %d 节点" % (len(conv.nodes), s["nodes"]))
    print("=" * 76)
    for k, v in s["by_class"].items():
        print("  %-42s %d" % (k, v))
    if conv.skipped:
        print("-" * 76)
        print("  未进入 API（静音 / 旁路）：")
        for nid, t, why in conv.skipped:
            print("    #%-5s %-34s %s" % (nid, t, why))
    if conv.notes:
        print("-" * 76)
        for x in conv.notes:
            print("  [i] %s" % x)
    print("-" * 76)
    if bad:
        print("  [FAIL] 悬空引用 %d 处（这些节点指向了不存在的 API 节点）：" % len(bad))
        for nid, k, to in bad[:12]:
            print("    #%s.%s → #%s" % (nid, k, to))
        print("  常见原因：上游节点被静音（mode=2）却仍被引用。")
    else:
        print("  [OK] 无悬空引用")

    if a.check:
        return 0 if not bad else 3

    if a.out:
        out = pathlib.Path(a.out).expanduser().resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(api, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8", newline="")
        print("\n[OK] 已写出：%s" % out)

    if a.report:
        rp = pathlib.Path(a.report).expanduser().resolve()
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(report_md(p, conv, api, bad), encoding="utf-8", newline="")
        print("[OK] 报告：%s" % rp)

    if not bad:
        print("\n下一步：写 sidecar 映射（<同名>.map.json），再用")
        print("  python stages/video/comfyui/comfy_local_video.py --workflow %s --list-nodes"
              % (a.out or "<api.json>"))
    return 0 if not bad else 3


if __name__ == "__main__":
    sys.exit(main())
