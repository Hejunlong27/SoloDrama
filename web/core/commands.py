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
    # ★ 2026-11-02（分支 feat/pack-engine）：创作层已移出仓库，唯一入口是制作包导入。
    "pack_import": paths.IMPORT_SCRIPTS / "pack_import.py",
    "md2pack": paths.IMPORT_SCRIPTS / "md2pack.py",
    "prompt_marks": paths.IMPORT_SCRIPTS / "prompt_marks.py",
    "preset_apply": paths.IMPORT_SCRIPTS / "preset_apply.py",
    "asset_md": paths.ASSETS_SCRIPTS / "asset_md.py",
    "ingest": paths.PROD_SCRIPTS / "ingest_check.py",
    "compliance": paths.PROD_SCRIPTS / "compliance_precheck.py",
    "prepare_refs": paths.PROD_SCRIPTS / "prepare_refs.py",
    "release_export": paths.PROD_SCRIPTS / "release_export.py",
    "time_model": paths.PROD_SCRIPTS / "time_model.py",
    "time_report": paths.PROD_SCRIPTS / "time_report.py",
    "preflight_ep": paths.PROD_SCRIPTS / "episode_preflight.py",
    "subtitle": paths.SUBTITLE_SCRIPTS / "subtitle.py",
    "upscale": paths.SUBTITLE_SCRIPTS / "upscale.py",
    "layout": paths.STAGES_DIR / "_layout.py",
    "comfy_check": paths.COMIFY_SCRIPTS / "comfy_client.py",
    # ★ 2026-10-29：视频本地出片（H3，￥0）与 RH 工作流出图（t2i / i2i 双工作流）
    "comfy_video": paths.STAGES_DIR / "video" / "comfyui" / "comfy_local_video.py",
    # ★ 新分支补入：批量出图 / 分镜图 / 节点状态机
    "gen_local": paths.PROD_SCRIPTS / "gen_assets_local.py",
    "gen_boards": paths.PROD_SCRIPTS / "gen_boards.py",
    "nodes": paths.PROD_SCRIPTS / "nodes.py",
    # ★ 2026-11-04：新建项目（结构 + 空模板）
    "init_project": paths.PROD_SCRIPTS / "init_project.py",
    "env_check": paths.TOOLS_DIR / "env_check.py",
    # 平台通道（RunningHub）。默认不出网，显式选 video.rh.* / assets.rh_wf 才走这里。
    "rhdoctor": paths.PROD_SCRIPTS / "rh_doctor.py",
    "gen_rh_wf": paths.PROD_SCRIPTS / "gen_assets_rh_workflow.py",
}


# 计费口径
FREE = "free"           # 完全免费
GPU = "gpu"             # 不花钱，但独占本机 GPU
PAID = "paid"           # 按次/按量计费（平台通道 RunningHub / 闭源模型）
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
                 help="", agent="", resources=(), env=None):
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
        # env: {环境变量名: 参数名} —— 有些引擎脚本**只认环境变量**（如 gen_assets_local.py 要
        # SOLODRAMA_ASSET_MD），没有对应的命令行参数。这里声明映射，执行时由 runner 注入，
        # 既不改引擎，也不让浏览器拼任何命令。
        self.env = dict(env or {})

    def env_for(self, values: dict) -> dict:
        """把参数解析成要注入子进程的环境变量（空值不注入）。"""
        out = {}
        for env_name, key in self.env.items():
            v = (values or {}).get(key)
            if v not in (None, "", False):
                out[str(env_name)] = str(v)
        return out

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
            lines.append("注意：本命令★计费，须先给出清单与**按台账实测的参考费用**，"
                         "等我明确确认后再执行；不要自行重试。不要编预估单价——"
                         "报不出实测数据就直说「尚无计费记录」。")
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
    "release_export": ("--workspace", "suffix"),
    "subtitle": ("--workspace", "suffix"),
    "upscale": ("--workspace", "suffix"),
    "workflow": ("--workspace", "suffix"),
    "setup": ("--workspace", "suffix"),
    "continuity": ("--workspace", "suffix"),
    # ★ env_check.py 没有 --workspace 参数（它只查解释器/ffmpeg/依赖），刻意不登记
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
# ===== 前置门禁 0 通道 =====================================================
_add(_c("models.list", "0 通道", "通道清单（含执行依据要求）", "drama",
        argv=["models", "list"], mode="sync", danger=READ,
        help="列出本地 ComfyUI / 远程 ComfyUI / 闭源模型。",
        agent="用表格列出各通道必须提供的「执行依据」，并说明哪些是★计费。"))
_add(_c("models.status", "0 通道", "当前通道确认状态", "drama",
        argv=["models", "status", "--json"], mode="sync", danger=READ,
        help="只读查看 image / video 通道与执行依据是否齐备。",
        agent="告我 image / video 各自选了哪条通道、执行依据是否齐备；缺什么就明确列出。"))
_add(_c("models.set", "0 通道", "确认通道（G0）", "drama",
        argv=["models", "set", "{pairs}"], gate="G0", danger=WRITE,
        flags={"--comfy-url": "comfy_url", "--comfy-workflow": "comfy_workflow",
               "--app-url": "app_url", "--app-id": "app_id", "--workflow-id": "workflow_id"},
        params=[Param("pairs", "确认项", "str", required=True, placeholder="image=local_comfyui video=local_comfyui",
                      help="形如 image=<通道> video=<通道>"),
                Param("comfy_url", "ComfyUI 地址", "str", placeholder="http://127.0.0.1:8188"),
                Param("comfy_workflow", "工作流 API 文件", "str"),
                Param("app_url", "RH 应用地址", "str"),
                Param("app_id", "RH 应用 ID", "str"),
                Param("workflow_id", "RH 工作流 ID", "str", placeholder="2111004946442563585")],
        help="★ 必须先确认通道；缺工作流文件时退出码 4。",
        agent="按「执行依据」齐备性检查我给的参数，缺一样就停下告诉我还缺什么，不要用默认值糊过去。"))
_add(_c("models.reset", "0 通道", "清除通道确认", "drama",
        argv=["models", "reset", "{kind}"], danger=WRITE,
        params=[Param("kind", "类别", "enum", required=True, choices=["image", "video"])],
        help="换通道前使用。",
        agent="确认我要换的是哪条通道，并提示换通道后需要重跑哪些环节。"))

# ===== 项目与布局 ==========================================================
_add(_c("layout.show", "0 项目", "布局与目录落点", "layout",
        argv=[], mode="sync", danger=READ,
        flags={"--workspace": "ws"},
        params=[Param("ws", "工作区（留空用当前）", "str")],
        help="打印引擎根 / 输入目录 / 输出目录与各阶段目录是否存在。",
        agent="指出哪些阶段目录还缺失（那是还没开始的环节）。"))

# ★ 2026-11-04：新建项目终于有命令了。
#   此前 `project_create` 引用的 spec 在本分支里**根本不存在**（创作层移出仓库时一起没了），
#   于是「新建项目」按钮 100% 抛 500。这里指向 `stages/production/scripts/init_project.py`，
#   它调的仍是布局真源 `_layout.scaffold()`，不另写一套建目录逻辑。
_add(_c("project.scaffold", "0 项目", "新建剧项目（结构 + 空模板）", "init_project",
        argv=[], mode="sync", danger=WRITE,
        flags={"--workspace": "target", "--title": "title", "--platform": "platform",
               "--episodes": "ep", "--ep-seconds": "sec",
               "--track": "track", "--look": "look", "--aspect": "aspect",
               "--resolution": "resolution"},
        params=[Param("target", "目标目录（绝对路径）", "str", required=True,
                      placeholder="D:/剧本/我的新剧"),
                Param("title", "剧名", "str", required=True),
                Param("platform", "目标平台", "str"),
                Param("ep", "集数", "int", default=30),
                Param("sec", "单集秒数", "int", default=60)],
        help="建 9 个阶段目录 + layout.json + 引擎配置；模板是空的（不是范例）。",
        agent="建完汇报：目录数量、layout 是否写好、下一步该写企划案还是导入制作包。"))

# ===== 制作包：新分支的唯一输入入口 ========================================
# 为什么把「导入」放在第一位：创作已经移出引擎（选题/剧本/资产设计/导演/分镜/提示词
# 都在 Skill 里），引擎能做的第一件事就是**读包**。没有包，后面每个按钮都点不动。
_add(_c("convert.apply", "1 导入", "创作稿 → 制作包（机械转换，不创作）", "md2pack",
        argv=[], billing=FREE, danger=WRITE,
        flags={"--out": "out", "--ep": "ep"},
        bools={"--drop-missing-cast": "drop_missing_cast"},
        params=[Param("out", "输出目录", "str", placeholder="留空用 <工作区>/pack"),
                Param("ep", "只转这些集", "str", placeholder="1,2（留空转全部）"),
                Param("drop_missing_cast", "资产没齐时移除缺失参考图（会连 {{Mixed n}} 一起摘）",
                      "bool", default=False)],
        help="把 00-创作/ 的资产库与导演手册转成 pack（资产/分集 JSON），并写一份缺口报告。"
             "只做识别与搬运：不改台词、不改提示词、不补写。缺口一律写进 _import_report.md。",
        agent="转换后先读缺口报告：缺提示词的资产、被跳过的镜头、没认出来的台词，都要逐条告诉我。"))
# ★ 2026-11-06：老项目补台词标记。裸写在引号里的中文会被 H3 烧成画面字幕，
#   转换器只兜底「新转的包」，已经落盘的 `06-提示词/<ep>/h3_prompts.json` 要单独重写。
_add(_c("prompt.fix", "1 导入", "老项目补台词标记（<d>，重写 h3_prompts.json）", "prompt_marks",
        argv=[], billing=FREE, danger=WRITE,
        flags={"--ep": "ep", "--lang": "lang"},
        bools={"--apply": "apply"},
        params=[Param("ep", "只处理这些集", "str", placeholder="ep01,ep02（留空全扫）"),
                Param("lang", "台词语种标签", "str", placeholder="Chinese / Spanish"),
                Param("apply", "真写盘（每份文件先落 .bak-时间戳）", "bool", default=False)],
        help="把已落盘提示词里的裸引号台词包成 <d>[语种] 原句。</d>。幂等，只动提示词不动台词数组。"
             "默认干跑。改完要重跑受影响的镜 —— 已烧进成片的字幕无法去除。",
        agent="先干跑，告诉我多少镜会被改、还剩几条要人工判断（招牌/标语类不自动改）；"
              "确认后再写盘。写盘前必须说明「旧成片只能重跑」。"))
_add(_c("pack.check", "1 导入", "校验制作包（只读，不写盘）", "pack_import",
        argv=[], mode="sync", danger=READ,
        flags={"--pack": "pack", "--ep": "ep"},
        params=[Param("pack", "制作包目录", "str", placeholder="留空用 <工作区>/pack"),
                Param("ep", "集号", "str", placeholder="ep01")],
        help="结构校验：spec / 必填字段 / 资产引用 / 时长越界 / 参考图号闭合。",
        agent="逐条说清哪一条不过、是哪个文件的哪一项、改法是补字段还是改值。"))
_add(_c("pack.import", "1 导入", "导入制作包 → data/ 五文件", "pack_import",
        argv=["--apply"], flags={"--pack": "pack", "--ep": "ep"},
        params=[Param("pack", "制作包目录", "str", placeholder="留空用 <工作区>/pack"),
                Param("ep", "集号", "str", placeholder="留空导全部")],
        help="落盘前自动备份旧 data/；缺参考图会列出，出图后重跑即可回填。",
        agent="汇报导入了多少镜、多少资产、还缺几张参考图。"))
_add(_c("pack.preset", "1 导入", "应用项目预配置（出图/出片/放大通道）", "preset_apply",
        argv=["--apply"], danger=WRITE,
        flags={"--preset": "preset"},
        params=[Param("preset", "预配置卡", "enum", required=True,
                      choices=["local-comfyui-all", "local-comfyui-rh"])],
        help="一次性写 model-plan.json / config.local.json / config.upscale.json，并回读校验。",
        agent="确认三条通道分别是什么、并发多少、放大目标尺寸多少。"))

# ===== 资产 ================================================================
_add(_c("asset_md.list", "2 资产", "资产卡解析清单", "asset_md",
        argv=["--list", "--json"], mode="sync", danger=READ,
        flags={"--md": "md", "--kind": "kind"},
        params=[Param("md", "资产提示词 md", "str", placeholder="留空读环境变量 SOLODRAMA_ASSET_MD"),
                Param("kind", "类型", "enum", choices=["char", "scene", "prop"])],
        help="纯标准库解析，零网络零计费。",
        agent="汇总人物/场景/道具数量与缺项。"))
_add(_c("assets.local", "2 资产", "本地出图（￥0，默认干跑）", "drama",
        argv=["assets", "--engine", "local"], billing=GPU, danger=WRITE,
        flags={"--kind": "kind", "--only": "only", "--pack": "pack"},
        bools={"--submit": "submit", "--force": "force"},
        params=[Param("kind", "类型", "enum", default="all", choices=["all", "char", "scene", "prop"]),
                Param("only", "只做这些", "str", placeholder="P01@LOOK-A,P02"),
                Param("pack", "制作包目录", "str", placeholder="留空用 <工作区>/pack"),
                Param("submit", "真的出图（占 GPU，不花钱）", "bool", default=False),
                Param("force", "已生成的也重跑", "bool", default=False),
                Param("asset_md", "资产提示词 md（老通道，SOLODRAMA_ASSET_MD）", "str",
                      placeholder="留空则读制作包")],
        resources=["GPU"],
        env={"SOLODRAMA_ASSET_MD": "asset_md"},
        help="默认干跑只列清单；--submit 才动 GPU。资产来源优先制作包（<工作区>/pack），"
             "没给 --pack 时才回落到 SOLODRAMA_ASSET_MD 指向的资产提示词 md。"
             "本机 ComfyUI 没启动时会自动拉起后台实例（30–90 秒，可用 --no-boot 关掉）。",
        agent="先干跑给我看清单与缺口；我确认后再加 --submit。出图前不用管 ComfyUI 是否在线，"
              "它会自动启动。"))
_add(_c("assets.check", "2 资产", "出图能力预检（免费）", "drama",
        argv=["assets", "--engine", "local", "--check"], mode="sync", danger=READ,
        # 2026-11-02：资产提示词已改为惰性校验（--pack 通道不必设 SOLODRAMA_ASSET_MD），
        # 所以体检不再需要先给 md；保留这个参数只为老项目。
        # ★ 2026-11-05：它已经不是「只看在线」了 —— 会核守卫/在线/版本/节点类/模型文件/必需输入，
        #   与批量入口用的是**同一份判据**（gen_preflight -> cloud.health）。标题必须跟着改，
        #   否则人会以为「在线 = 能出图」。
        params=[Param("asset_md", "资产提示词 md（老通道，可留空）", "str")],
        env={"SOLODRAMA_ASSET_MD": "asset_md"},
        help="核四件事：ComfyUI 在线 / 工作流节点类齐全 / 模型文件存在 / 必需输入有着落。"
             "不出图、不花钱（没启动会先自动拉起）。",
        agent="逐条报失败项（缺哪个节点类、哪个模型文件全名），并给出「补齐」或「换工作流」两条出路。"))
_add(_c("assets.cloud", "2 资产", "云端 ComfyUI 出图（★按主机时长）", "drama",
        # 不打 gate 标记：G5 是**出片**门禁，出图挂在它上面会让任务记录里出现假的阶段标记。
        # 计费确认靠 billing=PAID + danger=DANGER（与 assets.rh_wf 同一套）。
        argv=["assets", "--engine", "cloud"], billing=PAID, danger=DANGER,
        flags={"--kind": "kind", "--only": "only", "--pack": "pack", "--comfy-url": "comfy_url"},
        bools={"--submit": "submit", "--force": "force"},
        params=[Param("kind", "类型", "enum", default="all", choices=["all", "char", "scene", "prop"]),
                Param("only", "只做这些", "str", placeholder="P01@LOOK-A,P02"),
                Param("pack", "制作包目录", "str", placeholder="留空用 <工作区>/pack"),
                Param("comfy_url", "云端 ComfyUI 地址", "str",
                      placeholder="https://<实例>-8188.container.x-gpu.com（留空取模型确认单）"),
                Param("submit", "真的出图（★计费）", "bool", default=False),
                Param("force", "已生成的也重跑（★重复计费）", "bool", default=False),
                Param("asset_md", "资产提示词 md（老通道，SOLODRAMA_ASSET_MD）", "str")],
        resources=["GPU"],
        env={"SOLODRAMA_ASSET_MD": "asset_md"},
        help="同一套出图客户端，只是地址指向云端实例。计费按**主机时长**（以云平台账单为准），"
             "不是按张 —— 所以干跑先看清单，别在空中排队。地址留空时取模型确认单。",
        agent="执行前报出：目标地址、将出几张、预计主机时长；**不要给单价或预估金额**"
              "（内置单价已废弃，真实消耗以台账为准）。地址是本机时要拦住（那是假云端）。"))
_add(_c("assets.rh_wf", "2 资产", "云端工作流出图（★计费，非默认）", "gen_rh_wf",
        billing=PAID, danger=DANGER,
        flags={"--md": "md", "--only": "only", "--ratio": "ratio",
               "--mode": "mode", "--ref": "ref"},
        bools={"--submit": "submit", "--force": "force"},
        params=[Param("md", "资产提示词 md", "str", required=True,
                      placeholder="<工作区>/04-资产/资产提示词.md"),
                Param("only", "只做这些", "str", placeholder="char_01,char_02"),
                Param("ratio", "画幅", "str", default="16:9"),
                Param("mode", "模式（t2i / i2i）", "enum", default="t2i", choices=["t2i", "i2i"]),
                Param("ref", "参考图路径", "str", placeholder="i2i 必填，如 04-资产/characters/xxx.png"),
                Param("submit", "确认提交（★计费）", "bool", default=False),
                Param("force", "已生成的也重跑（重复计费）", "bool", default=False)],
        resources=["RH"],
        help="走 RunningHub「工作流」通道（nodeInfoList）。★ 文生图与图生图是两套工作流："
             "t2i 用 image_providers[active].id，i2i 用 id_i2i 且必须给 --ref。默认干跑。"
             "日常出图用 assets.local（￥0），这条只在需要平台模型时用。",
        agent="先干跑列出清单与将用的工作流 ID；i2i 要确认参考图路径存在，"
             "等我明确确认后再 --submit。",
        env={"RUNNINGHUB_API_KEY": "key"}))
_add(_c("board.frame", "3 分镜图", "批量出分镜图（每镜一张 9:16 首帧）", "gen_boards",
        argv=["--apply"], billing=GPU, danger=WRITE,
        flags={"--ep": "ep", "--only": "only"},
        bools={"--force": "force"},
        params=[Param("ep", "集号", "str", required=True, placeholder="ep01"),
                Param("only", "只做这些镜", "str", placeholder="shot_001,shot_003"),
                Param("force", "已生成的也重跑", "bool", default=False)],
        resources=["GPU"],
        help="读 data/<ep>/boards.json 的 prompt，每镜出一张与成片同构的首帧。"
             "缺 board_prompt 的镜会跳过并列出来。",
        agent="汇报出了几张、跳过哪几镜、为什么跳过。"))
# ===== 环节 7 参考图 =======================================================
_add(_c("refs.report", "2 资产", "参考图瘦身体检", "drama",
        argv=["refs"], mode="sync", danger=READ,
        help="默认只报告；超 H3 上限 5760px 的图必须瘦身。",
        agent="列出需要瘦身的图与当前尺寸，说明为什么必须做（超 5760 会被平台丢弃并错位）。"))
_add(_c("refs.apply", "2 资产", "参考图瘦身（写盘）", "drama",
        argv=["refs"], danger=WRITE,
        bools={"--apply": "apply", "--write-config": "write_config"},
        params=[Param("apply", "真的写盘", "bool", default=True),
                Param("write_config", "同时把 characters.json 指到新目录", "bool", default=False)],
        help="写盘前会自动备份。",
        agent="执行前说明会改哪些文件、有没有备份。"))
_add(_c("refs.prepare", "2 资产", "参考图规格化（长边/质量/格式）", "prepare_refs",
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
# ===== 环节 9 门禁 =========================================================
_add(_c("ingest.check", "1 导入", "入 data/ 生成端门禁（G7）", "ingest",
        argv=[], mode="sync", danger=READ, gate="G7",
        flags={"--ep": "ep"}, params=[P_EP()],
        help="台词齐全 / Picture 槽连续且 ≤6 / duration 与时间戳一致 / 参考图存在；不过退出码 2。",
        agent="按缺陷类型分组列出（缺 <d> / 槽位超限 / duration 不一致），每类给出最小修法；本命令挡在计费之前，必须过。"))

# ===== 环节 10 出片 ========================================================
_add(_c("video.local", "4 出片", "本地出视频（H3，￥0，默认干跑）", "comfy_video",
        billing=GPU, danger=WRITE,
        flags={"--prompt": "prompt", "--ref": "ref", "--seconds": "seconds",
               "--mp": "mp", "--steps": "steps", "--out": "out",
               "--workflow": "workflow", "--map": "map"},
        bools={"--submit": "submit"},
        params=[Param("prompt", "镜头提示词", "str",
                      placeholder="自然语言长句；可含 subject_definitions"),
                Param("ref", "参考图路径", "str", placeholder="图生视频建议给，否则人物一致性不保证"),
                Param("seconds", "时长（秒）", "str", placeholder="留空 = 沿用工作流原值"),
                Param("mp", "百万像素", "str", placeholder="留空 = 沿用原值；8G 卡可填 0.3-0.4"),
                Param("steps", "采样步数", "str", placeholder="留空 = 沿用工作流里的值（4 步 turbo 填 4）"),
                Param("out", "产物目录", "str", placeholder="<工作区>/video-pipeline/output/local-video"),
                Param("workflow", "工作流 JSON", "str",
                      placeholder="留空用 stages/video/comfyui/workflow_h3_local.json"),
                Param("map", "节点映射 JSON", "str",
                      placeholder="留空读同名 <工作流>.map.json"),
                Param("submit", "真的出片（占 GPU，不花钱）", "bool", default=False)],
        resources=["GPU"],
        help="走本机 ComfyUI 的 H3 图生视频工作流（stages/video/comfyui/workflow_h3_local.json）。"
             "默认干跑；地址取连接中心（默认 127.0.0.1:8188）。"
             "正式出片请用「真跑出片」（含预检与断点续跑），本命令是单镜调试通道。",
        agent="先干跑给我看时长/帧数/槽位；确认后加 --submit。出片前先体检。"))
_add(_c("video.local.check", "4 出片", "本地视频体检", "comfy_video",
        argv=["--check"], mode="sync", danger=READ, billing=GPU,
        flags={"--workflow": "workflow", "--map": "map"},
        params=[Param("workflow", "工作流 JSON", "str"),
                Param("map", "节点映射 JSON", "str")],
        resources=["GPU"],
        help="逐项核对：ComfyUI 在线 + 工作流里每个节点类可用 + 每个模型文件存在。不占 GPU 出片。",
        agent="缺什么直接说缺哪个文件/节点，并给出替代工作流；连不上就说清探测的实际地址。"))
_add(_c("video.workflow.nodes", "4 出片", "列出工作流节点（换工作流时用）", "comfy_video",
        argv=["--list-nodes"], mode="sync", danger=READ,
        flags={"--workflow": "workflow"},
        params=[Param("workflow", "工作流 JSON", "str", placeholder="留空用本机默认 H3 工作流")],
        help="离线（不连 ComfyUI、不占 GPU）：列出每个节点 id / class_type，"
             "并标出它适合当哪个角色（prompt / images / seconds / steps / seed / aspect / prefix）。",
        agent="把输出按 id + class_type 列给我，我据此写映射文件。"))
_add(_c("video.workflow.mapcheck", "4 出片", "校验节点映射（离线）", "comfy_video",
        argv=["--map-check"], mode="sync", danger=READ,
        flags={"--workflow": "workflow", "--map": "map"},
        params=[Param("workflow", "工作流 JSON", "str"),
                Param("map", "节点映射 JSON", "str", placeholder="留空读同名 <工作流>.map.json")],
        help="离线校验：映射里的节点 id 在工作流里是否存在、类型是否对得上。"
             "换工作流后先跑这个，能在花 GPU 之前抓出「id 写错」这类必然失败。",
        agent="有 [NG] 就按提示改映射文件的 id；[? ] 只是类型提醒，可以说清风险后继续。"))
_add(_c("video.plan", "4 出片", "出片计划与耗时预估（不提交任务）", "drama",
        argv=["video", "plan"], mode="sync", danger=READ,
        flags={"--limit": "limit", "--only": "only", "--ep": "ep"},
        params=[Param("ep", "集号", "str", required=True, placeholder="ep01"),
                Param("limit", "只算前 N 段", "int"), Param("only", "指定段", "str")],
        help="零开销、不提交任何任务。给出总耗时与该集的时间分解（出片通常占七成以上）。",
        agent="报出「这一集预计多久 / 瓶颈在哪个阶段」，并说明哪些系数还没实测校准。"))
_add(_c("video.run", "4 出片", "真跑出片（本机 GPU，￥0）", "drama",
        argv=["video", "run", "--engine", "local"], billing=GPU, danger=DANGER,
        # `--workflow`：默认工作流缺件时的**替代方案**入口。没有它，界面上只能被预检拦住，
        # 而命令行早就支持（2026-11-05 实测：h3_local 能跑，却在界面里无路可走）。
        flags={"--limit": "limit", "--only": "only", "--ep": "ep", "--workflow": "workflow"},
        bools={"--yes": "yes", "--force": "force"},
        params=[Param("ep", "集号", "str", required=True, placeholder="ep01"),
                Param("yes", "确认执行（会占 GPU）", "bool", default=False),
                Param("limit", "只跑前 N 段（小样）", "int"),
                Param("only", "指定段", "str"),
                Param("workflow", "工作流 JSON", "str",
                      placeholder="留空取确认单；缺件时可填 workflow_h3_local.json"),
                Param("force", "已有产物也重跑", "bool", default=False)],
        resources=["GPU"],
        help="￥0，占本机 GPU。已有产物的镜自动跳过；缺口的镜再跑同一条命令即可补，不用改提示词。",
        agent="执行前报出：将跑几镜、预计多久（用 video.plan 的数字）。跑完若退出码 3，说明有缺口，直接重跑同一条命令。"))
_add(_c("video.status", "4 出片", "批次进度", "drama",
        argv=["video", "status"], mode="sync", danger=READ,
        params=[Param("batch", "批次号（留空取最新）", "str")],
        help="读 summary.json / state.json。",
        agent="汇总：总数 / 成功 / 失败 / 待跑 / 消耗 / 用时，并列出失败段 id。"))
_add(_c("video.cloud", "4 出片", "云端 ComfyUI 出片（★按主机时长）", "drama",
        argv=["video", "run", "--engine", "cloud"], billing=PAID, danger=DANGER, gate="G5",
        flags={"--limit": "limit", "--only": "only", "--ep": "ep",
               "--comfy-url": "comfy_url", "--cloud-lifecycle": "cloud_lifecycle",
               "--cloud-name": "cloud_name", "--workflow": "workflow"},
        bools={"--yes": "yes", "--force": "force"},
        params=[Param("ep", "集号", "str", required=True, placeholder="ep01"),
                Param("yes", "确认执行（会开机并计费）", "bool", default=False),
                Param("limit", "只跑前 N 段（小样）", "int"),
                Param("only", "指定段", "str"),
                Param("comfy_url", "实例地址", "str",
                      placeholder="https://<实例>-8188.container.x-gpu.com（留空由启停流程给）"),
                Param("cloud_lifecycle", "实例启停", "enum", default="auto",
                      choices=["auto", "keep", "off"],
                      help="auto=要跑才开、跑完就关；keep=跑完保留（继续计费）；off=只用给定地址"),
                Param("cloud_name", "实例名（幂等键）", "str", placeholder="留空自动命名"),
                Param("workflow", "工作流 JSON", "str", placeholder="留空取模型确认单 -> 仓库默认"),
                Param("force", "已有产物也重跑", "bool", default=False)],
        resources=["GPU"],
        help="与本地出片**同一个执行器**，只是地址在云端。默认 auto：复用/开机/新建 -> 出片 -> "
             "停机，只停自己开的。干跑不建实例，门禁在建实例之前。",
        agent="执行前报出：实例名、集号、将跑几段、预计主机时长；**不要给单价或预估金额**"
              "（真实消耗以台账为准）。结束后提醒查成本台账。"))
_add(_c("video.rh", "4 出片", "云端出片（RunningHub，★计费）", "drama",
        argv=["video", "run", "--engine", "workflow"], billing=PAID, danger=DANGER, gate="G5",
        flags={"--limit": "limit", "--only": "only", "--resume": "resume",
               "--concurrency": "concurrency"},
        bools={"--yes": "yes"},
        params=[Param("yes", "确认计费闸门", "bool", default=False),
                Param("limit", "只跑前 N 段（小样）", "int"),
                Param("only", "指定段", "str"),
                Param("resume", "续跑批次号", "str", placeholder="20261017_141530"),
                Param("concurrency", "并发（平台硬限 ≤5）", "int", default=2)],
        resources=["RH"],
        help="★ 不加 --resume 的全量重跑 = 重复提交、重复扣费。默认通道是本机 GPU（video.run，￥0）。",
        agent="执行前必须报出：批次号、将提交段数、按台账实测的参考花费、是否续跑。等我明确确认后再执行。"))
_add(_c("video.rh.sample", "4 出片", "云端小样 1 段（★计费）", "drama",
        argv=["video", "run", "--engine", "workflow", "--limit", "1"],
        billing=PAID, danger=DANGER, gate="G4",
        flags={"--only": "only"}, bools={"--yes": "yes"},
        params=[Param("only", "指定段（更精准）", "str"),
                Param("yes", "确认计费", "bool", default=False)],
        resources=["RH"], help="先出 1 段，看过成片再决定是否全量。",
        agent="出完后提醒我：先看这一段成片，再决定是否全量。"))
_add(_c("video.rh.resume", "4 出片", "云端续跑批次（★计费）", "drama",
        argv=["video", "run", "--engine", "workflow"], billing=PAID, danger=DANGER, gate="G5",
        flags={"--resume": "resume", "--only": "only"}, bools={"--yes": "yes"},
        params=[Param("resume", "批次号", "str", required=True),
                Param("only", "只补这些段", "str"),
                Param("yes", "确认计费", "bool", default=False)],
        resources=["RH"], help="复用 taskId，不重复提交已成功的段。",
        agent="续跑前先查该批次的在途任务；告我这次补哪些段、参考花费（按台账实测，不是预估）。"))
# ===== 环节 7 剪辑：母版拼接 → 高清放大 → 字幕 ==========================
# ★ 2026-11-01：分组名从「11 拼接字幕」改为「7 剪辑」，并删掉 `media.assemble`
#   —— 它的 help 写「拼接 + 2K 放大」，argv 却是 `subtitle.py --stage upscale`（受开关
#   控制的空转分支），与 `upscale.py` 是同一件事的两个入口。
_add(_c("media.master", "5 剪辑", "① 母版拼接（封面 + 片段 + BGM）", "subtitle",
        argv=["--stage", "master"], billing=GPU, danger=WRITE,
        flags={"--ep": "ep"}, bools={"--no-cover": "no_cover", "--no-bgm": "no_bgm"},
        params=[P_EP(required=True),
                Param("no_cover", "不加首帧封面", "bool", default=False),
                Param("no_bgm", "不混 BGM", "bool", default=False)],
        resources=["GPU"],
        help="首帧封面取 09-发行/封面/cover_9x16*.png（0.8s 片头）；BGM 有 plan 才混。",
        agent="拼完告我母版时长、段数、是否带封面与 BGM，供我核对节奏。"))
_add(_c("media.upscale", "5 剪辑", "② 高清放大（RH / Topaz / 跳过）", "upscale",
        billing=GPU, danger=WRITE,
        flags={"--ep": "ep", "--backend": "backend"},
        bools={"--force": "force", "--json": "as_json"},
        params=[P_EP(required=True),
                Param("backend", "放大后端", "str", default="",
                      placeholder="留空=按 config.upscale.json；topaz / rh / off"),
                Param("force", "忽略缓存重跑", "bool", default=False)],
        resources=["GPU"],
        help="topaz=本地（￥0）｜off=跳过。产物 _master_1080x1920.mp4。",
        agent="RH 后端会花钱，提交前必须我确认；Topaz 只占本机 GPU（一次一集，中断要整集重跑）。"))
_add(_c("media.render", "5 剪辑", "③ 字幕生成与烧录", "subtitle",
        argv=["--stage", "render"], gate="G6", danger=WRITE,
        flags={"--ep": "ep", "--lang": "lang"}, bools={"--burn": "burn"},
        params=[P_EP(required=True), Param("lang", "语言", "str", default="zh"),
                Param("burn", "直接烧录", "bool", default=True)],
        resources=["GPU"],
        help="三语规范锁死（configs/subtitle-styles.json）：zh 58px/12 字、en 52px/26、es 50px/26。",
        agent="执行前先问我「要不要烧字幕」；我说不要就只交付无字幕母版，不要自己决定。"))
_add(_c("media.preview", "5 剪辑", "字幕快速预览", "subtitle",
        argv=["--stage", "render", "--preview", "{n}"], danger=WRITE,
        flags={"--ep": "ep"}, params=[P_EP(required=True), Param("n", "预览段数", "int", default=3)],
        resources=["GPU"], help="只用前 N 段快速验证字幕样式与断行。",
        agent="预览完后告我样式是否合格（落点 6:4、距底 ≥200px、文本宽 ≤70%）。"))
_add(_c("media.upscale_verify", "5 剪辑", "放大产物自检", "upscale",
        argv=["--verify-only", "--json"], mode="sync", danger=READ,
        flags={"--ep": "ep"}, params=[P_EP(required=True)],
        help="读 <ep>_upscale.json 的自检项。",
        agent="列出未过的自检项；若退化为插值（锐度增益不足）要明确告警。"))

# ===== 环节 12 验收与结账 ==================================================
_add(_c("time.plan", "6 验收", "耗时预估：单集 / 整季", "time_model",
        argv=[], mode="sync", danger=READ,
        flags={"--episodes": "episodes", "--shots": "shots",
               "--shot-seconds": "shot_seconds", "--images": "images"},
        bools={"--upscale": "upscale", "--calibrate": "calibrate", "--json": "as_json"},
        params=[Param("episodes", "算几集", "int", default=1),
                Param("shots", "每集镜头数", "int", default=8),
                Param("shot_seconds", "平均每镜秒数", "float", default=6.0),
                Param("images", "每集资产图张数", "int", default=12),
                Param("upscale", "计入超分耗时", "bool", default=False),
                Param("calibrate", "用台账实测反推系数", "bool", default=False)],
        help="成本口径 = 时间。默认系数是经验值；跑过几次后加 calibrate 就换成本机实测。",
        agent="报出单集与整季的总时长、瓶颈阶段，并说明系数是否已校准。"))
_add(_c("time.report", "6 验收", "耗时台账：已跑了多久", "time_report",
        argv=[], mode="sync", danger=READ,
        flags={"--ep": "ep"}, bools={"--per-shot": "per_shot", "--json": "as_json"},
        params=[Param("ep", "只看这一集", "str"), Param("per_shot", "逐镜明细", "bool", default=False)],
        help="按集 / 按阶段 / 逐镜汇总实际耗时（读 video-pipeline/ledger/）。",
        agent="指出哪个阶段最费时间、哪几镜明显偏慢（可能是参考图或提示词的问题）。"))
_add(_c("episode.preflight", "6 验收", "集级前置体检", "preflight_ep",
        argv=["{eps}"], mode="sync", danger=READ,
        params=[Param("eps", "集号（可多个）", "str", required=True, placeholder="ep01 ep02")],
        help="交付前的集级体检。",
        agent="列出未过项与其影响的交付物。"))

_add(_c("release.export", "7 发行", "导出发布版（EpisodeNN.mp4）", "release_export",
        argv=[], billing=FREE, danger=WRITE,
        flags={"--ep": "ep", "--target": "target", "--digits": "digits"},
        bools={"--all": "all", "--apply": "apply", "--link": "link",
               "--no-media-check": "no_media_check", "--json": "as_json"},
        params=[Param("ep", "只导出这一集", "str", placeholder="ep01（留空=全部）"),
                Param("target", "目标规格", "str", default="1080x1920"),
                Param("digits", "编号位数", "int", default=2),
                Param("all", "导出全部找到的集", "bool", default=True),
                Param("apply", "真的写盘（默认干跑）", "bool", default=False),
                Param("link", "用硬链接代替复制（省空间，需同盘）", "bool", default=False),
                Param("no_media_check", "跳过出口门禁（仅供预览，正式发行别用）", "bool", default=False)],
        help="命名严格 EpisodeNN.mp4，落 09-发行/剧集/。默认干跑；--apply 才写。"
             "出口门禁会查规格（1080x1920/SAR 1:1）与硬字幕，不过的不进 plans。",
        agent="干跑先让用户看「会导出哪几集、从哪来」；写盘前必须确认，并说清会覆盖同名文件。"))

# ===== 环节 13 合规与发行 ==================================================
_add(_c("compliance.ep", "7 发行", "发布前合规预检（G8 · 单集）", "compliance",
        argv=[], mode="sync", danger=READ, gate="G8",
        flags={"--ep": "ep", "--q1": "q1", "--q2": "q2", "--q3": "q3", "--note": "note"},
        params=[P_EP(required=True),
                Param("q1", "方法是否出现", "enum", required=True, choices=["yes", "no"]),
                Param("q2", "主体是否出现（含背景/倒影/屏幕）", "enum", required=True, choices=["yes", "no"]),
                Param("q3", "身份是否歧义（校服/童装风）", "enum", required=True, choices=["yes", "no"]),
                Param("note", "补充说明", "str")],
        help="发布前三问必须全「否」；有整改项退出码 2，不可发布。",
        agent="三问必须由我逐条回答，不要替我判断；有整改项时给出「主体不出现 / 方法不出现 / 身份不歧义」的最小改法。"))
_add(_c("compliance.all", "7 发行", "整剧合规预检（受限集数 + AIGC）", "compliance",
        argv=["--all"], mode="sync", danger=READ, gate="G8",
        flags={"--aigc-label": "aigc", "--restricted": "restricted", "--total": "total"},
        params=[Param("aigc", "全剧是否统一标注 AIGC", "enum", required=True, choices=["yes", "no"]),
                Param("restricted", "已受限集数", "int", default=0),
                Param("total", "总集数", "int", default=40)],
        help="受限集数占比 ≤10%；未标注 AIGC = 降流。",
        agent="算出余量（ceil(0.1×总集数) − 已受限），并提示 AIGC 标注口径。"))

# ===== 诊断 ===============================================================
_add(_c("preflight.gen", "9 诊断", "生成能力预检（图像 + 视频，免费）", "drama",
        argv=["preflight", "--only", "gen"], mode="sync", danger=READ, billing=FREE,
        help="按模型确认单逐条核：守卫放行 / 服务在线 / 版本 / 节点类 / 模型文件 / 必需输入。"
             "本地与云端用的是同一份判据（gen_preflight -> cloud.health），不另算一套。",
        agent="按「通道 · 状态 · 缺什么 · 下一步」四列报告；缺模型时把「本机就能跑的替代工作流」一并给出。"))
_add(_c("diag.preflight", "9 诊断", "一次性体检（免费）", "drama",
        argv=["preflight"], mode="sync", danger=READ,
        help="生成通道 + Key 分级 + 引擎 doctor + check + 预演（六段，可用 --only 只跑某段）。",
        agent="按「环境 / 密钥 / 通道 / 数据」四类汇总问题清单，并给出可照抄的修法。"))
_add(_c("diag.rhdoctor", "9 诊断", "RunningHub 双 Key 体检", "rhdoctor",
        argv=["--json"], mode="sync", danger=READ, billing=FREE,
        flags={"--check": "check"},
        params=[Param("check", "只查一类", "enum", default="",
                      choices=["", "workflow", "ai-app", "model", "llm"])],
        resources=["RH"],
        help="只读探测：消费级 Key 与企业级 Key 是否可用、站点对不对、工作流能不能取到。不提交任务、不扣费。",
        agent="按「哪一类可用 / 不可用 + 原因 + 改法」三列报告。"))
_add(_c("diag.comfy", "9 诊断", "本地 ComfyUI 在线体检", "comfy_check",
        argv=["--check"], mode="sync", danger=READ,
        help="按「连接中心」里配的地址探 /system_stats（不再写死 8188 —— 改过端口或上云后就对不上）。",
        agent="不在线就告我启动方法，并把实际探测的地址打出来。"))
_add(_c("diag.guide", "9 诊断", "打印速查（drama.py guide）", "drama",
        argv=["guide"], mode="sync", danger=READ, help="命令速查全文。",
        agent="把速查整理成「常用五条命令」。"))


# ===== 环境自检（零网络） ==================================================
_add(_c("env.check", "9 诊断", "环境自检（JSON，零网络）", "env_check",
        argv=["--json"], mode="sync", danger=READ,
        help="Python / Pillow / ffmpeg / ffprobe 是否齐备，缺一即停。",
        agent="按「缺什么 + 怎么装」两列报告，不要贴整段 JSON。"))

# ===== 剧本连续性（5.5 五锚，只读） ========================================
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
