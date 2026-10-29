#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""delivery_spec.py —— 交付规格唯一真源 + 规格体检 / 归一化（2026-10-30 新增）

为什么有它（平台驳回「检测到视频画面中存在黑边」的根因）
------------------------------------------------------
画面里**没有黑边**，`cropdetect` 全片 1466 帧都返回满幅。真正的成因是**交付规格的
显示比例不是 9:16**，平台按显示比例重新适配播放器时补出了边：

| 环节 | 尺寸 | SAR | DAR |
|---|---|---|---|
| H3 出片（`megapixels=0.8` + 32 对齐） | 672×1216 | 1:1 | 21:38 = 0.5526 |
| 放大产物（RH_Astra 按源比例吸附） | 1062×1920 | 1:1 | 177:320 = 0.5531 |
| 交付层（`scale=1080:1920` 硬凑容器） | 1080×1920 | **59:60** | 177:320 = 0.5531 |
| 平台 9:16 播放器 | 1080×1920 | 1:1 | 9:16 = **0.5625** |

偏差 1.69%。平台把 DAR 177:320 的内容塞进 9:16 容器，只能补边：
按高适配 ⇒ 左右各 9px；按宽适配 ⇒ 上下各 16px。**每集每帧必然触发**，
所以「黑边」是三类驳回里最高频的一项，且**本地自查永远查不出**——
像素是被拉伸的，没有黑。

`1080×1920 + SAR 59:60` 这种写法是「用非方形像素骗过容器」，容器元数据看着对，
实际显示比例是错的。平台不吃这一套。

本模块的职责
------------
1. `SPEC` —— 发布规格的**唯一定义**（别处不许再写字面量 1080/1920）
2. `probe()` —— 读出真实显示比例（width × SAR，不是 width）
3. `judge()` —— 判定是否符合规格，返回可读的违规项
4. `normalize()` —— **crop-to-fill** 归一化（放大到刚好覆盖 → 中心裁切 → SAR=1:1），
   **绝不用 pad**：补边就是制造黑边，等于把问题原样交给平台
5. `edge_band()` —— 内容层黑边检测（生成段自带黑边时才用得上，规格修正后应恒为 0）

用法
----
    python delivery_spec.py probe "Episode01.mp4"
    python delivery_spec.py check "Episode01.mp4"                 # 退出码 0/2
    python delivery_spec.py normalize "in.mp4" -o "out.mp4"       # crop-to-fill
    python delivery_spec.py fix-dir --workspace "D:/剧/新剧" --ep ep01

退出码：0 = 合规；2 = 不合规 / 修复失败
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

# ---------------------------------------------------------------------------
# 发布规格（唯一真源）
# ---------------------------------------------------------------------------
# ★ 改这里等于改全链路。1080×1920 / SAR 1:1 / 9:16 是平台竖屏发布口径；
#   横屏项目用 --target 1920x1080 覆盖，不要改常量。
SPEC = {
    "width": 1080,
    "height": 1920,
    "ratio": 9.0 / 16.0,        # 0.5625
    "sar": (1, 1),
    "pix_fmt": "yuv420p",
    "fps": 24,
}

# 显示比例容差：0.3% ≈ 3px/1080。比这更松就抓不住 1.69% 这个量级的偏差了。
RATIO_TOL = 0.003
# SAR 容差：只接受方形像素（1:1）。SAR 不是 1 就是「用元数据骗容器」。
SAR_TOL = 0.005


def target_from_str(s, base=None):
    """'1080x1920' → dict(spec)。给了就整份替换，避免只改一半。"""
    base = dict(base or SPEC)
    if not s:
        return base
    m = re.match(r"^\s*(\d{2,5})\s*[xX×]\s*(\d{2,5})\s*$", str(s))
    if not m:
        raise ValueError("目标规格必须写成 1080x1920，收到：%r" % (s,))
    w, h = int(m.group(1)), int(m.group(2))
    base.update({"width": w, "height": h, "ratio": float(w) / float(h)})
    return base


# ---------------------------------------------------------------------------
# ffprobe
# ---------------------------------------------------------------------------
def _ffprobe(root=None):
    return os.path.join(root, "ffprobe") if root else "ffprobe"


def _ffmpeg(root=None):
    return os.path.join(root, "ffmpeg") if root else "ffmpeg"


def _run(cmd, timeout=120):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          timeout=timeout)


def _parse_ratio(txt, default=(1, 1)):
    """'59:60' → (59, 60)；'1/1'、'N/A' 也吃得下。"""
    if not txt:
        return default
    txt = str(txt).strip()
    if txt in ("N/A", "0:1", "0/0", ""):
        return default
    m = re.match(r"^(\d+)\s*[:/]\s*(\d+)$", txt)
    if not m:
        return default
    n, d = int(m.group(1)), int(m.group(2))
    return (n, d) if n and d else default


def probe(path, ffprobe=None):
    """读一条视频的真实规格。返回 dict；读不出抛 RuntimeError。"""
    cmd = [ffprobe or "ffprobe", "-v", "error", "-select_streams", "v:0",
           "-show_entries",
           "stream=width,height,sample_aspect_ratio,display_aspect_ratio,pix_fmt,"
           "r_frame_rate,nb_frames,duration",
           "-of", "json", str(path)]
    p = _run(cmd)
    if p.returncode != 0:
        raise RuntimeError("ffprobe 失败（rc=%d）：%s" % (p.returncode, path))
    try:
        st = (json.loads(p.stdout.decode("utf-8", "replace")).get("streams") or [])[0]
    except (ValueError, IndexError):
        raise RuntimeError("ffprobe 输出无法解析：%s" % path)

    w, h = int(st.get("width") or 0), int(st.get("height") or 0)
    if not w or not h:
        raise RuntimeError("读不到分辨率：%s" % path)
    sar_n, sar_d = _parse_ratio(st.get("sample_aspect_ratio"), (1, 1))

    # ★ 真实显示宽度 = 像素宽 × SAR。这就是平台看到的宽度，也是黑边的判据来源。
    display_w = w * (float(sar_n) / float(sar_d))
    fps = st.get("r_frame_rate") or "0/1"
    try:
        fn, fd = (int(x) for x in fps.split("/"))
        fps_f = (float(fn) / fd) if fd else 0.0
    except (ValueError, ZeroDivisionError):
        fps_f = 0.0

    return {
        "path": str(path),
        "width": w, "height": h,
        "sar": "%d:%d" % (sar_n, sar_d),
        "sar_n": sar_n, "sar_d": sar_d,
        "dar": st.get("display_aspect_ratio") or "",
        "display_w": round(display_w, 2),
        "display_ratio": round(display_w / float(h), 6),
        "pix_ratio": round(w / float(h), 6),
        "pix_fmt": st.get("pix_fmt") or "",
        "fps": round(fps_f, 3),
        "frames": int(st.get("nb_frames") or 0) or None,
    }


# ---------------------------------------------------------------------------
# 判定
# ---------------------------------------------------------------------------
def judge(p, spec=None):
    """返回违规项列表（人话，可直接打印）。空列表 = 合规。

    ★ 判据顺序刻意把 SAR 放第一条：它是「黑边」的直接原因，
      先报它，人一眼就知道该改什么。
    """
    spec = dict(spec or SPEC)
    out = []
    tw, th = int(spec["width"]), int(spec["height"])
    tr = float(spec["ratio"])

    sar_actual = float(p["sar_n"]) / float(p["sar_d"])
    if abs(sar_actual - 1.0) > SAR_TOL:
        out.append(
            "SAR=%s（非方形像素）—— 用拉伸像素骗容器，平台按显示比例重算后会补边。"
            "必须重采样成 SAR=1:1" % p["sar"])

    if abs(p["display_ratio"] - tr) / tr > RATIO_TOL:
        out.append(
            "显示比例 %.4f（%d×%d 按 SAR %s 折算=%.0f×%d）≠ 目标 %.4f（%d:%d）"
            "，偏差 %.2f%% ⇒ 平台适配 9:16 播放器时必然补黑边"
            % (p["display_ratio"], p["width"], p["height"], p["sar"],
               p["display_w"], p["height"], tr, tw, th,
               abs(p["display_ratio"] - tr) / tr * 100.0))

    if (p["width"], p["height"]) != (tw, th):
        out.append("像素尺寸 %d×%d ≠ 目标 %d×%d"
                   % (p["width"], p["height"], tw, th))

    if spec.get("pix_fmt") and p["pix_fmt"] and p["pix_fmt"] != spec["pix_fmt"]:
        out.append("像素格式 %s ≠ %s（部分平台拒收 10bit/4:4:4）"
                   % (p["pix_fmt"], spec["pix_fmt"]))
    return out


def is_ok(p, spec=None):
    return not judge(p, spec)


# ---------------------------------------------------------------------------
# 内容层黑边检测（零依赖：crop + signalstats）
# ---------------------------------------------------------------------------
def edge_band(path, band=4, sample_every=45, ffmpeg=None, timeout=180):
    """检测四边是否存在**纯色暗边**（内容层黑边）。

    判据不是「暗」而是「纯」：真实夜景有噪点和渐变（YHIGH−YLOW 大），
    补边是恒定色（YHIGH−YLOW 极小）。两个条件同时满足才算黑边。
    返回 {left,right,top,bottom} 像素数（0 = 无）。
    """
    try:
        p = probe(path)
    except RuntimeError:
        return {"error": "unreadable"}
    w, h = p["width"], p["height"]
    band = max(2, min(int(band), w // 8, h // 8))
    boxes = {
        "left": "crop=%d:%d:0:0" % (band, h),
        "right": "crop=%d:%d:%d:0" % (band, h, w - band),
        "top": "crop=%d:%d:0:0" % (w, band),
        "bottom": "crop=%d:%d:0:%d" % (w, band, h - band),
    }
    out = {}
    for side, crop in boxes.items():
        vf = ("select='not(mod(n\\,%d))',%s,signalstats,metadata=print:file=-"
              % (max(1, int(sample_every)), crop))
        cmd = [ffmpeg or "ffmpeg", "-hide_banner", "-nostats", "-v", "error",
               "-i", str(path), "-vf", vf, "-f", "null", "-"]
        try:
            r = _run(cmd, timeout=timeout)
        except subprocess.TimeoutExpired:
            out[side] = None
            continue
        txt = r.stdout.decode("utf-8", "replace")
        yavg = [float(x) for x in re.findall(r"signalstats\.YAVG=([\d.]+)", txt)]
        ylow = [float(x) for x in re.findall(r"signalstats\.YLOW=([\d.]+)", txt)]
        yhigh = [float(x) for x in re.findall(r"signalstats\.YHIGH=([\d.]+)", txt)]
        if not yavg:
            out[side] = None
            continue
        # 跨帧一致才判边：中位数暗 + 中位数动态范围小
        pairs = sorted(zip(yavg, [hi - lo for lo, hi in zip(ylow, yhigh)]))
        med_avg = pairs[len(pairs) // 2][0]
        med_range = sorted(hi - lo for lo, hi in zip(ylow, yhigh))[len(pairs) // 2]
        dark = med_avg <= 20.0
        flat = med_range <= 14.0
        out[side] = band if (dark and flat) else 0
    return out


def any_edge(v):
    return isinstance(v, dict) and any((v.get(k) or 0) > 0 for k in ("left", "right", "top", "bottom"))


# ---------------------------------------------------------------------------
# 归一化：crop-to-fill（绝不用 pad）
# ---------------------------------------------------------------------------
def build_normalize_vf(spec=None, fps=None):
    """生成 crop-to-fill 滤镜串。

    三步，顺序不能换：
      ① `scale=trunc(iw*sar/2)*2:ih` —— 先把非方形像素**还原成真实显示宽度**，
         否则后面的 scale 会接着沿用那 1.69% 的拉伸，改了个寂寞。
      ② `scale=W:H:force_original_aspect_ratio=increase` —— 放大到**刚好覆盖**目标，
         不留任何余量（用 decrease 就会留边，再 pad 就是黑边）。
      ③ `crop=W:H` —— 中心裁切（ffmpeg 默认居中）。裁掉的是 1.69% 的边缘，
         比补黑边可接受得多：平台宁可要构图略紧，也不要一条边。
    """
    spec = dict(spec or SPEC)
    w, h = int(spec["width"]), int(spec["height"])
    vf = ("scale=trunc(iw*sar/2)*2:ih,setsar=1,"
          "scale=%d:%d:force_original_aspect_ratio=increase:flags=lanczos,setsar=1,"
          "crop=%d:%d,setsar=1" % (w, h, w, h))
    if fps and float(spec.get("fps") or 0) > 0:
        vf += ",fps=%s" % (("%g" % float(spec["fps"])))
    return vf


def normalize(src, dst, spec=None, *, crf=17, preset="medium", copy_audio=True,
              ffmpeg=None, timeout=1800):
    """把 src 归一化到 spec 并写 dst。返回 (ok, 信息)。"""
    spec = dict(spec or SPEC)
    vf = build_normalize_vf(spec)
    cmd = [ffmpeg or "ffmpeg", "-hide_banner", "-nostats", "-v", "error", "-y",
           "-i", str(src), "-vf", vf,
           "-c:v", "libx264", "-crf", str(crf), "-preset", str(preset),
           "-pix_fmt", spec.get("pix_fmt", "yuv420p"),
           "-c:a", "copy" if copy_audio else "aac",
           "-movflags", "+faststart", str(dst)]
    try:
        r = _run(cmd, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "ffmpeg 超时（%ds）" % timeout
    if r.returncode != 0:
        return False, "ffmpeg rc=%d" % r.returncode
    try:
        np_ = probe(dst)
    except RuntimeError as e:
        return False, str(e)
    bad = judge(np_, spec)
    if bad:
        return False, "归一化后仍不合规：" + "；".join(bad)
    return True, "→ %d×%d SAR %s（crop-to-fill）" % (np_["width"], np_["height"], np_["sar"])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _print_probe(p, spec=None):
    print("  文件   : %s" % p["path"])
    print("  像素   : %d×%d   SAR %s   显示 %.0f×%d"
          % (p["width"], p["height"], p["sar"], p["display_w"], p["height"]))
    print("  比例   : 像素 %.4f / 显示 %.4f / 目标 %.4f"
          % (p["pix_ratio"], p["display_ratio"], float((spec or SPEC)["ratio"])))
    print("  编码   : %s  %.3ffps  %s 帧"
          % (p["pix_fmt"], p["fps"], p["frames"] or "?"))


def main() -> int:
    ap = argparse.ArgumentParser(description="交付规格体检 / 归一化（crop-to-fill）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("probe", help="打印真实规格")
    p1.add_argument("files", nargs="+")
    p1.add_argument("--target", default=None, help="目标规格，如 1080x1920")

    p2 = sub.add_parser("check", help="判定是否符合规格（退出码 0/2）")
    p2.add_argument("files", nargs="+")
    p2.add_argument("--target", default=None)
    p2.add_argument("--json", action="store_true")
    p2.add_argument("--edges", action="store_true", help="同时检测内容层黑边（慢）")

    p3 = sub.add_parser("normalize", help="归一化到规格（crop-to-fill，不补边）")
    p3.add_argument("src")
    p3.add_argument("-o", "--out", required=True)
    p3.add_argument("--target", default=None)
    p3.add_argument("--crf", type=int, default=17)

    a = ap.parse_args()
    spec = target_from_str(getattr(a, "target", None))

    if a.cmd == "probe":
        rc = 0
        for f in a.files:
            try:
                _print_probe(probe(f), spec)
            except RuntimeError as e:
                print("  [FAIL] %s" % e)
                rc = 2
        return rc

    if a.cmd == "check":
        rows, bad_total = [], 0
        for f in a.files:
            try:
                p = probe(f)
            except RuntimeError as e:
                rows.append({"file": f, "error": str(e), "violations": ["无法读取"]})
                bad_total += 1
                continue
            v = judge(p, spec)
            edges = edge_band(f) if a.edges else None
            if edges and any_edge(edges):
                v.append("内容层黑边：%s" % json.dumps(edges, ensure_ascii=False))
            if v:
                bad_total += 1
            rows.append({"file": f, "width": p["width"], "height": p["height"],
                         "sar": p["sar"], "display_ratio": p["display_ratio"],
                         "violations": v})
        if a.json:
            print(json.dumps({"target": "%dx%d" % (spec["width"], spec["height"]),
                              "ok": bad_total == 0, "rows": rows},
                             ensure_ascii=False, indent=2))
        else:
            for r in rows:
                mark = "OK  " if not r["violations"] else "FAIL"
                print("[%s] %s" % (mark, os.path.basename(r["file"])))
                if r.get("width"):
                    print("       %d×%d SAR %s 显示比例 %.4f"
                          % (r["width"], r["height"], r["sar"], r["display_ratio"]))
                for v in r["violations"]:
                    print("       - %s" % v)
        return 0 if bad_total == 0 else 2

    if a.cmd == "normalize":
        ok, msg = normalize(a.src, a.out, spec, crf=a.crf)
        print(("[OK] " if ok else "[FAIL] ") + msg)
        return 0 if ok else 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
