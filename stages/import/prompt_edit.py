# -*- coding: utf-8 -*-
"""单镜提示词的读取 / 校验 / 写回（只解决一件事）。

为什么单独一个脚本，而不是塞进 `h3_prompt.py` 或 Web 层
--------------------------------------------------------
· 放 Web 层：解析规则要和 `h3_prompt.py` 的 `SECTIONS` / `lint()` 保持同步，
  一旦 Web 自己写一份正则，引擎改契约后 UI 会静默用旧规则 —— 这正是「假检查」。
· 放 `h3_prompt.py`：那个脚本的职责是**批量体检**（扫整目录、出报告）。
  单镜读写是另一条使用路径（Studio 打开一镜、改一段、存回去），混进去会让
  两个职责互相牵制（比如批量模式的输出格式不能随便改）。

所以：新脚本，复用 `h3_prompt` 的解析与校验，只做「一镜」的事。
它不改任何既有脚本的行为，Web 通过子进程调用它（Web 不 import 引擎）。

三个模式
--------
    read   读一镜：定位文件 → 归一 → 六段 → lint。**只读**。
    check  校验一段候选文本（不落盘）。给前端「保存前先看看」用。
    save   校验通过后写回：先备份 `.bak-<时间戳>`，再原子替换，再复检。

定位规则（本机实测得出，不是推测）
----------------------------------
`_layout.data_dir()` 在这些项目里解析到 `06-提示词`（`layout.json` 的 `data_rel="../06-提示词"`），
真实文件是 `06-提示词/<ep>/h3_prompts.json`。**注意 `<ep>` 这一层**：
历史上 `studio.prompt_of()` 少拼了这一层，于是永远返回 `no_prompts` ——
提示词面板一直是空的，而没人报错。

`shot_001` 这种 id 在每一集都存在，所以不指定 `--ep` 时必须能发现歧义并报出来，
不能默默取第一份。

```bash
python stages/import/prompt_edit.py read  --workspace <剧目录> --shot shot_001 --json
python stages/import/prompt_edit.py read  --workspace <剧目录> --shot shot_001 --ep ep03 --json
python stages/import/prompt_edit.py check --workspace <剧目录> --shot shot_001 --ep ep03 --text-file x.txt --json
python stages/import/prompt_edit.py save  --workspace <剧目录> --shot shot_001 --ep ep03 --text-file x.txt --json
```
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import h3_prompt                       # noqa: E402  （同目录，复用解析与校验的唯一真源）
from _layout import data_dir           # noqa: E402

SHOT_RE = re.compile(r"^shot_\d{1,4}$")
# 分镜页传过来的是 `ep01_shot_001`（集号+镜号的合成 id），提示词文件里的键却是 `shot_001`。
# 两种都收：前者拆成 (ep, shot)，后者按原样用。只认这两种形态，别的一律 bad_shot ——
# 放宽成正则通配就会把 `../../x` 之类的路径混进来。
EP_SHOT_RE = re.compile(r"^(ep\d{1,4})_(shot_\d{1,4})$", re.I)
EP_RE = re.compile(r"^ep\d{1,4}$", re.I)
PROMPT_NAME = "h3_prompts.json"
BLOCKING = ("struct", "label")         # 与 h3_prompt.lint 的 bucket 语义一致


class Bad(Exception):
    """参数或定位失败 → 输出 {"ok": false, "reason": ...}，不抛栈。"""

    def __init__(self, reason, **extra):
        super().__init__(reason)
        self.reason = reason
        self.extra = extra


# ---------------------------------------------------------------------------
# 定位
# ---------------------------------------------------------------------------
def prompt_files(ws) -> list:
    """→ [(ep, path)]，按集号排序；根下若还有一份无集号的旧文件，ep 记为 ''。"""
    root = pathlib.Path(data_dir(str(ws)))
    out = []
    if root.is_dir():
        for p in sorted(root.glob("*/" + PROMPT_NAME)):
            out.append((p.parent.name, p))
        legacy = root / PROMPT_NAME
        if legacy.is_file():
            out.append(("", legacy))
    return out


def _read_json(p: pathlib.Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def locate(ws, shot: str, ep: str):
    """→ (ep, path, record)。

    不指定 ep 时：在所有集里找含这一镜的文件；0 个 → not_found，≥2 个 → ambiguous。
    """
    files = prompt_files(ws)
    if not files:
        raise Bad("no_prompts", detail="这个工作区没有找到 <ep>/h3_prompts.json")

    if ep:
        hit = [x for x in files if x[0].lower() == ep.lower()]
        if not hit:
            raise Bad("no_such_ep", ep=ep, candidates=[e for e, _ in files if e][:40])
        e, p = hit[0]
        rec = _read_json(p)
        if not isinstance(rec, dict):
            raise Bad("bad_json", rel=_rel(ws, p))
        if shot not in rec:
            raise Bad("not_found", ep=e, rel=_rel(ws, p))
        return e, p, rec

    hits = []
    for e, p in files:
        rec = _read_json(p)
        if isinstance(rec, dict) and shot in rec:
            hits.append((e, p, rec))
    if not hits:
        raise Bad("not_found", candidates=[e for e, _ in files if e][:40])
    if len(hits) > 1:
        raise Bad("ambiguous", candidates=[e for e, _, _ in hits])
    return hits[0]


def _rel(ws, p: pathlib.Path) -> str:
    try:
        return str(pathlib.Path(p).resolve().relative_to(pathlib.Path(ws).resolve())).replace("\\", "/")
    except Exception:                                  # noqa: BLE001
        return str(p)


# ---------------------------------------------------------------------------
# 组装一个镜头的结果
# ---------------------------------------------------------------------------
# 段头行内接正文：`summary: [reference generation]`
# ★ 实测结论（2026-11-10）：`h3_prompt.split_sections` 的 docstring 写着「允许行内接正文」，
#   但实现里 `(.*)$` 已经把行内内容吃掉了，段体取到的是空串 —— 于是这种写法会被判「缺该段」。
#   不在这里改它的判据（改了会放过本该拦的提示词），而是**把真实原因说出来**：
#   否则用户看到「缺 summary 段」会去检查自己写没写，而其实写了、只是写在同一行。
_INLINE_HEAD = re.compile(
    r"^[ \t]*(" + "|".join(h3_prompt.SECTIONS) + r")[ \t]*[：:][ \t]*(\S.*)$", re.M)
_HEAD_ANY = re.compile(r"^[ \t]*(" + "|".join(h3_prompt.SECTIONS) + r")[ \t]*[：:]", re.M)


def preamble(text: str) -> str:
    """第一个段头之前的全部内容（老格式的「资产图锚定：…」这类前言）。

    为什么要单独拿出来：按段重组正文时，如果直接把六段拼起来，前言会被**静默丢掉**。
    丢掉前言 = 丢掉「这张图是谁」的绑定说明，比报错严重得多。
    """
    m = _HEAD_ANY.search(text or "")
    return (text[:m.start()] if m else (text or "")).strip()


def inline_hints(text: str, sections: dict) -> list:
    """找出「段头行内接了正文、但段体取不到」的段，给一条能照着修的提示。"""
    out = []
    for m in _INLINE_HEAD.finditer(text or ""):
        key = m.group(1).lower()
        if sections.get(key):
            continue
        out.append([key, "段头行内接正文不被支持：把 %s 后面的内容换到下一行再写" % key])
    return out


def analyse(text: str, *, duration: float = 0.0, n_cast: int = 0) -> dict:
    """原文 → 归一 + 六段 + lint。所有判断都交给 h3_prompt，这里不做二次解读。"""
    norm = h3_prompt.normalize(text)
    sections, order, dup = h3_prompt.split_sections(norm)
    errors, warns = h3_prompt.lint(norm, duration=duration, n_cast=n_cast)
    return {
        "inline_hints": inline_hints(norm, sections),
        "normalized": norm,
        "sections": sections,
        "order": order,
        "duplicated": dup,
        "missing": [k for k in h3_prompt.SECTIONS if k not in sections],
        "structured": h3_prompt.has_sections(norm),
        "errors": [list(x) for x in errors],
        "warnings": [list(x) for x in warns],
        "blocking": [list(x) for x in errors if x[0] in BLOCKING],
        "summary": h3_prompt.summary_line([tuple(x) for x in errors] + [tuple(x) for x in warns]),
    }


def _n_cast(ws, ep: str, shot: str) -> int:
    """参考图槽位数：读同集的 shots.json（读不到就 0 = 不查图号越界）。"""
    if not ep:
        return 0
    p = pathlib.Path(data_dir(str(ws))) / ep / "shots.json"
    d = _read_json(p)
    if isinstance(d, list):
        for it in d:
            if isinstance(it, dict) and it.get("id") == shot:
                return len(it.get("cast") or [])
    if isinstance(d, dict):
        for it in (d.get("shots") or []):
            if isinstance(it, dict) and it.get("id") == shot:
                return len(it.get("cast") or [])
    return 0


def cmd_read(args) -> int:
    ws = args.workspace
    try:
        ep, p, rec = locate(ws, args.shot, args.ep)
    except Bad as exc:
        print(json.dumps(dict({"ok": False, "shot": args.shot, "reason": exc.reason}, **exc.extra),
                         ensure_ascii=False))
        return 2
    row = rec.get(args.shot) or {}
    text = row.get("prompt") or ""
    dur = float(row.get("duration") or 0)
    out = {
        "ok": True, "shot": args.shot, "ep": ep or "",
        "rel": _rel(ws, p),
        "duration": row.get("duration"), "ratio": row.get("ratio"), "voice": row.get("voice"),
        "preamble": preamble(h3_prompt.normalize(text)),
        "section_order": list(h3_prompt.SECTIONS),
    }
    out.update(analyse(text, duration=dur, n_cast=_n_cast(ws, ep, args.shot)))
    out["prompt"] = text
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def build_from_parts(parts: dict) -> str:
    """{"preamble":..., "sections": {k: body}} → 一段完整提示词。

    顺序**只由引擎的 `h3_prompt.SECTIONS` 决定**：前端送来的顺序不参与拼接。
    段头一律独占一行（段体换行写），这是实测唯一能被 `split_sections` 正确读到的写法。
    """
    sec = parts.get("sections") or {}
    blocks = []
    for key in h3_prompt.SECTIONS:
        body = (sec.get(key) or "").strip()
        if body:
            blocks.append(key + ":" + chr(10) + body)
        elif key in sec:
            blocks.append(key + ":" + chr(10))
    head = (parts.get("preamble") or "").strip()
    return (head + chr(10) * 2 if head else "") + (chr(10) * 2).join(blocks)


def _read_text(args) -> str:
    if getattr(args, "parts_file", ""):
        raw = pathlib.Path(args.parts_file).read_text(encoding="utf-8")
        return build_from_parts(json.loads(raw))
    if args.text_file:
        return pathlib.Path(args.text_file).read_text(encoding="utf-8")
    return sys.stdin.read()


def cmd_check(args) -> int:
    ws = args.workspace
    try:
        ep, p, rec = locate(ws, args.shot, args.ep)
    except Bad as exc:
        print(json.dumps(dict({"ok": False, "shot": args.shot, "reason": exc.reason}, **exc.extra),
                         ensure_ascii=False))
        return 2
    text = _read_text(args)
    dur = float((rec.get(args.shot) or {}).get("duration") or 0)
    out = {"ok": True, "shot": args.shot, "ep": ep or "", "rel": _rel(ws, p)}
    out.update(analyse(text, duration=dur, n_cast=_n_cast(ws, ep, args.shot)))
    out.pop("prompt", None)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_save(args) -> int:
    ws = args.workspace
    try:
        ep, p, rec = locate(ws, args.shot, args.ep)
    except Bad as exc:
        print(json.dumps(dict({"ok": False, "shot": args.shot, "reason": exc.reason}, **exc.extra),
                         ensure_ascii=False))
        return 2

    text = _read_text(args)
    row = dict(rec.get(args.shot) or {})
    dur = float(row.get("duration") or 0)
    res = analyse(text, duration=dur, n_cast=_n_cast(ws, ep, args.shot))

    # 结构/标签级错误 = 会把参考图喂错位，默认拒绝落盘。
    # `--force` 留给「我知道我在写半成品」，但必须显式说。
    if res["blocking"] and not args.force:
        print(json.dumps({"ok": False, "reason": "blocked_by_lint", "shot": args.shot,
                          "blocking": res["blocking"], "errors": res["errors"],
                          "warnings": res["warnings"]},
                         ensure_ascii=False, indent=2))
        return 3

    before = row.get("prompt") or ""
    if res["normalized"] == h3_prompt.normalize(before):
        print(json.dumps({"ok": True, "changed": False, "shot": args.shot, "ep": ep or "",
                          "rel": _rel(ws, p), "summary": res["summary"]}, ensure_ascii=False))
        return 0

    # 备份：同一文件同秒内多次保存会撞名，加 1..n 后缀
    stamp = time.strftime("%Y%m%d-%H%M%S")
    bak = p.with_name(p.name + ".bak-" + stamp)
    n = 1
    while bak.exists():
        bak = p.with_name("%s.bak-%s-%d" % (p.name, stamp, n))
        n += 1
    shutil.copy2(p, bak)

    row["prompt"] = res["normalized"]
    rec[args.shot] = row
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)                      # 原子替换：中途失败不会留下半个 JSON

    after = analyse(row["prompt"], duration=dur, n_cast=_n_cast(ws, ep, args.shot))
    print(json.dumps({"ok": True, "changed": True, "shot": args.shot, "ep": ep or "",
                      "rel": _rel(ws, p), "backup": _rel(ws, bak),
                      "summary": after["summary"], "warnings": after["warnings"],
                      "errors": after["errors"]},
                     ensure_ascii=False, indent=2))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="单镜提示词：读 / 校验 / 写回")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("read", "check", "save"):
        p = sub.add_parser(name)
        p.add_argument("--workspace", required=True)
        p.add_argument("--shot", required=True)
        p.add_argument("--ep", default="")
        p.add_argument("--json", action="store_true")
        if name in ("check", "save"):
            p.add_argument("--text-file", dest="text_file", default="")
            p.add_argument("--parts-file", dest="parts_file", default="")
        if name == "save":
            p.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)

    m = EP_SHOT_RE.match(args.shot or "")
    if m:
        if not args.ep:
            args.ep = m.group(1)
        args.shot = m.group(2)
    if not SHOT_RE.match(args.shot or ""):
        print(json.dumps({"ok": False, "reason": "bad_shot", "shot": args.shot}, ensure_ascii=False))
        return 2
    if args.ep and not EP_RE.match(args.ep):
        print(json.dumps({"ok": False, "reason": "bad_ep", "ep": args.ep}, ensure_ascii=False))
        return 2

    return {"read": cmd_read, "check": cmd_check, "save": cmd_save}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
