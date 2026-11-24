<template>
  <el-dialog v-model="visible" title="确定项目规格" width="min(760px, 94vw)" appendToBody :closeOnClickModal="false" destroyOnClose>
    <div class="projectSetup">
      <div class="setupIntro">
        <div class="introMark"><icon-adjustments-horizontal :size="22" /></div>
        <div>
          <strong>画幅、画风和题材规格会写入项目配置</strong>
          <p>之后创建的图片、视频、字幕、封面和流水线默认继承这些值；节点内仍可单独覆盖。</p>
        </div>
      </div>
      <div class="pathLine" title="工作目录"><icon-folder :size="15" /><code>{{ directory }}</code></div>
      <el-form class="projectForm" labelPosition="top" @submit.prevent>
        <div class="formGrid twoColumns">
          <el-form-item label="项目名称">
            <el-input v-model="name" maxlength="100" placeholder="SoloDrama 项目" />
          </el-form-item>
          <el-form-item label="默认画布帧率">
            <el-select v-model="fps" aria-label="默认画布帧率">
              <el-option :value="24" label="24 fps" />
              <el-option :value="25" label="25 fps" />
              <el-option :value="30" label="30 fps" />
              <el-option :value="60" label="60 fps" />
            </el-select>
          </el-form-item>
        </div>
        <el-form-item label="画幅">
          <el-radio-group v-model="aspectRatio" class="aspectOptions" aria-label="项目画幅">
            <el-radio-button v-for="item in aspectOptions" :key="item.value" :value="item.value">
              <span class="aspectLabel"><span class="aspectShape" :style="aspectStyle(item.value)" />{{ item.label }}</span>
            </el-radio-button>
          </el-radio-group>
        </el-form-item>
        <div class="formGrid twoColumns">
          <el-form-item label="交付分辨率">
            <el-select v-model="resolution" aria-label="交付分辨率">
              <el-option v-for="item in resolutionOptions" :key="item" :value="item" :label="item" />
            </el-select>
          </el-form-item>
          <el-form-item label="实际尺寸">
            <el-input :modelValue="`${dimensions.width} × ${dimensions.height}`" readonly />
          </el-form-item>
        </div>
        <el-form-item label="项目画风">
          <styleSelect v-model="styleKey" class="projectStyle" placeholder="选择全项目统一画风" teleported />
        </el-form-item>
        <el-form-item label="短剧台词语言">
          <el-select v-model="language" aria-label="短剧台词语言">
            <el-option v-for="item in projectLanguageOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="导演 Skill">
          <el-select v-model="directorSkill" filterable clearable :loading="loadingSkills" placeholder="可选；用于提示词增强和工作台导演约束">
            <el-option v-for="skill in skills" :key="skill.name" :label="skill.displayName || skill.name" :value="skill.name">
              <div class="skillOption"><strong>{{ skill.displayName || skill.name }}</strong><span>{{ skill.description }}</span></div>
            </el-option>
          </el-select>
        </el-form-item>
        <div class="formGrid threeColumns">
          <el-form-item label="集数">
            <el-input-number v-model="episodeCount" :min="1" :max="999" controls-position="right" />
          </el-form-item>
          <el-form-item label="单集目标时长">
            <el-input-number v-model="episodeSeconds" :min="10" :max="1800" :step="5" controls-position="right" />
          </el-form-item>
          <el-form-item label="单集时长单位"><el-input modelValue="秒" readonly /></el-form-item>
        </div>
        <el-divider contentPosition="left">默认配音</el-divider>
        <div class="formGrid twoColumns">
          <el-form-item label="默认音色"><el-input v-model="ttsVoice" placeholder="default" /></el-form-item>
          <el-form-item label="语速倍率"><el-input-number v-model="ttsSpeed" :min="0.25" :max="4" :step="0.05" controls-position="right" /></el-form-item>
        </div>
      </el-form>
    </div>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" @click="submit">建立项目</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import axios from "axios";
import { computed, ref, watch } from "vue";
import { ElButton, ElDialog, ElDivider, ElForm, ElFormItem, ElInput, ElInputNumber, ElOption, ElRadioButton, ElRadioGroup, ElSelect } from "element-plus";
import { IconAdjustmentsHorizontal, IconFolder } from "@tabler/icons-vue";
import styleSelect from "@solodrama/node-shared/styleSelect";
import { dimensionsFor, projectLanguageOptions, type ProjectLanguage } from "@solodrama/node-shared/projectSettings";
import { styleByKey } from "@solodrama/node-shared/styleLibrary";
import type { ProjectSetupValue } from "@/lib/projectDefaults";

const visible = defineModel<boolean>({ default: false });
const props = defineProps<{ directory: string; suggestedName?: string; settings?: import("@solodrama/node-shared/projectSettings").SoloDramaProjectSettings }>();
const emit = defineEmits<{ confirm: [value: ProjectSetupValue] }>();
const name = ref("");
const aspectRatio = ref("9:16");
const resolution = ref("1080P");
const styleKey = ref("");
const language = ref<ProjectLanguage>("zh-CN");
const directorSkill = ref("");
const skills = ref<{ name: string; displayName?: string; description?: string; enabled?: boolean }[]>([]);
const loadingSkills = ref(false);
const episodeCount = ref(30);
const episodeSeconds = ref(90);
const fps = ref(30);
const ttsVoice = ref("default");
const ttsSpeed = ref(1);
const aspectOptions = [
  { label: "竖屏 9:16", value: "9:16" },
  { label: "竖版 3:4", value: "3:4" },
  { label: "横屏 16:9", value: "16:9" },
  { label: "方形 1:1", value: "1:1" },
];
const resolutionOptions = ["720P", "1080P", "2K", "4K"];
const dimensions = computed(() => dimensionsFor(aspectRatio.value, resolution.value));

watch(visible, value => {
  if (!value) return;
  name.value = props.settings?.name || props.suggestedName?.trim() || props.directory.split(/[\\/]/).filter(Boolean).at(-1) || "SoloDrama";
  if (props.settings) {
    aspectRatio.value = props.settings.aspectRatio;
    resolution.value = props.settings.resolution;
    styleKey.value = props.settings.styleKey;
    language.value = props.settings.language ?? props.settings.tts.language as ProjectLanguage;
    directorSkill.value = props.settings.directorSkill;
    episodeCount.value = props.settings.episodeCount;
    episodeSeconds.value = props.settings.episodeSeconds;
    fps.value = props.settings.fps;
    ttsVoice.value = props.settings.tts.voice;
    ttsSpeed.value = props.settings.tts.speed;
  } else {
    aspectRatio.value = "9:16";
    resolution.value = "1080P";
    styleKey.value = "";
    language.value = "zh-CN";
    directorSkill.value = "";
    episodeCount.value = 30;
    episodeSeconds.value = 90;
    fps.value = 30;
    ttsVoice.value = "default";
    ttsSpeed.value = 1;
  }
  if (!skills.value.length) void loadSkills();
}, { immediate: true });

async function loadSkills() {
  loadingSkills.value = true;
  try {
    const { data } = await axios.get<{ code: number; data: typeof skills.value; message?: string }>("/api/skills/get", { headers: { "x-solodrama-workspace": "1" } });
    if (data.code === 200 && Array.isArray(data.data)) skills.value = data.data.filter(skill => skill.enabled !== false);
  } finally {
    loadingSkills.value = false;
  }
}

function aspectStyle(value: string) {
  const [width = 1, height = 1] = value.split(":").map(Number);
  return { width: `${18 * Math.min(width / height, 1)}px`, height: `${18 * Math.min(height / width, 1)}px` };
}

function submit() {
  const style = styleByKey.get(styleKey.value);
  const size = dimensions.value;
  emit("confirm", {
    name: name.value.trim() || "SoloDrama",
    aspectRatio: aspectRatio.value,
    resolution: resolution.value,
    width: size.width,
    height: size.height,
    styleKey: style?.key ?? "",
    stylePrompt: style?.promptZh ?? "",
    language: language.value,
    directorSkill: directorSkill.value,
    episodeCount: episodeCount.value,
    episodeSeconds: episodeSeconds.value,
    fps: fps.value,
    tts: { voice: ttsVoice.value.trim() || "default", speed: ttsSpeed.value },
  });
  visible.value = false;
}
</script>

<style scoped lang="scss">
.projectSetup { display: flex; flex-direction: column; gap: 16px; }
.setupIntro {
  display: flex; gap: 13px; padding: 15px; border: 1px solid var(--el-border-color-lighter); border-radius: 14px;
  background: linear-gradient(135deg, var(--el-fill-color-lighter), color-mix(in srgb, var(--el-color-primary-light-9) 55%, var(--el-bg-color)));
  .introMark { display: grid; place-items: center; flex: 0 0 42px; height: 42px; border-radius: 12px; color: var(--el-color-primary); background: var(--el-color-primary-light-9); }
  strong { font-size: 14px; }
  p { margin: 5px 0 0; color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.7; }
}
.pathLine { display: flex; align-items: center; gap: 8px; min-width: 0; color: var(--el-text-color-secondary); code { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } }
.projectForm {
  :deep(.el-form-item) { margin-bottom: 16px; }
  :deep(.el-select), :deep(.el-input-number) { width: 100%; }
  .formGrid { display: grid; gap: 14px; }
  .twoColumns { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .threeColumns { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .aspectOptions { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); width: 100%; gap: 8px; }
  .aspectOptions :deep(.el-radio-button__inner) { width: 100%; padding: 10px 8px; }
  .aspectLabel { display: inline-flex; align-items: center; justify-content: center; gap: 8px; }
  .aspectShape { display: inline-block; flex: 0 0 auto; border: 1px solid currentColor; border-radius: 2px; }
  .projectStyle { width: 100%; }
  .skillOption { display: grid; gap: 2px; padding: 3px 0; strong { font-size: 12px; } span { overflow: hidden; max-width: 560px; color: var(--el-text-color-secondary); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; } }
}
@media (max-width: 620px) {
  .projectForm {
    .twoColumns, .threeColumns { grid-template-columns: 1fr; }
    .aspectOptions { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  }
}
</style>
