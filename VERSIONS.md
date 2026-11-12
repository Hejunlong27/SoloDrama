# VERSIONS.md —— 引擎收编清单与版本固化

- 收编日期：2026-10-08
- **2026-11-12 更新（LLM 记账框架 · T1 路线 2）**

  | # | 变更 | 说明 |
  |---|---|---|
  | 1 | 统一模型调用入口 | 制片助手改走 `Gateway.chat()`，不再直接调用 provider；多轮对话也写入 `usage.jsonl` |
  | 2 | 补齐用量证据 | OpenAI 兼容适配器保留完整 `usage.raw`，不再丢弃中转站返回的 cost、缓存/推理 token 等字段 |
  | 3 | 项目归属 | 新 usage 记录写入 `project`；`/api/llm/usage` 支持 `project` 过滤，旧记录保持兼容 |
  | 4 | 金额状态收口 | summary 新增 `cost_status` / `cost_unknown_records`，成本中心与模型中心明确显示已知/未知，未知不回退为 0 |
  | 5 | 回归测试 | 新增 `web/tests/test_llm_framework.py`，覆盖 Gateway 记账、未知金额、混合金额和 Agent 不旁路 |
  | 6 | 助手费用闸门 | `POST /api/agent/chat` 必须显式 `confirm=true`；前端每次发送先弹出「最多 12 步、按供应商 usage 结算」确认 |
  | 7 | 生成模型能力目录 | 新增 `configs/generation-models.json`，按模型声明参数、默认值、范围和端点；首批登记 GPT Image 2.6 低价版与 Muse Video |
  | 8 | 参数校验入口 | 新增 `web/core/generation_models.py`，把 UI 选择映射为平台请求字段；Muse 的时长 2–10 秒和 720p 是模型约束，不是全局视频限制 |
  | 9 | 模型参数 UI | 生成通道页新增模型参数表单与只读校验按钮，展示最终平台请求字段，不提交任务 |
  | 10 | 媒体任务状态层 | 新增 `web/core/media_tasks.py`：本地任务 ID、远端 task ID、报价/最大费用、状态归一、断点恢复与重复提交保护 |
  | 11 | 媒体任务观测 | 新增 `/api/media/tasks*` 只读接口，并在生成通道页显示任务状态、远端 ID、预估价与实际金额 |
  | 12 | ZZAI 媒体客户端 | 新增 `stages/media_api/zzai.py`：钱包、模型、公开价格、免费 estimate、授权提交、轮询、usage 提取与下载；提交默认拒绝 |
  | 13 | ZZAI Mock 回归 | 新增 `stages/media_api/tests/test_zzai.py`，6 例覆盖成功/失败退款/下载/上限头/Key 脱敏；当前未调用真实接口 |
  | 14 | ZZAI 只读 CLI | 新增 `python -m stages.media_api.cli`，仅提供 wallet/models/pricing/estimate，不提供 submit |
  | 15 | 多中转站主备路由 | `purposes` 支持 `routes[]` 主路由 + 备用路由；旧 `provider_id/model` 配置保持兼容 |
  | 16 | 安全故障切换 | Gateway 仅对 config/auth/quota/model_not_found/rate_limit 切换备用；timeout/server/schema 等不静默重提，避免重复计费或掩盖内容问题 |
  | 17 | 路由审计 | 每次尝试独立写入 usage，并记录 `route_id/provider/model/error_kind`；用途页显示备用链路数量且保存主模型时不会清空备用路由 |
  | 18 | 路由链编辑器 | 模型中心新增路由链弹窗：添加、删除、上下调整主备路由，复用 `POST /api/llm/purposes/{pid}` |
  | 19 | 提供商健康状态 | `list_providers` 从 usage 派生 healthy/cooling/blocked/degraded/unknown；rate-limit/timeout/network/server 进入有时效冷却 |
  | 20 | 冷却路由跳过 | 有健康备用路由时自动跳过冷却中的主路由；若所有路由都在冷却则保留原链，避免系统被直接锁死 |
  | 21 | 分镜图独立门禁 | `model-plan.json` 新增独立 `board.choice`，不跟随 `image.choice`；老项目未确认时安全回落本地 |
  | 22 | 分镜图多通道 | `gen_boards.py --engine auto/local/cloud/zzai`：本地 ComfyUI、仙宫云 ComfyUI、ZZAI 图片 API；人工通道不静默回落 |
  | 23 | 分镜图 ZZAI 执行链 | 先用免费 estimate，再要求 `--yes` 与 `--max-cost`；submit/poll/download 后写 `.drama/media` 任务记录 |
  | 24 | 分镜图固定图生图 | `board.frame` 禁止无参考图退化文生图；本地/仙宫云至少加载角色/场景参考图，ZZAI 先上传参考图并传 `images[]` |
  | 25 | t2i/i2i 工作流预设 | model-plan 支持 `comfy_workflow_t2i` / `comfy_workflow_i2i` 与 `workflow_id_t2i` / `workflow_id_i2i`；分镜图固定读取 i2i |
  | 26 | RunningHub 分镜图 | 新增 `runninghub_workflow` board 通道；上传参考图、按 prompt/image(s)/aspect 节点映射提交 i2i，任务 ID/usage 写媒体台账 |

- **2026-11-10 更新（V0.7.76 · Studio 2.0 Phase 1：独立设计系统（深/浅双主题）+ 依赖版本对齐）**

  本版**不动引擎、不动文件契约、不动生产门禁**，只做控制台视觉层与依赖声明。

  | # | 变更 | 说明 |
  |---|---|---|
  | 1 | `web/ui/studio/css/tokens.css` 重构为三层 | 基色板 / 语义 Token（`--sd-*`）/ 旧变量别名。旧名一个不删，22 个视图零改动即可继续工作 |
  | 2 | 深/浅双主题 | `[data-theme]` 切换，浅色只覆盖语义层；`<head>` 内联脚本定首帧防闪白；`?theme=dark\|light` 可临时强制（不写记忆） |
  | 3 | `css/app.css` 按钮段改接 Token | 原引用外部规范（陶土 `#c96442` + 炭 `#30302e`），与琥珀 Token 并存导致同屏两套暖色。现统一为 `--sd-accent` |
  | 4 | 新增 `css/components-2.css` | 只新增类名：`.btn.danger` `.sd-poster` `.sd-stages` `.sd-prompt-sec` `.sd-cost-row`，以及全局 `:focus-visible` |
  | 5 | 新增 `js/theme.js` | 三态 `auto/dark/light`，`localStorage.sd-theme` 记忆，系统外观变化实时跟随 |
  | 6 | 新增 `design.html` | 视觉样板（真实组件 + 实时读取计算后的 Token 值），双主题可切换 |
  | 7 | 浅色强调色严格用 `#9B7145` | 规范给定值原样使用；白底 4.34:1，**已知不足 AA**，需 AA 的文字级金色改用 `--sd-accent-strong`（`#8A6439`，5.30:1） |
  | 8 | 依赖对齐 | `web/requirements-web.txt`：`fastapi==0.143.3 → 0.162.0`；`requirements.txt`：`Pillow==12.2.0 → 13.0.0`。两处均为本机实际运行且 `web/tests` 146 项全绿验证过的版本 |
  | 9 | 硬编码色清零（T2） | `app.css` 72 处 → **生效仅 1 处**（`.video-box video` 黑边，属画面内容，故意保留）。旧状态色走 `color-mix`，白/黑遮罩改为跟随 `--sd-text`（否则浅色下白色叠加等于不可见），阴影走 `--sd-shadow-*` |
  | 10 | 状态色双档 | 新增 `--sd-{ok,teal,warn,danger,info}-ink`（淡底文字档）。浅色下实测：ok 3.91→4.97、teal 3.60→4.86、warn 3.46→5.34、danger 4.59→5.81 |
  | 11 | 新增 `design-probe.html` | 对比度探针：打印每个组件两种主题下的真实计算色与对比度，底部给 `LOW(<4.5)` 清单。改 Token 后必跑；当前 `LOW` 仅剩浅色主按钮 4.34（用户拍板品牌忠实优先） |
  | 12 | **信息架构：15 项平铺 → 5 个工作空间** | 创意工作室 / 视觉资产 / 分镜与拍摄 / 后期与发行 / 制作控制 + 4 个全局入口。侧栏只展开「当前所在」那块，成员横向移动靠新增的工作空间页签条（`#wsbar`）。**所有旧路由不变**，书签不失效 |
  | 13 | 首页重做 | 「继续创作」海报墙（2:3、真实剧照、当前项目带阶段角标）提到首屏第一块；KPI 4→3；项目表移到底部；数据全部来自 `/api/workspaces` 与 `/api/studio/cover` |
  | 14 | 新增 `/api/studio/cover` | 海报封面只读端点：资产图 → 分镜图 → 根层散图取 mtime 最新；路径只从 `_layout.stage_dir()` 来，前端不拼目录；60s 缓存 |
  | 15 | 品牌副标题 | `STUDIO 0.2` → `STUDIO 2.0` |
  | 16 | **项目详情 → 项目驾驶舱** | 旧「7 环节 23 节点」口径是过期文案（实际 5 环节 13 节点，同一处 `web/core/adapters.py` docstring 也写错），一并修正。阶段矩阵按「环节名（引擎真值）+ 节点契约 id」渲染，不给节点自造中文名 —— 否则引擎改 id 后 UI 会说旧名字 |
  | 17 | 新增「下一步」与判据冲突提示 | 下一步 = 拓扑序第一个未通过节点，原样显示 `detail`（含「上游未通过：X」），`video.*` 标注「计费节点」；当「集列表有成片但节点判据缺产物」时，页面上明说两个口径不一致且引擎不会跳过 |
  | 18 | 新增 `web/tests/test_studio_ia.py` | 5 条静态守卫：视图必须有入口、导航不得指向不存在视图、`PROJECT_ROUTES` 必须可点、《引擎环节必须都有落点》防止「去处理」静默退回、overview 不得硬编码节点 id |
  | 19 | **修一个长期静默 bug**：`studio.prompt_of()` 少拼 `<ep>/` 一层 | 真实路径是 `data_dir(ws)/<ep>/h3_prompts.json`（本机实测 30 个集各一份）。旧实现读 `<data_dir>/h3_prompts.json`，永远 `no_prompts` —— 提示词面板一直是空的，且不报错 |
  | 20 | 新增 `stages/import/prompt_edit.py` | 单镜提示词的 read / check / save。解析与校验一律复用 `h3_prompt`（不在 Web 层再写一套正则）；`save` 前先备份 `.bak-<时间戳>`、原子替换、写后复检；结构/标签级错误默认拒写（`rc=3`），要存半成品须显式 `--force` |
  | 21 | `/api/studio/prompt` 扩参 + 新增 POST | GET 支持 `ep`（不给且跨集存在时返回 `ambiguous` + 候选）；新增 POST 写回（只读模式 423）。兼容 `ep01_shot_001` 形式的合成镜头 id |
  | 22 | 分镜页提示词面板改为编辑器 | 六段式 → 逐段编辑（段名中文对照仅显示用，键与顺序来自引擎 `section_order`）；非六段式 → 全文编辑（分段保存会丢前言，不能给）。问题清单在打开时就摆出来，不等到点保存 |
  | 23 | 发现并记录 T19 | `h3_prompt.split_sections` 的 docstring 说支持「段头行内接正文」，实测行内内容被吃掉、段体为空。未改引擎判据（会放过本该拦的提示词），改为 `inline_hints` 把真实原因说出来 |
  | 24 | **分镜页改三栏工作台** | 左 288（镜头列表：搜索 / 集号 / 状态筛选）/ 中 弹性（画布 + 状态·批次·任务号·文件 + 续跑）/ 右 430（提示词）。三栏各自滚动；断点 1440→250/386、1240→228/344、1040 起单栏堆叠。新增上一镜/下一镜，按**筛选后**的顺序跳 |
  | 25 | **提示词改回整段编辑**（推翻第 22 项的逐段方案） | 用户裁决：拆成六个框之后，每次拿去模型里试都要自己拼回去，复制粘贴平白多一步。现在＝一个 `textarea` 装完整原文（含段头）+ 一行只读结构 chip（缺段标红）+ 一键复制全文；保存走 `text` 整段写回，落盘内容与眼前一致 |
  | 26 | 校验清单改为「一行摘要 + 展开」 | 右栏同时要装编辑区和诊断信息，全展开时编辑区只剩四五行。摘要常驻（阻断条数 / 首条编码 / 缺几段），正文默认收起；**保存被拦时自动展开**并露出「仍然保存」 |
  | 27 | 守卫测试 +2 | `test_storyboard_is_three_column`、`test_prompt_editor_stays_single_block`（后者防「以后有人觉得分段更整齐又拆开」，同时禁止 `parts:` 按段写回） |
  | 28 | **创作页改三栏工作台** | 左 268（文档树：灵感 / 企划案 / 资产库 / 分集剧本 / 导演手册 × N 集）/ 中 弹性（Markdown 编辑 ⇄ 只读预览）/ 右 372（下一步 / 生成参数 / 制作包 / 上下文）。文档清单来自 `/api/create/state`，前端不再写 `const PIPE` 常量（旧实现硬编码七段标签，引擎一改就漂移） |
  | 29 | **修一个会静默毁数据的路径** | 旧结构里点「导演手册」会进入编辑整本（`read('director')` 把 30 集拼成 598K 字符），保存时 `write()` 拿不到 name 回落到 `第01集.md` → 第 1 集被整本覆盖且无报错。现在有文件的多文件阶段渲染成**不可点的容器头**，只有每一集可点 |
  | 30 | 受限 Markdown 预览 | 标题 / 表格 / 列表 / 引用 / 分隔线 / 粗体 / 行内码 / 代码块。先整段 `esc` 再处理标记，不支持的内联 HTML 原样显示。理由：企划案立项卡是表格、导演手册靠 `##` 分节，纯文本看不出结构；项目不引 Markdown 依赖 |
  | 31 | 灵感参数回补 + `?doc=` | 原卡片的「集数 / 单集秒数」在改版中一度丢失，已并回灵感文档的工具条；当前文档写进 URL（`?doc=director/第05集.md`），刷新/分享不再跳回第 1 集 |
  | 32 | 守卫测试 +2 | `test_multifile_stage_is_not_editable_as_one_doc`（多文件阶段必须有容器标记）、`test_create_stage_list_comes_from_api`（禁止前端再写阶段常量） |
  | 33 | **T20 完成：创作版本对照** | 新增只读 `GET /api/create/versions`（当前 + 该产物自己的全部 `.bak_<时间戳>.md`）与 `GET /api/create/version`（读某版正文）。创作页工具条加「版本」→ 宽版弹窗左右行级 diff（`+N/-N`，两列滚动同步）+ 一键恢复。**不建版本库**：磁盘备份即版本；恢复走 `write()`，会先把当前内容再备份一份 |
  | 34 | **修复参考图错位的静默 bug** | `pack_import._pick_image()` 原来用 `rest.endswith("_" + code)` 匹配，而真实产物名是 `P01_Elena_VIEW_00.png`（尾部带帧号 `_00`），条件恒假 → 掉到「该 ID 唯一一张图」兜底。实测 `P01@VIEW/EXP/LOOK-A/B/C` **五个键全指向 `P01_Elena_EXP_00.png`**，出片一直拿表情图当造型参考。改为分段匹配（`_<code>_`），补 2 条回归测试 |
  | 35 | 修复工具条按钮无效绑定 | 保存 / 复制 / 版本 / 编辑预览切换由 `renderDoc()` 用 innerHTML 生成，而它是异步的、比 `mount()` 晚；在 mount 里 `querySelector('#edSave')` 得到 null → 按钮**永远没有处理函数**且无报错。抽出 `bindEditor()` 在 `renderDoc` 之后调用 |
  | 36 | `modal-wide` 收尾 | 宽版是「这一次弹窗」的形态，`closeModal()` 里显式摘掉；否则下一个普通确认框会莫名变全宽 |
  | 37 | **角色身份图规范：16:9 三视图 + 表情四宫格** | 21 个题材 Skill 的资产卡段落统一改写：左 60% 三个完整全身视图（正面 / **严格 90° 侧面** / 背面，同人同比例同服装、头顶到鞋底），右 40% **2×2** 四宫格（Neutral / Happy / Shocked / Angry，只换表情不换人）；画幅由 9:16 竖构图改为 16:9 横构图 |
  | 38 | 新增 `stages/import/view_sheet.py` | 把**存量**资产库 md 的「三视图 / 表情四态」改写成新规范。只动这两块，造型与表格一字不动；改写结果先过 **13 项结构自检**（画幅/三视图名/90°/2x2/四种表情/两条禁止项），任一项缺失整体不写；默认干跑，`--apply` 才落盘并备份 `.bak_<时间戳>` |
  | 39 | **角色档案（同一角色的多套穿搭归并）** | 新增 `web/core/characters.py` + `GET /api/studio/characters`：把 `P01@VIEW / @EXP / @LOOK-A..E` 按角色聚成一张卡，卡内按层分组（三视图 → 造型 → 表情 → 状态）。数据只来自磁盘（资产库 md + `04-资产/characters` + `refs.json`），**不建索引、不落盘** |
  | 40 | 资产页新增「角色档案」区 | 一人一卡：编号 + 名字 + 变体进度 + 一致性锚点 + 按层分组的缩略图（3:4，图上直接标 `LOOK-B` 这类参考图 key）。点任一变体 → 看该变体全部图 + 提示词（可复制）。角色页签下保留原图片网格 |
  | 41 | 新增「按规范改写身份卡」入口 | 干跑优先：先显示「将改写 N 处三视图 / M 处表情块 / 自检是否通过」，再由人点「改写并备份」。只读模式下按钮禁用、端点 423 |
  | 42 | **主形象（master）** | 每个角色显式确定唯一主形象，选取顺序写死：`base` 层 → `turnaround`（三视图）→ 第一个有图的 look。取不到就 `master_missing=true`，界面显示「尚无主形象」而不是拿随便一张图冒充。主形象即封面、也是唯一基准，各套造型都是它的派生 |
  | 43 | **资产分类收敛为三类** | 依用户裁决移除「参考图」「散图」两个一级分类：`06-提示词/refs_h3` 是 `prepare_refs.py` 的瘦身副本（长边≤2048/JPEG，原图在 `04-资产/*`），属派生物；「散图」是未归位的图，属待办。两者降级为**诊断**入口（有内容才出现），不参与缺口与出图判定 |
  | 44 | 角色框重做 | 一个角色一个框：上方大图（主形象/当前变体，框内可滚动、高度≤480），下方一排文字 tab 切变体（★ 标主形象、缺图标灰）。点 tab 只换图不重绘整页。图区**不按 code 猜横竖** —— 存量 VIEW 是 9:16 竖图，按 code 判横会拉到两千多像素只剩头顶 |
  | 45 | 操作区放大 | 页签 / KPI（数字 30px）/ 缺口芯片 / 页头按钮统一抬一档；角色卡标题 19px、内边距 18px。资产页是看图和选图的地方，密度换可读性 |
  | 46 | 守卫测试 +2 | `test_asset_tabs_are_only_real_material_kinds`（分类只许三类）、`test_character_has_single_master`（主形象必须有唯一且优先级显式） |
  | 47 | **变体单张重出** | 角色框的变体图区加「重出这一张」：走引擎既有的 `--only P01@LOOK-B --force --submit`，只重跑这一张。通道**不由界面选**，读 `GET /api/studio/image-channel`（真源 `model-plan.json`）——界面自定默认值会与确认单不一致，被 `_model_gate` 拦成退出码 4，用户只看到「按钮没反应」 |
  | 48 | **修一个会永久丢原图的路径** | `comfy_client` 落盘是 `os.replace(tmp, final)`：**直接覆盖、不留旧版**。「重出更差」时原图已经没了。新增 `gen_assets_local.py --backup`：出图前把将被覆盖的图存到 `<目录>/_bak/`，文件名带 `.bak` 后缀 |
  | 49 | 备份为何必须是 `.bak` | `_scan_outputs()` 用 `iterdir()+startswith(prefix+'_')` 判产物；`pack_import._scan_asset_images()` 是 **rglob** 会递归进 `_bak/`。备份若仍叫 `.png`，stem 会被解析成 `P01`+`LOOK-B`，**和真产物抢参考图**。`.bak` 两处天然跳过 |
  | 50 | **修一个会阻断全部资产出图的边界** | `assets_from_pack()` 原来对 `rep.ok` 全量判断。而 30 集旧格式提示词会让 `SHOT019/020` 全红 → **本机任何项目都出不了资产图**，尽管资产卡完全合规。改为：只阻断资产级错误（PACK/ASSET/STYLE），分镜级（SHOT0xx）降级为打印提示。资产卡天生早于分镜提示词定稿 |
  | 51 | 新增 `GET /api/studio/image-channel` | 只读：返回这次会走哪条通道（`assets.local`/`assets.cloud`/`assets.rh_wf`）、是否计费、地址、工作流、是否假云端、能否备份。**RH 通道不支持单张重出**（它的 `--only` 是老 md 口径 `char_01`），界面上直接说清而不是静默失败 |
  | 52 | md ↔ pack 变体漂移检测 | 角色档案的**提示词**读 `00-创作/02-资产库.md`，**出图**只认 `pack/assets/characters.json`。两边不同源：改了 md 没重建 pack 时，点重出会用包里的旧提示词，或直接 `rc=2`「找不到资产 id」。`characters.roster()` 新增 `pack_exists` / `drift`，页面顶部给警告，弹窗里对「包里没有的变体」直接禁用按钮。实测抓到真实案例：`海外剧/10` 的 P12（md 有 VIEW/LOOK-A/EXP，包里只有 BASE） |
  | 53 | 修一条误导的提示条 | 「没找到资产提示词 md，出图会被引擎拒绝」在**有制作包**的项目上是错的（引擎优先读 `<ws>/pack`，有包就不看 `SOLODRAMA_ASSET_MD`）。改为仅在「既无 md 又无 pack」时出现 |
  | 54 | 重出后的缓存 | `/media` 是 `private, max-age=60` + ETag。不 bust 的话 60 秒内仍显示旧图，用户会认为「重出没生效」。只对刚重出的那一张加 `&v=<ts>`，不整页刷 |
  | 55 | 守卫测试 +10 | `test_asset_regen.py`（6：备份落点/递归扫描免疫/二次重出不重复备份/无产物不建目录/分镜门禁不阻断资产出图/资产级错误照旧阻断）、`test_image_channel.py`（5：云端→计费、无确认单→本地免费、假云端、RH 无备份、argv 必带 only+force+backup）、`test_character_drift.py`（4：无 pack 不误报、一致不报、md_only、pack_only） |

  文档：新增 `docs/architecture/`（4 份）、`docs/upgrade/01–07 + roadmap + inventory + phase-report`、`docs/design/`（8 份，含 `ui-redesign-plan.md`）。
  取证截图：`docs/design/shots/`（深浅样板 + 深浅首页）。

  **未做**：Phase 3 的页面级改造（首页、五工作空间导航、分镜工作台）尚未开始；`data/h3_prompts.json` 与 `06-提示词/` 的双份提示词仍是待定源（T5，Phase 4 前置）。

- **2026-11-10 更新（V0.7.75 · 新增第 13 节点 `edit.draft`：产出剪映工程，版权资料加第三入口）**

  需求原话是「把现在的剪辑方案板块全部替换掉，产出完整剪映工程文件」。
  **不能全替换**，理由写进代码而不是口头：剪映 7+ 把「导出」控件藏了，
  `pyJianYingDraft` 的自动导出只支持 Windows + 剪映 ≤6.8；模板加载在 7+ 也已失效。
  所以是**双轨并行**——MP4 仍由 ffmpeg 出（唯一发布版来源），剪映工程是**并行的可举证物**。

  | # | 变更 | 说明 |
  |---|---|---|
  | 1 | 新增 `stages/edit/scripts/edit_draft.py` | 读 `cues.json` + `bgm-plan.json` + `_master/` 造草稿：视频轨（封面+逐镜 final.mp4）、字幕轨（逐条 cue）、BGM 轨；三轨共用**母版轴** |
  | 2 | 新增节点 `edit.draft` | 13 节点：`edit.subtitle → edit.draft → edit.release`；判据 `draft` **只认** `draft_manifest.json` 的 `verdict.pass`，不认目录存在 |
  | 3 | `subtitle.py` 抽 `cover_lead_seconds()` | 唯一真源；`write_ass(offset_s=)`、`verify_render(offset_s=)` 共用 |
  | 4 | `copyright_kit.py --what edit-draft` | 出口 C 四张 A4：`draft-01-overview / 02-timeline / 03-subtitles / 04-digest`；人工截 `draft-shot-01-<ep>.png` |
  | 5 | `release_check.py` 加第三类 | `draft-*` 必过（≥4，≤20，长边 ≥1200）；`draft-shot-*` 缺只告警；`--no-draft` 给老项目 |
  | 6 | Studio | 命令 `media.draft`、`edit.draft` 节点/环节映射、episodes 记录加 `draft` 字段 |
  | 7 | 依赖 | `requirements-edit.txt`：`pyJianYingDraft==0.3.1`（MIT）；生成草稿在 Linux/macOS 也可用，自动导出不支持 |

  **顺手修掉一个既有静默 bug**：母版封面片头（`master.cover_seconds`，默认 0.8s）从来没被计入
  ASS/字幕时间 —— `cues.json` 是「片段轴」，母版是「母版轴」。有封面的项目每条字幕早 0.8 秒，
  而所有断言都通过。现在三处（ASS、剪映工程、渲染自检）都用 `cover_lead_seconds()`。

  防复发：
  - `test_edit_draft.py` **59 例**：亚秒精度（禁用 `trange()`，`0.2→0`、`1.6→2` 会截断）、
    封面偏移、dB→线性、空 cues 拒绝、**空画面拒绝生成**、**缺镜判不合格**、端到端、
    **篡改 `draft_content.json` 与断链必须被 `verify()` 抓到**、**首页时长被改成 0 必须判不合格**、
    **草稿根目录探测取 `draft_root_path` 众数而非 `root_path`**；
  - `test_copyright_kit` 新增「`draft-NN` 被门禁扫到 / `draft-shot-NN` 不被 `draft` 正则匹配」——
    防「截 4 张图绕过工程自检」；
  - `test_feedback_20261020` 的发布资料夹具补 4 张 `draft-*`（口径一变夹具必须跟上，
    否则它测的是「旧口径物料齐」）。这条正是本次唯一被测试抓到的回归。

  另：`compliance_media_check.py` 字幕带不再写死 0.60，改按项目 `config.subtitle.json` 的
  `placement` 推导（缺陷 R32：竖屏 0.84 落点被误判成「不像硬字幕」）。

  ### 剪映专业版 10.8.0.14162 实测（当日补测，已改口径）

  上一版记的「本机未安装剪映」是**错的**：剪映装在公开目录而非 `AppData\Local\JianyingPro\Apps`。
  实测四条，都写进 `docs/production/剪映工程.md §七`：

  | 事项 | 实测 |
  |---|---|
  | 安装 / 索引 | `D:\Program Files (x86)\JianyingPro`（10.8.0.14162）；索引在 `%LOCALAPPDATA%\...\com.lveditor.draft\root_meta_info.json` |
  | **真实草稿根目录** | `D:\Program Files (x86)\JianyingPro Drafts` —— 索引里的 `root_path` 仍指 C 盘默认位置，**照它生成剪映看不见** |
  | 剪映自己写的草稿 | `draft_content.json` / `draft_meta_info.json` 均为加密串，不是明文 |
  | 剪映读明文 meta | **能**。补 `tm_duration`/`draft_cover` 后首页卡片从「00:00 + 黑块」变「01:01 + 真实画面」 |
  | 自动发现新草稿 | **会**。草稿目录放进根目录，启动 3 秒内注册进索引（35→36），无需手改索引 |

  据此新增：`--to-jianying`（自动探测草稿根目录，生成完开剪映就能看见）、
  `detect_jianying_root()`（取 `draft_root_path` 众数）、`_patch_meta()` + `_make_cover_jpg()`（首页时长与缩略图）。
  清单/报告改为落两处（`07-成片/<ep>/_draft/` 供节点判据 + 草稿目录内随草稿搬走），
  不再把 `draft_manifest.json` 扔进剪映草稿**根目录**。

  仍缺一步：**双击打开后时间轴是否完整**需要人在桌面确认一次（脚本所在会话没有交互桌面，
  不能模拟点击），验证前只能说「剪映已列出工程且时长/缩略图正确」，不能说「一定能打开」。

  实跑还抓出两个「看起来成功」的坑，一并堵掉：**一段画面都没有**时原来会生成
  「视频 0 段 / 字幕 9 条」的空壳草稿并报「自检通过」（现在直接拒绝，退出码 3）；
  **缺镜**原来只打 WARN 就判 pass（现在照落草稿给人看，但结论判不合格）。
  四张证据板末尾加「这一页证明什么 · 怎么核对」块（只写可核对的事实与命令）。

  回归：pytest **562**（prod 135 / subtitle+web 193 / cloud+video+import+engine+tools 234）
  ＋ 脚本型（edit **59** / feedback 40 / nodes 22 / release_check 22 / thin_one 16 / asset_md 19）全绿。
  干净 HEAD 上同样红的 6 个脚本型用例（`test_repo_paths` P01、`workflow_map` 1、
  `web` 的 connections/new_actions/pipeline/skill_library/llm_e2e）属**既有环境问题**，与本次无关。

- **2026-11-07 更新（V0.7.74 · 版权资料改口径：平台两个入口 + 权利声明，旧 4+4 废止）**

  真实驳回：TikTok Drama Center **「材料不足：提交的版权材料不足以证明本剧所需的相关权利。」**
  旧口径要求的 8 张（`ai-process-01..04` + `source-file-01..04`）正是被驳回的那一版。两个错：

  | 错 | 说明 |
  |---|---|
  | 对标错 | 平台要截图「对应拟上线作品的具体画面、角色、场景或片段」，我们交的是批次表/参数/目录树/ffprobe |
  | 层次错 | 截图只回答「是我做的吗」；平台问「**发行权在你手上吗**」—— 权利人、原创性、AI 合规、第三方清零、授权范围，截图证不了 |

  | # | 变更 | 说明 |
  |---|---|---|
  | 1 | 新增 `copyright_kit.py` | 入口 A 四联板（提示词+分镜图+成片帧+资产卡，同一镜）、入口 B 六类文件信息板、7 页 A4 权利声明；三件套一次出 |
  | 2 | `release_check.py` 改判据 | 入口 A/B 各 **≥4 张（≤20）**、权利声明 01–05+07 必须、06 视情况；旧前缀只告警不阻断 |
  | 3 | `docs/distribution/发行资料清单.md` §四 重写 | 真源换成「两入口 + 权利层」，含逐条判据、命名、提交顺序、措辞纪律 |
  | 4 | 清理旧口径 | 使用者路线 / 项目档案 / 标准作业流程 / 生产流程总纲 / 技能映射 / 退役表：`4+4` 全部替换，旧前缀进「补充材料」 |
  | 5 | Studio 命令 `release.copyright` | 生成三件套；参数 `--what/--shots/--count/--entity/--registration` |
  | 6 | `<ws>/copyright.json` | 主体名、注册号、模型许可口径、代表性镜头标题 —— 人才能定的，引擎不猜 |

  两条防复发：
  - `test_release_check` 的夹具改按新结构造（旧夹具正是被驳回那版，门禁改了也测不出来），18 例；
  - `test_copyright_kit` 11 例守「生成器命名必须被门禁扫到」「门禁要求的编号必须都在渲染清单里」。
  另修 `test_feedback_20261020` 里 5 条**过期断言**（本机出片 2026-11-04 起已有执行器；
  两条用例引用的脚本已退役）：40 例全绿。

  回归：pytest **530**（prod 134 / web 146 / import 78 / video 50 / cloud 49 / subtitle 47 /
  tools 15 / assets 11）＋ 脚本型 **198** 全绿。

- **2026-11-07 更新（V0.7.73 · 资产出图：种子逐条派生 + 负向词走真负向通道）**

  用户反馈「做出来的剧，角色形象全部趋同」。查资产链路，两条机械成因：

  | # | 病灶 | 证据 |
  |---|---|---|
  | 1 | 清单里**一条 `seed` 都没有**，`build()` 的 `if seed is not None` 永远为假 | 3 角色 + 6 场景共 9 张图实测拿到**同一个** `noise_seed`（工作流写死的 1001791701491090） |
  | 2 | 卡片末尾 `EXCLUDE:` / `人物负面：` 段被当**正向提示词**提交 | 工作流 `negative_prompt` 为空、`cfg=1`；等于反复说「网红脸、削尖下颌、放大眼裂」 |

  | # | 变更 | 说明 |
  |---|---|---|
  | 1 | `asset_md.derive_seed` | `seed = 基底 + hash(id)`，逐条不同、同一 id 可复现；新增 `--seed-base` / `--vary` |
  | 2 | `asset_md.split_negative` | `EXCLUDE:` / `NEGATIVE:` / `人物负面：` / `排除：`（行首或句末标点后）整块拆出，正向提示词不再含否定块 |
  | 3 | `comfy_client.build(negative=)` | 写进 `negative_prompt` 节点（`neg_node_of` 自动探测，`COMFYUI_NODE_NEG` 可覆盖）；无节点则告警不静默丢 |
  | 4 | `gen_assets_local --neg-mode {auto,strip,block}` | `auto` 拆出并**说明是否生效**；`strip` 丢弃；`block` 用不上就拒绝出图 |
  | 5 | 清单新增 `seed_base` / `negative` / `negative_effective` / `_workflow{cfg,negative_node}` | 结论可审计：这锅是谁的、负向到底生不生效 |
  | 6 | `pack.json::negative` 终于被读 | 此前它没有任何消费方；现与每条卡片的否定块合并 |
  | 7 | 21 份题材模板的「人物负面」行补一句 | cfg=1 下负向词不生效，压网红脸要写正面特征 |
  | 8 | `drama.py assets` 增 `--seed-base / --vary / --neg-mode` | 文档让用户走这一层，参数到不了脚本等于没这功能 |

  ⚠ **说清一件事**：默认出图工作流 `workflow_qwen21_t2i_hq.json` 的 `cfg` 是 **1**，
  负向条件乘 0 —— 词写进 `negative_prompt` 也**物理无效**。所以清单记
  `negative_effective: false`，运行时打 WARN。要真生效只有两条路：换 `cfg≥2` 的工作流
  （`workflow_qwen21_t2i_hq_9x16.json` 是 2.0），或把否定改写成正向具体特征。
  **本批修掉的是「否定词被当正向用」这个反向伤害，不是「负向词生效」。**

  守卫：`stages/assets/scripts/tests/test_asset_seed_negative.py` 11 例
  （拆词四种写法 / 空块不吃提示词 / 种子稳定且互不相同 / 清单记 seed_base 且哈希覆盖负向 /
  写进 471 节点 / cfg 判据）。回归：pytest **519**（assets 11 新增）+ 脚本型 **121** 全绿。

- **2026-11-06 更新（V0.7.72 · 视频提示词锁成 H3 多参六段式：`{{Mixed n}}` 从来就没被模型认过）**

  用户反馈「提示词生成的效果不佳」。查现有产物发现三件事叠在一起，根因是**参考图没被点名**：

  | 现象 | 真相 |
  |---|---|
  | 提示词里写 `{{Mixed 2}}` | 那是本仓库的占位符，H3 不认识 —— 它被当正文读进去，参考图等于没绑定 |
  | 没有 `subject_definitions` | 「第 2 张图是谁、要保留什么」全靠模型自己猜，人物一集一个样 |
  | 「上传顺序：Mixed 1＝…」整行是中文 | 会被当成「画面中应出现的文字」，有概率烧进画面 |

  | # | 变更 | 说明 |
  |---|---|---|
  | 1 | 新增 `stages/import/h3_prompt.py` | 六段式判据**唯一真源**：解析 / lint（14 条判据）/ 归一化 / CLI 体检 |
  | 2 | `pack_spec` 新增 `SHOT019` / `SHOT020`（阻断）、`SHOT021`（告警） | 结构错与质量项分开：结构错必然重跑（花钱），质量项只提示 |
  | 3 | `md2pack` 归一化 `{{Mixed n}}` → `<Picture n>` | 顺手删掉「上传顺序：」脚手架行（它会被画进画面） |
  | 4 | 21 份题材模板 × B 段整块重写 | 六段示例 + 「六段分别写什么」表 + 三条禁令（`{{Mixed}}` / `<Video n>` / 负向词） |
  | 5 | `skill_director.md` §五重写 | 提示层与判据同源；补 `<Picture n>` = 上传顺序、`(Sx)` 发声顺序、时间戳写法 |
  | 6 | 文档 | 新增 `docs/pack/H3-REF2VA-PROMPT.md`（锁定契约 + 完整样例 + 判据表）；PACK-SPEC §5.3 重写 |
  | 7 | 修正两处**假文档** | §8.3 声称「导入器会机械重排图号」——代码里没有这个实现；`init_project` 的骨架说明同样在教错 |

  另：`--drop-missing-cast` 在六段式下**拒绝执行** —— 摘一张图要重排全部 `<Picture n>` /
  `<Subject n>` 与 retention 行，机械重排会静默改语义。宁可让门禁点名。

  守卫：`test_h3_prompt.py` 23 例（结构/标签/质量三档 + 与门禁接线）、`test_md2pack` 增端到端
  「模板 → 转换 → 门禁全绿」1 例、`test_video_remote` 的 `--engine` 断言改为解析 choices。
  回归：pytest 508（import 78 / web 146 / prod 123 / video 50 / cloud 49 / subtitle 47 / tools 15）
  ＋ 脚本型 121 全绿。

- **2026-11-06 更新（V0.7.71 · 云端出片通道打通：pika 工作流实测可用 + 节点按确认单选通道）**

  用户实测确认：`workflow_h3_pika_8g.json` 在仙宫云镜像可直接跑通（含 LoRA 与 LayerStyle 节点）。

  | # | 变更 | 说明 |
  |---|---|---|
  | 1 | `drama video run --engine auto` | 通道只从 `<ws>/model-plan.json` 的 `video.choice` 读一次：`cloud_comfyui→cloud`、`runninghub*→workflow`、`local_comfyui→local`；无确认单回落本机（￥0）并打印原因；`closed_source` 明确拒绝（无内置执行器） |
  | 2 | 出片节点模板 `--engine local` → `--engine auto` | 原来节点写死本机，**确认单选了云端也永远跑不到 pika**——两套真源；现在统一 |
  | 3 | 依赖状态从「待确认」改为「已实测」 | `docs/云端ComfyUI接入.md`、`workflow_h3_pika_8g.map.json`（`_extra_deps` / `_verified`） |

  守卫：`test_video_plan.py` +7 例（映射表全覆盖、无确认单回落、cloud/RH 解析、未确认不偷跑、闭源拒绝、节点模板必须是 auto）。
  回归：生产 123（+7）＋脚本型 58 全绿。

- **2026-11-06 更新（V0.7.70 · 复盘遗留：B3/B4/B5 处理完 + R2/R3/R5 收敛）**

  接 `docs/复盘-2026-11-06-bug与冗余.md` 的清单，用户指定「待修待决全修，冗余只做 R2/R3/R5」。

  | # | 问题 | 处置 |
  |---|---|---|
  | B3 | `--resume` / `--concurrency` 在 local/cloud 上被静默吞掉 | `--concurrency>1` **直接拒绝**（单实例只能串行，指出 RH 才支持并发）；`--resume` 明说「等价于重跑、已有产物会跳过」；`video plan` 的结尾文案按通道分开写 |
  | B4 | RH `status` 通道字段名未实测 | 解析不到状态时**抛错并打印响应实际键**（原来返回 None，被外层当「还在排队」一路轮询到超时）；收口办法记入 `docs/待修清单.md` T2 |
  | B5 | 汇率 5 份，其中 6.865 与 7.2 并存 | 新增 `stages/_rates.py`（两个用户锚点 + 派生汇率）→ `web/core/fx.py`；`ui.js` 那份副本**没有任何 import**，已删 |
  | R2 | 两个 `run_ledger.py`（216 行差 5 行） | 抽 `stages/_ledger_core.py`，两份变薄壳（re-export，调用方 import 路径不变） |
  | R3 | 花费聚合 4 套 | `inventory.spend.cny` 成为唯一聚合；`studio.time_summary` 改读它 —— 顺带修掉「同一个页面两个金额」（rows 求和 vs inventory 去重） |
  | R5 | `video.local` 与 `video.run` 重叠 | 标题加「单镜调试：」，help 写明**不过门禁、不出整集、不进平台台账**，agent 指令改为「别在这条上拼批次」 |

  **没做**（用户明确本轮不动）：R1 收敛 RunningHub 执行链（5621 行，暂缓但未废弃）、
  R4 模板抽公共段（21 份 80% 重复，属架构级改动）。

  口径决定记录：汇率以**用户给定锚点**为准（1 美元 = 2746 RH 币、1 RH 币 = ¥0.0025
  ⇒ 1 美元 = 6.865 元），`7.2` 是早期按市价随手填的近似值，与锚点不自洽，已统一。
  该汇率只用于展示折算，不参与任何计费判断。

  测试：`web/tests/test_rates.py` 4 例（常量单源 / ux 跟随 / inventory 唯一聚合 /
  **AST 扫描禁止 `× 0.0025|7.2|6.865` 的算式**）；`test_video_plan.py` 增 3 例
  （`--concurrency 4` 拒绝、`=1` 放行、`--resume` 必须解释）。回归 **566 例全绿**。

- **2026-11-06 更新（V0.7.69 · 复盘后修两条 P0：校准分支崩溃、出图默认流两套真源）**

  全量扫描 + 定向复核结果见 `docs/复盘-2026-11-06-bug与冗余.md`。本轮只动「有明确对错」的两条，
  其余（RH 轮询字段未实测、汇率 5 份、两条执行链并存…）留在复盘里排期。

  | # | 问题 | 证据 | 处置 |
  |---|---|---|---|
  | B1 | `drama video plan --save-calibration` 必然 `NameError` | 读未赋值的 `cal`；校准结果实际在 `est['_calibrate']` | 改读该字段；补「必须与 `--calibrate` 同用」的提示 |
  | B2 | 出图默认工作流两套真源，指向**不同文件** | 执行器/预置卡 = `workflow_qwen21_t2i_hq.json`；界面/预检 = `workflow_qwen_image21.json` | 界面与预检对齐到执行器那份 |

  B2 的后果与视频侧 2026-11-05 那次同类：**没有确认单的项目**，预检核的是根本不会提交的图。
  `workflow_qwen_image21.json` 因此失去代码引用，**未删**（老项目确认单里可能还记着它）。

  另修一处误导：`video.local` 的占位文案还写着早已不是默认的 `workflow_h3_local.json`；
  `--resume` / `--concurrency` 在 local/cloud 上被静默忽略（只在 RH 链生效），现已显式提示。

  测试：`test_video_plan.py`（3 例，子进程真跑，判据「退出码 0 且无 Traceback」）、
  `test_generator_workflows.py`（2 例，执行器/预检/界面/预置卡四处同名）。回归 **559 例全绿**。

- **2026-11-06 更新（V0.7.68 · 视频默认工作流按通道分：云端换 pika 极速版）**

  此前本机与云端共用同一个默认工作流。云端镜像（4090 24G）与产线模型都换成 pika 极速版之后，
  两边该用的流不一样了，于是把「默认值是哪个」从四个地方各写一遍收成一个真源。

  | 通道 | 默认工作流 | 关键差异 |
  |---|---|---|
  | 本机 ComfyUI（4060 8G） | `workflow_h3_minimax_canvas.json`（沿用） | 6 参考槽、fl2v turbo 8step |
  | 云端镜像（4090 D） | **`workflow_h3_pika_8g.json`**（新增） | pika 极速版：**2 参考槽**、lcm 采样、SigmaShift(12/2)、LoRA `pika_h3_flex_ref2va` |

  ### 一、新工作流入库

  - 源：`workflows_src/h3_pika_8g_raw.json`（界面 66 节点）→ `workflow_ui2api.py` → API 27 节点。
  - **删掉 `#200 忽略多组孤海`**：无下游引用的界面门控残留，中文 `class_type` 会让云端整份
    400 `missing_node_type`（与 2026-11-05 canvas 那次同一个坑，`test_workflow_hygiene` 已守）。
  - 新增 sidecar `workflow_h3_pika_8g.map.json`：`prompt/seconds/seed/aspect/prefix` 照常；
    `images` 只登记 **199、188** 两个槽（作者画布上另外 4 个 LoadImage 与其预缩放节点被**旁路**，
    转 API 后不执行）；`_length_node: 136` 让帧数写成 INT 字面量。
  - `steps` 登记 `147 ManualSigmas` 并标 `_steps_ineffective` —— 本流没有步数节点，
    实际步数由手写 sigmas（1.0 → 0.0，6 段）+ lcm 决定。

  ### 二、默认值收成一个真源

  新增 `stages/video/comfyui/workflow_defaults.py`，四处在读的那一个：

  | 位置 | 改动 |
  |---|---|
  | `comfy_local_video.DEFAULT_WORKFLOW` | 本机不变；**新增** `DEFAULT_WORKFLOW_CLOUD` |
  | `gen_preflight.DEFAULT_WF` | 新增 `default_workflow(kind, cloud=)`；视频按地址判通道 |
  | `web/core/generators.py` | 新增 `VIDEO_CLOUD_WF`，云端通道页不再用本机那份 |
  | `drama.py::_run_cloud_task` | 原来**写死 canvas** → 改用 `_video_wf_default(cloud=True)` |

  ### 三、两处「静默吃掉参数」的修正

  1. `apply_nodes` 的 `steps`：当 map 标了 `_steps_ineffective` 时**只告警、不写入**。
     此前会往节点里塞 `value`，而 pika 流登记的 `147 ManualSigmas` 没有这个输入 ——
     0.43.2 会以「多出未知输入」400 拒掉整张图。canvas 流因 160 是 BasicScheduler 才侥幸无害。
  2. 参考图多于槽位时**打印 WARN 点名**被丢掉的那几张。2 槽工作流配三人镜头时，
     旧行为是静默丢弃 —— 只会表现为「第三个人长得不像」，不报错。

  ### 四、上云前必须确认的两项镜像依赖

  | 依赖 | 说明 |
  |---|---|
  | LoRA `pika_h3_flex_ref2va_comfy_bf16.safetensors` | 本流新增；canvas 用的是 fl2v turbo 8step，不通用 |
  | 节点类 `LayerUtility: ImageScaleByAspectRatio V2` | 需要 ComfyUI_LayerStyle 插件；canvas 未使用 |

  两项任一缺失都会卡在提交（前者 probe 报缺模型，后者 400 missing_node_type）。
  先 `python -m cloud probe`，再 `--workflow workflow_h3_pika_8g.json --map-check`，两条都过再真跑。

  测试：新增 `test_workflow_defaults.py`（6 例：两份不同文件 / 都是 API 格式且带 map /
  执行器与预检同源 / 图像不分通道 / pika 槽数确为 2）；`test_channel_isolation` 的逐字断言
  改成语义断言（原来会因为调用串换行而无谓变红）。回归 **552 例全绿**。

- **2026-11-06 更新（V0.7.67 · 不再默认跑到 RunningHub + 清掉全部 RH 价格提示）**

  用户实测两件事，都指向同一类问题：**界面替用户做了花钱的决定，还给了一个已知会错的数字**。

  ### 一、「新建项目后什么都没选，就默认变成 RunningHub」

  三处成因，逐条堵：

  | # | 位置 | 问题 |
  |---|---|---|
  | 1 | `web/core/ux.py::VIDEO_MACHINE_OPTIONS` | 视频组**只有 RunningHub 且带 `recommend`**，本机选项根本不存在 —— 用户不点，确认单也被写成 RH |
  | 2 | `web/ui/home.js::uiDual` | 预选规则是 `recommend \|\| 第一项`，于是「第一项就是计费通道」直接变成默认值 |
  | 3 | `stages/import/preset_apply.py` | 兜底写的是 `vid.get("choice") or "runninghub"` —— 预配置卡漏一个字段就静默设成计费通道 |

  改法：视频组补回 `local_comfyui` 并设为唯一预选；**带 `paid` 的选项永不预选**，且提交前校验「两组都选了吗」；
  预配置兜底改成 `local_comfyui`。

  顺带修掉三处「点了也跑不通」：
  `ux.py` 的选项值写的是 `runninghub` / `closed_model`，而引擎的 id 是 `runninghub_workflow` / `closed_source`
  —— 这两项从来没工作过；`review_episode` 任务引用的 `report.batch` 命令早已删除；`plan_then_run` 的断言
  把「开始生成」锁死成 `PAID`，而 `video.run` 早已是「本机 GPU 出片」。

  ### 二、RH 价格提示全部移除

  | 位置 | 原文 | 现在 |
  |---|---|---|
  | `web/core/ux.py` | `COIN_PER_SHOT = 145` + `spend_for_shots()` 按镜头数算 ¥ | 删除；不再有任何按镜头数报预价的路径 |
  | `web/core/connections.py` | 「27 币/段 + 1 币/秒」 | 「按平台实际用量结算（跑完自动写台账，不做预估）」 |
  | `model_gate.py` | `cost: "约 78-209 RH币/段（按帧数）"`（会被写进确认单并显示） | 「按平台实际用量结算（跑完进台账，不做预估）」 |
  | `commands.py` | 「默认 ￥1.59/时」+ 助手指令「按 ￥1.59/时 报预计费用」 | 去掉单价；助手指令改为「不要给单价或预估金额」 |
  | `views/assets.js` | 「默认 ￥1.59/时」 | 「按实例开机时长结算（以云平台账单为准）」 |
  | `views/pipeline.js` | 「预计花费 X / 预算 Y 点」 | 「预算闸门 X / Y 点（估算，只用来拦截，不作费用参考）」 |
  | `configs/model-plan.example.json` | 示例 video 通道 = runninghub + 那条价格 | 改为 local_comfyui；示例本身就是很多项目的复制源 |

  统一口径：**只报「按平台实际用量结算」，具体数字跑完按台账实测报**（`cost_model.observed()`）。

  ### 三、测试

  修掉一个**静默失效的测试套件**：`web/tests/test_ux.py` 的 `check()` 只打印不抛出，
  `python test_ux.py` 会红，而 `pytest` 一直把它当绿的 —— 上面几条就是这样挂着没被发现。
  现已加 `test_no_failures`（末尾统一断言）让 pytest 也能看见。

  新增守卫：
  - `test_ux.py`：机器选项的 value 必须是引擎 id、**不得有必填依据**、`paid` 不得 `recommend`、
    两组都必须有本机选项；用户文案不得出现单价或预估金额（正则）；
  - `test_preset_apply.py`（新文件，3 例）：每份预配置卡必须显式声明两类通道且 id 合法、
    兜底必须是 `local_comfyui`、本机通道必须零依据且有执行器；
  - `test_model_gate.py`：`MODEL_OPTIONS` 的 cost/label/desc 不允许出现单价。

  回归 **546 例全绿**（cloud 49 / import 53 / subtitle 47 / comfyui 42 / tools 6 / web 140 /
  production 110 / assets 19 / gen_boards 17 / model_gate 63）。

  ⚠ 已存在的项目若被这套默认值写过 `model-plan.json`（`video.choice=runninghub`），需要显式改回：
  `drama models set video=local_comfyui`（或 `cloud_comfyui` + 地址）。`drama models status` 可查当前选择。

- **2026-11-06 更新（V0.7.66 · H3 把台词烧成画面字幕：写法问题，不是工作流问题）**

  实跑发现：成片在**有人开口的时间段**底部出现白字黑边字幕，文本与剧本逐字一致；
  同一镜的闭口段没有。加「不生成任何字幕、文字、水印」、换 steps、找节点开关，**全都无效**
  （BasicGuider 等价 cfg=1，负向不参与引导）。

  根因：**台词裸写在引号里 → H3 把它当成「画面中应出现的文字」**。正确写法是
  `<d>[Chinese] 原句。</d>` —— 语音事件标记，驱动口型与配音，不落到画面。
  同实例三组对照（固定 seed 123456）：A 基线有字幕、B 官方六段式无、C 只换 `<d>` 无 ⇒
  **关键变量是标记本身，不是六段式结构**。

  影响面与处置：

  | 层 | 位置 | 改动 |
  |---|---|---|
  | 模板（21 份） | `stages/creation/skills/*/SKILL.md` | 约束行 / 台词说明段 / B段示例 共 5 类写法统一改成 `<d>`；示例里的引号台词逐句包标记 |
  | 提示 | `prompts/skill_director.md`、`convert_to_pack.md` | 明写「只许 `<d>` 写法」+ 反例；通道 C 的 6.5 条豁免「逐字保留」 |
  | 转换 | `stages/import/md2pack.py` | 转换时**自动补标记**（幂等），并逐镜记进 `_import_report.md` |
  | 判据 | **新增** `stages/import/prompt_marks.py` | 三处（转换/门禁/迁移）共用一份正则；`normalize_dialogue` / `find_bare` |
  | 门禁 | `stages/import/pack_spec.py` | `SHOT018` **告警不阻断**（标记不是硬约束，且拦下来会让能跑的项目导不进） |
  | 契约 | `docs/pack/PACK-SPEC.md` §5.3、`MD-TEMPLATE.md` | 写进规范；三条交付通道都指向同一判据 |
  | 老项目 | `python stages/import/prompt_marks.py --workspace <剧目录> --apply` | 重写 `h3_prompts.json`，先落 `.bak-时间戳`；**已烧字幕的成片只能重跑** |

  设计取舍两条：① 只自动包「有说话动词」和「口型对齐台词」两种高置信写法 ——
  招牌/标语里的引号中文（`招牌写着："营业中"`）**不包**，把它改成台词是另一种错，只告警；
  ② 归一化**只动 `board_prompt` / `video_prompt`**，`dialogue[].text` 保持纯文本 ——
  套标记会让字幕里出现 `<d>[Chinese]`。

  顺带修掉两处静默错误：

  | # | 位置 | 症状 |
  |---|---|---|
  | 1 | `stages/production/scripts/gen_boards.py` | 分镜图提示词写死 `vertical 9:16`，横屏项目的分镜图仍是竖构图，出片被裁且**不报错** → 改为跟 `ratio` 走 |
  | 2 | 同上 `_codes()` | 没有 `character-bible.json` 时裸代号 `P01` 不算角色 → 人数算成 0 兜底成 1，双人镜被写成 `exactly one person` |
  | 3 | `stages/import/md2pack.py` | 写死 `character/scene=16:9` 并**盖掉** `pack_spec.DEFAULT_ASPECT` 的 9:16 → 人物卡按 16:9 出图再当 9:16 参考，竖向拉伸 22%；同时 `board/video` 改为读 `drama.json` 的 `format.aspect`（新增 `--aspect`） |

  测试：`stages/import/tests/test_prompt_marks.py` 新增 12 例（幂等 / 只包高置信写法 /
  门禁告警不阻断 / 迁移带备份），`test_md2pack.py` +5 例（台词只进提示词不进 dialogue、
  语种参数、画幅三源优先级），`test_gen_boards.py` +1 例并强化 C05（画幅跟随 ratio）。
  回归 **478 例全绿**（cloud 49 / import 50 / subtitle 47 / comfyui 42 / tools 6 /
  web 138 / production 110 / assets 19 / gen_boards 17）。

  文档：施工单 `docs/patches/2026-11-06_H3台词烧字幕_patch提案.md`。

- **2026-11-05 更新（V0.7.65 · 对照 4090 镜像实测反馈加固）**

  在仙宫云 RTX 4090 D 24G + ComfyUI **0.43.2** 上跑通全链，带回 12 条坑，逐条对照改代码。
  本地是 0.42.1 —— **本机能跑不代表云端能跑**。

  | # | 坑 | 处置 |
  |---|---|---|
  | 1 | `_length_node` 声明了却被 `load_map` 白名单过滤掉 | **自己的静默 bug**：帧数按秒计算从未生效。下划线键单独成组透传 |
  | 2 | 帧数要 INT，0.43.2 拒绝 FLOAT | `frames_for()` 写字面量；两份 map 声明 `_length_node` / `_preview_node` |
  | 3 | `/object_info/<不存在>` 返回 200 → 节点检查假阳性 | 一律解析 JSON 判断 key，不看状态码 |
  | 4 | 相同 prompt+seed 命中节点缓存（2 秒「完成」，画面是上次的） | 批次 seed = 基底 + 镜序，逐镜唯一并落批次记录 |
  | 5 | 参考图比例不匹配 → 画面拉伸（3:4→9:16 纵拉 22%） | 提交前 `check_ref_ratio()` 按 5% 告警；**资产卡默认 16:9 → 9:16** |
  | 6 | SSH 高 IO 假死 / 限流 | `_scp` 只对连接类错误重试，退避 3 → 15 → 60 秒 |

  新增体检 `check_length_wiring()`：`length` 还是连线而 map 没声明时直接提示「云端会 400」。

  文档 `docs/云端ComfyUI接入.md` §8 收录全部 12 条（已修 / 环境侧 / 4090 稳态基准）。
  排期结论：**10 秒/段是效率拐点** —— 15 秒帧数只多 49%、耗时多 67%。

  测试：+25 例（`test_length_wiring` 7 / `test_ref_ratio` 9 / `test_seed_unique` 4 /
  `test_transport_retry` 5）。回归 357 + 110 全绿。

- **2026-11-05 更新（V0.7.64 · 费用只报实测 + 云端产物回传）**

  两件事：**不再展示预估价格**，以及**给云端产物一条明确的回家路**。

  ### 一、删掉 RH 预估价，改报台账实测

  起因：核对台账时发现两处「看起来对、其实错」：

  | 问题 | 事实 |
  |---|---|
  | 自校准从未生效 | `iter_ledger_records` 读 `<ws>/ledger/runs`，引擎写台账在 `<ws>/video-pipeline/ledger/runs` → 真实项目 **307 条记录、样本恒为 0** |
  | 内置参数低报 4 倍 | 内置 `27 币/任务 + 1 币/秒`；真实台账中位 **45 币/段、6.07 币/秒**（7s 段 138–146 币） |

  改法：
  - `cost_model.observed(ws)`：只报事实（中位 / 区间 / 币每秒 / 中位时长），无样本返回 `None` 而不是 0；
  - `drama video plan` 与真跑前提示：删掉「两段式预估 / GPU 秒口径 ×0.205 / 参数来源 / 自校准」四行，
    改为「实测参考 + 本批约 + 数据来源」；
  - 界面价签：RH → 「按平台 usage 结算」；云端 → 「按云主机时长结算」（不再写死 ￥1.59/时）；
  - 删死常量 `CNY_PER_RH` / `CHAR_RH_PER_IMAGE`；给助手的指令改成「报实测参考，不准编单价」。

  ★ 预估**没有删**：它仍留在 `estimate_video()` 里供预算闸门用，只是不再出现在「我要花多少钱」的位置。

  ### 二、云端产物回传（`cloud pull`）

  ComfyUI 的产物在实例的 `ComfyUI/output/`，只能靠 `GET /view` 取回；`/history` 是**内存态**，
  实例重启即清空，非 retain 实例销毁连磁盘一起没 —— 所以回传是**一次性时间窗**。

  | 路径 | 说明 |
  |---|---|
  | 自动（主） | 每镜跑完立即下载，写 `.part` 再改名，Range 续传 |
  | 自动（兜底） | `--engine cloud` 在**退出 lease、停机之前**再扫一次 `/history` 补缺口 |
  | 手动 | `python -m cloud pull --workspace <ws> --ep ep01 [--file <名>] [--out <目录>] [--dry-run]` |

  归位规则：文件名带 `shot_NNN` 且本地已有该镜目录 → `shot_NNN/final.mp4`；否则进 `_cloud_pull/`，
  **不替用户新建目录结构**。每次回传写 `_cloud_pull/pull-<ts>.json`（prompt → 文件 → 大小 → 失败原因）。
  幂等：已存在且非空即跳过，`--force` 才覆盖。

  测试：`cloud/tests/test_pull.py` 8 例（真走 HTTP）+ `test_cost_observed.py` 7 例（含文案回归防线）。

- **2026-11-05 复盘（文档，非版本）· 全项目工作流程 + 检查分析**

  目录 `docs/复盘-2026-11-05/`：

  | 文件 | 内容 |
  |---|---|
  | `工作流程报告.md` | 四层结构、主链路 21 步逐个输入/产物/卡点、通道决策、门禁体系、五道一致性锁、文件级数据流、时间账 |
  | `检查分析报告.md` | 量化画像、7 项优势（带证据）、7 项劣势（P0/P1/P2）、三维度前沿对照、风险登记、三档演进建议 |
  | `index.html` | 可视化总览，内联 SVG 三图（主链路 / 通道决策 / 三维评分），离线可看 |

  核实数字：Python 183 文件 61,549 行；测试 427 例；命令 48；画布节点 18。
  结论：综合 6.2/10；差距排序 **生成能力 5.0 > 调度 5.5 > 成本 8.0**；
  **P0 缺口 = 无对白配音（全仓无 TTS）**；瓶颈在 GPU（8G 显存 → int4 + 4step），不在架构。

- **2026-11-05 更新（V0.7.63 · 分批续写 + 4–5 镜/批 + variant kind + md2pack 转换器）**

  上一版实测留下的四个缺口，这一版落地三个半：

  | 能力 | 做法 |
  |---|---|
  | **续写** | `creation.write(append=True)`（分隔线 + 备份）；`vars_for` 注入 `prior` / `batch_no` / `shot_from` / `ep_from`；界面每个分批环节多一个「继续写第 N 批」 |
  | **4–5 镜/批** | `skill_director.md` 重写「每批 4–5 镜 + 只写这一批 + 批次号用输入值 + A/B 段逐字标签」；`shots_per_batch` 可调 |
  | **variant kind** | `base / turnaround / look / expression / state`；缺省按 code/label 推断；出图顺序按「三视图 → 造型 → 表情」 |
  | **转换器** | `stages/import/md2pack.py` + 命令 `convert.apply`：资产库/导演手册 → pack，含名字→代号、缺口报告、严格/宽松 cast 策略 |

  实测（真调 DeepSeek）：同一集连写两批 → 镜 1–10 无重复、10/10 有 A/B 段、无截断；
  转换这份手册 → ep01(10 镜) 并通过 `pack_import --apply`。

  顺手修掉两个「被当成产物」的 bug：`creation.state/read` 与 `md2pack` 的 `*.md` 收集
  会把 `.bak_时间戳.md` 当成另一集/另一批（字数翻倍、批次号乱、prior 里两份内容）。

  回归：Studio+导入 171 / 生产 103 / 其余 153 全绿。

- **2026-11-05 更新（V0.7.62 · Skill → 下游兼容性实测）**

  用两个模板（宅斗 `zhaidou-manju` / 甜宠 `tianchong-manju`）真跑「企划案 → 资产库 → 剧本 →
  导演手册」，再机械抽成 pack 走下三环。报告：`docs/Skill接入与下游兼容性.md`。

  | 环节 | 结果 |
  |---|---|
  | Skill 生效 | ✅ 特征词 4/4、3/3；小节结构与模板一致 |
  | 资产识别 | ⚠ 宅斗 25 条目仅 6 条带提示词；甜宠 6/6 |
  | 导入校验 | ✅ 严格（缺集 / 缺资产引用 / 缺 video_prompt 全阻断） |
  | 出图 | ✅ P01 1682KB / 31s |
  | 分镜识别 | ⚠ 7 镜中 6 镜两段齐全（末镜被截断） |
  | 出片 | ✅ 9.42s / 226 帧 / 2.4MB |

  修三处：**截断不可见**（gateway 透出 `finish_reason`，生成接口给警告）、
  **预检不认裸文件名工作流**、**镜头级 ratio 从未生效**（竖屏出横屏；现按 `object_info`
  实际枚举下传，实测 480×864）。

  四个硬缺口留给决策：分批模板 vs 单文件覆盖、8 镜超 8k 输出上限、三视图/表情卡无 schema 位置、
  台词需 name→id 映射。回归：生产 103 / 其余 92 / Studio 132。

- **2026-11-05 更新（V0.7.61 · 本地实跑复核：五处「看起来正常」的错）**

  用本机 4060 真跑了一轮（出图 / 出片 / WebUI 作业 / Skill 装载），把「说一套跑一套」的地方
  逐个改掉。全部免费（￥0），数据见 `docs/生成能力与预检.md` §1.1。

  | # | 问题 | 后果 |
  |---|---|---|
  | 1 | 预检不认 `--workflow` | 替代工作流被默认版缺件拦死 —— 提示了却走不通 |
  | 2 | 干跑不透传 `--workflow` | 计划显示 canvas、真跑 h3_local（反方向的「核 A 跑 B」） |
  | 3 | 相对文件名按 CWD 解析 | `workflow_h3_local.json` 报「不存在」，映射静默退回内置 |
  | 4 | 资产清单整份覆盖 | `--only D01` 把 24 条台账打成 1 条（工具自己就这么建议） |
  | 5 | 错误翻译张冠李戴 | 缺 LoRA 被说成「画图工具连不上」，人跑去重启服务 |

  顺带：界面 `video.run` 补 `--workflow`；体检项「ComfyUI 远端地址」补映射别名。

  **实测数据**：出图 31.9s / 1440×1440；出片单镜 4s→160s、1056×608 / 24fps / 含音轨；
  批量 1 镜 157s；预检判据与真实缺件一致。回归：生产 103 / 其余 181 / Studio 132。

- **2026-11-05 更新（V0.7.60 · WebUI 同步：云端通道从「看得见」到「点得动」）**

  引擎侧 V0.7.57–59 把云端能力铺完了，但 Studio 只更新了**通道页**（能显示），
  命令层完全没跟 —— 界面说「云端可用」，却没有任何按钮能跑它。七处补齐：

  | 缺口 | 修法 |
  |---|---|
  | 没有云端命令 | 新增 `assets.cloud` / `video.cloud` / `preflight.gen` |
  | 通道页云端行的命令列指向本地命令 | 改指 `assets.cloud` / `video.cloud` |
  | 流水线资产环节写死本地 | 按模型确认单切（云端→`assets.cloud`，且计费标 paid） |
  | 画布节点运行按钮写死本地 | 同一条口径（`graph._cmd_for`） |
  | 出图抽屉只有本地/RH | 加「云端镜像（★按主机时长）」，与 RH 的「按张」分开写 |
  | 通道页看不出实际打哪台 | 新增「实际地址 + 来源」列 |
  | 8188 被当硬前提（体检/文案/修复按钮） | `env_check` 按实际地址探测；云端时改「去连接中心」 |

  `generators.plan_choice()` 提为公开函数：流水线、画布、通道页三处**共用一份**
  「读模型确认单」的逻辑。不一致的根源从来不是缺功能，而是同一件事被读了三次。

  新增 `web/tests/test_cloud_wiring.py`（11 例，含「本地确认时不许被误切云端」）。
  回归：Studio 132 / 生产 100 / 其余 181 全绿。

- **2026-11-05 更新（V0.7.59 · ComfyUI 调用一致性审计 + 通道隔离）**

  把「谁在什么地址、用哪份工作流、按谁的映射调 ComfyUI」逐环节对了一遍。
  12 个调用点里找出 6 处不一致，全部是**能跑但跑错机器/跑错工作流**那一类：

  | # | 问题 | 后果 |
  |---|---|---|
  | 1 | 图像云端通道无入口 | `image=cloud_comfyui` 能确认、不能执行（视频侧早有） |
  | 2 | 图像地址 `setdefault` 注入 | 被残留的云端地址污染 → 图像静默打到云端 |
  | 3 | 视频本机路径不显式传地址 | 长驻进程里「本机出片」跑到云端 |
  | 4 | 视频确认单 `comfy_workflow` 不生效 | 确认 A 跑 B |
  | 5 | 文档写了 `--workflow` 但 CLI 没有 | 照抄文档报错 |
  | 6 | 能力卡写死 8188 | 改端口/上云后一直报不可达 |

  **隔离方案（生图本地 + 视频云端）现在成立**：依据按「类」解析（`gen_preflight.resolve`），
  不再靠全局环境变量在环节间传话；新增 `test_channel_isolation.py` 6 例钉住，其中有
  「env 已被云端污染，图像仍回本地」这一条。另加防错：`engine=cloud` 但地址是本机 → 判「待配置」。

  回归：生产 100 / 其余 181 / Studio 121 全绿。审计矩阵见 `docs/ComfyUI调用一致性审计.md`。

- **2026-11-05 更新（V0.7.58 · 生成能力预检：批量开跑前先证明「能出」）**

  三条通道（本地 ComfyUI / RunningHub / 云端镜像）× 两个阶段（图像 / 视频），此前只有
  **散的**检查：`assets --check` 要人记得跑、`comfy_batch_video --submit` 什么都不查、
  `preflight` 只看 RH。缺一个模型的代价不是失败一次，而是**每镜各失败一次**。

  | 项 | 结果 |
  |---|---|
  | 新增 | `stages/production/scripts/gen_preflight.py`：守卫/在线/版本/节点/模型/必需输入，判据复用 `cloud/health` |
  | 接入 | 出片批量（`--check` + 真跑前自动）、出图批量（同上）、`drama preflight --only gen` |
  | 兜底 | 缺模型时自动扫同目录工作流，给出「本机就能跑的那份」（替代工作流提示） |
  | 通道页 | 新增云端两行（确认了才出现）+ 视频工作流与执行器同源 + 应用 `_substitute` |

  修掉 8 处**口径错误**（都不是跑不动，而是说错）：图像工作流被视频映射误判为缺件、
  通道页核 A 跑 B、不应用模型替换、i2i 被写成「未内置」、批量零预检、preflight 只看 RH。

  实测（4060 8G / 项目 `UNTIL-DECEMBER`）：图像·本地可用；视频·本地缺 8step LoRA，
  已给出替代工作流；云端待部署。详见 `docs/生成能力与预检.md`。

  回归：生产 94 / 其余 181 / Studio 121 / 通道页 7 段 / `model_gate` 36 全绿。

- **2026-11-05 更新（V0.7.57 · 出片侧接上云端 ComfyUI 镜像，补掉唯一的执行器缺口）**

  `model_gate` 里 `video=cloud_comfyui` 一直是 `executor: None`，注释写着「引擎暂无远程
  ComfyUI 视频执行器」—— 所以「支持云」只是菜单上的一行字，门禁根本走不到执行。
  这次补齐，且**不新增第二条代码路径**：`--engine cloud` 与 `local` 同分支、同客户端，
  差别只有超时档位、提交前 `/free`、产物续传三处。

  | 项 | 结果 |
  |---|---|
  | 执行器 | 视频云端填 `executor` + `engine_arg=cloud`；`requires` 只留 `comfy_url`（工作流随仓库交付）|
  | 守卫 | 新增「受信远端」窄口子（`SOLODRAMA_TRUSTED_HOSTS`），插在私网之后、粗开关之前 |
  | 超时 | `_default_timeout_min()`：远端 30 / 本地 20（本地保持实测原值，5–10 分钟/镜）|
  | 续传 | `download(resume=True)`：206 追加 / 200 截断重写 / 416 收尾 |
  | 编排层 | 新增 `cloud/`：`config` / `health` / `provisioner` / `transport` / `ledger` / `cli` |
  | 配置 | `settings.json` 增 `comfyui.mode/ssh/trusted_hosts/timeout` + `cloud`（环境变量优先）|

  **文档里的「本地 3.0 分钟」没有照抄**：本机实测单镜 5–10 分钟（`docs/orchestration/
  标准作业流程.md`），压到 3 分钟会让长镜判超时 —— 那是拿新功能换旧回归。

  四条云端硬约束都有测试：幂等（`list` 没配就拒绝创建，不盲建）、失败必停
  （`wait_ready` 超时自动 `stop`）、凭证不落盘（台账与状态文件扫不到 Token）、
  成本护栏（当日超 `max_hours_per_day` 直接拒绝、且在建之前生效）。

  上游信息分三块，只有一块还缺：
  - **字段名已校准**（读官方 API Playground「获取实例列表」）：实例是**扁平**结构，
    `web_url`（不是 http_url）、`ssh_domain`、`ssh_port`（**字符串**）、`status`、
    `price_per_hour`、`retain` / `retain_price`。`field_map` 因此改成**候选路径列表**
    （`["data.id","id"]`），网关包不包 `data` 都能取到。
  - **信封已识别**：`{code, msg, success}` —— 缺令牌是 `1000 未找到访问令牌`。
    `success=false` 现在直接抛错，不再退化成「取不到实例 ID」这种误导性报错。
  - **端点路径仍缺**（需登录后的 Playground 目录）：留空时 `up` 明确报「待配置」，
    `attach`（接管手动启动的实例）今天就能用。
  - 单价按用户给定 **￥1.59/时** 作兜底；有上游实例价时以实例价为准（不同卡型不同价）。
    顺带补一个真实成本陷阱：`retain`（关机保留磁盘）**仍按 `retain_price` 计费**，
    `stop()` 现在会告警并写进台账备注 —— 「停了就不花钱」是错的。
  **任务级启停**（用户追加要求）：`--engine cloud` 默认 `--cloud-lifecycle auto` ——
  要跑才开（复用 → 借 → 开机 → 新建）、跑完就关，且**只关自己开的**（`owned`）；
  失败与 Ctrl-C 同样停机。新增 `cloud/session.py`（`Lease`）与 `python -m cloud reap`
  （空闲 15 分钟回收，忘停的兜底）。干跑不建实例、门禁在建实例之前。
  测试用本地假上游真跑 HTTP 全链路（`cloud/tests/`，36 例，其中 `test_session.py` 10 例）。
  进度与待办：`docs/云端接入进度.md`（连续对话以该文件为准）。

  回归：生产 85 / 导入 28 / 字幕 47 / 视频 14 / 引擎 42 / 工具 6 / Studio 121 / 云端 36，
  全绿；`test_model_gate.py` 脚本自测 36/36。

- **2026-11-04 更新（V0.7.56 · 平台通道作为可选能力接回，默认仍是本地）**

  上午把 RunningHub 整体删掉了（"代码里不存在"）。下午的判断变了：删掉一条能跑的
  通道，代价比留着它大 —— 本机 8G 显存在 H3 上撞到硬墙，而云端是唯一能出片的路。
  所以接回来，但**不做默认**。

  | 项 | 结果 |
  |---|---|
  | 恢复 | 37 个文件：RH 出片引擎、云端出图、能力卡、站点真源、成本模型 |
  | 守卫 | 从「永久禁止」改成「默认关闭、显式开闸」，两种粒度（进程级 / 上下文） |
  | 默认 | `init --video-engine` 改回 `local_comfyui`；`--engine` 默认 `local` |
  | 界面 | 连接中心三卡；资产出图两项；用时页新增「平台花费」（有花费才出现） |
  | 命令 | +5 条（`video.rh` 系列 / `assets.rh_wf` / `diag.rhdoctor`），本地一条没动 |

  **「默认不出网」靠的是代码路径，不是配置。** `cmd_video_run` 里本地分支在开闸
  之前 return，所以本地通道根本走不到那一行 —— 改 `model-plan.json` 也绕不过去。
  测试 `test_local_branch_returns_before_gate` 钉住的是这个顺序，不是能力。

  三个顺带修掉的 bug，都是这次改动才暴露：
  1. `cost.js` 的注释块在第 2 行就闭合了，后面 4 行是裸文本 —— 这个页面从来没加载过。
  2. 守卫把平台判定写在本地白名单之后，`runninghub-proxy.internal` 被 `.internal`
     当内网放行。顺序反过来就等于留了一条旁路。
  3. `_boot_netguard` 用 `install() or module` 取值，首次安装时返回 `True`。

  一个数字值得记：这个项目台账里有 **13780 RH 币（¥34.45）** 的历史消耗。
  之前那个写着「平台费用恒为 0」的页面不只是不准确，它把一个真实发生过的支出
  显示成了零。

- **2026-11-04 更新（V0.7.55 · 顶栏资源监视：显存 / 内存 / 磁盘）**

  出片前最常问的一句是「现在能不能压活」。答案不在任何一页里，而在三个数字上：
  显存够不够、内存见没见底、D 盘还有多少。现在它们常驻顶栏，点开是详情 + 2 分钟曲线。

  | 项 | 来源 | 为什么 |
  |---|---|---|
  | 显存 | `nvidia-smi` | 随驱动安装，**不为它引入 psutil**（这个项目一个第三方依赖都没加） |
  | 内存 | `GlobalMemoryStatusEx`（ctypes）/ `/proc/meminfo` | 同上 |
  | 磁盘 | `shutil.disk_usage` | 取**工作区所在盘**，不是 C: —— 成片落 D: |

  四条口径：**GiB**（/1024³，和资源管理器对得上）；**同盘去重**；**内存阈值比显卡宽松**
  （85/94 对 75/90，Windows 本来就爱把内存用满，同阈值只会训练人无视黄条）；
  **取不到就降级**（没有 nvidia-smi 时只有显存段显示「—」，顶栏不会挂）。

  轮询 3 秒、页面隐藏暂停、失败不 toast（背景信息抖一下就弹窗比不显示更烦），
  服务端按 ws 缓存 1.2 秒（多标签页不该各自 fork 一次 nvidia-smi）。

  两个坑写进 `web/STUDIO.md` §22.4：SVG 曲线描边**两次**不生效（属性里的 `var()` 无效，
  `style.stroke` 里的 `var()` 被静默丢弃，只有 class + 样式表可行）；
  显存那行的字段名写错成 `data-gpu-num`，条和百分比都对、只有数字永远是「—」。

  新增 `web/tests/test_monitor.py`（8 项：单位/去重/缓存/无卡降级）；web 108 全绿。

- **2026-11-04 更新（V0.7.54 · 助手改浮窗：拖、缩、贴边，边看边问）**

  助手原来是整页。整页的问题不是「不好看」，而是**用一次就得多切一次页**：
  问「第 3 镜为什么没出片」，眼睛正看着分镜页；切成助手页，上下文没了；
  切回去，浮到哪儿也忘了。而且整页每次 `render` 都重建 DOM —— 没发出去的草稿直接消失。

  现在它是一个窗口（`js/float.js` + `js/agent-panel.js`）：

  | 能力 | 做法 |
  |---|---|
  | 打开/收起 | 点左侧「助手」就地开/关，**不切页**（`#/agent` 保留为落地页） |
  | 移动 | 拖标题栏；双击 = 铺满 / 还原 |
  | 改大小 | 八向边缘与四角，最小 360×320 |
  | 最大化 | 对齐内容区矩形，不盖左侧导航 |
  | 关闭 | 只 `display:none` —— 草稿、滚动位置、对话都还在 |
  | 记忆 | 位置尺寸存 `localStorage`，但每次打开重新夹进视口 |
  | 恢复 | 上次是开着的就还开着；`?agent=1` 强制打开（分享组合视图用） |

  两条经得起复盘的细节：

  1. **越界必须留「抓手」**。拖动最多把窗口推出到只剩 132px 标题栏 ——
     否则一次误拖就再也拖不回来，只能清 localStorage。
  2. **换项目要清空对话**。带着上一部的上下文问新项目，模型会用旧事实回答新问题，
     比「不回答」更糟。`syncAgent()` 在每次页面渲染后检查工作区并重置。

  拖动/缩放用合成 PointerEvent 实测过七种情形（拖到上边界、右下角放到极限、
  缩到最小、左边缘缩放右边界不动、最大化与还原、拖出 3000px、关闭重开保尺寸），
  结果全部符合预期；探针文件已删除，不留测试垃圾。

- **2026-11-04 更新（V0.7.53 · 会动手的助手 + 打通大模型/ComfyUI 的真实生成 + 模板改单选）**

  用户的判断是对的：「现在好像还无法真正接入本地 ComfyUI 和大模型 API」——
  实测确实有硬故障，而且不是网络问题。

  | 问题 | 根因 | 处置 |
  |---|---|---|
  | 生成企划案/剧本一律失败，`content=""` | `gateway` 按「提供商有 json 能力」就开 `response_format=json_object`，长文用途也被塞进去 | 判据改为**看模板输出类型**（`want_json_mode`），长文一律不开 |
  | 偶发「模型没反应」 | 混合推理模型的**思考计入 max_tokens**，8000 全被思考吃掉 | 提供商支持 `thinking: disabled`；四个创作用途改绑 `deepseek-chat`（非推理） |
  | 创作用途其实绑在 mock 上 | 历史演练残留（`create.plan → mock / mock-episode`） | 重新绑定到 deepseek，`max_tokens=8000` |
  | ComfyUI 显示「未接通」 | 启动要 45–90 秒，期间探测返回 unreachable 并被缓存 | 启动后自动复探（已在线：0.42.1 / RTX 4060） |

  **实测证据**：本地出一张分镜图 1088×1920（真出图，不是占位）；企划案 22 秒写出 5110 字；
  助手一轮里跑完 `state → generate(plan)` 并把 3290 字落进 `00-创作/01-企划案.md`。

  **新增「助手」`#/agent`**：对话 → 工具 → 引擎。工具白名单 12 个，没有 shell、
  没有 06-提示词 契约写入口；占 GPU 的命令必须人打开开关才提交；每轮只回一个 JSON，
  一次一动作，右侧摊开每一步。`agent.run(ws, messages) → {steps, reply}` 是纯函数，
  任何前端都能接（包括 DSH 风格的壳）。

  **创作模板改单选**：`skills.install(exclusive=True)` —— 装新的会替换旧的并删掉旧文件；
  `install_many` 只取第一个，其余在结果里标明被忽略。新建项目弹窗改 radio。

  新增 `web/tests/test_agent.py`（解析与闸门）、`web/tests/test_llm_modes.py`（json_mode 判据）；
  web 100 全绿。
- **2026-11-04 更新（V0.7.52 · 节点画布 + 导航重排 + 模板预配置 + 一键下载/更新）**
  这一轮全部来自用户对工作台的直接反馈（原话：「画布是指可以连线操作的那种模式」
  「工作台和项目管理两个可以合并」「ai模型中心、连接中心、环境体检合并到一个模块」）。

  | 件 | 内容 |
  |---|---|
  | 节点画布 `#/graph` | 可拖 / 滚轮缩放 / 从右圆点拖到左圆点连线；18 节点（创作 6 + 引擎 13，分镜图独立）；位置与视口落 `<ws>/canvas.json` |
  | `web/core/graph.py` | 一张图两种模式；**实线=引擎依赖（锁定不可删）**、虚线=编排意图（不改执行顺序）；状态只认磁盘，门禁另标琥珀点 |
  | `GET /api/graph` · `POST /api/graph/{layout,edge,reset}` | 只读聚合 + 布局/连线写盘；删依赖边返回 `locked` 并说明原因 |
  | 导航重排 | 工作台 = 原「工作台 + 项目管理」；系统中心 = 原「模型/连接/体检」三页签；用时（时间中心）移进项目；项目内按创作顺序：项目详情 · 画布 · 创作 · 创作模板 · 资产 · 分镜 · 视频 · 剪辑 · 发行 · 用时 |
  | 全局时间 | `GET /api/time/global`（只扫台账，不起子进程）；工作台首屏显示总 GPU 时长 / 按项目 / 按环节 |
  | 分镜页 `#/boards` | 每镜一张 9:16 首帧的缩略墙 + 缺图清单 + 一键出分镜图；分镜图在画布上是独立节点 |
  | 创作模板 | 21 份题材模板**内置进仓库**（`stages/creation/skills/`）；新建项目时多选装载（≤6 份）；支持上传自己的 SKILL.md（落 `web/var/skills-user/`） |
  | 一键下载 / 一键更新 | `web/core/updater.py`：前者把「可自动修」的体检项全跑一遍并逐项复检；后者 `git pull --ff-only` → pip → 复检。都走线程池，不掐死单进程 uvicorn |

  **顺带修（都是会 500 的硬故障）**：
  - `project_create` 引用的 `project.scaffold` 命令在本分支**根本不存在** ⇒ 点「新建项目」100% 500。
    现在指向 `init_project.py`，它调的仍是布局真源 `_layout.scaffold()`；
  - 同一处的 `CMD.SCRIPTS["setup"]` / `drama style set` 也早已随创作层删除 ⇒ 改为
    **建档时一次写入** track/look/aspect/resolution（`init_project --track/--look/--aspect/--resolution`），
    结果一律回读 `drama.json` / `project-setup.json` 验真，不看退出码；
  - `nodes.py --json` 增加 `reads / output / ep` 字段：画布不再抄一份依赖表（抄一份必漂）。

  新增 `web/tests/test_graph.py`（4 组 31 项）与 `web/tests/test_skill_library.py`（4 组 17 项）；
  web 91 + 引擎 148 全绿。
- **2026-11-04 更新（V0.7.51 · 剧集画布 P1：一屏看完 30 集做到哪一镜）**
  「30 集做到哪了」此前要翻四个目录（`06-提示词` 的镜数 / `04-资产/boards` 的分镜图 /
  `07-成片` 的段文件 / `09-发行` 的发布版）。现在压成一屏：横向镜号、纵向集号、一格一镜。

  | 件 | 内容 |
  |---|---|
  | `web/core/canvas.py` | 只读聚合：段索引只走一遍 `<out>`（深度 3）、分镜图每集 `scandir` 一次；30 集整页 < 60ms |
  | `GET /api/canvas/series` | 格子表 + 列缺口 + 合计；集号轴按目标集数补齐 |
  | `GET /api/canvas/shot` | 单镜四段链（参考图 / 提示词 / 时长画幅 / 成片），坏参数一律 `ok:false`，不 500 |
  | `#/canvas` | 双向吸顶表格、缺口行常驻表头下、筛选（全部/有缺口/已完成）、隐藏无制作包集、格子→抽屉 |

  三条口径钉死在 `web/STUDIO.md` §16：**状态只认磁盘不认台账**、**镜序只认 `shots.json`**
  （缺则退化列举并标 `no_pack`）、**集号轴按目标集数补齐**。新增 `web/tests/test_canvas.py`（31 项）。

  **顺带修（不修就会误判「改了没生效」）**：Starlette `StaticFiles` 不发 `Cache-Control`，
  Chrome 按「(现在 − Last-Modified) 的 10%」启发式缓存 ⇒ 改完 css/js 刷新看到的还是旧文件
  （画布样式写完，页面上一个格子都没有，排查半小时）。现由 `_FreshStatic` 统一发 `no-cache`
  （ETag 命中仍是 304），`index.html` 的三个资源引用加 `?v=` 日期串。
  另：抽屉加 `overflow:hidden` + 正文 `min-height:0`，长内容只滚正文，标题栏与按钮不动。
- **2026-11-02 更新（V0.7.50 · 收口 D2：参考图缩放只有一处实现）**
  `prepare_refs.py` 与 `wire_new_assets.py` 各写了一遍「等比缩放 + 转码」，
  连常量都靠注释互相抄（`# 与 prepare_refs.py 的 DEFAULT_MAX_EDGE 一致`）—— 改一边就漂。
  现在抽成 `prepare_refs.thin_one()`，`wire_new_assets` 的两个常量直接取
  `DEFAULT_MAX_EDGE` / `DEFAULT_QUALITY`，自带的 `thin()` 删除。
  行为不变：同一张 6000×300 仍产出 2048×102、省 58.2%、原图不动。
  新增 `tests/test_thin_one.py`（16 例，含「缩放只此一处实现」的防回归断言）；
  引擎层 31 + Studio 21 全绿。
  至此 `docs/reform/2026-11-01_重复项复核.md` 的 D1–D13 全部结案（D6/D7 为复核后不改）。
- **2026-11-01 更新（V0.7.49 · 导出发布版 / 参考图瘦身 / 分镜续跑 接成真功能）**
  这三件事原来在页面上都只写着「未开放 / 用命令行」。现在都能在界面里点，且带确认单。

  | 功能 | 改动 |
  |---|---|
  | 导出发布版 | 新增 `release.export` 命令 + 只读预览接口 `/api/studio/release/export-preview`；发行页显示「可导出几集 / 被哪些门禁拦 / 看全部原因」，导出走确认单（写几个、覆盖同名、可硬链接） |
  | 参考图瘦身 | 修 `drama refs` 不传 `--workspace`（功能此前对任何项目都报「找不到工作区 data/」）；资产页加「瘦身参考图…」弹窗（只体检 / 写盘 + 改 characters.json 两个开关） |
  | 分镜续跑 | 弹窗改成真动作：勾确认 → `video.resume`（`--only` 用磁盘原始段名 `shot_001`，不是展示用的 `ep01_shot_001`） |

  **真跑验证**：导出（合成 1080×1920/SAR 1:1）→ `09-发行/剧集/Episode01.mp4` 71,987 B +
  剧集清单.json；瘦身（6000px）→ `refs_h3/char_big_00.jpg` 2048×102、省 58.2%、原图不动。

  **顺带修**：
  - `release_export.py` 判「烧过字幕的成片」用了 `\b`，`ep01_subbed_1080p` 因 `subbed_`
    命中不了 ⇒ 4 条误报「不是烧过字幕的成片」；
  - 分镜页顶部「成功/失败/未跑」读 `totals.success/failed/pending`，引擎写的是
    `{total, ok, fail}` ⇒ 恒为 0（筛选条却是对的）。

  **真实项目现状**：4 集成片 `SAR=59:60`，导出被门禁拦下（门禁是对的）。页面现在直接列出
  原因，并指向「重跑③字幕（那步会 crop-to-fill 归一化）」这条修复路径。

  **待修**：成本中心看不到 LLM 花费 → `docs/待修清单.md` T1（含两条候选路线与验收标准）。

  新增 `web/tests/test_new_actions.py`（3 个新动作的 danger/billing/argv 契约）；
  Studio 21 + 引擎层 30 测试全绿；manifest 同步。
- **2026-11-01 更新（V0.7.48 · 连接中心站点口径：测的站点 ≠ 花钱的站点）**
  第三轮按页面继续验写路径（连接中心 / AI 模型中心 / 环境体检 / 任务中心），
  两页三条路径正确，**一条错得严重**。

  **核心问题：RunningHub 站点三处不一致**
  | | 值 |
  |---|---|
  | 界面保存的（`connections.json`） | `runninghub.ai` |
  | 引擎实际用的（`configs/channels.json`） | `runninghub.cn` |
  | 测试连接原来打 | `.ai` |
  | 出片实际打 | `.cn` |
  | 两个站余额 | **13687 vs 32689 RH币（两套账户）** |

  原来「测试连接」显示已连接 + 13687，花的却是另一个站的钱。根因：连接中心注
  `RUNNINGHUB_BASE_URL`，而引擎从 2026-10-29 起不读它了（真源 `_site.project_site`）。
  修法：`_engine_site()` 问真源 → `_test_runninghub()` 改测 effective 并回传
  `site{used,source,stored,stored_ignored}` → `overview()` 只对 runninghub 暴露
  `effective` → 页面把「引擎实际使用」直接印出来，选择器降级为「兜底值」。

  **其余**：保存连接语义（空串=清除/不传=保持）正确；模型自检与浅测都免费且
  明说「未产生生成费用」；非法 provider 400、删除不存在 404；体检修复对
  不可自动修项返回 `not_auto`、对已好的项幂等、未知 id 给 `unknown_item`；
  取消已结束作业幂等、未知作业 404。

  新增 `web/tests/test_runninghub_site.py`（站点真源 / overview 形状 / 测试打 effective）；
  引擎层 30 + Studio 20 测试全绿；manifest 316 条一致。
- **2026-11-01 更新（V0.7.47 · 资产/创作写操作真跑：真出图 1 张 + 真生成 1 集剧本）**
  接 V0.7.46（只验了读）。这轮把两页的**写**跑通，然后修掉 11 处「只在写的时候才炸」的问题。
  记录见 `docs/patches/2026-11-01_Studio实测缺陷清单.md` 第二节。

  **真跑结果**：本地出图 1 张（59.4s / 2769KB / ￥0，ComfyUI 按需启动 30s 就绪）；
  剧本生成走 DeepSeek 真实调用（19.6s / 4286 入 / 3326 出 tokens / 8 镜 62s）；
  草稿确认落盘并自动备份旧版。**主链路是通的。**

  **修掉的（按影响面）**
  | 问题 | 后果 |
  |---|---|
  | 草稿确认的乐观锁从未生效（前端不传 `expected_sha`，接口也不给） | 审稿期间别人改了剧本，确认会**静默覆盖**。现补 `target_sha` 往返 |
  | 分镜页「校验前置（G10）」调 `workflow.check`（已删） | 按钮点了报未知命令 |
  | `episode_preflight` 要求 `shot_id` 带 `ep01_` 前缀 | 真实项目恒报「段数 0 / 没有缺口」——**看起来正常，其实一个镜头都没查** |
  | 同上：`--ep ep01` 直接 `ValueError` | 界面按钮必然崩（`int('ep01')`） |
  | 同上：读根目录 shots.json | 分集产物在 `_eps/ep01/`，根目录那份可能过期 |
  | 流水线页 `PAGE_OF` 键还是 S1–S11 | 每行「打开」都跳「项目详情」 |
  | 创作页标题 / 资产页旧单价 / 三处 `tools/cli.py` 指引 | 文案过期，把人指向已删入口 |

  **金额**：DeepSeek 不返回 cost，`/api/llm/usage` 如实标「未知」而不是 ¥0；
  代价是成本中心看不到 LLM 花费，只有 token。要不要按 token 估算是产品决定，未动。

  新增 `stages/production/scripts/tests/test_episode_preflight_ep.py`（集号两种写法 + 镜头归属）；
  四层测试 49 个全绿；manifest 同步。
- **2026-11-01 更新（V0.7.46 · Studio 实测：三页读空气 + 4 个按钮点的命令不存在 + 首屏 22 秒）**
  记录见 `docs/patches/2026-11-01_Studio实测缺陷清单.md`。方法是起真服务、用 Node 直跑
  16 个视图模块（真后端）并真调命令，不是读代码猜。

  **① 首屏从 22 秒降到 1 秒（两个「重复求值」）**
  | 接口 | 修前 | 修后 | 根因 |
  |---|---|---|---|
  | `/api/studio/workflow` | 21.7s | 1.1s | `node_state` 递归无缓存 → 553 次调用、`cmd:` 判据真跑 62 次子进程 |
  | `/api/studio/overview` | 24.9s | 2.0s | 同上 |
  | `/api/health/checks` | 29.0s | 1.0s | `env_check` 用 `glob(recursive)` 扫整棵 Program Files：52,776 次目录列举 |
  | `/api/studio/env` | 13.6s | 1.0s | 同上 |

  节点备忘录放在 `evaluate()` 的**局部变量**里并显式向下传，**不挂 Ctx**
  —— 挂 Ctx 会让「改完文件再判一次」拿到旧结论（`test_nodes.py` 的 B04 当场抓到）。
  `env_check` 改为限深遍历 + 命中即停，三个二进制结果与修前一致。

  **② 三页读不到真实项目（最严重）**
  `studio.batches()` 只认 `^\d{8}_\d{6}$` 目录名**且**必须有 `summary.json`，而引擎支持
  `--batch-id EP01` —— 磁盘上 8 个段都在，后期制作/分镜/发行三页全显示「还没有集」。
  改为**按内容认批次**（目录下有 shot 级 `final.mp4` 即可），没有 summary 就现场数；
  产物名从写死改成前缀 glob（`_subbed_1080p.mp4` 以前识别不到）；
  只有字幕的集（ep02–ep04）也列出，标「无批次记录」。

  **③ 四个按钮点的命令已被删**
  `media.assemble`（后期页）、`assets.rh`（资产页 ×2）、`ux.py` 的任务动作表 ——
  全部在 V0.7.44 改名/删除，前端没跟。现在视图引用的 67 条命令 id 与 70 个 `api.*`
  方法都能对上（这条已做成脚本可复查）。

  **④ 把「未接入」换成真数据**
  发行页原写「G9 未接入（release_check 会写盘）」—— 理由成立但结论不必是不接：
  给 `release_check.py` 加 `--no-write`，新增只读接口 `/api/studio/release`，
  页面显示 verdict / fails / warns 与「看全部缺项」抽屉。

  **⑤ 新项目开箱可用**
  `subtitle.load_config` 缺 `config.subtitle.json` 时直接 `SystemExit`，而 `drama init`
  只生成 `config.local.json` —— **每个新项目第一次拼接母版都会失败**，报的是一句绝对路径。
  现在回退到仓库自带的 example 配置（stderr 说明一次）。

  **⑥ 文案与口径**
  总览「S1–S11 / workflow.py / 退出码 4」、创作中心与设置页的 `workflow.py`、
  后期页第 4 步「BGM 未接入」（V0.7.43 已并入母版）、总览「4 集 · ? 秒」
  （新增 `_ep_meta()`，从 blueprint/drama.json 取）—— 全部改掉；
  `web/STUDIO.md` 的 11 环节口径同步为 7 环节 23 节点，两份旧流程文档加失效声明。

  **测试**：新增 `web/tests/test_studio_episodes.py`（13 例：批次识别 / 产物 glob /
  集号归一）与 `test_node_state_memo.py`（求值纪律）；生产层 22 个 + Studio 19 个全绿。
- **2026-11-01 更新（V0.7.45 · 流程堵点复查：7 个「永远过不去」的节点 + 4 个坑）**
  详细记录见 `docs/patches/2026-11-01_流程堵点复查.md`。根因一句话：
  **`convert_storyboard` 把 data 按集分目录后，读侧有 5 处还写死根目录**，
  加上剪辑/出片判据找的目录层级与现实不符 —— 于是一堆节点「产物明明在，判据说找不到」。

  | # | 节点 | 修法 |
  |---|---|---|
  | 1 | `edit.master/upscale/subtitle` | 新增 `_out_hits()`：`<out>/<ep>` → `<out>/subs/<ep>` → 全 out 递归（限本集号） |
  | 2 | `video.batch/audit` | 新增 `_ep_segments()`：按本集 shot_id 找 `<批次>/<shot>/final.mp4` |
  | 3 | `edit.subtitle`（拼接） | `subtitle.data_ep_dir()`，两处读取容忍缺失 |
  | 4 | `prompt.contract` | `ingest_check` 改用 `W.data_ep(ws, --ep)` |
  | 5 | `script.continuity` | 节点加 `ep_style: int`（该脚本 `--ep` 要数字） |
  | 6 | `script.continuity` | `_pick()` 认三种 data 摆法（`data/` · `06-提示词/` · `06-提示词/<ep>/`） |
  | 7 | `drama status` | `data_f()`，按集目录优先、回退根 |

  新增 `_ws.data_ep()` / `_ws.data_file()` 两个解析函数，读侧统一走它们（老布局零迁移）。
  四个坑：dry-run 对「手写节点」打印假命令、`ep_path` 展示与宽容查找不一致、
  `asset.roster` 被 init 的占位名册假绿（新增 `roster` 判据做占位检测）、
  调研全 skipped 在 Studio 显示 done（展示层，未改）。

  验证：空项目 `drama init` 后全链只剩「剧本还是骨架」一处失败，其余均为上游阻塞；
  生产层 21 个测试文件全绿。
- **2026-11-01 更新（V0.7.44 · 重复项清理：删 20 个文件 / 净减 4703 行 + Studio 接回节点真源）**
  按 `docs/reform/2026-11-01_重复项复核.md` 的 D1–D13 执行（Owner：按建议走）。
  清单里每条都写了决定与落地结果，这里只记影响面最大的四件。

  **① 删（20 个文件，净减 4703 行）**
  | 项 | 删了什么 | 为什么 |
  |---|---|---|
  | D1 | `gen_char_assets.py`(448) / `gen_scene_assets.py`(487) / `probe_char_app.py`(106) | RH **AI 应用**通道：引擎 `IMAGE_PROVIDERS` 里没有对应 provider，且与工作流通道做同一件事；`drama assets` 只剩 `local` / `wf` |
  | D3 | `tools/cli.py`(385) + `tools/core/`(6 文件 ≈1102) | 旧工作台（SQLite + project.json）与 `nodes.py` 是两套编排；Studio 73 条命令里 `SCRIPTS["tools"]` 是唯一死映射 |
  | D4 | `cover_forge.py`(802) + 其测试 | 封面已定 AI 直出（`cover_prompt.py`），PIL 叠字兜底从未进主链路 |
  | D12 | `upscale_compare_frames`(169) / `upscale_cost_compare`(186) / `_qa_subtitle_frame`(172) / `fetch_bgm`(286) / `rh_workflow_id`(140) / `wire_episode_refs`(89) | 全仓零调用；`test_safe_area.py` 移入 `tests/` 并按新口径重写 |

  **② Studio 接回 23 节点真源（D5，本轮最重要）**
  上一版 `adapters.workflow_status()` 调的是 **V0.7.42 已删的 `workflow.py`**，实测
  `ok=False / reason=script_missing / stages=0` —— 于是「流程总览 / 助手上下文 / 流水线推进」
  三块全部**静默失效**（UI 只显示「未接入」，不报错，所以一直没人发现）。
  现在：`drama nodes --json` → `nodes.py::evaluate`（快照新增 `stage` 字段与 `stages` 定义）
  → `norm_workflow` 把 23 节点按环节聚合成 7 个 stage（done / current / todo，probes 放节点明细）。
  连带：`pipeline.STAGE_MAP` / `MANUAL_HINT` 从 S1–S11 改为七环节；`creation.js` 的
  `STAGE_IDS` 同步（否则创作页会白屏）；`setup_show` 改读 `drama.json`（原调已删的 `drama setup`）；
  删无调用的 `workflow_check`；`media.*` 命令按新剪辑顺序重排（删 `media.assemble`，
  新增 `media.upscale`，`media.master` 补封面/BGM 开关）。

  **③ 字幕只留锁定口径（D8）**
  `config.subtitle.example.json` 去掉 11 个视觉字段（字体/字号/边距/行宽/描边），只留断句与时序；
  `style_metrics()` 删掉百分比分支，`configs/subtitle-styles.json` 是唯一真源；
  **找不到规范直接报错**，不再静默回退 —— 回退的代价是「同一份规范在不同剧里长得不一样」，
  而 `qa_safe_area` 会按两套口径分别判过，比失败更危险。

  **④ 顺带修掉的三个真缺陷**（都是清理过程中暴露的）
  | 缺陷 | 症状 |
  |---|---|
  | `dialogue_gate` 把「拉丁 55 字符」写回去 | 2026-10-31 已取消该上限（改按词速预算），V0.7.42 新增的台词门禁又判死 —— 西语正常长句会被误杀。现改为「CJK 20 字 / 拉丁 本镜时长×3.8 词/秒」，测试加了一条「60+ 字符但读得完必须放行」 |
  | `nodes.py` 的禁用字段正则用了 `^#?\\s*` | 带缩进的 `    MOOD:` 是续行（属上一条 ACTION），却被判「含禁用字段」——合法剧本被判死。改为严格行首，并在 C01 加正反例 |
  | `find_cover` 与 `release_check.scan_covers` 命名规则不同 | 前者只认 `cover_9x16`，后者认 `cover[_-]9x16`；封面叫 `cover-9x16.png` 时片头静默不加。现共用同一条正则 |

  **⑤ 测试与文档**
  新增 `test_layout_parity.py`（四份布局实现对同一工作区必须给出同一 data/out/assets）、
  `_util.py`（`harden_stdio` / `read_json` / `write_json`，同层 4 处 `_harden_stdio` 收口，-60 行）；
  生产层 21 个测试文件全绿；四份旧文档（`creation/pipeline.md` 等）加「`tools/cli.py` 已废弃 +
  新旧入口对照」声明；`生产流程总纲.md` 第 22 行改「7 环节 23 节点」；`drama cost --help` 去掉 Excel。
- **2026-11-01 更新（V0.7.43 · 剪辑三步定型 + 三语字幕锁死）**
  剪辑环节此前是五节点（master → upscale → audio → subtitle → release），顺序与用户口径不符：
  BGM 排在放大之后，且 `_master.mp4` 与 `_mix.mp4` 谁是真母版说不清。本次按用户明确定义重排，
  并把「三语字幕规范」从运行期算出来的百分比改成**锁死的绝对像素**。

  **① 顺序定型：母版拼接（首帧封面 + 片段 + BGM）→ 高清放大 → 字幕生成与烧录**
  | 变更 | 内容 |
  |---|---|
  | 删 | `edit.audio` 节点（BGM 不再单独一步） |
  | 改 | `stage_master()` 一次产出 `<ep>_master.mp4`，内部三步：① 首帧封面（`09-发行/封面/cover_9x16*.png` → 0.8s 片头，找不到就告警跳过）② 片段拼接（保留 120ms 切点淡入淡出）③ BGM 混音（有 `_bgm-plan.json` 才混，混完覆盖回 `_master.mp4`） |
  | 改 | 节点数 24 → **23**；剪辑链 `edit.master → edit.upscale → edit.subtitle → edit.release` |

  为什么 BGM 必须在放大前：放大只重编码视音频，混好的音轨跟着走；放最后则要再重编码一次容器，
  且母版会有两个候选名。封面片头按**第一段实测编码参数**生成（同 codec/pix_fmt/fps/SAR），
  否则 `-c copy` 拼不上、或静默丢段（沿用已有的帧数校验 + 失败重编码兜底）。

  **② 放大后端三选一**（`config.upscale.json` 的 `backend`，命令行 `--backend` 覆盖）
  | 后端 | 说明 |
  |---|---|
  | `topaz`（默认） | 本地 GPU，免费，整集 3–8 分钟 |
  | `rh` | 新增。RunningHub `RH_Astra Iris`（`2110614419863592961`），约 35 币/61s 集、2–3 分钟；输入先转 h264/8bit（服务端解不动 hevc Main10），节点 4/5 传短边/长边，输出按源宽高比吸附后自动 crop 到精确目标 |
  | `off` | 跳过（母版已是交付规格时用），落 `skipped` 报告，节点判据据此放行 —— 否则节点会永远等一个不会出现的文件 |

  RH 分支**复用引擎的 `runninghub_client`**（协议层只有一份实现），不另写一套 HTTP；
  找不到引擎目录就明确报「改用 --backend topaz」。新增能力卡 `configs/capabilities/rh.upscale.v1.json`；
  `capabilities.py` 的节点校验改为**按卡声明**（`required_nodes`），不再写死视频卡的五个键 ——
  否则放大卡会被判「缺 prompt / 缺 duration」，一张完好的卡永远红。

  **③ 三语字幕规范锁死**（新增 `configs/subtitle-styles.json`）
  以 1080×1920 的**绝对像素**为准，其它画布按 `min(W/1080, H/1920)` 等比缩放：

  | 语言 | 字体 | 字号 | 每行 | 两行块高 |
  |---|---|---|---|---|
  | `zh` | Microsoft YaHei | 58px | 12 字 | 140px |
  | `en` | Arial | 52px | 26 字符 | 126px |
  | `es` | Arial | 50px | 26 字符 | 120px |

  三语共用落点：文字块中心 `0.6 × H`（1080×1920 上 y=1152，6:4），`\an5\pos` 逐条定位。
  两条硬规则：一行字宽超安全区（756px）→ **报错**，不静默缩字；落点进 UI 区（距底 <200px）→ **报错**，
  不静默上顶。静默缩字/上顶正是「同一份规范在不同剧里长得不一样」且 qa 查不出来的成因。
  样式表查找顺序：`config.subtitle.json` 的 `style_sheet` > 项目 `config.subtitle-styles.json` >
  仓库 `configs/subtitle-styles.json`；**都找不到才回退旧的百分比算法**（老项目不受影响）。
  `config.subtitle.example.json` 补 `en` 语言段（断句/语速口径），断句与时序仍归它管。

  **④ 文档与测试**
  新增 `docs/production/剪辑与字幕规范.md`（顺序、产物名、三语参数、失败定位一张表）；
  `生产流程总纲.md` 第 11 行与字幕安全区两处改为新口径；
  新增 `stages/subtitle/scripts/tests/test_subtitle_styles.py`（9 例：锁定值 / 同线 / 安全区 /
  等比缩放 / 两处必须报错 / 回退兼容）；`test_nodes.py` 节点数断言 24 → 23。

  **⑤ manifest 重新基线化**
  `manifest.sha256` 停在 V0.7.41：13 条指向已删文件（S2/S6/B5/B7/L8 那批）、47 个文件哈希与磁盘不符
  —— 于是 `env_check` 的完整性一项本来就是红的。本次按当前磁盘重算（47 条更新 + 13 条移除，
  共 313 条），复核 `313 条受管文件全部一致`。新增的三份配置/文档不在受管范围内
  （`configs/` 只收 example 两份，与 `channels.json`/`looks.json` 同规则）。

- **2026-11-01 更新（V0.7.42 · 按 Owner 圈定删六项 + 新增台词复核 + 资产转手写）**
  两件事：把 Owner 圈定的六项能力删掉，再按他的三条口径改造剧本与资产环节。

  **① 删（六项）**
  | 编号 | 对象 | 为什么 |
  |---|---|---|
  | S2 | `workflow.py` + `pipeline.py` | 与 `nodes.py` 是两套编排（S1–S11 vs 23 节点），口径不一致 |
  | S6 | `project_setup.py` | 九项确认与 style/models/init 重叠，且被 S2 依赖 |
  | B5 | `half_narrated_check.py` | 读 `05-分镜/storyboard.json`，全仓无生成器 → 永远跑不通 |
  | B7 | 四个 `_check_*.py` | 零引用的一次性校验器 |
  | L8 | `cost_report.py` + `cost_xlsx.py` | 与 cost_ledger 报表重叠；台账只留 markdown/JSON |
  | V9 | `workflow_qwen21_blocking_16x9.json` | 九宫格链遗留，无人引用 |

  连带：`drama.py` 去掉 setup/workflow/pipeline/halfcheck 四个入口、cost 去掉 Excel 参数、
  成本估算改为直接读 `project-setup.json`（不再 import 已删模块）；
  `commands.py` 81 → 73 条；`app.py` / `adapters.py` 去掉 workflow、setup 两条能力声明；
  `cost_ledger.py` 移除 xlsx 导出。
  `test_setup_workflow_pipeline.py`（57 例）拆为 `test_convert_ffs_release.py`（13 例）——
  只保留仍然有效的三类契约：refs 分流 / FFS 规则 / 发行版本选取。

  **② 新增：台词逻辑复核（剧本环节）**
  `dialogue_gate.py` + 节点 `script.dialogue`（在 `script.gate` 与 `script.continuity` 之间，故节点 23 → 24）。
  规则来自 `3d-short-drama-studio/references/dialogue-driven-rules.md`，**只取能机器判的部分**：
  单镜 ≤2 句（E1）、单句 CJK≤20/拉丁≤55（E2）、同镜旁白与对白并存（E3，规则 R3）、
  旁白条数超配额（E4）、旁白出现在中段（E5）、台词密度不足（E6，按本集实际时长折算）。
  另有三条提示：连续 3 镜零台词（W1）、疑似空功能台词（W2，词表）、说话人不在本镜 CHAR（W3）。
  判不了的（「这句有没有功能」「三拍落点是否可摘录」）**不假装能判** —— 那属内容评审。
  实测 US01 ep01：5 条硬失败（2 处单镜 3 句、3 处单句超 55 字符）。

  **③ 资产：A1/A2 改为会话或技能产出**
  `asset.prompt` 节点从「跑 `character_design.py plan`」改为**手写**：
  人物设计与角色卡提示词由会话/技能产出，引擎只留 `check`（四条规则验收，是节点判据）
  与 `plan`（可选骨架）。`character_design.py` 因此从「生成器」退为「骨架 + 验收」。

  **④ 资产：风格段统一为变量**
  原来角色卡有「真人版 / 3D 版」两套文案，各自的风格句写死 —— 选了 look 也进不来，
  这才是「为什么只有两个版式」的真正观感来源。现在：
  结构差异仍由 track 决定（要不要三视图是该它管），但**风格只有一份** ——
  `resolve_style_prompt()` 从 `drama.json` 的 `format{track,look,sub_mode}` 解析，
  经 `style_gate.compose_style_prompt()` 拼成「look.prompt + 渲染流.prompt」，
  灌进 `bible["style_anchor"]` 供所有模板共用；`--style-prompt` 可临时覆盖。
  实测：US01 解析出 `surreal live-action film look, ...`（来自 drama.json 的 `surreal-cinema`）。

  **回归**：生产层 23 个测试文件全绿（新增 test_dialogue_gate 12 例、test_convert_ffs_release 13 例）；
  Studio 9 套全绿；节点 24 / 命令 73 与文档一致。
- **2026-11-01 更新（V0.7.40 · 更正 V0.7.38 的一处错判；新增能力清单）**
  **更正**：V0.7.38 写的「`stages/subtitle/scripts/upscale.py` 这个文件不存在」是**错的**。
  该文件存在（49 KB，独立 CLI，自带 `--ep/--workspace/--target`，产物名 `<ep>_master_<W>x<H>.mp4`，
  与 `edit.upscale` 的判据 `*_master_1080x1920.mp4` 完全对得上）。
  错因：我先在一个**筛选过的文件名列表**里没看到它，就把「不在列表里」当成「不存在」——
  拿筛选结果当全集，这是这次排查里最不该犯的错。

  连带后果：V0.7.38 把 `edit.upscale` 改成了 `subtitle.py --stage upscale`。
  那是个**受开关控制的阶段**（`want_up = up_on and args.stage in (...)`，`upscale.enabled` 默认关），
  开关关着就什么都不做，节点会永远卡在「找不到 `*_master_1080x1920.mp4`」——
  等于把一个正确的实现换成了一个空转的。现已改回直连 `upscale.py`，并在节点注释里写明原委。

  V0.7.38 另外三条判断经复核仍然成立：
  `edit.audio` 路径确实错（`bgm.py` 在 production 下）且缺 `--apply`；
  `edit.release` 的 `--all` 确实越界到其它集；`release` 判据确实拿全剧总集数在比。

  **新增** `docs/reform/2026-11-01_能力清单_待删减.md`：按环节列出全部能力
  （S 系统 / R 调研 / P 剧本 / A 资产 / B 分镜 / H 提示词 / V 出片 / E 剪辑 / L 合规发行 / W Studio / T 工具），
  每条标注入口、状态（主链路/辅助/重叠/无引用/死）与说明，并附「重点决策可疑项」排序。
  该文档只做盘点，未删除任何能力。

  **回归**：node_runs 6 例、nodes 25 例；其余未受影响。
- **2026-11-01 更新（V0.7.39 · 画风库成为唯一口径；修 Studio 目录回归）**
  用户问：「画风已经从三轨增加到画风库，怎么项目还是用的『画风三轨规范』？」查下来是三件事叠在一起。

  **① 文档层**：`docs/styles/画风三轨规范.md` 虽在 V0.7.32 加了「已降级」横幅，但**正文仍是旧口径**
  （三轨 = 形态 + 题材 + 半解说三合一，含 `storyboard.json` 与三格分镜约束），而 README 还把它标成「★ 单一真源」。
  现在：删除该文件，新建 `docs/styles/画风库规范.md` —— 四维对照表、**13 条 look 全表**、
  **6 条渲染流表**（并说清「渲染流不是风格库」）、拼装公式、锁定时机、命令、常见误用、与旧文档逐条对照。

  **② 代码层（真 bug，V0.7.32 引入）**：`web/core/styles.py::catalog()` 把 `style_lib()` 当成风格库返回。
  但 V0.7.32 已把 `style_lib()` 的语义从「题材风格」改成「轨道渲染流」，且返回项**没有 `id` 字段** ——
  后果：Studio 里只能看到 6 条渲染手法（`guoman-3d-render` / `cel-anime` / …），
  **超现实电影、赛璐璐、拉美魔幻现实这 13 条真正风格一条都看不到**；
  `web/tests/test_workflow_store.py` 直接 `KeyError: 'id'`。
  现在 `catalog()` 返回 `looks`（风格库，含 id/name/prompt/tags/recommended_for）+ `render_styles`（渲染流，标注所属轨），
  `styles` 保留为兼容别名。`web/app.py` 建项目时的 style→track 推断改读 `recommended_for[0]`
  （look 拆分后不再有 `track` 字段，旧代码恒取空）。

  **③ 命名层**：`configs/styles.json` 早已不含风格（只剩画幅/分辨率预设），改名为
  `configs/render-presets.json`。改名理由很直接：打开一个叫 styles 的文件却找不到风格，
  就会得出「风格没写进库」这个结论 —— 用户这次问的正是这个。

  **④ 全仓库「三轨」措辞清理**：`style_gate.py`（头注释/argparse）、`drama.py`（style 帮助）、
  `web/core/commands.py`（style.list 说明与 agent 提示）、`stages/_layout.py`、`project_setup.py`、README、三份 docs。
  历史记录（`docs/patches/*`、`VERSIONS.md` 旧条目）**不动** —— 它们记的是当时的事实，改了就是伪造。

  **⑤ 新增边界判据**：`test_style_gate.py` 加 3 例 —— `looks.json` 不得含
  `track/narrative/delivery_stop/narration_*` 字段、至少 13 条、每条必须有 prompt。
  这条把「look 只承载视觉」从文档约定变成机器判据：一旦有人往库里塞 track，换 look 又会连带换规格，
  整轮拆分就白做。

  **⑥ 顺带修 `env_check` 重复项**：`RUNNINGHUB_API_KEY` 同时在「配置」与「环境快照」两个组各出一条，
  Studio 修复清单出现重复 id `cfg.rh_key`，`web/tests/test_health.py` 判失败（17 项 → 16 项）。
  现在一个变量只一条体检项，`SNAPSHOT_KEYS` 改为 `(name, why)`，`missing` 时按「有没有 KEY」给不同修法。

  **流程教训**：这批 bug 里有两条（Studio 目录、体检重复项）都在 `web/tests/` 覆盖范围内，
  而我 V0.7.32–V0.7.38 期间**从未跑过 web 测试**。以后回归清单必须包含 `web/tests/*.py`。

  **回归**：style 26 例（+3）；web 全绿（health 16 项、workflow_store、commands、inventory、jobs、pipeline、
  assistant、assets_page、connections、generators、comfy_boot、llm_gateway；llm_e2e 缺 fastapi 跳过）；
  其余全绿（nodes 25 / node_runs 6 / convert 17 / gen_boards 16 / init 14 / model 29 / release 15+14 /
  migrate 16 / workflow 57 / channels 10 / slot_hygiene 32 / character_design 28 / env_check 22 /
  comfy_ports / workflow_map / escape 3 / repo_paths 3）。
- **2026-11-01 更新（V0.7.38 · 剪辑五节点接上执行体；节点执行体的错法从此可判）**
  第 14 项。`edit.*` 五个节点此前**只有判据、没有可用执行体**：`run` 字段是「想当然写下的」，
  四类错同时存在，而且都不会抛异常 —— 节点只会「一直过不去」，报错却是「找不到 `*_bgm.mp4`」，
  看起来像数据缺失。这类错以前没有任何东西能挡住。

  **① 改掉四个真错**
  | 节点 | 原 run | 问题 | 现 run |
  |---|---|---|---|
  | `edit.upscale` | `subtitle/scripts/upscale.py` | **脚本不存在**（放大是 `subtitle.py` 的一个 stage） | `subtitle.py --stage upscale` |
  | `edit.audio` | `subtitle/scripts/bgm.py mix` | 路径错（实在 `production/scripts`）+ 缺 `--apply` | `production/scripts/bgm.py mix --apply` |
  | `edit.release` | `release_export.py --all --apply` | ep 级节点用 `--all`，跑 ep01 会重导全部 | `release_export.py --apply`（`--ep` 由调度器注入） |
  | `edit.master` / `edit.subtitle` | 正确 | — | 保持 |

  **② `release` 判据改成按集判**
  旧实现拿「全剧总集数」跟已导出数比，于是跑 ep01 时因为另外 29 集还没导出**永远不过**，
  报错是「发布版 1 / 目标 30 集」—— 看着像数据缺失，其实是判据越界。
  现在 ep 级只看本集 `EpisodeNN.mp4`；全剧盘点归 `release_check.py`，不归这个节点。

  **③ `--dry-run` 在上游阻塞时也打印命令**
  以前 `do edit.audio --dry-run` 只回一句 `[BLOCKED]`，而人想看的是「这条命令拼成什么样」——
  检查接线恰恰发生在上游还没跑通的时候。现在抽了 `_build_args()` / `_print_plan()`，
  **dry-run 与真跑共用同一份命令拼装**（各写一份的下场是「干跑看着对、真跑报错」）。

  **④ 新增 `tests/test_node_runs.py`（6 例，全静态、零执行）**
  - R01 每个节点都有 `run`，且要么是 python 命令、要么显式声明为人工/内置
  - R02 命令里的脚本**必须真实存在**（这条直接抓出 `upscale.py` 不存在）
  - R03 目标脚本有 `--apply` 门闸而命令没带 → 判失败（抓「永远空转」）
  - R04 ep 级节点不许用 `--all`（抓「跑到别的集去」）
  - R05 `cmd:` 检查器必须能解析到脚本
  - R06 **检测器自测**：正反两个方向都要能判出来 —— 永远返回 False 的检测器
    会让 R03 永远通过，那种绿比红更有害

  **回归**：新增 6 例；其余全绿（nodes 25 / convert 17 / gen_boards 16 / init 14 / style 23 /
  model 29 / release 15+14 / migrate 16 / workflow 57 / channels 10 / slot_hygiene 32 /
  character_design 28 / env_check 22 / comfy_ports / workflow_map / escape 3 / repo_paths 3）。
- **2026-11-01 更新（V0.7.37 · 删冗余：站点只剩一条路，三份重复实现收敛成一份）**
  V0.7.36 把站点搬进配置后，`RUNNINGHUB_BASE_URL` 就成了**死变量** —— 但代码里还有 8 处读它、
  三处各写一份「先 env、再项目配置、最后引擎默认」。留着不是「兼容」，是给同一件事留三条路。
  按用户口径「冗余的都删掉，直接删」，一次清干净。

  **① 环境变量**：用户级 `RUNNINGHUB_BASE_URL` 已删除（注册表键一并清掉）。
  保留的是**凭据**而不是配置：`RUNNINGHUB_API_KEY` / `_2` / `ENT_` / `ENT_2` / `ENT_3`。
  其中 `ENT_3` 当前无代码引用，但删掉不可恢复（要重新从平台复制），故只标记不删。

  **② 解析规则收成一条**：`resolve_rh_site()` 不再是「有配置就用、没配置回退 env」的双轨，
  而是**显式参数 > SOLODRAMA_RH_SITE > configs/channels.json > 常量默认**。
  旧变量仍然读一次，但**只用于体检提示「它还在，但已经没用了」**（`RH_SITE_IGNORED`），
  让下次 `echo` 到旧值的人能立刻看到原因，而不是再排查一轮。

  **③ 三份重复实现收敛为 `stages/production/scripts/_site.py`**
  `runtime_site()`（仓库真源）/ `project_site(vp)`（项目覆盖层优先）。
  改动点：
  - `capabilities._rh_runtime_site()` → 委托 `_site`
  - `tools/env_check._resolved_site()` → 委托 `_site`
  - `project_setup`：删掉 `SITE_ENV_NAMES`，三处读站点改走 `_runtime_site()`
  - `gen_char_assets` / `gen_scene_assets` / `gen_assets_rh_workflow` 的 `base_url()`
    三份逐字重复（且都先读死变量）→ 统一 `return _site.project_site(VP)`
  - `rh_doctor.BASE_URL` → `_site.runtime_site()`
  - `drama.hydrate_env` 的 `want`、`gen_assets_rh_workflow._ENV_WANT` 里删掉该变量
    （这两处会把死值**重新灌进子进程**，是「哪来的 .ai」的再生源）
  - `project_setup` 的两处提示文案：不再教用户 `setx RUNNINGHUB_BASE_URL`，改成 `configure.py set-site`

  **④ 体检里不再检查一个不生效的变量**：`ENV_KEYS` 去掉 `RUNNINGHUB_BASE_URL`；
  配置组改成显示「RunningHub 站点 + 来源」，残留旧变量时给出「建议删掉」的 hint。

  **⑤ 实测抓到一条同类隐患**：`tools/env_check.py::_bin_candidates` 里写的是
  `r"C://Program Files"` —— 反斜杠在写盘时被吃成斜杠，这些路径**永远不可能命中**。
  后果正是「装在 Program Files 里的工具被判成没装」。已改回真反斜杠，并在注释里标了病因。

  **验证**：`capabilities check` 全过；全仓库 `os.getenv("RUNNINGHUB_BASE_URL")` 直读 **0 处**；
  `test_channels.py` 10 例（含「没有配置也不许回退旧变量」）；其余套件全绿
  （nodes 25 / convert 17 / gen_boards 16 / init 14 / style 23 / model 29 / release 15+14 /
  migrate 16 / workflow 57 / slot_hygiene 32 / character_design 28 / env_check 22 /
  comfy_ports / workflow_map / escape 3 / repo_paths 3）。
  **manifest.sha256 36 条不符**：预期内（本轮改了文件），收编/推送时统一重建，不在中途刷。
- **2026-11-01 更新（V0.7.36 · 环境整改：站点真源、快照可见、死路径清理）**
  起因是用户点名「本地环境识别的功能经常误判，明明已装好的工具却说没装」。查下来是两个真问题，
  而且是同一类根因：**进程环境是启动快照，而系统里没有一处地方说清楚「以谁为准」**。

  **① 站点从「环境变量」搬到「仓库配置」**（`configs/channels.json` 新建）
  `RUNNINGHUB_BASE_URL` 是进程启动快照：用户级早就改成 `.cn`，已开着的终端 / Studio / 由其派生的
  子进程仍读 `.ai`。症状是上传接口报 `code=1 API Key不存在` —— 看起来像 Key 错、像账号错、像站点错，
  唯独不像「变量过期」。而站点根本不是机密，没有理由放环境变量里。
  现在解析链是：**显式参数 > `SOLODRAMA_RH_SITE` > `configs/channels.json` > 旧环境变量（仅当没有该配置）> 常量默认 `.cn`**。
  模块暴露 `RH_SITE_SOURCE`（这次站点从哪来）与 `RH_SITE_IGNORED`（被忽略的过期值），
  但**不在 import 时 print** —— 这条路径被大量 import，一次跑批会刷几十遍；要查的时候能查到即可。

  **② 能力卡与引擎共用同一个数**
  以前 `capabilities.py` 拿裸环境变量跟卡里的 `site` 比，于是报「站点不一致」，而引擎根本不会用那个值 ——
  纯噪音，还把人往「换 Key」上引。现在通过 `_rh_runtime_site()` 问引擎自己（解析规则只留一份实现）。
  顺带修两处卡与代码脱节：
  - `_node_ready()` 同时认**平铺**（`nodeId`）与**分段**（`slots`）两种写法。出片改六槽后
    `char_ref` 变成 283/284/285 三个槽，旧校验只读 `nodeId`，会把分段写法的卡判成「缺 char_ref」。
  - 卡里 `slots` 从旧的 `declared: [282,283]` 同步为六槽分段（282 分镜 / 283-285 角色 / 286-287 场景），
    并新增「分段之和 ≠ total」判据 —— 否则「有槽位没分段」会静默退化成顶灰。

  **③ 环境体检新增「环境快照」组，能区分「没设」与「设了但没读到」**
  读 Windows 注册表拿**持久化值**，与进程值对照，四态：`present`（一致）/ `stale`（持久化有、进程没读到）/
  `process_only`（临时 export，重开就丢）/ `dangling`（指向的目录已不存在）。
  这两种情况的修法完全相反（一个去填值，一个去重开终端），以前全被归成「未设置」，于是同样的现象反复被当成新问题。
  实测抓到两条：
  - `RUNNINGHUB_BASE_URL` 进程 `.ai` ｜ 持久化 `.cn` → 标 stale，但**已不影响运行**（引擎读配置）。
  - `SOLODRAMA_WORKSPACE` = `D:/剧本/海外剧/1013新建`，**目录已不存在** → 标 dangling。
    这个变量会让每次不带 `--workspace` 的命令都落到死路径，报错却像「找不到剧本」。
    已从用户级环境变量删除（空值也一并清掉），改由命令显式传 `--workspace`。

  **④ `configure.py set-site cn|ai|https://...`**
  换站点不再手改 JSON、更不再改环境变量。带 `--dry-run`，认不出的站点直接拒。

  **⑤ 顺手改掉一个反复出错的写法**：`_find_repo_root()` 不再数 `parents[N]`，而是**向上找
  `configs/channels.json`**。`parents[n]` 数错一层在本仓库已发生五次，症状全是「文件不存在/模块找不到」。

  **验证（都不花钱）**
  - `capabilities check`：三张卡全过；站点行显示 `卡=.cn ｜ 运行时=.cn（configs/channels.json，已忽略过期的 .ai）`
  - `video.resolve` 判据由 **failed → PASS**（此前就是被「站点不一致」拦下的）；`prompt.contract` 判据亦 PASS
  - `drama nodes`：通过 7 ｜ 不过 0 ｜ 过期 2 ｜ 阻塞 12 ｜ 跳过 2。两条「过期」是资产图按**旧 bible**出的
    （7 维→3 项那次改动），属内容侧重出，不是环境问题
  - 新增 `test_channels.py` 9 例（配置压过过期快照 / 显式覆盖 / 别名 / 无配置回退 / 忽略留痕 /
    卡与引擎同数 / set-site dry-run 不写盘）

  **回归**：新增 9 例；存量全绿（nodes 25 / convert 17 / gen_boards 16 / init 14 / style 23 / model 29 /
  release 15+14 / migrate 16 / workflow 57 / slot_hygiene 32 / character_design 28 / env_check 22 /
  comfy_ports / workflow_map / escape 3 / repo_paths 3）。
- **2026-11-01 更新（V0.7.35 · `drama init` 建项目骨架 + 两条新判据）**
  第 13 项。在此之前，开一部新剧要手工建 9 个阶段目录、手写 `layout.json`、
  抄 roster、抄分镜骨架 —— 漏一个就出现「引擎去 `video-pipeline/data/` 找、布局写在 `06-提示词/`」这类错位。

  **① 新增 `init_project.py` + `drama init`**
  - **结构不重写**：目录、README、`layout.json`、`config.local.json` 全部由 `_layout.scaffold()` 产出（布局唯一真源）。
    本脚本只做两件事：调 scaffold，写内容模板。
  - 写 6 个模板：`drama.json`（四维）/ `04-资产/design/roster.json`（2 个占位角色）/ `refs.json`（空表）/
    `blueprint.md` / `ep_01.md` / `ep01_storyboard.md`。
  - **模板是空的，不是范例**：三个内容模板里刻意一个 `[SC-nn]`、一个镜头块都没有。
    塞一个能解析的示例镜，`drama next` 会以为这集写完了，人得靠肉眼分辨「示例还是真稿」。
    **空模板的失败比示例模板的通过更有用。**
  - 幂等：不加 `--force` 不覆盖已有文件；`--dry-run` 不落盘。
  - `drama init` 走**早期分派**：在 `_preset_workspace_from_argv()` + `import _ws` 之前就切给 `init_project`。
    试图在主流程里「降级放行」会一路漏（WS/VP/DATA/OUT/LOG_DIR 逐个 None 检查），
    而 init 的职责正是「让工作区存在」——建项目的脚本不能依赖「项目已存在」的模块。

  **② 新增 `STATUS: DRAFT` 判据**
  `init` 建出的蓝图 0.8 KB，而判据是 `file>=800` 字节 —— **模板差点被判成完成**（差 30 字节）。
  现在三个内容模板首行都带 `<!-- STATUS: DRAFT — 写完把这一行删掉 -->`，
  `nodes.py` 的 `file>=` / `ffs` / `board` 判据统一识别该标记。
  比调大字数门槛可靠：标记只有「写完删掉」这一个语义。老项目没有这行，直接过，不误伤。

  **③ `tracks.json` 加显式 `default`**
  形态默认值原本取 `order[0]`。`order` 是「界面上怎么排」，`default` 是「新项目默认用哪个」——
  混用会让「调了显示顺序 → 新建项目默认形态静默变化」。现在 `default=live_action`。

  **④ 新增 `tools/tests/test_repo_paths.py`（3 例）—— 治「parents[N] 数错一层」**
  这个错误本轮出现**五次**（gen_boards / nodes / main.py / init_project / test_init_project），
  症状都不是「路径写错」，而是「文件不存在 / 模块找不到 / 数值为空」，排查会先怀疑数据。
  现在用 AST 静态解析所有 `ROOT = <本文件基准>.parents[N]`，算出实际指向并与仓库根比对；
  零 import、零副作用；含自测样本防扫描器空转。

  **测试**：新增 17 例（init 14 + repo_paths 3），累计新增 75 例；存量 232 例全绿。
- **2026-11-01 更新（V0.7.34 · 把验收从「做一部剧」改成「引擎自证」）**
  用户纠正了一次边界：我的任务是整改引擎，不是制作短剧。这条纠正暴露的是**引擎的设计缺陷**——
  V0.7.33 那批新代码（`nodes.py` / `gen_boards.py` / `convert_storyboard.py` 的新逻辑）**零测试**，
  所以验收只能靠「真跑一遍 ep01」：写 8 条分镜提示词、出 8 张图。那等于用「我做出一部短剧」
  证明「引擎没坏」——剧做出来了可能是我手工补了内容，引擎照样有 bug；做不出来又分不清是谁的问题。

  **① 新增最小项目夹具** `stages/production/scripts/tests/fixtures/mini_drama/`
  1 集 2 镜，全字段齐（layout / 调研 / 蓝图 / 剧本 / 名册 / refs / 分镜 5 字段），
  不含任何真实剧本内容。9 个文本文件，合计 ~5 KB。

  **② 新增四份测试（58 例，全离线、零计费）**
  - `test_nodes.py`（25 例）：23 节点表自洽 / 状态六值推导 / 判据正反例 / Loop 四层 / variant_hash 防抖 / 执行与 marker
  - `test_convert_storyboard.py`（17 例）：5 字段解析 / `board: |` 块标量 / 不吞 `prompt:` / Picture 重排闭合 / 五文件契约 / 死字段
  - `test_gen_boards.py`（16 例）：**人数从 refs 实算（1/2/3 人分别验）** / 模板无写死句式 / 构图锚定位 / 读 md 不依赖 boards.json
  - `test_escape_corruption.py`（3 例）：全仓库扫描「正则转义被破坏」

  **③ 测试逼出来的 6 个真缺陷**（全部是「只有跑起来才发现」的）
  1. **`gen_boards.py` 的 `_specs_from_md` 整段正则是坏的**（heredoc 把 `\s` 写成 `//s`），
     所以 V0.7.33 那次「改读分镜 md」其实从未生效，一直靠 `boards.json` 回退在工作。
  2. `nodes.py` 的 argparse 报错解析同样是 `//s` —— 自适应剥参数从未生效。
  3. **`（手写` 与 `（内置判据` 被同一分支吞掉**：`asset.roster` 这种「该你写」的节点，
     产物在就被当成「检查通过」返回 0。
  4. **`stale` 被 `passed` 抢先**：旧顺序是「判据通过就 passed」，于是改完资产、
     分镜 md 一个字没动也照样 passed —— 拿上一版分镜去出图，肉眼查不出来。
  5. **拓扑成环**：`board.frame` 依赖排在它后面的 `prompt.assemble`。修法是让分镜图生成器
     **直接读分镜 md**（分镜环节自己的产物），不经提示词环节的中间文件。
  6. **`refs.json` 的相对路径有第三种基准**（相对资产目录）。此前只认「相对工作区/相对 data」，
     US01 与夹具各踩一次，基准还不一样。
  另修：`asset.prompt` 的执行命令缺 `--roster/--out`；`AVA` 这种「直接写代号」的 refs 认不出；
  节点执行命令支持 `{ws}/{ep}/{assets}/{data}` 占位符。

  **④ 转义损坏从「靠记忆」改成「靠判据」**
  同一条坑踩了四次（`subtitle.py` / `prompt_gate.py` / `nodes.py` / `gen_boards.py`），
  共同点是**都不报错、静默不匹配**，症状看起来像数据问题。现在 `tools/tests/test_escape_corruption.py`
  扫全仓库，把 `//s //d //w //n //Z` 这类正则上下文里的可疑写法直接判失败（含自测，防止扫描器永远返回空）。
  纪律仍然有效：**正则不经过 heredoc 写盘，用直接编辑**。

  **回归**：新增 58 例 + 存量 232 例全绿（style_gate 23 / model_gate 29 / release_check 15 /
  release_export 14 / migrate_assets 16 / creation 57 / workflow 57 / slot_hygiene 32 /
  character_design 28 / comfy_ports / workflow_map / env_check 22）。
- **2026-11-01 更新（V0.7.33 · 四项 D1 破坏性改造做完：资产 3 项 / 分镜 5 字段 / data 五文件 / 分镜图出片 / 七环节 23 节点）**
  这一版把 V0.7.32 有意留下的四项 D1 一次做完。用户确认「现在没有其他短剧任务在做」，产物作废可接受。

  **① 资产 7 维 → 3 项签名**（`stages/assets/scripts/character_design.py` 1765 → 1029 行，−42%）
  - 保留：**身份**（代号/姓名/年龄/性别/身份/阵营/皮肤/表情）、**造型**（色签名 + 服装中英 + 发型）、**锚**（一处非对称标记，可为空）。
  - 删除：骨相 7 槽（`FACE_GEOM`/`SLOTS`）、体态（`POSTURE`）、人群桶（`PERSONA`/`_bucket`）、织物轮转（`FABRIC`）、阶层自动判定（`WEALTH_*`）、面部距离规则 R1/R2。
    理由：模型不按「中庭比例」执行，只按「年轻女性」执行；写满七槽等于写一张均值脸。真正的辨识靠发型轮廓 + 主色 + 锚，这三样在缩略图上就能分辨。
  - 规则从 6 条收到 4 条（R1 色相间隔 / R2 锚唯一 / R3 主演发型 / R4 美颜词）。
  - `_formal()` 补「法务/总监/合伙人/护士长」——旧表认不出「集团法务」，把法务判成工装。
  - `_hue_slots()` 改「按色相排序后等间距取」：旧实现按下标跳，3 个阵营拿到 8°/148°/286°，最刺眼的一对只隔 82°。现在 8°/92°/222°。
  - 测试重写 28 例（含 A02 断言「8 个已删符号必须不存在」，防止残骸被别的代码 import 到）。

  **② 分镜 11 字段 → 5 字段**（`convert_storyboard.py`）
  - 现行：`duration / ratio / refs / board / prompt`。新增 `board`（**这一镜的分镜图提示词**，单帧 9:16）。
  - 删除：`banana_prompt`（九宫格）、`crop`（裁 3×3）、`time`（光位注入）。旧 md 里出现只告警、不生效（`DEAD_FIELDS`）。
  - `crop` 固定 `{1,1}`（分镜图是整张，不切）。

  **③ data 四文件 → 五文件，且按集分目录**
  - 新增 `boards.json`（`{shot_id: {prompt, ratio, refs}}`）；`shots.json` 每镜加 `board_ref`。
  - 落点由 `data/` 改为 `data/<ep>/`。**旧实现固定一个目录，跑 ep02 会把 ep01 的 shots.json 静默覆盖**（只留一堆 .bak_时间戳）。
  - 引擎加 `--ep`，并且 `--data-dir` 未显式给时**走 `_layout` 真源**。此前 `config.local.json` 的 `data_dir` 只给 `_layout` 读、引擎自己不用，于是布局写 `06-提示词/`、引擎找 `video-pipeline/data/`，报「shots.json 不存在」——两处各说各话。

  **④ 出片改「分镜图 + 角色 + 场景」三参**
  - H3 六槽重新分段：`282=board_ref`（`<Picture 1>`）、`283–285=char_ref`、`286–287=scene_ref`。此前只登记 282/283，另外 4 槽交给 SLOT_HYGIENE 顶灰，等于浪费。
  - `<Picture n>` 由 `renumber_pictures()` **机械重排**：分镜图占 1，角色与场景整体后移，并在 `[REFS]` 段首插入分镜图说明（「定义 WHERE，不定义 WHO」）。人手改 32 个镜必出错。
  - **分镜图只做构图锚，不做身份锚**：默认走本地文生图（240 张 ￥0），不给角色卡。给得太像，H3 会把分镜图里那张脸当身份锚，与角色卡打架 —— 两头都像、又都不完全像，是最差的结果。
  - 新增 `gen_boards.py`（分镜图生成器）：人数从 `refs` 的 `char_*` **实算**，绝不写死（EP03/EP04 的事故就是写死 `exactly one person`）。
  - 引擎 `Inputs` 扫 `04-资产/boards/<ep>/` 建 key→路径映射（`board_<ep>_<shot_id>`），不靠手工登记。

  **⑤ 画风四维维护**：`configs/tracks.json` / `narratives.json` / `looks.json` 三份正交配置延续 V0.7.32，`style_gate` 双读双写 `drama.json`。

  **⑥ 七环节 23 节点 + Loop 四层环**（新增 `nodes.py`，`drama next|do|nodes|graph|skip`）
  - 七环节：调研 3 / 剧本 4 / 资产 3 / 分镜 3 / 提示词 2 / 出片 3 / 剪辑 5 = **23 节点**。每节点六字段：触发 / 读 / 产物 / 判据 / 接替 / 回流。
  - 状态六值（`absent/stale/failed/passed/skipped/blocked`）**只由磁盘 + 判据推出**，不读内存、不读对话。
  - Loop：L0 retry(2) / L1 repair(3，必须变变量) / L2 reflow(1，回白名单上游) / L3 batch。`variant_hash` 相同即判 `stuck`（退出码 5），不浪费一次失败重跑。
  - **回流边白名单 23 条**，不在表里的跳转一律拒绝。
  - 可选节点（调研 / continuity）缺席或未达标**只标注不阻塞** —— 否则一部没有调研的项目永远走不到剧本。
  - 判据里不挂 `tools/cli.py check`：它要求工作区有 `project.json`，而实跑项目（引擎视角工作区）没有那个文件，挂它永远 exit 1。改用**内置 FFS 结构检查**（HEADER 允许 `# TITLE:` 前缀；HEADER 不全只告警，镜头/DUR/禁用字段才硬判）。

  **⑦ 实测抓出并修掉的 8 个真缺陷**（都是只有真跑才暴露的）
  1. `comfy_ports.missing_required_inputs` 把 `COMFY_AUTOGROW_V3`（min=0 的动态输入组）判成缺输入 → 文生图工作流永远过不了自检。
  2. `parse_md` 的 YAML 块解析「取前 60 行里所有缩进行」，`board:` 会把后面的 `prompt:` 整块吸进来。
  3. `board: |` 初版没走块解析，`boards.json` 里存的是字面量 `"|"`（契约看着有值，实际是空内容）。
  4. `ROOT = HERE.parents[1]` 写错一层（应为 `parents[2]`），在 `gen_boards.py` 与 `nodes.py` 各犯一次。
  5. `main.py` 找 `_layout` 用 `parents[3]`（= `stages/video`），应 `parents[4]`（= `stages`）。
  6. `_layout.data_dir(video-pipeline)` 返回 `video-pipeline/video-pipeline/data`：`_layout` 要**项目根**，引擎 workspace 是 `video-pipeline`，差一层。
  7. `drama.py` 转发 `--workspace` 时 `str(None)` 传成字面量 `"None"`。
  8. 判 `--data-dir` 是否显式给，不能用「和默认值比」（默认值会被覆盖层改），要用 `sys.argv`。

  以及一条反复踩的**工程教训**：heredoc 写盘会把正则里的 `\s` 变成 `//s`（这次在 `nodes.py` 又踩一次，函数静默不匹配）。**正则不要经过多层字符串拼接写盘，改用直接编辑。**

  **实测证据**（`docs/reform/evidence_20261101_图生图顺序/`）
  - `05_ep01_八镜分镜图拼版.png`：ep01 八张分镜图，构图各异、主色稳定（女绿男红）、空间连续、无文字无拼版。
  - 出片 nodeInfoList 实测顺序：`282` 分镜图 → `283/284` 角色 → `286` 场景 → `132` 时长，`[shot_001] ④ 参考图匹配完成（分镜图 1 张 / 角色 2 张 / 场景 1 张）`。

  **回归**：style_gate 23 / model_gate 29 / release_check 15 / release_export 14 / migrate_assets 16 / creation 57 / workflow 57 / slot_hygiene 32 / character_design 28 / comfy_ports / workflow_map 全绿。
- **2026-11-01 更新（V0.7.32 · 四维拆分 + 单一档案 + 提示词门禁 + 能力卡 · 破坏性变更）**：按整改方案 v2 施工，四包里已完成三包半。
  ① **画风四维拆开**（这是「画风库和 3D/2D/真人半解说串在一起」的根因）：新增 `configs/tracks.json`（形态：时长/资产/拓扑/交付）、`configs/narratives.json`（叙事：旁白配额/台词密度）、`configs/looks.json`（视觉：13 条纯 prompt，**禁止** track/narrative/delivery_stop 字段）。`style_gate.py` 改为配置驱动，`sub_modes` 只留渲染流，题材风格走独立 `--look`。`configs/styles.json` 瘦身为 aspect/resolution 预设。**验收过了**：同一个 `surreal-cinema` 在 live_action / 2d_animation / 3d_manhua 三轨都能 `set` 成功。
  ② **单一档案 `drama.json`**：新增 `stages/production/scripts/drama_profile.py`（读写唯一实现，文件名避开标准库 `profile`）+ `migrate_profile.py`（从三份旧确认单推导，只做可判定映射、不猜）。`style_gate` 双读双写：drama.json 优先、旧文件兜底。US01 已迁移，状态与迁移前一致。
  ③ **口径变更两条**：2D 轨 `delivery_stop` 由 `narration_handoff` 改为 `final_video`（2D 也是短剧，不该止步于旁白交接）；真人轨 `storyboard_topology` 由 `three_panel_per_clip` 改为 `one_frame_per_clip`（三格拼版正是 P21 雷同的源头）。对应 2 条单测已按新口径更新。
  ④ **提示词门禁 `prompt_gate.py`（新增）**：C1 人数锁=CHAR 代号数 / C2 SHOT 的 Two-Three bodies 与 N 一致且不得与 ONLY one body 并存 / C3 在场一致 / C4 无 CJK / C5 `<Picture n>` 闭合。**实测抓出 EP03 2 镜、EP04 3 镜硬失败，EP01/EP02 各 0** —— 与人工核对完全吻合。已接进 `ingest_check.py`（`--ep` 时自动跑）。
      · 实现要点：角色来源**用分镜 md 的 `- refs:`，不用 shots.json** —— 后者是转换产物且 data_dir 固定（多集互相覆盖），拿它判所有集会张冠李戴。
      · 踩坑复现：写正则时又被多转义成 `refs://s*`，函数静默返回空、全部判成「CHAR 0 人」。这正是 P36 记过的那条坑，第二次踩到。**教训：正则不要经过多层字符串拼接写盘**。
  ⑤ **环境体检三态**：`tools/env_check.py` 的 BINS 探测由 `shutil.which` 改为「PATH + 候选安装位置」，输出 `state ∈ present / found_elsewhere / missing`，`found_elsewhere` **算通过**。实测 `whisper-cli` 现在显示 `found_elsewhere` 并给出真实路径 `C://Users//15274//whisper-cli//whisper-bin-v1.8.0//Release//`，不再报「未安装」。`web/core/health.py` 透传三态。
  ⑥ **能力卡 `configs/capabilities/`（新增 3 张）** + `capabilities.py list/show/check`（默认离线 <1 秒，`--online` 才联网）：`comfy.qwen21_t2i_hq.v1` / `rh.h3.multiref.v1` / `topaz.iris-2.v1`。每张带 `known_issues`，把今天踩的坑（494 语义、枚举后缀、RH 不能禁节点、Topaz 双目录）写死在卡里，避免下次重新推理。
  ⑦ **清理**：`_回灌包_20261101` 归档到 `docs/archive/回灌包_20261031`；12 个 `_probe/_ep0*.log` 移入 `_scratch/`（已 gitignore）；三份旧规范（总纲/标准作业流程/画风三轨）标题去掉「唯一真源」并加降级声明；回灌包里「旧剧本只会变松、不会变严」的错误结论已就地更正（实测反例：4 秒镜 19 词，旧 PASS 新 FAIL）。
  **回归**：test_style_gate 23 / test_model_gate 29 / test_release_check 15 / test_release_export 14 / test_migrate_assets 16 / test_creation_pipeline 57 / test_setup_workflow_pipeline 57 / slot_hygiene 32 / character_design 28 / comfy_ports / workflow_map 全绿。
  **未完成（下一批）**：出片改「分镜图+角色+场景」与 data 五文件契约、资产 7 维→3 项、分镜 11→6 字段、七环节 23 节点与 Loop 四层环。这四项都是 D1（已产出作废）或大改，需单独一批做完，不在本次半途留下半套。
- **2026-11-01 更新（V0.7.31 · 节点开关能力 + 图生图实测 + 站点改 zh · 破坏性变更）**：三条用户口径落地。
  ① **本地通道获得「真的关节点」的能力**：按参考图数量从 prompt 图里**删掉**多余 LoadImage、指向它的边、以及因此孤立的上游。实测同一份 6 槽工作流：2 张参考图 → 槽 6→2、关掉 8 个节点；4 张 → 槽 6→4、关掉 4 个。出图侧（`comfy_client.build`）与出片侧（`comfy_local_video`）都已接上，实现只有一份（`comfy_ports.prune_for_refs`），`comfy_client` 按路径加载复用、不复制。
  ② **RH 侧没有这个能力，必须说清楚**：`nodeInfoList` 是**值覆盖表**，没有「禁用节点」语义，未发的槽位沿用工作流保存值。只能 `blank`（顶中性灰，默认）/`empty`（空串）/`keep`（危险）。要真减少槽位只能改平台侧工作流。这条写进了 `SLOT_HYGIENE` 注释，避免下次又以为「代码里关掉了」。
  ③ **RH 站点默认改 zh**：用户级 `RUNNINGHUB_BASE_URL` 由 `.ai` 改为 `https://www.runninghub.cn`（config.py 默认本来就是 .cn）。实测这枚 key 在 `.cn` 与 `.ai` 都能 probe 通过，所以切换无风险；**注意进程环境是启动快照，改完要重开终端/Studio 才生效**（同 `env_check` 的 E2 坑）。
  ④ **本地图生图工作流实测通过（真跑，不是干跑）**，并给出顺序证据（`docs/reform/evidence_20261101_图生图顺序/`）：
      · 参考图顺序 = 槽位顺序：`--image A --image B` → 489=A、490=B；
      · **画幅由 13 `ResolutionSelector` 控制，与参考图无关**（2026-11-01 更正，此前判断错了）：`--aspect 9:16` 实测输出 **1088×1920**（比例 0.5667，2MP × multiple 8 取整）。
      · **教训**：先前观察到「输出跟着 ref1 的比例走」，误判成工作流的固有限制，其实是**我们自己的 bug** —— `build()` 一见 refs 就把 494 写成 `false`，开关于是取 `on_false = 471[2]`（参考图编码出的 latent），绕开了 `EmptyLatentImage`。494 的标题是「自定义比例」，`true` 才是「按我给的画幅」，此时参考图仍作为 conditioning 喂给 471，身份照样生效。已改为默认 `true`，并加 `--follow-ref-ratio` 保留「跟随参考图」这条路。
      · **用三视图角色卡做参考，出图就是三视图**（又一次印证 P27）：单人正面裁图 420×1088 作 ref1 → 恰好一个人；整张三视图卡作 ref1 → 画面复刻出正/侧/背三个小人。
  ⑤ **修掉四个只有真跑才会暴露的缺陷**：
      · `--image` 原来是**可重复传但只保留最后一个**（`action="append"` 漏了）—— 传两张实际只用一张，日志只字不提，于是「槽位顺序不对」查无可查；
      · `--aspect` 传裸 `9:16` 必 400 `value_not_in_list`（ResolutionSelector 只认 `9:16 (Portrait Widescreen)`），新增 `normalize_aspect()`；
      · `/prompt` 的 400 原来只显示 `HTTP Error 400`，真正的 `node_errors` 被丢掉；现在解析成「节点X(类)：原因 —— 详情」；
      · **有参考图时把 494 布尔写成 `false`**，等于主动放弃画幅控制权，`--aspect` 白给。改为按 preset 声明 `mode_when_refs`（edit 轨 = `true`），语义写进注释：这个布尔不是「开不开编辑」，而是「画幅听谁的」。
  ⑥ **新增提交前「必需输入」校验**（`comfy_ports.missing_required_inputs`，本地出图/出片两边都接）：节点类存在 + 模型存在 ≠ 能跑。用用户给的 6 参考图工作流一验就抓到两处 —— `VAEDecodeAudio` 少了必需的 `vae`（原导出里 audio VAE 节点 18 是**孤立**的，等于没接线，成片会没音轨）、`ImageScaleToTotalPixels` 少了 `resolution_steps`。两处已在工作流里修好，修复说明写进同名 `.map.json` 的 `_substitutions`。
  ⑦ **`frame_source` 按用户要求清掉**：配置项、校验分支、`configure set-h3 --frame-source` 参数、示例配置、探针输出全部移除；`pipeline.py` 的首帧分支简化为「取裁剪第 1 格」。旧覆盖层里残留这个键只告警不报错。
- **2026-11-01 更新（V0.7.30 · 四条通道 ID 与三份本地工作流写进默认值）**：把「每次换通道都要 probe 一遍再手填」的活儿收敛成默认值。
  ① **RH 四条通道全部落到默认**（来源：`solodrama预配置.txt`）——文生图 `2113267040969646081`、图像编辑 `2111261410541006850`、视频 `2113319585146560513`、放大 `2110614419863592961`。前三者挂在 `config.py` 的 `IMAGE_PROVIDERS` / `IMAGE_EDIT_PROVIDERS` / `H3`，放大新建 `UPSCALE_PROVIDERS`（此前引擎**根本没有**放大通道，`upscale.py` 只有本地 Topaz 分支）。
  ② **图片通道从三个空 TODO 收敛为一条真通道**：原 `banana / gpt_image / jimeng` 三个 `id=""` 的占位槽，只有 `banana` 实际在用。现在合并为 `rh_t2i`（纯文生图，`image_input=False`），旧名走 `_IMAGE_PROVIDER_ALIASES` 映射，不复制配置。**顺带修掉一个假阴性**：`missing_configs()` 原先无条件索要 `char_ref / scene_ref`，而纯文生图工作流没有 LoadImage，等于把「配置正确」判成「没配好」，永远过不了启动检查。
  ③ **`nodes` 只登记引擎会消费的键**：H3 填 `prompt=138 / duration=132 / char_ref=282 / scene_ref=283`（实测已跑通 47 币/9s 段）。284–287 另外 4 个 LoadImage 槽**故意不登记**——登记了会被当成「本镜要用的图」，应由 `SLOT_HYGIENE` 顶中性灰。参考图提交形态沿用 `url`（历史 30 集批量实证），不改成 `fileName`。
  ④ **三份本地工作流入库**：`workflow_qwen21_t2i_hq.json`（= 桌面《Qwen 2.1 turbo 文生图》+ 3 处基线：cfg 1→2 / 负向非空 / 3:4·m8→16:9·m32，原始导出留 `workflows_src/qwen21_t2i_raw.json`）、`workflow_qwen21_edit.json`（桌面《图生图》，新增）、`workflow_h3_multiref6.json`（桌面《minimax 多参一采 6 参考图 + 4 步 LoRA》，替换旧的单图 4 步版）。
  ⑤ **视频工作流两处必要替换**（已写进同名 `.map.json` 的 `_substitutions`）：UNET 由 `minimax_h3_hybrid_fl2va_ref2va_b25-49-int8` 换成本机已有的 `Cobijada_H3_Hybrid_Uncensored_pruned_hybrid_int8_convrot_pruned`（原权重未下载）；6 个 `LayerUtility: ImageScaleByAspectRatio V2` 换成内置 `ImageScaleToTotalPixels(1.28MP, lanczos)`（layerstyle 依赖 `blend_modes` 未安装，节点类型不存在）。
  ⑥ **`comfy_client.py` 改为「按工作流文件名套预设」**：`t2i` / `edit` 两套节点映射沉淀进 `WORKFLOW_PRESETS`，`--workflow` 一变即自动换映射，环境变量仍可单键覆盖。此前每换一次工作流都要手工 export 五个变量。
  ⑦ **`comfy_local_video.py` 的槽位填充语义修正**：参考图少于槽位时，由「循环复用第一张」改为「重复最后一张（场景）」。旧行为把两张人脸各喂两遍，与 RH 侧「未覆盖槽位沿用残留图导致串景」是同一类问题，只是这里由循环造成。
  **判据**：`configure.py show` 四条通道 id 齐全；`comfy_local_video.py --map-check` 12 项全 OK；`test_slot_hygiene` 32 / `test_comfy_ports` / `test_workflow_map` / `test_setup_workflow_pipeline` 57 / `test_character_design` 28 全绿。
  ⑧ **图像编辑工作流的节点是实测回填的，不是猜的**：`run.py probe --kind workflow --id 2111261410541006850` 拿到 30 个可填节点——提示词在 **74（CR Prompt Text）**、6 个 LoadImage 在 91/177–181、KSampler 32（cfg=1 / steps=25 / denoise=1）、SaveImage 95 前缀 `LQ-`。**它与文生图那条不是同一套图**（t2i 的提示词在 57），照抄 id 会写到不存在的节点上。
  ⑨ **站点问题实测收口**：预配置文本把 key 标注为「zh 站」，但本机 `RUNNINGHUB_BASE_URL=https://www.runninghub.ai`（用户级环境变量）下 `probe` **正常返回**，说明这枚 key 属于**国际站**。此前 `docs/patches/2026-11-01_取消站位图参考与切换RH视频通道.md` 的「必须 .cn」结论与当前 key 不符，**以实测为准：保持 .ai，不要改成 .cn**。若哪天报 `code=1 API Key不存在`，先查这一条。
  ⑩ 放大通道的 4/5 号节点**实测默认值是 4=1920 / 5=1080（横版）**，竖版必须显式送 `4=1080, 5=1920`——这也解释了当初「给反了输出 598×1080」。
- **2026-11-01 更新（V0.7.29 · EP01 画面不可读的三层根因 · 破坏性变更）**：用户看完首集成片判定「画面内容完全是乱的，不知道在讲什么东西」。自查后结论：**不是出图模型的问题，是三件事同时发生**。
  ① **剧本层（P25，最致命）**：EP01 里 `contract / 契约 / sign / marriage / 婚 / 90` 各出现 **0 次**，标题《Ninety Days, Mr. Nobody》承诺的东西正片一次没有。查骨架 `人工拆解.md` 与 `blueprint.md` 确认——**契约被排到 EP02 才登场，问题在骨架不在正文**。连带三条：男主在 SC-03/04 **断线 16 秒**（占全片 24%）、四空间三跳时、开场是「递扳手」这种日常而非冲突（违反 §3.3 黄金 3 秒）。修法给了两案（倒叙砸设定 / 补视觉设定），**待用户拍板**。
  ② **提示词层（P26）**：8 个镜头的 H3 提示词里 `woman / man / she / he / female / male` 各 **0 次**，`figure` 出现 **38 次** —— 人物指代用的是 `the shorter figure in a worn cardigan` 这类**相对外貌**，出处是项目侧 `_tools/patch_storyboard_h3.py` 的 `LABEL` 字典。后果：SC-02（剧本是一男一女）成片出成**两个中年男人**。修法已验证：指代改为「姓名 + 性别 + 年龄段 + 服装色签名」，并在 `[SUBJECT]` 首句锁人数（`exactly two people — one woman and one man, nobody else`），`[ACTION]` 改用姓名。
  ③ **参考图层（P27）**：角色卡是「16:9 纯白 + 左脸特写 + 右三视图」= **一张图 4 个人像**，H3 多参把它读成 **4 个人物**，成片出现 3 个女主。修法：从角色卡裁**单人正面竖条**（`crop=420:1088:890:0`，左右边缘不得带进相邻视角——第一次用 `x=830,w=520` 把侧面像切进半个人，H3 仍判成两人），`characters.json` 指向单人版。实测同段提示词 → 8.5 秒全程恰好一男一女。
  ④ **whisper 反证（本次最重要的方法）**：用 `whisper-cli` 转写自己的成片，19 句台词**全部正确、无时序错位**。所以「看不懂」不等于「听不清」——**是画面与声音完全脱节**。根因：`[SUBJECT]/[ACTION]` 全是肢体动作（holds out / kneels / walks / copies），没有一条把**信息**翻译成画面里的**物件**。修法：每条补 `[PROP]`，且信息物件**用背面/侧面/局部表达**（「一张被两条黄胶带压住、边角卷起的纸」远比「写着 41 个名字的告示」可画）。
  ⑤ **连带修复 RH 放大工作流 `2110614419863592961`**：此前判「跑了 11 分钟报 805，不可用」是**误判**。真实三因：输入是 `hevc / Main 10 / yuv420p10le`（服务端解不动，先转 `h264+yuv420p`）、提交走了 v1 legacy 通道（改 `/openapi/v2/run/workflow/{id}`）、节点 4/5 是**短边/长边**不是宽/高（竖版给 `4=1080, 5=1920`；给反输出 598×1080）。修完实测 **52–62 秒 / 10–12 币**，输出 1062×1920。
  ⑥ **P31 引擎不支持一镜多角色**：`CHAR: ELLE, KANE` 被整串比对，同时报 E002 与 E003（12 个错）。一镜两角是短剧常态，照原实现根本写不出来。修法：`validate.py` 新增 `_split_codes()`（按 `, ， 、 ; ； /` 切分），`_check_codes` 与 `_check_char_anchor` 改为逐个代号比对，单代号行为不变。已同步五工作区。
  ⑦ **P32 宽景别诱发边缘补人**：`shot_001`（medium 35mm）右下角多出半个人（同款卡其夹克与棕裤），其余 7 段紧景别全部干净。`exactly two people` 这类数量约束**对宽景别效力不足**。修法双管：景别收紧到 `medium close shot, 50mm` 并写明站位关系；`[SUBJECT]` 末尾加边缘约束 `Nothing else enters the frame — no limb, no shoulder, no second body at either edge.`。**判据：出片后必须看画框四边**，问题在右下角，缩略图里几乎看不见。
  ⑧ **P33 上游产物改不动**：`convert_storyboard.py --apply` 会把 `characters.json` 按 `04-资产/refs.json` 重写，直接改 `06-提示词/characters.json` 等于没改（单人参考图的修复被无声回滚）。改源 `refs.json` 才持久，已封装 `_tools/make_single_refs.py --patch-refs`。**普适教训：凡上游生成的产物，改它等于没改。**
  ⑨ 重制结果（方案 A）：剧本 66 秒 / 8 镜 / 3 空间（BOARD·BOILER·WARD）/ 契约词 6 次 / 男主断线 8 秒，`lint` + `cli check` 双门禁 0 ERROR 0 WARN；RH 出片 8/8（1 段偶发失败原样重试即过，共 339 币）。**`[PROP]` 机制验证有效**——黄黑封条、打开的铝制工具箱、笔夹歪掉的银色钢笔、第七条上的红圈，四类信息物件均可在成片指认，且不依赖可读文字。
  ⑩ **P34 整集 ASR 让字幕逐段漂移**：整集合并后一次转写，whisper 把每段台词后的静音算进这一句，时间戳逐段累积（第 1 条占 0–13s，而 shot_001 只有 9.42s），到第 3 段已错开一整句——画面上是锅炉房、字幕却是上一镜台词。修法：`build_subs_ep.py` 改**逐段转写 + 段偏移**，误差锁在单段内；条数由 8 变 10（长台词正确切句）。判据：烧完必须抽帧比对字幕文本与画面场景是否同属一镜。
  ⑪ **P35 `subtitles=` 塞 Windows 绝对路径必失败**：`D\:` 转义会让 ffmpeg 把盘符后的路径当作 `original_size` 选项值。修法：ASS 复制进临时目录、`cwd` 切过去、filter 里只写裸文件名。
  ⑫ **P36 字幕普遍比音轨提前（用户验收反馈）**：`whisper.cpp` 的 SRT 起点习惯性标到 0，而 H3 语音每段开头有 0.3–1.4 秒呼吸/环境音（实测 8 段：0.313 / 0.398 / 0.421 / 0.685 / 0.730 / 0.739 / 1.357 s），逐段转写只解决段间漂移（P34），段内仍整体提前。修法：`voice_start()` 用 `ffmpeg silencedetect` 取首个 `silence_end`，把该段全部 cue 整体后移（仅当 0.05 < shift < 2.0）。**坑中坑**：第一版正则多转义成 `//s`，匹配不到任何东西，函数静默返回 0、流程照常出片——判据必须看行为：抽 0.2 s 应**无字幕**、0.7 s 应有字幕。另新增 `<ep>.fix.json` 每集 ASR 错字修正表，重跑不丢。
  ⑬ **P37 主角与群演同色系会被淹没**：EP02 SC-01 病区公告栏群戏，ELLE 的青绿针织衫与护士刷手服同色，人群里认不出主角。色签名只约束了「角色之间不撞」，没约束「角色与环境/群演」。修法：群戏镜 `[SHOT]` 写明其他人焦外不解析面孔、主角占前景、必要时给对比色小块。判据：抽一帧三秒内能指出主角。
  ⑭ **P38 放大失败不阻断，静默产出残缺成片（最危险）**：EP03 成片 58.87s 而剧本 66s——`shot_008`（钩子镜）放大返回 805，`upscale_rh.py` 只把失败写进 summary 不让进程失败，`pipeline_ep.py` 又没校验，于是拿 7 段拼了一集照常烧字幕归档。**成片能播、看起来完成了，但钩子没了**。修法：流水线两处硬校验（放大后逐段比对 + 烧录前 `copied < 8` 即中止），补跑后 58.87→68.29s。判据：成片时长必须接近剧本合计（±10%），不等就查 `upscale_summary.json` 的 `ok=false`。
  ⑮ **P39 中文剧本不能直接生成提示词**：第一版 `gen_h3.py` 把中文 ACTION 直接拼进 `[SUBJECT]`，出「beat 1 早班的病区走廊…」这种中文提示词；`[REFS]` 也残留「齐耳内扣短发」「松石青」。H3 只认英文，中文片段等同噪声。修法：**剧本/英文层/提示词三层分离**——`03-剧本/ep_XX.md`（中文，给编剧）+ `03-剧本/en/epXX.en.json`（英文，给 H3）+ `06-提示词/h3_prompts.json`（机器生成）。缺英文层直接报错退出，另加 `HAIR_EN`/`COLOR_EN` 映射表。
  ⑯ 完整复盘（含 whisper 19 句对照表、三条量化命令、判据、回滚）见 `docs/patches/2026-11-01_EP01画面不可读三层根因修复记录.md`。
  **遗留**：P25 待拍板、P28 跨段一致性无锚、P29 画面内文字载体出乱码、P30 字幕时间轴仍为字数估算（whisper 模型已备好，可直接重做）。
- **2026-10-31 更新（V0.7.28 · 弃用剪影：分镜图改为俯视站位图 · 破坏性变更）**：用户看完剪影分镜图直接要求「把剪影这个环节删掉，不要用剪影了」。
  ① **决策**：改用**俯视站位图**（`top-down floor-plan blocking diagram`）—— 这不是新发明，`画风三轨规范.md` §1.3.1 的对照表里本来就有，当时定位「调度补充」，现升为**主方案**，灰阶三色调剪影标为 **2026-10-31 弃用**。
  ② **为什么这个替换是对的**（不是迁就用户，是剪影选错了重点）：剪影把「景别 + 光位 + 构图」压在三格里，而**这些 H3 提示词本来就写清楚了**，图纸只是重复文字信息；它**无法表达的**「演员站哪、机位在哪、视锥盖哪块地」才是分镜阶段真正要确认、也最容易出错的部分。且实测同镜三格常被画成几乎一样的画面（因为三格差别往往只是光线与头部角度）。
  ③ **实现**：新增 `workflow_qwen21_blocking_16x9.json`（16:9 / 2MP / cfg=2）。与通用工作流**唯一差别是负向词** —— 必须去掉 `text, letters, numbers, signage, labels`，否则标题与图例会被一起压掉；改为 `photograph, 3d render, perspective view, realistic figures, human faces, hands, colour, gradient, shading, texture, drop shadow, blurry, low detail, watermark`。8 条分镜提示词全部重写为「ROOM / FIGURE A / FIGURE B / KEY MARKER / 标题 / 图例」六段式，画幅由 9:16 改 16:9，删除原 8 张三格剪影图。
  ④ **规范同步**（`docs/styles/画风三轨规范.md` §1.3.1）：① 标题改「统一画俯视站位图」并写明弃用理由；⑥「剪影的代价」改「站位图的边界」（不表达景别光位微表情，只解决空间调度）；⑦ 改「站位图必须写文字，负向词要单独配」（与场景卡相反：文字是需求不是噪音）；⑧ 模板补「相机三角必须在房间轮廓之外」并新增三个坑 —— **相机跑进房间/被家具压住**、**单人镜凭空多一个人**（模板留着 `FIGURE B:` 而该镜只有一人时模型会补画）、**缺图例无法审阅**；⑨ `weak_reference` 的解释由「复刻剪影质感」改为「把平面调度图当画面去复刻」。
  ⑤ **实测**（Qwen 2.1 turbo / 2MP / cfg=2 / 单张约 50 秒，8 张全部 1920×1088）：标题 `BLOCKING - EP01 SC07`、图例 `dot A = the seated woman, four small rectangles = the stack of bills` **全部清晰可读无乱码**；圆点带朝向箭头、视锥虚线扇开、关键物位置准确；单人镜确认只画一个点。已知小瑕疵：个别镜 `CAM A` 文字未出现、楼梯镜上方圆点的箭头画成双向。
  ⑥ **判据**：俯视平面（无透视/无写实人物/无脸）→ 人物=圆点+单箭头且点内无字母 → 相机三角在房间外且有 CAM A 与虚线视锥 → 底部必有一行图例 → 单人镜必须显式写 `exactly ONE human dot on the whole sheet`。
  ⑦ **P24 多集分镜图串集（数据流缺陷）**：EP02 的 8 张图出完，抽检发现标题写着 `BLOCKING - EP03 SC07`。根因三层：`convert_storyboard.py` 的 `data_dir` 是**固定目录**（每集转换覆盖上一集）→ `build_sb_manifest.py` 默认读 `06-提示词/shots.json`（只保留最后一集）→ 改 `kind` 后跑的「批量重建三份清单」循环里三次都读了同一个文件，三份 manifest 全成 EP03 内容。分集后果：EP01 图早出完反而是对的、EP02 全错、EP03 碰巧对。修法：`build_sb_manifest.py` 新增 `--shots` **显式绑定本集源文件**；每集转换后归档 data 到 `06-提示词/_eps/<ep>/`；站位图按集分目录 `scenes/ep01|02|03/`、清单按集命名；清单 `kind` 用 `shot` 避免被 `comfy_client` 再套一层 `scenes/`。判据：清单首条 `ROOM:` 必须属于本集场景、条目数等于本集段数、**出图后抽检图上标题的集号**。普适教训：**任何「读当前状态」的批处理，在多版本产物下必然串**。遗留：`convert_storyboard.py` 不支持按集分目录，多集只能靠外部 `_eps/` 绕，根治需给 `data_dir` 加 `--ep` 维度。
  完整复盘见 `docs/patches/2026-10-31_文生图选型与人像细节修复记录.md` §P23 / §P24。
- **2026-10-31 更新（V0.7.27 · 出图通道标准化：Qwen 2.1 turbo 高清基线 + 图生图 + 固定 seed）**：用户反馈「人物面部细节有点漂移，不够清晰」，要求生图统一回 Qwen image 2.1 turbo 但必须解决人像飘移。排查结论：**不是模型不行，是四个参数同时错了**。
  ① **cfg=1 让负向条件完全不参与引导**：`497 SamplerCustom.cfg=1` 时 `negative` 不参与计算，而 `character_design.py` 生成的【反默认】段（「不要画成通用 AI 美人脸：不削尖下颌、不放大眼裂、不做磨皮…」100+ 字）**全是否定句** —— 那一段 100% 无效，而它恰恰是反塑料脸的唯一约束。
  ② **1.5MP 下人脸像素密度不够**：16:9/1.5MP=1632×918，左半脸特写约占画面 40% 宽 → 脸部仅约 300×350 px。实测 1.5→2.0MP，针织织纹从「糊成一片」变为「可辨单根毛线走向」，是唯一零副作用的变量。
  ③ **manifest 不带 seed → 每次重跑换脸**：`_tools/build_manifest.py` 只写 id/kind/name/prompt/aspect；`comfy_client.build()` 里 `if seed is not None` 才写，None 就用工作流默认值 → 同角色重跑 3 次得 3 张脸，且改提示词时无法做受控实验（以为是提示词的功劳，其实是运气）。新增 `stable_seed(project, asset_id)` = `sha1("项目::资产")[:8] % (2**31-1)`：同资产跨批次可复现，不同剧不撞脸，且不写死常量（否则全公司同一张脸）。
  ④ **步数越多不等于越好**：Qwen 2.1 turbo 是蒸馏模型，8 步是设计点。实测 12 步 → 31 岁画成 40+，16 步更甚（细纹加深、眼窝凹陷）。hires fix 二段同样试过：denoise 0.55 会**改脸**（鼻梁压痕重绘变形），0.40 安全但 87 s vs 25 s 换不到明显收益 → 不做默认。
  ⑤ **修法**：新增 `workflow_qwen21_t2i_hq.json`（14 节点，16:9 / 2MP / cfg=2 / 负向词 `plastic skin, waxy texture, airbrushed, over-smoothed, symmetric face, cgi render…` / 8 步原 sigmas），并把 `comfy_client.py` 默认节点映射切到 488/487/497/13/474（否则开箱即用会崩）。
  ⑥ **图生图通道（P13/P14）**：新增 `COMFYUI_NODE_LOADIMAGE`（逗号分隔 LoadImage，按序接 `ref_images`）、`COMFYUI_NODE_MODE`（布尔开关，有参考图写 False）、`COMFYUI_NODE_SAVE`（指定 SaveImage；留空则多输出按**像素数取最大**）。参考图必须先 `upload_image()` 上传换成 input 目录文件名（`LoadImage.image` 只认服务器端文件名，写本地绝对路径无效），上传名用内容 sha1 前 16 位保证 ASCII 且可复用；`_img_size()` 纯标准库读 PNG IHDR / JPEG SOF。配套产出 `qwen_edit_16x9.json`（单图 15 节点，摘掉 `490` 与 `471.images.image_2`）与 `qwen_edit2_16x9.json`（双图 16 节点）。多输出不筛的后果：Moss+SeedVR2 这类双 SaveImage 工作流会让一张资产变成 `x_00.png`+`x_01.png`，下游 `refs.json` glob 与 `--skip-existing` 判重全被污染。
  ⑦ **Moss-image 试过未采用**：细节更实（毛孔/胡茬/发丝），但 38 岁出成 50 岁、指定短寸偏分出成大背头 —— 角色卡是全剧身份一致性的工业件，年龄发型错了就得重画，细节可以靠分辨率与 cfg 补，五官年龄补不回来。工作流保留在 `workflows/moss_image_16x9.json`。
  ⑧ **附带修好 SeedVR2 节点注册失败**：`ModuleNotFoundError: comfy_api` 是表层，真因是 `diffusers 0.27.2` 仍在 import `huggingface_hub` 已删除的 `cached_download`（要求 `diffusers>=0.33.1` 但没装上）。装 `diffusers>=0.33.1 gguf peft omegaconf rotary_embedding_torch` 后节点恢复。备用工作流 `moss_hires_16x9.json` 已产出（`batch_size` 5→1、`ImageScaleToTotalPixels` 0.3→1.5 MP、只留高清 SaveImage）。
  ⑨ **P18 落盘回归**：P3 把落盘改成「临时文件 → `os.replace`」后，Windows 上目标文件被占用（看图程序/杀软）会抛 `[WinError 5] 拒绝访问`，19 张批量必撞 1 张。改为三级降级（换名 → 先删再换 → 覆盖写），失败时保留临时文件并把路径写进报错——那张图其实已经生成好了，改名即可，不必重跑 50 秒。
  ⑩ **P19 场景伪文字**：2MP 后 11 个场景里 5 个出现满墙乱码（诊所整面数字表格、会议室白板乱码折线图）。先加负向词 `text, letters, numbers, signage…` **无效**——因为正向提示词的【空间】行就写着「墙上 32 个名字」「41 个名牌墙」「墙上一张并购进度表」「玻璃上的手写菜单」，模型只是忠实照做。这是 §3.8.1「剧本↔资产解耦」的复发，泄漏的不是长相而是**信息内容**。修法：只描述物质痕迹（`残胶/划痕/褪色/擦拭痕/空插槽/油渍`），不描述其上承载的信息。改完整面墙的伪表格消失，角色卡提示词 `cmp` 逐文件核对零变化。**普适教训：负向词只能减少，不能撤销指令——正向要求的元素，任何负向都压不住。**
⑪ **P20 女主脸上多出一道疤**：锚 `A14` 原描述「鼻梁上一道横向浅压痕（长期戴眼镜留下，但不戴眼镜）」自相矛盾，模型只能按「伤」理解；而 `live_card_prompt` 对**所有**锚都写「必须清晰可见」，把一道浅痕推成了显眼的疤（2MP 高像素密度进一步放大）。修法三件套：① 新增 `_anchor_sentence()`，锚的可见度按类型分档 —— `饰/眼镜/纹` 要求清晰可见，`疤/痕/斑/痣/轮廓/发` 改为「按本身尺寸与淡度如实呈现，不要加深/扩大/加高光/画成伤疤」；② `A14` 改为「无名指戒痕」（手部、肤色差，同属「痕」配额但不会被画成伤）；③ 主角显式指定锚，ELLE 用 `A08 磨损编织绳`。⑫ **P20b**：A08 初版被画成金属手链——「素色编织绳」在图像先验里指向不明，改为「米色棉线、三股细棉线搓成、绳头留短须、无金属件无吊坠」后正确。规律：**识别锚必须能被画出来，不是被理解**（「素色/低调」模型转不成像素）。⑬ **P21 分镜三格雷同**：`shot_001` 三格原为「两人面对面 / 光灭 / 头微抬几度」，差别只有程度副词，出图必然一样；改为「伸手够不到 / 手将触碰时光灭 / 收回胸前且距离拉开」后推进成立。判据：任意两格至少一项可画物理差异（肢体位置/物体位置/进画面/距离/光源状态）。⑭ 同批：8 张角色卡与 8 张分镜图按新基线重出，分镜专用 9:16 高清工作流 `workflow_qwen21_t2i_hq_9x16.json`。
  完整复盘（含 8 组实测对照表、判据、验证命令、回滚）见 `docs/patches/2026-10-31_文生图选型与人像细节修复记录.md`。**遗留**：P16 一人多套造型、P17 场景缺豪门空间、P19 场景描述待加自动校验、P22 分镜剪影在 2MP 下带出面部轮廓（需分镜专用负向词）。
- **2026-10-31 更新（V0.7.26 · 剧本层与资产层解耦：不再逼编剧先定长相）**：用户反馈「每次剧本创作都会出现这道手上伤疤」，要求「剧本环节不要把设定卡太细，要保留随机性」，并指出资产设计同病。排查后确认不是模型问题，是**三层串联的设计缺陷**：`convert.world_bible_to_char_anchors` 缺 `visual_anchor` 直接 `raise`（不写长相不许开工）→ `render_skeleton` 模板写死 `# CHAR: 代号: <锚点>`（占位符就在索要长相）→ `validate` 的 E002 用 `sha1` 逐字比对且无「留空」分支（只能照抄资产卡）。于是编剧的第一决策变成「他长什么样」，而不是「他想要什么」。⑥ 更深的病灶在随机性：`seed` 缺省是常量 `"solodrama"`，**没写 seed 的项目共用同一串哈希**；锚库 24 条里 4 条是疤（16.7%），A02/A03 排最前，选取用 `hash % len(pool)` 反复命中靠前条目 —— 实测 4 组模拟名册里 3 组的第二个角色都是「虎口烫痕」。修法：① `visual_anchor` 改可选，缺失即空串，不再抛错；② 骨架占位符改 `<身份/关系>`；③ E002 增加三条短路（HEADER 空 / 写 `-`·`无`·`待定` / 库内空），只有两边都写了才比对；④ `seed` 缺省改为按 `world + 全部角色名` 派生 `auto-<sha1[:12]>`，显式 seed 仍优先；⑤ 新增 `ANCHOR_KIND` + `KIND_QUOTA`（疤 1 / 痕 1 / 斑 1 / 痣 2 / 饰 2 / 纹 1），选取算法由取模改为 `sorted(pool, key=hash(seed+id))[0]`；⑥ `overrides.anchor` 支持 `none`，R4 跳过无锚角色，提示词整段省略锚点 —— 原则改为「主卡必须有锚，配角可以没有」。⑦ 同批修的还有：拉丁语系 55 字符单句上限取消（改 `DUR × 3.8 词/秒` 预算，单镜句数 2→4，4 条单测）；`script_rewrite.lint` 里残留的 40 字符硬阈值同步改词/秒；`tools/cli.py::cmd_import_bible` 读 `<ws>/bible/`、写 `03-剧本/` 的路径分叉。⑧ 资产侧同批补两处：`plan` 新增 `--card-style {auto,3d_manhua,2d_animation,live_action}` 与 `--scenes`，真人轨原生产出「16:9 纯白 + 左脸特写 + 右三视图」角色卡与场景卡（此前只有竖版 3D 模板，照它出图直接跑偏画风，每个真人项目都得在外面手写一套）；`_bucket()` 改为**只匹配 persona 词**并加年龄闸门（B7 长者 ≥50 / B3 天真者 14–32），修掉「31 岁急诊护士因身份里有『母亲』被判成长者」「护士长因『病区』被判成病态者」，无命中时也不再固定回落 B2（原本 8 人 6 个隐忍者），名册可用 `persona_bucket` 与 `overrides.expression` 直接指定。⑨ 测试：`test_setup_workflow_pipeline` 57 例、`test_character_design` 28 例全绿。**破坏性变更**：重跑 `plan` 的项目会换一套锚点，已出图的项目不要重跑（要旧行为就显式写 `"seed": "solodrama"`）。完整复盘见 `docs/patches/2026-10-31_剧本过度设定与识别锚重复修复记录.md`。
- **2026-10-30 更新（V0.7.25 · README 重构：交付报告 → 落地页）**：用户要求「简化说明，只介绍解决什么核心问题、技术思路，然后放几个案例效果」。原 README 736 行 / 121 KB，把完整操作手册与验收清单堆在首页，读者要翻过三段提示词才看到产品长什么样。重构后 ≈180 行 / 12 KB（−90%），结构固定为：它解决什么问题 → 技术思路（一张图）→ 案例效果（3 图 + 实测表）→ 三分钟跑起来 → 仓库结构与文档地图。
  ① **问题段用可核对的数字代替形容词**：一集 60 秒 = 6–10 个生成段 + 20–40 张资产图 + 11 个环节；交付规格 672×1216 = 0.5526 ≠ 9:16。
  ② **技术思路压成一张 SVG 图 + 三句洞察**（`docs/showcase/04-architecture.svg`，1200×556，6.5 KB）：三段式——编排层（虚线框，只调度不干活）/ 中缝 `data/` 四文件只读契约 / 引擎层 6 站，每站吊一条硬约束；底部一句「能自动判的绝不问人，判不了就停在原地等人」。图下只留三条反直觉设计（门禁拦「确认 A 跑 B」/ 字幕只认对齐 / 裁不补边），6 条落点收进 `<details>` 折叠表。**刻意不用 `<style>` 类选择器**：全部 presentation attribute + 根节点 `font-family` —— GitHub 走 camo 代理转发 SVG，内嵌样式有被剥离的风险，剥了就是黑底黑字。文字宽度先用 `ImageFont.getlength` 预检（超框直接报错退出），再用 headless Chrome 截图复核版式。
  ③ **案例效果三张图全部取自实跑工作区**（`docs/showcase/`，3 文件 645 KB）：① 资产总表（4 角色 × 4 视图 + 场景，2026-10-17 10:08 产出）② 同批分镜 3 段原帧（672×1216，同日 11:00 产出）③ Studio 工作台实机截图。实测表只留规模与产出：`《离婚后，四个大佬哥哥接我回家》` ep02–ep40 共 39 集 **261 段 / 1853 秒**（`ffprobe` 逐文件累计，非估算）。
  ④ **不写实际花费**（用户追加要求：「不要把我的实际成本写出来了，只介绍项目效果和功能」）：README 与 `docs/operations/项目档案.md` 里的账单列（RH 币金额 / 折人民币 / 平台单价与段数价差）全部撤掉，只留「云端按次计费、段数越碎越贵、台账逐笔可核」这类功能性表述。口径记在此处，不再出现在首页。
  ⑤ **提示词里的硬编码路径改成占位符**：原三段提示词写死 `D:\SoloDrama`（`docs/新项目启动提示词.md` 里更写死本机 `D:\编程\SoloDrama`），别人克隆到别处照抄就会指错。README / `使用者路线.md` / `新项目启动提示词.md` 统一改为 `<仓库路径>` / `<你想放的目录>` / `<剧项目目录>`，并在文档开头写明「复制前替换」。顺带修掉拆分时留下的重复句（「跑一遍离线自检，跑一遍离线用例」）。
  ⑥ **操作细节零丢失，按主题迁入 `docs/operations/`（新增 4 文件）**：`环境自检.md`（原 §零）、`使用者路线.md`（原 4.1 三段提示词 + 命令行速查）、`开发者路线.md`（原 4.2 + 配置与密钥 + 目录纪律）、`项目档案.md`（原 §一 交付清单/能力矩阵/平台硬限 + §三 实现历程）。**拆分只搬不改**，命令与判据逐字保留；标题层级按「原 H3→H2、H4→H3」重排，跨文件链接改 `../`。
  ⑦ **表述纪律**：不写「免费」（统一 ￥0 / 零费用）；图 2 图注显式说明「字幕在整集母版阶段烧录，这里看的是出片原帧」，不让读者误以为没有字幕能力。
  ⑧ 同步与验证：`docs/新项目启动提示词.md` 中「README 文末版本记录表」改指 `VERSIONS.md`（原引用已过期至 V0.3.1）；README 与 4 个新文档的相对链接 / 图片路径 0 失效；表格列数一致；`manifest.sha256` 重建后自校验 0 不符。
  基线提交（远端）：`7bb08ca`（`cd35348` → `7bb08ca`，4 个提交快进、未重写历史；本地已 `reset --hard` 对齐，`git status` 干净）。
- **2026-10-30 更新（V0.7.24 · 画面合规：黑边 / 品牌 logo / 无字幕的根因根治）**：用户反馈发布后频繁被驳回三类问题，其中「检测到视频画面中存在黑边」次数格外多，要求从工具根源上解决。
  ① **先证伪再定位**：对 `Episode01.mp4` 全片 1466 帧跑 `cropdetect`（limit 24 与 12 两档）**全部返回满幅** `crop=1080:1920:0:0`，左右边带 `YAVG=114`（不是黑）。⇒ 画面里没有黑边。真因是**交付规格的显示比例不是 9:16**：H3 出片 672×1216（21:38 = 0.5526）→ RH_Astra 按源比例吸附成 1062×1920（0.5531）→ 交付层为凑 1080×1920 用了 `SAR 59:60`（DAR 177:320 = 0.5531），平台按显示比例渲染进 9:16 容器必然补边（按高适配左右各 9px、按宽适配上下各 16px）。**这类缺陷本地永远查不出**：像素被拉伸过，四边全是画面内容。`1080×1920 + SAR 59:60` 是「用非方形像素骗过容器」，容器元数据对、显示比例错。
  ② **生成端为什么改不了**：`megapixels=0.8` + `ratio=9:16` 交给平台，平台按 **32 像素对齐**取整 —— 9:16 且 0.8MP 理论值 670.8×1192.5，对齐后只能落到 672×1216。精确 9:16 且 32 对齐的最小解是 **720×1280（0.92MP，成本 +15%）**，0.8MP 无解。⇒ 结论是「不要指望调 megapixels」，必须靠归一化层。
  ③ **新增 `stages/production/scripts/delivery_spec.py`（规格唯一真源）**：`SPEC` 常量（1080×1920 / SAR 1:1 / 9:16 / yuv420p）供全链引用，别处不许再写字面量；`probe()` 返回 `display_w = width × SAR` 与 `display_ratio`（不是像素比）；`judge()` 四条判据按顺序报（SAR 第一，因为它是黑边的直接原因）；`normalize()` 做 **crop-to-fill**，三步顺序不可换 —— 先 `scale=trunc(iw*sar/2)*2:ih` 把非方形像素**还原成真实显示宽度**（否则后面的 scale 会接着沿用那 1.69% 的拉伸），再 `force_original_aspect_ratio=increase` 放大到**刚好覆盖**（用 decrease 就留余量，留余量只能 pad），最后 `crop` 居中裁切。**绝不 pad**。比例容差 0.3%（比 1.69% 这个量级松就抓不住），尺寸另设硬要求（比例对不等于尺寸对）。
  ④ **归一化挂进烧字幕那一步（不新增工序）**：`subtitle.py` 新增 `DELIVERY_SPEC` / `norm_filter()` / `spec_violations()` / `ensure_delivery_spec()`，在 `do_render` 分支里先归一化母版再按归一化结果写 ASS。顺序不能反：ASS 的 `PlayRes` 一旦按放大母版的 2560×4632 写好，烧到 1080×1920 上虽然 libass 会按比例缩放，但 `qa_safe_area` 的断言口径就和实际画面不一致了。已合规的源零成本复用（只 probe 不重编码），`--no-normalize` 可关。实测 672×1216（10bit）→ 1080×1920（8bit）**17 秒/集**。
  ⑤ **新增 `stages/production/scripts/compliance_media_check.py`（画面侧门禁）**：与只覆盖题材侧（发布前三问 / AIGC 标注 / 受限占比，全靠人答 yes-no）的 `compliance_precheck.py` 并列。C1 规格；C2 内容层黑边**判「纯」不判「暗」**（真实夜景有噪点渐变，补边是恒定色 —— 取 `YAVG ≤ 20` 且 `YHIGH−YLOW ≤ 14` 且跨帧一致，零依赖走 `crop + signalstats`）；C3 硬字幕三级证据链（产物名 `_subbed` → `report.json` 的 `verify_render.pass` → 字幕带（画面 50–70% 高，对应 `anchor_top=0.6`）近白像素 ≥ 25%），任一级不成立即 FAIL，判据刻意「宁可误杀」；C4 品牌 logo **只做 4×3 抽帧拼图 + 明确标 MANUAL** —— 本机无 vision provider，任何「疑似通过」都是伪结论。
  ⑥ **出口设卡**：`release_export.py` 默认对每个候选源过门禁，不合格**不进导出计划**（退出码 2，附人话修法），`--no-media-check` 仅限临时预览。不可读的源降级为 WARN（离线测试用假 mp4 造工作区，不能因此全红）。顺带修三个真实缺陷：顶层 `from _ws import WS as _WS_DEFAULT` 是导入期常量，脏环境变量下 `--workspace` 还没解析进程就 `SystemExit`（改为延迟导入 `_default_ws()`）；`_scan` 里 `f.parent.name == "剧集"` 无条件跳过，导致人工放在 `07-成片/剧集/` 的成片整批被判「没有可识别集号」（改为只跳过**目标目录本身**）；`EP_RE` 不认 `EpisodeNN`（补 `(?:isode)?`）。
  ⑦ **品牌 logo 前置规避**：`prompt_templates.BAN` 原只禁「文字/字母/数字」，管不住**图形商标**（勾 / 咬了一口的苹果 / 三叶草 / 四环）与**去字化的配色标识**（红底白字方块、双 C 扣）。补一条覆盖服装鞋包 / 手表首饰 / 手机电脑 / 汽车车标 / 店招门头 / 商品包装，一律用无标识通用款。一处改动、三类资产（角色/场景/道具）全部生效。
  ⑧ **踩坑**：归一化中间件最初命名 `<ep>_norm1080_1920.mp4`，会被 `SOURCE_PREFERENCE` 的 `_1080` 规则判成「已编码发布版」（rank 0，比 `_subbed` 还优先）—— 等于把「无字幕」问题原样复制一遍；改成不含分辨率数字的 `_normdelivery`，并在 `_rank()` 里强制排最后。另：本轮抽帧发现画面里有**大面积可读文字道具**（手写信件满屏），这类同样可能触发「未授权文字/水印」类驳回，已写进文档。
  ⑩ **补一道断言：cues=0 不许出片**。`--stage render` 不跑对齐，`align/*.json` 缺失时 `build_cues` 返回空列表，旧实现会静默写一份空 ASS、烧出无字幕视频，文件名还叫 `_subbed.mp4` —— 与「已加字幕」无法区分，于是被导出、被平台驳回。现在 `render` / `all --burn` 直接断言退出，并列出三条排查路径（没跑 align / 台词没解析到 / 对齐器不可用）。实测项目 `D:/剧本/海外剧/4` ep01：8 段里 6 段时间缺失、cues=0，被当场拦下。顺带把「分辨率路线」提示拆成「放大目标 → 交付规格」两段，此前只打「字幕画布 2560x4632」而实际交付 1080×1920，名字对不上容易误判为 4K 交付。
  ⑨ 测试：新增 `test_delivery_spec.py` **21 组**（比例容差只放宽比例、尺寸仍须精确 / SAR 59:60 判不合规 / 1062×1920 与 672×1216 均被拦 / 10bit 被拦 / 滤镜不含 pad / 横屏目标可用 / `_parse_ratio` 容错）；`test_release_export` **14 组**、`test_subtitle_alignment` **38 组**、`test_safe_area` 全绿。全量 24 个 `test_*.py` 中 21 个通过，3 个失败（`test_cover_forge` / `test_feedback_20261020` / `test_slot_hygiene`）经核查**全部因本机缺 Pillow**（`envs/default` 已不存在），与本次改动无关。**端到端实测**：真实母版 → 归一化 → 烧 7 条测试字幕 → 门禁，C1（1080×1920 SAR 1:1 显示比例 0.5625）/ C2（四边满幅）/ C3（检出硬字幕）全 PASS，抽帧复核字幕落在 60% 高。
- **2026-10-29 更新（V0.7.23 · 本地 ComfyUI 按需启动）**：用户的原话是「必须让我先打开 ComfyUI 你才能调用，能不能不点」。此前这确实是设计出来的限制 —— `health._MANUAL_WHY["本机服务"]` 写着「ComfyUI 是独立 GUI 程序，Studio 不替你拉起外部进程」，`connections._test_comfyui()` 连不上就返回「打开桌面版」，`gen_assets_local.py --check` 只打印「请先启动」。这轮把它从 manual 提升成 auto。① **能做的前提是搞清进程模型**：桌面版只是 Electron 外壳，真正的服务是 `python -s ComfyUI\main.py --port 8188 --enable-manager --extra-model-paths-config <inst-*.yaml> --input-directory … --output-directory …`；三个参数少一个就出「模型缺失」或产物落错目录。新增 `stages/assets/comfyui/comfy_boot.py`（纯标准库，引擎脚本可直接 import）负责 `discover/spawn/ensure/stop/status`，安装信息读 `%APPDATA%\Comfy Desktop\installations.json`，换实例不用改代码。② **三个入口共用一个 `ensure()`**：连接中心卡片（`GET /api/comfy/status`、`POST /api/comfy/start`、`/stop`，启动走后台线程 + 前端轮询，避免一个 90 秒请求把单进程 uvicorn 掐死）、环境体检 `svc.comfy`（`fix.kind=comfy_start`，**同步**等就绪 —— 复检要的是「现在能用了吗」）、出图脚本 `--submit/--check` 前（`--no-boot` 可关）。③ **六条边界**：只对 loopback 启动；在线一律 attach 不抢端口；端口被非 ComfyUI 占用就报错不硬起；停止只停自己启动的（要「pid 正在监听该端口」才敢 kill）；不做开机常驻；失败按日志分类给人话。④ **修 `generators.py` 硬编码 8188**：连接中心改了地址它不认，导致「界面未启动 / 实际能出图」，现改为读连接配置。⑤ `connections.env_for()` 注入 `SOLODRAMA_COMFY_AUTOSTART`，界面开关与命令行同一口径（否则界面关了、CLI 照旧拉起，用户没法解释）。⑥ **踩坑**：0.42 的 `main.py` 会再拉一个子进程 bind 端口（实测 spawn 23324 / LISTENING 8792），锁里只记 spawn pid 时 `stop()` 永远判 `not_listener` —— 现在锁同时记 `spawn_pid` 与 `pid`，就绪时回填监听者。验证：全量 **40 个 `test_*.py` 0 失败**，新增 `test_comfy_boot.py` 13 组；真机 CPU 冒烟 35.8 秒就绪、13 个自定义节点全加载、`stop` 杀掉两个 pid 并清锁；Studio 三接口与两张页面截图复核。
- **2026-10-29 更新（V0.7.22 · 助手引导）**：上轮把对话模式做出来，但用户打开抽屉只会看到一句「想看什么直接说」——**不知道能问什么、问完也不知道该点哪**。这轮把「引导」当功能做，分三层落地。
  ① **提示词升级为产品说明书**（`stages/creation/prompts/assistant-chat.md` 重写）：15 个页面的 route→中文名→什么时候去、S1–S11 与页面的对应、5 条不能给错的规矩（画风不可事后换 / 发布版唯一来源 `09-发行/剧集/EpisodeNN.mp4` / 资产必进 `04-资产` / 按段计费 27 币+1 币/秒 / 字幕必须真对齐）、80 字回答口径、6 种常见问法的写法示例，新增 `suggestions` 字段（2–3 条接话，≤18 字）。**它是产品文档，改页面就要改它** —— 这条由测试盯。
  ② **开场引导 `welcome()` + `GET /api/assistant/welcome`**（不调模型、不花钱）：按当前项目算问候（「《2、母亲之路》已完成 0/11，停在 调研」），给能力边界（「我只读状态、只给建议；花钱和写盘的按钮永远由你按」）、3 条可点 chips、页脚显示**真实**模型名（mock 时明说「离线演练」并第一条建议改成「怎么接一个大模型」）。
  ③ **`goto_hint()`：动作双来源**。用户问「现在卡在哪」，按规则模型只该回答（`action=none`），但这句话的下一个动作永远明确 —— 去卡住的那页。服务端按「第一个未完成环节」算出 `goto`（route + 中文 label + 「卡在「调研」」），前端画成次要按钮。**不经过模型，就不会幻觉**；状态读不到时返回 `{}`，宁可没按钮也不指错路。
  ④ **前端**：`actionBar(a, goto)` 两条来源分开画（主按钮=模型提案，次按钮=状态推导，同页去重）；chips 固定在输入框上方一条（`suggestions` 点一下即发送，发送时先收起旧 chips）；`navigate`/`run` 改用中文 `label`（不再显示 `assets`/`convert.apply`）；跳转后 toast。
  ⑤ **踩坑**：模型对「现在卡在哪」返回 `none` 是**符合规则**的（问状态不该有动作），但产品上这是断头路 —— 结论是「动作不能只有模型一个来源」。另外 `route` 白名单虽在前端也有映射，但两处维护必漂，改成后端下发 `label`。
  ⑥ 测试：`test_assistant` 从 4 组扩到 8 组（新增：welcome 字段与兜底、suggestions 归一化、提示词与 `ROUTES` 不漂移、`goto_hint` 与 label）。全量 **40 个 `test_*.py` 0 失败**（web 16 + 引擎 24）。
- **2026-10-29 更新（V0.7.21 · 工作流可换 / 槽位自动关 / 画风库 / 对话控制）**：用户一次提了 5 件：①本地工作流支持手动替换 ②不管本地还是 RH 都要自动识别输入节点、运行时关掉多余图槽 ③连接中心与生成通道重叠，合并 ④新建项目可选路径/画幅/分辨率/画风，并把 RH 官方 6 个风格加进默认库 ⑤接入 DeepSeek 后增加对话模式。
  ① **工作流可换**：`web/core/comfy_store.py` + `GET/POST /api/comfy/workflows*`。上传校验三条：是 API 格式（`nodes/links` 的界面导出直接拒，提示「导出 API 格式」）、有输出节点（没输出的跑完不出东西）、能描述出端口。上传件落 `web/var/comfy/workflows/`，内置只读；同名再上传先挪 `.bak_时间戳`。自动映射按端口角色生成，识别不出的**如实列出**并区分「必需（prompt/images）」与「沿用原值（其余）」。
  ② **端口识别 + 槽位裁剪**：真源 `stages/video/comfyui/comfy_ports.py`（纯标准库，可独立运行；`web/core/comfy_ports.py` 只是按路径加载，避免两份漂）。`describe()` 认两类槽写法（`image1` / `ref_images.ref_image_0`），`prune_for_refs()` **真的改图**：删多余 `LoadImage`、删多槽节点上的 `ref_image_n`、按输出做可达性剪枝。实测真实 6 槽云端工作流裁到 2：`dropped_nodes=[146,159,160,161,278]`，**零悬空引用**，原文件未被改动。客户端 `--list-ports` 可离线看端口；干跑也会打印「将关闭哪些槽」。云端 RH 只能覆盖值不能删节点，文档与界面都写明，不装样子。
  ③ **合并**：连接中心改三页签（通道配置/生成通道/出片工作流），`generators.js` 支持 `embedded` 模式（去掉自己的页头，避免一页两个大标题），顶级导航删掉「生成通道」，`#/generators` 保留为旧链接。
  ④ **画风库**：`configs/styles.json` 收录 6 个官方风格（提示词为原文），按语义挂到 `live_action`（4 个）与 `2d_animation`（2 个）轨道；`style_gate.style_lib()` 读它并 `_merge_style_lib()`，确认画风时写 `style_prompt`/`style_name`。新建项目接口加 `resolution/style/track`，建档后调 `drama style set` + `project_setup set --resolution`，**回读文件验真**（rc=4 是「等待确认」，不是失败）。
  ⑤ **对话**：`web/core/assistant.py` + `/api/assistant/chat` + 顶栏「助手」抽屉。用途 `assistant.chat`（新增提示词 `assistant-chat.md`）。服务端只出提案：`navigate` 走前端白名单、`run` 走 `pipeline/run` 的 `only=` 且必须过确认，计费命令**代码里就不在白名单**；模型不按 JSON 回时整段当回答、动作置空。实测三句行为正确（问进度→none；要资产→navigate；跑分镜→反问并说明不替你按）。
  ⑥ **踩坑**：加子模式没给默认值 → `style set live_action` 报「未知子模式 None」，连带 12 个引擎测试挂；`llm_gateway.complete` 不存在（是 `get_gateway().complete`）；模板数量断言写死 7 会被新增用途打红，改成「≥7 且每个用途都有模板」。
  ⑦ 测试：新增 3 个文件（`test_comfy_ports` 7 组、`test_workflow_store` 6 组、`test_assistant` 4 组），全量 **41 个 0 失败**。
- **2026-10-29 更新（V0.7.20 · 可读性 / 动效 / 打开速度）**：用户反馈「按钮太小、字太小、切换没动效、模块打开慢」，并要求先装个设计类 skill 再做。已装 `ui-design-library`（Emil Kowalski 的动效准则）与 `ui-design-system`，按前者的规矩落地，不是凭感觉调数值。
  ① **字号**：正文 13→15、元信息 11→12、小标题 14→16、页面标题 20→24、KPI 26→32；`--row-h` 36→44、`--top-h` 56→60、`--nav-w` 232→252。**不做等比 ×1.15** —— 那样「都变大了」但主次更糊，层级要靠差值。全部走 `tokens.css`，一处改完全局生效（此前只有 6 处硬编码 10px，这轮一并清到 12px）。
  ② **按钮**：`.btn` 30→36、`.lg` 36→44、`.sm` 24→30、`.icon` 28→36，新增 `.btn.stage`（34px）。**流水线 11 行每行补按钮**：可自动→「运行此步」，需人工/被挡→「打开页面 / 去补齐」；配套 `/api/pipeline/run` 新增 `only=<Sx>`（**只跑这一条**，否则点 S10 会把前 9 步跑一遍）。顺带修 `MANUAL_HINT` 里 S3 的 page 写成 `asset`（前端路由是 `assets`，点了会落空）—— 这个字段此前从未被消费，接上按钮才暴露。
  ③ **动效**（四条规矩：只动 transform/opacity、入场 ease-out、高频 ≤120ms、reduced-motion 全关）：视图切换 6px 上移 + 淡入 180ms；卡片首层错峰 30/60ms；按钮 `:active` 下压 1px；主按钮按指针位置做径向高光（`--mx/--my`，即「鼠标流动」，只给主按钮——高频小按钮上做跟随会让人手忙）；顶部进度条**延迟 200ms 才亮**（快请求闪一下比不闪更烦）。
  ④ **速度**：慢的根因是每个重接口都起 Python 子进程（workflow 0.5s、setup 0.5s、env 1.3s）。三层处理：后端 TTL（12s/20s/60s）、前端 `api.js` 只读重接口短缓存（**写操作后整体 clear**）、首屏三项改 `Promise.all` + `requestIdleCallback` 预取。实测：项目详情 970→5ms、生成通道 669→4ms、环境体检 1281→2ms；前端用 fetch 计数验证「连续三次调用只发 1 次请求，写后第一次读必发」。
  ⑤ **放大字号暴露的两个真缺陷**：设置页长路径顶穿卡片（环境行是 flex，span 不收缩；`.kv` 又写死 `max-width:720px`）→ 改两列栅格 + `minmax(0,1fr)` + `overflow-wrap:anywhere`，≤1500px 环境项改上下排；`nth-of-type` 错峰在混排容器上会失效（无功能影响，已记录）。
  ⑥ **测试**：`test_studio_assets` 新增第 7/8 组（可读性下限、动效与缓存纪律：TTL 表不许出现 `/api/jobs`、`@keyframes` 只许 transform/opacity、必须能 reduced-motion）；`test_pipeline` 新增第 5 组（`only=` 只跑指定环节）。全量 38 个 0 失败。
- **2026-10-29 更新（V0.7.19 · 项目图标：竖屏画幅 + 播放）**：用户要「给项目生成一个 logo，用于项目图标」。此前侧栏是 `SD` 文字占位、浏览器标签是默认图标（全站无 favicon），这一轮把图标做成可复现的资产链。
  ① **真源 `tools/make_logo.py`**：几何（`FRAME = (18,6,28,52,7)`、`PLAY`）与配色（`AMBER #E0A458` / `INK #171A1F`）都在文件头常量里，改完跑一遍即重出 12 个文件，避免「改了 SVG 忘了 PNG」。产物进 `web/ui/studio/img/`：`logo.svg`、`logo-mark.svg`、`logo-mark-light.svg`、`logo-square.svg`、`logo-maskable.svg`、`icon-192/512.png`、`icon-maskable-512.png`、`apple-touch-icon.png`、`favicon-16/32.png`、`favicon.ico`（Pillow 打包 16/32/48/64）。
  ② **图形语言**：竖屏画幅（28×52，9:16）里挖一个播放三角 —— 短剧的本体是竖屏，不是加个播放键。三角用 `fill-rule="evenodd"` **挖空**，不是再叠一个琥珀三角：后者换底色就露补丁，而且 PNG 边缘会出现色差。
  ③ **选型是量出来的**：做了 4 轮对比页（描边取景框 / 闭合框穿透 / 竖屏描边 / 圆环开口 / 实心竖屏 / 方折 S / 叠片），每轮都在 256/96/48/32/16px 下看，并对 16px 做 8x 最近邻放大验像素。结论：**描边风格在 16px 必糊**（线宽 5/64≈1.25px，框与三角粘连）；齿孔、字幕条在 48px 以上加分、32px 以下成噪点；第一版三角 tip 距右边框仅 1px（≈0.25px@16px）看着像连体 —— 最终只留两个形，四周留 5–7px 琥珀边。
  ④ **接进产品**：`index.html` 加 SVG favicon + PNG/ICO 兜底 + `apple-touch-icon` + `manifest.webmanifest` + `theme-color`；侧栏 `.brand-mark` 换成 `<img src="img/logo.svg">`，并**删掉 CSS 里的琥珀底与圆角**（否则图标外多一圈方框，且与 favicon 不是同一个东西）；旧控制台 `/ui/index.html`、`/ui/advanced.html` 与 README 首图同步。
  ⑤ **两个平台细节写进自检**：iOS 主屏图标必须**实心方底**（透明角会被系统填黑）→ 用 `logo-square.svg` 出 180×180；PWA maskable 把 mark 缩到 80% 留安全区 → `logo-maskable.svg`。
  ⑥ **MIME 钉死**：`.webmanifest → application/manifest+json`、`.ico → image/x-icon`。Windows 上 `mimetypes` 会读注册表，Chrome 对错误 MIME 的 manifest 直接忽略（不报错，只是「添加到主屏」失效）。
  ⑦ 测试：`test_studio_assets.py` 增第 6 组（12 个文件存在非空、`index.html` 引用的图标/清单必须存在、manifest 合法且 icon src 存在 + 含 maskable、品牌区不许退回文字占位、`logo.svg` 主色必须等于 `tokens.css --accent`）。全量 **38 个 `test_*.py` 0 失败**。
  ⑧ 实测：`curl` 四个资源均 200 且 MIME 正确；侧栏展开/折叠两种状态截图复核无多余边框；`tools/make_logo.py --out <临时目录>` 重跑，与仓库内 12 个文件**逐字节一致**。
- **2026-10-29 更新（V0.7.18 · 环境体检 + 一键修复）**：用户要「检测发现缺什么环境配置，能一键安装/修复」。诊断侧已有 `tools/env_check.py`（`--fix` 只打印命令），本轮把它做成产品闭环：`web/core/health.py` + 页面 `#/health`。
  ① **15 项体检**：`env_check --json` 的 12 项（Python / 虚拟环境 / 解释器 / Pillow / httpx / ffmpeg / ffprobe / whisper-cli / RUNNINGHUB_API_KEY / RUNNINGHUB_BASE_URL / ComfyUI 8188 / manifest）原样接管并归一 id（`dep.pillow`、`bin.ffmpeg`…），另加三项 Studio 自有：`dir.var` 与 `dir.llm` 是否可写、`rt.engine_py` 是否被配置指到空文件（`paths.engine_python()` 会**静默回落**，用户根本发现不了）。
  ② **只自动修三类，其余如实标人工**：`pip`（`[engine_python, -m, pip, install, <requirements 里的锁定版本>]`，禁止 `--user` / `--break-system-packages` —— 那会装到引擎读不到的地方）、`mkdir`（只建 `web/var` 与 `web/var/llm`）、`config`（清掉 `configs/settings.json` 的失效 `python`，写前备份、其它键原样保留）。`manual`：winget 装 ffmpeg（要 UAC）、启动 ComfyUI（外部 GUI 进程）、manifest 不符（那是「仓库被改过」不是「环境缺东西」）；`page`：填 Key（跳连接中心，Key 不走环境变量）。每类都带一句「为什么不能自动」——只说「需人工」等于没说。
  ③ **三条纪律**：**动作白名单在服务端**（`POST /api/health/fix` 只收 `fix_id`，命令由 `_fix_spec()` 现算，前端传不进一条命令）；**复检才是结论**（命令 rc=0 ≠ 这一项能过，修完重跑 `collect()` 取同一项，不过就 `ok=false` + 「命令跑完了，但这一项复检仍未通过」）；**留痕**（`web/var/health-fixes.jsonl`，页面底部「修复记录」显示时间 / 项目 / 动作 / 复检 / 命令）。
  ④ **修掉自己埋的坑**：`_writable()` 最初用「建探针文件再删」判断可写，而 `mkdir(parents=True)` 顺手把目录建了 ⇒ `dir.var` 永远判通过、一键修复成摆设，且 GET 有副作用。改为「存在 + `os.access(W_OK)`」，建目录只由修复动作做。
  ⑤ **实测**：临时 venv（不碰真实环境）复现缺依赖 → 体检报 `Pillow 缺失 · 2 项可一键修复`、页面显示红色「缺失」+「一键修复」+ 将执行的命令 → `POST /api/health/fix {id:"dep.pillow"}` **2.64s**（走 pip 缓存）装好、复检 `已装 12.2.0`、httpx 3.46s；修复记录表两行「已通过」。非自动项（manifest）调 fix 返回 `reason=not_auto` 且无任何执行输出。
  ⑥ 测试 `web/tests/test_health.py` 7 组（含「命令成功但复检不过必须返回 false」这类反向断言）；全量 **38 个 `test_*.py` 0 失败**。系统设置页新增入口按钮。
- **2026-10-29 更新（V0.7.17 · 流水线模式：连跑 + 预算内自动放行）**：用户问「为什么没有流水线模式的开关」—— 翻遍代码确认确实没有，只有 G-0 配置项里出现过「流水线预算」四个字，11 个环节只能各自去对应页面点。本轮补上：`web/core/pipeline.py` + `#/pipeline` 页面。① **两种模式**：逐步确认（`max_steps=1`）/ 连跑（最多 6 步）。② **三条硬纪律**：不猜（`STAGE_MAP` 只登记语义确实等价的命令：S1 market.template、S2 script.plan、S4 assets.local、S5 convert.apply、S6 video.plan、S8 media.assemble、S9 media.master、S10 media.render；没登记的 S3/S7/S11 标「需人工」并给出页面）；计费可估才放行（`est_coins` 已知且累计+本步 ≤ 预算，否则 `ask`；**估不出来一律停**，不猜金额）；前置未齐不动手（引擎 probes 的 `found/need` 未过即 `blocked`，不跳过不硬跑）。③ **参数解析 `_values_for()`**：`assets.local` 只认 `SOLODRAMA_ASSET_MD`，自动从 `studio.asset_mds` 找「资产提示词 md」并注进 `env_for`；找不到就判 `ask` 并说明要准备什么 —— 不给空值硬跑，否则会被误读成「ComfyUI 没开」。④ **接口**：`GET /api/pipeline/plan`（只读）、`POST /api/pipeline/run`（默认 dry_run，`_write_guard`）。⑤ **修一个隐蔽 bug**：旧 `/api/pipeline` 的处理函数名就叫 `pipeline`，在模块级覆盖了 `from core import ... pipeline` 的模块对象，新接口一调 `pipeline.plan` 就 `AttributeError` → 500；改名 `legacy_pipeline` 后正常（教训：新增同名模块前先 grep 有没有同名路由函数）。⑥ 测试：新增 `web/tests/test_pipeline.py`（4 组，离线，用假 probes 注入 `adapters.workflow_status` 与 `norm_workflow`）；全量 37 个 0 失败。⑦ 实测真实项目：11 环节 → 可自动 0 / 需确认 0 / 被挡 8 / 需人工 3（该项目 `video-pipeline/` 下只有 output，缺 data 与剧本）。
- **2026-10-29 更新（V0.7.16 · 本地出片改数据驱动：换工作流不用改代码）**：① **节点映射外置**：新增 `stages/video/comfyui/workflow_h3_local.map.json`，把 `prompt / images / seconds / steps / seed / aspect / prefix` 七个角色的节点 id 从脚本常量搬到 JSON；默认按约定读**同名 sidecar**（`xxx.json` → `xxx.map.json`），优先级 `--map` > sidecar > 环境变量 `COMFYUI_VIDEO_NODE_*` > 内置默认。上一版这七个 id 写死在 `comfy_local_video.py` 顶部，换一份工作流就得改 Python，换机器/换流程都别扭。② **两个离线工具**：`--list-nodes` 列出每个节点 id / class_type，并按 `MAP_ROLES[*].expect` 标出「它适合当哪个角色」（未映射的显示「（可作 xxx）」），用户照抄即可写映射；`--map-check` 逐个校验映射的 id 是否存在于工作流、class_type 是否在允许集合内。**为什么必须有一条**：映射 id 写错时脚本不会报错、能正常提交、GPU 也会跑完，但参数全落在没人读的节点上 —— 产出是默认参数的片，等于白等几分钟；`--map-check` 在花 GPU 之前就能 100% 抓出来。③ **非 API 格式拦截**：`load_workflow()` 现在要求「每个值都是带 `class_type` 的节点」。ComfyUI 界面直接导出的 workflow 是 `{"nodes": [...], "links": [...]}`，同为 dict，旧检查会放行，然后在后面报一堆「节点 id 不存在」，把人误导向映射；现在直接提示「需要用导出 API 格式」。④ **命令层开放**：`video.local` / `video.local.check` 增加 `--workflow` / `--map` 两个参数；新增 `video.workflow.nodes`（`argv=["--list-nodes"]`）与 `video.workflow.mapcheck`（`argv=["--map-check"]`），都是 sync 只读、不占 GPU、不连 ComfyUI 也能跑（`--list-nodes`/`--map-check` 纯读文件）。`video.local` 的 `steps` 参数默认值去掉 —— 留空即沿用工作流里的值，避免页面把用户调好的 4 步冲成代码默认。⑤ 文档：`web/STUDIO.md` §9.3 新增「怎么换工作流（不用改代码）」的三层表 + 四步流程 + 两条命令的对应关系，原「已知限制」顺延为 §9.4。⑥ 测试：新增 `stages/video/comfyui/tests/test_workflow_map.py`（5 组，全离线子进程跑真实 CLI）：自带映射必须通过、映射 id 写错必须非零退出并说「不存在」、换工作流时同目录 sidecar 被自动识别且类型不符给 `[? ]`、界面格式被挡住、`--list-nodes` 离线可用。全量 **36 个 `test_*.py` 0 失败**。
- **2026-10-29 更新（V0.7.15 · 本地视频通道 + RH 图像工作流区分文生图/图生图 + 生成通道台账）**：① **本地出片落地**：新增 `stages/video/comfyui/comfy_local_video.py` + `workflow_h3_local.json`，走本机 ComfyUI 跑 MiniMax H3 图生视频。工作流直接采用用户本机在用的「minimax 多参(4步采样)」：`Cobijada_H3_Hybrid_Uncensored_pruned_hybrid_int8_convrot_pruned` + `qwen3vl_32b_minimax_h3_int4_convrot` + `minimax_h3_video_vae_int8_convrot` + `lightx2v turbo 4step` LoRA（strength 0.75），**`SolAttnMiniMax` 加速节点保留、`BasicScheduler.steps=4`**（上一版我按云端图移植的那份缺 `selection` 参数，在本机直接 `TypeError`，已废弃）。实测（RTX 4060 8G / ComfyUI 0.42.1 / 空闲显存仅 0.6G）：5 秒 16:9 0.6MP → **283 秒 / 2.0MB / 1056×608 / 24fps / 124 帧**，抽帧人工复核人脸与场景正常；主要耗时是 unet 冷加载 offload，不是采样。客户端纪律与出图一致：纯标准库、默认 dry-run、`--check` 逐项核对「ComfyUI 在线 + 每个 class_type 可用 + 每个模型文件存在」，**`--seconds/--mp/--aspect` 不传就沿用工作流原值**（不覆盖用户调好的 0.6MP/16:9）。节点映射收在文件头 `NODE_*` 常量（可被 `COMFYUI_VIDEO_NODE_*` 覆盖）。② **RH 图像工作流分模式**：`gen_assets_rh_workflow.py` 增 `--mode t2i|i2i` 与 `--ref`。文生图取 `image_providers[active].id`；图生图取 `id_i2i`，并**先上传参考图**、把返回的平台 `fileName` 写进 `nodes.image.nodeId` 指定槽位。关键裁决：**两个 id 互不兜底** —— 拿 t2i 工作流硬套图生图不会报错，而是静默忽略参考图（钱扣了、图还是纯文生图），这比报错更贵。缺 `nodes.image.nodeId` 时直接判「待配置」。快照文件 `docs/asset-wf-nodeinfo-*.json` 里补记 `mode` 与所用 `id`，事后能查「这次到底走的哪套」。③ **生成通道台账**：新增 `web/core/generators.py` + `GET /api/generators?ws=`，只读现算六条通道（`image.local.t2i/i2i`、`image.rh.t2i/i2i`、`video.local.i2v`、`video.rh.workflow`）的真实状态：ComfyUI 是否在线（`/system_stats`，30s 缓存）、工作流文件是否存在与节点类/模型是否齐全（`/object_info`，300s 缓存）、项目 `config.local.json` 里的工作流 ID 与节点映射是否齐。状态分 `ready / config / offline / missing / unsupported / no_ws`，每条都给「下一步」并点名缺哪个文件/哪个键。④ **新页面「生成通道」**（`web/ui/studio/js/views/generators.js`）：图像、视频两张表，文生图与图生图**分行显示**（这是本轮的产品诉求）；右上「配置云端工作流」把「文生图 ID / 图生图 ID / 提示词节点 / 加载图像节点」四个值写进项目配置，走 `POST /api/generators/rh`：`_write_guard()` 保护、只改 `image_providers[这一条]`、其余键原样保留、**写前自动备份**、`i2i` 填了却没给节点 id 直接 400。⑤ **新命令**：`assets.rh_wf`（RH 工作流出图，★计费，默认干跑）、`video.local`（本地出片，￥0，默认干跑，`steps` 默认 4、时长/分辨率留空即沿用工作流）、`video.local.check`（体检，sync 只读）。⑥ 测试：新增 `web/tests/test_generators.py`（6 组：t2i/i2i 各取各的 id 且不串、只配 t2i 时 i2i 必须是待配置、有 id_i2i 但缺「加载图像」节点仍待配置、本地通道区分「ComfyUI 没开」与「工作流缺文件」、缺模型时点名文件、未选项目时云端通道不许假装可配置）。全量 **35 个 `test_*.py` 0 失败**。⑦ 文档：`web/STUDIO.md` 增 §9「生成通道」（通道表 / 为什么 t2i 与 i2i 必须分开 / 本地出片的实测口径 / 已知限制），页面矩阵补「生成通道」行。
- **2026-10-28 更新（V0.7.14 · 真实大模型接通 DeepSeek + 推理模型适配 + 深链修复）**：① **真因不是「出网受阻」**：旧的 `openai-env` provider 端点已是 `api.deepseek.com/v1`，但 `env_var` 绑着 `OPENAI_API_KEY`（属于 `api.commandcode.ai` 平台的 Key，打码 `user…qXud`），于是拿别人的 Key 敲 DeepSeek，稳态 401；`OPENAI_BASE_URL` 又指着 `api.commandcode.ai/provider/v1`。换成本机 Key + 官方端点后一次通过。② **可用模型 id**：`deepseek-flash`、`deepseek-v4-pro`；`deepseek-v4.1-flash` 之类是**平台侧别名**，API 返回 `400 invalid_request_error: The supported API model names are …`。`store.PRESETS` 的 DeepSeek 预设同步改掉（原来写的是不存在的 `deepseek-chat`）。provider 配置取 `capabilities=["json"]`（不虚标 vision/tools）、`timeout_s=120`（推理模型首字慢）、`max_retries=0`（重试会重复计费）；Key 只进 `web/var/llm/keys.json`。③ **推理模型的两个坑（本轮主要代码改动）**：(a) **思考计入 max_tokens** —— 给 8-16 token 时回包 `HTTP 200` + `content:""`，旧实现报成 parse（「输出不是合法 JSON」），把人带偏到提示词上。`errors.KINDS` 新增 `truncated`（`finish_reason=length`）与 `empty`（内容策略/模型没话说），`providers.OpenAICompatible.chat()` 在 content 为空时按 `finish_reason` 分流，并把 `finish_reason` 放进 `ProviderResult.extra`；探针额度 8→64（`connections._LLM_PROBE_TOKENS`，`gateway.probe` 同改）。(b) **数值预算写不进 Schema** —— 实测模型写出 90 秒的「60 秒档」。新增 `web/core/llm/budget.py` 作为镜数/时长边界的**唯一真源**（优先问引擎 `script_rewrite.py.bounds_for()`），`templates.render_parts()` 把边界写进 user 段，`drafts.bounds_for()` 改为委托同一函数；`drafts.py` 里重复的 `_SECONDS` 常量已删（死常量就是漂移源头）。④ **字段填写约定 `SCHEMA_NOTES`**：无台词的镜头 `dialog` 写「无」而不是空串（引擎 lint 用 `^DIALOG\s*:\s*(.+)$` 判定）、`char` 只能用 HEADER 已登记代号；Schema 校验失败时用 `FIELD_HINTS` 追加「怎么改」。实测补上后引擎 lint 的两条 WARN（dialog 为空、CHAR 未登记）归零。⑤ **深链工作区修复**：`GET /?ws=<剧目录>` 的 307 目标是 `/studio/`，**查询串被丢掉** ⇒ 书签永远打不开指定项目，前端只能退回注册表 `current`（用户以为开 A 实际是 B，且后续操作会改写 `current`）。现在带住 query，且无 query 时不硬拼 `?`。⑥ **注册表写盘剥计算字段**：`_i_workspaces()` 会往 items 贴 `exists/images/loose/yuan/has_output…`，自愈写盘时一并落盘 ⇒ 下次读到过期快照（`images` 越写越旧、删掉的目录仍显示存在）。新增 `_registry_clean()`，4 处写盘点统一走它；本机被污染的 `registry.json` 已归一化。⑦ **探测头条认真实通道**：`_test_llm()` 原来取 `good[0]`，Mock 排前面时界面写「离线演练可调用 · 实测 2/2」，看起来像没接通。现在探针按「云端 > 本地 > Mock」排队（名额不被 Mock 占掉），头条只认真实通道，并说明「另有 N 个本次未测」。⑧ **验证工具自身修复**：`verify_llm_loop.py` 第 7 步硬编码断言「演练草稿必须被拒」，用真实提供商跑必然 NG；改为两种通道都额外造一个 `simulated=true` 的草稿撞门禁，真实通道再断言「可直接落盘」。实测：**34 个 `test_*.py` 全绿**；`verify_llm_loop.py --llm-dir web/var/llm --provider deepseek --confirm-cost` **28/28**（27s），引擎 `script_rewrite.py lint` rc=0（8 镜 / 70 秒）；AI 模型中心可用用途 **7/7**。
- **2026-10-28 更新（V0.7.13 · 登记表自愈 + 散图口径统一 + 本地出图首次真跑通）**：① **「当前工作区」会指向已删除目录**（真机复现）：`web/var/registry.json` 的 `current` 停在已删除的 `D://剧本//海外剧//3`，而 `_i_workspaces()` 原有一段 `for extra in (reg.get("current"),)` 会把它**塞进 items 伪造成项目卡片**，前端 `store.loadProjects()` 又直接 `d.current` 采信 ⇒ 整个应用带着不存在的目录请求所有接口，页面全空且无报错。修法：删掉伪造逻辑；`current` 失效时自愈到「第一个真实存在且带 `layout.json`/`model-plan.json`/`video-pipeline` 的项目」并 `write_json` 落盘；响应新增 `current_exists` / `stale` / `current_replaced`（只回传不落盘）；`_registry()` 的空值兜底也改成只挑真实存在的项。前端 `loadProjects()` 双保险：只接受存在于可用列表里的 `current`，否则回落第一个可用项目、全无则清空（并清掉 localStorage 里的死路径）。② **失效条目可清理**：新增 `POST /api/workspaces/prune`（`_write_guard()` 保护，只删注册表条目、**绝不删磁盘**），项目页顶部出警示条「有 N 个登记目录已经不存在（…）」+「从清单里移除」。此前前端只渲染 `exists` 为真的项，于是「登记了 4 个、只显示 2 个」，且没有任何入口能去掉死条目。③ **散图计数统一到所有口径**：`inventory._inventory()` 增 `images.loose`（直接复用 `artifacts.loose_images()`，与资产页第 5 页签**同一函数**，不再各写一套）与 `images.all = total + loose`；`has_output` 计入散图；`discover()` 每项带 `loose`。消费端全部改成 `images + loose`：`projects.js`（卡片/表格/排序/扫描抽屉）、`workbench.js`（项目表）、`main.js`（顶部项目条）、`overview.js`（项目详情「图片」行改为「N 张（角色 x / 场景 y）· 另有 N 张散图」）、`ux.py`（用户端首页加「还没归档的图（散图）」一行，`counts.images` 改用 `images.all`）。`images.total` 语义**保持不变**（仍有断言依赖）。④ **本地 ComfyUI 首次真实出图**（此前只验过连接与离线路径）：队列空闲时以 `comfy_client.py` 提交 Qwen-Image 2.1，preflight 逐项核对工作流节点（`KSampler` 8 steps/cfg1、`TextEncodeQwenImage21`、`ResolutionSelector` 2:3 @2.2MP、`UNETLoader qwen_image_2.1_int8_convrot` + `LoraLoaderModelOnly …turbo-4step`、`CLIPLoader qwen3vl_8b_int8_convrot`、`VAELoader qwen_image_2.1_vae_bf16`）与实际可用模型清单一致；实测 **2 分钟出 1248×1856 / 3.6MB PNG / ￥0**，画面为目标场景且人脸无畸变（唯一瑕疵：霓虹招牌文字是乱码，属模型固有）。⑤ 测试：新增 `web/tests/test_workspaces.py`（4 组，覆盖自愈落盘、不伪造卡片、全盘皆死置空、prune 不碰磁盘），`test_inventory.py` 新增 `[5] 散图口径`（根 2 + 子目录 1 = 3，工程目录与非图片不计入，`total` 仍为 0）。全量 **34 个 `test_*.py` 0 失败**。⚠ 仍未做：真实云端大模型未接入（本机没有可用的第三方 Key，用途自动选路落到 Mock）。
- **2026-10-28 回填（V0.7.12）**：内容提交 `b98e0b7`（远端 `f4a8c66` → `b98e0b7`，快进）；本条仅改 `README.md` / `VERSIONS.md` / `manifest.sha256`。
- **2026-10-28 更新（V0.7.12 · 三通道接通：大模型真实探测 + 用途自动选路 + 资产可见性）**：① **大模型探测改成真发请求**：旧 `_test_llm()` 只判「有没有 provider / Key」，于是 Key 过期、模型改名、`base_url` 少 `/v1`、代理拦截四种情况一律显示「可用」——用户要到写剧本时才知道不通。现在复用网关同一个 `providers.build(cfg, key).chat()` 发 1 token 级请求（`_LLM_PROBE_MAX=2` 控成本、`_LLM_PROBE_TIMEOUT=20s`），逐提供商返回 `ok/kind/ms`，失败按 `core/llm/errors.KINDS` 映射下一步话术（`auth`→重抄 Key、`model_not_found`→核对模型与 `/v1`、`quota`→充值…）。② **`has_key` 摊平 bug**：`store.public_provider()` 为 `out.update(key_status(prov))`，`has_key` 落在**顶层**；`connections` 原先读 `p["key_status"]["has_key"]` 恒 None ⇒ 「填了 Key 仍显示缺 Key」。新增 `_prov_has_key()` 兼容两种形态，且 `mock/ollama` 不需要 Key（判断顺序：先看 kind，再看 has_key）。同一 bug 的连带修复：`_llm_providers()` 的 `has_key` 也从恒 False 变为真实值。③ **用途自动选路（`store.auto_provider`）**：按「有 Key 的云端(3) > 本地(2) > Mock(1)」排序，尊重 `requires` 能力、跳过停用与无 Key；`list_purposes()` 与 `get_purpose()` 共用它，所以「界面说会用谁」与「网关实际用谁」不会分叉。显式绑定仍最优先，`bound=False`+`auto=True` 表示系统代选。前端用途表状态列显示「自动：<名称>」，KPI 由「已绑定用途」改「可用用途」。④ **资产散图**：`artifacts.loose_images()`（只读）扫根目录 + 一层子目录，跳过 `04-资产`/`06-提示词`/`07-成片`/`08-成片`/`09-发行` 与 `video-pipeline`/`logs`/`db`/`tools`/`workflows`；新增 `GET /api/artifacts/loose`、资产页「散图」页签（含「21 张 · 根目录 20 · 分镜 1」计数）、「角色资产」KPI 注释补「另有 N 张未归档」。**产品不移动用户文件**（归档由用户决定）。⑤ **工作台口径统一**：`channelCard(ctx, setup, providers, purposes, conn)`，三路机器级通道读连接中心 `last_ok/last_detail/last_test`，`workflow_api` 仍读 G-0 且无项目时明示「未选项目」；原 `#btnComfyProbe`（跑 `diag.comfy` 出抽屉）删除，改为 `[data-probe]` 调 `/api/connections/comfyui/test`，结果由后端持久化 ⇒ 卡片与连接中心永不打架。⑥ 资产页页签写 URL（`currentTab()`，与 `models.js` 同写法）；`connections.js` 去掉 `COMFYUI_URL` / `RUNNINGHUB_API_KEY` 等变量名（改为「出图任务启动时自动带上」），因 `test_studio_assets.py` 明令「前端不得出现密钥字段」，本轮被它拦下后改正。验证：全量 33 个 `test_*.py` 0 失败；`test_connections.py` 10 组（6 旧 + 7 凭据摊平 + 8 自动选路 + 9 用途就绪 + 10 真实探测）；`test_llm_e2e.py` §4 由「未绑定应报 config」改为「未绑定不得因没绑定失败、且 `auto=True && ready=True`」；真实项目实测：散图 21 张、`/media` 返回 200 + `image/png` + 3.7MB、连接中心 `llm ok=True（Mock 回包 {"ok": true}）/ comfyui v0.42.1 / runninghub 36 币`。⚠ 未做：真实云端模型（DeepSeek 等）未接入 —— 本机无可用的第三方 Key；ComfyUI 侧当时有他人任务在跑（`queue_running=1`、显存剩 0.59G），故未提交真实出图。
- **2026-10-28 更新（V0.7.11 · 叙事模式裁决：对白驱动）**：用户判定「旁白解说太单调」，要求把 `3d-short-drama-studio` 的**剧本解析 / 分镜设计 / 台词设计 / 视频提示词**四环节融合回来，并明确「走对白驱动、只改 agent 项目、不动短剧项目、不改其它环节引擎」。① **先做性质更正**：逐层核对代码后确认，2026-10-16 的「画风三轨接管分镜 / H3 提示词」**只是文档声明**，执行链路从未改口径 —— `workflow.py` S5 的 `what` 仍写「分镜（11 字段）→ H3 六段式提示词 → 转换四文件」，`convert_storyboard.py` 的输入契约仍是 md（`## shot_NNN` + `prompt`），`script_continuity.py` 解析的仍是 `subject_definitions`+`summary` 六段；而画风三轨的 `storyboard.json` **没有生成器**（全仓只有 `half_narrated_check.py` 读）、**未挂进 workflow/pipeline**，`style_gate.py` 写进 `style-plan.json` 的 `shot_duration` 也只有 `half_narrated_check.py:76` 在用。② **技能侧**（`~/.dsh/skills/3d-short-drama-studio`，WorkBuddy 经符号链接加载）：撤销 description 里的接管声明；新增 `references/dialogue-driven-rules.md` 作为叙事单一真源（载体优先级「能说就说→说不出口才演→演不出来才旁白」、旁白四合法用途与五条禁令、台词四功能与三拍、分镜信息事件与反应镜交替、H3 一段一 `<d>`、自检 10 问）；`SKILL.md` 新增「叙事模式：对白驱动」节（硬指标表 + 四职能引擎落点 + FFS 落盘映射），流程表改为 1 剧本解析 / 1.5 台词设计 / 4 分镜设计 / 5 视频提示词；`screenwriter-a|b|b-es` 加铁律第 0 条与台词密度（质量门 9→11）；`director-storyboarder` 明确「1.5–3s 是**段内切点**不是生成段」并新增 §4.1 与 `## shot_NNN` 的机器层映射（质量门 15→17）；`h3-prompter` 新增 §5.4 对白驱动装配、`non_diegetic_music` 改一律 `N/A`（铁律 8→9、质量门 16→18）；`director-core` 立项五→六项（叙事模式写死对白驱动）并加「旁白 vs 对白→删旁白」裁决；`dialogue-auditor` 加四功能审核（无功能判删，不润色）。③ **文档侧**：`README.md`（画风=皮/叙事=骨、`halfcheck` 标可选、文档索引分两行）、`docs/styles/画风三轨规范.md`（标题去「半解说」、§四 由「替换说明」改「与 3D 技能的分工」、交付终点与旁白包改「仅在确有旁白时」）、`docs/orchestration/生产流程总纲.md` §3.0（半解说四件套 → 叙事模式：对白驱动）、`docs/orchestration/技能映射与缺口.md`（二之二改「分工」、G10 加边界注）。④ **未做（显式声明）**：`storyboard_to_units.py`（剪辑镜→`U##`→`shot_NNN`）与 `h3_prompt_lint.py`（六段式结构校验）属引擎代码，按「不改引擎」跳过；`~/.hub/skills/half-narrated-*` 未移动 —— 它不在 WorkBuddy 加载路径，替换发生在规范引用层。验证：无引擎代码改动，离线基线不变（31 个 `test_*.py` 全绿，2026-10-23）；短剧项目零改动。

- **2026-10-23 更新（V0.7.10 · Web 工作台 Studio + LLM 统一网关）**：`/` 自动进 Studio，`/ui/` 保留旧控制台，端口 8788。① 前端 `web/ui/studio/` 12 视图（ES module、零构建、零外链，删目录即回滚）；后端 `web/core/studio.py` 聚合读、`adapters.py`（CLI 输出→结构化）、`artifacts.py`（路径白名单 + 媒体流 Range）、`jsonout.py`（唯一 JSON 抽取）。② `web/core/llm/` 8 模块统一网关：业务只调 `gateway.complete(purpose, variables)`，**提示词不另写**（system = 仓库 `stages/creation/prompts/*.md` 原文，带 `body_sha`），能力不满足**拒发**，重试只对 timeout/network/rate_limit/5xx，金额只认供应商 `usage.cost`，Key 只进不出。③ **生成与落盘彻底分离**：生成只写 `<ws>/video-pipeline/llm-drafts/`，`confirm` 才写 `03-剧本/ep_NN.md`（显式 `overwrite` + 备份 + `expected_sha`）；**计费接口一律 428 + `confirm=true`**；项目创建单独走 `/api/projects/create`（`/api/run` 要求 ws 已存在）。④ 已修的旧缺陷（勿回退）：`/api/episodes` 恒空、跨批次 totals 相加、字幕用 `subs/` 文件数判完成、`reader.ROUNDS/EVIDENCE` 自造判据。⑤ `httpx==0.28.1` 进 `web/requirements-web.txt`（与引擎同版本）。说明真源 `web/STUDIO.md`。
- **2026-10-22 更新（V0.7.9 · H3 参考图槽位卫生）**：用户报告「调用 RH 视频工作流时，工作流默认打开的 6 张图会被当参考放进去」。实测**确认，且比报告更重**。根因：`nodeInfoList` 是**覆盖表不是完整表** —— 没发的节点，平台沿用工作流里保存的那个值。只读接口 `getJsonApiFormat` 拉回该工作流 31 个节点，`MiniMaxH3ReferenceToVideo`(136) 有 `ref_image_0…5` 六个 `LoadImage`(137/139/146/159/160/161)，项目 `config.local.json` 只覆盖 3 个（角色 137、场景 139+159）⇒ **146/160/161 每镜都在送同一张遗留图 `cb955bf6….png`**。旧代码注释里「不发 = 沿用内置默认，安全」的判断是错的，已删并写明。连带后果：模型一直按 6 路参考图推理，而 `OOM_RETRY` 注释早就写着「12 秒 + 6 路参考图在 24G 实例必 OOM」—— 其中 3 路是废物，顶掉后参考图降到 3 路。修法：`pipeline.py` 新增槽位卫生（`is_image_slot` / `image_slot_nodes` / `covered_slot_ids` / `placeholder_png` / `SlotGuard` / `make_slot_guard`），运行开始时用只读接口探测全部图片槽（免费、不排队、落 `slots_<key>.json` 供 `--dry-run` 用），把未覆盖槽位显式填 1024×1024 中性灰占位图顶掉；`mode` 三态 blank（默认）/ empty（传空，LoadImage 会报 Invalid image file）/ keep（保留，必须写 reason，配置层也回退）；`value_form` 默认 `url`（30 集 `refs_used.json` 证明传 download_url 能出片），`fileName` 留作切换。顺带：`build_node_list` 按 (nodeId, fieldName) **先到先得去重**（真实值永远赢过填充值）；`empty` 的 `""` 不被当空节点丢弃；补 `h3.nodes` 结构校验。可观测性：运行开头打印「工作流 N ｜ 覆盖 M ｜ 未使用 K」、dry-run 逐条预演「哪个槽被顶掉、原默认是什么」、`--probe` 标注「图片槽·已覆盖 / 图片槽·未使用」、探测失败明说「本轮未使用槽位会沿用工作流里的图」、配置指向不存在节点报 `ghost`。文档同步 `references/runninghub-contract.md`（新增「一之二、nodeInfoList 是覆盖表不是完整表」）与 `references/troubleshooting.md` §12（画面多出不该有的人/景怎么确诊）。验证：新增 `engine/tests/test_slot_hygiene.py` **32/32**、全量离线 **678 例 0 失败**、真实 dry-run 得 `6/3/3` 且 `cb955bf6….png` 完全消失、`--probe` 标注正确、占位图上传成功（5334 B）。⚠ **真实出片未验证**：账号 `errorCode=605 余额不足`，充值后 `--video-only --only ep01_sc01 --limit 1` 即可闭环。详见 `docs/patches/2026-10-22_H3参考图槽位残留修复记录.md`。

- **2026-10-22 更新（V0.7.8 · API Key 必填 + 放大正名 1080P + 歧义排查）**：用户三条要求逐条落地。① **「开工前需要把 API key 确定下来」** —— 旧 `_account_state()` 在「无 RunningHub 通道」时返回 `required=False` 直接判过，等于**从没问过**。改：恒为必填，两种合法终态必须显式拍板（登记真实账号 / `--account none --account-none-reason "<理由>"` 声明不需要，理由入单留痕）；只写 none 不给理由仍退出码 4；有云端通道时 none 直接非法（"不能声明不需要"）。第 6 项工作流 API 保持按通道条件化（本地项目确实没有工作流）。测试夹具与三处断言（缺项数 6→7、`full_setup` 带 none 声明、`test_80` 重写为三态）同步。② **「放大的环节改成 1080P，不要设置 2k」** —— 查证 `config.upscale.json` 的 target 本来就是 `1080x1920`，**问题不在分辨率而在名字**：产物叫 `<ep>_master_2k.mp4`（2K 通常指 2560×1440），名不副实会让人以为"已经出过 2K 版"。改：新名 `<ep>_master_<W>x<H>.mp4`，`upscale.upscaled_path()` / `bgm._hi_res_names()` / `release_export` 的 `master_res` 档 / `workflow` S9 判据 / 工作区 `asr_burn.py` 全部"新名优先、旧名 `_master_2k` 只读回退"；在跑项目 30 集已改名（`_master_2k` → `_master_1080x1920`），改名后 `workflow status` S9 仍 30/30。③ **歧义排查** —— 修掉 `--ep 26` 静默产 0 条字幕（三处入口统一 `canon_ep()`，非法输入退出码 1，并清掉误建的 `subs/26/`）；修掉两份「高清放大」文档都指向不存在的 `<ws>/docs/高清放大-2K-实测与操作手册*.md`（245 行手册改名 `hd-upscale-case-2560x1480.md`，引用改仓库内相对路径）；把七类术语的多义写成唯一解释（母版四义 / 2K 三义 / 字每秒两义 / 续跑两义 / 退出码三分法 / G 编号两套 / voice 两处同义），见 `docs/orchestration/项目流程与设定对账_20261022.md` §九。验证：`test_setup_workflow_pipeline.py` 54/54、`test_subtitle_alignment.py` 38/38、`test_bgm.py` 41/41、`test_release_export.py` 14/14；在跑项目 `--ep 26` 由 0 条变 ep26/6 条、`setup require` 9/9。
- **2026-10-22 更新（V0.7.7 · 流程与设定全量对账）**：用户要求「整理一下项目的思路流程，看下有没有互相冲突的设定内容」。方法：以 `stages/` 代码为裁判，交叉比对「代码 ↔ 配置 ↔ 文档 ↔ 在跑项目实例」，产出 `docs/orchestration/项目流程与设定对账_20261022.md`（一张流程图 + 五层真源裁判权 + 冲突台账 + 已核对不冲突项）。**4 处真冲突**：① `workflow.py` S10 印着**不存在的** `--sync-from`（2026-10-21 补丁单的"建议"被当成已实现抄进去）→ 改 `--stage align`，补丁记录 10.4 回填为「已落地（换了做法）」；② `bgm check` 与 `bgm mix` 读不同增益（`sync_plan_gain` 只在 mix 里跑）→ 同集出现「check 报 FAIL、mix 成功」（实测 ep29 -3dB vs -14.6dB，30 集旧计划全中）→ `cmd_check` 先做同样校正（只改内存不写盘）再判门禁；③ S6 判据按**文件数**而非**镜头数**（240 镜报成 284/240，返工旧批次把缺口盖住）→ probe 支持 `count: parent` 按镜头去重；④ 总纲环节 14 把封面主路径写成 `cover_forge.py`（与 README/发行清单/workflow 的「`cover_prompt.py` 为主、forge 仅兜底」相反）→ 已同步。**8 处口径不一致**已写明：安全区三数（平台 200 / 项目 400 / 6:4 实际 696 属层层加严）、`margin_v_pct` 在 ratio 模式已失效、`es.cps_ok` 下限 6.0→**3.0**（6.0 会把正常台词判异常，与「偏慢不是缺陷」相反）、G6 停点只对手动跑生效（pipeline 不停）、`drama.py` 只转发 4 个子命令、环节判据只看齐备度不看质量、G-1 是 G-0 第 1 项、补丁 10.4 状态回填。**1 处命名撞车**：`技能映射与缺口.md` 的 G1–G10 是缺口编号、总纲 G-0…G11 是门禁编号，同字母不同义（已标注，不改名以免制造悬空引用）。验证：`test_bgm.py` 39/39、`test_setup_workflow_pipeline.py` 53/53；在跑项目 S6 `284/240`→`240/240`、`bgm check ep29` FAIL→通过、`setup require` 9/9、`workflow status` 11/11。
- **2026-10-22 更新（V0.7.6 · 字幕纵向落点改「视觉中心 6:4」）**：用户在看过 V0.7.5 的成片后提出「把 6:4 视觉中心版式的规则搬过来，我觉得字幕在这个位置更好」。移植自 `vidpure/core/subtitle_burn.py` 的 `Placement(anchor="ratio", anchor_top=0.6)` 口径：文字块**中心**落在 `0.6 × 画面高`（距顶:距底 = 6:4），1080×1920 上 `y=1152`、块下沿距底 696px（安全区下限 400px 不放松）。实现改用 `{\an5\pos(W/2,y)}` **逐条**定位而非样式 `MarginV`，关键收益是**一行与两行字幕的中心同线** —— 旧口径 `Alignment=2`（底对齐）在折行时文字往下长、整块上半部分空出来，同一段连续台词在"一行↔两行"切换时字幕会跳；`\an5` 以块中心为锚点，行数变化不动位置。第二收益是**换分辨率不漂移**（固定 400px 在 1080×1920 占 20.8% 高、2176×3840 只占 10.4%，同剧两版位置不一致）。配套：`qa_safe_area()` 改**分模式断言**（ratio 判 `\pos` 实际落点 + 所有条目 y 相同且等于设计值容 1px + 块下沿距底 ≥ min_bottom；pixel 仍判 MarginV），`style_metrics()` 在 `anchor_top` 过低时按安全区**上顶**并置 `anchor_clamped`；`verify_render()` 的字幕带改按 `center_y ± 块高/2` 取窗（旧口径把画面下半部都当字幕带，`diff_rest` 被拉高导致判定失真）；`write_ass()` 报告新增 anchor/center_y/bottom_px/block_h 字段；配置新增 `placement` 块（示例配置与在跑项目 `D:/剧本/海外剧/2` 均已写入 `{"anchor":"ratio","anchor_top":0.6}`，`anchor:"pixel"` 可回退）。文档：`stages/subtitle/references/rendering-and-styling.md` 新增 §1.1、`quality-gates.md` 断言 6 改分模式判据。验证：`test_subtitle_alignment.py` **35/35**（新增 `TestVisualCenter` 6 例），`test_safe_area.py` 三画布 × 两语言全通过且篡改 `\pos` 能拦住；ep26 重烧 65.8s，6 条 ASS 全为 `{\an5\pos(540,1152)}`，渲染自检字幕带差异 10.7 vs 其余 0.9。逐条说明见 `docs/patches/2026-10-22_字幕与后期故障修复记录.md` §八。
- **2026-10-22 更新（V0.7.5 · 字幕四层故障 + 后期/配乐/引擎并发症）**：输入为 30 集实跑的调试日志包（395 条任务 / 343 成功 / 52 失败 / 9270 RH币）。**结论：字幕「频繁异常」是四层叠加，不是一个 bug** —— ① *时间层是假的*：项目侧 `tools/gen_align_estimate.py` 按「镜长 × 经验话音模型」写 `method=script_estimate` 的 align 记录，而 `stage_align` 只判 `os.path.exists()` ⇒ **CTC 强对齐一次都没跑过**（实测 ep26_sc02：估算 0.56–6.75s，`ctc-forced-aligner` 真值 3.32–6.26s，起点偏 2.8s；语速体检那堆 `3.7 字/秒` 也是估算撑出来的）。改：`_align_cache_ok()` **看 method 不看存在**，估算档一律重建；report 增 `align_methods` / `warnings_align`；`gen_align_estimate.py` 改为停用说明页（退出码 2，不写文件）。② *判据层是错的*：whisper 对纯音乐段输出 `[Música]`，旧 `speech_regions` 当它是语音 ⇒ 覆盖检查大面积误报，且 `repair_leading_gaps` 据此把首条字幕**前移到静音上**（ep26_sc02 从 3.22 拉到 0.00，而 0–3s 的 RMS 只有 53–234、人声段 3618–5208）。改：`is_nonspeech()` 过滤 `[Música]/[Music]/[Applause]/[BLANK_AUDIO]/♪` 等，`asr_entries()` 成唯一 SRT 入口；新增 `window_loud_fraction()` 对每个候选缺口做**声学复核**（有声帧 <15% 即丢弃），因为 whisper 对短镜头惯常给一条跨满整段的假时间。③ *条目层是缺的*：`build_cues` 只认剧本 `<d>` 所在的镜头，而 H3 会自行在无台词镜头里说话（ep26_sc03/sc08 实测）⇒ 新增 `asr_fill_segment()`（`source=asr-unscripted`，绝不覆盖剧本原文）；同时重写 `tools/asr_burn.py` —— 它的 `align_to_script()` 只保留剧本行、丢弃所有未匹配 ASR 条目（ep25 剩 1 条/4.4s、ep26 剩 4 条/11.4s，每集 62s），现在改为读引擎 `cues.json`，只保留客户端才需要的「封面首帧 +1.5s」与「直烧混过 BGM 的底片」。④ *口径层是弱的*：`asr_calibrate` 用「字符集合重叠」+「有任意公共字符就吞并」，把 38 条粘成 4 条 ⇒ 改 `difflib` 比率（主匹配 0.45 / 吞并 0.25）。**移植 vidpure**：`loud_intervals`（纯标准库 20ms 帧 RMS + p90 相对阈值）与 `tighten_to_audio`（含「缩了就念不完就整条放弃」护栏）用于字幕首尾收紧；刻意**不搬**其 6:4 视觉中心版式（本项目平台口径是「距底 ≥200px」像素硬限，`margin_v_pct` 与像素下限取大者已满足）。**另修**：对齐器**无超时**（`aligner_timeout_s` 从 V0.5 起写在配置里却从没接线，死锁时整集挂死）→ `run(timeout=)`；段起点**按写死 24fps** 推算（非 24fps 素材每段偏 0.15–0.2s、30 段累计 4–6s）→ 改用 `media_duration()`；西语断行取「第一个装得下的切点」把语义切碎 → 按 Netflix 断点分级（句末 > 分句 > 长度）；`<d>台词</d>` 无方括号被静默丢弃 → 正则放宽；语速「偏慢」改为汇总一行。**并发症**：`upscale.py` 每集 `_cleanup` + 逐帧删样张，30 集 100+ 次删除撞上宿主 safe-delete 阈值 50（ep28–30 在 Topaz 100% 后被杀）→ 删除预算自我设额（默认 30，`SOLODRAMA_DELETE_BUDGET` 可调）；`StateStore` 临时文件名固定 `state.json.tmp`，同批次两个引擎进程互踩（`Errno 13` ×20、`WinError 32` ×1）→ pid+tid 唯一名 + `os.replace` 指数退避 6 次 + 最终退化覆盖写不抛；上传调用点无重试（`ReadError` ×8 白跑）→ 包 `retry_async(3, (2,6,15))`；BGM 门禁三方口径不一致（plan 按 -3dB 报 FAIL 却照写、mix 里 `sync_plan_gain` 改成 -14.6 后通过、check 读盘上那份永远 FAIL）→ `plan` 不写自己门禁过不了的产物 + `--force-gain` 写 `gain_locked` 且 `check_plan` 对锁定段降为提示。**验证**：新增 `test_subtitle_alignment.py` 29/29，全量 27 个测试文件 0 失败；真实项目 ep26 重对齐 → 条目 4 条/30.75s 变 6 条/43.29s、假缺口 4 段 20.5s 降 2 段 4.9s → `--stage render` 64.8s 通过自检；抽帧目视 t=1.5s 无字幕、t=4.5s 正常两行。逐条对照与未修项见 `docs/patches/2026-10-22_字幕与后期故障修复记录.md`。
- **2026-10-21 回填（V0.7.4）**：内容提交 `78925a9`（远端 `99fb865` → `78925a9`，快进）；本条仅改 `README.md` / `VERSIONS.md` / `manifest.sha256`。
- **2026-10-21 更新（V0.7.4 · AI 曲目改记自有版权）**：用户声明 6 首 AI 生成曲目**版权归己**，`license` 由 `generated`（条款待补）改为 **`owned`**，另加 `origin: ai_generated` 保留事实；修 `cmd_credits` 把 `owned` 误标「需署名」的 bug（原逻辑只排除 cc0），现在标 `[自有]` 且不输出署名段；`bpm` 从「必须人工填」改为**可选**（仅卡点剪辑需要）。文档口径三处同步。`test_bgm.py` 38/38，全量 564 例。
- **2026-10-21 回填（V0.7.3）**：内容提交 `6c55ffc`（远端 `76577e1` → `6c55ffc`，快进）；本条仅改 `README.md` / `VERSIONS.md` / `manifest.sha256`。
- **2026-10-21 更新（V0.7.3 · AI 生成 BGM 入库 + 响度校准）**：用户用 AI 音乐平台生成 6 首入库（原样不转码，库共 18 首）。体检发现母带响度跨 13.5 dB（全域 -6.8 ~ -28.6，跨 22 dB），统一 -22 dB 会「有时震耳有时听不见」→ 改**按 EBU R128 实测反推**（`gain = (-33 + 情绪偏移) - loudness_lufs`）；门禁改判**最终铺底响度** `[-42,-25] LUFS`；新增 `--scan --loudness` 并修「只回写项目库」缺陷；新增 `sync_plan_gain()` 自动校正过期计划增益；ducking 默认 `threshold` 0.05→0.15、`ratio` 6→4、`release` 350→300（人声连续时 0.05 会压整集）。用发布版 Episode01 做样片验证：片尾静音段 -52.4 → -38.6 dB。`test_bgm.py` 37/37，全量 563 例。
- **2026-10-21 回填（V0.7.2）**：内容提交 `3411550`（远端 `c08618c` → `3411550`，快进）；本条仅改 `README.md` / `VERSIONS.md` / `manifest.sha256`。
- **2026-10-21 更新（V0.7.2 · BGM 生成提示词）**：新增 `docs/production/BGM生成提示词.md`。先定「什么样的 BGM 才混得进去」六条硬约束（无人声/无旋律主线/无突袭音效/无前奏无 drop/可无缝循环/中低音量铺底），再给 6 情绪 × 主用·变体共 12 条可直接粘贴的提示词（曲风+情绪+乐器+BPM+调性+结构），附 negative 词表、参数建议与交付要求。纯文档改动。
- **2026-10-21 回填（V0.7.1）**：内容提交 `85d8a1a`（远端 `ae03b32` → `85d8a1a`，快进）；本条仅改 `README.md` / `VERSIONS.md` / `manifest.sha256`。
- **2026-10-21 更新（V0.7.1 · BGM 库落地）**：① 先证伪一条路：**Pexels 无法提供 BGM** —— 实测其 API 只有 `photos`/`videos`，`/v1/audio`、`/v1/music`、`/v2/audio` 全部 404，视频不带音轨；改用 **Wikimedia Commons**（授权字段结构化，能机器判定可商用）。② 预置 **12 首**（6 类情绪 × 2），全部 **CC BY 3.0/4.0**（可商用须署名），清单含 `artist/license_name/source_url/attribution/license_note` 可审计；音频不进 git（补了 `.gitignore` 规则并用探针验证）。③ 新增 `stages/production/scripts/fetch_bgm.py`：**库可再生**，换机器跑 `--apply` 按同一检索与过滤口径抓回；排除 BY-SA/NC/ND、访谈讲座录音、地域时代风格。④ 新增 `bgm.py credits --ep epNN` 输出署名段（CC BY 署名义务，粘进发布文案）。⑤ 选曲加 **LRU**（扫计划文件，优先最久没用过的），整剧不重复同一首。验证：`test_bgm.py` **31/31**，全量 **557 例**。
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

