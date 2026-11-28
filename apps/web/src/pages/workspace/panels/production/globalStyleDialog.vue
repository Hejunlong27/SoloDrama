<template>
  <el-dialog v-model="visible" title="全局画风" width="min(1120px, 94vw)" alignCenter appendToBody destroyOnClose>
    <div class="styleToolbar">
      <el-input v-model="search" clearable placeholder="搜索风格" />
      <el-segmented v-model="group" :options="groupOptions" />
      <el-button type="primary" :loading="saving" @click="save">应用全局画风</el-button>
    </div>
    <p v-if="currentStyle" class="currentStyle">当前画风：{{ currentStyle.nameZh }}</p>
    <el-scrollbar maxHeight="68vh">
      <div class="styleGrid">
        <button v-for="(style, index) in filteredStyles" :key="style.key" type="button" class="styleCard" :class="{ active: form.styleKey === style.key }" :style="cardStyle(style.groupKey, index)" @click="selectStyle(style.key)">
          <span class="styleGroup">{{ style.groupLabel }}</span>
          <strong>{{ style.nameZh }}</strong>
          <small>{{ compact(style.promptZh, 88) }}</small>
          <i>{{ form.styleKey === style.key ? '已选择' : '选择' }}</i>
        </button>
      </div>
      <el-empty v-if="!filteredStyles.length" description="没有匹配的画风" />
    </el-scrollbar>
    <el-form labelPosition="top" class="stylePrompt">
      <el-form-item label="画风提示词"><el-input v-model="form.stylePrompt" type="textarea" :rows="4" /></el-form-item>
    </el-form>
    <template #footer><el-button @click="visible = false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存</el-button></template>
  </el-dialog>
</template><script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { getStylePrompt, styleGroups, styleLibrary, type StyleLibraryItem } from "@solodrama/node-shared/styleLibrary";
import { projectSettingsPath, type SoloDramaProjectSettings } from "@solodrama/node-shared/projectSettings";
import useWorkspaceFiles from "@/lib/workspaceFiles";
import { buildProjectSettings } from "@/lib/projectDefaults";

const visible = defineModel<boolean>({ default: false });
const props = defineProps<{ directory: string }>();
const emit = defineEmits<{ saved: [settings: SoloDramaProjectSettings] }>();
const files = useWorkspaceFiles(() => props.directory);
const project = ref<SoloDramaProjectSettings>();
const search = ref("");
const group = ref("all");
const saving = ref(false);
const form = reactive({ styleKey: "", stylePrompt: "" });
const groupOptions = [{ label: "全部", value: "all" }, ...styleGroups.map(item => ({ label: item.label, value: item.key }))];
const currentStyle = computed(() => styleLibrary.find(item => item.key === form.styleKey));
const filteredStyles = computed(() => {
  const query = search.value.trim().toLowerCase();
  return styleLibrary.filter(item => (group.value === "all" || item.groupKey === group.value)
    && (!query || [item.nameZh, item.nameEn, item.promptZh, item.promptEn].some(value => value.toLowerCase().includes(query))));
});
watch(visible, async value => {
  if (!value || !props.directory) return;
  try {
    project.value = await files.readJson<SoloDramaProjectSettings>(projectSettingsPath).catch(() => undefined);
    if (!project.value) {
      const name = props.directory.split(/[\\/]/).filter(Boolean).at(-1) || "SoloDrama 项目";
      project.value = buildProjectSettings({ name, aspectRatio: "9:16", resolution: "1080P", width: 1080, height: 1920, styleKey: "", stylePrompt: "", language: "zh-CN", directorSkill: "", episodeCount: 1, episodeSeconds: 90, fps: 30, tts: { voice: "", speed: 1 } });
    }
    form.styleKey = project.value.styleKey || "";
    form.stylePrompt = project.value.stylePrompt || getStylePrompt(form.styleKey);
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : "读取项目画风失败"); }
}, { immediate: true });

function selectStyle(key: string) {
  form.styleKey = key;
  form.stylePrompt = getStylePrompt(key);
}
function compact(value: string, max: number) {
  return value.length > max ? `${value.slice(0, max)}…` : value;
}
function cardStyle(groupKey: StyleLibraryItem["groupKey"], index: number) {
  const palettes: Record<StyleLibraryItem["groupKey"], string[]> = {
    realistic: ["#496479", "#786657"], "3d-special": ["#6f5c8f", "#456b77"], "2d": ["#8b5d67", "#4e7064"], custom: ["#666"],
  };
  const color = palettes[groupKey][index % 2] ?? "#555";
  return { background: `linear-gradient(145deg, color-mix(in srgb, ${color} 34%, #111), #111 72%)` };
}
async function save() {
  if (!project.value || saving.value) return;
  saving.value = true;
  try {
    project.value = { ...project.value, styleKey: form.styleKey, stylePrompt: form.stylePrompt.trim(), updatedAt: new Date().toISOString() };
    await files.writeJson(projectSettingsPath, project.value);
    emit("saved", project.value);
    ElMessage.success("全局画风已保存");
    visible.value = false;
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : "保存全局画风失败"); }
  finally { saving.value = false; }
}
</script><style scoped lang="scss">
.styleToolbar { display: grid; grid-template-columns: minmax(180px, 1fr) auto auto; gap: 10px; margin-bottom: 12px; }
.currentStyle { margin: 0 0 12px; color: var(--el-color-primary); font-size: 12px; }
.styleGrid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; padding-right: 8px; }
.styleCard { position: relative; display: flex; min-height: 150px; flex-direction: column; justify-content: flex-end; gap: 6px; overflow: hidden; padding: 14px; border: 1px solid rgb(255 255 255 / 10%); border-radius: 13px; color: #f5f5f2; text-align: left; cursor: pointer; }
.styleCard::before { position: absolute; inset: 0; background: radial-gradient(circle at 75% 20%, rgb(255 255 255 / 18%), transparent 32%); content: ""; pointer-events: none; }
.styleCard:hover, .styleCard.active { border-color: var(--el-color-primary); box-shadow: 0 0 0 2px color-mix(in srgb, var(--el-color-primary) 25%, transparent); }
.styleCard strong, .styleCard small, .styleCard i, .styleGroup { position: relative; z-index: 1; }
.styleCard strong { font-size: 16px; }.styleCard small { color: rgb(255 255 255 / 60%); font-size: 10px; line-height: 1.5; }
.styleCard i { color: var(--el-color-primary-light-3); font-size: 10px; font-style: normal; }
.styleGroup { align-self: flex-start; padding: 2px 6px; border-radius: 5px; background: rgb(0 0 0 / 28%); font-size: 9px; }
.stylePrompt { margin-top: 14px; }
@media (max-width: 900px) { .styleGrid { grid-template-columns: repeat(3, minmax(0, 1fr)); }.styleToolbar { grid-template-columns: 1fr; } }
@media (max-width: 620px) { .styleGrid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>