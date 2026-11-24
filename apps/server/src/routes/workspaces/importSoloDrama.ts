import { Router } from "express";
import { basename, dirname, join, resolve } from "node:path";
import { lstat, readFile, realpath } from "@solodrama/file";
import { z } from "zod";
import u from "@/utils";
import conf from "@/utils/conf";
import { validateFields } from "@/lib/middleware";
import { error, success } from "@/lib/responseFormat";

const router = Router();

const inputSchema = z.object({
  source: z.string().trim().min(1).max(4096),
  name: z.string().trim().min(1).max(100).optional(),
  dryRun: z.boolean().optional(),
});

type PackInfo = { title: string; spec: string; path: string };

async function directoryExists(path: string) {
  return lstat(path).then(info => !info.isSymbolicLink() && info.isDirectory()).catch(() => false);
}

async function fileExists(path: string) {
  return lstat(path).then(info => info.isFile() && !info.isSymbolicLink()).catch(() => false);
}

async function readPack(path: string): Promise<PackInfo | undefined> {
  const file = join(path, "pack.json");
  if (!(await fileExists(file))) return undefined;
  let data: unknown;
  try { data = JSON.parse((await readFile(file, "utf8")).replace(/^\uFEFF/, "")); }
  catch { throw Object.assign(new Error("SoloDrama 创作包的 pack.json 不是有效 JSON"), { status: 400 }); }
  if (!data || typeof data !== "object" || Array.isArray(data)) throw Object.assign(new Error("SoloDrama 创作包格式无效"), { status: 400 });
  const record = data as Record<string, unknown>;
  if (typeof record.spec === "string" && record.spec !== "solodrama-pack/1") {
    throw Object.assign(new Error(`暂不支持创作包版本 ${record.spec}，当前支持 solodrama-pack/1`), { status: 400 });
  }
  return {
    title: typeof record.title === "string" && record.title.trim() ? record.title.trim() : basename(path),
    spec: typeof record.spec === "string" ? record.spec : "legacy",
    path,
  };
}

function safeName(value: string) {
  const cleaned = value
    .replace(/[<>:"/\\|?*\u0000-\u001f\u007f-\u009f]/g, "_")
    .replace(/[. ]+$/g, "")
    .trim()
    .slice(0, 80);
  return cleaned || "SoloDrama导入";
}

async function uniqueOutput(root: string, requested: string) {
  const base = safeName(requested);
  for (let index = 1; index < 1000; index++) {
    const name = index === 1 ? base : `${base}-${index}`;
    const path = join(root, name);
    if (!(await lstat(path).catch((error: NodeJS.ErrnoException) => {
      if (error.code === "ENOENT") return undefined;
      throw error;
    }))) return { path, name };
  }
  throw Object.assign(new Error("无法生成可用的导入目录名"), { status: 409 });
}

function pythonCandidates() {
  const candidates: string[][] = [];
  for (const command of process.platform === "win32" ? ["python", "python3", "py"] : ["python3", "python"]) {
    const executable = Bun.which(command);
    if (executable) candidates.push(command === "py" && process.platform === "win32" ? [executable, "-3"] : [executable]);
  }
  return candidates;
}

async function findImporterScript() {
  const fileName = "import-solodrama-project.py";
  const candidates = [
    resolve(dirname(conf.path), "..", "migration", fileName),
    resolve(dirname(conf.path), "migration", fileName),
    resolve(import.meta.dirname, "../../migration", fileName),
    resolve(process.cwd(), "migration", fileName),
    resolve(process.cwd(), "..", "migration", fileName),
  ];
  for (const candidate of candidates) if (await fileExists(candidate)) return candidate;
  throw Object.assign(new Error("缺少 migration/import-solodrama-project.py，请确认使用完整发布包"), { status: 500 });
}

async function runImporter(source: string, pack: PackInfo | undefined, output: string, name: string, dryRun: boolean) {
  const script = await findImporterScript();
  const python = pythonCandidates()[0];
  if (!python) throw Object.assign(new Error("未找到 Python 3。SoloDrama 创作包导入需要本机安装 Python 3，安装后重试。"), { status: 424 });
  const projectRoot = pack ? dirname(pack.path) : source;
  const args = [...python, script, "--source", projectRoot, "--output", output, "--canvas-name", `${safeName(name)}导入`];
  if (pack) args.push("--pack", pack.path);
  if (dryRun) args.push("--dry-run");
  const processResult = Bun.spawn({
    cmd: args,
    cwd: dirname(script),
    stdout: "pipe",
    stderr: "pipe",
    timeout: 600000,
    windowsHide: true,
  });
  const [stdout, stderr, exitCode] = await Promise.all([
    new Response(processResult.stdout).text(),
    new Response(processResult.stderr).text(),
    processResult.exited,
  ]);
  if (exitCode !== 0) throw Object.assign(new Error(stderr.trim() || stdout.trim() || "SoloDrama 导入器执行失败"), { status: 400 });
  try { return JSON.parse(stdout); }
  catch { throw Object.assign(new Error("SoloDrama 导入器返回了无效结果"), { status: 500 }); }
}

export default router.post("/", validateFields(inputSchema.shape), async (req, res) => {
  if (!u.workspace.isLocalWorkspaceRequest(req)) {
    return res.status(403).json(error("仅允许在本机 SoloDrama 页面导入 SoloDrama 创作包", null, 403));
  }
  const input = inputSchema.parse(req.body);
  const source = await realpath(input.source).catch((cause: NodeJS.ErrnoException) => {
    if (cause.code === "ENOENT" || cause.code === "ENOTDIR") throw Object.assign(new Error("SoloDrama 项目或创作包目录不存在"), { status: 404 });
    throw cause;
  });
  if (!(await directoryExists(source))) throw Object.assign(new Error("请选择 SoloDrama 项目目录或 pack 目录"), { status: 400 });

  let pack: PackInfo | undefined;
  let legacyProject = false;
  if (await fileExists(join(source, "pack.json"))) pack = await readPack(source);
  else {
    if (await directoryExists(join(source, "pack"))) pack = await readPack(join(source, "pack"));
    legacyProject = await fileExists(join(source, "layout.json"))
      || await directoryExists(join(source, "03-剧本"))
      || await directoryExists(join(source, "04-资产"))
      || await fileExists(join(source, "model-plan.json"));
  }
  if (!pack && !legacyProject) {
    throw Object.assign(new Error("没有找到 SoloDrama 的 pack.json、layout.json 或制作目录"), { status: 400 });
  }

  const root = await u.workspace.getWorkspaceRoot(req);
  const requested = input.name || pack?.title || basename(source);
  const output = await uniqueOutput(root, requested);
  const report = await runImporter(source, pack, output.path, output.name, input.dryRun === true);
  res.json(success({
    directory: input.dryRun ? null : output.path,
    name: output.name,
    title: pack?.title || basename(source),
    report,
  }, input.dryRun ? "试运行完成" : "SoloDrama 创作包导入完成"));
});
