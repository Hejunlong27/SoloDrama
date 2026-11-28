# 云端 ComfyUI 连接指南

## 适用范围

只要实例提供标准 ComfyUI HTTP/WebSocket API，就可以通过同一套配置接入。平台名称只用于区分实例，不会触发平台专属工作流代码。

## 添加实例

1. 打开 SoloDrama 设置。
2. 进入“云端算力中心”。
3. 点击“添加实例”。
4. 填写实例名称和平台标签。
5. 填写 ComfyUI API 根地址，例如：
   - `https://comfy.example.com`
   - `https://gpu.example.com/comfyui`
   - `http://192.168.1.20:8188`（必须显式允许局域网）
6. 选择鉴权：
   - 无鉴权。
   - Bearer Token。
   - 自定义 Header。
7. 如有需要填写自定义 Header JSON。
8. 点击“保存”。
9. 点击“测试连接”。

## 测试内容

测试会检查：

- `/system_stats`
- `/object_info`
- `/queue`
- `/features`
- `/ws`

页面显示：

- 在线/可用降级/离线。
- 延迟。
- ComfyUI 版本。
- 节点数量。
- 运行和排队任务数。
- WebSocket 是否可用。

## 地址和认证

- URL 不得内嵌用户名密码。
- Token 保存后不会通过列表接口返回。
- 编辑实例时 Token 输入框留空表示保留原 Token。
- 关闭鉴权或输入空 Token 保存会清除原凭据。
- 自定义 Header 的敏感值同样加密保存。

## 本机与局域网

默认禁止本机、内网和保留地址。需要连接本地或局域网 ComfyUI 时，必须勾选“允许本机/局域网地址”。

即使勾选，以下地址仍被拒绝：

- IPv4 链路本地：`169.254.0.0/16`
- IPv6 链路本地：`fe80::/10`
- 已知云元数据主机名
- URL 内嵌账号密码

## WebSocket 与 HTTP 回退

- WebSocket 可用时用于快速接收执行事件。
- 最终成功和输出仍通过 `/history/{prompt_id}` 核验。
- WebSocket 不可用或断开时自动回退 HTTP 轮询。
- WebSocket 失败不会单独判定实例不可用，但健康状态会显示为“可用（降级）”。

## 取消规则

- 排队任务按 prompt_id 精确删除。
- 运行中任务只在实例提供经过验证的任务级取消能力时才能远端中断。
- 当前通用 Connector 不会发送无 prompt_id 的全局 `/interrupt`。

## 常见错误

### 鉴权失败

检查 Bearer Token、Header 名称和 Header 值。

### 接口不存在

确认地址指向 ComfyUI 根地址；不要把云平台控制台 API 地址当作 ComfyUI API。

### 本机/局域网地址被拒绝

在实例配置中勾选允许私有网络，并确认地址不是链路本地或云元数据地址。

### 实例离线但云端控制台显示运行中

检查：

- ComfyUI 服务是否已启动。
- 端口是否已暴露。
- 反向代理是否支持 HTTP 和 WebSocket。
- 实例安全组是否允许当前网络。