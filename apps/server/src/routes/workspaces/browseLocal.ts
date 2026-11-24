import { Router } from "express";
import { readdir, realpath } from "@solodrama/file";
import { dirname, isAbsolute, parse, resolve } from "node:path";
import { homedir } from "node:os";
import { z } from "zod";
import u from "@/utils";
import { validateFields } from "@/lib/middleware";
import { error, success } from "@/lib/responseFormat";

const router = Router();

async function windowsRoots() {
  if (process.platform !== "win32") return [];
  const letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");
  const checks = await Promise.all(letters.map(async letter => {
    const path = `${letter}:\\`;
    try { await readdir(path); return path; }
    catch { return null; }
  }));
  return checks.filter((path): path is string => !!path);
}

export default router.get("/", validateFields({ path: z.string().max(4096).optional() }, "query"), async (req, res) => {
  if (!u.workspace.isLocalWorkspaceRequest(req)) {
    return res.status(403).json(error("仅允许在本机 SoloDrama 页面浏览本机目录", null, 403));
  }
  const requested = typeof req.query.path === "string" ? req.query.path.trim() : "";
  const target = requested ? (isAbsolute(requested) ? requested : resolve(homedir(), requested)) : homedir();
  try {
    const directory = await realpath(target);
    const entries = await readdir(directory, { withFileTypes: true });
    const root = parse(directory).root;
    const parent = directory === root ? null : dirname(directory);
    res.set("Cache-Control", "no-store").json(success({
      path: directory,
      absolutePath: directory,
      parent,
      roots: parent === null ? await windowsRoots() : [],
      directories: entries.filter(entry => entry.isDirectory()).map(entry => ({ name: entry.name, path: resolve(directory, entry.name) }))
        .sort((a, b) => a.name.localeCompare(b.name, "zh-CN", { numeric: true })),
    }));
  } catch (cause) {
    const code = (cause as NodeJS.ErrnoException).code;
    if (code === "ENOENT" || code === "ENOTDIR") return res.status(404).json(error("目录不存在", null, 404));
    if (code === "EACCES" || code === "EPERM") return res.status(403).json(error("没有权限访问此目录", null, 403));
    throw cause;
  }
});
