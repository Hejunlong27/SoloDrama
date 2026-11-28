<template>
  <main class="launcherPage">
    <div class="ambient" aria-hidden="true" />
    <header class="topbar">
      <div class="brand">
        <span class="brandMark" aria-hidden="true"><span /></span>
        <div><strong>SoloDrama</strong><small>Launcher · {{ status?.runtime.version || '2.0.0' }}</small></div>
      </div>
      <div class="topActions">
        <el-tag :type="overallTone" effect="plain">{{ overallLabel }}</el-tag>
        <el-button :icon="IconRefresh" :loading="loading" @click="refresh">刷新状态</el-button>
        <el-button v-if="!firstRun" type="primary" :icon="IconArrowRight" @click="enterWorkspace">进入工作台</el-button>
      </div>
    </header>

    <div class="launcherLayout">
      <aside class="rail" aria-label="启动器导航">
        <button v-for="item in navItems" :key="item.id" type="button" :class="{ active: activeTab === item.id }" :aria-pressed="activeTab === item.id" @click="activeTab = item.id">
          <component :is="item.icon" :size="19" aria-hidden="true" /><span>{{ item.label }}</span>
        </button>
        <div class="railFoot">
          <button type="button" @click="openLogs"><icon-folder-open :size="18" /><span>打开日志目录</span></button>
          <button type="button" class="danger" @click="requestQuit"><icon-power :size="18" /><span>退出 SoloDrama</span></button>
        </div>
      </aside>

      <section class="content" :aria-label="activeNav?.label" tabindex="0">
        <template v-if="activeTab === 'overview'">
          <section class="readiness" :data-state="overallTone">
            <div class="readinessCopy">
              <span class="stateLine"><span class="stateDot" />{{ overallLabel }}</span>
              <h1>{{ firstRun ? '欢迎来到 SoloDrama' : '创作环境运行正常' }}</h1>
              <p>{{ firstRun ? '先确认运行环境与数据位置，再进入创作工作台。本地和云端 ComfyUI 都可以稍后配置。' : '本地服务、创作界面与数据目录来自实时检测；云端连接状态不会阻止进入工作台。' }}</p>
              <div class="heroActions"><el-button type="primary" size="large" @click="firstRun ? completeOnboarding() : enterWorkspace()">{{ firstRun ? '开始使用' : '打开工作台' }}</el-button><el-button size="large" @click="activeTab = 'logs'">查看日志</el-button></div>
            </div>
            <div class="signalPanel" aria-hidden="true"><span v-for="index in 7" :key="index" :class="{ live: stepDone(index - 1) }" /><strong>{{ completedSteps }}/{{ startupSteps.length }}</strong></div>
          </section>
          <section class="statusGrid">
            <article v-for="card in overviewCards" :key="card.id" class="statusCard">
              <div class="statusIcon" :data-tone="card.tone"><component :is="card.icon" :size="20" /></div>
              <div><span>{{ card.label }}</span><strong>{{ card.value }}</strong><small>{{ card.detail }}</small></div>
            </article>
          </section>
          <section class="startupSection">
            <div class="sectionTitle"><div><h2>启动过程</h2><p>每一步都基于真实状态，不使用预设时间动画。</p></div><el-text type="info">最后检查 {{ checkedAtLabel }}</el-text></div>
            <ol class="startupSteps"><li v-for="(step, index) in startupSteps" :key="step.id" :data-done="stepDone(index)"><span class="stepIcon"><icon-check v-if="stepDone(index)" :size="15" /><span v-else>{{ index + 1 }}</span></span><div><strong>{{ step.label }}</strong><small>{{ step.detail }}</small></div><span class="stepState">{{ stepDone(index) ? '完成' : index === activeStep ? '进行中' : '等待' }}</span></li></ol>
          </section>
        </template>

        <template v-else-if="activeTab === 'services'">
          <div class="sectionTitle"><div><h2>本地服务</h2><p>只展示 SoloDrama 自己管理的进程与真实健康检查结果。</p></div><el-button :icon="IconRefresh" :loading="loading" @click="refresh">重新检测</el-button></div>
          <div class="serviceList"><article v-for="service in services" :key="service.id" class="serviceRow"><div class="serviceLead"><span :data-tone="service.tone" /><div><strong>{{ service.name }}</strong><small>{{ service.description }}</small></div></div><el-tag :type="service.tone" effect="plain">{{ service.label }}</el-tag><span class="serviceDetail">{{ service.detail }}</span><el-button size="small" :icon="IconCopy" @click="copyText(service.detail)">复制</el-button></article></div>
          <section class="pathPanel"><div><span>程序版本</span><code>{{ status?.runtime.version || '未知' }}</code></div><div><span>后端端口</span><code>{{ status?.checks.backend.port || '未知' }}</code></div><div><span>进程 PID</span><code>{{ status?.runtime.pid || '未知' }}</code></div><div><span>运行平台</span><code>{{ status ? `${status.runtime.platform}/${status.runtime.arch}` : '未知' }}</code></div></section>
        </template>

        <template v-else-if="activeTab === 'cloud'">
          <div class="sectionTitle"><div><h2>云端连接</h2><p>状态来自现有 Cloud Hub，不在 Launcher 中重复实现 ComfyUI 连接协议。</p></div><div class="titleActions"><el-button :icon="IconRefresh" :loading="loading" @click="refresh">重新检测</el-button><el-button type="primary" :icon="IconCloud" @click="openCloudHub">打开云端算力中心</el-button></div></div>
          <div class="cloudHero"><div><span>已配置实例</span><strong>{{ status?.checks.cloud.configured ?? 0 }}</strong></div><div><span>可用实例</span><strong class="online">{{ status?.checks.cloud.online ?? 0 }}</strong></div><div><span>离线实例</span><strong :class="{ offline: (status?.checks.cloud.offline ?? 0) > 0 }">{{ status?.checks.cloud.offline ?? 0 }}</strong></div></div>
          <el-alert :closable="false" showIcon :type="(status?.checks.cloud.offline ?? 0) > 0 ? 'warning' : 'info'" :title="(status?.checks.cloud.configured ?? 0) === 0 ? '尚未配置云端 ComfyUI，不影响本地创作。' : (status?.checks.cloud.offline ?? 0) > 0 ? '部分云端算力暂时不可用，已提交任务仍由 Task Runtime 持久保存。' : '云端算力连接正常。'" />
          <section class="taskSnapshot"><h3>任务概况</h3><div><span>运行中</span><strong>{{ status?.checks.tasks.running ?? 0 }}</strong></div><div><span>待恢复</span><strong>{{ status?.checks.tasks.interrupted ?? 0 }}</strong></div><div><span>已记录任务</span><strong>{{ status?.checks.tasks.total ?? 0 }}</strong></div><p>Launcher 只读取任务状态，不取消、不接管、不删除云端任务。</p></section>
        </template>        <template v-else-if="activeTab === 'logs'">
          <div class="sectionTitle"><div><h2>运行日志</h2><p>日志在读取时再次脱敏，不展示 Token、认证 Header 或密码。</p></div><div class="titleActions"><el-button :icon="IconRefresh" :loading="logsLoading" @click="loadLogs">刷新日志</el-button><el-button :icon="IconFolderOpen" @click="openLogs">打开日志目录</el-button></div></div>
          <div class="logToolbar"><el-input v-model="logSearch" :prefixIcon="IconSearch" clearable placeholder="搜索日志" aria-label="搜索日志" /><el-segmented v-model="logLevel" :options="logLevels" /><el-button :icon="IconCopy" :disabled="!filteredLogs.length" @click="copyText(filteredLogs.join('\n'))">复制错误详情</el-button><el-button :icon="IconDownload" :disabled="!status" @click="exportDiagnostics">导出诊断包</el-button></div>
          <pre class="logView" tabindex="0">{{ filteredLogs.join('\n') || '暂无匹配日志' }}</pre>
        </template>

        <template v-else-if="activeTab === 'settings'">
          <div class="sectionTitle"><div><h2>启动设置</h2><p>设置写入 SoloDrama 配置，不修改项目文件。</p></div></div>
          <section class="settingsPanel">
            <label><span><strong>启动后自动进入工作台</strong><small>关闭后双击会停留在启动控制中心。</small></span><el-switch v-model="launcherSettings.autoOpenWorkspace" @change="saveSettings({ autoOpenWorkspace: launcherSettings.autoOpenWorkspace })" /></label>
            <label><span><strong>启动时检查更新</strong><small>只在桌面端和正式版本生效。</small></span><el-switch v-model="launcherSettings.checkUpdatesOnStartup" @change="saveSettings({ checkUpdatesOnStartup: launcherSettings.checkUpdatesOnStartup })" /></label>
            <label><span><strong>开机自启动</strong><small>Windows 正式安装版通过当前用户启动项实现。</small></span><el-switch v-model="launcherSettings.launchOnStartup" :loading="savingSettings" @change="saveSettings({ launchOnStartup: launcherSettings.launchOnStartup })" /></label>
          </section>
          <section class="pathPanel"><div><span>项目与配置数据</span><code>{{ status?.paths.dataDirectory || '读取中' }}</code><el-button size="small" :icon="IconFolderOpen" @click="openData">打开</el-button></div><div><span>运行日志</span><code>{{ status?.paths.logDirectory || '读取中' }}</code><el-button size="small" :icon="IconFolderOpen" @click="openLogs">打开</el-button></div></section>
          <el-alert type="info" :closable="false" showIcon title="升级只替换程序文件。项目、工作流、Provider 配置、凭据和日志分别保存在数据目录，不会被安装器清理。" />
        </template>

        <template v-else>
          <div class="sectionTitle"><div><h2>关于 SoloDrama</h2><p>桌面入口与创作平台使用同一版本和同一数据目录。</p></div></div>
          <section class="aboutPanel"><div class="aboutBrand"><span class="brandMark large" aria-hidden="true"><span /></span><div><h3>SoloDrama</h3><p>面向 AI 短剧创作的桌面生产平台</p></div></div><dl><div><dt>当前版本</dt><dd>{{ status?.runtime.version || '未知' }}</dd></div><div><dt>构建平台</dt><dd>{{ status ? `${status.runtime.platform} / ${status.runtime.arch}` : '未知' }}</dd></div><div><dt>数据目录</dt><dd><code>{{ status?.paths.dataDirectory }}</code></dd></div></dl><div class="heroActions"><el-button :icon="IconRefresh" @click="checkUpdate">检查更新</el-button><el-button :icon="IconExternalLink" @click="enterWorkspace">返回工作台</el-button></div></section>
        </template>
      </section>
    </div>

    <el-dialog v-model="firstRunDialog" title="欢迎使用 SoloDrama" width="min(620px, calc(100vw - 32px))" alignCenter :closeOnClickOutside="false" :closeOnPressEscape="false" :showClose="false" appendToBody>
      <div class="wizard"><p>SoloDrama 会自动管理本地服务。ComfyUI 不是启动条件，你可以在进入软件后再配置本地或云端算力。</p><div class="wizardPath"><icon-database :size="20" /><div><strong>数据保存位置</strong><code>{{ status?.paths.dataDirectory || '正在检测' }}</code><small>已有数据目录会被优先复用；升级不会清理项目、工作流和凭据。</small></div></div><div class="wizardChecks"><span v-for="item in overviewCards.slice(0, 4)" :key="item.id"><icon-check :size="14" />{{ item.label }}：{{ item.value }}</span></div></div>
      <template #footer><el-button type="primary" :loading="savingSettings" @click="completeOnboarding">继续进入 SoloDrama</el-button></template>
    </el-dialog>
  </main>
</template><script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import {
  IconActivity, IconArrowRight, IconCheck, IconCloud, IconCopy, IconDatabase, IconDownload, IconExternalLink,
  IconFolderOpen, IconInfoCircle, IconPower, IconRefresh, IconSearch, IconServer, IconSettings, IconListCheck,
} from "@tabler/icons-vue";
import http from "@/lib/http";
import { settings } from "@/stores/settings";
import { actualPlatform } from "@/lib/platform";
import { useHelloStore } from "@/stores/hello";

type Status = {
  runtime: { version: string; pid: number; platform: string; arch: string };
  settings: { launcherOnboarded: boolean; autoOpenWorkspace: boolean; checkUpdatesOnStartup: boolean; launchOnStartup: boolean };
  checks: {
    environment: { status: string; label: string }; data: { status: string; label: string; path: string };
    backend: { status: string; label: string; port?: number }; frontend: { status: string; label: string };
    database: { status: string; label: string }; localComfy: { status: string; label: string };
    cloud: { configured: number; online: number; offline: number; lastCheckedAt?: number };
    tasks: { running: number; interrupted: number; total: number };
  };
  paths: { dataDirectory: string; logDirectory: string; logPath: string; logExists: boolean; logBytes: number };
};
type TabId = "overview" | "services" | "cloud" | "logs" | "settings" | "about";
const router = useRouter();
const helloStore = useHelloStore();
const activeTab = ref<TabId>("overview");
const status = ref<Status>();
const loading = ref(false);
const savingSettings = ref(false);
const logs = ref<string[]>([]);
const logsLoading = ref(false);
const logSearch = ref("");
const logLevel = ref("全部");
const firstRunDialog = ref(false);
let timer: ReturnType<typeof setInterval> | undefined;
const navItems = [
  { id: "overview" as const, label: "运行概览", icon: IconActivity }, { id: "services" as const, label: "本地服务", icon: IconServer },
  { id: "cloud" as const, label: "云端连接", icon: IconCloud }, { id: "logs" as const, label: "运行日志", icon: IconListCheck },
  { id: "settings" as const, label: "启动设置", icon: IconSettings }, { id: "about" as const, label: "关于 SoloDrama", icon: IconInfoCircle },
];
const logLevels = ["全部", "INFO", "WARN", "ERROR"];
const launcherSettings = reactive({ autoOpenWorkspace: true, checkUpdatesOnStartup: true, launchOnStartup: false });
const firstRun = computed(() => status.value?.settings.launcherOnboarded !== true);
const activeNav = computed(() => navItems.find(item => item.id === activeTab.value));
const checkedAtLabel = computed(() => status.value?.checks.cloud.lastCheckedAt ? new Date(status.value.checks.cloud.lastCheckedAt).toLocaleString() : "未检测云端");
const overallTone = computed<"success" | "warning" | "danger" | "info">(() => {
  const checks = status.value?.checks;
  if (!checks) return "info";
  if (checks.backend.status !== "healthy" || checks.frontend.status !== "healthy" || checks.data.status !== "healthy") return "danger";
  if (checks.cloud.offline > 0) return "warning";
  return "success";
});
const overallLabel = computed(() => !status.value ? "正在检测" : overallTone.value === "danger" ? "启动异常" : overallTone.value === "warning" ? "部分云端不可用" : "SoloDrama 已就绪");
const startupSteps = computed(() => [
  { id: "environment", label: "检查运行环境", detail: status.value?.checks.environment.label || "正在读取桌面环境" },
  { id: "data", label: "检查数据目录", detail: status.value?.checks.data.label || "正在检查数据目录" },
  { id: "backend", label: "启动本地服务", detail: status.value?.checks.backend.label || "等待后端响应" },
  { id: "frontend", label: "初始化创作界面", detail: status.value?.checks.frontend.label || "等待界面连接" },
  { id: "cloud", label: "检查可选算力", detail: status.value ? `本地：${status.value.checks.localComfy.label}；云端在线 ${status.value.checks.cloud.online}` : "正在读取 Cloud Hub" },
]);
const activeStep = computed(() => status.value ? startupSteps.value.length : 0);
const completedSteps = computed(() => status.value ? startupSteps.value.length : 0);
const overviewCards = computed(() => {
  const checks = status.value?.checks;
  return [
    { id: "backend", label: "本地服务", value: checks?.backend.status === "healthy" ? "运行中" : "检测中", detail: checks?.backend.port ? `端口 ${checks.backend.port}` : "等待健康检查", icon: IconServer, tone: "success" as const },
    { id: "frontend", label: "创作界面", value: checks?.frontend.status === "healthy" ? "已连接" : "检测中", detail: "桌面 WebView 已加载", icon: IconActivity, tone: "success" as const },
    { id: "data", label: "项目数据", value: checks?.data.status === "healthy" ? "可访问" : "异常", detail: status.value?.paths.dataDirectory || "读取路径中", icon: IconDatabase, tone: checks?.data.status === "healthy" ? "success" as const : "danger" as const },
    { id: "cloud", label: "云端算力", value: checks?.cloud.configured ? `${checks.cloud.online}/${checks.cloud.configured} 可用` : "未配置", detail: checks?.cloud.configured ? `${checks.cloud.offline} 个离线` : "不阻止进入工作台", icon: IconCloud, tone: checks?.cloud.configured ? (checks.cloud.offline > 0 ? "warning" as const : "success" as const) : "info" as const },
    { id: "tasks", label: "任务运行", value: `${checks?.tasks.running ?? 0} 运行中`, detail: `${checks?.tasks.interrupted ?? 0} 个待恢复`, icon: IconListCheck, tone: "info" as const },
  ];
});
const services = computed(() => {
  const checks = status.value?.checks;
  return [
    { id: "backend", name: "SoloDrama 核心后端", description: "Express 业务接口和本地文件服务", label: checks?.backend.status === "healthy" ? "正常" : "未知", tone: "success" as const, detail: checks?.backend.label || "等待检测" },
    { id: "frontend", name: "创作界面", description: "Electrobun 桌面 WebView", label: checks?.frontend.status === "healthy" ? "正常" : "未知", tone: "success" as const, detail: checks?.frontend.label || "等待检测" },
    { id: "data", name: "项目数据服务", description: "工作区、配置与任务记录", label: checks?.data.status === "healthy" ? "正常" : "异常", tone: checks?.data.status === "healthy" ? "success" as const : "danger" as const, detail: status.value?.paths.dataDirectory || "等待检测" },
    { id: "task", name: "统一任务运行时", description: "媒体生成与云端 ComfyUI 任务状态", label: "正常", tone: "success" as const, detail: `运行中 ${checks?.tasks.running ?? 0}，待恢复 ${checks?.tasks.interrupted ?? 0}` },
  ];
});
const filteredLogs = computed(() => logs.value.filter(line => (!logSearch.value || line.toLowerCase().includes(logSearch.value.toLowerCase())) && (logLevel.value === "全部" || line.toUpperCase().includes(`[${logLevel.value}]`))));
const stepDone = (index: number) => !!status.value && index < completedSteps.value;
async function loadStatus() { loading.value = true; try { status.value = await http<Status>({ method: "GET", url: "/api/desktop/launcher/status" }); Object.assign(launcherSettings, status.value.settings); firstRunDialog.value = !status.value.settings.launcherOnboarded; } catch (error) { ElMessage.error(error instanceof Error ? error.message : "读取启动器状态失败"); } finally { loading.value = false; } }
async function refresh() { await Promise.all([loadStatus(), activeTab.value === "logs" ? loadLogs() : Promise.resolve()]); }
async function loadLogs() { logsLoading.value = true; try { logs.value = (await http<{ lines: string[] }>({ method: "GET", url: "/api/desktop/launcher/logs" })).lines; } catch (error) { ElMessage.error(error instanceof Error ? error.message : "读取日志失败"); } finally { logsLoading.value = false; } }
async function saveSettings(patch: Record<string, boolean>) { savingSettings.value = true; try { await http({ method: "PUT", url: "/api/desktop/launcher/settings", data: patch }); await loadStatus(); ElMessage.success("设置已保存"); } catch (error) { ElMessage.error(error instanceof Error ? error.message : "保存设置失败"); await loadStatus(); } finally { savingSettings.value = false; } }
async function completeOnboarding() { await saveSettings({ launcherOnboarded: true }); firstRunDialog.value = false; await enterWorkspace(); }
async function enterWorkspace() { const completed = await helloStore.load().catch(() => settings.value.helloCompleted === true); await router.push(completed ? "/home" : "/hello"); }
function openCloudHub() { void router.push("/cloudCompute"); }
async function openLogs() { try { await http({ method: "POST", url: "/api/desktop/launcher/openLogs" }); } catch (error) { ElMessage.error(error instanceof Error ? error.message : "打开日志失败"); } }
async function openData() { try { await http({ method: "POST", url: "/api/desktop/launcher/openData" }); } catch (error) { ElMessage.error(error instanceof Error ? error.message : "打开数据目录失败"); } }
async function checkUpdate() { try { const response = await fetch("/api/desktop/update/check", { method: "POST", headers: { "x-solodrama-desktop": "1" } }); if (!response.ok) throw new Error((await response.json()).message || "检查更新失败"); ElMessage.success("更新检查已启动"); } catch (error) { ElMessage.error(error instanceof Error ? error.message : "检查更新失败"); } }
async function copyText(text: string) { await navigator.clipboard.writeText(text); ElMessage.success("已复制"); }
function exportDiagnostics() { const payload = JSON.stringify({ generatedAt: new Date().toISOString(), status: status.value, logs: filteredLogs.value }, null, 2); const url = URL.createObjectURL(new Blob([payload], { type: "application/json" })); const anchor = document.createElement("a"); anchor.href = url; anchor.download = "solodrama-launcher-diagnostics.json"; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
function requestQuit() { if (actualPlatform.isDesktop) window.close(); }
onMounted(async () => { await loadStatus(); if (activeTab.value === "logs") await loadLogs(); timer = setInterval(() => { if (!document.hidden) void loadStatus(); }, 10000); });
onBeforeUnmount(() => { if (timer) clearInterval(timer); });
</script><style scoped lang="scss">
.launcherPage { --base: #0d0d12; --panel: #15151d; --line: #2b2937; --ink: #f1eff7; --muted: #9a96aa; --accent: #8c7cff; min-height: 100dvh; overflow: auto; color: var(--ink); background: var(--base); position: relative; }
.ambient { position: fixed; inset: 0; pointer-events: none; background: radial-gradient(circle at 78% 10%, rgb(140 124 255 / 14%), transparent 28%), linear-gradient(180deg, #111018 0, var(--base) 38%); }
.topbar { position: sticky; top: 0; z-index: 5; display: flex; justify-content: space-between; align-items: center; gap: 20px; min-height: 72px; padding: 12px 32px; border-bottom: 1px solid var(--line); background: color-mix(in srgb, var(--base) 88%, transparent); backdrop-filter: blur(16px); }
.brand, .aboutBrand { display: flex; align-items: center; gap: 12px; strong { font-size: 16px; letter-spacing: .02em; } small { display: block; margin-top: 2px; color: var(--muted); font-size: 11px; } }
.brandMark { display: grid; place-items: center; width: 34px; height: 34px; border: 1px solid rgb(154 143 255 / 55%); border-radius: 10px; background: linear-gradient(145deg, #7868ff33, #1c1a28); box-shadow: inset 0 1px 0 #fff2, 0 8px 24px #0005; span { width: 15px; height: 15px; border: 2px solid #c4bcff; border-radius: 50% 50% 46% 54%; transform: rotate(-24deg); box-shadow: inset 4px 0 0 #8c7cff; } &.large { width: 54px; height: 54px; border-radius: 15px; span { width: 24px; height: 24px; } } }
.topActions, .heroActions, .titleActions { display: flex; flex-wrap: wrap; align-items: center; gap: 9px; }
.launcherLayout { position: relative; z-index: 1; display: grid; grid-template-columns: 190px minmax(0, 1fr); min-height: calc(100dvh - 72px); max-width: 1440px; margin: 0 auto; }
.rail { display: flex; flex-direction: column; gap: 4px; padding: 26px 14px 18px 22px; border-right: 1px solid var(--line); button { display: flex; align-items: center; gap: 10px; width: 100%; padding: 11px 12px; border: 0; border-radius: 9px; color: var(--muted); background: transparent; font: inherit; font-size: 12px; text-align: left; cursor: pointer; transition: color 160ms ease, background 160ms ease; &:hover { color: var(--ink); background: #ffffff08; } &.active { color: #dcd7ff; background: #8c7cff18; } &:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; } &.danger:hover { color: #ff9ba8; background: #e45f7414; } } }
.railFoot { display: flex; flex-direction: column; gap: 4px; margin-top: auto; padding-top: 18px; border-top: 1px solid var(--line); }
.content { min-width: 0; padding: 34px clamp(24px, 4vw, 56px) 60px; &:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; } }
.readiness { display: grid; grid-template-columns: minmax(0, 1fr) 260px; gap: 30px; min-height: 245px; padding: 32px; border: 1px solid var(--line); border-radius: 18px; background: linear-gradient(120deg, #191823, #121116 70%); overflow: hidden; }
.stateLine { display: inline-flex; align-items: center; gap: 8px; color: #8ce0b2; font-size: 12px; }
.stateDot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; box-shadow: 0 0 0 5px rgb(86 211 154 / 10%); }
.readiness[data-state="warning"] .stateLine { color: #f0bd63; } .readiness[data-state="danger"] .stateLine { color: #f17888; } .readiness[data-state="info"] .stateLine { color: var(--muted); }
.readinessCopy { max-width: 660px; h1 { margin: 15px 0 10px; font-size: clamp(28px, 4vw, 46px); font-weight: 590; letter-spacing: -.045em; line-height: 1.04; } p { max-width: 620px; margin: 0 0 25px; color: var(--muted); font-size: 14px; line-height: 1.8; } }
.signalPanel { align-self: end; display: grid; grid-template-columns: repeat(7, 1fr); align-items: end; gap: 6px; height: 180px; padding: 20px; border-left: 1px solid var(--line); span { display: block; height: 30%; border-radius: 3px 3px 1px 1px; background: #343141; &.live { background: linear-gradient(180deg, #a698ff, #6758d5); box-shadow: 0 0 18px #8c7cff2b; } &:nth-child(2) { height: 45%; } &:nth-child(3) { height: 58%; } &:nth-child(4) { height: 41%; } &:nth-child(5) { height: 78%; } &:nth-child(6) { height: 66%; } &:nth-child(7) { height: 88%; } } strong { grid-column: 1 / -1; color: var(--muted); font-size: 11px; font-weight: 500; } }
.statusGrid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; margin-top: 18px; }
.statusCard { display: flex; gap: 11px; min-height: 104px; padding: 16px 14px; border: 1px solid var(--line); border-radius: 12px; background: var(--panel); span { display: block; color: var(--muted); font-size: 11px; } strong { display: block; margin: 5px 0 3px; font-size: 17px; font-weight: 560; } small { display: -webkit-box; overflow: hidden; color: #777386; font-size: 10px; line-height: 1.5; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow-wrap: anywhere; } }
.statusIcon { display: grid; place-items: center; width: 34px; height: 34px; flex-shrink: 0; border-radius: 9px; color: #a89cff; background: #8c7cff16; &[data-tone="success"] { color: #69dda1; background: #56d39a14; } &[data-tone="warning"] { color: #f0bd63; background: #f0bd6314; } &[data-tone="danger"] { color: #f17888; background: #f1788814; } }
.startupSection { margin-top: 34px; }
.sectionTitle { display: flex; justify-content: space-between; align-items: flex-end; gap: 18px; margin-bottom: 18px; h2 { margin: 0 0 5px; font-size: 20px; letter-spacing: -.02em; } p { margin: 0; color: var(--muted); font-size: 12px; line-height: 1.6; } }
.startupSteps { display: flex; flex-direction: column; margin: 0; padding: 0; list-style: none; border-top: 1px solid var(--line); li { display: grid; grid-template-columns: 30px minmax(0, 1fr) 64px; gap: 12px; align-items: center; min-height: 62px; border-bottom: 1px solid var(--line); strong { display: block; font-size: 12px; font-weight: 560; } small { display: block; margin-top: 4px; color: var(--muted); font-size: 11px; } } }
.stepIcon { display: grid; place-items: center; width: 25px; height: 25px; border: 1px solid var(--line); border-radius: 50%; color: var(--muted); font-size: 10px; } li[data-done="true"] .stepIcon { color: #0e1712; border-color: #69dda1; background: #69dda1; } .stepState { justify-self: end; color: var(--muted); font-size: 10px; }.serviceList { border-top: 1px solid var(--line); }
.serviceRow { display: grid; grid-template-columns: minmax(240px, 1.4fr) 70px minmax(180px, 1fr) auto; align-items: center; gap: 16px; min-height: 76px; border-bottom: 1px solid var(--line); }
.serviceLead { display: flex; align-items: center; gap: 11px; > span { width: 8px; height: 8px; border-radius: 50%; background: #69dda1; &[data-tone="danger"] { background: #f17888; } } small { display: block; margin-top: 4px; color: var(--muted); font-size: 11px; } }
.serviceDetail { overflow: hidden; color: var(--muted); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.pathPanel { display: flex; flex-direction: column; gap: 1px; margin-top: 20px; border: 1px solid var(--line); border-radius: 12px; background: var(--panel); > div { display: grid; grid-template-columns: 150px minmax(0, 1fr) auto; gap: 12px; align-items: center; padding: 12px 15px; border-bottom: 1px solid var(--line); &:last-child { border-bottom: 0; } span { color: var(--muted); font-size: 11px; } code { overflow-wrap: anywhere; color: #d9d5e5; font-size: 11px; } } }
.cloudHero, .taskSnapshot { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin: 20px 0; }
.cloudHero > div, .taskSnapshot > div { display: flex; flex-direction: column; gap: 7px; padding: 20px; border: 1px solid var(--line); border-radius: 12px; background: var(--panel); span { color: var(--muted); font-size: 11px; } strong { font-size: 28px; font-weight: 570; } .online { color: #69dda1; } .offline { color: #f17888; } }
.taskSnapshot { grid-template-columns: repeat(3, 1fr); h3, p { grid-column: 1 / -1; margin: 0; } p { color: var(--muted); font-size: 11px; line-height: 1.6; } }
.logToolbar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 12px; .el-input { min-width: 240px; flex: 1; } }
.logView { min-height: 360px; max-height: calc(100dvh - 270px); overflow: auto; margin: 0; padding: 15px; border: 1px solid var(--line); border-radius: 12px; color: #c8c3d4; background: #0b0b0f; font: 11px/1.7 ui-monospace, SFMono-Regular, Consolas, monospace; white-space: pre-wrap; overflow-wrap: anywhere; }
.settingsPanel { border: 1px solid var(--line); border-radius: 12px; background: var(--panel); label { display: flex; justify-content: space-between; align-items: center; gap: 20px; padding: 16px; border-bottom: 1px solid var(--line); &:last-child { border-bottom: 0; } strong { display: block; font-size: 12px; } small { display: block; margin-top: 4px; color: var(--muted); font-size: 11px; } } }
.aboutPanel { max-width: 760px; border: 1px solid var(--line); border-radius: 15px; padding: 25px; background: var(--panel); dl { margin: 24px 0; div { display: grid; grid-template-columns: 120px minmax(0, 1fr); gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--line); } dt { color: var(--muted); font-size: 11px; } dd { margin: 0; font-size: 12px; overflow-wrap: anywhere; } } }
.wizard { display: flex; flex-direction: column; gap: 16px; p { margin: 0; color: var(--el-text-color-secondary); line-height: 1.7; } }
.wizardPath { display: flex; gap: 12px; padding: 14px; border-radius: 10px; background: var(--el-fill-color-light); strong, code, small { display: block; } code { margin: 7px 0; overflow-wrap: anywhere; } small { color: var(--el-text-color-secondary); } }
.wizardChecks { display: flex; flex-wrap: wrap; gap: 8px 15px; color: var(--el-text-color-secondary); font-size: 11px; span { display: inline-flex; align-items: center; gap: 5px; } }
@media (max-width: 1050px) { .statusGrid { grid-template-columns: repeat(3, minmax(0, 1fr)); } .readiness { grid-template-columns: 1fr; } .signalPanel { display: none; } .serviceRow { grid-template-columns: minmax(200px, 1fr) auto; } .serviceDetail { grid-column: 1 / -1; } }
@media (max-width: 760px) { .topbar { align-items: flex-start; flex-direction: column; } .launcherLayout { grid-template-columns: 1fr; } .rail { flex-direction: row; overflow-x: auto; padding: 10px 12px; border-right: 0; border-bottom: 1px solid var(--line); button { width: auto; white-space: nowrap; } .railFoot { flex-direction: row; margin: 0 0 0 auto; padding: 0; border: 0; } } .content { padding: 24px 16px 50px; } .statusGrid, .cloudHero, .taskSnapshot { grid-template-columns: 1fr 1fr; } .startupSteps li { grid-template-columns: 28px minmax(0, 1fr); .stepState { display: none; } } }
@media (max-width: 520px) { .topActions .el-button:last-child { display: none; } .statusGrid, .cloudHero, .taskSnapshot { grid-template-columns: 1fr; } .readiness { padding: 22px; } }
@media (prefers-reduced-motion: reduce) { .rail button { transition: none; } }
</style>