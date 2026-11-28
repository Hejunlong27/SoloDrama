import { Router } from "express";
import { z } from "zod";
import { validateFields } from "@/lib/middleware";
import { success } from "@/lib/responseFormat";
import u from "@/utils";

export default Router().post("/", validateFields({
  directory: z.string().min(1).max(4096), providerId: z.string().min(1).max(96), modelId: z.string().min(1).max(256),
  shotId: z.uuid(), mode: z.enum(["general", "h3"]), instructions: z.string().max(10000).optional(),
}), async (req, res) => {
  u.mcpControl.assertAppRequest(req);
  u.multiTenant.requireDirectModelAccess();
  const cwd = await u.workspace.resolveWorkspace(req, req.body.directory);
  const controller = new AbortController();
  const close = () => controller.abort();
  res.once("close", close);
  req.once("aborted", close);
  try {
    const result = await u.production.optimizeShotPrompt(cwd, req.body.providerId, req.body.modelId, req.body, AbortSignal.any([controller.signal, AbortSignal.timeout(5 * 60 * 1000)]));
    res.set("Cache-Control", "no-store").json(success(result));
  } finally {
    res.off("close", close);
    req.off("aborted", close);
  }
});