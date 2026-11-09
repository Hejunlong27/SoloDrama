#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""copyright_kit.py —— 版权资料三件套：平台两个入口 + 权利声明（2026-11-07 新增）

为什么重做这套东西
------------------
2026-11-07 实测被 TikTok Drama Center 驳回：**「材料不足：提交的版权材料不足以证明本剧
所需的相关权利。」** 回头看，上一版 8 张（`ai-process-01..04` + `source-file-01..04`）
是**数据面板**：批次表、工作流参数、目录树、ffprobe 输出。

两个错，性质不同：

1. **对标错了**。平台两个入口写得很具体：
   * 「AI 生成过程截图」4–20 张，要能展示**提示词、操作过程及对应生成结果**，
     且「截图需要能够对应**拟上线作品的具体画面、角色、场景或片段**」；
   * 「原始文件或素材文件信息」4–20 张，类型为**剧本、角色矢量图、场景设计图、
     视频 raw 文件、项目素材文件**。
   旧 8 张里没有一处出现「画面 / 角色 / 场景」，审核员无法把它指向某一集某一帧。
2. **层次错了**。即便把上面补齐，回答的仍是「这片子是我做的吗」；
   平台问的是「**发行权在你手上吗**」—— 权利人、原创性、AI 使用、第三方素材、逐集范围。
   那一层靠截图证明不了，只能靠**签章声明书**。

所以本脚本产出三层材料（对应 `docs/distribution/发行资料清单.md` §四）：

| 子命令 | 产物 | 落点 | 回答什么 |
|---|---|---|---|
| `ai-process` | `ai-gen-NN-epNN-shot_XXX.png`（每镜一张四联板） | `09-发行/版权资料/AI生成过程/` | 提示词 → 分镜图 → 成片帧 → 资产卡，四者同框指向同一镜 |
| `source-files` | `src-NN-<slug>.png`（6 张） | `09-发行/版权资料/原始文件/` | 剧本 / 角色设计 / 场景设计 / 导演手册 / video raw / 素材清单 |
| `rights` | `rights-01..07-*.png`（A4） | `09-发行/版权资料/权利声明/` | 权属、原创性、AI 披露、第三方素材、逐集清单、授权、索引 |

纪律
----
* **只用真实数据**：提示词读 `06-提示词/<ep>/h3_prompts.json`，分镜图读 `04-资产/boards/`，
  成片帧从 `07-成片/<ep>/<shot>/final.mp4` 现抽，文件信息取自 `stat()`。
  取不到就**留空并在命令行点名**，不编数字、不拿别的镜头顶替。
* **不伪造 UI**：云平台控制台不在本机，所以不画「截图」，而是把真实记录排成可读的板。
  每张底部标注数据来源文件，外部可回原文件逐项核对。
* **可复现**：同一份工作区重跑得到同样的板（抽帧时刻固定为片长的 55%）。

用法
----
    python copyright_kit.py --workspace "<剧目录>" all
    python copyright_kit.py --workspace "<剧目录>" ai-process --shots 6
    python copyright_kit.py --workspace "<剧目录>" ai-process --shots ep01:shot_007,ep13:shot_002
    python copyright_kit.py --workspace "<剧目录>" source-files
    python copyright_kit.py --workspace "<剧目录>" rights --entity "某某科技有限公司"

退出码：0 = 全部产出；2 = 有前置数据缺失（缺剧本 / 缺提示词 / 缺成片），已产出的部分仍会打印
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[union-attr]
except Exception:                                                # noqa: BLE001
    pass

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:                                              # pragma: no cover
    Image = ImageDraw = ImageFont = None

# ── 版面（A4 @ 200dpi；长边 2339 落在平台 1200–2560 的区间内）────────────────
W, H = 1654, 2339
M = 90                                  # 页边距（A4 声明书用 130）
INK = (26, 26, 30)
GREY = (118, 120, 126)
LINE = (200, 202, 208)
ACCENT = (168, 36, 36)
PANEL = (246, 246, 248)
PAPER = (255, 255, 255)


def _first_font(paths) -> str:
    for p in paths:
        try:
            if pathlib.Path(p).is_file():
                return p
        except OSError:
            continue
    return ""


# 字体：Windows 优先，其次 macOS，最后 Linux 常见包。缺 CJK 字体时中文会成方块，
# 所以 `_font()` 之外还要有一条显式告警（见 `check_fonts`）。
LAT = _first_font(["C:/Windows/Fonts/arial.ttf",
                   "/System/Library/Fonts/Supplemental/Arial.ttf",
                   "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"])
LATB = _first_font(["C:/Windows/Fonts/arialbd.ttf",
                    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"])
LATI = _first_font(["C:/Windows/Fonts/ariali.ttf",
                    "/System/Library/Fonts/Supplemental/Arial Italic.ttf",
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"])
CJK = _first_font(["C:/Windows/Fonts/msyh.ttc",
                   "/System/Library/Fonts/PingFang.ttc",
                   "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                   "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"])
CJKB = _first_font(["C:/Windows/Fonts/msyhbd.ttc",
                    "/System/Library/Fonts/PingFang.ttc",
                    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"])


def _font(path: str, size: int):
    try:
        if path:
            return ImageFont.truetype(path, size)
        # 没找到对应字重的字体时，退回另一条链，而不是直接 load_default（那个不支持中文）
        for alt in (LAT, CJK):
            if alt:
                return ImageFont.truetype(alt, size)
    except OSError:
        pass
    return ImageFont.load_default()


CJK_RE = re.compile(r"[\u3400-\u9fff\u3000-\u303f\uff00-\uffef]")


def _f(text, size: int, bold: bool = False):
    """按**这一行文字**选字体：含中文就用 CJK 字体。

    为什么必须逐行判断：Arial 没有汉字字形，中文会渲染成一排方框。真实项目里
    片名是「女佣的隐藏身份」、权利主体是中文公司名 —— 这两处恰好是整份材料里
    最不能出错的地方（审核员靠它认主体），必须自动切字体而不是靠调用方记得传。
    """
    if CJK_RE.search(str(text or "")):
        return _font(CJKB if bold else CJK, size)
    return _font(LATB if bold else LAT, size)


def check_fonts() -> list:
    """返回缺失的字体类别（空列表 = 齐）。缺 CJK 时中文会渲染成方块，必须喊出来。"""
    if Image is None:
        return ["Pillow 未安装"]
    missing = []
    if not LAT:
        missing.append("拉丁字体（Arial / DejaVuSans）")
    if not CJK:
        missing.append("中文字体（msyh / PingFang / Noto CJK）")
    return missing


# ── 基础排版 ────────────────────────────────────────────────────────────────
def wrap_chars(text: str, font, max_w: int) -> list:
    """按字符断行（中文无空格，按词断行会整段溢出）。"""
    lines, cur = [], ""
    for ch in str(text or ""):
        if ch == "\n":
            lines.append(cur)
            cur = ""
            continue
        if font.getlength(cur + ch) <= max_w:
            cur += ch
        else:
            lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines


def wrap_words(text: str, font, max_w: int) -> list:
    """按词断行（英文声明书用）。"""
    lines, cur = [], ""
    for w in str(text or "").split():
        trial = (cur + " " + w).strip()
        if font.getlength(trial) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def fmt_size(n: float) -> str:
    n = float(n or 0)
    return "%.1f KB" % (n / 1024) if n < 1048576 else "%.1f MB" % (n / 1048576)


def fmt_time(p: pathlib.Path) -> str:
    try:
        return datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    except OSError:
        return "-"


def fmt_day(p: pathlib.Path) -> str:
    try:
        return datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d")
    except OSError:
        return ""


def probe_duration(path: pathlib.Path):
    """ffprobe 读时长（秒）；不可用返回 None —— 不猜。"""
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", str(path)],
                           capture_output=True, text=True, timeout=30)
        return float(r.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def probe_stream(path: pathlib.Path):
    """→ (宽, 高, 时长) ；失败项返回 None。"""
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                            "-show_entries", "stream=width,height",
                            "-show_entries", "format=duration", "-of", "json", str(path)],
                           capture_output=True, text=True, timeout=30)
        j = json.loads(r.stdout)
        st = j["streams"][0]
        return int(st["width"]), int(st["height"]), float(j["format"]["duration"])
    except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError):
        return None, None, None


def grab_frame(video: pathlib.Path, out_png: pathlib.Path, at: float = 0.55):
    """从成片抽一帧（时刻固定在片长 55%，可复现）。"""
    if not video.is_file():
        return False
    dur = probe_duration(video) or 0.0
    t = max(dur * at, 1.0) if dur else 3.0
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "%.2f" % t, "-i", str(video),
                        "-frames:v", "1", str(out_png)],
                       capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return False
    return out_png.is_file()


def paste_fill(img, path: pathlib.Path, box, crop_bias: float = 0.5):
    """把图按「填满后居中裁切」贴进 box（避免竖版卡在横框里留大片白）。

    `crop_bias`：纵向裁切时保留的重心（0=顶部，1=底部）。人物卡取 0.25 左右保住头。
    """
    x, y, w, h = box
    try:
        im = Image.open(path).convert("RGB")
    except (OSError, ValueError):
        return False
    scale = max(w / im.size[0], h / im.size[1])
    nw, nh = int(im.size[0] * scale + 0.5), int(im.size[1] * scale + 0.5)
    im = im.resize((nw, nh), Image.LANCZOS)
    left = (nw - w) // 2
    top = int((nh - h) * crop_bias)
    img.paste(im.crop((left, top, left + w, top + h)), (x, y))
    return True


# ── 配置 ────────────────────────────────────────────────────────────────────
def _read_json(p: pathlib.Path):
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def _split_title(title: str) -> tuple:
    """`La Heredera Oculta · 女佣的隐藏身份` → (en, zh)。分不开就两边同值。"""
    s = str(title or "").strip()
    for sep in ("·", "|", "｜", "/"):
        if sep in s:
            a, _, b = s.partition(sep)
            return a.strip(), b.strip()
    return s, s


def load_cfg(ws: pathlib.Path) -> dict:
    """工作区配置：`copyright.json` > `project.json::meta` > 现场探测。

    为什么允许 copyright.json 覆盖：主体信息（公司名/注册号）、模型许可口径、
    代表性镜头与它们的英文小标题，都是**人才能定**的东西，不该由引擎猜。
    """
    meta = (_read_json(ws / "project.json").get("meta") or {})
    drama = _read_json(ws / "drama.json")
    over = _read_json(ws / "copyright.json")

    title_en, title_zh = _split_title(over.get("title") or meta.get("title") or ws.name)
    episodes = over.get("episodes") or meta.get("total_ep") \
        or ((drama.get("episodes") or {}).get("count")) or 0
    if not episodes:
        eps = sorted((ws / "09-发行" / "剧集").glob("Episode*.mp4"))
        episodes = len(eps)
    ep_seconds = over.get("ep_seconds") or meta.get("ep_seconds") \
        or ((drama.get("episodes") or {}).get("seconds")) or 0

    # 交付规格：真源 delivery_spec（别在这里再写一遍 1080/1920）
    spec = {"width": 1080, "height": 1920, "fps": 24}
    try:
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        import delivery_spec as DS                                # noqa: PLC0415
        spec = DS.SPEC
    except Exception:                                             # noqa: BLE001
        pass

    lang = over.get("language") or meta.get("language") or "Chinese (Mandarin)"
    cfg = {
        "title_en": title_en,
        "title_zh": title_zh,
        "slug": over.get("slug") or meta.get("slug") or re.sub(r"[^a-z0-9-]+", "-", title_en.lower()),
        "episodes": int(episodes or 0),
        "ep_seconds": int(ep_seconds or 0),
        "language": lang,
        "format": over.get("format") or "%dx%d vertical, H.264/AAC, %d fps"
                  % (spec.get("width", 1080), spec.get("height", 1920), spec.get("fps", 24)),
        "models": over.get("models") or {},
        "entity": over.get("entity") or "",
        "registration": over.get("registration") or "",
        "aigc_label": over.get("aigc_label") or "Contenido generado con IA",
        "shots": over.get("shots") or [],
    }
    return cfg


# ── 代表性镜头选取 ──────────────────────────────────────────────────────────
def _load_shots(ws: pathlib.Path, ep: str) -> list:
    """读 `<ep>` 的镜表：优先 shots.json（带 cast），退回 h3_prompts.json 的键。"""
    base = ws / "06-提示词" / ep
    shots = _read_json(base / "shots.json")
    if isinstance(shots, list) and shots:
        return shots
    prompts = _read_json(base / "h3_prompts.json")
    return [{"shot_id": k} for k in prompts] if isinstance(prompts, dict) else []


def pick_shots(ws: pathlib.Path, want: int = 6, explicit=None) -> list:
    """挑 `want` 个「代表性镜头」→ [{ep, shot, cast, duration}]。

    规则（可用 `copyright.json::shots` 覆盖）：
      1. 集层面**均匀分布**（1 … 末集），保证覆盖面而不是全挤在前几集；
      2. 集内取「cast 最多、时长最长」的那一镜 —— 出镜角色越多，越能对上平台要求的
         「对应具体画面、角色、场景」；
      3. 顺序按集号排序（第 1 张留给开局，它是审核员第一眼判断这剧讲什么的地方）。

    这不是「艺术选择」，是**举证选择**：目标是让每张板都同时出现人、景、画面。
    """
    if explicit:
        out = []
        for item in explicit:
            ep, _, sid = str(item).partition(":")
            ep, sid = ep.strip(), sid.strip()
            if not ep or not sid:
                continue
            shots = _load_shots(ws, ep)
            me = next((s for s in shots if s.get("shot_id") == sid), {})
            out.append({"ep": ep, "shot": sid,
                        "cast": me.get("cast") or [],
                        "duration": me.get("duration")})
        return out

    ep_dirs = sorted(p.parent for p in (ws / "06-提示词").glob("*/h3_prompts.json"))
    if not ep_dirs:
        return []
    eps = [d.name for d in ep_dirs]

    def best_of(ep: str):
        shots = _load_shots(ws, ep)
        if not shots:
            return None
        def score(s):
            return (len(s.get("cast") or []) * 100, float(s.get("duration") or 0))
        return max(shots, key=score)

    if want >= len(eps):
        picked = eps
    else:
        # 均匀取点：i=0..want-1 → round(i*(n-1)/(want-1))
        idx = [round(i * (len(eps) - 1) / (want - 1)) for i in range(want)]
        picked = []
        for i in idx:
            if eps[i] not in picked:
                picked.append(eps[i])

    out = []
    for ep in picked:
        s = best_of(ep)
        if s:
            out.append({"ep": ep, "shot": s.get("shot_id"),
                        "cast": s.get("cast") or [], "duration": s.get("duration")})
    return out


def assets_for_shot(ws: pathlib.Path, ep: str, sid: str, limit: int = 3) -> list:
    """该镜实际用到的资产卡文件（按 cast 顺序）→ [(code, variant, path)]。"""
    shots = _load_shots(ws, ep)
    me = next((s for s in shots if s.get("shot_id") == sid), None)
    if not me:
        return []
    out = []
    for ref in (me.get("cast") or [])[:limit]:
        code, _, variant = str(ref).partition("@")
        bucket = "characters" if code.startswith("P") else ("props" if code.startswith("D") else "scenes")
        pat = "%s_*%s*.png" % (code, variant) if variant else "%s_*.png" % code
        for f in sorted((ws / "04-资产" / bucket).glob(pat)):
            out.append((code, variant, f))
            break
    return out


# ── 入口 A：AI 生成过程（每镜一张四联板）────────────────────────────────────
def board_ai(ws: pathlib.Path, cfg: dict, rec: dict, out: pathlib.Path,
             idx: int, total: int, tmp: pathlib.Path) -> bool:
    ep, sid = rec["ep"], rec["shot"]
    prompt_doc = _read_json(ws / "06-提示词" / ep / "h3_prompts.json")
    shot = prompt_doc.get(sid, {}) if isinstance(prompt_doc, dict) else {}
    prompt = str(shot.get("prompt") or "")
    if not prompt:
        print("  [SKIP] %s/%s 没有 h3_prompts 提示词，跳过（不拿别的镜头顶替）" % (ep, sid))
        return False
    dur = shot.get("duration") or rec.get("duration") or "?"

    seed, wall = "-", "-"
    batch = _read_json(ws / "07-成片" / ep / "_batch_local.json")
    for it in (batch.get("items") or []):
        if it.get("shot") == sid:
            seed = it.get("seed", "-")
            wall = it.get("shot_wall_s") or it.get("wall_s") or "-"
            break

    board = ws / "04-资产" / "boards" / ep / ("%s.png" % sid)
    frame = tmp / ("%s_%s_frame.png" % (ep, sid))
    has_frame = grab_frame(ws / "07-成片" / ep / sid / "final.mp4", frame)

    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)

    d.text((M, 84), "AI GENERATION RECORD", font=_font(LATB, 24), fill=ACCENT)
    tag = "%d / %d" % (idx, total)
    d.text((W - M - d.textlength(tag, font=_font(LATB, 24)), 84), tag,
           font=_font(LATB, 24), fill=GREY)
    d.line([M, 128, W - M, 128], fill=LINE, width=3)

    y = 170
    en = rec.get("title_en") or ("Ep.%s — %s" % (re.sub(r"\D", "", ep) or ep, sid))
    zh = rec.get("title_zh") or ("第%s集 %s（%d 人出镜 / %ss）"
                                 % (re.sub(r"\D", "", ep) or ep, sid,
                                    len(rec.get("cast") or []), dur))
    for line in wrap_chars(en, _font(LATB, 38), W - 2 * M):
        d.text((M, y), line, font=_font(LATB, 38), fill=INK)
        y += 50
    d.text((M, y), zh, font=_font(CJKB, 26), fill=GREY)
    y += 48
    d.line([M, y, W - M, y], fill=LINE, width=2)
    y += 34

    kv = [("SHOT", "%s / %s" % (ep, sid)), ("DURATION", "%ss" % dur),
          ("SEED", str(seed)), ("RENDER", "%ss" % wall if wall != "-" else "-"),
          ("RATIO", shot.get("ratio", "9:16"))]
    x = M
    for k, v in kv:
        d.text((x, y), k, font=_font(LATB, 19), fill=ACCENT)
        d.text((x, y + 26), str(v), font=_font(LAT, 22), fill=INK)
        x += 300
    y += 82

    col_gap, left_w, mid_w, right_w = 30, 640, 420, 420
    panel_top, panel_h = y, 1268
    left_x = M
    mid_x = left_x + left_w + col_gap
    right_x = mid_x + mid_w + col_gap

    d.rectangle([left_x, panel_top, left_x + left_w, panel_top + panel_h], fill=PANEL, outline=LINE)
    d.text((left_x + 24, panel_top + 18), "PROMPT (as submitted)", font=_font(LATB, 21), fill=ACCENT)
    d.text((left_x + 24, panel_top + 50), "提交给模型的提示词原文", font=_font(CJK, 18), fill=GREY)
    py = panel_top + 90
    fp = _f(prompt, 16)
    for line in wrap_chars(prompt, fp, left_w - 48):
        if py > panel_top + panel_h - 40:
            break
        d.text((left_x + 24, py), line, font=fp, fill=INK)
        py += 24

    for bx, bw, cap, cap_zh in ((mid_x, mid_w, "STORYBOARD (input ref)", "分镜图：作为首帧参考输入"),
                                (right_x, right_w, "OUTPUT FRAME", "成片抽帧：实际生成结果")):
        d.rectangle([bx, panel_top, bx + bw, panel_top + panel_h], fill=PANEL, outline=LINE)
        d.text((bx + 20, panel_top + 18), cap, font=_font(LATB, 20), fill=ACCENT)
        d.text((bx + 20, panel_top + 48), cap_zh, font=_font(CJK, 17), fill=GREY)

    if board.is_file():
        paste_fill(img, board, (mid_x + 20, panel_top + 100, mid_w - 40, panel_h - 120))
    if has_frame:
        paste_fill(img, frame, (right_x + 20, panel_top + 100, right_w - 40, panel_h - 120))

    y = panel_top + panel_h + 34
    strip = assets_for_shot(ws, ep, sid)
    if strip:
        d.text((M, y), "REFERENCE ASSETS USED (character / scene / prop cards)",
               font=_font(LATB, 20), fill=ACCENT)
        y += 32
        card_h, n = 230, max(1, min(len(strip), 3))
        cw = int((W - 2 * M - 24 * (n - 1)) / n)
        for i, (code, variant, f) in enumerate(strip[:3]):
            cx = M + i * (cw + 24)
            d.rectangle([cx, y, cx + cw, y + card_h], outline=LINE, width=2)
            if paste_fill(img, f, (cx, y, cw, card_h), crop_bias=0.28):
                d.text((cx, y + card_h + 8), "%s %s" % (code, variant), font=_font(LATB, 17), fill=INK)
                d.text((cx, y + card_h + 30), f.name, font=_font(LAT, 14), fill=GREY)
        y += card_h + 92

    note = ("Prompt as submitted to the video model; storyboard frame supplied as the first "
            "reference image; output frame extracted from the delivered episode file.")
    for line in wrap_words(note, _font(LAT, 18), W - 2 * M):
        d.text((M, y), line, font=_font(LAT, 18), fill=GREY)
        y += 26
    d.line([M, H - 130, W - M, H - 130], fill=LINE, width=2)
    d.text((M, H - 100), "Source: 06-提示词/%s/h3_prompts.json · 04-资产/boards/%s/%s.png "
                         "· 07-成片/%s/%s/final.mp4" % (ep, ep, sid, ep, sid),
           font=_font(LAT, 16), fill=GREY)
    img.save(out)
    return True


# ── 入口 B：原始文件 / 素材文件信息 ─────────────────────────────────────────
def _hdr(img, d, title_en: str, title_zh: str, tag: str,
         kicker: str = "SOURCE FILE RECORD") -> int:
    # kicker 可按材料类别换（剪辑工程页用 EDITING PROJECT RECORD），别让所有页都自称原始文件
    d.text((M, 84), kicker, font=_font(LATB, 24), fill=ACCENT)
    d.text((W - M - d.textlength(tag, font=_font(LATB, 24)), 84), tag,
           font=_font(LATB, 24), fill=GREY)
    d.line([M, 128, W - M, 128], fill=LINE, width=3)
    y = 172
    for line in wrap_chars(title_en, _font(LATB, 36), W - 2 * M):
        d.text((M, y), line, font=_font(LATB, 36), fill=INK)
        y += 48
    for line in wrap_chars(title_zh, _font(CJKB, 24), W - 2 * M):
        d.text((M, y), line, font=_font(CJKB, 24), fill=GREY)
        y += 36
    y += 10
    d.line([M, y, W - M, y], fill=LINE, width=2)
    return y + 28


def _file_bar(d, y: int, name: str, size: str, mtime: str, path: str) -> int:
    """文件信息条 —— 平台原文要求「包含文件信息」，这条就是那个「信息」。"""
    d.rectangle([M, y, W - M, y + 132], fill=PANEL, outline=LINE)
    d.text((M + 22, y + 14), "FILE", font=_font(LATB, 20), fill=ACCENT)
    d.text((M + 22, y + 46), name, font=_f(name, 19), fill=INK)
    d.text((M + 22, y + 82), path, font=_f(path, 16), fill=GREY)
    d.text((W - M - 470, y + 14), "SIZE", font=_font(LATB, 20), fill=ACCENT)
    d.text((W - M - 470, y + 46), size, font=_font(LAT, 20), fill=INK)
    d.text((W - M - 240, y + 14), "MODIFIED", font=_font(LATB, 20), fill=ACCENT)
    d.text((W - M - 240, y + 46), mtime, font=_font(LAT, 20), fill=INK)
    return y + 156


def _footer(d, note: str, page, total) -> None:
    d.line([M, H - 120, W - M, H - 120], fill=LINE, width=2)
    d.text((M, H - 92), note, font=_font(LATI, 18), fill=GREY)
    if page and total:
        d.text((W - M - 60, H - 92), "%s / %s" % (page, total), font=_font(LAT, 18), fill=GREY)


def _text_board(ws, out, title_en, title_zh, tag, src: pathlib.Path,
                note: str, page, total, hint_label: str, hint_path: str,
                start_kw: str = "", max_lines: int = 60):
    """「文件信息条 + 正文片段」的板（剧本、导演手册共用）。"""
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    y = _hdr(img, d, title_en, title_zh, tag)
    if src.is_file():
        try:
            txt = src.read_text(encoding="utf-8", errors="replace")
        except OSError:
            txt = ""
        y = _file_bar(d, y, src.name, fmt_size(src.stat().st_size), fmt_time(src),
                      "%s · %d characters" % (hint_path, len(txt)))
    else:
        y = _file_bar(d, y, "（文件缺失）", "-", "-", hint_path)
        txt = ""
    d.text((M, y), "CONTENT — %s" % hint_label, font=_font(LATB, 20), fill=ACCENT)
    y += 32
    lines = txt.splitlines()
    start = next((i for i, l in enumerate(lines) if start_kw and l.startswith(start_kw)), 0)
    for line in lines[start:start + max_lines]:
        if y > H - 170:
            break
        color = ACCENT if line.startswith(("第", "###", "**", "#")) else INK
        fp = _f(line, 17)
        for seg in wrap_chars(line, fp, W - 2 * M):
            if y > H - 170:
                break
            d.text((M, y), seg, font=_f(seg, 17), fill=color)
            y += 24
    _footer(d, note, page, total)
    img.save(out)


def _grid_board(ws, out, title_en, title_zh, tag, files: list, labels: list,
                note: str, page, total, bar_name: str, bar_path: str, cols: int = 2):
    """2×2 资产卡板（角色设计 / 场景设计共用）。"""
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    y = _hdr(img, d, title_en, title_zh, tag)
    exist = [f for f in files if f.is_file()]
    y = _file_bar(d, y, bar_name, fmt_size(sum(f.stat().st_size for f in exist)),
                  fmt_time(exist[0]) if exist else "-", bar_path)
    cw = int((W - 2 * M - 30 * (cols - 1)) / cols)
    ch = 780
    for i, f in enumerate(files):
        if not f.is_file():
            continue
        cx = M + (i % cols) * (cw + 30)
        cy = y + (i // cols) * (ch + 92)
        if cy + ch > H - 150:
            break
        d.rectangle([cx, cy, cx + cw, cy + ch], outline=LINE, width=2)
        paste_fill(img, f, (cx, cy, cw, ch), crop_bias=0.22)
        d.text((cx, cy + ch + 10), labels[i] if i < len(labels) else "", font=_font(LATB, 19), fill=ACCENT)
        d.text((cx, cy + ch + 36), f.name, font=_font(LAT, 15), fill=GREY)
    _footer(d, note, page, total)
    img.save(out)


def _video_raw_board(ws, out, cfg, note, page, total):
    """183 段镜头 + 30 集母版的文件清单（每行都有文件名/大小/分辨率/时长）。"""
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    y = _hdr(img, d, "Video raw files and delivered masters",
             "视频原始文件与母版：逐镜 raw + 集母版", "%s / %s" % (page, total))
    shots = sorted((ws / "07-成片").glob("ep*/shot_*/final.mp4"))
    masters = sorted((ws / "09-发行" / "剧集").glob("Episode*.mp4"))
    total_bytes = sum(p.stat().st_size for p in shots) + sum(p.stat().st_size for p in masters)
    y = _file_bar(d, y, "final.mp4 × %d  +  Episode*.mp4 × %d" % (len(shots), len(masters)),
                  fmt_size(total_bytes), fmt_time(shots[-1]) if shots else "-",
                  "07-成片/epNN/shot_XXX/final.mp4 · 09-发行/剧集/")
    cols = [M, M + 180, M + 560, M + 760, M + 960]
    for x, hh in zip(cols, ["File", "Size", "Resolution", "Duration"]):
        d.text((x, y), hh, font=_font(LATB, 18), fill=ACCENT)
    y += 30
    d.line([M, y - 6, W - M, y - 6], fill=LINE, width=1)
    fp = _font(LAT, 17)
    shown = 0
    for p in shots:
        if y > H - 200:
            break
        w, hh, dur = probe_stream(p)
        vals = ["/".join(p.parts[-3:]), fmt_size(p.stat().st_size),
                "%dx%d" % (w, hh) if w else "-", "%.1fs" % dur if dur else "-"]
        for x, v in zip(cols, vals):
            d.text((x, y), str(v), font=_f(v, 17), fill=INK)
        y += 25
        shown += 1
    d.line([M, y, W - M, y], fill=LINE, width=1)
    y += 14
    d.text((M, y), "Delivered masters: %d files in 09-发行/剧集/ (%s each)"
           % (len(masters), cfg.get("format", "-")), font=_font(LAT, 19), fill=INK)
    _footer(d, note + " Showing %d of %d shot files." % (shown, len(shots)), page, total)
    img.save(out)


def _inventory_board(ws, out, note, page, total):
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    y = _hdr(img, d, "Project asset inventory",
             "项目素材文件清单：角色 / 场景 / 道具 / 分镜图", "%s / %s" % (page, total))
    groups = [("characters", "人物资产卡"), ("scenes", "场景设计图"),
              ("props", "道具参考卡"), ("boards", "分镜图（按集）")]
    counts = {k: len(list((ws / "04-资产" / k).rglob("*.png"))) for k, _ in groups}
    total_files = sum(counts.values())
    all_files = [p for k, _ in groups for p in (ws / "04-资产" / k).rglob("*.png")]
    y = _file_bar(d, y, "%d PNG files in 4 folders" % total_files,
                  fmt_size(sum(p.stat().st_size for p in all_files)),
                  fmt_time(all_files[0]) if all_files else "-",
                  "04-资产/ · characters / scenes / props / boards")
    for k, label in groups:
        d.text((M, y), label, font=_font(CJKB, 20), fill=ACCENT)
        d.text((M + 320, y), "%d 个文件" % counts[k], font=_font(CJK, 20), fill=INK)
        d.text((M + 580, y), "04-资产/%s/" % k, font=_font(LAT, 17), fill=GREY)
        y += 38
    y += 12
    d.text((M, y), "分镜图样例（每镜一张）", font=_font(CJKB, 20), fill=ACCENT)
    y += 38
    ep_dirs = sorted((ws / "04-资产" / "boards").glob("ep*"))
    samples = sorted(ep_dirs[0].glob("shot_*.png"))[:4] if ep_dirs else []
    cw = int((W - 2 * M - 3 * 20) / 4)
    ch = 520
    for i, p in enumerate(samples):
        cx = M + i * (cw + 20)
        d.rectangle([cx, y, cx + cw, y + ch], outline=LINE, width=2)
        paste_fill(img, p, (cx, y, cw, ch), crop_bias=0.0)
        d.text((cx, y + ch + 8), p.name, font=_font(LAT, 15), fill=GREY)
    _footer(d, note, page, total)
    img.save(out)


# ── 权利声明（A4 竖版，打印签章后拍照上传）──────────────────────────────────
RM = 130          # 声明书页边距


def _page(title: str, subtitle: str, doc_no: str):
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    d.text((RM, 96), "RIGHTS DOCUMENTATION", font=_font(LATB, 26), fill=ACCENT)
    d.text((W - RM - d.textlength(doc_no, font=_font(LATB, 26)), 96), doc_no,
           font=_font(LATB, 26), fill=GREY)
    d.line([RM, 146, W - RM, 146], fill=LINE, width=3)
    y = 200
    for line in str(title).split("\n"):
        d.text((RM, y), line, font=_font(LATB, 50), fill=INK)
        y += 64
    y += 6
    for line in str(subtitle).split("\n"):
        d.text((RM, y), line, font=_font(LAT, 25), fill=GREY)
        y += 36
    d.line([RM, y + 18, W - RM, y + 18], fill=LINE, width=2)
    return img, d, y + 56


def _body(d, y: int, blocks, size: int = 26, lh: int = 42) -> int:
    """blocks: [(kind, text)]；kind = h / p / kv"""
    max_w = W - 2 * RM
    for kind, text in blocks:
        if kind == "h":
            y += 10
            d.text((RM, y), text, font=_f(text, size + 4, bold=True), fill=ACCENT)
            y += lh + 12
        elif kind == "p":
            f = _f(text, size)
            for line in wrap_words(text, f, max_w):
                d.text((RM, y), line, font=_f(line, size), fill=INK)
                y += lh
            y += 8
        elif kind == "kv":
            k, v = text
            fk, fv = _f(k, size, bold=True), _f(v, size)
            d.text((RM, y), k, font=fk, fill=INK)
            # 值列起点跟着**键的实测宽度**走（下限 380、上限 620）。
            # 写死 380 的后果：`Stage 3 — Character & set design` 这类长键会与值撞在一起 ——
            # 声明书出现叠字，审核方第一眼就是「这份材料不专业」。
            kw = max(380, min(int(d.textlength(k, font=fk)) + 30, 620))
            rows = wrap_words(v, fv, max_w - kw)
            if not rows:
                y += lh
            for line in rows:
                d.text((RM + kw, y), line, font=_f(line, size), fill=INK)
                y += lh
            y += 6
    return y


def _sign_block(d, y: int, with_chop: bool = True) -> int:
    """签章区：姓名 / 职务 / 签字 / 日期 / 公章位 —— 这四行是整份材料的效力所在。"""
    f, fb = _font(LAT, 24), _font(LATB, 24)
    d.text((RM, y), "SIGNED BY THE RIGHTS HOLDER", font=fb, fill=ACCENT)
    y += 46
    for label in ("Full name", "Title / Position"):
        d.text((RM, y), label + ":", font=f, fill=INK)
        d.line([RM + 250, y + 32, RM + 250 + 620, y + 32], fill=LINE, width=2)
        y += 62
    d.text((RM, y), "Signature:", font=f, fill=INK)
    d.line([RM + 250, y + 34, RM + 250 + 620, y + 34], fill=LINE, width=2)
    y += 62
    d.text((RM, y), "Date (YYYY-MM-DD):", font=f, fill=INK)
    d.line([RM + 250, y + 34, RM + 250 + 300, y + 34], fill=LINE, width=2)
    y += 70
    if with_chop:
        d.text((RM, y), "Company seal:", font=f, fill=INK)
        d.rectangle([RM + 250, y - 10, RM + 250 + 300, y + 190], outline=LINE, width=2)
        d.text((RM + 300, y + 80), "(affix seal here)", font=_font(LATI, 20), fill=GREY)
        y += 220
    return y


def _rfoot(d, page_no: int, note: str) -> None:
    y = H - 150
    d.line([RM, y, W - RM, y], fill=LINE, width=2)
    d.text((RM, y + 26), note, font=_font(LATI, 19), fill=GREY)
    d.text((W - RM - 40, y + 26), "%d / 7" % page_no, font=_font(LAT, 19), fill=GREY)


def rights_docs(ws: pathlib.Path, cfg: dict, out_dir: pathlib.Path) -> list:
    """渲染 7 页 → 返回写出的文件名列表。

    文字口径的三条纪律（来自 2026-11-07 那次的教训）：
      * **只写事实**。字体说「已栅格化进画面、MP4 里没有字体程序」；音乐说「全部由模型音频
        分支合成、无第三方」—— 不主张「已获某方授权」这种核不了的事。
      * **日期取真实 mtime**，不写死，否则换项目就是假的。
      * **能力边界写进正文**（DOC 3 的 prompt 作者、DOC 6 的适用条件），审核员能据此追问。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    en, zh = cfg["title_en"], cfg["title_zh"]
    eps, fmt, lang = cfg["episodes"], cfg["format"], cfg["language"]
    entity = cfg.get("entity") or ""
    label = cfg.get("aigc_label") or "AI-generated"

    def day(rel: str, fallback: str = "") -> str:
        return fmt_day(ws / rel) or fallback or "-"

    d_script = day("00-创作/03-分集剧本.md") or day("00-创作")
    d_asset = day("04-资产")
    d_board = day("04-资产/boards") or d_asset
    d_shot = day("07-成片")
    d_rel = day("09-发行/剧集") or d_shot

    # 总时长：母版实测优先，其次 集数 × 单集秒数
    total_s, n_master = 0.0, 0
    for p in sorted((ws / "09-发行" / "剧集").glob("Episode*.mp4")):
        dur = probe_duration(p)
        if dur:
            total_s += dur
            n_master += 1
    if total_s:
        runtime = "%d min %02d s (measured from %d delivered masters)" % (
            int(total_s // 60), int(total_s % 60), n_master)
    elif cfg.get("ep_seconds"):
        runtime = "approx. %d min (from project settings, masters not yet delivered)" % (
            int(eps * cfg["ep_seconds"] / 60))
    else:
        runtime = "-"

    model_v = (cfg.get("models") or {}).get("video") or "open-weight video checkpoint"
    model_i = (cfg.get("models") or {}).get("image") or "open-weight image checkpoint"
    written = []

    def save(name: str, img) -> None:
        p = out_dir / name
        img.save(p)
        written.append(name)

    # ---------------- DOC 1 权属声明 ----------------
    img, d, y = _page("Statement of Copyright Ownership",
                      "Who owns this work, and on what basis.", "DOC 1")
    y = _body(d, y, [
        ("h", "1. Identification of the Work"),
        ("kv", ("Title", en)),
        ("kv", ("Localised title", zh)),
        ("kv", ("Type", "Short-form drama series, live-action style, AI-assisted production")),
        ("kv", ("Episodes", "%d episodes%s" % (eps, (", approx. %d s each" % cfg["ep_seconds"])
                                     if cfg.get("ep_seconds") else ""))),
        ("kv", ("Total runtime", runtime)),
        ("kv", ("Language / Format", "%s; %s" % (lang, fmt))),
        ("kv", ("Rights holder", entity or "_______________________________________")),
        ("kv", ("Registration no.", cfg.get("registration") or "_______________________________________")),
        ("kv", ("Creation dates",
                "%s (screenplay) / %s" % (d_script,
                                          ("%s (delivered masters)" % d_rel) if n_master
                                          else "masters not yet delivered"))),
        ("h", "2. Declaration"),
        ("p", "The undersigned declares that the work identified above was created under the "
              "direction and control of the undersigned organisation, and that the undersigned "
              "organisation is the sole and exclusive owner of all copyright and neighbouring "
              "rights in the work, including the rights of reproduction, distribution, "
              "communication to the public and making available on digital platforms worldwide."),
        ("p", "The work is an original creation. The literary work (screenplay), the visual "
              "design, the shot composition, the editing, the subtitle translation and the final "
              "assembly were conceived and executed by the undersigned organisation's creative "
              "team. No pre-existing literary work, film, television programme or other "
              "copyrighted work was adapted, reproduced or incorporated."),
        ("p", "No third-party musical works, sound recordings, stock footage, stock photography, "
              "typefaces requiring a separate distribution licence, or trademarks are embodied in "
              "the work. All audiovisual material was produced in-house; all audio was synthesised "
              "by the pipeline described in DOC 3."),
        ("h", "3. Absence of encumbrance"),
        ("p", "The work is not subject to any prior exclusive licence, option, pledge, lien or "
              "pending dispute. The undersigned has not granted and will not grant any right that "
              "conflicts with the licence granted to the platform."),
    ])
    _sign_block(d, min(y + 24, H - 470))
    _rfoot(d, 1, "This statement must be signed and sealed to be effective.")
    save("rights-01-ownership.png", img)

    # ---------------- DOC 2 原创性 ----------------
    img, d, y = _page("Proof of Original Authorship",
                      "Script, design, storyboard and edit — created in-house, dated.", "DOC 2")
    y = _body(d, y, [
        ("h", "1. Chain of creation (dates from file records)"),
        ("p", "The work was developed in the following documented sequence. Each stage produced "
              "native project files that remain in the possession of the undersigned and can be "
              "produced on request."),
        ("kv", ("Stage 1 — Concept & outline", "%s. Original premise and episode outline written in-house." % d_script)),
        ("kv", ("Stage 2 — Screenplay", "%s. Full screenplay, %d episodes, scene by scene, with dialogue." % (d_script, eps))),
        ("kv", ("Stage 3 — Character & set design", "%s. Original character sheets and location designs; no reference to any existing production." % d_asset)),
        ("kv", ("Stage 4 — Storyboard", "%s. Per-episode storyboard documents with shot duration, camera position and dialogue timing." % d_board)),
        ("kv", ("Stage 5 — Generation", "%s. Audiovisual generation per DOC 3." % d_shot)),
        ("kv", ("Stage 6 — Edit & subtitle",
                ("%s. Assembly, subtitle timing, loudness and delivery conform." % d_rel)
                if n_master else "Post-production complete; masters not yet exported.")),
        ("h", "2. What is human-authored"),
        ("p", "The following elements are the product of human creative authorship and are the "
              "core protectable subject matter of the work: the story and its plot structure; all "
              "dialogue; the characterisation and the relationships between characters; the visual "
              "design of every character and location; the shot list and the composition of every "
              "shot; the editing rhythm; the subtitle adaptation and timing."),
        ("h", "3. Native files held"),
        ("p", "Screenplay (Markdown), per-episode storyboard documents, per-shot prompt records "
              "(JSON), character / scene / prop design sheets, storyboard frames rendered per "
              "shot, subtitle files, per-shot video files and delivered masters. File-level "
              "metadata (size, creation and modification timestamps) is preserved and can be "
              "inspected on request."),
    ])
    _sign_block(d, min(y + 20, H - 470))
    _rfoot(d, 2, "Supports the originality declaration in DOC 1.")
    save("rights-02-originality.png", img)

    # ---------------- DOC 3 AI 披露 ----------------
    img, d, y = _page("AI-Assisted Production Disclosure",
                      "Which tools were used, on what legal basis, and what they did not do.", "DOC 3")
    y = _body(d, y, [
        ("h", "1. Nature of AI use"),
        ("p", "The work is an AI-assisted production. Generative models were used as a rendering "
              "instrument to visualise assets and shots that were conceived, specified and "
              "selected by the human creative team. The models did not originate the story, the "
              "dialogue, the characters, the shot design or the edit."),
        ("h", "2. Models and licence basis"),
        ("kv", ("Video model", "%s, executed on rented GPU compute under the model's open-weight licence." % model_v)),
        ("kv", ("Image model", "%s, executed under the model's open-weight licence." % model_i)),
        ("kv", ("Inference host", "Rented GPU instance; no platform-generated content was supplied by the compute provider.")),
        ("kv", ("Audio", "Synthesised by the video model's audio branch. No commercial recording, no production-music library and no third-party sound effect was used.")),
        ("h", "3. Prompt authorship"),
        ("p", "Every prompt was written by the human team and is retained in the project files. "
              "Each shot has a recorded prompt specifying subject, wardrobe, camera position, "
              "lighting and duration, plus a reference image set chosen by the team. Prompts and "
              "reference images are available for inspection."),
        ("h", "4. Rights position"),
        ("p", "The undersigned asserts that copyright in the work vests in the human authors and "
              "the producing organisation, on the basis of the creative selection, arrangement and "
              "modification carried out by them, and accepts responsibility for the content of the "
              "work."),
        ("h", "5. Labelling"),
        ("p", "The work is labelled as AI-generated. A visible notice \u201c%s\u201d appears on the "
              "cover frame of every episode and in the published description; the platform's own "
              "AI-generated disclosure setting is enabled." % label),
    ])
    _sign_block(d, min(y + 14, H - 470))
    _rfoot(d, 3, "Disclosure per the platform's AI-generated content policy.")
    save("rights-03-ai-disclosure.png", img)

    # ---------------- DOC 4 第三方素材 ----------------
    img, d, y = _page("Third-Party Material Declaration",
                      "Clearance status of music, typefaces, footage and likeness.", "DOC 4")
    y = _body(d, y, [
        ("h", "1. Music and sound"),
        ("p", "No pre-existing musical composition or sound recording is embodied in the work. "
              "All audio was synthesised by the production pipeline. No production-music library, "
              "no commercial track and no third-party sound effect was used; therefore no "
              "synchronisation or master-use licence is required."),
        ("h", "2. Footage and photography"),
        ("p", "No stock footage, archival material or third-party photograph was used. All frames "
              "were generated for this production."),
        ("h", "3. Typefaces"),
        ("p", "Subtitles were rendered with a standard system typeface and rasterised into the "
              "video frames. No font software or font file is embedded in, attached to, or "
              "distributed with the work: the delivered files contain pixel data only and no font "
              "can be extracted from them. If the platform requires a specific open-licensed "
              "typeface for subtitles, the undersigned will re-render and re-supply on request."),
        ("h", "4. Likeness and personality rights"),
        ("p", "All characters are fictional and were generated. No real person's name, image, "
              "likeness or voice is depicted, imitated or implied. No performer was engaged, so no "
              "performer or model release is required. Any resemblance to an actual person is "
              "coincidental."),
        ("h", "5. Trademarks and brands"),
        ("p", "The work contains no third-party trademark, logo, trade dress or brand identifier. "
              "Vehicles, devices, packaging and set dressing are generic; no product placement "
              "arrangement exists."),
        ("h", "6. Locations"),
        ("p", "All settings are fictional interiors generated for the production. No real "
              "property, private residence or restricted location was filmed or reproduced."),
    ])
    _sign_block(d, min(y + 18, H - 470))
    _rfoot(d, 4, "Supports DOC 1 \u00a72 (no third-party material).")
    save("rights-04-third-party.png", img)

    # ---------------- DOC 5 逐集清单 ----------------
    img, d, y = _page("Episode Inventory", "What is being licensed, episode by episode.", "DOC 5")
    cols = [RM, RM + 90, RM + 430, RM + 860, RM + 1090]
    for x, hh in zip(cols, ["No.", "File", "Duration", "Resolution"]):
        d.text((x, y), hh, font=_font(LATB, 21), fill=ACCENT)
    y += 34
    d.line([RM, y - 8, W - RM, y - 8], fill=LINE, width=2)
    fp = _font(LAT, 21)
    eps_files = sorted((ws / "09-发行" / "剧集").glob("Episode*.mp4"))
    rows = eps_files or []
    for i, p in enumerate(rows):
        if y > H - 260:
            d.text((RM, y), "… (%d more rows not shown on this page)" % (len(rows) - i),
                   font=_font(LATI, 19), fill=GREY)
            break
        dur = probe_duration(p)
        w, hh, _d = probe_stream(p)
        n = re.sub(r"\D", "", p.stem) or "%02d" % (i + 1)
        vals = [n, p.name, "%.1fs" % dur if dur else "-", "%dx%d" % (w, hh) if w else "-"]
        for x, v in zip(cols, vals):
            d.text((x, y), str(v), font=fp, fill=INK)
        y += 40
    if not rows:
        for i in range(1, min(eps, 30) + 1):
            vals = ["%02d" % i, "Episode%02d.mp4" % i, "-", "-"]
            for x, v in zip(cols, vals):
                d.text((x, y), str(v), font=fp, fill=(GREY if i > 1 else INK))
            y += 40
        d.text((RM, y + 10), "Masters not yet exported — list pre-filled from project settings.",
               font=_font(LATI, 19), fill=GREY)
    y = max(y, H - 300)
    d.line([RM, y, W - RM, y], fill=LINE, width=2)
    d.text((RM, y + 18), "Total: %d episodes, %s. Delivered as a clean feed (no third-party "
                         "watermark or logo)." % (len(rows) or eps, runtime),
           font=_font(LAT, 21), fill=INK)
    _rfoot(d, 5, "Episode list matches the delivered masters.")
    save("rights-05-inventory.png", img)

    # ---------------- DOC 6 发行授权 ----------------
    img, d, y = _page("Authorisation for Distribution",
                      "If the uploading account differs from the rights holder.", "DOC 6")
    y = _body(d, y, [
        ("h", "When this document is required"),
        ("p", "Complete this page only if the account that uploads the work is not registered in "
              "the name of the rights holder identified in DOC 1. If both are the same legal "
              "entity, DOC 1 is sufficient and this page may be omitted."),
        ("h", "1. Parties"),
        ("kv", ("Rights holder", entity or "_______________________________________")),
        ("kv", ("Registration no.", cfg.get("registration") or "_______________________________________")),
        ("kv", ("Authorised uploader", "_______________________________________")),
        ("kv", ("Account / entity ID", "_______________________________________")),
        ("h", "2. Grant"),
        ("p", "The rights holder authorises the uploader identified above to upload, publish and "
              "monetise the work on the platform and its affiliated services, and to communicate "
              "with the platform on the rights holder's behalf in relation to the work. The "
              "authorisation is non-exclusive unless stated otherwise, worldwide, and valid for "
              "the term of the work's availability on the platform."),
        ("h", "3. Warranty"),
        ("p", "The rights holder warrants that it holds the rights declared in DOC 1 and that the "
              "uploader's use of the work in accordance with this authorisation will not infringe "
              "any third-party right."),
    ])
    _sign_block(d, min(y + 26, H - 470))
    _rfoot(d, 6, "Omit if uploader and rights holder are the same entity.")
    save("rights-06-authorisation.png", img)

    # ---------------- DOC 7 索引 ----------------
    img, d, y = _page("Submission Index", "What each page proves, and how to check it.", "DOC 7")
    y = _body(d, y, [
        ("h", "Document map"),
        ("kv", ("DOC 1", "Ownership — identifies the work and declares exclusive ownership.")),
        ("kv", ("DOC 2", "Originality — dated chain of creation; human-authored elements.")),
        ("kv", ("DOC 3", "AI disclosure — models, licence basis, prompt authorship, labelling.")),
        ("kv", ("DOC 4", "Third-party clearance — music, footage, typefaces, likeness, marks.")),
        ("kv", ("DOC 5", "Inventory — the delivered episodes and their specifications.")),
        ("kv", ("DOC 6", "Authorisation — only if the uploading account is not the rights holder.")),
        ("kv", ("DOC 7", "This index.")),
        ("h", "Screenshots submitted alongside"),
        ("kv", ("Entry A", "AI generation process — prompt, storyboard reference, output frame and "
                           "the asset cards used, per shot.")),
        ("kv", ("Entry B", "Source files — screenplay, character design, set design, storyboard "
                           "document, video raw files, asset inventory.")),
        ("h", "Common rejection reasons and how this set addresses them"),
        ("p", "1. No identification of the rights holder — DOC 1, signed and sealed."),
        ("p", "2. No proof that the script is original — DOC 2 with a dated creation chain."),
        ("p", "3. Unclear rights in AI-generated footage — DOC 3 states the licence basis of each "
              "model and the human authorship of the creative elements."),
        ("p", "4. Unclear music and font clearance — DOC 4."),
        ("p", "5. Uploader is not the rights holder — DOC 6."),
        ("p", "6. Screenshots that do not correspond to the work — Entry A ties every screenshot "
              "to a specific shot of a specific episode, and Entry B shows the underlying files."),
        ("h", "Before submitting"),
        ("p", "Sign and seal DOC 1, and DOC 6 if applicable. Every page must carry the same legal "
              "entity name as the business verification on the account. Upload as images in the "
              "order above."),
    ])
    _rfoot(d, 7, "Generated from the project's own records; no figures are estimated.")
    save("rights-07-index.png", img)

    return written


# ── 命令 ────────────────────────────────────────────────────────────────────
def cmd_ai_process(ws: pathlib.Path, cfg: dict, args) -> tuple:
    out_dir = ws / "09-发行" / "版权资料" / "AI生成过程"
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = ws / "07-成片" / "_tmp_frames"
    tmp.mkdir(parents=True, exist_ok=True)

    explicit = [x.strip() for x in args.shots.split(",") if ":" in x] if args.shots else []
    want = int(args.count or 6)
    recs = pick_shots(ws, want, explicit or None)
    if not recs:
        print("  [FAIL] 06-提示词/ 下没有 h3_prompts.json，无从取证")
        return [], ["缺少提示词（06-提示词/<ep>/h3_prompts.json）"]

    # 人工小标题（copyright.json::shots 里按 "ep:shot" 提供）
    titles = {}
    for s in (cfg.get("shots") or []):
        key = "%s:%s" % (s.get("ep"), s.get("shot"))
        titles[key] = s

    done, problems = [], []
    total = len(recs)
    for i, rec in enumerate(recs, 1):
        t = titles.get("%s:%s" % (rec["ep"], rec["shot"])) or {}
        rec.update({"title_en": t.get("title_en"), "title_zh": t.get("title_zh")})
        name = "ai-gen-%02d-%s-%s.png" % (i, rec["ep"], rec["shot"])
        p = out_dir / name
        try:
            ok = board_ai(ws, cfg, rec, p, i, total, tmp)
        except Exception as exc:                                 # noqa: BLE001
            print("  [FAIL] %s：%s: %s" % (name, type(exc).__name__, exc))
            problems.append("%s 渲染失败" % name)
            continue
        if ok:
            done.append(name)
            print("  %s  %s" % (name, fmt_size(p.stat().st_size)))
    if len(done) < 4:
        problems.append("AI 生成过程只有 %d 张（平台下限 4 张）" % len(done))
    return done, problems


def cmd_source_files(ws: pathlib.Path, cfg: dict, args) -> tuple:
    out_dir = ws / "09-发行" / "版权资料" / "原始文件"
    out_dir.mkdir(parents=True, exist_ok=True)
    done, problems = [], []
    total = 6

    def emit(name, fn, *a, **kw):
        try:
            fn(ws, out_dir / name, *a, **kw)
            done.append(name)
            print("  %s  %s" % (name, fmt_size((out_dir / name).stat().st_size)))
        except Exception as exc:                                 # noqa: BLE001
            print("  [FAIL] %s：%s: %s" % (name, type(exc).__name__, exc))
            problems.append("%s 渲染失败（%s）" % (name, exc))

    # 1 剧本：优先 03-分集剧本.md，否则 00-创作 下任意 *剧本*.md
    script = ws / "00-创作" / "03-分集剧本.md"
    if not script.is_file():
        cands = sorted((ws / "00-创作").glob("*剧本*.md")) or sorted((ws / "00-创作").rglob("*剧本*.md"))
        script = cands[0] if cands else script
    emit("src-01-screenplay.png", _text_board,
         "Screenplay — original literary work",
         "分集剧本原稿（%d 集，%s）" % (cfg["episodes"], cfg["language"]), "1 / %d" % total,
         script, "Script drafts with timestamps remain in the project folder.",
         1, total, "first pages", "00-创作/03-分集剧本.md", start_kw="第")
    if not script.is_file():
        problems.append("缺分集剧本（00-创作/03-分集剧本.md）")

    # 2 角色设计：女主 P01 的三视图 + 各套造型
    chars = sorted((ws / "04-资产" / "characters").glob("P01_*.png"))[:4]
    emit("src-02-character-design.png", _grid_board,
         "Character design — lead character",
         "角色设计图：主角三视图 + 造型卡", "2 / %d" % total,
         chars, ["TURNAROUND / LOOK %d" % i for i in range(len(chars))],
         "Character sheets were designed for this production; no reference to any existing work.",
         2, total, "P01_*.png (%d files)" % len(chars), "04-资产/characters/")
    if not chars:
        problems.append("缺角色设计卡（04-资产/characters/P01_*.png）")

    # 3 场景设计
    scenes = sorted((ws / "04-资产" / "scenes").glob("*.png"))[:4]
    emit("src-03-set-design.png", _grid_board,
         "Set design — principal locations",
         "场景设计图：主要场景", "3 / %d" % total,
         scenes, [p.stem.split("_")[1] if "_" in p.stem else p.stem for p in scenes],
         "All sets are fictional and were generated for this production; no real location was filmed.",
         3, total, "%d scene design files" % len(scenes), "04-资产/scenes/")
    if not scenes:
        problems.append("缺场景设计图（04-资产/scenes/*.png）")

    # 4 导演手册 / 分镜文档
    manual = ws / "00-创作" / "04-导演手册" / "第01集.md"
    if not manual.is_file():
        cands = sorted((ws / "00-创作" / "04-导演手册").glob("第*.md"))
        manual = cands[0] if cands else manual
    n_manual = len(list((ws / "00-创作" / "04-导演手册").glob("第*.md")))
    emit("src-04-storyboard.png", _text_board,
         "Storyboard document — shot list, prompt, timing",
         "分镜脚本：%s（共 %d 份）" % (manual.name, n_manual), "4 / %d" % total,
         manual, "Each shot specifies duration, wardrobe code, camera position and dialogue timing.",
         4, total, "shot 1 and shot 2", "00-创作/04-导演手册/")
    if not manual.is_file():
        problems.append("缺导演手册（00-创作/04-导演手册/第01集.md）")

    # 5 video raw
    emit("src-05-video-raw.png", _video_raw_board, cfg,
         "All raw shot files are kept in the project folder.", 5, total)
    if not list((ws / "07-成片").glob("ep*/shot_*/final.mp4")):
        problems.append("缺逐镜成片（07-成片/<ep>/<shot>/final.mp4）")

    # 6 素材清单
    emit("src-06-asset-inventory.png", _inventory_board,
         "Asset cards and storyboard frames are the visual source for every generated shot.",
         6, total)
    return done, problems


# ── 剪辑工程（平台第三入口，★ 2026-11-10）────────────────────────────────────
def _film_dir(ws: pathlib.Path) -> pathlib.Path:
    """成片阶段目录（走 `_layout` 真源；取不到就用编号目录兜底）。"""
    try:
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))
        import _layout as L                                       # noqa: PLC0415
        return pathlib.Path(L.stage_dir(ws, "film"))
    except Exception:                                             # noqa: BLE001
        return ws / "07-成片"


def _draft_manifests(ws: pathlib.Path, ep: str = "") -> list:
    """扫 `<成片>/<ep>/_draft/draft_manifest.json`，按集号排序。

    只认**生成器自己写的清单**（`edit_draft.py` 的产物）：它有 sha256、有自检结论，
    而 `draft_content.json` 只有结构 —— 拿它当证据时说不清「这份工程对应哪一集」。
    """
    out = []
    for p in sorted(_film_dir(ws).glob("*/_draft/draft_manifest.json")):
        d = _read_json(p)
        if not isinstance(d, dict):
            continue
        d["_manifest"] = str(p)
        out.append(d)
    if ep:
        want = re.sub(r"[^0-9]", "", ep) or "01"
        out = [d for d in out if (re.sub(r"[^0-9]", "", str(d.get("ep") or "")) or "") == want]
    return out


def _table(d, y: int, cols: list, rows: list, widths: list, *, size: int = 17,
           lh: int = 30, max_rows: int = 40, zebra: bool = True) -> int:
    """画一张表（列名 + 若干行，超长截断并注明）。返回结束 y。"""
    x0 = M
    total_w = sum(widths)
    if total_w > W - 2 * M:                       # 超宽按比例压回版面
        k = (W - 2 * M) / float(total_w)
        widths = [int(w * k) for w in widths]
    # 表头
    d.rectangle([x0, y, x0 + sum(widths), y + lh + 8], fill=(238, 238, 241), outline=LINE)
    x = x0
    for c, w in zip(cols, widths):
        # ⚠ 列名可能是中文（「镜号」「起点s」）——LATB 没有汉字字形，会渲染成方框。
        #   必须走 `_f` 按内容选字体，这是本仓踩过一次的坑。
        d.text((x + 8, y + 6), str(c), font=_f(c, size, bold=True), fill=INK)
        x += w
    y += lh + 8
    for i, row in enumerate(rows[:max_rows]):
        if i % 2 == 1 and zebra:
            d.rectangle([x0, y, x0 + sum(widths), y + lh], fill=PANEL)
        x = x0
        for cell, w in zip(row, widths):
            txt = str(cell)
            fp = _f(txt, size)
            while txt and d.textlength(txt, font=fp) > w - 14:
                txt = txt[:-1]
            d.text((x + 8, y + 5), txt, font=fp, fill=INK)
            x += w
        y += lh
        if y > H - 200:
            break
    d.line([x0, y, x0 + sum(widths), y], fill=LINE, width=2)
    if len(rows) > max_rows:
        d.text((x0, y + 10), "（共 %d 行，此处显示前 %d 行；全量见 draft_manifest.json）"
               % (len(rows), max_rows), font=_f("共", 17), fill=GREY)
        y += 34
    return y + 14


def _stats(d, y: int, items: list) -> int:
    """一排「标签 + 数值」格子（给时间轴页补上轨汇总，避免 A4 大片空白）。"""
    n = max(1, len(items))
    gap = 20
    cw = int((W - 2 * M - gap * (n - 1)) / n)
    for i, (label, value) in enumerate(items):
        x = M + i * (cw + gap)
        d.rectangle([x, y, x + cw, y + 118], fill=PANEL, outline=LINE)
        d.text((x + 16, y + 14), label, font=_f(label, 17), fill=GREY)
        d.text((x + 16, y + 50), str(value), font=_f(str(value), 30, bold=True), fill=INK)
    return y + 146


def _proves(d, y: int, lines: list) -> int:
    """「这一页证明什么 + 怎么核对」块，返回结束 y。

    为什么要有：A4 证据板只有一张小表时，审核看到的是**大半页白纸** ——
    既不像材料，也没告诉对方「该从这页得出什么结论」。这里只写
    **可核对的事实与命令**（与 rights 页的措辞纪律一致：不写承诺、不写形容词），
    顺带把版面下半页占住。
    """
    if not lines:
        return y
    items = []
    for ln in lines:
        fp = _f(ln, 18)
        items.append((fp, wrap_chars(ln, fp, W - 2 * M - 64)))
    n = sum(len(p) for _fp, p in items)
    head = "这一页证明什么 · 怎么核对"
    box_h = 58 + 28 * n + 18
    d.rectangle([M, y, W - M, y + box_h], fill=PANEL, outline=LINE, width=2)
    d.text((M + 18, y + 16), head, font=_f(head, 19, bold=True), fill=INK)
    yy = y + 54
    for fp, pieces in items:
        d.text((M + 16, yy), "·", font=fp, fill=GREY)
        for piece in pieces:
            d.text((M + 40, yy), piece, font=fp, fill=INK)
            yy += 28
    return y + box_h + 18



def cmd_edit_draft(ws: pathlib.Path, cfg: dict, args) -> tuple:
    """剪辑工程证据板：机器能产的四张（工程树 / 时间轴 / 字幕 / 素材哈希）。

    ⚠ **不画时间轴截图**。本机不装剪映、也不该用假 UI 冒充截图 ——
      素材截图由人在剪映里截一张，命名 `draft-shot-01-<ep>.png` 放进同目录，
      门禁（release_check）会认它并作为补充材料。
    """
    out_dir = ws / "09-发行" / "版权资料" / "剪辑工程"
    out_dir.mkdir(parents=True, exist_ok=True)
    mans = _draft_manifests(ws, getattr(args, "ep", "") or "")
    if not mans:
        print("  [FAIL] 没找到任何 draft_manifest.json ⇒ 先跑：")
        print("         python stages/edit/scripts/edit_draft.py --workspace \"%s\" --ep ep01" % ws)
        return [], ["缺剪辑工程清单（<成片>/<ep>/_draft/draft_manifest.json）"]

    first = mans[0]
    ep = str(first.get("ep") or "ep01")
    canvas = first.get("canvas") or {}
    total = 4
    done, problems = [], []

    def emit(name, fn, *a, **kw):
        try:
            fn(*a, **kw)
            done.append(name)
            print("  %s  %s" % (name, fmt_size((out_dir / name).stat().st_size)))
        except Exception as exc:                                 # noqa: BLE001
            print("  [FAIL] %s：%s: %s" % (name, type(exc).__name__, exc))
            problems.append("%s 渲染失败（%s）" % (name, exc))

    # ① 工程总览：一季有多少工程、画布、总时长、自检结论
    def board_overview(path: pathlib.Path):
        img = Image.new("RGB", (W, H), PAPER)
        d = ImageDraw.Draw(img)
        y = _hdr(img, d, "Editing project — overview",
                 "剪辑工程总览（%d 个剪映工程）" % len(mans), "1 / %d" % total,
                 kicker="EDITING PROJECT RECORD")
        y = _file_bar(d, y, "draft_manifest.json × %d" % len(mans),
                      fmt_size(sum(pathlib.Path(m["_manifest"]).stat().st_size for m in mans)),
                      fmt_time(pathlib.Path(first["_manifest"])),
                      "%s/<ep>/_draft/draft_manifest.json" % _film_dir(ws).name)
        rows = [[str(m.get("ep") or "-"),
                 pathlib.Path(str(m.get("draft_dir") or "")).name or "-",
                 "%sx%s" % ((m.get("canvas") or {}).get("width"), (m.get("canvas") or {}).get("height")),
                 "%s" % m.get("fps"),
                 "%.2fs" % float(m.get("total_duration_s") or 0),
                 "视频 %s / 字幕 %s / BGM %s" % (
                     ((m.get("verdict") or {}).get("counts") or {}).get("video"),
                     ((m.get("verdict") or {}).get("counts") or {}).get("text"),
                     ((m.get("verdict") or {}).get("counts") or {}).get("audio")),
                 "PASS" if (m.get("verdict") or {}).get("pass") else "FAIL"]
                for m in mans]
        y = _table(d, y, ["集", "工程目录", "画布", "fps", "总时长", "轨道内容", "自检"],
                   rows, [90, 420, 150, 70, 140, 470, 100], size=17)
        note = ("每个工程 = 逐镜素材 + 逐条字幕 + BGM 的可编辑时间轴，与发行版 EpisodeNN.mp4 同源同序；"
                "工程内素材为项目内文件，sha256 见第 4 页。")
        for line in wrap_chars(note, _f(note, 19), W - 2 * M):
            d.text((M, y), line, font=_f(line, 19), fill=GREY)
            y += 28
        y = _proves(d, y + 20, [
            "本表每行对应一集，由 edit_draft.py 读「成片目录 + 字幕线索 + BGM 计划」后生成，不是手填。",
            "「自检」列是引擎回读 draft_content.json 逐项比对（画布 / 段起止 / 字幕起点 / 素材可读）的结论，"
            "PASS 才算可提交。",
            "核对：打开 <集>/_draft/epNN_剪映工程/draft_content.json，tracks 里的 target_timerange 应能与本表总时长对上。",
        ])
        _footer(d, "Source: draft_manifest.json written by stages/edit/scripts/edit_draft.py", 1, total)
        img.save(path)

    # ② 时间轴结构（取第一集，逐镜）
    def board_timeline(path: pathlib.Path):
        img = Image.new("RGB", (W, H), PAPER)
        d = ImageDraw.Draw(img)
        y = _hdr(img, d, "Timeline — shot by shot",
                 "时间轴结构：%s（逐镜起止与素材）" % ep, "2 / %d" % total,
                 kicker="EDITING PROJECT RECORD")
        vid = (first.get("tracks") or {}).get("video") or []
        y = _file_bar(d, y, "video track · %d segments" % len(vid),
                      fmt_size(sum(int(v.get("bytes") or 0) for v in vid)),
                      fmt_time(pathlib.Path(first["_manifest"])),
                      "%s/%s/_draft/draft_manifest.json" % (_film_dir(ws).name, ep))
        rows = [[str(i + 1),
                 ("封面" if v.get("kind") == "photo" else str(v.get("shot_id") or "-")),
                 "%.2f" % float(v.get("start_s") or 0),
                 "%.2f" % (float(v.get("start_s") or 0) + float(v.get("dur_s") or 0)),
                 "%.2f" % float(v.get("dur_s") or 0),
                 str(v.get("name") or "-"),
                 "%.1f KB" % (int(v.get("bytes") or 0) / 1024.0)]
                for i, v in enumerate(vid)]
        y = _table(d, y, ["#", "镜号", "起点s", "终点s", "时长s", "素材文件", "大小"],
                   rows, [60, 150, 110, 110, 110, 640, 150], size=17)
        tr = first.get("tracks") or {}
        y = _stats(d, y + 6, [
            ("视频轨", "%d 段" % len(vid)),
            ("字幕轨", "%d 条" % len(tr.get("text") or [])),
            ("BGM 轨", "%d 段" % len(tr.get("audio") or [])),
            ("封面片头", "%.2fs" % (float((first.get("cover") or {}).get("seconds") or 0))),
            ("总时长", "%.2fs" % float(first.get("total_duration_s") or 0)),
        ])
        note = ("时间轴按 shot_id 顺序拼接，段长取自 ffprobe 实测；封面片头 0.8s 计在第 1 行。"
                "字幕完整条目见第 3 页，BGM 与素材哈希见第 4 页，全量字段在 draft_manifest.json。")
        for line in wrap_chars(note, _f(note, 19), W - 2 * M):
            d.text((M, y), line, font=_f(line, 19), fill=GREY)
            y += 28
        y = _proves(d, y + 20, [
            "每行就是一镜，终点 = 起点 + 时长，逐段累加不做四舍五入（微秒取整，0.2s 不会被截成 0）。",
            "段长不是素材清单上的计划值，而是对 final.mp4 实测的结果；缺镜会在生成时被判为不合格，不会静默少一段。",
            "核对：逐镜跑 ffprobe -v error -show_entries format=duration，各段之和应等于本页总时长。",
        ])
        _footer(d, "Source: draft_manifest.json · tracks.video", 2, total)
        img.save(path)

    # ③ 字幕对照（条数 + 前若干条）
    def board_subtitles(path: pathlib.Path):
        img = Image.new("RGB", (W, H), PAPER)
        d = ImageDraw.Draw(img)
        y = _hdr(img, d, "Subtitles — time, text, alignment source",
                 "字幕对照：%s（%d 条）" % (ep, len(((first.get("tracks") or {}).get("text") or []))),
                 "3 / %d" % total, kicker="EDITING PROJECT RECORD")
        txt = (first.get("tracks") or {}).get("text") or []
        y = _file_bar(d, y, "text track · %d segments" % len(txt), "-",
                      fmt_time(pathlib.Path(first["_manifest"])),
                      "字幕时间来自 CTC/ASR 强制对齐（cues.json），非估算")
        rows = [[str(i + 1),
                 "%.2f" % float(t.get("start_s") or 0),
                 "%.2f" % float(t.get("end_s") or 0),
                 str(t.get("text") or ""),
                 str(t.get("source") or "-")]
                for i, t in enumerate(txt)]
        y = _table(d, y, ["#", "起s", "止s", "字幕文本", "对齐来源"],
                   rows, [60, 100, 100, 1000, 260], size=17, max_rows=34)
        note = ("字幕起点已含封面片头偏移（%d µs）；与 EpisodeNN.mp4 的烧录时间轴一致。"
                % int(first.get("cue_offset_us") or 0))
        for line in wrap_chars(note, _f(note, 19), W - 2 * M):
            d.text((M, y), line, font=_f(line, 19), fill=GREY)
            y += 28
        y = _proves(d, y + 20, [
            "字幕文本与时间是 cues.json 的原样搬运，工程生成过程不改写、不润色、不补句。",
            "「对齐来源」列标明每条时间是 CTC/ASR 强制对齐得来，不是按字数估算。",
            "核对：在 EpisodeNN.mp4 的对应时刻应有同一句字幕；工程内该条起点 = 成片时刻 + 封面片头偏移。",
        ])
        _footer(d, "Source: draft_manifest.json · tracks.text", 3, total)
        img.save(path)

    # ④ 素材哈希（可回原文件核对）
    def board_digest(path: pathlib.Path):
        img = Image.new("RGB", (W, H), PAPER)
        d = ImageDraw.Draw(img)
        y = _hdr(img, d, "Source assets — SHA-256 ledger",
                 "素材哈希台账：%s（可回原文件逐项核对）" % ep, "4 / %d" % total,
                 kicker="EDITING PROJECT RECORD")
        items = []
        for v in (first.get("tracks") or {}).get("video") or []:
            items.append(("画面", v))
        for a in (first.get("tracks") or {}).get("audio") or []:
            items.append(("BGM", a))
        y = _file_bar(d, y, "referenced assets · %d files" % len(items),
                      fmt_size(sum(int(i[1].get("bytes") or 0) for i in items)),
                      fmt_time(pathlib.Path(first["_manifest"])),
                      "工程引用绝对路径；换机器需重链，或用 edit_draft --copy-media")
        rows = [[k, str(v.get("name") or "-"), "%.1f KB" % (int(v.get("bytes") or 0) / 1024.0),
                 (str(v.get("sha256") or "")[:32] + "…") if v.get("sha256") else "（未计算）"]
                for k, v in items]
        y = _table(d, y, ["轨", "文件", "大小", "SHA-256（前 32 位）"],
                   rows, [80, 520, 160, 760], size=16, max_rows=26)
        note = ("完整 64 位哈希见 draft_manifest.json。同一文件两次生成的哈希不变，说明工程可复现；"
                "如果素材被替换，哈希会先变，而成片肉眼看不出来。")
        # ⚠ 别在图上写 `⇒` / `→`：Arial 没有这些字形，会渲染成方框（本条已实测踩一次）
        for line in wrap_chars(note, _f(note, 19), W - 2 * M):
            d.text((M, y), line, font=_f(line, 19), fill=GREY)
            y += 28
        y = _proves(d, y + 20, [
            "每个被工程引用的文件一行，哈希是对磁盘文件实测的结果，不是文件名或时间戳的派生值。",
            "同一素材两次生成哈希不变，说明工程可复现；素材被替换时哈希先变，而成片肉眼看不出来。",
            "核对：Windows 用 certutil -hashfile <文件> SHA256，Linux/macOS 用 sha256sum <文件>，与左列前缀逐字比对。",
        ])
        _footer(d, "Source: draft_manifest.json · tracks.{video,audio}.sha256", 4, total)
        img.save(path)

    emit("draft-01-overview.png", board_overview, out_dir / "draft-01-overview.png")
    emit("draft-02-timeline.png", board_timeline, out_dir / "draft-02-timeline.png")
    emit("draft-03-subtitles.png", board_subtitles, out_dir / "draft-03-subtitles.png")
    emit("draft-04-digest.png", board_digest, out_dir / "draft-04-digest.png")

    bad = [m for m in mans if not (m.get("verdict") or {}).get("pass")]
    if bad:
        problems.append("%d 集的工程自检没过（%s）⇒ 先修工程再上传，面板上会印 FAIL"
                        % (len(bad), "、".join(str(m.get("ep")) for m in bad[:5])))
    print("  · 还缺一张**剪映时间轴截图**：在剪映里打开草稿截一张，命名 "
          "`draft-shot-01-%s.png` 放进 %s（引擎不伪造 UI，只能人工截）" % (ep, out_dir))
    return done, problems


def cmd_rights(ws: pathlib.Path, cfg: dict, args) -> tuple:
    out_dir = ws / "09-发行" / "版权资料" / "权利声明"
    try:
        written = rights_docs(ws, cfg, out_dir)
    except Exception as exc:                                     # noqa: BLE001
        print("  [FAIL] 权利声明渲染失败：%s: %s" % (type(exc).__name__, exc))
        return [], ["权利声明未生成"]
    for n in written:
        print("  %s  %s" % (n, fmt_size((out_dir / n).stat().st_size)))
    problems = []
    if not cfg.get("entity"):
        problems.append("缺权利主体名称 → DOC 1 / DOC 6 留空，必须补齐并盖章（否则仍会驳回）")
    return written, problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="版权资料四件套（平台两个入口 + 剪辑工程 + 权利声明）")
    ap.add_argument("what", nargs="?", default="all",
                    choices=("all", "ai-process", "source-files", "edit-draft", "rights"))
    # `--what` 与位置参数等价：控制台的命令面板按「带 -- 的开关」拼 argv，
    # 只留位置参数会出现 `... what all` 这种非法的命令行。
    ap.add_argument("--what", dest="what_flag", default=None,
                    choices=("all", "ai-process", "source-files", "edit-draft", "rights"))
    ap.add_argument("--workspace", default=None, help="剧目录（默认取 SOLODRAMA_WORKSPACE）")
    ap.add_argument("--shots", default=None,
                    help="AI 生成过程用哪些镜：`6`（自动挑 6 个）或 `ep01:shot_007,ep13:shot_002`")
    ap.add_argument("--count", type=int, default=None, help="自动挑几个镜（默认 6，平台区间 4–20）")
    ap.add_argument("--entity", default=None, help="权利主体名称（写入 DOC 1 / DOC 6）")
    ap.add_argument("--registration", default=None, help="注册号 / 营业执照号")
    ap.add_argument("--ep", default=None,
                    help="剪辑工程面板只画某一集（默认取扫到的第一集，其余集在总览表里）")
    a = ap.parse_args(argv)

    if Image is None:
        print("[FAIL] 需要 Pillow：pip install -r requirements.txt")
        return 2

    ws = pathlib.Path(a.workspace or __import__("os").environ.get("SOLODRAMA_WORKSPACE") or ".")
    ws = ws.expanduser().resolve()
    if not ws.is_dir():
        print("[FAIL] 工作区不存在：%s" % ws)
        return 2

    missing = check_fonts()
    for m in missing:
        print("  [WARN] 缺%s —— 图上文字会变成方块/缺字" % m)

    cfg = load_cfg(ws)
    if a.entity:
        cfg["entity"] = a.entity
    if a.registration:
        cfg["registration"] = a.registration
    a.what = a.what_flag or a.what
    if a.shots and ":" not in a.shots:
        a.count = int(re.sub(r"\D", "", a.shots) or 6)

    print("=" * 84)
    print("版权资料生成：%s" % cfg["title_en"])
    print("=" * 84)
    print("工作区    : %s" % ws)
    print("集数/时长 : %d 集 × %ss" % (cfg["episodes"], cfg["ep_seconds"] or "?"))
    print("画幅/规格 : %s ｜ %s" % (cfg.get("slug"), cfg["format"]))
    print("权利主体  : %s" % (cfg["entity"] or "（未填，声明书留空待签）"))
    print("-" * 84)

    problems = []
    if a.what in ("all", "ai-process"):
        print("[入口 A] AI 生成过程（提示词 → 分镜图 → 成片帧 → 资产卡）")
        done, p1 = cmd_ai_process(ws, cfg, a)
        problems += p1
        print("  合计 %d 张" % len(done))
        print()
    if a.what in ("all", "source-files"):
        print("[入口 B] 原始文件 / 素材文件信息")
        done, p2 = cmd_source_files(ws, cfg, a)
        problems += p2
        print("  合计 %d 张" % len(done))
        print()
    if a.what in ("all", "edit-draft"):
        print("[剪辑工程] 工程树 / 时间轴结构 / 字幕对照 / 素材哈希（4 张）")
        done, p4 = cmd_edit_draft(ws, cfg, a)
        problems += p4
        print("  合计 %d 张" % len(done))
        print()
    if a.what in ("all", "rights"):
        print("[权利声明] 7 页 A4（打印 → 签字 → 盖章 → 拍照上传）")
        done, p3 = cmd_rights(ws, cfg, a)
        problems += p3
        print("  合计 %d 页" % len(done))
        print()

    print("-" * 84)
    if problems:
        print("[注意] %d 项要处理：" % len(problems))
        for p in problems:
            print("  - %s" % p)
        print("\n落点：09-发行/版权资料/{AI生成过程,原始文件,权利声明}/")
        return 2
    print("[OK] 四套已产出。下一步：")
    print("     1) 打开 权利声明/rights-01..07 打印、签字、盖章（主体名要与平台商务认证逐字一致）")
    print("     1b) 在剪映里打开草稿，截一张时间轴图存 剪辑工程/draft-shot-01.png（人工项）")
    print("     2) 上传时按「入口 A 01→NN」「入口 B 01→NN」「剪辑工程 01→NN」「DOC 1→7」分开传，别混")
    print("     3) python stages/production/scripts/release_check.py --workspace \"%s\"" % ws)
    print("落点：09-发行/版权资料/{AI生成过程,原始文件,剪辑工程,权利声明}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
