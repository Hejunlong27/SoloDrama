"""校验层：G1 格式门，E001-E011 全自动。

设计原则：脚本只查「可穷举的形式错误」。
语义漂移（比如这集角色换了红衣）查不出来，靠锚点冻结 + 分镜阶段注入锚定行来防。
"""

from __future__ import annotations

import re

from .schema import (ABSTRACT_WORDS, CODE_TOKEN_WHITELIST, HEADER_FIELDS,
                     LEVEL_ERROR, LEVEL_WARN, MAX_SHOT_SEC, MIN_SHOT_SEC,
                     ALL_SHOT_FIELDS, Issue, ep_bounds, sha1)

FIELD_LINE_RE = re.compile(r"^([A-Z]+)\s*:", re.M)
# ★ 2026-10-20（反馈 P2-4）：字段行的**唯一**写法 —— 允许行首缩进、允许中英文冒号。
#   以前各处各写一套（`^DUR:` 在带缩进的文件上匹配 0 条），排查成本极高。
#   需要解析 DUR/SHOT 等字段时，一律用这个常量，不要再手写正则。
FIELD_LINE_LOOSE_RE = re.compile(r"^\s*([A-Z]+)\s*[:：]\s*(.*)$")
# 镜头块内「长得像字段、但其实不是合法字段」的行（反馈 P2-5）。
# 例：`镜头说明：xxx`、`MOOD: 紧张`、`CAMERA: 低角度` —— 这些字段引擎不认，
# 写进块里会被当成上一字段的续行，静默污染 ACTION/DIALOG。
STRAY_FIELD_RE = re.compile(r"^([^\s:：][^:：]{0,12})\s*[:：]\s*\S")
SC_LINE_RE = re.compile(r"^\s*SC[-_ ]?\d+", re.I)
CODE_TOKEN_RE = re.compile(r"\b([A-Z][A-Z0-9_]{2,})\b")
QUOTED_RE = re.compile(r"[“\"]([^”\"]+)[”\"]")
SENT_SPLIT_RE = re.compile(r"[。！？!?…；;]+|\.(?=\s|$)")

# ★ 2026-10-21（反馈 2.1 / 4.y）：断句符此前只有中文标点，于是西语 `Es prueba. Está firmada.`
#   被当成**一整句 24 字**判超限。西语/英语的 `.` 必须参与断句。
#   用「点后跟空白或行尾」判定，避免把小数（3.5）与版本号切开。
# ★ 2026-10-21（反馈 2.2）：20 字上限对拉丁语系过严（20 字符西语 ≈ 3–4 个词，
#   等于把台词压到主谓宾都不全）。按内容分档：含中日韩字符 → 20；拉丁/西里尔 → 55 字符。
CJK_SENT_MAX = 20
LATIN_SENT_MAX = 55
DUR_TOLERANCE_SEC = 2      # 总时长边界容差（反馈 4.x：设定 60 秒，成片 59 秒就判死太硬）


def _sent_limit(text: str) -> tuple:
    """→ (上限, 单位说明)。按字符集分档，不按项目语种猜（混排剧本也稳）。"""
    if any("\u4e00" <= ch <= "\u9fff" for ch in text):
        return CJK_SENT_MAX, "字"
    return LATIN_SENT_MAX, "字符"


# ---------------------------------------------------------------- 剧本校验

def validate_script(conn, project: str, ep, raw_md: str) -> list:
    issues: list = []
    known_chars = {r["code"] for r in conn.execute(
        "SELECT code FROM characters WHERE project=?", (project,))}
    known_scenes = {r["code"] for r in conn.execute(
        "SELECT code FROM scenes WHERE project=?", (project,))}
    # 中文剧本的 ACTION 里写的是角色中文名，不是大写代号，一并纳入可识别集合
    known_names = {r["name"] for r in conn.execute(
        "SELECT name FROM characters WHERE project=?", (project,)) if r["name"]}
    recognizable = (known_chars | known_scenes | known_names) - {""}

    issues += _check_header(ep)
    issues += _check_char_anchor(conn, project, ep)
    issues += _check_codes(ep, known_chars, known_scenes)
    issues += _check_custom_fields(raw_md)
    issues += _check_stray_field_lines(raw_md)
    issues += _check_sc_seq(ep)
    issues += _check_duration(ep, _proj_bounds(conn, project))
    issues += _check_dialog(ep)
    issues += _check_vo(ep)
    issues += _check_action(ep, recognizable)
    return issues


def _check_header(ep) -> list:
    out = []
    order = ep.header.get("_order", [])
    present = [f for f in order if f in HEADER_FIELDS]
    for f in HEADER_FIELDS:
        if f not in ep.header:
            out.append(Issue("E001", LEVEL_ERROR, "HEADER", f"缺 HEADER 字段：{f}"))
    if present != list(HEADER_FIELDS) and len(present) == len(HEADER_FIELDS):
        out.append(Issue("E001", LEVEL_ERROR, "HEADER",
                         f"HEADER 顺序错误：当前 {present}"))
    return out


def _parse_char_header(text: str) -> dict:
    """'LIN_A: 锚点; LIN_B: 锚点' -> {'LIN_A': '锚点'}"""
    out = {}
    for part in (text or "").split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _check_char_anchor(conn, project, ep) -> list:
    out = []
    declared = _parse_char_header(ep.header.get("CHAR", ""))
    for code, anchor in declared.items():
        row = conn.execute(
            "SELECT anchor_text, anchor_hash FROM characters WHERE project=? AND code=?",
            (project, code)).fetchone()
        if not row:
            continue  # E003 已报未登记
        if sha1(anchor) != row["anchor_hash"]:
            out.append(Issue("E002", LEVEL_ERROR, f"HEADER#CHAR:{code}",
                             f"锚点与库不一致\n  剧本：{anchor}\n  库内：{row['anchor_text']}"))
    # 集内出场但未在 HEADER 声明的
    for s in ep.shots:
        if s.char and s.char != "无" and s.char not in declared:
            out.append(Issue("E002", LEVEL_ERROR, s.sc_id,
                             f"角色 {s.char} 出场但 HEADER 未声明锚点"))
    return out


def _check_codes(ep, known_chars: set, known_scenes: set) -> list:
    out = []
    for s in ep.shots:
        if s.char and s.char != "无" and s.char not in known_chars:
            out.append(Issue("E003", LEVEL_ERROR, s.sc_id,
                             f"CHAR 引用未登记代号：{s.char}"))
        if s.location and s.location not in known_scenes:
            out.append(Issue("E003", LEVEL_ERROR, s.sc_id,
                             f"LOCATION 引用未登记代号：{s.location}"))
        for tok in set(CODE_TOKEN_RE.findall(s.action)):
            if tok in CODE_TOKEN_WHITELIST:
                continue
            if tok not in known_chars and tok not in known_scenes:
                out.append(Issue("E003", LEVEL_WARN, s.sc_id,
                                 f"ACTION 中的疑似未登记代号：{tok}"))
    return out


def _check_custom_fields(raw_md: str) -> list:
    out = []
    for i, line in enumerate(raw_md.splitlines(), 1):
        m = FIELD_LINE_RE.match(line.strip())
        if not m:
            continue
        if m.group(1) in ALL_SHOT_FIELDS:
            continue
        if line.strip().startswith("#"):
            continue
        out.append(Issue("E004", LEVEL_ERROR, f"L{i}",
                         f"非法字段行：{m.group(1)}:（只允许 {'/'.join(ALL_SHOT_FIELDS)}）"))
    return out


def _check_stray_field_lines(raw_md: str) -> list:
    """镜头块内「字段形状但不合法」的行 → WARN（反馈 P2-5）。

    为什么只 WARN、且要求行首不缩进：
      * 合法的字段续行通常是缩进写的（ACTION 折行），不该被打扰；
      * 写在行首的 `MOOD: 紧张` / `镜头说明：xxx` 才是真正的误写 ——
        它们会被解析器当成上一字段的续行，**静默污染** ACTION/DIALOG，
        而此前 lint 完全不报（E004 只认全大写 ASCII 键名）。
    用 WARN 而不是 ERROR：中文正文里「他说：…」这类行如果写在行首也确实存在，
    需要人判断；但至少不再静默。
    """
    out = []
    in_shot = False
    for i, raw in enumerate(raw_md.splitlines(), 1):
        line = raw.rstrip()
        st = line.strip()
        if SC_LINE_RE.match(st):
            in_shot = True
            continue
        if st.startswith("#") or st.startswith("```"):
            in_shot = False if st.startswith("##") else in_shot
            continue
        if not in_shot or not st or st == "---" or st.startswith("<!--"):
            continue
        if raw[:1] in (" ", "\t"):      # 缩进 = 续行，放过
            continue
        m = STRAY_FIELD_RE.match(st)
        if not m:
            continue
        key = m.group(1).strip()
        if key.upper() in ALL_SHOT_FIELDS:
            continue
        out.append(Issue("E012", LEVEL_WARN, f"L{i}",
                         f"镜头块内的非法字段行「{key}:」可能被当作续行拼进上一字段；"
                         f"合法字段只有 {'/'.join(ALL_SHOT_FIELDS)}"))
    return out


def _check_sc_seq(ep) -> list:
    out = []
    seqs = [s.seq for s in ep.shots]
    if seqs != list(range(1, len(seqs) + 1)):
        out.append(Issue("E005", LEVEL_ERROR, "全篇",
                         f"SC 编号不连续：{seqs}"))
    return out


def _proj_bounds(conn, project: str) -> dict:
    """按项目自身的 `ep_seconds` 取时长口径（老项目 70 秒、新项目 60 秒各按各的）。"""
    sec = None
    try:
        row = conn.execute("SELECT ep_seconds FROM projects WHERE slug=?", (project,)).fetchone()
        if row is not None:
            sec = row["ep_seconds"] if hasattr(row, "keys") else row[0]
    except Exception:                                            # noqa: BLE001
        sec = None
    return ep_bounds(sec)


def _check_duration(ep, bounds: dict | None = None) -> list:
    out = []
    b = bounds or ep_bounds(None)
    lo_s, hi_s = b["shots"]
    lo_t, hi_t = b["total"]
    n = len(ep.shots)
    total = ep.total_sec
    if not (lo_s <= n <= hi_s):
        out.append(Issue("E006", LEVEL_ERROR, "全篇",
                         f"镜头数 {n} 超出 {lo_s}-{hi_s} 镜区间"))
    if not (lo_t - DUR_TOLERANCE_SEC <= total <= hi_t + DUR_TOLERANCE_SEC):
        out.append(Issue("E006", LEVEL_ERROR, "全篇",
                         f"总时长 {total} 秒超出 {lo_t - DUR_TOLERANCE_SEC}-{hi_t + DUR_TOLERANCE_SEC} 秒区间"
                         f"（含 ±{DUR_TOLERANCE_SEC}s 容差）"))
    for s in ep.shots:
        if not (MIN_SHOT_SEC <= s.est_sec <= MAX_SHOT_SEC):
            out.append(Issue("E006", LEVEL_ERROR, s.sc_id,
                             f"单镜 {s.est_sec} 秒超出 {MIN_SHOT_SEC}-{MAX_SHOT_SEC} 秒"))
    return out


def _check_dialog(ep) -> list:
    out = []
    for s in ep.shots:
        if not s.dialog or s.dialog == "无":
            continue
        quoted = QUOTED_RE.findall(s.dialog)
        body = "".join(quoted) if quoted else s.dialog.strip('“”"')
        sents = [x for x in SENT_SPLIT_RE.split(body) if x.strip()]
        if len(sents) > 2:
            out.append(Issue("E007", LEVEL_ERROR, s.sc_id,
                             f"对白 {len(sents)} 句，超过 2 句上限"))
        for x in sents:
            lim, unit = _sent_limit(x.strip())
            if len(x.strip()) > lim:
                out.append(Issue("E007", LEVEL_ERROR, s.sc_id,
                                 f"单句 {len(x.strip())} {unit}超过 {lim} {unit}：{x.strip()}"))
    return out


def _check_vo(ep) -> list:
    out = []
    for s in ep.shots:
        if not s.vo or s.vo == "无":
            continue
        if "NARRATOR:" not in s.vo and "(V.O.):" not in s.vo and "：" not in s.vo[:12]:
            out.append(Issue("E008", LEVEL_ERROR, s.sc_id,
                             f"VO 缺说话者前缀：{s.vo}"))
    return out


def _check_action(ep, known: set) -> list:
    out = []
    for s in ep.shots:
        if not s.action.strip():
            out.append(Issue("E009", LEVEL_ERROR, s.sc_id, "ACTION 为空"))
            continue
        if not any(c in s.action for c in known if c):
            out.append(Issue("E009", LEVEL_ERROR, s.sc_id,
                             "ACTION 未包含任何已登记代号（无法定位主体）。"
                             "★ 校验器只认 HEADER `# CHAR:` 里登记过的**大写代号**，"
                             "中文名（外婆/律师）不参与匹配；省略主语的句子必然不过 —— "
                             "请让 ACTION 以 ABUELA / ANA 这类代号开头；一次性群演请登记为 EXTRA"))
        for w in ABSTRACT_WORDS:
            if w in s.action:
                out.append(Issue("E009", LEVEL_ERROR, s.sc_id,
                                 f"ACTION 含抽象词「{w}」，改为具体动作/表情"))
    return out


# ------------------------------------------------------------ 分镜校验

def validate_storyboard(conn, project: str, ep, sb: dict) -> list:
    issues: list = []
    row = conn.execute("SELECT style_lock, style_lock_hash FROM projects WHERE slug=?",
                       (project,)).fetchone()
    if row:
        # 分镜的 STYLE LOCK 是展开后的中文段落，不能逐字比对；
        # 只要求它原样包含项目锁定的风格常量（防止 LLM 自由改写视觉基调）
        sl = sb.get("style_lock", "")
        fingerprint = (row["style_lock"] or "").strip()[:60]
        if fingerprint and fingerprint not in sl:
            issues.append(Issue("E011", LEVEL_ERROR, "STYLE LOCK",
                                "分镜 STYLE LOCK 未原样包含项目锁定的风格常量"))
    script_dialogs = []
    for s in ep.shots:
        if s.dialog and s.dialog != "无":
            script_dialogs += QUOTED_RE.findall(s.dialog)
    sb_dialogs = []
    for p in sb.get("shots", []):
        sb_dialogs += p.dialogs
    for d in script_dialogs:
        if d not in sb_dialogs:
            issues.append(Issue("E010", LEVEL_ERROR, "分镜", f"台词缺失或被改写：{d}"))
    total = sum(p.est_sec for p in sb.get("shots", []))
    _lo, _hi = _proj_bounds(conn, project)["total"]
    if sb.get("shots") and not (_lo <= total <= _hi):
        issues.append(Issue("E006", LEVEL_ERROR, "分镜",
                            f"分镜总时长 {total} 秒超出 {_lo}-{_hi} 秒"))
    for p in sb.get("shots", []):
        if not (MIN_SHOT_SEC <= p.est_sec <= MAX_SHOT_SEC):
            issues.append(Issue("E006", LEVEL_ERROR, p.no,
                                f"分镜单镜 {p.est_sec} 秒超出 {MIN_SHOT_SEC}-{MAX_SHOT_SEC} 秒"))
    return issues


# ------------------------------------------------------------ 报告

def render_report(project: str, ep_no: int, issues: list, extra: str = "") -> str:
    errs = [i for i in issues if i.level == LEVEL_ERROR]
    warns = [i for i in issues if i.level == LEVEL_WARN]
    lines = [f"# 校验报告 · {project} · EP{ep_no:02d}", "",
             f"- ERROR：**{len(errs)}**", f"- WARN：**{len(warns)}**",
             f"- 结论：{'[PASS] 通过' if not errs else '[FAIL] 未通过，禁止进入下一环节'}", ""]
    if extra:
        lines += [extra, ""]
    if not issues:
        lines.append("无问题。")
        return "\n".join(lines)
    lines += ["| 码 | 级别 | 位置 | 说明 |", "|---|---|---|---|"]
    for i in issues:
        msg = i.message.replace("\n", "<br>").replace("|", "\\|")
        lines.append(f"| {i.code} | {i.level} | {i.where} | {msg} |")
    return "\n".join(lines) + "\n"
