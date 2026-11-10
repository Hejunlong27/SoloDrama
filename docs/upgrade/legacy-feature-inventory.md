# 既有功能清单（Legacy Inventory）

> 判据：**有代码入口 + 有落盘产物**才算「已实现」。同源于 `docs/upgrade/02-current-feature-inventory.md`。
> 这张表是 2.0 的「不得弄丢」清单，也是「不得造假」清单。

## A 创作层

| # | 功能 | 入口 | 产物 | 状态 |
|---|---|---|---|---|
| A1 | 剧项目创建 | `POST /api/projects/create` → `init_project.py` | 工作区 + `layout.json` | 已实现 |
| A2 | 题材模板装/卸 | `/api/skills/*` | 工作区 Skill 目录 | 已实现 |
| A3 | 灵感→企划→成文 | `/api/create/*` → `web/core/creation.py` | `00-创作/` Markdown | 已实现 |
| A4 | LLM 网关 | `/api/llm/*`（9 端点） | `web/var/llm_usage` | 已实现 |
| A5 | 助手浮窗 | `/api/agent/*` | 不落盘 | 已实现 |
| A6 | 内容质量检查（FFS/连续性） | — | — | **已移除**，无脚本 |
| A7 | 角色差异化检查 | — | — | **已移除**（`character_design.py` 不在仓库） |

> A6/A7 禁止建页面。建了就是假门禁。

## B 契约层

| # | 功能 | 入口 | 状态 |
|---|---|---|---|
| B1 | Markdown → 制作包 | `stages/import/md2pack.py` | 已实现 |
| B2 | 制作包结构校验 `SHOT001–021` | `pack_spec.py` | 已实现（批处理） |
| B3 | H3 六段式解析与 lint | `h3_prompt.py`：`SECTIONS` `split_sections` `normalize` `lint` | 已实现（**库函数，无 HTTP**） |
| B4 | 台词标记归一 | `prompt_marks.py`：`normalize_dialogue` `find_bare` `migrate` | 已实现 |
| B5 | 制作包导入 | `pack_import.py` | 已实现 |
| B6 | 预设套用 | `preset_apply.py` | 已实现 |

## C 生产引擎（13 节点）

| 节点 | 名称 | 计费 | 判据 |
|---|---|---|---|
| `import.pack` | 导入-打包 | 0 | 产物存在 |
| `asset.render` | 资产出图 | 0 | 图数对齐 |
| `import.bind` | 导入-绑定 | 0 | 绑定表 |
| `board.frame` | 分镜图 | 0 | 每镜 1 张 9:16 |
| `import.gate` | 导入门禁 | 0 | `pack_spec` 无 err |
| `video.resolve` | 出片-解析 | 0 | 素材齐 |
| `video.batch` | 出片-批量 | **★** | 退出码 3 = 批次缺口 |
| `video.audit` | 出片-审计 | 0 | — |
| `edit.master` | 剪辑-母版 | 0 | 帧数校验 |
| `edit.upscale` | 剪辑-放大 | 0 | — |
| `edit.subtitle` | 剪辑-字幕 | 0 | 时间轴自检 |
| `edit.draft` | 剪辑-剪映工程 | 0 | `draft_manifest.verdict.pass` |
| `edit.release` | 剪辑-发布版 | 0 | `EpisodeNN.mp4` 落 `09-发行/剧集/` |

## D 通道与生成

| # | 功能 | 入口 | 状态 |
|---|---|---|---|
| D1 | 本地 ComfyUI | `/api/comfy/*` | 已实现 |
| D2 | 云端 ComfyUI | `cloud/`（10 模块） | 已实现 |
| D3 | RunningHub | `/api/generators/rh` | 已实现 |
| D4 | 工作流参数/映射/备份/还原 | `/api/comfy/workflows/{id}/*` | 已实现 |
| D5 | 模型确认单 | `model_gate.py` | 已实现 |
| D6 | 生成预检 | `gen_preflight.py` `episode_preflight.py` | 已实现 |
| D7 | 出网守护/域名信任 | `stages/_netguard.py` | 已实现 |
| D8 | 计费闸门 | 428 + confirm；`CMD.danger > CMD.READ` | 已实现 |
| D9 | 台账（唯一聚合） | `cost_ledger.py` `_ledger_core.py` `_rates.py` | 已实现 |
| D10 | 成本展示 | `/api/studio/cost` | 已实现 |

## E 后期与发行

| # | 功能 | 入口 | 状态 |
|---|---|---|---|
| E1 | 母版拼接 | `edit_draft.py` | 已实现 |
| E2 | 高清放大 | `upscale.py` | 已实现 |
| E3 | 字幕 | `subtitle.py`（含 `--from-srt auto`） | 已实现 |
| E4 | BGM | `bgm.py` | 已实现 |
| E5 | 剪映工程 | `pyJianYingDraft==0.3.1` | 已实现（MP4 仍是唯一发布版） |
| E6 | 发布版导出 | `release_export.py --all --apply` | 已实现（唯一出口） |
| E7 | 发行资料检查 | `release_check.py` | 已实现 |
| E8 | 版权资料 | `copyright_kit.py`（三入口 A/B/C） | 已实现 |
| E9 | 画面合规 | `compliance_precheck.py` `compliance_media_check.py` | 已实现 |
| E10 | 封面生成 | — | **引擎已移除**（`cover_prompt.py`/`cover_forge.py` 不在仓库） |
| E11 | 交付规格 1080×1920 | `delivery_spec.py` | 已实现 |

## F 控制层

| # | 功能 | 入口 | 状态 |
|---|---|---|---|
| F1 | 工作区登记/发现/切换 | `/api/workspaces*` | 已实现 |
| F2 | 作业队列 + SSE | `/api/jobs*` `/api/events/stream` | 已实现 |
| F3 | 审计日志 | `/api/audit` | 已实现 |
| F4 | 环境体检/修复 | `/api/health/*` | 已实现 |
| F5 | GPU 锁 | `_lock.py` `/api/locks` | 已实现 |
| F6 | 资源监视 | `/api/monitor` + `monitor.js` | 已实现 |
| F7 | 只读模式 | `SOLODRAMA_CONSOLE_READONLY` | 已实现（后端 423，非隐藏按钮） |
| F8 | 旧控制台 | `/ui/` | 保留 |
| F9 | 系统下载/更新 | `/api/system/*` | 已实现 |

## G 2.0 要新增的（只有这两处是「补后端」）

| # | 能力 | 为什么要新增 |
|---|---|---|
| G1 | 提示词结构化读（`sections`） | 现有 `prompt` 是单串，六段结构在传输层丢失 |
| G2 | 提示词写回 + 单镜即时校验 | 现在只能整包批处理，改一个字要回编辑器 |

其余全部是「把已有端点组织成专业界面」。
