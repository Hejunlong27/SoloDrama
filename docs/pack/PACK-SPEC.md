# 制作包规范 v1（Production Pack Spec）

> 本文件是分支 `feat/pack-engine` 的**唯一输入契约**。
> 引擎只认这份规范；创作（选题、剧本、资产设计、导演、分镜、提示词）全部在引擎之外，
> 由可插拔的创作 Skill 完成，产出本规范描述的制作包后交给引擎批量执行。

## 一、定位：引擎不做创作

| 能力 | 归属 | 说明 |
|---|---|---|
| 选题、市场调研、爆款拆解 | **Skill** | 引擎无相关代码 |
| 剧本、对白、分集结构 | **Skill** | 引擎只读台词文本用于字幕 |
| 资产设计（人物/场景/道具设定） | **Skill** | 引擎只收「出图提示词 + 编号」 |
| 导演、分镜、镜头设计 | **Skill** | 引擎只收「镜号 + 时长 + 分镜图提示词 + 视频提示词」 |
| 提示词工程（六段式、风格锁） | **Skill** | 引擎只做拼装与净化，不发明 |
| **批量出图** | 引擎 | 本地 ComfyUI |
| **批量出分镜图** | 引擎 | 每镜一张首帧 |
| **批量出视频** | 引擎 | 本地 ComfyUI |
| **剪辑交付** | 引擎 | 母版拼接、放大、字幕、交付规格、发布版导出 |

一句话：**Skill 决定「拍什么」，引擎负责「把它批量做出来」。**

## 二、制作包目录

```
<pack>/
├── pack.json                 必需  项目元信息 + 全季风格锁
├── assets/
│   ├── characters.json       可选  人物资产（含服装线/状态变体）
│   ├── scenes.json           可选  场景资产
│   └── props.json            可选  道具资产
├── episodes/
│   ├── ep01.json             必需  第 1 集镜头表
│   └── ep02.json
└── refs/                     可选  参考图原图（文件名 = 资产 ID，见 §6）
    ├── P01.png
    └── S01.png
```

规则：

1. **一个制作包 = 一部剧的一季**。集数与 `pack.json.delivery.episode_count` 一致。
2. `episodes/*.json` 的文件名决定集号，必须是 `epNN.json`（两位数，`ep01`…`ep99`；≥100 集用三位）。
3. 包内**不放图片产物**。参考图只放 `refs/`，出图产物由引擎写到工作区 `04-资产/`。
4. 编码 UTF-8（无 BOM），JSON 用 2 空格缩进。引擎对 BOM 容错。

## 三、`pack.json`

```json
{
  "spec": "solodrama-pack/1",
  "title": "亿万丈夫的三个月合约",
  "slug": "billionaire-contract",
  "logline": "为了给母亲治病，女设计师和冷面总裁签了一年的契约婚姻。",
  "skill": {
    "name": "tianchong-manju",
    "version": "2026-11-02",
    "source": "总裁甜宠AI漫剧 SKILL.MD"
  },
  "delivery": {
    "width": 1080,
    "height": 1920,
    "fps": 24,
    "episode_count": 30,
    "target_duration": 240
  },
  "style_lock": "美式复古影视风格，胶片颗粒，年代色偏，自然窗光与钨丝灯，轻微褪色",
  "negative": "多余手指，五官扭曲，比例失调，Q版，卡通，真人实拍，文字，水印",
  "aspect": {
    "character": "16:9",
    "scene": "16:9",
    "prop": "16:9",
    "board": "9:16",
    "video": "9:16"
  },
  "channels": {
    "image": null,
    "video": null
  },
  "notes": "可选，任意说明"
}
```

| 字段 | 必需 | 类型 | 约束 |
|---|---|---|---|
| `spec` | 是 | string | 固定 `solodrama-pack/1`；不匹配即拒绝导入 |
| `title` | 是 | string | 剧名，用于项目显示与发布版目录 |
| `slug` | 否 | string | 目录安全名；缺省由 `title` 生成 |
| `logline` | 否 | string | 一句话故事，仅展示 |
| `skill` | 否 | object | 溯源自哪个创作 Skill；只记录不解析 |
| `delivery` | 是 | object | 交付规格，见下 |
| `style_lock` | **是** | string | **全季风格串**，非空；拼进每条出图/出片提示词 |
| `negative` | 否 | string | 全局负面词，拼进每条出图提示词 |
| `aspect` | 否 | object | 各类型画幅；缺省用引擎默认（见 §7.2） |
| `channels` | 否 | object | 通道偏好；`null` 表示走引擎的通道确认单 |

`delivery` 子字段：

| 字段 | 必需 | 默认 | 说明 |
|---|---|---|---|
| `width` / `height` | 否 | 1080 / 1920 | 交付容器尺寸；非 1080×1920 需显式声明 |
| `fps` | 否 | 24 | 帧率 |
| `episode_count` | 是 | — | 本季集数；与 `episodes/` 文件数不符 → 导入警告 |
| `target_duration` | 否 | 0 | 单集目标秒数，仅用于成本预估与超时告警 |

### 3.1 `style_lock` 是硬约束

引擎**不再提供画风三轨选择**（`3d_manhua` / `2d_animation` / `live_action` 已下线）。
画风由 Skill 在 `style_lock` 里一次性定死，理由：

- 画风是创作决策，不是执行参数；放在引擎里选，等于让两个角色同时决定同一件事。
- 同一季中途换画风会让已出素材作废，而引擎无法判断「换了没有」。
- `style_lock` 为空 → 导入直接失败（退出码 2），不猜、不兜底。

## 四、资产 JSON

人物、场景、道具**共用一套 schema**，靠 `kind` 区分。

```json
{
  "spec": "solodrama-assets/1",
  "kind": "character",
  "items": [
    {
      "id": "P01",
      "name": "何暖",
      "role": "女主，28 岁，建筑设计师",
      "anchors": ["左眉尾有一颗小痣", "常戴细银链"],
      "variants": [
        {
          "code": "LOOK-A",
          "label": "职场装",
          "prompt": "美式复古影视风格角色设定图，胶片颗粒质感……",
          "aspect": "9:16",
          "episodes": ["ep01", "ep02", "ep03"]
        },
        {
          "code": "LOOK-B",
          "label": "居家装",
          "prompt": "……",
          "episodes": ["ep04"]
        }
      ]
    }
  ]
}
```

| 字段 | 必需 | 说明 |
|---|---|---|
| `spec` | 是 | 固定 `solodrama-assets/1` |
| `kind` | 是 | `character` / `scene` / `prop` |
| `items[].id` | 是 | 资产 ID，见 §4.1；**全包唯一** |
| `items[].name` | 是 | 中文名，用于文件名 |
| `items[].role` | 否 | 身份描述，仅人读 |
| `items[].anchors` | 否 | 一致性锚点，仅人读；引擎不解析、不校验 |
| `items[].variants` | 是 | 至少 1 条；每条 = 一张要出的图 |
| `variants[].code` | 是 | 变体代号（`LOOK-A` / `空景` / `状态-1`）；同一资产内唯一 |
| `variants[].prompt` | 是 | **完整可提交的提示词**，引擎逐字使用，不裁剪不补写 |
| `variants[].aspect` | 否 | 画幅；缺省取 `pack.aspect[kind]` |
| `variants[].episodes` | 否 | 使用集列表；仅用于「按集出图」筛选与缺图告警 |

### 4.1 资产 ID 命名

| kind | 前缀 | 示例 | 说明 |
|---|---|---|---|
| character | `P` | `P01`、`P02` | P = person |
| scene | `S` | `S01`、`S02` | S = scene |
| prop | `D` | `D01` | D = device / prop |
| 特效 | `FX` | `FX01` | 只做后期氛围层，不进视频参考槽 |

约束：

- ID 形如 `^[A-Z]{1,3}\d{2,3}$`（大写字母 + 2–3 位数字）。
- 前缀与 `kind` 必须匹配：`character` 只接受 `P`，`scene` 只接受 `S`，`prop` 只接受 `D`。
  允许 `prop` 使用 `FX` 前缀，导入后归入 `props`，并标记 `post_only: true`（默认不上传视频模型）。
- 不同 `kind` 之间 ID 不得重复。

### 4.2 出图产物落点与命名

```
<工作区>/04-资产/
├── characters/P01_何暖_LOOK-A.png
├── scenes/S01_客厅.png
└── props/D01_合约.png
```

- 文件名 = `<ID>_<name>` + （多变体时）`_<code>`。
- 单变体且 code 属于 `基础` / `base` / `空景` 时省略 code 后缀。
- 引擎出图前会检查同名文件：已存在且提示词指纹未变 → 跳过（不重复计费）。

## 五、分集镜头表 `episodes/epNN.json`

```json
{
  "spec": "solodrama-episode/1",
  "episode": 1,
  "title": "契约成婚",
  "duration_total": 63,
  "shots": [
    {
      "id": "shot_001",
      "duration": 6,
      "ratio": "9:16",
      "cast": [
        { "asset": "P01", "variant": "LOOK-A" },
        { "asset": "P02", "variant": "LOOK-A" },
        { "asset": "S01" },
        { "asset": "D01" }
      ],
      "board_prompt": "办公室。何暖在画左站着，手拿合同，面朝画右……",
      "video_prompt": "subject_definitions://n<Picture 1> 是本镜分镜图……\n<Subject 1> 是 <Picture 2> 中的何暖……\n\nsummary://n[reference generation] ……",
      "dialogue": [
        { "asset": "P01", "text": "一年，互不干涉。", "start": 0.4, "end": 2.2 }
      ],
      "shots_within": 1,
      "notes": "可选"
    }
  ]
}
```

| 字段 | 必需 | 约束 |
|---|---|---|
| `spec` | 是 | 固定 `solodrama-episode/1` |
| `episode` | 是 | 正整数；必须与文件名一致 |
| `title` | 否 | 集名 |
| `duration_total` | 否 | 声明总时长；与 `shots[].duration` 之和相差 >2s → 导入警告（不阻断） |
| `shots` | 是 | 非空数组，按时间顺序 |
| `shots[].id` | 是 | `shot_NNN`（三位起）；集内唯一、连续 |
| `shots[].duration` | 是 | 整数，**4–15 秒**（平台硬限）；超出 → 导入失败 |
| `shots[].ratio` | 否 | 缺省取 `pack.aspect.video` |
| `shots[].cast` | 是 | 参考图列表，**顺序即参考槽顺序**；至少 1 项 |
| `cast[].asset` | 是 | 必须在资产 JSON 里存在，否则导入失败 |
| `cast[].variant` | 否 | 缺省取该资产的第一个变体 |
| `shots[].board_prompt` | 是 | 分镜图提示词；空则跳过该镜分镜图并在 `ingest` 报缺 |
| `shots[].video_prompt` | 是 | 视频提示词，引擎逐字提交。**必须是 H3 多参六段式**（见 §5.3），台词写成 `<d>[语种] 原句。</d>` |
| `shots[].dialogue` | 否 | 台词；只用于字幕对齐，不参与出片 |
| `shots[].shots_within` | 否 | 段内切点数，仅展示 |

### 5.1 `cast` 顺序就是参考槽顺序

平台侧参考图槽位是固定的（H3 六槽）。`cast` 的数组顺序直接决定：

- `<Picture 1>` = 分镜图（本镜有分镜图时；它固定占 1 号）
- `<Picture 2>` = `cast[0]`
- `<Picture 3>` = `cast[1]`
- …

所以 `video_prompt` 里的 `<Picture n>` 必须与 `cast` 顺序**逐位对应**。导入器会做一次
机械校验：`video_prompt` 里出现的最大图号不得大于 `len(cast) + 1`，否则报错。
如需重排，改 `cast` 顺序，引擎会同步重排提示词里的图号（见 §8）。

> 老包里的 `{{Mixed n}}` / `{{Picture n}}` 仍被接受并同样校验；`md2pack` 会把它们
> 机械归一成 `<Picture n>`（H3 只认后者）。新包不要再写 `{{…}}`。

### 5.2 台词块是可选的，但字幕依赖它

引擎的字幕时间**必须来自真实对齐**（ASR/CTC）。`dialogue` 提供三个作用：

1. 给对齐器一个文本先验（提高准确率）；
2. 给导入器一个「本集应有几句台词」的基线，用于发现漏句；
3. 不做对齐时，作为人工核对清单。

没有 `dialogue` 也能出片，字幕走纯 ASR 通道。

### 5.3 视频提示词：H3 多参六段式 + `<d>` 标记

`video_prompt` **必须**是 H3 多参（Ref2VA）六段式，顺序固定：

```
subject_definitions → summary → retention_analysis
→ detailed_description → overall_soundscape → non_diegetic_music
```

它不是文风偏好，而是「哪张参考图是谁」的唯一声明。缺 `subject_definitions` /
`retention_analysis` 时，上传的参考图对模型只是「几张没署名的图」，人物与场景会漂 ——
出片能出，但每条都要重跑。判据见 `stages/import/h3_prompt.py`，完整契约与样例见
[`H3-REF2VA-PROMPT.md`](H3-REF2VA-PROMPT.md)。

| 判据 | 行为 |
|---|---|
| 六段缺失 / 顺序错 / 残留 `{{Mixed n}}` / 出现 `<Video n>` | `SHOT019` **阻断** |
| `<Subject n>` 缺失或编号不连续、图号空号或越界、`retention_analysis` 缺行或标记词自造 | `SHOT020` **阻断** |
| 正文过短、缺 `[Shot 1]`、缺时间戳、缺 `(Sx)`、配乐留空 | `SHOT021` 告警 |

#### 5.3.1 台词必须带 `<d>` 标记

`video_prompt` 里的对话**一律**写成 `<d>[语种] 原句。</d>`（中文项目即 `<d>[Chinese] …</d>`）。
裸写在引号里的目标语言文本会被 H3 当成「画面中应当出现的文字」，**直接烧成画面字幕**，
出片后无法去除，只能重跑（2026-11-06 同实例三组对照实测，固定 seed 123456）。

| 写法 | 模型的理解 | 结果 |
|---|---|---|
| `说："这个箱子周三之前不许开"` | 画面里应该出现的文字 | 渲染成字幕 |
| `说：<d>[Chinese] 这个箱子周三之前不许开。</d>` | 一个语音事件（谁说、说什么） | 驱动口型与配音，**不落到画面** |

三条要求：

1. 一句一个 `<d>`；句末必须是 `。？！`（西语/英语项目的 `.!?` 同样成立）。
2. 语种标签必填，跨语种项目改标签即可（`<d>[Spanish] …</d>`），不要另起一套写法。
3. 本镜不开口的角色写「闭口」，不要给他/她加 `<d>`；内心独白与画外音不写 `<d>`，只写在「音效」段。

判据与归一化只有一份实现：`stages/import/prompt_marks.py`。
产生方式不同，兜底程度也不同：

| 来源 | 兜底 |
|---|---|
| `md2pack.py` 转换（模板/手册） | **自动补标记**，并在 `_import_report.md` 里逐镜留痕 |
| 手写 pack / 别的 Skill 直接产出 | 不自动改；导入时 `SHOT018` **告警**（不阻断） |
| 已出片的老项目 | `python stages/import/prompt_marks.py --workspace <剧目录> --apply` 重写 `h3_prompts.json`（先落 `.bak`），再重跑受影响的镜 |


## 六、参考图 `refs/`

```
refs/P01.png        人物主参考（优先用出图产物，没有才用这里）
refs/S01.png
refs/D01.png
```

规则：

1. 文件名主干必须是资产 ID；扩展名 `.png` / `.jpg` / `.jpeg` / `.webp`。
2. 引擎优先用 `04-资产/` 里的出图产物；`refs/` 只在出图尚未完成时兜底。
3. 参考图会被 `prepare_refs.py` 瘦身到平台可接受尺寸（默认长边 1568）。

## 七、与旧契约的映射

导入器负责把制作包翻译成出片引擎吃的 `data/` 五文件。这张表是**唯一映射口径**。

| 制作包 | 引擎 `data/` | 生成时机 |
|---|---|---|
| `episodes/*.json` 的 shots | `shots.json` | 导入 |
| `shots[].board_prompt` | `boards.json` | 导入 |
| `shots[].video_prompt` + `duration` + `ratio` | `h3_prompts.json` | 导入 |
| `assets/characters.json` + 出图产物 | `characters.json` | 出图后回填 |
| `assets/scenes.json` + 出图产物 | `scenes.json` | 出图后回填 |
| `assets/props.json` + 出图产物 | `characters.json`（同表） | 出图后回填 |

> `props` 与 `characters` 共用参考图表，因为引擎按 key 查表、不区分角色与道具。
> 导入器会把 `D*` / `FX*` 的 key 一并写进 `characters.json`。

### 7.1 `shots.json` 逐字段

| 字段 | 取值 |
|---|---|
| `shot_id` | `shots[].id` |
| `ratio` | `shots[].ratio` 或 `pack.aspect.video` |
| `crop` | 固定 `{"rows":1,"cols":1}`（九宫格链已下线，保留字段兼容引擎） |
| `board_ref` | `board_<ep>_<shot_id>` |
| `character_refs` | `cast` 中 `P*` / `D*` / `FX*` 的 key，按 `cast` 顺序 |
| `scene_refs` | `cast` 中 `S*` 的 key，按 `cast` 顺序 |

### 7.2 画幅默认值

| 类型 | 默认 | 理由 |
|---|---|---|
| character | `16:9` | 角色设计卡固定横版：左侧三视图、右侧 2×2 表情四宫格 |
| scene | `16:9` | 场景资产卡统一横版，便于构图与复用 |
| prop | `16:9` | 道具资产卡统一横版，和角色/场景设计稿同规格 |
| board | `9:16` | 与成片同构，作为首帧 |
| video | `9:16` | 竖屏短剧交付规格 |

> **16:9 资产卡是设计资产，不是视频直用构图。** 角色卡还包含三视图和 2×2 表情格；
> 下游视频参考应使用从卡面裁出的**单正面视图**（或单独的 `base` / `look` 9:16 图），
> 不要把整张多视图卡直接喂给竖屏视频模型。否则模型可能把多个视图误判成多个人物。

## 八、导入器的三道校验

导入默认**干跑**（只报差异、不落盘）。加 `--apply` 才写 `data/`。

### 8.1 结构校验（阻断，退出码 2）

- `spec` 版本不匹配
- 缺必需字段
- `shot.duration` 越界（<4 或 >15）
- `cast.asset` 引用了不存在的资产
- `video_prompt` 不是 H3 六段式（`SHOT019`）
- 六段里的标签对不上：Subject 缺失/编号不连续、图号空号或越界、retention 缺行（`SHOT020`）
- 资产 ID 前缀与 `kind` 不符
- `style_lock` 为空
- 同一资产内 `variant.code` 重复

### 8.2 一致性告警（不阻断，退出码 0 + WARN）

- `duration_total` 与逐镜求和相差 >2s
- `episodes/` 文件数 ≠ `episode_count`
- `cast` 中的资产在 `assets/*.json` 里没有 `prompt`（无法出图，出图阶段会缺）
- `video_prompt` 的图号超过 `len(cast) + 1`（`SHOT016`）
- 六段写得不完整：正文过短、缺 `[Shot 1]`、缺时间戳、缺 `(Sx)`、配乐留空（`SHOT021`）
- `video_prompt` 里有引号包住的中文台词却没包 `<d>` 标记（`SHOT018`，见 §5.3）
- 某资产被多集引用，但 `variants[].episodes` 未覆盖该集
- 分镜图提示词缺失

### 8.3 图号：作者负责，导入只校验形状

> 2026-11-06 更正：本节此前写「导入器会按 cast 顺序机械重排图号」——**没有这个实现**。
> 文档说有、代码没有，比写错更危险：人会以为写错了也会被自动修好。

规则只有一条，由作者遵守：

- `board_ref` 固定占 `1` 号（本镜有分镜图时）；
- `cast` 里的资产从 `2` 号起，**按数组顺序**依次排。

导入器**只校验形状**，不改内容：

| 校验 | 判据 |
|---|---|
| 图号连续 | `<Picture n>` 必须从 1 起连续，不留空号（`SHOT020`） |
| 不越界 | 最大图号 ≤ `len(cast) + 1`（`SHOT016` / `SHOT020`） |
| 不悬空 | 六段里出现的每个 `<Picture n>` 都要在 `subject_definitions` 里被解释（`SHOT020`） |

**「第 2 张图到底是哪个资产」导入器无法判断** —— 它读不出中文描述里的语义。
写错顺序不会被拦，只会表现为「模型把场景当成了人」。所以模板与提示层把
「`<Picture n>` = 上传顺序」写成硬规则，转换时逐镜对位。

## 九、Skill 侧的产出责任

任何创作 Skill 要接进本引擎，只需交付制作包。三种交付方式：

| 通道 | Skill 要做的 | 确定性 | 适用 |
|---|---|---|---|
| **A 原生包** | 直接按本规范写 JSON | 100% | 有代码能力的 Skill |
| **B 模板解析** | 按固定 Markdown 模板产出（见 `docs/pack/MD-TEMPLATE.md`） | 高 | 沿用现有 Markdown 工作流的 Skill |
| **C LLM 适配** | 产出任意 Markdown，用 `docs/pack/IMPORT-PROMPT.md` 转换 | 中 | 一次性接入、格式不固定 |

三条通道最终都汇聚到同一份 `pack.json` + `assets/` + `episodes/`，
下游（出图/出片/剪辑）完全不知道上游是哪种通道。

### 9.1 Skill 不得触碰的字段

以下字段由引擎写入，Skill 产出时**即使写了也会被覆盖**：

- `data/` 下全部文件（引擎独占）
- `04-资产/` 下产物文件名
- `pack.json.delivery.width/height`（除非显式声明非标规格）

## 十、样例：从「总裁甜宠」Skill 到制作包

仓库里有一份可直接跑的端到端样例：

```
stages/import/tests/fixtures/tianchong_demo/
├── source_导演手册_第01集.md      ← 创作 Skill 的人读产出（时间轴总表 + A段/B段）
└── pack/                          ← 转换后的制作包（引擎吃的）
    ├── pack.json
    ├── assets/{characters,scenes,props}.json
    └── episodes/ep01.json
```

```bash
# 只看校验结果（不写盘）
python stages/import/pack_import.py --pack stages/import/tests/fixtures/tianchong_demo/pack \
  --workspace <工作区>

# 导入
python stages/production/scripts/drama.py pack import \
  --pack stages/import/tests/fixtures/tianchong_demo/pack --apply
```

样例覆盖了三个最容易出错的点，可作对照：

| 点 | 样例里的做法 | 错法 |
|---|---|---|
| 图号 | 分镜图占 `<Picture 1>`，`cast[0]` 从 `<Picture 2>` 起 | `<Picture 1>` 写成人物 → 导入报图号错位（`SHOT020`） |
| 时长 | 6 / 6 / 4，合计 16 与 `duration_total` 一致 | 把一条长镜拆成 3s + 3s 两个 shot → 3s 越界被拒 |
| 风格 | `style_lock` 是完整一句（风格 + 色彩 + 光影） | 只写「美式复古」→ 出图风格漂 |

## 十一、版本与兼容

- 本规范版本 `v1`，spec 字符串 `solodrama-pack/1`。
- 加字段：向后兼容，旧包照常导入（未知字段忽略并告警）。
- 改语义 / 删字段：升 `spec` 主版本，导入器同时支持 `v1` 与新版一个过渡期。
- 导入器的 spec 支持列表写在 `stages/import/pack_spec.py::SUPPORTED`。
