#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""rh_workflow_id.py —— 从 RunningHub 页面存档里反查 workflowId（纯标准库、零网络）

为什么有它（反馈 P2-2）
----------------------
`/openapi/v2/workflow/list` 不存在（301 / code=1001），所以**无法按名字反查工作流 ID**。
实测可行途径：AI 应用详情页 `ai-detail/<id>` 的 `__NUXT_DATA__` 里能解出底层 `workflowId`
（本项目即由此拿到 `2110380691388194818`）。此前这一步靠人肉翻页面源码，因此写进流程。

用法
----
    # 1) 在浏览器里打开 AI 应用页 → Ctrl+S 保存「网页，仅 HTML」，或用 curl 抓一份：
    #    curl -s "https://www.runninghub.ai/ai-detail/xxxx" -o app.html
    python rh_workflow_id.py app.html
    python rh_workflow_id.py app.html --json

判据与纪律
----------
* **只读**：本脚本只解析本地文件，不发任何请求（因此不可能建任务、不可能计费）。
* **不猜**：解析出多个不同 ID 时全部列出来，由人确认，不默认取第一个。
* 识别四种来源：① 明文 `workflowId: "123…"`；② `__NUXT_DATA__` 扁平数组；
  ③ 内嵌 JSON 里的 `"workflowId"` 键；④ 页面里出现的 18–20 位长整数（只作候选提示）。

退出码：0 找到（≥1 个候选）；1 没找到；2 用法/文件错误
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ID_RE = re.compile(r"\b(\d{17,20})\b")
NUXT_RE = re.compile(r'id="__NUXT_DATA__"[^>]*>(.*?)</script>', re.S)
KEY = "workflowId"


def _walk_nuxt(arr: list) -> list:
    """在 Nuxt 的扁平数组里找 `workflowId` 的取值。

    Nuxt/devalue 把对象序列化成 `{"workflowId": <数组下标>}`（值被提到顶层数组里），
    所以先找「键在下标 i」，再按三种常见形态取值：
      * 对象字面量：{"workflowId": "123…"} / {"workflowId": 12} （12 是下标）
      * 相邻元素：arr[i+1] 是字符串或指向字符串的下标
    """
    found = []
    for i, item in enumerate(arr):
        if not isinstance(item, dict):
            continue
        for k, v in item.items():
            if k != KEY:
                continue
            if isinstance(v, str) and v.isdigit() and len(v) >= 15:
                found.append(v)
            elif isinstance(v, int) and 0 <= v < len(arr):
                target = arr[v]
                if isinstance(target, str) and target.isdigit():
                    found.append(target)
                elif isinstance(target, dict):           # 再退一层
                    for vv in target.values():
                        if isinstance(vv, str) and vv.isdigit() and len(vv) >= 15:
                            found.append(vv)
        if isinstance(item, str) and item == KEY:
            for cand in arr[i + 1: i + 3]:
                if isinstance(cand, str) and cand.isdigit() and 15 <= len(cand) <= 20:
                    found.append(cand)
    return found


def extract(text: str) -> dict:
    """返回 {'strong': [...], 'nuxt': [...], 'loose': [...]}（去重后）。"""
    strong = re.findall(r'["\']?%s["\']?\s*[:=]\s*["\']?(\d{15,20})' % KEY, text)
    nuxt = []
    m = NUXT_RE.search(text)
    if m:
        raw = m.group(1).strip()
        try:
            arr = json.loads(raw)
            if isinstance(arr, list):
                nuxt = _walk_nuxt(arr)
        except json.JSONDecodeError:
            nuxt = [x for x in re.findall(r'"%s"\s*,\s*(\d{15,20})' % KEY, raw)]
    loose = ID_RE.findall(text)

    def uniq(xs):
        out = []
        for x in xs:
            if x and x not in out:
                out.append(x)
        return out

    return {"strong": uniq(strong), "nuxt": uniq(nuxt), "loose": uniq(loose)}


def main() -> int:
    ap = argparse.ArgumentParser(description="从 RunningHub 页面存档里反查 workflowId（只读、零网络）")
    ap.add_argument("html", help="保存下来的页面 HTML（或 curl 输出）")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    a = ap.parse_args()

    p = pathlib.Path(a.html).expanduser()
    if not p.is_file():
        print("[FAIL] 文件不存在：%s" % p)
        return 2
    text = p.read_text(encoding="utf-8", errors="replace")
    got = extract(text)

    best = got["strong"] or got["nuxt"]
    if a.json:
        print(json.dumps({"file": str(p), "workflow_ids": best,
                          "loose_candidates": got["loose"] if not best else [],
                          "source": ("strong" if got["strong"] else ("nuxt" if got["nuxt"] else "none"))},
                         ensure_ascii=False, indent=2))
    else:
        print("=" * 74)
        print("RunningHub workflowId 反查（只读，未联网）")
        print("=" * 74)
        print("  文件：%s（%.1f KB）" % (p, p.stat().st_size / 1024))
        if len(best) == 1:
            print("  [OK] workflowId = %s" % best[0])
            print("       下一步：drama.py models set video=runninghub --workflow-id %s" % best[0])
        elif len(best) > 1:
            print("  [?] 解析到 %d 个不同的 workflowId（不替你选，请核对应用的实际工作流）：" % len(best))
            for x in best:
                print("        - %s" % x)
        else:
            print("  [NG] 没找到明确的 workflowId。")
            if got["loose"]:
                print("       页面里的长整数候选（可能是应用 ID / 任务 ID，需人工辨认）：")
                for x in got["loose"][:8]:
                    print("        - %s" % x)
            print("       建议：确认保存的是 **AI 应用详情页**（ai-detail/<id>）且脚本未被拦截；"
                  "也可在浏览器控制台执行 `__NUXT_DATA__` 搜 workflowId。")
    return 0 if best else 1


if __name__ == "__main__":
    sys.exit(main())
