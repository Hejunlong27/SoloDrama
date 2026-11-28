import { Router } from "express";
import { z } from "zod";
import { validateFields } from "@/lib/middleware";
import { error, success } from "@/lib/responseFormat";
import u from "@/utils";

const inputSchema = z.strictObject({
  kind: z.enum(["media", "language"]),
  providerId: z.string().regex(/^[a-z][a-zA-Z0-9]{0,95}$/).optional(),
  providerType: z.string().trim().min(1).max(64).optional(),
  source: z.string().min(1).max(2 * 1024 * 1024).optional(),
  config: z.record(z.string(), z.json()).default({}),
}).superRefine((value, context) => {
  if (value.kind === "media" && (!value.providerId || !value.source)) context.addIssue({ code: "custom", message: "媒体供应商诊断需要 providerId 和 source" });
});

export default Router().post("/", validateFields(inputSchema.shape), async (req, res) => {
  const input = inputSchema.parse(req.body);
  if (!u.workspace.isLocalWorkspaceRequest(req)) return res.status(403).json(error("请在桌面端或服务器本机诊断供应商", null, 403));
  u.multiTenant.requireDirectModelAccess();
  const result = input.kind === "media"
    ? await u.providerDiagnostics.diagnoseMediaProvider({ source: input.source!, config: input.config, providerId: input.providerId!, providerType: input.providerType })
    : await u.providerDiagnostics.diagnoseLanguageProvider(input.config);
  res.set("Cache-Control", "no-store").json(success(result));
});