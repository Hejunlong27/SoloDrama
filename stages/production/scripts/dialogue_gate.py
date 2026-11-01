# -*- coding: utf-8 -*-
"""dialogue_gate.py —— 台词逻辑复核（剧本环节新增，2026-11-01）

规则来源
--------
`3d-short-drama-studio/references/dialogue-driven-rules.md`（对白驱动单一真源）。
那里写的是**给人和模型看的**规则，本文只把它里面**能机器判**的部分抽出来，
判不了的（「这句有没有功能」「三拍落点是否可摘录」）不假装能判 —— 那属于内容评审，
硬做成规则只会产出一堆不准的红灯。

为什么放在剧本环节而不是分镜环节
--------------------------------
台词是剧本的产物。等分镜才发现「单镜三句台词」「旁白和解说同镜打架」，
改的是剧本，不是分镜。门禁要放在**改起来最便宜**的那一环。

能判什么（E = 硬失败，W = 提示）
--------------------------------
    E1 单镜台词句数 > 2                规则 §3.3「单镜台词 ≤ 2 句」
    E2 单句超长：CJK > 20 字 / 拉丁 > 55 字符        规则 §3.3
    E3 同镜既有旁白又有对白（VO + DIALOG 并存）      规则 R3
    E4 旁白条数超配额（默认 2 条/集）                规则 §二
    E5 旁白出现在中段（非首镜非尾镜）                规则 §二「仅允许开场/结尾」
    E6 台词密度不足（< 10 句/60s，按本集实际时长折算） 规则 §3.4
    W1 连续 3 镜零台词（无对白也无旁白）
    W2 寒暄/纯抒情/已知信息类空台词（词表命中，需人工确认）
    W3 台词写了说话人但不在本镜 CHAR 里

用法
----
    python dialogue_gate.py --workspace "D:/剧/某剧" --ep ep01
    python dialogue_gate.py --workspace "..." --ep ep01 --json
    # 退出码：0 通过｜2 有硬失败（与其余门禁一致）
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import unicodedata

# 台词长度口径（与 FFS lint 的 CJK 20 / 拉丁 55 一致）
CJK_MAX = 20
LATIN_MAX = 55
SHOT_LINES_MAX = 2
DEFAULT_NARRATION_PER_EP = 2

# 空功能台词词表：只做提示，不做硬判 —— 语境能让这些词变成有效台词。
EMPTY_PHRASES = (
    "你好", "谢谢", "对不起", "抱歉", "再见", "晚安", "早上好",
    "知道了", "我明白", "我懂了", "没问题", "好的", "嗯", "哦",
    "你等着", "你会后悔", "走着瞧",
)

_CJK_RE = re.compile(r"[\u3400-\u9fff\u3040-\u30ff]")
_SENT_SPLIT = re.compile(r"[。！？!?…]+|\.(?=\s|$)")
_SPEAKER_RE = re.compile(r"^\s*([A-Z][A-Z0-9_]{1,11})\s*[:：]\s*(.*)$", re.S)
_SHOT_RE = re.compile(r"(?m)^\[SC-(\d+)\]")


def _strip_quotes(s: str) -> str:
    return (s or "").strip().strip("“”\"'「」『』").strip()


def _sentences(text: str) -> list:
    body = _strip_quotes(text)
    if not body:
        return []
    return [x.strip() for x in _SENT_SPLIT.split(body) if x and x.strip()]


def _is_empty_marker(v: str) -> bool:
    """FFS 里「没有」写成 `无` / `N/A` / `-` / 空。"""
    return _strip_quotes(v).lower() in ("", "无", "n/a", "na", "-", "none")


def parse_script(text: str) -> dict:
    """剧本 md → {header:{codes}, shots:[{id, char:[], duration, dialog, vo, action}]}"""
    head = text[:_SHOT_RE.search(text).start()] if _SHOT_RE.search(text) else text
    codes = []
    for m in re.finditer(r"(?m)^#?\s*CHAR\s*[:：]\s*(.+)$", head):
        for part in re.split(r"[,，、;；]", m.group(1)):
            name = part.split(":", 1)[0].split("：", 1)[0].strip()
            if name and re.fullmatch(r"[A-Z][A-Z0-9_]{1,11}", name):
                codes.append(name)

    shots = []
    marks = list(_SHOT_RE.finditer(text))
    for idx, m in enumerate(marks):
        start = m.end()
        end = marks[idx + 1].start() if idx + 1 < len(marks) else len(text)
        body = text[start:end]
        f = {}
        for line in body.splitlines():
            mm = re.match(r"^#?\s*([A-Z][A-Z_]{1,12})\s*[:：]\s*(.*)$", line)
            if mm:
                f[mm.group(1)] = mm.group(2).strip()
        char = [x.strip().upper() for x in re.split(r"[,，、]", f.get("CHAR", "")) if x.strip()]
        dur = 0.0
        try:
            dur = float(re.sub(r"[^0-9.]", "", f.get("DUR", "") or "0") or 0)
        except ValueError:
            dur = 0.0
        shots.append({
            "id": "SC-%s" % m.group(1),
            "char": char,
            "duration": dur,
            "dialog": "" if _is_empty_marker(f.get("DIALOG", "")) else f.get("DIALOG", "").strip(),
            "vo": "" if _is_empty_marker(f.get("VO", "")) else f.get("VO", "").strip(),
            "action": f.get("ACTION", "").strip(),
        })
    return {"header": {"codes": codes}, "shots": shots}


def _len_rule(sentence: str) -> tuple:
    """→ (是否合规, 实际长度, 上限, 口径)。CJK 按字数，纯拉丁按字符。"""
    s = _strip_quotes(sentence)
    if _CJK_RE.search(s):
        n = len(_CJK_RE.findall(s))
        return (n <= CJK_MAX, n, CJK_MAX, "CJK 字数")
    n = len(s)
    return (n <= LATIN_MAX, n, LATIN_MAX, "拉丁字符")


def check(script: dict, narration_max: int = DEFAULT_NARRATION_PER_EP,
          lines_per_60s: float = 10.0) -> list:
    """→ [{'code','level','shot','msg'}]"""
    issues = []
    shots = script["shots"]
    if not shots:
        return [{"code": "E0", "level": "ERROR", "shot": "-", "msg": "没有解析到 [SC-nn] 镜头"}]

    total_lines = 0
    for i, s in enumerate(shots):
        sid = s["id"]
        sents = _sentences(s["dialog"])

        # E1 单镜句数
        if len(sents) > SHOT_LINES_MAX:
            issues.append({"code": "E1", "level": "ERROR", "shot": sid,
                           "msg": "单镜 %d 句台词（上限 %d）：%s"
                                  % (len(sents), SHOT_LINES_MAX, " / ".join(sents)[:60])})

        # E2 单句超长
        for sent in sents:
            ok, n, cap, unit = _len_rule(sent)
            if not ok:
                issues.append({"code": "E2", "level": "ERROR", "shot": sid,
                               "msg": "单句 %d %s（上限 %d）：%s" % (n, unit, cap, sent[:40])})

        # E3 旁白与对白同镜（R3）
        if s["vo"] and s["dialog"]:
            issues.append({"code": "E3", "level": "ERROR", "shot": sid,
                           "msg": "同镜既有旁白又有对白（规则 R3 要求先拆镜）"})

        # E5 旁白位置：只允许首镜或尾镜
        if s["vo"] and 0 < i < len(shots) - 1:
            issues.append({"code": "E5", "level": "ERROR", "shot": sid,
                           "msg": "旁白出现在第 %d 镜（只允许开场镜或结尾镜）" % (i + 1)})

        # W3 说话人必须在 CHAR 里
        m = _SPEAKER_RE.match(_strip_quotes(s["dialog"]))
        if m:
            who = m.group(1).upper()
            if s["char"] and who not in s["char"]:
                issues.append({"code": "W3", "level": "WARN", "shot": sid,
                               "msg": "说话人 %s 不在本镜 CHAR（%s）里" % (who, ", ".join(s["char"]))})

        # W2 空功能台词
        lowered = _strip_quotes(s["dialog"]).lower()
        for phrase in EMPTY_PHRASES:
            if phrase and phrase in lowered and len(lowered) <= max(12, len(phrase) + 6):
                issues.append({"code": "W2", "level": "WARN", "shot": sid,
                               "msg": "疑似空功能台词（%s），需人工确认是否可删" % phrase})
                break

        total_lines += len(sents)

    # E4 旁白条数
    vos = [s for s in shots if s["vo"]]
    if len(vos) > narration_max:
        issues.append({"code": "E4", "level": "ERROR", "shot": "-",
                       "msg": "旁白 %d 条（上限 %d）：%s"
                              % (len(vos), narration_max, "、".join(s["id"] for s in vos))})

    # E6 台词密度（按本集实际时长折算）
    total_sec = sum(s["duration"] for s in shots)
    need = max(1, int(round(lines_per_60s * (total_sec / 60.0))))
    if total_sec and total_lines < need:
        issues.append({"code": "E6", "level": "ERROR", "shot": "-",
                       "msg": "台词密度不足：%d 句 / %.0f 秒（按 %.0f 句/60s 应 ≥ %d 句）"
                              % (total_lines, total_sec, lines_per_60s, need)})

    # W1 连续 3 镜零台词（既无对白也无旁白）
    streak = 0
    for s in shots:
        if not s["dialog"] and not s["vo"]:
            streak += 1
            if streak == 3:
                issues.append({"code": "W1", "level": "WARN", "shot": s["id"],
                               "msg": "连续 3 镜没有任何台词/旁白（确认是否用画面代替了戏）"})
        else:
            streak = 0
    return issues


def _narration_max(ws: pathlib.Path) -> tuple:
    """读 narratives.json 的默认叙事模式配额；读不到用内置默认。"""
    try:
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        import style_gate as SG
        spec = SG.merge_spec("live_action")           # 配额与轨道无关，取任一轨即可
        return (int(spec.get("narration_per_ep_max") or DEFAULT_NARRATION_PER_EP),
                float(spec.get("dialogue_lines_per_60s_min") or 10.0))
    except Exception:                                            # noqa: BLE001
        return (DEFAULT_NARRATION_PER_EP, 10.0)


def find_script(ws: pathlib.Path, ep: str) -> pathlib.Path | None:
    d = ws / "03-剧本"
    if not d.is_dir():
        return None
    want = re.sub(r"[^0-9]", "", ep or "") or ""
    for p in sorted(d.glob("*.md")):
        n = p.stem.lower()
        if n.startswith(("ep_", "ep")) and re.sub(r"[^0-9]", "", n) == want:
            return p
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="台词逻辑复核（规则来自对白驱动单一真源）")
    ap.add_argument("--workspace", default=None)
    ap.add_argument("--ep", default="ep01")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    # ★ 顺序很重要：有 --workspace 就**不要** import `_ws`。
    #   它在 import 期就解析工作区，而本机常驻一条指向已删目录的 SOLODRAMA_WORKSPACE，
    #   一旦先 import，显式传入的 --workspace 还没机会生效，进程就直接 SystemExit 了。
    if a.workspace:
        ws = pathlib.Path(a.workspace).expanduser().resolve()
    else:
        try:
            sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
            import _ws as W
            ws = pathlib.Path(W.WS)
        except SystemExit:
            print("[FAIL] 需要用 --workspace 指定工作区")
            return 2

    src = find_script(ws, a.ep)
    if not src:
        print("[FAIL] 找不到剧本：%s/03-剧本/%s.md（也接受 ep_01.md / EP01.md）" % (ws, a.ep))
        return 2

    script = parse_script(src.read_text(encoding="utf-8", errors="replace"))
    nmax, lpm = _narration_max(ws)
    issues = check(script, narration_max=nmax, lines_per_60s=lpm)
    errs = [i for i in issues if i["level"] == "ERROR"]
    warns = [i for i in issues if i["level"] == "WARN"]

    if a.json:
        print(json.dumps({"ep": a.ep, "file": str(src),
                          "shots": len(script["shots"]),
                          "total_sec": sum(s["duration"] for s in script["shots"]),
                          "issues": issues}, ensure_ascii=False, indent=2))
        return 0 if not errs else 2

    print("=" * 74)
    print("台词逻辑复核 ｜ %s ｜ %d 镜 / %.0f 秒" % (a.ep, len(script["shots"]),
                                                sum(s["duration"] for s in script["shots"])))
    print("=" * 74)
    if not issues:
        print("[OK] 无硬失败、无提示")
        return 0
    for i in issues:
        print("  [%s] %s %s：%s" % ("FAIL" if i["level"] == "ERROR" else "WARN",
                                    i["code"], i["shot"], i["msg"]))
    print("-" * 74)
    print("硬失败 %d ｜ 提示 %d" % (len(errs), len(warns)))
    if errs:
        print("规则来源：3d-short-drama-studio/references/dialogue-driven-rules.md")
        print("改法优先级：删旁白 → 补对白 → 拆镜；不要靠加旁白解释画面。")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
