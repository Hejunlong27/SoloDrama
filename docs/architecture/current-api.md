# 当前 API（122 端点，按域归档）

> 来源：`grep -cE '@app\.(get|post|put|delete|websocket)' web/app.py` → **122**（新增模型参数校验与媒体任务状态接口）。
> 只列真实端点；标 † 的为危险写操作（受 `CMD.danger > CMD.READ` + 只读闸约束）。

## 1. 健康与运行时

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/health` | 服务健康 + 解释器 + GPU 锁摘要 |
| GET | `/api/health/checks` | 环境体检查项（`tools/env_check.py`） |
| POST† | `/api/health/fix` | 一键修复 |
| GET | `/api/health/fixes` | 修复历史 |
| GET | `/api/monitor` | 显存/内存/磁盘采样 |
| GET | `/api/locks` | GPU 资源令牌 |

## 2. 工作区与项目

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/workspaces` | 已登记工作区 |
| GET | `/api/workspaces/discover` | 扫本机常见目录（不改文件） |
| POST† | `/api/workspaces` | 登记已有目录 |
| POST† | `/api/projects/create` | 新建剧项目（`init_project.py`） |
| POST | `/api/workspaces/current` | 切换当前项目 |
| POST† | `/api/workspaces/prune` | 清理失效登记（只删登记，不删文件） |

## 3. Studio 只读聚合（页面主力数据源）

| 方法 | 路径 | 返回要点 |
|---|---|---|
| GET | `/api/studio/capabilities` | 能力清单 + `readonly` |
| GET | `/api/studio/overview` | 项目元信息 + 流程 + 九项 + 双门禁 + 计数 + 花费 |
| GET | `/api/studio/workflow` | 13 节点状态（`nodes.py`） |
| GET | `/api/studio/setup` | 项目前置检查 |
| GET | `/api/studio/shots?ep=` | 单集镜头三态（图/提示词/视频） |
| GET | `/api/studio/episodes` | 逐集：`total/ok/fail/pending/state/master/upscaled/mix/subbed/ass/draft/release` |
| GET | `/api/studio/prompt?shot=&ep=` | 单镜提示词 + 六段解析 + lint。`ep` 不给且该镜跨集存在时返回 `ambiguous` + 候选 |
| POST | `/api/studio/prompt` | 写回单镜提示词（引擎侧备份 + 原子替换 + 复检；`blocked_by_lint` 时 rc=3 不落盘） |
| GET | `/api/studio/cost` | 项目耗时与平台花费；LLM 用量另由 `/api/llm/usage` 汇入成本页展示 |
| GET | `/api/studio/cover?ws=` | 首页海报用的一张代表性图（只读，60s 缓存；取不到返回 `ok=false`） |
| GET | `/api/studio/image-channel?ws=` | 资产出图的通道判定（只读）：`spec`/`paid`/`url`/`fake_cloud`/`backup`，真源 `model-plan.json` |
| GET | `/api/studio/release` | 发行资料齐全度 `verdict ∈ ok/ready_for_export/blocked` |
| GET | `/api/studio/release/export-preview` | 导出发行版**干跑** |
| GET | `/api/studio/env` | `env_check.py` 结构化输出 |
| GET | `/api/studio/asset-md` | 资产 Markdown |
| GET | `/api/studio/media-info?rel=` | 文件可否播放（避免 404 试探） |
| POST | `/api/studio/refresh` | 清服务端缓存 |

## 4. 作业与事件

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/jobs` `/api/jobs/{id}` | 作业列表/详情 |
| POST | `/api/jobs/{id}/cancel` | 取消 |
| GET | `/api/jobs/{id}/stream` `/api/events/stream` | SSE 流 |
| GET | `/api/tasks` `/api/tasks/{id}` | 旧任务视图（与 jobs 并存） |
| POST† | `/api/run` | **通用命令通道**，按 `CMD.danger` 判定 |
| GET | `/api/commands` | 命令表（UI 按钮的来源） |
| GET | `/api/audit` | 审计日志 |

## 5. 生成通道

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/connections` | 三通道状态（密钥只回指纹） |
| POST† | `/api/connections/{kind}` | 保存连接 |
| POST | `/api/connections/{kind}/test` | 连接测试（0 费用） |
| GET | `/api/comfy/status` | ComfyUI 状态 |
| POST† | `/api/comfy/{start,stop,interrupt,free}` | 启停/打断/放显存 |
| GET | `/api/comfy/workflows` 等 5 个 | 工作流列表/详情/当前 |
| POST† | `/api/comfy/workflows` `/{id}/params` `/{id}/map` `/{id}/duplicate` `/{id}/restore` | 参数与映射编辑 |
| POST | `/api/comfy/workflows/{id}/validate` | 校验（只读） |
| GET | `/api/comfy/workflows/{id}/backups` | 备份列表 |
| POST† | `/api/generators/rh` | 设 RunningHub 工作流 |
| GET | `/api/generators` | 生成通道状态 + `model_catalog` + `board_channel`（本地/云端/ZZAI/RunningHub 分镜图下游） |
| POST | `/api/generators/model-params` | 只读校验模型参数并返回平台请求映射；不提交任务、不产生费用 |
| GET | `/api/media/tasks?ws=` | 媒体任务列表；支持 `kind/status/limit`，记录远端 task ID、报价、供应商暂报 `usage` 与后台最终 `settled_cost` |
| GET | `/api/media/tasks/{id}?ws=` | 单条媒体任务详情 |
| GET | `/api/media/tasks/{id}/resume?ws=` | 断点恢复信息：是否需轮询、是否允许重新提交、成本是否已结算 |
| GET | `/api/scheduler/status?ws=&ep=&limit=` | 13 节点只读状态、下一步、journal、工作区锁 |
| POST† | `/api/scheduler/run` | 入队受控 Runner；默认干跑，`apply` 真跑需确认，`yes` 另需 GPU/计费确认 |
| GET | `/api/pipeline/plan` | 旧版环节计划（兼容保留；Studio 调度页已改用 `/api/scheduler/status`） |
| POST† | `/api/pipeline/run` | 旧版环节执行（兼容保留） |

## 6. 创作与 LLM

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/create/state` `/api/create/read` | 创作链状态与读文档 |
| POST† | `/api/create/{idea,write,generate}` | 生成灵感/写文件/生成正文 |
| GET | `/api/skills` `/installed` `/prompt` `/presets` `/api/skills/{sid}` | 题材模板 |
| POST† | `/api/skills/{upload,install,uninstall}` | 装/卸模板 |
| GET | `/api/llm/meta` `/providers` `/purposes` `/templates` `/usage` | 网关元信息；`providers` 返回 provider health，`purposes` 返回 `routes/fallback_count`，`usage` 支持 `purpose/provider/project` 过滤并区分已知/未知金额 |
| POST† | `/api/llm/purposes/{pid}` | 绑定主路由或 `routes[]` 主备链；保存前校验 provider/model 与能力 |
| POST† | `/api/llm/providers` | 供应商配置 |
| POST | `/api/llm/{preview,complete}` `/{pid}/test` | 预览/补全/测试 |

## 7. 图解与画布

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/canvas/series` | 镜号×集号格子状态（只读） |
| GET | `/api/canvas/shot` | 单格四段链 |
| POST† | `/api/canvas/shot` | 编辑单格 |
| GET | `/api/graph` | 剧集关系图 |
| POST† | `/api/graph/{layout,reset,edge}` | 布局/重置/连线 |

## 8. 文件与静态

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/file` | 读工作区文件（受限白名单） |
| GET | `/api/artifacts` `/api/artifacts/loose` | 产物索引 |
| GET | `/media` | 媒体流（Range） |
| GET | `/api/styles` | 画风库 |
| GET | `/api/time/global` | 全局耗时 |
| GET | `/api/glossary` `/api/home` `/api/episodes` `/api/overview` `/api/pipeline` `/api/gates` | 旧控制台数据 |
| POST | `/api/help` `/api/agent/chat` | 助手；`/api/agent/chat` 必须带 `confirm=true`，一次请求最多执行 12 步模型调用 |
| GET | `/api/system/status`、POST† `/api/system/{download,update}` | 系统维护 |
| GET | `/` | 跳 `/studio/` |

## 9. UI 契约纪律

1. UI **只用已有端点**。要新数据先问「能否由已有端点组合得出」，能就不加端点。
2. 新增写端点必须过只读闸（`READONLY_MODE` → 423），并在 `docs/architecture/current-api.md` 登记。
3. `verdict` 类字段是**门禁结论**，不是错误码：`blocked` 时 `rc=2` 是正常的，页面不得显示为「接口故障」。
