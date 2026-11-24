import { dirname } from "node:path";
import { z } from "zod";
import type { ToolPlugin } from "@solodrama/tools-scaffold/runtime";
import { projectDimension, readSoloDramaProject } from "@solodrama/tools-scaffold/project";

const configSchema = z.object({
  fontPath: z.string().default("C:/Windows/Fonts/msyhbd.ttc"),
  width: z.number().int().min(240).max(7680).default(1080),
  height: z.number().int().min(240).max(7680).default(1920),
  style: z.enum(["suspense", "emotion", "urban", "costume"]).default("suspense"),
  textPosition: z.enum(["top", "center", "bottom"]).default("bottom"),
  safeArea: z.number().finite().min(0).max(0.35).default(0.12),
  outline: z.number().int().min(0).max(20).default(3),
  shadow: z.number().int().min(0).max(20).default(2),
  titleColor: z.string().default("#FFFFFF"),
  subtitleColor: z.string().default("#F0E8D8"),
}).strict();
const requestSchema = z.strictObject({
  title: z.string().trim().min(1).max(120),
  subtitle: z.string().trim().max(200).optional(),
  backgroundPath: z.string().trim().min(1).optional().describe("已有底图路径；与 providerId/modelId 二选一"),
  providerId: z.string().trim().min(1).optional(),
  modelId: z.string().trim().min(1).optional(),
  prompt: z.string().trim().max(4000).optional(),
  style: z.enum(["suspense", "emotion", "urban", "costume"]).optional(),
  styleKey: z.string().trim().max(200).optional(),
  stylePrompt: z.string().trim().max(4000).optional(),
  platform: z.string().trim().max(100).optional(),
  width: z.number().int().min(240).max(7680).optional(),
  height: z.number().int().min(240).max(7680).optional(),
  fontPath: z.string().trim().max(4096).optional(),
  textPosition: z.enum(["top", "center", "bottom"]).optional(),
  safeArea: z.number().finite().min(0).max(0.35).optional(),
  outline: z.number().int().min(0).max(20).optional(),
  shadow: z.number().int().min(0).max(20).optional(),
  titleColor: z.string().regex(/^#[\da-f]{6}$/i).optional(),
  subtitleColor: z.string().regex(/^#[\da-f]{6}$/i).optional(),
  outputPath: z.string().trim().min(1).max(4096),
  overwrite: z.boolean().default(false),
});
const stylePrompt = {
  suspense: "强冲突悬疑短剧封面，人物情绪张力强，高对比电影光，留出下方标题安全区，不生成文字",
  emotion: "情绪特写短剧封面，面部近景，泪光与冷暖对比光，留出下方标题安全区，不生成文字",
  urban: "都市逆袭短剧封面，城市霓虹与权力对峙，高对比商业海报构图，留出下方标题安全区，不生成文字",
  costume: "古风权谋短剧封面，电影级服化道，强烈人物关系与压迫感，留出下方标题安全区，不生成文字",
} as const;

function escapeDrawText(value: string) {
  return value.replaceAll("\\", "\\\\").replaceAll("'", "\\'").replaceAll(":", "\\:").replaceAll("%", "\\%").replace(/\r?\n/g, "\\n");
}

const plugin: ToolPlugin = {
  validateConfig: config => configSchema.parse(config),
  createTools(context) {
    const config = configSchema.parse(context.config);
    return [{
      name: "designCover",
      label: "设计短剧封面",
      description: "用已有底图或图片模型生成竖屏封面，并叠加标题、副标题和暗色压字层，输出 PNG。",
      promptSnippet: "设计爆款封面时先确认标题、风格和底图；若调用图片模型，先核对报价与预算。",
      promptGuidelines: [
        "backgroundPath 与 providerId/modelId 至少提供一种。",
        "调用图片模型前必须获得用户对费用或未知费用的明确确认。",
        "生成后检查输出 PNG 真实存在；不把生成提示词当成已生成封面。",
      ],
      parameters: z.toJSONSchema(requestSchema, { io: "input", target: "draft-07" }),
      executionMode: "sequential",
      async execute(_id, params, signal) {
        const request = requestSchema.parse(params);
        signal?.throwIfAborted();
        const project = await readSoloDramaProject(context);
        const dimensions = projectDimension(project, config.width, config.height);
        const width = request.width ?? dimensions.width;
        const height = request.height ?? dimensions.height;
        if (width % 2 || height % 2) throw new Error("封面宽高必须为偶数");
        const output = await context.resolvePath(request.outputPath);
        if (!request.overwrite && await context.files.access(output).then(() => true).catch(() => false)) throw new Error("封面文件已存在；如需覆盖请显式设置 overwrite=true");
        await context.files.mkdir(dirname(output), true);
        let background: string;
        if (request.backgroundPath) {
          background = await context.resolvePath(request.backgroundPath, true);
        } else {
          if (!request.providerId || !request.modelId) throw new Error("生成底图需要同时提供 providerId 和 modelId");
          if (!context.media) throw new Error("当前宿主不支持图片模型调用");
          const style = request.style ?? config.style;
          const prompt = [
            request.stylePrompt || (request.styleKey && request.styleKey === project?.styleKey ? project.stylePrompt : "") || stylePrompt[style],
            request.prompt,
          ].filter(Boolean).join("。");
          const generated = await context.media.generateImage({
            providerId: request.providerId,
            modelId: request.modelId,
            prompt,
            size: `${width}x${height}`,
            ratio: project?.aspectRatio || (width >= height ? "16:9" : "9:16"),
          }, signal);
          const image = generated.find(item => item.mediaType === "image");
          if (!image) throw new Error("图片模型没有返回封面底图");
          background = await context.resolvePath(image.path, true);
        }
        const titleSize = request.width ? Math.max(48, Math.round(width * 0.095)) : Math.max(48, project?.cover?.titleSize ?? Math.round(width * 0.095));
        const subtitleSize = request.width ? Math.max(28, Math.round(width * 0.042)) : Math.max(28, project?.cover?.subtitleSize ?? Math.round(width * 0.042));
        const fontPath = request.fontPath ?? project?.cover?.fontPath ?? config.fontPath;
        const font = fontPath.trim() ? `fontfile='${escapeDrawText(await context.resolvePath(fontPath, true).catch(() => fontPath))}'` : "font='Microsoft YaHei'";
        const title = escapeDrawText(request.title);
        const subtitle = request.subtitle ? escapeDrawText(request.subtitle) : "";
        const position = request.textPosition ?? project?.cover?.textPosition ?? config.textPosition;
        const safeArea = Math.max(12, Math.round(height * (request.safeArea ?? project?.cover?.safeArea ?? config.safeArea)));
        const textTop = position === "top" ? safeArea : position === "center" ? Math.round(height * 0.43) : Math.round(height - safeArea - titleSize * 2.1);
        const outline = request.outline ?? project?.cover?.outline ?? config.outline;
        const shadow = request.shadow ?? project?.cover?.shadow ?? config.shadow;
        const textStyle = `borderw=${outline}:bordercolor=black@0.72${shadow ? `:shadowcolor=black@0.8:shadowx=${shadow}:shadowy=${shadow}` : ""}`;
        const filters = [
          `scale=${width}:${height}:force_original_aspect_ratio=increase`,
          `crop=${width}:${height}`,
          `drawbox=x=0:y=${Math.max(0, textTop - Math.round(height * 0.05))}:w=iw:h=${Math.min(height, Math.round(height * 0.42))}:color=black@0.52:t=fill`,
          `drawtext=${font}:text='${title}':fontcolor=${request.titleColor ?? config.titleColor}:fontsize=${titleSize}:line_spacing=12:x=(w-text_w)/2:y=${textTop}:${textStyle}`,
          ...(subtitle ? [`drawtext=${font}:text='${subtitle}':fontcolor=${request.subtitleColor ?? config.subtitleColor}:fontsize=${subtitleSize}:x=(w-text_w)/2:y=${textTop + Math.round(titleSize * 1.35)}:${textStyle}`] : []),
        ];
        let failure: Error | undefined;
        await context.executeFfmpeg({
          directory: context.cwd,
          requestId: crypto.randomUUID(),
          options: { cwd: context.cwd },
          calls: [
            { method: "input", args: [background] },
            { method: "videoFilters", args: [filters.join(",")] },
            { method: "outputOptions", args: ["-frames:v", "1"] },
            { method: "output", args: [output] },
          ],
          operation: { method: "run", args: [] },
        }, event => { if (event.event === "error") failure = event.args[0] as Error; });
        if (failure) throw failure;
        await context.files.access(output).catch(() => { throw new Error("封面合成结束但没有找到输出文件"); });
        return { content: [{ type: "text", text: `封面已生成：${request.outputPath.replaceAll("\\", "/")}` }], details: { outputPath: request.outputPath.replaceAll("\\", "/"), width, height, platform: request.platform ?? project?.cover?.platform ?? project?.aspectRatio ?? "", styleKey: request.styleKey ?? project?.styleKey ?? "" } };
      },
    }];
  },
};

export default plugin;
