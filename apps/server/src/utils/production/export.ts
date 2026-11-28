import { dirname, extname, relative } from "node:path";
import { mkdir, realpath, stat } from "@solodrama/file";
import type { ProductionDocument } from "@solodrama/production";
import { executeWorkspaceFfmpeg, prepareWorkspaceFfmpeg } from "@/utils/ffmpeg";
import { resolveWorkspacePath } from "@/utils/workspace/files";
import { loadProduction, mutateProduction } from "./store";

function even(value: number, label: string) {
  if (!Number.isInteger(value) || value < 2 || value > 8192 || value % 2) throw Object.assign(new Error(`${label}必须是 2 到 8192 之间的偶数`), { status: 400 });
}
type ExportClip = {
  asset: ProductionDocument["assets"][number];
  duration: number;
  transition: "cut" | "fade";
  shotId?: string;
  takeId?: string;
  timelineItemId?: string;
};
function selectedClips(document: ProductionDocument): ExportClip[] {
  return document.episodes.flatMap(episode => episode.scenes.flatMap(scene => scene.shots.flatMap(shot => {
    const take = shot.takes.find(item => item.id === shot.selectedTakeId);
    const asset = take?.outputAssetId ? document.assets.find(item => item.id === take.outputAssetId) : undefined;
    const timelineItem = document.timeline.find(item => item.kind === "video" && item.shotId === shot.id);
    return asset?.type === "video" && take ? [{ episode, scene, shot, asset, take, timelineItem }] : [];
  }))).sort((left, right) => left.episode.number - right.episode.number || left.scene.number - right.scene.number || left.shot.number - right.shot.number)
    .map(item => ({
      asset: item.asset, duration: item.shot.duration, transition: item.timelineItem?.transition ?? "cut",
      shotId: item.shot.id, takeId: item.take.id, timelineItemId: item.timelineItem?.id,
    }));
}
function timelineVideoClips(document: ProductionDocument): ExportClip[] {
  return document.timeline
    .filter(item => (item.kind === "video" || item.kind === "remotion") && item.assetId)
    .sort((left, right) => left.start - right.start)
    .flatMap(item => {
      const asset = document.assets.find(entry => entry.id === item.assetId);
      return asset?.type === "video" ? [{
        asset, duration: item.duration, transition: item.transition,
        ...(item.shotId ? { shotId: item.shotId } : {}), ...(item.takeId ? { takeId: item.takeId } : {}), timelineItemId: item.id,
      }] : [];
    });
}

export async function exportProduction(cwd: string, outputPath: string, options: { width?: number; height?: number; fps?: number; signal?: AbortSignal } = {}) {
  const root = await realpath(cwd);
  const document = await loadProduction(root);
  const clips = timelineVideoClips(document);
  const fallbackClips = clips.length ? clips : selectedClips(document);
  if (!fallbackClips.length) throw Object.assign(new Error("时间轴没有视频片段，无法导出成片"), { status: 409 });
  const width = options.width ?? 1080;
  const height = options.height ?? 1920;
  const fps = options.fps ?? 30;
  even(width, "宽度");
  even(height, "高度");
  if (!Number.isFinite(fps) || fps < 1 || fps > 120) throw Object.assign(new Error("帧率无效"), { status: 400 });
  if (!/\.(?:mp4|mov)$/i.test(outputPath)) throw Object.assign(new Error("成片输出必须为 MP4 或 MOV 路径"), { status: 400 });
  const output = await resolveWorkspacePath(root, outputPath, true);
  const existing = await stat(output.path).catch((cause: NodeJS.ErrnoException) => cause.code === "ENOENT" ? null : Promise.reject(cause));
  if (existing) throw Object.assign(new Error("输出文件已存在，请更换文件名，避免覆盖已有成片"), { status: 409 });
  await mkdir(dirname(output.path), { recursive: true });
  const clipPaths = await Promise.all(fallbackClips.map(item => resolveWorkspacePath(root, item.asset.path)));
  const timelineAudios = document.timeline.filter(item => item.kind === "audio" || item.kind === "music" || item.kind === "sfx").flatMap(item => {
    const asset = item.assetId ? document.assets.find(entry => entry.id === item.assetId) : undefined;
    return asset?.type === "audio" ? [{ item, asset }] : [];
  });
  const audioPaths = await Promise.all(timelineAudios.map(item => resolveWorkspacePath(root, item.asset.path)));
  const totalDuration = fallbackClips.reduce((sum, item) => sum + item.duration, 0);
  const calls: { method: string; args: unknown[] }[] = [];
  let inputIndex = 0;
  const clipIndexes = clipPaths.map(clip => { calls.push({ method: "input", args: [clip.path] }); return inputIndex++; });
  const audioIndexes = audioPaths.map(audio => { calls.push({ method: "input", args: [audio.path] }); return inputIndex++; });
  const filters = clipIndexes.map((index, position) => {
    const clip = fallbackClips[position]!;
    const fade = clip.transition === "cut" ? "" : `,fade=t=in:st=0:d=0.2,fade=t=out:st=${Math.max(0, clip.duration - 0.2)}:d=0.2`;
    return `[${index}:v]scale=${width}:${height}:force_original_aspect_ratio=decrease,pad=${width}:${height}:(ow-iw)/2:(oh-ih)/2:color=black,fps=${fps},setsar=1,tpad=stop_mode=clone:stop_duration=${clip.duration},trim=duration=${clip.duration},setpts=PTS-STARTPTS${fade}[v${position}]`;
  });
  const videoLabels = clipIndexes.map((_index, position) => `[v${position}]`).join("");
  filters.push(`${videoLabels}concat=n=${clipIndexes.length}:v=1:a=0[basev]`);
  const audioLabels: string[] = [];
  filters.push(`anullsrc=channel_layout=stereo:sample_rate=48000,atrim=duration=${totalDuration},asetpts=PTS-STARTPTS[basea]`);
  audioLabels.push("[basea]");
  for (const [index, entry] of timelineAudios.entries()) {
    const delay = Math.max(0, Math.round(entry.item.start * 1000));
    filters.push(`[${audioIndexes[index]}:a]aresample=48000,aformat=sample_rates=48000:channel_layouts=stereo,volume=${entry.item.volume},adelay=${delay}|${delay},atrim=duration=${entry.item.duration},asetpts=PTS-STARTPTS[ta${index}]`);
    audioLabels.push(`[ta${index}]`);
  }
  filters.push(`${audioLabels.join("")}amix=inputs=${audioLabels.length}:duration=first:dropout_transition=0[outa]`);
  calls.push({ method: "complexFilter", args: [filters.join(";")] });
  calls.push({ method: "videoCodec", args: ["libx264"] });
  calls.push({ method: "audioCodec", args: ["aac"] });
  calls.push({ method: "outputOptions", args: ["-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-map", "[basev]", "-map", "[outa]", "-shortest"] });
  calls.push({ method: "output", args: [output.path] });
  const paths = await prepareWorkspaceFfmpeg(options.signal);
  let failure: Error | undefined;
  await executeWorkspaceFfmpeg(root, {
    directory: root, requestId: crypto.randomUUID(), options: { cwd: root }, calls, operation: { method: "run", args: [] },
  }, event => { if (event.event === "error") failure = event.args[0] as Error; }, options.signal, paths);
  if (failure) throw failure;
  const info = await stat(output.path).catch(() => null);
  if (!info?.isFile() || info.size <= 0) throw new Error("FFmpeg 已结束，但没有找到输出成片");
  const relativeOutput = relative(root, output.path).replaceAll("\\", "/");
  const assetId = crypto.randomUUID();
  const latest = await loadProduction(root);
  await mutateProduction(root, latest.revision, "timeline:export", document => {
    document.assets.push({
      id: assetId, type: "video", path: relativeOutput, mimeType: extname(output.path).toLowerCase() === ".mov" ? "video/quicktime" : "video/mp4",
      name: output.path.split(/[\\/]/).at(-1), confirmed: false, version: 1, createdAt: Date.now(),
      metadata: { width, height, fps, duration: totalDuration, sourceShotIds: fallbackClips.flatMap(item => item.shotId ? [item.shotId] : []), sourceTakeIds: fallbackClips.flatMap(item => item.takeId ? [item.takeId] : []), sourceAssetIds: fallbackClips.map(item => item.asset.id), sourceTimelineItemIds: fallbackClips.flatMap(item => item.timelineItemId ? [item.timelineItemId] : []) },
    });
  });
  return { outputPath: relativeOutput, assetId, bytes: info.size, duration: totalDuration, width, height, fps, clips: fallbackClips.map(item => ({ shotId: item.shotId, takeId: item.takeId, assetId: item.asset.id })), audioItems: timelineAudios.map(item => item.item.id) };
}

