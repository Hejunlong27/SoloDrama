# SoloDrama 2.0 独立验收报告

> 验收日期：2026-11-27  
> 验收范围：上一轮架构升级、Provider、ComfyUI、RunningHub、媒体任务、Provider Diagnostics、Workbench、多租户、安全边界与构建链路。  
> 验收原则：重新读取实现并以本轮实际命令和实际运行结果为准；未运行的测试不记为通过。

## 1. 结论

本轮没有发现仍未修复的 P0。发现并在验收中修复了 1 个 P0 权限问题，并补充了云元数据/链路本地地址阻断。

当前不能判定 SoloDrama 2.0 全量验收通过，原因是存在明确未实现的 P1 能力：

- Workbench 独立领域模型、Take 版本管理和领域迁移尚未实现。
- ComfyUI Connection Manager 的多实例注册表、WebSocket、实例健康/队列/GPU/节点能力探测尚未实现。
- 仓库没有自动化测试，也没有 Lint 命令。
- 桌面端完整 typecheck/build 受既有 `.hutch` 生成文件和 `electrobun/main` 类型声明缺失阻断。
- ComfyUI 运行中任务仍无法在无法证明安全时执行远端精确取消，只能停止本地等待。

核心 Provider 稳定性修复、任务持久化、跨进程重复提交防护、队列任务精确取消和 `resumeTask` 恢复在本轮模拟验收中通过。

## 2. 实际运行过的命令

| 命令 | 真实结果 |
|---|---|
| `bun test` | 失败：`No tests found!`，仓库没有测试文件 |
| `bun run lint` | 失败：`Script not found "lint"` |
| `bun run typecheck` | 失败：仅 `@solodrama/desktop` 失败；其余已输出包均 exit 0 |
| `bun run --cwd apps/server typecheck` | 通过 |
| `bun run --cwd apps/web typecheck` | 通过 |
| `bunx tsc -p packages/providers/tsconfig.json --noEmit` | 通过 |
| `bun run build` | 通过，exit 0；保留既有 Vite native configLoader 与大 chunk 警告 |
| `bun run build:desktop` | 失败：缺少 `.hutch/dependencies.lock` |
| `git diff --check` | 通过；只有既有 LF/CRLF 提示，无空白错误 |
| `python migration\import-solodrama-project.py --help` | 通过 |
| `python <临时旧项目 dry-run 探针>` | 通过；读取 1 个旧脚本文档，生成计划 1 个画布节点，`dryRun=true`，未创建输出目录 |
| `bun <临时 ComfyUI 并发验收探针>` | 通过 |
| `bun <临时跨进程任务恢复探针>` | 通过 |
| `bun <临时跨进程重复提交探针>` | 通过 |
| `bun <临时 Provider 权限探针>` | 通过 |
| `bun <临时 API Key 脱敏探针>` | 通过 |
| `bun -e <媒体请求路径安全校验>` | 通过 |
| `bun -e <Provider 元数据地址阻断探针>` | 通过 |

说明：根 `AGENTS.md` 禁止新增测试文件、测试脚本和测试入口，因此行为验收使用 `%TEMP%` 下的临时外部探针执行，没有把测试代码写入仓库。

## 3. 详细验收结果

### 3.1 ComfyUI 多任务并发、精确取消、断线恢复

模拟 ComfyUI 服务同时具有：

- 运行中任务 B。
- 排队中任务 A。
- `/queue`、`/history/{promptId}`、`/interrupt` 和 `/view`。

实际结果：

```json
{
  "taskA": "cancel A",
  "taskBBytes": 68,
  "deletedA": true,
  "interrupts": 0,
  "resumedBytes": 68
}
```

结论：

- A 在排队态被精确删除。
- B 同时在运行并正常完成，输出 68 字节 PNG。
- 取消过程没有调用 `/interrupt`，不存在误伤 B 的全局中断。
- 使用保存的 `promptId` 新建 Provider 后调用 `resumeTask()`，成功下载 68 字节结果，断线后的 HTTP 恢复通过。
- 独立上传探针中两个同名参考图得到不同 UUID 文件名，`overwrite` 均为 `false`，任务取消仍只删除 A。

未验证：

- 真实 ComfyUI 不同版本对 `/queue` 结构的差异。
- WebSocket 实时进度和断线重连，因为当前没有 WebSocket Connection Manager。
- 运行中任务的远端精确取消，因为当前实现只确认排队项，运行中项只停止本地等待。

### 3.2 任务持久化、重复提交防护、服务重启恢复

#### 同一进程重复提交

同一 `taskId` 重复调用返回同一任务，上游只有一次生成调用。

#### 跨进程重复提交

两个独立 Bun 进程同时启动同一 `taskId`：

```json
{
  "code1": 0,
  "code2": 0,
  "out1": "{\"ok\":true,\"taskId\":\"2a74ad36-...\",\"state\":\"running\"}",
  "out2": "{\"ok\":true,\"taskId\":\"2a74ad36-...\",\"state\":\"running\"}",
  "submits": 1
}
```

结论：两个进程获得同一个任务 ID，模拟上游提交次数为 1，跨进程重复提交防护通过。

#### 异常退出后恢复

进程 1：

- 创建并持久化任务。
- 上游提交一次。
- 保存 `providerData` 和 `submissionState=accepted`。
- 模拟进程异常退出，未执行正常任务收尾。

进程 2：

- 重新读取同一任务 JSON。
- `resumeCalls=1`。
- 恢复到 `succeeded`。
- 输出文件 68 字节 PNG。

关键结果：

```json
{
  "persistedState": "running",
  "submissionState": "accepted",
  "submitCalls": 1,
  "resumeCalls": 1,
  "resumeState": "succeeded"
}
```

结论：单进程 JSON 任务记录在新进程中可以恢复，且没有重新调用生成提交。

未验证：

- 真实操作系统强杀服务器主进程并由桌面/服务管理器重新拉起，本次是受控子进程异常退出模拟。
- 多实例同时轮询、取消同一任务的分布式租约。
- 数据库型 Task Repository 和任务事件。

### 3.3 Provider 权限、API Key、SSRF、文件上传安全

#### Provider 管理权限

验收发现并修复 P0：

- 旧的 Provider 新增、保存、删除、模型刷新、源码读取、源码校验、调试和诊断路由此前主要依赖页面来源或可伪造 Header。
- 远程调用者可以伪造这些条件并写入/执行 Provider 源码。
- 现已统一要求 `isLocalWorkspaceRequest(req)`；前端对应请求补充了 `x-solodrama-workspace: 1`。

实际权限探针结果：

```json
{
  "remoteAdd": [403, "请在桌面端或服务器本机管理媒体供应商"],
  "noHeaderAdd": [403, "请在桌面端或服务器本机管理媒体供应商"],
  "localAdd": [200, 200],
  "remoteDiagnostic": [403, "请在桌面端或服务器本机诊断供应商"],
  "localDiagnostic": [200, "healthy"]
}
```

结论：远程/无 Header 写入被拒绝，本机合法页面仍可使用。

#### API Key 脱敏

调试运行器收到含 API Key 的错误：

```json
[{"type":"error","message":"invalid apiKey=\"••••••\"","duration":19}]
```

结论：原始 Key 未出现在事件正文中，脱敏有效。

#### SSRF

本轮新增 `providerUrl.ts`：

- 拒绝 URL 内嵌账号密码。
- 拒绝非 HTTP(S) 地址。
- 拒绝 IPv4 `169.254.0.0/16`。
- 拒绝 IPv6 `fe80::/10`。
- 拒绝已知元数据主机名。

实际访问 `http://169.254.169.254/latest/meta-data` 在发起请求前被拒绝：

```text
供应商请求不能访问链路本地或云元数据地址
```

仍存在边界：

- DNS 解析后指向链路本地地址的域名未被异步复核。
- Provider 自身使用 `redirect: follow` 时，最终重定向目标未被重新校验。
- 自定义 Provider 代码仍属于本机管理员信任边界，应继续使用独立进程/容器作为未来强隔离方案。

#### 文件与路径

媒体请求 Schema 实测：

```json
[false, false, true]
```

分别表示：

- `../secret.png` 被拒绝。
- `text/plain` 作为图片引用被拒绝。
- 合法的 `assets/a.png` 加 `image/png` 被接受。

ComfyUI 上传使用任务唯一文件名并设置 `overwrite=false`。

### 3.4 Provider Diagnostics

接口和现有测试面板已存在：

```text
POST /api/providers/diagnostics/run
```

本机合法请求在模拟上游返回：

- HTTP 200。
- `status=healthy`。
- 检查项覆盖配置、连接、鉴权、模型和能力。

诊断实际生成检查保持 `skipped`，必须由用户主动点击现有“开始测试”触发，未擅自产生费用。

### 3.5 Workbench 数据模型、旧项目迁移、Take

静态复读结果：

- `workbenchPanel.vue` 仍从画布节点的类型、标签关键词、连边和 `outputs` 推导工作台数据。
- 项目配置仍只有 `.solodrama/project.json` 的项目规格。
- 仓库中未发现 `DramaProject`、`DramaEpisode`、`DramaScene`、`DramaShot`、`ShotTake`、`CanvasDomainReference` 的实际实现。
- 未发现 Take 创建、选择、比较、正式版本锁定或历史恢复逻辑。
- 未发现从旧画布迁移到 Workbench 领域实体的领域迁移器。

旧项目导入器 dry-run 实际通过：

```json
{
  "scripts": 1,
  "nodeCount": 1,
  "edgeCount": 0,
  "dryRun": true
}
```

但它生成的是原生画布节点，不是 Workbench Episode/Scene/Shot/Character/Take 领域模型。

结论：Workbench Domain Model 与 Take 版本管理未实现，属于 P1 未解决项。

### 3.6 TODO、Mock、临时实现检查

对本轮新增/修改模块搜索 `TODO`、`FIXME`、`HACK`、`mock`、`临时`、`未实现`：

- 未发现未标记的 TODO/FIXME。
- Provider Diagnostics 的生成检查明确标记为 `skipped`，是有意的安全设计，不是伪造成功。
- Workbench 领域能力不是以 TODO 占位存在，而是确实尚未实现。
- `providerTestPanel` 使用临时本地诊断统计，不涉及密钥。

## 4. 已修复问题

### P0

1. **Provider 代码写入与调试接口未强制执行本机权限**
   - 影响：远程或伪造页面来源请求可能写入/执行服务端 Provider 源码。
   - 修复：新增、保存、删除、模型刷新、源码、校验、调试、诊断和文本模型列表统一要求本机工作区请求。
   - 前端：相关请求补齐 `x-solodrama-workspace: 1`。
   - 验证：远程和无 Header 请求均为 403，本机请求为 200。

### P1 安全加固

2. **Provider 网络请求未阻断云元数据/链路本地地址**
   - 修复：新增 `providerUrl.ts`，覆盖 Provider 普通 fetch、查询 fetch、媒体工具、模型刷新和生成结果下载。
   - 验证：`169.254.169.254` 在请求前被拒绝。

## 5. 未解决问题

### P1

1. **Workbench 独立领域模型未实现**
   - 缺少 Project、Episode、Scene、Shot、Character、Location、Prop、Asset、Take 的稳定 ID 和持久化关系。
   - 当前仍以画布节点推导业务视图。

2. **Take 版本管理未实现**
   - 无法创建多个 Take、选中正式 Take、锁定已选版本、记录参数快照或从历史版本恢复。

3. **Workbench 领域迁移未实现**
   - 现有旧项目导入器只生成画布，不生成领域实体。
   - Canvas 与领域实体没有稳定 ID 关联。

4. **ComfyUI Connection Manager 未实现**
   - 多实例注册、实例健康、GPU、队列、节点能力和工作流版本管理缺失。
   - WebSocket、心跳、重连和 HTTP fallback 缺失。
   - 当前仍为 HTTP 轮询。

5. **运行中 ComfyUI 任务远端精确取消未实现**
   - 排队任务可精确删除。
   - 运行中任务只停止本地等待；远端是否继续执行不确定。
   - 未发送无 `prompt_id` 的全局 `/interrupt`，因此没有误伤其他任务，但也没有证明远端已取消。

6. **没有自动化测试**
   - `bun test` 未发现测试文件。
   - 根规范禁止新增测试模块，导致核心回归无法形成持续 CI 门禁。

7. **没有 Lint 入口**
   - `bun run lint` 无脚本。
   - 仓库未发现 ESLint、Biome、Oxlint 等可执行配置。

8. **桌面端类型检查与完整构建失败**
   - `electrobun/main` 缺少声明，产生 TS7016 和隐式 any。
   - `.hutch/dependencies.lock` 缺失，桌面 build 在运行时准备阶段失败。
   - 其余已输出工作区 typecheck 均通过。

9. **SSRF 防护仍有 DNS/重定向边界**
   - 当前阻断已知主机和直接链路本地 IP。
   - 未完成 DNS 解析后 IP 钉扎和重定向逐跳复核。

10. **任务运行时仍为单进程文件记录**
    - 跨进程重复提交测试通过，但没有共享租约、跨实例调度、数据库任务仓库或分布式取消。

### P2

1. Diagnostics 历史仅保存在当前浏览器 localStorage，不是跨设备健康状态。
2. Diagnostics 检查项状态在 UI 中仍显示英文枚举值。
3. 没有真实 Provider 健康状态历史表或最近错误服务端聚合。
4. Web/Server 生产构建保留大 chunk 和 Vite native configLoader 警告。
5. Provider URL 策略尚未提供可配置的企业网络白名单/黑名单。

### P3

1. 为 Provider Diagnostics 增加服务端指标聚合和趋势。
2. 为任务中心增加事件流、耗时、重试建议和审计导出。
3. 为领域模型和 Task Runtime 建立显式的版本迁移工具与回滚文档。
4. 将自定义 Provider 执行迁移到独立 Worker/容器隔离。

## 6. 需要人工验证的事项

- 在真实 ComfyUI 实例上验证多个并发任务、排队删除和运行中任务状态。
- 在真实 ComfyUI 版本上验证 `/queue`、`/history`、`/view`、鉴权 Header 和自定义工作流兼容性。
- 验证 ComfyUI WebSocket 能力，但当前代码尚未实现 WebSocket Manager。
- 使用真实 RunningHub 凭据验证提交、查询、下载和取消，不执行未确认的付费调用。
- 使用真实 MySQL 8.0 数据源验证多租户表结构、迁移和并发写入。
- 在桌面端实际完成 Provider 新增、编辑、测试、诊断和删除 UI 流程。
- 在浏览器中检查诊断面板的布局、键盘操作、读屏文本和 localStorage 历史。
- 使用复杂旧项目包验证资产、分镜、成片、缺失素材和重复导入。
- 在真实服务器进程被强杀后，由正式进程管理器重启并验证任务恢复。
- 在多实例部署环境中验证任务租约、重复提交、取消和事件隔离。
- 对 DNS 重绑定、HTTP 重定向和自定义 Provider 的网络访问做专项安全测试。

## 7. 兼容性结论

- Provider Diagnostics 为新增接口，不改变原有生成接口参数。
- 媒体任务 `submissionState` 为可选字段，旧任务记录可读取。
- ComfyUI `cancelRunning` 保留旧字段，但语义收窄为精确删除排队任务。
- RunningHub 取消逻辑保持原提交数据格式。
- Provider 管理接口新增本机权限限制；这是有意的安全行为变化，远程用户应使用管理员管理入口或桌面端。
- Workbench 和 Take 的能力尚未落地，因此不能宣称旧项目已迁移到领域模型。
- 本轮未执行真实付费 Provider、真实 ComfyUI、真实 RunningHub、MySQL、桌面真机或浏览器交互验收。