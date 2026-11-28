# Milestone 1 稳定性修复报告

日期：2026-11-26

## 完成内容

- Provider VM 补齐 `FormData`、`crypto`、`Headers`、`Request`、`Response`、`File`、`structuredClone`、`performance` 等运行时全局对象。
- 新增统一 Provider 错误码与安全归一化：鉴权、DNS、TLS、网络、限流、额度、超时、无效响应、能力不支持、上游失败等。
- API 错误响应在保留现有 `{ code, data, message }` 结构的前提下增加 `providerCode`、`upstreamCode`、`retryable` 安全诊断信息。
- ComfyUI 本地与云端 Provider 的上传文件改为 UUID 唯一文件名，并设置 `overwrite=false`。
- 移除 ComfyUI 无 `prompt_id` 的全局 `/interrupt`。取消时先查询 `/queue`，只删除仍处于 `queue_pending` 的精确 `promptId`；运行中任务只停止本地等待。
- RunningHub 与闭源模型的取消请求允许显式退出已中止的任务信号，避免取消逻辑因原 AbortSignal 已中止而永远发不出去。
- 媒体任务新增 `submissionState`：`submitting | submitted | accepted | unknown`。
- 在调用供应商前持久化 `submitted`；收到 Provider 恢复数据后持久化 `accepted`；已提交但未获得可恢复凭据时持久化 `unknown`。
- 旧任务记录仍可读取；新字段为可选，未升级记录版本。

## 修改文件

- `apps/server/src/lib/responseFormat.ts`
- `apps/server/src/utils/media/provider.ts`
- `apps/server/src/utils/media/generation.ts`
- `apps/server/src/utils/media/tasks.ts`
- `packages/providers/errors.ts`
- `packages/providers/types.d.ts`
- `packages/providers/index.ts`
- `packages/providers/package.json`
- `packages/providers/src/media/solodramaComfy.ts`
- `packages/providers/src/media/solodramaComfyCloud.ts`
- `packages/providers/src/media/solodramaRunningHub.ts`
- `packages/providers/src/media/solodramaRunningHubClosed.ts`
- `packages/nodeScaffold/src/nodeAi.ts`
- `packages/nodeShared/src/useNodeGeneration.ts`
- `docs/SOLODRAMA-PROVIDERS.md`

## 验证

已通过：

- `bun run --cwd apps/server typecheck`
- `bun run --cwd apps/web typecheck`
- `bun run --cwd packages/nodeScaffold typecheck`
- `bun run --cwd packages/nodeShared typecheck`
- `bunx tsc -p packages/providers/tsconfig.json --noEmit`
- `bun run build:server`
- `bun run --cwd apps/web build`
- 模拟 ComfyUI HTTP 服务：同名素材得到不同上传名，`overwrite=false`，排队任务 A 只发送 `delete:["taskA"]`，`/interrupt` 调用为 0。
- 模拟 ComfyUI 运行中任务：不发送删除请求，也不调用 `/interrupt`。
- 临时媒体任务探针：`accepted` 保存后可恢复；提交响应丢失时为 `unknown`；供应商调用前失败时为 `failed`。
- Provider 错误分类探针：401、DNS、429、402、超时和无效 JSON 分别映射到预期错误码。

根级 `bun run typecheck` 仍被仓库既有桌面类型问题阻断：`electrobun/main` 缺少声明并导致两个隐式 `any`。该问题与本阶段改动无关。

## 兼容与边界

- 未修改已有 API 必填参数或响应外层结构。
- 未删除旧 `cancelRunning` 配置字段；其语义收窄为“允许精确删除排队任务”，不再执行全局中断。
- ComfyUI 运行中任务没有可证明安全的实例级中断时，只停止本地等待；远端任务可能继续运行，界面继续使用“结果未知/待核实”路径。
- 仓库规范禁止新增测试模块或测试脚本，因此本阶段没有新增自动化测试文件；使用临时外部探针完成行为验证。