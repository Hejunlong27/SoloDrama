import type { WorkspaceFiles } from "@solodrama/nodes-scaffold/workspaceFiles";

export const projectLanguageOptions = [
  { label: "中文", value: "zh-CN" },
  { label: "英语", value: "en" },
  { label: "日语", value: "ja" },
  { label: "韩语", value: "ko" },
] as const;
export type ProjectLanguage = typeof projectLanguageOptions[number]["value"];

export type SoloDramaProjectSettings = {
  version: 1;
  name: string;
  createdAt: string;
  updatedAt: string;
  aspectRatio: string;
  resolution: string;
  width: number;
  height: number;
  styleKey: string;
  stylePrompt: string;
  language: ProjectLanguage;
  directorSkill: string;
  episodeCount: number;
  episodeSeconds: number;
  fps: number;
  tts: {
    voice: string;
    speed: number;
    language: string;
    format: "mp3" | "wav";
    sampleRate: number;
    volume: number;
  };
  jianying: {
    mode: "episode" | "season";
    includeCover: boolean;
    includeSubtitles: boolean;
    includeBgm: boolean;
    bgmPath: string;
    bgmVolume: number;
    coverSeconds: number;
  };
  pipeline: {
    includeSubtitles: boolean;
    includeCover: boolean;
    includeBgm: boolean;
    bgmPath: string;
    bgmVolume: number;
  };
  cover: {
    platform: string;
    fontPath: string;
    titleSize: number;
    subtitleSize: number;
    textPosition: "top" | "center" | "bottom";
    safeArea: number;
    outline: number;
    shadow: number;
  };
};

export const projectSettingsPath = ".solodrama/project.json";

export async function readSoloDramaProject(files: WorkspaceFiles) {
  try {
    return await files.readJson<SoloDramaProjectSettings>(projectSettingsPath);
  } catch {
    return undefined;
  }
}

export function dimensionsFor(aspectRatio: string, resolution: string) {
  const [ratioWidth = 9, ratioHeight = 16] = aspectRatio.split(":").map(Number);
  const base = resolution === "4K" ? 2160 : resolution === "2K" ? 1440 : resolution === "720P" ? 720 : 1080;
  if (ratioWidth >= ratioHeight) return { width: Math.round(base * ratioWidth / ratioHeight), height: base };
  return { width: base, height: Math.round(base * ratioHeight / ratioWidth) };
}
