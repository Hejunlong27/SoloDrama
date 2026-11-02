# -*- coding: utf-8 -*-
"""提示词模板注册表（唯一真源）—— 只剩一个用途：把创作 Skill 的产物转成制作包

为什么从 8 个用途收敛到 1 个
---------------------------
`main` 上这张表登记的是**创作**用途（剧本改写、选题定位、爆款拆解、转译、审稿），
模板正文直接读 `stages/creation/prompts/*.md`。分支 `feat/pack-engine` 把创作整体移出
引擎后，那些模板文件不存在了，继续保留登记项的结果是：

  * 界面上还能点「生成剧本」，点了报 `FileNotFoundError` —— 看起来像坏了，其实是没了；
  * 每次启动都要扫一遍不存在的目录；
  * 最糟的是「半死」：模板缺了但 Schema 还在，于是校验能过、正文永远生成不出来。

所以只留 **`pack.convert`** 一个用途：把任意创作 Skill 产出的 Markdown 转成制作包 JSON。
它服务的是「导入适配」，不是创作 —— 引擎仍然不改一个字提示词。

本模块只做三件事：
  1. 登记模板 ID、用途、版本与所需变量；
  2. 追加「本次输入」与「输出契约」两段；
  3. 提供输出 Schema（当前为空：转换结果由 `pack_spec.py` 做结构校验，不在这一层重复）。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .. import paths

# 提示词正文的真源目录（与 `docs/pack/IMPORT-PROMPT.md` 同源，这里是机器可读的落地版）
PROMPT_DIR = paths.STAGES_DIR / "import" / "prompts"

# 输出 Schema：转换产物是**多份 JSON 文件**，由 pack_import 逐字段校验（那边能给出
# 「第几个镜头的 duration 越界」这种定位信息）。这里留空，避免两套校验各说一套。
SCHEMAS: dict = {}

SCHEMA_NOTES: dict = {}

FIELD_HINTS = {
    "spec": "spec 必须是 solodrama-pack/1 / solodrama-assets/1 / solodrama-episode/1",
    "style_lock": "style_lock 不能为空：画风只在这里定义一次，引擎不提供默认值",
    "duration": "duration 是整数秒，平台只接受 4–15",
    "cast": "cast 的顺序就是参考图上传顺序，必须与提示词里的图号逐位对应",
}

TEMPLATE_MAP = {
    "convert-to-pack": {
        "file": "convert_to_pack.md",
        "title": "人读制作文档 → 制作包 JSON",
        "purpose": "pack.convert",
        "format": "json",
        "schema_id": "",
        "vars": ("source_dir", "output_dir", "style_hint"),
    },
}

PURPOSES = [
    {
        "id": "pack.convert", "label": "制作包转换（格式搬运）", "group": "导入",
        "template_id": "convert-to-pack", "schema_id": None,
        "requires": ["json"],
        "needs": "创作 Skill 产出的 Markdown（企划案 / 资产库 / 剧本 / 导演手册）",
        "hint": "只做格式搬运：不改剧情、不改台词、不改提示词、不补写内容",
    },
]

PURPOSE_MAP = {p["id"]: p for p in PURPOSES}


# ---------------------------------------------------------------------------
# 正文读取
# ---------------------------------------------------------------------------
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
        "sha": body_sha(tid),
        "missing_file": ("" if body else str(body_path(tid))),
    }


def all_templates() -> list:
    return [describe(tid) for tid in TEMPLATE_MAP]


def purpose_list() -> list:
    return [dict(p) for p in PURPOSES]


def field_hint(path: str) -> str:
    """从 `shots[7].duration` 这样的路径里取出最后一节，给出可执行的修改建议。"""
    tail = str(path or "").split(".")[-1].strip()
    return FIELD_HINTS.get(tail, "")


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------
def render_parts(tid: str, variables: dict):
    """渲染成 (system, user) 两段。

    system = 仓库提示词原文（方法论，权威）；
    user   = 本次输入（从哪读到哪写）。
    """
    t = TEMPLATE_MAP.get(tid)
    if not t:
        raise KeyError(tid)
    body = body_text(tid)
    if not body:
        raise FileNotFoundError(str(body_path(tid)))

    vars_ = variables or {}
    # `style_hint` 是可选的：有的 Skill 已经把风格写在提示词里，不必再给
    missing = [v for v in t["vars"]
               if v != "style_hint" and (v not in vars_ or vars_[v] in (None, ""))]
    if missing:
        from .errors import LLMError
        raise LLMError("config", "模板 %s 缺少输入变量：%s" % (tid, "、".join(missing)))

    parts = ["## 本次输入"]
    for key in t["vars"]:
        val = vars_.get(key)
        if val in (None, ""):
            continue
        if isinstance(val, (dict, list)):
            val = json.dumps(val, ensure_ascii=False, indent=2)
        parts += ["", "### %s" % key, "", str(val).strip()]

    parts += ["", "## 输出契约", "",
              "把结果直接写到 `output_dir`：`pack.json`、`assets/*.json`、`episodes/epNN.json`。",
              "同时写一份 `_import_report.md`，逐条说明「原文位置 → 输出字段」以及所有留空、",
              "合并、跳过的项及原因。不要输出解释性正文。"]
    return body.rstrip() + "\n", "\n".join(parts).strip() + "\n"


def render(tid: str, variables: dict) -> str:
    """预览用：把 system + user 拼成一份完整提示词。"""
    system, user = render_parts(tid, variables)
    return system + "\n\n---\n\n" + user


# ---------------------------------------------------------------------------
# 离线演练（Mock）
# ---------------------------------------------------------------------------
# 没有凭据时也要能验证整条链路（渲染 → 网关 → 落盘 → 导入校验）。
# 只替换「网络那一段」，下游全走真实代码；结果一律带 `simulated: true`。
_MOCK_PACK = {
    "pack.json": {
        "spec": "solodrama-pack/1", "title": "演练用最小包", "slug": "mock-pack",
        "delivery": {"width": 1080, "height": 1920, "fps": 24,
                     "episode_count": 1, "target_duration": 10},
        "style_lock": "美式复古影视风格，胶片颗粒，年代色偏",
        "negative": "文字，水印",
    },
    "assets/characters.json": {
        "spec": "solodrama-assets/1", "kind": "character",
        "items": [{"id": "P01", "name": "演练角色",
                   "variants": [{"code": "base", "prompt": "演练用提示词"}]}],
    },
    "episodes/ep01.json": {
        "spec": "solodrama-episode/1", "episode": 1, "title": "演练",
        "shots": [{"id": "shot_001", "duration": 5,
                   "cast": [{"asset": "P01"}],
                   "board_prompt": "演练构图", "video_prompt": "演练视频提示词"}],
    },
}


def mock_payload(purpose, variables):
    """离线演练返回的样例（结构与真实转换产物一致，字段值只是占位）。"""
    return {"simulated": True,
            "note": "演练结果：只验证链路，不产生可用的制作包",
            "files": _MOCK_PACK}
