<template>
  <div class="imagePromptPreset">
    <el-dropdown trigger="click" :disabled="disabled" @command="openPreset">
      <el-button text :icon="IconUserSquareRounded" :disabled="disabled">提示词设定<icon-chevron-down :size="14" /></el-button>
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item command="fourView">角色四视图</el-dropdown-item>
          <el-dropdown-item command="characterSheet">角色设定卡</el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
    <el-dialog v-model="visible" :title="preset === 'fourView' ? '角色四视图提示词' : '角色设定卡提示词'" width="min(720px, 94vw)" appendToBody>
      <el-form labelPosition="top">
        <div class="formGrid">
          <el-form-item label="角色名称"><el-input v-model="subjectName" maxlength="80" placeholder="例如：林晚" /></el-form-item>
          <el-form-item label="服装与配色"><el-input v-model="outfit" maxlength="500" placeholder="例如：深灰风衣、黑色长靴、银色耳饰" /></el-form-item>
        </div>
        <el-form-item label="外貌与身份特征"><el-input v-model="appearance" type="textarea" :rows="3" maxlength="2000" placeholder="年龄、发型、脸型、体型、身份、标志性细节" /></el-form-item>
        <el-form-item label="补充要求（可选）"><el-input v-model="notes" type="textarea" :rows="2" maxlength="2000" placeholder="例如：冷峻疏离；不要文字；保持纯色背景" /></el-form-item>
        <el-form-item label="提示词预览"><el-input v-model="preview" type="textarea" :autosize="{ minRows: 8, maxRows: 18 }" resize="none" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="visible = false">取消</el-button><el-button @click="rebuild">重新生成</el-button><el-button type="primary" @click="apply">使用此提示词</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { ElButton, ElDialog, ElDropdown, ElDropdownItem, ElDropdownMenu, ElForm, ElFormItem, ElInput } from "element-plus";
import { IconChevronDown, IconUserSquareRounded } from "@tabler/icons-vue";

type Preset = "fourView" | "characterSheet";
const props = withDefaults(defineProps<{ stylePrompt?: string; projectName?: string; disabled?: boolean }>(), {
  stylePrompt: "", projectName: "", disabled: false,
});
const emit = defineEmits<{ apply: [prompt: string, preset: Preset] }>();
const visible = ref(false);
const preset = ref<Preset>("fourView");
const subjectName = ref("主角");
const appearance = ref("");
const outfit = ref("");
const notes = ref("");
const preview = ref("");

function openPreset(command: string) {
  if (command !== "fourView" && command !== "characterSheet") return;
  preset.value = command;
  if (!subjectName.value.trim() || subjectName.value === "主角") subjectName.value = props.projectName ? `${props.projectName}主角` : "主角";
  visible.value = true;
  rebuild();
}

function rebuild() {
  const name = subjectName.value.trim() || "the protagonist";
  const details = [appearance.value.trim(), outfit.value.trim()].filter(Boolean).join(". ");
  const style = props.stylePrompt.trim() ? ` Visual style: ${props.stylePrompt.trim()}.` : "";
  const extra = notes.value.trim() ? ` Additional requirements: ${notes.value.trim()}.` : "";
  preview.value = preset.value === "fourView"
    ? `Character turnaround reference sheet for ${name}. A clean four-panel horizontal layout with equal panel sizes and a consistent plain light-gray studio background. Panel 1: tight facial close-up showing recognizable facial structure, hairstyle, expression and material details. Panel 2: full-body front view in a neutral standing pose, entire body and footwear fully inside the frame. Panel 3: full-body side profile view with the same pose, proportions, costume and accessories. Panel 4: full-body back view showing the back of the hairstyle, garment construction and accessories. The face, body proportions, hairstyle, outfit, colors and accessories must remain identical across all four views.${details ? ` Character details: ${details}.` : ""}${style}${extra} No captions, no labels, no logos, no watermark, no collage borders, no extra characters.`
    : `Professional character design model sheet for ${name}, presented as one polished reference board. Include a large heroic portrait, a front full-body view, a side full-body view, a back full-body view, three distinct facial expressions, two signature poses, and a compact row of key props or accessories. Keep the same face, age, body proportions, hairstyle, costume construction, colors and material details across every panel. Use a clean neutral studio background, organized editorial layout, clear silhouettes and production-ready concept-art rendering.${details ? ` Character details: ${details}.` : ""}${style}${extra} No misspelled text, no watermark, no logo, no duplicate characters, no unrelated background scene.`;
}

function apply() {
  if (!preview.value.trim()) rebuild();
  emit("apply", preview.value.trim(), preset.value);
  visible.value = false;
}
</script>

<style scoped lang="scss">
.imagePromptPreset { display: inline-flex; }
.formGrid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
@media (max-width: 620px) { .formGrid { grid-template-columns: 1fr; } }
</style>
