import { Router } from "express";
import { error, success } from "@/lib/responseFormat";
import u from "@/utils";

export default Router().put("/", async (req, res) => {
  if (!u.workspace.isLocalWorkspaceRequest(req)) return res.status(403).json(error("请在桌面端或服务器本机管理工作流", null, 403));
  res.set("Cache-Control", "no-store").json(success(await u.comfyHub.comfyHubStore.saveWorkflow(req.body)));
});
