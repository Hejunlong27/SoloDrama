# -*- coding: utf-8 -*-
"""媒体生成任务的本地状态与 task ID 持久化。

设计边界
--------
* 只管理控制层状态，不调用任何图片/视频 API；
* 一个任务一个 JSON，落在 `<workspace>/.drama/media/`，文件系统仍是唯一数据源；
* 远端 task ID 一旦落盘，后续只能 poll/resume，不能再次 submit；
* 不持久化 API Key、Authorization 头或带签名的临时结果 URL；
* 预估价、最高允许价、实际金额分开保存，未知不回退为 0。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path


class MediaTaskError(ValueError):
    pass


_SCHEMA_VERSION = 1
_LOCK = threading.RLock()
_ID_RE = re.compile(r"^mt_[A-Za-z0-9_-]{8,40}$")
_STATUS = {
    "not_start": "queued", "submitted": "queued", "queued": "queued",
    "in_progress": "running", "running": "running", "processing": "running",
    "success": "succeeded", "succeeded": "succeeded", "completed": "succeeded",
    "failure": "failed", "failed": "failed", "error": "failed",
    "canceled": "canceled", "cancelled": "canceled",
}
_TERMINAL = {"succeeded", "failed", "canceled"}
_SECRET_KEYS = {"api_key", "apikey", "authorization", "auth", "token", "secret", "key"}


def root(ws) -> Path:
    return Path(ws).resolve() / ".drama" / "media"


def _path(ws, local_id: str) -> Path:
    ident = str(local_id or "").strip()
    if not _ID_RE.fullmatch(ident):
        raise MediaTaskError("非法媒体任务 id：%s" % (ident or "（空）"))
    return root(ws) / (ident + ".json")


def _clean(value, depth=0):
    """递归去掉密钥字段；保留业务参数与成本证据。"""
    if depth > 8:
        return "[depth-limited]"
    if isinstance(value, dict):
        out = {}
        for key, val in value.items():
            if str(key).lower() in _SECRET_KEYS:
                continue
            out[str(key)] = _clean(val, depth + 1)
        return out
    if isinstance(value, list):
        return [_clean(v, depth + 1) for v in value[:200]]
    if isinstance(value, tuple):
        return [_clean(v, depth + 1) for v in value[:200]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _write(ws, rec: dict) -> dict:
    target = _path(ws, rec["id"])
    target.parent.mkdir(parents=True, exist_ok=True)
    rec["updated_at"] = time.time()
    tmp = target.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, target)
    return rec


def _read(ws, local_id: str) -> dict:
    target = _path(ws, local_id)
    try:
        data = json.loads(target.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise MediaTaskError("媒体任务不存在：%s" % local_id) from None
    except (OSError, json.JSONDecodeError) as exc:
        raise MediaTaskError("媒体任务记录损坏：%s（%s）" % (local_id, exc)) from exc
    if not isinstance(data, dict) or data.get("schema_version") != _SCHEMA_VERSION:
        raise MediaTaskError("媒体任务版本不支持：%s" % local_id)
    return data


def _history(rec, status, note=""):
    rec.setdefault("history", []).append({
        "at": time.time(), "status": status, "note": str(note or "")[:300],
    })
    rec["history"] = rec["history"][-50:]


def normalize_status(raw: str) -> str:
    key = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    return _STATUS.get(key, "unknown")


def create(ws, *, kind: str, model: str, provider_id: str = "", request=None,
           purpose: str = "", episode: str = "", shot_id: str = "",
           estimate=None, max_cost=None) -> dict:
    kind = str(kind or "").strip().lower()
    if kind not in ("image", "video"):
        raise MediaTaskError("kind 只能是 image / video")
    model = str(model or "").strip()
    if not model:
        raise MediaTaskError("model 不能为空")
    request_obj = _clean(request or {})
    digest = hashlib.sha256(json.dumps(request_obj, ensure_ascii=False,
                                       sort_keys=True).encode("utf-8")).hexdigest()
    ident = "mt_%s_%s" % (time.strftime("%Y%m%d%H%M%S"), uuid.uuid4().hex[:8])
    rec = {
        "schema_version": _SCHEMA_VERSION,
        "id": ident,
        "project": str(Path(ws).resolve()),
        "kind": kind,
        "provider_id": str(provider_id or ""),
        "model": model,
        "purpose": str(purpose or ""),
        "episode": str(episode or ""),
        "shot_id": str(shot_id or ""),
        "status": "planned",
        "remote_task_id": "",
        "request": request_obj,
        "request_sha": digest,
        "estimate": _clean(estimate) if estimate is not None else None,
        "max_cost": _clean(max_cost) if max_cost is not None else None,
        "actual_cost": None,
        "cost_source": "unknown",
        "usage": None,
        "progress": None,
        "artifacts": [],
        "error": "",
        "raw_status": "",
        "submissions": 0,
        "created_at": time.time(),
        "updated_at": time.time(),
        "history": [],
    }
    _history(rec, "planned", "task record created")
    with _LOCK:
        return _write(ws, rec)


def get(ws, local_id: str) -> dict:
    with _LOCK:
        return _read(ws, local_id)


def list_tasks(ws, *, limit=100, kind=None, status=None) -> list:
    base = root(ws)
    if not base.is_dir():
        return []
    out = []
    for path in base.glob("mt_*.json"):
        try:
            rec = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(rec, dict) or rec.get("schema_version") != _SCHEMA_VERSION:
            continue
        if kind and rec.get("kind") != str(kind):
            continue
        if status and rec.get("status") != str(status):
            continue
        out.append(rec)
    out.sort(key=lambda r: float(r.get("updated_at") or 0), reverse=True)
    return out[:max(1, min(int(limit or 100), 500))]


def set_estimate(ws, local_id: str, estimate, *, max_cost=None) -> dict:
    with _LOCK:
        rec = _read(ws, local_id)
        if rec.get("remote_task_id"):
            raise MediaTaskError("任务已提交，不能修改报价")
        rec["estimate"] = _clean(estimate) if estimate is not None else None
        if max_cost is not None:
            rec["max_cost"] = _clean(max_cost)
        if rec.get("status") == "planned":
            rec["status"] = "estimated"
            _history(rec, "estimated", "quote stored")
        return _write(ws, rec)


def mark_submitted(ws, local_id: str, remote_task_id: str, *, authorized=False,
                   raw_status: str = "submitted") -> dict:
    remote_task_id = str(remote_task_id or "").strip()
    if not remote_task_id:
        raise MediaTaskError("远端 task_id 不能为空")
    if not authorized:
        raise MediaTaskError("提交媒体任务前必须显式授权")
    with _LOCK:
        rec = _read(ws, local_id)
        existing = str(rec.get("remote_task_id") or "")
        if existing:
            if existing == remote_task_id:
                return rec
            raise MediaTaskError("任务已提交到 %s，拒绝重复提交" % existing)
        rec["remote_task_id"] = remote_task_id
        rec["submissions"] = int(rec.get("submissions") or 0) + 1
        rec["status"] = normalize_status(raw_status)
        if rec["status"] == "unknown":
            rec["status"] = "queued"
        rec["raw_status"] = str(raw_status or "")
        _history(rec, rec["status"], "remote task submitted")
        return _write(ws, rec)


def update_remote(ws, local_id: str, *, raw_status: str, progress=None,
                  usage=None, artifacts=None, error: str = "") -> dict:
    normalized = normalize_status(raw_status)
    with _LOCK:
        rec = _read(ws, local_id)
        previous = rec.get("status") or ""
        rec["raw_status"] = str(raw_status or "")
        if normalized != "unknown":
            rec["status"] = normalized
        if progress is not None:
            rec["progress"] = _clean(progress)
        if usage is not None:
            rec["usage"] = _clean(usage)
            amount = usage.get("amount") if isinstance(usage, dict) else None
            currency = usage.get("currency") if isinstance(usage, dict) else None
            if isinstance(amount, (int, float)) and not isinstance(amount, bool):
                rec["actual_cost"] = {"amount": amount, "currency": str(currency or "")}
                rec["cost_source"] = "provider"
            elif normalized in _TERMINAL:
                rec["actual_cost"] = None
                rec["cost_source"] = "unknown"
        if artifacts is not None:
            # 只收本地相对路径；远端签名 URL 会过期，不能当持久产物。
            rec["artifacts"] = [str(x)[:500] for x in list(artifacts)[:50]]
        rec["error"] = str(error or "")[:500]
        if normalized != "unknown" and normalized != previous:
            _history(rec, normalized, "poll update")
        return _write(ws, rec)


def resume_info(ws, local_id: str) -> dict:
    rec = _read(ws, local_id)
    remote = str(rec.get("remote_task_id") or "")
    status = str(rec.get("status") or "")
    return {
        "id": rec["id"],
        "status": status,
        "remote_task_id": remote,
        "terminal": status in _TERMINAL,
        "needs_poll": bool(remote and status not in _TERMINAL),
        "can_resubmit": not remote and status in ("planned", "estimated", "failed"),
        "request_sha": rec.get("request_sha") or "",
        "estimate": rec.get("estimate"),
        "max_cost": rec.get("max_cost"),
        "actual_cost": rec.get("actual_cost"),
        "cost_source": rec.get("cost_source") or "unknown",
    }
