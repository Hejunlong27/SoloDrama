# -*- coding: utf-8 -*-
"""zzai_batch.py —— 真真AI（ZZAI）批量任务内核：报价 → 授权 → 提交 → 轮询 → 落盘 → 记账

它解决的是什么
--------------
`gen_boards.py` 里那段 ZZAI 逻辑（上传参考图 → estimate → --yes/--max-cost 闸门 →
submit → poll → download → 写 `.drama/media/*.json`）在 2026-11 已经被复制到第三处。
每复制一次就多一处「哪份才是真闸门」的歧义：资产图放过了超额，视频又拦不住。

本模块把它抽成**一份**：
  * `upload_refs()`  参考图去重上传（同一进程内按绝对路径缓存）
  * `quote()`        单任务报价；`estimate_available=False` 视为「不知道价」，不放行
  * `guard()`        `--yes` + `--max-cost` 双闸门 + 报价超限即拒
  * `run_one()`      提交-轮询-下载-写任务记录，失败不抛给上层（批量要能续跑）

纪律
----
1. **不在日志/任务文件里写 API Key**（`ZZAIClient` 已做遮蔽，这里只透传对象）。
2. **没有 `--max-cost` 一律不提交**：真实计费通道必须有单任务上限，否则一次手滑就是全季账单。
3. **产物先落 `.part` 再原子替换**（由 `ZZAIClient.download` 负责），中断不留半张图。
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import time
import uuid

try:                                                     # 允许 `python -m` 与直接脚本两种用法
    from .zzai import ZZAIClient, ZZAIError               # type: ignore
except ImportError:                                       # pragma: no cover
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
    from stages.media_api.zzai import ZZAIClient, ZZAIError  # type: ignore


# ---------------------------------------------------------------------------
# 任务记录（与 gen_boards.py 的历史字段保持一致，便于 Studio 统一读）
# ---------------------------------------------------------------------------
def _task_dir(ws: pathlib.Path) -> pathlib.Path:
    d = pathlib.Path(ws) / ".drama" / "media"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write(ws: pathlib.Path, rec: dict) -> None:
    rec["updated_at"] = time.time()
    p = _task_dir(ws) / (rec["id"] + ".json")
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def task_new(ws, *, kind: str, model: str, purpose: str, request: dict,
             estimate, max_cost, ep: str = "", shot_id: str = "",
             provider: str = "zzai", dest: str = "") -> dict:
    rid = "mt_%s_%s" % (time.strftime("%Y%m%d%H%M%S"), uuid.uuid4().hex[:8])
    digest = hashlib.sha256(json.dumps(request, ensure_ascii=False,
                                       sort_keys=True).encode("utf-8")).hexdigest()
    rec = {
        "schema_version": 1, "id": rid, "project": str(pathlib.Path(ws).resolve()),
        "kind": kind, "provider_id": provider, "model": model, "purpose": purpose,
        "episode": ep, "shot_id": shot_id, "status": "planned",
        "dest": str(dest), "remote_task_id": "", "request": request, "request_sha": digest,
        "estimate": estimate, "max_cost": max_cost, "actual_cost": None,
        "cost_source": "unknown", "usage": None, "progress": None,
        "artifacts": [], "error": "", "raw_status": "", "submissions": 0,
        "created_at": time.time(), "updated_at": time.time(),
        "history": [{"at": time.time(), "status": "planned", "note": "%s task created" % purpose}],
    }
    _write(ws, rec)
    return rec


def task_update(ws, rec: dict, *, status: str, remote_task_id: str = "",
                progress=None, usage=None, artifact: str = "", error: str = "") -> None:
    rec["status"] = status
    rec["raw_status"] = status
    if remote_task_id:
        rec["remote_task_id"] = str(remote_task_id)
        rec["submissions"] = max(1, int(rec.get("submissions") or 0))
    if progress is not None:
        rec["progress"] = progress
    if usage is not None:
        rec["usage"] = usage
        if isinstance(usage, dict) and isinstance(usage.get("amount"), (int, float)):
            rec["actual_cost"] = {"amount": usage["amount"],
                                  "currency": str(usage.get("currency") or "")}
            rec["cost_source"] = "provider"
    if artifact:
        rec["artifacts"] = [artifact]
    if error:
        rec["error"] = str(error)[:500]
    rec.setdefault("history", []).append({"at": time.time(), "status": status,
                                          "note": "%s poll" % rec.get("purpose", "")})
    rec["history"] = rec["history"][-50:]
    _write(ws, rec)


# ---------------------------------------------------------------------------
# 参考图上传（进程内缓存：同一张角色卡在 179 镜里会被复用 179 次）
# ---------------------------------------------------------------------------
class Uploader:
    def __init__(self, client: ZZAIClient):
        self.client = client
        self.cache: dict = {}

    def url_of(self, ref) -> str:
        s = str(ref)
        if s.startswith(("http://", "https://")):
            return s
        p = pathlib.Path(s).resolve()
        if not p.is_file():
            raise ZZAIError("config", "参考图不存在：%s" % p)
        key = str(p)
        if key not in self.cache:
            self.cache[key] = self.client.upload(str(p))
        return self.cache[key]

    def urls(self, refs) -> list:
        return [self.url_of(r) for r in refs]


# ---------------------------------------------------------------------------
# 报价与闸门
# ---------------------------------------------------------------------------
def quote(client: ZZAIClient, kind: str, payload: dict) -> dict:
    est = client.estimate(kind, payload)
    if not isinstance(est, dict):
        return {"estimate_available": False, "raw": est}
    return est


def guard(*, yes: bool, max_cost, amounts_single: list, label: str = "") -> tuple:
    """→ (放行?, 说明)。`yes=False` 或 `max_cost=None` 一律不放行。"""
    if not yes:
        return False, "真实提交需要 --yes（当前为干跑/报价模式）"
    if max_cost is None:
        return False, "真实提交必须给 --max-cost（单任务 CNY 上限）"
    over = [a for a in amounts_single if isinstance(a, (int, float)) and float(a) > float(max_cost)]
    if over:
        return False, ("有 %d 个任务报价超过 --max-cost %s（最高 %s）；"
                       "要么调高 --max-cost，要么先缩量" % (len(over), max_cost, max(over)))
    unknown = [a for a in amounts_single if a is None]
    if unknown:
        return False, ("有 %d 个任务拿不到报价（estimate_available=False）："
                       "不知道价就不提交" % len(unknown))
    return True, label or "闸门通过"


# ---------------------------------------------------------------------------
# 单任务执行
# ---------------------------------------------------------------------------
def run_one(ws, client: ZZAIClient, *, kind: str, model: str, payload: dict,
            estimate, max_cost, purpose: str, dest, ep: str = "", shot_id: str = "",
            poll_seconds: float = 3.0, timeout_s: float = 3600.0,
            quiet: bool = False) -> tuple:
    """→ (ok: bool, 说明: str)。下载成功才算成功；任何异常都收敛成 False。"""
    dest = pathlib.Path(dest)
    rec = task_new(ws, kind=kind, model=model, purpose=purpose, request=payload,
                   estimate=estimate, max_cost=max_cost, ep=ep, shot_id=shot_id,
                   dest=str(dest))
    # ★ 2026-11-13 压测：并发 20 时约 5% 的提交会被上游直接拒——
    #   `当前分组上游负载已饱和，请稍后再试`。这**不是**参数错误，退避几秒重提即可，
    #   而且此时还没生成任务、不产生费用。所以这里做「饱和退避重试」，
    #   让高并发下的偶发拒绝变成可自愈，而不是把整镜判死。
    sub = None
    last_err = None
    for attempt in range(4):
        try:
            sub = client.submit(kind, payload, max_cost=max_cost, authorized=True)
            break
        except ZZAIError as exc:
            last_err = exc
            msg = str(exc)
            if ("饱和" in msg or "saturat" in msg.lower() or exc.status == 429) and attempt < 3:
                time.sleep(4 * (attempt + 1))
                continue
            task_update(ws, rec, status="failed", error=msg)
            return False, "提交失败：%s" % msg
    if sub is None:
        task_update(ws, rec, status="failed", error=str(last_err))
        return False, "提交失败：%s" % last_err
    tid = sub["task_id"]
    task_update(ws, rec, status="queued", remote_task_id=tid)
    deadline = time.time() + float(timeout_s)
    result = None
    last_note = ""
    while time.time() < deadline:
        time.sleep(max(0.2, float(poll_seconds)))
        try:
            result = client.poll(kind, tid)
        except ZZAIError as exc:
            if exc.retryable:
                continue
            task_update(ws, rec, status="failed", remote_task_id=tid, error=str(exc))
            return False, "轮询失败：%s" % exc
        task_update(ws, rec, status=result["status"], remote_task_id=tid,
                    progress=result.get("progress"), usage=result.get("usage"),
                    error=result.get("error") or "")
        if not quiet and result.get("progress") not in (None, last_note):
            last_note = result.get("progress")
            print("        … %s" % last_note)
        if result["status"] in ("succeeded", "failed", "canceled"):
            break
    if not result:
        task_update(ws, rec, status="failed", remote_task_id=tid, error="轮询超时")
        return False, "轮询超时（%ss）" % timeout_s
    if result["status"] != "succeeded":
        return False, "终态 %s：%s" % (result["status"], result.get("error") or "无错误信息")
    if not result.get("result_url"):
        task_update(ws, rec, status="failed", remote_task_id=tid, error="无结果地址")
        return False, "成功但响应里没有结果地址"
    try:
        client.download(result["result_url"], dest)
    except ZZAIError as exc:
        task_update(ws, rec, status="failed", remote_task_id=tid, error=str(exc))
        return False, "下载失败：%s" % exc
    task_update(ws, rec, status="succeeded", remote_task_id=tid,
                progress=result.get("progress"), usage=result.get("usage"),
                artifact=str(dest))
    return True, str(dest)


def client_from_env(base_url: str | None = None) -> ZZAIClient:
    """建客户端；缺 Key 时给出可照抄的修法（不打印 Key 本身）。"""
    try:
        return ZZAIClient(base_url=base_url) if base_url else ZZAIClient()
    except ZZAIError:
        raise
    except Exception as exc:                              # noqa: BLE001
        raise ZZAIError("config", "无法初始化 ZZAI 客户端：%s" % exc) from exc
