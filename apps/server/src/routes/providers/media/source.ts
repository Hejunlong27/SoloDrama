import { Router } from "express";
import u from "@/utils";
import { validateFields } from "@/lib/middleware";
import { error, success } from "@/lib/responseFormat";

export default Router().get("/", validateFields({
  fileName: u.mediaProvider.mediaProviderFileSchema,
}, "query"), async (req, res) => {
  if (!u.workspace.isLocalWorkspaceRequest(req)) return res.status(403).json(error("请在桌面端或服务器本机读取供应商源码", null, 403));
  res.set("Cache-Control", "no-store").json(success(await u.mediaProvider.getMediaProviderSource(req.query.fileName as string)));
});
