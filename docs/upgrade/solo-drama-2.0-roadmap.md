# SoloDrama 2.0 路线图

> 铁律：**先审计，后整理；先设计系统，后开发页面；先核心体验，再扩展功能。**
> 状态时间点：2026-11-10。

## 0. 核心判断（决定整条路线）

不需要重写。审计已确认：

- 引擎 13 节点、双份门禁（CLI+Web）、六态状态机、退出码语义**已在生产验证**。
- 后端 111 端点能力**远超**当前 UI 暴露程度。UI 工作是「组织」，不是「补能力」。
- 唯一必须新增的后端能力只有两处：提示词结构化读、提示词写回 + 单镜校验 —— **这两处已于 2026-11-10 完成**（`stages/import/prompt_edit.py` + `GET/POST /api/studio/prompt`）。

所以本次升级的性质是：**视觉重设计 + 信息架构重排 + 两处后端补齐 + 工程整理**，不含引擎重写。

## 1. 阶段总表

| Phase | 主题 | 状态 | 交付物 |
|---|---|---|---|
| 0 | 完整审计 | **已完成** | `docs/architecture/*`（4 份）、`docs/upgrade/01–07`、`legacy-feature-inventory.md` |
| 1 | 工程整理（清理与规范） | **清单已出，未执行** | 见 §2 |
| 2 | 品牌视觉与设计系统 | **已完成（含硬编码色清零）** | `docs/design/*`（8 份）、`tokens.css` 双主题、`components-2.css`、`design.html`、`design-probe.html` |
| 3 | 核心 UI 重设计 | **进行中（导航 / 首页 / 驾驶舱 / 分镜三栏 / 创作三栏 已落地）** | 首页 / 项目管理 / 驾驶舱 / 创作 / 资产 / 分镜 |
| 4 | 生产与管理功能 | **提示词读写已完成**；视频生产 / 任务 / 通道 / 成本 / 后期发行未开始 | `prompt_edit.py` + `GET/POST /api/studio/prompt` + 分镜页编辑器 |
| 5 | 全面测试与优化 | 未开始 | 测试报告、性能、响应式、部署说明 |

> 说明：Phase 1 与 Phase 2 的次序被并行处理了 —— 因为设计系统必须先有 Token 才能验证「浅色不改结构」。整理清单见 §2，**不含任何删除动作**，需逐条确认后执行。

## 2. Phase 1 整理清单（待确认，未执行）

| # | 整理项 | 动作 | 风险 |
|---|---|---|---|
| C1 | 旧控制台 `/ui/`（`app.js` 432 / `home.js` 458 / `styles.css` 548 行） | **冻结**（保留 `advanced.html` 逃生口），不删 | 用户书签可能依赖 |
| C2 | `docs/` 下 30 个条目 | 加索引 `docs/README.md`，标注「现行 / 历史 / 复盘」 | 低 |
| C3 | 重复的设计口径文档 | `design/SoloDrama_Studio_产品定义_v1.md` 与 `docs/design/*` 合并，只留一处 | 低 |
| C4 | `web/ui/styles.css` 与 `studio/css/app.css` | 不合并（分属两个前端），仅标注边界 | 低 |
| C5 | 未使用依赖 | 先审计 `requirements*.txt` 实际 import，出清单 | 中（误删会跑不起来） |
| C6 | 命名规范 | 统一 `web/core/*` 的模块前缀说明，写进 `web/README.md` | 低 |
| C7 | 环境变量 | 汇总成一张表（`SOLODRAMA_*`），写进 README | 低 |

**不做**：不搬迁目录（`frontend/`+`backend/` 的目标结构对本项目不适用——它是 Python 引擎 + 单端口控制台，硬拆会让 `start.cmd` 与全部文档失效），不删任何用户数据。

## 3. Phase 2 范围与状态

### 已完成

1. `tokens.css` 三层结构（基色板 / 语义 / 旧变量别名），双主题，22 个视图零改动。
2. 语义命名 `--sd-*` + 旧名 alias（`--fs-11`…`--bg-app` 全保留）。
3. 主题解析三态（auto/dark/light）+ `<head>` 内联脚本防闪白 + 顶栏切换按钮。
4. `components-2.css`：`.btn.danger`、`.sd-poster`、`.sd-stages`、`.sd-prompt-sec`、`.sd-cost-row`、全局 `:focus-visible`。
5. `design.html` 视觉样板（真实组件，含双主题切换与色板实测）。
6. 六份设计规范（品牌 / Token / 排版 / 色彩 / 动效 / 组件）+ `design-system.md` 索引 + `ui-redesign-plan.md`。

7. T2 收尾：`app.css` 硬编码色 72 → 生效 1 处；新增状态色文字档（`-ink`）；新建 `design-probe.html` 对比度探针。

### 待完成

1. 补齐 `.sd-stages` / `.sd-prompt-sec` 在真实页面的接入（Phase 3/4）。
2. 移动端断点复核（现有 11 处断点，需在改版后重测）。
3. `app.css` 里少数仍用旧别名（`--txt-3` 等）的地方，随页面改版逐步换成语义 Token —— **不单独开一轮改造**，避免为改而改。

## 4. Phase 3–5 的内容与验收

### Phase 3 核心 UI

| 页面 | 数据源（已存在） | 关键约束 |
|---|---|---|
| Studio 首页 | `/api/workspaces` `/api/home` `/api/studio/overview` | 数字必须可追源；无虚构统计卡 |
| 项目管理 | `/api/workspaces` `/api/studio/episodes` | 海报卡 2:3；缺图用场记板占位 |
| 项目驾驶舱 | `/api/studio/{overview,workflow,episodes,cost}` | 13 节点阶段条 + 唯一推荐动作 |
| AI 创作中心 | `/api/create/*` `/api/skills/*` `/api/llm/*` | 创作数据仍是 Markdown |
| 资产中心 | `/api/artifacts` `/api/studio/asset-md` `/api/file` | 落点走 `assets_dir()`，禁前端拼路径 |
| 分镜工作室 | `/api/studio/{shots,prompt}` `/api/canvas/*` | 六段式编辑器；校验调真规则 |

### Phase 4 生产与管理

视频生产（`/api/comfy/*` `/api/generators/rh`）、任务中心（`/api/jobs*`）、模型（`/api/llm/*`）、通道（`/api/connections/*`）、成本（`/api/studio/cost`）、后期发行（`/api/studio/release*`）。
**铁律**：默认不选付费通道；不绕过预检；不绕过计费确认；界面与 CLI 同一套门禁。

### Phase 5 测试

基线（干净 HEAD 上本来就红 6 例）：`tools/tests/test_repo_paths.py` P01、`test_workflow_map.py` 1、`web/tests` connections 3 / new_actions 1 / pipeline 3 / skill_library 4 / llm_e2e。

## 5. 关键路径

```
T5 提示词定源 ──→ T3 结构化读 ──→ T4 写回+单镜校验 ──→ 分镜工作室（Phase 3）
T2 色值收敛 ──→ 浅色主题验收 ──→ 首页与驾驶舱（Phase 3）
T6 导航重排 ──→ 五工作空间 ──→ 其余页面（Phase 3/4）
```

约束：**T5 必须先于 T4**。写回落到错副本的表现是「改了没生效」，比崩溃难查一个量级。

## 6. 风险登记

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| 改 CSS 后某页视觉错乱 | 高 | 中 | 旧变量全别名；逐页截图比对 |
| 提示词写回写错副本 | 中 | **高** | T5 先定源 + 写前备份 + 干跑 |
| 导航重排导致路由 404 | 中 | 中 | 旧 hash 全部保留重定向 |
| 误改用户工作区 | 低 | **极高** | 只读优先、干跑、备份、二次确认 |
| 把已移除能力做成页面 | 中 | 中 | 对照 `legacy-feature-inventory.md` A6/A7/E10 |

## 7. 每阶段汇报模板（不允许用「已完成」代替证据）

1. 本阶段目标 2. 实际完成 3. 修改文件清单 4. 新增文件清单 5. 旧功能影响分析
6. 数据契约影响 7. 测试结果（命令 + 通过/失败数） 8. UI 实际效果（截图）
9. 未完成项 10. 下一阶段计划
