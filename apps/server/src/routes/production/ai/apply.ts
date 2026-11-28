import { Router } from "express";
import { z } from "zod";
import { validateFields } from "@/lib/middleware";
import { scriptUnderstandingSchema } from "@solodrama/production";
import { success } from "@/lib/responseFormat";
import u from "@/utils";

const source = z.object({ kind: z.string().max(80), input: z.string().max(2 * 1024 * 1024), providerId: z.string().max(96).optional(), modelId: z.string().max(256).optional(), section: z.string().max(120), rawResponse: z.string().max(500000).optional() });
export default Router().post("/", validateFields({
  directory: z.string().min(1).max(4096), expectedRevision: z.number().int().min(0), result: scriptUnderstandingSchema, source,
  sections: z.array(z.enum(["synopsis", "world", "characters", "locations", "props", "episodes", "timeline"])).max(7).optional(), force: z.boolean().optional(),
}), async (req, res) => {
  u.mcpControl.assertAppRequest(req);
  const cwd = await u.workspace.resolveWorkspace(req, req.body.directory);
  res.set("Cache-Control", "no-store").json(success(await u.production.applyUnderstanding(cwd, req.body.expectedRevision, req.body.result, req.body.source, { force: req.body.force, sections: req.body.sections })));
});