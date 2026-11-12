#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""pack_spec.py —— 制作包规范的**唯一常量与校验真源**

为什么单独成文件
----------------
`pack_import.py`（搬运）、`nodes.py`（调度）、`web/core/*`（界面）都要知道
「什么算合法的制作包」。如果三处各写一遍正则，就一定会漂成三个口径 ——
本仓库在「五锚」「集号 epNN」上都吃过这个亏。

所以：**常量、ID 规则、必需字段、校验函数，全部只在这里定义。**

规范文本见 `docs/pack/PACK-SPEC.md`；本模块是它的可执行版本，两者必须同步。

设计纪律
--------
* 纯标准库（re / json / pathlib / dataclasses），零第三方、零网络、零计费。
* **只校验、不修正**：发现越界就报错，不替用户把 duration 从 3 改成 4。
  自愈会让「导入成功」失去信息量 —— 出片时才发现少了一秒，比导入时红一次更贵。
* 校验分两档：`errors` 阻断（退出码 2），`warnings` 只提示（退出码 0）。
  分档依据只有一条：**错了会不会导致钱白花或产物不可用**。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import h3_prompt as H3        # 六段式（Ref2VA）结构判据的唯一真源
import prompt_marks as PM      # 台词标记判据的唯一真源（<d>[语种] …</d>）

# ===========================================================================
# 一、版本
# ===========================================================================
SPEC_PACK = "solodrama-pack/1"
SPEC_ASSETS = "solodrama-assets/1"
SPEC_EPISODE = "solodrama-episode/1"

SUPPORTED = {SPEC_PACK, SPEC_ASSETS, SPEC_EPISODE}

PACK_FILE = "pack.json"
ASSET_DIR = "assets"
EPISODE_DIR = "episodes"
REFS_DIR = "refs"
REPORT_FILE = "_import_report.md"

# 资产三份文件的固定顺序：出图顺序 = 人物 → 场景 → 道具
ASSET_FILES = (("characters.json", "character"), ("scenes.json", "scene"), ("props.json", "prop"))
ASSET_KINDS = ("character", "scene", "prop")

# ===========================================================================
# 二、ID 规则
# ===========================================================================
# ID = 1–3 个大写字母 + 2–3 位数字。两位是为了 P01，三位是给长剧留的余量（P100）。
ID_RE = re.compile(r"^([A-Z]{1,3})(\d{2,3})$")

# 前缀 → kind。FX 归 props（特效是「后期的道具」，共用参考图表，但默认不进视频槽）。
PREFIX_KIND = {
    "P": "character",   # person
    "S": "scene",       # scene
    "D": "prop",        # device / prop
    "FX": "prop",       # effect layer
}
KIND_DESC = {"character": "人物", "scene": "场景", "prop": "道具"}

# 集号文件名：ep01 … ep99；≥100 集用三位（ep100）。
EP_FILE_RE = re.compile(r"^ep(\d{2,3})\.json$")
SHOT_ID_RE = re.compile(r"^shot_(\d{3,4})$")

# ===========================================================================
# 三、硬约束
# ===========================================================================
DUR_MIN, DUR_MAX = 4, 15          # 平台单段时长上下限（秒）；越界直接失败
DUR_TOLERANCE = 2.0               # 声明总时长与逐镜求和的容差（秒）；超出只告警
MAX_REFS = 6                      # H3 参考槽上限
VALID_RATIOS = ("9:16", "16:9", "1:1", "4:3", "3:4")

# ★ 2026-11-12：角色设定卡固定 16:9 横版（左 60% 三视图 + 右 40% 表情四宫格）。
#   场景、分镜、视频按项目的竖屏交付画幅；道具卡保持 1:1。
#   ⚠ 16:9 角色卡是设计资产，下游视频参考应使用裁出的单正面视图，不要把整张多视图卡直接喂给视频模型。
DEFAULT_ASPECT = {
    "character": "16:9",
    "scene": "16:9",
    "prop": "16:9",
    "board": "9:16",
    "video": "9:16",
}

DEFAULT_DELIVERY = {"width": 1080, "height": 1920, "fps": 24,
                    "episode_count": 0, "target_duration": 0}

# base 类变体代号：单变体时文件名不加后缀
BASE_CODES = {"", "base", "基础", "基础造型", "空景", "主卡"}


# ===========================================================================
# 四、报告对象
# ===========================================================================
class Report:
    """导入报告：errors 阻断，warnings 提示，notes 是中性说明（做了什么搬运）。"""

    def __init__(self) -> None:
        self.errors: list = []
        self.warnings: list = []
        self.notes: list = []

    def err(self, code: str, msg: str) -> None:
        self.errors.append({"code": code, "msg": msg})

    def warn(self, code: str, msg: str) -> None:
        self.warnings.append({"code": code, "msg": msg})

    def note(self, msg: str) -> None:
        self.notes.append(msg)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict:
        return {"ok": self.ok, "errors": self.errors,
                "warnings": self.warnings, "notes": self.notes}

    def render(self) -> str:
        out = []
        if self.errors:
            out.append("错误（阻断，必须修）：")
            out += ["  [E] %-10s %s" % (e["code"], e["msg"]) for e in self.errors]
        if self.warnings:
            out.append("告警（不阻断）：")
            out += ["  [W] %-10s %s" % (w["code"], w["msg"]) for w in self.warnings]
        if self.notes:
            out.append("说明：")
            out += ["  [i] %s" % n for n in self.notes]
        return "\n".join(out) or "（无问题）"


# ===========================================================================
# 五、读取
# ===========================================================================
def _read_json(p: Path, report: Report, code: str):
    """读 JSON；失败时记一条 error 并返回 None（不再抛，让校验一次报全）。"""
    if not p.is_file():
        report.err(code, "文件不存在：%s" % p)
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, ValueError) as e:
        report.err(code, "%s 无法解析：%s" % (p.name, e))
        return None


def kind_of(asset_id: str) -> str | None:
    """资产 ID → kind；不合规返回 None。"""
    m = ID_RE.match(str(asset_id or "").strip())
    if not m:
        return None
    return PREFIX_KIND.get(m.group(1))


def ep_key(ep_index: int) -> str:
    """集号（1 起）→ `ep01`。"""
    return "ep%02d" % int(ep_index)


def ep_index_of(name: str) -> int | None:
    """`ep01` / `ep01.json` / `1` / `第1集` → 1；认不出返回 None。"""
    s = str(name or "").strip()
    m = EP_FILE_RE.match(s if s.endswith(".json") else s + ".json")
    if m:
        return int(m.group(1))
    m = re.match(r"^(?:ep)?(\d{1,3})$", s, re.I)
    if m:
        return int(m.group(1))
    m = re.match(r"^第(\d{1,3})集$", s)
    return int(m.group(1)) if m else None


# variant 的「层」：模板产出的资产卡是多层的（三视图 / 造型 / 表情 / 状态），
# 引擎以前只能存一层，于是信息被压扁。这里显式记录层别，出图时可按层决定顺序与用途。
VARIANT_KINDS = ("base", "turnaround", "look", "expression", "state")


def guess_variant_kind(code: str, label: str = "") -> str:
    """按 code / label 推断层别。识别不出来就是 base。"""
    c = str(code or "").upper()
    lb = str(label or "")
    if c.startswith("LOOK") or "造型" in lb or "服装" in lb:
        return "look"
    if ("VIEW" in c or "TURN" in c or c.startswith("三视图")
            or "三视图" in lb or "turnaround" in lb.lower()):
        return "turnaround"
    if c.startswith("EXP") or "表情" in lb or "expression" in lb.lower():
        return "expression"
    if c.startswith("STATE") or "状态" in lb:
        return "state"
    return "base"


def variant_key(asset_id: str, code: str = "") -> str:
    """资产 ID + 变体代号 → 参考图表里的 key。

    单变体（code 为空或 base 类）→ `P01`；多变体 → `P01@LOOK-A`。
    为什么带 `@`：引擎按 key 精确查表，同名不同图会串造型；`@` 不是路径字符，不会被误当文件。
    """
    c = str(code or "").strip()
    if not c or c.lower() in BASE_CODES:
        return asset_id
    return "%s@%s" % (asset_id, c)


def load_pack(pack_dir) -> tuple:
    """读整个制作包 → (pack, assets, episodes, report)。

    * `pack` 是 pack.json 原文（含补全的默认值）
    * `assets` = {kind: {id: item}}，item 里补全了 `variants[].code` 与 `aspect`
    * `episodes` = {ep_index: episode_dict}
    读不到的项留空，问题全记在 report 里 —— **不在这里抛异常**，
    这样 CLI 能一次把 20 个问题打印完，而不是修一个重启一次。
    """
    pack_dir = Path(pack_dir).expanduser().resolve()
    rep = Report()

    raw = _read_json(pack_dir / PACK_FILE, rep, "PACK001") or {}
    if not isinstance(raw, dict):
        rep.err("PACK002", "pack.json 顶层必须是对象")
        raw = {}

    if raw.get("spec") != SPEC_PACK:
        rep.err("PACK003", "spec 必须是 '%s'，实际是 %r" % (SPEC_PACK, raw.get("spec")))

    pack = dict(raw)
    pack.setdefault("spec", SPEC_PACK)
    pack.setdefault("title", "")
    pack.setdefault("style_lock", "")
    pack.setdefault("negative", "")
    dl = dict(DEFAULT_DELIVERY)
    if isinstance(raw.get("delivery"), dict):
        dl.update({k: v for k, v in raw["delivery"].items() if v is not None})
    pack["delivery"] = dl
    asp = dict(DEFAULT_ASPECT)
    if isinstance(raw.get("aspect"), dict):
        for k, v in raw["aspect"].items():
            if k in asp and isinstance(v, str) and v.strip():
                asp[k] = v.strip()
    pack["aspect"] = asp

    # ★ style_lock 为空必须阻断。
    #   为什么不是「给个默认值」：默认值会让一季的图带错风格，而**出图不会报错**，
    #   等于错误被推迟到发布时才发现（那时已经出了几百张图）。
    if not str(pack.get("style_lock") or "").strip():
        rep.err("STYLE001", "style_lock 为空 —— 画风必须由创作 Skill 在 pack.json 里一次定死，"
                            "引擎不提供默认值也不做三轨选择（见 PACK-SPEC §3.1）")

    # ---- 资产 ----------------------------------------------------------
    assets: dict = {}
    for fname, default_kind in ASSET_FILES:
        doc = _read_json(pack_dir / ASSET_DIR / fname, rep, "ASSET001")
        if doc is None:
            assets[default_kind] = {}
            continue
        if not isinstance(doc, dict):
            rep.err("ASSET002", "%s 顶层必须是对象" % fname)
            assets.setdefault(default_kind, {})
            continue
        if doc.get("spec") != SPEC_ASSETS:
            rep.err("ASSET003", "%s 的 spec 必须是 '%s'，实际是 %r"
                    % (fname, SPEC_ASSETS, doc.get("spec")))
        kind = str(doc.get("kind") or default_kind)
        if kind not in ASSET_KINDS:
            rep.err("ASSET004", "%s 的 kind 非法：%r（可选 %s）"
                    % (fname, kind, "/".join(ASSET_KINDS)))
            kind = default_kind
        bucket = assets.setdefault(kind, {})
        items = doc.get("items")
        if not isinstance(items, list):
            rep.err("ASSET005", "%s 的 items 必须是数组" % fname)
            continue
        for i, it in enumerate(items):
            if not isinstance(it, dict):
                rep.err("ASSET006", "%s.items[%d] 不是对象" % (fname, i))
                continue
            aid = str(it.get("id") or "").strip()
            if not aid:
                rep.err("ASSET007", "%s.items[%d] 缺 id" % (fname, i))
                continue
            k = kind_of(aid)
            if k is None:
                rep.err("ASSET008", "%s：id=%r 不合规（应为 1–3 个大写字母 + 2–3 位数字，如 P01）"
                        % (fname, aid))
                continue
            if k != kind:
                rep.err("ASSET009", "%s：id=%s 的前缀属于 %s，但文件 kind=%s"
                        % (fname, aid, KIND_DESC.get(k, k), KIND_DESC.get(kind, kind)))
                continue
            if aid in bucket:
                rep.err("ASSET010", "%s：id=%s 重复" % (fname, aid))
                continue
            one = dict(it)
            one["id"] = aid
            one["kind"] = kind
            one.setdefault("name", aid)
            one.setdefault("anchors", [])
            vs = one.get("variants")
            if not isinstance(vs, list) or not vs:
                rep.err("ASSET011", "%s：id=%s 没有 variants（每个资产至少 1 张图）" % (fname, aid))
                continue
            clean, seen = [], set()
            for j, v in enumerate(vs):
                if not isinstance(v, dict):
                    rep.err("ASSET012", "%s：id=%s variants[%d] 不是对象" % (fname, aid, j))
                    continue
                code = str(v.get("code") or "").strip()
                if not code:
                    code = "base" if len(vs) == 1 else "状态%d" % (j + 1)
                    rep.warn("ASSET013", "%s：id=%s variants[%d] 缺 code，按 %r 处理"
                             % (fname, aid, j, code))
                if code in seen:
                    rep.err("ASSET014", "%s：id=%s 的 variant code 重复：%r" % (fname, aid, code))
                    continue
                seen.add(code)
                prompt = str(v.get("prompt") or "").strip()
                if not prompt:
                    rep.err("ASSET015", "%s：id=%s 的 %s 提示词为空（无法出图）" % (fname, aid, code))
                    continue
                raw_kind = str(v.get("kind") or "").strip().lower()
                label = str(v.get("label") or code)
                vkind = raw_kind or guess_variant_kind(code, label)
                if vkind not in VARIANT_KINDS:
                    rep.warn("ASSET016", "%s：id=%s 的 %s kind=%r 不认识，按推断值 %r 处理"
                             % (fname, aid, code, raw_kind, guess_variant_kind(code, label)))
                    vkind = guess_variant_kind(code, label)
                clean.append({
                    "code": code,
                    "label": label,
                    "kind": vkind,
                    "prompt": prompt,
                    "aspect": str(v.get("aspect") or pack["aspect"].get(kind) or "").strip(),
                    "episodes": [str(x).strip() for x in (v.get("episodes") or []) if str(x).strip()],
                })
            if not clean:
                continue
            one["variants"] = clean
            one["post_only"] = (aid.startswith("FX"))
            one["_file"] = fname
            bucket[aid] = one
        assets[kind] = bucket

    # 跨 kind 查重（P01 只能出现一次）
    seen_ids: dict = {}
    for kind, bucket in assets.items():
        for aid in bucket:
            if aid in seen_ids:
                rep.err("ASSET016", "资产 id=%s 在 %s 与 %s 中重复出现"
                        % (aid, seen_ids[aid], kind))
            seen_ids[aid] = kind

    # ---- 分集 ----------------------------------------------------------
    episodes: dict = {}
    ep_root = pack_dir / EPISODE_DIR
    if not ep_root.is_dir():
        rep.err("EP001", "缺少 episodes/ 目录：%s" % ep_root)
    else:
        files = sorted([p for p in ep_root.iterdir() if p.is_file() and p.suffix.lower() == ".json"])
        if not files:
            rep.err("EP002", "episodes/ 里没有任何 epNN.json")
        for p in files:
            m = EP_FILE_RE.match(p.name)
            if not m:
                rep.warn("EP003", "文件名不符合 epNN.json，已跳过：%s" % p.name)
                continue
            idx = int(m.group(1))
            doc = _read_json(p, rep, "EP004")
            if doc is None:
                continue
            if not isinstance(doc, dict):
                rep.err("EP005", "%s 顶层必须是对象" % p.name)
                continue
            if doc.get("spec") != SPEC_EPISODE:
                rep.err("EP006", "%s 的 spec 必须是 '%s'，实际是 %r"
                        % (p.name, SPEC_EPISODE, doc.get("spec")))
            if int(doc.get("episode") or 0) != idx:
                rep.err("EP007", "%s 的 episode=%r 与文件名不一致（应为 %d）"
                        % (p.name, doc.get("episode"), idx))
            shots = doc.get("shots")
            if not isinstance(shots, list) or not shots:
                rep.err("EP008", "%s 的 shots 必须是非空数组" % p.name)
                continue
            norm = dict(doc)
            norm["episode"] = idx
            norm["_file"] = p.name
            norm["shots"] = _norm_shots(shots, idx, assets, pack, rep, p.name)
            episodes[idx] = norm

    # ---- 计数一致性 -----------------------------------------------------
    want = int(pack["delivery"].get("episode_count") or 0)
    if want and episodes and len(episodes) != want:
        rep.warn("EP009", "delivery.episode_count=%d，但 episodes/ 里有 %d 集"
                 % (want, len(episodes)))

    return pack, assets, episodes, rep


def _norm_shots(shots: list, idx: int, assets: dict, pack: dict,
                rep: Report, fname: str) -> list:
    """逐镜校验 + 归一化（补 ratio、拆 cast、校 Mixed 图号）。"""
    known: dict = {}
    for kind, bucket in assets.items():
        for aid, item in bucket.items():
            known[aid] = item
    out, seen = [], set()
    for i, s in enumerate(shots):
        tag = "%s shots[%d]" % (fname, i)
        if not isinstance(s, dict):
            rep.err("SHOT001", "%s 不是对象" % tag)
            continue
        sid = str(s.get("id") or s.get("shot_id") or "").strip()
        if not SHOT_ID_RE.match(sid):
            rep.err("SHOT002", "%s 的 id=%r 不合规（应形如 shot_001）" % (tag, sid))
            continue
        if sid in seen:
            rep.err("SHOT003", "%s 的 id=%s 重复" % (tag, sid))
            continue
        seen.add(sid)

        dur = s.get("duration")
        try:
            dur = float(dur)
        except (TypeError, ValueError):
            rep.err("SHOT004", "%s 缺 duration 或不是数字：%r" % (tag, dur))
            continue
        if dur < DUR_MIN or dur > DUR_MAX:
            rep.err("SHOT005", "%s（%s）duration=%g 越界，平台只接受 %d–%d 秒"
                    % (tag, sid, dur, DUR_MIN, DUR_MAX))
            continue

        ratio = str(s.get("ratio") or pack["aspect"].get("video") or "").strip()
        if ratio not in VALID_RATIOS:
            rep.warn("SHOT006", "%s（%s）ratio=%r 不在常用集合内，按原样提交"
                     % (tag, sid, ratio))

        cast_raw = s.get("cast")
        if not isinstance(cast_raw, list) or not cast_raw:
            rep.err("SHOT007", "%s（%s）缺 cast（至少 1 个参考图）" % (tag, sid))
            continue
        if len(cast_raw) > MAX_REFS:
            rep.err("SHOT008", "%s（%s）cast 有 %d 项，超过平台参考槽上限 %d"
                    % (tag, sid, len(cast_raw), MAX_REFS))
            continue

        cast, used = [], set()
        bad = False
        for j, c in enumerate(cast_raw):
            if isinstance(c, str):
                c = {"asset": c}
            if not isinstance(c, dict):
                rep.err("SHOT009", "%s（%s）cast[%d] 不是对象或字符串" % (tag, sid, j))
                bad = True
                continue
            aid = str(c.get("asset") or c.get("id") or "").strip()
            item = known.get(aid)
            if item is None:
                rep.err("SHOT010", "%s（%s）cast[%d] 引用了不存在的资产 %r"
                        % (tag, sid, j, aid))
                bad = True
                continue
            codes = [v["code"] for v in item["variants"]]
            code = str(c.get("variant") or "").strip()
            if code and code not in codes:
                rep.err("SHOT011", "%s（%s）cast[%d] %s 没有变体 %r（可选 %s）"
                        % (tag, sid, j, aid, code, "/".join(codes)))
                bad = True
                continue
            if not code:
                code = codes[0]
            key = variant_key(aid, code)
            if key in used:
                rep.warn("SHOT012", "%s（%s）cast 里 %s 重复，已去重" % (tag, sid, key))
                continue
            used.add(key)
            cast.append({"asset": aid, "variant": code, "key": key,
                         "kind": item["kind"], "post_only": item.get("post_only", False)})
        if bad:
            continue
        if not cast:
            rep.err("SHOT013", "%s（%s）cast 去重后为空" % (tag, sid))
            continue

        board = str(s.get("board_prompt") or s.get("board") or "").strip()
        video = str(s.get("video_prompt") or s.get("prompt") or "").strip()
        if not board:
            rep.warn("SHOT014", "%s（%s）缺 board_prompt，分镜图环节会跳过该镜" % (tag, sid))
        if not video:
            rep.err("SHOT015", "%s（%s）缺 video_prompt（出片必需）" % (tag, sid))
            continue

        # 图号越界检查：n 不超过 cast 数（分镜图占 1 号，故上限为 len(cast)+1）。
        # ★ 2026-11-06：两种写法都认 —— `<Picture n>`（现行六段式）与 `{{Mixed n}}`
        #   （2026-11 之前的老包）。老包仍按原规则拦，不做静默转换。
        nums = [int(a or b) for a, b in re.findall(
            r"\{\{\s*(?:Mixed|Picture)\s*(\d+)\s*\}\}|<Picture\s+(\d+)\s*>", video)]
        if nums and max(nums) > len(cast) + 1:
            rep.err("SHOT016", "%s（%s）video_prompt 里最大图号 Picture %d 超过 cast 数 %d + 分镜图 1 张"
                    % (tag, sid, max(nums), len(cast)))
            continue

        # ★ 2026-11-06：裸写在引号里的中文台词，H3 会当成「画面中应出现的文字」直接烧成
        #   画面字幕 —— 出片后无法去除，只能重跑。规范写法是 `<d>[Chinese] 原句。</d>`。
        #   **只告警不阻断**：标记不是硬约束，模型仍可能偶发画字；而拦下来会让
        #   「本来能跑、只是字幕难看」的项目连导入都过不去。判据见 `prompt_marks.py`。
        bare = PM.find_bare(video)
        if bare:
            rep.warn("SHOT018",
                     "%s（%s）video_prompt 有 %d 处引号中文没包 <d> 标记，出片会烧成画面字幕：%s"
                     % (tag, sid, len(bare), " / ".join(bare[:3])))

        # ★ 2026-11-06：**视频提示词必须是 H3 多参（Ref2VA）六段式**。
        #   为什么是阻断而不是告警：六段结构决定「哪张参考图是谁」。缺了 subject_definitions，
        #   上传的图对模型只是几张没署名的图，人物与场景会漂 —— 出片能出，但每条都要重跑，
        #   那才是真的贵。判据只有一份（`h3_prompt.py`），这里只做 severity 映射。
        h3_err, h3_warn = H3.lint(video, duration=float(dur), n_cast=len(cast))
        for bucket, ident, msg in h3_err:
            rep.err("SHOT019" if bucket == "struct" else "SHOT020",
                    "%s（%s）%s（%s）" % (tag, sid, msg, ident))
        for _bucket, ident, msg in h3_warn:
            rep.warn("SHOT021", "%s（%s）%s（%s）" % (tag, sid, msg, ident))

        out.append({
            "id": sid,
            "duration": int(dur) if float(dur).is_integer() else dur,
            "ratio": ratio,
            "cast": cast,
            "board_prompt": board,
            "video_prompt": video,
            "dialogue": _norm_dialogue(s.get("dialogue"), cast, rep, tag, sid),
            "notes": str(s.get("notes") or "").strip(),
        })

    # id 连续性：不连续只告警（用户可能故意删了一镜）
    order = [o["id"] for o in out]
    if order != sorted(order):
        rep.warn("SHOT017", "%s 的 shots 不是按 id 升序排列，导入后按数组顺序执行" % fname)
    total = sum(float(o["duration"]) for o in out)
    declared = shots and isinstance(shots[0], dict)  # noqa: F841 —— 便于阅读
    return out


def _norm_dialogue(raw, cast: list, rep: Report, tag: str, sid: str) -> list:
    """台词块：只保留能定位到本镜 cast 内资产的条目。"""
    if not raw:
        return []
    if not isinstance(raw, list):
        rep.warn("DLG001", "%s（%s）dialogue 不是数组，已忽略" % (tag, sid))
        return []
    keys = {c["asset"] for c in cast}
    out = []
    for i, d in enumerate(raw):
        if not isinstance(d, dict):
            continue
        aid = str(d.get("asset") or d.get("who") or "").strip()
        text = str(d.get("text") or "").strip()
        if not text:
            continue
        if aid not in keys:
            rep.warn("DLG002", "%s（%s）dialogue[%d] 的 asset=%r 不在本镜 cast 里，已忽略"
                     % (tag, sid, i, aid))
            continue
        try:
            start = float(d.get("start"))
        except (TypeError, ValueError):
            start = None
        try:
            end = float(d.get("end"))
        except (TypeError, ValueError):
            end = None
        out.append({"asset": aid, "text": text,
                    "start": start, "end": end})
    return out


def refs_lookup(pack_dir) -> dict:
    """扫 `refs/` → {资产 ID: 绝对路径}。只认文件名主干是合法 ID 的图。"""
    out: dict = {}
    d = Path(pack_dir).expanduser().resolve() / REFS_DIR
    if not d.is_dir():
        return out
    for p in d.iterdir():
        if not p.is_file() or p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            continue
        if ID_RE.match(p.stem):
            out[p.stem] = p.resolve()
    return out


def summarize(pack: dict, assets: dict, episodes: dict) -> dict:
    """给 CLI / Studio 用的一行摘要。"""
    n_assets = sum(len(v) for v in assets.values())
    n_variants = sum(len(i["variants"]) for v in assets.values() for i in v.values())
    n_shots = sum(len(e.get("shots") or []) for e in episodes.values())
    total_s = sum(float(s["duration"]) for e in episodes.values() for s in (e.get("shots") or []))
    return {
        "title": pack.get("title") or "",
        "episodes": len(episodes),
        "assets": n_assets,
        "images": n_variants,
        "shots": n_shots,
        "duration_s": round(total_s, 1),
        "by_kind": {k: len(v) for k, v in assets.items()},
    }
