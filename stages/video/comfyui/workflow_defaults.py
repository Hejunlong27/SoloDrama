#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""workflow_defaults.py —— 「默认工作流是哪一份」的唯一真源（按通道分）

为什么单独成文件
----------------
同一个项目会跑两条通道：本机 ComfyUI（4060 / ￥0）与云端镜像（4090 / 按主机时长计费）。
2026-11-13 起按用户要求：本机和仙宫云镜像共用 `workflow_h3_minimax_audio`，
默认 0.8MP、6 参考槽、带音频；仍可按 `--workflow` / 环境变量单独覆盖。

此前「默认工作流」这四个字散在四个地方各写一遍：

    comfy_local_video.DEFAULT_WORKFLOW        ← 执行器
    gen_preflight.DEFAULT_WF["video"]         ← 预检
    generators.VIDEO_LOCAL_WF / _cloud_target ← 界面通道页
    drama._run_cloud_task                     ← 云端任务（写死 canvas）

任何一处没跟着改，就是「界面说 A、预检核 B、真跑提交 C」—— 本仓库在这一点上已经踩过两次
（2026-11-04 界面核对 canvas 而执行器跑旧版；2026-11-05 干跑显示 canvas 而真跑提交替代版）。
所以路径只在这里定义，别处一律 import。

约定
----
* 纯标准库、零副作用、可被任何层 import（不需要 torch、不需要网络、不读环境变量）。
* 返回**绝对路径**：调用方常常要把路径塞进子进程 argv 或写进确认单，相对路径的基准
  在不同 cwd 下会漂（`--workflow` 只给文件名时执行器才按本目录解析，别处不会）。
* 环境变量 `COMFYUI_VIDEO_WORKFLOW` 由调用方自己处理（各入口的优先级不同），不在这里判断。
"""
from __future__ import annotations

import os

HERE = os.path.dirname(os.path.abspath(__file__))

# 本机与仙宫云共用：6 参考槽 + fl2v turbo 8step + 音频，默认 0.8MP。
LOCAL_VIDEO = "workflow_h3_minimax_audio.json"

# 仙宫云镜像使用同一份工作流；换机器只换模型文件与地址。
CLOUD_VIDEO = "workflow_h3_minimax_audio.json"


def video_name(cloud: bool = False) -> str:
    """视频默认工作流的**文件名**（写日志、写确认单、给 ``--workflow`` 用）。"""
    return CLOUD_VIDEO if cloud else LOCAL_VIDEO


def video_path(cloud: bool = False) -> str:
    """视频默认工作流的**绝对路径**。"""
    return os.path.join(HERE, video_name(cloud))
