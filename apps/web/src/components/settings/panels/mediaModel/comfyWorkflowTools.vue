<template>
  <section class="comfyTools" aria-label="ComfyUI 工作流导入">
    <div class="toolsHeader">
      <div>
        <strong>ComfyUI 工作流导入</strong>
        <p>直接导入 ComfyUI 界面导出的工作流 JSON，也兼容 API 格式。界面工作流会自动转换为 /prompt API 图，再通过映射绑定输入。</p>
      </div>
      <icon-braces :size="20" aria-hidden="true" />
    </div>
    <el-segmented v-model="target" class="targetTabs" :options="targets" block ariaLabel="工作流类型" />
    <div class="toolsRow">
      <el-button :icon="IconUpload" @click="fileInput?.click()">导入 {{ activeTarget.label }} JSON</el-button>
      <el-button :icon="IconWand" @click="autoMap">自动识别 {{ activeTarget.label }} 映射</el-button>
      <input ref="fileInput" type="file" accept=".json,application/json" hidden @change="importFile" />
    </div>
    <p v-if="hint" class="toolsHint" :data-error="!!error">{{ hint }}</p>
    <div class="fieldEditors">
      <label class="jsonField">
        <span>{{ activeTarget.label }}工作流 JSON</span>
        <el-input
          :modelValue="workflowValue"
          type="textarea"
          :rows="7"
          resize="vertical"
          placeholder="粘贴或导入 ComfyUI 界面工作流 JSON；API 格式也兼容"
          @update:modelValue="value => setText(activeTarget.workflow, value)" />
      </label>
      <label v-if="activeTarget.mapping" class="jsonField">
        <span>{{ activeTarget.label }}输入映射 JSON</span>
        <el-input
          :modelValue="mappingValue"
          type="textarea"
          :rows="5"
          resize="vertical"
          placeholder="绑定 prompt、images、seed、steps 等节点字段"
          @update:modelValue="value => setText(activeTarget.mapping!, value)" />
      </label>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { IconBraces, IconUpload, IconWand } from "@tabler/icons-vue";
import { inferComfyMapping, parseComfyJsonWithReport } from "@/lib/comfyWorkflow";

type Target = { label: string; value: string; workflow: string; mapping?: string };
const props = defineProps<{ fields: string[] }>();
const model = defineModel<Record<string, unknown>>({ default: () => ({}) });
const allTargets: Target[] = [
  { label: "文生图", value: "textToImage", workflow: "textToImageWorkflow", mapping: "textToImageMapping" },
  { label: "图像编辑", value: "imageEdit", workflow: "imageEditWorkflow", mapping: "imageEditMapping" },
  { label: "视频模型", value: "video", workflow: "videoWorkflow", mapping: "videoMapping" },
];
const targets = computed(() => allTargets.filter(item => props.fields.includes(item.workflow)));
const activeTarget = computed(() => targets.value.find(item => item.value === target.value) ?? targets.value[0]!);
const target = ref(allTargets[0]!.value);
const fileInput = ref<HTMLInputElement>();
const hint = ref("");
const error = ref(false);
watch(targets, value => {
  if (!value.some(item => item.value === target.value)) target.value = value[0]?.value ?? "textToImage";
}, { immediate: true });

function textValue(field?: string) {
  const value = field ? (model.value ?? {})[field] : "";
  return typeof value === "string" ? value : "";
}
const workflowValue = computed(() => textValue(activeTarget.value.workflow));
const mappingValue = computed(() => textValue(activeTarget.value.mapping));

function setText(field: string, value: string) {
  model.value = { ...(model.value ?? {}), [field]: value };
}

async function importFile(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  if (file.size > 5 * 1024 * 1024) return fail("JSON 文件不能超过 5 MB");
  try {
    const converted = parseComfyJsonWithReport(await file.text());
    model.value = { ...(model.value ?? {}), [activeTarget.value.workflow]: JSON.stringify(converted.workflow, null, 2) };
    hint.value = converted.warnings.length ? `已导入 ${file.name}；${converted.warnings.slice(0, 3).join("；")}` : `已导入并转换 ${file.name}`;
    error.value = converted.warnings.length > 0;
    if (converted.warnings.length) ElMessage.warning(`${activeTarget.value.label} 工作流已转换，请检查转换提示`);
    else ElMessage.success(`${activeTarget.value.label} 工作流已导入并转换，保存后生效`);
  } catch (cause) {
    fail(cause instanceof Error ? cause.message : "导入 JSON 失败");
  }
}

function autoMap() {
  const mappingField = activeTarget.value.mapping;
  if (!mappingField) return fail("当前类型没有对应的映射字段");
  try {
    if (!workflowValue.value.trim()) throw new Error(`请先导入或填写${activeTarget.value.label}工作流 JSON`);
    const converted = parseComfyJsonWithReport(workflowValue.value);
    setText(activeTarget.value.workflow, JSON.stringify(converted.workflow, null, 2));
    const mapping = inferComfyMapping(converted.workflow);
    if (!Object.keys(mapping).length) throw new Error("没有识别到常用输入节点，请手动填写映射 JSON");
    setText(mappingField, JSON.stringify(mapping, null, 2));
    hint.value = converted.warnings.length ? `已识别 ${Object.keys(mapping).length} 个输入映射；${converted.warnings.slice(0, 3).join("；")}` : `已识别 ${Object.keys(mapping).length} 个输入映射，请检查后保存`;
    error.value = converted.warnings.length > 0;
    ElMessage.success(`${activeTarget.value.label}映射已生成，请检查节点 ID 和参考图顺序`);
  } catch (cause) {
    fail(cause instanceof Error ? cause.message : "自动识别映射失败");
  }
}

function fail(message: string) {
  hint.value = message;
  error.value = true;
  ElMessage.error(message);
}
</script>

<style lang="scss" scoped>
.comfyTools {
  margin-bottom: 18px;
  padding: 14px;
  border: 1px solid var(--el-color-primary-light-7);
  border-radius: calc(var(--ui-radius) * 1.5);
  background: color-mix(in srgb, var(--el-color-primary-light-9) 70%, var(--el-bg-color-overlay));
  .toolsHeader { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; > svg { flex-shrink: 0; color: var(--el-color-primary); } }
  strong { font-size: 13px; }
  p { margin: 4px 0 0; color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.6; }
  .targetTabs { margin-top: 12px; }
  .toolsRow { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
  .toolsHint { color: var(--el-text-color-secondary); &[data-error="true"] { color: var(--el-color-danger); } }
  .fieldEditors { display: grid; gap: 14px; margin-top: 14px; }
  .jsonField { display: grid; gap: 7px; > span { color: var(--el-text-color-regular); font-size: 12px; font-weight: 500; } }
}
</style>
