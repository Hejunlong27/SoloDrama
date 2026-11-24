# SoloDrama 文档目录

[返回项目首页](../README.md)

## 核心文档

- [Provider 接入说明](./SOLODRAMA-PROVIDERS.md)：ComfyUI、RunningHub、优云智算、TTS、文本模型和费用安全边界。
- [Prompt Skills、导演 Skill 与 TTS](./promptSkillsAndTts.md)：提示词增强、角色四视图、角色设定卡和 TTS 媒体模型。
- [SoloDrama 基线说明](./SOLODRAMA.md)：当前主干基线、品牌边界、端口和发行更新配置。
- [开发与扩展指南](./development.md)：源码运行、插件扩展、桌面打包和发布流程。
- [旧项目导入工具](../migration/import-solodrama-project.py)：将旧 SoloDrama 创作包单向导入为原生画布工作区。

## 项目协作

- [开发规范](../AGENTS.md)
- [MCP 接入说明](../packages/mcp/README.md)
- [多语言维护说明](../packages/i18n/readme.md)
- [多语言回归记录](../packages/i18n/regression.md)

## 目录约定

```text
docs/
  readme.md                 文档入口
  SOLODRAMA.md              主干基线与运行说明
  SOLODRAMA-PROVIDERS.md    模型和 Provider 接入
  promptSkillsAndTts.md     Prompt Skill、导演 Skill 与 TTS
  development.md            通用开发与打包说明
```

各子包的实现和维护说明保留在对应的 `packages/` 目录。SoloDrama 后续开发以根目录 [README.md](../README.md) 和当前仓库代码为准。
