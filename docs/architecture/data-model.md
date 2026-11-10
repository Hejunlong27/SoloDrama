# 数据模型（文件契约）

> 唯一数据源是**文件**。没有业务数据库；`sqlite3` 只用于作业队列/审计/事件流（可重建）。
> 所有字段名取自实际代码（`web/core/studio.py`、`stages/_ledger_core.py`、`nodes.py`）。

## 1. 实体与标识

| 实体 | 实际标识 | 依据 | 备注 |
|---|---|---|---|
| 项目 Project | **工作区绝对路径**（无 `project_id` 字段） | `web/app.py` 全站以 `ws` 查询参数传递 | 刻意不加 ID：加 ID 就要迁移全部用户工作区 |
| 集 Episode | `ep01` / `ep1`（正则 `^ep(\d+)$`） | `studio._ep_from_name` / `_release_index` | 发布版名 `EpisodeNN.mp4` 由 `RELEASE_EPISODE_DIGITS` 决定 |
| 镜头 Shot | `shot_001`（三位数字） | `pack_spec.py` 规则 `SHOT002` | 格式不合规会被导入拦截 |
| 资产 Asset | 资产 key + 变体名 | `pack_spec.py` `SHOT010/011` | 落 `04-资产/{characters,scenes,props}` |
| 任务 Task | 平台 `task_id`（云端）/ 本地批次 `batch_id` | `ledger/runs/<batch_id>__<shot_id>.json` | 金额聚合按 `taskId` **去重** |
| 节点 Node | `import.pack` 等 13 个 id | `nodes.py` | 状态只认产物里的 `verdict` |

`character_id` / `scene_id` / `prop_id` / `storyboard_id` 在代码中**不是独立 ID**，而是资产 key 与镜头 id 的组合。2.0 不新增一套 ID 体系（会破坏既有制作包）。

## 2. 工作区布局

```json
// layout.json
{ "stages": { "script": "03-剧本", "assets": "04-资产", "storyboard": "05-分镜",
              "prompts": "06-提示词", "film": "07-成片", "compliance": "08-合规",
              "release": "09-发行" } }
```

`stages` 可被用户覆盖（`_layout.load()` 归一后回填缺省）。**任何代码不得硬编目录名**，必须 `stage_dir(ws, key)` / `studio.assets_dir(ws)`。

## 3. 集记录（`studio.episodes()` 真实返回）

| 字段 | 类型 | 含义 |
|---|---|---|
| `ep` | str | 集号（`ep01`） |
| `total` `ok` `fail` `pending` | int | 镜头计数 |
| `state` | str | `done` / `fail` / `doing` / `todo` |
| `master` `upscaled` `mix` `subbed` `ass` | bool/str | 后期产物是否存在 |
| `draft` | — | 剪映工程（`draft_manifest.json`） |
| `release` | str | 发布版文件名（`EpisodeNN.mp4`），无则空 |
| `note` | str? | 仅「无批次记录、按 `subs/` 目录列出」的集才有 |

## 4. 节点状态（`nodes.py`）

```json
{ "id": "video.batch", "state": "blocked", "detail": "上游未通过：video.resolve", "mtime": 0 }
```

`state ∈ passed | failed | blocked | absent | skipped | stale`。
**UI 六态必须与之同名**，不得自造 `warning` / `error` 之类。

## 5. 提示词记录（`data_dir(ws)/<ep>/h3_prompts.json` 单条）

> **路径修正（2026-11-10）**：`data_dir(ws)` 由 `layout.json` 的 `data_rel` 决定，这些项目里解析到
> `06-提示词`；真实文件是 **`06-提示词/<ep>/h3_prompts.json`**。
> 旧实现 `studio.prompt_of()` 少拼了 `<ep>` 这一层，于是永远返回 `no_prompts` —— 提示词面板一直空着，
> 且没有任何报错。实测：本机 30 个集的 `h3_prompts.json` 都在各自的集目录下。

```json
{ "duration": 4.0, "ratio": "9:16", "voice": "…", "prompt": "subject_definitions: …\nsummary: …" }
```

**问题**：`prompt` 是单串，六段结构在传输层丢失。六段真源是 `h3_prompt.SECTIONS`（顺序即契约）。2.0 需新增 `sections` 字段，**不改 `prompt`**（保兼容）。

## 6. 台账（`ledger/runs/<batch_id>__<shot_id>.json`）

```json
{ "shot_id": "shot_007", "episode": "ep01", "stage": "video", "created_at": "…",
  "attempts": [ { "status": "SUCCESS", "billed": true,
                  "usage": { "consumeCoins": 12, "consumeMoney": 0.06 },
                  "elapsed": 96.4, "task_id": "…", "started_at": "…",
                  "error_class": "", "error": "" } ] }
```

口径变更记录（代码注释原文）：字段从「花了多少币」改为「占了多少 GPU 时间」；`coins/money` 保留兼容，新代码看 `sec`。

## 7. 成本聚合（`studio.cost()`）

| 字段 | 含义 |
|---|---|
| `unit` | 恒 `"sec"` |
| `source` | `ledger` / `none` |
| `ledger.{coins,usd,cny}` | **只取 `inventory.spend`**（按 taskId 去重，汇率只在那里算一次） |
| `ledger.{attempts,success,failed,sec,human}` | 尝试维度 |
| `avg_shot.{sec,human,sample}` | 单镜均值 |
| `by_stage[]` / `by_episode[]` | 分布（合计**不必**等于总数，有意如此） |
| `rows[]` | 最近 200 条尝试（含失败） |
| `estimate.{confidence,basis,summary}` | `measured` 或 `estimated`，必带依据文案 |
| `assets.{images,loose}` | 「还要跑多少」的分母 |

**纪律**：金额总数只认 `inventory.spend`。此前按 attempt 求和再自乘汇率，导致「耗时页」与「工作台」显示两个数（复盘 R3/B5）。2.0 不得再写第二套聚合。

## 8. 元信息（`_ep_meta`）

| 来源 | 字段 | 优先级 |
|---|---|---|
| `03-剧本/blueprint.json` | `total_ep` `ep_seconds` | 高 |
| `drama.json`（工作区根） | `episodes.count` `episodes.seconds` | 兜底 |

历史坑：总览页曾从 `setup.items` 取 `detail.seconds`，而 `detail` 已改成人话（「集数：4」），显示成 `?`。**展示文案不能当数据源。**

## 9. 不可重建类（禁止任何清理逻辑触碰）

| 文件 | 为什么 |
|---|---|
| `layout.json` | 用户可自定义目录名，重建会丢 |
| `ledger/runs/*` | 唯一的钱与时间证据 |
| `_cover_lead.json` | 母版实测偏移，重算需重跑 ffprobe（且可能与已发布版不一致） |
| `model-plan.json` | 人工决策 |
| `copyright.json` | 法律信息，禁止编造 |
| 用户素材（图/视频/剧本） | 不可再生成 |

## 10. 契约演进纪律

1. 只加字段，不改语义；改语义必须同步改夹具（`改口径必须改夹具`）。
2. 新契约文件必须登记进本文，并在 `docs/pack/PACK-SPEC.md` 或对应规范落一条。
3. 禁止引入 SQLite 作为唯一数据源；索引必须可从文件完整重建，损坏时自动降级扫盘。
