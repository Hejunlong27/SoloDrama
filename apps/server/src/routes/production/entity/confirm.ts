import { Router } from "express";
import { z } from "zod";
import { validateFields } from "@/lib/middleware";
import { success } from "@/lib/responseFormat";
import u from "@/utils";

export default Router().post("/", validateFields({
  directory: z.string().min(1).max(4096), expectedRevision: z.number().int().min(0),
  targetType: z.enum(["synopsis", "world", "characters", "locations", "props", "episodes", "timeline", "character", "location", "prop", "episode", "scene", "shot"]),
  targetId: z.uuid().optional(), confirmed: z.boolean(),
}), async (req, res) => {
  u.mcpControl.assertAppRequest(req);
  const cwd = await u.workspace.resolveWorkspace(req, req.body.directory);
  res.json(success(await u.production.confirmProductionEntity(cwd, req.body.expectedRevision, req.body.targetType, req.body.targetId, req.body.confirmed)));
});