import { createHash } from "node:crypto";
import { lstat, readFile, realpath } from "@solodrama/file";
import { join } from "node:path";
import { emptyProductionDocument, productionDocumentSchema, scriptUnderstandingSchema, type ProductionDocument } from "@solodrama/production";
import { lockWorkspaceFiles, resolveWorkspacePath, writeWorkspaceFile } from "@/utils/workspace/files";

export const productionPath = ".solodrama/production.json";
export type ProductionSource = { kind: string; input: string; providerId?: string; modelId?: string; section: string; rawResponse?: string };
function invalid(message: string, status = 400): never { throw Object.assign(new Error(message), { status }); }
function identity(value: string) { return value.trim().normalize("NFKC").toLowerCase(); }
function now() { return Date.now(); }
function uid() { return crypto.randomUUID(); }
async function projectName(cwd: string) {
  try {
    const value: unknown = JSON.parse(await readFile(join(cwd, ".solodrama/project.json"), "utf8"));
    if (value && typeof value === "object" && typeof (value as Record<string, unknown>).name === "string") return (value as Record<string, unknown>).name as string;
  } catch { /* ACT: 旧项目没有设置时使用目录名。 */ }
  return cwd.split(/[\\/]/).filter(Boolean).at(-1) || "SoloDrama 项目";
}
export async function loadProduction(cwd: string): Promise<ProductionDocument> {
  const root = await realpath(cwd);
  const { path } = await resolveWorkspacePath(root, productionPath, true);
  const info = await lstat(path).catch((cause: NodeJS.ErrnoException) => cause.code === "ENOENT" ? null : Promise.reject(cause));
  if (!info) return saveProduction(root, emptyProductionDocument(await projectName(root)), 0, "create");
  if (!info.isFile() || info.isSymbolicLink() || info.size > 20 * 1024 * 1024) invalid("制作领域数据文件无效", 503);
  try { return productionDocumentSchema.parse(JSON.parse(await readFile(path, "utf8"))); }
  catch { invalid("制作领域数据文件损坏，请从备份恢复", 503); }
}
export async function saveProduction(cwd: string, input: ProductionDocument, expectedRevision: number, action: string) {
  const root = await realpath(cwd);
  const parsed = productionDocumentSchema.parse(input);
  if (parsed.revision !== expectedRevision) invalid("制作数据已更新，请重新加载后保存", 409);
  const { path } = await resolveWorkspacePath(root, productionPath, true);
  const release = lockWorkspaceFiles([path]);
  try {
    const current = await lstat(path).catch((cause: NodeJS.ErrnoException) => cause.code === "ENOENT" ? null : Promise.reject(cause));
    let previous: ProductionDocument | undefined;
    if (current) {
      if (!current.isFile() || current.isSymbolicLink() || current.size > 20 * 1024 * 1024) invalid("制作领域数据文件无效", 503);
      try { previous = productionDocumentSchema.parse(JSON.parse(await readFile(path, "utf8"))); }
      catch { invalid("制作领域数据文件损坏，不能覆盖", 503); }
      if (previous.revision !== expectedRevision) invalid("制作数据已更新，请重新加载后保存", 409);
    }
    const revisions = [...(previous?.revisions ?? parsed.revisions)];
    if (previous) {
      const snapshot = JSON.stringify({ ...previous, revisions: [] });
      if (Buffer.byteLength(snapshot, "utf8") <= 12 * 1024 * 1024) {
        revisions.unshift({ revision: previous.revision, action, createdAt: now(), snapshot });
      }
    }
    let document = productionDocumentSchema.parse({ ...parsed, revision: expectedRevision + 1, revisions: revisions.slice(0, 20), updatedAt: now() });
    // ACT: 快照同时受时间上限和文件总量限制，避免历史累积到读取上限后把项目锁死。
    while (document.revisions.length && Buffer.byteLength(JSON.stringify(document, null, 2), "utf8") > 18 * 1024 * 1024) {
      document = productionDocumentSchema.parse({ ...document, revisions: document.revisions.slice(0, -1) });
    }
    const content = `${JSON.stringify(document, null, 2)}\n`;
    if (Buffer.byteLength(content, "utf8") > 20 * 1024 * 1024) invalid("制作数据超过 20 MB，请拆分项目或清理过大的来源文本", 413);
    await writeWorkspaceFile(path, content);
    return document;
  } finally { release(); }
}
export async function mutateProduction(cwd: string, expectedRevision: number, action: string, mutate: (document: ProductionDocument) => void | Promise<void>) {
  const document = await loadProduction(cwd);
  if (document.revision !== expectedRevision) invalid("制作数据已更新，请重新加载后保存", 409);
  await mutate(document);
  return saveProduction(cwd, document, expectedRevision, action);
}
export async function applyUnderstanding(cwd: string, expectedRevision: number, rawResult: unknown, source: ProductionSource, options: { force?: boolean; sections?: string[] } = {}) {
  const result = scriptUnderstandingSchema.parse(rawResult);
  const document = await loadProduction(cwd);
  if (document.revision !== expectedRevision) invalid("制作数据已更新，请重新加载后应用 AI 结果", 409);
  const sections = new Set(options.sections?.length ? options.sections : ["synopsis", "world", "characters", "locations", "props", "episodes", "timeline"]);
  const force = options.force === true;
  const canWrite = (section: string) => force || document.confirmedSections[section] !== true;
  if (sections.has("synopsis") && canWrite("synopsis")) document.synopsis = result.synopsis;
  if (sections.has("world") && canWrite("world")) document.world = result.world;
  if (sections.has("characters") && canWrite("characters")) {
    const byName = new Map(document.characters.map(item => [identity(item.name), item]));
    for (const input of result.characters) {
      const existing = byName.get(identity(input.name));
      if (existing?.confirmed && !force) continue;
      const item = existing ?? { id: uid(), name: input.name, description: "", appearance: "", personality: "", age: "", clothingVersions: [], visualProfile: { face: "", hair: "", body: "", style: "" }, referenceImages: [], voice: {}, relationships: [], confirmed: false, revision: 0, createdAt: now(), updatedAt: now() };
      Object.assign(item, { name: input.name, description: input.description, appearance: input.appearance, visualDescription: input.appearance || item.visualDescription, personality: input.personality, age: input.age, updatedAt: now(), revision: item.revision + 1 });
      if (input.voice) item.voice = { ...item.voice, voiceId: input.voice };
      byName.set(identity(item.name), item);
      if (!existing) document.characters.push(item);
    }
    for (const input of result.characters) {
      const item = byName.get(identity(input.name));
      if (!item) continue;
      item.relationships = input.relationships.flatMap(relation => { const target = byName.get(identity(relation.name)); return target ? [{ characterId: target.id, label: relation.label, description: relation.description }] : []; });
    }
  }
  if (sections.has("locations") && canWrite("locations")) {
    const byName = new Map(document.locations.map(item => [identity(item.name), item]));
    for (const input of result.locations) {
      const existing = byName.get(identity(input.name));
      if (existing?.confirmed && !force) continue;
      const item = existing ?? { id: uid(), name: input.name, description: "", spatialStructure: "", lighting: "", colorPalette: "", timeOfDay: "", atmosphere: "", referenceImages: [], propIds: [], confirmed: false, revision: 0, createdAt: now(), updatedAt: now() };
      Object.assign(item, input, { updatedAt: now(), revision: item.revision + 1 });
      byName.set(identity(item.name), item);
      if (!existing) document.locations.push(item);
    }
  }
  if (sections.has("props") && canWrite("props")) {
    const byName = new Map(document.props.map(item => [identity(item.name), item]));
    for (const input of result.props) {
      const existing = byName.get(identity(input.name));
      if (existing?.confirmed && !force) continue;
      const item = existing ?? { id: uid(), name: input.name, description: "", referenceImages: [], confirmed: false, revision: 0, createdAt: now(), updatedAt: now() };
      Object.assign(item, input, { updatedAt: now(), revision: item.revision + 1 });
      byName.set(identity(item.name), item);
      if (!existing) document.props.push(item);
    }
  }
  const characterByName = new Map(document.characters.map(item => [identity(item.name), item.id]));
  const locationByName = new Map(document.locations.map(item => [identity(item.name), item.id]));
  const propByName = new Map(document.props.map(item => [identity(item.name), item.id]));
  if (sections.has("episodes") && canWrite("episodes")) {
    const episodeByNumber = new Map(document.episodes.map(item => [item.number, item]));
    for (const inputEpisode of result.episodes) {
      let episode = episodeByNumber.get(inputEpisode.number);
      if (episode?.confirmed && !force) continue;
      if (!episode) { episode = { id: uid(), number: inputEpisode.number, title: "", synopsis: "", script: "", status: "draft", scenes: [], confirmed: false, revision: 0, createdAt: now(), updatedAt: now() }; document.episodes.push(episode); }
      Object.assign(episode, { title: inputEpisode.title, synopsis: inputEpisode.synopsis, script: inputEpisode.script, updatedAt: now(), revision: episode.revision + 1 });
      const sceneByNumber = new Map(episode.scenes.map(item => [item.number, item]));
      for (const inputScene of inputEpisode.scenes) {
        let scene = sceneByNumber.get(inputScene.number);
        if (scene?.confirmed && !force) continue;
        if (!scene) { scene = { id: uid(), episodeId: episode.id, number: inputScene.number, title: "", description: "", characterIds: [], propIds: [], status: "draft", shots: [], confirmed: false, revision: 0, createdAt: now(), updatedAt: now() }; episode.scenes.push(scene); }
        Object.assign(scene, { title: inputScene.title, description: inputScene.description, locationId: locationByName.get(identity(inputScene.locationName)), characterIds: inputScene.characterNames.flatMap(name => characterByName.get(identity(name)) ?? []), updatedAt: now(), revision: scene.revision + 1 });
        const shotByNumber = new Map(scene.shots.map(item => [item.number, item]));
        for (const inputShot of inputScene.shots) {
          let shot = shotByNumber.get(inputShot.number);
          if (shot?.confirmed && !force) continue;
          if (!shot) { shot = { id: uid(), sceneId: scene.id, number: inputShot.number, title: "", duration: 5, shotSize: "中景", cameraAngle: "平视", cameraMovement: "固定", description: "", action: "", positions: "", expressions: "", dialogue: "", ambientSound: "", characterIds: [], propIds: [], firstFramePrompt: "", lastFramePrompt: "", videoPrompt: "", takes: [], confirmed: false, revision: 0, createdAt: now(), updatedAt: now() }; scene.shots.push(shot); }
          Object.assign(shot, { number: inputShot.number, duration: inputShot.duration, shotSize: inputShot.shotSize, cameraAngle: inputShot.cameraAngle, cameraMovement: inputShot.cameraMovement, description: inputShot.description, action: inputShot.action, positions: inputShot.positions, expressions: inputShot.expressions, dialogue: inputShot.dialogue, ambientSound: inputShot.ambientSound, characterIds: inputShot.characterNames.flatMap(name => characterByName.get(identity(name)) ?? []), propIds: inputShot.propNames.flatMap(name => propByName.get(identity(name)) ?? []), firstFramePrompt: inputShot.firstFramePrompt, lastFramePrompt: inputShot.lastFramePrompt, videoPrompt: inputShot.videoPrompt, updatedAt: now(), revision: shot.revision + 1 });
        }
        scene.shots.sort((left, right) => left.number - right.number);
      }
      episode.scenes.sort((left, right) => left.number - right.number);
    }
    document.episodes.sort((left, right) => left.number - right.number);
  }
  if (sections.has("timeline")) document.storyTimeline = result.timeline.map(item => ({ id: uid(), ...item }));
  document.continuityWarnings = result.continuityWarnings;
  document.storyIdea ||= source.input;
  document.sources.unshift({ id: uid(), kind: source.kind, providerId: source.providerId, modelId: source.modelId, inputHash: createHash("sha256").update(source.input).digest("hex"), section: source.section, rawResponse: source.rawResponse, createdAt: now() });
  document.sources = document.sources.slice(0, 50);
  return saveProduction(cwd, document, expectedRevision, "ai:understand");
}