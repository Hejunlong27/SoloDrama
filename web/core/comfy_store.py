# -*- coding: utf-8 -*-
"""comfy_store.py —— 本地出片工作流的「可见可换」：上传、校验、自动映射、切换

为什么要有这一层
----------------
工作流原来只能改代码常量或用 `--workflow` 传路径 —— 换一份就得记参数。这里把它变成
**可控的资产**：上传 → 校验是 API 格式 → 自动识别端口并生成映射 → 设为当前 → 出片默认用它。

三条纪律
--------
1. **不覆盖仓库里的内置工作流**：上传件一律进 `web/var/comfy/workflows/`，内置那份只读；
2. **自动映射只是起点**：识别不出的角色留空并说明，不猜 —— 猜错的表现是「参数没生效但任务成功」；
3. **写前留备份**：同 id 再上传会把旧文件挪成 `.bak_<时间戳>`，不直接覆盖。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from . import comfy_ports, paths

DIR = paths.VAR_DIR / "comfy" / "workflows"
INDEX = DIR / "index.json"
BUILTIN = paths.STAGES_DIR / "video" / "comfyui" / "workflow_h3_local.json"
BUILTIN_ID = "builtin-h3-local"

# comfy_local_video.py 认的映射角色 → 端口里对应的角色
ROLE_MAP = {
    "prompt": ("prompt", "text"),
    "seconds": ("seconds",),
    "steps": ("steps",),
    "seed": ("seed",),
    "aspect": ("aspect",),
    "prefix": ("filename",),
}


def _safe_id(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(name or "")).strip("-").lower()
    return (s or "workflow")[:48]


def _read(p) -> dict:
    d = paths.read_json(p, default=None)
    return d if isinstance(d, dict) else {}


def _auto_map(wf: dict) -> tuple:
    """按端口角色猜一份节点映射。→ (map, missing)

    `missing` 列出「该有但没有」的角色：交给界面显示成「这一项需要你手动指定」，
    而不是给个空字符串让脚本静默跳过。
    """
    info = comfy_ports.describe(wf)
    by_role = {}
    for p in info["ports"]:
        by_role.setdefault(p["role"], []).append(p)

    m, missing = {}, []
    for role, accept in ROLE_MAP.items():
        hit = None
        for r in accept:
            if by_role.get(r):
                hit = by_role[r][0]
                break
        if hit:
            m[role] = str(hit["node"])
        else:
            missing.append(role)

    imgs = [p["node"] for p in info["ports"] if p["role"] == "image"]
    if imgs:
        m["images"] = [str(x) for x in imgs]
    else:
        missing.append("images")
    return m, missing


def _entry(wf_id: str, name: str, path, builtin: bool = False) -> dict:
    wf = _read(path)
    try:
        info = comfy_ports.describe(wf)
        cap, nodes, outs = info["capacity"], info["node_count"], info["outputs"]
        groups = info["groups"]
    except Exception as exc:                                  # noqa: BLE001
        return {"id": wf_id, "name": name, "path": str(path), "builtin": builtin,
                "node_count": 0, "capacity": 0, "outputs": [], "groups": [],
                "error": "读不出工作流：%s" % exc}
    side = path.with_suffix(".map.json")
    return {
        "id": wf_id, "name": name, "path": str(path), "builtin": builtin,
        "node_count": nodes, "capacity": cap, "outputs": outs,
        "groups": [{"node": g["node"], "class_type": g["class_type"],
                    "fields": g["fields"]} for g in groups],
        "map_path": str(side) if side.is_file() else "",
        "has_map": side.is_file(),
        "size": path.stat().st_size,
        "uploaded_at": path.stat().st_mtime,
    }


def list_all() -> dict:
    DIR.mkdir(parents=True, exist_ok=True)
    idx = _read(INDEX)
    cur = str(idx.get("current") or BUILTIN_ID)
    items = []
    if BUILTIN.is_file():
        items.append(_entry(BUILTIN_ID, "内置 H3 图生视频（4 步）", BUILTIN, builtin=True))
    for f in sorted(DIR.glob("*.json"), key=lambda p: -p.stat().st_mtime):
        if f.name.endswith(".map.json") or f.name == "index.json":
            continue
        items.append(_entry(f.stem, f.stem, f))
    for it in items:
        it["current"] = it["id"] == cur
    return {"items": items, "current": cur, "dir": str(DIR)}


def get(wf_id: str) -> dict:
    for it in list_all()["items"]:
        if it["id"] == wf_id:
            d = _read(Path(it["path"]))
            try:
                d2 = comfy_ports.describe(d)
                it["ports"] = d2["ports"]
                it["capacity"] = d2["capacity"]
            except Exception:                                # noqa: BLE001
                it["ports"] = []
            return it
    raise KeyError(wf_id)


def save(name: str, text: str) -> dict:
    """保存上传的工作流（JSON 文本）。校验不过一律拒绝，不留半成品。"""
    try:
        wf = json.loads(text)
    except ValueError as exc:
        raise ValueError("不是合法 JSON：%s" % exc) from None
    if not comfy_ports.is_workflow(wf):
        raise ValueError("不是 ComfyUI「API 格式」工作流（应为 {节点id: {class_type, inputs}}）。"
                         "界面里导出的那种带 nodes/links 的在 ComfyUI 里要用「导出 API 格式」。")
    info = comfy_ports.describe(wf)
    if not info["outputs"]:
        raise ValueError("工作流里没有输出节点（SaveVideo / SaveImage 等），跑完不会产出文件")

    wf_id = _safe_id(name)
    path = DIR / ("%s.json" % wf_id)
    DIR.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        bak = path.with_name("%s.bak_%d.json" % (wf_id, int(time.time())))
        path.replace(bak)

    path.write_text(json.dumps(wf, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8", newline="")
    m, missing = _auto_map(wf)
    (DIR / ("%s.map.json" % wf_id)).write_text(
        json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="")
    # prompt / images 缺了会直接影响出片（提示词写不进去、参考图没人接）；
    # 其余角色缺了只是「不覆盖」—— 沿用工作流里的值，这是合理默认，不该报警。
    essential = [r for r in missing if r in ("prompt", "images")]
    optional = [r for r in missing if r not in essential]
    hint = "自动识别了 %d 个角色" % len(m)
    if essential:
        hint += "；缺必需角色 %s，需要在映射文件里手动指定" % "、".join(essential)
    if optional:
        hint += "；%s 未识别（将沿用工作流里的值）" % "、".join(optional)
    return {"ok": True, "id": wf_id, "map": m, "missing_roles": missing,
            "missing_essential": essential, "missing_optional": optional,
            "capacity": info["capacity"], "node_count": info["node_count"],
            "outputs": info["outputs"], "path": str(path), "hint": hint}


def set_current(wf_id: str) -> dict:
    ids = {it["id"] for it in list_all()["items"]}
    if wf_id not in ids:
        raise KeyError(wf_id)
    idx = _read(INDEX)
    idx["current"] = wf_id
    paths.write_json(INDEX, idx)
    return list_all()
