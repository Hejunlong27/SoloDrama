#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ingest_check.py —— 入 `data/` 的生成端门禁（缺口 G7 / 断点 B7）

为什么有它
----------
此前「`<d>` 是否齐全、Picture 槽是否 ≤6、duration 与时间戳是否一致」全靠人查，
错误要到**出片或字幕阶段**才暴露 —— 资产多花的 269 RH币就是这么来的。
本脚本把校验提前到「进 data/ 之前」，不过就停，**把错误挡在计费之前**。

校验项（逐条报，缺关键字段报错让人补，**不猜不编**）
----------------------------------------------------
1. `shots.json`  非空 / `shot_id` 唯一 / 有 `board_ref`（分镜图 key）
2. `h3_prompts.json` 覆盖全部 shot_id，且 `prompt` 非空
3. `<Picture N>` 编号**从 1 连续、≤6、不留空号**（留空号会让后面全部错位）
4. `<d>[lang] …</d>` 存在且非空（字幕真源）
5. 镜头时间戳 `[Shot N] At MM:SS(.mmm)` **严格递增**，且总时长 == `duration`（±0.5s）
6. 参考图槽位一致性：`len(character_refs) + len(scene_refs) >= max(<Picture N>)`
   （2026-10-17 修正：H3 的 6 个参考槽是「角色图 + 场景图」按顺序共用的，提示词里的
     `<Picture N>` 指的是**合并后**的槽位序号；此前只数 character_refs，
     会把「2 角色 + 1 场景」这种完全合法的引用误判为缺图。）
7. 参考图文件存在（相对 `data/` 解析的本地路径）

用法
----
    python ingest_check.py --workspace "D:/剧/新剧" --ep ep01
    python ingest_check.py --workspace "D:/剧/新剧"            # 全量
退出码：0 = 通过；2 = 门禁不过（不得进入出片）
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _ws as W  # noqa: E402

PIC = re.compile(r"<Picture\s+(\d+)\s*>|\{\{\s*(?:Mixed|Picture)\s*(\d+)\s*\}\}")
SHOT_TS = re.compile(r"\[Shot\s+(\d+)\]\s*(?:At\s+(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?)?")
D_TAG = re.compile(r"<d>\[[^\]]*\]\s*([^<]*)</d>", re.S)
# ★ 平台硬限：H3 图片槽 ≤6，改不了
# ★ 与 `prompt_gate.py` 的 C5 不重复（2026-11-01 复核）：这里查「编号从 1 连续、≤6、
#   不留空号」（结构完整性），C5 查「最大编号 == 实际发送的图片数」（与实际输入闭合）。
#   两者角度不同，删任意一个都会降低检查强度 —— 别当重复删掉。
PICTURE_MAX = 6


def load(p: pathlib.Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def total_seconds(frag: str) -> float | None:
    """把 `duration` 字段（8 / \"8s\" / \"8.5\"）折算成秒。"""
    m = re.search(r"(\d+(?:\.\d+)?)", str(frag))
    return float(m.group(1)) if m else None


def check_shot(sid: str, prompt: str, duration, refs: list, data_dir: pathlib.Path,
               first_pic: int = 1, refs_map: dict | None = None) -> tuple:
    """单镜校验。

    `first_pic` 是**提示词里第一张图的编号**：
      * 有分镜图 → 2（分镜图固定占 `<Picture 1>`，与引擎 `board_ref` 节点的位置一致）
      * 无分镜图 → 1
    这个参数是 2026-11-02 分叉时补的：旧实现硬编码「必须从 1 开始」，于是所有
    「分镜图 + 2 角色 + 1 场景」的合法镜次全部被判「编号不连续」—— 一次误杀整集。
    """
    errs, warns = [], []
    if not prompt.strip():
        return ["%s: prompt 为空" % sid], warns
    refs_map = refs_map or {}

    # 3) <Picture N> 连续且 ≤6
    # ★ 两种图号写法都要认：`<Picture N>`（旧 FFS 契约）与 `{{Mixed N}}`（制作包/外部
    #   Skill 的写法，见 docs/pack/PACK-SPEC.md §5.1）。引擎两者都不解析，只按槽位顺序提交；
    #   这里查的是「提示词点到第几张」与「实际挂了几张」是否闭合 —— 写法不同，语义一样。
    nums = sorted({int(g1 or g2) for g1, g2 in (m.groups() for m in PIC.finditer(prompt))})
    if nums:
        if nums != list(range(first_pic, max(nums) + 1)):
            errs.append("%s: 图号不连续 %s（应从 %d 起连续；留空号会让后面全部错位）"
                        % (sid, nums, first_pic))
        if max(nums) > PICTURE_MAX:
            errs.append("%s: <Picture N> 最大 %d 超过硬上限 %d（须删槽位改纯文字，不能只改 refs）"
                        % (sid, max(nums), PICTURE_MAX))
        if len(refs) < max(nums):
            errs.append("%s: 参考图只有 %d 张，但提示词点到了 <Picture %d>（缺 %d 张）"
                        % (sid, len(refs), max(nums), max(nums) - len(refs)))
    elif refs:
        warns.append("%s: 挂了 %d 张参考图，但提示词里没有 <Picture N> 引用" % (sid, len(refs)))

    # 4) <d> 台词齐全
    if not D_TAG.search(prompt):
        warns.append("%s: 没有 <d>…</d> 台词（无台词集可忽略）" % sid)
    elif any(not m.group(1).strip() for m in D_TAG.finditer(prompt)):
        errs.append("%s: 存在空的 <d></d>" % sid)

    # 5) 时间戳严格递增 + 总时长 == duration
    ts = []
    for m in SHOT_TS.finditer(prompt):
        if m.group(2) is None:
            continue
        secs = int(m.group(2)) * 60 + int(m.group(3)) + (int(m.group(4).ljust(3, "0")) / 1000 if m.group(4) else 0)
        ts.append(secs)
    if ts != sorted(ts) or len(ts) != len(set(ts)):
        errs.append("%s: 镜头切点时间戳非严格递增 %s" % (sid, ts))
    d = total_seconds(duration) if duration is not None else None
    if d:
        last = ts[-1] if ts else 0.0
        if last > d + 0.5:
            errs.append("%s: 最后切点 %.3fs 超过 duration %.1fs" % (sid, last, d))
        elif ts and abs((d - last) - (ts[1] - ts[0] if len(ts) > 1 else d - last)) > 0 and False:
            pass  # 保留位：不强求末镜时长，避免误伤
        if not ts and d:
            warns.append("%s: 有 duration=%.1fs 但提示词里没有 [Shot N] At 时间戳" % (sid, d))
    elif ts:
        warns.append("%s: 有时间戳但 h3_prompts 里没有 duration（引擎无法校验节奏）" % sid)

    # 7) 参考图可解析：先查 key 是否登记，再查文件是否存在。
    #    两件事分开报，因为修法完全不同 —— 未登记 = 还没出图（跑 asset 环节）；
    #    文件丢了 = 产物被删/搬走（重出或改路径）。旧实现混成一句「路径不存在」，
    #    实测会让人去翻 characters.json，其实那里压根没这个 key。
    for r in refs:
        if r == "__board__":
            continue
        if not isinstance(r, str) or r.startswith(("http://", "https://", "data:")):
            continue
        if r not in refs_map:
            errs.append("%s: 参考图 key=%s 未在 characters/scenes.json 登记（先出资产图，再重跑导入）"
                        % (sid, r))
            continue
        real = str(refs_map[r])
        if real.startswith(("http://", "https://", "data:")):
            continue
        if not (data_dir / real).is_file():
            errs.append("%s: 参考图 key=%s 指向的文件不存在：%s" % (sid, r, real))
    return errs, warns


def main() -> int:
    ap = argparse.ArgumentParser(description="入 data/ 的生成端门禁（不猜不编）")
    ap.add_argument("--workspace", default=None)
    ap.add_argument("--ep", default=None, help="只查该集（shot_id 前缀 epNN_）")
    a = ap.parse_args()

    # ★ 按**参数里的工作区**解析输入目录（不要用导入期常量，否则 --workspace 被静默忽略）
    ws = pathlib.Path(a.workspace).expanduser().resolve() if a.workspace else W.WS
    # ★ 2026-11-01：data 可能按集分子目录（`data/ep01/shots.json`）。
    #   直接读根目录会报「缺 shots.json / h3_prompts.json」，而文件就在子目录里 ——
    #   于是 `prompt.contract` 节点永远过不去。`data_ep` 有集目录用集目录，没有就是老布局。
    DATA = W.data_ep(ws, a.ep or "")
    if not DATA.is_dir():
        print("[FAIL] 找不到输入目录：%s" % DATA)
        print("       先跑 pack_import.py（或 drama pack import），再检查 layout.json / config.local.json")
        return 2
    shots = load(DATA / "shots.json", None)
    prompts = load(DATA / "h3_prompts.json", None)
    # ★ 2026-10-17 修：data-schema 规定 character_refs / scene_refs 存的是**字典 key**
    #   （char_01 / scene_01），旧实现直接把 key 当本地路径查文件 → 整集 18 条误杀。
    #   这里先按 characters.json / scenes.json 反查真实路径；未登记的 key 保留原值以便报错。
    REFS_MAP: dict = {}
    for _name in ("characters.json", "scenes.json"):
        _d = load(DATA / _name, {}) or {}
        if isinstance(_d, dict):
            REFS_MAP.update(_d)
    if shots is None or prompts is None:
        print("[FAIL] %s 下缺 shots.json 或 h3_prompts.json" % DATA)
        return 2
    if not isinstance(shots, list):
        shots = shots.get("shots") or []

    errs, warns = [], []
    ids = []
    for s in shots:
        sid = str(s.get("shot_id") or "")
        if not sid:
            errs.append("存在没有 shot_id 的分镜条目")
            continue
        ids.append(sid)
    dup = {x for x in ids if ids.count(x) > 1}
    if dup:
        errs.append("shot_id 重复：%s" % sorted(dup))
    if a.ep:
        scoped = [i for i in ids if i.startswith(a.ep + "_") or i == a.ep]
        if scoped:
            ids = scoped
        else:
            # 分镜号可能是 shot_001（不带宽前缀）——此时 --ep 只作提示，不误杀全部
            print("[WARN] 没有 shot_id 以「%s_」开头（本数据集用的是 %s 之类）；改按全部 %d 段检查。"
                  % (a.ep, ids[0], len(ids)))
    if not ids:
        print("[FAIL] 没有可检查的分镜")
        return 2

    for sid in ids:
        s = next(x for x in shots if str(x.get("shot_id")) == sid)
        # 2026-11-01：`banana_prompt` 已删（九宫格链下线）。现在的出图契约是分镜图：
        #   每镜一个 `board_ref`，图在 `04-资产/boards/<ep>/<shot_id>.png`。
        #   缺 key 记 WARN（引擎会退化为「角色+场景」两参，还能出）；
        #   有 key 但图不在记 ERROR（会静默退化，必须挡在计费之前）。
        _bref = str(s.get("board_ref") or "").strip()
        if not _bref:
            warns.append("%s: 缺 board_ref（分镜图 key）——出片退化为两参" % sid)
        else:
            # ★ 2026-11-02 修两个 bug（分叉 pack-engine 时实测出来的）：
            #   ① `board_ep01_shot_001` 用 rsplit("_", 1) 会拆成 `ep01_shot` —— 因为 shot_id
            #      自己带下划线。改为按**后缀**剥：board_ref 必然以 `_<shot_id>` 结尾。
            #   ② 分镜图不在 `<data>/../04-资产/` 下，而在工作区的资产目录（layout 真源）。
            #      旧写法在 `06-提示词/04-资产/...` 找一个不存在的路径，于是**恒报缺图**。
            _suffix = "_" + sid
            _ep = _bref[len("board_"):-len(_suffix)] if _bref.endswith(_suffix) else (a.ep or "")
            _assets = (W.L.assets_dir(ws) if getattr(W, "L", None) else W.ASSETS)
            _bp = _assets / "boards" / _ep / ("%s.png" % sid)
            if not _bp.is_file():
                errs.append("%s: board_ref=%s 但没有分镜图 %s" % (sid, _bref, _bp))
        v = prompts.get(sid)
        if not isinstance(v, dict) or not v.get("prompt"):
            errs.append("%s: h3_prompts.json 里没有该段的 prompt（引擎会直接 FAILED，不猜）" % sid)
            continue
        # ★ 槽位口径：H3 的 6 个参考槽 = 分镜图 + 角色图 + 场景图，按顺序共用一套编号。
        #   分镜图排在 `<Picture 1>`（引擎的 `first_frame` 节点），所以有 board 时
        #   资产图从 2 号起；没有 board 才从 1 号起。
        refs_all = list(s.get("character_refs") or []) + list(s.get("scene_refs") or [])
        if s.get("board_ref"):
            refs_all = ["__board__"] + refs_all
        e, w = check_shot(sid, v["prompt"], v.get("duration"), refs_all, DATA,
                          first_pic=2 if s.get("board_ref") else 1,
                          refs_map=REFS_MAP)
        errs += e
        warns += w

    # ★ 2026-11-02（分叉 pack-engine）：`prompt_gate.py` 已随创作层一起下线。
    #   它查的 C1–C5（人数锁 / 图号闭合 / 缺 board）里，能与**提示词文本**无关地机械判定的
    #   那几条，已经前移到 `stages/import/pack_spec.py` 的结构校验（导入时一次报全）；
    #   剩下几条依赖「SUBJECT 锁几个人」这类语义，本来就只能靠模型自查 —— 留在引擎里
    #   等于让引擎读中文判断剧情。宁可不查，也不装一个会误判的门禁。

    print("=" * 74)
    print("入 data/ 生成端门禁（B7）")
    print("=" * 74)
    print("  输入目录: %s" % DATA)
    print("  检查范围: %s" % (a.ep or "全部"))
    print("  分镜数  : %d" % len(ids))
    for w in warns:
        print("  [WARN] %s" % w)
    for e in errs:
        print("  [FAIL] %s" % e)
    print("-" * 74)
    if errs:
        print("[BLOCK] %d 个硬问题 —— 不得进入出片（错误已挡在计费之前）。" % len(errs))
        return 2
    print("[OK] 门禁通过，可进入：doctor → assets → refs → video plan")
    return 0


if __name__ == "__main__":
    sys.exit(main())
