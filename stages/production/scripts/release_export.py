#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""release_export.py —— 发布版成片导出：**严格命名 + 固定落点**（2026-10-19 新增）

为什么有它
----------
用户明确要求（2026-10-19）：

> 「发布版剧集的命名，严格以 `Episode+**` 的格式，如 Episode01、Episode02、Episode03。
>   不要每次输出之后，发布版文件名字都是乱七八糟的。」

此前实际出现过 `EP01_1080p_ES.mp4`、`ep01_拼接_11段_672x1216.mp4`、`ep01_西语硬字幕_11段_672x1216.mp4`
这类**即兴命名** —— 上架时要手工改名，且无法机器校验集号是否连续。

本脚本把「发布版」固化为一条确定性动作：

    源（成片/带字幕成片/已编码发布版）  →  `09-发行/剧集/EpisodeNN.mp4`

* **命名**：`Episode` + 至少两位编号（`Episode01`、`Episode40`；≥100 集自动加位）
* **落点**：`09-发行/剧集/`（发行物料目录，与封面/文案/版权资料并列）
* **纪律**：目标目录里只要存在**不符合命名**的文件，直接报错（退出码 2），不静默通过

用法
----
    # 干跑（默认）：只打印「哪个源 → 哪个目标」
    python release_export.py --workspace "<工作区>" --all
    # 真写（复制）
    python release_export.py --workspace "<工作区>" --all --apply
    # 指定来源目录（例如已编码好的 1080p 发布版）
    python release_export.py --workspace "<工作区>" --from "<ws>/07-成片/发布版1080p_es" --all --apply
    # 硬链接省空间（同一磁盘；改一个不影响另一个）
    python release_export.py --workspace "<工作区>" --all --apply --link

退出码：0 = 成功（或干跑无问题）；2 = 命名冲突 / 缺集 / 有不合规文件。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _ws import WS as _WS_DEFAULT                                        # noqa: E402
import _layout as L                                                      # noqa: E402

# 源文件候选：**越靠前越接近可发布**
#   ① 已编码发布版（1080p / hd / final / pub）—— 平台规格已达标，优先
#   ② 烧录字幕成片（_subbed）—— 内容已完整，规格可能仍是中间分辨率
#   ③ 放大母版 → ④ 母版
# ★ 2026-10-22：放大母版的正名是 `<ep>_master_<W>x<H>.mp4`（如 _master_1080x1920）；
#   旧名 `_master_2k` 继续识别（老项目不迁移），且**排在正名之后** —— 两者同时存在时
#   优先用带真实分辨率的那份。
SOURCE_PREFERENCE = (
    ("encoded", re.compile(r"(1080p|2160p|_1080|_hd$|_hd_|_final|_pub\b|_publish)", re.I)),
    ("subbed", re.compile(r"_subbed", re.I)),
    ("master_res", re.compile(r"_master_\d{3,4}x\d{3,4}", re.I)),
    ("master_2k", re.compile(r"_master_2k", re.I)),
    ("master", re.compile(r"_master", re.I)),
)
EP_RE = re.compile(r"^ep[_\-]?(\d{1,3})", re.I)      # ep01_xxx / ep1 / EP01_1080p_ES
AUTO_FROM_HINTS = ("发布版", "交付", "subs", "_subs")


def _rank(stem: str) -> int:
    for i, (_tag, rx) in enumerate(SOURCE_PREFERENCE):
        if rx.search(stem):
            return i
    return len(SOURCE_PREFERENCE)          # 无后缀（如 EP01_1080p_ES 已由 encoded 命中）


def _better(cur, r: int, f: Path) -> bool:
    """候选是否优于当前：先比 rank，**同 rank 取 mtime 最新**（反馈 10.8）。

    此前是 `r < found[n][0]`（严格小于），所以**先扫到的**胜出：`_final/` 里同时有
    `ep01_1080p_sub.mp4`（旧，字幕错位）与 `ep01_final.mp4`（新，ASR 校时）时，
    导出脚本会静默选旧的那份 —— 静默交付错版本比直接报错危险得多。
    """
    if cur is None:
        return True
    r0, f0 = cur
    if r != r0:
        return r < r0
    try:
        return f.stat().st_mtime > f0.stat().st_mtime
    except OSError:
        return False


def _scan(dir_: Path, rec: bool = True) -> dict:
    """{集号: (rank, path)}，同集号取 rank 最小；同 rank 取 mtime 最新。"""
    found: dict = {}
    it = dir_.rglob("*") if rec else dir_.glob("*")
    for f in it:
        if not f.is_file() or f.suffix.lower() not in (".mp4", ".mov", ".mkv"):
            continue
        if f.parent.name == L.RELEASE_EPISODE_DIR:
            continue                                        # 已是目标目录，跳过
        m = EP_RE.match(f.stem)
        if not m:
            continue
        n, r = int(m.group(1)), _rank(f.stem)
        if _better(found.get(n), r, f):
            found[n] = (r, f)
    return found


def _auto_dirs(film: Path, out_dir: Path) -> list[Path]:
    """自动探测的候选来源目录（按优先级）。"""
    cands = [p for p in sorted(film.glob("发布版*")) if p.is_dir()]
    cands += [p for p in (film / n for n in ("交付", "subs", "_subs")) if p.is_dir()]
    cands.append(out_dir / "subs")
    cands.append(film)                                       # 兜底：07-成片 里直接躺着成片
    seen, out = set(), []
    for c in cands:
        if c.is_dir() and str(c) not in seen:
            seen.add(str(c))
            out.append(c)
    return out


def _merge_scan(dirs: list[Path]) -> dict:
    """跨多个来源目录合并：先比 rank，同 rank 取 mtime 最新（口径与 _scan 一致）。"""
    found: dict = {}
    for d in dirs:
        for n, (r, f) in _scan(d).items():
            if _better(found.get(n), r, f):
                found[n] = (r, f)
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description="发布版成片导出（EpisodeNN 严格命名）")
    ap.add_argument("--workspace", default=None)
    ap.add_argument("--from", dest="src", default=None, help="来源目录（默认自动探测）")
    ap.add_argument("--all", action="store_true", help="导出全部找到的集")
    ap.add_argument("--ep", action="append", default=[], help="只导出指定集，可多次：--ep ep01")
    ap.add_argument("--digits", type=int, default=L.RELEASE_EPISODE_DIGITS,
                    help="编号位数，默认 %d（Episode01）" % L.RELEASE_EPISODE_DIGITS)
    ap.add_argument("--apply", action="store_true", help="真写（默认干跑）")
    ap.add_argument("--link", action="store_true", help="用硬链接代替复制（省空间，同盘可用）")
    ap.add_argument("--json", action="store_true", help="输出 JSON 到 stdout")
    a = ap.parse_args()

    ws = Path(a.workspace).expanduser().resolve() if a.workspace else _WS_DEFAULT
    film = L.stage_dir(ws, "film")
    out_dir = L.out_dir(ws)
    dst_dir = L.release_episode_dir(ws)
    rx = re.compile(r"^Episode(\d{%d,})\.mp4$" % a.digits)

    fails, warns = [], []

    # ---- 0. 目标目录里已有的不合规文件（命名纪律） ----
    existing = {}
    if dst_dir.is_dir():
        for f in dst_dir.iterdir():
            if f.is_file() and f.suffix.lower() == ".mp4":
                m = rx.match(f.name)
                if m:
                    existing[int(m.group(1))] = f
                else:
                    fails.append("目标目录已有**不符合命名**的文件：%s（应为 EpisodeNN.mp4）" % f.name)

    # ---- 1. 找源（跨候选目录合并，同集取最优） ----
    if a.src:
        src_dirs = [Path(a.src).expanduser().resolve()]
    else:
        src_dirs = _auto_dirs(film, out_dir)
    src_dirs = [d for d in src_dirs if d.is_dir()]
    if not src_dirs:
        fails.append("未找到可导出的成片（自动探测范围：%s 下的 发布版* / 交付 / subs / _subs 与 %s/subs）"
                     "⇒ 用 --from 指定来源目录" % (film, out_dir))
        return _report(a, dst_dir, [], {}, [], fails, warns, dry_run=not a.apply)
    if a.src and not src_dirs:
        fails.append("--from 指向的目录不存在：%s" % a.src)
        return _report(a, dst_dir, [], {}, [], fails, warns, dry_run=not a.apply)

    found = _merge_scan(src_dirs)
    if not found:
        fails.append("来源目录里没有任何可识别集号的成片：%s ⇒ 文件名需以 `ep01` / `EP01` 开头"
                     % " 、".join(str(d) for d in src_dirs))
        return _report(a, dst_dir, src_dirs, {}, [], fails, warns, dry_run=not a.apply)

    # ---- 2. 选集 ----
    if a.ep and not a.all:
        want = set()
        for e in a.ep:
            m = EP_RE.match(e.strip())
            if not m:
                fails.append("--ep 参数无法解析集号：%s（示例：--ep ep01）" % e)
                return _report(a, dst_dir, src_dirs, {}, [], fails, warns, dry_run=not a.apply)
            want.add(int(m.group(1)))
    elif a.all or not a.ep:
        want = set(found)
    else:
        want = set(found)

    picked = sorted(n for n in want if n in found)
    missing = sorted(n for n in want if n not in found)
    for n in missing:
        fails.append("来源目录里找不到第 %d 集（期望 %s 或 EP%02d_*.mp4）"
                     % (n, L.release_episode_name(n, a.digits), n))

    # 集号连续性（只提示不阻断：连载中很正常）
    if picked:
        span = set(range(min(picked), max(picked) + 1))
        gap = sorted(span - set(picked) - set(missing))
        if gap:
            warns.append("集号不连续，缺 %s（连载中属正常，整季交付前需补齐）"
                         % ", ".join(str(g) for g in gap))

    plans = [{"ep": n, "src": str(found[n][1]), "dst": str(dst_dir / L.release_episode_name(n, a.digits)),
              "already": n in existing and existing[n].stat().st_size == found[n][1].stat().st_size}
             for n in picked]

    # ---- 3. 执行 ----
    done = []
    if a.apply and not fails:
        dst_dir.mkdir(parents=True, exist_ok=True)
        for p in plans:
            src, dst = Path(p["src"]), Path(p["dst"])
            if p["already"]:
                p["action"] = "skip（已存在且大小一致）"
                done.append(p)
                continue
            if dst.exists():
                dst.unlink()
            if a.link:
                try:
                    os.link(src, dst)
                    p["action"] = "hardlink"
                except OSError:
                    shutil.copy2(src, dst)
                    p["action"] = "copy（硬链接失败，已回退）"
            else:
                shutil.copy2(src, dst)
                p["action"] = "copy"
            done.append(p)
        # 清单
        manifest = {"at": datetime.now().astimezone().replace(microsecond=0).isoformat(),
                    "workspace": str(ws), "sources": [str(d) for d in src_dirs],
                    "naming": {"prefix": L.RELEASE_EPISODE_PREFIX, "digits": a.digits,
                               "example": L.release_episode_name(1, a.digits)},
                    "episodes": [{"ep": p["ep"], "file": Path(p["dst"]).name,
                                  "bytes": Path(p["dst"]).stat().st_size}
                                 for p in done if Path(p["dst"]).is_file()]}
        (dst_dir / "剧集清单.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    return _report(a, dst_dir, src_dirs, plans if not a.apply else done, picked, fails, warns,
                   dry_run=not a.apply)


def _report(a, dst_dir, src_dirs, plans, picked, fails, warns, dry_run=False) -> int:
    if a.json:
        print(json.dumps({"dst_dir": str(dst_dir),
                          "src_dir": str(src_dirs[0]) if len(src_dirs) == 1 else None,
                          "src_dirs": [str(d) for d in src_dirs],
                          "dry_run": dry_run, "plans": plans,
                          "fails": fails, "warns": warns,
                          "verdict": "blocked" if fails else "ok"},
                         ensure_ascii=False, indent=2))
    else:
        print("=" * 74)
        print("发布版成片导出（EpisodeNN 命名）%s" % ("· 干跑" if dry_run else "· 真写"))
        print("=" * 74)
        print("  来源 : %s" % ("、".join(str(d) for d in src_dirs) or "（未找到）"))
        print("  落点 : %s" % dst_dir)
        for p in plans:
            act = p.get("action") or ("计划" if dry_run else "完成")
            print("  %-6s %-44s → %s" % (act, Path(p["src"]).name, Path(p["dst"]).name))
        for w in warns:
            print("  [WARN] %s" % w)
        for b in fails:
            print("  [FAIL] %s" % b)
    if fails:
        print("\n[BLOCK] 发布版导出未完成 —— 共 %d 项问题（退出码 2）。" % len(fails),
              file=sys.stderr if a.json else sys.stdout)
        return 2
    if dry_run:
        print("\n[OK] 干跑通过，共 %d 集。加 --apply 真写。" % len(plans),
              file=sys.stderr if a.json else sys.stdout)
        return 0
    print("\n[OK] 已导出 %d 集到 %s（命名 %s）" % (len(plans), dst_dir, L.release_episode_name(1, a.digits)),
          file=sys.stderr if a.json else sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
