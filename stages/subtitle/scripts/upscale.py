#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
upscale.py —— 高清放大（Topaz Video 本地 AI 超分）· 短剧流水线「合并之后」的一道工序

为什么需要它
------------
H3 出片是 1440x832。这个尺寸在手机竖屏/大屏播放时不够看，而**烧字幕会重编码**：
如果先烧字幕再放大，字幕会跟着被"AI 重绘"（描边发糊、字被当成纹理处理）。
⇒ 正确顺序是【合并母版 → 放大到交付分辨率 → 再问要不要字幕 → 在放大版上烧字幕】。
本脚本负责中间那一步，产出 <ep>_master_2k.mp4，字幕管线接着拿它当母版。

它跟 Topaz 官方 GUI 的关系
--------------------------
Topaz Video（D:\\Program Files\\Topaz Labs LLC\\Topaz Video）自带一个**带 tvai_up 滤镜的 ffmpeg**，
GUI 导出时内部就是在调它。本脚本复刻 GUI 的命令行，因此**结果与 GUI 一致**，但可批处理、可断言。

★ 本机实测踩到的坑（2026-09-21）：直接跑那个 ffmpeg 会报 `Model not found: prob-4`。
  原因不是没买/没装，而是**模型权重被放在 D 盘**（用户把 Topaz 的模型目录挪到了 D:），
  而独立运行的 ffmpeg 默认只看 C:\\ProgramData\\...\\models（那里只有模型定义 json，没有权重 .tz3）。
  解法 = 给子进程设两个环境变量（库内部读的就是它们，从 videoai.dll 里挖出来的）：
      TVAI_MODEL_DIR      -> 模型定义目录（*.json，通常在 C:\\ProgramData\\Topaz Labs LLC\\Topaz Video\\models）
      TVAI_MODEL_DATA_DIR -> 模型权重目录（*.tz3，本机在 D:\\ProgramData\\Topaz Labs LLC\\Topaz Video\\models）
  本脚本会自动探测这两个目录，也可在 config.upscale.json 里写死。

★ 放大链路 checklist（2026-10-20 反馈 P1-14，三条坑合并；文档缺失曾导致三次返工）
  ① **模型双目录**：`Model not found: prob-4`
     → 必须同时设 `TVAI_MODEL_DIR`（定义 *.json）与 `TVAI_MODEL_DATA_DIR`（权重 *.tz3）。
     本脚本已自动探测；手工调 ffmpeg 时也要设这两个环境变量。
  ② **滤镜里的路径冒号**：`Unable to parse "original_size"`
     → `subtitles=D:/xxx.ass` 中的冒号被当成参数分隔符。
     解法：`cwd` 切到 .ass 所在目录，`subtitles=` 只传文件名。
  ③ **Topaz 的 ffmpeg 不含 libass**：`subtitles=ep01.ass` 直接失败。
     → 必须拆两遍：本脚本只放大（tvai_up），再用**系统 ffmpeg** 烧字幕。
     本脚本启动时会探测 `-filters` 里的 subtitles 滤镜，缺失即打印两遍法提示。

用法
----
    python scripts/upscale.py --ep ep03                 # 放大 ep03 母版到目标分辨率
    python scripts/upscale.py --ep ep03 --dry-run       # 只打印将要执行的命令与预计耗时
    python scripts/upscale.py --ep ep03 --verify-only   # 只对已有产物做断言
    python scripts/upscale.py --ep ep03 --force         # 忽略缓存重跑
    python scripts/upscale.py --ep ep03 --target 3840x2160
    python scripts/upscale.py --ep ep03 --fallback-lanczos   # Topaz 不可用时退到插值（画质不提升，会明确告警）
    python scripts/upscale.py --ep ep03 --json          # 机器可读输出（给上层编排用）

产物（与字幕管线同一个目录）
    <ep>_master_2k.mp4      放大后的母版（后续字幕就烧在它上面）
    <ep>_upscale.json       本次放大的参数 + 全部自检数据（可复核）
    <ep>_upscale.log        ffmpeg 原始日志

配置
    <工作区>/video-pipeline/config.upscale.json —— 改目标分辨率/模型/编码参数，不改代码。
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import time

_HINT = (
    "找不到短剧工作区。请二选一：\n"
    "  ① 命令行加 --workspace \"<项目根目录>\"\n"
    "  ② 设环境变量：$env:SOLODRAMA_WORKSPACE = \"<项目根目录>\"  （PowerShell）\n"
    "工作区的标志物是 <项目根>/video-pipeline/data/。")


def resolve_ws():
    """工作区解析：`_ws`（项目里有）> SOLODRAMA_WORKSPACE > 脚本位置推断 > None。

    ★ 为什么不能简单 `from _ws import WS`：本脚本住在 **Skill 包**里时没有 `_ws.py`
    （它属于另一个 Skill），会直接 ModuleNotFoundError —— 而且 `_ws` 在解析不到工作区时
    抛的是 **SystemExit**（不是 Exception），不接住会把宿主进程一起带走。
    实测踩过：从 Skill 目录调用报 `No module named '_ws'`。
    ⇒ 这里做成「能用就用、不能用就按同样的优先级自己推」。
    """
    d = os.path.dirname(os.path.abspath(__file__))
    if d not in sys.path:
        sys.path.insert(0, d)
    try:
        from _ws import WS as _WS          # noqa
        return str(_WS), ""
    except BaseException:
        pass
    env = (os.environ.get("SOLODRAMA_WORKSPACE") or os.environ.get("DRAMA_WORKSPACE"))
    if env and os.path.isdir(env):
        return os.path.abspath(env), ""
    cand = os.path.dirname(d)
    if (os.path.isdir(os.path.join(cand, "video-pipeline", "data"))
            or os.path.isfile(os.path.join(cand, "layout.json"))):
        return cand, ""
    return None, _HINT


WS, WS_HINT = resolve_ws()


# ------------------------------------------------- 分阶段目录（stages/_layout.py 的轻量复刻）
# 与 subtitle.py 内那份**保持逐字一致**；两处都自带实现是有意为之 ——
# 本脚本可能被拷进 Skill 包运行，那时仓库的 stages/_layout.py 不在 sys.path 上。
def _layout_paths(ws):
    """返回 (engine_root, data_dir, out_dir)，均为绝对路径。"""
    ws = os.path.abspath(ws)
    eng = os.path.join(ws, "video-pipeline")
    data_rel = out_rel = None
    lj = os.path.join(ws, "layout.json")
    if os.path.isfile(lj):
        try:
            lay = json.load(open(lj, encoding="utf-8-sig"))
            if isinstance(lay, dict):
                eng = os.path.join(ws, lay.get("engine_root") or "video-pipeline")
                data_rel, out_rel = lay.get("data_rel"), lay.get("out_rel")
        except Exception:                                                  # noqa: BLE001
            pass
    cl = os.path.join(eng, "config.local.json")
    if os.path.isfile(cl):
        try:
            cfg = json.load(open(cl, encoding="utf-8-sig"))
            if isinstance(cfg, dict):
                data_rel = cfg.get("data_dir") or data_rel
                out_rel = cfg.get("out_dir") or out_rel
        except Exception:                                                  # noqa: BLE001
            pass

    def _r(rel, fallback):
        rel = rel or fallback
        return os.path.abspath(rel) if os.path.isabs(rel) else os.path.abspath(os.path.join(eng, rel))

    return eng, _r(data_rel, "data"), _r(out_rel, "output")


def engine_root_of(ws):
    return _layout_paths(ws)[0]


def out_dir_of(ws):
    return _layout_paths(ws)[2]

EXE_SUFFIX = ".exe"
FFMPEG_NAME = "ffmpeg" + EXE_SUFFIX
FFPROBE_NAME = "ffprobe" + EXE_SUFFIX

# ---------------------------------------------------------------------------
# ★ 2026-10-22：放大产物的名字必须**如实**反映分辨率
# ---------------------------------------------------------------------------
# 事故：竖屏项目按 `target = {1080, 1920}` 放大，产物却叫 `<ep>_master_2k.mp4` ——
#   实际是 **1080P**，名字里却写着 2K（2K 通常指 2560×1440）。同一个人隔一周看目录，
#   会以为"已经出过 2K 版了"，用户也是照这个名字提出"不要 2K，要 1080P"。
#   ⇒ 新名 `<ep>_master_<W>x<H>.mp4`（如 ep03_master_1080x1920.mp4），名字自带分辨率。
#   旧名 `_master_2k` 继续**可读**（老项目不必迁移），但不再产出。
MASTER_UP_SUFFIX = "_master_%dx%d.mp4"
LEGACY_UP_SUFFIXES = ("_master_2k.mp4",)      # 只读回退，不写


def upscaled_path(subs_dir, ep, size=None):
    """该集放大母版的路径：新名优先，旧名（_master_2k）回退；都没有则返回新名。

    `size` 给了就按该分辨率组名（如 (1080,1920)）；不给则先扫目录里任何
    `<ep>_master_<W>x<H>.mp4`，再退 `_master_2k.mp4`。
    """
    import glob as _glob
    if size:
        p = os.path.join(subs_dir, ep + MASTER_UP_SUFFIX % (int(size[0]), int(size[1])))
        if os.path.isfile(p):
            return p
    hits = sorted(_glob.glob(os.path.join(subs_dir, ep + "_master_*x*.mp4")))
    hits = [h for h in hits if os.path.basename(h) != "%s_master.mp4" % ep]
    if hits:
        return max(hits, key=os.path.getmtime)
    for suf in LEGACY_UP_SUFFIXES:
        p = os.path.join(subs_dir, ep + suf)
        if os.path.isfile(p):
            return p
    if size:
        return os.path.join(subs_dir, ep + MASTER_UP_SUFFIX % (int(size[0]), int(size[1])))
    return os.path.join(subs_dir, ep + (LEGACY_UP_SUFFIXES[0] if not size else
                                        MASTER_UP_SUFFIX % (1080, 1920)))


# 模型定义目录（*.json）的候选位置；权重目录（*.tz3）另行全盘探测
MODEL_DIR_CANDIDATES = [
    r"C:\ProgramData\Topaz Labs LLC\Topaz Video\models",
    r"C:\ProgramData\Topaz Labs LLC\Topaz Video AI\models",
    r"D:\ProgramData\Topaz Labs LLC\Topaz Video\models",
    r"D:\ProgramData\Topaz Labs LLC\Topaz Video AI\models",
]

# 权重目录的扫描根：<盘>:\ProgramData\Topaz Labs LLC\Topaz Video\models（用户把模型挪走时会在别的盘）
DATA_DIR_SCAN_ROOTS = [
    r"C:\ProgramData\Topaz Labs LLC",
    r"D:\ProgramData\Topaz Labs LLC",
    r"E:\ProgramData\Topaz Labs LLC",
]

TOPAZ_INSTALL_CANDIDATES = [
    r"D:\Program Files\Topaz Labs LLC\Topaz Video",
    r"C:\Program Files\Topaz Labs LLC\Topaz Video",
    r"D:\Program Files\Topaz Labs LLC\Topaz Video AI",
    r"C:\Program Files\Topaz Labs LLC\Topaz Video AI",
]


# ---------------------------------------------------------------- 基础设施

def harden_stdio():
    """Windows 控制台是 GBK，直接打印非 GBK 字符会崩（本项目已踩过多次）。"""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def say(msg=""):
    print(msg, flush=True)


def load_json(p, default=None):
    if not os.path.exists(p):
        return default
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def dump_json(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


DEFAULT_CONFIG = {
    "_note": "高清放大配置。target.mode=width 表示『按宽度等比放大』（本机 1440x832 -> 2560x1480，不变形）。",
    "version": 1,
    "enabled": True,
    "backend": "topaz",
    "_backend_note": "放大后端三选一：topaz（本地 GPU，免费，慢）/ rh（RunningHub RH_Astra Iris，约 35 币一集，2–3 分钟）/ off（跳过，母版直接进字幕）。命令行 --backend 可临时覆盖。",
    "tool": {
        "_note": "留空则自动探测 Topaz Video 安装目录与模型目录；探测不到会在报错里给出可照抄的改法",
        "install_dir": "",
        "ffmpeg": "",
        "ffprobe": "",
        "model_dir": "",
        "model_data_dir": "",
        "extra_env": {},
    },
    "target": {
        "mode": "width",
        "width": 2560,
        "scale": 2.0,
        "keep_aspect": True,
        "even": True,
        "fallback_to_exact_none": True,
    },
    "model": {
        "name": "prob-4",
        "_note": "prob-4=Proteus 4（通用实拍/AI 生成人物最稳，本机 GUI 实测用的就是它）。其它可选：iris-3=人脸修复、rhea-1=4 倍、nyx-3=降噪",
        "scale": 0,
        "estimate": 8,
        "blend": 0.2,
        "preblur": 0.0,
        "noise": 0.0,
        "details": 0.0,
        "halo": 0.0,
        "blur": 0.0,
        "compression": 0.0,
        "device": 0,
        "vram": 1,
        "instances": 1,
    },
    "encode": {
        "_note": "h264_nvenc + constqp 18 与 Topaz GUI 完整导出同参；要更小体积可换 hevc_nvenc",
        "codec": "h264_nvenc",
        "preset": "p5",
        "rc": "constqp",
        "qp": 18,
        "profile": "high",
        "pix_fmt": "yuv420p",
        "audio": "copy",
    },
    "verify": {
        "samples": 3,
        "min_frame_gain_hf": 1.02,
        "min_frame_gain_lap": 1.05,
        "flush_warn": True,
    },
    # 只用于 --dry-run 的耗时预估（实测值，RTX 4060 Laptop 跑 prob-4 放大一集）
    "perf": {"expected_fps": 8.2},
}


def deep_merge(base, override):
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(ws, path=None):
    p = path or os.path.join(engine_root_of(ws), "config.upscale.json")
    cfg = deep_merge(DEFAULT_CONFIG, load_json(p, {}) or {})
    cfg["_config_path"] = p
    cfg["_config_exists"] = os.path.exists(p)
    return cfg


# ---------------------------------------------------------------- 工具与模型探测

def _first_existing(paths):
    for p in paths:
        if p and os.path.exists(p):
            return p
    return None


def detect_toolchain(cfg):
    """定位 Topaz 的 ffmpeg/ffprobe + 模型定义目录 + 模型权重目录。

    返回 (info, problems)：problems 非空时调用方负责给出可照抄的修法。
    """
    t = cfg["tool"]
    problems = []
    install = t.get("install_dir") or os.environ.get("TOPAZ_VIDEO_DIR") or ""
    if install and not os.path.isdir(install):
        problems.append("配置的 install_dir 不存在：%s" % install)
        install = ""
    if not install:
        install = _first_existing(TOPAZ_INSTALL_CANDIDATES) or ""

    ff = t.get("ffmpeg") or (os.path.join(install, FFMPEG_NAME) if install else "")
    fp = t.get("ffprobe") or (os.path.join(install, FFPROBE_NAME) if install else "")
    if not ff or not os.path.exists(ff):
        problems.append("找不到 Topaz 自带的 ffmpeg（它才带 tvai_up 滤镜）")
    if not fp or not os.path.exists(fp):
        fp = "ffprobe"          # 系统 ffprobe 也够用

    # 模型定义目录（*.json）
    mdir = t.get("model_dir") or os.environ.get("TVAI_MODEL_DIR") or ""
    if not mdir or not os.path.isdir(mdir):
        mdir = _first_existing(MODEL_DIR_CANDIDATES) or mdir
    if not mdir or not os.path.isdir(mdir):
        problems.append("找不到 Topaz 模型定义目录（内含 prob-4.json 等）")

    # 模型权重目录（*.tz3）
    ddir = t.get("model_data_dir") or os.environ.get("TVAI_MODEL_DATA_DIR") or ""
    if not ddir or not _has_weights(ddir):
        found = _scan_for_weight_dir()
        if found:
            ddir = found
    if not ddir or not _has_weights(ddir):
        problems.append("找不到 Topaz 模型权重目录（内含 *.tz3）。"
                        "通常是模型被挪到了别的盘 —— 见 stages/production/references/hd-upscale-case-2560x1480.md")

    return {
        "install_dir": install,
        "ffmpeg": ff, "ffprobe": fp,
        "model_dir": mdir, "model_data_dir": ddir,
        "extra_env": t.get("extra_env") or {},
    }, problems


def _has_weights(d):
    if not d or not os.path.isdir(d):
        return False
    try:
        for name in os.listdir(d):
            if name.endswith(".tz3"):
                return True
    except OSError:
        pass
    return False


def _scan_for_weight_dir():
    """在候选根下找『装着 *.tz3 的 models 目录』（深度 ≤2，够用且快）。"""
    for root in DATA_DIR_SCAN_ROOTS:
        if not os.path.isdir(root):
            continue
        for sub in ("Topaz Video", "Topaz Video AI"):
            for cand in (os.path.join(root, sub, "models"), os.path.join(root, sub)):
                if _has_weights(cand):
                    return cand
    return ""


def model_weight_files(tools, model_name):
    """统计该模型在权重目录里有多少个 *.tz3（0 = 权重没下载）。"""
    d = tools.get("model_data_dir") or ""
    if not _has_weights(d):
        return 0, []
    # 模型名 prob-4 -> 文件名前缀 prob-v4-
    m = re.match(r"^([a-z]+)-?(\d+)?$", model_name or "")
    prefixes = []
    if m:
        base, ver = m.group(1), m.group(2)
        if ver:
            prefixes.append("%s-v%s-" % (base, ver))
            prefixes.append("%s-%s-" % (base, ver))
        prefixes.append(base)
    hits = []
    try:
        for name in os.listdir(d):
            if name.endswith(".tz3") and any(name.startswith(p) for p in prefixes):
                hits.append(name)
    except OSError:
        pass
    return len(hits), sorted(hits)[:5]


def probe_filters(tools):
    """一次性探测这个 ffmpeg 支持的滤镜（2026-10-20 反馈 P1-14）。

    - `tvai_up`   ：放大必需（只有 Topaz 自带 ffmpeg 有）
    - `subtitles`  ：烧字幕必需（依赖 libass）—— **Topaz 自带 ffmpeg 不含 libass**，
                     所以「放大 + 烧字幕」必须拆成两遍：Topaz 只放大，系统 ffmpeg 烧字幕。
                     这条以前只写在文档里，脚本启动时不提示，实测踩了三次才被发现。
    """
    out = {"tvai_up": False, "subtitles": False}
    try:
        p = subprocess.run([tools["ffmpeg"], "-hide_banner", "-filters"],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
        text = (p.stdout or b"").decode("utf-8", "replace")
        out["tvai_up"] = "tvai_up" in text
        out["subtitles"] = bool(re.search(r"^\s*\S+\s+subtitles\s", text, re.M)) or " ass " in text
    except Exception:                                                 # noqa: BLE001
        pass
    return out


def probe_filter(tools):
    """兼容旧调用：只问「有没有 tvai_up」。"""
    return bool(probe_filters(tools).get("tvai_up"))


def burn_subtitle_note(tools):
    """返回「烧字幕该怎么做」的一句提示（无 libass 时明确给出两遍法）。"""
    f = probe_filters(tools)
    if not tools.get("ffmpeg"):
        return ""
    if f.get("subtitles"):
        return ""
    return ("★ 本机 Topaz 的 ffmpeg **不含 libass**（无 subtitles 滤镜）——"
            "不要在同一遍里放大+烧字幕。正确姿势是两遍法：\n"
            "    ① 本脚本只放大（Topaz ffmpeg，tvai_up）；\n"
            "    ② 另用系统 ffmpeg 的 subtitles= 烧字幕，且 cwd 切到 .ass 所在目录、只传文件名\n"
            "       （绝对路径里的冒号会被当成参数分隔符，报 Unable to parse original_size）。")


# ---------------------------------------------------------------- 尺寸与命令

def ffprobe_json(tools, path, entries):
    cmd = [tools["ffprobe"], "-v", "error", "-show_entries", entries,
           "-of", "json", path]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = p.stdout.decode("utf-8", errors="replace")
    try:
        return json.loads(out)
    except Exception:
        raise RuntimeError("ffprobe 解析失败：%s\n%s" % (path, out[-500:]))


def video_info(tools, path):
    j = ffprobe_json(tools, path, "stream=index,codec_type,codec_name,width,height,"
                                  "r_frame_rate,nb_frames,duration")
    v = a = None
    for s in j.get("streams", []):
        if s.get("codec_type") == "video" and v is None:
            v = s
        elif s.get("codec_type") == "audio" and a is None:
            a = s
    if not v:
        raise RuntimeError("没有视频流：%s" % path)
    fmt = ffprobe_json(tools, path, "format=duration,size,bit_rate").get("format", {})

    def num(x, d=0.0):
        try:
            return float(x)
        except (TypeError, ValueError):
            return d
    return {
        "path": path, "width": int(v["width"]), "height": int(v["height"]),
        "fps": num(str(v.get("r_frame_rate", "0/1")).split("/")[0]) /
               max(num(str(v.get("r_frame_rate", "0/1")).split("/")[-1], 1), 1),
        "nb_frames": int(num(v.get("nb_frames"))),
        "v_duration": num(v.get("duration"), num(fmt.get("duration"))),
        "duration": num(fmt.get("duration")),
        "codec": v.get("codec_name"),
        "audio_codec": (a or {}).get("codec_name"),
        "a_duration": num((a or {}).get("duration"), num(fmt.get("duration"))),
        "a_nb_frames": int(num((a or {}).get("nb_frames"))),
        "size": int(num(fmt.get("size"))),
    }


def count_frames(tools, path):
    """实数帧数（不信容器声明）——与字幕管线同一套口径。"""
    p = subprocess.run([tools["ffprobe"], "-v", "error", "-select_streams", "v:0",
                        "-count_frames", "-show_entries", "stream=nb_read_frames",
                        "-of", "csv=p=0", path],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = p.stdout.decode("utf-8", errors="replace").strip()
    try:
        return int(out.splitlines()[0].strip('"'))
    except Exception:
        return 0


def target_size(src, tgt):
    """算目标分辨率。mode=width 时等比（必要时取偶），保证不变形。"""
    mode = tgt.get("mode", "width")
    w, h = src["width"], src["height"]
    if mode == "exact":
        return int(tgt["width"]), int(tgt["height"]), 1.0
    if mode == "factor":
        f = float(tgt.get("scale", 2.0))
    else:
        W = int(tgt.get("width", 2560))
        f = W / float(w)
    if tgt.get("keep_aspect", True):
        tw, th = int(round(w * f)), int(round(h * f))
    else:
        tw = int(round(w * f))
        th = int(round(h * f))
    if tgt.get("even", True):
        tw += tw % 2
        th += th % 2
    return tw, th, f


def build_filter(cfg, tw, th):
    m = cfg["model"]
    # ★ tvai_up 的**参数之间用冒号**、滤镜之间用逗号 —— 写错会被当成未知滤镜参数
    #   （实测踩过：全用逗号 → "No such filter"，或者参数被静默忽略）
    spec = "tvai_up=model=%s:scale=%d:w=%d:h=%d" % (m["name"], int(m.get("scale", 0)), tw, th)
    for key in ("preblur", "noise", "details", "halo", "blur", "compression",
                "estimate", "blend", "device", "vram", "instances"):
        if m.get(key) is not None:
            spec += ":%s=%s" % (key, _fmt(m[key]))
    # 末尾的 scale 把结果精确钉到目标尺寸（Topaz GUI 也这么做）
    return "%s,scale=w=%d:h=%d:flags=lanczos:threads=0" % (spec, tw, th)


def _fmt(v):
    if isinstance(v, float):
        s = ("%.4f" % v).rstrip("0").rstrip(".")
        return s if s else "0"
    return str(v)


def build_cmd(cfg, tools, src, dst, tw, th):
    e = cfg["encode"]
    cmd = [tools["ffmpeg"], "-hide_banner", "-nostdin", "-y", "-i", src,
           "-sws_flags", "spline+accurate_rnd+full_chroma_int",
           "-filter_complex", build_filter(cfg, tw, th)]
    if e["codec"] == "libx264":
        cmd += ["-c:v", e["codec"], "-crf", str(e.get("crf", 18)),
                "-preset", str(e.get("preset", "medium"))]
    else:
        cmd += ["-c:v", e["codec"], "-preset", str(e.get("preset", "p5"))]
        if e.get("rc") == "constqp":
            cmd += ["-rc", "constqp", "-qp", str(e.get("qp", 18))]
        else:
            cmd += ["-b:v", str(e.get("bitrate", "12M"))]
        if e.get("profile"):
            cmd += ["-profile:v", str(e["profile"])]
    cmd += ["-pix_fmt", e.get("pix_fmt", "yuv420p")]
    # ★ 千万不要写 `-map 0:v:0`：ffmpeg 会先把输入视频流"预定"给显式 map，
    #   于是滤镜图里那个未命名的 tvai_up 输入垫拿不到流，报
    #   "Cannot find an unused video input stream to feed the unlabeled input pad tvai_up:default"
    #   （2026-09-21 实测踩到；Topaz GUI 自身也只 map 音频）
    if e.get("audio", "copy") == "copy":
        cmd += ["-map", "0:a?", "-c:a", "copy"]
    else:
        cmd += ["-map", "0:a?", "-c:a", "aac", "-b:a", "192k"]
    cmd += ["-fps_mode:v", "passthrough", "-movflags", "+faststart", dst]
    return cmd


# ---------------------------------------------------------------- 自检

def sample_frames(tools, path, times, outdir):
    os.makedirs(outdir, exist_ok=True)
    got = {}
    for i, t in enumerate(times):
        dst = os.path.join(outdir, "_up_s_%d.png" % i)
        # 不预删旧样张：ffmpeg `-y` 本来就覆盖写，而删除会计入 safe-delete 预算
        subprocess.run([tools["ffmpeg"], "-hide_banner", "-nostats", "-v", "error", "-y",
                        "-ss", "%.3f" % t, "-i", path, "-frames:v", "1", dst],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(dst):
            got[round(t, 3)] = dst
    return got


def frame_metrics(png):
    """清晰度指标（无 numpy/PIL 时返回 None）。"""
    try:
        import numpy as np
        from PIL import Image
    except Exception:
        return None
    a = np.asarray(Image.open(png).convert("L"), dtype=np.float64)
    k = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float64)
    from numpy.lib.stride_tricks import sliding_window_view
    if min(a.shape) < 8:
        lap = 0.0
    else:
        w = sliding_window_view(a, (3, 3))
        lap = float(np.einsum("ijkl,kl->ij", w, k).var())
    F = np.abs(np.fft.fftshift(np.fft.fft2(a)))
    h, wd = a.shape
    cy, cx = h // 2, wd // 2
    R = min(h, wd) // 8
    Y, X = np.ogrid[:h, :wd]
    mask = ((Y - cy) ** 2 + (X - cx) ** 2) > R * R
    hf = float(F[mask].mean() / F.mean()) if F.mean() else 0.0
    return {"lap_var": round(lap, 3), "hf_ratio": round(hf, 4),
            "mean": round(float(a.mean()), 2), "max": int(a.max())}


def verify(tools, cfg, src_path, dst_path, tmpdir, do_sharpness=True):
    """全部机器断言：尺寸/帧数/时长/音轨/抽样帧非黑 + 比插值更锐。"""
    v = {"checks": [], "passed": True}

    def check(name, ok, detail):
        v["checks"].append({"name": name, "ok": bool(ok), "detail": detail})
        if not ok:
            v["passed"] = False
        return ok

    src = video_info(tools, src_path)
    dst = video_info(tools, dst_path)
    v["src"] = src
    v["dst"] = dst

    want_w, want_h, _ = target_size(src, cfg["target"])
    check("分辨率精确匹配目标", (dst["width"], dst["height"]) == (want_w, want_h),
          "期望 %dx%d，实际 %dx%d" % (want_w, want_h, dst["width"], dst["height"]))
    check("宽高均为偶数（yuv420p 硬要求）",
          dst["width"] % 2 == 0 and dst["height"] % 2 == 0,
          "%dx%d" % (dst["width"], dst["height"]))

    sf = count_frames(tools, src_path)
    df = count_frames(tools, dst_path)
    v["src_frames"], v["dst_frames"] = sf, df
    check("帧数与源一致", sf == df and df > 0, "源 %d 帧 / 新 %d 帧" % (sf, df))
    check("时长一致（±0.2s）", abs(dst["v_duration"] - src["v_duration"]) <= 0.2,
          "源 %.2fs / 新 %.2fs" % (src["v_duration"], dst["v_duration"]))
    check("音轨保留且时长一致（±0.2s）",
          bool(dst["audio_codec"]) and abs(dst["a_duration"] - src["a_duration"]) <= 0.2,
          "源 %s %.2fs / 新 %s %.2fs" % (src["audio_codec"], src["a_duration"],
                                         dst["audio_codec"], dst["a_duration"]))

    # 抽样帧：不许是黑帧/绿帧，且必须比纯 lanczos 插值更锐（否则模型根本没生效）
    n = int(cfg["verify"].get("samples", 3)) or 3
    dur = max(dst["v_duration"], 0.1)
    times = [round(dur * (i + 0.5) / n, 3) for i in range(n)]
    up = sample_frames(tools, dst_path, times, tmpdir)
    smp = sample_frames(tools, src_path, times, tmpdir + "_src")
    rows = []
    for t, png in sorted(up.items()):
        m = frame_metrics(png)
        if m is None:
            rows.append({"t": t, "skipped": "缺少 numpy/Pillow"})
            continue
        row = {"t": t, "up": m}
        sp = smp.get(t)
        if sp and do_sharpness:
            try:
                from PIL import Image
                im = Image.open(sp).convert("RGB").resize(
                    (dst["width"], dst["height"]), Image.LANCZOS)
                lan_png = os.path.join(tmpdir, "_up_lan_%.3f.png" % t)
                im.save(lan_png)
                row["lanczos"] = frame_metrics(lan_png)
                _safe_remove(lan_png)
            except Exception as e:
                row["lanczos"] = {"error": str(e)}
        rows.append(row)
    v["frames"] = rows

    black = [r for r in rows if "up" in r and r["up"]["max"] < 16]
    check("抽样帧不是黑帧/绿帧", not black, "黑帧时间点：%s" % ([r["t"] for r in black] or "无"))

    gain_hf, gain_lap = [], []
    for r in rows:
        lz = r.get("lanczos") or {}
        if "hf_ratio" in lz and "up" in r:
            if lz["hf_ratio"]:
                gain_hf.append(r["up"]["hf_ratio"] / lz["hf_ratio"])
            if lz["lap_var"]:
                gain_lap.append(r["up"]["lap_var"] / lz["lap_var"])
    if gain_hf and gain_lap:
        v["sharpness_gain_hf"] = round(sum(gain_hf) / len(gain_hf), 4)
        v["sharpness_gain_lap"] = round(sum(gain_lap) / len(gain_lap), 4)
        need_hf = float(cfg["verify"].get("min_frame_gain_hf", 1.02))
        need_lap = float(cfg["verify"].get("min_frame_gain_lap", 1.05))
        check("确实比纯插值更锐（说明 AI 模型真的生效了）",
              v["sharpness_gain_hf"] >= need_hf and v["sharpness_gain_lap"] >= need_lap,
              "相对 lanczos：高频 x%.3f（需 ≥%.2f）／拉普拉斯方差 x%.3f（需 ≥%.2f）"
              % (v["sharpness_gain_hf"], need_hf, v["sharpness_gain_lap"], need_lap))
    return v


# ---------------------------------------------------------------- 主流程

def _file_fingerprint(path, chunk=1 << 20):
    """文件指纹 = 大小 + 头尾各 1MB 的 md5。

    ★ 为什么不用 mtime：`subtitle.py --stage all` 每次都重跑一遍「无损拼接」，
    母版内容一模一样但 mtime 变了 —— 用 mtime 当缓存键会导致**每跑一次都重放大一遍**
    （实测代价：8 分钟 GPU 时间白烧）。
    拼接是无损的、对同一批段是可复现字节的 ⇒ 用「内容指纹」当键既准又省。
    """
    size = os.path.getsize(path)
    h = hashlib.md5()
    with open(path, "rb") as f:
        h.update(f.read(chunk))
        if size > chunk * 2:
            f.seek(-chunk, os.SEEK_END)
            h.update(f.read(chunk))
    return size, h.hexdigest()


def cache_key(cfg, tools, src, tw, th):
    size, fp = _file_fingerprint(src)
    src_info = video_info(tools, src)
    blob = json.dumps({
        "src": [os.path.basename(src), size, fp],
        "src_info": [src_info["width"], src_info["height"], src_info["nb_frames"],
                     round(src_info["duration"], 3)],
        "target": [tw, th], "model": cfg["model"], "encode": cfg["encode"],
    }, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def run_ffmpeg(cmd, env, log_path, total_frames, quiet=False):
    """跑 Topaz ffmpeg 并回报进度（用户明确要求长操作必须有进度）。"""
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    t0 = time.time()
    logf = open(log_path, "w", encoding="utf-8", errors="replace")
    logf.write(" ".join(cmd) + "\n\n")
    logf.flush()
    p = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT)
    last = -1
    tail = []
    for raw in p.stdout:
        line = raw.decode("utf-8", errors="replace")
        logf.write(line)
        tail.append(line)
        if len(tail) > 200:
            tail.pop(0)
        m = re.search(r"frame=\s*(\d+)", line)
        if m and total_frames:
            n = int(m.group(1))
            pct = int(n * 100 / total_frames)
            if pct >= last + 5:
                last = pct
                el = time.time() - t0
                eta = (el / max(n, 1)) * max(total_frames - n, 0)
                if not quiet:
                    say("      %3d%%  %d/%d 帧  已用 %.0fs  预计还需 %.0fs"
                        % (pct, n, total_frames, el, eta))
    p.wait()
    logf.close()
    return p.returncode, "".join(tail[-40:]), round(time.time() - t0, 1)


# ---------------------------------------------------------------------------
# ★ 2026-11-01：放大后端三选一 —— topaz（本地）/ rh（云端）/ off（跳过）
# ---------------------------------------------------------------------------
# 用户定的剪辑顺序：母版拼接（封面 + 片段 + BGM）→ **高清放大** → 字幕生成与烧录。
# 放大这一步有两台机器能干活，能力等价、成本不同：
#   · topaz：本地 GPU，免费，慢（整集约 3–8 分钟），画质最稳；
#   · rh   ：云端 RH_Astra + Iris，约 35 币/集、2–3 分钟，不占本机；
#   · off  ：不放大，母版直接进字幕（只在母版本来就是交付规格时合理）。
# 选哪一台是**配置**（config.upscale.json 的 backend），不是代码分支的分叉。
RH_UPSCALE_DEFAULT = {
    "_note": "RunningHub 放大通道。★ 节点映射不在这里 —— 唯一真源是能力卡 "
             "configs/capabilities/rh.upscale.v1.json（卡里有 nodeId + fieldName，"
             "换工作流只改卡，不改代码、不改项目配置）。",
    "label": "RH 放大 · RH_Astra Iris",
    "instance_type": "default",
    "nodes": {},
    "fields": {},
    "keep_audio": True,
    "cleaner_action": "Purge Model",
    "timeout_min": 40.0,
    "poll_interval": 5.0,
}

RH_CARD_REL = os.path.join("configs", "capabilities", "rh.upscale.v1.json")


def _repo_root():
    """本脚本在 <repo>/stages/subtitle/scripts/ ⇒ 上溯四层是仓库根。"""
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))


def _load_upscale_card():
    """读放大能力卡；读不到返回 None（由调用方报「拿不到节点映射」）。"""
    d = load_json(os.path.join(_repo_root(), RH_CARD_REL), None)
    return d if isinstance(d, dict) else None


def _flat_nodes(card_nodes):
    """卡里的 `{角色: {nodeId, fieldName}}` → 扁平的 nodeId / fieldName 两张表。"""
    ids, fields = {}, {}
    for k, v in (card_nodes or {}).items():
        if isinstance(v, dict):
            if v.get("nodeId"):
                ids[k] = str(v["nodeId"])
            if v.get("fieldName"):
                fields[k] = str(v["fieldName"])
        elif v not in (None, ""):
            ids[k] = str(v)
    return ids, fields


def rh_spec(cfg_rh=None):
    """合成 RH 放大参数：代码默认 < 能力卡 < 项目配置（`config.upscale.json` 的 rh 段）。"""
    spec = deep_merge(RH_UPSCALE_DEFAULT, {})
    cap = _load_upscale_card()
    if cap:
        spec["workflow_id"] = str(cap.get("workflow_id") or "")
        spec["nodes"], spec["fields"] = _flat_nodes(cap.get("nodes"))
        if "keep_audio" in cap:
            spec["keep_audio"] = bool(cap["keep_audio"])
    return deep_merge(spec, cfg_rh or {})


def _find_engine_dir():
    """找引擎目录（runninghub_client.py 所在）。找不到返回 None。

    RH 放大**不另写一套 HTTP**：协议层（上传/建任务/轮询）只有引擎那一份实现，
    这里复用它。找不到就明确说「用 --backend topaz」，不要偷偷发请求。
    """
    cands = []
    env = os.environ.get("SOLODRAMA_ENGINE")
    if env:
        cands.append(os.path.join(env, "stages", "video", "workflow", "scripts", "engine"))
        cands.append(env)
    repo = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))   # <repo>/stages/subtitle/scripts → 上溯四层
    cands.append(os.path.join(repo, "stages", "video", "workflow", "scripts", "engine"))
    for c in cands:
        if c and os.path.isfile(os.path.join(c, "runninghub_client.py")):
            return c
    return None


def _rh_base_url():
    """运行时站点：问 `_site.runtime_site()`（与能力卡/体检同一真源），失败才读 channels.json。"""
    repo = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    try:
        p = os.path.join(repo, "stages", "production", "scripts")
        if p not in sys.path:
            sys.path.insert(0, p)
        from _site import runtime_site                       # noqa: WPS433
        url, _src, _ignored = runtime_site()
        if url:
            return url, _src
    except Exception:                                        # noqa: BLE001
        pass
    try:
        ch = load_json(os.path.join(repo, "configs", "channels.json"), {}) or {}
        rh = ch.get("runninghub") or {}
        key = os.environ.get("SOLODRAMA_RH_SITE") or rh.get("site") or "cn"
        url = ((rh.get("sites") or {}).get(key) or {}).get("url")
        if url:
            return url, "channels.json"
    except Exception:                                        # noqa: BLE001
        pass
    return "", "站点未解析"


def _probe_pix_fmt(tools, path):
    try:
        j = ffprobe_json(tools, path, "stream=codec_type,pix_fmt")
        for s in j.get("streams", []):
            if s.get("codec_type") == "video":
                return str(s.get("pix_fmt") or "")
    except Exception:                                        # noqa: BLE001
        pass
    return ""


def _prep_rh_input(tools, src, workdir):
    """RH 的 LoadVideo 解不动 hevc / Main 10 / 10bit（实测报 805），先转 h264 8bit。

    已是 h264 + yuv420p 就直接上传（不重复转码，省一次画质损失）。
    """
    os.makedirs(workdir, exist_ok=True)
    info = video_info(tools, src)
    pix = _probe_pix_fmt(tools, src)
    if str(info.get("codec") or "").lower() == "h264" and pix in ("yuv420p", "yuvj420p"):
        return src, "源已是 h264/%s，直接上传" % pix
    dst = os.path.join(workdir, "_rh_in.mp4")
    p = subprocess.run([tools["ffmpeg"], "-hide_banner", "-nostats", "-v", "error", "-y",
                        "-i", src, "-c:v", "libx264", "-crf", "16", "-preset", "medium",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                        "-ac", "2", "-ar", "48000", dst],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if not os.path.isfile(dst) or os.path.getsize(dst) < 1024:
        raise RuntimeError("转 h264 输入失败：%s"
                           % p.stdout.decode("utf-8", "replace")[-400:])
    return dst, "转 h264/yuv420p（原 %s/%s，RH 服务端解不动）" % (info.get("codec"), pix)


async def _rh_upscale_async(spec, base_url, api_key, src, dst, tw, th, prefix, log):
    import httpx                                            # noqa: WPS433
    from runninghub_client import RunningHubClient          # noqa: WPS433

    client = RunningHubClient(api_key, base_url, timeout=90.0, channel="v2")
    log("上传：%s（%.1f MB）" % (os.path.basename(src),
                              os.path.getsize(src) / 1048576.0))
    up = await client.upload_file(src)
    short, long_ = (tw, th) if tw <= th else (th, tw)
    n, f = (spec.get("nodes") or {}), (spec.get("fields") or {})
    try:
        vid, pref = n["video_in"], n["prefix"]
        n_short, n_long = n["short_edge"], n["long_edge"]
        n_clean = n.get("cleaner")
    except KeyError as e:                                     # noqa: F841
        raise RuntimeError("能力卡缺节点映射 %s —— 检查 configs/capabilities/rh.upscale.v1.json"
                           % e)
    nodes = RunningHubClient.build_node_list([
        (vid, f.get("video_in") or "file", up["fileName"]),
        # keep_audio 挂在 LoadVideo 上，卡里没单列（它是同一节点的另一个输入）
        (vid, "keep_audio", "true" if spec.get("keep_audio", True) else "false"),
        (pref, f.get("prefix") or "filename_prefix", prefix),
        (n_short, f.get("short_edge") or "value", str(int(short))),
        (n_long, f.get("long_edge") or "value", str(int(long_))),
        (n_clean, f.get("cleaner") or "model_action",
         spec.get("cleaner_action") or "Purge Model"),
    ])
    tid = await client.create_task("workflow", str(spec["workflow_id"]), nodes,
                                  spec.get("instance_type") or "default")
    log("任务已提交：%s（短边=%d 长边=%d）" % (tid, short, long_))
    last = await client.poll_until_done(
        tid, timeout_min=float(spec.get("timeout_min") or 40.0),
        interval=float(spec.get("poll_interval") or 5.0),
        on_poll=lambda _t, st: log("  … %s" % st))
    if str(last.get("status")) != "SUCCESS":
        raise RuntimeError("RH 放大失败：status=%s %s"
                           % (last.get("status"), last.get("raw") and
                              str(last["raw"])[:300] or ""))
    urls = [r.get("url") for r in (last.get("results") or []) if r.get("url")]
    if not urls:
        raise RuntimeError("RH 放大成功但没返回文件：%s" % str(last.get("raw"))[:300])
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    async with httpx.AsyncClient(timeout=900.0, follow_redirects=True) as hc:
        async with hc.stream("GET", urls[0]) as resp:
            resp.raise_for_status()
            with open(dst, "wb") as fh:
                async for chunk in resp.aiter_bytes(1 << 20):
                    fh.write(chunk)
    return {"task_id": tid, "url": urls[0], "usage": last.get("usage") or {}}


def _upscale_rh(cfg, src, dst, tw, th, result, quiet=False, spec=None):
    """云端放大：上传 → 提交 → 轮询 → 下载 → 裁到精确目标。"""
    spec = rh_spec(spec or (cfg.get("rh") or {}))
    out = (lambda m: (not quiet) and say(m))
    key = os.environ.get("RUNNINGHUB_API_KEY") or ""
    if not key:
        result["error"] = "未设置 RUNNINGHUB_API_KEY（云端放大要计费，必须显式给 key）"
        return result
    base_url, src_note = _rh_base_url()
    if not base_url:
        result["error"] = "拿不到 RunningHub 站点（%s）；改用 --backend topaz" % src_note
        return result
    eng = _find_engine_dir()
    if not eng:
        result["error"] = ("找不到引擎目录（runninghub_client.py）—— 云端放大复用引擎协议层，"
                           "不另写一套 HTTP。改用 --backend topaz")
        return result
    tools = detect_toolchain(cfg)[0]
    # 云端放大只用系统 ffmpeg/ffprobe，**不依赖 Topaz** —— 没装 Topaz 也能跑 RH。
    tools = {"ffmpeg": tools.get("ffmpeg") or "ffmpeg",
             "ffprobe": tools.get("ffprobe") or "ffprobe",
             "model_dir": tools.get("model_dir"), "model_data_dir": tools.get("model_data_dir")}
    workdir = os.path.join(os.path.dirname(dst), "_up_tmp")
    os.makedirs(workdir, exist_ok=True)
    t0 = time.time()
    result["backend"] = "rh"
    result["site"] = base_url
    result["workflow_id"] = str(spec["workflow_id"])
    try:
        feed, feed_note = _prep_rh_input(tools, src, workdir)
        result["actions"].append(feed_note)
        out("上传前处理：%s" % feed_note)
        if eng not in sys.path:
            sys.path.insert(0, eng)
        got = asyncio.run(_rh_upscale_async(
            spec, base_url, key, feed, dst + ".raw.mp4", tw, th,
            "%s_up" % os.path.splitext(os.path.basename(dst))[0].split("_master")[0],
            out))
        result["task_id"] = got["task_id"]
        result["usage"] = got["usage"]
        # 平台按源宽高比吸附输出（672×1216 → 1062×1920），这里裁到精确目标，
        # 保证文件名 `_master_1080x1920` 名副其实；不补边（补边=黑边）。
        vf = ("scale=%d:%d:force_original_aspect_ratio=increase:flags=lanczos,"
              "crop=%d:%d,setsar=1" % (tw, th, tw, th))
        p = subprocess.run([tools["ffmpeg"], "-hide_banner", "-nostats", "-v", "error", "-y",
                            "-i", dst + ".raw.mp4", "-vf", vf,
                            "-c:v", "libx264", "-crf", "17", "-preset", "medium",
                            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                            "-movflags", "+faststart", dst],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if not os.path.isfile(dst) or os.path.getsize(dst) < 1024:
            raise RuntimeError("裁切输出失败：%s" % p.stdout.decode("utf-8", "replace")[-400:])
        s_info = video_info(tools, src)
        d_info = video_info(tools, dst)
        checks = []
        checks.append({"name": "分辨率", "ok": (d_info["width"], d_info["height"]) == (tw, th),
                       "detail": "%dx%d（目标 %dx%d）"
                                 % (d_info["width"], d_info["height"], tw, th)})
        checks.append({"name": "时长", "ok": abs(d_info["duration"] - s_info["duration"]) < 1.0,
                       "detail": "%.2fs / 源 %.2fs" % (d_info["duration"], s_info["duration"])})
        if s_info.get("audio_codec"):
            checks.append({"name": "音轨", "ok": bool(d_info.get("audio_codec")),
                           "detail": "%s（keep_audio=true 必须保住台词）"
                                     % (d_info.get("audio_codec") or "无")})
        result["verify"] = {"passed": all(c["ok"] for c in checks), "checks": checks}
        result["elapsed_s"] = round(time.time() - t0, 1)
        result["ok"] = bool(result["verify"]["passed"])
        if not result["ok"]:
            result["error"] = "自检未通过：" + "；".join(
                c["detail"] for c in checks if not c["ok"])
        # 清理原始下载（保留会白占一份整集空间）
        try:
            os.remove(dst + ".raw.mp4")
        except OSError:
            pass
    except Exception as e:                                    # noqa: BLE001
        result["error"] = "%s: %s" % (type(e).__name__, e)
        result["elapsed_s"] = round(time.time() - t0, 1)
    return result


def upscale_episode(ws, ep, cfg, *, force=False, dry_run=False, verify_only=False,
                    fallback_lanczos=False, target_override=None, quiet=False,
                    allow_flat=False, sample=0.0, out_path=None):
    subs_dir = os.path.join(out_dir_of(ws), "subs", ep)
    src = os.path.join(subs_dir, "%s_master.mp4" % ep)
    # ★ 2026-10-22：产物名如实写分辨率（<ep>_master_1080x1920.mp4），不再叫 _master_2k
    _sz = None
    try:
        _t = (target_override or cfg.get("target") or {})
        if str(_t.get("mode")) == "exact" and _t.get("width") and _t.get("height"):
            _sz = (int(_t["width"]), int(_t["height"]))
    except (TypeError, ValueError):
        _sz = None
    dst = out_path or (os.path.join(subs_dir, ep + MASTER_UP_SUFFIX % _sz) if _sz
                       else upscaled_path(subs_dir, ep))
    # 自定义输出（测速样片）时，报告也写到旁边去，绝不覆盖正式产物的 <ep>_upscale.json
    report_path = (dst + ".json") if out_path else os.path.join(
        subs_dir, "%s_upscale.json" % ep)
    log_path = (os.path.splitext(dst)[0] + ".ffmpeg.log") if out_path else os.path.join(
        subs_dir, "%s_upscale.log" % ep)
    tmpdir = os.path.join(subs_dir, "_up_tmp")

    result = {"episode": ep, "src": src, "dst": dst, "ok": False, "actions": []}
    if not os.path.exists(src):
        result["error"] = "找不到母版（先跑 subtitle.py --stage master）：%s" % src
        return result

    # ★ 测速样片：只取母版前 N 秒。为什么先落盘成一个小文件再跑：
    #   这样后面所有断言（帧数一致 / 时长一致 / 音轨一致）口径完全不变，
    #   否则"源 3805 帧 vs 样片 1440 帧"会直接判失败。
    sample_src = None
    if sample and sample > 0:
        sample_src = os.path.splitext(dst)[0] + ".src.mp4"
        os.makedirs(os.path.dirname(sample_src), exist_ok=True)
        r = subprocess.run([cfg["tool"].get("ffmpeg") or "ffmpeg", "-hide_banner",
                            "-v", "error", "-y", "-t", "%.3f" % sample, "-i", src,
                            "-c", "copy", sample_src],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if not os.path.exists(sample_src):
            result["error"] = "抽测速样片失败：%s" % r.stdout.decode("utf-8", "replace")[-300:]
            return result
        src = sample_src
        result["sample_seconds"] = sample
        result["actions"].append("测速模式：只用母版前 %.1f 秒" % sample)

    tools, problems = detect_toolchain(cfg)
    result["tools"] = tools
    src_info = None
    if os.path.exists(tools.get("ffprobe") or "ffprobe"):
        try:
            src_info = video_info(tools, src)
        except Exception as e:
            result["error"] = "读源视频失败：%s" % e
            return result
    result["source_info"] = src_info
    if src_info and target_override:
        cfg = deep_merge(cfg, {"target": target_override})

    tw, th, factor = target_size(src_info, cfg["target"]) if src_info else (0, 0, 0)
    result["target"] = {"width": tw, "height": th, "factor": round(factor, 4),
                        "model": cfg["model"]["name"]}

    # ---- 后端分派：topaz（默认）/ rh（云端）/ off（跳过）-------------------
    backend = str(cfg.get("backend") or "topaz").strip().lower()
    result["backend"] = backend
    if backend in ("off", "none", "skip"):
        # 「跳过」是合法选择，不是失败：母版已是交付规格时才该这么配。
        # 落一份 skipped 报告，节点判据据此放行（否则节点会一直等一个不会出现的文件）。
        result.update(ok=True, skipped=True,
                      note="按配置跳过放大（backend=off）—— 母版直接进字幕")
        dump_json(report_path, result)
        if not quiet:
            say("[i] 已按配置跳过放大（backend=off）；母版：%s" % src)
        return result
    if backend == "rh":
        if sample:
            result["error"] = "--sample 只支持本地 Topaz 测速；云端按整集计费，不做样片"
            return result
        spec = rh_spec(cfg.get("rh") or {})
        if verify_only:
            if not os.path.exists(dst):
                result["error"] = "产物不存在，无法只做验证：%s" % dst
                return result
            result["ok"] = True
            return result
        if dry_run:
            if not spec.get("nodes"):
                # 干跑最容易骗人：节点映射读不到时，下面照样能打印"短边/长边"（那是算出来的，
                # 不是从卡里来的）。必须在这里就红，否则真跑时才炸。
                result["error"] = ("拿不到 RH 放大节点映射 —— 能力卡缺失或损坏：%s"
                                   % os.path.join(_repo_root(), RH_CARD_REL))
                return result
            short, long_ = (tw, th) if tw <= th else (th, tw)
            result["plan"] = {
                "backend": "rh", "workflow_id": str(spec["workflow_id"]),
                "site": _rh_base_url()[0],
                "nodes": {"video_in": spec["nodes"].get("video_in"),
                          "prefix": spec["nodes"].get("prefix"),
                          "short_edge": short, "long_edge": long_,
                          "keep_audio": spec.get("keep_audio", True)},
                "source": src, "dst": dst,
                "note": "云端放大按整集计费（实测约 35 币/61s 集）；加 --force 不会跳过缓存",
            }
            result["ok"] = True
            if not quiet:
                say("[dry-run] RH 放大：%s → %s（短边 %d / 长边 %d，节点 %s/%s）"
                    % (os.path.basename(src), os.path.basename(dst), short, long_,
                       spec["nodes"].get("short_edge"), spec["nodes"].get("long_edge")))
            return result
        result = _upscale_rh(cfg, src, dst, tw, th, result, quiet=quiet, spec=spec)
        dump_json(report_path, result)
        return result
    if backend not in ("topaz", "local"):
        result["error"] = ("未知 backend=%r（可选 topaz / rh / off）；"
                           "配置在 config.upscale.json 的 backend" % backend)
        return result

    if src_info and (tw, th) == (src_info["width"], src_info["height"]):
        result["error"] = "目标分辨率与源相同（%dx%d），无需放大" % (tw, th)
        return result

    # Topaz 可用性
    tvai_ok = bool(tools.get("ffmpeg")) and not problems and probe_filter(tools)
    n_weights, sample_files = model_weight_files(tools, cfg["model"]["name"]) if tools.get("model_data_dir") else (0, [])
    result["model_weights"] = {"count": n_weights, "sample": sample_files}
    if tvai_ok and n_weights == 0:
        tvai_ok = False
        problems = list(problems) + [
            "模型 %s 的权重（*.tz3）不在 %s 里" % (cfg["model"]["name"],
                                            tools.get("model_data_dir") or "?")]
    result["topaz_available"] = tvai_ok
    result["problems"] = problems
    # ★ 反馈 P1-14：把「Topaz ffmpeg 无 libass」这条主动探出来，而不是等人踩坑。
    _burn_note = burn_subtitle_note(tools)
    if _burn_note:
        result["subtitle_note"] = _burn_note

    if verify_only:
        if not os.path.exists(dst):
            result["error"] = "产物不存在，无法只做验证：%s" % dst
            return result
        v = verify(tools, cfg, src, dst, tmpdir, do_sharpness=not fallback_lanczos)
        result["verify"] = v
        result["ok"] = v["passed"]
        return result

    if dry_run:
        cmd = build_cmd(cfg, tools, src, dst, tw, th)
        fps = float((cfg.get("perf") or {}).get("expected_fps") or 8.2)
        est = round(src_info["nb_frames"] / fps, 1) if src_info["nb_frames"] else None
        result["plan"] = {
            "command": " ".join('"%s"' % c if " " in c else c for c in cmd),
            "env": {"TVAI_MODEL_DIR": tools.get("model_dir"),
                    "TVAI_MODEL_DATA_DIR": tools.get("model_data_dir")},
            "estimated_seconds": est,
            "estimated_human": ("约 %.1f 分钟（按实测 %.1f 帧/秒估）" % (est / 60.0, fps)
                                if est else None),
            "estimated_size_mb": round(src_info["size"] * (tw * th) / float(
                max(src_info["width"] * src_info["height"], 1)) * 0.9 / 1048576.0, 1),
            "source": src_info,
        }
        result["ok"] = tvai_ok
        if not tvai_ok:
            result["hint"] = _hint(problems)
        return result

    if not tvai_ok and not fallback_lanczos:
        result["error"] = "Topaz 不可用，且没有开 --fallback-lanczos（拒绝用插值冒充高清）"
        result["hint"] = _hint(problems)
        return result

    key = cache_key(cfg, tools, src, tw, th)
    old = load_json(report_path, {}) or {}
    if (not force) and (not sample) and os.path.exists(dst) and old.get("cache_key") == key and old.get("ok"):
        result["ok"] = True
        result["cached"] = True
        result["verify"] = old.get("verify")
        result["elapsed_s"] = 0
        result["actions"].append("命中缓存（参数与源都没变），跳过重跑")
        return result

    os.makedirs(subs_dir, exist_ok=True)
    env = os.environ.copy()
    if tools.get("model_dir"):
        env["TVAI_MODEL_DIR"] = tools["model_dir"]
    if tools.get("model_data_dir"):
        env["TVAI_MODEL_DATA_DIR"] = tools["model_data_dir"]
    env.update(tools.get("extra_env") or {})

    total = src_info["nb_frames"] or 0
    if tvai_ok:
        cmd = build_cmd(cfg, tools, src, dst, tw, th)
        engine = "topaz:%s" % cfg["model"]["name"]
    else:
        cmd = [tools["ffprobe"], "-version"] if False else [
            "ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", src,
            "-vf", "scale=w=%d:h=%d:flags=lanczos" % (tw, th),
            "-c:v", cfg["encode"]["codec"], "-pix_fmt", "yuv420p"]
        if cfg["encode"]["codec"] == "h264_nvenc":
            cmd += ["-preset", str(cfg["encode"].get("preset", "p5")),
                    "-rc", "constqp", "-qp", str(cfg["encode"].get("qp", 18)),
                    "-profile:v", "high"]
        cmd += ["-map", "0:v:0", "-map", "0:a?", "-c:a", "copy",
                "-fps_mode:v", "passthrough", "-movflags", "+faststart", dst]
        engine = "lanczos(插值，非 AI)"
    result["engine"] = engine
    result["actions"].append("开始放大：%s -> %dx%d（%s）" % (
        "%dx%d" % (src_info["width"], src_info["height"]), tw, th, engine))
    if not tvai_ok:
        result["warning"] = ("Topaz 不可用，本次用 lanczos 插值把分辨率提上去 —— "
                             "**画质并不会真的变好**，只是分辨率数字变大。原因：%s"
                             % "；".join(problems))

    if total and not quiet:
        say("   放大 %s：%dx%d -> %dx%d ｜ %d 帧 ｜ 模型 %s"
            % (ep, src_info["width"], src_info["height"], tw, th, total, engine))
    rc, tail, elapsed = run_ffmpeg(cmd, env, log_path, total, quiet=quiet)
    result["elapsed_s"] = elapsed
    result["ffmpeg_rc"] = rc
    result["avg_fps"] = round(total / elapsed, 2) if elapsed > 0 and total else None
    if rc != 0 or not os.path.exists(dst):
        result["error"] = "ffmpeg 失败 rc=%s" % rc
        result["tail"] = tail
        result["hint"] = _hint(problems) if problems else ""
        return result

    v = verify(tools, cfg, src, dst, tmpdir, do_sharpness=tvai_ok)
    result["verify"] = v
    result["ok"] = bool(v["passed"])
    if not result["ok"] and not allow_flat:
        result["error"] = "产物自检未全部通过（见 verify.checks）"
    result["cache_key"] = key
    _cleanup(tmpdir)
    _cleanup(tmpdir + "_src")
    if sample_src and os.path.exists(sample_src):
        # 样片源留着没意义（下一条命令就是另一套参数），但报告里保留它是哪一段
        _safe_remove(sample_src)
    # 测速模式下额外给出「整集 / 30·60·90 分钟剧」的外推，省得每次口算
    if sample and result.get("avg_fps"):
        fps = result["avg_fps"]
        src_full = video_info(tools, os.path.join(subs_dir, "%s_master.mp4" % ep))
        frames_full = src_full["nb_frames"]
        result["extrapolation"] = {
            "fps": fps,
            "full_frames": frames_full,
            "episode_minutes": round(frames_full / fps / 60.0, 2),
            "per_video_minute_minutes": round(60.0 * 24 / fps / 60.0, 3),
            "drama_30min_hours": round(30 * 60 * 24 / fps / 3600.0, 2),
            "drama_60min_hours": round(60 * 60 * 24 / fps / 3600.0, 2),
            "drama_90min_hours": round(90 * 60 * 24 / fps / 3600.0, 2),
        }
    dump_json(report_path, result)
    return result


def _cleanup(d):
    """只删自己建的临时目录里的文件（本项目有过「通配符删错交付物」的事故，这里写死路径）。"""
    try:
        for n in os.listdir(d):
            p = os.path.join(d, n)
            if os.path.isfile(p):
                _safe_remove(p)
        os.rmdir(d)
    except OSError:
        pass


# ---------------------------------------------------------------- 删除预算
# ★ 2026-10-22（实跑排障）：宿主环境的 safe-delete 钩子按【会话/轮次】累计删除数量
#   计数（阈值 50），批量跑 30 集时必炸：
#     `[safe-delete][SAFE_DELETE_BULK_CONFIRM_REQUIRED] {"count":50,"threshold":50,...}`
#   表现为「Topaz 已经 100% 完成，进程却被杀，成片没出来」——实测 ep28/ep29/ep30 全中。
#   旧实现在每集末尾 `_cleanup(tmpdir)` + 逐帧删样张，30 集 = 100+ 次删除。
#   改法：**自我设额**（默认 30，留足余量给宿主其他删除），用完即停，不再抛给钩子；
#   剩余临时文件留在 <ws>/output/subs/<ep>/_up_tmp，不影响交付，需要时人工清理。
DELETE_BUDGET = int(os.environ.get("SOLODRAMA_DELETE_BUDGET") or 30)
_deleted = 0


def _safe_remove(path):
    """在预算内删除一个文件；超预算或无权限则跳过（返回是否删掉）。"""
    global _deleted
    if not path or _deleted >= DELETE_BUDGET:
        return False
    try:
        if os.path.isfile(path):
            os.remove(path)
            _deleted += 1
            return True
    except OSError:
        pass
    return False


def _hint(problems):
    if not problems:
        return ""
    return ("\n".join("  - %s" % p for p in problems) +
            "\n  修法：① 打开一次 Topaz Video 图形界面，用该模型跑一次导出（权重会自动下载）；"
            "\n        ② 或在 video-pipeline/config.upscale.json 的 tool.install_dir / "
            "tool.model_dir / tool.model_data_dir 里写死路径。")


def canon_ep(s):
    """集号规范化为 `epNN`（两位）；与 subtitle.py 同一口径（`26` / `EP26` 都接受）。"""
    m = re.match(r"(?:ep)?\s*0*(\d{1,4})$", str(s or "").strip(), re.I)
    if not m:
        raise SystemExit("--ep 无法识别：%r（要 epNN 或纯数字，例如 ep03 / 3）" % s)
    return "ep%02d" % int(m.group(1))


def main():
    harden_stdio()
    ap = argparse.ArgumentParser(description="高清放大（Topaz Video 本地 AI 超分）")
    ap.add_argument("--ep", required=True, help="集号，如 ep03")
    ap.add_argument("--workspace", default=None, help="项目根目录；也可用 SOLODRAMA_WORKSPACE")
    ap.add_argument("--config", default=None, help="自定义配置文件路径")
    ap.add_argument("--target", default=None, help="覆盖目标分辨率，如 2560x1440 或 3840x2160")
    ap.add_argument("--factor", type=float, default=None, help="按倍数放大，如 2")
    ap.add_argument("--model", default=None, help="覆盖模型，如 prob-4 / iris-3 / rhea-1")
    ap.add_argument("--backend", default=None, choices=["topaz", "rh", "off"],
                    help="放大后端：topaz=本地 GPU（默认）｜rh=RunningHub 云端（计费）｜off=跳过")
    ap.add_argument("--dry-run", action="store_true", help="只打印将要执行的命令")
    ap.add_argument("--verify-only", action="store_true", help="只对已有产物做断言")
    ap.add_argument("--sample", type=float, default=0.0, metavar="秒",
                    help="测速样片：只用母版前 N 秒（产物/报告都另存，不碰正式交付物）")
    ap.add_argument("--out", default=None, help="自定义输出路径（配合 --sample 用）")
    ap.add_argument("--force", action="store_true", help="忽略缓存重跑")
    ap.add_argument("--fallback-lanczos", action="store_true",
                    help="Topaz 不可用时退到插值放大（画质不提升，会明确告警）")
    ap.add_argument("--allow-flat", action="store_true", help="自检未过也保留产物")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    args = ap.parse_args()
    args.ep = canon_ep(args.ep)          # 26 / EP26 / ep026 → ep26

    from pathlib import Path
    if args.workspace:
        ws = str(Path(args.workspace).expanduser().resolve())
    elif WS is not None:
        ws = str(WS)
    else:
        raise SystemExit(WS_HINT or "找不到短剧工作区（用 --workspace 指定）")
    cfg = load_config(ws, args.config)
    if args.backend:
        cfg["backend"] = args.backend
    if args.model:
        cfg["model"]["name"] = args.model
    if args.target:
        m = re.match(r"^\s*(\d+)\s*[xX*]\s*(\d+)\s*$", args.target)
        if not m:
            raise SystemExit("--target 格式应为 宽x高，例如 2560x1440")
        cfg["target"] = deep_merge(cfg["target"], {"mode": "exact",
                                                  "width": int(m.group(1)),
                                                  "height": int(m.group(2))})
    elif args.factor:
        cfg["target"] = deep_merge(cfg["target"], {"mode": "factor", "scale": args.factor})

    r = upscale_episode(ws, args.ep, cfg, force=args.force, dry_run=args.dry_run,
                        verify_only=args.verify_only,
                        fallback_lanczos=args.fallback_lanczos,
                        allow_flat=args.allow_flat, quiet=args.json,
                        sample=args.sample, out_path=args.out)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        _print_human(r)
    return 0 if r.get("ok") else 2


def _print_human(r):
    say("=" * 78)
    say("高清放大 · %s" % r["episode"])
    if r.get("subtitle_note"):
        say(r["subtitle_note"])          # 反馈 P1-14：无 libass 时的两遍法提示
    if r.get("error"):
        say("[FAIL] %s" % r["error"])
        if r.get("hint"):
            say(r["hint"])
        if r.get("tail"):
            say("--- ffmpeg 末尾输出 ---")
            say(r["tail"][-1200:])
        return
    if r.get("skipped"):
        say("  结果    已跳过（backend=%s）—— %s" % (r.get("backend"), r.get("note") or ""))
        say("=" * 78)
        return
    t = r["target"]
    say("  源      %s%s" % (r["src"], "（前 %.1f 秒样片）" % r["sample_seconds"]
                            if r.get("sample_seconds") else ""))
    say("  目标    %dx%d（x%.3f）｜ 后端 %s ｜ 模型 %s"
        % (t["width"], t["height"], t["factor"], r.get("backend") or "topaz",
           t["model"] if (r.get("backend") or "topaz") == "topaz"
           else "RH_Astra Iris"))
    ex = r.get("extrapolation")
    if ex:
        say("  外推    本集(%d 帧) 约 %.1f 分钟 ｜ 每 1 分钟视频约 %.2f 分钟"
            % (ex.get("full_frames") or 0, ex["episode_minutes"], ex["per_video_minute_minutes"]))
        say("          30/60/90 分钟剧：%.2f / %.2f / %.2f 小时"
            % (ex["drama_30min_hours"], ex["drama_60min_hours"], ex["drama_90min_hours"]))
    plan = r.get("plan")
    if plan and plan.get("backend") == "rh":
        say("  计划    workflow %s ｜ 站点 %s" % (plan["workflow_id"], plan.get("site") or "?"))
        say("  节点    LoadVideo=%s ｜ SaveVideo=%s ｜ 短边=%s 长边=%s ｜ keep_audio=%s"
            % (plan["nodes"].get("video_in"), plan["nodes"].get("prefix"),
               plan["nodes"].get("short_edge"), plan["nodes"].get("long_edge"),
               plan["nodes"].get("keep_audio")))
        say("  （--dry-run：什么都没提交。云端放大按整集计费）")
    elif plan:
        say("  预计    耗时 %s ｜ 体积 约 %.0f MB"
            % (plan.get("estimated_human") or "?", plan.get("estimated_size_mb") or 0))
        say("  环境    TVAI_MODEL_DIR=%s" % plan["env"].get("TVAI_MODEL_DIR"))
        say("          TVAI_MODEL_DATA_DIR=%s" % plan["env"].get("TVAI_MODEL_DATA_DIR"))
        say("  命令    %s" % plan["command"])
        say("  （--dry-run：什么都没跑。去掉这个参数才会真跑）")
    if r.get("cached"):
        say("  结果    命中缓存，跳过重跑")
    if r.get("elapsed_s"):
        _fps = r.get("avg_fps")
        say("  耗时    %.1fs%s" % (r["elapsed_s"],
                                  (" ｜ 平均 %.2f 帧/秒" % _fps) if _fps else ""))
    if r.get("task_id"):
        say("  任务    %s（usage: %s）" % (r["task_id"],
                                        json.dumps(r.get("usage") or {}, ensure_ascii=False)))
    v = r.get("verify") or {}
    if v:
        say("  自检    %s" % ("全部通过" if v.get("passed") else "有未通过项"))
        for c in v.get("checks", []):
            say("    %s %s —— %s" % ("[OK]  " if c["ok"] else "[FAIL]", c["name"], c["detail"]))
    if r.get("warning"):
        say("  [WARN] %s" % r["warning"])
    d = v.get("dst") or {}
    if d:
        say("  产物    %s（%.1f MB，%d 帧，%.2fs）"
            % (r["dst"], d["size"] / 1048576.0, d["nb_frames"], d["duration"]))
    say("=" * 78)


if __name__ == "__main__":
    sys.exit(main())
