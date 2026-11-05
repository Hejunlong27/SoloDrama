# 云端 ComfyUI 接入（第三方镜像部署）

> 目标：把「本机 8G 跑不动长镜」这件事，变成一条**可计费、可回收、可追溯**的云端通道。
> 真源：`cloud/`（代码）、`configs/settings.example.json`（配置项）、本文（操作口径）。
> **进度与待办看 `docs/云端接入进度.md`** —— 连续对话时以那份为准。

---

## 0. 一句话结论

> **产物回传是这套接入里唯一「有时间窗」的环节**：`/history` 是内存态、output 随实例销毁，
> 所以拉回必须发生在停机之前。`cloud pull` 手动兜底，`--engine cloud` 自动兜底（见 §2 ⑥）。

出片侧原本**没有**云端执行器（`model_gate` 里 `video=cloud_comfyui` 是 `executor: None`），
所以「支持云端」只是菜单上的一行字。本次把这条路补齐，并且**不新增第二条代码路径**：

```
drama video run --engine cloud  →  cmd_video_local()  →  comfy_batch_video.py
                                                         →  comfy_local_video.py（同一客户端）
                                                         →  COMFYUI_URL 指向远端
```

本机与远端的差别只有三处：**超时档位、提交前释放显存、产物断点续传**。
回滚只需要把 `COMFYUI_URL` 改回 `http://127.0.0.1:8188`，不用回滚代码。

---

## 1. 选拓扑（先定这个，再谈配置）

| 拓扑 | 形态 | 守卫改动 | 适合 |
|---|---|---|---|
| **A 引擎同机** | 引擎 + ComfyUI 都跑在云实例里，工作区挂云储存 | 零（127.0.0.1） | 无人值守批量生产（**推荐**） |
| **B SSH 隧道** | 本机引擎 `ssh -L 18188:127.0.0.1:8188`，`COMFYUI_URL=http://127.0.0.1:18188` | 零（端点仍是 loopback） | 本机调试、临时验证 |
| **C 直连公网** | `COMFYUI_URL=https://<实例>-8188.container.x-gpu.com` | **要**（受信域名） | 本机下发、云端出片；必须先解决鉴权 |

选 A 的理由：云端批量的形态是「提交后无人值守」。本机一断网，240 个镜头的队列就断了 ——
这比多付一点机时贵得多。C 的风险是「地址泄露 = 别人用你的 GPU 烧钱」，
真要暴露就加 Nginx Basic Auth + IP 白名单，不要裸奔。

---

## 2. 五步打通（以拓扑 C 为例，A/B 只差 COMFYUI_URL）

### ① 让守卫认识「受信远端」

守卫默认只放本机与内网（`stages/_netguard.py`）。云端域名必须**逐条点名**：

```bash
# PowerShell
$env:SOLODRAMA_TRUSTED_HOSTS = "*.container.x-gpu.com"
# cmd
set SOLODRAMA_TRUSTED_HOSTS=*.container.x-gpu.com
```

或者写进 `configs/settings.json` 的 `comfyui.trusted_hosts`（由 `python -m cloud` 补进环境变量）。

> 为什么不用 `SOLODRAMA_ALLOW_REMOTE=1`：它放开的是「除黑名单外的一切远端」。
> 为了跑一镜就把整个互联网放开，等于用一个粗开关换掉一个精确边界。
> 通配 `*.suffix` **只匹配子域**，`container.x-gpu.com` 本身不放、`a.suffix.evil.com` 也不放；
> 黑名单（`rh-api` / `rhapi`）永远优先于受信名单。

### ② 确认模型（确认单即执行依据）

```bash
drama models set video=cloud_comfyui --comfy-url https://<实例>-8188.container.x-gpu.com
```

确认后 `detail.comfy_url` 会被回灌成 `COMFYUI_URL`（`model_gate.apply_env()`，环境变量优先，
不覆盖已有值）。出片侧此前缺这一步 —— 确认了 A 却跑 B 时，报出来是「连不上 ComfyUI」，
真相是「跑到了另一台机器」。

工作流**不再是必填**：`workflow_h3_minimax_canvas.json` + 同名 map 随仓库交付，
与出图侧的 `local_comfyui` 同一口径。要换才给 `comfy_workflow`。

### ③ 就绪三查（别等提交才发现缺模型）

```bash
python -m cloud probe --url https://<实例>-8188.container.x-gpu.com
```

| 检查 | 接口 | 判据 |
|---|---|---|
| 版本 | `/system_stats` | ComfyUI ≥ **0.42.1**（`convrot` 量化格式的最低要求） |
| 节点 | `/object_info` | 工作流引用的 class_type 全部存在 |
| 模型 | 同上，读 Loader 的 `enum` | 工作流写死的文件名在枚举内 |
| （附）必需输入 | 同上 | 连线缺口也拦 —— 节点齐 + 模型齐 ≠ 能跑 |

云端缺模型的症状是「提交即 400，报 node type missing」，看起来像节点没装，其实是
文件名差一个字符（`convrot` / `int8` / `pruned` 后缀最容易漏）。所以这项必须点名到文件。

### ④ 出片

```bash
drama video run --engine cloud --ep 01 --yes
```

两道前置会自动跑，任一不过直接退出（不会「以为在云端其实跑在本机」）：

1. 地址不是 loopback（否则 = 账实不符，和「确认本地却跑 RH」同一类错）；
2. 守卫认这个域名 + `/system_stats` 通。

产物落点与本地一致：`07-成片/<ep>/<shot>/final.mp4`；批次记录写
`_batch_local.json`（`channel` 为 `comfyui-cloud`、`billed: true`、并记 `endpoint`）。
超时自动取 30 分钟/镜（`SOLODRAMA_VIDEO_TIMEOUT_MIN` 可覆盖），本地仍是 20 分钟。

### ⑤ 停机：默认**自动**，不用你记

`--engine cloud` 默认 `--cloud-lifecycle auto`，所以第 ④ 步那条命令已经包含了启停：

```
任务开始 → 复用/开机/新建/借一台 → 等就绪 → 出片 → 停实例（含失败、含 Ctrl-C）→ 记台账
```

| lifecycle | 行为 | 什么时候用 |
|---|---|---|
| `auto`（默认） | 要跑才开，跑完就关；**只关自己开的** | 日常 |
| `keep` | 跑完保留（★继续计费） | 连续跑多集、中间要调参 |
| `off` | 不启停，只用 `--comfy-url` | 调试、临时验证 |

三条语义各自对应一类事故：**只停自己开的**（复用别人的机器却替他关机 = 掐掉别人的任务）、
**失败也停**（出片失败时更没人想起来停）、**没端点就借**（`endpoints` 未配时接管已有地址，
照常跑但不停机，因为不是我们开的）。

手动命令仍然保留，供运维与兜底：

```bash
python -m cloud down          # 停最后一台未停的实例
python -m cloud reap          # 回收「开着但很久没动」的（默认 15 分钟，忘停的兜底）
python -m cloud cost          # 今日 / 累计工时与金额
```

`python -m cloud up` 在**就绪超时时自动 stop**（失败必停）；`cost` 读
`<工作区>/台账/cloud-cost.jsonl`。正常路径用不到这两条 —— `reap` 是给「进程被 kill、
机器重启、压根没走到 finally」准备的。

### ⑥ 产物怎么回本地（★必须在停机之前）

云端出片和本地只有一处本质差别：**产物不在你自己硬盘上**。它在实例的
`ComfyUI/output/` 目录里，靠 `GET /view?filename=&subfolder=&type=output` 取回。

正常路径**不需要你操心**：出片脚本是「跑完一镜立刻下载」，`drama video run --engine cloud`
还会在**停机前**再扫一遍 `/history` 补缺口：

```
提交 → 轮询 → /history 拿到产物清单 → /view 下载（写 .part 再改名，Range 续传）
     → 落 07-成片/<ep>/shot_NNN/final.mp4 → 下一镜
     → 批次结束 → cloud pull 兜底补拉 → 退出 with lease → 停机
```

手动兜底命令（**实例还开着时**用）：

```bash
# 扫一遍远端 /history，把本地缺的补回来（已存在的自动跳过）
python -m cloud pull --workspace "<剧目录>" --ep ep01

# 只下到一个目录，不归位（想先看看云端都有什么）
python -m cloud pull --workspace "<剧目录>" --out D:/tmp/cloud --dry-run

# /history 已清空（实例重启过）时，按文件名单取
python -m cloud pull --workspace "<剧目录>" --ep ep01 --file h3_shot_003_1793866174.mp4
```

**归位规则**（不猜、不新建结构）：

| 情况 | 落到哪 |
|---|---|
| 文件名带镜号（`h3_shot_003_*.mp4`）且本地已有 `shot_003/` 目录 | `shot_003/final.mp4` |
| 同上但本地没有该镜目录 | `_cloud_pull/<原文件名>` |
| 文件名不带镜号（如 `board_001.png`） | `_cloud_pull/<原文件名>` |
| 显式 `--out` | 该目录下，保留原名 |

每次回传都会写一份 `_cloud_pull/pull-<时间戳>.json`（哪个 prompt → 哪个本地文件、大小、失败原因），
出问题时这是唯一能对上号的记录。

**三条硬约束，直接决定「来不来得及」：**

1. **`/history` 是内存态**。实例一重启就清空，但文件还在磁盘上 —— 所以「按名取」（`--file`）能用，
   「列表取」（默认）不能。
2. **非 retain 的实例一销毁，磁盘一起没**。所以回传必须在停机**之前**完成，
   而 `--cloud-lifecycle auto` 的停机点在 `with lease` 退出时 —— 兜底拉回就放在那个点之前。
3. **拉不回来就别急着停**。`cloud pull` 失败会明确打印「实例即将停机」，
   这时改 `--cloud-lifecycle keep` 保机，或去控制台续租，比事后重跑省钱。

> 一句话：**这是一次性的时间窗**。云上跑完 → 本地有文件 → 才能停；
> 顺序反了，产物就只剩「再花一次钱」。

---

## 3. 命令速查

| 命令 | 作用 | 备注 |
|---|---|---|
| `python -m cloud doctor` | 自检：Token / 端点 / 守卫 / scp | 缺什么点名说，不猜 |
| `python -m cloud attach --url <地址>` | 接管已启动的实例 | 拓扑 A/B 最省事；不建实例 |
| `python -m cloud up --name <名> [--gpu 4090]` | 建实例 → 等就绪 | 同名实例在跑则**复用** |
| `python -m cloud status` | 本地记录 + 就绪三查 | 离线也看得到记录 |
| `python -m cloud probe --url <地址>` | 只查不建 | 支持 `--json` |
| `python -m cloud down [--instance ID] [--all]` | 停实例 | 停不了会明确让你去控制台 |
| `python -m cloud reap [--idle-min N] [--dry-run]` | 回收空闲实例 | 忘停的自动兜底 |
| `python -m cloud pull --workspace <ws> --ep ep01` | **把远端产物拉回本地** | 停机前！已存在的自动跳过；`--file` 兜底 |
| `python -m cloud cost [--json]` | 成本台账 | 未定价的行会标出来 |

`up` 的**四条硬约束**（都有测试）：

1. **幂等** —— `list` 端点没配就拒绝创建，不盲建（脚本重跑 ≠ 两台机器同时计费）；
2. **失败必停** —— `wait_ready` 超时自动 `stop()`；
3. **凭据不落盘** —— `XGY_TOKEN` / SSH 只用环境变量，日志一律 `mask()`，台账/状态文件里搜不到；
4. **成本护栏** —— 当日累计 GPU 小时超 `cloud.max_hours_per_day` 直接拒绝。

---

## 4. 配置项（`configs/settings.json`，从 `.example.json` 复制）

```jsonc
"comfyui": {
  "base_url": "https://<实例>-8188.container.x-gpu.com",
  "mode": "direct",                         // local | ssh_tunnel | direct
  "trusted_hosts": ["*.container.x-gpu.com", "api.xiangongyun.com"],
  "timeout": { "submit": 120, "poll": 1.5, "video_min": 0 }   // 0 = 按链路自动
},
"cloud": {
  "provider": "xiangongyun", "gpu": "4090", "disk_gb": 100,
  "max_hours_per_day": 8, "price_per_hour": 1.59,              // 兜底价；上游报的实例价优先
  "api_base": "https://api.xiangongyun.com/api/",
  "token_env": "XGY_TOKEN", "auth_header": "Authorization", "auth_scheme": "Bearer",
  "id_field": "instance_id",                                    // 待核对：请求体里的 ID 键名
  "endpoints": { "create": "", "list": "", "stop": "", "destroy": "", "detail": "" },
  // 候选路径列表：按序尝试，命中即用（网关是否包一层 data 不固定）
  "field_map": {
    "id": ["data.id", "id"],            "http_url": ["data.web_url", "web_url"],
    "ssh_host": ["data.ssh_domain", "ssh_domain"], "ssh_port": ["data.ssh_port", "ssh_port"],
    "state": ["data.status", "status"], "price_per_hour": ["data.price_per_hour", "price_per_hour"],
    "retain": ["data.retain", "retain"], "retain_price": ["data.retain_price", "retain_price"]
  },
  "ready_timeout_min": 8, "price_per_hour": 0
}
```

**加载优先级：环境变量 > `settings.json` > 内置默认。** `effective()` 的返回值里**不含密钥**，
`hydrate_env()` 只往环境变量里补、不覆盖已有值（供子进程使用）。

---

## 5. 本次改了什么

| 文件 | 改动 |
|---|---|
| `stages/_netguard.py` | +`_trusted_hosts/_is_trusted/reset_trusted/would_allow`；插入点在私网之后、`ALLOW_REMOTE` 之前；自检加一行 |
| `stages/_comfy_http.py` | `download(..., resume=True)`：`Range` 续传、206 追加 / 200 截断重写 / 416 收尾 |
| `stages/video/comfyui/comfy_local_video.py` | +`_is_loopback/_default_timeout_min`；`submit_and_wait(timeout_min=None)`；远端提交前 `/free`；CLI 超时默认自动 |
| `stages/video/comfyui/comfy_batch_video.py` | `--comfy-url`、`--timeout-min` 自动档、批次记录区分 `comfyui-cloud` |
| `stages/production/scripts/model_gate.py` | 视频 `cloud_comfyui` 填 `executor` / `engine_arg=cloud` / `requires=["comfy_url"]`；+`apply_env()` |
| `stages/production/scripts/drama.py` | `video run --engine cloud`、`--comfy-url`、两道前置、停机提示 |
| `cloud/`（新） | `config` / `health` / `provisioner` / `transport` / `ledger` / `cli` |
| `configs/settings.example.json` | `comfyui.mode/ssh/trusted_hosts/timeout` + `cloud` 段 |
| 测试 | `test_netguard_trusted.py`(11) / `test_video_remote.py`(14) / `cloud/tests/test_cloud.py`(22) / `test_comfy_http.py` +3 / `test_model_gate.py` +7 断言 |

---

## 6. 待确认项（不臆造上游字段）

| 项 | 状态 | 影响 |
|---|---|---|
| **端点路径**（`create`/`list`/`stop`/`destroy`/`detail`） | **未确认**（需登录后的 Playground 目录） | 留空 → `up` 报「待配置」；`attach` 仍可用 |
| 响应**字段名** | ✅ 已校准（2026-11-05 读官方 Playground「获取实例列表」） | `web_url` / `ssh_domain` / `ssh_port`（字符串）/ `status` / `price_per_hour` / `retain` |
| 响应**信封** | 已知 `{code, msg, success}`（缺令牌时 `1000 未找到访问令牌`） | 已识别：`success=false` 直接抛错，不当成空结果 |
| GPU 单价 | ✅ 用户给定 **￥1.59/时**（兜底） | 有上游实例价时以实例价为准，兜底只在上游没给时用 |
| 自启脚本拉起 ComfyUI 的耗时 | 待实测 | `ready_timeout_min` 默认 8 |
| 云端 SSH 是否默认开放 | 待确认 | 不开就只能用 HTTP 拓扑；`transport` 会报「没有 SSH 地址」 |

端点核对之后的正确做法：只改 `settings.json` 的 `endpoints` / `field_map`，
**不改代码** —— 语义层（幂等 / 必停 / 护栏 / 台账）已经用本地假上游全量测过。

---

## 7. 风险与对策

| 风险 | 表现 | 对策 |
|---|---|---|
| 云端模型文件名不一致 | 提交即 400，报 node type missing | 先 `cloud probe` 点名缺哪个文件 |
| ComfyUI 版本过低 | `convrot` 加载失败 | `probe` 校验 ≥ 0.42.1 |
| 网络抖动 | `/history` 偶发读失败 | 已有「连续 3 次才判失败」，**不要改严** |
| 实例忘停 | 持续计费 | `max_hours_per_day` + `wait_ready` 失败必停 + `cloud cost` 对账 |
| **关机仍计费**（`retain` 保留磁盘） | 以为「停了不花钱」，账单一直在走 | `stop()` 检测到 `retain_price>0` 会告警并写进台账备注；彻底归零要销毁实例 |
| 守卫被绕过 | 镜头传到非预期域名 | 黑名单优先于白名单；新增受信域名走 code review |
