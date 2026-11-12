# SoloDrama 技术交接文档（Codex 接手版 · v2）

> 交接基线：`main` @ `88324c6`（2026-11-12 复核，本地与 GitHub 一致）
> 目标读者：接手继续开发的编码 Agent（Codex / Claude Code）与代码评审人
> 使用方式：§0 读完 → §1–§3 建立模型 → §6 记住红线 → §9 领任务。**§6 违反即破坏性改动。**

---

## 0. 交接速览

### 0.1 交接卡

| 项 | 值 |
|---|---|
| 仓库 | `github.com/Hejunlong27/SoloDrama`（Apache-2.0） |
| 基线 | `main` @ `88324c6`，工作树干净 |
| 本地路径（参考） | `D:\编程\SoloDrama` |
| 语言 / 运行时 | Python 3.10+（**实测 3.13**）；前端原生 ES Module |
| 代码规模 | `stages/ web/ tools/ cloud/` 下 200+ Python 文件；23 个前端视图；118 个 HTTP 端点 |
| 引擎依赖 | `httpx==0.28.1`、`Pillow==13.0.0` |
| Web 依赖 | `fastapi==0.162.0`、`uvicorn==0.54.0`、`httpx==0.28.1` |
| 剪辑依赖（可选） | `requirements-edit.txt` → `pyJianYingDraft==0.3.1` |
| 外部二进制 | ffmpeg / ffprobe（必需）；whisper.cpp、Topaz、剪映（可选） |
| 数据源 | **文件系统**；SQLite 仅作业队列/审计/事件流（可重建） |
| 核心文件 | `stages/production/scripts/nodes.py`（流程）、`stages/_layout.py`（路径）、`web/app.py`（端点） |

### 0.2 三条命令确认起点

```bash
python tools/env_check.py --json
python -m pytest tools/tests stages/import/tests -q     # 期望 112 passed
python web/launcher.py --no-browser                     # 127.0.0.1:8788，/ → /studio/
```

`env_check.py --json` 的必需项只有四项：Python 3.10+、Pillow、ffmpeg、ffprobe。其余缺失只影响对应能力。

### 0.3 权限边界（先明确你被授权做什么）

| 类别 | 允许 | 需要人确认 |
|---|---|---|
| 读代码、跑测试、跑干跑 | ✅ 随时 | — |
| 改文档、加测试、修 bug | ✅ | — |
| 改引擎业务规则（判据、门禁、契约字段） | — | ✅ 必须先给方案与验收标准 |
| 任何 ★计费动作（云端实例 / RunningHub / 放大服务） | — | ✅ 必须先报价 |
| 改提示词 / 剧本 / 画风语义 | — | ✅ 属内容决策 |
| `git commit` | ✅（按 §12 纪律） | push 前告知 |
| 删除用户工作区文件 | ❌ | ✅ 且需二次确认 |

---

## 1. 系统全貌

### 1.1 问题与设计取舍

SoloDrama 把「一句话点子 → 可发布竖屏短剧」拆成**创作**与**执行**两半：

- 创作是**非确定性**的（LLM 写剧本、写提示词），交给可插拔的题材 Skill（Markdown 模板）
- 执行是**确定性**的（同样的输入必须出同样的产物），交给 Python 脚本 + ComfyUI
- 两半之间只隔**一份 JSON 契约**（制作包 `pack/`）

**这样换题材模板时，引擎一行不用改。** 这是全仓库最重要的架构决策，任何「让引擎理解剧情」的改动都是倒退。

配套的三个推论：

1. 引擎**不创作**：提示词逐字搬运，缺字段报错，不润色、不猜、不补。
2. 流程归代码，内容归模型：状态机只看磁盘，LLM 只决定「这一节点写什么」，不决定「下一步做什么」。
3. 层与层传文件，不传内存状态：任何阶段都可以单独重跑。

### 1.2 四层结构

```
① 创作层  人 × LLM
   stages/creation/skills/ + web/core/{creation,skills,llm}
   → 00-创作/01-企划案.md、02-资产库.md、03-分集剧本.md、04-导演手册/第NN集.md

② 契约层  机械转换（确定性）
   stages/import/{md2pack,pack_spec,pack_import,h3_prompt,prompt_marks}
   → pack/assets/*.json、pack/episodes/*.json → 06-提示词/<ep>/*.json

③ 引擎层  只认契约
   stages/{assets,production,subtitle,video,edit}/scripts + cloud/
   → 04-资产 05-分镜 06-提示词 07-成片 08-合规 09-发行

④ 控制层  Studio（只读聚合 + 作业调度）
   web/app.py、web/core/*、web/ui/studio
```

### 1.3 进程模型（改代码前必须知道）

```
浏览器 ──HTTP──> FastAPI（单进程 uvicorn，端口 8788）
                    │
                    ├─ 读文件（只读聚合，直接 Python 读盘）
                    └─ subprocess ──> Python 脚本（每次一个新进程，cwd=仓库根）
                                          └──HTTP──> ComfyUI(8188) / 云端 / RunningHub
```

- **Web 不 import 引擎**。`grep -r "from stages" web/` 必须零命中。新增能力 = 新脚本 + 子进程。
- 引擎脚本每次冷启动，不共享内存；跨调用的状态只能落盘（`.drama/`、`ledger/`）。
- 作业队列用 `sqlite3`（`web/var/jobs.db`），只为「谁在跑、跑到哪、日志在哪」，不是业务数据。

### 1.4 目录地图（含改动风险）

| 路径 | 职责 | 风险 |
|---|---|---|
| `stages/_layout.py` | **目录名唯一真源**：`stage_dir()` / `data_dir()` / `assets_dir()` / `layout.json` 读写 | 极高 |
| `stages/production/scripts/_ws.py` | 工作区解析与校验（导入期 `sys.exit`） | 极高 |
| `stages/production/scripts/nodes.py` | 13 节点状态机 + 判据 + 环 | 极高 |
| `stages/import/pack_spec.py` | 制作包规则引擎（`SHOT0xx`） | 极高 |
| `stages/import/h3_prompt.py` | 视频提示词六段式（`SECTIONS` 顺序即契约） | 极高 |
| `stages/import/prompt_marks.py` | 台词 `<d>` 标记的解析与注入 | 高 |
| `stages/import/pack_import.py` | 制作包 → `06-提示词/<ep>/` 五文件 | 高 |
| `stages/import/md2pack.py` | 创作 Markdown → 制作包 | 高 |
| `stages/production/scripts/drama.py` | 面向人的 CLI 总入口（19 个子命令） | 高 |
| `stages/production/scripts/release_export.py` | **发布版唯一导出** | 极高 |
| `stages/subtitle/scripts/subtitle.py` | 母版拼接 + 字幕对齐 + 渲染 | 极高 |
| `stages/subtitle/scripts/upscale.py` | 放大（topaz / rh / off） | 高 |
| `stages/edit/scripts/edit_draft.py` | 剪映草稿生成 | 高 |
| `stages/video/workflow/scripts/` | 出片引擎（run/doctor/check_billing/report + `engine/`） | 高（★计费） |
| `stages/assets/scripts/` | 资产清单与净化（`asset_md.py` / `sanitize.py`） | 中 |
| `web/app.py` | 118 个端点（单体） | 高 |
| `web/core/*` | 30 个聚合/适配/作业模块 | 中高 |
| `web/core/llm/` | LLM 网关（providers / gateway / store / templates / safety） | 中 |
| `web/ui/studio/` | 新工作台（23 视图，零构建） | 中 |
| `web/ui/`（其余） | 旧控制台，**冻结**，只留 `advanced.html` 逃生口 | 低 |
| `cloud/` | 云端 ComfyUI 镜像编排（`python -m cloud`） | 中（★计费） |
| `configs/` | 通道、画风、字幕样式、剪辑默认值、模型确认单模板 | 中 |
| `docs/pack/` | 制作包与提示词契约 | 极高（与引擎门禁同源） |
| `manifest.sha256` | 受管文件完整性清单 | 每次改动都重建 |

### 1.5 模块清单（找代码时用）

**引擎 / 生产脚本**（`stages/production/scripts/`）

| 文件 | 职责 |
|---|---|
| `drama.py` | CLI 总入口：`init/next/do/nodes/graph/skip/status/preflight/pack/assets/refs/models/style/video/report/balance/cost/guide/bgm` |
| `nodes.py` | 13 节点、六态、四层环、判据、`_done/_skip/_spend` |
| `init_project.py` | 建项目骨架（目录 + 模板） |
| `drama_profile.py` | `drama.json` 单一档案的唯一读写 |
| `capabilities.py` | 能力卡：把验证过的通道参数固化成数据 |
| `model_gate.py` | 生图/视频模型「首次执行前确认」门禁 |
| `style_gate.py` | 画风确认门禁 |
| `gen_preflight.py` | 批量开跑前的一次性预检 |
| `gen_assets_local.py` | 本地 ComfyUI 出资产图（￥0） |
| `gen_assets_rh_workflow.py` | RunningHub 工作流出资产图（★计费） |
| `gen_boards.py` | 每镜一张 9:16 分镜图 |
| `prepare_refs.py` | 参考图瘦身（不联网、不计费） |
| `wire_new_assets.py` | 新资产瘦身 + 接进 `characters.json` |
| `ingest_check.py` | 入 `data/` 的生成端门禁 |
| `episode_preflight.py` | 单/多集出片前置体检（零计费） |
| `release_check.py` | 发行资料齐全度门禁 |
| `release_export.py` | 发布版导出（严格命名 + 固定落点） |
| `delivery_spec.py` | 交付规格唯一真源 + 规格体检 |
| `compliance_precheck.py` | 发布前平台合规预检 |
| `compliance_media_check.py` | 画面级合规门禁 |
| `copyright_kit.py` | 版权资料三件套 |
| `cost_model.py` / `time_model.py` | 成本 / 耗时口径（唯一真源） |
| `cost_ledger.py` / `run_ledger.py` / `time_report.py` | 台账与报表（`_ledger_core.py` 是实现） |
| `bgm.py` | BGM 库、铺排、混音 |
| `rh_doctor.py` | RunningHub 双 Key 体检（默认零网络） |
| `migrate_assets.py` / `migrate_profile.py` | 历史数据迁移 |

**Web 核心**（`web/core/`）

| 模块 | 职责 |
|---|---|
| `paths.py` | Web 层路径与运行时常量（唯一真源） |
| `studio.py` | Studio 只读聚合：Episodes / Shots / Cost / Overview / `assets_dir()` |
| `inventory.py` | 「做出了什么、花了多少」的用户端口径 |
| `reader.py` / `artifacts.py` | 只读聚合 / 工作区文件安全访问 |
| `runner.py` | **白名单命令执行器**（Web 层唯一写通道） |
| `commands.py` | 白名单命令目录（UI 按钮来源） |
| `jobs.py` | 作业队列 + 资源锁 + 事件流 + 审计（sqlite3） |
| `pipeline.py` | 流水线模式（按环节推进，`STAGE_MAP`） |
| `adapters.py` / `jsonout.py` | CLI 适配 / 从输出稳定取 JSON |
| `agent.py` | 会动手的助手（对话 → 工具调用） |
| `canvas.py` / `graph.py` | 剧集画布 / 节点画布 |
| `characters.py` | 角色档案归并（含 `drift` 分叉检测） |
| `connections.py` | 三类外部通道的配置、注入、探测（产品层唯一真源） |
| `comfy_{launcher,ports,probe,store}.py` | 本地 ComfyUI 启停 / 端口 / 探活 / 工作流存取 |
| `generators.py` | 图像/视频通道统一台账 |
| `generation_models.py` | 模型级参数能力加载与请求映射（真源 `configs/generation-models.json`） |
| `media_tasks.py` | 媒体任务状态、远端 task ID、报价、供应商暂报 `usage`、后台最终 `settled_cost` 与断点恢复记录 |
| `creation.py` / `skills.py` / `styles.py` | 创作产物 / 题材模板 / 画风目录 |
| `health.py` / `monitor.py` / `timing.py` | 体检与修复 / 资源快照 / 全局时间账 |
| `ux.py` | 用户语言层（把技术话翻成人话） |
| `updater.py` | 一键下载/更新 |
| `llm/{gateway,providers,store,templates,safety,schema,budget,errors}.py` | LLM 网关全家桶 |

**云端**（`cloud/`）：`cli.py`（`python -m cloud <up|attach|status|down|probe|cost|doctor>`）、`provisioner.py`（实例生命周期）、`session.py`（任务级：要跑才开）、`pull.py`（收产物）、`ledger.py`（GPU 时长台账）、`transport.py`（素材搬运）、`health.py`（就绪三查）。

---

## 2. 流程：13 节点状态机

### 2.1 节点表（含判据算法）

真源 `stages/production/scripts/nodes.py`。**写「12 节点」「16 环节」「23 节点」都是过期口径**（见 §14）。

| # | id | 环节 | 读 | 产物 | 判据实际算法 |
|---|---|---|---|---|---|
| 1 | `import.pack` | 导入 | — | `06-提示词/<ep>/shots.json` | `imported`：`shots.json` + `boards.json` + `h3_prompts.json` 三件存在，且 shots 非空 |
| 2 | `asset.render` | 资产 | `import.pack` | `04-资产/refs.json` | `assets`：refs.json 里 characters/scenes/props 每个 key 都能解析到图（三种相对基准都认） |
| 3 | `import.bind` | 导入 | `asset.render` | `_done/import.bind.<ep>.json` | `five`：五文件齐（+`characters.json` `scenes.json`） |
| 4 | `board.frame` | 分镜图 | `import.bind` | `04-资产/boards/<ep>/` | `boards`：图片数 ≥ 镜数 |
| 5 | `import.gate` | 导入 | `board.frame` | `_done/import.gate.<ep>.json` | `cmd:ingest_check.py` 退出码 0 |
| 6 | `video.resolve` | 出片 | `import.gate` | `_done/video.resolve.<ep>.json` | `cmd:capabilities.py check` 退出码 0 |
| 7 | `video.batch` | 出片 | `video.resolve` | `07-成片/<ep>/shot_00N/final.mp4` | `segments`：段数 ≥ 镜数 |
| 8 | `video.audit` | 出片 | `video.batch` | `_done/video.audit.<ep>.json` | `audit`：逐段 ffprobe，时长 > 1.0s 且无失败 |
| 9 | `edit.master` | 剪辑 | `video.audit` | `07-成片/<ep>/*_master.mp4` | `master`：按名找文件 |
| 10 | `edit.upscale` | 剪辑 | `edit.master` | `*_master_1080x1920.mp4` | `upscaled`：按名找；认 `*_upscale.json` 的 `skipped=true` |
| 11 | `edit.subtitle` | 剪辑 | `edit.upscale` | `*_subbed.mp4` | `subtitled`：按名找（`cues=0` 时脚本自己拒绝出片） |
| 12 | `edit.draft` | 剪辑 | `edit.subtitle` | `07-成片/<ep>/_draft/draft_manifest.json` | `draft`：只认 `verdict.pass`，不看目录存在 |
| 13 | `edit.release` | 剪辑 | `edit.draft` | `09-发行/剧集/EpisodeNN.mp4` | `release`：文件名匹配 `Episode\d{2,3}\.mp4`，且**按当前集**判（无 `--ep` 才看全剧） |

回流白名单（`reflow`，只能回这些，不许自由跳）：

```
import.pack    → []
asset.render   → [import.pack]
import.bind    → [asset.render]
board.frame    → [import.bind]
import.gate    → [import.bind, board.frame]
video.resolve  → [import.gate]
video.batch    → [video.resolve]
video.audit    → [video.batch]
edit.master    → [video.batch]
edit.upscale   → [edit.master]
edit.subtitle  → [edit.upscale]
edit.draft     → [edit.subtitle]
edit.release   → [edit.subtitle]
```

### 2.2 六态 / 四层环 / 退出码

**状态**：`absent`（产物不存在）、`stale`（产物比上游旧）、`failed`（判据不过）、`passed`、`skipped`（`_skip/<node>.json` 且带理由）、`blocked`（上游未通过）。UI 必须同名。

**环**

| 层 | 触发 | 预算 | 耗尽后 |
|---|---|---|---|
| L0 retry | 网络 / 显存 / 上传失败 | 2 次，退避 5s → 15s | 进 L1 |
| L1 repair | 判据不过（内容问题） | 3 次，**每次必须改一个变量** | 进 L2 |
| L2 reflow | L1 耗尽 | 1 次，只回白名单 | `blocked_human` |
| L3 batch | 集级失败 | 集数 | 全局 blocked，release 不放行 |

`variant_hash` 防抖动：同一修复方案第二次出现直接判 `stuck`（退出码 5）。
`_spend/<node>.json` 记 task_id 与金额，重入先比对，已花的不重花。

**退出码**（不要另发明）

| 码 | 含义 | 典型场景 |
|---|---|---|
| 0 | 通过 / 干跑成功 | — |
| 2 | 判据不过（可修） | 缺文件、张数不够、命名不规范 |
| 3 | 缺输入（上游没产物） | 上游节点未跑 |
| 4 | 需要人工 | L2 耗尽 / 计费闸门 / 门禁不过 |
| 5 | stuck | 修复方案与上次相同 |
| 6 | 未实现 | 节点执行体未接 |

### 2.3 从零到成片的完整命令序列

```bash
# ① 建项目（写结构 + 模板，不写内容）
python stages/production/scripts/drama.py init \
  --workspace "<剧目录>" --title "剧名" \
  --episodes 30 --ep-seconds 60 \
  --track live_action --look <look-id> --narrative dialogue --aspect 9:16 \
  --image-engine local_comfyui --video-engine local_comfyui

# ② 确认前置（画风 + 模型）—— 不做这一步，出图/出片会被门禁拦下（rc=4）
python .../drama.py style  --workspace "<ws>" list
python .../drama.py style  --workspace "<ws>" set live_action --look <look-id>
python .../drama.py models --workspace "<ws>" set image=local_comfyui video=local_comfyui

# ③ 人工/LLM 写：03-剧本/blueprint.md、ep_01.md、05-分镜/ep01_storyboard.md、04-资产/design/roster.json

# ④ 循环推进（每步先看，再跑）
python .../drama.py next  --workspace "<ws>" --ep ep01      # 只读，告诉你下一步
python .../drama.py do import.pack --workspace "<ws>" --ep ep01 --dry-run
python .../drama.py do import.pack --workspace "<ws>" --ep ep01

# ⑤ 出图与出片（★计费动作要人确认）
python .../drama.py assets --workspace "<ws>" --engine local --submit
python .../drama.py video  --workspace "<ws>" plan
python .../drama.py video  --workspace "<ws>" run --yes --limit 1     # 先出小样

# ⑥ 后期四步（顺序不可换）
python .../drama.py do edit.master   --workspace "<ws>" --ep ep01
python .../drama.py do edit.upscale  --workspace "<ws>" --ep ep01
python .../drama.py do edit.subtitle --workspace "<ws>" --ep ep01
python .../drama.py do edit.draft    --workspace "<ws>" --ep ep01

# ⑦ 导出（唯一出口）
python stages/production/scripts/release_export.py --all --apply
```

### 2.4 干跑输出长什么样

```
$ drama do import.pack --workspace <ws> --ep ep01 --dry-run
==========================================================================
节点 import.pack ｜ 现状 absent（产物不存在：<ws>\06-提示词\ep01\shots.json）
触发 drama do import.pack --ep ep01
执行 python stages/import/pack_import.py --pack {ws}/pack --apply
==========================================================================
[DRY-RUN] <python> stages/import/pack_import.py --pack <ws>/pack --apply --workspace <ws> --ep ep01
```

`nodes.py` 会把 `{ws}` 展开、补齐 `--workspace` / `--ep`。**干跑与真跑用同一份 argv**——这是防止「干跑通过、真跑失败」的设计，改节点时不要另拼一条命令。

### 2.5 跳过语义

```bash
python .../drama.py skip edit.draft --workspace "<ws>" --ep ep01 --reason "只要母版做内部预览"
```

写 `_skip/<node>.json`（必须带 `reason`）。跳过后下游把该节点按 `skipped` 处理，**不阻塞**。不要用「把产物删掉」来跳过——那会让下游变 `blocked`。

### 2.6 两套流程叙事的历史包袱（重要）

仓库里同时存在两套「环节」说法，**只有一套是现行**：

| 说法 | 出处 | 状态 |
|---|---|---|
| **5 环节 13 节点**（导入/资产/分镜图/出片/剪辑） | `nodes.py::STAGES/NODES` | ✅ **现行唯一真源** |
| 11 环节（调研→剧本→…→定稿）、S1–S11 | `drama guide` 输出、`web/core/pipeline.py` 头部 docstring、`pipeline.js` | ❌ 旧编排，`workflow.py` 已移除 |
| 16 环节、七环节 23 节点、23 节点 | `docs/Agent项目技术文档.md`、`drama.py` 注释与 argparse help | ❌ 过期文案 |

**Codex 注意**：不要按 `drama guide` 里的 `setup / workflow / pipeline` 敲命令——这三个子命令 2026-11-01 已删除，argparse 会直接报 `invalid choice`。现行只有 §1.5 列出的 19 个子命令。修文案属 P1 T14，**不要混进功能改动**。

---

## 3. 数据与契约

### 3.1 工作区骨架（`init` 的真实产物）

```
<剧目录>/
├── layout.json                 # 目录映射
├── drama.json                  # 四维档案 + 集数 + 通道确认
├── 03-剧本/{blueprint.md, ep_01.md, README.md}
├── 04-资产/
│   ├── refs.json               # 参考图登记（三类 key）
│   ├── design/roster.json      # 角色名册（人写的）
│   ├── {characters,scenes,props}/   # 资产图落点
│   └── boards/<ep>/            # 分镜图
├── 05-分镜/ep01_storyboard.md
├── 06-提示词/<ep>/{shots,boards,h3_prompts,characters,scenes}.json
├── 07-成片/<ep>/{shot_001..N/final.mp4, *_master.mp4, *_master_1080x1920.mp4, *_subbed.mp4, _draft/}
├── 08-合规/
├── 09-发行/{剧集/EpisodeNN.mp4, 封面, 版权资料}
└── video-pipeline/             # 引擎视角的 workspace（engine_root）
    ├── config.local.json       # 唯一可写运行配置
    ├── ledger/runs/            # ★钱与时间的唯一证据
    ├── logs/
    └── output/
```

`.drama/`（在剧目录根）存状态：`_done/<node>.<ep>.json`、`_skip/<node>.json`、`_spend/<node>.json`、循环记录。

### 3.2 `layout.json` 的双层相对路径（头号踩坑点）

```json
{
  "layout_version": 1,
  "engine_root": "video-pipeline",
  "stages": { "script": "03-剧本", "assets": "04-资产", "storyboard": "05-分镜",
              "prompts": "06-提示词", "film": "07-成片", "compliance": "08-合规",
              "release": "09-发行" },
  "data_rel": "../06-提示词",
  "out_rel":  "../07-成片",
  "assets_rel": "../04-资产"
}
```

**`data_rel` / `out_rel` / `assets_rel` 是相对于 `engine_root`（`video-pipeline/`）的**，所以带 `../`。它们会被回填进 `video-pipeline/config.local.json` 的 `data_dir` / `out_dir` / `assets_dir`。

- 路径一律走 `stage_dir(ws, key)` / `data_dir(ws)` / `assets_dir(ws)`，**不要自己 `ws / "04-资产"`**。
- 用户可改 `layout.json` 的目录名；硬编字面量会在那种项目上静默错位。
- `assets_dir()` 有历史兼容（`legacy_assets_dir`），读它、不要重写。

### 3.3 `drama.json`

```json
{
  "format":   { "track": "live_action", "look": "", "narrative": "dialogue", "aspect": "9:16" },
  "episodes": { "count": 30, "seconds": 60 },
  "channel":  { "image": {"engine": "local_comfyui", "capability": ""},
                "video": {"engine": "local_comfyui", "capability": ""} },
  "confirmed": { "format_at": "", "channel_at": "" }
}
```

`format` 四维正交：形态 / 视觉 / 叙事 / 画幅。**改这里等于改全剧设定**，必须重跑对应门禁。

### 3.4 制作包 `pack/`（真实字段）

```
pack/
├── pack.json
├── assets/{characters,scenes,props}.json
└── episodes/epNN.json
```

`pack.json`：

```
spec, title, slug, logline,
skill:{name,version},
delivery:{width,height,fps,episode_count,target_duration},
style_lock, negative,
aspect:{character,scene,prop,board,video}
```

`assets/*.json`：`{spec, kind, items:[{id,name,role,anchors,variants:[{code,label,kind,prompt}]}]}`

`episodes/epNN.json`：

```
{spec, episode, title, duration_total,
 shots:[{id, duration, ratio, cast:[{asset,variant}], board_prompt, video_prompt, dialogue}]}
```

字段级约束、`SHOT0xx` 编号、命名规范在 `docs/pack/PACK-SPEC.md`。**改字段前先读它**——`pack_spec.py` 的校验与它同源。

### 3.5 导入产物（`06-提示词/<ep>/` 五文件）

| 文件 | 结构 | 说明 |
|---|---|---|
| `shots.json` | `[{shot_id, ratio, crop, board_ref, cast, character_refs, scene_refs}]` | 镜头表（**list**，不是 dict） |
| `boards.json` | 分镜图索引 | 分镜路径与镜号映射 |
| `h3_prompts.json` | `{shot_001: {prompt, duration, ratio}, …}` | 单镜提示词（**dict**，key 是 shot_id） |
| `characters.json` | 角色参考表 | 资产图出完后回填（`import.bind` 就是为这个存在） |
| `scenes.json` | 场景参考表 | 同上 |

顺序陷阱：**先导入再出图，然后必须重跑同一条导入命令回填参考表**。图没出就导入会写出空参考表，出片时报「key 找不到」，看起来像导入坏了，其实只是顺序反了——这就是 `import.bind` 独立成节点的原因。

### 3.6 台账与成本口径

`video-pipeline/ledger/runs/<batch_id>__<shot_id>.json`：

```json
{ "shot_id": "shot_007", "episode": "ep01", "stage": "video", "created_at": "…",
  "attempts": [{ "status": "SUCCESS", "billed": true,
                 "usage": { "consumeCoins": 12, "consumeMoney": 0.06 },
                 "elapsed": 96.4, "task_id": "…", "error_class": "", "error": "" }] }
```

- 口径已从「花了多少币」改为「占了多少 GPU 时间」，新代码看 `sec`，`coins/money` 只保兼容。
- **金额总数只认 `inventory.spend`**（按 taskId 去重，汇率只在那算一次）。不得写第二套聚合。
- 供应商不返金额时写「未知」，**不许回退成 0 或编默认价**（P0 T1 就是这件事）。

### 3.7 不可重建（禁止任何清理逻辑触碰）

| 文件 | 原因 |
|---|---|
| `layout.json` | 用户自定义目录名，重建即丢 |
| `ledger/runs/*` | 唯一的钱与时间证据 |
| `_cover_lead.json` | 母版实测偏移，重算需重跑 ffprobe，且可能与已发布版不一致 |
| `model-plan.json` | 人工决策 |
| `copyright.json` | 法律信息，禁止编造 |
| 用户素材（图/视频/剧本） | 不可再生成 |

---

## 4. Web 层

### 4.1 三条铁律（有机器可查的依据）

1. **Web 不 import 引擎**：`grep -r "from stages" web/` 零命中。
2. **路径不由前端拼**：真源 `web/core/studio.py` / `stages/_layout.py`。
3. **零构建**：无 npm / 打包器 / node_modules；`_FreshStatic` + 版本查询串是防缓存修复。

### 4.2 端点（118 个，9 组）

实测：`grep -cE '@app\.(get|post|put|delete|websocket)' web/app.py` → **118**
（`docs/architecture/current-api.md` 标题仍写 111，是旧计数；正文注释已更新。）

| 组 | 代表端点 |
|---|---|
| 健康与运行时 | `/api/health` `/api/health/checks` `/api/monitor` `/api/locks` |
| 工作区与项目 | `/api/workspaces` `/api/projects/create` `/api/workspaces/current` |
| Studio 聚合（页面主力） | `/api/studio/{overview,workflow,shots,episodes,prompt,cost,release,cover,image-channel}` |
| 作业与事件 | `/api/jobs` `/api/jobs/{id}/stream` `/api/run` `/api/commands` `/api/audit` |
| 生成通道 | `/api/connections` `/api/comfy/*` `/api/generators` |
| 创作与 LLM | `/api/create/*` `/api/skills/*` `/api/llm/*` |
| 图解与画布 | `/api/canvas/*` `/api/graph` |
| 文件与静态 | `/api/file` `/api/artifacts` `/media` `/api/styles` |
| 旧控制台 | `/api/overview` `/api/pipeline` `/api/gates` `/api/glossary` 等 |

纪律：
- UI **只用已有端点**；要新数据先想「能否组合得出」。
- 新增写端点必须过只读闸（`READONLY_MODE` → 423），并在 `current-api.md` 登记。
- `verdict` 是门禁结论不是错误码：`blocked` 时 `rc=2` 正常，页面不得显示「接口故障」。

### 4.3 23 个视图（改 UI 先看这张表）

| 视图 | 职责 | 备注 |
|---|---|---|
| `overview` | 项目驾驶舱：5 环节 / 13 节点 + 下一步 + 门禁 + 集列表 | 集号在 URL（`?ep=ep03`） |
| `workbench` | 全局视图（不依赖当前项目） | 首页 |
| `projects` / `project-list` | 项目列表 / 独立深链路由 | 导航已并入工作台 |
| `create` | 创意工作室（三栏） | 企划/剧本/导演手册 |
| `storyboard` | 分镜与拍摄（三栏） | 提示词读写 |
| `assets` | 资产中心：缺口 + 预览 + 单张重出 | 只有角色/场景/道具三类 |
| `boards` | 分镜图 | — |
| `canvas` | 剧集画布（镜号×集号） | — |
| `pipeline` | 13 节点受控调度：状态/下一步/干跑/真实执行/journal | 数据走 `/api/scheduler/*`；旧 pipeline API 仅兼容保留 |
| `post` | 后期：母版/放大/字幕 + 播放 + GPU 动作 | — |
| `release` | 发行中心：发布版 + G9 资料齐全度 + 干跑预览 | — |
| `cost` | 用时（原成本中心） | 金额显示见 P0 T1 |
| `connections` | 连接中心（Key 只进不出） | 945 行单体，待拆 |
| `models` / `generators` | 模型确认 / 通道真实状态 | 只管配置与观测 |
| `skills` | Skill 中心（磁盘模板 → 本项目用哪套） | — |
| `graph` | 节点画布 | — |
| `tasks` | 作业列表 / SSE 日志 / 取消 | — |
| `health` / `system` / `settings` | 体检 / 系统维护 / 设置 | — |
| `agent` | 助手对话 | — |

### 4.4 三条执行通道（分工不要混）

| 通道 | 语义 | 用途 |
|---|---|---|
| `POST /api/run` | 跑**一条**白名单命令 | 单步动作、按钮 |
| `POST /api/scheduler/run` | 受控 Runner 顺序推进 13 节点（默认干跑，真实执行需确认） | 调度页、自动推进 |
| `POST /api/pipeline/run` | 旧版环节计划（兼容保留） | 历史接口，不再作为 Studio 主调度 |

`web/core/runner.py` 是唯一写通道，命令必须先在 `commands.py` 登记（`CMD.danger > CMD.READ` 才需确认）。

### 4.5 只读模式

`start-readonly.cmd` → `SOLODRAMA_CONSOLE_READONLY=1`，后端对所有写端点返回 **423**。演示/评审用，不要绕过。

### 4.6 前端约定

- 改完刷页面即可（零构建）。新增视图：`web/ui/studio/js/views/<name>.js` + 在路由与导航注册。
- 配色 Token：`--fs-11` 值实为 12px（历史包袱，保留 alias）；状态色文字档用 `-ink` 后缀（浅色下满足 AA）。
- 不引入 CSS 框架 / 组件库；不暴力重命名旧 Token（22 个视图依赖）。

---

## 5. 生成通道与计费

### 5.1 通道决策（唯一真源 `<ws>/model-plan.json` 的 `choice`）

```
要出图/出片
  └─ model-plan.json 有 choice 吗？ ── 无 ──> 拒绝执行（先 models set）
       └─ 有
          ├─ local_comfyui  → 预检（地址/节点/模型/必需输入）→ 提交（￥0）
          ├─ cloud_comfyui  → 先拒 loopback → 域名在受信名单 → 预检 → 提交（★按主机时长）
          └─ runninghub     → Key + 工作流 ID 齐 → 提交（★按平台 usage）
                                └─ billing=PAID 且界面无 confirm=true → 428，先看报价
```

不允许「因为上云就放宽 `ALLOW_REMOTE`」。云端镜像 0.43.2 有 6 个坑，见 `docs/云端ComfyUI接入.md`。

### 5.2 计费保护的三层

1. **门禁层**：`model_gate.py` / `style_gate.py` / `capabilities.py` 不通过 → rc=4，不提交。
2. **HTTP 层**：PAID 动作缺 `confirm=true` → 428。
3. **台账层**：`_spend/<node>.json` 记 task_id + 金额，重入先比对，已花的不重花。

### 5.3 命令约定

- 默认**不花钱**；要真跑必须 `--submit`（资产）或 `--yes`（出片）。
- 中断后一律 `--resume <批次>`，**不重新提交**。
- `video run --limit 1` 先出小样，确认风格再放量。

---

## 6. 红线（硬约束，逐条带原因）

### R1 · 台词必须写 `<d>[Chinese] 原句。</d>`

裸引号中文会被当成「画面中应出现的文字」**烧进画面**，事后无法去除；负向词在 cfg=1 时物理无效。
真源 `stages/import/prompt_marks.py`；违规 `SHOT018` 告警；老项目 `prompt_marks.py --apply`。

### R2 · 视频提示词必须 H3 六段式

`subject_definitions → summary → retention_analysis → detailed_description → overall_soundscape → non_diegetic_music`。
真源 `stages/import/h3_prompt.py`；`SHOT019/020` 阻断、`SHOT021` 告警。
`<Picture 1>` = 分镜图，`2..` 按 `cast` 顺序。`{{Mixed n}}` 模型不认；「上传顺序：」会被画进画面。契约 `docs/pack/H3-REF2VA-PROMPT.md`。

### R3 · 发布版只有一个出口

`09-发行/剧集/EpisodeNN.mp4`，唯一导出 `release_export.py --all --apply`。
`edit.release` 是 ep 级节点，**不要给它加 `--all`**。

### R4 · 资产落点

`04-资产/{characters,scenes,props}`，禁止进 `07-成片/`。真源 `_layout.py::assets_dir()`。

### R5 · 画风不可事后更换

`docs/styles/画风库规范.md`。门禁顺序：`style → models → 资产 → 分镜 → 导入 → 出片 → 成片`。

### R6 · 剪辑四步顺序不可换

`母版 → 放大 → 字幕 → 发布版`。字幕对**母版音频**验，不是 `asr/*.wav` 切片。

### R7 · 封面偏移必须读实测值

默认封面 **0.06s**；0.06s @ 24fps 实际只出 1 帧 = 0.041667s（ffmpeg `-t` 被帧率取整）。
一律读 `<subs>/_cover_lead.json`（`cover_lead_seconds()`），按配置算会系统性晚 0.018s。

### R8 · 字幕时间必须来自声学

- `build_cues` 游标在任何 `continue` **之前**推进（无台词镜头也占时长）。
- 档位评分同时罚「漏覆盖」+「假覆盖」，否则等分铺满永远胜出。
- 缓存判据用**源指纹**（size + mtime_ns），不用 mtime / 存在性；缺指纹视为过期。
- `snap_to_voiced()` 只贴单个语音块端点，不贴并集；跨块先 `split_cues_on_gaps()`。
- `min_duration_s` 是节奏目标，不是硬门槛（0.20s 短应答不能被放弃）。
- `sync_check()` 判据是「窗口内最长**连续**人声 ≥0.12s」，不是占比。

### R9 · 金额只认 `usage.cost` / `inventory.spend`

供应商没给写「未知」；不许 0 或默认价；只允许一套聚合。

### R10 · 不猜数据

缺关键字段报错让人补。无 `model-plan.json` 的 `choice` 就拒绝执行。

### R11 · 已移除能力不要「顺手恢复」

封面引擎（`cover_prompt.py`/`cover_forge.py`）、角色差异化（`character_design.py`）、五锚连续性/FFS lint、旧工作台（`tools/cli.py`+`tools/core/`）、`workflow.py`（11 环节）。清单：`docs/operations/已退役脚本.md`。

### R12 · 零构建 / 不 import 引擎 / 旧 Token 不暴力重命名

这三条「看起来是债、其实不是」（`technical-debt.md` 末节）。

---

## 7. 测试

### 7.1 分组跑（全仓 pytest 必失败）

```bash
python -m pytest tools/tests stages/import/tests -q            # 112 passed / ~15s
python -m pytest stages/subtitle/scripts/tests -q               # 72 passed
python -m pytest web/tests -q                                   # 200 passed / ~30s
python -m pytest stages/media_api/tests -q                       # 6 passed / Mock，零外网

# production：收集阶段就 import _ws，必须先给真实工作区
python - <<'PY'
import shutil, tempfile, pathlib
src = pathlib.Path("stages/production/scripts/tests/fixtures/mini_drama")
dst = pathlib.Path(tempfile.mkdtemp(prefix="sd_ws_")) / "mini_drama"
shutil.copytree(src, dst); print(dst)
PY
SOLODRAMA_WORKSPACE="<上一步输出>" python -m pytest stages/production/scripts/tests -q   # 141 passed

# 脚本型（自带 CASES + main()，不是 pytest）
python stages/production/scripts/tests/test_nodes.py            # 22 例
python stages/edit/scripts/tests/test_edit_draft.py             # 59 例
python stages/production/scripts/tests/test_release_export.py  # 14 例
```

### 7.2 基线（2026-11-12 实跑）

| 组 | 实测 |
|---|---|
| `tools` + `import` | 112 passed |
| `subtitle` | 72 passed |
| `production` | 141 passed |
| `web` | 200 passed |
| `media_api` | 6 passed（本地 Mock） |
| 脚本型 nodes / edit / release_export | 22 / 59 / 14，全通过 |
| 分镜图 / 模型门禁脚本 | gen_boards 29；model_gate 84，全通过 |

未逐一复跑：`stages/video/comfyui/tests`、`stages/video/workflow/.../tests`、`cloud/tests`、`stages/assets/scripts/tests`（可能需要外部服务或工作区）。

### 7.3 关于「先天红」

旧记录有 6 类环境性失败（`test_repo_paths.py` P01、`test_workflow_map.py` 1 例、web 的 connections/new_actions/pipeline/skill_library/llm_e2e）。
**2026-11-12 复核：上述四组全绿。** 不要预设「红了就是环境问题」——先判断是不是自己改坏了。

### 7.4 写测试的口径

- 改口径必须改夹具。
- 夹具别依赖默认值（曾有测试靠「默认 0.8s」断言，默认改 0.06 后全红）。
- 断言表达**语义**不表达**顺序**（`REAL_ALIGN_METHODS[-1] == "asr-only"` 加一档就红）。

---

## 8. 已知坑（按证据）

| # | 现象 | 根因 | 处置 |
|---|---|---|---|
| K1 | 字幕整体错位但自检 PASS | 「不报错 ≠ 对」，等分兜底铺满缺口 | R8；对母版音频验 |
| K2 | 剪映打开草稿后读不到内容 | `draft_content.json` 被改成全 Base64，官方无解密器 | 只能「导出 SRT → `subtitle.py --from-srt`」，不要承诺直接改草稿 |
| K3 | 字幕跨静音连成一条 | `snap_to_voiced()` 贴到多块并集 | 只贴单块端点；跨块先拆 |
| K4 | 0.20s 短应答被贴到别处 | 把 `min_duration_s` 当硬门槛 | 只是节奏目标 |
| K5 | 剪映首页看不到草稿 | 索引 `root_path` 指 C 盘默认位置 | 取各草稿 `draft_root_path` 的众数 |
| K6 | 云端镜像起不来 | 0.43.2 六个坑 | `docs/云端ComfyUI接入.md` |
| K7 | 改文件后 manifest 校验红 | `Edit`/`Write` 写成 CRLF | 改回 LF；`--check` 要求双零 |
| K8 | 新文件没进 manifest | 文件集取自 git 索引 | `git add` → `--apply` → `git add manifest.sha256` |
| K9 | push 报 `No anonymous write access` | 全局 `insteadOf → gh-proxy` | `GIT_CONFIG_GLOBAL=/dev/null` + 显式 token |
| K10 | 大包 push 被 reset | 直连大包超时 | `http.version=HTTP/1.1` + `postBuffer` + `lowSpeedTime` |
| K11 | 提示词面板空且无报错 | `prompt_of()` 少拼 `<ep>/`（已修） | 真实路径 `06-提示词/<ep>/h3_prompts.json` |
| K12 | 参考图五键指同一张 | `endswith("_"+code)` 恒假（已修） | 分段匹配 + 回归测试 |
| K13 | md 改了出图还是旧的 | md / pack 双源未强制同步 | 已有 `characters.roster().drift` 检测；根治需门禁评审 |
| K14 | 全仓 pytest 跑不起来 | `_ws.py` 导入期 `sys.exit`（有意） | 逐目录跑 |
| K15 | `drama guide` 里的命令敲了报错 | setup/workflow/pipeline 已删 | 见 §2.6 |
| K16 | 发布版判据「1/30 集」永远不过 | 旧实现用全剧集数判 ep 级节点（已修 2026-11-01） | 判据按 `ctx.ep` 判 |
| K17 | 放大节点永远「找不到文件」 | 后端 `off` 时不产 `_master_1080x1920.mp4` | 判据认 `*_upscale.json` 的 `skipped` |
| K18 | 导入后出片报「key 找不到」 | 图没出就导入，写了空参考表 | 出图后重跑导入（`import.bind`） |

---

## 9. 待办与优先级

> 来自 `docs/待修清单.md` 与 `docs/architecture/technical-debt.md`。
> **动手前读原条目里的「动手前先看」与「验收标准」**，别只看摘要。

### P0 · 已定性、可直接开工

| 编号 | 任务 | 约束 | 验收 |
|---|---|---|---|
| T2 | RunningHub `status` 字段收口 | `query_status_v1` 现为候选容错，注释明写「未实测」 | 跑一次 `rh.sample`（★计费）拿真实键，收紧候选表，1 次轮询判 SUCCESS |

已完成：T1 成本中心 LLM 金额（路线 2：显示 token 与「已知/未知」，未知不回退为 0）。

### P1 · 技术债

| 编号 | 债 | 修法 |
|---|---|---|
| T6 | 一级导航 15 项平铺 | 收敛为 5 工作空间 + 驾驶舱唯一推荐动作（`main.js`） |
| T7 | `connections.js` 945 行 | 先抽 3 子组件再改视觉 |
| T11 | 两条执行通道并存 | 明确 `/api/run`（单命令）vs `/api/pipeline/run`（计划）分工 |
| T18 | 估算与实付未分列 | UI 分行 + 标来源（`.sd-cost-row` 已备） |
| T21 | 创作生成无草稿区 | 先生成到 `var/drafts/`，UI 确认后写正文（引擎侧改动，需评审） |
| T23 | 存量身份卡提示词旧口径 | `view_sheet.py` 定向改写（默认干跑、13 项自检、写前备份），不批量 |
| T25 | md / pack 双源 | 只读检测已有；根治需让 `gen_assets_local` 在分叉时拒绝出图（需评审） |
| T14 | 文案与代码口径冲突 | §14 清单，逐条改注释/UI 文案（P1 级，别混进功能改动） |

已完成、不要重做：T1（配色）/T2（硬编码色）/T3/T4/T5/T8/T9/T16/T20/T22/T24。

### P2 · 需用户决策，不要自主开工

- **全自动出片 Agent**：`docs/AGENT-PLAN.md` 是已降级历史稿，`journal.py` / `agent_runner.py` / `qa.py` / `triage.py` 均未创建。边界是「三类闸门停人」，不是无人决策。
- **UI 信息架构重写**：T13（产品文档写「12 视图」实际 23）、T14（品牌副标题 `STUDIO 0.2`）。

---

## 10. 开发 SOP（照做就不会炸）

### 10.1 加一个节点

1. 在 `nodes.py::NODES` 加一条，**六个字段必须齐**（`trigger/reads/output/check/next/reflow`，加 `run`）。
2. 判据若属新类型，在 `check_node()` 加分支，**返回 `(bool, detail)`，detail 只写数字与路径**。
3. 接进上游的 `next`、下游的 `reflow` 白名单；不允许自由跳。
4. 在 `docs/pack/` 或对应规范记一条契约。
5. 补 `test_nodes.py` 一例：干跑 argv 与真跑一致、状态能推出。
6. 跑 `python .../test_nodes.py`（22 例）与 `pytest stages/production/scripts/tests`（141 例）。

### 10.2 加一个 API 端点

1. 先问：能否由已有端点组合得出？能就不加。
2. 只读端点：在 `web/app.py` 加 `@app.get`，聚合逻辑放 `web/core/`，不要在 app.py 写业务。
3. 写端点：必须过只读闸（423），且走 `runner.py` 白名单，不直接 `subprocess`。
4. 在 `docs/architecture/current-api.md` 登记（方法/路径/作用/是否危险写）。
5. 补 `web/tests` 一例，跑 `pytest web/tests -q`（175 例）。

### 10.3 加一个前端视图

1. `web/ui/studio/js/views/<name>.js`，导出 `render(el, ctx)`（参照 `overview.js`）。
2. 在路由表 + 导航注册；视图只用已有端点。
3. 不加依赖、不加构建步骤；样式写进 `css/`，用 Token。
4. 截图自检浅色/深色两套（状态色用 `-ink` 变体）。

### 10.4 加一条生成通道

1. 先做**能力卡**（`configs/capabilities/<id>.json`）：节点映射、必需输入、实测参数。
2. 客户端放 `stages/video/.../engine/` 或 `web/core/comfy_*.py`，产出 schema **不变**。
3. 在 `model_gate` 的可选值里登记，并在预检里加「地址/节点/模型」三查。
4. PAID 通道必须走 428 + `confirm=true`；台账写 `usage`，不写估算。
5. 小样验证（1 段），把实测响应键抄回注释，删掉「未实测」标记。

### 10.5 改字幕 / 剪辑

- 字幕：先读 `stages/subtitle/references/` 与 R8；改完必须对**母版音频**跑 `sync_check()`。
- 剪辑：四步顺序不可换；剪映工程与发布版必须同源同序；`verify()` 要读回核对。

---

## 11. 故障排查决策树

```
页面打不开 / 白屏
  ├─ 端口被占？ → launcher 会自动 +1，看窗口打印的实际端口
  └─ 依赖缺？   → python tools/env_check.py --json

节点一直 blocked
  └─ 看 upstream detail：是「产物不存在」还是「判据不过」
       ├─ blocked → 上游没跑，先跑上游
       └─ failed  → 按 detail 补产物；不要手动改状态文件

出图报「缺模型 / 通道不可用」
  ├─ model-plan.json 有 choice 吗 → 无则 models set
  ├─ 本地 8188 在线吗 → assets --engine local --check
  └─ 能力卡节点映射对吗 → preflight（免费）

出片失败
  ├─ rc=3 批次缺口 → --resume <批次>，不要重写提示词
  ├─ rc=4 计费闸门 → 需 confirm=true / 人确认
  └─ rc=2 判据不过 → 看 detail 是缺图还是时长

字幕错位
  ├─ 先看 <subs>/_cover_lead.json 是否存在且指纹匹配
  ├─ 对齐档位是什么（asr-word / ctc / fallback-estimate）
  └─ 用母版音频跑 sync_check()，不要只看 asr/*.wav

manifest --check 红
  ├─ 哈希不符 → 文件改过但没 --apply
  ├─ 行尾漂移 → 文件被写成 CRLF
  └─ 顺序 → git add → --apply → git add manifest.sha256

git push 失败
  ├─ No anonymous write access → GIT_CONFIG_GLOBAL=/dev/null
  ├─ CONNECT tunnel failed → 先 env -u 清代理
  └─ Connection reset → HTTP/1.1 + postBuffer
```

---

## 12. 提交纪律

```bash
git add <files>
python tools/rebuild_manifest.py --apply
python tools/rebuild_manifest.py --check     # 哈希不符 0 + 行尾漂移 0
git add manifest.sha256
git commit -F <消息文件>                      # heredoc，别用 /tmp 中转
```

- `.gitattributes` 声明 `* text=auto eol=lf`；工作树不得有 CRLF。
- 不用 `--fix-eol`（内部 `git checkout --` 会丢未提交改动）。
- 提交消息写「为什么」；一次提交一件事。
- 改完待办：`VERSIONS.md` 记一行，并删掉 `docs/待修清单.md` 对应条目。
- **push 前告知用户**；push 要点：清代理（`env -u HTTPS_PROXY …`）+ `GIT_CONFIG_GLOBAL=/dev/null` + HTTP/1.1 + 大 postBuffer。

---

## 13. Codex 作业准则

**先做**

1. 跑 §0.2 三条命令，确认起点是绿的。
2. 改文件前先在 §3 / §7 找到对应契约；新能力先补契约。
3. 一次只推进一个节点 / 端点 / 视图，改完立刻跑该目录测试。
4. 报结果给可核对的事实：退出码、测试数、文件路径、`verdict`。

**不要做**

1. 不要改 `_ws.py` 让它能在仓库根跑（那是防误跑的设计）。
2. 不要为「让测试变绿」放宽判据或门禁。
3. 不要新增 npm / 打包器 / 业务数据库。
4. 不要在 Web 层 import 引擎。
5. 不要硬编目录名，走 `stage_dir()`。
6. 不要执行 ★计费动作而不先报价。
7. 不要提交 `envs/` `data/` 真实密钥、用户工作区产物。
8. 不要恢复 R11 的已移除能力。
9. 不要把「未验证」写成「已完成」。
10. 不要按 `drama guide` 的过期命令操作（§2.6）。

**必须停下来问人**

- 要花钱（批量出片 / 云端实例 / 放大）
- 要改内容语义（提示词 / 剧本 / 门禁阈值）
- 要动契约（`pack` 字段、`data/` schema、节点 id）

---

## 14. 文档与代码的口径冲突（以代码为准）

这些是真实存在的滞后文案。Codex 遇到时**按右列执行**，不要按左列实现，也不要顺手大改：

| 位置 | 写的 | 实际 |
|---|---|---|
| `drama.py` 顶层 usage 字符串 | 列 15 个命令，不含 `pack` / `bgm` | argparse 有 19 个（含 `pack`、`bgm`） |
| `drama guide` 输出 | `setup` / `workflow` / `pipeline` 三组命令 | 2026-11-01 已删除，敲了报 `invalid choice` |
| `drama.py` 注释 / argparse help | 「七环节 23 节点」「11 环节」 | 5 环节 13 节点 |
| `web/core/pipeline.py` docstring | 「11 个环节」「七环节」 | `STAGE_MAP` 已按 `nodes.STAGES` 五环节 |
| `web/ui/studio/js/views/pipeline.js` | 「11 个环节」 | 同上 |
| `docs/architecture/current-api.md` 标题 | 111 端点 | 实测 118 |
| `pipeline.py` 的 `until/only` 注释 | 举例 `S5` | 环节 id 是 `import/asset/board/video/edit` |
| `docs/Agent项目技术文档.md` | 旧命令与 16 环节 | 历史材料，勿照做（顶部已有警告） |

---

## 15. 术语 / 文档地图 / 交付

### 15.1 术语

| 术语 | 含义 |
|---|---|
| 制作包 pack | `md2pack` 产出的 JSON 集合，引擎唯一输入 |
| 分镜图 board | 每镜一张 9:16 首帧，出片第一张参考图，不是装饰 |
| H3 六段式 | 视频提示词固定六段，顺序即契约 |
| 母版 master | 封面 + 片段 + BGM 拼成的 `<ep>_master.mp4` |
| 发布版 release | `09-发行/剧集/EpisodeNN.mp4` |
| 闸门 gate | 机器判据（退出码 + `verdict`），不是提示 |
| 回流 reflow | 判据不过时允许回退的上游白名单 |
| 模型确认单 | `<ws>/model-plan.json`，通道选择唯一真源 |
| 台账 ledger | `ledger/runs/*`，钱与时间唯一证据 |
| engine_root | 工作区里的 `video-pipeline/`，引擎视角的 workspace |

### 15.2 文档地图

| 想知道 | 读 |
|---|---|
| 怎么装 / 怎么用 | `README.md`、`docs/operations/使用者路线.md` |
| 怎么改引擎 | `docs/operations/开发者路线.md` |
| 当前架构 / API / 数据模型 / 债 | `docs/architecture/*.md` |
| 制作包怎么写 | `docs/pack/PACK-SPEC.md`、`MD-TEMPLATE.md` |
| 提示词怎么写 | `docs/pack/H3-REF2VA-PROMPT.md` |
| 已知坑 | `stages/production/references/pitfalls.md`、`docs/复盘-2026-11-06-bug与冗余.md` |
| 已退役脚本 | `docs/operations/已退役脚本.md` |
| 全自动 Agent 规划 | `docs/AGENT-PLAN.md`（规划稿，勿当现状） |
| 2.0 审计证据 | `docs/upgrade/01..07`、`docs/upgrade/phase-report-20261110.md` |

### 15.3 交给 Codex 的三种方式

| 方式 | 做法 | 适用 |
|---|---|---|
| GitHub 直连 | 给仓库 URL + `main` | 云端 Codex，最省事 |
| 本地目录 | 在仓库根打开 Codex CLI | 需要 ffmpeg / ComfyUI 真机验证 |
| 压缩包 | 打包仓库根 | 内网 |

打包排除：`.git/` `envs/` `__pycache__/` `.pytest_cache/` `web/var/`，以及**任何用户工作区**（在仓库外）。

### 15.4 可直接粘贴的启动提示词

```text
接手 SoloDrama（Python 流水线，把点子做成竖屏短剧）。
仓库根有 AGENTS.md，先完整读它，再读 docs/HANDOFF-CODEX.md。基线 main @ 88324c6。

第一步只做验证，不改代码：
1) python tools/env_check.py --json，报告未通过项；
2) python -m pytest tools/tests stages/import/tests -q，期望 112 passed；
3) 复述 13 个节点 id 的顺序，确认你读懂了调度模型。

然后从待办挑 P0 的 T1 或 T2，先给改动方案与验收标准，等我确认再动手。
硬性要求：不执行任何计费动作；不改门禁判据；提交前重建 manifest.sha256。
```

---

> 本文与代码冲突时**以代码为准**，并回头修本文。
