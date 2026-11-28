import { Router } from "express";
import { z } from "zod";
import { validateFields } from "@/lib/middleware";
import { success } from "@/lib/responseFormat";
import u from "@/utils";

export default Router().post("/", validateFields({
  directory: z.string().min(1).max(4096), expectedRevision: z.number().int().min(0),
  sourceId: z.string().regex(/^[a-f0-9]{64}$/),
  targetType: z.enum(["episode", "character", "location", "prop", "shot", "asset"]).optional(),
  targetId: z.uuid().optional(),
}), async (req, res) => {
  u.mcpControl.assertAppRequest(req);
  const cwd = await u.workspace.resolveWorkspace(req, req.body.directory);
  res.set("Cache-Control", "no-store").json(success(await u.production.importCanvasSource(
    cwd, req.body.expectedRevision, req.body.sourceId, { targetType: req.body.targetType, targetId: req.body.targetId },
  )));
});