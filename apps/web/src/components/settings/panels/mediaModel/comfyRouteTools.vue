<template>
  <section class="comfyRoutes" aria-label="ComfyUI 多工作流通道">
    <div class="routesHeader">
      <div>
        <strong>ComfyUI 工作流通道</strong>
        <p>一个供应商可同时配置多套工作流。请为每套工作流填写自定义名称、模型 ID 和类型，保存后会同步到画布模型列表。</p>
      </div>
      <el-dropdown trigger="click" @command="addRoute">
        <el-button :icon="IconPlus">添加工作流</el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="textToImage">文生图</el-dropdown-item>
            <el-dropdown-item command="imageEdit">图像编辑</el-dropdown-item>
            <el-dropdown-item command="video">视频模型</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>

    <div class="routeList">
      <el-card v-for="(route, index) in routes" :key="route.key" class="routeCard" shadow="never">
        <template #header>
          <div class="routeTitle">
            <el-input v-model="route.label" aria-label="工作流显示名称" placeholder="例如：Pika 加速 H3" @input="sync" />
            <el-select v-model="route.kind" class="kindSelect" aria-label="工作流类型" @change="sync">
              <el-option label="文生图" value="textToImage" />
              <el-option label="图像编辑" value="imageEdit" />
              <el-option label="视频模型" value="video" />
            </el-select>
            <el-button text type="danger" :icon="IconTrash" aria-label="删除工作流" @click="removeRoute(index)" />
          </div>
        </template>

        <div class="routeGrid">
          <label>
            <span>模型 ID</span>
            <el-input v-model="route.id" dir="ltr" placeholder="例如：h3PikaFast" @input="sync" />
          </label>
          <label>
            <span>实例地址（可选）</span>
            <el-input v-model="route.baseUrl" dir="ltr" placeholder="留空使用供应商地址" @input="sync" />
          </label>
          <label>
            <span>鉴权 Header 名称（可选）</span>
            <el-input v-model="route.authHeaderName" dir="ltr" placeholder="例如 Authorization" @input="sync" />
          </label>
          <label>
            <span>鉴权 Header 值（可选）</span>
            <el-input v-model="route.authHeaderValue" type="password" showPassword dir="ltr" autocomplete="off" @input="sync" />
          </label>
        </div>

        <div class="workflowActions">
          <el-button :icon="IconUpload" @click="openFile(index)">导入 ComfyUI 工作流 JSON</el-button>
          <el-button :icon="IconWand" @click="autoMap(index)">自动识别输入映射</el-button>
        </div>

        <label class="jsonField">
          <span>工作流 JSON</span>
          <el-input v-model="route.workflow" type="textarea" dir="ltr" :rows="7" resize="vertical" placeholder="支持 ComfyUI 界面导出的工作流 JSON；导入时会自动转换为 API prompt" @input="sync" />
        </label>
        <label class="jsonField">
          <span>输入映射 JSON</span>
          <el-input v-model="route.mapping" type="textarea" dir="ltr" :rows="5" resize="vertical" placeholder='例如 {"prompt":["6","text"],"images":[["10","image"]],"seed":["12","seed"]}' @input="sync" />
        </label>
      </el-card>
    </div>

    <el-empty v-if="!routes.length" description="尚未添加工作流，请选择文生图、图像编辑或视频模型" :imageSize="72" />
    <input ref="fileInput" type="file" accept=".json,application/json" hidden @change="importFile" />
  </section>
</template>

<script setup lang="ts">
import { ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { IconPlus, IconTrash, IconUpload, IconWand } from "@tabler/icons-vue";
import type { MediaProviderModel } from "@solodrama/provider-web/types";
import { inferComfyMapping, parseComfyJsonWithReport } from "@/lib/comfyWorkflow";

type RouteKind = "textToImage" | "imageEdit" | "video";
type RouteDraft = {
  key: string;
  id: string;
  label: string;
  kind: RouteKind;
  workflow: string;
  mapping: string;
  baseUrl: string;
  authHeaderName: string;
  authHeaderValue: string;
};
const props = defineProps<{ cloud?: boolean; defaultValue?: string }>();
const config = defineModel<Record<string, unknown>>("config", { default: () => ({}) });
const models = defineModel<MediaProviderModel[]>("models", { default: () => [] });
const routes = ref<RouteDraft[]>([]);
const fileInput = ref<HTMLInputElement>();
const importIndex = ref<number>();
let syncingFromConfig = false;

function fromConfig(value: unknown): RouteDraft[] {
  if (typeof value !== "string" || !value.trim()) return [];
  try {
    const parsed = JSON.parse(value);
    if (!Array.isArray(parsed)) return [];
    return parsed.flatMap(item => {
      if (!item || typeof item !== "object" || Array.isArray(item)) return [];
      const route = item as Record<string, unknown>;
      const kind = route.kind;
      if (!["textToImage", "imageEdit", "video"].includes(String(kind))) return [];
      return [{
        key: crypto.randomUUID(),
        id: typeof route.id === "string" ? route.id : "",
        label: typeof route.label === "string" ? route.label : "",
        kind: kind as RouteKind,
        workflow: typeof route.workflow === "string" ? route.workflow : "",
        mapping: typeof route.mapping === "string" ? route.mapping : "",
        baseUrl: typeof route.baseUrl === "string" ? route.baseUrl : "",
        authHeaderName: typeof route.authHeaderName === "string" ? route.authHeaderName : "",
        authHeaderValue: typeof route.authHeaderValue === "string" ? route.authHeaderValue : "",
      }];
    });
  } catch {
    return [];
  }
}

watch(() => config.value.routes, value => {
  const current = serialize();
  const raw = typeof value === "string" && value.trim() ? value : props.defaultValue ?? "";
  if (raw && raw !== current) {
    syncingFromConfig = true;
    routes.value = fromConfig(raw);
    syncingFromConfig = false;
    if (!value && raw) config.value = { ...(config.value ?? {}), routes: raw };
    syncModels();
  } else if (!routes.value.length && raw) {
    routes.value = fromConfig(raw);
    syncModels();
  }
}, { immediate: true });

function addRoute(kind: RouteKind) {
  const index = routes.value.length + 1;
  const prefix = kind === "textToImage" ? "comfyTextToImage" : kind === "imageEdit" ? "comfyImageEdit" : "comfyVideo";
  routes.value.push({
    key: crypto.randomUUID(),
    id: `${prefix}${index}`,
    label: kind === "textToImage" ? `文生图工作流 ${index}` : kind === "imageEdit" ? `图像编辑工作流 ${index}` : `视频工作流 ${index}`,
    kind,
    workflow: "",
    mapping: kind === "video" ? `{\n  "prompt": [],\n  "images": [],\n  "duration": [],\n  "ratio": [],\n  "seed": [],\n  "prefix": []\n}` : "{}",
    baseUrl: "",
    authHeaderName: "",
    authHeaderValue: "",
  });
  sync();
}

function removeRoute(index: number) {
  routes.value.splice(index, 1);
  sync();
}

function serialize() {
  return JSON.stringify(routes.value.map(({ key, ...route }) => ({
    id: route.id.trim(),
    label: route.label.trim(),
    kind: route.kind,
    workflow: route.workflow,
    mapping: route.mapping,
    ...(route.baseUrl.trim() ? { baseUrl: route.baseUrl.trim() } : {}),
    ...(route.authHeaderName.trim() ? { authHeaderName: route.authHeaderName.trim() } : {}),
    ...(route.authHeaderValue.trim() ? { authHeaderValue: route.authHeaderValue.trim() } : {}),
  })), null, 2);
}

function sync() {
  if (syncingFromConfig) return;
  config.value = { ...(config.value ?? {}), routes: serialize() };
  syncModels();
}

function syncModels() {
  const previous = new Map(models.value.map(model => [model.id, model]));
  models.value = routes.value.filter(route => route.id.trim() && route.label.trim()).map(route => {
    const existing = previous.get(route.id.trim());
    const image = route.kind !== "video";
    return {
      ...(existing ?? {}),
      id: route.id.trim(),
      label: route.label.trim(),
      type: image ? "image" : "video",
      mode: route.kind === "textToImage" ? ["text"]
        : route.kind === "imageEdit" ? ["singleImage", "multiReference"]
        : ["text", "singleImage", "endFrameOptional", ["imageReference:6"]],
      ...(image ? {
        imageSizes: existing?.imageSizes ?? ["1024x1024", "1280x720", "720x1280", "1536x1024", "1024x1536"],
        imageRatios: existing?.imageRatios ?? ["1:1", "4:3", "3:4", "16:9", "9:16", "3:2", "2:3"],
      } : {
        audio: existing?.audio ?? "optional",
        imageRatios: existing?.imageRatios ?? ["adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"],
        durationResolutionMap: existing?.durationResolutionMap ?? [{ duration: [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30], resolution: ["480P", "768P", "1080P", "2K", "4K"] }],
      }),
      ...(props.cloud ? { rules: [{ type: "switch", field: "allowUnknownCostSubmit", title: "云端费用未知时仍允许提交", value: false }] } : {}),
    } as MediaProviderModel;
  });
}

function openFile(index: number) {
  importIndex.value = index;
  fileInput.value?.click();
}

async function importFile(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  const route = importIndex.value === undefined ? undefined : routes.value[importIndex.value];
  if (!file || !route) return;
  if (file.size > 5 * 1024 * 1024) return ElMessage.error("JSON 文件不能超过 5 MB");
  try {
    const converted = parseComfyJsonWithReport(await file.text());
    route.workflow = JSON.stringify(converted.workflow, null, 2);
    sync();
    if (converted.warnings.length) ElMessage.warning({ message: `工作流已转换，但有 ${converted.warnings.length} 项需要检查：${converted.warnings.slice(0, 3).join("；")}`, duration: 8000 });
    else ElMessage.success("ComfyUI 工作流已导入并转换，保存后生效");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "导入 JSON 失败");
  }
}

function autoMap(index: number) {
  const route = routes.value[index];
  if (!route?.workflow.trim()) return ElMessage.error("请先导入或填写 ComfyUI 工作流 JSON");
  try {
    const converted = parseComfyJsonWithReport(route.workflow);
    route.workflow = JSON.stringify(converted.workflow, null, 2);
    const mapping = inferComfyMapping(converted.workflow);
    if (!Object.keys(mapping).length) return ElMessage.error("没有识别到常用输入节点，请手动填写映射 JSON");
    route.mapping = JSON.stringify(mapping, null, 2);
    sync();
    ElMessage.success(converted.warnings.length ? `已生成输入映射；另有 ${converted.warnings.length} 项转换提示需要检查` : "已生成输入映射，请检查节点 ID 和参考图顺序");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "自动识别映射失败");
  }
}
</script>

<style lang="scss" scoped>
.comfyRoutes {
  display: grid;
  gap: 12px;
  margin-bottom: 18px;
  padding: 14px;
  border: 1px solid var(--el-color-primary-light-7);
  border-radius: calc(var(--ui-radius) * 1.5);
  background: color-mix(in srgb, var(--el-color-primary-light-9) 64%, var(--el-bg-color-overlay));

  .routesHeader { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
  .routesHeader strong { font-size: 13px; }
  .routesHeader p { margin: 4px 0 0; color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.6; }
  .routeList { display: grid; gap: 12px; }
  .routeCard :deep(.el-card__header) { padding: 10px 12px; }
  .routeCard :deep(.el-card__body) { display: grid; gap: 12px; }
  .routeTitle { display: grid; grid-template-columns: minmax(0, 1fr) 150px auto; align-items: center; gap: 8px; }
  .routeGrid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
  .routeGrid label, .jsonField { display: grid; gap: 6px; min-width: 0; }
  .routeGrid span, .jsonField > span { color: var(--el-text-color-regular); font-size: 12px; font-weight: 500; }
  .workflowActions { display: flex; flex-wrap: wrap; gap: 8px; }
}
@media (max-width: 640px) {
  .comfyRoutes .routesHeader { flex-direction: column; }
  .comfyRoutes .routeTitle, .comfyRoutes .routeGrid { grid-template-columns: 1fr; }
}
</style>
