#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""convert_storyboard.py —— 分镜/提示词 md → `data/` 四文件（缺口 G7 / 断点 B1）

为什么有它
----------
可行性报告把「创作层产物（md）→ 出片引擎输入（`data/` 四文件）」定为**唯一 P0 断点**：
上游产出的是给人看的 Markdown，下游吃的是严格 schema 的 JSON，中间此前靠**手工搬**。
本脚本把这一步固化成可复现的转换，**只做搬运与校验，不改一个字提示词**。

输入契约（md，容错解析）
------------------------
    ## shot_001
    - duration: 8
    - ratio: 9:16
    - refs: char_01, char_02, scene_01
    - banana_prompt: <九宫格图生图提示词，单行>
    - prompt: |
        <H3 六段式提示词全文，缩进块>
        ...

兼容写法：`prompt:` 后接 ``` 围栏代码块，或直接缩进 4 空格；键名大小写与中划线/下划线均可。
`## 第N段` 亦可（段号自动转为 shot_id）。

输出（`data/` 四文件，schema 见 stages/video/workflow/references/data-schema.md）
--------------------------------------------------------------------------------
    shots.json       [{shot_id, banana_prompt, ratio, crop, character_refs, scene_refs}]
    h3_prompts.json  {shot_id: {prompt, duration, ratio}}
    characters.json  {key: 图片路径}   ← 自 `<04-资产>/refs.json` 合并（可选）
    scenes.json      {key: 图片路径}   ← 同上

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
SHOT_ALIASES = {"duration": "duration", "时长": "duration", "秒": "duration",
                "ratio": "ratio", "画幅": "ratio",
                "refs": "refs", "参考图": "refs", "picture": "refs",
                "banana_prompt": "banana_prompt", "banana": "banana_prompt",
                "九宫格": "banana_prompt",
                "prompt": "prompt", "h3": "prompt", "提示词": "prompt",
                "time": "time", "时间": "time", "时段": "time", "日夜": "time",
                "crop": "crop"}


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
            k, v = _norm_key(m.group(1)), m.group(2).strip()
            if not v:
                continue
            if k == "prompt" and not prompt:
                # `prompt: |` 形式 —— 取其后缩进块
                tail = body[m.end():]
                block = "\n".join(ln for ln in tail.splitlines()[:40]
                                  if ln.startswith(("    ", "\t")))
                prompt = block.strip() or v
            else:
                fields.setdefault(k, v)
        out.append({"shot_id": sid, "fields": fields, "prompt": prompt})
    return out


def _crop(v: str | None):
    if not v:
        return {"rows": 3, "cols": 3}
    m = re.fullmatch(r"(\d+)\s*[x×]\s*(\d+)", v.strip())
    return {"rows": int(m.group(1)), "cols": int(m.group(2))} if m else {"rows": 3, "cols": 3}


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


def build(shots: list, ws: pathlib.Path, inject_light: bool = True,
          inject_audio: bool = True) -> tuple:
    """→ (data 四文件 dict, 问题列表, 统计)"""
    problems, out_shots, out_h3 = [], [], {}
    seen = set()
    stats = {"light_injected": 0, "light_skipped_has_light": 0, "time_unmapped": []}

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
        if not s["prompt"].strip():
            problems.append("%s 缺 prompt（H3 六段式）" % sid)
        if not f.get("banana_prompt"):
            problems.append("%s 缺 banana_prompt（九宫格图生图提示词）" % sid)
        refs = [x.strip() for x in re.split(r"[,，、\s]+", f.get("refs") or "") if x.strip()]
        c_refs, s_refs = _split_refs(refs, char_keys, scene_keys, sid, stats)
        out_shots.append({
            "shot_id": sid,
            "banana_prompt": f.get("banana_prompt") or "",
            "ratio": f.get("ratio") or "9:16",
            "crop": _crop(f.get("crop")),
            # ★ 约定：`character_refs` + `scene_refs` 的拼接顺序 = 提示词 `<Picture N>` 顺序
            #   （引擎按顺序喂槽，缺一号后面全错位）。
            "character_refs": c_refs,
            **({"scene_refs": s_refs} if s_refs else {}),
        })
        dur = f.get("duration")
        prompt = s["prompt"].strip()
        # ★ 反馈 P2-9：有 TIME 字段就把它落成光位短语（提示词自己已写光位则不插）。
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
        ab = audio_block(prompt) if inject_audio else ""
        out_h3[sid] = {"prompt": (prompt + "\n\n" + ab) if ab else prompt,
                       **({"duration": float(re.sub(r"[^\d.]", "", dur))} if dur else {}),
                       "ratio": f.get("ratio") or "9:16",
                       # 声音归属（反馈 10.1）：h3 自带音轨 / external 另配 TTS / mute 全后配
                       "voice": voice}

    # characters/scenes 已在函数开头读过（分流要用），这里直接落盘
    return ({"shots.json": out_shots, "h3_prompts.json": out_h3,
             "characters.json": chars, "scenes.json": scenes}, problems, stats)


def main() -> int:
    ap = argparse.ArgumentParser(description="分镜/提示词 md → data/ 四文件（只搬运不改写）")
    ap.add_argument("--workspace", default=None)
    ap.add_argument("--ep", required=True, help="集号，如 ep01")
    ap.add_argument("--src", default=None, help="md 路径；默认自动在 05-分镜 / 06-提示词 里找")
    ap.add_argument("--apply", action="store_true", help="真写 data/（先备份原文件）")
    ap.add_argument("--no-audio-direction", dest="inject_audio", action="store_false",
                    help="不追加 [AUDIO] 段（默认追加：禁止模型自造配乐，BGM 归后期）")
    ap.add_argument("--no-inject-light", dest="inject_light", action="store_false",
                    help="不按 TIME 字段注入光位短语（默认会注入；反馈 P2-9）")
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

    data_dir = W.data_dir(ws)
    shots = parse_md(src.read_text(encoding="utf-8", errors="replace"))
    if not shots:
        print("[FAIL] %s 里没有解析到任何 `## <shot_id>` 段落" % src)
        return 2
    files, problems, stats = build(shots, ws, inject_light=bool(a.inject_light),
                                   inject_audio=bool(a.inject_audio))

    print("=" * 74)
    print("分镜/提示词 md → data/ 四文件")
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
    if stats.get("light_injected"):
        print("  光位    : 按 TIME 注入 %d 段（提示词已含光位的 %d 段未动；"
              "如需逐字保留请加 --no-inject-light）"
              % (stats["light_injected"], stats["light_skipped_has_light"]))
    if stats.get("time_unmapped"):
        print("  [WARN] TIME 无法映射成光位（%d 段，未猜）：%s"
              % (len(stats["time_unmapped"]), "、".join(stats["time_unmapped"][:8])))
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
