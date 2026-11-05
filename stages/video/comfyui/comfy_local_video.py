#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""comfy_local_video.py —— 用**本机 ComfyUI** 出视频（H3 图生视频，￥0）

工作流怎么设定（三层，改哪层都行）
----------------------------------
1. **工作流 JSON**：默认 `stages/video/comfyui/workflow_h3_multiref6.json`
   （「minimax 多参一采 · 6 参考图 + 4 步 LoRA」，2026-11-01 起）。原件与替换说明见
   `workflows_src/h3_multiref6_raw.json` 与同名 `.map.json` 的 `_substitutions`。
   要换就换文件，或 `--workflow <路径>`，或环境变量 `COMFYUI_VIDEO_WORKFLOW`；
   旧的 4 步单图版仍在 `workflow_h3_local.json`，可随时切回。**不需要上传到 ComfyUI**：这两份文件是 ComfyUI 的
   "API 格式" JSON，由本脚本直接 POST 给 `/prompt`。
2. **节点映射**：默认读**同名 sidecar** `workflow_h3_local.map.json`
   （约定：`<工作流文件名去掉 .json>.map.json`）。换一份工作流时，把映射文件放在它旁边
   同名前缀即可，**不用改代码**。优先级：`--map` > sidecar > 环境变量 > 内置默认。
3. **单次覆盖**：`--steps / --seconds / --mp / --aspect / --seed` 只影响这一次；
   不传就**沿用工作流里的原值**（不覆盖别人调好的 0.6MP / 16:9）。

换工作流的标准动作（4 步）
--------------------------
    # ① 看清这份工作流里都有哪些节点（离线，不连 ComfyUI）
    python comfy_local_video.py --workflow 新工作流.json --list-nodes
    # ② 照着输出写一份 新工作流.map.json（或复制旧的改 id）
    # ③ 离线校验映射对不对（节点在不在、类型对不对）
    python comfy_local_video.py --workflow 新工作流.json --map-check
    # ④ 在线体检（ComfyUI 在线 + 节点类 + 模型文件），再真跑一条短的
    python comfy_local_video.py --workflow 新工作流.json --check

为什么要有 `--map-check`：第三方节点**随版本变签名**（本机 `SolAttnMiniMax` 就比云端
版本多一个必填 `selection`），`--check` 只能查「节点存不存在」，签名兼容性只能真跑才发现；
但「映射写错节点 id」是能提前 100% 抓出来的，那是最常见的错。

用法
----
    python comfy_local_video.py --check
    python comfy_local_video.py --prompt "..." --ref a.png --out out/
    python comfy_local_video.py --prompt "..." --ref a.png --out out/ --submit

远端（云端镜像实例）怎么用
--------------------------
    set SOLODRAMA_TRUSTED_HOSTS=*.container.x-gpu.com    ← 守卫要认这个域名（见 _netguard）
    set COMFYUI_URL=https://<实例ID>-8188.container.x-gpu.com
    python comfy_local_video.py --check                              ← 先过就绪三查（版本/节点/模型）
    python comfy_local_video.py --prompt "..." --ref a.png --out out/ --submit

三处差异自动生效：超时 30 分钟（`SOLODRAMA_VIDEO_TIMEOUT_MIN` 可覆盖）、提交前 `/free`、
产物下载带 Range 续传。本机默认值不变，回滚只需把 `COMFYUI_URL` 改回 127.0.0.1。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

# 同目录模块：端口识别 / 槽位裁剪（引擎侧唯一实现，见 comfy_ports.py 顶部说明）
try:
    from comfy_ports import (describe as ports_describe, prune_for_refs,
                             missing_required_inputs)
except ImportError:                                      # 缺了就降级：不裁也不报错
    ports_describe = None
    prune_for_refs = None
    missing_required_inputs = None

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
# ★ 2026-11-04：HTTP 全部走共享层 `stages/_comfy_http.py`（重试 / 错误分类 / 原子下载）。
#   原来这个文件自己写了一版 urllib 调用，零重试 —— 8G 卡长任务偶发 ConnectionReset
#   就作废一整镜（5–10 分钟）。两套实现还会让「ComfyUI 没开」在两处显示成两种原因。
def _load_comfy_http():
    import importlib.util as _ilu
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, "..", "..", "_comfy_http.py"),
                 os.path.join(here, "..", "..", "..", "stages", "_comfy_http.py")):
        cand = os.path.normpath(cand)
        if os.path.isfile(cand):
            spec = _ilu.spec_from_file_location("_comfy_http", cand)
            mod = _ilu.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    raise SystemExit("[FAIL] 找不到 stages/_comfy_http.py（HTTP 共享层）")


Q = _load_comfy_http()
COMFY = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")

# ★ 2026-11-05：这个脚本不只跑本机了。`COMFYUI_URL` 指向云端镜像实例时，它就是
#   「远程执行器」—— 门禁侧 `model_gate` 的 `video=cloud_comfyui` 指向本文件。
#   与本地只有三处差别：超时档位、提交前释放显存、产物下载允许续传（见 _comfy_http）。

# 单段轮询超时（分钟）。
#   · 本地按实测给：RTX 4060 8G / H3 8 步 / 0.8MP，单段 **5–10 分钟**（docs/orchestration/
#     标准作业流程.md），所以留 20 分钟（含冷加载 offload 的抖动）。
#   · 远端按「本地 × 1.5」：多一层网络与排队，但卡通常更快。**不是**把本地压到 3 分钟 ——
#     那样本地长段会被判超时，属于用新功能换旧回归。
TIMEOUT_MIN_LOCAL = 20.0
TIMEOUT_MIN_REMOTE = 30.0


def _is_loopback(url: str) -> bool:
    """这个地址是不是本机？只认 loopback 字面量 —— 内网 IP 也算远端（走网络、会排队）。"""
    h = (urllib.parse.urlsplit(url or "").hostname or "").strip().lower()
    return h in ("127.0.0.1", "localhost", "::1", "0.0.0.0", "")


def _default_timeout_min() -> float:
    """超时默认值：环境变量 > 链路类型（远端放宽 50%）。"""
    env = (os.environ.get("SOLODRAMA_VIDEO_TIMEOUT_MIN") or "").strip()
    if env:
        try:
            v = float(env)
            if v > 0:
                return v
        except ValueError:
            print("  [WARN] SOLODRAMA_VIDEO_TIMEOUT_MIN=%r 不是数字，改用自动档" % env)
    return TIMEOUT_MIN_LOCAL if _is_loopback(COMFY) else TIMEOUT_MIN_REMOTE


# ---------------------------------------------------------------------------
#   这里不是「删掉调用点」，而是把出站通道收窄到本机/内网。任何试图连
#   某次合并里被悄悄加回来的 httpx 调用。细则见 stages/_netguard.py。
# ---------------------------------------------------------------------------
def _boot_netguard() -> None:
    import pathlib as _pl
    import sys as _sys
    for _p in _pl.Path(__file__).resolve().parents[:5]:
        for _cand in ((_p / "_netguard.py"), (_p / "stages" / "_netguard.py")):
            if _cand.is_file():
                if str(_cand.parent) not in _sys.path:
                    _sys.path.insert(0, str(_cand.parent))
                try:
                    import importlib as _il
                    _il.import_module("_netguard").install()
                except Exception:        # noqa: BLE001 —— 守卫自身异常不能拖垮主流程
                    pass
                return


_boot_netguard()
# ★ 2026-11-04：默认工作流换成 Owner 指定的「Minimax+H3 无损融合单采（满血 API 画布级）」。
#   它是界面格式，由 `workflow_ui2api.py` 转成这里的 API 格式（64 → 30 节点），
#   映射与两处断链修补见同名 sidecar `workflow_h3_minimax_canvas.map.json`。
#   旧的 `workflow_h3_multiref6.json` 仍在，`--workflow` 可随时切回。
DEFAULT_WORKFLOW = os.environ.get(
    "COMFYUI_VIDEO_WORKFLOW", os.path.join(HERE, "workflow_h3_minimax_canvas.json"))

# ---------------------------------------------------------------------------
# 节点映射的角色表
# ---------------------------------------------------------------------------
# `expect` 只用于 --map-check 的**类型提醒**：同角色常有多个等价节点（如种子既可以是
# Seed (rgthree) 也可以是 RandomNoise），所以按「允许集合」判定，不做唯一绑定。
MAP_ROLES = {
    "prompt":  {"env": "COMFYUI_VIDEO_NODE_PROMPT",  "default": "30",
                "hint": "提示词（多行字符串）",
                "expect": ("PrimitiveStringMultiline", "PrimitiveString", "String Literal")},
    "images":  {"env": "COMFYUI_VIDEO_NODE_IMAGES",  "default": "24",
                "hint": "参考图（加载图像）。多参工作流可能不止一个槽位，用逗号分隔",
                "expect": ("LoadImage", "LoadImageMask")},
    "seconds": {"env": "COMFYUI_VIDEO_NODE_SECONDS", "default": "15",
                "hint": "时长秒数（浮点），下游用 17n+5 公式换算帧数",
                "expect": ("PrimitiveFloat", "PrimitiveInt", "INTConstant", "Float")},
    "steps":   {"env": "COMFYUI_VIDEO_NODE_STEPS",   "default": "9",
                "hint": "采样步数（4 步 turbo LoRA 就填 4）",
                "expect": ("BasicScheduler", "KSampler", "KSamplerAdvanced")},
    "seed":    {"env": "COMFYUI_VIDEO_NODE_SEED",    "default": "10",
                "hint": "种子",
                "expect": ("Seed (rgthree)", "RandomNoise", "PrimitiveInt", "INTConstant")},
    "aspect":  {"env": "COMFYUI_VIDEO_NODE_ASPECT",  "default": "14",
                "hint": "分辨率：aspect_ratio + megapixels",
                "expect": ("ResolutionSelector", "EmptyLatentImage", "EmptyMiniMaxH3LatentAV")},
    "prefix":  {"env": "COMFYUI_VIDEO_NODE_PREFIX",  "default": "4",
                "hint": "产物文件名前缀（保存视频节点）",
                "expect": ("SaveVideo", "VHS_VideoCombine", "SaveAnimatedWEBP", "SaveWEBM")},
}
MAP_KEYS = ("prompt", "images", "seconds", "steps", "seed", "aspect", "prefix")


def sidecar_for(workflow_path: str) -> str:
    """约定：`xxx.json` 的映射放 `xxx.map.json`（同目录）。"""
    p = str(workflow_path or DEFAULT_WORKFLOW)
    base = p[:-5] if p.lower().endswith(".json") else p
    return base + ".map.json"


def _builtin_map() -> dict:
    out = {}
    for role, spec in MAP_ROLES.items():
        raw = os.environ.get(spec["env"], spec["default"])
        out[role] = [x.strip() for x in raw.split(",") if x.strip()] if role == "images" else raw
    return out


def load_map(workflow_path: str, map_path: str = "") -> tuple:
    """返回 (映射, 来源说明)。优先级：--map > sidecar > 内置(含环境变量)。"""
    cand = []
    if map_path:
        cand.append((map_path, "命令行 --map"))
    # 与 load_workflow 同一条基准：只给文件名时按本目录找 sidecar，
    # 否则「同目录有 .map.json」这件事会因为工作目录不同而失效（映射悄悄退回内置默认）。
    wf_abs = workflow_path
    if workflow_path and not os.path.isabs(workflow_path) and not os.path.exists(workflow_path):
        here = os.path.join(os.path.dirname(os.path.abspath(__file__)), workflow_path)
        if os.path.exists(here):
            wf_abs = here
    sc = sidecar_for(wf_abs)
    if os.path.isfile(sc):
        cand.append((sc, "同名 sidecar"))
    for path, why in cand:
        try:
            with open(path, encoding="utf-8-sig") as fh:
                d = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            raise SystemExit("[FAIL] 读不了映射文件 %s（%s）" % (path, type(exc).__name__))
        if not isinstance(d, dict):
            raise SystemExit("[FAIL] 映射文件必须是对象：%s" % path)
        # 允许只写部分 role，其余落回内置
        base = _builtin_map()
        base.update({k: v for k, v in d.items() if k in MAP_KEYS})
        # ★ 2026-11-04：`_rewire` 是「连线修补」段，不属于角色映射，单独透传。
        #   为什么需要：从 ComfyUI 界面格式转来的工作流常带**静默断链** ——
        #   画布上看着连着，实际 SetNode 的输入是空的，于是「秒数」根本没接到
        #   `length`（帧数）上，改成 5 秒仍然出 10 秒。这类断链不报错、不改就永远发现不了。
        if isinstance(d.get("_rewire"), dict):
            base["_rewire"] = d["_rewire"]
        if isinstance(d.get("_substitute"), dict):
            base["_substitute"] = d["_substitute"]
        return base, "%s（%s）" % (path, why)
    env_used = any(os.environ.get(s["env"]) for s in MAP_ROLES.values())
    return _builtin_map(), ("环境变量 COMFYUI_VIDEO_NODE_*" if env_used else "脚本内置默认")


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def http_json(url: str, payload=None, timeout=30, retries: int = 3):
    """兼容旧调用点：把完整 URL 拆成 path 交给共享层（重试/分类都在那里）。

    ★ POST 默认 `retries=0`：重发 `/prompt` 会真的再出一遍视频。
      GET（history / queue / object_info）默认重试 3 次，抖动自己吸收掉。
    """
    if url.startswith(COMFY):
        path = url[len(COMFY):] or "/"
    else:
        path = url
    if payload is None:
        return Q.get_json(path, timeout=timeout, retries=retries, tag=path)
    return Q.post_json(path, payload, timeout=timeout, retries=retries, tag=path)


def upload_image(path: str) -> str:
    """把参考图塞进 ComfyUI 的 input 目录，返回 LoadImage 可用的名字。"""
    boundary = "----solodrama" + uuid.uuid4().hex
    name = os.path.basename(path)
    with open(path, "rb") as fh:
        blob = fh.read()
    body = b"".join([
        ("--%s\r\n" % boundary).encode(),
        ('Content-Disposition: form-data; name="image"; filename="%s"\r\n' % name).encode("utf-8"),
        b"Content-Type: application/octet-stream\r\n\r\n", blob, b"\r\n",
        ("--%s\r\n" % boundary).encode(),
        b'Content-Disposition: form-data; name="overwrite"\r\n\r\ntrue\r\n',
        ("--%s--\r\n" % boundary).encode(),
    ])
    # 上传可重试（同一张图重复上传只是覆盖，不会产生副作用）
    d = Q.post_multipart("/upload/image", body, boundary, timeout=180, tag="upload")
    return d.get("name") or name


# ---------------------------------------------------------------------------
# 工作流 + 映射
# ---------------------------------------------------------------------------
MODEL_NODES = {
    "UNETLoader": "unet_name",
    "CLIPLoader": "clip_name",
    "VAELoader": "vae_name",
    "LoraLoaderModelOnly": "lora_name",
    "LoraLoaderBypassModelOnly": "lora_name",
}


def load_workflow(path: str = "") -> dict:
    p = path or DEFAULT_WORKFLOW
    # ★ 只给文件名时按**本目录**解析：用户（和界面输入框）习惯写 `workflow_h3_local.json`，
    #   而命令行的工作目录未必是这里 —— 直接 open 会报 FileNotFoundError，
    #   看起来像「替代工作流不存在」，其实只是相对路径的基准不同。
    if path and not os.path.isabs(p) and not os.path.exists(p):
        cand = os.path.join(os.path.dirname(os.path.abspath(__file__)), p)
        if os.path.exists(cand):
            p = cand
    with open(p, encoding="utf-8") as fh:
        wf = json.load(fh)
    # ★ 必须整份都是 API 格式（每个值都是带 class_type 的节点）。只查顶层 dict 是不够的：
    #   ComfyUI 界面导出的 workflow 是 {"nodes": [...], "links": [...]}，同样是 dict，
    #   放过去会在后面报一堆「节点 id 不存在」，把人引到映射上 —— 真因是导出方式错了。
    if (not isinstance(wf, dict) or not wf
            or any(not isinstance(v, dict) or "class_type" not in v for v in wf.values())):
        raise SystemExit("[FAIL] 工作流必须是 API 格式（{nodeId: {class_type, inputs}}），"
                         "不是 ComfyUI 界面导出的 workflow（那种带 nodes/links 数组，"
                         "需要在 ComfyUI 里用「导出 API 格式」再存一份）")
    return wf


def list_nodes(workflow_path: str = "") -> int:
    """列出工作流里的节点，并给出「这个节点适合当什么角色」的建议。离线，不连 ComfyUI。"""
    wf = load_workflow(workflow_path)
    m, src = load_map(workflow_path)
    used = {}
    for role, v in m.items():
        for nid in (v if isinstance(v, list) else [v]):
            used[str(nid)] = role
    print("工作流: %s（%d 节点）" % (workflow_path or DEFAULT_WORKFLOW, len(wf)))
    print("映射  : %s" % src)
    print()
    print("%-5s %-42s %-11s %s" % ("id", "class_type", "当前角色", "可选参数"))
    for nid in sorted(wf, key=lambda x: int(x) if str(x).isdigit() else 9999):
        node = wf[nid]
        cls = node.get("class_type")
        plain = [k for k, v in (node.get("inputs") or {}).items() if not isinstance(v, (list, dict))]
        role = used.get(str(nid), "")
        if not role:
            for r, spec in MAP_ROLES.items():
                if cls in spec["expect"]:
                    role = "（可作 %s）" % r
                    break
        print("%-5s %-42s %-11s %s" % (nid, cls, role, ", ".join(plain[:6])))
    print("\n把上面合适的 id 写进映射文件：")
    print("  %s" % sidecar_for(workflow_path))
    print('  {"prompt": "30", "images": ["24"], "seconds": "15", "steps": "9",'
          ' "seed": "10", "aspect": "14", "prefix": "4"}')
    return 0


def list_ports(workflow_path: str = "") -> int:
    """离线列端口：这个工作流能喂哪些值、最多接几张参考图、产物从哪出来。"""
    if ports_describe is None:
        print("[FAIL] 同目录缺少 comfy_ports.py，无法识别端口")
        return 2
    wf = load_workflow(workflow_path)
    d = ports_describe(wf)
    ROLE_CN = {"image": "参考图", "prompt": "提示词", "text": "文本编码", "steps": "步数",
               "seed": "种子", "aspect": "画幅", "megapixels": "百万像素",
               "seconds": "时长", "int": "整数", "filename": "文件名前缀"}
    print("工作流  : %s（%d 个节点）" % (workflow_path or DEFAULT_WORKFLOW, d["node_count"]))
    print("参考图  : 最多 %d 个槽（加载器节点 %s）"
          % (d["capacity"], "、".join(d["slots"]) or "无"))
    print("输出节点: %s" % ("、".join(d["outputs"]) or "未识别到（可能是纯计算图）"))
    if d["unreachable"]:
        print("不可达  : %s（不会被 ComfyUI 执行，可删）" % "、".join(d["unreachable"]))
    print()
    print("%-5s %-34s %-12s %-8s %s" % ("id", "class_type", "字段", "角色", "当前值"))
    for p in d["ports"]:
        print("%-5s %-34s %-12s %-8s %s"
              % (p["node"], str(p["class_type"])[:32], p["field"],
                 ROLE_CN.get(p["role"], p["role"]), str(p["value"])[:44]))
    if d["groups"]:
        print()
        print("多槽节点（会按参考图数量自动关掉多余的）：")
        for g in d["groups"]:
            print("  %s %s：%s" % (g["node"], g["class_type"], "、".join(g["fields"])))
    print()
    print("提交时按 --ref 的张数裁剪；想先看裁完的样子：--list-ports 之后直接 --submit 会打印裁剪结果。")
    return 0


def map_check(workflow_path: str = "", map_path: str = "") -> int:
    """离线校验映射：节点在不在、类型对不对。**不连 ComfyUI、不占 GPU。**"""
    wf = load_workflow(workflow_path)
    m, src = load_map(workflow_path, map_path)
    print("工作流: %s（%d 节点）" % (workflow_path or DEFAULT_WORKFLOW, len(wf)))
    print("映射  : %s" % src)
    print()
    bad = 0
    for role in MAP_KEYS:
        spec = MAP_ROLES[role]
        raw = m.get(role)
        ids = raw if isinstance(raw, list) else [raw]
        ids = [str(x) for x in ids if str(x).strip()]
        if not ids:
            print("  [NG] %-8s 未配置" % role)
            bad += 1
            continue
        for nid in ids:
            node = wf.get(nid)
            if not node:
                print("  [NG] %-8s #%s 在工作流里不存在（%s）" % (role, nid, spec["hint"]))
                bad += 1
                continue
            cls = node.get("class_type")
            ok = cls in spec["expect"]
            print("  %s %-8s #%-4s %-38s %s" % ("[OK]" if ok else "[? ]", role, nid, cls,
                                               "" if ok else "（预期 %s 之一，仍可继续但请确认）"
                                               % "/".join(spec["expect"])))
    print()
    if bad:
        print("[FAIL] 有 %d 处必须修（节点 id 对不上，提交后参数不会生效）" % bad)
        return 2
    print("[OK] 映射可用。下一步：--check（在线体检节点类与模型文件），再 --submit 真跑一条短的。")
    return 0


# ---------------------------------------------------------------------------
# 在线体检
# ---------------------------------------------------------------------------
def check(workflow_path: str = "", map_path: str = "") -> int:
    print("ComfyUI : %s" % COMFY)
    try:
        st = http_json(COMFY + "/system_stats", timeout=10)
    except Exception as exc:  # noqa: BLE001
        print("[FAIL] 连不上 ComfyUI（%s）：先在 ComfyUI Desktop 里启动 8188 端口" % type(exc).__name__)
        return 2
    dev = (st.get("devices") or [{}])[0]
    vram = int(dev.get("vram_free") or 0) / (1024 ** 3)
    print("版本    : %s ｜ GPU %s ｜ 空闲 %.1fG" % (
        (st.get("system") or {}).get("comfyui_version"), dev.get("name") or "?", vram))

    wf = load_workflow(workflow_path)
    m, src = load_map(workflow_path, map_path)
    # ★ 体检的口径必须与真跑一致（模型替换 / 连线修补都要先应用），
    #   否则会报一堆「缺模型」而实际能跑，告警就失去信用。
    wf = apply_map_patches(json.loads(json.dumps(wf)), m)
    print("工作流  : %s（%d 节点）" % (workflow_path or DEFAULT_WORKFLOW, len(wf)))
    print("映射    : %s" % src)

    oi = http_json(COMFY + "/object_info", timeout=60)
    miss_cls = sorted({v.get("class_type") for v in wf.values()} - set(oi))
    if miss_cls:
        print("[FAIL] 缺自定义节点：%s" % "、".join(miss_cls))
    else:
        print("[OK] 节点类齐全（%d 个 class_type 全部可用）"
              % len({v.get("class_type") for v in wf.values()}))

    # ★ 2026-11-01：连线缺失也要拦。节点类齐全 + 模型齐全 ≠ 能跑 ——
    #   `VAEDecodeAudio` 少了必需的 `vae` 输入时，前两项全绿、一提交就 400。
    #   这是换工作流（尤其别人导出的）时最高频的坑，必须在体检阶段拦下来。
    if missing_required_inputs is not None:
        miss_in = missing_required_inputs(wf, oi)
        if miss_in:
            print("[FAIL] 以下节点缺必需输入（提交必 400）：")
            for nid, cls, fields in miss_in[:12]:
                print("   - 节点 %s(%s) 缺：%s" % (nid, cls, "、".join(fields)))
            print("   修法：在 ComfyUI 里把该端口接上再重新「导出（API）」。")
            return 2
        print("[OK] 必需输入齐全（%d 个节点逐个核对）" % len(wf))

    miss_models = []
    for nid, node in wf.items():
        cls = node.get("class_type")
        field = MODEL_NODES.get(cls)
        if not field:
            continue
        want = (node.get("inputs") or {}).get(field)
        if not want:
            continue
        node_key = {"unet_name": "UNETLoader", "clip_name": "CLIPLoader",
                    "vae_name": "VAELoader", "lora_name": "LoraLoaderModelOnly"}[field]
        try:
            have = oi[node_key]["input"]["required"][field][0]
        except Exception:  # noqa: BLE001
            have = []
        if want not in have:
            miss_models.append("#%s %s = %s" % (nid, cls, want))
    if miss_models:
        print("[FAIL] 缺模型文件：")
        for mm in miss_models:
            print("       %s" % mm)
    else:
        print("[OK] 模型文件齐全（unet / clip / vae / lora 逐项核对）")

    # 映射的节点 id 也顺手核一遍（离线逻辑复用）
    map_bad = 0
    for role in MAP_KEYS:
        raw = m.get(role)
        for nid in (raw if isinstance(raw, list) else [raw]):
            if str(nid).strip() and str(nid) not in wf:
                print("[FAIL] 映射 %s 指向 #%s，但工作流里没有这个节点" % (role, nid))
                map_bad += 1

    ok = not miss_cls and not miss_models and not map_bad
    print("\n%s" % ("可以提交（--submit 会真的占 GPU 出片）" if ok else "先补齐上面的缺失项"))
    return 0 if ok else 2


# ---------------------------------------------------------------------------
# 覆盖槽位
# ---------------------------------------------------------------------------
def frames_for(seconds: float) -> int:
    """H3 帧数约束：length = 17n + 5（与工作流里 ComfyMathExpression 的公式同源）。"""
    n = max(5, round(float(seconds) * 24))
    return n + (5 - (n % 17)) % 17


def _roles(m: dict, role: str) -> list:
    raw = m.get(role)
    return [str(x) for x in (raw if isinstance(raw, list) else [raw]) if str(x).strip()]


def apply_map_patches(wf: dict, m: dict) -> dict:
    """把 map 里的「模型替换」与「连线修补」应用到工作流（原地改，调用方负责深拷贝）。

    ★ 2026-11-04：这两件事必须在**体检和真跑两处用同一份逻辑**。
      此前只有真跑应用替换，体检读的是原始工作流 —— 于是体检报「缺模型」，
      而实际跑起来是通的，人就会去删那三条告警，然后真的缺模型时也不管了。
    """
    for tid, patch in (m.get("_substitute") or {}).items():
        if tid not in wf or not isinstance(patch, dict):
            continue
        ins = wf[tid].setdefault("inputs", {})
        for k, v in patch.items():
            if k in ins:
                ins[k] = v
    for tid, patch in (m.get("_rewire") or {}).items():
        if tid not in wf or not isinstance(patch, dict):
            continue
        ins = wf[tid].setdefault("inputs", {})
        for inp, val in patch.items():
            ins[inp] = val
    return wf


def apply_nodes(wf: dict, m: dict, *, prompt: str, ref_names: list, seconds, steps: int,
                seed: int, aspect: str, mp, prefix: str) -> dict:
    wf = json.loads(json.dumps(wf))          # 深拷贝，避免污染模板

    apply_map_patches(wf, m)

    ids = _roles(m, "prompt")
    if ids and ids[0] in wf:
        wf[ids[0]]["inputs"]["value"] = prompt

    # 参考图按序铺到每个 LoadImage 槽位。
    # ★ 不能只看映射里的 images：裁剪/换工作流后映射可能是旧的，没列到的加载器会带着
    #   模板里的占位文件名提交 → ComfyUI 报「image not found」，而报错看起来像工作流坏了。
    #
    # ★ 2026-11-01：槽位多于参考图时，**剩余槽位重复最后一张（通常是场景），不再循环复用第一张**。
    #   原因：6 参考槽的工作流只给 3 张图时，旧逻辑填成 角色1/角色2/场景/角色1/角色2/场景，
    #   等于把两张人脸各喂了两遍 —— 与 RH 侧「未覆盖槽位沿用残留图导致串景」是同一类问题，
    #   只是这里由循环造成。多绑场景无害，多绑人脸会加剧「同一张脸复制出多人」。
    img_ids = [x for x in _roles(m, "images") if x in wf]
    extra = [nid for nid, n in wf.items()
             if str(n.get("class_type")) == "LoadImage" and nid not in img_ids]
    img_ids += sorted(extra, key=lambda x: (0, int(x)) if str(x).isdigit() else (1, str(x)))
    if img_ids and ref_names:
        for i, nid in enumerate(img_ids):
            wf[nid]["inputs"]["image"] = ref_names[i] if i < len(ref_names) else ref_names[-1]

    # ★ None / 空串 = 「沿用工作流原值」：不传就别覆盖，否则会把工作流里调好的
    #   分辨率/时长冲成代码默认值，用户会以为「换了个工作流结果画质变差了」。
    ids = _roles(m, "seconds")
    if ids and ids[0] in wf and seconds is not None:
        wf[ids[0]]["inputs"]["value"] = float(seconds)

    # ★ 2026-11-04：帧数（`length`）在 H3 上要 **INT**，而 ComfyMathExpression 输出 FLOAT ——
    #   ComfyUI 提交前的类型校验会以 `return_type_mismatch` 直接拒掉整张图。
    #   所以帧数不进连线：由 Python 侧按 frames_for(seconds) 算好，直接写成字面量。
    #   判据只认 map 里显式声明的 `_length_node`，不猜节点，猜错会改到别的时间参数上。
    lid = str(m.get("_length_node") or "")
    if lid and lid in wf and seconds is not None:
        ins = wf[lid].setdefault("inputs", {})
        if "length" in ins:
            ins["length"] = frames_for(seconds)

    ids = _roles(m, "steps")
    # `steps is None` = 沿用工作流原值。批处理里没有「步数」这个概念，
    # 传 None 比传一个猜出来的数字安全：猜大了慢，猜小了糊，而且都不报错。
    if ids and ids[0] in wf and steps is not None:
        ins = wf[ids[0]]["inputs"]
        ins["steps" if "steps" in ins else "value"] = int(steps)
        # ★ 2026-11-04：有些工作流的步数不是由采样器节点决定，而是由一串**手写的 sigmas**
        #   决定（Minimax H3 画布版就是）。改 steps 会改到一个没被引用的节点上 ——
        #   静默无效。宁可吵一次，也不让人以为「设了 8 步」。
        if m.get("_steps_ineffective"):
            print("  [WARN] 本工作流的实际步数由固定 sigmas 决定，steps=%s 不生效。" % steps)
            if m.get("_steps_note"):
                print("         %s" % m["_steps_note"])

    ids = _roles(m, "seed")
    if ids and ids[0] in wf:
        ins = wf[ids[0]]["inputs"]
        if "noise_seed" in ins:
            ins["noise_seed"] = int(seed)
        else:
            ins["seed" if "seed" in ins else "value"] = int(seed)

    ids = _roles(m, "aspect")
    if ids and ids[0] in wf:
        ins = wf[ids[0]]["inputs"]
        if aspect:
            ins["aspect_ratio"] = aspect
        if mp is not None:
            ins["megapixels"] = float(mp)

    ids = _roles(m, "prefix")
    if ids and ids[0] in wf:
        wf[ids[0]]["inputs"]["filename_prefix"] = prefix
    return wf


# ---------------------------------------------------------------------------
# 提交 + 轮询 + 落盘
# ---------------------------------------------------------------------------
def submit_and_wait(wf: dict, timeout_min: float | None = None) -> dict:
    """提交并等到产物就绪。`timeout_min=None` 按链路自动取档（远端 30 / 本地 20）。

    ★ 2026-11-04 重写，三处稳定性改动：

    1. **提交前看队列**。本地出片一镜 5–10 分钟，如果队列里还有别人的任务，
       你会以为「我这镜特别慢」。先说清楚前面有几项，比事后解释便宜。
    2. **轮询自适应**：前 30 秒 1 秒一次（短任务能立刻拿到），之后 3 秒一次
       （长任务不必刷屏）。原来的固定 3 秒会让 4 秒的小样白等两轮。
    3. **任务丢失检测**：ComfyUI 重启或队列被手工清空后，`/history/<pid>` 会永远
       空着 —— 旧实现会死等到 20 分钟超时才报「超时」，而真正原因是「任务没了」。
       现在同时查 `/queue`：既不在历史也不在队列，连续两次就立刻判定丢失。

    ★ 2026-11-05 云端接入：远端多一步「提交前释放显存」。24G 看着宽裕，但出图/出片
      两条工作流同时驻留就会 OOM；而云端的 OOM 表现为任务直接消失，比本地更难查。
      释放失败**不阻塞**主流程 —— 它只是优化，不是前置条件。
    """
    if timeout_min is None:
        timeout_min = _default_timeout_min()

    if not _is_loopback(COMFY):
        try:
            Q.free_memory(unload_models=True, free_memory=True)
            print("  [显存] 远端提交前已请求 /free（unload_models=True）")
        except Exception as exc:                                  # noqa: BLE001
            print("  [显存] /free 请求失败（不影响提交）：%s" % str(exc).splitlines()[0][:80])

    # —— 提交前：队列状况 ——
    try:
        q = Q.queue_state()
        if q["running_count"] or q["pending_count"]:
            print("  [队列] 已有 %d 项在跑 / %d 项排队 —— 这一镜会在后面等"
                  % (q["running_count"], q["pending_count"]))
    except Q.ComfyError as exc:
        print("  [队列] 读不到（%s），继续提交" % str(exc).splitlines()[0][:80])

    cid = uuid.uuid4().hex
    # retries=0：重发 /prompt 会真的再出一遍视频
    r = Q.post_json("/prompt", {"prompt": wf, "client_id": cid}, timeout=180, retries=0, tag="prompt")
    pid = r.get("prompt_id")
    if not pid:
        raise SystemExit("[FAIL] 提交未返回 prompt_id：%s" % json.dumps(r, ensure_ascii=False)[:400])
    if r.get("node_errors"):
        raise SystemExit("[FAIL] 工作流校验未通过：%s"
                         % json.dumps(r["node_errors"], ensure_ascii=False)[:600])
    print("prompt_id: %s（开始轮询 /history）" % pid)

    t0, last = time.time(), ""
    deadline = t0 + max(60.0, timeout_min * 60)
    read_fail = 0          # 连续读失败次数
    gone = 0               # 连续「历史没有 + 队列没有」次数
    next_tick = 0.0

    while time.time() < deadline:
        elapsed = time.time() - t0
        # 自适应间隔：前 30 秒密一点，之后疏一点
        time.sleep(1.0 if elapsed < 30 else 3.0)

        try:
            h = Q.get_json("/history/" + pid, timeout=30, retries=2, tag="history")
            read_fail = 0
        except Q.ComfyError as exc:
            # 单次读失败多半是服务端忙；连续 3 次才算真出问题
            read_fail += 1
            last = str(exc).splitlines()[0][:120]
            if read_fail >= 3:
                raise SystemExit(
                    "[FAIL] 连续 %d 次读不到 /history（最后错误：%s）\n"
                    "       ComfyUI 可能已退出或端口变了；产物若已生成可在 output 目录找到，"
                    "补下载用：comfy_local_video.py --list?" % (read_fail, last))
            continue

        item = h.get(pid) or {}
        outs = item.get("outputs") or {}
        for node_out in outs.values():
            for key in ("gifs", "videos", "images"):
                for f in (node_out.get(key) or []):
                    if str(f.get("filename", "")).lower().endswith((".mp4", ".webm", ".webp", ".gif")):
                        return {"files": node_out.get(key), "elapsed": time.time() - t0,
                                "status": (item.get("status") or {}).get("status_str", "")}
        stt = (item.get("status") or {}).get("status_str")
        if stt in ("error", "failed"):
            raise SystemExit("[FAIL] 任务失败：%s"
                             % json.dumps(item.get("status"), ensure_ascii=False)[:500])

        # —— 任务丢失检测 ——
        # 刚提交的头 20 秒不判（队列可能还没登记），之后才查
        if not outs and elapsed > 20:
            try:
                if not Q.pid_running(pid):
                    gone += 1
                    if gone >= 2:
                        raise SystemExit(
                            "[FAIL] 任务从 ComfyUI 消失：%s 既不在 /history 也不在 /queue。\n"
                            "       常见原因：ComfyUI 重启、队列被手工清空、显存不足被丢弃。\n"
                            "       处理：重跑同一条命令即可（已经完成的镜会自动跳过）。" % pid)
                else:
                    gone = 0
            except Q.ComfyError:
                pass                              # 查不到队列就先不判，别误杀
        else:
            gone = 0

        if time.time() >= next_tick:
            print("  已等 %ds…（队列中）" % int(elapsed))
            next_tick = time.time() + 30

    raise SystemExit("[FAIL] 轮询超时 %d 分钟（最后错误：%s）\n"
                     "       · 先开 ComfyUI 队列面板看是否还在跑\n"
                     "       · 若已跑完只是没回写，产物在 ComfyUI 的 output 目录\n"
                     "       · 加大超时：--timeout-min %d"
                     % (timeout_min, last or "无", int(timeout_min * 2)))


def download(f: dict, out_dir: str, name: str) -> str:
    """把产物从 ComfyUI 的 output 目录下到本地。返回落地路径。

    走共享层：先写 `name.part` 再改名 —— 中断不会留下一个冒充完整产物的半截 mp4。
    """
    qs = urllib.parse.urlencode({"filename": f["filename"],
                                 "subfolder": f.get("subfolder", ""),
                                 "type": f.get("type", "output")})
    dst = os.path.join(out_dir, name)
    Q.download("/view?" + qs, dst, timeout=300, retries=3)
    return dst


def main() -> int:
    ap = argparse.ArgumentParser(description="本地 ComfyUI 出视频（H3，￥0，默认干跑）")
    ap.add_argument("--workflow", default="", help="API 格式工作流 JSON（默认本目录 workflow_h3_local.json）")
    ap.add_argument("--map", default="", help="节点映射 JSON（默认读同名 sidecar <工作流>.map.json）")
    ap.add_argument("--list-nodes", action="store_true", help="列出工作流节点与建议角色（离线）")
    ap.add_argument("--map-check", action="store_true", help="离线校验映射（节点在不在/类型对不对）")
    ap.add_argument("--list-ports", action="store_true",
                    help="离线列端口：提示词/图片槽/步数/画幅/输出，以及最多能接几张参考图")
    ap.add_argument("--check", action="store_true", help="在线体检（ComfyUI + 节点类 + 模型文件）")
    ap.add_argument("--prompt", default="", help="镜头提示词（自然语言长句，可含 subject_definitions）")
    ap.add_argument("--ref", action="append", default=[], help="参考图路径（可多次；不足会循环复用第一张）")
    ap.add_argument("--seconds", type=float, default=None, help="时长（秒）；不给就沿用工作流里的值")
    ap.add_argument("--steps", type=int, default=None, help="采样步数；不给就沿用工作流里的值")
    ap.add_argument("--seed", type=int, default=-1, help="种子；-1 随机")
    ap.add_argument("--aspect", default="", help="画幅；不给就沿用工作流里的值")
    ap.add_argument("--mp", type=float, default=None, help="百万像素；不给就沿用工作流里的值（8G 卡可降到 0.3-0.4）")
    ap.add_argument("--prefix", default="h3local", help="ComfyUI 侧文件名前缀")
    ap.add_argument("--out", default="", help="产物落盘目录（必填，除了体检类命令）")
    ap.add_argument("--name", default="", help="落盘文件名（默认 <prefix>_<seed>.mp4）")
    ap.add_argument("--submit", action="store_true", help="真的提交（占 GPU；不花钱）")
    ap.add_argument("--timeout-min", type=float, default=None,
                    help="轮询超时（分钟）；不给 = 按链路自动（远端 30 / 本地 20）")
    a = ap.parse_args()

    if a.list_nodes:
        return list_nodes(a.workflow)
    if a.list_ports:
        return list_ports(a.workflow)
    if a.map_check:
        return map_check(a.workflow, a.map)
    if a.check:
        return check(a.workflow, a.map)

    if not a.prompt.strip():
        print("[FAIL] 缺 --prompt")
        return 2
    if not a.out:
        print("[FAIL] 缺 --out（产物目录）")
        return 2

    seed = a.seed if a.seed >= 0 else int(time.time()) % 2_000_000_000
    wf = load_workflow(a.workflow)
    m, src = load_map(a.workflow, a.map)

    def _wfv(role, field, cast=None):
        ids = _roles(m, role)
        if not ids or ids[0] not in wf:
            return None
        v = wf[ids[0]].get("inputs", {}).get(field)
        if v is None or v == "":
            return None
        try:
            return cast(v) if cast else v
        except (TypeError, ValueError):
            return None

    # 步数/时长：不传就沿用工作流原值
    steps = a.steps if a.steps is not None else (_wfv("steps", "steps", int)
                                                 or _wfv("steps", "value", int) or 4)
    sec = a.seconds if a.seconds is not None else _wfv("seconds", "value", float)
    asp = a.aspect or str(_wfv("aspect", "aspect_ratio") or "")
    mp = a.mp if a.mp is not None else _wfv("aspect", "megapixels", float)

    print("工作流  : %s" % (a.workflow or DEFAULT_WORKFLOW))
    print("映射    : %s" % src)
    print("ComfyUI : %s（%s）" % (COMFY, "本机" if _is_loopback(COMFY) else "远端 · 超时 %.0f 分钟"
                                  % _default_timeout_min()))
    if sec:
        print("时长    : %.1fs ≈ %d 帧（17n+5 对齐）" % (sec, frames_for(sec)))
    else:
        print("时长    : 沿用工作流原值")
    print("画幅    : %s @ %sMP｜步数 %d｜种子 %d" % (asp or "沿用原值", mp, steps, seed))
    print("参考图  : %s" % ("、".join(os.path.basename(p) for p in a.ref) or "（无）"))

    if not a.ref:
        print("  ★ 注意：这是 H3 **图生**视频，没有参考图会跑成纯文本条件，人物一致性不保证")

    if not a.submit:
        # 干跑也把「会关掉哪些槽」说清楚：这是最容易在出片后才发现的问题（串景）
        if prune_for_refs is not None:
            _wf2, rep = prune_for_refs(wf, len(a.ref) or None)
            if rep.get("dropped_nodes"):
                print("  端口裁剪：图片槽 %s → %s，将关闭节点 %s"
                      % (rep["before"], rep["after"], "、".join(rep["dropped_nodes"])))
            elif rep.get("before"):
                print("  端口裁剪：图片槽 %s 个，本次用 %s 个（无需关闭）"
                      % (rep["before"], rep.get("after")))
        print("\n★ DRY-RUN：未提交，未占 GPU。加 --submit 才真的出片。")
        print("  将覆盖：prompt=%s  images=%s  seconds=%s  steps=%s  seed=%s"
              % (m.get("prompt"), m.get("images"), m.get("seconds"), m.get("steps"), m.get("seed")))
        return 0

    if check(a.workflow, a.map) != 0:
        return 2

    names = []
    for p in a.ref:
        if not os.path.isfile(p):
            print("[FAIL] 参考图不存在：%s" % p)
            return 2
        names.append(upload_image(p))
    if names:
        print("参考图已上传: %s" % "、".join(names))

    # ★ 按实际参考图数量关掉多余槽位：6 槽工作流这次只有 2 张图时，
    #   不裁就等于让另外 4 个槽继续拿上次的文件跑（串景 + 白占显存）。
    if prune_for_refs is not None:
        wf, rep = prune_for_refs(wf, len(names) or None)
        if rep.get("dropped_nodes"):
            print("[端口] 图片槽 %s → %s，已关闭 %d 个多余槽（节点 %s）"
                  % (rep["before"], rep["after"], len(rep["dropped_nodes"]),
                     "、".join(rep["dropped_nodes"])))
        elif rep.get("before"):
            print("[端口] 图片槽 %s 个（按参考图数量 %s 使用）" % (rep["before"], rep.get("after")))

    wf = apply_nodes(wf, m, prompt=a.prompt, ref_names=names or [""], seconds=a.seconds,
                     steps=steps, seed=seed, aspect=a.aspect, mp=a.mp, prefix=a.prefix)
    res = submit_and_wait(wf, timeout_min=a.timeout_min)
    files = res["files"] or []
    if not files:
        print("[FAIL] 任务结束但没有产物")
        return 2
    ext = os.path.splitext(files[0]["filename"])[1] or ".mp4"
    name = a.name or ("%s_%d%s" % (a.prefix, seed, ext))
    dst = download(files[0], a.out, name)
    size = os.path.getsize(dst) / 1024 / 1024
    print("\n[OK] 出片 %.0fs ｜ %.1f MB ｜ %s" % (res["elapsed"], size, dst))
    return 0


if __name__ == "__main__":
    sys.exit(main())
