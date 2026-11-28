import { Router } from "express";
import { z } from "zod";
import { validateFields } from "@/lib/middleware";
import { success } from "@/lib/responseFormat";
import u from "@/utils";

export default Router().post("/", validateFields({
  directory: z.string().min(1).max(4096), outputPath: z.string().min(1).max(4096),
  width: z.number().int().min(2).max(8192).optional(), height: z.number().int().min(2).max(8192).optional(), fps: z.number().positive().max(120).optional(),
}), async (req, res) => {
  u.mcpControl.assertAppRequest(req);
  const cwd = await u.workspace.resolveWorkspace(req, req.body.directory);
  const controller = new AbortController();
  const close = () => controller.abort();
  res.once("close", close);
  req.once("aborted", close);
  try { res.json(success(await u.production.exportProduction(cwd, req.body.outputPath, { width: req.body.width, height: req.body.height, fps: req.body.fps, signal: controller.signal }))); }
  finally { res.off("close", close); req.off("aborted", close); }
});