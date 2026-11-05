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
资产图锚定：
角色 崔昭 的参考图是 {{Mixed 1}}
场景 S09 的参考图是 {{Mixed 2}}
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
角色 崔昭 的参考图是 {{Mixed 1}}
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


def test_loose_mode_drops_missing_cast_and_mixed_refs():
    """资产库只有人物时：cast 移除 S09，并把 {{Mixed 2}} 那行一起摘掉。"""
    assets, _ = md2pack.parse_assets(ASSETS_MD)
    name2id = md2pack._name_map(assets)
    doc, gaps = md2pack.parse_episode(DIRECTOR_MD, 1, "9:16", name2id,
                                      known={"P01", "P02"}, strict_cast=False)
    shot = doc["shots"][0]
    assert [c["asset"] for c in shot["cast"]] == ["P01"], shot["cast"]
    assert "{{Mixed 2}}" not in shot["video_prompt"], shot["video_prompt"]
    assert "{{Mixed 1}}" in shot["video_prompt"]
    assert any("S09" in g["reason"] for g in gaps)


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
