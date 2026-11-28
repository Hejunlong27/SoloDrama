import { z } from "zod";

const id = z.uuid();
const timestamp = z.number().finite().nonnegative();
const mediaType = z.enum(["image", "video", "audio"]);
const status = z.enum(["draft", "generating", "completed", "failed", "confirmed", "rejected"]);

export const productionAssetSchema = z.object({
  id,
  type: mediaType,
  path: z.string().min(1).max(4096),
  mimeType: z.string().min(1).max(256),
  name: z.string().max(512).optional(),
  sourceTaskId: z.string().max(128).optional(),
  providerId: z.string().max(96).optional(),
  modelId: z.string().max(256).optional(),
  instanceId: z.string().max(128).optional(),
  workflowId: z.string().max(128).optional(),
  workflowVersion: z.number().int().positive().optional(),
  metadata: z.record(z.string(), z.json()).optional(),
  version: z.number().int().positive().default(1),
  previousAssetId: id.optional(),
  confirmed: z.boolean().default(false),
  createdAt: timestamp,
});

export const canvasBindingSchema = z.object({
  id,
  sourceId: z.string().regex(/^[a-f0-9]{64}$/),
  entityType: z.enum(["episode", "character", "location", "prop", "shot", "asset"]),
  entityId: id,
  canvasPath: z.string().min(1).max(4096),
  nodeId: z.string().min(1).max(512),
  relation: z.enum(["source", "reference", "output"]).default("source"),
  sourceHash: z.string().regex(/^[a-f0-9]{64}$/),
  importedAt: timestamp,
});

export const generationJobSchema = z.object({
  id,
  taskId: z.string().min(1).max(128),
  kind: z.enum(["storyboard", "shotImage", "blocking", "characterReference", "locationReference", "propReference", "voice", "voiceDesign", "music", "sfx"]),
  mediaType: mediaType,
  targetId: id,
  providerId: z.string().max(96),
  modelId: z.string().max(256),
  status,
  assetId: id.optional(),
  error: z.string().max(4000).optional(),
  createdAt: timestamp,
  updatedAt: timestamp,
});

export const takeSchema = z.object({
  id,
  shotId: id,
  number: z.number().int().positive(),
  status,
  selected: z.boolean().default(false),
  taskId: z.string().max(128).optional(),
  workflowId: z.string().max(128).optional(),
  workflowVersion: z.number().int().positive().optional(),
  providerId: z.string().max(96).optional(),
  instanceId: z.string().max(128).optional(),
  modelId: z.string().max(256).optional(),
  prompt: z.string().max(100000).default(""),
  negativePrompt: z.string().max(100000).default(""),
  referenceAssetIds: z.array(id).default([]),
  seed: z.number().int().optional(),
  parameters: z.record(z.string(), z.json()).default({}),
  outputAssetId: id.optional(),
  createdAt: timestamp,
  updatedAt: timestamp,
  startedAt: timestamp.optional(),
  completedAt: timestamp.optional(),
  durationMs: z.number().int().nonnegative().optional(),
  error: z.string().max(4000).optional(),
});

export const shotSchema = z.object({
  id,
  sceneId: id,
  number: z.number().int().positive(),
  title: z.string().max(200).default(""),
  duration: z.number().positive().max(3600).default(5),
  shotSize: z.string().max(80).default("中景"),
  cameraAngle: z.string().max(80).default("平视"),
  cameraMovement: z.string().max(80).default("固定"),
  description: z.string().max(10000).default(""),
  action: z.string().max(10000).default(""),
  positions: z.string().max(10000).default(""),
  expressions: z.string().max(10000).default(""),
  dialogue: z.string().max(100000).default(""),
  ambientSound: z.string().max(10000).default(""),
  characterIds: z.array(id).default([]),
  propIds: z.array(id).default([]),
  firstFramePrompt: z.string().max(100000).default(""),
  lastFramePrompt: z.string().max(100000).default(""),
  videoPrompt: z.string().max(100000).default(""),
  h3VideoPrompt: z.string().max(100000).optional(),
  takes: z.array(takeSchema).default([]),
  selectedTakeId: id.optional(),
  storyboardAssetId: id.optional(),
  shotImageAssetId: id.optional(),
  blockingAssetId: id.optional(),
  continuationSourceShotId: id.optional(),
  continuationTakeId: id.optional(),
  generationOptions: z.object({
    storyboardEnabled: z.boolean().default(true),
    shotImageEnabled: z.boolean().default(false),
    blockingEnabled: z.boolean().default(false),
    useStoryboardReference: z.boolean().default(true),
    useShotImageReference: z.boolean().default(true),
    useBlockingReference: z.boolean().default(true),
    continueFromPreviousShot: z.boolean().default(false),
  }).optional(),
  confirmed: z.boolean().default(false),
  revision: z.number().int().nonnegative().default(0),
  createdAt: timestamp,
  updatedAt: timestamp,
});

export const sceneSchema = z.object({
  id,
  episodeId: id,
  number: z.number().int().positive(),
  title: z.string().max(200).default(""),
  description: z.string().max(20000).default(""),
  locationId: id.optional(),
  characterIds: z.array(id).default([]),
  propIds: z.array(id).default([]),
  status,
  shots: z.array(shotSchema).default([]),
  confirmed: z.boolean().default(false),
  revision: z.number().int().nonnegative().default(0),
  createdAt: timestamp,
  updatedAt: timestamp,
});

export const episodeSchema = z.object({
  id,
  number: z.number().int().positive(),
  title: z.string().max(200).default(""),
  synopsis: z.string().max(20000).default(""),
  script: z.string().max(2000000).default(""),
  status,
  scenes: z.array(sceneSchema).default([]),
  confirmed: z.boolean().default(false),
  revision: z.number().int().nonnegative().default(0),
  createdAt: timestamp,
  updatedAt: timestamp,
});

export const referenceImageSchema = z.object({ id, assetId: id, kind: z.string().max(80).default("reference"), confirmed: z.boolean().default(false) });

export const characterSchema = z.object({
  id,
  name: z.string().min(1).max(200),
  description: z.string().max(20000).default(""),
  appearance: z.string().max(20000).default(""),
  visualDescription: z.string().max(40000).optional(),
  personality: z.string().max(20000).default(""),
  age: z.string().max(80).default(""),
  clothingVersions: z.array(z.object({ id, name: z.string().max(160), description: z.string().max(10000).default(""), assetIds: z.array(id).default([]), confirmed: z.boolean().default(false) })).default([]),
  visualProfile: z.object({ face: z.string().max(10000).default(""), hair: z.string().max(10000).default(""), body: z.string().max(10000).default(""), style: z.string().max(10000).default("") }).default({ face: "", hair: "", body: "", style: "" }),
  referenceImages: z.array(referenceImageSchema).default([]),
  voice: z.object({ providerId: z.string().max(96).optional(), voiceId: z.string().max(256).optional(), speed: z.number().optional(), language: z.string().max(64).optional(), designPrompt: z.string().max(10000).optional(), previewText: z.string().max(10000).optional(), previewAssetId: id.optional(), emotion: z.string().max(256).optional(), instructions: z.string().max(10000).optional() }).default({}),
  relationships: z.array(z.object({ characterId: id, label: z.string().max(160), description: z.string().max(10000).default("") })).default([]),
  confirmed: z.boolean().default(false),
  revision: z.number().int().nonnegative().default(0),
  createdAt: timestamp,
  updatedAt: timestamp,
});

export const locationSchema = z.object({
  id,
  name: z.string().min(1).max(200),
  description: z.string().max(20000).default(""),
  spatialStructure: z.string().max(20000).default(""),
  lighting: z.string().max(10000).default(""),
  colorPalette: z.string().max(10000).default(""),
  timeOfDay: z.string().max(200).default(""),
  atmosphere: z.string().max(10000).default(""),
  referenceImages: z.array(referenceImageSchema).default([]),
  propIds: z.array(id).default([]),
  confirmed: z.boolean().default(false),
  revision: z.number().int().nonnegative().default(0),
  createdAt: timestamp,
  updatedAt: timestamp,
});

export const propSchema = z.object({
  id,
  name: z.string().min(1).max(200),
  description: z.string().max(20000).default(""),
  referenceImages: z.array(referenceImageSchema).default([]),
  confirmed: z.boolean().default(false),
  revision: z.number().int().nonnegative().default(0),
  createdAt: timestamp,
  updatedAt: timestamp,
});

export const timelineItemSchema = z.object({
  id,
  kind: z.enum(["video", "audio", "subtitle", "music", "sfx", "remotion"]),
  shotId: id.optional(),
  takeId: id.optional(),
  assetId: id.optional(),
  start: z.number().nonnegative(),
  duration: z.number().positive(),
  track: z.string().max(120),
  text: z.string().max(100000).optional(),
  volume: z.number().min(0).max(4).default(1),
  muted: z.boolean().default(false),
  transition: z.enum(["cut", "fade"]).default("cut"),
});

export const productionDocumentSchema = z.object({
  schemaVersion: z.literal(1),
  revision: z.number().int().nonnegative(),
  id,
  name: z.string().min(1).max(200),
  description: z.string().max(20000).default(""),
  storyIdea: z.string().max(1000000).default(""),
  synopsis: z.string().max(100000).default(""),
  world: z.string().max(100000).default(""),
  characters: z.array(characterSchema).default([]),
  locations: z.array(locationSchema).default([]),
  props: z.array(propSchema).default([]),
  storyTimeline: z.array(z.object({ id, title: z.string().max(200), description: z.string().max(10000).default(""), episodeNumber: z.number().int().positive().optional(), sceneNumber: z.number().int().positive().optional() })).default([]),
  continuityWarnings: z.array(z.string().max(2000)).default([]),
  episodes: z.array(episodeSchema).default([]),
  assets: z.array(productionAssetSchema).default([]),
  canvasBindings: z.array(canvasBindingSchema).default([]),
  generationJobs: z.array(generationJobSchema).default([]),
  timeline: z.array(timelineItemSchema).default([]),
  output: z.object({
    aspectRatio: z.enum(["9:16", "16:9", "1:1"]).default("9:16"),
    width: z.number().int().min(2).max(8192).default(1080),
    height: z.number().int().min(2).max(8192).default(1920),
    fps: z.number().positive().max(120).default(30),
    format: z.enum(["mp4", "mov"]).default("mp4"),
  }).default({ aspectRatio: "9:16", width: 1080, height: 1920, fps: 30, format: "mp4" }),
  sources: z.array(z.object({ id, kind: z.string().max(80), providerId: z.string().max(96).optional(), modelId: z.string().max(256).optional(), inputHash: z.string().max(128), section: z.string().max(120), rawResponse: z.string().max(500000).optional(), createdAt: timestamp })).default([]),
  revisions: z.array(z.object({ revision: z.number().int().nonnegative(), action: z.string().max(120), createdAt: timestamp, snapshot: z.string().max(16 * 1024 * 1024) })).max(20).default([]),
  confirmedSections: z.record(z.string(), z.boolean()).default({}),
  createdAt: timestamp,
  updatedAt: timestamp,
});

export const scriptUnderstandingSchema = z.object({
  synopsis: z.string().max(100000).default(""),
  world: z.string().max(100000).default(""),
  characters: z.array(z.object({ name: z.string().min(1).max(200), description: z.string().max(20000).default(""), appearance: z.string().max(20000).default(""), personality: z.string().max(20000).default(""), age: z.string().max(80).default(""), voice: z.string().max(1000).default(""), relationships: z.array(z.object({ name: z.string().max(200), label: z.string().max(160), description: z.string().max(10000).default("") })).default([]) })).default([]),
  locations: z.array(z.object({ name: z.string().min(1).max(200), description: z.string().max(20000).default(""), spatialStructure: z.string().max(20000).default(""), lighting: z.string().max(10000).default(""), colorPalette: z.string().max(10000).default(""), timeOfDay: z.string().max(200).default(""), atmosphere: z.string().max(10000).default("") })).default([]),
  props: z.array(z.object({ name: z.string().min(1).max(200), description: z.string().max(20000).default("") })).default([]),
  episodes: z.array(z.object({ number: z.number().int().positive(), title: z.string().max(200).default(""), synopsis: z.string().max(20000).default(""), script: z.string().max(2000000).default(""), scenes: z.array(z.object({ number: z.number().int().positive(), title: z.string().max(200).default(""), description: z.string().max(20000).default(""), locationName: z.string().max(200).default(""), characterNames: z.array(z.string().max(200)).default([]), shots: z.array(z.object({ number: z.number().int().positive(), duration: z.number().positive().max(3600).default(5), shotSize: z.string().max(80).default("中景"), cameraAngle: z.string().max(80).default("平视"), cameraMovement: z.string().max(80).default("固定"), description: z.string().max(10000).default(""), action: z.string().max(10000).default(""), positions: z.string().max(10000).default(""), expressions: z.string().max(10000).default(""), dialogue: z.string().max(100000).default(""), ambientSound: z.string().max(10000).default(""), characterNames: z.array(z.string().max(200)).default([]), propNames: z.array(z.string().max(200)).default([]), firstFramePrompt: z.string().max(100000).default(""), lastFramePrompt: z.string().max(100000).default(""), videoPrompt: z.string().max(100000).default("") })).default([]) })).default([]) })).default([]),
  timeline: z.array(z.object({ title: z.string().max(200), description: z.string().max(10000).default(""), episodeNumber: z.number().int().positive().optional(), sceneNumber: z.number().int().positive().optional() })).default([]),
  continuityWarnings: z.array(z.string().max(2000)).default([]),
});

export type ProductionAsset = z.infer<typeof productionAssetSchema>;
export type ProductionCanvasBinding = z.infer<typeof canvasBindingSchema>;
export type ProductionGenerationJob = z.infer<typeof generationJobSchema>;
export type ShotTake = z.infer<typeof takeSchema>;
export type ProductionShot = z.infer<typeof shotSchema>;
export type ProductionScene = z.infer<typeof sceneSchema>;
export type ProductionEpisode = z.infer<typeof episodeSchema>;
export type ProductionCharacter = z.infer<typeof characterSchema>;
export type ProductionLocation = z.infer<typeof locationSchema>;
export type ProductionProp = z.infer<typeof propSchema>;
export type ProductionTimelineItem = z.infer<typeof timelineItemSchema>;
export type ProductionDocument = z.infer<typeof productionDocumentSchema>;
export type ScriptUnderstanding = z.infer<typeof scriptUnderstandingSchema>;

export function emptyProductionDocument(name: string): ProductionDocument {
  const now = Date.now();
  return { schemaVersion: 1, revision: 0, id: crypto.randomUUID(), name, description: "", storyIdea: "", synopsis: "", world: "", characters: [], locations: [], props: [], storyTimeline: [], continuityWarnings: [], episodes: [], assets: [], timeline: [], canvasBindings: [], generationJobs: [], output: { aspectRatio: "9:16", width: 1080, height: 1920, fps: 30, format: "mp4" }, sources: [], revisions: [], confirmedSections: {}, createdAt: now, updatedAt: now };
}


