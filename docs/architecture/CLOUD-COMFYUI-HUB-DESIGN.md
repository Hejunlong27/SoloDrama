# 通用云端 ComfyUI 接入中心设计

## 1. 总体架构

```text
Web 云端算力中心
  |-- 实例管理
  |-- 工作流库
  |-- 兼容性检测
  |-- 任务监控
          |
          v
ComfyHub Service (apps/server/src/utils/comfyHub)
  |-- Encrypted Store
  |-- ComfyUI Connector (HTTP + WebSocket)
  |-- Instance Scheduler
  |-- Workflow Source Reader
  |-- Provider Tools
          |
          v
Existing Media Task Runtime
          |
          v
solodramaComfyHub Provider
          |
          v
任意兼容 ComfyUI API 的实例
```

平台名称只保存在 `platformLabel`，执行协议不按平台分支。

## 2. 数据模型

### ComfyUIInstance

持久化到 `data/comfyHub/instances.json`：

```ts
type ComfyUIInstance = {
  id: string;
  name: string;
  platformLabel: string;
  endpoint: string;
  websocketEndpoint?: string;
  authMode: "none" | "bearer" | "header";
  authHeaderName?: string;
  secretCipher?: string;
  customHeaders?: string; // 合并进 secretCipher 的密文载荷
  allowPrivateNetwork: boolean;
  connectionTimeoutMs: number;
  priority: number;
  enabled: boolean;
  favorite: boolean;
  group?: string;
  tags: string[];
  note?: string;
  health?: ComfyHealth;
  createdAt: number;
  updatedAt: number;
};
```

公开 API 只返回：

- `hasCredential`
- `headerNames`
- 健康状态和非敏感元数据

Token 与自定义 Header 使用 AES-256-GCM 加密：

- 密钥文件：`data/comfyHub/secret.key`，目录 0700，文件 0600。
- 密文 AAD：`solodrama:comfyHub:v1`。
- API 和前端不接触明文 Token。

### WorkflowDefinition

```ts
type ComfyWorkflow = {
  id: string;
  name: string;
  description: string;
  category: string;
  type: "image" | "video" | "audio";
  format: "api" | "ui";
  apiWorkflow: string;
  sourceWorkflow?: string;
  mapping: string;
  requiredNodes: string[];
  requiredModels: string[];
  sourceType: "local" | "http" | "git" | "s3" | "market";
  sourceRef?: string;
  sourceConfig?: Record<string, unknown>;
  version: number;
  versions: WorkflowVersion[];
  createdAt: number;
  updatedAt: number;
};
```

- UI Workflow 保存原始来源并通过共享转换器生成 API Prompt。
- 更新工作流时旧版本进入最多 20 条本地版本历史。
- 生成节点以工作流 ID 作为模型 ID。

## 3. ComfyUI Connector

### 健康与能力

`probeInstance()` 执行：

1. `GET /system_stats`
2. `GET /object_info`
3. `GET /queue`
4. `GET /features`（可选）
5. WebSocket 连接探测

返回：

- 在线/降级/离线。
- 延迟。
- ComfyUI 版本。
- 节点数量和节点名。
- 运行/排队任务数。
- 可选 features。
- WebSocket 状态。

单个实例失败只返回自身离线或降级，不阻断其他实例。

### 提交与结果

- `POST /prompt` 提交 API Prompt。
- `prompt_id` 立即通过 ProviderTaskData 保存。
- `/ws` 用于完成/错误事件唤醒。
- 无论 WebSocket 是否存在，都保留 `/history/{prompt_id}` 轮询核验。
- 完成后通过 `/view` 下载结果。

### 精确取消

- 排队任务：读取 `/queue`，只有目标 promptId 在 `queue_pending` 时才 POST `delete: [promptId]`。
- 运行中任务：不发送无 prompt_id 的全局 `/interrupt`。
- 没有经过验证的实例级定向取消能力时，只停止本地等待并保持结果不确定提示。

### SSRF

- 默认只允许公网 HTTP(S)。
- 用户必须显式开启“允许本机/局域网地址”。
- 即使开启，仍拒绝 IPv4 链路本地、IPv6 链路本地和已知云元数据主机。
- 工作流 HTTP/S3/Git 来源使用公网地址校验；Git 只接受 HTTPS、仓库内相对文件路径和受限 clone。

## 4. 调度

自动调度步骤：

1. 只保留启用实例。
2. 使用手动指定的 `request.other.instanceId`，若指定。
3. 探测实例节点。
4. 过滤缺少必需节点的实例。
5. 工作流显式声明 `requiredModels` 时，在无法从标准 API 可靠确认模型安装的情况下拒绝执行。
6. 按优先级降序、队列总长度升序、实例名称排序。
7. 选中实例后保存其 ID 与 endpoint 到 ProviderTaskData。

支持：

- 手动实例。
- 自动选择。
- 优先级。
- 队列长度。
- 工作流节点匹配。

未实现：

- 失败后自动换实例重试。
- 实例组偏好。
- GPU 显存精确门槛调度。

## 5. 工作流来源

已实现：

- 本地 JSON 粘贴/文件输入。
- HTTP/HTTPS 下载。
- Git HTTPS clone + 仓库内 JSON 路径 + 分支。
- S3 兼容公开或预签名对象 URL。

未实现：

- AWS SigV4 临时凭据/SDK 原生 S3 客户端。
- 未经确认的云厂商专有工作流市场 API。

`market` 来源当前返回 501，不会伪造成功。

## 6. Task Runtime 集成

Provider 文件：

`packages/providers/src/media/solodramaComfyHub.ts`

- 只有薄协议入口。
- 调用宿主注入的 `this.tool.comfyHub.generate/resume`。
- 没有按平台复制 HTTP 或工作流实现。

持久任务 ProviderTaskData：

```ts
{
  kind: "solodramaComfyHub";
  promptId: string;
  instanceId: string;
  baseUrl: string;
  mediaType: "image" | "video" | "audio";
  deadline: number;
}
```

现有媒体任务记录继续负责：

- taskId。
- submissionState。
- 原子落盘。
- 重复提交控制。
- 进程重启恢复。
- 输出文件哈希。

## 7. API

### 实例

- `GET /api/comfyHub/instances/list`
- `PUT /api/comfyHub/instances/save`
- `DELETE /api/comfyHub/instances/delete`
- `POST /api/comfyHub/instances/test`
- `POST /api/comfyHub/instances/capabilities`

### 工作流

- `GET /api/comfyHub/workflows/list`
- `GET /api/comfyHub/workflows/get`
- `PUT /api/comfyHub/workflows/save`
- `POST /api/comfyHub/workflows/import`
- `POST /api/comfyHub/workflows/sync`
- `POST /api/comfyHub/workflows/verify`
- `DELETE /api/comfyHub/workflows/delete`

### 任务

- `GET /api/comfyHub/tasks/list`

所有 Hub 管理接口仅允许桌面端或服务器本机工作区请求。Token 不在响应中出现。

## 8. 生命周期适配器

`lifecycle.ts` 预留：

- Start。
- Stop。
- Restart。
- Release。
- Query。

当前没有注册任何平台适配器，因为没有在本项目中确认到可用的官方生命周期 API。ComfyUI 连接不依赖该能力。

## 9. 桌面启动器

复用现有 Electrobun：

- 双击后启动应用。
- 同进程启动 Server。
- 自动分配本地端口。
- 原生启动画面。
- Server/WebView 就绪后自动进入主界面。
- Windows 写入 `app.log`。
- 启动失败显示错误弹窗和日志路径。
- 关闭主窗口时关闭 Server、MCP、浏览器及连接。
- 安装、快捷方式、更新器和数据保留沿用现有发布链路。

本轮没有重新实现第二套桌面技术。