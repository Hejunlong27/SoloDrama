import { dirname } from "node:path";
import { access, mkdir, readFile, realpath, writeAtomic } from "@solodrama/file";
import type { ProductionDocument } from "@solodrama/production";
import { createJianyingDraft, type JianyingDraftClip, type JianyingDraftHost } from "@solodrama/tool-jianying-draft";
import { executeWorkspaceFfmpeg } from "@/utils/ffmpeg";
import { resolveWorkspacePath } from "@/utils/workspace/files";
import { loadProduction } from "./store";

function srtTime(seconds: number) {
  const milliseconds = Math.max(0, Math.round(seconds * 1000));
  const hours = Math.floor(milliseconds / 3_600_000);
  const minutes = Math.floor(milliseconds % 3_600_000 / 60_000);
  const wholeSeconds = Math.floor(milliseconds % 60_000 / 1000);
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(wholeSeconds).padStart(2, "0")},${String(milliseconds % 1000).padStart(3, "0")}`;
}

function subtitleSrt(document: ProductionDocument) {
  const items = document.timeline.filter(item => item.kind === "subtitle" && item.text?.trim()).sort((left, right) => left.start - right.start);
  return items.map((item, index) => `${index + 1}\n${srtTime(item.start)} --> ${srtTime(item.start + item.duration)}\n${item.text!.trim()}`).join("\n\n") + (items.length ? "\n" : "");
}

function timelineVideos(document: ProductionDocument) {
  return document.timeline
    .filter(item => (item.kind === "video" || item.kind === "remotion") && item.assetId)
    .sort((left, right) => left.start - right.start)
    .flatMap(item => {
      const asset = document.assets.find(entry => entry.id === item.assetId);
      return asset?.type === "video" ? [{ item, asset }] : [];
    });
}

function assetPath(document: ProductionDocument, itemId: string | undefined, type: "audio" | "video") {
  if (!itemId) return undefined;
  const item = document.timeline.find(entry => entry.id === itemId);
  const asset = item?.assetId ? document.assets.find(entry => entry.id === item.assetId) : undefined;
  return asset?.type === type ? asset.path : undefined;
}

export async function exportJianyingDraft(cwd: string, options: { outputDirectory?: string; signal?: AbortSignal } = {}) {
  const root = await realpath(cwd);
  const document = await loadProduction(root);
  const timelineVideosValue = timelineVideos(document);
  if (!timelineVideosValue.length) throw Object.assign(new Error("时间轴没有视频片段，无法创建剪映草稿"), { status: 409 });
  const srt = subtitleSrt(document);
  let subtitlePath: string | undefined;
  if (srt) {
    subtitlePath = `.solodrama/production/jianying/${crypto.randomUUID()}.srt`;
    const target = await resolveWorkspacePath(root, subtitlePath, true);
    await mkdir(dirname(target.path), { recursive: true });
    await writeAtomic(target.path, srt);
  }
  const clips: JianyingDraftClip[] = timelineVideosValue.map(({ item, asset }, index) => {
    const audio = item.shotId ? document.timeline.find(entry => entry.shotId === item.shotId && entry.kind === "audio" && entry.assetId) : undefined;
    return {
      videoPath: asset.path,
      durationSeconds: item.duration,
      ...(audio?.assetId ? { audioPath: assetPath(document, audio.id, "audio") ?? undefined } : {}),
      ...(index === 0 && subtitlePath ? { subtitlePath } : {}),
    };
  });
  const bgm = document.timeline.find(item => item.kind === "music" && item.assetId);
  const narration = document.timeline.find(item => item.kind === "audio" && item.track === "narration" && item.assetId);
  const bgmPath = bgm ? assetPath(document, bgm.id, "audio") : undefined;
  const narrationPath = narration ? assetPath(document, narration.id, "audio") : undefined;
  const outputDirectory = options.outputDirectory ?? ".solodrama/jianyingDrafts";
  const host: JianyingDraftHost = {
    cwd: root,
    resolvePath: async (path, readOnly = false) => (await resolveWorkspacePath(root, path, !readOnly)).path,
    files: {
      access: async path => { await access(path); },
      readFile: async path => readFile(path),
      writeFile: async (path, content) => { await writeAtomic(path, content); },
      mkdir: async (path, recursive = false) => { await mkdir(path, { recursive }); },
    },
    executeFfmpeg: async (request, emit, signal) => {
      await executeWorkspaceFfmpeg(root, request, emit, signal);
    },
  };
  const draft = await createJianyingDraft(host, {
    width: document.output.width,
    height: document.output.height,
    fps: document.output.fps,
    outputDirectory,
    includeCover: false,
    includeSubtitles: Boolean(subtitlePath),
    bgmPath: bgmPath ?? "",
    bgmVolume: 0.18,
    coverSeconds: 0.06,
    ...(narrationPath ? { narrationPath } : {}),
  }, document.name, clips, outputDirectory, false, options.signal);
  return {
    ...draft,
    ...(subtitlePath ? { subtitlePath } : {}),
    ...(bgmPath ? { bgmPath } : {}),
    ...(narrationPath ? { narrationPath } : {}),
  };
}

