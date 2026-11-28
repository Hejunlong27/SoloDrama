import { Router } from "express";
import { z } from "zod";
import { validateFields } from "@/lib/middleware";
import { error, success } from "@/lib/responseFormat";
import u from "@/utils";
import { providerHeadersSchema } from "@/utils/ai/provider";

const router = Router();

export default router.post("/", validateFields({
  apiUrl: z.url().refine(value => {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password && !url.search && !url.hash;
  }, "请填写不含查询参数的 HTTP API 基础地址"),
  protocol: z.enum(["openai-completions", "openai-responses", "anthropic-messages"]),
  apiKey: z.string().max(8192),
  headers: providerHeadersSchema.optional(),
}), async (req, res) => {
  if (!u.workspace.isLocalWorkspaceRequest(req)) return res.status(403).json(error("请在桌面端或服务器本机获取模型列表", null, 403));
  const { apiUrl, protocol, apiKey, headers } = req.body as { apiUrl: string; protocol: string; apiKey: string; headers?: Record<string, string> };
  res.json(success(await u.ai.fetchProviderModels({ apiUrl, protocol, apiKey, headers })));
});
