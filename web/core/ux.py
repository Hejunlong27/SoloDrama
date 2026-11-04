# -*- coding: utf-8 -*-
"""ux.py —— 用户语言层（面向「做短剧的人」，不是面向开发者）

定位
----
Web 控制台有**两张脸**，本模块是「用户端」那一张的脸面层：

  用户端（web/ui/index.html）      开发者端（web/ui/advanced.html）
  ─────────────────────────────    ─────────────────────────────
  「我的短剧」                      工作区 / workspace
  「今天建议做这个」                下一步命令 + 门禁代号
  「这一步要跑约 6 分钟」            单段耗时、G5 闸门
  「正在做：第 3 集的画面」          作业 job / 批次 batch id
  「有几处要先修好」                退出码 2

原则
----
1. **只翻译，不决策**：所有事实来自引擎（读文件 / 读 CLI 的 `--json`），本层只把它们换成
   用户能懂的话、并组织成「任务」。
2. **不暴露实现细节**：不出现 argv、退出码、门禁代号、批次号、金额小数、工作区路径。
3. **用户端与开发者端共用同一套后端接口**：用户端只用 `/api/home`、`/api/tasks`、
   `/api/episodes`、`/api/help`；开发者端才用 `/api/commands`、`/api/audit`、`/api/locks`。
"""
from __future__ import annotations

import json
from pathlib import Path

from . import commands as CMD
from . import inventory
from . import reader

# ---------------------------------------------------------------------------
# 术语对照（也用于界面「这是什么？」的说明）
# ---------------------------------------------------------------------------
GLOSSARY = [
    ("画风", "整部剧的呈现方式（3D 漫剧 / 2D 动画 / 真人出演）。一开始就要定，之后换画风会让已做好的素材全部作废。"),
    ("出图通道", "让电脑「画」角色和场景的方式：用你自己这台电脑（免费，但会占用电脑）。"),
    ("镜头", "一集里的一小段画面（通常 4–15 秒）。一集通常由 5–12 个镜头拼成。"),
    ("本次生成", "一次「把这些镜头交给本机做」的动作。做坏了重做不额外花钱。"),
    ("发布前检查", "正式发布前必须回答的几个问题（画面里有没有不宜出现的内容等），不通过就不能发布。"),
    ("AI 标注", "用 AI 还原真实人物或场景时，平台要求明确标注，否则会被减少推荐。"),
]

# 6 个「用户阶段」← 由 15 个引擎环节归并（用户不需要知道 15 个环节）
USER_STAGES = [
    {"key": "setup", "name": "配通道", "rounds": ["0"],
     "hint": "确认出图、出片、放大分别走哪条通道（一次配好，全季复用）"},
    {"key": "import", "name": "导入", "rounds": ["1"],
     "hint": "把创作 Skill 做好的制作包交给引擎"},
    {"key": "cast", "name": "出图", "rounds": ["2"],
     "hint": "批量出角色、场景、道具的形象图"},
    {"key": "boards", "name": "分镜图", "rounds": ["3"],
     "hint": "每个镜头一张首帧，出片时当作构图锚"},
    {"key": "shoot", "name": "出片", "rounds": ["4"],
     "hint": "把镜头做成真正的画面"},
    {"key": "deliver", "name": "成片发行", "rounds": ["5", "6"],
     "hint": "接成整集、放大、加字幕、导出发布版"},
]

# 用户可见状态（不是 todo/doing/blocked 这些工程词）
STATE_TEXT = {
    "done": "已完成",
    "doing": "正在做",
    "blocked": "需要你先做一步",
    "todo": "还没开始",
}

COIN_TO_CNY = 0.0025
COIN_PER_SHOT = 145
USD_TO_CNY = 7.2          # 仅用于把「美元钱包消耗」折算成人民币展示，界面上会注明是估算


def yuan(v) -> str:
    """把人民币金额写成人话（小额保留两位、大额取整；四舍五入按「半数进位」，避免 1234.5 变成 1234）。"""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—"
    if v == 0:
        return "¥0"
    if v < 0:
        return "—"
    if v < 100:
        return "¥%.2f" % v
    return "¥%d" % int(v + 0.5)


def coins_to_yuan(coins) -> str:
    try:
        return yuan(float(coins) * COIN_TO_CNY)
    except (TypeError, ValueError):
        return "—"


def human_state(state: str) -> str:
    return STATE_TEXT.get(state, state)


# ---------------------------------------------------------------------------
# 用户任务（把「命令」组织成「用户要做的事」）
# ---------------------------------------------------------------------------
class Task:
    """一个「用户要做的事」。`ui` 决定界面上怎么问用户，`spec_ids` 决定实际调用哪些引擎动作。"""

    def __init__(self, tid, title, why, how, spec_ids=(), stage="", needs_confirm=False,
                 cost_hint="", after="", ui=None):
        self.id = tid
        self.title = title
        self.why = why
        self.how = how
        self.spec_ids = list(spec_ids)
        self.stage = stage
        self.needs_confirm = needs_confirm
        self.cost_hint = cost_hint
        self.after = after
        self.ui = ui or {"kind": "sequence", "steps": [{"spec": s, "label": "开始"} for s in spec_ids]}

    def as_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "why": self.why, "how": self.how,
                "stage": self.stage, "needs_confirm": self.needs_confirm,
                "cost_hint": self.cost_hint, "after": self.after,
                "spec_ids": self.spec_ids, "ui": self.ui}


# 画风选项（用户语言；值与引擎枚举一致，绝不臆造）
STYLE_OPTIONS = [
    {"value": "3d_manhua", "title": "3D 漫剧",
     "desc": "像动画剧集，画面精致，适合玄幻 / 都市 / 逆袭题材", "recommend": True},
    {"value": "2d_animation", "title": "2D 动画",
     "desc": "手绘动漫风，出片更快，适合轻松、搞笑、恋爱题材"},
    {"value": "live_action", "title": "真人出演",
     "desc": "接近真人短剧；用 AI 还原真人时平台要求标注，否则减少推荐"},
]

# 机器选项（用户语言）
#   不是「隐藏」而是删掉 —— 留一个选不动的选项比没有更让人困惑。
#   `closed_model` 也去掉了：它没有引擎执行路径，选它等于承诺一件做不到的事。
IMAGE_MACHINE_OPTIONS = [
    {"value": "local_comfyui", "title": "这台电脑（免费）",
     "desc": "不花钱，但会占用电脑；出图时电脑会比较忙", "recommend": True},
]
VIDEO_MACHINE_OPTIONS = [
    {"value": "local_comfyui", "title": "这台电脑（免费）",
     "desc": "占本机 GPU，一集通常几十分钟；不联网、不产生费用", "recommend": True},
]

TASKS = [
    Task("choose_machine", "选择用哪台机器做画面", "这一步决定后面要不要花钱",
         "出图、出片、放大可以分别选；一次配好，全季复用", ["models.list", "models.set"], stage="setup",
         after="接下来把创作 Skill 做好的制作包导进来",
         ui={"kind": "dual_choice", "spec": "models.set",
             "groups": [{"label": "画角色和场景的形象", "key": "image", "options": IMAGE_MACHINE_OPTIONS},
                        {"label": "把镜头做成画面", "key": "video", "options": VIDEO_MACHINE_OPTIONS}]}),
    Task("import_pack", "把制作包交给引擎",
         "选题、剧本、资产设计、导演、分镜、提示词都在创作 Skill 里完成；引擎只负责把它们做出来",
         "把制作包放进这部剧的 pack/ 目录，先校验、再导入", ["pack.check", "pack.import"],
         stage="import", after="导入成功后开始批量出图",
         ui={"kind": "sequence", "steps": [
             {"spec": "pack.check", "label": "先校验制作包（只读，不写盘）", "free": True},
             {"spec": "pack.import", "label": "导入并生成 data/ 契约"},
         ]}),
    Task("cast_assets", "给角色和场景定形象", "形象定好之后，每个镜头里的长相才能保持一致",
         "先看要画哪些，再决定用哪台机器画", ["assets.check", "assets.local"],
         stage="cast", cost_hint="用这台电脑画不花钱，只占 GPU", after="接下来把剧本拆成分镜",
         ui={"kind": "sequence", "steps": [
             {"spec": "assets.check", "label": "先检查画图工具", "free": True, "next": "清单"},
             {"spec": "assets.local", "label": "用这台电脑画（免费）", "params": {"kind": "all"}},
         ]}),
    Task("draw_boards", "给每个镜头画一张首帧", "首帧决定这一镜的构图、站位和光线，出片时当第一张参考图",
         "一集一集画，缺哪镜会列出来", ["board.frame"], stage="boards",
         cost_hint="用这台电脑画不花钱，只是占 GPU", after="首帧齐了就能批量出片",
         ui={"kind": "sequence", "steps": [
             {"spec": "board.frame", "label": "画这一集的分镜图", "params": {"ep": "{ep}"}},
         ]}),
    Task("make_episode", "做出这一集的画面", "这是最花时间的一步，做完就能看到活动的剧",
         "先算清楚要跑多久，你同意后再交给本机生成",
         ["video.plan", "video.run"], stage="shoot", needs_confirm=True,
         cost_hint="按镜头数量排期，开始前会显示预计耗时", after="做完可以逐段预览",
         ui={"kind": "plan_then_run", "plan_spec": "video.plan", "run_spec": "video.run",
             "params": {"limit": None},
             "confirm_title": "现在开始生成画面", "free_label": "先排一下要跑多久（不占 GPU）"}),
    Task("finish_episode", "拼成完整一集（含字幕）", "把分散的镜头接成能直接看的完整一集",
         "先把镜头接起来并提升清晰度，然后问你要不要加字幕",
         # ★ 2026-11-01：剪辑已定为三步（拼接母版 → 高清放大 → 字幕），
         #   旧的 `media.assemble`（拼接+放大合一）已删。
         ["media.master", "media.upscale", "media.render"], stage="deliver",
         cost_hint="不额外花钱，但会占用电脑一段时间（放大最久，约 8–10 分钟/集）",
         after="这一集就完整了",
         ui={"kind": "sequence", "steps": [
             {"spec": "media.master", "label": "① 接成完整一集（封面 + 片段 + BGM）", "params": {}},
             {"spec": "media.upscale", "label": "② 提升清晰度（会占用电脑）", "params": {}},
             {"spec": "media.render", "label": "③ 加字幕（可选）", "params": {"burn": True}, "optional": True},
         ]}),
    Task("review_episode", "看看这一集做得怎么样", "确认画面和字幕没问题，再决定发不发",
         "打开成片播放，逐集检查", ["report.batch"], stage="deliver",
         after="没问题就去发布前检查",
         ui={"kind": "sequence", "steps": [{"spec": "report.batch", "label": "整理这一集的制作情况"}]}),
    Task("publish_check", "发布前检查", "平台要求检查内容合规，过了才能发布",
         "回答 3 个问题，系统告诉你能不能发", ["compliance.ep", "compliance.all"],
         stage="deliver", after="通过后就能导出发布",
         ui={"kind": "questions", "spec": "compliance.ep", "field_prefix": "q",
             "questions": [
                 {"key": "q1", "text": "画面里有没有出现具体的做法或步骤？"},
                 {"key": "q2", "text": "有没有出现可能被误认为真实人物的画面（含背景、倒影、屏幕里）？"},
                 {"key": "q3", "text": "有没有穿校服、童装风格等可能引起身份误解的画面？"},
             ],
             "fields": [{"key": "ep", "label": "检查哪一集", "placeholder": "ep01"}]}),
    Task("start_drama", "开始一部新短剧", "先建一个属于这部剧的文件夹，后面的东西都放里面",
         "填写剧名、集数和目标平台", ["project.scaffold"], stage="idea", after="接着选画风",
         ui={"kind": "form", "spec": "project.scaffold",
             "fields": [{"key": "target", "label": "放在电脑里的哪个位置", "placeholder": "D:/剧本/我的新剧", "required": True},
                        {"key": "slug", "label": "英文短名（用于文件名）", "placeholder": "my-new-drama", "required": True},
                        {"key": "title", "label": "剧名", "placeholder": "我的新剧", "required": True},
                        {"key": "platform", "label": "目标平台", "placeholder": "TikTok"},
                        {"key": "ep", "label": "计划做几集", "kind": "int", "default": 40},
                        {"key": "sec", "label": "每集大约多少秒", "kind": "int", "default": 70}]}),
]

TASK_BY_ID = {t.id: t for t in TASKS}


def _cmd_exists(spec_id: str) -> bool:
    return CMD.get(spec_id) is not None


# ---------------------------------------------------------------------------
# 数据整形
# ---------------------------------------------------------------------------
def stage_progress(pipeline_rounds) -> list:
    """把 15 环节的看板压缩成 6 个用户阶段。"""
    by_no = {r["no"]: r for r in (pipeline_rounds or [])}
    out = []
    for st in USER_STAGES:
        rs = [by_no[n] for n in st["rounds"] if n in by_no]
        if not rs:
            state = "todo"
        elif any(r["state"] == "blocked" for r in rs):
            state = "blocked"
        elif all(r["state"] == "done" for r in rs):
            state = "done"
        elif any(r["state"] in ("doing", "done") for r in rs):
            state = "doing"
        else:
            state = "todo"
        out.append({"key": st["key"], "name": st["name"], "hint": st["hint"],
                    "state": state, "state_text": human_state(state)})
    return out


def user_problems(ws) -> list:
    """把「需要用户动手的事」翻译成人话（用户端唯一的问题呈现方式）。"""
    out = []
    ov = reader.overview(ws)
    for a in ov.get("next_actions") or []:
        text = a.get("text") or ""
        if "画风" in text:
            # 画风不再由引擎选；它来自制作包的 style_lock（创作 Skill 定的）。
            out.append({"kind": "action", "title": "还没导入制作包",
                        "detail": "画风写在制作包的 style_lock 里；导入之后这里就不再提示。",
                        "task": "import_pack"})
        elif "通道确认" in text or "G0" in text:
            out.append({"kind": "action", "title": "还没有选择用哪台机器做画面",
                        "detail": "这一步决定后面要不要花钱。",
                        "task": "choose_machine"})
        elif "缺资产" in text:
            out.append({"kind": "action", "title": "角色和场景的形象还没画好",
                        "detail": text.split("→")[0].strip(),
                        "task": "cast_assets"})
        elif "参考图超过" in text or "5760" in text:
            out.append({"kind": "action", "title": "有图片尺寸过大，需要先处理",
                        "detail": "尺寸超过限制的图片会导致生成失败或错位，系统可以自动处理。",
                        "task": "cast_assets"})
        elif "G2 未就绪" in text or "工作流" in text:
            out.append({"kind": "warning", "title": "出片环境还没配好",
                        "detail": "缺少出片工作流文件，无法提交生成。这属于技术配置，可点「高级工具」处理。",
                        "task": ""})
        elif "段失败" in text:
            out.append({"kind": "action", "title": "有镜头没做成功，可以重做",
                        "detail": "重做不额外花钱，系统只会补做失败的部分。",
                        "task": "make_episode"})
    return out


def spent_summary(ws, status_data=None) -> dict:
    """「花了多少钱」+「做了多少东西」——用户端的花费卡数据。

    ★ 口径修复（2026-10-17）：只读 `ledger` 会漏掉部分生成记录的用量
      （实测《亿万丈夫的三个月合约》12 个任务 / 170 点未进台账 → 界面显示 ¥0）。
      现改为 `inventory` 聚合：台账优先、生成记录兜底、按 taskId 去重，并标注来源。
    """
    inv = inventory.inventory(ws)
    sp = inv["spend"]
    cny = sp["coins"] * COIN_TO_CNY + sp["usd"] * USD_TO_CNY
    imgs = inv["images"]

    lines = []
    if imgs["total"]:
        parts = []
        for k, label in (("characters", "角色"), ("scenes", "场景"), ("props", "道具")):
            if imgs.get(k):
                parts.append("%s %d 张" % (label, imgs[k]))
        lines.append({"label": "角色和场景的图", "value": " · ".join(parts)})
    if inv["refs"]:
        lines.append({"label": "用来对照的参考图", "value": "%d 张" % inv["refs"]})
    # ★ 散图单列一行：真实项目把图直接放剧目录根下（不进 04-资产），
    #   只报「已归档资产」会让用户以为自己的图没了。数字与资产页「散图」页签同源。
    if imgs.get("loose"):
        lines.append({"label": "还没归档的图（散图）",
                      "value": "%d 张 · 资产页「散图」里能看到" % imgs["loose"]})
    if inv["clips"]:
        lines.append({"label": "已做出的镜头", "value": "%d 段" % inv["clips"]})
    if inv["renders"]:
        lines.append({"label": "已拼好的整集", "value": "%d 集" % inv["renders"]})
    if sp["workflow_hits"] or sp["ledger_hits"]:
        lines.append({"label": "生成次数", "value": "%d 次" % (sp["ledger_hits"] + sp["workflow_hits"])})

    note = sp["source_text"] or ("按平台实际用量统计" if cny else "")
    if sp["usd"]:
        note = (note + "；" if note else "") + "美元部分按 1 美元 ≈ ¥%.1f 估算" % USD_TO_CNY

    return {
        "text": yuan(cny),
        "coins": sp["coins"],
        "usd": sp["usd"],
        "tasks": sp["tasks"],
        "images": imgs,
        "refs": inv["refs"],
        "clips": inv["clips"],
        "lines": lines,
        "note": note,
        "source": sp["source"],
        "ledger_incomplete": sp["source"] in ("workflow", "mixed"),
        "has_output": inv["has_output"],
        "updated_text": inv["updated_text"],
    }


def _title(name: str) -> str:
    """剧名加书名号（文件夹名已带《》时不重复加）。"""
    n = (name or "").strip()
    if n.startswith("《") and n.endswith("》"):
        return n
    return "《%s》" % n


def switch_hint(ws) -> dict:
    """当前这部剧还没有产出、而本机别的剧有产出时，提示用户切换（防「在 A 里找 B 的图」）。"""
    me = inventory.inventory(ws)
    if me["has_output"]:
        return {}
    try:
        me_path = str(Path(ws).resolve())
    except OSError:
        me_path = str(ws)
    best = None
    for it in inventory.discover().get("items") or []:
        try:
            if str(Path(it["path"]).resolve()) == me_path:
                continue
        except (OSError, ValueError):
            continue
        if it.get("images") and (best is None or it["images"] > best["images"]):
            best = it
    if not best:
        return {}
    return {
        "kind": "switch",
        "title": "你在看的这部剧还没有产出，但另一部已经有了",
        "detail": "%s 已生成 %d 张图，花费约 %s。要切过去看看吗？"
                  % (_title(best["name"]), best["images"], yuan(best["yuan"])),
        "path": best["path"],
        "name": best["name"],
    }


def _pack_style(ws) -> str:
    """从制作包读画风锁（`pack/pack.json` 的 `style_lock`）。

    为什么不在引擎里放一份画风清单：画风是创作决策，写在包里等于「谁做的谁负责」；
    引擎里留一份选项列表，迟早会出现「单子上有 A、实际出了 B」的账实不符。
    读不到就返回空串 —— 界面上显示「还没导入制作包」，而不是编一个默认画风出来。
    """
    try:
        p = Path(ws) / "pack" / "pack.json"
        if not p.is_file():
            return ""
        doc = json.loads(p.read_text(encoding="utf-8-sig")) or {}
        s = str(doc.get("style_lock") or "").strip()
        return (s[:40] + "…") if len(s) > 40 else s
    except (OSError, json.JSONDecodeError, ValueError):
        return ""


def _drama_name(ws, info) -> str:
    try:
        p = Path(ws)
        for f in ("project.json", "creation/brief.json"):
            d = reader.paths.read_json(p / f, default=None)
            if isinstance(d, dict):
                for k in ("title", "name", "drama", "slug"):
                    if d.get(k):
                        return str(d[k])
        return p.name
    except Exception:  # noqa: BLE001
        return str(ws)


def episodes(status_data, out_dir) -> list:
    """按集聚合（镜头 id 前缀 epNN_）。"""
    eps = {}
    for b in (status_data or {}).get("batches") or []:
        for sh in b.get("shots") or []:
            sid = sh.get("shot_id") or ""
            ep = sid.split("_")[0] if "_" in sid else "其他"
            e = eps.setdefault(ep, {"ep": ep, "total": 0, "ok": 0, "fail": 0, "pending": 0})
            e["total"] += 1
            st = (sh.get("video_status") or sh.get("status") or "").lower()
            if st in ("success", "succeeded", "ok"):
                e["ok"] += 1
            elif st in ("failed", "fail", "error"):
                e["fail"] += 1
            else:
                e["pending"] += 1
    out = []
    for ep, e in eps.items():
        if e["ok"] and not e["fail"] and e["ok"] == e["total"]:
            state, text = "done", "画面已完成"
        elif e["fail"]:
            state, text = "blocked", "%d 个镜头没做成功" % e["fail"]
        elif e["ok"]:
            state, text = "doing", "已完成 %d/%d 个镜头" % (e["ok"], e["total"])
        else:
            state, text = "todo", "还没开始做画面"
        out.append({**e, "state": state, "state_text": text})
    return sorted(out, key=lambda x: x["ep"])


def _rounds(ws):
    return reader.pipeline(ws).get("rounds") or []


def next_task(ws) -> dict:
    """给出「今天建议做这个」——用户端的主行动按钮。"""
    rounds = {r["no"]: r["state"] for r in _rounds(ws)}
    pl = {s["key"]: s["state"] for s in stage_progress(_rounds(ws))}

    # ★ 2026-11-02 分支 feat/pack-engine：创作环节已移出引擎，主行动链只剩五步。
    #   顺序是有依赖的：没配通道 → 不知道图往哪出；没导入 → 没有镜头可做。
    if rounds.get("0") == "blocked":
        return TASK_BY_ID["choose_machine"].as_dict()
    if pl.get("setup") in ("todo", "blocked"):
        return TASK_BY_ID["choose_machine"].as_dict()
    if pl.get("import") in ("todo", "blocked"):
        return TASK_BY_ID["import_pack"].as_dict()
    if pl.get("cast") in ("todo", "blocked"):
        return TASK_BY_ID["cast_assets"].as_dict()
    if pl.get("boards") in ("todo", "blocked"):
        return TASK_BY_ID["draw_boards"].as_dict()
    if pl.get("shoot") in ("todo", "blocked", "doing"):
        return TASK_BY_ID["make_episode"].as_dict()
    if pl.get("deliver") in ("todo", "blocked", "doing"):
        return TASK_BY_ID["finish_episode"].as_dict()
    return TASK_BY_ID["publish_check"].as_dict()


def home(ws) -> dict:
    """用户端首页的全部数据（一句话：这部剧现在怎么样、今天该做什么）。"""
    info = reader.workspace_info(ws)
    ov = reader.overview(ws)
    st = ov.get("status") or {}
    rounds = _rounds(ws)
    gates = ov.get("gates") or {}
    style = gates.get("style") or {}
    models = gates.get("models") or {}
    spent = spent_summary(ws, st)

    drama = {
        "name": _drama_name(ws, info),
        "style_text": style.get("label") or _pack_style(ws) or "还没导入制作包",
        "machine_text": _machine_text(models),
    }
    probs = user_problems(ws)
    hint = switch_hint(ws)
    if hint:
        probs = [hint] + probs
    return {
        "drama": drama,
        "stages": stage_progress(rounds),
        "next_task": next_task(ws),
        "problems": probs,
        "spent": spent,
        "episodes": episodes(st, info.get("out_dir")),
        "counts": {
            "shots": (st.get("data") or {}).get("shots", 0),
            "images": spent["images"].get("all", spent["images"]["total"]),
            "clips": spent["clips"],
        },
        "has_workspace": bool(info.get("ok")),
    }


def _machine_text(models: dict) -> str:
    im = (models.get("image") or {})
    vi = (models.get("video") or {})
    label = {"local_comfyui": "这台电脑（免费）"}
    parts = []
    if im.get("choice"):
        parts.append("画形象：" + label.get(im["choice"], im["choice"]))
    if vi.get("choice"):
        parts.append("做画面：" + label.get(vi["choice"], vi["choice"]))
    return " · ".join(parts) or "还没选择"


def help_prompt(ws, topic: str = "") -> dict:
    """「把问题交给 AI 助手」：生成一段可以直接粘贴给 AI 助手的话。

    用户端不出现命令、参数、退出码 —— 提示词由系统自动拼好，用户只需复制。
    """
    rounds = _rounds(ws)
    by_no = {r["no"]: r for r in rounds}
    stuck = []
    if by_no.get("-1", {}).get("state") == "blocked":
        stuck.append("还没选画风")
    if by_no.get("0", {}).get("state") == "blocked":
        stuck.append("还没选好用哪台机器做画面")
    for s in stage_progress(rounds):
        if s["state"] == "blocked" and s["key"] not in ("idea",):
            stuck.append("「%s」这一步还没做完" % s["name"])
    lines = [
        "我在用 SoloDrama 做一部短剧，遇到问题想请你帮我处理。",
        "",
        "这部剧放在：%s" % ws,
        "目前的进度：%s" % "、".join("%s（%s）" % (s["name"], s["state_text"]) for s in stage_progress(rounds)),
    ]
    if stuck:
        lines.append("卡住的地方：%s" % "；".join(stuck))
    if topic:
        lines += ["", "我的问题：%s" % topic]
    lines += ["",
              "请你：",
              "1) 先用大白话告诉我问题出在哪、为什么；",
              "2) 告诉我你会做哪些操作、有没有花钱的部分（花多少）；",
              "3) 需要我确认的地方先问我，得到我同意后再继续；",
              "4) 做完用 3 行以内汇报结果，别给我一堆命令和日志。"]
    return {"prompt": "\n".join(lines)}


def task_detail(ws, tid: str) -> dict:
    """任务详情（给用户端渲染用）：人话步骤 + 各步骤需不需要花钱 / 确认。"""
    t = TASK_BY_ID.get(tid)
    if not t:
        return {"ok": False, "error": "没有这个任务"}
    specs = set(t.spec_ids)
    for s in _ui_specs(t):
        specs.add(s)
    steps = []
    for sid in sorted(specs):
        c = CMD.get(sid)
        if c is None:
            continue
        steps.append({
            "spec": sid,
            "what": _step_text(c),
            "free": c.billing == CMD.FREE,
            "needs_confirm": c.billing == CMD.PAID,
            "may_take_long": c.mode == "job",
        })
    return {"ok": True, "task": t.as_dict(), "steps": steps}


def _ui_specs(t):
    ui = t.ui or {}
    out = []
    for k in ("spec", "preview_spec", "plan_spec", "run_spec"):
        if ui.get(k):
            out.append(ui[k])
    for s in ui.get("steps") or []:
        if s.get("spec"):
            out.append(s["spec"])
    return out


def friendly_error(code, text: str = "") -> dict:
    """把引擎退出码翻成用户能懂的话 + 该怎么办（用户端不出现退出码本身）。"""
    txt = text or ""
    if code == 0:
        return {"level": "ok", "title": "完成了", "detail": ""}
    if code == 4:
        return {"level": "ask", "title": "需要你先确认一下",
                "detail": "有一项必须由你决定的事情（例如画风、用哪台机器、要不要花钱）。"}
    if code == 2:
        return {"level": "fix", "title": "有几处要先修好，才能继续",
                "detail": "系统已经把问题列出来了。修好之后再点一次就行。"}
    if code == 3:
        return {"level": "stop", "title": "已经停下来保护你的钱",
                "detail": "出现了不该计费的情况，系统主动停了。请不要急着重来，先让我（AI 助手）看一下。"}
    if code == 130:
        return {"level": "stop", "title": "被中断了",
                "detail": "这次动作没做完。已经做好的部分会保留，可以继续。"}
    if "找不到短剧工作区" in txt:
        return {"level": "fix", "title": "没找到这部剧的文件夹",
                "detail": "可能是文件夹被移动或改名了。请重新选择这部剧的位置。"}
    if "ComfyUI" in txt or "8188" in txt:
        return {"level": "fix", "title": "画图工具没有打开",
                "detail": "用「这台电脑」画图需要先打开本机的画图工具（ComfyUI）。打开后重试即可。"}
    if "API Key" in txt or "并发" in txt:
        return {"level": "fix", "title": "账号或并发出了点问题",
                "detail": "可能是密钥没配好或同时在跑的任务太多。建议交给 AI 助手处理。"}
    return {"level": "error", "title": "这一步没有成功",
            "detail": "可以先看下面的详细记录；如果看不懂，点「把问题交给 AI 助手」。"}


def spend_for_shots(n) -> str:
    """按镜头数给出「大概要花多少」（仅供用户预估，实际以平台账单为准）。"""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "—"
    return yuan(n * COIN_PER_SHOT * COIN_TO_CNY)


_STEP_TEXT = {
    "pack.check": "先校验制作包（只读，不写盘）",
    "pack.import": "把制作包导入成引擎能做的镜头清单",
    "board.frame": "给每个镜头画一张首帧",
    "models.list": "先给你看两种做法各自的代价",
    "models.set": "把你选定的做法记下来",
    "project.scaffold": "建好这部剧的文件夹",
    "project.status": "看看创作进行到哪一步了",
    "assets.check": "先确认画图工具是否可用",
    "assets.local": "用你这台电脑画（免费，会占用电脑）",
    "video.plan": "先排一下这一集要跑多久（不占 GPU）",
    "video.run": "把镜头交给本机生成（只占 GPU 时间）",
    "media.assemble": "把镜头接成完整一集并提升清晰度",
    "media.render": "在画面上加字幕",
    "report.batch": "整理这次的制作报告",
    "compliance.ep": "回答 3 个问题，检查这一集能不能发布",
    "compliance.all": "检查整部剧的合规情况",
}


def _step_text(c) -> str:
    if c.id in _STEP_TEXT:
        return _STEP_TEXT[c.id]
    return c.title
