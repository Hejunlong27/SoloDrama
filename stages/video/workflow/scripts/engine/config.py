# -*- coding: utf-8 -*-
"""
================================================================================
 config.py —— 唯一需要你手动修改的文件
================================================================================

【必填清单】（一共 4 处，填完即可直接运行）

  [1] API Key            —— 不用改代码：设置环境变量 RUNNINGHUB_API_KEY
                            Windows CMD:      set RUNNINGHUB_API_KEY=你的key
                            Windows PowerShell: $env:RUNNINGHUB_API_KEY="你的key"
                            也可以直接在下面 RUNNINGHUB_API_KEY 里硬编码（不推荐）

  [2] 激活的图片模型      —— 改 ACTIVE_IMAGE_PROVIDER（"banana" / "gpt_image" / "jimeng"）
                            并在 IMAGE_PROVIDERS 里填该模型的 workflow/应用 ID + 节点映射

  [3] 图片工作流节点       —— IMAGE_PROVIDERS[...]["nodes"] 里的 nodeId / fieldName
                            香蕉是「图生图」：必须填 提示词 + 角色参考图 + 场景参考图 三类节点

  [4] H3 视频工作流        —— H3["id"] 与 H3["nodes"] 里的 nodeId / fieldName

【怎么拿到真实的 nodeId / fieldName？】
  跑一次：  python main.py --probe
  它会调用 RunningHub 的节点发现接口，把每个工作流/应用的 nodeId + fieldName + 示例值
  打印出来。你把打印结果粘到下面的 nodes 里即可。
  （你也可以跑 tools/probe_nodes.py，功能相同）

【配置分层】（优先级从低到高，高者覆盖低者）
  ① 本文件                       —— 结构与默认值，Agent/脚本永不修改
  ② <工作区>/config.local.json   —— 用户私有覆盖层（Key / workflow ID / 节点映射都写这里）
  ③ 环境变量                     —— 只放机密：RUNNINGHUB_API_KEY / RUNNINGHUB_BASE_URL

【不用猜的部分 —— 已由本机验证过的代码确认】
  - 提交工作流: POST /task/openapi/create          body {apiKey, workflowId, nodeInfoList} -> data.taskId
  - 提交AI应用: POST /task/openapi/ai-app/run      body {apiKey, webappId,  nodeInfoList} -> data.taskId
  - 查询任务  : POST /openapi/v2/query             body {taskId} -> status + results[].url + usage
  - 上传文件  : POST /openapi/v2/media/upload/binary  multipart 字段名必须是 file
                返回 data.fileName / data.download_url（download_url 仅 1 天有效）
  - 状态值    : CREATE / QUEUED / RUNNING 为非终态；SUCCESS 成功；FAILED / CANCEL 失败
================================================================================
"""
from __future__ import annotations

import json
import os
from pathlib import Path

# ==============================================================================
# [1] API Key —— 优先读环境变量，读不到就用下面的兜底值
# ==============================================================================
RUNNINGHUB_API_KEY: str = os.getenv("RUNNINGHUB_API_KEY", "")  # ← 建议用环境变量，别写这里

# ==============================================================================
# [1.1] RunningHub 站点 —— 真源是 configs/channels.json，不是环境变量
# ==============================================================================
# 为什么改：`RUNNINGHUB_BASE_URL` 是**进程启动快照**。用户把用户级变量改对了，
#   已经开着的终端 / Studio / 由它派生的子进程仍读旧值，而症状是上传接口报
#   `code=1 API Key不存在` —— 看起来像 Key 错、像账号错、像站点错，唯独不像
#   「变量过期」。实测踩过：能力卡写 .cn、进程里是 .ai，`capabilities check`
#   报「站点不一致」，而人第一反应是去换 Key。
#
#   站点不是机密，就该跟仓库走：改一次，所有进程、所有人、所有子进程都一致。
#   环境变量保留两条口子：SOLODRAMA_RH_SITE（单次覆盖）、旧名 RUNNINGHUB_BASE_URL
#   （仅在没有 channels.json 时兜底）。
#
# 优先级：显式参数 > SOLODRAMA_RH_SITE > channels.json > 旧环境变量 > 常量默认 .cn
#   注意「项目覆盖层」config.local.json 的 runninghub_base_url 仍然最优先 ——
#   它是单个项目的显式选择，覆盖层在 import 之后 apply，天然压过这里。
_SITE_ALIASES = {
    "cn": "https://www.runninghub.cn",
    "zh": "https://www.runninghub.cn",
    "runninghub.cn": "https://www.runninghub.cn",
    "ai": "https://www.runninghub.ai",
    "intl": "https://www.runninghub.ai",
    "runninghub.ai": "https://www.runninghub.ai",
}
_DEFAULT_SITE = "https://www.runninghub.cn"


def _find_repo_root() -> Path | None:
    """向上找带 `configs/channels.json` 的仓库根。

    ★ **不数 parents[N]**：这个仓库里 `parents[n]` 数错一层已经发生过五次
      （gen_boards / nodes / main / init_project / test_init_project），
      每次的症状都是「文件不存在 / 模块找不到」，排查时先怀疑数据。
      改成「向上找特征文件」，层级怎么变都不会错。
    """
    for up in Path(__file__).resolve().parents[:7]:
        if (up / "configs" / "channels.json").is_file():
            return up
    return None


def load_channels() -> dict:
    """读通道配置；读不到返回 {}（不让配置缺失变成启动失败）。"""
    root = _find_repo_root()
    if root is None:
        return {}
    try:
        return json.loads((root / "configs" / "channels.json").read_text(encoding="utf-8-sig"))
    except Exception:                                          # noqa: BLE001
        return {}


def normalize_site(value: str) -> str:
    """`cn` / `ai` / 完整 URL → 完整 URL。认不出的别名原样返回，交给上层报错。"""
    v = str(value or "").strip().rstrip("/")
    if not v:
        return ""
    if v.lower().startswith(("http://", "https://")):
        return v
    return _SITE_ALIASES.get(v.lower(), v)


def resolve_rh_site(explicit: str | None = None) -> tuple:
    """→ (base_url, 来源说明, 被忽略的旧环境变量值)。

    第三项专门给「体检 / 配置总览」用：不警告是因为这条路径被大量 import，
    一次跑批会打印几十遍；但**必须能查得到**，所以做成返回值而不是 print。
    """
    ch = (load_channels().get("runninghub") or {})
    sites = (ch.get("sites") or {})
    cfg_raw = str(ch.get("site") or "").strip()
    cfg_url = ""
    if cfg_raw:
        if cfg_raw.lower() in sites:
            cfg_url = normalize_site((sites[cfg_raw.lower()] or {}).get("url") or cfg_raw)
        else:
            cfg_url = normalize_site(cfg_raw)

    legacy_name, legacy_val = "", ""
    for name in (ch.get("legacy_env") or ["RUNNINGHUB_BASE_URL", "RH_BASE_URL"]):
        v = os.getenv(str(name))
        if v:
            legacy_name, legacy_val = str(name), normalize_site(v)
            break

    if explicit:
        return normalize_site(explicit), "显式参数", ""
    env_site = os.getenv("SOLODRAMA_RH_SITE")
    if env_site:
        return normalize_site(env_site), "环境变量 SOLODRAMA_RH_SITE", ""
    if cfg_url:
        ignored = legacy_val if (legacy_val and legacy_val != cfg_url) else ""
        src = "configs/channels.json"
        if ignored:
            src += "（已忽略过期的 %s=%s）" % (legacy_name, ignored)
        return cfg_url, src, ignored
    if legacy_val:
        return legacy_val, "环境变量 %s（回退：没有 channels.json）" % legacy_name, ""
    return _DEFAULT_SITE, "常量默认", ""


RH_BASE_URL, RH_SITE_SOURCE, RH_SITE_IGNORED = resolve_rh_site()
# ⚠️ 站点必须与账号一致：账号在「国际站」(.ai) 时，上传接口在 .cn 会返回
#    code=1「API Key不存在」（账号类接口两站共用所以能过，唯独上传不行 —— 极易误判成 Key 错）。
#    换站点：`configure.py set-site cn|ai`（写 channels.json），或 SOLODRAMA_RH_SITE=ai 临时覆盖。
# RH币 -> 人民币 折算率。用户 2026-09-18 提供：1 人民币 ≈ 400 RH币。
# 仅用于台账把消耗换算成可比金额，不影响任何提交行为。
RH_CNY_PER_COIN: float = float(os.getenv("RUNNINGHUB_CNY_PER_COIN", "0.0025"))

# 单次 HTTP 请求超时（秒）。下载大文件会用这个值 ×3
HTTP_TIMEOUT: float = 60.0


# ==============================================================================
# [1.5] 图片槽位卫生 —— 防止工作流里的「残留参考图」被当成输入
# ==============================================================================
# 背景（2026-10-22 实测）：RunningHub 提交只发「要改的节点」。工作流里**没有覆盖**
#   的图片槽位不会变空 —— 平台沿用工作流里保存的那张图。实测 H3 工作流有 6 个
#   LoadImage（MiniMaxH3ReferenceToVideo 的 ref_image_0…5），本项目只覆盖 3 个，
#   另外 3 个每镜都在送同一张遗留图 ⇒ 画面被污染（多出不属于本镜的人物/景物），
#   并白吃显存（6 路参考图在 24G 实例上采样阶段必 OOM）。
#
# 处置模式（mode）：
#   blank   默认。上传一张 1024×1024 中性灰图填进未使用槽位（无信息量，最安全）
#   empty   传空字符串。省一次上传，但 ComfyUI 的 LoadImage 可能报 Invalid image file
#   keep    保留工作流默认值。**危险**，必须写 reason；只有确知残留图无害才允许
#
# ★ 2026-11-01（用户要求「必须有开关节点的能力」）——**能力边界必须说清楚**：
#   本地 ComfyUI：真的关。我们手里就是那张图（API 格式的 prompt dict），
#                 按参考图数量删掉多余 LoadImage + 指向它的边 + 孤立上游
#                 （实现见 comfy_ports.prune_for_refs，本地出图/出片两条路都已接上）。
#   RunningHub ：关不了。`nodeInfoList` 是**值覆盖表**，没有任何「禁用节点」语义；
#                 没发的槽位沿用工作流保存值。所以这里只能「顶替」——blank/empty/keep 三选一。
#                 要真正减少槽位，只能改平台侧那份工作流（少接几个 LoadImage）或换工作流。
#                 每次出片 SlotGuard.summary() 会把「实际用几个 / 顶掉几个」打出来，不静默。
#
# discover=True 时每次运行会调一次只读接口拉工作流节点清单，自动找出全部图片槽位
#   （免费、不排队），并把快照落到 <工作区>/slots_*.json 供 --dry-run 用。
# discover=False 时用 slot_ids 手工指定，例如 ["146", "160", "161"]。
#
# value_form：占位图提交成什么形态
#   url       默认。download_url —— 本项目历史 30 集的 char_ref/scene_ref 就是这个形态
#             （见各批次 refs_used.json 的 submitted），是唯一有大批量实证的做法
#   fileName  形如 openapi/<sha256>.png。只给「只认文件名」的工作流用
SLOT_HYGIENE: dict = {
    "mode": "blank",
    "discover": True,
    "slot_ids": [],
    "reason": "",
    "value_form": "url",
}


# ==============================================================================
# [2] 图片模型注册表 —— 「选择香蕉 / GPT / 即梦」就是切换 ACTIVE_IMAGE_PROVIDER
# ==============================================================================
# nodes 里每个键的含义：
#   prompt     必填  分镜提示词（文本）
#   ratio      可选  画幅比例，如 "16:9"
#   char_ref   可选  角色参考图（图生图关键输入）
#   scene_ref  可选  场景参考图（图生图关键输入）
#   image      可选  如果你的工作流只有一个「多图输入」节点，把 char_ref/scene_ref
#                    删掉，改在这里配，代码会把角色图+场景图合并成一个数组塞进去
#
# 每个节点项支持：
#   nodeId     节点 ID（字符串，如 "64"）
#   fieldName  字段名（如 "text" / "image" / "imageUrls"）
#   multi      是否数组型输入（true 时多个值会被序列化成 JSON 数组字符串）
#
IMAGE_PROVIDERS: dict = {
    # ★ 2026-11-01：从「香蕉 / GPT / 即梦」三个空 TODO 收敛为**唯一一条真实通道**。
    #   预配置给的文生图工作流就是这条：Qwen Image 2.1 turbo，纯文生图（工作流里没有 LoadImage）。
    #   旧配置写 active_image_provider = "banana" 仍可用，见下面的别名表。
    "rh_t2i": {
        "label": "RH 文生图 · Qwen 2.1 turbo",
        "kind": "workflow",
        "id": "2113267040969646081",
        "instance_type": "default",
        # False = 该工作流没有图片输入。missing_configs 不再索要 char_ref / scene_ref，
        # 否则「纯文生图」会被判成「没配好」，永远过不了启动检查。
        "image_input": False,
        "unused_slots": dict(SLOT_HYGIENE),
        # 该工作流有 57 个可填节点（含 SeedVR2 二段超分），但**没有任何 LoadImage**，
        # 所以它确实是纯文生图 —— 由 `run.py probe` 实测确认，不是靠命名猜的。
        "nodes": {
            # 已实测：正向提示词是 57 PrimitiveStringMultiline.value。
            # 探针会把它猜成 36 CLIPTextEncode.text（那是**负向词**），必须手写，不能靠猜。
            "prompt": {"nodeId": "57", "fieldName": "value"},
        },
    },
}

# 历史名 → 现名（只做映射，不复制一份配置，避免同一事实两个源）
_IMAGE_PROVIDER_ALIASES = {"banana": "rh_t2i", "gpt_image": "rh_t2i", "jimeng": "rh_t2i"}

ACTIVE_IMAGE_PROVIDER: str = "rh_t2i"


# ==============================================================================
# [2.1] 图像编辑通道（img2img）
# ==============================================================================
# 与 [2] 分开的理由：文生图没有图输入、编辑必须带图，两者的 node 结构不同，
# 塞进同一个字典就得靠 if 分支猜，属于「同一字段表达两件事」——串味的典型来源。
IMAGE_EDIT_PROVIDERS: dict = {
    "rh_edit": {
        "label": "RH 图像编辑 · Qwen 2.1 turbo 图生图",
        "kind": "workflow",
        "id": "2111261410541006850",
        "instance_type": "default",
        "image_input": True,
        "unused_slots": dict(SLOT_HYGIENE),
        # ★ 2026-11-01 由 `run.py probe --kind workflow --id 2111261410541006850` 实测回填。
        #   注意：这条的提示词节点是 **74（CR Prompt Text）**，不是文生图那条的 57，
        #   两条工作流不是同一套图 —— 别照着 t2i 的 id 抄。
        "nodes": {
            "prompt": {"nodeId": "74", "fieldName": "prompt"},
            # 6 个 LoadImage（91 / 177–181）。少于 6 张时，多余槽位复用最后一张，
            # 不循环复用第一张 —— 循环会把同一张脸喂多遍（见 comfy_local_video 同类修正）。
            "load_image": {"value": "fileName", "slots": [
                {"nodeId": "91",  "fieldName": "image"},
                {"nodeId": "177", "fieldName": "image"},
                {"nodeId": "178", "fieldName": "image"},
                {"nodeId": "179", "fieldName": "image"},
                {"nodeId": "180", "fieldName": "image"},
                {"nodeId": "181", "fieldName": "image"},
            ]},
        },
        # 观测值（只读参考，不要当输入发）：
        #   32 KSampler  cfg=1 / steps=25 / denoise=1 / euler
        #   27 ResolutionSelector 2:3 (Portrait Photo) / 1.5MP / multiple 32
        #   95 SaveImage filename_prefix="LQ-"
        #   33 TextEncodeQwenImage21.negative_prompt（负向词）
        "probe_required": False,
    },
}

ACTIVE_IMAGE_EDIT_PROVIDER: str = "rh_edit"


# ==============================================================================
# [4] MiniMax H3 视频工作流
# ==============================================================================
H3: dict = {
    "kind": "workflow",           # 你自己的 H3 工作流 -> workflow
    # ★ 预配置给定的视频工作流（zh 站）。实测：8 步 / 0.8MP / 9:16 / 8~10 秒。
    "id": "2113319585146560513",
    "instance_type": "default",

    # ★ 2026-10-22 新增：未使用图片槽位的处置（见 [1.5]）
    #   本项目只覆盖 char_ref + scene_ref 的槽位；工作流里剩下的 LoadImage 槽位
    #   如果不顶掉，平台会沿用工作流里保存的图（实测 6 个槽只覆盖 3 个）。
    "unused_slots": dict(SLOT_HYGIENE),

    # ★ 2026-11-01 实测回填（工作流 2113319585146560513，已跑通 47 币/9s 段）。
    #   6 个 LoadImage（282–287）**全部登记、按用途分段**，顺序即 <Picture n>：
    #
    #       <Picture 1>      282  board_ref   分镜图（这一镜的构图锚）
    #       <Picture 2–4>  283-285 char_ref    角色（最多 3 人）
    #       <Picture 5–6>  286-287 scene_ref   场景（最多 2 处）
    #
    #   为什么分镜图要排第一（2026-11-01 用户口径）：
    #   只给角色卡与场景卡时，两张图的构图都不是「本镜」的构图，模型每一镜都在重新猜机位，
    #   于是同一个空间在相邻镜头里朝向乱跳。分镜图是**与成片同构的单帧画面**，
    #   和视频同模态，把它放第一张等于把「这一镜长什么样」直接告诉模型。
    #
    #   注意：这不是 2026-10-31 被否掉的「站位图」。站位图是俯视平面线稿，模型会当画面复刻；
    #   分镜图是 9:16 摄影画面，只提供构图与光位，不含任何线稿语义。
    "nodes": {
        "prompt":    {"nodeId": "138", "fieldName": "value"},    # PrimitiveStringMultiline
        "duration":  {"nodeId": "132", "fieldName": "value"},    # PrimitiveFloat（秒）
        "board_ref": {"nodeId": "282", "fieldName": "image"},    # <Picture 1>
        "char_ref":  {"value": "url", "slots": [                 # <Picture 2–4>
            {"nodeId": "283", "fieldName": "image"},
            {"nodeId": "284", "fieldName": "image"},
            {"nodeId": "285", "fieldName": "image"},
        ]},
        "scene_ref": {"value": "url", "slots": [                 # <Picture 5–6>
            {"nodeId": "286", "fieldName": "image"},
            {"nodeId": "287", "fieldName": "image"},
        ]},
        # 说明（勿改）：
        #   163 = INTConstant 采样步数（工作流内已是 8）
        #   115 = ResolutionSelector（已是 9:16 / 0.8MP / multiple 32）
        #   156 = VHS_VideoCombine 输出
        #   参考图提交形态沿用默认 "url"（历史 30 集批量实证），此工作流的 LoadImage 吃 url。
    },
}


# ==============================================================================
# 路径配置
# ==============================================================================
DATA_DIR: str = "data"            # 输入 JSON 目录（相对「工作区」，也可写绝对路径）
OUTPUT_DIR: str = "output"        # 批次输出根目录（相对「工作区」，也可写绝对路径）


# ==============================================================================
# [3.5] 放大通道（RH_Astra · Iris）
# ==============================================================================
# ⚠ 名字要准：这条放大**不是 Topaz**，是 RunningHub 的 RH_Astra + Iris 模型。
#   历史文档按「Topaz 放大工作流」叫过一阵，排查时会被名字带偏。
#
# 节点 4/5 是**短边/长边**，不是宽/高：
#   竖版给 4=1080, 5=1920；给反了（4=1920,5=1080）输出会变成 598×1080。
UPSCALE_PROVIDERS: dict = {
    "rh_astra_iris": {
        "label": "RH 放大 · RH_Astra Iris",
        "kind": "workflow",
        "id": "2110614419863592961",
        "instance_type": "default",
        "nodes": {
            "video_in":   {"nodeId": "2", "fieldName": "file", "value": "fileName"},
            "video_out":  {"nodeId": "3", "fieldName": "filename_prefix"},
            "short_edge": {"nodeId": "4", "fieldName": "value"},
            "long_edge":  {"nodeId": "5", "fieldName": "value"},
            "model":      {"nodeId": "6"},                          # RH_Astra：模型 / 增强强度 / 输入质量
            "cleaner":    {"nodeId": "7", "fieldName": "model_action"},
        },
        "keep_audio": True,          # LoadVideo.keep_audio 必须 true，否则台词丢失
        "target": {"short_edge": 1080, "long_edge": 1920},
        "constraints": [
            "输入必须先转 h264 / yuv420p / 8bit：RH 原始产物是 hevc Main10，服务端 LoadVideo 解不动（805）",
            "提交必须走 /openapi/v2/run/workflow/{id}；v1 legacy 通道同样报 805",
            "输出宽会按源宽高比吸附（672×1216 → 1062×1920），交付前必须 crop-to-fill 归一化到 1080×1920",
            "实测：整集 61 秒一次放大 ≈ 35 币 / 174 秒",
        ],
    },
}
ACTIVE_UPSCALE_PROVIDER: str = "rh_astra_iris"


# ==============================================================================
# 并发与限流  —— ★★★ 不要调高 ★★★
# RunningHub 同一时间最多只能同时执行 5 个任务。
# 该信号量包住「提交 + 轮询直到终态 + 下载」的完整生命周期。
# ==============================================================================
CONCURRENCY_MAX: int = 5          # ★ 硬上限，全局唯一来源（并发不得高于此值）
# ★ 2026-10-21（反馈 10.14 / 11.3）：默认并发从 5 降到 2。
#   实测：标称 ≤5，但真按 5 提交会被拒 —— `errorCode=421 api queue limit reached`
#   （shot_04/06/07 直接失败，失败未计费但要白等一轮）。改 2 后 8/8 零失败，
#   且 `--resume` 不会重复提交已完成的段。要更高并发请显式 `--concurrency 4`，
#   并且记住：421 不是失败，是排队，必须走 `--resume`。
CONCURRENCY: int = 2              # 默认值（上限仍是 CONCURRENCY_MAX）
BATCH_SIZE: int = 20              # 每批处理多少个 shot，批末检查熔断
POLL_INTERVAL: float = 5.0        # 轮询间隔（秒）

# 轮询通道：
#   "v2"     = 只用 POST /openapi/v2/query（本机已验证，推荐，保持默认）
#   "status" = 只用 POST /task/openapi/status（字段名未实测，留给你验证）
#   "auto"   = 优先 v2，结构无法识别时自动降级到 status
POLL_CHANNEL: str = "v2"
IMAGE_TIMEOUT_MIN: float = 15.0   # 单张分镜图任务超时（分钟）
VIDEO_TIMEOUT_MIN: float = 60.0   # 单个 H3 视频任务超时（分钟）


# ==============================================================================
# 失败重试（单任务级）
# ==============================================================================
RETRY_MAX: int = 3
RETRY_BACKOFF: tuple = (5, 15, 45)     # 秒；第 n 次重试前等待 RETRY_BACKOFF[n-1]
ERROR_TEXT_LIMIT: int = 200             # 错误信息截断长度


# ==============================================================================
# 显存不足（OOM）降级重试  ★ 2026-10-20 新增（反馈 P1-13）
# ==============================================================================
# 实测：12 秒镜头 + 6 路参考图 + 0.8MP，在 default(24G) 实例上采样阶段必挂
#   （errorCode 805 / VRAM grow failed / torch.OutOfMemoryError）。
# 平台对 OOM 任务返回 usage=null（**不计费**），所以「换更大实例 / 缩短时长」重试
# 不会多花钱，只会多花时间；而直接判失败会让整镜白等并卡住整集。
OOM_RETRY: bool = True                     # 关掉就退回「OOM 即失败」的旧行为
OOM_ESCALATE_INSTANCE: str = "plus"        # 升到哪个实例类型（平台支持 default/plus）
OOM_SHORTEN_SECONDS: float = 2.0           # 第二级重试时把时长下移几秒（0 = 不降时长）

# 本次运行归属的账号标识（多账号混跑时写进台账，便于按账号回溯重跑；反馈 P0-4）
ACCOUNT: str = os.getenv("SOLODRAMA_ACCOUNT", "")


# ==============================================================================
# 熔断（整批级）
# ==============================================================================
FUSE_CONSECUTIVE_FAILS: int = 5     # 连续失败达到该值 -> 熔断
FUSE_FAIL_RATE: float = 0.5         # 失败率超过该值 -> 熔断
FUSE_MIN_SAMPLES: int = 4           # 至少完成这么多个才参与"失败率"判定，避免早批误熔断


# ==============================================================================
# 裁剪与其它
# ==============================================================================
DEFAULT_CROP: dict = {"rows": 3, "cols": 3}   # shots.json 未写 crop 时的默认值（九宫格）
UPLOAD_CACHE_TTL_HOURS: float = 20.0          # 上传链接 1 天有效，超过该时长则重传（留出安全余量）
KEEP_RAW_ZIP: bool = False                    # 香蕉若回传 zip 包，是否保留原包


def resolve_image_provider(name: str | None = None) -> str:
    """把历史名解析成现名。

    旧项目 config.local.json 里可能还写着 banana / gpt_image / jimeng
    （2026-11-01 之前的三个空 TODO 槽）。这里只做映射，不复制配置 ——
    同一事实只留一个源，别名表是唯一允许的第二处。
    """
    key = str(name if name is not None else ACTIVE_IMAGE_PROVIDER or "").strip()
    if key in IMAGE_PROVIDERS:
        return key
    return _IMAGE_PROVIDER_ALIASES.get(key, key)


def get_active_provider() -> dict:
    """返回当前激活的图片模型配置；顺便做基础校验。"""
    key = resolve_image_provider()
    if key not in IMAGE_PROVIDERS:
        raise KeyError(
            f"ACTIVE_IMAGE_PROVIDER='{ACTIVE_IMAGE_PROVIDER}' 不在 IMAGE_PROVIDERS 里，"
            f"可选：{list(IMAGE_PROVIDERS.keys())}；"
            f"历史别名：{sorted(_IMAGE_PROVIDER_ALIASES)}"
        )
    return IMAGE_PROVIDERS[key]


def get_active_edit_provider() -> dict:
    """当前激活的图像编辑通道（img2img）。"""
    key = str(ACTIVE_IMAGE_EDIT_PROVIDER or "").strip()
    if key not in IMAGE_EDIT_PROVIDERS:
        raise KeyError(
            f"ACTIVE_IMAGE_EDIT_PROVIDER='{key}' 不在 IMAGE_EDIT_PROVIDERS 里，"
            f"可选：{list(IMAGE_EDIT_PROVIDERS.keys())}"
        )
    return IMAGE_EDIT_PROVIDERS[key]


def get_active_upscale_provider() -> dict:
    """当前激活的放大通道。"""
    key = str(ACTIVE_UPSCALE_PROVIDER or "").strip()
    if key not in UPSCALE_PROVIDERS:
        raise KeyError(
            f"ACTIVE_UPSCALE_PROVIDER='{key}' 不在 UPSCALE_PROVIDERS 里，"
            f"可选：{list(UPSCALE_PROVIDERS.keys())}"
        )
    return UPSCALE_PROVIDERS[key]


def _node_ready(spec: Any) -> bool:
    """节点算不算「已配置」。

    两种合法形态都认：
      - 单节点：{"nodeId": "...", "fieldName": "..."}
      - 有序多槽位：{"slots": [{"nodeId": "...", "fieldName": "..."}, ...]}
    """
    if not isinstance(spec, dict):
        return False
    if spec.get("nodeId"):
        return True
    slots = spec.get("slots")
    if isinstance(slots, list):
        return any(isinstance(s, dict) and s.get("nodeId") for s in slots)
    return False


def missing_configs(video_only: bool = False) -> list:
    """返回所有「还没填」的关键配置项，用于启动时友好提示（而不是跑到一半才炸）。

    注意：`first_frame` **不再强制** —— H3 多参模式（--video-only）走的是
    reference generation，提示词 + 有序参考图，不需要首帧图。
    真正必填的是 prompt 与（视频阶段的）参考图槽位。

    注意（2026-09-19 修）：`video_only=True` 时**不再索要 image_providers** ——
    该模式下分镜图整段被跳过（见 pipeline.py `if ctx.video_only:` 分支），
    图片 Provider 对象永远不会被构造，缺它完全不影响出片。
    此前这里无条件索要，于是出现了一个很难发现的矛盾：
      * `--dry-run` 不做这项校验 ⇒ **预演永远绿**；
      * 真实出片才校验 ⇒ **一到花钱那一步才被自己的闸门挡下**（退出码 1、零花费）。
    本项目整条线只用 `--video-only`，所以这个假绿一直是「预演通过但跑不起来」的根因。
    """
    miss = []
    if not RUNNINGHUB_API_KEY:
        miss.append("RUNNINGHUB_API_KEY（环境变量未设置，config.local.json 也没有）")
    if not video_only:
        name = resolve_image_provider()
        prov = IMAGE_PROVIDERS.get(name) or {}
        if not prov.get("id"):
            miss.append(f"image_providers['{name}'].id（图片工作流 ID）")
        pnodes = prov.get("nodes") or {}
        # ★ 2026-11-01：只索要该通道**真有**的节点。
        #   纯文生图（image_input=False）没有 LoadImage，此前无条件索要
        #   char_ref / scene_ref，等于把「配置正确」判成「没配好」，永远过不了启动检查。
        need = ["prompt"] + (["char_ref", "scene_ref"] if prov.get("image_input", True) else [])
        for key in need:
            if not _node_ready(pnodes.get(key)):
                miss.append(f"image_providers['{name}'].nodes.{key}.nodeId")
    if not H3.get("id"):
        miss.append("h3.id（H3 视频工作流 ID）")
    hnodes = H3.get("nodes") or {}
    if not _node_ready(hnodes.get("prompt")):
        miss.append("h3.nodes.prompt.nodeId")
    if not _node_ready(hnodes.get("char_ref")):
        miss.append("h3.nodes.char_ref.nodeId（或 .slots[]，多参模式的参考图槽位）")
    return miss


# ##############################################################################
# 配置分层：<工作区>/config.local.json 覆盖层
# ##############################################################################
OVERLAY_FILENAME = "config.local.json"

# 分阶段布局键：由 `stages/_layout.py` 读取（data_dir / out_dir / assets_dir / layout_version），
# 引擎本身不消费 —— 出现在覆盖层里属**正常**，不报「未知配置项」（反馈 4.2）。
_LAYOUT_KEYS = {"data_dir", "out_dir", "assets_dir", "layout_version", "stages"}

# 允许覆盖的顶层键白名单（含别名映射）
_KEY_ALIASES = {
    "runninghub_api_key": "RUNNINGHUB_API_KEY",
    "runninghub_base_url": "RH_BASE_URL",
    "runninghub_cny_per_coin": "RH_CNY_PER_COIN",
    "http_timeout": "HTTP_TIMEOUT",
    "active_image_provider": "ACTIVE_IMAGE_PROVIDER",
    "image_providers": "IMAGE_PROVIDERS",
    "active_image_edit_provider": "ACTIVE_IMAGE_EDIT_PROVIDER",
    "image_edit_providers": "IMAGE_EDIT_PROVIDERS",
    "active_upscale_provider": "ACTIVE_UPSCALE_PROVIDER",
    "upscale_providers": "UPSCALE_PROVIDERS",
    "h3": "H3",
    "concurrency": "CONCURRENCY",
    "batch_size": "BATCH_SIZE",
    "poll_interval": "POLL_INTERVAL",
    "poll_channel": "POLL_CHANNEL",
    "image_timeout_min": "IMAGE_TIMEOUT_MIN",
    "video_timeout_min": "VIDEO_TIMEOUT_MIN",
    "retry_max": "RETRY_MAX",
    "retry_backoff": "RETRY_BACKOFF",
    "error_text_limit": "ERROR_TEXT_LIMIT",
    "oom_retry": "OOM_RETRY",
    "oom_escalate_instance": "OOM_ESCALATE_INSTANCE",
    "oom_shorten_seconds": "OOM_SHORTEN_SECONDS",
    "account": "ACCOUNT",
    "fuse_consecutive_fails": "FUSE_CONSECUTIVE_FAILS",
    "fuse_fail_rate": "FUSE_FAIL_RATE",
    "fuse_min_samples": "FUSE_MIN_SAMPLES",
    "default_crop": "DEFAULT_CROP",
    "upload_cache_ttl_hours": "UPLOAD_CACHE_TTL_HOURS",
    "keep_raw_zip": "KEEP_RAW_ZIP",
    "data_dir": "DATA_DIR",
    "out_dir": "OUTPUT_DIR",
    "output_dir": "OUTPUT_DIR",
}

# 需要深合并的 dict 键
_DEEP_KEYS = {"IMAGE_PROVIDERS", "IMAGE_EDIT_PROVIDERS", "UPSCALE_PROVIDERS", "H3", "DEFAULT_CROP"}

OVERLAY_WARNINGS: list = []      # apply_overlay 产生的非致命警告（供 doctor / main 打印）


def mask_key(value: str) -> str:
    """API Key 打码展示：rh_****abcd。永不回显完整值。"""
    v = str(value or "")
    if not v:
        return "(空)"
    if len(v) <= 6:
        return "*" * len(v)
    return f"{v[:3]}****{v[-4:]}"


def _deep_merge(base: dict, patch: dict) -> dict:
    """递归合并 patch 到 base 的副本上，返回新 dict（不改 base）。"""
    out = dict(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _warn(msg: str) -> None:
    OVERLAY_WARNINGS.append(msg)


def _shorten(text: str, limit: int = 160) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _validate_nodes(where: str, nodes: Any) -> None:
    """只做结构/类型校验；nodeId / fieldName 为空视为「未配置」，由 missing_configs()
    按「当前激活 provider 的必填项」统一判定，避免可选节点刷屏警告。"""
    if nodes is None:
        return
    if not isinstance(nodes, dict):
        _warn(f"{where}.nodes 应为对象，已忽略该字段")
        return
    for name, node in nodes.items():
        if node is None:
            continue
        if not isinstance(node, dict):
            _warn(f"{where}.nodes.{name} 应为对象，已忽略")
            continue
        for f in ("nodeId", "fieldName"):
            v = node.get(f)
            if v in (None, ""):
                continue                      # 未配置，不算错
            if not isinstance(v, str):
                node[f] = str(v)              # 数字型 nodeId 宽容转字符串
        if "multi" in node and not isinstance(node["multi"], bool):
            _warn(f"{where}.nodes.{name}.multi 应为布尔值，已忽略")
            node.pop("multi", None)


def _validate_slots(where: str, cfg: Any) -> None:
    """校验 unused_slots 段（见 [1.5]）。非法只警告并回退默认，不拦住整个运行。"""
    if cfg is None:
        return
    if not isinstance(cfg, dict):
        _warn(f"{where}.unused_slots 应为对象，已忽略")
        return
    mode = str(cfg.get("mode") or "blank").lower()
    if mode not in ("blank", "empty", "keep"):
        _warn(f"{where}.unused_slots.mode='{cfg.get('mode')}' 非法（blank/empty/keep），"
              "已回退 blank")
        cfg["mode"] = "blank"
    if cfg.get("mode") == "keep" and not str(cfg.get("reason") or "").strip():
        # 不静默放行：保留工作流残留图会把不属于本镜的人物带进画面，
        # 必须写清为什么可以。这里回退 blank 而不是崩掉整批。
        _warn(f"{where}.unused_slots 用了 mode=keep 但没写 reason ——"
              "保留工作流里的残留参考图会污染画面，已回退 blank")
        cfg["mode"] = "blank"
    if "discover" in cfg and not isinstance(cfg["discover"], bool):
        cfg["discover"] = True
    vf = str(cfg.get("value_form") or "url").lower()
    if vf not in ("url", "filename"):
        _warn(f"{where}.unused_slots.value_form='{cfg.get('value_form')}' 非法"
              "（url/fileName），已回退 url")
        vf = "url"
    cfg["value_form"] = vf
    ids = cfg.get("slot_ids")
    if ids is not None and not isinstance(ids, list):
        _warn(f"{where}.unused_slots.slot_ids 应为数组，已忽略")
        cfg["slot_ids"] = []
    elif isinstance(ids, list):
        cfg["slot_ids"] = [str(x).strip() for x in ids
                           if x is not None and str(x).strip()]


def _coerce(key: str, value: Any) -> Any:
    """把 JSON 值转换成 config.py 里对应变量的 Python 类型；非法返回 _INVALID 哨兵。"""
    if key == "RETRY_BACKOFF":
        if isinstance(value, list) and all(isinstance(x, (int, float)) for x in value):
            return tuple(float(x) if isinstance(x, float) else int(x) for x in value)
        return _INVALID
    if key in ("CONCURRENCY", "BATCH_SIZE", "RETRY_MAX", "ERROR_TEXT_LIMIT",
               "FUSE_CONSECUTIVE_FAILS", "FUSE_MIN_SAMPLES"):
        if isinstance(value, bool) or not isinstance(value, int):
            return _INVALID
        return value
    if key in ("HTTP_TIMEOUT", "POLL_INTERVAL", "IMAGE_TIMEOUT_MIN", "VIDEO_TIMEOUT_MIN",
               "UPLOAD_CACHE_TTL_HOURS", "OOM_SHORTEN_SECONDS"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return _INVALID
        return float(value)
    if key in ("FUSE_FAIL_RATE",):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return _INVALID
        return float(value)
    if key in ("KEEP_RAW_ZIP", "OOM_RETRY"):
        if not isinstance(value, bool):
            return _INVALID
        return value
    if key in ("RUNNINGHUB_API_KEY", "RH_BASE_URL", "ACTIVE_IMAGE_PROVIDER",
               "POLL_CHANNEL", "DATA_DIR", "OUTPUT_DIR", "OOM_ESCALATE_INSTANCE", "ACCOUNT"):
        if not isinstance(value, str):
            return _INVALID
        return value
    return value


class _Invalid:
    pass


_INVALID = _Invalid()


def apply_overlay(path) -> list:
    """读取 <工作区>/config.local.json 并覆盖本模块的配置常量。

    - 白名单之外的顶层键：警告并忽略（不崩溃、不静默）
    - 以下划线开头的键：注释约定，直接忽略
    - concurrency 超过 CONCURRENCY_MAX：自动收敛并警告
    - runninghub_api_key：仅在环境变量未设置时生效（环境变量优先）
    - 返回警告列表（同时存入 OVERLAY_WARNINGS）
    """
    del OVERLAY_WARNINGS[:]
    p = Path(path)
    if not p.is_file():
        return OVERLAY_WARNINGS
    try:
        raw = json.loads(p.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError) as e:
        _warn(f"{p.name} 无法解析，已忽略该覆盖层: {_shorten(str(e), 120)}")
        return OVERLAY_WARNINGS
    if not isinstance(raw, dict):
        _warn(f"{p.name} 顶层应为 JSON 对象，已忽略该覆盖层")
        return OVERLAY_WARNINGS

    for key, value in raw.items():
        if key.startswith("_"):
            continue
        # ★ 2026-10-21（反馈 4.2）：布局键由 `stages/_layout.py` 解析，引擎不消费 ——
        #   此前每跑一次 preflight 都报 `[WARN] 未知配置项 'assets_dir'，已忽略`，
        #   而总纲 §3.7 明确说解析链包含它。文档说有、代码说不认识，接手者会以为配置没生效。
        if key in _LAYOUT_KEYS:
            continue
        target = _KEY_ALIASES.get(key)
        if target is None:
            _warn(f"{p.name}: 未知配置项 '{key}'，已忽略（白名单见 references/config-layers.md）")
            continue

        coerced = _coerce(target, value)
        if coerced is _INVALID:
            _warn(f"{p.name}: '{key}' 类型不符（期望 {_TYPE_HINT.get(target, '标量')}），已忽略")
            continue

        if target == "CONCURRENCY":
            if coerced > CONCURRENCY_MAX:
                _warn(f"{p.name}: concurrency={coerced} 超过上限 {CONCURRENCY_MAX}，已收敛为 {CONCURRENCY_MAX}")
                coerced = CONCURRENCY_MAX
        elif target == "POLL_CHANNEL":
            if coerced not in ("v2", "status", "auto"):
                _warn(f"{p.name}: poll_channel='{coerced}' 非法（可选 v2/status/auto），已忽略")
                continue
        elif target == "ACTIVE_IMAGE_PROVIDER":
            if coerced not in IMAGE_PROVIDERS:
                _warn(f"{p.name}: active_image_provider='{coerced}' 不在注册表里"
                      f"（可选 {list(IMAGE_PROVIDERS.keys())}），已忽略")
                continue
        elif target in _DEEP_KEYS:
            if not isinstance(coerced, dict):
                _warn(f"{p.name}: '{key}' 应为对象，已忽略")
                continue
            coerced = _deep_merge(globals()[target], coerced)
            if target == "IMAGE_PROVIDERS":
                for pname, pcfg in coerced.items():
                    if not isinstance(pcfg, dict):
                        continue
                    if pcfg.get("kind") not in (None, "workflow", "ai-app"):
                        _warn(f"image_providers.{pname}.kind='{pcfg.get('kind')}' 非法"
                              "（可选 workflow/ai-app），已忽略该字段")
                        pcfg.pop("kind", None)
                    _validate_nodes(f"image_providers.{pname}", pcfg.get("nodes"))
                    _validate_slots(f"image_providers.{pname}", pcfg.get("unused_slots"))
            elif target == "H3":
                if coerced.get("kind") not in (None, "workflow", "ai-app"):
                    _warn(f"h3.kind='{coerced.get('kind')}' 非法（可选 workflow/ai-app），已忽略该字段")
                    coerced.pop("kind", None)
                # frame_source（九宫格裁哪一格当首帧）已于 2026-11-01 随九宫格链下线。
                # 旧覆盖层里残留这个键不报错，只忽略 —— 免得老项目升级时被一条无意义告警打断。
                if coerced.pop("frame_source", None) is not None:
                    _warn("h3.frame_source 已废弃（九宫格链已下线），该键被忽略")
                _validate_nodes("h3", coerced.get("nodes"))
                _validate_slots("h3", coerced.get("unused_slots"))
        elif target == "RUNNINGHUB_API_KEY":
            if os.getenv("RUNNINGHUB_API_KEY"):
                _warn(f"{p.name}: 已设置环境变量 RUNNINGHUB_API_KEY，文件里的 key 已被忽略（环境变量优先）")
                continue

        globals()[target] = coerced
    return OVERLAY_WARNINGS


_TYPE_HINT = {
    "CONCURRENCY": "整数", "BATCH_SIZE": "整数", "RETRY_MAX": "整数",
    "ERROR_TEXT_LIMIT": "整数", "FUSE_CONSECUTIVE_FAILS": "整数",
    "FUSE_MIN_SAMPLES": "整数", "HTTP_TIMEOUT": "数字", "POLL_INTERVAL": "数字",
    "IMAGE_TIMEOUT_MIN": "数字", "VIDEO_TIMEOUT_MIN": "数字",
    "UPLOAD_CACHE_TTL_HOURS": "数字", "FUSE_FAIL_RATE": "0~1 之间的小数",
    "RETRY_BACKOFF": "数字数组，如 [5, 15, 45]", "KEEP_RAW_ZIP": "true/false",
    "OOM_RETRY": "true/false", "OOM_ESCALATE_INSTANCE": "字符串（如 plus）",
    "OOM_SHORTEN_SECONDS": "数字（秒）", "ACCOUNT": "字符串（账号标识）",
    "RUNNINGHUB_API_KEY": "字符串", "RH_BASE_URL": "字符串",
    "RH_CNY_PER_COIN": "数字（1 RH币 = ? 人民币，默认 0.0025）",
    "ACTIVE_IMAGE_PROVIDER": "字符串", "POLL_CHANNEL": "v2 | status | auto",
    "DATA_DIR": "字符串", "OUTPUT_DIR": "字符串",
    "IMAGE_PROVIDERS": "对象", "H3": "对象", "DEFAULT_CROP": "对象 {rows, cols}",
}
