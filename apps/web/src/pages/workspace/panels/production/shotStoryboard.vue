<template>
  <section class="shotStudio">
    <header class="studioHeader">
      <div><p class="eyebrow">SHOT {{ shot.number }}</p><h2>{{ shot.title || scene.title || '未命名镜头' }}</h2><p>{{ shot.duration }} 秒 · {{ shot.shotSize }} · {{ shot.cameraMovement }}</p></div>
      <div class="headerActions"><el-button size="small" @click="emit('move', -1)">上移</el-button><el-button size="small" @click="emit('move', 1)">下移</el-button><el-button size="small" @click="emit('split')">拆分</el-button><el-button size="small" @click="emit('merge')">合并下一镜</el-button><el-switch :modelValue="shot.confirmed" activeText="镜头已确认" @change="emit('confirm', Boolean($event))" /></div>
    </header>

    <div class="studioGrid">
      <aside class="referenceColumn">
        <div class="columnTitle"><h3>参考角色</h3><span>{{ characterRefs.length }}</span></div>
        <article v-for="character in characterRefs" :key="character.id" class="referenceCard">
          <div class="referenceImage"><img v-if="character.image" :src="character.image" :alt="character.name" /><icon-user v-else :size="22" /></div>
          <div><strong>{{ character.name }}</strong><small>{{ character.voice || '未绑定音色' }}</small><small>{{ compact(character.visual, 56) }}</small></div>
        </article>
        <div class="columnTitle"><h3>参考场景</h3><span>{{ locationRef ? 1 : 0 }}</span></div>
        <article v-if="locationRef" class="referenceCard"><div class="referenceImage"><img v-if="locationRef.image" :src="locationRef.image" :alt="locationRef.name" /><icon-building v-else :size="22" /></div><div><strong>{{ locationRef.name }}</strong><small>{{ compact(locationRef.description, 70) }}</small></div></article>
        <div class="columnTitle"><h3>参考道具</h3><span>{{ propRefs.length }}</span></div>
        <article v-for="item in propRefs" :key="item.id" class="referenceCard"><div class="referenceImage"><img v-if="item.image" :src="item.image" :alt="item.name" /><icon-box v-else :size="22" /></div><div><strong>{{ item.name }}</strong><small>{{ compact(item.description, 70) }}</small></div></article>
      </aside>

      <main class="promptColumn">
        <div class="promptHeader"><h3>镜头与提示词</h3><el-tag effect="plain">引用自动关联</el-tag></div>
        <el-form labelPosition="top">
          <el-form-item label="画面描述"><el-input v-model="shot.description" type="textarea" :rows="4" @input="emit('dirty')" /></el-form-item>
          <div class="inlineFields"><el-form-item label="人物动作"><el-input v-model="shot.action" type="textarea" :rows="3" @input="emit('dirty')" /></el-form-item><el-form-item label="站位关系"><el-input v-model="shot.positions" type="textarea" :rows="3" @input="emit('dirty')" /></el-form-item></div>
          <div class="inlineFields"><el-form-item label="表情"><el-input v-model="shot.expressions" type="textarea" :rows="3" @input="emit('dirty')" /></el-form-item><el-form-item label="对白"><el-input v-model="shot.dialogue" type="textarea" :rows="3" @input="emit('dirty')" /></el-form-item></div>
          <div class="promptBlock">
            <div class="promptTitle">
              <div><strong>视频提示词</strong><small>通用与 H3 共用此输入框，生成视频时优先使用当前内容</small></div>
              <div class="promptActions">
                <el-button size="small" :loading="optimizing === 'general'" @click="optimize('general')">通用提示词优化</el-button>
                <el-button size="small" type="primary" plain :loading="optimizing === 'h3'" @click="optimize('h3')">H3 提示词优化</el-button>
              </div>
            </div>
            <el-input v-model="commonPrompt" type="textarea" :rows="7" maxlength="100000" showWordLimit @input="emit('dirty')" />
          </div>
          <el-form-item label="提示词优化模型"><el-select v-model="promptModelKey" filterable placeholder="选择语言模型"><el-option v-for="model in languageModels" :key="modelKey(model)" :label="`${model.providerLabel} / ${model.label}`" :value="modelKey(model)" /></el-select></el-form-item>
        </el-form>
        <div class="generationBar"><el-select v-model="videoModelKey" filterable placeholder="视频模型" style="min-width: 240px"><el-option v-for="model in videoModels" :key="modelKey(model)" :label="`${model.providerLabel} / ${model.label}`" :value="modelKey(model)" /></el-select><el-input v-model="workflowId" placeholder="Workflow ID" /><el-input v-model="instanceId" placeholder="实例 ID" /><label class="continuationToggle"><el-switch v-model="continueFromPreviousShot" @change="updateContinuation" /><span>尾帧续画</span></label><el-button type="primary" :loading="generating" @click="generateVideo">生成视频</el-button></div>
      </main>

      <aside class="artifactColumn">
        <div class="columnTitle"><h3>生成辅助图</h3><el-select v-model="imageModelKey" filterable size="small" placeholder="图片模型"><el-option v-for="model in imageModels" :key="modelKey(model)" :label="model.label" :value="modelKey(model)" /></el-select></div>
        <article class="artifactCard"><div class="artifactHead"><div><strong>故事板</strong><small>叙事顺序与镜头关系</small></div><el-switch v-model="options.storyboardEnabled" /></div><div class="artifactPreview"><img v-if="artifactUrl('storyboard')" :src="artifactUrl('storyboard')" alt="故事板" /><icon-layout-grid v-else :size="26" /></div><div class="artifactActions"><el-checkbox v-model="options.useStoryboardReference">作为生成参考</el-checkbox><el-button size="small" :disabled="!options.storyboardEnabled" :loading="artifactBusy('storyboard')" @click="generateArtifact('storyboard')">生成</el-button></div></article>
        <article class="artifactCard"><div class="artifactHead"><div><strong>分镜图</strong><small>单帧画面与构图</small></div><el-switch v-model="options.shotImageEnabled" /></div><div class="artifactPreview"><img v-if="artifactUrl('shotImage')" :src="artifactUrl('shotImage')" alt="分镜图" /><icon-photo :size="26" /></div><div class="artifactActions"><el-checkbox v-model="options.useShotImageReference">作为生成参考</el-checkbox><el-button size="small" :disabled="!options.shotImageEnabled" :loading="artifactBusy('shotImage')" @click="generateArtifact('shotImage')">生成</el-button></div></article>
        <article class="artifactCard"><div class="artifactHead"><div><strong>站位图</strong><small>俯视平面与人物位置</small></div><el-switch v-model="options.blockingEnabled" /></div><div class="artifactPreview"><img v-if="artifactUrl('blocking')" :src="artifactUrl('blocking')" alt="站位图" /><icon-map :size="26" /></div><div class="artifactActions"><el-checkbox v-model="options.useBlockingReference">作为生成参考</el-checkbox><el-button size="small" :disabled="!options.blockingEnabled" :loading="artifactBusy('blocking')" @click="generateArtifact('blocking')">生成</el-button></div></article>
      </aside>
    </div>

    <div class="takeStrip"><div class="columnTitle"><h3>Take 版本</h3><el-button size="small" @click="emit('sync')">同步任务</el-button></div><div class="takeList"><article v-for="take in shot.takes" :key="take.id" class="takeCard" :class="{ selected: take.id === shot.selectedTakeId }"><div><strong>Take {{ take.number }}</strong><small>{{ take.providerId }} / {{ take.modelId }}</small></div><el-tag size="small" :type="take.status === 'completed' || take.status === 'confirmed' ? 'success' : take.status === 'failed' ? 'danger' : 'warning'">{{ take.status }}</el-tag><small>{{ take.outputAssetId ? assetName(take.outputAssetId) : take.error || '等待任务' }}</small><el-button v-if="take.outputAssetId" size="small" :disabled="take.id === shot.selectedTakeId" @click="emit('selectTake', take.id)">设为正式</el-button><el-button v-if="take.status === 'generating' && take.taskId" size="small" type="danger" @click="emit('cancelTask', take.taskId)">取消</el-button></article><el-empty v-if="!shot.takes.length" description="尚未生成 Take" :imageSize="54" /></div></div>
  </section>
</template>
<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import type { ProductionCharacter, ProductionDocument, ProductionEpisode, ProductionLocation, ProductionProp, ProductionScene, ProductionShot } from "@solodrama/production";
import { IconBox, IconBuilding, IconLayoutGrid, IconMap, IconPhoto, IconUser } from "@tabler/icons-vue";
import http from "@/lib/http";
import { useProductionAssetUrls } from "./useProductionAssetUrls";

type Model = { providerId: string; providerLabel?: string; modelId: string; label: string; type?: "image" | "video" | "audio" };
const props = defineProps<{
  directory: string; document: ProductionDocument; shot: ProductionShot; scene: ProductionScene; episode: ProductionEpisode;
  languageModels: Model[]; mediaModels: (Model & { type: "image" | "video" | "audio" })[]; generating: boolean;
}>();
const emit = defineEmits<{
  dirty: []; confirm: [confirmed: boolean]; move: [direction: -1 | 1]; split: []; merge: []; sync: [];
  selectTake: [takeId: string]; cancelTask: [taskId: string];
  generateShot: [payload: Record<string, unknown>]; generateArtifact: [payload: Record<string, unknown>];
}>();
const defaults = () => ({ storyboardEnabled: true, shotImageEnabled: false, blockingEnabled: false, useStoryboardReference: true, useShotImageReference: true, useBlockingReference: true, continueFromPreviousShot: false });
if (!props.shot.generationOptions) props.shot.generationOptions = defaults();
const options = computed(() => props.shot.generationOptions!);
const { assetUrls } = useProductionAssetUrls(() => props.directory, () => props.document.assets);
const promptModelKey = ref("");
const videoModelKey = ref("");
const imageModelKey = ref("");
const workflowId = ref("");
const instanceId = ref("");
const optimizing = ref<"general" | "h3" | "">("");
const imageModels = computed(() => props.mediaModels.filter(model => model.type === "image"));
const videoModels = computed(() => props.mediaModels.filter(model => model.type === "video"));
watch([() => props.languageModels, () => props.mediaModels], () => {
  promptModelKey.value ||= props.languageModels[0] ? modelKey(props.languageModels[0]) : "";
  videoModelKey.value ||= videoModels.value[0] ? modelKey(videoModels.value[0]) : "";
  imageModelKey.value ||= imageModels.value[0] ? modelKey(imageModels.value[0]) : "";
}, { immediate: true });
watch(() => props.shot.id, () => { if (!props.shot.generationOptions) props.shot.generationOptions = defaults(); });
const characterRefs = computed(() => props.shot.characterIds.flatMap(id => props.document.characters.filter(item => item.id === id)).map(item => characterReference(item)));
const locationRef = computed(() => {
  const location = props.scene.locationId ? props.document.locations.find(item => item.id === props.scene.locationId) : undefined;
  return location ? locationReference(location) : undefined;
});
const propRefs = computed(() => props.shot.propIds.flatMap(id => props.document.props.filter(item => item.id === id)).map(item => propReference(item)));
const commonPrompt = computed({
  get: () => props.shot.h3VideoPrompt || props.shot.videoPrompt || "",
  set: (value: string) => {
    props.shot.videoPrompt = value;
    props.shot.h3VideoPrompt = value;
  },
});
const continueFromPreviousShot = computed({
  get: () => options.value.continueFromPreviousShot,
  set: (value: boolean) => { options.value.continueFromPreviousShot = value; },
});
function modelKey(model: Model) { return JSON.stringify([model.providerId, model.modelId]); }
function pickModel(models: Model[], key: string) { try { const value = JSON.parse(key); return models.find(model => model.providerId === value[0] && model.modelId === value[1]); } catch { return undefined; } }
function referenceImage(ids: string[]) { return ids.map(id => assetUrls.value[id]).find(Boolean) ?? ""; }
function characterReference(item: ProductionCharacter) { return { id: item.id, name: item.name, voice: [item.voice.providerId, item.voice.voiceId].filter(Boolean).join(" · "), visual: item.visualDescription || [item.appearance, item.visualProfile.face, item.visualProfile.hair].filter(Boolean).join("，"), image: referenceImage(item.referenceImages.map(reference => reference.assetId)) }; }
function locationReference(item: ProductionLocation) { return { id: item.id, name: item.name, description: [item.description, item.lighting, item.colorPalette].filter(Boolean).join(" · "), image: referenceImage(item.referenceImages.map(reference => reference.assetId)) }; }
function propReference(item: ProductionProp) { return { id: item.id, name: item.name, description: item.description, image: referenceImage(item.referenceImages.map(reference => reference.assetId)) }; }
function compact(value: string, max: number) { return value.length > max ? `${value.slice(0, max)}…` : value; }
function assetName(assetId: string) { const asset = props.document.assets.find(item => item.id === assetId); return asset?.name || asset?.path || assetId.slice(0, 8); }
function artifactAsset(targetType: "storyboard" | "shotImage" | "blocking") {
  const id = targetType === "storyboard" ? props.shot.storyboardAssetId : targetType === "shotImage" ? props.shot.shotImageAssetId : props.shot.blockingAssetId;
  return id ? props.document.assets.find(item => item.id === id) : undefined;
}
function artifactUrl(targetType: "storyboard" | "shotImage" | "blocking") { const asset = artifactAsset(targetType); return asset ? assetUrls.value[asset.id] : undefined; }
function artifactBusy(targetType: "storyboard" | "shotImage" | "blocking") { return props.document.generationJobs.some(job => job.kind === targetType && job.targetId === props.shot.id && job.status === "generating"); }
function updateContinuation() { options.value.continueFromPreviousShot = continueFromPreviousShot.value; emit("dirty"); }
function artifactReferences() {
  return [options.value.useStoryboardReference ? props.shot.storyboardAssetId : undefined, options.value.useShotImageReference ? props.shot.shotImageAssetId : undefined, options.value.useBlockingReference ? props.shot.blockingAssetId : undefined].filter((id): id is string => !!id);
}
function generateVideo() {
  const model = pickModel(videoModels.value, videoModelKey.value);
  if (!model) return ElMessage.warning("请选择视频模型");
  emit("generateShot", { targetType: "shot", targetId: props.shot.id, mediaType: "video", providerId: model.providerId, modelId: model.modelId, duration: props.shot.duration, workflowId: workflowId.value || undefined, instanceId: instanceId.value || undefined, prompt: commonPrompt.value || undefined, referenceAssetIds: artifactReferences(), continueFromPreviousShot: options.value.continueFromPreviousShot });
}
function generateArtifact(targetType: "storyboard" | "shotImage" | "blocking") {
  const model = pickModel(imageModels.value, imageModelKey.value);
  if (!model) return ElMessage.warning("请选择图片模型");
  emit("generateArtifact", { targetType, targetId: props.shot.id, mediaType: "image", providerId: model.providerId, modelId: model.modelId });
}
async function optimize(mode: "general" | "h3") {
  const model = pickModel(props.languageModels, promptModelKey.value);
  if (!model) return ElMessage.warning("请选择提示词优化模型");
  optimizing.value = mode;
  try {
    const result = await http<{ prompt: string }>({ method: "POST", url: "/api/production/shot/optimizePrompt", data: { directory: props.directory, providerId: model.providerId, modelId: model.modelId, shotId: props.shot.id, mode }, timeout: 5 * 60 * 1000 });
    commonPrompt.value = result.prompt;
    emit("dirty");
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : "提示词优化失败"); }
  finally { optimizing.value = ""; }
}
</script>
<style scoped lang="scss">
.shotStudio { display: grid; gap: 14px; padding: 16px; border: 1px solid var(--el-border-color-light); border-radius: 16px; background: var(--el-bg-color-overlay); }.studioHeader { display: flex; align-items: center; justify-content: space-between; gap: 14px; }.studioHeader h2, .studioHeader p { margin: 0; }.studioHeader h2 { margin: 4px 0; font-size: 19px; }.studioHeader p { color: var(--el-text-color-secondary); font-size: 11px; }.eyebrow { color: var(--el-color-primary); font-size: 9px; letter-spacing: .14em; }.headerActions { display: flex; align-items: center; gap: 6px; }.studioGrid { display: grid; grid-template-columns: 220px minmax(0, 1fr) 280px; gap: 12px; align-items: start; }.referenceColumn, .promptColumn, .artifactColumn { min-width: 0; padding: 12px; border-radius: 12px; background: var(--el-fill-color-lighter); }.columnTitle, .promptHeader, .artifactHead { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 9px; }.columnTitle h3, .promptHeader h3 { margin: 0; font-size: 13px; }.columnTitle span { color: var(--el-text-color-secondary); font-size: 10px; }.referenceCard { display: grid; grid-template-columns: 54px minmax(0, 1fr); gap: 8px; align-items: center; margin-bottom: 8px; padding: 8px; border-radius: 9px; background: var(--el-bg-color-overlay); }.referenceImage { display: grid; width: 54px; height: 42px; place-items: center; overflow: hidden; border-radius: 7px; background: var(--el-fill-color); color: var(--el-text-color-placeholder); }.referenceImage img { width: 100%; height: 100%; object-fit: cover; }.referenceCard div:last-child { display: grid; min-width: 0; gap: 2px; }.referenceCard strong { font-size: 11px; }.referenceCard small { overflow: hidden; color: var(--el-text-color-secondary); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }.inlineFields { display: grid; grid-template-columns: 1fr 1fr; gap: 0 9px; }.promptBlock { margin-bottom: 12px; padding: 12px; border: 1px solid var(--el-border-color-light); border-radius: 12px; background: var(--el-bg-color-overlay); }.promptTitle { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; }.promptTitle>div:first-child { display: grid; gap: 3px; }.promptTitle strong { font-size: 12px; }.promptTitle small { color: var(--el-text-color-secondary); font-size: 10px; }.promptActions { display: flex; flex-shrink: 0; gap: 6px; }.generationBar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 8px; }.generationBar .el-input { width: 130px; }.continuationToggle { display: flex; align-items: center; gap: 6px; font-size: 11px; }.artifactColumn { display: grid; gap: 9px; }.artifactCard { padding: 10px; border: 1px solid var(--el-border-color-lighter); border-radius: 10px; background: var(--el-bg-color-overlay); }.artifactHead div { display: grid; gap: 2px; }.artifactHead strong { font-size: 12px; }.artifactHead small { color: var(--el-text-color-secondary); font-size: 9px; }.artifactPreview { display: grid; height: 110px; place-items: center; overflow: hidden; margin: 8px 0; border-radius: 8px; background: repeating-conic-gradient(#18191e 0 25%, #111217 0 50%) 50% / 18px 18px; color: var(--el-text-color-placeholder); }.artifactPreview img { width: 100%; height: 100%; object-fit: cover; }.artifactActions { display: flex; align-items: center; justify-content: space-between; gap: 6px; }.artifactActions .el-checkbox { margin-right: 0; }.artifactActions :deep(.el-checkbox__label) { font-size: 9px; }.takeStrip { padding-top: 10px; border-top: 1px solid var(--el-border-color-lighter); }.takeList { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }.takeCard { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 6px; padding: 10px; border: 1px solid var(--el-border-color-lighter); border-radius: 9px; }.takeCard.selected { border-color: var(--el-color-success-light-5); background: var(--el-color-success-light-9); }.takeCard > div { display: grid; gap: 2px; }.takeCard strong { font-size: 11px; }.takeCard small { overflow: hidden; color: var(--el-text-color-secondary); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }.takeCard > small, .takeCard > .el-button { grid-column: 1 / -1; }@media(max-width:1350px){.studioGrid{grid-template-columns:200px minmax(0,1fr)}.artifactColumn{grid-column:1 / -1;grid-template-columns:repeat(3,1fr)}.artifactColumn>.columnTitle{grid-column:1 / -1}}@media(max-width:900px){.studioGrid{grid-template-columns:1fr}.artifactColumn{grid-column:auto;grid-template-columns:1fr}.inlineFields,.takeList{grid-template-columns:1fr}.promptTitle{align-items:flex-start;flex-direction:column}.promptActions{flex-wrap:wrap}.studioHeader{align-items:flex-start;flex-direction:column}}
</style>
