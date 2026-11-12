# AGENTS.md — SoloDrama 交接入口

> 你是接手本仓库的编码 Agent。**先读完本文件，再动手。**
> 完整技术交接（945 行）：`docs/HANDOFF-CODEX.md` —— 架构、13 节点判据、数据契约、23 视图、
> 18 条已知坑、开发 SOP、故障排查树、口径冲突清单。
> 基线：`main` @ `88324c6`。本文件与代码冲突时以代码为准，并回头修本文。

## 这是什么

把一句话点子做成可发布竖屏短剧的本地流水线。创作写 Markdown，引擎只读 JSON，
换题材模板引擎零改动。Python 3.10+（实测 3.13），FastAPI + 原生 ESM（零构建），文件系统为唯一数据源。

## 开工三步

```bash
python tools/env_check.py --json                        # 环境自检（必需项仅 4 个）
python -m pytest tools/tests stages/import/tests -q     # 期望 112 passed
python web/launcher.py --no-browser                     # 127.0.0.1:8788，/ → /studio/
```

**不要 `pytest` 全仓**：`stages/production/scripts/_ws.py` 导入期缺工作区就 `sys.exit`，这是有意设计。
逐目录跑，命令见 HANDOFF §7.1。

## 先读哪几份

| 要做什么 | 必读 |
|---|---|
| 改流程 / 调度 | `stages/production/scripts/nodes.py` + HANDOFF §2（含判据算法与回流白名单） |
| 改导入 / 门禁 | `docs/pack/PACK-SPEC.md`、`docs/pack/H3-REF2VA-PROMPT.md` |
| 改数据契约 | HANDOFF §3（真实字段样例 + `layout.json` 双层相对路径陷阱） |
| 改 Web / 界面 | `docs/architecture/current-api.md` + HANDOFF §4（23 视图职责表） |
| 改剪辑 / 字幕 | HANDOFF §8 已知坑 K1–K5、§6 R6–R8 |
| 接新通道 | `docs/生成能力与预检.md`、`web/core/comfy_*.py`、HANDOFF §10.4 |

## 不可违反（违反即破坏性改动）

1. **Web 不 import 引擎**。`grep -r "from stages" web/` 必须零命中；新增能力走子进程。
2. **路径不硬编**。目录名真源 `stages/_layout.py` / `web/core/studio.py`；禁止字面量 `04-资产`。
3. **零构建**。不加 npm / 打包器 / node_modules；保留 `_FreshStatic` 防缓存机制。
4. **台词写 `<d>[Chinese] 原句。</d>`**。裸引号中文会被烧进画面，事后无法去除。
5. **视频提示词必须 H3 六段式**，顺序固定（`subject_definitions` → … → `non_diegetic_music`）。
6. **发布版唯一出口** `release_export.py --all --apply` → `09-发行/剧集/EpisodeNN.mp4`。
7. **金额只认 `usage.cost` / `inventory.spend`**，供应商没给就写「未知」，不许回退成 0。
8. **不猜数据**。缺字段报错让人补；无 `model-plan.json` 的 `choice` 就拒绝出图出片。
9. **不恢复已移除能力**：封面引擎、角色差异化、FFS lint、`tools/cli.py`、`workflow.py`。
10. **★计费动作先报价**：云端实例、RunningHub、放大服务，未获确认不得执行。

## 状态机（一句话记住）

13 节点：`import.pack → asset.render → import.bind → board.frame → import.gate →
video.resolve → video.batch → video.audit → edit.master → edit.upscale →
edit.subtitle → edit.draft → edit.release`

五环节：导入(3) / 资产(1) / 分镜图(1) / 出片(3) / 剪辑(5)。
六态 `absent/stale/failed/passed/skipped/blocked`；退出码 `0/2/3/4/5/6`（2 = 判据不过，属正常）。
状态只由产物 + 判据推出，**不认目录存在**。

## 口径陷阱（会误导你的过期文案）

- `drama guide` 里的 `setup / workflow / pipeline` **已删除**，敲了报 `invalid choice`。
- `drama.py` 注释与 argparse help 写「七环节 23 节点」，实际 **5 环节 13 节点**。
- `pipeline.js` 与 `pipeline.py` docstring 写「11 环节」，实际已按五环节。
- `current-api.md` 标题写 111 端点，实测 **118**。
- 完整清单：HANDOFF §14。**修文案单独提交，别混进功能改动。**

## 提交纪律

```bash
git add <files>
python tools/rebuild_manifest.py --apply
python tools/rebuild_manifest.py --check      # 哈希不符 0 + 行尾漂移 0
git add manifest.sha256
```

顺序不可换（文件集取自 git 索引）。工作树必须 LF，不用 `--fix-eol`（会丢未提交改动）。

## 现在能做什么

- **P0**：T1 成本中心 LLM 金额（两选一，不许编价）；T2 RunningHub `status` 字段实测收口。
- **P1**：导航收敛、`connections.js` 拆分、`/api/run` 与 `/api/pipeline/run` 分工、创作草稿区（需评审）、口径文案统一。
- **P2 需用户决策**：全自动出片 Agent（`docs/AGENT-PLAN.md` 是规划稿，脚本未创建）。

## 停下来问人的三种情况

要花钱 · 要改内容语义（提示词/剧本/阈值） · 要动契约（`pack` 字段、`data` schema、节点 id）。

---

完整依据、验收标准、开发 SOP、故障排查：`docs/HANDOFF-CODEX.md`。
