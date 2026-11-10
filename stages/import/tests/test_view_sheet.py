# -*- coding: utf-8 -*-
"""身份卡提示词改写的结构守卫。

这个工具会改**用户已经写好的创作稿**，所以它比只读工具更需要测试。
守三件事：

1. 改写后必须过 13 项结构自检（画幅 / 三视图 / 90° / 2×2 / 四种表情 / 两条禁止项）；
2. 角色身份与服装**必须原样保留** —— 丢了「24 岁拉丁女性、灰蓝工作服」，
   三视图就会出成另一个人；
3. 只动 VIEW / EXP 两个块，造型（LOOK-*）与正文表格一个字符都不许变。

```bash
python -m pytest stages/import/tests/test_view_sheet.py -q
```
"""
from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import view_sheet as V  # noqa: E402

OLD_VIEW = ("Character turnaround sheet of a 24-year-old Latina woman, front view, "
            "three-quarter side view and back view stacked vertically in one tall 9:16 frame, "
            "wearing a slate-blue heavy cotton work uniform, white apron with two faded coffee "
            "stains, dark non-slip shoes, warm brown skin, dark hair pulled back, "
            "full body, plain studio background, no text")

OLD_EXP = ("Four-expression head-and-shoulders sheet of the same 24-year-old Latina woman "
           "in a slate-blue work uniform, chest-up framing, 9:16 vertical, 2x2 grid, "
           "neutral, smiling, angry, surprised")

MD = """# 全季资产库 · 人物

## 一、人物

### P01｜Elena

| 项 | 内容 |
|---|---|
| 身份 | 24 岁，庄园佣人 |
| 一致性锚点 | ① 左眉内侧细疤 ② 右耳垂小痣 |

**LOOK-A 立绘提示词**
```
9:16 vertical full-body character reference plate, single subject centered, 24-year-old Latina
```

**三视图**
```
%s
```

**表情四态**
```
%s
```
""" % (OLD_VIEW, OLD_EXP)


def test_rewrite_passes_structural_check():
    out, changes, failures = V.rewrite_md(MD)
    assert not failures, "改写结果没过自检：%s" % failures
    m = V._VIEW_BLOCK.search(out)
    assert m, "改写后找不到三视图块"
    assert V.check(m.group(2)) == []


def test_keeps_identity_and_costume():
    """身份与服装不能被改写丢掉 —— 丢了就出成另一个人。"""
    out, _c, _f = V.rewrite_md(MD)
    body = V._VIEW_BLOCK.search(out).group(2)
    assert "24-year-old Latina woman" in body
    assert "slate-blue heavy cotton work uniform" in body
    assert "white apron" in body


def test_drops_old_framing_wording():
    """旧的 9:16 / 纵向堆叠 / 3/4 侧必须被清掉，否则新旧措辞并存，模型只听到一半。"""
    out, _c, _f = V.rewrite_md(MD)
    body = V._VIEW_BLOCK.search(out).group(2).lower()
    assert "stacked vertically" not in body
    assert "three-quarter side" not in body
    assert "9:16" not in body


def test_does_not_touch_look_or_tables():
    """造型提示词与正文表格必须逐字不变。"""
    out, _c, _f = V.rewrite_md(MD)
    assert "**LOOK-A 立绘提示词**" in out
    assert "9:16 vertical full-body character reference plate, single subject centered" in out
    assert "| 一致性锚点 | ① 左眉内侧细疤 ② 右耳垂小痣 |" in out


def test_exp_block_marked_as_merged():
    """表情块不删（保留文案语境），但要标明已并入身份卡、不再单独出图。"""
    out, _c, _f = V.rewrite_md(MD)
    m = V._EXP_BLOCK.search(out)
    assert m, "表情块被整块删掉了；应保留并标注已合并"
    assert "已并入" in m.group(2)
    assert "原提示词" in m.group(2)


def test_check_rejects_missing_pieces():
    """自检本身要能拦住缺项，否则它只是装饰。"""
    bad = "16:9 horizontal composition, front view, back view"
    miss = V.check(bad)
    assert "严格90度侧面" in miss
    assert "2x2四宫格" in miss
    assert "右侧40%" in miss


def test_style_prefix_is_prepended():
    out, _c, _f = V.rewrite_md(MD, style="当代真人短剧质感")
    body = V._VIEW_BLOCK.search(out).group(2)
    assert body.startswith("当代真人短剧质感")
