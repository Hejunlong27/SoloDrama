"""cloud/pull.py —— 把远端 ComfyUI 已生成的产物捞回本地

为什么需要一个独立的「拉回」动作
--------------------------------
出片脚本本来就是**每镜跑完立刻下载**（`comfy_local_video.download()`），正常路径不需要
事后补救。但三条现实情况会让产物留在云上：

1. **下载失败但任务成功**：网络抖动、反代超时、磁盘写满。任务在 ComfyUI 那边是完成的，
   本地却没有文件 —— 一停机，这份产物就只剩「重跑一遍再花一次钱」。
2. **批次中途中断**：Ctrl-C、超时、守卫拒绝。已完成的镜在云上，本地只落了一部分。
3. **别人替你跑了**：同事在控制台点过一次，或你自己用 ComfyUI 网页跑的。

ComfyUI 的产物在 `<实例>/ComfyUI/output/`，通过 `GET /view?filename=&subfolder=&type=output`
取回。**没有列目录的 HTTP 接口**，唯一的索引是 `/history`（内存态，实例重启即清空）。
所以：

* 实例还活着 → `/history` 能列全，按名批量拉；
* `/history` 空了（重启过）→ 只能 `--file` 按文件名单取（文件仍在磁盘）；
* 实例被销毁且未保留磁盘 → **文件已不存在**，只能重跑。

这条约束决定了用法：**停机之前拉**。`drama video run --engine cloud` 已内置这一步
（`_run_cloud_task` 在 `with lease:` 内、退出前调用），这里是它和手动兜底共用的实现。
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys
import time
from urllib.parse import urlencode

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent


def _stages() -> None:
    p = ROOT / "stages"
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


# 产物后缀：视频为主，出图/分镜图也能一并捞
MEDIA_EXT = (".mp4", ".webm", ".mov", ".gif", ".webp", ".png", ".jpg", ".jpeg")

# ComfyUI 侧文件名里带镜号（批次提交时 prefix = `h3_<shot_id>`），
# 有了它才能把拉回来的文件**归位**成 `shot_001/final.mp4`，而不是堆在下载目录里。
SHOT_RE = re.compile(r"(shot[_-]?\d{1,4})", re.I)


def _shots_index(engine_out: pathlib.Path, ep: str) -> dict:
    """本地已有镜目录 → 便于把同名产物归位。"""
    idx = {}
    base = engine_out / ep
    if base.is_dir():
        for d in base.iterdir():
            if d.is_dir() and d.name.lower().startswith("shot"):
                idx[d.name.lower().replace("-", "_")] = d
    return idx


def discover(url: str, *, history: int = 200, timeout: float = 30.0) -> list:
    """列出远端 `/history` 里的全部产物。返回去重后的条目列表。

    只读，不下载。`history` 是条数上限（ComfyUI 的 `max_items`）。
    """
    _stages()
    import _comfy_http as Q

    base = str(url or "").rstrip("/")
    if not base:
        raise RuntimeError("要拉产物必须先知道实例地址（--url 或 COMFYUI_URL）")
    raw = Q.request(base + "/history?max_items=%d" % max(1, int(history)),
                    timeout=timeout, retries=2, tag="history")
    doc = json.loads(raw.decode("utf-8")) if raw else {}
    if not isinstance(doc, dict):
        return []

    out, seen = [], set()
    for pid, item in doc.items():
        if not isinstance(item, dict):
            continue
        for node_out in (item.get("outputs") or {}).values():
            if not isinstance(node_out, dict):
                continue
            for key in ("gifs", "videos", "images"):
                for f in (node_out.get(key) or []):
                    if not isinstance(f, dict):
                        continue
                    fn = str(f.get("filename") or "")
                    if not fn.lower().endswith(MEDIA_EXT):
                        continue
                    k = (pid, fn, str(f.get("subfolder") or ""))
                    if k in seen:
                        continue
                    seen.add(k)
                    out.append({"prompt_id": pid, "filename": fn,
                                "subfolder": str(f.get("subfolder") or ""),
                                "type": str(f.get("type") or "output")})
    return out


def _target(entry: dict, *, engine_out: pathlib.Path, ep: str,
            out_dir: pathlib.Path | None, shots: dict) -> pathlib.Path:
    """一条产物该落到哪。

    优先级：显式 `--out` > 按镜号归位 > `_cloud_pull/` 暂存。

    归位只做**无风险**的那种：本地已有 `shot_001/` 目录才往里放；
    没有就进暂存区，不替用户新建一套目录结构（新建会让「这镜到底跑没跑过」更难判断）。
    """
    fn = entry["filename"]
    ext = os.path.splitext(fn)[1] or ".mp4"
    if out_dir is not None:
        return out_dir / fn
    m = SHOT_RE.search(fn)
    if ep:
        sid = (m.group(1).lower().replace("-", "_") if m else "")
        if sid and sid in shots:
            return shots[sid] / ("final" + ext)
    return engine_out / "_cloud_pull" / fn


def pull(ws, *, ep: str = "", url: str = "", out_dir: str = "",
         history: int = 200, force: bool = False, dry_run: bool = False,
         filename: str = "", subfolder: str = "", timeout: float = 600.0) -> dict:
    """把远端产物拉回本地。幂等：已存在且非空即跳过（`force=True` 才覆盖）。

    参数
    ----
    ws        剧目录（用来决定落点）。给空则只下到 `out_dir`。
    ep        集号（`ep01`）；给了才能按镜号归位。
    url       实例地址；空则用 `COMFYUI_URL`。
    filename  只拉这一个文件（`/history` 已清空时的唯一办法）。
    """
    _stages()
    import _comfy_http as Q
    import _layout as L

    url = str(url or os.environ.get("COMFYUI_URL") or "").rstrip("/")
    if not url:
        return {"ok": False, "reason": "没有实例地址（--url 或 COMFYUI_URL）",
                "found": 0, "downloaded": [], "skipped": [], "failed": []}
    # ★ `_comfy_http.download()` 内部是 `base_url() + path`，**不认绝对 URL**
    #   （它是全仓唯一流式写盘的调用点，为了 Range 续传单独实现，地址取环境变量）。
    #   所以这里显式把目标机写进 COMFYUI_URL，再传相对路径 —— 否则会拼成
    #   `https://host/view?/view?...` 这种必然 404 的地址。
    #   进程级设置是有意的：本次调用从头到尾只处理这一台机器。
    os.environ["COMFYUI_URL"] = url

    ws_p = pathlib.Path(ws).expanduser() if str(ws or "").strip() else None
    engine_out = (L.out_dir(ws_p) if ws_p else pathlib.Path.cwd() / "_cloud_pull")
    out_p = pathlib.Path(out_dir).expanduser() if str(out_dir or "").strip() else None
    ep = str(ep or "").strip()
    shots = _shots_index(engine_out, ep) if ep else {}

    if filename:
        entries = [{"prompt_id": "", "filename": filename,
                    "subfolder": subfolder, "type": "output"}]
    else:
        entries = discover(url, history=history)
    if not entries:
        return {"ok": True, "reason": "远端 history 里没有产物"
                                      "（实例重启过？用 --file 按文件名单取）",
                "found": 0, "downloaded": [], "skipped": [], "failed": [], "url": url}

    got, skipped, failed = [], [], []
    for e in entries:
        dst = _target(e, engine_out=engine_out, ep=ep, out_dir=out_p, shots=shots)
        exists = dst.is_file() and dst.stat().st_size > 0
        if exists and not force:
            skipped.append({"filename": e["filename"], "path": str(dst),
                            "size": dst.stat().st_size})
            continue
        if dry_run:
            got.append({"filename": e["filename"], "path": str(dst), "dry_run": True})
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        qs = urlencode({"filename": e["filename"],
                        "subfolder": e.get("subfolder", ""),
                        "type": e.get("type", "output")})
        try:
            Q.download("/view?" + qs, str(dst), timeout=timeout, retries=3)
            size = dst.stat().st_size if dst.is_file() else 0
            if size <= 0:
                raise RuntimeError("下载后文件为空")
            got.append({"filename": e["filename"], "path": str(dst), "size": size,
                        "prompt_id": e.get("prompt_id", "")})
        except Exception as exc:                              # noqa: BLE001
            failed.append({"filename": e["filename"], "path": str(dst),
                           "error": "%s: %s" % (type(exc).__name__,
                                                str(exc).splitlines()[0][:160])})

    res = {"ok": not failed, "url": url, "found": len(entries),
           "downloaded": got, "skipped": skipped, "failed": failed,
           "engine_out": str(engine_out)}
    if got or failed:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        idx_dir = out_p or (engine_out / "_cloud_pull")
        try:
            idx_dir.mkdir(parents=True, exist_ok=True)
            idx = idx_dir / ("pull-%s.json" % stamp)
            idx.write_text(json.dumps({"_note": "云端产物回传记录（本文件自动生成）",
                                       "at": stamp, **res}, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            res["index"] = str(idx)
        except OSError:
            pass
    return res


def local_gaps(ws, ep: str) -> dict:
    """本地这一集还有哪些镜没有成片。用于「停机前确认」。"""
    _stages()
    import _layout as L

    engine_out = L.out_dir(pathlib.Path(ws).expanduser())
    base = engine_out / str(ep or "")
    have, missing = [], []
    if base.is_dir():
        for d in sorted(base.iterdir()):
            if not (d.is_dir() and d.name.lower().startswith("shot")):
                continue
            f = d / "final.mp4"
            (have if (f.is_file() and f.stat().st_size > 0) else missing).append(d.name)
    return {"ep": ep, "have": have, "missing": missing,
            "path": str(base), "complete": bool(have) and not missing}


def format_result(res: dict) -> str:
    """给人看的一段话（CLI 与 drama 共用，避免两处措辞分叉）。"""
    if not res.get("ok") and res.get("reason"):
        return "[FAIL] %s" % res["reason"]
    lines = ["远端产物 %d 个：新拉回 %d ｜ 已存在 %d ｜ 失败 %d"
             % (res.get("found", 0), len(res.get("downloaded") or []),
                len(res.get("skipped") or []), len(res.get("failed") or []))]
    for x in (res.get("downloaded") or [])[:8]:
        lines.append("  + %s → %s（%.1f MB）"
                     % (x["filename"], x["path"],
                        (x.get("size") or 0) / 1024 / 1024))
    if len(res.get("downloaded") or []) > 8:
        lines.append("  … 另有 %d 个" % (len(res["downloaded"]) - 8))
    for x in (res.get("failed") or [])[:6]:
        lines.append("  ! %s：%s" % (x["filename"], x["error"]))
    if res.get("skipped"):
        lines.append("  （已存在的按幂等跳过；要覆盖加 --force）")
    if res.get("index"):
        lines.append("  记录：%s" % res["index"])
    return "\n".join(lines)
