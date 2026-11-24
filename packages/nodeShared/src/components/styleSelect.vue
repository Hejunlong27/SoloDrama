<template>
  <el-select
    v-model="styleKey"
    class="styleSelect"
    :disabled="disabled"
    :placeholder="placeholder"
    :size="size"
    :teleported="teleported"
    clearable
    filterable
    aria-label="画风">
    <template #label>
      <span v-if="selectedStyle" class="selectedStyle">{{ selectedStyle.title }}</span>
    </template>
    <el-option-group v-for="group in styleGroups" :key="group.key" :label="group.label">
      <el-option
        v-for="item in group.styles"
        :key="item.key"
        :label="`${item.title} ${item.nameEn} ${item.promptZh} ${item.key}`"
        :value="item.key">
        <div class="styleOption">
          <span class="styleTitle">{{ item.title }}</span>
          <span class="styleMeta">{{ item.nameEn }}</span>
          <code>{{ item.key }}</code>
        </div>
      </el-option>
    </el-option-group>
  </el-select>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { ElOption, ElOptionGroup, ElSelect } from "element-plus";
import { styleByKey, styleGroups } from "../styleLibrary";

withDefaults(defineProps<{
  disabled?: boolean;
  placeholder?: string;
  size?: "small" | "default" | "large";
  teleported?: boolean;
}>(), {
  disabled: false,
  placeholder: "画风",
  size: "small",
  teleported: true,
});

const styleKey = defineModel<string>({ default: "" });
const selectedStyle = computed(() => styleByKey.get(styleKey.value));
</script>

<style scoped lang="scss">
.styleSelect {
  width: 172px;
  flex-shrink: 0;

  .selectedStyle {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .styleOption {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: center;
    gap: 2px 10px;
    min-width: 240px;

    .styleTitle {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .styleMeta {
      grid-column: 1;
      overflow: hidden;
      color: var(--el-text-color-secondary);
      font-size: 11px;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    code {
      grid-column: 2;
      grid-row: 1 / span 2;
      color: var(--el-text-color-placeholder);
      font-size: 11px;
    }
  }
}
</style>
