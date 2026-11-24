<template>
  <el-button v-if="!hideTrigger" class="workspaceButton" text :icon="IconFolder" :loading="selecting" :disabled="loading || disabled" :title="selectedDirectory || '选择工作目录'" aria-label="选择工作目录" @click="chooseDirectory">
    <span class="directoryName">{{ selectedDirectory ? selectedDirectory.split(/[\\/]/).filter(Boolean).at(-1) || selectedDirectory : '工作目录' }}</span>
    <component :is="dialogVisible ? IconChevronUp : IconChevronDown" :size="14" aria-hidden="true" />
  </el-button>
  <el-dialog v-model="dialogVisible" :title="external ? '选择本机已有目录' : !publicWeb && isLocalMobile ? '选择手机工作目录' : '选择服务器工作目录'" width="min(680px, 92vw)" appendToBody :closeOnClickModal="!editing" :closeOnPressEscape="!editing" :showClose="!editing" @close="finishSelection?.(null)">
    <div class="workspaceBrowser">
      <div class="directoryHeader">
        <el-button :icon="IconArrowLeft" circle :disabled="loading || editing || !listing?.parent" aria-label="上一级目录" @click="loadDirectory(listing?.parent ?? '')" />
        <el-text class="directoryPath" truncated :title="listing?.absolutePath">{{ external ? '本机目录' : !publicWeb && isLocalMobile ? '手机工作区' : '服务器工作区' }}{{ listing?.path ? ` / ${listing.path}` : '' }}</el-text>
        <el-button v-if="!external" :icon="IconFolderPlus" :disabled="loading || editing || !listing || !!browseError" @click="manageEntry('mkdir')">新建文件夹</el-button>
      </div>
      <div v-if="external" class="pathJump">
        <el-input v-model="pathInput" dir="ltr" placeholder="可直接输入已有目录的绝对路径" aria-label="本机目录路径" @keyup.enter="goPath" />
        <el-button :disabled="loading || !pathInput.trim()" @click="goPath">前往</el-button>
      </div>
      <el-alert v-if="browseError" :title="browseError" type="error" :closable="false" />
      <el-table v-loading="loading" :data="listing?.entries ?? []" height="300" emptyText="当前目录为空">
        <el-table-column label="名称" minWidth="160">
          <template #default="{ row }">
            <el-button v-if="row.type === 'directory'" class="entryName" link :icon="IconFolder" :title="row.name" :disabled="loading || editing" @click="loadDirectory(external ? row.path : [listing?.path, row.path].filter(Boolean).join('/'))">{{ row.name }}</el-button>
            <span v-else class="fileName" :title="row.name"><icon-file :size="18" aria-hidden="true" /><span>{{ row.name }}</span></span>
          </template>
        </el-table-column>
        <el-table-column v-if="!external" label="操作" width="130" align="right">
          <template #default="{ row }">
            <el-button link :disabled="loading || editing" :aria-label="`重命名 ${row.name}`" @click="manageEntry('rename', row as WorkspaceEntry)">重命名</el-button>
            <el-button link type="danger" :disabled="loading || editing" :aria-label="`删除 ${row.name}`" @click="manageEntry('remove', row as WorkspaceEntry)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
    <template #footer>
      <el-button :disabled="editing" @click="dialogVisible = false">取消</el-button>
      <el-button type="primary" :disabled="loading || editing || !listing || !!browseError" @click="confirmDirectory">选择此目录</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import axios from "axios";
import { translate } from "@solodrama/i18n/vue";
import { onBeforeUnmount, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { IconFolder, IconFolderPlus, IconFile, IconChevronDown, IconChevronUp, IconArrowLeft } from "@tabler/icons-vue";
import useWorkspaceFiles from "@/lib/workspaceFiles";
import { actualPlatform, isLocalMobile } from "@/lib/platform";
import { publicWeb } from "@/stores/multiTenant";

type WorkspaceEntry = { name: string; path: string; type: "file" | "directory" };
type DirectoryListing = {
  path: string;
  absolutePath: string;
  parent: string | null;
  entries: WorkspaceEntry[];
};

const selectedDirectory = defineModel<string>({ default: "" });
const props = defineProps<{ disabled?: boolean; hideTrigger?: boolean; external?: boolean }>();
const dialogVisible = ref(false);
const selecting = ref(false);
const loading = ref(false);
const editing = ref(false);
const listing = ref<DirectoryListing>();
const browseError = ref("");
const pathInput = ref("");
let finishSelection: ((directory: string | null) => void) | undefined;
onBeforeUnmount(() => finishSelection?.(null));
defineExpose({ chooseDirectory, selecting });

async function chooseDirectory(): Promise<string | null> {
  if (selecting.value || loading.value || props.disabled) return null;
  selecting.value = true;
  try {
    const native = await chooseNativeDirectory();
    if (native.supported) {
      if (native.directory) selectedDirectory.value = native.directory;
      return native.directory;
    }
    dialogVisible.value = true;
    void loadDirectory(props.external ? selectedDirectory.value || "" : "");
    return await new Promise<string | null>(resolve => { finishSelection = resolve; });
  } catch (error) {
    ElMessage.error(axios.isAxiosError<{ message?: string }>(error) ? error.response?.data?.message || "无法打开文件夹选择器，请重试" : "无法打开文件夹选择器，请重试");
    return null;
  }
  finally { selecting.value = false; finishSelection = undefined; }
}

async function chooseNativeDirectory(): Promise<{ supported: boolean; directory: string | null }> {
  if (publicWeb.value) return { supported: false, directory: null };
  if (actualPlatform.isLocalDesktop) {
    try {
      const { data } = await axios.post<{ data: { directory: string | null } }>("/api/desktop/selectDirectory", null, { headers: { "x-solodrama-desktop": "1" } });
      return { supported: true, directory: data.data.directory };
    } catch { /* 桌面宿主不可用时继续尝试独立 server 的系统选择器。 */ }
  }
  try {
    const { data } = await axios.post<{ code: number; data: { native: boolean; directory: string | null } }>("/api/workspaces/selectDirectory", null, { headers: { "x-solodrama-workspace": "1" } });
    return { supported: data.data.native === true, directory: data.data.directory };
  } catch {
    return { supported: false, directory: null };
  }
}

async function loadDirectory(path: string) {
  if (loading.value) return;
  loading.value = true;
  browseError.value = "";
  try {
    if (props.external) {
      const { data } = await axios.get<{ code: number; data: { path: string; absolutePath: string; parent: string | null; directories: { name: string; path: string }[] }; message?: string }>("/api/workspaces/browseLocal", { params: { path }, headers: { "x-solodrama-workspace": "1" } });
      if (data.code !== 200 || !data.data) throw new Error(data.message || "读取目录失败");
      listing.value = {
        path: data.data.path,
        absolutePath: data.data.absolutePath,
        parent: data.data.parent,
        entries: data.data.directories.map(item => ({ name: item.name, path: item.path, type: "directory" as const })),
      };
      pathInput.value = data.data.absolutePath;
      return;
    }
    const { data } = await axios.get<{ code: number; data: Omit<DirectoryListing, "entries">; message: string }>("/api/workspaces/list", { params: { path } });
    if (data.code !== 200) throw new Error(data.message);
    listing.value = { ...data.data, entries: [] };
    const { entries } = await useWorkspaceFiles(data.data.absolutePath).list();
    listing.value = { ...data.data, entries: entries.sort((a, b) => Number(b.type === "directory") - Number(a.type === "directory") || a.name.localeCompare(b.name, "zh-CN", { numeric: true })) };
  } catch (err) {
    browseError.value = axios.isAxiosError<{ message?: string }>(err) ? err.response?.data?.message || "读取目录失败，请重试" : "读取目录失败，请重试";
  } finally { loading.value = false; }
}

function goPath() {
  const value = pathInput.value.trim();
  if (value) void loadDirectory(value);
}

async function manageEntry(action: "mkdir" | "rename" | "remove", entry?: WorkspaceEntry) {
  const directory = listing.value;
  if (!directory || loading.value || editing.value || browseError.value || (action !== "mkdir" && !entry)) return;
  const files = useWorkspaceFiles(directory.absolutePath);
  editing.value = true;
  try {
    if (action === "remove" && entry) {
      await ElMessageBox.confirm(entry.type === "directory"
        ? `确定删除文件夹“${entry.name}”及其全部内容？此操作无法撤销。`
        : `确定删除文件“${entry.name}”？此操作无法撤销。`, "删除确认", {
        type: "warning", confirmButtonText: "删除", cancelButtonText: "取消",
      });
      await files.remove(entry.path, entry.type === "directory");
    } else {
      const { value } = await ElMessageBox.prompt("请输入名称", action === "mkdir" ? "新建文件夹" : "重命名", {
        inputValue: entry?.name ?? "新建文件夹",
        inputValidator: value => {
          const name = value?.trim();
          return !!name && name !== "." && name !== ".." && !/[\\/:*?"<>|\u0000-\u001f]/.test(name) || translate("请输入有效的单个文件或文件夹名称");
        },
        confirmButtonText: action === "mkdir" ? "创建" : "保存", cancelButtonText: "取消",
      });
      const name = value.trim();
      if (action === "mkdir") await files.mkdir(name);
      else if (entry && name !== entry.name) await files.rename(entry.path, name);
      else return;
    }
    if (entry?.type === "directory") {
      const path = `${directory.absolutePath.replaceAll("\\", "/").replace(/\/$/, "")}/${entry.path}`;
      const selected = selectedDirectory.value.replaceAll("\\", "/").replace(/\/$/, "");
      if (selected === path || selected.startsWith(`${path}/`)) selectedDirectory.value = "";
    }
    await loadDirectory(directory.path);
  } catch (error) {
    if (error !== "cancel" && error !== "close") ElMessage.error(axios.isAxiosError<{ message?: string }>(error)
      ? error.response?.data?.message || "操作失败，请重试" : error instanceof Error ? error.message : "操作失败，请重试");
  } finally { editing.value = false; }
}

function confirmDirectory() {
  if (loading.value || editing.value || !listing.value || browseError.value) return;
  selectedDirectory.value = listing.value.absolutePath;
  finishSelection?.(listing.value.absolutePath);
  dialogVisible.value = false;
}
</script>

<style lang="scss" scoped>
.workspaceButton {
  max-width: min(340px, 100%);

  :deep(> span) { min-width: 0; gap: 6px; }
  .directoryName { overflow: hidden; text-overflow: ellipsis; }
  svg { flex-shrink: 0; }
}

.workspaceBrowser {
  display: flex;
  flex-direction: column;
  gap: 12px;

  .directoryHeader {
    display: flex;
    align-items: center;
    gap: 12px;

    .directoryPath { flex: 1; min-width: 0; }
    .el-button { flex-shrink: 0; }
  }

  .pathJump {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 8px;
  }

  .entryName {
    max-width: 100%;
    color: var(--el-text-color-regular);
    :deep(.el-icon) { font-size: 18px; color: var(--el-text-color-secondary); }
    :deep(> span) { overflow: hidden; text-overflow: ellipsis; }
  }

  .fileName {
    display: flex;
    align-items: center;
    gap: 6px;
    svg { flex-shrink: 0; color: var(--el-text-color-secondary); }
    span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  }
}
</style>
