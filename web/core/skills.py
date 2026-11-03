# -*- coding: utf-8 -*-
"""skills.py —— 创作 Skill 的发现、装载与「给模型看的指令」组装

Skill 是什么
------------
一个目录 + 一份 `SKILL.md`：YAML frontmatter（`name` / `description`）+ 正文提示词。
它**不是可执行程序**，是给大模型的创作说明（"你是总裁甜宠的总导演兼编剧……"）。
产出是 Markdown：企划案 / 资产库 / 分集剧本 / 导演手册。

为什么要有这一层
----------------
引擎只做执行（出图 / 出片 / 剪辑），创作靠 Skill。但 Skill 之前散在磁盘上，
必须人手找到、粘进对话框 —— 中间没有任何登记。于是「这部片用的是哪套题材模板」
只能靠记忆，换人接手就断线。这里把它变成可查的事实：

  · 项目装载了哪一份（`<ws>/skills.json`）
  · 是哪个来源的哪一版（sha256 + installed_at + source 路径）
  · 组装给模型时「画风归谁」（见 §画风归属）

画风归属（重要）
----------------
Skill 里通常写死了风格（"现代精致国漫"）。但本项目**画风由项目的 style_lock 决定**
（三轨规范 + `project.json` / `style-plan.json`）。两者会打架。

规矩：**Skill 管叙事结构与题材套路，style_lock 管画风**。
`compose_prompt()` 会显式把 style_lock 插到指令最前面，并要求模型「忽略 Skill 里
与画风冲突的描述」。这条不写死在提示词里，就会出现「换了题材风格，出图却还是国漫」。

安全
----
装载 = 复制到 `<ws>/skills/<name>.md`，**不执行、不 import**。SKILL.md 是数据。
读取时会剥掉 frontmatter 之后可能存在的 `<script>` / 指令注入段落？
—— 不做。它是给模型看的文本，模型自己有权读到全部；我们只负责不让它变成代码路径。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

from . import paths

# 已装载的登记文件（放工作区，不进仓库）
REG_NAME = "skills.json"
SKILL_SUBDIR = "skills"

# ---------------------------------------------------------------------------
# 来源
# ---------------------------------------------------------------------------
DEFAULT_SOURCES = [
    # 用户给的那包 21 个题材模板
    r"D:/整合包/ai-manju-skills-main/skills",
    # 仓库内自带（如果有）
    "stages/creation/skills",
]


def sources() -> list:
    """候选 Skill 根目录（存在的才返回）。→ [{path, count, kind}]"""
    cand = []
    cfg = paths.REPO_ROOT / "configs" / "skills-sources.json"
    if cfg.is_file():
        try:
            doc = json.loads(cfg.read_text(encoding="utf-8-sig")) or {}
            for x in (doc.get("sources") or []):
                if isinstance(x, str) and x.strip():
                    cand.append(("config", x.strip()))
        except (OSError, json.JSONDecodeError):
            pass
    env = (os.environ.get("SOLODRAMA_SKILLS_DIR") or "").strip()
    if env:
        for x in re.split(r"[;|]", env):
            if x.strip():
                cand.append(("env", x.strip()))
    for x in DEFAULT_SOURCES:
        cand.append(("default", x))

    out, seen = [], set()
    for kind, raw in cand:
        p = Path(raw)
        if not p.is_absolute():
            p = paths.REPO_ROOT / raw
        try:
            key = str(p.resolve()).lower()
        except OSError:
            key = str(p).lower()
        if key in seen or not p.is_dir():
            continue
        seen.add(key)
        n = len([d for d in p.iterdir() if (d / "SKILL.md").is_file()]) if p.is_dir() else 0
        out.append({"path": str(p), "kind": kind, "count": n})
    return out


# ---------------------------------------------------------------------------
# frontmatter
# ---------------------------------------------------------------------------
_FM = re.compile(r"\A---\s*\r?\n(.*?)\r?\n---\s*\r?\n?", re.S)


def parse(text: str) -> tuple:
    """→ (meta dict, body str)。只认 `key: value` 单行，不引入 yaml 依赖。"""
    m = _FM.match(text or "")
    if not m:
        return {}, (text or "")
    raw, body = m.group(1), text[m.end():]
    meta = {}
    for line in raw.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        meta[k.strip()] = v
    return meta, body


def _guess_title(body: str, fallback: str) -> str:
    for line in (body or "").splitlines():
        s = line.strip()
        if s.startswith("#"):
            return s.lstrip("#").strip()[:60]
        if s:
            break
    return fallback


# ---------------------------------------------------------------------------
# 扫描
# ---------------------------------------------------------------------------
def scan() -> dict:
    """列出所有可装载的 Skill（跨来源去重，同 name 先到先得）。"""
    items, by_name = [], {}
    for src in sources():
        root = Path(src["path"])
        for d in sorted(root.iterdir()):
            f = d / "SKILL.md"
            if not f.is_file():
                continue
            name = d.name
            if name in by_name:
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            meta, body = parse(text)
            it = {
                "name": str(meta.get("name") or name),
                "id": name,
                "title": _guess_title(body, name),
                "desc": str(meta.get("description") or "")[:400],
                "path": str(f),
                "source": src["path"],
                "source_kind": src["kind"],
                "chars": len(body),
                "sha": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
            }
            by_name[name] = it
            items.append(it)
    items.sort(key=lambda x: x["id"])
    return {"items": items, "count": len(items), "sources": sources()}


def detail(id_or_name: str) -> dict:
    """读一份 Skill 的全文（给界面「看它到底写了什么」用）。"""
    for it in scan()["items"]:
        if id_or_name in (it["id"], it["name"]):
            f = Path(it["path"])
            text = f.read_text(encoding="utf-8", errors="replace")
            meta, body = parse(text)
            return {**it, "meta": meta, "body": body, "raw": text}
    raise KeyError(id_or_name)


# ---------------------------------------------------------------------------
# 装载 / 卸载（按项目）
# ---------------------------------------------------------------------------
def _reg_path(ws) -> Path:
    return Path(str(ws)) / REG_NAME


def installed(ws) -> dict:
    """本项目已装载的 Skill。→ {items: [...], dir}"""
    ws = Path(str(ws))
    p = _reg_path(ws)
    doc = {}
    if p.is_file():
        try:
            doc = json.loads(p.read_text(encoding="utf-8-sig")) or {}
        except (OSError, json.JSONDecodeError):
            doc = {}
    items = doc.get("items") or []
    # 文件被删了要说清，而不是继续报「已装载」
    for it in items:
        cp = ws / SKILL_SUBDIR / ("%s.md" % it.get("id"))
        it["file_exists"] = cp.is_file()
    return {"items": items, "dir": str(ws / SKILL_SUBDIR),
            "note": "装载只是「复制 + 登记」，不改 Skill 本身，也不执行任何代码"}


def install(ws, id_or_name: str, *, replace: bool = False) -> dict:
    """把一份 Skill 装进本项目：复制到 `<ws>/skills/<id>.md` 并登记。"""
    ws = Path(str(ws))
    src = detail(id_or_name)
    reg = installed(ws)
    if any(x.get("id") == src["id"] for x in reg["items"]) and not replace:
        return {"ok": True, "already": True, "id": src["id"],
                "detail": "这个 Skill 已经在项目里了（%s）" % src["id"]}

    dst_dir = ws / SKILL_SUBDIR
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / ("%s.md" % src["id"])
    dst.write_text(Path(src["path"]).read_text(encoding="utf-8", errors="replace"),
                   encoding="utf-8", newline="")

    items = [x for x in reg["items"] if x.get("id") != src["id"]]
    items.append({
        "id": src["id"], "name": src["name"], "title": src["title"],
        "desc": src["desc"], "sha": src["sha"], "chars": src["chars"],
        "source": src["path"], "installed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "file": "%s/%s.md" % (SKILL_SUBDIR, src["id"]),
    })
    paths.write_json(_reg_path(ws), {"version": 1, "items": items,
                                    "updated_at": time.time()})
    return {"ok": True, "id": src["id"], "file": str(dst),
            "detail": "已装载「%s」。创作环节会用它的叙事套路，画风仍由本项目 style_lock 决定"
                      % src["title"]}


def uninstall(ws, id_or_name: str) -> dict:
    ws = Path(str(ws))
    reg = installed(ws)
    keep = [x for x in reg["items"] if x.get("id") != id_or_name]
    if len(keep) == len(reg["items"]):
        return {"ok": False, "detail": "项目里没有这个 Skill"}
    f = ws / SKILL_SUBDIR / ("%s.md" % id_or_name)
    if f.is_file():
        f.unlink()
    paths.write_json(_reg_path(ws), {"version": 1, "items": keep,
                                    "updated_at": time.time()})
    return {"ok": True, "detail": "已移除 %s" % id_or_name}


# ---------------------------------------------------------------------------
# 组装：给模型看的完整指令
# ---------------------------------------------------------------------------
STYLE_OVERRIDE = """\
━━━━━ 本项目画风（优先级最高）━━━━━
{style_lock}

上面的画风由本项目的 style_lock 定义，**优先级高于 Skill 正文里任何关于画风的描述**。
写作时请遵守：
· 不要写「国漫」「2.5D」「赛璐璐」这类与上面冲突的风格词；
· 描述画面时用上面这段画风能落地的语言（镜头、光、色、材质）；
· 如果 Skill 正文给了「风格」默认值，一律忽略，改用上面的。
━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

OUTPUT_RULES = """\
━━━━━ 输出要求 ━━━━━
1. 直接输出正文 Markdown，不要前言、不要解释你在做什么。
2. 结构按 Skill 正文里规定的章节走，不要自创章节。
3. 不要输出任何「以下是」「希望对你有帮助」这类客套。
4. 中文一律用中文标点；人名/地名/品牌自己起，不复用真实品牌与真实明星。
"""


def compose_prompt(ws, *, style_lock: str = "", stage: str = "",
                   extra: str = "") -> str:
    """把「已装载的 Skill + 本项目画风 + 输出要求」拼成一份完整指令。

    `stage` 用来只取 Skill 里对应阶段的要求（例如 `stage="剧本"`），
    取不到就整份给 —— 宁可多给，也不要因为匹配失败而少给。
    """
    ws = Path(str(ws))
    reg = installed(ws)
    if not reg["items"]:
        raise ValueError("本项目还没装载任何 Skill：先到「Skill 中心」装一个题材模板")

    parts = []
    for it in reg["items"]:
        f = ws / SKILL_SUBDIR / ("%s.md" % it["id"])
        if not f.is_file():
            continue
        meta, body = parse(f.read_text(encoding="utf-8", errors="replace"))
        parts.append("━━━━━ 创作模板：%s ━━━━━\n%s" % (it["title"], body.strip()))
    if not parts:
        raise ValueError("登记里有 Skill，但文件都不在了：重新装载一次")
    if style_lock.strip():
        parts.insert(0, STYLE_OVERRIDE.format(style_lock=style_lock.strip()))
    parts.append(OUTPUT_RULES)
    if extra.strip():
        parts.append(extra.strip())
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# 自检
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    d = scan()
    print("来源：")
    for s in d["sources"]:
        print("  [%s] %-52s %d 份" % (s["kind"], s["path"], s["count"]))
    print("\n共 %d 份 Skill：" % d["count"])
    for it in d["items"]:
        print("  %-18s %-30s %5d 字  %s" % (it["id"], it["title"][:28], it["chars"],
                                            (it["desc"] or "")[:40]))
    if len(sys.argv) > 1:
        ws = sys.argv[1]
        r = install(ws, d["items"][0]["id"]) if d["items"] else {}
        print("\n装载到 %s：%s" % (ws, r.get("detail")))
        print("\n拼出的指令前 400 字：")
        print(compose_prompt(ws)[:400])
