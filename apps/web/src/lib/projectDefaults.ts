import type { SoloDramaProjectSettings } from "@solodrama/node-shared/projectSettings";

export type ProjectSetupValue = Pick<SoloDramaProjectSettings,
  "name" | "aspectRatio" | "resolution" | "width" | "height" | "styleKey" | "stylePrompt" | "language" | "directorSkill"
  | "episodeCount" | "episodeSeconds" | "fps"> & {
  tts: Pick<SoloDramaProjectSettings["tts"], "voice" | "speed">;
};

export function buildProjectSettings(value: ProjectSetupValue, existing?: SoloDramaProjectSettings): SoloDramaProjectSettings {
  const now = new Date().toISOString();
  return {
    version: 1,
    name: value.name,
    createdAt: existing?.createdAt ?? now,
    updatedAt: now,
    aspectRatio: value.aspectRatio,
    resolution: value.resolution,
    width: value.width,
    height: value.height,
    styleKey: value.styleKey,
    stylePrompt: value.stylePrompt,
    language: value.language,
    directorSkill: value.directorSkill,
    episodeCount: value.episodeCount,
    episodeSeconds: value.episodeSeconds,
    fps: value.fps,
    tts: {
      voice: value.tts.voice,
      speed: value.tts.speed,
      language: value.language,
      format: existing?.tts.format ?? "mp3",
      sampleRate: existing?.tts.sampleRate ?? 44100,
      volume: existing?.tts.volume ?? 0,
    },
    jianying: existing?.jianying ?? {
      mode: "episode",
      includeCover: true,
      includeSubtitles: true,
      includeBgm: false,
      bgmPath: "",
      bgmVolume: 0.18,
      coverSeconds: 0.06,
    },
    pipeline: existing?.pipeline ?? {
      includeSubtitles: true,
      includeCover: false,
      includeBgm: false,
      bgmPath: "",
      bgmVolume: 0.18,
    },
    cover: {
      platform: value.aspectRatio,
      fontPath: existing?.cover.fontPath ?? "C:/Windows/Fonts/msyhbd.ttc",
      titleSize: Math.max(48, Math.round(value.width * 0.095)),
      subtitleSize: Math.max(28, Math.round(value.width * 0.042)),
      textPosition: existing?.cover.textPosition ?? "bottom",
      safeArea: existing?.cover.safeArea ?? 0.12,
      outline: existing?.cover.outline ?? 3,
      shadow: existing?.cover.shadow ?? 1,
    },
  };
}
