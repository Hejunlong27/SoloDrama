# 封面提示词工程规范（AI 直出带字封面）

> **2026-10-20 起的唯一主路径**。上一版是「AI 出无字底图 → PIL 排版引擎叠字」，
> 用户明确否决：**要一张由 AI 直接生成的、带标题的完整海报**，不要程序拼字。
> 排版引擎 `cover_forge.py` 降级为**兜底**（仅当 AI 反复拼错字、inpaint 也修不好时使用）。
>
> 交付目标不是「一张图」，而是：**符合目标市场审美、有爆款潜质、内容抓马、缩略图里也抓眼**的封面。

---

## 一、为什么 AI 直出比程序叠字更可能出爆款

程序叠字的天花板是「干净但平」：标题永远是一行标准字体压在图底部，人物和文字各说各话。
而爆款封面是**一张构图里同时完成叙事与情绪**——两个人物的距离、眼神、手的位置、光的落点，
都在替标题说话。这类东西只能由生成模型整体画出来。

代价也要写清楚：**AI 写字会拼错**。所以本规范用两件事对冲：
① 把「文字排版」写成模型能执行的强约束（见 §四）；
② 设一条五级降级路径（见 §七），拼错不等于交付失败。

---

## 二、提示词的五段式结构（顺序不能换）

模型对**先出现的信息**权重更高，且「风格」一旦定了，「内容」必须服从它。所以顺序是：

| 段 | 名称 | 作用 | 典型长度 |
|---|---|---|---|
| ① | **STYLE ANCHOR** | 一句话钉死画风/媒介/质感（电影海报 / 剧照感 / 超写实 / 胶片颗粒） | 15–30 词 |
| ② | **SUBJECTS & RELATIONSHIP** | 谁、穿什么、什么关系、身体距离、手在哪、看哪 | 60–120 词 |
| ③ | **SCENE & LIGHT** | 地点、时间、光源方向与色温、天气、景深 | 40–80 词 |
| ④ | **COMPOSITION & TYPOGRAPHY** | 机位/景别、主体占比、文字块位置与字体气质、**逐条写出要渲染的确切文字** | 80–160 词 |
| ⑤ | **TECH & NEGATIVE** | 画幅、分辨率、镜头参数、负面词 | 30–60 词 |

**纪律**
- 全程英文（模型对英文排版指令的服从度显著更高）；中文只用于「给人看的设计说明」。
- 一段一件事，不用形容词堆叠。`beautiful, stunning, masterpiece` 这类空词一律删——
  它们不改变像素，只稀释真正的约束。
- 每段之间空行，便于人工 diff 与版本管理。

---

## 三、风格锚库（STYLE ANCHOR 可直接抄）

按「市场 × 题材」选一条，**不要混用**（混用会得到四不像）。

| ID | 适用 | 锚句 |
|---|---|---|
| `latam-rain-night` | 拉美都市情感 / 豪门 | `Cinematic telenovela poster, hyper-realistic photography, shot on 85mm f/1.4, rain-soaked night street seen through a glass window, warm tungsten practicals against cold blue neon bokeh, subtle film grain, shallow depth of field, glossy magazine finish` |
| `latam-mansion-gold` | 豪门家宴 / 继承争夺 | `Luxury drama key art, warm amber chandelier light, marble and dark wood interior, gold accents, rich shadows, editorial fashion photography, medium format look, elegant and oppressive` |
| `office-revenge` | 职场复仇 / 逆袭 | `Modern revenge drama poster, cold glass-and-steel office at dusk, hard side light through blinds, desaturated teal palette with one crimson accent, sharp corporate styling, high contrast` |
| `suspense-noir` | 悬疑 / 身份谜题 | `Neo-noir thriller poster, single hard key light, deep blacks, wet asphalt reflections, smoke haze, anamorphic flare, muted palette, unsettling stillness` |
| `family-estate` | 家族伦理 / 乡土 | `Prestige family saga key art, late-afternoon golden hour, old estate courtyard, dust in the air, warm earth tones, painterly realism, dignified composition` |

> 风格锚里已经包含「光位 + 色彩 + 镜头」，**不要在第③段重复**，否则模型会打架。

---

## 四、TYPOGRAPHY 段：怎么写模型才肯照做

AI 不是排版软件，它对「文字」的理解是**图像区域**。所以文字指令必须同时给出
**确切字符串 + 位置 + 层级 + 字体气质 + 颜色**，并且**放在 prompt 靠后但独立成段**
（放最前面会被当成风格描述，放最后会被截断）。

### 4.1 标准写法（照抄改内容）

```
Typography — render this text exactly, correctly spelled, no extra words:
- Headline: "ME CASÉ CON UN MULTIMILLONARIO AMNÉSICO" — elegant high-contrast serif,
  all capitals, warm champagne-gold with a subtle bevel and soft drop shadow,
  centered in the upper third, broken into three balanced lines, wide letter spacing.
- Top strip: three small caps labels, thin white sans-serif, evenly spaced across the
  top edge: "PAREDO BENYIDON"  "DRAMA MEXICO CITY"  "ROSTAR PAUL WATER".
- Subtitle: "UNA HISTORIA DE AMOR Y MEMORIAS PERDIDAS" — cream serif, smaller,
  centered just above the bottom edge, generous tracking.
- Bottom credits: one line of tiny condensed sans, low contrast, at the very bottom:
  "FICTIONAL DRAMA POSTER · UNA PRODUCCIÓN ORIGINAL".
Text must be fully inside the frame, never cropped, never overlapping faces.
```

### 4.2 硬约束（写进 prompt，也用于验收）

| 项 | 约束 | 理由 |
|---|---|---|
| 标题行数 | ≤ 3 行 | 超过 3 行模型必然错行/漏字 |
| 每行字符 | 西语 ≤ 18；中文 ≤ 6 | 缩略图可读性；也降低拼错概率 |
| 文字块数量 | ≤ 4 块（顶条 / 标题 / 副标 / 底注） | 块越多错字概率越高 |
| 与脸的关系 | 文字**不得压五官** | 压脸=废片，且平台缩略图会裁 |
| 位置 | 标题放上 1/3 或下 1/3，**避开中心人脸区** | 双人特写时中心一定是脸 |
| 颜色 | 与背后区域对比 ≥ 4.5:1；常用「香槟金 / 米白 / 纯白 + 描边」 | 夜景深底上金/白最稳 |
| 描边 | 必须显式写 `subtle bevel / soft drop shadow / thin dark outline` | 没有描边的白字在亮部会消失 |

### 4.3 绝对不要写

- ❌ `with beautiful typography`（模型不知道什么叫 beautiful）
- ❌ `movie title`（不给字符串 = 它自己编）
- ❌ 长句标题（> 18 字符/行）——拼错率随长度线性上升
- ❌ 中英混排标题（字形系统冲突，几乎必错）

---

## 五、抓马六抓手 → 提示词映射

发行资料清单 §三 的六抓手是**验收标准**，这里是**怎么把它们写进 prompt**。

| 抓手 | 提示词写法（可组合） |
|---|---|
| ① 单主体大特写 ≥45% | `tight chest-up framing, the two faces fill 60% of the frame height`；双人时写 `both faces in sharp focus, forehead-to-chin large in frame` |
| ② 强明暗对比 | `hard rim light on the jawline, deep unlit background, single warm practical as key` |
| ③ 可指认的冲突物 | 具体名词，不要抽象：`a divorce envelope between them` / `his wedding ring on her palm` / `a crumpled paternity test` |
| ④ 大字标题 | 见 §四；标题本身要是「一句话冲突」（见 §六） |
| ⑤ 悬念留白 | `negative space in the upper third, dark and empty except the headline` |
| ⑥ 情绪色撞色 | `warm amber key against cold cyan background` / `crimson accent on desaturated teal` |

> 每张封面**至少命中 5 条**。命中不足不是「风格问题」，是**不发行**。

---

## 六、文案：标题就是钩子

标题不是剧名搬运，是**把最抓马的一句话压到 6 个词以内**。

- 结构优先选：`我 + 动词 + 一个不该存在的对象`（我嫁给了一个失忆的亿万富翁 / 我的前夫是我老板）
- 悬念型：`那个说爱我的人，签了我的死亡证明`
- 反差型：`全家都以为我是保姆`
- 副标只做**一次反转补充**，不重复标题（`被羞辱 → 如今归我管`）。
- 顶部三栏是「剧种 / 地点 / 主演感」的**假演职员表**，作用是让它看起来像正规发行海报；
  可以用真实演员名，也可以是虚构名（**不得用真实名人肖像**，见 §八）。

## 七、文字拼错的五级处置（按代价从低到高）

1. **重试 1–3 次**（同 prompt，换 seed）：大标题短词的成功率通常 >70%。
2. **缩短标题**：把 `ME CASÉ CON UN MULTIMILLONARIO AMNÉSICO` 拆成
   `ME CASÉ CON UN` / `MULTIMILLONARIO` / `AMNÉSICO`（分行后每行更短，错字率显著下降）。
3. **强化权重**：把 typography 段提到第④段开头，并加
   `The headline text is the most important element; render every letter exactly.`
4. **局部重绘（inpaint）**：只框标题区重绘，其余像素不动——这是最省成本的修字法。
5. **兜底叠字**：以上都失败才用 `cover_forge.py` 在 AI 图上重排标题（它已降级为兜底工具）。
   **注意**：这是「补救」，不是主路径；用了要在交付说明里写明，避免下一版又回到老路子。

## 八、合规与平台

- **AIGC 标注**：封面上或发布文案中必须体现（整剧统一口径），不能靠「读者自己猜」。
- **不得**使用真实名人肖像/真实品牌 logo/真实平台 UI。
- 顶部「假演职员表」若用真实姓名，须确保是**虚构剧集**且不涉及诽谤；不确定就用虚构名。
- 尺寸与安全区（平台会裁边）：9:16 / 3:4 顶部与底部各留 ≥6% 安全边；16:9 左右各留 ≥5%。
- 交付同时给 **PNG（存档）+ JPG q92（上传）**；文件名带尺寸档，便于 `release_check.py` 识别
  （`cover_9x16.png` / `cover_3x4.png` / `cover_16x9.png`）。

## 九、验收清单（逐条打勾，缺一不交付）

```
[ ] 标题逐字母核对：与 brief 完全一致，0 错字、0 乱码、0 多余词
[ ] 标题 ≤3 行、每行 ≤18 字符（西语）/ ≤6 字（中文）
[ ] 文字未压五官、未被画框裁切
[ ] 缩略图 300px 宽时标题仍可读（缩到 300px 亲自看）
[ ] 主体面部占画面 ≥45%（双人 ≥40% 且两张脸都清晰）
[ ] 抓马六抓手 ≥5/6（逐条写清命中/未命中）
[ ] 色彩 ≤3 主色 +1 强调色；标题对比 ≥4.5:1
[ ] 服装/场景/道具符合目标市场（不是「通用欧美」）
[ ] 画面里没有多余手指、错位肢体、镜像文字、水印
[ ] 尺寸档齐全，命名符合 cover_<ratio>.png
[ ] prompt + seed + 工作流 ID 已存档（可复现）
[ ] AIGC 标注已定稿
```

## 十、完整示例（复刻「拉美雨夜豪门」型）

> 参考实拍：双人侧面对视、雨窗、金色三行大标题 + 顶部三栏小字 + 底部副标与演职员表。
> 见 `docs/distribution/发行资料清单.md` §三 的抓马六抓手。

```
[① STYLE]
Cinematic telenovela key art, hyper-realistic photography, 85mm f/1.4, rain-soaked night
street seen through a glass window, warm tungsten sconce light against cold blue neon
bokeh, subtle 35mm grain, glossy magazine finish.

[② SUBJECTS]
A man in his early thirties, navy chalk-stripe three-piece suit, white shirt, navy tie,
dark hair swept back, clean jaw, restrained intensity, standing on the left. A woman in
her late twenties, black off-shoulder evening dress, dark hair in a low chignon, small
gold earrings, a thin pink beaded bracelet on her wrist, standing on the right, inches
away. They are in profile facing each other, eyes locked, not touching except her right
hand resting flat on his chest. Both faces sharp, skin texture visible, no glamour
retouching.

[③ SCENE & LIGHT]
Inside a warmly lit bar looking out onto a rainy street at night; raindrops and city
lights blurred into bokeh on the glass; a brass sconce behind the man throws a warm rim
light along his cheekbone; cold blue spill from the street fills the negative space above
their heads; faint reflections double their silhouettes on the wet glass.

[④ COMPOSITION & TYPOGRAPHY]
Vertical 3:4 poster. Chest-up two-shot, both faces occupying the middle two-thirds, the
upper third kept dark and empty for type. Typography — render this text exactly, correctly
spelled, no extra words:
- Top strip: three small caps labels in thin white sans, evenly spaced along the top edge:
  "PAREDO BENYIDON"  "DRAMA MEXICO CITY"  "ROSTAR PAUL WATER".
- Headline: "ME CASÉ CON UN MULTIMILLONARIO AMNÉSICO" in elegant high-contrast serif
  capitals, champagne-gold with bevel and soft shadow, centered in the upper third,
  broken into three balanced lines, wide tracking.
- Subtitle: "UNA HISTORIA DE AMOR Y MEMORIAS PERDIDAS" in cream serif, centered above the
  bottom edge.
- Bottom credits: one line of tiny condensed sans, low contrast, at the very bottom:
  "FICTIONAL DRAMA POSTER · UNA PRODUCCIÓN ORIGINAL".
Text stays inside the frame, never over faces.

[⑤ TECH]
Vertical 3:4, 1080x1440, photorealistic, natural skin, filmic color grade.
Negative: gibberish text, misspelled words, extra words, watermark, logo, signature,
duplicate faces, deformed hands, extra fingers, collage, split screen, frame border,
cartoon, 3d render, plastic skin, oversaturated.
```
