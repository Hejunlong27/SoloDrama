# 01 · 当前架构审计（SoloDrama 现状）

> 审计基线：`main` @ `2347df2`，工作树干净（`git status --short` 无输出）。
> 采集时间：2026-11-10。所有数字均来自实际命令输出，未使用估算。

## 1. Git 实况

| 项 | 值 |
|---|---|
| 当前分支 | `main` |
| HEAD | `2347df2 chore(manifest): rebase 到远端 README 之后重建完整性清单` |
| 未提交修改 | 无 |
| 未跟踪文件 | 无 |
| 上一个 Release 锚点 | `v0.7.65` = `54b5da5`（VERSIONS.md 口径） |

结论：**没有用户未完成的开发内容**，可以直接在干净基线上推进 2.0，不会覆盖任何人的改动。

## 2. 目录体量与真实构成

| 目录 | 实际内容 | 体量 |
|---|---|---|
| `web/` | `app.py`(1813 行) + `launcher.py`(405 行) + `core/`(30 个模块) + `ui/`(177 个文件) + `tests/`(26 个测试文件) + `var/`(运行态) | 控制层 |
| `stages/` | `_layout.py` `_ledger_core.py` `_netguard.py` `_rates.py` `_comfy_http.py` + 7 个子域（`creation` `assets` `import` `production` `video` `edit` `subtitle`） | 引擎层 |
| `configs/` | 13 项：`channels.json` `edit-draft.json` `looks.json` `narratives.json` `render-presets.json` `subtitle-styles.json` `tracks.json` `skills-sources.json` `settings.json` `model-plan.example.json` + `capabilities/` `presets/` | 配置真源 |
| `cloud/` | 10 个模块（`cli` `config` `health` `ledger` `provisioner` `pull` `session` `transport`）+ `tests/` | 云端通道 |
| `tools/` | `env_check.py` `make_logo.py` `rebuild_manifest.py` + `tests/` | 运维 |
| `design/` | **仅 1 个文件**：`SoloDrama_Studio_产品定义_v1.md`(100 行) | 产品口径 |
| `docs/` | 30 个条目（含 `orchestration/` `pack/` `styles/` `assets/` `distribution/` `patches/` `archive/`） | 规范真源 |
| `manifest.sha256` | 全仓文件完整性清单 | 防篡改 |

## 3. 四层架构的真实映射

文档要求「不许合并四层」。实测四层是**物理分离**的，靠文件与子进程解耦，这是本项目最大的资产，2.0 必须原样保留：

| 层 | 代码位置 | 边界形式 | 真源文件 |
|---|---|---|---|
| ① 创作层 | `stages/creation/skills/`（Skill 包）＋ `web/core/creation.py`、`web/core/skills.py`、`web/core/llm/`（9 模块） | Markdown 文档落工作区 | 工作区内 `00-创作/`（创作链）与 `03-剧本/` 的 Markdown |
| ② 契约层 | `stages/import/`：`md2pack.py` `pack_spec.py` `pack_import.py` `h3_prompt.py` `prompt_marks.py` `preset_apply.py` | Markdown → JSON 制作包 | `docs/pack/PACK-SPEC.md`、`docs/pack/H3-REF2VA-PROMPT.md` |
| ③ 生产引擎层 | `stages/{assets,production,edit,subtitle,video,import}/scripts/` ＋ `cloud/` | 全部为**独立可执行脚本** | `stages/production/scripts/nodes.py`（13 节点） |
| ④ Studio 控制层 | `web/app.py` + `web/core/` + `web/ui/` | HTTP + SSE | 本层消费 ①②③，不逆向依赖 |

### 3.1 Web 与引擎之间**零 import**（重要）

```
$ grep -rn "from stages|import stages" web/*.py web/core/*.py
（无输出）
```

Web 层调引擎的唯一方式是子进程：

```python
# web/core/adapters.py:64
argv = [paths.engine_python(), str(script)] + [str(a) for a in args]
```

**这是必须守住的铁律**：2.0 任何新页面需要的引擎能力，都只能「新增/复用脚本 + 子进程调用」，不得在 `web/core/` 里 `import stages.*`。否则 Web 依赖引擎内部实现，引擎改一个函数签名就会连带前端崩。

### 3.2 目录抽象的真源

资产/数据/剧本/发行路径**不能在前端拼接**。唯一真源两处：

- 引擎侧：`stages/_layout.py`
- 控制台侧：`web/core/studio.py`

`web/core/studio.py` 的路径函数（均已实测存在）：

| 函数 | 行 | 职责 |
|---|---|---|
| `out_dir(ws)` | 60 | `07-成片/`（成片输出） |
| `data_dir(ws)` | 70 | `data/`（契约物：`h3_prompts.json` 等） |
| `script_dir(ws)` | 80 | 剧本目录定位 |
| `assets_dir(ws)` | 91 | `04-资产/`（`_layout.py::assets_dir()` 的等价实现） |
| `release_dir(ws)` | 158 | `09-发行/` |
| `engine_root(ws)` | 148 | 引擎根 |

## 4. 进程与端口拓扑

| 组件 | 启动方式 | 端口 | 说明 |
|---|---|---|---|
| Studio 主服务 | `start.cmd` → `web/launcher.py` → uvicorn | 8788 | 单端口，全部能力 |
| 只读形态 | `start-readonly.cmd` → `start.cmd --readonly` | 8788 | 置 `SOLODRAMA_CONSOLE_READONLY=1` |
| 本地 ComfyUI | 手动（Studio 可启停） | 8188 | `web/core/comfy_launcher.py` |
| 云端 ComfyUI / RunningHub | 外部 HTTP | — | `cloud/`、`stages/_netguard.py` 守护 |

静态挂载（`web/app.py:1795/1800`）：

```python
app.mount("/ui", _FreshStatic(directory=str(UI_DIR), html=True), name="ui")     # 旧控制台
app.mount("/studio", _FreshStatic(directory=str(STUDIO_DIR), html=True), name="studio")  # Studio
```

`_FreshStatic` 不是随便写的类：Starlette 默认不发 `Cache-Control`，Chrome 会按「距 Last-Modified 的 10%」启发式缓存，导致改完 CSS 看不到效果。**它是项目的一次真实事故补丁**（见 `web/ui/studio/index.html` 顶部注释）。2.0 改前端资源必须继续走这套机制，换构建工具会直接丢掉这个修复。

## 5. HTTP 面规模

`grep -cE '@app\.(get|post|put|delete|websocket)' web/app.py` → **111 个端点**。

按域粗分：

| 域 | 端点数（约） | 代表端点 |
|---|---|---|
| 工作区/项目 | 12 | `/api/workspaces/discover` `/api/projects/create` `/api/workspaces/prune` |
| 作业/事件 | 8 | `/api/jobs` `/api/jobs/{id}/stream` `/api/events/stream` |
| Studio 数据 | 10 | `/api/studio/overview` `/api/studio/shots` `/api/studio/release` `/api/studio/cost` |
| ComfyUI 工作流 | 12 | `/api/comfy/workflows/{id}/map` `/validate` `/backups` `/restore` |
| 连接/健康 | 10 | `/api/connections/{kind}/test` `/api/health/checks` `/api/health/fix` |
| LLM 网关 | 9 | `/api/llm/providers` `/api/llm/complete` `/api/llm/usage` |
| 创作 | 6 | `/api/create/state` `/api/create/idea` `/api/create/write` `/api/create/generate` |
| 画布/图解 | 7 | `/api/canvas/series` `/api/graph` `/api/graph/layout` |
| 资产/文件/媒体 | 7 | `/api/artifacts` `/api/file` `/api/media` `/api/studio/media-info` |
| 其余（系统/时间/技能/预设） | ≈30 | `/api/system/update` `/api/time/global` `/api/skills/*` |

**结论：后端能力远超当前 UI 已暴露的程度。**2.0 的 UI 工作量主要在「把已有端点组织成专业界面」，而不是「先补后端」。

## 6. 启动链路

```
start.cmd
  → 优先 envs\solodrama-web\Scripts\python.exe，回退 py -3 / python
  → web\launcher.py（探测端口、挑解释器、可选 --readonly）
  → uvicorn app:app  :8788
  → GET /            → 302 /studio/
  → /studio/         → web/ui/studio/index.html（零构建 ES Module）
```

前端零构建：`index.html` 直接 `<script type="module" src="js/main.js?v=20261105a">`。**没有 npm / 没有打包器 / 没有 node_modules**。2.0 若不引入构建链，就必须继续用「原文件 + 版本号查询串」这套办法；若引入构建链，属于架构变更，需单独评审。

## 7. 与既有文档的口径冲突（已记录，未擅自改文档）

| # | 文档说法 | 代码实况 | 处置 |
|---|---|---|---|
| C1 | `design/SoloDrama_Studio_产品定义_v1.md` 里程碑写「v0.9：**12 视图**骨架」 | `main.js` 的 `VIEWS` 注册 **22 个**视图 | 产品定义文档滞后，2.0 需重写 §5 信息架构 |
| C2 | 同文档 §5 IA：全局 6 项 / 项目 6 项 | 实际 `NAV`：全局 4 项 + 当前项目 11 项（含 1 个浮窗） | 同上 |
| C3 | 同文档 §8 称 `v1.0` 为「本期」 | `index.html` 品牌副标题仍是 `STUDIO 0.2` | 品牌版本号未同步 |
| C4 | 2.0 指令要求「深浅双主题」 | `tokens.css` / `app.css` **零**处 `prefers-color-scheme` / `data-theme` | 缺口，Phase 1 必修 |

> 纪律：以上仅做记录。**冲突不通过改文档掩盖**，先由 2.0 的实施把代码与文档拉齐，再统一改文档措辞。

## 8. 架构层面 2.0 的红线（从现状反推）

1. 保持 `web/` → 子进程 → `stages/` 的边界，禁止 `import stages`。
2. 保持 `studio.py` / `_layout.py` 作为路径唯一真源，禁止前端拼 `04-资产/...`。
3. 保持零构建前端（除非单独评审）。
4. 保持 `_FreshStatic` + 版本号查询串的缓存策略。
5. 保持 111 个端点的语义，UI 重构不得顺手改后端返回结构（改了就要同步夹具）。
