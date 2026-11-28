import { randomUUID } from "node:crypto";
import { dirname } from "node:path";
import { lstat, mkdir, realpath, stat } from "@solodrama/file";
import type { AuthIdentity } from "@solodrama/multi-tenant-auth";
import type { GeneratedMedia, MediaGenerationRequest } from "@solodrama/tools-scaffold/runtime";
import type { ProductionAsset, ProductionDocument, ProductionGenerationJob, ProductionShot, ShotTake } from "@solodrama/production";
import { loadProduction, mutateProduction } from "./store";
import { resolveWorkspacePath } from "@/utils/workspace/files";
import { cancel as cancelMediaTasks, start as startMediaTask, status as mediaTaskStatus } from "@/utils/media/tasks";
import { createWorkspaceFfmpeg } from "@/utils/ffmpeg";

export type ProductionGenerationInput = {
  targetType: "shot" | "storyboard" | "shotImage" | "blocking" | "characterReference" | "locationReference" | "propReference" | "voice" | "voiceDesign" | "music" | "sfx";
  targetId: string;
  mediaType: "image" | "video" | "audio";
  providerId: string;
  modelId: string;
  prompt?: string;
  negativePrompt?: string;
  referenceAssetIds?: string[];
  firstFrameAssetId?: string;
  lastFrameAssetId?: string;
  workflowId?: string;
  workflowVersion?: number;
  instanceId?: string;
  ratio?: string;
  size?: string;
  resolution?: string;
  duration?: number;
  voice?: string;
  speed?: number;
  language?: string;
  format?: string;
  continueFromPreviousShot?: boolean;
};

type TaskSnapshot = {
  taskId: string;
  state: string;
  submissionState?: string;
  resumable?: boolean;
  result?: { code: number; data: GeneratedMedia[] | null; message: string };
};

function invalid(message: string, status = 400): never {
  throw Object.assign(new Error(message), { status });
}

function allShots(document: ProductionDocument) {
  return document.episodes.flatMap(episode => episode.scenes.flatMap(scene => scene.shots));
}

function locateShot(document: ProductionDocument, shotId: string) {
  return allShots(document).find(item => item.id === shotId);
}

function referenceAssets(document: ProductionDocument, ids: string[]) {
  return ids.flatMap(id => {
    const asset = document.assets.find(item => item.id === id);
    return asset?.type === "image" ? [asset] : [];
  });
}

function shotReferenceAssets(document: ProductionDocument, shot: ProductionShot) {
  const scene = document.episodes.flatMap(episode => episode.scenes).find(item => item.id === shot.sceneId);
  const characterAssets = shot.characterIds.flatMap(id => document.characters.find(item => item.id === id)?.referenceImages ?? []).map(item => item.assetId);
  const locationAssets = scene?.locationId ? document.locations.find(item => item.id === scene.locationId)?.referenceImages.map(item => item.assetId) ?? [] : [];
  const propAssets = shot.propIds.flatMap(id => document.props.find(item => item.id === id)?.referenceImages ?? []).map(item => item.assetId);
  return referenceAssets(document, [...characterAssets, ...locationAssets, ...propAssets]);
}
function promptFor(document: ProductionDocument, input: ProductionGenerationInput) {
  if (input.prompt?.trim()) return input.prompt.trim();
  if (["shot", "storyboard", "shotImage", "blocking", "voice"].includes(input.targetType)) {
    const shot = locateShot(document, input.targetId) ?? invalid("镜头不存在", 404);
    if (input.targetType === "voice") return shot.dialogue.trim() || invalid("镜头没有可配音的对白");
    if (input.targetType === "storyboard") return [shot.description, shot.positions, shot.expressions, shot.firstFramePrompt].filter(Boolean).join("\n");
    if (input.targetType === "shotImage") return [shot.firstFramePrompt, shot.description, shot.positions, shot.expressions].filter(Boolean).join("\n");
    if (input.targetType === "blocking") return ["俯视站位图，平面构图", shot.positions, shot.action, shot.description].filter(Boolean).join("\n");
    return input.mediaType === "video"
      ? [shot.h3VideoPrompt, shot.videoPrompt, shot.description, shot.action, shot.positions, shot.expressions, shot.dialogue].filter(Boolean).join("\n")
      : [shot.firstFramePrompt, shot.description, shot.positions, shot.expressions].filter(Boolean).join("\n");
  }
  if (input.targetType === "voiceDesign") {
    const character = document.characters.find(entry => entry.id === input.targetId) ?? invalid("角色不存在", 404);
    return input.prompt?.trim() || `${character.name}的角色音色试听`;
  }
  if (input.targetType === "characterReference") {
    const item = document.characters.find(entry => entry.id === input.targetId) ?? invalid("角色不存在", 404);
    return [item.visualDescription, item.appearance, item.description, item.visualProfile.face, item.visualProfile.hair, item.visualProfile.body, item.visualProfile.style].filter(Boolean).join("\n") || item.name;
  }
  if (input.targetType === "locationReference") {
    const item = document.locations.find(entry => entry.id === input.targetId) ?? invalid("场景不存在", 404);
    return [item.description, item.spatialStructure, item.lighting, item.colorPalette, item.timeOfDay, item.atmosphere].filter(Boolean).join("\n") || item.name;
  }
  if (input.targetType === "propReference") {
    const item = document.props.find(entry => entry.id === input.targetId) ?? invalid("道具不存在", 404);
    return item.description || item.name;
  }
  return "生成短剧制作素材";
}

function generationRequest(document: ProductionDocument, input: ProductionGenerationInput, prompt: string) {
  const explicit = referenceAssets(document, [
    ...(input.referenceAssetIds ?? []),
    ...(input.firstFrameAssetId ? [input.firstFrameAssetId] : []),
    ...(input.lastFrameAssetId ? [input.lastFrameAssetId] : []),
  ]);
  const automatic = ["shot", "storyboard", "voice"].includes(input.targetType)
    ? shotReferenceAssets(document, locateShot(document, input.targetId)!) : [];
  const images = [...explicit, ...automatic].filter((asset, index, list) => list.findIndex(item => item.id === asset.id) === index).slice(0, 64);
  const firstFrame = images.find(item => item.id === input.firstFrameAssetId);
  const lastFrame = images.find(item => item.id === input.lastFrameAssetId);
  const request: MediaGenerationRequest = {
    providerId: input.providerId,
    modelId: input.modelId,
    prompt,
    outputDirectory: `assets/production/${input.targetType}`,
    ...(input.ratio ? { ratio: input.ratio } : {}),
    ...(input.size ? { size: input.size } : {}),
    ...(input.resolution ? { resolution: input.resolution } : {}),
    ...(input.duration ? { duration: input.duration } : {}),
    ...(input.voice ? { voice: input.voice } : {}),
    ...(input.speed ? { speed: input.speed } : {}),
    ...(input.language ? { language: input.language } : {}),
    ...(input.format ? { format: input.format } : {}),
    ...(images.length ? { images: images.map(item => ({ path: item.path, mimeType: item.mimeType })) } : {}),
    ...(input.mediaType === "video" && images.length ? { referenceOrder: images.map((_item, index) => ({ type: "image" as const, index })) } : {}),
    ...(input.mediaType === "video" && firstFrame ? { firstFrame: { path: firstFrame.path, mimeType: firstFrame.mimeType } } : {}),
    ...(input.mediaType === "video" && lastFrame ? { lastFrame: { path: lastFrame.path, mimeType: lastFrame.mimeType } } : {}),
    other: {
      ...(input.negativePrompt ? { negativePrompt: input.negativePrompt } : {}),
      ...(input.workflowId ? { workflowId: input.workflowId } : {}),
      ...(input.workflowVersion ? { workflowVersion: input.workflowVersion } : {}),
      ...(input.instanceId ? { instanceId: input.instanceId } : {}),
      productionTarget: { type: input.targetType, id: input.targetId },
    },
  };
  return { request, referenceAssetIds: images.map(item => item.id) };
}
async function extractPreviousTailFrame(root: string, document: ProductionDocument, shotId: string) {
  const shots = allShots(document);
  const index = shots.findIndex(shot => shot.id === shotId);
  if (index <= 0) invalid("当前镜头没有可续接的上一个镜头", 409);
  const previous = shots[index - 1]!;
  const take = previous.takes.find(item => item.id === previous.selectedTakeId) ?? invalid("上一个镜头还没有正式 Take，不能尾帧续画", 409);
  const source = take.outputAssetId ? document.assets.find(item => item.id === take.outputAssetId) : undefined;
  if (source?.type !== "video") invalid("上一个正式 Take 不是视频素材，不能提取尾帧", 409);
  const relativePath = `assets/production/tailFrames/${take.id}.png`;
  const existing = document.assets.find(item => item.path === relativePath && item.type === "image");
  if (existing) return { asset: existing, previousShotId: previous.id, previousTakeId: take.id };
  const input = await resolveWorkspacePath(root, source.path);
  const output = await resolveWorkspacePath(root, relativePath, true);
  await mkdir(dirname(output.path), { recursive: true });
  const ffmpeg = await createWorkspaceFfmpeg(root);
  await new Promise<void>((resolve, reject) => {
    ffmpeg(input.path)
      .inputOptions(["-sseof", "-0.15"])
      .outputOptions(["-frames:v", "1", "-y"])
      .output(output.path)
      .on("end", () => resolve())
      .on("error", error => reject(error))
      .run();
  });
  const info = await stat(output.path).catch(() => null);
  if (!info?.isFile() || info.size <= 0) invalid("尾帧提取失败，没有生成图片", 500);
  return {
    asset: {
      id: randomUUID(), type: "image" as const, path: relativePath, mimeType: "image/png",
      name: `镜头${previous.number}-尾帧.png`, version: 1, confirmed: false, createdAt: Date.now(),
      metadata: { tailFrameFromAssetId: source.id, previousShotId: previous.id, previousTakeId: take.id },
    } satisfies ProductionAsset,
    previousShotId: previous.id,
    previousTakeId: take.id,
  };
}

export async function startProductionGeneration(cwd: string, expectedRevision: number, input: ProductionGenerationInput, owner?: AuthIdentity | null) {
  const document = await loadProduction(cwd);
  if (document.revision !== expectedRevision) invalid("制作数据已更新，请重新加载后生成", 409);
  const continuation = input.targetType === "shot" && input.mediaType === "video" && input.continueFromPreviousShot
    ? await extractPreviousTailFrame(await realpath(cwd), document, input.targetId) : undefined;
  const prompt = promptFor(document, input);
  let { request, referenceAssetIds } = generationRequest(document, input, prompt);
  if (continuation) {
    const image = { path: continuation.asset.path, mimeType: continuation.asset.mimeType };
    request = { ...request, images: [...(request.images ?? []), image], firstFrame: image };
    referenceAssetIds = [...referenceAssetIds, continuation.asset.id];
  }
  const taskId = randomUUID();
  const itemId = randomUUID();
  const shot = ["shot", "storyboard", "shotImage", "blocking", "voice"].includes(input.targetType) ? locateShot(document, input.targetId) : undefined;
  if (["shot", "storyboard", "shotImage", "blocking", "voice"].includes(input.targetType) && !shot) invalid("镜头不存在", 404);
  if (["characterReference", "voiceDesign"].includes(input.targetType) && !document.characters.some(item => item.id === input.targetId)) invalid("角色不存在", 404);
  if (input.targetType === "locationReference" && !document.locations.some(item => item.id === input.targetId)) invalid("场景不存在", 404);
  if (input.targetType === "propReference" && !document.props.some(item => item.id === input.targetId)) invalid("道具不存在", 404);
  if (input.targetType === "shot") {
    const numbering = Math.max(0, ...shot!.takes.map(item => item.number)) + 1;
    const take: ShotTake = {
      id: itemId, shotId: shot!.id, number: numbering, status: "generating", selected: false, taskId,
      ...(input.workflowId ? { workflowId: input.workflowId } : {}), ...(input.workflowVersion ? { workflowVersion: input.workflowVersion } : {}),
      providerId: input.providerId, modelId: input.modelId, ...(input.instanceId ? { instanceId: input.instanceId } : {}),
      prompt, negativePrompt: input.negativePrompt ?? "", referenceAssetIds, parameters: request as unknown as Record<string, never>, createdAt: Date.now(), updatedAt: Date.now(),
    };
    await mutateProduction(cwd, expectedRevision, "generation:start", latest => {
      const currentShot = locateShot(latest, input.targetId)!;
      if (continuation && !latest.assets.some(item => item.id === continuation.asset.id)) latest.assets.push(continuation.asset);
      currentShot.takes.push(take);
      if (continuation) {
        currentShot.continuationSourceShotId = continuation.previousShotId;
        currentShot.continuationTakeId = continuation.previousTakeId;
        currentShot.generationOptions = { ...(currentShot.generationOptions ?? { storyboardEnabled: true, shotImageEnabled: false, blockingEnabled: false, useStoryboardReference: true, useShotImageReference: true, useBlockingReference: true }), continueFromPreviousShot: true };
      }
    });
  } else {
    const job: ProductionGenerationJob = {
      id: itemId, taskId, kind: input.targetType, mediaType: input.mediaType, targetId: input.targetId,
      providerId: input.providerId, modelId: input.modelId, status: "generating", createdAt: Date.now(), updatedAt: Date.now(),
    };
    await mutateProduction(cwd, expectedRevision, "generation:start", latest => { latest.generationJobs.push(job); });
  }
  try {
    const task = await startMediaTask(cwd, taskId, input.mediaType, request, { nodeId: itemId, canvasPath: ".solodrama/production.json" }, owner);
    return { itemId, taskId, task };
  } catch (error) {
    const latest = await loadProduction(cwd);
    await mutateProduction(cwd, latest.revision, "generation:start-failed", next => {
      const take = allShots(next).flatMap(item => item.takes).find(item => item.id === itemId);
      if (take) Object.assign(take, { status: "failed", error: error instanceof Error ? error.message : String(error), updatedAt: Date.now() });
      const job = next.generationJobs.find(item => item.id === itemId);
      if (job) Object.assign(job, { status: "failed", error: error instanceof Error ? error.message : String(error), updatedAt: Date.now() });
    });
    throw error;
  }
}

function assetForResult(document: ProductionDocument, taskId: string, file: GeneratedMedia) {
  const existing = document.assets.find(item => item.sourceTaskId === taskId && item.path === file.path);
  if (existing) return existing;
  const asset: ProductionAsset = {
    id: randomUUID(), type: file.mediaType, path: file.path, mimeType: file.mimeType, sourceTaskId: taskId,
    name: file.path.split(/[\\/]/).at(-1), createdAt: Date.now(), version: 1, confirmed: false,
  };
  document.assets.push(asset);
  return asset;
}

function shotOffset(document: ProductionDocument, shotId: string) {
  let offset = 0;
  for (const episode of document.episodes) for (const scene of episode.scenes) for (const shot of scene.shots) {
    if (shot.id === shotId) return offset;
    offset += shot.duration;
  }
  return offset;
}
export async function syncProductionGeneration(cwd: string, expectedRevision: number | undefined, resume: boolean, owner?: AuthIdentity | null) {
  const document = await loadProduction(cwd);
  if (expectedRevision !== undefined && document.revision !== expectedRevision) invalid("制作数据已更新，请重新加载后同步", 409);
  const taskIds = new Set<string>();
  for (const take of allShots(document).flatMap(item => item.takes)) if (take.taskId && take.status === "generating") taskIds.add(take.taskId);
  for (const job of document.generationJobs) if (job.status === "generating") taskIds.add(job.taskId);
  if (!taskIds.size) return document;
  const statuses = await mediaTaskStatus(cwd, [...taskIds], resume, owner) as TaskSnapshot[];
  const byTask = new Map(statuses.map(item => [item.taskId, item]));
  return mutateProduction(cwd, document.revision, "generation:sync", latest => {
    for (const shot of allShots(latest)) for (const take of shot.takes) {
      if (!take.taskId || take.status !== "generating") continue;
      const task = byTask.get(take.taskId);
      if (!task) continue;
      if (task.state === "succeeded" && task.result?.data?.length) {
        const assets = task.result.data.map(file => assetForResult(latest, task.taskId, file));
        take.outputAssetId = assets[0]!.id;
        take.status = "completed";
        take.completedAt = Date.now();
        take.updatedAt = Date.now();
        take.durationMs = Math.max(0, take.completedAt - take.createdAt);
        delete take.error;
      } else if (task.state === "failed" || task.state === "cancelled" || task.state === "interrupted" && task.resumable === false) {
        take.status = "failed";
        take.error = task.result?.message ?? "生成失败或任务记录不存在";
        take.updatedAt = Date.now();
      } else {
        take.updatedAt = Date.now();
        if (task.result?.message) take.error = task.result.message;
      }
    }
    for (const job of latest.generationJobs) {
      if (job.status !== "generating") continue;
      const task = byTask.get(job.taskId);
      if (!task) continue;
      if (task.state === "succeeded" && task.result?.data?.length) {
        const assets = task.result.data.map(file => assetForResult(latest, task.taskId, file));
        job.assetId = assets[0]!.id;
        job.status = "completed";
        delete job.error;
        if (job.targetId && ["storyboard", "shotImage", "blocking"].includes(job.kind)) {
          const shot = locateShot(latest, job.targetId);
          if (shot && job.kind === "storyboard") shot.storyboardAssetId = assets[0]!.id;
          if (shot && job.kind === "shotImage") shot.shotImageAssetId = assets[0]!.id;
          if (shot && job.kind === "blocking") shot.blockingAssetId = assets[0]!.id;
        }
        if (job.kind === "voiceDesign" && job.targetId) {
          const character = latest.characters.find(item => item.id === job.targetId);
          if (character) {
            character.voice.previewAssetId = assets[0]!.id;
            character.updatedAt = Date.now();
            character.revision += 1;
          }
        }
        if (job.kind === "voice" && job.targetId) {
          const shot = locateShot(latest, job.targetId);
          const asset = assets[0]!;
          if (shot && !latest.timeline.some(item => item.assetId === asset.id)) {
            const start = shotOffset(latest, shot.id);
            latest.timeline.push({ id: randomUUID(), kind: "audio", shotId: shot.id, assetId: asset.id, start, duration: shot.duration, track: "dialogue", volume: 1, muted: false, transition: "cut" });
            if (shot.dialogue.trim() && !latest.timeline.some(item => item.kind === "subtitle" && item.shotId === shot.id)) {
              latest.timeline.push({ id: randomUUID(), kind: "subtitle", shotId: shot.id, start, duration: shot.duration, track: "subtitle", text: shot.dialogue, volume: 1, muted: false, transition: "cut" });
            }
          }
        }
        if ((job.kind === "music" || job.kind === "sfx") && !latest.timeline.some(item => item.assetId === assets[0]!.id)) {
          const duration = Math.max(0.1, allShots(latest).reduce((sum, shot) => sum + shot.duration, 0));
          latest.timeline.push({ id: randomUUID(), kind: job.kind, assetId: assets[0]!.id, start: 0, duration, track: job.kind, volume: 1, muted: false, transition: "cut" });
        }
      } else if (task.state === "failed" || task.state === "cancelled" || task.state === "interrupted" && task.resumable === false) {
        job.status = "failed";
        job.error = task.result?.message ?? "生成失败或任务记录不存在";
      }
      job.updatedAt = Date.now();
    }
  });
}

export async function cancelProductionGeneration(cwd: string, expectedRevision: number, taskIds: string[], owner?: AuthIdentity | null) {
  await cancelMediaTasks(cwd, taskIds, owner);
  return mutateProduction(cwd, expectedRevision, "generation:cancel", document => {
    for (const take of allShots(document).flatMap(item => item.takes)) {
      if (take.taskId && taskIds.includes(take.taskId) && take.status === "generating") Object.assign(take, { status: "failed", error: "已取消", updatedAt: Date.now() });
    }
    for (const job of document.generationJobs) if (taskIds.includes(job.taskId) && job.status === "generating") Object.assign(job, { status: "failed", error: "已取消", updatedAt: Date.now() });
  });
}
export async function selectProductionTake(cwd: string, expectedRevision: number, shotId: string, takeId: string) {
  return mutateProduction(cwd, expectedRevision, "take:select", document => {
    const shot = locateShot(document, shotId) ?? invalid("镜头不存在", 404);
    const take = shot.takes.find(item => item.id === takeId) ?? invalid("Take 不存在", 404);
    if (!take.outputAssetId) invalid("该 Take 尚无可用输出", 409);
    for (const item of shot.takes) item.selected = item.id === takeId;
    shot.selectedTakeId = takeId;
    take.status = "confirmed";
    shot.updatedAt = Date.now();
    document.timeline = document.timeline.filter(item => item.kind !== "video");
    let offset = 0;
    for (const currentShot of allShots(document)) {
      if (currentShot.selectedTakeId) {
        const selected = currentShot.takes.find(item => item.id === currentShot.selectedTakeId);
        if (selected?.outputAssetId) document.timeline.push({
          id: randomUUID(), kind: "video", shotId: currentShot.id, takeId: selected.id, assetId: selected.outputAssetId,
          start: offset, duration: currentShot.duration, track: "video", volume: 1, muted: false, transition: "cut",
        });
      }
      offset += currentShot.duration;
    }
  });
}

export async function attachReference(cwd: string, expectedRevision: number, input: {
  targetType: "character" | "location" | "prop"; targetId: string; assetId: string; kind?: string; confirmed?: boolean;
}) {
  const document = await loadProduction(cwd);
  const candidate = document.assets.find(item => item.id === input.assetId);
  if (!candidate) invalid("素材不存在", 404);
  if (candidate.type !== "image") invalid("参考图必须是图片素材");
  const resolved = await resolveWorkspacePath(cwd, candidate.path);
  const info = await lstat(resolved.path);
  if (!info.isFile() || info.isSymbolicLink()) invalid("参考素材不是有效文件", 409);
  return mutateProduction(cwd, expectedRevision, "asset:reference", document => {
    const asset = document.assets.find(item => item.id === input.assetId) ?? invalid("素材不存在", 404);
    if (asset.type !== "image") invalid("参考图必须是图片素材");
    const item = input.targetType === "character" ? document.characters.find(entry => entry.id === input.targetId)
      : input.targetType === "location" ? document.locations.find(entry => entry.id === input.targetId)
        : document.props.find(entry => entry.id === input.targetId);
    if (!item) invalid("参考资产所属实体不存在", 404);
    let reference = item.referenceImages.find(entry => entry.assetId === input.assetId);
    if (!reference) {
      reference = { id: randomUUID(), assetId: input.assetId, kind: input.kind ?? "reference", confirmed: input.confirmed === true };
      item.referenceImages.push(reference);
    } else if (input.confirmed === true) reference.confirmed = true;
    item.updatedAt = Date.now();
    item.revision += 1;
  });
}

export async function confirmProductionEntity(cwd: string, expectedRevision: number, targetType: string, targetId: string | undefined, confirmed: boolean) {
  return mutateProduction(cwd, expectedRevision, "entity:confirm", document => {
    if (["synopsis", "world", "characters", "locations", "props", "episodes", "timeline"].includes(targetType)) {
      document.confirmedSections[targetType] = confirmed;
      return;
    }
    if (targetType === "character") {
      const item = document.characters.find(entry => entry.id === targetId) ?? invalid("角色不存在", 404);
      item.confirmed = confirmed;
      item.updatedAt = Date.now();
      return;
    }
    if (targetType === "location") {
      const item = document.locations.find(entry => entry.id === targetId) ?? invalid("场景不存在", 404);
      item.confirmed = confirmed;
      item.updatedAt = Date.now();
      return;
    }
    if (targetType === "prop") {
      const item = document.props.find(entry => entry.id === targetId) ?? invalid("道具不存在", 404);
      item.confirmed = confirmed;
      item.updatedAt = Date.now();
      return;
    }
    if (targetType === "episode") {
      const item = document.episodes.find(entry => entry.id === targetId);
      if (!item) invalid("分集不存在", 404);
      item.confirmed = confirmed;
      item.updatedAt = Date.now();
      return;
    }
    if (targetType === "scene") {
      const item = document.episodes.flatMap(entry => entry.scenes).find(entry => entry.id === targetId) ?? invalid("场次不存在", 404);
      item.confirmed = confirmed;
      item.updatedAt = Date.now();
      return;
    }
    if (targetType === "shot") {
      const item = locateShot(document, targetId!) ?? invalid("镜头不存在", 404);
      item.confirmed = confirmed;
      item.updatedAt = Date.now();
      return;
    }
    invalid("确认对象类型无效");
  });
}

export async function productionImpact(cwd: string, targetType: "character" | "location" | "prop", targetId: string) {
  const document = await loadProduction(cwd);
  const shots = document.episodes.flatMap(episode => episode.scenes.flatMap(scene => scene.shots.flatMap(shot => {
    const affected = targetType === "character" ? shot.characterIds.includes(targetId)
      : targetType === "prop" ? shot.propIds.includes(targetId) : scene.locationId === targetId;
    return affected ? [{ episodeNumber: episode.number, sceneNumber: scene.number, shotId: shot.id, shotNumber: shot.number, title: shot.title }] : [];
  })));
  return { targetType, targetId, shots, count: shots.length };
}

