import { createToolConfig } from "@solodrama/tools-scaffold";

await createToolConfig({
  name: "coverDesign",
  displayName: "封面设计",
  description: "使用已有图片或图片模型生成竖屏短剧封面底图，再叠加标题、副标题和暗色压字层，输出 PNG 封面。",
  author: "SoloDrama",
  github: "",
  prompt: `封面设计必须使用真实图片或调用用户指定的图片模型生成底图，不伪造素材。标题和副标题由用户确定；画幅、画风、字体、安全区、描边和阴影优先继承项目 .solodrama/project.json。
调用图片模型会产生费用；提交前先核对报价和项目预算，未确认不得生成。输出使用新文件名。`,
  configRules: [
    { type: "input", field: "fontPath", title: "中文字体文件（可选）", value: "C:/Windows/Fonts/msyhbd.ttc" },
    { type: "inputNumber", field: "width", title: "封面宽度", value: 1080, props: { min: 240, max: 7680, step: 2 } },
    { type: "inputNumber", field: "height", title: "封面高度", value: 1920, props: { min: 240, max: 7680, step: 2 } },
    { type: "select", field: "style", title: "默认风格", value: "suspense", options: [
      { label: "强冲突悬疑", value: "suspense" },
      { label: "情绪特写", value: "emotion" },
      { label: "都市逆袭", value: "urban" },
      { label: "古风权谋", value: "costume" },
    ] },
    { type: "select", field: "textPosition", title: "标题位置", value: "bottom", options: [
      { label: "顶部", value: "top" }, { label: "中部", value: "center" }, { label: "底部", value: "bottom" },
    ] },
    { type: "inputNumber", field: "safeArea", title: "安全区比例", value: 0.12, props: { min: 0, max: 0.35, step: 0.01 } },
    { type: "inputNumber", field: "outline", title: "文字描边", value: 3, props: { min: 0, max: 20, step: 1 } },
    { type: "inputNumber", field: "shadow", title: "文字阴影", value: 2, props: { min: 0, max: 20, step: 1 } },
  ],
}, import.meta.url);
