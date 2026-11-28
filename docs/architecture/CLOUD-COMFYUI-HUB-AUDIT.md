# 通用云端 ComfyUI 接入中心审计

> 审计日期：2026-11-27  
> 范围：现有 ComfyUI Provider、媒体任务、Provider 注册、工作流导入、配置存储、前端设置、Electrobun 桌面应用、安装与构建链路。

## 1. 当前架构

### 1.1 ComfyUI Provider

现有实现：

- `packages/providers/src/media/solodramaComfy.ts`
- `packages/providers/src/media/solodramaComfyCloud.ts`

两者均直接使用标准 ComfyUI API：

- `/system_stats`
- `/object_info`
- `/queue`
- `/upload/image`
- `/prompt`
- `/history/{prompt_id}`
- `/view`

现有能力：

- 工作流 API JSON 提交。
- 前端画布工作流 JSON 转换。
- 参数映射。
- ProviderTaskData 保存 promptId/baseUrl/deadline。
- `resumeTask()` 恢复。
- 排队任务精确删除。
- 不发送无 prompt_id 的全局 `/interrupt`。

限制：

- 云端配置仍以单 Provider 配置和 routes 为主，没有独立实例注册表。
- 没有实例健康、队列、GPU、节点清单和 WebSocket 连接管理。
- 没有跨实例自动调度。

### 1.2 Provider 注册

- `apps/server/src/app.ts` 在启动时把内置 Provider 源文件安装到 `data/providers/`。
- `loadMediaProviderSource()` 通过 Bun Transpiler + Node VM 执行可信 Provider。
- 宿主通过 `ProviderTools` 注入 fetch、媒体处理、FFmpeg、错误脱敏等能力。
- 本轮为 Hub 增加 `comfyHub` 宿主工具，Provider 文件只负责协议入口，实例、认证、工作流和调度由宿主持久领域执行。

### 1.3 Task Runtime

实际复用：

- `apps/server/src/utils/media/tasks.ts`
- `apps/server/src/utils/media/generation.ts`
- `packages/nodeScaffold/src/nodeAi.ts`
- `packages/nodeShared/src/useNodeGeneration.ts`

已有任务能力：

- UUID 任务 ID。
- 原子 JSON 持久化。
- ProviderTaskData 恢复。
- submissionState：`submitting | submitted | accepted | unknown`。
- 跨进程重复提交防护。
- 进程重启后的状态查询与 `resumeTask`。
- 输出文件哈希校验和结果落盘。

Hub 没有另建任务系统，所有 Hub 生成都经现有媒体任务入口。

### 1.4 工作流管理

已有：

- `apps/web/src/lib/comfyWorkflow.ts` 中的 UI Workflow → API Prompt 转换和参数自动映射。
- 媒体 Provider 编辑器中的 JSON 导入。
- 参数映射、节点依赖的零散文本配置。

限制：

- 工作流没有独立版本库。
- 工作流与实例没有兼容性记录。
- 没有本地/HTTP/Git/S3 来源统一入口。
- UI Workflow 和 API Prompt 格式没有显式持久化区分。

本轮把转换器提取到 `packages/providers/comfyWorkflow.ts`，供 Web 与 Server 共用。

### 1.5 配置存储

已有：

- `data/settings.json`：用户设置和 Provider 配置。
- `data/providers/`：Provider TypeScript 源码。
- 多租户模型密文适配器：`packages/multiTenant/models/secret.ts`。

问题：

- 普通媒体 Provider API Key 存储于 settings，不适合新增实例密文需求。
- 多租户模型密钥依赖多租户数据目录，不适合独立模式。

本轮新增独立 `data/comfyHub/`：

- `instances.json`
- `workflows.json`
- `secret.key`（0600）

实例 Token 和自定义 Header 使用 AES-256-GCM 加密，普通 API 不返回明文。

### 1.6 前端结构

- 设置中心为单对话框 + 侧边导航：`apps/web/src/components/settings/index.vue`。
- 媒体模型、文本模型和 Provider 测试面板已存在。
- 工作台目前主要读取画布节点，没有正式云端算力中心页面。

本轮新增：

- `apps/web/src/components/settings/panels/cloudCompute/index.vue`
- “云端算力中心”设置导航

该页面包含实例、工作流库、任务监控和连接说明，复用现有设计体系。

### 1.7 桌面应用

现有 `apps/desktop` 已是完整 Electrobun 桌面应用：

- 双击启动。
- 启动前显示原生动画。
- 同一进程内创建 Express Server。
- 自动创建本地监听端口。
- 等待健康后端和 WebView。
- 自动打开主窗口。
- 关闭窗口时停止服务、浏览器和 MCP。
- Windows 安装包、快捷方式、更新器、数据保留和日志路径已有实现。

因此不新增第二套 Electron/Tauri 启动器。本轮只补充启动失败时的可见错误和日志路径提示。

## 2. 可复用能力

- ComfyUI 标准 HTTP 协议实现。
- Provider VM 和宿主工具注入。
- 媒体任务持久化、恢复、幂等和取消状态。
- UI Workflow → API Prompt 转换器。
- 设置中心 UI、Element Plus、现有样式变量。
- Electrobun 桌面生命周期、日志、安装器和更新器。
- 工作区下载器的公网地址校验。
- 多租户服务端代码执行边界和本地管理权限。

## 3. 本轮调整模块

### 新增

- `apps/server/src/utils/comfyHub/`
  - `store.ts`
  - `secret.ts`
  - `connector.ts`
  - `runtime.ts`
  - `index.ts`
  - `lifecycle.ts`
- `apps/server/src/routes/comfyHub/`
- `packages/providers/src/media/solodramaComfyHub.ts`
- `packages/providers/comfyWorkflow.ts`
- `apps/web/src/components/settings/panels/cloudCompute/index.vue`

### 修改

- `apps/server/src/utils/media/generation.ts`
- `apps/server/src/utils/media/provider.ts`
- `apps/server/src/utils/media/tasks.ts`
- `apps/server/src/app.ts`
- `apps/server/src/utils.ts`
- `apps/server/src/router.ts`（自动生成）
- `packages/providers/types.d.ts`
- `packages/providers/index.ts`
- `packages/providers/package.json`
- `apps/web/src/components/settings/index.vue`
- `apps/web/src/components/settings/panels/mediaModel/addCustomProviderDialog.vue`
- `apps/desktop/src/index.ts`

## 4. 数据迁移要求

- 不修改旧 `data/providers/`、`data/settings.json`、画布或项目文件。
- 首次使用 Hub 时才创建 `data/comfyHub/`。
- 原 `solodramaComfy` 和 `solodramaComfyCloud` Provider 继续可用。
- 云端 Hub 新增工作流不会覆盖旧 Provider routes 或工作流。
- `secret.key` 必须与实例密文一起备份；丢失密钥无法恢复 Token。
- 删除实例或工作流只删除 Hub 自身配置，不删除旧项目、生成文件或云资源。

## 5. 桌面启动器技术选型

继续使用 Electrobun：

- 已是当前技术栈。
- 已具备后端进程内启动、健康进入、窗口管理、日志、安装包和更新器。
- 新增独立启动器会重复已有生命周期和打包能力。

## 6. 影响范围与风险

影响：

- 生成节点媒体模型列表新增 Hub 工作流。
- Provider VM 工具契约增加可选 `comfyHub`。
- 新增本地管理模式 API。
- 桌面启动失败时多一个错误提示。

主要风险：

- 不同 ComfyUI 定制镜像的 `/queue`、`/history` 或 WebSocket 事件格式可能不同。
- 模型依赖无法仅从标准 `/object_info` 可靠确认，必须由工作流显式声明。
- 当前 WebSocket 为按任务连接，未做实例级长连接池。
- 当前自动调度按优先级和队列长度选择，不做提交失败后的自动换实例。
- 完整桌面安装包仍依赖 Hutch/Electrobun SDK 和 Bun 1.4.4 运行时下载。