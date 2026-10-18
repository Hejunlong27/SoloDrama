# VERSIONS.md —— 引擎收编清单与版本固化

- 收编日期：2026-10-08
- 收编方式：**拷贝固化**（副本为唯一运行真源，原 Skill 包不再承担引擎职责）
- 2026-10-08 更新：按新宗旨（让所有人都可以做AI短剧，每个人都可以把自己的故事拍出来！！！）决策移除免费通道（rh-free-h3-video），出片仅保留「AI 应用 + 工作流」标准通道
- **2026-10-10 更新**：新增**本地 ComfyUI 资产出图通道**（收编自 WorkBuddy Skill `comfyui-local-imagegen`），资产出图改为**默认本地（￥0）**、云端计费通道并存；同时修复两处收编遗留缺陷（`drama.py` 的脚本路径与工作区下传）
- **2026-10-12 更新**：①新增**模型选择门禁**（前置条件）：首次生图/出片前必须确认模型（本地 ComfyUI / RunningHub / 闭源模型），确认单落 `<工作区>/model-plan.json`，未确认即拦（退出码 4）；②新增**西语 AI 漫剧创作链路** `stages/creation/`，按交付**四部分**组织：① 榜单调研与对比（多市场 + 西语重点）→ ② 爆款拆解（题材/套路/爆点/偏好/差异化趋势）→ ③ 选题定位（受众画像/题材方向/差异化卖点）→ ④ 剧本改写（源剧本 → N 集规划，默认 60 集，每集冲突/反转/钩子），并打通与 `tools/cli.py` 及 `drama.py` 的对接
- **2026-10-13 更新**：**项目更名为 SoloDrama**（取自「一个人，就是一个剧组」，命名格式 `<前缀>+Drama`），GitHub 仓库同步更名为 `Hejunlong27/SoloDrama`（旧地址自动跳转）；README 首段补齐「创作层 + 执行层」双段式介绍与「一台家用笔记本（RTX 4060 8G + 16G 内存）即可跑通」的硬件门槛说明；**环境变量前缀由 `DRAMA_*` 迁至 `SOLODRAMA_*`**（新名优先、旧名回退，见第五节）
- **2026-10-19 更新（V0.3.1 · 文档修正，无代码变更）**：把用户两条验收意见**写进项目**以防复发 —— ① 新增 `docs/patches/2026-10-19_落点与命名事故复盘.md`（保留用户原话、现象/根因/修法、**规则+工具+门禁三层防复发**、交付前自检 5 问）；② `stages/production/references/pitfalls.md` 追加 **§F 落点与命名**（6 行「现象-根因-修法」，含「注释把 bug 固化成事实」「JSON 双反斜杠导致路径改写恒为 0」「零迁移兼容」三条陷阱）；③ `README.md` §4.1 新增「**给 AI 助手的三条红线**」提示块（资产落 `04-资产` / 发布版 `EpisodeNN.mp4` / 不许临时起名挑目录），并在文档索引与「改动前必看四份」契约表中指向 §F 与复盘文档；④ `生产流程总纲.md` 与 `发行资料清单.md` 互链
- **2026-10-19 更新（V0.3）**：①**发布版剧集命名硬规则** —— 严格 `EpisodeNN.mp4`（`Episode01` … `Episode40`，≥100 集自动加位）落 `09-发行/剧集/`；新增 `stages/production/scripts/release_export.py`（默认干跑、自动探测来源、同集取「最接近可发布」的那份：已编码发布版 > `_subbed` > `_master_2k` > `_master`）+ 13 例离线测试；`release_check.py` 增「发布版命名 / 集号连续性」检查（命名不符 → 退出码 2）。②**资产落点硬规则** —— 人物/场景/道具出图产物一律落 `04-资产/{characters,scenes,props}`，**不再进 `07-成片/assets`**；`stages/_layout.py` 新增 `assets_dir()` / `assets_rel` / `release_episode_name()`，`scaffold()` 自动建资产子目录并回填 `config.local.json` 的 `assets_dir`；4 个资产生成器 + 2 个消费侧（`wire_new_assets`、`episode_preflight`）与控制台 `web/core/inventory.py` 同步改口；**零迁移兼容**：老项目未迁移前自动沿用旧位置并给出迁移提示；新增 `stages/production/scripts/migrate_assets.py`（默认干跑、先备份到 `_assets_backup_<ts>/`、按解析后字符串改写清单绝对路径）+ 16 例离线测试。③文档：生产流程总纲新增 **§3.7 落点与命名硬规则**、环节链 6/7/14 更新；发行资料清单由「四类」扩为**五类**（剧集 + 封面 + 文案 + 发布清单 + 版权资料）并新增 §二「发布版剧集：命名与落点」
- **2026-10-18 更新（V0.2）**：①**新增「发行资料」全链路** —— 单一真源 `docs/distribution/发行资料清单.md`（封面「抓马度 / 视觉冲击」六抓手与反例、**版权资料 = 4 张「AI 生成过程截图」+ 4 张「原始文件/素材文件信息」**、文案六槽位、发布清单）+ 确定性门禁 `stages/production/scripts/release_check.py`（离线、零第三方依赖、退出码 2）+ 11 例离线测试；总纲补**环节 14** 与 **G9 发行资料门禁**，`_layout.py` 的 `release` 用途同步。②**回填产线补丁 P1–P6**：`ingest_check.py` 两处合法输入误判修正、`pipeline.py` 出图画幅 `value_map`、`runninghub_client.py` v2 提交通道 + 直链下载鉴权、`model_gate.py` 新增「RunningHub 工作流出图」通道、`.gitignore`（`web/var/` 等，**禁止 `web/*` 通配**）、`manifest.sha256` 重算。③**新增实跑复盘文档**：`docs/patches/` 三篇（踩坑清单 26 条 / 产线补丁清单 / 产线对账关卡）。④**Web 控制台 `web/` 首次入库**（FastAPI + 原生 JS + SSE，引擎零改动）
- 完整性校验：`manifest.sha256`（每文件 SHA-256，可用 `Get-FileHash` / `sha256sum -c` 核对）
- 依赖锁定：`requirements.txt`（httpx==0.28.1 / Pillow==12.2.0，实测 Python 3.13）

## 一、源 → 副本映射

| 副本路径 | 收编自 | 引擎版本标记 | 说明 |
|---|---|---|---|
| `stages/video/workflow/` | WorkBuddy Skill `ai-video-pipeline` | v1.0.0（2026-09-17） | 出片引擎：doctor / probe / configure / check_billing / run / report + `engine/` 四件套 + probe_nodes；含 references 技术契约（data-schema / runninghub-contract / config-layers / operations / troubleshooting）与 assets 模板 |

| `stages/subtitle/` | WorkBuddy Skill `drama-subtitle-pipeline` | 2026-09-20 四缺陷修复版 + 2026-10-06 安全区/竖屏标定 | `subtitle.py` + `upscale.py`（单真源）+ compare/cost 工具 + config 模板 + references |
| `stages/production/` | WorkBuddy Skill `short-drama-production` | 2026-10-08 在用版 | 总控 `drama.py`、体检 `episode_preflight.py`、资产 `gen_char_assets.py` / `gen_scene_assets.py`、接线 `wire_*.py` / `prepare_refs.py`、成本 `cost_*.py`、验收 `_qa_subtitle_frame.py` + references |
| `stages/assets/` | WorkBuddy Skill `asset-card-image-prompter` | 2026-10-05 实战版（28 例离线测试全绿） | 净化器 `sanitize.py` + 三类模板 `prompt_templates.py` + 离线测试 + references（AI 应用提交契约 / 踩坑全录） |
| `stages/assets/comfyui/` | WorkBuddy Skill `comfyui-local-imagegen` | **2026-10-10 收编** | **本地出图引擎**：`comfy_client.py`（纯标准库、零第三方依赖、不出网）+ `workflow_qwen_image21.json` 示例工作流 + references（出图流程 / 节点表与换工作流适配） |
| `stages/assets/scripts/asset_md.py` | 新增（补断点：创作产物 → 引擎输入） | **v1.0.0（2026-10-10）** | 资产提示词 md → 本地 ComfyUI 清单（纯标准库）；配套 19 例离线测试 |
| `stages/production/scripts/gen_assets_local.py` | 新增（薄桥） | **v1.0.0（2026-10-10）** | 生产总控侧本地出图桥：md → 清单 → 调本地引擎 → 产物清单 + 零成本台账 |
| `stages/production/scripts/model_gate.py` | 新增（前置条件门禁） | **v1.0.0（2026-10-12）** | 首次生图/出片前的模型选择确认（本地 ComfyUI / RunningHub / 闭源模型）；配套 19 例离线测试 |
| `stages/production/scripts/release_check.py` | 新增（发行资料门禁） | **v1.0.0（2026-10-18）** | 发行资料齐全度：封面多尺寸成组（比例校验）+ 文案 + 发布清单 + 版权资料 4+4（不缺号、长边 ≥1200）；纯标准库（自行解析 PNG/JPEG 文件头，不依赖 Pillow）；配套 11 例离线测试。真源 `docs/distribution/发行资料清单.md` |
| `docs/distribution/发行资料清单.md` | 新增（发行资料单一真源） | **v1.0.0（2026-10-18）** | 封面「抓马度」六抓手与反例、色板表、硬约束（不得裁切/首帧亮度/色彩范围/四视图切分）、版权资料 4 张 AI 生成过程截图 + 4 张原始文件/素材文件信息、文案六槽位、发布清单、验收口径 |
| `stages/production/scripts/release_export.py` | 新增（发布版导出） | **v1.0.0（2026-10-19）** | 发布版成片严格 `EpisodeNN.mp4` 落 `09-发行/剧集/`；默认干跑、自动探测来源、同集取最接近可发布者、目标目录杂名一票拦下；配套 13 例离线测试 |
| `stages/production/scripts/migrate_assets.py` | 新增（资产落点迁移） | **v1.0.0（2026-10-19）** | 旧 `<out>/assets/**` → `04-资产/**`；默认干跑、先备份、按解析后字符串改写 `*_assets_manifest.json` 的绝对路径，并补齐 `layout.json` / `config.local.json` 声明；配套 16 例离线测试 |
| `stages/creation/` | 新增（西语漫剧创作链路·四部分） | **v1.0.0（2026-10-12）** | ① 榜单调研与对比（`market_data.py`）→ ② 爆款拆解（`hit_breakdown.py`）→ ③ 选题定位（`topic_analysis.py` + `hit_selection.py`）→ ④ 剧本改写（`script_rewrite.py`）；纯标准库；配套 49 例离线测试 |
| `tools/` | 项目工具链 `D:\AI-Drama\parallel-me\tools` | 2026-09 版 | 创作层确定性工具：init / import-bible / parse / check / convert / reindex / report / set-anchor / gen(stub) |
| `docs/creation/` | WorkBuddy Skill `ai-drama-creator` references | 2026-09 版 | 创作层方法论：FFS 规范 / 转换规则 / QA 门 / STYLE LOCK 预设 / 流水线落盘规范 |

**未收编**（保持 WorkBuddy 技能形态）：创作层技能本体（`ai-drama-creator` / `3d-short-drama-studio` / `seedance-storyboard` / `overseas-ai-comic-script-master` / `parallel-world-writer` / `short-drama-hit-topics` 等）——它们是会话内 LLM 工作流，不属于本地引擎。

## 二、副本相对源的改动（去硬编码手术清单）

核心逻辑**零改动**；以下改动仅限「配置默认值 / 提示文案」，全部为去除个人机器路径与账号绑定 ID：

| 文件 | 改动 | 原因 |
|---|---|---|
| `stages/production/scripts/drama.py` | `AI_VIDEO_PIPELINE_SKILL` 缺省回退改为仓库相对路径 `<repo>/stages/video/workflow` | 原硬编码本机 Skill 安装路径 |
| `stages/production/scripts/gen_char_assets.py` | 同上；`DRAMA_ASSET_MD` 改为必填环境变量（缺省 fail-fast）；`RH_CHAR_APP_ID` 改为环境变量注入；`RH_CHAR_HAVE_SECTIONS` 可覆盖已生成集合；docstring/argparse 描述去 ID 化 | 原硬编码本机路径、项目专属 md 路径、账号 AI 应用 ID |
| `stages/production/scripts/gen_scene_assets.py` | ENGINE 回退仓库相对；`DRAMA_ASSET_MD` 必填；`RH_SCENE_HAVE_SECTIONS` 可覆盖；docstring 去个人路径 | 同上 |
| `stages/production/scripts/episode_preflight.py` | `DRAMA_ASSET_MD` 缺省为空（本就容缺失跳过） | 去个人路径默认值 |
| `stages/production/scripts/cost_ledger.py` | 读余额时引擎路径回退改仓库相对/环境变量 | 原硬编码本机 Skill 路径 |
| `stages/production/scripts/probe_char_app.py` | ENGINE 回退仓库相对；快照目录 `DRAMA_WORKSPACE` 优先；`RH_CHAR_APP_ID` 环境变量注入；docstring 去 ID 化 | 原硬编码本机路径与账号 ID |
| `stages/production/scripts/_check_seg.py` | 工作区改 `DRAMA_WORKSPACE` 优先 | 原硬编码工作区路径 |
| `stages/production/scripts/_ws.py`、`cost_ledger.py` | docstring 示例路径泛化 | 去个人路径（历史问题描述保留语义） |
| `stages/production/scripts/prepare_refs.py` | 缺 Pillow 提示改为通用安装指引 | 去本机解释器路径 |
| `stages/video/workflow/scripts/run.py`、`doctor.py` | 用法/体检提示文案泛化 | 去本机路径 |
| `stages/video/workflow/scripts/engine/tools/probe_nodes.py` | 用法示例工作流 ID → 占位符 | 去账号工作流 ID |
| `stages/video/workflow/references/config-layers.md`、`troubleshooting.md` | 示例 ID / 示例路径泛化 | 同上 |

| `stages/subtitle/assets/config.subtitle.example.json` | `whisper_cli` / `whisper_model` / `aligner` 改占位符 | 原为本机绝对路径（使用时复制为 config.subtitle.json 填入自己的路径） |
| `stages/subtitle/scripts/upscale_compare_frames.py` | ffmpeg 候选改 `FFMPEG_PATH` / `TOPAZ_FFMPEG_PATH` 环境变量；字体可用 `SUBTITLE_FONT_PATH` 覆盖（缺省仍为 Windows 系统雅黑） | 去本机个人路径 |
| `stages/subtitle/references/*.md`、`stages/production/references/*.md`、`stages/assets/references/runninghub-ai-app-提交契约.md` | 个人路径 / 账号 ID / webapp ID → 占位符 | 开源卫生 |
| `tools/cli.py`、`docs/creation/pipeline.md` | 用法示例路径泛化 | 去本机项目路径 |

### 2026-10-10 新增/修复（本地 ComfyUI 通道）

| 文件 | 改动 | 原因 |
|---|---|---|
| `stages/assets/comfyui/comfy_client.py` | 五类节点 id 改为 `COMFYUI_NODE_{PROMPT,PREFIX,SEED,ASPECT,LATENT}` 可覆盖；工作流路径改为 `COMFYUI_WORKFLOW` 可覆盖；新增**空代理 opener**；`--check` 失败改为友好 JSON + 退出码 1；清单级 `style_lock` 会在批量路径生效 | 从「改代码换工作流」变为「改配置换工作流」；**实测**：环境存在 `HTTP_PROXY` 时 urllib 会把 `127.0.0.1:8188` 也塞进代理，返回 `HTTP Error 502`；失败不再是原始 traceback |
| `stages/assets/comfyui/workflow_qwen_image21.json` | 节点 6 的示例提示词中性化（原为第三方动漫角色示例）；`filename_prefix` 由 `LQ-` 改为 `drama` | 开源卫生（不携带他人作品示例） |
| `stages/assets/scripts/asset_md.py` | 新增（纯标准库）。解析口径与 `gen_char_assets.py` / `gen_scene_assets.py` **同为**「`# 一、角色资产库` / `# 二、场景资产` / `# 三、道具资产`；`## N. 名字` 节内 ``` 块 = 提示词」。**刻意不 import 既有引擎**，以免把 httpx / RunningHub 客户端拖进零成本的本地通道 | 补「创作产物 → 引擎输入」断点；本地通道不得被云端依赖拖累 |
| `stages/assets/scripts/tests/test_asset_md.py` | 新增 19 例离线测试（零网络零计费） | 转换器是确定性的，应可回归 |
| `stages/production/scripts/gen_assets_local.py` | 新增（薄桥） | 生产总控侧统一入口，与云端两脚本并列 |
| `stages/production/scripts/drama.py` | ① `SCRIPTS` 由 `<工作区>/scripts` 改为**本文件所在目录**（`DRAMA_SCRIPTS_DIR` 可覆盖）；② `hydrate_env()` 下传 `DRAMA_WORKSPACE`、并把 `DRAMA_ASSET_MD` 纳入用户级环境变量补全；③ `assets` 子命令新增 `--engine {local,rh}` 与 `--check`，`--kind` 增加 `prop`；④ 状态面板聚合本地通道产物（资产不分通道，一并计入「已生成」） | **修复收编遗留缺陷**：脚本已住在仓库内（`stages/production/scripts/`），原 `<工作区>/scripts` 写法会让 `rh_doctor` / `cost_ledger` / `gen_char_assets` / `gen_scene_assets` **全部找不到**；子脚本也无法从自身位置推断工作区（脚本不在工作区里） |
| `configs/settings.example.json` | 新增 `comfyui` 段（base_url / workflow / 节点映射 / aspect 默认） | 配置单点，不硬编码 |
| `README.md`、`docs/Agent项目技术文档.md` | 新增本地通道的定位、命令、配置与模块表 | 文档同步 |

**行为不变性说明**：所有改动不触碰提交/轮询/下载/对齐/渲染/计费守卫等任何业务逻辑；在原环境设置相同环境变量时行为与源版本一致；未设环境变量时按仓库内缺省或显式报错（不再静默指向个人机器路径）。

### 2026-10-12 新增（模型门禁 + 西语漫剧创作链路）

| 文件 | 改动 | 原因 |
|---|---|---|
| `stages/production/scripts/model_gate.py` | **新增**（纯标准库）。生图/视频模型的「首次执行前确认」门禁：可选清单、菜单/确认请求渲染、`status/list/set/reset/ask/require` 子命令、`gate_state`/`require` 判定（含通道一致性校验）、退出码 4 | **新增前置条件**：首次生图/出片前必须确认模型，未确认不得执行 |
| `stages/production/scripts/drama.py` | ①新增 `models` 子命令（转发 model_gate）；②`cmd_assets`（local 与 rh 两路）在 `--submit` 前、`cmd_video_run` 在 `--yes` 后，先查模型门禁，未过即停（`_model_gate`）；③docstring/GUIDE 同步 | 把门禁接入计费动作入口，确保「未确认不执行」 |
| `stages/production/scripts/tests/test_model_gate.py` | **新增** 19 例离线测试（零网络零计费） | 门禁是安全边界，必须可回归 |
| `configs/model-plan.example.json` | **新增** 模型确认单模板（含规则、可选值、闭源模型说明） | 配置单点、可留档 |
| `stages/creation/` （整目录） | **新增**（纯标准库）西语漫剧创作链路，按交付**四部分**组织：`scripts/{creation,market_data,hit_breakdown,topic_analysis,hit_selection,script_rewrite,_common}.py` + `prompts/{s0-market-research,s1-hit-breakdown,s2-topic-positioning,s3-script-rewrite}.md` + `references/{spanish-market,scoring-model,module-contracts}.md` + `assets/{market-data,creation-brief}.template.json` + `scripts/tests/test_creation_pipeline.py`（49 例）+ `README.md` | **围绕西语 AI 漫剧生产流程完善功能**：① 榜单调研与对比（多市场横向对比 + 西语重点 + 覆盖度门禁）、② 爆款拆解（题材类型/剧情套路/爆点元素/内容偏好/差异化趋势）、③ 选题定位（受众画像/题材方向/差异化卖点）、④ 剧本改写（源剧本 → N 集规划，默认 60 集，每集核心冲突/反转/钩子 + 爆点节拍），并**对接现有 agent 体系**（`tools/cli.py` 创作工具链 + `drama.py` 执行引擎） |
| `README.md`、`VERSIONS.md`、`docs/Agent项目技术文档.md` | 新增模型门禁与创作链路的定位、命令、模块表与数据契约 | 文档同步 |

> 创作层技能本体（`ai-drama-creator` / `overseas-ai-comic-script-master` / `short-drama-hit-topics` 等）
> **仍保持 WorkBuddy 技能形态**（会话内 LLM 工作流）；本次新增的是其**确定性部分**（评分/交叉/去重/排期/
> 结构抽取/FFS 骨架/格式自检/数据覆盖度门禁），不重复实现 LLM 创意环节。

## 三、运行时排除项（未收编）

| 项 | 原因 |
|---|---|
| `**/__pycache__`、`*.pyc` | 运行时产物 |
| `engine/.workspace`（工作区指针文件） | 内含本机工作区路径；副本缺省回退 `~/video-pipeline-workspace`，可用 `--workspace` / `VIDEO_PIPELINE_WORKSPACE` 覆盖 |
| 各 Skill 的 `SKILL.md` | WorkBuddy 会话层文档，含平台上下文；技术契约已由 `references/` 覆盖 |
| WorkBuddy Skill `rh-free-h3-video`（免费通道引擎） | **决策移除（2026-10-08）**：免费端点为限时能力、不具备可复用性；出片统一走「AI 应用 + 工作流」标准通道 |
| 创作层技能与真实剧项目数据 | 属内容资产，不入引擎仓库 |

## 四、验证方式

```powershell
# 1) 完整性
Get-FileHash -Algorithm SHA256 (Get-ChildItem -Recurse -File | Where-Object {$_.Name -ne 'manifest.sha256'}) | ...

# 或在 Git Bash / WSL：
sha256sum -c manifest.sha256

# 2) 依赖
pip install -r requirements.txt

# 3) 离线冒烟（零计费、零网络）
python stages/video/workflow/scripts/run.py doctor --json
python stages/assets/scripts/sanitize.py --selftest
python stages/assets/scripts/tests/test_prompter.py
python stages/assets/scripts/tests/test_asset_md.py

# 4) 本地出图通道（零第三方依赖，不需要任何 Key；需本机 ComfyUI 在跑）
python stages/assets/comfyui/comfy_client.py --check
python stages/production/scripts/drama.py assets --engine local          # 干跑

# 5) 模型门禁 + 创作链路（零网络零计费）
python stages/production/scripts/tests/test_model_gate.py
python stages/production/scripts/tests/test_style_gate.py
python stages/production/scripts/tests/test_release_check.py
python stages/production/scripts/tests/test_release_export.py
python stages/production/scripts/tests/test_migrate_assets.py
python stages/creation/scripts/tests/test_creation_pipeline.py
python stages/creation/scripts/creation.py guide
```

## 五、环境变量前缀迁移（2026-10-13）

项目更名 SoloDrama 后，自有环境变量前缀由 `DRAMA_*` 迁至 `SOLODRAMA_*`。**为不破坏已有配置，采取「新名优先、旧名回退」策略**——
两套名字并存，读到哪个用哪个：

| 用途 | 新名（推荐） | 旧名（仍兼容） |
|---|---|---|
| 默认工作区 | `SOLODRAMA_WORKSPACE` | `DRAMA_WORKSPACE` |
| 资产提示词 md | `SOLODRAMA_ASSET_MD` | `DRAMA_ASSET_MD` |
| 生产脚本目录覆盖 | `SOLODRAMA_SCRIPTS_DIR` | `DRAMA_SCRIPTS_DIR` |

实现要点：

- 统一读取口径：`os.environ.get("SOLODRAMA_X") or os.environ.get("DRAMA_X")`，共 10 处读取点；
- `stages/production/scripts/_ws.py` 新增 `env_workspace()` 与 `ENV_NAMES`，作为工作区解析的唯一入口；
- `drama.py hydrate_env()` 会**同时下发**新旧两个工作区变量，因此外部工具或用户自写脚本读旧名也不会失灵；
- 用户级环境变量补全（winreg）同时认这两个名字。

> 未迁移的变量（刻意保留原名）：`RUNNINGHUB_*` / `RH_*` / `COMFYUI_*` / `VIDEO_PIPELINE_WORKSPACE` / `TVAI_*`
> —— 前四类属平台或引擎既有契约，改名会破坏兼容；`VIDEO_PIPELINE_WORKSPACE` 由引擎自带，不属于本项目自有前缀。

