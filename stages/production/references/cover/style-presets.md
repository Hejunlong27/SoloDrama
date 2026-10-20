# 风格预设（AI 直出版 · 对应 `--style`）

> **真源声明（2026-10-20）**：本文件是仓库唯一真源；原技能副本已归档。
> **2026-10-20 改版**：执行方式从「PIL 排版引擎 + 暗罩参数」改为「AI 直出带字封面」。
> 因此每套预设不再给 `side/power/strength`，改为给**可直接抄进提示词的风格锚 + 光位 + 文字处理**。
> 引擎侧的 `cover_forge.py` 已降级为兜底工具（仅在 AI 反复拼错字、inpaint 修不好时使用）。

预设的价值在于**减少来回**：用户往往说不清「想要什么风格」，但能对「冷调还是暖调」「压迫感还是甜感」做出判断。
提问时（SKILL.md 第 0 步）**先给这张表让用户挑编号**，再让其补充自定义要求。

---

## 一览

| # | 名称 | `--style` 值 | 标题色 | 适用题材 | 情绪 |
|---|---|---|---|---|---|
| P1 | 复仇爽剧·冷调高级 | `revenge-cold` | 香槟金 `#E9C79C` | 复仇、豪门、马甲文、商战 | 克制、压迫、贵气 |
| P2 | 豪门甜宠·暖金 | `latam-mansion-gold` | 蜜金 `#FCD9A0` | 甜宠、契约婚、先婚后爱 | 温暖、亲近、明亮 |
| P3 | 暗黑悬疑·硬光 | `suspense-noir` | 冷白 `#F2F5F8` | 悬疑、犯罪、黑化 | 冷硬、不安、克制 |
| P4 | 奇幻血脉·夜紫 | `fantasy-violet` | 月白 `#E6E1FF` | 狼人、吸血鬼、西幻 | 神秘、异质、优雅 |
| P5 | 都市情感·清透 | `urban-clean` | 纯白 `#FFFFFF` | 都市情感、职场、治愈 | 清爽、克制、现代 |
| P6 | 古装权谋·鎏金 | `east-period-gold` | 鎏金 `#D4AF37` | 古装、宫斗、宅斗、年代 | 厚重、肃穆、东方 |

另有两条**题材专用**锚：`latam-rain-night`（拉美雨夜豪门，用户参考图即此类）、
`family-estate`（家族伦理/乡土）。

> 挑不出来时默认 **P1**：冷调不易过时，金红配色对「逆袭/复仇」母题适配度最高。

---

## P1 · 复仇爽剧·冷调高级（`revenge-cold`）

- **风格锚（直接抄）**：`High-end revenge drama key art, cold desaturated steel-blue grade with a single deep crimson accent, hard directional side light, tailored dark clothing, glossy corporate interior, restrained and oppressive, editorial photography`
- **光位短语**：`hard window side light, deep unlit background, one crimson practical as accent`
- **文字处理**：标题香槟金衬线大写 + `subtle bevel and soft shadow`；副标米白；顶条纯白细无衬线。
- **人物/服装**：深色定制西装、无袖礼服、极简珠宝；**不要**亮片、不要高饱和。
- **反例（写进 negative）**：`neon colors, explosion, comic style, tilted split layout`

## P2 · 豪门甜宠·暖金（`latam-mansion-gold`）

- **风格锚**：`Luxury drama key art, warm amber chandelier light, marble and dark wood interior, gold accents, rich shadows, editorial fashion photography, medium format look`
- **光位短语**：`warm chandelier key from above, soft fill, gentle falloff into shadow`
- **文字处理**：标题蜜金 + 描边更柔和（`soft glow, thin dark outline`）；整体对比略降，保留暖光。
- **人物/服装**：浅色礼服、真丝、珍珠；姿态可微侧带笑。
- **反例**：`cold blue grade, heavy black shadows`

## P3 · 暗黑悬疑·硬光（`suspense-noir`）

- **风格锚**：`Neo-noir thriller poster, single hard key light, deep blacks, wet asphalt reflections, smoke haze, anamorphic flare, muted palette`
- **光位短语**：`one hard key from the side, 90% of the frame in shadow, thin rim on the cheek`
- **文字处理**：标题冷白 + 细黑描边（暗底上不要用金色）；副标冷灰。
- **人物/服装**：风衣、暗色针织；表情克制、视线偏离。
- **反例**：`warm amber, cheerful smile, bright daylight`

## P4 · 奇幻血脉·夜紫（`fantasy-violet`）

- **风格锚**：`Dark fantasy key art, deep violet and midnight palette with pale moonlight rim, low fog, subtle supernatural glow, ornate textures, cinematic chiaroscuro`
- **光位短语**：`pale moonlight rim from behind, violet fill, fog catching the backlight`
- **文字处理**：标题月白 + 极细描边；可用 `slight metallic sheen`。
- **人物/服装**：皮革、刺绣、暗银饰；瞳色可异色但**不做发光眼**（会掉到廉价奇幻）。
- **反例**：`cartoon, glowing eyes, video game UI`

## P5 · 都市情感·清透（`urban-clean`）

- **风格锚**：`Contemporary urban romance poster, clean daylight, soft window light, muted teal and warm skin tones, minimal modern interior, airy negative space`
- **光位短语**：`soft window daylight, gentle fill, no harsh shadow`
- **文字处理**：标题纯白或深墨（看底明暗），**不加发光**；副标同色系。
- **人物/服装**：衬衫、针织、通勤装；场景要「真实可住人」。
- **反例**：`heavy vignette, dramatic chiaroscuro, fantasy elements`

## P6 · 古装权谋·鎏金（`east-period-gold`）

- **风格锚**：`Chinese period drama key art, deep vermilion and antique gold palette, candlelit interior, carved wood and silk textures, solemn symmetrical composition, painterly realism`
- **光位短语**：`candlelight from below-left, warm falloff, deep lacquer-dark background`
- **文字处理**：标题鎏金 + 细描边；字重偏粗（`heavy serif, engraved look`）。
- **人物/服装**：织锦、暗纹、发冠；姿态端正、对称。
- **反例**：`modern clothing, western architecture, anime style`

---

## 用法（两条通道都一样）

```bash
# 只看提示词
python stages/production/scripts/cover_prompt.py --brief cover_brief.json --style revenge-cold --print

# 本地 ComfyUI：生成清单 → 交给既有出图客户端
python stages/production/scripts/cover_prompt.py --brief cover_brief.json --style revenge-cold \
  --emit comfy --out-dir ./covers
python stages/assets/comfyui/comfy_client.py --spec ./covers/comfyui_manifest.json --out ./covers

# RunningHub 工作流：先生成计划，再按 probe 到的 nodeId 组装 nodeInfoList
python stages/production/scripts/cover_prompt.py --brief cover_brief.json --style revenge-cold \
  --emit rh --out-dir ./covers
```

> 预设只决定**风格与光位**；标题文案、断行、字数上限由 `prompt-guide.md §四` 与
> `cover_prompt.py --check` 管。两者冲突时以 `prompt-guide.md` 为准（它带验收标准）。
