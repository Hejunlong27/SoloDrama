# SoloDrama Studio（Web 工作台）

本文件是 **WebUI 的唯一说明**：启动方式、配置项、页面能力矩阵、LLM 系统、安全边界、测试与未完成事项。

- 与旧控制台的关系：`web/ui/`（两张旧页面）**原样保留**，Studio 是并列的新前端（`web/ui/studio/`），  
  共用同一个 FastAPI 后端。删掉 `web/ui/studio/` 即回滚，旧入口 `/ui/` 不受影响。
- 技术栈**未更换**：FastAPI + 原生 ES module + 原生 CSS，零构建、零外链、断网可用。

---

## 1. 启动

**日常启动：双击仓库根目录的 `start.cmd`。** 它会自动处理这些事：

| 它会检查 | 处理方式 |
|---|---|
| Python 版本 | < 3.10 直接告诉你装哪个 |
| 依赖 | 当前解释器缺 fastapi/uvicorn/httpx 时，**自动换一个装好的**；都没有就问你「要不要现在建环境」 |
| 引擎解释器 | 自动找一个装了 Pillow + httpx 的（字幕/出图需要），并打印用的是哪个 |
| 端口 | 8788 被占就从 8789 往后找，不会 `address in use` |
| 浏览器 | 健康检查通过后才开页面，不会给你一个白屏 |

窗口里会打印「工作台地址 / 旧控制台地址 / 默认项目」，**关掉窗口或 Ctrl+C 即停止**。

```bat
start.cmd                      :: 正常启动（自动开浏览器）
start.cmd --port 9000          :: 换端口
start.cmd --no-browser         :: 不起浏览器
start-readonly.cmd             :: 只读模式：拒绝一切写操作与计费
```

**首次使用 / 换机器**：如果它提示缺依赖，两种方式任选：

```bat
:: A. 自动建环境 + 装依赖（推荐，只需一次）
python web\launcher.py --init
:: B. 手动
python -m venv envs\solodrama-web
envs\solodrama-web\Scripts\python.exe -m pip install -r web\requirements-web.txt
```

`requirements-web.txt` 里已含 `httpx==0.28.1`（LLM 网关需要，与引擎同版本）。
引擎侧若还要跑字幕/放大，另需 `pip install -r requirements.txt`（Pillow）。

**不用启动器的等价命令**（排查问题时用）：

```bash
cd web
../envs/solodrama-web/Scripts/python.exe -m uvicorn app:app --host 127.0.0.1 --port 8788
```

**做桌面快捷方式**：右键 `start.cmd` → 发送到 → 桌面快捷方式；可在「属性 → 起始位置」保持仓库根目录。

工作区选择：顶栏「切换项目」→ 扫描本机 / 登记已有目录 / 新建项目。  
也可以用环境变量给默认值：`SOLODRAMA_WORKSPACE=D:/剧本/海外剧/2`。

**引擎解释器**：Studio 不执行任意命令，但所有 CLI 调用都用 `SOLODRAMA_PYTHON` 指定的解释器  
（需装 httpx + Pillow）。不指定时按 `configs/settings.json → 本机默认 venv → 当前解释器` 回退。

---

## 2. 配置项（新增项在此登记默认值）

| 配置                                | 默认            | 作用                                     |
| --------------------------------- | ------------- | -------------------------------------- |
| `SOLODRAMA_CONSOLE_READONLY`      | 空（关）          | 只读模式：拒绝一切写操作 / 计费 / LLM 配置变更           |
| `SOLODRAMA_CONSOLE_TOKEN`         | 空             | 局域网访问令牌。**不配就不允许局域网访问**（宁可不可用，也不裸奔）    |
| `SOLODRAMA_CONSOLE_ALLOWED_HOSTS` | 空             | 额外允许的 Host（逗号分隔），用于反代                  |
| `SOLODRAMA_LLM_DIR`               | `web/var/llm` | LLM 配置 / Key 保险箱 / 用量日志的根目录（测试隔离与多实例用） |
| `SOLODRAMA_PYTHON`                | 见上            | 引擎解释器                                  |
| `SOLODRAMA_WORKSPACE`             | 空             | 默认工作区                                  |

存储文件（都在 `web/var/`，已被 `.gitignore` 覆盖）：

```
web/var/registry.json      登记的项目（current 指针）
web/var/jobs.db            作业 / 事件 / 审计 / 资源锁
web/var/llm/config.json    提供商 + 用途路由（**不含任何明文 Key**）
web/var/llm/keys.json      密钥保险箱（仅「保存到本机」时写；尽力 0600）
web/var/llm/usage.jsonl    每次调用：用途 / 模型 / token / 金额 / 耗时（不含提示词与正文）
```

---

## 3. 页面 × 真实功能矩阵

图例：**真** = 接真实后端；**读** = 只读展示；**未** = 未接入并**如实标注原因**。

| 页面      | 真实功能                                                                       | 后端来源                                                                                                                                       |
| ------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| 工作台     | 项目数/产出/花费、待处理事项、运行中任务、**接入状态**（LLM 提供商与用途就绪数、出图/出片通道、工作流 API、ComfyUI 体检按钮） | `/api/workspaces`、`/api/jobs`、`/api/studio/workflow`、`/api/studio/setup`、`/api/llm/providers`、`/api/llm/purposes`、`/api/run`(`diag.comfy`) |
| 项目管理    | 登记、扫描本机、搜索/筛选/排序、打开、**新建项目**（调 `creation.py scaffold`，建完自动登记）              | `/api/workspaces*`、`/api/projects/create`                                                                                                  |
| 项目详情    | 11 环节判据、集数规划、产物目录、G-0 九项、阶段推进                                              | `/api/studio/workflow`、`/api/studio/setup`、`/api/episodes`、`/api/artifacts`                                                                |
| 创作中心    | S1–S5 完成度（引擎 probes）、5 个免费校验、**AI 剧本正文闭环**（预览提示词 → 生成草稿 → 编辑 → 确认落盘）       | `/api/studio/workflow`、`/api/run`、`/api/studio/script/*`、`/api/llm/preview`                                                                |
| 资产中心 | 角色/场景/道具/参考图浏览（缩略图 + 原图抽屉）、缺口清单、**真实出图**（本地 ComfyUI ￥0 占 GPU / 云端 RH ★计费，均走作业队列）、出图器体检、参考图体检 | `/api/artifacts`、`/media`、`/api/studio/asset-md`、`/api/run`（`assets.*` `refs.*`） |
| 分镜与视频   | 镜头表（跨批次按镜头去重）、提示词抽屉、产物预览、**出片**（计费五步）                                      | `/api/studio/shots`、`/api/studio/prompt`、`/media`、`/api/run`（428 确认单 + 续跑批次号）                                                              |
| 后期制作    | 拼接/放大/字幕的现状与产物、G6「要不要加字幕」停点                                                | `/api/studio/shots`、`/api/run`（`upscale.*` `subtitle.*`）                                                                                   |
| 发行中心    | 发布版剧集/封面/文案/发布清单/版权资料的存在性核对                                                | `/api/artifacts`、`/api/file`、`release_check`（未接入，见 §7）                                                                                     |
| 任务中心    | 排队/运行/成功/失败/待确认、日志 SSE、退出码语义、安全重试、取消                                       | `/api/jobs*`、`/api/jobs/{id}/stream`、`/api/jobs/{id}/cancel`                                                                               |
| 成本中心    | 台账逐次尝试、按阶段/按集、失败不计费、**LLM 用量独立分栏**（不折算点数）                                  | `/api/studio/cost`、`/api/llm/usage`                                                                                                        |
| AI 模型中心 | 提供商 CRUD、连接测试、用途路由、提示词模板、调用记录                                              | `/api/llm/*`                                                                                                                               |
| 系统设置    | 环境自检、G-0 九项、能力清单（哪些没接+原因）、审计                                               | `/api/studio/env`、`/api/studio/setup`、`/api/studio/capabilities`、`/api/audit`                                                              |

设计纪律：**所有数字都来自后端**。没有数据的就显示「未知 / 不可得」，不填 0、不编进度。

---

## 4. LLM 系统

### 4.1 结构

```
web/core/llm/
  errors.py     错误分类（kind + 是否可重试）—— 重试决策只读这里
  schema.py     极简 JSON Schema 校验（零新增依赖）
  safety.py     Key 打码 / SSRF 地址校验 / 报错脱敏
  store.py      配置 + 密钥保险箱 + 用量日志
  templates.py  仓库提示词注册表 + 用途路由 + 输出 Schema
  providers.py  协议适配：OpenAI 兼容 / Ollama / Mock
  gateway.py    编排：能力校验 → 渲染 → 调用 → 解析 → 校验 → 记用量
  drafts.py     草稿 → 人工编辑 → 确认落盘
```

一句话：**业务层只调 `gateway.complete(purpose, variables)`**，不各自发 HTTP、不各自拼提示词。

### 4.2 Provider 支持

| kind     | 协议                             | 说明                                                                             |
| -------- | ------------------------------ | ------------------------------------------------------------------------------ |
| `openai` | `POST {base}/chat/completions` | OpenAI / DeepSeek / Kimi / Qwen-DashScope 兼容 / vLLM / LM Studio / one-api 同一形态 |
| `ollama` | `POST {base}/api/chat`         | 本地服务，**不需要云端 Key**；`format=json` 原生支持                                          |
| `mock`   | —                              | 仅测试注入，不在 UI 出现                                                                 |

**代理**：云端提供商默认继承系统代理（`HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY`），本地服务默认直连——
否则 `127.0.0.1` 的 Ollama 会被代理劫走。可在提供商表单里用「走系统代理」显式覆盖。
（踩过的坑：早期一律 `trust_env=False`，在本机表现为「请求超时」，会被误判成 Key 或模型问题。）

能力标识：`json` / `tools` / `stream` / `vision`。用途声明 `requires`，**能力不满足时网关直接拒发请求**  
（省一次失败与一次计费），而不是发出去再报错。

### 4.3 用途路由（7 个）

| 用途                       | 模板（仓库原文）                  | 输出 Schema                                         |
| ------------------------ | ------------------------- | ------------------------------------------------- |
| `script.generate` 剧本正文生成 | `s3-script-rewrite.md`    | `script.episode`（硬约束 5–10 镜 / DUR 4–15 / 60–80 秒） |
| `script.diagnose` 改编诊断   | `s3a-diagnosis.md`        | `script.diagnosis`                                |
| `script.review` 观众审稿     | `s3c-audience-review.md`  | `script.review`                                   |
| `topic.position` 选题定位    | `s2-topic-positioning.md` | `topic.candidates`                                |
| `topic.research` 榜单调研    | `s0-market-research.md`   | 无 Schema（人工复核）                                    |
| `topic.breakdown` 爆款拆解   | `s1-hit-breakdown.md`     | 无 Schema                                          |
| `script.translate` 剧本转译  | `s0b-script-translate.md` | 无 Schema                                          |

**提示词不另写一套**：`templates.py` 直接读 `stages/creation/prompts/*.md`（仓库的权威方法论），  
system 段放原文，user 段放「本次输入 + 输出契约（内嵌 Schema）」。模板带 `body_sha` 指纹，  
仓库里的提示词被改动会在界面上看得出来。

### 4.4 Key 与成本

- 读取顺序：**环境变量**（`env_var` 指定）→ **本机保险箱** `web/var/llm/keys.json`。
- 对外只回 `has_key` / `key_source` / `key_hint`（形如 `sk-a…7890`）。`config.json` 里永远没有明文。
- 报错文本过 `scrub`：上游把 Key 回显在 401 body 里也不会漏到前端或日志。
- 用量记录只存 **token / 金额 / 耗时 / 指纹**，**不存提示词与生成正文**。
- 金额只认供应商返回的 `usage.cost`；**没返回就是「未知」，绝不按 token 单价估算**。

### 4.5 离线演练通道（Mock）——没凭据时怎么证明链路是通的

它不是「演示数据」：只替换**网络那一段**，下游 `解析 → Schema 校验 → 引擎口径复核 → 草稿 → 落盘 → lint`
全部走真实代码。所以它既能证明闭环，也能证明校验器真的会拦人。

- 创建：AI 模型中心 → 新建提供商 → 选预置「离线演练（Mock）」；地址固定 `mock://local`，不需要 Key。
- 输出：`simulated: true`（草稿、用量、界面三处都会标「演练」）。
- 闸门：演练草稿调用 `confirm` 会被拒绝；只有显式 `allow_simulated=true`（验证脚本 + 临时工作区）才放行。
- 为什么这么严：Mock 产出没有经过任何模型，写进 `03-剧本/` 就是伪造产物。

### 4.6 一条命令验证闭环

```bash
python web/tools/verify_llm_loop.py            # 临时工作区，离线演练，零费用
python web/tools/verify_llm_loop.py -k         # 保留临时工作区以便查看产物
python web/tools/verify_llm_loop.py --provider <id> --confirm-cost   # 用已配置的真实模型（会花钱）
```

按顺序打印 10 步：配置 → 连接测试 → 绑定用途 → 预览提示词 → 生成 → 人工编辑 → 确认落盘 →
**引擎 lint 验收** → 用量口径 → 产物预览。末行 `27/27 项通过` 即全通。

关键点：**最后一步不是本脚本自说自话，而是调用 `script_rewrite.py lint`**——
产物能不能用由引擎判定（退出码 0 才算通过）。


### 4.7 创作闭环（`/api/studio/script/generate`）

```
门禁检查（blueprint / 诊断卡 / world-bible）
  → 组装变量（蓝本单集行 + 画风锁 + HEADER + 秒数 + 镜数）
  → 网关生成（真实调用）
  → 解析 JSON + Schema 校验 + 引擎口径复核（镜数/总时长）
  → 存草稿 <ws>/video-pipeline/llm-drafts/epNN-<id>.json   ← 不碰正式文件
  → 人工编辑（可直接改 Markdown）
  → 确认落盘 /api/studio/drafts/{id}/confirm
       ├ 诊断卡未确认 → 拒绝（与 build --emit 退出码 4 同口径）
       ├ 目标已存在且未勾「覆盖」→ 拒绝
       ├ expected_sha 不符 → 拒绝（防覆盖别人刚改的内容）
       └ 通过 → 备份旧版 → 写 03-剧本/ep_NN.md（强制 LF）
```

HEADER 优先沿用**已有正式剧本的六行**（保住人工写的视觉锚点）；没有才从 `blueprint.json`

- `bible/world-bible.json` 推导，并在草稿里给出「需要人工确认」的 warning。

---

## 5. 安全边界

| 风险                       | 措施                                                                                                      |
| ------------------------ | ------------------------------------------------------------------------------------------------------- |
| 浏览器执行任意命令                | 不存在。前端只调白名单命令 id，参数由后端 `Param` 校验，`subprocess` 用数组不拼 shell                                              |
| Host 头伪造 / DNS rebinding | 只允许回环 Host，其余 403（可用 `ALLOWED_HOSTS` 显式加）                                                               |
| 跨站写请求                    | `Origin` + `Sec-Fetch-Site` 双判据，跨站写一律 403                                                               |
| 局域网裸奔                    | 非回环客户端必须带 `X-Console-Token`，且服务端必须已配 token；没配就拒绝                                                        |
| 路径遍历 / 任意读               | `/api/artifacts` + `/media` 走 `artifacts.safe_rel`（realpath 校验 + 6 类媒体扩展白名单）                            |
| 凭据泄露                     | Key 只进不出；日志与错误统一打码；`mask_text` 覆盖 CLI stdout                                                            |
| 计费误触                     | 引擎自带门禁 + 服务端 428 确认单（含续跑批次号回填）+ 只读模式 + 资源锁                                                              |
| LLM 计费误触                 | `/api/llm/complete`、`/api/studio/script/generate`、`confirm` 都必须显式 `confirm=true`；deep 连接测试需 `confirm=1` |
| SSRF                     | Base URL 只允许 http/https、禁止内嵌口令；云元数据地址**任何情况**拒绝；内网/回环需显式勾「本地服务」；连接测试时再做一次 DNS 解析核对                      |
| 覆盖用户文件                   | 新建项目只接受**空目录**；落盘必须显式覆盖 + 备份 + 指纹校验                                                                     |

---

## 6. 测试

```bash
# 离线单元/契约（默认 venv 即可；共 31 个文件）
for t in $(find stages tools web -name "test_*.py" -not -path "*__pycache__*"); do
  python "$t" || echo "FAILED $t"; done

# LLM 端到端（需要 fastapi + httpx → 用 Web 的 venv；本地伪造上游 + 内置演练通道，零费用）
envs/solodrama-web/Scripts/python.exe web/tests/test_llm_e2e.py

# 人工可读的闭环验证（10 步 + 引擎 lint 验收）
python web/tools/verify_llm_loop.py
```

本轮实测结果（2026-10-23）：

- **31 个测试文件全绿**（引擎 22 + web 9）。新增：`test_llm_gateway.py`、`test_llm_e2e.py`、  
  `test_studio_assets.py` 扩展（12 个视图）。
- `test_llm_gateway.py`：Schema 校验 7 例、安全 12 例、配置隔离 6 例、**代理默认值 3 例**、成功路径 5 例、错误分类与重试 12 例、模板 6 例、**离线演练通道 17 例**、创作闭环 12 例、门禁与失败保护 6 例 —— 全部通过。
- `test_llm_e2e.py`：**10 组**断言，走真实 HTTP（本地伪造上游 + 内置演练通道），覆盖 SSRF 拒绝、Key 不回显、
  428 门禁、跨站 403、生成→编辑→落盘→幂等、上游 401/烂 JSON 分类、诊断卡门禁、**演练草稿默认拒写 + allow_simulated 放行**。
- `verify_llm_loop.py`：**27/27 通过（0.7s）**，末步 `script_rewrite.py lint` 退出码 **0**。

---

## 7. 未完成事项（如实登记）

| 项                                     | 状态  | 原因 / 下一步                                                                      |
| ------------------------------------- | --- | ----------------------------------------------------------------------------- |
| 流式输出（SSE 逐字）                          | 未实现 | 网关是同步链路；要流式需把 gateway 改异步并加 SSE 转发。已在能力表标 `llm_stream: false`                 |
| 真实模型连接验证 | **受阻（环境出网策略）** | 已获授权并实测：本机只能经代理出网（`HTTP_PROXY=127.0.0.1:64746`），该代理对 `api.openai.com` 返回 **502 CONNECT tunnel failed**，直连则超时；`example.com` 经同一代理为 200，说明代理本身可用。另：`OPENAI_API_KEY` 打码后为 `user…qXud`（不是 `sk-` 形态），很可能不是 OpenAI 平台 Key。→ 换成可达端点或正确的 Key 后，用 `verify_llm_loop.py --provider <id> --confirm-cost` 即可验完 |
| `release_check` / `release_export` 入口 | 未接入 | `release_check --json` 会写 `09-发行/release-manifest.json`（属写操作），需先定"写前确认"的交互再放行 |
| `bgm.*` 入口                            | 未接入 | `bgm.py` 未进命令白名单，需先补门禁口径（license/铺底 LUFS/覆盖率的判定要在服务端复算）                       |
| `character_design` 审计入口               | 未接入 | 未进白名单；需先确认 `plan/check/audit` 三段的可重入性                                         |
| 分镜与脚本在线编辑                             | 未实现 | 刻意不做：正文由 AI + 人工在 `03-剧本/` 演进，网页只做「草稿→确认」这一个受控写入口                             |
| 多用户 / 权限                              | 未实现 | 只有「只读模式」，没有账号体系。当前定位是本机单人工具                                                   |
| 任务级精确金额                               | 不可得 | 引擎 audit 只存预估文本；真实金额只有平台 `usage`（已在成本页明示）                                     |
| LLM 用途级预算熔断                           | 未实现 | 引擎的预算熔断只管 RH 点数；LLM 没有统一计价，先靠"每次调用需确认 + 用量可见"                                 |



---

## 8. 已知限制

- **端口**：默认 8788（`web/run_console.py` 的约定值），不是 8000。
- **Windows 上 `.js` 的 MIME**：`app.py` 已显式钉住，避免注册表把 `.js` 报成 `text/plain` 导致 module 加载失败。
- **ComfyUI / RunningHub 的"连接状态"**：页面只显示**配置状态**（来自 G-0 九项）；  
  真正的连通性要显式点「检测」（ComfyUI，0 费用）或在「分镜与视频」跑「小样 1 段」（RunningHub，计费）。  
  打开页面时**不会**自动联网探测。
- **资产出图的前置是「资产提示词 md」，不是 ComfyUI**：引擎的 `gen_assets_local.py` / `gen_asset*.py`
  **没有命令行参数**，只认环境变量 `SOLODRAMA_ASSET_MD`；缺了会在解析 `--check` 之前就 rc=1，
  看起来像「ComfyUI 没开」，其实是缺文件。资产中心会在打开时自动探测
  （`04-资产/*.md` 与 `04-资产/design/*.md`，优先文件名含「资产提示词」），
  选中后由后端注入（命令声明 `env={"SOLODRAMA_ASSET_MD": "asset_md"}`），**不需要你手动设环境变量**。
- **`/api/studio/script/context` 会读 blueprint**：旧项目若没有 `blueprint.json`，生成会被拒绝并给出原因，  
  不会静默降级成"随便写一集"。
