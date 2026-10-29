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
| 项目管理    | 登记、扫描本机、搜索/筛选/排序、打开、**新建项目**（调 `creation.py scaffold`，建完自动登记）、**失效目录提示与一键清理**（只清注册表，不碰磁盘） | `/api/workspaces*`、`/api/workspaces/prune`、`/api/projects/create`                                                                          |
| 项目详情    | 11 环节判据、集数规划、产物目录、G-0 九项、阶段推进                                              | `/api/studio/workflow`、`/api/studio/setup`、`/api/episodes`、`/api/artifacts`                                                                |
| 创作中心    | S1–S5 完成度（引擎 probes）、5 个免费校验、**AI 剧本正文闭环**（预览提示词 → 生成草稿 → 编辑 → 确认落盘）       | `/api/studio/workflow`、`/api/run`、`/api/studio/script/*`、`/api/llm/preview`                                                                |
| 资产中心 | 角色/场景/道具/参考图浏览（缩略图 + 原图抽屉）、**散图**（标准目录之外、只读扫描）、缺口清单、**真实出图**（本地 ComfyUI ￥0 占 GPU / 云端 RH ★计费，均走作业队列）、出图器体检、参考图体检 | `/api/artifacts`、`/api/artifacts/loose`、`/media`、`/api/studio/asset-md`、`/api/run`（`assets.*` `refs.*`） |
| 流水线 | **11 个环节串成一条可执行的线**：连跑 / 逐步确认两种模式、预算内自动放行、遇「前置未齐 / 需人工 / 计费估不出来」停下并说明原因；**每行一个可点的大按钮**（运行此步 `only=` 只跑这一条 / 打开对应页面） | `/api/pipeline/plan`（只读计划）、`/api/pipeline/run`（执行，默认 dry_run） |
| 分镜与视频   | 镜头表（跨批次按镜头去重）、提示词抽屉、产物预览、**出片**（计费五步）                                      | `/api/studio/shots`、`/api/studio/prompt`、`/media`、`/api/run`（428 确认单 + 续跑批次号）                                                              |
| 后期制作    | 拼接/放大/字幕的现状与产物、G6「要不要加字幕」停点                                                | `/api/studio/shots`、`/api/run`（`upscale.*` `subtitle.*`）                                                                                   |
| 发行中心    | 发布版剧集/封面/文案/发布清单/版权资料的存在性核对                                                | `/api/artifacts`、`/api/file`、`release_check`（未接入，见 §7）                                                                                     |
| 任务中心    | 排队/运行/成功/失败/待确认、日志 SSE、退出码语义、安全重试、取消                                       | `/api/jobs*`、`/api/jobs/{id}/stream`、`/api/jobs/{id}/cancel`                                                                               |
| 成本中心    | 台账逐次尝试、按阶段/按集、失败不计费、**LLM 用量独立分栏**（不折算点数）                                  | `/api/studio/cost`、`/api/llm/usage`                                                                                                        |
| AI 模型中心 | 提供商 CRUD、连接测试、用途路由（**未绑定时自动选路**）、提示词模板、调用记录                              | `/api/llm/*`                                                                                                                               |
| 环境体检 | **15 项体检**（运行时 / Python 依赖 / 外部程序 / 本机服务 / 数据目录 / 配置 / 完整性），每项标清「能不能自动修」：能的三类可**一键修复并自动复检**，其余只给可复制命令或跳转页面；底部有修复留痕 | `/api/health/checks`（现算）、`POST /api/health/fix`（服务端白名单）、`/api/health/fixes` |
| 系统设置    | 环境自检（可跳「环境体检」一键修）、G-0 九项、能力清单（哪些没接+原因）、审计                                               | `/api/studio/env`、`/api/studio/setup`、`/api/studio/capabilities`、`/api/audit`                                                              |

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

#### 4.2.1 DeepSeek（真实通道，2026-10-28 实测接通）

| 项 | 值 |
| --- | --- |
| 端点 | `https://api.deepseek.com/v1`（不要写成控制台首页；`/v1/models` 可自检） |
| 可用模型 id | **`deepseek-flash`**、`deepseek-v4-pro` |
| 不认的 id | `deepseek-v4.1-flash` 这类**平台侧别名** → HTTP 400 `invalid_request_error` |
| Key | 只进 `web/var/llm/keys.json`（git 已忽略），界面回显仅 `sk-2…44d0` |
| 超时 / 重试 | 120 秒 / 0 次（推理模型首字慢；重试会重复计费，改为人工重试） |

**两个模型都是推理模型**，这带来两个必须在产品里体现的差异：

1. **思考过程也计入 `max_tokens`**。给 8–16 个 token 时，思考就吃光额度，
   回包是 `HTTP 200` + `content: ""`。旧口径会把这种情况报成「输出不是合法 JSON」，
   用户完全不知道该调大额度。现在明确分成两类：
   `truncated`（`finish_reason=length`，额度不足）与 `empty`（内容策略拦截或模型真的没话说）。
   探针统一给 **64 tokens**（`connections._LLM_PROBE_TOKENS`），够它想完并吐一句「可用」。
2. **数值预算写进提示词**。`Script.episode` 的 Schema 只能管住单镜 `DUR ∈ [4,15]`，
   管不住「所有 DUR 之和」。实测模型会写出 90 秒的「60 秒档」剧集。
   现在 `render_parts()` 会把 `budget.bounds_for(ep_seconds)` 算出的边界
   （镜数 5–10、总时长 60–80 秒）直接写进 user 段——**提示词与校验器共用同一个函数**，不会各说一套。


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
**引擎 lint 验收** → 用量口径 → 产物预览。末行 `28/28 项通过` 即全通（真实通道与演练通道各跑一遍）。

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
# 离线单元/契约（默认 venv 即可；共 41 个文件）
for t in $(find stages tools web -name "test_*.py" -not -path "*__pycache__*"); do
  python "$t" || echo "FAILED $t"; done

# LLM 端到端（需要 fastapi + httpx → 用 Web 的 venv；本地伪造上游 + 内置演练通道，零费用）
envs/solodrama-web/Scripts/python.exe web/tests/test_llm_e2e.py

# 人工可读的闭环验证（10 步 + 引擎 lint 验收）
python web/tools/verify_llm_loop.py
```

本轮实测结果（2026-10-28）：

- **41 个测试文件全绿**（引擎 24 + web 17）。新增：`test_workspaces.py`（登记表自愈 / prune 不碰磁盘），
  `test_inventory.py` 补 `[5] 散图口径`。
- 新增 `test_workspaces.py` 的动因：真实登记表里 `current` 指着已删除的目录，四个用例分别守住
  「死路径自愈并落盘」「未登记的死 current 不许变卡片」「全盘皆死时置空」「prune 只清注册表」。
- `test_llm_gateway.py`：Schema 校验 7 例、安全 12 例、配置隔离 6 例、**代理默认值 3 例**、成功路径 5 例、错误分类与重试 12 例、模板 6 例、**离线演练通道 17 例**、创作闭环 12 例、门禁与失败保护 6 例 —— 全部通过。
- `test_llm_e2e.py`：**10 组**断言，走真实 HTTP（本地伪造上游 + 内置演练通道），覆盖 SSRF 拒绝、Key 不回显、
  428 门禁、跨站 403、生成→编辑→落盘→幂等、上游 401/烂 JSON 分类、诊断卡门禁、**演练草稿默认拒写 + allow_simulated 放行**。
- `verify_llm_loop.py`：离线演练 **27/27**（0.7s）；**真实 DeepSeek 通道 28/28**（约 27s，多出的一项是把「演练草稿必须被门禁拒收」改成两种通道都验）。末步 `script_rewrite.py lint` 退出码 **0**。

---

## 7. 未完成事项（如实登记）

| 项                                     | 状态  | 原因 / 下一步                                                                      |
| ------------------------------------- | --- | ----------------------------------------------------------------------------- |
| 流式输出（SSE 逐字）                          | 未实现 | 网关是同步链路；要流式需把 gateway 改异步并加 SSE 转发。已在能力表标 `llm_stream: false`                 |
| 真实模型连接验证 | **已接通（DeepSeek，2026-10-28）** | 旧结论是「环境出网策略受阻」，实际卡点有两个：① 本机 `OPENAI_BASE_URL` 指向 `api.commandcode.ai`、`OPENAI_API_KEY` 也不是 OpenAI 形态的 Key（打码 `user…qXud`）；② 那个 provider 的 `env_var` 绑的是 `OPENAI_API_KEY`，于是拿着别人的 Key 去敲 DeepSeek，稳态 401。换成 DeepSeek 官方端点 + 自己的 Key 后一次通过：`verify_llm_loop.py --llm-dir web/var/llm --provider deepseek --confirm-cost` **28/28**，引擎 `script_rewrite.py lint` 退出码 0（8 镜 / 70 秒 / 台词齐全）。⚠ 仍未接入第二家云端模型做对比评测 |
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
- **`store.public_provider()` 会把 `key_status` 摊平到顶层**：它做的是
  `out.update(key_status(prov))`，所以 `has_key` 在**顶层**，`p["key_status"]["has_key"]` 恒为 None。
  读错的表现是「填了 Key 界面仍说缺 Key」。判定统一走 `connections._prov_has_key()`。
- **用途未显式绑定 → 自动选路**（`store.auto_provider()`）：按「有 Key 的云端 > 本地模型 > 离线演练」
  挑一个，排序里 Mock 永远最后（能跑通但输出是假的，不该抢在真模型前面）。
  `list_purposes()` 与 `get_purpose()` **共用同一个函数**，否则会出现「界面说用 A、网关实际用 B」。
  显式绑定仍最优先；`bound=False` 但 `auto=True` 表示「用户没指定，系统代选」。
- **大模型探测是真发请求**（1 token 级）：只看「有没有 Key」区分不出 Key 过期 / 模型改名 /
  base_url 少 `/v1` / 代理拦截——这四种配置看起来都齐。失败按 `core/llm/errors.KINDS` 分类给下一步；
  `test_connections.py` 里同时守正例（Mock 返回）与负例（端口拒绝 → network/timeout）。
- **散图是只读视图，不归档**：真实项目的图常直接丢在剧目录根下，而资产页只读
  `04-资产/{characters,scenes,props}` → 打开是空的。`artifacts.loose_images()` 扫根目录 + 一层子目录，
  跳过 `04-资产`/`06-提示词`/`07-成片`/`09-发行` 与工程目录，**只报告位置**。
  移动用户文件属破坏性操作，产品里不自动做。
- **散图数必须一路加到所有计数口径**：`inventory` 里 `images.total` 是「已归档资产」的稳定口径
  （多处断言依赖，不改），散图单列 `images.loose`，合计 `images.all`。凡是「这部有多少张图」
  的显示（项目卡片、工作台表格、顶部项目条、扫描本机列表、项目详情）都要用
  `images + loose`，否则会出现「项目卡片说 21 张、工作台说 0 张」。`has_output` 也把散图算进去，
  否则图都在根目录的项目会被判成「未开工」。
- **当前工作区绝不能停在死路径上**：登记表会攒下已删除/已改名的路径（实测 `current` 指着
  已删除的 `D:\剧本\海外剧\3`）。旧实现把 `current` 无条件塞进 `items` 伪造成卡片，前端又直接
  采信 `current` ⇒ 一进站就用不存在的目录请求所有接口，页面全空还不报错。现在：
  `_i_workspaces()` 不再伪造条目，`current` 失效时自愈到「第一个真实存在且像工作区」的项目并落盘，
  响应里给 `current_exists` / `stale` / `current_replaced`；前端 `loadProjects()` 只接受在可用列表里的
  `current`（双保险）。失效条目用 `POST /api/workspaces/prune` 清掉——**只删注册表条目，不删磁盘**。
- **资产出图的前置是「资产提示词 md」，不是 ComfyUI**：引擎的 `gen_assets_local.py` / `gen_asset*.py`
  **没有命令行参数**，只认环境变量 `SOLODRAMA_ASSET_MD`；缺了会在解析 `--check` 之前就 rc=1，
  看起来像「ComfyUI 没开」，其实是缺文件。资产中心会在打开时自动探测
  （`04-资产/*.md` 与 `04-资产/design/*.md`，优先文件名含「资产提示词」），
  选中后由后端注入（命令声明 `env={"SOLODRAMA_ASSET_MD": "asset_md"}`），**不需要你手动设环境变量**。
- **`/api/studio/script/context` 会读 blueprint**：旧项目若没有 `blueprint.json`，生成会被拒绝并给出原因，  
  不会静默降级成"随便写一集"。
- **`/?ws=<剧目录>` 深链必须带住查询串**：`/` 是 307 到 `/studio/`，若跳转时把 query 丢掉，
  前端只能退回注册表的 `current` —— 用户以为打开的是 A，看到的却是 B（本机实测：书签里的 `?ws`
  从来没生效过，而 `current` 还会被后续操作改写）。已修，`test_workspaces.py` §5 守着「无 query 时不许硬拼 `?`」。
- **注册表写盘前必须剥掉计算字段**：`_i_workspaces()` 会往 items 上贴 `exists/images/loose/yuan…`，
  这些是**算出来的快照**。一旦随自愈写回 `registry.json`，下次读到的「注册表」就混着上次的扫描结果——
  `images` 越写越旧，`exists` 变成过期快照（目录删了卡片还显示在）。统一走 `_registry_clean()`。
- **推理模型的「空回包」不是网络问题**：`finish_reason=length` 说明额度被思考吃光；
  报 `parse`（输出不是合法 JSON）会把人带偏到提示词上。见 §4.2.1。


---

## 9. 生成通道（图像 / 视频）

> 台账真源：`web/core/generators.py`；本机模板在 `stages/assets/comfyui/` 与 `stages/video/comfyui/`。
> 状态全部**现算**（ComfyUI 在线 + 工作流节点类 + 模型文件 + 项目 `config.local.json`），不存快照。

| 通道 | 引擎 | 模式 | 工作流 / 配置 | 成本 |
| --- | --- | --- | --- | --- |
| `image.local.t2i` | 本地 ComfyUI | 文生图 | `stages/assets/comfyui/workflow_qwen_image21.json`（Qwen-Image 2.1 int8 + 4step turbo） | ￥0 |
| `image.local.i2i` | 本地 ComfyUI | 图生图 | **未内置**（现用工作流是纯文生图，没有加载图像节点） | ￥0 |
| `image.rh.t2i` | RH 工作流 | 文生图 | `image_providers[active].id` + `nodes.prompt.nodeId` | 按点数 |
| `image.rh.i2i` | RH 工作流 | 图生图 | `image_providers[active].id_i2i` + `nodes.image.nodeId` | 按点数 |
| `video.local.i2v` | 本地 ComfyUI | 图生视频 | `stages/video/comfyui/workflow_h3_local.json`（MiniMax H3 多参 · 4 步） | ￥0 |
| `video.rh.workflow` | RH 工作流 | 图生视频 | `h3.id` + `h3.nodes` | 27 RH币/任务 + 1 币/秒 |

### 9.1 为什么文生图与图生图必须分成两条

图生图比文生图**多一个「加载图像」节点**，是另一份工作流。用一个 id 硬套的后果不是报错，而是
**静默忽略参考图**：钱扣了、图还是纯文生图。所以：

* 两个 id 各取各的（`id` / `id_i2i`），**互不兜底**；
* 图生图必须先上传参考图，把返回的**平台文件名**写进 `nodes.image` 指定的节点；
* 缺 `nodes.image.nodeId` 时状态直接判「待配置」，不允许提交。

界面「生成通道」页有「配置云端工作流」按钮，四个输入框写进项目配置，**写前自动备份**，
只改 `image_providers` 这一条，其余键原样保留。

### 9.2 本地出片（H3）的实测口径

* 工作流来自「Minimax 多参（4 步采样）」：`Cobijada_H3_Hybrid…int8` + `qwen3vl_32b_minimax_h3_int4` +
  `minimax_h3_video_vae_int8` + `qwen3vl` 文本编码 + `lightx2v turbo 4step` LoRA（strength 0.75），
  **`SolAttnMiniMax` 加速节点保留**，`BasicScheduler.steps = 4`。
* 实测（RTX 4060 8G，ComfyUI 0.42.1，空闲显存仅 0.6G）：5 秒 / 16:9 / 0.6MP → **283 秒 / 2.0 MB /
  1056×608 / 24fps / 124 帧**，画面与人脸正常。耗时主要在**冷加载**（unet 走 offload），不是采样。
* 客户端 `stages/video/comfyui/comfy_local_video.py`：`--check` 先核对节点类与模型文件，
  默认 dry-run；`--seconds / --mp / --aspect` **不传就沿用工作流原值**（不要把别人调好的 0.6MP 冲掉）。
* 节点映射写在文件头的 `NODE_*` 常量里（也可用环境变量覆盖）：换工作流必须逐个核对，
  否则会出现「提交成功但参数没生效」——这类错最贵。

### 9.3 怎么换工作流（不用改代码）

本地这条通道是**数据驱动**的，三层都能改，按需选一层：

| 层 | 放哪 | 改法 | 适合 |
| --- | --- | --- | --- |
| 工作流 JSON | `stages/video/comfyui/workflow_h3_local.json` | 直接替换文件；或 `--workflow <路径>`；或环境变量 `COMFYUI_VIDEO_WORKFLOW` | 换一整套流程 |
| 节点映射 | 同目录同名 sidecar `workflow_h3_local.map.json` | 改 JSON 里的 id；或 `--map <路径>`；或环境变量 `COMFYUI_VIDEO_NODE_*` | 换了工作流后改参数落点 |
| 单次参数 | 命令行 / 页面 | `--steps / --seconds / --mp / --aspect / --seed` | 只这一次不一样 |

**不需要把工作流上传到 ComfyUI**：这两个文件是 ComfyUI 的「API 格式」JSON，脚本直接
POST 给 `/prompt`。参考图才需要上传（脚本自动做，走 `/upload/image`）。

换工作流的四步（都能在「生成通道 / 任务中心」里点，也能命令行）：

```bash
cd stages/video/comfyui
python comfy_local_video.py --workflow 新工作流.json --list-nodes   # ① 看节点 id 与建议角色
# ② 复制 workflow_h3_local.map.json → 新工作流.map.json，按输出改 id
python comfy_local_video.py --workflow 新工作流.json --map-check     # ③ 离线校验（不占 GPU）
python comfy_local_video.py --workflow 新工作流.json --check         # ④ 在线体检（节点类 + 模型文件）
```

对应命令：`video.workflow.nodes`（①）、`video.workflow.mapcheck`（③）、`video.local.check`（④）。
`--map-check` 的价值：**映射 id 写错时脚本照样能提交、GPU 照样跑，参数却全落空** ——
这条能在花 GPU 之前 100% 抓出来。非 API 格式（界面直接导出的带 `nodes/links`）也会被挡住并提示
「用导出 API 格式」。

### 9.4 已知限制

* **第三方加速节点会随版本变签名**。本机 `SolAttnMiniMax` 的 `execute()` 比云端版本多一个必填
  `selection` 参数，拿云端导出的工作流直接跑会在该节点 `TypeError`。`--check` 只能核对「节点存不存在」，
  **签名兼容性只能运行时发现** —— 所以第一次跑新工作流先用最短时长 + 最低分辨率试。
* 8G 卡跑 H3 时显存会很紧（实测空闲 0.6G 也能出，但慢）；`--mp` 降到 0.3–0.4 可快一些。
* 本地图生图（Qwen-Image）尚未内置：需要一份带 `LoadImage` 的图生图工作流，放到
  `stages/assets/comfyui/` 并登记节点映射后才可用（页面会如实标「不支持」）。

---

## 10. 流水线（连跑模式）

真源 `web/core/pipeline.py`；页面 `#/pipeline`（项目级）。

### 10.1 两种模式

| 模式 | 行为 |
| --- | --- |
| 逐步确认 | 点一次只跑 **1 步**（`max_steps=1`），跑完停下看结果 |
| 连跑（流水线） | 按环节顺序最多推进 **6 步**，遇以下情况立刻停 |
|  | ① 引擎 probes 未过（前置未齐）；② 环节标记为「需人工」；③ 计费步骤估不出金额或超预算 |

### 10.2 三条硬纪律

1. **不猜**：只有 `STAGE_MAP` 里明确登记了命令的环节才算「可自动」。没登记的一律标 `manual`
   并给出该去的页面（S3 资产设计 → 资产中心、S7/S11 → 发行中心）。假装能全自动比不给这功能更糟。
2. **计费可估才放行**：`est_coins` 已知且「累计 + 本步 ≤ 预算」才自动跑；估不出来就停（不猜金额）。
3. **前置未齐不动手**：环节自带 probes（`found/need`），未满足就停在该环节，不跳过、不硬跑。

### 10.3 与旧控制台的区别

`/api/pipeline`（旧）返回旧控制台的 15 轮视图（`reader.pipeline`）；新接口是
`/api/pipeline/plan` + `/api/pipeline/run`。⚠ 踩过的坑：旧路由的处理函数曾叫 `pipeline`，
**在模块级覆盖了 `core.pipeline` 模块**，导致新接口 500 —— 已改名 `legacy_pipeline`，
以后新增同名模块时先 grep 函数名。

---

## 11. 环境体检 / 一键修复

真源 `web/core/health.py`；页面 `#/health`（全局）。诊断复用 `tools/env_check.py --json`
（**用引擎解释器跑**，口径和出片一致），外加三项 Studio 自己的检查：运行时目录是否可写、
引擎解释器是否被配置指到空文件、配置项是否落在连接中心。

### 11.1 为什么只自动修三类

| 类型 | 动作 | 为什么能自动 |
| --- | --- | --- |
| `pip` | `python -m pip install <锁定版本>` | 只装进**引擎解释器**，不动系统 Python；`requirements.txt` 里有精确版本 |
| `mkdir` | 建 `web/var` / `web/var/llm` | 只建 Studio 自己的运行时目录，不碰项目文件 |
| `config` | 清掉 `configs/settings.json` 里指向空文件的 `python` | 先备份；清掉后自动回落到本机默认 venv |
| `comfy_start` | 拉起本机 ComfyUI 后台实例（无窗口） | 复刻桌面版命令行（模型路径 yaml + input/output 目录）；只对 loopback 生效，已在线一律复用，只停自己启动的那个 |

**不能自动的**一律标 `manual` / `page`，并说清原因（这是这个功能的关键）：

* `winget install ffmpeg` —— 要弹 UAC，Studio 不去替你点授权框；
* 填 Key —— 只能人来给（且不该走环境变量：填一次进连接中心，之后所有命令自动带上）；
* manifest 不符 —— 是「仓库被改过」，不是「环境缺东西」，清错方向的自动修复更危险。

把这几类混进「全部修复」的结果是：按钮转两圈、然后什么也没变。**假装修好比没有按钮更糟。**

### 11.2 三条纪律

1. **动作白名单在服务端**：接口只接受 `fix_id`，命令由 `_fix_spec()` 现算；前端传不进一条命令。
2. **复检才是结论**：`pip` 退出码 0 只说明 pip 没崩。修完必重跑 `collect()` 取同一项，
   不过就返回 `ok=false` + 「命令跑完了，但这一项复检仍未通过」。
3. **留痕**：每次修复追加一行到 `web/var/health-fixes.jsonl`（时间 / id / 命令 / rc / 复检结果 / 耗时），
   页面底部可直接看到「上次改了什么、过没过」。

### 11.3 踩过的坑

* **体检不能有副作用**：`_writable()` 一开始用「建个探针文件再删」判断可写，结果 `mkdir` 顺手把目录建了，
  `dir.var` 永远判「通过」，一键修复按钮等于摆设。现在改成「存在 + `os.access(W_OK)`」，建目录留给修复动作。
* **`launcher.py` 会覆盖 `SOLODRAMA_PYTHON`**：它只接受「装了 Pillow/httpx」的解释器（避免一启动就一片红），
  所以想复现「缺依赖」现场必须直接 `python -m uvicorn app:app` 起。
* **`web/var` 里没有 `health-fixes.jsonl` 时 `history()` 返回空**，不报错 —— 页面显示「还没有修复记录」。

---

## 12. 品牌与图标

真源 `tools/make_logo.py`（几何与配色都在文件头常量里），产物在 `web/ui/studio/img/`。

| 文件 | 用在哪 |
| --- | --- |
| `logo.svg` | 侧栏品牌区、`<link rel="icon" type="image/svg+xml">`、README 首图 |
| `icon-192.png` / `icon-512.png` | `manifest.webmanifest` 的 `purpose: any` |
| `icon-maskable-512.png` | `purpose: maskable`：mark 缩到 80%，四周留系统裁切的安全区 |
| `apple-touch-icon.png` | iOS 主屏：**实心方底**（透明角会被系统填成黑色） |
| `favicon-16/32.png` + `favicon.ico` | 老浏览器兜底；ico 内打包 16/32/48/64 |
| `logo-mark.svg` / `logo-mark-light.svg` | 单色 mark：浅底用深墨，深底用琥珀 |

图形语言：**竖屏画幅 + 播放三角**。竖屏是短剧的本体（不是装饰）；播放三角用
`fill-rule="evenodd"` **挖空**，而不是在上面叠一个琥珀色三角形 —— 后者一旦换底色就会露出补丁。

选型时实测的三条（都影响可用性，不是审美偏好）：

1. **描边风格在 16px 会糊成一坨**：「取景框 + 播放」的线宽 5/64 ≈ 1.25px，缩到标签页尺寸后
   框和三角粘在一起；实心剪影（深色画幅 + 挖空三角）才保得住两个形。
2. **细节只在 48px 以上加分**：试过胶片齿孔、底部字幕条 —— 256px 很好看，32px 变噪点、16px 像脏点，
   所以最终只留「画幅 + 三角」两个形。
3. **三角与画框的间距必须 ≥5/64**：第一版 tip 离右边框只有 1px（≈0.25px @16px），
   看起来像连体字，必须留出真正的琥珀边。

改图标的标准动作：

```bash
# ① 改 tools/make_logo.py 顶部的 FRAME / PLAY / AMBER / INK
python tools/make_logo.py            # ② 重新生成 12 个文件（含自检：尺寸 / 透明角 / iOS 满幅）
python web/tests/test_studio_assets.py   # ③ 契约测试会校验「引用不悬空 + 主色与 --accent 一致」
```

产物是**可复现**的：同一浏览器版本下重跑，12 个文件逐字节一致（已验证）。
`brand-mark` 的 CSS 刻意不再画琥珀底 —— 底色与圆角由 `logo.svg` 自带，
否则侧栏图标外面会多出一圈方框，且和 favicon 不是同一个东西。

---

## 13. 可读性 / 动效 / 打开速度（2026-10-29）

### 13.1 字号：整体上调一档，但不是等比放大

`css/tokens.css` 是唯一来源，改这一处全局生效：

| Token | 旧 | 新 | 用在哪 |
| --- | --- | --- | --- |
| `--fs-11` | 11 | **12** | 表头、元信息、表格副行 |
| `--fs-12` | 12 | **13** | 次要说明 |
| `--fs-13` | 13 | **15** | 正文基准 |
| `--fs-14` | 14 | **16** | 小标题 |
| `--fs-16` | 16 | **18** | 卡片内大标题 |
| `--fs-20` | 20 | **24** | 页面标题 |
| `--fs-26` | 26 | **32** | KPI 数字 |

**不是统一 ×1.15**：元信息只 +1，正文 +2，标题 +4~6。等比放大的结果是「字都变大了」，
但主次仍然糊在一起 —— 层级要靠差值，不靠绝对值。配套把 `--row-h` 36→44、`--top-h` 56→60、
`--nav-w` 232→252，否则字变大了会挤在原来的框里。

回归防线：`test_studio_assets.py` 第 7 组卡死下限（正文 ≥14px、元信息 ≥12px、`.btn` ≥34px、
表格行高 ≥40px），并禁止 `app.css` 出现 <11px 的硬编码字号 —— 这类「顺手写小一点」最难发现。

### 13.2 按钮

| 类 | 旧高 | 新高 | 场合 |
| --- | --- | --- | --- |
| `.btn` | 30 | **36** | 默认；页面右上角主操作 |
| `.btn.lg` | 36 | **44** | 空状态里的唯一动作 |
| `.btn.sm` | 24 | **30** | 表格行内、卡片角落 |
| `.btn.icon` | 28 | **36** | 纯图标按钮（也更容易点中） |
| `.btn.stage` | — | **34**（新增） | 流水线每一步的「运行此步 / 打开页面」 |

**流水线每一行现在都有按钮**（之前只有文字，看完还得自己去找页面）：可自动的给「运行此步」，
需人工/被前置挡住的给「打开页面 / 去补齐」。点「运行此步」走的是 `POST /api/pipeline/run`
新增的 `only=<Sx>` 语义 —— **只跑这一条**，不会把前面几步一起跑一遍（`test_pipeline.py` 第 5 组守这个）。

### 13.3 动效：四条规矩

取自 `ui-design-library`（Emil Kowalski 的动效准则），不是自己编的：

1. **只动 `transform` / `opacity`**。动 `width/left/top` 会触发布局，越长越卡。
   `test_motion_contract` 会扫 `@keyframes` 里有没有这些属性。
2. **入场用 `--ease-out`（快进慢出），退场用 `--ease-in`**；「进来慢、停住慢」是最常见的廉价感来源。
3. **高频交互压到 90–120ms**：导航项、悬停只做颜色/背景过渡，不做位移 —— 一天点几十次的东西，
   动效越好越烦。
4. **`prefers-reduced-motion` 必须能全关**（前庭障碍用户）。

落地的东西：

| 位置 | 效果 | 为什么值得存在 |
| --- | --- | --- |
| `#view.view-in` | 6px 上移 + 淡入 180ms | 避免整页内容「凭空出现」（空间连续性） |
| `.card` / `.kpi` | 同款入场，最多错开 60ms | 只给第一层，层级越多越像 PPT |
| `.btn:active` | 下压 1px + 轻微缩放 | 按压反馈要在 pointer-down 就给 |
| `.btn.primary` | 指针位置的径向高光（`--mx/--my`） | 「鼠标流动」；只给主按钮，属于反馈不是装饰 |
| `#loadbar` | 请求 >200ms 才出现的顶部进度条 | 快请求闪一下比不闪更烦，所以延迟 200ms |

### 13.4 打开速度：两级缓存 + 空闲预取

慢的根因不是前端，是**每个重接口背后都起一个 Python 子进程**：
`workflow.status` / `project_setup.show` / `env_check` 各 0.5–1.3 秒。

| 层 | 做法 | 效果（实测） |
| --- | --- | --- |
| 后端 | `adapters` 的 TTL：workflow 5→**12s**、setup 10→**20s**、env 30→**60s** | 项目详情 970ms → **5ms**；生成通道 669ms → **4ms**；环境体检 1281ms → **2ms** |
| 前端 | `api.js` 对**只读重接口**做 8–60s 短缓存（`TTL` 表） | 再打开同一模块 **0 次网络请求**（用 fetch 计数验证） |
| 预取 | 首屏画完、`requestIdleCallback` 里预热 workflow/setup/capabilities | 第一次点「项目详情」就不用等 |
| 首屏 | `caps` / `projects` / `health` 由串行改 `Promise.all` | 少 2 个 RTT |

**写操作一定清缓存**（`POST/DELETE` 成功后 `CACHE.clear()`），所以「点完按钮还看到旧数据」不会发生。
`/api/jobs`、`/api/run`、SSE 这些秒级数据**明确不缓存** —— `test_motion_contract` 第二段会拦：
谁把 jobs 加进 TTL 表，测试就红。

### 13.5 这轮踩的两个坑

* **长路径顶穿卡片**：字号放大后，设置页「当前解释器 / ffmpeg」这些路径溢出卡片边界。
  原因是环境行用了 flex（`span` 不肯收缩）且 `.kv` 写死 `max-width: 720px`。
  改成两列栅格 + `minmax(0,1fr)` + `overflow-wrap: anywhere`，并在 ≤1500px 时上下排。
* **`nth-of-type` 别用在混排容器**：卡片入场用 `.view-in .card:nth-of-type(2)` 控制错峰，
  只在 card 全是 `<section>` 的页面成立；混排页面上错峰会失效（视觉上只是少了 30ms 延迟，不影响功能）。

---

## 14. 工作流 / 画风 / 对话（2026-10-29 第二批）

### 14.1 本地出片工作流：手动替换 + 端口识别 + 槽位裁剪

**换工作流**不再需要改代码：连接中心 → **出片工作流** → 上传或粘贴 JSON → 校验 → 自动生成映射 → 设为当前。

| 文件 | 作用 |
| --- | --- |
| `web/var/comfy/workflows/<id>.json` | 上传的工作流（内置那份只读，永不被覆盖） |
| `web/var/comfy/workflows/<id>.map.json` | 自动生成的节点映射（角色 → 节点 id） |
| `web/var/comfy/workflows/index.json` | 哪一份是「当前使用」 |

保存时做三件事：校验是 **API 格式**（带 `nodes/links` 的界面导出会被拒，并提示「导出 API 格式」）、
校验**有输出节点**（没有的话跑完不出东西）、按端口角色生成映射。识别不出的角色**如实列出来**：
`prompt` / `images` 缺了算「必需」，其余只是「不覆盖，沿用工作流里的值」。

**端口识别与槽位裁剪**的真源是 `stages/video/comfyui/comfy_ports.py`（纯标准库，引擎脚本直接 import；
`web/core/comfy_ports.py` 只按路径加载它）：

* `describe(wf)`：认出提示词 / 参考图槽 / 步数 / 种子 / 画幅 / 输出，算出**参考图容量**；
  两种槽写法都认 —— `image1` 与 H3 的 `ref_images.ref_image_0`；
* `prune_for_refs(wf, n)`：**真的改图** —— 删掉多余的 `LoadImage`、删掉多槽节点上的 `ref_image_n` 字段、
  再按输出节点做可达性剪枝。实测把 6 槽工作流裁到 2 槽：删 4 个加载器 + 1 个孤立节点，**零悬空引用**。

为什么必须真删而不是「不传值」：本地提交的是整张图，多余的 `LoadImage` 会带着上次的文件名照样执行
（串景 + 白占显存）；云端的 `nodeInfoList` 是覆盖表，没发的节点沿用保存值 —— 这两条都踩过。

**云端的边界**：RunningHub 只能覆盖节点值，**不能删节点**。所以那边做的是「按张数决定喂哪几个槽 +
多余的按策略处理」，界面上会如实写清楚，而不是假装关掉了。

### 14.2 画风库：6 个官方风格进了系统默认

`configs/styles.json`（真源，可增补）+ `style_gate.py` 的轨道。轨道决定**生产规格**
（资产几张、单镜多长、交付到哪），风格只决定**看起来像什么** —— 两者不能混，选错轨道会在出片一半才发现资产不够。

| 风格 | 轨道 | 场景 |
| --- | --- | --- |
| 电影超写实 `cinematic` | live_action | 真人写实、电影感 |
| 拉美魔幻现实 `magical-realism` | live_action | 文艺、魔幻但不靠特效 |
| 日式青春胶片 `jp-youth-film` | live_action | 怀旧、颗粒、生活流 |
| 短剧风格 `short-form-drama` | live_action | 强情绪、快识别（真人短剧默认） |
| 日式赛璐璐 `cel-shading` | 2d_animation | 二维动画 |
| 国漫二次元常用风格 `cn-anime-style` | 2d_animation | 国漫插画感 |

提示词为官方原文，未改写。确认画风时会一并写进 `style-plan.json` 的 `style_prompt` / `style_name`。
`live_action` 原来没有子模式，这轮补了 `default_sub_mode = short-form-drama` —— 否则
`style set live_action`（不带 `--sub-mode`）会判「未知子模式 None」，整条 setup 流程都会挂
（实测挂了 12 个引擎测试，见 §14.5）。

### 14.3 新建项目：路径 + 画幅 + 分辨率 + 画风

`POST /api/projects/create` 新增 `resolution` / `style` / `track`。建档后调引擎自己的
`drama.py style set` 与 `project_setup.py set --resolution`，**然后回读 `style-plan.json` /
`project-setup.json` 验真**：

> 这两个脚本在「其它 G-0 项没填」时会用 **rc=4** 表示「等待确认」，但文件其实已经写了。
> 拿退出码当结论会误报「分辨率没写上」—— 实测踩到，改成回读文件。

界面里路径用「已有项目的上级目录」做候选根（浏览器拿不到系统目录选择框，这点在弹窗里写明）。

### 14.4 对话模式

顶栏「助手」→ 抽屉。**服务端只出提案，不执行任何动作**：

| 动作 | 谁执行 | 边界 |
| --- | --- | --- |
| `navigate` | 前端直接跳 | route 按页面清单白名单过滤 |
| `run` | 前端弹确认 → `pipeline/run` 的 `only=` | 只允许流水线登记的免费命令，`assets.rh` 这类计费命令**代码里就不在白名单** |
| `none` | — | 问状态类问题必须落到这里 |

模型输出不是 JSON 时整段当回答、动作置空（宁可少做）。实测三句：

* 「现在卡在哪一步？」→ 准确说出停在 S1、0/11 完成、下一步是调研，`action=none`；
* 「带我看看资产」→ `navigate assets`；
* 「跑一下转分镜」→ 模型主动发现「可执行命令里没有这一项」，反问要哪个，并说明「真跑会写盘，我不替你按」。

### 14.5 对话引导（2026-10-29 第三批）

助手最难的不是「会不会答」，而是**用户不知道能问什么、问完不知道该点哪**。所以引导做了三层：

| 层 | 位置 | 谁生成 | 什么时候出现 |
| --- | --- | --- | --- |
| 提示词 | `stages/creation/prompts/assistant-chat.md` | 人手写 | 每次提问都生效 |
| 开场引导 | `GET /api/assistant/welcome`（**不调模型**） | 服务端按状态拼 | 打开抽屉 |
| 接着问 + 去 XX | `POST /api/assistant/chat` 的 `suggestions` / `goto` | 模型 + 服务端各一条 | 每次回答后 |

**提示词**里放的是产品知识，不是话术：15 个页面的 route 与用途、S1–S11 与页面的对应、
五条不能给错的规矩（画风不可换 / 发布版唯一来源 / 资产目录 / 按段计费 / 字幕真对齐）、
80 字口径、以及六种常见问法的接法。它是**产品说明书**，改页面就要改它。

**动作有两个来源**：

* `action` 是模型提案（可能 `none`，也可能被白名单丢掉）；
* `goto` 是服务端按「第一个未完成环节」算出来的，**不经过模型，也就不会幻觉**。

为什么要两条：用户问「现在卡在哪」，按规则模型只该回答（`action=none`），但这句话的下一个动作
永远是明确的——去卡住的那页。前端把 `goto` 画成次要按钮，模型没给动作也不会断头路。

前端渠道：chips（`suggestions`，点一下即发送）＋ 按钮（`navigate` 的 `label` 是中文名，
`run` 的 `label` 是环节说明，不再暴露 route/命令 id）。`suggestions` 由服务端归一化：去空、去重、
最多 3 条、单条 ≤40 字；模型不按格式给就用状态兜底（`_stage_suggestions`），**永远有候选**。

契约测试（`test_assistant.py` §7/§8）守两件事：

1. `ROUTES` 里每个 id 都必须出现在提示词里 —— 新增页面忘改提示词会直接红；
2. `goto_hint` 在状态读不到时返回 `{}`（宁可没有按钮，也不要指错路）。

实测（真实 DeepSeek + 真实项目）：

| 输入 | 输出 |
| --- | --- |
| （打开抽屉） | 「《2、母亲之路》已完成 0/11，停在 调研」+ 三条 chips + 页脚「模型：DeepSeek（云端）」 |
| 点「现在卡在哪一步？」 | 报 0/11 + S1 + 建议生成调研模板；下方「去创作中心（卡在「调研」）」 |
| 「帮我直接出片，云端跑」 | 拒绝并说明「0/11、S6 没有输入、27 币/任务 + 1 币/秒」，指回创作中心，**不给 run** |
| 「出片大概要花多少钱？」 | 说清按段计费与「段数定不下来，总价算不出」，`navigate cost` |
| 无项目「我想做一部海外短剧，从哪开始？」 | 讲新建时要选路径/画幅/分辨率/画风，`navigate projects` |

### 14.6 这轮踩的坑

* **模板数量的断言不该写死**：新增一个 `assistant.chat` 用途就让「应有 7 个模板」红了。改成
  「≥7 且每个用途都有模板」—— 测试要守契约，不守数字。
* **`live_action` 加了子模式但没有默认值** → `style set live_action` 直接报「未知子模式 None」，
  连带 12 个引擎测试失败。加子模式时必须同时给默认值。
* **`project_setup` 的 rc=4 不是失败**：它是「等待确认」，文件已写。所有「跑完就断言」的地方都要回读文件。


## 15. 本地 ComfyUI 按需启动（2026-10-29）

### 15.1 之前为什么必须手点

ComfyUI Desktop 是 Electron 外壳，真正提供服务的是它 spawn 的 `python main.py`。旧实现
把「拉起进程」判为不可自动化（`health._MANUAL_WHY["本机服务"]`），于是每次出图前都要先开桌面版：
连不上 → 体检提示「需手动启动」→ 用户去开窗口 → 回来重测。这条链本身没有错，只是把机器能做的事留给了人。

### 15.2 做法

真源是 `stages/assets/comfyui/comfy_boot.py`（纯标准库，引擎脚本可直接用），Web 层
`core/comfy_launcher.py` 只负责按路径加载 + 读连接中心 + 把启动变成可轮询的后台动作。

启动命令**复刻桌面版**，三个参数不能省：

| 参数 | 少了会怎样 |
| --- | --- |
| `--extra-model-paths-config <inst-*.yaml>` | 找不到模型，报「模型缺失」，极易误判成装坏了 |
| `--input-directory / --output-directory` | 产物落进安装目录，而不是共享目录 |
| `--enable-manager`（来自 `launchArgs`） | 插件管理不可用；其余桌面版私有参数一律白名单挡掉 |

安装信息不手填：读 `%APPDATA%\Comfy Desktop\installations.json`（`installPath` / `launchArgs` /
`id`），解释器取 `<安装>/ComfyUI/.venv/Scripts/python.exe`，模型路径取 `instance-model-paths/<id>.yaml`。
换机器、换实例都不用改代码；找不到才要求手填（`connections.json` 的 `launch` 段）。

三个入口共用同一个 `ensure()`：

* 连接中心「本地出图」卡片：`GET /api/comfy/status` + `POST /api/comfy/start|stop`（异步，前端轮询进度）；
* 环境体检 `svc.comfy`：`fix.kind = comfy_start`，**同步等就绪**（复检要的是「现在能用了吗」）；
* 出图脚本 `gen_assets_local.py`：`--submit` 与 `--check` 之前先 `ensure()`，`--no-boot` 可关。

### 15.3 六条边界

1. **只对 loopback 生效**：远程地址只探测，不在本机起进程（起了也没用，还白占显存）。
2. **在线就 attach**：8188 上已有 ComfyUI 就复用，绝不另起；桌面版 `portConflict: auto` 会自己让路。
3. **端口被非 ComfyUI 占用时停下报错**，不硬起（硬起的表现是「点了没反应」，比报错更难查）。
4. **停止只停自己的**：锁里记 pid，且必须「这个 pid 正在监听该端口」才允许 kill。
5. **不做开机常驻**：16G 内存下常驻代价偏高，按需启动已满足「不用手点」。
6. **失败给人话**：按日志分类为 端口被占 / 缺 torch / CUDA 失败 / 启动超时 / 缺安装，各带下一步。

### 15.4 这轮踩的坑

* **监听端口的不是 spawn 的那个进程**：0.42 的 `main.py` 会再拉一个子进程 bind 端口
  （实测 spawn=23324、LISTENING=8792）。锁里只记 spawn pid 时，`stop()` 会判 `not_listener` 永远停不掉。
  现在锁同时记 `spawn_pid` 与 `pid`，就绪时回填真正的监听者。
* **不能拿「pid 还活着」当所有权**：Windows 会复用 PID。判据改成「它是这个端口的监听者」。
* **同步等待会掐死界面**：单进程 uvicorn 下一个 90 秒的请求会让整页刷不出来，所以界面走异步 + 轮询。
* **`generators.py` 硬编码 8188**：连接中心改了地址它不认，界面说「未启动」而实际能出图。已改为读连接配置。
