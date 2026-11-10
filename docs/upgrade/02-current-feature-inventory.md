# 02 · 当前功能清单（按真实入口盘点）

> 判据：**有代码入口且有落盘产物**才算「已实现」。只有页面没后端的记为「壳」。
> 数据来源：`web/app.py`（111 端点）、`web/core/`（30 模块）、`stages/*/scripts/`（真实脚本）、`web/ui/studio/js/views/`（23 文件）。

## 1. 创作层

| # | 功能 | 真实入口 | 落盘产物 | 状态 |
|---|---|---|---|---|
| A1 | 剧项目创建 | `POST /api/projects/create` → `stages/production/scripts/init_project.py` | 工作区目录 + `layout.json` | 已实现 |
| A2 | Skill 模板安装/卸载 | `/api/skills/*` → `web/core/skills.py` | 工作区 Skill 目录 | 已实现 |
| A3 | 灵感 → 企划 → 逐步成文 | `/api/create/{state,read,idea,write,generate}` → `web/core/creation.py` | Markdown 落 `00-创作/` | 已实现 |
| A4 | LLM 网关（多供应商/用途路由） | `/api/llm/*` → `web/core/llm/`（providers/gateway/budget/safety/store/templates） | `web/var/llm_usage` 台账 | 已实现 |
| A5 | 助手浮窗（工具调用） | `/api/agent/{tools,chat}` → `web/core/agent.py` | 对话不落盘 | 已实现，浮窗形态 |
| A6 | 内容质量检查（FFS lint / 连续性） | — | — | **已移除**（记忆红线 7：现行不可执行门禁） |
| A7 | 角色差异化检查 | — | — | **脚本已移除**（`character_design.py` 不在仓库），无门禁 |

> A6/A7 必须写进 2.0 的 UI 决策：**不得为它们建页面**。页面建了但无真规则 = 假检查，违反「提示词校验必须调用真实规则」。

## 2. 契约层

| # | 功能 | 真实入口 | 产物 | 状态 |
|---|---|---|---|---|
| B1 | md2pack（Markdown → 制作包） | `stages/import/md2pack.py` | `episodes/*.json` `assets/*.json` | 已实现 |
| B2 | 制作包结构校验 | `stages/import/pack_spec.py`，规则 `SHOT001–SHOT021` | 校验报告 | 已实现（**批处理**） |
| B3 | H3 六段式解析 | `stages/import/h3_prompt.py`：`SECTIONS`(6) / `split_sections()` / `normalize()` / `lint()` | — | 已实现（**纯库函数，无 HTTP 暴露**） |
| B4 | 台词 `<d>[Chinese] …</d>` 归一 | `stages/import/prompt_marks.py`：`normalize_dialogue` `find_bare` `migrate` | 改写提示词文件 | 已实现 |
| B5 | 制作包导入 | `stages/import/pack_import.py` | `data/` 契约物 | 已实现 |
| B6 | 预设套用 | `stages/import/preset_apply.py` | — | 已实现 |

**关键发现（决定 Phase 3 的工作量）**：

```python
# web/core/studio.py:739  prompt_of()
return {"ok": True, "shot": shot, "duration": ..., "ratio": ..., "voice": ...,
        "prompt": v.get("prompt") or ""}      # ← 整段当**一个字符串**返回
```

- 前端拿到的提示词是**一整段文本**，没有六段结构。
- `GET /api/studio/prompt` 是**只读**，**没有写接口**。
- `h3_prompt.split_sections()` / `lint()` 已经能给出六段与规则结论，但**从未通过 HTTP 暴露**。

→ Phase 3「六段式结构化编辑 + 真规则校验」的正确做法：**新增两个薄端点复用 `h3_prompt`**，不是在前端写正则假装解析。

## 3. 生产引擎层（13 节点，真源 `stages/production/scripts/nodes.py`）

| # | 节点 id | 名称 | 计费 | 判据（verdict） |
|---|---|---|---|---|
| 1 | `import.pack` | 导入-打包 | 0 | 产物存在 |
| 2 | `asset.render` | 资产出图 | 0（本地） | 图数对齐 |
| 3 | `import.bind` | 导入-绑定 | 0 | 绑定表 |
| 4 | `board.frame` | 分镜图 | 0（本地） | 每镜 1 张 9:16 |
| 5 | `import.gate` | 导入门禁 | 0 | `pack_spec` 报告 |
| 6 | `video.resolve` | 出片-解析 | 0 | 素材齐 |
| 7 | `video.batch` | 出片-批量 | **★计费** | 退出码 3 = 批次缺口 |
| 8 | `video.audit` | 出片-审计 | 0 | — |
| 9 | `edit.master` | 剪辑-母版 | 0 | 帧数校验 |
| 10 | `edit.upscale` | 剪辑-高清放大 | 0（GPU） | — |
| 11 | `edit.subtitle` | 剪辑-字幕 | 0 | 时间轴自检 |
| 12 | `edit.draft` | 剪辑-剪映工程 | 0 | `draft_manifest.json` 的 `verdict.pass` |
| 13 | `edit.release` | 剪辑-发布版 | 0 | `EpisodeNN.mp4` 落 `09-发行/剧集/` |

`nodes.py` 另有 5 个 stage 元数据（`import` `asset` `board` `video` `edit`）带 `why` 字段，说明每个阶段「为什么存在」。**这是天然的 UI 文案来源**，2.0 的流程视图应直接读它，不要另写一套人话。

## 4. 通道与生成

| # | 功能 | 入口 | 状态 |
|---|---|---|---|
| D1 | 本地 ComfyUI 通道 | `/api/comfy/*` + `web/core/comfy_{launcher,ports,probe,store}.py` | 已实现（启停/拆线/放显存） |
| D2 | 云端 ComfyUI | `cloud/`（provisioner/session/transport/ledger/health/pull） | 已实现 |
| D3 | RunningHub | `/api/generators/rh` + `stages/production/scripts/gen_assets_rh_workflow.py` | 已实现 |
| D4 | 工作流参数映射/校验/备份/还原 | `/api/comfy/workflows/{id}/*`（12 端点） | 已实现 |
| D5 | 模型确认单 | `stages/production/scripts/model_gate.py` | 已实现 |
| D6 | 生成预检 | `stages/production/scripts/gen_preflight.py`、`episode_preflight.py` | 已实现 |
| D7 | 域名信任 / 出网守护 | `stages/_netguard.py` | 已实现 |
| D8 | 计费确认闸门 | `web/app.py` 428 + confirm、`CMD.danger > CMD.READ` | 已实现 |
| D9 | 花费台账（唯一聚合） | `stages/production/scripts/cost_ledger.py` + `stages/_ledger_core.py` + `stages/_rates.py` | 已实现 |
| D10 | 成本展示 | `GET /api/studio/cost` → `studio.cost(ws)` | 已实现 |

**D9 纪律**：`cost()` 已有唯一聚合实现，2.0 的「成本中心」必须**调它**。另写一套汇总 = 数字对不上 = 用户失去信任。

## 5. 后期与发行

| # | 功能 | 入口 | 状态 |
|---|---|---|---|
| E1 | 母版拼接 | `stages/edit/scripts/edit_draft.py`（母版轴） | 已实现 |
| E2 | 高清放大 | `stages/subtitle/scripts/upscale.py` | 已实现 |
| E3 | 字幕 | `stages/subtitle/scripts/subtitle.py`（含 `--from-srt auto`） | 已实现 |
| E4 | BGM | `stages/production/scripts/bgm.py` | 已实现 |
| E5 | 剪映工程 | `edit_draft.py`（`pyJianYingDraft==0.3.1`） | 已实现（双轨，MP4 仍是唯一发布版） |
| E6 | 发布版导出 | `release_export.py --all --apply` | 已实现（唯一出口） |
| E7 | 发行资料检查 | `release_check.py` | 已实现（`verdict ∈ ok/ready_for_export/blocked`） |
| E8 | 版权资料 | `copyright_kit.py`（三入口 A/B/C） | 已实现 |
| E9 | 画面合规 | `compliance_precheck.py` `compliance_media_check.py` | 已实现 |
| E10 | 封面 | — | 引擎侧**已移除**（`cover_prompt.py`/`cover_forge.py` 不在仓库），仅剩 `cover_prompts.json` 数据文件与校验 |
| E11 | 交付规格 | `delivery_spec.py`（1080×1920） | 已实现 |

## 6. Studio 控制层

| # | 功能 | 入口 | 状态 |
|---|---|---|---|
| F1 | 工作区登记/发现/切换 | `/api/workspaces*`（6 端点） | 已实现 |
| F2 | 作业队列 / 取消 / SSE 流 | `/api/jobs*` `/api/events/stream` | 已实现 |
| F3 | 审计日志 | `GET /api/audit` | 已实现 |
| F4 | 环境体检 / 一键修复 | `/api/health/*` + `tools/env_check.py` | 已实现 |
| F5 | GPU 锁 | `stages/production/scripts/_lock.py`、`/api/locks` | 已实现 |
| F6 | 资源监视（显存/内存/磁盘） | `/api/monitor` + `web/core/monitor.py` + `web/ui/studio/js/monitor.js` | 已实现 |
| F7 | 只读模式 | `SOLODRAMA_CONSOLE_READONLY` | 已实现，**后端强制**（见下） |
| F8 | 旧控制台 | `/ui/`（`index.html`+`app.js`+`home.js`+`advanced.html`） | 保留（历史入口） |
| F9 | 系统下载/更新 | `/api/system/{download,update}` | 已实现 |

### 只读模式的真实强度（实测代码）

```python
# web/app.py:82
READONLY_MODE = os.environ.get("SOLODRAMA_CONSOLE_READONLY", "") not in ("", "0", "false")

# web/app.py:597  —— 命令通道统一拦截
if READONLY_MODE and cmd.danger > CMD.READ:
    raise HTTPException(status_code=423, detail="控制台处于只读模式…")

# web/app.py:1017/1079/1088/1621  —— 写配置类端点逐个拦截
```

结论：只读**不是隐藏按钮**，是后端 423。2.0 新增的每个写端点都必须过这道闸（漏一个就是安全洞）。

## 7. 功能缺口汇总（2.0 要补的，不是要重写的）

| 缺口 | 性质 | 归属阶段 |
|---|---|---|
| 浅色主题 | 完全缺失 | Phase 1 |
| 五工作空间 IA | 现为 15 项平铺导航 | Phase 2 |
| 六段式提示词结构化读写 | 只有只读整串 + 无写接口 | Phase 3 |
| 单镜即时校验 API | 现在只能整包批处理 | Phase 3 |
| 首页真实数据看板 | `workbench` 现有，但无「当前阶段/通道/成本」整合视图 | Phase 2 |
| 发行/版权资料界面 | `release.js`(235 行) 只覆盖部分 | Phase 5 |
| 设计规范文档 | `docs/design/` 不存在 | Phase 1 |

**不存在「需要重写引擎」的缺口** —— 这是本次升级最重要的判断。
