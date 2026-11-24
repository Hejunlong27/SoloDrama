# SoloDrama Provider 接入说明

## 集成边界

Provider 使用当前 SoloDrama 的 `ProviderDefinition`、媒体节点请求和 `rules` 表单接口，不修改生成节点协议，也不需要独立设置页。

默认内置媒体供应商：

- 本地 ComfyUI：`packages/providers/src/media/solodramaComfy.ts`
- 云端 ComfyUI：`packages/providers/src/media/solodramaComfyCloud.ts`
- RunningHub 工作流：`packages/providers/src/media/solodramaRunningHub.ts`
- RunningHub 闭源模型：`packages/providers/src/media/solodramaRunningHubClosed.ts`
- 优云智算：`packages/providers/src/media/compshare.ts`
- SoloDrama TTS：`packages/providers/src/media/solodramaTts.ts`

真真 AI、APIMart、秘塔版 MiniMax 仍保留源码兼容能力，但不再出现在默认供应商目录中；需要时可通过“添加自定义媒体供应商”导入。

内部包名、画布数据键、请求头和事件名统一使用 SoloDrama 命名。

## ComfyUI

本地与云端是两个独立入口，共用 ComfyUI API 协议和模型能力。一个 ComfyUI 供应商通道可同时配置多个命名工作流，每条工作流对应画布中的一个独立模型：

- 文生图工作流
- 图像编辑工作流
- 视频模型工作流（支持 H3 六参考图槽）

两者都支持：

- 按通道直接导入 ComfyUI **界面工作流 JSON**，自动转换为 `/prompt` 所需 API 图；同时兼容已有 API 格式 JSON
- 自定义工作流名称和模型 ID，可同时加入 Pika 加速 H3、普通 H3、Krea2、Moss 等多套工作流
- 每条工作流独立填写实例地址、鉴权 Header 和输入映射
- 通过 JSON 映射绑定 prompt、负面提示词、参考图顺序、尺寸、比例、时长、步数、种子和输出前缀
- `POST /upload/image` 上传参考图
- `POST /prompt` 提交
- `GET /history/{promptId}` 轮询
- `GET /view` 下载图片或视频
- 保存 `promptId` 并通过 `resumeTask` 恢复
- 取消本地等待；可配置是否调用 `/queue` 和 `/interrupt`

Provider 字段：

- `routes`：工作流通道数组，前端通过“ComfyUI 工作流通道”编辑器维护
- 界面工作流中的 `nodes`、`links`、`widgets_values` 会按控件名称转换；Reroute、PrimitiveNode、静音和旁路节点会自动处理
- 子图或缺少控件名称元数据的自定义节点会保留转换提示，需要人工检查映射
- 每条 route 包含 `id`、`label`、`kind`、`workflow`、`mapping`，以及可选的实例地址和鉴权 Header
- 旧版 `imageWorkflow` / `imageMapping` 及 `textToImageWorkflow` 等字段仍可读取，便于兼容已有配置

保存工作流通道后，模型会同步到图片生成、视频生成或音频生成节点的模型列表。

### 本地 ComfyUI

默认地址：`http://127.0.0.1:8188`。

本地调用显示 `¥0（本地）`，仅表示不产生模型 API 调用费；电费和设备折旧不计入。

### 仙宫云 / 优云智算镜像

云端 ComfyUI 支持两种连接方式：

- 平台公网访问地址：把 ComfyUI 端口暴露为平台提供的 HTTP(S) 地址，直接填入 `baseUrl`
- SSH / 本地端口转发：先建立隧道，再填写本地转发地址，例如
  `ssh -L 8188:127.0.0.1:8188 <用户>@<实例地址> -p <端口>`

SSH 是登录 GPU 实例的传输方式，不是 ComfyUI API 的鉴权 Header。Provider 不保存 SSH 密码或私钥。

官方链接：

- 仙宫云获取 API Key / 注册：https://www.xiangongyun.com/register/PNLH4L
- 仙宫云端口说明：https://www.xiangongyun.com/a/ymb72dfxtogn
- 优云智算获取 API Key / 注册：https://passport.compshare.cn/register?referral_code=2UZNw7j4pcEExqFlumDrU
- 优云智算 ComfyUI 镜像：https://www.compshare.cn/image-community?keyword=ComfyUI
- 优云智算软件访问地址 API：https://www.compshare.cn/docs/gpus/instance/getsoftwareurl

云端费用没有可核验金额时显示“未知”，不会回退为 0。提交前必须在模型设置中显式开启“云端费用未知时仍允许提交”。

### H3 六参考图槽

默认映射示例：

```json
{
  "prompt": ["30", "value"],
  "images": [["24", "image"], ["31", "image"], ["39", "image"], ["36", "image"], ["60", "image"], ["59", "image"]],
  "duration": ["15", "value"],
  "steps": ["9", "steps"],
  "seed": ["10", "seed"],
  "ratio": ["14", "aspect_ratio"],
  "prefix": ["4", "filename_prefix"]
}
```

`images` 数组顺序就是参考图上传顺序。缺失的视频槽会使用上传的空图片占位，避免 ComfyUI 缓存复用旧图。

## RunningHub

显示名为 `RunningHub`，使用官方站点图标。Provider **只保留 AI App 接入**，不再提供 Workflow 分支：

- 提交：`POST /task/openapi/ai-app/run`
- 使用数字 `webappId` / `appId`
- 一个 RunningHub 通道可配置多个 AI App
- 每个 App 只需设置自定义名称、媒体类型和 `webappId / appId`
- 生成时自动调用官方 `GET /api/webapp/apiCallDemo` 获取字段列表，自动填充提示词和参考图，无需用户填写 JSON
- 支持图片、视频和音频 AI App 模型

获取 API Key：

- 国内站：https://www.runninghub.cn?inviteCode=cn-v1122
- 国际站（宽审核）：https://www.runninghub.ai/zh-cn?inviteCode=rh-v1727

Provider 支持 API Key、`.cn` / `.ai` 站点、多个 AI App ID、`nodeInfoList`、参考图上传、任务轮询、输出下载、失败原因映射、保存任务 ID 和恢复查询。RunningHub 未提供可核验的公开估价时显示“未知”；`allowUnknownCostSubmit` 默认关闭。余额通过只读接口 `POST /uc/openapi/accountStatus` 查询，不使用提交接口做连通性测试。

### RunningHub 闭源模型

“RunningHub 闭源模型”是独立的内置媒体供应商，与上述工作流通道分开配置。当前预置四个模型：

- `Seedance 2.5 Flash`：文生视频、首帧/首尾帧图生视频、多模态参考；480p/720p。
- `Seedance 2.5`：文生视频、首帧/首尾帧图生视频、多模态参考；支持原生 1080p 及超分档。
- `Seedance 2.0`：文生视频、首帧/首尾帧图生视频、多模态参考；4–15 秒。
- `GPT Image 2.6 Flare（AI 站低价版）`：文生图和最多 16 张参考图的图像编辑，仅通过 `.ai` 站调用。

视频站点可在国内站（zh / `.cn`）和国际站（宽审核 / `.ai`）之间切换；该站点同时决定 API Key 和视频请求域名。GPT Image 2.6 图像模型固定使用 AI 站，若视频站点设为国内站会明确拒绝图片提交。参考图、视频和音频先通过 `/openapi/v2/media/upload/binary` 上传，再按生成模式调用文生、图生或多模态端点，并用 `/openapi/v2/query` 轮询、下载和恢复任务。未返回可核验估价时显示“未知”，真实提交前必须由用户显式开启“费用未知时仍允许提交”。

## 真真 AI

真真 AI 源码仍保留，可用于手动导入：

- 真真图片 G v2.6（低价版）
- Muse Video
- MiniMax H3 ComfyUI Max

它支持 `/v1/files/upload`、`estimate`、异步提交、轮询、产物下载、usage 记录和 `taskId` 恢复。每个模型都要求配置 CNY 单任务上限；报价缺失或超限时禁止提交。

## 文本模型供应商

当前默认文本模型入口直接列在“设置 → 文本模型”中：

- OpenCode Go（Token Plan）
- Command Code（Token Plan）
- DeepSeek

OpenCode Go、Command Code 和 DeepSeek 统一使用 OpenAI Chat Completions 兼容协议。已添加的自定义文本供应商也会直接显示在列表中。

“接入本地模型”会预填 `http://127.0.0.1:11434/v1` 等本地 OpenAI 兼容地址，API Key 可留空。支持手动填写模型 ID，也可以通过 `/v1/models` 自动获取模型列表。

## 验证边界

已完成的验证覆盖 Provider 源码解析、TypeScript 类型检查、Web/Server 构建、ComfyUI JSON 导入与映射保存，以及不产生费用的协议映射检查。RunningHub 国内站与国际站的闭源端点已通过无 API Key 请求确认路由存在；没有执行真实付费生成任务。真实 RunningHub、真真 AI 或云端 ComfyUI 提交仍需用户提供凭据并明确确认费用。

## 旧项目导入

```powershell
python migration/import-solodrama-project.py `
  --source "D:\path\to\legacy-solodrama-workspace" `
  --output "D:\path\to\new-solodrama-workspace"
```

可选参数：`--layout`、`--pack`、`--canvas-name`、`--dry-run`。导入器读取旧项目 layout、pack、剧本、分镜、资产、分镜图和成片，生成原生 `solodramaCanvas`、文本/图片/视频节点及参考图连线。只做单向导入，不与旧系统同步。

## 创作插件

“设置 → 插件管理”内置以下创作工具：

- **剪映草稿**：逐集或整季生成剪映草稿目录，包含视频轨、逐镜配音轨和可选旁白/BGM 轨。
- **流水线出片模式**：扫描真实分镜视频，统一规格后串联；支持逐镜外部配音、整段旁白及 BGM。
- **封面设计**：使用已有底图或图片模型生成竖屏封面并叠加标题。
- **项目预算管理**：在当前项目 `.solodrama/budget.json` 中记录预算、真实成本和未知费用。

剪映草稿格式受剪映版本影响，必须在用户实际安装的剪映版本中验证导入结果。
