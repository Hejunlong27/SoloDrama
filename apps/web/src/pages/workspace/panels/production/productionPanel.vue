<template>
  <section class="productionPage">
    <header class="productionHeader">
      <div>
        <p class="eyebrow">SoloDrama 3.0</p>
        <h1>{{ document?.name || "AI 短剧制作引擎" }}</h1>
        <p class="summary">{{ document?.synopsis || "从故事创意、角色场景、分镜到配音和成片的可追踪生产线。" }}</p>
      </div>
      <div class="headerActions">
        <el-tag v-if="document" effect="plain">修订 {{ document.revision }}</el-tag>
        <el-button :icon="IconArrowLeft" @click="goHome">返回项目</el-button>
        <el-button v-if="activeTab !== 'overview'" @click="activeTab = 'overview'">返回总览</el-button>
        <el-button :icon="IconPalette" @click="globalStyleVisible = true">全局画风</el-button>
        <el-button :loading="loading" @click="load">重新加载</el-button>
        <el-button type="primary" :loading="saving" :disabled="!dirty || !document" @click="save()">保存修改</el-button>
      </div>
    </header>

    <div v-if="loading && !document" class="emptyState" v-loading="true">正在加载制作数据</div>
    <div v-else-if="error" class="emptyState">
      <p>{{ error }}</p>
      <el-button @click="load">重试</el-button>
    </div>
    <el-tabs v-else-if="document" v-model="activeTab" class="productionTabs">
      <el-tab-pane label="总览" name="overview">
        <productionOverview
          :document="document"
          :canvasTotal="canvasSourceCount"
          :canvasBound="canvasBoundCount"
          :canvasPending="canvasPendingCount"
          @navigate="activeTab = $event" />
      </el-tab-pane>
      <el-tab-pane label="剧本理解" name="script">
        <div class="scriptLayout">
          <section class="workspaceCard editorCard">
            <div class="cardHeader">
              <div>
                <h2>剧本编制</h2>
                <p>直接输入创意、大纲或上传整本剧本文档；长文先识别章节并切段，再交给 AI 解析。</p>
              </div>
              <div class="confirmGroup">
                <el-tag :type="document.confirmedSections.synopsis ? 'success' : 'info'">{{ document.confirmedSections.synopsis ? "简介已确认" : "简介未确认" }}</el-tag>
                <el-switch :modelValue="document.confirmedSections.synopsis === true" activeText="确认简介" @change="confirmSection('synopsis', Boolean($event))" />
              </div>
            </div>
            <scriptSegmenter v-model="scriptSourceText" />
            <el-form labelPosition="top" class="formGrid scriptOutputForm">
              <el-form-item label="项目名称"><el-input v-model="document.name" @input="markDirty" /></el-form-item>
              <el-form-item label="故事简介"><el-input v-model="document.synopsis" type="textarea" :rows="4" @input="markDirty" /></el-form-item>
              <el-form-item label="世界观"><el-input v-model="document.world" type="textarea" :rows="6" @input="markDirty" /></el-form-item>
            </el-form>
            <div class="sectionConfirms">
              <el-switch :modelValue="document.confirmedSections.world === true" activeText="确认世界观" @change="confirmSection('world', Boolean($event))" />
              <el-switch :modelValue="document.confirmedSections.timeline === true" activeText="确认时间线" @change="confirmSection('timeline', Boolean($event))" />
            </div>
            <div class="warningList" v-if="document.continuityWarnings.length">
              <h3>连续性提示</h3>
              <el-alert v-for="warning in document.continuityWarnings" :key="warning" :title="warning" type="warning" :closable="false" showIcon />
            </div>
          </section>

          <section class="workspaceCard aiCard">
            <div class="cardHeader">
              <div><h2>剧本解析</h2><p>选择要提取的结构化内容；结果应用前保留来源哈希和原始响应。</p></div>
            </div>
            <el-form labelPosition="top">
              <el-form-item label="输入类型">
                <el-select v-model="aiForm.sourceKind">
                  <el-option label="故事创意" value="idea" /><el-option label="故事大纲" value="outline" />
                  <el-option label="小说文本" value="novel" /><el-option label="已有剧本" value="script" />
                  <el-option label="分集剧本" value="episodeScript" />
                </el-select>
              </el-form-item>
              <el-form-item label="语言模型">
                <el-select v-model="aiForm.modelKey" filterable placeholder="选择已配置模型">
                  <el-option v-for="model in languageModels" :key="modelKey(model)" :label="`${model.providerLabel} / ${model.label}`" :value="modelKey(model)" />
                </el-select>
              </el-form-item>
              <el-form-item label="要生成的段落">
                <el-checkbox-group v-model="aiForm.sections">
                  <el-checkbox label="synopsis">简介</el-checkbox><el-checkbox label="world">世界观</el-checkbox>
                  <el-checkbox label="characters">人物</el-checkbox><el-checkbox label="locations">场景</el-checkbox>
                  <el-checkbox label="props">道具</el-checkbox><el-checkbox label="episodes">分集与镜头</el-checkbox>
                  <el-checkbox label="timeline">时间线</el-checkbox>
                </el-checkbox-group>
              </el-form-item>
              <div class="sourceMeta">
                <div><span>待解析文本</span><strong>{{ aiForm.sourceText.length.toLocaleString() }} 字</strong></div>
                <p>{{ aiForm.sourceText ? "已从剧本编制区带入，可在左侧继续切段并选择要解析的片段。" : "请先在左侧输入、上传或选择剧本片段。" }}</p>
              </div>
              <el-button type="primary" :loading="understanding" @click="understand">开始理解</el-button>
            </el-form>
            <div v-if="aiPreview" class="aiPreview">
              <h3>生成结果摘要</h3>
              <p>人物 {{ aiPreview.characters.length }}，场景 {{ aiPreview.locations.length }}，道具 {{ aiPreview.props.length }}，分集 {{ aiPreview.episodes.length }}，连续性提示 {{ aiPreview.continuityWarnings.length }}</p>
              <el-collapse>
                <el-collapse-item title="查看结构化预览" name="preview"><pre>{{ JSON.stringify(aiPreview, null, 2) }}</pre></el-collapse-item>
              </el-collapse>
              <el-button type="success" :loading="applyingAi" @click="applyAi">应用到未确认部分</el-button>
            </div>
          </section>
        </div>
      </el-tab-pane>      <el-tab-pane label="角色与场景" name="assets">
        <div class="assetStudioLayout">
          <assetOverview
            :document="document"
            :directory="directory"
            :selectedId="designerId"
            @design="openAssetDesigner"
            @add="addAssetEntity"
            @globalStyle="globalStyleVisible = true" />
          <assetDesigner
            v-if="designerId"
            :directory="directory"
            :kind="designerKind"
            :document="document"
            :character="designerCharacter"
            :location="designerLocation"
            :prop="designerProp"
            :generating="generating"
            @dirty="markDirty"
            @confirm="confirmEntity"
            @voiceDesign="openVoiceDesigner"
            @generateReference="generateDesignerReference"
            @attachReference="attachDesignerReference"
            @queryImpact="showImpact" />
          <section v-else class="workspaceCard assetEmpty"><el-empty description="选择或新增角色、场景、道具开始设计" /></section>
        </div>
      </el-tab-pane>
      <el-tab-pane label="分镜与 Take" name="storyboard">
        <div class="storyboardLayout">
          <aside class="workspaceCard shotRail">
            <div class="cardHeader compact"><h2>镜头树</h2><el-tag effect="plain">{{ shotRows.length }} 镜</el-tag></div>
            <el-scrollbar class="shotList">
              <div v-for="episode in document.episodes" :key="episode.id" class="episodeBlock">
                <div class="episodeTitle"><strong>第 {{ episode.number }} 集 · {{ episode.title }}</strong><el-tag size="small" :type="episode.confirmed ? 'success' : 'info'">{{ episode.confirmed ? "已确认" : "草稿" }}</el-tag></div>
                <div v-for="scene in episode.scenes" :key="scene.id" class="sceneBlock">
                  <div class="sceneTitle">场 {{ scene.number }} · {{ scene.title }}</div>
                  <button v-for="shot in scene.shots" :key="shot.id" class="shotItem" :class="{ active: shot.id === selectedShotId }" @click="selectShot(shot.id)">
                    <span>{{ scene.number }}-{{ shot.number }} {{ shot.title || shot.description.slice(0, 20) }}</span>
                    <span class="shotStatus"><el-tag size="small" :type="shot.selectedTakeId ? 'success' : shot.takes.length ? 'warning' : 'info'">{{ shot.selectedTakeId ? "正式" : `${shot.takes.length} Take` }}</el-tag></span>
                  </button>
                </div>
              </div>
              <el-empty v-if="!shotRows.length" description="先用 AI 剧本理解生成分集和分镜" :imageSize="70" />
            </el-scrollbar>
          </aside>

          <shotStoryboard
            v-if="selectedShot && selectedShotContext?.scene && selectedShotContext?.episode"
            :directory="directory"
            :document="document"
            :shot="selectedShot"
            :scene="selectedShotContext.scene"
            :episode="selectedShotContext.episode"
            :languageModels="languageModels"
            :mediaModels="mediaModels"
            :generating="generating"
            @dirty="markDirty"
            @confirm="confirmEntity('shot', selectedShot.id, $event)"
            @move="moveShot"
            @split="splitShot"
            @merge="mergeNextShot"
            @sync="syncGeneration(true)"
            @selectTake="selectTake"
            @cancelTask="cancelTask"
            @generateShot="handleStudioGenerate"
            @generateArtifact="handleStudioGenerate" />
          <el-empty v-else class="workspaceCard" description="选择一个镜头" />
        </div>
      </el-tab-pane>      <el-tab-pane label="声音与成片" name="timeline">
        <div class="timelineLayout">
          <section class="workspaceCard timelineCard">
            <div class="cardHeader">
              <div><h2>后期时间轴</h2><p>正式 Take、旁白、音频和 Remotion 预渲染片段统一在这里拼接。</p></div>
              <div class="inlineActions"><el-button @click="addSubtitle">从镜头对白加字幕</el-button><el-button @click="syncGeneration(true)">同步任务</el-button></div>
            </div>
            <div class="timelineComposer">
              <el-select v-model="timelineAssetKind"><el-option label="Remotion / 视频片段" value="remotion" /><el-option label="旁白 / 音频" value="audio" /></el-select>
              <el-select v-model="timelineAssetId" filterable placeholder="选择已登记素材"><el-option v-for="asset in timelineAddableAssets" :key="asset.id" :label="asset.name || asset.path" :value="asset.id" /></el-select>
              <el-button :disabled="!timelineAssetId" @click="addTimelineAsset">加入时间轴</el-button>
            </div>
            <div class="timelineRows">
              <div v-for="item in sortedTimeline" :key="item.id" class="timelineRow">
                <el-tag :type="item.kind === 'video' || item.kind === 'remotion' ? 'primary' : item.kind === 'subtitle' ? 'warning' : 'success'">{{ timelineKindLabel(item.kind) }}</el-tag>
                <el-input-number v-model="item.start" :min="0" :step="0.1" controlsPosition="right" @change="markDirty" />
                <el-input-number v-model="item.duration" :min="0.1" :step="0.1" controlsPosition="right" @change="markDirty" />
                <el-input v-model="item.track" @input="markDirty" />
                <el-input v-if="item.kind === 'subtitle'" v-model="item.text" @input="markDirty" />
                <span v-else class="timelineAsset">{{ item.assetId ? assetName(item.assetId) : item.shotId ? `镜头 ${item.shotId.slice(0, 8)}` : "无素材" }}</span>
                <el-select v-if="item.kind !== 'subtitle' && item.kind !== 'audio' && item.kind !== 'music' && item.kind !== 'sfx'" v-model="item.transition" style="width: 105px" @change="markDirty"><el-option label="硬切" value="cut" /><el-option label="淡入淡出" value="fade" /></el-select>
                <el-button text type="danger" @click="removeTimelineItem(item.id)">移除</el-button>
              </div>
              <el-empty v-if="!document.timeline.length" description="选择 Take 或生成配音后形成时间轴" :imageSize="70" />
            </div>
          </section>

          <aside class="workspaceCard outputCard">
            <h2>成片导出</h2>
            <div class="soundCreate">
              <h3>音乐与音效</h3>
              <el-select v-model="timelineSoundKind"><el-option label="背景音乐" value="music" /><el-option label="音效" value="sfx" /></el-select>
              <el-input v-model="soundPrompt" placeholder="描述音乐或音效" />
              <el-button :loading="generating" @click="generateTimelineSound">生成音频</el-button>
            </div>
            <el-form labelPosition="top">
              <el-form-item label="画幅"><el-select v-model="document.output.aspectRatio" @change="applyAspectRatio"><el-option label="9:16 竖屏短剧" value="9:16" /><el-option label="16:9 横屏" value="16:9" /><el-option label="1:1 方形" value="1:1" /></el-select></el-form-item>
              <el-form-item label="分辨率"><el-input v-model="outputSize" placeholder="1080x1920" /></el-form-item>
              <el-form-item label="帧率"><el-input-number v-model="document.output.fps" :min="1" :max="120" @change="markDirty" /></el-form-item>
              <el-form-item label="格式"><el-select v-model="document.output.format"><el-option label="MP4" value="mp4" /><el-option label="MOV" value="mov" /></el-select></el-form-item>
              <el-form-item label="输出文件名"><el-input v-model="exportPath" /></el-form-item>
            </el-form>
            <el-alert title="导出不会覆盖已有文件；每个成片都会作为新 Asset 记录来源镜头、Take 和素材 ID。" type="info" :closable="false" showIcon />
            <el-button class="exportButton" type="primary" :loading="exporting" @click="exportMovie">导出成片</el-button>
            <el-button class="exportButton" :loading="exportingDraft" @click="exportJianyingDraft">导出剪映草稿</el-button>
            <p v-if="exportResult" class="exportResult">已生成 {{ exportResult.outputPath }}（{{ (exportResult.bytes / 1024 / 1024).toFixed(1) }} MB）</p>
            <p v-if="jianyingResult" class="exportResult">草稿已生成 {{ jianyingResult.draftPath }}；请在剪映实际版本中验证导入。</p>
            <div class="statsGrid">
              <div><strong>{{ shotRows.length }}</strong><span>镜头</span></div>
              <div><strong>{{ takeCount }}</strong><span>Take</span></div>
              <div><strong>{{ completedTakeCount }}</strong><span>可用 Take</span></div>
              <div><strong>{{ document.assets.length }}</strong><span>素材</span></div>
            </div>
            <div class="jobsList" v-if="document.generationJobs.length">
              <h3>参考素材任务</h3>
              <div v-for="job in document.generationJobs.slice(-12).reverse()" :key="job.id" class="jobRow">
                <span>{{ job.kind }}</span><el-tag size="small" :type="job.status === 'completed' ? 'success' : job.status === 'failed' ? 'danger' : 'warning'">{{ job.status }}</el-tag>
                <el-button v-if="job.status === 'generating'" size="small" @click="cancelTask(job.taskId)">取消</el-button>
              </div>
            </div>
          </aside>
        </div>
      </el-tab-pane>
      <el-tab-pane label="画布来源" name="canvas">
        <canvasSources
          :document="document"
          :sources="canvasSourceItems"
          :loading="canvasLoading"
          :importingId="importingSourceId"
          :focusNode="props.focusNode"
          @refresh="loadCanvasSources"
          @import="importCanvasSource"
          @focus="focusCanvasSource"
          @create="createCanvasNode"
          @openCanvas="emit('openCanvas')" />
      </el-tab-pane>
    </el-tabs>
    <globalStyleDialog v-model="globalStyleVisible" :directory="directory" @saved="onGlobalStyleSaved" />
    <voiceDesignDialog v-if="document" v-model="voiceDesignerVisible" :directory="directory" :document="document" :characterId="voiceDesignerCharacterId" :audioModels="audioModels" @dirty="markDirty" @generate="generateVoiceDesign" />
  </section>
</template>
<script setup lang="ts">
import { computed, onMounted, onScopeDispose, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { IconArrowLeft, IconPalette } from "@tabler/icons-vue";
import type { ProductionAsset, ProductionCharacter, ProductionDocument, ProductionLocation, ProductionProp, ProductionShot, ScriptUnderstanding } from "@solodrama/production";
import http from "@/lib/http";
import productionOverview from "./productionOverview.vue";
import canvasSources from "./canvasSources.vue";
import assetOverview from "./assetOverview.vue";
import assetDesigner from "./assetDesigner.vue";
import globalStyleDialog from "./globalStyleDialog.vue";
import shotStoryboard from "./shotStoryboard.vue";
import scriptSegmenter from "./scriptSegmenter.vue";
import voiceDesignDialog from "./voiceDesignDialog.vue";
import type { CanvasImportRequest, CanvasSource, CanvasSourcePreview } from "./canvasSourceTypes";

type LanguageModel = { providerId: string; providerLabel: string; modelId: string; label: string };
type MediaModel = { providerId: string; providerLabel: string; modelId: string; label: string; type: "image" | "video" | "audio" };
type GenerationResult = { itemId: string; taskId: string };
type ExportResult = { outputPath: string; bytes: number; assetId: string };
type JianyingResult = { draftPath: string; metaPath: string; readmePath: string; durationSeconds: number; clips: number; subtitles: number; hasNarration: boolean; hasBgm: boolean };

const props = defineProps<{
  directory: string;
  focusNode?: (canvasPath: string, nodeId: string) => Promise<void>;
  createNode?: (type: string, label: string) => Promise<void>;
}>();
const emit = defineEmits<{ openCanvas: [] }>();
const router = useRouter();
const activeTab = ref("overview");
const globalStyleVisible = ref(false);
const assetDesignerOpen = ref(false);
const designerKind = ref<"character" | "location" | "prop">("character");
const designerId = ref("");
const voiceDesignerVisible = ref(false);
const voiceDesignerCharacterId = ref("");
const document = ref<ProductionDocument>();
const loading = ref(false);
const saving = ref(false);
const dirty = ref(false);
const error = ref("");
const languageModels = ref<LanguageModel[]>([]);
const mediaModels = ref<MediaModel[]>([]);
const aiPreview = ref<ScriptUnderstanding>();
const aiSource = ref<Record<string, unknown>>();
const understanding = ref(false);
const applyingAi = ref(false);
const generating = ref(false);
const exporting = ref(false);
const exportingDraft = ref(false);
const jianyingResult = ref<JianyingResult>();
const exportResult = ref<ExportResult>();
const exportPath = ref("");
const selectedShotId = ref("");
const entityKind = ref<"character" | "location" | "prop">("character");
const selectedEntityId = ref("");
const referenceAssetId = ref("");
const impactText = ref("");
const timelineSoundKind = ref<"music" | "sfx">("music");
const timelineAssetKind = ref<"remotion" | "audio">("remotion");
const timelineAssetId = ref("");
const soundPrompt = ref("");
const canvasSourceItems = ref<CanvasSource[]>([]);
const canvasLoading = ref(false);
const canvasSkippedFiles = ref(0);
const importingSourceId = ref("");
const canvasSourceCount = computed(() => canvasSourceItems.value.length);
const canvasBoundCount = computed(() => canvasSourceItems.value.filter(source => !!source.binding).length);
const canvasPendingCount = computed(() => Math.max(0, canvasSourceCount.value - canvasBoundCount.value));
const aiForm = ref({
  sourceKind: "outline" as "idea" | "outline" | "novel" | "script" | "episodeScript",
  modelKey: "",
  sections: ["synopsis", "world", "characters", "locations", "props", "episodes", "timeline"],
  sourceText: "",
});
const generationForm = ref({
  mediaType: "video" as "image" | "video",
  modelKey: "",
  workflowId: "",
  instanceId: "",
  prompt: "",
  negativePrompt: "",
});

const scriptSourceText = computed({
  get: () => aiForm.value.sourceText || document.value?.storyIdea || "",
  set: (value: string) => {
    aiForm.value.sourceText = value;
    if (document.value) document.value.storyIdea = value;
    markDirty();
  },
});
const allShots = computed(() => document.value?.episodes.flatMap(episode => episode.scenes.flatMap(scene => scene.shots.map(shot => ({ episode, scene, shot })))) ?? []);
const shotRows = computed(() => allShots.value);
const selectedShotContext = computed(() => allShots.value.find(item => item.shot.id === selectedShotId.value));
const selectedShot = computed(() => selectedShotContext.value?.shot);
const selectedScene = computed(() => selectedShotContext.value?.scene);
const imageAssets = computed(() => document.value?.assets.filter(asset => asset.type === "image") ?? []);
const generationMediaModels = computed(() => mediaModels.value.filter(model => model.type === generationForm.value.mediaType));
const audioModels = computed(() => mediaModels.value.filter((model): model is MediaModel & { type: "audio" } => model.type === "audio"));
const takeCount = computed(() => allShots.value.reduce((sum, item) => sum + item.shot.takes.length, 0));
const completedTakeCount = computed(() => allShots.value.reduce((sum, item) => sum + item.shot.takes.filter(take => ["completed", "confirmed"].includes(take.status)).length, 0));
const entityItems = computed(() => entityKind.value === "character" ? document.value?.characters ?? [] : entityKind.value === "location" ? document.value?.locations ?? [] : document.value?.props ?? []);
const selectedCharacter = computed(() => entityKind.value === "character" ? document.value?.characters.find(item => item.id === selectedEntityId.value) : undefined);
const selectedLocation = computed(() => entityKind.value === "location" ? document.value?.locations.find(item => item.id === selectedEntityId.value) : undefined);
const selectedProp = computed(() => entityKind.value === "prop" ? document.value?.props.find(item => item.id === selectedEntityId.value) : undefined);
const sortedTimeline = computed(() => [...(document.value?.timeline ?? [])].sort((left, right) => left.start - right.start));
const timelineAddableAssets = computed(() => (document.value?.assets ?? []).filter(asset => timelineAssetKind.value === "remotion" ? asset.type === "video" : asset.type === "audio"));
const outputSize = computed({
  get: () => document.value ? `${document.value.output.width}x${document.value.output.height}` : "",
  set: (value: string) => {
    const match = /^(\d+)x(\d+)$/i.exec(value.trim());
    if (!match || !document.value) return;
    document.value.output.width = Number(match[1]);
    document.value.output.height = Number(match[2]);
    markDirty();
  },
});

function modelKey(model: LanguageModel | MediaModel) {
  return JSON.stringify([model.providerId, model.modelId]);
}
function mediaModelKey(model: MediaModel) {
  return modelKey(model);
}
function pickModel<T extends LanguageModel | MediaModel>(models: T[], key: string) {
  try {
    const value = JSON.parse(key);
    return models.find(model => model.providerId === value[0] && model.modelId === value[1]);
  } catch { return undefined; }
}

const designerCharacter = computed(() => designerKind.value === "character" ? document.value?.characters.find(item => item.id === designerId.value) : undefined);
const designerLocation = computed(() => designerKind.value === "location" ? document.value?.locations.find(item => item.id === designerId.value) : undefined);
const designerProp = computed(() => designerKind.value === "prop" ? document.value?.props.find(item => item.id === designerId.value) : undefined);

function goHome() {
  void router.push("/home");
}
function onGlobalStyleSaved() {
  ElMessage.success("全局画风已应用，后续提示词优化会自动带入");
}
function openAssetDesigner(kind: "character" | "location" | "prop", id: string) {
  designerKind.value = kind;
  designerId.value = id;
}
function openVoiceDesigner(characterId: string) {
  voiceDesignerCharacterId.value = characterId;
  voiceDesignerVisible.value = true;
}
function addAssetEntity(kind: "character" | "location" | "prop") {
  if (!document.value) return;
  const now = Date.now();
  if (kind === "character") {
    const entity = { id: crypto.randomUUID(), name: "新角色", description: "", appearance: "", visualDescription: "", personality: "", age: "", clothingVersions: [], visualProfile: { face: "", hair: "", body: "", style: "" }, referenceImages: [], voice: {}, relationships: [], confirmed: false, revision: 0, createdAt: now, updatedAt: now };
    document.value.characters.push(entity);
    openAssetDesigner("character", entity.id);
  } else if (kind === "location") {
    const entity = { id: crypto.randomUUID(), name: "新场景", description: "", spatialStructure: "", lighting: "", colorPalette: "", timeOfDay: "", atmosphere: "", referenceImages: [], propIds: [], confirmed: false, revision: 0, createdAt: now, updatedAt: now };
    document.value.locations.push(entity);
    openAssetDesigner("location", entity.id);
  } else {
    const entity = { id: crypto.randomUUID(), name: "新道具", description: "", referenceImages: [], confirmed: false, revision: 0, createdAt: now, updatedAt: now };
    document.value.props.push(entity);
    openAssetDesigner("prop", entity.id);
  }
  markDirty();
}
async function generateDesignerReference(kind: "character" | "location" | "prop", id: string) {
  const targetType = kind === "character" ? "characterReference" : kind === "location" ? "locationReference" : "propReference";
  await generateReference(targetType, id);
}
async function attachDesignerReference(kind: "character" | "location" | "prop", id: string, assetId: string) {
  if (!document.value) return;
  if (!await save(true)) return;
  try {
    await reloadAfterMutation(await http<ProductionDocument>({
      method: "POST", url: "/api/production/asset/reference",
      data: { directory: props.directory, expectedRevision: document.value.revision, targetType: kind, targetId: id, assetId, confirmed: false },
    }));
  } catch (cause) { ElMessage.error(cause instanceof Error ? cause.message : "关联参考图失败"); }
}
function markDirty() {
  dirty.value = true;
}
function assetName(assetId: string) {
  const asset = document.value?.assets.find(item => item.id === assetId);
  return asset?.name || asset?.path || assetId.slice(0, 8);
}
function selectShot(id: string) {
  selectedShotId.value = id;
}
watch(entityKind, () => {
  selectedEntityId.value = entityItems.value[0]?.id ?? "";
  referenceAssetId.value = "";
});
watch(() => entityItems.value.length, () => {
  if (!entityItems.value.some(item => item.id === selectedEntityId.value)) selectedEntityId.value = entityItems.value[0]?.id ?? "";
});
watch(() => generationForm.value.mediaType, () => {
  generationForm.value.modelKey = generationMediaModels.value[0] ? mediaModelKey(generationMediaModels.value[0]) : "";
});
async function load() {
  if (!props.directory) return;
  loading.value = true;
  error.value = "";
  try {
    const [production, language, media] = await Promise.all([
      http<ProductionDocument>({ method: "GET", url: "/api/production/get", params: { directory: props.directory } }),
      http<LanguageModel[]>({ method: "GET", url: "/api/ai/models" }),
      http<MediaModel[]>({ method: "GET", url: "/api/ai/media/models" }),
    ]);
    document.value = production;
    languageModels.value = language;
    mediaModels.value = media;
    aiForm.value.modelKey ||= language[0] ? modelKey(language[0]) : "";
    aiForm.value.sourceText ||= production.storyIdea;
    generationForm.value.modelKey ||= generationMediaModels.value[0] ? mediaModelKey(generationMediaModels.value[0]) : "";
    if (!shotRows.value.some(item => item.shot.id === selectedShotId.value)) selectedShotId.value = shotRows.value[0]?.shot.id ?? "";
    selectedEntityId.value = entityItems.value.some(item => item.id === selectedEntityId.value) ? selectedEntityId.value : entityItems.value[0]?.id ?? "";
    if (!designerId.value) openAssetDesigner("character", production.characters[0]?.id ?? "");
    exportPath.value = `outputs/SoloDrama-${new Date().toISOString().slice(0, 10)}.${production.output.format}`;
    dirty.value = false;
    await loadCanvasSources();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : "制作数据加载失败";
  } finally {
    loading.value = false;
  }
}

async function loadCanvasSources() {
  if (!props.directory) return;
  canvasLoading.value = true;
  try {
    const preview = await http<CanvasSourcePreview>({ method: "GET", url: "/api/production/canvas/sources", params: { directory: props.directory } });
    canvasSourceItems.value = preview.sources;
    canvasSkippedFiles.value = preview.skippedFiles;
  } catch (cause) {
    ElMessage.warning(cause instanceof Error ? cause.message : "画布来源读取失败");
  } finally {
    canvasLoading.value = false;
  }
}

async function importCanvasSource(request: CanvasImportRequest) {
  if (!document.value) return;
  if (!await save(true)) return;
  importingSourceId.value = request.source.id;
  try {
    const result = await http<{ document: ProductionDocument }>({
      method: "POST", url: "/api/production/canvas/import",
      data: {
        directory: props.directory, expectedRevision: document.value.revision, sourceId: request.source.id,
        targetType: request.targetType, targetId: request.targetId,
      },
    });
    await reloadAfterMutation(result.document);
    await loadCanvasSources();
    ElMessage.success("画布来源已导入 Production");
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : "画布来源导入失败");
  } finally {
    importingSourceId.value = "";
  }
}

async function focusCanvasSource(canvasPath: string, nodeId: string) {
  if (!props.focusNode) return;
  try { await props.focusNode(canvasPath, nodeId); }
  catch (cause) { ElMessage.error(cause instanceof Error ? cause.message : "无法定位画布节点"); }
}

async function createCanvasNode(type: string, label: string) {
  if (!props.createNode) return;
  try { await props.createNode(type, label); }
  catch (cause) { ElMessage.error(cause instanceof Error ? cause.message : "无法创建画布节点"); }
}

async function save(quiet = false) {
  if (!document.value || !dirty.value || saving.value) return true;
  saving.value = true;
  try {
    const saved = await http<ProductionDocument>({
      method: "PUT", url: "/api/production/save",
      data: { directory: props.directory, expectedRevision: document.value.revision, document: document.value },
    });
    document.value = saved;
    dirty.value = false;
    if (!quiet) ElMessage.success("制作数据已保存");
    return true;
  } catch (cause) {
    ElMessage.error(cause instanceof Error ? cause.message : "保存失败");
    return false;
  } finally {
    saving.value = false;
  }
}

async function reloadAfterMutation(value: ProductionDocument) {
  const shot = selectedShotId.value;
  document.value = value;
  if (!shotRows.value.some(item => item.shot.id === shot)) selectedShotId.value = shotRows.value[0]?.shot.id ?? "";
  dirty.value = false;
}

async function confirmSection(section: string, confirmed: boolean) {
  if (!document.value) return;
  if (!await save(true)) return;
  try {
    await reloadAfterMutation(await http<ProductionDocument>({
      method: "POST", url: "/api/production/entity/confirm",
      data: { directory: props.directory, expectedRevision: document.value.revision, targetType: section, confirmed },
    }));
  } catch (cause) { ElMessage.error(cause instanceof Error ? cause.message : "确认失败"); }
}

async function confirmEntity(targetType: string, targetId: string, confirmed: boolean) {
  if (!document.value) return;
  if (!await save(true)) return;
  try {
    await reloadAfterMutation(await http<ProductionDocument>({
      method: "POST", url: "/api/production/entity/confirm",
      data: { directory: props.directory, expectedRevision: document.value.revision, targetType, targetId, confirmed },
    }));
    ElMessage.success(confirmed ? "已确认" : "已取消确认");
  } catch (cause) { ElMessage.error(cause instanceof Error ? cause.message : "确认失败"); }
}

async function understand() {
  if (!aiForm.value.sourceText.trim()) return ElMessage.warning("请输入故事文本");
  const model = pickModel(languageModels.value, aiForm.value.modelKey);
  if (!model) return ElMessage.warning("请选择语言模型");
  understanding.value = true;
  try {
    const response = await http<{ result: ScriptUnderstanding; source: Record<string, unknown> }>({
      method: "POST", url: "/api/production/ai/understand",
      data: {
        directory: props.directory, providerId: model.providerId, modelId: model.modelId,
        title: document.value?.name || "未命名短剧", sourceText: aiForm.value.sourceText,
        sourceKind: aiForm.value.sourceKind, sections: aiForm.value.sections,
      }, timeout: 10 * 60 * 1000,
    });
    aiPreview.value = response.result;
    aiSource.value = response.source;
  } catch (cause) { ElMessage.error(cause instanceof Error ? cause.message : "剧本理解失败"); }
  finally { understanding.value = false; }
}

async function applyAi() {
  if (!document.value || !aiPreview.value || !aiSource.value) return;
  applyingAi.value = true;
  try {
    const result = await http<ProductionDocument>({
      method: "POST", url: "/api/production/ai/apply",
      data: {
        directory: props.directory, expectedRevision: document.value.revision,
        result: aiPreview.value, source: aiSource.value, sections: aiForm.value.sections,
      },
    });
    await reloadAfterMutation(result);
    aiPreview.value = undefined;
    aiSource.value = undefined;
    ElMessage.success("AI 结果已应用到未确认部分");
  } catch (cause) { ElMessage.error(cause instanceof Error ? cause.message : "应用失败"); }
  finally { applyingAi.value = false; }
}
async function startGeneration(targetType: string, targetId: string, mediaType: "image" | "video" | "audio", model: MediaModel, extra: Record<string, unknown> = {}) {
  if (!document.value) return;
  if (!await save(true)) return;
  generating.value = true;
  try {
    await http<GenerationResult>({
      method: "POST", url: "/api/production/generation/start",
      data: {
        directory: props.directory, expectedRevision: document.value.revision,
        targetType, targetId, mediaType, providerId: model.providerId, modelId: model.modelId,
        ...extra,
      },
    });
    await load();
    ElMessage.success("任务已提交，可在页面中查看进度");
  } catch (cause) { ElMessage.error(cause instanceof Error ? cause.message : "任务提交失败"); }
  finally { generating.value = false; }
}

async function handleStudioGenerate(payload: Record<string, unknown>) {
  const providerId = String(payload.providerId ?? "");
  const modelId = String(payload.modelId ?? "");
  const model = mediaModels.value.find(item => item.providerId === providerId && item.modelId === modelId);
  if (!model) return ElMessage.warning("所选媒体模型不存在，请刷新后重试");
  const { targetType, targetId, mediaType, providerId: _providerId, modelId: _modelId, ...extra } = payload;
  await startGeneration(String(targetType), String(targetId), mediaType as "image" | "video" | "audio", model, extra);
}
async function generateShot() {
  if (!selectedShot.value) return;
  const model = pickModel(mediaModels.value, generationForm.value.modelKey);
  if (!model) return ElMessage.warning("请选择图片或视频模型");
  await startGeneration("shot", selectedShot.value.id, generationForm.value.mediaType, model, {
    prompt: generationForm.value.prompt || undefined,
    negativePrompt: generationForm.value.negativePrompt || undefined,
    workflowId: generationForm.value.workflowId || undefined,
    instanceId: generationForm.value.instanceId || undefined,
    duration: generationForm.value.mediaType === "video" ? selectedShot.value.duration : undefined,
  });
}

async function generateVoice() {
  if (!selectedShot.value) return;
  const model = audioModels.value[0];
  if (!model) return ElMessage.warning("请先配置音频或语音模型");
  const character = selectedShot.value.characterIds.length ? document.value?.characters.find(item => item.id === selectedShot.value!.characterIds[0]) : undefined;
  await startGeneration("voice", selectedShot.value.id, "audio", model, {
    voice: character?.voice.voiceId,
    speed: character?.voice.speed,
    language: character?.voice.language,
  });
}

async function generateVoiceDesign(payload: Record<string, unknown>) {
  const providerId = String(payload.providerId ?? "");
  const modelId = String(payload.modelId ?? "");
  const model = audioModels.value.find(item => item.providerId === providerId && item.modelId === modelId);
  if (!model) return ElMessage.warning("所选语音模型不存在，请刷新后重试");
  if (!voiceDesignerCharacterId.value) return ElMessage.warning("请选择角色");
  const { providerId: _providerId, modelId: _modelId, ...extra } = payload;
  await startGeneration("voiceDesign", voiceDesignerCharacterId.value, "audio", model, extra);
}
async function generateReference(targetType: "characterReference" | "locationReference" | "propReference", targetId: string) {
  const model = mediaModels.value.find(item => item.type === "image");
  if (!model) return ElMessage.warning("请先配置图片生成模型");
  await startGeneration(targetType, targetId, "image", model);
}



async function batchStoryboards() {
  if (!document.value) return;
  const model = mediaModels.value.find(item => item.type === "image");
  if (!model) return ElMessage.warning("请先配置图片生成模型");
  const targets = allShots.value.filter(item => !item.shot.storyboardAssetId && !item.shot.confirmed);
  if (!targets.length) return ElMessage.info("没有待生成分镜图的镜头");
  if (!await save(true)) return;
  generating.value = true;
  let submitted = 0;
  let failed = 0;
  try {
    for (const item of targets) {
      try {
        await http<GenerationResult>({
          method: "POST", url: "/api/production/generation/start",
          data: { directory: props.directory, expectedRevision: document.value!.revision, targetType: "storyboard", targetId: item.shot.id, mediaType: "image", providerId: model.providerId, modelId: model.modelId },
        });
        document.value = await http<ProductionDocument>({ method: "GET", url: "/api/production/get", params: { directory: props.directory } });
        submitted += 1;
      } catch { failed += 1; }
    }
    ElMessage.success(`已提交 ${submitted} 个分镜任务${failed ? `，${failed} 个失败` : ""}`);
  } finally { generating.value = false; }
}

async function batchShotVideos() {
  if (!document.value) return;
  const model = mediaModels.value.find(item => item.type === "video");
  if (!model) return ElMessage.warning("请先配置视频生成模型");
  const episode = selectedShotContext.value?.episode ?? document.value.episodes[0];
  const targets = episode?.scenes.flatMap(scene => scene.shots).filter(shot => !shot.selectedTakeId && !shot.confirmed) ?? [];
  if (!targets.length) return ElMessage.info("当前分集没有待生成镜头");
  if (!await save(true)) return;
  generating.value = true;
  let submitted = 0;
  let failed = 0;
  try {
    for (const shot of targets) {
      try {
        await http<GenerationResult>({
          method: "POST", url: "/api/production/generation/start",
          data: { directory: props.directory, expectedRevision: document.value!.revision, targetType: "shot", targetId: shot.id, mediaType: "video", providerId: model.providerId, modelId: model.modelId, duration: shot.duration },
        });
        document.value = await http<ProductionDocument>({ method: "GET", url: "/api/production/get", params: { directory: props.directory } });
        submitted += 1;
      } catch { failed += 1; }
    }
    ElMessage.success(`已提交 ${submitted} 个镜头任务${failed ? `，${failed} 个失败` : ""}`);
  } finally { generating.value = false; }
}

async function generateTimelineSound() {
  if (!document.value) return;
  const model = audioModels.value[0];
  if (!model) return ElMessage.warning("请先配置音频模型");
  if (!soundPrompt.value.trim()) return ElMessage.warning("请描述音乐或音效");
  await startGeneration(timelineSoundKind.value, document.value.id, "audio", model, { prompt: soundPrompt.value.trim() });
  soundPrompt.value = "";
}

async function syncGeneration(resume = true) {
  if (!document.value) return;
  const pending = document.value.generationJobs.some(job => job.status === "generating")
    || allShots.value.some(item => item.shot.takes.some(take => take.status === "generating"));
  if (!pending) return;
  if (dirty.value && !await save(true)) return;
  try {
    const result = await http<ProductionDocument>({
      method: "POST", url: "/api/production/generation/status",
      data: { directory: props.directory, expectedRevision: document.value.revision, resume },
    });
    await reloadAfterMutation(result);
  } catch (cause) {
    if ((cause as { status?: number }).status === 409) await load();
  }
}

async function cancelTask(taskId: string) {
  if (!document.value) return;
  if (!await save(true)) return;
  try {
    await reloadAfterMutation(await http<ProductionDocument>({
      method: "POST", url: "/api/production/generation/cancel",
      data: { directory: props.directory, expectedRevision: document.value.revision, taskIds: [taskId] },
    }));
  } catch (cause) { ElMessage.error(cause instanceof Error ? cause.message : "取消失败"); }
}

async function selectTake(takeId: string) {
  if (!selectedShot.value || !document.value) return;
  if (!await save(true)) return;
  try {
    await reloadAfterMutation(await http<ProductionDocument>({
      method: "POST", url: "/api/production/take/select",
      data: { directory: props.directory, expectedRevision: document.value.revision, shotId: selectedShot.value.id, takeId },
    }));
    ElMessage.success("已设为正式 Take，并更新视频时间轴");
  } catch (cause) { ElMessage.error(cause instanceof Error ? cause.message : "选择失败"); }
}

async function attachSelectedReference(targetType: "character" | "location" | "prop", targetId: string) {
  if (!document.value || !referenceAssetId.value) return;
  if (!await save(true)) return;
  try {
    await reloadAfterMutation(await http<ProductionDocument>({
      method: "POST", url: "/api/production/asset/reference",
      data: { directory: props.directory, expectedRevision: document.value.revision, targetType, targetId, assetId: referenceAssetId.value, confirmed: true },
    }));
    referenceAssetId.value = "";
  } catch (cause) { ElMessage.error(cause instanceof Error ? cause.message : "关联参考图失败"); }
}

function removeReference(targetType: "character" | "location" | "prop", targetId: string, referenceId: string) {
  const item = targetType === "character" ? document.value?.characters.find(entry => entry.id === targetId)
    : targetType === "location" ? document.value?.locations.find(entry => entry.id === targetId)
      : document.value?.props.find(entry => entry.id === targetId);
  if (!item) return;
  item.referenceImages = item.referenceImages.filter(reference => reference.id !== referenceId);
  markDirty();
}

function addClothingVersion() {
  if (!selectedCharacter.value) return;
  selectedCharacter.value.clothingVersions.push({ id: crypto.randomUUID(), name: "新服装", description: "", assetIds: [], confirmed: false });
  markDirty();
}

async function showImpact(targetType: "character" | "location" | "prop", targetId: string) {
  try {
    const result = await http<{ count: number; shots: { episodeNumber: number; sceneNumber: number; shotNumber: number }[] }>({
      method: "GET", url: "/api/production/impact", params: { directory: props.directory, targetType, targetId },
    });
    impactText.value = result.count
      ? `该设定影响 ${result.count} 个镜头：${result.shots.map(item => `${item.episodeNumber}-${item.sceneNumber}-${item.shotNumber}`).join("、")}`
      : "当前没有镜头引用该设定";
  } catch (cause) { ElMessage.error(cause instanceof Error ? cause.message : "影响查询失败"); }
}
function splitShot() {
  const context = selectedShotContext.value;
  if (!context) return;
  const index = context.scene.shots.findIndex(item => item.id === context.shot.id);
  const now = Date.now();
  const next: ProductionShot = {
    ...structuredClone(context.shot), id: crypto.randomUUID(), number: context.shot.number + 1,
    title: `${context.shot.title || "镜头"}（拆分）`, takes: [], selectedTakeId: undefined, storyboardAssetId: undefined,
    confirmed: false, revision: 0, createdAt: now, updatedAt: now,
  };
  for (const shot of context.scene.shots.slice(index + 1)) shot.number += 1;
  context.scene.shots.splice(index + 1, 0, next);
  markDirty();
  selectedShotId.value = next.id;
}

function mergeNextShot() {
  const context = selectedShotContext.value;
  if (!context) return;
  const index = context.scene.shots.findIndex(item => item.id === context.shot.id);
  const next = context.scene.shots[index + 1];
  if (!next) return ElMessage.warning("当前已经是最后一个镜头");
  const current = context.shot;
  current.title = [current.title, next.title].filter(Boolean).join(" / ");
  current.description = [current.description, next.description].filter(Boolean).join("\n");
  current.action = [current.action, next.action].filter(Boolean).join("\n");
  current.dialogue = [current.dialogue, next.dialogue].filter(Boolean).join("\n");
  current.duration += next.duration;
  for (const take of next.takes) { take.shotId = current.id; current.takes.push(take); }
  if (!current.selectedTakeId) current.selectedTakeId = next.selectedTakeId;
  current.updatedAt = Date.now();
  current.revision += 1;
  context.scene.shots.splice(index + 1, 1);
  context.scene.shots.forEach((shot, shotIndex) => { shot.number = shotIndex + 1; });
  markDirty();
}

function moveShot(direction: -1 | 1) {
  const context = selectedShotContext.value;
  if (!context) return;
  const shots = context.scene.shots;
  const index = shots.findIndex(item => item.id === context.shot.id);
  const target = index + direction;
  if (target < 0 || target >= shots.length) return;
  [shots[index], shots[target]] = [shots[target]!, shots[index]!];
  shots.forEach((shot, shotIndex) => { shot.number = shotIndex + 1; });
  markDirty();
}

function addSubtitle() {
  if (!document.value || !selectedShot.value) return;
  const start = allShots.value.slice(0, allShots.value.findIndex(item => item.shot.id === selectedShot.value!.id)).reduce((sum, item) => sum + item.shot.duration, 0);
  document.value.timeline.push({
    id: crypto.randomUUID(), kind: "subtitle", shotId: selectedShot.value.id,
    start, duration: selectedShot.value.duration, track: "subtitle", text: selectedShot.value.dialogue,
    volume: 1, muted: false, transition: "cut",
  });
  markDirty();
}

function timelineKindLabel(kind: string) {
  return ({ video: "画面", audio: "旁白", subtitle: "字幕", music: "音乐", sfx: "音效", remotion: "Remotion" } as Record<string, string>)[kind] ?? kind;
}
function addTimelineAsset() {
  if (!document.value) return;
  const asset = document.value.assets.find(item => item.id === timelineAssetId.value);
  if (!asset) return ElMessage.warning("请选择要加入时间轴的素材");
  const expectedType = timelineAssetKind.value === "remotion" ? "video" : "audio";
  if (asset.type !== expectedType) return ElMessage.warning("素材类型与当前轨道类型不一致");
  const duration = Number(asset.metadata?.duration);
  const start = document.value.timeline.reduce((end, item) => Math.max(end, item.start + item.duration), 0);
  document.value.timeline.push({
    id: crypto.randomUUID(), kind: timelineAssetKind.value, assetId: asset.id, start,
    duration: Number.isFinite(duration) && duration > 0 ? duration : 5, track: timelineAssetKind.value === "remotion" ? "insert" : "narration",
    volume: 1, muted: false, transition: "cut",
  });
  timelineAssetId.value = "";
  markDirty();
}
function removeTimelineItem(id: string) {
  if (!document.value) return;
  document.value.timeline = document.value.timeline.filter(item => item.id !== id);
  markDirty();
}

function applyAspectRatio(value: string) {
  if (!document.value) return;
  const sizes: Record<string, [number, number]> = { "9:16": [1080, 1920], "16:9": [1920, 1080], "1:1": [1080, 1080] };
  const size = sizes[value];
  if (size) [document.value.output.width, document.value.output.height] = size;
  markDirty();
}

async function exportJianyingDraft() {
  if (!document.value) return;
  if (!await save(true)) return;
  exportingDraft.value = true;
  jianyingResult.value = undefined;
  try {
    jianyingResult.value = await http<JianyingResult>({ method: "POST", url: "/api/production/timeline/jianying", data: { directory: props.directory }, timeout: 30 * 60 * 1000 });
    ElMessage.success("剪映草稿已生成");
  } catch (cause) { ElMessage.error(cause instanceof Error ? cause.message : "剪映草稿导出失败"); }
  finally { exportingDraft.value = false; }
}
async function exportMovie() {
  if (!document.value) return;
  if (!await save(true)) return;
  exporting.value = true;
  try {
    exportResult.value = await http<ExportResult>({
      method: "POST", url: "/api/production/timeline/export",
      data: {
        directory: props.directory, outputPath: exportPath.value,
        width: document.value.output.width, height: document.value.output.height, fps: document.value.output.fps,
      },
      timeout: 30 * 60 * 1000,
    });
    await load();
    ElMessage.success("成片导出完成");
  } catch (cause) { ElMessage.error(cause instanceof Error ? cause.message : "成片导出失败"); }
  finally { exporting.value = false; }
}

const pollTimer = setInterval(() => { void syncGeneration(true); }, 5000);
onScopeDispose(() => clearInterval(pollTimer));
onMounted(load);
watch(() => props.directory, load);
defineExpose({ flushSave: () => save(true) });
</script>
<style scoped lang="scss">
.productionPage {
  position: absolute;
  inset: 0;
  z-index: 8;
  overflow: auto;
  padding: 24px 28px 80px;
  color: var(--el-text-color-primary);
  background: color-mix(in srgb, var(--el-bg-color-page) 94%, #8fd7d0 6%);

  .productionHeader {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 24px;
    margin-bottom: 18px;

    h1 { margin: 2px 0 6px; font-size: 26px; letter-spacing: -0.03em; }
    .eyebrow { margin: 0; color: var(--el-color-primary); font-size: 12px; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; }
    .summary { max-width: 880px; margin: 0; color: var(--el-text-color-secondary); line-height: 1.65; }
    .headerActions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
  }

  .productionTabs {
    min-height: calc(100vh - 165px);
  }

  .workspaceCard {
    border: 1px solid var(--el-border-color-light);
    border-radius: 14px;
    background: var(--el-bg-color-overlay);
    box-shadow: 0 12px 36px #23352d10;
  }

  .cardHeader {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 18px;
    margin-bottom: 18px;

    &.compact { align-items: center; margin-bottom: 10px; }
    h2, h3, p { margin: 0; }
    h2 { font-size: 18px; }
    h3 { font-size: 15px; }
    p { margin-top: 4px; color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.55; }
  }

  .scriptLayout { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(380px, 0.85fr); gap: 16px; }
  .editorCard, .aiCard, .entityEditor, .timelineCard, .outputCard { padding: 20px; }
  .scriptOutputForm { margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--el-border-color-lighter); }
  .sourceMeta { display: grid; gap: 5px; margin-bottom: 16px; padding: 12px; border-radius: 9px; background: var(--el-fill-color-lighter); }
  .sourceMeta div { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
  .sourceMeta p { margin: 0; color: var(--el-text-color-secondary); font-size: 11px; line-height: 1.55; }
  .formGrid { display: grid; gap: 0 14px; }
  .formGrid.twoColumns { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .formGrid.threeColumns { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .span2 { grid-column: span 2; }
  .confirmGroup, .inlineActions { display: flex; align-items: center; gap: 8px; }
  .inlineActions.wrap { flex-wrap: wrap; margin-bottom: 10px; }
  .sectionConfirms { display: flex; flex-wrap: wrap; gap: 18px; margin-top: 8px; }
  .warningList { display: grid; gap: 8px; margin-top: 12px; }
  .aiPreview { display: grid; gap: 12px; margin-top: 18px; padding-top: 16px; border-top: 1px solid var(--el-border-color-lighter); }
  .aiPreview pre { max-height: 360px; overflow: auto; padding: 12px; border-radius: 8px; background: var(--el-fill-color-light); font-size: 11px; white-space: pre-wrap; }

  .assetLayout { display: grid; grid-template-columns: 240px minmax(0, 1fr); gap: 16px; align-items: start; }
  .entityRail { display: grid; gap: 12px; min-height: 640px; padding: 14px; }
  .entityList { height: 560px; margin-top: 4px; }
  .entityItem { display: flex; width: 100%; align-items: center; justify-content: space-between; gap: 8px; padding: 10px; border: 1px solid transparent; border-radius: 9px; background: transparent; color: inherit; text-align: left; cursor: pointer; }
  .entityItem:hover, .entityItem.active { border-color: var(--el-color-primary-light-7); background: var(--el-color-primary-light-9); }
  .entityEditor { min-height: 640px; }
  .entityReferences, .versionBlock { display: grid; gap: 10px; padding-top: 16px; margin-top: 16px; border-top: 1px solid var(--el-border-color-lighter); }
  .entityReferences h3, .versionBlock h3 { margin: 0; }
  .referenceList { display: flex; flex-wrap: wrap; gap: 8px; }
  .versionRow { display: grid; grid-template-columns: minmax(120px, 0.7fr) minmax(220px, 1.3fr) auto; align-items: center; gap: 8px; }
  .impactAlert { grid-column: 2; }
  .assetStudioLayout { display: grid; grid-template-columns: 310px minmax(0, 1fr); gap: 16px; align-items: start; }
  .assetEmpty { min-height: 720px; display: grid; place-items: center; }
  .storyboardLayout { display: grid; grid-template-columns: 290px minmax(0, 1fr); gap: 16px; align-items: start; }
  .shotRail { min-height: 720px; padding: 14px; }
  .shotList { height: 650px; }
  .episodeBlock { margin-bottom: 12px; }
  .episodeTitle { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 4px; }
  .sceneBlock { margin: 4px 0 8px 7px; padding-left: 9px; border-left: 1px solid var(--el-border-color); }
  .sceneTitle { padding: 5px 4px; color: var(--el-text-color-secondary); font-size: 11px; }
  .shotItem { display: flex; width: 100%; align-items: center; justify-content: space-between; gap: 8px; padding: 8px; border: 1px solid transparent; border-radius: 8px; background: transparent; color: inherit; font-size: 12px; text-align: left; cursor: pointer; }
  .shotItem:hover, .shotItem.active { border-color: var(--el-color-primary-light-7); background: var(--el-color-primary-light-9); }
  .shotStatus { flex-shrink: 0; }
  .shotEditor { min-height: 720px; padding: 18px; }
  .generationBox { margin-top: 10px; padding: 14px; border-radius: 10px; background: var(--el-fill-color-lighter); }
  .generationBox > .el-input { margin-top: 8px; }
  .takeSection { margin-top: 18px; padding-top: 16px; border-top: 1px solid var(--el-border-color-lighter); }
  .takeRow { display: grid; grid-template-columns: minmax(180px, 1.2fr) auto 60px minmax(130px, 1fr) auto auto; align-items: center; gap: 10px; padding: 10px; border: 1px solid var(--el-border-color-lighter); border-radius: 9px; margin-bottom: 8px; }
  .takeRow.selected { border-color: var(--el-color-success-light-5); background: var(--el-color-success-light-9); }
  .takeRow > div { display: flex; flex-direction: column; gap: 2px; }
  .muted { color: var(--el-text-color-secondary); font-size: 11px; }
  .takeAsset, .timelineAsset { overflow: hidden; color: var(--el-text-color-regular); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }

  .timelineLayout { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 16px; align-items: start; }
  .timelineComposer { display: grid; grid-template-columns: 180px minmax(180px, 1fr) auto; gap: 8px; margin-bottom: 12px; padding: 10px; border-radius: 10px; background: var(--el-fill-color-lighter); }
  .timelineRows { display: grid; gap: 8px; }
  .timelineRow { display: grid; grid-template-columns: 75px 135px 135px 100px minmax(140px, 1fr) 105px auto; align-items: center; gap: 8px; padding: 8px; border: 1px solid var(--el-border-color-lighter); border-radius: 9px; }
  .outputCard { display: grid; gap: 14px; }
  .outputCard h2 { margin: 0; font-size: 18px; }
  .outputCard .el-alert { margin-top: 2px; }
  .soundCreate { display: grid; grid-template-columns: 1fr; align-items: center; gap: 8px; padding: 12px; border-radius: 9px; background: var(--el-fill-color-lighter); }
  .soundCreate h3 { margin: 0; font-size: 14px; }
  .exportButton { width: 100%; }
  .exportResult { margin: 0; color: var(--el-color-success); font-size: 12px; line-height: 1.5; }
  .statsGrid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
  .statsGrid div { display: flex; flex-direction: column; gap: 2px; padding: 12px; border-radius: 9px; background: var(--el-fill-color-lighter); }
  .statsGrid strong { font-size: 22px; }
  .statsGrid span { color: var(--el-text-color-secondary); font-size: 11px; }
  .jobsList { display: grid; gap: 7px; }
  .jobsList h3 { margin: 0; }
  .jobRow { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; align-items: center; gap: 8px; font-size: 12px; }
  .emptyState { display: grid; min-height: 55vh; place-items: center; align-content: center; gap: 12px; color: var(--el-text-color-secondary); }

  @media (max-width: 1180px) {
    .scriptLayout, .timelineLayout { grid-template-columns: 1fr; }
    .shotEditor .threeColumns { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .timelineComposer { grid-template-columns: 1fr; }
    .timelineRow { grid-template-columns: 70px 120px 120px minmax(110px, 1fr) auto; }
    .timelineRow .timelineAsset, .timelineRow .el-select { grid-column: span 2; }
  }

  @media (max-width: 900px) {
    padding: 16px 14px 80px;
    .productionHeader { flex-direction: column; }
    .assetLayout, .assetStudioLayout, .storyboardLayout { grid-template-columns: 1fr; }
    .entityRail, .shotRail { min-height: auto; }
    .entityList, .shotList { height: 280px; }
    .formGrid.twoColumns, .formGrid.threeColumns { grid-template-columns: 1fr; }
    .span2 { grid-column: auto; }
    .takeRow { grid-template-columns: 1fr auto; }
    .referenceList, .impactAlert { grid-column: auto; }
  }
}
</style>





