# -*- coding: utf-8 -*-
"""
cover_forge.py — 短剧 / 影视发行封面**兜底**排版引擎（底图 + PIL 叠字）

★★ 2026-10-20 用户决策：**本方案不是主路径**。封面改为 AI 一次画出来（带标题、参与构图），
   主路径 = `stages/production/scripts/cover_prompt.py` + 本地 ComfyUI / RunningHub 工作流，
   规范见 `stages/production/references/cover/prompt-guide.md`。
   本脚本降级为**兜底**：仅当 AI 连续多轮 + inpaint 都写不对标题、档期又不允许等时，
   才用它在 AI 生成的图上重排标题。固有短板：文字与人物是两层，抓马度上限低。

用法：
    python cover_forge.py --spec cover_spec.json
    python cover_forge.py --write-example ./cover_spec.json     # 导出示例配置
    python cover_forge.py --spec cover_spec.json --check        # 只校验尺寸，不出图

spec 结构（所有相对路径均以 spec 文件所在目录为基准）：
    {
      "out_dir":   "covers",                    # 相对 spec 目录；省略则与 spec 同目录
      "palette":   {"accent": "#8A1538",        # 主色：tag 胶囊底色、分隔线
                    "accent2": "#E9C79C"},      # 强调色：副标第 2 行、右下 badge
      "fonts":     {"title": ["georgiab.ttf"],  # 主标题字族；数组为回退链
                    "body":  ["georgia.ttf"],   # 副标题字族
                    "sans":  ["seguisb.ttf"]},  # 标签/胶囊字族
      "text":      {                            # 全局文案（六槽位），可被逐张覆盖
                    "tag": "", "title": "", "sub1": "", "sub2": "",
                    "kicker": "", "badge": ""},
      "covers": [
        {
          "src":    "assets/hero.png",          # 底图
          "size":   [1920, 1080],               # 目标像素
          "name":   "cover_16x9",               # 输出文件名（不含扩展名）
          "focus":  0.115,                      # 垂直取景 0=顶部 1=底部
          "layout": "auto",                     # auto | wide | stacked | vertical
          "side":   0.58,                       # 仅 wide：左栏压暗宽度占比
          "power":  0.78,                       # 仅 wide：压暗衰减曲线（勿超 1.0）
          "strength": 236,                      # 仅 wide：最左端暗度 0-255
          "scrim":  true,                       # 仅 wide：false=纯靠描边不压暗
          "stroke_scale": 1.0,                  # 描边倍率，极端浅底可提到 1.3
          "saturation": 1.06,                   # 饱和度微调
          "text":   {"tag": "..."}              # 逐张覆盖文案（A/B 方案用）
        }
      ],
      "export":    {"png": true, "jpg": true, "jpg_quality": 92, "preview": true}
    }

设计原则（方法论的代码化，勿轻易改动）：
  1. **一律从底部基线反向排布文字块**。自上而下累加行高，在字号随画布变化时极易
     让末行撞上底部的 kicker/badge；自下而上计算 y 则任何字号都不重叠。
  2. **文字可读性三保险，优先级：描边 > 投影 > 压暗**。压暗会同时压低主体亮度，
     是三者中代价最高的一档，只加到达标即止，不要靠它兜底。
  3. **取景必须知道源图与目标的比例关系**。源图比目标"更窄"时水平方向零余量，
     主体无法左右平移，此时只能靠垂直 focus 取景——这是最常见的隐性失效点。
  4. 任何尺寸都不得让文字压在人脸上。
"""

import sys, os, json, argparse

try:
    from PIL import Image, ImageDraw, ImageFont, ImageEnhance
except ImportError:
    sys.exit("[FATAL] 需要 Pillow：pip install Pillow")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ---------------------------------------------------------------- 字体

FONT_DIRS = [
    r"C:\Windows\Fonts",
    "/System/Library/Fonts",
    "/Library/Fonts",
    "/usr/share/fonts",
    os.path.expanduser("~/.fonts"),
]

# 各字族的候选回退链：按顺序取第一个存在的文件。
# 末位总是 CJK 字体，保证中文标题不会渲染成方块。
DEFAULT_FONTS = {
    "title": ["georgiab.ttf", "timesbd.ttf", "palab.ttf", "SimHei.ttf",
              "NotoSerifSC-VF.ttf", "msyhbd.ttc"],
    "body": ["georgia.ttf", "times.ttf", "pala.ttf", "NotoSerifSC-VF.ttf", "msyh.ttc"],
    "sans": ["seguisb.ttf", "segoeuib.ttf", "arialbd.ttf", "NotoSansSC-VF.ttf", "msyhbd.ttc"],
}

_font_cache = {}


def _find_font_file(names):
    for nm in names:
        for d in FONT_DIRS:
            p = os.path.join(d, nm)
            if os.path.isfile(p):
                return p
    return None


def resolve_family(family_cfg, key):
    """把 spec 里的字族配置（字符串或列表）解析为可用文件路径"""
    ck = (key, tuple(family_cfg) if isinstance(family_cfg, list) else family_cfg)
    if ck in _font_cache:
        return _font_cache[ck]
    names = family_cfg if isinstance(family_cfg, list) else [family_cfg]
    names = list(names) + DEFAULT_FONTS.get(key, [])
    seen, ordered = set(), []
    for n in names:
        if n not in seen:
            seen.add(n)
            ordered.append(n)
    p = _find_font_file(ordered)
    if not p:
        raise RuntimeError(f"找不到 {key} 字族的任何可用字体，候选：{ordered}")
    _font_cache[ck] = p
    return p


def has_cjk(text):
    return any("\u2e80" <= ch <= "\u9fff" or "\uff00" <= ch <= "\uffef" for ch in text)


def load_font(family_path, size):
    return ImageFont.truetype(family_path, max(8, int(size)))


# ---------------------------------------------------------------- 取景


def cover_crop(src, tw, th, focus=0.38):
    """等比铺满目标框后裁切。

    focus: 垂直取景位置 0=取顶部 1=取底部。人物立绘取 0.10~0.15（保头肩），
           场景图取 0.30~0.45（保地平线）。
    返回 (图像, 水平余量, 垂直余量)。两个余量都为 0 说明该方向被锁死。
    """
    im = Image.open(src).convert("RGB")
    sw, sh = im.size
    s = max(tw / sw, th / sh)
    nw, nh = int(round(sw * s)), int(round(sh * s))
    im = im.resize((nw, nh), Image.LANCZOS)

    hx, vy = nw - tw, nh - th
    left = hx // 2                                   # 水平恒居中
    top = int(vy * max(0.0, min(1.0, focus))) if vy > 0 else 0
    return im.crop((left, top, left + tw, top + th)), hx, vy


# ---------------------------------------------------------------- 暗罩


def _ramp(n, strength, power, invert=False):
    """返回长度 n 的 0~strength 渐变值序列。invert=True 则反向衰减。"""
    out = []
    for i in range(n):
        t = i / max(1, n - 1)
        if invert:
            t = 1 - t
        out.append(int(strength * (t ** power)))
    return out


def v_scrim(im, frac, strength, at="bottom", power=1.45):
    """垂直方向渐变压暗（上下堆叠布局用）。

    at="bottom" 底部最暗（压住底部文字），at="top" 相反。
    """
    w, h = im.size
    sh = max(1, int(h * frac))
    g = Image.new("L", (1, sh))
    # at="bottom" → 末行最强（invert=False）；at="top" → 首行最强（invert=True）
    for y, v in enumerate(_ramp(sh, strength, power, invert=(at == "top"))):
        g.putpixel((0, y), v)
    g = g.resize((w, sh), Image.BILINEAR)
    black = Image.new("RGB", (w, sh), (8, 6, 8))
    y0 = h - sh if at == "bottom" else 0
    base = im.crop((0, y0, w, y0 + sh))
    im.paste(Image.composite(black, base, g), (0, y0))
    return im


def h_scrim(im, frac, strength, power=0.85, at="left"):
    """水平方向渐变压暗（左右分栏布局用）。

    power 是关键：>1 衰减过快，文字右端得不到压暗（曾导致白字压在浅色服饰上不可读）；
    0.78~0.90 能在中段维持有效压暗。但不要靠加大 frac 兜底——frac 过大会连主体
    一起压黑，反而不如把描边加厚。

    注意 invert 的取向与 v_scrim 相反：at="left" 要求**首列最强**（文字在左），
    故须 invert=True。取错方向会变成「人物被压暗、右侧空旷背景被压黑」——
    画面主体变闷而文字区反而不受保护，是隐蔽但影响最大的错误。
    """
    w, h = im.size
    sw = max(1, int(w * frac))
    g = Image.new("L", (sw, 1))
    for x, v in enumerate(_ramp(sw, strength, power, invert=(at == "left"))):
        g.putpixel((x, 0), v)
    g = g.resize((sw, h), Image.BILINEAR)
    black = Image.new("RGB", (sw, h), (8, 6, 8))
    x0 = 0 if at == "left" else w - sw
    base = im.crop((x0, 0, x0 + sw, h))
    im.paste(Image.composite(black, base, g), (x0, 0))
    return im


# ---------------------------------------------------------------- 文字


def text_width(text, font, tr=0):
    return sum(font.getlength(c) for c in text) + tr * max(0, len(text) - 1)


def draw_tracked(d, xy, text, font, fill, tr=0, stroke=0, stroke_fill=(0, 0, 0, 205)):
    """带字距/描边的逐字符绘制"""
    x, y = xy
    for ch in text:
        if stroke:
            d.text((x, y), ch, font=font, fill=fill,
                   stroke_width=stroke, stroke_fill=stroke_fill)
        else:
            d.text((x, y), ch, font=font, fill=fill)
        x += font.getlength(ch) + tr


def fit_font(fp, text, target, max_w):
    """在不超过 max_w 的前提下取最大字号"""
    size = int(target)
    while size > 8:
        f = ImageFont.truetype(fp, size)
        if f.getlength(text) <= max_w:
            return f
        size -= max(1, size // 50)
    return ImageFont.truetype(fp, 8)


def title_bbox(d, font, text, x, y):
    """返回文字渲染后的真实 bbox (l, t, r, b)（含描边外的字形范围）。

    ★ 反馈 P1-9 的根因：色条 y 以前写 `标题顶 + 字号 × 0.96~1.12 em`。
    衬线体的基线约在 0.75~0.8 em，逗号/降部（, ; g j p q y）会伸到 ~0.95–1.05 em，
    所以 0.98/0.96 恰好落在降部区间内，色条直接穿过逗号（`5,8 MILLONES` 看起来像 `5.8`）。
    `textbbox` 给的是**这一行字真实的上下界**，与字族、字号、字符集都无关。
    """
    try:
        return d.textbbox((x, y), text, font=font)
    except Exception:                                        # noqa: BLE001 - 极老 Pillow
        w = text_width(text, font)
        return (x, y, x + int(w), y + int(font.size * 1.0))


def band_y(d, font, text, x, y, gap_em=0.16):
    """色条/分隔线该放的 y：标题**真实底边**之下留 gap_em。

    返回 (y_band, bbox_bottom)。任何字族／字号／语言都稳，不再依赖 em 经验值。
    """
    _, _, _, bottom = title_bbox(d, font, text, x, y)
    return int(bottom + font.size * gap_em), int(bottom)


def _sub_font(fp, T, target, max_w):
    """副标字体：取 sub1/sub2 里**更长**的那行做一次 fit_font（两行保持同字号）。

    ★ 反馈 P1-10 的根因：主标题走 fit_font 会自动收缩，副标却用固定 `h × 0.0335` 且无宽度校验，
    画幅越窄越容易溢出（9:16 档 `ME LLAMARON LA PRIMA POBRE` 右侧被裁掉 3 个字符，
    同文案在 3:4 档却刚好放得下 —— 所以「只看一档」永远发现不了）。
    """
    texts = [T.get("sub1") or "", T.get("sub2") or ""]
    longest = max(texts, key=len) if any(texts) else ""
    if not longest:
        return load_font(fp, target)
    return fit_font(fp, longest, target, max_w)


def soft_shadow(d, xy, text, font, layers=10, alpha=28, dx=0.34, dy=0.5):
    for o in range(layers, 0, -1):
        d.text((xy[0] + o * dx, xy[1] + o * dy), text, font=font, fill=(0, 0, 0, alpha))


# ---------------------------------------------------------------- 布局


def _hex2rgb(s, default):
    s = (s or "").lstrip("#")
    if len(s) == 6:
        try:
            return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            pass
    return default


def layout_stacked(im, T, PAL, F, stroke_scale=1.0):
    """上下堆叠：文字压在底部暗部。适用于 3:4 / 4:3 / 1:1 / 9:16 等接近方形的画幅。"""
    w, h = im.size
    d = ImageDraw.Draw(im)
    PAD = int(w * 0.052)
    ZA, GOLD = PAL["accent"], PAL["accent2"]
    SW = max(2, int(h * 0.0055 * stroke_scale))

    # --- 顶部 tag 胶囊
    ft = load_font(F["sans"], h * 0.042)
    tw_ = text_width(T["tag"], ft, int(h * 0.0035))
    bw, bh = int(tw_ + h * 0.062), int(h * 0.094)
    box = Image.new("RGBA", (max(1, bw), max(1, bh)), (0, 0, 0, 0))
    ImageDraw.Draw(box).rounded_rectangle([0, 0, bw - 1, bh - 1],
                                          radius=int(bh * 0.26), fill=ZA + (242,))
    px, py = PAD, int(h * 0.045)
    im.paste(box, (px, py), box)
    d = ImageDraw.Draw(im)
    draw_tracked(d, (px + int(h * 0.026), py + (bh - ft.size * 1.30) / 2), T["tag"], ft,
                 (255, 255, 255), int(h * 0.0035), stroke=max(1, SW // 2))

    # --- 反向排布：底行基线 → 副标 2 → 副标 1 → 主标题
    fs = _sub_font(F["body"], T, h * 0.056, w - PAD * 2)   # P1-10 副标自适应
    step = int(fs.size * 1.30)
    fb = fit_font(F["title"], T["title"], h * 0.185, w - PAD * 2)
    base = h - PAD - int(h * 0.062)
    y_sub2 = base - step
    y_sub1 = y_sub2 - step
    y_title = y_sub1 - int(fb.size * 1.40)

    soft_shadow(d, (PAD, y_title), T["title"], fb, layers=12, alpha=26)
    d.text((PAD, y_title), T["title"], font=fb, fill=(255, 255, 255),
           stroke_width=SW, stroke_fill=(0, 0, 0, 205))
    ry, _bb = band_y(d, fb, T["title"], PAD, y_title)   # P1-9 真实字形底边
    d.rectangle([PAD, ry, PAD + int(w * 0.105), ry + max(3, int(h * 0.008))], fill=ZA)

    for txt, yy, col in ((T["sub1"], y_sub1, (255, 255, 255)), (T["sub2"], y_sub2, GOLD)):
        if not txt:
            continue
        soft_shadow(d, (PAD, yy), txt, fs, layers=8, alpha=30)
        d.text((PAD, yy), txt, font=fs, fill=col,
               stroke_width=max(2, SW - 1), stroke_fill=(0, 0, 0, 200))

    # --- 底部 kicker（左） / badge（右）
    fk = load_font(F["sans"], h * 0.034)
    kw = text_width(T["kicker"], fk, int(h * 0.0026))
    ky = h - PAD - fk.size * 0.92
    if T["kicker"]:
        d.rounded_rectangle([PAD - int(h * 0.013), ky - int(h * 0.013),
                             PAD + kw + int(h * 0.013), ky + fk.size * 1.30],
                            radius=int(fk.size * 0.52), outline=(255, 255, 255, 240),
                            width=max(1, int(h * 0.0032)))
        draw_tracked(d, (PAD, ky), T["kicker"], fk, (250, 250, 250),
                     int(h * 0.0026), stroke=max(1, SW // 2))
    if T["badge"]:
        fr = load_font(F["sans"], h * 0.033)
        rx = w - PAD - text_width(T["badge"], fr, int(h * 0.0022))
        draw_tracked(d, (rx, ky + fk.size * 0.03), T["badge"], fr, GOLD,
                     int(h * 0.0022), stroke=max(1, SW // 2))
    return im


def layout_wide(im, T, PAL, F, side=0.60, power=0.85, strength=236,
                scrim=True, stroke_scale=1.0):
    """左右分栏：左栏承载全部文字，右侧保留主体。适用于 16:9 / 2:1 / 21:9 等宽画幅。

    side/power 见 h_scrim 的说明。scrim=False 时完全不加压暗（纯靠描边），
    适合主体本身已经很暗（如深色西装、夜戏）的画面。
    """
    if scrim:
        im = h_scrim(im, side, strength, power=power)
        im = v_scrim(im, 0.26, 165, "bottom", power=1.6)
        im = v_scrim(im, 0.16, 130, "top", power=1.8)
    w, h = im.size
    d = ImageDraw.Draw(im)
    PAD = int(h * 0.098)
    ZA, GOLD = PAL["accent"], PAL["accent2"]
    SW = max(2, int(h * 0.0055 * stroke_scale))

    # --- tag 胶囊
    ft = load_font(F["sans"], h * 0.036)
    tw_ = text_width(T["tag"], ft, int(h * 0.0032))
    bw, bh = int(tw_ + h * 0.056), int(h * 0.082)
    py = int(h * 0.108)
    box = Image.new("RGBA", (max(1, bw), max(1, bh)), (0, 0, 0, 0))
    ImageDraw.Draw(box).rounded_rectangle([0, 0, bw - 1, bh - 1],
                                          radius=int(bh * 0.26), fill=ZA + (245,))
    im.paste(box, (PAD, py), box)
    d = ImageDraw.Draw(im)
    draw_tracked(d, (PAD + int(h * 0.024), py + (bh - ft.size * 1.30) / 2), T["tag"], ft,
                 (255, 255, 255), int(h * 0.0032), stroke=max(1, SW // 2))

    # --- 主标题
    fb = fit_font(F["title"], T["title"], h * 0.160, int((w - PAD * 2) * 0.86))
    ys = int(h * 0.300)
    soft_shadow(d, (PAD, ys), T["title"], fb, layers=14, alpha=24)
    d.text((PAD, ys), T["title"], font=fb, fill=(255, 255, 255),
           stroke_width=SW, stroke_fill=(0, 0, 0, 205))
    ry, _bb = band_y(d, fb, T["title"], PAD, ys)   # P1-9 真实字形底边
    d.rectangle([PAD, ry, PAD + int(w * 0.058), ry + max(4, int(h * 0.010))], fill=ZA)

    # --- 副标两行
    fs = _sub_font(F["body"], T, h * 0.054, w - PAD * 2)   # P1-10 副标自适应
    ys1 = ry + int(h * 0.055)
    ys2 = ys1 + int(fs.size * 1.30)
    for txt, yy, col in ((T["sub1"], ys1, (255, 255, 255)), (T["sub2"], ys2, GOLD)):
        if not txt:
            continue
        soft_shadow(d, (PAD, yy), txt, fs, layers=9, alpha=30)
        d.text((PAD, yy), txt, font=fs, fill=col,
               stroke_width=max(2, SW - 1), stroke_fill=(0, 0, 0, 200))

    # --- 底部 kicker（左） / badge（右）
    fk = load_font(F["sans"], h * 0.032)
    kw = text_width(T["kicker"], fk, int(h * 0.0028))
    ky = h - PAD - fk.size * 1.05
    if T["kicker"]:
        d.rounded_rectangle([PAD - int(h * 0.012), ky - int(h * 0.012),
                             PAD + kw + int(h * 0.012), ky + fk.size * 1.28],
                            radius=int(fk.size * 0.52), outline=(255, 255, 255, 245),
                            width=max(1, int(h * 0.0032)))
        draw_tracked(d, (PAD, ky), T["kicker"], fk, (250, 250, 250),
                     int(h * 0.0028), stroke=max(1, SW // 2))
    if T["badge"]:
        fr = load_font(F["sans"], h * 0.031)
        rx = w - PAD - text_width(T["badge"], fr, int(h * 0.0024))
        draw_tracked(d, (rx, ky + fk.size * 0.04), T["badge"], fr, GOLD,
                     int(h * 0.0024), stroke=max(1, SW // 2))
    return im


def layout_vertical(im, T, PAL, F, stroke_scale=1.0):
    """海报式竖版（9:16 / 2:3 / 4:3 竖）：文字块集中画面下部，tag 紧跟标题上方，
    把画面上部完整留给主体。

    与 stacked 的关键区别是 **tag 不置于画面顶边**——竖长画幅里顶边离正文太远，
    标签会与文字块脱节，读者需要跳视两次才能把「题材」与「剧名」关联起来。
    """
    w, h = im.size
    d = ImageDraw.Draw(im)
    PAD = int(w * 0.055)
    ZA, GOLD = PAL["accent"], PAL["accent2"]
    SW = max(2, int(h * 0.0042 * stroke_scale))

    fs = _sub_font(F["body"], T, h * 0.0335, w - PAD * 2)   # P1-10 副标自适应
    step = int(fs.size * 1.28)
    fb = fit_font(F["title"], T["title"], h * 0.098, w - PAD * 2)

    # 反向排布：底部 kicker → 副标 2 → 副标 1 → 主标题 → tag
    fk = load_font(F["sans"], h * 0.019)
    ky = h - int(h * 0.050) - fk.size
    base = ky - int(h * 0.022)
    y_sub2 = base - step
    y_sub1 = y_sub2 - step
    y_title = y_sub1 - int(fb.size * 1.40)

    if T["tag"]:
        ft = load_font(F["sans"], h * 0.0235)
        tw_ = text_width(T["tag"], ft, int(h * 0.0018))
        bw, bh = int(tw_ + h * 0.036), int(h * 0.054)
        py = y_title - bh - int(h * 0.026)
        box = Image.new("RGBA", (max(1, bw), max(1, bh)), (0, 0, 0, 0))
        ImageDraw.Draw(box).rounded_rectangle([0, 0, bw - 1, bh - 1],
                                              radius=int(bh * 0.26), fill=ZA + (245,))
        im.paste(box, (PAD, py), box)
        d = ImageDraw.Draw(im)
        draw_tracked(d, (PAD + int(h * 0.015), py + (bh - ft.size * 1.30) / 2),
                     T["tag"], ft, (255, 255, 255), int(h * 0.0018),
                     stroke=max(1, SW // 2))

    d.text((PAD, y_title), T["title"], font=fb, fill=(255, 255, 255),
           stroke_width=SW, stroke_fill=(0, 0, 0, 205))
    ry, _bb = band_y(d, fb, T["title"], PAD, y_title)   # P1-9 真实字形底边
    d.rectangle([PAD, ry, PAD + int(w * 0.13), ry + max(3, int(h * 0.0035))], fill=ZA)

    for txt, yy, col in ((T["sub1"], y_sub1, (255, 255, 255)), (T["sub2"], y_sub2, GOLD)):
        if not txt:
            continue
        d.text((PAD, yy), txt, font=fs, fill=col,
               stroke_width=max(2, SW - 1), stroke_fill=(0, 0, 0, 200))

    if T["kicker"]:
        kw = text_width(T["kicker"], fk, int(h * 0.0022))
        d.rounded_rectangle([PAD - int(h * 0.010), ky - int(h * 0.010),
                             PAD + kw + int(h * 0.010), ky + fk.size * 1.28],
                            radius=int(fk.size * 0.52), outline=(255, 255, 255, 245),
                            width=max(1, int(h * 0.0028)))
        draw_tracked(d, (PAD, ky), T["kicker"], fk, (250, 250, 250),
                     int(h * 0.0022), stroke=max(1, SW // 2))
    if T["badge"]:
        fr = load_font(F["sans"], h * 0.0185)
        rx = w - PAD - text_width(T["badge"], fr, int(h * 0.002))
        draw_tracked(d, (rx, ky + fk.size * 0.04), T["badge"], fr, GOLD,
                     int(h * 0.002), stroke=max(1, SW // 2))
    return im


def pick_layout(w, h, explicit="auto"):
    """按宽高比自动判定布局。显式指定 layout 时优先。"""
    if explicit and explicit != "auto":
        return explicit
    a = w / float(h)
    if a >= 1.45:
        return "wide"
    if a <= 0.85:
        return "vertical"
    return "stacked"


# ---------------------------------------------------------------- 主流程


def build_cover(spec, item, out_dir):
    w, h = item["size"]
    pal = {
        "accent": _hex2rgb(spec.get("palette", {}).get("accent"), (138, 21, 56)),
        "accent2": _hex2rgb(spec.get("palette", {}).get("accent2"), (233, 199, 156)),
    }
    F = {
        "title": resolve_family(spec.get("fonts", {}).get("title"), "title"),
        "body": resolve_family(spec.get("fonts", {}).get("body"), "body"),
        "sans": resolve_family(spec.get("fonts", {}).get("sans"), "sans"),
    }
    # 文案：全局 spec.text 打底，covers[].text 做逐张覆盖。
    # 逐张覆盖用于 A/B 方案（同一剧集不同 tag/副标）与多语言版本。
    merged = dict(spec.get("text") or {})
    merged.update(item.get("text") or {})
    T = {k: (merged.get(k) or "") for k in
         ("tag", "title", "sub1", "sub2", "kicker", "badge")}
    if not T["title"]:
        raise ValueError("剧名不能为空（请设置 spec.text.title）")

    im, hx, vy = cover_crop(item["src"], w, h, item.get("focus", 0.38))
    im = ImageEnhance.Color(im).enhance(item.get("saturation", 1.06))

    layout = pick_layout(w, h, item.get("layout", "auto"))
    ss = item.get("stroke_scale", 1.0)

    if layout == "wide":
        im = layout_wide(im, T, pal, F,
                         side=item.get("side", 0.60),
                         power=item.get("power", 0.85),
                         strength=item.get("strength", 236),
                         scrim=item.get("scrim", True), stroke_scale=ss)
    elif layout == "vertical":
        im = v_scrim(im, 0.42, 225, "bottom")
        im = layout_vertical(im, T, pal, F, stroke_scale=ss)
    else:
        im = v_scrim(im, 0.36, 215, "bottom")
        im = v_scrim(im, 0.30, 200, "top")
        im = layout_stacked(im, T, pal, F, stroke_scale=ss)

    name = item.get("name") or f"cover_{w}x{h}"
    base = os.path.join(out_dir, name)
    exp = spec.get("export", {})
    saved = []
    if exp.get("png", True):
        p = base + ".png"
        im.save(p, "PNG", optimize=True)
        saved.append(p)
    if exp.get("jpg", True):
        p = base + ".jpg"
        im.convert("RGB").save(p, "JPEG", quality=exp.get("jpg_quality", 92),
                               optimize=True, subsampling=0)
        saved.append(p)

    note = ""
    if hx == 0:
        note += " [水平零余量:主体无法左右平移]"
    if vy == 0:
        note += " [垂直零余量]"
    print(f"  [{layout:8s}] {name:34s} {w}x{h}  ratio={w/h:.4f}  focus={item.get('focus', 0.38)}{note}")
    return im, saved, layout


def build_preview(images, out_dir, name="preview_sheet.png", cols=2, cell_w=620):
    """拼版预览。各图保持自身宽高比居中放置（contain），绝不拉伸变形——
    混排 16:9 与 9:16 时若按统一比例缩放，画面会被压扁，评审时容易误判。"""
    if len(images) < 2:
        return None
    cell_h = int(cell_w * max(im.size[1] / im.size[0] for im in images))
    cols = max(1, min(cols, len(images)))
    rows = (len(images) + cols - 1) // cols
    GAP = 20
    W = cols * cell_w + GAP * (cols + 1)
    H = rows * cell_h + GAP * (rows + 1)
    sheet = Image.new("RGB", (W, H), (240, 242, 245))
    for i, im in enumerate(images):
        r, c = divmod(i, cols)
        s = min(cell_w / im.size[0], cell_h / im.size[1])
        nw, nh = max(1, int(im.size[0] * s)), max(1, int(im.size[1] * s))
        tile = im.convert("RGB").resize((nw, nh), Image.LANCZOS)
        ox = GAP + c * (cell_w + GAP) + (cell_w - nw) // 2
        oy = GAP + r * (cell_h + GAP) + (cell_h - nh) // 2
        sheet.paste(tile, (ox, oy))
    p = os.path.join(out_dir, name)
    sheet.save(p, "PNG", optimize=True)
    print(f"  [preview ] {p} {W}x{H}")
    return p


EXAMPLE_SPEC = {
    "out_dir": "./covers",
    "palette": {"accent": "#8A1538", "accent2": "#E9C79C"},
    "fonts": {
        "title": ["georgiab.ttf"],
        "body": ["georgia.ttf"],
        "sans": ["seguisb.ttf"],
    },
    "text": {
        "tag": "VENGANZA FAMILIAR",
        "title": "VUELO 603",
        "sub1": "ME HUMILLARON,",
        "sub2": "AHORA SOY LA DUEÑA",
        "kicker": "60 EPISODIOS",
        "badge": "ESPAÑOL · 18-44",
    },
    "covers": [
        {"src": "assets/characters/valentina_00.png", "size": [1000, 750],
         "name": "cover_3x4_1000x750", "focus": 0.34},
        {"src": "assets/scenes/scene_tarmac_00.png", "size": [1440, 1920],
         "name": "cover_4x3_1440x1920", "focus": 0.30},
        {"src": "assets/characters/valentina_00.png", "size": [1920, 1080],
         "name": "cover_16x9_1920x1080", "focus": 0.115, "side": 0.58, "power": 0.78},
    ],
    "export": {"png": True, "jpg": True, "jpg_quality": 92, "preview": True},
}


def release_dir_of(ws):
    """`<工作区>/09-发行`（读 layout.json 的 stages.release，缺省 09-发行）。

    刻意**不导入** `_layout` / `_ws`：本脚本可以在任意工作区之外单独用（只给 --spec），
    那两个模块在导入期就要解析工作区，会把「只想生成一张封面」的调用变成一次工作区校验。
    """
    lay = os.path.join(ws, "layout.json")
    name = "09-发行"
    try:
        with open(lay, encoding="utf-8-sig") as f:
            name = (json.load(f).get("stages") or {}).get("release") or name
    except (OSError, ValueError):
        pass
    return os.path.join(ws, name)


_LAYOUT_PAD = {"stacked": ("w", 0.052), "wide": ("h", 0.098), "vertical": ("w", 0.055)}
_LAYOUT_TITLE = {"stacked": 0.185, "wide": 0.160, "vertical": 0.098}
_LAYOUT_SUB = {"stacked": 0.056, "wide": 0.054, "vertical": 0.0335}


def check_items(items, spec):
    """出图前体检：返回 (errors, warnings, rows)。

    errors  = 必须修（缺字段 / 源图不存在 / 尺寸过小）
    warnings = 会「静默变差」但不至于失败的三类（本次反馈的核心）：
        ① P1-10 文字溢出：先算清楚「要缩到多少 px」，而不是等出图后肉眼看裁字；
        ② P1-11 窄源图转宽幅：水平零余量，横幅必被裁成一条躯干；
        ③ wide 布局下左栏可用宽不足（标题会缩得很小，提示换构图）。
    """
    errs, warns, rows = [], [], []
    text = dict(spec.get("text") or {})
    for idx, it in enumerate(items):
        name = it.get("name") or ("covers[%d]" % idx)
        for k in ("src", "size"):
            if k not in it:
                errs.append("%s 缺字段 %s" % (name, k))
        src = it.get("src", "")
        if not os.path.isfile(src):
            errs.append("%s 源图不存在：%s" % (name, src))
        w, h = it.get("size", [0, 0])
        if w < 64 or h < 64:
            errs.append("%s 尺寸过小：%sx%s" % (name, w, h))
            continue
        if not os.path.isfile(src):
            continue

        layout = pick_layout(w, h, it.get("layout", "auto"))
        try:
            sw, sh = Image.open(src).size
        except Exception as e:                                # noqa: BLE001
            errs.append("%s 源图读不出来：%s" % (name, e))
            continue

        merged = dict(text)
        merged.update(it.get("text") or {})
        T = {k: (merged.get(k) or "") for k in ("tag", "title", "sub1", "sub2", "kicker", "badge")}

        # ---------- P1-11：源图比目标更窄 + 目标是宽幅 ----------
        src_ratio, tgt_ratio = sw / float(sh), w / float(h)
        if layout == "wide" and src_ratio < tgt_ratio - 0.02:
            warns.append(
                "%s：源图 %dx%d（比例 %.2f）比目标 %dx%d（比例 %.2f）**更窄** ⇒ 水平零余量，"
                "横幅会被裁成一条躯干。这一档请单独用横版底图（spec 每项可独立 src）。"
                % (name, sw, sh, src_ratio, w, h, tgt_ratio))

        # ---------- P1-10：文字溢出预判 ----------
        pad_key, pad_ratio = _LAYOUT_PAD[layout]
        PAD = int((w if pad_key == "w" else h) * pad_ratio)
        usable = w - PAD * 2
        F = {k: resolve_family(spec.get("fonts", {}).get(k), k) for k in ("title", "body", "sans")}

        def _report(label, txt, fp, target, limit, key):
            if not txt:
                return None
            base = max(8, int(target))
            need = ImageFont.truetype(fp, base).getlength(txt)
            fitted = fit_font(fp, txt, base, limit)
            if need > limit + 0.5:
                warns.append("%s：%s 在 %dx%d 下会溢出（%dpx 时字宽 %.0f > 可用 %d），"
                             "已自动收缩到 %dpx；若缩得太小请改文案或换画幅。"
                             % (name, label, w, h, base, need, limit, fitted.size))
            elif fitted.size < base:
                warns.append("%s：%s 自动收缩 %dpx → %dpx（仍在可用宽内，仅提示）"
                             % (name, label, base, fitted.size))
            return fitted.size

        _report("主标题", T["title"], F["title"], _LAYOUT_TITLE[layout] * h,
                int(usable * 0.86) if layout == "wide" else usable, "title")
        sub_long = max([T["sub1"], T["sub2"]], key=len) if (T["sub1"] or T["sub2"]) else ""
        sub_px = _report("副标", sub_long, F["body"], _LAYOUT_SUB[layout] * h, usable, "sub")

        rows.append({"name": name, "src": os.path.basename(src), "src_size": (sw, sh),
                     "size": (w, h), "layout": layout,
                     "src_ratio": round(src_ratio, 3), "tgt_ratio": round(tgt_ratio, 3),
                     "sub_px": sub_px})
    return errs, warns, rows


def main():
    ap = argparse.ArgumentParser(description="短剧/影视发行封面生成引擎（仓库真源版）")
    ap.add_argument("--spec", help="封面配置 JSON 路径")
    ap.add_argument("--write-example", metavar="PATH", help="导出示例配置后退出")
    ap.add_argument("--check", action="store_true", help="只校验配置/尺寸/取景/溢出，不出图")
    ap.add_argument("--workspace", default=None, metavar="DIR",
                    help="工作区；spec 未写 out_dir 时默认落 <工作区>/<发行目录>/封面/")
    ap.add_argument("--out-dir", dest="out_dir", default=None, metavar="DIR",
                    help="强制指定输出目录（优先于 spec.out_dir）")
    a = ap.parse_args()

    if a.write_example:
        with open(a.write_example, "w", encoding="utf-8", newline="\n") as f:
            json.dump(EXAMPLE_SPEC, f, ensure_ascii=False, indent=2)
        print("已写出示例配置：%s" % a.write_example)
        return 0

    if not a.spec:
        ap.error("需要 --spec <file>（或用 --write-example 导出模板）")

    with open(a.spec, encoding="utf-8-sig") as f:
        spec = json.load(f)

    items = spec.get("covers") or []
    if not items:
        print("[FATAL] spec.covers 为空")
        return 1

    # 路径基准统一为「spec 文件所在目录」，不随调用时的 cwd 漂移。
    # （否则 src 相对 cwd、out_dir 相对 spec，两套规则会让人踩坑）
    spec_dir = os.path.dirname(os.path.abspath(a.spec))
    for it in items:
        src = it.get("src", "")
        if src and not os.path.isabs(src):
            it["src"] = os.path.normpath(os.path.join(spec_dir, src))

    errs, warns, rows = check_items(items, spec)
    if errs:
        for e in errs:
            print("[ERR] %s" % e)
        return 1
    for wmsg in warns:
        print("[WARN] %s" % wmsg)

    print("== cover_forge ==  spec=%s  共 %d 张  layout 自动判定" % (a.spec, len(items)))
    if a.check:
        for r in rows:
            print("  [check   ] %-28s %4dx%-4d -> %4dx%-4d  layout=%-8s src_ratio=%.3f tgt=%.3f%s"
                  % (r["src"], r["src_size"][0], r["src_size"][1], r["size"][0], r["size"][1],
                     r["layout"], r["src_ratio"], r["tgt_ratio"],
                     "" if r["sub_px"] is None else ("  sub=%dpx" % r["sub_px"])))
        print("== 校验通过 ==" + ("（%d 条告警，见上；不影响出图）" % len(warns) if warns else ""))

    # ---- 输出目录：--out-dir > spec.out_dir > <工作区>/<发行目录>/封面 > spec 目录 ----
    if a.out_dir:
        out_dir = a.out_dir
    elif spec.get("out_dir"):
        out_dir = spec["out_dir"]
    elif a.workspace or os.environ.get("SOLODRAMA_WORKSPACE") or os.environ.get("DRAMA_WORKSPACE"):
        ws = a.workspace or os.environ.get("SOLODRAMA_WORKSPACE") or os.environ.get("DRAMA_WORKSPACE")
        out_dir = os.path.join(release_dir_of(os.path.abspath(ws)), "封面")
    else:
        out_dir = spec_dir
    if not os.path.isabs(out_dir):
        out_dir = os.path.join(spec_dir, out_dir)
    print("   输出目录：%s" % out_dir)
    if a.check:
        return 0

    os.makedirs(out_dir, exist_ok=True)
    imgs, lays = [], []
    for it in items:
        im, _, lay = build_cover(spec, it, out_dir)
        imgs.append(im)
        lays.append(lay)

    if spec.get("export", {}).get("preview", True):
        build_preview(imgs, out_dir)

    print("== 完成 ==  出图 %d 张 (layout: %s)"
          % (len(imgs), ", ".join(sorted(set(lays)))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
