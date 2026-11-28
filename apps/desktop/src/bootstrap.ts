import { mkdirSync, writeFileSync } from "@solodrama/file";
import { homedir } from "node:os";
import { join, resolve } from "node:path";
import { formatWithOptions } from "node:util";

function defaultLogDirectory() {
  if (process.platform === "win32") return join(process.env.APPDATA || join(homedir(), "AppData", "Roaming"), "SoloDrama", "logs");
  if (process.platform === "darwin") return join(homedir(), "Library", "Logs", "SoloDrama");
  return join(process.env.XDG_STATE_HOME || join(homedir(), ".local", "state"), "solodrama", "logs");
}

function redact(value: string) {
  return value
    .replace(/((?:Bearer|Basic)\s+)[^\s"'<>]+/gi, "$1••••••")
    .replace(/(https?:\/\/)[^/\s@]+@/gi, "$1••••••@")
    .replace(/([?&][^=&#\s]+)=[^&#\s"'<>]*/g, "$1=••••••")
    .replace(/((?:api[_-]?key|secret|token|password|authorization|cookie|credential|private[_-]?key|access[_-]?key|signature)["']?\s*[:=]\s*["']?)[^\s"',;}&<>]+/gi, "$1••••••");
}

{
  const logDirectory = resolve(process.env.SOLODRAMA_DESKTOP_LOG_DIR || defaultLogDirectory());
  mkdirSync(logDirectory, { recursive: true, mode: 0o700 });
  process.env.SOLODRAMA_DESKTOP_LOG_DIR = logDirectory;
  const logPath = join(logDirectory, "app.log");
  const printError = console.error.bind(console);
  for (const method of ["log", "info", "warn", "error", "debug"] as const) {
    const print = console[method].bind(console);
    console[method] = (...args: unknown[]) => {
      try {
        const message = redact(formatWithOptions({ colors: false }, ...args));
        writeFileSync(logPath, `[${new Date().toISOString()}] [${method}] ${message}\n`, { flag: "a", mode: 0o600 });
      } catch (error) {
        printError("桌面日志写入失败：", error);
      }
      print(...args);
    };
  }
  console.info("桌面进程启动：", process.platform, process.arch, process.versions.bun);
}

// ACT: 日志先于桌面依赖初始化，依赖加载异常也能留下完整错误。
try { await import("./index"); }
catch (error) {
  console.error("桌面入口加载失败：", error);
  process.exit(1);
}
