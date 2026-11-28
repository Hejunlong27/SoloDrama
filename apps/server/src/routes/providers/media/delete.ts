import { Router as createRouter } from "express";
import { z } from "zod";
import u from "@/utils";
import { validateFields } from "@/lib/middleware";
import { error, success } from "@/lib/responseFormat";

export default createRouter().delete("/", validateFields({
  fileName: u.mediaProvider.mediaProviderFileSchema,
  revision: z.string().regex(/^[a-f0-9]{64}$/),
}), async (req, res) => {
  if (!u.workspace.isLocalWorkspaceRequest(req)) return res.status(403).json(error("请在桌面端或服务器本机删除媒体供应商", null, 403));
  await u.mediaProvider.deleteMediaProvider(req.body.fileName, req.body.revision);
  res.json(success());
});
