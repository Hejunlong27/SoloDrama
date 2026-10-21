#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""bgm.py —— BGM（配乐）库、铺排计划与混音（唯一真源）

为什么是「库 + 后期混音」，而不是「让视频模型一起生成 BGM」
----------------------------------------------------------
短剧的 BGM 有三个硬需求，生成模型目前都给不了：

1. **贯穿整集、可循环**：BGM 是按情绪段落的连续铺底，模型逐段生成 ⇒ 段与段之间
   调性/节拍/混响不连续，拼起来像换了三首曲子。
2. **可换、可调、可避版权**：发布到 TikTok 要商用授权；AI 生成音乐的商用条款各家不同，
   平台 Content ID 也可能误判。库里的曲目可换、可留授权凭证。
3. **不能盖对白**：短剧 80% 信息在对白里，BGM 必须 ducking（说话时自动压下去）。

所以本模块的定位：**H3 只负责画面与同期声（diegetic sound），BGM 在后期铺**。
提示词侧配套约束见 `convert_storyboard.py` 的 `[AUDIO]` 段（显式禁止模型自造配乐，
否则会与后期 BGM 打架：双重铺底、相位抵消、音量台阶）。

库的两种位置
------------
* **项目库**：`<ws>/04-资产/bgm/`（本剧专用素材）
* **共享库**：`<引擎仓库>/stages/production/assets/bgm/`（跨剧复用；音频文件不进 git，
  只提交 `bgm-library.json` 与 README）

解析顺序：项目库优先，同名 id 覆盖共享库。

库清单 `bgm-library.json`
------------------------
```json
{
  "version": 1,
  "tracks": [
    {"id": "tension_low_01", "file": "tension_low_01.mp3",
     "moods": ["tension", "suspense"], "bpm": 88, "duration": 128.4, "loop": true,
     "license": "licensed", "source": "Artlist 订阅（凭证 2026-03-xx）",
     "license_note": "可商用，禁止转售原曲", "gain_db": -22}
  ]
}
```
`license` 只接受 `owned` / `licensed` / `cc0` / `generated`；`generated`（AI 生成）必须写
`license_note` 说明商用条款 —— 这是发行合规的一部分，缺了 `check` 直接拦。

铺排计划 `bgm-plan.json`（每集一份，落 `07-成片/subs/<ep>/`）
------------------------------------------------------------
```json
{
  "ep": "ep01",
  "total_s": 62.4,
  "voice": "h3",
  "ducking": {"enabled": true, "threshold": 0.05, "ratio": 6, "attack": 20, "release": 350},
  "segments": [
    {"track": "tension_low_01", "start": 0.0, "end": 62.4, "gain_db": -22,
     "fade_in": 1.5, "fade_out": 2.5, "loop": true, "note": "整集铺底"}
  ]
}
```

命令
----
    python bgm.py library [--scan] [--json]     看库（--scan 用 ffprobe 补时长/BPM 缺失项）
    python bgm.py plan --ep ep01 [--mood tension] [--apply]    生成铺排计划
    python bgm.py check --ep ep01 [--json]      门禁（退出码 2 = 不可混）
    python bgm.py mix --ep ep01 [--apply]       混音（默认干跑，打印 ffmpeg 命令）
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
import _layout as L                                              # noqa: E402

LIB_NAME = "bgm-library.json"
PLAN_SUFFIX = "_bgm-plan.json"
LICENSE_CHOICES = ("owned", "licensed", "cc0", "generated")
EXIT_NOT_READY = 2

# 情绪 ↔ 默认增益／淡入淡出（短剧口径：BGM 常年在 -22dB 附近，说话时被压到 -30 以下）
MOOD_DEFAULTS = {
    "tension": {"gain_db": -22.0, "fade_in": 1.5, "fade_out": 2.5},
    "sad": {"gain_db": -24.0, "fade_in": 2.0, "fade_out": 3.0},
    "warm": {"gain_db": -21.0, "fade_in": 1.5, "fade_out": 2.5},
    "revenge": {"gain_db": -20.0, "fade_in": 0.8, "fade_out": 2.0},
    "suspense": {"gain_db": -23.0, "fade_in": 1.2, "fade_out": 2.2},
    "epic": {"gain_db": -19.0, "fade_in": 1.0, "fade_out": 2.5},
}
DEFAULT_MOOD = "tension"

# 题材 → 默认情绪（与 generation-brief / 题材公式的 id 对齐，认不出用 default）
GENRE_MOOD = {
    "revenge": "revenge", "逆袭": "revenge", "复仇": "revenge",
    "sweet": "warm", "甜宠": "warm", "family": "warm", "家庭": "warm",
    "suspense": "suspense", "悬疑": "suspense", "狼人": "suspense", "奇幻": "epic",
}


# ---------------------------------------------------------------------------
# 路径与工具
# ---------------------------------------------------------------------------
def _ws(ws=None) -> pathlib.Path:
    if ws:
        return pathlib.Path(ws).expanduser().resolve()
    env = os.environ.get("SOLODRAMA_WORKSPACE") or os.environ.get("DRAMA_WORKSPACE")
    if env and pathlib.Path(env).is_dir():
        return pathlib.Path(env).expanduser().resolve()
    sys.exit("[FAIL] 找不到短剧工作区：给 --workspace 或设 SOLODRAMA_WORKSPACE")


def project_lib_dir(ws: pathlib.Path) -> pathlib.Path:
    return L.stage_dir(ws, "assets") / "bgm"


def shared_lib_dir() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parents[1] / "assets" / "bgm"


def subs_dir(ws: pathlib.Path, ep: str) -> pathlib.Path:
    return L.out_dir(ws) / "subs" / ep


def plan_path(ws: pathlib.Path, ep: str) -> pathlib.Path:
    return subs_dir(ws, ep) / ("%s%s" % (ep, PLAN_SUFFIX))


def tool(name: str) -> str:
    """ffmpeg / ffprobe 解析：环境变量 → PATH → 常见安装位置。"""
    env = os.environ.get(name.upper())
    if env and pathlib.Path(env).is_file():
        return env
    hit = shutil.which(name)
    if hit:
        return hit
    for c in (r"C:\ffmpeg\bin\%s.exe" % name, "/usr/local/bin/%s" % name, "/usr/bin/%s" % name):
        if pathlib.Path(c).is_file():
            return c
    return name


# ---------------------------------------------------------------------------
# 库
# ---------------------------------------------------------------------------
def _read_lib(root: pathlib.Path) -> dict:
    p = root / LIB_NAME
    if not p.is_file():
        return {"version": 1, "tracks": [], "_missing": str(p)}
    try:
        d = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, ValueError) as e:
        return {"version": 1, "tracks": [], "_error": "%s: %s" % (p, e)}
    if isinstance(d, list):
        d = {"version": 1, "tracks": d}
    d.setdefault("tracks", [])
    d["_path"] = str(p)
    return d


def load_library(ws: pathlib.Path) -> dict:
    """合并共享库 + 项目库（项目库同名 id 覆盖）。"""
    shared = _read_lib(shared_lib_dir())
    proj = _read_lib(project_lib_dir(ws))
    by_id = {}
    for t in (shared.get("tracks") or []):
        if isinstance(t, dict) and t.get("id"):
            t = dict(t)
            t["_root"] = str(shared_lib_dir())
            by_id[str(t["id"])] = t
    for t in (proj.get("tracks") or []):
        if isinstance(t, dict) and t.get("id"):
            t = dict(t)
            t["_root"] = str(project_lib_dir(ws))
            by_id[str(t["id"])] = t
    return {"tracks": list(by_id.values()),
            "project": {"path": proj.get("_path"), "count": len(proj.get("tracks") or []),
                        "missing": proj.get("_missing"), "error": proj.get("_error")},
            "shared": {"path": shared.get("_path"), "count": len(shared.get("tracks") or [])}}


def track_file(t: dict) -> pathlib.Path:
    root = pathlib.Path(t.get("_root") or "")
    f = pathlib.Path(str(t.get("file") or ""))
    return f if f.is_absolute() else (root / f)


def _probe(path: pathlib.Path) -> dict:
    """ffprobe 读时长/采样率（只读本地文件，不联网）。"""
    out = {"duration": None, "ok": False, "error": ""}
    try:
        r = subprocess.run([tool("ffprobe"), "-v", "error", "-show_entries",
                            "format=duration:stream=codec_type,sample_rate",
                            "-of", "json", str(path)],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            out["error"] = (r.stderr or "").strip()[:200]
            return out
        d = json.loads(r.stdout or "{}")
        try:
            out["duration"] = round(float(d["format"]["duration"]), 2)
        except (KeyError, TypeError, ValueError):
            pass
        out["ok"] = True
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as e:
        out["error"] = "%s: %s" % (type(e).__name__, str(e)[:150])
    return out


def scan(ws: pathlib.Path) -> dict:
    """用 ffprobe 补齐库条目的时长（BPM 不猜，只保留人工填的值）。"""
    lib = load_library(ws)
    filled, failed = [], []
    for t in lib["tracks"]:
        f = track_file(t)
        if not f.is_file():
            failed.append({"id": t.get("id"), "file": str(f), "error": "文件不存在"})
            continue
        got = _probe(f)
        if got["ok"] and got["duration"]:
            if not t.get("duration"):
                t["duration"] = got["duration"]
                filled.append(t["id"])
        else:
            failed.append({"id": t.get("id"), "file": str(f), "error": got["error"] or "读不到时长"})
    return {"library": lib, "filled": filled, "failed": failed}


# ---------------------------------------------------------------------------
# 集时长与默认情绪
# ---------------------------------------------------------------------------
def _data_dirs(ws: pathlib.Path) -> list:
    """出片输入目录的候选（布局真源 + 两个历史落点；交付报告里的 9.1 就是「三个脚本三个目录」）。"""
    out = []
    try:
        out.append(L.data_dir(ws))
    except Exception:                                            # noqa: BLE001
        pass
    try:
        pd = L.stage_dir(ws, "prompts")
        out += [pd, pd / "data"]
    except Exception:                                            # noqa: BLE001
        pass
    seen, uniq = set(), []
    for d in out:
        k = str(d).lower()
        if k not in seen:
            seen.add(k)
            uniq.append(d)
    return uniq


def ep_duration(ws: pathlib.Path, ep: str) -> float:
    """整集成片时长：优先 ffprobe 母版；否则按 `h3_prompts.json` 的 duration 求和。"""
    for name in ("%s_master_2k.mp4" % ep, "%s_master.mp4" % ep, "%s_subbed.mp4" % ep):
        p = subs_dir(ws, ep) / name
        if p.is_file():
            got = _probe(p)
            if got.get("duration"):
                return float(got["duration"])
    import re
    for d in _data_dirs(ws):
        hp = d / "h3_prompts.json"
        if not hp.is_file():
            continue
        try:
            obj = json.loads(hp.read_text(encoding="utf-8-sig"))
            tot = 0.0
            for sid, v in (obj or {}).items():
                s = str(sid).lower()
                # 带集号就只算本集；不带集号（shot_01）全算
                m = re.search(r"(?:^|[_-])ep0*(\d+)(?:[_-]|$)", s)
                if m:
                    n = int(m.group(1))
                    want = int(re.sub(r"[^\d]", "", ep) or 0)
                    if n != want:
                        continue
                try:
                    tot += float((v or {}).get("duration") or 0)
                except (TypeError, ValueError):
                    pass
            if tot > 0:
                return round(tot, 2)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
    return 0.0


def ep_voice(ws: pathlib.Path) -> str:
    """声音归属（与 project-setup / h3_prompts 一致）：h3 / external / mute。"""
    try:
        p = ws / "project-setup.json"
        d = json.loads(p.read_text(encoding="utf-8-sig"))
        v = str(((d.get("video_options") or {}).get("voice")) or "").strip()
        if v in ("h3", "external", "mute"):
            return v
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return "h3"


def guess_mood(ws: pathlib.Path, ep: str) -> str:
    """从题材/情绪规划猜一个默认情绪；认不出用 DEFAULT_MOOD（不猜细节，只给基线）。"""
    script = L.stage_dir(ws, "script")
    for name in ("blueprint.json", "genre-plan.json"):
        p = script / name
        if not p.is_file():
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        for key in ("genre", "genre_id", "formula", "theme", "genre_direction"):
            v = str((d or {}).get(key) or "")
            for k, mood in GENRE_MOOD.items():
                if k in v:
                    return mood
    return DEFAULT_MOOD


# ---------------------------------------------------------------------------
# 计划
# ---------------------------------------------------------------------------
def _recent_usage(ws: pathlib.Path) -> dict:
    """{track_id: 最近使用它的集号}（扫已有 `<ep>_bgm-plan.json`）。

    用途：整剧几十集，同一首曲连续出现会被平台判"相似内容"降流（库 README 的纪律）。
    这里给"最久没用过的优先"——不需要维护额外状态，计划文件本身就是记录。
    """
    out = {}
    base = L.out_dir(ws) / "subs"
    if not base.is_dir():
        return out
    for d in base.iterdir():
        m = re.match(r"ep0*(\d+)$", d.name, re.I)
        if not m or not d.is_dir():
            continue
        n = int(m.group(1))
        pp = d / ("%s%s" % (d.name, PLAN_SUFFIX))
        if not pp.is_file():
            continue
        try:
            pl = json.loads(pp.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        for seg in (pl.get("segments") or []):
            tid = str(seg.get("track") or "")
            if tid:
                out[tid] = max(out.get(tid, 0), n)
    return out


def make_plan(ws: pathlib.Path, ep: str, mood: str = None, track_id: str = None,
              gain_db: float = None, segments: int = 1) -> dict:
    """生成铺排计划：默认整集一首、淡入淡出、开 ducking。

    `segments` > 1 时按等分切段（第二段起用同一首曲的不同起点），便于后续人工改成多首。
    """
    lib = load_library(ws)
    total = ep_duration(ws, ep)
    mood = mood or guess_mood(ws, ep)
    dflt = MOOD_DEFAULTS.get(mood, MOOD_DEFAULTS[DEFAULT_MOOD])

    pool = [t for t in lib["tracks"]
            if not t.get("moods") or mood in (t.get("moods") or [])]
    if track_id:
        pool = [t for t in lib["tracks"] if str(t.get("id")) == track_id] or pool
    if not pool:
        return {"ep": ep, "total_s": total, "voice": ep_voice(ws), "mood": mood,
                "segments": [], "_error": "库里没有可用曲目（先放素材并写 bgm-library.json，"
                                          "或跑 bgm.py library --scan）"}
    usage = _recent_usage(ws)
    # 选曲优先"最久没用过"：从未用过的排最前（-1），其次是上次用得很早的
    pool.sort(key=lambda t: (usage.get(str(t.get("id")), -1), str(t.get("id"))))
    track = pool[0]
    # 增益优先级：命令行 > 曲目建议值（license 授权时按曲目登记的最稳）> 情绪默认
    try:
        track_gain = track.get("gain_db")
        track_gain = float(track_gain) if track_gain is not None else None
    except (TypeError, ValueError):
        track_gain = None
    gain = float(gain_db if gain_db is not None
                 else (track_gain if track_gain is not None else dflt["gain_db"]))
    tid = str(track.get("id"))
    segs = []
    n = max(1, int(segments))
    if total <= 0:
        segs = [{"track": tid, "start": 0.0, "end": 0.0, "gain_db": gain,
                 "fade_in": dflt["fade_in"], "fade_out": dflt["fade_out"],
                 "loop": bool(track.get("loop", True)), "note": "总时长未知，先补母版再 plan"}]
    else:
        step = round(total / n, 2)
        for i in range(n):
            s = round(i * step, 2)
            e = total if i == n - 1 else round((i + 1) * step, 2)
            segs.append({"track": tid, "start": s, "end": e, "gain_db": gain,
                         "fade_in": 0.8 if i else dflt["fade_in"],
                         "fade_out": dflt["fade_out"],
                         "loop": bool(track.get("loop", True)),
                         "note": "整集铺底" if n == 1 else "第 %d/%d 段" % (i + 1, n)})
    return {"ep": ep, "total_s": total, "voice": ep_voice(ws), "mood": mood,
            "ducking": {"enabled": True, "threshold": 0.05, "ratio": 6,
                        "attack": 20, "release": 350},
            "segments": segs,
            "_note": "由 bgm.py plan 生成；可手工改 gain_db / 换 track / 加段，改完跑 check"}


# ---------------------------------------------------------------------------
# 门禁
# ---------------------------------------------------------------------------
def check_plan(ws: pathlib.Path, plan: dict) -> list:
    """返回问题列表 [{"level": "hard|warn", "code": "...", "msg": "..."}]。"""
    out = []
    lib = {str(t.get("id")): t for t in load_library(ws)["tracks"]}
    total = float(plan.get("total_s") or 0)
    segs = plan.get("segments") or []
    if not segs:
        out.append({"level": "hard", "code": "B001", "msg": "没有任何 BGM 段（segments 为空）"})
        return out
    covered = 0.0
    for i, s in enumerate(segs, 1):
        tid = str(s.get("track") or "")
        t = lib.get(tid)
        if not t:
            out.append({"level": "hard", "code": "B002",
                        "msg": "第 %d 段引用了库里不存在的曲目：%s" % (i, tid)})
            continue
        f = track_file(t)
        if not f.is_file():
            out.append({"level": "hard", "code": "B003",
                        "msg": "第 %d 段曲目文件不存在：%s" % (i, f)})
        lic = str(t.get("license") or "")
        if lic not in LICENSE_CHOICES:
            out.append({"level": "hard", "code": "B004",
                        "msg": "曲目 %s 的 license 非法或缺失（%r），可选 %s —— 发行合规必须写清"
                               % (tid, lic, "/".join(LICENSE_CHOICES))})
        elif lic == "generated" and not str(t.get("license_note") or "").strip():
            out.append({"level": "hard", "code": "B005",
                        "msg": "曲目 %s 是 AI 生成（license=generated），必须写 license_note "
                               "说明商用条款（平台审核与 Content ID 争议都要用）" % tid})
        try:
            a, b = float(s.get("start") or 0), float(s.get("end") or 0)
        except (TypeError, ValueError):
            out.append({"level": "hard", "code": "B006", "msg": "第 %d 段 start/end 不是数字" % i})
            continue
        if b <= a:
            out.append({"level": "hard", "code": "B007",
                        "msg": "第 %d 段 end(%.2f) <= start(%.2f)" % (i, b, a)})
        covered += max(0.0, b - a)
        gain = s.get("gain_db")
        try:
            g = float(gain)
        except (TypeError, ValueError):
            g = None
        if g is None:
            out.append({"level": "warn", "code": "B008", "msg": "第 %d 段没写 gain_db" % i})
        elif g > -6:
            out.append({"level": "hard", "code": "B009",
                        "msg": "第 %d 段 gain_db=%.1f dB 太高（> -6），会压住对白" % (i, g)})
        elif g < -30:
            out.append({"level": "warn", "code": "B010",
                        "msg": "第 %d 段 gain_db=%.1f dB 过低，基本听不见" % (i, g)})
        if total and b > total + 0.5:
            out.append({"level": "warn", "code": "B011",
                        "msg": "第 %d 段超出成片时长（end %.2f > total %.2f）" % (i, b, total)})
    if total and covered < total * 0.9:
        out.append({"level": "hard", "code": "B012",
                    "msg": "BGM 只覆盖 %.1fs / %.1fs（<90%%），结尾会突然安静" % (covered, total)})
    if str(plan.get("voice") or "") == "h3" and not (plan.get("ducking") or {}).get("enabled"):
        out.append({"level": "hard", "code": "B013",
                    "msg": "voice=h3（模型自带音轨）却关掉了 ducking —— 对白会被 BGM 盖住"})
    return out


# ---------------------------------------------------------------------------
# 混音
# ---------------------------------------------------------------------------
def build_mix_cmd(ws: pathlib.Path, plan: dict, base: pathlib.Path, out: pathlib.Path) -> list:
    """拼 ffmpeg 命令：视频 copy，音频 = 主音轨 + BGM（含淡入淡出、延时、ducking）。"""
    lib = {str(t.get("id")): t for t in load_library(ws)["tracks"]}
    total = float(plan.get("total_s") or 0)
    segs = [s for s in (plan.get("segments") or []) if float(s.get("end") or 0) > float(s.get("start") or 0)]
    cmd = [tool("ffmpeg"), "-hide_banner", "-nostats", "-v", "error", "-y",
           "-i", str(base)]
    inputs = []
    for s in segs:
        t = lib[str(s.get("track"))]
        if bool(s.get("loop", t.get("loop", True))):
            cmd += ["-stream_loop", "-1"]
        cmd += ["-i", str(track_file(t))]
        inputs.append(s)

    chains, labels = [], []
    for i, s in enumerate(inputs, start=1):
        a, b = float(s.get("start") or 0), float(s.get("end") or 0)
        dur = b - a
        gi = max(0.0, float(s.get("fade_in") or 0))
        go = max(0.0, float(s.get("fade_out") or 0))
        gain = float(s.get("gain_db") or -22)
        parts = ["atrim=0:%.3f" % dur, "asetpts=PTS-STARTPTS", "volume=%.1fdB" % gain]
        if gi > 0:
            parts.append("afade=t=in:st=0:d=%.3f" % gi)
        if go > 0 and dur > go:
            parts.append("afade=t=out:st=%.3f:d=%.3f" % (dur - go, go))
        if a > 0:
            parts.append("adelay=%d:all=1" % int(round(a * 1000)))
        parts.append("apad=whole_dur=%.3f" % (total or dur))
        chains.append("[%d:a]%s[b%d]" % (i, ",".join(parts), i))
        labels.append("[b%d]" % i)

    duck = plan.get("ducking") or {}
    if len(labels) > 1:
        chains.append("%samix=inputs=%d:duration=longest:normalize=0[bg]"
                      % ("".join(labels), len(labels)))
        bg = "[bg]"
    else:
        bg = labels[0]
    if duck.get("enabled") and len(inputs):
        chains.append("[0:a]asplit=2[vo][sc]")
        chains.append("%s[sc]sidechaincompress=threshold=%.3f:ratio=%.1f:attack=%d:release=%d[bd]"
                      % (bg, float(duck.get("threshold") or 0.05),
                         float(duck.get("ratio") or 6), int(duck.get("attack") or 20),
                         int(duck.get("release") or 350)))
        chains.append("[vo][bd]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]")
    else:
        chains.append("[0:a]%samix=inputs=2:duration=first:normalize=0[aout]" % bg)

    cmd += ["-filter_complex", ";".join(chains),
            "-map", "0:v:0", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", str(out)]
    return cmd


def target_video(ws: pathlib.Path, ep: str) -> pathlib.Path:
    """混哪一条：优先 2K 母版（字幕烧在它上面），其次带字幕成片，再次 1440 母版。"""
    d = subs_dir(ws, ep)
    for name in ("%s_master_2k.mp4" % ep, "%s_subbed.mp4" % ep, "%s_master.mp4" % ep):
        p = d / name
        if p.is_file():
            return p
    return d / ("%s_master_2k.mp4" % ep)


def mix_episode(ws: pathlib.Path, plan: dict, base: pathlib.Path = None,
                out: pathlib.Path = None, apply: bool = False) -> dict:
    """按计划混音。返回 {ok, cmd, out, error}；apply=False 时只构建不执行。"""
    ep = str(plan.get("ep") or "")
    base = base or target_video(ws, ep)
    out = out or (subs_dir(ws, ep) / ("%s_mix.mp4" % ep))
    issues = check_plan(ws, plan)
    hard = [i for i in issues if i["level"] == "hard"]
    if hard:
        return {"ok": False, "error": "; ".join(i["msg"] for i in hard[:4]), "issues": issues}
    if not pathlib.Path(base).is_file():
        return {"ok": False, "error": "找不到要混音的母版：%s（先跑 --stage master / upscale）"
                                     % base, "issues": issues}
    cmd = build_mix_cmd(ws, plan, pathlib.Path(base), pathlib.Path(out))
    if not apply:
        return {"ok": True, "dry_run": True, "cmd": " ".join(cmd), "out": str(out),
                "issues": issues}
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        return {"ok": False, "cmd": " ".join(cmd), "out": str(out),
                "error": (r.stderr or "").strip()[:600], "issues": issues}
    got = _probe(pathlib.Path(out))
    return {"ok": pathlib.Path(out).is_file(), "out": str(out), "duration": got.get("duration"),
            "cmd": " ".join(cmd), "issues": issues}


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------
def render_library(lib: dict, ws: pathlib.Path = None) -> str:
    root_proj = project_lib_dir(ws) if ws else "<ws>/04-资产/bgm"
    L_ = ["=" * 78, "BGM 库", "=" * 78]
    proj, shared = lib["project"], lib["shared"]
    L_.append("项目库：%s（%d 条）" % (proj.get("path") or root_proj, proj.get("count") or 0))
    if proj.get("missing"):
        L_.append("        ★ 还不存在：%s" % proj["missing"])
    if proj.get("error"):
        L_.append("        [WARN] 解析失败：%s" % proj["error"])
    L_.append("共享库：%s（%d 条）" % (shared.get("path"), shared.get("count") or 0))
    L_.append("-" * 78)
    if not lib["tracks"]:
        L_.append("（库里没有曲目）")
        L_.append("")
        L_.append("怎么建库：")
        L_.append("  1) 把音频放进 %s（或共享库 %s）" % (root_proj, shared_lib_dir()))
        L_.append("  2) 写 %s，每条至少给 id / file / moods / license / source" % LIB_NAME)
        L_.append("  3) 跑 `bgm.py library --scan` 用 ffprobe 自动补时长")
        L_.append("  4) 跑 `bgm.py plan --ep ep01 --apply` 生成铺排计划")
        L_.append("=" * 78)
        return "\n".join(L_)
    L_.append("%-22s %-10s %-6s %-8s %-11s %s" % ("id", "情绪", "BPM", "时长", "许可", "文件"))
    L_.append("-" * 78)
    for t in lib["tracks"]:
        f = track_file(t)
        L_.append("%-22s %-10s %-6s %-8s %-11s %s%s"
                  % (str(t.get("id"))[:22], ",".join(t.get("moods") or [])[:10] or "-",
                     t.get("bpm") or "-", t.get("duration") or "-",
                     t.get("license") or "★缺", f.name, "" if f.is_file() else "  ← 文件不存在"))
    L_.append("=" * 78)
    return "\n".join(L_)


def render_plan(plan: dict, issues: list) -> str:
    L_ = ["=" * 78, "BGM 铺排计划：%s" % plan.get("ep"), "=" * 78]
    L_.append("成片时长：%ss ｜ 情绪：%s ｜ 声音归属：%s ｜ ducking：%s"
              % (plan.get("total_s") or "?", plan.get("mood") or "-",
                 plan.get("voice") or "-",
                 "开" if (plan.get("ducking") or {}).get("enabled") else "关"))
    if plan.get("_error"):
        L_.append("★ %s" % plan["_error"])
    L_.append("-" * 78)
    L_.append("%-4s %-22s %-14s %-8s %-6s %s" % ("#", "曲目", "时间线", "增益", "淡入/出", "循环"))
    L_.append("-" * 78)
    for i, s in enumerate(plan.get("segments") or [], 1):
        L_.append("%-4d %-22s %-14s %-8s %-6s %s"
                  % (i, str(s.get("track"))[:22],
                     "%.1f–%.1fs" % (float(s.get("start") or 0), float(s.get("end") or 0)),
                     "%.1f dB" % float(s.get("gain_db") or 0),
                     "%.1f/%.1f" % (float(s.get("fade_in") or 0), float(s.get("fade_out") or 0)),
                     "是" if s.get("loop") else "否"))
    L_.append("-" * 78)
    if issues:
        L_.append("门禁：%d 个问题" % len(issues))
        for i in issues:
            L_.append("  [%s] %s %s" % ("FAIL" if i["level"] == "hard" else "WARN",
                                        i["code"], i["msg"]))
    else:
        L_.append("门禁：通过（可混音）")
    L_.append("=" * 78)
    return "\n".join(L_)


# ---------------------------------------------------------------------------
# 命令
# ---------------------------------------------------------------------------
def cmd_library(a) -> int:
    ws = _ws(a.workspace)
    if a.scan:
        got = scan(ws)
        if got["filled"]:
            print("[OK] 用 ffprobe 补了 %d 条时长：%s" % (len(got["filled"]),
                                                        "、".join(got["filled"])))
            # 只回写项目库（共享库是仓库文件，由维护者手工更新）
            p = project_lib_dir(ws) / LIB_NAME
            if p.is_file():
                raw = json.loads(p.read_text(encoding="utf-8-sig"))
                tracks = raw.get("tracks") if isinstance(raw, dict) else raw
                byid = {str(t.get("id")): t for t in (got["library"]["tracks"])}
                for t in (tracks or []):
                    src = byid.get(str(t.get("id")))
                    if src and src.get("duration"):
                        t["duration"] = src["duration"]
                if isinstance(raw, dict):
                    raw["tracks"] = tracks
                p.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8", newline="")
                print("     已回写：%s" % p)
        if got["failed"]:
            print("[WARN] %d 条读不到时长（文件缺失或不是音频）：" % len(got["failed"]))
            for f in got["failed"][:8]:
                print("       - %s：%s" % (f["id"], f["error"]))
        lib = got["library"]
    else:
        lib = load_library(ws)
    if a.json:
        print(json.dumps({"tracks": [{k: v for k, v in t.items() if not k.startswith("_")}
                                     | {"path": str(track_file(t))} for t in lib["tracks"]],
                          "project": lib["project"], "shared": lib["shared"]},
                         ensure_ascii=False, indent=2))
    else:
        print(render_library(lib, ws))
    return 0


def cmd_plan(a) -> int:
    ws = _ws(a.workspace)
    plan = make_plan(ws, a.ep, mood=a.mood, track_id=a.track, gain_db=a.gain_db,
                     segments=a.segments)
    issues = check_plan(ws, plan)
    print(render_plan(plan, issues))
    if not a.apply:
        print("\n（干跑：未写盘。加 --apply 写 %s）" % plan_path(ws, a.ep))
        return 0 if plan.get("segments") else EXIT_NOT_READY
    p = plan_path(ws, a.ep)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8", newline="")
    print("\n[OK] 已写入 %s" % p)
    print("     下一步：bgm.py check --ep %s → bgm.py mix --ep %s --apply" % (a.ep, a.ep))
    return 0 if plan.get("segments") else EXIT_NOT_READY


def cmd_check(a) -> int:
    ws = _ws(a.workspace)
    p = plan_path(ws, a.ep)
    if not p.is_file():
        print("[FAIL] 没有铺排计划：%s（先跑 bgm.py plan --ep %s --apply）" % (p, a.ep))
        return EXIT_NOT_READY
    try:
        plan = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, ValueError) as e:
        print("[FAIL] 计划文件无法解析：%s" % e)
        return EXIT_NOT_READY
    issues = check_plan(ws, plan)
    hard = [i for i in issues if i["level"] == "hard"]
    if a.json:
        print(json.dumps({"ok": not hard, "issues": issues}, ensure_ascii=False, indent=2))
    else:
        print(render_plan(plan, issues))
    return 0 if not hard else EXIT_NOT_READY


def cmd_mix(a) -> int:
    ws = _ws(a.workspace)
    p = plan_path(ws, a.ep)
    if not p.is_file():
        print("[FAIL] 没有铺排计划：%s（先跑 bgm.py plan --ep %s --apply）" % (p, a.ep))
        return EXIT_NOT_READY
    plan = json.loads(p.read_text(encoding="utf-8-sig"))
    res = mix_episode(ws, plan, apply=bool(a.apply))
    if not res.get("ok"):
        print("[FAIL] %s" % res.get("error"))
        return EXIT_NOT_READY
    if res.get("dry_run"):
        print("=" * 78)
        print("干跑：将执行以下命令（加 --apply 真执行）")
        print("=" * 78)
        print(res["cmd"])
        print("\n输出：%s" % res["out"])
        return 0
    print("[OK] 已混音：%s ｜ 时长 %ss" % (res["out"], res.get("duration")))
    print("     下一步：烧字幕时用这条作为底片（subtitle.py 会自动优先取 _mix 版本）")
    return 0


def cmd_credits(a) -> int:
    """输出本集用到的 BGM 署名段（CC BY 必须署名，直接粘进发布文案或片尾）。"""
    ws = _ws(a.workspace)
    p = plan_path(ws, a.ep)
    if not p.is_file():
        print("[FAIL] 没有铺排计划：%s（先跑 bgm.py plan --ep %s --apply）" % (p, a.ep))
        return EXIT_NOT_READY
    plan = json.loads(p.read_text(encoding="utf-8-sig"))
    lib = {str(t.get("id")): t for t in load_library(ws)["tracks"]}
    seen, lines = set(), []
    for seg in (plan.get("segments") or []):
        tid = str(seg.get("track") or "")
        t = lib.get(tid)
        if not t or tid in seen:
            continue
        seen.add(tid)
        attr = str(t.get("attribution") or "").strip()
        if not attr:
            attr = "%s — “%s”（%s，via Wikimedia Commons）" % (
                t.get("artist") or "Unknown", t.get("title") or tid,
                t.get("license_name") or t.get("license") or "见清单")
        lines.append({"id": tid, "license": t.get("license"),
                      "need_credit": t.get("license") != "cc0",
                      "text": attr})
    if a.json:
        print(json.dumps({"ep": a.ep, "credits": lines}, ensure_ascii=False, indent=2))
        return 0
    need = [x for x in lines if x["need_credit"]]
    print("=" * 78)
    print("BGM 署名：%s（%d 首，其中 %d 首要求署名）" % (a.ep, len(lines), len(need)))
    print("=" * 78)
    if not lines:
        print("（这一集没有铺 BGM）")
        return 0
    for x in lines:
        print("%s %s" % ("[需署名]" if x["need_credit"] else "[可免]  ", x["text"]))
    if need:
        print("-" * 78)
        print("可直接粘进发布文案：")
        print("Music: " + "; ".join(x["text"] for x in need))
    else:
        print("-" * 78)
        print("全部为 CC0 / 公有领域，无需署名（仍建议保留来源备查）。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="BGM 库 · 铺排计划 · 混音")
    ap.add_argument("--workspace", default=None)
    sub = ap.add_subparsers(dest="cmd")

    q = sub.add_parser("library", help="看库 / 扫描补时长")
    q.add_argument("--workspace", default=argparse.SUPPRESS)
    q.add_argument("--scan", action="store_true", help="用 ffprobe 补时长并回写项目库")
    q.add_argument("--json", action="store_true")

    q = sub.add_parser("plan", help="生成某集的铺排计划")
    q.add_argument("--workspace", default=argparse.SUPPRESS)
    q.add_argument("--ep", required=True)
    q.add_argument("--mood", default=None, help="情绪：%s" % "/".join(MOOD_DEFAULTS))
    q.add_argument("--track", default=None, help="指定曲目 id（默认按情绪取第一条）")
    q.add_argument("--gain-db", dest="gain_db", type=float, default=None)
    q.add_argument("--segments", type=int, default=1, help="等分成几段（默认 1 = 整集一首）")
    q.add_argument("--apply", action="store_true")

    q = sub.add_parser("check", help="门禁")
    q.add_argument("--workspace", default=argparse.SUPPRESS)
    q.add_argument("--ep", required=True)
    q.add_argument("--json", action="store_true")

    q = sub.add_parser("mix", help="混音（默认干跑）")
    q.add_argument("--workspace", default=argparse.SUPPRESS)
    q.add_argument("--ep", required=True)
    q.add_argument("--apply", action="store_true")

    q = sub.add_parser("credits", help="输出本集 BGM 署名段（CC BY 必须署名）")
    q.add_argument("--workspace", default=argparse.SUPPRESS)
    q.add_argument("--ep", required=True)
    q.add_argument("--json", action="store_true")

    a = ap.parse_args()
    fn = {"library": cmd_library, "plan": cmd_plan, "check": cmd_check,
          "mix": cmd_mix, "credits": cmd_credits}.get(a.cmd)
    if not fn:
        print(render_library(load_library(_ws(a.workspace)), _ws(a.workspace)))
        return 0
    return fn(a)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
