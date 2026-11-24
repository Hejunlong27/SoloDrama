<template>
  <section class="workbenchPanel" :aria-busy="loading">
    <div class="filmGrain" aria-hidden="true" />
    <header class="workbenchHeader">
      <div class="projectIdentity">
        <span class="eyebrow">SOLODRAMA WORKBENCH</span>
        <div class="titleLine">
          <h1>{{ projectName }}</h1>
          <el-tag effect="plain" round>{{ project?.episodeCount ? `${project.episodeCount} 集` : '项目规格未设置' }}</el-tag>
        </div>
        <div class="projectMeta">
          <span>{{ project?.aspectRatio ?? "9:16" }}</span>
          <span>{{ project?.width ?? 1080 }} × {{ project?.height ?? 1920 }}</span>
          <span>{{ styleName }}</span>
          <span v-if="project?.directorSkill">导演 · {{ project.directorSkill }}</span>
          <span>{{ project?.episodeSeconds ?? 90 }} 秒 / 集</span>
        </div>
      </div>
      <div class="headerActions">
        <el-button :icon="IconAdjustmentsHorizontal" @click="settingsVisible = true">项目规格</el-button>
        <el-button :icon="IconRefresh" :loading="loading" @click="refresh">同步工作区</el-button>
        <el-button type="primary" :icon="IconVector" @click="emit('openCanvas')">进入画布</el-button>
      </div>
    </header>

    <nav class="stageTabs" aria-label="工作台阶段">
      <button v-for="item in stages" :key="item.id" type="button" :class="{ active: activeStage === item.id }" @click="activeStage = item.id">
        <component :is="item.icon" :size="17" />
        <span>{{ item.label }}</span>
        <small>{{ item.count }}</small>
      </button>
    </nav>

    <div v-loading="loading" class="workbenchLayout">
      <aside class="projectRail">
        <section class="railSection">
          <div class="railTitle"><span>项目状态</span><icon-database :size="15" /></div>
          <div class="miniStats">
            <div><b>{{ documentNodes.length }}</b><span>剧本/文本</span></div>
            <div><b>{{ assetNodes.length }}</b><span>视觉资产</span></div>
            <div><b>{{ shotNodes.length }}</b><span>分镜镜头</span></div>
            <div><b>{{ videoNodes.length }}</b><span>成片片段</span></div>
          </div>
        </section>
        <section class="railSection">
          <div class="railTitle"><span>快速创建</span><icon-plus :size="15" /></div>
          <button v-for="action in quickActions" :key="action.type" class="quickAction" type="button" @click="createNode(action.type, action.label)">
            <span class="quickIcon"><component :is="action.icon" :size="17" /></span>
            <span><b>{{ action.label }}</b><small>{{ action.hint }}</small></span>
            <icon-chevron-right :size="15" />
          </button>
        </section>
        <section class="railSection canvasListSection">
          <div class="railTitle"><span>画布</span><icon-vector :size="15" /></div>
          <button v-for="canvas in canvases" :key="canvas.id" class="canvasRow" :class="{ active: canvas.id === canvases[0]?.id }" type="button" @click="focusFirstNode(canvas)">
            <icon-vector :size="16" />
            <span>{{ canvas.name }}</span>
            <small>{{ canvas.data.nodes.length }}</small>
          </button>
          <p v-if="!canvases.length" class="railEmpty">还没有画布节点。</p>
        </section>
      </aside>

      <main class="stageCanvas">
        <template v-if="activeStage === 'overview'">
          <section class="heroCard">
            <div class="heroCopy">
              <span class="eyebrow">CREATIVE PIPELINE</span>
              <h2>把剧本、角色、分镜和成片放在同一条工作线上</h2>
              <p>这里展示的全部内容都来自当前项目画布。工作台修改文本、定位节点或新建素材后，画布同步使用同一份文件。</p>
              <div class="heroActions">
                <el-button type="primary" :icon="IconSparkles" @click="activeStage = 'script'">从剧本开始</el-button>
                <el-button @click="emit('openCanvas')">查看画布</el-button>
              </div>
            </div>
            <div class="heroReel" aria-hidden="true">
              <div class="reelFrame"><span /><span /><span /></div>
              <div class="reelCaption">SCRIPT → ASSET → SHOT → FILM</div>
            </div>
          </section>
          <section class="overviewGrid">
            <article v-for="item in pipelineCards" :key="item.title" class="pipelineCard" @click="activeStage = item.stage">
              <span class="pipelineIndex">{{ item.index }}</span>
              <div class="pipelineIcon"><component :is="item.icon" :size="22" /></div>
              <h3>{{ item.title }}</h3>
              <p>{{ item.description }}</p>
              <span class="pipelineCount">{{ item.count }} 项 <icon-arrow-up-right :size="14" /></span>
            </article>
          </section>
          <section class="recentSection">
            <div class="sectionHeading"><div><span class="eyebrow">RECENT WORK</span><h3>最近内容</h3></div><el-button text @click="activeStage = 'script'">查看全部</el-button></div>
            <div class="recentList">
              <button v-for="item in recentNodes" :key="`${item.canvasPath}:${item.id}`" type="button" @click="focusNode(item.canvasPath, item.id)">
                <span class="nodeType">{{ item.typeLabel }}</span>
                <span class="nodeName">{{ item.label }}</span>
                <span class="nodeCanvas">{{ item.canvasName }}</span>
                <icon-chevron-right :size="15" />
              </button>
              <p v-if="!recentNodes.length" class="emptyState">画布还是空的，可以从左侧快速创建第一个节点。</p>
            </div>
          </section>
        </template>

        <template v-else-if="activeStage === 'script'">
          <div class="sectionHeading"><div><span class="eyebrow">STORY ROOM</span><h2>剧本与文本</h2><p>点击卡片编辑 Markdown 正文，保存后直接更新画布文本节点。</p></div><el-button :icon="IconPlus" @click="createNode('remote-textNode', '剧本')">新增剧本节点</el-button></div>
          <div class="documentGrid">
            <article v-for="doc in documentNodes" :key="`${doc.canvasPath}:${doc.id}`" class="documentCard" @click="editDocument(doc)">
              <header><span>{{ doc.canvasName }}</span><el-tag size="small" effect="plain">{{ doc.typeLabel }}</el-tag></header>
              <h3>{{ doc.label }}</h3>
              <p>{{ doc.preview || "空白文档" }}</p>
              <footer><span>{{ doc.preview.length }} 字预览</span><span>编辑 <icon-edit :size="13" /></span></footer>
            </article>
            <button class="createCard" type="button" @click="createNode('remote-textNode', '剧本')"><icon-plus :size="22" /><span>新建剧本或文本节点</span></button>
          </div>
        </template>

        <template v-else-if="activeStage === 'assets'">
          <div class="sectionHeading"><div><span class="eyebrow">CAST & WORLD</span><h2>角色、场景与道具</h2><p>视觉资产从图片节点输出中读取，并按节点名称归类。</p></div><div class="filterRow"><button v-for="item in assetFilters" :key="item.value" type="button" :class="{ active: assetFilter === item.value }" @click="assetFilter = item.value">{{ item.label }}</button></div></div>
          <div class="assetGrid">
            <article v-for="asset in filteredAssets" :key="`${asset.canvasPath}:${asset.id}`" class="assetCard" @click="focusNode(asset.canvasPath, asset.id)">
              <div class="assetMedia">
                <img v-if="asset.imageUrl" :src="asset.imageUrl" :alt="asset.label" />
                <div v-else class="assetPlaceholder"><component :is="asset.icon" :size="34" /><span>待生成图片</span></div>
                <span class="assetBadge">{{ asset.category }}</span>
              </div>
              <div class="assetInfo"><div><h3>{{ asset.label }}</h3><p>{{ asset.model || asset.typeLabel }}</p></div><icon-arrow-up-right :size="16" /></div>
            </article>
            <button class="createCard assetCreate" type="button" @click="createNode('remote-imageGenerationNode', '角色/场景资产')"><icon-plus :size="22" /><span>新建图片生成节点</span></button>
          </div>
        </template>

        <template v-else-if="activeStage === 'shots'">
          <div class="sectionHeading"><div><span class="eyebrow">SHOT BOARD</span><h2>分镜与镜头</h2><p>镜头卡片对应画布中的视频生成节点，参考图按画布连线关联。</p></div><el-button :icon="IconPlus" @click="createNode('remote-videoGenerationNode', '分镜镜头')">新增分镜镜头</el-button></div>
          <div class="shotList">
            <article v-for="(shot, index) in shotNodes" :key="`${shot.canvasPath}:${shot.id}`" class="shotCard" @click="focusNode(shot.canvasPath, shot.id)">
              <div class="shotNumber">{{ String(index + 1).padStart(2, "0") }}</div>
              <div class="shotVisual">
                <img v-if="shot.imageUrl" :src="shot.imageUrl" :alt="shot.label" />
                <video v-else-if="shot.videoUrl" :src="shot.videoUrl" muted preload="metadata" />
                <div v-else class="shotPlaceholder"><icon-movie :size="30" /><span>等待分镜画面</span></div>
              </div>
              <div class="shotBody"><span class="shotCanvas">{{ shot.canvasName }}</span><h3>{{ shot.label }}</h3><p>{{ shot.prompt || "尚未填写镜头提示词" }}</p><div class="shotMeta"><span>{{ shot.ratio || project?.aspectRatio || "9:16" }}</span><span>{{ shot.model || "未选择模型" }}</span><span>{{ shot.styleName }}</span></div></div>
              <icon-chevron-right class="shotArrow" :size="18" />
            </article>
            <button v-if="!shotNodes.length" class="createCard emptyCreate" type="button" @click="createNode('remote-videoGenerationNode', '分镜镜头')"><icon-plus :size="24" /><span>创建第一个分镜镜头</span></button>
          </div>
        </template>

        <template v-else>
          <div class="sectionHeading"><div><span class="eyebrow">SCREENING ROOM</span><h2>成片与视频片段</h2><p>集中查看已生成的视频节点，并直接回到对应画布继续调整。</p></div><el-button :icon="IconPlus" @click="createNode('remote-videoGenerationNode', '视频片段')">新增视频节点</el-button></div>
          <div class="videoGrid">
            <article v-for="video in videoNodes" :key="`${video.canvasPath}:${video.id}`" class="videoCard" @click="focusNode(video.canvasPath, video.id)">
              <div class="videoMedia">
                <video v-if="video.videoUrl" :src="video.videoUrl" controls preload="metadata" />
                <div v-else class="videoPlaceholder"><icon-player-play :size="34" /><span>等待生成视频</span></div>
              </div>
              <div class="videoInfo"><div><span>{{ video.canvasName }}</span><h3>{{ video.label }}</h3></div><icon-arrow-up-right :size="16" /></div>
            </article>
            <p v-if="!videoNodes.length" class="emptyState">还没有视频节点。你可以先在分镜中创建镜头，或直接新增视频节点。</p>
          </div>
        </template>
      </main>
    </div>

    <el-dialog v-model="editorVisible" :title="editingDocument ? `编辑 · ${editingDocument.label}` : '编辑文本'" width="min(900px, 94vw)" appendToBody>
      <div class="documentEditor">
        <div class="editorMeta"><span>{{ editingDocument?.canvasName }}</span><code>{{ editingDocument?.contentPath }}</code></div>
        <el-input v-model="documentDraft" type="textarea" :autosize="{ minRows: 16, maxRows: 32 }" resize="none" />
      </div>
      <template #footer><el-button @click="editorVisible = false">取消</el-button><el-button type="primary" :loading="savingDocument" @click="saveDocument">保存到画布节点</el-button></template>
    </el-dialog>
    <projectSetupDialog v-model="settingsVisible" :directory="directory" :suggestedName="projectName" :settings="project" @confirm="saveProjectSettings" />
  </section>
</template>
<script setup lang="ts">
import { computed, onMounted, onScopeDispose, ref } from "vue";
import axios from "axios";
import { ElButton, ElDialog, ElInput, ElMessage, ElTag } from "element-plus";
import {
  IconAdjustmentsHorizontal, IconArrowUpRight, IconChevronRight, IconDatabase, IconEdit, IconFileText, IconLayersLinked,
  IconMovie, IconPlus, IconPlayerPlay, IconRefresh, IconSparkles, IconUserSquareRounded, IconVector, IconWorld, IconBox,
} from "@tabler/icons-vue";
import type { Node } from "@vue-flow/core";
import useWorkspaceFiles from "@/lib/workspaceFiles";
import { readCanvasFiles } from "../canvas/canvasFiles";
import { projectSettingsPath, type SoloDramaProjectSettings } from "@solodrama/node-shared/projectSettings";
import { styleByKey } from "@solodrama/node-shared/styleLibrary";
import projectSetupDialog from "@/pages/home/projectSetupDialog.vue";
import { buildProjectSettings, type ProjectSetupValue } from "@/lib/projectDefaults";

const props = defineProps<{
  directory: string;
  focusNode: (canvasPath: string, nodeId: string) => Promise<void>;
  createNode: (type: string, label: string) => Promise<void>;
}>();
const emit = defineEmits<{ openCanvas: [] }>();
type CanvasItem = Awaited<ReturnType<typeof readCanvasFiles>>[number];
type DocumentItem = { canvasPath: string; canvasName: string; id: string; label: string; typeLabel: string; contentPath: string; preview: string };
type MediaItem = { path: string; mimeType: string };
type AssetItem = { canvasPath: string; canvasName: string; id: string; label: string; typeLabel: string; category: string; model: string; imageUrl: string; icon: typeof IconUserSquareRounded };
type ShotItem = { canvasPath: string; canvasName: string; id: string; label: string; prompt: string; model: string; ratio: string; styleName: string; imageUrl: string; videoUrl: string };
type VideoItem = { canvasPath: string; canvasName: string; id: string; label: string; videoUrl: string };

const files = useWorkspaceFiles(props.directory);
const loading = ref(false);
const project = ref<SoloDramaProjectSettings>();
const canvases = ref<CanvasItem[]>([]);
const textPreviews = ref<Record<string, string>>({});
const mediaUrls = ref<Record<string, string>>({});
const activeStage = ref<"overview" | "script" | "assets" | "shots" | "video">("overview");
const assetFilter = ref("all");
const editorVisible = ref(false);
const settingsVisible = ref(false);
const savingSettings = ref(false);
const editingDocument = ref<DocumentItem>();
const documentDraft = ref("");
const savingDocument = ref(false);
let documentSnapshot: Awaited<ReturnType<typeof files.readTextSnapshot>> | undefined;
const mediaReleases = new Map<string, () => void>();

const projectName = computed(() => project.value?.name || props.directory.split(/[\\/]/).filter(Boolean).at(-1) || "SoloDrama 项目");
const styleName = computed(() => styleByKey.get(project.value?.styleKey ?? "")?.nameZh || project.value?.styleKey || "未设置画风");
const documentNodes = computed<DocumentItem[]>(() => canvases.value.flatMap(canvas => canvas.data.nodes
  .filter(node => nodeType(node).toLowerCase().includes("textnode"))
  .map(node => ({
    canvasPath: canvas.id, canvasName: canvas.name, id: node.id, label: nodeLabel(node, "文本节点"),
    typeLabel: "文本", contentPath: textPath(node), preview: textPreviews.value[`${canvas.id}:${node.id}`] ?? "",
  }))));
const assetNodes = computed<AssetItem[]>(() => canvases.value.flatMap(canvas => canvas.data.nodes
  .filter(node => /image(?:generation)?node/i.test(nodeType(node)) || !!outputMedia(node, "image"))
  .map(node => {
    const media = outputMedia(node, "image");
    const label = nodeLabel(node, "视觉资产");
    const category = /场景|地点|环境/.test(label) ? "场景" : /道具|物件/.test(label) ? "道具" : /角色|人物|主角|配角|群演/.test(label) ? "角色" : "视觉";
    return {
      canvasPath: canvas.id, canvasName: canvas.name, id: node.id, label, category,
      typeLabel: "图片", model: stringValue(nodeData(node).model), imageUrl: media ? mediaUrls.value[media.path] ?? "" : "",
      icon: category === "场景" ? IconWorld : category === "道具" ? IconBox : IconUserSquareRounded,
    };
  })));
const filteredAssets = computed(() => assetFilter.value === "all" ? assetNodes.value : assetNodes.value.filter(item => item.category === assetFilter.value));
const shotNodes = computed<ShotItem[]>(() => canvases.value.flatMap(canvas => canvas.data.nodes
  .filter(node => /videogenerationnode/i.test(nodeType(node)))
  .map(node => {
    const image = incomingImage(canvas, node);
    const video = outputMedia(node, "video");
    const data = nodeData(node);
    return {
      canvasPath: canvas.id, canvasName: canvas.name, id: node.id, label: nodeLabel(node, "分镜镜头"),
      prompt: compactText(stringValue(data.prompt), 180), model: compactText(stringValue(data.model), 60),
      ratio: stringValue(data.ratio), styleName: styleByKey.get(stringValue(data.styleKey))?.nameZh || styleName.value,
      imageUrl: image ? mediaUrls.value[image.path] ?? "" : "", videoUrl: video ? mediaUrls.value[video.path] ?? "" : "",
    };
  })));
const videoNodes = computed<VideoItem[]>(() => canvases.value.flatMap(canvas => canvas.data.nodes.flatMap(node => {
  const media = outputMedia(node, "video");
  if (!media) return [];
  return [{ canvasPath: canvas.id, canvasName: canvas.name, id: node.id, label: nodeLabel(node, "视频片段"), videoUrl: mediaUrls.value[media.path] ?? "" }];
})));
const recentNodes = computed(() => canvases.value.flatMap(canvas => canvas.data.nodes.slice(-3).map(node => ({
  canvasPath: canvas.id, canvasName: canvas.name, id: node.id, label: nodeLabel(node, nodeType(node)),
  typeLabel: nodeType(node).replace(/Node$/, "") || "节点",
}))).slice(-8).reverse());
const stages = computed(() => [
  { id: "overview" as const, label: "概览", count: canvases.value.length, icon: IconLayersLinked },
  { id: "script" as const, label: "剧本", count: documentNodes.value.length, icon: IconFileText },
  { id: "assets" as const, label: "设定", count: assetNodes.value.length, icon: IconUserSquareRounded },
  { id: "shots" as const, label: "分镜", count: shotNodes.value.length, icon: IconMovie },
  { id: "video" as const, label: "成片", count: videoNodes.value.length, icon: IconPlayerPlay },
]);
const pipelineCards = computed(() => [
  { index: "01", title: "剧本与文本", description: "整理故事、人物小传、场次和台词，正文与画布文本节点共用。", count: documentNodes.value.length, stage: "script" as const, icon: IconFileText },
  { index: "02", title: "角色与场景", description: "沉淀角色、场景和道具视觉，后续镜头可直接引用。", count: assetNodes.value.length, stage: "assets" as const, icon: IconUserSquareRounded },
  { index: "03", title: "分镜与生成", description: "查看镜头提示词、模型、画幅和参考图，并回到画布继续生成。", count: shotNodes.value.length, stage: "shots" as const, icon: IconMovie },
  { index: "04", title: "成片管理", description: "汇总视频输出，为后续剪映草稿、TTS 和流水线出片做准备。", count: videoNodes.value.length, stage: "video" as const, icon: IconPlayerPlay },
]);
const quickActions = [
  { type: "remote-textNode", label: "新建剧本", hint: "Markdown 文本节点", icon: IconFileText },
  { type: "remote-imageGenerationNode", label: "新建设定图", hint: "角色、场景或道具", icon: IconUserSquareRounded },
  { type: "remote-videoGenerationNode", label: "新建分镜镜头", hint: "视频生成节点", icon: IconMovie },
  { type: "remote-audioGenerationNode", label: "新建音频", hint: "配音或音效节点", icon: IconPlayerPlay },
];
const assetFilters = [{ value: "all", label: "全部" }, { value: "角色", label: "角色" }, { value: "场景", label: "场景" }, { value: "道具", label: "道具" }, { value: "视觉", label: "其他" }];

onMounted(() => { void refresh(); });
onScopeDispose(releaseMedia);

async function refresh() {
  loading.value = true;
  try {
    project.value = await files.readJson<SoloDramaProjectSettings>(projectSettingsPath).catch(() => undefined);
    canvases.value = await readCanvasFiles(files);
    const previews: Record<string, string> = {};
    await Promise.all(documentNodesFrom(canvases.value).map(async doc => {
      try { previews[`${doc.canvasPath}:${doc.id}`] = compactText(await files.readText(doc.contentPath, 8000), 420); }
      catch { previews[`${doc.canvasPath}:${doc.id}`] = "正文文件暂不可读"; }
    }));
    textPreviews.value = previews;
    await loadMediaUrls();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "工作台读取失败");
  } finally {
    loading.value = false;
  }
}

function documentNodesFrom(items: CanvasItem[]) {
  return items.flatMap(canvas => canvas.data.nodes.filter(node => nodeType(node).toLowerCase().includes("textnode")).map(node => ({ canvasPath: canvas.id, id: node.id, contentPath: textPath(node) })));
}

async function loadMediaUrls() {
  releaseMedia();
  const candidates = new Map<string, string>();
  for (const canvas of canvases.value) for (const node of canvas.data.nodes) for (const key of ["image", "video", "audio"]) {
    const media = outputMedia(node, key);
    if (media) candidates.set(media.path, media.mimeType);
  }
  await Promise.all([...candidates].map(async ([path, mimeType]) => {
    const shared = files.acquireUrl(path, mimeType);
    mediaReleases.set(path, shared.release);
    try { mediaUrls.value[path] = await shared.url; }
    catch { delete mediaUrls.value[path]; shared.release(); mediaReleases.delete(path); }
  }));
}

function releaseMedia() {
  for (const release of mediaReleases.values()) release();
  mediaReleases.clear();
  mediaUrls.value = {};
}

async function editDocument(doc: DocumentItem) {
  try {
    documentSnapshot = await files.readTextSnapshot(doc.contentPath);
    editingDocument.value = doc;
    documentDraft.value = documentSnapshot.text;
    editorVisible.value = true;
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "读取文档失败");
  }
}

async function saveDocument() {
  if (!editingDocument.value || !documentSnapshot || savingDocument.value) return;
  savingDocument.value = true;
  try {
    documentSnapshot.revision = await files.writeTextSnapshot(editingDocument.value.contentPath, documentDraft.value, documentSnapshot);
    documentSnapshot.text = documentDraft.value;
    editorVisible.value = false;
    ElMessage.success("已保存到画布文本节点");
    await refresh();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "保存文档失败");
  } finally {
    savingDocument.value = false;
  }
}

async function saveProjectSettings(value: ProjectSetupValue) {
  if (savingSettings.value) return;
  savingSettings.value = true;
  try {
    await files.mkdir(".solodrama").catch(error => {
      const code = axios.isAxiosError<{ data?: { code?: string } }>(error) ? error.response?.data?.data?.code : undefined;
      if (code !== "EEXIST") throw error;
    });
    project.value = buildProjectSettings(value, project.value);
    await files.writeJson(projectSettingsPath, project.value);
    ElMessage.success("项目规格已保存，画布和创作插件会使用新配置");
    await refresh();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "保存项目规格失败");
  } finally {
    savingSettings.value = false;
  }
}

async function focusNode(canvasPath: string, nodeId: string) {
  try { await props.focusNode(canvasPath, nodeId); }
  catch (error) { ElMessage.error(error instanceof Error ? error.message : "无法定位画布节点"); }
}

async function focusFirstNode(canvas: CanvasItem) {
  const node = canvas.data.nodes[0];
  if (node) await focusNode(canvas.id, node.id);
}

async function createNode(type: string, label: string) {
  try { await props.createNode(type, label); }
  catch (error) { ElMessage.error(error instanceof Error ? error.message : "无法创建节点"); }
}

function nodeType(node: Node) { return String(node.type ?? "").replace(/^remote-/, ""); }
function nodeData(node: Node) { return (node.data ?? {}) as Record<string, unknown>; }
function nodeLabel(node: Node, fallback: string) { return stringValue(nodeData(node).label) || fallback; }
function stringValue(value: unknown) { return typeof value === "string" ? value : ""; }
function compactText(value: string, length: number) { return value.replace(/\s+/g, " ").trim().slice(0, length); }
function textPath(node: Node) { return stringValue(nodeData(node).textPath) || `assets/${node.id}/content.md`; }

function outputMedia(node: Node, key: string): MediaItem | undefined {
  const outputs = nodeData(node).outputs;
  if (!outputs || typeof outputs !== "object") return;
  const output = (outputs as Record<string, unknown>)[key];
  if (!output || typeof output !== "object") return;
  const value = (output as Record<string, unknown>).value;
  if (!value || typeof value !== "object") return;
  const path = stringValue((value as Record<string, unknown>).url);
  if (!path) return;
  return { path, mimeType: stringValue((value as Record<string, unknown>).mimeType) || `${key}/octet-stream` };
}

function incomingImage(canvas: CanvasItem, node: Node) {
  const sourceIds = canvas.data.edges.filter(edge => edge.target === node.id).map(edge => edge.source);
  for (const sourceId of sourceIds) {
    const source = canvas.data.nodes.find(item => item.id === sourceId);
    const media = source ? outputMedia(source, "image") : undefined;
    if (media) return media;
  }
}
</script>
<style scoped lang="scss">
.workbenchPanel {
  position: relative;
  height: 100%;
  overflow: auto;
  color: #f2f2ee;
  background:
    radial-gradient(circle at 15% 5%, rgb(255 255 255 / 8%), transparent 30%),
    radial-gradient(circle at 90% 0%, rgb(176 136 72 / 10%), transparent 28%),
    linear-gradient(180deg, #101116 0%, #090a0e 100%);
}
.filmGrain { position: fixed; inset: 0; pointer-events: none; opacity: .18; background-image: repeating-linear-gradient(90deg, transparent 0 7px, rgb(255 255 255 / 2%) 8px), repeating-linear-gradient(0deg, transparent 0 7px, rgb(0 0 0 / 10%) 8px); }
.workbenchHeader, .stageTabs, .workbenchLayout { position: relative; z-index: 1; }
.workbenchHeader { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; padding: 34px 38px 24px 96px; border-bottom: 1px solid rgb(255 255 255 / 8%); }
.eyebrow { color: #c9a66b; font-size: 10px; font-weight: 700; letter-spacing: .16em; }
.projectIdentity { min-width: 0; }
.titleLine { display: flex; align-items: center; gap: 12px; margin-top: 7px; h1 { margin: 0; overflow: hidden; font-size: clamp(24px, 3vw, 38px); font-weight: 600; letter-spacing: -.03em; text-overflow: ellipsis; white-space: nowrap; } }
.projectMeta { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 12px; span { padding: 4px 9px; border: 1px solid rgb(255 255 255 / 10%); border-radius: 999px; color: rgb(255 255 255 / 58%); font-size: 11px; } }
.headerActions { display: flex; gap: 9px; flex-shrink: 0; }
.stageTabs { display: flex; gap: 6px; padding: 14px 38px; overflow-x: auto; border-bottom: 1px solid rgb(255 255 255 / 7%); background: rgb(7 8 11 / 62%); backdrop-filter: blur(18px); }
.stageTabs button { display: inline-flex; align-items: center; gap: 8px; min-height: 38px; padding: 0 15px; border: 1px solid transparent; border-radius: 10px; color: rgb(255 255 255 / 55%); background: transparent; font: inherit; font-size: 13px; cursor: pointer; white-space: nowrap; }
.stageTabs button:hover { color: #fff; background: rgb(255 255 255 / 5%); }
.stageTabs button.active { border-color: rgb(255 255 255 / 12%); color: #fff; background: rgb(255 255 255 / 9%); }
.stageTabs small { min-width: 20px; padding: 1px 6px; border-radius: 6px; color: #d5bc91; background: rgb(201 166 107 / 12%); font-size: 10px; }
.workbenchLayout { display: grid; grid-template-columns: 238px minmax(0, 1fr); gap: 26px; max-width: 1560px; margin: 0 auto; padding: 26px 38px 54px; }
.projectRail { display: flex; flex-direction: column; gap: 14px; }
.railSection { padding: 15px; border: 1px solid rgb(255 255 255 / 9%); border-radius: 16px; background: rgb(255 255 255 / 4%); }
.railTitle { display: flex; align-items: center; justify-content: space-between; margin-bottom: 13px; color: rgb(255 255 255 / 55%); font-size: 11px; font-weight: 600; letter-spacing: .06em; }
.miniStats { display: grid; grid-template-columns: 1fr 1fr; gap: 1px; overflow: hidden; border-radius: 10px; background: rgb(255 255 255 / 7%); }
.miniStats div { display: flex; flex-direction: column; gap: 3px; padding: 12px; background: #111217; b { font-size: 21px; font-weight: 500; } span { color: rgb(255 255 255 / 42%); font-size: 10px; } }
.quickAction { display: grid; grid-template-columns: 32px minmax(0, 1fr) auto; align-items: center; gap: 10px; width: 100%; padding: 9px 0; border: 0; color: inherit; background: transparent; text-align: left; cursor: pointer; & + & { border-top: 1px solid rgb(255 255 255 / 6%); } &:hover { color: #e0c28e; } }
.quickIcon { display: grid; place-items: center; width: 32px; height: 32px; border-radius: 9px; color: #d6b77f; background: rgb(201 166 107 / 10%); }
.quickAction > span:nth-child(2) { display: grid; gap: 2px; min-width: 0; } .quickAction b { font-size: 12px; font-weight: 500; } .quickAction small { color: rgb(255 255 255 / 38%); font-size: 10px; }
.canvasRow { display: grid; grid-template-columns: 16px minmax(0, 1fr) auto; align-items: center; gap: 8px; width: 100%; padding: 8px 4px; border: 0; color: rgb(255 255 255 / 58%); background: transparent; text-align: left; cursor: pointer; } .canvasRow span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } .canvasRow small { color: rgb(255 255 255 / 32%); font-size: 10px; } .canvasRow:hover, .canvasRow.active { color: #fff; }
.railEmpty { margin: 6px 0 0; color: rgb(255 255 255 / 35%); font-size: 11px; line-height: 1.7; }
.stageCanvas { min-width: 0; }
.heroCard { position: relative; display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(260px, .65fr); gap: 28px; overflow: hidden; min-height: 280px; padding: 38px; border: 1px solid rgb(255 255 255 / 10%); border-radius: 22px; background: linear-gradient(125deg, rgb(255 255 255 / 8%), rgb(255 255 255 / 2%) 55%, rgb(201 166 107 / 9%)); }
.heroCard::after { position: absolute; inset: 0; background: radial-gradient(circle at 75% 40%, rgb(255 255 255 / 11%), transparent 24%); content: ""; pointer-events: none; }
.heroCopy { position: relative; z-index: 1; align-self: center; h2 { max-width: 720px; margin: 12px 0 12px; font-size: clamp(27px, 3.5vw, 48px); font-weight: 520; line-height: 1.12; letter-spacing: -.045em; } p { max-width: 680px; margin: 0; color: rgb(255 255 255 / 52%); font-size: 13px; line-height: 1.8; } }
.heroActions { display: flex; gap: 9px; margin-top: 24px; }
.heroReel { position: relative; display: grid; place-items: center; min-height: 220px; border-left: 1px solid rgb(255 255 255 / 9%); }
.reelFrame { position: relative; width: min(250px, 100%); aspect-ratio: 1; border: 1px solid rgb(255 255 255 / 15%); border-radius: 50%; animation: reelSpin 32s linear infinite; span { position: absolute; top: 50%; left: 50%; width: 30%; aspect-ratio: 1; border: 1px solid rgb(255 255 255 / 18%); border-radius: 50%; transform: translate(-50%, -50%) translateY(-37%); } span:nth-child(2) { transform: translate(-50%, -50%) rotate(120deg) translateY(-37%); } span:nth-child(3) { transform: translate(-50%, -50%) rotate(240deg) translateY(-37%); } }
.reelCaption { position: absolute; bottom: 10px; color: rgb(255 255 255 / 35%); font-size: 9px; letter-spacing: .18em; }
.overviewGrid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-top: 16px; }
.pipelineCard { position: relative; min-height: 195px; padding: 18px; border: 1px solid rgb(255 255 255 / 9%); border-radius: 16px; background: rgb(255 255 255 / 4%); cursor: pointer; transition: transform .18s ease, border-color .18s ease, background .18s ease; &:hover { transform: translateY(-3px); border-color: rgb(201 166 107 / 32%); background: rgb(255 255 255 / 6%); } h3 { margin: 30px 0 7px; font-size: 14px; font-weight: 520; } p { margin: 0; color: rgb(255 255 255 / 42%); font-size: 11px; line-height: 1.7; } }
.pipelineIndex { position: absolute; top: 17px; right: 17px; color: rgb(255 255 255 / 25%); font-size: 11px; }
.pipelineIcon { display: grid; place-items: center; width: 38px; height: 38px; border-radius: 11px; color: #d6b77f; background: rgb(201 166 107 / 9%); }
.pipelineCount { display: inline-flex; align-items: center; gap: 5px; margin-top: 16px; color: #d6b77f; font-size: 11px; }
.recentSection { margin-top: 24px; }
.sectionHeading { display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; margin: 0 0 17px; h2, h3 { margin: 5px 0 0; font-weight: 520; letter-spacing: -.02em; } h2 { font-size: 26px; } h3 { font-size: 19px; } p { margin: 7px 0 0; color: rgb(255 255 255 / 43%); font-size: 12px; line-height: 1.6; } }
.recentList { overflow: hidden; border: 1px solid rgb(255 255 255 / 9%); border-radius: 15px; background: rgb(255 255 255 / 3%); }
.recentList button { display: grid; grid-template-columns: 72px minmax(0, 1fr) minmax(100px, auto) 16px; align-items: center; gap: 12px; width: 100%; min-height: 54px; padding: 10px 15px; border: 0; color: inherit; background: transparent; text-align: left; cursor: pointer; & + button { border-top: 1px solid rgb(255 255 255 / 6%); } &:hover { background: rgb(255 255 255 / 4%); } }
.nodeType { color: #d6b77f; font-size: 10px; text-transform: uppercase; } .nodeName { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; } .nodeCanvas { overflow: hidden; color: rgb(255 255 255 / 34%); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.documentGrid, .assetGrid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 13px; }
.documentCard { min-height: 210px; padding: 18px; border: 1px solid rgb(255 255 255 / 9%); border-radius: 16px; background: rgb(255 255 255 / 4%); cursor: pointer; &:hover { border-color: rgb(201 166 107 / 30%); background: rgb(255 255 255 / 6%); } header, footer { display: flex; align-items: center; justify-content: space-between; gap: 10px; color: rgb(255 255 255 / 38%); font-size: 10px; } h3 { margin: 22px 0 9px; font-size: 17px; font-weight: 520; } p { display: -webkit-box; overflow: hidden; margin: 0; color: rgb(255 255 255 / 47%); font-size: 12px; line-height: 1.75; -webkit-box-orient: vertical; -webkit-line-clamp: 4; } footer { margin-top: 24px; span:last-child { display: inline-flex; align-items: center; gap: 5px; color: #d6b77f; } } }
.createCard { display: grid; place-items: center; align-content: center; gap: 10px; min-height: 210px; border: 1px dashed rgb(255 255 255 / 16%); border-radius: 16px; color: rgb(255 255 255 / 42%); background: transparent; font: inherit; font-size: 12px; cursor: pointer; &:hover { border-color: rgb(201 166 107 / 40%); color: #d6b77f; background: rgb(201 166 107 / 4%); } }.assetGrid { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.assetCard { overflow: hidden; border: 1px solid rgb(255 255 255 / 9%); border-radius: 15px; background: rgb(255 255 255 / 4%); cursor: pointer; &:hover { border-color: rgb(201 166 107 / 30%); } }
.assetMedia { position: relative; display: grid; place-items: center; aspect-ratio: 4 / 3; overflow: hidden; background: linear-gradient(135deg, #1a1b21, #101116); img { width: 100%; height: 100%; object-fit: cover; } }
.assetPlaceholder { display: grid; place-items: center; gap: 8px; color: rgb(255 255 255 / 25%); font-size: 10px; }
.assetBadge { position: absolute; top: 9px; left: 9px; padding: 3px 7px; border: 1px solid rgb(255 255 255 / 12%); border-radius: 6px; color: rgb(255 255 255 / 66%); background: rgb(0 0 0 / 42%); font-size: 9px; backdrop-filter: blur(8px); }
.assetInfo, .videoInfo { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 13px; h3 { margin: 0; overflow: hidden; font-size: 13px; font-weight: 520; text-overflow: ellipsis; white-space: nowrap; } p { margin: 4px 0 0; overflow: hidden; color: rgb(255 255 255 / 36%); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; } }
.assetCreate { min-height: 230px; }
.filterRow { display: flex; flex-wrap: wrap; gap: 5px; button { padding: 6px 10px; border: 1px solid rgb(255 255 255 / 10%); border-radius: 8px; color: rgb(255 255 255 / 45%); background: transparent; font: inherit; font-size: 11px; cursor: pointer; &.active { color: #111; border-color: #e2d6bf; background: #e2d6bf; } } }
.shotList { display: flex; flex-direction: column; gap: 10px; }
.shotCard { display: grid; grid-template-columns: 42px minmax(180px, 260px) minmax(0, 1fr) 18px; align-items: center; gap: 18px; padding: 13px; border: 1px solid rgb(255 255 255 / 9%); border-radius: 16px; background: rgb(255 255 255 / 4%); cursor: pointer; &:hover { border-color: rgb(201 166 107 / 30%); background: rgb(255 255 255 / 6%); } }
.shotNumber { align-self: start; padding-top: 6px; color: rgb(255 255 255 / 30%); font-size: 12px; }
.shotVisual { display: grid; place-items: center; aspect-ratio: 16 / 9; overflow: hidden; border-radius: 11px; background: #111217; img, video { width: 100%; height: 100%; object-fit: cover; } }
.shotPlaceholder, .videoPlaceholder { display: grid; place-items: center; gap: 7px; color: rgb(255 255 255 / 24%); font-size: 10px; }
.shotBody { min-width: 0; .shotCanvas { color: #d6b77f; font-size: 9px; letter-spacing: .08em; } h3 { margin: 5px 0 7px; font-size: 15px; font-weight: 520; } p { display: -webkit-box; overflow: hidden; margin: 0; color: rgb(255 255 255 / 43%); font-size: 11px; line-height: 1.7; -webkit-box-orient: vertical; -webkit-line-clamp: 2; } }
.shotMeta { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; span { padding: 3px 7px; border-radius: 5px; color: rgb(255 255 255 / 45%); background: rgb(255 255 255 / 6%); font-size: 9px; } }
.shotArrow { color: rgb(255 255 255 / 25%); }
.emptyCreate { width: 100%; min-height: 180px; }
.videoGrid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
.videoCard { overflow: hidden; border: 1px solid rgb(255 255 255 / 9%); border-radius: 16px; background: rgb(255 255 255 / 4%); cursor: pointer; &:hover { border-color: rgb(201 166 107 / 30%); } }
.videoMedia { display: grid; place-items: center; aspect-ratio: 9 / 16; max-height: 430px; overflow: hidden; background: #0e0f13; video { width: 100%; height: 100%; object-fit: contain; } }
.videoInfo span { color: #d6b77f; font-size: 9px; }
.emptyState { grid-column: 1 / -1; margin: 0; padding: 44px; border: 1px dashed rgb(255 255 255 / 12%); border-radius: 15px; color: rgb(255 255 255 / 38%); font-size: 12px; text-align: center; }
.documentEditor { display: flex; flex-direction: column; gap: 12px; }
.editorMeta { display: flex; align-items: center; justify-content: space-between; gap: 12px; color: var(--el-text-color-secondary); font-size: 11px; code { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } }
@keyframes reelSpin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .reelFrame { animation: none; } }
@media (max-width: 1100px) {
  .workbenchLayout { grid-template-columns: 1fr; }
  .projectRail { display: grid; grid-template-columns: 1.1fr 1fr 1fr; }
  .overviewGrid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .assetGrid, .videoGrid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 760px) {
  .workbenchHeader { align-items: flex-start; flex-direction: column; padding: 72px 18px 18px; }
  .stageTabs { padding-inline: 18px; }
  .workbenchLayout { padding: 18px; }
  .projectRail { grid-template-columns: 1fr; }
  .heroCard { grid-template-columns: 1fr; padding: 26px; }
  .heroReel { display: none; }
  .overviewGrid, .documentGrid, .assetGrid, .videoGrid { grid-template-columns: 1fr 1fr; }
  .shotCard { grid-template-columns: 32px minmax(120px, 190px) minmax(0, 1fr); }
  .shotArrow { display: none; }
}
@media (max-width: 520px) { .overviewGrid, .documentGrid, .assetGrid, .videoGrid { grid-template-columns: 1fr; } .shotCard { grid-template-columns: 28px minmax(0, 1fr); } .shotVisual { grid-column: 2; } .shotBody { grid-column: 2; } }
</style>
