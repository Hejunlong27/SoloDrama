# SoloDrama 3.0 AI 短剧生产引擎设计

- 版本：3.0
- 日期：2026-11-27
- 状态：第一阶段已实现并通过本地构建与真实 FFmpeg 链路验收

## 1. 设计目标

SoloDrama 3.0 在现有 Workbench、Task Runtime、Provider、Cloud Hub、Workflow Library 上增加短剧生产领域层，形成：

```text
故事创意 → 剧本理解 → 角色/场景资产 → 分镜 → Take → 声音 → 时间轴 → 成片
```

不改变旧画布文件格式，不替换已有 Provider 与任务 Runtime。

## 2. 分层

```text
表现层
  productionPanel.vue
  Workbench / Canvas / Document

API 层
  /api/production/*

领域编排层
  production/store.ts
  production/ai.ts
  production/pipeline.ts
  production/export.ts

领域模型
  @solodrama/production/schema.ts

既有基础设施
  AI / Provider / ComfyUI / Cloud Hub / Task Runtime / FFmpeg / File
```

## 3. 持久化

领域文档：

```text
<project>/.solodrama/production.json
```

特性：

- `schemaVersion = 1`
- 文档稳定 UUID
- `revision` 乐观并发控制
- 最多 20 个完整历史快照
- 原子写入和文件锁
- 路径校验与符号链接拒绝
- AI 来源、输入哈希、Provider、Model、原始响应
- 用户确认状态

旧项目不迁移画布内容；首次读取时创建空 Production 文档，因此不会破坏旧项目。

## 4. 核心数据模型

### 4.1 ProductionDocument

```ts
{
  schemaVersion: 1;
  revision: number;
  id: uuid;
  name: string;
  storyIdea: string;
  synopsis: string;
  world: string;
  characters: ProductionCharacter[];
  locations: ProductionLocation[];
  props: ProductionProp[];
  storyTimeline: StoryEvent[];
  continuityWarnings: string[];
  episodes: ProductionEpisode[];
  assets: ProductionAsset[];
  generationJobs: ProductionGenerationJob[];
  timeline: ProductionTimelineItem[];
  output: OutputSpec;
  sources: ProductionSource[];
  revisions: RevisionSnapshot[];
  confirmedSections: Record<string, boolean>;
}
```

### 4.2 Episode → Scene → Shot

- Episode：分集标题、简介、剧本、确认状态。
- Scene：集内场次、地点、人物、道具、镜头数组。
- Shot：景别、角度、运镜、动作、位置、表情、对白、环境音、首尾帧要求、视频提示词。
- 每个 Shot 包含多个 Take 和一个 `selectedTakeId`。

### 4.3 Character / Location / Prop

Character：

- 基础档案、外貌、性格、年龄。
- `visualProfile`：face、hair、body、style。
- `clothingVersions[]`。
- `referenceImages[]`，每张参考图可独立确认。
- `voice`：Provider、voiceId、speed、language。
- `relationships[]` 使用目标角色 UUID。

Location：

- 空间结构、光线、色彩、时间、氛围。
- 参考图集合。
- 关联道具。

Prop：

- 描述和参考图。
- 被 Shot 通过 `propIds[]` 引用。

### 4.4 Take

Take 记录：

- `shotId`、Take 序号。
- `taskId`。
- Provider、Model、Instance、Workflow ID/Version。
- 正向/反向提示词。
- 参考 Asset IDs。
- Seed 和完整请求参数。
- 输出 Asset ID。
- 创建、开始、完成时间与耗时。
- 状态、失败原因。
- 是否被用户选为正式版本。

### 4.5 Asset Version

ProductionAsset 包含：

- 稳定 UUID。
- 类型、工作区相对路径、MIME。
- `sourceTaskId`、Provider、Model、Instance、Workflow。
- `version`、`previousAssetId`。
- `confirmed`。
- 追加式来源元数据。

生成只新增 Asset，不覆盖已确认标准图。

### 4.6 Timeline

Timeline Item 支持：

- `video`、`audio`、`subtitle`、`music`、`sfx`。
- 镜头、Take、Asset 关联。
- 开始时间、持续时间、轨道、音量。
- `cut`、`fade`。

## 5. 剧本理解

入口：

- `understandScript()`
- `POST /api/production/ai/understand`
- `POST /api/production/ai/apply`

处理：

1. Zod 校验输入长度与类型。
2. 超过 50,000 字符按段落分段。
3. 每段输出结构化 JSON。
4. 汇总时二次去重人物、地点、道具、时间线与场景。
5. 对未建档角色引用生成连续性警告。
6. 应用时按名称/编号复用现有稳定 ID。
7. 已确认 section 或实体默认跳过，显式 `force` 才覆盖。
8. 写入输入 SHA-256、Provider、Model、原始响应。

## 6. 视觉资产与参考图注入

`startProductionGeneration()` 根据目标类型组装 Prompt 和参考图：

- Shot：角色参考图 + 场景参考图 + 道具参考图 + 分镜图。
- CharacterReference：Visual Profile 与角色档案。
- LocationReference：空间、光线、色彩、时间和氛围。
- PropReference：道具描述。
- Voice：镜头对白和角色音色配置。

所有图片都进入统一 `MediaGenerationRequest.images`；视频首尾帧进入 `firstFrame/lastFrame`。能力是否支持仍由现有 Provider/Workflow 判断。

## 7. Take 生成与恢复

调用链：

```text
startProductionGeneration()
  → 创建 Take / GenerationJob
  → mediaTasks.start()
  → 生成完成
  → syncProductionGeneration()
  → mediaTasks.status()
  → 创建 ProductionAsset
  → Take.status = completed
  → 用户 selectProductionTake()
```

服务重启：

- Production 文档中的 taskId 保留。
- 媒体任务记录保留。
- `/generation/status` 使用 `resume=true` 恢复可恢复任务。
- 没有任务记录的 Take 标记失败，不会伪装成功。

## 8. 声音

- 对白可由镜头 `dialogue` 自动生成音频任务。
- 角色 `voice` 字段决定 voiceId、speed、language。
- 配音完成后写入：
  - `audio` 对白轨。
  - `subtitle` 字幕轨。
- 背景音乐和音效使用音频任务并自动加入时间轴。
- 页面仍可人工编辑时间、时长、轨道、音量和字幕文本。

## 9. 成片导出

`exportProduction()`：

1. 读取每个 Shot 的 `selectedTakeId`。
2. 校验输出路径和工作区边界。
3. 拒绝覆盖已有成片。
4. 对每段视频执行：
   - `scale`
   - `pad`
   - `fps`
   - `setsar=1`
   - `tpad` 补齐短素材
   - `trim` 到镜头时长
   - `fade`（非硬切）
5. `concat` 视频。
6. 创建静音底轨并 `amix` 全部音频。
7. H.264 + AAC 输出。
8. 写入 ProductionAsset，记录来源 Shot、Take 和 Asset IDs。

## 10. API

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/api/production/get` | 读取领域文档 |
| PUT | `/api/production/save` | CAS 保存 |
| POST | `/api/production/ai/understand` | 结构化剧本理解 |
| POST | `/api/production/ai/apply` | 应用 AI 结果 |
| POST | `/api/production/generation/start` | 创建 Take/素材任务 |
| POST | `/api/production/generation/status` | 同步/恢复任务 |
| POST | `/api/production/generation/cancel` | 精确取消 |
| POST | `/api/production/take/select` | 选择正式 Take |
| POST | `/api/production/asset/reference` | 关联确认参考图 |
| POST | `/api/production/entity/confirm` | 确认实体/段落 |
| GET | `/api/production/impact` | 查询受影响镜头 |
| GET | `/api/production/canvas/sources` | 扫描并返回旧画布来源 |
| POST | `/api/production/canvas/import` | 显式导入画布来源并建立映射 |
| POST | `/api/production/timeline/export` | 导出成片 |

## 11. 安全边界

- `assertAppRequest` 保护控制接口。
- `resolveWorkspace` 和 `resolveWorkspacePath` 限制工作区路径。
- 素材必须是普通文件，拒绝符号链接。
- 领域文档最大 20 MiB。
- 媒体请求沿用现有 Schema 与 Provider 校验。
- 输出不覆盖已有文件。
- 多租户媒体任务继续沿用 owner、模型路由与扣费预占。
- 不在此阶段新增删除型迁移。

## 12. 统一工作台

原“工作台”和“制作”融合为一个入口：

```text
画布 | 工作台 | 文档
```

工作台内部阶段：

```text
总览 → 剧本理解 → 角色与场景 → 分镜与 Take → 声音与成片 → 画布来源
```

数据职责：

- Production 领域文档负责正式集、场、镜、角色、场景、道具、Take、确认状态和时间轴。
- 画布继续负责自由节点创作、节点实现和节点输出。
- `canvasBindings` 只记录来源关系，不把节点 ID 当作业务主 ID。
- 旧节点通过“画布来源”显式导入，不能自动覆盖已确认内容。
- 原文、图片、视频和音频节点分别映射为 Episode、角色/场景/道具、Shot Take 和 Asset。

重构顺序：

1. 合并底部入口。
2. 增加统一总览。
3. 增加画布来源扫描和持久映射。
4. 抽取总览与画布来源组件。
5. 停止导入旧 `workbenchPanel.vue`；旧逻辑仅作为过渡参考，不再拥有独立入口。

## 13. 兼容性

- 不改 `solodramaCanvas` 文件。
- 不改已有媒体任务 JSON 格式。
- 不新增第二套任务状态机。
- 旧项目首次进入制作页时创建空领域文档。
- 新增字段均有默认值，可读取较早的 Production 文档。
- 画布、工作台和文档继续工作；Agent 对旧 `workbench` 和 `production` 面板名保持兼容映射。

## 14. 制作工作台交互升级

- 顶部提供返回项目、返回总览、全局画风和保存入口。
- AI 对话使用常驻可拖动宠物入口；宠物只负责打开/收起现有 Agent，不复制对话系统。
- 角色、场景和道具采用总览卡片 + 独立设计器，角色形象使用统一视觉描述，音色配置独立分组。
- 全局画风复用现有 `styleLibrary` 与 `.solodrama/project.json`。
- Shot Designer 使用参考角色、场景、道具、通用/H3 提示词和辅助图三栏结构。
- 辅助图类型包括 `storyboard`、`shotImage`、`blocking`，结果分别写入 `storyboardAssetId`、`shotImageAssetId`、`blockingAssetId`，是否作为视频参考由 `generationOptions` 控制。
- 尾帧续画从上一正式视频 Take 提取尾帧，生成新的 Production Asset，并写入当前 Take 的首帧和 `continuationSourceShotId`/`continuationTakeId`。
