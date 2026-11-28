# SoloDrama Launcher 验收报告

> 验收日期：2026-11-27  
> 范围：Launcher 路由、首次启动向导、运行控制中心、真实状态 API、日志脱敏、启动设置、数据/日志分域、Electrobun 生命周期、桌面构建。

## 1. 结论

Launcher 产品代码和控制中心已实现，并通过 Web/Server 类型检查、生产构建和隔离 API 探针。

但桌面安装包和双击启动没有完成真实验证，原因是本机构建环境无法完成 Electrobun/Hutch 工具链准备：

- `.hutch/dependencies.lock` 缺失。
- Hutch 引导下载 Bun 1.4.4 时返回 `CertificateBundleLoadFailure`。
- `bun run build:desktop` 在运行时准备阶段失败。

因此：

- 没有生成新的桌面安装包。
- 没有可报告的实际双击启动成功结果。
- 没有将系统托盘做成静态假界面。

## 2. 实际运行命令

| 命令 | 结果 |
|---|---|
| `bun run --cwd apps/server typecheck` | 通过 |
| `bun run --cwd apps/web typecheck` | 通过 |
| `bun run build` | 通过 |
| `bun run build:desktop` | 失败：缺少 `.hutch/dependencies.lock` |
| `bunx electrobun --help` / Hutch 引导 | 失败：Bun 1.4.4 工具链 `CertificateBundleLoadFailure` |
| `bun test` | 失败：`No tests found!` |
| `bun run lint` | 失败：没有 lint 脚本 |
| `bun run typecheck` | 失败：仅 `@solodrama/desktop` 因 Electrobun SDK 类型缺失；其他已输出包通过 |
| `git diff --check` | 通过，仅有 LF/CRLF 提示 |
| Launcher API 临时探针 | 通过 |
| 日志脱敏临时探针 | 通过 |
| Launcher 设置持久化探针 | 通过 |

## 3. 已实现功能

### 启动流程

- 正常启动保留现有原生启动动画。
- Server/WebView 就绪后自动进入工作台。
- 首次启动进入 `/launcher` 向导。
- `launcherOnboarded=true` 后普通启动不再显示完整控制中心。
- 设置 `autoOpenWorkspace=false` 时，后续启动停留在控制中心。
- 启动失败弹窗显示错误和日志路径。

### 控制中心

- 运行概览。
- 本地服务状态。
- 云端连接数量。
- 统一任务概况。
- 运行日志。
- 启动设置。
- 关于 SoloDrama。
- 进入工作台。
- 退出应用。
- 打开日志目录。
- 打开项目数据目录。
- 导出诊断 JSON。

### 真实状态 API

`GET /api/desktop/launcher/status` 返回：

- 应用版本、PID、平台、架构。
- 数据目录和日志目录。
- 后端和前端健康状态。
- 数据目录可访问状态。
- 数据库配置状态。
- 本地/局域网 ComfyUI 配置状态。
- 云端实例在线/离线数量。
- Hub 任务运行中和待恢复数量。

不使用虚假步骤计时。

### 日志

- 日志写入位置独立于程序文件。
- 写入时对 Token、Authorization、Cookie、URL 查询参数和敏感字段脱敏。
- 读取 API 再次脱敏。
- 前端支持搜索、级别筛选、复制和导出诊断。

### 设置

- 启动后自动进入工作台。
- 启动时检查更新。
- Windows 当前用户开机自启动。
- 数据和日志目录查看/打开。

### 数据保护

新安装：

- 程序：安装目录。
- 数据：系统 AppData 下的 `SoloDrama/data`。
- 日志：系统 AppData 下的 `SoloDrama/logs`。

已有旧数据：

- 如果安装目录已有 `data/settings.json` 或 `data/workspaces`，继续使用旧目录，避免升级后丢失项目。

卸载：

- 只有用户明确勾选“同时删除用户数据”时才删除旧 `INSTDIR\data`、新 `APPDATA\SoloDrama\data` 和日志目录。

### 云端任务策略

- Launcher 只读取任务状态。
- Launcher 不取消、不接管、不删除云端任务。
- 应用退出只关闭本地连接与服务。
- 已提交任务由现有 `mediaTasks`、ProviderTaskData 和上游 promptId 持久保存。
- 下次启动后可继续恢复和核实。

## 4. Launcher API 实测

隔离 Express + 临时桌面运行时探针结果：

```json
{
  "statusCode": 200,
  "version": "2.1.0",
  "logCode": 200,
  "logs": ["[2026-11-27] [error] authorization=•••••• ••••••"],
  "settings": [
    200,
    {
      "launcherOnboarded": true,
      "autoOpenWorkspace": false,
      "checkUpdatesOnStartup": false,
      "launchOnStartup": true
    }
  ]
}
```

验证：

- 状态 API 返回真实运行时信息。
- 日志中的 Bearer Token 和查询 Token 均被脱敏。
- 启动设置保存成功。
- 开机自启动调用由桌面 runtime 实现，探针使用受控 stub 验证调用链。

## 5. 未完成和阻塞

### P1

1. 桌面安装包未生成
   - 阻塞：Hutch SDK 和 Bun 1.4.4 工具链不可用。
   - 结果：无法验证安装、桌面快捷方式和双击启动。

2. 系统托盘未实现
   - 当前 Electrobun SDK 未成功投影，无法确认托盘 API。
   - 没有添加空托盘按钮或假“最小化到托盘”设置。

3. 桌面 typecheck 未通过
   - `electrobun/main` 类型由 `.hutch/devkit/api/sdks/main` 提供。
   - 当前 SDK 缺失。

4. 无自动化测试和 Lint
   - 仓库规范禁止新增测试文件。
   - 根 `package.json` 没有 lint 脚本。

### P2

1. 首次向导暂不支持应用内切换数据目录；可使用 `SOLODRAMA_DATA_DIR`。
2. 关闭窗口行为没有托盘模式，当前仍按原桌面生命周期退出。
3. 本地服务重启按钮未实现；当前 Server 与桌面主进程同生命周期。
4. 开机自启动只验证了 Windows 注册调用链，未在安装包上实际验证。
5. Launcher UI 未进行真实桌面截图验收。

## 6. 需要人工验证

- 在可正常下载 Hutch/Electrobun SDK 的机器生成 `.hutch/dependencies.lock`。
- 提供 Bun 1.4.4 工具链缓存。
- 执行 `bun run build:desktop`。
- 执行 `bun run package:desktop`。
- 验证安装包、桌面快捷方式和开始菜单入口。
- 双击启动实际进入工作台。
- 连续双击不产生多份核心服务。
- 端口冲突诊断。
- 启动失败日志和错误弹窗。
- 无本地 ComfyUI、无云端实例时启动。
- 首次启动向导。
- 自动进入工作台设置。
- 日志搜索、复制、导出。
- 升级后数据、工作流、Provider Token 和项目保留。
- Windows 开机自启动。
- 系统托盘和关闭到托盘需要 SDK 可用后补齐。

## 7. 预期安装包位置

当前不存在新安装包。

预期 Windows x64 输出目录：

```text
D:\编程\SoloDrama\build\desktop\artifacts\windows-x64\
```

在 Hutch 工具链问题解决前，该目录不能作为已交付产物。