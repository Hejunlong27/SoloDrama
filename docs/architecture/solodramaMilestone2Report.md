# Milestone 2 Provider Diagnostics 报告

日期：2026-11-26

## 完成内容

- 在 `@solodrama/providers` 增加统一诊断类型：`ProviderDiagnosticResult`、`ProviderDiagnosticCheck`、`ProviderDiagnostics`。
- 新增服务端媒体 Provider 诊断：配置、连接、鉴权、模型、能力、余额和实际生成占位检查。
- 新增文本 Provider 基础诊断：连接、鉴权、模型、协议能力和实际生成占位检查。
- 实际生成检查保持 `skipped`，付费调用仍只能由用户在现有测试面板主动触发。
- 新增 `POST /api/providers/diagnostics/run`，响应继续使用 `{ code, data, message }`。
- 在现有媒体模型测试面板增加“连接诊断”、诊断状态、检查明细、最近成功时间、最近错误和平均诊断耗时。
- 诊断统计保存在浏览器 localStorage，仅含状态、时间和安全错误摘要，不保存密钥或请求正文。

## 修改文件

- `packages/providers/diagnostics.ts`
- `packages/providers/index.ts`
- `packages/providers/package.json`
- `apps/server/src/utils/media/diagnostics.ts`
- `apps/server/src/routes/providers/diagnostics/run.ts`
- `apps/server/src/router.ts`（路由生成器）
- `apps/server/src/utils.ts`
- `apps/server/src/utils/network/index.ts`
- `apps/web/src/components/settings/panels/mediaModel/providerTestPanel.vue`
- `docs/SOLODRAMA-PROVIDERS.md`

## 验证

已通过：

- `bun run --cwd apps/server typecheck`
- `bun run --cwd apps/web typecheck`
- `bun run --cwd packages/providerWeb typecheck`
- `bunx tsc -p packages/providers/tsconfig.json --noEmit`
- `bun run build:server`
- `bun run --cwd apps/web build`
- 媒体与文本 Provider 诊断函数模拟上游均为 `healthy`。
- 临时 Express 路由 + 模拟上游实际 HTTP 往返：`POST /api/providers/diagnostics/run` 返回 HTTP 200 和健康结果。

## 已知边界

- 文本 Provider 已有诊断 API 能力，但本阶段只在现有媒体模型测试面板加入可视化入口；文本设置页的独立诊断按钮尚未接入。
- 健康状态和平均耗时当前为前端本地历史摘要，不是跨设备/跨进程持久健康中心。
- 诊断不自动执行真实生成，避免未经用户确认产生费用。