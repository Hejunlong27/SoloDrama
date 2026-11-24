import { dirname, extname } from "node:path";
import { z } from "zod";
import type { ToolPlugin } from "@solodrama/tools-scaffold/runtime";
import { projectDimension, readSoloDramaProject } from "@solodrama/tools-scaffold/project";

const configSchema = z.object({
  width: z.number().int().min(240).max(7680).default(1080),
  height: z.number().int().min(240).max(7680).default(1920),
  fps: z.number().int().min(1).max(120).default(30),
  outputDirectory: z.string().default(".solodrama/jianyingDrafts"),
  includeCover: z.boolean().default(true),
  includeSubtitles: z.boolean().default(true),
  bgmPath: z.string().default(""),
  bgmVolume: z.number().finite().min(0).max(2).default(0.18),
  coverSeconds: z.number().finite().min(0.01).max(5).default(0.06),
}).strict();
const clipSchema = z.strictObject({
  videoPath: z.string().trim().min(1).max(4096),
  audioPath: z.string().trim().min(1).optional(),
  subtitlePath: z.string().trim().min(1).optional(),
  coverPath: z.string().trim().min(1).optional(),
  durationSeconds: z.number().finite().positive().optional(),
});
const draftSchema = z.strictObject({
  name: z.string().trim().min(1).max(100),
  mode: z.enum(["episode", "season"]).default("episode"),
  episodes: z.array(z.strictObject({
    name: z.string().trim().min(1).max(100),
    clips: z.array(clipSchema).min(1).max(500),
  })).min(1).max(100),
  outputDirectory: z.string().trim().min(1).optional(),
  width: z.number().int().min(240).max(7680).optional(),
  height: z.number().int().min(240).max(7680).optional(),
  fps: z.number().int().min(1).max(120).optional(),
  bgmPath: z.string().trim().min(1).optional(),
  bgmVolume: z.number().finite().min(0).max(2).optional(),
  narrationPath: z.string().trim().min(1).optional(),
  includeCover: z.boolean().optional(),
  includeSubtitles: z.boolean().optional(),
  coverSeconds: z.number().finite().min(0.01).max(5).optional(),
  overwrite: z.boolean().default(false),
});
const roughCutSchema = z.strictObject({
  name: z.string().trim().min(1).max(100),
  manifestPath: z.string().trim().min(1),
  outputDirectory: z.string().trim().min(1).optional(),
  width: z.number().int().min(240).max(7680).optional(),
  height: z.number().int().min(240).max(7680).optional(),
  fps: z.number().int().min(1).max(120).optional(),
  bgmPath: z.string().trim().min(1).optional(),
  bgmVolume: z.number().finite().min(0).max(2).optional(),
  includeCover: z.boolean().optional(),
  includeSubtitles: z.boolean().optional(),
  coverSeconds: z.number().finite().min(0.01).max(5).optional(),
  overwrite: z.boolean().default(false),
});
type Clip = z.infer<typeof clipSchema>;
type DraftOptions = z.infer<typeof configSchema> & {
  narrationPath?: string;
  includeCover?: boolean;
  includeSubtitles?: boolean;
};

function safeName(value: string) {
  return value.replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_").replace(/[. ]+$/g, "").slice(0, 80) || "draft";
}

async function probeDuration(context: Parameters<ToolPlugin["createTools"]>[0], path: string, signal?: AbortSignal) {
  let result: Record<string, unknown> | undefined;
  let failure: Error | undefined;
  await context.executeFfmpeg({
    directory: context.cwd, requestId: crypto.randomUUID(), options: { cwd: context.cwd },
    calls: [{ method: "input", args: [path] }],
    operation: { method: "ffprobe", args: [{ options: [], json: true }] },
  }, event => {
    if (event.event === "result") result = event.args[0] as Record<string, unknown>;
    if (event.event === "error") failure = event.args[0] as Error;
  }, signal);
  if (failure) throw failure;
  const format = result?.format && typeof result.format === "object" ? result.format as Record<string, unknown> : {};
  const duration = Number(format.duration ?? result?.duration);
  if (!Number.isFinite(duration) || duration <= 0) throw new Error(`无法读取媒体时长：${path}`);
  return duration;
}

function materialPath(path: string) {
  return path.replaceAll("\\", "/");
}

function parseSrt(value: string) {
  return value.replace(/^\uFEFF/, "").trim().split(/\r?\n\r?\n/).flatMap(block => {
    const lines = block.split(/\r?\n/).map(line => line.trimEnd());
    const timingIndex = lines.findIndex(line => line.includes("-->"));
    if (timingIndex < 0) return [];
    const [startText, endText] = lines[timingIndex]!.split("-->").map(part => part.trim().split(/\s+/)[0]!);
    const toSeconds = (text: string) => {
      const match = text.match(/^(\d+):(\d+):(\d+)[,.](\d+)$/);
      if (!match) return Number.NaN;
      return Number(match[1]) * 3600 + Number(match[2]) * 60 + Number(match[3]) + Number(match[4].padEnd(3, "0").slice(0, 3)) / 1000;
    };
    const start = toSeconds(startText);
    const end = toSeconds(endText);
    const text = lines.slice(timingIndex + 1).join("\n").trim();
    return Number.isFinite(start) && Number.isFinite(end) && end > start && text ? [{ start, end, text }] : [];
  });
}

async function writeDraft(
  context: Parameters<ToolPlugin["createTools"]>[0],
  options: DraftOptions,
  name: string,
  clips: Clip[],
  outputDirectory: string,
  overwrite: boolean,
  signal?: AbortSignal,
) {
  const root = `${outputDirectory.replace(/\/+$/, "")}/${safeName(name)}`;
  const draftPath = `${root}/draft_content.json`;
  const metaPath = `${root}/draft_meta_info.json`;
  const readmePath = `${root}/导入说明.md`;
  const absoluteDraft = await context.resolvePath(draftPath);
  if (!overwrite && await context.files.access(absoluteDraft).then(() => true).catch(() => false)) throw new Error(`草稿已存在：${draftPath}`);
  await context.files.mkdir(dirname(absoluteDraft), true);

  const videos: Record<string, unknown>[] = [];
  const audios: Record<string, unknown>[] = [];
  const images: Record<string, unknown>[] = [];
  const texts: Record<string, unknown>[] = [];
  const videoSegments: Record<string, unknown>[] = [];
  const clipAudioSegments: Record<string, unknown>[] = [];
  const narrationSegments: Record<string, unknown>[] = [];
  const bgmSegments: Record<string, unknown>[] = [];
  const imageSegments: Record<string, unknown>[] = [];
  const textSegments: Record<string, unknown>[] = [];
  let cursor = 0;
  if (options.includeCover !== false) {
    const coverPath = clips.find(clip => clip.coverPath)?.coverPath;
    if (coverPath) {
      const coverAbsolute = await context.resolvePath(coverPath, true);
      const imageId = crypto.randomUUID();
      const duration = Math.max(1, Math.round((options.coverSeconds ?? 0.06) * 1_000_000));
      images.push({ id: imageId, path: materialPath(coverAbsolute), type: "image", width: options.width, height: options.height, material_name: "封面" });
      imageSegments.push({ id: crypto.randomUUID(), material_id: imageId, source_timerange: { start: 0, duration: duration * 2 }, target_timerange: { start: 0, duration } });
      cursor += duration;
    }
  }
  for (const [index, clip] of clips.entries()) {
    signal?.throwIfAborted();
    const videoAbsolute = await context.resolvePath(clip.videoPath, true);
    const durationSeconds = clip.durationSeconds ?? await probeDuration(context, videoAbsolute, signal);
    const duration = Math.max(1, Math.round(durationSeconds * 1_000_000));
    const videoId = crypto.randomUUID();
    videos.push({
      id: videoId, path: materialPath(videoAbsolute), type: "video",
        duration, width: options.width, height: options.height,
      material_name: clip.videoPath.split(/[\\/]/).at(-1) || `shot-${index + 1}`,
    });
    videoSegments.push({
      id: crypto.randomUUID(), material_id: videoId,
      source_timerange: { start: 0, duration },
      target_timerange: { start: cursor, duration },
      speed: 1, volume: 1, visible: true,
    });
    if (clip.audioPath) {
      const audioAbsolute = await context.resolvePath(clip.audioPath, true);
      const audioDuration = await probeDuration(context, audioAbsolute, signal);
      const audioId = crypto.randomUUID();
      audios.push({
        id: audioId, path: materialPath(audioAbsolute), type: "extract",
        duration: Math.max(1, Math.round(audioDuration * 1_000_000)),
        name: clip.audioPath.split(/[\\/]/).at(-1) || `audio-${index + 1}`,
      });
      clipAudioSegments.push({
        id: crypto.randomUUID(), material_id: audioId,
        source_timerange: { start: 0, duration: Math.max(1, Math.round(audioDuration * 1_000_000)) },
        target_timerange: { start: cursor, duration: Math.max(1, Math.round(audioDuration * 1_000_000)) },
        volume: 1,
      });
    }
    if (options.includeSubtitles !== false && clip.subtitlePath) {
      const subtitleAbsolute = await context.resolvePath(clip.subtitlePath, true);
      const subtitles = parseSrt((await context.files.readFile(subtitleAbsolute, true)).toString("utf8"));
      for (const cue of subtitles) {
        const textId = crypto.randomUUID();
        const duration = Math.max(1, Math.round((cue.end - cue.start) * 1_000_000));
        texts.push({ id: textId, type: "text", content: cue.text, font_name: "SourceHanSansCN_Medium", font_size: 15, text_color: "#FFFFFF" });
        textSegments.push({
          id: crypto.randomUUID(), material_id: textId,
          source_timerange: { start: 0, duration },
          target_timerange: { start: cursor + Math.round(cue.start * 1_000_000), duration },
        });
      }
    }
    cursor += duration;
  }
  if (options.narrationPath) {
    const narrationAbsolute = await context.resolvePath(options.narrationPath, true);
    const duration = Math.max(1, Math.round(await probeDuration(context, narrationAbsolute, signal) * 1_000_000));
    const audioId = crypto.randomUUID();
    audios.push({ id: audioId, path: materialPath(narrationAbsolute), type: "extract", duration, name: "旁白" });
    narrationSegments.push({ id: crypto.randomUUID(), material_id: audioId, source_timerange: { start: 0, duration }, target_timerange: { start: 0, duration }, volume: 1 });
  }
  if (options.bgmPath) {
    const bgmAbsolute = await context.resolvePath(options.bgmPath, true);
    const duration = Math.max(1, Math.round(await probeDuration(context, bgmAbsolute, signal) * 1_000_000));
    const audioId = crypto.randomUUID();
    audios.push({ id: audioId, path: materialPath(bgmAbsolute), type: "music", duration, name: "BGM" });
    bgmSegments.push({ id: crypto.randomUUID(), material_id: audioId, source_timerange: { start: 0, duration }, target_timerange: { start: 0, duration: Math.min(duration, cursor) }, volume: options.bgmVolume });
  }
  const draft = {
    id: crypto.randomUUID(),
    version: 360000,
    name,
    fps: options.fps,
    duration: cursor,
    canvas_config: { width: options.width, height: options.height, ratio: "original" },
    tracks: [
      ...(imageSegments.length ? [{ id: crypto.randomUUID(), type: "image", attribute: 0, flag: 0, segments: imageSegments }] : []),
      { id: crypto.randomUUID(), type: "video", attribute: 0, flag: 0, segments: videoSegments },
      ...(textSegments.length ? [{ id: crypto.randomUUID(), type: "text", attribute: 0, flag: 0, segments: textSegments }] : []),
      ...(clipAudioSegments.length ? [{ id: crypto.randomUUID(), type: "audio", attribute: 0, flag: 0, segments: clipAudioSegments }] : []),
      ...(narrationSegments.length ? [{ id: crypto.randomUUID(), type: "audio", attribute: 0, flag: 0, segments: narrationSegments }] : []),
      ...(bgmSegments.length ? [{ id: crypto.randomUUID(), type: "audio", attribute: 0, flag: 0, segments: bgmSegments }] : []),
    ],
    materials: { videos, audios, texts, stickers: [], images, effects: [], transitions: [], masks: [], common: [] },
  };
  const meta = {
    draft_id: draft.id,
    draft_name: name,
    draft_root_path: root,
    draft_fold_path: root,
    tm_draft_create: Date.now(),
    tm_draft_modified: Date.now(),
    draft_removable_storage_space: 0,
    draft_cloud_purchase_info: "",
    draft_timeline_materials_size_: 0,
  };
  await context.files.writeFile(absoluteDraft, JSON.stringify(draft, null, 2) + "\n");
  const absoluteMeta = await context.resolvePath(metaPath);
  await context.files.writeFile(absoluteMeta, JSON.stringify(meta, null, 2) + "\n");
  const absoluteReadme = await context.resolvePath(readmePath);
  await context.files.writeFile(absoluteReadme, `# ${name}\n\n将本目录复制到剪映草稿目录后在剪映中打开。不同版本草稿格式可能不同，请用实际版本验证。\n\n- 画布：${options.width}×${options.height}\n- 帧率：${options.fps}\n- 镜头：${clips.length}\n- 字幕轨：${textSegments.length ? "有" : "无"}\n- 旁白轨：${narrationSegments.length ? "有" : "无"}\n- BGM 轨：${bgmSegments.length ? "有" : "无"}\n`);
  return { draftPath, metaPath, readmePath, durationSeconds: cursor / 1_000_000, clips: clips.length, subtitles: textSegments.length, hasNarration: !!narrationSegments.length, hasBgm: !!bgmSegments.length };
}

const plugin: ToolPlugin = {
  validateConfig: config => configSchema.parse(config),
  createTools(context) {
    const config = configSchema.parse(context.config);
    return [{
      name: "createDraft",
      label: "创建剪映草稿",
      description: "按逐集或整季模式创建剪映草稿目录，包含视频轨、可选音频轨和草稿元数据。",
      promptSnippet: "用户要求剪映草稿时，先确认视频、音频文件真实存在；episode 模式逐集创建，season 模式合并整季镜头。",
      parameters: z.toJSONSchema(draftSchema, { io: "input", target: "draft-07" }),
      executionMode: "sequential",
      async execute(_id, params, signal) {
        const request = draftSchema.parse(params);
        const project = await readSoloDramaProject(context);
        const dimensions = projectDimension(project, config.width, config.height);
        const options: DraftOptions = {
          ...config,
          width: request.width ?? dimensions.width,
          height: request.height ?? dimensions.height,
          fps: request.fps ?? project?.fps ?? config.fps,
          bgmPath: request.bgmPath ?? project?.jianying?.bgmPath ?? config.bgmPath,
          bgmVolume: request.bgmVolume ?? project?.jianying?.bgmVolume ?? config.bgmVolume,
          coverSeconds: request.coverSeconds ?? project?.jianying?.coverSeconds ?? config.coverSeconds,
          includeCover: request.includeCover ?? project?.jianying?.includeCover ?? config.includeCover,
          includeSubtitles: request.includeSubtitles ?? project?.jianying?.includeSubtitles ?? config.includeSubtitles,
          narrationPath: request.narrationPath,
        };
        const outputDirectory = request.outputDirectory ?? config.outputDirectory;
        const drafts = request.mode === "season"
          ? [await writeDraft(context, options, request.name, request.episodes.flatMap(episode => episode.clips), outputDirectory, request.overwrite, signal)]
          : await Promise.all(request.episodes.map(episode => writeDraft(context, options, `${request.name}-${episode.name}`, episode.clips, outputDirectory, request.overwrite, signal)));
        return { content: [{ type: "text", text: JSON.stringify({ mode: request.mode, drafts }, null, 2) }], details: { mode: request.mode, drafts } };
      },
    }, {
      name: "createDraftFromRoughCut",
      label: "从粗剪清单创建剪映草稿",
      description: "读取 solodrama-voice-rough-cut 清单，把镜头和旁白整理成一份剪映草稿。",
      parameters: z.toJSONSchema(roughCutSchema, { io: "input", target: "draft-07" }),
      executionMode: "sequential",
      async execute(_id, params, signal) {
        const request = roughCutSchema.parse(params);
        const project = await readSoloDramaProject(context);
        const dimensions = projectDimension(project, config.width, config.height);
        const options: DraftOptions = {
          ...config,
          width: request.width ?? dimensions.width,
          height: request.height ?? dimensions.height,
          fps: request.fps ?? project?.fps ?? config.fps,
          bgmPath: request.bgmPath ?? project?.jianying?.bgmPath ?? config.bgmPath,
          bgmVolume: request.bgmVolume ?? project?.jianying?.bgmVolume ?? config.bgmVolume,
          coverSeconds: request.coverSeconds ?? project?.jianying?.coverSeconds ?? config.coverSeconds,
          includeCover: request.includeCover ?? project?.jianying?.includeCover ?? config.includeCover,
          includeSubtitles: request.includeSubtitles ?? project?.jianying?.includeSubtitles ?? config.includeSubtitles,
        };
        const manifestPath = await context.resolvePath(request.manifestPath, true);
        const manifest = JSON.parse((await context.files.readFile(manifestPath, true)).toString("utf8")) as Record<string, unknown>;
        if (manifest.kind !== "solodrama-voice-rough-cut" || !Array.isArray(manifest.clips)) throw new Error("不是有效的配音粗剪清单");
        const clips: Clip[] = manifest.clips.flatMap(item => {
          if (!item || typeof item !== "object") return [];
          const clip = item as Record<string, unknown>;
          if (typeof clip.videoPath !== "string") return [];
          return [{
            videoPath: clip.videoPath,
            ...(typeof clip.audioPath === "string" ? { audioPath: clip.audioPath } : typeof manifest.narrationPath === "string" ? { audioPath: manifest.narrationPath } : {}),
          }];
        });
        const draft = await writeDraft(context, options, request.name, clips, request.outputDirectory ?? config.outputDirectory, request.overwrite, signal);
        return { content: [{ type: "text", text: JSON.stringify(draft) }], details: draft };
      },
    }];
  },
};

export default plugin;
