# -*- coding: utf-8 -*-
r"""character_design.py —— 角色造型设计器（3 项签名，不是 7 维骨相）

## 2026-11-01 重写：从「七维骨相」砍到「三项签名」

旧版把长相拆成七维（骨相 7 槽 / 发型 / 眉眼 / 色签名 / 织物 / 阶层 / 姿态），
1765 行、24 条锚、8 个人群桶、5 档阶层的自动判定 —— 产出的资产卡精细到
「中庭偏长、下颌角 118°、眉骨突出 2mm」，而剧情还停在「她推门进来」。
**刻画精度远超叙事需求，边际收益为负**：模型并不照着这些条款画，人也不会照着审。

新版只保留**真的能改变出图结果**的三项：

| # | 项 | 内容 | 为什么留 |
|---|---|---|---|
| A1 | 身份 | 代号 / 姓名 / 年龄 / 性别 / 身份 / 阵营 / 皮肤 / 表情 | 决定「这是谁」，模型和观众都靠它 |
| A2 | 造型 | 色签名（阵营色相槽 + 明度分层）+ 服装（中/英）+ 发型 | 3 米外唯一能分辨的东西：轮廓 + 主色 |
| A3 | 锚 | 一处非对称标记，**可为空** | 模型画不出「气质」，但画得出一颗痣 |

删掉的东西及其理由：
- **骨相 7 槽**：模型不会按「中庭比例」执行，只会按「年轻女性」执行；写满七槽等于写一张均值脸。
  真正的辨识靠发型轮廓 + 主色 + 锚，这三样在 512px 缩略图上就能分辨。
- **人群桶 / 阶层自动判定**：靠「母/父/病」这类关键词推断阶层，31 岁护士会被判成老太太。
  阶层现在只从名册读；名册没写就不猜。
- **织物轮转 / 姿态表**：这两项在成片里几乎不可见，却让每张卡多 200 字。
- **面部距离规则 R1/R2**：既然不分配骨相，就没有「面部距离」可算；留着只会产生假精度。

保留的规则（4 条，机器可判）：

| # | 规则 | 判据 |
|---|---|---|
| R1 | 不同阵营色相间隔 ≥ 30° | 色相环最短弧 |
| R2 | 识别锚全局唯一 | 不得两人共用同一处标记 |
| R3 | 主演发型不重复 | 群演可复用，只告警 |
| R4 | 文案不得含评价性美颜词 | 见 `BANNED_WORDS` |

## 用法

```bash
python stages/assets/scripts/character_design.py plan --roster roster.json --out 04-资产/design
python stages/assets/scripts/character_design.py check --bible 04-资产/design/character-bible.json
python stages/assets/scripts/character_design.py audit --md 资产提示词.md   # 老项目体检
python stages/assets/scripts/character_design.py template --out roster.json
```

## 纪律（别删）

1. **纯标准库、零网络、零计费**：造型设计不该依赖任何 API。
2. **确定性**：同一份名册 + 同一 seed 必得同一份结果，便于 diff 与进 git。
3. **不发明剧本没给的身份**：身份/年龄/阵营一律从名册读；名册缺失就留空，不脑补。
4. **色签名不是滤镜**：主色落在服装与配饰上，环境仍按场景卡走。
5. **写文件一律 LF**（`newline=""`），否则 Windows 的 CRLF 会污染 `manifest.sha256`。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys

try:                                    # Windows 控制台 GBK → 强制 UTF-8
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[union-attr]
except Exception:                                                # noqa: BLE001
    pass

try:                                    # 同目录直接 import / 作为包内模块
    from prompt_templates import build_char          # type: ignore
    from sanitize import F                            # type: ignore
except ImportError:                                   # pragma: no cover
    from .prompt_templates import build_char          # type: ignore
    from .sanitize import F                           # type: ignore


LIB_VERSION = "2.0.0"

# ===========================================================================
# 一、词库（只留三项签名用得到的）
# ===========================================================================
# 族裔基线：只影响「皮肤与五官材质」，不再逐条改写骨相槽。
REGION = {
    "east_asian": {
        "cn": "东亚",
        "line": "东亚面孔：肤色偏黄调的浅至中等（不是冷白瓷）；黑发、发丝粗硬带蓝紫反光。",
        "forbid": "五官不混入欧美高鼻骨与深眼窝",
    },
    "western": {
        "cn": "欧美",
        "line": "欧美面孔：肤色从冷白到橄榄都有；发色金棕黑皆可；眉骨与鼻梁立体度自然。",
        "forbid": "五官不混入东亚扁平鼻骨与内双",
    },
    "south_asian": {
        "cn": "南亚",
        "line": "南亚面孔：肤色偏暖棕；睫毛浓密、眉眼距近；发色深黑带自然卷。",
        "forbid": "五官不混入北欧冷白肤色",
    },
    "latin": {
        "cn": "拉丁",
        "line": "拉丁面孔：肤色偏暖橄榄或浅棕；深色卷发；眉形浓而连。",
        "forbid": "五官不混入东亚内双特征",
    },
}

# 发型：**唯一保留的「长相」维度**。理由是它在缩略图上就能分辨，而骨相不能。
# id 只用于「同剧不重复」判定，不再参与任何骨相计算。
HAIR = [
    {"id": "H01", "name": "高蓬松马尾", "gender": "f", "age": (14, 40), "tone": "casual",
     "detail": "深色头发在脑后扎成高蓬松马尾，发根立起、发尾散开，鬓角与额前留几缕碎发",
     "forbid": "不画成低马尾或披发"},
    {"id": "H02", "name": "低盘髻", "gender": "f", "age": (28, 80), "tone": "formal",
     "detail": "头发向后梳紧、在颈后盘成低髻，发丝服帖、无碎发，露出完整发际线",
     "forbid": "不画成松散丸子头"},
    {"id": "H03", "name": "齐耳内扣短发", "gender": "f", "age": (16, 55), "tone": "any",
     "detail": "齐耳短发，发尾向内扣住下颌线，发顶蓬松、侧分",
     "forbid": "不画成长发或外翻"},
    {"id": "H04", "name": "长直发", "gender": "f", "age": (14, 45), "tone": "any",
     "detail": "及胸直发，中分，发尾齐平无层次，发丝服帖贴住肩线",
     "forbid": "不画成卷发或大波浪"},
    {"id": "H05", "name": "大波浪", "gender": "f", "age": (20, 50), "tone": "formal",
     "detail": "及肩大波浪，侧分，卷度松而不碎，发尾外翻",
     "forbid": "不画成直发或紧卷"},
    {"id": "H06", "name": "低马尾", "gender": "f", "age": (14, 60), "tone": "casual",
     "detail": "后颈低马尾，无刘海，额前干净，发尾自然垂落",
     "forbid": "不画成高马尾或盘发"},
    {"id": "H07", "name": "编发盘头", "gender": "f", "age": (16, 45), "tone": "formal",
     "detail": "头发编成辫子后绕头盘起，留少量碎发在耳前",
     "forbid": "不画成披发或马尾"},
    {"id": "H08", "name": "灰色短发", "gender": "f", "age": (45, 90), "tone": "any",
     "detail": "花白短发，剪到耳上，发根蓬松，发尾利落",
     "forbid": "不画成黑色或长发"},
    {"id": "H09", "name": "短寸偏分", "gender": "m", "age": (16, 70), "tone": "any",
     "detail": "短寸头，三七偏分，发际线清晰，鬓角修短",
     "forbid": "不画成长发或背头"},
    {"id": "H10", "name": "背头", "gender": "m", "age": (22, 70), "tone": "formal",
     "detail": "头发向后梳成背头，鬓角短，发丝有梳理痕迹",
     "forbid": "不画成刘海遮额"},
    {"id": "H11", "name": "中长碎发", "gender": "m", "age": (14, 45), "tone": "casual",
     "detail": "中长发，额前碎发自然垂落遮住一半眉毛，发尾过耳",
     "forbid": "不画成板寸或背头"},
    {"id": "H12", "name": "花白平头", "gender": "m", "age": (50, 90), "tone": "any",
     "detail": "花白平头，发际线后退，鬓角全白，头发稀薄贴头皮",
     "forbid": "不画成浓密黑发"},
    {"id": "H13", "name": "短卷贴头", "gender": "m", "age": (20, 55), "tone": "any",
     "detail": "短发带紧卷，贴着头皮，两侧修短，发顶略高",
     "forbid": "不画成直发或背头"},
]

# 色相槽：按阵营分配，同阵营用明度分层（家族相似但不同人）。
# 这是全剧 palette 统一的唯一机制，**不要删**。
PALETTE = [
    {"id": "P01", "name": "朱砂", "h": 8, "s": 0.42, "l": 0.34},
    {"id": "P02", "name": "姜黄", "h": 42, "s": 0.30, "l": 0.42},
    {"id": "P03", "name": "苔绿", "h": 92, "s": 0.24, "l": 0.30},
    {"id": "P04", "name": "松柏墨绿", "h": 148, "s": 0.28, "l": 0.26},
    {"id": "P05", "name": "松石青", "h": 186, "s": 0.30, "l": 0.30},
    {"id": "P06", "name": "靛青", "h": 222, "s": 0.32, "l": 0.28},
    {"id": "P07", "name": "紫檀", "h": 286, "s": 0.26, "l": 0.28},
    {"id": "P08", "name": "绛紫", "h": 330, "s": 0.24, "l": 0.32},
    {"id": "P09", "name": "烟灰", "h": 210, "s": 0.06, "l": 0.38},
    {"id": "P10", "name": "石膏白", "h": 40, "s": 0.05, "l": 0.72},
    {"id": "P11", "name": "墨黑", "h": 220, "s": 0.08, "l": 0.16},
]
NEUTRAL_S = 0.15        # 低于此饱和度视为中性色：不参与色相判定

# 识别锚：可选。24 条精简到 14 条 —— 旧表里「疤/痕/斑」占了 4 条，
# 且 A02/A03 排最前，几乎每部剧都抽到同一道印记（P4 的现场症状）。
ANCHOR = [
    {"id": "A01", "name": "泪痣", "text": "左眼角下方一颗扁平泪痣（直径约 2mm）", "kind": "痣"},
    {"id": "A02", "name": "眉尾旧疤", "text": "右眉尾一道浅白旧疤（约 1.5cm，断开眉毛）", "kind": "疤"},
    {"id": "A03", "name": "虎口烫痕", "text": "左手虎口一处烫伤旧痕（皮肤发亮、无毛）", "kind": "痕"},
    {"id": "A04", "name": "素银印章戒", "text": "左手中指一枚素银印章戒（戒面磨平）", "kind": "饰"},
    {"id": "A05", "name": "细圆框眼镜", "text": "一副细金属圆框眼镜（镜片有细微划痕）", "kind": "眼镜"},
    {"id": "A06", "name": "单只旧金耳夹", "text": "右耳单只旧金耳夹（另一只耳垂无饰）", "kind": "饰"},
    {"id": "A07", "name": "颈侧细疤", "text": "左侧颈侧一道淡色细疤（约 3cm）", "kind": "疤"},
    {"id": "A08", "name": "磨损编织绳", "text": "右手腕一圈磨白的编织绳（起毛、无金属扣）", "kind": "饰"},
    {"id": "A09", "name": "旧机械表", "text": "左手腕一只表盘泛黄的旧机械表（皮表带开裂）", "kind": "饰"},
    {"id": "A10", "name": "唇下浅凹", "text": "下唇下方一处浅酒窝状凹陷（只在说话时可见）", "kind": "轮廓"},
    {"id": "A11", "name": "额角发旋", "text": "右侧额角一处逆生发旋，头发在此处翘起", "kind": "发"},
    {"id": "A12", "name": "眉骨旧伤", "text": "左眉骨上方一道细疤（眉毛在此断开约 4mm）", "kind": "疤"},
    {"id": "A13", "name": "手背烫疤", "text": "右手手背一枚硬币大小的旧烫疤（皮肤发亮）", "kind": "疤"},
    {"id": "A14", "name": "素圈脚链", "text": "右脚踝一圈素银脚链（长期佩戴、压出浅印）", "kind": "饰"},
]
# 同类锚在一部剧里的配额：防「全员一身疤」
KIND_QUOTA = {"疤": 1, "痕": 1, "斑": 1, "痣": 2, "饰": 2, "纹": 1}

SKIN = [
    (0, 22, "皮肤有细密绒毛与轻微肤色不均，鼻翼两侧泛淡红，无妆感"),
    (23, 32, "眼下有淡青，鼻唇沟初现，颧骨处有极淡晒斑，皮肤有真实毛孔"),
    (33, 45, "法令纹与颈纹清晰可见，眼尾有细纹，手背有浅纹与淡斑"),
    (46, 60, "皮肤松弛下垂、颈纹深，眼袋明显，手背青筋与色斑清晰"),
    (61, 200, "皱纹密集、皮肤薄透失去弹性，老年斑与手背凸起的青筋明显"),
]

# 服装：按「性别 × 正式度」给骨架，色名由色签名填。
# 旧版从 FABRIC（14 种织物）轮转 + 阶层改写，产出一段 400 字的服装说明书；
# 现在只要一句能出图的话：上装 + 下装 + 鞋 + 一处配饰。
GARMENT_TMPL = {
    ("f", True): ("{color_cn}色精纺衬衫配同色系半身裙，外罩同色薄西装；脚穿低跟皮鞋；"
                  "{accent}",
                  "{color_en} fine-weave shirt and matching skirt under a light blazer; "
                  "low-heeled leather shoes; {accent_en}"),
    ("f", False): ("{color_cn}色系纯棉上衣配直筒裤；脚穿平底鞋；{accent}",
                   "{color_en} cotton top with straight-leg trousers; flat shoes; {accent_en}"),
    ("m", True): ("{color_cn}色系单排扣西装外套配同色西裤，内搭浅色衬衫；脚穿系带皮鞋；"
                  "{accent}",
                  "{color_en} single-breasted suit jacket with matching trousers over a light shirt; "
                  "lace-up leather shoes; {accent_en}"),
    ("m", False): ("{color_cn}色系工装外套配深色长裤；脚穿旧运动鞋；{accent}",
                   "{color_en} work jacket with dark trousers; worn sneakers; {accent_en}"),
}
ACCENT_CN = ("领口一处同色系深一档的滚边", "腰间一条细皮带", "无额外配饰，保持干净",
             "内搭比外套浅一档", "袖口卷起露出小臂", "颈间一条细链")
ACCENT_EN = ("a collar trim one shade deeper than the garment", "a thin leather belt",
             "no extra accessories, kept clean", "a top one shade lighter than the jacket",
             "sleeves rolled up to the forearm", "a thin chain at the neck")
COLOR_EN = {"朱砂": "vermilion", "姜黄": "ochre", "苔绿": "moss green", "松柏墨绿": "pine green",
            "松石青": "turquoise", "靛青": "indigo", "紫檀": "rosewood", "绛紫": "plum",
            "烟灰": "smoke grey", "石膏白": "plaster white", "墨黑": "ink black", "驼棕": "camel"}

BANNED_WORDS = ("俊美", "俊朗", "绝美", "惊艳", "倾国倾城", "气质出众", "面容精致", "白皙无瑕",
                "宛如天神", "绝世", "完美无瑕", "天使面孔", "祸水", "倾世")


# ===========================================================================
# 二、小工具
# ===========================================================================
def _h(s: str) -> int:
    """稳定哈希。取 sha256 前 16 位，**不做取模** —— 取模由调用方做。"""
    return int(hashlib.sha256(str(s).encode("utf-8")).hexdigest()[:16], 16)


def _rgb(h: float, s: float, l: float) -> str:
    import colorsys
    r, g, b = colorsys.hls_to_rgb(h / 360.0, l, s)
    return "#%02X%02X%02X" % (round(r * 255), round(g * 255), round(b * 255))


def _hue_gap(a: float, b: float) -> float:
    d = abs((a or 0) - (b or 0)) % 360
    return min(d, 360 - d)


def _write(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8", newline="")


def _skin(age: int) -> str:
    for lo, hi, text in SKIN:
        if lo <= age <= hi:
            return text
    return SKIN[-1][2]


def _gender_cn(g: str) -> str:
    return {"f": "女", "m": "男", "female": "女", "male": "男"}.get(str(g).lower(), "女")


def _hue_slots(n: int) -> list:
    """给 n 个阵营分配色相槽：**按色相环排序后等间距取**。

    旧实现按下标跳（`usable[i*step]`），而 PALETTE 是按「写表顺序」排的，
    结果 3 个阵营拿到 0/3/6 号 = 朱砂 8° / 墨绿 148° / 紫檀 286°，
    间隔 140/138/82 —— 视觉上是「红、绿、紫」，最刺眼的那一对只隔 82°。
    按 h 排序再等分，3 个阵营得到 8° / 148° / 222°，最短弧 74° 仍可辨，
    但两两都进得了「同框不打架」的区间。
    """
    usable = sorted([p for p in PALETTE if p["s"] >= NEUTRAL_S], key=lambda p: p["h"])
    if n <= 0:
        return []
    if n >= len(usable):
        return usable[:n]
    step = len(usable) / float(n)
    return [usable[int(i * step) % len(usable)] for i in range(n)]


def _is_formal(ch: dict) -> bool:
    """正式度只看名册显式字段或身份关键词。**不再从人群桶推断**。"""
    v = str((ch.get("overrides") or {}).get("formal") or ch.get("formal") or "").strip().lower()
    if v in ("1", "true", "yes", "formal"):
        return True
    if v in ("0", "false", "no", "casual"):
        return False
    ident = str(ch.get("identity") or "")
    return any(k in ident for k in ("总裁", "董事", "律师", "医生", "院长", "高管", "经理",
                                    "法务", "总监", "合伙人", "法官", "教授", "主管",
                                    "会计", "审计", "警", "军", "护士长"))


def _pick_hair(ch: dict, age: int, gender: str, used: set) -> dict:
    ov = (ch.get("overrides") or {}).get("hair")
    if ov:
        hit = next((h for h in HAIR if h["name"] == ov or h["id"] == ov), None)
        if hit:
            return hit
        # 名册写了个不在表里的发型：尊重它，但补一条 detail 供提示词使用
        return {"id": "HX-" + str(ov), "name": str(ov), "detail": str(ov),
                "forbid": "", "gender": gender, "tone": "any"}
    pool = [h for h in HAIR if h["gender"] == gender and h["age"][0] <= age <= h["age"][1]]
    pool = pool or [h for h in HAIR if h["gender"] == gender] or HAIR
    free = [h for h in pool if h["id"] not in used] or pool
    # 无偏排序：按 hash(seed+id) 排，避免「小余数反复命中靠前条目」
    return sorted(free, key=lambda h: _h("hair" + h["id"]))[0]


def _pick_anchor(ch: dict, age: int, seed: str, used: set, used_kind: dict) -> dict:
    ov = (ch.get("overrides") or {}).get("anchor")
    if str(ov or "").strip().lower() in ("none", "无", "不设", "-"):
        return {"id": "", "name": "无", "text": "", "kind": ""}
    if ov:
        hit = next((a for a in ANCHOR if a["name"] == ov or a["id"] == ov), None)
        if hit:
            return hit
        return {"id": "AX-" + str(ov), "name": str(ov), "text": str(ov), "kind": "饰"}
    free = [a for a in ANCHOR if a["id"] not in used]
    quota = [a for a in free if used_kind.get(a["kind"], 0) < KIND_QUOTA.get(a["kind"], 99)]
    free = quota or free
    if not free:
        return {"id": "", "name": "无", "text": "", "kind": ""}
    return sorted(free, key=lambda a: _h(seed + "anchor" + a["id"]))[0]


# ===========================================================================
# 三、设计：名册 → 角色圣经（三项签名）
# ===========================================================================
def design(roster: dict) -> dict:
    """名册 → 角色圣经。确定性：同输入同输出。"""
    chars = list(roster.get("characters") or [])
    if not chars:
        raise SystemExit("[FAIL] 名册里没有 characters（至少给一个角色）")

    # seed：显式给就用；没给按 world + 角色名派生 —— 两个项目自然不同，
    # 不会出现「不同剧、不同人物，抽到的锚却是同一套」。
    seed = str(roster.get("seed") or "").strip()
    if not seed:
        _fp = hashlib.sha1("|".join([str(roster.get("world") or ""),
                                     ",".join(str(c.get("name") or "") for c in chars)]
                                    ).encode("utf-8")).hexdigest()[:12]
        seed = "auto-" + _fp

    region_key = roster.get("region") or "east_asian"
    if region_key not in REGION:
        raise SystemExit("[FAIL] 未知 region：%s（可选 %s）" % (region_key, "/".join(REGION)))
    region = REGION[region_key]

    used_hair, used_anchor, used_kind = set(), set(), {}
    designs = []
    # 主演先选：让主角拿到最贴合的候选，配角随后避让
    tier_rank = {"lead": 0, "support": 1, "minor": 2}
    ordered = sorted(chars, key=lambda c: (tier_rank.get(c.get("tier") or "support", 1),
                                           _h(seed + str(c.get("name")))))
    for ch in ordered:
        ov = ch.get("overrides") or {}
        age = int(ch.get("age") or 30)
        gender = str(ch.get("gender") or "f").lower()
        gender = "m" if gender in ("m", "male", "男") else "f"
        hair = _pick_hair(ch, age, gender, used_hair)
        used_hair.add(hair["id"])
        anchor = _pick_anchor(ch, age, seed, used_anchor, used_kind)
        if anchor["id"]:
            used_anchor.add(anchor["id"])
            used_kind[anchor["kind"]] = used_kind.get(anchor["kind"], 0) + 1
        designs.append({
            "code": str(ch.get("code") or "").upper(),
            "name": ch["name"],
            "tier": ch.get("tier") or "support",
            "gender": gender,
            "age": age,
            "identity": ch.get("identity") or "",
            "faction": ch.get("faction") or "主线",
            "hair": {"id": hair["id"], "name": hair["name"],
                     "detail": hair.get("detail") or "", "forbid": hair.get("forbid") or ""},
            "anchor": anchor,
            "skin": _skin(age),
            "expression": str(ov.get("expression") or "").strip()
                          or "情绪克制，不外放到表情上",
            "formal": _is_formal(ch),
            "wealth": str(ov.get("wealth") or ch.get("wealth") or ""),
            "region": region_key, "region_cn": region["cn"],
            "region_line": region["line"], "region_forbid": region["forbid"],
            "overrides": ov,
        })

    # ---- 色签名：按阵营分色相槽，同阵营用明度分层（家族相似但不同人） ----
    factions = []
    for d in designs:
        if d["faction"] not in factions:
            factions.append(d["faction"])
    slots = _hue_slots(len(factions))
    variant_l = (0.0, 0.16, -0.10, 0.26, -0.18)
    for d in designs:
        base = slots[factions.index(d["faction"])]
        members = [x for x in designs if x["faction"] == d["faction"]]
        idx = members.index(d)
        l = max(0.16, min(0.80, base["l"] + variant_l[idx % len(variant_l)]))
        place = ACCENT_CN[_h(seed + d["name"] + "acc") % len(ACCENT_CN)]
        d["color"] = {
            "id": base["id"], "name": base["name"], "hue": base["h"], "s": base["s"],
            "hex": _rgb(base["h"], base["s"], l), "l": round(l, 2),
            "accent_hex": _rgb((base["h"] + 150) % 360, 0.42, 0.38),
            "accent_place": place,
            "accent_place_en": ACCENT_EN[ACCENT_CN.index(place)],
        }

    # ---- 服装（中/英） ----
    for d in designs:
        tpl = GARMENT_TMPL[(d["gender"], bool(d["formal"]))]
        color_cn = d["color"]["name"]
        color_en = COLOR_EN.get(color_cn, color_cn)
        d["garment"] = tpl[0].format(color_cn=color_cn, accent=d["color"]["accent_place"])
        d["garment_en"] = tpl[1].format(color_en=color_en,
                                        accent_en=d["color"]["accent_place_en"])
        d["color_line"] = "%s（%s，H%d/%d%%，#%s）" % (
            color_cn, "中性色" if d["color"]["s"] < NEUTRAL_S else "主色",
            d["color"]["hue"], round(d["color"]["s"] * 100), d["color"]["hex"].lstrip("#"))

    # ---- 差异对照（只与「最可能撞车」的那位比：同阵营 + 同性别） ----
    for d in designs:
        rivals = [x for x in designs if x is not d and x["faction"] == d["faction"]]
        rivals = rivals or [x for x in designs if x is not d]
        if rivals:
            near = min(rivals, key=lambda x: (_hue_gap(d["color"]["hue"], x["color"]["hue"]),
                                              _h(d["name"] + x["name"])))
            d["contrast"] = ("同剧 %s（%s）主色 %s 明度 %.2f、发型 %s；"
                             "本角色主色 %s 明度 %.2f、发型 %s。"
                             "两人同框时发型轮廓与主色明度必须一眼可分。"
                             % (near["name"], near["identity"] or near["tier"],
                                near["color"]["name"], near["color"]["l"], near["hair"]["name"],
                                d["color"]["name"], d["color"]["l"], d["hair"]["name"]))
        else:
            d["contrast"] = "本剧仅此一名主要角色：以唯一识别锚与色签名作为全场辨识依据。"

    # 输出顺序回到名册顺序
    order = {str(ch.get("name")): i for i, ch in enumerate(chars)}
    designs.sort(key=lambda d: order.get(d["name"], 999))

    bible = {
        "_note": "角色造型真源（由 character_design.py v%s 生成，勿手改）。"
                 "三项签名：身份 / 造型（色+服装+发型）/ 可选锚。" % LIB_VERSION,
        "lib_version": LIB_VERSION,
        "seed": seed,
        "region": region_key,
        "world": roster.get("world") or "当代中国都市题材",
        "style_lock": roster.get("style_lock") or "",
        "style_anchor": roster.get("style_anchor") or "",
        "characters": [_public(d) for d in designs],
    }
    bible["_matrix"] = matrix(bible)
    return bible


def _public(d: dict) -> dict:
    """导出到 bible 的字段（不带内部临时键）。"""
    keep = ("code", "name", "tier", "gender", "age", "identity", "faction",
            "hair", "anchor", "skin", "expression", "color", "color_line",
            "garment", "garment_en", "contrast", "formal", "wealth",
            "region", "region_cn", "region_line", "region_forbid")
    return {k: d[k] for k in keep if k in d}


# ===========================================================================
# 四、资产卡字段与提示词
# ===========================================================================
def _end(text: str) -> str:
    """保证一段描述以且仅以一个句号收尾。"""
    return (text or "").rstrip("。；; ") + "。"


def to_fields(c: dict, style_anchor: str = "") -> dict:
    """三项签名 → 资产卡字段（形象定位 / 服装细节 / 识别锚 / 差异对照 / 反默认）。"""
    anchor = c.get("anchor") or {}
    return {
        "风格": style_anchor,
        "形象定位": ("%d 岁%s%s；主色 %s；发型 %s。"
                     % (c["age"], _gender_cn(c["gender"]),
                        ("，" + c["identity"]) if c.get("identity") else "",
                        c["color"]["name"], c["hair"]["name"])),
        "发型": _end(c["hair"].get("detail") or c["hair"]["name"]),
        "皮肤质感": _end(c["skin"]),
        "表情": _end(c.get("expression") or ""),
        "服装细节": c["garment"],
        "服装细节EN": c.get("garment_en") or "",
        # 锚可选：空锚不生成句子，提示词里整段省略
        "识别锚": ("%s。" % anchor["text"]) if (anchor.get("text") or "").strip() else "",
        "差异对照": c.get("contrast") or "",
        "反默认": ("排除标准网红脸（削尖下颌＋放大眼裂＋垫高鼻梁＋无毛孔磨皮）、韩式平眉、"
                   "烤瓷牙反光、左右绝对对称的脸；%s。" % c["region_forbid"]),
    }


def _item(c: dict, fields: dict) -> dict:
    return {"kind": "char", "id": "CH%02d" % (c.get("section") or 1), "title": c["name"],
            "fields": fields, "raw": ""}


def board_prompt(c: dict, fields: dict, world: str = "", style_anchor: str = "") -> str:
    """横版设定板（走共享模板 build_char，保证版式口径唯一）。"""
    design = {"anchor": fields["识别锚"], "contrast": fields["差异对照"],
              "palette": "%s；%s。" % (c["color_line"], c["garment"]),
              "exclude": fields["反默认"], "world": world}
    return build_char(_item(c, fields), design=design)


def maincard_prompt(c: dict, fields: dict, world: str = "", style_style: str = "") -> str:
    """正面 3/4 全身主卡：单视角、干净背景、无排版。"""
    f = fields
    return "\n".join(x for x in [
        "一张**竖版角色主卡**（单视角角色定妆图），%s，电影级写实渲染，实拍级质感；"
        "画面里**只有这一个角色**，全身入画、从头顶到鞋底完整。" % (world or "当代中国都市题材"),
        ("【唯一识别锚｜先读这一条】%s" % f["识别锚"]) if f["识别锚"] else "",
        "【形象】%s" % f["形象定位"],
        "【发型】%s" % f["发型"],
        "【皮肤与质感】%s" % f["皮肤质感"],
        "【表情】%s" % f["表情"],
        "【服装与配饰】%s" % f["服装细节"],
        "【WARDROBE - 英文段，按此执行】%s" % (c.get("garment_en") or f.get("服装细节EN") or ""),
        "【差异化】%s" % f["差异对照"],
        "【镜头与站位】3/4 侧身面向镜头、正面偏向画面左侧约 30°；85mm 焦段、平视略低机位；"
        "全身入画、正常人体比例；大面积纯色干净底、无道具、无环境；柔光主光 + 极弱轮廓光。",
        "【禁止项】画面里不出现第二个人、不出现文字与编号、不出现边框与排版、不出现道具与场景；"
        "%s" % f["反默认"],
    ] if x)


def headshot_prompt(c: dict, fields: dict, world: str = "", style_anchor: str = "") -> str:
    """半身胸像（选角/定妆用）：只验脸，不带排版。"""
    f = fields
    return "\n".join(x for x in [
        "一张**半身胸像**定妆照，%s，电影级写实渲染，实拍级质感；单一角色、胸线以上取景。"
        % (world or "当代中国都市题材"),
        ("【唯一识别锚】%s" % f["识别锚"]) if f["识别锚"] else "",
        "【发型】%s" % f["发型"],
        "【皮肤与质感】%s" % f["皮肤质感"],
        "【表情】%s" % f["表情"],
        "【服装领口】%s" % f["服装细节"],
        "【WARDROBE - 英文段，按此执行】%s" % (c.get("garment_en") or f.get("服装细节EN") or ""),
        "【镜头】正面偏 3/4、85mm、平视；中灰色干净背景、柔光打面；重点刻画皮肤纹理与真实毛孔。",
        "【禁止项】不出现第二个人、不出现文字、不出现排版与色卡；%s" % f["反默认"],
    ] if x)


# ===========================================================================
# 四点五、真人写实轨（live_action）专用版式
# ===========================================================================
LIVE_PHOTO = ("photographic material truth, real skin texture with visible pores and fine facial hair, "
              "believable fabric wrinkles, credible lens perspective, natural depth of field")
LIVE_NEG = ("no second person, no text, no letters, no numbers, no watermark, no logo, no border, "
            "no layout grid, no props, no environment, no scenery, no CG render look, no 3D render, "
            "no illustration, no anime, no plastic skin, no airbrushed retouch, no poreless face, "
            "no perfectly symmetrical AI face, no Instagram filter, no glow, no lens flare")


def _live_style(style_anchor: str) -> str:
    """风格串：名册已写材质项就不重复拼，避免「photographic material truth」出现两次。"""
    base = (style_anchor or "surreal live-action film look").strip().rstrip("，,")
    extra = [x for x in LIVE_PHOTO.split(", ") if x.lower() not in base.lower()]
    return base + ("，" + "，".join(extra) if extra else "")


_ANCHOR_LOUD_KINDS = ("饰", "眼镜", "纹")


def _anchor_sentence(c: dict, text: str) -> str:
    """锚的可见度必须跟锚的类型匹配：疤/痕/痣要「按原样」，饰物/眼镜才「清晰可见」。

    旧版对所有锚都写「必须清晰可见」，模型于是把一道浅压痕画成显眼的疤。
    """
    if not text:
        return ""
    kind = (c.get("anchor") or {}).get("kind") or ""
    if kind in _ANCHOR_LOUD_KINDS:
        vis = "这个锚必须清晰可见、非对称；"
    else:
        vis = ("这个锚要按它本身的尺寸与淡度如实呈现：不要加深、不要扩大、不要加高光、"
               "不要画成伤疤或妆效，自然光下能辨认即可；")
    return "【唯一识别锚 · 先读这一条】%s %s全剧只此一处锚，不要再加第二个。" % (text, vis)


def live_card_prompt(c: dict, fields: dict, world: str = "", style_anchor: str = "") -> str:
    """真人写实轨角色卡：16:9 纯白、左脸特写 + 右三视图半身。

    为什么不能复用 maincard_prompt：那是竖版全身主卡，与真人轨要求相反。
    """
    f = fields
    gender_cn = "女性" if c.get("gender") == "f" else "男性"
    return "\n".join(x for x in [
        "【风格】%s，16:9 horizontal frame" % _live_style(style_anchor),
        "【任务】一张**横版 16:9 角色定妆参考卡**，纯白无缝背景上只有这一个人，用于全剧跨镜身份一致性。",
        _anchor_sentence(c, f["识别锚"]),
        "【版式】左半边：正侧 3/4 面部特写，眼睛看向镜头；右半边：同一个人半身三视图——正面、侧面、背面——"
        "等距排列，服装、光位、色温完全一致；画面内不出现分隔线、不出现标签、不出现文字。",
        "【人物】%s，%d 岁%s，%s。" % (c["name"], c.get("age") or 30, gender_cn, c.get("identity") or ""),
        "【发型】%s" % f["发型"],
        "【皮肤与质感】%s；保留真实毛孔、细发丝与不对称的左右脸。" % c["skin"].rstrip("。"),
        "【服装与主色】%s（主色 %s）。" % (c.get("garment_en") or c.get("garment") or "",
                                          c["color"]["name"]),
        "【表情】%s" % (c.get("expression") or "情绪克制，不外放。").rstrip("。") + "。",
        "【脸型基准】真实寻常面孔，不是平面化的美人模板：下颌角明确、骨量偏小；"
        "眼裂宽度与脸型成比例、上睑有厚度；鼻梁高度自然、鼻背有轻微起伏与骨点；"
        "皮肤保留毛孔、细纹、不均匀反光与轻微色差；左右脸在眉高、颧宽、嘴角位置上存在可见差异。",
        "【族裔约束】%s。" % c["region_forbid"].rstrip("。"),
        "【差异对照】%s" % c["contrast"],
        "【负向】" + LIVE_NEG,
    ] if x)


def live_scene_prompt(s: dict, style_anchor: str = "") -> str:
    """真人写实轨场景卡：16:9 纯白、**绝对不含人物**（含剪影/倒影）。"""
    return "\n".join([
        "【风格】%s，16:9 horizontal frame, empty set" % _live_style(style_anchor),
        "【任务】一张**横版 16:9 场景参考卡**，用于全剧同一空间的跨镜一致性。",
        "【空间】%s。" % s.get("desc", ""),
        "【硬约束 · 绝对不含人物】画面里没有人物、没有人影、没有剪影、没有倒影里的人物、没有肢体局部。"
        "把这个空间当作在无人时被拍下的一张现场照片。",
        "【陈设细节】该空间被真实使用过的痕迹要可见：磨损、污渍、贴纸残留、被反复触碰的高光位置；"
        "但不要出现可读的文字、机构标识或品牌。",
        "【光线】%s，来源明确、方向可辨，允许一处不合理的入射角作为超现实标记。"
        % ("夜间人工光" if s.get("time") == "夜" else "白天自然光与室内灯混合"),
        "【构图】平视，轻微广角，画面深处保留一条通向画外的通道（门、走廊、楼梯）。",
        "【负向】" + LIVE_NEG,
    ])


def emit_live_scenes(bible: dict, out_dir: pathlib.Path, scenes_path: str) -> list:
    """按 world-bible 的 scenes 段落盘场景卡提示词（真人轨）。"""
    src = _load(scenes_path)
    scenes = (src.get("scenes") if isinstance(src, dict) else src) or []
    files = []
    for s in scenes:
        code = str(s.get("code") or "").upper()
        if not code:
            continue
        p = out_dir / "prompts" / "live" / ("SC_%s_card.txt" % code)
        _write(p, live_scene_prompt(s, bible.get("style_anchor") or ""))
        files.append(str(p))
    return files


# ===========================================================================
# 五、差异矩阵与规则（4 条）
# ===========================================================================
def matrix(bible: dict) -> dict:
    """两两对照矩阵（只算还真有意义的三项：色相 / 发型 / 锚）。"""
    chars = bible["characters"]
    pairs = []
    for i in range(len(chars)):
        for j in range(i + 1, len(chars)):
            a, b = chars[i], chars[j]
            pairs.append({
                "a": a["name"], "b": b["name"],
                "hue_gap": round(_hue_gap(a["color"]["hue"], b["color"]["hue"]), 1),
                "same_faction": a["faction"] == b["faction"],
                "same_hair": (a.get("hair") or {}).get("id") == (b.get("hair") or {}).get("id"),
                "same_anchor": bool((a.get("anchor") or {}).get("id"))
                and (a.get("anchor") or {}).get("id") == (b.get("anchor") or {}).get("id"),
                "light_gap": round(abs(a["color"]["l"] - b["color"]["l"]), 2),
            })
    return {"pairs": pairs}


def check_rules(bible: dict) -> list:
    """四条规则 → [(level, code, msg)]。level ∈ hard/warn。"""
    chars = bible["characters"]
    out = []
    pairs = (bible.get("_matrix") or matrix(bible))["pairs"]
    leads = [c["name"] for c in chars if c.get("tier") == "lead"]

    # R1 不同阵营色相间隔 ≥ 30°
    for p in pairs:
        if p["same_faction"]:
            continue
        if p["hue_gap"] < 30:
            out.append(("hard", "R1", "%s ↔ %s 阵营不同但色相仅隔 %.0f° < 30°（%s / %s）"
                        % (p["a"], p["b"], p["hue_gap"], "见名册 faction", "色签名会撞")))
    # R2 识别锚全局唯一
    for p in pairs:
        if p["same_anchor"]:
            out.append(("hard", "R2", "%s 与 %s 共用同一识别锚（全剧只能出现一次）" % (p["a"], p["b"])))
    # R3 主演发型不重复
    for p in pairs:
        if p["same_hair"] and (p["a"] in leads or p["b"] in leads):
            out.append(("warn", "R3", "%s 与 %s 发型相同且含主演（%s）"
                        % (p["a"], p["b"], p["a"] if p["a"] in leads else p["b"])))
    # R4 文案不得含评价性美颜词
    for c in chars:
        blob = " ".join(str(c.get(k) or "") for k in ("garment", "expression", "identity", "contrast"))
        hit = [w for w in BANNED_WORDS if w in blob]
        if hit:
            out.append(("hard", "R4", "%s 的文案含评价性美颜词：%s" % (c["name"], "、".join(hit))))
    return out


def _ok_note(bible: dict) -> str:
    chars = bible["characters"]
    anchors = [c["name"] for c in chars if (c.get("anchor") or {}).get("id")]
    hues = sorted({(c["color"]["name"], c["color"]["hue"]) for c in chars},
                  key=lambda x: x[1])
    return ("%d 个角色；%d 人有识别锚；%d 个色相槽（%s）"
            % (len(chars), len(anchors), len(hues),
               "、".join(n for n, _ in hues)))


def render_matrix_md(bible: dict, issues: list) -> str:
    L = ["# 角色造型矩阵", "",
         "> seed=`%s`；%s。由 `character_design.py` 生成，**勿手改**。"
         % (bible["seed"], _ok_note(bible)), "",
         "## 逐角色签名", "",
         "| 代号 | 姓名 | 身份 | 主色 | 发型 | 识别锚 |",
         "|---|---|---|---|---|---|"]
    for c in bible["characters"]:
        a = (c.get("anchor") or {}).get("name") or "**无**"
        L.append("| %s | %s | %s | %s | %s | %s |"
                 % (c.get("code") or "-", c["name"], c["identity"] or c["tier"],
                    c["color_line"], c["hair"]["name"], a))
    L += ["", "## 两两对照（只列真正可能撞车的项）", "",
          "| A | B | 色相间隔 | 同阵营 | 同发型 | 同锚 |", "|---|---|---|---|---|---|"]
    for p in (bible.get("_matrix") or matrix(bible))["pairs"]:
        L.append("| %s | %s | %.0f° | %s | %s | %s |"
                 % (p["a"], p["b"], p["hue_gap"],
                    "是" if p["same_faction"] else "否",
                    "**是**" if p["same_hair"] else "否",
                    "**是**" if p["same_anchor"] else "否"))
    L += ["", "## 规则判定（R1 色相 / R2 锚唯一 / R3 主演发型 / R4 美颜词）", ""]
    if issues:
        for lv, code, msg in issues:
            L.append("- `%s` %s %s" % (code, "硬" if lv == "hard" else "警", msg))
    else:
        L.append("- 四条规则全部通过")
    L.append("")
    return "\n".join(L)


def render_asset_md(bible: dict, prompts: dict) -> str:
    """`# 一、角色资产库` 格式，可直接被 asset_md.py 解析。"""
    L = ["# 一、角色资产库", "",
         "> 由 `character_design.py` 生成（seed=`%s`）；每节 ``` 内为**设定板**提示词。" % bible["seed"], ""]
    for i, c in enumerate(bible["characters"], 1):
        L += ["## %d. %s（%s）" % (i, c["name"], c["identity"] or c["tier"]), "",
              "**基础造型**", "```", prompts[c["name"]]["board"], "```", ""]
    return "\n".join(L)


def emit(bible: dict, out_dir: pathlib.Path, variants=("board", "maincard", "headshot"),
         card_style: str = "3d_manhua", scenes_path: str = "") -> dict:
    """落盘：bible / 矩阵 md / 资产提示词 md / 逐角色提示词。

    - card_style="live_action"：只出 `prompts/live/<代号>_<名>_card.txt`（一人一卡）
    - 其它取值：board / maincard / headshot 三件套
    """
    world = bible["world"]
    style_anchor = bible["style_anchor"]
    live = str(card_style or "").startswith("live")
    prompts, files = {}, []
    for i, c in enumerate(bible["characters"], 1):
        fields = to_fields(c, style_anchor)
        if live:
            prompts[c["name"]] = {"board": live_card_prompt(c, fields, world, style_anchor),
                                  "_fields": fields}
        else:
            prompts[c["name"]] = {
                "board": board_prompt(c, fields, world, style_anchor),
                "maincard": maincard_prompt(c, fields, world),
                "headshot": headshot_prompt(c, fields, world),
                "_fields": fields,
            }
    issues = check_rules(bible)

    _write(out_dir / "character-bible.json", json.dumps(bible, ensure_ascii=False, indent=2))
    _write(out_dir / "角色差异化矩阵.md", render_matrix_md(bible, issues))
    _write(out_dir / "资产提示词_角色段.md", render_asset_md(bible, prompts))
    files += ["character-bible.json", "角色差异化矩阵.md", "资产提示词_角色段.md"]

    if live:
        for i, c in enumerate(bible["characters"], 1):
            code = c.get("code") or "CH%02d" % i
            p = out_dir / "prompts" / "live" / ("%s_%s_card.txt" % (code, c["name"].replace(" ", "-")))
            _write(p, prompts[c["name"]]["board"])
            files.append(str(p.relative_to(out_dir)))
        if scenes_path:
            files += [str(pathlib.Path(x).relative_to(out_dir)) if str(x).startswith(str(out_dir)) else x
                      for x in emit_live_scenes(bible, out_dir, scenes_path)]
    else:
        for i, c in enumerate(bible["characters"], 1):
            for v in variants:
                p = out_dir / "prompts" / "char" / ("CH%02d_%s_%s.txt" % (i, c["name"], v))
                _write(p, prompts[c["name"]][v])
                files.append(str(p.relative_to(out_dir)))
    return {"files": files, "issues": issues,
            "fields": {k: v["_fields"] for k, v in prompts.items()}}


# ===========================================================================
# 六、老项目体检（audit）：扫既有资产提示词 md
# ===========================================================================
AUDIT_LEX = {
    "脸型": {"短圆": ("圆脸", "娃娃脸", "短圆"), "方颌": ("方脸", "国字脸", "方颌"),
             "长椭圆": ("长脸", "鹅蛋脸", "长椭圆"), "菱形": ("菱形脸", "高颧骨"),
             "心形尖颌": ("瓜子脸", "心形脸", "锥子脸"), "宽扁": ("宽脸", "扁脸", "方圆脸"),
             "瘦削": ("瘦削", "凹陷", "清瘦脸")},
    "发型": {"马尾": ("马尾",), "盘发": ("盘发", "发髻", "盘髻"), "短发": ("短发", "齐耳", "寸头", "背头"),
             "长直": ("长直发", "直发"), "大波浪": ("波浪", "卷发"), "刘海": ("刘海",),
             "编发": ("辫", "编发")},
    "眉": {"剑眉": ("剑眉",), "柳叶眉": ("柳叶眉",), "平眉": ("平眉", "一字眉"), "浓眉": ("浓眉", "粗眉"),
           "细眉": ("细眉", "淡眉"), "上挑": ("上挑", "上斜")},
    "眼": {"杏眼": ("杏眼",), "丹凤眼": ("丹凤眼", "凤眼"), "圆眼": ("圆眼", "大眼"), "细长": ("细长", "狭长"),
           "单眼皮": ("单眼皮",), "双眼皮": ("双眼皮",), "下垂": ("下垂",)},
    "锚": {"泪痣": ("泪痣",), "疤": ("疤",), "痕": ("痕",), "胎记": ("胎记",), "痣": ("痣",),
           "眼镜": ("眼镜",), "耳饰": ("耳钉", "耳环", "耳夹"), "戒指": ("戒指",),
           "手表": ("手表",), "项链": ("项链", "锁骨链"), "纹身": ("纹身",)},
    "色": {"黑": ("黑色", "纯黑", "深黑"), "白": ("白色", "纯白", "米白"), "灰": ("灰",),
           "藏青": ("藏青", "深蓝"), "酒红": ("酒红", "暗红", "枣红"), "墨绿": ("墨绿", "橄榄"),
           "驼棕": ("驼色", "棕色", "卡其", "咖啡"), "红": ("红色", "正红", "朱红", "红油", "辣油")},
}

_SEC_RE = re.compile(r"^#{2,3}\s*(\d+)[a-z]?\s*[.、]\s*(.+?)\s*$", re.M)
_FENCE_RE = re.compile(r"```(.*?)```", re.S)


def _char_block(text: str) -> str:
    """切出「角色」章节：标题含「角色」且含「资产/提示词」，到下一个标题含「场景」为止。"""
    lines = text.split("\n")
    start = -1
    for i, ln in enumerate(lines):
        if ln.startswith("#") and "角色" in ln and ("资产" in ln or "提示词" in ln):
            start = i
            break
    if start < 0:
        return text
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("#") and "场景" in lines[j]:
            end = j
            break
    return "\n".join(lines[start:end])


def audit_md(md_path: pathlib.Path) -> dict:
    """扫「资产提示词 md」的角色段：抽签名 → 报撞脸 / 撞色 / 缺识别锚。"""
    text = md_path.read_text(encoding="utf-8")
    block = _char_block(text)
    if not _SEC_RE.search(block):
        raise SystemExit("[FAIL] 没解析到任何角色节（需 `## N. 名字` 或 `### N. 名字`）：%s" % md_path)
    rows, variants = [], 0
    for m in _SEC_RE.finditer(block):
        body_end = _SEC_RE.search(block, m.end())
        body = block[m.end(): body_end.start() if body_end else len(block)]
        title = m.group(2)
        if "变体" in title:
            variants += 1
            continue
        prompts = "\n".join(_FENCE_RE.findall(body)) or body
        name = re.split(r"[（(]", title)[0].strip()
        # 只留「描述角色的子句」：剔掉棚拍/背景/镜头这类全剧共用的技术句
        clauses = [c for c in re.split(r"[。；;，,\n]", body) if c.strip()]
        vis = [c for c in clauses
               if not any(k in c for k in ("背景", "镜头", "画质", "杰作", "超精细", "透视", "构图", "打光"))]
        cloth = [c for c in vis
                 if not any(k in c for k in ("头发", "发丝", "长发", "短发", "马尾", "盘", "刘海", "辫",
                                             "眉", "眼", "瞳", "睫毛"))]
        row = {"section": int(m.group(1)), "name": name, "hits": {}}
        for dim, lex in AUDIT_LEX.items():
            scope = "\n".join(cloth if dim == "色" else vis)
            row["hits"][dim] = [k for k, words in lex.items() if any(w in scope for w in words)]
        row["prompt_len"] = len(prompts)
        rows.append(row)
    conflicts = []
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            a, b = rows[i], rows[j]
            same = {}
            for dim in ("脸型", "眉", "眼", "发型", "色"):
                inter = set(a["hits"][dim]) & set(b["hits"][dim])
                if inter:
                    same[dim] = sorted(inter)
            if len(same) >= 3:
                conflicts.append({"a": a["name"], "b": b["name"], "same": same, "score": len(same)})
    no_anchor = [r["name"] for r in rows if not r["hits"]["锚"]]
    coverage = {d: [r["name"] for r in rows if not r["hits"][d]] for d in AUDIT_LEX}
    return {"source": str(md_path), "characters": rows, "conflicts": conflicts,
            "no_anchor": no_anchor, "variants": variants, "coverage": coverage}


def render_audit_md(rep: dict) -> str:
    L = ["# 角色同质化体检", "", "> 源：`%s`；共 %d 个角色。" % (rep["source"], len(rep["characters"])), "",
         "| # | 角色 | 脸型 | 发型 | 眉 | 眼 | 色 | 识别锚 | 提示词字数 |",
         "|---|---|---|---|---|---|---|---|---|"]
    for r in rep["characters"]:
        h = r["hits"]
        L.append("| %d | %s | %s | %s | %s | %s | %s | %s | %d |"
                 % (r["section"], r["name"], "/".join(h["脸型"]) or "—", "/".join(h["发型"]) or "—",
                    "/".join(h["眉"]) or "—", "/".join(h["眼"]) or "—", "/".join(h["色"]) or "—",
                    "/".join(h["锚"]) or "**无**", r["prompt_len"]))
    L += ["", "## 冲突对（同一部剧里 ≥3 个维度撞车）", ""]
    if rep["conflicts"]:
        for c in sorted(rep["conflicts"], key=lambda x: -x["score"]):
            L.append("- **%s ↔ %s**（%d 项重合）：%s"
                     % (c["a"], c["b"], c["score"],
                        "；".join("%s=%s" % (k, "/".join(v)) for k, v in c["same"].items())))
    else:
        L.append("- 无 3 项以上重合对（阈值：脸型/发型/眉/眼/色 五维）")
    L += ["", "## 维度覆盖率（缺 = 该维度交给模型自由发挥）", "",
          "| 维度 | 写出的人数 | 缺失人数 | 缺失者 |", "|---|---|---|---|"]
    for dim in AUDIT_LEX:
        miss = rep.get("coverage", {}).get(dim, [])
        L.append("| %s | %d / %d | %d | %s |"
                 % (dim, len(rep["characters"]) - len(miss), len(rep["characters"]),
                    len(miss), "、".join(miss) or "—"))
    if rep.get("variants"):
        L += ["", "> 另有 %d 个「变体」节未计入（同一角色的换装/受伤状态），不计入同质化统计。"
              % rep["variants"]]
    L += ["", "## 缺识别锚（模型无从分辨这些角色）", ""]
    L.append("- " + ("、".join(rep["no_anchor"]) if rep["no_anchor"] else "无（每个角色都有可指认标记）"))
    L += ["", "> 说明：本体检是**词表启发式**，只认显式写出的特征词；写得越含糊（「气质清冷」"
              "「面容精致」）命中率越低——命中率低本身就是同质化的信号。", ""]
    return "\n".join(L)


# ===========================================================================
# 七、CLI
# ===========================================================================
def _load(p: str) -> dict:
    path = pathlib.Path(p)
    if not path.is_file():
        raise SystemExit("[FAIL] 文件不存在：%s" % path)
    return json.loads(path.read_text(encoding="utf-8"))


def _template() -> dict:
    return {
        "_note": "角色名册模板：只需给身份与性格；色签名/发型/锚由 character_design.py 分配。"
                 "确有必要时用 overrides 指定（hair / anchor / expression / formal / wealth）。"
                 "不写 anchor 就是自动分配；写 \"anchor\": \"none\" 表示这人不设锚。",
        "world": "当代韩国首尔·财阀高中",
        "region": "east_asian",
        "style_lock": "3d-manhua-cel",
        "style_anchor": "电影级写实 3D CG 渲染，实拍级质感，PBR 物理材质",
        "seed": "",
        "characters": [
            {"name": "楚湘", "gender": "f", "age": 18, "tier": "lead", "identity": "转校生",
             "faction": "外来者", "code": "CHU",
             "overrides": {"anchor": "磨损编织绳", "hair": "高蓬松马尾"}},
            {"name": "申雅莱", "gender": "f", "age": 18, "tier": "support", "identity": "财阀大小姐",
             "faction": "财阀", "code": "SHIN"},
            {"name": "具承贤", "gender": "m", "age": 19, "tier": "support", "identity": "财阀太子爷",
             "faction": "财阀", "code": "GU"},
            {"name": "教导主任", "gender": "m", "age": 52, "tier": "minor", "identity": "教导主任",
             "faction": "学校", "code": "DEAN", "overrides": {"anchor": "none"}},
        ],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="角色造型设计器（3 项签名；纯标准库、零网络）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("plan", help="名册 → 角色圣经 + 提示词 + 矩阵")
    p1.add_argument("--roster", required=True)
    p1.add_argument("--out", required=True, help="输出目录（建议 <项目>/04-资产/design）")
    p1.add_argument("--variants", default="board,maincard,headshot",
                    help="逐角色写出哪些提示词（逗号分隔）")
    p1.add_argument("--strict", action="store_true", help="硬规则不过也退出码 2")
    p1.add_argument("--card-style", default="auto",
                    choices=["auto", "3d_manhua", "2d_animation", "live_action"],
                    help="角色卡版式：auto=读名册 style_lock；live_action=16:9 纯白+左脸特写+右三视图")
    p1.add_argument("--scenes", default="",
                    help="（可选）world-bible.json 路径：同时产出真人轨场景卡提示词")

    p2 = sub.add_parser("check", help="校验角色圣经的四条规则（退出码 2 = 不过）")
    p2.add_argument("--bible", required=True)

    p3 = sub.add_parser("audit", help="体检既有「资产提示词 md」的同质化程度")
    p3.add_argument("--md", required=True)
    p3.add_argument("--out", default="", help="把体检报告写成 md（省略则只打印）")

    p4 = sub.add_parser("template", help="输出名册模板")
    p4.add_argument("--out", required=True)

    args = ap.parse_args(argv)

    if args.cmd == "template":
        _write(pathlib.Path(args.out), json.dumps(_template(), ensure_ascii=False, indent=2))
        print("[OK] 名册模板：%s" % args.out)
        return 0

    if args.cmd == "plan":
        roster = _load(args.roster)
        bible = design(roster)
        out = pathlib.Path(args.out)
        variants = tuple(v.strip() for v in args.variants.split(",") if v.strip())
        style = str(getattr(args, "card_style", "auto") or "auto").lower()
        if style == "auto":
            lock = str(roster.get("style_lock") or "").lower()
            style = "live_action" if lock.startswith("live") else (lock or "3d_manhua")
        bible["card_style"] = style
        res = emit(bible, out, variants, card_style=style, scenes_path=getattr(args, "scenes", "") or "")
        print("[OK] %d 个角色 → %s" % (len(bible["characters"]), out))
        for f in res["files"]:
            print("  · %s" % f)
        print()
        print(_ok_note(bible))
        hard = [x for x in res["issues"] if x[0] == "hard"]
        for lv, code, msg in res["issues"]:
            print("  [%s] %s %s" % ("HARD" if lv == "hard" else "warn", code, msg))
        if not res["issues"]:
            print("  四条规则全部通过")
        return 2 if (hard and args.strict) else 0

    if args.cmd == "check":
        bible = _load(args.bible)
        if "_matrix" not in bible:
            bible["_matrix"] = matrix(bible)
        issues = check_rules(bible)
        hard = [x for x in issues if x[0] == "hard"]
        for lv, code, msg in issues:
            print("[%s] %s %s" % ("HARD" if lv == "hard" else "warn", code, msg))
        if hard:
            print("\n[FAIL] %d 条硬规则未通过（退出码 2）" % len(hard))
            return 2
        print("[OK] 四条规则通过；%s" % _ok_note(bible))
        return 0

    if args.cmd == "audit":
        rep = audit_md(pathlib.Path(args.md))
        md = render_audit_md(rep)
        if args.out:
            _write(pathlib.Path(args.out), md)
            print("[OK] 体检报告：%s" % args.out)
        for r in rep["characters"]:
            print("  %2d. %-10s 脸型=%-8s 发型=%-6s 锚=%s"
                  % (r["section"], r["name"], "/".join(r["hits"]["脸型"]) or "—",
                     "/".join(r["hits"]["发型"]) or "—", "/".join(r["hits"]["锚"]) or "无"))
        print("\n冲突对 %d 组；缺识别锚 %d 人" % (len(rep["conflicts"]), len(rep["no_anchor"])))
        for c in sorted(rep["conflicts"], key=lambda x: -x["score"])[:8]:
            print("  · %s ↔ %s：%s" % (c["a"], c["b"],
                                       "；".join("%s=%s" % (k, "/".join(v)) for k, v in c["same"].items())))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
