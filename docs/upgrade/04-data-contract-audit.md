# 04 · 数据契约审计

> 原则：**文件契约是唯一数据来源；数据库只能做可重建索引。**（2.0 指令 §9.3）
> 本文只列**实测存在**的契约物。未验证用途的标 `[待核实]`。

## 1. 契约链路（自上游到下游）

```
创作 Markdown（00-创作/ 03-剧本/）
   │  stages/import/md2pack.py
   ▼
制作包 JSON（pack/ ：episodes/*.json、assets/*.json）
   │  stages/import/pack_spec.py  ← 规则 SHOT001–SHOT021（含阻断级）
   │  stages/import/pack_import.py
   ▼
data/*.json（引擎内部契约：h3_prompts.json 等）
   │
   ▼ 13 节点
06-提示词/  05-分镜/  04-资产/  07-成片/  08-合规/  09-发行/
```

## 2. 工作区目录契约（真源 `stages/_layout.py::STAGE_DIRS`，第 60-67 行）

| 键 | 目录 | 内容 |
|---|---|---|
| `script` | `03-剧本` | 分集剧本 |
| `assets` | `04-资产` | `characters/` `scenes/` `props/` |
| `storyboard` | `05-分镜` | 分镜图 |
| `prompts` | `06-提示词` | 提示词产物 |
| `film` | `07-成片` | 母版与发布版源 |
| `compliance` | `08-合规` | 合规材料 |
| `release` | `09-发行` | 发行资料 |

实测真实工作区（`D:\剧本\海外剧\10`）顶层：

```
00-创作  03-剧本  04-资产  05-分镜  06-提示词  07-成片  08-合规  09-发行
layout.json  project.json  drama.json  brief.json  pack/  video-pipeline/
```

注意两点：

1. `00-创作` **不在 `STAGE_DIRS`** —— 它是创作层目录，不参与引擎阶段遍历。UI 不能把它当第 0 阶段塞进节点链。
2. `layout.json` 的 `stages` 可覆盖默认目录名（`_layout.py::load()` 第 152-187 行做归一与回填）。**UI 绝不能硬编 `04-资产`**，必须走 `studio.assets_dir(ws)`。

## 3. 关键契约文件清单

| 文件 | 位置 | 写方 | 读方 | 可否重建 |
|---|---|---|---|---|
| `layout.json` | 工作区根 | `init_project.py` | `_layout.load()`、`studio._layout()` | 不可（用户可自定义目录名） |
| `project.json` / `drama.json` / `brief.json` | 工作区根 | `init_project.py` 等 | `studio` 各聚合函数 | 部分 `[待核实]` |
| `project-setup.json` | 工作区根 | 项目初始化 | `nodes.py:375` | 否 |
| `pack/episodes/*.json` | `pack/` | `md2pack.py` | `pack_spec.py` `pack_import.py` | **是**（可从 Markdown 重生成） |
| `pack/assets/*.json` | `pack/` | `md2pack.py` | 同上 | 是 |
| `data/h3_prompts.json` | `data/` | `pack_import.py` 等 | `studio.prompt_of()`、出片脚本 | 是 |
| `06-提示词/h3_prompts.json` | 阶段目录 | 导入/归一 | 出片 | `[待核实]` 与上一行的关系 |
| `ledger/runs/<batch_id>__<shot_id>.json` | `ledger/`（`_ledger_core.py:19`） | 每次实跑 | `cost_ledger.py`、`studio.cost()` | **否（唯一钱证据）** |
| `cues.json` | 母版产物区 | `subtitle.py` | `edit_draft.py` | 是 |
| `bgm-plan.json` | 同上 | `bgm.py` | `edit_draft.py` | 是 |
| `_master/` | 同上 | `edit_draft.py` 母版段 | 放大/字幕/发布 | 是（耗 GPU） |
| `_cover_lead.json` | 字幕产物区 | 母版生成时 ffprobe 实测 | `cover_lead_seconds()` | **否（实测值）** |
| `draft_manifest.json` | 剪映工程目录 | `edit_draft.py` | `nodes.py` 的 `edit.draft` 判据 | 是 |
| `EpisodeNN.mp4` | `09-发行/剧集/` | `release_export.py --all --apply` | 发布 | 是（唯一发布版） |
| `model-plan.json` | 项目/配置 | 用户确认 | `model_gate.py` | 否（人工决策） |
| `config.subtitle.json` | 项目配置 | 用户 | 字幕/合规 | 否 |
| `copyright.json` | 版权资料区 | 用户填主体字段 | `copyright_kit.py`、`release_check.py` | **否（禁编造）** |

## 4. 读写矩阵（从 Web 侧实测）

| 端点 | 读/写 | 目标 |
|---|---|---|
| `GET /api/studio/overview` | 读 | 目录扫描 + `nodes` 状态 |
| `GET /api/studio/shots?ep=` | 读 | 分镜/提示词/视频三态 |
| `GET /api/studio/prompt?shot=` | **只读** | `h3_prompts.json` 单条 |
| `GET /api/studio/episodes` | 读 | 逐集四类产物 + 发布版 |
| `GET /api/studio/cost` | 读 | 台账聚合 |
| `GET /api/studio/release` | 读 | `release_check.py` 子进程 |
| `GET /api/studio/release/export-preview` | 读（干跑） | `release_export.py` 干跑 |
| `POST /api/canvas/shot` | **写** | 画布镜头编辑 |
| `POST /api/create/write` | **写** | 创作 Markdown |
| `POST /api/run` | **写**（危险） | 任意命令，受 `CMD.danger` + 只读闸 |

## 5. 三个契约级风险（2.0 必须处理）

### R1 · 提示词是「单串」，无结构契约

```python
# web/core/studio.py:739
{"ok": True, "prompt": v.get("prompt") or ""}
```

坑在于：`h3_prompt.SECTIONS` 定义六段顺序即契约（`h3_prompt.py:55-63` 注释原话：「改名/换序 = 换契约，下游全部要跟着改」），但 Web 层把它拍平成一个字符串返回。**结构信息在传输层丢掉了**。

处置：新增读取端点返回 `split_sections()` 结果，**不修改原 `prompt` 字段**（保兼容），另开 `sections` 字段。

### R2 · 没有写回 + 没有单镜校验

现状校验只有两处，都是批处理：

- `pack_spec.py`（整包，`SHOT001–021`）
- `h3_prompt.py --lint`（文件级）

单镜「改完立刻知道对不对」的能力**不存在**。处置：新增 `POST /api/studio/prompt`，内部**复用** `h3_prompt.normalize()` + `lint()` + `prompt_marks.find_bare()`，不新写规则。

### R3 · `data/h3_prompts.json` 与 `06-提示词/h3_prompts.json` 可能双份

`studio.prompt_of()` 读 `data_dir(ws)/h3_prompts.json`，而工作区同时存在 `06-提示词/` 阶段目录。两者是否同源 `[待核实: 在真实工作区对两个文件做 sha256 比对]`。

风险：若不同源，UI 编辑写回哪一份就是事故。**Phase 3 开工前必须先核实**，否则会出现「改了没生效 / 改错副本」。

## 6. 契约纪律（写进 2.0 实施规范）

1. 任何 UI 需要的路径，只能经 `studio.py` 的路径函数取，**禁止前端拼字符串**。
2. 任何新契约文件必须落进上表，并在 `docs/pack/PACK-SPEC.md` 或对应规范登记。
3. 任何写操作必须：**干跑 → 备份 → 展示影响 → 用户确认**（2.0 指令 §9.4）。
4. 不得引入 SQLite 作为唯一数据源；若做索引，必须能从文件完整重建，且索引损坏时自动降级为扫盘。
5. `ledger/`、`_cover_lead.json`、`model-plan.json`、`copyright.json` 是**不可重建**类，任何清理逻辑必须白名单排除。
