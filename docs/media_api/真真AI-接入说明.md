# 真真AI（ZZAI）通道接入说明

> 落定时间：2026-11-13 ｜ 适用项目：`D:\剧本\海外剧\10`（《Cinco Años Después》）
> 本文只写**实测到的事实**，不写推测；每条都能用一条命令复现。

## 一、通道定位

| 环节 | 通道 id | 执行器 | 计费 |
|---|---|---|---|
| 资产卡（角色/场景/道具） | `image=zzai_image_api` | `stages/production/scripts/gen_assets_zzai.py` | 按张固定价 |
| 分镜图（构图锚） | `board=zzai_image_api` | `gen_boards.py --engine zzai`（支持四宫格） | 按张固定价 |
| 出片 | `video=zzai_video_api` | `stages/media_api/zzai_video.py` | 按秒 |

站点与鉴权：`https://api.seedance.nz`，`Authorization: Bearer <key>`。
Key 读取顺序（`stages/media_api/zzai.py`）：

1. 环境变量 `SEEDANCE_API_KEY` / `ZZAI_API_KEY`
2. `<工作区>/.secrets/zzai.key`
3. `<仓库>/configs/zzai.key`（`.gitignore` 已含 `*.key`）

## 二、模型与参数（实测）

### 2.1 图片 `zhenzhen-image-g-v2.6-lowprice`

| 项 | 值 |
|---|---|
| 接口 | `POST /v1/image/generations`、`/estimate`、`GET /v1/image/generations/{task_id}` |
| 1k 实测价 | **¥0.044 / 张**（`confidence=exact`，固定价） |
| 参考图 | `images` 数组，0–16 张（URL 形式，先 `POST /v1/files/upload`） |
| 输出 | `output_format=png`，`size` 用 `9:16` 这类裸比例 |
| 1k 9:16 实测尺寸 | **941 × 1672**（长边约 1672，非 1024 对齐） |

### 2.2 视频 `minimax-h3-comfyui-max`

| 项 | 值 |
|---|---|
| 接口 | `POST /v1/video/generations`、`/estimate`、`GET /v1/video/generations/{task_id}` |
| 计费 | **¥0.022313/秒**，线性；与分辨率无关（480p 与 1088p 同价） |
| 时长 | **必须是 3–15 的整数秒**（提交侧校验；estimate 对 2s/20s 也给报价，不可信） |
| 分辨率 | `1088p` 可用；`540p/720p/1080p/2k` 在 6 秒档被拒 |
| 参考图 | `images` 数组（与图片接口同名字段），实测会改变 estimate 的 `basis`：无图 `rate` → 有图 `quote` |
| 输出 | **1088 × 1920 / 24fps / h264**（实测 3 秒样片） |

**踩坑记录**

1. `duration` 在 estimate 与 submit 两侧口径不一致：estimate 2–20 秒都报价，submit 只收 3–15。
   第一次样片按 2 秒提交，返回 `400 invalid_parameter: Duration must be an integer from 3 to 15`。
2. 结果文件在 CDN（`xbuddy.si`）上**不支持流式读取**：`httpx` 的 `stream()` + `iter_bytes()`
   只拿到响应头就挂住，read 超时也不触发（实测卡 90 秒以上）。
   同 URL 普通 GET 正常（4.4s / 19s 都出现过，CDN 首次命中会慢）。
   → `ZZAIClient.download()` 已改为「整取 + 180s 宽超时 + 3 次重试」。
3. WorkBuddy / 编辑器里的子进程不会 `source ~/.bashrc`，注册表里的用户变量也要重开终端才生效 ——
   表现为「明明设过 Key 还报缺少 Key」。这就是加文件回落的原因。

## 三、四宫格分镜（成本优化）

一集 6 镜、全季 179 镜。逐镜出图 = 179 次请求（¥7.88）；四宫格 = **45 次**（¥1.98），省 75%。

规则（`gen_boards.py`）：

* 每 4 镜一次请求，画 2×2 联络表，格间细白缝；
* 画完在本地按四等分 + 2% 内缩切回 4 张单镜 PNG，**落点与逐镜模式完全相同**
  （`04-资产/boards/<ep>/<shot>.png`），下游无感；
* 拼版整图另存 `04-资产/boards/<ep>/_grid/<ep>_gridNN.png` 供人工复核；
* 尾巴 2–3 镜**不拼版**，退回单镜 —— 模板要求「不许留空格」，两格空着模型必然自己编；
* 四宫格请求只带**角色卡**，不带场景卡：4 个机位同时给 4 张场景卡，模型分不清哪张对应哪格。

**代价**：单格像素约为整图 1/4 边长。1k 竖版整图 941×1672 → 单格约 470×836。
1088×1920 出片会把它放大 ~2.3 倍。定位是「定构图/站位/光位」，身份细节由角色卡在出片时兜住。
需要更锐的分镜时：`--grid 1`（逐镜）或 `--resolution 2k`（四宫格但单格接近 1k）。

## 四、常用命令

```bash
WS="D:/剧本/海外剧/10"
P="$WS/pack"

# 0) 模型确认单（一次性）
python stages/production/scripts/drama.py models --workspace "$WS" \
  --set image=zzai_image_api board=zzai_image_api video=zzai_video_api

# 1) 资产卡：干跑报价 / 真出
python stages/production/scripts/gen_assets_zzai.py --workspace "$WS" --pack "$P"
python stages/production/scripts/gen_assets_zzai.py --workspace "$WS" --pack "$P" --yes --max-cost 0.06
#   或走统一入口：drama.py assets --engine zzai [--submit --max-cost 0.06]

# 2) 出完资产要重跑导入，回填 04-资产/refs.json 与 06-提示词/*/characters.json
python stages/import/pack_import.py --pack "$P" --workspace "$WS" --apply

# 3) 分镜图（四宫格来自 model-plan.json 的 board.detail.grid=4）
python stages/production/scripts/gen_boards.py --workspace "$WS" --ep ep01            # 干跑
python stages/production/scripts/gen_boards.py --workspace "$WS" --ep ep01 --apply --yes --max-cost 0.06

# 4) 出片（按集；1088p 来自 model-plan.json 的 video.detail.resolution）
python stages/media_api/zzai_video.py --workspace "$WS" --ep ep01                     # 干跑+报价
python stages/media_api/zzai_video.py --workspace "$WS" --ep ep01 --yes --max-cost 0.30
#   或走统一入口：drama.py video run --engine zzai --ep ep01 --yes --max-cost 0.30
```

## 五、成本口径（本项目实测价）

| 项 | 单价 | 数量 | 小计 |
|---|---|---|---|
| 资产卡 | ¥0.044/张 | 73 张 | ¥3.21 |
| 分镜图（四宫格） | ¥0.044/次 | 45 次（179 镜） | ¥1.98 |
| 分镜图（逐镜对照） | ¥0.044/张 | 179 张 | ¥7.88 |
| 出片 1088p | ¥0.0223/秒 | 约 1950 秒 | 约 ¥43.5 |

## 六、已知限制

* 视频模型不接受负向词 / seed / 首尾帧（接口没有这些字段）；
* 单镜 >15 秒必须拆镜，`zzai_video.py` 会直接报错而不是悄悄截断；
* 图片接口没有负向字段，资产卡的负向词以 `Do not include: …` 一句写进正向提示词；
* 四宫格的人物一致性靠角色卡 + 每格文字，仍可能出现「同一个人在四格里衣服不一致」，
  批量前务必先看第 1 组拼版图。

## 七、并行能力（2026-11-13 压测）

**能并行，而且能开到很高。** 服务端是异步任务队列：同时提交不会互相拒绝，但算力共享，
单条耗时会被拉长。用「3 秒镜 × N 条同时提交」测出的吞吐阶梯：

| 并发 | 总耗时 | 成功 | 吞吐（秒画面/秒） | 相对串行 |
|---|---|---|---|---|
| 1（串行） | 80s/条 | 1/1 | 0.038 | 1.0× |
| 3 | 148s | 3/3 | 0.061 | 1.6× |
| 6 | 136s | 6/6 | 0.132 | 3.5× |
| 12 | 149s | 12/12 | 0.242 | 6.4× |
| 20 | 148s | **19/20** | 0.384 | 10.1× |

**关键发现：并发 20 出现上限。** 第 17 条被上游直接拒：
`当前分组上游负载已饱和，请稍后再试`。这是**瞬时饱和**，不是参数错误、也不产生费用。

已据此在 `zzai_batch.run_one()` 加了「饱和退避重试」（4 次、指数退避），
所以 20 开也不会把镜判死，只是平均下来逼近平台上限。

**推荐值：12。** 理由：12 条时 12/12 全成功、吞吐已达串行 6.4 倍；
16 以上进入「偶发饱和 + 重试」区间，收益边际化（20 只比 12 快 1.6 倍，却开始有拒绝）。

按 12 并发估算全季（1950 秒画面）：

| 并发 | 预计时长 | 成本 |
|---|---|---|
| 1 | 约 14 小时 | ¥43.5 |
| 3 | 约 8.9 小时 | ¥43.5 |
| **12** | **约 2.2 小时** | ¥43.5 |
| 20 | 约 1.4 小时（含重试） | ¥43.5 |

成本与并发完全无关（按秒计费，不加价）。

```bash
python stages/media_api/zzai_video.py --workspace "$WS" --ep ep02 --yes --max-cost 0.35 --concurrency 12
# 整季：python stages/media_api/zzai_season.py --workspace "$WS" --stage video --eps ep02-ep30 \
#       --yes --max-cost 0.35 --concurrency 12
```

**注意**：以上阶梯用 3 秒短镜测，长镜（10–14 秒）单条更重，同一并发下吞吐会低一些，
但相对倍率应保持同阶。首集建议先用 `--concurrency 6` 跑 6 镜看稳定性，再放开 12。
