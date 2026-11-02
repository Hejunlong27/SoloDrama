# 项目预配置（PRESET）

> 预配置卡把「出图走哪条通道、出片用哪个工作流、并发多少、放大到多大」收成一份 JSON，
> 一条命令落到工作区，并**回读校验**。它解决的是一个具体事故：
> 确认单写着本地，实际跑的是云端 —— 账对不上时，已经出了几十张图。

## 一、当前可用的预配置

| ID | 出图 | 出片 | 并发 | 放大 |
|---|---|---|---|---|
| `local-comfyui-rh` | 本地 ComfyUI · Qwen Image 2.1 turbo（￥0） | RunningHub 工作流 `2113319585146560513`（8 步 / 0.8MP） | 5 | RunningHub `2100177270433476609` → 1080×1920 |

```bash
# 看有哪些
python stages/import/preset_apply.py --list

# 干跑（只打印将要写什么）
python stages/import/preset_apply.py --preset local-comfyui-rh --workspace "D:/剧/x"

# 真写（自动回读校验）
python stages/import/preset_apply.py --preset local-comfyui-rh --workspace "D:/剧/x" --apply
```

等价 CLI：`drama pack preset --preset local-comfyui-rh --apply`

## 二、落到哪三处

| 文件 | 写什么 | 谁读它 |
|---|---|---|
| `<ws>/model-plan.json` | `image=local_comfyui` / `video=runninghub` + 执行依据 | `model_gate.py`（首次出图/出片前的门禁） |
| `<ws>/video-pipeline/config.local.json` | `concurrency`（以及其他引擎覆盖键） | `engine/config.py` 的覆盖层 |
| `<ws>/video-pipeline/config.upscale.json` | `backend=rh`、`target={exact,1080,1920}`、`rh.workflow_id` | `upscale.py` |

**为什么必须是三处而不是一处**：确认单管「走哪条路」，引擎覆盖层管「怎么跑」，放大配置管
「另一种任务」。合并成一个文件会让「改并发」和「换通道」互相牵连。

## 三、画风不在预配置里

画风由制作包的 `style_lock` 定义（见 `PACK-SPEC.md` §3.1）。预配置只管执行参数，
所以同一份预配置可以服务任何题材的剧 —— 甜宠、悬疑、出海西语，执行层是一样的。

## 四、并发 5 的前提

RunningHub 同一账号的并发额度决定了 5 是否可行。若账号仍是默认额度，会出现部分段
`421 api queue limit reached`：

- 这**不是失败**，是排队；
- 退出码 3 表示「批次有缺口」，**不要改提示词重跑**，直接 `--resume`；
- 想稳一点：在 `config.local.json` 里写 `"concurrency": 2` 覆盖预配置。

## 五、新增一份预配置

在 `configs/presets/` 放一个 JSON，字段照 `local-comfyui-rh.json` 抄。
必填四项：`id`、`label`、`image.choice`、`video.choice`（`video.choice` 带 `workflow_id`）。
`upscale` 段可省 —— 省了就沿用引擎默认（Topaz 本地放大）。
