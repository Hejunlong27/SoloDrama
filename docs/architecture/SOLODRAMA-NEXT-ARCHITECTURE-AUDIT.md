# SoloDrama 下一阶段架构审计

> 审计日期：2026-11-26  
> 审计范围：`packages/providers`、媒体任务、ComfyUI、RunningHub、工作台、工作区、多租户、当前验证体系。  
> 本报告只记录仓库中实际读取到的实现；未运行的测试不会标记为通过。

> 实施状态：Milestone 1 与 Milestone 2 已在审计后落地，见同目录阶段性报告；本审计中的问题表保留为整改前基线。

## 1. 结论摘要

SoloDrama 已经具备可复用的基础能力，不需要推倒重写：

- `ProviderDefinition`、`resumeTask`、`saveTaskData` 已经定义了“供应商负责上游通信，宿主负责持久化与恢复”的基本边界。
- `apps/server/src/utils/media/tasks.ts` 已经实现任务 UUID、同一任务串行锁、原子 JSON 落盘、Provider 恢复数据、输出文件哈希校验和取消状态落盘。
- `apps/server/src/utils/media/generation.ts` 已经实现参考素材读取、结果下载、MIME 检测、文件写入、任务恢复和扣费后处理。
- 多租户已经具备 SQLite/MySQL Drizzle 数据层、账号/会话、按用户隔离的工作区根目录、用户设置版本控制和媒体任务 `ownerUserId` 校验。
- 工作台已经复用工作区文件和画布数据，不应另建一套完全独立的前端。

但当前存在必须先修复的运行时与稳定性断点：

1. Provider 运行 VM 没有注入 `FormData`、`crypto` 等 Web 全局对象，ComfyUI 上传/提交、RunningHub 上传和部分媒体 Provider 会在真实调用时直接失败。
2. ComfyUI 上传固定 `overwrite: true`，任务素材可能互相覆盖。
3. ComfyUI 取消会在删除排队任务后无条件发送无 `prompt_id` 的 `/interrupt`，可能中断同一实例上的其他任务。
4. Provider 错误目前主要靠散落的普通 `Error`/`status` 表示，没有统一错误码、可重试语义和稳定的前端分类。
5. 媒体任务虽然能恢复，但“已开始提交、上游响应丢失”没有独立状态；任务无法在进程崩溃后区分“尚未提交”和“提交结果未知”。
6. 工作台仍由画布节点类型、标签关键词和连边推导业务实体，没有 Episode/Scene/Shot/Character/Take 的稳定领域 ID。
7. 多租户目前是“用户 + 工作区目录 + 任务 owner”隔离，不是完整租户/项目关系模型；数据库中尚无项目、剧集、镜头、Take、任务运行记录表。
8. 仓库没有自动化测试入口；根 `AGENTS.md` 又明确禁止新增测试模块、测试脚本和测试框架。因此后续只能使用现有类型检查、构建和显式手工验证，不能伪造“自动化测试通过”。

## 2. 当前技术栈与仓库结构

- 包管理：Bun 1.4.3 Workspaces。
- 前端：Vue 3、Vite、TypeScript、Pinia、Element Plus、Vue Flow。
- 后端：Bun、Express 5、Zod、Undici。
- 桌面：Electron/Electrobun。
- 多租户持久化：Drizzle ORM，SQLite 默认，MySQL 8.0 适配。
- Provider：自定义 TypeScript 文件保存到 `data/providers/`，由 Babel 解析元数据、Bun Transpiler 转译、Node `vm.SourceTextModule` 执行。

关键目录：

```text
packages/providers/
  types.d.ts                         Provider 公共协议
  index.ts                           内置语言/媒体 Provider 清单
  src/media/solodramaComfy.ts        本地/局域网 ComfyUI
  src/media/solodramaComfyCloud.ts   云端 ComfyUI
  src/media/solodramaRunningHub.ts   RunningHub AI App
  src/media/solodramaRunningHubClosed.ts RunningHub 闭源模型

apps/server/src/utils/media/
  provider.ts                        Provider 解析、安装、VM 加载、宿主 fetch 注入
  generation.ts                      请求准备、提交、结果下载、落盘、恢复
  tasks.ts                           媒体任务状态机、串行锁、JSON 持久化、取消
  schemas.ts                         HTTP 请求 Schema
  debug.ts                           Provider 源码调试运行器

apps/server/src/utils/ai/
  provider.ts                        文本 Provider 配置与模型能力
  index.ts                           streamAi 文本调用
  network/transport.ts 所在模块       代理与 Undici transport

apps/server/src/routes/providers/    Provider 安装、编辑、校验、调试 API
apps/server/src/routes/ai/media/     媒体生成、模型、报价、余额、任务状态/取消 API

apps/web/src/pages/workspace/        工作台、画布、文档
apps/web/src/pages/workspace/panels/workbench/workbenchPanel.vue
packages/nodeShared/src/useNodeGeneration.ts
packages/nodeScaffold/src/nodeAi.ts

packages/multiTenant/db/             Drizzle Schema、SQLite/MySQL 实现
packages/multiTenant/auth/           账号、会话、用户设置
packages/multiTenant/models/         模型路由、价格、专用云凭据
packages/multiTenant/billing/        钱包、预占、结算
packages/multiTenant/gateway/        统一模型分派与计费
```

## 3. 现有 Provider 体系

### 3.1 公共协议

`packages/providers/types.d.ts` 中已有：

- `ProviderDefinition`：`id`、`label`、`rules`、`models`、可选 `getPrice`、`getBalance`、`generateImage`、`generateVideo`、`generateAudio`、`resumeTask`、`processMedia`。
- `ProviderTaskData`：只允许 JSON 标量、数组和对象，用来保存可恢复的上游凭据。
- `ProviderTools`：宿主注入的 `fetch`、错误信息提取、媒体处理、音频处理、FFmpeg。
- `ProviderContext`：配置、AbortSignal、`saveTaskData`、工具集合。

这是后续 Diagnostics、Task Runtime 和 ComfyUI Connection Manager 应复用的主协议。不要另建与 `ProviderDefinition` 平行的媒体 Provider 接口。

### 3.2 Provider 加载链

实际调用链：

```text
HTTP /api/ai/media/generate
  -> apps/server/src/routes/ai/media/generate.ts
  -> mediaTasks.start(cwd, taskId, ...)
  -> apps/server/src/utils/media/tasks.ts execute()
  -> generateMedia()
  -> configuredProvider()
  -> loadMediaProviderSource()
  -> Provider.generateImage()/generateVideo()/generateAudio()
  -> Provider.resumeTask()（恢复时）
```

`loadMediaProviderSource()` 的关键事实：

- 用 Babel 读取对象字面量元数据，用 Bun Transpiler 转成可执行源码。
- 使用 Node `vm.createContext()` 提供隔离上下文。
- 当前注入：`Buffer`、`atob`、`btoa`、`URL`、`URLSearchParams`、`TextEncoder`、`TextDecoder`、`Blob`、`AbortController`、`AbortSignal`、`setTimeout`、`clearTimeout`。
- 没有注入 `FormData`、`crypto`、`Headers`、`Request`、`Response`、`structuredClone` 等；`URL`、`URLSearchParams`、`Blob` 已注入。
- Provider 不能静态 import 模块；宿主通过 `this.tool` 注入能力。
- 注释已明确：VM 不是完整安全沙箱，不可信 Provider 仍需独立进程/容器隔离。

### 3.3 Provider HTTP 与错误

- `provider.ts` 包装 `generate*`/`resumeTask`，记录最近一次串行 HTTP 失败的 status 和响应正文，尝试把上游错误补入供应商抛出的消息。
- 当前错误模型没有统一的 `ProviderErrorCode`，API 响应主要由 `errorFromCause()` 根据 `status` 或文件系统 `code` 生成。
- 429、401、402、模型不存在、DNS、TLS、超时、无效响应等通常退化为上游文本或通用 500。
- `mediaErrorMessage()` 能从 JSON/对象字段提取错误，但对 `Error` 实例的 `message` 读取不完整，存在“普通 Error 被裸露、无法统一脱敏”的风险。

### 3.4 现有调试能力

已有 `apps/server/src/utils/media/debug.ts` 和 `/api/providers/debug/run`：

- 可以执行源码。
- 记录网络请求。
- 对配置密钥、Authorization、URL 查询参数做脱敏。
- 有 200 次请求、响应正文大小和流式事件限制。

这不是完整的 Provider Diagnostics：没有统一健康结果、检查项、最近成功/错误、模型列表检查、实际调用测试的正式 API 和健康状态持久化。后续应把它作为底层调试器复用，而不是另写一套执行器。

## 4. 媒体任务生命周期

### 4.1 当前数据结构

`apps/server/src/utils/media/tasks.ts` 的 `TaskRecord` 是持久化任务记录，主要字段：

```ts
{
  version: 1;
  taskId: string;
  cwd: string;
  mediaType?: "image" | "video" | "audio";
  request?: ImageRequest | VideoRequest | AudioRequest;
  nodeId?: string;
  canvasPath?: string;
  ownerUserId?: string;
  modelRouteCipher?: string;
  chargeId?: string;
  chargeStatus?: "settled" | "released" | "pendingReview";
  state: "running" | "interrupted" | "succeeded" | "failed" | "cancelled";
  createdAt: number;
  updatedAt: number;
  checkpoint: {
    providerData?: ProviderTaskData;
    assets?: URL 资产[];
    assetCount?: number;
    files?: Array<GeneratedMedia & { index: number; hash: string }>;
  };
  blobs?: BlobReference[];
  result?: { code: number; data: GeneratedMedia[] | null; message: string };
}
```

### 4.2 当前状态与控制

- 前端在 `packages/nodeShared/src/useNodeGeneration.ts` 和 `packages/nodeScaffold/src/nodeAi.ts` 中先创建任务 UUID，再提交 `/api/ai/media/generate`。
- 服务端 `mediaTasks.start()` 对同一 `taskId` 使用串行锁；相同 `taskId` 和相同请求返回已有任务，不相同则 409。这是当前的基础幂等保护。
- 任务记录写到 `data/mediaTasks/workspace<hash>/task<hash>.json`，采用 `writeAtomic`，大 base64 参考素材拆分到私有 `media<hash>.bin`。
- 运行中的任务用 `AbortController` 取消；取消先持久化 `cancelled`，再释放扣费。
- `resumeMedia()` 走 `/api/ai/media/tasks/status` 的 `resume: true`，由 `providerData` 调用 Provider 的 `resumeTask()`。
- 进程重启后没有主动扫描任务；只有前端下一次轮询/恢复时才加载记录。
- 并发上限是全局进程内 `activeCount >= 1000`，没有 Provider、实例、任务类型或租户级并发控制。
- 内存 `Map` 和 Promise 队列只做单进程协调，不能作为多实例一致性保障。

### 4.3 幂等性缺口

当前已经能防止：

- 同一页面重复点击导致同一 `taskId` 被创建两次。
- 相同任务 ID 的不同请求被 409 拒绝。
- 取消请求早于提交响应时，取消状态先落盘。

仍不能证明：

- 上游已接受、但响应在网络上丢失时的远端幂等。
- 进程在“开始调用 Provider 前”和“保存 ProviderTaskData 前”崩溃后的精确区分。
- 多 Worker/多实例同时处理同一个持久任务。

当前 `generateMedia()` 在调用 Provider 前会执行 `markSubmitted()`，但这只是进程内标志，没有形成持久化的 `submission_unknown` 状态。重启后若 `providerData` 不存在，`resumable()` 返回 false，前端会进入“结果未知，请人工核对”的路径；这是保守的，但不是完整的 Runtime 状态机。

## 5. ComfyUI 实现审计

涉及：

- `packages/providers/src/media/solodramaComfy.ts`
- `packages/providers/src/media/solodramaComfyCloud.ts`
- `apps/server/src/utils/media/provider.ts`
- `apps/server/src/utils/media/generation.ts`
- `apps/server/src/utils/media/tasks.ts`

### 5.1 当前调用链

```text
generateImage/generateVideo
  -> routeFor()
  -> workflowForRoute()/workflowFor()
  -> mappingForRoute()/mappingFor()
  -> applyCommon()
  -> prepareImages()
  -> uploadImage()              POST /upload/image
  -> submitPrompt()             POST /prompt
  -> saveTaskData({ promptId, deadline, baseUrl })
  -> awaitResult()              GET /history/{promptId}
  -> collectOutputs()           GET /view?... 下载结果
```

渲染层：

```text
nodeShared/useNodeGeneration
  -> nodeScaffold/nodeAi
  -> POST /api/ai/media/generate
  -> mediaTasks.start
  -> mediaGeneration.generateMedia
  -> solodramaComfy.generateImage/Video
```

### 5.2 已确认问题

#### P0：Provider VM 缺少 `FormData`、`crypto` 等运行时全局对象

- `solodramaComfy.ts` 使用 `new FormData()` 上传参考图。
- `submitPrompt()` 使用 `crypto.randomUUID()`。
- `normalizeBaseUrl()` 和 `isLocalAddress()` 使用 `new URL()`。
- `solodramaComfyCloud.ts`、`solodramaRunningHub.ts`、`solodramaRunningHubClosed.ts` 也依赖这些对象。
- `provider.ts` 的 VM 上下文没有注入这些全局对象。
- 已用同一 `node:vm` 方式验证：空白上下文中的 `typeof crypto`、`typeof FormData` 均为 `undefined`；Provider 加载器虽注入 `URL`，但未注入前两项。

影响：即使 ComfyUI 服务在线，上传或提交也会抛 `ReferenceError`；Provider Debug、余额查询、实际生成都可能被阻断。

#### P0：上传覆盖

`uploadImage()` 当前：

```ts
const name = ... sanitize(media.name)
form.append("image", new Blob(...), name + "." + extension)
form.append("overwrite", "true")
```

同名素材会被覆盖，任务之间没有隔离。默认图的 `name` 还可能固定为 `solodrama-empty.png` 等，无法依靠业务名保证唯一。

#### P0：全局 interrupt

`cancel()` 当前先 POST `/queue` 删除 `promptId`，随后除非配置为 false，否则无条件 POST `/interrupt`，请求体为 `{}`，没有 `prompt_id`。

ComfyUI 的 `/interrupt` 语义通常是中断当前正在执行的处理，而不是按给定的 prompt_id 精确取消。这个实现可能中断同实例上另一个用户的另一个任务。

#### P1：取消结果不可核实

Provider 的取消是 `catch` 中尽力而为，错误被吞掉，宿主任务已经被标为 `cancelled`。没有区分：

- 排队任务已从队列删除。
- 运行中任务仅停止本地等待，远端仍在运行。
- 远端取消失败或待确认。

#### P1：没有 `/queue`、`/system_stats`、`/object_info`、`/features` 能力探测

当前只依赖 `/history` 轮询，没有实例能力、GPU、队列、节点安装、版本特性检测。也不能在实例不支持任务级取消时安全降级。

#### P1：没有 WebSocket 复用和断线恢复

当前没有 `/ws` 连接管理、节点事件、进度、心跳或 HTTP fallback；始终轮询 `/history`。

#### P1：实例模型仍是“单 Provider 配置 + routes 数组”

`MediaRoute` 可以在每条 route 填 `baseUrl`、鉴权 Header 和工作流，但这不是独立实例注册表、健康状态、并发配额或连接管理器。没有统一 `ComfyInstance` 持久化实体。

#### P1：工作流元数据不完整

当前 route 里有 `workflow`、`mapping`、`baseUrl` 等，但没有稳定的工作流 ID、版本号、必需节点列表、导入/导出版本链和节点缺失检测。

#### P1：SSRF 边界不足

`normalizeBaseUrl()` 只校验协议和内嵌凭据，不限制私网、回环、链路本地、云元数据地址。Provider 可以在服务端请求任意 HTTP(S) URL。多租户下供应商管理一般是管理员权限，但远端 ComfyUI 和自建 Provider 仍需明确信任边界。

## 6. RunningHub 实现审计

涉及：

- `packages/providers/src/media/solodramaRunningHub.ts`
- `packages/providers/src/media/solodramaRunningHubClosed.ts`

### 6.1 当前实现

- `solodramaRunningHub.ts` 只使用 AI App 协议：
  - `POST /task/openapi/ai-app/run`
  - `GET /api/webapp/apiCallDemo`
  - `/openapi/v2/query`，失败后兼容 `/task/openapi/outputs`
  - `/task/openapi/cancel`
  - `/openapi/v2/media/upload/binary`
- `RunningHubTaskData` 保存 `taskId`、`routeId`、`mediaType`、`deadline`，支持 `resumeTask()`。
- `awaitResult()` 轮询任务状态，校验失败/成功状态，过滤输出类型，下载结果。
- 闭源模型 Provider 使用官方 v2 上传、查询和下载端点，支持恢复。
- `RunningHubRequestError` 保留 HTTP status 和平台 code，`friendly()` 对 421/805/1014/1602 提供提示。

### 6.2 已确认问题

- 与 ComfyUI 一样受 Provider VM 缺少 `FormData`/`crypto` 影响。
- 提交成功但响应丢失时，`taskId` 无法从本地任务恢复；`providerData` 只在响应解析出 `taskId` 后才保存。
- `cancel()` 吞掉所有错误，任务取消只代表本地停止等待，不代表 RunningHub 远端已取消。
- 错误分类仍不统一；不同 Provider 的 HTTP/平台 code 没有映射到统一 Provider 错误码。
- 没有 Provider 级并发控制、队列、健康检查、最近错误和诊断结果。
- 输出下载允许 Provider 返回任意 HTTP(S) URL；需要按信任边界评估是否限制重定向目标、私网地址和响应大小。当前 `generation.ts` 下载结果时有 100 MB 上限，但 Provider 自身下载路径不受同一个宿主预算约束。

## 7. Workbench 数据来源审计

涉及：

- `apps/web/src/pages/workspace/panels/workbench/workbenchPanel.vue`
- `apps/web/src/pages/workspace/panels/canvas/canvasFiles.ts`
- `packages/nodeShared/src/projectSettings.ts`
- `apps/web/src/lib/workspaceFiles.ts`
- 各画布节点包

### 7.1 当前数据来源

工作台读取：

- `.solodrama/project.json` 的 `SoloDramaProjectSettings`。
- 当前工作区所有画布 JSON。
- 文本节点的 `textPath` 指向的文本文件。
- 画布节点的 `outputs.image/video/audio`。
- 节点类型正则：`textNode`、`imageGenerationNode`、`videoGenerationNode`。
- 节点标签中文关键词：`场景|地点|环境`、`道具|物件`、`角色|人物|主角|配角|群演`。
- 画布边：从分镜视频节点向上游寻找图片输出，作为参考图。

### 7.2 已确认问题

- `project.json` 只有项目规格和插件配置，没有 Episode、Scene、Shot、Character、Location、Prop、Asset、Take 的稳定实体。
- 工作台 `documentNodes`、`assetNodes`、`shotNodes`、`videoNodes` 都是每次从画布节点实时推导的视图模型。
- 角色/场景/道具分类依赖节点标签正则，不是业务 ID。
- 分镜镜头就是视频生成节点，无法明确表达“一个 Shot 的多个 Take”。
- 没有正式 Take 选择、历史比较、已选版本不可覆盖、生成参数快照和恢复语义。
- 文本编辑已经使用 `readTextSnapshot()` + `writeTextSnapshot()` 的 revision 冲突保护，这是可复用的乐观并发机制。
- 工作台修改项目规格时写 `.solodrama/project.json`；没有与画布节点建立稳定实体关联。
- Canvas 与 Workbench 目前是“共享画布文件”，不是“两个独立模型通过稳定 ID 关联”。

## 8. 数据库与存储审计

### 8.1 媒体任务存储

- 任务 JSON 在 `data/mediaTasks/` 下按工作区路径哈希分目录。
- 任务 ID 和输出文件名以 UUID 派生，输出写入工作区 `assets/generated/`。
- 记录和大引用素材使用原子写入，目录权限 0700，文件 0600。
- 队列、活跃任务、Provider 并发配额目前都在进程内。

### 8.2 多租户数据库

`packages/multiTenant/db/schema.ts` 当前表：

- `multiTenantAdmin`
- `multiTenantUser`
- `multiTenantWebSession`
- `multiTenantSettings`
- `multiTenantSourceMapping`
- `multiTenantModelRouting`
- `multiTenantWallet`
- `multiTenantBillingLedger`

没有：

- 项目/剧集/场景/镜头/角色/道具/资产/Take 表。
- 持久任务表和任务事件表。
- 租户组织表、项目归属表和跨用户协作关系表。
- Provider/ComfyUI 实例健康状态表。

### 8.3 多租户隔离现状

- 用户身份来自 `multiTenantUser`，工作区根目录为 `data/multiTenant/workspaces/<userId>`。
- `resolveWorkspace()` 校验目录必须在用户根目录内；管理员可以访问主工作区。
- 媒体任务的 `ownerUserId` 写入任务记录；`assertOwner()` 拒绝其他普通用户读取。
- 用户设置存 SQL，使用 `settingsRevision` 做比较写入。
- 账号禁用/重置通过 `authVersion` 使旧会话失效。
- 当前“租户”主要是用户级隔离，没有组织/租户实体；多用户共享一个租户、项目转交、租户管理员等能力尚未落地。
- 任务内存状态、文件锁、Provider 余额缓存和取消控制器都不能跨实例共享。

## 9. 验证体系审计

- 根 `package.json` 有 `typecheck`、`build`、各应用 `typecheck`/`build`。
- `packages/providers` 只有 tsconfig，没有独立 test 脚本。
- 仓库内未发现 `*.test.ts`、`*.spec.ts`、`__tests__` 或测试框架配置。
- 根 `AGENTS.md` 明确禁止新增测试模块、测试脚本、测试依赖和 CI 测试入口。
- 因此本项目的“测试”必须解释为：现有类型检查、构建、已有脚本允许的手动验证，以及不落盘测试代码的临时命令验证。

## 10. 可复用能力

必须优先复用：

1. `ProviderDefinition` / `ProviderContext` / `ProviderTaskData`：统一 Provider 契约。
2. `loadMediaProviderSource()`：Provider 的解析、注入、错误提取和 VM 边界。
3. `mediaTasks`：现有任务 UUID、原子记录、恢复、幂等锁和扣费关联。
4. `mediaGeneration`：请求准备、媒体下载、MIME 校验、工作区写入。
5. `workspaceFiles`：路径边界、原子写入、快照 revision 和 URL 生命周期。
6. `multiTenant` 的 `AuthIdentity`、`requestIdentity()`、SQL 用户设置和 `authVersion`。
7. `modelGateway` / `billing`：不要为媒体任务重造扣费和模型路由。
8. `useNodeGeneration`：节点级提交、恢复、取消和状态保存。
9. `workbenchPanel` 的现有设计系统、画布读取和项目规格读取。

## 11. 建议修改文件

### Milestone 1：稳定性

- `apps/server/src/utils/media/provider.ts`
  - 补 VM Web 全局对象。
  - 统一 Provider 错误归一化和安全脱敏入口。
- `packages/providers/src/media/solodramaComfy.ts`
  - 唯一上传文件名、关闭 overwrite。
  - 取消仅做精确排队删除，禁止无条件全局 interrupt。
- `packages/providers/src/media/solodramaComfyCloud.ts`
  - 与本地 ComfyUI 同步修复。
- `packages/providers/types.d.ts`
  - 增加 Provider 错误码契约和提交状态类型。
- `apps/server/src/utils/media/errors.ts`（新文件，小驼峰）
  - 统一错误分类、可重试性、安全 message。
- `apps/server/src/utils/media/tasks.ts`
  - 持久化 `submissionState`，区分 `submitting`、`submitted`、`accepted`、`unknown`。
  - 恢复时保守处理未知提交，不允许盲目重试。
- `apps/server/src/utils/media/generation.ts`
  - 在调用 Provider 前持久化提交意图，在收到 ProviderTaskData 后标记已接受。
- `packages/nodeScaffold/src/nodeAi.ts` / `packages/nodeShared/src/useNodeGeneration.ts`
  - 如需展示“提交未知/待核实”，补充状态映射；不改变已有 API 必填结构。

### Milestone 2：Provider Diagnostics

- 复用 `apps/server/src/utils/media/debug.ts` 的网络捕获和脱敏。
- 新增 `apps/server/src/utils/media/diagnostics.ts`（小驼峰）。
- 新增 Provider 诊断路由（单接口单文件）。
- `packages/providerWeb/providerEditor.vue` 增加连接、模型、鉴权和实际调用测试入口。
- 统一读取 `ProviderDefinition.modelsUrl` 和 `getBalance` 能力。

### Milestone 3：ComfyUI Connection Manager

- 复用现有 `MediaRoute`，逐步扩展为实例注册表。
- 新增 `apps/server/src/utils/comfy/`（目录小驼峰）和持久化配置。
- 新增实例管理、健康检测、WebSocket、HTTP fallback、队列和能力 API。
- 前端在现有媒体模型设置页增加实例管理，不建冲突的独立设置页。

### Milestone 4：Task Runtime

- 在 `mediaTasks` 外抽象持久 Repository / Scheduler / Dispatcher，但第一阶段实现仍复用现有 JSON 记录。
- 任务状态扩展为 Runtime 状态；保留旧 `running/interrupted/succeeded/failed/cancelled` 映射。
- 事件通过现有任务轮询/项目 SSE 基础评估后接入。

### Milestone 5：Workbench Domain Model

- 在 `.solodrama/` 增加版本化领域模型文件，不改变现有画布格式。
- 先做读模型和迁移器，再让工作台读取正式实体。
- 使用 `readTextSnapshot/writeTextSnapshot` 做冲突保护。
- 旧项目迁移必须幂等、保留原画布和原文件。

## 12. 风险与兼容策略

- 不在 Milestone 1 一次性替换媒体任务记录格式；新增字段保持可选，旧记录默认可读。
- 不改变 `/api/ai/media/generate` 现有参数；只增加内部状态和响应字段。
- 不删除旧 `cancelRunning` 配置字段，但改变其危险行为时应明确提示它是兼容字段，不再代表全局中断。
- 不把 `FormData`/`crypto` 的修复写成业务 Provider 的分散兜底；在 Provider VM 注入层统一修复。
- 不对 RunningHub 未公开接口做逆向；继续使用当前官方端点。
- 不做无确认的数据库删除、迁移回滚或 OSS 清理。
- 多租户隔离不能仅依赖前端隐藏；所有任务/文件/事件接口必须继续在服务端做 owner 校验。
- 任何领域模型迁移都必须保留旧画布、旧文本和旧项目设置，并提供可重复执行的导入路径。

## 13. 审计限制

本报告基于静态读取和类型检查：

- 已运行：`apps/server` typecheck、`apps/web` typecheck、`packages/providers` typecheck、`packages/multi-tenant-db` typecheck。
- 未执行真实 ComfyUI、RunningHub 付费调用；未使用真实 API Key。
- 未执行 MySQL 实例验证。
- 未发现仓库测试入口，因此没有测试数量可报告。
- `packages/nodeScaffold` 单独 `tsc` 因虚拟 Vue 模块失败，未把它当作业务回归结论。
