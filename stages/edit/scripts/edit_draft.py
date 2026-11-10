#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""edit_draft.py —— 剪映专业版工程（草稿）生成器（2026-11-10 新增）

为什么要有它
------------
剪辑链原来是**一条黑箱**：`subtitle.py --stage master` 拼母版、`upscale.py` 放大、
`--stage render` 烧字幕，最后 `release_export.py` 出一个 `EpisodeNN.mp4`。
这条链能保证交付规格（1080×1920/SAR 1:1/帧数校验），但它**只交结果、不交过程**：

* 送审被质疑「这片子怎么来的」时，能拿出来的只有成片和一串 ffmpeg 参数 ——
  参数回答不了「第 7 镜用了哪个素材、字幕什么时候进的、BGM 铺了多长」；
* 想改一句台词、换一段 BGM，只能回到脚本里改配置再整集重跑，改不了、也回不去。

所以新增**并行产物**：一集一个剪映工程。时间轴是逐镜素材、逐条字幕、逐段 BGM 的真实结构，
与 `EpisodeNN.mp4` 同源同序；打开就能改，也能作为「剪辑过程」的证据材料。

⚠ **它不替代 ffmpeg 链**。剪映 7+ 已隐藏导出控件，`pyJianYingDraft` 的自动导出只在
  剪映 6 及以下可用 ⇒ **MP4 仍由 `release_export.py` 出**。本脚本的产物是工程，不是成片。
  两条轨道必须一致：本脚本用 `verify()` 逐项比对（画布/总时长/字幕条数与起点/素材可读），
  不一致直接判失败，绝不「生成成功」了事。

数据来源（全部复用，不另算一套）
--------------------------------
| 内容 | 真源 | 复用方式 |
|---|---|---|
| 逐镜片段与顺序 | `<out>/<ep>/<批次>/<shot>/final.mp4` | `subtitle.episode_segments()` |
| 字幕条目 | `<out>/subs/<ep>/cues.json` | 直接读（对齐产物，不重算） |
| 画布/帧率/封面时长 | `<engine>/config.subtitle.json` | `subtitle.load_config()` |
| 三语字号/落点 | `configs/subtitle-styles.json` | `subtitle.style_metrics()` |
| BGM 铺排 | `<out>/subs/<ep>/<ep>_bgm-plan.json` | `bgm.plan_path/load_library/track_file()` |

三个必须记住的坑（都是实测踩出来的，不是推测）
-----------------------------------------------
1. **`trange()` 会把秒截成整数**。`trange(0.2, 1.6)` 得到的是 `0 → 2` 秒：
   0.2 秒的偏移和 1.6 秒的时长被四舍五入吃掉。字幕时间全部要靠亚秒精度，
   所以本文件**一律用 `Timerange(start_us, duration_us)` 直接给微秒整数**，不碰 `trange`。
2. **字幕时间是「片段轴」，母版带封面片头**。`cues.json` 的起点从第一段画面算起，
   而母版前面还有一帧级封面（`master.cover_seconds`，默认 0.06s→实际 1 帧）。工程里字幕必须**整体后移**这个量，
   否则工程与成片差这一段 —— 送审时「工程和成片对不上」比没工程更糟。
3. **素材路径是绝对路径**。`draft_content.json` 里存的是绝对路径，换机器就断链。
   `--copy-media` 会把素材拷进草稿目录并改引用；默认只落 `draft_manifest.json`
   记全量 sha256，供外部逐项核对。

用法
----
    python stages/edit/scripts/edit_draft.py --workspace "<剧目录>" --ep ep01
    python stages/edit/scripts/edit_draft.py --workspace "<剧目录>" --ep ep01 --to-jianying
    python stages/edit/scripts/edit_draft.py --workspace "<剧目录>" --ep ep01 \\
        --drafts-dir "D:/Program Files (x86)/JianyingPro Drafts"
    python stages/edit/scripts/edit_draft.py --workspace "<剧目录>" --ep ep01 --dry-run
    python stages/edit/scripts/edit_draft.py --workspace "<剧目录>" --ep ep01 --copy-media

`--to-jianying` 会自己去 `%LOCALAPPDATA%\\JianyingPro\\User Data\\Projects\\com.lveditor.draft
\\root_meta_info.json` 里读各草稿的 `draft_root_path`，取众数当草稿根目录 —— 因为
剪映「全局设置-草稿位置」改过之后，`root_path` 字段并不会跟着变（本机实测：`root_path`
指 C 盘，35 条草稿全在 D 盘，照 `root_path` 生成等于白干）。

退出码
------
    0 工程已生成且自检通过
    2 自检不过（工程文件与预期结构不一致 —— 不要拿去送审）
    3 缺输入（没有分段成片 / 没有 cues.json / 缺 pyJianYingDraft）
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[union-attr]
except Exception:                                                # noqa: BLE001
    pass

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]                       # stages/edit/scripts → 仓库根
SUB_SCRIPTS = REPO / "stages" / "subtitle" / "scripts"
PROD_SCRIPTS = REPO / "stages" / "production" / "scripts"

EXIT_OK, EXIT_FAIL, EXIT_NOINPUT = 0, 2, 3

DRAFT_DIR_NAME = "draft_manifest.json"       # 清单文件名（与草稿目录同级）
REPORT_NAME = "report.json"
DEFAULT_CANVAS = (1080, 1920)
DEFAULT_FPS = 30
DEFAULT_COVER_SECONDS = 0.06      # 一帧级闪封（与 subtitle.COVER_LEAD_DEFAULT_S 同口径）
MEDIA_DIR_NAME = "media"

# 剪映文本字号的近似映射。
# ⚠ 剪映的 `TextStyle.size` 与 ASS 的 `Fontsize` **不是同一个单位**（前者是相对画布的档位，
#   后者是像素），两者没有可推导的换算关系。这里给的是「按 1080×1920 目视校对」的起点值，
#   必须在剪映里开一集看过再定 —— 所以它是 `configs/edit-draft.json` 的可覆盖项，
#   而不是代码里的硬编码真理。`[待核实: 在剪映内打开生成工程，逐语言目视校对字号]`
TEXT_SIZE_FALLBACK = {"zh": 15.0, "en": 13.5, "es": 13.0}
TEXT_SIZE_NOTE = ("剪映字号单位与 ASS 像素不同源，本值为近似起点；"
                  "首集需在剪映内目视校对后写回 configs/edit-draft.json")

# 固定字幕字体：不指定时剪映按模板默认字体渲染，换机器/换版本就可能换脸。
#   送审材料里「字体前后一致」是对方能直接用眼睛看出来的，所以要钉死一个内置字体。
#   选思源黑体 CN Medium：中英西三种字形都覆盖，且是剪映内置（`FontType` 里有）。
DEFAULT_TEXT_FONT = "SourceHanSansCN_Medium"


# ---------------------------------------------------------------- 模块加载
def _load_sibling(name: str, path: pathlib.Path):
    """按文件路径加载兄弟脚本（它们是 CLI 脚本，不在包里，不能直接 import）。"""
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError("无法加载 %s" % path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _sub():
    return _load_sibling("_sd_subtitle_mod", SUB_SCRIPTS / "subtitle.py")


def _bgm():
    return _load_sibling("_sd_bgm_mod", PROD_SCRIPTS / "bgm.py")


def _draft_lib():
    """导入 pyJianYingDraft；缺依赖时给可照抄的安装命令，不静默降级。"""
    try:
        import pyJianYingDraft as d          # noqa: PLC0415
        return d
    except ImportError as e:                 # pragma: no cover - 环境问题
        raise SystemExit(
            "缺依赖 pyJianYingDraft：%s\n"
            "  安装：pip install pyJianYingDraft==0.3.1\n"
            "  （该库仅用于**写草稿**，不需要安装剪映；自动导出另需剪映 6 及以下 + uiautomation，"
            "本仓库不使用该能力）\n"
            "  依赖清单见 requirements-edit.txt" % e)


# ---------------------------------------------------------------- 配置
def load_edit_config(ws: pathlib.Path) -> dict:
    """`configs/edit-draft.json`（仓库真源）→ 项目 `video-pipeline/config.edit.json` 覆盖。"""
    cfg = {"canvas": {"width": DEFAULT_CANVAS[0], "height": DEFAULT_CANVAS[1]},
           "fps": DEFAULT_FPS,
           "text": {"size": dict(TEXT_SIZE_FALLBACK), "border_width": 40.0,
                    "shadow": {"diffuse": 15.0, "distance": 5.0, "angle": -45.0}},
           "audio": {"volume_ceiling": 1.0},
           "cover_seconds": DEFAULT_COVER_SECONDS}
    base = REPO / "configs" / "edit-draft.json"
    if base.is_file():
        cfg = _deep_merge(cfg, _read_json(base, {}))
    try:
        import _layout as L                  # noqa: PLC0415
        proj = L.engine_root(ws) / "config.edit.json"
    except Exception:                        # noqa: BLE001
        proj = ws / "video-pipeline" / "config.edit.json"
    if proj.is_file():
        cfg = _deep_merge(cfg, _read_json(proj, {}))
        cfg["_config_path"] = str(proj)
    return cfg


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _read_json(p: pathlib.Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def _write_json(p: pathlib.Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8", newline="")


# ---------------------------------------------------------------- 时间工具
def _us(seconds: float) -> int:
    """秒 → 微秒整数（四舍五入，不用 trange —— 它会把亚秒截掉）。"""
    return int(round(float(seconds) * 1_000_000))


def _s(us: int) -> float:
    return round(us / 1_000_000.0, 3)


# ---------------------------------------------------------------- 素材采集
def collect(ws: pathlib.Path, ep: str, *, with_cover: bool = True, with_bgm: bool = True,
            allow_empty_subs: bool = False) -> dict:
    """把一集工程需要的素材全部解析出来。缺什么都写进 `missing`，不猜、不顶替。"""
    S = _sub()
    ep = S.canon_ep(ep)
    cfg = S.load_config(ws)
    out_root = pathlib.Path(S.out_dir_of(ws))
    subs_dir = out_root / "subs" / ep

    segs, miss_segs = S.episode_segments(str(ws), ep)
    ffprobe = (cfg.get("tools") or {}).get("ffprobe", "ffprobe")

    clips, total_seg_s = [], 0.0
    for i, seg in enumerate(segs):
        path = pathlib.Path(seg["file"]).resolve()
        dur = float(S.media_duration(ffprobe, str(path)) or 0.0)
        if dur <= 0:
            raise SystemExit(
                "读不到片段时长：%s\n"
                "  ffprobe 探测失败 ⇒ 先确认这段视频没坏（`ffprobe -v error -show_entries "
                "format=duration \"%s\"`），坏段要用 video.batch 重出，不能在剪辑阶段绕过。"
                % (path, path))
        clips.append({"index": i + 1, "shot_id": seg["shot_id"], "path": str(path),
                      "dur_s": round(dur, 6), "batch": seg.get("batch", "")})
        total_seg_s += dur

    # ★ 2026-11-10：一段画面都没有时**拒绝生成**（不是"生成后再自检"）。
    #   实跑踩过：工作区里 `shots.json` 不在（只搬了 07-成片）⇒ 段列表为空 ⇒
    #   造出一份 0 段视频、9 条字幕的草稿，`verify()` 还报「自检通过」。
    #   空工程在剪映里打开就是一片黑，拿去送审等于自曝。缺输入就不该产出文件。
    if not clips:
        raise SystemExit(
            "本集一段成片都没找到（%s）。\n"
            "  空工程（没有画面轨）不能作为送审材料，不做假通过 ⇒ 先确认两件事：\n"
            "    ① 数据目录里有没有这一集的镜号清单 shots.json"
            "（没有就跑 `md2pack` + `pack_import`）；\n"
            "    ② 每镜 `final.mp4` 是否已出（没出就跑 `drama do video.batch --ep %s`）。\n"
            "  两者都在之后重跑本脚本。" % (out_root / ep, ep))

    cover_path, cover_msg, cover_s = "", "", 0.0
    if with_cover:
        # 复用 subtitle.cover_lead_seconds：封面片头时长只有一处真源，
        # 否则「母版加了片头、工程不知道」这类错位会再次发生。
        secs, hit = S.cover_lead_seconds(str(ws), ep, cfg, enabled=True)
        if secs > 0 and hit and os.path.isfile(hit):
            cover_path = str(pathlib.Path(hit).resolve())
            cover_s = float(secs)
        else:
            cover_msg = hit or "未找到封面"

    cues = _read_json(subs_dir / "cues.json", []) or []
    cues = [c for c in cues if float(c.get("end", 0)) > float(c.get("start", 0))]

    bgm_plan, bgm_items, bgm_msg = {}, [], ""
    if with_bgm:
        try:
            B = _bgm()
            ppath = B.plan_path(ws, ep)
            if ppath.is_file():
                bgm_plan = _read_json(ppath, {}) or {}
                lib = {str(t.get("id")): t for t in (B.load_library(ws).get("tracks") or [])}
                for s in (bgm_plan.get("segments") or []):
                    a, b = float(s.get("start") or 0), float(s.get("end") or 0)
                    if b - a <= 0.05:
                        continue
                    tid = str(s.get("track") or "")
                    t = lib.get(tid)
                    tp = B.track_file(t) if t else None
                    if not tp or not pathlib.Path(tp).is_file():
                        bgm_msg = "BGM 计划里的 `%s` 在库里找不到文件，已跳过该段" % tid
                        continue
                    bgm_items.append({"track": tid, "path": str(pathlib.Path(tp).resolve()),
                                      "start_s": round(a, 3), "dur_s": round(b - a, 3),
                                      "gain_db": float(s.get("gain_db") or 0.0),
                                      "note": s.get("note") or ""})
            else:
                bgm_msg = "没有 %s（不铺 BGM）" % ppath.name
        except Exception as e:               # noqa: BLE001
            bgm_msg = "BGM 计划解析失败，已跳过：%s" % e

    if not cues and not allow_empty_subs:
        raise SystemExit(
            "本集没有字幕条目（%s）。\n"
            "  工程里没有字幕轨 = 与成片不一致，不能作为送审材料 ⇒ 先跑：\n"
            "    python stages/subtitle/scripts/subtitle.py --stage render --ep %s\n"
            "  （只有确认这片子本就没有字幕时，才用 --allow-empty-subtitles 放行）"
            % (subs_dir / "cues.json", ep))

    return {"ep": ep, "cfg": cfg, "sub_cfg": cfg, "out_root": out_root,
            "subs_dir": subs_dir, "clips": clips, "missing_segments": miss_segs,
            "total_seg_s": round(total_seg_s, 3), "cover_path": cover_path,
            "cover_s": cover_s, "cover_msg": cover_msg, "cues": cues,
            "bgm_plan": bgm_plan, "bgm_items": bgm_items, "bgm_msg": bgm_msg,
            "ffprobe": ffprobe}


# ---------------------------------------------------------------- 时间轴
def build_timeline(data: dict, edit_cfg: dict, with_subtitle: bool = True) -> dict:
    """→ 纯数据的时间轴（不碰第三方库，便于单测）。单位一律微秒整数。"""
    cover_us = _us(data["cover_s"]) if data["cover_path"] else 0
    cursor = cover_us

    video = []
    if data["cover_path"]:
        video.append({"kind": "photo", "shot_id": "cover", "path": data["cover_path"],
                      "start_us": 0, "dur_us": cover_us, "note": "首帧封面片头"})
    for c in data["clips"]:
        dur = _us(c["dur_s"])
        video.append({"kind": "video", "shot_id": c["shot_id"], "path": c["path"],
                      "start_us": cursor, "dur_us": dur, "note": "镜 %02d" % c["index"]})
        cursor += dur
    total_us = cursor

    # 字幕：cues 的时间是【整集绝对时间】（= 全部镜头累加轴，不含封面片头），
    #   工程轴 = 母版轴（含封面片头）⇒ 整体后移 cover_us。
    #   ★ 2026-11-10：此前这里是对的，但上游 build_cues 漏算了「无台词镜头」的时长，
    #   于是 cues 本身就少了 10 秒；本处加法没有错，错在基准。上游已修。
    # `with_subtitle=False` 时不出字幕轨 —— 留给剪映「识别字幕」，见 --no-subtitle。
    text = []
    if with_subtitle:
        for c in data["cues"]:
            st = _us(float(c["start"])) + cover_us
            en = _us(float(c["end"])) + cover_us
            if en - st <= 0:
                continue
            text.append({"start_us": st, "dur_us": en - st,
                         "text": str(c.get("text") or ""),
                         "lines": list(c.get("lines") or []),
                         "shot_id": c.get("shot_id") or "",
                         "source": c.get("source") or ""})

    audio = []
    for a in data["bgm_items"]:
        audio.append({"start_us": _us(a["start_s"]), "dur_us": _us(a["dur_s"]),
                      "path": a["path"], "track": a["track"],
                      "gain_db": a["gain_db"], "note": a.get("note") or ""})

    return {"cover_us": cover_us, "video": video, "text": text, "audio": audio,
            "total_us": total_us, "cue_offset_us": cover_us,
            "cue_offset_reason": ("母版有 %.2fs 封面片头，cues.json 从第一段画面算起"
                                  % data["cover_s"]) if cover_us else "无封面片头，字幕不偏移"}


def sync_check(data: dict, min_voiced_s: float = 0.12) -> dict:
    """量化「字幕有没有压到静音上」：每条字幕窗口里**最长连续有声区间**的时长。

    为什么要有这一步：对齐错了不会报错，只会「看起来怪」。实测 海外剧/28 ep01
    第一句标在 0.35s，而人声 4.25s 才出现。人眼得逐帧比对才知道，机器算一次
    能量就能点名。它**只诊断不改时间** —— 改时间的事归 `subtitle.py`
    （`--from-srt` 走外部 SRT，或重调 aligner）。

    ★ 2026-11-10 口径修正：判据从「窗口内有声**占比**」换成「窗口内**有没有一段
      连续 >=0.25s 的人声**」。原因：占比判据在两条已知正确的字幕上误报：
        · shot_005「Es la diseñadora del año.」人声实际是 0.08–0.6 与 2.5–3.9 两段，
          中间 2 秒空（AI 配音的换气/停顿）；whisper 词级时间戳把 `diseñadora`
          拉成 0.6–2.7，于是窗口 0.08–2.71 里占比只有 9%。
        · 首尾是对的、中间空洞是词级时间戳的固有抖动，不是错位。
      字幕的职责是「有人说话时它在场」，不是「在场时一直有人说话」；
      用占比判会把正确的全判成错的，人就再也不看这个告警了。

    ★ 门限 0.12s 的理由：「No.」「¿Eh?」这种应答的真实人声就是 0.2 秒级
      （实测 shot_004「No.」人声 5.90–6.10 = 0.20s）。门限设太高会把**正确的短句**
      报成错位，人就再也不看这个告警了。真正要抓的是「整条都压在静音上」，
      那类错的连续人声是 0.00s。
    """
    sub = _sub()
    starts, t = {}, 0.0
    for c in data["clips"]:
        starts[c["shot_id"]] = t
        t += float(c["dur_s"])

    suspects, checked, skipped = [], 0, 0
    for c in data["cues"]:
        sid = str(c.get("shot_id") or "")
        if sid not in starts:
            skipped += 1
            continue
        wav = pathlib.Path(data["subs_dir"]) / "asr" / (sid + ".wav")
        if not wav.is_file():
            skipped += 1
            continue
        # ★ cues 的时间是**整集绝对时间**（build_cues 已把段内相对时间加上段起点），
        #   而 asr/<sid>.wav 是**单镜切片** ⇒ 必须减回该段起点再用。少了这一步
        #   会在完全正确的字幕上报「最长连续人声 0.02s」，把体检变成噪声。
        #   实测踩点：shot_003 字幕 24.39–26.78，段起点 21.05 ⇒ 切片内 3.34–5.73，
        #   而那一段的人声在 4.58–6.53（本句起点确实是 4.58）。
        base = starts[sid]
        a = max(0.0, float(c["start"]) - base)
        b = float(c["end"]) - base
        if b - a <= 0.05:
            continue
        voiced = _longest_voiced(str(wav), a, b)
        if voiced is None:
            skipped += 1
            continue
        checked += 1
        if voiced < float(min_voiced_s):
            suspects.append({"shot_id": sid,
                             "start": round(float(c["start"]), 3),
                             "end": round(float(c["end"]), 3),
                             "voiced_s": round(float(voiced), 3),
                             "text": str(c.get("text") or "")[:24]})
    return {"checked": checked, "skipped": skipped, "min_voiced_s": float(min_voiced_s),
            "suspects": suspects}


def _longest_voiced(wav: str, a: float, b: float, frame_s: float = 0.02):
    """窗口 [a,b) 内最长**连续**有声区间的秒数；读不出音频返回 None。

    阈值口径复用 `subtitle._loud_threshold`（p90 相对 30% 与绝对下限 600 取大），
    与覆盖检查、ASR 幻觉拦截共用同一套 —— 三处各算一套阈值迟早互相矛盾。
    """
    sub = _sub()
    fr, fs = sub._frame_rms(wav, frame_s)
    if not fr:
        return None
    thr = sub._loud_threshold(fr)
    if thr is None:
        return None                       # 全段数字静音，没有可判依据
    i0 = max(0, int(a / fs))
    i1 = min(len(fr), max(i0 + 1, int(round(b / fs))))
    best = run = 0
    for v in fr[i0:i1]:
        if v >= thr:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best * fs


def _volume_of(gain_db: float, ceiling: float = 1.0) -> float:
    """dB → 线性增益（剪映 volume 是线性倍数）。clamp 到 [0, ceiling]。"""
    v = 10.0 ** (float(gain_db) / 20.0)
    return max(0.0, min(float(ceiling), round(v, 4)))


def _font_of(name) -> tuple:
    """字体名 → (FontType 或 None, 说明)。未知字体不硬崩，只是退回剪映默认。

    为什么返回元组而不是裸值：字体名写错是配置错误，必须让人看见，
    但**不能因此中断出片** —— 工程里少一个字体字段仍然可用，报错只会挡住交付。
    """
    want = str(name or DEFAULT_TEXT_FONT).strip()
    if not want:
        return None, "未指定字体，剪映用模板默认"
    try:
        d = _draft_lib()
        ft = getattr(d.FontType, want)
    except (AttributeError, ImportError):
        return None, "字体 `%s` 不在剪映内置字体表里，已退回默认（改 configs/edit-draft.json）" % want
    return ft, "字体 `%s`" % want


# ---------------------------------------------------------------- 写草稿
JIANYING_INDEX_TAIL = ("JianyingPro", "User Data", "Projects",
                       "com.lveditor.draft", "root_meta_info.json")


def detect_jianying_root(index_path=None) -> tuple:
    """探测剪映「全局设置-草稿位置」指向的**真实**目录。

    为什么不能只看 `root_path`：那只是默认安装位置，用户改过草稿位置后它不跟着变。
    本机实测（2026-11-10，剪映专业版 10.8.0.14162）：`root_path` 写的是
    `C:/Users/.../AppData/Local/.../com.lveditor.draft`，而 35 条草稿的
    `draft_root_path` 全是 `D:\\Program Files (x86)\\JianyingPro Drafts`。
    照 `root_path` 生成，剪映首页根本看不见这份工程。

    唯一可信的证据是每条草稿记的 `draft_root_path`，取众数。没有草稿可投票时才退回
    `root_path`（新装剪映、一条草稿都没有的情况）。
    """
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    cands = []
    if index_path is not None:
        cands.append(pathlib.Path(index_path))
    elif base:
        cands.append(pathlib.Path(base).joinpath(*JIANYING_INDEX_TAIL))
    for p in cands:
        js = _read_json(p, None)
        if not isinstance(js, dict):
            continue
        votes = {}
        for e in js.get("all_draft_store") or []:
            rp = (e or {}).get("draft_root_path") or ""
            if rp:
                votes[rp] = votes.get(rp, 0) + 1
        for rp, n in sorted(votes.items(), key=lambda kv: -kv[1]):
            cand = pathlib.Path(rp)
            if cand.is_dir():
                return cand, "取 %d 条草稿的 draft_root_path 众数" % sum(votes.values())
        rp = js.get("root_path") or ""
        if rp and pathlib.Path(rp).is_dir():
            return pathlib.Path(rp), "取自 root_meta_info.root_path（还没有草稿可投票）"
    return None, "没找到剪映草稿索引：%s" % (cands[0] if cands else "环境变量 LOCALAPPDATA 缺失")


def _make_cover_jpg(clip: dict, draft_dir: pathlib.Path, width: int = 436) -> str:
    """抽首段画面的一帧当草稿缩略图。

    剪映首页的卡片缩略图只认 `draft_cover.jpg`，不认 `draft_content.json` 里的素材。
    没有它卡片就是黑块 —— 送审时对方在首页看到一排黑块，第一印象就是「空的」。
    抽帧失败不算不合格（缩略图不是必要条件），返回 "" 由调用方记录。
    """
    out = draft_dir / "draft_cover.jpg"
    exe = shutil.which("ffmpeg") or "ffmpeg"
    # 取中段而不是第 0 帧：很多片子首帧是黑场/淡入，抽出来还是黑块
    dur = float(clip.get("dur_us") or 0) / 1e6
    ss = min(0.5, max(0.0, dur / 2.0)) if dur > 0 else 0.0
    cmd = [exe, "-y", "-ss", "%.3f" % ss, "-i", str(clip["path"]),
           "-frames:v", "1", "-vf", "scale=%d:-1" % int(width),
           "-update", "1", str(out)]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return ""
    if r.returncode != 0 or not out.is_file():
        return ""
    return str(out)


def _patch_meta(draft_dir: pathlib.Path, name: str, drafts_dir: pathlib.Path,
                total_us: int, cover_jpg: str) -> dict:
    """补 `draft_meta_info.json` 的首页元信息：名称 / 路径 / 时长 / 缩略图。

    剪映首页的「时长」和「封面」来自这份 meta，与 `draft_content.json` 无关。
    pyJianYingDraft 拷的是空白模板（`tm_duration=0`、`draft_cover` 指向不存在的文件），
    所以不补的话卡片一律显示 `00:00` + 黑块。

    本机实测（剪映 10.8.0.14162）：补写成**明文 JSON** 后剪映照样读得进去 ——
    它是「先尝试解密，失败再按明文解析」，不是只认一种。所以这里不做加密。
    """
    p = draft_dir / "draft_meta_info.json"
    meta = _read_json(p, None)
    if not isinstance(meta, dict):
        return {"written": False,
                "reason": "draft_meta_info.json 不是明文 JSON（被第三方加密过），未改写"}
    meta["draft_name"] = name
    # 实测口径：fold 用正斜杠，root 用反斜杠 —— 跟剪映自己写的一致
    meta["draft_fold_path"] = str(draft_dir).replace("\\", "/")
    meta["draft_root_path"] = str(drafts_dir)
    meta["draft_cover"] = (str(cover_jpg).replace("\\", "/") if cover_jpg else "")
    meta["tm_duration"] = int(total_us)
    _write_json(p, meta)
    return {"written": True, "tm_duration": int(total_us),
            "draft_cover": meta["draft_cover"]}


def write_draft(data: dict, tl: dict, edit_cfg: dict, drafts_dir: pathlib.Path,
                name: str, *, allow_replace: bool = True, copy_media: bool = False,
                make_draft_cover: bool = True) -> dict:
    d = _draft_lib()
    drafts_dir.mkdir(parents=True, exist_ok=True)
    W = int(edit_cfg["canvas"]["width"])
    H = int(edit_cfg["canvas"]["height"])
    fps = int(edit_cfg.get("fps") or DEFAULT_FPS)

    folder = d.DraftFolder(str(drafts_dir))
    script = folder.create_draft(name, W, H, fps, allow_replace=allow_replace)
    draft_dir = drafts_dir / name
    font_notes = []      # 字体/样式类告警（不致命，随结果带回主流程打印）

    def _path(p: str) -> str:
        """--copy-media 时把素材拷进草稿目录，草稿才可整体搬走。"""
        if not copy_media:
            return p
        src = pathlib.Path(p)
        dst_dir = draft_dir / MEDIA_DIR_NAME
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / ("%s_%s" % (_sha1(p)[:8], src.name))
        if not dst.is_file() or dst.stat().st_size != src.stat().st_size:
            shutil.copy2(src, dst)
        return str(dst)

    vtrack = script.append_track(d.TrackSpec(d.TrackType.video, "主轨-画面"))
    for c in tl["video"]:
        script.add_segment(d.VideoSegment(_path(c["path"]),
                                         d.Timerange(c["start_us"], c["dur_us"])),
                           track=vtrack)

    ttrack = None
    if tl["text"]:
        ttrack = script.append_track(d.TrackSpec(d.TrackType.text, "字幕"))
        tcfg = (edit_cfg.get("text") or {})
        lang = data["cfg"].get("default_language") or "zh"
        size = float((tcfg.get("size") or {}).get(lang) or TEXT_SIZE_FALLBACK.get(lang, 15.0))
        border_w = float(tcfg.get("border_width") or 40.0)
        sh = tcfg.get("shadow") or {}
        font, font_note = _font_of(tcfg.get("font"))
        font_notes.append(font_note)
        # 落点：文字块中心 = 0.6 × 画布高（与三语规范同一条），换算成剪映的归一化位移。
        #   剪映 transform.y 的 1.0 = 画布高的一半 ⇒ ty = -(center_ratio - 0.5) × 2。
        _m = _sub().style_metrics(data["cfg"], lang, (W, H))
        cy = int(_m.get("center_y") or int(H * 0.6))
        ty = -round(((cy / float(H)) - 0.5) * 2.0, 4)
        clip = d.ClipSettings(transform_y=ty)
        for c in tl["text"]:
            body = "\n".join(c["lines"]) if c["lines"] else c["text"]
            script.add_segment(
                d.TextSegment(body, d.Timerange(c["start_us"], c["dur_us"]),
                              font=font,
                              style=d.TextStyle(size=size, bold=True,
                                                color=(1.0, 1.0, 1.0)),
                              border=d.TextBorder(width=border_w),
                              shadow=d.TextShadow(diffuse=float(sh.get("diffuse", 15.0)),
                                                  distance=float(sh.get("distance", 5.0)),
                                                  angle=float(sh.get("angle", -45.0))),
                              clip_settings=clip),
                track=ttrack)

    atrack = None
    if tl["audio"]:
        atrack = script.append_track(d.TrackSpec(d.TrackType.audio, "BGM"))
        ceiling = float((edit_cfg.get("audio") or {}).get("volume_ceiling") or 1.0)
        kept = []
        for a in tl["audio"]:
            try:
                seg = d.AudioSegment(_path(a["path"]),
                                     d.Timerange(a["start_us"], a["dur_us"]),
                                     volume=_volume_of(a["gain_db"], ceiling))
            except (ValueError, TypeError) as e:
                # 典型：BGM 库里的文件其实是视频容器（带视频轨），
                # pyJianYingDraft 会拒绝。跳过并点名 —— 但要把 tl["audio"] 一起改掉，
                # 否则 verify() 会拿「计划段数」比「实际段数」，报一个假的不一致。
                tl.setdefault("skipped", []).append(
                    "BGM `%s` 无法作为音频素材（%s），已跳过该段"
                    % (a.get("track") or pathlib.Path(a["path"]).name, e))
                continue
            script.add_segment(seg, track=atrack)
            kept.append(a)
        tl["audio"] = kept
        if not kept:
            atrack = None

    script.save()

    # 缩略图要从**真实画面**抽，不能拿片头封面（那张是静帧，抽帧超出时长会得到空文件）
    first_real = next((c for c in tl["video"] if c.get("kind") == "video"), None)
    cover_jpg = ""
    if make_draft_cover and first_real:
        cover_jpg = _make_cover_jpg(first_real, draft_dir)
    meta = _patch_meta(draft_dir, name, drafts_dir, tl["total_us"], cover_jpg)

    return {"draft_dir": str(draft_dir), "canvas": [W, H], "fps": fps,
            "tracks": {"video": 1, "text": 1 if ttrack else 0, "audio": 1 if atrack else 0},
            "cover_jpg": cover_jpg, "meta": meta,
            "text_font": (str((edit_cfg.get("text") or {}).get("font") or DEFAULT_TEXT_FONT)
                          if ttrack else ""),
            "notes": list(font_notes)}


# ---------------------------------------------------------------- 自检
def write_draft_safe(data, tl, edit_cfg, drafts_dir, name, *, allow_replace, copy_media,
                     make_draft_cover=True):
    """`write_draft` 的外壳：把「同名草稿已存在」翻译成人能读的处置方式。

    为什么不让 `FileExistsError` 直接冒到终端：它的栈顶在第三方库里，
    用户看到的是「draft_folder.py 第 92 行」—— 完全不知道该删哪个目录。
    """
    try:
        return write_draft(data, tl, edit_cfg, drafts_dir, name,
                           allow_replace=allow_replace, copy_media=copy_media,
                           make_draft_cover=make_draft_cover)
    except FileExistsError:
        raise SystemExit(
            "草稿已存在且指定了 --no-replace：%s\n"
            "  二选一：① 换名字 --name <新名>；② 允许覆盖（去掉 --no-replace，"
            "旧工程会被整体替换）；③ 先手工备份再删掉那个目录。"
            % (drafts_dir / name))
    except ImportError as e:                 # 第三方库内部依赖缺失（如 pymediainfo）
        raise SystemExit("剪映草稿库依赖缺失：%s\n  重装：pip install -r requirements-edit.txt" % e)


def verify(draft_dir: pathlib.Path, tl: dict, edit_cfg: dict,
           missing=None) -> dict:
    """读回 `draft_content.json` 逐项核 —— **不信任写入函数的返回值**。

    核五件事：**画面轨非空**、画布/帧率、视频段起止与总时长、字幕条数与每一条起点、
    素材文件是否仍在；另把「缺镜」也算进来（`missing`）。
    任何一项不符 ⇒ `pass=False`，调用方以退出码 2 结束（这份工程不能拿去送审）。

    `missing` 为什么在自检里而不是在 `collect()` 里拦：缺镜时**仍要落草稿**，
    人要打开看缺了哪几段、时间轴从哪儿开始错；但结论必须是「不合格」。
    否则一份 19/20 镜的工程会顶着 `pass` 送去平台，等于自证素材不全。
    """
    fails, notes = [], []
    p = draft_dir / "draft_content.json"
    if not p.is_file():
        return {"pass": False, "fails": ["草稿里没有 draft_content.json：%s" % p], "notes": []}
    js = _read_json(p, {}) or {}

    # 结构性检查①：必须有真实画面段（封面图不算，cover 只是片头那一帧）
    real = [c for c in (tl.get("video") or []) if c.get("kind") == "video"]
    if not real:
        fails.append("时间轴里一段真实画面都没有（只有封面或空）⇒ 空工程不能作为送审材料")
    if missing:
        fails.append("缺 %d 镜成片，工程与母版不一致：%s ⇒ 先补出这几镜再重跑"
                     % (len(missing), "、".join(list(missing)[:8])))

    W = int(edit_cfg["canvas"]["width"])
    H = int(edit_cfg["canvas"]["height"])
    cc = js.get("canvas_config") or {}
    if int(cc.get("width") or 0) != W or int(cc.get("height") or 0) != H:
        fails.append("画布不符：草稿 %sx%s，要求 %dx%d"
                     % (cc.get("width"), cc.get("height"), W, H))
    if int(js.get("fps") or 0) and int(js["fps"]) != int(edit_cfg.get("fps") or DEFAULT_FPS):
        fails.append("帧率不符：草稿 %s，要求 %s" % (js["fps"], edit_cfg.get("fps")))

    tracks = js.get("tracks") or []
    by_type = {}
    for t in tracks:
        by_type.setdefault(t.get("type"), []).append(t)
    if len(by_type.get("video") or []) != 1:
        fails.append("视频轨数量 %d（应为 1）" % len(by_type.get("video") or []))
    vsegs = [s for t in (by_type.get("video") or []) for s in (t.get("segments") or [])]
    if len(vsegs) != len(tl["video"]):
        fails.append("视频片段 %d 个，时间轴要求 %d 个" % (len(vsegs), len(tl["video"])))
    else:
        for got, want in zip(sorted(vsegs, key=lambda s: (s.get("target_timerange") or {}).get("start", 0)),
                             tl["video"]):
            tr = got.get("target_timerange") or {}
            if int(tr.get("start", -1)) != want["start_us"]:
                fails.append("%s 起点 %s µs ≠ 预期 %d µs"
                             % (want["shot_id"], tr.get("start"), want["start_us"]))
            if int(tr.get("duration", -1)) != want["dur_us"]:
                fails.append("%s 时长 %s µs ≠ 预期 %d µs（源 %.3fs）"
                             % (want["shot_id"], tr.get("duration"), want["dur_us"],
                                want["dur_us"] / 1e6))
    tsegs = [s for t in (by_type.get("text") or []) for s in (t.get("segments") or [])]
    if len(tsegs) != len(tl["text"]):
        fails.append("字幕片段 %d 条，cues 有 %d 条" % (len(tsegs), len(tl["text"])))
    else:
        tsegs = sorted(tsegs, key=lambda s: (s.get("target_timerange") or {}).get("start", 0))
        for got, want in zip(tsegs, sorted(tl["text"], key=lambda c: c["start_us"])):
            tr = got.get("target_timerange") or {}
            if int(tr.get("start", -1)) != want["start_us"]:
                fails.append("字幕「%s」起点 %s µs ≠ 预期 %d µs（含封面偏移 %d µs）"
                             % (want["text"][:10], tr.get("start"), want["start_us"],
                                tl["cue_offset_us"]))
    asegs = [s for t in (by_type.get("audio") or []) for s in (t.get("segments") or [])]
    if len(asegs) != len(tl["audio"]):
        fails.append("BGM 片段 %d 段，计划 %d 段" % (len(asegs), len(tl["audio"])))

    # 素材可读性：绝对路径是剪映的口径，断链在剪映里表现为「素材丢失」
    mats = js.get("materials") or {}
    checked = 0
    for kind in ("videos", "audios"):
        for m in mats.get(kind) or []:
            fp = m.get("path") or ""
            if not fp:
                fails.append("素材缺 path 字段（%s）" % m.get("material_name") or "?")
                continue
            if not pathlib.Path(fp).is_file():
                fails.append("素材断链：%s" % fp)
            checked += 1

    # 总时长：以视频轨为准（音频轨可以更长，剪映会裁到主轨长度）
    got_total = sum(int((s.get("target_timerange") or {}).get("duration", 0)) for s in vsegs)
    want_total = sum(c["dur_us"] for c in tl["video"])
    if abs(got_total - want_total) > 1000:          # 容差 1ms（只容舍入）
        fails.append("视频轨总时长 %.3fs ≠ 预期 %.3fs"
                     % (got_total / 1e6, want_total / 1e6))

    notes.append("素材条目 %d 个全部可读" % checked)
    notes.append("视频 %d 段 / 字幕 %d 条 / BGM %d 段 / 总时长 %.3fs"
                 % (len(vsegs), len(tsegs), len(asegs), got_total / 1e6))

    # 首页元信息：剪映列表页的时长与缩略图只读这份 meta。
    # 写错不会让工程打不开，但会让卡片显示 00:00 + 黑块 —— 送审时等于自证「空工程」。
    meta = _read_json(draft_dir / "draft_meta_info.json", None)
    meta_note = "非明文 JSON（未改写）"
    if isinstance(meta, dict):
        tm = int(meta.get("tm_duration") or 0)
        if abs(tm - want_total) > 1000:
            fails.append("draft_meta_info.tm_duration=%d µs ≠ 时间轴 %.3fs"
                         " ⇒ 剪映首页会显示错误时长" % (tm, want_total / 1e6))
        cvp = meta.get("draft_cover") or ""
        if cvp and not pathlib.Path(cvp).is_file():
            fails.append("草稿缩略图断链：%s" % cvp)
        meta_note = "时长 %.3fs / 缩略图 %s" % (tm / 1e6, "有" if cvp else "无")
    notes.append("草稿首页元信息：%s" % meta_note)

    return {"pass": not fails, "fails": fails, "notes": notes,
            "total_s": round(got_total / 1e6, 3),
            "counts": {"video": len(vsegs), "text": len(tsegs), "audio": len(asegs),
                       "materials": checked}}


# ---------------------------------------------------------------- 清单
def _sha1(p: str) -> str:
    h = hashlib.sha1()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(data: dict, tl: dict, draft: dict, verdict: dict) -> dict:
    def entry(p: str, **extra):
        f = pathlib.Path(p)
        try:
            size = f.stat().st_size
            digest = _sha256(p)
        except OSError:
            size, digest = 0, ""
        row = {"path": str(f), "name": f.name, "bytes": size, "sha256": digest}
        row.update(extra)
        return row

    return {
        "version": 1,
        "ep": data["ep"],
        "generated_at": _now(),
        "engine": "pyJianYingDraft",
        "draft_dir": draft["draft_dir"],
        "canvas": {"width": draft["canvas"][0], "height": draft["canvas"][1]},
        "fps": draft["fps"],
        "tracks": {
            "video": [dict(entry(c["path"]), shot_id=c["shot_id"], start_s=_s(c["start_us"]),
                           dur_s=_s(c["dur_us"]), kind=c["kind"]) for c in tl["video"]],
            "text": [{"shot_id": c["shot_id"], "start_s": _s(c["start_us"]),
                      "end_s": _s(c["start_us"] + c["dur_us"]), "text": c["text"],
                      "source": c["source"]} for c in tl["text"]],
            "audio": [dict(entry(a["path"]), track=a["track"], start_s=_s(a["start_us"]),
                           dur_s=_s(a["dur_us"]), gain_db=a["gain_db"]) for a in tl["audio"]],
        },
        "cue_offset_us": tl["cue_offset_us"],
        "cue_offset_reason": tl["cue_offset_reason"],
        "cover": {"path": data["cover_path"], "seconds": data["cover_s"]},
        "cover_note": data["cover_msg"],
        "bgm_note": data["bgm_msg"],
        "total_duration_s": _s(tl["total_us"]),
        "verdict": verdict,
        "_note": "本清单是「工程 ↔ 成片」的对照表：外部可拿 sha256 回原文件核；"
                 "text 段的时间是母版时间轴（已含封面片头偏移）。",
    }


def _now() -> str:
    import datetime
    return datetime.datetime.now().astimezone().replace(microsecond=0).isoformat()


# ---------------------------------------------------------------- 主流程
def plan(ws: pathlib.Path, ep: str, opts) -> tuple:
    data = collect(ws, ep,
                   with_cover=not opts.no_cover, with_bgm=not opts.no_bgm,
                   allow_empty_subs=bool(opts.allow_empty_subtitles))
    edit_cfg = load_edit_config(ws)
    if opts.canvas:
        w, h = (int(x) for x in re.split(r"[x×]", opts.canvas.lower()))
        edit_cfg = _deep_merge(edit_cfg, {"canvas": {"width": w, "height": h}})
    if opts.fps:
        edit_cfg = _deep_merge(edit_cfg, {"fps": int(opts.fps)})
    tl = build_timeline(data, edit_cfg, with_subtitle=not getattr(opts, "no_subtitle", False))
    return data, edit_cfg, tl


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="生成剪映专业版工程（草稿）：逐镜视频 + 字幕 + BGM，与发布版同源")
    ap.add_argument("--workspace", default=os.environ.get("SOLODRAMA_WORKSPACE") or None,
                    help="剧项目根目录（默认取 SOLODRAMA_WORKSPACE）")
    ap.add_argument("--ep", required=True, help="集号，如 ep01")
    ap.add_argument("--drafts-dir", default=None,
                    help="剪映草稿根目录（剪映「全局设置-草稿位置」那个目录）；"
                         "不给则落 <ws>/07-成片/<ep>/_draft/")
    ap.add_argument("--to-jianying", dest="to_jianying", action="store_true",
                    help="直接生成到剪映「全局设置-草稿位置」（自动探测），"
                         "启动剪映首页就能看到这份工程")
    ap.add_argument("--no-draft-cover", dest="no_draft_cover", action="store_true",
                    help="不生成草稿缩略图 draft_cover.jpg（首页卡片会是黑块）")
    ap.add_argument("--name", default=None, help="草稿名，默认 <ep>_剪映工程")
    ap.add_argument("--canvas", default=None, help="覆盖画布，如 1080x1920")
    ap.add_argument("--fps", type=int, default=None, help="覆盖帧率，默认 30")
    ap.add_argument("--copy-media", dest="copy_media", action="store_true",
                    help="把素材拷进草稿目录（工程可整体搬走；体积翻倍）")
    ap.add_argument("--no-cover", dest="no_cover", action="store_true", help="工程不加首帧封面")
    ap.add_argument("--no-bgm", dest="no_bgm", action="store_true", help="工程不加 BGM 轨")
    ap.add_argument("--no-subtitle", dest="no_subtitle", action="store_true",
                    help="不出字幕轨（画面 + BGM 的干净工程）—— 留给剪映「识别字幕」；"
                         "识别出来的时间来自剪映自己的 ASR，通常比本仓库的 CTC/whisper 对齐更贴人声")
    ap.add_argument("--allow-empty-subtitles", dest="allow_empty_subtitles",
                    action="store_true", help="本集确实没有字幕时放行（默认拒绝）")
    ap.add_argument("--no-replace", dest="no_replace", action="store_true",
                    help="同名草稿已存在时报错，不覆盖")
    ap.add_argument("--dry-run", dest="dry_run", action="store_true", help="只打印时间轴，不写盘")
    ap.add_argument("--json", action="store_true", help="输出 JSON 摘要")
    a = ap.parse_args(argv)

    if not a.workspace:
        print("[FAIL] 没给 --workspace，也没有 SOLODRAMA_WORKSPACE。", file=sys.stderr)
        return EXIT_NOINPUT
    ws = pathlib.Path(a.workspace).expanduser().resolve()
    if not ws.is_dir():
        print("[FAIL] 工作区不存在：%s" % ws, file=sys.stderr)
        return EXIT_NOINPUT

    try:
        data, edit_cfg, tl = plan(ws, a.ep, a)
    except SystemExit as e:
        print("[FAIL] %s" % e, file=sys.stderr)
        return EXIT_NOINPUT

    ep = data["ep"]
    if data["missing_segments"]:
        # 只提示、不提前退出：草稿要落盘（人得看缺在哪），但 verify() 会把它判成不合格
        print("[WARN] 这些镜缺成片，工程里不会有它们（结论将判不合格）：%s"
              % "、".join(data["missing_segments"][:8]), file=sys.stderr)

    if a.dry_run:
        _print_plan(data, tl)
        return EXIT_OK

    drafts_dir = pathlib.Path(a.drafts_dir).expanduser().resolve() if a.drafts_dir \
        else (data["out_root"] / ep / "_draft")
    drafts_src = "命令行 --drafts-dir"
    if not a.drafts_dir and a.to_jianying:
        root, why = detect_jianying_root()
        if root is None:
            print("[FAIL] --to-jianying 没能定位剪映草稿目录：%s\n"
                  "  改用 --drafts-dir 显式指定剪映「全局设置-草稿位置」。"
                  % why, file=sys.stderr)
            return EXIT_NOINPUT
        drafts_dir, drafts_src = root, "剪映草稿根目录（%s）" % why
    elif not a.drafts_dir:
        drafts_src = "项目内 _draft/（默认；加 --to-jianying 可直接进剪映）"
    name = a.name or ("%s_剪映工程" % ep)
    try:
        draft = write_draft_safe(data, tl, edit_cfg, drafts_dir, name,
                                 allow_replace=not a.no_replace, copy_media=a.copy_media,
                                 make_draft_cover=not a.no_draft_cover)
    except SystemExit as e:
        print("[FAIL] %s" % e, file=sys.stderr)
        return EXIT_FAIL
    verdict = verify(pathlib.Path(draft["draft_dir"]), tl, edit_cfg,
                     missing=data["missing_segments"])
    # 字幕与音频的同步体检：只诊断不改时间（改时间归 subtitle.py）。
    #   对齐错位是「沉默的错」—— 不断言、不报错，只在画面里静静错着。
    #   所以每次出工程都算一遍，把「哪条压静音」写进 manifest，让审核能追。
    sync = (sync_check(data) if tl["text"]
            else {"checked": 0, "skipped": 0, "suspects": [], "min_voiced_s": 0.12})

    manifest = build_manifest(data, tl, draft, verdict)
    manifest["sync"] = sync
    # 清单/报告落两处，各管一件事：
    #   ① 项目内 `07-成片/<ep>/_draft/` —— 节点判据只认这里（nodes.py::_is_draft），
    #      而且送审打包时材料要跟着剧目录走，不能只存在剪映的草稿库里；
    #   ② 草稿目录内 —— 草稿被整体搬走/拷给别人时，哈希清单跟着一起走。
    # 早先只写 `drafts_dir`，`--to-jianying` 时会把 draft_manifest.json 直接扔进剪映
    # 草稿**根目录**，等于在别人的库里丢垃圾。
    proj_draft = data["out_root"] / ep / "_draft"
    proj_draft.mkdir(parents=True, exist_ok=True)
    mpath = proj_draft / DRAFT_DIR_NAME
    _write_json(mpath, manifest)
    ddir = pathlib.Path(draft["draft_dir"])
    if ddir.resolve() != proj_draft.resolve():
        _write_json(ddir / DRAFT_DIR_NAME, manifest)
    report = {"at": _now(), "ep": ep, "draft": draft, "verify": verdict,
              "manifest": str(mpath), "draft_manifest_in_draft": str(ddir / DRAFT_DIR_NAME),
              "cue_offset_us": tl["cue_offset_us"], "sync": sync,
              "skipped": list(tl.get("skipped") or []),
              "totals": {"segments": len(data["clips"]), "cues": len(data["cues"]),
                         "bgm": len(tl["audio"]),
                         "total_s": _s(tl["total_us"])}}
    _write_json(proj_draft / REPORT_NAME, report)
    if ddir.resolve() != proj_draft.resolve():
        _write_json(ddir / REPORT_NAME, report)

    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("=" * 74)
        print("剪映工程 · %s" % ep)
        print("=" * 74)
        print("  草稿目录  %s" % draft["draft_dir"])
        print("  位置来源  %s" % drafts_src)
        print("  画布      %dx%d @ %dfps" % (draft["canvas"][0], draft["canvas"][1], draft["fps"]))
        print("  视频轨    %d 段（封面 %s）" % (len(tl["video"]),
                                          ("%.2fs" % data["cover_s"]) if data["cover_path"] else "无"))
        if tl["text"]:
            print("  字幕轨    %d 条（整体后移 %d µs：%s）"
                  % (len(tl["text"]), tl["cue_offset_us"], tl["cue_offset_reason"]))
            if not sync.get("checked"):
                print("  字幕同步  未核（缺 <subs>/asr/<shot>.wav，没有声学依据）")
            else:
                print("  字幕同步  %d 条已核，%d 条找不到连续人声"
                      % (sync["checked"], len(sync["suspects"])))
                for s in sync["suspects"][:5]:
                    print("    ⚠ %s %.2f–%.2f 最长连续人声仅 %.2fs：「%s」—— "
                          "用 subtitle.py --from-srt 或重跑对齐"
                          % (s["shot_id"], s["start"], s["end"],
                             s["voiced_s"], s["text"]))
        else:
            print("  字幕轨    未生成（--no-subtitle：留给剪映「识别字幕」，"
                  "识别完照样式卡统一位置与字体）")
        print("  BGM 轨    %d 段%s" % (len(tl["audio"]), ("（%s）" % data["bgm_msg"]) if data["bgm_msg"] else ""))
        print("  总时长    %.3fs" % (tl["total_us"] / 1e6))
        _meta = draft.get("meta") or {}
        if _meta.get("written"):
            print("  首页信息  时长 %s / 缩略图 %s"
                  % ("%.3fs" % (_meta.get("tm_duration", 0) / 1e6),
                     "已生成" if _meta.get("draft_cover") else "未生成（首页显示黑块）"))
        else:
            print("  首页信息  [WARN] %s" % (_meta.get("reason") or "未写入"))
        print("  清单      %s" % mpath)
        print("  报告      %s" % (proj_draft / REPORT_NAME))
        for w in (tl.get("skipped") or []):
            print("  [WARN] %s" % w)
        if verdict["pass"]:
            print("\n[OK] 自检通过：%s" % "；".join(verdict["notes"]))
        else:
            print("\n[FAIL] 自检不过 —— 这份工程**不能**作为送审材料：")
            for f in verdict["fails"]:
                print("       · %s" % f)
        print("\n  打开方式：① 加 --to-jianying 重新生成，工程直接落进剪映草稿位置，"
              "启动剪映首页即可见；\n"
              "            ② 手工把 %s 整个目录搬进剪映「全局设置-草稿位置」。"
              % draft["draft_dir"])
        print("  字幕字号为近似映射（%s）" % TEXT_SIZE_NOTE)

    return EXIT_OK if verdict["pass"] else EXIT_FAIL


def _print_plan(data: dict, tl: dict) -> None:
    print("=" * 74)
    print("剪映工程时间轴（dry-run，不写盘）· %s" % data["ep"])
    print("=" * 74)
    print("  %-9s %-9s %-9s %s" % ("轨", "起点", "时长", "内容"))
    for c in tl["video"]:
        print("  %-9s %-9s %-9s %s"
              % ("视频", "%.3fs" % _s(c["start_us"]), "%.3fs" % _s(c["dur_us"]),
                 "%s  %s" % (c["shot_id"], pathlib.Path(c["path"]).name)))
    for c in tl["text"]:
        print("  %-9s %-9s %-9s %s"
              % ("字幕", "%.3fs" % _s(c["start_us"]), "%.3fs" % _s(c["dur_us"]), c["text"][:28]))
    for a in tl["audio"]:
        print("  %-9s %-9s %-9s %s  (%.1f dB)"
              % ("BGM", "%.3fs" % _s(a["start_us"]), "%.3fs" % _s(a["dur_us"]),
                 a["track"], a["gain_db"]))
    print("\n  合计 %.3fs ｜ 字幕偏移 %d µs（%s）"
          % (tl["total_us"] / 1e6, tl["cue_offset_us"], tl["cue_offset_reason"]))


if __name__ == "__main__":
    sys.exit(main())
