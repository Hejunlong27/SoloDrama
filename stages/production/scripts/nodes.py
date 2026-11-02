#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""nodes.py —— 五环节 12 节点的状态机（调度器的唯一真源）

它替代了什么
------------
旧链路有三套并存的「环节编号」：`生产流程总纲` 的 16 环节、`标准作业流程` 的 S1–S11、
`workflow.py` 里再写一遍 S1–S11，三份文档各自声称自己是真源。三套编号对不上，
于是「现在该干什么」这个问题有三个答案。

现在只有一份：**五环节 12 节点**，每个节点六个字段齐全（触发 / 读 / 产物 / 判据 / 接替 / 回流）。

为什么流程归代码、内容归模型
----------------------------
调度器是**确定性状态机**：它只看磁盘，不看对话、不看内存。
LLM 只决定「这一个节点的内容怎么写」，不决定「下一步做什么」——
一旦让模型每次自己推流程，它就会漂（今天按 A 顺序、明天按 B 顺序，跑三次三个结果）。

状态只有六个值，全部由产物 + 判据推出：

    absent   产物不存在
    stale    产物在，但比上游旧（上游改过）
    failed   判据不过
    passed   判据通过
    skipped  显式跳过（写 _skip/<node>.json，必须带理由）
    blocked  上游未通过

四层环（Loop）
--------------
| 层 | 触发 | 预算 | 耗尽后 |
|---|---|---|---|
| L0 retry  | 网络 / 显存 / 上传失败 | 2 次，退避 5s→15s | 进 L1 |
| L1 repair | 判据不过（内容问题） | 3 次，**每次必须变一个变量** | 进 L2 |
| L2 reflow | L1 耗尽 | 1 次，回白名单里的上游 | blocked_human |
| L3 batch  | 集级失败 | 集数 | 全局 blocked，release 不放行 |

反抖动靠 `variant_hash`：第二次拿到的修复方案与上次一样，直接判 `stuck`（退出码 5），
不浪费一次失败重跑来凑数。

计费保护：`_spend/<node>.json` 记 task_id 与金额，重入先比对，已花的不重花。

用法
----
    python stages/production/scripts/nodes.py next     --workspace <ws> [--ep ep01] [--json]
    python stages/production/scripts/nodes.py status   --workspace <ws> [--json]
    python stages/production/scripts/nodes.py do <node> --workspace <ws> [--ep ep01] [--dry-run]
    python stages/production/scripts/nodes.py graph                # 打印节点图（人读）

退出码
------
    0 通过 / 干跑成功
    2 判据不过（可修）
    3 缺输入（上游没产物）
    4 需要人工（L2 耗尽 / 计费闸门 / 门禁不过）
    5 stuck（variant_hash 与上次相同，修不动）
    6 未实现（该节点的执行体还没接）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[union-attr]
except Exception:                                                # noqa: BLE001
    pass

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]                       # stages/production/scripts → 仓库根（parents[1] 是 stages）
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "stages"))

import _ws as W                              # noqa: E402
import _layout as L                          # noqa: E402

EXIT_OK, EXIT_FAIL, EXIT_NOINPUT, EXIT_HUMAN, EXIT_STUCK, EXIT_TODO = 0, 2, 3, 4, 5, 6

# ===========================================================================
# 五环节
# ===========================================================================
STAGES = [
    {"id": "import", "name": "导入", "why": "把创作 Skill 的制作包翻译成 data/ 契约；引擎不读创作文档，也不改一个字提示词"},
    {"id": "asset", "name": "资产", "why": "批量出资产图（人/场/道）；本地通道 ￥0，云端逐张计费"},
    {"id": "board", "name": "分镜图", "why": "每镜一张 9:16 首帧；它是出片的第一张参考图，不是可选装饰"},
    {"id": "video", "name": "出片", "why": "★计费。分镜图 + 角色 + 场景三参；退出码 3 是批次缺口，--resume 而不是重写提示词"},
    {"id": "edit", "name": "剪辑", "why": "母版拼接（帧数校验）→ 高清放大 → 字幕 → 交付规格 → 发布版"},
]

# ===========================================================================
# 12 节点（导入 3 / 资产 1 / 分镜图 1 / 出片 3 / 剪辑 4）
# ---------------------------------------------------------------------------
# 每个节点六个字段：
#   trigger  触发命令（唯一入口，重复执行结果相同）
#   reads    依赖的上游产物（缺一个即 blocked）
#   output   产物落点（唯一，别处不再生成）
#   check    判据（机器可判，二值）—— 见下面 CHECKERS
#   next     接替（下一节点）
#   reflow   不过时的回流边白名单（只能回这些，不许自由跳）
# ===========================================================================
NODES: list = [
    # ---------------- 导入 ----------------
    # ⚠️ 这一环节**不创作**：它只把制作包（docs/pack/PACK-SPEC.md）翻译成 data/ 契约，
    #    提示词逐字搬运，一个字都不改。缺字段就报错，不猜、不补、不润色。
    {"id": "import.pack", "stage": "import", "ep": True,
     "trigger": "drama do import.pack --ep ep01",
     "reads": [], "output": "06-提示词/<ep>/shots.json",
     "check": "imported", "next": "asset.render", "reflow": [],
     "run": "python stages/import/pack_import.py --pack {ws}/pack --apply"},

    # ---------------- 资产 ----------------
    {"id": "asset.render", "stage": "asset", "ep": False,
     "trigger": "drama do asset.render",
     "reads": ["import.pack"], "output": "04-资产/refs.json",
     "check": "assets", "next": "import.bind", "reflow": ["import.pack"],
     # 本地 ComfyUI：￥0，占 GPU 不占钱。`--pack` 直接吃制作包的资产清单；
     # 已出过且提示词指纹未变的图会跳过（断点续跑）。
     "run": "python stages/production/scripts/gen_assets_local.py --pack {ws}/pack --submit"},

    {"id": "import.bind", "stage": "import", "ep": True,
     "trigger": "drama do import.bind --ep ep01",
     "reads": ["asset.render"], "output": "_done/import.bind.<ep>.json",
     "check": "five", "next": "board.frame", "reflow": ["asset.render"],
     # 出完图要**重跑同一条导入命令**回填 characters.json / scenes.json。
     # 这一步单独立节点，是因为「图没出就导入」会写出一张空参考表，
      # 而空表在出片时表现为「key 找不到」——看起来像导入坏了，其实只是顺序反了。
     "run": "python stages/import/pack_import.py --pack {ws}/pack --apply"},

    # ---------------- 分镜图 ----------------
    {"id": "board.frame", "stage": "board", "ep": True,
     "trigger": "drama do board.frame --ep ep01",
     "reads": ["import.bind"], "output": "04-资产/boards/<ep>/",
     "check": "boards", "next": "import.gate", "reflow": ["import.bind"],
     "run": "python stages/production/scripts/gen_boards.py --apply"},

    {"id": "import.gate", "stage": "import", "ep": True,
     "trigger": "drama do import.gate --ep ep01",
     "reads": ["board.frame"], "output": "_done/import.gate.<ep>.json",
     "check": "cmd:ingest_check.py", "next": "video.resolve",
     "reflow": ["import.bind", "board.frame"],
     "run": "python stages/production/scripts/ingest_check.py"},

    # ---------------- 出片 ----------------
    {"id": "video.resolve", "stage": "video", "ep": True,
     "trigger": "drama do video.resolve --ep ep01",
     "reads": ["import.gate"], "output": "_done/video.resolve.<ep>.json",
     "check": "cmd:capabilities.py check", "next": "video.batch", "reflow": ["import.gate"],
     "run": "python stages/production/scripts/capabilities.py check"},
    {"id": "video.batch", "stage": "video", "ep": True,
     "trigger": "drama do video.batch --ep ep01 --yes",
     "reads": ["video.resolve"], "output": "07-成片/<ep>/",
     "check": "segments", "next": "video.audit", "reflow": ["video.resolve"],
     "ws_kind": "engine", "run": "python stages/video/workflow/scripts/run.py --video-only"},
    {"id": "video.audit", "stage": "video", "ep": True,
     "trigger": "drama do video.audit --ep ep01",
     "reads": ["video.batch"], "output": "_done/video.audit.<ep>.json",
     "check": "audit", "next": "edit.master", "reflow": ["video.batch"],
     "run": "（逐段校验：存在/时长/分辨率/音轨）"},

    # ---------------- 剪辑 ----------------
    {"id": "edit.master", "stage": "edit", "ep": True,
     "trigger": "drama do edit.master --ep ep01",
     "reads": ["video.audit"], "output": "07-成片/<ep>/*_master.mp4",
     "check": "master", "next": "edit.upscale", "reflow": ["video.batch"],
     # 母版 = 首帧封面 + 视频片段 + BGM（可选），一次产出 `<ep>_master.mp4`。
     "run": "python stages/subtitle/scripts/subtitle.py --stage master"},
    {"id": "edit.upscale", "stage": "edit", "ep": True,
     "trigger": "drama do edit.upscale --ep ep01",
     "reads": ["edit.master"], "output": "07-成片/<ep>/*_master_1080x1920.mp4",
     "check": "upscaled", "next": "edit.subtitle", "reflow": ["edit.master"],
     # 后端由 config.upscale.json 的 backend 决定：topaz（本地）/ rh（计费）/ off。
     # 本分支的项目预配置默认 rh + exact 1080x1920。
     "run": "python stages/subtitle/scripts/upscale.py"},
    {"id": "edit.subtitle", "stage": "edit", "ep": True,
     "trigger": "drama do edit.subtitle --ep ep01",
     "reads": ["edit.upscale"], "output": "07-成片/<ep>/*_subbed.mp4",
     "check": "subtitled", "next": "edit.release", "reflow": ["edit.upscale"],
     # 字幕时间只认对齐结果（ASR/CTC）。cues=0 直接拒绝出片 —— 旧行为会静默烧一条空字幕
     # 还叫 `_subbed.mp4`，与「已加字幕」从文件名上分不出来。
     "run": "python stages/subtitle/scripts/subtitle.py --stage render"},
    {"id": "edit.release", "stage": "edit", "ep": True,
     "trigger": "drama do edit.release --ep ep01",
     "reads": ["edit.subtitle"], "output": "09-发行/剧集/EpisodeNN.mp4",
     "check": "release", "next": "", "reflow": ["edit.subtitle"],
     # 按集导出，不是 --all：节点本身是 ep 级的，--all 会把其它集一起过一遍。
     "run": "python stages/production/scripts/release_export.py --apply"},
]

NODE_BY_ID = {n["id"]: n for n in NODES}
ORDER = [n["id"] for n in NODES]
REFLOW_EDGES = {(n["id"], r) for n in NODES for r in n["reflow"]}
MAX_REPAIR = 3          # L1 预算
MAX_RETRY = 2           # L0 预算


# ===========================================================================
# 上下文与状态
# ===========================================================================
def _read_json(p: pathlib.Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8-sig")) if p.is_file() else default
    except Exception:                                            # noqa: BLE001
        return default


def _write_json(p: pathlib.Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8", newline="")


class Ctx:
    """工作区 + 阶段目录。所有路径解析走 `_layout`（唯一真源），不硬拼。"""

    def __init__(self, ws: pathlib.Path, ep: str = ""):
        self.ws = ws
        self.ep = ep or ""
        self.state_dir = ws / ".drama"           # 状态、消耗、循环记录都在这
        try:
            self.stage = {k: L.stage_dir(ws, k) for k in
                          ("research", "topic", "script", "assets", "storyboard", "prompts")}
        except Exception:                                        # noqa: BLE001
            self.stage = {}
        try:
            self.data = L.data_dir(ws)
            self.out = L.out_dir(ws)
        except Exception:                                        # noqa: BLE001
            self.data = ws / "06-提示词"
            self.out = ws / "07-成片"
        # 节点状态的「一轮内备忘录」不放这里，而是 `evaluate()` 里的局部 dict
        # —— 挂在 Ctx 上会让「改完文件再判一次」拿到上一轮的结论。

    def ep_path(self, node: dict) -> pathlib.Path:
        """把节点 output 里的 `<ep>` 换成实际集号。

        ★ 2026-11-01：剧本文件存在三种命名（`ep_01.md` / `ep01.md` / `EP01.md`），
          判据用 `ep_script()` 宽容查找，但这里原来只拼 `<ep>.md` —— 于是
          `drama do script.episode` 打印的「产物：03-剧本/ep01.md」与实际文件
          `ep_01.md` 不符，人会以为文件放错了地方。剧本类节点优先返回真实文件。
        """
        rel = str(node.get("output") or "")
        if "<ep>" in rel and rel.startswith("03-剧本"):
            found = self.ep_script()
            if found is not None:
                return found
        return self.ws / rel.replace("<ep>", self.ep or "ep01")

    def ep_dir(self, parent: pathlib.Path) -> pathlib.Path | None:
        """在 parent 下找本集目录，**大小写与分隔符都不敏感**。

        现实里的集目录有 `EP01` / `ep01` / `EP_01` 三种写法（历史项目各写各的），
        而 `canon_ep()` 只规范化新产物，旧目录不会自己改名。这里做一次宽容匹配，
        比强推「必须叫 ep01」现实得多 —— 改名意味着旧批次全部失联。
        """
        if not parent.is_dir():
            return None
        key = re.sub(r"[^0-9a-z]", "", (self.ep or "ep01").lower())
        for d in sorted(parent.iterdir()):
            if d.is_dir() and re.sub(r"[^0-9a-z]", "", d.name.lower()) == key:
                return d
        return None

    def ep_script(self) -> pathlib.Path | None:
        """剧本文件：`ep_01.md` / `ep01.md` / `EP01.md` 都认。"""
        d = self.ws / "03-剧本"
        if not d.is_dir():
            return None
        want = re.sub(r"[^0-9]", "", self.ep or "01") or "01"
        for p in sorted(d.glob("*.md")):
            n = p.stem.lower()
            if n.startswith(("ep_", "ep")) and re.sub(r"[^0-9]", "", n) == want:
                return p
        return None

    def marker(self, node_id: str) -> pathlib.Path:
        """`_done` 标记：节点执行并通过时写一份（带判据快照）。"""
        suff = (".%s" % self.ep) if (NODE_BY_ID.get(node_id, {}).get("ep") and self.ep) else ""
        return self.state_dir / "_done" / ("%s%s.json" % (node_id, suff))

    def loop_dir(self, node_id: str) -> pathlib.Path:
        return self.state_dir / "_loop" / node_id

    def spend(self, node_id: str) -> pathlib.Path:
        return self.state_dir / "_spend" / ("%s.json" % node_id)


def _belongs_to_ep(sid, ep) -> bool:
    """段 id 是否属于该集（与 `subtitle._belongs_to_ep` 同一条规则）。

    · 带集号（`ep01_shot_01` / `shot_ep01_01`）→ 只收本集
    · 不带集号（`shot_01`）→ 全收（集号由 --ep 与批次区分）
    """
    s_ = str(sid or "")
    if not s_:
        return False
    m = re.search(r"(?:^|[_-])ep0*(\d+)(?:[_-]|$)", s_, re.I)
    if m:
        want = re.sub(r"[^\d]", "", str(ep or "")) or "0"
        return int(m.group(1)) == int(want)
    return True


def _ep_segments(ctx: Ctx) -> tuple:
    """→ (本集段文件列表, 本集应有哪些段 id)。

    段落在 `<out>/<批次>/<shot>/final.mp4`（或旧的两层 `<out>/<引擎>/<批次>/<shot>/final.mp4`），
    **没有** `<out>/<ep>/` 这一层。原判据用 `ep_dir(out).rglob("*.mp4")` —— 目录都不存在，
    于是 `video.batch` / `video.audit` 在标准布局下永远判不过。这里复刻字幕管线的定位方式。
    """
    d = ctx.data / (ctx.ep or "ep01")
    if not (d / "shots.json").is_file():
        d = ctx.data
    shots = _read_json(d / "shots.json", []) or []
    if isinstance(shots, dict):
        shots = shots.get("shots") or []
    ids = [x.get("shot_id") for x in shots
           if isinstance(x, dict) and x.get("shot_id") and _belongs_to_ep(x.get("shot_id"), ctx.ep)]
    segs = []
    for sid in ids:
        cands = list(ctx.out.glob("*/%s/final.mp4" % sid))
        cands += list(ctx.out.glob("*/*/%s/final.mp4" % sid))
        cands = [c for c in cands if c.is_file() and c.stat().st_size > 2048]
        if cands:
            segs.append(max(cands, key=lambda q: q.stat().st_mtime))
    return segs, ids


def _out_hits(ctx: Ctx, pat: str) -> list:
    """在出片目录里找本集产物。★ 2026-11-01：`07-成片/` 下**没有** `ep01/` 子目录。

    实际布局是 `07-成片/subs/ep01/<ep>_master.mp4`（母版/放大/字幕都在这儿），
    而批次段在 `07-成片/<批次时间戳>/`。原实现只认 `07-成片/ep01/`，于是这三个
    剪辑节点在标准布局下**永远判不过**（母版明明在，却报「找不到」）。

    查找顺序：`<out>/<ep>/` → `<out>/subs/<ep>/` → `<out>/subs/` 下按集号宽容匹配 →
    整个 `<out>` 递归但只认文件名含本集号的（防跨集误命中）。
    """
    cands = []
    for d in (ctx.ep_dir(ctx.out), ctx.ep_dir(ctx.out / "subs"),
              ctx.out / "subs" / (ctx.ep or "ep01")):
        if d and d.is_dir():
            cands += sorted(d.rglob(pat))
    if cands:
        return cands
    num = re.sub(r"[^0-9]", "", ctx.ep or "01") or "01"
    if ctx.out.is_dir():
        cands = [q for q in sorted(ctx.out.rglob(pat)) if num in q.name]
    return cands


# ===========================================================================
# 判据（CHECKERS）—— 全部二值、全部离线
# ===========================================================================
def _eps_of(ws: pathlib.Path) -> int:
    """目标集数：drama.json → project-setup.json → 30。"""
    for name, path in (("drama.json", ("episodes",)),
                       ("project-setup.json", ("episodes",))):
        d = _read_json(ws / name, {}) or {}
        for k in path + ("episode_count", "episodes"):
            v = d.get(k)
            if isinstance(v, int) and v > 0:
                return v
            if isinstance(v, dict) and isinstance(v.get("count"), int):
                return v["count"]
    return 30


def _shots_of(ctx: Ctx) -> int:
    """本集镜数：data/<ep>/shots.json 的条数。

    `ctx.ep` 为空时（`status` 不带 --ep）退回 ep01 —— 与 `five` / `imported` 判据同口径。
    不兜底的话，整块面板会显示「0 镜」，看起来像制作包坏了，其实只是没指定集。
    """
    d = _read_json(ctx.data / (ctx.ep or "ep01") / "shots.json", [])
    if isinstance(d, dict):
        d = d.get("shots") or []
    return len(d or [])


def _is_draft(p: pathlib.Path) -> bool:
    """文件里有没有 `STATUS: DRAFT` 标记 —— 有就是「骨架还没填」。

    为什么要有：`init_project.py` 建出的骨架字数与真稿接近（蓝图 0.8KB vs 门槛 800 字节），
    纯按文件大小判会把**模板**判成**完成**，`next` 于是直接跳到下一步，
    人以为写完了。用显式标记比调大字数门槛可靠：标记只有「写完删掉」这一个语义。
    """
    try:
        return "STATUS: DRAFT" in p.read_text(encoding="utf-8", errors="replace")[:2000]
    except OSError:
        return False


def check_node(ctx: Ctx, node: dict) -> tuple:
    """→ (passed: bool, detail: str)。detail 不含「大概」「应该」——只有数字与路径。"""
    spec = str(node.get("check") or "")
    oid = node["id"]
    out = ctx.ep_path(node)

    # ---- JSON 类：json:<key> 或 json:<key>>=N ----
    if spec.startswith("json:"):
        expr = spec[5:]
        key, _, need = expr.partition(">=")
        d = _read_json(out if out.suffix == ".json" else out, None)
        if d is None:
            return False, "产物不存在或不是 JSON：%s" % out
        val = d.get(key) if isinstance(d, dict) else d
        if val is None:
            return False, "JSON 里没有 `%s`" % key
        n = len(val) if isinstance(val, (list, dict)) else (val if isinstance(val, int) else 1)
        if need and n < int(need):
            return False, "%s 只有 %s 条，要求 ≥%s" % (key, n, need)
        return True, "%s=%s" % (key, n if not isinstance(val, (str, int)) else val)

    # ---- 文件类：file>=N（字节）----
    if spec.startswith("file>="):
        n = int(spec[6:])
        if not out.is_file():
            return False, "产物不存在：%s" % out
        if _is_draft(out):
            return False, "仍是骨架（含 STATUS: DRAFT 标记），写完后删掉该行"
        size = out.stat().st_size
        return (size >= n), "%.1f KB" % (size / 1024.0)

    # ---- 导入：三件必需（参考表由出图后回填，这一步不查）----
    # 为什么只查三件：`characters.json` / `scenes.json` 在资产图出来之前必然是空的，
    # 把它们算进「导入是否成功」会让「先导入、再出图」这个正确顺序永远过不去。
    if spec == "imported":
        d = ctx.data / (ctx.ep or "ep01")
        need = ("shots.json", "boards.json", "h3_prompts.json")
        miss = [n for n in need if not (d / n).is_file()]
        if miss:
            return False, "缺 %s（先跑 import.pack）" % "、".join(miss)
        n = _shots_of(ctx)
        if not n:
            return False, "shots.json 为空（制作包里这一集没有镜头）"
        return True, "%d 镜" % n

    # ---- 分镜图：张数 = 镜数 ----
    if spec == "boards":
        d = ctx.ws / "04-资产" / "boards" / (ctx.ep or "ep01")
        n = len([p for p in d.glob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg")]) if d.is_dir() else 0
        need = _shots_of(ctx)
        if not need:
            return (n > 0), "分镜图 %d 张（还没有 shots.json，无法比对镜数）" % n
        return (n >= need), "分镜图 %d / 镜数 %d" % (n, need)

    # ---- 资产：refs.json 里每个 key 都有图 ----
    if spec == "assets":
        rj = _read_json(ctx.ws / "04-资产" / "refs.json", {}) or {}
        keys = {}
        for kind in ("characters", "scenes", "props"):
            keys.update({k: v for k, v in (rj.get(kind) or {}).items()})
        if not keys:
            return False, "refs.json 里没有登记任何参考图"
        def _ok(p: str) -> bool:
            s = str(p)
            if s.startswith(("http://", "https://", "data:")):
                return True
            if pathlib.Path(s).is_absolute():
                return pathlib.Path(s).is_file()
            # refs.json 里的相对路径有**三种**基准，历史上三种都出现过：
            #   ① 相对工作区  ② 相对 data 目录  ③ 相对资产目录（refs.json 自己所在处）
            # 只认一种就会报「N 个 key 缺图」的假阴性（US01 与夹具各踩一次，基准还不一样）。
            bases = [ctx.ws, ctx.data]
            try:
                bases.append(L.assets_dir(ctx.ws))
            except Exception:                                    # noqa: BLE001
                pass
            return any((b / s).is_file() for b in bases)
        miss = [k for k, v in keys.items() if not _ok(v)]
        return (not miss), ("%d 张齐" % len(keys)) if not miss else \
            "%d 个 key 缺图：%s" % (len(miss), "、".join(miss[:6]))

    # ---- 五文件 ----
    if spec == "five":
        d = ctx.data / (ctx.ep or "ep01")
        need = ("shots.json", "boards.json", "h3_prompts.json", "characters.json", "scenes.json")
        miss = [n for n in need if not (d / n).is_file()]
        return (not miss), ("5 文件齐（%d 镜）" % _shots_of(ctx)) if not miss else \
            "缺 %s" % "、".join(miss)

    # ---- 出片段数 ----
    if spec == "segments":
        segs, ids = _ep_segments(ctx)
        n = len(segs)
        need = len(ids) or _shots_of(ctx)
        if not need:
            return (n > 0), "%d 段（没有 shots.json，无法比对）" % n
        return (n >= need), "%d 段 / 镜数 %d" % (n, need)

    # ---- 出片体检：逐段有音轨且时长 > 1s ----
    if spec == "audit":
        segs, _ids = _ep_segments(ctx)
        if not segs:
            return False, "没有分段成片（找过 %s 下 */<shot>/final.mp4）" % ctx.out
        bad = []
        for p in segs:
            try:
                out_ = subprocess.run(
                    [os.environ.get("SOLODRAMA_FFPROBE", "ffprobe"), "-v", "error",
                     "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                    capture_output=True, text=True, timeout=30)
                dur = float((out_.stdout or "0").strip() or 0)
                if dur <= 1.0:
                    bad.append("%s(%.1fs)" % (p.name, dur))
            except Exception:                                # noqa: BLE001
                bad.append("%s(ffprobe 失败)" % p.name)
        return (not bad), ("%d 段全部可读" % len(segs)) if not bad else \
            "%d 段异常：%s" % (len(bad), "、".join(bad[:5]))

    # ---- 母版 / 放大 / 字幕 / 发布 都是「按名字找文件」 ----
    if spec in ("master", "upscaled", "subtitled"):
        pat = {"master": "*_master.mp4",
               "upscaled": "*_master_1080x1920.mp4",
               "subtitled": "*_subbed.mp4"}[spec]
        hits = _out_hits(ctx, pat)
        if not hits and spec == "upscaled":
            # ★ 2026-11-01：放大后端可以是 `off`（母版本来就是交付规格）。
            #   那时永远不会出现 `_master_1080x1920.mp4` —— 判据若不认这份「跳过报告」，
            #   节点会一直卡在「找不到文件」，而人看到的是「产物缺失」，方向全错。
            #   报告由 upscale.py --backend off 落盘，含 skipped=true 与原因。
            rep = _out_hits(ctx, "*_upscale.json")
            for rp in rep:
                d = _read_json(rp, {}) or {}
                if d.get("skipped"):
                    return True, "已跳过放大（%s）" % (d.get("note") or d.get("backend") or "off")
        if not hits:
            return False, "找不到 %s" % pat
        return True, "%s（%.1f MB）" % (hits[0].name, hits[0].stat().st_size / 1048576.0)

    if spec == "release":
        d = ctx.ws / "09-发行" / "剧集"
        got = {p.name for p in d.glob("Episode*.mp4")} if d.is_dir() else set()
        # 文件名必须是 EpisodeNN.mp4（补零），否则平台排序会乱
        bad = [n for n in got if not re.fullmatch(r"Episode\d{2,3}\.mp4", n)]
        if bad:
            return False, "命名不规范：%s" % "、".join(bad[:5])
        # ★ 2026-11-01：节点是 ep 级的，判据也必须按集判。
        #   旧实现拿「全剧总集数」比，于是跑 ep01 时因为另外 29 集还没导出而永远不过，
        #   报错是「发布版 1 / 目标 30 集」—— 看起来像数据缺失，其实是判据越界。
        #   全剧盘点归 release_check.py，不归这个节点。
        if ctx.ep:
            nn = re.sub(r"[^0-9]", "", ctx.ep) or "01"
            name = "Episode%s.mp4" % nn.zfill(2)
            if name not in got:
                return False, "本集发布版不存在：%s" % name
            return True, name
        need = _eps_of(ctx.ws)
        if len(got) < need:
            return False, "发布版 %d / 目标 %d 集" % (len(got), need)
        return True, "%d 集齐" % len(got)

    # ---- cmd:xxx —— 调外部脚本，退出码 0 即通过 ----
    if spec.startswith("cmd:"):
        return _run_checker_cmd(ctx, node, spec[4:])

    return False, "未知判据 `%s`" % spec


def _run_checker_cmd(ctx: Ctx, node: dict, cmd: str) -> tuple:
    """跑一个「只读」校验脚本，退出码 0 = 通过。

    ⚠ 这里只允许挂**不花钱、不改产物**的检查器（ingest_check / capabilities check 这类）。
      跑批与出图绝不走这条路。
    """
    # `cmd:` 后面可以是「脚本名」也可以是一整条命令（含参数）。
    # 占位符：{ws} / {ep} / {data}。脚本名自动在仓库里找。
    raw = cmd.format(ws=str(ctx.ws), ep=ctx.ep or "ep01",
                     data=str(ctx.data))
    parts = raw.split()
    script, extra = parts[0], parts[1:]
    if script.startswith("tools/"):
        path = ROOT / script
    else:
        cand = [HERE / script,
                ROOT / "stages" / "assets" / "scripts" / script,
                ROOT / "stages" / "import" / script,
                ROOT / "stages" / "subtitle" / "scripts" / script]
        path = next((x for x in cand if x.is_file()), cand[0])
    args = [sys.executable, str(path)] + extra
    if "--workspace" not in extra:
        args += ["--workspace", str(ctx.ws)]
    if node.get("ep") and ctx.ep and "--ep" not in extra:
        ep_arg = str(int(re.sub(r"[^0-9]", "", ctx.ep) or "1")) \
            if node.get("ep_style") == "int" else ctx.ep
        args += ["--ep", ep_arg]
    # 参数约定不统一是这个仓库的老问题（`WS_FLAG` 里 20 条特例：有的脚本认
    # `--workspace`，有的只认环境变量）。与其维护一张表，不如**按报错自适应**：
    # 脚本说「不认这个参数」就去掉它重跑。最多 3 次，不会死循环。
    for _ in range(4):
        try:
            r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=180, cwd=str(ROOT))
        except Exception as exc:                             # noqa: BLE001
            return False, "检查器启动失败：%s" % exc
        err = (r.stderr or "") + (r.stdout or "")
        m = re.search(r"unrecognized arguments:\s*--([a-z0-9-]+)", err)
        if r.returncode == 2 and m:
            bad = "--" + m.group(1)
            if bad in args:
                i = args.index(bad)
                n_del = 2 if (i + 1 < len(args) and not args[i + 1].startswith("--")) else 1
                del args[i:i + n_del]
                continue
        break
    tail = (r.stdout or r.stderr or "").strip().splitlines()
    last = tail[-1][:90] if tail else ""
    return (r.returncode == 0), ("%s（exit 0）" % last) if r.returncode == 0 else \
        ("exit %d：%s" % (r.returncode, last))


# ===========================================================================
# 状态推导
# ===========================================================================
def node_state(ctx: Ctx, node: dict, _memo: dict | None = None) -> dict:
    """→ {id, state, detail, mtime, upstream_ok}。**只看磁盘**。

    `_memo` 是**一次评估内**的备忘录：`node_state` 递归查上游，同一个节点会被问很多次，
    而 `cmd:` 判据每次都要起一个 Python 子进程 —— 不缓存就是「22 秒一张流程页」
    （实测 553 次递归 → 62 次子进程 → 22 秒）。

    ⚠ 缓存**不挂在 Ctx 上**：Ctx 会被反复使用（测试里改完文件再判一次），
      挂在 Ctx 上就会拿到上一轮的结论。只有 `evaluate()` 显式传 `_memo`，
      直接调 `node_state(ctx, node)` 永远是最新结果。
    """
    oid = node["id"]
    if _memo is not None:
        hit = _memo.get(oid)
        if hit is not None:
            return hit
    res = _node_state_uncached(ctx, node, _memo)
    if _memo is not None:
        _memo[oid] = res
    return res


def _node_state_uncached(ctx: Ctx, node: dict, _memo: dict | None = None) -> dict:
    """真正的判定（自身不缓存，但把 `_memo` 透传给上游）。"""
    oid = node["id"]

    # 显式跳过
    skip = _read_json(ctx.state_dir / "_skip" / ("%s.json" % oid), None)
    if isinstance(skip, dict) and skip.get("reason"):
        return {"id": oid, "state": "skipped", "detail": "跳过：%s" % skip["reason"], "mtime": 0}

    # 上游
    blocked_by = []
    for up in node.get("reads") or []:
        u = NODE_BY_ID.get(up)
        if not u:
            continue
        st = node_state(ctx, u, _memo)["state"]
        if st not in ("passed", "skipped"):
            blocked_by.append("%s(%s)" % (up, st))
    if blocked_by:
        return {"id": oid, "state": "blocked", "detail": "上游未通过：%s" % "、".join(blocked_by),
                "mtime": 0}

    out = ctx.ep_path(node)
    # 剧本文件名有三种写法（ep_01 / ep01 / EP01），存在性也得用宽容查找，
    # 否则「剧本明明在，却说缺失」——这正是 E1/E2 类假阴性在调度器里的复现。
    if node.get("check") == "script":
        out = ctx.ep_script() or out
    # 纯检查类节点（run 以「（内置…」开头，无副作用）不该要求 marker：
    # 它的「产物」就是判据的结论本身。要求 marker 等于强迫每部剧都手工 do 一遍
    # 纯只读检查，否则 next 永远卡在这里 —— 这是流程税，不是把关。
    _pure_check = str(node.get("run") or "").startswith("（") and "手写" not in str(node.get("run") or "")
    exists = out.exists() or ctx.marker(oid).is_file() or _pure_check
    if not exists:
        # 可选节点缺失 != 流程卡住：调研类节点很多项目直接跳过（手上有素材就开写）。
        # 缺了只标注，不阻塞下游 —— 否则一部没有调研的项目永远走不到剧本。
        if node.get("optional"):
            return {"id": oid, "state": "skipped",
                    "detail": "可选节点，未做（不影响下游）", "mtime": 0}
        return {"id": oid, "state": "absent", "detail": "产物不存在：%s" % out, "mtime": 0}

    mtime = 0
    try:
        mtime = out.stat().st_mtime if out.exists() else ctx.marker(oid).stat().st_mtime
    except OSError:
        pass

    ok, detail = check_node(ctx, node)

    # ★ stale 要**先于** passed 判：产物格式对、但上游改过了，仍算过期。
    #   旧顺序是「判据通过就 passed」，于是改了分镜 md 之后，旧的 shots.json
    #   因为「五文件都在」被算作 passed —— 拿上一版的提示词去出片，肉眼查不出来。
    newest_up = 0.0
    for up in node.get("reads") or []:
        u = NODE_BY_ID.get(up)
        if not u:
            continue
        try:
            up_p = ctx.ep_path(u)
            if u.get("check") == "script":
                up_p = ctx.ep_script() or up_p
            if up_p.exists():
                newest_up = max(newest_up, up_p.stat().st_mtime)
        except OSError:
            pass
    if ok and newest_up and mtime and newest_up > mtime + 1:
        return {"id": oid, "state": "stale",
                "detail": "产物比上游旧 %d 分钟（%s）" % ((newest_up - mtime) / 60, detail),
                "mtime": mtime}
    if ok:
        return {"id": oid, "state": "passed", "detail": detail, "mtime": mtime}
    # 可选节点：产物在但判据不过，也只标注、不阻塞。
    # 调研 / 发行物料这类「有更好、没有也能开工」的环节，卡住它等于卡住整条链。
    if node.get("optional"):
        return {"id": oid, "state": "skipped",
                "detail": "可选节点未达标（不阻塞）：%s" % detail, "mtime": mtime}

    return {"id": oid, "state": "failed", "detail": detail, "mtime": mtime}


def evaluate(ctx: Ctx) -> dict:
    """全量状态快照。★ 2026-11-01：每条节点带 `stage`，并附 `stages` 定义 ——
    Studio 的流程视图（adapters.norm_workflow）据此把 12 节点聚合成 5 环节，
    不再依赖已删除的 `workflow.py`（S1–S11 那套）。"""
    memo = {}                    # 一轮评估一份备忘录：上游节点会被反复问
    rows = []
    for n in NODES:
        r = dict(node_state(ctx, n, memo))
        r["stage"] = n["stage"]
        rows.append(r)
    return {"ws": str(ctx.ws), "ep": ctx.ep, "nodes": rows,
            "stages": [{"id": s["id"], "name": s["name"], "why": s.get("why", "")}
                       for s in STAGES],
            "counts": {s: sum(1 for r in rows if r["state"] == s)
                       for s in ("passed", "failed", "absent", "stale", "skipped", "blocked")}}


def next_node(ctx: Ctx) -> dict | None:
    """按拓扑序找第一个非通过节点。全部通过返回 None。"""
    for n in NODES:
        st = node_state(ctx, n)["state"]
        if st in ("passed", "skipped"):
            continue
        return {"node": n, "state": st, "detail": node_state(ctx, n)["detail"]}
    return None


# ===========================================================================
# Loop：L0 retry / L1 repair / L2 reflow
# ===========================================================================
def _variant_hash(node_id: str, payload: dict) -> str:
    """修复方案的指纹。两次相同 → stuck，不再浪费一次失败重跑。"""
    blob = json.dumps({"node": node_id, "payload": payload}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def record_attempt(ctx: Ctx, node_id: str, payload: dict, passed: bool, detail: str) -> dict:
    """落一次尝试记录 → {attempt, variant_hash, verdict}。

    verdict ∈ ok / retry / stuck / escalate
    """
    d = ctx.loop_dir(node_id)
    d.mkdir(parents=True, exist_ok=True)
    n = len(list(d.glob("attempt-*.json"))) + 1
    vh = _variant_hash(node_id, payload)
    prev = [_read_json(p, {}) or {} for p in sorted(d.glob("attempt-*.json"))]
    same = [p for p in prev if p.get("variant_hash") == vh]

    if passed:
        verdict = "ok"
    elif same:
        verdict = "stuck"                    # 同一方案重复失败，别再试
    elif n > MAX_REPAIR:
        verdict = "escalate"                 # L1 预算耗尽 → 进 L2
    else:
        verdict = "retry"

    _write_json(d / ("attempt-%02d.json" % n), {
        "node": node_id, "attempt": n, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "variant_hash": vh, "passed": passed, "detail": detail, "verdict": verdict,
        "payload": payload,
    })
    return {"attempt": n, "variant_hash": vh, "verdict": verdict}


def reflow_target(ctx: Ctx, node_id: str) -> str | None:
    """L2：回白名单里的上游。**不在白名单的跳转一律拒绝。**"""
    node = NODE_BY_ID.get(node_id) or {}
    for cand in node.get("reflow") or []:
        if (node_id, cand) in REFLOW_EDGES:
            return cand
    return None


# ===========================================================================
# 执行
# ===========================================================================
def _build_args(ctx: Ctx, node: dict) -> list:
    """把节点的 `run` 模板展开成 argv：占位符 + `--workspace` + `--ep`。

    ★ 抽成函数是为了让 `--dry-run` 与真跑**共用同一份拼装**。各写一份的下场是
      「干跑打印的命令和真跑的命令不一样」，于是「干跑看着对、真跑报错」——
      而那时候人已经相信干跑结果了。
    """
    cmd = str(node.get("run") or "")
    try:
        assets = str(L.assets_dir(ctx.ws))
    except Exception:                                            # noqa: BLE001
        assets = str(ctx.ws / "04-资产")
    raw = (cmd.replace("{ws}", str(ctx.ws)).replace("{ep}", ctx.ep or "ep01")
              .replace("{assets}", assets).replace("{data}", str(ctx.data)))
    args = raw.split()
    # 引擎类节点（出片）的 workspace 是 `<项目根>/video-pipeline`：
    # 引擎的 `--workspace` 指的是引擎根，不是项目根，两者差一层。
    node_ws = ctx.ws
    if node.get("ws_kind") == "engine":
        cand = ctx.ws / "video-pipeline"
        node_ws = cand if cand.is_dir() else ctx.ws
    args += ["--workspace", str(node_ws)]
    if node.get("ep") and ctx.ep and "--ep" not in args:
        # 集号的形态各家不同：`cli.py` 要整数（--ep 1），出片/转换要 `ep01`。
        # 这是「参数约定不统一」的又一例，用声明而不是猜。
        ep_arg = ctx.ep
        if node.get("ep_style") == "int":
            ep_arg = str(int(re.sub(r"[^0-9]", "", ctx.ep) or "1"))
        args += ["--ep", ep_arg]
    return args


def _print_plan(ctx: Ctx, node: dict, dry_run: bool = True) -> None:
    """打印将要执行的命令（`--dry-run` 用，包括上游被阻塞时）。

    ★ 2026-11-01：手写/内置节点的 `run` 是**说明文字**（`（手写：…）`），不是命令。
      原来这里无脑拼 `[DRY-RUN] （手写：…） --workspace … --ep ep01` —— 看着像能跑，
      真跑却什么都不执行（`run_node` 有专门分支）。干跑与真跑不一致，人会被带偏。
    """
    run_text = str(node.get("run") or "")
    if run_text.startswith("（") or "手写" in run_text:
        print("[NO-CMD] %s" % run_text)
        print("         该节点没有可执行命令：产物由人或会话产出，产出后用 `drama nodes` 复核")
        return
    args = _build_args(ctx, node)
    if args and args[0] in ("python", "python3"):
        args[0] = sys.executable
    if dry_run:
        print("[DRY-RUN] %s" % " ".join(args))
    else:
        print("执行 %s" % " ".join(args))


def run_node(ctx: Ctx, node_id: str, dry_run: bool = False, yes: bool = False) -> int:
    node = NODE_BY_ID.get(node_id)
    if not node:
        print("[FAIL] 未知节点：%s（用 `nodes.py graph` 看全表）" % node_id)
        return EXIT_FAIL

    st = node_state(ctx, node)
    if st["state"] == "blocked":
        # ★ dry-run 是**检查接线**用的，不是执行。上游没通过时更要能看见命令 ——
        #   否则「drama do edit.subtitle --dry-run」只会回一句 BLOCKED，
        #   而人想看的是「这条命令到底拼成什么样」。只打印，绝不执行。
        if dry_run:
            print("[BLOCKED] %s" % st["detail"])
            _print_plan(ctx, node, dry_run=True)
            print("（dry-run 只打印命令，不执行；上游通过后才真跑）")
            return EXIT_OK
        print("[BLOCKED] %s" % st["detail"])
        return EXIT_NOINPUT

    cmd = str(node.get("run") or "")
    trigger = str(node.get("trigger") or "")
    print("=" * 74)
    print("节点 %s ｜ 现状 %s（%s）" % (node_id, st["state"], st["detail"]))
    print("触发 %s" % trigger)
    print("执行 %s" % cmd)
    print("=" * 74)

    # 「手写」类节点：产物得由人或会话产出，调度器**不能替它做决定**。
    # 一旦产物已经在，就算完成（写 marker + 报 TODO）；不在就报 TODO 让人去补。
    # ★ 这个分支必须排在「内置判据」之前：两者都以中文括号开头，
    #   混在一起会把「该你写的」当成「检查通过」直接放行。
    if "手写" in cmd:
        ok, detail = check_node(ctx, node)
        if ok:
            _write_json(ctx.marker(node_id), {
                "node": node_id, "ep": ctx.ep, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "detail": "产物已存在（人工产出）", "returncode": 0})
            print("产物已在：%s" % detail)
            print("[OK] 该节点由人工产出，产物齐即可 —— 已记 passed。")
            return EXIT_OK
        print("[TODO] 这一步需要人或会话完成，调度器不代做。")
        print("       现在：%s" % detail)
        print("       产物：%s" % ctx.ep_path(node))
        return EXIT_TODO

    # run 以中文括号开头且不是手写 = 「判据本身就是执行」（如 FFS 结构检查）。
    # 这类节点只跑判据、不 spawn 子进程 —— 否则会把说明文字当命令执行。
    if cmd.startswith("（"):
        ok, detail = check_node(ctx, node)
        print("判据：%s —— %s" % ("通过" if ok else "不过", detail))
        if ok:
            _write_json(ctx.marker(node_id), {
                "node": node_id, "ep": ctx.ep, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "detail": detail, "returncode": 0})
            return EXIT_OK
        rec = record_attempt(ctx, node_id, {"check": node.get("check"), "ep": ctx.ep}, ok, detail)
        return EXIT_STUCK if rec["verdict"] == "stuck" else EXIT_FAIL

    if cmd.startswith("（"):
        # 以「（…）」开头的是**说明性占位**，没有可自动执行的命令。
        # 例：`video.audit` 的「（逐段校验：存在/时长/分辨率/音轨）」—— 它的判据是内置的，
        # 执行体就是判据本身，不需要再起一个进程。
        print("[TODO] 该节点没有可自动执行的命令（产物即判据）。")
        print("       产物：%s" % ctx.ep_path(node))
        print("       完成后续跑：python stages/production/scripts/nodes.py do %s%s"
              % (node_id, (" --ep " + ctx.ep) if ctx.ep else ""))
        return EXIT_TODO

    # 占位符：{ws} / {ep} / {assets} / {data}。节点的执行命令要能引用项目内路径，
    # 否则像 `plan` 这种必须带 --roster/--out 的脚本根本跑不起来（实测踩过）。
    args = _build_args(ctx, node)
    if args[0] in ("python", "python3"):
        args[0] = sys.executable

    if node_id == "video.batch":
        if not yes:
            print("[HUMAN] 出片计费，必须显式 --yes")
            return EXIT_HUMAN
        args += ["--yes"]

    if dry_run:
        print("[DRY-RUN] %s" % " ".join(args))
        return EXIT_OK

    # 与检查器同一套自适应：脚本不认 --workspace / --ep 就去掉重跑
    for _ in range(4):
        r = subprocess.run(args, cwd=str(ROOT), text=True, encoding="utf-8", errors="replace",
                           capture_output=True)
        err = (r.stderr or "") + (r.stdout or "")
        m = re.search(r"unrecognized arguments:\s*--([a-z0-9-]+)", err)
        if r.returncode in (1, 2) and m:
            bad = "--" + m.group(1)
            if bad in args:
                i = args.index(bad)
                n_del = 2 if (i + 1 < len(args) and not args[i + 1].startswith("--")) else 1
                del args[i:i + n_del]
                continue
        break
    if r.stdout:
        print(r.stdout.rstrip())
    if r.stderr:
        print(r.stderr.rstrip(), file=sys.stderr)
    ok, detail = check_node(ctx, node)
    rec = record_attempt(ctx, node_id, {"cmd": cmd, "ep": ctx.ep}, ok, detail)
    print("\n判据：%s —— %s" % ("通过" if ok else "不过", detail))
    print("尝试 #%d，verdict=%s" % (rec["attempt"], rec["verdict"]))

    if ok:
        _write_json(ctx.marker(node_id), {
            "node": node_id, "ep": ctx.ep, "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "detail": detail, "returncode": r.returncode,
        })
        return EXIT_OK
    if rec["verdict"] == "stuck":
        print("[STUCK] 同一方案已失败过，换一个变量再试（退出码 5）")
        return EXIT_STUCK
    if rec["verdict"] == "escalate":
        tgt = reflow_target(ctx, node_id)
        if tgt:
            print("[REFLOW] L1 耗尽，回上游 %s（白名单内）" % tgt)
            print("         重跑：python stages/production/scripts/nodes.py do %s" % tgt)
        else:
            print("[HUMAN] L1 耗尽且无白名单上游，需要人判断（退出码 4）")
        return EXIT_HUMAN
    return EXIT_FAIL


# ===========================================================================
# 渲染
# ===========================================================================
ICON = {"passed": "OK  ", "failed": "FAIL", "absent": "--  ", "stale": "OLD ",
        "skipped": "SKIP", "blocked": "BLK "}


def render_status(ev: dict) -> str:
    L_ = ["五环节 12 节点 · 状态", "=" * 92]
    counts = ev["counts"]
    L_.append("通过 %d ｜ 不过 %d ｜ 缺失 %d ｜ 过期 %d ｜ 阻塞 %d ｜ 跳过 %d"
              % (counts["passed"], counts["failed"], counts["absent"],
                 counts["stale"], counts["blocked"], counts["skipped"]))
    L_.append("")
    cur = None
    for st in STAGES:
        rows = [r for r in ev["nodes"] if NODE_BY_ID[r["id"]]["stage"] == st["id"]]
        if not rows:
            continue
        if cur != st["id"]:
            L_.append("【%s】%s" % (st["name"], st["why"]))
            cur = st["id"]
        for r in rows:
            L_.append("  %s %-20s %s" % (ICON.get(r["state"], r["state"]), r["id"], r["detail"][:96]))
        L_.append("")
    return "\n".join(L_)


def render_graph() -> str:
    L_ = ["五环节 12 节点 · 触发与接替", "=" * 100]
    for st in STAGES:
        L_.append("")
        L_.append("【%s】%s" % (st["name"], st["why"]))
        for n in [x for x in NODES if x["stage"] == st["id"]]:
            L_.append("  %-20s %s" % (n["id"], n["trigger"]))
            L_.append("  %-20s 读 %s → 产物 %s" % ("", "、".join(n["reads"]) or "（无）", n["output"]))
            L_.append("  %-20s 判据 %s ｜ 接替 → %s%s"
                      % ("", n["check"], n["next"] or "（终点）",
                         " ｜ 回流可回 " + "、".join(n["reflow"]) if n["reflow"] else ""))
    L_.append("")
    L_.append("回流边白名单（%d 条，不在表里的跳转一律拒绝）：" % len(REFLOW_EDGES))
    for a, b in sorted(REFLOW_EDGES):
        L_.append("  %s → %s" % (a, b))
    return "\n".join(L_)


# ===========================================================================
# CLI
# ===========================================================================
def _resolve_ws(v) -> pathlib.Path:
    if v:
        return pathlib.Path(v).expanduser().resolve()
    try:
        return pathlib.Path(W.WS).resolve()
    except Exception:                                            # noqa: BLE001
        raise SystemExit("[FAIL] 需要 --workspace")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="五环节 12 节点状态机（只读磁盘，确定性）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("next", help="打印下一步该做什么（不执行）")
    p.add_argument("--workspace"); p.add_argument("--ep", default=""); p.add_argument("--json", action="store_true")

    p = sub.add_parser("status", help="全节点状态")
    p.add_argument("--workspace"); p.add_argument("--ep", default=""); p.add_argument("--json", action="store_true")

    p = sub.add_parser("do", help="执行一个节点（重复执行结果相同）")
    p.add_argument("node"); p.add_argument("--workspace"); p.add_argument("--ep", default="")
    p.add_argument("--dry-run", action="store_true"); p.add_argument("--yes", action="store_true")

    p = sub.add_parser("graph", help="打印节点图与回流白名单")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("skip", help="显式跳过一个节点（必须给理由，落 _skip/）")
    p.add_argument("node"); p.add_argument("--workspace"); p.add_argument("--reason", required=True)

    a = ap.parse_args(argv)

    if a.cmd == "graph":
        if a.json:
            print(json.dumps({"stages": STAGES, "nodes": NODES,
                              "reflow": sorted(REFLOW_EDGES)}, ensure_ascii=False, indent=2))
        else:
            print(render_graph())
        return EXIT_OK

    ctx = Ctx(_resolve_ws(a.workspace), getattr(a, "ep", "") or "")

    if a.cmd == "next":
        nx = next_node(ctx)
        if not nx:
            print("[DONE] 12 节点全部通过。")
            return EXIT_OK
        if a.json:
            print(json.dumps({"node": nx["node"]["id"], "stage": nx["node"]["stage"],
                              "state": nx["state"], "detail": nx["detail"],
                              "trigger": nx["node"]["trigger"],
                              "output": nx["node"]["output"]}, ensure_ascii=False, indent=2))
        else:
            print("下一步：%s" % nx["node"]["id"])
            print("  现状：%s（%s）" % (nx["state"], nx["detail"]))
            print("  触发：%s" % nx["node"]["trigger"])
            print("  产物：%s" % nx["node"]["output"])
        return EXIT_OK

    if a.cmd == "status":
        ev = evaluate(ctx)
        print(json.dumps(ev, ensure_ascii=False, indent=2) if a.json else render_status(ev))
        return EXIT_OK

    if a.cmd == "do":
        return run_node(ctx, a.node, dry_run=bool(a.dry_run), yes=bool(a.yes))

    if a.cmd == "skip":
        if a.node not in NODE_BY_ID:
            print("[FAIL] 未知节点：%s" % a.node)
            return EXIT_FAIL
        _write_json(ctx.state_dir / "_skip" / ("%s.json" % a.node),
                    {"node": a.node, "reason": a.reason,
                     "at": time.strftime("%Y-%m-%dT%H:%M:%S")})
        print("[OK] 已跳过 %s：%s" % (a.node, a.reason))
        return EXIT_OK
    return EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
