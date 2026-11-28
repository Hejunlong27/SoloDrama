# SoloDrama Launcher 技术栈与生命周期审计

> 审计日期：2026-11-27

## 现有技术栈

- 桌面框架：Electrobun 2.0.5 + Hutch。
- 主进程运行时：Bun。
- 业务后端：Bun + Express。
- 前端：Vue 3 + Vite + Element Plus + Pinia + Vue Router。
- 数据：本地文件工作区 + 可选多租户 SQLite/MySQL。
- 媒体任务：`mediaTasks` 内存索引 + 原子 JSON 持久记录。
- 云端 ComfyUI：Cloud Hub + 统一 Provider + 现有 Task Runtime。
- 日志：桌面 `console` 包装写入 `app.log`。

## 当前启动链

```text
用户双击桌面图标
  -> Electrobun 原生启动器 / startupLauncher
  -> apps/desktop/src/bootstrap.ts
  -> 初始化 app.log
  -> apps/desktop/src/index.ts
  -> 显示原生启动画面
  -> createApp()
  -> createDesktopConnection()
  -> BrowserWindow
  -> Web 页面 notifyDesktopReady()
  -> 关闭启动画面，进入主界面
```

## 已有能力

- 自动启动本地服务。
- 自动选择本地监听端口。
- WebView 健康进入。
- 原生启动动画。
- 启动失败日志。
- 主窗口关闭时停止 Server、MCP、浏览器和连接。
- Windows NSIS 安装器、桌面快捷方式、协议注册、更新器和卸载器。
- 安装器检查同一安装目录的进程。
- 更新失败核验和数据保留逻辑。
- 本地 ComfyUI 不是启动条件。

## 缺口

- 没有正式 Launcher 控制中心页面。
- 没有首次启动数据目录向导。
- 没有启动设置持久化。
- 没有数据/日志与程序文件的明确分域。
- 日志写入前未统一脱敏。
- 启动失败只有日志和进程退出提示，缺少完整可见诊断。
- 没有独立 Launcher 状态 API。
- 系统托盘 API 在本次环境中的 Electrobun SDK 未成功投影，无法进行真实托盘实现和验证。
- 桌面 typecheck 和安装包构建受 `.hutch` SDK/工具链阻塞。

## 选型结论

继续使用 Electrobun，不引入 Electron/Tauri：

- 当前已有完整桌面生命周期。
- 已有安装包和更新器链路。
- 新框架会重复服务启动、WebView、更新、协议和卸载实现。
- Launcher 应作为现有桌面的启动状态层和控制中心，而不是第二套应用。

## 数据保护改动

新安装默认：

```text
程序：安装目录
用户数据：<AppData>/SoloDrama/data
日志：<AppData>/SoloDrama/logs
```

已有用户在安装目录 `data/` 有旧配置或工作区时继续使用旧目录，避免升级迁移导致数据失联。

卸载器只有在用户明确勾选“同时删除用户数据”时才删除：

- 旧安装目录 `data/`
- `<AppData>/SoloDrama/data`
- `<AppData>/SoloDrama/logs`

## 影响范围

- `apps/desktop/src/bootstrap.ts`
- `apps/desktop/src/index.ts`
- `apps/desktop/installer/installer.nsi`
- `apps/server/src/types/desktop.ts`
- `apps/server/src/routes/desktop/launcher/`
- `apps/web/src/router/index.ts`
- `apps/web/src/pages/launcher/index.vue`
- `apps/web/src/pages/workspace/components/workspaceMenu.vue`
- `apps/web/src/pages/workspace/index.vue`
- `apps/web/src/stores/desktopUpdate.ts`