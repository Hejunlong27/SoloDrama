import { Router } from "express";
import { z } from "zod";
import u from "@/utils";
import { validateFields } from "@/lib/middleware";
import { error, success } from "@/lib/responseFormat";

const inputSchema = z.strictObject({ source: z.string().min(1).max(2 * 1024 * 1024) });

export default Router().post("/", validateFields(inputSchema.shape), (req, res) => {
  if (!u.workspace.isLocalWorkspaceRequest(req)) return res.status(403).json(error("请在桌面端或服务器本机校验供应商源码", null, 403));
  const { source } = inputSchema.parse(req.body);
  res.set("Cache-Control", "no-store").json(success(u.mediaProvider.validateMediaProviderSource(source)));
});
