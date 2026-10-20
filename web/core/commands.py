# -*- coding: utf-8 -*-
"""commands.py —— 白名单命令目录（Web 层动作的唯一声明处）

设计要点
--------
1. **声明式白名单**：新增动作必须改本文件（而非改配置），这是刻意的安全设计 ——
   Web 层不存在「任意命令执行」入口。
2. **零业务逻辑**：每条命令只描述「怎么拼 argv」，一切判断仍在引擎里。
3. **W6 完整版**：覆盖「生产流程总纲」全部 15 环节 + G-1/G0/G1/G3/G4/G5/G6/G7/G8 门禁 +
   诊断/结账，每条命令都带**可直接复制的 Agent 提示词**。
4. argv 一律数组传递，不做 shell 拼接。
"""
from __future__ import annotations

from . import paths

# ---------------------------------------------------------------------------
# 脚本路径表
# ---------------------------------------------------------------------------
SCRIPTS = {
    "drama": paths.PROD_SCRIPTS / "drama.py",
    "creation": paths.CREATION_SCRIPTS / "creation.py",
    "market": paths.CREATION_SCRIPTS / "market_data.py",
    "breakdown": paths.CREATION_SCRIPTS / "hit_breakdown.py",
    "topic": paths.CREATION_SCRIPTS / "topic_analysis.py",
    "hit": paths.CREATION_SCRIPTS / "hit_selection.py",
    "genre": paths.CREATION_SCRIPTS / "genre_formula.py",
    "translate": paths.CREATION_SCRIPTS / "script_translate.py",
    "rewrite": paths.CREATION_SCRIPTS / "script_rewrite.py",
    "timing": paths.PROD_SCRIPTS / "script_timing_check.py",
    "asset_md": paths.ASSETS_SCRIPTS / "asset_md.py",
    "convert": paths.PROD_SCRIPTS / "convert_storyboard.py",
    "ingest": paths.PROD_SCRIPTS / "ingest_check.py",
    "halfcheck": paths.PROD_SCRIPTS / "half_narrated_check.py",
    "compliance": paths.PROD_SCRIPTS / "compliance_precheck.py",
    "prepare_refs": paths.PROD_SCRIPTS / "prepare_refs.py",
    "cost_ledger": paths.PROD_SCRIPTS / "cost_ledger.py",
    "preflight_ep": paths.PROD_SCRIPTS / "episode_preflight.py",
    "rhdoctor": paths.PROD_SCRIPTS / "rh_doctor.py",
    "subtitle": paths.SUBTITLE_SCRIPTS / "subtitle.py",
    "upscale": paths.SUBTITLE_SCRIPTS / "upscale.py",
    "layout": paths.STAGES_DIR / "_layout.py",
    "tools": paths.TOOLS_DIR / "cli.py",
    "comfy_check": paths.COMIFY_SCRIPTS / "comfy_client.py",
}

# 计费口径
FREE = "free"           # 完全免费
GPU = "gpu"             # 不花钱，但独占本机 GPU
PAID = "paid"           # ★ 计费（RH币 / 美元）
EXTERNAL = "external"   # 站外计费（闭源模型 / 人工）

BILLING_LABEL = {
    FREE: "免费",
    GPU: "￥0 · 占 GPU",
    PAID: "★计费",
    EXTERNAL: "站外计费",
}

# danger：0 = 只读；1 = 写本地文件；2 = 危险（涉及计费 / 覆盖产物 / 不可逆）
READ, WRITE, DANGER = 0, 1, 2


class Param:
    def __init__(self, key, label, kind="str", required=False, default=None,
                 choices=None, help="", placeholder=None):
        self.key = key
        self.label = label
        self.kind = kind                      # str | enum | bool | int | ep
        self.required = required
        self.default = default
        self.choices = choices
        self.help = help
        self.placeholder = placeholder

    def as_dict(self) -> dict:
        return {
            "key": self.key, "label": self.label, "kind": self.kind,
            "required": self.required, "default": self.default,
            "choices": self.choices, "help": self.help,
            "placeholder": self.placeholder,
        }


class Command:
    def __init__(self, cid, group, title, script, script_key="", argv=(), params=(), flags=None,
                 bools=None, gate=None, billing=FREE, danger=READ, mode="job",
                 help="", agent="", resources=()):
        self.id = cid
        self.group = group
        self.title = title
        self.script = script
        self.script_key = script_key
        self.argv = list(argv)
        self.params = list(params)
        self.flags = dict(flags or {})
        self.bools = dict(bools or {})
        self.gate = gate
        self.billing = billing
        self.danger = danger
        self.mode = mode                      # sync = 直接执行；job = 入作业队列
        self.help = help
        self.agent = agent
        self.resources = list(resources)

    # -- 校验 --------------------------------------------------------------
    def validate(self, values: dict) -> dict:
        out, errs = {}, []
        for p in self.params:
            raw = values.get(p.key, None)
            if isinstance(raw, str):
                raw = raw.strip()
            if raw in ("", None):
                raw = p.default
            if p.kind == "bool":
                out[p.key] = bool(raw)
                continue
            if raw in ("", None):
                if p.required:
                    errs.append("缺少必填参数：%s" % p.label)
                out[p.key] = None
                continue
            if isinstance(raw, str) and raw.startswith("-"):
                errs.append("参数「%s」不允许以 - 开头" % p.label)
                continue
            if p.kind == "int":
                try:
                    out[p.key] = int(raw)
                except (TypeError, ValueError):
                    errs.append("参数「%s」必须是整数" % p.label)
                continue
            if p.kind == "enum" and p.choices and raw not in p.choices:
                errs.append("参数「%s」取值非法：%s（可选 %s）" % (p.label, raw, "/".join(p.choices)))
                continue
            out[p.key] = raw
        return {"ok": not errs, "values": out, "errors": errs}

    # -- 拼 argv -----------------------------------------------------------
    def build_argv(self, values: dict, ws=None) -> list:
        argv = [paths.engine_python(), str(self.script)]
        spec = WS_FLAG.get(self.script_key)
        # ★ 工作区两种传法并存（实测结论，见 web/README.md 第 1 条）：
        #   drama.py 没有 --workspace 全局参数 → 只能靠环境变量（runner.base_env）；
        #   其余脚本自带 --workspace → 显式传参更可靠（creation.py 要求放在子命令之前）。
        if spec and ws:
            argv = argv[:2] + ([spec[0], str(ws)] if spec[1] == "prefix" else [])
        for tok in self.argv:
            if tok.startswith("{") and tok.endswith("}"):
                v = values.get(tok[1:-1])
                if v in (None, ""):
                    continue
                argv.append(str(v))
            else:
                argv.append(tok)
        for flag, key in self.flags.items():
            v = values.get(key)
            if v in (None, "", False):
                continue
            argv += [flag, str(v)]
        for flag, key in self.bools.items():
            if values.get(key):
                argv.append(flag)
        if spec and ws and spec[1] == "suffix":
            argv += [spec[0], str(ws)]
        return argv

    # -- Agent 提示词 ------------------------------------------------------
    def agent_prompt(self, ws, values=None) -> str:
        cmd = " ".join(_q(a) for a in self.build_argv(values or {}, ws)[1:])
        lines = [
            "【SoloDrama · %s ｜ %s】" % (self.group, self.title),
            "工作区：%s" % (ws or "<未指定>"),
            "执行命令：",
            "  python %s" % cmd,
        ]
        tail = self.agent or self.help or self.title
        lines.append("要求：%s" % tail)
        if self.gate:
            lines.append("注意：本命令受「%s」门禁约束，未过门禁（退出码 4）时不要跳步，先按提示完成确认。" % self.gate)
        if self.billing in (PAID, EXTERNAL):
            lines.append("注意：本命令★计费，须先给出清单与预估金额，等我明确确认后再执行；不要自行重试。")
        if self.danger == DANGER:
            lines.append("注意：本命令会写盘或覆盖产物，执行前先说明影响范围。")
        lines.append("执行后把结果压缩成 3 行以内汇报（结果 / 花费 / 下一步建议）；退出码为 2 或 3 时立即停下说明原因。")
        return "\n".join(lines)

    def as_dict(self, ws=None) -> dict:
        return {
            "id": self.id, "group": self.group, "title": self.title, "help": self.help,
            "gate": self.gate, "billing": self.billing,
            "billing_label": BILLING_LABEL.get(self.billing, self.billing),
            "danger": self.danger, "mode": self.mode, "resources": self.resources,
            "script": str(self.script.relative_to(paths.REPO_ROOT)).replace("\\", "/"),
            "params": [p.as_dict() for p in self.params],
            "argv_preview": " ".join(_q(a) for a in self.build_argv(_defaults(self), ws)[1:]),
            "agent_prompt": self.agent_prompt(ws, _defaults(self)),
        }


def _q(a) -> str:
    a = str(a)
    return '"%s"' % a if " " in a else a


def _defaults(cmd: Command) -> dict:
    return {p.key: p.default for p in cmd.params if p.default is not None}


# ---------------------------------------------------------------------------
# 参数复用
# ---------------------------------------------------------------------------
def P_EP(required=False):
    return Param("ep", "集号", "str", required=required, placeholder="ep01",
                 help="形如 ep01 / ep07")


P_WS_NOTE = "工作区由后端注入环境变量 SOLODRAMA_WORKSPACE（引擎 CLI 无 --workspace 全局参数）"

# ★ 哪些脚本自带 `--workspace`，以及该参数要放的位置（实测逐个 `--help` 核对过）。
#   不在表里的脚本（drama.py / tools/cli.py / asset_md.py / cost_ledger.py /
#   rh_doctor.py / episode_preflight.py / comfy_client.py）**只认环境变量**。
WS_FLAG = {
    "creation": ("--workspace", "prefix"),     # creation.py 的转发子命令要求写在子命令之前
    "layout": ("--workspace", "suffix"),
    "market": ("--workspace", "suffix"),
    "breakdown": ("--workspace", "suffix"),
    "topic": ("--workspace", "suffix"),
    "hit": ("--workspace", "suffix"),
    "genre": ("--workspace", "suffix"),
    "translate": ("--workspace", "suffix"),
    "rewrite": ("--workspace", "suffix"),
    "timing": ("--workspace", "suffix"),
    "convert": ("--workspace", "suffix"),
    "ingest": ("--workspace", "suffix"),
    "halfcheck": ("--workspace", "suffix"),
    "compliance": ("--workspace", "suffix"),
    "prepare_refs": ("--workspace", "suffix"),
    "subtitle": ("--workspace", "suffix"),
    "upscale": ("--workspace", "suffix"),
}


def _c(cid, group, title, script, **kw):
    return Command(cid, group, title, SCRIPTS[script], script_key=script, **kw)


# ---------------------------------------------------------------------------
# 命令目录（按「生产流程总纲」的 15 环节顺序编排）
# ---------------------------------------------------------------------------
COMMANDS: list = []


def _add(cmd: Command) -> None:
    COMMANDS.append(cmd)


# ===== 前置门禁 -1 画风 =====================================================
_add(_c("style.list", "-1 画风确认", "画风清单（含三轨规格）", "drama",
        argv=["style", "list"], mode="sync", danger=READ,
        help="打印 3D 漫剧 / 2D 动画 / 真人三轨规格，用于开工前选定画风。",
        agent="把三轨规格整理成一句话对比（单镜时长 / 资产要求 / 交付终点），并给出推荐画风与理由。"))
_add(_c("style.status", "-1 画风确认", "当前画风确认状态", "drama",
        argv=["style", "status", "--json"], mode="sync", danger=READ,
        help="只读查看画风是否已确认。",
        agent="告我当前画风是否已确认；未确认则提醒必须先过 G-1 才能开工。"))
_add(_c("style.set", "-1 画风确认", "确认画风（G-1）", "drama",
        argv=["style", "set", "{choice}"], gate="G-1", danger=WRITE,
        flags={"--sub-mode": "sub_mode"}, mode="job",
        params=[Param("choice", "画风", "enum", required=True,
                      choices=["3d_manhua", "2d_animation", "live_action"]),
                Param("sub_mode", "子模式", "str", placeholder="cel-anime / light-color-webtoon",
                      help="2D 动画可指定子模式")],
        help="★ 画风必须最先锁；事后更换会导致已产出素材全部作废。",
        agent="确认画风后立即提醒：资产、分镜、提示词全部要按该画风规格重做，且不可事后更换。"))
_add(_c("style.reset", "-1 画风确认", "清除画风确认", "drama",
        argv=["style", "reset"], danger=WRITE, mode="job",
        help="换画风前使用；已产出素材会作废。",
        agent="先明确告我「已产出素材将全部作废」，我确认后再执行。"))
_add(_c("style.require", "-1 画风确认", "画风门禁查询", "drama",
        argv=["style", "require"], mode="sync", danger=READ,
        help="未过则退出码 4（供上游脚本调用）。",
        agent="报告门禁是否通过；退出码 4 说明必须先去确认画风。"))

# ===== 前置门禁 0 通道 =====================================================
_add(_c("models.list", "0 通道确认", "通道清单（含执行依据要求）", "drama",
        argv=["models", "list"], mode="sync", danger=READ,
        help="列出本地 ComfyUI / 云端 ComfyUI / RH AI 应用 / RH 工作流 / 闭源模型。",
        agent="用表格列出各通道必须提供的「执行依据」，并说明哪些是★计费。"))
_add(_c("models.status", "0 通道确认", "当前通道确认状态", "drama",
        argv=["models", "status", "--json"], mode="sync", danger=READ,
        help="只读查看 image / video 通道与执行依据是否齐备。",
        agent="告我 image / video 各自选了哪条通道、执行依据是否齐备；缺什么就明确列出。"))
_add(_c("models.set", "0 通道确认", "确认通道（G0）", "drama",
        argv=["models", "set", "{pairs}"], gate="G0", danger=WRITE,
        flags={"--comfy-url": "comfy_url", "--comfy-workflow": "comfy_workflow",
               "--app-url": "app_url", "--app-id": "app_id", "--workflow-id": "workflow_id"},
        params=[Param("pairs", "确认项", "str", required=True, placeholder="image=local_comfyui video=runninghub",
                      help="形如 image=<通道> video=<通道>"),
                Param("comfy_url", "ComfyUI 地址", "str", placeholder="http://127.0.0.1:8188"),
                Param("comfy_workflow", "工作流 API 文件", "str"),
                Param("app_url", "RH 应用地址", "str"),
                Param("app_id", "RH 应用 ID", "str"),
                Param("workflow_id", "RH 工作流 ID", "str", placeholder="2111004946442563585")],
        help="★ 必须先确认通道；云端 ComfyUI 需地址+工作流二者齐备，否则退出码 4。",
        agent="按「执行依据」齐备性检查我给的参数，缺一样就停下告诉我还缺什么，不要用默认值糊过去。"))
_add(_c("models.reset", "0 通道确认", "清除通道确认", "drama",
        argv=["models", "reset", "{kind}"], danger=WRITE,
        params=[Param("kind", "类别", "enum", required=True, choices=["image", "video"])],
        help="换通道前使用。",
        agent="确认我要换的是哪条通道，并提示换通道后需要重跑哪些环节。"))

# ===== 项目与布局 ==========================================================
_add(_c("project.scaffold", "项目", "新建剧项目（建 9 个阶段目录）", "creation",
        argv=["scaffold"], danger=WRITE,
        flags={"--slug": "slug", "--title": "title", "--workspace": "target",
               "--platform": "platform", "--ep": "ep", "--sec": "sec"},
        params=[Param("target", "新工作区目录", "str", required=True, placeholder="D:/剧/新剧A"),
                Param("slug", "短标识", "str", required=True, placeholder="newdrama-a"),
                Param("title", "剧名", "str", placeholder="新剧 A"),
                Param("platform", "目标平台", "str", placeholder="TikTok"),
                Param("ep", "集数", "int", placeholder="40"),
                Param("sec", "单集秒数", "int", placeholder="70")],
        help="建 01-调研…09-发行 + layout.json，并回填 config.local.json。",
        agent="建完后用 layout 命令复核目录是否齐备，并把新工作区登记进控制台。"))
_add(_c("project.status", "项目", "创作链路状态一屏", "creation",
        argv=["status"], mode="sync", danger=READ,
        help="creation.py 的链路状态汇总。",
        agent="总结链路走到哪一步、还差什么。"))
_add(_c("layout.show", "项目", "布局与目录落点", "layout",
        argv=[], mode="sync", danger=READ,
        flags={"--workspace": "ws"},
        params=[Param("ws", "工作区（留空用当前）", "str")],
        help="打印引擎根 / 输入目录 / 输出目录与各阶段目录是否存在。",
        agent="指出哪些阶段目录还缺失（那是还没开始的环节）。"))

# ===== 环节 1 调研 =========================================================
_add(_c("market.template", "1 调研", "写出市场数据模板", "market",
        argv=["template"], danger=WRITE,
        help="生成 01-调研/market-data.json 骨架。",
        agent="告我模板路径，并列出必填字段（近 2 个月 / 多市场 / 西语市场）。"))
_add(_c("market.check", "1 调研", "覆盖度门禁", "market",
        argv=["check"], mode="sync", danger=READ,
        help="校验「近 2 个月 + 多市场 + 西语市场」是否达标。",
        agent="没过就说清缺哪一项，并给我补齐的检索建议。"))
_add(_c("market.compare", "1 调研", "多市场横向对比表", "market",
        argv=["compare"], mode="sync", danger=READ,
        help="生成对比表。",
        agent="把对比结论压成 3 条选题启示。"))
_add(_c("market.queries", "1 调研", "当期检索清单", "market",
        argv=["queries"], mode="sync", danger=READ,
        help="打印当期要检索的查询词。",
        agent="把检索清单整理成可直接投喂给检索工具的提示词。"))

# ===== 环节 2 拆解 =========================================================
_add(_c("breakdown.analyze", "2 拆解", "爆款拆解（题材/套路/爆点）", "breakdown",
        argv=["analyze"], danger=WRITE,
        help="分析并落盘到 01-调研/。",
        agent="汇总题材分布、剧情套路、爆点元素与差异化趋势，给出 3 条可执行建议。"))

# ===== 环节 3 选题 =========================================================
_add(_c("topic.scaffold", "3 选题", "写 raw 候选模板", "topic",
        argv=["scaffold"], danger=WRITE,
        help="生成候选池模板（8–12 个候选）。",
        agent="告我候选数下限与「同批主赛道重合度 ≤40%」的要求。"))
_add(_c("topic.score", "3 选题", "七维评分", "topic",
        argv=["score"], mode="sync", danger=READ,
        help="权重 20/12/15/13/12/13/15；合规≤3 一票否决；独特性≤3 封顶 74.9。",
        agent="列出各候选总分与等级（S/A/B/C/D），并标出被一票否决或封顶的候选及原因。"))
_add(_c("hit.select", "3 选题", "敲定 Top-N 定位卡", "hit",
        argv=["select"], danger=WRITE,
        help="多样性排期 + 对标匹配 → 定位卡（02-选题/positioning.json）。",
        agent="给出最终定位卡三要素（谁 / 什么冲突 / 差异化）。"))

# ===== 环节 3.5 转译 =======================================================
_add(_c("translate.langs", "3.5 转译", "支持语种清单", "translate",
        argv=["langs"], mode="sync", danger=READ,
        help="9 语种注册表（含语速/口语/翻译腔黑名单/QC 阈值）。",
        agent="列出语种与各自语速口径，方便我选目标语。"))
_add(_c("translate.detect", "3.5 转译", "判定源语言", "translate",
        argv=["detect"], mode="sync", danger=READ,
        flags={"--src": "src"}, params=[Param("src", "源文件", "str")],
        help="识别稿件源语言。",
        agent="报告判定结果与置信度。"))
_add(_c("translate.plan", "3.5 转译", "生成转译工作单", "translate",
        argv=["plan"], danger=WRITE,
        flags={"--to": "to", "--src": "src"}, bools={"--write": "write"},
        params=[Param("to", "目标语种", "str", required=True, placeholder="es"),
                Param("src", "源文件", "str"),
                Param("write", "同时写 brief", "bool", default=True)],
        help="产物：工作单 + brief（source-script.<lang>.md）。",
        agent="先只出工作单，等我确认术语口径后再落盘。"))
_add(_c("translate.check", "3.5 转译", "转译稿四维质检", "translate",
        argv=["check"], mode="sync", danger=READ,
        flags={"--to": "to", "--src": "src"},
        params=[Param("to", "目标语种", "str", required=True, placeholder="es"),
                Param("src", "待检文件", "str")],
        help="特征字符占比 / 源语言残留 / 翻译腔 / 术语一致性；未过退出码 4，禁止进下游。",
        agent="逐条列出未过的维度与命中片段，并给出修改建议。"))

# ===== 环节 3.6 题材公式 ===================================================
_add(_c("genre.list", "3.6 题材公式", "题材公式清单", "genre",
        argv=["list"], mode="sync", danger=READ,
        help="列出已收录的固定题材框架。",
        agent="列出公式 id 与适用题材。"))
_add(_c("genre.match", "3.6 题材公式", "关键词匹配公式", "genre",
        argv=["match"], mode="sync", danger=READ,
        flags={"--text": "text"}, params=[Param("text", "关键词/一句话", "str", required=True)],
        help="命中即可跳过选题（skip_topic）。",
        agent="告我命中哪个公式、命中依据是什么。"))
_add(_c("genre.show", "3.6 题材公式", "查看公式要点", "genre",
        argv=["show"], mode="sync", danger=READ,
        flags={"--id": "gid"}, params=[Param("gid", "公式 id", "str", required=True, placeholder="female-comeback")],
        help="打印根本原因 / 阶梯 / 五拍 / 钩子。",
        agent="把公式要点转成剧本改写时可直接照做的检查表。"))
_add(_c("genre.apply", "3.6 题材公式", "套用公式（跳过选题）", "genre",
        argv=["apply"], danger=WRITE,
        flags={"--id": "gid"},
        params=[Param("gid", "公式 id", "str", required=True, placeholder="female-comeback")],
        help="落 03-剧本/genre-plan.json，后续 plan 自动走公式模式。",
        agent="确认套用后，提醒后续剧本规划将不再需要 positioning.json。"))
_add(_c("genre.check", "3.6 题材公式", "公式符合度校验", "genre",
        argv=["check"], mode="sync", danger=READ,
        flags={"--id": "gid"}, params=[Param("gid", "公式 id", "str")],
        help="校验 blueprint 是否符合公式 QC。",
        agent="列出不符合项，并对应到剧本具体位置。"))

# ===== 环节 4 剧本 =========================================================
_add(_c("script.plan", "4 剧本", "集数规划（默认 30 集 × 60 秒）", "rewrite",
        argv=["plan"], danger=WRITE,
        flags={"--ep": "ep", "--sec": "sec"},
        params=[Param("ep", "集数", "int", default=30, placeholder="30"),
                Param("sec", "单集秒数", "int", default=60, placeholder="60")],
        help="把定位卡（或公式）落成 N 集规划 blueprint。",
        agent="报告集数规划结果，并提示每集四件套（cold_open/core_conflict/reversal/hook）为硬校验项。"))
_add(_c("script.build", "4 剧本", "生成某集 FFS 骨架", "rewrite",
        argv=["build"], danger=WRITE,
        flags={"--ep": "ep"}, params=[P_EP(required=True)],
        help="生成单集 FFS 剧本骨架。",
        agent="告我骨架路径，以及本集必须填的四件套字段。"))
_add(_c("script.lint", "4 剧本", "FFS 结构自检", "rewrite",
        argv=["lint"], mode="sync", danger=READ,
        flags={"--ep": "ep"}, params=[P_EP()],
        help="留存率导向结构硬校验（四件套 / 钩子不重复 / 反转必须改变力量对比）。",
        agent="逐条列出未过项与所在集，给出最小修改建议。"))
_add(_c("script.ref_template", "4 剧本", "对标结构模板", "rewrite",
        argv=["ref-template"], danger=WRITE,
        help="写出可直接照抄的结构模板。",
        agent="告我模板路径与照抄要点。"))

# ===== 环节 5 台词审计 =====================================================
_add(_c("timing.check", "5 台词审计", "台词时长审计（4.2 字/秒）", "timing",
        argv=[], mode="sync", danger=READ,
        flags={"--ep": "ep", "--unit": "unit", "--report": "report"},
        params=[P_EP(), Param("unit", "单元秒数", "int", default=30)],
        help="30s 单元目标 60–90 字、上限 100 字；超载/偏轻都会标出。",
        agent="列出超载与偏轻的段落，给出删改到区间内的具体建议。"))

# ===== 环节 6 资产 =========================================================
_add(_c("asset_md.list", "6 资产", "资产卡解析清单", "asset_md",
        argv=["--list", "--json"], mode="sync", danger=READ,
        flags={"--md": "md", "--kind": "kind"},
        params=[Param("md", "资产提示词 md", "str", placeholder="留空读环境变量 SOLODRAMA_ASSET_MD"),
                Param("kind", "类型", "enum", choices=["char", "scene", "prop"])],
        help="纯标准库解析，零网络零计费。",
        agent="汇总人物/场景/道具数量与缺项。"))
_add(_c("assets.local", "6 资产", "本地出图（￥0，默认干跑）", "drama",
        argv=["assets", "--engine", "local"], billing=GPU, danger=WRITE,
        flags={"--kind": "kind", "--only": "only"}, bools={"--submit": "submit", "--force": "force"},
        params=[Param("kind", "类型", "enum", default="all", choices=["all", "char", "scene", "prop"]),
                Param("only", "只做这些", "str", placeholder="char_01,char_02"),
                Param("submit", "真的出图（占 GPU，不花钱）", "bool", default=False),
                Param("force", "已生成的也重跑", "bool", default=False)],
        resources=["GPU"],
        help="默认干跑只列清单；--submit 才动 GPU。本机需 ComfyUI 在 8188 运行。",
        agent="先干跑给我看清单与缺口；我确认后再加 --submit。出图前请确认本机 ComfyUI 是否在线。"))
_add(_c("assets.check", "6 资产", "ComfyUI 在线体检", "drama",
        argv=["assets", "--engine", "local", "--check"], mode="sync", danger=READ,
        help="只体检 ComfyUI 是否在线，不出图。",
        agent="不在线就告诉我怎么启动（ComfyUI 桌面版需手动启动 8188 端口）。"))
_add(_c("assets.rh", "6 资产", "云端出图（★计费）", "drama",
        argv=["assets", "--engine", "rh"], billing=PAID, danger=DANGER,
        flags={"--kind": "kind", "--only": "only"}, bools={"--submit": "submit", "--force": "force"},
        params=[Param("kind", "类型", "enum", default="all", choices=["all", "char", "scene", "prop"]),
                Param("only", "只做这些", "str"),
                Param("submit", "确认提交（★计费）", "bool", default=False),
                Param("force", "已生成的也重跑（重复计费）", "bool", default=False)],
        resources=["RH"],
        help="人物约 27 RH币/张、场景约 $0.01/张；必须先过 G1 计费确认。",
        agent="先干跑列出清单、单价与合计金额，等我明确确认后再加 --submit；未确认前不要提交任何计费请求。"))
_add(_c("assets.gen_char", "6 资产", "云端角色资产出图", "drama",
        argv=["assets", "--engine", "rh", "--kind", "char"], billing=PAID, danger=DANGER,
        flags={"--only": "only"}, bools={"--submit": "submit"},
        params=[Param("only", "只做这些", "str"), Param("submit", "确认提交", "bool", default=False)],
        resources=["RH"], help="与云端出图同通道，仅限定人物。",
        agent="先给清单与金额，等我确认。"))
_add(_c("assets.gen_scene", "6 资产", "云端场景资产出图", "drama",
        argv=["assets", "--engine", "rh", "--kind", "scene"], billing=PAID, danger=DANGER,
        flags={"--only": "only"}, bools={"--submit": "submit"},
        params=[Param("only", "只做这些", "str"), Param("submit", "确认提交", "bool", default=False)],
        resources=["RH"], help="与云端出图同通道，仅限定场景。",
        agent="先给清单与金额，等我确认。"))

# ===== 环节 7 参考图 =======================================================
_add(_c("refs.report", "7 参考图", "参考图瘦身体检", "drama",
        argv=["refs"], mode="sync", danger=READ,
        help="默认只报告；超 H3 上限 5760px 的图必须瘦身。",
        agent="列出需要瘦身的图与当前尺寸，说明为什么必须做（超 5760 会被平台丢弃并错位）。"))
_add(_c("refs.apply", "7 参考图", "参考图瘦身（写盘）", "drama",
        argv=["refs"], danger=WRITE,
        bools={"--apply": "apply", "--write-config": "write_config"},
        params=[Param("apply", "真的写盘", "bool", default=True),
                Param("write_config", "同时把 characters.json 指到新目录", "bool", default=False)],
        help="写盘前会自动备份。",
        agent="执行前说明会改哪些文件、有没有备份。"))
_add(_c("refs.prepare", "7 参考图", "参考图规格化（长边/质量/格式）", "prepare_refs",
        argv=[], danger=WRITE,
        flags={"--max-edge": "max_edge", "--quality": "quality", "--format": "fmt"},
        bools={"--apply": "apply", "--write-config": "write_config"},
        params=[Param("max_edge", "长边上限", "int", default=2048),
                Param("quality", "JPEG 质量", "int", default=92),
                Param("fmt", "输出格式", "enum", choices=["jpg", "png"]),
                Param("apply", "真的写文件（不给只体检）", "bool", default=False),
                Param("write_config", "同时把 characters.json 指到新目录", "bool", default=False)],
        help="与 refs 的区别：refs 是「超限才瘦身」，prepare_refs 是「统一规格」。",
        agent="先只体检给我看会改哪些文件，我确认后再带 --apply。"))

# ===== 环节 8 分镜 / 提示词 ================================================
_add(_c("halfcheck.all", "8 分镜提示词", "半解说结构三类硬校验", "drama",
        argv=["halfcheck", "all"], mode="sync", danger=READ,
        help="旁白时间窗 / 资产规格 / 首帧锚点（读 05-分镜/storyboard.json）。",
        agent="逐类列出未过项与所在镜头，给出改法。"))
_add(_c("halfcheck.windows", "8 分镜提示词", "只校验旁白时间窗", "drama",
        argv=["halfcheck", "windows"], mode="sync", danger=READ,
        help="旁白/对白零重叠、最小间隔、尾缓冲。",
        agent="列出越界镜头。"))
_add(_c("halfcheck.anchors", "8 分镜提示词", "只校验首帧锚点", "drama",
        argv=["halfcheck", "anchors"], mode="sync", danger=READ,
        help="3D 漫剧首帧强制且角度必须匹配。",
        agent="列出缺锚点或角度不匹配的镜头。"))
_add(_c("convert.apply", "8 分镜提示词", "分镜 → data/ 四文件", "convert",
        argv=[], danger=WRITE,
        flags={"--ep": "ep", "--src": "src"}, bools={"--apply": "apply"},
        params=[P_EP(required=True), Param("src", "md 路径（留空自动找）", "str"),
                Param("apply", "真写 data/（先备份）", "bool", default=False)],
        help="先看差异再落盘；只搬运，不改写一个字的提示词。",
        agent="先不带 --apply 跑一遍给我看差异，我确认后再落盘。"))

# ===== 环节 9 门禁 =========================================================
_add(_c("ingest.check", "9 入门口禁", "入 data/ 生成端门禁（G7）", "ingest",
        argv=[], mode="sync", danger=READ, gate="G7",
        flags={"--ep": "ep"}, params=[P_EP()],
        help="台词齐全 / Picture 槽连续且 ≤6 / duration 与时间戳一致 / 参考图存在；不过退出码 2。",
        agent="按缺陷类型分组列出（缺 <d> / 槽位超限 / duration 不一致），每类给出最小修法；本命令挡在计费之前，必须过。"))

# ===== 环节 10 出片 ========================================================
_add(_c("video.plan", "10 出片", "出片计划与成本预估（G3）", "drama",
        argv=["video", "plan"], mode="sync", danger=READ, gate="G3",
        flags={"--limit": "limit", "--only": "only"},
        params=[Param("limit", "只算前 N 段", "int"), Param("only", "指定段", "str")],
        help="免费，不提交；预估偏高约 4%，只作闸门参考。",
        agent="告我将提交几段、跳过几段、预估消耗与按 145 RH币/段的对照值。"))
_add(_c("video.run", "10 出片", "真跑出片（★计费，G5）", "drama",
        argv=["video", "run"], billing=PAID, danger=DANGER, gate="G5",
        flags={"--limit": "limit", "--only": "only", "--resume": "resume", "--concurrency": "concurrency"},
        bools={"--yes": "yes"},
        params=[Param("yes", "确认计费闸门", "bool", default=False),
                Param("limit", "只跑前 N 段（小样）", "int"),
                Param("only", "指定段", "str"),
                Param("resume", "续跑批次号", "str", placeholder="20261017_141530"),
                Param("concurrency", "并发（平台硬限 ≤5）", "int", default=5)],
        resources=["RH"], help="★ 不加 --resume 的全量重跑 = 重复扣费；续跑必须带批次号。",
        agent="执行前必须报出：批次号、将提交段数、预估金额、是否续跑。等我明确确认后再执行；失败段重跑一律带 --resume 与 --only。"))
_add(_c("video.sample", "10 出片", "小样 1 段（G4）", "drama",
        argv=["video", "run", "--limit", "1"], billing=PAID, danger=DANGER, gate="G4",
        flags={"--only": "only"}, bools={"--yes": "yes"},
        params=[Param("only", "指定段（更精准）", "str"), Param("yes", "确认计费", "bool", default=False)],
        resources=["RH"], help="先出 1 段，用户看过成片再全量。",
        agent="出完后提醒我：必须先看过这一段成片，再决定是否全量。"))
_add(_c("video.status", "10 出片", "批次进度", "drama",
        argv=["video", "status"], mode="sync", danger=READ,
        params=[Param("batch", "批次号（留空取最新）", "str")],
        help="读 summary.json / state.json。",
        agent="汇总：总数 / 成功 / 失败 / 待跑 / 消耗 / 用时，并列出失败段 id。"))
_add(_c("video.resume", "10 出片", "续跑批次（★计费）", "drama",
        argv=["video", "run"], billing=PAID, danger=DANGER, gate="G5",
        flags={"--resume": "resume", "--only": "only"}, bools={"--yes": "yes"},
        params=[Param("resume", "批次号", "str", required=True),
                Param("only", "只补这些段", "str"),
                Param("yes", "确认计费", "bool", default=False)],
        resources=["RH"], help="复用 taskId，不重复提交已成功的段。",
        agent="续跑前先查该批次的在途任务，避免重复提交；告我这次会补哪些段、预估金额。"))

# ===== 环节 11 拼接 / 放大 / 字幕 ==========================================
_add(_c("media.assemble", "11 拼接字幕", "拼接 + 2K 放大（跑完即停）", "subtitle",
        argv=["--stage", "upscale"], billing=GPU, danger=WRITE,
        flags={"--ep": "ep"}, params=[P_EP(required=True)],
        resources=["GPU"],
        help="Topaz GPU 独占，一次一集；中断需整集重跑。",
        agent="提醒我：本环节独占 GPU（8–10 分钟/集），中断需整集重跑；跑完会停在 G6 字幕停点。"))
_add(_c("media.master", "11 拼接字幕", "只拼母版（不放大）", "subtitle",
        argv=["--stage", "master"], billing=GPU, danger=WRITE,
        flags={"--ep": "ep"}, params=[P_EP(required=True)], resources=["GPU"],
        help="快速确认镜头节奏是否与分镜一致。",
        agent="拼完告我母版时长与段数，供我核对节奏。"))
_add(_c("media.render", "11 拼接字幕", "烧录字幕（G6 停点后）", "subtitle",
        argv=["--stage", "render"], gate="G6", danger=WRITE,
        flags={"--ep": "ep", "--lang": "lang"}, bools={"--burn": "burn"},
        params=[P_EP(required=True), Param("lang", "语言", "str", default="zh"),
                Param("burn", "直接烧录", "bool", default=True)],
        resources=["GPU"],
        help="★ 必须问过用户才做；不答就只交付无字幕 2K 母版。",
        agent="执行前先问我「要不要烧字幕」；我说不要就只交付无字幕母版，不要自己决定。"))
_add(_c("media.preview", "11 拼接字幕", "字幕快速预览", "subtitle",
        argv=["--stage", "render", "--preview", "{n}"], danger=WRITE,
        flags={"--ep": "ep"}, params=[P_EP(required=True), Param("n", "预览段数", "int", default=3)],
        resources=["GPU"], help="只用前 N 段快速验证字幕样式与断行。",
        agent="预览完后告我样式是否合格（安全区距底 ≥200px、文本宽 ≤70%）。"))
_add(_c("media.upscale_verify", "11 拼接字幕", "放大产物自检", "upscale",
        argv=["--verify-only", "--json"], mode="sync", danger=READ,
        flags={"--ep": "ep"}, params=[P_EP(required=True)],
        help="读 <ep>_upscale.json 的 7 项自检。",
        agent="列出未过的自检项；若退化为插值（sharpness_gain_hf 不足）要明确告警。"))

# ===== 环节 12 验收与结账 ==================================================
_add(_c("report.batch", "12 验收结账", "出片战报", "drama",
        argv=["report"], mode="sync", danger=READ,
        flags={"--batch": "batch"}, params=[Param("batch", "批次号", "str")],
        help="四段式战报（结果 / 失败 / 用量 / 下一步）。",
        agent="把战报压成 3 行，并给出下一步建议。"))
_add(_c("cost.checkpoint", "12 验收结账", "成本台账 + 结账基线（Excel）", "drama",
        argv=["cost", "--checkpoint"], danger=WRITE,
        flags={"--drama": "drama_name"}, bools={"--json": "as_json", "--balance": "balance"},
        params=[Param("drama_name", "剧名", "str"), Param("as_json", "机器可读", "bool", default=False),
                Param("balance", "附带只读余额", "bool", default=True)],
        help="口径：只认平台 usage，不用余额倒推；产出 xlsx + markdown。",
        agent="报告本次增量消耗与全剧累计，并说明余额是否够再跑一集。"))
_add(_c("cost.json", "12 验收结账", "成本台账（只读 JSON）", "cost_ledger",
        argv=["--json", "--no-write"], mode="sync", danger=READ, flags={"--balance": "balance"},
        params=[Param("balance", "附带余额", "bool", default=True)],
        help="不写任何文件。",
        agent="汇总消耗构成（RH币 / 美元 / token）与单价口径。"))
_add(_c("episode.preflight", "12 验收结账", "集级前置体检", "preflight_ep",
        argv=["{eps}"], mode="sync", danger=READ,
        params=[Param("eps", "集号（可多个）", "str", required=True, placeholder="ep01 ep02")],
        help="交付前的集级体检。",
        agent="列出未过项与其影响的交付物。"))

# ===== 环节 13 合规与发行 ==================================================
_add(_c("compliance.ep", "13 合规发行", "发布前合规预检（G8 · 单集）", "compliance",
        argv=[], mode="sync", danger=READ, gate="G8",
        flags={"--ep": "ep", "--q1": "q1", "--q2": "q2", "--q3": "q3", "--note": "note"},
        params=[P_EP(required=True),
                Param("q1", "方法是否出现", "enum", required=True, choices=["yes", "no"]),
                Param("q2", "主体是否出现（含背景/倒影/屏幕）", "enum", required=True, choices=["yes", "no"]),
                Param("q3", "身份是否歧义（校服/童装风）", "enum", required=True, choices=["yes", "no"]),
                Param("note", "补充说明", "str")],
        help="发布前三问必须全「否」；有整改项退出码 2，不可发布。",
        agent="三问必须由我逐条回答，不要替我判断；有整改项时给出「主体不出现 / 方法不出现 / 身份不歧义」的最小改法。"))
_add(_c("compliance.all", "13 合规发行", "整剧合规预检（受限集数 + AIGC）", "compliance",
        argv=["--all"], mode="sync", danger=READ, gate="G8",
        flags={"--aigc-label": "aigc", "--restricted": "restricted", "--total": "total"},
        params=[Param("aigc", "全剧是否统一标注 AIGC", "enum", required=True, choices=["yes", "no"]),
                Param("restricted", "已受限集数", "int", default=0),
                Param("total", "总集数", "int", default=40)],
        help="受限集数占比 ≤10%；未标注 AIGC = 降流。",
        agent="算出余量（ceil(0.1×总集数) − 已受限），并提示 AIGC 标注口径。"))

# ===== 诊断 ===============================================================
_add(_c("diag.preflight", "诊断", "一次性体检（免费）", "drama",
        argv=["preflight"], mode="sync", danger=READ,
        help="Key 分级 + 引擎 doctor + check + 预演。",
        agent="按「环境 / 密钥 / 通道 / 数据」四类汇总问题清单，并给出可照抄的修法。"))
_add(_c("diag.balance", "诊断", "Key 余额（只读）", "drama",
        argv=["balance"], mode="sync", danger=READ,
        help="仅用于判断够不够跑，不参与消耗统计。",
        agent="告我各账号余额与「够跑几集」的粗略估计（按 145 RH币/段）。"))
_add(_c("diag.rhdoctor", "诊断", "RunningHub 双 Key 体检", "rhdoctor",
        argv=[], mode="sync", danger=READ,
        flags={"--check": "check", "--key": "key"}, bools={"--live": "live"},
        params=[Param("check", "预检类型", "enum", choices=["workflow", "ai-app", "model", "llm"]),
                Param("key", "Key 类型", "enum", choices=["consumer", "ent_shared", "ent_exclusive"]),
                Param("live", "真发只读请求", "bool", default=False)],
        help="默认零网络；--live 才发请求。",
        agent="默认先零网络体检；要联网前先问我。"))
_add(_c("diag.comfy", "诊断", "本地 ComfyUI 在线体检", "comfy_check",
        argv=["--check"], mode="sync", danger=READ,
        help="零网络依赖，检查 127.0.0.1:8188。",
        agent="不在线就告我启动方法。"))
_add(_c("diag.guide", "诊断", "打印速查（drama.py guide）", "drama",
        argv=["guide"], mode="sync", danger=READ, help="命令速查全文。",
        agent="把速查整理成「常用五条命令」。"))


def catalog(ws=None) -> list:
    return [c.as_dict(ws) for c in COMMANDS]


def get(cid: str):
    for c in COMMANDS:
        if c.id == cid:
            return c
    return None


def groups() -> list:
    seen, out = set(), []
    for c in COMMANDS:
        if c.group not in seen:
            seen.add(c.group)
            out.append(c.group)
    return out
