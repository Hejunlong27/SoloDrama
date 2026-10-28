# -*- coding: utf-8 -*-
"""artifacts.py —— 工作区文件的安全访问层（目录清单 / 文本预览 / 媒体流）

为什么需要独立一层
------------------
Studio 要展示缩略图、成片预览、提示词原文，但**浏览器绝不能直接读任意路径**。
本模块是唯一允许「按相对路径取工作区文件」的入口，纪律如下：

  1. **根必须显式**：调用方给 `<ws>`，本模块用 `stages/_layout.py` 计算阶段目录，
     不允许调用方传绝对路径或自身拼 `..`；
  2. **realpath 后校验**：`resolve()` 之后再判前缀，Windows 的 junction / 符号链接
     解析后会落到真实目标，因此能挡住「链接到 C:\\Windows」这类逃逸；
  3. **扩展名白名单**：媒体 6 类 + 文本 3 类，`.py/.env/.key/.pem/.json` 一律不服务
     （工作区里的 JSON 虽无密钥，但也没有预览需求）；
  4. **大小与条数上限**：文本 ≤ 512KB、目录 ≤ 500 条，防止把浏览器拖死。

不做的事：不生成缩略图（不引 Pillow 到 Web 层）、不转码、不复制文件。
"""
from __future__ import annotations

import os
from pathlib import Path

# 可内联展示的媒体类型（浏览器原生支持，不需要转码）
MEDIA_TYPES = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
}

# 可当文本预览的类型（不含 .json：没有预览需求，且避免误传结构化配置）
TEXT_TYPES = {".md": "text/markdown; charset=utf-8", ".txt": "text/plain; charset=utf-8",
              ".ass": "text/plain; charset=utf-8", ".srt": "text/plain; charset=utf-8",
              ".vtt": "text/vtt; charset=utf-8"}

TEXT_MAX_BYTES = 512 * 1024
LIST_MAX_ITEMS = 500

# 阶段目录之外的允许项（工作区根下的状态文件，只用于「关于本项目」展示）
ROOT_FILES = {"project.json", "brief.json", "layout.json", "project-setup.json",
              "style-plan.json", "model-plan.json", "workflow-state.json",
              "pipeline-state.json", "config.local.json", "README.md"}


class PathDenied(Exception):
    """路径越界 / 类型不允许。调用方应转成 403 或 404，且**不回显真实路径**。"""


def _deny(msg: str = "路径不被允许") -> PathDenied:
    return PathDenied(msg)


def _under(root: Path, target: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def safe_root(ws) -> Path:
    """工作区根：必须存在、必须是目录，且必须像一个工作区。"""
    p = Path(str(ws)).expanduser()
    if not p.is_dir():
        raise _deny("工作区不存在")
    p = p.resolve()
    markers = ("layout.json", "video-pipeline", "project-setup.json", "model-plan.json")
    if not any((p / m).exists() for m in markers):
        raise _deny("该目录不像短剧工作区")
    if p == Path(p.anchor):                       # 盘符根
        raise _deny("不允许把盘符根作为工作区")
    return p


def safe_rel(ws, rel: str, *, extra_roots=()) -> Path:
    """把「相对路径」解析成绝对路径，并保证落在允许的根内。"""
    root = safe_root(ws)
    raw = (rel or "").replace("\\", "/").strip()
    if not raw or raw.startswith("/") or ":" in raw.split("/")[0]:
        raise _deny("只接受工作区内的相对路径")
    # 先做纯字符串层面的 `..` 拒绝（不依赖解析，意图明确）
    parts = [x for x in raw.split("/") if x not in ("", ".")]
    if any(x == ".." for x in parts):
        raise _deny("路径不允许包含 ..")
    target = root.joinpath(*parts)
    try:
        resolved = target.resolve()
    except OSError:
        raise _deny("路径无法解析")
    allowed = [root] + [Path(r).resolve() for r in extra_roots if r]
    if not any(_under(r, resolved) for r in allowed):
        raise _deny("路径越界")
    if resolved.is_symlink():                      # resolve 后仍为链接（极少见）也拒绝
        raise _deny("不服务符号链接")
    return resolved


def kind_of(p: Path) -> str:
    ext = p.suffix.lower()
    if ext in MEDIA_TYPES:
        return "image" if MEDIA_TYPES[ext].startswith("image/") else (
            "video" if MEDIA_TYPES[ext].startswith("video/") else "audio")
    if ext in TEXT_TYPES:
        return "text"
    return "other"


def media_type(p: Path) -> str:
    ext = p.suffix.lower()
    mt = MEDIA_TYPES.get(ext) or TEXT_TYPES.get(ext)
    if not mt:
        raise _deny("不支持的文件类型：%s" % (ext or "无扩展名"))
    return mt


def is_servable(p: Path) -> bool:
    return p.suffix.lower() in MEDIA_TYPES or p.suffix.lower() in TEXT_TYPES


# 已经在标准位置、由资产页专门展示的目录（散图扫描要跳过，否则同一张图出现两次）
_STD_ASSET_DIRS = ("04-资产", "06-提示词")
# 工程/产物目录：里面有图也不是「用户资产」，扫进来只会让人误判
_SKIP_LOOSE_DIRS = {".git", "__pycache__", "node_modules", "logs", "db", "tools",
                    "workflows", "video-pipeline", "07-成片", "08-成片", "09-发行"}


def loose_images(ws, *, limit: int = 80) -> dict:
    """标准目录之外的图片（根目录 + 一层子目录）。**只读，不移动任何文件**。

    为什么需要它：真实项目常常把图直接丢在剧目录根下（"六月.png"、"加油站.png"），
    而资产页只读 `04-资产/{characters,scenes,props}` → 用户打开资产中心是**空的**，
    明明有几十张图却显示「还没有图片」。这不是数据缺失，是视图太窄。

    为什么不自动归档：移动用户文件属于破坏性操作。这里只报告位置，归档由用户决定。
    """
    root = safe_root(ws)
    items, groups, truncated = [], {}, False

    def add(p: Path) -> None:
        nonlocal truncated
        if len(items) >= limit:
            truncated = True
            return
        if not p.is_file() or kind_of(p) != "image" or not is_servable(p):
            return
        try:
            st = p.stat()
            rel = p.relative_to(root).as_posix()
        except (OSError, ValueError):
            return
        where = "" if p.parent == root else p.parent.relative_to(root).as_posix()
        label = where or "（根目录）"
        items.append({"name": p.name, "rel": rel, "where": where, "kind": "image",
                      "bytes": int(st.st_size), "mtime": int(st.st_mtime), "servable": True})
        groups[label] = groups.get(label, 0) + 1

    try:
        for p in sorted(root.iterdir(), key=lambda x: x.name.lower()):
            add(p)
    except OSError:
        pass

    try:
        subs = [d for d in sorted(root.iterdir(), key=lambda x: x.name.lower())
                if d.is_dir() and not d.name.startswith(".")
                and d.name not in _SKIP_LOOSE_DIRS
                and d.name not in _STD_ASSET_DIRS]
    except OSError:
        subs = []
    for d in subs:
        try:
            for p in sorted(d.iterdir(), key=lambda x: x.name.lower()):
                add(p)
        except OSError:
            continue

    return {
        "ws": str(root),
        "items": items,
        "groups": [{"where": k, "count": v} for k, v in
                   sorted(groups.items(), key=lambda kv: -kv[1])],
        "truncated": truncated,
        "limit": limit,
        "note": "只读扫描：图片仍在原位。归档请自行移到 04-资产/，本页不会动你的文件",
    }


def list_dir(ws, rel: str = "", *, limit: int = LIST_MAX_ITEMS, extra_roots=()) -> dict:
    """列出工作区内某个目录（默认工作区根）。只返回可服务文件的元信息。"""
    # ★ root 必须在这里算好：下面每一项的 rel 都要**相对工作区根**返回，
    #   否则 /media 会按「工作区相对」解析而找不到文件（曾经整页图片 404 就是这个原因）。
    root = safe_root(ws)
    if not rel:
        base = root
    else:
        base = safe_rel(ws, rel, extra_roots=extra_roots)
    if not base.is_dir():
        raise _deny("不是目录")
    items, truncated = [], False
    try:
        entries = sorted(base.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except OSError:
        raise _deny("目录不可读")
    for p in entries:
        if p.name.startswith(".") or p.name in ("__pycache__",):
            continue
        if len(items) >= limit:
            truncated = True
            break
        try:
            st = p.stat()
        except OSError:
            continue
        is_dir = p.is_dir()
        try:
            rel_full = p.relative_to(root).as_posix()          # 工作区相对（/media 认这个）
        except ValueError:                                     # extra_roots：目录在根之外
            rel_full = p.relative_to(base.parent).as_posix()
        items.append({
            "name": p.name,
            "rel": rel_full,
            "dir": is_dir,
            "kind": "dir" if is_dir else kind_of(p),
            "bytes": 0 if is_dir else int(st.st_size),
            "mtime": int(st.st_mtime),
            "servable": (not is_dir) and is_servable(p),
        })
    return {
        "ws": str(root),
        "dir": str(base.relative_to(root)).replace("\\", "/") if base != root else "",
        "items": items,
        "truncated": truncated,
        "limit": limit,
    }


def read_text(ws, rel: str, *, max_bytes: int = TEXT_MAX_BYTES, extra_roots=()) -> dict:
    """读文本预览（提示词 / 字幕 / 说明）。超限截断并标注。"""
    p = safe_rel(ws, rel, extra_roots=extra_roots)
    if not p.is_file():
        raise _deny("文件不存在")
    if p.suffix.lower() not in TEXT_TYPES:
        raise _deny("只支持文本类预览")
    size = p.stat().st_size
    if size > max_bytes:
        with open(p, "rb") as fh:
            head = fh.read(max_bytes)
        return {"rel": rel, "bytes": size, "truncated": True, "text": head.decode("utf-8", "replace")}
    return {"rel": rel, "bytes": size, "truncated": False,
            "text": p.read_text(encoding="utf-8", errors="replace")}


def iter_range(path: Path, start: int, end: int, chunk: int = 64 * 1024):
    """按字节区间产出内容（媒体流用，避免整文件读入内存）。"""
    remaining = end - start + 1
    with open(path, "rb") as fh:
        fh.seek(start)
        while remaining > 0:
            data = fh.read(min(chunk, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data


def parse_range(header: str, size: int):
    """解析 `Range: bytes=a-b`。返回 (start, end) 或 None（非法则忽略区间）。

    只支持单区间——浏览器视频拖动只用单区间；多区间回 200 全量更简单也更安全。
    """
    if not header or not size:
        return None
    h = header.strip()
    if not h.lower().startswith("bytes="):
        return None
    spec = h[6:].split(",")[0].strip()
    if "-" not in spec:
        return None
    a, b = spec.split("-", 1)
    try:
        if a == "":                      # 后缀区间 bytes=-N
            n = int(b)
            if n <= 0:
                return None
            return max(0, size - n), size - 1
        start = int(a)
        end = int(b) if b else size - 1
    except ValueError:
        return None
    if start < 0 or start >= size:
        return None
    return start, min(end, size - 1)


def os_is_windows() -> bool:
    return os.name == "nt"
