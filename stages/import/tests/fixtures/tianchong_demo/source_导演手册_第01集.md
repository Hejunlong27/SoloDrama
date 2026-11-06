# 亿万丈夫的三个月合约（第01集 · 导演手册节选）

> 本文件模拟创作 Skill（`tianchong-manju` 总裁甜宠）的产出格式，只保留转换所需的部分：
> 时间轴总表 + 每镜 A 段（分镜图提示词）与 B 段（视频提示词）。
> 转换结果见同目录 `pack/`；转换规则见 `docs/pack/IMPORT-PROMPT.md`。

## 时间轴总表

| 镜号 | 镜头名 | 时间 | 时长 | 场景 | 生成方式 | 口型镜 | 首帧 |
|---|---|---|---|---|---|---|---|
| 1 | 递交合约 | 0:00–0:06 | 6s | S01 | 图生视频 | 是 | shot_001 |
| 2 | 抬头 | 0:06–0:12 | 6s | S01 | 图生视频 | 是 | shot_002 |
| 3 | 落地窗空镜 | 0:12–0:16 | 4s | S01 | 图生视频 | 否 | shot_003 |

合计 16 秒。

## 第1镜 递交合约

参考：STYLE01｜何暖 LOOK-A｜靳衍 LOOK-A｜S01 空景卡｜D01 合约

**A段：分镜图提示词**

```
参考：STYLE01｜何暖 LOOK-A｜靳衍 LOOK-A｜S01 空景卡｜D01 合约
画面：办公室。何暖在画左站着，手拿合约，面朝画右；靳衍在画右坐在办公桌后，抬头看她，面朝画左。表情：倔强。
机位：50mm，办公室东侧略低，双人中景，两人各占画面三分之一。
光线：落地窗的午后暖光从画右照来，桌角一盏钨丝灯补出暖橙轮廓。
风格：美式复古影视风格，胶片颗粒，年代色偏，自然窗光与钨丝灯，轻微褪色，9:16竖构图，无文字，无水印
```


```
subject_definitions:
<Picture 1> 是本镜分镜图（首帧构图锚点）：长桌两侧的中景，何暖居左、靳衍居右。
<Subject 1> 是 <Picture 2> 中的何暖：二十五六岁，齐肩卷发，墨绿丝绒连衣裙。
<Subject 2> 是 <Picture 3> 中的靳衍：三十出头，深棕格纹西装，领口松开一颗扣。
<Subject 3> 是 <Picture 4> 中的办公室：深色胡桃木桌、墨绿丝绒窗帘、午后斜光。
<Subject 4> 是 <Picture 5> 中的合约：米白纸本，封面一枚火漆印。

summary:
[reference generation] 目标视频呈现 <Subject 1> 把 <Subject 4> 推给 <Subject 2> 的一拍，以及 <Subject 2> 抬眼敲桌的回应，参考图提供两人形象、<Subject 3> 的空间与合约外观。

retention_analysis:
<Subject 1>（出现于 [Shot 1]）：fully_preserved - 保留齐肩卷发与墨绿丝绒裙。
<Subject 2>（出现于 [Shot 2]）：fully_preserved - 保留格纹西装与松开的领口。
<Subject 3>（出现于 [Shot 1]、[Shot 2]）：fully_preserved - 保留胡桃木桌、丝绒窗帘与斜光方向。
<Subject 4>（出现于 [Shot 1]）：fully_preserved - 保留米白纸本与火漆印。
<Picture 1>（[Shot 1] 首帧）：partially_preserved - 保留机位与左右站位。

detailed_description:
美式复古影视质感，胶片颗粒，褪色绿与钨丝灯橙，午后窗光轻微过曝。
[Shot 1] 中景，<Subject 1> 把 <Subject 4> 推到 <Subject 2> 面前，说：<d>[Chinese] 一年，互不干涉。</d>
[Shot 2] At 00:03.000，镜头缓推到两人之间，<Subject 2> 抬眼，指尖在桌面轻敲两下，说：<d>[Chinese] 三个月。</d>

overall_soundscape:
纸张落桌声，指节敲桌的两声，室外远处车流。

non_diegetic_music:
N/A
```

## 第2镜 抬头

参考：何暖 LOOK-A｜S01 空景卡

**A段：分镜图提示词**

```
参考：何暖 LOOK-A｜S01 空景卡
画面：何暖站在办公桌前，画右三分之一，低头看合约，手指停在签名栏。表情：犹豫。
机位：85mm，平视，中近景，背景是虚化的落地窗。
光线：午后的窗光从画右后方打来，脸侧留一道暖边。
风格：美式复古影视风格，胶片颗粒，年代色偏，自然窗光与钨丝灯，轻微褪色，9:16竖构图，无文字，无水印
```


```
subject_definitions:
<Picture 1> 是本镜分镜图（首帧构图锚点）：中近景，何暖低头看合约。
<Subject 1> 是 <Picture 2> 中的何暖：二十五六岁，齐肩卷发，墨绿丝绒连衣裙。
<Subject 2> 是 <Picture 3> 中的办公室：胡桃木桌边缘与墨绿丝绒窗帘。

summary:
[reference generation] 目标视频呈现 <Subject 1> 在 <Subject 2> 前低头看合约、抬眼开口的两拍。

retention_analysis:
<Subject 1>（出现于 [Shot 1]、[Shot 2]）：fully_preserved - 保留卷发、丝绒裙与面部。
<Subject 2>（出现于 [Shot 1]、[Shot 2]）：fully_preserved - 保留桌沿与窗帘的材质与色温。
<Picture 1>（[Shot 1] 首帧）：partially_preserved - 保留中近景机位。

detailed_description:
美式复古影视质感，胶片颗粒，褪色绿与钨丝灯橙，午后窗光轻微过曝。
[Shot 1] 中近景，<Subject 1> 低头看合约，睫毛轻颤，没有说话；镜头极缓推近。
[Shot 2] At 00:03.000，<Subject 1> 抬眼看向画右，嘴唇轻启，说：<d>[Chinese] 我签。</d>

overall_soundscape:
纸张摩擦声，笔尖落纸的一声轻响。

non_diegetic_music:
N/A
```

## 第3镜 落地窗空镜

参考：S01 空景卡

**A段：分镜图提示词**

```
参考：S01 空景卡
画面：空镜。办公室落地窗，百叶半开，午后光带斜切过地毯，办公桌一角入画。
机位：35mm，略低，广角，无人物。
光线：午后的光带从画右扫到画左，暖橙偏黄。
风格：美式复古影视风格，胶片颗粒，年代色偏，自然窗光与钨丝灯，轻微褪色，9:16竖构图，无文字，无水印
```


```
subject_definitions:
<Picture 1> 是本镜分镜图（首帧构图锚点）：空镜，办公室无人。
<Subject 1> 是 <Picture 2> 中的办公室：胡桃木桌、墨绿丝绒窗帘、午后斜光。

summary:
[reference generation] 目标视频是 <Subject 1> 的空镜，一道暖色反光缓慢移过桌面。

retention_analysis:
<Subject 1>（出现于 [Shot 1]）：fully_preserved - 保留桌面、窗帘与斜光方向。
<Picture 1>（[Shot 1] 首帧）：fully_preserved - 保留空镜构图。

detailed_description:
美式复古影视质感，胶片颗粒，褪色绿与钨丝灯橙。
[Shot 1] 空镜，一道暖色反光穿过窗帘落上桌面并缓慢移动，尘埃在光里浮动；无人入画。

overall_soundscape:
远处城市底噪，空调低鸣。

non_diegetic_music:
N/A
```
