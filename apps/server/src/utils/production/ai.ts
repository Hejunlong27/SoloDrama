import type { Context } from "@earendil-works/pi-ai";
import { z } from "zod";
import { scriptUnderstandingSchema, type ScriptUnderstanding } from "@solodrama/production";
import { readFile, realpath } from "@solodrama/file";
import { join } from "node:path";
import { loadProduction } from "./store";
import { getConfiguredModel, streamAi } from "@/utils/ai";
import { translateError } from "@/lib/i18n";

const maxChunkChars = 50000;

function chunksOf(text: string) {
  if (text.length <= maxChunkChars) return [text];
  const chunks: string[] = [];
  let current = "";
  for (const paragraph of text.split(/(?<=\n)\s*(?=\S)/)) {
    if (paragraph.length > maxChunkChars) {
      for (let offset = 0; offset < paragraph.length; offset += maxChunkChars) {
        const part = paragraph.slice(offset, offset + maxChunkChars);
        if (current) { chunks.push(current); current = ""; }
        chunks.push(part);
      }
      continue;
    }
    if (current.length + paragraph.length > maxChunkChars) { chunks.push(current); current = ""; }
    current += paragraph;
  }
  if (current.trim()) chunks.push(current);
  return chunks;
}

function extractJson(text: string) {
  const trimmed = text.trim().replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/, "");
  try { return JSON.parse(trimmed); }
  catch {
    const start = trimmed.indexOf("{");
    const end = trimmed.lastIndexOf("}");
    if (start >= 0 && end > start) {
      try { return JSON.parse(trimmed.slice(start, end + 1)); }
      catch { /* 继续返回统一错误。 */ }
    }
    throw Object.assign(new Error("AI 返回的剧本结构不是有效 JSON，请重试或更换模型"), { code: "INVALID_RESPONSE" });
  }
}



function numericValue(value: unknown) {
  if (typeof value === "number") return value;
  if (typeof value !== "string") return value;
  const match = value.match(/-?\d+(?:\.\d+)?/);
  return match ? Number(match[0]) : value;
}

function integerValue(value: unknown) {
  const parsed = numericValue(value);
  return typeof parsed === "number" && Number.isFinite(parsed) ? Math.trunc(parsed) : value;
}

function normalizeUnderstanding(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return value;
  const result = structuredClone(value) as Record<string, unknown>;
  if (Array.isArray(result.episodes)) {
    result.episodes = result.episodes.map(inputEpisode => {
      if (!inputEpisode || typeof inputEpisode !== "object" || Array.isArray(inputEpisode)) return inputEpisode;
      const episode = inputEpisode as Record<string, unknown>;
      episode.number = integerValue(episode.number);
      if (Array.isArray(episode.scenes)) episode.scenes = episode.scenes.map(inputScene => {
        if (!inputScene || typeof inputScene !== "object" || Array.isArray(inputScene)) return inputScene;
        const scene = inputScene as Record<string, unknown>;
        scene.number = integerValue(scene.number);
        if (Array.isArray(scene.shots)) scene.shots = scene.shots.map(inputShot => {
          if (!inputShot || typeof inputShot !== "object" || Array.isArray(inputShot)) return inputShot;
          const shot = inputShot as Record<string, unknown>;
          shot.number = integerValue(shot.number);
          shot.duration = numericValue(shot.duration);
          return shot;
        });
        return scene;
      });
      return episode;
    });
  }
  if (Array.isArray(result.characters)) result.characters = result.characters.map(inputCharacter => {
    if (!inputCharacter || typeof inputCharacter !== "object" || Array.isArray(inputCharacter)) return inputCharacter;
    const character = inputCharacter as Record<string, unknown>;
    if (typeof character.age === "number" && Number.isFinite(character.age)) character.age = String(character.age);
    return character;
  });
  if (Array.isArray(result.timeline)) result.timeline = result.timeline.map(inputItem => {
    if (!inputItem || typeof inputItem !== "object" || Array.isArray(inputItem)) return inputItem;
    const item = inputItem as Record<string, unknown>;
    if (item.episodeNumber !== undefined) item.episodeNumber = integerValue(item.episodeNumber);
    if (item.sceneNumber !== undefined) item.sceneNumber = integerValue(item.sceneNumber);
    return item;
  });
  return result;
}

function promptFor(input: { title: string; sourceText: string; sourceKind: string; sections?: string[]; context?: unknown }) {
  return `你是 AI 短剧制片系统的剧本理解引擎。请把输入内容转换为严格 JSON，不要输出 Markdown、解释或 JSON 之外的文字。

输入类型：${input.sourceKind}
项目名称：${input.title}
目标部分：${input.sections?.length ? input.sections.join("、") : "synopsis, world, characters, locations, props, episodes, timeline"}
${input.context ? `已确认上下文（不得改写）：${JSON.stringify(input.context).slice(0, 120000)}` : ""}

JSON 顶层必须包含：
- synopsis: string
- world: string
- characters: { name, description, appearance, personality, age, voice, relationships: { name, label, description }[] }[]
- locations: { name, description, spatialStructure, lighting, colorPalette, timeOfDay, atmosphere }[]
- props: { name, description }[]
- episodes: { number, title, synopsis, script, scenes: { number, title, description, locationName, characterNames: string[], shots: { number, duration, shotSize, cameraAngle, cameraMovement, description, action, positions, expressions, dialogue, ambientSound, characterNames, propNames, firstFramePrompt, lastFramePrompt, videoPrompt }[] }[] }[]
- timeline: { title, description, episodeNumber?, sceneNumber? }[]
- continuityWarnings: string[]

要求：
1. 人物、地点、道具名称在全集保持一致。
2. 镜头数量必须足以覆盖场景，每个镜头具备可执行的画面、动作、对白和视频提示词。
3. shot.duration 必须是数字（单位为秒），不能输出带“秒”的字符串；集、场、镜编号也必须是整数。
4. 不编造输入中不存在的重要事实；不确定内容写入 continuityWarnings。
5. 保持原文语言。
6. 输出只包含 JSON。

输入内容：
${input.sourceText}`;
}

async function generateText(providerId: string, modelId: string, systemPrompt: string, prompt: string, signal: AbortSignal, timeoutMessage: string) {
  const configured = await getConfiguredModel(providerId, modelId);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(new Error(timeoutMessage)), 5 * 60 * 1000);
  const combined = AbortSignal.any([signal, controller.signal]);
  const context: Context = {
    systemPrompt,
    messages: [{ role: "user", content: prompt, timestamp: Date.now() }],
  };
  const stream = streamAi(configured, context, combined);
  let text = "";
  try {
    for await (const event of stream) if (event.type === "text_delta" && event.delta) text += event.delta;
    const message = await stream.result();
    if (message.stopReason === "error" || message.stopReason === "aborted") throw new Error(message.errorMessage || timeoutMessage);
    if (!text.trim()) text = message.content.filter(part => part.type === "text").map(part => part.text).join("");
    return text;
  } catch (error) {
    if (signal.aborted) throw signal.reason;
    throw Object.assign(new Error(translateError(error)), { cause: error });
  } finally {
    clearTimeout(timer);
  }
}

async function generateJson(providerId: string, modelId: string, prompt: string, signal: AbortSignal) {
  const text = await generateText(providerId, modelId, "你是严谨的短剧剧本结构与分镜设计引擎。只输出符合要求的 JSON。", prompt, signal, "剧本理解模型执行失败");
  return { value: extractJson(text), raw: text };
}

export async function understandScript(inputValue: unknown, providerId: string, modelId: string, signal: AbortSignal) {
  const input = z.strictObject({
    title: z.string().trim().min(1).max(200),
    sourceText: z.string().trim().min(1).max(2 * 1024 * 1024),
    sourceKind: z.enum(["idea", "outline", "novel", "script", "episodeScript"]),
    sections: z.array(z.enum(["synopsis", "world", "characters", "locations", "props", "episodes", "timeline"])).max(7).optional(),
    context: z.record(z.string(), z.json()).optional(),
  }).parse(inputValue);
  const chunks = chunksOf(input.sourceText);
  let context: unknown;
  if (chunks.length > 1) {
    const summaries: unknown[] = [];
    for (const [index, chunk] of chunks.entries()) {
      signal.throwIfAborted();
      const generated = await generateJson(providerId, modelId, promptFor({ ...input, sourceText: chunk, sections: ["characters", "locations", "props", "episodes", "timeline"], context: { chunk: index + 1, total: chunks.length } }), signal);
      summaries.push(generated.value);
    }
    context = summaries;
  }
  const finalPrompt = chunks.length > 1
    ? promptFor({ ...input, sourceText: "以下内容由长文本分段解析得到。请合并去重，修复人物名称和时间线连续性，并输出最终结构。", context })
    : promptFor(input);
  const generated = await generateJson(providerId, modelId, finalPrompt, signal);
  const result = scriptUnderstandingSchema.parse(normalizeUnderstanding(generated.value)) as ScriptUnderstanding;
  const names = new Set(result.characters.map(item => item.name.normalize("NFKC").toLowerCase()));
  const warnings = new Set(result.continuityWarnings);
  for (const episode of result.episodes) for (const scene of episode.scenes) {
    for (const name of scene.characterNames) if (!names.has(name.normalize("NFKC").toLowerCase())) warnings.add(`场景 ${episode.number}-${scene.number} 引用了未建档角色：${name}`);
    for (const shot of scene.shots) for (const name of shot.characterNames) if (!names.has(name.normalize("NFKC").toLowerCase())) warnings.add(`镜头 ${episode.number}-${scene.number}-${shot.number} 引用了未建档角色：${name}`);
  }
  return { result: { ...result, continuityWarnings: [...warnings] }, raw: generated.raw };
}
export async function optimizeShotPrompt(cwd: string, providerId: string, modelId: string, inputValue: unknown, signal: AbortSignal) {
  const input = z.object({
    shotId: z.uuid(),
    mode: z.enum(["general", "h3"]),
    instructions: z.string().max(10000).optional(),
  }).parse(inputValue);
  const root = await realpath(cwd);
  const document = await loadProduction(root);
  let shot;
  let scene;
  let episode;
  for (const currentEpisode of document.episodes) for (const currentScene of currentEpisode.scenes) {
    const currentShot = currentScene.shots.find(item => item.id === input.shotId);
    if (currentShot) {
      shot = currentShot;
      scene = currentScene;
      episode = currentEpisode;
      break;
    }
  }
  if (!shot || !scene || !episode) throw Object.assign(new Error("镜头不存在"), { status: 404 });
  let stylePrompt = "";
  try {
    const project = JSON.parse(await readFile(join(root, ".solodrama/project.json"), "utf8")) as Record<string, unknown>;
    stylePrompt = typeof project.stylePrompt === "string" ? project.stylePrompt : "";
  } catch { /* ACT: 项目没有画风配置时由镜头字段和模型自行组织。 */ }
  const characters = shot.characterIds.flatMap(id => document.characters.filter(item => item.id === id)).map(item => ({
    name: item.name,
    visual: item.visualDescription || [item.appearance, item.visualProfile.face, item.visualProfile.hair, item.visualProfile.body, item.visualProfile.style].filter(Boolean).join("，"),
    voice: item.voice.voiceId || "",
  }));
  const location = scene.locationId ? document.locations.find(item => item.id === scene.locationId) : undefined;
  const props = shot.propIds.flatMap(id => document.props.filter(item => item.id === id)).map(item => ({ name: item.name, description: item.description }));
  const source = {
    project: document.name,
    globalStyle: stylePrompt,
    episode: { number: episode.number, title: episode.title },
    scene: { number: scene.number, title: scene.title, description: scene.description },
    location: location ? { name: location.name, description: location.description, lighting: location.lighting, colorPalette: location.colorPalette, timeOfDay: location.timeOfDay, atmosphere: location.atmosphere } : undefined,
    shot: {
      number: shot.number, duration: shot.duration, shotSize: shot.shotSize, cameraAngle: shot.cameraAngle, cameraMovement: shot.cameraMovement,
      description: shot.description, action: shot.action, positions: shot.positions, expressions: shot.expressions,
      dialogue: shot.dialogue, ambientSound: shot.ambientSound, generalPrompt: shot.videoPrompt, h3Prompt: shot.h3VideoPrompt,
    },
    characters, props, userInstructions: input.instructions ?? "",
  };
  const prompt = input.mode === "h3"
    ? `你是 H3 全参考视频提示词引擎。根据以下镜头资料，输出可直接交给 H3 视频模型的完整中文提示词。必须保留参考角色、场景和道具的一致性；必须使用明确的主体定义和参考关系；对白原文不能改写。输出结构必须包含：subject_definitions、summary、retention_analysis、detailed_description、overall_soundscape、non_diegetic_music。不要输出 Markdown 代码围栏或解释。\n\n镜头资料：\n${JSON.stringify(source, null, 2)}`
    : `你是短剧视频提示词优化引擎。根据以下镜头资料，输出一段可直接用于视频生成的最终中文提示词。必须整合全局画风、角色形象、音色动作、场景、道具、景别、机位、运镜、动作、表情、对白、环境音和连续性；不要输出解释、标题或 Markdown。\n\n镜头资料：\n${JSON.stringify(source, null, 2)}`;
  const raw = await generateText(providerId, modelId, input.mode === "h3" ? "你是严谨的 H3 视频提示词设计师，只输出最终提示词。" : "你是短剧导演和视频提示词设计师，只输出最终提示词。", prompt, signal, "提示词优化失败");
  return { prompt: raw.trim(), mode: input.mode, raw };
}