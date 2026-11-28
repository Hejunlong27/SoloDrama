import { Router } from "express";
import { z } from "zod";
import { validateFields } from "@/lib/middleware";
import { success } from "@/lib/responseFormat";
import u from "@/utils";

export default Router().post("/", validateFields({
  directory: z.string().min(1).max(4096), expectedRevision: z.number().int().min(0),
  targetType: z.enum(["character", "location", "prop"]), targetId: z.uuid(), assetId: z.uuid(),
  kind: z.string().min(1).max(80).optional(), confirmed: z.boolean().optional(),
}), async (req, res) => {
  u.mcpControl.assertAppRequest(req);
  const cwd = await u.workspace.resolveWorkspace(req, req.body.directory);
  const { directory: _directory, expectedRevision, ...input } = req.body;
  res.json(success(await u.production.attachReference(cwd, expectedRevision, input)));
});