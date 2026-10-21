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
> # ① 画风三轨（最先：它决定资产/时长/提示词规格，换了等于已产出素材全部作废）
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
> 画风完整规格（资产 / 分镜 / H3 提示词 · 单一真源）见
> **[`docs/styles/画风三轨规范.md`](docs/styles/画风三轨规范.md)**。

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

# ⓪.5 半解说结构三类硬校验（读 05-分镜/storyboard.json；零费用）
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
├── docs/                  单一真源文档：流程总纲 / 画风三轨 / 发行资料 / 合规预检 / 创作方法论
├── configs/               配置模板（含 model-plan.example.json 模型确认单）
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
| **画风三轨规范（资产 / 分镜 / H3 提示词）★ 单一真源** | `docs/styles/画风三轨规范.md` |
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
| **V0.6** | 2026-10-21 | **标准作业流程（11 环节）+ 开工前置条件（7 项）+ 流水线模式；并按实跑优化建议单修 19 条**。① 新增 `stages/production/scripts/workflow.py`：11 环节机器真源（调研→剧本→资产设计→资产生成→视频提示词→视频生成→发行资料→拼接→放大→字幕→定稿），每环节有**产物判据**与**顺序门禁**（`check` 不过退出码 4），跳过必须 `--reason` 留痕；真源文档 `docs/orchestration/标准作业流程.md`。② 新增 `project_setup.py`：开工前置 7 项（画风 / 集数 / 每集时长 / 生图模型 / 视频模型+功能选项 / 分辨率 / 是否流水线）收成一张确认单 `<ws>/project-setup.json`，单一门禁 `require()`（未齐退出码 4）；不另立真源（画风仍写 `style-plan.json`、通道仍写 `model-plan.json`）。③ 新增 `pipeline.py`：流水线模式 —— `plan` 先报**预计完工时间与花费**（不花钱），`run --yes` 无人值守一次跑到底，**每个计费环节之前核对预算上限**（超限退出码 3），内容环节停点给作业单（退出码 4）由 Agent 补齐后 `mark` 继续。④ 三条命令接进统一入口：`drama.py setup / workflow / pipeline`。⑤ 修复实跑反馈单：`_num()` 与 `subtitle` 的 shot_id 死锁（10.3/9.4）、`convert_storyboard` 分流 `character_refs`/`scene_refs`（9.3，且只在顺序不变时才拆）、`STYLE_LOCKS` 改读 `style-plan.json`（2.4）、中文服装段英译 `garment_en`（7.1）、cfg=1 负向词失效主动告警（1.1）、种子字段名不再静默（1.3）、`h3_prompts` 增 `voice` 字段（10.1）、`cost_model` 吃 `steps`/`megapixels`（11.1）、默认并发 2（11.3）、`release_export` 同集取 mtime 最新（10.8）、`E007` 支持西语断句与拉丁 55 字符档（2.1/2.2）、`E006` 总时长 ±2s 容差（4.x）、`E009` 报错文案（5.x）、`assets_dir` 进布局白名单（4.2）、剪影分镜 11 条硬约束写进画风规范（8.x）。逐条对照（含未修项与原因）见 `docs/patches/2026-10-21_实跑优化建议修复记录.md`。 | `pending` | 新增 `test_setup_workflow_pipeline.py` **42/42**；既有 17 个测试文件全绿（合计 **516 例**）；`manifest.sha256` 重建后自校验 0 不符 |
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

