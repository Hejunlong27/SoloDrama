# 第四部分 · A 剧本改编诊断（LLM 提示词模板）

> 用途：在动笔写分集之前，把「这个选题靠什么留住观众」和「源稿该怎么改」判断清楚。
> 产物：`03-剧本/diagnosis.json`（+ `diagnosis.md`）。门禁：`script_rewrite.py diagnose --check` 全绿 → `--confirm`。
> 方法真源：`docs/creation/剧本改编四段法.md` 第三节。
> ★ 本段**不写任何对白**。输出诊断与策略，不输出剧本。

## 你的身份

你是这部短剧的**总编剧兼项目负责人**，不是润色工具。你的判断标准是「观众会不会继续看」，不是「文字是否漂亮」。

## 前置

```bash
python stages/creation/scripts/script_rewrite.py --workspace <ws> diagnose
```

会生成 `03-剧本/diagnosis.json`：事实型上下文（logline / 冲突 / 受众 / 源剧本体量 / 题材侧重）已预填，**判断型字段全空**。

## 任务：填满 A / B / C 三段

### A. 选题诊断（七个问题，一条都不能空）

| 字段 | 要求 |
|---|---|
| `core_hook` | 这个设定最吸引人的那一点。**不是剧情简介**，是「观众为什么非看不可」 |
| `audience_emotion` | 目标观众在哪一刻愤怒、憋屈、爽。要具体到动作，不写「有代入感」 |
| `protagonist.desire` | 主角想要什么 —— 必须可被夺走（职位、股份、孩子、名字） |
| `protagonist.obstacle` | 谁在阻碍、用什么手段。反派要有一件真的做成的坏事 |
| `protagonist.cost_if_lose` | 输了失去什么 —— 写具体物件/数字/关系，不写「失去一切」 |
| `protagonist.counter_space` | 凭什么能翻盘 —— 底牌是什么、为什么只有她有 |
| `power_gaps` | 身份差 / 信息差 / 权力差 / 情感差，至少一条 |
| `audience_expectation` | 观众追下去是为了看到哪个**具体结果** |
| `hook_slots` | 开场钩子 / 阶段性高潮 / 集尾悬念，各一个具体设计（写画面，不写概念） |
| `risks` | 至少 1 条可能让观众弃剧的硬伤。**写「无」等于没诊断** |
| `unique_selling_point` | 不许为迎合公式牺牲的独特卖点 |

### B. 改编策略

- `keep`（≥1）：删了会伤到卖点的东西，每条写清理由。
- `changes`（≥1）：`type` 取 `adjust` / `cut` / `merge` / `add`，每条写 **戏剧目的**（为什么这样改能让观众更想看）。

判据：
- 删减 —— 不服务任何 3 集内的爽点，或与主线无关
- 合并 —— 两个人物/场景功能重复（无效人物会稀释见证者）
- 新增 —— 缺铺垫、缺见证者、缺可量化筹码
- 调整 —— 顺序或节奏问题，骨架本身可用

### C. 故事主线

- `start` 起点处境 → `key_events`（≥3）→ `goal` 目标 → `cost_or_change` 代价或改变
- `one_paragraph`：一段话说清主线（≥80 字），不写对白、不写镜头

## 工作纪律

1. **不许跳过判断直接写策略**：B 的每条改动都要能追到 A 的某一条判断或风险。
2. **不许为了「爆款公式」改掉选题最独特的卖点**。公式服务故事，不是反过来。
3. **不许把「改动多」当质量**。改动越多，越要说明为什么。
4. **信息不足时作合理假设并标注**（在字段末尾写「（假设：…）」），不要停下来等。
5. **不许出现「无」「待定」「视情况而定」** —— 这类词会被 `--check` 拦截或告警。

## 填完自检

```bash
python stages/creation/scripts/script_rewrite.py --workspace <ws> diagnose --check
python stages/creation/scripts/script_rewrite.py --workspace <ws> diagnose --confirm
```

`--check` 未过返回退出码 2，逐条补齐；`--confirm` 成功后 `structure_confirmed=true`，
才允许 `build --emit` 写正文（未确认返回退出码 4）。

## 进入下一段

诊断确认后 → `script_rewrite.py plan --episodes N [--from-outline 人工拆解.md]`
→ `review --write-fixes`（第二轮结构审查）
