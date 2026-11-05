# Skill 接入与下游兼容性（实测报告）

> 日期：2026-11-05 17:00–17:20｜环境：RTX 4060 8G + 本地 ComfyUI 0.42.1 + DeepSeek（deepseek-chat）
> 被测 Skill：`zhaidou-manju`（宅斗）、`tianchong-manju`（甜宠）
> 产出物与中间文件：`D:/tmp/skillcompat/`（临时工作区，不进仓库）
> 全程费用：LLM 约 4 次长文调用（企划案/资产库/剧本/导演手册 ×2 套）；出图/出片 ￥0（本机 GPU）

---

## 1. 测法（为什么这么测）

要回答的不是「Skill 能不能装上」，而是「**装上的 Skill 产出的东西，引擎能不能一路吃到成片**」。
所以按真实链路跑一遍，每段只做**机械识别**（不额外创作），看哪一段会断：

```
装 Skill → 企划案 → 资产库 → 剧本 → 导演手册
                                   ↓（机械抽取，模拟「资产识别 / 分镜识别」）
                              pack/*.json
                                   ↓ pack_import
                     data/ep01/{shots,boards,h3_prompts}.json
                                   ↓ 出图（资产图）→ 回填参考图
                                   ↓ 出片
                              shot_001/final.mp4
```

识别脚本（临时，不进仓库）：`md2pack.py`（资产库 → assets）、`md2ep.py`（导演手册 → episodes）。

---

## 2. 结果矩阵

| 环节 | 兼容性 | 实测证据 |
|---|---|---|
| **Skill 装载** | ✅ 通 | 两份都是「内置」来源、单选替换；`skills.json` 记 sha/chars；组装出的指令 7–8k 字 |
| **Skill 生效（企划案）** | ✅ 通 | 宅斗：特征词 4/4（嫡/侯/内宅/主母），小节＝立项卡/企划案/1–8 项（与模板一致）；甜宠：3/3（总裁/契约/婚） |
| **资产库（人物批）** | ⚠ 部分 | 宅斗 25 条目里只有 **6 条**带可用提示词（其余是场景/道具的索引行）；甜宠 6 条 **6/6** 带提示词 |
| **资产识别（md → assets）** | ⚠ 需按模板分派 | 甜宠：`### P01 名称` + 服装卡表 + 围栏提示词 → 直接可抽；宅斗：`### P01｜名称` + 三视图/表情四态/服装卡三层 → 只能取「服装卡提示词」或「三视图」之一 |
| **导入校验（pack_import）** | ✅ 严格 | 缺 ep 阻断（EP002）、cast 引用不存在的资产阻断（SHOT010）、缺 video_prompt 阻断（SHOT015） |
| **出图（资产图）** | ✅ 真出 | P01 → `P01_崔昭_LOOK-A_00.png` 1682KB / 31s（提示词来自 Skill 资产库原文，未改写） |
| **分镜识别（md → episodes）** | ⚠ 大体可用 | 首批 8 镜解析到 7 个块，其中 **6 镜两段提示词齐全**（A 段 209–237 字符 / B 段 715–841 字符）；1 镜被截断 |
| **分镜表 → 引擎契约** | ✅ 通 | shots/boards/h3_prompts 三份 JSON 生成；时长 9s/镜、总 54s 均在 4–15 / 60–80 区间 |
| **出片** | ✅ 真出 | `shot_001/final.mp4` 9.42s / 226 帧 / 24fps / h264+aac / 2.4MB（307.9s 渲染） |

---

## 3. 四个缺口：三个已落地，一个仍是决策

> 2026-11-05 18:30 更新：3.1 / 3.2 / 3.3 / 3.4 已按下述方案实现，并做过实测（见 §6）。
> 下面保留原始分析，方便回看「为什么这么改」。



### 3.1 分批模板 vs 单文件写入（**影响最大**｜已修）

21 份内置模板几乎都按「第N批／共M批」输出（宅斗资产库 4 批、导演手册 3 批、剧本每次 3 集）。
而 `creation.write()` 对非 multi 环节是**整份覆盖**（留 .bak），`vars_for()` 也**不带上一批内容**。

后果：
- 点第二次「生成资产库」→ 第二批覆盖第一批，前面的人物卡只剩备份文件；
- 模型拿到的输入只有企划案，没有「已写好的部分」，所以它会**从第 1 批重写**，不是续写。

现在的可行姿势（都在人工侧）：把上一批内容贴进输入，或直接按批导出到 `00-创作/` 的不同文件。

### 3.2 单批 8 镜 > 模型输出上限（已改为 4–5 镜/批）

`create.director` 的 `max_tokens=8000`，而 8 镜 × (A 段 ~220 字 + B 段 ~780 字) ≈ 8k 汉字 ≈ **超过 8k tokens**。
实测第 7 镜的 A 段围栏**没有闭合**、B 段整段缺失 —— 原文在「角门在画」处被切断。

已修：`gateway` 现在把 `finish_reason` 透出，`/api/create/generate` 在 `truncated` 时返回明确警告
（此前截断与正常结束在调用方看来一模一样，直到 `pack_import` 报「缺 video_prompt」才发现）。

未修（需要决策）：把「每批镜数」降到 4–5，或换长输出模型，或分批落不同文件。

### 3.3 资产卡的三视图 / 表情卡在 pack schema 里没有位置（已加 `kind`）

模板产出的资产卡是「三视图 + 表情四态 + 服装卡（LOOK-A…D）」三层；引擎的 `variants[]` 只有
`code + label + prompt + aspect`。现在只能二选一：

- 取「服装卡提示词」→ 有造型区分（LOOK-A/B/C），但丢掉三视图与表情；
- 取「三视图」→ 一致性锚点最全，但只有一套造型。

建议：`variants` 增加 `kind`（`turnaround` / `look` / `expression` / `state`），文件名前缀带上它，
出图时按「三视图先出 → 派生造型」的顺序。**这是 schema 变更，不擅自做。**

### 3.4 台词归属要「名字 → 代号」映射（转换器已实现）

导演手册的台词写「崔昭：父亲，三日盘缠…」，引擎的 `dialogue[].asset` 只认 `P01`。
`pack_spec._norm_dialogue` 对不在本镜 cast 里的 asset 直接丢弃（警告 DLG002）。
所以转换器必须先从资产库建 name→id 表；否则台词全被丢掉（成片没口型依据）。

---

## 4. 本轮修掉的 3 处（都是「跑起来才发现」）

| # | 现象 | 原因 | 修法 |
|---|---|---|---|
| 1 | 导演手册看起来完整，导入才报「最后一镜缺 video_prompt」 | 截断状态被吞，产物与正常结束无差别 | `gateway` 透出 `finish_reason`/`truncated`；生成接口返回警告 |
| 2 | `--workflow workflow_h3_local.json` 能提交，预检却报「缺工作流文件」 | 执行器按本目录解析裸文件名，预检按 CWD | `gen_preflight._abs_wf()` 统一到 `<repo>/stages/video/comfyui` |
| 3 | 竖屏项目出成横屏（1056×608） | 批次只传全局 `--aspect`（默认 None），**镜头级 ratio 从未生效** | 批次按 `shots[].ratio` 查 ComfyUI **实际枚举**（`9:16 (Portrait Widescreen)`）并下传；实测竖屏 480×864（精确 9:16） |

> ⚠ 画幅枚举不能凭直觉写：`ResolutionSelector` 的选项是 `9:16 (Portrait Widescreen)`，
> 写 `9:16 (Portrait)` 会让节点直接 `execution_error`。所以映射必须**从 `object_info` 读**，
> 硬编码的那张表只作兜底。

另外：预检判据在「默认图像工作流」上会缺 `TESpeedQwenImage21` 节点（当前 ComfyUI 实例没装），
而 `workflow_qwen21_t2i_hq.json` 是齐的 —— 新项目确认通道时要**显式指定工作流**，别只写 `image=local_comfyui`。

---

## 5. 现在能怎么跑（不含未修项）

```bash
# 0) 新建项目工作区（含 layout.json / project.json(style_lock) / brief.json(idea)）
# 1) 装模板（单选），生成企划案 → 资产库 → 剧本 → 导演手册（每批一次，人工拼接）
# 2) 把 md 机械转成 pack（资产 + episodes），pack_import 校验
python stages/import/pack_import.py --pack <ws>/pack --workspace <ws> --apply
# 3) 确认出图通道与工作流（必须显式给可用的那份）
drama models set image=local_comfyui --comfy-workflow stages/assets/comfyui/workflow_qwen21_t2i_hq.json
drama assets --engine local --submit
# 4) 回填参考图 → 出片（本机 4 步工作流，9s 镜约 5 分钟）
python stages/import/pack_import.py --pack <ws>/pack --workspace <ws> --apply
drama video run --engine local --ep ep01 --limit 1 --workflow workflow_h3_local.json --yes
```

**补充实测（竖屏）**：`--aspect "9:16 (Portrait Widescreen)" --mp 0.4` → 480×864 / 24fps / 4.46s / 103s 渲染，
说明画幅通路本身没问题，问题只出在「镜头级比例没被传下去」。

**结论一句话**：Skill 的「文本产出」与引擎「契约」之间**没有自动化转换器**（`convert_to_pack.md` 是给 LLM 的提示词，不是代码）。
本轮用机械抽取验证了**格式上可识别**（人物卡 6/6、分镜 6/7），但要做到「一句话点子 → 成片」，
还差三个东西：**多批续写**、**资产卡三层映射**、**名字→代号映射**。

---

## 6. 四项实现与实测（2026-11-05 18:30）

| # | 原来 | 现在 | 关键落点 |
|---|---|---|---|
| 1 | 每次生成覆盖 + 不带上一批 | `write(append=True)` 追加（分隔线 + 备份）；`vars_for` 注入 `prior` / `batch_no` / `shot_from`；界面加「继续写第 N 批」 | `web/core/creation.py`、`app.py:/api/create/generate`、`create.js` |
| 2 | 8 镜/批 撞 8k 输出上限 | 提示词改成 **4–5 镜/批**，且明确「只写这一批、批次号用输入值」 | `stages/import/prompts/skill_director.md` |
| 3 | 资产卡三层没位置 | `variants[].kind ∈ base/turnaround/look/expression/state`（缺省按 code/label 推断），出图按「三视图 → 造型 → 表情」排序 | `pack_spec.py`、`gen_assets_local.py` |
| 4 | 没有确定性转换器 | 新增 `stages/import/md2pack.py`：资产库 + 导演手册 → pack（含名字→代号、缺口报告、严格/宽松两种 cast 策略） | `md2pack.py`、命令 `convert.apply` |

### 6.1 续写实测（同一集连写两批，真调 DeepSeek）

```
第 1 批  batch_no=1 shot_from=1  → 11385 字，镜 1–5，头部「第1批」
第 2 批  batch_no=2 shot_from=6  → 7103 字，镜 6–10，头部「第2批」，追加写入（旧版留 .bak）
整份    镜号 1–10，无重复，10/10 镜都有 A/B 段，finish_reason=stop（无截断）
```

### 6.2 转换实测（这份 10 镜手册）

```
资产：character 6（含 P01 的 VIEW / LOOK-A / LOOK-C / LOOK-D 四个 kind）
分集：ep01(10 镜 / 92s)      ← 92s 超 60–80s，是模板节奏问题，不是转换问题
缺口：资产 20 项（场景/道具还没写批）、分镜 19 项（cast 缺资产、台词未映射）
导入：pack_import --apply → OK（7 个文件）
```

### 6.3 转换器的两种 cast 策略

- **默认严格**：镜头的「参考图」行引用到资产库里还没有的资产 → 原样保留，让 `pack_import`
  以 `SHOT010` 拦下。缺资产是事实，不该被脚本抹掉。
- **`--drop-missing-cast`**：资产库还没补齐（只写了人物批）时，把缺失参考图从 cast 移除，
  并**连带摘掉对应的 `{{Mixed n}}` 行**（否则撞 `SHOT016`，而且真出片时模型在等一张没上传的图）。
  每一条都写进 `_import_report.md`。

> 两种模式的差别写在命令行参数上，不是隐藏开关 —— 因为它改变的是「这一镜用什么图」。
