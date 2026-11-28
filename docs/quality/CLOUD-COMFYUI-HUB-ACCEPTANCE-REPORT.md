# 通用云端 ComfyUI 接入中心验收报告

> 验收日期：2026-11-27  
> 验收对象：Cloud ComfyUI Hub、统一 Provider、工作流库、实例调度、现有 Task Runtime 集成、Electrobun 一键桌面启动器。  
> 原则：只记录实际执行过的命令和真实结果；未连接的真实云平台不标记为通过。

## 1. 总体结论

云端 ComfyUI Hub 的核心连接、实例管理、工作流库、兼容性检测、任务调度、WebSocket/HTTP 回退、精确取消、任务持久化和安全存储已经落地，并通过本地 Mock ComfyUI 服务实际执行。

桌面启动器复用现有 Electrobun 应用，代码链路具备双击启动、自动创建 Server、自动进入主界面、日志和失败弹窗。但本次环境无法生成桌面安装包：

- `.hutch/dependencies.lock` 缺失。
- Hutch 0.30.0 已安装。
- Bun 1.4.4 工具链下载返回 `CertificateBundleLoadFailure`。

因此：

- Web/Server 生产构建通过。
- 桌面应用源码已修改，但桌面 typecheck 和安装包构建未通过。
- 未生成新的安装包，不虚报安装路径中的文件存在。

## 2. 实际运行过的命令

| 命令 | 结果 |
|---|---|
| `bun run --cwd apps/server typecheck` | 通过 |
| `bun run --cwd apps/web typecheck` | 通过 |
| `bunx tsc -p packages/providers/tsconfig.json --noEmit` | 通过 |
| `bunx tsc -p packages/toolScaffold/tsconfig.json --noEmit` | 通过 |
| `bun run build` | 通过，保留既有 Vite configLoader 和大 chunk 警告 |
| `bun test` | 失败：`No tests found!` |
| `bun run lint` | 失败：`Script not found "lint"` |
| `bun run typecheck` | 失败：仅桌面端 Electrobun 类型声明缺失；其余已输出包均通过 |
| `bun run build:desktop` | 失败：缺少 `.hutch/dependencies.lock` |
| `bunx electrobun --help` | Hutch 安装后失败：Bun 1.4.4 工具链下载 `CertificateBundleLoadFailure` |
| `git diff --check` | 通过，仅有既有 LF/CRLF 提示 |
| `bun <Cloud Hub 三实例探针>` | 通过：`["online","online","online"]` |
| `bun <Cloud Hub 调度/回退探针>` | 通过 |
| `bun <Cloud Hub Task Runtime 探针>` | 通过 |
| `bun <Cloud Hub HTTP API 探针>` | 通过 |
| `bun <Hub 精确取消探针>` | 通过 |
| `bun <Hub 凭据加密探针>` | 通过 |
| `bun <工作流版本探针>` | 通过 |
| `bun <缺失节点检测探针>` | 通过 |
| `bun <Hub 模型目录探针>` | 通过 |

说明：根 `AGENTS.md` 禁止新增 `.test.ts`、`.spec.ts`、测试脚本、测试依赖和 CI 测试入口，因此行为验收使用 `%TEMP%` 下的临时外部探针，没有向仓库写入测试文件。

## 3. 已实现功能

### 3.1 统一 ComfyUI Connector

- `/system_stats` 健康检查。
- `/object_info` 节点清单。
- `/queue` 队列查询。
- `/features` 可选能力。
- `/ws` WebSocket 探测。
- `/upload/image` 上传。
- `/prompt` 提交。
- `/history/{prompt_id}` 最终状态核验。
- `/view` 结果下载。
- WebSocket 不可用时 HTTP 轮询回退。
- 单实例超时。

所有平台共用同一协议。`platformLabel` 只是实例标签，不参与执行分支。

### 3.2 实例管理

- 多实例新增、编辑、删除、启用/禁用。
- token 和自定义 Header 加密保存。
- 收藏、分组、标签、备注、优先级。
- 私网访问白名单开关。
- 单实例连接测试。
- 节点数量、features、运行/排队数。
- 健康状态和最近检测时间。

### 3.3 自动调度

当前实现：

- 手动指定 `instanceId`。
- 自动选择启用实例。
- 必需节点匹配。
- 优先级降序。
- 队列总长度升序。
- 实例名称稳定排序。
- 离线实例不影响其他实例。
- 选中实例 ID 和 endpoint 写入 ProviderTaskData。

未实现：

- 提交失败后自动换实例重试。
- 实例组偏好。
- GPU 显存硬性门槛。

### 3.4 WebSocket 与 HTTP 回退

- 优先打开实例 `/ws`。
- 收到 executed/error 事件后立即查询 history。
- WebSocket 断开或不可用时继续 history 轮询。
- 最终完成状态始终通过 HTTP history 核实。
- 恢复任务不重新提交工作流。

### 3.5 精确取消

- 排队任务先读取 `/queue`。
- 只有 promptId 存在于 `queue_pending` 时才按 promptId 删除。
- 不调用无 promptId 的全局 `/interrupt`。
- 运行中任务只停止本地等待，并保留不确定状态。

### 3.6 工作流库

- 本地 JSON 导入。
- HTTP 下载。
- Git HTTPS 浅克隆 + 仓库内相对路径。
- S3 兼容公开/预签名 URL。
- UI Workflow 自动转换为 API Prompt。
- 显式区分 `ui` 和 `api` 格式。
- 参数映射。
- 节点依赖提取。
- 工作流版本自动递增。
- 保留最近 20 个版本。
- 实例兼容性检测。
- 来源同步创建新版本。
- 工作流作为媒体模型出现在现有生成节点。

### 3.7 Task Runtime 集成

- 没有新增第二套任务系统。
- 全部 Hub 生成经现有 `mediaTasks`。
- ProviderTaskData 保存 instanceId、promptId、baseUrl、deadline。
- 现有幂等、submissionState、原子持久化和启动恢复继续生效。
- 任务监控读取同一任务记录。

### 3.8 桌面启动器

复用现有 Electrobun：

- 双击启动。
- 自动创建 Express Server。
- 自动分配本地端口。
- 原生启动画面。
- 等待页面 ready 后进入主界面。
- 关闭时停止 Server、MCP、浏览器和连接。
- Windows `app.log`。
- 本轮新增启动失败弹窗和日志路径提示。
- 本地 ComfyUI 不是启动条件。

## 4. 实际验收结果

### 4.1 三实例同时连接

三个不同本地 Mock ComfyUI 地址并发测试：

```json
["online","online","online"]
```

通过。

### 4.2 单实例异常隔离

一个离线实例与两个在线实例同时配置：

- 在线实例保持可用。
- 离线实例只影响自身状态。
- 自动生成仍能选择在线实例。
- 手动指定 HTTP 回退实例仍可完成生成。

通过。

### 4.3 WebSocket 和 HTTP 回退

- WebSocket 正常实例：health=`online`。
- WebSocket 不可用实例：health=`degraded`。
- WebSocket 断开后仍通过 history 轮询拿到结果。
- 两次生成结果均为 68 字节 PNG。

通过。

### 4.4 节点缺失

工作流要求 `MissingNode`，实例只提供 `SaveImage`：

```json
{
  "compatible": false,
  "missingNodes": ["MissingNode"],
  "missingModels": []
}
```

通过。

### 4.5 精确取消

Mock 队列：

- running：`taskB`
- pending：`taskA`

删除结果：

```json
{
  "cancelled": true,
  "deletes": [["taskA"]],
  "interrupts": 0
}
```

通过。

### 4.6 Task Runtime 端到端

通过 `mediaTasks.start()` 创建 Hub 任务：

- Provider VM 加载成功。
- `comfyHub` 工具注入成功。
- 实例自动选择成功。
- 提交 prompt 成功。
- WebSocket 完成事件触发。
- history 核实成功。
- PNG 落盘成功。
- 任务最终 `succeeded`。
- ProviderTaskData 包含 instanceId 和 promptId。

通过。

### 4.7 HTTP API

临时 Express 挂载真实 Hub 路由：

- 保存实例：HTTP 200。
- 导入工作流：HTTP 200。
- 兼容检测：HTTP 200，compatible=true。
- 工作流列表：HTTP 200。
- 远程请求：HTTP 403。

通过。

### 4.8 凭据安全

保存 Token 和自定义 Header 后：

```json
{
  "publicHasSecret": false,
  "headerNames": ["X-Key"],
  "runtimeToken": "sk-hub-secret-123",
  "diskHasSecret": false,
  "cipher": true
}
```

结论：

- 普通 API 无明文。
- JSON 文件无明文。
- 运行时内部可解密。
- secret.key 用于 AES-256-GCM。

通过。

### 4.9 工作流格式与版本

- UI Workflow 识别为 `ui`。
- API Prompt 识别为 `api`。
- 原始 sourceWorkflow 保留。
- 更新后版本从 v1 增至 v2。
- v1 历史可读取。

通过。

### 4.10 模型目录

Hub 工作流在现有媒体模型目录返回：

```json
{
  "providerId": "solodramaComfyHub",
  "providerLabel": "云端 ComfyUI",
  "type": "image"
}
```

通过。

## 5. 未解决问题

### P0

无已知未解决的问题。

### P1

1. 桌面端安装包未生成
   - 原因：Hutch/Bun 1.4.4 工具链下载证书失败。
   - 影响：不能提供本次新安装包。
   - 不得关闭 TLS 校验绕过。

2. 真实云端 ComfyUI 未验证
   - 没有仙宫云、晨羽、优云智算或 RunningHub 的真实 ComfyUI URL/Token。
   - 本地 Mock 通过不等同于真实平台通过。

3. 无自动化测试文件
   - `bun test` 没有测试。
   - 根规范禁止新增测试模块。

4. 无 Lint 入口
   - `bun run lint` 无脚本。

5. 桌面 typecheck 失败
   - `.hutch/devkit/api/sdks/main` 缺失。
   - `electrobun/main` 无声明。

### P2

1. WebSocket 为按任务连接，未实现实例级长连接池。
2. 失败后不会自动切换到另一实例重试，避免未知提交状态重复执行。
3. 模型依赖检查依赖工作流显式 `requiredModels`。
4. S3 当前只支持公开/预签名 URL，不支持 SigV4 Access Key。
5. 工作流市场专有扩展未实现，`market` 返回 501。
6. 任务监控为轮询，不是实时事件流。
7. 自动调度没有 GPU 显存硬门槛和实例组偏好。

### P3

1. 增加实例级 WebSocket 复用和指数退避重连。
2. 增加 Provider 级别滑窗健康指标和任务耗时趋势。
3. 增加 SigV4/S3 SDK 适配器。
4. 增加真实平台连接向导模板，但模板不改变协议实现。
5. 增加安全的失败换实例策略：仅在明确“未提交”时切换。

## 6. 需要人工验证事项

- 真实仙宫云 ComfyUI 实例。
- 真实晨羽 ComfyUI 实例。
- 真实优云智算 ComfyUI 实例。
- 真实 RunningHub ComfyUI 兼容镜像（不是 RunningHub AI App API）。
- 其他自建/反向代理 ComfyUI。
- 各平台自定义 Token/Header 鉴权。
- WebSocket 经 Nginx/CDN 的代理兼容。
- 不同 ComfyUI 版本的 `/queue` 和 history 输出结构。
- 自定义节点和模型安装检查。
- Windows 安装包生成与桌面快捷方式。
- 双击启动、失败弹窗、日志打开、关闭时子服务清理。
- 无本地 ComfyUI 情况下仅用云端实例启动并生成。
- macOS/Linux 对应安装包。

## 7. 交付物状态

- 云端 ComfyUI Hub：已实现。
- 实例管理页面：已实现。
- 工作流库页面：已实现。
- 本地/HTTP/Git/S3 预签名来源：已实现。
- Task Runtime 集成：已实现并验证。
- 任务监控：已实现只读列表。
- Lifecycle Adapter 接口：已预留，无平台适配器。
- Web/Server 生产构建：通过。
- 桌面安装包：未生成，受 Hutch 工具链环境阻塞。