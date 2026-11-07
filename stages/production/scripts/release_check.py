#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""release_check.py —— 发行资料齐全度门禁（2026-10-18 新增）

为什么有它
----------
「发行资料」此前只在 Skill 侧有零散说明，**没有验收口径**。实测后果有两类：
  * **封面漏档**：只出了 9:16，上架时卡片位（3:4）要临时补做，风格对不上；
  * **版权资料缺失**：被平台质疑「搬运 / 非原创 / AIGC 未标注」时，**拿不出举证材料**。

本脚本把「发行资料 = 剧集 + 封面 + 文案 + 发布清单 + 版权资料」固化为**可机器校验**的关卡：
结构齐不齐、尺寸档对不对、发布版成片是否严格 `EpisodeNN.mp4`（2026-10-19 用户要求）、
版权资料是否覆盖平台的两个入口（AI 生成过程 / 原始文件素材，各 ≥4 张）**加**权利声明
（权属 / 原创性 / AI 披露 / 第三方素材 / 逐集清单 / 索引，2026-11-07 按驳回诊断改口径）。
**零网络、零第三方依赖（图片尺寸读文件头，不依赖 Pillow）**。

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
# ★ 2026-11-07 改口径：平台两个入口都是「至少 4 张、最多 20 张」，没有固定张数；
#   旧版把 `ai-process-01..04` / `source-file-01..04` 写死成「必须这 8 张」，
#   而那 8 张正是被驳回的那一版（数据面板，无画面/角色/场景）。现在的判据是
#   「**每类至少 4 张、不超过 20 张、每张都要有实质内容**」，编号只需连续。
ENTRY_MIN, ENTRY_MAX = 4, 20
RIGHTS_REQUIRED = ("01", "02", "03", "04", "05", "07")   # 06 视上传账号是否同一主体
RIGHTS_OPTIONAL = ("06",)
MIN_LONG_SIDE = 1200                        # 版权资料长边下限（太小看不清文件信息 / 提示词）
RATIO_TOLERANCE = 0.02                      # 封面比例容差 ±2%
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")

# 旧口径（2026-11-07 前）：这两类文件**不再作为主材料**，出现即告警
LEGACY_PREFIXES = ("ai-process", "source-file")

RIGHTS_LABEL = {
    "01": "权属声明（作品标识 + 独占所有权 + 无权利负担）",
    "02": "原创性证明（按文件日期排的创作链 + 人类创作贡献）",
    "03": "AI 使用披露（模型与许可基础 + 提示词作者 + 标注情况）",
    "04": "第三方素材声明（音乐/素材/字体/肖像/商标/场地）",
    "05": "逐集清单（文件名 + 时长 + 分辨率）",
    "06": "发行授权书（上传账号 ≠ 权利人时必填）",
    "07": "提交索引（每页证明什么 + 常见驳回对照）",
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
        # ★ 2026-10-20：允许 `cover_9x16_00.png` 这类**多候选**后缀（AI 直出会一档出 2–4 张，
        #   选定后再改名为 cover_9x16.png）。后缀不参与档位判定，只放宽识别。
        m = re.match(r"^cover[_-]([0-9]+x[0-9]+)(?:[_-].*)?$", p.stem.lower())
        if not m:
            continue
        tag = m.group(1)
        w, h = image_size(p) or (0, 0)
        found.setdefault(tag, []).append({"path": p, "w": w, "h": h, "ratio_ok": ratio_ok(w, h, tag)})
    return found


def scan_prefixed(release: pathlib.Path, prefix: str):
    """按前缀找证据图 → {序号: [条目]}；序号只用于排序与连续性判断，不预设张数。"""
    found: dict = {}
    pat = re.compile(r"^%s[_-](\d{1,2})(?:[_-].*)?$" % re.escape(prefix), re.IGNORECASE)
    for p in release.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in IMG_EXT:
            continue
        m = pat.match(p.stem)
        if not m:
            continue
        w, h = image_size(p) or (0, 0)
        found.setdefault(int(m.group(1)), []).append(
            {"path": p, "w": w, "h": h, "long_side": max(w, h)})
    return found


def scan_rights(release: pathlib.Path):
    """权利声明按两位编号找（`rights-01-*.png`…）→ {编号: [条目]}。"""
    found: dict = {}
    pat = re.compile(r"^rights[_-](\d{2})(?:[_-].*)?$", re.IGNORECASE)
    for p in release.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in IMG_EXT:
            continue
        m = pat.match(p.stem)
        if not m:
            continue
        w, h = image_size(p) or (0, 0)
        found.setdefault(m.group(1), []).append(
            {"path": p, "w": w, "h": h, "long_side": max(w, h)})
    return found


# ---------------------------------------------------------------- 主流程
def main() -> int:
    ap = argparse.ArgumentParser(description="发行资料齐全度门禁（离线、零网络）")
    ap.add_argument("--workspace", default=None)
    ap.add_argument("--min-side", type=int, default=MIN_LONG_SIDE,
                    help="版权资料长边下限，默认 %d px" % MIN_LONG_SIDE)
    ap.add_argument("--json", action="store_true", help="输出 JSON（给控制台/CI 用）")
    ap.add_argument("--no-write", dest="no_write", action="store_true",
                    help="只算不写：不落 09-发行/release-manifest.json（给只读接口用）")
    ap.add_argument("--material-only", dest="material_only", action="store_true",
                    help="只校验物料：连载/未杀青阶段把「成片未出」降为 WARN（反馈 P0-6）")
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

    # ★ 2026-10-20（反馈 P0-6）：把「物料缺项」与「成片未出（下游依赖）」分开记。
    #   此前五类产物被当作同一批次的并列项，任缺即整体不合格 —— 于是「封面/文案/版权全齐、
    #   只是还没杀青」也被判成「发行资料不齐备」，已完成的工作在唯一的结构化输出里看不见，
    #   连载阶段更是每次全红，红久了就没人看门禁了。
    fails, warns, notes, downstream = [], [], [], []

    # ---- 0. 目录本身 ----
    if not release.is_dir():
        fails.append("发行目录不存在：%s ⇒ 先跑 `drama init`，或手工建 `09-发行/`" % release)
        return _report(a, ws, release, fails, warns, notes, {}, downstream)

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

    # ---- 1.5 发布版成片：严格 EpisodeNN.mp4（★ 2026-10-19 用户要求）----
    ep_dir = L.release_episode_dir(ws)
    ep_rx = re.compile(L.RELEASE_FILENAME_RE, re.I)
    eps, bad_names = {}, []
    if ep_dir.is_dir():
        for f in sorted(ep_dir.iterdir()):
            if not f.is_file():
                continue
            if f.suffix.lower() != ".mp4":
                if f.name not in ("剧集清单.json",) and f.suffix.lower() not in (".json", ".md", ".txt"):
                    bad_names.append(f.name)
                continue
            m = ep_rx.match(f.name)
            (eps.__setitem__(int(m.group(1)), f) if m else bad_names.append(f.name))
    if bad_names:
        downstream.append("发布版命名不符合规范（须 `Episode01.mp4` 形式）：%s ⇒ 用 "
                     "`python stages/production/scripts/release_export.py --workspace \"<ws>\" --all --apply` 统一导出"
                     % "、".join(bad_names[:8]))
    if not eps:
        downstream.append("缺发布版成片：`09-发行/剧集/EpisodeNN.mp4`（一份都没有）⇒ 同上命令导出")
    else:
        nums = sorted(eps)
        gap = [n for n in range(min(nums), max(nums) + 1) if n not in nums]
        if gap:
            warns.append("发布版集号不连续，缺 %s（连载中属正常；整季交付前须补齐）"
                         % ", ".join(L.release_episode_name(g).replace(".mp4", "") for g in gap[:10]))

    # ---- 1.6 画面侧合规记录：**必须有，且必须新于成片**（★ 2026-10-30）----
    #   为什么查记录而不是重跑检测：本脚本的约定是「零网络、零第三方依赖」，
    #   重跑要调 ffprobe 扫全片；而 `compliance_media_check.py` 已经把结论落成 JSON。
    #   这里只做举证核对 —— 记录存在、结论 ok、时间戳不早于最新成片（防止拿旧记录充数）。
    #   注意：`release_export.py` 是硬拦（不合格根本不导出），本项是**二次举证**，
    #   两者互为独立防线，任何一条被绕过都还能兜住。
    try:
        comp_dir = L.stage_dir(ws, "compliance")
    except Exception:                                                      # noqa: BLE001
        comp_dir = ws / "08-合规"
    recs = sorted(comp_dir.glob("画面合规_*.json")) if comp_dir.is_dir() else []
    if not recs:
        downstream.append("缺画面侧合规记录（%s/画面合规_*.json）⇒ 跑 "
                          "`python stages/production/scripts/compliance_media_check.py "
                          "--workspace \"<ws>\" --all --from-source --sheet`" % comp_dir)
    else:
        latest = recs[-1]
        try:
            data = json.loads(latest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if data.get("verdict") != "ok":
            blocked = [r for r in (data.get("results") or []) if r.get("verdict") == "blocked"]
            fails.append("画面侧门禁未通过（%s，%d 集不合格）⇒ 修片后重跑 compliance_media_check，"
                         "不要只重跑本检查" % (latest.name, len(blocked) or 1))
        if eps:
            newest_ep = max((f.stat().st_mtime for f in eps.values()), default=0)
            try:
                if latest.stat().st_mtime < newest_ep:
                    warns.append("画面合规记录（%s）早于最新成片 —— 成片被替换过就该重跑门禁"
                                 % latest.name)
            except OSError:
                pass

    # ---- 2. 版权资料：两个平台入口 + 权利声明（2026-11-07 改口径）----
    #   旧判据要求固定 8 张（`ai-process-01..04` + `source-file-01..04`），而那 8 张
    #   正是被平台驳回的一版：数据面板，没有画面、没有角色、没有场景，也不回答
    #   「发行权在谁手上」。新判据按平台原文的两条入口来：
    #     入口 A（AI 生成过程）≥4 张，每张必须把「提示词 → 分镜图 → 成片帧」指向同一镜；
    #     入口 B（原始文件/素材）≥4 张，覆盖剧本 / 角色 / 场景 / 分镜文档 / video raw；
    #     权利声明 01–05 + 07 必须（06 视上传账号）。
    entry_a = scan_prefixed(release, "ai-gen")
    entry_b = scan_prefixed(release, "src")
    rights = scan_rights(release)

    for label, found, prefix, tip in (
            ("入口 A · AI 生成过程", entry_a, "ai-gen",
             "每张 = 同一镜的提示词 + 分镜图 + 成片抽帧 + 该镜用到的资产卡；"
             "缺画面/角色/场景是最常见的驳回原因"),
            ("入口 B · 原始文件/素材", entry_b, "src",
             "覆盖剧本 / 角色设计 / 场景设计 / 导演手册 / video raw / 素材清单，"
             "每张顶上要有文件信息条（名字+大小+时间）")):
        n = len(found)
        if n == 0:
            fails.append("版权资料缺「%s」整类（≥%d 张）：%s ⇒ 命名 `%s-NN-<slug>.png`，"
                         "生成器 `copyright_kit.py`"
                         % (label, ENTRY_MIN, tip, prefix))
            continue
        if n < ENTRY_MIN:
            fails.append("「%s」只有 %d 张（平台下限 %d）：%s ⇒ 补到 4–20 张"
                         % (label, n, ENTRY_MIN, tip))
        if n > ENTRY_MAX:
            warns.append("「%s」有 %d 张，超过平台上限 %d ⇒ 挑最能对应的 %d 张上传"
                         % (label, n, ENTRY_MAX, ENTRY_MAX))
        for k in sorted(found):
            best = max(found[k], key=lambda i: i["long_side"])
            if best["long_side"] and best["long_side"] < a.min_side:
                fails.append("版权资料 `%s` 长边仅 %d px（下限 %d）⇒ 重新渲染/截图，"
                             "放大后看不清提示词与文件信息" % (best["path"].name,
                                                              best["long_side"], a.min_side))
            elif not best["long_side"]:
                warns.append("版权资料 `%s` 尺寸无法从文件头解析（格式异常？）" % best["path"].name)
        # 编号连续性：只提示，不阻断（平台不要求连续，但缺号通常是漏传）
        gap = [i for i in range(1, max(found) + 1) if i not in found]
        if gap:
            warns.append("「%s」序号缺 %s ⇒ 多半是漏传，核对一下再上传"
                         % (label, "、".join("%02d" % g for g in gap)))

    for k in RIGHTS_REQUIRED:
        if k not in rights:
            fails.append("版权资料缺 `权利声明/rights-%s-*.png`：%s ⇒ 这是驳回的主因层"
                         "（截图证明不了权利归属），必须签章后上传"
                         % (k, RIGHTS_LABEL[k]))
    if not rights:
        notes.append("权利声明：**整类缺失** —— 平台驳回原文是「不足以证明本剧所需的相关权利」，"
                     "缺的就是这一层")
    for k in sorted(rights):
        best = max(rights[k], key=lambda i: i["long_side"])
        if best["long_side"] and best["long_side"] < a.min_side:
            fails.append("`%s` 长边仅 %d px（下限 %d）⇒ A4 声明书请用 1654×2339 渲染"
                         % (best["path"].name, best["long_side"], a.min_side))

    # 旧口径：文件在就留着（追询时可当补充材料），但不能再当主材料上传
    legacy = [p.name for pre in LEGACY_PREFIXES for p in release.rglob("*")
              if p.is_file() and p.stem.lower().startswith(pre)]
    if legacy:
        warns.append("版权资料里有 %d 个旧口径文件（%s）⇒ 它们是「创作过程台账」，只能当补充材料，"
                     "**不要**作为主材料上传（上一版就是这样被驳回的）"
                     % (len(legacy), "、".join(sorted(legacy)[:3]) + ("…" if len(legacy) > 3 else "")))

    checklist = release / "版权资料" / "版权资料清单.md"
    if not checklist.is_file() and not (release / "版权资料清单.md").is_file():
        fails.append("缺 `版权资料/版权资料清单.md`（逐张一句说明；外部人靠它读懂举证链）")

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
                 "②权利声明 rights-01..05 已**逐页签字盖章**（主体名与平台商务认证逐字一致）；"
                 "③上传账号与权利人是否同一主体（否 → rights-06 必填）；"
                 "④截图可辨认性（提示词/文件信息肉眼可读，未被打码）；"
                 "⑤AIGC 标注已落在片头/片尾/文案位（整剧统一）")

    return _report(a, ws, release, fails, warns, notes,
                   {"covers": sorted(covers),
                    "entry_a": sorted(entry_a), "entry_b": sorted(entry_b),
                    "rights": sorted(rights),
                    "legacy": sorted(legacy),
                    "episodes": [f.name for _n, f in sorted(eps.items())]}, downstream)


def _verdict(material_fails: list, downstream: list) -> tuple:
    """分层判定（反馈 P0-6）：返回 (code, 人话)。

    * `ok`               —— 物料齐、成片也齐；
    * `ready_for_export` —— 物料齐，只差下游的发布版成片（连载/未杀青阶段属正常）；
    * `blocked`          —— 物料本身缺项，必须补。

    「物料齐、只差成片」和「物料也没做」是**两种完全不同的状态**，
    混成一句「不齐备」会让已完成的工作在唯一的结构化输出里消失。
    """
    if material_fails:
        return "blocked", "物料缺项 %d 项（先补物料）" % len(material_fails)
    if downstream:
        return "ready_for_export", "物料已备，仅缺下游成片 %d 项（导出后即可发行）" % len(downstream)
    return "ok", "发行资料齐备"


def _report(a, ws, release, fails, warns, notes, summary, downstream=None) -> int:
    # --json 时 stdout **只放 JSON**（供控制台/CI 解析），人读内容一律走 stderr。
    human = sys.stderr if a.json else sys.stdout
    downstream = list(downstream or [])

    # --material-only：连载阶段做增量验收时不把「成片未出」当阻断（转成 WARN）。
    if getattr(a, "material_only", False) and downstream:
        warns = list(warns) + ["（--material-only）成片类缺项不计入阻断：%s"
                               % "；".join(downstream)]
        downstream = []

    code, verdict_cn = _verdict(fails, downstream)
    all_fails = list(fails) + list(downstream)

    if a.json:
        out = {"at": datetime.now().astimezone().replace(microsecond=0).isoformat(),
               "workspace": str(ws), "release_dir": str(release),
               "fails": all_fails, "material_fails": list(fails),
               "downstream": list(downstream),
               "warns": warns, "notes": notes, "found": summary,
               "verdict": code, "verdict_cn": verdict_cn,
               "material_only": bool(getattr(a, "material_only", False))}
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print("=" * 74)
        print("发行资料齐全度检查 · %s" % release)
        print("=" * 74)
        if summary:
            # ★ 反馈 P0-6：五类拆成「已备 / 缺」，成片单独标为**下游依赖**。
            def row(name, have, need):
                miss = max(0, need - have)
                print("  %-12s 已备 %-2s / 需 %-2s  %s"
                      % (name, have, need, "缺 %d" % miss if miss else "齐"))

            have_eps = len(summary.get("episodes") or [])
            print("  %-12s %s%s"
                  % ("发布版成片", ("已备 %d 集" % have_eps) if have_eps else "缺",
                     "" if have_eps else "  ← 属下游依赖，不是物料缺项"))
            print("  %-12s 已备 %s" % ("封面档位", ", ".join(summary["covers"]) or "（无）"))
            row("入口 A 生成过程", len(summary.get("entry_a") or []), ENTRY_MIN)
            row("入口 B 原始文件", len(summary.get("entry_b") or []), ENTRY_MIN)
            row("权利声明", len(summary.get("rights") or []), len(RIGHTS_REQUIRED))
        for w in warns:
            print("  [WARN] %s" % w)
        for b in fails:
            print("  [FAIL] %s" % b)
        for b in downstream:
            print("  [下游] %s" % b)
        print()
        for n in notes:
            print("  · %s" % n)

    # 落痕到 09-发行/release-manifest.json
    # ★ 2026-11-01：`--no-write` 供 Studio 的只读接口调用 —— GET 请求不该改工作区。
    #   检查结论本身是纯计算，写盘只为留痕；要不要留痕由调用方决定。
    if not getattr(a, "no_write", False):
        try:
            release.mkdir(parents=True, exist_ok=True)
            rec = {"at": datetime.now().astimezone().replace(microsecond=0).isoformat(),
                   "workspace": str(ws), "fails": all_fails,
                   "material_fails": list(fails), "downstream": list(downstream),
                   "warns": warns, "found": summary, "min_side": a.min_side,
                   "verdict": code, "verdict_cn": verdict_cn}
            (release / "release-manifest.json").write_text(
                json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        except OSError:
            pass

    if code == "ok":
        print("\n[OK] 发行资料机器校验通过（人工项见上）。", file=human)
        return 0
    if code == "ready_for_export":
        print("\n[WAIT] %s" % verdict_cn, file=human)
        print("       物料部分已通过；导出发布版后重跑本命令即可转 [OK]：", file=human)
        print("       python stages/production/scripts/release_export.py --workspace \"%s\" --all --apply"
              % ws, file=human)
        return 2
    print("\n[BLOCK] %s —— 补齐后再发行。" % verdict_cn, file=human)
    return 2


if __name__ == "__main__":
    sys.exit(main())
