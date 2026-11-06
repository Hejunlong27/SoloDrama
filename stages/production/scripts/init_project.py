#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""init_project.py —— 建一个符合七环节布局的空项目（结构 + 模板，不写内容）

它解决什么
----------
在这之前，开一部新剧要手工做这些事：建 9 个阶段目录、手写 `layout.json`、
手写 `video-pipeline/config.local.json` 的 3 个覆盖键、抄一份 roster、抄一份分镜骨架。
漏一个就会出现「引擎去 `video-pipeline/data/` 找、布局却写在 `06-提示词/`」这类错位——
而这正是 V0.7.32 之前反复踩的坑。

结构部分**不在这里重写**：目录、README、`layout.json`、`config.local.json`
全部由 `stages/_layout.py::scaffold()` 产出（布局唯一真源）。本脚本只做两件事：
调 scaffold，然后写「内容模板」。

模板是**空的，不是范例**
------------------------
这一点很关键：模板里如果一个 `[SC-01]` 都没有，`drama next` 就会停在
`script.episode` 并说「没有 [SC-nn] 镜头」——那正是「还没写」该有的样子。
如果模板里塞一个能解析的示例镜，`next` 会以为这集写完了，
人就得靠肉眼分辨「这是示例还是真的」。**空模板的失败比示例模板的通过更有用。**

用法
----
    # 干跑：只打印将创建什么
    python stages/production/scripts/init_project.py --workspace "D:/剧/新剧" --title "剧名" --dry-run

    # 真建
    python stages/production/scripts/init_project.py --workspace "D:/剧/新剧" \
        --title "Ninety Days, Mr. Nobody" --platform ReelShort --episodes 30 --ep-seconds 60

    # 也可以走 drama 入口
    python stages/production/scripts/drama.py init --workspace "D:/剧/新剧" --title "剧名"

产物
----
    <ws>/layout.json                        （由 scaffold 写，布局真源）
    <ws>/01-调研 … 09-发行/                  （9 个阶段目录 + README）
    <ws>/04-资产/{characters,scenes,props}/  （资产子目录）
    <ws>/video-pipeline/config.local.json   （data_dir/out_dir/assets_dir 回填）
    <ws>/drama.json                         ← 四维档案（format 待确认）
    <ws>/04-资产/design/roster.json          ← 名册模板（2 个占位角色）
    <ws>/04-资产/refs.json                   ← 空结构
    <ws>/03-剧本/blueprint.md                ← 蓝图骨架
    <ws>/03-剧本/ep_01.md                    ← FFS 骨架（**不含镜头**）
    <ws>/05-分镜/ep01_storyboard.md          ← 5 字段骨架（**不含镜**）

纪律
----
1. **不覆盖已有文件**（加 `--force` 才覆盖）。重跑 init 是安全的幂等操作。
2. **不写内容**：标题、平台、集数写进 `drama.json`，但剧本/分镜/名册一律留空待填。
3. 不猜 look：`--look` 不给就留空，`drama next` 会提示去选。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[union-attr]
except Exception:                                                # noqa: BLE001
    pass

HERE = pathlib.Path(__file__).resolve().parent
# `parents[0]`=production/scripts 的上层… 逐层：HERE=…/stages/production/scripts，
#   parents[0]=…/stages/production, [1]=…/stages, [2]=仓库根
# ★ 这个下标在本仓库已经错四次了（gen_boards / nodes / main / 这里）。
#   所以这里不靠数数，而是**断言找到 stages/_layout.py 才算对**。
ROOT = HERE.parents[2]
if not (ROOT / "stages" / "_layout.py").is_file():
    raise SystemExit("[FAIL] 仓库根定位失败：%s 下没有 stages/_layout.py" % ROOT)
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "stages"))

# ★ 刻意**不** import `_ws`：它在 import 期就会解析工作区，找不到直接 SystemExit。
#   而 init 的职责正是「让工作区存在」——建项目的脚本不能依赖「项目已存在」的模块。
import _layout as L                          # noqa: E402

# 只写这些键，其余交给 scaffold
TRACKS_FILE = ROOT / "configs" / "tracks.json"
LOOKS_FILE = ROOT / "configs" / "looks.json"


def _read_json(p: pathlib.Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8-sig")) if p.is_file() else default
    except Exception:                                            # noqa: BLE001
        return default


def _write(p: pathlib.Path, text: str, force: bool) -> bool:
    """→ 是否真的写了。已存在且没 --force 就跳过（幂等）。"""
    if p.exists() and not force:
        return False
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text if text.endswith("\n") else text + "\n",
                 encoding="utf-8", newline="")
    return True


# ===========================================================================
# 模板
# ===========================================================================
def _drama_json(a, ep: str) -> dict:
    return {
        "_note": "四维档案：形态 track / 视觉 look / 叙事 narrative / 画幅 aspect 相互正交。"
                 "改这里等价于改全剧设定；`drama do asset.prompt` 之前必须确认。",
        "format": {
            "track": a.track,
            "look": a.look or "",
            "narrative": a.narrative,
            "aspect": a.aspect,
        },
        "episodes": {"count": int(a.episodes), "seconds": int(a.ep_seconds)},
        "channel": {
            "image": {"engine": a.image_engine, "capability": ""},
            "video": {"engine": a.video_engine, "capability": ""},
        },
        "confirmed": {"format_at": "", "channel_at": ""},
    }


def _roster(a) -> dict:
    note = ("名册模板：填**身份**与必要的 overrides 即可。\n"
            "视觉参数（色签名/发型/锚）按 docs/assets/角色差异化设计规范.md 的六维签名分配 ——\n"
            "该文档里的 character_design.py 已于 2026-11 移除，方法照用、命令不跑。\n"
            "不设锚写 \"anchor\": \"none\"。下面两个是**占位角色**，替换成你自己的；主演标 tier=lead。")
    return {
        "_note": note,
        "world": a.world,
        "region": a.region,
        "style_lock": a.track,
        "style_anchor": "",
        "seed": "",
        "characters": [
            {"name": "主角姓名", "code": "LEAD", "gender": "f", "age": 28, "tier": "lead",
             "identity": "一句话身份（职业/处境）", "faction": "主线",
             "overrides": {"expression": "一句话表情基调，别写「气质清冷」这种"}},
            {"name": "配角姓名", "code": "SUP", "gender": "m", "age": 35, "tier": "support",
             "identity": "一句话身份", "faction": "对手方"},
        ],
    }


BLUEPRINT_TMPL = """# 蓝图 · {title}

<!-- STATUS: DRAFT — 写完把这一行删掉，判据才认完成 -->

> 集数 {episodes} × {seconds} 秒；平台 {platform}；形态 `{track}`。
> 本文件由 `init_project.py` 生成，是**骨架不是内容** —— 下面每一节都要你自己写。

## 一、一句话卖点

（写一句：谁、在什么处境下、要做什么、赌注是什么。）

## 二、核心矛盾

- 表层冲突：
- 底层冲突：
- 为什么非解决不可：

## 三、主线节奏（分段）

| 段落 | 集号 | 发生什么 | 观众要得到什么 |
|---|---|---|---|
| 契约建立 | 1–5 |  |  |
| 第一次反噬 | 6–15 |  |  |
| 中段反转 | 16–25 |  |  |
| 收束 | 26–{episodes} |  |  |

## 四、角色关系

（谁与谁是什么关系、什么在变。）

## 五、每集钩子（一句话，先写前 3 集）

1.
2.
3.
"""


FFS_TMPL = """<!-- STATUS: DRAFT — 写完把这一行删掉，判据才认完成 -->
# TITLE: {title}
# EP: 01/{episodes}
# PLATFORM: {platform}
# STYLE LOCK: （一行风格锁，全剧恒定，禁止逐集改写）
# CHAR: LEAD: 一句话身份; SUP: 一句话身份
# SCENE: ROOM: 一句话空间描述

---

<!--
  骨架说明（写完请整段删掉）：

  1. 上面 6 行 HEADER 必须留着（TITLE / EP / PLATFORM / STYLE LOCK / CHAR / SCENE）。
  2. 下面的镜头块格式：

     [SC-01]
     CHAR: LEAD
     DUR: 8
     ACTION: 谁做了什么（写动作，不写情绪形容词）
     DIALOG: LEAD: 台词原文

  3. DUR 只能是 4–15 的整数；禁写 MOOD / CAMERA / EMOTION / MUSIC / LIGHT 字段。
  4. 台词单句：中文 ≤20 字 / 拉丁 ≤55 字符；一镜最多 2 句。
  5. **本文件此刻故意没有任何 [SC-nn]** —— 所以你跑 `drama next` 会停在这里，
     提示「没有镜头」。那是正常的：把镜头写进来，判据才会过。
-->
"""


STORYBOARD_TMPL = """# EP01 分镜 · {title}

<!-- STATUS: DRAFT — 写完把这一行删掉，判据才认完成 -->

> 形态 `{track}`｜单镜 4–15 秒整数｜1 镜 = 1 段视频
> 每镜 **5 个字段**：`duration` / `ratio` / `refs` / `board` / `prompt`

<!--
  骨架说明（写完请整段删掉）：

  1. `refs` 写参考图 key，**角色在前、场景在后**（顺序就是提示词里的 <Picture n>）：
       - refs: char_lead, char_sup, scene_room

  2. `board` 是**这一镜的分镜图**提示词 —— 单帧、与成片同构、竖版 9:16：
       它是构图锚（机位/光位/人物位置），不是身份锚。
       默认走本地文生图，￥0；人数由 refs 里的 char_* 自动算，不用你写「几个人」。

  3. `prompt` 是 H3 多参提示词，**六段式**（顺序固定）：
       subject_definitions / summary / retention_analysis /
       detailed_description / overall_soundscape / non_diegetic_music
       `<Picture 1>` 固定是分镜图，`<Picture 2>` 起按 refs 顺序排。编号**不会**被自动重排 ——
       写错只会表现为「模型把场景当成了人」。详见 docs/pack/H3-REF2VA-PROMPT.md。

  4. 已删字段（写了也没用，只会告警）：banana_prompt / crop / time。

  5. **本文件此刻故意没有镜头块** —— `drama next` 会停在 board.script 并提示缺字段。
-->

## shot_001

（按上面的格式写第一镜，然后删掉这行占位。字段齐了判据才会过。）
"""


REFS_TMPL = {
    "_note": "参考图登记表：key → 相对本文件所在目录（04-资产）的路径。"
             "出图后由 gen_assets_local.py / 手工补登；引擎按 key 取图。",
    "characters": {},
    "scenes": {},
    "props": {},
}


# ===========================================================================
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="建七环节空项目（结构 + 模板，不写内容）")
    ap.add_argument("--workspace", required=True, help="项目根目录（可以还不存在）")
    ap.add_argument("--title", default="未命名短剧")
    ap.add_argument("--platform", default="")
    ap.add_argument("--episodes", default=30, type=int)
    ap.add_argument("--ep-seconds", dest="ep_seconds", default=60, type=int)
    ap.add_argument("--track", default="",
                    help="形态：live_action / 2d_animation / 3d_manhua（默认取 tracks.json 第一个）")
    ap.add_argument("--look", default="", help="视觉 look id（不给就留空，待确认）")
    ap.add_argument("--narrative", default="dialogue", choices=["dialogue", "narration"])
    ap.add_argument("--aspect", default="9:16")
    ap.add_argument("--world", default="")
    ap.add_argument("--region", default="east_asian",
                    choices=["east_asian", "western", "south_asian", "latin"])
    ap.add_argument("--image-engine", dest="image_engine", default="local_comfyui",
                    choices=["local_comfyui", "runninghub"])
    ap.add_argument("--video-engine", dest="video_engine", default="local_comfyui",
                    choices=["local_comfyui", "runninghub"])
    ap.add_argument("--force", action="store_true", help="覆盖已有模板文件（默认跳过）")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    # 形态默认值：从 tracks.json 的 order 取第一个，不硬编码
    if not a.track:
        cfg = _read_json(TRACKS_FILE, {}) or {}
        a.track = str(cfg.get("default") or (cfg.get("order") or ["live_action"])[0])

    ws = pathlib.Path(a.workspace).expanduser().resolve()

    print("=" * 74)
    print("建项目骨架 · %s" % ws)
    print("=" * 74)
    print("  标题    : %s" % a.title)
    print("  规格    : %d 集 × %d 秒 ｜ 形态 %s ｜ 叙事 %s ｜ 画幅 %s"
          % (a.episodes, a.ep_seconds, a.track, a.narrative, a.aspect))
    print("  通道    : 图 %s ｜ 视频 %s" % (a.image_engine, a.video_engine))
    if not a.look:
        print("  [注意] 未指定 --look：视觉风格留空，`drama next` 会提示你去选")

    if a.dry_run:
        print("\n（干跑：未写盘。将创建 9 个阶段目录 + layout.json + config.local.json + 6 个模板文件）")
        return 0

    # ---- 1) 结构与布局：交给 _layout.scaffold（唯一真源，不重写一遍）----
    res = L.scaffold(ws)
    print("\n[结构] 9 个阶段目录 + layout.json + config.local.json")
    print("       layout → %s" % res["layout_file"])

    # ---- 2) 内容模板 ----
    ep = "ep01"
    files = {
        "drama.json": json.dumps(_drama_json(a, ep), ensure_ascii=False, indent=2),
        "04-资产/design/roster.json": json.dumps(_roster(a), ensure_ascii=False, indent=2),
        "04-资产/refs.json": json.dumps(REFS_TMPL, ensure_ascii=False, indent=2),
        "03-剧本/blueprint.md": BLUEPRINT_TMPL.format(
            title=a.title, episodes=a.episodes, seconds=a.ep_seconds,
            platform=a.platform or "（待填）", track=a.track),
        "03-剧本/ep_01.md": FFS_TMPL.format(
            title=a.title, episodes=a.episodes, platform=a.platform or "（待填）"),
        "05-分镜/ep01_storyboard.md": STORYBOARD_TMPL.format(title=a.title, track=a.track),
    }
    print("\n[模板]")
    wrote = skipped = 0
    for rel, text in files.items():
        p = ws / rel
        if _write(p, text, a.force):
            print("  + %s" % rel)
            wrote += 1
        else:
            print("  = %s（已存在，跳过）" % rel)
            skipped += 1

    # ---- 3) 下一步 ----
    print("\n" + "-" * 74)
    print("建好：新增 %d 个文件 / 跳过 %d 个（重跑安全，加 --force 才覆盖）" % (wrote, skipped))
    print("\n下一步（按顺序）：")
    print("  1. 选画风：   python stages/production/scripts/drama.py style list")
    print("                python stages/production/scripts/drama.py style set %s --look <id> --workspace \"%s\""
          % (a.track, ws))
    print("  2. 填名册：   %s" % (ws / "04-资产" / "design" / "roster.json"))
    print("  3. 写蓝图 + 第 1 集剧本：%s" % (ws / "03-剧本"))
    print("  4. 看还差什么：python stages/production/scripts/drama.py next --ep ep01 --workspace \"%s\""
          % ws)
    return 0


if __name__ == "__main__":
    sys.exit(main())
