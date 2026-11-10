#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
字幕管线（可复用）—— 从剧本台词 + CTC 强制对齐时间，生成并烧录字幕。

用法（默认：对齐 → 生成 ASS → 无损拼接母版 → 烧录）：
    python scripts/subtitle.py --ep ep03
    python scripts/subtitle.py --ep ep03 --preview 2      # 只出前 2 段的预览，最快看到效果
    python scripts/subtitle.py --ep ep03 --stage ass      # 只生成 ASS，不渲染
    python scripts/subtitle.py --ep ep03 --soft           # 软字幕（不重编视频）
    python scripts/subtitle.py --ep ep03 --force-align    # 强制重跑对齐

★ 2026-09-21 起：**合并之后先做高清放大到交付分辨率（竖屏 1080P），再由用户决定要不要加字幕**。
    python scripts/subtitle.py --ep ep03               # 跑到放大母版就【停下】等你回答
    python scripts/subtitle.py --ep ep03 --burn        # 同一口气跑完（放大 → 烧字幕）
    python scripts/subtitle.py --ep ep03 --no-upscale  # 关掉放大（旧行为，1440p 直接烧）

设计要点（与《L3 字幕与 BGM 组装方案》一致）：
  * 时间轴【不】用提示词切点（实测 52% 偏差 >1s），一律用 CTC 强制对齐的实测时间
  * 样式/断行/位置全部来自 video-pipeline/config.subtitle.json，改配置不改代码
  * 语言参数化：zh 按字符断行（避头尾）；es 按单词边界断行（不切断单词）
  * 每步产物落盘、可缓存、可重跑；末尾有断言兜底（不信任 ffmpeg 退出码）
  * 【先放大、后烧字幕】：烧字幕必然重编码，若先烧后放，字幕会被 AI 超分"重绘"
    （描边发糊、笔画被当成纹理）。所以字幕必须烧在已经放大好的母版上。

产物目录：video-pipeline/output/subs/<ep>/
    align/<seg>.txt      字符级对齐原始输出
    cues.json            每集字幕条目（含来源与实测时间）
    <ep>.ass             成品字幕文件
    <ep>_master.mp4      无损拼接母版（无字幕，1440p）
    <ep>_master_<W>x<H>.mp4  放大后的母版（无字幕，如 1080x1920）★ 字幕烧在它上面
    （旧名 <ep>_master_2k.mp4 仍可读回，仅兼容；新产物不再用这个名字）
    <ep>_subbed.mp4      烧录字幕成片
    report.json          运行报告（可复核）
"""

import argparse
import difflib
import glob
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time

# ---------------------------------------------------------------- 基础设施

def default_workspace():
    """默认工作区解析：环境变量 SOLODRAMA_WORKSPACE > 脚本位置推断 > None。

    为什么不能只靠 `__file__` 推断：本脚本住在 **Skill 包**里时，推出来的是 Skill 目录，
    不是用户项目 —— 会报「找不到配置 <skill>/video-pipeline/config.subtitle.json」。
    ⇒ 调用方用 `--workspace "<项目根>"` 或设 `SOLODRAMA_WORKSPACE` 指过去。

    刻意**不在 import 期退出**（否则连 `--help` 都跑不了）：解析不到返回 None，
    由 main() 给出可照抄的报错。
    """
    env = (os.environ.get("SOLODRAMA_WORKSPACE") or os.environ.get("DRAMA_WORKSPACE"))
    if env and os.path.isdir(env):
        return os.path.abspath(env)
    cand = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if (os.path.isdir(os.path.join(cand, "video-pipeline", "data"))
            or os.path.isfile(os.path.join(cand, "layout.json"))):
        return cand
    return None


ROOT = default_workspace()


# ------------------------------------------------- 分阶段目录（stages/_layout.py 的轻量复刻）
# 为什么要自带一份：本脚本可能被拷进 Skill 包运行，那时仓库的 stages/_layout.py
# 不在 sys.path 上（见 upscale.py 顶部同类约束）。口径必须与 stages/_layout.py 一致：
#   <engine_root>/config.local.json 的 data_dir / out_dir  →  <ws>/layout.json  →  旧默认 data/output
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
    """引擎技术目录（config.*.json / ledger / logs）。"""
    return _layout_paths(ws)[0]


def data_dir_of(ws):
    """出片引擎输入目录（含 shots.json / h3_prompts.json）。"""
    return _layout_paths(ws)[1]


def out_dir_of(ws):
    """出片引擎输出根（批次 / assets / subs 都在它下面）。"""
    return _layout_paths(ws)[2]


def canon_ep(s):
    """集号规范化为 `epNN`（两位）。`3` / `ep3` / `ep03` / `EP03` 都接受。

    ★ 2026-10-22（歧义排查）：旧实现直接用传入的字符串拼路径 —— `--ep 26` 能通过参数
      校验，`_belongs_to_ep()` 也能匹配到 ep26 的分镜，但 align/cues 的路径变成
      `subs/26/`，于是**静默产出 0 条字幕**（还把 `subs/26/` 目录建了出来）。
      同一件事两种写法只有一种对、且错的那种不报错 —— 这是最会骗人的一类歧义。
    """
    m = re.fullmatch(r"(?:ep)?\s*0*(\d{1,4})", str(s or "").strip(), re.I)
    if not m:
        raise SystemExit("--ep 无法识别：%r（要 epNN 或纯数字，例如 ep03 / 3）" % s)
    return "ep%02d" % int(m.group(1))


def harden_stdio():
    """Windows 控制台是 GBK，直接打印非 GBK 字符会崩（本项目已踩过多次）。"""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def run(cmd, env=None, cwd=None, check=True, quiet=True, timeout=None):
    e = os.environ.copy()
    if env:
        e.update(env)
    try:
        p = subprocess.run(cmd, env=e, cwd=cwd, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=timeout)
    except subprocess.TimeoutExpired:
        # ★ 2026-10-22：对齐器实测会**死锁**（Rust 扩展里卡住，不打印任何东西）。
        #   旧实现没有 timeout ⇒ 整条字幕管线永久挂起、日志停在上一行，只能人工杀进程。
        #   现在超时按"这一步失败"处理，由调用方降级（对齐窗口 → 估算），不拖垮整集。
        raise RuntimeError("命令超时（%ss 未返回，已强制终止）：%s"
                           % (timeout, " ".join(map(str, cmd))[:300]))
    out = p.stdout.decode("utf-8", errors="replace")
    if check and p.returncode != 0:
        raise RuntimeError("命令失败 rc=%s\n%s\n%s" % (p.returncode, " ".join(map(str, cmd)), out[-2000:]))
    return p.returncode, out


def esc_filter_path(p):
    """ffmpeg 滤镜里的绝对路径：必须『转义冒号 + 整值加单引号』（已实测，别无他法）。"""
    s = str(p).replace("\\", "/")
    s = re.sub(r"^([A-Za-z]):", r"\1\\:", s)
    return "filename='%s'" % s


def load_json(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def dump_json(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- 配置与素材

def _example_config_path():
    """随脚本发布的默认配置（`stages/subtitle/assets/config.subtitle.example.json`）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    cand = os.path.join(os.path.dirname(here), "assets", "config.subtitle.example.json")
    return cand if os.path.isfile(cand) else ""


def load_config(ws):
    """读项目配置；**没有就用随仓库发布的默认值**。

    ★ 2026-11-01：原先没有 `<engine>/config.subtitle.json` 就直接 `SystemExit`，
      而 `drama init` 只生成 `config.local.json` —— 于是**每个新项目**第一次点
      「拼接母版」都会失败，报的是一句绝对路径（"找不到配置：D://...//config.subtitle.json"），
      用户既不知道要复制哪个文件，也不知道默认值在哪。
      现在回退到 example（并在 stderr 说明一次），新项目开箱可用；
      要改就把它复制到 `video-pipeline/config.subtitle.json`。
    """
    p = os.path.join(engine_root_of(ws), "config.subtitle.json")
    if os.path.exists(p):
        cfg = load_json(p)
    else:
        ex = _example_config_path()
        if not ex:
            raise SystemExit("找不到字幕配置，且仓库里没有默认配置：%s" % p)
        cfg = load_json(ex)
        cfg["_config_path"] = ex
        cfg["_config_is_default"] = True
        sys.stderr.write("[i] 本集没有 config.subtitle.json，先用仓库默认配置：%s\n" % ex)
        sys.stderr.write("    要改断句/时序：把它复制到 %s 再改\n" % p)
    cfg = apply_style_sheet(cfg, load_style_sheet(ws, cfg))
    if not cfg.get("_style_sheet"):
        # ★ 2026-11-01：不再回退旧的百分比算法。回退的代价是「同一份规范在不同剧里
        #   长得不一样」且 qa 查不出来 —— 那正是三语锁死要解决的问题。没有规范就明确报错。
        raise SystemExit(
            "找不到三语字幕规范（configs/subtitle-styles.json）。\n"
            "  找过：%s\n"
            "        <项目>/video-pipeline/config.subtitle-styles.json\n"
            "        <仓库>/configs/subtitle-styles.json"
            % os.path.join(engine_root_of(ws), STYLE_SHEET_NAME))
    return cfg


# ---------------------------------------------------------------------------
# ★ 2026-11-01：三语字幕规范（锁死层）
# ---------------------------------------------------------------------------
# 为什么加这一层：字号原本是「画布高 × font_size_pct」，再被「文本框宽 ÷ 每行字数」
# 反向压住 —— 同一部剧的 1080 与 2K 两版字号不同，三种语言各算一套，实测返工三次。
# 现在把视觉参数（字体/字号/边距/行宽/描边）从 `config.subtitle.json` 抽出来，放进
# 仓库级 `configs/subtitle-styles.json`，以 1080×1920 为基准写**绝对像素**。
#   · 其它画布按 min(W/1080, H/1920) 等比缩放 ⇒ 视觉比例恒定；
#   · 一行字宽超出安全区 = 规范写错了 ⇒ 直接报错，**不静默缩字**（静默缩字正是
#     「同一份规范在不同剧里长得不一样」的成因）。
STYLE_SHEET_NAME = "config.subtitle-styles.json"


def style_sheet_candidates(ws, cfg):
    """样式表的查找顺序：显式指定 > 项目副本 > 仓库真源。

    项目副本（`<engine_root>/config.subtitle-styles.json`）是为了让某一部剧能整体换一套
    视觉；不给就吃仓库真源 —— 那是「可直接复用」的那一份。
    """
    p = str((cfg or {}).get("style_sheet") or "").strip()
    if p:
        yield (os.path.abspath(p) if os.path.isabs(p)
               else os.path.join(engine_root_of(ws), p))
    yield os.path.join(engine_root_of(ws), STYLE_SHEET_NAME)
    yield os.path.join(engine_root_of(ws), "subtitle-styles.json")
    # 仓库真源：`configs/` 下的文件**不带 `config.` 前缀**（与 channels/looks/tracks 一致），
    # 项目副本则跟 config.subtitle.json 同风格叫 config.subtitle-styles.json —— 两种都认。
    # 本文件在 <repo>/stages/subtitle/scripts/ ⇒ 上溯四层才是仓库根。
    # ★ 2026-11-01 实测踩点：只用三层会算到 <repo>/stages，于是「三语规范找不到、
    #   静默回退旧的百分比算法」—— 规范明明存在却不生效，且没有任何报错。
    repo = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    yield os.path.join(repo, "configs", "subtitle-styles.json")
    yield os.path.join(repo, "configs", STYLE_SHEET_NAME)


def load_style_sheet(ws, cfg):
    """→ 样式表 dict（附 `_path`）；一份都没有则返回 None（回退旧的百分比算法）。"""
    for p in style_sheet_candidates(ws, cfg):
        if not os.path.isfile(p):
            continue
        try:
            sheet = load_json(p)
        except Exception as e:                                             # noqa: BLE001
            raise SystemExit("三语字幕规范读不了：%s（%s: %s）" % (p, type(e).__name__, e))
        if not isinstance(sheet, dict) or not isinstance(sheet.get("styles"), dict):
            raise SystemExit("三语字幕规范结构不对（缺 styles）：%s" % p)
        sheet["_path"] = p
        return sheet
    return None


def apply_style_sheet(cfg, sheet):
    """把锁定层合并进 `cfg`：视觉字段覆盖 `languages.*`，落点/安全区固定。

    合并而不是「另走一条分支」：下游（断行 build_cues、断言 qa_safe_area、自检
    verify_render）都在读 `cfg["languages"][lang]`，保持同一份口径才不会出现
    「算字号用一套、断言用另一套」。
    """
    if not sheet:
        return cfg
    for lang, st in (sheet.get("styles") or {}).items():
        lc = cfg.setdefault("languages", {}).setdefault(lang, {})
        if not [k for k in lc if not str(k).startswith("_")]:
            # 老项目的 config.subtitle.json 只有 zh/es，没有 en。样式表能补视觉字段，
            # 但断句/时序字段（`min_duration_s`、`wrap`、`cps_*`）是**硬访问**的 ——
            # 缺了会在 build_cues 里 KeyError。按语系继承一份：中文取 zh，拉丁取 es。
            proto = "zh" if lang == "zh" else "es"
            for k, v in ((cfg.get("languages") or {}).get(proto) or {}).items():
                if not str(k).startswith("_"):
                    lc.setdefault(k, v)
            lc["_inherited_from"] = proto
        for src, dst in (("font", "font"), ("font_px", "font_px"),
                         ("char_width_em", "char_width_em"), ("bold", "bold"),
                         ("max_line_chars", "max_line_chars"), ("max_lines", "max_lines"),
                         ("max_cue_chars", "max_cue_chars"),
                         ("margin_lr_px", "margin_lr_px"),
                         ("outline_px", "outline"), ("shadow_px", "shadow")):
            if st.get(src) is not None:
                lc[dst] = st[src]
        lc["_style_locked"] = True
    pl = sheet.get("placement") or {}
    if pl:
        cfg["placement"] = {"anchor": "ratio",
                            "anchor_top": pl.get("anchor_top", ANCHOR_TOP_DEFAULT)}
    sa = sheet.get("safe_area") or {}
    merged_sa = dict(cfg.get("safe_area") or {})
    merged_sa.update({k: v for k, v in sa.items() if not str(k).startswith("_")})
    cfg["safe_area"] = merged_sa
    cfg["_style_sheet"] = sheet
    return cfg


# ---------------------------------------------------------------------------
# ★ 2026-10-20（反馈 P2-13）：字幕必须只有**一套**纵向坐标
# ---------------------------------------------------------------------------
# 事故：第一版把旁白放顶部 42pt、对白放底部 54pt，用户两次反馈「位置忽高忽低 / 字号不统一」，
# 最终拆成两套坐标是主因；40 集要全量重渲染一次（25 集 × 约 3 分钟本地 GPU）。
# 本引擎的模板本来就是单套（一个 `Style: Default` + 按语言百分比的字号/边距），
# 这里加一条硬校验：**配置里出现「按角色区分的纵向坐标」就直接拦下**，
# 防止后人再把两套坐标加回来。旁白与对白只允许用斜体区分，不允许换位置。
_ROLE_STYLE_KEYS = ("narrator", "narration", "dialogue", "dialog", "subtitle_top",
                    "subtitle_bottom", "top", "bottom")
_VERTICAL_FIELDS = ("margin_v_pct", "margin_v", "margin_bottom_pct", "font_size_pct",
                    "font_size", "alignment")


def check_single_template(cfg) -> tuple:
    """返回 (错误列表, 告警列表)。错误 = 阻断（两套纵向坐标）；告警 = 可疑但不阻断。"""
    errors, warns = [], []
    for key in _ROLE_STYLE_KEYS:
        v = cfg.get(key)
        if isinstance(v, dict) and any(f in v for f in _VERTICAL_FIELDS):
            errors.append("config.subtitle.json 出现了按角色区分的样式段 `%s`"
                          "（含 %s）⇒ 只允许一套模板：同一 Alignment / MarginV / Fontsize，"
                          "旁白与对白仅用斜体区分。请删掉这段，改用 languages.*（按语言、不按角色）。"
                          % (key, "/".join(f for f in _VERTICAL_FIELDS if f in v)))
    for lang, lc in (cfg.get("languages") or {}).items():
        if not isinstance(lc, dict):
            continue
        same = [f for f in ("margin_v_pct", "margin_v") if f in lc]
        if len(same) > 1 and len({str(lc[f]) for f in same}) > 1:
            warns.append("语言 %s 同时给了 %s 且取值不同 ⇒ 以 margin_v_pct 为准，"
                         "建议删掉另一个（避免两套纵向坐标）" % (lang, "/".join(same)))
    return errors, warns


def load_upscale(ws):
    """载入高清放大配置（同目录的 upscale.py + config.upscale.json）。

    为什么要它：合并后要先放大到交付分辨率，字幕是在【放大后的母版】上烧的 ——
    所以字幕画布 = 放大后的分辨率，字号按百分比自动跟着变大（视觉比例不变）。
    """
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import upscale as _up
    except BaseException as e:            # ★ SystemExit 也要接住（_ws 解析不到时会抛它）
        return None, None, "高清放大引擎不可用（%s）" % e
    try:
        return _up, _up.load_config(ws), None
    except BaseException as e:
        return _up, None, "高清放大配置读取失败（%s）" % e


def video_dims(ffprobe, path):
    """取视频流的真实宽高（放大目标要按它算，不能拿配置里的画布冒充）。"""
    _, out = run([ffprobe, "-v", "error", "-select_streams", "v:0",
                  "-show_entries", "stream=width,height", "-of", "csv=p=0", path])
    nums = re.findall(r"\d+", out)
    if len(nums) < 2:
        raise SystemExit("读不到视频宽高：%s" % path)
    return int(nums[0]), int(nums[1])


def ffprobe_frames(ffprobe, path):
    _, out = run([ffprobe, "-v", "error", "-select_streams", "v:0",
                  "-count_frames", "-show_entries", "stream=nb_read_frames",
                  "-of", "csv=p=0", path])
    # ★ 2026-10-22 修复：HEVC 源上 ffprobe 会先往输出里插一行解码器警告
    #   （实测 `[hevc @ ...] alignment_bit_equal_to_one=0`），旧实现直接取第一行整数
    #   会 ValueError 整集中断。改为取第一行「纯数字」。
    for ln in out.splitlines():
        ln = ln.strip()
        if ln.isdigit():
            return int(ln)
    raise SystemExit("读不到帧数：%s（ffprobe 输出片段：%r）" % (path, out[:200]))


def _belongs_to_ep(sid, ep):
    """段 id 是否属于该集（兼容**带集号**与**不带集号**两种命名）。

    ★ 2026-10-21（反馈 10.3）：此前只认 `ep01_shot_01` 前缀；而 `script_continuity._num()`
      取第一个数字组，会把 `shot_ep01_02` 判成第 1 镜并报「丢镜 7 个」，于是项目侧只能把
      shot_id 改成不带集号的 `shot_01` —— 两边要求**正好相反**，字幕管线整体不可用。
      `_num()` 已改为取最后一个数字组（`shot_ep01_02` → 2），这里同步放宽：
        * 带集号（`ep01_shot_01` / `shot_ep01_01`）→ 只收本集的；
        * 不带集号（`shot_01`）→ 全收（集号由 `--ep` 与批次/文件区分）。
    """
    s = str(sid or "")
    if not s:
        return False
    m = re.search(r"(?:^|[_-])ep0*(\d+)(?:[_-]|$)", s, re.I)
    if m:
        try:
            want = int(re.sub(r"[^\d]", "", str(ep)) or 0)
        except (TypeError, ValueError):
            want = 0
        return int(m.group(1)) == want
    return True


def data_ep_dir(ws, ep):
    """本集的数据目录：**优先 `<data>/<ep>/`，回退 `<data>/`**。

    ★ 2026-11-01 修：`convert_storyboard` 从 V0.7.42 起把 data 按集分目录
      （`data/ep01/shots.json`，为了修「跑 ep02 覆盖 ep01」），但字幕管线两处读取
      仍写死 `data/shots.json` —— 于是新布局下**拼接阶段一个段都找不到**，
      报「missing 全部镜头」，而肉眼在 `data/ep01/` 里明明看得见。
      两种布局都认，老项目不用迁移。
    """
    base = data_dir_of(ws)
    for cand in (os.path.join(base, ep or ""), base):
        if cand and os.path.isfile(os.path.join(cand, "shots.json")):
            return cand
    # 两处都没有 shots.json：返回根目录。**不要**返回 `<data>/<ep>/`——
    # 那个目录可能不存在，后续读 h3_prompts.json 会抛 FileNotFoundError，
    # 而真正的症状（没跑 convert）反而看不见了。
    return base


def episode_segments(ws, ep):
    """返回该集的段列表（含成片路径与帧数），顺序 = shots.json 顺序。

    兼容两种产物结构（2026-10-07 扩）：
      A. output/<批次>/<段>/final.mp4          —— 旧单层结构
      B. output/<引擎目录>/<批次>/<段>/final.mp4 —— 《贤妻不装了》的 h3_free / h3_free_acc2 两层结构
    同一段在多处存在时取 **mtime 最新**（错脸返工重出后必须用新版本）。
    """
    _sp = os.path.join(data_ep_dir(ws, ep), "shots.json")
    shots = load_json(_sp) if os.path.isfile(_sp) else []
    ids = [s["shot_id"] for s in shots if _belongs_to_ep(s.get("shot_id"), ep)]
    outdir = out_dir_of(ws)
    # ★ 2026-11-07：段 id 在**各集之间是重名的**（每集都有 shot_001），而下面的 glob
    #   会扫描 outdir 下所有批次目录，`max(mtime)` 于是跨集选中了「最近生成的那一集的
    #   shot_001」。实测事故：ep01 的母版拼进了 ep19 的画面（法庭戏），而 ep01 本身是
    #   产房 + 发布会走廊；因为 ep19 当时正在出片，mtime 最新。
    #   ⇒ 只要 outdir 下存在以集号命名的目录（ep01 / 01 / EP01），就**只在它里面找**，
    #     彻底杜绝跨集串素材。老结构（h3_free/h3_free_acc2 两层）没有集号目录，仍走原路径。
    ep_dirs = [d for d in glob.glob(os.path.join(outdir, "*"))
               if os.path.isdir(d) and os.path.basename(d).lower().lstrip("ep") ==
               str(ep).lower().lstrip("ep")]
    segs, missing = [], []
    for sid in ids:
        if ep_dirs:
            cands = []
            for d in ep_dirs:
                cands += [f for f in glob.glob(os.path.join(d, "*", sid, "final.mp4"))
                          if os.path.getsize(f) > 2048]
                cands += [f for f in glob.glob(os.path.join(d, sid, "final.mp4"))
                          if os.path.getsize(f) > 2048]
        else:
            cands = [f for f in glob.glob(os.path.join(outdir, "*", "*", sid, "final.mp4"))
                     if os.path.getsize(f) > 2048]
            cands += [f for f in glob.glob(os.path.join(outdir, "*", sid, "final.mp4"))
                      if os.path.getsize(f) > 2048]
        if cands:
            best = max(cands, key=os.path.getmtime)
            rel = os.path.relpath(os.path.dirname(best), outdir)
            segs.append({"shot_id": sid, "batch": rel, "file": best})
        else:
            missing.append(sid)
    return segs, missing


def dialogue_lines(ws, ep):
    """从 h3_prompts.json 取该集每段的 <d> 台词（按顺序）。

    ★ 2026-10-22：方括号段改成**可选**。旧正则 `<d>\\[[^\\]]*\\]\\s*...` 要求
      `<d>` 后必须紧跟 `[角色/语气]`，写成 `<d>台词</d>` 时整行被静默丢弃 ——
      表现为「台词明明有、字幕就是没有」，且不报任何错。
    """
    _hp = os.path.join(data_ep_dir(ws, ep), "h3_prompts.json")
    prompts = load_json(_hp) if os.path.isfile(_hp) else {}
    pat = re.compile(r"<d>(?:\s*\[[^\]]*\])?\s*([^<]*)</d>")
    out = {}
    for sid, v in prompts.items():
        if not _belongs_to_ep(sid, ep):
            continue
        out[sid] = [m.group(1).strip() for m in pat.finditer(v.get("prompt", ""))
                    if m.group(1).strip()]
    return out


# ---------------------------------------------------------------- 阶段 1：对齐

def align_in_window(cfg_tools, full, win_path, txt_path, out_txt, cursor, text, iso, extra,
                    win_end=None):
    """在 [cursor, 段尾] 窗口内对齐 text。

    ★ 与旧版的唯一区别：**失败不抛异常**，而是返回 (None, 原因)。
    为什么必须这样：实测 ep06_seg05 第 3 句（30 字 / 2.4s ≈ 12.5 字/秒）会让
    CTC 对齐器内部断言失败（`AssertionError: n != i`）。旧实现里 `run()` 直接抛
    RuntimeError ⇒ **整集字幕全部做不出来**。语速快是内容属性，不该炸管线。
    """
    # ★ 2026-10-07：不再预删窗口 tmp —— 宿主 safe-delete 钩子按【会话轮次】累计
    #   删除数（阈值 50），批量烧录必触发 fail-closed。ffmpeg -y / open("w") 都是
    #   覆盖写，不删旧文件也正确；残留由批量脚本收尾统一清理。
    for p in (win_path, out_txt):
        pass
    cmd = [cfg_tools["ffmpeg"], "-hide_banner", "-nostats", "-v", "error", "-y",
           "-i", full, "-ss", "%.3f" % cursor]
    if win_end is not None:
        # ★ 收紧窗口：CTC 在「窗口远长于台词真实跨度」时会自由乱放
        cmd += ["-t", "%.3f" % max(win_end - cursor, 0.2)]
    cmd += ["-ac", "1", "-c:a", "pcm_s16le", win_path]
    run(cmd)
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(text)
    try:
        run([cfg_tools["aligner"], "--audio_path", win_path, "--text_path", txt_path,
             "--language", iso] + extra, env=cfg_tools.get("aligner_env"),
            timeout=cfg_tools.get("aligner_timeout_s") or 180)
    except OSError as e:
        # ★ 2026-11-10：aligner 路径是**项目配置**，没配就只是个占位符字符串。
        #   `subprocess` 找不到可执行文件时抛的是 FileNotFoundError（OSError 子类），
        #   不是 RuntimeError —— 旧实现只接 RuntimeError，于是一路 traceback 打穿整集，
        #   而不是降级到 whisper/ASR 档。降级链存在的意义就是"缺件也能出字幕"。
        return None, "对齐器不可用（%s）：%s" % (cfg_tools.get("aligner"), e)
    except RuntimeError as e:
        msg = str(e)
        if "命令超时" in msg:
            return None, "对齐器超时（疑似死锁），已跳过该句"
        hits = re.findall(r"(?:AssertionError|RuntimeError|\w*Error):.*", msg)
        return None, (hits[-1].strip()[:120] if hits else "对齐器 rc!=0")
    if not os.path.exists(out_txt):
        return None, "对齐器无输出"
    rel = parse_align(out_txt)
    if not rel:
        return None, "对齐输出为空"
    return rel, None


def split_pieces(text, cfg, limit=12):
    """把一句台词按标点切成有序片段（标点跟随前一片）；无标点且过长则按字符对半切。

    用途：整句一次对齐失败时的**保真降级**——切小后逐片顺序对齐，仍然拿到真实
    CTC 时间轴，而不是直接放弃估算。片段越小，CTC 越容易收敛。
    """
    punct = cfg.get("break_punct", "")
    text = (text or "").strip()
    if len(text) <= 1:
        return [text]
    parts, cur = [], ""
    for ch in text:
        cur += ch
        if ch in punct:
            parts.append(cur)
            cur = ""
    if cur:
        parts.append(cur)
    if len(parts) > 1:
        return parts
    if len(text) > limit:
        mid = len(text) // 2
        return [text[:mid], text[mid:]]
    return [text]


def align_text(cfg_tools, full, tmp, sid, i, text, tag, langcfg, iso, extra,
               cursor, dur, depth=0, problems=None, win_end=None):
    """把一段文本对齐到 [cursor, win_end]（win_end 默认 = 段尾），返回 [(s, e, text), ...]。

    实测依据（2026-09-20 隔离实验，ep06_seg05 第 3 句，30 字 / 2.44s）：
      * 整句 + 2.44s 窗口           → 失败（`<star> != n` / `targets length is too long for CTC`）
      * 整句 + 9.4s 全窗口          → **成功 7.06–9.38**（whisper 真值 7.0–9.4，吻合）
      * 按标点切片 + 2.44s 窗口      → **四片全成功**：0.08–0.32 / 0.38–1.26 / 1.22–1.72 / 1.74–2.40
    ⇒ 结论：CTC 需要「帧数 ≥ 目标 token 数」，罗马化后每个汉字≈4–5 token，
      所以**短窗口装不下长句，但装得下短句**。这不是对齐错位，是表示法开销。

    `win_end` 是「策略」参数：默认段尾（宽窗口）。收窄它可以抑制 CTC 的乱放
    （实测 ep10_seg05 第 2 句在 6.6s 窗口里被放到 9.56–12.12，真值 5.68–6.88）。
    """
    problems = problems if problems is not None else []
    if not text:
        return []
    limit = dur if win_end is None else min(win_end, dur)
    if cursor >= limit - 0.05:
        problems.append({"i": i, "text": text[:16], "reason": "音频已到窗口/尾部，无音频可对齐"})
        return []
    win = os.path.join(tmp, "%s_%s_%d.wav" % (sid, tag, depth))
    inp = os.path.join(tmp, "%s_%s_%d.txt" % (sid, tag, depth))
    out_txt = os.path.splitext(win)[0] + ".txt"
    rel, err = align_in_window(cfg_tools, full, win, inp, out_txt, cursor, text, iso, extra,
                               win_end=win_end)
    if rel is not None:
        s = cursor + rel[0][0]
        e = cursor + rel[-1][1]
        if e <= s:
            e = s + 0.4
        return [(round(s, 3), round(e, 3), text)]
    if depth < 2:
        parts = split_pieces(text, langcfg, limit=12 if depth == 0 else 6)
        if len(parts) > 1:
            out = []
            for k, p in enumerate(parts):
                out += align_text(cfg_tools, full, tmp, sid, i, p, "%s%d" % (tag, k),
                                  langcfg, iso, extra, cursor, dur, depth + 1, problems, win_end)
            if out:
                return out
    problems.append({"i": i, "text": text[:16], "reason": err or "对齐失败"})
    return []


def align_line(cfg_tools, full, tmp, sid, i, text, langcfg, iso, extra, dur, cursor,
               cps_floor=None):
    """顺序约束地对齐**一句**台词，返回 (record, new_cursor, problems)。

    降级链（越靠后越不保真，但绝不让整集失败）：
      ① 整句在 [cursor, 窗口尾] 内对齐       —— 正常路径（ep03 全靠这条）
      ② 按标点切片、各片在**同一窗口**内对齐 —— 快语速长句的保真降级（实测有效）
      ③ 按剩余时长估算                      —— 最后手段，写进 problems 留痕

    `cps_floor`（字/秒）> 0 时启用「紧窗口」策略：把窗口尾收到
    `cursor + max(字数/cps_floor, 1.2) + 0.6`，用来抑制 CTC 的远距离乱放。
    """
    problems = []
    win_end = None
    if cps_floor:
        n = max(spoken_len(text), 1)
        win_end = min(dur, cursor + max(n / float(cps_floor), 1.2) + 0.6)
    spans = align_text(cfg_tools, full, tmp, sid, i, text, "w", langcfg, iso, extra,
                       cursor, dur, 0, problems, win_end)
    if spans:
        # 各片是同一窗口内的独立对齐 ⇒ 可能轻微交叠，这里强制单调不重叠
        fixed, last = [], cursor
        for s, e, t in spans:
            s = max(s, last)
            if e <= s:
                e = s + 0.4
            fixed.append((round(s, 3), round(e, 3), t))
            last = e
        spans = fixed
        s, e = spans[0][0], spans[-1][1]
        source = "ctc-sequential" if len(spans) == 1 else "ctc-piecewise"
        cursor = e
    else:
        remain = max(dur - cursor, 0.0)
        s = round(min(cursor, dur), 3)
        e = round(min(max(cursor + remain, s + 0.4), dur), 3)
        if e <= s:
            # 音频已用尽：宁可退到段尾内侧 0.4s，也绝不越过段尾（越界会盖住下一段）
            e = round(dur, 3)
            s = round(max(dur - 0.4, 0.0), 3)
        source = "fallback-estimate"
        problems.append({"i": i, "text": text[:16],
                         "reason": "整句与切片对齐均失败，按剩余时长估算"})
        cursor = e
    rec = {"i": i, "text": text, "start": round(s, 3), "end": round(e, 3),
           "source": source}
    if len(spans) > 1:
        rec["pieces"] = [{"text": p[2], "start": p[0], "end": p[1]} for p in spans]
    return rec, cursor, problems


def stage_align(ws, ep, cfg, segs, lines, subs_dir, force=False, asr_fill=True, trim=True):
    """逐段做【顺序约束的逐条对齐】，产出 align/<seg>.json。

    ★ 繁体中文（2026-10-07）：traditional_zh=true 时，**对齐仍吃简体原文**——
      CTC 对齐器词典不含繁体字形，喂繁体整段断言失败（实测 <star> != 湯，
      ep01_seg02 全句降级 fallback）。繁体转换在 align 产物【落盘时】做：
      dump 后立即把 lines[].text / problems[].text 做 s2tw 写回 ——
      后续 ASS/cues 从本文件读文本，拿到的即繁体终稿。

    ⚠ 为什么不"整段文本一次性对齐"（踩过的坑）：
       把一段的全部台词一起喂给 CTC，对齐器会把文本在整段音频上重新分配。
       当音频里某处存在与首句声学相似的片段时，首句会被"吸引"过去 ——
       实测 seg05 首句被推到 3.72s（真值 0.08s）、seg06 首句被推到 4.42s（真值 0.20s）。
       隔离实验证明：单独对齐首句时结果完全正确（0.08-1.94）。

    ⚠ 为什么不是"简单逐条对齐"：
       每条都在整段音频上找最佳位置，会互相抢占同一区间（实测 seg07 两行区间重叠）。

    ⇒ 正确做法：逐条对齐 + 【前一条的终点作为下一条的搜索窗口起点】（顺序单调约束）。
       实测：修好 seg05/seg06，且不破坏本来就正确的 seg04（2.52-7.40）。

    ⚠ 2026-09-20 追加：**顺序约束还不够** —— 窗口本身可能远长于台词真实跨度。
       实测 ep10_seg05 第 2 句：窗口 [5.60, 12.22]（6.6s）里被放到 **9.56–12.12**，
       而 whisper 真值是 **5.68–6.88**；结果把剩余音频吃光，第 3/4 句只能估算
       （26 字 / 0.10s = 250 字/秒）。同一病根也会造成**段首首句被推后**。
       ⇒ 采用【双策略 + 声学覆盖度择优】：
          S1「宽窗口」= [cursor, 段尾]（= 既有行为，多数段最优）
          S2「紧窗口」= [cursor, cursor + max(字数/3.5, 1.2) + 0.6]
        用缓存的 whisper 语音区间算「有语音却无字幕」的总时长作为**分数**，
        S2 必须比 S1 好 0.5 秒以上才被采用 —— 保证不牺牲既有正确结果。
    """

    cfg_tools = cfg["tools"]
    lang = cfg["default_language"]
    iso = cfg_tools["aligner_language_code"].get(lang, "cmn")
    adir = os.path.join(subs_dir, "align")
    tmp = os.path.join(subs_dir, "_tmp")
    asr_dir = os.path.join(subs_dir, "asr")
    os.makedirs(adir, exist_ok=True)
    os.makedirs(tmp, exist_ok=True)
    os.makedirs(asr_dir, exist_ok=True)
    extra = cfg_tools.get("aligner_args", ["--split_size", "char", "--romanize"])
    langcfg = cfg["languages"][lang]   # ★ 断句规则在语言段里，别把顶层 config 传下去
    IMPOSS = langcfg.get("cps_impossible", 20.0)
    # 窗口策略：宽 → 紧 → 更紧。按顺序择优，后一档必须比当前最好再**好 0.5 秒**才被采用，
    # 这样既能修「乱放」，又不会牺牲本来对齐正确的段（实测多数段 wide 已是最优）。
    STRATEGIES = [("wide", None), ("tight", 3.5), ("tighter", 6.0)]

    _PUNCT = re.compile(r"[，。！？；：…—、（）「」《》\s\"'!?.,;:\-]")

    def asr_calibrate(txts, srt):
        """★ S3 whisper 校准（2026-10-07 加）：切片 srt 与台词按序字符映射。

        为什么可信：whisper 切片转写的【时间】是实测真值（SKILL.md 口径：
        整段时间戳会被音乐拉长，切片后单独转写才可信）。文本只用来做单调
        匹配——繁体台词 vs whisper 简体转写在比较前统一 OpenCC tw2s 归一。
        全部台词都匹配成功（相似度 >=0.45、顺序单调）才返回 recs，否则
        None（让位给 CTC 档位）。

        ★ 2026-10-22 改：匹配分从「字符**集合**重叠」换成 `text_similarity`
          （difflib 比率）。原因是集合口径实测会误配并把整集粘成一条：
          ep26 原始 38 条 ASR 被并成 4 条，最后一条字幕止于 11.4s（整集 62s）。
        """
        try:
            from opencc import OpenCC
            cc = OpenCC("tw2s")
        except ImportError:
            cc = None

        def norm(s):
            s = cc.convert(s) if cc else s
            return _PUNCT.sub("", s)

        srt_n = [(a, b, norm(x)) for a, b, x in srt]
        pairs, j = [], 0
        for t in txts:
            core = norm(t)
            if not core:
                return None
            # 顺序贪心：在 [j:] 里找与该台词相似度最高的 srt 条。
            # 台词分句与 whisper 转写分句常常不对齐（ep14_seg05：台词 1 句跨
            # 转写 2 条），所以找到主匹配条后还要【向后吞并】仍然相似的
            # 连续条，时间取并入区间并集。
            best, bi = 0.0, None
            for k in range(j, len(srt_n)):
                sc = text_similarity(core, srt_n[k][2])
                if sc > best:
                    best, bi = sc, k
            if best < 0.45 or bi is None:
                return None
            e = bi
            while (e + 1 < len(srt_n)
                   and text_similarity(core, srt_n[e + 1][2]) >= 0.25):
                e += 1
            pairs.append((srt_n[bi][0], srt_n[e][1], t))
            j = e + 1
        fixed, last = [], 0.0
        for a, b, t in pairs:
            a = max(a, last)
            # ★ 最小时长保底（2026-10-07）：whisper 对短句的 end-start 偏窄
            #   （实测「是一隻鐲子。」5 字仅 0.24s → 21 字/秒撞语速生理上限断言，
            #   ep69 整集失败）。按发音字数给保底：0.28s/字、至少 0.6s；
            #   拉长后与下一条的冲突由下方顺序单调（a=max(a,last)）自然消化。
            core_len = len(_PUNCT.sub("", t))
            b = max(b, a + max(0.6, 0.28 * core_len))
            fixed.append({"text": t, "start": round(a, 3), "end": round(b, 3),
                          "source": "whisper-asr"})
            last = b
        return fixed

    def run_strategy(seg, sid, full, dur, txts, cps_floor):
        recs, cursor, bad = [], 0.0, []
        for i, t in enumerate(txts):
            rec, cursor, probs = align_line(cfg_tools, full, tmp, sid, i, t,
                                            langcfg, iso, extra, dur, cursor, cps_floor)
            recs.append(rec)
            bad.extend(probs)
        # ★ 打分：这段音频里「有语音却没有字幕覆盖」的总时长（越小越好）
        gaps = coverage_gaps(cfg, seg["file"],
                             [(r["start"], r["end"]) for r in recs],
                             asr_dir, sid, min_gap=0.5, wav=full)
        score = sum(g[2] for g in gaps)
        # ★ 2026-11-10：加上「字幕压在静音上」的时长（假覆盖）。
        #   只算缺口会让「等分铺满整段」的估算档恒得 0 分而永远胜出，
        #   见 `silence_overlap` 的说明与 shot_004 实测。
        score += silence_overlap(recs, full)
        # 生理上限之外的语速是硬错误，额外重罚
        for r in recs:
            d = max(r["end"] - r["start"], 1e-6)
            if spoken_len(r["text"]) / d > IMPOSS:
                score += 5.0
        return score, recs, bad

    done, skipped, rebuilt, filled = 0, 0, 0, 0
    for seg in segs:
        sid = seg["shot_id"]
        dst = os.path.join(adir, sid + ".json")
        txts = lines.get(sid) or []
        if os.path.exists(dst) and not force:
            # ★ 2026-10-22（实跑排障）：缓存必须**看方法**，不能只看文件存在。
            #   事故：项目侧用 `tools/gen_align_estimate.py` 按「镜长 × 经验话音模型」
            #   写了 method=script_estimate 的近似记录；本函数见文件存在就 skip，
            #   真正的 CTC 对齐**一次都没跑过**，整集字幕位置全靠猜。
            #   实测 ep26_sc02：估算 0.56–6.75s，CTC 真值 3.32–6.26s —— 起点偏 2.8 秒。
            #   ⇒ 只有真对齐结果才算命中缓存；估算档一律重建。
            if _align_cache_ok(dst, seg["file"],
                               deps=[os.path.join(asr_dir, sid + ".wav"),
                                     os.path.join(asr_dir, sid + ".srt")]):
                skipped += 1
                continue
            rebuilt += 1
        if not txts:
            # ★ 2026-10-22：**没有剧本台词 ≠ 没有语音**。H3 会自行在镜头里加话
            #   （实测 ep26_sc03 「¡Pero si no te hagas!」、ep26_sc08「¡Vamos a ver, Nello!」
            #    剧本无 <d> 却确实有人声）。旧实现直接 continue，这些段必然"有声音没字幕"。
            #   这里用 ASR 补位，source 标 asr-unscripted 供人工复核。
            if asr_fill:
                got = asr_fill_segment(cfg, seg, sid, asr_dir, tmp, langcfg, trim)
                if got is not None:
                    dump_json(dst, got)
                    filled += 1
                    print("   + %s 剧本无台词但检测到语音 → ASR 补 %d 条"
                          % (sid, len(got["lines"])))
            continue
        full = os.path.join(tmp, sid + "_full.wav")
        run([cfg_tools["ffmpeg"], "-hide_banner", "-nostats", "-v", "error", "-y",
             "-i", seg["file"], "-vn", "-ar", "16000", "-ac", "1",
             "-c:a", "pcm_s16le", full])
        dur = audio_duration(cfg_tools["ffprobe"], full)
        if dur <= 0:
            # 读不到时长就没法做窗口对齐；跳过该段并留痕，不要静默产出错位字幕
            print("   ⚠ %s 读不到音频时长，跳过对齐" % sid)
            continue
        cand = []
        for sname, floor in STRATEGIES:
            sc, rc, bd = run_strategy(seg, sid, full, dur, txts, floor)
            cand.append((sname, sc, rc, bd))
        # ★ S3 whisper 校准（2026-10-07）：asr/<sid>.srt 与台词按序一一映射时，
        #   whisper 切片时间就是真值——ep01_seg02 实测 CTC 把后 3 句早放 4.7-7s，
        #   而 srt 与语音完全吻合。S3 构造后与 CTC 档位同台竞争（同一覆盖分口径，
        #   低于当前最优 0.5s 以上才顶替——规则与既有档位一致）。
        # ★ 2026-10-22：改走 asr_entries（已剔 `[Música]` 等非语音标记）——
        #   旧实现把音乐标记也当成对齐目标，会把台词钉到音乐段上。
        srt_entries = asr_entries(cfg, seg["file"], asr_dir, sid)
        if srt_entries:
            cal = asr_calibrate(txts, srt_entries)
            if cal:
                gaps3 = coverage_gaps(cfg, seg["file"],
                                      [(r["start"], r["end"]) for r in cal],
                                      asr_dir, sid, min_gap=0.5, wav=full)
                cand.append(("asr-whisper",
                             sum(g[2] for g in gaps3) + silence_overlap(cal, full),
                             cal, []))
        # ★ S4 词级 whisper（2026-11-10 加）：段级时间不可信、CTC 未必装，
        #   这条是「没有 CTC 也能拿到真实对齐」的主力档。
        #   打分口径与前几档完全一致（同一覆盖分），所以它不会靠"身份"顶替谁，
        #   只能靠「有语音却没字幕的时长更少」赢 —— 赢不了就说明段级更好，正常。
        words = asr_words(cfg, seg["file"], asr_dir, sid)
        if words:
            wal = align_by_words(txts, words, langcfg, allow_partial=True)
            if wal:
                _lost = wal[0].pop("_unmatched", None) or []
                # 词级边界贴到真实有声区间（只动边界，不动文本/顺序）
                _snap = snap_to_voiced(wal, full, langcfg) if trim else 0
                gaps4 = coverage_gaps(cfg, seg["file"],
                                      [(r["start"], r["end"]) for r in wal],
                                      asr_dir, sid, min_gap=0.5, wav=full)
                cand.append(("asr-word",
                             sum(g[2] for g in gaps4) + silence_overlap(wal, full),
                             wal,
                             [{"i": 0, "text": t[:16],
                               "reason": "词级 ASR 里找不到这句（可能有声但漏转写），"
                                         "未给时间，请人工补或改用 --from-srt"}
                              for t in _lost]))
        # 默认取 wide；后续档位要「好 0.5 秒以上」才顶替
        strat, score, recs, bad = cand[0]
        for sname, sc, rc, bd in cand[1:]:
            if sc < score - 0.5:
                strat, score, recs, bad = sname, sc, rc, bd
        scores = {c[0]: round(c[1], 2) for c in cand}

        # ★ 单条 whisper 校正（2026-10-07）：S3 全匹配失败回退 CTC 后，仍可能有
        #   个别句被压进极短区间（cps > 生理上限）。此时用 asr srt 里与该句
        #   字符重叠最高的条目时间替换——覆盖检查已证明那才是真区间
        #   （ep14_seg05 实测：14 字被压进 0.27s，真区间 2.96-4.48s 空着）。
        if srt_entries:
            for _r in recs:
                _d = max(_r["end"] - _r["start"], 1e-6)
                # 触发条件二选一：① 语速超生理上限（对齐错位铁证）
                #                ② 时长 < 0.3s 硬底线（ep81「誰？」单字句 0.08s 实测）
                if spoken_len(_r["text"]) / _d > IMPOSS or _d < 0.3:
                    _cal = asr_calibrate([_r["text"]], srt_entries)
                    if _cal:
                        _r["start"], _r["end"] = _cal[0]["start"], _cal[0]["end"]
                        _r["source"] = "whisper-asr"
                        _r.pop("pieces", None)
                        print("   ⚠ %s 句%d 异常区间 → whisper 校正至 %.2f-%.2f"
                              % (sid, _r["i"], _r["start"], _r["end"]))
        # ★ 2026-10-22（移植 vidpure）：按声学能量把每条字幕收紧到真实发声区间。
        #   为什么需要：CTC/whisper 给出的边界常含前后静音，"字幕先亮 0.5 秒才出声"
        #   与"声音结束字幕还挂着"都是这个原因。收紧有护栏（缩到念不完就放弃）。
        n_trim = tighten_to_audio(recs, full, langcfg) if trim else 0
        dump_json(dst, {"shot_id": sid, "audio_duration": round(dur, 3),
                        "method": strat, "strategy": strat,
                        "src_fingerprint": _src_fingerprint(seg["file"]),
                        "trimmed": n_trim,
                        "gap_score": scores,
                        "lines": recs, "problems": bad})

        # ★ 繁体终稿（2026-10-07）：对齐吃的是简体原文（CTC 词典不含繁体字形，
        #   喂繁体整段 AssertionError），所以转换放在【落盘时】——
        #   把本文件 lines[].text / problems[].text 做 s2tw 写回，
        #   后续 ASS/cues 阶段从本文件读文本，拿到的即繁体。
        if cfg.get("traditional_zh"):
            try:
                from opencc import OpenCC
                _cc = OpenCC(str(cfg.get("traditional_profile") or "s2tw"))
                _d = load_json(dst)
                for _r in _d.get("lines", []):
                    if _r.get("text"):
                        _r["text"] = _cc.convert(_r["text"])
                for _p in _d.get("problems", []):
                    if _p.get("text"):
                        _p["text"] = _cc.convert(_p["text"])
                dump_json(dst, _d)
            except ImportError:
                print("   ★ 警告：traditional_zh=true 但未安装 opencc-python-reimplemented，回退简体")
        s1, s2 = scores["wide"], scores["tight"]
        if bad or strat == "tight":
            note = "；".join(sorted({b["reason"] for b in bad}))[:100] if bad else "覆盖率更优"
            print("   ⚠ %s：策略=%s（缺口分 wide %.2fs / tight %.2fs）｜%d 处降级 %s"
                  % (sid, strat, s1, s2, len(bad), note))
        done += 1
    # ★ 2026-10-07：不再 rmtree _tmp —— 本环境的安全删除钩子对【进程内累积删除】
    #   超 50 个文件强制 fail-closed（SAFE_DELETE_BULK_CONFIRM_REQUIRED），批量烧录
    #   跑到几十集必炸（ep98 实录 count=216）。临时 wav 每集 ~3-8 个、单个 <1MB，
    #   留在原地，由批量脚本/人工在跑完后统一清理。
    # shutil.rmtree(tmp, ignore_errors=True)
    return done, skipped, rebuilt, filled


def media_duration(ffprobe, path):
    """媒体实际时长（秒）；读不到返回 0.0。

    ★ 2026-10-22：与 `ffprobe_frames` 同一类坑 —— ffprobe 在坏流上会先插解码器
      警告行，取「第一行」解析会 ValueError。这里只认第一行**纯数字**，读不到返回 0
      交给调用方兜底，绝不让整集中断。
    """
    try:
        _, out = run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                      "-of", "csv=p=0", path], check=False)
    except Exception:                                                       # noqa: BLE001
        return 0.0
    for ln in (out or "").splitlines():
        ln = ln.strip()
        if re.fullmatch(r"\d+(?:\.\d+)?", ln):
            return float(ln)
    return 0.0


def audio_duration(ffprobe, path):
    return media_duration(ffprobe, path)


def spoken_len(text):
    """只统计【会发音的字】，不含标点——「真的？！」实际只说 2 个字，不是 4 个。
    （踩过的坑：把标点算进去会让语速被高估，误报成"对齐错位"）"""
    return len(re.sub(r"[！？。，、；：…—「」《》（）\s\"'!?.,;:\-]", "", text))


def text_similarity(a, b):
    """两段文本的相似度（0~1），difflib 比率。

    为什么不用「字符集合重叠」（旧实现）：集合丢掉顺序与重复次数，短句之间几乎
    总能撞上几个公共字母。实测 ep26「No puede recordar nada.」与不相干条目靠 e/a/n
    就能拿到 0.5+；更致命的是"向后吞并"以「有任何公共字符」为条件，会把整集
    条目粘成一条（38 条 → 4 条，末条止于 11.4s）。
    """
    a = re.sub(r"\s+", " ", str(a or "").strip().lower())
    b = re.sub(r"\s+", " ", str(b or "").strip().lower())
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


# 真对齐产出的 method 值；其余（script_estimate / fallback-estimate）都算"没对齐"
REAL_ALIGN_METHODS = ("ctc-sequential", "ctc-piecewise", "asr-whisper", "asr-only",
                      "asr-word")


def _align_cache_ok(path, seg_file=None, deps=None):
    """对齐缓存是否可信：必须存在、method 属于真对齐档，且**不比源媒体旧**。

    ★ 2026-10-22（实跑排障）：这是"字幕时间不可信"的根因。项目侧
      `tools/gen_align_estimate.py` 按镜长 × 经验话音模型写了 method=script_estimate
      的近似记录，旧实现只看 `os.path.exists()` 就 skip，于是 CTC **一次都没跑**。
      实测 ep26_sc02：估算 0.56–6.75s vs CTC 真值 3.32–6.26s，起点偏 2.8 秒；
      表现为「字幕凭空提前、念完还在屏幕上」。

    ★ 2026-11-10（第二个根因）：重出成片后，`align/*.json` 仍按旧素材的时间挂着。
      素材换了、对白换了、静音段换了，而这个文件还是「真对齐档」，
      于是 `_align_cache_ok` 返回 True，一切照旧 —— 字幕与音频错位且毫无告警。
      实测 海外剧/28 ep01：asr 切片 22:39 生成，final.mp4 17:00 前就换过，sha256 不同。
      ⇒ 源媒体比缓存新就必须重建（素材重出的代价远小于送审被驳回）。

    `deps` 是这份对齐**依赖的输入**清单：源媒体 + 该段的 ASR 切片/转写。
    任一比缓存新就重建 —— 只比源媒体是不够的：asr 切片被重抽后（换的是转写证据、
    不是素材本身），旧对齐同样是错的，而且它的 mtime 完全看不出来。
    """
    try:
        rec = load_json(path)
    except Exception:                                                       # noqa: BLE001
        return False
    if str(rec.get("method") or "") not in REAL_ALIGN_METHODS:
        return False
    # ★ 优先用指纹（能抓到「mtime 更新但内容错了」）。
    #   旧记录**没有** src_fingerprint —— 一律视为过期，理由与 `_asr_cache_fresh` 相同：
    #   本次实测的错误缓存恰好「mtime 更新 + 时长一致 + 内容错位」，
    #   所有基于时间的判据都会放行它。缺指纹就重建一次，之后就一直有指纹了。
    if seg_file:
        rec_src = str(rec.get("src_fingerprint") or "")
        if not rec_src or rec_src != _src_fingerprint(seg_file):
            return False
    for dep in [seg_file] + list(deps or []):
        if not dep:
            continue
        try:
            if os.path.getmtime(path) < os.path.getmtime(dep):
                return False
        except OSError:
            return False
    return True


def group_asr_lines(entries, lc):
    """把连续 ASR 条目聚成字幕行 —— 只用于【剧本没有台词】的镜头。

    切分口径与 `build_cues` 拆条一致：间隔 > 0.7s / 超 max_cue_chars / 超
    max_duration_s / 上一句已以句末标点收尾且够长，命中任一即切。
    """
    sep = "" if lc.get("wrap") == "char" else " "
    mc = int(lc.get("max_cue_chars") or 40)
    maxdur = float(lc.get("max_duration_s") or 6.0)
    endp = "。！？!?…" if lc.get("wrap") == "char" else ".!?…"
    min_for_punct = 6 if lc.get("wrap") == "char" else 18
    out, cur = [], None
    for a, b, t in entries:
        if cur is None:
            cur = {"start": a, "end": b, "text": t}
            continue
        cand = (cur["text"] + sep + t) if sep else (cur["text"] + t)
        if (a - cur["end"] > 0.7 or len(cand) > mc or (b - cur["start"]) > maxdur
                or (cur["text"][-1:] in endp and len(cur["text"]) >= min_for_punct)):
            out.append(cur)
            cur = {"start": a, "end": b, "text": t}
        else:
            cur["text"], cur["end"] = cand, b
    if cur:
        out.append(cur)
    return [c for c in out if c["end"] > c["start"]]


def asr_fill_segment(cfg, seg, sid, asr_dir, tmp, langcfg, trim=True):
    """为【剧本无台词】的镜头补 ASR 字幕；无语音返回 None。

    背景（2026-10-22 实跑）：H3 会自行在镜头里加话（ep26_sc03「¡Pero si no te hagas!」、
    ep26_sc08「¡Vamos a ver, Nello!」剧本都没有 <d>）。旧实现直接跳过这些段，
    结果是**有声音没字幕**，而且覆盖检查只能一直报警。

    取舍：ASR 文字不可靠（音乐床上常出乱码），所以：
      · 只在剧本确实没有台词时用，**绝不覆盖**剧本原文；
      · source 标 `asr-unscripted`，report 里单独统计，供人工复核；
      · 一旦 ASR 只给出非语音标记（`[Música]`），返回 None。

    ★ 2026-11-10（实测抓到幻觉）：whisper 会在**几乎全程静音**的镜头上编出整段台词。
      实测 海外剧/28 ep01 shot_002：音频 10.05s，能量只有前 0.5s（峰值 2899，其余无），
      而 whisper 给出 `0.00–9.60` 的「La demandante firmó una renuncia total dos veces…」
      —— 剧本里根本没这句，画面里也没有人声。
      ⇒ 补位前必须过声学门槛：字幕窗口的**有声覆盖率**低于 15% 就判为幻觉，不给时间。
      这与 `coverage_gaps` 里对 whisper 假区间的处理同一口径（那里也是 <0.15 丢弃）。
    """
    entries = asr_entries(cfg, seg["file"], asr_dir, sid)
    if not entries:
        return None
    recs = [{"i": i + 1, "text": c["text"], "start": round(c["start"], 3),
             "end": round(c["end"], 3), "source": "asr-unscripted"}
            for i, c in enumerate(group_asr_lines(entries, langcfg))]
    if not recs:
        return None
    full = os.path.join(tmp, sid + "_full.wav")
    if os.path.exists(full):
        kept, dropped = [], 0
        for r in recs:
            frac = window_loud_fraction(full, r["start"], r["end"])
            if frac is not None and frac < 0.15:
                dropped += 1
                continue
            kept.append(r)
        if dropped:
            print("   ⚠ %s ASR 补位丢弃 %d 条「有字无声」的疑似幻觉" % (sid, dropped))
        recs = kept
        if not recs:
            return None
    n_trim = 0
    if trim and os.path.exists(full):
        n_trim = tighten_to_audio(recs, full, langcfg)
    return {"shot_id": sid, "audio_duration": round(entries[-1][1], 3),
            "method": "asr-only", "strategy": "asr-only",
            "src_fingerprint": _src_fingerprint(seg["file"]),
            "trimmed": n_trim, "gap_score": {}, "lines": recs, "problems": []}


# ---------------------------------------------------------------- 声学与非语音识别
# ★ 2026-10-22（实跑排障）：whisper 会把**纯音乐段**输出成 `[Música]` / `[Music]` /
#   `[Applause]` 这类标记。旧实现把它们当作「有语音」，于是覆盖检查整段误报
#   （实测 ep26_sc01 的 srt 只有一条 `[Música] 0.00–6.50`，却被判「6.5s 有语音却无字幕」；
#    ep30 更严重：8 段里 7 段误报）。
#   误报不只是噪声 —— `repair_leading_gaps` 会据此把第一条字幕**前移到段首**，
#   等于为了盖住"音乐"而破坏本来正确的时间轴。所以必须在源头过滤。
_NONSPEECH_RE = re.compile(
    r"^[\s\[\(（【]*\s*(m[uú]sica|music|musique|m[úu]sica de fondo|applause|aplausos|"
    r"risas|laughter|laughs|silencio|silence|inaudible|blank_?audio|noise|static|"
    r"beep|sonido|sfx|suspiro|sigh)\s*[\]\)）】]*[\s.。]*$", re.I)
# 只剩音符/标点的条目（whisper 对纯旋律段常这样输出）
_MUSIC_ONLY_RE = re.compile(r"^[\s♪♫♬\-–—.,!?¡¿·…]+$")


def is_nonspeech(text):
    """该条 ASR 文本是否是【非语音标记】（纯音乐/掌声/静音等）。

    只做"是不是语音"的判断，不做长度门槛 —— `¿Eh?` 这种 2 个字也是真台词。
    """
    t = (text or "").strip()
    if not t:
        return True
    if _NONSPEECH_RE.match(t):
        return True
    return bool(_MUSIC_ONLY_RE.match(t))


_SRT_LINE = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def parse_srt_file(path):
    """解析 SRT → [(start, end, text)]；缺失/损坏返回 []。

    与旧的两个内嵌解析器合并成一处：语言无关、编码容错、保留原始文本。
    """
    try:
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            txt = fh.read().replace("\r", "")
    except OSError:
        return []
    out = []
    for blk in re.split(r"\n\s*\n", txt.strip()):
        L = [x for x in blk.split("\n") if x.strip()]
        if len(L) < 3:
            continue
        m = _SRT_LINE.match(L[1].strip())
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        a = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000.0
        b = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000.0
        out.append((a, b, " ".join(L[2:]).strip()))
    return out


def _src_fingerprint(path):
    """源媒体指纹：size + mtime_ns + 时长。用来判定缓存切片是否仍对应当前素材。

    ★ 为什么 mtime 比较不够（2026-11-10 实测）：
      `asr/shot_001.wav` 的 mtime（22:39）比 `final.mp4`（15:54）**更新**，
      所以「缓存比源旧就重建」这种判据会放行 —— 但两边内容根本不同：
      缓存里的人声在 6.00s，成片里在 4.25s，整条错位 1.75 秒。
      音频时长、帧数完全一样，只有内容不一样，肉眼与元数据都看不出来。
      原因是这份 wav 当初是从别的东西抽的（或者抽完以后成片被原样重写过）。
      ⇒ 只能记「抽的时候源长什么样」，对不上就重抽。指纹放过期文件的概率极低，
        而且重抽本身很便宜（10 秒素材 ~0.2s）。
    """
    try:
        st = os.stat(path)
    except OSError:
        return ""
    return "%d:%d" % (st.st_size, st.st_mtime_ns)


def _asr_cache_fresh(wav, path):
    """asr 切片是否仍对应当前源媒体（指纹一致才算）。缺指纹一律视为过期。

    缺指纹为什么判过期而不是判有效：历史缓存全都没有指纹，
    而本次实测证明「有文件 + mtime 看着合理」恰恰是错的来源。
    宁可多抽一次，也不能让错误的时间轴一路进 ASS、进工程、进送审材料。
    """
    side = wav + ".src"
    if not os.path.isfile(wav) or not os.path.isfile(side):
        return False
    try:
        with open(side, encoding="utf-8") as fh:
            return fh.read().strip() == _src_fingerprint(path)
    except OSError:
        return False


def asr_words(cfg, path, asr_dir=None, tag=None):
    """该段的**词级** ASR 条目 [(start, end, word)]；拿不到返回 []。

    ★ 2026-11-10 新增，用途是替掉「CTC 没配 ⇒ 全部 fallback-estimate」这条死路。
      实测 海外剧/28 ep01：`config.subtitle.json` 的 `tools.aligner` 还是占位符
      （`<ctc-forced-aligner 可执行文件绝对路径…>`），CTC 从来没跑过，
      每段都走 `fallback-estimate`；而 `build_cues` 只对 `fallback-estimate`
      做「等分剩余时长」，于是字幕位置与真实人声毫无关系 —— 这就是用户看到的
      「字幕跟音频没有对齐」，且全程无告警。

      为什么词级时间可信：whisper 的**段级**时间戳在有音乐时会被拉长到整段
      （实测 shot_001 一条 `0.00–9.68`），但**词级**时间戳是逐 token 的，
      同一段能给出 `El 0.35–0.49 / contrato 0.49–2.44 / está 2.44–4.44 / …`，
      与实测人声能量吻合。所以段级不可信、词级可用。

    实现要点：
      · `-sow`（split-on-word）必须开，否则会按 token 切（`contr`/`ato` 两半）；
      · `-ml 1` 每词一条；纯空白/标点条目丢弃；
      · 只抽一次，结果单独存 `<sid>.words.srt`，与段级 `<sid>.srt` 互不覆盖
        （段级那份被覆盖检查与 ASR 补位用着，不能动）。
    """
    wc = cfg["tools"].get("whisper_cli")
    model = cfg["tools"].get("whisper_model")
    if not (wc and model and os.path.exists(wc) and os.path.exists(model)):
        return []
    adir = asr_dir or os.path.dirname(path)
    tag = tag or "asr"
    wav = os.path.join(adir, tag + ".wav")
    out_base = os.path.join(adir, tag + ".words")
    out_srt = out_base + ".srt"
    if not _asr_cache_fresh(wav, path):
        # 音频过期就别用旧词表；让 asr_entries 负责重抽（它会写指纹）
        return []
    if not os.path.exists(out_srt):
        try:
            run([wc, "-m", model, "-f", wav, "-l", cfg["tools"].get("whisper_lang", "zh"),
                 "-sow", "-ml", "1", "-osrt", "-of", out_base, "-np"], check=False,
                timeout=cfg["tools"].get("whisper_timeout_s") or 900)
        except RuntimeError as e:
            print("   ⚠ %s 词级转写失败：%s" % (os.path.basename(out_base), str(e)[:80]))
            return []
    words = []
    for a, b, t in parse_srt_file(out_srt):
        t = (t or "").strip()
        if not t or not re.search(r"\w", t):
            continue
        words.append((round(float(a), 3), round(float(b), 3), t))
    return words


def silence_overlap(recs, wav, frame_s=0.05):
    """字幕「压在静音上」的总时长（秒）；读不出音频返回 0.0。

    ★ 2026-11-10（评分口径缺陷，实测后果很严重）：
      原来档位只用 `coverage_gaps`（有语音却没字幕的时长）打分。而
      `fallback-estimate` 的操作恰恰是「把台词等分铺满整段」—— 铺满当然没有缺口，
      于是它的缺口分恒为 **0，永远是最优**，真对齐的 asr-word（0.6–2.4s 缺口）
      反而输掉。实测 shot_004：`gap_score` 里 wide/tight/tighter 全 0、
      asr-word 2.4 ⇒ 估算档胜出，字幕位置与人声毫无关系。
      ⇒ 必须加上「假覆盖」这一半：字幕亮着但没人在说话的时间也是错。

    单条覆盖率 < 0.25 的直接整条计入（`window_loud_fraction` 已按 p90 归一，
    所以这 0.25 是「基本没声」而非「声音小」）。
    """
    tot = 0.0
    for r in recs:
        a, b = float(r["start"]), float(r["end"])
        if b - a <= 0.05:
            continue
        frac = window_loud_fraction(wav, a, b, frame_s)
        if frac is None:
            continue
        tot += (1.0 - frac) * (b - a)
    return round(tot, 3)


def align_by_words(txts, words, lc, allow_partial=False):
    """用**词级** ASR 时间把台词按序映射成字幕条目；映射不成立返回 None。

    做法（与 `asr_calibrate` 同族，但基准是词而不是段）：
      逐条台词，在剩余词序列里找相似度最高的一段连续词窗口（从当前位置起、
      长度取「台词的词数 ± 40%」），取其首词起点与末词终点。
      任一条台词找不到 >= 0.42 的匹配 ⇒ 整段放弃（返回 None），
      交给别的档位 —— 宁可用段级结果，也不要半对半错。

    时间只取**匹配到的词**的首尾，不做等分、不按字数估 —— 这正是旧实现错的地方。
    最小时长保底与段级一致（0.6s 或 0.28s/发音字），但**不越过下一个词**，
    否则会把字幕拖到静音里。

    ★ 2026-11-10 补：`allow_partial=True` 时，匹配不到的**尾部**台词不参与对齐，
      并把它们原样返回（调用方读 `_unmatched`）—— 用于 shot_006 这种
      「第一句能对上、第二句 whisper 没转出来（Esperame 是人声但模型漏词）」的段。
      为什么不能退化成等分估算：等分给出的时间与人声无关，比"少一条字幕"更坏的
      是"给出一个错的时间还声称对齐成功"。漏的那句会进 problems 让人补，而不是被掩盖。
    """
    if not words or not txts:
        return None
    _punct = re.compile(r"[，。！？；：…—、（）「」《》\s\"'!?.,;:\-¿¡]")

    def norm(s):
        return _punct.sub("", str(s or "")).lower().strip()

    def _nword(t):
        """台词的大致词数。

        ★ 必须用**原始**文本切词，不能先 `norm()` —— `norm` 会把空格一起去掉，
        于是 `"El contrato está cumplido."` 变成 `elcontratoestácumplido`（一个 token），
        词数恒为 1，窗口搜索只能在 1–2 词之间打转，永远匹配不到整句。
        实测后果：首条字幕只覆盖 `El contrato`（0.35–2.44），后半句整段丢失。
        中文没有空格，按字数算；拼音文字按「字母串」个数算（不受标点影响）。
        """
        s = str(t or "")
        latin = re.findall(r"[A-Za-zÀ-ÿ]+", s)
        if latin:
            return max(1, len(latin))
        return max(1, len(norm(s)))

    def window_score(core, i, n):
        cand = norm(" ".join(w[2] for w in words[i:i + n]))
        return text_similarity(core, cand)

    out, j, unmatched = [], 0, []
    for k, t in enumerate(txts):
        core = norm(t)
        if not core:
            return None
        nword = _nword(t)
        # 先求全表最高分，再在「分差 ≤0.12」的窗口里取**起点最早**的一个。
        #   ★ 2026-11-10 实测反例：台词「El contrato está cumplido.」（5 词），
        #   从 `El` 起的 5 词窗口末尾多带一个 `Firmaste.`，相似度被拉低约 0.1；
        #   从 `contrato` 起的 4 词窗口反而整句被包含、分最高 ⇒ 起点落到 0.49，
        #   白丢开头 `El`（0.35–0.49）。差 0.14s 看着不多，但「首词不亮」是观众
        #   第一眼就能感觉到的那种错。容差 0.12 是「一整句里多带/少带一个短词」的
        #   典型分差量级，再大就说明是两个不同窗口，不能让步。
        cands = []
        for i in range(j, len(words)):
            for n in {max(1, nword - 1), nword, nword + 1, max(1, int(nword * 1.4))}:
                if i + n > len(words):
                    continue
                cands.append((window_score(core, i, n), i, n))
        if not cands:
            if allow_partial:
                unmatched = list(txts[k:])
                break
            return None
        best = max(c[0] for c in cands)
        if best < 0.42:
            if allow_partial:
                unmatched = list(txts[k:])
                break
            return None
        bi, bn = min(((i, n) for sc, i, n in cands if sc >= best - 0.12),
                     key=lambda p: (p[0], p[1]))
        a = words[bi][0]
        b = words[bi + bn - 1][1]
        # 最小时长保底：按**语言的字/词单位**算，不能一律用「字符数 × 0.28」。
        #   ★ 2026-11-10 踩到：西语「Firmaste. Quien firma, no tiene derecho.」是 32 个字符、
        #   真实时长约 3.5s，按 0.28×32 = 8.96s 保底 ⇒ 字幕挂到 14.92s，
        #   越过词表末尾（10.0s）三倍多，直接盖住后半段画面。
        #   中文按字（3.5 字/秒 ≈ 0.28s/字）成立，拼音文字必须按**词**算（≈0.30s/词）。
        if (lc or {}).get("wrap") == "char":
            floor_s = 0.28 * len(_punct.sub("", t))
        else:
            floor_s = 0.30 * _nword(t)
        b = max(b, a + max(0.6, floor_s))
        # 保底不许越过该段音频末尾（词表最后一项就是它），否则字幕会拖到静音/下一段
        b = min(b, max(words[-1][1], a + 0.6))
        out.append({"text": t, "start": round(a, 3), "end": round(b, 3),
                    "source": "whisper-word"})
        j = bi + bn
    if not out:
        return None
    # 顺序单调 + 不越过下一条起点（越过就砍到下一条起点，砍没了才放弃）
    for k, r in enumerate(out):
        if k:
            r["start"] = max(r["start"], out[k - 1]["end"])
        nxt = out[k + 1]["start"] if k + 1 < len(out) else None
        if nxt is not None and r["end"] > nxt:
            r["end"] = nxt
        if r["end"] - r["start"] <= 0.02:
            return None
    if unmatched:
        # 尾部没匹配上的台词挂在这份返回里，调用方负责写进 problems（不许静默丢）
        for r in out[:1]:
            r["_unmatched"] = unmatched
    return out


def snap_to_voiced(recs, wav, lc, head_keep=0.04, tail_keep=0.08):
    """把每条字幕的首尾**贴到真实有声区间**上；返回调整条数。

    ★ 2026-11-10（第三次修）：词级 whisper 的边界在「人声分段 + 长静音」的素材上仍会偏。
      实测 海外剧/28 ep01：
        · shot_003 第二句词级给 4.58–6.53，而该镜人声实际在 6.50–7.40（偏 2 秒）；
        · shot_005「Es la diseñadora del año.」词级把 `diseñadora` 拉成 0.6–2.70，
          真人是 0.10–0.70 一句、2.70–3.90 一句，中间两秒空。
      为什么会这样：whisper 的时间是按 token 均摊回声学段的，遇到长静音会把某个 token
      拉长去盖住静音。文本对不对是一回事，边界对不对是另一回事。

      修法（只动边界，不动文本、不动顺序、不做等分）：
        ① 取该段的声学有声区间（`loud_intervals`，同一套阈值）；
        ② 与该字幕区间**有交叠**的区间 → 首尾取这些区间的并集端点；
        ③ 一条都不交叠 → 找第一个起点落在 [start-0.3, end+2.0] 的区间接上去；
        ④ 仍找不到 → 原样保留（宁可不动，也不要凭空挪）。
      ②的作用是把「跨过静音的两段人声」正确地一起罩住；③的作用是把整句挪到
      真正有声音的位置。前后各留 40/80ms 让字幕不要卡着声波起止闪。

    护栏：调整后若短于 `min_duration_s` 或短于「念得完」所需，就**放弃调整** ——
    与 `tighten_to_audio` 同一原则：宁可多停留，不产出念不完的字幕。
    """
    loud = loud_intervals(wav)
    if not loud:
        return 0
    changed = 0
    safe_cps = max(8.0, float((lc or {}).get("cps_hard_max", 12.0)) * 0.85)
    prev_end = 0.0
    for i, r in enumerate(recs):
        a, b = float(r["start"]), float(r["end"])
        hit = [(x, y) for (x, y) in loud if y > a + 0.02 and x < b - 0.02]
        if hit:
            na = min(x for x, _ in hit)
            nb = max(y for _, y in hit)
        else:
            nxt = [iv for iv in loud if a - 0.3 <= iv[0] <= b + 2.0]
            if not nxt:
                prev_end = max(prev_end, b)
                continue
            na, nb = nxt[0][0], nxt[0][1]
        na = max(0.0, na - head_keep)
        nb = nb + tail_keep
        # 不许回退越过上一条（顺序约束）——动边界不能把顺序搞乱
        na = max(na, prev_end)
        # ★ 也不许盖住**下一条**已经校验过的起点：shot_004 现场，
        #   第一句贴到 3.58–5.12，而第二句「No.」贴着 4.0–4.6（人声确实在 4.0），
        #   不管顺序就会重叠，剪映里两条字幕同一时刻抢同一行，看起来像花屏。
        #   这里把上一条的尾巴收到下一条起点，收完不足最小时长就整条放弃调整。
        nxt_floor = None
        if i + 1 < len(recs):
            nxt_floor = float(recs[i + 1]["start"])
        if nxt_floor is not None and nb > nxt_floor:
            nb = max(na, nxt_floor)
        if nb - na < float((lc or {}).get("min_duration_s", 0.5)):
            prev_end = max(prev_end, b)
            continue
        if nb - na < spoken_len(r.get("text") or "") / safe_cps:
            prev_end = max(prev_end, b)
            continue
        if abs(na - a) > 0.03 or abs(nb - b) > 0.03:
            r["start"], r["end"] = round(na, 3), round(nb, 3)
            r["snapped"] = True
            changed += 1
        prev_end = float(r["end"])
    return changed


def asr_entries(cfg, path, asr_dir=None, tag=None):
    """该段的 ASR 条目 [(start, end, text)]，**已剔除非语音标记**。

    语音检测的正源仍是 whisper（它只会为真的词给出条目），但必须过 `is_nonspeech`：
    音乐段的 `[Música]` 一旦混进来，覆盖检查与段首修复都会做错事。

    ★ 缓存口径（2026-11-10 第二次修）：判据从「文件存在 / mtime 更新」改成
      **源媒体指纹一致**。理由见 `_src_fingerprint` 的说明 —— mtime 更新也可能内容错位，
      而错位的音频会让 whisper 转写出错误时间、让覆盖检查把对齐好的判成「压静音」。
    """
    wc = cfg["tools"].get("whisper_cli")
    model = cfg["tools"].get("whisper_model")
    if not (wc and model and os.path.exists(wc) and os.path.exists(model)):
        return []
    base = os.path.join(asr_dir or os.path.dirname(path), tag or "asr")
    srt, wav = base + ".srt", base + ".wav"
    # whisper-cli 只接受 16k 单声道 WAV；直接喂 mp4 会静默失败（踩过的坑）
    if not _asr_cache_fresh(wav, path):
        run([cfg["tools"]["ffmpeg"], "-hide_banner", "-nostats", "-v", "error", "-y",
             "-i", path, "-vn", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", wav])
        with open(wav + ".src", "w", encoding="utf-8") as fh:
            fh.write(_src_fingerprint(path))
        if os.path.exists(srt):
            # 音频换了，旧 srt 的时间全部作废 —— 留着比没有更危险
            try:
                os.remove(srt)
            except OSError:
                pass
    if not os.path.exists(srt):
        try:
            run([wc, "-m", model, "-f", wav, "-l", cfg["tools"].get("whisper_lang", "zh"),
                 "-osrt", "-of", base, "-np"], check=False,
                timeout=cfg["tools"].get("whisper_timeout_s") or 900)
        except RuntimeError as e:
            # 转写失败/超时不该拖死整条管线：返回空，覆盖检查退回声学口径
            print("   ⚠ %s whisper 转写失败：%s" % (os.path.basename(base), str(e)[:80]))
            return []
    return [(a, b, t) for a, b, t in parse_srt_file(srt) if not is_nonspeech(t)]


def _frame_rms(wav, frame_s=0.02):
    """16k 单声道 wav → (每帧 RMS 列表, 帧长秒)；失败返回 (None, frame_s)。"""
    import array
    import wave
    try:
        with wave.open(str(wav), "rb") as w:
            sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
            if sw != 2:
                return None, frame_s
            raw = w.readframes(w.getnframes())
    except Exception:                                                       # noqa: BLE001
        return None, frame_s
    a = array.array("h")
    a.frombytes(raw)
    if ch == 2:
        a = a[0::2]
    per = max(1, int(sr * frame_s))
    fr = []
    for i in range(0, len(a), per):
        seg = a[i:i + per]
        if not seg:
            break
        s = 0.0
        for x in seg:
            s += float(x) * float(x)
        fr.append(math.sqrt(s / len(seg)))
    return (fr or None), frame_s


def _loud_threshold(fr, rel_frac=0.30, abs_floor=600.0):
    """有声判定的 RMS 阈值：p90 的相对比例与绝对下限取大者。

    ★ 2026-11-10：p90 == 0 时不能直接判「无法判断」。
      p90 = 0 的含义是「90% 的帧完全静音」，这在**短镜头 / 只有片头有声音**的段里
      很常见（实测 海外剧/28 ep01 shot_002：前 0.5s 有声、其余 9.5s 全静音，
      p90 恰为 0）。旧实现此时返回 None，`window_loud_fraction` 也跟着返回 None，
      于是所有「这窗口是不是静音」的判据全部失效 —— 包括 ASR 补位的幻觉拦截，
      结果 whisper 在静音上编出的整段台词照样进字幕。
      ⇒ p90 为 0 时改用**峰值**作参照；连峰值都是 0 才是真的全静音（返回 None）。
    """
    vals = sorted(fr)
    p90 = vals[min(len(vals) - 1, int(len(vals) * 0.9))]
    if p90 <= 0:
        peak = vals[-1] if vals else 0.0
        if peak <= 0:
            return None                     # 全段数字静音，没有任何可判依据
        return max(abs_floor, rel_frac * peak)
    return max(abs_floor, rel_frac * p90)


def window_loud_fraction(wav, a, b, frame_s=0.05):
    """[a, b) 窗口内「有声帧」占比（0~1）；读不出音频返回 None。

    用途（★ 2026-10-22 实跑教训）：whisper 切片对**短镜头**常给出一条
    跨满整段的时间（实测 ep26_sc02：`00:00:00,000 --> 00:00:06,240`，
    而真实台词在 3.3–6.3s，前 3 秒 RMS 只有 50–230，是环境底噪）。
    旧代码据此认为"0s 起就有语音"，`repair_leading_gaps` 于是把首条字幕
    前移到 0.00 —— 字幕凭空亮了 3 秒。这里用**声学能量**复核，
    静音窗口不许算成"有语音"。
    """
    fr, fs = _frame_rms(wav, frame_s)
    if not fr:
        return None
    thr = _loud_threshold(fr, abs_floor=max(600.0, 0.02 * max(fr)))
    if thr is None:
        return None
    i0 = max(0, int(a / fs))
    i1 = min(len(fr), max(i0 + 1, int(round(b / fs))))
    seg = fr[i0:i1]
    if not seg:
        return None
    return sum(1 for v in seg if v >= thr) / float(len(seg))


def loud_intervals(wav, frame_s=0.02, rel_frac=0.30, abs_floor=600.0,
                   min_dur=0.20, merge_gap=0.15):
    """音频能量给出的「真实有声区间」；解析失败返回 None。

    纯标准库（wave + array）实现，20ms 帧 RMS，阈值取 p90 的相对比例 ——
    环境噪声大的素材也能自适应。用途是**收紧字幕首尾**（对齐到真实发声），
    不用它判断"有没有人说话"（音乐也会响，同样是高能量）。
    移植自 vidpure 的 `loud_intervals`（同一套口径，已在那边跑通）。
    """
    fr, fs = _frame_rms(wav, frame_s)
    if not fr:
        return None
    thr = _loud_threshold(fr, rel_frac, abs_floor)
    if thr is None or not any(v >= thr for v in fr):
        return None
    regs, i, n = [], 0, len(fr)
    while i < n:
        if fr[i] < thr:
            i += 1
            continue
        j, k, gap = i, i, 0
        while k < n:
            if fr[k] >= thr:
                j, gap = k, 0
            else:
                gap += 1
                if gap > merge_gap / fs:
                    break
            k += 1
        a0, b0 = i * fs, (j + 1) * fs
        if b0 - a0 >= min_dur:
            regs.append((round(a0, 3), round(b0, 3)))
        i = k + 1
    return regs or None


def tighten_to_audio(recs, wav, lc, head_keep=0.06, tail_keep=0.06, min_loud=0.30):
    """把每条字幕收紧到其覆盖范围内的真实有声区间（去头尾静音）。

    护栏（移植 vidpure 的实测教训）：收紧后若短于「发音字数所需时长」则**整条放弃收紧**
    —— 宁可多停留，绝不产出念不完的字幕。
    """
    loud = loud_intervals(wav)
    if not loud:
        return 0
    safe_cps = max(12.0, float(lc.get("cps_hard_max", 12.0)) * 0.85)
    changed = 0
    for r in recs:
        seg = [(a, b) for (a, b) in loud if b > r["start"] + 0.02 and a < r["end"] - 0.02]
        if not seg:
            continue
        a = max(r["start"], min(x[0] for x in seg)) - head_keep
        b = min(r["end"], max(x[1] for x in seg)) + tail_keep
        if b - a < min_loud:
            continue
        spoken = spoken_len(r.get("text") or "")
        if b - a < spoken / safe_cps:
            continue
        if a > r["start"] + 0.05 or b < r["end"] - 0.05:
            r["start"], r["end"] = round(max(0.0, a), 3), round(b, 3)
            r["trimmed"] = True
            changed += 1
    return changed


def speech_regions(cfg, path, asr_dir=None, tag=None, noise_db=-35, min_sil=0.25):
    """取该段的【真实语音区间】。

    优先用 whisper-cli 的转写结果 —— 它只输出识别到「词」的地方，
    背景音乐/音效不会被算进去。silencedetect 会把音乐当语音（踩过的坑：
    seg14 前 9.66 秒 whisper 什么都没听到，silencedetect 却判为"有语音"）。
    没有 whisper-cli 时退回 silencedetect。

    ★ 2026-10-22：whisper 输出的 `[Música]` 这类**非语音标记**已在 `asr_entries`
      里剔除 —— 旧实现把它们当语音，导致覆盖检查大面积误报、并把首条字幕
      前移到段首（实测 ep26/ep30）。
    """
    regs = [(a, b) for a, b, _t in asr_entries(cfg, path, asr_dir, tag)]
    if regs:
        return regs
    # 退回纯声学
    rc, out = run([cfg["tools"]["ffmpeg"], "-hide_banner", "-nostats", "-i", path,
                   "-vn", "-af", "silencedetect=noise=%ddB:d=%s" % (noise_db, min_sil),
                   "-f", "null", "NUL"], check=False)
    sil, cur = [], None
    for ln in out.splitlines():
        m = re.search(r"silence_start:\s*([\d.]+)", ln)
        if m:
            cur = float(m.group(1))
            continue
        m = re.search(r"silence_end:\s*([\d.]+)", ln)
        if m and cur is not None:
            sil.append((cur, float(m.group(1))))
            cur = None
    dur = audio_duration(cfg["tools"]["ffprobe"], path)
    if cur is not None:
        sil.append((cur, dur))
    sil.sort()
    reg, t = [], 0.0
    for a, b in sil:
        if a - t > 0.12:
            reg.append((t, a))
        t = max(t, b)
    if dur - t > 0.12:
        reg.append((t, dur))
    return reg


def coverage_gaps(cfg, path, subs, asr_dir=None, tag=None, min_gap=0.6, wav=None):
    """找出【有语音但没有任何字幕覆盖】的区间 —— 这是"字幕没对齐/漏台词"的机器判据。
    实测：这个判据能抓住 seg05/seg06 首句被推后 3.7/4.2 秒的问题（语速判据抓不住）。

    ★ 2026-10-22：候选缺口再过一道**声学复核**（`wav` 给了才做）。原因见
      `window_loud_fraction` 的说明 —— whisper 对短镜头会给一条跨满整段的时间，
      这是"假语音"，据此修首条字幕会把字幕拉到没人说话的静音上。
    """
    gaps = []
    for (a, b) in speech_regions(cfg, path, asr_dir, tag):
        covered = [(max(a, s), min(b, e)) for s, e in subs if e > a and s < b]
        covered = [c for c in covered if c[1] > c[0]]
        cand = []
        if not covered:
            if b - a >= min_gap:
                cand.append((a, b))
        else:
            covered.sort()
            cur = a
            for c0, c1 in covered:
                if c0 - cur >= min_gap:
                    cand.append((cur, c0))
                cur = max(cur, c1)
            if b - cur >= min_gap:
                cand.append((cur, b))
        for a0, b0 in cand:
            if wav:
                frac = window_loud_fraction(wav, a0, b0)
                if frac is not None and frac < 0.15:
                    continue                     # 该窗口基本无声 ⇒ 不是缺口，是 whisper 的假区间
            gaps.append((round(a0, 2), round(b0, 2), round(b0 - a0, 2)))
    return gaps


def collect_gaps(segs, cues, seg_offsets, cfg, asr_dir):
    """逐段跑声学覆盖检查，返回缺口列表（字幕时间已按段起点换算成"集内相对时间"）。"""
    gaps = []
    for seg in segs:
        sid = seg["shot_id"]
        base = seg_offsets.get(sid, 0.0)
        rel_subs = [(c["start"] - base, c["end"] - base) for c in cues if c["shot_id"] == sid]
        wav = os.path.join(asr_dir, sid + ".wav")
        for (a, b, d) in coverage_gaps(cfg, seg["file"], rel_subs, asr_dir, sid,
                                       min_gap=0.6, wav=wav if os.path.isfile(wav) else None):
            gaps.append({"shot_id": sid, "from": a, "to": b, "seconds": d})
    return gaps


def repair_leading_gaps(segs, cues, seg_offsets, gaps, warn, lead=0.06):
    """★ 段首覆盖修复：把「段首有语音却无字幕」的区间并入该段第一条字幕。

    实测依据（2026-09-20；真值取自 whisper-cli `-ml 1` 的**逐字**时间戳）：

      | 段          | 首句真实起点 | CTC 对齐起点 | 被推后 |
      |-------------|--------------|--------------|--------|
      | ep06_seg01  | 0.00         | 1.84         | +1.84s |
      | ep06_seg02  | 0.00         | 5.44         | +5.44s |
      | ep06_seg07  | 0.00         | 3.96         | +3.96s |

    成因：CTC 的搜索窗口是 [cursor, 段尾]；对**第一句**来说窗口远长于台词真实跨度，
    模型会自行挑一段子区间。后续各行因顺序约束把窗口收紧了，所以不受影响 ——
    这解释了为什么"只有段首错、后面都对"。
    ⇒ 观众看到的现象：前几秒**听得到人声却没有字幕**。
    这里**只外扩时间**（不改文本、不改行序），把段首人声盖住。
    """
    targets = {}
    for g in gaps:
        if g["from"] <= 0.05 and g["seconds"] >= 0.3:
            targets[g["shot_id"]] = min(targets.get(g["shot_id"], 9e9), g["from"])
    if not targets:
        return 0
    fixed = []
    for sid, gap_from in targets.items():
        base = seg_offsets.get(sid, 0.0)
        seg_cues = [c for c in cues if c["shot_id"] == sid]
        if not seg_cues:
            continue
        first = min(seg_cues, key=lambda c: c["start"])
        want = round(max(base + max(gap_from - lead, 0.0), 0.0), 3)
        if first["start"] > want:
            first["start"] = want
            fixed.append(sid)
    if not fixed:
        return 0
    # 前移后必须重新保证单调不重叠、且不短于可读下限
    cues.sort(key=lambda c: c["start"])
    for i, c in enumerate(cues):
        nxt = cues[i + 1]["start"] if i + 1 < len(cues) else None
        if nxt is not None and c["end"] > nxt:
            c["end"] = nxt
        if c["end"] - c["start"] < 0.4:
            c["end"] = round(c["start"] + 0.4, 3)
    warn.append("段首覆盖修复：%d 段的第一条字幕已前移盖住段首人声（%s）"
                % (len(fixed), ", ".join(fixed)))
    return len(fixed)


def parse_align(path):
    """解析对齐输出：每行 `start-end: 字`，返回 [(start, end, char), ...]。"""
    ent = []
    with open(path, encoding="utf-8") as f:
        for ln in f:
            m = re.match(r"([\d.]+)-([\d.]+):\s?(.*)$", ln.rstrip("\n"))
            if m:
                ent.append((float(m.group(1)), float(m.group(2)), m.group(3)))
    return ent


# ---------------------------------------------------------------- 阶段 2：字幕条目

def split_two_lines(text, cfg):
    """把一条台词折成 ≤max_lines 行，每行 ≤max_line_chars；中文按字符、西语按单词。

    断行策略（实测踩过的坑）：
      * 中文没有空格，任何"按字符硬切"都可能把词切开（如「癌/症」）⇒ 优先在标点处断
      * 标点断点若略微超出行宽，允许 line_tolerance_chars 的容差 —— 宁可行长一点，
        也不要把词切开（实测：允许 +3 字容差后，「…怎么可能得癌症！」能整段落在一行）
    """
    # 缺 max_line_chars 不崩：退回 max_cue_chars（两者在标准配置里本就接近）。
    #   ★ 2026-11-10：外部 SRT 导入路径（`load_cues_from_srt`）会构造精简的语言配置，
    #   旧实现在这里 `KeyError: max_line_chars` 直接崩 —— 一个可推导的字段缺省，
    #   不值得让整集字幕不出来。
    ml = int(cfg.get("max_line_chars") or cfg.get("max_cue_chars") or 40)
    tol = cfg.get("line_tolerance_chars", 0)
    n = len(text)
    if n <= ml:
        return [text]
    if cfg.get("wrap") == "word":
        # 西语：必须按单词边界，绝不切断单词
        # ★ 2026-10-22：旧实现「第一个满足 ≤行宽的切点」就返回，实测会把
        #   `Mintió para salvar mi empresa.` 折成 `Mintió` / `para salvar mi empresa.`，
        #   `Eran las once y veinte. Llovía.` 折成 `Eran las` / `once y veinte. Llovía.`
        #   —— 语义单元被切碎。改为在所有可行切点里挑**最均衡**的一条；
        #   紧跟标点的切点给一点奖励（阅读上更自然）。
        words = text.split(" ")
        SENT_END = ".!?…"
        SOFT = ",;:"
        best = None
        for k in range(1, len(words)):
            left, right = " ".join(words[:k]), " ".join(words[k:])
            if len(left) > ml or len(right) > ml:
                continue
            # 断点优先级（Netflix 口径：先句末、再分句、最后才按长度均衡）
            if left[-1:] in SENT_END:
                tier = 0
            elif left[-1:] in SOFT:
                tier = 1
            else:
                tier = 2
            score = tier * 100 + abs(len(left) - len(right))
            if right[:1] in cfg.get("forbid_line_start", ""):
                score += 60                      # 别把逗号/句点甩到下一行行首
            if best is None or score < best[0]:
                best = (score, left, right)
        if best:
            return [best[1], best[2]]
        # 单行怎么切都会超宽：仍取最均衡的，交给字号/容差兜底
        best_k, best_w = 1, None
        for k in range(1, len(words)):
            w = max(len(" ".join(words[:k])), len(" ".join(words[k:])))
            if best_w is None or w < best_w:
                best_k, best_w = k, w
        return [" ".join(words[:best_k]), " ".join(words[best_k:])]
    # 中文：优先在标点处断（允许容差），取离中点最近者
    punct = cfg.get("break_punct", "")
    mid = n // 2
    best = None
    for i in range(1, n):
        if text[i - 1] in punct:
            if max(i, n - i) <= ml + tol:
                score = abs(i - mid)
                if best is None or score < best[0]:
                    best = (score, i)
    if best:
        return [text[:best[1]], text[best[1]:]]
    # 兜底：在容差范围内取最接近中点处硬切（仍可能切词，但没有标点可用）
    cut = min(ml + tol, n - 1)
    return [text[:cut], text[cut:]]


def split_long_cue(text, cfg):
    """整句超过 max_cue_chars 时拆成多条（一条字幕最多两行）。

    ★ 2026-11-07 重写（西语实跑事故）：旧实现逐字符累加到 mc 就断，
      `. . . el hombro izquierdo tiembla.` 被切成 `...izquierdo t` / `iembla.`
      —— 单词从中间断掉，成片字幕少一个字母。
      现在分两种口径：
        · wrap=word（西语/英语）：只在**空格**处切，且优先挑「紧跟标点的切点」，
          让 `Labios azules, uñas blancas,` / `y el hombro izquierdo tiembla.`
          这样语义完整的形状出现，而不是把名词和动词拆开；
        · wrap=char（中文）：保持原样，按标点断。
    """
    mc = int(cfg["max_cue_chars"])
    if len(text) <= mc:
        return [text]
    punct = cfg.get("break_punct", "")
    if cfg.get("wrap") != "word":
        chunks, cur = [], ""
        for ch in text:
            cur += ch
            if len(cur) >= mc or (ch in punct and len(cur) >= mc * 0.55):
                chunks.append(cur)
                cur = ""
        if cur:
            if chunks and len(cur) < 6:
                chunks[-1] += cur
            else:
                chunks.append(cur)
        return chunks

    # ---- 西语/英语：只在词边界切 ----
    chunks, rest = [], text.strip()
    while len(rest) > mc:
        cands = []          # (优先级, 距理想长度的偏差, 切点)
        for i, ch in enumerate(rest):
            if ch != " ":
                continue
            left = rest[:i].rstrip()
            if not (mc * 0.45 <= len(left) <= mc):
                continue
            tier = 0 if left[-1:] in ".!?…" else (1 if left[-1:] in ",;:" else 2)
            # 均衡优先：左右两段长度越接近越自然（左 29 / 右 25 好过 左 45 / 右 9）
            cands.append((tier, abs(len(left) - (len(rest) - i - 1)), i))
        if not cands:
            sp = rest.rfind(" ", 0, mc)
            if sp <= 0:
                break
            chunks.append(rest[:sp].rstrip())
            rest = rest[sp + 1:].lstrip()
            continue
        _, _, cut = min(cands)
        chunks.append(rest[:cut].rstrip())
        rest = rest[cut + 1:].lstrip()
    if rest:
        chunks.append(rest)
    # 最后一片太短就往回并（避免单蹦一个词）
    if len(chunks) >= 2 and len(chunks[-1]) < 6:
        chunks[-2] = (chunks[-2] + " " + chunks[-1]).strip()
        chunks.pop()
    return chunks


def load_cues_from_srt(path, cfg, segs, offset_s=0.0):
    """把外部 SRT 读成 cues（整集绝对时间，**镜头轴**）。

    为什么需要它：本仓库的自动对齐要过 whisper + CTC 两道，遇到「整段一条时间戳」
    或底噪被当人声时，台词会整条挂到静音上（实测 海外剧/28 ep01：第一句标 0.35s，
    而人声 4.25s 才出现）。这时最省事、质量最稳的做法是**让剪映识别字幕**：
    剪映的 ASR 对带 BGM 的对白明显更稳，识别完在剪映里「导出字幕」得到 SRT。

    轴的处理（必须显式声明，不能猜）：
      剪映导出的 SRT 起点是**工程/成片轴**（前面可能压着封面片头），
      而 cues 的语义是**镜头轴**（第一段画面 = 0）。所以要把片头减回去。
      `offset_s` 就是这段片头：由调用方用 `cover_lead_seconds()` 算好传进来，
      不在这里猜 —— 猜错就是「整体早/晚 0.8 秒」这种最难查的错。

    返回 (cues, 说明列表, 镜头总长秒)。文本为空的、纯音乐标记的条目直接丢弃（沿用 `is_nonspeech`）。

    ★ 调用方传进来的必须是**完整**的语言配置（`cfg["languages"][lang]`），
      不能只给 `{"wrap": "word"}` —— `split_two_lines` 要读 `max_line_chars`，
      缺了会 `KeyError` 而不是给个默认值。缺字段就补默认，比崩掉合理。
    """
    lc = dict(cfg["languages"][cfg["default_language"]])
    lc.setdefault("max_line_chars", int(lc.get("max_cue_chars") or 40))
    lc.setdefault("max_lines", 2)
    lc.setdefault("line_tolerance_chars", 0)
    lc.setdefault("wrap", "word")
    lc.setdefault("min_duration_s", 0.5)
    recs = parse_srt_file(path)
    notes = []
    if not recs:
        return [], ["SRT 里没读到任何字幕块：%s" % path], 0.0

    # 段起点表（用于把每条字幕归属到镜头，覆盖检查与证据板要它）
    bounds, t = [], 0.0
    for seg in segs:
        d = media_duration(cfg["tools"]["ffprobe"], seg["file"])
        if d <= 0:
            d = ffprobe_frames(cfg["tools"]["ffprobe"], seg["file"]) / 24.0
        bounds.append((seg["shot_id"], t, t + d))
        t += d
    total_seg = t

    cues, dropped = [], 0
    for a, b, txt in recs:
        txt = (txt or "").strip()
        if not txt or is_nonspeech(txt):
            dropped += 1
            continue
        st = max(0.0, float(a) - float(offset_s))
        en = max(st, float(b) - float(offset_s))
        if en - st <= 0.05:
            dropped += 1
            continue
        sid = ""
        for _sid, s0, s1 in bounds:
            if s0 - 0.05 <= st < s1:
                sid = _sid
                break
        if not sid and bounds:
            sid = bounds[-1][0]
        cues.append({"shot_id": sid, "start": round(st, 3), "end": round(en, 3),
                     "text": txt, "lines": split_two_lines(txt, lc),
                     "source": "srt"})

    cues.sort(key=lambda c: c["start"])
    notes.append("外部 SRT：%d 块 → %d 条字幕（丢弃空/纯音乐 %d 条），"
                 "轴=工程轴减 %.2fs 片头" % (len(recs), len(cues), dropped, offset_s))
    over = [c for c in cues if c["end"] > total_seg + 0.5]
    if over:
        notes.append("%d 条字幕超出镜头总长 %.2fs（例 %.2f–%.2f），"
                     "多半是 SRT 轴给错了：工程的片头没减" %
                     (len(over), total_seg, over[0]["start"], over[0]["end"]))
    return cues, notes, total_seg


def build_cues(ws, ep, cfg, segs, lines, subs_dir):
    """产出该集全部字幕条目（时间已换算成【整集绝对时间】）。"""
    lang = cfg["default_language"]
    lc = cfg["languages"][lang]
    t0 = 0.0
    cues = []
    warn = []
    cps_hard, cps_soft = [], []
    seg_offsets = {}
    for seg in segs:
        sid = seg["shot_id"]
        # ★ 2026-11-10 修：段起点与游标推进**必须在任何 continue 之前**完成。
        #   旧实现把 `t0 += _d` 放在段末，而「本段没有台词/没有对齐产物」时会
        #   `continue` 提前跳下一段 ⇒ 该段时长从未计入 ⇒ **其后所有字幕整体提前**。
        #   实测 海外剧/28 ep01：shot_002 无对白（10.125s）被跳过，此后每条字幕
        #   早 10.125 秒；而 ASS 与剪映工程都照旧「生成成功」，只有肉眼看得出来。
        #   这是既有 bug（不是剪映工程引入的）：ASS 烧录同样错，只是没人逐帧比对。
        _d = media_duration(cfg["tools"]["ffprobe"], seg["file"])
        if _d <= 0:
            _d = ffprobe_frames(cfg["tools"]["ffprobe"], seg["file"]) / 24.0
            warn.append("%s 读不到实际时长，按 24fps 帧数估算（%.2fs）" % (sid, _d))
        seg_start = t0                 # 本段在整集里的起点（后面换算字幕绝对时间用）
        seg_offsets[sid] = seg_start   # 覆盖检查要用同口径
        t0 = seg_start + _d            # 无条件推进 —— 有没有台词都要占这 10 秒
        ap = os.path.join(subs_dir, "align", sid + ".json")
        if not os.path.exists(ap):
            # ★ 2026-10-22：剧本本来就没有台词的段（H3 也没在里头说话）不该报
            #   「没有对齐结果」—— 那是正常状态。旧实现每集刷 4–7 行假告警，
            #   把真正的「对齐失败」淹掉了。
            if not (lines.get(sid) or []):
                continue
            warn.append("%s 没有对齐结果（先跑 --stage align）" % sid)
            continue
        rec = load_json(ap)
        # ★ 相邻台词连续性约束（2026-09-20 追加，实测依据见下）
        #   现象：CTC 有明确的【起点偏晚】倾向 —— 真值 0.00 被放到 1.84（ep06_seg01）、
        #         真值 0.00 被放到 5.44（ep06_seg02）、真值 3.0 被放到 5.76（ep06_seg06）、
        #         真值 5.68 被放到 7.86（ep10_seg05 第 2 句）。
        #   规律：本剧**同一段内相邻台词基本首尾相接**，实测间隔仅 0～0.2 秒 ——
        #         ep06_seg01 0-6.72 / 6.72-11.52；ep06_seg02 0-8.24 / 8.44-11.68；
        #         ep06_seg05 0-2.6 / 2.6-7.0 / 7.0-9.4；ep10_seg05 四句全连续。
        #   ⇒ 若本句起点落后上一句终点 **不超过 2.5 秒**，判定为「CTC 起点漂移」，
        #     把起点拉回上一句终点（只改起点，不动终点 ⇒ 只增覆盖、不减信息）。
        #   为什么不无条件拉：间隔 > 2.5s 说明中间是**剧本外语音**（音乐/他人插话），
        #     硬拉会把上一句的字幕盖到无关音频上 —— 实测 ep09_seg05 间隔 5.4s 即属此类。
        _prev_end = None
        for it in rec.get("lines", []):
            if _prev_end is not None:
                _gap = float(it["start"]) - _prev_end
                # ★ 2026-11-10：这条约束**只用于 CTC 档**。
                #   它的由来是「CTC 有起点偏晚倾向」（真值 0.00 被放到 1.84 之类），
                #   而 CTC 恰好没有可靠的声学边界。ASR 档（asr-word / asr-whisper）
                #   的时间来自实测声学，并且已经过 `snap_to_voiced` 贴过边界 ——
                #   再拉平就是把对的改成错的。实测 海外剧/28 ep01：
                #   shot_003 第二句 asr-word 给 6.48–7.58（人声就在 6.5–7.4），
                #   被这条规则拉到 4.16 起，字幕亮了 3.4 秒却只有 1 秒有声。
                _acoustic = str(rec.get("method") or "").startswith("asr-")
                if not _acoustic and 0.05 < _gap <= 2.5:
                    it["start"] = round(_prev_end, 3)
                    it["pulled_back"] = True
            _prev_end = float(it["end"])
        for it in rec.get("lines", []):
            t = it["text"]
            st, en = float(it["start"]), float(it["end"])
            if en <= st:
                en = st + lc["min_duration_s"]
            # ★ 语速合理性检查（对齐是否可信的机器判据）
            #   中文正常说话 3~5.5 字/秒；若某条对齐出 "8 字/秒"，那不是语速快，是【对齐错了】
            dur = en - st
            if dur > 0.05:
                cps = spoken_len(t) / dur          # ← 只算发音的字，不含标点
                lo, hi = lc.get("cps_ok", [0, 999])
                hard = lc.get("cps_hard_max", 999)
                imposs = lc.get("cps_impossible", hard * 1.7)
                crec = {"shot_id": sid, "text": t[:20], "dur": round(dur, 2),
                        "spoken": spoken_len(t), "cps": round(cps, 2),
                        "source": it.get("source", "")}
                if cps > imposs:
                    # ⚠️ 这里**只告警不致命**：此刻用的是【对齐原始记录】的时长，
                    #    而段首修复会把第一条字幕的起点前移（实测 ep06_seg06 原始 0.76s
                    #    → 修复后 3.94s，18.4 字/秒 是假象）。
                    #    真正的「生理上限」判定放在【最终字幕】上（见本函数末尾）。
                    cps_soft.append(crec)
                    warn.append("★ %s 「%s」对齐原始时长仅 %.2fs（%.1f 字/秒）——"
                                "若修复后仍如此则判定错位，见末尾的最终判定"
                                % (sid, t[:14], dur, cps))
                elif cps > hard:
                    # ★ 2026-09-20 修正：这条以前是【致命】断言，已被实测推翻。
                    #   证据：ep06_seg05 第 3 句 30 字 / 2.32s = 12.9 字/秒，whisper 独立转写
                    #   证实音频确实是这个语速（AI 配音把长台词压进短片长）。语速快是内容属性，
                    #   不是对齐错位的证据 ⇒ 降为告警，只有超过生理上限才算错位。
                    cps_soft.append(crec)
                    warn.append("⚠ %s 「%s」语速 %.1f 字/秒（%d 发音字 / %.2fs）很快 —— 已核对为真实语速则无需处理"
                                % (sid, t[:14], cps, spoken_len(t), dur))
                elif cps > hi:
                    cps_soft.append(crec)
                    warn.append("  %s 「%s」语速 %.1f 字/秒 高于常规上限 %.1f —— 多为字幕停留含停顿"
                                % (sid, t[:14], cps, hi))
                elif cps < lo:
                    # ★ 2026-10-22：语速**偏慢不是缺陷**。字幕的停留时间天然包含前后停顿
                    #   （一句 23 字的台词在 6.2s 里说完只剩 3.7 字/秒，实属正常）。
                    #   旧实现对每条都报 ⚠，实测 ep12/ep26/ep29/ep30 每段刷 3–7 行，
                    #   把真正的「有语音无字幕」淹掉了。这里只计数，不逐条报警。
                    crec["kind"] = "slow"
                    cps_soft.append(crec)
            # 整句过长 → 拆多条，时间按字数比例分配
            parts = split_long_cue(t, lc)
            total_c = sum(len(p) for p in parts) or 1
            cur = st
            for p in parts:
                span = (en - st) * (len(p) / total_c)
                pst, pen = cur, min(cur + span, en)
                if pen - pst < lc["min_duration_s"]:
                    pen = min(pst + lc["min_duration_s"], en)
                cues.append({
                    "shot_id": sid,
                    "start": round(seg_start + pst, 3),
                    "end": round(seg_start + pen, 3),
                    "text": p,
                    "lines": split_two_lines(p, lc),
                    "source": it.get("source", "ctc-sequential")
                })
                cur = pen
    # 排序 → 延长过短条目 → 去重叠（后一条不得早于前一条结束）
    #   注意：延长必须受【下一条起点】约束，否则会把两条字幕叠在一起
    cues.sort(key=lambda c: c["start"])
    total = t0
    for i, c in enumerate(cues):
        nxt = cues[i + 1]["start"] if i + 1 < len(cues) else total
        if c["end"] <= c["start"]:
            c["end"] = c["start"] + lc["min_duration_s"]
        if c["end"] - c["start"] < lc["min_duration_s"]:
            c["end"] = min(c["start"] + lc["min_duration_s"], nxt)
        if c["end"] > nxt:
            c["end"] = nxt
        if c["end"] - c["start"] < lc["min_duration_s"] - 1e-6:
            warn.append("%s 「%s」时长仅 %.2fs（< 目标 %.1fs，因下一句紧跟，无法延长）"
                        % (c["shot_id"], c["text"][:12], c["end"] - c["start"], lc["min_duration_s"]))

    # ★ 语速偏慢的汇总（不逐条报警，见上方注释）
    _slow = [c for c in cps_soft if c.get("kind") == "slow"]
    if _slow:
        warn.append("（参考）%d 条字幕语速低于常规下限 %.1f 字/秒 —— 停留时间含停顿，属正常"
                    % (len(_slow), lc.get("cps_ok", [0, 999])[0]))

    # ★ 声学覆盖检查：段内【有语音却没有字幕覆盖】的区间 —— 这才是"字幕没对齐"的硬判据
    #   注意：必须减【该段在整集里的起点】，不是减"该段第一条字幕的起点"（踩过的坑：
    #   减错基准会让所有字幕整体前移，于是每段都误报一大堆缺口）
    asr_dir = os.path.join(subs_dir, "asr")
    os.makedirs(asr_dir, exist_ok=True)
    gaps = collect_gaps(segs, cues, seg_offsets, cfg, asr_dir)
    # ★ 先修「段首推后」，再复检 —— 报告里给出的是【修复后仍然存在】的缺口，不粉饰
    if repair_leading_gaps(segs, cues, seg_offsets, gaps, warn):
        gaps = collect_gaps(segs, cues, seg_offsets, cfg, asr_dir)
    warn.append("声学覆盖检查：%d 段中 %d 段存在『有语音但无字幕』的区间（合计 %.1fs）"
                % (len(segs), len({g["shot_id"] for g in gaps}),
                   sum(g["seconds"] for g in gaps)))
    for g in gaps:
        if g["seconds"] >= 1.5:
            warn.append("★ %s 集内 %.2f-%.2f s 有语音 %.2fs 却无字幕 ⇒ 对齐错位或台词缺失"
                        % (g["shot_id"], g["from"], g["to"], g["seconds"]))

    # ★ 生理上限的**最终判定**：判在【最终会渲染出去的字幕】上（含段首修复的效果）。
    #   为什么必须放这里：判在对齐原始记录上会误报（ep06_seg06 原始 0.76s → 修复后 3.94s）。
    imposs_final = lc.get("cps_impossible", 20.0)
    for c in cues:
        d = c["end"] - c["start"]
        if d > 0.05:
            v = spoken_len(c["text"]) / d
            if v > imposs_final:
                cps_hard.append({"shot_id": c["shot_id"], "text": c["text"][:20],
                                 "dur": round(d, 2), "spoken": spoken_len(c["text"]),
                                 "cps": round(v, 2), "source": c.get("source", ""),
                                 "final": True})
    for h in [x for x in cps_hard if x.get("final")]:
        warn.append("★ %s 「%s」最终字幕 %.1f 字/秒（%d 发音字 / %.2fs）超过生理上限"
                    % (h["shot_id"], h["text"][:14], h["cps"], h["spoken"], h["dur"]))
    return cues, warn, total, {"cps_hard": cps_hard, "cps_outliers": cps_soft,
                               "coverage_gaps": gaps}


# ---------------------------------------------------------------- 阶段 3：ASS

def ass_time(t):
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return "%d:%02d:%02d.%02d" % (h, m, s, cs)


def safe_area_limits(cfg):
    """平台字幕安全区下限（用户 2026-10-06 给定，属**硬性**规则）。

      · 距画面底部 **≥ 200px**
      · 文本框宽度 **≤ 视频宽度的 70%**

    为什么按【像素】存而不是百分比：平台口径就是像素。百分比会在换分辨率时漂移
    （200px 在 1080×1920 上是 10.4%，在 2560×1440 上只有 7.8%），所以配置里存像素，
    实现里取「配置百分比边距」与「安全区下限」的**较大值** ⇒ 任何画布下都满足。
    """
    sa = cfg.get("safe_area") or {}
    return {"min_bottom_px": float(sa.get("min_bottom_px") or 0),
            "max_text_width_pct": float(sa.get("max_text_width_pct") or 100)}


# ---------------------------------------------------------------------------
# ★ 2026-10-22（V0.7.6）：字幕纵向落点 —— 视觉中心 6:4（移植自 vidpure）
# ---------------------------------------------------------------------------
# 为什么不再用「距底固定像素」：400px 在 1080×1920 上占 20.8% 高，在 2176×3840 上只占
# 10.4% —— 同一部剧出 1080P 与 2K 两版，字幕位置肉眼可见地不同；横竖屏混着出时更明显。
# 6:4 是**比例**（中心落在 0.6H），任何画布下视觉重心一致。
#
# 为什么必须用 `\an5\pos` 而不是样式的 MarginV：`Alignment=2`（底对齐）时，
# **一行字幕与两行字幕的视觉中心不是同一条线** —— 折行会让文字往下长，整块上半部分
# 空出来，观感上"字幕在跳"。`\an5` 以文字块中心为锚点，逐条精确居中，行数变化不动位置。
ANCHOR_TOP_DEFAULT = 0.6        # = 距顶 6 : 距底 4
LINE_HEIGHT_EM = 1.2            # 估算文字块高度用的行高系数（只用于报告与安全区判定）


def ratio_label(top):
    """把 `0.6` 表述为 `6:4`（距顶:距底，十分制近似）。"""
    a = int(round(min(max(float(top or 0), 0.0), 1.0) * 10))
    return "%d:%d" % (a, 10 - a)


def placement_of(cfg):
    """读 `placement` 块；缺省即 6:4 视觉中心。

    兼容思路：老项目配置里没有 `placement` 键 —— 默认给 6:4（用户 2026-10-22 明确要求
    「字幕在这个位置更好」）；想保留旧的固定距底，显式写 `"anchor": "pixel"`。
    """
    pl = cfg.get("placement") or {}
    anchor = str(pl.get("anchor") or "ratio").lower()
    if anchor not in ("ratio", "pixel"):
        anchor = "ratio"
    try:
        top = float(pl.get("anchor_top", ANCHOR_TOP_DEFAULT))
    except (TypeError, ValueError):
        top = ANCHOR_TOP_DEFAULT
    return {"anchor": anchor, "anchor_top": top}


def pixel_locked_metrics(cfg, lang, canvas):
    """三语锁定口径：以样式表的 1080×1920 绝对像素为基准，等比缩放到当前画布。

    与旧百分比算法的区别（这是「锁死」的全部含义）：
      · 字号 = `font_px × scale`，**不被「文本框宽 ÷ 每行字数」二次压小**；
        装不下就当场报错 —— 说明规范本身写错了，必须改规范，而不是让运行时偷偷缩字。
      · 落点 = `anchor_top × H`，**不静默上顶**：安全区不满足同样报错。
      · 左右边距 = `margin_lr_px × scale`，与安全区的「宽 ≤70%」取较大值。
    """
    sheet = cfg.get("_style_sheet") or {}
    base = sheet.get("base") or {}
    bw = float(base.get("width") or 1080)
    bh = float(base.get("height") or 1920)
    W, H = canvas
    lim = safe_area_limits(cfg)
    pl = placement_of(cfg)
    line_em = float((sheet.get("placement") or {}).get("line_height_em") or LINE_HEIGHT_EM)
    scale = min(W / bw, H / bh)
    font_px = float(lc_font_px(cfg, lang))
    font_size = max(1, int(round(font_px * scale)))
    need_lr = int(math.ceil(W * (100.0 - lim["max_text_width_pct"]) / 200.0))
    margin_lr = max(int(round(float(lc_get(cfg, lang, "margin_lr_px", W * 0.15)) * scale)), need_lr)
    usable_w = W - 2 * margin_lr
    cw = float(lc_get(cfg, lang, "char_width_em", 1.0))
    ml = int(lc_get(cfg, lang, "max_line_chars", 12))
    lines = int(lc_get(cfg, lang, "max_lines", 2))
    need_w = ml * cw * font_size
    if need_w > usable_w + 0.5:
        raise SystemExit(
            "断言失败（字幕规范）：%s 一行 %d 字 × %.2fem × %dpx = %.0fpx，"
            "超出可用宽度 %dpx（安全区 %.0f%%，左右各 %dpx）。\n"
            "  这不是运行期问题，是规范写错了：改 configs/subtitle-styles.json 的 "
            "font_px / max_line_chars / char_width_em 三者之一，别让脚本自动缩字。"
            % (lang, ml, cw, font_size, need_w, usable_w,
               lim["max_text_width_pct"], margin_lr))
    block_h = max(1, int(round(font_size * line_em))) * lines
    top = min(max(float(pl["anchor_top"]), 0.05), 0.95)
    center_y = int(round(H * top))
    bottom_px = H - center_y - block_h // 2
    if bottom_px < lim["min_bottom_px"] - 0.5:
        raise SystemExit(
            "断言失败（字幕规范）：%s 落点 y=%d、块高 %d ⇒ 下沿距底 %dpx < %.0fpx。\n"
            "  改 anchor_top（当前 %.2f）或字号；不做静默上顶 —— 上顶后实际位置与规范不符，"
            "而 qa_safe_area 会按上顶后的值判过，等于把偏差藏起来。"
            % (lang, center_y, block_h, bottom_px, lim["min_bottom_px"], top))
    return {"margin_v": 0, "margin_lr": margin_lr, "usable_w": usable_w,
            "text_w_pct": 100.0 * usable_w / W, "font_size": font_size,
            "font_size_by": "locked(%dpx@%dx%d ×%.3f)" % (int(font_px), int(bw), int(bh), scale),
            "limits": lim, "char_width_em": cw,
            "anchor": "ratio", "anchor_top": round(top, 4),
            "anchor_label": ratio_label(top),
            "center_y": center_y, "pos": (W // 2, center_y), "block_h": block_h,
            "bottom_px": bottom_px, "clamped": False,
            "_style_sheet": sheet.get("_path") or ""}


def _pct_label(v):
    """报告用：锁定层只给绝对像素，没有百分比 —— 打印时要说「锁定」而不是崩在格式化上。"""
    return ("%.1f%%" % v) if isinstance(v, (int, float)) else "锁定"


def lc_get(cfg, lang, key, default):
    return (cfg["languages"].get(lang) or {}).get(key, default)


def lc_font_px(cfg, lang):
    v = (cfg["languages"].get(lang) or {}).get("font_px")
    if not v:
        raise SystemExit(
            "字幕规范里没有 %s 的 font_px（configs/subtitle-styles.json 的 styles.%s）"
            % (lang, lang))
    return v


def style_metrics(cfg, lang, canvas):
    """按三语锁定口径算字号 / 边距 / 落点。

    ★ 2026-11-01：删掉旧的「按 canvas 高度百分比 + 行宽反向压字」分支。
      保留两套算法的后果是「有人按百分比调字号，看起来生效了，其实被规范覆盖」——
      典型的两处真源。现在只有一个口径：`configs/subtitle-styles.json`。
    """
    return pixel_locked_metrics(cfg, lang, canvas)


def qa_safe_area(ass_path, cfg):
    """★ 机器断言：从**写好的 ASS** 回读几何，验证平台字幕安全区。

    回读文件而不是复用算出来的值 —— 断言看产物、不看意图（本项目一贯做法）。
    这样以后谁改了写入逻辑，这道断言都会拦住。

    ★ 2026-10-22（V0.7.6）：两种落点分别判 ——
      · `ratio`（6:4）：位置写在每条 Dialogue 的 `{\\an5\\pos(x,y)}` 里，
        判据是「文字块**下沿**距底 ≥ min_bottom_px」+「所有条目 y 相同且等于设计值」；
      · `pixel`（旧行为）：位置写在样式的 MarginV 里，判据是「距底 ≥ min_bottom_px」。
    只看样式 MarginV 会在 ratio 模式下永远为 0 而误判，所以必须先认出用的是哪种。
    """
    with open(ass_path, encoding="utf-8", errors="replace") as fh:
        txt = fh.read()
    W, H, style = None, None, None
    pos_ys = []
    for ln in txt.splitlines():
        if ln.startswith("PlayResX:"):
            W = int(ln.split(":", 1)[1].strip())
        elif ln.startswith("PlayResY:"):
            H = int(ln.split(":", 1)[1].strip())
        elif ln.startswith("Style: Default,"):
            style = ln
        elif ln.startswith("Dialogue:"):
            m = re.search(r"\\pos\(\s*-?\d+\s*,\s*(-?\d+)\s*\)", ln)
            if m:
                pos_ys.append(int(m.group(1)))
    if W is None or H is None or style is None:
        return {"pass": False, "failures": ["ASS 里找不到 PlayResX/Y 或 Default 样式行"]}
    p = style.split(",")
    font_size = int(p[2])                # p[0]="Style: Default", p[1]=字体名, p[2]=字号
    mL, mR, mV = int(p[-4]), int(p[-3]), int(p[-2])
    lim = safe_area_limits(cfg)
    lc = cfg["languages"][cfg.get("default_language", "zh")]
    pl = placement_of(cfg)
    text_w = W - mL - mR
    pct = 100.0 * text_w / W
    need_w = lc["max_line_chars"] * float(lc.get("char_width_em", 1.0)) * font_size
    block_h = max(1, int(round(font_size * LINE_HEIGHT_EM))) * int(lc.get("max_lines", 2))
    fails = []

    if pos_ys:
        # ---- ratio 模式：判 \pos 的实际落点 ----
        top = min(max(pl["anchor_top"], 0.05), 0.95)
        want_y = int(round(H * top))
        cap_y = H - int(math.ceil(lim["min_bottom_px"])) - block_h // 2
        if want_y > cap_y:                     # 安全区更严时以安全区为准
            want_y = max(block_h // 2, cap_y)
        uniq = sorted(set(pos_ys))
        if len(uniq) > 1:
            fails.append("各条目 \\pos 的 y 不一致（%s）—— 折行会让字幕上下浮动" % uniq[:6])
        y = uniq[0]
        if abs(y - want_y) > 1:
            fails.append("落点 y=%d 与设计值 %d 相差 >1px" % (y, want_y))
        bottom_edge = y + block_h // 2
        if H - bottom_edge < lim["min_bottom_px"] - 0.5:
            fails.append("文字块下沿距底 %dpx < %dpx"
                         % (H - bottom_edge, int(lim["min_bottom_px"])))
        if y - block_h // 2 < 0:
            fails.append("文字块上沿超出画面（y=%d，块高 %d）" % (y, block_h))
    else:
        # ---- pixel 模式：判样式 MarginV ----
        want_y = None
        if mV < lim["min_bottom_px"] - 0.5:
            fails.append("距底 %dpx < %dpx" % (mV, int(lim["min_bottom_px"])))

    if pct > lim["max_text_width_pct"] + 0.05:
        fails.append("文本宽 %.2f%% > %.0f%%" % (pct, lim["max_text_width_pct"]))
    if need_w > text_w + 0.5:
        fails.append("一行 %d 字 × %.2fem × %dpx = %.0fpx 溢出文本框 %dpx"
                     % (lc["max_line_chars"], float(lc.get("char_width_em", 1.0)),
                        font_size, need_w, text_w))
    return {"pass": not fails, "failures": fails,
            "canvas": "%dx%d" % (W, H), "font_size_px": font_size,
            "margin_v_px": mV, "margin_lr_px": mL, "text_w_px": text_w,
            "text_w_pct": round(pct, 2),
            "anchor": "ratio" if pos_ys else "pixel",
            "anchor_top": pl["anchor_top"] if pos_ys else None,
            "anchor_label": ratio_label(pl["anchor_top"]) if pos_ys else None,
            "pos_y": (sorted(set(pos_ys))[0] if pos_ys else None),
            "anchor_expected_y": want_y,
            "bottom_gap_px": (H - (pos_ys[0] + block_h // 2)) if pos_ys else mV,
            "block_h_px": block_h,
            "min_bottom_px": int(lim["min_bottom_px"]),
            "max_text_width_pct": lim["max_text_width_pct"]}


def write_ass(cues, cfg, out_path, lang=None, canvas=None, offset_s=0.0):
    """canvas=(W,H)：字幕实际要烧上去的分辨率。

    offset_s：整体后移量（秒）。★ 2026-11-10 新增 —— 见下方「封面片头」说明。

    **为什么需要 offset_s**：`cues` 的时间轴是「片段轴」，从第一段画面算起
    （`build_cues` 的 `t0` 从 0 开始累加）。而母版前面还有 `master.cover_seconds`
    的封面片头（默认 0.8s）。旧实现两处都不加偏移 ⇒ 只要封面存在，**每条字幕都早
    0.8 秒**：第 3 句台词出在第 2 句的画面上，肉眼看着像「对齐又错了一点」，
    而所有断言都过（因为断言比较的是 cues 与 cues）。
    现在由调用方把真实偏移传进来，ASS、剪映工程、渲染自检三处用同一个值。

    为什么必须显式传：高清放大后画布从 1440x832 变成 2560x1480，
    PlayResX/Y 与实际分辨率不一致会让 libass 拉伸/偏移字幕（本项目踩过：
    「样式改了没生效」十有八九是 PlayRes 与视频分辨率不等）。
    字号/边距仍按百分比算 ⇒ 视觉比例与 1440p 时完全一致，只是像素值变大。
    """
    lang = lang or cfg["default_language"]
    lc = cfg["languages"][lang]
    lay = cfg["layout"]
    W, H = (canvas or (cfg["canvas"]["width"], cfg["canvas"]["height"]))
    _m = style_metrics(cfg, lang, (W, H))
    font_size, margin_v, margin_lr = _m["font_size"], _m["margin_v"], _m["margin_lr"]
    bold = -1 if lc.get("bold") else 0
    head = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "Title: %s" % os.path.basename(out_path),
        "PlayResX: %d" % W,
        "PlayResY: %d" % H,
        "WrapStyle: %d" % lay.get("WrapStyle", 2),
        "ScaledBorderAndShadow: %s" % lay.get("ScaledBorderAndShadow", "yes"),
        "YCbCr Matrix: TV.709",
        "",
        "[V4+ Styles]",
        ("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
         "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
         "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"),
        "Style: Default,%s,%d,%s,&H000000FF,%s,%s,%d,0,0,0,100,100,0,0,1,%d,%d,2,%d,%d,%d,%d" % (
            lc["font"], font_size, lay["primary_colour"], lay["outline_colour"],
            lay["back_colour"], bold, lc.get("outline", 3), lc.get("shadow", 1),
            margin_lr, margin_lr, margin_v, lay.get("encoding", 1)),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    body = []
    # ★ 2026-10-22（V0.7.6）：ratio 模式用 `\an5\pos` 逐条定位 —— 文字块中心固定在
    #   0.6H，一行与两行同线；pixel 模式仍是样式 MarginV（旧行为，只写纯文本）。
    for c in cues:
        txt = "\\N".join(c["lines"]).replace("{", "(").replace("}", ")")
        if _m["pos"]:
            txt = "{\\an5\\pos(%d,%d)}%s" % (_m["pos"][0], _m["pos"][1], txt)
        body.append("Dialogue: 0,%s,%s,Default,,0,0,0,,%s" % (
            ass_time(c["start"] + offset_s), ass_time(c["end"] + offset_s), txt))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(head + body) + "\n")
    return {"font": lc["font"], "font_size_px": font_size,
            "font_size_pct": lc.get("font_size_pct"),
            "offset_s": round(float(offset_s), 3),
            "margin_v_px": margin_v, "margin_lr_px": margin_lr,
            "margin_v_pct": lc.get("margin_v_pct"),
            "anchor": _m["anchor"], "anchor_top": _m["anchor_top"],
            "anchor_label": _m["anchor_label"],
            "center_y": _m["center_y"], "bottom_px": _m["bottom_px"],
            "block_h_px": _m["block_h"], "anchor_clamped": _m["clamped"],
            "font_size_by": _m["font_size_by"], "text_w_px": _m["usable_w"],
            "text_w_pct": round(_m["text_w_pct"], 2),
            "safe_area": {"min_bottom_px": int(_m["limits"]["min_bottom_px"]),
                          "max_text_width_pct": _m["limits"]["max_text_width_pct"]},
            "canvas": "%dx%d" % (W, H), "cues": len(body)}


# ---------------------------------------------------------------- 阶段 4/5：拼接与烧录

DEFAULT_EDGE_FADE_MS = 120     # ★ 2026-10-20（反馈 P2-11）：切点音频淡入淡出默认值


def _seg_probe(tools, path):
    """探测一段的 (时长秒, 是否有音轨)；读不出来返回 (0, False)。"""
    try:
        _, out = run([tools["ffprobe"], "-v", "error",
                      "-show_entries", "stream=codec_type,duration:format=duration",
                      "-of", "json", path])
        data = json.loads(out or "{}")
        streams = data.get("streams") or []
        has_audio = any(s.get("codec_type") == "audio" for s in streams)
        dur = 0.0
        for s in streams:
            try:
                dur = max(dur, float(s.get("duration") or 0))
            except (TypeError, ValueError):
                pass
        if not dur:
            try:
                dur = float((data.get("format") or {}).get("duration") or 0)
            except (TypeError, ValueError):
                dur = 0.0
        return dur, has_audio
    except BaseException:                                         # noqa: BLE001
        return 0.0, False


def _fade_segment(tools, src, dst, fade_ms):
    """把一段的首尾各做 fade_ms 的音频淡入/淡出（视频流 copy，不重编码画面）。

    为什么需要（反馈 P2-11 实测）：每段由模型独立生成，**段尾自带淡出**；
    硬切拼接时电平从「近静音」跳到「满环境声」，于是每个切点都有「噗」声/音量台阶。
    实测：sc01 尾 0.15s 均值 -43.5 dB → sc02 头 0.15s 均值 -33.1 dB（约 10 dB 台阶）；
    逐段淡入淡出后切点 peak 从 -23.0 dB 降到 -37.2 dB，爆点消除。
    """
    dur, has_audio = _seg_probe(tools, src)
    d = max(0.0, float(fade_ms) / 1000.0)
    if not has_audio or dur <= 0 or d <= 0:
        return None
    out_at = max(0.0, dur - d)
    af = "afade=t=in:st=0:d=%.3f,afade=t=out:st=%.3f:d=%.3f" % (d, out_at, d)
    run([tools["ffmpeg"], "-hide_banner", "-nostats", "-v", "error", "-y", "-i", src,
         "-c:v", "copy", "-af", af,
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
         dst])
    return dst


def release_dir_of(ws):
    """发行目录（09-发行）。口径与 stages/_layout.py 一致，缺 layout.json 时用默认名。"""
    ws = os.path.abspath(ws)
    rel = "09-发行"
    lj = os.path.join(ws, "layout.json")
    if os.path.isfile(lj):
        try:
            lay = json.load(open(lj, encoding="utf-8-sig"))
            rel = ((lay.get("stages") or {}).get("release")) or rel
        except Exception:                                                  # noqa: BLE001
            pass
    return os.path.join(ws, rel)


COVER_LEAD_DEFAULT_S = 0.8       # 首帧封面停留时长（短剧常用 0.5–1.0s；太长会被判「片头拖沓」）


def _seg_video_info(ffprobe, path):
    """读第一段的视频参数 —— 封面片头必须按它生成，否则 `-c copy` 拼不上。"""
    _, out = run([ffprobe, "-v", "error", "-select_streams", "v:0",
                  "-show_entries",
                  "stream=codec_name,pix_fmt,width,height,r_frame_rate,sample_aspect_ratio",
                  "-of", "json", path])
    st = ((json.loads(out or "{}").get("streams") or [{}])[0]) or {}
    try:
        num, den = (st.get("r_frame_rate") or "24/1").split("/")
        fps = float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        fps = 24.0
    return {"codec": (st.get("codec_name") or "h264").lower(),
            "pix_fmt": st.get("pix_fmt") or "yuv420p",
            "width": int(st.get("width") or 1080), "height": int(st.get("height") or 1920),
            "fps": round(fps, 6) or 24.0,
            "sar": st.get("sample_aspect_ratio") or "1:1"}


# 封面命名规则 —— ★ 与 `release_check.scan_covers()` 的 `^cover[_-](\d+x\d+)` 同一条。
# 两处都认 `cover_9x16.png` 与 `cover-9x16_01.jpg`（AI 直出会一档出多张，选定后改名）。
COVER_STEM_RE = re.compile(r"^cover[_-](\d+)x(\d+)(?:[_-].*)?$", re.I)
COVER_PREF = ("9", "16")          # 片头只用竖版那档


def _cover_candidates(d):
    """目录下符合封面命名、且是 9:16 的图片（按文件名排序，可复现）。"""
    out = []
    if not os.path.isdir(d):
        return out
    for name in sorted(os.listdir(d)):
        p = os.path.join(d, name)
        stem, ext = os.path.splitext(name)
        if ext.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            continue
        m = COVER_STEM_RE.match(stem)
        if m and (m.group(1), m.group(2)) == COVER_PREF:
            out.append(p)
    return out


def find_cover(ws, ep, cfg=None):
    """找该集的封面图。→ (path, 说明) ／ (None, 为什么没有)。

    查找顺序刻意是「发行目录优先」：`09-发行/封面/cover_9x16*.png` 是**已定稿**的那张
    （release_check 认这个名字）；草稿图放 `subs/<ep>/<ep>_cover.png`，方便在定稿前先试片头。
    """
    subs = os.path.join(out_dir_of(ws), "subs", ep)
    rel = release_dir_of(ws)
    cands = []
    for d in (os.path.join(rel, "封面"), rel):
        cands += _cover_candidates(d)
    for stem in ("%s_cover" % ep, "cover_%s" % ep, "cover"):
        for ext in ("png", "jpg", "jpeg", "webp"):
            cands.append(os.path.join(subs, "%s.%s" % (stem, ext)))
    seen, uniq = set(), []
    for p in cands:
        ap = os.path.abspath(p)
        if ap not in seen and os.path.isfile(ap):
            seen.add(ap)
            uniq.append(ap)
    if not uniq:
        return None, ("没找到封面（找过 %s/封面/cover_9x16*.png 与 %s/%s_cover.png）"
                      % (os.path.basename(rel), os.path.basename(subs), ep))
    return uniq[0], os.path.basename(uniq[0])


def build_cover_lead(cfg, cover, ref, out_path, seconds, has_audio):
    """把封面图转成「与第一段同参数」的短视频，好让 concat 直接 -c copy。

    ★ 为什么必须同参数：`-f concat -c copy` 是**流级拼接**，编码器/像素格式/分辨率/
      帧率/SAR 有一项不同就会报错或（更糟）静默丢段。这里按第一段实测参数生成；
      生成完再比一次，不一致就让拼接走重编码（`stage_master` 里的兜底）。
    """
    W, H, fps = ref["width"], ref["height"], ref["fps"]
    pix = ref["pix_fmt"] if ref["pix_fmt"] in ("yuv420p", "yuvj420p") else "yuv420p"
    vf = ("scale=%d:%d:force_original_aspect_ratio=increase:flags=lanczos,"
          "crop=%d:%d,setsar=%s,fps=%s,format=%s"
          % (W, H, W, H, ref["sar"] or "1:1", ("%g" % fps), pix))
    enc = (["-c:v", "libx265", "-crf", "18", "-preset", "medium", "-tag:v", "hvc1",
            "-x265-params", "log-level=error"]
           if ref["codec"] in ("hevc", "h265")
           else ["-c:v", "libx264", "-crf", "16", "-preset", "medium"])
    cmd = [cfg["tools"]["ffmpeg"], "-hide_banner", "-nostats", "-v", "error", "-y",
           "-loop", "1", "-t", "%.3f" % seconds, "-i", cover]
    if has_audio:
        cmd += ["-f", "lavfi", "-t", "%.3f" % seconds,
                "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
    cmd += ["-vf", vf, "-r", "%g" % fps] + enc + ["-pix_fmt", pix,
                                                  "-t", "%.3f" % seconds]
    if has_audio:
        cmd += ["-c:a", "aac", "-b:a", "192k", "-ac", "2", "-ar", "48000", "-shortest"]
    cmd += [out_path]
    run(cmd)
    if not os.path.isfile(out_path) or ffprobe_frames(cfg["tools"]["ffprobe"], out_path) < 1:
        raise SystemExit("封面片头生成失败（0 帧）：%s" % out_path)
    return out_path


def cover_lead_seconds(ws, ep, cfg, enabled=True):
    """母版封面片头的**实际**时长（秒）＋命中的封面路径；没有封面/关闭则 (0.0, 原因)。

    ★ 2026-11-10：这是「封面片头到底占多长时间」的唯一真源。
      此前这个数字散在 `stage_master` 一处，而字幕时间、渲染自检、剪映工程都需要它 ——
      各算一份的下场是「母版加了 0.8s，字幕不知道」，全部字幕早 0.8 秒而无人报警。
      任何需要「母版时间轴 = 片段轴 + 片头」的地方都必须调这里。
    """
    if not enabled:
        return 0.0, "已关闭封面（--no-cover）"
    cpath, cmsg = find_cover(ws, ep, cfg)
    if not cpath:
        return 0.0, cmsg
    secs = float((cfg.get("master") or {}).get("cover_seconds") or COVER_LEAD_DEFAULT_S)
    return secs, cpath


def stage_master(ws, ep, cfg, segs, subs_dir, cover=True, bgm=True):
    """拼接母版 —— 剪辑第一道工序，一次产出 `<ep>_master.mp4`。

    组成固定为三步（顺序即规范）：
      ① **首帧封面**（可选）：`09-发行/封面/cover_9x16*.png` → 0.8s 静帧片头；
         找不到就跳过并告警，**不阻塞出片**（封面是发行资料，可能晚于成片）。
      ② **视频片段**：按镜头顺序拼接，逐段做音频首尾淡入淡出（反馈 P2-11）。
      ③ **BGM**（可选）：检测到 `<ep>_bgm-plan.json` 就混一条；没有就跳过。
    放大与字幕都在**这一步之后**，所以母版里已经带着 BGM —— 与用户定的顺序一致：
      母版拼接（封面 + 片段 + BGM）→ 放大（RH / Topaz / 跳过）→ 字幕生成与烧录。
    """
    out = os.path.join(subs_dir, "%s_master.mp4" % ep)
    raw = os.path.join(subs_dir, "%s_master_raw.mp4" % ep)
    lst = os.path.join(subs_dir, "_concat.txt")
    tools = cfg["tools"]
    fade_ms = int((cfg.get("audio") or {}).get("edge_fade_ms", DEFAULT_EDGE_FADE_MS) or 0)
    notes = []

    seg_files = [s["file"] for s in segs]
    if fade_ms > 0 and len(seg_files) > 1:
        prepped, changed = [], 0
        for i, src in enumerate(seg_files):
            dst = os.path.join(subs_dir, "_fade_%02d.mp4" % (i + 1))
            got = _fade_segment(tools, src, dst, fade_ms)
            prepped.append(got or src)
            changed += 1 if got else 0
        seg_files = prepped
        sys.stderr.write("[i] 切点音频淡入淡出：%d ms，已处理 %d/%d 段（反馈 P2-11）\n"
                         % (fade_ms, changed, len(seg_files)))

    files = []
    # ① 首帧封面
    if cover:
        cpath, cmsg = find_cover(ws, ep, cfg)
        if not cpath:
            notes.append("① 首帧封面：跳过 —— %s" % cmsg)
        else:
            ref = _seg_video_info(tools["ffprobe"], seg_files[0])
            _, has_audio = _seg_probe(tools, seg_files[0])
            secs, _ = cover_lead_seconds(ws, ep, cfg, enabled=True)
            secs = secs or COVER_LEAD_DEFAULT_S
            lead = build_cover_lead(cfg, cpath, ref, os.path.join(
                subs_dir, "_cover_lead.mp4"), secs, has_audio)
            files.append(lead)
            notes.append("① 首帧封面：%s → %.1fs 片头（%dx%d %s）"
                         % (cmsg, secs, ref["width"], ref["height"], ref["codec"]))
    # ② 视频片段
    files += seg_files

    lines = []
    for f in files:
        lines.append("file '%s'" % f.replace("\\", "/").replace("'", "'\\''"))
    with open(lst, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    run([cfg["tools"]["ffmpeg"], "-hide_banner", "-nostats", "-v", "error", "-y",
         "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", raw])
    # ★ 2026-10-22：HEVC 多段 `-c copy` 拼接会间歇性产生**坏码流**
    #   （实测 ep17：解码报 `Could not find ref with POC 258`，母版只有 1259/1485 帧，
    #    下游 Topaz 直接崩溃 rc=3226505、产物 moov 缺失）。
    #   拼接是流级别的，参数微小差异就会断参考帧 ⇒ 这里做一次帧数校验，
    #   对不上就重编码重建（crf 16 视觉无损），不要带着坏母版往下走。
    try:
        expect = 0
        for f in files:
            expect += ffprobe_frames(cfg["tools"]["ffprobe"], f)
        got = ffprobe_frames(cfg["tools"]["ffprobe"], raw)
        if expect and got < expect * 0.98:
            sys.stderr.write("[!] 拷贝拼接丢帧（%d/%d）→ 改用 concat 滤镜重编码重建母版\n" % (got, expect))
            tmp = raw + ".reenc.mp4"
            # ★ 必须用 filter 版：并流器（-f concat）在 HEVC 段参数不一致时会静默丢段
            #   （实测 ep17 丢了整整一段 226 帧），filter 版逐帧解码重编码，帧数准确。
            cmd = [cfg["tools"]["ffmpeg"], "-hide_banner", "-nostats", "-v", "error", "-y"]
            for f in files:
                cmd += ["-i", f]
            cmd += ["-filter_complex", "concat=n=%d:v=1:a=1[v][a]" % len(files),
                    "-map", "[v]", "-map", "[a]",
                    "-c:v", "libx264", "-crf", "16", "-preset", "medium", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k", tmp]
            run(cmd)
            os.replace(tmp, raw)
            got = ffprobe_frames(cfg["tools"]["ffprobe"], raw)
            sys.stderr.write("[i] 重编码后帧数：%d（期望 %d）\n" % (got, expect))
    except SystemExit as exc:
        sys.stderr.write("[!] 母版帧数校验跳过：%s\n" % exc)

    # ③ BGM（可选，非必选）
    final = raw
    if bgm:
        mixed, msg = _try_bgm(ws, ep, raw)
        if msg:
            notes.append("③ BGM：%s" % msg.replace("⑤.6 BGM：", ""))
        if mixed and os.path.abspath(mixed) != os.path.abspath(raw):
            os.replace(mixed, out)      # 统一成 <ep>_master.mp4，下游不必知道有没有 BGM
        else:
            os.replace(raw, out)
    else:
        notes.append("③ BGM：已关闭（--no-bgm）")
        os.replace(raw, out)
    for n in notes:
        print("  " + n)
    return out


def _try_bgm(ws, ep, base_video, disabled=False):
    """BGM 混音（★ 2026-11-01 起并入**母版拼接**，不再挂在烧字幕前）。

    顺序依据（用户 2026-11-01 定）：母版拼接（首帧封面 + 片段 + BGM）→ 高清放大 →
    字幕生成与烧录。BGM 必须在放大之前混：放大只重编码视频/音频，混好的音轨会跟着
    一起处理；若放在最后，则要再重编码一次视频容器。

    依赖方向是**单向可选**的：本脚本可能被拷进 Skill 包单独运行，那时仓库的
    `stages/production/scripts/bgm.py` 不在 sys.path 上。所以：
      ① 已有 `<ep>_mix.mp4` 且不比底片旧 → 直接复用（零依赖）；
      ② 否则尝试 import bgm，有计划就现混；
      ③ import 不到 → 打印手动命令，**不阻塞出片**（没有 BGM 也要能交片）。
    """
    if disabled:
        return base_video, ""
    subs = os.path.join(out_dir_of(ws), "subs", ep)
    mix = os.path.join(subs, "%s_mix.mp4" % ep)
    plan = os.path.join(subs, "%s_bgm-plan.json" % ep)
    if os.path.isfile(mix):
        try:
            if not base_video or os.path.getmtime(mix) >= os.path.getmtime(base_video):
                return mix, "复用已有混音版 %s" % os.path.basename(mix)
        except OSError:
            pass
    if not os.path.isfile(plan):
        return base_video, ""
    if not base_video:
        return base_video, ""
    repo_scripts = os.path.join(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))), "production", "scripts")
    if repo_scripts not in sys.path:
        sys.path.insert(0, repo_scripts)
    try:
        import bgm as _bgm                                                  # noqa: WPS433
    except Exception:                                                       # noqa: BLE001
        return base_video, ("⑤.6 BGM：检测到 %s，但当前环境没有 bgm.py，已跳过混音\n"
                            "     手动：python stages/production/scripts/bgm.py "
                            "--workspace \"%s\" --ep %s mix --apply"
                            % (os.path.basename(plan), ws, ep))
    try:
        _plan = json.load(open(plan, encoding="utf-8-sig"))
        res = _bgm.mix_episode(ws, _plan, base=base_video, apply=True)
    except Exception as e:                                                  # noqa: BLE001
        return base_video, "⑤.6 BGM：混音异常，按无 BGM 继续 —— %s: %s" % (type(e).__name__, e)
    if not res.get("ok"):
        return base_video, "⑤.6 BGM：混音失败，按无 BGM 继续 —— %s" % res.get("error")
    return res["out"], "⑤.6 BGM：已混音 %s（%ss，视频直通只重编码音频）" % (
        os.path.basename(res["out"]), res.get("duration"))


def stage_render(cfg, master, ass, out, soft=False, norm_vf=None):
    r = cfg["render"]
    if soft:
        run([cfg["tools"]["ffmpeg"], "-hide_banner", "-nostats", "-v", "error", "-y",
             "-i", master, "-i", ass, "-c", "copy", "-c:s", "mov_text", out])
        return out
    # ★ 2026-10-30：归一化必须在烧字幕【之前】—— 字幕坐标按最终画布算，
    #   crop 在前才不会让字幕跟着被裁掉一半。
    vf = "subtitles=%s" % esc_filter_path(ass)
    if norm_vf:
        vf = "%s,%s" % (norm_vf, vf)
    run([cfg["tools"]["ffmpeg"], "-hide_banner", "-nostats", "-v", "error", "-y",
         "-i", master, "-vf", vf,
         "-c:v", r["video_codec"], "-crf", str(r["crf"]), "-preset", r["preset"],
         "-pix_fmt", r["pix_fmt"],
         "-c:a", r["audio_codec"], "-movflags", "+faststart", out])
    return out


# ---------------------------------------------------------------------------
# 交付规格归一化（★ 2026-10-30）
# ---------------------------------------------------------------------------
# 为什么需要（平台驳回「检测到视频画面中存在黑边」）
#   H3 出片是 672×1216（21:38 = 0.5526），不是 9:16（0.5625）；平台在 0.8MP + 32 对齐下
#   只能给这个尺寸。整条链到交付层为了凑 1080×1920 用了 SAR 59:60（非方形像素），
#   平台按显示比例重算时必然补边 —— 本地 cropdetect 满幅，所以自查永远查不出来。
#   ⇒ 交付前一律 **crop-to-fill** 到精确 9:16 + SAR 1:1。绝不 pad（补边就是制造黑边）。
DELIVERY_SPEC = {"width": 1080, "height": 1920, "sar": "1:1", "pix_fmt": "yuv420p"}
DELIVERY_RATIO_TOL = 0.003          # 显示比例容差 0.3%
# ★ 中间件命名刻意**不带分辨率数字**：`release_export.SOURCE_PREFERENCE` 里 `_1080`
#   会被判成「已编码发布版」（rank 0，比 `_subbed` 还优先），于是归一化中间件会
#   抢在带字幕的成片前面被导出 —— 那等于把「无字幕」问题原样复制一遍。
NORM_SUFFIX = "_normdelivery.mp4"    # <ep>_normdelivery.mp4（中间件，绝不是发布版）


def norm_filter(w, h):
    """crop-to-fill 滤镜串。三步顺序不能换，理由见 delivery_spec.build_normalize_vf。"""
    return ("scale=trunc(iw*sar/2)*2:ih,setsar=1,"
            "scale=%d:%d:force_original_aspect_ratio=increase:flags=lanczos,setsar=1,"
            "crop=%d:%d,setsar=1" % (w, h, w, h))


def spec_violations(dims, w, h, sar=None):
    """dims=(像素宽, 像素高)。返回违规描述列表；空 = 合规。

    ★ 判据是「显示比例」，不是「像素比例」—— SAR 59:60 的文件像素比是 0.5625，
      看着完全符合，显示比例却是 0.5531，这正是黑边的来源。
    """
    out = []
    pw, ph = dims
    sn, sd = (1, 1)
    if sar:
        try:
            a, b = str(sar).split(":")
            sn, sd = int(a), int(b)
        except (ValueError, TypeError):
            sn, sd = (1, 1)
    disp = pw * (float(sn) / float(sd))
    if abs(disp / float(ph) - float(w) / h) / (float(w) / h) > DELIVERY_RATIO_TOL:
        out.append("显示比例 %.4f（%d×%d SAR %d:%d）≠ %.4f"
                   % (disp / ph, pw, ph, sn, sd, float(w) / h))
    if (pw, ph) != (w, h):
        out.append("像素尺寸 %d×%d ≠ %d×%d" % (pw, ph, w, h))
    return out


def _probe_sar(ffprobe, path):
    p = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=sample_aspect_ratio,pix_fmt",
                        "-of", "csv=p=0", path],
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    txt = p.stdout.decode("utf-8", "replace").strip().splitlines()
    parts = (txt[0].split(",") if txt else [])
    sar = parts[0].strip() if parts and parts[0] not in ("N/A", "") else None
    fmt = parts[1].strip() if len(parts) > 1 else ""
    return sar, fmt


def ensure_delivery_spec(cfg, src, subs_dir, ep, *, target=None, force=False):
    """把 src 归一化到交付规格，返回 (路径, 说明)。

    已经合规就直接返回原路径（零成本复用）；不合规才重编码一次。
    产物名 `<ep>_norm_<W>_<H>.mp4` —— 明确是**中间件**，不是发布版，
    避免又变成「某个 1080p 文件被当成成片直接发出去」。
    """
    # target 既接受 (W, H) 也接受 {"width":…, "height":…}：调用方从 cfg["canvas"] 拿的是两种形状
    if isinstance(target, (tuple, list)) and len(target) >= 2:
        w, h = int(target[0]), int(target[1])
    else:
        t = target or DELIVERY_SPEC
        w, h = int(t["width"]), int(t["height"])
    dims = video_dims(cfg["tools"]["ffprobe"], src)
    sar, fmt = _probe_sar(cfg["tools"]["ffprobe"], src)
    bad = spec_violations(dims, w, h, sar)
    if fmt and fmt != DELIVERY_SPEC["pix_fmt"]:
        bad.append("像素格式 %s ≠ %s" % (fmt, DELIVERY_SPEC["pix_fmt"]))
    if not bad and not force:
        return src, "已是交付规格 %d×%d SAR 1:1（复用，不重编码）" % (w, h)

    dst = os.path.join(subs_dir, ep + NORM_SUFFIX)
    print("  规格归一化：%dx%d SAR %s → %d×%d SAR 1:1（crop-to-fill，不补边）"
          % (dims[0], dims[1], sar or "1:1", w, h))
    for b in bad:
        print("    · %s" % b)
    r = cfg["render"]
    run([cfg["tools"]["ffmpeg"], "-hide_banner", "-nostats", "-v", "error", "-y",
         "-i", src, "-vf", norm_filter(w, h),
         "-c:v", r["video_codec"], "-crf", str(r["crf"]), "-preset", r["preset"],
         "-pix_fmt", DELIVERY_SPEC["pix_fmt"],
         "-c:a", "copy", "-movflags", "+faststart", dst])
    got = video_dims(cfg["tools"]["ffprobe"], dst)
    left = spec_violations(got, w, h, "1:1")
    if left:
        raise SystemExit("断言失败：归一化后仍不合规 —— %s" % "；".join(left))
    print("    ⇒ %s（%d×%d）" % (os.path.basename(dst), got[0], got[1]))
    return dst, "已归一化到 %d×%d SAR 1:1" % (w, h)


def verify_render(cfg, master, subbed, cues, subs_dir, canvas=None, offset_s=0.0):
    """机器断言字幕【真的画出来了】—— 本机无 vision provider，不能靠眼睛。

    原理：同一时间点分别抽「母版（无字幕）」与「成片（有字幕）」一帧，
    比较【字幕带】与【画面其余部分】的像素差异。
      * 字幕带差异应显著大于画面其余部分（证明变化是局部发生在字幕区）
      * 字幕带内的【近白像素】数量应明显增加（字幕是白字黑边）

    offset_s：与 `write_ass` 同一个封面片头偏移。抽帧时刻若不加这个偏移，
    就会去「字幕还没出现的画面」上找字幕差异，自检随机失败（或被误判通过）。
    """
    try:
        import numpy as np
        from PIL import Image
    except Exception as e:
        return {"skipped": "缺少 numpy/Pillow: %s" % e}

    W, H = (canvas or (cfg["canvas"]["width"], cfg["canvas"]["height"]))
    lc = cfg["languages"][cfg["default_language"]]
    _sm = style_metrics(cfg, cfg["default_language"], (W, H))
    fsz = _sm["font_size"]
    # ★ 2026-10-22（V0.7.6）：字幕带必须跟着**实际落点**走 —— 6:4 模式下字幕在
    #   0.6H 附近，若还按「H − margin_v − 2.6×字号」取带，会把画面下半部分当字幕带，
    #   自检就变成"哪里都在动"（diff_rest 被拉高），判定失真。
    if _sm["pos"]:
        pad = int(fsz * 0.8)
        band_top = max(0, _sm["center_y"] - _sm["block_h"] // 2 - pad)
        band_bottom = min(H, _sm["center_y"] + _sm["block_h"] // 2 + pad)
    else:
        band_top = max(0, H - _sm["margin_v"] - int(fsz * 2.6))       # 两行字幕 + 边距
        band_bottom = H
    cand = sorted([c for c in cues if c["end"] - c["start"] >= 1.0],
                  key=lambda c: c["end"] - c["start"], reverse=True)[:3] or cues[:1]

    results, best = [], None
    for c in cand:
        t = (c["start"] + c["end"]) / 2.0 + float(offset_s)
        fa = os.path.join(subs_dir, "_vfy_master.png")
        fb = os.path.join(subs_dir, "_vfy_subbed.png")
        for src, dst in ((master, fa), (subbed, fb)):
            run([cfg["tools"]["ffmpeg"], "-hide_banner", "-nostats", "-v", "error", "-y",
                 "-ss", "%.3f" % t, "-i", src, "-frames:v", "1", dst])
        a = np.asarray(Image.open(fa).convert("RGB"), dtype=np.int16)
        b = np.asarray(Image.open(fb).convert("RGB"), dtype=np.int16)
        band = slice(band_top, band_bottom)
        # 「画面其余」= 上块 + 下块（字幕带可能在中间，不能只取上半部分）
        other = np.concatenate([
            np.arange(0, max(1, band_top)),
            np.arange(min(H, band_bottom + 1), H)]) if _sm["pos"] else slice(0, max(1, band_top - 60))
        d_band = float(np.abs(a[band] - b[band]).mean())
        d_other = float(np.abs(a[other] - b[other]).mean())
        w_a = int((a[band] > 225).all(axis=2).sum())
        w_b = int((b[band] > 225).all(axis=2).sum())
        r = {"t": round(t, 2), "text": c["text"][:20],
             "diff_band": round(d_band, 2), "diff_rest": round(d_other, 2),
             "white_master": w_a, "white_subbed": w_b, "white_gain": w_b - w_a}
        results.append(r)
        if best is None or r["white_gain"] > best["white_gain"]:
            best = r
    for p in ("_vfy_master.png", "_vfy_subbed.png"):
        # ★ 2026-10-07：不删验证截图（safe-delete 钩子会话级计数），残留收尾统一清
        pass

    verdict = {
        "band_top_px": band_top,
        "band_bottom_px": band_bottom,
        "samples": results,
        "best": best,
        "pass": bool(best and best["white_gain"] > 200 and best["diff_band"] > best["diff_rest"]),
    }
    return verdict


# ---------------------------------------------------------------- 主流程

def main():
    harden_stdio()
    ap = argparse.ArgumentParser(description="可复用字幕管线（对齐 → ASS → 母版 → 烧录）")
    ap.add_argument("--ep", required=True, help="集号，如 ep03")
    ap.add_argument("--workspace", default=ROOT,
                    help="项目根目录；也可用环境变量 SOLODRAMA_WORKSPACE 指定")
    ap.add_argument("--stage", default="all",
                    choices=["align", "cues", "ass", "master", "upscale", "render", "all"])
    ap.add_argument("--preview", type=int, default=0, metavar="N",
                    help="只用前 N 段做快速预览")
    ap.add_argument("--soft", action="store_true", help="软字幕（不重编视频）")
    ap.add_argument("--force-align", action="store_true",
                    help="忽略缓存重跑对齐（默认也会自动重建 script_estimate 伪对齐）")
    ap.add_argument("--no-asr-fill", dest="no_asr_fill", action="store_true",
                    help="剧本无台词的镜头不再用 ASR 补字幕（默认补，标 asr-unscripted 供复核）")
    ap.add_argument("--no-trim", dest="no_trim", action="store_true",
                    help="不按声学能量收紧字幕首尾（默认收紧，去头尾静音）")
    ap.add_argument("--force-upscale", action="store_true", help="忽略缓存重跑高清放大")
    ap.add_argument("--burn", action="store_true",
                    help="放完直接烧字幕（默认跑到放大母版就停下，等用户决定要不要字幕）")
    ap.add_argument("--no-upscale", action="store_true",
                    help="关掉高清放大：仍是旧行为（1440p 母版直接烧字幕）")
    ap.add_argument("--no-normalize", dest="no_normalize", action="store_true",
                    help="不把成片归一化到交付规格（1080×1920 / SAR 1:1）。"
                         "★ 默认归一化：H3 出片是 672×1216（21:38≠9:16），不归一化会被平台判「画面有黑边」")
    ap.add_argument("--lang", default=None)
    ap.add_argument("--no-bgm", dest="no_bgm", action="store_true",
                    help="不混 BGM（默认检测到 <ep>_bgm-plan.json 就在母版拼接时混音；2026-11-01）")
    ap.add_argument("--no-cover", dest="no_cover", action="store_true",
                    help="母版不加首帧封面（默认用 09-发行/封面/cover_9x16*.png 做 0.8s 片头）")
    ap.add_argument("--from-srt", dest="from_srt", default=None, metavar="PATH",
                    help="用外部 SRT 作为字幕时间源（例如剪映「识别字幕」后导出的字幕文件）；"
                         "给了它就不跑 whisper/CTC 对齐 —— 外部 ASR 已经定过时间，别再覆盖")
    ap.add_argument("--srt-axis", dest="srt_axis", default="master",
                    choices=["master", "shots"],
                    help="外部 SRT 的时间轴：master=工程/成片轴（含封面片头，默认，会自动减回）；"
                         "shots=镜头轴（第一段画面=0，不减）")

    args = ap.parse_args()
    args.ep = canon_ep(args.ep)          # 26 / EP26 / ep026 → ep26（否则路径对不上）

    if not args.workspace:
        raise SystemExit(
            "找不到短剧工作区。请二选一：\n"
            "  ① --workspace \"<项目根目录>\"\n"
            "  ② 设环境变量：$env:SOLODRAMA_WORKSPACE = \"<项目根目录>\"  （PowerShell）\n"
            "工作区的标志物是 <项目根>/layout.json（新布局）或 <项目根>/video-pipeline/（旧布局）。")
    ws = os.path.abspath(args.workspace)
    cfg = load_config(ws)
    # ★ 反馈 P2-13：单一模板硬校验（两套纵向坐标 = 40 集返工的根因）
    _tpl_errs, _tpl_warns = check_single_template(cfg)
    for _w in _tpl_warns:
        sys.stderr.write("[WARN] %s\n" % _w)
    if _tpl_errs:
        for _e in _tpl_errs:
            sys.stderr.write("[FAIL] %s\n" % _e)
        sys.stderr.write("       修好后再跑；否则 40 集要全量重渲染一次（本项目实测 75 分钟本地 GPU）。\n")
        return 2
    if args.lang:
        cfg["default_language"] = args.lang
    subs_dir = os.path.join(out_dir_of(ws), "subs", args.ep)
    os.makedirs(subs_dir, exist_ok=True)

    # ---- 高清放大：决定「字幕最终烧在多大的画布上」------------------------
    up_mod, up_cfg, up_err = load_upscale(ws)
    up_on = (not args.no_upscale) and bool(up_mod) and bool(up_cfg) \
        and bool(up_cfg.get("enabled", True))
    if up_on and up_err:
        print("  ⚠ 高清放大不可用，按 1440p 处理：%s" % up_err)
        up_on = False

    t_start = time.time()
    segs, missing = episode_segments(ws, args.ep)
    if args.preview:
        segs = segs[:args.preview]
    if not segs:
        raise SystemExit("没有找到 %s 的成片段落" % args.ep)
    lines = dialogue_lines(ws, args.ep)

    src_w, src_h = video_dims(cfg["tools"]["ffprobe"], segs[0]["file"])
    if up_on:
        cw, ch, cf = up_mod.target_size({"width": src_w, "height": src_h}, up_cfg["target"])
    else:
        cw, ch, cf = cfg["canvas"]["width"], cfg["canvas"]["height"], 1.0
    canvas = (cw, ch)

    report = {"episode": args.ep, "workspace": ws, "segments": len(segs),
              "missing_segments": missing,
              "segments_used": [s["shot_id"] for s in segs],
              "config": {"language": cfg["default_language"]},
              "upscale": {"enabled": up_on, "target": "%dx%d" % canvas,
                          "factor": round(cf, 4),
                          "model": (up_cfg or {}).get("model", {}).get("name")}}

    print("集号 %s ｜ 段数 %d ｜ 缺失 %d" % (args.ep, len(segs), len(missing)))
    if missing:
        print("  ⚠ 缺失段：%s" % ", ".join(missing))
    # ★ 2026-10-30：把「放大目标」与「交付规格」分开打印。
    #   此前只打「字幕画布 2560x4632」，而最终交付其实是 1080×1920 —— 名字对不上，
    #   排查时容易误以为交付了 4K。
    _dw, _dh = int(cfg["canvas"]["width"]), int(cfg["canvas"]["height"])
    print("分辨率路线：源 %dx%d → %s → 交付 %dx%d SAR 1:1（%s）"
          % (src_w, src_h,
             ("放大 %dx%d（%s）" % (cw, ch, (up_cfg or {}).get("model", {}).get("name")))
             if up_on else "不放大",
             _dw, _dh,
             "烧字幕时 crop-to-fill 归一化" if not getattr(args, "no_normalize", False)
             else "未归一化（--no-normalize）"))

    if args.stage in ("align", "all"):
        n, sk, rebuilt, filled = stage_align(
            ws, args.ep, cfg, segs, lines, subs_dir, force=args.force_align,
            asr_fill=not args.no_asr_fill, trim=not args.no_trim)
        print("① 对齐：新跑 %d 段 ／ 命中缓存 %d 段 ／ 重建伪对齐 %d 段 ／ ASR 补位 %d 段"
              % (n, sk, rebuilt, filled))
        report["aligned_segments"] = n + sk + rebuilt + filled
        report["align_cached"] = sk
        report["align_rebuilt_estimate"] = rebuilt
        report["align_asr_fill"] = filled

    # ★ 2026-10-22：把「每段到底用的是 CTC、whisper 还是估算」写进报告 —— **任何 stage 都写**。
    #   事故里没人发现"整集字幕是估算的"，就是因为这个事实在任何地方都看不见。
    #   放在 align 分支外面：`--stage render`（不重跑对齐）同样需要这份账。
    am = {}
    for _s in segs:
        _p = os.path.join(subs_dir, "align", _s["shot_id"] + ".json")
        if os.path.isfile(_p):
            try:
                am[_s["shot_id"]] = load_json(_p).get("method")
            except Exception:                                               # noqa: BLE001
                am[_s["shot_id"]] = "unreadable"
        elif lines.get(_s["shot_id"]):
            am[_s["shot_id"]] = "missing"
    report["align_methods"] = am
    _est = [k for k, v in am.items() if v not in REAL_ALIGN_METHODS]
    if _est:
        report["warnings_align"] = (
            "%d 段仍是估算或缺失时间（%s）—— 字幕位置不可信，"
            "先确认 aligner / whisper-cli 路径可用" % (len(_est), ", ".join(_est[:6])))
        print("  ⚠ %s" % report["warnings_align"])

    if args.stage in ("cues", "all", "ass", "render"):
        if getattr(args, "from_srt", None):
            # ★ 2026-11-10：外部字幕（剪映「识别字幕」后导出）作为时间源。
            #   走这条路时**不跑** whisper/CTC —— 用户已经用更强的 ASR 定过时间，
            #   再用本仓库的退化对齐覆盖它，等于把好的换回坏的。
            _cov_s, _cmsg = cover_lead_seconds(
                ws, args.ep, cfg, enabled=not getattr(args, "no_cover", False))
            _axis = getattr(args, "srt_axis", "master") or "master"
            _off = 0.0 if _axis == "shots" else _cov_s
            cues, warn, total = load_cues_from_srt(
                args.from_srt, cfg, segs, offset_s=_off)
            cps = {"cps_hard": [], "cps_soft": [], "cps_outliers": [], "coverage_gaps": []}
            print("②.0 时间源：外部 SRT（轴=%s，减片头 %.2fs；%s）" % (_axis, _off, _cmsg))
        else:
            cues, warn, total, cps = build_cues(ws, args.ep, cfg, segs, lines, subs_dir)

        # ★ 短字幕修整（2026-10-07）：时长 < 0.3s 的条目（真实发音极短，如
        #   ep81「誰？」0.08s）优先向后延长，撞到下一条起点再向前延伸，
        #   保证 end-start >= 0.3 且不与相邻条重叠——0.08s 的字幕人眼根本看不到。
        cues.sort(key=lambda c: (c["start"], c["end"]))
        for _i, _c in enumerate(cues):
            if _c["end"] - _c["start"] >= 0.3:
                continue
            _nxt = cues[_i + 1]["start"] if _i + 1 < len(cues) else _c["end"] + 1.0
            _prv = cues[_i - 1]["end"] if _i > 0 else 0.0
            _c["end"] = min(max(_c["end"], _c["start"] + 0.3),
                            max(_nxt, _c["start"] + 0.3))
            if _c["end"] - _c["start"] < 0.3:
                _c["start"] = max(_prv, round(_c["end"] - 0.3, 3))

        dump_json(os.path.join(subs_dir, "cues.json"), cues)
        print("② 字幕条目：%d 条 ｜ 覆盖 %.1fs" % (len(cues), total))
        # ★ 2026-10-30：cues 为空时**不许烧成片**。此前会静默写一份空 ASS、
        #   烧出一条无字幕视频，文件名还叫 `_subbed.mp4` —— 和「已经加过字幕」长得一模一样，
        #   于是被 release_export 当合格成片导出，直到平台驳回「画面中不包含字幕」。
        #   实测踩点：`--stage render` 不跑对齐，而 align/*.json 缺失时 build_cues 返回空列表。
        if not cues:
            _why = ("本集字幕条目为 0（build_cues 返回空）。常见原因：\n"
                    "  ① align/<shot>.json 不存在 —— `--stage render` 不会自动对齐，先跑 `--stage align`\n"
                    "  ② 剧本台词没解析到 —— 检查 03-剧本 里 <d> 台词段与 shot 编号是否对得上\n"
                    "  ③ 对齐器/whisper 路径不可用 —— 时间拿不到真对齐，宁可不出片也不许用估算糊过去")
            if args.stage == "render" or (args.stage == "all" and args.burn):
                raise SystemExit("断言失败：%s\n%s" % ("不能烧一条空字幕冒充成片", _why))
            print("  ⚠ %s" % _why.replace("\n", "\n  "))
        for w in warn:
            print("  ⚠ %s" % w)
        report["cues"] = len(cues)
        report["timeline_seconds"] = round(total, 3)
        report["warnings"] = warn
        report["cps_check"] = cps
        # ★ 语速断言：字/秒超过硬上限 = 对齐错位的铁证（不是"语速快"）
        if cps["cps_hard"]:
            _lc = cfg["languages"][cfg["default_language"]]
            raise SystemExit(
                "断言失败：%d 条字幕语速超过生理上限（>%.1f 字/秒），对齐必定错位。例：%s\n"
                "  排查：① 该段音频是否真的说了这句（用 whisper 独立转写核对）\n"
                "        ② 顺序约束是否失效（前一句终点被推太后，把后一句窗口压没）"
                % (len(cps["cps_hard"]), _lc.get("cps_impossible", 20.0),
                   cps["cps_hard"][0]))
        # 断言：时间必须合法（硬底线 0.3s；低于目标时长只告警，因为下一句紧跟时无法延长。
        # 0.3 口径：CTC 对齐出的真实短应答「好。」实测 0.32s（2026-10-07 ep01），
        # 0.4 会误杀——对齐成功的真实语速不该被断言判死；0.3 以下才真的看不清）
        HARD_MIN = 0.3
        bad = [c for c in cues if c["start"] < 0 or c["end"] > total + 0.5
               or c["end"] - c["start"] < HARD_MIN]
        if bad:
            raise SystemExit("断言失败：%d 条字幕时间非法，例：%s" % (len(bad), bad[0]))

    # ★ 2026-11-10：字幕时间必须对齐「母版有没有封面片头」
    #   cues 的时间从第一段画面算起，母版前面却可能压着 0.8s 封面。旧实现不加偏移 ⇒
    #   有封面时每条字幕都早 0.8s，而所有断言都通过（它们只比较 cues 自己）。
    #   这里先探一次封面，把真实偏移算出来，供 ASS / 渲染自检 / 剪映工程共用。
    cover_lead_s = 0.0
    if args.stage in ("ass", "all", "render"):
        cover_lead_s, _cmsg = cover_lead_seconds(
            ws, args.ep, cfg, enabled=not getattr(args, "no_cover", False))
        if cover_lead_s > 0:
            print("③.0 封面片头 %.2fs ⇒ 字幕整体后移同量（%s）"
                  % (cover_lead_s, os.path.basename(_cmsg)))
        else:
            print("③.0 无封面片头，字幕不偏移（%s）" % _cmsg)

    ass = os.path.join(subs_dir, "%s.ass" % args.ep)
    if args.stage in ("ass", "all", "render"):
        info = write_ass(cues, cfg, ass, canvas=canvas, offset_s=cover_lead_s)
        print("③ ASS：%s" % ass)
        if info.get("anchor") == "ratio":
            print("   字体=%s 字号=%dpx(%s) 落点=视觉中心 %s(y=%dpx) 块高=%dpx "
                  "下沿距底=%dpx 左右=%dpx 画布=%s 条目=%d"
                  % (info["font"], info["font_size_px"], _pct_label(info["font_size_pct"]),
                     info["anchor_label"], info["center_y"], info["block_h_px"],
                     info["bottom_px"], info["margin_lr_px"], info["canvas"], info["cues"]))
            if info.get("anchor_clamped"):
                print("      ⚠ 6:4 落点被安全区上顶（配置 anchor_top 偏低/画布过矮）")
        else:
            print("   字体=%s 字号=%dpx(%s) 底部间距=%dpx(%s) 左右=%dpx 画布=%s 条目=%d"
                  % (info["font"], info["font_size_px"], _pct_label(info["font_size_pct"]),
                     info["margin_v_px"], _pct_label(info["margin_v_pct"]),
                     info["margin_lr_px"],
                     info["canvas"], info["cues"]))
        print("   字号依据=%s ｜ 文本框宽=%dpx(%.1f%%) ｜ 安全区：底≥%dpx 宽≤%.0f%%"
              % (info["font_size_by"], info["text_w_px"], info["text_w_pct"],
                 info["safe_area"]["min_bottom_px"], info["safe_area"]["max_text_width_pct"]))
        report["ass"] = info
        qa = qa_safe_area(ass, cfg)
        print("   ★ 安全区断言：%s" % ("✅ 通过" if qa["pass"] else "❌ " + "；".join(qa["failures"])))
        report["ass_safe_area"] = qa
        if not qa["pass"]:
            raise SystemExit("断言失败（字幕安全区）：%s" % "；".join(qa["failures"]))

    master = None
    if args.stage in ("master", "all", "render", "upscale"):
        master = stage_master(ws, args.ep, cfg, segs, subs_dir,
                              cover=not getattr(args, "no_cover", False),
                              bgm=not getattr(args, "no_bgm", False))
        fr = ffprobe_frames(cfg["tools"]["ffprobe"], master)
        print("④ 母版（无损拼接）：%s ｜ %d 帧" % (master, fr))
        report["master"] = {"path": master, "frames": fr}

    # ---- ⑤ 高清放大（合并之后、烧字幕之前）--------------------------------
    # ★ 2026-10-22：产物名如实写分辨率（<ep>_master_1080x1920.mp4）。
    #   旧名 `_master_2k` 与实际分辨率（1080P）不符，是"以为已经出过 2K"的歧义源；
    #   `upscaled_path()` 仍能读回旧名，老项目不用迁移。
    if up_mod is not None:
        hi_res = up_mod.upscaled_path(subs_dir, args.ep, (cw, ch))
    else:
        hi_res = os.path.join(subs_dir, args.ep + "_master_%dx%d.mp4" % (cw, ch))
    up_result = None
    want_up = up_on and args.stage in ("upscale", "all", "render")
    if want_up:
        if master is None and not os.path.exists(hi_res):
            raise SystemExit("要先有母版才能放大：%s 不存在（先跑 --stage master）" % hi_res)
        print("⑤ 高清放大（Topaz %s）：%dx%d → %dx%d …"
              % (up_cfg["model"]["name"], src_w, src_h, cw, ch))
        up_result = up_mod.upscale_episode(ws, args.ep, up_cfg,
                                           force=args.force_upscale, quiet=False)
        report["upscale_result"] = up_result
        if not up_result.get("ok"):
            raise SystemExit(
                "高清放大失败：%s\n%s"
                % (up_result.get("error") or "自检未通过",
                   up_result.get("hint") or
                   "  排查：① Topaz 模型权重是否在本机（脚本会打印探测到的目录）\n"
                   "        ② 想先跳过放大：--no-upscale；只想要分辨率数字变大：--fallback-lanczos"))
        v = up_result.get("verify") or {}
        # 放大真正落盘的那个路径（可能命中旧名缓存）
        hi_res = up_result.get("dst") or hi_res
        if up_result.get("cached"):
            print("   命中缓存，跳过重跑")
        else:
            print("   完成：%.1fs ｜ %.2f 帧/秒 ｜ %s"
                  % (up_result.get("elapsed_s") or 0, up_result.get("avg_fps") or 0,
                     hi_res))
        for c in v.get("checks", []):
            print("   %s %s —— %s" % ("[OK]" if c["ok"] else "[FAIL]", c["name"], c["detail"]))
        report["upscale_path"] = hi_res

    # 字幕烧在哪个视频上：有放大版就用放大版
    base_video = master
    if up_on and os.path.exists(hi_res) and args.stage in ("upscale", "all", "render"):
        base_video = hi_res

    # ★ 2026-11-01：BGM 已并入母版拼接（stage_master 第 ③ 步），这里**不再混音**。
    #   此前挂在烧字幕前，导致「放大后的视频再混一次音频」，且 master 与 mix 两个产物
    #   谁才是母版说不清 —— 现在 `<ep>_master.mp4` 就是带 BGM 的母版，只有一个名字。

    # --stage all 的收尾语义：
    #   * 开了放大 → 跑到放大母版就【停】，等用户回答要不要字幕（这是用户明确要求的停点）
    #   * --burn   → 不停，直接烧
    #   * --no-upscale → 回到旧行为（一条链跑到底，1440p 直接烧），别让老脚本突然"什么都没出"
    do_render = args.stage == "render" or (args.stage == "all" and (args.burn or not up_on))
    if do_render:
        if base_video is None:
            raise SystemExit("没有可烧字幕的母版（先跑 --stage master 或 --stage upscale）")
        # ★ 画布必须等于【真的要烧的那条视频】的分辨率，否则 libass 会拉伸/偏移字幕
        # ★ 2026-10-30：先做交付规格归一化（crop-to-fill），再按归一化结果写 ASS。
        #   顺序不能反：ASS 的 PlayRes 一旦按 2560×4632 的放大母版写好，烧到 1080×1920
        #   上虽然 libass 会按比例缩放，但安全区断言的口径就与实际不一致了。
        _rewrite = False
        if not getattr(args, "no_normalize", False):
            # 目标一律取**交付画布**（config.subtitle.json 的 canvas），
            # 不是放大目标 —— 放大到 2560×4632 只是为了超采样，交付仍须 1080×1920。
            base_video, _spec_msg = ensure_delivery_spec(
                cfg, base_video, subs_dir, args.ep,
                target=(cfg["canvas"]["width"], cfg["canvas"]["height"]))
            print("  ⑤.9 %s" % _spec_msg)
            canvas = video_dims(cfg["tools"]["ffprobe"], base_video)
            report["delivery_spec"] = {"canvas": "%dx%d" % canvas, "note": _spec_msg}
            _rewrite = True
        real = video_dims(cfg["tools"]["ffprobe"], base_video)
        if _rewrite or real != canvas:
            if not _rewrite:
                print("   ⚠ 母版实际 %dx%d ≠ 预期 %dx%d，按实际分辨率重写 ASS"
                      % (real[0], real[1], canvas[0], canvas[1]))
                canvas = real
            info2 = write_ass(cues, cfg, ass, canvas=canvas, offset_s=cover_lead_s)
            report["canvas_corrected"] = "%dx%d" % canvas
            qa2 = qa_safe_area(ass, cfg)
            _y = ("落点 %s y=%dpx" % (info2["anchor_label"], info2["center_y"])
                  if info2.get("anchor") == "ratio" else "距底=%dpx" % info2["margin_v_px"])
            print("   重写后几何：字号=%dpx(%s) %s 文本框=%dpx(%.1f%%) ★ 安全区断言：%s"
                  % (info2["font_size_px"], info2["font_size_by"], _y,
                     info2["text_w_px"], info2["text_w_pct"],
                     "✅ 通过" if qa2["pass"] else "❌ " + "；".join(qa2["failures"])))
            report["ass_safe_area"] = qa2
            if not qa2["pass"]:
                raise SystemExit("断言失败（字幕安全区，按实际分辨率重写后）：%s"
                                 % "；".join(qa2["failures"]))
        out = os.path.join(subs_dir, "%s_%s.mp4" % (args.ep, "softsub" if args.soft else "subbed"))
        # ★ 不许静默覆盖更好的一版：已有成片的分辨率比这次要高时，先改名留存再渲染
        #   （踩点：先跑了放大版，后来又用 --no-upscale 跑一次低分辨率，高分辨率成片就被盖掉了）
        if os.path.exists(out):
            try:
                old = video_dims(cfg["tools"]["ffprobe"], out)
            except Exception:                 # ★ SystemExit 之外还有 RuntimeError：
                old = canvas                  #   被杀进程留下的损坏 mp4（moov 缺失）
                print("   ⚠ 旧成片读取失败（疑似损坏）→ 视为同分辨率，直接重烧覆盖")
            if old[0] * old[1] > canvas[0] * canvas[1]:
                kept = os.path.join(subs_dir, "%s_%s_%dx%d.mp4"
                                    % (args.ep, "softsub" if args.soft else "subbed",
                                       old[0], old[1]))
                if not os.path.exists(kept):
                    os.replace(out, kept)
                    print("   ⚠ 原成片分辨率更高（%dx%d），已改名留存：%s"
                          % (old[0], old[1], os.path.basename(kept)))
                else:
                    print("   ⚠ 原有更高分辨率成片已存在于 %s，本次直接覆盖同名文件"
                          % os.path.basename(kept))
        stage_render(cfg, base_video, ass, out, soft=args.soft)
        fr = ffprobe_frames(cfg["tools"]["ffprobe"], out)
        exp = ffprobe_frames(cfg["tools"]["ffprobe"], base_video)
        ok = (fr == exp) if exp else None
        print("⑥ 成片：%s ｜ %d 帧 ｜ 与母版一致：%s" % (out, fr, ok))
        if exp and not ok:
            raise SystemExit("断言失败：成片帧数 %d != 母版 %d" % (fr, exp))
        report["output"] = {"path": out, "frames": fr, "frames_match": ok,
                            "base": base_video, "canvas": "%dx%d" % canvas}

        if not args.soft:
            v = verify_render(cfg, base_video, out, cues, subs_dir, canvas=canvas,
                              offset_s=cover_lead_s)
            report["verify_render"] = v
            if "skipped" in v:
                print("⑦ 渲染自检：跳过（%s）" % v["skipped"])
            else:
                b = v["best"]
                print("⑦ 渲染自检（字幕带 y=%d–%d）："
                      % (v["band_top_px"], v.get("band_bottom_px", v["band_top_px"])))
                print("   t=%.2fs 「%s」  字幕带差异=%.1f  画面其余差异=%.1f  近白像素 %d→%d (增 %+d)"
                      % (b["t"], b["text"], b["diff_band"], b["diff_rest"],
                         b["white_master"], b["white_subbed"], b["white_gain"]))
                print("   ⇒ %s" % ("✅ 字幕确实画出来了" if v["pass"]
                                   else "❌ 未检出字幕（渲染可能失败）"))
                if not v["pass"]:
                    raise SystemExit("断言失败：渲染自检未通过")
        report["elapsed_s"] = round(time.time() - t_start, 1)
        print("\n✅ 完成，用时 %.1fs" % report["elapsed_s"])
        print("   看片：%s" % out)

    # ---- 停在「放大母版已就绪」，把决定权交回用户 ---------------------------
    if args.stage == "all" and up_on and not args.burn and os.path.exists(hi_res):
        print("")
        print("=" * 74)
        print(" %dx%d 母版已就绪（无字幕）：%s" % (cw, ch, hi_res))
        print("")
        print(" 要不要加字幕？（这一步要你确认，因为烧字幕要重编码一遍，约 1–3 分钟）")
        print("   要 → python scripts/subtitle.py --workspace \"%s\" --ep %s --stage render"
              % (ws, args.ep))
        print("   不要 → 直接交付上面那个 mp4")
        print("")
        print(" 为什么先放大后烧字幕：烧字幕必然重编码，若先烧再放大，")
        print(" 字幕会被 AI 超分当成画面纹理一起「重绘」（描边发糊、笔画变形）。")
        print("=" * 74)

    dump_json(os.path.join(subs_dir, "report.json"), report)
    print("   报告：%s" % os.path.join(subs_dir, "report.json"))


if __name__ == "__main__":
    main()
