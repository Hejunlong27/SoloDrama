import { createHash } from "node:crypto";
import { basename, extname, join, relative } from "node:path";
import { lstat, readFile, readdir, realpath } from "@solodrama/file";
import type { ProductionAsset, ProductionCanvasBinding, ProductionDocument } from "@solodrama/production";
import { loadProduction, mutateProduction } from "./store";
import { resolveWorkspacePath } from "@/utils/workspace/files";

export type CanvasSourceKind = "script" | "image" | "video" | "audio";
export type CanvasSuggestedTarget = "episode" | "character" | "location" | "prop" | "shot" | "asset";
export type CanvasSource = {
  id: string;
  sourceHash: string;
  canvasPath: string;
  canvasName: string;
  nodeId: string;
  kind: CanvasSourceKind;
  label: string;
  typeLabel: string;
  preview?: string;
  textPath?: string;
  mediaPath?: string;
  mediaMimeType?: string;
  prompt?: string;
  model?: string;
  suggestedTarget: CanvasSuggestedTarget;
  binding?: ProductionCanvasBinding;
};

type CanvasNode = { id?: unknown; type?: unknown; data?: unknown };
type CanvasFile = { solodramaCanvas?: unknown; nodes?: unknown };

const skippedDirectories = new Set([".git", ".solodrama", ".agent", "assets", "outputs", "node_modules", "build", "dist"]);
const maxCanvasFiles = 4000;
const maxCanvasFileBytes = 8 * 1024 * 1024;
const maxPreviewBytes = 16 * 1024;

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
function text(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}
function digest(...values: string[]) {
  const hash = createHash("sha256");
  for (const value of values) hash.update(value).update("\0");
  return hash.digest("hex");
}
function outputMedia(node: CanvasNode, key: "image" | "video" | "audio") {
  const output = record(record(record(node.data).outputs)[key]);
  const value = record(output.value);
  const path = text(value.url);
  return path ? { path, mimeType: text(value.mimeType) || `${key}/octet-stream` } : undefined;
}
function suggestedTarget(label: string, kind: CanvasSourceKind): CanvasSuggestedTarget {
  if (kind === "script") return "episode";
  if (kind === "video") return "shot";
  if (kind === "audio") return "asset";
  if (/场景|地点|环境/.test(label)) return "location";
  if (/道具|物件/.test(label)) return "prop";
  if (/角色|人物|主角|配角|群演/.test(label)) return "character";
  return "asset";
}
function candidateKind(node: CanvasNode): CanvasSourceKind | undefined {
  const type = String(node.type ?? "").replace(/^remote-/, "");
  if (/textnode/i.test(type)) return "script";
  if (/audio/i.test(type) || outputMedia(node, "audio")) return "audio";
  if (/video/i.test(type) || outputMedia(node, "video")) return "video";
  if (/image/i.test(type) || outputMedia(node, "image")) return "image";
}
async function canvasFiles(root: string) {
  const files: string[] = [];
  async function walk(directory: string, depth: number) {
    if (depth > 12 || files.length >= maxCanvasFiles) return;
    const entries = await readdir(directory, { withFileTypes: true }).catch((error: NodeJS.ErrnoException) => {
      if (error.code === "ENOENT") return [];
      throw error;
    });
    for (const entry of entries.sort((left, right) => left.name.localeCompare(right.name))) {
      if (files.length >= maxCanvasFiles) break;
      const path = join(directory, entry.name);
      if (entry.isSymbolicLink()) continue;
      if (entry.isDirectory()) {
        if (!skippedDirectories.has(entry.name.toLowerCase())) await walk(path, depth + 1);
        continue;
      }
      if (entry.isFile() && extname(entry.name).toLowerCase() === ".json") files.push(path);
    }
  }
  await walk(root, 0);
  return files;
}

async function readCanvasText(root: string, path: string) {
  const resolved = await resolveWorkspacePath(root, path);
  const info = await lstat(resolved.path);
  if (!info.isFile() || info.isSymbolicLink() || info.size > 2 * 1024 * 1024) return "";
  return readFile(resolved.path, "utf8");
}
export async function previewCanvasSources(cwd: string) {
  const root = await realpath(cwd);
  const document = await loadProduction(root);
  const sources: CanvasSource[] = [];
  let canvasCount = 0;
  let skippedFiles = 0;
  for (const path of await canvasFiles(root)) {
    const info = await lstat(path);
    if (!info.isFile() || info.isSymbolicLink() || info.size > maxCanvasFileBytes) continue;
    let value: CanvasFile;
    try { value = JSON.parse(await readFile(path, "utf8")) as CanvasFile; }
    catch { skippedFiles += 1; continue; }
    if (value.solodramaCanvas !== true || !Array.isArray(value.nodes)) continue;
    canvasCount += 1;
    const canvasPath = relative(root, path).replaceAll("\\", "/");
    for (const item of value.nodes as CanvasNode[]) {
      const nodeId = text(item?.id);
      const kind = candidateKind(item);
      if (!nodeId || !kind) continue;
      const data = record(item.data);
      const media = kind === "script" ? undefined : outputMedia(item, kind);
      const label = text(data.label) || basename(canvasPath) || nodeId;
      const textPath = kind === "script" ? text(data.textPath) || `assets/${nodeId}/content.md` : undefined;
      let preview = text(data.prompt) || text(data.description);
      if (textPath) preview = (await readCanvasText(root, textPath).catch(() => "")).slice(0, maxPreviewBytes);
      const sourceId = digest(canvasPath, nodeId);
      const sourceHash = digest(JSON.stringify(item), media?.path ?? "", preview ?? "");
      const binding = document.canvasBindings.find(entry => entry.sourceId === sourceId);
      sources.push({
        id: sourceId, sourceHash, canvasPath, canvasName: basename(canvasPath), nodeId, kind,
        label, typeLabel: String(item.type ?? "").replace(/^remote-/, "") || kind,
        ...(preview ? { preview } : {}), ...(textPath ? { textPath } : {}),
        ...(media ? { mediaPath: media.path, mediaMimeType: media.mimeType } : {}),
        ...(text(data.prompt) ? { prompt: text(data.prompt) } : {}), ...(text(data.model) ? { model: text(data.model) } : {}),
        suggestedTarget: suggestedTarget(label, kind), ...(binding ? { binding } : {}),
      });
    }
  }
  return { sources, canvasCount, boundCount: sources.filter(source => !!source.binding).length, skippedFiles };
}
export type CanvasImportOptions = { targetType?: CanvasSuggestedTarget; targetId?: string };
function invalid(message: string, status = 400): never {
  throw Object.assign(new Error(message), { status });
}

async function sourceAsset(root: string, document: ProductionDocument, source: CanvasSource) {
  if (!source.mediaPath) return undefined;
  const resolved = await resolveWorkspacePath(root, source.mediaPath);
  const info = await lstat(resolved.path);
  if (!info.isFile() || info.isSymbolicLink()) invalid("画布输出不是有效文件", 409);
  const existing = document.assets.find(asset => asset.path === source.mediaPath);
  if (existing) return existing;
  const type = source.kind === "video" ? "video" : source.kind === "audio" ? "audio" : "image";
  const asset: ProductionAsset = {
    id: crypto.randomUUID(), type, path: source.mediaPath,
    mimeType: source.mediaMimeType || `${type}/octet-stream`, name: source.label,
    metadata: { canvasPath: source.canvasPath, nodeId: source.nodeId, sourceHash: source.sourceHash },
    version: 1, confirmed: false, createdAt: Date.now(),
  };
  document.assets.push(asset);
  return asset;
}
function importBinding(source: CanvasSource, entityType: ProductionCanvasBinding["entityType"], entityId: string): ProductionCanvasBinding {
  return {
    id: crypto.randomUUID(), sourceId: source.id, entityType, entityId,
    canvasPath: source.canvasPath, nodeId: source.nodeId, relation: "source",
    sourceHash: source.sourceHash, importedAt: Date.now(),
  };
}

function stagingScene(document: ProductionDocument, sceneId?: string) {
  if (sceneId) {
    const existing = document.episodes.flatMap(episode => episode.scenes).find(scene => scene.id === sceneId);
    if (existing) return existing;
    invalid("目标场次不存在", 404);
  }
  let episode = document.episodes.find(item => item.title === "画布导入");
  if (!episode) {
    episode = { id: crypto.randomUUID(), number: Math.max(0, ...document.episodes.map(item => item.number)) + 1, title: "画布导入", synopsis: "", script: "", status: "draft", scenes: [], confirmed: false, revision: 0, createdAt: Date.now(), updatedAt: Date.now() };
    document.episodes.push(episode);
  }
  let scene = episode.scenes.find(item => item.title === "未归档镜头");
  if (!scene) {
    scene = { id: crypto.randomUUID(), episodeId: episode.id, number: Math.max(0, ...episode.scenes.map(item => item.number)) + 1, title: "未归档镜头", description: "从旧画布节点显式导入，等待归档。", characterIds: [], propIds: [], status: "draft", shots: [], confirmed: false, revision: 0, createdAt: Date.now(), updatedAt: Date.now() };
    episode.scenes.push(scene);
  }
  return scene;
}
export async function importCanvasSource(cwd: string, expectedRevision: number, sourceId: string, options: CanvasImportOptions = {}) {
  const root = await realpath(cwd);
  const preview = await previewCanvasSources(root);
  const source = preview.sources.find(item => item.id === sourceId) ?? invalid("画布来源不存在或已变化，请刷新后重试", 404);
  if (source.binding) invalid("该画布来源已经导入，请勿重复创建实体", 409);
  let binding: ProductionCanvasBinding | undefined;
  const document = await mutateProduction(root, expectedRevision, "canvas:import", async latest => {
    const now = Date.now();
    if (source.kind === "script") {
      const script = source.textPath ? (await readCanvasText(root, source.textPath)).trim() : source.preview?.trim() ?? "";
      if (!script) invalid("文本节点没有可导入的正文", 409);
      let episode = options.targetId ? latest.episodes.find(item => item.id === options.targetId) : undefined;
      if (options.targetId && !episode) invalid("目标分集不存在", 404);
      if (!episode) {
        episode = { id: crypto.randomUUID(), number: Math.max(0, ...latest.episodes.map(item => item.number)) + 1, title: source.label, synopsis: "", script: "", status: "draft", scenes: [], confirmed: false, revision: 0, createdAt: now, updatedAt: now };
        latest.episodes.push(episode);
      }
      episode.script = [episode.script, script].filter(Boolean).join("\n\n");
      episode.updatedAt = now;
      episode.revision += 1;
      binding = importBinding(source, "episode", episode.id);
    } else if (source.kind === "image") {
      const targetType = options.targetType ?? source.suggestedTarget;
      if (!["character", "location", "prop", "asset"].includes(targetType)) invalid("图片只能导入为角色、场景、道具或素材");
      const asset = await sourceAsset(root, latest, source);
      if (targetType === "asset") {
        if (!asset) invalid("图片节点没有可导入的输出文件", 409);
        binding = importBinding(source, "asset", asset.id);
      } else {
        let entityId = options.targetId;
        if (targetType === "character") {
          let entity = entityId ? latest.characters.find(item => item.id === entityId) : undefined;
          if (entityId && !entity) invalid("目标角色不存在", 404);
          if (!entity) {
            entity = { id: crypto.randomUUID(), name: source.label, description: source.preview ?? "", appearance: "", personality: "", age: "", clothingVersions: [], visualProfile: { face: "", hair: "", body: "", style: "" }, referenceImages: [], voice: {}, relationships: [], confirmed: false, revision: 0, createdAt: now, updatedAt: now };
            latest.characters.push(entity);
          }
          if (asset && !entity.referenceImages.some(reference => reference.assetId === asset.id)) entity.referenceImages.push({ id: crypto.randomUUID(), assetId: asset.id, kind: "canvas", confirmed: false });
          entity.updatedAt = now; entity.revision += 1; entityId = entity.id;
        } else if (targetType === "location") {
          let entity = entityId ? latest.locations.find(item => item.id === entityId) : undefined;
          if (entityId && !entity) invalid("目标场景不存在", 404);
          if (!entity) {
            entity = { id: crypto.randomUUID(), name: source.label, description: source.preview ?? "", spatialStructure: "", lighting: "", colorPalette: "", timeOfDay: "", atmosphere: "", referenceImages: [], propIds: [], confirmed: false, revision: 0, createdAt: now, updatedAt: now };
            latest.locations.push(entity);
          }
          if (asset && !entity.referenceImages.some(reference => reference.assetId === asset.id)) entity.referenceImages.push({ id: crypto.randomUUID(), assetId: asset.id, kind: "canvas", confirmed: false });
          entity.updatedAt = now; entity.revision += 1; entityId = entity.id;
        } else {
          let entity = entityId ? latest.props.find(item => item.id === entityId) : undefined;
          if (entityId && !entity) invalid("目标道具不存在", 404);
          if (!entity) {
            entity = { id: crypto.randomUUID(), name: source.label, description: source.preview ?? "", referenceImages: [], confirmed: false, revision: 0, createdAt: now, updatedAt: now };
            latest.props.push(entity);
          }
          if (asset && !entity.referenceImages.some(reference => reference.assetId === asset.id)) entity.referenceImages.push({ id: crypto.randomUUID(), assetId: asset.id, kind: "canvas", confirmed: false });
          entity.updatedAt = now; entity.revision += 1; entityId = entity.id;
        }
        if (!entityId) invalid("画布来源导入失败");
        binding = importBinding(source, targetType, entityId);
      }
    } else if (source.kind === "video") {
      const asset = await sourceAsset(root, latest, source);
      const scene = stagingScene(latest, options.targetId);
      const shotId = crypto.randomUUID();
      const prompt = source.prompt?.slice(0, 10000) ?? "";
      const take = asset ? {
        id: crypto.randomUUID(), shotId, number: 1, status: "completed" as const, selected: false,
        providerId: "canvas", modelId: source.model || "canvas", prompt: prompt.slice(0, 100000), negativePrompt: "",
        referenceAssetIds: [], parameters: { canvasPath: source.canvasPath, nodeId: source.nodeId },
        outputAssetId: asset.id, createdAt: now, updatedAt: now, completedAt: now,
      } : undefined;
      const shot = {
        id: shotId, sceneId: scene.id, number: Math.max(0, ...scene.shots.map(item => item.number)) + 1,
        title: source.label, duration: 5, shotSize: "中景", cameraAngle: "平视", cameraMovement: "固定",
        description: prompt.slice(0, 10000), action: "", positions: "", expressions: "", dialogue: "", ambientSound: "",
        characterIds: [], propIds: [], firstFramePrompt: "", lastFramePrompt: "", videoPrompt: prompt.slice(0, 100000),
        takes: take ? [take] : [], confirmed: false, revision: 0, createdAt: now, updatedAt: now,
      };
      scene.shots.push(shot);
      scene.updatedAt = now; scene.revision += 1;
      binding = importBinding(source, "shot", shot.id);
    } else if (source.kind === "audio") {
      const asset = await sourceAsset(root, latest, source);
      if (!asset) invalid("音频节点没有可导入的输出文件", 409);
      binding = importBinding(source, "asset", asset.id);
    }
    if (!binding) invalid("不支持的画布来源类型");
    latest.canvasBindings.push(binding);
  });
  const imported = document.canvasBindings.find(item => item.sourceId === source.id);
  return { document, binding: imported };
}