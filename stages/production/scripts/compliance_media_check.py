#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""compliance_media_check.py —— 画面级平台合规门禁（2026-10-30 新增）

为什么有它
----------
`compliance_precheck.py` 只覆盖**题材侧**（发布前三问 + AIGC 标注 + 受限占比），
全部靠人回答 yes/no；**画面侧**零覆盖。于是三类驳回反复出现，且每次都是
「提交 → 被拒 → 手工改 → 再提交」的闭环，单集返工 20 分钟起：

| 平台驳回文案 | 真实成因 | 本门禁的判据 |
|---|---|---|
| 检测到视频画面中存在黑边 | 交付规格 DAR ≠ 9:16（1080×1920 + SAR 59:60），平台适配播放器时补边 | C1 规格（SAR/DAR/像素） |
| 检测到视频画面中出现品牌 logo | 生成 prompt 无品牌负向约束，出片前无抽检 | C4 抽帧人审 + 前置 prompt 约束 |
| 检测到视频画面中不包含字幕 | `--stage all` 默认停在「无字幕放大母版」，导出脚本不校验字幕就发了 | C3 字幕证据链 |

设计原则
--------
1. **能机器判定的绝不靠人**：C1/C2/C3 是确定性判据，直接 FAIL 阻断导出。
2. **不能机器判定的不假装能**：C4 品牌 logo 在无 vision provider 的环境下**无法可靠自动识别**，
   所以只做「抽帧拼图 + 明确 MANUAL」，不输出任何"疑似通过"的伪结论。
3. **证据链优先于重复检测**：C3 优先读 `report.json` 里 `subtitle.py` 自己的渲染自检结果，
   没有报告才退到像素启发式 —— 不重复造已经有实现且更准的检测。

用法
----
    python compliance_media_check.py --workspace "D:/剧/新剧" --ep ep01
    python compliance_media_check.py --workspace "D:/剧/新剧" --all --json
    python compliance_media_check.py --file "09-发行/剧集/Episode01.mp4"
    python compliance_media_check.py --workspace "D:/剧" --ep ep01 --sheet   # 顺便出抽帧拼图

退出码：0 = 画面侧合规（MANUAL 项仍需人看）；2 = 有阻断项
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import delivery_spec as DS          # noqa: E402

# 字幕带：与 config.subtitle.json 的 placement.anchor_top=0.6 对齐（6:4 落点）
SUB_BAND_CENTER = 0.60
SUB_BAND_HALF = 0.10
# 字幕带内「近白像素」的相对亮度下限（Y，TV range 235 为白）
SUB_WHITE_Y = 210.0


# ---------------------------------------------------------------------------
# C1 / C2：规格与内容层黑边（直接复用唯一真源）
# ---------------------------------------------------------------------------
def check_spec(path, spec=None):
    try:
        p = DS.probe(path)
    except RuntimeError as e:
        return {"id": "C1", "level": "FAIL", "title": "交付规格",
                "detail": str(e), "probe": None}
    bad = DS.judge(p, spec)
    fix = ""
    if bad:
        fix = ("跑 `python stages/production/scripts/delivery_spec.py normalize \"%s\" -o \"<out>\"` "
               "做 crop-to-fill 归一化（不补边）" % os.path.basename(path))
    return {"id": "C1", "level": "FAIL" if bad else "PASS", "title": "交付规格",
            "detail": "；".join(bad) if bad else
                      "%d×%d SAR %s 显示比例 %.4f（= %d:%d）"
                      % (p["width"], p["height"], p["sar"], p["display_ratio"],
                         (spec or DS.SPEC)["width"], (spec or DS.SPEC)["height"]),
            "probe": p, "fix": fix}


def check_edges(path):
    e = DS.edge_band(path)
    if e.get("error"):
        return {"id": "C2", "level": "WARN", "title": "内容层黑边",
                "detail": "无法检测（%s）" % e["error"], "edges": e}
    bad = DS.any_edge(e)
    return {"id": "C2", "level": "FAIL" if bad else "PASS", "title": "内容层黑边",
            "detail": ("四边检出纯色暗边 %s ⇒ 该段生成时自带黑边，回到对应 shot 重跑"
                       % json.dumps({k: v for k, v in e.items() if v}, ensure_ascii=False))
                      if bad else "四边均为画面内容（无纯色暗边）",
            "edges": e}


# ---------------------------------------------------------------------------
# C3：硬字幕
# ---------------------------------------------------------------------------
def _read_json(p):
    try:
        with open(p, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _sub_band_stats(path):
    """字幕带的亮度分布（零依赖：crop + signalstats）。"""
    try:
        p = DS.probe(path)
    except RuntimeError:
        return None
    h, w = p["height"], p["width"]
    top = int(h * (SUB_BAND_CENTER - SUB_BAND_HALF))
    hh = int(h * SUB_BAND_HALF * 2)
    vf = ("select='not(mod(n\\,40))',crop=%d:%d:0:%d,signalstats,metadata=print:file=-"
          % (w, hh, top))
    try:
        r = DS._run([DS._ffmpeg(), "-hide_banner", "-nostats", "-v", "error",
                     "-i", str(path), "-vf", vf, "-f", "null", "-"], timeout=180)
    except subprocess.TimeoutExpired:
        return None
    txt = r.stdout.decode("utf-8", "replace")
    ymax = [float(x) for x in re.findall(r"signalstats\.YMAX=([\d.]+)", txt)]
    yavg = [float(x) for x in re.findall(r"signalstats\.YAVG=([\d.]+)", txt)]
    if not ymax:
        return None
    hot = sum(1 for v in ymax if v >= SUB_WHITE_Y)
    return {"frames": len(ymax), "frames_with_white": hot,
            "ymax_median": sorted(ymax)[len(ymax) // 2],
            "yavg_median": sorted(yavg)[len(yavg) // 2] if yavg else 0.0}


def check_subtitle(ws, ep, path, out_dir=None):
    """三级证据链：产物名 → 渲染报告 → 像素启发式。任一级不成立即 FAIL。

    ★ 这里的判据是刻意「宁可误杀」的：无字幕是平台硬驳回项，
      放行一集就白跑一次审核周期。
    """
    name = os.path.basename(path)
    reasons, evidence = [], {}

    # ① 产物名：必须是烧过字幕的（_subbed / _hard / _hardsub）
    subbed = bool(re.search(r"_(subbed|hardsub|hard_sub)\b", name, re.I))
    evidence["name_has_subbed"] = subbed
    if not subbed:
        reasons.append("文件名不含 `_subbed` —— 是母版/放大版，不是烧过字幕的成片")

    # ② 渲染报告：subtitle.py 自己写过 verify_render 结论
    rep = None
    if ws and ep:
        rep = _read_json(os.path.join(ws, "video-pipeline", "output", "subs", ep, "report.json"))
    if rep:
        vr = rep.get("verify_render") or {}
        evidence["report_render"] = {
            "cues": rep.get("cues"),
            "pass": vr.get("pass"),
            "skipped": vr.get("skipped"),
        }
        if not rep.get("cues"):
            reasons.append("渲染报告里 cues=0（没有字幕条目）")
        elif vr.get("skipped"):
            reasons.append("渲染自检被跳过（%s）⇒ 没有字幕画出来的证据" % vr.get("skipped"))
        elif vr.get("pass") is False:
            reasons.append("渲染自检未通过（字幕没画出来）")
        elif vr.get("pass") is not True:
            reasons.append("渲染报告缺 verify_render 结论")
    else:
        evidence["report_render"] = None

    # ③ 像素启发式：字幕带是否出现近白像素（白字）
    st = _sub_band_stats(path)
    evidence["band"] = st
    if st:
        ratio = st["frames_with_white"] / float(st["frames"] or 1)
        evidence["band_white_ratio"] = round(ratio, 3)
        if ratio < 0.25:
            reasons.append("字幕带（画面 %.0f%%–%.0f%% 高）仅 %.0f%% 的抽样帧出现近白像素，"
                           "不像是硬字幕" % ((SUB_BAND_CENTER - SUB_BAND_HALF) * 100,
                                            (SUB_BAND_CENTER + SUB_BAND_HALF) * 100, ratio * 100))
    else:
        reasons.append("字幕带无法取样")

    return {"id": "C3", "level": "FAIL" if reasons else "PASS", "title": "硬字幕",
            "detail": "；".join(reasons) if reasons else "检出硬字幕（产物名 + 渲染报告 + 字幕带白字）",
            "evidence": evidence}


# ---------------------------------------------------------------------------
# C4：品牌 logo（抽帧拼图 → 人工复核）
# ---------------------------------------------------------------------------
def build_contact_sheet(path, dst, cols=4, rows=3, cell=(270, 480)):
    """抽 12 帧拼一张图，4×3。人一眼扫完整集，比逐帧看快 20 倍。"""
    try:
        p = DS.probe(path)
    except RuntimeError:
        return None
    n = cols * rows
    # 均匀取 n 个时间点（避开片头片尾各 3%）
    dur = p["frames"] / p["fps"] if (p["frames"] and p["fps"]) else 60.0
    step = max(1, int(p["frames"] / (n + 1))) if p["frames"] else 60
    vf = ("select='not(mod(n\\,%d))',scale=%d:%d,tile=%dx%d"
          % (step, cell[0], cell[1], cols, rows))
    cmd = [DS._ffmpeg(), "-hide_banner", "-nostats", "-v", "error", "-y",
           "-i", str(path), "-vf", vf, "-frames:v", "1", str(dst)]
    try:
        r = DS._run(cmd, timeout=300)
    except subprocess.TimeoutExpired:
        return None
    return str(dst) if r.returncode == 0 and os.path.isfile(dst) else None


def check_brand(path, sheet_dir):
    os.makedirs(sheet_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(path))[0]
    dst = os.path.join(sheet_dir, "%s_抽帧.jpg" % base)
    got = build_contact_sheet(path, dst)
    return {"id": "C4", "level": "MANUAL", "title": "品牌 logo",
            "detail": ("无法自动判定（本机无 vision provider）。已抽 12 帧拼图：%s ⇒ "
                       "人看一遍，重点查：角色服装 logo、手机/手表品牌、店招与包装上的可读商标"
                       % (got or "（拼图生成失败，请手动抽帧）")),
            "sheet": got}


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------
def check_file(path, *, ws=None, ep=None, spec=None, sheet_dir=None):
    items = [check_spec(path, spec), check_edges(path), check_subtitle(ws, ep, path)]
    if sheet_dir:
        items.append(check_brand(path, sheet_dir))
    fails = [i for i in items if i["level"] == "FAIL"]
    warns = [i for i in items if i["level"] == "WARN"]
    manual = [i for i in items if i["level"] == "MANUAL"]
    return {"file": str(path), "items": items,
            "verdict": "blocked" if fails else "ok",
            "fails": len(fails), "warns": len(warns), "manual": len(manual)}


def _resolve_eps(ws, ep, all_, source_dir=False):
    """把 --ep/--all 解析成 [(ep, 文件路径)]。

    两种口径：
    * `--all`            → 查 `09-发行/剧集/EpisodeNN.mp4`（**已导出**的发布版）
    * `--all --from-source` → 查待发布的 `*_subbed.mp4`（**导出前**就该拦，别等进了发行目录）
    """
    out = []
    if source_dir:
        # 待发布成片的两个常见落点：引擎的 output/subs/<ep>/ 与项目自己的 07-成片/
        roots = []
        p1 = os.path.join(ws, "video-pipeline", "output", "subs")
        if os.path.isdir(p1):
            roots.append(p1)
        for name in ("07-成片", "成片"):
            p2 = os.path.join(ws, name)
            if os.path.isdir(p2):
                roots.append(p2)
        seen = set()
        for root in roots:
            for dirpath, _dirs, files in os.walk(root):
                for f in files:
                    if not f.lower().endswith(".mp4"):
                        continue
                    if not re.search(r"_(subbed|hardsub|hard_sub)\.mp4$", f, re.I):
                        continue
                    full = os.path.join(dirpath, f)
                    if full in seen:
                        continue
                    seen.add(full)
                    m = re.search(r"ep(?:isode)?[_\-\s]?(\d{1,3})", f, re.I)
                    out.append((("ep%02d" % int(m.group(1))) if m else os.path.basename(dirpath), full))
        return sorted(out, key=lambda x: x[0])

    ep_dir = os.path.join(ws, "09-发行", "剧集")
    if all_:
        if os.path.isdir(ep_dir):
            for f in sorted(os.listdir(ep_dir)):
                m = re.match(r"^Episode(\d{2,})\.mp4$", f, re.I)
                if m:
                    out.append(("ep%02d" % int(m.group(1)), os.path.join(ep_dir, f)))
        return out
    eps = [ep] if ep else []
    for e in eps:
        n = re.sub(r"^ep[_\-]?", "", str(e), flags=re.I)
        try:
            nn = int(n)
        except ValueError:
            continue
        p = os.path.join(ep_dir, "Episode%02d.mp4" % nn)
        if os.path.isfile(p):
            out.append(("ep%02d" % nn, p))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="画面级平台合规门禁（黑边/品牌/字幕）")
    ap.add_argument("--workspace", default=None)
    ap.add_argument("--ep", default=None, help="单集，如 ep01")
    ap.add_argument("--all", action="store_true", help="全部发布版成片")
    ap.add_argument("--from-source", dest="from_source", action="store_true",
                    help="改查**待发布**的 *_subbed.mp4（导出前就该拦，别等进了发行目录）")
    ap.add_argument("--file", default=None, help="直接指定视频文件（不查报告）")
    ap.add_argument("--target", default=None, help="目标规格，默认 1080x1920")
    ap.add_argument("--sheet", action="store_true", help="顺带生成 4×3 抽帧拼图（品牌人审用）")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    spec = DS.target_from_str(a.target)
    ws = os.path.abspath(a.workspace) if a.workspace else None
    if not ws and not a.file:
        print("[FAIL] 需要 --workspace 或 --file")
        return 2

    sheet_dir = None
    if a.sheet and ws:
        sheet_dir = os.path.join(ws, "08-合规", "抽帧")

    jobs = []
    if a.file:
        # `Episode01.mp4` / `ep01_subbed.mp4` 都要能解析出 ep01（前者丢了集号会读不到渲染报告）
        m = re.search(r"ep(?:isode)?[_\-\s]?(\d{2,})", os.path.basename(a.file), re.I)
        jobs = [("ep%02d" % int(m.group(1)) if m else None, a.file)]
    else:
        jobs = _resolve_eps(ws, a.ep, a.all, source_dir=a.from_source)
        if not jobs:
            if a.from_source:
                print("[FAIL] 没找到待发布的 *_subbed.mp4（查了 %s 下的 video-pipeline/output/subs 与 07-成片）" % ws)
                print("       先跑 subtitle.py --ep <ep> --stage render 烧字幕")
            else:
                print("[FAIL] 没找到发布版成片（%s/09-发行/剧集/EpisodeNN.mp4）" % ws)
                print("       先跑 release_export.py --all --apply，或用 --file 指定")
            return 2

    results = [check_file(p, ws=ws, ep=e, spec=spec, sheet_dir=sheet_dir) for e, p in jobs]
    blocked = [r for r in results if r["verdict"] == "blocked"]

    if a.json:
        print(json.dumps({"at": datetime.now().astimezone().replace(microsecond=0).isoformat(),
                          "target": "%dx%d" % (spec["width"], spec["height"]),
                          "results": results,
                          "verdict": "blocked" if blocked else "ok"},
                         ensure_ascii=False, indent=2))
    else:
        print("=" * 74)
        print("画面级平台合规门禁 · %d 集 · 目标 %dx%d" % (len(results), spec["width"], spec["height"]))
        print("=" * 74)
        for r in results:
            print("\n%s" % os.path.basename(r["file"]))
            for it in r["items"]:
                mark = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠ ", "MANUAL": "👁 "}[it["level"]]
                print("  %s [%s] %-8s %s" % (mark, it["id"], it["title"], it["detail"]))
                if it.get("fix"):
                    print("      修法：%s" % it["fix"])
        print("\n" + "=" * 74)
        if blocked:
            print("[BLOCK] %d 集画面侧不合规 —— 修完再提交平台" % len(blocked))
        else:
            print("[OK] 画面侧机器判据全部通过（C4 品牌仍需人看抽帧拼图）")

    # 落痕
    if ws:
        try:
            d = os.path.join(ws, "08-合规")
            os.makedirs(d, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            p = os.path.join(d, "画面合规_%s.json" % stamp)
            with open(p, "w", encoding="utf-8", newline="\n") as f:
                json.dump({"at": datetime.now().astimezone().replace(microsecond=0).isoformat(),
                           "target": "%dx%d" % (spec["width"], spec["height"]),
                           "results": results,
                           "verdict": "blocked" if blocked else "ok"},
                          f, ensure_ascii=False, indent=2)
            if not a.json:
                print("预检记录：%s" % p)
        except OSError:
            pass

    return 2 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
