# -*- coding: utf-8 -*-
"""prompt_gate.py —— H3 提示词的一致性门禁（免费、离线、可复算）

为什么单独做一个门禁：EP03 有 3 个镜、EP04 有 5 个镜，提示词里`[SUBJECT]`写着
`exactly one person in the frame`，而同一条提示词的 `[ACTION]` 里明明有两个人。
出片当然会出问题，但**没有任何一步会报错** —— 生成时没人看，出片后才发现。

这类错误必须在**计费之前**挡住，且判据必须机器可判。五条检查：

  C1 人数锁      `CHAR:` 拆出的代号数 N ⇒ `[SUBJECT]` 必须写 `exactly N`
  C2 景别自洽    `[SHOT]` 里 Two/Three bodies 的 N 与 C1 一致，且不得同时出现 ONLY one body
  C3 在场一致    `[ACTION]` 提到的不同代号数 ≤ N
  C4 无中文      提示词正文不得含 CJK（H3 只认英文，中文等同噪声）
  C5 图号闭合    `<Picture n>` 的最大编号 == 实际发送的图片数

用法：
    python prompt_gate.py --workspace <ws> --ep ep03
    python prompt_gate.py --workspace <ws> --all
    python prompt_gate.py --workspace <ws> --ep ep03 --json

退出码：0 通过｜2 有硬失败｜1 输入缺失
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

CJK_RE = re.compile(r"[\u4e00-\u9fff]")
NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
             "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6}
PICTURE_RE = re.compile(r"<Picture\s*(\d+)>", re.I)


# ---------------------------------------------------------------------------
def _read_json(p: pathlib.Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception:                                          # noqa: BLE001
        return default


def split_codes(v: str) -> list:
    """与 tools/core/validate.py::_split_codes 同口径（一镜多角色）。"""
    return [x.strip() for x in re.split(r"[,，、;；/]", v or "") if x.strip()]


def parse_header_codes(text: str) -> list:
    """从分镜 md 的 `CHAR:` 行取代号列表。"""
    out = []
    for ln in (text or "").splitlines():
        if re.match(r"^\s*CHAR\s*:", ln, re.I):
            out = split_codes(ln.split(":", 1)[1])
            break
    return [_canon_code(c) for c in out if c]


def _canon_code(x: str) -> str:
    """`char_elle` / `ELLE` / `elle` → `ELLE`。"""
    s = str(x or "").strip()
    for pre in ("char_", "character_", "CH_", "ch_"):
        if s.lower().startswith(pre.lower()):
            s = s[len(pre):]
            break
    return s.upper()


def _n_from_words(v: str):
    return NUM_WORDS.get(str(v or "").strip().lower())


def check_prompt(prompt: str, char_codes: list, image_count: int | None) -> list:
    """单条提示词的检查 → [{"code","level","msg"}]。"""
    issues = []
    n_char = len(char_codes)

    subj = re.search(r"\[SUBJECT\]([\s\S]*?)(?=\n\s*\[|$)", prompt)
    shot = re.search(r"\[SHOT\]([\s\S]*?)(?=\n\s*\[|$)", prompt)
    act = re.search(r"\[ACTION\]([\s\S]*?)(?=\n\s*\[|$)", prompt)

    # ---- C1 人数锁 ----
    m = re.search(r"exactly\s+(one|two|three|four|five|six|\d)\s+(person|people|body|bodies)",
                  subj.group(1) if subj else "", re.I)
    if not m:
        issues.append({"code": "C1", "level": "ERROR",
                       "msg": "SUBJECT 未写人数锁（应写 exactly %d person/people）" % n_char})
    else:
        n_lock = _n_from_words(m.group(1))
        if n_lock != n_char:
            issues.append({"code": "C1", "level": "ERROR",
                           "msg": "SUBJECT 锁 %d 人，但 CHAR 有 %d 个代号（%s）"
                                  % (n_lock, n_char, "、".join(char_codes) or "空")})

    # ---- C2 景别自洽 ----
    shot_txt = shot.group(1) if shot else ""
    m2 = re.search(r"\b(one|two|three|four|five)\s+bodies?\b", shot_txt, re.I)
    if m2:
        n_shot = _n_from_words(m2.group(1))
        if n_shot != n_char:
            issues.append({"code": "C2", "level": "ERROR",
                           "msg": "SHOT 写 %s bodies，但 CHAR 有 %d 个代号" % (m2.group(1), n_char)})
        if n_shot > 1 and re.search(r"ONLY\s+one\s+body", shot_txt, re.I):
            issues.append({"code": "C2", "level": "ERROR",
                           "msg": "SHOT 自相矛盾：同一句里既写 %s bodies 又写 ONLY one body"
                                  % m2.group(1)})
    elif n_char > 0 and re.search(r"ONLY\s+one\s+body", shot_txt, re.I) and n_char > 1:
        issues.append({"code": "C2", "level": "ERROR",
                       "msg": "SHOT 写 ONLY one body，但 CHAR 有 %d 个代号" % n_char})

    # ---- C3 在场一致 ----
    act_txt = act.group(1) if act else ""
    seen = {c for c in char_codes if re.search(r"\b%s\b" % re.escape(c), act_txt, re.I)}
    if n_char and len(seen) > n_char:
        issues.append({"code": "C3", "level": "ERROR",
                       "msg": "ACTION 出现 %d 个代号，超过 CHAR 的 %d 个" % (len(seen), n_char)})
    # 反向：ACTION 里出现了 HEADER 没登记的代号（大写英文名）
    capped = set(re.findall(r"\b[A-Z][A-Z]{2,}\b", act_txt))
    unknown = {c for c in capped if c not in {x.upper() for x in char_codes}}
    if unknown and char_codes:
        # 只提示，不判死：可能是 SFX/道具缩写
        issues.append({"code": "C3", "level": "WARN",
                       "msg": "ACTION 里出现未登记的代号：%s" % "、".join(sorted(unknown))})

    # ---- C4 无中文 ----
    body = re.sub(r"^\s*\[STYLE\][\s\S]*?(?=\n\s*\[|$)", "", prompt, flags=re.M)
    if CJK_RE.search(body):
        hit = CJK_RE.search(body)
        s = max(0, hit.start() - 20)
        issues.append({"code": "C4", "level": "ERROR",
                       "msg": "提示词含中文字符：…%s…" % body[s:hit.start() + 20].replace("\n", " ")})

    # ---- C5 图号闭合 ----
    # 2026-11-01 收紧：原来是「最大编号 > 图片数」才报错，于是「少发一张」永远查不出来
    # （编号 1..3、实际只发 2 张 → 通过）。现在要求**严格相等**：
    # `<Picture n>` 必须刚好覆盖「分镜图 1 + 角色 + 场景」的每一张。
    nums = [int(x) for x in PICTURE_RE.findall(prompt)]
    if nums:
        mx = max(nums)
        if image_count is not None and mx != image_count:
            issues.append({"code": "C5", "level": "ERROR",
                           "msg": "<Picture %d> 与实际发送的图片数 %d 不符"
                                  "（分镜图 1 + 角色 + 场景）" % (mx, image_count)})
        if sorted(set(nums)) != list(range(1, mx + 1)):
            issues.append({"code": "C5", "level": "WARN",
                           "msg": "<Picture n> 编号不连续：%s" % sorted(set(nums))})
    elif image_count:
        issues.append({"code": "C5", "level": "ERROR",
                       "msg": "发送了 %d 张参考图，但提示词里没有任何 <Picture n>" % image_count})
    return issues


# ---------------------------------------------------------------------------
def parse_storyboard_md(text: str) -> dict:
    """分镜 md → {shot_id: {"codes": [...], "refs": [...], "prompt": "..."}}。

    ★ 为什么以 md 为准：`shots.json` 是**转换产物**且 data_dir 是固定目录
      （V0.7.x 已知缺陷：多集会互相覆盖）。拿它判所有集，会把 ep01 的角色配到 ep04 上。
      分镜 md 是每集一份、且 `- refs:` 就是这一镜真正要用的参考图 —— 唯一不会串的来源。
    """
    out = {}
    for block in re.split(r"(?m)^##\s+", text or "")[1:]:
        lines = block.split("\n")
        sid = lines[0].strip().split()[0] if lines else ""
        if not sid:
            continue
        body = "\n".join(lines[1:])
        m = re.search(r"(?m)^-\s*refs:\s*(.+)$", body)
        refs = split_codes(m.group(1)) if m else []
        codes = [_canon_code(c) for c in refs
                 if c.lower().startswith(("char_", "character_", "ch_"))]
        # prompt 是 `- prompt: |` 之后的缩进块
        pm = re.search(r"(?ms)^-\s*prompt:\s*\|\s*\n(.*?)(?=\n-\s|\n---|\Z)", body)
        prompt = pm.group(1) if pm else ""
        prompt = "\n".join(ln[4:] if ln.startswith("    ") else ln.strip()
                           for ln in prompt.split("\n"))
        # board 同理（`- board: |` 之后的缩进块）。有它，图片数要多算 1 张：它占 <Picture 1>。
        bm = re.search(r"(?ms)^-\s*board:\s*\|\s*\n(.*?)(?=\n-\s|\n---|\Z)", body)
        board = "\n".join(ln[4:] if ln.startswith("    ") else ln.strip()
                          for ln in (bm.group(1) if bm else "").split("\n")).strip()
        out[sid] = {"codes": codes, "refs": refs, "prompt": prompt.strip(), "board": board}
    return out


def run_ep(ws: pathlib.Path, ep: str) -> dict:
    """检查一集 → {"ep","shots","issues"}。角色与参考图取自分镜 md，提示词取 _eps 快照。"""
    md = ws / "05-分镜" / ("%s_storyboard.md" % ep)
    if not md.is_file():
        return {"ep": ep, "error": "找不到分镜 md：%s" % md, "shots": []}
    shots_md = parse_storyboard_md(md.read_text(encoding="utf-8"))

    # 提示词：优先**真正会发出去的那份** —— 先看 data/<ep>/（convert_storyboard 的落点，
    # 已含 <Picture n> 重排），再看历史 `_eps/<ep>/` 快照。
    # 顺序不能反：_eps 是旧路径，里面的编号还是「角色从 1 开始」的旧编号，
    # 拿它来判会报一堆假 C5。
    data = ws / "06-提示词"
    prompts, src = None, ""
    for cand in (data / ep / "h3_prompts.json", data / "_eps" / ep / "h3_prompts.json"):
        if cand.is_file():
            prompts = _read_json(cand, {}) or {}
            src = str(cand)
            break
    if prompts is None:
        prompts = {sid: {"prompt": v["prompt"]} for sid, v in shots_md.items()}
        src = "%s（md 内联，无 data/<ep> 快照）" % md.name

    out = []
    for sid, meta in shots_md.items():
        item = prompts.get(sid)
        if isinstance(item, dict):
            prompt = item.get("prompt") or ""
        elif isinstance(item, str):
            prompt = item
        else:
            prompt = meta["prompt"]
        # 图片数 = 分镜图 1 张 + refs 里的角色与场景。分镜图进了槽位就必须算进来，
        # 否则 C5 会拿「不含分镜图」的数字去对「已含分镜图」的编号，永远差一位。
        n_img = len(meta["refs"]) + (1 if meta.get("board") else 0)
        if not prompt:
            out.append({"shot": sid, "codes": meta["codes"], "images": n_img,
                        "issues": [{"code": "C0", "level": "ERROR", "msg": "该镜没有提示词正文"}]})
            continue
        _iss = check_prompt(prompt, meta["codes"], n_img or None)
        if not meta.get("board"):
            # 缺分镜图不拦（老项目还能跑），但必须说出来 ——
            # 否则又是「以为用了构图锚，其实一直在两参出片」。
            _iss.append({"code": "C6", "level": "WARN",
                         "msg": "缺 board（分镜图）字段：出片退化为「角色+场景」两参"})
        out.append({"shot": sid, "codes": meta["codes"], "images": n_img, "issues": _iss})
    return {"ep": ep, "source": src, "shots": out}


def main() -> int:
    ap = argparse.ArgumentParser(description="H3 提示词一致性门禁")
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--ep", default="", help="集号，如 ep03")
    ap.add_argument("--all", action="store_true", help="检查 06-提示词/_eps 下全部集")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    ws = pathlib.Path(a.workspace).expanduser().resolve()
    if not ws.is_dir():
        print("[FAIL] 工作区不存在：%s" % ws)
        return 1

    eps = []
    if a.all:
        root = ws / "06-提示词" / "_eps"
        eps = sorted(p.name for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
    elif a.ep:
        eps = [a.ep]
    else:
        print("[FAIL] 需要 --ep <epNN> 或 --all")
        return 1
    if not eps:
        print("[FAIL] 没有可检查的集（%s）" % (ws / "06-提示词" / "_eps"))
        return 1

    reports = [run_ep(ws, e) for e in eps]
    hard = 0
    for r in reports:
        if r.get("error"):
            print("[FAIL] %s：%s" % (r["ep"], r["error"]))
            return 1
        bad = [s for s in r["shots"] if any(i["level"] == "ERROR" for i in s["issues"])]
        hard += len(bad)
        if not a.json:
            print("=" * 74)
            print("%s ｜ %d 镜 ｜ 失败 %d 镜 ｜ %s" % (r["ep"], len(r["shots"]), len(bad), r["source"]))
            print("=" * 74)
            for s in r["shots"]:
                errs = [i for i in s["issues"] if i["level"] == "ERROR"]
                warns = [i for i in s["issues"] if i["level"] == "WARN"]
                if not errs and not warns:
                    continue
                print("  [%s] %s（CHAR %d 人 / 参考图 %s 张）"
                      % ("FAIL" if errs else "WARN", s["shot"], len(s["codes"]),
                         s["images"] if s["images"] is not None else "?"))
                for i in errs + warns:
                    print("     %s %s：%s" % (i["code"], i["level"], i["msg"]))

    if a.json:
        print(json.dumps({"reports": reports, "fail_shots": hard}, ensure_ascii=False, indent=2))
    else:
        print()
        print("合计：%d 集 / 失败 %d 镜" % (len(reports), hard))
        print("通过" if hard == 0 else "★ 有硬失败，必须先修提示词再出片（否则白花钱）")
    return 0 if hard == 0 else 2


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                          # noqa: BLE001
        pass
    raise SystemExit(main())
