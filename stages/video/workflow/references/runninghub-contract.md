# runninghub-contract.md —— RunningHub API 契约

> 保持诚实口径：**「已确认」= 本机真实联调跑通的代码验证过；「待实测」= 只做了容错解析，需要你跑一次确认。** 两张表分开维护，不要混。

## 一、已确认契约（可放心依赖）

| 事项 | 契约 |
|---|---|
| 统一入口 | `https://www.runninghub.cn`（注意是 .cn） |
| 鉴权 | `Authorization: Bearer <apiKey>`；v1 端点兼容 body 内 `apiKey` |
| 上传 | `POST /openapi/v2/media/upload/binary`，multipart 字段名**必须是 `file`** → `data.fileName` / `data.download_url`（**仅 1 天有效**，引擎缓存 20h） |
| 提交工作流 | `POST /task/openapi/create`，body `{apiKey, workflowId, nodeInfoList}` → `data.taskId` |
| 提交 AI 应用 | `POST /task/openapi/ai-app/run`，body `{apiKey, webappId, nodeInfoList}` → `data.taskId` |
| 查询任务 | `POST /openapi/v2/query`，body `{taskId}` → 顶层 `status` + `results[{url, outputType, text, nodeId}]` + `usage{consumeMoney, consumeCoins, taskCostTime}` |
| 状态词 | `CREATE / QUEUED / RUNNING` 非终态；`SUCCESS` 成功；`FAILED / CANCEL` 失败 |
| 节点注入 | `nodeInfoList = [{"nodeId": "…", "fieldName": "…", "fieldValue": "…"}]` |
| 输出链接 | `results[].url` 约 24 小时有效 → 必须落盘（引擎已做） |
| 失败原因 | 查询响应里的 `failedReason`（引擎会截断到 200 字符落盘） |

## 二、待实测契约（代码已做容错，跑一次即可坐实）

| # | 待确认项 | 现状 | 怎么验证 |
|---|---|---|---|
| 1 | `/task/openapi/status` 的真实返回字段名 | 代码做了多候选容错解析；`config` 的 `poll_channel` 默认 `v2`，一般用不到 status 通道 | 无需主动验证；若被迫切 `poll_channel=status`，看轮询日志是否识别状态 |
| 2 | 香蕉提示词节点 `fieldName` 是 `text` 还是 `prompt` | 默认写 `text` | `run.py probe --target banana`，对照实际 fieldName；**小样（G4）必须先跑 1 条确认** |
| 3 | H3 首帧图 / 参考图节点的 `nodeId` + `fieldName` | 默认为空 | `run.py probe --target h3`，候选必须用户逐项确认 |
| 4 | 香蕉是否回传 zip | 引擎只解 zip 到 `banana_raw_extracted.png`，但裁剪阶段目前读 `banana_raw.png` → **会崩**（见 troubleshooting §1） | 第一次真实跑香蕉后看 `shot_XXX/` 里落的是 png 还是 zip |

## 三、并发与重试纪律（引擎已内置，不要绕过）

- **平台硬限：消费级（会员）API Key 的同时调用数量上限 = 5 个**（用户 2026-09-18 明确，非可调优参数）。因此并发只能是 5，`config.CONCURRENCY_MAX = 5` 是唯一来源；**不得靠多开脚本 / 多进程绕过**。
- 全局 `asyncio.Semaphore(5)` 包住「**提交 + 轮询到终态**」整段生命周期；提交成功但还在轮询时，槽位不释放。下载放在信号量外。
- 只重试瞬时错误（网络错误 / 429 / 5xx / 限流）；**401 / 403 / 余额不足 / 参数错误不重试**。
- 重试退避：5s → 15s → 45s，最多 3 次；**队列满（421）例外**：30s → 60s → 120s。
- **省钱铁律**：`create` 成功但 `poll` 失败 → 只重试 poll，复用原 taskId，**禁止重复提交**。断点续跑时 `image_task_id` / `video_task_id` 存在且未终态 → 复用 taskId 继续轮询，且不重新上传参考图、不重新拼 nodeInfoList。

## 四、节点探测（get_nodes）

- 引擎方法：`RunningHubClient.get_nodes(kind, target_id)`；CLI：`run.py probe --target banana|h3` 或 `--kind workflow|ai-app --id <ID>`。
- 探测**不扣费**，但需要 API Key 且目标 ID 已填。
- 返回空列表的常见原因：工作流没暴露 API 输入节点（需在 RunningHub 工作流编辑器里把节点标记为 API 输入）、ID 填错、该工作流不属于当前 Key 的账号。
- 候选映射由启发式生成并标 `confidence: high|medium|low|none`；**low / none 必须人工确认**。

## 五、绝对禁区：不要用 `/run` 做连通性探测

`POST /openapi/v2/run/workflow/{workflowId}` **不是幂等接口**：只要 `workflowId` 格式上像样，
平台就会真的创建任务并排队执行。2026-10-19 实测因此产生了一个真实任务
（taskId `2112006454897758210`，随后 `FAILED: missing_node_type`，`usage=null` 属侥幸未计费；
换一把余额充足、参数合法的 Key，这就是**真实扣费**）。

**允许的探针**（全部只读）：`POST /uc/openapi/accountStatus`（Key 类型/余额）、
`POST /openapi/v2/query {"taskId": "0"}`（判断 Key 是否被该站点承认）。
引擎已内置：`rh_doctor.py --probe-readonly`（逐把 Key 判定归属站点，不建任务、不计费）。

## 六、多账号：Key 清单与站点归属

同一把 Key 在错误站点上传会报 `API Key不存在`（账号类接口两站共用，唯独上传不行，极易误判）。
实测归属：账号 1/2 的消费级 Key → `.ai` 站；账号 3 的消费级 Key → `.cn` 站。

Key 清单放 `<工作区>/keys.json`，**只写环境变量名，不写明文**：

```json
{"keys": [
  {"account": "账号1", "site": "https://www.runninghub.ai", "tier": "consumer", "env": "RH_KEY_A1_AI"},
  {"account": "账号3", "site": "https://www.runninghub.cn", "tier": "consumer", "env": "RH_KEY_A3_CN"}
]}
```

```bash
python stages/production/scripts/rh_doctor.py --matrix            # 只看环境变量是否就位（零网络）
python stages/production/scripts/rh_doctor.py --matrix --live      # 逐把做只读探针，输出可用组合
```

引擎当前一次运行只用**一把** Key（`RUNNINGHUB_API_KEY` 或 `config.local.json` 覆盖）——
要吃满多账号并发，需要把可用 Key 逐条分配给 worker（一账号一 worker），
否则两条链落到同一账号会撞 421（见 §三）。

## 七、计费与失败语义（决定「重试要不要钱」）

| 情形 | 平台返回 | 是否计费 | 引擎行为 |
|---|---|---|---|
| 显存不足（OOM） | `errorCode 805` / `VRAM grow failed` / `torch.OutOfMemoryError` | **不计费**（`usage=null`） | 按 `default → plus → plus+降 2s` 三级重试（`config.OOM_*`） |
| 单账号队列满 | `errorCode 421` / `api queue limit reached` | 不计费（未建任务） | 视为瞬时错误，退避 **30/60/120s** 重试 |
| 任务成功但下载断 | 查询仍 `SUCCESS`，下载抛 `WinError 10054` | **已计费** | 下载内部重试 3 次；仍失败写 `pending_download.json`，用 `video resume-download` 只重下 |
| 进程在轮询中被杀 | 无返回 | 可能已计费 | 提交即落 `inflight.json`；`--resume` 启动时逐条 `query` 接回结果 |

## 八、反查 workflowId（没有 list 接口）

`/openapi/v2/workflow/list` 不存在（301 / code=1001），无法按名字反查。
可行途径：保存 AI 应用详情页（`ai-detail/<id>`）HTML，从 `__NUXT_DATA__` 解出底层 `workflowId`：

```bash
curl -s "https://www.runninghub.ai/ai-detail/<appId>" -o app.html
python stages/production/scripts/rh_workflow_id.py app.html
```

脚本只解析本地文件、不联网、不猜（多个候选会全部列出）。

