import { Router } from "express";
import { z } from "zod";
import { validateFields } from "@/lib/middleware";
import { error, success } from "@/lib/responseFormat";
import u from "@/utils";

export default Router().post("/", validateFields({ workflowId: z.uuid(), instanceId: z.uuid() }), async (req, res) => {
  if (!u.workspace.isLocalWorkspaceRequest(req)) return res.status(403).json(error("请在桌面端或服务器本机检测工作流兼容性", null, 403));
  res.set("Cache-Control", "no-store").json(success(await u.comfyHub.verifyInstanceWorkflow(req.body.workflowId, req.body.instanceId)));
});
