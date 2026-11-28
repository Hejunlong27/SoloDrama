import { Router } from "express";
import { z } from "zod";
import { validateFields } from "@/lib/middleware";
import { error, success } from "@/lib/responseFormat";
import u from "@/utils";

export default Router().get("/", validateFields({ id: z.uuid(), version: z.coerce.number().int().positive().optional() }, "query"), async (req, res) => {
  if (!u.workspace.isLocalWorkspaceRequest(req)) return res.status(403).json(error("请在桌面端或服务器本机管理工作流", null, 403));
  res.set("Cache-Control", "no-store").json(success(await u.comfyHub.comfyHubStore.getWorkflow(req.query.id as string, req.query.version === undefined ? undefined : Number(req.query.version))));
});
