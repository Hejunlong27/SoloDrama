<template>
  <div class="providerList">
    <div class="itemList">
      <el-card v-for="item in providerCards" :key="item.key" class="providerItem" shadow="never">
        <div class="providerHeader">
          <div v-if="item.icon" class="providerMark" aria-hidden="true">
            <img class="providerLogo" :src="item.icon" alt="" />
          </div>
          <div class="providerInfo">
            <div class="providerHeading">
              <el-text class="providerName" tag="strong">{{ item.label }}</el-text>
            </div>
            <el-text class="providerId" size="small" type="info" :title="item.id">{{ item.id }}</el-text>
          </div>
        </div>
        <div class="providerFooter">
          <div class="providerMeta">
            <el-tag v-if="item.version" size="small" type="info" effect="plain">v{{ item.version }}</el-tag>
            <el-text size="small" type="info">{{ item.configured ? `${item.models.length} 个模型` : '未配置' }}</el-text>
          </div>
          <el-space class="itemActions" wrap>
            <template v-if="item.configured">
              <el-button text :icon="IconEdit" :disabled="!!deletingId" @click="openCustomProvider(item.provider!)">编辑</el-button>
              <el-popconfirm title="确定删除此供应商及其模型？" confirmButtonText="删除" cancelButtonText="取消" @confirm="deleteProvider(item.id)">
                <template #reference><el-button text type="danger" :icon="IconTrash" :loading="deletingId === item.id" :disabled="!!deletingId">删除</el-button></template>
              </el-popconfirm>
            </template>
            <el-button v-else text type="primary" :icon="IconPlus" @click="openProvider(item.id)">配置</el-button>
          </el-space>
        </div>
      </el-card>
    </div>
    <div class="providerActions">
      <el-button class="addButton" :icon="IconPlus" @click="openCustomProvider()">添加供应商</el-button>
      <el-button class="addButton" :icon="IconServer" @click="openLocalProvider()">接入本地模型</el-button>
    </div>
    <component :is="addCustomProviderDialog" v-model="customProviderDialogVisible" :provider="editingProvider" :preset="customProviderPreset" />
  </div>
</template>

<script setup lang="ts">
import { computed, defineAsyncComponent, ref, shallowRef, type Component } from "vue";
import { ElMessage } from "element-plus";
import { customProviders, saveSettings, type CustomProvider } from "@/stores/settings";
import { IconPlus, IconEdit, IconTrash, IconServer } from "@tabler/icons-vue";
import { languageProviders } from "@solodrama/providers";

defineProps<{ visible?: boolean }>();
type ProviderCard = {
  key: string;
  id: string;
  label: string;
  icon?: string;
  version?: string;
  configured: boolean;
  models: readonly unknown[];
  provider?: CustomProvider;
};
const addCustomProviderDialog = shallowRef<Component>();
const customProviderDialogVisible = ref(false);
const editingProvider = ref<CustomProvider>();
const customProviderPreset = ref<{ id?: string; label?: string; website?: string; apiUrl?: string; icon?: string; version?: string }>();
const deletingId = ref("");
const providerWebsites: Record<string, string> = {
  opencodeGo: "https://opencode.ai/go",
  commandCode: "https://commandcode.ai",
  deepSeek: "https://platform.deepseek.com",
};
const providerCards = computed<ProviderCard[]>(() => {
  const configured = customProviders.value;
  const builtins = languageProviders.map(template => {
    const saved = configured.find(item => item.id.toLowerCase() === template.id.toLowerCase());
    return saved
      ? { key: saved.id, id: saved.id, label: saved.label, icon: saved.icon, version: template.version ?? saved.version, configured: true, models: saved.models, provider: saved }
      : { key: template.id, id: template.id, label: template.label, icon: template.icon, version: template.version, configured: false, models: template.models };
  });
  const custom = configured.filter(item => !languageProviders.some(template => template.id.toLowerCase() === item.id.toLowerCase()))
    .map(item => ({ key: item.id, id: item.id, label: item.label, icon: item.icon, version: item.version, configured: true, models: item.models, provider: item }));
  return [...builtins, ...custom];
});

function openProvider(providerId?: string) {
  const template = languageProviders.find(item => item.id === providerId);
  if (!template) return openCustomProvider();
  openCustomProvider(undefined, {
    id: template.id,
    label: template.label,
    website: providerWebsites[template.id],
    apiUrl: template.apiUrl,
    icon: template.icon,
    version: template.version,
  });
}

function openCustomProvider(provider?: CustomProvider, preset?: typeof customProviderPreset.value) {
  addCustomProviderDialog.value ??= defineAsyncComponent(() => import("./addCustomProviderDialog.vue"));
  editingProvider.value = provider;
  customProviderPreset.value = preset;
  customProviderDialogVisible.value = true;
}

function openLocalProvider() {
  addCustomProviderDialog.value ??= defineAsyncComponent(() => import("./addCustomProviderDialog.vue"));
  editingProvider.value = undefined;
  customProviderPreset.value = {
    id: "localModel",
    label: "本地 OpenAI 兼容模型",
    apiUrl: "http://127.0.0.1:11434/v1",
  };
  customProviderDialogVisible.value = true;
}

async function deleteProvider(id: string) {
  if (deletingId.value) return;
  deletingId.value = id;
  try {
    await saveSettings(settings => {
      const current = settings.customProviders;
      if (!Array.isArray(current)) throw new Error("配置格式错误");
      return { customProviders: current.filter(item => item?.id !== id) };
    });
  } catch { ElMessage.error("删除失败，请重试"); }
  finally { deletingId.value = ""; }
}
</script>

<style lang="scss" scoped src="../../providerList.scss"></style>
