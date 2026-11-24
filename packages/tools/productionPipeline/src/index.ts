import { dirname, extname, relative } from "node:path";
import { z } from "zod";
import type { ToolPlugin } from "@solodrama/tools-scaffold/runtime";
import { projectDimension, readSoloDramaProject } from "@solodrama/tools-scaffold/project";

const configSchema = z.object({
  width: z.number().int().min(240).max(7680).default(1080),
  height: z.number().int().min(240).max(7680).default(1920),
  fps: z.number().int().min(1).max(120).default(30),
  outputDirectory: z.string().default("09-发行/剧集"),
  bgmPath: z.string().default(""),
  bgmVolume: z.number().finite().min(0).max(2).default(0.18),
}).strict();
const renderSchema = z.strictObject({
  clips: z.array(z.string().trim().min(1)).min(1).max(500).describe("按播放顺序排列的工作区视频路径"),
  clipAudios: z.array(z.string().trim().min(1).nullable()).optional().describe("与 clips 一一对应的逐镜配音路径；无配音的位置填 null"),
  narrationPath: z.string().trim().min(1).optional().describe("可选整段旁白音频"),
  bgmPath: z.string().trim().min(1).optional().describe("可选背景音乐"),
  bgmVolume: z.number().finite().min(0).max(2).optional(),
  subtitlePath: z.string().trim().min(1).optional().describe("可选 SRT/ASS 字幕，设置后默认烧录"),
  burnSubtitles: z.boolean().optional(),
  coverPath: z.string().trim().min(1).optional(),
  coverSeconds: z.number().finite().min(0.01).max(10).optional(),
  audioMode: z.enum(["clip", "narration", "mix", "none"]).default("clip"),
  outputPath: z.string().trim().min(1).max(4096),
  width: z.number().int().min(240).max(7680).optional(),
  height: z.number().int().min(240).max(7680).optional(),
  fps: z.number().int().min(1).max(120).optional(),
  overwrite: z.boolean().default(false),
});
const roughCutSchema = z.strictObject({
  manifestPath: z.string().trim().min(1).max(4096),
  outputPath: z.string().trim().min(1).max(4096),
  width: z.number().int().min(240).max(7680).optional(),
  height: z.number().int().min(240).max(7680).optional(),
  fps: z.number().int().min(1).max(120).optional(),
  bgmPath: z.string().trim().min(1).optional(),
  bgmVolume: z.number().finite().min(0).max(2).optional(),
  subtitlePath: z.string().trim().min(1).optional(),
  burnSubtitles: z.boolean().optional(),
  coverPath: z.string().trim().min(1).optional(),
  coverSeconds: z.number().finite().min(0.01).max(10).optional(),
  audioMode: z.enum(["clip", "narration", "mix", "none"]).optional(),
  overwrite: z.boolean().default(false),
});
const inspectSchema = z.strictObject({
  directory: z.string().trim().min(1).default("."),
  depth: z.number().int().min(0).max(8).default(4),
});

async function scanVideos(context: Parameters<ToolPlugin["createTools"]>[0], directory: string, depth: number) {
  const root = await context.resolvePath(directory, true);
  const results: string[] = [];
  async function walk(path: string, remaining: number) {
    const names = await context.files.readdir(path, true).catch(() => []);
    for (const name of names) {
      const child = `${path.replaceAll("\\", "/").replace(/\/$/, "")}/${name}`;
      const info = await context.files.stat(child, true).catch(() => null);
      if (!info) continue;
      if (info.isDirectory() && remaining > 0) await walk(child, remaining - 1);
      else if (info.isFile() && [".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"].includes(extname(name).toLowerCase())) {
        results.push(relative(context.cwd, child).replaceAll("\\", "/"));
      }
    }
  }
  await walk(root, depth);
  return results.sort((left, right) => left.localeCompare(right, "zh-CN", { numeric: true }));
}

async function executeRender(context: Parameters<ToolPlugin["createTools"]>[0], config: z.infer<typeof configSchema>, request: z.infer<typeof renderSchema>, signal?: AbortSignal) {
  const project = await readSoloDramaProject(context);
  const dimensions = projectDimension(project, config.width, config.height);
  const width = request.width ?? dimensions.width;
  const height = request.height ?? dimensions.height;
  const fps = request.fps ?? project?.fps ?? config.fps;
  if (width % 2 || height % 2) throw new Error("输出宽高必须为偶数");
  const output = await context.resolvePath(request.outputPath);
  if (!request.overwrite && await context.files.access(output).then(() => true).catch(() => false)) throw new Error("输出文件已存在；如需覆盖请显式设置 overwrite=true");
  await context.files.mkdir(dirname(output), true);
  if (request.clipAudios && request.clipAudios.length !== request.clips.length) throw new Error("clipAudios 必须与 clips 数量一致");
  const clipPaths: string[] = [];
  for (const clip of request.clips) clipPaths.push(await context.resolvePath(clip, true));
  const clipAudioPaths: string[] = [];
  for (const audio of request.clipAudios ?? []) clipAudioPaths.push(audio ? await context.resolvePath(audio, true) : "");
  const narration = request.narrationPath ? await context.resolvePath(request.narrationPath, true) : undefined;
  const bgmPath = request.bgmPath ?? project?.pipeline?.bgmPath ?? config.bgmPath;
  const bgm = bgmPath ? await context.resolvePath(bgmPath, true) : undefined;
  const subtitle = request.subtitlePath ? await context.resolvePath(request.subtitlePath, true) : undefined;
  const cover = request.coverPath ? await context.resolvePath(request.coverPath, true) : undefined;
  const coverSeconds = request.coverSeconds ?? 0.06;
  const audioMode = request.audioMode ?? "clip";
  if ((audioMode === "narration" || audioMode === "mix") && !narration) throw new Error(`${audioMode} 音频模式需要提供 narrationPath`);
  const calls: { method: string; args: unknown[] }[] = [];
  let inputIndex = 0;
  let coverIndex = -1;
  if (cover) {
    calls.push({ method: "inputOptions", args: [["-loop", "1", "-t", String(coverSeconds)]] });
    calls.push({ method: "input", args: [cover] });
    coverIndex = inputIndex++;
  }
  const clipIndexes = clipPaths.map(clip => { calls.push({ method: "input", args: [clip] }); return inputIndex++; });
  const clipAudioIndexes = clipAudioPaths.map(audio => {
    if (!audio) return -1;
    calls.push({ method: "input", args: [audio] });
    return inputIndex++;
  });
  const clipMedia = await Promise.all(clipPaths.map(clip => probeMedia(context, clip, signal)));
  const narrationIndex = narration ? (calls.push({ method: "input", args: [narration] }), inputIndex++) : -1;
  const bgmIndex = bgm ? (calls.push({ method: "input", args: [bgm] }), inputIndex++) : -1;
  const filters: string[] = [];
  const videoLabels: string[] = [];
  let videoNumber = 0;
  if (cover && coverIndex >= 0) filters.push(`[${coverIndex}:v]scale=${width}:${height}:force_original_aspect_ratio=increase,crop=${width}:${height},fps=${fps},setsar=1,trim=duration=${coverSeconds},setpts=PTS-STARTPTS[v${videoNumber}]`), videoLabels.push(`[v${videoNumber++}]`);
  for (const [index, clip] of clipPaths.entries()) filters.push(`[${clipIndexes[index]}:v]scale=${width}:${height}:force_original_aspect_ratio=decrease,pad=${width}:${height}:(ow-iw)/2:(oh-ih)/2:color=black,fps=${fps},setsar=1,setpts=PTS-STARTPTS[v${videoNumber}]`), videoLabels.push(`[v${videoNumber++}]`);
  filters.push(`${videoLabels.join("")}concat=n=${videoLabels.length}:v=1:a=0[basev]`);
  let videoLabel = "[basev]";
  if (subtitle && (request.burnSubtitles ?? true)) {
    filters.push(`[basev]subtitles='${escapeFilterPath(subtitle)}'[outv]`);
    videoLabel = "[outv]";
  }
  let audioLabel = "";
  if (audioMode !== "none") {
    const audioLabels: string[] = [];
    let audioNumber = 0;
    if (cover) filters.push(`anullsrc=channel_layout=stereo:sample_rate=48000,atrim=duration=${coverSeconds},asetpts=PTS-STARTPTS[a${audioNumber}]`), audioLabels.push(`[a${audioNumber++}]`);
    for (const [index, media] of clipMedia.entries()) {
      const clipAudioIndex = clipAudioIndexes[index] ?? -1;
      if (clipAudioIndex >= 0) filters.push(`[${clipAudioIndex}:a]aresample=48000,aformat=sample_rates=48000:channel_layouts=stereo,apad,atrim=duration=${media.duration},asetpts=PTS-STARTPTS[a${audioNumber}]`);
      else if (media.hasAudio) filters.push(`[${clipIndexes[index]}:a]aresample=48000,asetpts=PTS-STARTPTS[a${audioNumber}]`);
      else filters.push(`anullsrc=channel_layout=stereo:sample_rate=48000,atrim=duration=${media.duration},asetpts=PTS-STARTPTS[a${audioNumber}]`);
      audioLabels.push(`[a${audioNumber++}]`);
    }
    filters.push(`${audioLabels.join("")}concat=n=${audioLabels.length}:v=0:a=1[basea]`);
    audioLabel = "[basea]";
    if (narrationIndex >= 0 && audioMode !== "clip") {
      filters.push(`[${narrationIndex}:a]aresample=48000,asetpts=PTS-STARTPTS[narration]`);
      if (audioMode === "narration") audioLabel = "[narration]";
      else filters.push(`${audioLabel}[narration]amix=inputs=2:duration=first:dropout_transition=2[mixednarration]`), audioLabel = "[mixednarration]";
    }
    if (bgmIndex >= 0) {
      filters.push(`[${bgmIndex}:a]aresample=48000,volume=${request.bgmVolume ?? project?.pipeline?.bgmVolume ?? config.bgmVolume}[bgm]`);
      filters.push(`${audioLabel}[bgm]amix=inputs=2:duration=first:dropout_transition=2[mixedbgm]`);
      audioLabel = "[mixedbgm]";
    }
  } else if (bgmIndex >= 0) {
    filters.push(`[${bgmIndex}:a]aresample=48000,volume=${request.bgmVolume ?? project?.pipeline?.bgmVolume ?? config.bgmVolume}[audiobgm]`);
    audioLabel = "[audiobgm]";
  }
  calls.push({ method: "complexFilter", args: [filters.join(";")] });
  calls.push({ method: "videoCodec", args: ["libx264"] });
  calls.push({ method: "outputOptions", args: ["-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart"] });
  if (audioLabel) {
    calls.push({ method: "audioCodec", args: ["aac"] });
    calls.push({ method: "outputOptions", args: ["-map", videoLabel, "-map", audioLabel, "-shortest"] });
  } else calls.push({ method: "outputOptions", args: ["-map", videoLabel, "-an"] });
  calls.push({ method: "output", args: [output] });
  let failure: Error | undefined;
  await context.executeFfmpeg({
    directory: context.cwd,
    requestId: crypto.randomUUID(),
    options: { cwd: context.cwd },
    calls,
    operation: { method: "run", args: [] },
  }, event => {
    if (event.event === "error") failure = event.args[0] as Error;
  }, signal);
  if (failure) throw failure;
  await context.files.access(output).catch(() => { throw new Error("FFmpeg 已结束，但没有找到输出成片"); });
  return { outputPath: request.outputPath.replaceAll("\\", "/"), clips: clipPaths.length, width, height, fps, audioMode, narration: !!narration, bgm: !!bgm, subtitles: !!subtitle, cover: !!cover, styleKey: project?.styleKey ?? "" };
}

async function probeMedia(context: Parameters<ToolPlugin["createTools"]>[0], path: string, signal?: AbortSignal) {
  let result: Record<string, unknown> | undefined;
  let failure: Error | undefined;
  await context.executeFfmpeg({
    directory: context.cwd, requestId: crypto.randomUUID(), options: { cwd: context.cwd },
    calls: [{ method: "input", args: [path] }], operation: { method: "ffprobe", args: [{ options: [], json: true }] },
  }, event => {
    if (event.event === "result") result = event.args[0] as Record<string, unknown>;
    if (event.event === "error") failure = event.args[0] as Error;
  }, signal);
  if (failure) throw failure;
  const format = result?.format && typeof result.format === "object" ? result.format as Record<string, unknown> : {};
  const streams = Array.isArray(result?.streams) ? result.streams as Record<string, unknown>[] : [];
  const duration = Number(format.duration);
  if (!Number.isFinite(duration) || duration <= 0) throw new Error(`无法读取视频时长：${path}`);
  return { duration, hasAudio: streams.some(stream => stream.codec_type === "audio") };
}

function escapeFilterPath(path: string) {
  return path.replaceAll("\\", "/").replaceAll(":", "\\:").replaceAll("'", "\\'");
}

const plugin: ToolPlugin = {
  validateConfig: config => configSchema.parse(config),
  createTools(context) {
    const config = configSchema.parse(context.config);
    return [{
      name: "inspectProduction",
      label: "扫描出片素材",
      description: "递归扫描工作区视频文件，返回可作为流水线输入的相对路径。",
      parameters: z.toJSONSchema(inspectSchema, { io: "input", target: "draft-07" }),
      async execute(_id, params) {
        const request = inspectSchema.parse(params);
        const videos = await scanVideos(context, request.directory, request.depth);
        return { content: [{ type: "text", text: JSON.stringify({ videos }, null, 2) }], details: { videos } };
      },
    }, {
      name: "renderProduction",
      label: "按镜头列表出片",
      description: "按给定顺序统一分辨率、帧率和像素格式，串联合成 MP4，并可绑定整段旁白音频。",
      promptSnippet: "镜头与配音都已有真实文件时使用；先检查路径和顺序，输出使用新文件名。",
      parameters: z.toJSONSchema(renderSchema, { io: "input", target: "draft-07" }),
      executionMode: "sequential",
      async execute(_id, params, signal) {
        signal?.throwIfAborted();
        const result = await executeRender(context, config, renderSchema.parse(params), signal);
        return { content: [{ type: "text", text: JSON.stringify(result) }], details: result };
      },
    }, {
      name: "renderRoughCut",
      label: "从粗剪清单出片",
      description: "读取 solodrama-voice-rough-cut 粗剪清单，按镜头顺序和逐镜配音合成成片。",
      promptSnippet: "已有粗剪清单时按清单中的镜头和逐镜音频顺序合成，不伪造缺失素材。",
      parameters: z.toJSONSchema(roughCutSchema, { io: "input", target: "draft-07" }),
      executionMode: "sequential",
      async execute(_id, params, signal) {
        signal?.throwIfAborted();
        const request = roughCutSchema.parse(params);
        const manifestPath = await context.resolvePath(request.manifestPath, true);
        const manifest = JSON.parse((await context.files.readFile(manifestPath, true)).toString("utf8")) as Record<string, unknown>;
        if (manifest.kind !== "solodrama-voice-rough-cut" || !Array.isArray(manifest.clips)) throw new Error("不是有效的配音粗剪清单");
        const clipEntries = manifest.clips.flatMap(item => item && typeof item === "object" && typeof (item as Record<string, unknown>).videoPath === "string" ? [item as Record<string, unknown>] : []);
        const clips = clipEntries.map(item => item.videoPath as string);
        const clipAudios = clipEntries.map(item => typeof item.audioPath === "string" ? item.audioPath : null);
        const result = await executeRender(context, config, renderSchema.parse({
          clips,
          ...(clipAudios.some(Boolean) ? { clipAudios } : {}),
          ...(typeof manifest.narrationPath === "string" ? { narrationPath: manifest.narrationPath } : {}),
          outputPath: request.outputPath,
          width: request.width,
          height: request.height,
          fps: request.fps,
          bgmPath: request.bgmPath,
          bgmVolume: request.bgmVolume,
          subtitlePath: request.subtitlePath,
          burnSubtitles: request.burnSubtitles,
          coverPath: request.coverPath,
          coverSeconds: request.coverSeconds,
          audioMode: request.audioMode,
          overwrite: request.overwrite,
        }), signal);
        return { content: [{ type: "text", text: JSON.stringify(result) }], details: result };
      },
    }];
  },
};

export default plugin;
