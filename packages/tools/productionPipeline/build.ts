import { createToolConfig } from "@solodrama/tools-scaffold";

await createToolConfig({
  name: "productionPipeline",
  displayName: "流水线出片模式",
  description: "扫描工作区分镜视频或读取粗剪清单，将多个镜头规范化后合成为成片；支持镜头原声、旁白、BGM、字幕烧录和封面片头。",
  author: "SoloDrama",
  github: "",
  prompt: `流水线出片只在用户明确要求生成成片时使用。先 inspect 或读取粗剪清单确认真实视频路径，再 render。
画幅、分辨率、帧率、BGM 和画风规格优先继承项目 .solodrama/project.json；调用参数可以覆盖。audioMode 支持 clip（镜头原声）、narration（旁白替换）、mix（原声+旁白）和 none。
render 会统一分辨率、帧率和像素格式后串联合成，不会修改源文件。可加入封面、BGM 和 SRT/ASS 字幕烧录；没有可用音频时不得声称已自动配音。
输出使用新文件名，除非用户明确要求覆盖。生成后检查文件真实存在。`,
  configRules: [
    { type: "inputNumber", field: "width", title: "默认宽度", value: 1080, props: { min: 240, max: 7680, step: 2 } },
    { type: "inputNumber", field: "height", title: "默认高度", value: 1920, props: { min: 240, max: 7680, step: 2 } },
    { type: "inputNumber", field: "fps", title: "默认帧率", value: 30, props: { min: 1, max: 120, step: 1 } },
    { type: "input", field: "outputDirectory", title: "默认成片目录", value: "09-发行/剧集" },
    { type: "input", field: "bgmPath", title: "默认 BGM 路径（可留空）", value: "" },
    { type: "inputNumber", field: "bgmVolume", title: "BGM 音量（0-2）", value: 0.18, props: { min: 0, max: 2, step: 0.01 } },
  ],
}, import.meta.url);
