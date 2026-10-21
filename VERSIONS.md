# VERSIONS.md —— 引擎收编清单与版本固化

- 收编日期：2026-10-08
- **2026-10-21 回填（V0.7）**：内容提交 `269352e`（远端 `57d628e` → `269352e`，快进）；本条仅改 `README.md` / `VERSIONS.md` / `manifest.sha256`。
- **2026-10-21 更新（V0.7 · BGM 全链路）**：解决「已交付的剧没有配乐」。**先定分工**：画面与同期声归 H3、BGM 归后期 —— 逐段生成的音乐给不了「贯穿整集可循环 / 可换可证版权 / 不盖对白」三件事。① 新增 `stages/production/scripts/bgm.py`（库 / 计划 / 门禁 / 混音）：项目库 `<ws>/04-资产/bgm/` 与引擎共享库 `stages/production/assets/bgm/`（项目库优先，音频文件不进 git，只提交清单）；`library --scan` 用 ffprobe 补时长；`plan` 按情绪表生成 `<ep>_bgm-plan.json`（增益优先级：命令行 > 曲目建议值 > 情绪默认）；`mix` 用 `filter_complex` 混音，`-c:v copy` 视频直通、`sidechaincompress` 做对白 ducking、`-stream_loop -1` 支持短曲循环。② 门禁 5 条（退出码 2）：license 枚举、`generated` 必须写 license_note、gain ≤ -6 dB、覆盖 ≥ 90%、`voice=h3` 不得关 ducking。③ `convert_storyboard.py` 默认追加 `[AUDIO]` 段禁止模型自造配乐（`--no-audio-direction` 可关）—— 否则模型那层 + 后期那层双重铺底、相位抵消、音量台阶。④ S10 扩为「音频与字幕」：`subtitle.py --stage render` 检测到计划即混 `<ep>_mix.mp4` 并以其为底片；三条降级路径保证「没有 BGM 也能交片」。⑤ 新增 `docs/production/BGM与音频设计.md`；`drama.py` 增 `bgm` 转发。验证：`test_bgm.py` **28/28**（含 1 例真混音），全量 **554 例**全绿。
- **2026-10-21 回填（V0.6.1）**：内容提交 `f577951`（远端 `ba52e5b` → `f577951`，快进）；本条仅改 `README.md` / `VERSIONS.md` / `manifest.sha256`。
- **2026-10-21 更新（V0.6.1 · 前置条件补「工作流 API」与「账号 API Key」，7 项 → 9 项）**：用户当日追加要求「必须向用户确定使用哪个工作流 API、哪个账户的 API Key」。这不是加两行菜单，而是补上两个**选错不会报错**的开关：① 第 6 项 **工作流 API** —— `workflowId`（或 AI 应用地址 / 云端 ComfyUI 地址+工作流文件）+ **站点**三元组，站点只接受 `.ai` / `.cn`（写错退出码 2）；可从 `model-plan.json` 执行依据自动推断（不必抄两遍）。同名工作流在平台可有多份，换错 = 换个模型，8 段跑完才发现风格漂移。② 第 7 项 **账号 API Key** —— 只登记 `别名 + 指纹(sha256前8…后4) + 来源(环境变量名)`，**Key 本体永不落盘**；`require()` 每次比对当前环境 Key 指纹，不一致退出码 4 并明示「会花错账号的钱」；`pipeline run` 在每个计费环节**之前**再比对一次（跑几小时中途换 Key 也拦得住）。③ 新增 `drama.py setup accounts`（列可用账号，含 `<ws>/keys.json` 多账号清单，只显示指纹与站点）与 `--account-source`（多账号切换）。④ 两项按通道**条件化**：全本地/闭源自动「无需」，有 RunningHub 通道才硬性必填。⑤ `pipeline plan` 开工预告增「工作流 API / 账号」两行。⑥ 顺带修 `render` 编号重复（生图/视频都标 4）与 `--workflow-id` 需抄两遍。验证：`test_setup_workflow_pipeline.py` **52/52**（新增 10 例含账号漂移拦截与「Key 本体不落盘」断言），全量 **526 例**全绿。
- **2026-10-21 基线（V0.6 回填）**：内容提交 `649a77f`（远端 `f9d1e31` → `649a77f`，快进，未重写历史）；本条为回填提交，仅改 `README.md` / `VERSIONS.md` / `manifest.sha256`。
- **2026-10-21 更新（V0.6 · 标准作业流程 + 前置条件 + 流水线模式）**：把「顺序」做成可执行的一层。① 新增 `stages/production/scripts/workflow.py` —— 11 环节机器真源（S1 调研 → S2 剧本 → S3 资产设计 → S4 资产生成 → S5 视频提示词 → S6 视频生成 → S7 发行资料〔可选〕→ S8 拼接 → S9 放大 → S10 字幕 → S11 定稿），每环节给出 `kind`（内容/自动）、产物判据（含动态 `min`=集数/镜数）、标准命令；`status` 报当前应做环节，`check --stage` 前置未完成即退出码 4，`skip` 必须 `--reason` 并写 `workflow-state.json` 留痕；真源文档 `docs/orchestration/标准作业流程.md`（含与总纲 16 环节的映射表）。② 新增 `stages/production/scripts/project_setup.py` —— 开工前置 **7 项**（画风 / 集数 / 每集时长 / 生图模型 / 视频模型+功能选项 / 画面分辨率 / 是否流水线）收成一张 `<ws>/project-setup.json`，`require()` 单一门禁（未齐退出码 4）；**不另立真源**：画风转发 `style_gate._do_set`、通道转发 `model_gate._do_set`，本单只做汇总与门禁并留改动历史；视频功能选项默认值 4 步 / 0.8MP / voice=h3 / 并发 2（全部来自实测）。③ 新增 `stages/production/scripts/pipeline.py` —— 流水线模式：`plan` 打印**预计完工时间（机时 + 内容制作拆分）、预计花费、预算余量**（不花钱不改产物）；`run --yes` 按 11 环节无人值守推进，`auto` 环节调既有脚本、`agent` 环节打印作业单并停（退出码 4），每个计费环节**之前**核对 `ledger/runs` 的 `usage.consumeCoins`（只累加 SUCCESS），超上限退出码 3。④ `drama.py` 新增 `setup / workflow / pipeline` 三个薄转发子命令（REMAINDER 透传，后续加参数不必改 drama.py）。⑤ 同批修复实跑优化建议单 19 条 + 剪影分镜规范 11 条固化为文档，逐条对照见 `docs/patches/2026-10-21_实跑优化建议修复记录.md`。
- 收编方式：**拷贝固化**（副本为唯一运行真源，原 Skill 包不再承担引擎职责）
- 2026-10-08 更新：按新宗旨（让所有人都可以做AI短剧，每个人都可以把自己的故事拍出来！！！）决策移除免费通道（rh-free-h3-video），出片仅保留「AI 应用 + 工作流」标准通道
- **2026-10-10 更新**：新增**本地 ComfyUI 资产出图通道**（收编自 WorkBuddy Skill `comfyui-local-imagegen`），资产出图改为**默认本地（￥0）**、云端计费通道并存；同时修复两处收编遗留缺陷（`drama.py` 的脚本路径与工作区下传）
- **2026-10-12 更新**：①新增**模型选择门禁**（前置条件）：首次生图/出片前必须确认模型（本地 ComfyUI / RunningHub / 闭源模型），确认单落 `<工作区>/model-plan.json`，未确认即拦（退出码 4）；②新增**西语 AI 漫剧创作链路** `stages/creation/`，按交付**四部分**组织：① 榜单调研与对比（多市场 + 西语重点）→ ② 爆款拆解（题材/套路/爆点/偏好/差异化趋势）→ ③ 选题定位（受众画像/题材方向/差异化卖点）→ ④ 剧本改写（源剧本 → N 集规划，默认 60 集，每集冲突/反转/钩子），并打通与 `tools/cli.py` 及 `drama.py` 的对接
- **2026-10-13 更新**：**项目更名为 SoloDrama**（取自「一个人，就是一个剧组」，命名格式 `<前缀>+Drama`），GitHub 仓库同步更名为 `Hejunlong27/SoloDrama`（旧地址自动跳转）；README 首段补齐「创作层 + 执行层」双段式介绍与「一台家用笔记本（RTX 4060 8G + 16G 内存）即可跑通」的硬件门槛说明；**环境变量前缀由 `DRAMA_*` 迁至 `SOLODRAMA_*`**（新名优先、旧名回退，见第五节）
- **2026-10-20 更新（V0.4 · 新增角色差异化能力）**：解决「同一部剧的人物图撞脸」。① 新规范 `docs/assets/角色差异化设计规范.md`（五根因 + 六维签名 + 六条硬规则 R1–R6 + 提示词三件套 + 语言纪律 + 老项目体检 + 验收五问）；② 新脚本 `stages/assets/scripts/character_design.py`（纯标准库、确定性、零网络零计费）：`plan` 按人群桶定候选集 + 最大最小距离贪心分配骨相/发型/眉眼/色签名/材质/识别锚，产出 `character-bible.json`、`角色差异化矩阵.md`、`资产提示词_角色段.md`（可直接被 `gen_char_assets.py`、`asset_md.py` 解析）与三种逐角色提示词（设定板/主卡/定妆照）；`check` 六条硬规则门禁（退出码 2）；`audit` 对既有资产提示词做同质化体检（冲突对 + **维度覆盖率** + 缺锚名单）；③ `prompt_templates.build_char(it, design=None)` 新增可选差异化块并支持可配置 `world`，**design=None 时输出与旧版逐字一致**（28 例既有测试未改一行即通过）；④ 词库按性别/年龄/人群桶/族裔收敛（下装鞋履、面料、体态、骨相措辞），消除身份与材质打架、族裔与骨相自相矛盾两类生成事故；⑤ 总纲新增 **§3.8 角色差异化** 并更新环节 6 与文档索引；⑥ 新增 28 例离线测试（`test_character_design.py`），三套资产层测试共 75 例全绿（提交 `55381a4`）
- **2026-10-19 更新（V0.3.2 · 文档修正，无代码变更）**：新增 `docs/新项目启动提示词.md` —— 回答「怎么跟 AI 助手说才能用上当前版本的规则」：最短版一句话 / 完整版开工提示词（**先读 §3.7、事故复盘、pitfalls §F 再动手**）/ 让助手用上新版本的三条机制（规则在仓库 · 工具代替手工 · 技能层已加指针）/ 老项目「资产归位 + 发布版改名」两条命令 / 「本地是否最新」的判据（README 版本记录提交号 == `git log -1`）/ 常见追问模板。README §4.1 置顶指向该文件，文档索引同步。另给两个不引用仓库的驱动型技能正文补指针：`short-drama-production`、`drama-cover-forge`（**只改正文，description 未动**，不影响路由）
- **2026-10-19 更新（V0.3.1 · 文档修正，无代码变更）**：把用户两条验收意见**写进项目**以防复发 —— ① 新增 `docs/patches/2026-10-19_落点与命名事故复盘.md`（保留用户原话、现象/根因/修法、**规则+工具+门禁三层防复发**、交付前自检 5 问）；② `stages/production/references/pitfalls.md` 追加 **§F 落点与命名**（6 行「现象-根因-修法」，含「注释把 bug 固化成事实」「JSON 双反斜杠导致路径改写恒为 0」「零迁移兼容」三条陷阱）；③ `README.md` §4.1 新增「**给 AI 助手的三条红线**」提示块（资产落 `04-资产` / 发布版 `EpisodeNN.mp4` / 不许临时起名挑目录），并在文档索引与「改动前必看四份」契约表中指向 §F 与复盘文档；④ `生产流程总纲.md` 与 `发行资料清单.md` 互链
- **2026-10-19 更新（V0.3）**：①**发布版剧集命名硬规则** —— 严格 `EpisodeNN.mp4`（`Episode01` … `Episode40`，≥100 集自动加位）落 `09-发行/剧集/`；新增 `stages/production/scripts/release_export.py`（默认干跑、自动探测来源、同集取「最接近可发布」的那份：已编码发布版 > `_subbed` > `_master_2k` > `_master`）+ 13 例离线测试；`release_check.py` 增「发布版命名 / 集号连续性」检查（命名不符 → 退出码 2）。②**资产落点硬规则** —— 人物/场景/道具出图产物一律落 `04-资产/{characters,scenes,props}`，**不再进 `07-成片/assets`**；`stages/_layout.py` 新增 `assets_dir()` / `assets_rel` / `release_episode_name()`，`scaffold()` 自动建资产子目录并回填 `config.local.json` 的 `assets_dir`；4 个资产生成器 + 2 个消费侧（`wire_new_assets`、`episode_preflight`）与控制台 `web/core/inventory.py` 同步改口；**零迁移兼容**：老项目未迁移前自动沿用旧位置并给出迁移提示；新增 `stages/production/scripts/migrate_assets.py`（默认干跑、先备份到 `_assets_backup_<ts>/`、按解析后字符串改写清单绝对路径）+ 16 例离线测试。③文档：生产流程总纲新增 **§3.7 落点与命名硬规则**、环节链 6/7/14 更新；发行资料清单由「四类」扩为**五类**（剧集 + 封面 + 文案 + 发布清单 + 版权资料）并新增 §二「发布版剧集：命名与落点」
- **2026-10-18 更新（V0.2）**：①**新增「发行资料」全链路** —— 单一真源 `docs/distribution/发行资料清单.md`（封面「抓马度 / 视觉冲击」六抓手与反例、**版权资料 = 4 张「AI 生成过程截图」+ 4 张「原始文件/素材文件信息」**、文案六槽位、发布清单）+ 确定性门禁 `stages/production/scripts/release_check.py`（离线、零第三方依赖、退出码 2）+ 11 例离线测试；总纲补**环节 14** 与 **G9 发行资料门禁**，`_layout.py` 的 `release` 用途同步。②**回填产线补丁 P1–P6**：`ingest_check.py` 两处合法输入误判修正、`pipeline.py` 出图画幅 `value_map`、`runninghub_client.py` v2 提交通道 + 直链下载鉴权、`model_gate.py` 新增「RunningHub 工作流出图」通道、`.gitignore`（`web/var/` 等，**禁止 `web/*` 通配**）、`manifest.sha256` 重算。③**新增实跑复盘文档**：`docs/patches/` 三篇（踩坑清单 26 条 / 产线补丁清单 / 产线对账关卡）。④**Web 控制台 `web/` 首次入库**（FastAPI + 原生 JS + SSE，引擎零改动）
- **2026-10-20 更新（V0.5 · 本次发布合集，6 部分）**：远端此前停留在 **V0.4**（`cde1d4e`），本次一次性发布 6 批已完成的改动，**统一记为 V0.5**；原 V0.5 / V0.5.1 / V0.6 / V0.7 / V0.8 / V0.8.1 降为本版组成部分（V0.5-1 … V0.5-6），不再单独占版本号。逐条明细如下（按时间顺序）。
  基线提交：`a47a312`（远端 `cde1d4e` → `a47a312`，快进，未重写历史）。
  - **V0.5-1 · 实跑反馈单修复**：按 `D:/剧本/海外剧/1` 的 10-19/10-20 反馈单逐条定位并修复（24 修 / 3 部分 / 2 未修 / 5 属技能侧或文档建议）。① **钱与静默出错相关的 P0**：`rh_doctor.py` 新增只读探针 `--probe-readonly`（只用查询接口，**明令禁止用 `/run` 做连通性探测** —— 实测该接口会真的建任务）；`cost_ledger` 删掉硬编码剧名 `七大姑催婚`，改由 `_ws.drama_name()` 从 `brief.json`/`project.json`/目录名推导；新增 `engine/inflight.py`（提交即落 `inflight.json`，`--resume` 逐条 `query` 接回，避免「已提交被杀 → 静默漏镜」）+ 收尾镜数硬校验（缺口 → 退出码 3）；`_layout` 的阶段 README 写死**引擎仓库绝对路径**并声明参考系（老工作区幂等修复）。② **阻断流程的 P1**：`drama.py` 支持全局 `--workspace`（在导入 `_ws` 之前生效）；`preflight` 首步做依赖自检；`status` 场景计数误用人物集合已改；模型门禁为每个选项标注 `executor`，**没有执行器的通道（`video=local_comfyui`）禁止确认**；引擎首次真正把 `instanceType` 传给平台，并新增 OOM 三级降级重试（原实例 → plus → plus+降 2s，OOM 不计费）；下载改为 3 次退避重试 + `.part` 原子落盘，失败写 `pending_download.json` 并新增 `video resume-download`；`421 queue limit` 归为瞬时错误（退避 30/60/120s）；放大链路补 libass 探测与两遍法提示。③ **口径与体验的 P2**：新模块 `cost_model.py`（固定+变动 / tier 分币种 / GPU 运行秒 / `--calibrate` 台账自校准）取代按帧构造公式；新增 `rh_workflow_id.py` 反查 workflowId；`plan --from-outline` 直接吃人工拆解表；`TIME` 字段注入固定光位短语；镜头块内非法字段行给 E012 WARN；字幕单一模板硬校验（禁止两套纵向坐标）；母版拼接逐段音频淡入淡出（默认 120ms）；`_lock.py` 单例锁（防止重复启动导致同一镜重复计费）；工作流静态自检（悬空连线/空输入）。④ **回归**：离线 311 例全绿（原 267 + 迁移 16 + 发行 15 + 导出 13），新增 50 例专项 `test_feedback_20261020.py`；`test_migrate_assets` 由 3/16 修到 16/16。详见 `docs/patches/2026-10-20_实跑反馈单修复记录.md`（含未修项的所需信息）（内容提交 `8c937c6`）。
  - **V0.5-2 · 封面引擎收编 + P1-9/10/11**：`cover_forge.py` 原先只存在于 WorkBuddy 用户级技能 `drama-cover-forge/scripts/`，不进 git、不进 manifest、不随仓库分发 —— 反馈单 P1-9/10/11 的三个缺陷都在那份副本里，于是在技能里修「只有一台机器好」。本次把它与 `references/{size-specs,style-presets,copywriting}.md` **收编进仓库**（`stages/production/scripts/cover_forge.py` + `stages/production/references/cover/`），技能侧 `scripts/cover_forge.py` 改为 `runpy` **转发壳**（参数/退出码透传），原实现与 references 备份到 `_backup_20261020/`、`_archive_20261020/`。同时修三处：① 色条位置不再用 `字号 × 1.12em` 经验值，改用 `draw.textbbox()` 真实字形底边 +0.16em（实测旧值 1302 比逗号底边 1303 还高 1px，新值 1319）；② 副标走 `fit_font()` 自动收缩（900×1600 档 53→49px，不再裁字），`--check` 预先报出溢出量与收缩结果；③ `--check` 对「源图比目标更窄 + 目标为宽幅」主动告警，`size-specs.md` 新增 **§3.3 竖/横底图分别生成**。另新增 `--workspace`（spec 未写 out_dir 时默认落 `<发行目录>/封面/`，读 layout.json 的 stages.release）与 `--out-dir`。验证：新增 `test_cover_forge.py` **16/16**（含「色条必须低于旧经验值位置」「成品右边缘无亮像素」「窄图转宽幅告警」）。详见 `docs/patches/2026-10-20_实跑反馈单修复记录.md` §七（内容提交 `7343e07`）。
  - **V0.5-3 · 封面改为 AI 直出带字**：用户明确否决「底图 + PIL 叠字」方案，理由是标题永远压在图上、不参与构图，抓马度上限低。改为**由 AI 一次画出整张带标题的海报**，用本地 ComfyUI 或 RunningHub 工作流出图。① 新增 `stages/production/scripts/cover_prompt.py`：把 brief（剧名/副标/市场/风格锚/人物关系/冲突物）编译成五段式提示词（STYLE / SUBJECTS / SCENE & LIGHT / COMPOSITION & TYPOGRAPHY / TECH），**标题自动断行**（≤3 行；西语 ≤18 字符、中文 ≤6 字；DP 均分且不拆词），并产出两种通道清单（`--emit comfy` → `comfyui_manifest.json` 直接喂 `comfy_client.py`；`--emit rh` → `rh_plan.json`，nodeId 必须 probe 后回填、不猜）；`--check` 拦「放不进 3 行 / 超长单词 / 文字块 >4 / 缺标题」。② 新增 `references/cover/prompt-guide.md`：五段式结构、排版指令标准写法（给确切字符串+位置+字体+描边）、抓马六抓手→提示词映射、**文字拼错的五级处置**（重试→拆行→加权→inpaint→兜底叠字）、合规与 12 条验收清单。③ `style-presets.md` 重写：六套预设从「暗罩参数」改为「风格锚 + 光位 + 文字处理」，映射到 `--style` （revenge-cold / latam-mansion-gold / suspense-noir / fantasy-violet / urban-clean / east-period-gold，另加 latam-rain-night、family-estate）。④ `cover_forge.py`（PIL 叠字）**降级为兜底**并在文件头写明原因；`release_check.py` 放宽封面命名以识别 `cover_9x16_00.png` 多候选。⑤ 技能 `drama-cover-forge` 的**工作目标 / 工作流程（六步）/ 交付标准（12 条）** 整体重写，并新增 `scripts/cover_prompt.py` 转发壳。验证：`test_cover_prompt.py` **38/38**（内容提交 `89f5104`）。
  - **V0.5-4 · 剧本改写改为「四段法」**：解决「40 集四件套格式齐全、内容同质」。原流程 `plan → build → lint` 直接跳进正文，`cold_open/core_conflict/reversal/hook` 默认来自句库拼装，写完也只验格式不验观看体验。改为**四段带门禁**：① **诊断** `diagnose`（A 选题七问：核心卖点/情绪共鸣/主角四项/落差/观众期待/钩子落位/硬伤；B 改编策略 keep+changes 四类且每条写戏剧目的；C 主线五要素）—— 预填只带事实型上下文，判断型字段留空；`--check` 退出码 2、`--confirm` 落 `structure_confirmed`，**未确认 `build --emit` 返回 4**（旧项目无诊断卡仅告警）；② **结构审查** `review` 十项确定性体检（主角主动率、反转是否改格局〔连续三集无筹码变化即 FAIL〕、冲突去重与连续三集重复、钩子与本集的因果共享〔剔功能词 2-gram〕、情绪是否机械轮转、爆点间隔、**句库残留**、前三集钩子、EP1 黄金 3 秒），FAIL 返回 2；`--write-fixes` 出按集号的待改清单；**句库残留会把表面 OK 降级为「需人工复核」**；③ **正文** `build --emit` + `lint`（原有）；④ **观众验收** `audience`（七问，校验 ≥40 字、至少 4 问引用 EPxx、Q7 恰好 3 条且每条带改法）。配套：新真源 `docs/creation/剧本改编四段法.md`；新 `references/genre-profiles.json`（复仇逆袭/甜宠/悬疑/家庭伦理的结构侧重、情绪序列、主动与格局信号词、必检项、题材红线、改法提示；`review` 按 `must_check` 把 WARN 升级为 FAIL）；新提示词 `prompts/s3a-diagnosis.md`、`s3c-audience-review.md`，`s3-script-rewrite.md` 收敛为只管第 ③ 段并加四段路由；`plan --from-outline` 支持第 5 列情绪、`plan` 落 `structure_profile`；`creation.py status` 增三行状态。**只增不改**：既有 blueprint 字段与退出码口径不变。新增 47 例离线测试（`test_script_design.py`）。**⑧ 下游联动（同日补，防「剧本一个内容、分镜/提示词另一个内容」）**：`plan` 每集输出 `plot_points`（`EPnn-P1..P4`）；新增 `stages/production/scripts/script_continuity.py`（六项：镜数丢镜/拆镜、台词逐字指纹〔前 24 字〕、人物代号映射〔重音归一，场景与末帧参考不计人物，主角零参考 FAIL / 配角零参考 WARN〕、时长合计 ±10%、首镜落 `cold_open` 与末镜落 `hook`、中段节点落点；退出码 0/2/4，缺产物不空转通过；跨语种与句库元指令降级为告警）。实测 `D:/剧本/海外剧/1` 40 集：镜数 40/40 对齐、台词逐字命中、时长一致 → **40/40 通过**；同时暴露「blueprint 中文 / 剧本西语」跨语种与若干配角无参考图。总纲新增环节 **5.5** 与「往下游交什么」锚点表（镜号/台词/人物/时长/节点五锚 + 已知 `SC` 命名歧义的裁决）；画风三轨 §六 补两条跨技能不一致裁决；`lint` 新增「CHAR 未在 HEADER 登记」告警；新增 24 例离线测试（`test_script_continuity.py`）
  - **V0.5-5 · 默认口径下调 30 集 × 60 秒**：用户拍板把默认剧集从 40 集 × 70 秒下调为 **30 集 × 60 秒**。① 默认值同步五处：`stages/creation/scripts/script_rewrite.py`（`DEFAULT_EPISODES=30` / `DEFAULT_EP_SECONDS=60`）、`creation.py`、`creation-brief.template.json`、`tools/cli.py init`（`--ep 30 --sec 60`）、`tools/core/storage.py` 建表默认，Web 控制台 `script.plan` 参数与文案同步。② **时长改为分档校验，避免打死老项目**：`tools/core/schema.py` 新增 `SECONDS_PROFILES`（60 → 5–10 镜 / 60–80 秒；70 → 5–12 镜 / 70–95 秒；90 → 6–15 镜 / 90–120 秒）与 `ep_bounds()`；`script_rewrite.py` 保留同口径副本与 `bounds_for()`；`lint` 与 `tools/core/validate.py` 的 E006（含分镜总时长）**按项目 `ep_seconds` 选档**，老项目继续按 70 秒档校验。③ 节拍随集数下调：`MID_BOOM_EVERY=3`（30 集 9 次）、`BIG_BOOM_EVERY=7`（4 次），留存三段 `EP1-3 / EP4-8 / EP9+`（留存活口占比与原 40 集口径的 17.5% 对齐）。④ 修 `build` 骨架 DUR：按 `ep_seconds/shots` 均分（60 秒 8 镜 = 62 秒；原 5/8/5 只有 58 秒，一出骨架就被 lint 判越界），骨架 `<CHAR 代号>` 占位不再触发「未登记代号」告警。⑤ 文档口径统一：总纲 §3.2 与环节 4、`ffs-spec.md`、`剧本强度工程.md`、`qa-gates.md`、`s3-script-rewrite.md`、`剧本改编四段法.md`、`新项目启动提示词.md`、`Agent项目技术文档.md`、`module-contracts.md`、README。⑥ 新增 4 例离线测试（默认 30 集、60/70 秒分档、老口径兼容）
  - **V0.5-6 · 开工前环境自检**：起因是一次真实的误判 —— 用户已装 Pillow 12.2.0，但装在 WorkBuddy 托管 venv `~/.workbuddy/binaries/python/envs/default/`，而 `python` 命令指向 `~/.workbuddy/binaries/python/versions/3.13.12/`（base）。结果 `test_cover_forge` 6/6 全红、`test_feedback_20261020` 的 `t_oom_plan` 报 `ModuleNotFoundError: No module named 'PIL'`，**代码没问题，环境错配**，但报错信息把人往代码方向引。① 新增 `tools/env_check.py`（纯标准库、零网络、可离线）：必需项 **Python ≥3.10 / Pillow / ffmpeg / ffprobe**，可选项 httpx、whisper-cli、`RUNNINGHUB_API_KEY` / `RUNNINGHUB_BASE_URL`、ComfyUI `127.0.0.1:8188`，另加 `manifest.sha256` 自校验（被 scaffold 拷进项目后自动跳过）；**核心是解释器错配检测** —— 扫描 `envs/*`、`versions/*`、`C:/Python3*`、conda 等候选，逐个探测依赖，命中即打印「哪个解释器装了哪个版本」并给两条修法：A 用已装好的解释器跑（零安装，`envs/default` 优先推荐）、B 给当前解释器补装；支持 `--json`（给 Agent）、`--quiet`、`--fix`（只打印命令、不执行安装），退出码 0/2。② README 顶部加「⚙️ 开工第一件事：先自检环境」块，正文新增 **§零 环境自检（开工前第一件事）**：检查项表 + 三种典型失败 + 给 AI 助手的用法（`ok:false` 时不许开工）。③ `docs/新项目启动提示词.md` 新增「**第 -1 步 · 环境自检（不做完不许开工）**」，要求 Agent 把 `ok` 与 `alt_interpreters` 报给用户、由用户在 A/B 中选，不得自行安装。④ 总纲链路表新增环节 **-2**（标题改为「16 环节 + 前置自检 + 5.5 连续性门禁」）。⑤ `creation.py scaffold` 结尾流程提示补 -1 步。⑥ 新增 21 例离线测试（`tools/tests/test_env_check.py`）
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
| `stages/assets/scripts/character_design.py` | 新增（角色差异化设计器） | **v1.0.0（2026-10-20）** | 六维签名分配（骨相 14 型 / 发型 15 型 / 面料 12 型 / 色签名 10 槽 / 识别锚 24 个 / 体态 8 型 / 人群桶 10 类）+ 三件套提示词产出 + 六条硬规则门禁 + 老项目同质化体检；纯标准库、确定性；配套 28 例离线测试。规范真源 `docs/assets/角色差异化设计规范.md` |
| `docs/assets/角色差异化设计规范.md` | 新增（角色形象单一真源） | **v1.0.0（2026-10-20）** | 五根因 · 六维签名 · 六条硬规则 · 提示词三件套 · 语言纪律 · 验收五问 |
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

