import { Router } from "express";
import { z } from "zod";
import { validateFields } from "@/lib/middleware";
import { success } from "@/lib/responseFormat";
import conf from "@/utils/conf";
import u from "@/utils";

const schema = z.strictObject({
  launcherOnboarded: z.boolean().optional(),
  autoOpenWorkspace: z.boolean().optional(),
  checkUpdatesOnStartup: z.boolean().optional(),
  launchOnStartup: z.boolean().optional(),
});

export default Router().put("/", validateFields(schema.shape), async (req, res) => {
  const input = schema.parse(req.body);
  const runtime = u.desktop.getDesktopRuntime(req).launcher;
  const current = conf.get("settings", {}).launcher;
  const launcher = current && typeof current === "object" && !Array.isArray(current) ? current as Record<string, unknown> : {};
  const next = { ...launcher, ...input };
  if (input.launchOnStartup !== undefined) next.launchOnStartup = await runtime.setLaunchOnStartup(input.launchOnStartup);
  conf.set("settings.launcher", next);
  res.set("Cache-Control", "no-store").json(success(next));
});
