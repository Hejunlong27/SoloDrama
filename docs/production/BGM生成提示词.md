# BGM 生成提示词（给 AI 音乐平台用）

- 版本：v1.0 ｜ 日期：2026-10-21
- 配套：`docs/production/BGM与音频设计.md`（分工与混音）、`stages/production/scripts/bgm.py`（入库与门禁）
- 用途：在 MiniMax / Suno / Udio 等平台生成**短剧铺底配乐**，成品放进 BGM 库

---

## 零、写这些提示词的六条约束（先看，不然生成出来用不上）

短剧的 BGM 是**对白的背景**，不是主角。六条硬约束直接来自混音环节的需要：

| # | 约束 | 不这么写会怎样 |
|---|---|---|
| 1 | **纯音乐、无人声**（不含哼唱/vocal chops/chops 和声） | 人声垫底与对白撞频，混音压不下去，只能丢 |
| 2 | **不要旋律主线**（no melody hook / no lead melody） | 观众记住的是曲子不是剧情；而且旋律会与台词抢注意力 |
| 3 | **不要突袭音效**（no sudden hits / no stingers / no risers） | 与剪辑点、反转点打架，ducking 也压不干净 |
| 4 | **无独立前奏、无 build-drop**（no intro / no drop / through-composed） | 一集 60 秒，前奏 8 秒等于白铺；build-drop 会强迫你改剪辑节奏 |
| 5 | **可无缝循环**（seamless loop / consistent energy / ends where it begins） | 短剧集数多，每集都要重新对时常，循环省一半事 |
| 6 | **中低音量铺底**（underscore / sits under dialogue / not upfront） | 生成得越"燃"，后期压得越狠，最后听着闷 |

> **技巧**：同一提示词生成 3–4 个 take，**挑最"无聊"的那个**。铺底音乐越不抢戏越好用。

---

## 一、参数（生成时按这个填）

| 项 | 取值 | 理由 |
|---|---|---|
| 时长 | **90–120 秒**（平台上限内尽量长） | 一集 60 秒，长一点方便按段落取用；短于 60 秒要无缝循环 |
| 调性 | **小调为主**（Dm / Am / Em） | 短剧基调偏压迫与悬念；warm 类用大调 |
| 速度 | 60–120 BPM（见下表） | 慢速铺底不干扰语速；快曲会催观众跳戏 |
| 歌词 | 空 / `[Instrumental]` | 千万别留空让平台自由发挥，有些模型会自动补 vocal |
| 输出 | **wav 或 mp3 原始文件** | 不要自己压/剪/加淡入淡出，混音时统一处理 |

---

## 二、六类情绪 × 两条（主用 + 变体）

### 1. `tension` —— 对峙、压迫（最常用）

**主用**（70 BPM · D 小调）
```
cinematic dark tension underscore, slow pulsing low strings, deep sub bass drone,
sparse single piano notes with long decay, faint ticking texture, minor key,
70 BPM, no lead melody, no vocals, no sudden hits, no intro, consistent energy,
seamless loop, background score that sits under dialogue, not upfront
```

**变体**（更沉更空，适合长时间对峙）
```
minimal dark ambient underscore, sustained cello low drone, distant piano notes,
almost no percussion, very slow 58 BPM, D minor, through-composed, no melody,
no vocals, no risers, no accents, flat dynamic, loopable bed for tense dialogue
```

### 2. `suspense` —— 悬疑、信息差

**主用**（60 BPM · A 小调）
```
subtle suspense underscore, high harmonic shimmer pad, slow heartbeat-like low pulse,
isolated high piano notes, airy reverb, 60 BPM, A minor, no melody hook, no vocals,
no sharp hits, no build-drop, steady quiet tension, seamless loop for mystery scenes
```

**变体**（带轻微机械质感，适合取证/翻查线索）
```
investigative ambient suspense, muted metallic texture, low synth pulse, ticking clock
texture in distance, sparse pizzicato strings, 66 BPM, A minor, restrained, no vocals,
no melody, no stinger hits, continuous background bed under dialogue
```

### 3. `revenge` —— 逆袭、打脸前夜（唯一允许"有劲"的一类）

**主用**（100 BPM · E 小调）
```
determined dark cinematic underscore, staccato string ostinato, restrained low brass,
soft taiko-like hits on the beat, rising low ostinato bass, E minor, 100 BPM,
confident and controlled anger, no lead melody, no vocals, no big drop,
no sudden stingers, steady drive, loopable bed for confrontation scenes
```

**变体**（现代都市感，合成器低音）
```
modern urban revenge underscore, pulsing analog synth bass, tight staccato strings,
muted percussion, sparse piano stabs, 96 BPM, E minor, cool and determined,
no vocals, no melody hook, no risers, flat relentless groove under dialogue
```

### 4. `warm` —— 家庭、情感落点

**主用**（72 BPM · F 大调）
```
warm intimate underscore, soft felt piano arpeggio, gentle string pad underneath,
light acoustic guitar fingerpicking, 72 BPM, F major, tender and unhurried,
no lead melody, no vocals, no percussion hits, consistent gentle energy,
seamless loop for family and reconciliation scenes
```

**变体**（纯钢琴，最不抢戏）
```
solo felt piano underscore, slow sparse chords, long pedal sustain, slight room reverb,
68 BPM, F major, melancholic warmth, no melody line, no vocals, no other instruments,
flat gentle dynamic, loopable background for emotional dialogue
```

### 5. `sad` —— 失去、告别

**主用**（60 BPM · A 小调）
```
sombre minimal underscore, single piano notes with long tail, sustained cello line,
very soft string texture, 60 BPM, A minor, restrained grief, no lead melody,
no vocals, no percussion, no climax, even and quiet, seamless loop for farewell scenes
```

**变体**（更空，适合长镜头/独白）
```
empty melancholic ambient, lone piano note per bar, distant low string drone,
almost silent texture with room tone, 54 BPM, A minor, through-composed,
no melody, no vocals, no dynamic change, loopable quiet bed
```

### 6. `epic` —— 终章、格局升级

**主用**（110 BPM · D 小调）
```
epic cinematic underscore, layered strings with restrained brass swells,
steady low percussion, subtle choir-like string pad (wordless, strings only),
D minor, 110 BPM, dignified and rising, no lead melody, no vocals, no big drop,
no sudden stingers, sustained momentum, loopable bed for climax scenes
```

**变体**（纯弦乐，避免太满）
```
strings-only epic underscore, ostinato violins, broad legato cello lines,
no brass no percussion, 104 BPM, D minor, restrained grandeur, no vocals,
no melody hook, flat build, continuous energy, loopable background
```

---

## 三、生成后怎么交给我（照这个来，我就能直接入库）

1. **原始文件直接发**：wav / mp3 都行，**不要**压码率、不要剪、不要加淡入淡出、不要做响度统一。
2. **每首告诉我**：对应哪个情绪（tension / suspense / …）、平台显示时长、用的账号（或套餐名）。
3. **一张截图或链接**：平台的**商用授权条款**（这是 `license=generated` 必填 `license_note` 的依据，
   发行阶段平台抽查时要拿得出）。
4. 自己先听一遍，**明显有旋律记忆点、有人声哼唱的，别发** —— 那类东西混不进对白。
5. 命名不用管，我按 `<情绪>_<序号>_<曲子特征>` 统一改。

我收到后会做：`ffprobe` 读时长 → 写进 `bgm-library.json`（`license=generated` + `license_note`
写清平台与条款）→ `bgm.py check` 过门禁 → 在你的剧上试铺一集给你听。

---

## 四、如果平台只支持「描述一段音乐」而没有参数

把上面对应那条的英文整段粘进去即可，它已经包含风格、情绪、乐器、速度、调性与结构约束。
若平台有单独的「排除」或「negative」框，填：

```
vocals, vocal chops, humming, lead melody, catchy hook, sudden hit, stinger,
riser, build-drop, intro, ending cadence, loud drums, distorted guitar
```

若平台能填「时长」，填 90 秒；不能填就生成后取最长的那个 take。
