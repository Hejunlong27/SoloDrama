#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_md2pack.py —— 创作层 Markdown → 引擎 pack 的机械转换

这套用例守的不是「转换器写得漂亮」，而是四条**一错就白跑一遍**的规则：

1. 模板写法不统一（`P01 名称` / `P01｜名称`；`服装卡提示词` / `**LOOK-A 立绘提示词**`），
   少认一种就会「资产识别成 0 条」——用户看到的是一份空的出图清单。
2. 台词只写名字，引擎只认代号；映射做不对，台词全被丢（成片没口型、没字幕时间轴）。
3. 输出被截断的镜头（缺 A 或 B 段）必须**跳过并报告**，不能塞进 pack —— 那会被 SHOT015 阻断，
   而错误信息指不到「截断」这个真因。
4. cast 引用了资产库里还没有的资产时：严格模式要**如实保留**（让校验拦），
   宽松模式才移除，且必须把越界的 `{{Mixed n}}` 一起摘掉（否则撞 SHOT016）。
"""
from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import md2pack  # noqa: E402

ASSETS_MD = """# 第1批／共4批｜人物卡

### P01｜崔昭（主角）

| 项 | 内容 |
|---|---|
| 身份 | 二十四岁，被逐出侯府的嫡女 |
| 一致性锚点 | ①左腕一道浅疤 ②发髻一根木簪 ③灰青窄袖 |

**三视图提示词**

```
2D-cel-webtoon turnaround, young woman, grey-green robe, front / side / back, 16:9
```

**表情四态**

```
2D-cel-webtoon expression sheet, four panels, calm / cold / tired / smile
```

| 状态码 | 名称 | 外观 | 使用集数 |
|---|---|---|---|
| LOOK-A | 归府素服 | 灰青窄袖交领长衫 | 1–9 |
| LOOK-B | 掌家装束 | 深青缎面长袄 | 10–19 |

**LOOK-A 立绘提示词**

```
2D-cel-webtoon full body, grey-green cross-collar robe, plain cloth belt, 9:16
```

### P02 柳氏

| 项 | 内容 |
|---|---|
| 身份 | 继母 |

**三视图提示词**

```
2D-cel-webtoon turnaround, older woman in dark red, front / side / back, 16:9
```

### S09｜角门

| 项 | 内容 |
|---|---|
| 用途 | 侯府角门，黄昏到夜 |

**空景卡提示词**

```
2D-cel-webtoon empty scene, courtyard side gate, weathered vermilion door, bluestone paving, dusk light, 9:16
```
"""

DIRECTOR_MD = """# 第01集导演手册｜第1批／共3批｜镜1–3

## 第二部分：本集镜头

| 镜号 | 镜头名 | 时间 | 时长 | 场景 |
|---|---|---|---|---|
| 1 | 三日盘缠 | 0:00–0:09 | 9s | S09 |
| 2 | 父亲给个数 | 0:09–0:18 | 9s | S09 |
| 3 | 三下敲门 | 0:18–0:25 | 7s | S09 |

### 镜 1

- **时长**：9s
- **参考图**：P01 崔昭 LOOK-A｜S09 角门
- **台词**：
  崔昭：父亲，三日盘缠。

**A段：分镜图提示词**
```
2D-cel-webtoon, medium shot, woman at courtyard gate, dusk
```

**B段：视频提示词**
```
subject_definitions:
<Picture 1> 是本镜分镜图（首帧构图锚点）：黄昏角门前的全景，崔昭立于门内侧。
<Subject 1> 是 <Picture 2> 中的崔昭：二十四岁，灰青窄袖交领长衫，发髻一支木簪，左腕一道浅疤。
<Subject 2> 是 <Picture 3> 中的角门：斑驳朱漆、半掩门扇、门外一条青石甬道。

summary:
[reference generation] 目标视频呈现 <Subject 1> 在 <Subject 2> 前停步、抬手叩门的两拍动作，参考图提供其形象与该门的结构。

retention_analysis:
<Subject 1>（出现于 [Shot 1]、[Shot 2]）：fully_preserved - 保留其灰青长衫、木簪与左腕浅疤。
<Subject 2>（出现于 [Shot 1]、[Shot 2]）：fully_preserved - 保留朱漆门扇、门环与青石甬道。
<Picture 1>（[Shot 1] 首帧）：partially_preserved - 保留机位与门内外的站位关系。

detailed_description:
目标视频为 2D-cel-webtoon 国漫质感，黄昏侧逆光，朱红与灰青对比，边缘留高光。
[Shot 1] 全景，平视机位，<Subject 1> 停在 <Subject 2> 前，右手抬起一半，指尖离门环半寸，肩线绷着；<Subject 2> 半掩的门扇在她身侧留出一道阴影。镜头固定，衣角被穿堂风掀起。
[Shot 2] At 00:04.000，切中景，景别收到胸口以上，<Subject 1> 抬眼看向门内，<Subject 1>（S1）说：<d>[Chinese] 父亲，三日盘缠。</d> 门内无人应声，她指尖落下，轻轻敲在门板上。

overall_soundscape:
黄昏风声穿过甬道，远处更鼓一响，衣料摩擦声。

non_diegetic_music:
N/A
```
```

### 镜 2

- **时长**：9s
- **参考图**：P01 崔昭 LOOK-A

**A段：分镜图提示词**
```
2D-cel-webtoon, close-up, she lifts the coin string
```

**B段：视频提示词**
```
subject_definitions:
<Picture 1> 是本镜分镜图（首帧构图锚点）：门内近景，崔昭半侧身。
<Subject 1> 是 <Picture 2> 中的崔昭：二十四岁，灰青窄袖交领长衫，发髻一支木簪。

summary:
[reference generation] 目标视频呈现 <Subject 1> 摊开掌心数铜钱、又攥紧的连续动作。

retention_analysis:
<Subject 1>（出现于 [Shot 1]）：fully_preserved - 保留面部、木簪与灰青长衫。
<Picture 1>（[Shot 1] 首帧）：partially_preserved - 保留机位与半侧身角度。

detailed_description:
2D-cel-webtoon 国漫质感，黄昏侧逆光，暖灰调。
[Shot 1] 近景，平视略俯，<Subject 1> 摊开掌心，几枚铜钱在指间滑动，铜面反出黄昏的暖光；随后五指一根根收拢，把钱攥进掌心，指节泛白。她垂着眼，嘴唇闭紧，没有开口。镜头轻微下压，背景门缝的光被压暗。

overall_soundscape:
铜钱相碰的清脆声，衣料摩擦声。

non_diegetic_music:
N/A
```
```

### 镜 3

- **时长**：7s
- **参考图**：P01 崔昭 LOOK-A

**A段：分镜图提示词**
```
2D-cel-webtoon, she raises her hand to knock
```

（这一镜的 B 段被截断了）
"""


# 老格式（2026-11 之前）：只用来守「`--drop-missing-cast` 在非六段式上仍能摘图号」，
# 六段式下这条路径会被明确拒绝（见 test_loose_mode_refuses_to_drop_on_six_section）。
LEGACY_DIRECTOR = """### 镜 1

- **时长**：6s
- **参考图**：P01 崔昭 LOOK-A｜S09 角门

**A段：分镜图提示词**
```
2D-cel-webtoon, medium shot, woman at courtyard gate, dusk
```

**B段：视频提示词**
```
资产图锚定：
角色 崔昭 的参考图是 {{Mixed 1}}
场景 S09 的参考图是 {{Mixed 2}}
```
"""


def _write(tmp_path, assets=ASSETS_MD, director=DIRECTOR_MD):
    ws = tmp_path / "proj"
    (ws / "00-创作" / "04-导演手册").mkdir(parents=True)
    (ws / "00-创作" / "02-资产库.md").write_text(assets, encoding="utf-8")
    if director:
        (ws / "00-创作" / "04-导演手册" / "第01集.md").write_text(director, encoding="utf-8")
    return ws


def test_parse_assets_handles_both_heading_styles():
    assets, gaps = md2pack.parse_assets(ASSETS_MD)
    ids = [a["id"] for a in assets["character"]]
    assert ids == ["P01", "P02"], ids
    p01 = assets["character"][0]
    assert p01["name"] == "崔昭", p01["name"]
    codes = {v["code"]: v["kind"] for v in p01["variants"]}
    assert codes == {"VIEW": "turnaround", "EXP": "expression", "LOOK-A": "look"}, codes
    # LOOK-B 没有提示词 → 不产出，记进缺口（不套用 LOOK-A 的提示词）
    assert any(g["id"] == "P01" and g["code"] == "LOOK-B" for g in gaps)


def test_parse_episode_maps_dialogue_by_name_and_skips_truncated():
    assets, _ = md2pack.parse_assets(ASSETS_MD)
    name2id = md2pack._name_map(assets)
    doc, gaps = md2pack.parse_episode(DIRECTOR_MD, 1, "9:16", name2id,
                                      known=md2pack._all_ids(assets), strict_cast=True)
    assert [s["id"] for s in doc["shots"]] == ["shot_001", "shot_002"], doc["shots"]
    assert doc["shots"][0]["dialogue"][0]["asset"] == "P01", doc["shots"][0]["dialogue"]
    assert doc["duration_total"] == 18
    assert any(g["shot"] == "shot_003" for g in gaps), gaps


def test_loose_mode_refuses_to_drop_on_six_section():
    """六段式下 `--drop-missing-cast` 必须**拒绝执行**，而不是悄悄改内容。

    六段里 `<Picture n>` 与 cast 顺序强绑定：摘掉一张图要连带重排全部
    `<Picture n>` / `<Subject n>`、删掉对应的 Subject 定义与 retention 行，
    而 `<Subject n>` 可能正被 `detailed_description` 引用 —— 机械重排会静默改语义。
    所以保留 cast，把问题交给门禁点名（宁可导入红一次，也不要出片后才发现人不对）。
    """
    assets, _ = md2pack.parse_assets(ASSETS_MD)
    doc, gaps = md2pack.parse_episode(DIRECTOR_MD, 1, "9:16", md2pack._name_map(assets),
                                      known={"P01", "P02"}, strict_cast=False)
    shot = doc["shots"][0]
    assert [c["asset"] for c in shot["cast"]] == ["P01", "S09"], shot["cast"]
    assert "<Picture 3>" in shot["video_prompt"]
    assert any("不能自动摘" in g["reason"] for g in gaps), gaps


def test_loose_mode_still_drops_on_legacy_prompt():
    """老格式（无六段）仍按原规则摘：cast 移除 S09，并把 {{Mixed 2}} 那行一起摘掉。

    这条路径只为「2026-11 之前写好的手册」保留；它们导入时会被 SHOT019 拦，
    但转换本身不能因为一个残缺的参考图就整包失败。
    注意：占位符无论新老格式都会被归一成 `<Picture n>`（H3 不认 `{{Mixed n}}`）。
    """
    assets, _ = md2pack.parse_assets(ASSETS_MD)
    doc, gaps = md2pack.parse_episode(LEGACY_DIRECTOR, 1, "9:16", md2pack._name_map(assets),
                                      known={"P01", "P02"}, strict_cast=False)
    shot = doc["shots"][0]
    assert [c["asset"] for c in shot["cast"]] == ["P01"], shot["cast"]
    assert "<Picture 2>" not in shot["video_prompt"], shot["video_prompt"]
    assert "<Picture 1>" in shot["video_prompt"], shot["video_prompt"]
    assert "{{Mixed" not in shot["video_prompt"]
    assert any("S09" in g["reason"] for g in gaps), gaps


def test_strict_mode_keeps_missing_cast():
    """默认严格：宁可让导入校验拦下（缺资产是事实），也不悄悄改内容。"""
    assets, _ = md2pack.parse_assets(ASSETS_MD)
    doc, _ = md2pack.parse_episode(DIRECTOR_MD, 1, "9:16", md2pack._name_map(assets),
                                   known={"P01", "P02"}, strict_cast=True)
    assert [c["asset"] for c in doc["shots"][0]["cast"]] == ["P01", "S09"]


def test_convert_writes_pack_and_validates(tmp_path):
    ws = _write(tmp_path)
    res = md2pack.convert(str(ws), strict_cast=False)
    assert res["ok"] and pathlib.Path(res["pack"], "pack.json").is_file()
    assert res["episodes"] and res["episodes"][0][1] == 2      # 2 个完整镜头
    assets = (pathlib.Path(res["pack"]) / "assets" / "characters.json").read_text(encoding="utf-8")
    assert '"kind": "turnaround"' in assets and '"kind": "look"' in assets
    report = pathlib.Path(res["report"]).read_text(encoding="utf-8")
    assert "分镜缺口" in report and "截断" in report


# ---------------------------------------------------------------------------
# 台词标记归一化（2026-11-06）：只动提示词，不动 dialogue
# ---------------------------------------------------------------------------
DIRECTOR_WITH_BARE = DIRECTOR_MD.replace(
    "<Subject 1>（S1）说：<d>[Chinese] 父亲，三日盘缠。</d>",
    '<Subject 1>（S1）说："父亲，三日盘缠。"',
)


def test_bare_dialogue_is_wrapped_in_prompt_only():
    """裸引号中文会被 H3 烧成画面字幕 → 转换时自动包 <d>；而 dialogue 数组必须保持纯净。"""
    assets, _ = md2pack.parse_assets(ASSETS_MD)
    doc, gaps = md2pack.parse_episode(DIRECTOR_WITH_BARE, 1, "9:16",
                                      md2pack._name_map(assets),
                                      known=md2pack._all_ids(assets), strict_cast=True)
    shot = doc["shots"][0]
    assert "<d>[Chinese] 父亲，三日盘缠。</d>" in shot["video_prompt"], shot["video_prompt"]
    assert '"父亲，三日盘缠。"' not in shot["video_prompt"], shot["video_prompt"]
    # ★ 台词数组是字幕对齐用的纯文本：套标记会让字幕里出现 `<d>[Chinese]`
    assert shot["dialogue"][0]["text"] == "父亲，三日盘缠。", shot["dialogue"]
    assert "<d>" not in shot["dialogue"][0]["text"]
    # 自动补标记必须留痕（用户要能回源改手册）
    assert any("台词已自动包" in g["reason"] for g in gaps), gaps


def test_dialogue_lang_follows_argument():
    assets, _ = md2pack.parse_assets(ASSETS_MD)
    doc, _ = md2pack.parse_episode(DIRECTOR_WITH_BARE, 1, "9:16",
                                   md2pack._name_map(assets),
                                   known=md2pack._all_ids(assets), lang="Spanish")
    assert "<d>[Spanish] 父亲，三日盘缠。</d>" in doc["shots"][0]["video_prompt"]


# ---------------------------------------------------------------------------
# 画幅：不许写死 9:16（横屏项目会被按竖屏出资产卡与分镜图）
# ---------------------------------------------------------------------------
def test_converted_pack_passes_h3_gate(tmp_path):
    """端到端：按模板写出来的手册 → convert → **导入门禁必须全绿**。

    这条是「锁定」的闭环证据：只测 md2pack 的输出字段，测不出「六段式写得对不对」；
    只有真的过一遍 `pack_spec`，才能证明模板教出来的东西导入器认。
    """
    ws = _write(tmp_path)
    res = md2pack.convert(str(ws), style_lock="2D-cel-webtoon，电影级 2.5D 质感，黄昏侧逆光")
    _pack, _assets, _eps, rep = md2pack.S.load_pack(res["pack"])
    assert rep.ok, rep.render()


def test_aspect_defaults_match_pack_spec():
    """默认画幅必须与 `pack_spec.DEFAULT_ASPECT` 同源 —— 两处各写一份必然漂。"""
    assert md2pack.S.DEFAULT_ASPECT["character"] == "16:9"
    assert md2pack.S.DEFAULT_ASPECT["scene"] == "9:16"
    assert md2pack.S.DEFAULT_ASPECT["video"] == "9:16"


def test_aspect_written_from_drama_json(tmp_path):
    """`drama.json` 的 format.aspect 是横屏 → pack.json 里人物/场景/分镜/出片都跟它走。"""
    ws = _write(tmp_path)
    (ws / "drama.json").write_text(json.dumps(
        {"format": {"aspect": "16:9"}}, ensure_ascii=False), encoding="utf-8")
    res = md2pack.convert(str(ws), strict_cast=False)
    asp = json.loads((pathlib.Path(res["pack"]) / "pack.json").read_text(encoding="utf-8"))["aspect"]
    assert asp["video"] == "16:9" and asp["board"] == "16:9", asp
    assert asp["character"] == "16:9" and asp["scene"] == "16:9", asp
    assert asp["prop"] == "1:1", "道具卡保持方图：特写易裁，构图余量更大"


def test_aspect_explicit_argument_wins(tmp_path):
    ws = _write(tmp_path)
    (ws / "drama.json").write_text(json.dumps({"format": {"aspect": "16:9"}}), encoding="utf-8")
    res = md2pack.convert(str(ws), strict_cast=False, aspect="3:4")
    asp = json.loads((pathlib.Path(res["pack"]) / "pack.json").read_text(encoding="utf-8"))["aspect"]
    assert asp["video"] == "3:4", asp
