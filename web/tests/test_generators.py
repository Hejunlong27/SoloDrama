#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_generators.py —— 生成通道台账的口径测试（离线，不碰 GPU、不出网）

为什么单独守这一层
------------------
2026-10-29 用户明确要求：**图像要能接 RH 工作流，并且文生图 / 图生图必须分开**。
这两条最容易在实现里被「合并同类项」：
  * 用同一个工作流 id 跑两种模式 ⇒ 传了参考图但平台忽略它，出图还是纯文生图（白花钱）；
  * 图生图忘了校验「加载图像」节点 ⇒ 提交成功、钱扣了、图不对。

所以这里守三件事：
  1. t2i 与 i2i 各取各的 id（`id` vs `id_i2i`），且不互相兜底；
  2. i2i 缺参考图节点时状态必须是「待配置」并给出下一步，不能报「可用」；
  3. 本地通道要能区分「ComfyUI 没开」与「工作流/模型缺文件」——两者的修法完全不同。
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB))

from core import generators  # noqa: E402

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("  [NG] %s" % msg)
    return cond


def section(name):
    print("\n[%s]" % name)


def _cfg(root: Path, prov: dict, h3: dict | None = None) -> Path:
    ws = root / "剧"
    vp = ws / "video-pipeline"
    vp.mkdir(parents=True, exist_ok=True)
    d = {"active_image_provider": prov.pop("_name", "qwen"),
         "image_providers": {prov.pop("_name", "qwen"): prov}}
    if h3 is not None:
        d["h3"] = h3
    (vp / "config.local.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return ws


def main():
    root = Path(tempfile.mkdtemp(prefix="solodrama-gen-"))
    real_comfy, real_info = generators._comfy, generators._comfy_info
    real_video_wf, real_image_wf = generators.VIDEO_LOCAL_WF, generators.IMAGE_LOCAL_WF
    try:
        # ComfyUI 在线 + 所有模型都在（模拟）
        fake_info = {
            "UNETLoader": {"input": {"required": {"unet_name": [["u.safetensors"]]}}},
            "CLIPLoader": {"input": {"required": {"clip_name": [["c.safetensors"]]}}},
            "VAELoader": {"input": {"required": {"vae_name": [["v.safetensors"]]}}},
            "LoraLoaderModelOnly": {"input": {"required": {"lora_name": [["l.safetensors"]]}}},
        }
        generators._comfy = lambda: {"online": True, "version": "9.9.9",
                                     "vram_free_gb": 5.0, "reason": ""}
        generators._comfy_info = lambda: dict(fake_info)

        print("[1] 文生图 / 图生图必须各取各的工作流 id")
        ws = _cfg(root, {"_name": "qwen", "id": "WF-T2I-001", "id_i2i": "WF-I2I-002",
                         "nodes": {"prompt": {"nodeId": "6"},
                                   "image": {"nodeId": "12"}}})
        d = generators.channels(str(ws))
        t2i = [x for x in d["items"] if x["id"] == "image.rh.t2i"][0]
        i2i = [x for x in d["items"] if x["id"] == "image.rh.i2i"][0]
        check(t2i["status"] == "ready", "文生图应可用，实际 %s（%s）" % (t2i["status"], t2i["detail"]))
        check(i2i["status"] == "ready", "图生图应可用，实际 %s（%s）" % (i2i["status"], i2i["detail"]))
        check("WF-T2I-001" in t2i["detail"], "文生图应指向 id：%s" % t2i["detail"])
        check("WF-I2I-002" in i2i["detail"], "图生图应指向 id_i2i：%s" % i2i["detail"])
        check("WF-I2I-002" not in t2i["detail"], "文生图不得串到图生图的 id")

        print("[2] 只配了 t2i id 时，i2i 必须是「待配置」，不许互相兜底")
        ws2 = _cfg(root / "b", {"_name": "qwen", "id": "ONLY-T2I",
                                "nodes": {"prompt": {"nodeId": "6"},
                                          "image": {"nodeId": "12"}}})
        d2 = generators.channels(str(ws2))
        i2i2 = [x for x in d2["items"] if x["id"] == "image.rh.i2i"][0]
        t2i2 = [x for x in d2["items"] if x["id"] == "image.rh.t2i"][0]
        check(t2i2["status"] == "ready", "t2i 仍应可用")
        check(i2i2["status"] == "config", "i2i 缺 id_i2i 应为待配置，实际 %s" % i2i2["status"])
        check("id_i2i" in (i2i2["next"] or ""), "下一步要指名 id_i2i：%s" % i2i2.get("next"))

        print("[3] 有 id_i2i 但没有「加载图像」节点 → 仍是待配置")
        ws3 = _cfg(root / "c", {"_name": "qwen", "id": "A", "id_i2i": "B",
                                "nodes": {"prompt": {"nodeId": "6"}}})
        i2i3 = [x for x in generators.channels(str(ws3))["items"] if x["id"] == "image.rh.i2i"][0]
        check(i2i3["status"] == "config", "缺 nodes.image 应为待配置，实际 %s" % i2i3["status"])
        check("加载图像" in (i2i3["detail"] + i2i3["next"]), "说明里要点出「加载图像」节点")

        print("[4] 本地通道要区分「ComfyUI 没开」与「工作流缺文件」")
        generators._comfy = lambda: {"online": False, "version": "", "vram_free_gb": 0.0,
                                     "reason": "URLError（ComfyUI Desktop 需手动启动 8188）"}
        d4 = generators.channels(str(ws))
        v4 = [x for x in d4["items"] if x["id"] == "video.local.i2v"][0]
        check(v4["status"] == "offline", "ComfyUI 没开应为 offline，实际 %s" % v4["status"])
        check("8188" in (v4["detail"] + v4["next"]), "要告诉用户启动 8188")

        generators._comfy = lambda: {"online": True, "version": "9.9.9",
                                     "vram_free_gb": 5.0, "reason": ""}
        generators.VIDEO_LOCAL_WF = root / "不存在的视频工作流.json"
        v5 = [x for x in generators.channels(str(ws))["items"] if x["id"] == "video.local.i2v"][0]
        check(v5["status"] == "missing", "工作流文件缺失应为 missing，实际 %s" % v5["status"])

        print("[5] 本地视频工作流里缺模型时，要说出缺哪个文件")
        wf = root / "wf.json"
        wf.write_text(json.dumps({
            "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "not-there.safetensors"}},
            "2": {"class_type": "ModelAttentionBackend", "inputs": {}},
        }), encoding="utf-8")
        generators.VIDEO_LOCAL_WF = wf
        v6 = [x for x in generators.channels(str(ws))["items"] if x["id"] == "video.local.i2v"][0]
        check(v6["status"] == "missing", "缺模型应为 missing，实际 %s" % v6["status"])
        check(any("not-there" in m for m in (v6["missing"] or [])),
              "missing 列表要点名缺哪个模型：%s" % v6.get("missing"))

        print("[6] 没选项目时，云端通道不许假装可配置")
        d7 = generators.channels(None)
        rh = [x for x in d7["items"] if x["engine"] == "rh"]
        check(all(x["status"] in ("unsupported", "config") for x in rh),
              "无工作区时云端通道状态应为 unsupported/config：%s"
              % [(x["id"], x["status"]) for x in rh])
    finally:
        generators._comfy, generators._comfy_info = real_comfy, real_info
        generators.VIDEO_LOCAL_WF, generators.IMAGE_LOCAL_WF = real_video_wf, real_image_wf
        shutil.rmtree(str(root), ignore_errors=True)

    print("\n" + ("全部通过" if not FAILS else "失败 %d 项" % len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
