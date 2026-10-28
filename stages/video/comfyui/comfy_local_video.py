#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""comfy_local_video.py —— 用**本机 ComfyUI** 出视频（H3 图生视频，￥0）

为什么单独一个客户端
--------------------
出图那套（`stages/assets/comfyui/comfy_client.py`）取的是 `SaveImage` 的 `images`，
而视频走 `VHS_VideoCombine` 的 `gifs`，还要多两步：**上传参考图**、**从 /view 下载 mp4**。
硬塞进图片客户端会让两边都难读，所以这里独立一份，纪律与出图完全一致：

  * 纯标准库（urllib），不引第三方依赖；
  * 默认 **dry-run**：只打印将要覆盖的槽位，不占 GPU；
  * `--check` 先把「节点类 / 模型文件 / 参考图」逐项核对完再允许提交 ——
    否则要等模型加载失败才发现少文件，白等几分钟显存。

★ 工作流与模型的口径
--------------------
`workflow_h3_local.json` 是**本机实装**的 H3 图生视频图（30 节点）。它由云端同名工作流
移植而来，只换了 4 个模型文件名（RH 侧用 int8/fp16 变体，本机是 qwen3vl int4 + fl2va
pruned w4a8 + video_vae int8），节点图与连线一模一样。换模型必须同时改这里与环境变量映射，
否则 `--check` 会直接告诉你哪个文件不存在。

用法
----
  python comfy_local_video.py --check
  python comfy_local_video.py --prompt "..." --ref a.png --seconds 4 --out out/
  python comfy_local_video.py --prompt "..." --ref a.png --seconds 4 --out out/ --submit
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
COMFY = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")
DEFAULT_WORKFLOW = os.environ.get(
    "COMFYUI_VIDEO_WORKFLOW", os.path.join(HERE, "workflow_h3_local.json"))

# 节点映射：与 workflow_h3_local.json 对齐（换工作流必须同步改这里）
# ★ 映射对应「minimax 多参(4步采样)」这份工作流（26 节点，Sol 加速节点保留、steps=4）。
#   换工作流必须逐个核对，否则会出现「提交成功但参数没生效」（最贵的那种错：钱花了、片不对）。
NODE_PROMPT = os.environ.get("COMFYUI_VIDEO_NODE_PROMPT", "30")      # PrimitiveStringMultiline
NODE_IMAGES = os.environ.get("COMFYUI_VIDEO_NODE_IMAGES", "24").split(",")   # LoadImage（多参工作流只吃 1 张）
NODE_SECONDS = os.environ.get("COMFYUI_VIDEO_NODE_SECONDS", "15")    # PrimitiveFloat（秒）
NODE_STEPS = os.environ.get("COMFYUI_VIDEO_NODE_STEPS", "9")         # BasicScheduler.steps
NODE_SEED = os.environ.get("COMFYUI_VIDEO_NODE_SEED", "10")          # Seed (rgthree) → RandomNoise
NODE_ASPECT = os.environ.get("COMFYUI_VIDEO_NODE_ASPECT", "14")      # ResolutionSelector
NODE_PREFIX = os.environ.get("COMFYUI_VIDEO_NODE_PREFIX", "4")       # SaveVideo.filename_prefix


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
# 工作流校验：**提交前**就把缺失项说清楚
# ---------------------------------------------------------------------------
MODEL_NODES = {
    "UNETLoader": ("unet_name", "unet_name"),
    "CLIPLoader": ("clip_name", "clip_name"),
    "VAELoader": ("vae_name", "vae_name"),
    "LoraLoaderModelOnly": ("lora_name", "lora_name"),
    "LoraLoaderBypassModelOnly": ("lora_name", "lora_name"),
}
# 本地模型清单来自 /object_info，键名与上面一致
INFO_KEY = {"unet_name": "UNETLoader", "clip_name": "CLIPLoader",
            "vae_name": "VAELoader", "lora_name": "LoraLoaderModelOnly"}


def load_workflow(path: str = "") -> dict:
    p = path or DEFAULT_WORKFLOW
    with open(p, encoding="utf-8") as fh:
        wf = json.load(fh)
    if not isinstance(wf, dict) or "class_type" in wf:
        raise SystemExit("[FAIL] 工作流必须是 API 格式（{nodeId: {class_type, inputs}}）")
    return wf


def check(workflow_path: str = "") -> int:
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
    print("工作流  : %s（%d 节点）" % (workflow_path or DEFAULT_WORKFLOW, len(wf)))

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
        if cls not in MODEL_NODES:
            continue
        field, info_key = MODEL_NODES[cls]
        want = (node.get("inputs") or {}).get(field)
        if not want:
            continue
        try:
            have = oi[INFO_KEY[info_key]]["input"]["required"][info_key][0]
        except Exception:  # noqa: BLE001
            have = []
        # VAELoader 有多个节点，用 VAELoader 自己的清单
        if cls == "VAELoader":
            have = oi["VAELoader"]["input"]["required"]["vae_name"][0]
        if want not in have:
            miss_models.append("#%s %s = %s" % (nid, cls, want))
    if miss_models:
        print("[FAIL] 缺模型文件：")
        for m in miss_models:
            print("       %s" % m)
    else:
        print("[OK] 模型文件齐全（unet / clip / vae / lora 逐项核对）")

    ok = not miss_cls and not miss_models
    print("\n%s" % ("可以提交（--submit 会真的占 GPU 出片）" if ok else "先补齐上面的缺失项"))
    return 0 if ok else 2


# ---------------------------------------------------------------------------
# 覆盖槽位
# ---------------------------------------------------------------------------
def frames_for(seconds: float) -> int:
    """H3 的帧数约束：length = 17n + 5（与工作流里 ComfyMathExpression 的公式同源）。

    工作流内部节点 131 会按秒数算一次；这里先算出来只为**打印预期帧数**，
    真正的提交值仍由节点公式决定，避免两处算法打架。
    """
    import math
    n = max(5, round(float(seconds) * 24))
    return n + (5 - (n % 17)) % 17


def apply_nodes(wf: dict, *, prompt: str, ref_names: list, seconds: float,
                steps: int, seed: int, aspect: str, mp: float, prefix: str) -> dict:
    wf = json.loads(json.dumps(wf))          # 深拷贝，避免污染模板
    wf[NODE_PROMPT]["inputs"]["value"] = prompt
    # 参考图按序铺到每个 LoadImage 槽位；不够就循环复用第一张
    for i, nid in enumerate([n for n in NODE_IMAGES if n in wf]):
        wf[nid]["inputs"]["image"] = ref_names[i % len(ref_names)]
    # ★ None / 空串 = 「沿用工作流原值」。不传就别覆盖 —— 否则会把工作流里调好的
    #   分辨率/时长冲成代码默认值，用户会以为「换了个工作流结果画质变差了」。
    if seconds is not None and NODE_SECONDS in wf:
        wf[NODE_SECONDS]["inputs"]["value"] = float(seconds)
    if NODE_STEPS in wf:
        wf[NODE_STEPS]["inputs"]["value"] = int(steps)
    if NODE_SEED in wf:
        wf[NODE_SEED]["inputs"]["noise_seed"] = int(seed)
    if NODE_ASPECT in wf:
        if aspect:
            wf[NODE_ASPECT]["inputs"]["aspect_ratio"] = aspect
        if mp is not None:
            wf[NODE_ASPECT]["inputs"]["megapixels"] = float(mp)
    if NODE_PREFIX in wf:
        wf[NODE_PREFIX]["inputs"]["filename_prefix"] = prefix
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
    raise SystemExit("[FAIL] 超时（%s，最后错误：%s；可先在 ComfyUI 队列面板看是否卡住）"
                     % (last or "无", timeout_min))


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
    ap.add_argument("--prompt", default="", help="镜头提示词（自然语言长句，可含 subject_definitions）")
    ap.add_argument("--ref", action="append", default=[], help="参考图路径（可多次；不足会循环复用第一张）")
    ap.add_argument("--seconds", type=float, default=None, help="时长（秒）；不给就沿用工作流里的值")
    ap.add_argument("--steps", type=int, default=4, help="采样步数（配套 4 步 turbo LoRA，默认 4）")
    ap.add_argument("--seed", type=int, default=-1, help="种子；-1 随机")
    ap.add_argument("--aspect", default="", help="画幅；不给就沿用工作流里的值")
    ap.add_argument("--mp", type=float, default=None, help="百万像素；不给就沿用工作流里的值（8G 卡可降到 0.3-0.4）")
    ap.add_argument("--prefix", default="h3local", help="ComfyUI 侧文件名前缀")
    ap.add_argument("--out", default="", help="产物落盘目录（必填，除了 --check）")
    ap.add_argument("--name", default="", help="落盘文件名（默认 <prefix>_<seed>.mp4）")
    ap.add_argument("--submit", action="store_true", help="真的提交（占 GPU；不花钱）")
    ap.add_argument("--timeout-min", type=float, default=20.0, help="轮询超时（分钟）")
    ap.add_argument("--check", action="store_true", help="只体检：ComfyUI 在线 + 节点/模型齐全")
    a = ap.parse_args()

    if a.check:
        return check(a.workflow)

    if not a.prompt.strip():
        print("[FAIL] 缺 --prompt")
        return 2
    if not a.out:
        print("[FAIL] 缺 --out（产物目录）")
        return 2
    seed = a.seed if a.seed >= 0 else int(time.time()) % 2_000_000_000
    wf = load_workflow(a.workflow)

    # 「不传就沿用工作流原值」：这里把生效值读出来给人看，避免以为改过了
    sec = a.seconds
    if sec is None:
        sec = float((wf.get(NODE_SECONDS) or {}).get("inputs", {}).get("value") or 0) or None
    asp = a.aspect or str((wf.get(NODE_ASPECT) or {}).get("inputs", {}).get("aspect_ratio") or "")
    mp = a.mp
    if mp is None:
        mp = (wf.get(NODE_ASPECT) or {}).get("inputs", {}).get("megapixels")

    print("工作流  : %s" % (a.workflow or DEFAULT_WORKFLOW))
    if sec:
        print("时长    : %.1fs ≈ %d 帧（17n+5 对齐）" % (sec, frames_for(sec)))
    else:
        print("时长    : 沿用工作流原值")
    print("画幅    : %s @ %sMP｜步数 %d｜种子 %d" % (asp or "沿用原值", mp, a.steps, seed))
    print("参考图  : %s" % ("、".join(os.path.basename(p) for p in a.ref) or "（无）"))

    if not a.ref:
        print("  ★ 注意：这是 H3 **图生**视频，没有参考图会跑成纯文本条件，人物一致性不保证")

    if not a.submit:
        print("\n★ DRY-RUN：未提交，未占 GPU。加 --submit 才真的出片。")
        print("  将要覆盖的槽位：prompt=#%s  images=%s  seconds=#%s  steps=#%s  seed=#%s"
              % (NODE_PROMPT, ",".join(NODE_IMAGES), NODE_SECONDS, NODE_STEPS, NODE_SEED))
        return 0

    if check(a.workflow) != 0:
        return 2

    names = []
    for p in a.ref:
        if not os.path.isfile(p):
            print("[FAIL] 参考图不存在：%s" % p)
            return 2
        names.append(upload_image(p))
    if names:
        print("参考图已上传: %s" % "、".join(names))

    wf = apply_nodes(wf, prompt=a.prompt, ref_names=names or [""], seconds=a.seconds,
                     steps=a.steps, seed=seed, aspect=a.aspect, mp=a.mp, prefix=a.prefix)
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
