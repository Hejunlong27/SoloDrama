# BGM 与音频设计（配乐分工 · 库 · 铺排 · 混音）

- 版本：v1.0 ｜ 日期：2026-10-21
- 机器真源：`stages/production/scripts/bgm.py`（库/计划/门禁/混音）
- 相关：`convert_storyboard.py` 的 `[AUDIO]` 段（提示词侧禁配乐）、`subtitle.py` 的 `_try_bgm()`（S10 自动接）

---

## 一、结论先说：BGM 不交给视频模型，走「库 + 后期混音」

短剧的 BGM 有三个硬需求，生成模型现在都给不了：

| 需求 | 模型逐段生成的后果 |
|---|---|
| **贯穿整集、可循环** | 每段独立生成 ⇒ 段与段之间调性/节拍/混响不连续，拼起来像换了三首曲子 |
| **可换、可调、可证版权** | 生成的音频留在 mp4 里，换曲 = 重出片；平台 Content ID 误判时拿不出授权凭证 |
| **不能盖对白** | 模型不懂"说话时把音乐压下去"，短剧 80% 信息在对白里 |

所以分工写死：

```
画面 + 同期声（环境音/动作音/人声）  →  H3 负责（提示词里显式禁止配乐）
BGM（配乐）                          →  后期负责（bgm.py：库 → 计划 → 混音）
```

**为什么提示词里要专门禁配乐**：H3 是 video+audio 双模态，不写清楚它会自己垫一层含糊的音乐。
后果是「模型那层」+「后期那层」双重铺底 —— 相位抵消、音量忽大忽小，而且模型那层没法调、没法换、
没法证明版权。所以 `convert_storyboard.py` 默认给每条 H3 提示词追加：

```
[AUDIO] Diegetic sound only: room tone, footsteps, fabric rustle, doors, object handling,
muffled street noise through glass. NO background music, NO score, NO melody, NO drum loop,
NO stingers, NO musical bed of any kind — all music is added in post-production.
```

关掉它：`convert_storyboard.py --no-audio-direction`（不推荐；只有在你确定模型不出音频时才用）。

---

## 二、四层结构

```
① 提示词层   [AUDIO] 段：只允许同期声，禁配乐               convert_storyboard.py
② 库层       <ws>/04-资产/bgm/ + 引擎共享库，带版权字段     bgm.py library
③ 铺排层     情绪 → 增益/淡入淡出/时间线 → <ep>_bgm-plan.json   bgm.py plan
④ 混音层     母版 + BGM → <ep>_mix.mp4（视频直通，只重编码音频） bgm.py mix
             ↑ subtitle.py 在 S10 烧字幕前自动调用 ④
```

### 2.1 库层：两个位置，项目库优先

| 位置 | 用途 | 是否进 git |
|---|---|---|
| `<ws>/04-资产/bgm/` | 本剧专用素材 | 工作区，不进仓库 |
| `<引擎仓库>/stages/production/assets/bgm/` | 跨剧复用 | **只进清单**，音频文件不进（见该目录 README） |

清单 `bgm-library.json` 的字段、情绪标签表、版权纪律见
`stages/production/assets/bgm/README.md`（含 `bgm-library.example.json` 模板）。

**库里已预置 12 首**（2026-10-21）：来自 Wikimedia Commons，全部 CC BY 3.0/4.0，
按 6 类情绪各 2 首。**音频文件不在仓库里**（见 `.gitignore`），换台机器用
`python stages/production/scripts/fetch_bgm.py --apply` 重新抓一遍即可（同一套检索与过滤口径）。

**想自己用 AI 生成配乐**（MiniMax / Suno / Udio）：直接抄 `docs/production/BGM生成提示词.md` 里的
12 条提示词（6 情绪 × 主用/变体）。那里写清了六条硬约束（无人声、无旋律主线、无突袭音效、
无前奏无 drop、可无缝循环、中低音量铺底）——**不按这六条生成的作品混不进对白**。

### 2.2 铺排层：情绪 → 计划

```powershell
# 看库（--scan 用 ffprobe 补时长，BPM 必须人工填）
python stages/production/scripts/drama.py --workspace "<ws>" bgm library --scan

# 生成某集计划（默认整集一首、可循环、开 ducking）
python stages/production/scripts/drama.py --workspace "<ws>" bgm plan --ep ep01 --apply
```

`plan` 的取值逻辑：

| 输入 | 来源 | 说明 |
|---|---|---|
| 成片时长 | 优先 ffprobe `_master_2k.mp4`，否则 `h3_prompts.json` 的 `duration` 求和 | 决定段的时间线终点 |
| 情绪 | `--mood`，缺省从 `blueprint.json` 的题材推断 | `tension / suspense / revenge / warm / sad / epic` |
| 增益 / 淡入淡出 | 情绪默认表（见库 README） | 短剧口径：BGM 常年在 **-22 dB** 附近 |
| 声音归属 | `project-setup.json` 的 `video_options.voice` | `voice=h3` 时 ducking **必须开** |

计划文件：`<ws>/07-成片/subs/<ep>/<ep>_bgm-plan.json`（可手工改：换曲、加段、调增益）。

> **一条剧不要连续两集用同一首**（平台可能判相似内容降流）。`plan` 会打印最近三集用过的曲目。

### 2.3 混音层：ffmpeg 怎么做

`bgm.py mix` 构建一条 `filter_complex`（视频流 `-c:v copy`，只重编码音频）：

```
[1:a] atrim=0:<dur> → asetpts → volume=<gain>dB → afade in/out → adelay=<start> → apad  [b1]
[0:a] asplit=2 → [vo] / [sc]
[b1][sc] sidechaincompress=threshold:ratio:attack:release → [bd]
[vo][bd] amix=inputs=2:duration=first:normalize=0 → [aout]
-map 0:v:0 -map [aout] -c:v copy -c:a aac -b:a 192k
```

三个要点：

1. **`sidechaincompress` = ducking**：以主音轨（人声）为侧链，说话时自动把 BGM 压下去，
   说完再抬起来。这是"BGM 不盖对白"的唯一可靠做法（手动调音量做不到跟着对白走）。
2. **`-stream_loop -1`**：曲目短于时段时自动循环（`loop: true` 的曲目才加）。
3. **`-c:v copy`**：视频流不重编码，8 秒片段混音耗时约 0.2 秒，整集 60 秒不到 2 秒。

默认参数（`plan` 写进计划，可改）：

| 参数 | 默认 | 调法 |
|---|---|---|
| `gain_db` | -22（按情绪浮动 -19 ~ -24） | 听感偏小 → 提到 -18；偏大盖人声 → 降到 -26 |
| `ducking.threshold` | 0.05（≈ -26 dBFS） | BGM 被压得太狠 → 提高到 0.12；几乎不压 → 降到 0.03 |
| `ducking.ratio` | 6 | 想要"说话时几乎没音乐" → 10~12 |
| `ducking.release` | 350 ms | 句间恢复太慢（拖泥带水）→ 200~250 |
| `fade_in/out` | 1.5 / 2.5 s | 集尾要"收干净" → `fade_out` 提到 4 |

---

## 三、接到流程里（S10）

11 环节不变，**S10 从「字幕烧录」扩为「音频与字幕」**：

```
S9 视频放大 → S10 音频与字幕（BGM 混音 + 字幕烧录）→ S11 定稿输出
```

`subtitle.py --stage render` 会：

1. 找 `<ep>_bgm-plan.json`；
2. 混出 `<ep>_mix.mp4`（视频直通，只重编码音频）；
3. 用 `_mix.mp4` 当底片烧字幕。

三条自动降级（任一不满足就按"无 BGM"继续，**不阻塞交片**）：

- 没有计划文件 → 直接烧字幕；
- 已经有 `_mix.mp4` 且比底片新 → 复用（不重复混）；
- 当前环境没有 `bgm.py`（脚本被单独拷进 Skill 包时）→ 打印手动命令后继续。

关闭：`subtitle.py ... --no-bgm`。

---

## 四、版权与发行（这块会被平台抽查）

1. **清单里必须有 `license`**：`owned` / `licensed` / `cc0` / `generated`。
   缺了或非法 → `bgm.py check` **退出码 2**，不许混。
2. **`generated`（AI 生成）必须写 `license_note`**：多数平台对"生成物可商用"有附加条件
   （能否再分发、是否需署名）。这条是 `release_check` 之前的人工审核项，别用"反正是我生成的"糊过去。
3. **`source` 要能对上凭证**：订单号 / 授权书文件名 / 生成平台账号。发行资料里的
   「版权资料」四张截图，BGM 授权凭证要一并留档。
4. **曲目一旦进成片，换曲要重混**（`bgm.py mix --apply`），不要手工剪音频 ——
   手工剪会让字幕与音频时长脱节。
5. **CC BY 必须署名**（库里预置的 12 首都是 CC BY）：

   ```powershell
   python stages/production/scripts/drama.py --workspace "<ws>" bgm credits --ep ep01
   ```

   输出可直接粘进发布文案：`Music: Kevin MacLeod — “Ossuary 6 - Air”（CC BY 3.0，via Wikimedia Commons）`。
   **发行资料的文案槽位必须带上这段**；`bgm.py check` 只校验授权字段齐全，
   署名有没有真的写进文案仍是人工项（`release_check` 目前不查这一条）。

---

## 五、常见问题

**Q：混完听着 BGM 忽大忽小？**
A：那是 ducking 在跟着对白走，正常。嫌明显就把 `release` 降到 200ms、`ratio` 降到 4。

**Q：BGM 完全听不见？**
A：先看 `gain_db`（是否低于 -28），再看曲目本身是不是有 10 秒静音前奏 ——
`bgm.py plan` 不会跳过前奏，必要时在计划里给 `start` 加偏移，或把曲目重新裁一个 intro 干净的版本。

**Q：不想整集一首，想在 hook 段换曲？**
A：`plan --segments 3` 会等分成三段（同一首的不同起点），再手工把第 3 段 `track` 改成另一首，
然后 `check` + `mix`。

**Q：H3 那条音轨本来就有音乐怎么办？**
A：说明提示词没加 `[AUDIO]` 段（或用了 `--no-audio-direction`）。重跑 `convert_storyboard --apply`
把约束补上，再重出那几段。已经出过片的集，可以把那段音频整体拉低 6 dB 凑合，但不建议交付。

**Q：短剧真的需要 BGM 吗？**
A：需要。同类短剧的留存曲线在"静音段"掉得最快；配乐不是装饰，是节奏的一部分 ——
但**它必须让位于对白**，这就是 ducking 存在的理由。
