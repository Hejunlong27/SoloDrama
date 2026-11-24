<template>
  <div class="promptEnhancer">
    <el-button text :icon="IconWand" :disabled="disabled" @click="open">提示词优化</el-button>
    <el-dialog v-model="visible" title="提示词优化" width="min(920px, 96vw)" appendToBody :closeOnClickModal="false">
      <div class="enhancerBody">
        <el-alert type="info" :closable="false" showIcon>
          H3 模式会先执行通用增强，再把结果交给对应的 H3 Prompt Skill 做第二次结构化增强。
        </el-alert>
        <el-form labelPosition="top">
          <div class="formGrid">
            <el-form-item label="增强模式">
              <el-radio-group v-model="enhanceMode" aria-label="提示词增强模式">
                <el-radio-button value="generic">通用增强</el-radio-button>
                <el-radio-button value="h3">{{ mediaType === "video" ? "H3 视频增强" : "H3 Image 增强" }}</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="文字模型">
              <el-select v-model="modelKey" filterable :loading="loadingModels" aria-label="提示词增强文字模型">
                <el-option-group v-for="group in modelGroups" :key="group.id" :label="group.label">
                  <el-option v-for="item in group.models" :key="getNodeModelKey(item)" :label="item.label" :value="getNodeModelKey(item)" />
                </el-option-group>
              </el-select>
            </el-form-item>
          </div>
          <el-form-item v-if="showDirectorSkill" label="导演 Skill（可选）">
            <el-select v-model="directorSkill" filterable clearable :loading="loadingSkills" placeholder="选择一个已安装 Skill 作为导演约束" aria-label="导演 Skill">
              <el-option v-for="skill in skills" :key="skill.name" :label="skill.displayName || skill.name" :value="skill.name">
                <div class="skillOption"><strong>{{ skill.displayName || skill.name }}</strong><span>{{ skill.description }}</span></div>
              </el-option>
            </el-select>
          </el-form-item>
          <el-form-item label="补充要求（可选）">
            <el-input v-model="extraRequirements" type="textarea" :rows="2" maxlength="4000" placeholder="例如：加强压迫感、保持角色服装一致、不要增加新人物" />
          </el-form-item>
        </el-form>
        <div class="resultHeader"><span>增强结果</span><el-button v-if="genericResult && enhanceMode === 'h3'" text size="small" @click="result = genericResult">查看通用增强中间稿</el-button></div>
        <el-input v-model="result" type="textarea" :autosize="{ minRows: 12, maxRows: 24 }" resize="none" aria-label="优化后的提示词" />
      </div>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button :loading="enhancing" @click="enhance">开始增强</el-button>
        <el-button type="primary" :disabled="!result.trim() || enhancing" @click="apply">应用到节点</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import { ElAlert, ElButton, ElDialog, ElForm, ElFormItem, ElInput, ElMessage, ElOption, ElOptionGroup, ElRadioButton, ElRadioGroup, ElSelect } from "element-plus";
import { IconWand } from "@tabler/icons-vue";
import { findNodeModel, getNodeModelIdentity, getNodeModelKey, useNodeAi, type NodeAiModel } from "@solodrama/nodes-scaffold/runtime";
import { groupNodeModels } from "../groupNodeModels";
import { h3ImageEditGuide, h3ImageSkill, h3ImageTextGuide, h3VideoBaseGuide, h3VideoReferenceGuide, h3VideoSkill } from "../h3PromptGuides";

type SkillItem = { name: string; displayName?: string; description?: string; enabled?: boolean };
type EnhanceMode = "generic" | "h3";
const props = withDefaults(defineProps<{
  mediaType: "image" | "video";
  prompt: string;
  stylePrompt?: string;
  duration?: number;
  ratio?: string;
  mode?: string;
  references?: string[];
  defaultModelKey?: string;
  defaultDirectorSkill?: string;
  showDirectorSkill?: boolean;
  disabled?: boolean;
}>(), {
  stylePrompt: "",
  references: () => [],
  defaultModelKey: "",
  defaultDirectorSkill: "",
  showDirectorSkill: true,
  disabled: false,
});
const emit = defineEmits<{ apply: [prompt: string, meta: { modelKey: string; directorSkill: string }] }>();
const ai = useNodeAi();
const visible = ref(false);
const enhancing = ref(false);
const loadingModels = ref(false);
const loadingSkills = ref(false);
const models = ref<NodeAiModel[]>([]);
const skills = ref<SkillItem[]>([]);
const modelKey = ref("");
const directorSkill = ref("");
const enhanceMode = ref<EnhanceMode>("generic");
const extraRequirements = ref("");
const genericResult = ref("");
const result = ref("");
const modelGroups = computed(() => groupNodeModels(models.value));
const skillCache = new Map<string, string>();

defineExpose({ open });

async function open() {
  if (props.disabled) return;
  visible.value = true;
  result.value = props.prompt.trim();
  genericResult.value = "";
  directorSkill.value = props.defaultDirectorSkill || "";
  void Promise.all([loadModels(), props.showDirectorSkill ? loadSkills() : Promise.resolve()]);
}

async function loadModels() {
  if (models.value.length || loadingModels.value) return;
  loadingModels.value = true;
  try {
    models.value = await ai.getModels();
    if (!findNodeModel(models.value, modelKey.value)) {
      const preferred = findNodeModel(models.value, props.defaultModelKey);
      modelKey.value = preferred ? getNodeModelKey(preferred) : models.value[0] ? getNodeModelKey(models.value[0]) : "";
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "读取文字模型失败");
  } finally {
    loadingModels.value = false;
  }
}

async function loadSkills() {
  if (skills.value.length || loadingSkills.value) return;
  loadingSkills.value = true;
  try {
    const data = await requestJson<SkillItem[]>("/api/skills/get");
    if (!Array.isArray(data)) throw new Error("读取 Skill 列表失败");
    skills.value = data.filter(skill => skill.enabled !== false);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "读取 Skill 列表失败");
  } finally {
    loadingSkills.value = false;
  }
}

async function directorContent() {
  if (!directorSkill.value) return "";
  const cached = skillCache.get(directorSkill.value);
  if (cached !== undefined) return cached;
  const data = await requestJson<{ content: string }>(`/api/skills/read?name=${encodeURIComponent(directorSkill.value)}`);
  if (typeof data?.content !== "string") throw new Error("读取导演 Skill 失败");
  skillCache.set(directorSkill.value, data.content);
  return data.content;
}

async function requestJson<T>(url: string) {
  const response = await fetch(url, { headers: { "x-solodrama-workspace": "1", "Cache-Control": "no-cache" } });
  const payload = await response.json().catch(() => null) as { code?: number; data?: T; message?: string } | null;
  if (!response.ok || payload?.code !== 200) throw new Error(payload?.message || `请求失败（${response.status}）`);
  return payload.data as T;
}

function genericSystemPrompt(skill: string) {
  const type = props.mediaType === "video" ? "short-drama video generation" : "short-drama image generation";
  return `You are a senior prompt director for ${type}. Rewrite the user's request into one production-ready prompt while preserving every explicit fact, dialogue line, language, count, ratio, exclusion and continuity requirement. Add useful concrete visual decisions only when they do not contradict the request. For video, include subject consistency, composition, camera movement, action timing, lighting, environment, diegetic sound and duration fit. For images, include composition, subject identity, pose, expression, wardrobe, environment, light, lens and rendering style. Return only the final prompt, without commentary or Markdown fences.
${skill ? `\nThe user selected this director Skill as creative direction. Follow it as guidance but do not invent tools or external operations:\n${skill}` : ""}`;
}

function h3SystemPrompt(skill: string) {
  if (props.mediaType === "video") {
    const referenceMode = props.references.length >= 2 || /reference|multi|startEnd|首尾|多参考/i.test(props.mode ?? "");
    return `You are executing the H3 video prompt-writing Skill. Convert the generic enhanced draft into the required H3 prompt structure. Preserve all dialogue and visible text in their original language. Return only the final production prompt.
\n${h3VideoSkill}\n${h3VideoBaseGuide}${referenceMode ? `\n${h3VideoReferenceGuide}` : ""}${skill ? `\nDirector Skill guidance:\n${skill}` : ""}`;
  }
  return `You are executing the H3Image prompt-writing Skill. Convert the generic enhanced draft into one ready-to-use H3Image prompt. Preserve authored copy and explicit constraints. Return only the final prompt.
\n${h3ImageSkill}\n${props.references.length ? h3ImageEditGuide : h3ImageTextGuide}${skill ? `\nDirector Skill guidance:\n${skill}` : ""}`;
}

async function enhance() {
  if (enhancing.value) return;
  if (!modelKey.value) return ElMessage.warning("请先选择文字模型");
  const source = props.prompt.trim() || extraRequirements.value.trim();
  if (!source) return ElMessage.warning("当前提示词为空，请先填写提示词或补充要求");
  const model = findNodeModel(models.value, modelKey.value);
  if (!model) return ElMessage.warning("所选文字模型不可用，请重新选择");
  enhancing.value = true;
  try {
    const skill = await directorContent();
    const context = JSON.stringify({
      mediaType: props.mediaType,
      ratio: props.ratio || "",
      duration: props.duration ?? null,
      generationMode: props.mode || "",
      style: props.stylePrompt || "",
      references: props.references,
      extraRequirements: extraRequirements.value.trim(),
    }, null, 2);
    const identity = getNodeModelIdentity(model);
    const generic = await ai.generate({
      ...identity,
      prompt: `Current source prompt:\n${source}\n\nGeneration context:\n${context}`,
      systemPrompt: genericSystemPrompt(skill),
    });
    genericResult.value = cleanPrompt(generic.text);
    if (enhanceMode.value === "generic") {
      result.value = genericResult.value;
    } else {
      const h3 = await ai.generate({
        ...identity,
        prompt: `Generic enhanced prompt:\n${genericResult.value}\n\nGeneration context:\n${context}\n\nRewrite it using the required H3 structure.`,
        systemPrompt: h3SystemPrompt(skill),
      });
      result.value = cleanPrompt(h3.text);
    }
    ElMessage.success(enhanceMode.value === "h3" ? "H3 两阶段增强完成" : "通用提示词增强完成");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "提示词增强失败");
  } finally {
    enhancing.value = false;
  }
}

function cleanPrompt(value: string) {
  return value.trim().replace(/^```(?:markdown|text|txt)?\s*/i, "").replace(/\s*```$/i, "").trim();
}

function apply() {
  if (!result.value.trim()) return;
  emit("apply", result.value.trim(), { modelKey: modelKey.value, directorSkill: directorSkill.value });
  visible.value = false;
}
</script>

<style scoped lang="scss">
.promptEnhancer { display: inline-flex; }
.enhancerBody { display: flex; flex-direction: column; gap: 14px; }
.formGrid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.formGrid :deep(.el-select), .enhancerBody :deep(.el-select) { width: 100%; }
.skillOption { display: grid; gap: 2px; padding: 3px 0; strong { font-size: 12px; } span { overflow: hidden; max-width: 560px; color: var(--el-text-color-secondary); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; } }
.resultHeader { display: flex; align-items: center; justify-content: space-between; color: var(--el-text-color-regular); font-size: 12px; font-weight: 600; }
@media (max-width: 620px) { .formGrid { grid-template-columns: 1fr; } }
</style>
