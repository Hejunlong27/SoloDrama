# -*- coding: utf-8 -*-
"""characters.py —— 角色档案（把同一角色的多个变体归并成一张卡）

为什么需要这一层
----------------
引擎侧本来就是「一个角色 + 多个变体」，磁盘上的证据很清楚：

    04-资产/characters/P01_Elena_VIEW_00.png     三视图（含表情四宫格）
    04-资产/characters/P01_Elena_EXP_00.png      表情四态（旧口径的独立图）
    04-资产/characters/P01_Elena_LOOK-A_00.png   造型 A
    04-资产/characters/P01_Elena_LOOK-B_00.png   造型 B
    …
    refs.json: P01@VIEW / P01@EXP / P01@LOOK-A …

变体在 `pack_spec.variant_key()` 里已经被编码成 `P01@LOOK-A`，层别也有
`VARIANT_KINDS = base/turnaround/look/expression/state`。也就是说**归并所需的信息全都在**，
缺的只是「把它们按角色聚起来读出来」这一步 —— 之前界面只能看到一堆平铺的文件。

设计约束（不许破的）
--------------------
1. **不新增数据结构**：档案是派生视图，不落盘、不写库。数据源只有三样：
   `00-创作/02-资产库.md`（提示词与身份锚点）、`04-资产/characters/*`（出图产物）、
   `04-资产/refs.json`（key → 图）。
2. **不猜融合**：`VIEW` 已经按新规范含四宫格表情；旧项目里 `EXP` 是一张独立的竖图。
   两者都保留、都显示，**不自动删掉 EXP**，也不假装它们已经合并 —— 那是内容改动。
3. **跨目录容忍**：真实项目里 `04-资产` 的名字由 `layout.json` 决定，路径一律走
   `_layout.assets_dir()`，不在这里拼目录名。

只读。这个模块不写任何文件。
"""
from __future__ import annotations

import json
import pathlib
import re

from . import paths, studio

IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")

# 变体的层别 → 界面上的分区名与顺序。
# 顺序不是审美：三视图（身份基准）→ 造型（穿什么）→ 表情（什么情绪）→ 状态（哪一期）。
# 参考图生成时也是这个优先级，界面上顺序一致，人才不会挑错图。
LAYERS = [
    {"key": "base", "label": "主形象", "hint": "这一角色的基准图：先有它，再派生各套造型"},
    {"key": "turnaround", "label": "三视图", "hint": "身份基准：正/侧/背 + 表情四宫格"},
    {"key": "look", "label": "造型", "hint": "同一角色的不同穿搭或时期，各一张全身立绘"},
    {"key": "state", "label": "状态", "hint": "受伤、前世今生的形象差异"},
    {"key": "expression", "label": "表情", "hint": "旧口径的独立表情图"},
]

# 文件名 → 角色 id：`P01_Elena_LOOK-A_00.png` 取第一段
_ID_RE = re.compile(r"^([PSD]\d{2})_")


def _layer_of(code: str, label: str = "") -> str:
    """变体 code → 层别。与 `pack_spec.guess_variant_kind` 同口径，但这里不依赖引擎导入。"""
    c = str(code or "").upper()
    lb = str(label or "")
    if c.startswith("LOOK") or "造型" in lb or "服装" in lb:
        return "look"
    if "VIEW" in c or "TURN" in c or "三视图" in lb or "turnaround" in lb.lower():
        return "turnaround"
    if c.startswith("EXP") or "表情" in lb or "expression" in lb.lower():
        return "expression"
    if c.startswith("STATE") or "状态" in lb:
        return "state"
    return "base"


def _scan(adir: pathlib.Path) -> dict:
    """扫 characters 目录 → {角色id: {code: [相对路径, ...]}}。

    同一角色同一变体可能有多张（重出、`_00` `_01`），全部收下，
    界面按文件名排序展示 —— **不替用户选「哪张是对的」**。
    """
    out: dict = {}
    if not adir.is_dir():
        return out
    for p in sorted(adir.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in IMG_EXT:
            continue
        m = _ID_RE.match(p.name)
        if not m:
            continue
        aid = m.group(1)
        rest = p.stem[len(aid):].lstrip("_")
        # 去掉尾部的帧号 `_00`
        rest = re.sub(r"_\d+$", "", rest)
        # `<name>_<code>`：取最后一段当 code；没有下划线就是无 code 的主卡
        code = rest.rsplit("_", 1)[-1] if "_" in rest else ""
        if code.upper() in ("", aid):
            code = ""
        out.setdefault(aid, {}).setdefault(code, []).append(p)
    return out


def _md_prompts(ws) -> tuple:
    """从 `00-创作/02-资产库.md` 取每个角色的变体提示词与身份信息。

    解析失败不抛：资产库 md 是可选的（老项目可能只有出图没有 md），
    档案要能在「只有图、没有提示词」的情况下也显示出来。
    """
    p = pathlib.Path(str(ws)) / "00-创作" / "02-资产库.md"
    if not p.is_file():
        return {}, ""
    text = p.read_text(encoding="utf-8", errors="replace")
    # 引擎的解析器在 import 层；Web 不 import 引擎，这里只做**够用**的提取。
    # 真做校验/转换时走 `md2pack.parse_assets`（子进程或 CLI），不复用这段正则。
    secs = {}
    for m in re.finditer(r"^###\s+(P\d{2})\s*[｜|]\s*(.+?)\s*$", text, re.M):
        secs[m.group(1)] = {"name": m.group(2).strip(), "start": m.start()}
    keys = sorted(secs, key=lambda k: secs[k]["start"])
    for i, k in enumerate(keys):
        end = secs[keys[i + 1]]["start"] if i + 1 < len(keys) else len(text)
        body = text[secs[k]["start"]:end]
        variants = {}
        # `**LOOK-A 立绘提示词**` / `**三视图**` / `**表情四态**`
        for bm in re.finditer(r"\*\*([^*\n]+?)\*\*\s*\n+```[a-zA-Z]*\n(.*?)\n```", body, re.S):
            head = bm.group(1).strip()
            prompt = bm.group(2).strip()
            code = ""
            cm = re.search(r"(LOOK-[A-Z]|VIEW|EXP|STATE-[A-Z])", head)
            if cm:
                code = cm.group(1)
            elif "三视图" in head:
                code = "VIEW"
            elif "表情" in head:
                code = "EXP"
            if code:
                variants[code] = {"label": head, "prompt": prompt,
                                  "layer": _layer_of(code, head)}
        anchor = ""
        am = re.search(r"\|\s*一致性锚点\s*\|\s*(.+?)\s*\|", body)
        if am:
            anchor = am.group(1).strip()
        role = ""
        rm = re.search(r"\|\s*身份\s*\|\s*(.+?)\s*\|", body)
        if rm:
            role = rm.group(1).strip()
        secs[k].update({"variants": variants, "anchor": anchor, "role": role, "chars": len(body)})
    return secs, text


def roster(ws) -> dict:
    """角色档案：每个角色一张卡，卡内按层别归并全部变体。只读。"""
    ws = pathlib.Path(str(ws))
    adir = studio.assets_dir(ws) / "characters"
    refs = paths.read_json(studio.assets_dir(ws) / "refs.json", default=None) or {}

    scanned = _scan(adir)
    md, _md_text = _md_prompts(ws)

    # refs.json 里也可能登记了图（出图后回填），但没有落进 characters 目录的情况
    ref_map = {}
    for key, p in (refs.get("characters") or {}).items():
        if "@" in key:
            aid, _code = key.split("@", 1)
            ref_map.setdefault(aid, {})[_code] = p

    ids = sorted(set(scanned) | set(md) | set(ref_map))

    # 相对路径用 `_rel` 的口径（与 /media 一致）
    def rel(p):
        try:
            return str(pathlib.Path(p).relative_to(ws)).replace("\\", "/")
        except (ValueError, TypeError):
            return str(p or "")

    chars = []
    for aid in ids:
        info = md.get(aid) or {}
        md_vars = info.get("variants") or {}
        disk = scanned.get(aid) or {}
        codes = set(disk) | set(md_vars) | set(ref_map.get(aid) or {})

        items = []
        for code in codes:
            label = (md_vars.get(code) or {}).get("label") or ("主卡" if not code else code)
            layer = (md_vars.get(code) or {}).get("layer") or _layer_of(code, label)
            files = [rel(p) for p in (disk.get(code) or [])]
            if not files:
                r = (ref_map.get(aid) or {}).get(code)
                if r:
                    files = [rel(r)]
            items.append({
                "code": code or "BASE",
                "label": label,
                "layer": layer,
                "prompt": (md_vars.get(code) or {}).get("prompt") or "",
                "images": files,
                "count": len(files),
            })

        # 层别顺序 → code 顺序；没图的排后面（有提示词但还没出图，界面要能提示「待出图」）
        order = {x["key"]: i for i, x in enumerate(LAYERS)}
        items.sort(key=lambda x: (order.get(x["layer"], 99), x["code"], -x["count"]))

        have = sum(1 for x in items if x["count"])

        # ---- 主形象 ----
        # 一个角色只能有一个主形象：它是「这个角色长什么样」的唯一基准，
        # 各套造型都是它的派生。选取顺序（不随机、不取最新）：
        #   1) base 层（模板给的「主卡 / 基础造型」）；
        #   2) turnaround（三视图，含正/侧/背 + 表情，信息最全）；
        #   3) 第一个有图的 look（老项目常常只有造型、没有主卡）。
        # 都取不到就 master=None：界面显示「尚无主形象」，把它变成下一步该做的事。
        # 拿随便一张图冒充主形象，会让「主形象」这个词失去意义。
        def _first_img(layer):
            for x in items:
                if x["layer"] == layer and x["count"]:
                    return x
            return None

        master = _first_img("base") or _first_img("turnaround")
        if master is None:
            master = next((x for x in items if x["count"]), None)
        master_ref = None
        if master:
            master_ref = {"code": master["code"], "layer": master["layer"],
                          "label": master["label"], "image": master["images"][0],
                          "key": aid + ("@" + master["code"] if master["code"] not in ("", "BASE") else "")}

        chars.append({
            "id": aid,
            "name": info.get("name") or _name_from_files(disk) or aid,
            "role": info.get("role") or "",
            "anchor": info.get("anchor") or "",
            "variants": items,
            "variants_total": len(items),
            "variants_done": have,
            "images_total": sum(x["count"] for x in items),
            "master": master_ref,
            "master_missing": master_ref is None,
            # 封面＝主形象；没有主形象时才退回任何一张有图的变体
            "cover": (master_ref or {}).get("image")
                     or next((x["images"][0] for x in items if x["count"]), ""),
        })

    # 角色顺序：按 id（P01 在前），这是模板约定，不给用户「按名字排」的伪选项
    chars.sort(key=lambda c: c["id"])
    no_master = sum(1 for c in chars if c["master_missing"])

    # md 与 pack 的变体对不上 = 点「重出」会用**另一份提示词**出图。必须显式说出来。
    packs = _pack_codes(ws)
    drift = []
    for c in chars:
        pc = packs.get(c["id"])
        if pc is None:
            continue                     # 这个角色不在包里（包没用它，不报）
        md_set = {v["code"].upper() for v in c["variants"]}
        only_md = sorted(md_set - set(pc))
        only_pk = sorted(set(pc) - md_set)
        if only_md or only_pk:
            c["drift"] = {"md_only": only_md, "pack_only": only_pk}
            drift.append(c["id"])

    return {"ok": True, "dir": rel(adir), "layers": LAYERS,
            "source_md": "00-创作/02-资产库.md",
            "source_pack": "pack/assets/characters.json" if packs else "",
            "pack_exists": bool(packs), "drift": drift,
            "items": chars, "total": len(chars), "no_master": no_master,
            "note": "同一角色的三视图 / 多套造型 / 表情各是一张图，按层别归在一张卡里；"
                    "出图时按变体 code（如 LOOK-B）取对应那张做参考图"}


def _pack_codes(ws) -> dict:
    """制作包里每个角色的变体 code：`{P01: ["VIEW", "LOOK-A", ...]}`。读不到就空 dict。

    为什么角色档案需要它：档案的**提示词**来自 `00-创作/02-资产库.md`（人写的那份），
    而**出图**只认 `<ws>/pack`（`gen_assets_local.assets_from_pack`）。
    两边不同源，所以「改了 md 没重建 pack」时，界面显示的提示词与实际会喂给模型的不是一回事 ——
    点「重出这一张」出来的图会莫名其妙地不一样，且没有任何报错。

    这里只做**只读比对**，不试图自动同步（那属于导入环节 `md2pack` 的职责）。
    """
    p = pathlib.Path(str(ws)) / "pack" / "assets" / "characters.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    out = {}
    for it in (d.get("items") or []):
        if not isinstance(it, dict):
            continue
        aid = str(it.get("id") or "").strip()
        if not aid:
            continue
        out[aid] = [str(v.get("code") or "").strip().upper()
                    for v in (it.get("variants") or []) if isinstance(v, dict)]
    return out


def _name_from_files(disk: dict) -> str:
    """没有 md 时，从文件名里还原角色名（`P01_Elena_VIEW_00.png` → Elena）。"""
    for files in (disk or {}).values():
        for p in files:
            stem = p.stem
            m = re.match(r"^[PSD]\d{2}_(.+?)(?:_[A-Z][A-Z0-9-]*)?(?:_\d+)?$", stem)
            if m:
                return m.group(1).replace("_", " ")
    return ""
