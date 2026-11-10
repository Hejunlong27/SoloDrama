# 05 · 生产流程审计

> 判据真源：`stages/production/scripts/nodes.py`（13 节点 + 5 stage 元数据）。
> 「节点存在」不代表「Studio 能跑」——本文分开记录两者。

## 1. 13 节点与依赖链

| # | 节点 | 阶段 | 集级 | 上游依赖 | 判据 |
|---|---|---|---|---|---|
| 1 | `import.pack` | import | 是 | 制作包 JSON | 产物存在 |
| 2 | `asset.render` | asset | 否 | 资产清单 | 图数对齐 |
| 3 | `import.bind` | import | 是 | 1 | 绑定表完整 |
| 4 | `board.frame` | board | 是 | 2、3 | 每镜 1 张 9:16 |
| 5 | `import.gate` | import | 是 | 1、3 | `pack_spec` 报告无 err |
| 6 | `video.resolve` | video | 是 | 2、4 | 参考图齐 |
| 7 | `video.batch` | video | 是 | 6 | **计费**；退出码 3 = 批次缺口 |
| 8 | `video.audit` | video | 是 | 7 | 产物审计 |
| 9 | `edit.master` | edit | 是 | 7、8 | 帧数校验 |
| 10 | `edit.upscale` | edit | 是 | 9 | — |
| 11 | `edit.subtitle` | edit | 是 | 9（或 10） | 时间轴自检 |
| 12 | `edit.draft` | edit | 是 | 9、11 | `draft_manifest.json` 的 `verdict.pass` |
| 13 | `edit.release` | edit | 是 | 9–12 | `EpisodeNN.mp4` 落 `09-发行/剧集/` |

**节点数口径**：`nodes.py` 里 `stages` 元数据只有 5 条（import/asset/board/video/edit），这 5 条是**阶段**，13 条是**节点**。任何文档写「12 节点」都是过期口径。

**状态机语义**（`nodes.py:682-751` 实测）：`skipped` / `blocked` / `absent` / `stale` / `passed` / `failed` 六态。`blocked` 带「上游未通过：…」，这是 UI 必须原样展示的字段 —— 它直接回答用户「我这一步为什么不能做」。

## 2. 门禁顺序

```
style（画风三轨） → models（model_gate） → 资产 → 分镜 → 导入 → 出片 → 成片
```

`docs/styles/画风三轨规范.md` 定「画风不可事后更换」。这意味着 UI 上**画风一旦选定，必须显示为不可变属性**，不能用可点击的下拉框伪装成可改。

## 3. 计费闸门链（不可绕）

| 层 | 机制 | 位置 |
|---|---|---|
| CLI | `model_gate.py` 模型确认单 | `stages/production/scripts/` |
| CLI | `gen_preflight.py` / `episode_preflight.py` 生成预检 | 同上 |
| CLI | `_netguard.py` 出网与域名信任 | `stages/_netguard.py` |
| Web | `CMD.danger > CMD.READ` 只读拦截（423） | `web/app.py:597` |
| Web | 计费确认（428 + confirm） | `web/app.py:617` 附近 |
| 数据 | `ledger/runs/*.json` 每次实跑留证 | `stages/_ledger_core.py` |

审计结论：**门禁是双份的（CLI + Web）**，这是正确设计。2.0 的界面层**只能调用这套**，不得在前端做「跳过预检直接跑」的快捷路径。

## 4. 退出码语义（必须被 UI 正确翻译）

| 退出码 | 含义 | UI 应显示 |
|---|---|---|
| 0 | 成功 | 通过 |
| 2 | 门禁未通过（例如 `release_check` 缺项） | 「缺 N 项」，列清单，**不是「接口故障」** |
| 3 | 出片批次缺口 | 「有 K 镜没出」，给 `--resume` 的动作 |
| 其它非 0 | 真实错误 | 显示 stderr 尾部 |

`web/app.py:809-820` 已按这个语义处理 `release`（`rc=2` 时不报故障）。2.0 新增任何调用都必须沿用：**把门禁失败显示成「服务异常」是当前最容易犯的错**。

## 5. Studio 侧接线现状

| 环节 | `api.js` 有无 | 页面 | 备注 |
|---|---|---|---|
| 工作流状态 | `workflow(ws)` | workflow/setup 预取 | 每调一次起一个子进程 |
| 分镜三态 | `shots(ws, ep)` | boards / storyboard / canvas | 主力数据源 |
| 提示词 | `studio/prompt` | storyboard | 只有整串 |
| 发行检查 | `releaseStatus(ws)` | release | 含 verdict |
| 导出干跑 | `releaseExportPreview(ws)` | release | 只读 |
| 成本 | `cost(ws)` | cost | 唯一聚合 |
| 环境 | `env()` | health | `env_check.py` |
| 作业 | `jobs` + SSE | tasks | 真实队列 |

缺口：**没有「一键跑某节点」的统一入口**。当前 `POST /api/run` 是通用命令通道，`POST /api/pipeline/run` 是计划执行，两条路并存。2.0 的「生产控制中心」必须选定一条并说清区别，否则用户会在两个按钮之间反复试。

## 6. 已知不可执行项（禁止为它们建 UI 门禁）

| 项 | 事实 | 处置 |
|---|---|---|
| FFS lint / 五锚连续性 | 已移除，无脚本 | 不建页面 |
| 角色差异化检查 | 差异化脚本**已移除**（仓库无此脚本） | 不建页面；若保留 `docs/assets/角色差异化设计规范.md`，须标注「方法论，无执行」 |
| 封面生成 | `cover_prompt.py` / `cover_forge.py` 已移除 | 只做「封面是否齐/规格是否对」校验，不提供生成按钮 |
| 剪映「直接改草稿」 | 剪映打开即把 `draft_content.json` 加密，官方无解密器 | 只提供「导出 SRT → `subtitle.py --from-srt`」通道 |

## 7. 流程层结论

1. 引擎是**稳定资产**：13 节点、双份门禁、六态状态机、退出码语义都已在生产里跑过。2.0 一行不改最好。
2. Studio 的问题是**表达**不是**能力**：用户看不到「当前阶段 / 下一步 / 为什么被拦」。
3. 唯一必须新增的后端能力只有两处：**提示词结构化读写**、**单镜即时校验**。其余全部是「把已有端点组织好」。
