# -*- coding: utf-8 -*-
"""inflight.py —— 批次级「在途任务」与「待补下载」两份台账（纯标准库）

为什么需要它（反馈 P0-7 / P1-7）
--------------------------------
两个真实事故，根因都是「钱花了、状态丢了」：

**P0-7 漏镜**：EP39 的 SC02 在日志里既无 OK 也无 FAIL，40 集跑完后才发现少了一镜。
  机制：续跑判定只看「本地有没有 `scNN.mp4`」。任务已提交（钱已花）、进程在轮询中被杀
  → 本地无产物、无记录 → 下一轮既不进「已完成集」，也不进「失败集」，**静默漏掉**。

**P1-7 白跑**：AI 站 8 秒任务 SUCCESS（36 币已扣），下载阶段 `WinError 10054`，
  脚本抛异常退出，产物未落盘。任务其实成功了，只是没人记得去哪取。

本模块把「提交成功的那一刻」与「产物没拿到」都落成文件，使续跑可以**只补、不重提**：

    <批次>/inflight.json          {shot_id: {task_id, kind, submitted_at}}
    <批次>/pending_download.json  [{shot_id, task_id, url, dest, error, at}]

纪律：
* 提交成功后**立刻**写 inflight（此时 taskId 已知，崩溃后仍可查）；
* 拿到终态（成功且落盘 / 明确失败）后**立刻**移除 inflight；
* 下载失败不丢 URL —— 写 pending_download，由 `--resume-download` 只重下、不重提；
* 写盘一律「临时文件 + os.replace」，进程被杀也不会留下半截 JSON。
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

INFLIGHT_NAME = "inflight.json"
PENDING_NAME = "pending_download.json"


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _load(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        d = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return d if isinstance(d, dict) else {}


def _dump(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


class Inflight:
    """在途任务台账：`{shot_id: {task_id, kind, submitted_at, duration_s}}`。"""

    def __init__(self, batch_dir: str | Path) -> None:
        self.path = Path(batch_dir) / INFLIGHT_NAME
        self._lock: Optional[asyncio.Lock] = None

    def _guard(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def load(self) -> Dict[str, Dict[str, Any]]:
        return dict(_load(self.path).get("items") or {})

    async def add(self, shot_id: str, task_id: str, kind: str = "video",
                  duration_s: Any = None) -> None:
        async with self._guard():
            d = _load(self.path)
            items = dict(d.get("items") or {})
            items[str(shot_id)] = {
                "task_id": str(task_id),
                "kind": kind,
                "submitted_at": _now(),
                "duration_s": duration_s,
            }
            _dump(self.path, {"_note": "已提交但未回收结果的任务（崩溃后据此续跑，不重复提交）",
                              "updated_at": _now(), "items": items})

    async def remove(self, shot_id: str) -> None:
        async with self._guard():
            d = _load(self.path)
            items = dict(d.get("items") or {})
            if items.pop(str(shot_id), None) is None:
                return
            _dump(self.path, {"_note": d.get("_note") or "已提交但未回收结果的任务",
                              "updated_at": _now(), "items": items})


class PendingDownloads:
    """待补下载台账：一条一个「任务成功但产物没落盘」的记录。"""

    def __init__(self, batch_dir: str | Path) -> None:
        self.path = Path(batch_dir) / PENDING_NAME
        self._lock: Optional[asyncio.Lock] = None

    def _guard(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def load(self) -> List[Dict[str, Any]]:
        items = _load(self.path).get("items")
        return [it for it in (items or []) if isinstance(it, dict)]

    async def add(self, *, shot_id: str, task_id: Optional[str], url: str,
                  dest: str, error: str = "") -> None:
        async with self._guard():
            items = self.load()
            for it in items:
                if it.get("shot_id") == shot_id and it.get("dest") == dest:
                    it.update({"task_id": task_id, "url": url, "dest": dest,
                               "error": error, "at": _now()})
                    break
            else:
                items.append({"shot_id": shot_id, "task_id": task_id, "url": url,
                              "dest": dest, "error": error, "at": _now()})
            _dump(self.path, {"_note": "任务已成功但产物未落盘；用 --resume-download 只重下、不重提",
                              "updated_at": _now(), "items": items})

    async def remove(self, shot_id: str) -> None:
        async with self._guard():
            items = [it for it in self.load() if it.get("shot_id") != shot_id]
            _dump(self.path, {"_note": "任务已成功但产物未落盘；用 --resume-download 只重下、不重提",
                              "updated_at": _now(), "items": items})
