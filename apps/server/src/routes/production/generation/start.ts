import { Router } from "express";
import { z } from "zod";
import { validateFields } from "@/lib/middleware";
import { success } from "@/lib/responseFormat";
import u from "@/utils";

export default Router().post("/", validateFields({
  directory: z.string().min(1).max(4096), expectedRevision: z.number().int().min(0),
  targetType: z.enum(["shot", "storyboard", "shotImage", "blocking", "characterReference", "locationReference", "propReference", "voice", "voiceDesign", "music", "sfx"]),
  targetId: z.uuid(), mediaType: z.enum(["image", "video", "audio"]),
  providerId: z.string().min(1).max(96), modelId: z.string().min(1).max(256),
  prompt: z.string().max(100000).optional(), negativePrompt: z.string().max(100000).optional(),
  referenceAssetIds: z.array(z.uuid()).max(64).optional(), firstFrameAssetId: z.uuid().optional(), lastFrameAssetId: z.uuid().optional(),
  workflowId: z.string().min(1).max(128).optional(), workflowVersion: z.number().int().positive().optional(),
  instanceId: z.string().min(1).max(128).optional(), ratio: z.string().regex(/^[1-9]\d{0,3}:[1-9]\d{0,3}$/).optional(),
  size: z.string().min(1).max(64).optional(), resolution: z.string().min(1).max(64).optional(),
  duration: z.number().positive().max(3600).optional(), voice: z.string().min(1).max(256).optional(), emotion: z.string().max(256).optional(), instructions: z.string().max(10000).optional(),
  speed: z.number().positive().optional(), language: z.string().min(1).max(64).optional(), format: z.string().min(1).max(64).optional(), continueFromPreviousShot: z.boolean().optional(),
}), async (req, res) => {
  u.mcpControl.assertAppRequest(req);
  const cwd = await u.workspace.resolveWorkspace(req, req.body.directory);
  const { directory: _directory, expectedRevision, ...generation } = req.body;
  res.set("Cache-Control", "no-store").json(success(await u.production.startProductionGeneration(cwd, expectedRevision, generation, u.multiTenant.requestIdentity(req))));
});
