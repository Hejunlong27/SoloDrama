import { Router } from "express";
import { lstat } from "@solodrama/file";
import conf from "@/utils/conf";
import { success } from "@/lib/responseFormat";
import u from "@/utils";

export default Router().get("/", async (req, res) => {
  const runtime = u.desktop.getDesktopRuntime(req).launcher;
  const settings = conf.get("settings", {});
  const launcher = settings.launcher && typeof settings.launcher === "object" && !Array.isArray(settings.launcher)
    ? settings.launcher as Record<string, unknown> : {};
  const instances = (await u.comfyHub.comfyHubStore.listInstances()).items;
  const tasks = await u.mediaTasks.listComfyHubTasks();
  const logInfo = await lstat(runtime.logPath).catch(() => null);
  const dataInfo = await lstat(runtime.dataDirectory).catch(() => null);
  const multiTenant = settings.multiTenantEnabled === true;
  const checkedAt = instances.flatMap(item => item.health?.checkedAt ?? []).sort((left, right) => right - left)[0];
  res.set("Cache-Control", "no-store").json(success({
    runtime: { version: runtime.version, pid: runtime.pid, platform: runtime.platform, arch: runtime.arch },
    settings: {
      launcherOnboarded: launcher.launcherOnboarded === true,
      autoOpenWorkspace: launcher.autoOpenWorkspace !== false,
      checkUpdatesOnStartup: launcher.checkUpdatesOnStartup !== false,
      launchOnStartup: launcher.launchOnStartup === true,
    },
    checks: {
      environment: { status: "healthy", label: "桌面运行环境可用" },
      data: { status: dataInfo?.isDirectory() ? "healthy" : "unhealthy", label: dataInfo?.isDirectory() ? "数据目录可访问" : "数据目录不可访问", path: runtime.dataDirectory },
      backend: { status: "healthy", label: "本地服务正在运行", port: req.socket.localPort },
      frontend: { status: "healthy", label: "创作界面已连接" },
      database: { status: multiTenant ? "configured" : "notConfigured", label: multiTenant ? "多租户数据库已启用" : "未启用独立数据库" },
      localComfy: { status: instances.some(item => item.allowPrivateNetwork) ? "configured" : "notConfigured", label: instances.some(item => item.allowPrivateNetwork) ? "已配置本地/局域网 ComfyUI" : "未配置本地 ComfyUI" },
      cloud: { configured: instances.length, online: instances.filter(item => item.health?.status === "online" || item.health?.status === "degraded").length, offline: instances.filter(item => item.health?.status === "offline").length, lastCheckedAt: checkedAt },
      tasks: { running: tasks.filter(task => task.state === "running").length, interrupted: tasks.filter(task => task.state === "interrupted").length, total: tasks.length },
    },
    paths: { dataDirectory: runtime.dataDirectory, logDirectory: runtime.logDirectory, logPath: runtime.logPath, logExists: !!logInfo?.isFile(), logBytes: logInfo?.isFile() ? logInfo.size : 0 },
  }));
});
