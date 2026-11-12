#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""gen_boards.py —— 每镜一张分镜图（构图锚），喂给出片的第一张参考图

它解决的是什么
--------------
在它之前，出片只给「角色卡 + 场景卡」两三类参考图。这两张图的构图**都不是本镜的构图**：
角色卡是纯背景 3/4 站姿，场景卡是空房间。于是模型每一镜都在重新猜机位——
同一个会议室，在 shot_001 是俯拍、shot_002 变平视、shot_003 又贴着墙，
观众看到的是「空间在跳」，而不是「人在同一个空间里动」。

分镜图补的就是这一格：**与成片同构的 9:16 单帧画面**。它和视频同模态（都是摄影画面），
所以模型能直接读懂「这一镜长什么样」，不用猜。

它不是站位图
------------
2026-10-31 曾试过「俯视站位线稿」，结论是「对成片没有增益」——那个结论只对线稿成立：
线稿是**另一个模态**，模型会把它当画面内容复刻，而不是当构图指令。分镜图是摄影画面，
只提供构图、光位、人物位置，不含任何线稿语义。

它的边界：**只做构图锚，不做身份锚**
------------------------------------
人物长相对不对，由上片时喂的**角色卡**保证；分镜图里的人物只要「姿势与位置对」就行。
分镜图固定走**图生图**：参考图来自角色卡与场景卡。下游按「t2i / i2i 两套工作流预设」
切换，不允许因为找不到参考图就静默退化成文生图。

用法
----
    # 干跑：只打印将生成的提示词与落点，不出图
    python stages/production/scripts/gen_boards.py --workspace "D:/剧/新剧" --ep ep01 --dry-run

    # 真出（auto 读 model-plan.json 的 board.choice；未确认回落本地）
    python stages/production/scripts/gen_boards.py --workspace "D:/剧/新剧" --ep ep01 --apply

    # 显式通道
    python .../gen_boards.py --workspace "<ws>" --ep ep01 --engine local --apply
    python .../gen_boards.py --workspace "<ws>" --ep ep01 --engine cloud --comfy-url https://... --apply --yes
    python .../gen_boards.py --workspace "<ws>" --ep ep01 --engine zzai --apply --yes --max-cost 0.20

    # 只补某几镜
    python stages/production/scripts/gen_boards.py --workspace "D:/剧/新剧" --ep ep01 --apply --only shot_003,shot_005

产物
----
    04-资产/boards/<ep>/<shot_id>.png        ← 9:16，与成片同构
    data/<ep>/boards.json                    ← 输入契约（由 convert_storyboard 生成）

纪律
----
1. **只读 boards.json 的 prompt**，不发明剧情。缺 board 的镜直接跳过并列出，不猜。
2. 人数从 `refs` 的 `char_*` 数量推出，**不写死** —— EP03/EP04 的事故就是写死「exactly one person」。
3. 一张图一镜，**绝不拼版**（九宫格/分镜表那种）—— 拼版会让模型把整张当一帧。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import time
import uuid

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[union-attr]
except Exception:                                                # noqa: BLE001
    pass

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]                       # stages/production/scripts → 仓库根（parents[1] 是 stages）
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "stages" / "assets" / "comfyui"))


def _prescan_workspace() -> None:
    """--workspace 必须在 import _ws 前下沉到环境变量。"""
    for i, arg in enumerate(sys.argv):
        if arg == "--workspace" and i + 1 < len(sys.argv):
            os.environ["SOLODRAMA_WORKSPACE"] = sys.argv[i + 1]
            os.environ["DRAMA_WORKSPACE"] = sys.argv[i + 1]
        elif arg.startswith("--workspace="):
            value = arg.split("=", 1)[1]
            os.environ["SOLODRAMA_WORKSPACE"] = value
            os.environ["DRAMA_WORKSPACE"] = value


_prescan_workspace()

import _ws as W                              # noqa: E402
import _layout as L                          # noqa: E402

COMFY_CLIENT = ROOT / "stages" / "assets" / "comfyui" / "comfy_client.py"
WF_EDIT = ROOT / "stages" / "assets" / "comfyui" / "workflow_qwen21_edit.json"

# ---------------------------------------------------------------------------
# 提示词模板
# ---------------------------------------------------------------------------
# ★ 为什么「人数」要单独一段、且用英文写：H3 对 `[SUBJECT]` 里的人数极为敏感，
#   而中文人数（「两个人」）在英文提示词里权重太低。2026-11-01 的事故就是
#   模板写了 `exactly one person` 而画面里明明两个人 —— 这里按 refs 实算，绝不写死。
NUM_EN = {1: "exactly one person", 2: "exactly two people", 3: "exactly three people",
          4: "exactly four people", 5: "exactly five people"}

BOARD_TMPL = """\
【任务】一张**{orient_cn} {ratio} 电影静帧**，用作这一镜的构图参考。它是摄影画面，不是分镜表、不是线稿。
【构图】{board}
【人数】{people_line}
【人物】{cast_line}
【风格】{style_line}
【画面】single frame, {orient_en} {ratio}, cinematic still photograph, natural perspective, \
believable depth of field, photographic material truth, real skin texture, \
credible fabric wrinkles, no illustration look.
【光线】{light_line}
【禁止】no text, no letters, no numbers, no watermark, no logo, no captions, no subtitles,
no split screen, no collage, no grid, no storyboard layout, no panels, no border, no labels,
no arrows, no annotations, no second frame of the same person.
"""

# 分镜 md 里常写 `[LIGHT]` 段；这里只做「有就透传、没有就不编」。
_LIGHT_RE = re.compile(r"\[LIGHT\]\s*(.+)", re.I)


def _read_json(p: pathlib.Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8-sig")) if p.is_file() else default
    except Exception:                                                    # noqa: BLE001
        return default


def _specs_from_md(ws: pathlib.Path, ep: str) -> dict:
    """从分镜 md 抽 `{shot_id: {prompt, ratio, refs}}`。

    只认 5 字段里的 `board / ratio / refs` —— 与 `convert_storyboard` 的解析口径一致，
    但**不去读它的产物**（避免环节之间反向依赖）。
    """
    f = L.stage_dir(ws, "storyboard") / ("%s_storyboard.md" % ep)
    if not f.is_file():
        return {}
    text = f.read_text(encoding="utf-8", errors="replace")
    out = {}
    for block in re.split(r"(?m)^##\s+", text)[1:]:
        lines = block.split("\n")
        sid = lines[0].strip().split()[0] if lines else ""
        if not sid:
            continue
        body = "\n".join(lines[1:])
        m = re.search(r"(?m)^-\s*board:\s*\|\s*\n(.*?)(?=\n-\s|\n---|\Z)", body, re.S)
        if not m:
            continue
        buf = []
        for ln in m.group(1).split("\n"):
            if ln.startswith(("    ", "\t")):
                buf.append(ln[4:] if ln.startswith("    ") else ln.lstrip("\t"))
            elif not ln.strip() and buf:
                buf.append("")
            elif ln.strip():
                break
        prompt = "\n".join(buf).strip()
        if not prompt:
            continue
        r = re.search(r"(?m)^-\s*ratio:\s*(\S+)", body)
        ref = re.search(r"(?m)^-\s*refs:\s*(.+)$", body)
        out[sid] = {"prompt": prompt,
                    "ratio": (r.group(1) if r else "9:16"),
                    "refs": [x.strip() for x in re.split(r"[,，、\s]+", ref.group(1)) if x.strip()]
                    if ref else []}
    return out


def _codes(refs, known=()) -> list:
    """从 refs 里挑出角色代号。三种写法都认：

        char_elle  → ELLE      （下划线 key，最常见）
        Character_Elle → ELLE
        ELLE       → ELLE      （直接写代号 —— 名册里就是这么写的，别只认带前缀的）

    场景 key（`scene_room`）不在 `known` 里，所以不会被误当成角色。
    不传 `known` 时退化为「只认前缀」，保持旧行为。
    """
    known_set = {str(k).upper() for k in (known or [])}
    out = []
    for r in refs or []:
        s = str(r).strip()
        low = s.lower()
        hit = None
        # P01@LOOK-A / P01 LOOK-A / P01 都归一到 P01；LOOK 后缀不是角色身份。
        m = re.match(r"^(P\d{2})(?:@|\s|$)", s, flags=re.I)
        if m:
            out.append(m.group(1).upper())
            continue
        for pre in ("character_", "char_", "ch_"):
            if low.startswith(pre):
                hit = s[len(pre):].upper()
                break
        if hit is None and s.upper() in known_set:
            hit = s.upper()
        # 没有 character-bible 时（known 为空），裸代号 P01 也要能认成角色 ——
        # 否则人数会算成 0 再兜底成 1，两个人物的镜头会被写成「exactly one person」。
        if hit is None and re.fullmatch(r"P\d{2}", s, flags=re.I):
            hit = s.upper()
        if hit:
            out.append(hit)
    return out


def build_prompt(shot_id: str, spec: dict, bible: dict, style_line: str,
                 h3_prompt: str = "", ratio: str = "") -> tuple:
    """boards.json 的一条 → (完整提示词, 人数, 出场代号列表)。

    人数 = `refs` 里 char_* 的**实际个数**。这是硬约束：写死 1 人而画面两人，
    模型会把人裁掉一半或让第二个人变成背影，成片直接废。
    """
    refs = spec.get("refs") or []
    codes = _codes(refs, [c.get("code") for c in (bible.get("characters") or [])])
    n = len(codes)
    people = "no people in frame" if n == 0 else NUM_EN.get(n, "exactly %d people" % n)

    # 画幅：分镜图是构图稿，必须跟交付画幅一致（2026-11-06：横屏项目曾被写死成 9:16）
    _ratio = (str(ratio or "").strip() or str(spec.get("ratio") or "").strip() or "9:16")
    _portrait = True
    try:
        _w, _h = [float(x) for x in _ratio.split(":")[:2]]
        _portrait = _w <= _h
    except (ValueError, IndexError):
        pass

    # 人物外观：从 character-bible 取「服装 + 主色 + 发型」一句话。
    # 不写长相细节 —— 分镜图不承担身份，写多了反而把角色卡挤掉。
    by_code = {}
    for c in (bible.get("characters") or []):
        by_code[str(c.get("code") or "").upper()] = c
    bits = []
    for code in codes:
        c = by_code.get(code)
        if not c:
            bits.append("%s (identity held by the character card, do not invent a face)" % code)
            continue
        bits.append("%s — %s; %s" % (
            code,
            str(c.get("garment_en") or "").strip().rstrip(".") or "wardrobe per character card",
            "%d-year-old %s" % (int(c.get("age") or 30),
                                "woman" if str(c.get("gender")) == "f" else "man")))
    cast_line = ("; ".join(bits) + ". Faces need only be plausible — identity is enforced "
                 "by the character reference cards, not by this frame.") if bits else \
                ("the location with nobody in it" if n == 0 else
                 "figures described only by the composition note above")

    light = ""
    m = _LIGHT_RE.search(h3_prompt or "")
    if m:
        light = m.group(1).strip().rstrip(".")
    light_line = (light + "; direction and source must read clearly") if light else \
        "one clear key source, direction readable, natural falloff"

    txt = BOARD_TMPL.format(
        board=str(spec.get("prompt") or "").strip(),
        people_line=("%s — nobody else in frame." % people) if n else "no people in frame.",
        cast_line=cast_line,
        style_line=style_line or "cinematic live-action photography",
        light_line=light_line,
        ratio=_ratio or "9:16",
        orient_cn=("横版" if _portrait is False else "竖版"),
        orient_en=("horizontal" if _portrait is False else "vertical"),
    )
    return txt, n, codes


def _style_line(ws: pathlib.Path) -> str:
    """取画风的 style_prompt：优先 drama.json，回退 style-plan.json。

    只取 look 的 prompt（题材视觉），不拼 track 的渲染流 —— 分镜图是构图稿，
    渲染风格交给上片时的 H3（那边已经有一份完整风格串）。
    """
    for name in ("drama.json", "style-plan.json"):
        d = _read_json(ws / name, None)
        if not isinstance(d, dict):
            continue
        if name == "drama.json":
            look = str((d.get("format") or {}).get("look") or "")
        else:
            look = str((d.get("style") or {}).get("look") or "")
        if not look:
            continue
        lib = _read_json(ROOT / "configs" / "looks.json", {}) or {}
        for it in lib.get("looks") or []:
            if it.get("id") == look:
                return str(it.get("prompt") or "")
    return ""


def _board_plan(ws: pathlib.Path) -> dict:
    p = ws / "model-plan.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig")) if p.is_file() else {}
    except (OSError, json.JSONDecodeError):
        return {}
    return ((data.get("models") or {}).get("board") or {}) if isinstance(data, dict) else {}


def _workflow_preset(ws: pathlib.Path, mode: str) -> str:
    """读取 board 的 ComfyUI t2i/i2i 预设；旧 comfy_workflow 作为 i2i 兼容值。"""
    detail = _board_plan(ws).get("detail") or {}
    nested = detail.get("comfy_workflows") if isinstance(detail.get("comfy_workflows"), dict) else {}
    flat = "comfy_workflow_%s" % mode
    value = nested.get(mode) or detail.get(flat) or ""
    if not value and mode == "i2i":
        value = detail.get("comfy_workflow") or ""
    return str(value or "").strip()


def _rh_workflow_preset(ws: pathlib.Path, mode: str) -> str:
    detail = _board_plan(ws).get("detail") or {}
    nested = detail.get("runninghub_workflows") if isinstance(detail.get("runninghub_workflows"), dict) else {}
    value = nested.get(mode) or detail.get("workflow_id_%s" % mode) or ""
    if not value and mode == "i2i":
        value = detail.get("workflow_id") or ""
    return str(value or "").strip()


def _rh_pairs(detail: dict, txt: str, ratio: str, ref_names: list) -> tuple:
    """把 board.detail 的 i2i 节点映射变成 RunningHub node pairs。"""
    nodes = (detail.get("runninghub_nodes_i2i")
             or (detail.get("runninghub_nodes") or {}).get("i2i")
             or detail.get("nodes_i2i") or detail.get("nodes") or {})
    prompt_node = nodes.get("prompt") if isinstance(nodes, dict) else None
    image_nodes = nodes.get("images") if isinstance(nodes, dict) else None
    if not image_nodes and isinstance(nodes, dict):
        image_nodes = [nodes.get("image")] if nodes.get("image") else []
    image_nodes = [n for n in (image_nodes or []) if isinstance(n, dict)]
    if not isinstance(prompt_node, dict) or not image_nodes:
        return [], "RunningHub i2i 节点映射不全：需要 nodes.prompt 与 nodes.image(s)"
    pairs = [(prompt_node.get("nodeId"), prompt_node.get("fieldName") or "text", txt)]
    for node, name in zip(image_nodes, ref_names):
        pairs.append((node.get("nodeId"), node.get("fieldName") or "image", name))
    aspect = nodes.get("aspect")
    if isinstance(aspect, dict):
        pairs.append((aspect.get("nodeId"), aspect.get("fieldName") or "aspect_ratio", ratio))
    return pairs, ""


def _ref_sources(ws: pathlib.Path, spec: dict) -> list:
    """把分镜 refs 解析成本地图片路径或公网 URL。

    分镜图是图生图：没有参考图不是「退化成文生图」，而是配置错误。
    """
    rj = _read_json(L.assets_dir(ws) / "refs.json", {}) or {}
    tables = {}
    tables.update(rj.get("characters") or {})
    tables.update(rj.get("scenes") or {})
    tables.update(rj.get("props") or {})
    out = []
    for key in (spec.get("refs") or []):
        raw = tables.get(str(key))
        if not raw:
            continue
        raw = str(raw)
        if raw.startswith(("http://", "https://")):
            out.append(raw)
            continue
        p = pathlib.Path(raw)
        out.append(p if p.is_absolute() else (ws / p))
    return out


def _load_image_slots(workflow_path) -> int:
    """统计 ComfyUI 工作流中的 LoadImage 槽位；读不到时保守按 2 槽。"""
    try:
        wf = json.loads(pathlib.Path(workflow_path).read_text(encoding="utf-8-sig"))
        n = sum(1 for node in wf.values()
                if isinstance(node, dict) and node.get("class_type") == "LoadImage")
        return n or 2
    except Exception:  # noqa: BLE001
        return 2


def _resolve_engine(ws: pathlib.Path, requested: str):
    """把 board.choice / --engine 归一为 local | cloud | zzai。"""
    requested = str(requested or "auto").strip().lower()
    entry = _board_plan(ws)
    choice = str(entry.get("choice") or "").strip()
    confirmed = bool(entry.get("confirmed") and choice)
    mapping = {"local_comfyui": "local", "cloud_comfyui": "cloud",
               "zzai_image_api": "zzai", "runninghub_workflow": "rh"}
    if requested == "auto":
        if confirmed:
            engine = mapping.get(choice)
            if not engine:
                return "", ("确认单里的 board.choice=%s 没有内置执行器；"
                            "请改选 local_comfyui / cloud_comfyui / zzai_image_api" % choice)
            note = "模型确认单：board=%s → %s" % (choice, engine)
        else:
            engine, note = "local", "未确认 board 通道 → 本地 ComfyUI（￥0）"
    else:
        engine = requested
        note = "命令行指定：board=%s" % engine
    if engine not in ("local", "cloud", "zzai", "rh"):
        return "", "未知分镜图通道：%s（可选 local / cloud / zzai / rh）" % engine
    # 显式选择云端/ZZAI，或项目已确认过 board 时，必须通过模型门禁。
    if engine in ("cloud", "zzai", "rh") or confirmed:
        import model_gate
        ok, msg = model_gate.require(ws, "board", expected_engine=engine)
        if not ok:
            return "", msg
        note += "；" + msg
    return engine, note


def _task_write(ws: pathlib.Path, rec: dict) -> None:
    base = ws / ".drama" / "media"
    base.mkdir(parents=True, exist_ok=True)
    rec["updated_at"] = time.time()
    p = base / (rec["id"] + ".json")
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def _task_new(ws: pathlib.Path, *, model: str, request: dict, estimate, max_cost,
              ep: str, sid: str, provider_id: str = "zzai") -> dict:
    rid = "mt_%s_%s" % (time.strftime("%Y%m%d%H%M%S"), uuid.uuid4().hex[:8])
    digest = hashlib.sha256(json.dumps(request, ensure_ascii=False,
                                       sort_keys=True).encode("utf-8")).hexdigest()
    rec = {
        "schema_version": 1, "id": rid, "project": str(ws.resolve()),
        "kind": "image", "provider_id": provider_id, "model": model,
        "purpose": "board.frame", "episode": ep, "shot_id": sid,
        "status": "planned", "remote_task_id": "", "request": request,
        "request_sha": digest, "estimate": estimate, "max_cost": max_cost,
        "actual_cost": None, "cost_source": "unknown", "usage": None,
        "progress": None, "artifacts": [], "error": "", "raw_status": "",
        "submissions": 0, "created_at": time.time(), "updated_at": time.time(),
        "history": [{"at": time.time(), "status": "planned", "note": "task record created"}],
    }
    _task_write(ws, rec)
    return rec


def _task_update(ws: pathlib.Path, rec: dict, *, status: str, remote_task_id="",
                 progress=None, usage=None, artifact="", error="") -> None:
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
                                          "note": "board zzai poll"})
    rec["history"] = rec["history"][-50:]
    _task_write(ws, rec)


def _run_zzai(ws: pathlib.Path, a, plan, out_dir: pathlib.Path) -> int:
    """ZZAI 图片 API：先上传参考图，再逐张 estimate，最后要求 --yes 与 --max-cost。"""
    from stages.media_api.zzai import ZZAIClient, ZZAIError

    staged = []
    for sid, txt, n, codes, spec in plan:
        dst = out_dir / ("%s.png" % sid)
        if dst.is_file() and not a.force:
            print("[skip] %s 已存在" % sid)
            continue
        refs = _ref_sources(ws, spec)
        if not refs:
            print("[FAIL] %s 没有可解析的角色/场景参考图；分镜图必须图生图" % sid)
            return 2
        if len(refs) > 16:
            print("[FAIL] %s 参考图 %d 张，超过模型上限 16" % (sid, len(refs)))
            return 2
        staged.append((sid, txt, spec, refs, dst))
    if not staged:
        print("没有需要生成的镜。")
        return 0

    client = ZZAIClient()
    uploaded = {}
    items = []
    for sid, txt, spec, refs, dst in staged:
        image_urls = []
        try:
            for ref in refs:
                if isinstance(ref, str) and ref.startswith(("http://", "https://")):
                    image_urls.append(ref)
                    continue
                p = pathlib.Path(ref)
                key = str(p.resolve())
                if key not in uploaded:
                    uploaded[key] = client.upload(str(p))
                image_urls.append(uploaded[key])
        except ZZAIError as exc:
            print("[FAIL] %s 参考图上传失败：%s" % (sid, exc))
            return 2
        payload = {
            "model": a.model,
            "prompt": txt,
            "images": image_urls,
            "size": str(spec.get("ratio") or "9:16"),
            "resolution": a.resolution,
            "quality": a.quality,
            "output_format": "png",
            "n": 1,
        }
        items.append((sid, payload, dst))

    quotes = []
    total = 0.0
    has_amount = False
    currencies = set()
    try:
        for sid, payload, _ in items:
            est = client.estimate("image", payload)
            quotes.append((sid, payload, est))
            if est.get("estimate_available") and isinstance(est.get("amount"), (int, float)):
                total += float(est["amount"])
                has_amount = True
                currencies.add(str(est.get("currency") or ""))
            print("  quote %s：%s %s（%s）" % (
                sid, est.get("amount", "未知"), est.get("currency", ""),
                est.get("confidence", "unknown")))
    except ZZAIError as exc:
        print("[FAIL] ZZAI estimate 失败：%s" % exc)
        return 2

    if not a.yes:
        print("\n预估合计：%s %s（未知项不估算）" % (
            round(total, 6) if has_amount else "未知",
            "/".join(sorted(x for x in currencies if x))))
        print("[闸门] 真实分镜图生成需要 --yes；正式提交还需 --max-cost 作为单张上限。")
        return 4
    if a.max_cost is None:
        print("[FAIL] ZZAI 真实生成必须提供 --max-cost（单张 CNY 上限）。")
        return 2

    out_dir.mkdir(parents=True, exist_ok=True)
    ok = fail = 0
    for i, (sid, payload, dst) in enumerate(items, 1):
        est = next((q[2] for q in quotes if q[0] == sid), {})
        amount = est.get("amount")
        if isinstance(amount, (int, float)) and float(amount) > float(a.max_cost):
            print("[FAIL] %s 预估 %.6f 超过 --max-cost %s" % (sid, amount, a.max_cost))
            fail += 1
            continue
        rec = _task_new(ws, model=a.model, request=payload, estimate=est,
                        max_cost=a.max_cost, ep=a.ep, sid=sid)
        print("[%d/%d] %s → ZZAI 提交" % (i, len(items), sid))
        try:
            sub = client.submit("image", payload, max_cost=a.max_cost, authorized=True)
            _task_update(ws, rec, status="queued", remote_task_id=sub["task_id"])
            result = None
            for _ in range(120):
                time.sleep(max(0.2, float(a.poll_seconds)))
                result = client.poll("image", sub["task_id"])
                _task_update(ws, rec, status=result["status"],
                             remote_task_id=sub["task_id"],
                             progress=result.get("progress"),
                             usage=result.get("usage"),
                             error=result.get("error") or "")
                if result["status"] in ("succeeded", "failed", "canceled"):
                    break
            if not result or result["status"] != "succeeded" or not result.get("result_url"):
                fail += 1
                print("       [FAIL] %s" % ((result or {}).get("error") or "未到成功终态"))
                continue
            out_dir.mkdir(parents=True, exist_ok=True)
            client.download(result["result_url"], dst)
            _task_update(ws, rec, status="succeeded", remote_task_id=sub["task_id"],
                         progress=result.get("progress"), usage=result.get("usage"),
                         artifact=str(dst))
            ok += 1
            print("       → %s ｜ usage=%s" % (dst.name, result.get("usage")))
        except ZZAIError as exc:
            _task_update(ws, rec, status="failed", error=str(exc))
            fail += 1
            print("       [FAIL] %s" % exc)
    print("\n完成：成功 %d / 失败 %d（共 %d 镜）" % (ok, fail, len(items)))
    return 0 if fail == 0 else 3


def _run_rh(ws: pathlib.Path, a, plan, out_dir: pathlib.Path) -> int:
    """RunningHub 工作流图生图：工作流 ID 与节点映射来自 board.detail。"""
    if not a.yes:
        print("[闸门] RunningHub 分镜图会真实提交并计费；确认后加 --yes 重跑。")
        return 4
    key = os.environ.get("RUNNINGHUB_API_KEY") or ""
    if not key:
        print("[FAIL] 缺少 RUNNINGHUB_API_KEY")
        return 2
    wid = str(getattr(a, "workflow_id_i2i", "") or _rh_workflow_preset(ws, "i2i")).strip()
    if not wid:
        print("[FAIL] 未配置 RunningHub 图生图 workflowId（--workflow-id-i2i 或 model-plan）")
        return 2
    detail = _board_plan(ws).get("detail") or {}
    nodes = (detail.get("runninghub_nodes_i2i")
             or (detail.get("runninghub_nodes") or {}).get("i2i")
             or detail.get("nodes_i2i") or detail.get("nodes") or {})
    prompt_node = nodes.get("prompt") if isinstance(nodes, dict) else None
    image_nodes = nodes.get("images") if isinstance(nodes, dict) else None
    if not image_nodes and isinstance(nodes, dict):
        image_nodes = [nodes.get("image")] if nodes.get("image") else []
    image_nodes = [n for n in (image_nodes or []) if isinstance(n, dict)]
    if not isinstance(prompt_node, dict) or not image_nodes:
        print("[FAIL] RunningHub i2i 节点映射不全：需要 nodes.prompt 与 nodes.image(s)")
        return 2

    import asyncio
    engine = ROOT / "stages" / "video" / "workflow" / "scripts" / "engine"
    sys.path.insert(0, str(engine))
    sys.path.insert(0, str(HERE))
    from _site import project_site
    from runninghub_client import RunningHubClient, RunningHubError

    os.environ.setdefault("SOLODRAMA_ALLOW_RH", "1")
    base_url = project_site(ws / "video-pipeline")

    async def go() -> int:
        ok = fail = 0
        async with RunningHubClient(key, base_url) as client:
            uploads = {}
            for i, (sid, txt, n, codes, spec) in enumerate(plan, 1):
                dst = out_dir / ("%s.png" % sid)
                if dst.is_file() and not a.force:
                    print("[%d/%d] %s 已存在，跳过" % (i, len(plan), sid))
                    continue
                refs = _ref_sources(ws, spec)
                if not refs:
                    print("[FAIL] %s 没有角色/场景参考图；分镜图必须图生图" % sid)
                    fail += 1
                    continue
                ref_names = []
                try:
                    for ref in refs[:len(image_nodes)]:
                        p = pathlib.Path(ref)
                        if not p.is_file():
                            raise RunningHubError("参考图不存在：%s" % p)
                        cache_key = str(p.resolve())
                        if cache_key not in uploads:
                            uploads[cache_key] = await client.upload_file(str(p))
                        ref_names.append(uploads[cache_key]["fileName"])
                except RunningHubError as exc:
                    print("[FAIL] %s 参考图上传失败：%s" % (sid, exc))
                    fail += 1
                    continue
                pairs = [(prompt_node.get("nodeId"), prompt_node.get("fieldName") or "text", txt)]
                for node, name in zip(image_nodes, ref_names):
                    pairs.append((node.get("nodeId"), node.get("fieldName") or "image", name))
                aspect = nodes.get("aspect") if isinstance(nodes, dict) else None
                if isinstance(aspect, dict):
                    pairs.append((aspect.get("nodeId"), aspect.get("fieldName") or "aspect_ratio",
                                  str(spec.get("ratio") or "9:16")))
                node_list = RunningHubClient.build_node_list(pairs)
                rec = _task_new(ws, model="runninghub:%s" % wid,
                                request={"prompt": txt, "images": ref_names,
                                         "ratio": spec.get("ratio") or "9:16"},
                                estimate=None, max_cost=None, ep=a.ep, sid=sid,
                                provider_id="runninghub")
                try:
                    task_id = await client.create_workflow_v2(wid, node_list)
                    _task_update(ws, rec, status="queued", remote_task_id=task_id)
                    print("[%d/%d] %s → task %s" % (i, len(plan), sid, task_id))
                    result = await client.poll_until_done(
                        task_id, timeout_min=float(a.rh_timeout_min), interval=3.0)
                    urls = [str(x.get("url")) for x in (result.get("results") or [])
                            if str(x.get("url") or "").startswith(("http://", "https://"))]
                    if result.get("status") != "SUCCESS" or not urls:
                        raise RunningHubError("终态失败或无图片结果：%s" % result.get("status"))
                    out_dir.mkdir(parents=True, exist_ok=True)
                    await client.download(urls[0], str(dst))
                    _task_update(ws, rec, status="succeeded", remote_task_id=task_id,
                                 usage=result.get("usage") or {}, artifact=str(dst))
                    ok += 1
                    print("       → %s" % dst.name)
                except RunningHubError as exc:
                    _task_update(ws, rec, status="failed", error=str(exc))
                    fail += 1
                    print("       [FAIL] %s" % exc)
        print("\n完成：成功 %d / 失败 %d（共 %d 镜）" % (ok, fail, len(plan)))
        return 0 if fail == 0 else 3

    try:
        return asyncio.run(go())
    except RunningHubError as exc:
        print("[FAIL] RunningHub 分镜图失败：%s" % exc)
        return 2


def main() -> int:
    ap = argparse.ArgumentParser(description="每镜一张分镜图（构图锚）")
    ap.add_argument("--workspace", default=None)
    ap.add_argument("--ep", required=True, help="集号，如 ep01")
    ap.add_argument("--apply", action="store_true", help="真出图（默认干跑）")
    ap.add_argument("--dry-run", action="store_true", help="只打印提示词（默认行为）")
    ap.add_argument("--only", default="", help="只做指定 shot_id，逗号分隔")
    ap.add_argument("--limit", type=int, default=0, help="只做前 N 镜")
    ap.add_argument("--force", action="store_true", help="已存在也重出")
    ap.add_argument("--with-refs", dest="with_refs", action="store_true", default=True,
                    help="兼容参数；分镜图固定为图生图")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--engine", choices=("auto", "local", "cloud", "zzai", "rh"), default="auto",
                    help="分镜图通道：auto 读 model-plan.json 的 board.choice；无确认时回落本地")
    ap.add_argument("--comfy-url", dest="comfy_url", default=None,
                    help="local/cloud 的 ComfyUI 地址；cloud 必填（或由确认单提供）")
    ap.add_argument("--workflow", default=None,
                    help="覆盖 ComfyUI 工作流 JSON 路径")
    ap.add_argument("--yes", action="store_true", help="云端或 ZZAI 真实提交确认")
    ap.add_argument("--max-cost", dest="max_cost", type=float, default=None,
                    help="ZZAI 单张最高允许金额；真实提交必填")
    ap.add_argument("--model", default="zhenzhen-image-g-v2.6-lowprice",
                    help="ZZAI 图片模型 ID")
    ap.add_argument("--resolution", default="1k", choices=("1k", "2k", "4k"))
    ap.add_argument("--quality", default="high",
                    choices=("auto", "low", "medium", "high", "xhigh", "max"))
    ap.add_argument("--poll-seconds", dest="poll_seconds", type=float, default=3.0)
    ap.add_argument("--workflow-id-i2i", dest="workflow_id_i2i", default=None,
                    help="RunningHub 图生图 workflowId（覆盖 model-plan）")
    ap.add_argument("--rh-timeout-min", dest="rh_timeout_min", type=float, default=15.0)
    a = ap.parse_args()

    ws = pathlib.Path(a.workspace).expanduser().resolve() if a.workspace else W.WS
    data_dir = W.data_dir(ws) / a.ep

    # ★ 分镜图的提示词真源是**分镜 md**，不是 `boards.json`。
    #   为什么改：`boards.json` 是 `convert_storyboard` 的产物，而那一步在
    #   七环节里排在「提示词」环节 —— 如果分镜图只认 boards.json，
    #   「分镜」环节就得依赖排在它后面的「提示词」环节，拓扑直接成环。
    #   md 里的 `- board:` 就是分镜环节自己的产物，读它才符合环节边界。
    specs = _specs_from_md(ws, a.ep)
    src = "05-分镜/%s_storyboard.md" % a.ep
    if not specs:
        boards_json = data_dir / "boards.json"
        specs = _read_json(boards_json, {}) or {}
        src = str(boards_json)
    if not specs:
        print("[FAIL] 既没有分镜 md 的 `- board:` 字段，也没有 %s/boards.json" % data_dir)
        print("       分镜 md 里给每一镜补上：\n         - board: |\n             <这一镜的单帧构图描述>")
        return 2
    h3 = _read_json(data_dir / "h3_prompts.json", {}) or {}
    bible = _read_json(L.assets_dir(ws) / "design" / "character-bible.json", {}) or {}
    style_line = _style_line(ws)

    out_dir = L.assets_dir(ws) / "boards" / a.ep
    want = {s.strip() for s in a.only.split(",") if s.strip()}
    items = [(sid, spec) for sid, spec in specs.items() if not want or sid in want]
    if a.limit:
        items = items[: a.limit]

    print("=" * 74)
    print("分镜图生成 · %s" % a.ep)
    print("=" * 74)
    print("  工作区  : %s" % ws)
    print("  契约    : %s（%d 镜）" % (src, len(specs)))
    print("  落点    : %s" % out_dir)
    print("  风格    : %s" % (style_line[:70] or "（未取到 look，用默认摄影风格）"))
    engine, engine_note = _resolve_engine(ws, a.engine)
    if not engine:
        print("[BLOCK] %s" % engine_note)
        return 4
    print("  通道    : %s（%s）" % (
        {"local": "本地 ComfyUI", "cloud": "云端 ComfyUI", "zzai": "ZZAI 图片 API",
         "rh": "RunningHub 工作流"}.get(engine, engine),
        engine_note))
    print("  模式    : 图生图（角色/场景参考图，固定）")
    if not items:
        print("\n[WARN] 没有要处理的镜（--only 可能写错）")
        return 0

    # 缺 board 的镜先报出来：这些镜上片时会退化为两参
    missing = [sid for sid, spec in items if not str(spec.get("prompt") or "").strip()]
    if missing:
        print("\n[WARN] %d 镜缺 board 提示词，跳过：%s" % (len(missing), "、".join(missing[:12])))

    plan = []
    for sid, spec in items:
        if sid in missing:
            continue
        txt, n, codes = build_prompt(sid, spec, bible, style_line,
                                     str((h3.get(sid) or {}).get("prompt") or ""),
                                     ratio=str(spec.get("ratio") or ""))
        plan.append((sid, txt, n, codes, spec))

    if not a.apply or a.dry_run:
        for sid, txt, n, codes, spec in plan:
            print("\n" + "-" * 74)
            print("%s ｜ %d 人 %s ｜ ratio=%s" % (sid, n, "/".join(codes) or "无", spec.get("ratio")))
            print("-" * 74)
            print(txt)
        print("\n（干跑：%d 镜，未出图。加 --apply 真出。）" % len(plan))
        return 0

    if engine == "zzai":
        return _run_zzai(ws, a, plan, out_dir)
    if engine == "rh":
        return _run_rh(ws, a, plan, out_dir)
    if engine == "cloud" and not a.yes:
        print("[闸门] 云端 ComfyUI 分镜图会占用计费实例；确认后加 --yes 重跑。")
        return 4

    detail = (_board_plan(ws).get("detail") or {})
    comfy_url = str(a.comfy_url or detail.get("comfy_url") or "").strip()
    workflow = str(a.workflow or _workflow_preset(ws, "i2i") or "").strip()
    if engine == "cloud" and not comfy_url:
        print("[FAIL] cloud 通道缺少 --comfy-url（或确认单里的 detail.comfy_url）。")
        return 2
    try:
        from cloud import config as cloud_config
        cloud_config.hydrate_env()
    except Exception:  # noqa: BLE001
        pass
    env = os.environ.copy()
    if comfy_url:
        env["COMFYUI_URL"] = comfy_url

    out_dir.mkdir(parents=True, exist_ok=True)
    wf = pathlib.Path(workflow) if workflow else WF_EDIT
    slot_count = _load_image_slots(wf)
    ok = fail = skip = 0
    for i, (sid, txt, n, codes, spec) in enumerate(plan, 1):
        dst = out_dir / ("%s.png" % sid)
        if dst.is_file() and not a.force:
            print("[%d/%d] %s 已存在，跳过（--force 重出）" % (i, len(plan), sid))
            skip += 1
            continue
        seed = a.seed if a.seed is not None else (1000 + i)
        refs = _ref_sources(ws, spec)
        if not refs:
            fail += 1
            print("       [FAIL] 没有角色/场景参考图；分镜图必须图生图")
            continue
        ref_paths = []
        missing_ref = False
        for ref in refs[:slot_count]:
            p = pathlib.Path(ref)
            if not p.is_file():
                missing_ref = True
                print("       [FAIL] 参考图不存在或不支持 URL：%s" % ref)
                break
            ref_paths.append(str(p))
        if missing_ref:
            fail += 1
            continue
        cmd = [sys.executable, str(COMFY_CLIENT),
               "--workflow", str(wf),
               "--prompt", txt, "--prefix", "board_%s_%s" % (a.ep, sid),
               "--out", str(out_dir.parent / "._tmp"), "--aspect", spec.get("ratio") or "9:16",
               "--seed", str(seed)]
        for ref in ref_paths:
            cmd += ["--image", ref]
        print("[%d/%d] %s …" % (i, len(plan), sid))
        r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=env)
        if r.returncode != 0:
            fail += 1
            print("       [FAIL] %s" % ((r.stderr or r.stdout or "").strip().splitlines()[-1:] or "?"))
            continue
        # comfy_client 落的是 <prefix>_00.png，改名为 <shot_id>.png（引擎按 shot_id 扫）
        made = sorted((out_dir.parent / "._tmp").glob("board_%s_%s*.png" % (a.ep, sid)))
        if not made:
            fail += 1
            print("       [FAIL] 没有产物")
            continue
        made[0].replace(dst)
        ok += 1
        print("       → %s" % dst.name)

    tmp = out_dir.parent / "._tmp"
    if tmp.is_dir() and not any(tmp.iterdir()):
        tmp.rmdir()
    print("\n完成：成功 %d / 跳过 %d / 失败 %d（共 %d 镜）" % (ok, skip, fail, len(plan)))
    if ok:
        print("下一步：python stages/video/workflow/scripts/run.py --workspace \"%s\" --ep %s --dry-run"
              % (ws, a.ep))
    return 0 if fail == 0 else 3


if __name__ == "__main__":
    sys.exit(main())
