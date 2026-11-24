import type { ToolContext } from "./runtime";

export const soloDramaProjectPath = ".solodrama/project.json";

export type SoloDramaProject = {
  version?: number;
  name?: string;
  aspectRatio?: string;
  resolution?: string;
  width?: number;
  height?: number;
  styleKey?: string;
  stylePrompt?: string;
  language?: "zh-CN" | "en" | "ja" | "ko";
  directorSkill?: string;
  episodeCount?: number;
  episodeSeconds?: number;
  fps?: number;
  tts?: {
    voice?: string;
    speed?: number;
    language?: string;
    format?: "mp3" | "wav";
    sampleRate?: number;
    volume?: number;
  };
  jianying?: {
    mode?: "episode" | "season";
    includeCover?: boolean;
    includeSubtitles?: boolean;
    includeBgm?: boolean;
    bgmPath?: string;
    bgmVolume?: number;
    coverSeconds?: number;
  };
  pipeline?: {
    includeSubtitles?: boolean;
    includeCover?: boolean;
    includeBgm?: boolean;
    bgmPath?: string;
    bgmVolume?: number;
  };
  cover?: {
    platform?: string;
    fontPath?: string;
    titleSize?: number;
    subtitleSize?: number;
    textPosition?: "top" | "center" | "bottom";
    safeArea?: number;
    outline?: number;
    shadow?: number;
  };
};

export async function readSoloDramaProject(context: ToolContext): Promise<SoloDramaProject | undefined> {
  const path = await context.resolvePath(soloDramaProjectPath, true);
  try {
    await context.files.access(path, true);
  } catch {
    return undefined;
  }
  const bytes = await context.files.readFile(path, true, { maxBytes: 1024 * 1024 });
  return JSON.parse(bytes.toString("utf8").replace(/^\uFEFF/, "")) as SoloDramaProject;
}

export function projectDimension(project: SoloDramaProject | undefined, width: number, height: number) {
  return {
    width: Number.isFinite(project?.width) && (project?.width ?? 0) > 0 ? project!.width! : width,
    height: Number.isFinite(project?.height) && (project?.height ?? 0) > 0 ? project!.height! : height,
  };
}
