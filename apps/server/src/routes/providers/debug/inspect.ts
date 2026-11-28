import { Router } from "express";
import u from "@/utils";
import { validateFields } from "@/lib/middleware";
import { error, success } from "@/lib/responseFormat";

export default Router().post("/", validateFields({ source: u.providerDebug.providerDebugSchema.source }), async (req, res) => {
  if (!u.workspace.isLocalWorkspaceRequest(req)) return res.status(403).json(error("请在桌面端或服务器本机调试供应商", null, 403));
  res.json(success(await u.providerDebug.inspectProviderSource(req.body.source)));
});
