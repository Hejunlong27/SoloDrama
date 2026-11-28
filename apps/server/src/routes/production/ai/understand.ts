import { Router } from "express";
import { z } from "zod";
import { validateFields } from "@/lib/middleware";
import { success } from "@/lib/responseFormat";
import u from "@/utils";

const sections = z.array(z.enum(["synopsis", "world", "characters", "locations", "props", "episodes", "timeline"])).max(7).optional();
export default Router().post("/", validateFields({
  directory: z.string().min(1).max(4096), providerId: z.string().min(1).max(96), modelId: z.string().min(1).max(256),
  title: z.string().trim().min(1).max(200), sourceText: z.string().trim().min(1).max(2 * 1024 * 1024),
  sourceKind: z.enum(["idea", "outline", "novel", "script", "episodeScript"]), sections,
  context: z.record(z.string(), z.json()).optional(),
}), async (req, res) => {
  u.mcpControl.assertAppRequest(req);
  u.multiTenant.requireDirectModelAccess();
  await u.workspace.resolveWorkspace(req, req.body.directory);
  const { directory: _directory, providerId, modelId, ...input } = req.body;
  const controller = new AbortController();
  const close = () => controller.abort();
  res.once("close", close);
  req.once("aborted", close);
  try {
    const generated = await u.production.understandScript(input, providerId, modelId, AbortSignal.any([controller.signal, AbortSignal.timeout(10 * 60 * 1000)]));
    res.set("Cache-Control", "no-store").json(success({ result: generated.result, source: { kind: req.body.sourceKind, input: req.body.sourceText, providerId: req.body.providerId, modelId: req.body.modelId, section: (req.body.sections ?? ["all"]).join(","), rawResponse: generated.raw } }));
  } finally {
    res.off("close", close);
    req.off("aborted", close);
  }
});