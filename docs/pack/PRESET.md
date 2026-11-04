# 项目预配置（PRESET）

> 预配置卡把「出图走哪条通道、出片用哪个工作流、并发多少、放大到多大」收成一份 JSON，
> 一条命令落到工作区，并**回读校验**。它解决的是一个具体事故：
> 确认单写着本地，实际跑的不是它 —— 账对不上时，已经出了几十张图。

## 〇、本分支只有一条通道

**出图、出片、放大全部在本机 ComfyUI，零平台费用、数据不出局域网、不需要任何平台 Key。**

## 一、当前可用的预配置

| ID | 出图 | 出片 | 并发 | 放大 |
|---|---|---|---|---|
| `local-comfyui-all` | 本地 ComfyUI · Qwen Image 2.1 turbo（￥0） | 本地 ComfyUI · Minimax H3 六参考槽（￥0） | 1 | 关闭（H3 输出已够，靠 crop-to-fill） |

```bash
# 看有哪些
python stages/import/preset_apply.py --list

# 干跑（只打印将要写什么）
python stages/import/preset_apply.py --preset local-comfyui-all --workspace "D:/剧/x"

# 真写（自动回读校验）
python stages/import/preset_apply.py --preset local-comfyui-all --workspace "D:/剧/x" --apply
```

等价 CLI：`drama pack preset --preset local-comfyui-all --apply`

> 并发固定 **1**：单卡 8G，出图和出片抢同一块显存，第二个任务进来就 OOM。
> 提速不能靠并发，只能靠「减少重跑」—— 所以「先小样后全量」这条规则必须守着。

## 二、落到哪三处

| 文件 | 写什么 | 谁读它 |
|---|---|---|
| `<ws>/model-plan.json` | `image=local_comfyui` / `video=local_comfyui` + 执行依据 | `model_gate.py`（首次出图/出片前的门禁） |
| `<ws>/video-pipeline/config.local.json` | `concurrency`（以及其他引擎覆盖键） | 本地出片客户端 |
| `<ws>/video-pipeline/config.upscale.json` | `backend=off` 或 `topaz`、`target={exact,1080,1920}` | `upscale.py` |

**为什么必须是三处而不是一处**：确认单管「走哪条路」，引擎覆盖层管「怎么跑」，放大配置管
「另一种任务」。合并成一个文件会让「改并发」和「换通道」互相牵连。

## 三、画风不在预配置里

画风由制作包的 `style_lock` 定义（见 `PACK-SPEC.md` §3.1）。预配置只管执行参数，
所以同一份预配置可以服务任何题材的剧 —— 甜宠、悬疑、出海西语，执行层是一样的。

## 四、时间才是这里的成本

零费用不等于零代价。一集 8 镜 × 6 秒 ≈ **2.5 小时**，其中出片占七成以上；30 集 ≈ **76 小时**。

两个必守的习惯：

- **先小样**：`drama video run --ep ep01 --limit 1 --yes`，确认一镜的样子再全量。跑错一整集是几十小时。
- **缺口靠重跑补，不靠改提示词**：退出码 3 表示「批次有缺口」（OOM / 队列被打断），
  同一条命令再跑一次即可；改提示词会让已有产物失效，等于从头再来。

系数第一次是经验值，跑过一次后用实测校准：

```bash
drama time plan --calibrate     # 用台账反推，写进 <ws>/time-model.json
drama time report --per-shot    # 逐镜看谁最慢
```

## 五、新增一份预配置

在 `configs/presets/` 放一个 JSON，字段照 `local-comfyui-all.json` 抄。
必填四项：`id`、`label`、`image.choice`、`video.choice`。

唯一需要小心的是 `video.concurrency`：它是单卡并发，写大了不会更快，只会 OOM。
`image.workflows.t2i` / `edit` 是仓库相对路径 —— 换工作流就换文件，不要在别处再抄一份节点映射
（节点映射的真源是同名 `.map.json`）。
