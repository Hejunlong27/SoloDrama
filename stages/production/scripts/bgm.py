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
    python bgm.py library [--scan [--loudness]] [--json]   看库（补时长 / 补响度）
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

# ★ 2026-10-21：铺底目标响度（短剧口径）。
#   对白通常 -16 LUFS 左右，BGM 压到 -33 LUFS 就"听得到但不抢话"；
#   实测用户生成的 6 首响度从 -13.7 到 -27.2 LUFS（差 13.5 dB），
#   所以**不能给统一增益** —— 必须按每首实测 LUFS 反推：
#       gain_db = TARGET_BED_LUFS - loudness_lufs
TARGET_BED_LUFS = -33.0
BED_LUFS_MAX = -25.0        # 高于此值会压住对白
BED_LUFS_MIN = -42.0        # 低于此值基本听不见

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


def canon_ep(s):
    """集号规范化为 `epNN`（两位）；与 subtitle.py 同一口径（`26` / `EP26` 都接受）。

    ★ 2026-10-22：`--ep 26` 曾能通过校验，但拼出来的计划/产物路径是 `subs/26/...`，
      与 `subs/ep26/` 不是同一处 —— 不报错、只是"什么都没找到"。
    """
    m = re.match(r"(?:ep)?\s*0*(\d{1,4})$", str(s or "").strip(), re.I)
    if not m:
        raise SystemExit("--ep 无法识别：%r（要 epNN 或纯数字，例如 ep03 / 3）" % s)
    return "ep%02d" % int(m.group(1))


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


def _lufs(path: pathlib.Path):
    """集成响度（EBU R128）。用它反推铺底增益，比"统一 -22dB"准得多。"""
    try:
        r = subprocess.run([tool("ffmpeg"), "-hide_banner", "-nostats", "-i", str(path),
                            "-af", "ebur128=peak=true", "-f", "null", "-"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=180)
    except (OSError, subprocess.SubprocessError):
        return None
    hits = re.findall(r"I:\s*(-?\d+\.\d+)\s*LUFS", (r.stderr or ""))
    return float(hits[-1]) if hits else None


def scan(ws: pathlib.Path, loudness: bool = False) -> dict:
    """用 ffprobe 补齐库条目的时长；`loudness=True` 时再补 EBU R128 响度。

    BPM 不猜（必须人工听），只保留人工填的值。
    """
    lib = load_library(ws)
    filled, failed, loud = [], [], []
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
        if loudness:
            lu = _lufs(f)
            if lu is not None:
                t["loudness_lufs"] = lu
                loud.append({"id": t.get("id"), "lufs": lu})
    return {"library": lib, "filled": filled, "failed": failed, "loudness": loud}


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


def _hi_res_names(ep: str) -> list:
    """放大母版的候选名：新名（带分辨率）优先，旧名 `_master_2k` 兜底。

    ★ 2026-10-22：放大产物名从 `<ep>_master_2k.mp4` 改为 `<ep>_master_<W>x<H>.mp4`
      （竖屏 1080P 却叫 2k 是歧义源）。老项目不迁移，所以读取要按"新→旧"两级找。
    """
    d = ["%s_master_1080x1920.mp4" % ep, "%s_master_1440x2560.mp4" % ep,
         "%s_master_2160x3840.mp4" % ep]
    return d + ["%s_master_2k.mp4" % ep]


def ep_duration(ws: pathlib.Path, ep: str) -> float:
    """整集成片时长：优先 ffprobe 母版；否则按 `h3_prompts.json` 的 duration 求和。"""
    for name in _hi_res_names(ep) + ["%s_master.mp4" % ep, "%s_subbed.mp4" % ep]:
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
              gain_db: float = None, segments: int = 1, force_gain: bool = False) -> dict:
    """生成铺排计划：默认整集一首、淡入淡出、开 ducking。

    `segments` > 1 时按等分切段（第二段起用同一首曲的不同起点），便于后续人工改成多首。
    `gain_db` 是**显式指定增益**；`force_gain=True` 时同时写 `gain_locked`，表示
    「我知道它超出推荐区间，就按我说的来」——否则 `plan` 不会把它落盘（见 cmd_plan）。
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
    # 增益优先级：命令行 > 曲目建议值 > **按实测响度反推** > 情绪默认
    try:
        track_gain = track.get("gain_db")
        track_gain = float(track_gain) if track_gain is not None else None
    except (TypeError, ValueError):
        track_gain = None
    try:
        track_lufs = track.get("loudness_lufs")
        track_lufs = float(track_lufs) if track_lufs is not None else None
    except (TypeError, ValueError):
        track_lufs = None
    if gain_db is not None:
        gain = float(gain_db)
    elif track_gain is not None:
        gain = track_gain
    elif track_lufs is not None:
        # 不同来源的曲子母带响度差得远（实测 -13.7 ~ -27.2 LUFS），按目标反推才不跑偏
        gain = round(TARGET_BED_LUFS - track_lufs, 1)
    else:
        gain = float(dflt["gain_db"])
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
    # ★ 2026-10-22：显式指定增益时一并**锁定**，否则 mix 阶段的 sync_plan_gain
    #   会按库里实测响度把它改回去 —— 于是「plan 里写 -3 dB、实际混的是 -14.6 dB」，
    #   而 `plan` 打印的门禁还在按 -3 dB 报错。锁定后两边口径一致。
    if force_gain and gain_db is not None:
        for _s in segs:
            _s["gain_locked"] = True
    return {"ep": ep, "total_s": total, "voice": ep_voice(ws), "mood": mood,
            # ★ threshold 从 0.05 提到 0.15：短剧人声几乎连续，0.05(-26dBFS) 会在整集
            #   持续压缩，BGM 被压到听不见（实测片尾无对白处才抬 13dB，有对白处几乎为零）。
            #   0.15 ≈ -16dBFS 只在人声峰值处压，句中间隙能露出来。
            "ducking": {"enabled": True, "threshold": 0.15, "ratio": 4,
                        "attack": 20, "release": 300},
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
            g = float(gain) if gain is not None else None
        except (TypeError, ValueError):
            g = None
        # ★ 2026-10-21：判的是**最终铺底响度**，不是相对增益。
        #   起因：AI 生成的曲子母带响度差 13 dB（-13.7 ~ -27.2 LUFS），
        #   同一首"提 6dB"可能才 -21 LUFS（完全不抢戏），另一首"降 22dB"却是 -36。
        #   只看 gain 会同时误杀（太轻的曲子被拦）与漏放（本来就响的曲子）。
        try:
            lu = t.get("loudness_lufs")
            lu = float(lu) if lu is not None else None
        except (TypeError, ValueError):
            lu = None
        if g is None:
            out.append({"level": "warn", "code": "B008", "msg": "第 %d 段没写 gain_db" % i})
        elif lu is not None:
            final = lu + g
            # ★ 2026-10-22：`gain_locked` = 用户显式指定并确认过（plan --force-gain）。
            #   此时不拦，只提示 —— 否则会出现「plan 报 FAIL、mix 却照混」的口径矛盾：
            #   实测 ep29/ep30 日志里 `[FAIL] B009 -20.4 LUFS 过高` 紧跟着 `[OK] 已混音`。
            _lvl = "warn" if s.get("gain_locked") else "hard"
            _pre = "（增益已锁定，按指定值执行）" if s.get("gain_locked") else ""
            if final > BED_LUFS_MAX:
                out.append({"level": _lvl, "code": "B009",
                            "msg": _pre + "第 %d 段最终铺底 %.1f LUFS 过高（> %.0f），会压住对白"
                                   "（原曲 %.1f LUFS + 增益 %.1f dB）"
                                   % (i, final, BED_LUFS_MAX, lu, g)})
            elif final < BED_LUFS_MIN:
                out.append({"level": _lvl, "code": "B014",
                            "msg": _pre + "第 %d 段最终铺底 %.1f LUFS 过低（< %.0f），基本听不见"
                                   "（原曲 %.1f LUFS + 增益 %.1f dB）"
                                   % (i, final, BED_LUFS_MIN, lu, g)})
        elif g > -6:
            out.append({"level": "hard", "code": "B009",
                        "msg": "第 %d 段 gain_db=%.1f 偏高（> -6）且缺 loudness_lufs，无法判断"
                               "是否会压住对白 —— 先跑 `library --scan --loudness` 补响度" % (i, g)})
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
    """混哪一条：优先放大母版（字幕烧在它上面），其次带字幕成片，再次拼接母版。"""
    d = subs_dir(ws, ep)
    for name in _hi_res_names(ep) + ["%s_subbed.mp4" % ep, "%s_master.mp4" % ep]:
        p = d / name
        if p.is_file():
            return p
    return d / _hi_res_names(ep)[0]


def sync_plan_gain(ws: pathlib.Path, plan: dict) -> list:
    """把计划里的增益同步成库里当前的实测建议值（差 >3 dB 才动，段可 `gain_locked` 锁住）。

    为什么需要：`plan` 一旦落盘就把 `gain_db` 写死了，但库里的建议值会变 ——
    典型场景是刚入库的曲子补了 `loudness_lufs`，增益从拍脑袋的 -22 校正成 -10.1。
    旧计划带着 -22 去混，最终铺底就成了 -44.9 LUFS（等于没铺）。
    """
    lib = {str(t.get("id")): t for t in load_library(ws)["tracks"]}
    notes = []
    for i, s in enumerate(plan.get("segments") or [], 1):
        if s.get("gain_locked"):
            continue
        t = lib.get(str(s.get("track")))
        if not t or t.get("gain_db") is None:
            continue
        try:
            want, cur = float(t["gain_db"]), float(s.get("gain_db"))
        except (TypeError, ValueError):
            continue
        if abs(want - cur) > 3.0:
            s["gain_db"] = want
            notes.append("第 %d 段增益 %.1f → %.1f dB（按库中实测响度校正）" % (i, cur, want))
    return notes


def mix_episode(ws: pathlib.Path, plan: dict, base: pathlib.Path = None,
                out: pathlib.Path = None, apply: bool = False) -> dict:
    """按计划混音。返回 {ok, cmd, out, error, issues, notes}；apply=False 只构建不执行。"""
    ep = str(plan.get("ep") or "")
    notes = sync_plan_gain(ws, plan)          # 先校正过期增益，再过门禁
    base = base or target_video(ws, ep)
    out = out or (subs_dir(ws, ep) / ("%s_mix.mp4" % ep))
    issues = check_plan(ws, plan)
    hard = [i for i in issues if i["level"] == "hard"]
    if hard:
        return {"ok": False, "error": "; ".join(i["msg"] for i in hard[:4]),
                "issues": issues, "notes": notes}
    if not pathlib.Path(base).is_file():
        return {"ok": False, "error": "找不到要混音的母版：%s（先跑 --stage master / upscale）"
                                     % base, "issues": issues, "notes": notes}
    cmd = build_mix_cmd(ws, plan, pathlib.Path(base), pathlib.Path(out))
    if not apply:
        return {"ok": True, "dry_run": True, "cmd": " ".join(cmd), "out": str(out),
                "issues": issues, "notes": notes}
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        return {"ok": False, "cmd": " ".join(cmd), "out": str(out),
                "error": (r.stderr or "").strip()[:600], "issues": issues, "notes": notes}
    got = _probe(pathlib.Path(out))
    return {"ok": pathlib.Path(out).is_file(), "out": str(out), "duration": got.get("duration"),
            "cmd": " ".join(cmd), "issues": issues, "notes": notes}


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
def writeback(lib: dict, fields=("duration", "loudness_lufs")) -> list:
    """把 scan 补到的字段写回**各自的**清单文件（项目库 / 共享库分开写）。

    为什么要按 `_root` 分组：合并后的库混着两处来源，早先只回写项目库，
    于是共享库那批曲目的 `loudness_lufs` 永远补不上 —— 增益就只能靠拍脑袋的 -22 dB。
    """
    by_root = {}
    for t in lib.get("tracks") or []:
        root = t.get("_root")
        if root:
            by_root.setdefault(root, []).append(t)
    changed = []
    for root, tracks in by_root.items():
        p = pathlib.Path(root) / LIB_NAME
        if not p.is_file():
            continue
        try:
            raw = json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        items = raw.get("tracks") if isinstance(raw, dict) else raw
        items = [x for x in (items or []) if isinstance(x, dict)]
        touched = False
        by_id = {str(x.get("id")): x for x in items}
        for t in tracks:
            dst = by_id.get(str(t.get("id")))
            if not dst:
                continue
            for k in fields:
                if t.get(k) is not None and dst.get(k) != t.get(k):
                    dst[k] = t[k]
                    touched = True
        if touched:
            if isinstance(raw, dict):
                raw["tracks"] = [by_id[str(x.get("id"))] for x in items]
            else:
                raw = [by_id[str(x.get("id"))] for x in items]
            p.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8", newline="")
            changed.append(str(p))
    return changed


def cmd_library(a) -> int:
    ws = _ws(a.workspace)
    if a.scan:
        got = scan(ws, loudness=bool(getattr(a, "loudness", False)))
        if got["filled"]:
            print("[OK] 用 ffprobe 补了 %d 条时长：%s" % (len(got["filled"]),
                                                        "、".join(got["filled"])))
        if got.get("loudness"):
            print("[OK] 实测响度 %d 条（按 %.0f LUFS 铺底反推增益）"
                  % (len(got["loudness"]), TARGET_BED_LUFS))
        # 按条目来源分别回写项目库 / 共享库（早先只写项目库，共享库的响度永远补不上）
        for path in writeback(got["library"], ("duration", "loudness_lufs")):
            print("     已回写：%s" % path)
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
                     segments=a.segments, force_gain=bool(getattr(a, "force_gain", False)))
    issues = check_plan(ws, plan)
    print(render_plan(plan, issues))
    hard = [i for i in issues if i["level"] == "hard"]
    if hard:
        # ★ 2026-10-22：**不写一个自己门禁都过不了的计划**。
        #   旧行为是照样落盘 → `bgm check` 永远返回 2，而 `mix` 又会在
        #   sync_plan_gain 里把增益改掉后偷偷成功，三方口径各不相同。
        #   这里给出建议值 + 两种正确姿势（调增益 / 显式锁定）。
        _lu = [t.get("loudness_lufs") for t in load_library(ws)["tracks"]
               if str(t.get("id")) in {str(s.get("track")) for s in plan.get("segments") or []}]
        _lu = [float(x) for x in _lu if x is not None]
        print("\n[FAIL] 计划未通过门禁，**没有写盘**：")
        for i in hard[:4]:
            print("  - %s" % i["msg"])
        if _lu:
            print("  建议：--gain-db %.1f（按实测响度把铺底压到 %.0f LUFS）"
                  % (TARGET_BED_LUFS - max(_lu), TARGET_BED_LUFS))
        print("  若确实要按指定增益执行：加 --force-gain（会写 gain_locked，门禁降为提示）")
        return EXIT_NOT_READY
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
    # ★ 2026-10-22（对账）：`check` 必须和 `mix` 看**同一份增益**。
    #   旧实现直接读盘上的 gain_db，而 mix 会先跑 sync_plan_gain 按库里实测响度校正
    #   ⇒ 同一份计划出现「check 报 FAIL、mix 却成功」（实测 ep29：check 说 -3.0dB 会压对白，
    #   mix 实际用 -14.6dB）。这里先做同样的校正（只改内存对象，不写盘），再判门禁；
    #   校正过时明确提示一句，避免"数字怎么变了"的困惑。
    notes = sync_plan_gain(ws, plan)
    issues = check_plan(ws, plan)
    hard = [i for i in issues if i["level"] == "hard"]
    for n in notes:
        print("[i] %s（本次判定按校正后的值；写盘请重跑 plan --apply）" % n)
    if a.json:
        print(json.dumps({"ok": not hard, "issues": issues, "gain_notes": notes},
                         ensure_ascii=False, indent=2))
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
        lic = str(t.get("license") or "")
        attr = str(t.get("attribution") or "").strip()
        if not attr:
            # 自有 / CC0 不需要对外署名：只报「哪首曲子」，不要编造出处
            attr = "%s：%s" % (t.get("license_name") or lic or "版权见清单",
                              t.get("title") or tid)
        lines.append({"id": tid, "license": lic, "origin": t.get("origin"),
                      # ★ 2026-10-21 修：`owned`（自有版权）不需要对外署名，
                      #   原来只排除 cc0，会把自有版权曲目也标成「需署名」。
                      "need_credit": lic not in ("cc0", "owned"),
                      "text": attr})
    if a.json:
        print(json.dumps({"ep": a.ep, "credits": lines}, ensure_ascii=False, indent=2))
        return 0
    need = [x for x in lines if x["need_credit"]]
    own = [x for x in lines if x["license"] == "owned"]
    print("=" * 78)
    print("BGM 署名：%s（%d 首，其中 %d 首要求署名、%d 首自有版权）"
          % (a.ep, len(lines), len(need), len(own)))
    print("=" * 78)
    if not lines:
        print("（这一集没有铺 BGM）")
        return 0
    for x in lines:
        tag = "[需署名]" if x["need_credit"] else ("[自有]  " if x["license"] == "owned"
                                                  else "[可免]  ")
        print("%s %s" % (tag, x["text"]))
    if need:
        print("-" * 78)
        print("可直接粘进发布文案：")
        print("Music: " + "; ".join(x["text"] for x in need))
    else:
        print("-" * 78)
        print("全部为自有版权 / CC0，**无需对外署名**（仍建议保留来源备查）。")
        if own:
            print("提示：若发行平台要求披露 AI 生成，可用清单里的 origin=ai_generated 字段说明。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="BGM 库 · 铺排计划 · 混音")
    ap.add_argument("--workspace", default=None)
    sub = ap.add_subparsers(dest="cmd")

    q = sub.add_parser("library", help="看库 / 扫描补时长")
    q.add_argument("--workspace", default=argparse.SUPPRESS)
    q.add_argument("--scan", action="store_true", help="用 ffprobe 补时长并回写项目库")
    q.add_argument("--loudness", action="store_true",
                   help="连同 EBU R128 响度一起补（用于按实测响度反推铺底增益）")
    q.add_argument("--json", action="store_true")

    q = sub.add_parser("plan", help="生成某集的铺排计划")
    q.add_argument("--workspace", default=argparse.SUPPRESS)
    q.add_argument("--ep", required=True)
    q.add_argument("--mood", default=None, help="情绪：%s" % "/".join(MOOD_DEFAULTS))
    q.add_argument("--track", default=None, help="指定曲目 id（默认按情绪取第一条）")
    q.add_argument("--gain-db", dest="gain_db", type=float, default=None)
    q.add_argument("--force-gain", dest="force_gain", action="store_true",
                   help="按 --gain-db 强制执行（写 gain_locked，门禁降为提示）")
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
    if getattr(a, "ep", None):
        a.ep = canon_ep(a.ep)            # 26 / EP26 / ep026 → ep26
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
