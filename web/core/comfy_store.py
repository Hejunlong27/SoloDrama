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
# ★ 2026-11-04 修正：内置工作流原来指 `workflow_h3_local.json`，而引擎默认已切到
#   `workflow_h3_minimax_canvas.json`（六参考槽 8 步）。两边不一致的后果是：
#   界面上「设为当前」切到「内置」的那份，而引擎根本不用它 —— 改了等于没改。
BUILTIN = paths.STAGES_DIR / "video" / "comfyui" / "workflow_h3_minimax_canvas.json"
BUILTIN_ID = "builtin-h3-minimax"

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
        items.append(_entry(BUILTIN_ID, "内置 Minimax H3 六参考槽", BUILTIN, builtin=True))
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


# ---------------------------------------------------------------------------
# ★ 2026-11-04：在界面上「改工作流」
# ---------------------------------------------------------------------------
# 范围说明（重要）：这里改的是**参数与映射**，不是节点图。
#   · 参数：步数 / cfg / 尺寸 / 帧数 / 种子 / 采样器 / 模型文件 —— 生产里真正会调的就这些
#   · 映射：哪个节点是「提示词」、哪几个是「参考图」—— 换工作流后必须重新对一遍
#   · 不做：拖节点、连线、加自定义节点。那等于重写 ComfyUI 前端，而且改完没法保证
#     API 格式仍然合法（画布上的线在 API 里是 [node, slot]，不是用户以为的那个顺序）。
#
# 一条纪律：**有连线的字段不在这里改**。它的值由上游节点算出来（例如 136.length 来自
# 「秒数×24」），改它不会生效但提交照样成功 —— 这种「改了没用也不报错」是本项目最贵
# 的一类坑，界面必须显式标出「由节点 X 决定」并禁止编辑。
PARAM_LABELS = {
    "steps": ("步数", "int", 1, 200),
    "cfg": ("提示词跟随度", "float", 0.0, 30.0),
    "denoise": ("重绘幅度", "float", 0.0, 1.0),
    "seed": ("随机种子", "int", 0, 2 ** 32),
    "noise_seed": ("随机种子", "int", 0, 2 ** 32),
    "width": ("宽（像素）", "int", 64, 8192),
    "height": ("高（像素）", "int", 64, 8192),
    "batch_size": ("批量张数", "int", 1, 16),
    "length": ("帧数", "int", 1, 4096),
    "frames": ("帧数", "int", 1, 4096),
    "num_frames": ("帧数", "int", 1, 4096),
    "seconds": ("时长（秒）", "float", 1.0, 60.0),
    "megapixels": ("百万像素", "float", 0.05, 8.0),
    "fps": ("帧率", "float", 1.0, 120.0),
    "filename_prefix": ("输出文件名前缀", "str", None, None),
    "text": ("提示词", "str", None, None),
    "sampler_name": ("采样器", "enum", None, None),
    "scheduler": ("调度器", "enum", None, None),
    "ckpt_name": ("主模型（checkpoint）", "enum", None, None),
    "unet_name": ("主模型（UNet）", "enum", None, None),
    "lora_name": ("LoRA", "enum", None, None),
    "vae_name": ("VAE", "enum", None, None),
    "clip_name": ("文本编码器", "enum", None, None),
    "clip_name1": ("文本编码器 1", "enum", None, None),
    "clip_name2": ("文本编码器 2", "enum", None, None),
}
PARAM_ORDER = {k: i for i, k in enumerate(PARAM_LABELS)}


def _wf_path(wf_id: str):
    for it in list_all()["items"]:
        if it["id"] == wf_id:
            return Path(it["path"]), bool(it["builtin"])
    raise KeyError(wf_id)


def _linked_fields(wf: dict) -> dict:
    """找出每个节点里「值来自上游连线」的字段 → {(node, field): 上游节点}。"""
    out = {}
    for nid, node in wf.items():
        if not isinstance(node, dict):
            continue
        for field, val in (node.get("inputs") or {}).items():
            if isinstance(val, list) and len(val) == 2 and isinstance(val[0], str):
                out[(str(nid), field)] = str(val[0])
    return out


def _map_overrides(path: Path) -> tuple:
    """读同名 map 里的「运行期覆盖」，返回 ({(node, field): 原因}, map)。

    ★ 这是本项目最贵的一类坑的可视化：工作流文件里某个字段明明是可改的数字，
      但运行时会被 map 的 `_rewire` / `_substitute` 顶掉 —— 改了不生效，
      提交却照样成功。表现是「我改了帧数，出来的还是 10 秒」。
      界面上必须提前说清，否则用户会怀疑整个引擎。
    """
    side = path.with_suffix(".map.json")
    m = _read(side) if side.is_file() else {}
    out = {}
    for nid, patch in (m.get("_rewire") or {}).items():
        if not isinstance(patch, dict):
            continue
        for field, tgt in patch.items():
            src = tgt[0] if isinstance(tgt, (list, tuple)) and tgt else tgt
            out[(str(nid), str(field))] = "由映射接回节点 %s 计算（改这里不生效）" % src
    for nid, patch in (m.get("_substitute") or {}).items():
        if not isinstance(patch, dict):
            continue
        for field, val in patch.items():
            out[(str(nid), str(field))] = "由映射固定为本机模型（改这里会被覆盖）：%s" % str(val)[:48]
    if m.get("_steps_ineffective"):
        out[("__any__", "steps")] = (m.get("_steps_note")
                                     or "本工作流的步数由固定 sigmas 决定，改 steps 不改变实际步数")
    return out, m


def params(wf_id: str) -> dict:
    """列出可调参数。连线字段也会列出，但标 `linked` 且 `editable=False`。"""
    path, builtin = _wf_path(wf_id)
    wf = _read(path)
    linked = _linked_fields(wf)
    overrides, mp = _map_overrides(path)
    try:
        ports = comfy_ports.describe(wf).get("ports") or []
    except Exception:                                        # noqa: BLE001
        ports = []
    role_of = {(str(p["node"]), p["field"]): p["role"] for p in ports}

    items = []
    for nid, node in wf.items():
        if not isinstance(node, dict):
            continue
        cls = str(node.get("class_type") or "")
        ins = node.get("inputs") or {}
        for field, val in ins.items():
            spec = PARAM_LABELS.get(field)
            up = linked.get((str(nid), field))
            if spec is None and up is None:
                continue          # 不在白名单、也不是连线 —— 清单太长且没有调整价值
            label, ptype, lo, hi = spec if spec else (field, "str", None, None)
            is_linked = up is not None
            ovr = overrides.get((str(nid), field)) or (
                overrides.get(("__any__", field)) if field in ("steps", "noise_seed") else ""
            ) or ""
            shown = val
            if is_linked:
                # 连线时上游的真实值只有跑起来才知道；这里给「由谁决定」而不是假装有值
                shown = None
            blocked = is_linked or bool(ovr) or builtin
            reason = ("由节点 %s 决定，改这里不生效" % up) if is_linked else (
                ovr if ovr else ("内置工作流只读，先复制一份再改" if builtin else ""))
            items.append({
                "node": str(nid), "class_type": cls, "field": field,
                "label": label,
                "type": ("link" if is_linked else ("override" if ovr else ptype)),
                "value": shown, "upstream": up or "",
                "role": role_of.get((str(nid), field), ""),
                "editable": not blocked,
                "blocked_by": ("link" if is_linked else ("map" if ovr else ("builtin" if builtin else ""))),
                "reason": reason,
                "min": lo, "max": hi,
            })
    items.sort(key=lambda x: (PARAM_ORDER.get(x["field"], 999), x["node"]))
    return {"ok": True, "id": wf_id, "builtin": builtin, "path": str(path),
            "items": items,
            "linked_count": sum(1 for x in items if x["type"] == "link"),
            "override_count": sum(1 for x in items if x["type"] == "override"),
            "editable_count": sum(1 for x in items if x["editable"]),
            "map_notes": {k: v for k, v in (mp or {}).items() if str(k).endswith("_note")}}


def set_params(wf_id: str, changes: list) -> dict:
    """改若干参数并写回。→ {ok, changed[], rejected[], path, backup}

    全部校验通过才落盘：一条不合法就整体拒绝，不留「改了一半」的工作流。
    """
    path, builtin = _wf_path(wf_id)
    if builtin:
        raise ValueError("内置工作流是只读的：先用「复制为副本」生成一份，再改副本。")
    wf = _read(path)
    linked = _linked_fields(wf)
    overrides, _mp = _map_overrides(path)
    changed, rejected = [], []
    for ch in (changes or []):
        nid = str(ch.get("node") or "")
        field = str(ch.get("field") or "")
        node = wf.get(nid)
        if not isinstance(node, dict):
            rejected.append({"node": nid, "field": field, "why": "节点不存在"})
            continue
        ins = node.get("inputs") or {}
        if field not in ins:
            rejected.append({"node": nid, "field": field, "why": "该节点没有这个字段"})
            continue
        if (nid, field) in linked:
            rejected.append({"node": nid, "field": field,
                             "why": "值由节点 %s 决定，改这里不会生效" % linked[(nid, field)]})
            continue
        ovr = overrides.get((nid, field)) or (
            overrides.get(("__any__", field)) if field in ("steps", "noise_seed") else "")
        if ovr:
            rejected.append({"node": nid, "field": field, "why": ovr})
            continue
        spec = PARAM_LABELS.get(field)
        old = ins[field]
        raw = ch.get("value")
        try:
            if spec and spec[1] == "int":
                new = int(float(raw))
            elif spec and spec[1] == "float":
                new = float(raw)
            elif spec and spec[1] == "enum" or isinstance(old, str):
                new = str(raw)
            elif isinstance(old, bool):
                new = bool(raw)
            else:
                new = raw
        except (TypeError, ValueError):
            rejected.append({"node": nid, "field": field, "why": "值不是合法数字（%r）" % (raw,)})
            continue
        if spec and spec[2] is not None and isinstance(new, (int, float)):
            lo, hi = spec[2], spec[3]
            if new < lo or new > hi:
                rejected.append({"node": nid, "field": field,
                                 "why": "超出范围 %s–%s" % (lo, hi)})
                continue
        if new == old:
            continue
        ins[field] = new
        changed.append({"node": nid, "field": field, "old": old, "new": new,
                        "class_type": node.get("class_type")})
    if rejected:
        return {"ok": False, "changed": [], "rejected": rejected,
                "detail": "有 %d 项不合法，整体未写入（避免留下改了一半的工作流）" % len(rejected)}
    if not changed:
        return {"ok": True, "changed": [], "rejected": [], "detail": "没有变化"}

    bak = _backup(path)
    path.write_text(json.dumps(wf, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8", newline="")
    return {"ok": True, "changed": changed, "rejected": [], "path": str(path),
            "backup": str(bak) if bak else "",
            "detail": "已改 %d 项；出片/出图会立刻用新值" % len(changed)}


def map_of(wf_id: str) -> dict:
    path, _builtin = _wf_path(wf_id)
    side = path.with_suffix(".map.json")
    cur = _read(side) if side.is_file() else {}
    try:
        auto, missing = _auto_map(_read(path))
    except Exception:                                        # noqa: BLE001
        auto, missing = {}, []
    return {"ok": True, "id": wf_id, "map": cur or auto, "auto": auto,
            "source": ("保存的映射" if side.is_file() else "按端口自动识别（未保存）"),
            "missing_roles": [r for r in missing if r not in (cur or auto)],
            "note": ("映射是「角色 → 节点」的对照表：prompt 决定提示词写进哪个节点，"
                     "images 决定参考图铺到哪几个槽位。角色写错的表现是「任务成功但效果不对」，"
                     "不会报错 —— 所以改完请先跑一镜小样。")}


def set_map(wf_id: str, mapping: dict) -> dict:
    """保存映射。只允许写已知角色，且节点必须在工作流里存在。"""
    path, builtin = _wf_path(wf_id)
    if builtin:
        raise ValueError("内置工作流是只读的：先复制副本再改映射。")
    wf = _read(path)
    ids = {str(k) for k in wf.keys()}
    clean, bad = {}, []
    for role, val in (mapping or {}).items():
        if role.startswith("_") or role not in ROLE_MAP and role not in ("images", "aspect",
                                                                        "duration", "ratio"):
            bad.append({"role": role, "why": "未知角色"})
            continue
        vals = val if isinstance(val, list) else [val]
        keep = []
        for v in vals:
            s = str(v or "").strip()
            if not s:
                continue
            if s not in ids:
                bad.append({"role": role, "value": s, "why": "工作流里没有这个节点"})
                continue
            keep.append(s)
        if keep:
            clean[role] = keep if isinstance(val, list) else keep[0]
    if bad:
        return {"ok": False, "rejected": bad,
                "detail": "有 %d 项不合法，未写入" % len(bad)}

    side = path.with_suffix(".map.json")
    old = _read(side) if side.is_file() else {}
    # ★ 必须保留 `_` 开头的元信息段（`_rewire` / `_substitute` / `_steps_ineffective` /
    #   `_note` 等）。它们是**运行期行为**的一部分，不是注释：
    #   `_rewire` 负责把 136.length 接回「秒数×24」的表达式节点，丢了它帧数会被写死 1008，
    #   而界面上的「映射」看起来完全正常 —— 出片时才发现所有镜头都变成 10 秒。
    #   只覆盖角色键、元信息原样继承，是这一层唯一安全的写法。
    merged = {k: v for k, v in old.items() if str(k).startswith("_")}
    merged.update(clean)
    if side.is_file():
        _backup(side)
    side.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="")
    kept = sorted(k for k in merged if str(k).startswith("_"))
    return {"ok": True, "map": merged, "path": str(side),
            "kept_meta": kept,
            "detail": "映射已保存（保留 %d 段运行期元信息）%s。建议先跑一镜小样确认效果。"
                      % (len(kept), "：" + "、".join(kept) if kept else "")}


def duplicate(wf_id: str, name: str = "") -> dict:
    """复制一份副本（内置只读，要改先复制）。"""
    src, _builtin = _wf_path(wf_id)
    wf = _read(src)
    if not wf:
        raise ValueError("源工作流读不出来")
    new_id = _safe_id(name or ("%s-copy" % wf_id))
    if (DIR / ("%s.json" % new_id)).is_file():
        new_id = _safe_id("%s-%d" % (new_id, int(time.time())))
    DIR.mkdir(parents=True, exist_ok=True)
    dst = DIR / ("%s.json" % new_id)
    dst.write_text(json.dumps(wf, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8", newline="")
    side = src.with_suffix(".map.json")
    if side.is_file():
        (DIR / ("%s.map.json" % new_id)).write_text(
            side.read_text(encoding="utf-8"), encoding="utf-8", newline="")
    return {"ok": True, "id": new_id, "path": str(dst),
            "detail": "已复制为 %s，现在可以改参数与映射" % new_id}


# ---------------------------------------------------------------------------
# 备份与回滚
# ---------------------------------------------------------------------------
def _backup(path: Path):
    """写前留一份 .bak_<时间戳>。返回备份路径（没备份返回 None）。"""
    try:
        if not path.is_file():
            return None
        bak = path.with_name("%s.bak_%d%s" % (path.stem, int(time.time()), path.suffix))
        # 同名同秒重复保存时不互相覆盖
        n = 1
        while bak.exists():
            bak = path.with_name("%s.bak_%d_%d%s" % (path.stem, int(time.time()), n, path.suffix))
            n += 1
        bak.write_bytes(path.read_bytes())
        return bak
    except OSError:
        return None


def backups(wf_id: str) -> dict:
    path, _builtin = _wf_path(wf_id)
    pat = "%s.bak_*%s" % (path.stem, path.suffix)
    items = []
    for f in sorted(path.parent.glob(pat), key=lambda p: -p.stat().st_mtime):
        stamp = f.name.split(".bak_")[-1].replace(path.suffix, "").split("_")[0]
        try:
            ts = int(stamp)
            when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
        except ValueError:
            when = ""
        items.append({"file": f.name, "size": f.stat().st_size, "when": when,
                      "mtime": f.stat().st_mtime})
    return {"ok": True, "id": wf_id, "items": items[:30]}


def restore(wf_id: str, bak_name: str) -> dict:
    """回滚到某个备份。当前版本先备份，再覆盖 —— 回滚本身也可回滚。"""
    path, builtin = _wf_path(wf_id)
    if builtin:
        raise ValueError("内置工作流是只读的，不能回滚")
    bak = path.parent / Path(bak_name).name          # 只取文件名，防目录穿越
    if not bak.is_file() or ".bak_" not in bak.name:
        raise ValueError("找不到这个备份：%s" % bak_name)
    _backup(path)
    path.write_bytes(bak.read_bytes())
    return {"ok": True, "id": wf_id, "restored": bak.name, "path": str(path),
            "detail": "已回到 %s" % bak_name}
