import { Router } from "express";
import { z } from "zod";
import { validateFields } from "@/lib/middleware";
import { productionDocumentSchema } from "@solodrama/production";
import { success } from "@/lib/responseFormat";
import u from "@/utils";

export default Router().put("/", validateFields({ directory: z.string().min(1).max(4096), expectedRevision: z.number().int().min(0), document: productionDocumentSchema }), async (req, res) => {
  u.mcpControl.assertAppRequest(req);
  const cwd = await u.workspace.resolveWorkspace(req, req.body.directory);
  res.set("Cache-Control", "no-store").json(success(await u.production.saveProduction(cwd, req.body.document, req.body.expectedRevision, "manual:save")));
});