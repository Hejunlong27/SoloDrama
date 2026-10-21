# BGM 共享库（跨剧复用）

> 真源与工具：`stages/production/scripts/bgm.py`；设计说明见 `docs/production/BGM与音频设计.md`。

这个目录放**可以跨剧复用**的配乐素材。项目专用素材放 `<工作区>/04-资产/bgm/`（项目库）。
解析顺序：**项目库优先**，同名 `id` 覆盖共享库。

## 当前库里有什么（2026-10-21 预置 12 首）

全部来自 **Wikimedia Commons**，授权均为 **CC BY 3.0 / 4.0**：可商用，**但必须署名**。
按情绪各 2 首，覆盖 6 类：

| id | 情绪 | 曲目 | 作者 | 时长 | 授权 |
|---|---|---|---|---|---|
| `tension_01_ossuary_6_air` | tension | Ossuary 6 - Air | Kevin MacLeod | 250s | CC BY 3.0 |
| `tension_02_impending_boom` | tension | Impending Boom | Kevin MacLeod | 157s | CC BY 3.0 |
| `suspense_01_passing_action` | suspense | Passing Action | Kevin MacLeod | 50s | CC BY 3.0 |
| `suspense_02_rafael_krux_lights_creep` | suspense | Lights - Creepy Ambient Suspense | Rafael Krux | 132s | CC BY 4.0 |
| `revenge_01_scott_buckley_crusader` | revenge | Crusader | Scott Buckley | 77s | CC BY 4.0 |
| `revenge_02_ghost_dance_macleod_kevi` | revenge | Ghost Dance | Kevin MacLeod | 73s | CC BY 3.0 |
| `warm_01_scott_buckley_sleep_pian` | warm | Sleep (piano-only mix) | Scott Buckley | 184s | CC BY 4.0 |
| `warm_02_scott_buckley_interventi` | warm | Intervention | Scott Buckley | 258s | CC BY 4.0 |
| `sad_01_touching_moments_two_hig` | sad | Touching Moments Two - Higher | Kevin MacLeod | 174s | CC BY 3.0 |
| `sad_02_touching_moments_four_me` | sad | Touching Moments Four - Melody | Kevin MacLeod | 109s | CC BY 3.0 |
| `epic_01_dramatic_trailer_by_rafa` | epic | Dramatic Trailer | Rafael Krux | 98s | CC BY 4.0 |
| `epic_02_rafael_krux_uplifting_bl` | epic | Uplifting Blockbuster | Rafael Krux | 136s | CC BY 4.0 |

**`bpm` 全部为空**——必须人工听着填（剪接点对齐要用），工具不猜。

### 另有 6 首 AI 生成（2026-10-21 由用户用 AI 音乐平台生成）

| id | 情绪 | 曲目 | 时长 | 实测响度 | 增益 | 可循环 |
|---|---|---|---|---|---|---|
| `tension_11_quiet_tension` | tension | Quiet Tension | 116s | -19.5 LUFS | -13.5 dB | **是**（首尾电平一致） |
| `suspense_11_subtle_pressure` | suspense | Subtle Pressure | 88s | -27.2 LUFS | -6.8 dB | 否（尾部淡出） |
| `suspense_12_silence` | suspense | Silence | 193s | -25.1 LUFS | -8.9 dB | 否（弱起弱收） |
| `revenge_11_steady_fury` | revenge | Steady Fury | 149s | -14.7 LUFS | -16.3 dB | 否（尾部淡出） |
| `warm_11_tender_reunion` | warm | Tender Reunion | 176s | -17.4 LUFS | -14.6 dB | 否（尾部淡出） |
| `sad_11_no_words` | sad | No Words | 138s | -13.7 LUFS | -21.3 dB | 否（尾部淡出） |

⚠️ **待补**：这 6 首的 `license_note` 目前只写「AI 生成，平台与商用条款待补」——
发行前必须补上 **平台名 + 授权截图**（`license=generated` 的合规要求）。
另外它们的 `bpm` 也还没填。

> 注意这 6 首的响度跨了 13.5 dB（-13.7 ~ -27.2）。所以清单里记 `loudness_lufs`、
> 增益按实测反推 —— **不要给所有曲子套同一个 -22 dB**，否则有的震耳朵、有的听不见。
> 详见 `docs/production/BGM与音频设计.md` §2.3。

### 换台机器怎么把音频拿回来

清单在仓库里、音频不在，所以 clone 下来库是「有目录无曲目」。两种办法：

```powershell
# A. 按清单重新抓一遍（同一批曲子，脚本已内置检索与过滤规则）
python stages/production/scripts/fetch_bgm.py --apply

# B. 自己准备素材：把音频放进本目录，再 library --scan 补时长
python stages/production/scripts/bgm.py --workspace "<ws>" library --scan
```

`fetch_bgm.py` 就是你手上这套选曲口径的可执行版本：只要 `CC0/PD/CC BY`（排除 `BY-SA` 传染性、
`NC` 不可商用、`ND` 不能混音改编）、排除访谈/讲座录音、排除西部/凯尔特/中世纪/爵士等
「会把观众拉出剧情」的风格、时长卡 40–300 秒。

### 署名怎么做（CC BY 的硬要求）

```powershell
python stages/production/scripts/bgm.py --workspace "<ws>" credits --ep ep01
```

输出可直接粘进发布文案：

```
Music: Kevin MacLeod — “Ossuary 6 - Air”（CC BY 3.0，via Wikimedia Commons）
```

**发行资料里的文案槽位必须带上这段**，否则 CC BY 的署名义务没履行 —— 这是可被追溯的合规问题。
`bgm.py check` 只校验「授权字段齐全」，署名是否真的出现在文案里仍是**人工审核项**。

## 为什么音频文件不进 git

- 单个 mp3 通常 2–8 MB，30 首就上百 MB，会把仓库撑爆（`--max-mb` 默认 90 MB 直接拒推）。
- 商用授权凭证通常不允许随开源仓库再分发。

所以仓库里**只提交清单** `bgm-library.json`（曲目元数据），音频文件由使用者自己下载/购买后放进本目录。
清单里的 `file` 只写文件名，工具会自动在本目录（或项目库）里找。

## 建库三步

```powershell
# 1) 把音频放进本目录（或 <ws>/04-资产/bgm/）
# 2) 复制模板并改成本地清单
Copy-Item bgm-library.example.json bgm-library.json
# 3) 用 ffprobe 自动补时长（BPM 需要人工听/查，工具不猜）
python stages/production/scripts/bgm.py --workspace "<ws>" library --scan
```

然后用 `bgm.py plan --ep ep01 --mood tension --apply` 生成铺排计划。

## 清单字段（全部必填，`check` 会拦）

| 字段 | 说明 |
|---|---|
| `id` | 唯一标识，建议 `情绪_序号`，如 `tension_low_01` |
| `file` | 文件名（相对本目录或项目库根） |
| `moods` | 情绪标签数组，见下表；留空 = 任何情绪都可选 |
| `bpm` | 节拍数。**必须人工填**（剪接点对齐用），工具不猜 |
| `duration` | 秒；可留空后由 `library --scan` 补 |
| `loop` | 是否可无缝循环（决定混音时是否 `-stream_loop -1`） |
| `license` | `owned`（自有）/ `licensed`（已购买授权）/ `cc0`（公有领域）/ `generated`（AI 生成） |
| `source` | 出处与凭证位置。发行时平台可能抽查，必须可追溯 |
| `license_note` | 商用条款摘要。**`generated` 必填**（平台审核与 Content ID 争议都要用） |
| `gain_db` | 建议铺底增益（-30 ~ -6）。短剧常用 -22。**写了就以它为准**（不同曲目母带响度差很多，-14 LUFS 的曲子要压得比 -20 LUFS 的多），留空才走情绪默认表 |

## 情绪标签（与 `bgm.py` 的默认增益联动）

| 标签 | 用途 | 默认增益 | 默认淡入/淡出 |
|---|---|---|---|
| `tension` | 对峙、压力段 | -22 dB | 1.5 / 2.5 s |
| `suspense` | 悬疑、信息差 | -23 dB | 1.2 / 2.2 s |
| `revenge` | 逆袭、打脸前夜 | -20 dB | 0.8 / 2.0 s |
| `warm` | 家庭、情感落点 | -21 dB | 1.5 / 2.5 s |
| `sad` | 失去、告别 | -24 dB | 2.0 / 3.0 s |
| `epic` | 终章、格局升级 | -19 dB | 1.0 / 2.5 s |

## 版权纪律（发行前的硬要求）

1. **`license` 与 `source` 必须能对上凭证**（订单号 / 授权书文件名 / 生成平台账号）。
2. **AI 生成音乐要单独看条款**：多数平台对「生成物的商用权」有附加条件（是否可再分发、
   是否需署名）。写进 `license_note`，不要用「反正是我生成的」糊过去。
3. **同一首曲不要在相邻两集连续使用**（平台可能判相似内容降流）；`bgm.py plan` 会打印
   最近三集用过的曲目，供人工避开。
4. 曲目一旦进入某集成片，**换曲要重混**（`bgm.py mix --apply`），不要手工剪音频。
