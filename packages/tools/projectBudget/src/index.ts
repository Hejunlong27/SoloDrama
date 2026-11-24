import { dirname } from "node:path";
import { z } from "zod";
import type { ToolPlugin } from "@solodrama/tools-scaffold/runtime";

const BUDGET_PATH = ".solodrama/budget.json";
const configSchema = z.object({
  currency: z.string().trim().min(1).max(16).default("CNY"),
  warnPercent: z.number().int().min(1).max(100).default(80),
}).strict();
const entrySchema = z.object({
  id: z.string(),
  amount: z.number().finite().nonnegative().nullable(),
  currency: z.string(),
  category: z.string(),
  provider: z.string().optional(),
  model: z.string().optional(),
  taskId: z.string().optional(),
  note: z.string().optional(),
  createdAt: z.string(),
});
const budgetFileSchema = z.object({
  currency: z.string().default("CNY"),
  budget: z.number().finite().nonnegative().nullable().default(null),
  entries: z.array(entrySchema).default([]),
}).passthrough();
type BudgetFile = z.infer<typeof budgetFileSchema>;

const requestSchema = z.strictObject({
  action: z.enum(["summary", "setBudget", "record", "recordUnknown", "removeEntry"]).describe("操作类型"),
  budget: z.number().finite().nonnegative().optional().describe("setBudget 必填，项目总预算"),
  amount: z.number().finite().positive().optional().describe("record 必填，真实成本金额"),
  currency: z.string().trim().min(1).max(16).optional().describe("币种，默认使用插件配置"),
  category: z.string().trim().min(1).max(100).optional().describe("成本类别，例如 image、video、tts、render"),
  provider: z.string().trim().max(200).optional().describe("供应商名称或 ID"),
  model: z.string().trim().max(200).optional().describe("模型名称或 ID"),
  taskId: z.string().trim().max(200).optional().describe("供应商任务 ID"),
  note: z.string().trim().max(2000).optional().describe("备注或任务说明"),
  entryId: z.string().trim().min(1).optional().describe("removeEntry 必填"),
});

function parseBudget(text: string, currency: string): BudgetFile {
  if (!text.trim()) return budgetFileSchema.parse({ currency, budget: null, entries: [] });
  try { return budgetFileSchema.parse(JSON.parse(text)); }
  catch (error) { throw new Error("预算文件格式无效：" + (error instanceof Error ? error.message : String(error))); }
}

async function readBudget(context: Parameters<ToolPlugin["createTools"]>[0], currency: string) {
  const path = await context.resolvePath(BUDGET_PATH);
  const bytes = await context.files.readFile(path).catch((error: NodeJS.ErrnoException) => {
    if (error.code === "ENOENT") return Buffer.from("");
    throw error;
  });
  return { path, data: parseBudget(bytes.toString("utf8"), currency) };
}

async function writeBudget(context: Parameters<ToolPlugin["createTools"]>[0], path: string, data: BudgetFile) {
  await context.files.mkdir(dirname(path), true);
  await context.files.writeFile(path, JSON.stringify(data, null, 2) + "\n");
}

function summary(data: BudgetFile, warnPercent: number) {
  const known = data.entries.filter(entry => entry.amount !== null) as Array<z.infer<typeof entrySchema> & { amount: number }>;
  const unknownCost = data.entries.length - known.length;
  const spent = known.reduce((sum, entry) => sum + entry.amount, 0);
  const remaining = data.budget === null ? null : data.budget - spent;
  const percent = data.budget && data.budget > 0 ? spent / data.budget * 100 : null;
  const byCategory = Object.entries(known.reduce<Record<string, number>>((result, entry) => {
    result[entry.category] = (result[entry.category] ?? 0) + entry.amount;
    return result;
  }, {}));
  return {
    currency: data.currency,
    budget: data.budget,
    spent,
    remaining,
    percent: percent === null ? null : Math.round(percent * 100) / 100,
    warning: percent !== null && percent >= warnPercent,
    unknownCost,
    entries: data.entries.length,
    byCategory: Object.fromEntries(byCategory),
  };
}

const plugin: ToolPlugin = {
  validateConfig: config => configSchema.parse(config),
  createTools(context) {
    const config = configSchema.parse(context.config);
    return [{
      name: "projectBudget",
      label: "项目预算管理",
      description: "读取或修改当前项目预算，记录真实成本与未知成本，统计剩余额度、消耗比例和分类成本。",
      promptSnippet: "项目付费生成前检查预算，任务完成后记录可核验成本；没有返回金额时记录未知，不能写成 0。",
      promptGuidelines: [
        "首次使用先调用 summary。setBudget 已存在时只有用户明确修改预算才覆盖。",
        "record 只接受真实可核验的金额；供应商未返回金额时使用 recordUnknown。",
        "付费提交前把剩余额度和报价一起告知用户；报价超过剩余额度或金额未知时不得擅自提交。",
      ],
      parameters: z.toJSONSchema(requestSchema, { io: "input", target: "draft-07" }),
      async execute(_id, params) {
        const request = requestSchema.parse(params);
        const { path, data } = await readBudget(context, config.currency);
        if (request.action === "summary") {
          return { content: [{ type: "text", text: JSON.stringify(summary(data, config.warnPercent), null, 2) }], details: summary(data, config.warnPercent) };
        }
        if (request.action === "setBudget") {
          if (request.budget === undefined) throw new Error("setBudget 需要 budget");
          data.budget = request.budget;
          if (request.currency) data.currency = request.currency;
          await writeBudget(context, path, data);
          return { content: [{ type: "text", text: `项目预算已设置为 ${data.budget} ${data.currency}` }], details: summary(data, config.warnPercent) };
        }
        if (request.action === "record") {
          if (request.amount === undefined) throw new Error("record 需要 amount");
          const entry = entrySchema.parse({
            id: crypto.randomUUID(), amount: request.amount, currency: request.currency ?? data.currency,
            category: request.category ?? "other", provider: request.provider, model: request.model,
            taskId: request.taskId, note: request.note, createdAt: new Date().toISOString(),
          });
          data.entries.push(entry);
          await writeBudget(context, path, data);
          return { content: [{ type: "text", text: `已记录成本 ${entry.amount} ${entry.currency}` }], details: { entry, summary: summary(data, config.warnPercent) } };
        }
        if (request.action === "recordUnknown") {
          const entry = entrySchema.parse({
            id: crypto.randomUUID(), amount: null, currency: request.currency ?? data.currency,
            category: request.category ?? "other", provider: request.provider, model: request.model,
            taskId: request.taskId, note: request.note ?? "供应商未返回金额", createdAt: new Date().toISOString(),
          });
          data.entries.push(entry);
          await writeBudget(context, path, data);
          return { content: [{ type: "text", text: "已记录一笔费用未知的任务；未知不会按 0 计算" }], details: { entry, summary: summary(data, config.warnPercent) } };
        }
        if (!request.entryId) throw new Error("removeEntry 需要 entryId");
        const before = data.entries.length;
        data.entries = data.entries.filter(entry => entry.id !== request.entryId);
        if (data.entries.length === before) throw new Error("没有找到该成本记录");
        await writeBudget(context, path, data);
        return { content: [{ type: "text", text: "成本记录已删除" }], details: summary(data, config.warnPercent) };
      },
    }];
  },
};

export default plugin;