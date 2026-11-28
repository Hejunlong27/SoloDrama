<template>
  <div class="overviewStage">
    <section class="overviewHero">
      <div>
        <p class="eyebrow">SHORT DRAMA PRODUCTION</p>
        <h2>从剧本到成片，一条可追踪的短剧生产线</h2>
        <p class="heroCopy">正式制作数据使用稳定 ID、确认状态和 Take 版本；旧画布节点作为来源保留，不会自动改写已经确认的内容。</p>
        <div class="heroActions">
          <el-button type="primary" @click="navigate(nextStage)">{{ nextAction }}</el-button>
          <el-button @click="navigate('canvas')">查看画布来源</el-button>
        </div>
      </div>
      <div class="readinessDial">
        <el-progress type="dashboard" :percentage="readinessPercent" :width="146" :strokeWidth="10" color="#63c7b2">
          <template #default="{ percentage }">
            <strong>{{ percentage }}%</strong>
            <span>生产就绪</span>
          </template>
        </el-progress>
        <p>{{ readinessText }}</p>
      </div>
    </section>

    <section class="metricGrid">
      <article v-for="metric in metrics" :key="metric.label" class="metricCard" :class="metric.tone">
        <span>{{ metric.label }}</span>
        <strong>{{ metric.value }}</strong>
        <small>{{ metric.hint }}</small>
      </article>
    </section>

    <div class="overviewColumns">
      <section class="overviewCard">
        <div class="sectionHeader"><div><h3>生产阶段</h3><p>点击进入对应工作区。</p></div></div>
        <button v-for="stage in stages" :key="stage.id" class="stageRow" type="button" @click="navigate(stage.id)">
          <span class="stageIndex">{{ stage.index }}</span>
          <span class="stageBody"><b>{{ stage.label }}</b><small>{{ stage.description }}</small></span>
          <span class="stageCount">{{ stage.count }}</span>
          <el-tag size="small" :type="stage.done ? 'success' : 'info'">{{ stage.done ? "已具备" : "待完善" }}</el-tag>
        </button>
      </section>

      <section class="overviewCard">
        <div class="sectionHeader"><div><h3>待处理</h3><p>只展示会影响正式生产的项目。</p></div><el-tag effect="plain">{{ issues.length }} 项</el-tag></div>
        <div v-if="issues.length" class="issueList">
          <button v-for="issue in issues" :key="issue.id" class="issueRow" type="button" @click="navigate(issue.stage)">
            <span class="issueDot" :class="issue.level" />
            <span><b>{{ issue.title }}</b><small>{{ issue.description }}</small></span>
            <span class="issueAction">处理</span>
          </button>
        </div>
        <div v-else class="healthyState"><span>✓</span><p>当前没有阻断正式制作的待处理项。</p></div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { ProductionDocument } from "@solodrama/production";
import { ElButton, ElProgress, ElTag } from "element-plus";

type StageId = "script" | "assets" | "storyboard" | "timeline" | "canvas";
const props = defineProps<{ document: ProductionDocument; canvasTotal: number; canvasBound: number; canvasPending: number }>();
const emit = defineEmits<{ navigate: [stage: StageId] }>();

const shots = computed(() => props.document.episodes.flatMap(episode => episode.scenes.flatMap(scene => scene.shots)));
const takes = computed(() => shots.value.flatMap(shot => shot.takes));
const selectedShots = computed(() => shots.value.filter(shot => !!shot.selectedTakeId));
const confirmedShots = computed(() => shots.value.filter(shot => shot.confirmed));
const sceneCount = computed(() => props.document.episodes.reduce((sum, episode) => sum + episode.scenes.length, 0));
const generating = computed(() => takes.value.filter(take => take.status === "generating").length + props.document.generationJobs.filter(job => job.status === "generating").length);
const failed = computed(() => takes.value.filter(take => take.status === "failed").length + props.document.generationJobs.filter(job => job.status === "failed").length);
const missingCharacterRefs = computed(() => props.document.characters.filter(character => character.referenceImages.length === 0).length);
const missingLocationRefs = computed(() => props.document.locations.filter(location => location.referenceImages.length === 0).length);
const unconfirmedShots = computed(() => shots.value.length - confirmedShots.value.length);
const selectedRatio = computed(() => shots.value.length ? Math.round(selectedShots.value.length / shots.value.length * 100) : 0);
const metricList = computed(() => [
  { label: "分集 / 场次", value: `${props.document.episodes.length} / ${sceneCount.value}`, hint: "正式生产结构", tone: "" },
  { label: "镜头", value: shots.value.length, hint: `${confirmedShots.value.length} 已确认`, tone: "" },
  { label: "正式 Take", value: selectedShots.value.length, hint: `${selectedRatio.value}% 镜头已定稿`, tone: selectedShots.value.length ? "success" : "warning" },
  { label: "正在生成", value: generating.value, hint: generating.value ? "任务运行中" : "当前空闲", tone: generating.value ? "active" : "" },
  { label: "素材", value: props.document.assets.length, hint: "已登记 Production Asset", tone: "" },
  { label: "角色 / 场景", value: `${props.document.characters.length} / ${props.document.locations.length}`, hint: `${missingCharacterRefs.value + missingLocationRefs.value} 项缺少参考图`, tone: missingCharacterRefs.value + missingLocationRefs.value ? "warning" : "" },
  { label: "画布来源", value: props.canvasTotal, hint: `${props.canvasBound} 已关联 · ${props.canvasPending} 未归档`, tone: props.canvasPending ? "active" : "" },
  { label: "失败任务", value: failed.value, hint: failed.value ? "需要检查或重试" : "无失败记录", tone: failed.value ? "danger" : "" },
]);
const metrics = metricList;
const stages = computed(() => [
  { id: "script" as const, index: "01", label: "剧本编制与解析", description: "输入创意或上传剧本，解析故事、角色、分集与连续性", count: props.document.episodes.length, done: !!props.document.synopsis || props.document.episodes.length > 0 },
  { id: "assets" as const, index: "02", label: "提取资产", description: "角色、场景、道具、音色与统一画风", count: props.document.characters.length + props.document.locations.length + props.document.props.length, done: props.document.characters.length > 0 && props.document.locations.length > 0 },
  { id: "storyboard" as const, index: "03", label: "设计分镜", description: "导演分镜、视频提示词与分段视频 Take", count: shots.value.length, done: shots.value.length > 0 && selectedShots.value.length === shots.value.length },
  { id: "timeline" as const, index: "04", label: "旁白与成片", description: "旁白、字幕、Remotion 片段、拼接与剪映草稿", count: props.document.timeline.length, done: selectedShots.value.length > 0 && props.document.timeline.some(item => item.kind === "video") },
  { id: "canvas" as const, index: "05", label: "画布来源", description: "旧节点导入、来源映射与回画布定位", count: props.canvasTotal, done: props.canvasTotal === 0 || props.canvasPending === 0 },
]);
const nextStage = computed<StageId>(() => {
  if (!props.document.episodes.length) return "script";
  if (!props.document.characters.length || !props.document.locations.length) return "assets";
  if (!shots.value.length || selectedShots.value.length < shots.value.length) return "storyboard";
  return "timeline";
});
const nextAction = computed(() => ({ script: "继续剧本理解", assets: "完善角色与场景", storyboard: "检查分镜与 Take", timeline: "进入声音与成片", canvas: "整理画布来源" })[nextStage.value]);
const readinessPercent = computed(() => {
  const checks = [
    props.document.episodes.length > 0,
    props.document.characters.length > 0,
    props.document.locations.length > 0,
    shots.value.length > 0,
    selectedShots.value.length > 0,
    props.document.timeline.some(item => item.kind === "video"),
    props.document.timeline.some(item => item.kind === "subtitle" || item.kind === "audio"),
  ];
  return Math.round(checks.filter(Boolean).length / checks.length * 100);
});
const readinessText = computed(() => readinessPercent.value === 100 ? "已具备导出条件" : readinessPercent.value >= 60 ? "主体结构已形成" : "仍在搭建生产基础");
const issues = computed(() => {
  const list: { id: string; title: string; description: string; level: string; stage: StageId }[] = [];
  if (!props.document.episodes.length) list.push({ id: "episode", title: "还没有正式分集", description: "先用剧本理解生成分集、场次与镜头。", level: "warning", stage: "script" });
  if (missingCharacterRefs.value) list.push({ id: "characterRefs", title: `${missingCharacterRefs.value} 个角色缺少参考图`, description: "生成标准形象并设为确认参考图。", level: "warning", stage: "assets" });
  if (missingLocationRefs.value) list.push({ id: "locationRefs", title: `${missingLocationRefs.value} 个场景缺少参考图`, description: "补齐空间、光线和色彩参考。", level: "warning", stage: "assets" });
  if (unconfirmedShots.value) list.push({ id: "shots", title: `${unconfirmedShots.value} 个镜头尚未确认`, description: "人工检查画面、对白和生成要求后确认。", level: "info", stage: "storyboard" });
  if (failed.value) list.push({ id: "failed", title: `${failed.value} 个生成任务失败`, description: "检查 Provider 与工作流后重新生成。", level: "error", stage: "storyboard" });
  if (props.canvasPending) list.push({ id: "canvas", title: `${props.canvasPending} 个画布来源未归档`, description: "导入、关联或保留为历史节点。", level: "info", stage: "canvas" });
  return list;
});
function navigate(stage: StageId) {
  emit("navigate", stage);
}
</script>

<style scoped lang="scss">
.overviewStage { display: grid; gap: 16px; }
.overviewHero { display: grid; grid-template-columns: minmax(0, 1fr) 210px; gap: 28px; padding: 30px; border: 1px solid var(--el-border-color-light); border-radius: 18px; background: linear-gradient(125deg, color-mix(in srgb, var(--el-color-primary) 10%, var(--el-bg-color-overlay)), var(--el-bg-color-overlay) 58%, color-mix(in srgb, #d6b77f 10%, var(--el-bg-color-overlay))); }
.eyebrow { margin: 0; color: var(--el-color-primary); font-size: 10px; font-weight: 700; letter-spacing: .16em; }
.overviewHero h2 { max-width: 760px; margin: 10px 0 12px; font-size: clamp(25px, 3vw, 42px); line-height: 1.15; letter-spacing: -.04em; }
.heroCopy { max-width: 720px; margin: 0; color: var(--el-text-color-secondary); line-height: 1.8; }
.heroActions { display: flex; gap: 9px; margin-top: 22px; }
.readinessDial { display: grid; place-items: center; align-content: center; padding: 14px; border-radius: 16px; background: var(--el-bg-color); }
.readinessDial :deep(strong) { display: block; font-size: 24px; }
.readinessDial :deep(span) { display: block; margin-top: 3px; color: var(--el-text-color-secondary); font-size: 11px; }
.readinessDial p { margin: 8px 0 0; color: var(--el-text-color-secondary); font-size: 11px; }
.metricGrid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.metricCard { display: grid; gap: 5px; padding: 15px; border: 1px solid var(--el-border-color-light); border-radius: 13px; background: var(--el-bg-color-overlay); }
.metricCard span, .metricCard small { color: var(--el-text-color-secondary); font-size: 12px; }
.metricCard strong { font-size: 25px; font-weight: 600; }
.metricCard.warning { border-color: var(--el-color-warning-light-5); }
.metricCard.active { border-color: var(--el-color-primary-light-5); }
.metricCard.danger { border-color: var(--el-color-danger-light-5); }
.metricCard.success { border-color: var(--el-color-success-light-5); }
.overviewColumns { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(340px, .85fr); gap: 16px; }
.overviewCard { padding: 18px; border: 1px solid var(--el-border-color-light); border-radius: 15px; background: var(--el-bg-color-overlay); }
.sectionHeader { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
.sectionHeader h3, .sectionHeader p { margin: 0; }
.sectionHeader h3 { font-size: 16px; }
.sectionHeader p { margin-top: 4px; color: var(--el-text-color-secondary); font-size: 11px; }
.stageRow, .issueRow { display: grid; width: 100%; align-items: center; gap: 12px; padding: 12px 8px; border: 0; border-top: 1px solid var(--el-border-color-lighter); color: inherit; background: transparent; text-align: left; cursor: pointer; }
.stageRow { grid-template-columns: 34px minmax(0, 1fr) 48px auto; }
.stageRow:hover, .issueRow:hover { background: var(--el-fill-color-lighter); }
.stageIndex { color: var(--el-color-primary); font-size: 11px; letter-spacing: .12em; }
.stageBody, .issueRow > span:nth-child(2) { display: grid; gap: 3px; }
.stageBody b, .issueRow b { font-size: 13px; }
.stageBody small, .issueRow small { color: var(--el-text-color-secondary); font-size: 11px; }
.stageCount { text-align: right; font-size: 20px; }
.issueList { display: grid; }
.issueRow { grid-template-columns: 9px minmax(0, 1fr) auto; }
.issueDot { width: 8px; height: 8px; border-radius: 50%; background: var(--el-color-info); }
.issueDot.warning { background: var(--el-color-warning); }
.issueDot.error { background: var(--el-color-danger); }
.issueAction { color: var(--el-color-primary); font-size: 11px; }
.healthyState { display: grid; place-items: center; gap: 8px; min-height: 220px; color: var(--el-text-color-secondary); }
.healthyState span { display: grid; place-items: center; width: 42px; height: 42px; border-radius: 50%; color: var(--el-color-success); background: var(--el-color-success-light-9); font-size: 20px; }
.healthyState p { margin: 0; font-size: 12px; }
@media (max-width: 1100px) { .metricGrid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .overviewColumns { grid-template-columns: 1fr; } }
@media (max-width: 760px) { .overviewHero { grid-template-columns: 1fr; padding: 22px; } .readinessDial { justify-self: start; } }
</style>
