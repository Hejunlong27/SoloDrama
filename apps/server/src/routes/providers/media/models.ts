import { Router } from "express";
import { z } from "zod";
import u from "@/utils";
import { validateFields } from "@/lib/middleware";
import { error, success } from "@/lib/responseFormat";

export default Router().post("/", validateFields({
  fileName: u.mediaProvider.mediaProviderFileSchema,
  revision: z.string().regex(/^[a-f0-9]{64}$/),
}), async (req, res) => {
  if (!u.workspace.isLocalWorkspaceRequest(req)) return res.status(403).json(error("请在桌面端或服务器本机刷新媒体模型", null, 403));
  res.json(success(await u.mediaProvider.refreshMediaProviderModels(req.body.fileName, req.body.revision)));
});
