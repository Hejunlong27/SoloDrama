# SoloDrama

## 项目定位

SoloDrama 是面向竖屏短剧、漫剧和连续内容生产的本地 AI 创作平台。项目把剧本、设定、资产、分镜、画布、图片生成、视频生成、配音、剪辑和发行准备放在同一个工作区中。

## 核心能力

- 项目工作台：按剧本、设定、分镜、成片组织项目内容，并与画布共享同一份数据。
- 无限画布：文本、图片、视频、音频、3D 导演台和生成节点可以组合连线。
- 媒体模型：本地 ComfyUI、自定义云端 ComfyUI、RunningHub、优云智算、TTS 和多模型通道。
- 文本模型：OpenAI Chat Completions 兼容接口，支持 OpenCode、Command Code、DeepSeek、自定义服务和本地模型。
- Agent 与 Skills：读取项目上下文，支持全局技能、工作区技能和导演约束。
- 创作插件：项目预算、剪映草稿、封面设计、流水线出片、工作区文件和联网搜索。
- 旧项目导入：读取旧 SoloDrama 工作区并生成当前版本的画布、资产和节点。

## 技术结构

- Bun 1.4.3 Workspaces
- Vue 3、Vite、TypeScript、Pinia、Element Plus、Vue Flow
- Bun、Express、Zod
- Electron/Electrobun 桌面启动与安装结构
- Pi Agent、插件式 Tools、Markdown Skills
- FFmpeg、ComfyUI 和可扩展媒体 Provider

## 运行

环境要求：

- Bun 1.4.3
- 可选 FFmpeg，用于音频拼接、视频处理和流水线出片

```powershell
bun install --frozen-lockfile
bun run build:server
bun run start:server
```

默认访问地址：

```text
http://127.0.0.1:3000
```

## 数据目录

- `data/workspaces/`：用户工作区
- `data/nodes/`、`data/tools/`、`data/skills/`：本地插件和技能
- `data/providers/`：自定义媒体 Provider
- 构建产物位于 `build/`，不进入 Git

Provider、插件和模型配置以项目实际界面为准。付费媒体提交前会展示当前可获得的报价；供应商没有返回可核验金额时显示“未知”，不会回退为 0。
