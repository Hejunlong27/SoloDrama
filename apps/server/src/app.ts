import logger from "morgan";
import express from "express";
import cors from "cors";
import { createHash } from "node:crypto";
import { dirname, resolve } from "node:path";
import { lstat, readFile, readdir, unlink } from "@solodrama/file";
import type { Request, Response, NextFunction } from "express";
import buildRoute from "@/core";
import { errorFromCause } from "@/lib/responseFormat";
import desktopRequest from "@/lib/desktop";
import { getRuntimePlatform } from "@/lib/platform";
import initializePlugins from "@/utils/plugins/initialize";
import { languageRequest, setLocaleFallback, translateError, translateMessage } from "@/lib/i18n";
import { detectLocale, normalizeLocale } from "@solodrama/i18n";

const autoInstallProviders = ["solodramaComfy.ts", "solodramaComfyCloud.ts", "solodramaComfyHub.ts", "solodramaRunningHub.ts", "solodramaRunningHubClosed.ts", "compshare.ts", "solodramaTts.ts"];
const removedDefaultProviders = ["solodramaZhenzhen.ts", "apiMart.ts", "metaso.ts"];

async function removeLegacyBuiltinTools(directory: string) {
  const file = resolve(directory, "localTts.tool.js");
  const source = await readFile(file, "utf8").catch((error: NodeJS.ErrnoException) => {
    if (error.code === "ENOENT") return "";
    throw error;
  });
  if (!source) return;
  try {
    const header = source.match(/^\/\*! solodramaTool:([^\r\n]*) \*\//)?.[1];
    const metadata = JSON.parse(header ?? "") as { name?: unknown; author?: unknown };
    // 仅移除仍由当前发行版安装的旧内置 TTS 工具；用户自建或改写的同名工具保留。
    if (metadata.name === "localTts" && metadata.author === "SoloDrama") await unlink(file);
  } catch { /* 非法旧工具元数据交给插件列表显示错误，不在这里删除。 */ }
}

async function pluginTreeRevision(roots: (string | undefined)[]) {
  const hash = createHash("sha256");
  async function walk(root: string, directory: string) {
    const entries = await readdir(directory, { withFileTypes: true }).catch((error: NodeJS.ErrnoException) => {
      if (error.code === "ENOENT") return [];
      throw error;
    });
    for (const entry of entries.sort((left, right) => left.name.localeCompare(right.name))) {
      const path = resolve(directory, entry.name);
      hash.update(path.slice(root.length)).update("\0");
      if (entry.isDirectory()) await walk(root, path);
      else if (entry.isFile()) hash.update(await readFile(path)).update("\0");
    }
  }
  for (const root of roots) if (root) await walk(root, root);
  return hash.digest("hex");
}

export async function createApp({
  webRoot,
  appVersion = "",
  dataDirectory,
  toolsRoot,
  nodesRoot,
  extRoot,
  providersRoot,
  skillsRoot,
  agentsRoot,
  pluginRevision,
}: {
  webRoot: string;
  appVersion?: string;
  dataDirectory?: string;
  toolsRoot?: string;
  nodesRoot?: string;
  extRoot?: string;
  providersRoot?: string;
  skillsRoot?: string;
  agentsRoot?: string;
  pluginRevision?: string;
}) {
  // conf 由下方的路由动态加载，必须先确定整个进程共用的数据目录。
  if (dataDirectory) process.env.SOLODRAMA_DATA_DIR = resolve(dataDirectory);
  const { default: conf } = await import("@/utils/conf");
  const providerDirectory = resolve(dirname(conf.path), "providers");
  const providerDirectoryInfo = await lstat(providerDirectory).catch((error: NodeJS.ErrnoException) => {
    if (error.code === "ENOENT") return null;
    throw error;
  });
  if (providerDirectoryInfo) {
    if (providerDirectoryInfo.isSymbolicLink() || !providerDirectoryInfo.isDirectory()) throw new Error("供应商目录不能是符号链接或文件");
    // ACT: 仅迁移清理已移除的内置适配文件；不递归删除目录，不改其他用户供应商。
    for (const file of await readdir(providerDirectory, { withFileTypes: true })) {
      if (file.name.toLowerCase() !== "tfrouter.ts" || (!file.isFile() && !file.isSymbolicLink())) continue;
      await unlink(resolve(providerDirectory, file.name)).catch((error: NodeJS.ErrnoException) => {
        if (error.code !== "ENOENT") throw error;
      });
    }
    if (providersRoot) {
      for (const name of removedDefaultProviders) {
        const installed = resolve(providerDirectory, name);
        const bundled = resolve(providersRoot, "media", name);
        const [installedSource, bundledSource] = await Promise.all([readFile(installed).catch(() => undefined), readFile(bundled).catch(() => undefined)]);
        // ACT: 只删除仍与发行包完全一致的内置副本；用户修改过的 Provider 继续保留。
        if (installedSource && bundledSource && installedSource.equals(bundledSource)) {
          await unlink(installed).catch((error: NodeJS.ErrnoException) => {
            if (error.code !== "ENOENT") throw error;
          });
        }
      }
    }
  }
  const { initializeNetwork } = await import("@/utils/network");
  await initializeNetwork();
  setLocaleFallback(() => normalizeLocale((conf.get("settings", {}).ui as { language?: unknown } | undefined)?.language)
    ?? detectLocale([Intl.DateTimeFormat().resolvedOptions().locale]));
  const builtinRevision = pluginRevision ?? await pluginTreeRevision([toolsRoot, nodesRoot, extRoot, skillsRoot]);
  if (dataDirectory && toolsRoot)
    await initializePlugins(resolve(dataDirectory, "tools"), toolsRoot, /^[a-z][a-zA-Z0-9]*\.tool\.js$/, builtinRevision);
  if (dataDirectory) await removeLegacyBuiltinTools(resolve(dataDirectory, "tools"));
  if (dataDirectory && nodesRoot) await initializePlugins(resolve(dataDirectory, "nodes"), nodesRoot, /^[a-z][a-zA-Z0-9]*\.umd\.js$/, builtinRevision);
  if (dataDirectory && extRoot) {
    const { default: initializeExt } = await import("@/utils/plugins/initializeExt");
    await initializeExt(resolve(dataDirectory, "ext"), extRoot, builtinRevision);
  }
  // ACT: 内置媒体供应商随构建同步，其他供应商文件和独立保存的配置保留。
  if (dataDirectory && providersRoot) {
    const sourceDirectory = resolve(providersRoot, "media");
    let providerRevision = pluginRevision;
    if (providerRevision === undefined) {
      const hash = createHash("sha256");
      for (const name of autoInstallProviders) {
        const source = await readFile(resolve(sourceDirectory, name)).catch((error: NodeJS.ErrnoException) => {
          if (error.code === "ENOENT") return Buffer.alloc(0);
          throw error;
        });
        hash.update(name).update("\0").update(source).update("\0");
      }
      providerRevision = hash.digest("hex");
    }
    await initializePlugins(resolve(dataDirectory, "providers"), sourceDirectory, autoInstallProviders, providerRevision);
  }
  // ACT: 技能和团队只补首次安装，保留用户修改。
  if (dataDirectory && skillsRoot) await initializePlugins(resolve(dataDirectory, "skills"), skillsRoot, undefined, builtinRevision);
  if (dataDirectory && agentsRoot) await initializePlugins(resolve(dataDirectory, "agents"), agentsRoot);
  const app = express();
  app.locals.appVersion = appVersion;
  // ACT: 内置身份取自当前发行包的目录，不依赖作者或安装记录；更新后的同名插件仍属于内置插件。
  app.locals.builtinPlugins = Object.fromEntries(await Promise.all(
    Object.entries({ tool: toolsRoot, node: nodesRoot, ext: extRoot, skill: skillsRoot, agent: agentsRoot }).map(async ([type, root]) => {
      const entries = root ? await readdir(root, { withFileTypes: true }).catch((error: NodeJS.ErrnoException) => {
        if (error.code === "ENOENT") return [];
        throw error;
      }) : [];
      const pattern = type === "tool" ? /^[a-z][a-zA-Z0-9]*\.tool\.js$/ : type === "ext" ? /^ext-[a-z][a-zA-Z0-9]*\.umd\.js$/ : /^[a-z][a-zA-Z0-9]*\.umd\.js$/;
      const names = entries.filter(entry => type === "skill" || type === "agent" ? entry.isDirectory() : entry.isFile() && pattern.test(entry.name))
        .map(entry => entry.isDirectory() ? entry.name : entry.name.replace(/\.(?:tool|umd)\.js$/, ""));
      return [type, new Set(names)];
    }),
  ));

  if (getRuntimePlatform().development) {
    await buildRoute();
    app.use(logger("dev"));
  }
  app.use(cors());
  app.use(languageRequest);
  const { initializeMultiTenantRuntime, multiTenantAccess } = await import("@/utils/multiTenant/runtime");
  initializeMultiTenantRuntime(app);
  app.use(multiTenantAccess);
  app.use("/a2a", express.json({ limit: "2mb" }));
  app.use(["/api/workspaces/files/write", "/api/assets/save"], express.raw({ type: "application/octet-stream", limit: "100mb" }));
  app.use(express.json({ limit: "100mb" }));
  app.use(express.urlencoded({ extended: true, limit: "100mb" }));
  app.use("/api/desktop", desktopRequest);

  const router = await import("@/router");
  router.default(app);
  const [{ createMcpRouter }, { getMcpTools, runInMcpRequest }, { authorizeMcp }, { skillResources }] = await Promise.all([
    import("@solodrama/mcp"),
    import("@/utils/mcp/tools"),
    import("@/utils/mcp/control"),
    import("@/utils/mcp/resources"),
  ]);
  app.use("/mcp", createMcpRouter({ getTools: getMcpTools, authorize: authorizeMcp, resources: skillResources,
    runInRequest: runInMcpRequest,
    translate: translateMessage,
    translateError,
  }));
  const { createA2aRouter } = await import("@/agent/a2a");
  app.use("/a2a", createA2aRouter());
  app.use(express.static(webRoot));

  // 错误处理
  app.use((err: Error & { status?: number }, request: Request, response: Response, next: NextFunction) => {
    if (response.headersSent) return next(err);
    console.error(err);
    const body = errorFromCause(err);
    response.status(body.code).json(body);
  });

  return app;
}
