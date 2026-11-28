# SoloDrama Launcher 使用指南

## 结论

SoloDrama 的桌面启动器复用现有 Electrobun 应用，不另起 Electron/Tauri 壳。

用户双击 SoloDrama 后：

1. 显示原生启动动画。
2. 读取本地设置。
3. 在同一进程创建 Express 应用。
4. 自动创建本地监听端口。
5. 启动桌面连接与必要本地服务。
6. 创建 WebView。
7. 页面 ready 后关闭启动动画。
8. 自动进入 SoloDrama 主界面。

本地 ComfyUI 不是启动条件；只使用云端 ComfyUI 时也可以正常启动。

## 数据位置

- Windows/macOS：安装目录下的 `data/`
- Linux：XDG 应用数据目录下的 `solodrama/data/`
- 可用 `SOLODRAMA_DATA_DIR` 显式覆盖开发模式数据目录。

升级不得覆盖或删除：

- 项目工作区。
- 工作流。
- Provider 配置。
- `data/comfyHub/instances.json`
- `data/comfyHub/workflows.json`
- `data/comfyHub/secret.key`
- `data/settings.json`

## 日志

Windows 日志写入桌面进程工作目录下的 `app.log`。

启动失败时会显示错误弹窗，并提示日志文件位置。

日志会记录：

- 桌面进程版本和平台。
- Server/WebView 初始化错误。
- 设备连接错误。
- MCP 清理错误。
- 启动失败原因。

## 关闭行为

关闭主窗口时：

- 停止桌面连接。
- 停止多租户运行时。
- 停止 MCP。
- 关闭浏览器实例。
- 关闭本地 Server 监听。
- 清理启动画面。

不会按 PID 或路径误杀其他 SoloDrama 用户进程。

## 重复启动和端口

- 桌面 WebView 连接的是 Server 实际监听端口。
- Server 以动态本地端口启动，避免默认端口冲突。
- 多租户公开创作入口使用固定 `10888`；状态变化时单独报告监听错误。
- 桌面运行时记录包含 PID 和端口，供协议启动器判断旧记录是否已失效。

## 开发命令

```powershell
bun run dev:desktop
```

## 生产构建

```powershell
bun run build
bun run build:desktop
```

安装包输出目录由 Electrobun 配置决定：

```text
build/desktop/artifacts/
```

Windows x64 目标目录：

```text
build/desktop/artifacts/windows-x64/
```

## 当前环境阻塞

本次实际执行 `bun run build:desktop` 时，Electrobun/Hutch 引导因运行时工具链下载失败而停止：

- 缺少 `.hutch/dependencies.lock`。
- Hutch 0.30.0 已下载。
- Bun 1.4.4 工具链下载返回 `CertificateBundleLoadFailure`。

因此本次未生成新的桌面安装包。不是桌面应用代码编译错误，也不是 SoloDrama Server/Web 构建错误。

修复方向：

1. 在可正常访问 Hutch/Electrobun 发布源的构建机运行 Hutch 引导。
2. 生成 `.hutch/dependencies.lock` 和 SDK。
3. 提供或缓存 Bun 1.4.4 对应平台工具链。
4. 再执行：
   - `bun run build:desktop`
   - `bun run package:desktop`

不得通过关闭 TLS 校验或修改运行时校验清单绕过。