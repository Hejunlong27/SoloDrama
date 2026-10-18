#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""release_check.py —— 发行资料齐全度门禁（2026-10-18 新增）

为什么有它
----------
「发行资料」此前只在 Skill 侧有零散说明，**没有验收口径**。实测后果有两类：
  * **封面漏档**：只出了 9:16，上架时卡片位（3:4）要临时补做，风格对不上；
  * **版权资料缺失**：被平台质疑「搬运 / 非原创 / AIGC 未标注」时，**拿不出举证材料**。

本脚本把「发行资料 = 封面 + 文案 + 发布清单 + 版权资料」固化为**可机器校验**的关卡：
结构齐不齐、尺寸档对不对、版权资料是不是 4 张「AI 生成过程截图」+ 4 张
「原始文件/素材文件信息」。**零网络、零第三方依赖（图片尺寸读文件头，不依赖 Pillow）**。

唯一真源：`docs/distribution/发行资料清单.md`

用法
----
    python release_check.py --workspace "D:/剧/新剧"
    python release_check.py --workspace "D:/剧/新剧" --json
    python release_check.py --workspace "D:/剧/新剧" --min-side 900     # 放宽长边下限

退出码：0 = 发行资料齐备；2 = 有缺项（附人话修法）
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import struct
import sys
from datetime import datetime

# ⚠ 不要在这里 import _ws：`_ws.WS` 是**导入期常量**，没有可解析的工作区时会直接退出，
#   导致 `--workspace` 还没被解析就死了（新机器上首次调用必踩）。
#   正确姿势：先解析参数 → 把工作区写回环境变量 → 再导入（见 main）。

# ---- 口径常量（与 docs/distribution/发行资料清单.md 一致）----
REQUIRED_COVER_RATIOS = ("9x16", "3x4")     # 必须存在
OPTIONAL_COVER_RATIOS = ("16x9", "1x1")
AI_PROCESS_IDS = (1, 2, 3, 4)               # 4 张「AI 生成过程截图」（编号即证据序号，不得缺号）
SOURCE_FILE_IDS = (1, 2, 3, 4)              # 4 张「原始文件/素材文件信息」
MIN_LONG_SIDE = 1200                        # 版权资料长边下限（太小看不清任务 ID / 时间戳）
RATIO_TOLERANCE = 0.02                      # 封面比例容差 ±2%
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")

AI_PROCESS_LABEL = {
    1: "出图/出片平台任务页（含任务 ID + 提交时间）",
    2: "提示词或工作流节点（含节点号/字段名）",
    3: "生成结果列表（含数量 + 生成时间）",
    4: "用量/计费记录页（含任务 ID + 消耗量）",
}
SOURCE_FILE_LABEL = {
    1: "项目工作区目录树（展开到阶段目录）",
    2: "剧本原稿文件信息（文件名/大小/修改时间）",
    3: "分镜或提示词源文件信息",
    4: "成片母版文件信息（分辨率/编码/时长）",
}


# ---------------------------------------------------------------- 图片尺寸
def image_size(p: pathlib.Path):
    """从文件头读 (宽, 高)；无需第三方库。读不出返回 None。"""
    try:
        with open(p, "rb") as f:
            head = f.read(32)
            if head[:8] == b"\x89PNG\r\n\x1a\n":                       # PNG: IHDR
                w, h = struct.unpack(">II", head[16:24])
                return int(w), int(h)
            if head[:3] == b"\xff\xd8\xff":                            # JPEG: 扫 SOFn
                f.seek(2)
                while True:
                    b = f.read(1)
                    if not b:
                        return None
                    if b != b"\xff":
                        continue
                    marker = f.read(1)
                    while marker == b"\xff":                           # 填充字节
                        marker = f.read(1)
                    if not marker:
                        return None
                    m = marker[0]
                    if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:
                        continue
                    ln = f.read(2)
                    if len(ln) < 2:
                        return None
                    seg = struct.unpack(">H", ln)[0]
                    # SOF0–SOF15（排除 DHT/JPG/DAC = C4/C8/CC）：高在 +3，宽在 +5
                    if 0xC0 <= m <= 0xCF and m not in (0xC4, 0xC8, 0xCC):
                        rest = f.read(5)
                        if len(rest) < 5:
                            return None
                        h, w = struct.unpack(">HH", rest[1:5])
                        return int(w), int(h)
                    f.seek(seg - 2, 1)
            if head[:6] in (b"GIF87a", b"GIF89a"):
                w, h = struct.unpack("<HH", head[6:10])
                return int(w), int(h)
    except (OSError, struct.error, ValueError):
        return None
    return None


def ratio_ok(w, h, tag: str) -> bool:
    """封面比例是否与档位名一致（如 9x16 ⇒ 0.5625），容差 ±2%。"""
    try:
        tw, th = (int(x) for x in tag.lower().split("x"))
    except ValueError:
        return True
    if not w or not h:
        return False
    target = tw / th
    return abs((w / h) - target) / target <= RATIO_TOLERANCE


# ---------------------------------------------------------------- 采集
def scan_covers(release: pathlib.Path):
    """在 09-发行/（含 封面/ 子目录）里找 cover_<ratio>.<ext>。返回 {ratio: [(path, w, h, ok)]}。"""
    found: dict = {}
    for p in release.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in IMG_EXT:
            continue
        m = re.match(r"^cover[_-]([0-9]+x[0-9]+)$", p.stem.lower())
        if not m:
            continue
        tag = m.group(1)
        w, h = image_size(p) or (0, 0)
        found.setdefault(tag, []).append({"path": p, "w": w, "h": h, "ratio_ok": ratio_ok(w, h, tag)})
    return found


def scan_evidence(release: pathlib.Path, prefix: str, ids):
    """按固定前缀 + 两位序号找证据图。返回 {序号: [条目]}。"""
    found: dict = {}
    pat = re.compile(r"^%s[_-](\d{1,2})(?:[_-].*)?$" % re.escape(prefix), re.IGNORECASE)
    for p in release.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in IMG_EXT:
            continue
        m = pat.match(p.stem)
        if not m:
            continue
        n = int(m.group(1))
        if n not in ids:
            continue
        w, h = image_size(p) or (0, 0)
        found.setdefault(n, []).append({"path": p, "w": w, "h": h, "long_side": max(w, h)})
    return found


# ---------------------------------------------------------------- 主流程
def main() -> int:
    ap = argparse.ArgumentParser(description="发行资料齐全度门禁（离线、零网络）")
    ap.add_argument("--workspace", default=None)
    ap.add_argument("--min-side", type=int, default=MIN_LONG_SIDE,
                    help="版权资料长边下限，默认 %d px" % MIN_LONG_SIDE)
    ap.add_argument("--json", action="store_true", help="输出 JSON（给控制台/CI 用）")
    a = ap.parse_args()

    # 先解析参数再导入工作区模块（见文件头的 ¶ 说明）；显式 --workspace 必须**覆盖**环境变量。
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    if a.workspace:
        os.environ["SOLODRAMA_WORKSPACE"] = str(pathlib.Path(a.workspace).expanduser().resolve())
    import _ws as W      # noqa: E402
    import _layout as L  # noqa: E402

    ws = pathlib.Path(a.workspace).expanduser().resolve() if a.workspace else W.WS
    try:
        release = L.stage_dir(ws, "release")
    except Exception:                                                          # noqa: BLE001
        release = ws / "09-发行"

    fails, warns, notes = [], [], []

    # ---- 0. 目录本身 ----
    if not release.is_dir():
        fails.append("发行目录不存在：%s ⇒ 先跑 `creation.py scaffold`，或手工建 `09-发行/`" % release)
        return _report(a, ws, release, fails, warns, notes, {})

    # ---- 1. 封面 ----
    covers = scan_covers(release)
    for tag in REQUIRED_COVER_RATIOS:
        items = covers.get(tag)
        if not items:
            fails.append("缺封面档位 `cover_%s`（%s）⇒ 用 drama-cover-forge 出图，文件名固定 cover_%s.png"
                         % (tag, "竖版主封面" if tag == "9x16" else "卡片位封面", tag))
        elif not any(i["ratio_ok"] for i in items):
            bad = ", ".join("%s %dx%d" % (i["path"].name, i["w"], i["h"]) for i in items)
            fails.append("封面 `cover_%s` 实际比例与档位不符（容差 ±2%%）：%s ⇒ 重出，勿拉伸" % (tag, bad))
    for tag in OPTIONAL_COVER_RATIOS:
        if tag not in covers:
            warns.append("建议补一档 `cover_%s`，非阻断（多尺寸位可复用同一抓马构图）" % tag)
    if not any(p.is_file() for p in (release / "封面").glob("preview.*")) and \
       not any(release.glob("preview.*")):
        warns.append("未见 `preview.jpg` 预览拼图（供内部评审，非阻断）")

    # ---- 2. 版权资料：4 + 4 ----
    ai = scan_evidence(release, "ai-process", AI_PROCESS_IDS)
    src = scan_evidence(release, "source-file", SOURCE_FILE_IDS)
    for label, found, ids in (("AI 生成过程截图", ai, AI_PROCESS_IDS),
                              ("原始文件/素材文件信息", src, SOURCE_FILE_IDS)):
        for n in ids:
            items = found.get(n)
            if not items:
                hint = (AI_PROCESS_LABEL if found is ai else SOURCE_FILE_LABEL)[n]
                fails.append("版权资料缺第 %d 张「%s」：%s ⇒ 命名 `%s-%02d-<slug>.png`"
                             % (n, label, hint, "ai-process" if found is ai else "source-file", n))
                continue
            best = max(items, key=lambda i: i["long_side"])
            if best["long_side"] and best["long_side"] < a.min_side:
                fails.append("版权资料 `%s` 长边仅 %d px（下限 %d）⇒ 重新截图，放大后会糊到看不清任务 ID"
                             % (best["path"].name, best["long_side"], a.min_side))
            elif not best["long_side"]:
                warns.append("版权资料 `%s` 尺寸无法从文件头解析（格式异常？）" % best["path"].name)
        # 该类别是否整体缺失，单独给一条更醒目的话
        if not found:
            notes.append("%s：**整类缺失**（8 张里缺 4 张）" % label)

    checklist = release / "版权资料" / "版权资料清单.md"
    if not checklist.is_file() and not (release / "版权资料清单.md").is_file():
        fails.append("缺 `版权资料/版权资料清单.md`（八张图逐张一句说明；外部人靠它读懂举证链）")

    # ---- 3. 文案 ----
    copy_json = release / "文案" / "copy.json"
    copy_md = release / "文案" / "copy.md"
    if not copy_json.is_file() and not copy_md.is_file():
        fails.append("缺文案：`09-发行/文案/copy.json`（或 copy.md）⇒ 标题六槽位 + 三档描述 + 关键词")

    # ---- 4. 发布清单 ----
    if not (release / "发布清单.md").is_file():
        fails.append("缺 `09-发行/发布清单.md` ⇒ 按 docs/distribution/发行资料清单.md §六 逐项勾选")

    # ---- 5. 必须人工确认的三件事（机器替不了）----
    notes.append("需人工确认：①封面抓马度六抓手 ≥5/6 且 cover_spec.json 已填 reviewer；"
                 "②版权资料可辨认性（任务 ID / 时间戳肉眼可读，未被打码）；"
                 "③AIGC 标注已落在片头/片尾/文案位（整剧统一）")

    return _report(a, ws, release, fails, warns, notes,
                   {"covers": sorted(covers), "ai_process": sorted(ai), "source_file": sorted(src)})


def _report(a, ws, release, fails, warns, notes, summary) -> int:
    # --json 时 stdout **只放 JSON**（供控制台/CI 解析），人读内容一律走 stderr。
    human = sys.stderr if a.json else sys.stdout

    if a.json:
        out = {"at": datetime.now().astimezone().replace(microsecond=0).isoformat(),
               "workspace": str(ws), "release_dir": str(release),
               "fails": fails, "warns": warns, "notes": notes, "found": summary,
               "verdict": "blocked" if fails else "ok"}
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print("=" * 74)
        print("发行资料齐全度检查 · %s" % release)
        print("=" * 74)
        if summary:
            print("  封面档位    : %s" % (", ".join(summary["covers"]) or "（无）"))
            print("  AI 生成过程  : %s / 4" % len(summary["ai_process"]))
            print("  原始文件信息 : %s / 4" % len(summary["source_file"]))
        for w in warns:
            print("  [WARN] %s" % w)
        for b in fails:
            print("  [FAIL] %s" % b)
        print()
        for n in notes:
            print("  · %s" % n)

    # 落痕到 09-发行/release-manifest.json
    try:
        release.mkdir(parents=True, exist_ok=True)
        rec = {"at": datetime.now().astimezone().replace(microsecond=0).isoformat(),
               "workspace": str(ws), "fails": fails, "warns": warns,
               "found": summary, "min_side": a.min_side,
               "verdict": "发行资料不齐备" if fails else "发行资料齐备（机器部分）"}
        (release / "release-manifest.json").write_text(
            json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    except OSError:
        pass

    if fails:
        print("\n[BLOCK] 发行资料不齐备 —— 共 %d 项缺项，补齐后再发行。" % len(fails), file=human)
        return 2
    print("\n[OK] 发行资料机器校验通过（人工项见上）。", file=human)
    return 0


if __name__ == "__main__":
    sys.exit(main())
