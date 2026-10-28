# -*- coding: utf-8 -*-
"""提示词模板注册表与业务用途路由（唯一真源）

★ 复用原则：模板正文**直接读** `stages/creation/prompts/*.md`（仓库的权威提示词），
  本模块只负责三件事：
    1. 给每个模板登记稳定 ID、业务用途、版本与所需变量；
    2. 追加「本次输入」与「输出契约」两段（把结构化要求显式写进提示词）；
    3. 提供输出 Schema，供网关做机器校验。
  不新写一套提示词——那样会和仓库里的方法论分叉。

模板版本：`v1` 指「仓库原文件 + 本模块追加段」的口径。仓库原文件内容变化时，
  用 `body_sha` 记录指纹，前端能看出提示词被改过（而不是静默漂移）。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .. import paths

PROMPT_DIR = paths.STAGES_DIR / "creation" / "prompts"

# ---------------------------------------------------------------------------
# 输出 Schema
# ---------------------------------------------------------------------------
# 单集正文：与 `script_rewrite.py lint` 的硬约束严格对齐
#   镜头数 5-10（60 秒档）· DUR 4-15 · HEADER 六字段 · 镜头八字段 · 禁 MOOD/CAMERA/EMOTION/MUSIC/LIGHT
EPISODE_SCHEMA = {
    "type": "object",
    "required": ["episode", "title", "cold_open", "reversal", "hook", "shots"],
    "properties": {
        "episode": {"type": "integer", "minimum": 1, "maximum": 200},
        "title": {"type": "string", "minLength": 2, "maxLength": 60},
        "platform": {"type": "string", "maxLength": 40},
        "cold_open": {"type": "string", "minLength": 4, "maxLength": 200},
        "core_conflict": {"type": "string", "maxLength": 200},
        "reversal": {"type": "string", "minLength": 4, "maxLength": 240},
        "hook": {"type": "string", "minLength": 4, "maxLength": 200},
        "hook_type": {
            "type": "string",
            "enum": ["身份悬念", "危机逼近", "关系反转", "秘密揭露", "选择困境", "意外登场", "代价预告"],
        },
        "shots": {
            "type": "array",
            "minItems": 5,
            "maxItems": 10,
            "items": {
                "type": "object",
                "required": ["no", "shot", "location", "time", "char", "action", "dialog", "dur"],
                "properties": {
                    "no": {"type": "integer", "minimum": 1, "maximum": 20},
                    "shot": {"type": "string", "minLength": 2, "maxLength": 40},
                    "location": {"type": "string", "minLength": 2, "maxLength": 40},
                    "time": {"type": "string", "minLength": 1, "maxLength": 20},
                    "char": {"type": "string", "maxLength": 80},
                    "action": {"type": "string", "minLength": 6, "maxLength": 400},
                    "dialog": {"type": "string", "maxLength": 300},
                    "vo": {"type": "string", "maxLength": 300},
                    "sfx": {"type": "string", "maxLength": 120},
                    "dur": {"type": "integer", "minimum": 4, "maximum": 15},
                },
            },
        },
    },
}

# 改编诊断（A 选题诊断 / B 改编策略 / C 故事主线），对应 s3a-diagnosis.md
DIAGNOSIS_SCHEMA = {
    "type": "object",
    "required": ["A_diagnosis", "B_strategy", "C_mainline"],
    "properties": {
        "A_diagnosis": {
            "type": "object",
            "required": ["hook", "retention_risk", "verdict"],
            "properties": {
                "hook": {"type": "string", "minLength": 6, "maxLength": 400},
                "retention_risk": {"type": "string", "minLength": 6, "maxLength": 400},
                "verdict": {"type": "string", "maxLength": 60},
            },
        },
        "B_strategy": {
            "type": "object",
            "required": ["keep", "rework", "escalation"],
            "properties": {
                "keep": {"type": "array", "minItems": 1, "maxItems": 8, "items": {"type": "string", "maxLength": 200}},
                "rework": {"type": "array", "minItems": 1, "maxItems": 8, "items": {"type": "string", "maxLength": 200}},
                "escalation": {"type": "array", "minItems": 1, "maxItems": 8, "items": {"type": "string", "maxLength": 200}},
            },
        },
        "C_mainline": {
            "type": "object",
            "required": ["protagonist", "opposition", "turn_points"],
            "properties": {
                "protagonist": {"type": "string", "minLength": 2, "maxLength": 200},
                "opposition": {"type": "string", "minLength": 2, "maxLength": 200},
                "turn_points": {"type": "array", "minItems": 2, "maxItems": 10, "items": {"type": "string", "maxLength": 200}},
            },
        },
    },
}

# 观众视角审稿（七问 + 三条优先修改），对应 s3c-audience-review.md
REVIEW_SCHEMA = {
    "type": "object",
    "required": ["episode", "verdict", "answers", "top_fixes"],
    "properties": {
        "episode": {"type": "integer", "minimum": 1, "maximum": 200},
        "verdict": {"type": "string", "enum": ["PASS", "MINOR", "FAIL"]},
        "answers": {
            "type": "array",
            "minItems": 5,
            "maxItems": 9,
            "items": {
                "type": "object",
                "required": ["q", "a"],
                "properties": {
                    "q": {"type": "string", "maxLength": 120},
                    "a": {"type": "string", "minLength": 2, "maxLength": 400},
                },
            },
        },
        "top_fixes": {"type": "array", "minItems": 1, "maxItems": 3, "items": {"type": "string", "maxLength": 240}},
    },
}

# 选题候选池（s2-topic-positioning.md 的回填对象）
CANDIDATES_SCHEMA = {
    "type": "object",
    "required": ["candidates"],
    "properties": {
        "candidates": {
            "type": "array",
            "minItems": 1,
            "maxItems": 30,
            "items": {
                "type": "object",
                "required": ["title", "logline"],
                "properties": {
                    "title": {"type": "string", "minLength": 2, "maxLength": 60},
                    "logline": {"type": "string", "minLength": 10, "maxLength": 300},
                    "genre": {"type": "string", "maxLength": 40},
                    "hook": {"type": "string", "maxLength": 200},
                },
            },
        }
    },
}

SCHEMAS = {
    "script.episode": EPISODE_SCHEMA,
    "script.diagnosis": DIAGNOSIS_SCHEMA,
    "script.review": REVIEW_SCHEMA,
    "topic.candidates": CANDIDATES_SCHEMA,
}

# ---------------------------------------------------------------------------
# 业务用途（6.5 模型用途路由）
# ---------------------------------------------------------------------------
# requires: 模型能力要求；template/schema 为默认绑定（可在配置里改 provider/model，但不改语义）
PURPOSES = [
    {
        "id": "script.generate", "label": "剧本正文生成", "group": "剧本",
        "template_id": "s3-script-rewrite", "schema_id": "script.episode",
        "requires": ["json"], "needs": "项目已确认诊断卡与集数规划",
        "hint": "按 blueprint 的单集规划写 FFS 正文（开场钩子/核心冲突/反转/集尾钩子）",
    },
    {
        "id": "script.diagnose", "label": "剧本改编诊断", "group": "剧本",
        "template_id": "s3a-diagnosis", "schema_id": "script.diagnosis",
        "requires": ["json"], "needs": "源剧本 + 选题定位",
        "hint": "动笔前判断「靠什么留住观众」与「源稿怎么改」",
    },
    {
        "id": "script.review", "label": "观众视角审稿", "group": "剧本",
        "template_id": "s3c-audience-review", "schema_id": "script.review",
        "requires": ["json"], "needs": "已成稿的单集剧本",
        "hint": "只看「观众会不会看下去」，不看格式",
    },
    {
        "id": "topic.position", "label": "选题定位", "group": "创作",
        "template_id": "s2-topic-positioning", "schema_id": "topic.candidates",
        "requires": ["json"], "needs": "榜单拆解结果",
        "hint": "产出原始候选池，交确定性的七维评分脚本排序",
    },
    {
        "id": "topic.research", "label": "榜单调研", "group": "创作",
        "template_id": "s0-market-research", "schema_id": "",
        "requires": [], "needs": "目标市场",
        "hint": "补齐市场数据缺口；回填对象由 market_data.py 校验",
    },
    {
        "id": "topic.breakdown", "label": "爆款拆解", "group": "创作",
        "template_id": "s1-hit-breakdown", "schema_id": "",
        "requires": [], "needs": "榜单原始数据",
        "hint": "确定性算法已完成拆解，本用途只做洞察增补",
    },
    {
        "id": "script.translate", "label": "剧本转译", "group": "剧本",
        "template_id": "s0b-script-translate", "schema_id": "",
        "requires": [], "needs": "源剧本 + 目标语种",
        "hint": "非目标语种先转译，质检通过后再进改写",
    },
]

PURPOSE_MAP = {p["id"]: p for p in PURPOSES}

# ---------------------------------------------------------------------------
# 模板登记
# ---------------------------------------------------------------------------
# vars: 渲染时要求的变量名（缺失即报 config，不静默变成空串）
TEMPLATES = [
    {
        "id": "s3-script-rewrite", "title": "剧本改写 · 写正文", "purpose": "script.generate",
        "file": "s3-script-rewrite.md", "format": "json", "schema_id": "script.episode",
        "vars": ["blueprint_row", "style_lock", "char_header", "scene_header", "ep_seconds", "shot_count"],
    },
    {
        "id": "s3a-diagnosis", "title": "剧本改编诊断", "purpose": "script.diagnose",
        "file": "s3a-diagnosis.md", "format": "json", "schema_id": "script.diagnosis",
        "vars": ["source_script", "positioning"],
    },
    {
        "id": "s3c-audience-review", "title": "观众视角审稿", "purpose": "script.review",
        "file": "s3c-audience-review.md", "format": "json", "schema_id": "script.review",
        "vars": ["episode_no", "script_text"],
    },
    {
        "id": "s2-topic-positioning", "title": "选题定位", "purpose": "topic.position",
        "file": "s2-topic-positioning.md", "format": "json", "schema_id": "topic.candidates",
        "vars": ["breakdown", "market"],
    },
    {
        "id": "s0-market-research", "title": "榜单调研", "purpose": "topic.research",
        "file": "s0-market-research.md", "format": "text", "schema_id": "",
        "vars": ["market", "gaps"],
    },
    {
        "id": "s1-hit-breakdown", "title": "爆款拆解", "purpose": "topic.breakdown",
        "file": "s1-hit-breakdown.md", "format": "text", "schema_id": "",
        "vars": ["breakdown", "market"],
    },
    {
        "id": "s0b-script-translate", "title": "剧本转译", "purpose": "script.translate",
        "file": "s0b-script-translate.md", "format": "text", "schema_id": "",
        "vars": ["source_script", "target_language"],
    },
]

TEMPLATE_MAP = {t["id"]: t for t in TEMPLATES}


def body_path(tid: str) -> Path:
    t = TEMPLATE_MAP.get(tid)
    return PROMPT_DIR / t["file"] if t else None


def body_text(tid: str) -> str:
    """读仓库里的提示词原文件。缺失返回空串（由调用方判 config 错误）。"""
    p = body_path(tid)
    if p is None:
        return ""
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def body_sha(tid: str) -> str:
    txt = body_text(tid)
    return hashlib.sha256(txt.encode("utf-8")).hexdigest()[:16] if txt else ""


def describe(tid: str) -> dict:
    """前端用的模板描述（不含正文，正文单独取以省流量）。"""
    t = TEMPLATE_MAP.get(tid) or {}
    if not t:
        return {"ok": False, "reason": "unknown_template", "id": tid}
    body = body_text(tid)
    return {
        "ok": bool(body),
        "id": tid,
        "title": t["title"],
        "purpose": t["purpose"],
        "version": "v1",
        "format": t["format"],
        "schema_id": t["schema_id"],
        "vars": list(t["vars"]),
        "file": "stages/creation/prompts/" + t["file"],
        "body_sha": body_sha(tid),
        "body_lines": body.count("\n") + 1 if body else 0,
        "body": body,
    }


def all_templates() -> list:
    return [describe(t["id"]) for t in TEMPLATES]


def render_parts(tid: str, variables: dict):
    """渲染成 (system, user) 两段。

    system = 仓库提示词原文（方法论，权威）；
    user   = 本次输入 + 输出契约（机器可读要求）。
    这样既不改写仓库原文，又让模型看到明确的 Schema。
    """
    t = TEMPLATE_MAP.get(tid)
    if not t:
        raise KeyError(tid)
    body = body_text(tid)
    if not body:
        raise FileNotFoundError(str(body_path(tid)))

    vars_ = variables or {}
    missing = [v for v in t["vars"] if v not in vars_ or vars_[v] in (None, "")]
    if missing:
        from .errors import LLMError
        raise LLMError("config", "模板 %s 缺少输入变量：%s" % (tid, "、".join(missing)))

    parts = ["## 本次输入"]
    for key in t["vars"]:
        val = vars_.get(key)
        if isinstance(val, (dict, list)):
            val = json.dumps(val, ensure_ascii=False, indent=2)
        parts += ["", "### %s" % key, "", str(val).strip()]

    if t["format"] == "json" and t["schema_id"]:
        sch = SCHEMAS.get(t["schema_id"]) or {}
        parts += ["", "## 输出契约（必须严格遵守）", "",
                  "只输出**一个 JSON 对象**：不要解释、不要前言、不要 markdown 代码围栏、不要在 JSON 前后加任何文字。",
                  "下列 Schema 为硬约束，字段类型/取值范围/枚举不满足即视为失败：", "",
                  "```json", json.dumps(sch, ensure_ascii=False, indent=2), "```"]
    else:
        parts += ["", "## 输出契约", "",
                  "按上文要求输出正文。本环节没有机器可校验的 Schema，输出将由人工复核。"]
    return body.rstrip() + "\n", "\n".join(parts).strip() + "\n"


def render(tid: str, variables: dict) -> str:
    """预览用：把 system + user 拼成一份完整提示词。"""
    system, user = render_parts(tid, variables)
    return system + "\n\n---\n\n" + user


# ---------------------------------------------------------------------------
# 离线演练（Mock）的样例输出
# ---------------------------------------------------------------------------
# 为什么要有它：没有凭据时也要能验证**整条链路**（解析 → Schema → 草稿 → 落盘 → 引擎 lint）。
# 它只替换「网络那一段」，下游全部走真实代码路径；结果一律带 `simulated: true`，不许冒充真实生成。
_HOOK_TYPES = ["身份悬念", "危机逼近", "关系反转", "秘密揭露", "选择困境", "意外登场", "代价预告"]


def _header_codes(line, prefix):
    """从 `# CHAR: CAMILA: 描述; ADRIAN: 描述` 里取出代号。"""
    s = str(line or "").strip()
    if s.upper().startswith(prefix):
        s = s.split(":", 1)[1] if ":" in s else ""
    out = []
    for part in s.split(";"):
        name = part.split(":")[0].strip()
        if len(name) >= 2 and name.replace("_", "").isupper() and name.isascii():
            out.append(name)
    return out


def mock_payload(purpose, variables):
    """返回一段「会被下游当成模型输出」的文本（JSON 字符串或纯文本）。

    ★ 结构化用途一律按 **Schema 的边界**构造（镜数/时长/枚举都取合法值），
      这样它既能证明链路通，也能证明校验器真的在工作（越界会被拦下）。
    """
    v = variables or {}
    if purpose == "script.generate":   # 用途 id（不是 schema id）
        row = v.get("blueprint_row") if isinstance(v.get("blueprint_row"), dict) else {}
        try:
            ep = int(row.get("ep") or 1)
        except (TypeError, ValueError):
            ep = 1
        try:
            shots = int(v.get("shot_count") or 8)
        except (TypeError, ValueError):
            shots = 8
        shots = max(5, min(10, shots))
        try:
            secs = int(v.get("ep_seconds") or 60)
        except (TypeError, ValueError):
            secs = 60
        dur = max(4, min(15, int(round(float(secs) / max(shots, 1)))))

        chars = _header_codes(v.get("char_header"), "# CHAR:") or ["CHAR_A"]
        scenes = _header_codes(v.get("scene_header"), "# SCENE:") or ["SCENE_A"]
        hook_type = row.get("hook_type")
        if hook_type not in _HOOK_TYPES:
            hook_type = "身份悬念"

        body = []
        for i in range(1, shots + 1):
            body.append({
                "no": i,
                "shot": "特写, 推" if i % 4 == 0 else ("中景, 固定" if i % 2 else "全景, 跟随"),
                "location": scenes[(i - 1) % len(scenes)],
                "time": "夜",
                "char": chars[(i - 1) % len(chars)],
                "action": "演练第 %d 镜：她把手里的东西放下，抬眼看向门口的人，动作停在半空，呼吸乱了一拍" % i,
                "dialog": "无" if i % 2 else "“你终于肯开口了。”",
                "vo": "无",
                "sfx": "环境底噪与远处车声",
                "dur": dur,
            })
        return json.dumps({
            "episode": ep,
            "title": "演练单集（Mock 生成，非真实模型输出）",
            "platform": "演练",
            "cold_open": row.get("cold_open") or "演练开场：冲突直接摆到台面上",
            "core_conflict": row.get("core_conflict") or "演练冲突：她要保住手里这一点东西",
            "reversal": row.get("reversal") or "演练反转：力量对比发生变化，主动权换人",
            "hook": row.get("hook") or "演练钩子：门外有人停下脚步",
            "hook_type": hook_type,
            "shots": body,
        }, ensure_ascii=False)

    if purpose == "script.diagnose":
        return json.dumps({
            "A_diagnosis": {"hook": "演练：开场 3 秒把冲突摆到台面上",
                            "retention_risk": "演练：中段缺少力量对比的阶梯",
                            "verdict": "可写"},
            "B_strategy": {"keep": ["演练：核心人设"], "rework": ["演练：集尾钩子改写"],
                           "escalation": ["演练：每 3 集一次中型爆点"]},
            "C_mainline": {"protagonist": "演练：女主", "opposition": "演练：压制方",
                           "turn_points": ["演练：第一次打脸", "演练：身份揭示"]},
        }, ensure_ascii=False)

    if purpose == "script.review":
        ep = 1
        try:
            ep = int((v.get("episode_no") or 1))
        except (TypeError, ValueError):
            ep = 1
        return json.dumps({
            "episode": ep,
            "verdict": "PASS",
            "answers": [{"q": "开场 3 秒有没有钩子？", "a": "演练：有，直接泼汤。"},
                        {"q": "女主是否被动？", "a": "演练：第一镜之后开始反击。"},
                        {"q": "反转是否改变格局？", "a": "演练：名分被公开。"},
                        {"q": "集尾是否想让人看下一集？", "a": "演练：门外车里有人盯着。"},
                        {"q": "有没有看不懂的信息？", "a": "演练：没有。"}],
            "top_fixes": ["演练：把 SC-02 的骂句缩短到 18 字以内"],
        }, ensure_ascii=False)

    if purpose == "topic.position":
        return json.dumps({"candidates": [
            {"title": "演练候选 A", "logline": "演练：她被当众认作陌生人的妻子，名分成了武器。", "genre": "逆袭"},
            {"title": "演练候选 B", "logline": "演练：她替人背了三年黑锅，出狱那天有人来接她。", "genre": "复仇"},
        ]}, ensure_ascii=False)

    return "（演练输出）本用途没有机器可校验的 Schema；这段文本只用于验证链路连通，不含真实内容。\n"


def purpose_list() -> list:
    return [dict(p) for p in PURPOSES]
