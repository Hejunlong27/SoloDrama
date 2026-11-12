# -*- coding: utf-8 -*-
"""媒体生成任务的本地状态与 task ID 持久化。

设计边界
--------
* 只管理控制层状态，不调用任何图片/视频 API；
* 一个任务一个 JSON，落在 `<workspace>/.drama/media/`，文件系统仍是唯一数据源；
* 远端 task ID 一旦落盘，后续只能 poll/resume，不能再次 submit；
* 不持久化 API Key、Authorization 头或带签名的临时结果 URL；
* 预估价、供应商暂报 usage、后台最终结算分开保存；usage 不得冒充 actual_cost，未知不回退为 0。
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


def _normalize_record(rec: dict) -> dict:
    """Separate provisional provider usage from final settlement."""
    if not isinstance(rec, dict):
        return rec
    usage = rec.get("usage")
    if rec.get("provider_usage") is None and isinstance(usage, dict):
        rec["provider_usage"] = _clean(usage)
    if rec.get("provider_usage_cost") is None and isinstance(usage, dict):
        amount = usage.get("amount")
        if isinstance(amount, (int, float)) and not isinstance(amount, bool):
            rec["provider_usage_cost"] = {"amount": amount, "currency": str(usage.get("currency") or "")}
    settled = rec.get("settled_cost")
    if settled is None and rec.get("cost_source") in ("provider_backend", "manual_backend", "invoice"):
        legacy = rec.get("actual_cost")
        if isinstance(legacy, dict) and isinstance(legacy.get("amount"), (int, float)) and not isinstance(legacy.get("amount"), bool):
            settled = {"amount": legacy["amount"], "currency": str(legacy.get("currency") or "")}
            rec["settled_cost"] = settled
    if isinstance(settled, dict) and isinstance(settled.get("amount"), (int, float)) and not isinstance(settled.get("amount"), bool):
        rec["cost_status"] = "settled"
        rec["actual_cost"] = settled
    elif rec.get("cost_source") == "provider" and isinstance(rec.get("actual_cost"), dict):
        legacy = rec["actual_cost"]
        if isinstance(legacy.get("amount"), (int, float)) and not isinstance(legacy.get("amount"), bool):
            rec["provider_usage_cost"] = {"amount": legacy["amount"], "currency": str(legacy.get("currency") or "")}
        rec["actual_cost"] = None
        rec["cost_source"] = "unknown"
        rec["cost_status"] = "provisional"
    elif rec.get("provider_usage_cost") is not None:
        rec["cost_status"] = "provisional"
    else:
        rec["cost_status"] = rec.get("cost_status") or "unknown"
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
    return _normalize_record(data)


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
        "provider_usage": None,
        "provider_usage_cost": None,
        "settled_cost": None,
        "cost_status": "unknown",
        "settled_at": None,
        "settlement_note": "",
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
        rec = _normalize_record(rec)
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
            clean_usage = _clean(usage)
            rec["usage"] = clean_usage
            rec["provider_usage"] = clean_usage
            amount = usage.get("amount") if isinstance(usage, dict) else None
            currency = usage.get("currency") if isinstance(usage, dict) else None
            if isinstance(amount, (int, float)) and not isinstance(amount, bool):
                rec["provider_usage_cost"] = {"amount": amount, "currency": str(currency or "")}
                rec["cost_status"] = "provisional"
            elif normalized in _TERMINAL:
                rec["provider_usage_cost"] = None
                rec["cost_status"] = "unknown"
        if rec.get("cost_status") != "settled":
            rec["actual_cost"] = None
            rec["cost_source"] = "unknown"
        if artifacts is not None:
            # 只收本地相对路径；远端签名 URL 会过期，不能当持久产物。
            rec["artifacts"] = [str(x)[:500] for x in list(artifacts)[:50]]
        rec["error"] = str(error or "")[:500]
        if normalized != "unknown" and normalized != previous:
            _history(rec, normalized, "poll update")
        return _write(ws, rec)


def record_settlement(ws, local_id: str, amount, currency: str = "", *, source: str = "provider_backend", note: str = "") -> dict:
    """Record the final provider-backend invoice without replacing raw usage."""
    try:
        value = float(amount)
    except (TypeError, ValueError):
        raise MediaTaskError("结算金额无效：%r" % (amount,)) from None
    if value < 0 or value != value or value in (float("inf"), float("-inf")):
        raise MediaTaskError("结算金额必须是非负有限数字：%r" % (amount,))
    cur = str(currency or "").strip()
    if not cur:
        raise MediaTaskError("结算金额缺少币种")
    src = str(source or "provider_backend").strip()
    if not src:
        raise MediaTaskError("结算来源不能为空")
    with _LOCK:
        rec = _read(ws, local_id)
        settled = {"amount": value, "currency": cur}
        rec["settled_cost"] = settled
        rec["actual_cost"] = settled
        rec["cost_source"] = src
        rec["cost_status"] = "settled"
        rec["settled_at"] = time.time()
        rec["settlement_note"] = str(note or "")[:300]
        _history(rec, "cost_settled", note or "backend invoice reconciled")
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
        "provider_usage": rec.get("provider_usage"),
        "provider_usage_cost": rec.get("provider_usage_cost"),
        "settled_cost": rec.get("settled_cost"),
        "actual_cost": rec.get("actual_cost"),
        "cost_source": rec.get("cost_source") or "unknown",
        "cost_status": rec.get("cost_status") or "unknown",
    }
