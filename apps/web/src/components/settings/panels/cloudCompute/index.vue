<template>
  <section class="cloudCompute" aria-label="云端算力中心">
    <header class="hero">
      <div>
        <span class="eyebrow">UNIFIED COMFYUI RUNTIME</span>
        <h3>云端算力中心</h3>
        <p>统一连接本地、局域网和任意兼容 ComfyUI API 的云端实例。平台名称只是标签，不决定协议实现。</p>
      </div>
      <el-button type="primary" :icon="IconPlus" @click="openInstance()">添加实例</el-button>
    </header>

    <el-tabs v-model="activeTab" class="hubTabs" @tabChange="onTabChange">
      <el-tab-pane label="算力实例" name="instances">
        <div class="toolbar">
          <el-text type="info">{{ instances.length }} 个实例 · {{ onlineCount }} 个在线</el-text>
          <el-button :icon="IconRefresh" :loading="loadingInstances" @click="loadInstances">刷新</el-button>
        </div>
        <div class="instanceGrid">
          <article v-for="item in instances" :key="item.id" class="instanceCard" :class="{ disabled: !item.enabled }">
            <div class="cardTop">
              <div class="instanceIdentity">
                <span class="instanceIcon"><icon-cloud :size="20" /></span>
                <div><strong>{{ item.name }}</strong><small>{{ item.platformLabel }}{{ item.group ? ` · ${item.group}` : '' }}</small></div>
              </div>
              <el-tag :type="healthType(item)" effect="plain">{{ healthLabel(item) }}</el-tag>
            </div>
            <code class="endpoint">{{ item.endpoint }}</code>
            <div class="metaRow">
              <span>{{ item.favorite ? '已收藏' : '普通实例' }}</span>
              <span>优先级 {{ item.priority }}</span>
              <span>{{ item.hasCredential ? '已保存凭据' : '无凭据' }}</span>
              <span v-if="item.health?.latency !== undefined">{{ item.health.latency }} ms</span>
            </div>
            <div class="cardTags" v-if="item.tags.length"><el-tag v-for="tag in item.tags" :key="tag" size="small">{{ tag }}</el-tag></div>
            <div class="cardActions">
              <el-button size="small" :icon="IconPlugConnected" :loading="testingId === item.id" @click="test(item.id)">测试连接</el-button>
              <el-button size="small" :icon="IconEdit" @click="openInstance(item)">编辑</el-button>
              <el-button size="small" :icon="IconTrash" type="danger" plain @click="removeInstance(item)">删除</el-button>
            </div>
            <div v-if="details[item.id]" class="details">
              <span>{{ details[item.id]!.nodeCount }} 个节点</span>
              <span>{{ details[item.id]!.health?.websocket === 'connected' ? 'WebSocket 可用' : 'HTTP 轮询回退' }}</span>
              <span v-if="details[item.id]!.health?.version">v{{ details[item.id]!.health?.version }}</span>
              <span v-if="details[item.id]!.health?.queueRunning !== undefined">运行 {{ details[item.id]!.health?.queueRunning }}</span>
              <span v-if="details[item.id]!.health?.queuePending !== undefined">排队 {{ details[item.id]!.health?.queuePending }}</span>
            </div>
          </article>
          <button type="button" class="addCard" @click="openInstance()"><icon-plus :size="28" /><span>连接新的 ComfyUI 实例</span></button>
        </div>
      </el-tab-pane>

      <el-tab-pane label="工作流库" name="workflows">
        <div class="toolbar">
          <el-text type="info">{{ workflows.length }} 个工作流</el-text>
          <div class="toolbarActions">
            <el-button :icon="IconRefresh" :loading="loadingWorkflows" @click="loadWorkflows">刷新</el-button>
            <el-button type="primary" :icon="IconUpload" @click="openWorkflowImport">导入工作流</el-button>
          </div>
        </div>
        <div class="workflowGrid">
          <article v-for="item in workflows" :key="item.id" class="workflowCard">
            <div class="cardTop">
              <div><strong>{{ item.name }}</strong><small>{{ item.category }} · v{{ item.version }}</small></div>
              <el-tag effect="plain">{{ typeLabel[item.type] }}</el-tag>
            </div>
            <p>{{ item.description || '暂无说明' }}</p>
            <div class="metaRow"><span>{{ item.nodeCount }} 个节点</span><span>{{ item.format.toUpperCase() }}</span><span>{{ sourceLabel(item.sourceType) }}</span></div>
            <div class="requiredNodes" v-if="item.requiredNodes.length"><el-tag v-for="node in item.requiredNodes.slice(0, 5)" :key="node" size="small" type="info">{{ node }}</el-tag><el-text v-if="item.requiredNodes.length > 5" type="info">+{{ item.requiredNodes.length - 5 }}</el-text></div>
            <div class="verifyRow">
              <el-select v-model="verifyInstance[item.id]" size="small" placeholder="选择实例检测" clearable>
                <el-option v-for="instance in instances" :key="instance.id" :label="instance.name" :value="instance.id" />
              </el-select>
              <el-button size="small" :icon="IconShieldCheck" :disabled="!verifyInstance[item.id]" @click="verify(item.id)">兼容检测</el-button>
            </div>
            <div v-if="compatibility[item.id]" class="compatibility" :data-ok="compatibility[item.id]!.compatible">
              <span v-if="compatibility[item.id]!.compatible">当前实例可运行此工作流</span>
              <span v-else>缺少节点：{{ compatibility[item.id]!.missingNodes.join('、') || '无' }}<template v-if="compatibility[item.id]!.missingModels.length">；缺少模型：{{ compatibility[item.id]!.missingModels.join('、') }}</template></span>
            </div>
            <div class="cardActions">
              <el-button size="small" :icon="IconVersions" @click="openWorkflowVersion(item)">新版本</el-button>
              <el-button v-if="item.sourceType !== 'local' && item.sourceRef" size="small" :icon="IconRefresh" :loading="syncingWorkflow === item.id" @click="syncWorkflow(item)">同步来源</el-button>
              <el-button size="small" :icon="IconTrash" type="danger" plain @click="removeWorkflow(item)">删除</el-button>
            </div>
          </article>
          <button type="button" class="addCard workflowAdd" @click="openWorkflowImport"><icon-upload :size="26" /><span>导入 API 或 UI 工作流 JSON</span></button>
        </div>
      </el-tab-pane>

      <el-tab-pane label="任务监控" name="tasks">
        <div class="toolbar">
          <el-text type="info">只读展示现有统一媒体任务记录，不另建任务系统</el-text>
          <el-button :icon="IconRefresh" :loading="loadingTasks" @click="loadTasks">刷新</el-button>
        </div>
        <div class="taskList">
          <article v-for="task in tasks" :key="task.taskId" class="taskRow">
            <div><code>{{ task.taskId }}</code><small>{{ task.workflowId }}</small></div>
            <el-tag :type="stateType(task.state)" size="small">{{ stateLabel(task.state) }}</el-tag>
            <span>{{ task.mediaType }}</span>
            <span>{{ task.instanceId || '实例未记录' }}</span>
            <span>{{ task.promptId || '未提交' }}</span>
            <small>{{ new Date(task.updatedAt).toLocaleString() }}</small>
          </article>
          <el-empty v-if="!tasks.length" description="暂无云端 ComfyUI 任务" />
        </div>
      </el-tab-pane>
      <el-tab-pane label="连接说明" name="guide">
        <div class="guide">
          <h4>一个连接器，多个平台</h4>
          <p>仙宫云、晨羽、优云智算、RunningHub 或其他平台，只要实例暴露标准 ComfyUI API，就填写其 ComfyUI 服务地址即可。平台生命周期开关机不属于 ComfyUI 标准 API，SoloDrama 不会调用未经确认的私有接口。</p>
          <ul>
            <li>默认探测 `/system_stats`、`/object_info`、`/queue`、`/features` 和 `/ws`。</li>
            <li>WebSocket 不可用时自动使用 `/history/{prompt_id}` 轮询。</li>
            <li>排队任务按 `prompt_id` 精确删除；运行中任务不会发送全局 interrupt。</li>
            <li>本机和局域网地址默认禁止，需要在实例配置中明确允许。</li>
          </ul>
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="instanceDialog" :title="instanceForm.id ? '编辑 ComfyUI 实例' : '添加 ComfyUI 实例'" width="min(760px, calc(100vw - 32px))" appendToBody>
      <el-form labelPosition="top" :disabled="savingInstance">
        <div class="formGrid">
          <el-form-item label="实例名称" required><el-input v-model="instanceForm.name" maxlength="120" /></el-form-item>
          <el-form-item label="平台标签"><el-input v-model="instanceForm.platformLabel" maxlength="120" placeholder="例如：仙宫云、晨羽、优云智算" /></el-form-item>
        </div>
        <el-form-item label="ComfyUI API 地址" required><el-input v-model="instanceForm.endpoint" dir="ltr" placeholder="https://example.com/comfyui" /></el-form-item>
        <el-form-item label="WebSocket 地址（可选）"><el-input v-model="instanceForm.websocketEndpoint" dir="ltr" placeholder="留空自动推导为 ws(s)://.../ws" /></el-form-item>
        <div class="formGrid">
          <el-form-item label="鉴权方式">
            <el-select v-model="instanceForm.authMode"><el-option label="无需鉴权" value="none" /><el-option label="Bearer Token" value="bearer" /><el-option label="自定义 Header" value="header" /></el-select>
          </el-form-item>
          <el-form-item v-if="instanceForm.authMode === 'header'" label="鉴权 Header 名称"><el-input v-model="instanceForm.authHeaderName" dir="ltr" /></el-form-item>
        </div>
        <el-form-item v-if="instanceForm.authMode !== 'none'" :label="instanceForm.id ? 'Token / 凭据（留空保留原值）' : 'Token / 凭据'">
          <el-input v-model="instanceForm.token" type="password" showPassword autocomplete="off" />
        </el-form-item>
        <el-form-item label="自定义请求 Header JSON"><el-input v-model="instanceForm.customHeaders" type="textarea" :rows="3" dir="ltr" placeholder='{"X-API-Key":"..."}' /></el-form-item>
        <div class="formGrid three">
          <el-form-item label="连接超时 ms"><el-input-number v-model="instanceForm.connectionTimeoutMs" :min="1000" :max="300000" :step="1000" /></el-form-item>
          <el-form-item label="调度优先级"><el-input-number v-model="instanceForm.priority" :min="-1000" :max="1000" /></el-form-item>
          <el-form-item label="分组"><el-input v-model="instanceForm.group" maxlength="120" /></el-form-item>
        </div>
        <el-form-item label="标签"><el-input v-model="instanceForm.tags" placeholder="逗号分隔" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="instanceForm.note" type="textarea" :rows="2" maxlength="4000" /></el-form-item>
        <div class="switches">
          <el-checkbox v-model="instanceForm.enabled">启用实例</el-checkbox>
          <el-checkbox v-model="instanceForm.favorite">收藏</el-checkbox>
          <el-checkbox v-model="instanceForm.allowPrivateNetwork">允许本机/局域网地址</el-checkbox>
        </div>
      </el-form>
      <template #footer><el-button :disabled="savingInstance" @click="instanceDialog = false">取消</el-button><el-button type="primary" :loading="savingInstance" @click="saveInstance">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="workflowDialog" :title="workflowForm.id ? '更新工作流版本' : '导入 ComfyUI 工作流'" width="min(880px, calc(100vw - 32px))" appendToBody>
      <el-form labelPosition="top" :disabled="savingWorkflow">
        <div class="formGrid">
          <el-form-item label="工作流名称" required><el-input v-model="workflowForm.name" maxlength="160" /></el-form-item>
          <el-form-item label="媒体类型"><el-select v-model="workflowForm.type"><el-option label="图片" value="image" /><el-option label="视频" value="video" /><el-option label="音频" value="audio" /></el-select></el-form-item>
        </div>
        <div class="formGrid">
          <el-form-item label="分类"><el-input v-model="workflowForm.category" maxlength="120" /></el-form-item>
          <el-form-item label="必需模型（逗号分隔）"><el-input v-model="workflowForm.requiredModels" placeholder="无法可靠自动检测时由你明确填写" /></el-form-item>
        </div>
        <el-form-item label="说明"><el-input v-model="workflowForm.description" type="textarea" :rows="2" maxlength="4000" /></el-form-item>
        <template v-if="!workflowForm.id">
          <el-form-item label="来源"><el-select v-model="workflowForm.sourceType"><el-option label="本地 JSON" value="local" /><el-option label="HTTP 地址" value="http" /><el-option label="Git 仓库" value="git" /><el-option label="S3 兼容预签名 URL" value="s3" /></el-select></el-form-item>
          <el-form-item v-if="workflowForm.sourceType === 'local'" label="工作流 JSON" required><el-input v-model="workflowForm.content" type="textarea" :rows="12" dir="ltr" /></el-form-item>
          <template v-else>
            <el-form-item :label="workflowForm.sourceType === 'git' ? 'Git HTTPS 地址' : '工作流 URL'" required><el-input v-model="workflowForm.url" dir="ltr" /></el-form-item>
            <div v-if="workflowForm.sourceType === 'git'" class="formGrid">
              <el-form-item label="仓库内文件路径" required><el-input v-model="workflowForm.filePath" dir="ltr" placeholder="workflows/image.json" /></el-form-item>
              <el-form-item label="分支（可选）"><el-input v-model="workflowForm.branch" dir="ltr" /></el-form-item>
            </div>
          </template>
        </template>
        <el-form-item v-else label="工作流 JSON" required><el-input v-model="workflowForm.content" type="textarea" :rows="12" dir="ltr" /></el-form-item>
        <el-form-item label="参数映射 JSON"><el-input v-model="workflowForm.mapping" type="textarea" :rows="6" dir="ltr" /></el-form-item>
      </el-form>
      <template #footer><el-button :disabled="savingWorkflow" @click="workflowDialog = false">取消</el-button><el-button type="primary" :loading="savingWorkflow" @click="saveWorkflow">保存工作流</el-button></template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { IconCloud, IconEdit, IconPlugConnected, IconPlus, IconRefresh, IconShieldCheck, IconTrash, IconUpload, IconVersions } from "@tabler/icons-vue";
import http from "@/lib/http";

type Health = { status: "online" | "offline" | "degraded" | "unknown"; checkedAt: number; latency?: number; version?: string; nodeCount?: number; queueRunning?: number; queuePending?: number; websocket?: "connected" | "unavailable" | "unknown"; error?: string };
type Instance = { id: string; name: string; platformLabel: string; endpoint: string; websocketEndpoint?: string; authMode: "none" | "bearer" | "header"; authHeaderName?: string; hasCredential: boolean; headerNames: string[]; allowPrivateNetwork: boolean; connectionTimeoutMs: number; priority: number; enabled: boolean; favorite: boolean; group?: string; tags: string[]; note?: string; health?: Health; createdAt: number; updatedAt: number };
type HubTask = { taskId: string; state: "running" | "interrupted" | "succeeded" | "failed" | "cancelled"; submissionState?: "submitting" | "submitted" | "accepted" | "unknown"; mediaType: "image" | "video" | "audio"; workflowId: string; instanceId?: string; promptId?: string; createdAt: number; updatedAt: number };
type Workflow = { id: string; name: string; description: string; category: string; type: "image" | "video" | "audio"; format: "api" | "ui"; mapping: string; requiredNodes: string[]; requiredModels: string[]; sourceType: "local" | "http" | "git" | "s3" | "market"; sourceRef?: string; sourceConfig?: Record<string, unknown>; version: number; nodeCount: number; updatedAt: number };
type InstanceState = { revision: number; items: Instance[] };
type WorkflowState = { revision: number; items: Workflow[] };

const activeTab = ref("instances");
const instances = ref<Instance[]>([]);
const workflows = ref<Workflow[]>([]);
const tasks = ref<HubTask[]>([]);
const instanceRevision = ref(0);
const workflowRevision = ref(0);
const loadingInstances = ref(false);
const loadingWorkflows = ref(false);
const loadingTasks = ref(false);
const testingId = ref("");
const details = reactive<Record<string, { nodeCount: number; health?: Health; features: string[] }>>({});
const verifyInstance = reactive<Record<string, string>>({});
const compatibility = reactive<Record<string, { compatible: boolean; missingNodes: string[]; missingModels: string[] }>>({});
const onlineCount = computed(() => instances.value.filter(item => item.health?.status === "online" || item.health?.status === "degraded").length);
const typeLabel = { image: "图片", video: "视频", audio: "音频" } as const;
const healthType = (item: Instance) => item.health?.status === "online" ? "success" : item.health?.status === "degraded" ? "warning" : item.health?.status === "offline" ? "danger" : "info";
const healthLabel = (item: Instance) => item.health?.status === "online" ? "在线" : item.health?.status === "degraded" ? "可用（降级）" : item.health?.status === "offline" ? "离线" : "未检测";
const sourceLabel = (value: Workflow["sourceType"]) => ({ local: "本地", http: "HTTP", git: "Git", s3: "S3", market: "市场扩展" })[value];
const stateLabel = (value: HubTask["state"]) => ({ running: "运行中", interrupted: "待恢复", succeeded: "已完成", failed: "失败", cancelled: "已取消" })[value];
const stateType = (value: HubTask["state"]): "success" | "warning" | "danger" | "info" => value === "succeeded" ? "success" : value === "failed" ? "danger" : value === "running" ? "warning" : "info";

const instanceDialog = ref(false);
const savingInstance = ref(false);
const instanceForm = reactive({ id: "", name: "", platformLabel: "", endpoint: "", websocketEndpoint: "", authMode: "none" as Instance["authMode"], authHeaderName: "", token: "", customHeaders: "", allowPrivateNetwork: false, connectionTimeoutMs: 15000, priority: 0, enabled: true, favorite: false, group: "", tags: "", note: "" });
const workflowDialog = ref(false);
const savingWorkflow = ref(false);
const syncingWorkflow = ref("");
const workflowForm = reactive({ id: "", name: "", description: "", category: "通用", type: "image" as Workflow["type"], sourceType: "local" as "local" | "http" | "git" | "s3", content: "", url: "", filePath: "", branch: "", mapping: "{}", requiredModels: "" });

function resetInstanceForm(item?: Instance) {
  Object.assign(instanceForm, { id: item?.id ?? "", name: item?.name ?? "", platformLabel: item?.platformLabel ?? "", endpoint: item?.endpoint ?? "", websocketEndpoint: item?.websocketEndpoint ?? "", authMode: item?.authMode ?? "none", authHeaderName: item?.authHeaderName ?? "", token: "", customHeaders: "", allowPrivateNetwork: item?.allowPrivateNetwork ?? false, connectionTimeoutMs: item?.connectionTimeoutMs ?? 15000, priority: item?.priority ?? 0, enabled: item?.enabled ?? true, favorite: item?.favorite ?? false, group: item?.group ?? "", tags: item?.tags.join(", ") ?? "", note: item?.note ?? "" });
}
function openInstance(item?: Instance) { resetInstanceForm(item); instanceDialog.value = true; }
function parseHeaders(value: string) {
  if (!value.trim()) return undefined;
  const parsed: unknown = JSON.parse(value);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed) || Object.values(parsed).some(item => typeof item !== "string")) throw new Error("自定义 Header 必须是字符串 JSON 对象");
  return parsed as Record<string, string>;
}
async function saveInstance() {
  if (savingInstance.value) return;
  savingInstance.value = true;
  try {
    await http<Instance>({ method: "PUT", url: "/api/comfyHub/instances/save", data: { ...instanceForm, id: instanceForm.id || undefined, token: instanceForm.authMode === "none" ? "" : instanceForm.token || undefined, customHeaders: parseHeaders(instanceForm.customHeaders), tags: instanceForm.tags.split(",").map(item => item.trim()).filter(Boolean), expectedRevision: instanceRevision.value } });
    instanceDialog.value = false;
    ElMessage.success("实例已保存");
    await loadInstances();
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : "保存实例失败"); }
  finally { savingInstance.value = false; }
}
async function test(id: string) {
  testingId.value = id;
  try {
    const result = await http<{ health: Health; nodeNames: string[]; features: string[] }>({ method: "POST", url: "/api/comfyHub/instances/test", data: { id } });
    details[id] = { nodeCount: result.nodeNames.length, health: result.health, features: result.features };
    ElMessage.success(result.health.status === "offline" ? result.health.error || "连接失败" : "连接检测完成");
    await loadInstances();
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : "连接检测失败"); }
  finally { testingId.value = ""; }
}
async function removeInstance(item: Instance) {
  try {
    await ElMessageBox.confirm(`确定删除实例“${item.name}”？已有任务恢复信息将无法继续使用该实例。`, "删除实例", { type: "warning" });
    await http({ method: "DELETE", url: "/api/comfyHub/instances/delete", data: { id: item.id, expectedRevision: instanceRevision.value } });
    await loadInstances();
  } catch (error) { if (error !== "cancel" && error !== "close") ElMessage.error(error instanceof Error ? error.message : "删除实例失败"); }
}
async function loadInstances() {
  loadingInstances.value = true;
  try { const value = await http<InstanceState>({ method: "GET", url: "/api/comfyHub/instances/list" }); instances.value = value.items; instanceRevision.value = value.revision; }
  catch (error) { ElMessage.error(error instanceof Error ? error.message : "读取实例失败"); }
  finally { loadingInstances.value = false; }
}

function resetWorkflowForm() { Object.assign(workflowForm, { id: "", name: "", description: "", category: "通用", type: "image", sourceType: "local", content: "", url: "", filePath: "", branch: "", mapping: "{}", requiredModels: "" }); }
function openWorkflowImport() { resetWorkflowForm(); workflowDialog.value = true; }
async function openWorkflowVersion(item: Workflow) {
  try {
    const current = await http<Workflow & { apiWorkflow: string }>({ method: "GET", url: "/api/comfyHub/workflows/get", params: { id: item.id } });
    Object.assign(workflowForm, { id: item.id, name: item.name, description: item.description, category: item.category, type: item.type, sourceType: "local", content: current.apiWorkflow, url: "", filePath: "", branch: "", mapping: current.mapping, requiredModels: item.requiredModels.join(", ") });
    workflowDialog.value = true;
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : "读取工作流失败"); }
}
async function saveWorkflow() {
  if (savingWorkflow.value) return;
  savingWorkflow.value = true;
  try {
    const requiredModels = workflowForm.requiredModels.split(",").map(item => item.trim()).filter(Boolean);
    if (workflowForm.id) await http({ method: "PUT", url: "/api/comfyHub/workflows/save", data: { id: workflowForm.id, name: workflowForm.name, description: workflowForm.description, category: workflowForm.category, type: workflowForm.type, workflow: workflowForm.content, mapping: workflowForm.mapping, requiredModels, sourceType: "local", expectedRevision: workflowRevision.value } });
    else await http({ method: "POST", url: "/api/comfyHub/workflows/import", data: { name: workflowForm.name, description: workflowForm.description, category: workflowForm.category, type: workflowForm.type, sourceType: workflowForm.sourceType, content: workflowForm.sourceType === "local" ? workflowForm.content : undefined, url: workflowForm.sourceType === "local" ? undefined : workflowForm.url, filePath: workflowForm.filePath || undefined, branch: workflowForm.branch || undefined, mapping: workflowForm.mapping, requiredModels, expectedRevision: workflowRevision.value } });
    workflowDialog.value = false;
    ElMessage.success("工作流已保存");
    await loadWorkflows();
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : "保存工作流失败"); }
  finally { savingWorkflow.value = false; }
}
async function verify(id: string) { try { compatibility[id] = await http({ method: "POST", url: "/api/comfyHub/workflows/verify", data: { workflowId: id, instanceId: verifyInstance[id] } }); } catch (error) { ElMessage.error(error instanceof Error ? error.message : "兼容检测失败"); } }
async function syncWorkflow(item: Workflow) {
  if (!item.sourceRef || item.sourceType === "local") return;
  syncingWorkflow.value = item.id;
  try {
    const config = item.sourceConfig ?? {};
    await http({ method: "POST", url: "/api/comfyHub/workflows/sync", data: { id: item.id, sourceType: item.sourceType, url: item.sourceRef, filePath: typeof config.filePath === "string" ? config.filePath : undefined, branch: typeof config.branch === "string" ? config.branch : undefined, expectedRevision: workflowRevision.value } });
    ElMessage.success("工作流来源已同步并创建新版本");
    await loadWorkflows();
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : "同步工作流失败"); }
  finally { syncingWorkflow.value = ""; }
}
async function removeWorkflow(item: Workflow) {
  try {
    await ElMessageBox.confirm(`确定删除工作流“${item.name}”及其本地版本历史？`, "删除工作流", { type: "warning" });
    await http({ method: "DELETE", url: "/api/comfyHub/workflows/delete", data: { id: item.id, expectedRevision: workflowRevision.value } });
    await loadWorkflows();
  } catch (error) { if (error !== "cancel" && error !== "close") ElMessage.error(error instanceof Error ? error.message : "删除工作流失败"); }
}
async function loadWorkflows() {
  loadingWorkflows.value = true;
  try { const value = await http<WorkflowState>({ method: "GET", url: "/api/comfyHub/workflows/list" }); workflows.value = value.items; workflowRevision.value = value.revision; }
  catch (error) { ElMessage.error(error instanceof Error ? error.message : "读取工作流失败"); }
  finally { loadingWorkflows.value = false; }
}
async function loadTasks() { loadingTasks.value = true; try { tasks.value = await http<HubTask[]>({ method: "GET", url: "/api/comfyHub/tasks/list" }); } catch (error) { ElMessage.error(error instanceof Error ? error.message : "读取任务失败"); } finally { loadingTasks.value = false; } }
function onTabChange(name: string | number) { if (name === "instances" && !instances.value.length) void loadInstances(); if (name === "workflows" && !workflows.value.length) void loadWorkflows(); if (name === "tasks") void loadTasks(); }
onMounted(() => { void loadInstances(); void loadWorkflows(); });
</script>

<style scoped lang="scss">
.cloudCompute { display: flex; flex-direction: column; gap: 18px; }
.hero { display: flex; justify-content: space-between; align-items: flex-end; gap: 20px; padding: 18px 20px; border: 1px solid var(--el-border-color-lighter); border-radius: calc(var(--ui-radius) * 1.5); background: radial-gradient(circle at 85% 20%, color-mix(in srgb, var(--el-color-primary) 18%, transparent), transparent 35%), var(--el-fill-color-lighter); h3 { margin: 5px 0 7px; font-size: 20px; } p { max-width: 720px; margin: 0; color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.7; } }
.eyebrow { color: var(--el-color-primary); font-size: 10px; letter-spacing: .16em; }
.hubTabs { :deep(.el-tabs__content) { overflow: visible; } }
.toolbar { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 14px; }
.toolbarActions { display: flex; gap: 8px; }
.instanceGrid, .workflowGrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; }
.instanceCard, .workflowCard, .addCard { min-width: 0; padding: 15px; border: 1px solid var(--el-border-color-lighter); border-radius: calc(var(--ui-radius) * 1.4); background: var(--el-bg-color-overlay); }
.instanceCard.disabled { opacity: .68; }
.cardTop { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; strong { display: block; font-size: 14px; } small { display: block; margin-top: 3px; color: var(--el-text-color-secondary); } }
.instanceIdentity { display: flex; gap: 10px; align-items: center; }
.instanceIcon { display: grid; place-items: center; width: 36px; height: 36px; border-radius: 10px; color: var(--el-color-primary); background: var(--el-color-primary-light-9); }
.endpoint { display: block; overflow: hidden; margin: 13px 0 9px; color: var(--el-text-color-secondary); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.metaRow, .cardTags, .details, .requiredNodes, .verifyRow { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; }
.metaRow, .details { color: var(--el-text-color-secondary); font-size: 11px; }
.details { margin-top: 9px; padding-top: 9px; border-top: 1px solid var(--el-border-color-extra-light); }
.cardActions { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 13px; }
.workflowCard p { min-height: 38px; margin: 12px 0; color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.6; }
.requiredNodes { margin: 10px 0; }
.verifyRow { margin-top: 12px; .el-select { flex: 1; min-width: 150px; } }
.compatibility { margin-top: 9px; padding: 8px 10px; border-radius: 7px; color: var(--el-color-danger); background: var(--el-color-danger-light-9); font-size: 11px; line-height: 1.6; &[data-ok="true"] { color: var(--el-color-success); background: var(--el-color-success-light-9); } }
.addCard { display: grid; place-items: center; min-height: 190px; gap: 8px; border-style: dashed; color: var(--el-text-color-secondary); background: transparent; font: inherit; cursor: pointer; &:hover { color: var(--el-color-primary); border-color: var(--el-color-primary); } }
.workflowAdd { min-height: 160px; }
.taskList { display: flex; flex-direction: column; gap: 8px; }
.taskRow { display: grid; grid-template-columns: minmax(240px, 1.4fr) auto repeat(3, minmax(90px, .7fr)) auto; align-items: center; gap: 12px; padding: 10px 12px; border: 1px solid var(--el-border-color-lighter); border-radius: 10px; font-size: 12px; code { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } small, span { color: var(--el-text-color-secondary); } div small { display: block; margin-top: 3px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } }
.guide { max-width: 820px; color: var(--el-text-color-regular); line-height: 1.8; h4 { margin: 0 0 8px; } p, li { color: var(--el-text-color-secondary); font-size: 13px; } }
.formGrid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 14px; &.three { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
.switches { display: flex; flex-wrap: wrap; gap: 14px; }
@media (max-width: 760px) { .taskRow { grid-template-columns: minmax(0, 1fr) auto; } .hero { align-items: flex-start; flex-direction: column; } .formGrid, .formGrid.three { grid-template-columns: minmax(0, 1fr); } .toolbar { align-items: flex-start; flex-direction: column; } }
</style>