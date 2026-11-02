#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""pack_import.py —— 制作包 → 出片引擎的 `data/` 契约（唯一的转换入口）

它替代了什么
------------
`main` 上的转换入口是 `convert_storyboard.py`：读人读的分镜 Markdown，抽 5 个字段。
那条路要求创作侧按固定字段写 md，而外部创作 Skill（如 `tianchong-manju`）产出的是
另一种手册结构 —— 于是「每条新题材都要改一次解析器」。

本脚本反过来：**先定义一份格式无关的制作包**（`docs/pack/PACK-SPEC.md`），
让创作侧适配包，而不是让引擎适配每一种 Markdown。

输入 → 输出
-----------
  输入：`<pack>/pack.json` + `assets/*.json` + `episodes/epNN.json`
  输出：`<ws>/06-提示词/<ep>/`  ← 引擎的 `data_dir` 就是 `06-提示词/`，按集分子目录
        ├── shots.json         [{shot_id, ratio, crop, board_ref, character_refs, scene_refs}]
        ├── boards.json        {shot_id: {prompt, ratio, refs}}
        ├── h3_prompts.json    {shot_id: {prompt, duration, ratio}}
        ├── characters.json    {key: 绝对路径}   ← 人物 + 道具 + 特效（引擎共用一张表）
        └── scenes.json        {key: 绝对路径}

参考图来源（按优先级）：
  ① `<ws>/04-资产/{characters,scenes,props}/` 里已出的图
  ② `<pack>/refs/<ID>.png` 原图
  两处都没有 → 不写该 key，由 `asset` 环节出图后重跑本脚本回填（幂等）。

默认干跑；`--apply` 才落盘，落盘前把旧 `data/` 备份到 `data/.bak-<ts>/`。
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import sys
from datetime import datetime

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]                       # stages/import → 仓库根
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "stages"))

import pack_spec as S                        # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[union-attr]
except Exception:                            # noqa: BLE001
    pass

LAYOUT = None                                # 惰性导入：没有工作区时也要能只看包


def _layout():
    global LAYOUT
    if LAYOUT is None:
        import _layout as L                  # noqa: E402
        LAYOUT = L
    return LAYOUT


# ===========================================================================
# 参考图解析
# ===========================================================================
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")


def _scan_asset_images(assets_dir: pathlib.Path) -> dict:
    """扫出图产物 → {(ID, code|''): 路径}。

    文件名约定见 PACK-SPEC §4.2：`<ID>_<name>_<code>.png` 或 `<ID>_<name>.png`。
    解析方式：取文件名主干的第一段（`_` 前）当 ID，剩下的按 assets 里登记的 code 反查。
    """
    out: dict = {}
    if not assets_dir.is_dir():
        return out
    for p in assets_dir.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in IMG_EXT:
            continue
        stem = p.stem
        m = S.ID_RE.match(stem.split("_")[0])
        if not m:
            continue
        aid = stem.split("_")[0]
        rest = stem[len(aid):].lstrip("_")
        out.setdefault(aid, {})[rest] = p.resolve()
    return out


def _pick_image(by_id: dict, aid: str, code: str) -> pathlib.Path | None:
    """在一个资产的多张产物里挑出 code 对应的那张。

    匹配顺序：完整 rest 等于 `<name>_<code>` → rest 以 `_<code>` 结尾 → 该 ID 唯一一张图。
    前两条优先，是因为不同资产的 name 可能带下划线；最后一条兜底单变体情况。
    """
    group = by_id.get(aid) or {}
    if not group:
        return None
    if len(group) == 1:
        return next(iter(group.values()))
    c = str(code or "").strip()
    if not c:
        return next(iter(group.values()))
    cands = [v for rest, v in group.items() if rest.endswith("_" + c) or rest == c]
    if cands:
        return sorted(cands)[0]
    return next(iter(group.values()))


def resolve_refs(ws: pathlib.Path, pack_dir: pathlib.Path, assets: dict) -> tuple:
    """建 (characters, scenes, 资产登记表, 缺失列表)。值一律是绝对路径。"""
    L = _layout()
    adir = L.assets_dir(ws)
    scanned = {k: _scan_asset_images(adir / ("props" if k == "prop" else k + "s"))
               for k in S.ASSET_KINDS}
    pack_refs = S.refs_lookup(pack_dir)

    chars: dict = {}
    scenes: dict = {}
    registry: dict = {"characters": {}, "scenes": {}, "props": {}}
    missing: list = []
    for kind, bucket in assets.items():
        table = scenes if kind == "scene" else chars
        reg = registry.get("scenes" if kind == "scene" else ("props" if kind == "prop" else "characters"))
        for aid, item in bucket.items():
            for v in item["variants"]:
                key = S.variant_key(aid, v["code"])
                img = _pick_image(scanned.get(kind, {}), aid, v["code"]) or pack_refs.get(aid)
                if img is None:
                    missing.append({"id": aid, "code": v["code"], "key": key})
                    continue
                table[key] = _rel(img)
                reg[key] = _rel(img)
            # 主变体别名：shots 里没写 variant 时引擎也查得到
            if item["variants"] and item["variants"][0]["code"]:
                k0 = S.variant_key(aid, item["variants"][0]["code"])
                if k0 in table and aid not in table:
                    table[aid] = table[k0]
                    reg[aid] = table[k0]
    return chars, scenes, registry, missing


def _rel(p: pathlib.Path) -> str:
    """统一成正斜杠的**绝对**路径。

    为什么用绝对路径：`characters.json` 会被复制进每一集的 `data/<ep>/`，若写相对路径，
    基准目录就随集数变化，同一个文件在不同集里要写不同深度（`../../` vs `../../../`）。
    故障表现是静默的 —— 只有当某一集恰好少一层时才在出片时爆「文件不存在」。

    代价：整部剧换盘符/换机器后需要重跑一次导入（一条命令，幂等）。
    这个代价是可接受的；反过来，路径错位要在**计费之后**才发现，代价高得多。
    """
    return str(p).replace("\\", "/")


# ===========================================================================
# 转换
# ===========================================================================
def build_episode_files(pack: dict, assets: dict, ep: dict,
                        chars: dict, scenes: dict) -> dict:
    """一集 → 四份 data 文件的**内容**（不落盘）。

    `characters.json` / `scenes.json` 是全集共用的参考表，这里只按本集用到的 key 过滤，
    避免把「后面 20 集才出场的角色」也塞进本集的表里 —— 表越小，出问题时越好查。
    """
    ep_index = ep["episode"]
    ep_tag = S.ep_key(ep_index)
    shots_out, boards_out, h3_out = [], {}, {}
    used_char, used_scene = set(), set()

    for s in ep["shots"]:
        sid = s["id"]
        bref = "board_%s_%s" % (ep_tag, sid)
        ch_refs = [c["key"] for c in s["cast"] if c["kind"] != "scene"]
        sc_refs = [c["key"] for c in s["cast"] if c["kind"] == "scene"]
        used_char.update(ch_refs)
        used_scene.update(sc_refs)

        shots_out.append({
            "shot_id": sid,
            "ratio": s["ratio"],
            "crop": {"rows": 1, "cols": 1},          # 九宫格链已下线；字段保留给引擎兼容
            "board_ref": bref,
            "character_refs": ch_refs,
            "scene_refs": sc_refs,
        })
        if s["board_prompt"]:
            boards_out[sid] = {"prompt": s["board_prompt"], "ratio": s["ratio"],
                               "refs": [c["key"] for c in s["cast"]]}
        h3_out[sid] = {"prompt": s["video_prompt"], "duration": s["duration"],
                       "ratio": s["ratio"]}

    return {
        "shots.json": shots_out,
        "boards.json": boards_out,
        "h3_prompts.json": h3_out,
        "characters.json": {k: v for k, v in chars.items() if k in used_char or k.split("@")[0] in
                            {x.split("@")[0] for x in used_char}},
        "scenes.json": {k: v for k, v in scenes.items() if k in used_scene or k.split("@")[0] in
                        {x.split("@")[0] for x in used_scene}},
    }


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


def diff_files(old_dir: pathlib.Path, files: dict) -> list:
    """对比将写入的内容与磁盘现状 → 差异行（给干跑用）。"""
    lines = []
    for name, content in files.items():
        p = old_dir / name
        new = _dump(content)
        if not p.is_file():
            lines.append("  + 新增  %s（%d 字节）" % (name, len(new.encode("utf-8"))))
            continue
        try:
            old = p.read_text(encoding="utf-8")
        except OSError:
            old = ""
        if old == new:
            continue
        try:
            a, b = json.loads(old), json.loads(new)
            if a == b:
                lines.append("  ~ 格式  %s（内容相同，缩进/顺序差异，将重写）" % name)
                continue
        except (json.JSONDecodeError, ValueError):
            pass
        lines.append("  ~ 变更  %s" % name)
    for p in sorted(old_dir.glob("*.json")):
        if p.name not in files:
            lines.append("  - 残留  %s（不在本次输出里；--prune 才删）" % p.name)
    return lines


# ===========================================================================
# 报告
# ===========================================================================
def render_report(pack: dict, sumry: dict, rep, missing: list) -> str:
    lines = ["# 导入报告", "",
             "- 生成时间：%s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             "- 制作包：%s" % (pack.get("title") or "（未命名）"),
             "- 集数：%d　资产：%d　图片：%d　镜头：%d　总时长：%.1fs"
             % (sumry["episodes"], sumry["assets"], sumry["images"],
                sumry["shots"], sumry["duration_s"]),
             "- 风格锁：%s" % (pack.get("style_lock") or "（空）"),
             ""]
    body = rep.render()
    lines += ["## 校验", "", "```", body, "```", ""]
    if missing:
        lines += ["## 缺参考图（%d 张，出图后重跑本命令即可回填）" % len(missing), "",
                  "| 资产 | 变体 | 参考 key |", "|---|---|---|"]
        lines += ["| %s | %s | %s |" % (m["id"], m["code"], m["key"]) for m in missing]
        lines.append("")
    return "\n".join(lines)


# ===========================================================================
# CLI
# ===========================================================================
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="制作包 → data/ 契约（默认干跑，--apply 才写）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="例：python stages/import/pack_import.py --pack D:/剧/x/pack --workspace D:/剧/x --apply")
    ap.add_argument("--pack", required=True, help="制作包目录（含 pack.json）")
    ap.add_argument("--workspace", default=None,
                    help="剧项目工作区根；省略则用 SOLODRAMA_WORKSPACE 或 --pack 的上级目录")
    ap.add_argument("--ep", default=None, help="只导这一集（ep01 / 1）；省略导全部")
    ap.add_argument("--apply", action="store_true", help="真写（默认干跑）")
    ap.add_argument("--prune", action="store_true",
                    help="删除本集 data 目录里不在本次输出里的 *.json（默认保留并告警）")
    ap.add_argument("--json", action="store_true", help="机器可读输出（给 Studio 用）")
    args = ap.parse_args(argv)

    pack_dir = pathlib.Path(args.pack).expanduser().resolve()
    if not pack_dir.is_dir():
        print("[FAIL] 制作包目录不存在：%s" % pack_dir)
        return 2

    pack, assets, episodes, rep = S.load_pack(pack_dir)
    sumry = S.summarize(pack, assets, episodes)

    # 工作区：显式 > 环境变量 > pack 的上级目录（制作包通常放在项目根下）
    ws_raw = args.workspace or os.environ.get("SOLODRAMA_WORKSPACE") \
        or os.environ.get("DRAMA_WORKSPACE") or str(pack_dir.parent)
    ws = pathlib.Path(ws_raw).expanduser().resolve()

    if not rep.ok:
        if args.json:
            print(json.dumps({"ok": False, "report": rep.as_dict(), "summary": sumry},
                             ensure_ascii=False, indent=2))
        else:
            print("=" * 78)
            print("制作包校验未通过，未写任何文件")
            print("=" * 78)
            print(rep.render())
        return 2

    # 只导指定集
    if args.ep:
        want = S.ep_index_of(args.ep)
        if want is None:
            print("[FAIL] 认不出集号：%r（写 ep01 或 1）" % args.ep)
            return 2
        if want not in episodes:
            print("[FAIL] 制作包里没有第 %d 集（现有：%s）"
                  % (want, ", ".join(S.ep_key(i) for i in sorted(episodes))))
            return 2
        episodes = {want: episodes[want]}
        sumry = S.summarize(pack, assets, episodes)

    try:
        L = _layout()
        data_root = L.data_dir(ws)
    except SystemExit:
        print("[FAIL] 工作区解析失败：%s（缺 layout.json？）" % ws)
        return 2

    chars, scenes, registry, missing = resolve_refs(ws, pack_dir, assets)

    plans, lines, changed = {}, [], 0
    for idx in sorted(episodes):
        ep = episodes[idx]
        ep_dir = data_root / S.ep_key(idx)
        files = build_episode_files(pack, assets, ep, chars, scenes)
        plans[ep_dir] = files
        d = diff_files(ep_dir, files)
        head = "  %s（%d 镜，%.0fs）" % (S.ep_key(idx), len(ep["shots"]),
                                        sum(float(s["duration"]) for s in ep["shots"]))
        lines.append(head)
        lines += d or ["    （无变化）"]
        changed += sum(1 for x in d if not x.strip().startswith("（"))

    print("=" * 78)
    print("制作包导入%s：%s" % ("（干跑）" if not args.apply else "", pack.get("title") or pack_dir.name))
    print("=" * 78)
    print("  集数 %d ｜ 资产 %d ｜ 待出图 %d ｜ 镜头 %d ｜ 总时长 %.1fs"
          % (sumry["episodes"], sumry["assets"], sumry["images"],
             sumry["shots"], sumry["duration_s"]))
    print("  风格锁：%s" % (pack.get("style_lock") or "（空）"))
    print("  data   ：%s" % data_root)
    print("-" * 78)
    print("\n".join(lines))
    print("-" * 78)
    if rep.warnings or rep.notes:
        print(rep.render())
        print("-" * 78)
    if missing:
        print("  缺参考图 %d 张（出图后重跑本命令回填）：" % len(missing))
        for m in missing[:8]:
            print("    - %s / %s" % (m["id"], m["code"]))
        if len(missing) > 8:
            print("    …（其余 %d 张见报告）" % (len(missing) - 8))
        print("-" * 78)

    if not args.apply:
        print("干跑结束。确认无误后加 --apply 落盘（会先备份旧 data/）。")
        if args.json:
            print(json.dumps({"ok": True, "dry_run": True, "summary": sumry,
                              "report": rep.as_dict(), "missing_refs": missing},
                             ensure_ascii=False, indent=2))
        return 0

    # ---- 落盘 ----------------------------------------------------------
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    written = []
    for ep_dir, files in plans.items():
        ep_dir.mkdir(parents=True, exist_ok=True)
        olds = [p for p in ep_dir.glob("*.json")]
        if olds:
            bak = ep_dir / (".bak-" + stamp)
            bak.mkdir(exist_ok=True)
            for p in olds:
                shutil.copy2(p, bak / p.name)
        for name, content in files.items():
            (ep_dir / name).write_text(_dump(content), encoding="utf-8", newline="")
            written.append(ep_dir / name)
        if args.prune:
            for p in list(ep_dir.glob("*.json")):
                if p.name not in files:
                    p.unlink()

    prompt_root = data_root.parent if data_root.name == "data" else data_root
    rp = prompt_root / "import_report.md"
    rp.write_text(render_report(pack, sumry, rep, missing), encoding="utf-8", newline="")
    written.append(rp)

    # 资产登记表：`04-资产/refs.json`。
    # 为什么在这里写：`nodes.py` 的 `assets` 判据与 `prepare_refs.py` 都读它，
    # 而它本质是「资产 id → 图」的登记，正好是导入时已经算出来的东西，不必再扫一遍目录。
    if registry:
        rr = _layout().assets_dir(ws) / "refs.json"
        rr.parent.mkdir(parents=True, exist_ok=True)
        rr.write_text(_dump({"_note": "由 pack_import 生成：资产 key → 出图产物；出图后重跑导入即回填",
                             "pack": str(pack_dir), **registry}), encoding="utf-8", newline="")
        written.append(rr)

    print("[OK] 已写入 %d 个文件" % len(written))
    for p in written:
        print("  %s" % p)
    if args.json:
        print(json.dumps({"ok": True, "dry_run": False, "written": [str(p) for p in written],
                          "summary": sumry, "report": rep.as_dict(),
                          "missing_refs": missing}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
