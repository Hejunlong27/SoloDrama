# 工作流导入与同步指南

## 支持格式

- ComfyUI 界面导出的 UI Workflow JSON（包含 `nodes` 和 `links`）。
- ComfyUI API Prompt JSON（节点键映射到 `class_type` 和 `inputs`）。

导入时自动识别格式。UI Workflow 会转换为 API Prompt，同时保留原始来源 JSON。

## 本地导入

1. 进入“云端算力中心 → 工作流库”。
2. 点击“导入工作流”。
3. 来源选择“本地 JSON”。
4. 粘贴完整 JSON。
5. 填写名称、媒体类型、分类和说明。
6. 填写参数映射 JSON。
7. 保存。

## HTTP 导入

1. 来源选择“HTTP 地址”。
2. 填写可直接返回 JSON 的 HTTP/HTTPS 地址。
3. 保存后自动下载并解析。
4. 在卡片上点击“同步来源”可创建新版本。

## Git 来源

1. 来源选择“Git 仓库”。
2. 填写 HTTPS Git 地址。
3. 填写仓库内 JSON 文件路径，例如 `workflows/image.json`。
4. 可选填写分支。
5. 保存后服务器执行受限浅克隆并读取指定文件。
6. 后续点击“同步来源”可创建新版本。

限制：

- 只接受 HTTPS。
- 不接受仓库外路径。
- 临时仓库读取后清理。
- 不执行仓库内脚本。

## S3 兼容来源

当前支持 S3 兼容公开对象或预签名 URL。选择“S3 兼容预签名 URL”并填写 HTTPS URL。

尚未实现：

- AWS SigV4 Access Key/Secret 直连。
- Bucket 列表浏览。
- 凭证式 S3 SDK 客户端。

## 参数映射

示例：

```json
{
  "prompt": ["30", "value"],
  "negativePrompt": ["31", "value"],
  "images": [["24", "image"], ["31", "image"]],
  "duration": ["15", "value"],
  "steps": ["9", "steps"],
  "seed": ["10", "seed"],
  "ratio": ["14", "aspect_ratio"],
  "prefix": ["4", "filename_prefix"]
}
```

支持参数：

- 正向提示词。
- 反向提示词。
- 输入图片。
- 宽高/尺寸。
- 画面比例。
- 时长。
- Steps。
- Seed。
- 输出前缀。
- `extra` 自定义参数。

## 版本

- 首次保存为 v1。
- 更新工作流自动递增版本。
- 保留最近 20 个版本。
- 历史任务 ProviderTaskData 中的 promptId 仍可用于恢复。
- 手动更新和来源同步都会创建新版本，不静默覆盖当前工作流。

## 能力与兼容检测

工作流保存时会从 API Prompt 提取节点类型。点击“兼容检测”会：

1. 探测指定实例。
2. 读取 `/object_info`。
3. 报告缺失节点。
4. 报告显式声明的缺失模型。

标准 ComfyUI API 不能可靠枚举所有已安装模型，因此：

- 没有声明必需模型时，不宣称模型已安装。
- 声明必需模型时，当前版本会阻止执行并提示用户确认模型依赖。

## 使用工作流生成

保存后的工作流会出现在现有图片、视频或音频生成节点的媒体模型列表中，Provider 为“云端 ComfyUI”。

可配置自动实例或通过任务请求的 `instanceId` 手动指定实例。

## 失败恢复

- 提交成功后保存 promptId、instanceId 和实例地址。
- WebSocket 断开时继续 HTTP 查询。
- 不重复提交结果未知的任务。
- 实例被删除后，历史任务恢复会明确报错，不会转而提交到另一实例。