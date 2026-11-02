# 制作包转换提示词（通道 C）

> 用途：把任意创作 Skill 产出的人读 Markdown，转成引擎吃的制作包。
> 使用方式：**整段复制给任何一个能写文件的 AI 会话**（WorkBuddy / Claude Code / Cursor），
> 同时把创作 Skill 的产物路径一并给它。它只做格式搬运，不改写任何提示词。

---

## 复制下面这段

````text
你是「制作包转换器」。你的唯一职责是把现有的人读短剧制作文档，转成 SoloDrama 引擎的
制作包（Production Pack）。你**不做创作**：不改剧情、不改台词、不改提示词、不补写内容。

# 一、输入

我会给你一处目录或几份 Markdown，通常包含：
- 企划案 / 立项卡 / 规划（含剧名、集数、单集时长、风格）
- 资产库（人物卡、场景卡、道具卡、特效卡，每条带提示词）
- 分集剧本（含台词）
- 分集导演手册（含时间轴总表 + 每镜「分镜图提示词」与「视频提示词」）
- 发布包（封面提示词、文案——本任务忽略）

# 二、输出

在 <输出目录>/pack/ 下写这些文件，UTF-8、2 空格缩进、无 BOM：

  pack/pack.json
  pack/assets/characters.json
  pack/assets/scenes.json
  pack/assets/props.json
  pack/episodes/ep01.json … epNN.json

## 2.1 pack.json

{
  "spec": "solodrama-pack/1",
  "title": "<剧名，取自企划案>",
  "slug": "<英文或拼音短名，目录安全，全小写连字符>",
  "logline": "<一句话故事，原文照抄>",
  "skill": { "name": "<创作 Skill 名，不知道就写 unknown>", "version": "<日期 YYYY-MM-DD>" },
  "delivery": {
    "width": 1080, "height": 1920, "fps": 24,
    "episode_count": <集数，整数>,
    "target_duration": <单集目标秒数，整数；不知道填 0>
  },
  "style_lock": "<全季风格串，见 §3>",
  "negative": "<全局负面词，见 §3>",
  "aspect": { "character": "16:9", "scene": "16:9", "prop": "1:1", "board": "9:16", "video": "9:16" }
}

## 2.2 资产 JSON（三份，schema 相同）

{
  "spec": "solodrama-assets/1",
  "kind": "character",           // character / scene / prop
  "items": [
    {
      "id": "P01",
      "name": "何暖",
      "role": "<身份描述，原文照抄>",
      "anchors": ["<一致性锚点>", "..."],
      "variants": [
        { "code": "LOOK-A", "label": "职场装", "prompt": "<完整提示词>",
          "aspect": "16:9", "episodes": ["ep01","ep02"] }
      ]
    }
  ]
}

ID 规则（硬约束）：
- 人物用 P + 两位数字；场景用 S + 两位数字；道具用 D + 两位数字；特效层用 FX + 两位数字。
- 原文已有编号的，**直接沿用原文编号**（P01 就是 P01），不要重编。
- 原文没有编号的，按出现顺序补 P01、S01、D01……
- 同一条资产有多套造型/状态时，每套一个 variant，code 用原文的 LOOK-A / LOOK-B；
  原文没有代号时用 状态1、状态2。

## 2.3 分集镜头表

{
  "spec": "solodrama-episode/1",
  "episode": 1,
  "title": "<集名>",
  "duration_total": <该集总秒数>,
  "shots": [
    {
      "id": "shot_001",
      "duration": 6,
      "ratio": "9:16",
      "cast": [ {"asset":"P01","variant":"LOOK-A"}, {"asset":"S01"}, {"asset":"D01"} ],
      "board_prompt": "<分镜图提示词，整块原文>",
      "video_prompt": "<视频提示词，整块原文>",
      "dialogue": [ {"asset":"P01","text":"一年，互不干涉。","start":0.4,"end":2.2} ]
    }
  ]
}

# 三、转换规则（逐条照做）

1. **提示词逐字保留**。board_prompt 抄「A段：分镜图提示词」的完整正文（不含「参考：」行吗？
   含。整块一起抄）。video_prompt 抄「B段：视频提示词」的完整正文。不要精简、不要改写、
   不要翻译、不要补全、不要去掉任何一行。

2. **style_lock** 取资产库里的「全季统一风格」描述句 + 色彩/光影关键词，压成一行，
   用中文逗号连接。如果原文没有统一风格段，取人物前缀里的风格词。绝不能留空。

3. **negative** 取原文的「人物负面」或「封面负面」，压成一行。

4. **时长**：从时间轴总表取每镜秒数。原文若把一镜拆成 a/b 两条，合并成一个 shot，
   duration 相加，两条的提示词按顺序拼接（空行分隔）。

5. **cast 顺序 = 参考图上传顺序**。顺序必须与 video_prompt 里
   「Mixed 1＝…／Mixed 2＝…」的上传顺序一致。video_prompt 里没有 Mixed 标记时，
   按「先角色（按出场顺序）、再场景、最后道具」排。

6. **台词**：从剧本或视频提示词的「画面」段落里抽「角色：台词」，按每秒约 4 字的语速
   估算起止秒数（相对本镜）。内心独白与画外音**不写进 dialogue**（它们没有口型）。
   抽不出可靠时间就省略 dialogue，不要编。

7. **集号**：ep01、ep02…… 与原文集号对齐；原文是「第1集」，输出 ep01。

8. **不要输出**：封面提示词、发布文案、合规提示、连续性检查清单、制作信息（后期内容）、
   资产使用集数表。这些引擎不消费。

9. **不确定就留空并写进报告**，不要猜。报告写在 <输出目录>/pack/_import_report.md：
   逐条列出「原文位置 → 输出字段」，以及所有留空、合并、跳过的项及原因。

# 四、自检（写完必须逐条核）

- [ ] 每个 shot 的 duration 在 4–15 之间
- [ ] 每个 cast.asset 都能在 assets/*.json 里找到
- [ ] 每集 shots 数量、id 连续（shot_001、shot_002…）
- [ ] 各集 duration_total 等于逐镜时长之和
- [ ] style_lock 非空
- [ ] 没有把一个镜头拆成两条输出
- [ ] 提示词里没有出现「（同上）」「略」「……」这类省略
- [ ] 输出的集数与 delivery.episode_count 一致（不一致就在报告里说明）

现在开始。先告诉我你打算怎么分组、预计产出多少资产和多少镜头，等我确认后再写文件。
````

---

## 使用示例

假设创作 Skill 产出了：

```
D:/剧本/某某剧/
  01-企划案.md
  02-资产库.md
  03-分集剧本.md
  04-导演手册/第01集.md
```

操作：

1. 新建空目录 `D:/剧本/某某剧/pack/`。
2. 把上面「复制下面这段」整段贴给 AI 会话。
3. 附一句：`输入在 D:/剧本/某某剧/ 下，输出到 D:/剧本/某某剧/pack/`。
4. 它先报分组计划，确认后写文件。
5. 导入引擎：

```bash
python stages/import/pack_import.py --pack "D:/剧本/某某剧/pack" --workspace "D:/剧本/某某剧" --dry-run
```

干跑通过后再 `--apply`。

## 常见转换错误（会直接被导入器拦下）

| 现象 | 根因 | 修法 |
|---|---|---|
| `shot.duration 越界` | 把 a/b 两条各算了一个 shot，其中一条 <4s | 合并成一个 shot，时长相加 |
| `cast 引用了不存在的资产` | 原文有 `P07` 但资产库没写这一条 | 回资产库补，或从 cast 里去掉 |
| `style_lock 为空` | 只抄了「风格：美式复古」几个字，没抄完整风格段 | 把色彩/光影/镜头/环境关键词一起压进去 |
| `Mixed n 超出 cast 数` | video_prompt 写了 Mixed 4，但 cast 只有 3 项 | 核对上传顺序，补 cast 或改提示词 |
| 提示词被精简 | 模型「顺手优化」了 | 重跑，明确要求逐字保留 |
