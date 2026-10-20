#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""script_continuity.py —— 剧本 ↔ 分镜 ↔ H3 提示词 连续性门禁

为什么有它（2026-10-20）
------------------------
「剧本是唯一事实源」此前只写在各技能提示词里，**没有任何机器校验**：
`convert_storyboard.py` 只吃分镜 md，`ingest_check.py` 只查 `data/` 内部一致性，
两者都不读 `03-剧本/ep_XX.md`。实测风险：换会话、换模型、换人之后，分镜可以悄悄
改台词、丢镜、加人物，全链路零报警 —— 剧本一个内容、提示词另一个内容。

本脚本把「同一条内容往下流」变成可判定的六项检查。

输入（自动探测，哪种存在用哪种，**不猜不编**）
----------------------------------------------
剧本   `<03-剧本>/ep_XX.md`（FFS 八字段，唯一事实源）
产物   ① `<06-提示词>/epNN_scMM_prompt.txt`（当前真实形态：subject_definitions + summary 六段）
       ② `<06-提示词>/data/h3_prompts.json` + `shots.json`（脚本链形态）
       ③ `<05-分镜>/epNN.md`（`## shot_001` + `- duration:` + `- refs:`）

校验（每项都能指到具体镜号）
----------------------------
1 **镜头数**     剧本 `[SC-n]` 数 vs 产物镜数：少 = 丢镜（FAIL）；多 = 拆镜（>2× 判碎片化）
2 **台词逐字**   剧本 DIALOG/VO 每句须在对应镜产物中出现（前 24 字匹配，容忍标点差异）
3 **人物**       剧本 CHAR 代号须能在对应镜产物里找到；产物多出的人物告警（越权新增）
4 **时长**       剧本 DUR 合计 vs 产物 duration 合计（±10%，超出 FAIL）
5 **首尾承接**   首镜须落 `cold_open`、末镜须落 `hook`（与 blueprint 比实体共享）
6 **中段节点**   `core_conflict` / `reversal` 是否被至少一镜承接（WARN，允许压缩）

退出码：0 通过｜2 有硬失败｜4 找不到剧本或产物（不静默通过）
用法
----
    python script_continuity.py --workspace "D:/剧/新剧" --ep 01
    python script_continuity.py --workspace "D:/剧/新剧" --all
    python script_continuity.py --workspace "D:/剧/新剧" --ep 01 --json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import unicodedata

_HERE = pathlib.Path(__file__).resolve()
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE.parents[2]))
try:
    import _layout as L  # noqa: E402
except Exception:        # noqa: BLE001
    L = None

DUR_TOL = 0.10           # 时长偏差上限（剧本 DUR 合计 vs 产物 duration 合计）
SPLIT_MAX = 2.0          # 拆镜上限：产物镜数 ≤ 剧本镜数 × 2
TXT_HEAD = 24            # 台词指纹长度（字符）
_STOP = {"她的", "他的", "我的", "你的", "一个", "什么", "就是", "不是", "已经",
         "自己", "这个", "那个", "我们", "他们", "她们", "因为", "所以", "但是",
         "然后", "现在", "可以", "没有", "还是", "只是", "的时"}
_PUNCT = re.compile(r"[^\u4e00-\u9fa5A-Za-z0-9]+")


# ---------------------------------------------------------------------------
# 通用
# ---------------------------------------------------------------------------
def _stage(ws: pathlib.Path, key: str) -> pathlib.Path:
    if L is None:
        raise RuntimeError("stages/_layout.py 不可用，无法解析阶段目录")
    return L.stage_dir(ws, key)


def _read(p: pathlib.Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _norm(s) -> str:
    return _PUNCT.sub("", str(s or ""))


def _key(s) -> str:
    """人物名归一化：去重音（Héctor → hector）、去标点、小写。"""
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", s.casefold())


def _cn_ratio(s) -> float:
    t = re.sub(r"\s", "", str(s or ""))
    if not t:
        return 0.0
    return len(re.findall(r"[\u4e00-\u9fa5]", t)) / len(t)


def _grams(s, n: int = 2) -> set:
    t = _norm(s)
    return {t[i:i + n] for i in range(max(0, len(t) - n + 1))}


def _shared(a, b) -> int:
    return len((_grams(a) & _grams(b)) - _STOP)


def _ep_from_name(name: str):
    m = re.match(r"ep[_-]?(\d{1,3})", name, re.I)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# 剧本（FFS）
# ---------------------------------------------------------------------------
def parse_script(p: pathlib.Path) -> dict:
    """解析 FFS 正文 → {header, shots[]}。逐行解析，不依赖整段正则。"""
    text = _read(p)
    header, shots, cur = {}, [], None
    for raw in text.splitlines():
        ln = raw.rstrip()
        if ln.startswith("# ") and ":" in ln and cur is None:
            k, _, v = ln[2:].partition(":")
            header[k.strip().upper()] = v.strip()
            continue
        m = re.match(r"^\s*\[SC-(\d+)\]\s*$", ln)
        if m:
            cur = {"no": int(m.group(1)), "DUR": "", "CHAR": "", "DIALOG": "",
                   "VO": "", "ACTION": "", "SHOT": "", "LOCATION": ""}
            shots.append(cur)
            continue
        if cur is None or ":" not in ln:
            continue
        k, _, v = ln.partition(":")
        k = k.strip().upper()
        if k in cur:
            cur[k] = v.strip()

    for s in shots:
        s["dur"] = _num(s.get("DUR")) or 8.0
        s["chars"] = [c.strip() for c in re.split(r"[,，/、]", s.get("CHAR") or "") if c.strip()]
        s["lines"] = []
        dl = (s.get("DIALOG") or "").replace('\\"', '"').replace("\\'", "'")
        if dl and not dl.startswith("无"):
            quoted = re.findall(r"[“\"'「]([^”\"'」]+)[”\"'」]", dl)
            s["lines"] += [q.strip() for q in quoted
                           if len(re.sub(r"[^\w\u4e00-\u9fa5]", "", q)) >= 2]
        vo = (s.get("VO") or "").replace('\\"', '"')
        if vo and not vo.startswith("无"):
            vo = re.sub(r"^(?:NARR|NARRATOR|[A-Za-z_\u4e00-\u9fa5 ]+\(V\.O\.\))\s*[:：]\s*", "", vo)
            cand = re.findall(r"[“\"'「]([^”\"'」]+)[”\"'」]", vo)
            picked = [x.strip() for x in cand
                      if len(re.sub(r"[^\w\u4e00-\u9fa5]", "", x)) >= 2] or [vo.strip()]
            s["lines"] += [x for x in picked if x]
    return {"header": header, "shots": shots, "path": str(p),
            "registered": _registered_chars(header)}


def _registered_chars(header: dict) -> set:
    """HEADER `# CHAR: CODE: 描述; CODE2: 描述` → 已登记代号的归一化集合。"""
    out = set()
    for part in str(header.get("CHAR") or "").split(";"):
        if ":" in part:
            k = _key(part.split(":")[0])
            if k:
                out.add(k)
    return out


def _num(v):
    m = re.search(r"\d+(?:\.\d+)?", str(v or ""))
    return float(m.group(0)) if m else 0.0


# ---------------------------------------------------------------------------
# 产物探测（三种形态）
# ---------------------------------------------------------------------------
def find_product(ws: pathlib.Path, ep: int) -> dict | None:
    """返回 {kind, shots[], path}；三种都没有返回 None。"""
    prompts = _stage(ws, "prompts")
    storyboard = _stage(ws, "storyboard")

    # ① 真实形态：epNN_scMM_prompt.txt（每镜一个文件）
    pat = re.compile(r"^ep0*%d[_-]sc(\d+).*\.txt$" % ep, re.I)
    files = sorted(((int(m.group(1)), f) for f in prompts.glob("ep*_sc*.txt")
                    if (m := pat.match(f.name))), key=lambda x: x[0])
    if files:
        shots = []
        for no, f in files:
            body = _read(f)
            chars, _envs = _pictures(body)
            shots.append({
                "no": no, "text": body,
                "dur": _dur_from_summary(body),
                "chars": chars,
                "src": f.name,
            })
        return {"kind": "prompt-txt", "shots": shots, "path": str(prompts),
                "count": len(shots)}

    # ② 脚本链形态：data/h3_prompts.json
    hp = prompts / "data" / "h3_prompts.json"
    if hp.is_file():
        obj = json.loads(_read(hp) or "{}")
        sp = prompts / "data" / "shots.json"
        refs = {}
        if sp.is_file():
            for row in (json.loads(_read(sp) or "[]") or []):
                refs[str(row.get("shot_id"))] = (row.get("character_refs") or [])
        shots = []
        for i, (sid, v) in enumerate(sorted(obj.items(), key=lambda kv: _num(kv[0])), 1):
            shot = v if isinstance(v, dict) else {}
            shots.append({
                "no": int(_num(shot.get("shot_id") or sid) or i),
                "text": str(shot.get("prompt") or ""),
                "dur": float(shot.get("duration") or 0) or 8.0,
                "chars": refs.get(str(sid)) or [],
                "src": sid,
            })
        return {"kind": "data-h3", "shots": shots, "path": str(hp), "count": len(shots)}

    # ③ 分镜 md：epNN.md / ep0N.md（## shot_001）
    for cand in (storyboard / ("ep%02d.md" % ep), storyboard / ("ep%d.md" % ep)):
        if cand.is_file():
            shots = []
            for blk in re.split(r"(?m)^##\s+", _read(cand))[1:]:
                m = re.match(r"shot[_-]?(\d+)", blk, re.I)
                if not m:
                    continue
                dur = re.search(r"(?m)^\s*[-*]?\s*duration\s*[:：]\s*(\d+(?:\.\d+)?)", blk)
                rl = re.search(r"(?m)^\s*[-*]?\s*refs\s*[:：]\s*(.+)$", blk)
                shots.append({
                    "no": int(m.group(1)), "text": blk,
                    "dur": float(dur.group(1)) if dur else 8.0,
                    "chars": [c.strip() for c in re.split(r"[,，]", rl.group(1))] if rl else [],
                    "src": "shot_%s" % m.group(1),
                })
            if shots:
                return {"kind": "storyboard-md", "shots": shots, "path": str(cand),
                        "count": len(shots)}
    return None


def _dur_from_summary(body: str) -> float:
    """真实形态的时长藏在 summary 的「A single 7-second … shot」里。"""
    for pat in (r"A single\s+(\d+(?:\.\d+)?)[- ]second", r"(\d+(?:\.\d+)?)[- ]second\s+shot",
                r"总时长\s*[:：]?\s*(\d+(?:\.\d+)?)\s*s", r"(\d+(?:\.\d+)?)\s*秒",
                r"duration\s*[:：]\s*(\d+(?:\.\d+)?)"):
        m = re.search(pat, body, re.I)
        if m:
            return float(m.group(1))
    return 0.0


def _pictures(body: str) -> tuple:
    """`Picture N = <名>, … (Character|Environment|Continuity)` → (人物名[], 场景名[])。

    场景与「上一镜末帧」都不是人物：混在一起会把「公寓走廊」「last frame …」误判成人。
    """
    chars, envs = [], []
    for m in re.finditer(r"(?m)^Picture\s+\d+\s*=\s*(.+)$", body):
        line = m.group(1)
        if re.search(r"\(\s*(?:Environment|Continuity)\s*\)", line, re.I):
            envs.append(line.split(",")[0].split("(")[0].strip())
            continue
        name = line.split(",")[0].split("(")[0].strip()
        if name:
            chars.append(name)
    return chars, envs


# blueprint 里由 `plan` 句库生成的「元指令」不是内容，无法用于承接比对
_META = ("黄金 3 秒", "禁止背景铺垫", "禁止慢热", "必须前置", "（禁止", "句库")


def _is_meta(text: str) -> bool:
    return any(m in str(text or "") for m in _META)


def _lang_mismatch(node_text: str, prod_cn: float) -> bool:
    """节点文本与产物语种是否明显不同（中文节点 vs 外语产物，或反之）。

    阈值取「一侧明确中文、另一侧几乎没有中文」，避免把中英混排的产物误判成跨语种。
    """
    n = _cn_ratio(node_text)
    return (n > 0.5 and prod_cn < 0.15) or (n < 0.15 and prod_cn > 0.5)


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------
def check_episode(ws: pathlib.Path, ep: int) -> dict:
    script_p = _stage(ws, "script") / ("ep_%02d.md" % ep)
    if not script_p.is_file():
        return {"ep": ep, "status": "no-script", "fail": [], "warn": [],
                "detail": "找不到剧本：%s" % script_p}
    sc = parse_script(script_p)
    shots = sc["shots"]
    if not shots:
        return {"ep": ep, "status": "no-script", "fail": [], "warn": [],
                "detail": "剧本里没有 [SC-nn] 镜头块：%s" % script_p}

    prod = find_product(ws, ep)
    if not prod:
        return {"ep": ep, "status": "no-product", "fail": [], "warn": [],
                "detail": "找不到分镜或提示词产物（05-分镜 / 06-提示词）", "script_shots": len(shots)}

    fail, warn = [], []
    by_no = {s["no"]: s for s in prod["shots"]}

    # 1 镜头数
    n_s, n_p = len(shots), len(prod["shots"])
    lost = [s["no"] for s in shots if s["no"] not in by_no]
    if lost:
        fail.append("丢镜 %d 个：剧本 SC-%s 在产物里没有对应镜"
                    % (len(lost), "、SC-".join("%02d" % x for x in lost[:8])))
    elif n_p > n_s * SPLIT_MAX:
        fail.append("产物镜数 %d > 剧本 %d × %.0f —— 拆镜过度，一条内容被切碎" % (n_p, n_s, SPLIT_MAX))
    elif n_p > n_s:
        warn.append("产物多出 %d 镜（拆镜）—— 确认是导演切分而非新增剧情" % (n_p - n_s))

    # 2 台词逐字
    total_lines = hit_lines = 0
    missing = []
    for s in shots:
        p = by_no.get(s["no"])
        if not p:
            continue
        for ln in s["lines"]:
            total_lines += 1
            if _norm(ln)[:TXT_HEAD] and _norm(ln)[:TXT_HEAD] in _norm(p["text"]):
                hit_lines += 1
            else:
                missing.append((s["no"], ln[:26]))
    cross_lang = False
    if total_lines and hit_lines / total_lines < 0.2:
        cross_lang = True
        warn.append("台词命中率仅 %d/%d —— 疑似剧本与产物不同语种，本项需人工核对（不作 FAIL）"
                    % (hit_lines, total_lines))
    elif missing:
        fail.append("台词/旁白未逐字落到产物（%d 句）：%s"
                    % (len(missing), "；".join("SC-%02d「%s」" % m for m in missing[:4])))

    # 3 人物（分三层：未登记代号 → 跳过；偶发漏引 → WARN；重要角色整集零引用 → FAIL）
    registered = sc.get("registered") or set()
    unregistered, missing_pairs, extra_chars = set(), [], []
    total_by_char, used_by_char, code_of = {}, {}, {}
    for s in shots:
        for c in s["chars"]:
            k = _key(c)
            if not k:
                continue
            if registered and k not in registered:
                unregistered.add(c)
                continue
            total_by_char[k] = total_by_char.get(k, 0) + 1
            code_of.setdefault(k, c)
    for s in shots:
        p = by_no.get(s["no"])
        if not p:
            continue
        hay = _key(" ".join(p["chars"]))
        for c in s["chars"]:
            k = _key(c)
            if not k:
                continue
            if registered and k not in registered:
                unregistered.add(c)
                continue
            if k in hay:
                used_by_char[k] = used_by_char.get(k, 0) + 1
            else:
                missing_pairs.append("SC-%02d `%s`" % (s["no"], c))
        if s["chars"] and s["chars"] != ["无"]:
            want = {_key(c) for c in s["chars"]}
            for name in p["chars"]:
                k = _key(str(name).split()[0]) if str(name).split() else ""
                if k and k not in want:
                    extra_chars.append("SC-%02d `%s`" % (s["no"], str(name)[:18]))

    # 主角零参考 = 真事故（必漂）；配角零参考可能是有意的槽位取舍
    if total_by_char:
        lead_k = max(total_by_char, key=lambda k: total_by_char[k])
        if total_by_char[lead_k] >= 3 and used_by_char.get(lead_k, 0) == 0:
            fail.append("主角 %s 本集 %d 镜在场，产物一次都没引用参考图 —— 必漂"
                        % (code_of.get(lead_k, lead_k), total_by_char[lead_k]))
    dead = []
    for k, n in total_by_char.items():
        if n >= 3 and used_by_char.get(k, 0) == 0:
            dead.append("%s（%d 镜）" % (code_of.get(k, k), n))
    if dead:
        warn.append("配角整集没有参考图（槽位上限 6 时可接受，确认是否为一次性路人）：%s"
                    % "、".join(dead[:4]))
    if missing_pairs:
        warn.append("个别镜未引用参考图（%d 处，槽位上限 6 时可接受）：%s"
                    % (len(missing_pairs), "、".join(missing_pairs[:5])))
    if unregistered:
        warn.append("剧本用了未在 HEADER `# CHAR:` 登记的代号（FFS 违规，下游无法映射）：%s"
                    % "、".join(sorted(unregistered)[:5]))
    if extra_chars:
        warn.append("产物出现剧本外的人物（越权新增）：%s" % "、".join(extra_chars[:4]))

    # 4 时长
    dur_s = sum(s["dur"] for s in shots)
    dur_p = sum(p["dur"] for p in prod["shots"] if p["dur"])
    if dur_p:
        dev = abs(dur_p - dur_s) / max(dur_s, 1e-6)
        if dev > DUR_TOL:
            fail.append("总时长偏差 %.0f%%（剧本 %.0fs / 产物 %.0fs）—— 时长变了，节奏就变了"
                        % (dev * 100, dur_s, dur_p))
        elif dev > DUR_TOL / 2:
            warn.append("总时长偏差 %.0f%%（剧本 %.0fs / 产物 %.0fs）" % (dev * 100, dur_s, dur_p))
    else:
        warn.append("产物没有可解析的 duration，时长未校验")

    # 5/6 剧情节点承接（读 blueprint 的 plot_points）
    bp_p = _stage(ws, "script") / "blueprint.json"
    bp = {}
    try:
        bp = json.loads(_read(bp_p) or "{}")
    except json.JSONDecodeError:
        bp = {}
    row = next((e for e in (bp.get("episodes") or []) if int(e.get("ep") or 0) == ep), None)
    pts = (row or {}).get("plot_points") or []
    if not pts and row:
        pts = [{"id": "EP%02d-P%d" % (ep, j), "role": r, "text": str(row.get(k) or "")}
               for j, (r, k) in enumerate((("cold_open", "cold_open"),
                                           ("core_conflict", "core_conflict"),
                                           ("reversal", "reversal"),
                                           ("hook", "hook")), 1)]
    if pts:
        first = prod["shots"][0]
        last = prod["shots"][-1]
        gold = {p.get("role"): p for p in pts}
        # 语种判定看「产物文本」而非剧本 ACTION：ACTION 可能中文、旁白外语，混合时会误判
        prod_cn = _cn_ratio(" ".join(str(p.get("text") or "") for p in prod["shots"]))
        checked = 0
        for role, shot, where in (("cold_open", first, "首镜"), ("hook", last, "末镜")):
            node = gold.get(role) or {}
            txt = str(node.get("text") or "")
            if not txt:
                continue
            if _is_meta(txt):
                warn.append("blueprint 的 %s（%s）还是句库元指令，无法校验%s承接 —— "
                            "回 plan 用 --from-outline 覆盖后再跑" % (role, node.get("id"), where))
                continue
            if _lang_mismatch(txt, prod_cn):
                warn.append("blueprint 的 %s（%s）是中文、剧本正文是外语 —— 跨语种无法逐字比对承接，"
                            "请人工确认%s内容一致" % (role, node.get("id"), where))
                continue
            checked += 1
            if _shared(txt, shot["text"]) < 1:
                fail.append("%s没有承接剧本的 %s（%s）—— 开场/集尾是留存命门，不能换内容"
                            % (where, role, node.get("id")))
        for role in ("core_conflict", "reversal"):
            node = gold.get(role) or {}
            txt = str(node.get("text") or "")
            if not txt or _is_meta(txt) or _lang_mismatch(txt, prod_cn):
                continue
            checked += 1
            if not any(_shared(txt, p["text"]) >= 1 for p in prod["shots"]):
                warn.append("剧本的 %s（%s）在产物里没有明显落点，确认是否被压缩掉"
                            % (role, node.get("id")))
        if checked == 0:
            warn.append("本集四个剧情节点的承接整项未校验（句库元指令或跨语种）")
    else:
        warn.append("blueprint.json 里没有本集 plot_points，剧情节点未校验")

    return {"ep": ep, "status": "ok" if not fail else "bad", "fail": fail, "warn": warn,
            "script_shots": n_s, "product_shots": n_p, "kind": prod["kind"],
            "lines": "%d/%d" % (hit_lines, total_lines), "cross_lang": cross_lang,
            "dur": "%.0f/%.0f" % (dur_s, dur_p), "path": prod["path"]}


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------
def render_md(rows: list, ws: pathlib.Path) -> str:
    bad = [r for r in rows if r["status"] == "bad"]
    L_out = ["# 剧本 ↔ 分镜 ↔ 提示词 连续性报告", "",
             "- 工作区：`%s`" % ws, "- 生成：见文件时间", "",
             "| 集 | 结果 | 产物形态 | 镜数(剧本/产物) | 台词命中 | 时长(剧本/产物) |",
             "|---|---|---|---|---|---|"]
    for r in rows:
        L_out.append("| EP%02d | %s | %s | %s | %s | %s |"
                     % (r["ep"], {"ok": "通过", "bad": "**未过**",
                                  "no-script": "无剧本", "no-product": "无产物"}[r["status"]],
                        r.get("kind", "-"),
                        "%s/%s" % (r.get("script_shots", "-"), r.get("product_shots", "-")),
                        r.get("lines", "-"), r.get("dur", "-")))
    L_out += ["", "## 明细", ""]
    for r in rows:
        if r["status"] in ("ok",) and not r["warn"]:
            continue
        L_out += ["### EP%02d" % r["ep"], ""]
        if r.get("detail"):
            L_out.append("- %s" % r["detail"])
        for f in r["fail"]:
            L_out.append("- **[FAIL]** %s" % f)
        for w in r["warn"]:
            L_out.append("- [WARN] %s" % w)
        L_out.append("")
    L_out += ["## 判定口径", "",
              "剧本是**唯一事实源**：分镜与 H3 提示词只做编排层增强，不改剧情、不改对白、"
              "不换人物、不丢开场与集尾。要改内容，回 `03-剧本/ep_XX.md` 改，再重跑本门禁。", ""]
    return "\n".join(L_out)


def main() -> int:
    ap = argparse.ArgumentParser(description="剧本 ↔ 分镜 ↔ H3 提示词 连续性门禁")
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--ep", type=int, default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    ws = pathlib.Path(a.workspace).expanduser().resolve()
    if not ws.is_dir():
        print("[FAIL] 工作区不存在：%s" % ws)
        return 4

    if a.all:
        eps = sorted(int(m.group(1)) for p in (_stage(ws, "script")).glob("ep_*.md")
                     if (m := re.match(r"ep_(\d+)\.md$", p.name)))
    elif a.ep:
        eps = [a.ep]
    else:
        print("[FAIL] 请指定 --ep N 或 --all")
        return 4
    if not eps:
        print("[FAIL] 03-剧本 下没有 ep_XX.md")
        return 4

    rows = [check_episode(ws, e) for e in eps]
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        print("=" * 74)
        print("剧本 ↔ 分镜 ↔ 提示词 连续性门禁（%d 集）" % len(rows))
        print("=" * 74)
        for r in rows:
            tag = {"ok": "[OK  ]", "bad": "[FAIL]", "no-script": "[SKIP]",
                   "no-product": "[SKIP]"}[r["status"]]
            head = "EP%02d %s %s｜镜 %s/%s｜台词 %s｜时长 %s" % (
                r["ep"], tag, r.get("kind", "-"),
                r.get("script_shots", "-"), r.get("product_shots", "-"),
                r.get("lines", "-"), r.get("dur", "-"))
            print(head)
            if r.get("detail"):
                print("        %s" % r["detail"])
            for f in r["fail"]:
                print("        [FAIL] %s" % f)
            for w in r["warn"]:
                print("        [WARN] %s" % w)
        print("-" * 74)

    bad = [r for r in rows if r["status"] == "bad"]
    skip = [r for r in rows if r["status"] in ("no-script", "no-product")]
    if not a.json:
        out = _stage(ws, "script") / "连续性报告.md"
        out.write_text(render_md(rows, ws), encoding="utf-8", newline="")
        print("报告：%s" % out)

    if bad:
        if not a.json:
            print("[NG] %d 集割裂（剧本与下游不是同一条内容）。改剧本或改产物，二选一，不要两边各写一套。"
                  % len(bad))
        return 2
    if skip and len(skip) == len(rows):
        if not a.json:
            print("[FAIL] 全部集次都缺剧本或缺产物 —— 门禁不空转通过")
        return 4
    if not a.json:
        print("[OK] 连续性通过%s。可进入 convert_storyboard / ingest_check。"
              % ("（%d 集跳过）" % len(skip) if skip else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
