"""tests/test_seed_unique.py —— 同一批次内 seed 必须唯一

来源：2026-11-05 云端实测。
ComfyUI 对**完全相同的 prompt + seed** 会直接复用上次的节点输出：2.0 秒「完成」，
不报错、不告警，画面是上一次的。批量出片时两镜提示词恰好相同、seed 又撞上，
第二镜就会静默变成第一镜的画面 —— 这种错误只有人眼能发现。

以前 batch 用 `int(time.time()) % 2e9`（秒级），单机串行时不会撞；一旦并发
（多进程分段跑、或未来上调度器）同秒启动的两个进程必然同种子。

这里钉住派生规则：`批次基底 + 镜序`。同批唯一、可追溯、重跑可复现。
"""
from __future__ import annotations

import pathlib

BATCH = pathlib.Path(__file__).resolve().parents[1] / "comfy_batch_video.py"
SINGLE = pathlib.Path(__file__).resolve().parents[1] / "comfy_local_video.py"


def test_batch_derives_seed_per_shot() -> None:
    src = BATCH.read_text(encoding="utf-8")
    assert "base_seed = int(time.time() * 1000)" in src
    assert "shot_seed = base_seed + i" in src
    assert "seed=shot_seed" in src


def test_batch_no_longer_uses_second_level_seed() -> None:
    src = BATCH.read_text(encoding="utf-8")
    assert "seed=int(time.time()) % 2_000_000_000" not in src, \
        "秒级种子在并发下会撞，且撞了不报错（命中节点缓存）"


def test_single_uses_millisecond_seed() -> None:
    src = SINGLE.read_text(encoding="utf-8")
    assert "int(time.time() * 1000) % 2_000_000_000" in src
    assert "else int(time.time()) % 2_000_000_000" not in src


def test_batch_records_seed_for_traceability() -> None:
    """seed 要写进批次记录：事后才能回答「这镜是用哪个种子出的」。"""
    src = BATCH.read_text(encoding="utf-8")
    assert '"seed": shot_seed' in src
