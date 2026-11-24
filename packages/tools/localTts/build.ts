import { createToolConfig } from "@solodrama/tools-scaffold";

await createToolConfig({
  name: "localTts",
  displayName: "本地 TTS",
  description: "调用本地 OpenAI 兼容语音接口或本地 TTS 命令生成配音，并生成可交给剪映草稿和流水线插件使用的粗剪清单。",
  author: "SoloDrama",
  github: "",
  prompt: `本地 TTS 支持两种模式：http 调用 OpenAI 兼容 /v1/audio/speech；command 调用本机 TTS 程序。
默认音色、语速、语言和采样率会优先继承项目 .solodrama/project.json；角色音色映射用于逐角色批量配音。
命令参数 JSON 是可执行参数数组，可用 {text}、{output}、{voice}、{speed}、{language}、{format}、{sampleRate}、{volume}、{instructions} 占位符；禁止 shell 字符串拼接。
生成音频后必须检查工作区文件真实存在。synthesizeDialogue 输出带真实时长的时间轴清单；createVoiceRoughCut 只生成粗剪清单，不伪造已合成视频。`,
  configRules: [
    { type: "select", field: "mode", title: "调用模式", value: "http", options: [{ label: "本地 HTTP 接口", value: "http" }, { label: "本地命令", value: "command" }] },
    { type: "input", field: "endpoint", title: "语音接口地址", value: "http://127.0.0.1:8880/v1/audio/speech" },
    { type: "input", field: "apiKey", title: "API Key（本地可留空）", value: "", props: { type: "password", showPassword: true, autocomplete: "off" } },
    { type: "input", field: "model", title: "模型名称", value: "local-tts" },
    { type: "input", field: "command", title: "本地 TTS 命令", value: "" },
    { type: "textarea", field: "argsJson", title: "命令参数 JSON", value: "[\"--text\", \"{text}\", \"--output\", \"{output}\"]", props: { rows: 4 } },
    { type: "input", field: "defaultVoice", title: "默认音色（留空继承项目）", value: "" },
    { type: "select", field: "format", title: "默认格式", value: "mp3", options: [{ label: "MP3", value: "mp3" }, { label: "WAV", value: "wav" }] },
    { type: "input", field: "language", title: "默认语言（留空继承项目）", value: "" },
    { type: "inputNumber", field: "sampleRate", title: "采样率", value: 44100, props: { min: 8000, max: 192000, step: 1000 } },
    { type: "inputNumber", field: "volume", title: "默认增益（dB）", value: 0, props: { min: -30, max: 30, step: 0.5 } },
    { type: "switch", field: "normalize", title: "响度标准化", value: false },
    { type: "textarea", field: "characterVoicesJson", title: "角色音色映射 JSON", value: "{}", props: { rows: 4 } },
  ],
}, import.meta.url);
