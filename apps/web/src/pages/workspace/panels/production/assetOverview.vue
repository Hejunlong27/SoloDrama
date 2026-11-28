<template>
  <div class="assetOverview">
    <header class="assetHeader">
      <div><p class="eyebrow">CAST & LOCATIONS</p><h2>角色与场景</h2><p>在左侧选择资产，右侧持续编辑同一实体。</p></div>
      <div class="headerActions"><el-button size="small" @click="emit('globalStyle')">全局画风</el-button><el-button size="small" type="primary" @click="emit('add', activeKind)">新增{{ kindLabel(activeKind) }}</el-button></div>
    </header>
    <div class="assetToolbar">
      <button v-for="item in filters" :key="item.kind" type="button" :class="{ active: activeKind === item.kind }" @click="activeKind = item.kind">{{ item.label }}<span>{{ item.count }}</span></button>
    </div>
    <el-scrollbar class="assetList">
      <button v-for="card in cards" :key="card.id" type="button" class="assetCard" :class="{ active: card.id === selectedId }" @click="emit('design', card.kind, card.id)">
        <div class="assetVisual" :class="card.kind">
          <img v-if="card.images.length" :src="card.images[0]" :alt="card.name" />
          <component v-else :is="fallbackIcon(card.kind)" :size="22" />
        </div>
        <div class="assetCaption">
          <div class="assetName"><strong>{{ card.name }}</strong><el-tag size="small" :type="card.confirmed ? 'success' : 'info'">{{ card.confirmed ? '已确认' : '草稿' }}</el-tag></div>
          <small>{{ card.kind === 'character' ? card.voice || '未绑定音色' : card.kind === 'location' ? card.timeOfDay || '场景设定' : '道具设定' }}</small>
        </div>
      </button>
      <button type="button" class="addCard" @click="emit('add', activeKind)"><icon-plus :size="18" /><span>添加{{ kindLabel(activeKind) }}</span></button>
      <el-empty v-if="!cards.length" description="当前分类还没有资产" :imageSize="54" />
    </el-scrollbar>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import type { ProductionDocument } from "@solodrama/production";
import { IconBox, IconBuilding, IconPhoto, IconPlus, IconUser } from "@tabler/icons-vue";
import { useProductionAssetUrls } from "./useProductionAssetUrls";

type AssetKind = "character" | "location" | "prop";
const props = defineProps<{ document: ProductionDocument; directory: string; selectedId?: string }>();
const emit = defineEmits<{ design: [kind: AssetKind, id: string]; add: [kind: AssetKind]; globalStyle: [] }>();
const activeKind = ref<AssetKind>("character");
const { assetUrls } = useProductionAssetUrls(() => props.directory, () => props.document.assets);
const filters = computed(() => [
  { kind: "character" as const, label: "角色", count: props.document.characters.length },
  { kind: "location" as const, label: "场景", count: props.document.locations.length },
  { kind: "prop" as const, label: "道具", count: props.document.props.length },
]);
const cards = computed(() => {
  if (activeKind.value === "character") return props.document.characters.map(item => ({
    id: item.id, kind: "character" as const, name: item.name, confirmed: item.confirmed,
    voice: [item.voice.voiceId, item.voice.providerId].filter(Boolean).join(" · "),
    images: item.referenceImages.map(reference => assetUrls.value[reference.assetId]).filter((url): url is string => !!url),
  }));
  if (activeKind.value === "location") return props.document.locations.map(item => ({
    id: item.id, kind: "location" as const, name: item.name, confirmed: item.confirmed, voice: "", timeOfDay: item.timeOfDay,
    images: item.referenceImages.map(reference => assetUrls.value[reference.assetId]).filter((url): url is string => !!url),
  }));
  return props.document.props.map(item => ({
    id: item.id, kind: "prop" as const, name: item.name, confirmed: item.confirmed, voice: "", timeOfDay: "",
    images: item.referenceImages.map(reference => assetUrls.value[reference.assetId]).filter((url): url is string => !!url),
  }));
});
function kindLabel(kind: AssetKind) { return { character: "角色", location: "场景", prop: "道具" }[kind]; }
function fallbackIcon(kind: AssetKind) { return kind === "character" ? IconUser : kind === "location" ? IconBuilding : IconBox; }
</script>

<style scoped lang="scss">
.assetOverview { display: grid; grid-template-rows: auto auto minmax(0, 1fr); gap: 12px; min-height: 720px; padding: 14px; border: 1px solid var(--el-border-color-light); border-radius: 16px; background: var(--el-bg-color-overlay); }
.assetHeader { display: grid; gap: 10px; }
.assetHeader .eyebrow { margin: 0; color: var(--el-color-primary); font-size: 9px; letter-spacing: .16em; }
.assetHeader h2 { margin: 3px 0 0; font-size: 19px; }
.assetHeader p { margin: 5px 0 0; color: var(--el-text-color-secondary); font-size: 11px; line-height: 1.55; }
.headerActions { display: flex; gap: 6px; }
.assetToolbar { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 5px; }
.assetToolbar button { display: flex; align-items: center; justify-content: center; gap: 5px; min-width: 0; padding: 8px 4px; border: 1px solid var(--el-border-color-light); border-radius: 9px; color: var(--el-text-color-secondary); background: var(--el-fill-color-lighter); cursor: pointer; }
.assetToolbar button.active { border-color: var(--el-color-primary); color: var(--el-color-primary); background: var(--el-color-primary-light-9); }
.assetToolbar button span { font-size: 10px; opacity: .72; }
.assetList { min-height: 0; }
.assetCard { display: grid; grid-template-columns: 76px minmax(0, 1fr); width: 100%; gap: 10px; margin-bottom: 8px; padding: 7px; border: 1px solid var(--el-border-color-lighter); border-radius: 11px; color: inherit; background: var(--el-fill-color-lighter); text-align: left; cursor: pointer; transition: border-color .16s ease, background .16s ease; }
.assetCard:hover, .assetCard.active { border-color: var(--el-color-primary-light-5); background: var(--el-color-primary-light-9); }
.assetVisual { display: grid; width: 76px; height: 76px; place-items: center; overflow: hidden; border-radius: 9px; color: var(--el-text-color-placeholder); background: repeating-conic-gradient(#18191e 0 25%, #111217 0 50%) 50% / 16px 16px; }
.assetVisual img { width: 100%; height: 100%; object-fit: cover; }
.assetCaption { display: grid; min-width: 0; align-content: center; gap: 7px; }
.assetName { display: flex; min-width: 0; align-items: center; justify-content: space-between; gap: 6px; }
.assetName strong { overflow: hidden; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.assetCaption small { overflow: hidden; color: var(--el-text-color-secondary); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.addCard { display: flex; width: 100%; min-height: 52px; align-items: center; justify-content: center; gap: 7px; border: 1px dashed var(--el-border-color); border-radius: 10px; color: var(--el-text-color-secondary); background: transparent; cursor: pointer; }
.addCard:hover { border-color: var(--el-color-primary); color: var(--el-color-primary); }
</style>
