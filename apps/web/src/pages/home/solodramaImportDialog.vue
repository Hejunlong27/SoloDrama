<template>
  <el-dialog v-model="visible" title="导入 SoloDrama 创作包" width="min(720px, calc(100vw - 32px))" alignCenter appendToBody destroyOnClose :closeOnClickModal="!busy" :closeOnPressEscape="!busy" :showClose="!busy" @closed="reset">
    <div class="importer">
      <div class="intro">
        <span class="introIcon"><icon-database-import :size="24" aria-hidden="true" /></span>
        <div>
          <strong>单向导入旧 SoloDrama 内容</strong>
          <p>支持旧项目目录，也支持只包含 <code>pack.json</code> 的创作包目录。源文件只读，导入结果会写入新的 SoloDrama 工作区。</p>
        </div>
      </div>

      <label class="field">
        <span>旧项目 / 创作包目录</span>
        <div class="pathField">
          <el-input v-model="source" dir="ltr" placeholder="可选择已有目录，也可直接输入绝对路径" />
          <el-button :icon="IconFolderOpen" :disabled="busy" @click="chooseSource">选择目录</el-button>
        </div>
      </label>

      <label class="field">
        <span>导入项目名称</span>
        <el-input v-model="name" maxlength="100" showWordLimit :disabled="busy" placeholder="默认使用创作包标题或源目录名" />
      </label>

      <el-alert v-if="error" :title="error" type="error" :closable="false" showIcon />
      <el-alert title="导入需要本机安装 Python 3。该依赖只用于一次性迁移，不会成为 Provider 或日常运行结构。" type="info" :closable="false" showIcon />

      <section v-if="report" class="report" aria-label="导入检查结果">
        <header>
          <span class="reportState"><icon-circle-check :size="18" aria-hidden="true" />{{ dryRun ? '试运行完成' : '导入完成' }}</span>
          <span>{{ report.nodeCount ?? 0 }} 个节点 · {{ report.edgeCount ?? 0 }} 条连线</span>
        </header>
        <div class="reportGrid">
          <span><b>{{ report.scripts ?? 0 }}</b> 文档</span>
          <span><b>{{ report.assetImages ?? 0 }}</b> 资产图</span>
          <span><b>{{ report.boards ?? 0 }}</b> 分镜图</span>
          <span><b>{{ report.videos ?? 0 }}</b> 成片</span>
          <span><b>{{ report.releaseVideos ?? 0 }}</b> 发行视频</span>
        </div>
        <div v-if="report.warnings?.length" class="reportIssues">
          <icon-alert-triangle :size="16" aria-hidden="true" />
          <span>{{ report.warnings.length }} 条警告</span>
        </div>
        <div v-if="report.missing?.length" class="reportIssues warning">
          <icon-alert-triangle :size="16" aria-hidden="true" />
          <span>{{ report.missing.length }} 项缺失，可在导入报告中查看</span>
        </div>
      </section>
    </div>

    <template #footer>
      <el-button :disabled="busy" @click="visible = false">取消</el-button>
      <el-button :loading="checking" :disabled="busy || !source" @click="run(true)">试运行</el-button>
      <el-button type="primary" :loading="importing" :disabled="busy || !source" @click="run(false)">开始导入</el-button>
    </template>
  </el-dialog>
  <workspacePicker ref="picker" hideTrigger external />
</template>

<script setup lang="ts">
import axios from "axios";
import { computed, ref } from "vue";
import { ElMessage } from "element-plus";
import { IconAlertTriangle, IconCircleCheck, IconDatabaseImport, IconFolderOpen } from "@tabler/icons-vue";
import workspacePicker from "./workspacePicker.vue";

type ImportReport = {
  scripts?: number;
  assetImages?: number;
  boards?: number;
  videos?: number;
  releaseVideos?: number;
  nodeCount?: number;
  edgeCount?: number;
  warnings?: unknown[];
  missing?: unknown[];
};
type ImportResult = { directory: string | null; name: string; title: string; report: ImportReport };
const visible = defineModel<boolean>({ default: false });
const emit = defineEmits<{ imported: [result: { directory: string; name: string }] }>();
const picker = ref<InstanceType<typeof workspacePicker>>();
const source = ref("");
const name = ref("");
const checking = ref(false);
const importing = ref(false);
const report = ref<ImportReport>();
const dryRun = ref(false);
const error = ref("");
const busy = computed(() => checking.value || importing.value);

async function chooseSource() {
  if (busy.value) return;
  const directory = await picker.value?.chooseDirectory();
  if (!directory) return;
  source.value = directory;
  error.value = "";
  report.value = undefined;
  if (!name.value.trim()) name.value = directory.split(/[\\/]/).filter(Boolean).at(-1) || "SoloDrama导入";
}

async function run(isDryRun: boolean) {
  if (busy.value || !source.value) return;
  error.value = "";
  if (isDryRun) checking.value = true;
  else importing.value = true;
  try {
    const { data } = await axios.post<{ code: number; data: ImportResult; message?: string }>("/api/workspaces/importSoloDrama", {
      source: source.value,
      name: name.value.trim() || undefined,
      dryRun: isDryRun,
    }, { headers: { "x-solodrama-workspace": "1" }, timeout: 600000 });
    if (data.code !== 200 || !data.data) throw new Error(data.message || "导入失败");
    report.value = data.data.report;
    dryRun.value = isDryRun;
    if (isDryRun) return ElMessage.success("试运行完成");
    if (!data.data.directory) throw new Error("导入结果缺少工作区路径");
    ElMessage.success("SoloDrama 创作包已导入");
    emit("imported", { directory: data.data.directory, name: data.data.name });
    visible.value = false;
  } catch (cause) {
    error.value = axios.isAxiosError<{ message?: string }>(cause)
      ? cause.response?.data?.message || cause.message : cause instanceof Error ? cause.message : "导入失败，请重试";
  } finally {
    checking.value = false;
    importing.value = false;
  }
}

function reset() {
  if (busy.value) return;
  source.value = "";
  name.value = "";
  report.value = undefined;
  error.value = "";
  dryRun.value = false;
}
</script>

<style lang="scss" scoped>
.importer { display: flex; flex-direction: column; gap: 18px; }
.intro {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: calc(var(--ui-radius) * 1.5);
  background: var(--el-fill-color-lighter);
  .introIcon { display: grid; place-items: center; width: 42px; height: 42px; flex-shrink: 0; border-radius: 12px; background: var(--el-color-primary-light-9); color: var(--el-color-primary); }
  strong { font-size: 14px; }
  p { margin: 4px 0 0; color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.7; }
  code { padding: 1px 4px; border-radius: 4px; background: var(--el-fill-color); }
}
.field {
  display: grid;
  gap: 7px;
  > span { color: var(--el-text-color-regular); font-size: 13px; font-weight: 500; }
  .pathField { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px; }
}
.report {
  border: 1px solid var(--el-color-success-light-7);
  border-radius: calc(var(--ui-radius) * 1.5);
  overflow: hidden;
  header { display: flex; justify-content: space-between; gap: 12px; padding: 11px 14px; background: var(--el-color-success-light-9); color: var(--el-color-success); font-size: 12px; }
  .reportState { display: inline-flex; align-items: center; gap: 6px; font-weight: 600; }
  .reportGrid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 1px; background: var(--el-border-color-lighter); }
  .reportGrid span { display: grid; gap: 2px; padding: 12px 10px; background: var(--el-bg-color-overlay); color: var(--el-text-color-secondary); font-size: 11px; text-align: center; }
  .reportGrid b { color: var(--el-text-color-primary); font-size: 18px; }
  .reportIssues { display: flex; align-items: center; gap: 7px; padding: 10px 14px; border-top: 1px solid var(--el-border-color-lighter); color: var(--el-color-warning); font-size: 12px; }
  .reportIssues.warning { color: var(--el-color-danger); }
}
@media (max-width: 620px) {
  .field .pathField { grid-template-columns: 1fr; }
  .report .reportGrid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
