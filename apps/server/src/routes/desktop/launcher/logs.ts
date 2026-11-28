import { Router } from "express";
import { lstat, readFile } from "@solodrama/file";
import { success } from "@/lib/responseFormat";
import u from "@/utils";

function redact(value: string) {
  return value
    .replace(/((?:Bearer|Basic)\s+)[^\s"'<>]+/gi, "$1••••••")
    .replace(/(https?:\/\/)[^/\s@]+@/gi, "$1••••••@")
    .replace(/([?&][^=&#\s]+)=[^&#\s"'<>]*/g, "$1=••••••")
    .replace(/((?:api[_-]?key|secret|token|password|authorization|cookie|credential|private[_-]?key|access[_-]?key|signature)["']?\s*[:=]\s*["']?)[^\s"',;}&<>]+/gi, "$1••••••");
}

export default Router().get("/", async (req, res) => {
  const runtime = u.desktop.getDesktopRuntime(req).launcher;
  const info = await lstat(runtime.logPath).catch(() => null);
  if (!info?.isFile()) return res.set("Cache-Control", "no-store").json(success({ path: runtime.logPath, lines: [] }));
  const bytes = await readFile(runtime.logPath);
  const text = bytes.subarray(Math.max(0, bytes.length - 1024 * 1024)).toString("utf8");
  const lines = redact(text).split(/\r?\n/).filter(Boolean).slice(-2000);
  res.set("Cache-Control", "no-store").json(success({ path: runtime.logPath, lines }));
});
