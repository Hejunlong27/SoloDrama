import { createToolConfig } from "@solodrama/tools-scaffold";

await createToolConfig({
  name: "projectBudget",
  displayName: "项目预算管理",
  description: "按当前项目记录预算、实际成本、供应商、模型和任务 ID，汇总剩余额度与消耗比例。",
  author: "SoloDrama",
  github: "",
  prompt: `预算文件固定保存在当前工作区的 .solodrama/budget.json。每次付费生成前先调用 projectBudget 的 summary 检查剩余额度；供应商没有返回金额时如实记为“未知”，不得按 0 记账。
record 只记录真实可核验金额；setBudget 修改项目总预算；removeEntry 只删除用户明确要求删除的一笔记录。金额单位必须一致，默认 CNY。`,
  configRules: [
    { type: "input", field: "currency", title: "默认币种", value: "CNY" },
    { type: "inputNumber", field: "warnPercent", title: "预警阈值（%）", value: 80, props: { min: 1, max: 100, step: 1 } },
  ],
}, import.meta.url);