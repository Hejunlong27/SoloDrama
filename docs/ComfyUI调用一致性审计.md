# ComfyUI 调用一致性审计 + 通道隔离方案

> 审计时间：2026-11-05 15:30 ｜ 范围：仓库里**所有**会碰 ComfyUI 的环节（出图 / 出片 / 体检 /
> 预检 / 启停 / 状态页 / 能力卡）。
> 结论：**功能现在齐了（图像也有云端入口了），但一致性靠的是「每个入口自己解析」，不是共享一份契约**——
> 这是本次修掉 6 处不一致后仍要盯着的结构性风险（见 §4）。

---

## 1. 调用点矩阵（谁在哪一层、依据从哪来）

| 环节 | 入口 | 地址来源 | 工作流来源 | 节点映射 | 判据/超时 | 产物落点 |
|---|---|---|---|---|---|---|
| 图像出图（批量） | `gen_assets_local.py` → `comfy_client.py`（子进程） | **确认单 image** › 环境 › 默认 | 确认单 `comfy_workflow` › `COMFYUI_WORKFLOW` › 仓库默认 | `COMFYUI_NODE_*` / `configs.settings.nodes` | 提交前预检（30s） | `04-资产/` |
| 图像出图（单张） | `comfy_client.py` CLI | 环境 | `--workflow` › 环境 | 同上 | `--check` 自带 | `--out` |
| 图像预检 | `gen_preflight` / `drama preflight --only gen` | **确认单** › 环境 › settings › 默认 | 同上 | 有 sidecar 才校验 | 30s | — |
| 视频出片（批量） | `comfy_batch_video.py` → `comfy_local_video.py` | `--comfy-url` › 环境 | `--workflow` › `COMFYUI_VIDEO_WORKFLOW` › canvas | 同名 sidecar map | 20 / 30 分钟自动 | `07-成片/` |
| 视频出片（单条） | `comfy_local_video.py` | 环境 | `--workflow` › 环境 › canvas | 同上 | 同上 | `--out` |
| 视频体检 | `comfy_local_video.py --check` | 环境 | 同上 | 同上 | 自带 | — |
| 服务启动 | `comfy_boot.py` | 环境 › `DEFAULT_URL` | — | — | 等 120s | — |
| 云端探活/预检 | `cloud/health.probe()` | **显式入参**（不读环境） | 显式入参 | 有 sidecar 才校验 | 20s | — |
| 云端启停 | `cloud/provisioner.py` / `session.py` | 实例 `http_url` → 环境 | 传给 `wait_ready` | — | 就绪 8 分钟 | 台账 |
| Studio 通道页 | `web/core/generators.py` | 连接中心 / 确认单 | 确认单 › 环境 › 默认 | 应用 `_substitute` | 8s / 40s | — |
| 能力卡 | `capabilities.py` | 环境 | — | — | 4s | — |

---

## 2. 本次修掉的 6 处不一致

| # | 问题 | 之前的真实后果 |
|---|---|---|
| 1 | **图像云端通道没有入口**：`model_gate` 允许确认 `image=cloud_comfyui`，但 `drama assets` 只有 `local/wf/rh` | 确认得上、跑不起来；用 `--engine local` 又被门禁以「确认云端却用 local」拦下 ⇒ 通道是死的（视频侧 11-04 就补了，图像侧一直没补） |
| 2 | 图像地址用 `setdefault` 注入 | `COMFYUI_URL` 是 image/video **共用**的全局变量；上一步云端任务留下的地址会让图像**静默打到云端**（拼凑方案直接失效） |
| 3 | 视频本机路径不显式传地址 | 长驻进程里残留云端地址时，「本机出片」会跑到云端 |
| 4 | 视频确认单里的 `comfy_workflow` **不生效** | 只有预检和界面看得到它，实际提交仍是默认 canvas ⇒ 「确认 A、跑 B」 |
| 5 | 文档写了 `drama video run --workflow ...`，CLI 没有这个参数 | 照抄文档报 `unrecognized arguments` |
| 6 | 能力卡把 `127.0.0.1:8188` 写死 | 改端口或指向云端后，卡片一直报「不可达」，而实际能跑 |

修法都遵同一条原则：**依据按「类」解析一次，再显式往下传**（`gen_preflight.resolve()`），
不靠全局环境变量在环节之间传话。

---

## 3. 遗留项（已知、可解释，暂不改）

| 项 | 现状 | 为什么不急 |
|---|---|---|
| 两套体检实现 | `comfy_local_video.check()` 与 `cloud.health.probe()` 各有一份 | `health.probe` 已复用 V 的纯函数（工作流/映射/修补），判据一致；两者入口不同（单条 CLI vs 批量预检） |
| 导入期常量 | `comfy_client.COMFY`、`comfy_local_video.COMFY` 在 import 时读环境 | 因此**必须在子进程启动前设环境，或用 `--comfy-url` 传参**；同进程内改环境对这些模块无效（这是硬约束，已写进各文件注释） |
| Studio 缓存 | 通道页 30s / object_info 300s | 改完配置最多 5 分钟才反映；界面上有「刷新」入口 |
| `web/core/commands.py` 文案 | 帮助文本里写「检查 127.0.0.1:8188」 | 纯文案，不影响行为 |
| **本机服务会间歇不可达** | 15:20 `comfy_boot --up` 拉起成功；15:35 预检报 `ComfyOffline`；15:37 起连续三次探测均在线（0.42.1 / 6.9G）。**原因未验证**（可能是加载/重启/探测超时） | 不下结论，只记事实：批量前预检会明确报 `offline` 并给下一步，不会白跑；真要长期稳定就用桌面版并把预检当习惯 |

---

## 4. 通道隔离：三条线能不能同时各走各的？

**能。前提是「依据按类解析」，而这件事本轮才真正做到。**

| 场景 | 图像 | 视频 | 现在可行？ | 依据 |
|---|---|---|---|---|
| 全本机（默认） | local | local | ✅ | 两条都读确认单，地址都是 127.0.0.1 |
| 出图本机 + 出片云端 | local | **cloud** | ✅ | 图像走 `_apply_model_plan_env`（覆盖式），视频走 Lease 写入实例地址 |
| 出图云端 + 出片本机 | cloud | local | ✅ | 同上，方向对称 |
| 出图 RH + 出片云端 | rh | cloud | ✅（RH 通道暂缓测试） | 两者无共享变量 |

### 配置方式（确认单是按类记的，这就是隔离点）

```bash
# 图像接本地
drama models set image=local_comfyui
# 视频接云端（地址写进 video 的 detail，只影响视频）
drama models set video=cloud_comfyui --comfy-url https://<实例>-8188.container.x-gpu.com
# 受信域名（云端必须，本地不受影响）
set SOLODRAMA_TRUSTED_HOSTS=*.container.x-gpu.com
```

### 验证（免费，不发任务）

```bash
drama preflight --only gen
```

它会分别打印图像与视频两条结论、各自的地址与依据来源。**两行地址不同 = 隔离成立。**
若某一行显示「通道=cloud 但地址是本机」，预检直接判「待配置」——这是拼凑方案最常见的配错，
现在会被拦下，而不是等你出完片才发现跑错了机器。

---

## 5. 防再分叉：改动时的自检清单

1. 新增/修改任何「读 ComfyUI」的代码 → 地址只从 `gen_preflight.resolve(kind)` 拿，不自己 `os.environ.get`；
2. 新增通道 → `model_gate` 里必须有 `executor` + `engine_arg`，且 `drama` 有对应 `--engine` 分支（**两者缺一就是死通道**）；
3. 改工作流默认值 → 同步 `DEFAULT_WF`（预检）、`VIDEO_LOCAL_WF`（界面）、`DEFAULT_WORKFLOW`（执行器）三处；
4. 改模型文件名 → 先跑 `cloud probe` / `gen_preflight`，按**替换后**的名字改，不要照 raw JSON；
5. 任何「新判据」先问：能不能用 `cloud/health.probe`？能就不要写第二份。
