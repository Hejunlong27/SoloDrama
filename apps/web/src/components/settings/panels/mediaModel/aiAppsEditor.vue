<template>
  <section class="aiAppsEditor" aria-label="RunningHub AI 应用通道">
    <div class="editorHeader">
      <div>
        <strong>RunningHub AI 应用通道</strong>
        <p>一个 RunningHub 通道可同时接入多个 AI App。只需填写应用名称、类型和 webappId / appId；调用时会通过 RunningHub 官方 apiCallDemo 自动读取输入字段。</p>
      </div>
      <el-button :icon="IconPlus" @click="addApp">添加 AI 应用</el-button>
    </div>

    <div class="appList">
      <el-card v-for="(app, index) in apps" :key="app.key" class="appCard" shadow="never">
        <template #header>
          <div class="appTitle">
            <el-input v-model="app.label" aria-label="AI 应用显示名称" placeholder="例如：Muse Video" @input="sync" />
            <el-select v-model="app.type" class="typeSelect" aria-label="AI 应用类型" @change="sync">
              <el-option label="图片" value="image" />
              <el-option label="视频" value="video" />
              <el-option label="音频" value="audio" />
            </el-select>
            <el-button text type="danger" :icon="IconTrash" aria-label="删除 AI 应用" @click="removeApp(index)" />
          </div>
        </template>

        <div class="appGrid">
          <label>
            <span>webappId / appId</span>
            <el-input v-model="app.webappId" dir="ltr" placeholder="从 RunningHub AI 应用地址中复制数字 ID" @input="sync" />
          </label>
        </div>

        <el-alert title="无需填写 nodeInfoList、输入映射或输出映射；生成时会自动读取官方应用字段并回传提示词和参考图。" type="info" :closable="false" showIcon />
      </el-card>
    </div>

    <el-empty v-if="!apps.length" description="尚未添加 AI 应用" :imageSize="72" />
  </section>
</template>

<script setup lang="ts">
import { ref, watch } from "vue";
import { IconPlus, IconTrash } from "@tabler/icons-vue";
import type { MediaProviderModel } from "@solodrama/provider-web/types";

type AppType = "image" | "video" | "audio";
type AppDraft = {
  key: string;
  id: string;
  label: string;
  type: AppType;
  webappId: string;
  nodeInfoList?: string;
  inputMapping?: string;
  outputMapping?: string;
  imageValue: "fileName" | "url";
};
const props = defineProps<{ defaultValue?: string }>();
const config = defineModel<Record<string, unknown>>("config", { default: () => ({}) });
const models = defineModel<MediaProviderModel[]>("models", { default: () => [] });
const apps = ref<AppDraft[]>([]);
let syncingFromConfig = false;

function fromConfig(value: unknown): AppDraft[] {
  if (typeof value !== "string" || !value.trim()) return [];
  try {
    const parsed = JSON.parse(value);
    if (!Array.isArray(parsed)) return [];
    return parsed.flatMap(item => {
      if (!item || typeof item !== "object" || Array.isArray(item)) return [];
      const app = item as Record<string, unknown>;
      if (!["image", "video", "audio"].includes(String(app.type))) return [];
      return [{
        key: crypto.randomUUID(),
        id: typeof app.id === "string" ? app.id : "",
        label: typeof app.label === "string" ? app.label : "",
        type: app.type as AppType,
        webappId: typeof app.webappId === "string" ? app.webappId : String(app.webappId ?? ""),
        ...(app.nodeInfoList !== undefined ? { nodeInfoList: typeof app.nodeInfoList === "string" ? app.nodeInfoList : JSON.stringify(app.nodeInfoList, null, 2) } : {}),
        ...(app.inputMapping !== undefined ? { inputMapping: typeof app.inputMapping === "string" ? app.inputMapping : JSON.stringify(app.inputMapping, null, 2) } : {}),
        ...(app.outputMapping !== undefined ? { outputMapping: typeof app.outputMapping === "string" ? app.outputMapping : JSON.stringify(app.outputMapping, null, 2) } : {}),
        imageValue: app.imageValue === "url" ? "url" : "fileName",
      }];
    });
  } catch {
    return [];
  }
}

watch(() => config.value.aiApps, value => {
  const current = serialize();
  const raw = typeof value === "string" && value.trim() ? value : props.defaultValue ?? "";
  if (raw && raw !== current) {
    syncingFromConfig = true;
    apps.value = fromConfig(raw);
    syncingFromConfig = false;
    if (!value && raw) config.value = { ...(config.value ?? {}), aiApps: raw };
    syncModels();
  } else if (!apps.value.length && raw) {
    apps.value = fromConfig(raw);
    syncModels();
  }
}, { immediate: true });

function addApp() {
  const index = apps.value.length + 1;
  apps.value.push({
    key: crypto.randomUUID(),
    id: `runningHubApp${index}`,
    label: `RunningHub AI 应用 ${index}`,
    type: "video",
    webappId: "",
    nodeInfoList: "[]",
    inputMapping: `{\n  "prompt": [],\n  "images": [],\n  "extra": {}\n}`,
    outputMapping: "{}",
    imageValue: "fileName",
  });
  sync();
}

function removeApp(index: number) {
  apps.value.splice(index, 1);
  sync();
}

function serialize() {
  return JSON.stringify(apps.value.map(({ key, ...app }) => ({
    id: app.id.trim(),
    label: app.label.trim(),
    type: app.type,
    webappId: app.webappId.trim(),
    ...(app.nodeInfoList !== undefined ? { nodeInfoList: app.nodeInfoList } : {}),
    ...(app.inputMapping !== undefined ? { inputMapping: app.inputMapping } : {}),
    ...(app.outputMapping !== undefined ? { outputMapping: app.outputMapping } : {}),
    imageValue: app.imageValue,
  })), null, 2);
}

function sync() {
  if (syncingFromConfig) return;
  config.value = { ...(config.value ?? {}), aiApps: serialize() };
  syncModels();
}

function syncModels() {
  const previous = new Map(models.value.map(model => [model.id, model]));
  models.value = apps.value.filter(app => app.id.trim() && app.label.trim()).map(app => {
    const existing = previous.get(app.id.trim());
    return {
      ...(existing ?? {}),
      id: app.id.trim(),
      label: app.label.trim(),
      type: app.type,
      ...(app.type === "image" ? {
        mode: ["text", "singleImage", "multiReference"],
        imageRatios: ["1:1", "4:3", "3:4", "16:9", "9:16"],
      } : app.type === "video" ? {
        mode: ["text", "singleImage", "endFrameOptional", ["imageReference:6"]],
        audio: "optional",
        imageRatios: ["adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"],
        durationResolutionMap: [{ duration: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30], resolution: ["480P", "720P", "1080P"] }],
      } : {
        mode: ["text"],
      }),
      rules: [{ type: "switch", field: "allowUnknownCostSubmit", title: "费用未知时仍允许提交", value: false }],
    } as MediaProviderModel;
  });
}
</script>

<style lang="scss" scoped>
.aiAppsEditor {
  display: grid;
  gap: 12px;
  margin-bottom: 18px;
  padding: 14px;
  border: 1px solid var(--el-color-primary-light-7);
  border-radius: calc(var(--ui-radius) * 1.5);
  background: color-mix(in srgb, var(--el-color-primary-light-9) 64%, var(--el-bg-color-overlay));

  .editorHeader { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
  .editorHeader strong { font-size: 13px; }
  .editorHeader p { margin: 4px 0 0; color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.6; }
  .appList { display: grid; gap: 12px; }
  .appCard :deep(.el-card__header) { padding: 10px 12px; }
  .appCard :deep(.el-card__body) { display: grid; gap: 12px; }
  .appTitle { display: grid; grid-template-columns: minmax(0, 1fr) 110px auto; align-items: center; gap: 8px; }
  .appGrid { display: grid; grid-template-columns: minmax(0, 1fr); gap: 10px; }
  .appGrid label { display: grid; gap: 6px; min-width: 0; }
  .appGrid span { color: var(--el-text-color-regular); font-size: 12px; font-weight: 500; }
}
@media (max-width: 720px) {
  .aiAppsEditor .editorHeader { flex-direction: column; }
  .aiAppsEditor .appTitle, .aiAppsEditor .appGrid { grid-template-columns: 1fr; }
}
</style>