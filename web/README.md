# SoloDrama Web 控制台（web/）

> 定位：**观察者 + 调度者**，不是实现者。
> 读 → 工作区 JSON（唯一真源）或引擎 CLI 的 `--json`；写 → 只走白名单 CLI 子进程；
> 判断 → 退出码（`0` 成功 / `2` 门禁不过 / `3` 熔断 / `4` 待确认 / `130` 中断）。
> **引擎侧零改动**：删掉本目录即完全回滚。

## 两张脸：使用端 ≠ 开发者端（重要）

本目录同时提供两张界面，**共用同一套后端**，但受众、语言与信息密度完全不同。改动前先确认你在改哪一张脸：

| | 使用端（默认入口） | 开发者端 |
|---|---|---|
| 文件 | `ui/index.html` + `ui/home.js` | `ui/advanced.html` + `ui/app.js` |
| 受众 | **做短剧的人**（非开发人员） | 维护者 / 你自己 |
| 组织方式 | 按「**要做什么**」——今天建议做这个、需要你做的事、花了多少钱、我的剧集 | 按「**引擎结构**」——15 环节、命令目录、作业、门禁、审计 |
| 语言 | 人话：画风、这台电脑/云端、镜头、约 ¥36、正在做、需要你确认 | 工程语言：spec_id、argv、退出码 2/3/4、G0/G5、批次号、RH币、资源锁 |
| 后端接口 | `/api/home`·`/api/tasks`·`/api/episodes`·`/api/glossary`·`/api/help` | `/api/commands`·`/api/jobs`·`/api/audit`·`/api/locks`·`/api/pipeline` |
| 文案规则 | **不得出现**命令、参数、退出码、门禁代号、批次号、点数、路径 | 允许出现全部细节 |

**语言层在 `core/ux.py`**：它负责把引擎事实翻译成用户语言，并组织成 9 个「用户任务」
（选画风 / 选机器 / 写剧本 / 定形象 / 出画面 / 拼成完整一集 / 审片 / 发布前检查 / 建新剧）。
三条纪律：

1. `ux.py` **只翻译、不决策** —— 所有事实来自引擎（读文件或读 CLI 的 `--json`）。
2. 用户端只能触发 `ux.TASKS` 里声明过的动作，动作 id 必须存在于 `core/commands.py`（有测试守卫）。
3. **`tests/test_ux.py` 是产品纪律的机器守卫**：它扫描全部用户文案，出现 `argv / 退出码 / 门禁 /
   工作区 / RH币 / 批次号 / G0 / --yes …` 即判失败。改用户文案后必须跑它。

写文档、写文案、加功能前，先问一句：**这句话是给做短剧的人看的，还是给维护者看的？**

## 快速开始

```powershell
# 1) 建独立 venv（与引擎环境隔离；引擎只用 httpx + Pillow，本层才需要 FastAPI）
python -m venv C:\Users\<你>\.workbuddy\binaries\python\envs\solodrama-web
C:\Users\<你>\.workbuddy\binaries\python\envs\solodrama-web\Scripts\python.exe -m pip install -r web\requirements-web.txt

# 2) 指定剧项目工作区（控制台也可在页面里登记）
$env:SOLODRAMA_WORKSPACE = "D:\剧本\海外剧\1013新建"

# 3) 启动（默认仅本机 127.0.0.1:8788；首页 = 使用端）
C:\Users\<你>\.workbuddy\binaries\python\envs\solodrama-web\Scripts\python.exe web\run_console.py

# 只读模式（禁止一切写操作，用于纯查看/演示）
$env:SOLODRAMA_CONSOLE_READONLY = "1"
```

- 使用端：<http://127.0.0.1:8788/ui/> 　（「我的短剧」）
- 开发者端：<http://127.0.0.1:8788/ui/advanced.html>

## 关键实现事实（改动前必读）

1. **`drama.py` 没有 `--workspace` 全局参数**。工作区只能通过环境变量传递，
   所以 `core/runner.py` 的 `base_env()` 是「按工作区执行命令」的唯一出口：
   它注入 `SOLODRAMA_WORKSPACE` / `DRAMA_WORKSPACE` / `VIDEO_PIPELINE_WORKSPACE`。
   （`convert_storyboard.py` / `ingest_check.py` / `subtitle.py` 等**自带** `--workspace` 参数，
   两者并存、互不冲突。）
2. **布局解析必须 import `stages/_layout.py`**，不要复刻。仓库已存在 `subtitle.py` /
   `upscale.py` / `tools/cli.py` 三处轻量复刻，Web 层再抄一份就变第四处。
3. **命令是声明式白名单**（`core/commands.py`）：新增动作要改代码，配置里改不出来 ——
   这是刻意的安全设计，杜绝「任意命令执行」。
4. **计费与危险操作有闸门**：`billing=paid` 需前端显式确认；续跑必须回填批次号
   （防止误触发全量重跑造成重复扣费）；`SOLODRAMA_CONSOLE_READONLY=1` 时拒绝一切写操作。
5. **密钥不出后端**：日志/接口返回统一过 `runner.mask_text()`（替换真实 Key、抹掉 base64 长串）。
6. **作业是服务端对象**（`core/jobs.py`，stdlib `sqlite3`）：浏览器刷新/断线不影响作业；
   资源锁 `GPU-1` / `RH-1..5` / `MEDIA-1` 对应「Topaz 独占」与「RunningHub 单账号并发 ≤5」。

## 目录

```
web/
├── app.py               FastAPI 应用（REST + SSE + 静态 UI）
├── run_console.py       启动入口
├── core/
│   ├── paths.py         路径与运行时常量
│   ├── runner.py        白名单命令执行器（唯一的「写」通道）
│   ├── reader.py        只读聚合器（整剧一屏）
│   ├── jobs.py          作业队列 / 资源锁 / 事件流 / 审计
│   ├── commands.py      命令目录（开发者语言）
│   └── ux.py            ★ 用户语言层（使用端的唯一真源）
├── ui/
│   ├── index.html + home.js      使用端（我的短剧）
│   ├── advanced.html + app.js    开发者端
│   └── styles.css                共用样式
├── tests/               离线测试（零网络、零计费）
├── var/                 运行时（jobs.db、logs/）—— 已在 .gitignore 排除
└── requirements-web.txt
```

## 离线自测

```powershell
<venv>\Scripts\python.exe web\tests\test_ux.py         # ★ 用户语言层（产品纪律守卫）
<venv>\Scripts\python.exe web\tests\test_commands.py   # 命令目录契约（argv / 校验 / 工作区传参 / 提示词）
<venv>\Scripts\python.exe web\tests\test_runner.py     # 打码 / 环境注入 / 退出码语义
<venv>\Scripts\python.exe web\tests\test_jobs.py       # 作业库 / 资源锁 / 状态机
```
