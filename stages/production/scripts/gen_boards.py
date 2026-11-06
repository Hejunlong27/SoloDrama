#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""gen_boards.py —— 每镜一张分镜图（构图锚），喂给出片的第一张参考图

它解决的是什么
--------------
在它之前，出片只给「角色卡 + 场景卡」两三类参考图。这两张图的构图**都不是本镜的构图**：
角色卡是纯背景 3/4 站姿，场景卡是空房间。于是模型每一镜都在重新猜机位——
同一个会议室，在 shot_001 是俯拍、shot_002 变平视、shot_003 又贴着墙，
观众看到的是「空间在跳」，而不是「人在同一个空间里动」。

分镜图补的就是这一格：**与成片同构的 9:16 单帧画面**。它和视频同模态（都是摄影画面），
所以模型能直接读懂「这一镜长什么样」，不用猜。

它不是站位图
------------
2026-10-31 曾试过「俯视站位线稿」，结论是「对成片没有增益」——那个结论只对线稿成立：
线稿是**另一个模态**，模型会把它当画面内容复刻，而不是当构图指令。分镜图是摄影画面，
只提供构图、光位、人物位置，不含任何线稿语义。

它的边界：**只做构图锚，不做身份锚**
------------------------------------
人物长相对不对，由上片时喂的**角色卡**保证；分镜图里的人物只要「姿势与位置对」就行。
所以默认走**文生图**（不给角色卡），理由有两条：
1. 分镜图 240 张（30 集 × 8 镜），本地文生图 ￥0，走参考图编辑要上传 480 次；
2. 若分镜图长得太像角色卡，H3 会把「分镜图里那张脸」当成身份锚，
   反而与角色卡打架 —— 两头都像、又都不完全像，是最差的结果。
需要更贴脸时加 `--with-refs`，走本地图生图工作流（ref1=主角色，ref2=场景）。

用法
----
    # 干跑：只打印将生成的提示词与落点，不出图
    python stages/production/scripts/gen_boards.py --workspace "D:/剧/新剧" --ep ep01 --dry-run

    # 真出（本地 ComfyUI，需先起 8188）
    python stages/production/scripts/gen_boards.py --workspace "D:/剧/新剧" --ep ep01 --apply

    # 只补某几镜
    python stages/production/scripts/gen_boards.py --workspace "D:/剧/新剧" --ep ep01 --apply --only shot_003,shot_005

产物
----
    04-资产/boards/<ep>/<shot_id>.png        ← 9:16，与成片同构
    data/<ep>/boards.json                    ← 输入契约（由 convert_storyboard 生成）

纪律
----
1. **只读 boards.json 的 prompt**，不发明剧情。缺 board 的镜直接跳过并列出，不猜。
2. 人数从 `refs` 的 `char_*` 数量推出，**不写死** —— EP03/EP04 的事故就是写死「exactly one person」。
3. 一张图一镜，**绝不拼版**（九宫格/分镜表那种）—— 拼版会让模型把整张当一帧。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[union-attr]
except Exception:                                                # noqa: BLE001
    pass

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]                       # stages/production/scripts → 仓库根（parents[1] 是 stages）
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "stages" / "assets" / "comfyui"))

import _ws as W                              # noqa: E402
import _layout as L                          # noqa: E402

COMFY_CLIENT = ROOT / "stages" / "assets" / "comfyui" / "comfy_client.py"
WF_9x16 = ROOT / "stages" / "assets" / "comfyui" / "workflow_qwen21_t2i_hq_9x16.json"
WF_EDIT = ROOT / "stages" / "assets" / "comfyui" / "workflow_qwen21_edit.json"

# ---------------------------------------------------------------------------
# 提示词模板
# ---------------------------------------------------------------------------
# ★ 为什么「人数」要单独一段、且用英文写：H3 对 `[SUBJECT]` 里的人数极为敏感，
#   而中文人数（「两个人」）在英文提示词里权重太低。2026-11-01 的事故就是
#   模板写了 `exactly one person` 而画面里明明两个人 —— 这里按 refs 实算，绝不写死。
NUM_EN = {1: "exactly one person", 2: "exactly two people", 3: "exactly three people",
          4: "exactly four people", 5: "exactly five people"}

BOARD_TMPL = """\
【任务】一张**{orient_cn} {ratio} 电影静帧**，用作这一镜的构图参考。它是摄影画面，不是分镜表、不是线稿。
【构图】{board}
【人数】{people_line}
【人物】{cast_line}
【风格】{style_line}
【画面】single frame, {orient_en} {ratio}, cinematic still photograph, natural perspective, \
believable depth of field, photographic material truth, real skin texture, \
credible fabric wrinkles, no illustration look.
【光线】{light_line}
【禁止】no text, no letters, no numbers, no watermark, no logo, no captions, no subtitles,
no split screen, no collage, no grid, no storyboard layout, no panels, no border, no labels,
no arrows, no annotations, no second frame of the same person.
"""

# 分镜 md 里常写 `[LIGHT]` 段；这里只做「有就透传、没有就不编」。
_LIGHT_RE = re.compile(r"\[LIGHT\]\s*(.+)", re.I)


def _read_json(p: pathlib.Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8-sig")) if p.is_file() else default
    except Exception:                                                    # noqa: BLE001
        return default


def _specs_from_md(ws: pathlib.Path, ep: str) -> dict:
    """从分镜 md 抽 `{shot_id: {prompt, ratio, refs}}`。

    只认 5 字段里的 `board / ratio / refs` —— 与 `convert_storyboard` 的解析口径一致，
    但**不去读它的产物**（避免环节之间反向依赖）。
    """
    f = L.stage_dir(ws, "storyboard") / ("%s_storyboard.md" % ep)
    if not f.is_file():
        return {}
    text = f.read_text(encoding="utf-8", errors="replace")
    out = {}
    for block in re.split(r"(?m)^##\s+", text)[1:]:
        lines = block.split("\n")
        sid = lines[0].strip().split()[0] if lines else ""
        if not sid:
            continue
        body = "\n".join(lines[1:])
        m = re.search(r"(?m)^-\s*board:\s*\|\s*\n(.*?)(?=\n-\s|\n---|\Z)", body, re.S)
        if not m:
            continue
        buf = []
        for ln in m.group(1).split("\n"):
            if ln.startswith(("    ", "\t")):
                buf.append(ln[4:] if ln.startswith("    ") else ln.lstrip("\t"))
            elif not ln.strip() and buf:
                buf.append("")
            elif ln.strip():
                break
        prompt = "\n".join(buf).strip()
        if not prompt:
            continue
        r = re.search(r"(?m)^-\s*ratio:\s*(\S+)", body)
        ref = re.search(r"(?m)^-\s*refs:\s*(.+)$", body)
        out[sid] = {"prompt": prompt,
                    "ratio": (r.group(1) if r else "9:16"),
                    "refs": [x.strip() for x in re.split(r"[,，、\s]+", ref.group(1)) if x.strip()]
                    if ref else []}
    return out


def _codes(refs, known=()) -> list:
    """从 refs 里挑出角色代号。三种写法都认：

        char_elle  → ELLE      （下划线 key，最常见）
        Character_Elle → ELLE
        ELLE       → ELLE      （直接写代号 —— 名册里就是这么写的，别只认带前缀的）

    场景 key（`scene_room`）不在 `known` 里，所以不会被误当成角色。
    不传 `known` 时退化为「只认前缀」，保持旧行为。
    """
    known_set = {str(k).upper() for k in (known or [])}
    out = []
    for r in refs or []:
        s = str(r).strip()
        low = s.lower()
        hit = None
        for pre in ("character_", "char_", "ch_"):
            if low.startswith(pre):
                hit = s[len(pre):].upper()
                break
        if hit is None and s.upper() in known_set:
            hit = s.upper()
        # 没有 character-bible 时（known 为空），裸代号 P01 也要能认成角色 ——
        # 否则人数会算成 0 再兜底成 1，两个人物的镜头会被写成「exactly one person」。
        if hit is None and re.fullmatch(r"P\d{2}", s, flags=re.I):
            hit = s.upper()
        if hit:
            out.append(hit)
    return out


def build_prompt(shot_id: str, spec: dict, bible: dict, style_line: str,
                 h3_prompt: str = "", ratio: str = "") -> tuple:
    """boards.json 的一条 → (完整提示词, 人数, 出场代号列表)。

    人数 = `refs` 里 char_* 的**实际个数**。这是硬约束：写死 1 人而画面两人，
    模型会把人裁掉一半或让第二个人变成背影，成片直接废。
    """
    refs = spec.get("refs") or []
    codes = _codes(refs, [c.get("code") for c in (bible.get("characters") or [])])
    n = len(codes) or 1
    people = NUM_EN.get(n, "exactly %d people" % n)

    # 画幅：分镜图是构图稿，必须跟交付画幅一致（2026-11-06：横屏项目曾被写死成 9:16）
    _ratio = (str(ratio or "").strip() or str(spec.get("ratio") or "").strip() or "9:16")
    _portrait = True
    try:
        _w, _h = [float(x) for x in _ratio.split(":")[:2]]
        _portrait = _w <= _h
    except (ValueError, IndexError):
        pass

    # 人物外观：从 character-bible 取「服装 + 主色 + 发型」一句话。
    # 不写长相细节 —— 分镜图不承担身份，写多了反而把角色卡挤掉。
    by_code = {}
    for c in (bible.get("characters") or []):
        by_code[str(c.get("code") or "").upper()] = c
    bits = []
    for code in codes:
        c = by_code.get(code)
        if not c:
            bits.append("%s (identity held by the character card, do not invent a face)" % code)
            continue
        bits.append("%s — %s; %s" % (
            code,
            str(c.get("garment_en") or "").strip().rstrip(".") or "wardrobe per character card",
            "%d-year-old %s" % (int(c.get("age") or 30),
                                "woman" if str(c.get("gender")) == "f" else "man")))
    cast_line = ("; ".join(bits) + ". Faces need only be plausible — identity is enforced "
                 "by the character reference cards, not by this frame.") if bits else \
                ("the location with nobody in it" if n == 0 else
                 "figures described only by the composition note above")

    light = ""
    m = _LIGHT_RE.search(h3_prompt or "")
    if m:
        light = m.group(1).strip().rstrip(".")
    light_line = (light + "; direction and source must read clearly") if light else \
        "one clear key source, direction readable, natural falloff"

    txt = BOARD_TMPL.format(
        board=str(spec.get("prompt") or "").strip(),
        people_line=("%s — nobody else in frame." % people) if n else "no people in frame.",
        cast_line=cast_line,
        style_line=style_line or "cinematic live-action photography",
        light_line=light_line,
        ratio=_ratio or "9:16",
        orient_cn=("横版" if _portrait is False else "竖版"),
        orient_en=("horizontal" if _portrait is False else "vertical"),
    )
    return txt, n, codes


def _style_line(ws: pathlib.Path) -> str:
    """取画风的 style_prompt：优先 drama.json，回退 style-plan.json。

    只取 look 的 prompt（题材视觉），不拼 track 的渲染流 —— 分镜图是构图稿，
    渲染风格交给上片时的 H3（那边已经有一份完整风格串）。
    """
    for name in ("drama.json", "style-plan.json"):
        d = _read_json(ws / name, None)
        if not isinstance(d, dict):
            continue
        if name == "drama.json":
            look = str((d.get("format") or {}).get("look") or "")
        else:
            look = str((d.get("style") or {}).get("look") or "")
        if not look:
            continue
        lib = _read_json(ROOT / "configs" / "looks.json", {}) or {}
        for it in lib.get("looks") or []:
            if it.get("id") == look:
                return str(it.get("prompt") or "")
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description="每镜一张分镜图（构图锚）")
    ap.add_argument("--workspace", default=None)
    ap.add_argument("--ep", required=True, help="集号，如 ep01")
    ap.add_argument("--apply", action="store_true", help="真出图（默认干跑）")
    ap.add_argument("--dry-run", action="store_true", help="只打印提示词（默认行为）")
    ap.add_argument("--only", default="", help="只做指定 shot_id，逗号分隔")
    ap.add_argument("--limit", type=int, default=0, help="只做前 N 镜")
    ap.add_argument("--force", action="store_true", help="已存在也重出")
    ap.add_argument("--with-refs", dest="with_refs", action="store_true",
                    help="走图生图（ref1=主角色卡，ref2=场景卡），更贴脸但更慢")
    ap.add_argument("--seed", type=int, default=None)
    a = ap.parse_args()

    ws = pathlib.Path(a.workspace).expanduser().resolve() if a.workspace else W.WS
    data_dir = W.data_dir(ws) / a.ep

    # ★ 分镜图的提示词真源是**分镜 md**，不是 `boards.json`。
    #   为什么改：`boards.json` 是 `convert_storyboard` 的产物，而那一步在
    #   七环节里排在「提示词」环节 —— 如果分镜图只认 boards.json，
    #   「分镜」环节就得依赖排在它后面的「提示词」环节，拓扑直接成环。
    #   md 里的 `- board:` 就是分镜环节自己的产物，读它才符合环节边界。
    specs = _specs_from_md(ws, a.ep)
    src = "05-分镜/%s_storyboard.md" % a.ep
    if not specs:
        boards_json = data_dir / "boards.json"
        specs = _read_json(boards_json, {}) or {}
        src = str(boards_json)
    if not specs:
        print("[FAIL] 既没有分镜 md 的 `- board:` 字段，也没有 %s/boards.json" % data_dir)
        print("       分镜 md 里给每一镜补上：\n         - board: |\n             <这一镜的单帧构图描述>")
        return 2
    h3 = _read_json(data_dir / "h3_prompts.json", {}) or {}
    bible = _read_json(L.assets_dir(ws) / "design" / "character-bible.json", {}) or {}
    style_line = _style_line(ws)

    out_dir = L.assets_dir(ws) / "boards" / a.ep
    want = {s.strip() for s in a.only.split(",") if s.strip()}
    items = [(sid, spec) for sid, spec in specs.items() if not want or sid in want]
    if a.limit:
        items = items[: a.limit]

    print("=" * 74)
    print("分镜图生成 · %s" % a.ep)
    print("=" * 74)
    print("  工作区  : %s" % ws)
    print("  契约    : %s（%d 镜）" % (src, len(specs)))
    print("  落点    : %s" % out_dir)
    print("  风格    : %s" % (style_line[:70] or "（未取到 look，用默认摄影风格）"))
    print("  通道    : %s" % ("本地图生图（ref1=主角色）" if a.with_refs else "本地文生图"))
    if not items:
        print("\n[WARN] 没有要处理的镜（--only 可能写错）")
        return 0

    # 缺 board 的镜先报出来：这些镜上片时会退化为两参
    missing = [sid for sid, spec in items if not str(spec.get("prompt") or "").strip()]
    if missing:
        print("\n[WARN] %d 镜缺 board 提示词，跳过：%s" % (len(missing), "、".join(missing[:12])))

    plan = []
    for sid, spec in items:
        if sid in missing:
            continue
        txt, n, codes = build_prompt(sid, spec, bible, style_line,
                                     str((h3.get(sid) or {}).get("prompt") or ""),
                                     ratio=str(spec.get("ratio") or ""))
        plan.append((sid, txt, n, codes, spec))

    if not a.apply or a.dry_run:
        for sid, txt, n, codes, spec in plan:
            print("\n" + "-" * 74)
            print("%s ｜ %d 人 %s ｜ ratio=%s" % (sid, n, "/".join(codes) or "无", spec.get("ratio")))
            print("-" * 74)
            print(txt)
        print("\n（干跑：%d 镜，未出图。加 --apply 真出。）" % len(plan))
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    ok = fail = skip = 0
    for i, (sid, txt, n, codes, spec) in enumerate(plan, 1):
        dst = out_dir / ("%s.png" % sid)
        if dst.is_file() and not a.force:
            print("[%d/%d] %s 已存在，跳过（--force 重出）" % (i, len(plan), sid))
            skip += 1
            continue
        seed = a.seed if a.seed is not None else (1000 + i)
        cmd = [sys.executable, str(COMFY_CLIENT),
               "--workflow", str(WF_EDIT if a.with_refs else WF_9x16),
               "--prompt", txt, "--prefix", "board_%s_%s" % (a.ep, sid),
               "--out", str(out_dir.parent / "._tmp"), "--aspect", spec.get("ratio") or "9:16",
               "--seed", str(seed)]
        if a.with_refs:
            refs = [str(x) for x in (spec.get("refs") or [])]
            tables = {}
            rj = _read_json(L.assets_dir(ws) / "refs.json", {}) or {}
            tables.update(rj.get("characters") or {})
            tables.update(rj.get("scenes") or {})
            for key in refs[:2]:
                p = tables.get(key)
                if p and not str(p).startswith(("http://", "https://")):
                    cmd += ["--image", str(p if pathlib.Path(p).is_absolute()
                                           else (ws / p))]
        print("[%d/%d] %s …" % (i, len(plan), sid))
        r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode != 0:
            fail += 1
            print("       [FAIL] %s" % ((r.stderr or r.stdout or "").strip().splitlines()[-1:] or "?"))
            continue
        # comfy_client 落的是 <prefix>_00.png，改名为 <shot_id>.png（引擎按 shot_id 扫）
        made = sorted((out_dir.parent / "._tmp").glob("board_%s_%s*.png" % (a.ep, sid)))
        if not made:
            fail += 1
            print("       [FAIL] 没有产物")
            continue
        made[0].replace(dst)
        ok += 1
        print("       → %s" % dst.name)

    tmp = out_dir.parent / "._tmp"
    if tmp.is_dir() and not any(tmp.iterdir()):
        tmp.rmdir()
    print("\n完成：成功 %d / 跳过 %d / 失败 %d（共 %d 镜）" % (ok, skip, fail, len(plan)))
    if ok:
        print("下一步：python stages/video/workflow/scripts/run.py --workspace \"%s\" --ep %s --dry-run"
              % (ws, a.ep))
    return 0 if fail == 0 else 3


if __name__ == "__main__":
    sys.exit(main())
