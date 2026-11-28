import { Router } from "express";
import { z } from "zod";
import { validateFields } from "@/lib/middleware";
import { success } from "@/lib/responseFormat";
import u from "@/utils";

export default Router().post("/", validateFields({
  directory: z.string().min(1).max(4096),
}), async (req, res) => {
  u.mcpControl.assertAppRequest(req);
  const cwd = await u.workspace.resolveWorkspace(req, req.body.directory);
  const controller = new AbortController();
  const close = () => controller.abort();
  res.once("close", close);
  req.once("aborted", close);
  try { res.set("Cache-Control", "no-store").json(success(await u.production.exportJianyingDraft(cwd, { signal: controller.signal }))); }
  finally { res.off("close", close); req.off("aborted", close); }
});
