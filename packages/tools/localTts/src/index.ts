import { dirname, extname } from "node:path";
import { z } from "zod";
import type { ToolPlugin } from "@solodrama/tools-scaffold/runtime";
import { readSoloDramaProject } from "@solodrama/tools-scaffold/project";

const configSchema = z.object({
  mode: z.enum(["http", "command"]).default("http"),
  endpoint: z.string().default("http://127.0.0.1:8880/v1/audio/speech"),
  apiKey: z.string().default(""),
  model: z.string().trim().min(1).max(200).default("local-tts"),
  command: z.string().default(""),
  argsJson: z.string().default('["--text", "{text}", "--output", "{output}"]'),
  defaultVoice: z.string().default(""),
  format: z.enum(["mp3", "wav"]).default("mp3"),
  language: z.string().default(""),
  sampleRate: z.number().int().min(8000).max(192000).default(44100),
  volume: z.number().finite().min(-30).max(30).default(0),
  normalize: z.boolean().default(false),
  characterVoicesJson: z.string().default("{}"),
}).strict();
const speechSchema = z.strictObject({
  text: z.string().trim().min(1).max(100000),
  outputPath: z.string().trim().min(1).max(4096),
  voice: z.string().trim().max(200).optional(),
  speed: z.number().finite().min(0.25).max(4).optional(),
  language: z.string().trim().max(40).optional(),
  format: z.enum(["mp3", "wav"]).optional(),
  sampleRate: z.number().int().min(8000).max(192000).optional(),
  volume: z.number().finite().min(-30).max(30).optional(),
  normalize: z.boolean().optional(),
  instructions: z.string().trim().max(2000).optional(),
});
const dialogueSchema = z.strictObject({
  name: z.string().trim().min(1).max(100),
  segments: z.array(z.strictObject({
    character: z.string().trim().min(1).max(100),
    text: z.string().trim().min(1).max(10000),
    voice: z.string().trim().max(200).optional(),
    speed: z.number().finite().min(0.25).max(4).optional(),
    language: z.string().trim().max(40).optional(),
    instructions: z.string().trim().max(2000).optional(),
  })).min(1).max(1000),
  outputDirectory: z.string().trim().min(1).max(4096).optional(),
  format: z.enum(["mp3", "wav"]).optional(),
  sampleRate: z.number().int().min(8000).max(192000).optional(),
  volume: z.number().finite().min(-30).max(30).optional(),
  normalize: z.boolean().optional(),
});
const roughCutSchema = z.strictObject({
  name: z.string().trim().min(1).max(100),
  clips: z.array(z.strictObject({
    videoPath: z.string().trim().min(1),
    audioPath: z.string().trim().optional(),
    subtitle: z.string().trim().max(5000).optional(),
    note: z.string().trim().max(2000).optional(),
  })).min(1).max(500),
  narrationPath: z.string().trim().optional(),
  outputDirectory: z.string().trim().optional(),
});

function placeholders(value: string, values: Record<string, string>) {
  return value.replace(/\{(text|output|voice|speed|language|format|sampleRate|volume|instructions)\}/g, (_match, key: string) => values[key] ?? "");
}

async function synthesize(context: Parameters<ToolPlugin["createTools"]>[0], config: z.infer<typeof configSchema>, request: z.infer<typeof speechSchema>, signal?: AbortSignal) {
  const project = await readSoloDramaProject(context);
  const output = await context.resolvePath(request.outputPath);
  await context.files.mkdir(dirname(output), true);
  const voice = request.voice || config.defaultVoice || project?.tts?.voice || "default";
  const speed = request.speed ?? project?.tts?.speed ?? 1;
  const language = request.language || config.language || project?.tts?.language || "";
  const format = request.format ?? config.format ?? project?.tts?.format ?? "mp3";
  const sampleRate = request.sampleRate ?? config.sampleRate ?? project?.tts?.sampleRate ?? 44100;
  const volume = request.volume ?? config.volume ?? project?.tts?.volume ?? 0;
  const normalize = request.normalize ?? config.normalize;
  if (config.mode === "http") {
    const headers: Record<string, string> = { "Content-Type": "application/json", Accept: "audio/*,application/octet-stream" };
    if (config.apiKey.trim()) headers.Authorization = `Bearer ${config.apiKey.trim().replace(/^Bearer\s+/i, "")}`;
    const response = await fetch(config.endpoint, {
      method: "POST", headers,
      body: JSON.stringify({
        model: config.model, input: request.text, voice, response_format: format, speed,
        ...(language ? { language } : {}),
        ...(request.instructions ? { instructions: request.instructions } : {}),
      }), signal,
    });
    if (!response.ok) {
      const message = await response.text().catch(() => "");
      throw new Error(`本地 TTS HTTP ${response.status}：${message.slice(0, 2000) || "请求失败"}`);
    }
    const bytes = new Uint8Array(await response.arrayBuffer());
    if (!bytes.length) throw new Error("本地 TTS 返回了空音频");
    await context.files.writeFile(output, bytes);
  } else {
    if (!config.command.trim()) throw new Error("本地命令模式尚未配置 TTS 命令");
    let args: unknown;
    try { args = JSON.parse(config.argsJson); }
    catch (error) { throw new Error("命令参数 JSON 无效：" + (error instanceof Error ? error.message : String(error))); }
    if (!Array.isArray(args) || args.some(item => typeof item !== "string")) throw new Error("命令参数 JSON 必须为字符串数组");
    const values = {
      text: request.text, output, voice, speed: String(speed), language, format,
      sampleRate: String(sampleRate), volume: String(volume), instructions: request.instructions ?? "",
    };
    const command = placeholders(config.command, values);
    const processResult = Bun.spawn({
      cmd: [command, ...args.map(item => placeholders(item, values))],
      cwd: context.cwd,
      stdout: "pipe",
      stderr: "pipe",
      windowsHide: true,
    });
    const [stdout, stderr, exitCode] = await Promise.all([new Response(processResult.stdout).text(), new Response(processResult.stderr).text(), processResult.exited]);
    if (exitCode !== 0) throw new Error(`本地 TTS 命令失败（${exitCode}）：${(stderr || stdout).slice(-3000)}`);
    await context.files.access(output).catch(() => { throw new Error("本地 TTS 命令结束但没有生成目标音频"); });
  }
  if (sampleRate || volume || normalize) await postProcessAudio(context, output, { sampleRate, volume, normalize }, signal);
  return {
    path: request.outputPath.replaceAll("\\", "/"),
    mimeType: format === "wav" ? "audio/wav" : "audio/mpeg",
    voice, speed, language, format, sampleRate, volume, normalized: normalize,
  };
}

async function postProcessAudio(
  context: Parameters<ToolPlugin["createTools"]>[0],
  output: string,
  options: { sampleRate: number; volume: number; normalize: boolean },
  signal?: AbortSignal,
) {
  signal?.throwIfAborted();
  const extension = extname(output).toLowerCase();
  const temporary = `${output.slice(0, -extension.length)}.processed${extension}`;
  await context.files.remove(temporary).catch(() => {});
  const filters = [
    ...(options.volume ? [`volume=${options.volume}dB`] : []),
    ...(options.normalize ? ["loudnorm=I=-16:TP=-1.5:LRA=11"] : []),
  ];
  let failure: Error | undefined;
  await context.executeFfmpeg({
    directory: context.cwd,
    requestId: crypto.randomUUID(),
    options: { cwd: context.cwd },
    calls: [
      { method: "input", args: [output] },
      ...(filters.length ? [{ method: "audioFilters", args: [filters.join(",")] }] : []),
      { method: "audioCodec", args: [extension === ".wav" ? "pcm_s16le" : "libmp3lame"] },
      { method: "outputOptions", args: ["-ar", String(options.sampleRate || 44100)] },
      { method: "output", args: [temporary] },
    ],
    operation: { method: "run", args: [] },
  }, event => { if (event.event === "error") failure = event.args[0] as Error; }, signal);
  if (failure) throw failure;
  await context.files.access(temporary).catch(() => { throw new Error("音频转码结束但没有生成输出文件"); });
  await context.files.remove(output);
  await context.files.rename(temporary, output);
}

async function probeAudioDuration(context: Parameters<ToolPlugin["createTools"]>[0], path: string, signal?: AbortSignal) {
  let result: Record<string, unknown> | undefined;
  let failure: Error | undefined;
  await context.executeFfmpeg({
    directory: context.cwd,
    requestId: crypto.randomUUID(),
    options: { cwd: context.cwd },
    calls: [{ method: "input", args: [path] }],
    operation: { method: "ffprobe", args: [{ options: [], json: true }] },
  }, event => {
    if (event.event === "result") result = event.args[0] as Record<string, unknown>;
    if (event.event === "error") failure = event.args[0] as Error;
  }, signal);
  if (failure) throw failure;
  const format = result?.format && typeof result.format === "object" ? result.format as Record<string, unknown> : {};
  const duration = Number(format.duration ?? result?.duration);
  if (!Number.isFinite(duration) || duration <= 0) throw new Error(`无法读取音频时长：${path}`);
  return duration;
}

function safeName(value: string) {
  return value.replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_").replace(/[. ]+$/g, "").slice(0, 80) || "audio";
}

function parseCharacterVoices(value: string) {
  let parsed: unknown;
  try { parsed = JSON.parse(value || "{}"); }
  catch (error) { throw new Error("角色音色 JSON 无效：" + (error instanceof Error ? error.message : String(error))); }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("角色音色 JSON 必须是对象，如 {\"角色名\":\"音色\"}");
  return Object.fromEntries(Object.entries(parsed).flatMap(([key, voice]) => typeof voice === "string" && voice.trim() ? [[key, voice.trim()]] : []));
}

const plugin: ToolPlugin = {
  validateConfig: config => configSchema.parse(config),
  createTools(context) {
    const config = configSchema.parse(context.config);
    const characterVoices = parseCharacterVoices(config.characterVoicesJson);
    return [{
      name: "synthesizeSpeech",
      label: "生成配音",
      description: "调用本地 OpenAI 兼容 TTS HTTP 接口或本地 TTS 命令，将文本合成为工作区音频文件。",
      promptSnippet: "为台词生成音频时使用本地 TTS，优先复用用户已有音色，不猜测未验证的模型或输出路径。",
      parameters: z.toJSONSchema(speechSchema, { io: "input", target: "draft-07" }),
      async execute(_id, params, signal) {
        const request = speechSchema.parse(params);
        const result = await synthesize(context, config, request, signal);
        return { content: [{ type: "text", text: JSON.stringify(result) }], details: result };
      },
    }, {
      name: "createVoiceRoughCut",
      label: "生成配音粗剪清单",
      description: "把分镜视频、逐镜配音或整段旁白整理成粗剪清单，供剪映草稿和流水线出片插件继续处理。",
      promptSnippet: "视频画面与配音已确定时生成粗剪清单；清单不等于成片，必须由后续剪辑插件实际渲染或导入剪映。",
      parameters: z.toJSONSchema(roughCutSchema, { io: "input", target: "draft-07" }),
      async execute(_id, params) {
        const request = roughCutSchema.parse(params);
        const root = request.outputDirectory?.trim() || `.solodrama/roughCut/${request.name.replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_").slice(0, 80) || "episode"}`;
        const manifestPath = `${root.replace(/\/+$/, "")}/manifest.json`;
        const absolute = await context.resolvePath(manifestPath);
        await context.files.mkdir(dirname(absolute), true);
        const manifest = {
          version: 1,
          kind: "solodrama-voice-rough-cut",
          name: request.name,
          createdAt: new Date().toISOString(),
          narrationPath: request.narrationPath ?? null,
          clips: request.clips.map((clip, index) => ({ index: index + 1, ...clip })),
        };
        await context.files.writeFile(absolute, JSON.stringify(manifest, null, 2) + "\n");
        return { content: [{ type: "text", text: `粗剪清单已生成：${manifestPath}` }], details: { manifestPath, manifest } };
      },
    }, {
      name: "synthesizeDialogue",
      label: "按角色批量生成配音",
      description: "按角色音色批量生成逐段台词音频，并写入带累计起止时间的时间轴清单，供粗剪、剪映草稿或流水线出片使用。",
      promptSnippet: "角色台词需要不同音色时使用；优先使用项目默认音色和角色音色映射，生成后以清单中的真实音频时长为准。",
      parameters: z.toJSONSchema(dialogueSchema, { io: "input", target: "draft-07" }),
      executionMode: "sequential",
      async execute(_id, params, signal) {
        const request = dialogueSchema.parse(params);
        const root = (request.outputDirectory?.trim() || `.solodrama/voice/${safeName(request.name)}`).replace(/\/+$/, "");
        const format = request.format ?? config.format;
        const generated = [];
        let cursor = 0;
        for (const [index, segment] of request.segments.entries()) {
          signal?.throwIfAborted();
          const outputPath = `${root}/segments/${String(index + 1).padStart(4, "0")}-${safeName(segment.character)}.${format}`;
          const result = await synthesize(context, config, {
            text: segment.text,
            outputPath,
            voice: segment.voice || characterVoices[segment.character],
            speed: segment.speed,
            language: segment.language,
            instructions: segment.instructions,
            format,
            sampleRate: request.sampleRate,
            volume: request.volume,
            normalize: request.normalize,
          }, signal);
          const absolute = await context.resolvePath(outputPath, true);
          const duration = await probeAudioDuration(context, absolute, signal);
          generated.push({
            index: index + 1, character: segment.character, text: segment.text,
            audioPath: result.path, voice: result.voice, durationSeconds: duration,
            startSeconds: cursor, endSeconds: cursor + duration,
          });
          cursor += duration;
        }
        const manifestPath = `${root}/dialogue.json`;
        const manifest = {
          version: 1,
          kind: "solodrama-dialogue-timeline",
          name: request.name,
          createdAt: new Date().toISOString(),
          totalSeconds: cursor,
          segments: generated,
        };
        const absoluteManifest = await context.resolvePath(manifestPath);
        await context.files.mkdir(dirname(absoluteManifest), true);
        await context.files.writeFile(absoluteManifest, JSON.stringify(manifest, null, 2) + "\n");
        return { content: [{ type: "text", text: `逐角色配音与时间轴已生成：${manifestPath}` }], details: { manifestPath, manifest } };
      },
    }];
  },
};

export default plugin;
