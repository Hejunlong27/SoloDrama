import { createToolConfig } from "@solodrama/tools-scaffold";

await createToolConfig({
  name: "jianyingDraft",
  displayName: "剪映草稿",
  description: "把项目分镜视频、配音、字幕、封面和 BGM 整理为剪映可导入的草稿目录，支持逐集草稿和全季单份草稿。",
  author: "SoloDrama",
  github: "",
  prompt: `生成剪映草稿前先确认真实视频、音频和字幕文件路径。episode 模式为每集生成独立草稿；season 模式把整季镜头按顺序放入同一草稿。
画布尺寸、帧率、字幕、封面、BGM 和音量优先继承项目 .solodrama/project.json，调用参数可以覆盖。clip.subtitlePath 支持 SRT；clip.coverPath 会生成首帧封面图轨。
草稿目录写入工作区 .solodrama/jianyingDrafts，不能声称剪映一定能在所有版本打开；应提示用户使用实际剪映版本验证。`,
  configRules: [
    { type: "inputNumber", field: "width", title: "画布宽度", value: 1080, props: { min: 240, max: 7680, step: 2 } },
    { type: "inputNumber", field: "height", title: "画布高度", value: 1920, props: { min: 240, max: 7680, step: 2 } },
    { type: "inputNumber", field: "fps", title: "帧率", value: 30, props: { min: 1, max: 120, step: 1 } },
    { type: "input", field: "outputDirectory", title: "草稿输出目录", value: ".solodrama/jianyingDrafts" },
    { type: "switch", field: "includeCover", title: "默认加入封面轨", value: true },
    { type: "switch", field: "includeSubtitles", title: "默认加入字幕轨", value: true },
    { type: "input", field: "bgmPath", title: "默认 BGM 路径（可留空）", value: "" },
    { type: "inputNumber", field: "bgmVolume", title: "BGM 音量（0-2）", value: 0.18, props: { min: 0, max: 2, step: 0.01 } },
    { type: "inputNumber", field: "coverSeconds", title: "封面时长（秒）", value: 0.06, props: { min: 0.01, max: 5, step: 0.01 } },
  ],
}, import.meta.url);
