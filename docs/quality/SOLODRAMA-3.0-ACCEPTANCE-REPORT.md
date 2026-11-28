# SoloDrama 3.0 独立验收报告

- 验收日期：2026-11-27
- 验收范围：Milestone 0～7 的已完成实现
- 验收原则：未运行的测试不标记为通过；Mock、合成媒体和真实 Provider 结果严格区分。
- 仓库：`D:\编程\SoloDrama`

## 1. 验收结论

结论：**第一阶段达到可运行、可保存、可恢复、可导出的本地生产闭环，但尚未完成真实云端全流程制作验收。**

已实际验证：

- 领域文档懒创建和首次修订可正常保存。
- AI 结构化结果可应用，稳定 ID 可复用。
- 已确认 Shot 不会被后续 AI 结果覆盖。
- Take、参考图、时间轴和成片 Asset 可持久化。
- 已有媒体任务 Runtime 可持久化 taskId，服务重启后仍能同步失败/恢复状态。
- 使用真实 FFmpeg 将两段合成镜头和一条音频合成为 7 秒 H.264/AAC MP4。
- 使用真实 OpenCode Go + DeepSeek V4.1 Flash 完成短文本剧本理解，并生成经 Schema 校验的 3 集、9 场、36 镜头结构。
- 成片文件已阻止覆盖。
- 全仓 TypeScript 检查和全仓生产构建通过。

尚未验证：

- 真实语言模型对实际长篇剧本的输出质量；目前只验证了一段短故事创意。
- 真实 ComfyUI / RunningHub / Cloud Hub 实例和 Workflow。
- 真实 TTS 音色与字幕准确率。
- 1～3 分钟完整短剧的真实素材成功率、成本和质量。
- 桌面安装包/Hutch 工具链最终产物。

## 2. 实际运行命令与结果

### 2.1 路由生成

```powershell
cd apps/server
bun run routes
```

结果：通过。`src/router.ts` 已注册 `/api/production/*` 路由。

### 2.2 全仓类型检查

```powershell
cd D:\编程\SoloDrama
bun run typecheck
```

初次结果：失败。桌面端缺少 `electrobun/main` 类型声明，导致：

- `TS7016`
- `TS7006`

修复：新增 `apps/desktop/src/electrobun.d.ts`。

最终结果：通过。所有工作区包均以退出码 `0` 完成类型检查。

### 2.3 生产构建

```powershell
cd D:\编程\SoloDrama
bun run build
```

最终结果：通过。包括：

- 工具构建
- 扩展构建
- Web 构建
- Server 构建
- MCP 构建
- FFmpeg Worker 构建

已知非阻断警告：

- Vite 原生配置加载器提示 `electrobun.config.ts` 导入缺少扩展名。
- Web 存在大于 500 kB 的 chunk。
- 不影响本次生产构建成功。

### 2.4 Lint

```powershell
cd D:\编程\SoloDrama
bun run lint
```

结果：失败。

```text
error: Script not found "lint"
```

说明：仓库当前没有 Lint 脚本或统一 Lint 配置，因此不能将 Lint 标记为通过。

### 2.5 TODO/Mock 扫描

```powershell
rg -n TODO apps/server/src/utils/production apps/server/src/routes/production apps/web/src/pages/workspace/panels/production packages/production
rg -n FIXME apps/server/src/utils/production apps/server/src/routes/production apps/web/src/pages/workspace/panels/production packages/production
rg -ni mock apps/server/src/utils/production apps/server/src/routes/production apps/web/src/pages/workspace/panels/production packages/production
```

结果：三条命令均无匹配，3.0 新增生产模块中未发现 TODO、FIXME 或 Mock 占位实现。

## 3. 实际 API 验证

验证环境：

```text
SOLODRAMA_DATA_DIR=%TEMP%\solodrama3e2e\data
SOLODRAMA_SERVER_PORT=3317
测试项目=%TEMP%\solodrama3e2e\data\workspaces\e2e
```

### 3.1 剧本结构应用

通过 `POST /api/production/ai/apply` 输入一份**人工构造的 Mock 结构化剧本结果**，不是真实模型输出。

验证结果：

- 创建 1 集、1 场、2 个镜头。
- 创建角色、场景、道具稳定 UUID。
- Shot 的角色引用映射到 Character UUID。
- Scene 的地点引用映射到 Location UUID。
- 重复应用时 Shot ID 保持不变。
- 已确认 Shot 的 description 未被改写。
- 修订号按 CAS 递增。

### 3.2 参考图关联

通过 `POST /api/production/asset/reference`：

- 图片 Asset 成功关联到角色。
- 参考图 `confirmed=true`。
- 参考图文件必须是工作区内普通文件；路径不存在、符号链接、非图片类型会被拒绝。

### 3.3 Take 选择

通过 `POST /api/production/take/select`：

- 两个 Shot 分别选择一个正式 Take。
- 时间轴最终只有 2 条视频轨，数量与 Shot 一致。
- 重复重建不会产生重复视频时间轴项。

### 3.4 任务持久化与重启恢复

使用不存在的 Provider 启动一个真实任务记录：

```text
taskId=444e3ed2-aeea-4cab-ba57-ee432378115e
```

重启服务后：

- Production 文档中 Take 仍为 `generating`。
- 媒体任务 JSON 仍存在。
- 调用 `POST /api/production/generation/status` 后，Take 被同步为 `failed`。
- 错误为“请先在媒体模型设置中添加供应商”。

结论：任务记录和 Take taskId 能跨服务重启保留，不会误判为取消。

### 3.5 并发与冲突保护

- 使用旧 `expectedRevision` 保存，返回 HTTP `409` / `code=409`。
- 已有输出文件再次导出，返回 HTTP `409`，未覆盖原文件。

### 3.6 快照总量保护

再次保存验收项目：

```text
before revision=14
after revision=15
revisions=14
production.json bytes=110444
```

结果：修订号正常递增，历史快照保留 14 条，文件仍远低于 20 MB 读取上限。

### 3.7 路径安全

- 使用服务器工作区以外的目录请求 Production API，返回 `403`。
- 3.0 未新增上传路由；参考素材只接受已存在、已授权并位于当前工作区的普通文件。
### 3.8 OpenCode Go 真实语言模型验证

Provider：

```text
Provider ID=opencodeGo
API=https://opencode.ai/inference/go/openai/v1
Model=deepseek-v4.1-flash
Protocol=openai-completions
```

验证结果：

- Go 模型目录返回 11 个模型。
- 找到 `deepseek-v4.1-flash`，上下文 1,000,000，最大输出 384,000。
- OpenCode Go 用量接口返回 `rolling/weekly/monthly = ok`。
- `/api/providers/models` 模型发现通过。
- `/api/ai/models` 正确显示 OpenCode Go 和 DeepSeek V4.1 Flash。
- `/api/ai/generate` 通过 SSE 返回 `连接成功`。
- 通用生成耗时约 2.7 秒，usage 为 input 55 / output 49 / reasoning 45 / total 104。

真实 Production 剧本理解：

- 输入一段“雨夜怀表”的短故事创意。
- `/api/production/ai/understand` 返回 HTTP 200。
- 耗时约 261.7 秒。
- 输出简介 213 字、世界观 180 字。
- 人物：林夏、周野、老钟。
- 地点 4 个、道具 8 个。
- 生成 3 集、9 场、36 个 Shot。
- 输出 7 条连续性提示。
- 原始模型响应长度 39,596 字符，并通过 Production Schema。

这次是实际 OpenCode Go 模型调用，不是 Mock。

### 3.9 DeepSeek 官方 API 真实语言模型验证

Provider：

```text
Provider ID=deepseekOfficial
API=https://api.deepseek.com/v1
Model=deepseek-flash
Protocol=openai-completions
```

验证结果：

- 官方模型目录返回 `deepseek-flash`、`deepseek-v4-pro`。
- `/api/providers/models` 返回 2 个模型。
- `/api/ai/models` 正确显示 DeepSeek 官方 Provider。
- `/api/ai/generate` 通过 SSE 返回“连接成功”。
- 通用生成 usage：input 49 / output 50 / reasoning 47 / total 99。
- `/api/production/ai/understand` 耗时约 104.2 秒。
- 生成 3 集、6 场、24 个 Shot。
- 输出 2 个角色、1 个地点、5 个道具、6 条连续性提示。
- 原始模型响应 24,895 字符，并通过 Production Schema。

DeepSeek 返回的角色年龄是数字，本次同时补充了年龄数字到字符串的归一化。

## 4. 真实 FFmpeg 成片验证

### 4.1 输入素材

使用 FFmpeg 生成两段**合成测试视频**和一条**合成音频**，不是 AI 生成素材：

- `assets/clip1.mp4`：360×640，2 秒，H.264。
- `assets/clip2.mp4`：360×640，2 秒，H.264。
- `assets/tone.wav`：5 秒，440 Hz。
- 两个 Shot 时长分别为 3 秒和 4 秒。

### 4.2 导出

```text
POST /api/production/timeline/export
outputPath=outputs/pipeline-probe-2.mp4
width=360
height=640
fps=24
```

导出结果：

- 文件大小：63,260 bytes。
- 视频轨：H.264。
- 音频轨：AAC。
- 分辨率：360×640。
- 帧率：24 fps。
- 时长：7.000000 秒。

### 4.3 FFprobe 实际输出

```json
{
  "streams": [
    {
      "index": 0,
      "codec_name": "h264",
      "codec_type": "video",
      "width": 360,
      "height": 640,
      "r_frame_rate": "24/1"
    },
    {
      "index": 1,
      "codec_name": "aac",
      "codec_type": "audio",
      "r_frame_rate": "0/0"
    }
  ],
  "format": {
    "duration": "7.000000",
    "size": "63260"
  }
}
```

结论：时间轴不是静态页面，已实际完成视频补齐、拼接、混音和编码。

## 5. 页面验收

使用 Playwright CLI 在真实浏览器打开生产构建：

- 剧本理解页：`output/playwright/productionScript.png`
- 分镜与 Take 页：`output/playwright/productionStoryboard.png`
- 声音与成片页：`output/playwright/productionTimelineFinal.png`

页面实际显示：

- 项目名和简介。
- 编剧、世界观、连续性区域。
- AI 输入类型、模型、分段选项和文本。
- 角色、场景、道具页签。
- 集→场→镜树。
- Shot 结构化字段。
- Take 列表与任务操作。
- 时间轴视频/音频/字幕轨。
- 9:16、16:9、1:1 输出设置。

浏览器控制台有 2 条错误：

```text
/api/ai/media/balance -> 500
```

原因：临时验收环境没有配置 RunningHub 余额 Provider。该错误来自既有余额面板，不是 Production API，未影响制作页和导出链路。


## 5.1 统一工作台融合验收

底部入口已收敛为：

```text
画布 | 工作台 | 文档
```

原“制作”不再拥有独立入口，Production 页面成为“工作台”主界面。

工作台阶段：

```text
总览 | 剧本理解 | 角色与场景 | 分镜与 Take | 声音与成片 | 画布来源
```

实际验证：

- 总览正确显示 2 集、1 场、1 镜、3 个素材、4 个画布来源。
- 总览正确显示 4 个画布来源全部已关联、0 个待归档。
- 画布来源扫描识别 1 个画布、4 个节点来源。
- 文本节点成功导入为分集剧本。
- 图片节点成功导入为角色并关联参考图。
- 视频节点成功导入为未归档镜头和 Take。
- 音频节点成功导入为 Production 音频素材。
- `canvasBindings` 共写入 4 条映射。
- 同一画布来源重复导入返回 `409`。
- 页面截图：
  - `output/playwright/unifiedWorkbenchOverview.png`
  - `output/playwright/unifiedWorkbenchCanvasSources.png`

构建验证：

```powershell
bun run --cwd apps/web typecheck
bun run --cwd apps/server typecheck
bun run --cwd apps/web build
bun run --cwd apps/server build
```

均通过。

## 6. 已修复问题

### P1：首次读取后 revision 不一致

文件：

- `apps/server/src/utils/production/store.ts`

问题：

- `loadProduction()` 首次创建文件时调用了 `saveProduction()`，但返回未递增的临时文档。
- 页面拿到 revision 0，磁盘已是 revision 1，首次保存会发生冲突。

修复：

- 首次创建时直接返回 `saveProduction(...)` 的结果。

### P1：新增 API 路径重复

文件：

- `apps/server/src/routes/production/generation/status.ts`
- `apps/server/src/routes/production/generation/cancel.ts`
- `apps/server/src/routes/production/take/select.ts`
- `apps/server/src/routes/production/asset/reference.ts`
- `apps/server/src/routes/production/entity/confirm.ts`

问题：

- 路由文件路径已包含业务名，文件内又注册 `/status`、`/select` 等，产生 404。

修复：

- 路由文件内统一注册 `"/"`，与仓库路由生成规则一致。

### P1：重复选择 Take 产生重复视频轨

文件：

- `apps/server/src/utils/production/pipeline.ts`

问题：

- 每次选择 Take 只删除当前 Shot 的旧视频轨，再重新追加全部已选 Shot，导致其他 Shot 的视频轨重复。

修复：

- 重建前删除全部 `video` 时间轴项，再按镜头顺序生成唯一视频轨。

### P1：短素材导致成片时长缩短

文件：

- `apps/server/src/utils/production/export.ts`

问题：

- 镜头配置 3/4 秒，但实际素材只有 2 秒。
- `trim` 不能补足短素材，`-shortest` 导致最终成片只有 4 秒。

修复：

- 在 `trim` 前使用 `tpad=stop_mode=clone:stop_duration=<shotDuration>`。
- 重新验证后成片为 7 秒。

### P1：成片可能覆盖已有文件

文件：

- `apps/server/src/utils/production/export.ts`

问题：

- 导出前没有检查目标文件是否存在。

修复：

- 导出前检查目标；存在即返回 `409`。

### P1：任务重启后的状态同步不完整

文件：

- `apps/server/src/utils/production/pipeline.ts`

问题：

- 任务记录不存在或不可恢复时，Take/Job 可能长期停留在 `generating`。

修复：

- `interrupted` 且不可恢复时标记失败并写入错误；可恢复任务继续由现有 Task Runtime 恢复。

### P1：OpenCode 模型的零上限导致整批模型发现失败

文件：

- `apps/server/src/utils/ai/models.ts`

问题：

- OpenCode 目录中部分模型返回 `limit.context=0` 或 `limit.output=0`。
- 项目 Schema 要求上限必须大于 0，导致整批模型列表返回 400。

修复：

- 把 `0` 视为未知上限并允许解析。
- 返回项目模型目录时过滤非正数限制。

### P1：剧本理解路由把控制字段传给严格输入 Schema

文件：

- `apps/server/src/routes/production/ai/understand.ts`

问题：

- `directory`、`providerId`、`modelId` 被原样传给 `understandScript()`。
- `understandScript()` 使用严格对象 Schema，真实调用返回未知字段 400。

修复：

- 路由先拆出控制字段，只把 `title/sourceText/sourceKind/sections/context` 传入模型理解函数。

### P1：角色年龄数字与 Schema 字符串不一致

文件：

- `apps/server/src/utils/production/ai.ts`

问题：

- DeepSeek 官方模型返回 `age: 27`，Production Schema 要求字符串。

修复：

- 在剧本理解归一化阶段把有限数字年龄转换为字符串。
- 重跑后成功生成 3 集、6 场、24 镜头。

### P1：真实模型输出“3秒”导致时长时间校验失败

文件：

- `apps/server/src/utils/production/ai.ts`

问题：

- DeepSeek 返回 `shot.duration: "3秒"`，而 Production Schema 要求 number。
- 首次真实 Production 调用在 Schema 校验阶段失败。

修复：

- 在 Schema 校验前统一归一化集、场、镜编号和镜头时长。
- 提示词明确要求 `duration` 为数字秒数、编号为整数。
- 重跑同一请求后成功生成 3 集、9 场、36 镜头。

### P1：历史快照可能把领域文件推到读取上限

文件：

- `apps/server/src/utils/production/store.ts`

问题：

- 只按 20 条限制快照，没有限制快照总字节数。
- 多条接近 12 MB 的快照可能让 `production.json` 超过 20 MB 的读取上限，导致项目下次无法加载。

修复：

- 单条快照限制 12 MB。
- 文档快照总量限制约 18 MB，超出时从最旧快照开始裁剪。
- 最终写入前再次检查 20 MB 硬上限，超限返回 `413`。

### P1：参考图关联未校验实际文件

文件：

- `apps/server/src/utils/production/pipeline.ts`

问题：

- 只校验 Asset 存在，没有校验磁盘路径。

修复：

- 使用工作区路径解析和 `lstat`，拒绝不存在、非普通文件或符号链接。

### P1：桌面端类型检查阻断

文件：

- `apps/desktop/src/electrobun.d.ts`

问题：

- `electrobun/main` 无类型声明，导致全仓 typecheck 失败。

修复：

- 增加外部模块声明，使全仓类型检查通过。

### P2：音乐/音效输入框被压缩

文件：

- `apps/web/src/pages/workspace/panels/production/productionPanel.vue`

问题：

- 右侧窄栏中的音乐/音效表单横向排列，输入框只剩一个字符宽。

修复：

- 改为单列布局。

## 7. 未解决问题与风险

### P2：Lint 缺失

- 仓库没有 Lint 脚本。
- 本次不能报告 Lint 通过。
- 建议后续增加统一 ESLint/oxlint 配置，但不在本阶段擅自引入。

### P2：Web chunk 过大

- 构建提示存在大于 500 kB 的 chunk。
- 3.0 制作页按需加载，但工作台相关 chunk 仍较大。
- 后续可拆分制作页、模型列表和文档预览。

### P2：转场范围有限

- 当前支持 `cut` 与 `fade`。
- 已移除未实现真实交叉叠化的 `dissolve` 选项，避免界面承诺超出实际能力。

### P2：Asset 版本关系仍需 UI 深化

- 数据结构已支持 `version`、`previousAssetId`。
- 当前页面主要按生成任务和参考图集合展示，尚未提供完整版本树比较视图。

### P3：真实任务成本统计未完成

- Production 文档记录 Take 参数和耗时，但尚未汇总每集/每镜头成本。
- 现有 Provider billing 数据可作为后续来源，不能由前端估算伪造。

## 8. 需要人工验证的事项

以下项目**没有真实执行**，不能标记为通过：

1. 配置真实语言模型，对 10,000～100,000 字文本执行剧本理解。
2. 使用已授权 ComfyUI / RunningHub / Cloud Hub Workflow 生成角色、场景、分镜和视频。
3. 验证多角色 TTS 音色、语速和字幕时间。
4. 验证云端任务在执行中断网、退出页面、重启电脑后的恢复。
5. 运行 1～3 分钟完整短剧，统计镜头数、成功率、失败率、平均耗时、人工修改次数、素材可用率、成本和画质。
6. 在 Windows 安装包中验证 Launcher、更新、数据目录分离和卸载保留项目。

## 9. 当前测试数据性质

| 项目 | 性质 |
| --- | --- |
| 结构化剧本结果 | 人工构造 Mock，通过真实 Production API 应用 |
| 视频素材 | FFmpeg 合成色块 |
| 音频素材 | FFmpeg 合成正弦波 |
| 成片导出 | 真实 FFmpeg 执行 |
| 任务 Runtime | 真实任务记录，Provider 故意缺失以验证失败同步 |
| 语言模型调用 | 真实 OpenCode Go / DeepSeek V4.1 Flash，以及 DeepSeek 官方 / DeepSeek Flash，短文本剧本理解均通过 |
| Cloud Hub 调用 | 未执行真实调用 |
| TTS 调用 | 未执行真实调用 |

## 10. 最终判断

3.0 的领域模型、持久化、确认保护、Take 管线和 FFmpeg 导出已达到第一阶段可用标准。

由于没有已授权的真实云端 Workflow 和 TTS 账号，本报告不能声称“完整 AI 短剧生产已通过”。正式发布前必须完成第 8 节的人工验证。

## 11. 制作工作台体验升级验收

本轮新增并实际验证：

- 工作台顶部“返回项目”和“返回总览”按钮。
- AI 对话改为常驻可拖动宠物入口；点击可打开/收起对话。
- 角色与场景增加卡片总览和独立设计器。
- 角色形象合并为统一描述框，音色 Provider、Voice ID、语速和语言单独成区。
- 场景和道具采用同样的“总览 → 设计”路径。
- 全局画风弹窗接入 306 条现有画风库，并保存到 `.solodrama/project.json`。
- 分镜页改为参考角色、场景、道具 + 提示词 + 辅助图三栏工作区。
- 支持故事板、分镜图、站位图独立开关、生成和“作为视频参考”开关。
- 支持通用视频提示词和 H3 视频提示词优化。
- 支持尾帧续画：自动提取上一正式 Take 的尾帧，写入 Asset 并作为当前 Take 首帧参考。

实际验证数据：

- 尾帧提取成功：PNG 1,747 bytes。
- 尾帧 Asset 成功写入。
- 尾帧成功进入当前 Take `referenceAssetIds` 和 `firstFrame`。
- `continuationSourceShotId`、`continuationTakeId` 正确记录。
- 通用提示词优化成功：237 字。
- H3 提示词优化成功：1,602 字，包含 H3 所需章节。
- Web 与 Server typecheck 通过。
- 全仓生产构建通过。

页面截图：

- `output/playwright/workbenchPetOverview3.png`
- `output/playwright/assetOverviewNew.png`
- `output/playwright/characterDesignerNew.png`
- `output/playwright/globalStyleNew.png`
- `output/playwright/shotStudioNew.png`
- `output/playwright/petChatOpenNew.png`
