# -*- coding: utf-8 -*-
"""episode_preflight.py —— 单/多集出片前置体检（零计费）

用法：
    python scripts\\episode_preflight.py 4 5 6
    python scripts\\episode_preflight.py 4 --json
    python scripts\\episode_preflight.py 4 5 6 --plan-refs     # 只打印「应有 character_refs」

核心口径（2026-09-19 从第三/四/五/六集实测归纳）：
  `subject_definitions` 里的 `<Picture N>` 是对**全部 Subject 顺序编号**的 ——
  角色、场景、道具都占号。而 `character_refs` 只提供图片，顺序 = 槽位顺序 = Picture 号顺序。
  ⇒ 只要中间缺一个角色的图，**它后面的场景图就会错位**。
  所以补资产时不能「把场景图追加到末尾」，必须按 Picture 号逐个落位。

资产库口径：资产 md 的「节号 = char 编号」。char_01..09 = 第 1..9 节。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))  # noqa: E402
from _ws import WS, DATA, ASSETS as ASSETS_ROOT  # noqa: E402  ★ 工作区解析 + 分阶段目录真源
VP = WS / "video-pipeline"    # 引擎技术目录
ASSET_MD = Path((os.environ.get("SOLODRAMA_ASSET_MD") or os.environ.get("DRAMA_ASSET_MD")) or "")   # 资产提示词 md（可选：缺省时跳过资产核对）

SEC_PER_SEG = 360         # 单段出片约 6 分钟（RTX 4060 8G / 8 步 / 0.8MP）
SEC_PER_CHAR = 45         # 单张人物定妆图约 45 秒
SCENE_USD = 0.01          # 场景空镜单价（美元钱包）
MAX_SLOTS = 6             # H3 工作流/AI 应用的 LoadImage 槽位数（node 51/49/50/43/19/23）——硬上限

# 场景关键词 → 资产键（键名按本项目约定，尚未接进 characters.json 的也会列出）
SCENE_KEYS = [
    ("陆家宗祠天井", "scene_02"),
    ("三亚海景五星酒店露天阳台", "scene_03"),
    ("亚特兰蒂斯", "scene_04"),
    ("拘留所", "scene_05"),
    ("沈家老宅", "scene_06"),
    ("钟楼", "scene_07"),
    ("酒楼", "scene_01"),
    ("大包厢", "scene_01"),
]


def load_all():
    """读三件数据。★ 2026-11-01：data 可能按集分了子目录（`data/ep01/shots.json`），
    直接读根目录会报「文件不存在」，而文件就在子目录里。全盘视图取 mtime 最新的一份。"""
    def _read(name, default):
        p = DATA / name
        if not p.is_file() and DATA.is_dir():
            hits = [q for q in DATA.glob("*/%s" % name) if q.is_file()]
            if hits:
                p = max(hits, key=lambda q: q.stat().st_mtime)
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default
    return _read("shots.json", []), _read("h3_prompts.json", {}), _read("characters.json", {})


def parse_asset_md():
    if not ASSET_MD.is_file():
        return {}, {}
    text = ASSET_MD.read_text(encoding="utf-8", errors="replace")
    chars, scenes, zone = {}, {}, None
    for line in text.splitlines():
        if line.startswith("# 一、"):
            zone = "char"; continue
        if line.startswith("# 二、"):
            zone = "scene"; continue
        if line.startswith("# 三、"):
            zone = "prop"; continue
        if zone == "char":
            m = re.match(r"##\s*(\d+)\.\s*([^（(｜|]+)", line)
            if m:
                chars[int(m.group(1))] = m.group(2).strip()
        elif zone == "scene":
            m = re.match(r"##\s*场景\s*(\d+)\s*[·:：]\s*([^（(｜|]+)", line)
            if m:
                scenes[int(m.group(1))] = m.group(2).strip()
    return chars, scenes


def on_disk_assets():
    out = {}
    for sub, pat, pre in (("characters", "char_*.png", "char_"), ("scenes", "scene_*.png", "scene_")):
        d = ASSETS_ROOT / sub        # ★ 2026-10-19：资产在 04-资产/（原 07-成片/assets）
        if not d.is_dir():
            continue
        for f in d.glob(pat):
            m = re.match(re.escape(pre) + r"(\d+)_(.+?)(_r\d+|_preview)?$", f.stem)
            if m:
                out["%s%02d" % (pre, int(m.group(1)))] = m.group(2)
    return out


def sect(prompt: str, name: str) -> str:
    m = re.search(r"\n" + name + r":\n(.*?)(?=\n[a-z_]+:|\Z)", prompt, re.S)
    return m.group(1) if m else ""


def norm(s: str) -> str:
    return re.sub(r"[\s·、（）()【】\[\]]", "", s or "")


def name_to_section(name, char_sections):
    n = norm(name)
    if not n:
        return None
    for sec, nm in char_sections.items():
        if norm(nm) and (norm(nm) in n or n in norm(nm)):
            return sec
    return None


def scene_key_of(text: str):
    for kw, key in SCENE_KEYS:
        if kw in text:
            return key
    return None


def _belongs(sid, ep) -> bool:
    """段 id 是否属于该集。

    · 带集号（`ep01_shot_01`）→ 只收本集
    · **不带集号**（`shot_001`）→ 收（这类项目的 shots.json 本身就是按集放的）

    ★ 2026-11-01：原来严格要求 `ep01_` 前缀，而真实项目的 shot_id 就是 `shot_001`
      —— 前置体检对它们恒报「段数 0 / 没有缺口」，看起来一切正常，其实一个镜头都没查。
      同一套规则在 `nodes._ep_segments` 与 `studio.shots` 里已经用过，这里对齐。
    """
    s_ = str(sid or "")
    if not s_:
        return False
    m = re.search(r"(?:^|[_-])ep0*(\d+)(?:[_-]|$)", s_, re.I)
    if m:
        want = re.sub(r"[^0-9]", "", str(ep)) or "0"
        return int(m.group(1)) == int(want)
    return True


def analyze(ep, shots, prompts, chars, char_sections):
    segs = sorted([s for s in shots if _belongs(s.get("shot_id"), ep)],
                  key=lambda s: s["shot_id"])
    available = {k for k in chars if not k.startswith("_")}
    rows, missing_objs = [], {}
    for s in segs:
        sid = s["shot_id"]
        p = prompts.get(sid)
        refs = list(s.get("character_refs") or [])
        if not p or not str(p.get("prompt") or "").strip():
            rows.append({"shot": sid, "refs": refs, "target": None, "issue": "无提示词", "maxP": 0})
            continue
        sd = sect(p["prompt"], "subject_definitions")
        subs = []
        for m in re.finditer(r"<Subject (\d+)> 是 (?:<Picture (\d+)> )?中(?:的)?([^\n]+)", sd):
            subs.append({"subj": int(m.group(1)),
                         "pic": int(m.group(2)) if m.group(2) else None,
                         "text": m.group(3).strip()})
        maxP = max([x["pic"] for x in subs if x["pic"]] or [0])
        target, issues = [], []
        for x in subs:
            pic, txt = x["pic"], x["text"]
            if pic is None:
                continue
            if "形象" in txt:
                nm = re.sub(r"形象.*$", "", txt).strip()
                sec = name_to_section(nm, char_sections)
                key = "char_%02d" % sec if sec else None
                if key and key in available:
                    target.append((pic, key))
                else:
                    target.append((pic, "❌%s%s" % (nm, "(第%s节)" % sec if sec else "(库外)")))
                    missing_objs.setdefault(nm, sec)
                    issues.append("P%d 缺角色图:%s%s" % (pic, nm, "（第%s节）" % sec if sec else "（资产库无此人）"))
            elif txt.startswith("道具"):
                pass                                   # 道具不用图
            else:
                sk = scene_key_of(txt)
                if sk:
                    target.append((pic, sk))
                    if sk not in available:
                        issues.append("P%d 缺场景图:%s（%s 未接入）" % (pic, txt[:16], sk))
                else:
                    issues.append("P%d 未识别场景:%s" % (pic, txt[:16]))
        # 落位检查：target 的 pic 必须连续 1..len(target)
        pics = [t[0] for t in target]
        if pics != list(range(1, len(pics) + 1)):
            issues.append("落位不连续:%s" % pics)
        # ★ 槽位上限：H3 工作流/AI 应用只有 6 个 LoadImage 槽位（node 51/49/50/43/19/23）
        if len(target) > MAX_SLOTS:
            issues.append("★需要 %d 张图，但只有 %d 个槽位（末尾的会被丢掉 ⇒ 必须删掉超出者的 <Picture>）"
                          % (len(target), MAX_SLOTS))
        want = [k for _, k in target]
        rows.append({"shot": sid, "refs": refs, "target": want, "want_pics": pics,
                     "maxP": maxP, "issue": " | ".join(issues) or "OK"})
    return {"ep": ep, "n": len(segs), "rows": rows, "missing": missing_objs}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("episodes", nargs="+")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--plan-refs", action="store_true")
    args = ap.parse_args()

    shots, prompts, chars = load_all()
    char_sections, scene_sections = parse_asset_md()
    disk = on_disk_assets()
    available = {k for k in chars if not k.startswith("_")}
    # 集号两种写法都认：`--ep 1` 与 `--ep ep01`。
    # ★ 2026-11-01：原来只认纯数字，而 Studio 里选出来的是 `ep01` —— 直接 ValueError。
    #   用户在全站看到的都是 epNN，报错却是「invalid literal for int()」，等于把人挡在门外。
    def _ep_no(x):
        d = re.sub(r"[^0-9]", "", str(x))
        if not d:
            ap.error("集号无法解析：%r（要 1 或 ep01 这种）" % (x,))
        return int(d)

    def _per_ep(name, ep, fallback):
        """按集目录优先：`<data>/_eps/<ep>/<name>`（convert 的分集产物）→ 全局。"""
        for d in (DATA / "_eps" / ep, DATA / ep):
            f = d / name
            if f.is_file():
                try:
                    return json.loads(f.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    break
        return fallback

    report = []
    for e in args.episodes:
        ep = "ep%02d" % _ep_no(e)
        report.append(analyze(ep, _per_ep("shots.json", ep, shots),
                              _per_ep("h3_prompts.json", ep, prompts),
                              chars, char_sections))

    if args.json:
        print(json.dumps({"available": sorted(available), "disk": disk, "eps": report},
                         ensure_ascii=False, indent=2))
        return 0

    print("=" * 92)
    print("出片前置体检（零计费）")
    print("  已接入 characters.json : %s" % ", ".join(sorted(available)))
    unwired = {k: v for k, v in sorted(disk.items()) if k not in available}
    print("  已生成但未接入        : %s" % (", ".join("%s(%s)" % (k, v) for k, v in unwired.items()) or "无"))
    print("=" * 92)

    total, all_missing = 0, {}
    for r in report:
        total += r["n"]
        print("\n【%s】%d 段" % (r["ep"], r["n"]))
        print("-" * 92)
        if args.plan_refs:
            for row in r["rows"]:
                print("  %-14s 当前: %s" % (row["shot"], ",".join(row["refs"]) or "—"))
                print("  %-14s 应有: %s" % ("", ",".join(row["target"]) if row["target"] else "—"))
                if row["issue"] != "OK":
                    print("  %-14s 问题: %s" % ("", row["issue"]))
        else:
            print("  %-14s %-34s %-5s %-5s %s" % ("shot", "应有参考图", "maxP", "实发", "问题"))
            for row in r["rows"]:
                print("  %-14s %-34s %-5s %-5s %s"
                      % (row["shot"], ",".join(row["target"])[:34] if row["target"] else "—",
                         row["maxP"] or "—", len(row["refs"]), row["issue"]))
        if r["missing"]:
            all_missing.update(r["missing"])
            print("  ★ 本集缺失角色: %s"
                  % ", ".join("%s%s" % (n, "（第%s节，%s）" % (s, disk.get("char_%02d" % s, "未生成")) if s else "（资产库无此人）")
                              for n, s in sorted(r["missing"].items(), key=lambda x: x[1] or 99)))
        print("  耗时估算: %d 段 × %d 秒 ≈ %.1f 小时"
              % (r["n"], SEC_PER_SEG, r["n"] * SEC_PER_SEG / 3600))

    print("\n" + "=" * 92)
    print("汇总")
    print("=" * 92)
    print("  段数        : %d" % total)
    print("  出片耗时    : %.1f 小时" % (total * SEC_PER_SEG / 3600))
    known = {n: s for n, s in all_missing.items() if s}
    unknown = [n for n, s in all_missing.items() if not s]
    if known:
        print("  需补人物    : %d 个 → %s" % (len(known), ", ".join("第%s节%s" % (s, n) for n, s in sorted(known.items(), key=lambda x: x[1]))))
        print("  人物出图    : %d 张 ≈ %.1f 分钟"
              % (len(known), len(known) * SEC_PER_CHAR / 60))
    if unknown:
        print("  资产库没有  : %s  ← 需新写提示词或改为纯文字" % ", ".join(unknown))
    print("  合计（出片+资产）≈ %.1f 小时"
          % ((total * SEC_PER_SEG + len(known) * SEC_PER_CHAR) / 3600))
    return 0


if __name__ == "__main__":
    sys.exit(main())
