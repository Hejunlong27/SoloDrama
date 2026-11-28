<template>
  <el-dialog v-model="visible" title="智能音色设计" width="min(920px, 94vw)" appendToBody destroyOnClose>
    <div v-if="character" class="voiceDesigner">
      <section class="designForm">
        <div class="sectionHead"><div><h3>{{ character.name }}</h3><p>用角色设定生成可试听的音色方案，试听结果会记录为该角色的当前预览。</p></div><el-tag effect="plain">真实 TTS 任务</el-tag></div>
        <el-form labelPosition="top">
          <el-form-item label="音色设计描述"><el-input v-model="designPrompt" type="textarea" :rows="6" placeholder="描述年龄感、音高、音色、语速、情绪、口音和表演气质" @input="emit('dirty')" /></el-form-item>
          <el-form-item label="试听文本"><el-input v-model="previewText" type="textarea" :rows="3" maxlength="1000" showWordLimit placeholder="输入用于试听的角色台词或旁白" @input="emit('dirty')" /></el-form-item>
          <div class="inlineFields">
            <el-form-item label="语音模型"><el-select v-model="modelKey" filterable placeholder="选择已配置音频模型"><el-option v-for="model in audioModels" :key="modelKeyOf(model)" :label="`${model.providerLabel} / ${model.label}`" :value="modelKeyOf(model)" /></el-select></el-form-item>
            <el-form-item label="音色 ID"><el-input v-model="voiceId" placeholder="留空使用模型默认音色" @input="emit('dirty')" /></el-form-item>
            <el-form-item label="语速"><el-input-number v-model="speed" :min="0.25" :max="4" :step="0.05" @change="emit('dirty')" /></el-form-item>
            <el-form-item label="语言"><el-input v-model="language" placeholder="zh-CN" @input="emit('dirty')" /></el-form-item>
            <el-form-item label="情绪"><el-input v-model="emotion" placeholder="冷静、克制、温柔……" @input="emit('dirty')" /></el-form-item>
            <el-form-item label="表演说明"><el-input v-model="instructions" placeholder="停连、重音和表演细节" @input="emit('dirty')" /></el-form-item>
          </div>
        </el-form>
        <el-alert title="生成会把音色描述和表演说明作为 TTS 指令，并消耗所选语音模型的额度。" type="info" :closable="false" showIcon />
        <el-button class="generateButton" type="primary" :loading="generating" :disabled="!modelKey || !previewText.trim()" @click="generate">设计并试听</el-button>
      </section>

      <aside class="previewPanel">
        <div class="sectionHead"><div><h3>试听与历史</h3><p>只展示当前角色真实提交的语音设计任务。</p></div></div>
        <div class="currentPreview">
          <div class="previewLabel"><span>当前音色预览</span><el-tag v-if="currentAsset" size="small" type="success">已生成</el-tag></div>
          <audio v-if="currentAsset" :src="currentAsset" controls preload="metadata" />
          <div v-else class="emptyPreview">生成后可在此试听</div>
        </div>
        <div class="historyList">
          <article v-for="job in history" :key="job.id" class="historyItem">
            <div><strong>{{ new Date(job.createdAt).toLocaleString() }}</strong><small>{{ job.providerId }} / {{ job.modelId }}</small></div>
            <el-tag size="small" :type="job.status === 'completed' ? 'success' : job.status === 'failed' ? 'danger' : 'warning'">{{ job.status }}</el-tag>
            <audio v-if="job.assetId && assetUrls[job.assetId]" :src="assetUrls[job.assetId]" controls preload="metadata" />
            <small v-else-if="job.error" class="errorText">{{ job.error }}</small>
          </article>
          <el-empty v-if="!history.length" description="尚无智能音色生成记录" :imageSize="52" />
        </div>
      </aside>
    </div>
    <template #footer><el-button @click="visible = false">关闭</el-button></template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { ProductionCharacter, ProductionDocument } from "@solodrama/production";
import { useProductionAssetUrls } from "./useProductionAssetUrls";

type AudioModel = { providerId: string; providerLabel: string; modelId: string; label: string; type: "audio" };
type VoiceDesignPayload = { providerId: string; modelId: string; prompt: string; voice?: string; speed?: number; language?: string; emotion?: string; instructions?: string };
const props = defineProps<{ modelValue: boolean; directory: string; document: ProductionDocument; characterId: string; audioModels: AudioModel[]; generating?: boolean }>();
const emit = defineEmits<{ "update:modelValue": [value: boolean]; dirty: []; generate: [payload: VoiceDesignPayload] }>();
const visible = computed({ get: () => props.modelValue, set: (value: boolean) => emit("update:modelValue", value) });
const modelKey = ref("");
const character = computed(() => props.document.characters.find(item => item.id === props.characterId));
const { assetUrls } = useProductionAssetUrls(() => props.directory, () => props.document.assets);
const designPrompt = computed({ get: () => character.value?.voice.designPrompt ?? "", set: (value: string) => { if (character.value) character.value.voice.designPrompt = value; } });
const previewText = computed({ get: () => character.value?.voice.previewText ?? "", set: (value: string) => { if (character.value) character.value.voice.previewText = value; } });
const voiceId = computed({ get: () => character.value?.voice.voiceId ?? "", set: (value: string) => { if (character.value) character.value.voice.voiceId = value; } });
const speed = computed({ get: () => character.value?.voice.speed ?? 1, set: (value: number) => { if (character.value) character.value.voice.speed = value; } });
const language = computed({ get: () => character.value?.voice.language ?? "zh-CN", set: (value: string) => { if (character.value) character.value.voice.language = value; } });
const emotion = computed({ get: () => character.value?.voice.emotion ?? "", set: (value: string) => { if (character.value) character.value.voice.emotion = value; } });
const instructions = computed({ get: () => character.value?.voice.instructions ?? "", set: (value: string) => { if (character.value) character.value.voice.instructions = value; } });
const currentAsset = computed(() => character.value?.voice.previewAssetId ? assetUrls.value[character.value.voice.previewAssetId] : "");
const history = computed(() => props.document.generationJobs.filter(job => job.kind === "voiceDesign" && job.targetId === props.characterId).slice().reverse());
watch(() => [props.modelValue, props.audioModels, props.characterId] as const, ([open]) => {
  if (!open) return;
  if (!modelKey.value || !props.audioModels.some(model => modelKeyOf(model) === modelKey.value)) {
    const preferred = props.audioModels.find(model => model.providerId === "solodramaTts") ?? props.audioModels[0];
    modelKey.value = preferred ? modelKeyOf(preferred) : "";
  }
  const item = character.value;
  if (!item) return;
  item.voice.designPrompt ||= [item.description, item.personality, item.visualDescription].filter(Boolean).join("；");
  item.voice.previewText ||= item.voice.designPrompt ? "我会把这件事查清楚，也从不会让任何人替我决定结局。" : "这是角色音色试听。";
}, { immediate: true });
function modelKeyOf(model: AudioModel) { return JSON.stringify([model.providerId, model.modelId]); }
function selectedModel() { try { const value = JSON.parse(modelKey.value); return props.audioModels.find(model => model.providerId === value[0] && model.modelId === value[1]); } catch { return undefined; } }
function generate() {
  const model = selectedModel();
  if (!model) return;
  const item = character.value;
  if (!item || !previewText.value.trim()) return;
  const context = [designPrompt.value, `角色：${item.name}`, item.age && `年龄：${item.age}`, item.personality && `性格：${item.personality}`].filter(Boolean).join("\n");
  emit("generate", {
    providerId: model.providerId, modelId: model.modelId, prompt: previewText.value.trim(),
    ...(voiceId.value.trim() ? { voice: voiceId.value.trim() } : {}),
    ...(speed.value !== undefined ? { speed: speed.value } : {}),
    ...(language.value.trim() ? { language: language.value.trim() } : {}),
    ...(emotion.value.trim() ? { emotion: emotion.value.trim() } : {}),
    ...(context || instructions.value.trim() ? { instructions: [context, instructions.value].filter(Boolean).join("\n") } : {}),
  });
}
</script>

<style scoped lang="scss">
.voiceDesigner { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(320px, .85fr); gap: 16px; }
.designForm, .previewPanel { min-width: 0; padding: 16px; border: 1px solid var(--el-border-color-light); border-radius: 14px; background: var(--el-bg-color-overlay); }
.sectionHead { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.sectionHead h3, .sectionHead p { margin: 0; }
.sectionHead h3 { font-size: 17px; }
.sectionHead p { margin-top: 4px; color: var(--el-text-color-secondary); font-size: 11px; line-height: 1.55; }
.inlineFields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 12px; }
.generateButton { width: 100%; margin-top: 12px; }
.previewPanel { display: grid; grid-template-rows: auto auto minmax(0, 1fr); align-content: start; gap: 12px; }
.currentPreview { padding: 12px; border-radius: 11px; background: var(--el-fill-color-lighter); }
.previewLabel { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 9px; font-size: 12px; font-weight: 600; }
.currentPreview audio, .historyItem audio { width: 100%; }
.emptyPreview { display: grid; min-height: 78px; place-items: center; color: var(--el-text-color-secondary); font-size: 11px; }
.historyList { display: grid; max-height: 430px; gap: 8px; overflow: auto; }
.historyItem { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px; padding: 10px; border: 1px solid var(--el-border-color-lighter); border-radius: 10px; }
.historyItem>div { display: grid; gap: 2px; }
.historyItem strong { font-size: 11px; }
.historyItem small { color: var(--el-text-color-secondary); font-size: 9px; }
.historyItem audio, .historyItem .errorText { grid-column: 1 / -1; }
.errorText { color: var(--el-color-danger); }
@media (max-width: 820px) { .voiceDesigner, .inlineFields { grid-template-columns: 1fr; } }
</style>

