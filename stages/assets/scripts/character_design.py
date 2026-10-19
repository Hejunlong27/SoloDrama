# -*- coding: utf-8 -*-
r"""character_design.py —— 角色差异化设计器（同一部剧里，谁都不该长得像谁）

## 要解决的到底是什么问题

短剧人物图「撞脸」不是模型不行，是**提示词把差异抹平了**。三个结构性成因：

1. **模板同构**：一张人物设定板从头到尾用同一句风格锚（写实 3D CG / 低明度高级灰 /
   柔光体积光 / 东方古典色撞色）。风格 token 完全一致时，模型对「脸」的自由度最高，
   于是回落到训练分布的均值脸。
2. **字段空泛**：资产卡写「气质清冷、身材修长、面容精致」，这些词在模型里对应的是
   同一批高频脸；写十个人等于写一个人。
3. **缺剧组级对比**：每张卡独立手写，没人检查两张卡是否撞脸、撞色、撞轮廓；
   主角与配角还常共用同一套语汇（「俊美」「冷峻」「精致」）。

## 做法：把「长相」拆成可分配、可校验的六维签名

| 维 | 考察什么 | 为什么它能防撞脸 |
|---|---|---|
| D1 骨相 | 脸型几何 / 中庭比例 / 下颌角 / 颧弓 / 眉骨 | 骨相是脸的骨架，换骨相 ≠ 换妆 |
| D2 发型轮廓 | 长度 × 体积 × 发际线 × 边缘 | 轮廓是 3 米外唯一能分辨的特征 |
| D3 眉眼结构 | 眉形 / 眉距 / 眼型 / 眼裂高度 / 眼距 | 眉眼决定「像谁」，且不随服装变化 |
| D4 色彩签名 | 主色相 + 明度/饱和度 + 一处撞色 | 统一高级灰 = 全剧一个 palette |
| D5 材质织物 | 织物种类 + 垂坠/反光行为 | 材质是「阶层与职业」的视觉证据 |
| D6 识别锚 | 一处非对称、可指认、跨镜不变的标记 | 模型画不出来「气质」，但画得出一颗痣 |

分配方式：**按人群桶定候选集 → 最大最小距离贪心**（每选一个角色，都取「离已选角色最远」
的候选），因此差异是**构造出来的**，不靠写作者的灵感。

## 六条剧组级硬规则（`check` 子命令逐条判定）

| # | 规则 | 判据 |
|---|---|---|
| R1 | 任意两角色面部距离 ≥ 0.50 | 七槽签名（脸型/中庭/下颌/眉/眼/鼻/唇）至少 4 槽不同 |
| R2 | 主角 vs 任一其他角色 ≥ 0.625 | 至少 5 槽不同 |
| R3 | 不同阵营色相间隔 ≥ 30° | 色相环最短弧 |
| R4 | 识别锚全局唯一 | 不得两人共用同一处标记 |
| R5 | 主演/配演发型不重复 | 群演可复用，但须给 warning |
| R6 | 生成文案不得含评价性美颜词 | 见 `BANNED_WORDS` |

## 三条使用姿势

```bash
# ① 新剧：给一份角色名册，直接产出可出图的三件套提示词
python stages/assets/scripts/character_design.py plan --roster roster.json --out 04-资产/design

# ② 门禁：剧本定稿后校验，硬规则不过退出码 2（可挂进 CI / 交付前自检）
python stages/assets/scripts/character_design.py check --bible 04-资产/design/character-bible.json

# ③ 老项目体检：扫既有「资产提示词 md」，报撞脸/撞色/无识别锚
python stages/assets/scripts/character_design.py audit --md 资产提示词.md

# 名册模板
python stages/assets/scripts/character_design.py template --out roster.json
```

## 产物

| 文件 | 用途 |
|---|---|
| `character-bible.json` | 机器真源（六维签名 + 差异矩阵数值），`check` 的输入 |
| `资产提示词_角色段.md` | **可直接喂** `gen_char_assets.py` / `asset_md.py`（`# 一、角色资产库` + `## N. 名字` + ``` 块） |
| `prompts/char/CHxx_名字_设定板.txt` | 横版设定板（本地 ComfyUI / RH 单段） |
| `prompts/char/CHxx_名字_主卡.txt` | 正面 3/4 全身主卡（3D 轨首帧锚点用） |
| `prompts/char/CHxx_名字_定妆照.txt` | 半身胸像（选角 / 定妆 / 只出脸时用） |
| `角色差异化矩阵.md` | 人读：逐角色签名 + 两两对照 + 规则判定 |

## 纪律（别删）

1. **纯标准库、零网络、零计费**：差异设计不该依赖任何 API。
2. **确定性**：同一份名册 + 同一 seed 必得同一份结果（哈希只用于稳定的次序打散），
   便于 diff、便于复核、便于进 git。
3. **不发明剧本没给的身份**：本模块只分配「视觉参数」，身份/年龄/阵营一律从名册读；
   名册缺失的字段留空，不脑补。
4. **识别锚必须非对称**：左右对称的标记（「对称双眼」这类写法）不构成识别锚。
5. **色签名不是滤镜**：主色落在**服装与配饰**上，环境仍按场景卡走；不允许为了差异化把
   角色刷成高饱和色块（短剧要卖的是人，不是调色盘）。
6. **写文件一律 LF**（`newline=""`），否则 Windows 默认 CRLF 会污染 `manifest.sha256`。
"""
from __future__ import annotations

import argparse
import colorsys
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


# ===========================================================================
# 一、词库（全部为「可画出来的几何与材质」，不写评价性美颜词）
# ===========================================================================
SLOTS = ("脸型", "中庭", "下颌", "眉", "眼", "鼻", "唇")

FACE_GEOM = [
    {"id": "G01", "name": "长椭圆薄骨", "gender": "fb", "age": (16, 68), "tags": ("B1", "B2", "B10"),
     "slots": {"脸型": "长椭圆", "中庭": "偏长", "下颌": "窄而内收", "眉": "细直眉峰靠后",
               "眼": "细长眼裂小", "鼻": "细直尖鼻头", "唇": "薄唇唇峰明显"},
     "detail": "长椭圆脸，纵向偏长、横向偏窄；中庭略长；下颌角窄而内收、下巴偏尖；颧弓不外扩，两颊平直；"
               "眉骨平，眉毛细直、眉峰靠后；眼型细长、眼裂高度小、眼距偏窄；鼻梁细直、鼻头小而尖；唇薄、唇峰明显。",
     "forbid": "下颌不削成锥、眼裂不放大成圆眼"},
    {"id": "G02", "name": "短圆肉骨", "gender": "fb", "age": (14, 45), "tags": ("B3", "B4", "B8"),
     "slots": {"脸型": "短圆", "中庭": "偏短", "下颌": "圆润、下巴短", "眉": "粗短眉距宽",
               "眼": "圆眼眼裂高", "鼻": "低鼻梁圆鼻头", "唇": "厚唇唇峰圆"},
     "detail": "短圆脸，面宽与面长接近；中庭偏短；下颌角圆润、下巴短圆；软组织饱满、苹果肌位置偏高；"
               "眉骨低平，眉形粗短、眉距偏宽；眼型圆、眼裂高度大、眼距偏宽；鼻梁低、鼻头圆钝、鼻翼略宽；唇厚、唇峰圆。",
     "forbid": "脸型不拉长、下巴不收尖"},
    {"id": "G03", "name": "方颌宽面", "gender": "fb", "age": (25, 70), "tags": ("B1", "B6", "B9"),
     "slots": {"脸型": "方脸", "中庭": "适中", "下颌": "角约 110°、体厚", "眉": "平直粗短",
               "眼": "中等眼裂上睑微垂", "鼻": "宽平鼻骨肉鼻头", "唇": "中等偏厚唇角平"},
     "detail": "方脸，面宽大、下颌角接近 110°、下颌体厚；中庭适中；颧骨平缓但颧弓宽；"
               "眉骨略前突，眉形平直粗、眉尾短；眼裂中等、上眼睑微垂；鼻骨宽平、鼻头有肉；唇中等偏厚、唇角平。",
     "forbid": "下颌角不磨圆成鹅蛋脸"},
    {"id": "G04", "name": "菱形高颧", "gender": "fb", "age": (18, 55), "tags": ("B4", "B5", "B9"),
     "slots": {"脸型": "菱形", "中庭": "偏长", "下颌": "角高而内收", "眉": "上挑锐眉峰",
               "眼": "细长上挑眼角尖", "鼻": "高直鼻梁窄鼻翼", "唇": "薄唇唇角上扬"},
     "detail": "菱形脸，额头窄、颧骨突出、下巴尖；中庭长；下颌角高且向内收；颧弓明显外扩；"
               "眉骨高，眉形上挑、眉峰锐；眼型细长上挑、内眼角尖；鼻梁高直、鼻翼窄；唇薄、唇角上扬。",
     "forbid": "颧弓不外推成方脸、眼尾不下垂"},
    {"id": "G05", "name": "心形尖颌", "gender": "f", "age": (16, 40), "tags": ("B3", "B5"),
     "slots": {"脸型": "心形", "中庭": "适中", "下颌": "急收成尖下巴", "眉": "弯眉眉尾细",
               "眼": "杏眼外眼角微垂", "鼻": "直鼻梁小鼻头", "唇": "丰满唇珠明显"},
     "detail": "心形脸，额头宽、颧骨略宽、下颌急速收窄成尖下巴；中庭适中；下颌线锐利；"
               "眉形弯、眉尾细；眼型杏、外眼角略下垂；鼻梁直、鼻头小巧；唇丰满、唇珠明显。",
     "forbid": "不把额头画窄、不把下巴画钝"},
    {"id": "G06", "name": "宽扁方面", "gender": "fb", "age": (30, 75), "tags": ("B7", "B8"),
     "slots": {"脸型": "宽扁方", "中庭": "偏短", "下颌": "低平近方形", "眉": "稀疏平眉",
               "眼": "小眼裂眼皮厚", "鼻": "塌鼻梁宽鼻头", "唇": "厚唇上唇外翻"},
     "detail": "宽扁方脸，面宽大于面长、下颌角低平近乎方形；中庭短；颈部偏短粗；"
               "眉骨平、眉形稀疏散；眼裂小、眼皮厚（内双）；鼻梁塌、鼻头宽扁；唇厚、上唇略外翻。",
     "forbid": "脸不拉长、鼻梁不垫高"},
    {"id": "G07", "name": "瘦长鹰相", "gender": "fb", "age": (35, 72), "tags": ("B5", "B6", "B9"),
     "slots": {"脸型": "窄长面颊凹", "中庭": "长", "下颌": "角窄、骨量小", "眉": "浓眉压眼",
               "眼": "深眼窝窄眼裂", "鼻": "高鹰钩鼻尖下垂", "唇": "薄唇下唇内收"},
     "detail": "窄长脸，颧骨与颊部凹陷、两颊无肉；中庭长；下颌角窄；眉骨突出、眉形浓而压眼；"
               "眼窝深、眼裂窄；鼻梁高且带鹰钩、鼻尖下垂；唇薄、下唇内收。",
     "forbid": "两颊不填成饱满、鼻头不上翘"},
    {"id": "G08", "name": "六边棱角", "gender": "fb", "age": (18, 50), "tags": ("B4", "B9", "B1"),
     "slots": {"脸型": "六边棱角", "中庭": "偏长", "下颌": "角与额角同时方正", "眉": "浓密上扬",
               "眼": "眼窝中等深双眼皮宽", "鼻": "高宽直鼻骨", "唇": "厚唇唇峰平"},
     "detail": "六边脸，颧弓与下颌同时有棱角、额角方正；中庭长；眼窝中等深；"
               "眉骨明显、眉形浓密上扬；眼型深、双眼皮宽；鼻梁高、鼻骨直而宽；唇厚、唇峰平。",
     "forbid": "不磨成柔和小脸、不把眼窝画平"},
    {"id": "G09", "name": "圆钝厚相", "gender": "fb", "age": (28, 75), "tags": ("B7", "B8", "B3"),
     "slots": {"脸型": "圆钝厚", "中庭": "偏短", "下颌": "短平、软组织厚", "眉": "短淡眉",
               "眼": "小眼裂眼角圆", "鼻": "圆大鼻头厚鼻翼", "唇": "厚而平的唇"},
     "detail": "圆钝脸，面颊与下颌厚实、下巴短平；中庭偏短；鼻唇沟浅；"
               "眉骨平、眉形短淡；眼裂小、眼角圆；鼻头圆大、鼻翼厚；唇厚而平。",
     "forbid": "不把脸削薄、不拉高鼻梁"},
    {"id": "G10", "name": "削瘦刻相", "gender": "fb", "age": (25, 65), "tags": ("B2", "B5", "B10"),
     "slots": {"脸型": "瘦削颊凹", "中庭": "偏长", "下颌": "角明显、骨量小", "眉": "细眉眉头低",
               "眼": "浅眼窝上睑薄", "鼻": "细鼻梁鼻尖下垂", "唇": "薄唇唇角下压"},
     "detail": "瘦削脸，两颊凹陷、颧骨下缘有阴影；中庭偏长；下颌角明显但骨量小；"
               "眉形细、眉头低；眼窝浅、上眼睑薄；鼻梁细、鼻尖下垂；唇薄、唇角下压。",
     "forbid": "两颊不填平、唇角不上扬"},
    {"id": "G11", "name": "方圆过渡", "gender": "fb", "age": (22, 55), "tags": ("B2", "B6", "B8"),
     "slots": {"脸型": "方圆过渡", "中庭": "适中", "下颌": "略方、转角柔和", "眉": "平缓眉尾自然落",
               "眼": "标准眼型眼距适中", "鼻": "中等鼻梁圆鼻头", "唇": "中等厚度"},
     "detail": "方圆过渡脸，额与颊饱满、下颌角略方但转角柔和；中庭适中；"
               "眉形平缓、眉尾自然下落；眼型标准、眼距适中；鼻梁中等、鼻头圆；唇中等厚度。",
     "forbid": "不把下颌改尖、不把脸拉长"},
    {"id": "G12", "name": "长脸正相", "gender": "m", "age": (22, 60), "tags": ("B1", "B6"),
     "slots": {"脸型": "长方硬朗", "中庭": "长", "下颌": "方而平", "眉": "粗平眉距窄",
               "眼": "细长上睑平", "鼻": "直宽鼻梁", "唇": "薄而阔的唇"},
     "detail": "长方脸，纵向长、下颌角方而平；中庭长；眉骨平直、眉形粗平、眉距窄；"
               "眼型细长、上眼睑平；鼻梁直而宽；唇薄而阔。",
     "forbid": "不把下颌画圆、不把唇画厚"},
    {"id": "G13", "name": "短脸宽眼距", "gender": "fb", "age": (14, 30), "tags": ("B3", "B4"),
     "slots": {"脸型": "短脸额低", "中庭": "短", "下颌": "圆、下巴略后缩", "眉": "弯高眉眉距宽",
               "眼": "大眼裂眼距宽外眼角下垂", "鼻": "短鼻梁翘鼻头", "唇": "小唇唇峰高"},
     "detail": "短脸，额头低、下庭短；中庭短；下颌角圆、下巴略后缩；"
               "眉形弯而高、眉距宽；眼裂高度大、眼距宽、外眼角下垂；鼻梁短、鼻头翘；唇小、唇峰高。",
     "forbid": "不把脸拉长、不把眼尾提平"},
    {"id": "G14", "name": "窄肩长颈骨", "gender": "fb", "age": (20, 55), "tags": ("B2", "B10", "B1"),
     "slots": {"脸型": "窄长", "中庭": "偏长", "下颌": "线细", "眉": "细弯眉",
               "眼": "狭长内眼角下勾", "鼻": "细窄鼻尖微翘", "唇": "薄唇唇线模糊"},
     "detail": "窄长骨相，肩窄颈长、锁骨明显；面部窄长、下颌线细；中庭长；"
               "眉形细弯；眼型狭长、内眼角下勾；鼻梁细窄、鼻尖微翘；唇薄、唇线模糊。",
     "forbid": "不把肩加宽成方肩、不把下颌画厚"},
]

# 族裔包：只给「肤色/毛发/眼型基底」，骨相由 FACE_GEOM 决定；
# `repl` 负责把骨相描述里**与族裔冲突的措辞**就地改口（如东亚不写「深眼窝/鹰钩鼻」）
# —— 否则同一段提示词里会同时出现「眼窝浅（蒙古褶）」与「眼窝中等深」，模型只能二选一。
REGION = {
    "east_asian": {
        "cn": "东亚",
        "line": "东亚面孔：肤色偏黄调的浅至中等（不是冷白瓷）；黑发、发丝粗硬带蓝紫反光；眉毛细软。",
        "forbid": "五官不混入欧美高鼻骨与深眼窝",
        "repl": (("眼型深、双眼皮宽", "眼型平、双眼皮窄"),
                 ("眼窝中等深", "眼窝浅、蒙古褶明显"),
                 ("深眼窝", "眼窝略深"), ("眼窝深", "眼窝浅"),
                 ("鼻梁高且带鹰钩", "鼻梁中等高、鼻尖微垂"),
                 ("鼻梁高窄", "鼻梁中等偏高"),
                 ("鼻梁高、鼻骨直而宽", "鼻梁中等偏高、鼻骨直"),
                 ("鼻骨直而宽", "鼻骨直、中等宽"),
                 ("鼻骨宽、鼻翼厚", "鼻骨宽、鼻翼略厚"),
                 ("眉骨突出", "眉骨略高"), ("眉骨明显", "眉骨略高"), ("眉骨高", "眉骨略高"),
                 ("颧弓明显外扩", "颧弓略外扩"),
                 ("唇厚而平", "唇中等、唇峰平"), ("唇丰满", "唇中等、唇珠明显"),
                 ("唇厚", "唇中等偏厚")),
    },
    "latam_mestizo": {
        "cn": "拉美混血",
        "line": "拉美 mestizo 面孔：橄榄棕至深棕肤色；黑色或深棕发、发质粗硬带自然卷；眉浓、睫毛密。",
        "forbid": "五官不混入纯东亚扁平鼻骨与冷白皮",
        "repl": (("眼窝浅、蒙古褶明显", "眼窝中等深"),
                 ("眼窝浅", "眼窝中等深"),
                 ("鼻梁细窄", "鼻梁中等、鼻翼略宽"),
                 ("鼻骨宽平", "鼻骨宽、鼻翼厚"),
                 ("鼻头小而尖", "鼻头圆"),
                 ("唇薄至中等", "唇中等偏厚"), ("唇薄", "唇中等偏厚")),
    },
    "western": {
        "cn": "西方",
        "line": "西方高加索面孔：肤色从冷白到浅橄榄；发色棕/金/红棕；眉骨立体。",
        "forbid": "五官不混入亚裔眼型与扁平鼻骨",
        "repl": (("眼窝浅、蒙古褶明显", "眼窝深"),
                 ("眼窝浅", "眼窝深"),
                 ("鼻梁低", "鼻梁中等"),
                 ("鼻骨宽平", "鼻骨中等宽"),
                 ("鼻头圆钝", "鼻头略尖"),
                 ("唇厚", "唇中等"), ("唇中等偏厚", "唇中等")),
    },
}

HAIR = [
    {"id": "H01", "name": "高蓬松马尾", "gender": "f", "age": (14, 40), "tone": "casual",
     "silhouette": "顶部立起的高马尾，鬓角与额前留碎发",
     "detail": "深色头发在脑后扎成高蓬松马尾，发根立起、发尾散开，鬓角与额前留几缕碎发。",
     "forbid": "不画成低马尾或披发"},
    {"id": "H02", "name": "低盘髻", "gender": "f", "age": (28, 80), "tone": "formal",
     "silhouette": "贴头皮的低盘髻，颈后收紧",
     "detail": "头发向后梳紧、在颈后盘成低髻，发丝服帖、无碎发，露出完整发际线。",
     "forbid": "不画成松散丸子头"},
    {"id": "H03", "name": "齐耳内扣短发", "gender": "f", "age": (16, 55), "tone": "any",
     "silhouette": "齐耳短发，发尾内扣钩住下颌线",
     "detail": "齐耳短发，发尾向内扣住下颌线，发顶蓬松、侧分。",
     "forbid": "不画成长发或外翘"},
    {"id": "H04", "name": "中分长直", "gender": "f", "age": (18, 50), "tone": "formal",
     "silhouette": "笔直中分，长发过胸",
     "detail": "中分长直发，发缝笔直、发丝顺滑过胸，发尾齐平。",
     "forbid": "不画成卷发或齐刘海"},
    {"id": "H05", "name": "侧分大波浪", "gender": "f", "age": (24, 58), "tone": "formal",
     "silhouette": "3:7 侧分，卷度从下颌开始",
     "detail": "3:7 侧分长发，卷度从下颌开始向外扩，发量厚、发尾有弹性。",
     "forbid": "不画成直发或小卷"},
    {"id": "H06", "name": "贴头皮背头", "gender": "m", "age": (20, 75), "tone": "formal",
     "silhouette": "全部向后梳紧，两侧收窄",
     "detail": "头发向后梳紧成背头，发丝贴头皮、两侧收窄，露出额头与鬓角。",
     "forbid": "不画成蓬松刘海"},
    {"id": "H07", "name": "寸头", "gender": "m", "age": (18, 55), "tone": "casual",
     "silhouette": "3mm 推剪，发际线清晰",
     "detail": "3mm 推剪寸头，发际线与颅骨形状清晰可见。",
     "forbid": "不画成有刘海或长发"},
    {"id": "H08", "name": "短发微卷", "gender": "m", "age": (16, 40), "tone": "casual",
     "silhouette": "顶部短微卷，两侧剪短",
     "detail": "短发，顶部微卷有蓬松度、两侧剪短，鬓角利落。",
     "forbid": "不画成长发或直发"},
    {"id": "H09", "name": "双低辫", "gender": "f", "age": (12, 28), "tone": "casual",
     "silhouette": "两条低辫搭在锁骨前",
     "detail": "头发分成两股、编成低辫搭在锁骨前，辫尾用素色发圈扎住。",
     "forbid": "不画成单马尾"},
    {"id": "H10", "name": "半扎半披", "gender": "f", "age": (16, 32), "tone": "casual",
     "silhouette": "上半束起，下半披肩",
     "detail": "上半部分头发束在脑后、下半披肩，发丝自然垂落。",
     "forbid": "不画成全部盘起"},
    {"id": "H11", "name": "厚齐刘海长发", "gender": "f", "age": (14, 35), "tone": "casual",
     "silhouette": "刘海齐眉，两侧发束包住脸颊",
     "detail": "长发配厚齐刘海，刘海齐眉、两侧发束向内包住脸颊。",
     "forbid": "不画成露额中分"},
    {"id": "H12", "name": "鬓角短发", "gender": "fb", "age": (18, 55), "tone": "any",
     "silhouette": "无刘海，发际线露出，后颈碎发",
     "detail": "短发无刘海、发际线完全露出，后颈留碎发、耳前有鬓角。",
     "forbid": "不画成齐刘海"},
    {"id": "H13", "name": "短寸偏分", "gender": "m", "age": (20, 60), "tone": "any",
     "silhouette": "两侧推短、顶部留短偏分",
     "detail": "两侧推短、顶部留三厘米短发梳成偏分，发缝清晰。",
     "forbid": "不画成背头或长发"},
    {"id": "H14", "name": "灰白短发", "gender": "fb", "age": (52, 90), "tone": "any",
     "silhouette": "花白短发，发量偏薄",
     "detail": "花白短发，发量偏薄、发丝细软，发际线后退、鬓角与发尾有银白。",
     "forbid": "不画成乌黑浓密"},
    {"id": "H15", "name": "半长背头", "gender": "m", "age": (22, 62), "tone": "formal",
     "silhouette": "后颈留长、向后梳",
     "detail": "半长发向后梳、后颈留到衣领，发丝有梳痕、略见油光。",
     "forbid": "不画成短发或刘海"},
]

FABRIC = [
    {"id": "T01", "name": "精纺羊毛", "behavior": "垂坠挺括、表面哑光、折线利落"},
    {"id": "T02", "name": "粗针织", "behavior": "厚重、边缘起球、袖口松垮"},
    {"id": "T03", "name": "真丝缎", "behavior": "高光流动、褶皱细密、贴肤"},
    {"id": "T04", "name": "水洗棉", "behavior": "软塌、洗旧泛白、接缝起皱"},
    {"id": "T05", "name": "硬挺府绸", "behavior": "棱角分明、折线锐、反光均匀"},
    {"id": "T06", "name": "牛仔布", "behavior": "斜纹明显、膝肘磨白、硬壳感"},
    {"id": "T07", "name": "绒面麂皮", "behavior": "吸光、手感哑、边缘起绒"},
    {"id": "T08", "name": "亚麻", "behavior": "自然皱、透光、垂坠松散"},
    {"id": "T09", "name": "运动涤纶", "behavior": "表面反光、挺括、有压胶线"},
    {"id": "T10", "name": "羊绒", "behavior": "轻薄、边缘起绒、贴身无褶"},
    {"id": "T11", "name": "皮革", "behavior": "硬壳、折痕处发亮、肩线固定"},
    {"id": "T12", "name": "纱布棉麻", "behavior": "半透、层叠、下摆有毛边"},
]

# 色签名：8 个有彩色槽（相邻色相间隔 ≥ 36°，可容 8 个阵营互不撞色）+ 2 个中性槽
# 中性槽（s < 0.15）不参与色相判定，靠明度区分 —— 语义上「烟灰/米白」无所谓色相
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
    {"id": "P10", "name": "米白", "h": 40, "s": 0.10, "l": 0.72},
]
NEUTRAL_S = 0.15        # 低于此饱和度视为中性色：不参与色相判定

ANCHOR = [
    {"id": "A01", "name": "泪痣", "text": "左眼角下方一颗扁平泪痣（直径约 2mm）", "bare": True},
    {"id": "A02", "name": "眉尾旧疤", "text": "右眉尾一道浅白旧疤（约 1.5cm，断开眉毛）", "bare": False},
    {"id": "A03", "name": "虎口烫痕", "text": "左手虎口一处烫伤旧痕（皮肤发亮、无毛）", "bare": False},
    {"id": "A04", "name": "素银印章戒", "text": "左手中指一枚素银印章戒（戒面磨平）", "bare": False},
    {"id": "A05", "name": "细圆框眼镜", "text": "一副细金属圆框眼镜（镜片有细微划痕）", "bare": False},
    {"id": "A06", "name": "单只旧金耳夹", "text": "右耳单只旧金耳夹（另一只耳垂无饰）", "bare": False},
    {"id": "A07", "name": "颈侧细疤", "text": "左侧颈侧一道淡色细疤（约 3cm）", "bare": False},
    {"id": "A08", "name": "磨损编织绳", "text": "右手腕一条磨损的素色编织绳（无坠）", "bare": False},
    {"id": "A09", "name": "断眉", "text": "左眉中段一道断口（眉毛不连续）", "bare": True},
    {"id": "A10", "name": "单侧酒窝", "text": "右脸颊一个单侧酒窝（左脸没有）", "bare": True},
    {"id": "A11", "name": "唇下小痣", "text": "下唇正中偏左一颗小痣（直径约 1mm）", "bare": True},
    {"id": "A12", "name": "额角发旋", "text": "右侧额角发际线处一个明显发旋", "bare": False},
    {"id": "A13", "name": "小指旧伤", "text": "左手小指指甲缺半截（旧伤愈合）", "bare": False},
    {"id": "A14", "name": "鼻梁压痕", "text": "鼻梁上一道横向浅压痕（长期戴眼镜留下，但不戴眼镜）", "bare": True, "min_age": 28},
    {"id": "A15", "name": "锁骨胎记", "text": "右锁骨下方一处浅褐色胎记（边缘不规则）", "bare": False},
    {"id": "A16", "name": "方形旧表", "text": "左手腕一只老式方形手表（表带磨白、表盘发黄）", "bare": False, "min_age": 26},
    {"id": "A17", "name": "褪色徽章", "text": "左胸别一枚褪色金属徽章（图案磨损不可辨）", "bare": False},
    {"id": "A18", "name": "耳后纹身边缘", "text": "左耳后露出一小块纹身边缘（藏在发内，只露一线）", "bare": False},
    {"id": "A19", "name": "食指关节粗大", "text": "右手食指中段关节粗大（旧骨折愈合）", "bare": False, "min_age": 24},
    {"id": "A20", "name": "唇侧竖疤", "text": "下唇左侧一道竖向细疤（约 8mm）", "bare": True},
    {"id": "A21", "name": "腰间钥匙串", "text": "右侧腰间挂一串铜钥匙（三把、长短不一）", "bare": False, "min_age": 30},
    {"id": "A22", "name": "黑绳颈饰", "text": "颈间一根黑绳（坠子压在衣领内、不外露）", "bare": False},
    {"id": "A23", "name": "左颊晒斑", "text": "左颊一片浅淡晒斑（不规则、约拇指大）", "bare": True},
    {"id": "A24", "name": "宽银拇指环", "text": "右手拇指一枚宽银戒（表面有细密划痕）", "bare": False, "min_age": 22},
]

POSTURE = [
    {"id": "S01", "posture": "重心压在左脚，右肩略低，下巴微收"},
    {"id": "S02", "posture": "双脚与肩同宽，脊背笔直，下巴平抬"},
    {"id": "S03", "posture": "双臂抱在胸前，肩线前扣，上身略侧"},
    {"id": "S04", "posture": "单手插袋，另一手垂在体侧，身体略后仰"},
    {"id": "S05", "posture": "双肩内收、头略前倾，双手在身前交握"},
    {"id": "S06", "posture": "一侧胯部顶出，站姿松弛，一手扶着包带"},
    {"id": "S07", "posture": "挺胸收腹，双手背在身后，脚跟并拢"},
    {"id": "S08", "posture": "肩背微驼、重心偏后，双手自然下垂"},
]

# 人群桶：关键词命中 → 表情基准 + 偏好骨相 + 体态候选 + 面料候选
# 面料按人群桶收敛，是为了避免「野性转校生穿真丝缎」这类**身份与材质打架**的生成事故
PERSONA = {
    "B1": {"name": "掌控者", "kw": ("掌权", "总裁", "族长", "主母", "董事长", "强势", "控制", "主事", "当家人"),
           "expr": "目光平视、唇角平直略下压、下颌微抬，情绪收敛但有压迫感",
           "faces": ("G03", "G12", "G04", "G01"), "postures": ("S02", "S03", "S07"),
           "fabrics": ("T01", "T03", "T10", "T05")},
    "B2": {"name": "隐忍者", "kw": ("复仇", "隐忍", "重生", "装", "委屈", "蛰伏", "忍"),
           "expr": "眼睑微垂、唇角放松、眼珠上抬看向对方，情绪压在眼底",
           "faces": ("G01", "G10", "G11", "G14"), "postures": ("S05", "S08", "S01"),
           "fabrics": ("T04", "T08", "T02")},
    "B3": {"name": "天真者", "kw": ("天真", "单纯", "少女", "懵", "初恋", "无辜", "软"),
           "expr": "眼裂张开、唇微张、眉心上抬，情绪写在脸上",
           "faces": ("G13", "G05", "G02", "G09"), "postures": ("S06", "S05", "S01"),
           "fabrics": ("T02", "T04", "T12")},
    "B4": {"name": "闯入者", "kw": ("野", "叛逆", "痞", "不驯", "外来", "闯入", "转校", "混不吝"),
           "expr": "下巴前送、嘴角单侧斜挑、视线略微俯视，带挑衅",
           "faces": ("G08", "G04", "G02", "G13"), "postures": ("S04", "S06", "S01"),
           "fabrics": ("T06", "T09", "T04")},
    "B5": {"name": "算计者", "kw": ("心机", "伪善", "绿茶", "白莲", "算计", "两面", "人前"),
           "expr": "笑意只到眼下、唇角单侧上扬、眉尾放松，情绪不对齐",
           "faces": ("G05", "G07", "G10", "G01"), "postures": ("S02", "S06", "S03"),
           "fabrics": ("T03", "T05", "T10")},
    "B6": {"name": "执行者", "kw": ("保镖", "杀手", "助理", "秘书", "冷面", "执行", "司机", "随行"),
           "expr": "面无表情、上眼睑压平、唇线紧闭，情绪不外露",
           "faces": ("G12", "G03", "G07", "G11"), "postures": ("S02", "S07", "S03"),
           "fabrics": ("T01", "T09", "T11")},
    "B7": {"name": "长者", "kw": ("祖母", "祖父", "老爷", "老太", "长辈", "父", "母", "族长夫人"),
           "expr": "眼睑松弛、目光沉、唇色淡，情绪收在皱纹里",
           "faces": ("G09", "G06", "G14", "G03"), "postures": ("S08", "S05", "S07"),
           "fabrics": ("T02", "T08", "T10")},
    "B8": {"name": "市井者", "kw": ("市井", "小贩", "保姆", "邻居", "婆", "婶", "打工", "摆摊"),
           "expr": "眉间有竖纹、嘴角习惯性下垂、目光直白，情绪外放",
           "faces": ("G06", "G09", "G02", "G11"), "postures": ("S06", "S08", "S05"),
           "fabrics": ("T04", "T02", "T12")},
    "B9": {"name": "江湖者", "kw": ("江湖", "黑道", "混", "打手", "大哥", "道上", "刀"),
           "expr": "眼神斜视、下颌前倾、嘴角带笑不达眼底，情绪危险",
           "faces": ("G08", "G07", "G03", "G04"), "postures": ("S04", "S03", "S01"),
           "fabrics": ("T11", "T06", "T09")},
    "B10": {"name": "病态者", "kw": ("病", "弱", "抑郁", "绝症", "残", "药", "失忆", "厌世"),
            "expr": "面色偏淡、眼窝有青、唇无血色，情绪疲惫",
            "faces": ("G01", "G10", "G13", "G14"), "postures": ("S05", "S08", "S01"),
            "fabrics": ("T10", "T12", "T08")},
}

# 年龄 → 皮肤与手部纹理（绝大多数提示词写「细腻无瑕」，等于把全剧压成 25 岁）
SKIN = [
    (0, 22, "皮肤有细密绒毛与轻微肤色不均，鼻翼两侧泛淡红，无妆感"),
    (23, 32, "眼下有淡青，鼻唇沟初现，颧骨处有极淡晒斑，皮肤有真实毛孔"),
    (33, 45, "法令纹与颈纹清晰可见，眼尾有细纹，手背有浅纹与淡斑"),
    (46, 60, "皮肤松弛下垂、颈纹深，眼袋明显，手背青筋与色斑清晰"),
    (61, 200, "皱纹密集、皮肤薄透失去弹性，老年斑与手背凸起的青筋明显"),
]

DOWN_F = ("直筒西裤", "工装长裤", "水洗牛仔裤", "百褶中长裙", "包臀半身裙", "束脚运动裤",
          "阔腿长裤", "深色及膝裙")
DOWN_M = ("直筒西裤", "工装长裤", "水洗牛仔裤", "束脚运动裤", "阔腿长裤", "灯芯绒长裤")
SHOES_F = ("白色板鞋", "黑色乐福鞋", "短靴", "黑色布鞋", "尖头低跟鞋", "旧运动鞋", "平底单鞋")
SHOES_M = ("黑色乐福鞋", "系带皮鞋", "短靴", "白色板鞋", "旧运动鞋", "黑色布鞋", "工装靴")
FORMAL_FABRICS = ("T01", "T03", "T05", "T10", "T11")
ACCENT_PLACE = ("领口滚边", "袖口", "内搭", "包", "鞋", "发带", "围巾", "腰封")
ACCESSORY = ("细金属腰带", "单只耳环", "帆布托特包", "皮质公文包", "针织围巾", "无任何配饰",
             "细链项链", "墨镜挂在领口", "双肩包", "耳机挂在颈间")
ACCESSORY_YOUNG = ("帆布托特包", "双肩包", "耳机挂在颈间", "无任何配饰", "细链项链", "细金属腰带")
ACCESSORY_FORMAL = ("皮质公文包", "细金属腰带", "细链项链", "无任何配饰", "单只耳环")

# 评价性美颜词：出现即视为「把差异交回给模型的默认脸」（R6）
BANNED_WORDS = ("俊美", "俊朗", "绝美", "惊艳", "倾国倾城", "气质出众", "面容精致", "白皙无瑕",
                "完美无瑕", "五官精致", "盛世美颜", "高颜值", "帅", "漂亮", "美丽", "性感")

# 机器真源版本（bible 内记录，便于回溯口径）
LIB_VERSION = "1.0.0"


# ===========================================================================
# 二、确定性小工具
# ===========================================================================
def _h(s: str) -> int:
    """稳定哈希（只用于「同等分情况下的次序打散」，不引入随机）。"""
    return int(hashlib.sha256(s.encode("utf-8")).hexdigest()[:8], 16)


def _rgb(h: float, s: float, l: float) -> str:
    r, g, b = colorsys.hls_to_rgb(h / 360.0, l, s)
    return "#%02X%02X%02X" % (round(r * 255), round(g * 255), round(b * 255))


def _hue_gap(a: float, b: float) -> float:
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def _write(path: pathlib.Path, text: str) -> None:
    """写文件：显式 newline='' 强制 LF（Windows 默认 CRLF 会污染 manifest）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text if text.endswith("\n") else text + "\n")


def _skin(age: int) -> str:
    for lo, hi, line in SKIN:
        if lo <= age <= hi:
            return line
    return SKIN[-1][2]


def _gender_cn(g: str) -> str:
    return {"f": "女性", "m": "男性"}.get(g, "人物")


def _bucket(ch: dict) -> str:
    """人群桶：按关键词命中数取最高分（同分按桶序），无命中按年龄兜底。

    不能「首个命中即返回」——实测「冷面·病·疏离」会被先出现的 B6 抢走，
    而这个角色的核心是 B10 病态者。
    """
    text = " ".join([str(ch.get("identity") or "")] + [str(x) for x in (ch.get("persona") or [])])
    best, best_hit = None, 0
    for bid, p in PERSONA.items():
        hit = sum(1 for k in p["kw"] if k in text)
        if hit > best_hit:
            best, best_hit = bid, hit
    if best:
        return best
    age = int(ch.get("age") or 30)
    if age >= 55:
        return "B7"
    return "B3" if age <= 20 else "B2"


def _regionize(text: str, region: dict) -> str:
    """把骨相描述里与族裔冲突的措辞就地改口（长串优先，避免短串先吃掉长串）。"""
    for a, b in sorted(region.get("repl") or (), key=lambda x: -len(x[0])):
        text = text.replace(a, b)
    return text


def _face_distance(a: dict, b: dict) -> float:
    """七槽面部签名距离（0–1）。两套骨相若七槽全不同 = 1.0。"""
    sa, sb = a["face"]["slots"], b["face"]["slots"]
    return sum(sa[k] != sb[k] for k in SLOTS) / float(len(SLOTS))


def _formal(ch: dict) -> bool:
    text = " ".join([str(ch.get("identity") or "")] + [str(x) for x in (ch.get("persona") or [])])
    return any(k in text for k in ("总裁", "董事", "律师", "经理", "主任", "族长", "宴会", "婚礼",
                                   "秘书", "助理", "主母", "高管", "财阀", "少爷", "千金"))


# ===========================================================================
# 三、分配：最大最小距离贪心
# ===========================================================================
def _pick_face(ch: dict, picked: list, forbidden: tuple = ()) -> dict:
    bid = _bucket(ch)
    gender = ch.get("gender") or "f"
    age = int(ch.get("age") or 30)
    pool = [f for f in FACE_GEOM
            if f["id"] not in forbidden
            and (f["gender"] == "fb" or f["gender"] == gender)
            and f["age"][0] - 6 <= age <= f["age"][1] + 10]
    if not pool:                                    # 年龄/性别放宽后再退
        pool = [f for f in FACE_GEOM if f["id"] not in forbidden
                and (f["gender"] == "fb" or f["gender"] == gender)] or list(FACE_GEOM)
    prefer = PERSONA[bid]["faces"]
    best, best_key = None, None
    for f in pool:
        dist = min((_face_distance({"face": f}, {"face": p["face"]}) for p in picked), default=1.0)
        key = (round(dist, 6), 1 if f["id"] in prefer else 0, -_h(ch["name"] + f["id"]))
        if best_key is None or key > best_key:
            best, best_key = f, key
    return best


def _pick_hair(ch: dict, age: int, gender: str, used: set) -> dict:
    """发型：先按性别 + 年龄过滤，再优先匹配「正式 / 休闲」基调，最后取未用过的。

    不这么做的实测后果：52 岁的男教导主任被分配到「中分长直」。
    """
    pool = [h for h in HAIR
            if h["gender"] in ("fb", gender) and h["age"][0] - 4 <= age <= h["age"][1] + 6]
    if not pool:
        pool = [h for h in HAIR if h["gender"] in ("fb", gender)] or list(HAIR)
    free = [h for h in pool if h["id"] not in used] or list(pool)
    want = "formal" if _formal(ch) else "casual"
    fit = [h for h in free if h["tone"] == want]
    cand = fit or free
    return cand[_h(ch["name"] + "hair") % len(cand)]


def _pick_by_pool(pool: list, picked_ids: set, ch: dict) -> dict:
    """从池里挑一个未用过的；全都用过时按名字哈希取一个（确定性复用，规则层另行判定）。"""
    free = [x for x in pool if x["id"] not in picked_ids] or list(pool)
    return free[_h(ch["name"] + pool[0]["id"]) % len(free)]


def _hue_slots(n_groups: int) -> list:
    """给 n 个阵营分配色相槽位：按固定跨步取，使相邻入选槽位的色相尽量远离。

    前 8 个取有彩色（最小间隔 ≥ 36°），第 9、10 个才落到中性槽（烟灰/米白）。
    """
    order = [0, 4, 1, 5, 2, 6, 3, 7, 8, 9]
    return [PALETTE[i] for i in order[:max(1, min(n_groups, len(order)))]]


def design(roster: dict) -> dict:
    """名册 → 角色圣经（六维签名 + 差异矩阵）。确定性：同输入同输出。"""
    chars = list(roster.get("characters") or [])
    if not chars:
        raise SystemExit("[FAIL] 名册里没有 characters（至少给一个角色）")
    seed = str(roster.get("seed") or "solodrama")
    region_key = roster.get("region") or "east_asian"
    if region_key not in REGION:
        raise SystemExit("[FAIL] 未知 region：%s（可选 %s）" % (region_key, "/".join(REGION)))
    region = REGION[region_key]

    used_face, used_hair, used_fabric, used_anchor, used_posture = set(), set(), set(), set(), set()
    designs = []
    # 主演先选：让主角拿到「人群桶最贴合 + 距离最远」的骨相，配角随后避让
    tier_rank = {"lead": 0, "support": 1, "minor": 2}
    ordered = sorted(chars, key=lambda c: (tier_rank.get(c.get("tier") or "support", 1),
                                           _h(seed + str(c.get("name")))))
    picked_faces = []
    for ch in ordered:
        ov = ch.get("overrides") or {}
        bid = _bucket(ch)
        age = int(ch.get("age") or 30)
        gender = ch.get("gender") or "f"
        face = next((f for f in FACE_GEOM if f["name"] == ov.get("face") or f["id"] == ov.get("face")), None)
        if face is None:
            face = _pick_face(ch, picked_faces, tuple(used_face))
        used_face.add(face["id"])
        # 族裔改口：只改这份副本，不动全局词库（否则后面的角色被前一个角色的族裔污染）
        face = dict(face, detail=_regionize(face["detail"], region))
        picked_faces.append({"name": ch["name"], "face": face, "tier": ch.get("tier") or "support"})

        hair = next((h for h in HAIR if h["name"] == ov.get("hair") or h["id"] == ov.get("hair")), None)
        if hair is None:
            hair = _pick_hair(ch, age, gender, used_hair)
        used_hair.add(hair["id"])

        fabric = next((x for x in FABRIC if x["name"] == ov.get("fabric") or x["id"] == ov.get("fabric")), None)
        if fabric is None:
            want_formal = _formal(ch)
            pref_ids = [i for i in PERSONA[bid]["fabrics"] if (i in FORMAL_FABRICS) == want_formal] \
                or list(PERSONA[bid]["fabrics"])
            prefer = [x for x in FABRIC if x["id"] in pref_ids and x["id"] not in used_fabric]
            fabric = _pick_by_pool(prefer or FABRIC, used_fabric, ch)
        used_fabric.add(fabric["id"])

        anchor = next((a for a in ANCHOR if a["name"] == ov.get("anchor") or a["id"] == ov.get("anchor")), None)
        if anchor is None:
            free = [a for a in ANCHOR if a["id"] not in used_anchor
                    and a.get("min_age", 0) <= age <= a.get("max_age", 200)]
            free = free or [a for a in ANCHOR if a["id"] not in used_anchor]
            anchor = free[_h(seed + ch["name"] + "anchor") % len(free)]
        used_anchor.add(anchor["id"])

        pref_post = [p for p in POSTURE if p["id"] in PERSONA[bid]["postures"] and p["id"] not in used_posture]
        cand_post = pref_post or [p for p in POSTURE if p["id"] not in used_posture] or POSTURE
        posture = cand_post[_h(seed + ch["name"] + "posture") % len(cand_post)]
        used_posture.add(posture["id"])

        designs.append({
            "name": ch["name"], "tier": ch.get("tier") or "support", "gender": gender,
            "age": age, "identity": ch.get("identity") or "",
            "faction": ch.get("faction") or "主线", "persona_bucket": bid,
            "face": face, "hair": hair, "fabric": fabric, "anchor": anchor, "posture": posture,
            "skin": _skin(age),
            "region": region_key, "region_cn": region["cn"], "region_line": region["line"],
            "region_forbid": region["forbid"],
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
        d["color"] = {"id": base["id"], "name": base["name"], "hue": base["h"],
                      "hex": _rgb(base["h"], base["s"], l), "l": round(l, 2), "s": base["s"],
                      "accent_hex": _rgb((base["h"] + 150) % 360, 0.42, 0.38),
                      "accent_place": ACCENT_PLACE[_h(seed + d["name"] + "acc") % len(ACCENT_PLACE)]}

    # ---- 服装文本 ----
    for i, d in enumerate(designs):
        d["garment"] = _garment_text(d, i)
        d["expression"] = PERSONA[d["persona_bucket"]]["expr"]

    # ---- 差异对照（与最像的那位显式拉开） ----
    for d in designs:
        others = [x for x in designs if x is not d]
        if others:
            near = min(others, key=lambda x: (_face_distance(d, x), _h(d["name"] + x["name"])))
            d["contrast"] = ("同剧 %s（%s）为%s、%s；本角色为%s、%s。两人同框时发型、眉形与主色必须可区分。"
                             % (near["name"], near["identity"] or near["tier"],
                                near["face"]["name"], near["hair"]["name"],
                                d["face"]["name"], d["hair"]["name"]))
        else:
            d["contrast"] = "本剧仅此一名主要角色：以唯一识别锚与色签名作为全场辨识依据。"
        d["face_short"] = "%s、%s" % (d["face"]["slots"]["脸型"], d["face"]["slots"]["下颌"])

    # 输出顺序回到「名册顺序」：分配顺序是按 tier 排的，但产物要跟剧本目录一致
    order = {str(ch.get("name")): i for i, ch in enumerate(chars)}
    designs.sort(key=lambda d: order.get(d["name"], 999))

    bible = {
        "_note": "角色差异化设计真源（由 character_design.py 生成，勿手改）",
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


def _garment_text(d: dict, idx: int) -> str:
    """服装文本：**上装由面料决定**（牛仔配夹克、真丝配西装/衬衫），避免「牛仔布针织上衣」。"""
    age = d["age"]
    g = "f" if d["gender"] == "f" else "m"
    formal = _formal(d) or age >= 55
    fid = d["fabric"]["id"]
    if g == "f":
        # 学生与长者不穿包臀裙（身份与年龄适配，实测 17 岁「天真者」被分配过包臀裙）
        downs = tuple(x for x in DOWN_F
                      if not (x == "包臀半身裙" and (age <= 20 or age >= 50)))
        shoes_pool = SHOES_F
    else:
        downs, shoes_pool = DOWN_M, SHOES_M
    down = downs[(idx + _h(d["name"])) % len(downs)]
    shoes = shoes_pool[(idx * 3 + _h(d["name"] + "s")) % len(shoes_pool)]
    acc_pool = ACCESSORY_YOUNG if age <= 22 else (ACCESSORY_FORMAL if formal else ACCESSORY)
    acc = acc_pool[(idx + _h(d["name"] + "a")) % len(acc_pool)]

    if age >= 60:
        top = "上装为对襟开衫，扣至第二颗；下装为深色%s；脚穿软底%s" % (down, shoes)
    elif fid in ("T06", "T09"):
        top = ("上装为短款工装夹克，内搭素色 T 恤；下装为%s；脚穿%s" % (down, shoes)) if g == "m" \
            else ("上装为宽松牛仔外套，内搭素色 T 恤；下装为%s；脚穿%s" % (down, shoes))
    elif fid == "T11":
        top = "上装为皮质短夹克，领口立起；下装为%s；脚穿%s" % (down, shoes)
    elif fid == "T02":
        top = "上装为粗针织上衣，领口松垮；下装为%s；脚穿%s" % (down, shoes)
    elif fid == "T10":
        top = "上装为羊绒衫，袖口自然垂落；下装为%s；脚穿%s" % (down, shoes)
    elif fid in ("T04", "T08", "T12"):
        top = "上装为棉麻衬衫，袖口卷至小臂；下装为%s；脚穿%s" % (down, shoes)
    elif formal:
        top = "上装为单排两扣西装，内搭素色衬衫；下装为同色西裤；脚穿牛津鞋" if g == "m" \
            else "上装为收腰西装外套，内搭窄领衬衫；下装为同色系直筒西裤；脚穿尖头低跟鞋"
    else:
        top = "上装为府绸衬衫，领口敞开一颗扣；下装为%s；脚穿%s" % (down, shoes)

    return ("主色为%s（%s），撞色 %s（低饱和）只出现在%s；面料为%s，%s；%s；%s。"
            % (d["color"]["name"], d["color"]["hex"], d["color"]["accent_hex"],
               d["color"]["accent_place"], d["fabric"]["name"], d["fabric"]["behavior"], top, acc))


def _public(d: dict) -> dict:
    """导出到 bible 的字段（不带内部临时键）。"""
    keep = ("name", "tier", "gender", "age", "identity", "faction", "persona_bucket",
            "hair", "fabric", "anchor", "posture", "skin", "region", "region_cn",
            "region_line", "region_forbid", "color", "garment", "expression", "contrast", "face_short")
    out = {k: d[k] for k in keep if k in d}
    out["face"] = {k: d["face"][k] for k in ("id", "name", "slots", "detail", "forbid", "gender", "age")}
    out["persona"] = PERSONA[d["persona_bucket"]]["name"]
    return out


# ===========================================================================
# 四、资产卡字段与三件套提示词
# ===========================================================================
def _end(text: str) -> str:
    """保证一段描述以且仅以一个句号收尾。"""
    return (text or "").rstrip("。；; ") + "。"


def to_fields(c: dict, style_anchor: str = "") -> dict:
    """六维签名 → 资产卡字段（形象定位/面部特征/表情/服装细节/识别锚/差异对照/反默认）。"""
    face, hair, anchor = c["face"], c["hair"], c["anchor"]
    return {
        "风格": style_anchor,
        "形象定位": ("%d 岁%s%s；骨相：%s（中庭%s）；体态：%s；%s气质。"
                     % (c["age"], _gender_cn(c["gender"]),
                        ("，" + c["identity"]) if c.get("identity") else "",
                        c["face_short"], face["slots"]["中庭"],
                        c["posture"]["posture"], c["persona"])),
        "面部特征": ("%s%s发型：%s皮肤质感：%s"
                     % (c["region_line"], face["detail"], _end(hair["detail"]), _end(c["skin"]))),
        "表情": c["expression"] + "。",
        "服装细节": c["garment"],
        "识别锚": "%s。" % anchor["text"],
        "差异对照": c["contrast"],
        "反默认": ("排除标准网红脸（削尖下颌＋放大眼裂＋垫高鼻梁＋无毛孔磨皮）、韩式平眉、"
                   "烤瓷牙反光、左右绝对对称的脸；%s；%s。" % (face["forbid"], c["region_forbid"])),
    }


def _item(c: dict, fields: dict) -> dict:
    return {"kind": "char", "id": "CH%02d" % (c.get("section") or 1), "title": c["name"],
            "fields": fields, "raw": ""}


def board_prompt(c: dict, fields: dict, world: str = "", style_anchor: str = "") -> str:
    """横版设定板（走共享模板 build_char，保证版式口径唯一）。"""
    design = {"anchor": fields["识别锚"], "contrast": fields["差异对照"],
              "palette": c["garment"].split("；")[0] + "。",
              "exclude": fields["反默认"], "world": world}
    return build_char(_item(c, fields), design=design)


def maincard_prompt(c: dict, fields: dict, world: str = "", style_style: str = "") -> str:
    """正面 3/4 全身主卡：3D 轨首帧锚点直接用它（单视角、干净背景、无排版）。"""
    f = fields
    return "\n".join(x for x in [
        "一张**竖版角色主卡**（单视角角色定妆图），%s，电影级写实 3D CG 渲染，实拍级质感；"
        "画面里**只有这一个角色**，全身入画、从头顶到鞋底完整。" % (world or "当代中国都市题材"),
        "【唯一识别锚｜先读这一条】%s" % f["识别锚"],
        "【形象】%s" % f["形象定位"],
        "【面部特征】%s" % f["面部特征"],
        "【表情】%s" % f["表情"],
        "【服装与配饰】%s" % f["服装细节"],
        "【差异化】%s" % f["差异对照"],
        "【镜头与站位】3/4 侧身面向镜头、正面偏向画面左侧约 30°；85mm 焦段、平视略低机位；"
        "全身入画、正常人体比例；大面积纯色干净底、无道具、无环境；柔光主光 + 极弱轮廓光。",
        "【禁止项】画面里不出现第二个人、不出现文字与编号、不出现边框与排版、不出现道具与场景；"
        "%s" % f["反默认"],
    ] if x)


def headshot_prompt(c: dict, fields: dict, world: str = "") -> str:
    """半身胸像（选角/定妆用）：只验脸，不带排版。"""
    f = fields
    return "\n".join(x for x in [
        "一张**半身胸像**定妆照，%s，电影级写实 3D CG 渲染，实拍级质感；单一角色、胸线以上取景。"
        % (world or "当代中国都市题材"),
        "【唯一识别锚】%s" % f["识别锚"],
        "【面部特征】%s" % f["面部特征"],
        "【表情】%s" % f["表情"],
        "【服装领口】%s" % f["服装细节"],
        "【镜头】正面偏 3/4、85mm、平视；中灰色干净背景、柔光打面；重点刻画面部结构与皮肤纹理。",
        "【禁止项】不出现第二个人、不出现文字、不出现排版与色卡；%s" % f["反默认"],
    ] if x)


# ===========================================================================
# 五、差异矩阵与硬规则
# ===========================================================================
def matrix(bible: dict) -> dict:
    """两两对照矩阵 + 规则判定（纯数值，供 check 与人读 md 共用）。"""
    chars = bible["characters"]
    pairs = []
    for i in range(len(chars)):
        for j in range(i + 1, len(chars)):
            a, b = chars[i], chars[j]
            fd = _face_distance(a, b)
            gap = _hue_gap(a["color"]["hue"], b["color"]["hue"])
            same_faction = a["faction"] == b["faction"]
            pairs.append({
                "a": a["name"], "b": b["name"], "face_distance": round(fd, 3),
                "diff_slots": [k for k in SLOTS if a["face"]["slots"][k] != b["face"]["slots"][k]],
                "hue_gap": round(gap, 1), "same_faction": same_faction,
                "same_hair": a["hair"]["id"] == b["hair"]["id"],
                "same_anchor": a["anchor"]["id"] == b["anchor"]["id"],
                "light_gap": round(abs(a["color"]["l"] - b["color"]["l"]), 2),
                "a_neutral": a["color"].get("s", 1.0) < NEUTRAL_S,
                "b_neutral": b["color"].get("s", 1.0) < NEUTRAL_S,
            })
    return {"pairs": pairs}


def check_rules(bible: dict) -> list:
    """六条硬规则 → [(level, code, msg)]。level ∈ hard/warn。"""
    chars = bible["characters"]
    out = []
    pairs = (bible.get("_matrix") or matrix(bible))["pairs"]
    leads = [c["name"] for c in chars if c.get("tier") == "lead"]
    # R1 任意两角色面部距离 ≥ 0.50
    for p in pairs:
        if p["face_distance"] < 0.50:
            out.append(("hard", "R1", "%s ↔ %s 面部距离 %.2f < 0.50（相同槽位：%s）"
                        % (p["a"], p["b"], p["face_distance"],
                           "、".join(k for k in SLOTS if k not in p["diff_slots"]) or "全同")))
    # R2 主角 vs 其他 ≥ 0.625
    for p in pairs:
        if (p["a"] in leads or p["b"] in leads) and p["face_distance"] < 0.625:
            out.append(("hard", "R2", "主角 %s ↔ %s 面部距离 %.2f < 0.625"
                        % (p["a"] if p["a"] in leads else p["b"], p["b"] if p["a"] in leads else p["a"],
                           p["face_distance"])))
    # R3 不同阵营色相间隔 ≥ 30°（中性色对按明度差 ≥ 0.10 判定）
    for p in pairs:
        neutral = p.get("a_neutral") or p.get("b_neutral")
        if not p["same_faction"] and not neutral and p["hue_gap"] < 30:
            out.append(("hard", "R3", "%s ↔ %s 色相间隔 %.0f° < 30°" % (p["a"], p["b"], p["hue_gap"])))
        if not p["same_faction"] and neutral and p["light_gap"] < 0.10:
            out.append(("hard", "R3", "%s ↔ %s 为中性色且明度差 %.2f < 0.10"
                        % (p["a"], p["b"], p["light_gap"])))
        if p["same_faction"] and p["hue_gap"] <= 12 and p["light_gap"] < 0.10:
            out.append(("warn", "R3*", "%s ↔ %s 同阵营且明度差 %.2f < 0.10，家族内也难分"
                        % (p["a"], p["b"], p["light_gap"])))
    # R4 识别锚唯一
    seen = {}
    for c in chars:
        seen.setdefault(c["anchor"]["id"], []).append(c["name"])
    for aid, names in seen.items():
        if len(names) > 1:
            out.append(("hard", "R4", "识别锚 %s 被多人共用：%s" % (aid, "、".join(names))))
    # R5 主演/配演发型不重复
    hair_map = {}
    for c in chars:
        hair_map.setdefault(c["hair"]["id"], []).append((c["name"], c.get("tier")))
    for hid, items in hair_map.items():
        big = [n for n, t in items if t in ("lead", "support")]
        if len(big) > 1:
            out.append(("hard", "R5", "发型 %s 被主演/配演重复使用：%s" % (hid, "、".join(big))))
        elif len(items) > 1:
            out.append(("warn", "R5*", "发型 %s 被群演复用：%s" % (hid, "、".join(n for n, _ in items))))
    # R6 文案不得含评价性美颜词
    for c in chars:
        blob = " ".join([c.get("garment", ""), c.get("expression", ""), c.get("contrast", ""),
                         c["face"]["detail"], c["face"]["forbid"]])
        hit = [w for w in BANNED_WORDS if w in blob]
        if hit:
            out.append(("hard", "R6", "%s 文案含评价性美颜词：%s" % (c["name"], "、".join(hit))))
    return out


def _ok_note(bible: dict) -> str:
    chars = bible["characters"]
    pairs = (bible.get("_matrix") or matrix(bible))["pairs"]
    if not pairs:
        return "只有一个角色，无对照项"
    fd = [p["face_distance"] for p in pairs]
    hg = [p["hue_gap"] for p in pairs if not p["same_faction"]]
    return ("%d 个角色 / %d 对；面部距离 min %.2f / 均值 %.2f；跨阵营色相间隔 min %s"
            % (len(chars), len(pairs), min(fd), sum(fd) / len(fd),
               ("%.0f°" % min(hg)) if hg else "—"))


# ===========================================================================
# 六、产出文件
# ===========================================================================
def render_matrix_md(bible: dict, issues: list) -> str:
    chars = bible["characters"]
    pairs = bible["_matrix"]["pairs"]
    L = ["# 角色差异化矩阵", "",
         "> 由 `character_design.py` 生成，勿手改。seed=`%s`，词库版本 `%s`。" % (bible["seed"], bible["lib_version"]),
         "", "## 一、逐角色签名", "",
         "| # | 角色 | 层级 | 年龄 | 人群桶 | 骨相 | 发型 | 主色（色相） | 识别锚 | 体态 |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for i, c in enumerate(chars, 1):
        L.append("| %d | %s | %s | %d | %s | %s | %s | %s（%.0f°） | %s | %s |"
                 % (i, c["name"], c["tier"], c["age"], c["persona"], c["face"]["name"], c["hair"]["name"],
                    c["color"]["name"], c["color"]["hue"], c["anchor"]["text"][:14] + "…",
                    c["posture"]["posture"][:12] + "…"))
    L += ["", "## 二、两两对照（面部七槽距离 / 色相间隔）", "",
          "| 角色 A | 角色 B | 面部距离 | 不同槽位 | 色相间隔 | 判定 |", "|---|---|---|---|---|---|"]
    for p in pairs:
        verdict = "PASS" if (p["face_distance"] >= 0.50 and (p["hue_gap"] >= 30 or p["same_faction"])) else "FAIL"
        L.append("| %s | %s | %.2f | %s | %.0f°%s | %s |"
                 % (p["a"], p["b"], p["face_distance"], "、".join(p["diff_slots"]) or "无",
                    p["hue_gap"], "（同阵营）" if p["same_faction"] else "", verdict))
    L += ["", "## 三、规则判定", ""]
    if issues:
        L += ["| 级别 | 规则 | 说明 |", "|---|---|---|"]
        for lv, code, msg in issues:
            L.append("| %s | %s | %s |" % ("HARD" if lv == "hard" else "warn", code, msg))
    else:
        L.append("六条硬规则全部通过：%s" % _ok_note(bible))
    L += ["", "## 四、口径说明", "",
          "- **面部距离** = 七槽签名（脸型 / 中庭 / 下颌 / 眉 / 眼 / 鼻 / 唇）中不同的比例；0.50 = 至少四槽不同。",
          "- **同阵营**不要求色相拉开，但要求明度差 ≥ 0.10（家族相似而不撞人）。",
          "- 距离是**下限保障**，不是审美目标：真实拍摄里服饰、体态、光影仍要各自成立。",
          ""]
    return "\n".join(L)


def render_asset_md(bible: dict, prompts: dict) -> str:
    """`# 一、角色资产库` 格式，可直接被 gen_char_assets.py / asset_md.py 解析。"""
    L = ["# 一、角色资产库", "",
         "> 由 `character_design.py` 生成（seed=`%s`）；每节 ``` 内为**设定板**提示词，"
         "可直接 `gen_char_assets.py --dry-run` 预览。" % bible["seed"], ""]
    for i, c in enumerate(bible["characters"], 1):
        L += ["## %d. %s（%s·%s）" % (i, c["name"], c["identity"] or c["tier"], c["persona"]), "",
              "**基础造型**", "```", prompts[c["name"]]["board"], "```", ""]
    return "\n".join(L)


def emit(bible: dict, out_dir: pathlib.Path, variants=("board", "maincard", "headshot")) -> dict:
    """落盘：bible / 矩阵 md / 资产提示词 md / 逐角色提示词。返回写出的文件表。"""
    world = bible["world"]
    style_anchor = bible["style_anchor"]
    prompts, files = {}, []
    for i, c in enumerate(bible["characters"], 1):
        fields = to_fields(c, style_anchor)
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
    for i, c in enumerate(bible["characters"], 1):
        for v in variants:
            p = out_dir / "prompts" / "char" / ("CH%02d_%s_%s.txt" % (i, c["name"], v))
            _write(p, prompts[c["name"]][v])
            files.append(str(p.relative_to(out_dir)))
    return {"files": files, "issues": issues, "fields": {k: v["_fields"] for k, v in prompts.items()}}


# ===========================================================================
# 七、老项目体检（audit）：扫既有资产提示词 md
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
    "锚": {"泪痣": ("泪痣",), "疤": ("疤",), "胎记": ("胎记",), "痣": ("痣",),
           "眼镜": ("眼镜",), "耳饰": ("耳钉", "耳环", "耳夹"), "戒指": ("戒指",),
           "手表": ("手表",), "项链": ("项链", "锁骨链"), "纹身": ("纹身",)},
    "色": {"黑": ("黑色", "纯黑", "深黑"), "白": ("白色", "纯白", "米白"), "灰": ("灰",),
           "藏青": ("藏青", "深蓝"), "酒红": ("酒红", "暗红", "枣红"), "墨绿": ("墨绿", "橄榄"),
           "驼棕": ("驼色", "棕色", "卡其", "咖啡"), "红": ("红色", "正红", "朱红", "红油", "辣油")},
}

# 认 `## 1. 名字` / `### 1. 名字` / `### 5b. 名字`（老项目的资产提示词 md 三种写法都有）
_SEC_RE = re.compile(r"^#{2,3}\s*(\d+)[a-z]?\s*[.、]\s*(.+?)\s*$", re.M)
_FENCE_RE = re.compile(r"```(.*?)```", re.S)


def _char_block(text: str) -> str:
    """切出「角色」章节：标题含「角色」且含「资产/提示词」，到下一个标题含「场景」为止。

    老项目写法不统一（`# 一、角色资产库` / `## 一、角色定妆提示词`），
    但都满足「标题里同时有角色 + 资产/提示词」，因此按语义切而不是按固定串切。
    """
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
        if "变体" in title:                      # `2b. 申雅莱 · 狼狈变体` 是同一角色的变体，不单列
            variants += 1
            continue
        prompts = "\n".join(_FENCE_RE.findall(body)) or body   # 老项目直接写段落、无代码块
        name = re.split(r"[（(]", title)[0].strip()
        # 只留「描述角色的子句」：剔掉棚拍/背景/镜头这类**全剧共用**的技术句，
        # 否则「浅灰色棚拍背景」会让所有角色撞色（实测把 7 个角色判成同色）
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
    # 两两冲突
    conflicts = []
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            a, b = rows[i], rows[j]
            same = {}
            for dim in ("脸型", "眉", "眼", "发型", "色"):
                inter = set(a["hits"][dim]) & set(b["hits"][dim])
                if inter:
                    same[dim] = sorted(inter)
            # 记分 = 撞车的**维度数**（不是颜色个数），避免「白/黑」把分数灌高
            score = len(same)
            if score >= 3:
                conflicts.append({"a": a["name"], "b": b["name"], "same": same, "score": score})
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
# 八、CLI
# ===========================================================================
def _load(p: str) -> dict:
    path = pathlib.Path(p)
    if not path.is_file():
        raise SystemExit("[FAIL] 文件不存在：%s" % path)
    return json.loads(path.read_text(encoding="utf-8"))


def _template() -> dict:
    return {
        "_note": "角色名册模板：只需给身份与性格，视觉参数由 character_design.py 分配；"
                 "确有必要时用 overrides 指定并接受校验。",
        "world": "当代韩国首尔·财阀高中",
        "region": "east_asian",
        "style_lock": "3D-manhua-cel",
        "style_anchor": "电影级写实 3D CG 渲染，实拍级质感，PBR 物理材质",
        "seed": "solodrama",
        "characters": [
            {"name": "楚湘", "gender": "f", "age": 18, "tier": "lead", "identity": "转校生",
             "faction": "外来者", "persona": ["野性", "不驯", "天不怕地不怕"],
             "overrides": {"anchor": "磨损编织绳", "hair": "高蓬松马尾"}},
            {"name": "申雅莱", "gender": "f", "age": 18, "tier": "support", "identity": "财阀大小姐",
             "faction": "财阀", "persona": ["心机", "傲慢", "两面"]},
            {"name": "具承贤", "gender": "m", "age": 19, "tier": "support", "identity": "财阀太子爷",
             "faction": "财阀", "persona": ["疏离", "病弱", "厌世"]},
            {"name": "教导主任", "gender": "m", "age": 52, "tier": "minor", "identity": "教导主任",
             "faction": "学校", "persona": ["强势", "势利"]}
        ],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="角色差异化设计器（同剧组不撞脸；纯标准库、零网络）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("plan", help="名册 → 角色圣经 + 三件套提示词 + 差异矩阵")
    p1.add_argument("--roster", required=True)
    p1.add_argument("--out", required=True, help="输出目录（建议 <项目>/04-资产/design）")
    p1.add_argument("--variants", default="board,maincard,headshot",
                    help="逐角色写出哪些提示词（逗号分隔）")
    p1.add_argument("--strict", action="store_true", help="硬规则不过也退出码 2")

    p2 = sub.add_parser("check", help="校验角色圣经的六条硬规则（退出码 2 = 不过）")
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
        res = emit(bible, out, variants)
        print("[OK] %d 个角色 → %s" % (len(bible["characters"]), out))
        for f in res["files"]:
            print("  · %s" % f)
        print()
        print(_ok_note(bible))
        hard = [x for x in res["issues"] if x[0] == "hard"]
        for lv, code, msg in res["issues"]:
            print("  [%s] %s %s" % ("HARD" if lv == "hard" else "warn", code, msg))
        if not res["issues"]:
            print("  六条硬规则全部通过")
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
        print("[OK] 六条硬规则通过；%s" % _ok_note(bible))
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
