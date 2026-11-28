import { Router } from "express";
import { z } from "zod";
import { validateFields } from "@/lib/middleware";
import { error, success } from "@/lib/responseFormat";
import u from "@/utils";

export default Router().delete("/", validateFields({ id: z.uuid(), expectedRevision: z.number().int().min(0) }), async (req, res) => {
  if (!u.workspace.isLocalWorkspaceRequest(req)) return res.status(403).json(error("请在桌面端或服务器本机管理工作流", null, 403));
  await u.comfyHub.comfyHubStore.deleteWorkflow(req.body.id, req.body.expectedRevision);
  res.json(success());
});
