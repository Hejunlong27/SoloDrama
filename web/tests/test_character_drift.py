#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""角色档案的「md ↔ pack 变体漂移」检测。

## 为什么需要

角色档案的**提示词**读 `00-创作/02-资产库.md`（人写的那份），
而**出图**只认 `<ws>/pack/assets/characters.json`（`gen_assets_local.assets_from_pack`）。

两边不同源。于是「改了 md 没重建 pack」时：

* 界面上看到的是新提示词；
* 点「重出这一张」时，引擎在包里按 `--only P01@LOOK-A` 查 —— 查不到就 `rc=2` 中止，
  或者（更糟）用包里那份**旧提示词**出图，出来的图跟眼前写的不一样，且不报错。

真实案例：`D:\\剧本\\海外剧\\10` 的 P12 —— md 有 `VIEW/LOOK-A/EXP`，包里只有 `BASE`。

这里只做**只读比对**并如实上报，不尝试自动同步（那是 `md2pack` 导入环节的职责）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "web"))

from core import characters  # noqa: E402

# 一份最小的资产库 md：一个角色、三个变体块。
# 格式照 `characters._parse_md` 的正则（`### P01 名字` + `**变体名**` + ``` 提示词块）。
MD = """# 资产库

## 一、角色资产库

### P01 ｜ Elena

**三视图**
```
character turnaround, front view
```

**LOOK-A 造型**
```
a woman in grey coat
```

**表情四态**
```
four expressions
```
"""


def _ws(tmp_path, pack_codes=None):
    ws = tmp_path / "剧"
    (ws / "00-创作").mkdir(parents=True)
    (ws / "layout.json").write_text("{}", encoding="utf-8")
    (ws / "00-创作" / "02-资产库.md").write_text(MD, encoding="utf-8")
    if pack_codes is not None:
        d = ws / "pack" / "assets"
        d.mkdir(parents=True)
        (d / "characters.json").write_text(json.dumps({
            "spec": "solodrama-assets/1",
            "items": [{"id": "P01", "name": "Elena",
                       "variants": [{"code": c, "label": c, "prompt": "x"} for c in pack_codes]}],
        }, ensure_ascii=False), encoding="utf-8")
    return ws


def test_no_pack_means_no_drift_noise(tmp_path):
    """没有制作包时不报漂移 —— 那时出图走的是老 md 通道，两边本来就是一份。"""
    d = characters.roster(_ws(tmp_path, None))
    assert d["pack_exists"] is False, d
    assert d["drift"] == [], d


def test_matching_codes_report_no_drift(tmp_path):
    d = characters.roster(_ws(tmp_path, ["VIEW", "LOOK-A", "EXP"]))
    assert d["pack_exists"] is True, d
    assert d["drift"] == [], "两边一致却报了漂移：%s" % d["drift"]


def test_md_only_variant_is_reported(tmp_path):
    """包里少一个变体 —— 点它的「重出」会在包里查不到，必须提前说。"""
    d = characters.roster(_ws(tmp_path, ["BASE"]))
    assert d["drift"] == ["P01"], d["drift"]
    p01 = d["items"][0]
    assert set(p01["drift"]["md_only"]) == {"VIEW", "LOOK-A", "EXP"}, p01["drift"]
    assert p01["drift"]["pack_only"] == ["BASE"], p01["drift"]


def test_pack_only_variant_is_reported(tmp_path):
    """包里多一个 md 没有的变体 —— 反向也要报（说明 pack 比 md 新，md 漏写了）。"""
    d = characters.roster(_ws(tmp_path, ["VIEW", "LOOK-A", "EXP", "LOOK-B"]))
    assert d["drift"] == ["P01"], d["drift"]
    assert d["items"][0]["drift"]["pack_only"] == ["LOOK-B"], d["items"][0]["drift"]
