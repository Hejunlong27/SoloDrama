#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""prompt_marks.py —— 视频提示词「台词标记」的**唯一真源**（`<d>[语种] 原句。</d>`）

一句话结论
----------
**台词必须写成 `<d>[语种] 原句。</d>`**。裸写在引号里的目标语言文本，H3 会当成
「画面中应当出现的文字」，直接烧成画面字幕 —— 出片后无法去除，只能重跑。

这不是工作流缺开关，是提示词写法问题：调工作流、加负向词、加「不生成任何字幕」都无效
（BasicGuider 等价 cfg=1，负向不参与引导）。三组同实例对照（固定 seed 123456）证明
**关键变量就是 `<d>` 标记**，把整篇改写成英文六段式没有额外收益。

实测依据：`docs/patches/2026-11-06_H3台词烧字幕_patch提案.md`

为什么单独成文件
----------------
同一件事有三处要判：
  · `md2pack.py`（转换）—— 自动补标记，让老手册也能出干净片；
  · `pack_spec.py`（门禁）—— 只告警不阻断（模型对标记的遵循不是 100%）；
  · 本文件的 CLI       —— 重写老项目已有的 `06-提示词/<ep>/h3_prompts.json`。

三处各写一份正则，必然漂成三个口径 —— 本仓库在「五锚」「集号 epNN」上都吃过这个亏。

设计纪律
--------
1. **只动提示词，不动台词数组**：`dialogue[].text` 是字幕对齐用的纯文本，
   给它套标记会污染字幕（字幕里会出现 `<d>[Chinese]`）。
2. **幂等**：已带 `<d>` 的句子不动，二次转换不会变成 `<d><d>`。
3. **宁少改不多改**：只自动包「有说话动词」和「口型对齐台词」两种高置信写法。
   招牌/标语里的引号中文（`招牌写着："营业中"`）**不包** —— 把它改成台词是另一种错。
   那种情况由门禁告警，交给人判断。

用法
----
    # 看一眼哪些镜的提示词会烧字幕（不写盘）
    python stages/import/prompt_marks.py --workspace <剧目录>

    # 落盘（每份文件先落 .bak-时间戳）
    python stages/import/prompt_marks.py --workspace <剧目录> --apply

    # 只处理某一集；跨语种项目指定语种标签
    python stages/import/prompt_marks.py --workspace <剧目录> --ep ep02 --lang Spanish --apply
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import re
import sys

# 默认语种标签。西语/英语项目用 --lang 覆盖，别在这里加分支。
LANG_DEFAULT = "Chinese"

MARK_OPEN = "<d>"
MARK_CLOSE = "</d>"

# 已有标记的区间：这些位置一律跳过（幂等的第一道保险）
MARK_SPAN = re.compile(r"<d>.*?</d>", re.S)

# 句末合法标点：H3 的语音事件要求句子闭合（`.!?` 也算 —— 跨语种项目的句子未必用中文标点）
SENT_END = "。！？!?…."

# 说话动词。宁可少列，也不要让「说明：」「提示：」这类误命中 —— 它们后面基本不带引号台词，
# 但列进来会让误报难以排查。
SPEECH_VERB = (
    "说|道|问|答|喊|叫|吼|嚷|骂|念|读|笑|讲|谈|劝|嚷|"
    "命令|吩咐|嘱咐|叮嘱|提醒|解释|介绍|补充|反问|追问|回答|"
    "嘟囔|咕哝|低语|耳语|开口|叹|哭|念出声|开口说"
)

# ① 旧模板教出来的最脏写法：`时小满口型对齐台词"这个箱子周三之前不许开"`（人名为可选）
LIPSYNC_BARE = re.compile(
    r"(?:(?P<who>[\u4e00-\u9fa5A-Za-z·]{1,12})\s*)?口型对齐台词\s*[：:]?\s*"
    r"[“\"](?P<line>[^”\"\n]{1,160})[”\"]"
)

# ② 说话动词 + 冒号 + 引号：`周然笑着说："念念，这件真好看。"` / `王总："……"`
SAY_BARE = re.compile(
    r"(?P<head>(?:%s)(?:着|了|出声|道)?[^：:\n]{0,8}[：:])\s*[“\"](?P<line>[^”\"\n]{1,160})[”\"]"
    % SPEECH_VERB
)

# ③ 门禁用：任何「冒号 + 引号包住的中文」，不要求说话动词（漏网的全在这里）
BARE_ANY = re.compile(r"[：:]\s*[“\"](?P<line>[^”\"\n]{1,160})[”\"]")

CJK = re.compile(r"[\u4e00-\u9fa5]")


def has_mark(text: str) -> bool:
    """文本里有没有至少一个 `<d>…</d>`。"""
    return bool(MARK_SPAN.search(str(text or "")))


def count_marks(text: str) -> int:
    return len(MARK_SPAN.findall(str(text or "")))


def _close(line: str) -> str:
    """句末没有合法标点就补句号 —— `<d>` 是语音事件，句子必须闭合。"""
    s = line.strip()
    return s if s and s[-1] in SENT_END else s + "。"


def _spans(text: str) -> list:
    return [m.span() for m in MARK_SPAN.finditer(text)]


def _overlaps(a: int, b: int, spans: list) -> bool:
    return any(a < y and b > x for x, y in spans)


def normalize_dialogue(text: str, lang: str = LANG_DEFAULT) -> tuple:
    """把裸引号台词包成 `<d>[lang] …</d>` → (新文本, 包了几处)。

    只处理两种高置信写法（见模块头「设计纪律 3」）；已带 `<d>` 的句子不动，可重复调用。
    """
    src = str(text or "")
    if not src.strip():
        return src, 0
    lang = (lang or LANG_DEFAULT).strip() or LANG_DEFAULT
    n = 0

    def _wrap(line: str) -> str:
        return "%s[%s] %s%s" % (MARK_OPEN, lang, _close(line), MARK_CLOSE)

    # ① 口型对齐台词"…" → 说：<d>…</d>（先把 who 保留，标点补在标记内）
    src_spans = _spans(src)

    def _r1(m):
        nonlocal n
        if _overlaps(m.start(), m.end(), src_spans):
            return m.group(0)
        n += 1
        who = (m.group("who") or "").strip()
        # 没有人名时不要凭空补「说：」（会拼出 `约束：说：…` 这种双冒号）
        return ("%s 说：%s" % (who, _wrap(m.group("line")))) if who else _wrap(m.group("line"))

    out = LIPSYNC_BARE.sub(_r1, src)

    # ② 说话动词 + 冒号 + "…" → 保留动词与冒号，只把引号内容换成标记
    out_spans = _spans(out)

    def _r2(m):
        nonlocal n
        if _overlaps(m.start(), m.end(), out_spans):
            return m.group(0)
        n += 1
        return "%s%s" % (m.group("head"), _wrap(m.group("line")))

    out = SAY_BARE.sub(_r2, out)
    return out, n


def find_bare(text: str) -> list:
    """列出**可能**会被烧成字幕的裸引号中文（门禁用，含 normalize 认不出的写法）。

    返回原样的片段。只报含中文的，英文引号（`sign reading "EXIT"`）不报 ——
    那种情况提示词本就不该让模型画字，属于后期合成范畴，不在本条判据内。
    """
    src = str(text or "")
    spans = _spans(src)
    hits = []
    # ① 冒号 + 引号（最常见的台词写法）
    for m in BARE_ANY.finditer(src):
        if _overlaps(m.start(), m.end(), spans):
            continue
        if CJK.search(m.group("line")):
            hits.append(m.group(0).strip())
    # ② `X 口型对齐台词"…"`：没有冒号，但同样会烧
    for m in LIPSYNC_BARE.finditer(src):
        if _overlaps(m.start(), m.end(), spans):
            continue
        hits.append(m.group(0).strip())
    return hits


# ---------------------------------------------------------------------------
# CLI：老项目迁移（重写 06-提示词/<ep>/h3_prompts.json）
# ---------------------------------------------------------------------------
def _prompts_dirs(ws: pathlib.Path) -> list:
    """出片引擎可能读过的输入目录，按优先级去重。

    为什么不只认 `_layout.data_dir()`：那是**当前**生效的目录，而老项目里
    `video-pipeline/data` 与 `06-提示词` 可能同时残留着已出片的 `h3_prompts.json`。
    迁移是一次性动作，两个都扫才不会有片子被漏在角落里继续烧字幕。
    """
    stages = pathlib.Path(__file__).resolve().parents[1]
    if str(stages) not in sys.path:
        sys.path.insert(0, str(stages))
    cands = []
    try:
        import _layout  # noqa: PLC0415
        cands.append(pathlib.Path(_layout.data_dir(ws)))
    except Exception:                                        # noqa: BLE001
        pass
    cands += [ws / "06-提示词", ws / "video-pipeline" / "data"]
    out, seen = [], set()
    for d in cands:
        k = str(d).lower()
        if k in seen or not d.is_dir():
            continue
        seen.add(k)
        out.append(d)
    return out


def migrate(ws, *, eps=None, lang: str = LANG_DEFAULT, apply: bool = False) -> dict:
    """扫描 `<data_dir>/<ep>/h3_prompts.json`，逐镜归一化 → 报告。"""
    ws = pathlib.Path(ws).expanduser().resolve()
    roots = _prompts_dirs(ws)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    files, shots, wrapped, residual, backups = [], 0, 0, [], []

    for p in sorted({x for root in roots for x in root.glob("*/h3_prompts.json")}):
        ep = p.parent.name
        if eps and ep not in eps:
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError, ValueError) as e:
            residual.append({"file": str(p), "reason": "无法解析：%s" % e})
            continue
        if not isinstance(doc, dict):
            residual.append({"file": str(p), "reason": "顶层应为对象"})
            continue
        changed = 0
        for sid, shot in doc.items():
            if not isinstance(shot, dict):
                continue
            old = str(shot.get("prompt") or "")
            if not old:
                continue
            shots += 1
            new, n = normalize_dialogue(old, lang)
            if n:
                shot["prompt"] = new
                wrapped += n
                changed += 1
            left = find_bare(new)
            if left:
                residual.append({"ep": ep, "shot": sid, "bare": left,
                                 "reason": "归一化后仍有裸引号中文，需人工改源（多为招牌/标语写法）"})
        if changed:
            files.append({"file": str(p), "shots": changed})
            if apply:
                bak = p.with_name(p.name + ".bak-" + stamp)
                bak.write_bytes(p.read_bytes())
                backups.append(str(bak))
                p.write_text(json.dumps(doc, ensure_ascii=False, indent=2),
                             encoding="utf-8", newline="")

    return {"roots": [str(r) for r in roots], "apply": apply, "lang": lang,
            "files": files, "shots": shots, "wrapped": wrapped,
            "residual": residual, "backups": backups}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="把视频提示词里的裸引号台词归一化成 <d>[语种] …</d>（幂等）")
    ap.add_argument("--workspace", default=None, help="剧目录（留空读环境变量）")
    ap.add_argument("--ep", default="", help="只处理这些集（逗号分隔，如 ep01,ep02）")
    ap.add_argument("--lang", default=LANG_DEFAULT, help="语种标签（默认 Chinese）")
    ap.add_argument("--apply", action="store_true", help="真写盘（默认只报告）")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    ws = a.workspace or None
    if not ws:
        for k in ("SOLODRAMA_WORKSPACE", "DRAMA_WORKSPACE"):
            import os                                        # noqa: PLC0415
            ws = os.environ.get(k)
            if ws:
                break
    if not ws:
        print("[FAIL] 需要 --workspace（剧目录），或设 SOLODRAMA_WORKSPACE")
        return 2

    eps = [x.strip() for x in re.split(r"[,\s]+", a.ep) if x.strip()] or None
    res = migrate(ws, eps=eps, lang=a.lang, apply=a.apply)

    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0

    print("提示词目录：%s" % " ｜ ".join(res["roots"] or ["（无）"]))
    print("扫描镜头：%d ｜ 已包标记：%d 处 ｜ 改动文件：%d 份"
          % (res["shots"], res["wrapped"], len(res["files"])))
    for f in res["files"]:
        print("  ~ %s（%d 镜）" % (f["file"], f["shots"]))
    if res["backups"]:
        print("备份：%d 份（同名 .bak-*）" % len(res["backups"]))
    if res["residual"]:
        print("\n仍需人工处理 %d 条：" % len(res["residual"]))
        for r in res["residual"][:20]:
            if "bare" in r:
                print("  [%s %s] %s" % (r["ep"], r["shot"], " / ".join(r["bare"])))
            else:
                print("  [%s] %s" % (r["file"], r["reason"]))
        if len(res["residual"]) > 20:
            print("  …（共 %d 条，见 --json）" % len(res["residual"]))
    if not a.apply and res["wrapped"]:
        print("\n这是干跑。确认无误后加 --apply 写盘（会先落 .bak-时间戳）。")
    print("\n⚠ 已出片但未重跑的镜，字幕仍在画面里 —— 字幕一旦烧进成片无法后期去除，只能重跑。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
