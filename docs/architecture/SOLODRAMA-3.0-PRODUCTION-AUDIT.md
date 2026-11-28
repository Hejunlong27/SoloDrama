# SoloDrama 3.0 现有生产能力审计

- 审计日期：2026-11-27
- 审计范围：Project、Episode、Scene、Shot、Character、Location、Prop、Asset、Take、Workflow Definition、Task Runtime、Workbench UI
- 审计原则：以当前仓库实际代码为依据；不重复建设已有 Provider、Cloud Hub、Task Runtime、Workflow Library 和 FFmpeg 能力。

## 1. 结论摘要

SoloDrama 2.x 已具备较完整的底层生产能力，但没有正式的短剧制作领域模型：

- 已有画布、节点、文档、素材、Workflow、多 Provider 和持久媒体任务。
- 缺少跨节点、跨画布稳定存在的 Episode / Scene / Shot / Character / Location / Prop / Take 数据。
- Workbench 仍以画布节点和节点字段为事实来源，不能直接回答“某个角色改了会影响哪些镜头”。
- 媒体任务已经具备持久化、幂等 taskId、断线恢复和精确取消，必须复用，不能为 3.0 新建第二套任务系统。
- FFmpeg、TTS、Cloud Hub、Workflow Library 均已有基础能力，3.0 只需补生产领域编排与追踪。

3.0 采用“新增领域层、保留旧画布层”的兼容方案：项目内新增 `.solodrama/production.json`，旧画布、旧项目、旧工作流原样保留。

## 2. 已有能力

### 2.1 Project 与工作区

现有代码：

- `apps/web/src/stores/workspace.ts`
  - `Project`：`directory`、`name`、`lastOpenedAt`
  - `useWorkspaceStore().openProject()`
  - `addProject()`、`renameProject()`
- `apps/server/src/utils/workspace/index.ts`
  - `resolveWorkspace(req, path)`：工作区绝对路径授权、realpath、目录校验。
- `apps/server/src/utils/workspace/files.ts`
  - `resolveWorkspacePath()`
  - `lockWorkspaceFiles()`
  - `writeWorkspaceFile()`
- `apps/web/src/lib/workspaceFiles.ts`
  - 前端统一工作区文件入口 `useWorkspaceFiles()`。

已有结论：

- 项目以本地目录为边界，已有路径逃逸、符号链接和文件锁保护。
- 适合作为 3.0 领域文档的存储根目录。
- 缺少正式项目实体 ID；3.0 在 `.solodrama/production.json` 中生成稳定项目 UUID。

### 2.2 画布与 Workbench

现有代码：

- `apps/web/src/pages/workspace/index.vue`
  - 画布、工作台、文档三个面板。
- `apps/web/src/pages/workspace/panels/canvas/index.vue`
  - 画布 `solodramaCanvas` 文件格式。
- `apps/web/src/pages/workspace/panels/workbench/workbenchPanel.vue`
  - 从画布节点读取和操作内容。
- `apps/web/src/pages/workspace/canvasFile.ts`
  - 画布文件识别。

已有结论：

- Workbench 是节点视图，不是 Short Drama 领域模型。
- 节点数据适合执行单个生成动作，不适合承担集、场、镜头、Take 的长期关系与确认状态。
- 3.0 新增“制作”面板，不替换画布；旧项目仍可正常打开。

### 2.3 媒体 Provider、Cloud Hub 与 Workflow

现有代码：

- `packages/providers/index.ts`
- `packages/providers/src/media/solodramaComfy.ts`
- `packages/providers/src/media/solodramaComfyCloud.ts`
- `packages/providers/src/media/solodramaRunningHub.ts`
- `packages/providers/src/media/solodramaRunningHubClosed.ts`
- `apps/server/src/utils/comfyHub/`
- `apps/server/src/routes/comfyHub/`
- `apps/server/src/utils/media/provider.ts`
- `apps/web/src/lib/comfyWorkflow.ts`

已有结论：

- Provider 已统一媒体生成接口，Workflow 和实例调度已有 Cloud Hub。
- 不同 Workflow 输入能力由 Provider/Workflow 规则决定，3.0 不能在领域层假定所有工作流支持首帧、尾帧或参考图。
- 3.0 将参考素材注入统一的 `MediaGenerationRequest`，最终是否支持由现有 Provider 适配器继续判断。

### 2.4 Task Runtime

现有代码：

- `apps/server/src/utils/media/tasks.ts`
  - `start(cwd, taskId, mediaType, request, attachment, owner)`
  - `status(cwd, taskIds, resume, owner)`
  - `cancel(cwd, taskIds, owner)`
  - `wait(cwd, taskId, owner, signal)`
- `apps/server/src/utils/media/generation.ts`
  - `generateMedia()`
  - `MediaGenerationCheckpoint`
- `apps/server/src/routes/ai/media/generate.ts`
- `apps/server/src/routes/ai/media/tasks/status.ts`
- `apps/server/src/routes/ai/media/tasks/cancel.ts`

已有能力：

- UUID taskId 幂等。
- 任务 JSON 持久化、参考媒体 blob 校验、断线恢复。
- 提交结果未知时不会盲目重提。
- 精确取消单个或多个 taskId。
- 服务重启后可读取持久任务并恢复。
- 多租户模型路由与扣费预占。
- 最多 1000 个活动任务。

3.0 结论：

- 直接复用 `mediaTasks.start/status/cancel`。
- Take 和参考素材任务只保存 taskId，不复制任务状态机。
- Launcher 或页面退出不等于取消云端任务。

### 2.5 FFmpeg、TTS 与既有生产流水线

现有代码：

- `apps/server/src/utils/ffmpeg/index.ts`
  - `prepareWorkspaceFfmpeg()`
  - `executeWorkspaceFfmpeg()`
- `packages/ffmpeg/`
- `packages/tools/localTts/`
- `docs/promptSkillsAndTts.md`

已有结论：

- FFmpeg 已能在工作区安全执行并上报流式事件。
- TTS 已通过现有工具/Provider 体系存在。
- 3.0 不重建编码器或 TTS 框架，只增加时间轴、音频任务和成片来源记录。
## 3. 缺失能力

### 3.1 领域实体

审计时不存在正式的：

- Episode：分集。
- Scene：场次。
- Shot：可执行镜头。
- Character：稳定角色实体。
- Location：稳定场景实体。
- Prop：稳定道具实体。
- Take：同一镜头下可比较的生成版本。
- Production Asset：带来源 Task、Take、Workflow 版本和确认状态的素材。

因此无法可靠实现：

- 角色或场景修改后的受影响镜头查询。
- 镜头合并、拆分、排序后保持稳定 ID。
- 同一镜头保留多个 Take 并选择正式版本。
- 确认内容保护。
- 成片素材版本追踪。

### 3.2 剧本理解

- 没有严格的剧本理解 Schema。
- 没有长文本分段、跨段人物去重和连续性提示。
- 没有 AI 来源哈希、Provider、Model 和原始响应记录。
- 没有按段落确认和按部分重新生成。

### 3.3 视觉资产

- 没有 Character Visual Profile 和 Location Visual Profile。
- 没有角色服装版本。
- 没有参考图集合和确认标准图。
- 没有角色/场景/道具到镜头的反向影响查询。

### 3.4 Take 与生成管线

- 媒体任务能生成文件，但业务层不知道“属于哪个镜头、第几个 Take、是否首选”。
- 没有首帧、尾帧、分镜图、图片、图生视频的统一 Shot Generation Pipeline。
- 没有把角色、场景、道具参考图自动映射到请求。
- 没有 Take 选择和正式版本记录。

### 3.5 声音与时间轴

- 有 TTS 能力，但没有对白轨、字幕轨、音乐轨、音效轨的统一时间轴。
- 没有镜头对白到音频任务和字幕的自动关联。
- 没有带音频混合的成片导出来源清单。

### 3.6 Workbench UI

- 画布节点缺少集、场、镜头树和镜头级编辑体验。
- 节点工作台无法表达“未确认/已确认”“多个 Take”“正式 Take”。
- 缺少剧本理解预览、应用、确认保护的可视化入口。

## 4. 数据模型问题

1. 画布节点 ID 是画布内执行标识，不应被当成跨版本的镜头业务 ID。
2. 节点字段是生成参数，无法表达实体关系：一个角色可出现在多集、多场、多镜。
3. 当前素材记录偏文件级，缺少 `sourceTaskId`、`workflowVersion`、`instanceId`、`takeId` 的业务链路。
4. 若直接修改已确认节点参数，没有统一 CAS、快照和确认状态。
5. 没有通过确认状态阻止 AI 结果覆盖人工资产的机制。
6. 多任务状态若复制到业务表，容易与任务 Runtime 的真实状态不一致。

## 5. UI/UX 问题

- 用户无法从故事大纲直接看到“集 → 场 → 镜”的生产结构。
- 生成结果以节点输出为主，无法横向比较同一镜头的多个 Take。
- 没有正式 Take 标记，剪辑时无法明确哪些素材可以进入成片。
- 没有连续性提示、确认状态和受影响镜头提示。
- 没有可见的时间轴和导出参数。

## 6. 必须复用的模块

| 能力 | 复用模块 |
| --- | --- |
| Provider 与模型目录 | `packages/providers`、`apps/server/src/utils/media/provider.ts` |
| ComfyUI/Cloud Hub | `apps/server/src/utils/comfyHub`、`apps/server/src/routes/comfyHub` |
| 任务持久化/恢复/取消 | `apps/server/src/utils/media/tasks.ts` |
| 媒体输出落盘 | `apps/server/src/utils/media/generation.ts` |
| 文本模型 | `apps/server/src/utils/ai/index.ts` 的 `getConfiguredModel()`、`streamAi()` |
| 文件安全与原子写 | `packages/file`、`apps/server/src/utils/workspace/files.ts` |
| FFmpeg | `apps/server/src/utils/ffmpeg/index.ts`、`packages/ffmpeg` |
| TTS/工具 | 现有 Provider、`packages/tools/localTts` |
| 前端请求 | `apps/web/src/lib/http.ts` |
| 工作区文件 | `apps/web/src/lib/workspaceFiles.ts` |

## 7. 3.0 新增模块

```text
packages/production/
  schema.ts                 # 领域 Schema 与稳定 ID
  index.ts

apps/server/src/utils/production/
  store.ts                  # 懒初始化、CAS、快照、AI 应用
  ai.ts                     # 长文本剧本理解、JSON 修复、连续性检查
  pipeline.ts               # Take/参考素材任务、状态同步、确认与影响查询
  export.ts                 # 时间轴 FFmpeg 成片导出

apps/server/src/routes/production/
  get.ts
  save.ts
  ai/understand.ts
  ai/apply.ts
  generation/start.ts
  generation/status.ts
  generation/cancel.ts
  take/select.ts
  asset/reference.ts
  entity/confirm.ts
  impact.ts
  timeline/export.ts

apps/web/src/pages/workspace/panels/production/
  productionPanel.vue
```

## 8. 数据迁移要求

- 不修改旧画布 JSON。
- 不删除旧节点、旧素材或旧项目文件。
- 首次打开项目时按需创建 `.solodrama/production.json`。
- 新文档 `schemaVersion` 固定为 `1`，新增字段均有 Zod 默认值，后续可兼容扩展。
- 已确认内容、已选 Take 和正式素材不能被 AI 自动覆盖。
- 旧项目没有领域文档时，以空文档开始；用户可继续使用原画布，也可在“制作”面板建立新生产结构。
- 每次保存递增 `revision`，保留最多 20 个完整快照；旧版领域文档在字段有默认值时可读取。
- 所有素材路径必须是当前工作区相对路径，禁止绝对路径、`..`、符号链接和目录逃逸。

## 9. 调用链

### 9.1 剧本理解与应用

```text
productionPanel.vue
  → POST /api/production/ai/understand
  → understandScript()
  → getConfiguredModel() + streamAi()
  → scriptUnderstandingSchema.parse()
  → POST /api/production/ai/apply
  → applyUnderstanding()
  → loadProduction()
  → 按名称复用实体，按编号复用集/场/镜
  → confirmed 检查
  → saveProduction()
  → .solodrama/production.json
```

### 9.2 Take 生成

```text
productionPanel.vue
  → POST /api/production/generation/start
  → startProductionGeneration()
  → 组装参考图和 MediaGenerationRequest
  → 创建 Take/GenerationJob（状态 generating）
  → mediaTasks.start()
  → 现有 Provider/Workflow/Cloud Hub
  → POST /api/production/generation/status
  → mediaTasks.status()
  → 写入 ProductionAsset
  → Take 完成，等待人工选择
```

### 9.3 成片导出

```text
productionPanel.vue
  → POST /api/production/timeline/export
  → exportProduction()
  → 读取 selectedTakeId
  → 校验全部素材路径
  → prepareWorkspaceFfmpeg()
  → FFmpeg scale/pad/fps/tpad/trim/concat + 音频 amix
  → 输出新视频文件
  → 追加 ProductionAsset 并记录镜头/Take/素材来源
```

## 10. 审计结论

3.0 不应重写 Provider、Cloud Hub、Task Runtime 或 Workflow Library。正确路径是：

1. 增加独立 Production 领域文档。
2. 以现有 taskId 作为 Take 与任务 Runtime 的唯一桥接。
3. 以稳定 UUID 建立集、场、镜、角色、场景、道具和资产关系。
4. 以确认状态和 Take 选择保护人工决策。
5. 以现有 FFmpeg 完成可播放成片，而不是只做静态剪辑页面。