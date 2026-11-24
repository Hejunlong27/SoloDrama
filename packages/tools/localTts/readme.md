# 本地 TTS

在插件配置中选择本地 HTTP 接口或本地命令：

- HTTP：默认调用 OpenAI 兼容 `POST /v1/audio/speech`，请求体包含 `model`、`input`、`voice`、`response_format`、`speed`。
- 命令：配置可执行文件与参数 JSON，支持 `{text}`、`{output}`、`{voice}`、`{speed}`、`{language}` 占位符。
- 项目默认：音色、语速、语言、格式和采样率优先继承 `.solodrama/project.json`，插件配置可覆盖。
- 声音处理：支持采样率转换、dB 增益和响度标准化；角色音色可通过 JSON 映射。

`synthesizeDialogue` 会按角色批量生成台词音频，并用 FFprobe 真实时长生成 `dialogue.json` 时间轴。`createVoiceRoughCut` 再把分镜视频和音频整理成 `.solodrama/roughCut/<名称>/manifest.json`，可直接交给“剪映草稿”或“流水线出片模式”。
