# SoloDrama

**一个人，就是一个剧组。**

> **宗旨：一个人、一天时间、一台电脑、N部短剧！！！**
>
> 用得起、算得清、跑得稳：资产出图默认走**本地 ComfyUI（￥0）**，云端出片只走 RunningHub 官方标准通道，干跑默认 + 计费双确认 + 逐笔台账。
>
> **一台家用笔记本就够**：本项目全程在一台 **RTX 4060（8G 显存）+ 16G 内存的笔记本**上开发并验证 —— 本地出图、拼接、2K 放大都在本机完成，不需要工作站、服务器或云主机。

---

> ## ⚙️ 开工第一件事：先自检环境
>
> ```bash
> python tools/env_check.py          # 人读报告；加 --fix 打印逐条修复命令；加 --json 给 Agent 用
> ```
>
> **必需项（Python 3.10+ / Pillow / ffmpeg / ffprobe）不全就不要往下走。**
> 缺依赖的报错通常出现在中途（封面排版、字幕烧录、出片），而且错误信息往往指向错误的方向。
>
> 本项目实测最常见的坑是**依赖装给了另一个解释器**：`pip install` 装进了 A 环境，跑脚本用的是 B，
> 于是 `ModuleNotFoundError` 看着像代码坏了，其实是环境错配。自检会直接指出「哪个解释器装了、当前用的是哪个」，
> 并给出两条命令：**用已装好的解释器跑**（零安装），或**给当前解释器补装**。
>
> 详细口径见 [§零、环境自检](#零环境自检开工前第一件事)。

---

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B%20(tested%203.13)-3776AB.svg)](requirements.txt)

AI 短剧批量生产的**本地全链路工具集**：**创作**与**成片**在同一仓库里闭环。

- **创作层** `stages/creation/`：① 榜单调研与对比（多市场横向比较，西语重点）→ ② 爆款拆解（题材 / 套路 / 爆点 / 内容偏好 / 差异化趋势）→ ③ 选题定位（七维加权评分 + 定位卡）→ ④ 剧本改写（源剧本 → N 集规划）。
  其中确定性的部分——数据覆盖度门禁、评分、交叉去重、集数排期与爆点节拍、结构抽取、FFS 骨架、格式 lint——都已落成**可离线回归的脚本**；LLM 创意环节仍可留在 AI 会话中完成。
- **执行层** `stages/assets|video|subtitle|production/`：由 `data/` 四文件驱动
  **资产出图 → 逐段成片 → 整集母版 → 2K 高清 → 烧录字幕 → 像素验收 → 成本台账**，全本地 CLI，支持断点续跑、成本可控。

两层之间只有一份**只读数据契约**（`data/` 四文件）：换模型、换通道、换创作方式，另一侧零感知。

---

## 零、环境自检（开工前第一件事）

```bash
python tools/env_check.py            # 人读报告
python tools/env_check.py --fix      # 打印逐条修复命令（只打印，不执行任何安装）
python tools/env_check.py --json     # 机器读（CI / Agent）
python tools/env_check.py --quiet    # 只看未通过的项
```

退出码：`0` 必需项齐备｜`2` 有必需项缺失 —— **返回 2 的时候不要往下走**。

### 检查项

| 层 | 项 | 必需 | 缺失后果 |
|---|---|---|---|
| 运行时 | Python ≥3.10（实测 3.13） | ✅ | 语法/标准库不兼容 |
| 运行时 | 独立 venv（建议） | ⭕ | 依赖互相污染 |
| 依赖 | Pillow | ✅ | 封面排版/叠字兜底、图像体检全挂 |
| 依赖 | httpx | ⭕ | 云端（RunningHub）通道不可用 |
| 外部程序 | ffmpeg / ffprobe | ✅ | 拼接、2K、字幕烧录、像素验收全挂 |
| 外部程序 | whisper-cli | ⭕ | 字幕识别（可用平台字幕替代） |
| 配置 | `RUNNINGHUB_API_KEY` / `RUNNINGHUB_BASE_URL` | ⭕ | 只能走本地 ComfyUI |
| 配置 | ComfyUI `127.0.0.1:8188` | ⭕ | 本地出图需先手动启动 ComfyUI |
| 完整性 | `manifest.sha256` 自校验 | ⭕ | 仓库文件被改动过，或清单过期 |

### 三种典型失败与处理

**① 依赖装了，但装给了另一个解释器（最高频）**

自检会直接打印类似：

```
★ 依赖装在别的解释器里（这是最常踩的坑）
  C:\...\envs\default\Scripts\python.exe
     已装：Pillow 12.2.0

两种修法（推荐 A，不装任何东西）：
  A) 用这个解释器跑本项目： "C:\...\default\Scripts\python.exe" tools/env_check.py
  B) 给当前解释器补装：     "C:\...\versions\3.13.12\python.exe" -m pip install -r requirements.txt
```

选 A 零安装；选 B 之前先确认 `python -c "import sys; print(sys.executable)"` 打印的就是你要装的那个解释器。

**② 确实没有 Pillow / httpx**

```bash
python -m pip install -r requirements.txt
```

**③ 没有 ffmpeg / ffprobe**

```bash
winget install Gyan.FFmpeg      # Windows；装完重开终端让 PATH 生效
brew install ffmpeg             # macOS
```

### 给 AI 助手的用法

让 Agent 先跑 `python tools/env_check.py --json`，读 `ok` 字段：

- `ok: false` → **不要开始干活**，把 `items` 里 `required && !ok` 的项连同 `alt_interpreters` 一起报给用户，让用户在 A/B 之间选；
- `ok: true` → 正常进入下面的流程。

> 这条前置检查是硬要求：缺依赖导致的报错通常出现在中途（封面、字幕、出片），而且信息往往指向错误方向，
> 事后排查的成本远高于开工前 5 秒的自检。

---

## 一、交付成果

### 1.1 交付清单

| 类别 | 交付内容 | 状态 |
|---|---|---|
| **本地执行引擎集** | 5 个阶段模块（创作 / 出片 / 字幕 / 总控 / 资产）+ Web 控制台 `web/`，共 **172 个受管文件** | ✅ 已交付 |
| **统一 CLI 入口** | `stages/production/scripts/drama.py`，11 类子命令 | ✅ 已交付 |
| **西语漫剧创作链路** | `stages/creation/`（四部分，49 例离线测试） | ✅ 已交付 |
| **本地出图通道** | `stages/assets/comfyui/`（￥0 成本、零第三方依赖、不出网） | ✅ 已交付 |
| **模型选择门禁** | `stages/production/scripts/model_gate.py`（19 例离线测试） | ✅ 已交付 |
| **发行资料门禁** | `stages/production/scripts/release_check.py`（发布版命名 + 封面多尺寸 + 版权资料 4+4，15 例离线测试） | ✅ 已交付 |
| **发布版导出** | `stages/production/scripts/release_export.py`（严格 `EpisodeNN.mp4` 命名，13 例离线测试） | ✅ 已交付 |
| **封面（AI 直出带字）** | `stages/production/scripts/cover_prompt.py`：五段式提示词 + 标题断行（≤3 行 / 西语 ≤18 字符）+ 出图前体检，清单可直接喂**本地 ComfyUI** 或 **RunningHub 工作流**；规范 `references/cover/prompt-guide.md`；PIL 排版引擎 `cover_forge.py` 降级为兜底（38 例离线测试） | ✅ 主路径已切换（2026-10-20） |
| **资产落点迁移** | `stages/production/scripts/migrate_assets.py`（旧 `07-成片/assets` → `04-资产`，默认干跑+备份，16 例离线测试） | ✅ 已交付 |
| **离线测试集合** | 各套离线用例（零网络零计费）+ 字幕安全区断言集，全部通过 | ✅ 全绿 |
| **完整性指纹** | `manifest.sha256`（**172 条**，显式排除自身） | ✅ 逐文件 0 不符 |
| **设计文档** | 可行性检查报告 + 技术文档 + 创作层方法论 5 篇 + 模块 references | ✅ 已交付 |
| **依赖锁定** | `requirements.txt`（`httpx==0.28.1` / `Pillow==12.2.0`，实测 Python 3.13） | ✅ 已交付 |
| **开源发布** | GitHub [`Hejunlong27/SoloDrama`](https://github.com/Hejunlong27/SoloDrama)，Apache-2.0 | ✅ 已发布 |

### 1.2 已交付功能矩阵

| 阶段 | 模块 | 功能 |
|---|---|---|
| **创作** | `stages/creation/` | ① 榜单调研与对比（多市场横向比较 + 西语重点）→ ② 爆款拆解（题材分布 / 套路库 / 爆点 / 内容偏好 / 差异化趋势）→ ③ 选题定位（七维加权评分 + 定位卡）→ ④ 剧本改写（源剧本 → N 集规划，默认 **30 集 × 60 秒**，每集含开场钩子 / 核心冲突 / 反转 / 集尾钩子） |
| **资产** | `stages/assets/` | 资产卡提示词净化（14 条纪律）+ 三类模板 + `md → 清单` 转换；出图双通路：**本地 ComfyUI（默认，￥0）** 与 RunningHub 云端（★计费）；**产物统一落 `04-资产/{characters,scenes,props}`**（老项目用 `migrate_assets.py` 迁入） |
| **接线** | `stages/production/` | 参考图落位接线（`<Picture N>` ↔ refs 顺序一致）、悬空图槽 / 超 6 槽体检、参考图瘦身 |
| **出片** | `stages/video/workflow/` | RunningHub「工作流 + AI 应用」标准通道批量出片：`doctor` 体检 → 干跑计划 → 小样 → 全量；taskId 级断点续跑、并发上限 5（单账号，见下方说明）、计费预估与用量核对 |
| **成片** | `stages/subtitle/` | CTC 强制对齐 → ASS 生成 → 无损拼接母版 → Topaz 2K 放大 → 字幕烧录 → 七道质量断言 |
| **验收结账** | `stages/production/` | 字幕像素级验收、集级前置体检、成本台账（Excel 7 工作表 + markdown），口径只认平台返回的 `usage` |
| **发行** | `stages/production/` + `docs/distribution/` | 发布版成片统一导出为 **`09-发行/剧集/EpisodeNN.mp4`**（`release_export.py`，命名不许即兴发挥）+ 封面多尺寸成组（抓马构图口径）+ 文案 + 发布清单 + **版权资料 4 张「AI 生成过程截图」+ 4 张「原始文件/素材文件信息」**；齐全度门禁 `release_check.py` |
| **总控** | `stages/production/scripts/drama.py` | `status / preflight / assets / refs / models / video(plan·run·status) / report / balance / cost / guide` |

### 1.3 视频通道并发上限（RunningHub）

> **RunningHub 单账号最多支持 5 个 AI 应用 API 并发。**
>
> 本引擎据此把并发固定为 **5**，并将该值写入配置（`concurrency=5`）后作为**平台硬限**显式声明——它不是可调优参数。
> 超限提交会被平台拒绝（典型表现为 `errorCode 1520 并发已达上限`，引擎内置退避重试；仍失败则降并发到 1）。
> 该上限与「默认干跑 + 计费双确认 + 断点续跑」共同构成成本控制的边界。

### 1.4 流程实战背书

以下数据来自本项目改造前的 WorkBuddy 工作流阶段（引擎同源，收编时核心逻辑零改动）：

| 实战项目 | 规模 |
|---|---|
| 《七大姑催婚》ep03–ep10 | 64 段 / 172 条字幕 / 792 秒 / 9,705 RH 币 |
| 《贤妻不装了》 | 81/81 参考图全量出图；多段并发出片 |
| 《La Novia del Enemigo》 | 西语竖屏端到端（源剧本 → 成片） |

---

## 二、关键创新

### 1. 编排层与引擎层分离，引擎「单真源」收编

- **机制**：新增代码只做「调度、校验、搬运、记账」；引擎以子进程 + 固定 CLI 契约调用，业务逻辑一行不动。原 Skill 包不再承担引擎职责，副本为唯一运行真源。
- **价值**：消除「Skill 包 vs 项目 scripts/ 双副本分叉」——该分叉历史上真实引发过一次线上事故；分层后换剧只换 `--workspace`，引擎零改动。

### 2. 本地优先出图：默认路径 ￥0

- **机制**：资产出图默认走本机 ComfyUI（`stages/assets/comfyui/comfy_client.py`），纯标准库、零第三方依赖、不出网、**不需要任何 Key**；工作流路径与五类节点 id 全部用环境变量覆盖，换工作流不改代码。
- **价值**：批量铺量不产生任何云端费用；且该通道**刻意不 import** 既有云端引擎，避免把 `httpx` / RunningHub 客户端拖进零成本链路。

### 3. 模型选择门禁：把「确认」变成不可绕过的前置条件

- **机制**：首次生图与首次出片之前，必须先确认模型（本地 ComfyUI / RunningHub / 闭源模型），确认单落盘 `<工作区>/model-plan.json`；未确认即拦（退出码 4）。
- **价值**：门禁不只是拦「未确认」，还拦「确认一套、跑另一套」——确认了本地 ComfyUI 却执行 `--engine rh`，会被要求先改确认单。杜绝默认值静默生效造成的意外计费。

### 4. 成本可控四道闸

| 闸门 | 机制 |
|---|---|
| **默认干跑** | 所有会花钱的动作默认只打印清单与预估，真实提交必须显式 `--submit` / `--yes` |
| **计费双确认** | 先小样（1 段）验证成片与单价，确认后才全量 |
| **断点续跑** | `--resume <batch_id>` 复用原 taskId，只轮询不重复提交，已生成的自动跳过 |
| **硬限显式声明** | 并发 ≤5（**RunningHub 单账号最多支持 5 个 AI 应用 API 并发**）、单镜头参考图 ≤6 写入配置并在文档标注为**平台硬限**，不作为可调优参数暴露 |

台账口径只认平台返回的 `usage`；**本地通道消耗恒为 ￥0 也照记**，保证全链路逐笔可核算。

### 5. 数据契约驱动的解耦

- **机制**：创作层与执行层之间只有 `data/` 四文件（`shots.json` / `characters.json` / `scenes.json` / `h3_prompts.json`）这一份**只读契约**，外加一份 `data-schema.md`。
- **价值**：创作侧可替换任意工作流与模型，执行侧零感知；校验走 `--dry-run --strict`，缺关键字段**报错让人补，不猜不编**。

### 6. 创作层的「确定性化」

- **机制**：把创作流程中非创意的部分——市场数据覆盖度门禁、七维加权评分、三维交叉与差异化去重、集数排期与爆点节拍、结构抽取、FFS 骨架、格式 lint——全部用**纯标准库**实现；LLM 创意环节仍留在会话工作流中。
- **价值**：可离线回归（49 例）、零网络零计费，且每条结论强制可回指到具体数据条目（`score_basis` 逐维必填）。

### 7. 开源卫生与可复现性工程

- **去硬编码手术 17 处**：个人机器路径、账号 AI 应用 ID、工作流 ID 一律改为环境变量或占位符；合规扫描（用户名 / 盘符 / 中文路径 / 16 位 ID / 密钥样式）**0 命中**，真实 Key 从不入库。
- **零新增第三方依赖**：编排层与全部新增模块仅用标准库；`requirements.txt` 只锁 `httpx` 与 `Pillow`。
- **完整性可验证**：`manifest.sha256` 逐文件指纹（显式排除自身）防篡改防漂移；`.gitattributes` 固定 `eol=lf` + 仓库级 `core.autocrlf=false`，保证跨平台字节一致。
- **数据与引擎严格分离**：`data/`、`output/`、台账、密钥一律落工作区，`.gitignore` 兜底排除。

---

## 三、实现步骤

按实际开发顺序（2026-10-08 → 2026-10-12）：

### 阶段 1 · 只读盘点与断点诊断（10-08 上午）

盘点 9 个 WorkBuddy Skill + 确定性工具链 + 实战工作区，产出《可行性检查报告》。
识别出 **B0–B7 断点**（其中 **B1「创作 → 出片无数据转换器」定为唯一 P0**）、O1–O8 优化点、A1–A8 待拍板假设。
> 产出：`docs/可行性检查报告.md`

### 阶段 2 · 架构设计（10-08 下午）

确定**混合模式**：创作层保留在 AI 会话（人工质量闸），执行层独立为本地 CLI；确定编排层 / 引擎层分层、关卡制、数据契约与退出码约定。
> 产出：`docs/Agent项目技术文档.md`

### 阶段 3 · 引擎收编与去硬编码（10-08 傍晚）

按「拷贝固化、单真源」收编引擎：`stages/{video/workflow, subtitle, production, assets}` + `tools/` + `docs/creation/`；
执行去硬编码 17 处，合规扫描 0 命中；生成全量指纹与锁定依赖；跑通离线冒烟（doctor / 净化器 / 提示词用例）。

### 阶段 4 · 出片通道收敛（10-08 深夜）

把出片能力收敛为 RunningHub **「AI 应用 + 工作流」两条官方标准通道**——判据是长期稳定、可复算、可替换。
只保留官方标准通道也意味着一条统一规则：**单账号并发上限 5**，成本与排队行为都可预期。
同步更新设计文档与配置，重建指纹；确立项目宗旨与成本底线。

### 阶段 5 · 首次开源发布（10-09）

`git push` 被本地代理隧道打成 502，改用 **PAT + GitHub Git Data API** 完成首次单提交快进推送。
> 落地：`github.com/Hejunlong27/SoloDrama`（2026-10-13 由 `Drama` 更名，旧地址自动跳转），Apache-2.0。

### 阶段 6 · 接入本地 ComfyUI 出图通道（10-10）

新增 `stages/assets/comfyui/`（纯标准库本地出图引擎）+ `asset_md.py`（md → 清单转换器）+ 生产桥 `gen_assets_local.py`；
资产出图改为**默认本地（￥0）、云端计费通道并存**。
顺带修复 3 个收编遗留真缺陷：脚本路径失效导致子命令全找不到、子脚本无法推断工作区、代理劫持 localhost 导致 502。
> 验证：新增 19 例离线测试全绿，指纹重建。

### 阶段 7 · 模型门禁 + 西语创作链路（10-12）

① 新增 `model_gate.py` 并接入两个计费入口（生图、出片），19 例测试全绿；
② 新增 `stages/creation/` 创作链路，并按交付语义重构为**四部分**：调研对比 → 爆款拆解 → 选题定位 → 剧本改写，49 例测试全绿；
③ 打通与 `tools/cli.py`（创作工具链）及 `drama.py`（执行引擎）的对接。

### 阶段 8 · 发布与一致性核验（10-12 晚）

固定行尾策略（`.gitattributes` = `* text=auto eol=lf` + 仓库级 `core.autocrlf=false`），重建指纹（114 条，排除自身）；
以 API 方式推送两个快进提交，并用远端 tree 逐 blob 比对完成核验：**tree 一致、0 字节不符、无遗漏无多余**。

---

## 四、怎么用

> **统一入口（2026-10-16 起）**：本项目现在是短剧生产的**单一编排层** ——
> 此前分散在多个 WorkBuddy Skill 里的流程、规则与门禁，已收敛为「一份总纲 + 一套预置脚本 + 一个 CLI」。
> 全流程、目录规范与硬规则见 **[`docs/orchestration/生产流程总纲.md`](docs/orchestration/生产流程总纲.md)**（单一真源）。
>
> **开跑前必须先过两道前置门禁**（每次任务开始前，**顺序不可颠倒**）：
>
> ```powershell
> # ① 画风三轨（最先：它决定画风与资产规格，换了等于已产出素材全部作废）
> python stages/production/scripts/drama.py style status
> python stages/production/scripts/drama.py style set 3d_manhua --sub-mode guoman-3d-render
> #    三选一：3d_manhua（3D 漫剧）/ 2d_animation（2D 动画）/ live_action（真人写实）
>
> # ② 生图/视频通道 + 执行依据
> python stages/production/scripts/drama.py models status
> python stages/production/scripts/drama.py models set image=local_comfyui video=runninghub --workflow-id <ID>
> ```
>
> 通道四选一：**本地 ComfyUI（￥0）/ 云端 ComfyUI / RunningHub AI 应用 / 闭源模型**。
> 选了**云端 ComfyUI** 必须同时提供**服务地址 + 工作流 API 文件**；选了 **RH AI 应用**必须提供**应用地址**；
> 缺依据即停在关卡（退出码 4），不许开工。
>
> 画风完整规格（**画风与资产规格** · 单一真源）见
> **[`docs/styles/画风三轨规范.md`](docs/styles/画风三轨规范.md)**。
>
> **叙事结构与提示词装配**（剧本解析 / 分镜 11 字段 / 台词设计 / H3 六段式）真源 = **`3d-short-drama-studio` 技能**，
> 叙事模式**写死为对白驱动**（旁白每集 ≤2 条、≤8 秒、只在首尾；删掉全部旁白剧情仍须完整）。
> 画风三轨只管「皮」（画风块、资产数量、首帧角度），不管「骨」（谁来讲事、怎么切镜、台词怎么写）。

先分清你是哪一类 —— 两条路线的入口、前置与产出完全不同：

| | **使用者**（内容创作者 / 短剧团队） | **开发者**（改造引擎 / 接新通道 / 做集成） |
|---|---|---|
| **目标** | 把手上一个故事变成可发行的成片 | 读懂并扩展引擎，让它稳定可复用 |
| **要不要写代码** | **完全不需要** —— 把两段提示词交给 AI 助手，它替你跑完 | 需要（新增模块以 Python 标准库为主） |
| **入口** | **AI 助手 + 一句话提示词**（想自己敲命令，见 4.1 折叠区） | 各 `stages/*/scripts/` 源码 + `references/` 契约 |
| **前置** | Windows 电脑 + 一个能执行命令的 AI 助手（独显 / 云端账号均可选） | 同上，且需读懂数据契约再动手 |
| **交付物** | 成片 mp4 + 字幕 + 成本台账（xlsx / md）+ 发行资料（封面 + 文案 + 发布清单 + 版权资料） | 代码改动 + 离线测试全绿 + 重建后的指纹 |

### 4.1 使用者路线：把仓库交给 AI 助手，你只说两句话

> 📋 **不想读下文？直接复制 [`docs/新项目启动提示词.md`](docs/新项目启动提示词.md) 里的整段给 AI 助手** ——
> 它是为「让助手用上当前版本的规则」而写的：先读真源（§3.7 / 事故复盘 / pitfalls §F）再开工，
> 并含老项目「资产归位 + 发布版改名」的两条命令。

**不需要写代码，也不需要敲命令。** 你只要把仓库地址和下面两段提示词发给你的 AI 助手（WorkBuddy 等能读写本地文件、能执行命令的 Agent），它会完成安装、配置和全部生产步骤；你只需在几个「要不要花钱」的节点上答一句「可以」。

整条链路 Agent 会依次替你跑完：**选题 → 世界观与人物 → 剧本 → 分镜与视频提示词 → 资产出图 → 渲染出片 → 拼接与 2K → 字幕 → 验收结账 → 发行资料（剧集 / 封面 / 文案 / 发布清单 / 版权资料）**。

> ### ⚠️ 给 AI 助手的三条红线（先把这段读完再动手）
>
> 这三条来自**真实的用户验收意见**（2026-10-19），违反一次就要返工一次：
>
> 1. **资产（人物/场景/道具）一律放 `04-资产/{characters,scenes,props}`**，**不许**出现在 `07-成片/` 下。
>    新脚本用 `_ws.ASSETS` / `_ws.assets_dir(ws)`，**不要自己拼 `<out>/assets`**。
> 2. **发布版成片一律命名 `EpisodeNN.mp4`**（`Episode01`…`Episode40`）并落 `09-发行/剧集/`，
>    **只用 `release_export.py` 导出，不要手工改名**；`EP01_1080p_ES.mp4`、`ep01_拼接_11段_672x1216.mp4`
>    这类带过程信息的名字**不许**当交付物。
> 3. **不要临时起名、不要临时挑目录**。凡是要给用户看的交付物（成片 / 封面 / 版权资料），
>    先查 `docs/orchestration/生产流程总纲.md` **§3.7 落点与命名硬规则**；该节没有的规定，
>    **先把规则补进去**再动手。
>
> 完整事故复盘（现象 / 根因 / 修法 / 验收判据）：[`docs/patches/2026-10-19_落点与命名事故复盘.md`](docs/patches/2026-10-19_落点与命名事故复盘.md)

#### 你只需要准备这几样

| 准备 | 说明 |
|---|---|
| 一台 Windows 电脑 | Python 3.10+（**Agent 会自己装**，你不用管） |
| 一块 NVIDIA 独显（可选） | **有**：本地出图 ￥0，2K 放大建议 ≥8GB 显存（本项目实测机型：RTX 4060 8G + 16G 内存笔记本）；**没有**：全部走云端，照样能跑 |
| RunningHub 账号（可选） | 只有走云端出片时才要；**只用本地 ComfyUI 出图可以完全不申请** |
| 一个 AI 助手 | 能克隆仓库、执行命令、读写本地文件的 Agent |

#### 第 1 步：让 Agent 帮你安装

把下面整段复制给 Agent（路径可改成你想要的）：

```text
请帮我安装并初始化这个开源项目，我要用它制作 AI 短剧：
https://github.com/Hejunlong27/SoloDrama

请依次完成，每步做完告诉我结果：
1. 克隆到 D:\SoloDrama，安装 requirements.txt 里的依赖
2. 跑一遍离线自检，确认 131 例用例全绿（这一步不联网、不花钱）
3. 检查本机有没有装 ComfyUI；没装就告诉我怎么装，装好后帮我在项目里配置好
4. 检查 RunningHub 的 API Key 是否已配置成环境变量；没有就告诉我怎么申请
5. 新建一个剧项目工作区，路径用 D:\短剧\我的第一部剧
6. 全部完成后告诉我：怎么启动，以及我会被问到哪些问题

注意：任何要花钱的步骤，执行前必须先告诉我要花多少，等我同意再执行。
```

#### 第 2 步：让 Agent 帮你做剧

装好之后，把这段发给它（把故事、平台、集数换成你自己的）：

```text
用 D:\SoloDrama 帮我把下面这个故事做成一部短剧。

【故事】<把你的故事或小说粘在这里>
【平台】竖屏（TikTok / 红果风格）
【规格】30 集，每集约 60 秒（默认口径）

请走完整流程：选题 → 世界观与人物 → 剧本 → 分镜与视频提示词 →
资产出图 → 渲染出片 → 拼接 2K → 字幕 → 成本台账。

硬性要求：
- 所有要花钱的动作（云端出图、云端出片）先报价给我，我同意后再执行
- 人物/场景/道具资产一律放在 04-资产（characters / scenes / props），**不要**放到 07-成片 里面
- 出片先做 1 段小样给我看，我确认后再全量
- 中途失败或中断就用 --resume 续跑，绝不重复提交、不重复花钱
- 每做完一步告诉我：现在到哪一步、这一集花了多少、下一步预计花多少
```

#### 第 3 步：要发行时，让 Agent 备「发行资料」

剧做完了准备上架时，把这段发给它：

```text
准备发行资料。

要求：
1. 发布版成片统一导出到 09-发行/剧集/，文件名严格 Episode01、Episode02、Episode03 …（Episode + 两位编号），
   不要用 EP01_1080p_ES / ep01_拼接_11段 这类名字。导出用 release_export.py，不要手工改名。
2. 封面要抓马、有视觉冲击感（不是我给你的剧照精选，是冲突海报）：
   单主体大特写、强明暗对比、画面里有一个能一眼看懂冲突的物件、
   大字标题（中文不超过 6 个字）、留一半悬念、高饱和撞色。
3. 封面按多尺寸成组出：9:16 竖版主封面 + 3:4 卡片位封面（16:9 横版建议一起出）。
4. 版权资料按 4 + 4 备齐：
   - 4 张「AI 生成过程截图」：出图/出片平台任务页、提示词或工作流节点、
     生成结果列表、用量计费记录；
   - 4 张「原始文件或素材文件信息」：项目工作区目录树、剧本原稿文件信息、
     分镜或提示词源文件信息、成片母版文件信息。
   截图里任务 ID 与时间戳必须能看清（可以打码 API Key，但不要打码任务 ID）。
5. 另附文案（标题 + 三档描述 + 关键词）和一份发布清单。
5. 备齐后跑一次发行资料门禁，把结果告诉我。
```

#### Agent 会问你几个问题，照实答就行

| Agent 问 | 你怎么答 |
|---|---|
| 首次生图和出片用哪个模型？ | **有独显** → 本地 ComfyUI（￥0）；**没有** → RunningHub（按量付费） |
| 这几张人物定妆图满意吗？ | 满意就继续；不满意就说「第 2 张重出」 |
| 这一集出片预计花 XX，确认执行吗？ | 确认；或者说「先只跑 1 段小样」 |
| 2K 母版好了，这集要烧字幕吗？ | 要 / 不要（不要就给你无字幕的高清母版） |
| 这集收工了，要结账吗？ | 要（生成成本台账 Excel） |
| 准备发行资料了，封面走哪种风格？ | 说题材就行（逆袭 / 虐恋 / 商战 / 悬疑 / 甜宠），Agent 按对应情绪色板出抓马封面 |

#### 只要记住三条，就不会多花钱

1. **不确认不花钱** —— 没等到你点头，Agent 不会执行任何计费动作。
2. **先小样后全量** —— 先出 1 段看效果，满意了再放开整集。
3. **中断就续跑** —— 让它用 `--resume`，已完成的片段自动跳过，不重复扣费。

<details>
<summary><b>命令行速查（给愿意自己动手、不想用 Agent 的人）</b></summary>

```powershell
# 一次性：环境 + 模型确认（首次必做；未确认时一切计费动作会被拦下，退出码 4）
pip install -r requirements.txt
python stages/production/scripts/drama.py models status
python stages/production/scripts/drama.py models set image=local_comfyui video=runninghub

# ---- 每集循环：顺序执行；带 ★ 的会花钱，都需要你显式确认 ----
python stages/production/scripts/drama.py status          # 先看全盘状态（零网络）

# ⓪ 前置门禁（★ 首次必做；每次任务开始前先看一遍，顺序不可颠倒）
python stages/production/scripts/drama.py style status     # ① 画风三轨（最先）
python stages/production/scripts/drama.py style set 3d_manhua --sub-mode guoman-3d-render
python stages/production/scripts/drama.py models status    # ② 生图/视频通道 + 执行依据
python stages/production/scripts/drama.py models set image=<local_comfyui|cloud_comfyui|runninghub|closed_source> \
        video=<local_comfyui|cloud_comfyui|runninghub|runninghub_ai_app|closed_source> \
        [--comfy-url ...] [--comfy-workflow <导出的工作流API.json>] [--app-url ...] [--workflow-id ...]

# ⓪.5 旁白时间窗校验（**可选**；对白驱动项目通常不需要，读 05-分镜/storyboard.json；零费用）
#      仅当本集有旁白、或沿用半解说规格时才跑；对白驱动剧跳过不影响出片
python stages/production/scripts/drama.py halfcheck all     # 旁白时间窗 / 资产规格 / 首帧锚点
python stages/production/scripts/drama.py halfcheck windows # 只查旁白/对白时间窗

# ⓪.6 分镜/提示词 → data/ 四文件 + 入门口禁（零费用，把错误挡在计费之前）
python stages/production/scripts/convert_storyboard.py --workspace <工作区> --ep ep01            # 干跑
python stages/production/scripts/convert_storyboard.py --workspace <工作区> --ep ep01 --apply    # 真写
python stages/production/scripts/ingest_check.py      --workspace <工作区> --ep ep01
python stages/production/scripts/script_timing_check.py --workspace <工作区> --ep ep01          # 台词时长审计（4.2 字/秒）

# ① 资产出图（★ 默认本地 ComfyUI，￥0，只花本机电与时间）
python stages/production/scripts/drama.py assets --engine local --check    # 体检 ComfyUI 是否在线
python stages/production/scripts/drama.py assets --engine local            # 干跑：只看清单，不出图
python stages/production/scripts/drama.py assets --engine local --submit   # 批量出图（先出一张看风格）
python stages/production/scripts/drama.py assets --engine local --only char_01   # 只补某一个资产

# ② 参考图接线 + 一次过体检（零费用）
python stages/production/scripts/drama.py refs --apply --write-config
python stages/production/scripts/drama.py preflight

# ③ 出片（★ 计费：先小样，看到实际用量与单价再全量）
#    RunningHub 单账号最多支持 5 个 AI 应用 API 并发（引擎已据此固定并发=5，勿超限提交）
python stages/production/scripts/drama.py video plan                       # 计划与成本预估（零费用）
python stages/production/scripts/drama.py video run --yes --limit 1        # 小样：只出 1 段
python stages/production/scripts/drama.py video run --yes --resume <批次>   # 全量
python stages/production/scripts/drama.py video status <批次>               # 进度与失败清单

# ④ 拼接 + 2K 放大 + 字幕（零费用，GPU 独占，一次只跑一集）
python stages/subtitle/scripts/subtitle.py --workspace <工作区> --ep ep03
#   → 跑到 2K 母版就【停下】问你「要不要烧字幕」；答「要」才继续
python stages/subtitle/scripts/subtitle.py --workspace <工作区> --ep ep03 --burn   # 一口气完成
python stages/subtitle/scripts/subtitle.py --workspace <工作区> --ep ep03 --preview 2   # 只出 2 段预览

# ⑤ 验收 + 结账 + 发布前合规
python stages/production/scripts/drama.py report
python stages/production/scripts/drama.py cost --checkpoint                # 收工结账，记基线
python stages/production/scripts/compliance_precheck.py --workspace <工作区> --ep ep01 --q1 no --q2 no --q3 no
python stages/production/scripts/compliance_precheck.py --workspace <工作区> --all --aigc-label yes --restricted 0 --total 30

# ⑥ 发行资料（零费用；用户说「准备发行资料」时执行）
#    ① 发布版成片：严格 Episode01.mp4 / Episode02.mp4 …，落 09-发行/剧集/（别手工改名）
python stages/production/scripts/release_export.py --workspace <工作区> --all              # 干跑：看「哪个源 → 哪个目标」
python stages/production/scripts/release_export.py --workspace <工作区> --all --apply      # 真写
python stages/production/scripts/release_export.py --workspace <工作区> --from "<已编码发布版目录>" --all --apply
#    ② 发行资料齐全度门禁（剧集命名 + 封面档位 + 版权资料 4+4 + 文案 + 发布清单；退出码 2 = 不齐）
python stages/production/scripts/release_check.py --workspace <工作区>
python stages/production/scripts/release_check.py --workspace <工作区> --json               # 给控制台 / CI 解析

# ⑦ 只在需要时：把老项目里「跑到 07-成片 下」的资产迁回 04-资产（默认干跑，先备份）
python stages/production/scripts/migrate_assets.py --workspace <工作区>                     # 打印搬迁清单
python stages/production/scripts/migrate_assets.py --workspace <工作区> --apply             # 真搬
```

> 出片缺图 / 提示词有缺陷时，`preflight` 与干跑会先拦下来 —— 把错误挡在计费之前。

</details>

### 4.2 开发者路线：环境 → 契约 → 扩展 → 提交

#### ① 环境与离线自检（零网络、零计费）

```powershell
python tools/env_check.py              # ★ 先确认解释器与依赖（见 §零）
pip install -r requirements.txt        # 只装 httpx + Pillow，无其他第三方依赖

python tools/tests/test_env_check.py
python stages/video/workflow/scripts/run.py doctor --json
python stages/assets/scripts/sanitize.py --selftest
python stages/assets/scripts/tests/test_prompter.py
python stages/assets/scripts/tests/test_asset_md.py
python stages/production/scripts/tests/test_model_gate.py
python stages/production/scripts/tests/test_style_gate.py
python stages/production/scripts/tests/test_release_check.py
python stages/production/scripts/tests/test_release_export.py
python stages/production/scripts/tests/test_migrate_assets.py
python stages/creation/scripts/tests/test_creation_pipeline.py
# → 各套离线用例应全绿（零网络、零计费）
```

#### ② 先读契约，再读代码（改动前必看四份）

| 契约 | 位置 | 管什么 |
|---|---|---|
| 出片数据契约 | `stages/video/workflow/references/data-schema.md` | `data/` 四文件的字段与校验规则（唯一输入契约） |
| RunningHub 行为契约 | `stages/video/workflow/references/runninghub-contract.md` | 提交 / 轮询 / 计费字段 / 错误码语义 |
| 创作层模块契约 | `stages/creation/references/module-contracts.md` | 四部分的输入输出、门禁与产物结构 |
| 生产总控坑册（**§F 落点与命名** = AI 助手高频错误） | `stages/production/references/pitfalls.md` | 已知坑与处置口径 |

#### ③ 常用扩展点（多数不需要改上游逻辑）

| 想做什么 | 改哪里 |
|---|---|
| 换本地出图用的工作流 | 环境变量 `COMFYUI_WORKFLOW` / `COMFYUI_NODE_*`（**改配置不改代码**） |
| 改字幕样式 / 放大参数 | 工作区里的 `config.subtitle.json` / `config.upscale.json` |
| 换站点 / 工作流 ID / 节点映射 | 工作区 `config.local.json` 或对应环境变量 |
| 加一种字幕语言 | 依 `stages/subtitle/references/rendering-and-styling.md` 补字体、断行与字符预算 |
| 接一条新出片通道 | 沿用 `channel` 适配器接口扩写；**产出 schema 不变** |
| 加一类资产（如道具） | `assets --kind prop` 已支持；提示词 md 章节约定见 `stages/assets/comfyui/references/本地ComfyUI出图.md` |

#### ④ 改动红线

- **不碰业务规则**：计费守卫、关卡停靠、断点续跑语义、产出 schema 一律不动。
- **数据与密钥不入库**：`data/`、`output/`、台账、真实 Key 全部落工作区，`.gitignore` 兜底排除。
- **新依赖要克制**：新增模块优先用纯标准库（现有新增模块均为标准库实现）。
- **不猜数据**：缺关键字段时报错让人补，不静默编造默认值。

#### ⑤ 提交前必做

- **重建 `manifest.sha256`**：受管文件清单以 `git -c core.quotePath=false ls-files` 为唯一真源，**显式排除 `manifest.sha256` 自身**（正确条数 = 受管文件数 − 1）；格式 `sha256  *相对路径`、ASCII 排序、UTF-8 无 BOM、LF。**任何文件改动都要重建**，否则自校验出现 mismatch。
- **自校验 0 不符**：逐条比对 `manifest.sha256` 与磁盘文件后再提交。
- **行尾**：`.gitattributes` 已声明 `* text=auto eol=lf`；工作树不得出现 CRLF 文件。

## 目录结构

```
SoloDrama/
├── stages/
│   ├── creation/          ★ 西语漫剧创作链路（① 调研对比 → ② 爆款拆解 → ③ 选题定位 → ④ 剧本改写）
│   ├── video/workflow/    批量出片引擎（RunningHub 工作流 / AI 应用）
│   ├── subtitle/          字幕引擎（CTC 对齐 → ASS → 无损拼接 → Topaz 2K → 烧录 → 七道断言）
│   ├── production/        一集总控（模型门禁 / 体检 / 补资产 / 参考图接线 / 出片调度 / 验收 / 成本台账）
│   └── assets/            资产出图：净化器 + 三类模板 + md→清单转换器 + 离线测试
│       └── comfyui/       ★ 本地 ComfyUI 出图引擎（￥0、零第三方依赖、不出网）
├── tools/                 创作层确定性工具（初始化 / 锚点入库 / 剧本校验 / 格式转换）
├── web/                   本地 Web 控制台（FastAPI + 原生 JS + SSE；引擎零改动，可选）
│   ├── STUDIO.md          ★ Web 工作台说明：启动 / 配置 / 页面能力矩阵 / LLM 系统 / 安全边界
│   └── ui/studio/         Studio 前端（深色工作台，零构建零外链；删掉即回滚）
├── docs/                  单一真源文档：流程总纲 / 画风三轨 / 发行资料 / 合规预检 / 创作方法论
├── configs/               配置模板（含 model-plan.example.json 模型确认单）
├── start.cmd              ★ 双击启动 Studio（自动查依赖 / 挑解释器 / 找端口 / 开浏览器）
├── start-readonly.cmd     以只读模式启动（拒绝写操作与计费）
├── requirements.txt       锁定依赖
├── manifest.sha256        引擎文件指纹（防篡改 / 防漂移）
└── VERSIONS.md            收编来源、版本标记、改动清单
```

## 配置与密钥

- **所有平台密钥走环境变量**，代码与配置模板中不落任何真实 Key（**本地 ComfyUI 通道不需要任何 Key**）：
  - `RUNNINGHUB_API_KEY`（消费级；工作流 / AI 应用通道）
  - `RUNNINGHUB_ENT_API_KEY`（企业级-共享；仅标准模型 API 使用，如场景空镜文生图）
  - `RUNNINGHUB_BASE_URL`（站点，按账号所在站设置）
  - `SOLODRAMA_WORKSPACE`（默认工作区）、`SOLODRAMA_ASSET_MD`（资产提示词 md）
    > 旧前缀 `DRAMA_WORKSPACE` / `DRAMA_ASSET_MD` / `DRAMA_SCRIPTS_DIR` **仍然生效**（新名优先、旧名回退），已有配置无需改动。
  - `RH_CHAR_APP_ID` / `RH_SCENE_APP_ID`（账号绑定的 AI 应用 ID）
  - `COMFYUI_URL`（本地 ComfyUI 地址，默认 `http://127.0.0.1:8188`）
- 运行配置唯一可写文件是 `<工作区>/config.local.json`（模板：`stages/video/workflow/assets/config.local.example.json`）。
- 字幕样式 / 放大参数：复制 `stages/subtitle/assets/config.*.example.json` 到工作区后按需修改，**不要改代码**。
- 字幕链外部工具（ffmpeg / whisper.cpp / ctc-forced-aligner / Topaz）路径写在字幕配置的 `tools` 段，不进代码。
- 本地出图的**节点映射**（换工作流时）用 `COMFYUI_NODE_*` / `COMFYUI_WORKFLOW` 环境变量覆盖，不必改代码。

## 目录纪律

- 引擎代码与剧项目数据严格分离：`data/`、`output/`、台账一律落**工作区**，绝不写进本仓库。
- 已在 `.gitignore` 中排除数据、产物、密钥类文件；发布前请用 `manifest.sha256` 核对引擎完整性。

## 文档索引

| 主题 | 文档 |
|---|---|
| **生产流程总纲（流程 · 目录规范 · 硬规则 · 门禁）★ 单一真源** | `docs/orchestration/生产流程总纲.md` |
| **画风三轨规范（画风 / 资产规格）★ 单一真源** | `docs/styles/画风三轨规范.md` |
| **叙事结构（剧本解析 / 分镜 / 台词 / H3 提示词）· 对白驱动** | `3d-short-drama-studio` 技能（`references/dialogue-driven-rules.md`） |
| **角色差异化设计规范（六维签名 · 六条硬规则 · 提示词三件套）★** | `docs/assets/角色差异化设计规范.md` |
| **技能映射、缺口台账与重叠裁决** | `docs/orchestration/技能映射与缺口.md` |
| **发布前合规预检清单（TikTok 口径）** | `docs/compliance/发布前合规预检清单.md` |
| **发行资料清单（封面抓马度 · 版权资料 4+4 · 发布清单）★ 单一真源** | `docs/distribution/发行资料清单.md` |
| **产线对账关卡（26 个实跑坑 → 自动/人工对账项）** | `docs/patches/产线对账关卡_2026-10-18.md` |
| **落点与命名事故复盘（2026-10-19 用户验收意见 · 必读）** | `docs/patches/2026-10-19_落点与命名事故复盘.md` |
| **新项目启动提示词（复制给 AI 助手即可）** | `docs/新项目启动提示词.md` |
| 40 集实跑复盘（26 个坑，按严重度排序） | `docs/patches/SoloDrama_踩坑清单_2026-10-18.md` |
| 产线补丁清单（逐条 patch 与代码片段） | `docs/patches/2026-10-18_短剧产线补丁清单.md` |
| **台词时长审计口径（4.2 字/秒）** | `docs/creation/台词时长审计口径.md` |
| **剧本强度工程（爽点结构 · 打脸五拍 · 质控标准）★** | `docs/creation/剧本强度工程.md` |
| **题材公式库（女频逆袭，可扩展；命中即跳过选题）** | `stages/creation/references/genre-formulas/` |
| **转译语种注册表（西/英/日/韩/葡/泰/印尼/越 + 中文）** | `stages/creation/references/translation-languages.json` |
| 改造背景、可行性分析 | `docs/可行性检查报告.md` |
| 架构、数据契约、执行流程 | `docs/Agent项目技术文档.md` |
| **西语漫剧创作链路（四部分）** | `stages/creation/README.md` |
| **创作层模块职责与数据契约** | `stages/creation/references/module-contracts.md` |
| **西语与多市场基线（近 2 个月）** | `stages/creation/references/spanish-market.md` |
| **七维评分模型** | `stages/creation/references/scoring-model.md` |
| 出片数据契约 | `stages/video/workflow/references/data-schema.md` |
| RunningHub API 行为契约 | `stages/video/workflow/references/runninghub-contract.md` |
| 字幕对齐 / 样式 / 放大 | `stages/subtitle/references/` |
| 生产总控坑册（**§F 落点与命名** = AI 助手高频错误） | `stages/production/references/pitfalls.md` |
| 本地 ComfyUI 出图（流程 / 清单格式 / 症状表） | `stages/assets/comfyui/references/本地ComfyUI出图.md` |
| Qwen-Image 2.1 工作流节点表与换工作流适配 | `stages/assets/comfyui/references/workflow-qwen-image21.md` |
| 资产卡净化纪律 | `stages/assets/references/踩坑全录-6个真缺陷.md` |
| 创作层方法论 | `docs/creation/` |

## License

本项目以 **Apache-2.0** 协议开源，详见 [LICENSE](LICENSE)。

---

## 版本记录

> 纪律：**每次更新必须在本表追加一行**（版本号 + 日期 + 新增/变更/修复 + 基线提交 + 验证结论），并同步 `VERSIONS.md`。
> 版本号口径：`V0.x` 新能力 / `V0.x.y` 修复与文档 / `V1.0` 留给正式发布。

| 版本 | 日期 | 内容 | 基线提交 | 验证结论 |
|---|---|---|---|---|
| **V0.7.18** | 2026-10-29 | **环境体检 + 一键修复**。① 新增 `web/core/health.py` 与页面 `#/health`（全局导航「环境体检」）：15 项体检覆盖运行时 / Python 依赖 / 外部程序 / 本机服务 / 数据目录 / 配置 / 完整性，诊断复用 `tools/env_check.py --json`（用**引擎解释器**跑，口径与出片一致），另加三项 Studio 自有检查（`web/var` 与 `web/var/llm` 是否可写、引擎解释器是否被配置指到空文件、Key 是否落在连接中心）。② **只自动修三类**：`pip`（装进引擎解释器、用 `requirements.txt` 的锁定版本、不带 `--user`/`--break-system-packages`）、`mkdir`（只建 Studio 自己的运行时目录）、`config`（清掉 `settings.json` 里指向空文件的 `python`，先备份）。`winget` 装 ffmpeg / 启动 ComfyUI / 填 Key / manifest 不符一律标 `manual` 或 `page` 并**说清为什么不能自动**——把这几类混进「全部修复」，结果只会是「按钮转两圈、什么也没变」。③ **三条纪律**：动作白名单在服务端（接口只收 `fix_id`，命令由 `_fix_spec()` 现算，前端传不进一条命令）；**复检才是结论**（`pip` 退出码 0 只说明 pip 没崩，修完必重跑 `collect()` 取同一项，不过就返回 `ok=false` + 「命令跑完了但复检仍未通过」）；每次修复追加一行到 `web/var/health-fixes.jsonl` 并在页面底部可查。④ **修一个自己埋的坑**：`_writable()` 原用「建探针文件再删」判断可写，`mkdir` 顺手把目录建了 ⇒ `dir.var` 永远判「通过」、一键修复按钮成摆设；改为「存在 + `os.access(W_OK)`」，建目录只由修复动作做（体检是 GET，不该有副作用）。⑤ 系统设置页的「环境」卡新增「环境体检 / 一键修复」入口。 | `(pending)` | 全量 **38 个 `test_*.py` 0 失败**（引擎 23 + web 15）；新增 `test_health.py` 7 组：清单形状与 `fix.kind` 合法性、pip 命令只打引擎解释器且用锁定版本、非自动项必须被拒且不产生执行、建目录真建 + 复检、失效配置清理并备份且保留其它键、**「命令成功但复检不过 → ok 必须 false」**、留痕可读回。真机闭环（临时 venv 复现缺依赖，不碰真实环境）：`engine_python` 指向空 venv → 体检报 `Pillow 缺失 / 2 项可一键修复` → `POST /api/health/fix {id:dep.pillow}` **2.6s 装好并复检通过**（httpx 3.5s）；页面截图复核：失败态（红色「缺失」+ 一键修复按钮 + 将执行的命令 + 两个解释器路径并列）、修复后（顶部「必需项全部就绪」、修复记录表 2 行「已通过」） |
| **V0.7.17** | 2026-10-29 | **流水线模式（连跑）+ 预算内自动放行**。① 新增 `web/core/pipeline.py` 与页面 `#/pipeline`：把引擎的 11 个环节串成一条可执行的线，两种模式 —— **逐步确认**（点一次只跑 1 步）与**连跑**（最多 6 步）。② 三条硬纪律：**不猜**（只有 `STAGE_MAP` 明确登记命令的环节才算「可自动」，没登记的一律标「需人工」并给出该去的页面，S3 资产设计→资产中心、S7/S11→发行中心）；**计费可估才放行**（`est_coins` 已知且「累计+本步 ≤ 预算」才自动跑，估不出来就停下问，不猜金额）；**前置未齐不动手**（环节自带 probes 的 `found/need`，未满足就停在该环节，不跳过）。③ 参数解析：`assets.local` 这类只认环境变量的命令，由 `_values_for()` 自动找「资产提示词 md」并注入，找不到就判「需确认」并说明要准备什么——不给空值硬跑（否则会被误读成「ComfyUI 没开」）。④ 接口：`GET /api/pipeline/plan`（只读计划）、`POST /api/pipeline/run`（默认 `dry_run=true`，`_write_guard` 保护）。⑤ 修一个隐蔽 bug：旧 `/api/pipeline` 的处理函数名叫 `pipeline`，**在模块级覆盖了 `core.pipeline` 模块**，导致新接口 500 —— 已改名 `legacy_pipeline`。 | `c0211b0` | 全量 **37 个 `test_*.py` 0 失败**（引擎 23 + web 14），新增 `test_pipeline.py` 4 组：前置未齐必须 blocked、需人工必须 manual 且带页面、预算内 auto / 超预算 ask / 估不出 ask、dry-run 只回报不执行且遇 blocked 停；真实项目实测：11 环节 → 可自动 0 / 需确认 0 / 被挡 8 / 需人工 3，逐条给出缺什么（如 S5 缺「分镜脚本、data/shots.json、data/h3_prompts.json」）；页面截图复核（模式单选、预算输入、四项计数徽章、11 行环节表） |
| **V0.7.16** | 2026-10-29 | **本地出片改「数据驱动」：换工作流不用改代码**。① **节点映射外置成 sidecar**：新增 `stages/video/comfyui/workflow_h3_local.map.json`（`prompt/images/seconds/steps/seed/aspect/prefix` 七个角色的节点 id），默认按约定读「同名 `<工作流>.map.json`」；优先级 `--map` > sidecar > 环境变量 `COMFYUI_VIDEO_NODE_*` > 内置默认。之前这七个 id 是脚本里的硬编码常量，换一份工作流必须改 Python —— 换机器、换工作流都很别扭。② **新增 `--list-nodes`（离线）**：列出每个节点 id / class_type，并标出「它适合当哪个角色」，用户照抄就能写映射；**新增 `--map-check`（离线）**：逐个校验映射的 id 在工作流里是否存在、类型是否对得上。价值在于：映射 id 写错时脚本照样能提交、GPU 照样跑，但参数全落在没人读的节点上 —— 出来是默认参数的片，白等几分钟；这条能在花 GPU 之前 100% 抓出来。③ **非 API 格式拦截**：ComfyUI 界面直接导出的 workflow 是 `{nodes, links}` 数组，同样是 dict，以前会放过去然后在后面报一堆「节点 id 不存在」，把人引到映射上；现在在 `load_workflow()` 就挡住，并明确提示「用导出 API 格式」。④ **命令层开放**：`video.local` / `video.local.check` 增加 `workflow` / `map` 两个参数；新增 `video.workflow.nodes`（列节点）与 `video.workflow.mapcheck`（校验映射）两个 sync 只读命令。`steps` 的默认值也从命令里去掉 —— 留空即沿用工作流里的值（4 步 turbo 就是 4），避免页面把别人调好的 4 步冲成代码默认。 | `b31272d` | 全量 **36 个 `test_*.py` 0 失败**（引擎 23 + web 13），新增 `stages/video/comfyui/tests/test_workflow_map.py` 5 组：自带映射必须通过、id 写错必须判失败、换工作流时 sidecar 按文件名自动识别、界面格式被挡住、`--list-nodes` 离线可用；实测 `--map-check` 七项全 `[OK]`（30/24/15/9/10/14/4），干跑读数正确显示「沿用工作流：5.0s ≈ 124 帧 / 16:9 0.6MP / 4 步」 |
| **V0.7.15** | 2026-10-29 | **本地视频通道（H3）+ RH 图像工作流区分文生图/图生图 + 生成通道台账**。① **本地出片**：新增 `stages/video/comfyui/`（`comfy_local_video.py` + `workflow_h3_local.json`），用本机 ComfyUI 跑 MiniMax H3 图生视频 —— 工作流取自用户本机的「minimax 多参(4步采样)」：`Cobijada_H3_Hybrid…int8` + `qwen3vl_32b_minimax_h3_int4` + `video_vae_int8` + `lightx2v turbo 4step` LoRA(0.75)，**`SolAttnMiniMax` 加速节点保留、steps=4**。实测 5 秒 16:9 0.6MP → **283s / 2.0MB / 1056×608 / 24fps / 124 帧**，人脸与场景正常。客户端默认 dry-run，`--check` 先核对节点类与模型文件，`--seconds/--mp/--aspect` **不传就沿用工作流原值**。② **RH 图像工作流分模式**：`gen_assets_rh_workflow.py` 支持 `--mode t2i|i2i` —— 文生图取 `image_providers[active].id`，图生图取 `id_i2i` 且必须先上传参考图、把平台文件名写进 `nodes.image` 节点。**两个 id 互不兜底**：混用的后果不是报错，而是静默忽略参考图（钱扣了、图还是纯文生图）。③ **生成通道台账**：新增 `web/core/generators.py` + `GET /api/generators`（只读现算：ComfyUI 在线 + 工作流节点类 + 模型文件 + 项目 `config.local.json` 的 ID/节点映射），状态分 `ready/config/offline/missing/unsupported` 并给「下一步」。④ **新页面「生成通道」**：图像/视频两张表，文生图与图生图分行显示；右上「配置云端工作流」把 4 个关键值写进项目配置（`POST /api/generators/rh`，**写前备份**、只改这一条 provider、i2i 缺参考图节点直接拒绝）。⑤ **新命令**：`assets.rh_wf`（RH 工作流出图，★计费）、`video.local`（本地出片，￥0，默认干跑）、`video.local.check`（体检）。 | `0c4dda6` | 全量 **35 个 `test_*.py` 0 失败**（引擎 22 + web 13，新增 `test_generators.py` 6 组：t2i/i2i 各取各的 id、缺 id_i2i 不兜底、缺「加载图像」节点判待配置、本地通道区分 offline 与 missing、缺模型点名、未选项目不许假装可配置）；本机实测两条真片（4 步 5.17s / 2.0MB；早期 6 步 4.46s / 0.73MB），`ffprobe` 校验 h264/1056×608/24fps/124 帧，抽帧人工复核画面正常；生成通道页截图复核（图像 1/4、视频 1/2 可用，RH 两条如实标「待配置」并指出缺 `active_image_provider` / `h3`）。⚠ 未做：本地图生图（Qwen-Image i2i）未内置——现用工作流是纯文生图，没有加载图像节点，页面如实标「不支持」 |
| **V0.7.14** | 2026-10-28 | **真实大模型接通（DeepSeek）+ 推理模型适配 + 深链工作区修复**。① **接入 DeepSeek 官方通道**：`deepseek-flash` / `deepseek-v4-pro`（`deepseek-v4.1-flash` 是平台侧别名，API 直接 400）；Key 只落 `web/var/llm/keys.json`（git 忽略），界面只回显 `sk-2…44d0`；旧的 `openai-env` provider 已删除 —— 它把 `env_var` 绑在 `OPENAI_API_KEY`（另一个平台的 Key），所以永远是 401，这就是「环境出网受阻」的真因。② **推理模型适配（关键）**：这两个模型把**思考过程也算进 max_tokens**，给 8-16 token 时回包是 `HTTP 200` + `content: ""`。旧实现会报成 parse（输出不是合法 JSON），用户被带偏到提示词上。现在错误分类新增 `truncated`（`finish_reason=length`）与 `empty`（内容策略/真没话说），各自带可执行的下一步；探针额度由 8→64 tokens。③ **数值预算写进提示词**：Schema 管得住单镜 `DUR ∈ [4,15]`，管不住「所有 DUR 之和」——实测模型会写出 90 秒的「60 秒档」剧集。新增 `core/llm/budget.py` 作为镜数/时长边界的**唯一真源**，`render_parts()` 把边界写进 user 段，`drafts` 复算也走它（不会再出现「提示词说一套、校验器说另一套」）。④ **字段填写约定**（`SCHEMA_NOTES`）：无台词的镜头 `dialog` 必须写「无」而不是空串（引擎 lint 要求 `DIALOG:` 后有内容）、`char` 只能用 HEADER 已登记代号。实测补上这两条后，引擎 lint 的 WARN 归零。⑤ **深链修复**：`/?ws=<剧目录>` 的 307 跳转把查询串丢了（`location: /studio/`），所以书签永远打不开指定项目、还会被后续操作改写 `current`。现在带住 query，前端只接受「在可用列表里」的 current。⑥ **注册表写盘前剥掉计算字段**：自愈时把 `exists/images/loose` 也写回 `registry.json`，会导致下次读到过期快照。统一走 `_registry_clean()`。 | `dbd39ef` | 全量 **34 个 `test_*.py` 0 失败**；`verify_llm_loop.py --provider deepseek --confirm-cost` **28/28**（约 27s）：配置 → 真实探测 → 绑定用途 → 提示词 → 生成 → 人工编辑 → 落盘 → 引擎 `script_rewrite.py lint` **rc=0**（8 镜 / 70 秒）；界面复核：AI 模型中心显示 DeepSeek（`deepseek-flash` / 可用模型 2）、可用用途 **7/7**，工作台接入状态「DeepSeek 可调用 · 实测 2/2」；`test_workspaces.py` 增 §5（深链必须带住 `?ws=`）。 |
| **V0.7.13** | 2026-10-28 | **登记表自愈 + 散图口径统一 + 本地出图首次真跑通**。① **当前工作区绝不停在死路径**（真实缺陷）：真机登记表里 `current` 指着已删除的 `D://剧本//海外剧//3`，而旧 `_i_workspaces()` 会把 `current` 无条件塞进 `items` 伪造成一张卡片、前端 `loadProjects()` 又直接采信它 ⇒ 一进站就用不存在的目录请求所有接口，页面全空且不报错。现在：不再伪造条目；`current` 失效时自愈到「第一个真实存在且带 `layout.json`/`video-pipeline` 的项目」并落盘；响应新增 `current_exists` / `stale` / `current_replaced`；`_registry()` 的兜底也改成只挑真实存在的项。前端再兜一道：只接受在可用列表里的 `current`。② **失效目录可清理**：`POST /api/workspaces/prune` 只删注册表条目、**不碰磁盘**，项目页顶部给警示条与一键移除，解决「登记了 4 个只显示 2 个、数字对不上又无从下手」。③ **散图数一路加到所有看图的地方**：`inventory` 新增 `images.loose`（走 `artifacts.loose_images`，与资产页同源）与 `images.all`；`has_output` 计入散图（图都在根目录的项目不再被判「未开工」）；`discover()` 带 `loose`；项目卡片 / 工作台表格 / 顶部项目条 / 扫描本机列表 / 项目详情 / 用户端首页全部按 `images + loose` 显示 —— 修复「项目卡片说 21 张、工作台说 0 张」这类同机不同口径。`images.total` 保持「已归档资产」原义不动（多处断言依赖）。④ **本地 ComfyUI 通道首次真实出图**：Qwen-Image 2.1（int8 + 4step turbo LoRA，`1248×1856`）单张 **2 分钟 / ￥0**，产物 3.6MB、PNG 魔数正确、画面为指定场景（1972 加油站女性肖像，人脸无畸变）；工作流节点与模型（`qwen3vl_8b_int8_convrot` / `qwen_image_2.1_vae_bf16` / `qwen_image_2.1_int8_convrot`）已逐一核对。⑤ 新增 `test_workspaces.py`（4 组：死路径自愈并落盘 / 未登记死 current 不许变卡片 / 全盘皆死时置空 / prune 不碰磁盘），`test_inventory.py` 补「散图口径」。 | `45ebaa0` | 全量 **34 个 `test_*.py` 0 失败**（引擎 22 + web 12）；真机接口验证：`current` 由死路径 `D://剧本//海外剧//3` 自愈为 `D://剧本//海外剧//2、母亲之路`、`stale=[D:/剧本/海外剧/2]`、该项目 `loose=21 / has_output=true`；三个页面截图复核（项目卡片「21 张图」+ 失效警示条、资产页「21 张 · 根目录 20 · 分镜 1」全部真图、工作台表格与顶部条均显示 21）；ComfyUI 出图实测 2 分钟、`queue_running=0`。⚠ 未做：真实云端大模型仍未接入（本机无第三方 Key，仅 Mock 自动选路） |
| **V0.7.12** | 2026-10-28 | **三通道接通：大模型真实探测 + 用途自动选路 + 资产可见性（散图）**。① **大模型探测从「查配置」改成「真调一次」**：旧实现只看「有没有 provider / 有没有 Key」，Key 过期、模型改名、`base_url` 少 `/v1`、代理拦截这四种情况全报「可用」，用户到写剧本时才发现。现在按 `providers.build().chat()` 发一条 1 token 请求（最多测 2 个提供商），失败按 `core/llm/errors.KINDS` 分类给下一步；正例（Mock 返回）与负例（端口拒绝 → network）都进测试。② **修 `has_key` 摊平 bug**：`store.public_provider()` 做的是 `out.update(key_status(prov))`，`has_key` 在**顶层**，而 `connections` 读 `p["key_status"]["has_key"]` 恒为 None ⇒ 用户填了 Key 仍被告知「缺 Key」；统一走 `_prov_has_key()`（兼容嵌套与摊平，且 mock/ollama 不需要 Key）。③ **用途自动选路**：新增 `store.auto_provider()`（有 Key 的云端 > 本地 > Mock，尊重 `requires` 能力），`list_purposes()` 与 `get_purpose()` **共用同一函数**，返回 `bound=False` + `auto=True`；新用户不再需要手动绑 10 个用途（旧行为每次生成都报「还没有绑定提供商」）。④ **资产「散图」视图**：`artifacts.loose_images()` 只读扫描根目录 + 一层子目录（跳过 `04-资产`/`06-提示词`/`07-成片`/`09-发行` 与工程目录），`/api/artifacts/loose` + 资产页第 5 个页签 + KPI 提示「另有 N 张未归档」。真实项目的图常直接丢在剧目录根下，旧视图只读 `04-资产/` 会显示空 ⇒ 用户以为产品不认识他的文件。**不移动任何用户文件**。⑤ **工作台接入状态口径统一**：机器级通道（大模型/本地出图/云端出片）只认「连接中心」的 `last_ok`，项目级（工作流 API）才认 G-0；检测按钮改走 `/api/connections/{kind}/test`，与连接中心同一条链路（以前 `diag.comfy` 抽屉与卡片两套口径，同一个 ComfyUI 一边说「在线」一边说「未确认」）。⑥ 页签写进 URL（`#/assets?tab=loose`），与 AI 模型中心一致；界面不再出现环境变量名（`test_studio_assets` 的「前端不得出现密钥字段」门禁拦下过一次）。 | `b98e0b7` | 全量 **33 个 `test_*.py` 0 失败**；`test_connections.py` 扩到 **10 组**（新增凭据摊平、自动选路、用途就绪、真实探测正负例），`test_llm_e2e.py` 用例 4 按新契约改写（未绑定不得再报 config）；真实项目 `D:/剧本/海外剧/2、母亲之路` 实测散图 **21 张**全部出图、`/media` 200 且 PNG 魔数正确；连接中心三路状态（ComfyUI v0.42.1 在线 / RH 余额 36 币 / 大模型 Mock 可调用）与工作台显示一致 |
| **V0.7.11** | 2026-10-28 | **叙事模式裁决：对白驱动（四职能回归 3D 技能）**。用户判定「旁白解说太单调」，要求把 `3d-short-drama-studio` 的**剧本解析 / 分镜设计 / 台词设计 / 视频提示词**四环节融合回来。① **性质更正**：2026-10-16 的「画风三轨接管分镜 / H3 提示词」只是**文档声明**，代码从未改口径 —— `workflow.py` S5 仍定义「分镜（11 字段）→ H3 六段式」，`convert_storyboard.py` 吃 md 不吃 json，`script_continuity.py` 解析 `subject_definitions`+`summary`，而 `storyboard.json` **无生成器、未挂门禁**（仅手动 `halfcheck` 读）。② **技能侧**：撤销 `3d-short-drama-studio` 的接管声明；新增 `references/dialogue-driven-rules.md`（旁白四用途五禁令 / 台词四功能三拍 / 分镜信息事件 / H3 装配 / 自检 10 问）；`SKILL.md` 增「叙事模式」节 + 四职能引擎落点 + FFS 落盘映射（◆字段映射进八字段，**不新增** `MOOD/FX`）；screenwriter-a/b/b-es、director-storyboarder、h3-prompter、director-core、dialogue-auditor 全部加对白驱动铁律与质量门。③ **硬指标**：旁白 **≤2 条/集、≤8 秒、只在首尾**；台词密度 **60s ≥10 句 / 45s ≥7 句**；单句 CJK ≤20 字 / 拉丁 ≤55 字符；每句须归「推进/引爆/揭示/关系」四功能，无功能**判删不润色**；判据是「删掉全部旁白剧情仍完整」。④ **文档侧**：`README` / `docs/styles/画风三轨规范.md` §四 / `生产流程总纲.md` §3.0 / `技能映射与缺口.md` G10+二之二 收回画风三轨对**叙事与提示词**的管辖权，改为「皮 / 骨」分工；`halfcheck` 标为可选（对白驱动剧跳过不影响出片）。⑤ **有意裁决**：`non_diegetic_music` 一律 `N/A`（BGM 归后期），与 3D 技能旧文本「必填画外配乐」相反，理由见 `dialogue-driven-rules.md` §5.4。 | `2641f0b` | **无引擎代码改动**（仅技能与文档），离线测试基线不变（31 个 `test_*.py` 全绿，2026-10-23）；短剧项目零改动；跑测判据 = 文档自洽 + 技能可加载（经 `~/.workbuddy/skills` 符号链接读到新口径） |
| **V0.7.10** | 2026-10-23 | **Web 工作台（Studio）+ LLM 统一网关**。① `web/ui/studio/` 12 视图（ES module，零构建零外链，删掉即回滚）；`web/core/studio.py`（聚合读）、`adapters.py`（CLI→结构化）、`artifacts.py`（路径白名单 + 媒体 Range）、`jsonout.py`（唯一 JSON 抽取）。② `web/core/llm/` 8 模块统一网关：业务只调 `gateway.complete(purpose, variables)`；**提示词不另写**（system = `stages/creation/prompts/*.md` 原文，带 `body_sha` 指纹）；能力不满足**拒发**；重试只对 timeout/network/rate_limit/5xx；金额只认供应商 `usage.cost`；Key 只进不出（`has_key`/`key_hint`）。③ **生成与落盘彻底分离**：生成只写 `<ws>/video-pipeline/llm-drafts/`，`confirm` 才写 `03-剧本/ep_NN.md`（要求显式 `overwrite` + 备份 + `expected_sha`）；**计费接口一律 428 + `confirm=true`**。④ `/` 自动进 Studio、`/ui/` 保留旧控制台；端口 **8788**；`httpx==0.28.1` 进 `web/requirements-web.txt`。说明真源 `web/STUDIO.md`。 | `2641f0b` | 离线测试基线 31 个 `test_*.py` 全绿（2026-10-23）；涉及 fastapi 的 `test_llm_e2e.py` 需用 `envs/solodrama-web` 解释器 |
| **V0.7.9** | 2026-10-22 | **H3 参考图「残留图」污染修复（图片槽位卫生）**。用户报告「调用 RH 视频工作流时，工作流默认打开的 6 张图会被当参考送进去」—— 实测确认且更严重。① **根因**：`nodeInfoList` 是**覆盖表不是完整表**，没发的节点平台沿用工作流里保存的值。H3 的 `MiniMaxH3ReferenceToVideo` 有 `ref_image_0…5` 六个 `LoadImage`（137/139/146/159/160/161），本项目只覆盖 3 个（角色 137、场景 139+159），**146/160/161 每镜都在送同一张遗留图 `cb955bf6….png`**；旧代码还留着一句「不发 = 沿用内置默认，安全」的错误断言（已删）。② **连带后果**：模型一直按 **6 路参考图**推理 —— `OOM_RETRY` 注释里「12 秒 + 6 路参考图在 24G 实例必 OOM」说的就是这 6 路，其中 3 路是废物。③ **修法**：新增槽位卫生模块（`is_image_slot` / `image_slot_nodes` / `covered_slot_ids` / `placeholder_png` / `SlotGuard` / `make_slot_guard`），运行开始时用只读接口（免费不排队）探测工作流全部图片槽，把「工作流有、本项目不覆盖」的槽位显式填 **1024×1024 中性灰占位图顶掉**；三种模式 `blank`（默认）/`empty`（传空，LoadImage 会报错）/`keep`（保留，必须写 reason，配置层也会回退）。值形态默认 `url` —— 项目历史 30 集的 `refs_used.json` 证明传 `download_url` 能出片，`fileName` 留作切换项。④ 顺带修：`build_node_list` 按 (nodeId, fieldName) **先到先得去重**（真实值永远赢过填充值）；`empty` 模式的 `""` 不再被当空节点丢弃；补上 `h3.nodes` 的结构校验。⑤ 可观测性：运行开头打印「工作流 N 个 ｜ 覆盖 M ｜ 未使用 K」；`--dry-run` 逐条预演「哪个槽位被顶掉、原默认是什么」；`--probe` 每行标注「图片槽·已覆盖 / 图片槽·未使用」；探测失败会明说「本轮未使用槽位会沿用工作流里的图」；配置指向不存在节点时告警 `ghost`。 | `待回填` | 新增 `engine/tests/test_slot_hygiene.py` **32/32**；全量离线 **678 例 0 失败**；真实工作流 dry-run：`6 / 3 / 3`，`nodeInfoList` 里 160/161/146 变占位图、`cb955bf6….png` **完全消失**；`--probe` 实测逐行标注正确；占位图上传成功（`fileName=openapi/53f46d3d….png`，5334 B）。⚠ **真实出片未验证**：账号返回 `errorCode=605 余额不足`，充值后跑一镜 `--video-only --only ep01_sc01 --limit 1` 即可闭环（详见 `docs/patches/2026-10-22_H3参考图槽位残留修复记录.md` §三） |
| **V0.7.8** | 2026-10-22 | **开工前必须定下 API Key + 放大产物正名为 1080P + 歧义全量排查**。① **账号 API Key 改恒必填**（用户要求「开工前需要把 API key 确定下来」）：旧口径「无 RunningHub 通道就自动判无需」等于从没问过 → 现在两种合法终态都必须显式拍板：登记真实账号（别名+指纹+站点），或 `--account none --account-none-reason "<理由>"` 声明不需要（理由入单留痕）；只写 `none` 不给理由仍退出码 4；有云端通道时 `none` 直接非法。第 6 项工作流 API 仍按通道条件化（本地项目确实没有工作流）。② **放大产物正名**：`<ep>_master_2k.mp4` 实际是 **1080×1920**（`config.upscale.json` 的 target 就是 1080x1920），名字却写 2K —— 用户正是照这个名字提出「不要 2K 要 1080P」→ 改为 `<ep>_master_<W>x<H>.mp4`（竖屏 `ep03_master_1080x1920.mp4`），**旧名只读回退**（老项目不迁移），在跑项目 30 集已改名；`bgm`/`release_export`/`workflow` S9 判据/字幕管线全部改为"新名优先、旧名兜底"，发布导出的 `master_res` 档排在 `_master_2k` 之前。③ **`--ep` 两种写法只有一种对**：`--ep 26` 能过校验、也能匹配分镜，但 align/cues 路径被拼成 `subs/26/` ⇒ **静默产出 0 条字幕**还建了个空目录 → 三处入口统一 `canon_ep()`（`26`/`ep26`/`EP26`/`ep026`→`ep26`，非数字报错退出码 1）。④ **两份「高清放大」文档都指向不存在的文件**（`<ws>/docs/高清放大-2K-实测与操作手册*.md`）→ 245 行手册改名 `hd-upscale-case-2560x1480.md` 并注明"2k 是历史叫法"，两处引用改为仓库内相对路径。⑤ 歧义清单成文：`docs/orchestration/项目流程与设定对账_20261022.md` §九（母版四义、2K 三义、字/秒两义、续跑两义、退出码三分法、G 编号两套、voice 两处同义）。 | `待回填` | `test_setup_workflow_pipeline.py` **54/54**（账号必填三态：未声明/无理由/合规）；`test_subtitle_alignment.py` **38/38**（新增 `TestEpisodeId` 3 例）；`test_bgm.py` **41/41**（新名优先 + 旧名可读）；`test_release_export.py` **14/14**（新名优先于 `_master_2k`）；在跑项目 `--ep 26` 由「0 条」变「ep26 ｜ 6 条」，改名后 `workflow status` S9 **30/30**、`setup require` **9/9** |
| **V0.7.7** | 2026-10-22 | **流程与设定全量对账（4 处真冲突已修 + 8 处口径不一致已写明 + 1 处命名撞车已标注）**。产出 `docs/orchestration/项目流程与设定对账_20261022.md`（一张图 + 五层真源裁判权 + 冲突台账）。修掉的 4 处真冲突：① **`workflow.py` S10 印着不存在的 `--sync-from`** —— 那是 2026-10-21 补丁单的**建议**被当成已实现抄进去了，照机器真源敲命令直接 argparse 报错；改为真存在的 `--stage align`，并把补丁记录 10.4 从「未修」回填为「已落地（换了做法）」。② **`bgm check` 与 `bgm mix` 读不同增益** —— `sync_plan_gain` 只在 mix 里调用，于是同一集出现「check 报 FAIL（-20.4 LUFS 会压对白）、mix 却成功（实际用 -14.6dB）」（实测 ep29，30 集旧计划全是这状态）→ `cmd_check` 先做同样校正（只改内存不写盘）再判门禁。③ **S6 判据按文件数而非镜头数** —— 本项目 240 镜报成 284/240 达标（返工的新批次没删旧批次，同一镜多份 `final.mp4` 各算一个），缺 20 镜也看不出来 → probe 支持 `count: parent` 按镜头去重。④ **总纲环节 14 把封面主路径写成 `cover_forge.py`**（与 README/发行清单/workflow 的「`cover_prompt.py` AI 直出带字为主、forge 仅兜底」相反）→ 已同步。另：`es.cps_ok` 下限 6.0 → **3.0**（6.0 会把「23 字铺 6.2s = 3.7 字/秒」这种正常台词判成异常，与代码「偏慢不是缺陷」的判断相反）；G-1 改为「G-0 的第 1 项」；`标准作业流程.md` 补「G6 停点只对手动逐集跑生效，pipeline 不停」；`技能映射与缺口.md` 的 G1–G10 是**缺口编号**、总纲 G-0…G11 是**门禁编号**，同字母不同义已在文档里标注。 | `待回填` | `test_bgm.py` **39/39**（新增 `test_76`：check 与 mix 必须读到同一个 dB 值）；`test_setup_workflow_pipeline.py` **53/53**（新增 `test_26b`：S6 按镜头去重，两批次 4 个文件只算 2 镜）；在跑项目 `workflow status` S6 由 `284/240` → **`240/240`**；`bgm check ep29` 由 2 个 FAIL → **通过（可混音）**且显示 `-14.6 dB`；`setup require` 9/9、`workflow status` 11/11 复核通过 |
| **V0.7.6** | 2026-10-22 | **字幕纵向落点改「视觉中心 6:4」**（移植自 vidpure 的 `Placement(anchor="ratio", anchor_top=0.6)`，用户看过 V0.7.5 成片后提出「字幕在这个位置更好」）。① 口径：文字块**中心**落在 `0.6 × 画面高`（距顶:距底 = 6:4），1080×1920 上 `y=1152`、文字块下沿距底 **696px**（安全区下限 400px 未放松）。② 实现改用 `{\an5\pos(W/2,y)}` **逐条**定位，不再依赖样式 `MarginV` —— 关键收益是**一行与两行字幕的中心同线**：旧口径 `Alignment=2`（底对齐）折行时文字往下长、整块上半部分空出来，连续台词在"一行↔两行"间切换时字幕会跳；`\an5` 以块中心为锚点，行数变化不动位置。③ 顺带修掉**换分辨率漂移**：固定 400px 在 1080×1920 占 20.8% 高、在 2176×3840 只占 10.4%，同剧出 1080P 与 2K 两版字幕位置不一致；6:4 是比例，任何画布视觉重心一致。④ `qa_safe_area()` 改**分模式断言**：ratio 判 `\pos` 实际落点 + 「所有条目 y 相同且等于设计值（容 1px）」+ 文字块下沿距底 ≥ `min_bottom_px`；pixel 模式仍判 `MarginV`；`anchor_top` 调到贴底时按安全区**上顶**并置 `anchor_clamped`。⑤ `verify_render()` 的字幕带跟着 `center_y ± 块高/2` 取窗（旧口径会把画面下半部分都当字幕带，`diff_rest` 被拉高、判定失真）。⑥ 配置新增 `placement` 块（`anchor_top` 调法 + `anchor:"pixel"` 回退说明），示例配置与在跑项目均已写入。 | `待回填` | `test_subtitle_alignment.py` **35/35**（新增 `TestVisualCenter` 6 例：默认 6:4、三种竖屏分辨率比例恒定、一行两行同中心、pixel 模式仍可用、`anchor_top` 过低被上顶、QA 抓出错落点）；`test_safe_area.py` 三套画布 × 两语言全通过且新增「所有条目 y 一致 = 0.6H」断言，篡改 `\pos` 能拦住（`落点 y=1900 与设计值 1152 相差 >1px；下沿距底 -36px < 200px`）；ep26 重烧 65.8s，ASS 6 条全为 `{\an5\pos(540,1152)}`，`⑦ 渲染自检（字幕带 y=1032–1272）` 字幕带差异 10.7 vs 其余 0.9 |
| **V0.7.5** | 2026-10-22 | **字幕烧录（S10）四层故障修复 + 后期收尾/配乐/出片引擎并发症**。输入是 30 集实跑的调试日志包（395 条任务 / 52 条失败 / 9270 RH币），逐条定位到根因：① **伪对齐当缓存**——项目侧 `gen_align_estimate.py` 写的 `method=script_estimate` 记录被当有效缓存，`--stage align` 见文件存在就跳过，CTC **一次都没跑过**（实测 ep26_sc02 估算 0.56–6.75s vs 真值 3.32–6.26s，起点偏 2.8s）→ 缓存改「看方法不看存在」，估算档一律重建，report 增 `align_methods` 逐段写明；并把该脚本改为停用说明页。② **`[Música]` 被当语音**——whisper 给纯音乐段输出 `[Música]`，旧代码当「有语音」，覆盖检查大面积误报，还据此把首条字幕**前移到静音上**（ep26_sc02 从 3.22 拉到 0.00，那段 RMS 只有 53–234）→ 新增 `is_nonspeech` 过滤 + `window_loud_fraction` 声学复核。③ **条目层缺口**——旧 `asr_burn.align_to_script` 只保留剧本台词行、**丢弃所有未匹配 ASR 条目**（ep25 剩 1 条/4.4s、ep26 剩 4 条/11.4s，每集 62s）→ 重写 `tools/asr_burn.py` 改读引擎 `cues.json`（只保留封面首帧与直烧）；引擎新增 `asr_fill_segment`：剧本无台词的镜头用 ASR 补位并标 `asr-unscripted`。④ **相似度口径**——`set()` 字符重叠会误配并把整集粘成一条（38 条→4 条）→ 改 `difflib` 比率（0.45/0.25）。⑤ 移植 vidpure 的 `loud_intervals` + `tighten_to_audio`（含「缩了就念不完」护栏）做字幕首尾收紧；⑥ 修 **对齐器无超时**（`aligner_timeout_s` 写了从没接线，死锁时整集挂死）；⑦ 修**段起点按写死 24fps 推算**（非 24fps 素材累计偏 4–6s）；⑧ 修西语断行「取第一个装得下的切点」把语义切碎（`Mintió` / `para salvar…`）→ 按 Netflix 断点分级（句末>分句>长度）；⑨ `<d>台词</d>` 无方括号时被静默丢弃 → 正则放宽；⑩ 语速「偏慢」不再逐条报警（停留含停顿属正常，改为汇总一行）。并发症：⑪ `upscale.py` 批量删除触发 safe-delete 钩子（ep28–30 Topaz 100% 后进程被杀）→ 删除预算自我设额；⑫ `state.json` 固定名临时文件 + 多进程抢写（`Errno 13` ×20 / `WinError 32` ×1）→ pid+tid 唯一名 + 指数退避；⑬ 上传无重试（`ReadError` ×8 白跑）→ 包 `retry_async`；⑭ BGM 门禁三方口径不一致（plan 报 FAIL / mix 照混 / 增益被偷偷改）→ plan 不写失败计划 + `--force-gain` 锁定。逐条对照见 `docs/patches/2026-10-22_字幕与后期故障修复记录.md`。 | `待回填` | 新增 `stages/subtitle/scripts/tests/test_subtitle_alignment.py` **29/29**；全量 **27 个测试文件 0 失败**；真实项目 `D:/剧本/海外剧/2` ep26：重对齐（伪对齐重建 4 段 + ASR 补位 2 段）→ 条目 4 条/30.75s 变 **6 条/43.29s**、假缺口 4 段 20.5s 降 **2 段 4.9s** → `--stage render` 64.8s 完成且渲染自检通过；抽帧目视 t=1.5s **无字幕**（此前会被前移到 0.00）、t=4.5s 正常两行且落安全区 |
| **V0.7.4** | 2026-10-21 | **6 首 AI 曲目改记「自有版权」（`owned`），并修 `credits` 把自有版权误标成「需署名」的 bug**。① 用户声明这 6 首由本人用 AI 生成、**版权归己**，于是 `license: generated`（条款待补）→ **`owned`**，另加 `origin: ai_generated` 保留「AI 生成」这一事实（部分市场要求披露 AI 生成，别写成"原创配乐"）。② 修 `cmd_credits`：原来 `need_credit = license != "cc0"`，会把 `owned` 也标成「需署名」并输出 `Music: ...` 署名段 —— 自有版权**不需要对外署名**，现在标 `[自有]` 并提示「无需对外署名」。③ `bpm` 从「必须人工填」改为**可选**：短剧铺底不跟 BPM 走，只有卡点剪辑（预告/混剪）才需要，别为它设不必要门槛。④ 文档口径统一：库 README 字段表、`BGM与音频设计.md` §四（四种 license 的语义与署名义务）、`BGM生成提示词.md` 交付要求（先问平台条款，明确的记 owned）。 | `78925a9` | `test_bgm.py` **38/38**（新增 1 例：`owned` 不标需署名、不输出 `Music:` 行）；既有 20 个测试文件全绿（合计 **564 例**） |
| **V0.7.3** | 2026-10-21 | **AI 生成 BGM 入库 6 首 + 增益改按实测响度反推 + ducking/deck 参数实测校正**。① 用户用 AI 音乐平台生成 6 首（Quiet Tension / Subtle Pressure / Silence / Steady Fury / Tender Reunion / No Words）入库，**原样复制不转码**，库共 **18 首**。② 入库体检发现关键问题：**这批曲子母带响度跨 13.5 dB**（-13.7 ~ -27.2 LUFS），加上预置库的 -6.8 ~ -28.6，全域跨 **22 dB** —— 统一 `-22 dB` 之下的"铺底"有时震耳朵、有时听不见。改为 **按 EBU R128 实测响度反推**：`gain = (-33 LUFS + 情绪偏移) - loudness_lufs`。③ 门禁口径同步改：判的是**最终铺底响度**是否落在 `[-42, -25] LUFS`，不再看相对增益大小（否则"原本 -38 LUFS 的曲子提 4 dB"会被误判为增益过高）。④ 新增 `library --scan --loudness` 补实测响度，并修 `--scan` **只回写项目库、共享库永远补不上**的缺陷（改为按条目来源分别回写）。⑤ 新增 `sync_plan_gain()`：库里增益被校准后，旧计划里写死的 `gain_db` 会在 `mix` 时自动校正（差 >3 dB 触发，可用 `gain_locked` 锁住）——实测救了 ep01 的旧计划（-22 → -10.1，否则铺底会低到 -44.9 LUFS 等于没铺）。⑥ **ducking 默认值实测校正**：`threshold` 0.05 → **0.15**、`ratio` 6 → **4**、`release` 350 → **300** ms —— 短剧人声连续，0.05 意味着整集都在压缩区，BGM 被压到听不见。⑦ 用发布版 Episode01 做试听样片验证：片尾静音段从 **-52.4 dB → -38.6 dB**，正文段抬 15–17 dB。 | `6c55ffc` | `test_bgm.py` **37/37**（新增 6 例：最终响度门禁双向、轻曲提增益不误杀、按 LUFS 反推、旧计划校正、`gain_locked` 生效）；既有 20 个测试文件全绿（合计 **563 例**） |
| **V0.7.2** | 2026-10-21 | **新增 `docs/production/BGM生成提示词.md`：给 AI 音乐平台（MiniMax / Suno / Udio）的 12 条提示词**（6 情绪 × 主用/变体）。先把「什么样的 BGM 才混得进去」写成六条硬约束：**纯音乐无人声**（含哼唱/vocal chops）、**无旋律主线**（避免记忆点抢戏）、**无突袭音效**（no hits/stingers/risers，否则与剪辑点打架）、**无前奏无 drop**（一集 60 秒，前奏 8 秒等于白铺）、**可无缝循环**、**中低音量铺底**（underscore / sits under dialogue）。每条提示词含曲风 + 情绪 + 乐器编制 + BPM + 调性 + 结构约束，可直接粘贴；另给 negative 词表与参数建议（时长 90–120s、小调、60–120 BPM、`[Instrumental]`）。第三、四节写清交付要求（**原始文件、不做压剪与响度统一**、附平台商用条款截图 —— 这是库里 `license=generated` 必填 `license_note` 的依据）。 | `3411550` | 纯文档改动，`manifest.sha256` 212 条 0 不符 |
| **V0.7.1** | 2026-10-21 | **BGM 库落地：预置 12 首可商用配乐 + 库可再生 + 署名段**。① **实测 Pexels 无法提供 BGM**：其 API 只有 `photos` / `videos`，`/v1/audio`、`/v1/music`、`/v2/audio` 全部 404，视频本身也不带音轨 —— 所以改用 **Wikimedia Commons**（授权字段结构化，判定可商用最可靠）。② 预置 **12 首**按 6 类情绪各 2 首，全部 **CC BY 3.0/4.0**（可商用、须署名），清单落 `stages/production/assets/bgm/bgm-library.json`（含 artist / license_name / source_url / attribution / license_note，可审计）。③ 新增 `stages/production/scripts/fetch_bgm.py`：**库可再生** —— 音频不进 git，换台机器跑 `--apply` 按同一套检索与过滤口径重新抓回；过滤规则写死（只要 CC0/PD/CC BY，排除 BY-SA 传染性、NC 不可商用、ND 不能混音；排除访谈讲座录音；排除西部/凯尔特/中世纪/爵士等会把观众拉出剧情的风格；时长 40–300 秒）。④ 新增 `bgm.py credits --ep epNN`：输出可粘进发布文案的署名段（CC BY 的署名义务，`Music: 作者 — “曲名”（CC BY x.x，via Wikimedia Commons）`）。⑤ 选曲加 **LRU**：扫已有计划文件，优先「最久没用过」的曲目 —— 整剧几十集不重复同一首（平台会判相似内容降流）。⑥ **补 `.gitignore` 规则**：此前库 README 写着「音频不进 git」但没有任何规则，一旦把音频放进共享库就会被推上公开仓库（已用探针验证忽略生效）。 | `85d8a1a` | `test_bgm.py` **31/31**（新增：LRU 不重复、credits 输出署名、无计划时退出码 2、测试与真共享库隔离）；既有 20 个测试文件全绿（合计 **557 例**）；真实剧 `D:/剧本/海外剧/1` 上跑通 `plan --apply` + `credits`（自动识别为 tension 情绪、60s 成片、署名段可直接粘贴）；音频 12 首经探针验证**未进 git** |
| **V0.7** | 2026-10-21 | **BGM（配乐）全链路：库 → 铺排计划 → 混音，并把「禁模型自造配乐」写进提示词**。起因：已交付的几部剧在出片与后期都没有 BGM，而短剧的留存曲线在静音段掉得最快。**结论：BGM 不交给视频模型**——逐段生成给不了「贯穿整集可循环 / 可换可证版权 / 不盖对白」这三件事。① 新增 `stages/production/scripts/bgm.py`：**库**（项目库 `<ws>/04-资产/bgm/` + 引擎共享库 `stages/production/assets/bgm/`，项目库优先；`library --scan` 用 ffprobe 补时长，BPM 不猜）→ **铺排计划**（情绪 → 增益/淡入淡出 → `<ep>_bgm-plan.json`；增益优先级 命令行 > 曲目建议值 > 情绪默认表）→ **混音**（`filter_complex`：视频 `-c:v copy` 只重编码音频，`sidechaincompress` 做对白 ducking，`-stream_loop` 支持短曲循环）。② **门禁 5 条**（退出码 2）：`license` 必须为 `owned/licensed/cc0/generated`、`generated` 必须写 `license_note`（AI 音乐商用条款，平台抽查与 Content ID 争议都要用）、`gain_db` 不得高于 -6、BGM 覆盖 ≥ 成片 90%、`voice=h3` 时 ducking 不得关闭。③ **提示词侧分工**：`convert_storyboard.py` 默认给每条 H3 提示词追加 `[AUDIO]` 段（只允许同期声，显式禁 `background music / score / melody / drum loop / stingers`）——不写清楚模型会自己垫一层音乐，与后期 BGM 双重铺底、相位抵消、音量台阶且无法调参（可 `--no-audio-direction` 关）。④ **S10 从「字幕烧录」扩为「音频与字幕」**：`subtitle.py --stage render` 检测到计划就混出 `<ep>_mix.mp4` 并以其为底片烧字幕；三条自动降级（无计划 / 已有更新混音版则复用 / 环境无 bgm.py 时打印手动命令后继续）——**没有 BGM 也要能交片**。⑤ 新增规范 `docs/production/BGM与音频设计.md`（四层结构、参数调法、版权纪律、5 个常见问题）。⑥ `drama.py` 增 `bgm` 转发子命令。 | `269352e` | 新增 `test_bgm.py` **28/28**（含 1 例真混音：造 2 秒视频+正弦，断言时长一致、音视频流都在）；既有 20 个测试文件全绿（合计 **554 例**）；真实素材端到端验证过 plan → check → mix → 字幕钩子复用/现混两条路径 |
| **V0.6.1** | 2026-10-21 | **开工前置条件 7 项 → 9 项：补上「工作流 API」与「账号 API Key」，且必须问到具体值**。① 第 6 项 **工作流 API**：`workflowId`（或 AI 应用地址 / 云端 ComfyUI 服务地址+工作流文件）+ **站点**，三者缺一即拦；站点只接受 `https://www.runninghub.ai` / `.cn`（写错退出码 2，否则上传会报「API Key 不存在」）；可从 `model-plan.json` 的执行依据**自动推断**，不必抄两遍。② 第 7 项 **账号 API Key**：只登记 `别名 + 指纹(sha256前8…后4) + 来源(环境变量名)`，**Key 本体永不落盘/不进日志**；`require()` 每次读当前环境 Key 比对指纹，不一致 → 退出码 4 并明示「会花错账号的钱」；`pipeline run` 在**每个计费环节之前**再比对一次（流水线跑几小时，中途换 Key 也拦得住）。③ 新增 `drama.py setup accounts`：列出本机可用账号（含 `<ws>/keys.json` 多账号清单，只显示指纹与站点），`--account-source <环境变量名>` 支持多账号切换。④ 两项按通道**条件化**：全本地/闭源自动标「无需」不拦，只要有一条 RunningHub 通道即变硬性必填。⑤ `pipeline plan` 开工预告新增「工作流 API / 账号」两行。⑥ 顺带修 `render` 的编号重复（生图/视频都标 4）与 `--workflow-id` 需抄两遍的问题。 | `f577951` | `test_setup_workflow_pipeline.py` **52/52**（新增 10 例：条件化、站点校验、指纹不落盘、账号漂移拦截、`accounts` 不显示 Key）；既有 19 个测试文件全绿（合计 **526 例**） |
| **V0.6** | 2026-10-21 | **标准作业流程（11 环节）+ 开工前置条件（7 项）+ 流水线模式；并按实跑优化建议单修 19 条**。① 新增 `stages/production/scripts/workflow.py`：11 环节机器真源（调研→剧本→资产设计→资产生成→视频提示词→视频生成→发行资料→拼接→放大→字幕→定稿），每环节有**产物判据**与**顺序门禁**（`check` 不过退出码 4），跳过必须 `--reason` 留痕；真源文档 `docs/orchestration/标准作业流程.md`。② 新增 `project_setup.py`：开工前置 7 项（画风 / 集数 / 每集时长 / 生图模型 / 视频模型+功能选项 / 分辨率 / 是否流水线）收成一张确认单 `<ws>/project-setup.json`，单一门禁 `require()`（未齐退出码 4）；不另立真源（画风仍写 `style-plan.json`、通道仍写 `model-plan.json`）。③ 新增 `pipeline.py`：流水线模式 —— `plan` 先报**预计完工时间与花费**（不花钱），`run --yes` 无人值守一次跑到底，**每个计费环节之前核对预算上限**（超限退出码 3），内容环节停点给作业单（退出码 4）由 Agent 补齐后 `mark` 继续。④ 三条命令接进统一入口：`drama.py setup / workflow / pipeline`。⑤ 修复实跑反馈单：`_num()` 与 `subtitle` 的 shot_id 死锁（10.3/9.4）、`convert_storyboard` 分流 `character_refs`/`scene_refs`（9.3，且只在顺序不变时才拆）、`STYLE_LOCKS` 改读 `style-plan.json`（2.4）、中文服装段英译 `garment_en`（7.1）、cfg=1 负向词失效主动告警（1.1）、种子字段名不再静默（1.3）、`h3_prompts` 增 `voice` 字段（10.1）、`cost_model` 吃 `steps`/`megapixels`（11.1）、默认并发 2（11.3）、`release_export` 同集取 mtime 最新（10.8）、`E007` 支持西语断句与拉丁 55 字符档（2.1/2.2）、`E006` 总时长 ±2s 容差（4.x）、`E009` 报错文案（5.x）、`assets_dir` 进布局白名单（4.2）、剪影分镜 11 条硬约束写进画风规范（8.x）。逐条对照（含未修项与原因）见 `docs/patches/2026-10-21_实跑优化建议修复记录.md`。 | `649a77f` | 新增 `test_setup_workflow_pipeline.py` **42/42**；既有 19 个测试文件全绿（合计 **516 例**）；`manifest.sha256` 204 条自校验 0 不符；真实项目 `D:/剧本/海外剧/1` 上 11 环节判据全部识别正确 |
| **V0.5** | 2026-10-20 | **本次发布合集（6 部分）**：① 实跑反馈单 26 项修复 ② 封面引擎收编进仓库 ③ 封面改为 AI 直出带字 ④ 剧本改写「四段法」（诊断 → 骨架 → 正文 → 观众验收）⑤ 默认口径下调 **30 集 × 60 秒** ⑥ 开工前环境自检（`tools/env_check.py`）。逐项明细见本表下方的「V0.5 明细」。 | `a47a312` | 17 个离线测试文件 0 失败（creation 层 215 例）；`manifest.sha256` 198 条 0 不符；远端由 V0.4 快进至 V0.5 |
| **V0.4** | 2026-10-20 | **新增「角色差异化」能力（解决同剧组人物撞脸）**：① 新规范 `docs/assets/角色差异化设计规范.md` —— 五根因（含两部在跑项目的实测证据：10 人剧仅 2 人写脸型、7 人「浓眉」、3 人无识别锚；5 人剧 0 人写脸型）+ 六维签名（骨相/发型/眉眼/色签名/材质/识别锚）+ 六条硬规则 R1–R6 + 提示词三件套（识别锚前置 / 反默认 / 差异对照）；② 新增 `stages/assets/scripts/character_design.py`（纯标准库、确定性、零计费）：`plan` 按人群桶 + 最大最小距离贪心分配六维签名，产出 `character-bible.json` / `角色差异化矩阵.md` / `资产提示词_角色段.md`（可直接喂 `gen_char_assets.py`、`asset_md.py`）/ 三件套逐角色提示词（设定板 · 主卡 · 定妆照）；`check` 六条硬规则门禁（退出码 2）；`audit` 体检老项目同质化（含维度覆盖率）；③ `prompt_templates.build_char(it, design=None)` 支持差异化注入（识别锚/差异对照/色签名/反默认/可配置 `world`），**design=None 时行为与旧版逐字一致**；④ 词库按人群桶收敛体态与面料、按性别收敛下装鞋履、按族裔改口骨相措辞，避免「野性转校生穿真丝缎」「男角色穿高跟鞋」这类身份与材质打架；⑤ 总纲新增 §3.8 与环节 6／文档索引更新；⑥ 新增 28 例离线测试 | `55381a4` | `test_character_design.py` 28/28、`test_prompter.py` 28/28、`test_asset_md.py` 19/19；生成提示词过净化器三项自检 0/0/0；产物全 LF |
| **V0.3.2** | 2026-10-19 | **新增「怎么跟 AI 助手说」的交付物**：① `docs/新项目启动提示词.md` —— 最短版一句话 / 完整版开工提示词 / **让助手用上新版本的三条机制** / 老项目「资产归位 + 发布版改名」两条命令 / 「想确认本地是否最新」的判据 / 常见追问模板；② README §4.1 置顶指向该文件，文档索引同步（README + 总纲）；③ 两个不引用仓库的驱动型技能正文补「规则真源在 SoloDrama 仓库，冲突以仓库为准」指针：`short-drama-production`（生产执行端）、`drama-cover-forge`（封面/发行端）——**技能 description 未改动**（不影响路由） | `aac8e98` | 纯文档改动；`manifest.sha256` 重建后自校验 0 不符 |
| **V0.3.1** | 2026-10-19 | **把「落点与命名」两次事故写进项目（文档修正，无代码变更）**：① 新增 `docs/patches/2026-10-19_落点与命名事故复盘.md`（保留用户原话 + 现象/根因/修法/三层防复发/交付前自检 5 问）；② `stages/production/references/pitfalls.md` 追加 **§F 落点与命名**（6 行现象-根因-修法，含「注释把 bug 固化成事实」「JSON 双反斜杠致改写恒为 0」「零迁移兼容」三条陷阱）；③ README §4.1 增「**给 AI 助手的三条红线**」提示块（资产落 04-资产 / 发布版 EpisodeNN / 不许临时起名挑目录），文档索引与契约表同步；④ 总纲、发行资料清单互链 | `f6eca47` | 纯文档改动；`manifest.sha256` 重建后自校验 0 不符 |
| **V0.3** | 2026-10-19 | **① 发布版剧集命名硬规则**：严格 `EpisodeNN.mp4`（`Episode01` … `Episode40`，≥100 集自动加位），落 `09-发行/剧集/`；新增 `stages/production/scripts/release_export.py`（默认干跑，自动探测来源，同集取「最接近可发布」的那份）+ 13 例离线测试；`release_check.py` 增「发布版命名与集号连续性」检查。**② 资产落点硬规则**：人物/场景/道具出图产物一律落 `04-资产/{characters,scenes,props}`，**不再进 `07-成片/assets`**；`_layout.py` 新增 `assets_dir()` / `assets_rel` / `release_episode_name()`，`scaffold` 自动建资产子目录并回填 `config.local.json` 的 `assets_dir`；4 个资产生成器 + 2 个消费侧改口（零迁移兼容：老项目未迁移前自动沿用旧位置并给出迁移提示）；新增 `stages/production/scripts/migrate_assets.py`（默认干跑、先备份、改写清单绝对路径）+ 16 例离线测试；控制台 `inventory.py` 同步。**③ 文档**：总纲新增 §3.7 落点与命名硬规则、环节链 6/7/14 更新；发行资料清单改为五类（剧集 + 封面 + 文案 + 发布清单 + 版权资料）并新增 §二 发布版命名 | `27ab7e3` | `test_release_export.py` 13/13、`test_migrate_assets.py` 16/16、`test_release_check.py` 15/15；既有 **53 + 41 + 29 + 23** 例全绿；`manifest.sha256` 重建后自校验 0 不符 |
| V0.2 | 2026-10-18 | **新增「发行资料」全链路**：① 单一真源 `docs/distribution/发行资料清单.md`（封面「抓马度」六抓手 + 版权资料 **4 张 AI 生成过程截图 + 4 张原始文件/素材文件信息** + 文案六槽位 + 发布清单）；② 确定性门禁 `stages/production/scripts/release_check.py`（离线、零第三方依赖，退出码 2）+ 11 例离线测试；③ 总纲补环节 14 与 **G9 发行资料门禁**；④ 新增 `docs/patches/产线对账关卡_2026-10-18.md`（40 集实跑的 26 个坑 → 自动/人工对账项）；⑤ 回填产线补丁 P1–P6（`ingest_check.py` 两处逻辑修正、`pipeline.py` 画幅 `value_map`、`runninghub_client.py` v2 提交通道与直链下载鉴权、`model_gate.py` 新增「RH 工作流出图」通道、`.gitignore` 排除 `web/var/`）；⑥ Web 控制台 `web/` 首次入库 | `180cf7c` | `test_release_check.py` 11/11 通过；`manifest.sha256` 重建后自校验 0 不符；线上 tree 与本机逐 blob 一致 |
| V0.1 | 2026-10-16 | 统一编排层基线：端到端链路（15 环节）、门禁 G-1–G8、画风三轨规范、分阶段目录规范 `layout.json`、留存率导向剧本结构、`09-发行/` 目录占位 | — | `manifest.sha256` 114 条 0 不符 |

<details>
<summary><b>V0.5 明细（V0.5-1 → V0.5-6，按时间顺序）</b>　　原 V0.5 / V0.5.1 / V0.6 / V0.7 / V0.8 / V0.8.1 均已合并为本版组成部分，不再单独占版本号。</summary>

<br>

**V0.5-1 · 实跑反馈单修复（26 项）**（原 `V0.5`，2026-10-20）

**按实跑反馈单逐条处理（10-19/10-20；24 修 / 3 部分 / 2 未修 / 5 属技能侧）**：P0 —— 只读探针（禁 `/run` 探测）、剧名去硬编码、`inflight.json` + 收尾缺口校验（退出码 3）、阶段 README 写绝对路径；P1 —— 全局 `--workspace`、依赖自检、`status` 场景计数、无执行器通道禁止确认、`instanceType` 接线 + OOM 三级降级、下载重试 + `resume-download`、`421` 退避重试、放大链路 libass 探测；P2 —— `cost_model.py`（固定+变动/分 tier/GPU 秒/自校准）、workflowId 反查、`plan --from-outline`、`TIME`→光位、E012 非法字段行、字幕单一模板硬校验、切点音频淡入淡出、单例锁、工作流静态自检。未修 3 项（尾帧接力 / 多角度参考 / 水印自动识别）已在记录里写明设计与所需信息

> 验证：离线 311 例全绿（含新增 50 例；`test_migrate_assets` 3/16 → 16/16）

<br>

**V0.5-2 · 封面引擎收编进仓库**（原 `V0.5.1`，2026-10-20）

**封面引擎收编 + 修 P1-9/10/11**：`cover_forge.py` 与三份封面规范从 WorkBuddy 技能 `drama-cover-forge` 收编进仓库（`stages/production/scripts/` + `references/cover/`），技能侧改为转发壳；① 色条改用 `textbbox` 真实字形底边（旧 `1.12em` 经验值比逗号底边还高 1px，实测压字）；② 副标走 `fit_font` 自动收缩（9:16 长副标曾右侧裁字），`--check` 报出需缩到多少 px；③ `--check` 对「窄源图→宽幅」主动告警，`size-specs.md` 新增 §3.3 竖/横底图分开生成；④ 新增 `--workspace`（spec 未写 out_dir 时落 `<发行目录>/封面/`）与 `--out-dir`；⑤ 新增 16 例离线测试

> 验证：`test_cover_forge.py` 16/16；9:16 / 3:4 / 16:9 三档真图复出，逗号完整

<br>

**V0.5-3 · 封面改为 AI 直出带字**（原 `V0.6`，2026-10-20）

**封面改为 AI 直出带字（否决程序叠字）**：新增 `stages/production/scripts/cover_prompt.py`（五段式提示词编译 + 标题自动断行 + 出图前体检；`--emit comfy` 出本地 ComfyUI 清单、`--emit rh` 出 RunningHub 计划）；新增规范 `references/cover/prompt-guide.md`（五段式结构、排版指令词典、抓马六抓手→提示词映射、文字拼错五级处置、12 条验收）；`style-presets.md` 从「暗罩参数」改写为「风格锚 + 光位 + 文字处理」，六套预设映射到 `--style`；`cover_forge.py`（PIL 叠字）**降级为兜底**；`release_check` 放宽封面多候选命名（`cover_9x16_00.png`）；技能 `drama-cover-forge` 的工作目标/流程/交付标准整体重写

> 验证：`test_cover_prompt.py` 38/38；全量离线回归全绿

<br>

**V0.5-4 · 剧本改写「四段法」**（原 `V0.7`，2026-10-20）

**剧本改写改为「四段法」（诊断 → 骨架 → 正文 → 观众验收）**。起因：`plan` 产出的 40 集四件套格式齐全但内容同质（句库拼装），且写完只验格式不验观看体验。① 新流程真源 `docs/creation/剧本改编四段法.md`（四段产物 / 门禁 / 情绪承诺表 / 题材分轨 / 四条最易犯的错）；② `script_rewrite.py` 新增三子命令：`diagnose`（A 选题诊断七问 + B 改编策略四类改动 + C 故事主线，`--check` 校验必填、`--confirm` 落确认位，**未确认禁止 `build --emit`，退出码 4**；预填只带事实型上下文，判断型字段留空）、`review`（第二轮结构审查 10 项确定性体检：主角主动率 / 反转是否改格局 / 冲突推进与重复 / 钩子因果 / 情绪是否设计过 / 爆点间隔 / 句库残留 / 前三集 + `--write-fixes` 出待改清单；**句库残留会把表面 OK 降级为待人工复核**，避免「40 集套话 + 报告全绿」）、`audience`（第四轮观众七问，校验答满 / 引用具体集号 / Q7 恰好 3 条带改法）；③ 新增 `stages/creation/references/genre-profiles.json` —— 复仇逆袭 / 甜宠 / 悬疑 / 家庭伦理四类**结构侧重表**（受众承诺 / 情绪序列 / 主动与格局信号词 / 必检项 / 题材红线 / 改法提示），`review` 按 `must_check` 把 WARN 升级为 FAIL；④ 新增提示词 `prompts/s3a-diagnosis.md`、`prompts/s3c-audience-review.md`，`s3-script-rewrite.md` 改为只负责第 ③ 段并加四段路由表；⑤ `plan --from-outline` 支持第 5 列情绪，`plan` 落 `structure_profile`；⑥ `status` 增加诊断卡 / 结构审查 / 观众审稿三行状态；⑦ 新增 47 例离线测试；⑧ **下游联动（防「剧本一个内容、提示词另一个内容」）**：`plan` 每集输出 `plot_points`（`EPnn-P1..P4`，供分镜声明服务哪个节点）；新增 `stages/production/scripts/script_continuity.py` —— 剧本 ↔ 分镜 ↔ H3 提示词连续性门禁（镜数丢镜/拆镜、台词逐字指纹、人物代号映射〔重音归一〕、时长合计 ±10%、首镜落 `cold_open` 与末镜落 `hook`；退出码 2，缺产物不空转通过；跨语种与句库元指令降级为告警而非假装通过），实测在 40 集在跑项目上 40/40 通过；总纲新增环节 **5.5** 与「往下游交什么」锚点表；`lint` 新增「CHAR 代号未在 HEADER 登记」告警；`script_continuity` 新增 24 例离线测试

> 验证：`test_script_design.py` 47/47、`test_script_continuity.py` 24/24；creation 层回归 187 例全绿（53+41+46+47）

<br>

**V0.5-5 · 默认口径 30 集 × 60 秒**（原 `V0.8`，2026-10-20）

**默认口径下调为 30 集 × 60 秒**（原 40 集 × 70 秒）。① 全局默认值：`script_rewrite.py` / `creation.py` 的 `DEFAULT_EPISODES=30`、`DEFAULT_EP_SECONDS=60`，`creation-brief.template.json`、`tools/cli.py init`（`--ep 30 --sec 60`）、`tools/core/storage.py` 建表默认、Web 控制台 `script.plan` 参数同步；② **时长改成分档校验**：`tools/core/schema.py::SECONDS_PROFILES` 与 `script_rewrite.py` 各一份同口径表（60 秒 → 5–10 镜 / 60–80 秒；70 秒 → 5–12 镜 / 70–95 秒；90 秒 → 6–15 镜 / 90–120 秒），`lint` 与 `cli.py check`（E006）**按项目自身 `ep_seconds` 选档** —— 已建成的 40 集 × 70 秒项目不被判死；③ 节拍随集数下调：中型爆点每 **3** 集（30 集 = 9 次）、大型每 **7** 集（4 次），留存三段改为 **EP1-3 / EP4-8 / EP9+**（与原 17% 留存活口占比一致）；④ 修 `build` 骨架的 DUR 按目标秒数均分（60 秒 8 镜由 58 秒 → 62 秒，不再一出骨架就判越界），骨架占位符不再被当成「未登记 CHAR 代号」；⑤ 文档口径统一：总纲 §3.2、`ffs-spec.md`、`剧本强度工程.md`、`qa-gates.md`、`s3-script-rewrite.md`、`剧本改编四段法.md`、`新项目启动提示词.md`、`Agent项目技术文档.md`、README

> 验证：`test_creation_pipeline.py` 57/57（新增 4 例：默认 30 集、60/70 秒分档）；`test_script_design` 47/47、`test_script_continuity` 24/24、`test_genre_formula` 41/41 全绿；30 集实测 plan 输出幕结构 EP1-4/5-13/14-22/23-30、爆点 9+4

<br>

**V0.5-6 · 开工前环境自检**（原 `V0.8.1`，2026-10-20）

**新增开工前环境自检入口**。起因：用户已装 Pillow 12.2.0，但装在 WorkBuddy 托管 venv `~/.workbuddy/binaries/python/envs/default/`，而 `python` 命令指向 `~/.workbuddy/binaries/python/versions/3.13.12/`（base）—— 于是 `test_cover_forge` 6/6 全红、`test_feedback_20261020` 的 `t_oom_plan` 报 `ModuleNotFoundError: PIL`，**代码没坏、环境错配**，但报错信息完全指向错误方向。① 新增 `tools/env_check.py`（纯标准库、零网络）：必需项 Python ≥3.10 / Pillow / ffmpeg / ffprobe，可选项 httpx、whisper-cli、RUNNINGHUB Key、ComfyUI 8188，另加 `manifest.sha256` 自校验；**核心能力是解释器错配检测** —— 扫描同机 `envs/*`、`versions/*`、`C:/Python3*`、conda，逐个探测依赖，命中就打印「哪个解释器装了哪个版本」并给出两条修法（A 用已装好的解释器 / B 给当前解释器补装），`envs/default` 优先推荐；支持 `--json`（给 Agent）、`--quiet`、`--fix`（只打印命令不执行），退出码 0/2；② README 顶部加「开工第一件事」醒目块 + 新增 §零 环境自检（检查项表 / 三种典型失败 / 给 AI 助手的用法）；③ `docs/新项目启动提示词.md` 增「第 -1 步 · 环境自检（不做完不许开工）」，要求 Agent 报 `ok` 并让用户在 A/B 之间选；④ 总纲链路表增环节 **-2**；⑤ `creation.py scaffold` 结尾提示加 -1 步；⑥ 新增 21 例离线测试

> 验证：`test_env_check.py` 21/21；实测在本机正确报出「当前解释器无 Pillow、`envs/default` 有 12.2.0」；用该 venv 解释器跑 `test_cover_forge` 16/16、`test_feedback_20261020` 50/50 —— 两个"既有失败"确认是环境问题而非代码回归

</details>

