#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""convert_storyboard.py —— 分镜 md → `data/` 五文件（缺口 G7 / 断点 B1）

为什么有它
----------
「创作层产物（md）→ 出片引擎输入（`data/`）」是整条链上唯一的 P0 断点：
上游产出给人看的 Markdown，下游吃严格 schema 的 JSON，中间此前靠**手工搬**。
本脚本把这一步固化成可复现的转换，**只做搬运与校验，不改一个字提示词**。

输入契约（md，容错解析）—— 2026-11-01 收敛为 **5 个字段**
----------------------------------------------------------
    ## shot_001
    - duration: 9                 # 必填，4–15 秒整数
    - ratio: 9:16                 # 必填
    - refs: char_elle, char_kane, scene_office   # 角色在前、场景在后（顺序即 <Picture n>）
    - board: |                    # 必填：**这一镜的分镜图**提示词（单帧、与成片同构）
        <一句话构图描述，9:16 竖版，不要拼版>
    - prompt: |                   # 必填：H3 六段式提示词
        <[SHOT]/[SUBJECT]/[ACTION]/[DIALOGUE]/[LIGHT]...>

**已删除的字段**（2026-11-01，随九宫格链下线）：
`banana_prompt`（九宫格图生图）、`crop`（裁 3×3）、`time`（光位注入）。
留着它们只会让人以为还有两条出图路。旧 md 里如果出现，只告警、不报错、不生效。

输出（`data/` 五文件）
---------------------
    shots.json       [{shot_id, ratio, crop{1,1}, board_ref, character_refs, scene_refs}]
    boards.json      {shot_id: {prompt, ratio, refs}}      ← 出分镜图的契约（gen_boards.py 消费）
    h3_prompts.json  {shot_id: {prompt, duration, ratio, voice}}
    characters.json  {key: 图片路径}   ← 自 `<04-资产>/refs.json` 合并（可选）
    scenes.json      {key: 图片路径}   ← 同上

分镜图的落点约定：`04-资产/boards/<ep>/<shot_id>.png`。生成器按此写，引擎按此扫；
`board_ref` 存的是 key（`board_<ep>_<shot_id>`），不是路径 —— 换目录不用改数据。

用法
----
    python convert_storyboard.py --workspace "D:/剧/新剧" --ep ep01            # 干跑对比
    python convert_storyboard.py --workspace "D:/剧/新剧" --ep ep01 --apply    # 真写（先备份）
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import sys
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _ws as W  # noqa: E402  ★ 分阶段目录真源（stages/_layout.py）
import _layout as L  # noqa: E402

HEAD = re.compile(r"(?m)^##+\s*(.+?)\s*$")
KV = re.compile(r"(?m)^\s*[-*]?\s*([A-Za-z_\u4e00-\u9fff][\w\u4e00-\u9fff\-]*)\s*[:：]\s*(.*)$")
FENCE = re.compile(r"```[A-Za-z]*\s*\n(.*?)```", re.S)
# 现行 5 字段。**已删字段保留在别名表里只为「认出来并告警」**，
# 不删是因为旧 md 还散落在历史项目里，直接报错会把升级变成事故。
SHOT_ALIASES = {"duration": "duration", "时长": "duration", "秒": "duration",
                "ratio": "ratio", "画幅": "ratio",
                "refs": "refs", "参考图": "refs", "picture": "refs",
                "board": "board", "分镜图": "board", "storyboard": "board",
                "prompt": "prompt", "h3": "prompt", "提示词": "prompt",
                # 以下四个是 2026-11-01 删掉的：认得出、但不生效
                "banana_prompt": "_dead", "banana": "_dead", "九宫格": "_dead",
                "crop": "_dead", "time": "_dead", "时间": "_dead",
                "时段": "_dead", "日夜": "_dead"}
DEAD_FIELDS = {"_dead": "九宫格链（banana_prompt / crop / time）已于 2026-11-01 下线"}


# ★ 2026-10-20（反馈 P2-9）：TIME 字段必须落成**光位描述**，不能只是一个词。
#   实测：SC08 剧本写「夜」，成片明显偏亮，像下午室内；根因是提示词里只有 `Time: night`
#   一个词，模型对光位几乎没有约束。这里把常见时段映射成固定的英文光位短语，
#   由模板统一注入，避免每个镜头各写一套、也不再让「夜」自由漂移成白天。
TIME_LIGHT = (
    (("夜", "晚上", "深夜", "night", "noche", "nocturn"),
     "only a single warm practical lamp as the key light, deep shadows, no daylight"),
    (("黄昏", "傍晚", "日落", "dusk", "sunset", "atardecer"),
     "low warm side light from the window, long soft shadows"),
    (("清晨", "晨", "早晨", "dawn", "morning", "amanecer"),
     "cool morning light through the window, soft haze"),
    (("日", "白天", "中午", "day", "día", "tarde", "daylight"),
     "daylight from the window, soft fill"),
)


def light_phrase(time_text: str) -> str:
    """把 TIME 字段映射成固定的光位短语；认不出返回空串（不猜）。"""
    t = (time_text or "").strip().lower()
    if not t:
        return ""
    for keys, phrase in TIME_LIGHT:
        if any(k.lower() in t for k in keys):
            return phrase
    return ""


# 提示词里已经有明确光位描述时不再注入（避免自相矛盾的两套光）
_LIGHT_PRESENT = ("light", "lamp", "shadow", "daylight", "backlight",
                  "光", "灯", "阳光", "阴影")


def _norm_key(k: str) -> str:
    k = k.strip().lower().replace("-", "_")
    return SHOT_ALIASES.get(k, SHOT_ALIASES.get(k.replace("_", ""), k))


def _shot_id(raw: str) -> str:
    raw = raw.strip()
    m = re.fullmatch(r"第\s*(\d+)\s*段", raw)
    if m:
        return "shot_%03d" % int(m.group(1))
    m = re.fullmatch(r"(?:EP)?\s*(\d+)", raw)
    if m:
        return "shot_%03d" % int(m.group(1))
    return re.sub(r"[^\w\-]", "_", raw)


def parse_md(text: str) -> list:
    """把 md 解析成 shot 列表。返回 [{'shot_id', 'fields': {...}, 'prompt': str}]"""
    heads = list(HEAD.finditer(text))
    out = []
    for i, h in enumerate(heads):
        body = text[h.end(): heads[i + 1].start() if i + 1 < len(heads) else len(text)]
        sid = _shot_id(h.group(1))
        if sid in ("", "_"):
            continue
        fields, prompt = {}, ""
        # 1) 优先取围栏代码块作为 prompt（避免与字段行混淆）
        fm = FENCE.search(body)
        if fm:
            prompt = fm.group(1).strip()
            body = body[:fm.start()] + body[fm.end():]
        # 2) 字段行
        for m in KV.finditer(body):
            _raw_key = m.group(1).strip()
            k, v = _norm_key(_raw_key), m.group(2).strip()
            if not v:
                continue
            if k in ("prompt", "board") and v in ("|", "|-", ">", ">-", ""):
                # YAML 块标量：`prompt: |` / `board: |` 之后是缩进块。
                # ★ 2026-11-01：board 最初没走这个分支，结果 boards.json 里存的是字面量 "|"。
                #   症状很隐蔽 —— 契约文件看着有值，实际出图提示词是空内容。
                # 只取**紧邻的连续缩进行**。旧写法是「前 60 行里所有缩进行」，
                # 于是 `board:` 会把后面的 `prompt:` 整块吸进来 —— 分镜图提示词里
                # 混进一整段 H3 六段式，出图时模型只看到一堆 [SHOT]/[ACTION]。
                tail = body[m.end():]
                buf = []
                for ln in tail.splitlines():
                    if ln.startswith(("    ", "\t")):
                        buf.append(ln)
                    elif not ln.strip():
                        if buf:                     # 块内空行保留，块外空行停止
                            buf.append("")
                        continue
                    else:
                        break                       # 遇到下一个 `- key:` 就停
                val = "\n".join(buf).strip()
                if k == "prompt" and not prompt:
                    prompt = val
                elif val:
                    fields[k] = val
                continue
            if k == "prompt" and not prompt:
                prompt = v
            elif k == "_dead":
                # 记下**原字段名**：只写一个 `_dead` 的话，报错只能说「有已下线字段」，
                # 说不出是 banana_prompt 还是 time —— 用户不知道该删哪一行。
                fields.setdefault("_dead", [])
                if isinstance(fields["_dead"], list):
                    fields["_dead"].append(_raw_key)
                else:
                    fields["_dead"] = [str(fields["_dead"]), _raw_key]
            else:
                fields.setdefault(k, v)
        out.append({"shot_id": sid, "fields": fields, "prompt": prompt})
    return out


# 分镜图是**整张**画面，不再切 3×3。字段仍保留在 shots.json 里，
# 是因为引擎的 ImageRequest 读这个键；值固定 1×1 = 不切。
CROP_WHOLE = {"rows": 1, "cols": 1}


# ---------------------------------------------------------------------------
# <Picture n> 重编号：分镜图占 1，角色与场景整体后移
# ---------------------------------------------------------------------------
# ★ 2026-11-01：参考图顺序改成「分镜图 → 角色 → 场景」后，所有存量提示词里的
#   `<Picture 1> ELLE` 都会指错人（现在 1 是分镜图）。这是 D1 级破坏，
#   靠人手改 32 个镜必出错，所以由转换器**机械重排**，并在最前面补一句分镜图说明。
#
#   为什么不在 md 里直接写新编号：md 是人写的，人总会回到旧习惯。
#   编号是「槽位」的函数，就该由知道槽位的代码算。
_PIC_RE = re.compile(r"<Picture\s+(\d+)>", re.I)

BOARD_LINE = ("<Picture 1> this frame itself — the composition reference: keep its camera angle, "
              "blocking, lens and lighting. It defines WHERE things are, not WHO they are.")


def renumber_pictures(prompt: str, has_board: bool = True) -> tuple:
    """把 `<Picture n>` 整体后移 1（有分镜图时），并在 [REFS] 段首插入分镜图说明。

    → (新提示词, 最大编号)。没有 `[REFS]` 段时只做平移，不插入新段落（不硬造结构）。
    """
    txt = prompt or ""
    if not has_board:
        nums = [int(m.group(1)) for m in _PIC_RE.finditer(txt)]
        return txt, (max(nums) if nums else 0)

    def bump(m):
        return "<Picture %d>" % (int(m.group(1)) + 1)

    txt = _PIC_RE.sub(bump, txt)
    # 插在 `[REFS]` 标记**之后、行尾之前**（插到行尾会变成一段无主语的后缀，
    # 而这条说明必须出现在所有角色之前 —— 编号 1 是它的，模型得先读到）。
    m = re.search(r"(?m)^(\s*\[REFS\]\s*)", txt)
    if m:
        txt = txt[:m.end()] + BOARD_LINE + " " + txt[m.end():].lstrip()
    nums = [int(x.group(1)) for x in _PIC_RE.finditer(txt)]
    return txt, (max(nums) if nums else 0)


def _split_refs(refs: list, char_keys: set, scene_keys: set, sid: str, stats: dict) -> tuple:
    """把混合 `refs` 拆成 (character_refs, scene_refs)（反馈 9.3）。

    背景：此前所有 refs 一律塞进 `character_refs`，引擎于是拿场景 key 去 characters.json
    里查，报「引用了不存在的 key」（8 段 × 1 条），项目侧只能把场景也登记进 characters，
    语义不干净。

    ★ 但**不能无脑拆**：引擎喂槽顺序是「先 character_refs，再 scene_refs」，
      一旦原顺序是 `[角色, 场景, 角色]` 这种交错，拆完就会与 `<Picture N>` 错位 ——
      错位是硬错且很难看出来。所以只在「拆分后顺序不变」时才真拆：
      所有角色/未登记 key 都排在所有场景 key 之前。
    未登记 key（例如分镜图 `sb_ep01_sc01`）继续走 characters 槽，并单独记录（供上游登记）。
    """
    kind = []
    for r in refs:
        kind.append("s" if (r in scene_keys and r not in char_keys) else "c")
    unknown = [r for r in refs if r not in char_keys and r not in scene_keys]
    if unknown:
        stats.setdefault("refs_unknown", []).append("%s(%s)" % (sid, ",".join(unknown)))
    if "s" not in kind:
        return refs, []
    last_c = max((i for i, k in enumerate(kind) if k == "c"), default=-1)
    first_s = min((i for i, k in enumerate(kind) if k == "s"), default=10 ** 6)
    if last_c < first_s:
        return ([r for r, k in zip(refs, kind) if k == "c"],
                [r for r, k in zip(refs, kind) if k == "s"])
    stats.setdefault("refs_interleaved", []).append(sid)
    return refs, []


# ★ 2026-10-21（BGM 分工）：H3 是 video+audio 双模态，**必须显式禁止它自造配乐**。
#   否则会出现「模型自己垫了一层含糊的音乐」+「后期又铺一层 BGM」= 双重铺底、
#   相位抵消、音量台阶，而且模型那层没法调音量、没法换曲、没法证明版权。
#   分工写死：**画面 + 同期声归模型，BGM 归后期**（bgm.py）。
AUDIO_DIRECTION = (
    "[AUDIO] Diegetic sound only: room tone, footsteps, fabric rustle, doors, "
    "object handling, muffled street noise through glass. "
    "NO background music, NO score, NO melody, NO drum loop, NO stingers, "
    "NO musical bed of any kind — all music is added in post-production."
)
_AUDIO_MARKERS = ("[AUDIO]", "no background music", "no musical bed")


def audio_block(prompt: str) -> str:
    """返回要追加的音频约束段；提示词里已有则返回空串（不重复追加）。"""
    low = (prompt or "").lower()
    if any(m in low for m in _AUDIO_MARKERS):
        return ""
    return AUDIO_DIRECTION


def _default_voice(ws: pathlib.Path) -> str:
    """声音归属：读开工确认单（`project-setup.json` 的 `video_options.voice`），缺省 h3。

    ★ 2026-10-21（反馈 10.1）：H3 是 video+audio 双模态，**语音时间由模型自决**，
      `<d>` 的位置只是建议（实测偏差 −6.3s）。所以「这一段的声音由谁负责」必须是显式约定，
      否则字幕会按剧本时间窗烧、实际发声却在另一镜。三选一：h3 / external / mute。
    """
    try:
        p = pathlib.Path(ws) / "project-setup.json"
        d = json.loads(p.read_text(encoding="utf-8-sig"))
        v = str(((d.get("video_options") or {}).get("voice")) or "").strip()
        return v if v in ("h3", "external", "mute") else "h3"
    except (OSError, json.JSONDecodeError, ValueError):
        return "h3"


def build(shots: list, ws: pathlib.Path, ep: str = "",
          inject_light: bool = True, inject_audio: bool = True) -> tuple:
    """→ (data 五文件 dict, 问题列表, 统计)

    `ep` 用来拼 `board_ref` 的 key（`board_<ep>_<shot_id>`）。
    不传就按空串处理 —— 只影响 key 前缀，不阻断解析。
    """
    problems, out_shots, out_h3, out_boards = [], [], {}, {}
    seen = set()
    stats = {"board_missing": [], "dead_fields": [], "light_injected": 0,
             "light_skipped_has_light": 0, "time_unmapped": []}

    # 先读 04-资产/refs.json：分流 character_refs / scene_refs 要看 key 的归属
    try:
        rp = L.stage_dir(ws, "assets") / "refs.json"
        _rj = json.loads(rp.read_text(encoding="utf-8-sig")) if rp.is_file() else {}
    except Exception:                                                          # noqa: BLE001
        _rj = {}
    chars = (_rj or {}).get("characters") or {}
    scenes = (_rj or {}).get("scenes") or {}
    char_keys, scene_keys = set(chars), set(scenes)
    voice = _default_voice(ws)

    for s in shots:
        sid, f = s["shot_id"], s["fields"]
        if sid in seen:
            problems.append("shot_id 重复：%s" % sid)
            continue
        seen.add(sid)

        # 死字段：认得出、不生效，但要让人知道你写的没用了
        for _d in (f.get("_dead") or []):
            stats["dead_fields"].append("%s:%s" % (sid, _d))

        if not s["prompt"].strip():
            problems.append("%s 缺 prompt（H3 提示词）" % sid)
        board = (f.get("board") or "").strip()
        if not board:
            stats["board_missing"].append(sid)

        refs = [x.strip() for x in re.split(r"[,，、\s]+", f.get("refs") or "") if x.strip()]
        c_refs, s_refs = _split_refs(refs, char_keys, scene_keys, sid, stats)
        out_shots.append({
            "shot_id": sid,
            "ratio": f.get("ratio") or "9:16",
            "crop": dict(CROP_WHOLE),
            # ★ 顺序即 <Picture n>：分镜图(1) → 角色(2..) → 场景(..n)
            #   board_ref 是 key 不是路径：出图产物落在 04-资产/boards/<ep>/，
            #   引擎扫目录建映射，数据里只认 key。
            "board_ref": "board_%s_%s" % (ep or "ep", sid),
            # ★ 约定：`character_refs` + `scene_refs` 的拼接顺序 = 提示词 `<Picture N>` 顺序
            "character_refs": c_refs,
            **({"scene_refs": s_refs} if s_refs else {}),
        })
        out_boards[sid] = {"prompt": board, "ratio": f.get("ratio") or "9:16", "refs": refs}

        dur = f.get("duration")
        prompt = s["prompt"].strip()
        # TIME 字段已下线，但旧 md 里还有 tmux 光位需求：只在提示词**没有**光位时补一句
        phrase = light_phrase(f.get("time") or "")
        t_raw = (f.get("time") or "").strip()
        if phrase and prompt:
            if any(k in prompt.lower() for k in _LIGHT_PRESENT):
                stats["light_skipped_has_light"] += 1
            elif inject_light:
                prompt = prompt + "\n\nLight: " + phrase
                stats["light_injected"] += 1
        elif t_raw:
            stats["time_unmapped"].append("%s(%s)" % (sid, t_raw))
        # 分镜图占 <Picture 1>，角色与场景整体后移一位（见 renumber_pictures 的注释）
        prompt, _max_pic = renumber_pictures(prompt, has_board=bool(board))
        if board and _max_pic:
            stats.setdefault("pic_max", {})[sid] = _max_pic
        ab = audio_block(prompt) if inject_audio else ""
        out_h3[sid] = {"prompt": (prompt + "\n\n" + ab) if ab else prompt,
                       **({"duration": float(re.sub(r"[^\d.]", "", dur))} if dur else {}),
                       "ratio": f.get("ratio") or "9:16",
                       "voice": voice}

    return ({"shots.json": out_shots, "boards.json": out_boards,
             "h3_prompts.json": out_h3,
             "characters.json": chars, "scenes.json": scenes}, problems, stats)


def main() -> int:
    ap = argparse.ArgumentParser(description="分镜 md → data/<ep>/ 五文件（只搬运不改写）")
    ap.add_argument("--workspace", default=None)
    ap.add_argument("--ep", required=True, help="集号，如 ep01")
    ap.add_argument("--src", default=None, help="md 路径；默认自动在 05-分镜 / 06-提示词 里找")
    ap.add_argument("--apply", action="store_true", help="真写 data/<ep>/（先备份原文件）")
    ap.add_argument("--no-audio-direction", dest="inject_audio", action="store_false",
                    help="不追加 [AUDIO] 段（默认追加：禁止模型自造配乐，BGM 归后期）")
    ap.add_argument("--no-inject-light", dest="inject_light", action="store_false",
                    help="不按 TIME 字段注入光位短语（TIME 已下线，只剩旧 md 兼容）")
    a = ap.parse_args()

    ws = pathlib.Path(a.workspace).expanduser().resolve() if a.workspace else W.WS
    src = pathlib.Path(a.src).expanduser().resolve() if a.src else None
    if src is None:
        cands = []
        for key in ("storyboard", "prompts"):
            try:
                d = L.stage_dir(ws, key)
            except Exception:                                                  # noqa: BLE001
                continue
            cands += sorted(d.glob("%s*.md" % a.ep))
        src = next((c for c in cands if c.is_file()), None)
    if not src or not src.is_file():
        print("[FAIL] 找不到 %s 的分镜/提示词 md（用 --src 指定）" % a.ep)
        return 2

    # ★ 2026-11-01：data 目录按集分。旧实现固定 `data/` 一个目录，
    #   跑 ep02 会把 ep01 的 shots.json 覆盖掉 —— 于是「上一集还能出，这一集角色全错」，
    #   而且覆盖是静默的（只留下一堆 .bak_时间戳）。现在一集一目录。
    base_data = W.data_dir(ws)
    data_dir = base_data / a.ep
    shots = parse_md(src.read_text(encoding="utf-8", errors="replace"))
    if not shots:
        print("[FAIL] %s 里没有解析到任何 `## <shot_id>` 段落" % src)
        return 2
    files, problems, stats = build(shots, ws, ep=a.ep,
                                   inject_light=bool(a.inject_light),
                                   inject_audio=bool(a.inject_audio))

    print("=" * 74)
    print("分镜 md → data/ 五文件")
    print("=" * 74)
    print("  源文件  : %s" % src)
    print("  输入目录: %s" % data_dir)
    print("  解析到  : %d 段" % len(shots))
    for name, obj in files.items():
        print("    %-18s %d 条" % (name, len(obj)))
    _h3 = files.get("h3_prompts.json") or {}
    if _h3:
        _v = next(iter(_h3.values())).get("voice") or "h3"
        print("  声音归属: %s%s" % (_v, {
            "h3": "（H3 自带音轨；语音位置由模型自决，字幕必须走 ASR 校时）",
            "external": "（H3 只出画面，另配 TTS/配音）",
            "mute": "（音轨整体后配）"}.get(_v, "")))
    files_shots_ = files.get("shots.json") or []
    _bd = files.get("boards.json") or {}
    _n_board = len([1 for v in _bd.values() if (v.get("prompt") or "").strip()])
    print("  分镜图  : %d/%d 段有 board 提示词%s"
          % (_n_board, len(_bd),
             "（缺的这几段出片时没有构图锚，会退回「角色+场景」两参）"
             if _n_board < len(_bd) else ""))
    if stats.get("board_missing"):
        print("  [WARN] 缺 board 的镜：%s" % "、".join(stats["board_missing"][:12]))
    _pm = stats.get("pic_max") or {}
    if _pm:
        _mismatch = []
        for s in files_shots_:
            _n_img = (1 if _pm.get(s["shot_id"]) else 0) + len(s.get("character_refs") or []) \
                + len(s.get("scene_refs") or [])
            if _pm.get(s["shot_id"]) and _pm[s["shot_id"]] != _n_img:
                _mismatch.append("%s(%d≠%d)" % (s["shot_id"], _pm[s["shot_id"]], _n_img))
        print("  Picture 编号: %d 段已重排（分镜图=1）%s"
              % (len(_pm), "；[WARN] 编号与图片数不符：%s" % "、".join(_mismatch) if _mismatch else ""))
    if stats.get("dead_fields"):
        _u = sorted(set(stats["dead_fields"]))
        print("  [WARN] %d 段含已下线字段（banana_prompt/crop/time），已忽略：%s"
              % (len(_u), "、".join(_u[:8])))
    if stats.get("light_injected"):
        print("  光位    : 按 TIME 注入 %d 段（提示词已含光位的 %d 段未动）"
              % (stats["light_injected"], stats["light_skipped_has_light"]))
    if stats.get("refs_unknown"):
        print("  [WARN] 以下参考图 key 没在 04-资产/refs.json 登记（仍走 characters 槽，"
              "ingest_check 可能判「引用了不存在的 key」）：%s"
              % "、".join(stats["refs_unknown"][:8]))
    if stats.get("refs_interleaved"):
        print("  [WARN] %d 段 refs 角色/场景交错，为防 <Picture N> 错位**未分流**；"
              "把场景 key 排到所有角色之后即可自动分流：%s"
              % (len(stats["refs_interleaved"]), "、".join(stats["refs_interleaved"][:8])))
    if problems:
        print("\n  [WARN] %d 个问题（不猜不编，请回上游补齐）：" % len(problems))
        for p in problems[:20]:
            print("        - %s" % p)

    if not a.apply:
        print("\n（干跑：未写盘。加 --apply 真写。）")
        return 0

    data_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for name, obj in files.items():
        p = data_dir / name
        if p.is_file():
            shutil.copy2(p, p.with_suffix(".json.bak_%s" % stamp))
        p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\n[OK] 已写入 %s（原文件已备份为 *.bak_%s）" % (data_dir, stamp))
    print("     下一步：python ingest_check.py --workspace \"%s\" --ep %s" % (ws, a.ep))
    print("     出片：python stages/video/workflow/scripts/run.py --workspace \"%s\" --ep %s"
          % (ws, a.ep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
