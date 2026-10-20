#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""script_rewrite.py —— 第④部分「剧本改写」

职责（**只搭规划骨架与红线，正文交 LLM 按 prompt 填**）
-------------------------------------------------------
对应交付的第四部分：**将一部「很颠」的西语短剧剧本改写为完整 N 集规划（默认 30 集 × 60 秒），
每集须包含核心冲突、剧情反转与钩子设计；整体节奏紧凑、钩子密集、爽点高频。**

本脚本做三件确定性的事：

1. **集数蓝图 `plan`**：把定位卡（③）落到**逐集规划**——每集给出
   `核心冲突 / 剧情反转 / 钩子 / 钩子类型 / 情绪走向 / 节拍说明`，
   并植入**爆点节拍**（中型爆点每 4 集、大型爆点每 10 集、集尾钩子短收）。
   源剧本（`source-script.md`，"很颠"的原稿）会先被登记与体检。
2. **FFS 骨架 `build`**：按 `docs/creation/ffs-spec.md` 生成某集的文件头 + N 个空镜头块，
   字段与顺序合规，LLM 只需替换占位符。
3. **结构自检 `lint`**：对填充后的剧本做确定性检查（头字段/镜头块/禁字段/DUR/时长口径/
   镜头数/台词长度），把错误挡在 `tools/cli.py check` 之前。

输入：`creation/02-positioning/positioning.json`（rank N 定位卡）+ `creation/brief.json`
     + `creation/03-script/source-script.md`（可选，待改写的源剧本）
     + `creation/01-breakdown/breakdown.json`（可选，拆解结论）
     + `creation/03-script/reference-structure.json`（可选，对标结构）
输出：`creation/03-script/blueprint.json` + `blueprint.md` + `script-brief.md`（+ `skeleton_ep_XX.md`）

命令
----
    python script_rewrite.py diagnose [--check|--confirm|--force]   ← A/B/C 诊断（写正文前门禁）
    python script_rewrite.py plan [--rank 1] [--episodes 60] [--emit-brief] [--from-outline x.md]
    python script_rewrite.py review [--profile revenge] [--write-fixes]   ← 第二轮 结构审查
    python script_rewrite.py build --ep 1 [--shots 8] [--emit]
    python script_rewrite.py lint --ep 1
    python script_rewrite.py audience [--check|--force]              ← 第四轮 观众视角审稿
    python script_rewrite.py ref-template
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _common as C  # noqa: E402
import genre_formula as G  # noqa: E402  ★ 题材公式（S2.5）：跳过选题、给每集公式化要求

# ---- STYLE LOCK 预设（与 docs/creation/stylelock-presets.md 一致） ----------
BASE_LOCK = "no watermark, no subtitle, no text overlay, no logo"
STYLE_LOCKS = {
    "都市情感": "webtoon-adapted live-action style, soft warm lighting, pastel color palette, "
                "detailed character design, gentle bokeh in close-ups, 2.39:1 widescreen, " + BASE_LOCK,
    "逆袭": "webtoon-adapted live-action style, sleek modern interiors, sharp contrast, "
            "high-fashion styling, cool steel-blue accents, 2.39:1 widescreen, " + BASE_LOCK,
    "职场": "webtoon-adapted live-action style, sleek modern interiors, sharp contrast, "
            "high-fashion styling, cool steel-blue accents, 2.39:1 widescreen, " + BASE_LOCK,
    "热血": "webtoon-adapted live-action style, dynamic action framing, dramatic rim lighting, "
            "bold inking, dust particles in fight scenes, 2.39:1 widescreen, " + BASE_LOCK,
    "脑洞": "webtoon-adapted live-action style, desaturated palette with neon accents, uncanny detail, "
            "subtle lens distortion, 2.39:1 widescreen, " + BASE_LOCK,
    "奇幻": "webtoon-adapted dark fantasy style, moonlit cool palette with blood-red accents, "
            "ornate gothic interiors, sharp inking, fur and fabric detail, 2.39:1 widescreen, " + BASE_LOCK,
    "狼人": "webtoon-adapted dark fantasy style, moonlit cool palette with blood-red accents, "
            "ornate gothic interiors, sharp inking, fur and fabric detail, 2.39:1 widescreen, " + BASE_LOCK,
    "霸总": "webtoon-adapted live-action style, sleek modern interiors, sharp contrast, "
            "high-fashion styling, cool steel-blue accents, 2.39:1 widescreen, " + BASE_LOCK,
    "_default": "webtoon-adapted live-action style, cinematic framing, controlled contrast, "
                "detailed character design, 2.39:1 widescreen, " + BASE_LOCK,
}

DEFAULT_EPISODES = 30        # ★ 2026-10-20（V0.5）用户拍板：默认 30 集（由 40 下调）
DEFAULT_EP_SECONDS = 60      # ★ 2026-10-20（V0.5）用户拍板：单集 60 秒（由 70 下调）
ACT_SPLIT = [("起", 0.15), ("承", 0.45), ("转", 0.75), ("合", 1.0)]
HOOK_TYPES = ["身份悬念", "危机逼近", "关系反转", "秘密揭露", "选择困境", "意外登场", "代价预告"]
MID_BOOM_EVERY = 3           # 中型爆点（30 集口径 = 10 次；40 集口径为 4，**密度保持一致**）
BIG_BOOM_EVERY = 7           # 大型爆点（30 集口径 = 4 次；40 集口径为 10，**密度保持一致**）

# ===========================================================================
# ★ 留存率导向的剧本结构（2026-10-16 新增）
# ---------------------------------------------------------------------------
# 背景：用户实测几部剧「内容吸引度不够」—— 症状是前几集没能抓住人、每集中段平。
# 因此本层把「留存结构」从"写作建议"升级为**可机器校验的硬结构**：
#
#   每集必含四件套（缺一即返工）：
#     ① cold_open      开场钩子 —— 前 3-5 秒内出现「异常/冲突/悬念」之一
#                       EP1 为**黄金 3 秒**：必须把全剧最高冲突前置，禁止背景铺垫开场
#     ② core_conflict  核心冲突 —— 本集「谁 vs 谁 vs 什么」
#     ③ reversal       一次反转 —— 且必须改变力量对比或信息格局（不能只是情绪起伏）
#     ④ hook           集尾钩子 —— 让人必须点下一集；**类型不得与前两集连续重复**
#
#   留存三段（retention_role）：
#     EP1-3   「拉新攻坚」三连强钩子链，禁止出现铺垫集、禁止慢热
#     EP4-10  「留存活口」每集至少一次「小爽」落点，爆点密度最高
#     EP11+   「转化与收束」按爆点节拍推进，收尾前 2 集必须再拉一次强钩子
# ===========================================================================
RETENTION_ROLES = [
    (3, "拉新攻坚", "三连强钩子链；EP1 前 3 秒必须出现最高冲突，禁止背景铺垫开场"),
    (8, "留存活口", "每集至少一次「小爽」落点；中段不得出现连续两集无爆点"),
    (10 ** 9, "转化与收束", "按爆点节拍推进；收尾前 2 集必须再拉一次强钩子，留悬念收束"),
]

# 开场钩子（cold_open）句库：按留存段分配，保证前 3 秒有信息量
COLD_OPEN_BANK = {
    "拉新攻坚": [
        "冷开场直接抛出本集最尖锐的矛盾，主角处境一句话说清",
        "开场即冲突现场，先给结果再倒叙成因（3 秒内出画面）",
        "开场用一句反常识台词制造认知落差",
    ],
    "留存活口": [
        "开场承接上集钩子，10 秒内给出新变量",
        "开场以对手视角开场，让观众先看到危机全貌",
        "开场用一次小胜/小爽落点回报观众耐心",
    ],
    "转化与收束": [
        "开场给出倒计时或代价预告，明确终局临近",
        "开场回收一条早期伏笔，制造「原来如此」的满足感",
        "开场让主角主动出击，扭转被动局面",
    ],
}


def _retention_role(ep: int) -> tuple:
    """返回 (留存段名, 段内说明)。"""
    for upto, name, note in RETENTION_ROLES:
        if ep <= upto:
            return name, note
    return RETENTION_ROLES[-1][1], RETENTION_ROLES[-1][2]


CONFLICT_BANK = {
    "起": ["身份错位引发冲突", "至亲/资源被夺", "被误解并驱逐", "契约/误认开局"],
    "承": ["对手步步施压", "旧敌卷土重来", "真相碎片浮现", "信任开始崩塌"],
    "转": ["真凶身份揭露", "主角力量/身份觉醒", "盟友背叛", "公开对质"],
    "合": ["终极对决", "真相大白与清算", "代价与和解", "双强联手收官"],
}
REVERSAL_BANK = {
    "起": ["看似劣势实为伏笔", "救命恩人身份可疑", "主角底牌尚未亮出"],
    "承": ["示弱者才是操盘手", "关键证据被人为篡改", "最亲近者递出关键线索"],
    "转": ["背叛者竟是保护者", "复仇目标并非真凶", "主角身份高于对手"],
    "合": ["反派自曝致命破绽", "牺牲换来全局翻盘", "旧仇握手结成同盟"],
}
HOOK_TEMPLATE = {
    "身份悬念": "揭出主角身世/血脉的一角，但未说全",
    "危机逼近": "对手的下一步已经启动，倒计时开始",
    "关系反转": "最信任的人态度突然反转",
    "秘密揭露": "被隐藏多年的秘密浮出水面",
    "选择困境": "主角被迫在两个人/两件事之间选一个",
    "意外登场": "关键人物在此刻意外登场",
    "代价预告": "翻盘的代价被明确提出",
}
EMOTION_CYCLE = ["压抑", "期待", "小爽", "悬", "大爽", "暖", "虐", "燃"]
HOOK_CHAIN_FIRST3 = ["身份悬念", "危机逼近", "秘密揭露"]
# ★ 2026-10-20（V0.5）：剧情节点编号化的四件套（下游分镜/H3 提示词按 id 声明服务哪个节点）
PLOT_ROLES = (("cold_open", "cold_open"), ("core_conflict", "core_conflict"),
              ("reversal", "reversal"), ("hook", "hook"))

REDLINE_HARD = [
    "**不复刻**：不得照搬源剧本或任何对标剧的台词、镜序、角色名与专属设定，只借鉴结构与爽点机制。",
    "**不重叠**：同一批选题之间不得复用同一核心冲突结构。",
    "**反套路可验证**：若用「反套路」作卖点，必须写明反的是哪个具体套路（如「无替身梗、无失忆梗」）。",
    "**本土化**：台词为口语西语（拉美通用），避免翻译腔；文化元素须为拉美/西语观众可代入（家庭、阶层、都市、足球等）。",
    "**节奏铁律**：每集必须同时具备「核心冲突 + 一次反转 + 集尾钩子」；整体钩子密集、爽点高频。",
]

FFS_HEADER_ORDER = ["TITLE", "EP", "PLATFORM", "STYLE LOCK", "CHAR", "SCENE"]
FFS_SHOT_FIELDS = ["SHOT", "LOCATION", "TIME", "CHAR", "ACTION", "DIALOG", "VO", "SFX"]
FFS_FORBIDDEN = ["MOOD", "CAMERA", "EMOTION", "MUSIC", "LIGHT"]
# ★ 2026-10-20（V0.5）：单集秒数 → (镜数下限, 镜数上限, 总时长下限, 总时长上限)
#   60 秒为默认口径；70/90 保留给老项目与 90 秒老口径，**按 blueprint 的 ep_seconds 选档**，
#   口径与 tools/core/schema.py::SECONDS_PROFILES 保持一致（两处同步改）。
SECONDS_PROFILES = {
    60: (5, 10, 60, 80),
    70: (5, 12, 70, 95),
    90: (6, 15, 90, 120),
}
SHOT_MIN, SHOT_MAX, TOTAL_MIN, TOTAL_MAX = SECONDS_PROFILES[DEFAULT_EP_SECONDS]
DUR_MIN, DUR_MAX = 4, 15


def bounds_for(ep_seconds) -> tuple:
    """按单集秒数取 FFS 校验口径；未知秒数取最接近的档。"""
    sec = int(ep_seconds or DEFAULT_EP_SECONDS)
    return SECONDS_PROFILES[min(SECONDS_PROFILES, key=lambda s: abs(s - sec))]


# ---------------------------------------------------------------------------
# 源剧本登记与体检
# ---------------------------------------------------------------------------
def inspect_source(ws: pathlib.Path) -> dict:
    p = C.pdir(ws, C.SOURCE_SCRIPT)
    text = C.read_text(p)
    if not text:
        return {"present": False, "path": str(p),
                "note": "未找到源剧本（可放入 %s 供改写参考）" % p}
    acts = re.findall(r"(?m)^\s*(?:第\s*[一二三四五六七八九十\d]+\s*幕|Act\s*\d+|Part\s*\d+)", text)
    scenes = re.findall(r"(?m)^\s*(?:INT\.|EXT\.|内景|外景|场\d+)", text)
    return {"present": True, "path": str(p), "chars": len(text),
            "lines": text.count("\n") + 1,
            "acts_detected": [a.strip() for a in acts][:12],
            "scenes_detected": len(scenes),
            "note": "源剧本已登记；改写时**保留其核心人设与设定魅力**，仅重排结构、加密钩子。"}


# ---------------------------------------------------------------------------
# 第④部分核心：逐集规划
# ---------------------------------------------------------------------------
def _act_of(i: int, n: int) -> str:
    r = i / max(n, 1)
    for act, upto in ACT_SPLIT:
        if r <= upto:
            return act
    return ACT_SPLIT[-1][0]


def _pick(bank: list, i: int) -> str:
    return bank[(i - 1) % len(bank)]


# ---------------------------------------------------------------------------
# ★ 2026-10-20（反馈 P2-3）：人工拆解表 → 直接覆盖 plan 的通用句库
# ---------------------------------------------------------------------------
# 事故：`plan` 生成的 40 集 cold_open/core_conflict/reversal/hook 全是句库套话
# （「女主 vs 一个阶梯式的压迫者集团」），必须逐集手写覆盖 —— 40 集重写一遍节拍
# 是大工作量，而且容易与源文脱节。这里让 plan 直接吃人工拆解表，减少一次搬运。
#
# 支持的写法（任一）：
#   | EP01 | 女主被赶出家门 | 尾钩：她把钥匙扔回桌上 |
#   EP01: 女主被赶出家门
#   01 | 女主被赶出家门 | 核心冲突 | 反转 | 钩子
# 列数含义（1 列 → 只覆盖核心冲突；2+ 列 → 依次覆盖 cold_open/core_conflict/reversal/hook/emotion）
OUTLINE_LINE = re.compile(r"^\s*\|?\s*(?:EP)?\s*(\d{1,3})\s*[|｜:：\t]\s*(.+?)\s*\|?\s*$", re.I)
_OUTLINE_KEYS = ("cold_open", "core_conflict", "reversal", "hook", "emotion")


def parse_outline(path: pathlib.Path) -> tuple:
    """解析人工拆解表 → ({ep: {字段: 文本}}, 告警列表)。认不出就跳过，不猜。"""
    rows, warns = {}, []
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as e:
        return {}, ["读不了拆解表 %s：%s" % (path, e)]
    for ln, line in enumerate(text.splitlines(), 1):
        st = line.strip()
        if not st or st.startswith("#") or set(st) <= set("-|: "):
            continue
        m = OUTLINE_LINE.match(st)
        if not m:
            continue
        ep = int(m.group(1))
        cells = [c.strip() for c in re.split(r"[|｜]", m.group(2)) if c.strip()]
        if not cells:
            warns.append("L%d：EP%02d 没有内容，已跳过" % (ln, ep))
            continue
        if len(cells) == 1:
            row = {"core_conflict": cells[0]}
        else:
            row = {k: v for k, v in zip(_OUTLINE_KEYS, cells)}
        if ep in rows:
            # 同一集出现两次：保留**先出现**的那行（通常是主表格），避免后面的补充行
            # 把四列信息缩成单列，静默丢掉反转/钩子。
            warns.append("L%d：EP%02d 重复出现，已保留先出现的那行" % (ln, ep))
            continue
        rows[ep] = row
    return rows, warns


def plan(ws: pathlib.Path, rank: int = 1, episodes: int | None = None, dry: bool = False,
         genre: str | None = None, from_outline: str | None = None) -> int:
    """集数规划。两种入口：

    * **常规**：读 ③选题定位卡（`positioning.json`；
    * **题材公式**：`--genre female-comeback`，或工作区已有 `genre-plan.json`（套用过的公式）
      → **跳过选题**，直接用公式的 topic_card + 逐集公式化要求（打脸/阶梯/见证者/压放/里程碑/金句）。
    """
    gf = None
    if genre:
        try:
            gf = G.load(genre)
        except KeyError as e:
            print("[FAIL] %s" % e)
            return 2
    else:
        gp = G.load_plan(ws)
        if gp and gp.get("_formula"):
            gf, genre = gp["_formula"], gp["genre"]

    if gf:
        card = G.build_topic_card(gf)
        pos_obj = {"selected": [card], "_from_genre": gf["id"]}
        print("[i] 题材公式模式：%s —— **跳过选题环节**（S2a/S2b 不跑）" % gf.get("label"))
    else:
        pos_obj = C.read_json(C.pdir(ws, C.POSITIONING))
        if not isinstance(pos_obj, dict) or not pos_obj.get("selected"):
            print("[FAIL] 找不到③定位卡：%s（先跑 hit_selection.py select）" % C.pdir(ws, C.POSITIONING))
            print("       或者套用题材公式跳过选题：genre_formula.py apply --genre <id> → "
                  "script_rewrite.py plan --genre <id>")
            return 2
        card = next((x for x in pos_obj["selected"] if x.get("rank") == rank), None)
        if not card:
            print("[FAIL] 定位卡里没有 rank=%d" % rank)
            return 2
    brief = C.read_json(C.pdir(ws, C.BRIEF)) or {}
    bd = C.read_json(C.pdir(ws, C.BREAKDOWN)) or {}
    src = inspect_source(ws)
    n = int(episodes or brief.get("ep_total") or DEFAULT_EPISODES)
    if n < 6:
        print("[FAIL] 集数过少（%d）：短剧规划至少 6 集" % n)
        return 2

    style = _pick_style_lock(str(card.get("genre_direction")))
    platform = (card.get("audience_profile") or {}).get("platform") or brief.get("platform") or "TikTok"

    # ★ 反馈 P2-3：人工拆解表（可选）。给了就以它为准，覆盖句库。
    outline_rows, outline_warns = {}, []
    if from_outline:
        op = pathlib.Path(from_outline).expanduser()
        if not op.is_file():
            print("[FAIL] --from-outline 指向的拆解表不存在：%s" % op)
            return 2
        outline_rows, outline_warns = parse_outline(op)

    hf = (gf or {}).get("hook_formula") or {}
    # 前 3 集爆款钩子公式（题材公式自带；EP1 黄金 3 秒 → EP3 首个小打脸）
    hf_map = {1: ("ep1_golden_3s", "ep1_tail"), 2: ("ep2_mid", "ep2_tail"), 3: ("ep3_mid", "ep3_tail")}

    episodes_list = []
    for i in range(1, n + 1):
        act = _act_of(i, n)
        hook_type = HOOK_CHAIN_FIRST3[i - 1] if i <= 3 else HOOK_TYPES[(i - 1) % len(HOOK_TYPES)]
        boom = ("big" if i % BIG_BOOM_EVERY == 0 else ("mid" if i % MID_BOOM_EVERY == 0 else "none"))
        r_name, r_note = _retention_role(i)
        cold = COLD_OPEN_BANK[r_name][(i - 1) % len(COLD_OPEN_BANK[r_name])]
        item = {
            "ep": i, "act": act,
            "retention_role": r_name,
            "cold_open": cold,
            "core_conflict": "%s：%s" % (_pick(CONFLICT_BANK[act], i), card.get("conflict") or "主线对抗"),
            "reversal": _pick(REVERSAL_BANK[act], i),
            "hook_type": hook_type,
            "hook": "%s（%s）" % (HOOK_TEMPLATE[hook_type], card.get("logline") or "主线钩子"),
            "emotion": EMOTION_CYCLE[(i - 1) % len(EMOTION_CYCLE)],
            "beat_note": ("★大型爆点集" if boom == "big" else ("中型爆点集" if boom == "mid" else "常规推进")),
            "boom": boom,
        }
        if gf:
            # ★ 题材公式模式：每集附公式化要求（打脸/等级/见证者/压放/里程碑/金句）
            item.update(G.episode_overlay(gf, i, n))
            if i in hf_map:
                k1, k2 = hf_map[i]
                item["cold_open"] = "【前3集钩子公式】%s" % (hf.get(k1) or cold)
                item["hook"] = "【集尾钩子公式】%s" % (hf.get(k2) or item["hook"])
            if i == 1:
                item["cold_open"] = "★黄金 3 秒（公式）：%s" % (hf.get("ep1_golden_3s") or "")
        elif i == 1:
            item["cold_open"] = "★黄金 3 秒：把全剧最高冲突前置到开场（禁止背景铺垫、禁止慢热）"
        # ★ 反馈 P2-3：人工拆解表优先级最高（放在公式/黄金3秒之后覆盖）
        if outline_rows.get(i):
            item.update(outline_rows[i])
            item["from_outline"] = True
        # ★ V0.5：本集四个剧情节点编号化 —— 分镜/H3 提示词必须能指回其中之一，
        #   否则「剧本一个内容、分镜另一个内容」不会被任何门禁发现。见 script_continuity.py
        item["plot_points"] = [
            {"id": "EP%02d-P%d" % (i, j), "role": role, "text": str(item.get(key) or "")}
            for j, (role, key) in enumerate(PLOT_ROLES, 1)
        ]
        episodes_list.append(item)

    # ★ 题材结构侧重（只声明「靠什么撑住观众」，不改变既有逐集字段）
    prof = match_profile(" ".join(str(card.get(k) or "") for k in
                                 ("title", "logline", "conflict", "genre_direction")))

    hook_chain = [{"ep": e["ep"], "type": e["hook_type"], "hook": e["hook"]}
                  for e in episodes_list[:3]]
    act_structure = [{"act": a, "ep_range": "%d-%d" % (int(prev * n) + 1, int(upto * n)),
                      "share_pct": round((upto - prev) * 100, 1)}
                     for (a, upto), prev in zip(ACT_SPLIT, [0.0] + [x[1] for x in ACT_SPLIT[:-1]])]

    obj = {
        "generated_at": C.now_iso(), "module": "S3-script-rewrite-plan", "schema_version": 1,
        "title": card.get("title"), "title_es": card.get("title_es"),
        "market": (card.get("audience_profile") or {}).get("market") or brief.get("market"),
        "platform": platform, "form": brief.get("form") or "AI漫剧",
        "total_ep": n, "ep_seconds": brief.get("ep_seconds") or DEFAULT_EP_SECONDS,
        "style_lock": style, "rank": rank,
        "source_script": src,
        "positioning_digest": {
            "logline": card.get("logline"), "conflict": card.get("conflict"),
            "audience_profile": card.get("audience_profile"),
            "genre_direction": card.get("genre_direction"),
            "differentiation_selling_points": card.get("differentiation_selling_points"),
        },
        "act_structure": act_structure, "hook_chain": hook_chain,
        "boom_cadence": {"mid_every": MID_BOOM_EVERY, "big_every": BIG_BOOM_EVERY,
                         "mid_count": sum(1 for e in episodes_list if e["boom"] == "mid"),
                         "big_count": sum(1 for e in episodes_list if e["boom"] == "big")},
        # ★ 留存率导向结构（2026-10-16）：四件套 + 三段留存 + 校验口径
        "retention_plan": {
            "framework": ["cold_open（开场钩子）", "core_conflict（核心冲突）",
                          "reversal（一次反转，须改变力量对比或信息格局）", "hook（集尾钩子）"],
            "roles": [{"role": n, "ep_upto": u, "note": note}
                      for u, n, note in RETENTION_ROLES if u < 10 ** 9]
                     + [{"role": RETENTION_ROLES[-1][1], "ep_upto": None, "note": RETENTION_ROLES[-1][2]}],
            "ep1_golden_3s": "EP1 前 3 秒必须出现全剧最高冲突（禁止铺垫开场）",
            "hook_no_repeat_window": 2,   # 钩子类型不得与前 2 集连续重复
            "rationale": "用户实测多部剧「内容吸引度不够」；本结构把留存要求变成可机器校验的硬字段。",
        },
        "episodes": episodes_list,
        "hot_tropes": [t["name"] for t in (bd.get("tropes") or []) if t.get("count", 0) >= 2][:6],
        "differentiation_redlines": REDLINE_HARD + list(card.get("differentiation_redlines") or []),
        # ★ 题材公式（S2.5）：套用时把公式与 QC 口径一并落盘，供 genre_formula.py check 复核
        "topic_source": "genre-formula" if gf else "positioning",
        "genre": ({
            "id": genre, "label": gf.get("label"),
            "engine": (gf.get("engine") or {}).get("formula"),
            "phase_ids": [p.get("id") for p in (gf.get("phases") or [])],
            "punch_ladder": gf.get("punch_ladder"),
            "punch_five_beats": gf.get("punch_five_beats"),
            "hook_formula": gf.get("hook_formula"),
            "quote_rules": (gf.get("dialogue_policy") or {}).get("quote_rules"),
            "qc": gf.get("qc"),
            "skipped_topic": True,
            "note": "命中关键词即跳过选题；每集 punch/punch_level/witness/stake/milestone/quote 由公式生成。",
        } if gf else None),
        "structure_profile": ({
            "id": prof.get("id"), "label": prof.get("label"),
            "structure_focus": prof.get("structure_focus"),
            "audience_promise": prof.get("audience_promise"),
            "must_check": prof.get("must_check"),
            "note": "结构侧重见 references/genre-profiles.json；review 按 must_check 把 WARN 升为 FAIL。",
        } if prof else None),
        "note": "本文件是④改写的**结构规划**；每集正文由 LLM 按 prompts/s3-script-rewrite.md 填。",
    }

    print(C.hr())
    print("④ 剧本改写 · 集数规划（源剧本改写为 %d 集）" % n)
    print(C.hr())
    print("  选题      : %s" % ("**跳过选题**（题材公式 %s）" % gf.get("label") if gf
                                else "#%d %s（%s）" % (rank, card.get("title"), card.get("genre_direction"))))
    print("  平台/形态 : %s / %s" % (platform, obj["form"]))
    print("  源剧本    : %s" % ("已登记（%d 字 / 场景 %d）" % (src.get("chars", 0), src.get("scenes_detected", 0))
                              if src.get("present") else "未提供（按定位卡原创结构）"))
    print("  幕结构    : %s" % "；".join("%s EP%s" % (a["act"], a["ep_range"]) for a in act_structure))
    print("  钩子链    : %s" % " → ".join("%s(%s)" % (h["type"], h["ep"]) for h in hook_chain))
    print("  留存结构  : 每集四件套（开场钩子 + 核心冲突 + 一次反转 + 集尾钩子）")
    if prof:
        print("  结构侧重  : %s（%s）｜审查必检：%s"
              % (" → ".join(prof.get("structure_focus") or []), prof.get("label"),
                 "、".join(prof.get("must_check") or []) or "-"))
    if from_outline:
        filled = sorted(ep for ep in outline_rows if 1 <= ep <= n)
        extra = sorted(ep for ep in outline_rows if ep > n or ep < 1)
        print("  人工拆解  : %s（覆盖 %d/%d 集）"
              % (pathlib.Path(from_outline).name, len(filled), n))
        missing = [i for i in range(1, n + 1) if i not in filled]
        if missing:
            print("  [WARN] 仍有 %d 集用句库默认值：EP%s"
                  % (len(missing), ",EP".join("%02d" % i for i in missing[:12])
                     + ("…" if len(missing) > 12 else "")))
        if extra:
            print("  [WARN] 拆解表里有超出集数范围的行（已忽略）：EP%s"
                  % ",EP".join("%02d" % i for i in extra[:8]))
        for w in outline_warns:
            print("  [WARN] %s" % w)
        obj["outline_source"] = str(pathlib.Path(from_outline).expanduser())
        obj["outline_covered"] = filled
    _roles = obj["retention_plan"]["roles"]
    _seg, _lo = [], 1
    for r in _roles[:-1]:
        _seg.append("EP%d-%s %s" % (_lo, r["ep_upto"], r["role"]))
        _lo = (r["ep_upto"] or 0) + 1
    _seg.append("EP%d+ %s" % (_lo, _roles[-1]["role"]))
    print("              三段：%s" % "；".join(_seg))
    print("              EP1 = %s" % obj["retention_plan"]["ep1_golden_3s"])
    print("  爆点节拍  : 中型 %d 次（每 %d 集）/ 大型 %d 次（每 %d 集）"
          % (obj["boom_cadence"]["mid_count"], MID_BOOM_EVERY,
             obj["boom_cadence"]["big_count"], BIG_BOOM_EVERY))
    if gf:
        ladder = " → ".join("L%d %s" % (l.get("level"), l.get("name")) for l in gf.get("punch_ladder") or [])
        step = "；".join("%s %s" % (p.get("id"), p.get("name")) for p in gf.get("phases") or [])
        print("  题材公式  : %s" % gf.get("label"))
        print("  公式引擎  : %s" % ((gf.get("engine") or {}).get("formula") or ""))
        print("  阶段      : %s" % step)
        print("  打脸阶梯  : %s" % ladder)
        print("  压放呼吸  : 每 3 集至少 1 压 1 放（本规划已按 %s 循环标注）" % "→".join(G.STAKE_CYCLE))
    print("  前 8 集预览：")
    for e in episodes_list[:8]:
        extra = ""
        if gf:
            extra = "｜%s%s｜打脸 L%d%s" % (e.get("stake") or "", "★里程碑" if e.get("milestone") else "",
                                            e.get("punch_level") or 0,
                                            "（有见证者）" if e.get("witness") else "")
        print("    EP%02d [%s] %s｜反转：%s｜钩子(%s)：%s%s"
              % (e["ep"], e["act"], e["core_conflict"][:22], e["reversal"][:16],
                 e["hook_type"], e["hook"][:24], extra))
    print("    … 共 %d 集，逐集见 blueprint.json / blueprint.md" % n)

    if dry:
        print("[dry] 未落盘。")
        return 0
    p1 = C.write_json(C.pdir(ws, C.BLUEPRINT), obj)
    p2 = C.write_text(C.pdir(ws, "creation/03-script/blueprint.md"), render_blueprint_md(obj))
    p3 = C.write_text(C.pdir(ws, "creation/03-script/script-brief.md"), render_script_brief(obj))
    print("\n[OK] 已写出：\n     %s\n     %s\n     %s" % (p1, p2, p3))
    print("     下一步：LLM 按 prompts/s3-script-rewrite.md 写第 1 集 → "
          "script_rewrite.py build --ep 1 --emit → lint --ep 1")
    return 0


def _pick_style_lock(track: str) -> str:
    for k, v in STYLE_LOCKS.items():
        if k != "_default" and k in str(track):
            return v
    return STYLE_LOCKS["_default"]


def render_blueprint_md(o: dict) -> str:
    L = ["# ④ 剧本改写 · 集数规划（%s）" % o["generated_at"][:19], "",
         "- 剧名：%s（%s）　市场：%s　平台：%s　形态：%s"
         % (o["title"], o.get("title_es") or "-", o["market"], o["platform"], o["form"]),
         "- 集数：%d 集 × %d 秒　STYLE LOCK：`%s`" % (o["total_ep"], o["ep_seconds"], o["style_lock"][:50] + "…"),
         "- 源剧本：%s" % (o["source_script"].get("note") if o["source_script"].get("present")
                          else "未提供（按定位卡原创结构）"),
         "- 爆点节拍：中型 %d 次 / 大型 %d 次" % (o["boom_cadence"]["mid_count"], o["boom_cadence"]["big_count"]),
         "", "## 幕结构与钩子链", ""]
    L += ["| 幕 | 集数区间 | 占比 |", "|---|---|---|"]
    L += ["| %s | EP%s | %.1f%% |" % (a["act"], a["ep_range"], a["share_pct"]) for a in o["act_structure"]]
    L += ["", "| 集 | 钩子类型 | 钩子 |", "|---|---|---|"]
    L += ["| EP%d | %s | %s |" % (h["ep"], h["type"], h["hook"]) for h in o["hook_chain"]]
    L += ["", "## 逐集规划（核心冲突 / 反转 / 钩子 / 情绪）", "",
          "| 集 | 幕 | 核心冲突 | 剧情反转 | 钩子 | 钩子类型 | 情绪 | 节拍 |",
          "|---|---|---|---|---|---|---|---|"]
    L += ["| EP%02d | %s | %s | %s | %s | %s | %s | %s |"
          % (e["ep"], e["act"], e["core_conflict"], e["reversal"], e["hook"],
             e["hook_type"], e["emotion"], e["beat_note"]) for e in o["episodes"]]
    L += ["", "## 差异化红线（违反即失败）", ""] + ["- %s" % r for r in o["differentiation_redlines"]]
    return "\n".join(L)


def render_script_brief(o: dict) -> str:
    L = ["# ④ 改写指令书（%d 集规划已定稿）" % o["total_ep"], "",
         "> 本文件 + `blueprint.json` 是 LLM 写剧本的**唯一指令来源**；",
         "> 按 `stages/creation/prompts/s3-script-rewrite.md` 逐集产出 FFS 正文。", "",
         "## 一、项目", "",
         "- 剧名：%s（%s）　市场：%s　平台：%s　形态：%s"
         % (o["title"], o.get("title_es") or "-", o["market"], o["platform"], o["form"]),
         "- 集数：%d 集 × %d 秒　STYLE LOCK 须逐字复制：`%s`"
         % (o["total_ep"], o["ep_seconds"], o["style_lock"]),
         "- logline：%s" % (o["positioning_digest"].get("logline")),
         "- 核心冲突：%s" % (o["positioning_digest"].get("conflict")), "",
         "## 二、受众与差异化（来自③定位卡）", "",
         "- 受众画像：%s" % (o["positioning_digest"].get("audience_profile") or {}),
         "- 题材方向：%s" % (o["positioning_digest"].get("genre_direction")),
         "- 差异化卖点：%s" % "；".join(o["positioning_digest"].get("differentiation_selling_points") or []) or "-",
         "- ② 高频套路（可顺势）：%s" % ("、".join(o["hot_tropes"]) or "-"), "",
         "## 三、改写方式（源剧本 → 新规划）", "",
         "1. **保留**源剧本的核心人设、设定魅力与最「颠」的爽点机制。",
         "2. **重排**为 %d 集结构（见 blueprint.json 的 episodes），每集落实其" % o["total_ep"],
         "   「核心冲突 + 一次反转 + 集尾钩子」三件套。",
         "3. **加密**钩子与爆点：按 `boom_cadence` 植入中型/大型爆点。", "",
         "## 四、差异化红线（违反即失败）", ""] + ["- %s" % r for r in o["differentiation_redlines"]] + [
         "", "## 五、交付与自检", "",
         "1. 逐集输出 FFS 正文到 `<工作区>/script/ep_XX.md`（HEADER 六字段 + 镜头块 8 字段 + 可选 DUR）。",
         "2. 台词为口语西语；同时给中文译稿（bilingual）。",
         "3. 自检：`python script_rewrite.py lint --ep N` → 全 [OK] 后跑 `tools/cli.py check --ep N`。",
         ""]
    return "\n".join(L)


# ---------------------------------------------------------------------------
# FFS 骨架
# ---------------------------------------------------------------------------
def build(ws: pathlib.Path, ep: int, shots: int = 8, emit: bool = False, dry: bool = False) -> int:
    bp = C.read_json(C.pdir(ws, C.BLUEPRINT))
    if not isinstance(bp, dict) or not bp.get("episodes"):
        print("[FAIL] 找不到④集数规划：%s（先跑 script_rewrite.py plan）" % C.pdir(ws, C.BLUEPRINT))
        return 2
    row = next((e for e in bp["episodes"] if e.get("ep") == ep), None)
    if not row:
        print("[FAIL] 规划里没有 EP%d（共 %d 集）" % (ep, bp.get("total_ep", 0)))
        return 2
    b = {
        "title": bp.get("title"), "total_ep": bp.get("total_ep"), "platform": bp.get("platform"),
        "style_lock": bp.get("style_lock"), "_ep_row": row,
        "ep_seconds": bp.get("ep_seconds") or DEFAULT_EP_SECONDS,
    }
    skeleton = render_skeleton(ws, b, ep, shots)
    print(C.hr())
    print("④ 剧本改写 · FFS 骨架（EP%02d）" % ep)
    print(C.hr())
    print("  本集核心冲突：%s" % row["core_conflict"])
    print("  本集反转    ：%s" % row["reversal"])
    print("  本集钩子    ：[%s] %s" % (row["hook_type"], row["hook"]))
    if dry:
        print("[dry] 未落盘。\n")
        print(skeleton)
        return 0
    dst = C.pdir(ws, "creation/03-script/skeleton_ep_%02d.md" % ep)
    C.write_text(dst, skeleton)
    print("  [OK] 骨架：%s" % dst)
    if emit:
        # ★ 四段法门禁：结构未确认不许写正文（旧项目无诊断卡时仅告警，保持兼容）
        dg = C.read_json(C.pdir(ws, C.DIAGNOSIS))
        if isinstance(dg, dict) and not dg.get("structure_confirmed"):
            print("[FAIL] 诊断卡尚未确认（structure_confirmed=false）：%s" % C.pdir(ws, C.DIAGNOSIS))
            print("       先补齐 A/B/C → script_rewrite.py diagnose --check → diagnose --confirm")
            return 4
        if not isinstance(dg, dict):
            print("  [WARN] 未找到诊断卡（旧项目兼容）。建议先跑 diagnose 做选题诊断，"
                  "否则正文容易写成句库套话。")
        target = C.pdir(ws, "script/ep_%02d.md" % ep)
        C.write_text(target, skeleton)
        print("  [OK] 已就位：%s（用 prompts/s3 填正文字段）" % target)
    print("  下一步：script_rewrite.py lint --ep %d" % ep)
    return 0


def render_skeleton(ws: pathlib.Path, b: dict, ep: int, shots: int) -> str:
    row = b.get("_ep_row") or {}
    # 角色/场景骨架：优先读 bible（若有），否则用占位
    bible = C.pdir(ws, "bible")
    char_line, scene_line = "<CHAR 代号>: <锚点>", "<SCENE 代号>: <描述>"
    chars_md = C.read_text(bible / "characters.md")
    scenes_md = C.read_text(bible / "scenes.md")
    if chars_md:
        codes = re.findall(r"\|\s*`([A-Z_]{2,})`", chars_md)
        if codes:
            char_line = "; ".join("%s: <锚点>" % c for c in codes[:6])
    if scenes_md:
        codes = re.findall(r"\|\s*`([A-Z_]{2,})`", scenes_md)
        if codes:
            scene_line = "; ".join("%s: <描述>" % c for c in codes[:6])

    L = ["# TITLE: %s" % b.get("title"),
         "# EP: %02d/%d" % (ep, b.get("total_ep", 0)),
         "# PLATFORM: %s" % b.get("platform"),
         "# STYLE LOCK: %s" % b.get("style_lock"),
         "# CHAR: %s" % char_line,
         "# SCENE: %s" % scene_line,
         ""]
    # ★ 骨架的 DUR 要落在本剧秒数档内（60 秒 8 镜若按 5/8 填只有 58 秒，会被 lint 判越界）
    _target = int(b.get("ep_seconds") or DEFAULT_EP_SECONDS)
    base = max(DUR_MIN, min(DUR_MAX, int(round(_target / max(shots, 1)))))
    edge = max(DUR_MIN, base - 1)
    for i in range(1, shots + 1):
        L += ["---",
              "[SC-%02d]" % i,
              "SHOT: <景别, 运镜>",
              "LOCATION: <SCENE 代号>",
              "TIME: <日/夜/黄昏/黎明/雨夜>",
              "CHAR: <CHAR 代号 或 无>",
              "ACTION: <1-2句具体动作+表情；必须出现角色代号或名字；禁止抽象词>",
              "DIALOG: <\"西语台词\" 或 无；单句≤20字>",
              "VO: <NARRATOR: 旁白 或 无>",
              "SFX: <音效 或 无>",
              "DUR: %d" % (edge if i in (1, shots) else base),
              ""]
    L += ["<!-- 本集核心冲突：%s -->" % row.get("core_conflict", ""),
          "<!-- 本集反转：%s -->" % row.get("reversal", ""),
          "<!-- 本集钩子（写进最后一个镜头）：[%s] %s -->" % (row.get("hook_type", ""), row.get("hook", "")),
          "<!-- 填写口径见 creation/03-script/script-brief.md 与 prompts/s3-script-rewrite.md -->"]
    return "\n".join(L)


# ---------------------------------------------------------------------------
# FFS 结构自检
# ---------------------------------------------------------------------------
def lint(ws: pathlib.Path, ep: int) -> int:
    p = C.pdir(ws, "script/ep_%02d.md" % ep)
    if not p.is_file():
        print("[FAIL] 找不到剧本：%s" % p)
        return 2
    text = p.read_text(encoding="utf-8", errors="replace")
    errors: list[str] = []
    warns: list[str] = []

    for f in FFS_HEADER_ORDER:
        if not re.search(r"(?m)^#\s*%s\s*:" % re.escape(f), text):
            errors.append("缺 HEADER 字段 `# %s:`" % f)
    sl = re.search(r"(?m)^#\s*STYLE LOCK\s*:\s*(.+)$", text)
    if sl and not sl.group(1).strip():
        errors.append("STYLE LOCK 为空")

    blocks = re.split(r"(?m)^---\s*$", text)
    shot_blocks = [b for b in blocks if re.search(r"\[SC-\d+\]", b)]
    if not shot_blocks:
        errors.append("没有任何镜头块（应形如 `---` + `[SC-01]`）")
    for b in shot_blocks:
        m = re.search(r"\[SC-\d+\]", b)
        sid = m.group(0) if m else "?"
        for f in FFS_SHOT_FIELDS:
            if not re.search(r"(?m)^\s*%s\s*:" % f, b):
                errors.append("%s 缺字段 `%s`" % (sid, f))
        for bad in FFS_FORBIDDEN:
            if re.search(r"(?m)^\s*%s\s*:" % bad, b):
                errors.append("%s 出现禁止字段 `%s`（E004）" % (sid, bad))
        dur = re.search(r"(?m)^\s*DUR\s*:\s*(\d+)", b)
        if dur:
            d = int(dur.group(1))
            if not (DUR_MIN <= d <= DUR_MAX):
                errors.append("%s DUR=%d 越界（%d-%d）" % (sid, d, DUR_MIN, DUR_MAX))
        dl = re.search(r"(?m)^\s*DIALOG\s*:\s*(.+)$", b)
        if dl and dl.group(1).strip() not in ("无", ""):
            for sent in re.findall(r"[“\"']([^”\"']+)[”\"']", dl.group(1)):
                if len(sent.strip()) > 40:
                    warns.append("%s 台词偏长（%d 字）：%s" % (sid, len(sent.strip()), sent[:24]))

    # ★ 按本剧 blueprint 的 ep_seconds 选口径：老项目 70 秒、新项目 60 秒各按各的，
    #   不要用全局常量硬套（否则口径下调会把在跑的老项目判死）。
    bp = C.read_json(C.pdir(ws, C.BLUEPRINT)) or {}
    _bsec = bp.get("ep_seconds") if isinstance(bp, dict) else None
    s_min, s_max, t_min, t_max = bounds_for(_bsec)

    n = len(shot_blocks)
    if not (s_min <= n <= s_max):
        errors.append("镜头数 %d 越界（%s 秒口径 %d-%d 镜）" % (n, _bsec or DEFAULT_EP_SECONDS, s_min, s_max))

    durs = [int(m.group(1)) for m in re.finditer(r"(?m)^\s*DUR\s*:\s*(\d+)", text)]
    total = sum(durs) if durs else n * 8
    if not (t_min <= total <= t_max):
        warns.append("总时长约 %d 秒，超出口径 %d-%d 秒（%s 秒档；缺 DUR 时按 8 秒/镜估算）"
                     % (total, t_min, t_max, _bsec or DEFAULT_EP_SECONDS))

    # ★ 留存率结构校验（2026-10-16）：对集数规划里本集「四件套」做硬校验
    row = next((e for e in (bp.get("episodes") or []) if e.get("ep") == ep), None)
    if isinstance(row, dict):
        for key, cn in (("cold_open", "开场钩子"), ("core_conflict", "核心冲突"),
                        ("reversal", "一次反转"), ("hook", "集尾钩子")):
            if not str(row.get(key) or "").strip():
                errors.append("留存结构缺 `%s`（%s）—— 见 blueprint.json 的 retention_plan" % (key, cn))
        # 钩子类型不得与前 2 集连续重复（防观众疲劳）
        eps = bp.get("episodes") or []
        cur = row.get("hook_type")
        prev2 = [e.get("hook_type") for e in eps if ep - 2 <= e.get("ep", 0) <= ep - 1]
        if cur and len(prev2) == 2 and prev2[0] == prev2[1] == cur:
            warns.append("EP%d 钩子类型「%s」与前两集连续重复（建议换型）" % (ep, cur))
    else:
        warns.append("blueprint.json 里没有 EP%d 的规划行，无法校验留存结构" % ep)

    # ★ 四段法：本篇是否已做过观众视角审稿（不阻塞格式自检，只提醒别漏最后一轮）
    if not C.pdir(ws, C.AUDIENCE_REVIEW).is_file():
        warns.append("还没做观众视角审稿（script_rewrite.py audience --template）；"
                     "格式自检过了不等于好看")

    # ★ 2026-10-20：CHAR 代号必须在 HEADER 登记 —— 下游按代号映射资产与参考图，
    #   未登记的代号（如 AGENTE / JEFA 这类通用职业词）在分镜阶段无法映射，会静默漏图。
    hd = re.search(r"(?m)^#\s*CHAR\s*:\s*(.+)$", text)
    if hd and shot_blocks:
        reg = {p.split(":")[0].strip().upper() for p in hd.group(1).split(";") if ":" in p}
        used = set()
        for b in shot_blocks:
            m = re.search(r"(?m)^\s*CHAR\s*:\s*(.+)$", b)
            if not m:
                continue
            for c in re.split(r"[,，/、]", m.group(1)):
                c = c.strip().upper()
                if c and c not in ("无", "-", "") and not c.startswith("<"):
                    used.add(c)
        unreg = sorted(used - reg)
        if unreg:
            warns.append("CHAR 用了未在 HEADER 登记的代号：%s（分镜无法映射资产，"
                         "见 script_continuity.py 同一项检查）" % "、".join(unreg))

    print(C.hr())
    print("④ FFS 结构自检 · EP%02d（%s）" % (ep, p))
    print(C.hr())
    print("  镜头块：%d ｜ 估算总时长：%d 秒" % (n, total))
    for e in errors:
        print("  [FAIL] %s" % e)
    for w in warns:
        print("  [WARN] %s" % w)
    print("-" * 74)
    if errors:
        print("[NG] 结构自检未通过（%d 项错误）。修好再跑 tools/cli.py check。" % len(errors))
        return 1
    print("[OK] 结构自检通过。下一步：python tools/cli.py check --ep %d" % ep)
    return 0


# ===========================================================================
# ★ 2026-10-20（S3 四段法）：诊断 → 骨架 → 正文 → 观众审稿
# ---------------------------------------------------------------------------
# 背景：`plan` 能产出格式齐全的 40 集四件套，但 cold_open / core_conflict /
# reversal / hook 默认来自句库拼装 —— **结构齐、内容空**。用户实测的「不够抓人」
# 多数不是格式问题，而是两件事没做：
#   ① 动笔前没判断「这个选题靠什么留住观众」（诊断缺失）；
#   ② 写完没人以观众视角验一遍（只验了格式）。
#
# 因此把 ④ 拆成四段，每段都有产物、都能被机器卡住：
#   ① diagnose  A 选题诊断 / B 改编策略 / C 故事主线  → diagnosis.json（+ --confirm）
#   ② plan      D 分集大纲                            → blueprint.json（已有）
#   ③ build     正文骨架 + LLM 填正文                 → script/ep_XX.md（已有，加前置门禁）
#   ④ review    第二轮 结构审查 → structure-review.md
#      audience  第四轮 观众审稿 → audience-review.md
# 方法论真源：docs/creation/剧本改编四段法.md
# ===========================================================================
PROFILE_FILE = pathlib.Path(__file__).resolve().parents[1] / "references" / "genre-profiles.json"

# 题材未命中时使用的通用信号词（不冒充任何题材的专属口径）
_GENERIC_AGENCY = ("反击", "设局", "亮出", "夺回", "决定", "选择", "拒绝", "摊牌", "查", "护")
_GENERIC_STAKES = ("身份", "权力", "证据", "真相", "筹码", "关系", "利益", "资源", "立场",
                   "名分", "股权", "控股权", "表决", "控制权", "资格", "署名", "专利", "继承权")
PASSIVE_MARKS = ("被", "遭", "受制", "只能", "任人", "无端", "被迫", "由他人")


def load_profiles() -> list:
    obj = C.read_json(PROFILE_FILE) or {}
    return obj.get("profiles") or []


def profile_by_id(pid) -> dict | None:
    if not pid:
        return None
    return next((p for p in load_profiles() if p.get("id") == pid), None)


def match_profile(text: str, fallback: str | None = None) -> dict | None:
    """按关键词**最长匹配**题材侧重表；未命中返回 fallback（可为 None）。"""
    t = str(text or "")
    best, best_len = None, 0
    for p in load_profiles():
        for kw in p.get("keywords") or []:
            if kw and kw in t and len(kw) > best_len:
                best, best_len = p, len(kw)
    return best or profile_by_id(fallback)


# ---------------------------------------------------------------------------
# 文本相似度（中文按 2-gram，避免引入分词依赖）
# ---------------------------------------------------------------------------
_NORM_RE = re.compile(r"[^\u4e00-\u9fa5A-Za-z0-9]+")
# 纯功能词 2-gram：共享到它们不能证明「钩子由本集推出」
_STOP_GRAMS = {"她的", "他的", "我的", "你的", "一个", "什么", "就是", "不是", "已经",
               "自己", "这个", "那个", "我们", "他们", "她们", "因为", "所以", "但是",
               "然后", "现在", "可以", "没有", "还不", "还是", "只是", "就是", "的时"}


def _norm(s) -> str:
    return _NORM_RE.sub("", str(s or ""))


def _grams(s, n: int = 2) -> set:
    t = _norm(s)
    return {t[i:i + n] for i in range(max(0, len(t) - n + 1))}


def _jac(a, b) -> float:
    A, B = _grams(a), _grams(b)
    return len(A & B) / max(1, len(A | B))


def _shared(a, b) -> int:
    """共享**实义** 2-gram 数（剔除「她的/什么/已经」这类功能词）。"""
    return len((_grams(a) & _grams(b)) - _STOP_GRAMS)


def _hits(text, words) -> list:
    t = str(text or "")
    return [w for w in (words or ()) if w in t]


def _has(v, minlen: int = 4) -> bool:
    return isinstance(v, str) and len(v.strip()) >= minlen


# ---------------------------------------------------------------------------
# ① 诊断卡（A 选题诊断 / B 改编策略 / C 故事主线）
# ---------------------------------------------------------------------------
DIAG_TEMPLATE = {
    "_note": "填完跑 `script_rewrite.py diagnose --check`；全绿后 `diagnose --confirm`，"
             "才允许 `build --emit` 写正文。判断型字段不预填 —— 空着就是在提醒你还没想清楚。",
    "A_diagnosis": {
        "core_hook": "",
        "audience_emotion": "",
        "protagonist": {"desire": "", "obstacle": "", "cost_if_lose": "", "counter_space": ""},
        "power_gaps": [],
        "audience_expectation": "",
        "hook_slots": {"opening": "", "mid_climax": "", "ep_tail": ""},
        "risks": [],
        "unique_selling_point": "",
    },
    "B_strategy": {"keep": [], "changes": []},
    "C_mainline": {"start": "", "key_events": [], "goal": "", "cost_or_change": "",
                   "one_paragraph": ""},
    "structure_confirmed": False,
    "confirmed_at": None,
}

DIAG_HINTS = {
    "core_hook": "这个设定里最吸引人的那一点是什么？（一句话，≥10 字；不是剧情简介）",
    "audience_emotion": "目标观众最容易在哪一刻产生共鸣/愤怒/爽感？",
    "protagonist.desire": "主角想要什么（具体、可被夺走的）",
    "protagonist.obstacle": "谁在阻碍，用什么手段",
    "protagonist.cost_if_lose": "输了会失去什么（写具体物件/数字/关系）",
    "protagonist.counter_space": "主角的反击空间在哪（凭什么能翻盘）",
    "power_gaps": "身份差/信息差/权力差/情感差，至少写 1 条",
    "audience_expectation": "观众最期待看到的结果（他们会为了看这个追下去）",
    "hook_slots": "开场钩子 / 阶段性高潮 / 集尾悬念，各给一个具体设计",
    "risks": "这个选题可能让观众弃剧的硬伤（至少 1 条；写「无」视为未诊断）",
    "unique_selling_point": "不得为迎合公式牺牲的独特卖点",
    "B.keep": "必须保留的（核心设定/人物关系/爽点机制），每条带理由",
    "B.changes": "调整/删减/合并/新增，type 取 adjust|cut|merge|add，每条带戏剧目的",
    "C.key_events": "起点 → 关键事件（≥3）→ 目标 → 代价/改变",
    "C.one_paragraph": "一段话说清主线（≥80 字），不写对白",
}


def _merge_defaults(obj, tpl):
    """用模板补**缺失键**，绝不覆盖已有值（保护已填写内容）。"""
    if not isinstance(obj, dict):
        obj = {}
    for k, v in tpl.items():
        if k not in obj or obj[k] in (None, "", [], {}):
            if isinstance(v, dict):
                obj[k] = _merge_defaults(obj.get(k), v)
            else:
                obj[k] = json.loads(json.dumps(v, ensure_ascii=False))
        elif isinstance(v, dict):
            obj[k] = _merge_defaults(obj[k], v)
    return obj


def _diag_context(ws) -> tuple:
    """取预填上下文：定位卡（或公式 topic_card）+ brief + 源剧本体检。"""
    pos = C.read_json(C.pdir(ws, C.POSITIONING)) or {}
    card = next((x for x in (pos.get("selected") or []) if x.get("rank") == 1), None)
    if not card:
        gp = G.load_plan(ws)
        if gp and gp.get("_formula"):
            card = G.build_topic_card(gp["_formula"])
    if not isinstance(card, dict):
        card = {}
    return card, C.read_json(C.pdir(ws, C.BRIEF)) or {}, inspect_source(ws)


def diag_init(ws, force: bool = False) -> int:
    card, brief, src = _diag_context(ws)
    p = C.pdir(ws, C.DIAGNOSIS)
    existed = p.is_file()
    if existed and not force:
        obj = _merge_defaults(C.read_json(p) or {}, DIAG_TEMPLATE)
        print("[i] 诊断卡已存在，只补缺失字段（不覆盖已填内容）：%s" % p)
        print("    要整份重来请加 --force。")
    else:
        obj = json.loads(json.dumps(DIAG_TEMPLATE, ensure_ascii=False))

    text = " ".join(str(card.get(k) or "") for k in
                    ("title", "logline", "conflict", "genre_direction"))
    prof = match_profile(text)
    obj["title"] = card.get("title") or brief.get("title") or obj.get("title")
    obj["genre_profile"] = (prof or {}).get("id")
    obj["profile_label"] = (prof or {}).get("label")
    obj["_context"] = {
        "logline": card.get("logline"),
        "conflict": card.get("conflict"),
        "genre_direction": card.get("genre_direction"),
        "audience_profile": card.get("audience_profile"),
        "differentiation_selling_points": card.get("differentiation_selling_points"),
        "platform": (card.get("audience_profile") or {}).get("platform") or brief.get("platform"),
        "ep_total": brief.get("ep_total") or DEFAULT_EPISODES,
        "ep_seconds": brief.get("ep_seconds") or DEFAULT_EP_SECONDS,
        "source_script": ("已登记 %d 字" % src.get("chars", 0)) if src.get("present") else "未提供",
        "structure_focus": (prof or {}).get("structure_focus"),
        "audience_promise": (prof or {}).get("audience_promise"),
        "hints": DIAG_HINTS,
    }
    C.write_json(p, obj)
    md = C.write_text(C.pdir(ws, C.DIAGNOSIS_MD), render_diagnosis_md(obj))
    print(C.hr())
    print("④-A 选题诊断卡（%s）" % ("已存在·补缺" if existed and not force else "新建"))
    print(C.hr())
    print("  剧名      : %s" % (obj.get("title") or "-"))
    print("  题材侧重  : %s" % ("%s（%s）" % (obj.get("profile_label"), obj.get("genre_profile"))
                                if prof else "未命中 —— 可写 A/B/C 后手工指定 genre_profile"))
    if prof:
        print("  结构侧重  : %s" % " → ".join(prof.get("structure_focus") or []))
        print("  观众承诺  : %s" % prof.get("audience_promise"))
    print("  源剧本    : %s" % obj["_context"]["source_script"])
    print("-" * 74)
    print("  判断型字段**一律留空**：先想清楚再填，别让模板替你思考。")
    print("  下一步：按 docs/creation/剧本改编四段法.md 填 A/B/C → diagnose --check")
    print("\n[OK] 已写出：\n     %s\n     %s" % (p, md))
    return 0


def validate_diagnosis(obj: dict, prof: dict | None = None) -> tuple:
    """A/B/C 三段完整性校验 → (errors, warns)。宁严不宽：空着就是没诊断。"""
    errors, warns = [], []
    A = obj.get("A_diagnosis") or {}
    B = obj.get("B_strategy") or {}
    Cc = obj.get("C_mainline") or {}

    # --- A 选题诊断 -------------------------------------------------------
    if not _has(A.get("core_hook"), 10):
        errors.append("A.core_hook：核心卖点未写或过短（<10 字）")
    if not _has(A.get("audience_emotion"), 6):
        errors.append("A.audience_emotion：情绪共鸣点未写")
    pg = A.get("protagonist") or {}
    for k, cn in (("desire", "想要什么"), ("obstacle", "谁在阻碍"),
                  ("cost_if_lose", "输了失去什么"), ("counter_space", "反击空间")):
        if not _has(pg.get(k), 4):
            errors.append("A.protagonist.%s（%s）未写" % (k, cn))
    if len([x for x in (A.get("power_gaps") or []) if str(x).strip()]) < 1:
        errors.append("A.power_gaps：身份差/信息差/权力差/情感差至少要有一条")
    if not _has(A.get("audience_expectation"), 6):
        errors.append("A.audience_expectation：观众最期待看到的结果未写")
    hs = A.get("hook_slots") or {}
    for k, cn in (("opening", "开场钩子"), ("mid_climax", "阶段性高潮"), ("ep_tail", "集尾悬念")):
        if not _has(hs.get(k), 4):
            errors.append("A.hook_slots.%s（%s）未给具体设计" % (k, cn))
    risks = [str(x).strip() for x in (A.get("risks") or []) if str(x).strip()]
    if not risks:
        errors.append("A.risks：必须写出至少 1 条可能导致弃剧的硬伤")
    elif all(r in ("无", "没有", "暂无", "无风险", "待定") for r in risks):
        warns.append("A.risks：只写了「无」—— 无风险自评通常意味着还没诊断（不阻塞，但请复核）")
    if not _has(A.get("unique_selling_point"), 6):
        errors.append("A.unique_selling_point：不得牺牲的独特卖点未写")

    # --- B 改编策略 -------------------------------------------------------
    keep = [k for k in (B.get("keep") or []) if isinstance(k, dict)]
    if not keep:
        errors.append("B.keep：必须写明保留项（核心设定/人物关系/爽点机制）")
    for i, k in enumerate(keep, 1):
        if not _has(k.get("item"), 2):
            errors.append("B.keep[%d]：缺 item" % i)
        if not _has(k.get("why"), 6):
            errors.append("B.keep[%d]：缺理由（why）—— 无理由的保留等于没判断" % i)
    changes = [c for c in (B.get("changes") or []) if isinstance(c, dict)]
    if not changes:
        errors.append("B.changes：至少 1 条改动（adjust/cut/merge/add），含戏剧目的")
    for i, c in enumerate(changes, 1):
        t = str(c.get("type") or "")
        if t not in ("adjust", "cut", "merge", "add"):
            errors.append("B.changes[%d]：type=%r 非法（adjust|cut|merge|add）" % (i, t))
        if not _has(c.get("item"), 2):
            errors.append("B.changes[%d]：缺 item" % i)
        if not _has(c.get("why"), 8):
            errors.append("B.changes[%d]：缺戏剧目的（why ≥8 字）" % i)

    # --- C 故事主线 -------------------------------------------------------
    for k, cn in (("start", "起点处境"), ("goal", "主要目标"), ("cost_or_change", "代价或改变")):
        if not _has(Cc.get(k), 6):
            errors.append("C.%s（%s）未写" % (k, cn))
    ev = [x for x in (Cc.get("key_events") or []) if str(x).strip()]
    if len(ev) < 3:
        errors.append("C.key_events：关键事件至少 3 条（现 %d 条）" % len(ev))
    if not _has(Cc.get("one_paragraph"), 80):
        errors.append("C.one_paragraph：一段话主线不足 80 字（现 %d 字）"
                      % len(str(Cc.get("one_paragraph") or "").strip()))

    # --- 题材一致性 -------------------------------------------------------
    if prof and obj.get("genre_profile") and obj["genre_profile"] != prof.get("id"):
        warns.append("题材侧重同时命中 %s 与 %s，建议在 genre_profile 里明确一个"
                     % (obj["genre_profile"], prof.get("id")))
    if not obj.get("genre_profile"):
        warns.append("未指定 genre_profile —— 结构审查将用通用口径（不套题材侧重）")
    return errors, warns


def render_diagnosis_md(o: dict) -> str:
    A = o.get("A_diagnosis") or {}
    B = o.get("B_strategy") or {}
    Cc = o.get("C_mainline") or {}
    pg = A.get("protagonist") or {}
    hs = A.get("hook_slots") or {}
    st = "已确认" if o.get("structure_confirmed") else "**未确认**"

    def _v(x, dash="—"):
        return str(x).strip() if str(x or "").strip() else dash

    L = ["# ④-A 剧本改编诊断卡（%s）" % _v(o.get("title"), "未命名"), "",
         "> 结构确认：%s　题材侧重：%s　生成：%s"
         % (st, _v(o.get("profile_label")), o.get("generated_at") or C.now_iso()[:19]),
         "> 门禁：`diagnose --check` 全绿 → `diagnose --confirm` → 才允许 `build --emit`", "",
         "## A. 选题诊断", "",
         "| 项 | 判断 |", "|---|---|",
         "| 核心卖点 | %s |" % _v(A.get("core_hook")),
         "| 情绪共鸣点 | %s |" % _v(A.get("audience_emotion")),
         "| 主角想要 | %s |" % _v(pg.get("desire")),
         "| 谁在阻碍 | %s |" % _v(pg.get("obstacle")),
         "| 输了失去 | %s |" % _v(pg.get("cost_if_lose")),
         "| 反击空间 | %s |" % _v(pg.get("counter_space")),
         "| 身份/信息/权力差 | %s |" % _v("、".join(A.get("power_gaps") or [])),
         "| 观众期待 | %s |" % _v(A.get("audience_expectation")),
         "| 独特卖点（不可牺牲） | %s |" % _v(A.get("unique_selling_point")),
         "", "### 钩子落位", "",
         "| 位置 | 设计 |", "|---|---|",
         "| 开场 | %s |" % _v(hs.get("opening")),
         "| 阶段性高潮 | %s |" % _v(hs.get("mid_climax")),
         "| 集尾悬念 | %s |" % _v(hs.get("ep_tail")),
         "", "### 主要风险（可能弃剧的硬伤）", ""]
    L += ["- %s" % r for r in (A.get("risks") or [])] or ["- —"]
    L += ["", "## B. 改编策略", "", "### 保留", ""]
    L += ["- **%s** —— %s" % (_v(k.get("item")), _v(k.get("why")))
          for k in (B.get("keep") or []) if isinstance(k, dict)] or ["- —"]
    L += ["", "### 改动（调整 / 删减 / 合并 / 新增）", "",
          "| 类型 | 对象 | 戏剧目的 |", "|---|---|---|"]
    L += ["| %s | %s | %s |" % (_v(c.get("type")), _v(c.get("item")), _v(c.get("why")))
          for c in (B.get("changes") or []) if isinstance(c, dict)] or ["| — | — | — |"]
    L += ["", "## C. 故事主线", "",
          "- 起点：%s" % _v(Cc.get("start")),
          "- 目标：%s" % _v(Cc.get("goal")),
          "- 代价/改变：%s" % _v(Cc.get("cost_or_change")),
          "", "### 关键事件", ""]
    L += ["%d. %s" % (i, e) for i, e in enumerate(Cc.get("key_events") or [], 1)] or ["—"]
    L += ["", "### 一段话主线", "", _v(Cc.get("one_paragraph")), ""]
    return "\n".join(L)


def diag_check(ws, confirm: bool = False) -> int:
    p = C.pdir(ws, C.DIAGNOSIS)
    obj = C.read_json(p)
    if not isinstance(obj, dict):
        print("[FAIL] 找不到诊断卡：%s（先跑 script_rewrite.py diagnose）" % p)
        return 2
    prof = profile_by_id(obj.get("genre_profile"))
    errors, warns = validate_diagnosis(obj, prof)

    print(C.hr())
    print("④-A 诊断卡校验 · %s" % (obj.get("title") or "-"))
    print(C.hr())
    print("  题材侧重：%s" % ((prof or {}).get("label") or "未指定（通用口径）"))
    for w in warns:
        print("  [WARN] %s" % w)
    for e in errors:
        print("  [FAIL] %s" % e)
    print("-" * 74)
    if errors:
        print("[NG] 诊断不完整（%d 项）。补齐再跑 —— 这些字段空着，写出来的就是句库套话。" % len(errors))
        return 2
    if confirm:
        obj["structure_confirmed"] = True
        obj["confirmed_at"] = C.now_iso()
        C.write_json(p, obj)
        C.write_text(C.pdir(ws, C.DIAGNOSIS_MD), render_diagnosis_md(obj))
        print("[OK] A/B/C 完整，结构已确认（structure_confirmed=true）。")
        print("     下一步：script_rewrite.py plan → build --ep 1 --emit")
        return 0
    print("[OK] A/B/C 完整%s。确认骨架：script_rewrite.py diagnose --confirm"
          % ("（含 %d 项告警）" % len(warns) if warns else ""))
    return 0


# ---------------------------------------------------------------------------
# ④ 第二轮：结构审查（对 blueprint 做确定性体检）
# ---------------------------------------------------------------------------
def _review_agency(eps, prof) -> tuple:
    """主角是否主动：reversal 命中主动信号词才算；全剧零主动 = 硬伤。"""
    words = (prof or {}).get("agency_signals") or _GENERIC_AGENCY
    act, passive = [], []
    for e in eps:
        rv = str(e.get("reversal") or "")
        if _hits(rv, words):
            act.append(e.get("ep"))
        elif any(m in rv for m in PASSIVE_MARKS):
            passive.append(e.get("ep"))
    n = max(len(eps), 1)
    if not act:
        return "FAIL", "全剧 %d 集没有任何一集由主角主动改变局势（主动信号词：%s）" % (
            n, "、".join(words[:6]))
    if len(act) / n < 0.3:
        return "WARN", "仅 %d/%d 集由主角主动破局（%s）；其余多是被动承受" % (
            len(act), n, "、".join("EP%02d" % x for x in act[:6]))
    return "OK", "主动破局 %d/%d 集" % (len(act), n)


def _review_stakes(eps, prof) -> tuple:
    """反转是否改变力量/信息格局：只改情绪不算。"""
    words = (prof or {}).get("stakes_signals") or _GENERIC_STAKES
    zero = [e.get("ep") for e in eps
            if not _hits(str(e.get("reversal") or "") + str(e.get("core_conflict") or ""), words)]
    n = max(len(eps), 1)
    ratio = 1 - len(zero) / n
    # 连续 3 集都没有筹码/身份/信息变化 ⇒ 这一段没有推进（滑动窗口，不按固定集数切卷）
    dead = []
    for i in range(2, len(eps)):
        trio = eps[i - 2:i + 1]
        if all(e.get("ep") in zero for e in trio):
            dead.append("EP%02d-%02d" % (trio[0].get("ep"), trio[2].get("ep")))
    if dead:
        return "FAIL", "连续三集没有筹码/身份/信息变化：%s（反转只是情绪起伏）" % "、".join(dead[:4])
    if ratio < 0.5:
        return "WARN", "仅 %.0f%% 集的反转触到格局变化（信号词：%s）" % (
            ratio * 100, "、".join(words[:6]))
    return "OK", "%.0f%% 集的反转改变了格局" % (ratio * 100)


def _review_conflict_variety(eps, prof=None) -> tuple:
    norm = [_norm(e.get("core_conflict")) for e in eps]
    n = max(len(norm), 1)
    ratio = len(set(norm)) / n
    prefixes = {str(e.get("core_conflict") or "").split("：")[0].split(":")[0][:12] for e in eps}
    detail = "冲突去重 %.0f%%（%d/%d），前缀 %d 种" % (ratio * 100, len(set(norm)), n, len(prefixes))
    if ratio < 0.55:
        return "FAIL", detail + " —— 近半冲突在重复，属注水"
    if ratio < 0.75:
        return "WARN", detail + " —— 建议逐集改写 core_conflict"
    if n >= 10 and len(prefixes) <= 4:
        return "WARN", detail + " —— 前缀种类过少，疑似 plan 句库套用"
    return "OK", detail


def _review_conflict_repeat(eps, prof=None) -> tuple:
    """连续三集两两高相似 ⇒ 观众会觉得「上一集已经看过了」。"""
    hot, worst = [], 0.0
    for i in range(2, len(eps)):
        trio = eps[i - 2:i + 1]
        sims = [_jac(trio[0].get("core_conflict"), trio[1].get("core_conflict")),
                _jac(trio[1].get("core_conflict"), trio[2].get("core_conflict"))]
        m = min(sims)
        worst = max(worst, m)
        if m >= 0.72:
            hot.append("EP%02d-%02d" % (trio[0].get("ep"), trio[2].get("ep")))
    if hot:
        return "FAIL", "连续三集冲突高度相似（阈值 0.72）：%s" % "、".join(hot[:5])
    return "OK", "无连续三集重复（峰值相似度 %.2f）" % worst


def _review_hook_causal(eps, prof=None) -> tuple:
    """集尾钩子必须由本集内容推出，不能空降新事件。"""
    weak = []
    for e in eps:
        ctx = str(e.get("core_conflict") or "") + str(e.get("reversal") or "")
        if _shared(e.get("hook"), ctx) < 1:
            weak.append(e.get("ep"))
    n = max(len(eps), 1)
    ratio = 1 - len(weak) / n
    if ratio < 0.5:
        return "WARN", "仅 %.0f%% 的集尾钩子与本集内容共享实体（疑似生硬截断）：%s" % (
            ratio * 100, "、".join("EP%02d" % x for x in weak[:6]))
    return "OK", "%.0f%% 集尾钩子可追溯到本集内容" % (ratio * 100)


def _review_emotion(eps, prof=None) -> tuple:
    emos = [str(e.get("emotion") or "") for e in eps]
    n = len(emos)
    mechanical = [EMOTION_CYCLE[i % len(EMOTION_CYCLE)] for i in range(n)]
    if emos and emos == mechanical:
        return "WARN", "情绪节拍是句库轮转（%s），不是按题材设计的曲线" % "→".join(EMOTION_CYCLE)
    flat = [i for i in range(2, n) if emos[i] == emos[i - 1] == emos[i - 2] and emos[i]]
    if flat:
        return "WARN", "连续三集同情绪（EP%s）" % "、".join("%02d" % (i + 1) for i in flat[:5])
    seq = (prof or {}).get("emotion_sequence") or []
    if seq and emos:
        cover = len(set(emos) & set(seq)) / max(1, len(set(emos)))
        if cover < 0.3:
            return "WARN", "情绪词与题材承诺交集仅 %.0f%%（题材：%s）" % (
                cover * 100, "→".join(seq))
    return "OK", "情绪曲线非机械轮转"


def _review_boom_gap(eps, prof=None) -> tuple:
    marks = [int(e.get("ep") or 0) for e in eps if e.get("boom") in ("mid", "big")]
    if len(marks) < 2:
        return "WARN", "爆点少于 2 个，无法形成节拍"
    gaps = [b - a for a, b in zip(marks, marks[1:])]
    slow = ["EP%d→EP%d" % (a, b) for a, b in zip(marks, marks[1:]) if b - a > MID_BOOM_EVERY + 2]
    if slow:
        return "WARN", "爆点间隔过长（>%d 集）：%s" % (MID_BOOM_EVERY + 2, "、".join(slow[:4]))
    return "OK", "爆点间隔最大 %d 集" % max(gaps)


def _review_template_residue(eps, prof=None) -> tuple:
    """句库残留：plan 未人工覆盖时的典型指纹。"""
    bank = [p for v in CONFLICT_BANK.values() for p in v]
    bank += [p for v in COLD_OPEN_BANK.values() for p in v]
    hit_c, hit_o = [], []
    for e in eps:
        cc = str(e.get("core_conflict") or "")
        if any(cc.startswith(p + "：") or cc.startswith(p + ":") for p in bank) or "主线对抗" in cc:
            hit_c.append(e.get("ep"))
        co = str(e.get("cold_open") or "")
        if any(p in co for p in bank):
            hit_o.append(e.get("ep"))
    if hit_c:
        return "WARN", ("%d/%d 集的 core_conflict 仍是句库原文（EP%s）—— 跑 plan --from-outline "
                        "用人工拆解表覆盖" % (len(hit_c), len(eps),
                                          ",".join("%02d" % x for x in hit_c[:8])))
    if hit_o:
        return "WARN", "%d 集的 cold_open 仍是句库原文" % len(hit_o)
    return "OK", "无句库残留"


def _review_relation_progress(eps, prof) -> tuple:
    """甜宠专用：关系刻度必须逐集变化（靠近/后退/摊牌）。"""
    words = (prof or {}).get("stakes_signals") or ()
    n = max(len(eps), 1)
    ok = [e.get("ep") for e in eps
          if _hits(str(e.get("core_conflict") or "") + str(e.get("reversal") or ""), words)]
    if not ok:
        return "FAIL", "没有任何一集把冲突落到关系刻度上（题材：%s）" % (prof or {}).get("label")
    if len(ok) / n < 0.5:
        return "WARN", "仅 %d/%d 集有明确的关系推进/后退" % (len(ok), n)
    return "OK", "%d/%d 集推进了关系" % (len(ok), n)


def _review_info_gap(eps, prof) -> tuple:
    """悬疑专用：每 3 集内必须有一处信息差变化。"""
    words = (prof or {}).get("stakes_signals") or ()
    marks = [int(e.get("ep") or 0) for e in eps
             if _hits(str(e.get("core_conflict") or "") + str(e.get("reversal") or ""), words)]
    n = len(eps)
    gaps = []
    for lo in range(1, n + 1, 3):
        if not any(lo <= m <= lo + 2 for m in marks):
            gaps.append("EP%d-%d" % (lo, min(lo + 2, n)))
    if len(gaps) > n // 3 // 2:
        return "FAIL", "信息差长期无变化：%s" % "、".join(gaps[:5])
    if gaps:
        return "WARN", "以下区段没有信息差推进：%s" % "、".join(gaps[:5])
    return "OK", "每 3 集内均有信息差变化"


REVIEW_CHECKS = [
    ("protagonist_agency", "主角是否主动（不是只挨打）", _review_agency),
    ("reversal_changes_stakes", "反转是否改变力量/信息格局", _review_stakes),
    ("conflict_variety", "冲突是否在推进（而非换场景重复）", _review_conflict_variety),
    ("conflict_repeat", "是否存在连续三集同一冲突", _review_conflict_repeat),
    ("hook_causal", "集尾钩子是否由本集推出", _review_hook_causal),
    ("emotion_designed", "情绪曲线是否被设计过", _review_emotion),
    ("boom_cadence", "爆点间隔是否过长", _review_boom_gap),
    ("template_residue", "是否仍在用句库默认值", _review_template_residue),
]
PROFILE_ONLY_CHECKS = [
    ("relation_progress", "关系刻度是否逐集变化", _review_relation_progress, "sweet"),
    ("info_gap", "信息差是否持续推进", _review_info_gap, "suspense"),
]


def review(ws, profile_id: str | None = None, write_fixes: bool = False) -> int:
    bp = C.read_json(C.pdir(ws, C.BLUEPRINT))
    if not isinstance(bp, dict) or not bp.get("episodes"):
        print("[FAIL] 找不到集数规划：%s（先跑 script_rewrite.py plan）" % C.pdir(ws, C.BLUEPRINT))
        return 2
    eps = bp["episodes"]
    n = len(eps)
    prof = profile_by_id(profile_id) or profile_by_id((bp.get("structure_profile") or {}).get("id")) \
        or match_profile(" ".join(str(bp.get(k) or "") for k in ("title", "title_es"))
                         + " " + str((bp.get("positioning_digest") or {}).get("genre_direction") or ""))
    must = set((prof or {}).get("must_check") or [])

    rows = []
    for key, title, fn in REVIEW_CHECKS:
        level, detail = fn(eps, prof)
        rows.append([key, title, level, detail])
    for key, title, fn, need in PROFILE_ONLY_CHECKS:
        if (prof or {}).get("id") == need:
            level, detail = fn(eps, prof)
            rows.append([key, title, level, detail])

    # 必检项：WARN 升级为 FAIL（题材承诺的底线，不能只告警）
    for r in rows:
        if r[0] in must and r[2] == "WARN":
            r[2] = "FAIL"
            r[3] += "｜题材「%s」把它列为必检项" % (prof or {}).get("label")

    # 句库残留会污染所有「基于文本信号」的判断：此时 OK 一律降级为待人工复核，
    # 否则会出现「12 集句库套话 + 报告全绿」的假安全感。
    residue = next((r for r in rows if r[0] == "template_residue"), None)
    if residue and residue[2] == "WARN":
        for r in rows:
            if r[0] in ("reversal_changes_stakes", "conflict_variety",
                        "conflict_repeat", "hook_causal") and r[2] == "OK":
                r[2] = "WARN"
                r[3] += "｜但规划仍是句库原文，此项需人工复核"

    # 前 3 集专项
    h3 = [e.get("hook_type") for e in eps[:3]]
    rows.append(["hook_first3", "EP1-3 钩子类型互不相同", "OK" if len(set(h3)) == 3 else "FAIL",
                 str(h3)])
    ep1 = str(eps[0].get("cold_open") or "")
    setup_words = ("回忆", "小时候", "出身", "背景介绍", "旁白讲述", "从此", "这一天")
    if eps[0].get("from_outline"):
        golden, why = True, "已人工设计（outline）：%s" % ep1[:44]
    elif "黄金 3 秒" in ep1 or "golden" in ep1.lower():
        golden, why = True, ep1[:48]
    elif len(_norm(ep1)) >= 8 and not _hits(ep1, setup_words):
        golden, why = True, "开场为具体冲突，无铺垫词：%s" % ep1[:40]
    else:
        golden, why = False, ep1[:48] or "（空）"
    rows.append(["ep1_golden", "EP1 黄金 3 秒（最高冲突前置）", "OK" if golden else "WARN", why])

    fails = [r for r in rows if r[2] == "FAIL"]
    warns = [r for r in rows if r[2] == "WARN"]
    oks = [r for r in rows if r[2] == "OK"]

    print(C.hr())
    print("④ 第二轮 · 结构审查（%d 集｜题材侧重：%s）" % (n, (prof or {}).get("label") or "通用"))
    print(C.hr())
    for r in oks:
        print("  [OK  ] %-24s %s" % (r[1], r[3]))
    for r in warns:
        print("  [WARN] %-24s %s" % (r[1], r[3]))
    for r in fails:
        print("  [FAIL] %-24s %s" % (r[1], r[3]))
    print("-" * 74)

    md = C.pdir(ws, C.STRUCTURE_REVIEW)
    C.write_text(md, render_review_md(bp, rows, prof, n))
    print("  审查报告：%s" % md)
    if write_fixes and (fails or warns):
        fx = C.pdir(ws, C.BLUEPRINT_FIXES)
        C.write_text(fx, render_fixes_md(bp, fails + warns, prof))
        print("  待改清单：%s（按集号逐条填，改完重跑 review）" % fx)

    if fails:
        print("[NG] 结构审查未过（%d 项 FAIL / %d 项 WARN）。结构不改，正文写得再顺也留不住人。"
              % (len(fails), len(warns)))
        return 2
    print("[OK] 结构审查通过%s。下一步：逐集 build --ep N --emit 写正文。"
          % ("（含 %d 项告警）" % len(warns) if warns else ""))
    return 0


def render_review_md(bp: dict, rows: list, prof: dict | None, n: int) -> str:
    L = ["# ④ 第二轮 · 结构审查报告", "",
         "- 剧名：%s　集数：%d" % (bp.get("title") or "-", n),
         "- 题材侧重：%s　生成：%s" % ((prof or {}).get("label") or "通用", C.now_iso()[:19]),
         "- 结构侧重：%s" % (" → ".join((prof or {}).get("structure_focus") or []) or "—"),
         "", "| 结果 | 检查项 | 判断 |", "|---|---|---|"]
    order = {"FAIL": 0, "WARN": 1, "OK": 2}
    for r in sorted(rows, key=lambda x: order.get(x[2], 3)):
        L.append("| %s | %s | %s |" % (r[2], r[1], r[3]))
    fails = [r for r in rows if r[2] == "FAIL"]
    L += ["", "## 结论", ""]
    L += ["**未过**：先修 %d 项 FAIL，再谈写正文。" % len(fails)] if fails else \
         ["**通过**：可进入逐集正文。"]
    if prof and prof.get("avoid"):
        L += ["", "## 题材红线（违反即废集）", ""] + ["- %s" % x for x in prof["avoid"]]
    return "\n".join(L)


def render_fixes_md(bp: dict, rows: list, prof: dict | None) -> str:
    hints = (prof or {}).get("fix_hints") or {}
    L = ["# ④ 待改清单（结构审查未过项）", "",
         "> 逐条处理后重跑 `script_rewrite.py review`；改动落在 `plan --from-outline` 的人工拆解表里。", ""]
    for key, title, level, detail in rows:
        L += ["## [%s] %s（`%s`）" % (level, title, key), "", "- 现象：%s" % detail]
        if hints.get(key):
            L += ["- 改法：%s" % hints[key]]
        L += ["- 涉及集：", "", "| EP | 现写法 | 改成 | 为什么 |", "|---|---|---|---|"]
        eps = bp.get("episodes") or []
        picked = eps if level == "FAIL" else eps[:6]
        for e in picked[:12]:
            L += ["| EP%02d | %s |  |  |" % (int(e.get("ep") or 0),
                                             str(e.get("core_conflict") or "")[:28])]
        L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# ④ 第四轮：观众视角审稿
# ---------------------------------------------------------------------------
AUDIENCE_QUESTIONS = [
    ("Q1", "观众最可能在哪一段失去兴趣？为什么？", True),
    ("Q2", "哪个情节最值得期待？是否出现得太晚？", True),
    ("Q3", "哪个冲突看起来像作者刻意安排，而不是人物自然选择？", True),
    ("Q4", "哪个反转缺乏铺垫，或删掉也不影响故事？", True),
    ("Q5", "哪个爽点/虐点/情感回报不够充分？", True),
    ("Q6", "观众看完每集后，有什么具体理由继续追？", False),
    ("Q7", "当前最需要优先修改的三个问题是什么？", True),
]


def render_audience_template(bp: dict) -> str:
    L = ["# ④ 第四轮 · 观众视角审稿（%s）" % (bp.get("title") or "-"), "",
         "> 不要以编剧身份评价。**以目标观众和短剧项目负责人身份**审稿。",
         "> 每条必须**引用具体集号（EPxx）和具体情节**；只写「节奏不够快」这类形容词视为未回答。",
         "> Q7 请直接写成 3 条编号清单，每条含「问题」与「改法」。",
         "> 写完跑 `script_rewrite.py audience --check`。", ""]
    for q, text, need_ep in AUDIENCE_QUESTIONS:
        L += ["## %s %s" % (q, text), "",
              "（≥40 字%s）" % ("，须出现 EPxx" if need_ep else ""), ""]
        if q == "Q7":
            L += ["1. EP?? —— 问题：… 改法：…", "2. EP?? —— 问题：… 改法：…",
                  "3. EP?? —— 问题：… 改法：…", ""]
    return "\n".join(L)


def audience(ws, check_only: bool = False, force: bool = False) -> int:
    bp = C.read_json(C.pdir(ws, C.BLUEPRINT)) or {}
    p = C.pdir(ws, C.AUDIENCE_REVIEW)
    if not check_only:
        if p.is_file() and not force:
            print("[i] 审稿文件已存在，保持不动：%s（重写加 --force）" % p)
        else:
            C.write_text(p, render_audience_template(bp))
            print(C.hr())
            print("④ 第四轮 · 观众视角审稿模板")
            print(C.hr())
            print("  [OK] 已写出：%s" % p)
            print("  填写口径：prompts/s3c-audience-review.md（七问 + 三条优先修改）")
            return 0
    text = C.read_text(p)
    if not text:
        print("[FAIL] 找不到审稿文件：%s（先跑 audience --template）" % p)
        return 2
    errors, warns = validate_audience(text)
    print(C.hr())
    print("④ 第四轮 · 审稿校验")
    print(C.hr())
    for w in warns:
        print("  [WARN] %s" % w)
    for e in errors:
        print("  [FAIL] %s" % e)
    print("-" * 74)
    if errors:
        print("[NG] 审稿不完整（%d 项）。空话式评价挡不住问题，请补具体集号与情节。" % len(errors))
        return 2
    print("[OK] 审稿完整%s。若七问指向结构问题，回 plan 改 blueprint 再 review。"
          % ("（含 %d 项告警）" % len(warns) if warns else ""))
    return 0


def _q_sections(text: str) -> dict:
    """按 `## Qn` 切段 → {n: (标题, 正文)}。"""
    out, cur, buf = {}, None, []
    for line in str(text or "").splitlines():
        m = re.match(r"^##\s*Q(\d)\s*[：:、.]?\s*(.*)$", line.strip())
        if m:
            if cur:
                out[cur] = ("", "\n".join(buf).strip())
            cur, buf = int(m.group(1)), []
        elif line.strip().startswith("## "):
            if cur:
                out[cur] = ("", "\n".join(buf).strip())
            cur, buf = None, []
        elif cur is not None:
            buf.append(line)
    if cur:
        out[cur] = ("", "\n".join(buf).strip())
    return out


def validate_audience(text: str) -> tuple:
    errors, warns = [], []
    secs = _q_sections(text)
    ep_re = re.compile(r"EP\s*\d{1,3}", re.I)
    need_ep_hits = 0
    for q, title, need_ep in AUDIENCE_QUESTIONS:
        num = int(q[1:])
        body = (secs.get(num) or ("", ""))[1]
        # 去掉模板占位行
        body_clean = "\n".join(ln for ln in body.splitlines()
                               if not ln.strip().startswith("（≥40 字"))
        n_chars = len(_norm(body_clean))
        if n_chars < 40:
            errors.append("%s 未答或过短（%d 字，需 ≥40）：%s" % (q, n_chars, title))
            continue
        if need_ep:
            if ep_re.search(body_clean):
                need_ep_hits += 1
            else:
                errors.append("%s 没有引用具体集号（EPxx）：%s" % (q, title))
    if need_ep_hits < 4:
        errors.append("只有 %d 问引用了具体集号（至少 4 问）—— 属笼统评价" % need_ep_hits)

    # Q7 必须落成「按收益排序的 3 条 + 每条带改法」，否则等于没给结论
    q7_body = (secs.get(7) or ("", ""))[1]
    items = re.findall(r"(?m)^\s*(\d)[.、)]\s*(.+)$", q7_body)
    if len(items) != 3:
        errors.append("Q7 需恰好 3 条编号问题（现 %d 条），按修改收益排序" % len(items))
    else:
        for num, body in items:
            if len(_norm(body)) < 20:
                errors.append("Q7 第 %s 条过短（<20 字），要写问题 + 改法" % num)
            elif not ("改法" in body or "→" in body or "->" in body):
                errors.append("Q7 第 %s 条没有给改法（写「改法：」或用 → 连接）" % num)
    if "（≥40 字" in text:
        warns.append("模板占位行未清理干净（不影响判定，建议删掉）")
    return errors, warns


REF_TEMPLATE = {
    "source_hits": ["<对标剧名>"], "track": "<赛道>",
    "beat_sheet": [{"act": "起", "beat": "<...>", "ep_range": "1-9"}],
    "hook_chain": [{"ep": 1, "type": "<钩子类型>", "hook": "<...>"}],
    "structure_notes": "<从对标剧抽出的结构规律，不是剧情复述>",
}


def cmd_ref_template(a) -> int:
    ws = C.resolve_ws(a.workspace)
    p = C.write_json(C.pdir(ws, C.REFERENCE_STRUCTURE), REF_TEMPLATE)
    print("[OK] 已写出对标结构模板：%s（可被 plan 参考）" % p)
    return 0


def main() -> int:
    C.harden_stdio()
    ap = argparse.ArgumentParser(description="④ 剧本改写：集数规划 + FFS 骨架 + 结构自检")
    ap.add_argument("--workspace", default=None)
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("plan", help="把定位卡落成 N 集规划（默认 %d）" % DEFAULT_EPISODES)
    p.add_argument("--rank", type=int, default=1)
    p.add_argument("--episodes", type=int, default=None)
    p.add_argument("--genre", default=None,
                   help="套用题材公式并**跳过选题**（如 female-comeback）；工作区已有 genre-plan.json 时自动套用")
    p.add_argument("--from-outline", dest="from_outline", default=None, metavar="MD",
                   help="人工拆解表（EP01 | 事件 | 反转 | 钩子）。给了就以它为准覆盖句库")
    p.add_argument("--dry", action="store_true")
    p.set_defaults(fn=lambda a: plan(C.resolve_ws(a.workspace), a.rank, a.episodes, a.dry,
                                     a.genre, a.from_outline))
    p = sub.add_parser("build", help="生成某集 FFS 骨架")
    p.add_argument("--ep", type=int, required=True)
    p.add_argument("--shots", type=int, default=8)
    p.add_argument("--emit", action="store_true")
    p.add_argument("--dry", action="store_true")
    p.set_defaults(fn=lambda a: build(C.resolve_ws(a.workspace), a.ep, a.shots, a.emit, a.dry))
    p = sub.add_parser("lint", help="对已填写剧本做 FFS 结构自检")
    p.add_argument("--ep", type=int, required=True)
    p.set_defaults(fn=lambda a: lint(C.resolve_ws(a.workspace), a.ep))

    # ★ 四段法：A/B/C 诊断 → 结构审查 → 观众审稿
    p = sub.add_parser("diagnose", help="A 选题诊断 / B 改编策略 / C 故事主线（写正文前必须确认）")
    p.add_argument("--check", action="store_true", help="只校验必填项，不改文件")
    p.add_argument("--confirm", action="store_true", help="校验通过后置 structure_confirmed=true")
    p.add_argument("--force", action="store_true", help="整份重写诊断卡（会清空已填内容）")
    p.set_defaults(fn=lambda a: (diag_check(C.resolve_ws(a.workspace), True) if a.confirm
                                 else diag_check(C.resolve_ws(a.workspace)) if a.check
                                 else diag_init(C.resolve_ws(a.workspace), a.force)))
    p = sub.add_parser("review", help="第二轮：结构审查（注水/重复冲突/主角被动/反转不改格局）")
    p.add_argument("--profile", default=None,
                   help="题材侧重 id（revenge|sweet|suspense|family）；不给则按剧名自动匹配")
    p.add_argument("--write-fixes", dest="write_fixes", action="store_true",
                   help="另出 blueprint-fixes.md 待改清单")
    p.set_defaults(fn=lambda a: review(C.resolve_ws(a.workspace), a.profile, a.write_fixes))
    p = sub.add_parser("audience", help="第四轮：观众视角审稿（七问 + 三条优先修改）")
    p.add_argument("--check", action="store_true", help="校验审稿完整性")
    p.add_argument("--force", action="store_true", help="覆盖已有审稿模板")
    p.set_defaults(fn=lambda a: audience(C.resolve_ws(a.workspace), a.check, a.force))

    p = sub.add_parser("ref-template", help="写出对标结构模板")
    p.set_defaults(fn=cmd_ref_template)
    a = ap.parse_args()
    if not getattr(a, "fn", None):
        return plan(C.resolve_ws(a.workspace))
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
