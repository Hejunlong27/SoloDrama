#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""zzai_recover.py —— 收尾真真AI 的「孤儿任务」（服务端已成功，本地没落盘）

为什么需要它
------------
任务一旦提交就**已经计费**。可本地进程会因为网络抖动、终端关闭、批处理被 Ctrl-C 而退出，
于是出现最常见的浪费形态：钱花了、图在服务端生成了、本地却没有文件。
2026-11-13 实测就踩到两次（视频 3 秒样片、ep01 四宫格分镜）。

本脚本扫描 `<工作区>/.drama/media/*.json`：

* 有 `remote_task_id` 且状态非终态 → 重新轮询一次；
* 状态 succeeded 但没有产物 → 按记录里的 `dest` 下载；
  `dest` 缺失时落到 `<dest 目录>/_recovered_<id>.<ext>`；
* 分镜四宫格记录（`shot_id` 含 `/`）下载后自动切分回逐镜 PNG。

用法
----
    python tools/zzai_recover.py --workspace "D:/剧本/海外剧/10"            # 只报告
    python tools/zzai_recover.py --workspace "..." --apply                  # 真下载/切分
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")     # type: ignore[union-attr]
except Exception:                                                  # noqa: BLE001
    pass

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "stages"))

import _layout as L                                                # noqa: E402
from stages.media_api.zzai import ZZAIClient, ZZAIError            # noqa: E402

TERMINAL = ("succeeded", "failed", "canceled")


def _slice(src: pathlib.Path, sids: list, out_dir: pathlib.Path) -> list:
    """四宫格 → 逐镜 PNG（与 gen_boards._slice_grid 同口径：四等分 + 2% 内缩）。"""
    from PIL import Image
    out = []
    with Image.open(src) as im:
        W, H = im.size
        cw, ch = W // 2, H // 2
        inset = 0.02
        for idx, sid in enumerate(sids):
            cx, cy = (0 if idx in (0, 2) else 1), (0 if idx in (0, 1) else 1)
            box = (int(cx * cw + cw * inset), int(cy * ch + ch * inset),
                   int((cx + 1) * cw - cw * inset), int((cy + 1) * ch - ch * inset))
            dst = out_dir / ("%s.png" % sid)
            im.crop(box).save(dst)
            out.append(dst)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="收尾真真AI 孤儿任务（不重复计费）")
    ap.add_argument("--workspace", default=None)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)

    ws = pathlib.Path(a.workspace).expanduser().resolve() if a.workspace else pathlib.Path(
        __import__("os").environ.get("SOLODRAMA_WORKSPACE") or ".").resolve()
    media = ws / ".drama" / "media"
    if not media.is_dir():
        print("[FAIL] 没有任务记录目录：%s" % media)
        return 2

    client = ZZAIClient()
    n = fixed = 0
    for f in sorted(media.glob("mt_*.json")):
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        tid = str(rec.get("remote_task_id") or "")
        if not tid:
            continue
        art = [x for x in (rec.get("artifacts") or []) if x]
        status = str(rec.get("status") or "")
        if art and pathlib.Path(art[0]).is_file():
            continue
        n += 1
        kind = rec.get("kind") or "image"
        try:
            r = client.poll(kind, tid)
        except ZZAIError as exc:
            print("[轮询失败] %s %s：%s" % (f.stem, tid, exc))
            continue
        print("%-10s %-12s %-10s %s" % (f.stem, rec.get("purpose"), r["status"],
                                        (r.get("progress") or "")))
        if r["status"] != "succeeded" or not r.get("result_url"):
            continue
        dest = pathlib.Path(rec.get("dest") or "")
        if not dest.is_absolute():
            ep = str(rec.get("episode") or "")
            sid = str(rec.get("shot_id") or "")
            if rec.get("purpose") == "board.frame" and ep:
                # 分镜：先落 _grid/，再切回逐镜 —— 与 gen_boards 的落点一致
                dest = L.assets_dir(ws) / "boards" / ep / "_grid" / ("%s_%s.png" % (ep, f.stem))
            elif kind == "video" and ep and sid and "/" not in sid:
                dest = L.out_dir(ws) / ep / sid / "final.mp4"
            elif rec.get("purpose") == "asset.card" and sid:
                dest = media / ("_recovered_%s.png" % f.stem)
            else:
                dest = media / ("_recovered_%s.%s" % (f.stem, "mp4" if kind == "video" else "png"))
        if not a.apply:
            print("            → 可恢复：%s" % dest)
            continue
        try:
            client.download(r["result_url"], dest)
        except ZZAIError as exc:
            print("            [下载失败] %s" % exc)
            continue
        sids = [s for s in str(rec.get("shot_id") or "").split("/") if s]
        if len(sids) > 1:
            try:
                out_dir = L.assets_dir(ws) / "boards" / str(rec.get("episode") or "")
                _slice(dest, sids, out_dir)
                print("            → 已切分 %d 镜：%s" % (len(sids), "、".join(sids)))
            except Exception as exc:                           # noqa: BLE001
                print("            [切分失败] %s" % exc)
        rec.setdefault("artifacts", [])
        rec["artifacts"] = [str(dest)]
        rec["status"] = "succeeded"
        f.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        fixed += 1
        print("            → 已落盘 %s" % dest)

    print("\n待收尾 %d 个；本次恢复 %d 个%s"
          % (n, fixed, "" if a.apply else "（干跑，加 --apply 执行）"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
