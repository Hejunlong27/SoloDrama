#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""comfy_local_video.py —— 用**本机 ComfyUI** 出视频（H3 图生视频，￥0）

工作流怎么设定（三层，改哪层都行）
----------------------------------
1. **工作流 JSON**：默认 `stages/video/comfyui/workflow_h3_local.json`（本机在用的
   「minimax 多参(4步采样)」）。要换就换文件，或 `--workflow <路径>`，或环境变量
   `COMFYUI_VIDEO_WORKFLOW`。**不需要上传到 ComfyUI**：这两份文件是 ComfyUI 的
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
    from comfy_ports import describe as ports_describe, prune_for_refs
except ImportError:                                      # 缺了就降级：不裁也不报错
    ports_describe = None
    prune_for_refs = None

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
COMFY = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")
DEFAULT_WORKFLOW = os.environ.get(
    "COMFYUI_VIDEO_WORKFLOW", os.path.join(HERE, "workflow_h3_local.json"))

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
    sc = sidecar_for(workflow_path)
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
        return base, "%s（%s）" % (path, why)
    env_used = any(os.environ.get(s["env"]) for s in MAP_ROLES.values())
    return _builtin_map(), ("环境变量 COMFYUI_VIDEO_NODE_*" if env_used else "脚本内置默认")


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def http_json(url: str, payload=None, timeout=30):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json"})
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # 本机服务，绕开系统代理
    with op.open(req, timeout=timeout) as r:
        body = r.read()
    return json.loads(body.decode("utf-8")) if body else {}


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
    req = urllib.request.Request(COMFY + "/upload/image", data=body, method="POST",
                                 headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with op.open(req, timeout=120) as r:
        d = json.loads(r.read().decode("utf-8"))
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
    print("工作流  : %s（%d 节点）" % (workflow_path or DEFAULT_WORKFLOW, len(wf)))
    print("映射    : %s" % src)

    oi = http_json(COMFY + "/object_info", timeout=60)
    miss_cls = sorted({v.get("class_type") for v in wf.values()} - set(oi))
    if miss_cls:
        print("[FAIL] 缺自定义节点：%s" % "、".join(miss_cls))
    else:
        print("[OK] 节点类齐全（%d 个 class_type 全部可用）"
              % len({v.get("class_type") for v in wf.values()}))

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


def apply_nodes(wf: dict, m: dict, *, prompt: str, ref_names: list, seconds, steps: int,
                seed: int, aspect: str, mp, prefix: str) -> dict:
    wf = json.loads(json.dumps(wf))          # 深拷贝，避免污染模板

    ids = _roles(m, "prompt")
    if ids and ids[0] in wf:
        wf[ids[0]]["inputs"]["value"] = prompt

    # 参考图按序铺到每个 LoadImage 槽位；不够就循环复用第一张。
    # ★ 不能只看映射里的 images：裁剪/换工作流后映射可能是旧的，没列到的加载器会带着
    #   模板里的占位文件名提交 → ComfyUI 报「image not found」，而报错看起来像工作流坏了。
    img_ids = [x for x in _roles(m, "images") if x in wf]
    extra = [nid for nid, n in wf.items()
             if str(n.get("class_type")) == "LoadImage" and nid not in img_ids]
    img_ids += sorted(extra, key=lambda x: (0, int(x)) if str(x).isdigit() else (1, str(x)))
    for i, nid in enumerate(img_ids):
        wf[nid]["inputs"]["image"] = ref_names[i % len(ref_names)]

    # ★ None / 空串 = 「沿用工作流原值」：不传就别覆盖，否则会把工作流里调好的
    #   分辨率/时长冲成代码默认值，用户会以为「换了个工作流结果画质变差了」。
    ids = _roles(m, "seconds")
    if ids and ids[0] in wf and seconds is not None:
        wf[ids[0]]["inputs"]["value"] = float(seconds)

    ids = _roles(m, "steps")
    if ids and ids[0] in wf:
        ins = wf[ids[0]]["inputs"]
        ins["steps" if "steps" in ins else "value"] = int(steps)

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
def submit_and_wait(wf: dict, *, timeout_min: float) -> dict:
    cid = uuid.uuid4().hex
    r = http_json(COMFY + "/prompt", {"prompt": wf, "client_id": cid}, timeout=120)
    pid = r.get("prompt_id")
    if not pid:
        raise SystemExit("[FAIL] 提交未返回 prompt_id：%s" % json.dumps(r, ensure_ascii=False)[:400])
    print("prompt_id: %s（开始轮询 /history）" % pid)

    t0, last = time.time(), ""
    deadline = t0 + max(60.0, timeout_min * 60)
    while time.time() < deadline:
        time.sleep(3)
        try:
            h = http_json(COMFY + "/history/" + pid, timeout=30)
        except Exception as exc:  # noqa: BLE001
            last = "%s" % type(exc).__name__
            continue
        item = h.get(pid) or {}
        outs = item.get("outputs") or {}
        if outs:
            for node_out in outs.values():
                for key in ("gifs", "videos", "images"):
                    for f in (node_out.get(key) or []):
                        if str(f.get("filename", "")).lower().endswith((".mp4", ".webm", ".webp", ".gif")):
                            return {"files": node_out.get(key), "elapsed": time.time() - t0,
                                    "status": (item.get("status") or {}).get("status_str", "")}
        stt = (item.get("status") or {}).get("status_str")
        if stt in ("error", "failed"):
            raise SystemExit("[FAIL] 任务失败：%s" % json.dumps(item.get("status"), ensure_ascii=False)[:500])
        if int(time.time() - t0) % 30 < 4:
            print("  已等 %ds…" % int(time.time() - t0))
    raise SystemExit("[FAIL] 超时（最后错误：%s；可先在 ComfyUI 队列面板看是否卡住）"
                     % (last or "无"))


def download(f: dict, out_dir: str, name: str) -> str:
    qs = urllib.parse.urlencode({"filename": f["filename"],
                                 "subfolder": f.get("subfolder", ""),
                                 "type": f.get("type", "output")})
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    os.makedirs(out_dir, exist_ok=True)
    dst = os.path.join(out_dir, name)
    with op.open(COMFY + "/view?" + qs, timeout=180) as r, open(dst, "wb") as fh:
        fh.write(r.read())
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
    ap.add_argument("--timeout-min", type=float, default=20.0, help="轮询超时（分钟）")
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
