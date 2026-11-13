#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""fix_h3_pack.py —— 制作包里 h3 提示词的**机械**修整（只做能证明等价的那两类）

为什么只修两类
--------------
`stages/import/h3_prompt.py` 的纪律是「只判不修」。但有两类问题**修起来不可能改变语义**，
而每换一个项目都要人工抄一遍：

  1. `retention_analysis` 漏行（H3-E07，**阻断**）
     每个已定义的 `<Subject n>` / `<Picture n>` 都必须有一行「保留到什么程度」。
     漏一行，整包导入直接失败 —— 但补哪一行、写什么标记词是确定的：
       · `<Subject n>` 漏 → 按「保住外观」写 fully_preserved；
       · `<Picture n>` 漏 → 按「只保构图/光位、不复制内容」写 partially_preserved。
  2. `detailed_description` 缺 `[Shot 1]`（H3-W01，告警）
     全文一个 `[Shot n]` 都没有时，模型拿不到切点。在段首补 `[Shot 1]` 不改变任何一句描述。

不修什么（以及为什么）
----------------------
* `<d>` 句末标点（H3-W03）：判据是 `。！？!?…`，**不含 ASCII 句点**。西班牙语剧本里
  每句都以 `.` 结尾，机械补 `。` 会把西语台词的排版弄成中英混排 —— 那是把校验器的
  口径问题写进内容。要修应该修判据（按 `--lang` 决定句末集合），不是改文本。
* 正文过短（H3-W04）、缺 `(S1)/(S2)`（H3-W05）：需要人来判断，机械补等于编内容。

用法
----
    python tools/fix_h3_pack.py --pack "D:/剧本/海外剧/10/pack"          # 只报告
    python tools/fix_h3_pack.py --pack "..." --apply                    # 落盘（先自动备份）
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")     # type: ignore[union-attr]
except Exception:                                                  # noqa: BLE001
    pass

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stages" / "import"))

import h3_prompt as H                                              # noqa: E402

_DEF_SUB = re.compile(r"(?m)^<Subject\s+(\d+)>")
_DEF_PIC = re.compile(r"(?m)^<Picture\s+(\d+)>")
_ROW = re.compile(r"(?m)^<(Subject|Picture)\s+(\d+)>")


def _section_bounds(text: str, name: str) -> tuple:
    """→ (段首偏移, 段尾偏移)；找不到返回 (-1, -1)。段以「下一行顶格的 xxx:」为界。"""
    m = re.search(r"(?m)^%s\s*:\s*$" % re.escape(name), text)
    if not m:
        return -1, -1
    start = m.end()
    nxt = re.search(r"(?m)^[a-z_]+\s*:\s*$", text[start:])
    end = start + nxt.start() if nxt else len(text)
    return start, end


def fix_retention(text: str) -> tuple:
    """补齐 retention_analysis 漏掉的标签行。→ (新文本, 补了哪些)"""
    s0, s1 = _section_bounds(text, "subject_definitions")
    r0, r1 = _section_bounds(text, "retention_analysis")
    if s0 < 0 or r0 < 0:
        return text, []
    defs = text[s0:s1]
    have = {(m.group(1), int(m.group(2))) for m in _ROW.finditer(text[r0:r1])}
    add = []
    for m in _DEF_SUB.finditer(defs):
        if ("Subject", int(m.group(1))) not in have:
            add.append(("<Subject %s>（出现于 [Shot 1]）：fully_preserved - "
                        "保留其身份特征与服装，不新增配饰。" % m.group(1)))
    for m in _DEF_PIC.finditer(defs):
        if ("Picture", int(m.group(1))) not in have:
            add.append(("<Picture %s>（[Shot 1] 首帧）：partially_preserved - "
                        "只保留机位、构图与光位，不复制画面内容。" % m.group(1)))
    if not add:
        return text, []
    block = text[r0:r1].rstrip("\n")
    new_block = block + "\n" + "\n".join(add) + "\n"
    return text[:r0] + new_block + text[r1:], add


def fix_shot_marker(text: str) -> tuple:
    """detailed_description 全文无 `[Shot n]` 时，在段首补 `[Shot 1]`。→ (新文本, 是否改)"""
    d0, d1 = _section_bounds(text, "detailed_description")
    if d0 < 0:
        return text, False
    body = text[d0:d1]
    if re.search(r"\[Shot\s+\d+\]", body):
        return text, False
    stripped = body.lstrip("\n")
    if not stripped.strip():
        return text, False
    lead = body[: len(body) - len(stripped)]
    # ★ 必须把 d1 之后的段（overall_soundscape / non_diegetic_music）原样接回去：
    #   第一版漏了这一步，把六段砍成四段，导入直接报 H3-E01。
    return text[:d0] + lead + "[Shot 1] " + stripped + text[d1:], True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="h3 提示词的机械修整（retention 漏行 / [Shot 1] 缺失）")
    ap.add_argument("--pack", required=True, help="制作包目录（含 pack.json）")
    ap.add_argument("--apply", action="store_true", help="落盘（默认只报告）")
    a = ap.parse_args(argv)

    pack = pathlib.Path(a.pack).expanduser().resolve()
    eps = sorted((pack / "episodes").glob("ep*.json"))
    if not eps:
        print("[FAIL] %s/episodes 下没有 ep*.json" % pack)
        return 2

    if a.apply:
        bak = pack / ("episodes.bak-%s" % time.strftime("%Y%m%d_%H%M%S"))
        shutil.copytree(pack / "episodes", bak)
        print("备份：%s" % bak)

    n_ret = n_mark = n_shots = 0
    touched_eps = []
    for f in eps:
        data = json.loads(f.read_text(encoding="utf-8-sig"))
        shots = data.get("shots") or []
        changed = False
        for s in shots:
            vp = str(s.get("video_prompt") or "")
            if "subject_definitions" not in vp:
                continue
            n_shots += 0
            new, added = fix_retention(vp)
            if added:
                n_ret += len(added)
                print("  [retention] %s %s：补 %d 行 → %s" % (
                    f.stem, s.get("id"), len(added), "、".join(x.split("（")[0] for x in added)))
                vp, changed = new, True
            new2, marked = fix_shot_marker(vp)
            if marked:
                n_mark += 1
                print("  [shot]      %s %s：补 [Shot 1]" % (f.stem, s.get("id")))
                vp, changed = new2, True
            if vp != str(s.get("video_prompt") or ""):
                s["video_prompt"] = vp
        if changed:
            n_shots += len(shots)
            touched_eps.append(f.stem)
            if a.apply:
                f.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")

    print("\n汇总：retention 补 %d 行 ｜ [Shot 1] 补 %d 镜 ｜ 改动集数 %d"
          % (n_ret, n_mark, len(touched_eps)))
    if not a.apply and (n_ret or n_mark):
        print("（干跑：未写盘。加 --apply 落盘，会自动备份 episodes/）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
