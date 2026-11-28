import { Router } from "express";
import { success } from "@/lib/responseFormat";
import u from "@/utils";

export default Router().post("/", async (req, res) => {
  const runtime = u.desktop.getDesktopRuntime(req).launcher;
  await runtime.openLogFile();
  res.json(success({ path: runtime.logPath }));
});
