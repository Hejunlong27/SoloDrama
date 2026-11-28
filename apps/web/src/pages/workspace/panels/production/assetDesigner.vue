<template>
  <div class="assetDesigner">
    <header class="designerHeader">
      <div class="headerTitle"><div><p>{{ kindLabel }}设计</p><h2>{{ entityName }}</h2></div><el-tag :type="entityConfirmed ? 'success' : 'info'">{{ entityConfirmed ? '已确认' : '草稿' }}</el-tag></div>
      <div class="headerActions"><el-button :loading="generating" @click="emit('generateReference', kind, entityId)">生成参考图</el-button><el-switch :modelValue="entityConfirmed" activeText="确认此设定" @change="emit('confirm', kind, entityId, Boolean($event))" /></div>
    </header>

    <div class="designerGrid">
      <section class="visualPanel">
        <div class="mainVisual"><img v-if="activeReference" :src="activeReference.url" :alt="entityName" /><div v-else class="emptyVisual"><icon-photo :size="32" /><span>生成或关联参考图后在此预览</span></div></div>
        <div class="referenceStrip"><div v-for="image in referenceImages" :key="image.id" class="referenceThumb" :class="{ active: image.id === activeReferenceId }" @click="activeReferenceId = image.id"><img :src="image.url" :alt="image.name" /></div><div v-if="!referenceImages.length" class="emptyReference">暂无参考图</div></div>
        <div class="referenceActions"><el-select v-model="referenceAssetId" clearable placeholder="选择已有图片" size="small"><el-option v-for="asset in imageAssets" :key="asset.id" :label="asset.name || asset.path" :value="asset.id" /></el-select><el-button size="small" :disabled="!referenceAssetId" @click="emit('attachReference', kind, entityId, referenceAssetId)">加入参考</el-button><el-button size="small" @click="emit('queryImpact', kind, entityId)">关联镜头</el-button></div>
      </section>

      <section class="formPanel">
        <template v-if="character">
          <div class="formSection"><div class="sectionTitle"><h3>角色设定</h3><span>形象描述统一维护</span></div><el-form labelPosition="top"><div class="inlineFields"><el-form-item label="姓名"><el-input v-model="character.name" @input="emit('dirty')" /></el-form-item><el-form-item label="年龄"><el-input v-model="character.age" @input="emit('dirty')" /></el-form-item></div><el-form-item label="人物形象描述"><el-input v-model="visualDescription" type="textarea" :rows="7" placeholder="统一描述面孔、发型、身材、服装、气质和辨识特征" @input="emit('dirty')" /></el-form-item><el-form-item label="性格与表演"><el-input v-model="character.personality" type="textarea" :rows="3" @input="emit('dirty')" /></el-form-item></el-form></div>
          <div class="formSection voiceSection">
            <div class="sectionTitle"><div><h3>智能音色</h3><span>根据角色设定设计并试听声音</span></div><el-button size="small" type="primary" plain @click="emit('voiceDesign', character.id)">智能音色设计</el-button></div>
            <el-form labelPosition="top"><div class="inlineFields"><el-form-item label="Provider"><el-input v-model="character.voice.providerId" @input="emit('dirty')" /></el-form-item><el-form-item label="音色 ID"><el-input v-model="character.voice.voiceId" @input="emit('dirty')" /></el-form-item><el-form-item label="语速"><el-input-number v-model="character.voice.speed" :min="0.5" :max="3" :step="0.1" @change="emit('dirty')" /></el-form-item><el-form-item label="语言"><el-input v-model="character.voice.language" @input="emit('dirty')" /></el-form-item></div><el-form-item label="音色设计描述"><el-input v-model="character.voice.designPrompt" type="textarea" :rows="3" placeholder="例如：年轻女性，克制冷静，声线清亮，尾音轻微下沉" @input="emit('dirty')" /></el-form-item></el-form>
          </div>
          <div class="formSection"><div class="sectionTitle"><h3>服装版本</h3><el-button size="small" @click="addClothing">新增服装</el-button></div><div v-for="version in character.clothingVersions" :key="version.id" class="clothingRow"><el-input v-model="version.name" placeholder="服装名称" @input="emit('dirty')" /><el-input v-model="version.description" placeholder="服装描述" @input="emit('dirty')" /><el-switch v-model="version.confirmed" activeText="确认" @change="emit('dirty')" /></div></div>
        </template>
        <template v-else-if="location"><div class="formSection"><div class="sectionTitle"><h3>场景设定</h3><span>空间、光线和氛围</span></div><el-form labelPosition="top"><el-form-item label="场景名称"><el-input v-model="location.name" @input="emit('dirty')" /></el-form-item><el-form-item label="场景描述"><el-input v-model="location.description" type="textarea" :rows="4" @input="emit('dirty')" /></el-form-item><el-form-item label="空间结构"><el-input v-model="location.spatialStructure" type="textarea" :rows="3" @input="emit('dirty')" /></el-form-item><div class="inlineFields"><el-form-item label="时间"><el-input v-model="location.timeOfDay" @input="emit('dirty')" /></el-form-item><el-form-item label="光线"><el-input v-model="location.lighting" @input="emit('dirty')" /></el-form-item><el-form-item label="色彩"><el-input v-model="location.colorPalette" @input="emit('dirty')" /></el-form-item></div><el-form-item label="环境氛围"><el-input v-model="location.atmosphere" type="textarea" :rows="3" @input="emit('dirty')" /></el-form-item></el-form></div></template>
        <template v-else-if="prop"><div class="formSection"><div class="sectionTitle"><h3>道具设定</h3><span>外形与叙事用途</span></div><el-form labelPosition="top"><el-form-item label="道具名称"><el-input v-model="propName" @input="emit('dirty')" /></el-form-item><el-form-item label="描述"><el-input v-model="propDescription" type="textarea" :rows="6" @input="emit('dirty')" /></el-form-item></el-form></div></template>
      </section>
    </div>
  </div>
</template>
<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { ProductionCharacter, ProductionDocument, ProductionLocation, ProductionProp } from "@solodrama/production";
import { IconPhoto } from "@tabler/icons-vue";
import { useProductionAssetUrls } from "./useProductionAssetUrls";

type AssetKind = "character" | "location" | "prop";
const props = defineProps<{
  directory: string; kind: AssetKind; document: ProductionDocument;
  character?: ProductionCharacter; location?: ProductionLocation; prop?: ProductionProp; generating?: boolean;
}>();
const emit = defineEmits<{
  dirty: []; confirm: [kind: AssetKind, id: string, confirmed: boolean]; voiceDesign: [characterId: string];
  generateReference: [kind: AssetKind, id: string]; attachReference: [kind: AssetKind, id: string, assetId: string]; queryImpact: [kind: AssetKind, id: string];
}>();
const referenceAssetId = ref("");
const activeReferenceId = ref("");
const { assetUrls } = useProductionAssetUrls(() => props.directory, () => props.document.assets);
const entityId = computed(() => props.character?.id ?? props.location?.id ?? props.prop?.id ?? "");
const entityName = computed(() => props.character?.name ?? props.location?.name ?? props.prop?.name ?? "未命名");
const entityConfirmed = computed(() => props.character?.confirmed ?? props.location?.confirmed ?? props.prop?.confirmed ?? false);
const kindLabel = computed(() => ({ character: "角色", location: "场景", prop: "道具" })[props.kind]);
const references = computed(() => props.character?.referenceImages ?? props.location?.referenceImages ?? props.prop?.referenceImages ?? []);
const imageAssets = computed(() => props.document.assets.filter(asset => asset.type === "image"));
const referenceImages = computed(() => references.value.flatMap(reference => {
  const asset = props.document.assets.find(item => item.id === reference.assetId);
  const url = assetUrls.value[reference.assetId];
  return asset && url ? [{ id: reference.id, name: asset.name || asset.path, url }] : [];
}));
const activeReference = computed(() => referenceImages.value.find(item => item.id === activeReferenceId.value) ?? referenceImages.value[0]);
const propName = computed({ get: () => props.prop?.name ?? "", set: (value: string) => { if (props.prop) props.prop.name = value; } });
const propDescription = computed({ get: () => props.prop?.description ?? "", set: (value: string) => { if (props.prop) props.prop.description = value; } });
const visualDescription = computed({
  get() {
    const character = props.character;
    if (!character) return "";
    return character.visualDescription || [character.appearance, character.visualProfile.face, character.visualProfile.hair, character.visualProfile.body, character.visualProfile.style].filter(Boolean).join("，");
  },
  set(value: string) { if (props.character) props.character.visualDescription = value; },
});
watch([() => props.kind, entityId, () => referenceImages.value.map(item => item.id).join("|")], () => {
  if (!referenceImages.value.some(item => item.id === activeReferenceId.value)) activeReferenceId.value = referenceImages.value[0]?.id ?? "";
}, { immediate: true });
function addClothing() {
  if (!props.character) return;
  props.character.clothingVersions.push({ id: crypto.randomUUID(), name: "新服装", description: "", assetIds: [], confirmed: false });
  emit("dirty");
}
</script>
<style scoped lang="scss">
.assetDesigner { display: grid; gap: 16px; }.designerHeader { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 15px 18px; border: 1px solid var(--el-border-color-light); border-radius: 14px; background: var(--el-bg-color-overlay); }.headerTitle, .headerActions { display: flex; align-items: center; gap: 10px; }.sectionTitle>div { display: grid; gap: 3px; }.headerTitle p, .headerTitle h2 { margin: 0; }.headerTitle p { color: var(--el-text-color-secondary); font-size: 10px; }.headerTitle h2 { margin-top: 3px; font-size: 19px; }.designerGrid { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(380px, .85fr); gap: 16px; align-items: start; }.visualPanel, .formPanel { border: 1px solid var(--el-border-color-light); border-radius: 15px; background: var(--el-bg-color-overlay); }.visualPanel { padding: 14px; }.mainVisual { display: grid; min-height: 520px; place-items: center; overflow: hidden; border-radius: 12px; background: repeating-conic-gradient(#18191e 0 25%, #111217 0 50%) 50% / 24px 24px; }.mainVisual img { width: 100%; height: 100%; max-height: 660px; object-fit: contain; }.emptyVisual { display: grid; place-items: center; gap: 9px; color: var(--el-text-color-placeholder); font-size: 11px; }.referenceStrip { display: grid; grid-template-columns: repeat(6, 1fr); gap: 6px; margin-top: 10px; }.referenceThumb { overflow: hidden; aspect-ratio: 1; border: 2px solid transparent; border-radius: 7px; cursor: pointer; }.referenceThumb.active { border-color: var(--el-color-primary); }.referenceThumb img { width: 100%; height: 100%; object-fit: cover; }.emptyReference { grid-column: 1 / -1; padding: 9px; color: var(--el-text-color-secondary); text-align: center; font-size: 10px; }.referenceActions { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 8px; margin-top: 10px; }.formPanel { display: grid; gap: 12px; padding: 14px; }.formSection { padding: 14px; border-radius: 11px; background: var(--el-fill-color-lighter); }.sectionTitle { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 12px; }.sectionTitle h3, .sectionTitle span { margin: 0; }.sectionTitle h3 { font-size: 15px; }.sectionTitle span { color: var(--el-text-color-secondary); font-size: 10px; }.inlineFields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 10px; }.voiceSection { border: 1px solid var(--el-color-primary-light-7); }.clothingRow { display: grid; grid-template-columns: 110px minmax(0, 1fr) auto; align-items: center; gap: 8px; margin-top: 7px; }@media(max-width:1100px){.designerGrid{grid-template-columns:1fr}.mainVisual{min-height:420px}.referenceStrip{grid-template-columns:repeat(8,1fr)}}@media(max-width:700px){.designerHeader{align-items:flex-start;flex-direction:column}.inlineFields{grid-template-columns:1fr}.referenceActions{grid-template-columns:1fr}.clothingRow{grid-template-columns:1fr}}
</style>
