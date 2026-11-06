#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""h3_prompt.py —— MiniMax H3 多参（Ref2VA）提示词契约的**唯一判据**

为什么锁这个格式
----------------
H3 的多参生成不是「把参考图丢进去 + 一段自然语言」就能对齐的。它要求提示词里
**用 `<Picture n>` / `<Subject n>` 明确绑定每张参考图**，并且分六段说明
「参考什么 / 关系是什么 / 每一秒发生什么」。缺了绑定，上传的参考图对模型而言只是
「几张没署名的图」，人物与场景会漂。

2026-11-06 的实测把这一点钉死了：老格式把图号写成 `{{Mixed 2}}` —— 这是我们自己的
模板占位符，H3 **不认识**，于是它被当成正文一起读进去。同一批镜里「参考图在，人物不像」
的根因就在这。本模块把正确写法变成可执行判据，替代「文档里说说、靠自觉」。

六段结构（顺序不可改，段名恒为英文）
------------------------------------
    subject_definitions   参考内容与标签：每个 <Picture n> / <Subject n> 是什么
    summary               任务类型前缀 + 一段总述（只用已定义标签）
    retention_analysis    逐标签写「保留到什么程度」，标记词取自固定枚举
    detailed_description  正文：先立画风，再按 [Shot n] / At MM:SS.mmm 写动作与台词
    overall_soundscape    环境音 / 物理动作音 / 非语言人声
    non_diegetic_music    只有观众听得见的配乐；没有就写 N/A

口径来源
--------
* 官方：`h3-prompt-writing/references/ref-en.txt`（六段名、标签语义、标记词枚举）
* 本仓库的落地约定：**结构标记用英文，正文用项目语言**（中文项目即中文）。
  这条与官方「正文也用英文」不同，是有意的：本管线的台词、资产描述、画风锁都是中文，
  混排英文正文会让模型在两种语域之间摇摆。判据只认结构，不认正文语种。

三条纪律
--------
1. **只判不修**：本模块不替作者改句子。能机械做的只有一件事 ——
   把 `{{Mixed n}}` / `{{Picture n}}` 归一成 `<Picture n>`，因为那是我们自己的历史占位符。
2. **阻断项只放「错了必然浪费钱」的**：六段缺失、标签悬空、标记词乱写。
   正文长短、镜头切分这类质量问题只告警 —— 拦下来只会让人去删告警。
3. **判据只有一份**：转换（md2pack）、门禁（pack_spec）、体检 CLI 三处都调这里。
   任何一处另写正则，就会出现「转换说行、导入说不行」。

用法
----
    python stages/import/h3_prompt.py --workspace <剧目录>            # 体检 06-提示词/*/h3_prompts.json
    python stages/import/h3_prompt.py --file <某个 md 或 json>         # 体检单个文件
    python stages/import/h3_prompt.py --file x.md --json               # 机器可读
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

# 六段：顺序即契约。改名/换序 = 换契约，下游全部要跟着改。
SECTIONS = (
    "subject_definitions",
    "summary",
    "retention_analysis",
    "detailed_description",
    "overall_soundscape",
    "non_diegetic_music",
)

# 关系标记词（固定英文枚举，不许自造同义词）
VISIBLE_MARKERS = ("fully_preserved", "partially_preserved",
                   "attribute_transfer", "weak_reference")
AUDIO_MARKERS = ("fully_copy", "partially_copy", "reference", "weak_reference")

# 任务类型前缀（`summary` 开头方括号里的值，多关系用 ` + ` 连接）
TASK_TYPES = ("keyframe completion", "reference generation", "video editing",
              "video continuation", "audio reuse", "audio reference")

# 段头：允许行内接正文（`summary: [reference generation] …` 是常见写法）
_SECTION_HEAD = re.compile(
    r"^[ \t]*(" + "|".join(SECTIONS) + r")[ \t]*[：:][ \t]*(.*)$", re.M)
# 历史占位符：本仓库 2026-11 之前所有模板都写这个。H3 不认，必须归一。
_PLACEHOLDER = re.compile(r"\{\{\s*(?:Mixed|Picture)\s*(\d+)\s*\}\}")
_LABEL = re.compile(r"<(Subject|Picture|Video|Audio)\s+(\d+)\s*>")
_DEF_HEAD = re.compile(r"^[ \t]*<(Subject|Picture)\s+(\d+)\s*>", re.M)
_SHOT = re.compile(r"\[Shot\s+(\d+)\]\s*(?:At\s+(\d{2}):(\d{2})(?:[.:](\d{1,3}))?)?")
_MARKER = re.compile(r"\b(" + "|".join(
    sorted(set(VISIBLE_MARKERS + AUDIO_MARKERS), key=len, reverse=True)) + r")\b")
_SPEAKER = re.compile(r"<d>[\s\S]*?</d>")
_SPEAKER_ID = re.compile(r"[（(]S\d+[）)]")
_CJK = re.compile(r"[\u4e00-\u9fff]")
_SENT_END = "。！？!?…"


# ===========================================================================
# 解析
# ===========================================================================
def normalize(text: str) -> str:
    """机械归一：占位符 → `<Picture n>`，顺手清掉会漏进画面的脚手架行。

    只做三件事，都不改语义：

    1. `{{Mixed 2}}` / `{{Picture 2}}` → `<Picture 2>`（H3 只认后者）
    2. 删掉 `上传顺序：…` 整行 —— 那是写给人的对位表，被当成正文提交时 H3 会
       尝试在画面里渲染「Mixed 1＝shot_001 分镜图」这类文字（而且它本来就是中文）。
       图号信息在 `cast` 顺序里，删掉不丢信息。
    3. CRLF → LF、去 BOM、压掉 3 个以上连续空行（避免模型把空行当分镜）。

    幂等：对同一段文本反复调用结果不变。
    """
    src = str(text or "").replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    src = _PLACEHOLDER.sub(lambda m: "<Picture %s>" % m.group(1), src)
    kept = [ln for ln in src.splitlines() if not re.match(r"^[ \t]*上传顺序[：:]", ln)]
    out = "\n".join(kept)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def split_sections(text: str) -> tuple:
    """→ (sections, order, duplicated)。

    `sections` 只保留**首次**出现的段（重复的不覆盖，交给 `duplicated` 报错）。
    段体从段头行末开始，到下一个段头行之前结束 —— 所以 `summary: [..] …` 这种
    行内写法也能正确取到正文。
    """
    src = str(text or "")
    hits, order, sections, dup = [], [], {}, []
    for m in _SECTION_HEAD.finditer(src):
        key = m.group(1).lower()
        if key in sections:
            dup.append(key)
            continue
        order.append(key)
        sections[key] = {"at": m.start(), "body_at": m.end()}
        hits.append((key, m.start(), m.end()))
    for i, (key, _start, body_at) in enumerate(hits):
        end = hits[i + 1][1] if i + 1 < len(hits) else len(src)
        sections[key]["body"] = src[body_at:end].strip()
    return {k: v["body"] for k, v in sections.items()}, order, dup


def has_sections(text: str) -> bool:
    """六段是否齐全（顺序不管）。给转换层做「这是不是老格式」的快判。"""
    sec, _order, _dup = split_sections(text)
    return all(k in sec for k in SECTIONS)


def looks_structured(text: str) -> bool:
    """出现了**任何**一个段头 → 视为「六段式阵营」（哪怕写漏了几段）。

    用途只有一个：`--drop-missing-cast` 在六段式阵营里会被拒绝执行 ——
    摘一张参考图要连 `<Picture n>` / `<Subject n>` 编号与 retention 行一起重排，
    机械重排没法保证 `detailed_description` 里的引用还成立。半点式与老格式分开处理，
    比「两种写法共用一套正则」安全。
    """
    _sec, order, _dup = split_sections(text)
    return bool(order)


def definitions(text: str) -> list:
    """→ [(kind, num, body)]，按出现顺序。

    `kind` 是 `Subject` / `Picture`；`body` 是该定义行到下一个定义行之间的全文
    （允许多行，官方样例里 Subject 定义常折行）。
    """
    sec, _o, _d = split_sections(text)
    block = sec.get("subject_definitions", "")
    hits = list(_DEF_HEAD.finditer(block))
    out = []
    for i, m in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(block)
        out.append((m.group(1), int(m.group(2)), block[m.end():end].strip()))
    return out


def retention_rows(text: str) -> list:
    """→ [(kind, num, line)]，只收以标签开头的行（其余行当说明文字忽略）。"""
    sec, _o, _d = split_sections(text)
    rows = []
    for line in sec.get("retention_analysis", "").splitlines():
        m = re.match(r"^[ \t]*<(Subject|Picture|Video|Audio)\s+(\d+)\s*>", line)
        if m:
            rows.append((m.group(1), int(m.group(2)), line.strip()))
    return rows


def _labels(text: str) -> set:
    return {(m.group(1), int(m.group(2))) for m in _LABEL.finditer(text)}


def _cjk_len(text: str) -> int:
    return len(_CJK.findall(text))


# ===========================================================================
# 判据
# ===========================================================================
def lint(text: str, *, duration: float = 0.0, n_cast: int = 0) -> tuple:
    """校验一段视频提示词。→ (errors, warnings)，每项 `(bucket, ident, msg)`。

    `bucket` 决定门禁行为，只有三档：

    | bucket | 含义 | 门禁 |
    |---|---|---|
    | `struct` | 六段结构不成立 —— 模型读不到「参考什么」 | SHOT019 **阻断** |
    | `label` | 标签悬空 / 图号不连续 —— 参考图会喂错位 | SHOT020 **阻断** |
    | `quality` | 结构对了但写得薄 —— 出片会「能看但不像」 | SHOT021 **告警** |

    `duration` 给了才查时间戳是否越界；`n_cast` 给了才查图号是否超出槽位。
    """
    errors, warns = [], []
    src = normalize(text)
    if not src:
        return [("struct", "H3-E01", "提示词为空")], []

    sec, order, dup = split_sections(src)

    # ---- 结构 ------------------------------------------------------------
    missing = [k for k in SECTIONS if k not in sec]
    if missing:
        errors.append(("struct", "H3-E01",
                       "缺 %s 段（H3 多参要求六段齐全，缺段就等于没告诉模型参考什么）"
                       % "、".join(missing)))
    want_order = [k for k in SECTIONS if k in sec]
    if order and order != want_order:
        errors.append(("struct", "H3-E01",
                       "段顺序不对：实际 %s（应为 %s）" % (" → ".join(order), " → ".join(SECTIONS))))
    if dup:
        errors.append(("struct", "H3-E01", "段重复出现：%s" % "、".join(sorted(set(dup)))))

    left = _PLACEHOLDER.findall(src)
    if left:
        errors.append(("struct", "H3-E02",
                       "残留 %d 处 {{Mixed n}} 占位符 —— H3 不认这种写法，会被当正文念进画面" % len(left)))
    if re.search(r"<Video\s+\d+\s*>", src):
        errors.append(("struct", "H3-E03",
                       "出现 <Video N>：本管线只上传参考图，没有视频参考，该标签无法绑定"))

    body_summary = sec.get("summary", "")
    head = re.match(r"^\s*\[([^\]]+)\]", body_summary)
    if not head:
        errors.append(("struct", "H3-E04",
                       "summary 必须以任务类型前缀开头，如 `[reference generation]`"))
    else:
        kinds = [x.strip() for x in head.group(1).split("+") if x.strip()]
        bad = [k for k in kinds if k not in TASK_TYPES]
        if bad or not kinds:
            errors.append(("struct", "H3-E04",
                           "summary 的任务类型不认识：%s（可选 %s）"
                           % ("、".join(bad) or "空", " / ".join(TASK_TYPES))))

    # ---- 标签 ------------------------------------------------------------
    defs = definitions(src)
    subs = [(n, b) for k, n, b in defs if k == "Subject"]
    pics = [(n, b) for k, n, b in defs if k == "Picture"]
    if not subs:
        errors.append(("label", "H3-E05",
                       "subject_definitions 里没有 <Subject n>：参考图只是「几张没署名的图」，"
                       "人物会漂。至少给每个出场角色/场景写一条 `<Subject n> 是 <Picture k> 中的…`"))
    else:
        nums = sorted(n for n, _ in subs)
        if nums != list(range(1, len(nums) + 1)):
            errors.append(("label", "H3-E05",
                           "<Subject n> 编号不连续：%s（必须是 1..%d）" % (nums, len(nums))))

    # 每个 Subject 必须引用至少一张图；被引用的图号必须从 1 起连续（空号会让后面全部错位）
    cited = set()
    for n, body in subs:
        here = {int(x) for x in re.findall(r"<Picture\s+(\d+)\s*>", body)}
        if not here:
            errors.append(("label", "H3-E06",
                           "<Subject %d> 没有引用任何 <Picture n> —— 无法说明它的形象来自哪张图" % n))
        cited |= here
    cited |= {n for n, _ in pics}                        # 独立 Picture 定义（分镜图锚点）
    if cited:
        top = max(cited)
        gap = [i for i in range(1, top + 1) if i not in cited]
        if gap:
            errors.append(("label", "H3-E06",
                           "<Picture n> 编号有空号：%s（必须从 1 起连续）" % gap))
        if n_cast and top > n_cast + 1:
            errors.append(("label", "H3-E06",
                           "提示词点到 <Picture %d>，但本镜只有 %d 张参考图（分镜图占 1 号）"
                           % (top, n_cast + 1)))

    defined = {("Subject", n) for n, _ in subs} | {("Picture", n) for n, _ in pics}
    rows = retention_rows(src)
    have_rows = {(k, n) for k, n, _ in rows}
    for kind, num in sorted(defined - have_rows):
        errors.append(("label", "H3-E07",
                       "retention_analysis 缺 <%s %d> 的行（每个已定义标签都要写保留到什么程度）"
                       % (kind, num)))
    for kind, num, line in rows:
        if (kind, num) not in defined:
            errors.append(("label", "H3-E07",
                           "retention_analysis 写了未定义的 <%s %d>" % (kind, num)))
        if not _MARKER.search(line):
            errors.append(("label", "H3-E07",
                           "retention_analysis 的 <%s %d> 没有关系标记词（%s）"
                           % (kind, num, " / ".join(VISIBLE_MARKERS[:2] + ("…",)))))

    # ---- 质量 ------------------------------------------------------------
    body = sec.get("detailed_description", "")
    shots = list(_SHOT.finditer(body))
    if not shots:
        warns.append(("quality", "H3-W01",
                      "detailed_description 里没有 [Shot 1]：模型拿不到分镜切点，只会当一段连续动作"))
    else:
        for m in shots:
            if int(m.group(1)) > 1 and m.group(2) is None:
                warns.append(("quality", "H3-W02",
                              "[Shot %s] 缺 `At MM:SS.mmm`（第 2 镜起必须给切点时间）" % m.group(1)))
                break
        if duration:
            total = 0.0
            for m in shots:
                if m.group(2) is None:
                    continue
                sec_ = int(m.group(2)) * 60 + int(m.group(3))
                if m.group(4):
                    sec_ += float("0." + m.group(4))
                total = max(total, sec_)
            if total >= duration:
                warns.append(("quality", "H3-W06",
                              "最后一个 [Shot n] 的时间戳 %.3fs 不早于本镜时长 %.0fs —— "
                              "超出的部分会被截掉" % (total, duration)))
    # 正文体量：按「每秒约 15 字」估下限（低于 90 字一律算薄）。
    # 为什么按秒：4 秒空镜与 15 秒双人调度需要的描述量差三倍，写死一个数会两头错。
    # 这个数只用来提示「写得像提纲」，不是合格线 —— 所以放在 quality 档，不阻断。
    cjk = _cjk_len(body)
    need = max(90, int(15 * duration)) if duration else 90
    if cjk < need:
        warns.append(("quality", "H3-W04",
                      "detailed_description 只有 %d 个汉字（本镜 %s 秒，建议 ≥%d）：多参要写清"
                      "每个镜头里谁在哪、做什么、镜头怎么动，太短模型只能自由发挥"
                      % (cjk, ("%.0f" % duration) if duration else "?", need)))
    dialogue = _SPEAKER.findall(body)
    if dialogue and not _SPEAKER_ID.search(body):
        warns.append(("quality", "H3-W05",
                      "有 <d> 台词但全文没有 (S1)/(S2) 说话人编号：多人对话会分不清谁在说"))
    for seg in re.findall(r"<d>(.*?)</d>", body, re.S):
        line = seg.strip()
        if line and line[-1] not in _SENT_END:
            warns.append(("quality", "H3-W03",
                          "<d> 里的句子没有句末标点（…%s）：会与下一句连成一条语音" % line[-12:]))
            break
    music = sec.get("non_diegetic_music", "").strip()
    if not music:
        warns.append(("quality", "H3-W07",
                      "non_diegetic_music 为空：没有配乐就明确写 `N/A`，留空模型会自己加 BGM"))

    return errors, warns


def summary_line(codes: list) -> str:
    """给报告用的一行结论：把 (bucket, ident) 压成 `结构2/标签1/质量3`。"""
    if not codes:
        return "OK"
    bag = {}
    for bucket, _ident, _msg in codes:
        cn = {"struct": "结构", "label": "标签", "quality": "质量"}[bucket]
        bag[cn] = bag.get(cn, 0) + 1
    return " / ".join("%s%d" % (k, v) for k, v in bag.items())


# ===========================================================================
# CLI：体检（不改文件）
# ===========================================================================
def _iter_targets(ws: pathlib.Path, eps) -> list:
    """`<ws>/06-提示词/<ep>/h3_prompts.json`。目录名跟随 `_layout.data_dir()`。"""
    stages = pathlib.Path(__file__).resolve().parents[1]
    if str(stages) not in sys.path:
        sys.path.insert(0, str(stages))
    try:
        import _layout                                            # noqa: PLC0415
        root = pathlib.Path(_layout.data_dir(ws))
    except Exception:                                             # noqa: BLE001
        root = ws / "06-提示词"
    out = []
    for p in sorted(root.glob("*/h3_prompts.json")):
        if eps and p.parent.name not in eps:
            continue
        out.append(p)
    return out


def _lint_file(path: pathlib.Path) -> dict:
    """一个文件 → 逐镜结果。支持 `h3_prompts.json` 与导演手册 md。"""
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    rows = []
    if path.suffix.lower() == ".json":
        try:
            doc = json.loads(raw)
        except ValueError as e:
            return {"file": str(path), "error": "无法解析 JSON：%s" % e, "shots": []}
        for sid, rec in doc.items():
            if not isinstance(rec, dict):
                continue
            e, w = lint(str(rec.get("prompt") or ""), duration=float(rec.get("duration") or 0))
            rows.append({"shot": sid, "errors": e, "warnings": w})
    else:
        # 手册：按 `### 镜 N` 切，只取 B 段围栏
        chunks = re.split(r"^###[ \t]*镜[ \t]*(\d+)", raw, flags=re.M)
        for i in range(1, len(chunks) - 1, 2):
            no, body = chunks[i], chunks[i + 1]
            m = re.search(r"\*\*B段[：:][^*]*\*\*\s*```[a-zA-Z]*\n(.*?)\n```", body, re.S)
            if not m:
                rows.append({"shot": "shot_%03d" % int(no), "errors": [
                    ("struct", "H3-E01", "没有 B 段围栏（引擎按 `**B段：**` 切分）")], "warnings": []})
                continue
            dur = re.search(r"\*\*时长\*\*[：:]\s*(\d+(?:\.\d+)?)\s*s", body)
            e, w = lint(m.group(1), duration=float(dur.group(1)) if dur else 0.0)
            rows.append({"shot": "shot_%03d" % int(no), "errors": e, "warnings": w})
    return {"file": str(path), "shots": rows}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="体检 H3 多参提示词是否合规（只读，不改文件）")
    ap.add_argument("--workspace", help="剧目录；扫 06-提示词/*/h3_prompts.json")
    ap.add_argument("--ep", default="", help="只查这些集（逗号分隔，如 ep01,ep02）")
    ap.add_argument("--file", action="append", default=[], help="直接指定文件（.json 或 .md）")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    a = ap.parse_args(argv)

    targets = [pathlib.Path(f).expanduser().resolve() for f in a.file]
    if a.workspace:
        eps = {x.strip() for x in re.split(r"[,\s]+", a.ep) if x.strip()}
        targets += [p.resolve() for p in _iter_targets(pathlib.Path(a.workspace).expanduser(), eps)]
    if not targets:
        ap.error("给 --workspace 或 --file")

    reports = [_lint_file(p) for p in targets]
    bad = sum(len(r["errors"]) for rep in reports for r in rep.get("shots", []))

    if a.json:
        print(json.dumps({"files": reports, "errors": bad}, ensure_ascii=False, indent=2))
        return 0 if bad == 0 else 1

    for rep in reports:
        shots = rep.get("shots") or []
        print("\n== %s" % rep["file"])
        if rep.get("error"):
            print("   [FAIL] %s" % rep["error"])
            continue
        ok = sum(1 for s in shots if not s["errors"] and not s["warnings"])
        print("   %d 镜 ｜ 全绿 %d ｜ 阻断 %d ｜ 告警 %d"
              % (len(shots), ok,
                 sum(1 for s in shots if s["errors"]),
                 sum(1 for s in shots if s["warnings"])))
        for s in shots:
            if not s["errors"] and not s["warnings"]:
                continue
            print("   %-10s %s" % (s["shot"], summary_line(s["errors"] + s["warnings"])))
            for bucket, ident, msg in s["errors"] + s["warnings"]:
                mark = "NG" if bucket != "quality" else "WARN"
                print("      [%s] %-7s %s" % (mark, ident, msg))

    print("\n%s：阻断项 %d" % ("[FAIL] 不合规" if bad else "[OK] 全部合规", bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
