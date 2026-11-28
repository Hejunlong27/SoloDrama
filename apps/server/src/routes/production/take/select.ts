import { Router } from "express";
import { z } from "zod";
import { validateFields } from "@/lib/middleware";
import { success } from "@/lib/responseFormat";
import u from "@/utils";

export default Router().post("/", validateFields({
  directory: z.string().min(1).max(4096), expectedRevision: z.number().int().min(0), shotId: z.uuid(), takeId: z.uuid(),
}), async (req, res) => {
  u.mcpControl.assertAppRequest(req);
  const cwd = await u.workspace.resolveWorkspace(req, req.body.directory);
  res.json(success(await u.production.selectProductionTake(cwd, req.body.expectedRevision, req.body.shotId, req.body.takeId)));
});