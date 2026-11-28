<template>
  <div class="canvasSourcesStage">
    <section class="sourcesHeader">
      <div>
        <p class="eyebrow">CANVAS SOURCES</p>
        <h2>画布来源</h2>
        <p>旧画布节点只作为来源。导入时创建 Production 实体并记录映射，不修改原画布，也不自动覆盖已确认内容。</p>
      </div>
      <div class="headerActions">
        <el-button :loading="loading" @click="emit('refresh')">刷新来源</el-button>
        <el-button @click="emit('openCanvas')">进入画布</el-button>
      </div>
    </section>

    <section class="quickCreate">
      <button v-for="action in quickActions" :key="action.type" type="button" @click="emit('create', action.type, action.label)">
        <strong>{{ action.label }}</strong><span>{{ action.hint }}</span>
      </button>
    </section>

    <section class="sourceSummary">
      <div><strong>{{ sources.length }}</strong><span>节点来源</span></div>
      <div><strong>{{ sources.filter(source => source.binding).length }}</strong><span>已关联</span></div>
      <div><strong>{{ sources.filter(source => !source.binding).length }}</strong><span>待归档</span></div>
      <div><strong>{{ sources.filter(source => source.kind === 'video').length }}</strong><span>视频节点</span></div>
    </section>

    <div v-loading="loading" class="sourceList">
      <article v-for="source in sources" :key="source.id" class="sourceCard">
        <div class="sourceIdentity">
          <div class="sourceIcon" :class="source.kind">{{ kindLabel(source.kind) }}</div>
          <div>
            <h3>{{ source.label }}</h3>
            <p>{{ source.canvasPath }} · {{ source.typeLabel }}</p>
          </div>
          <el-tag v-if="source.binding" type="success" effect="plain">已关联 {{ boundName(source) }}</el-tag>
          <el-tag v-else type="info" effect="plain">待归档</el-tag>
        </div>

        <p v-if="source.preview" class="sourcePreview">{{ source.preview }}</p>
        <div class="sourceMeta">
          <span v-if="source.mediaPath">输出 · {{ source.mediaPath }}</span>
          <span v-if="source.textPath">正文 · {{ source.textPath }}</span>
          <span v-if="source.model">模型 · {{ source.model }}</span>
          <span>节点 · {{ source.nodeId.slice(0, 12) }}</span>
        </div>

        <div v-if="source.binding" class="sourceActions">
          <el-button size="small" :disabled="!focusNode" @click="emit('focus', source.canvasPath, source.nodeId)">在画布定位</el-button>
          <span class="bindingHint">Production 已拥有该内容，后续修改请在工作台对应阶段完成。</span>
        </div>
        <div v-else class="sourceActions">
          <template v-if="source.kind === 'image'">
            <el-select v-model="imageTargets[source.id]" size="small" style="width: 130px">
              <el-option label="角色" value="character" /><el-option label="场景" value="location" />
              <el-option label="道具" value="prop" /><el-option label="仅素材" value="asset" />
            </el-select>
          </template>
          <template v-else-if="source.kind === 'video'">
            <el-select v-model="videoScenes[source.id]" clearable placeholder="未归档镜头场次" size="small" style="width: 220px">
              <el-option v-for="scene in sceneOptions" :key="scene.id" :label="scene.label" :value="scene.id" />
            </el-select>
          </template>
          <template v-else-if="source.kind === 'script'">
            <el-select v-model="scriptEpisodes[source.id]" clearable placeholder="新建分集" size="small" style="width: 220px">
              <el-option v-for="episode in document.episodes" :key="episode.id" :label="`第 ${episode.number} 集 · ${episode.title}`" :value="episode.id" />
            </el-select>
          </template>
          <el-button type="primary" size="small" :loading="importingId === source.id" @click="importSource(source)">
            {{ importLabel(source) }}
          </el-button>
          <el-button size="small" :disabled="!focusNode" @click="emit('focus', source.canvasPath, source.nodeId)">查看节点</el-button>
        </div>
      </article>

      <el-empty v-if="!loading && !sources.length" description="当前项目没有可识别的剧本、图片、视频或音频节点" :imageSize="76" />
    </div>
  </div>
</template><script setup lang="ts">
import { computed, reactive, watch } from "vue";
import type { ProductionDocument } from "@solodrama/production";
import type { CanvasImportRequest, CanvasSource, CanvasSourceKind, CanvasSuggestedTarget } from "./canvasSourceTypes";

const props = defineProps<{
  document: ProductionDocument;
  sources: CanvasSource[];
  loading: boolean;
  importingId?: string;
  focusNode?: (canvasPath: string, nodeId: string) => Promise<void>;
}>();
const emit = defineEmits<{
  refresh: [];
  import: [request: CanvasImportRequest];
  focus: [canvasPath: string, nodeId: string];
  create: [type: string, label: string];
  openCanvas: [];
}>();
const imageTargets = reactive<Record<string, "character" | "location" | "prop" | "asset">>({});
const videoScenes = reactive<Record<string, string>>({});
const scriptEpisodes = reactive<Record<string, string>>({});
const quickActions = [
  { type: "remote-textNode", label: "新建剧本", hint: "Markdown 文本节点" },
  { type: "remote-imageGenerationNode", label: "新建设定图", hint: "角色、场景或道具" },
  { type: "remote-videoGenerationNode", label: "新建分镜镜头", hint: "视频生成节点" },
  { type: "remote-audioGenerationNode", label: "新建音频", hint: "配音、音乐或音效" },
];
const sceneOptions = computed(() => props.document.episodes.flatMap(episode => episode.scenes.map(scene => ({
  id: scene.id, label: `第 ${episode.number} 集 · 场 ${scene.number} · ${scene.title || "未命名场次"}`,
}))));watch(() => props.sources, sources => {
  for (const source of sources) {
    if (!imageTargets[source.id]) imageTargets[source.id] = ["character", "location", "prop", "asset"].includes(source.suggestedTarget)
      ? source.suggestedTarget as "character" | "location" | "prop" | "asset" : "asset";
    if (!Object.hasOwn(videoScenes, source.id)) videoScenes[source.id] = "";
    if (!Object.hasOwn(scriptEpisodes, source.id)) scriptEpisodes[source.id] = "";
  }
}, { immediate: true });

function kindLabel(kind: CanvasSourceKind) {
  return { script: "剧本", image: "图片", video: "视频", audio: "音频" }[kind];
}
function importLabel(source: CanvasSource) {
  if (source.kind === "script") return "导入为分集剧本";
  if (source.kind === "video") return "导入为镜头";
  if (source.kind === "audio") return "导入为音频素材";
  return imageTargets[source.id] === "asset" ? "导入为素材" : "导入为新设定";
}
function boundName(source: CanvasSource) {
  const binding = source.binding;
  if (!binding) return "";
  if (binding.entityType === "episode") return props.document.episodes.find(item => item.id === binding.entityId)?.title ?? "分集";
  if (binding.entityType === "character") return props.document.characters.find(item => item.id === binding.entityId)?.name ?? "角色";
  if (binding.entityType === "location") return props.document.locations.find(item => item.id === binding.entityId)?.name ?? "场景";
  if (binding.entityType === "prop") return props.document.props.find(item => item.id === binding.entityId)?.name ?? "道具";
  if (binding.entityType === "shot") {
    const shot = props.document.episodes.flatMap(episode => episode.scenes).flatMap(scene => scene.shots).find(item => item.id === binding.entityId);
    return shot ? `镜头 ${shot.number}` : "镜头";
  }
  return props.document.assets.find(item => item.id === binding.entityId)?.name ?? "素材";
}
function importSource(source: CanvasSource) {
  const targetType: CanvasSuggestedTarget | undefined = source.kind === "image" ? imageTargets[source.id]
    : source.kind === "video" ? "shot" : source.kind === "script" ? "episode" : "asset";
  const targetId = source.kind === "video" ? videoScenes[source.id] || undefined
    : source.kind === "script" ? scriptEpisodes[source.id] || undefined : undefined;
  emit("import", { source, targetType, targetId });
}
</script><style scoped lang="scss">
.canvasSourcesStage { display: grid; gap: 16px; }
.sourcesHeader { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; padding: 24px; border: 1px solid var(--el-border-color-light); border-radius: 16px; background: var(--el-bg-color-overlay); }
.sourcesHeader h2 { margin: 7px 0 8px; font-size: 25px; }
.sourcesHeader p { max-width: 820px; margin: 0; color: var(--el-text-color-secondary); line-height: 1.7; }
.eyebrow { color: var(--el-color-primary); font-size: 10px; font-weight: 700; letter-spacing: .15em; }
.headerActions { display: flex; gap: 8px; flex-shrink: 0; }
.quickCreate { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 9px; }
.quickCreate button { display: grid; gap: 3px; padding: 13px; border: 1px solid var(--el-border-color-light); border-radius: 12px; color: inherit; background: var(--el-bg-color-overlay); text-align: left; cursor: pointer; }
.quickCreate button:hover { border-color: var(--el-color-primary-light-5); background: var(--el-color-primary-light-9); }
.quickCreate strong { font-size: 13px; }.quickCreate span { color: var(--el-text-color-secondary); font-size: 10px; }
.sourceSummary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 9px; }
.sourceSummary div { display: flex; align-items: baseline; justify-content: space-between; padding: 12px 14px; border-radius: 10px; background: var(--el-fill-color-lighter); }
.sourceSummary strong { font-size: 21px; }.sourceSummary span { color: var(--el-text-color-secondary); font-size: 11px; }
.sourceList { display: grid; gap: 10px; min-height: 240px; }
.sourceCard { padding: 16px; border: 1px solid var(--el-border-color-light); border-radius: 14px; background: var(--el-bg-color-overlay); }
.sourceIdentity { display: grid; grid-template-columns: 54px minmax(0, 1fr) auto; align-items: center; gap: 12px; }
.sourceIdentity h3, .sourceIdentity p { margin: 0; }.sourceIdentity h3 { font-size: 15px; }.sourceIdentity p { margin-top: 4px; overflow: hidden; color: var(--el-text-color-secondary); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.sourceIcon { display: grid; place-items: center; width: 52px; height: 36px; border-radius: 9px; color: var(--el-color-primary); background: var(--el-color-primary-light-9); font-size: 11px; }
.sourceIcon.image { color: var(--el-color-success); background: var(--el-color-success-light-9); }
.sourceIcon.video { color: var(--el-color-warning); background: var(--el-color-warning-light-9); }
.sourceIcon.audio { color: var(--el-color-info); background: var(--el-color-info-light-9); }
.sourcePreview { display: -webkit-box; overflow: hidden; margin: 12px 0 0; color: var(--el-text-color-regular); font-size: 12px; line-height: 1.65; -webkit-box-orient: vertical; -webkit-line-clamp: 3; }
.sourceMeta { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.sourceMeta span { max-width: 100%; overflow: hidden; padding: 3px 7px; border-radius: 5px; color: var(--el-text-color-secondary); background: var(--el-fill-color-lighter); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.sourceActions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--el-border-color-lighter); }
.bindingHint { color: var(--el-text-color-secondary); font-size: 10px; }
@media (max-width: 900px) { .quickCreate, .sourceSummary { grid-template-columns: repeat(2, minmax(0, 1fr)); } .sourcesHeader { flex-direction: column; } }
@media (max-width: 600px) { .quickCreate, .sourceSummary { grid-template-columns: 1fr; } .sourceIdentity { grid-template-columns: 52px minmax(0, 1fr); } .sourceIdentity > .el-tag { grid-column: 2; justify-self: start; } }
</style>