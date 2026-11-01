#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""style_gate.py —— 画风库「任务开始前确认」门禁（前置条件，与通道门禁并列）

为什么有它（2026-10-16 用户要求，2026-11-01 重构）
--------------------------------
画风决定后面一切的规格，而且**不可事后弥补**，所以必须在开工前一次性锁死。
但它不是一个选项，是四个正交维度：

   形态 track      configs/tracks.json     时长 / 资产 / 首帧锚 / 分镜拓扑 / 交付终点 / 渲染流
   视觉 look       configs/looks.json      纯 prompt（surreal-cinema / cel-shading / …）
   叙事 narrative  configs/narratives.json 旁白配额 / 台词密度
   通道 channel    configs/channels.json + capabilities/*.json

旧版把这三件事压进同一个 `sub_modes` 字典（`guoman-3d-render` 与 `surreal-cinema` 并列），
于是换一个 look 会连带换掉资产规格与交付终点 —— 这就是「画风库和 3D/2D/真人串在一起」的根因。
现在 `sub_modes` 只放渲染流，题材风格走独立 `--look`，可跨轨使用。

设计约定
--------
* **零第三方依赖**（纯标准库），与其余生产脚本一致。
* 确认单落**工作区**：`drama.json`（真源）+ `style-plan.json`（过渡期兼容），都不进仓库。
* **只拦「首次」**：确认过就不再问；换画风需 `reset` 后重确认。
* **不一致就拦**：确认了 A 形态却按 B 形态的规格产出 → 拦下，防「确认一套、做另一套」。
* 中文 Windows 控制台纪律：正文不用 GBK 装不下的符号；UTF-8 无 BOM 写盘。

命令
----
    python style_gate.py status                     查看当前四维（只读）
    python style_gate.py list                       打印形态 / look / 叙事三段清单
    python style_gate.py set live_action --look surreal-cinema
    python style_gate.py set 3d_manhua --look guoman-xianxia --sub-mode guoman-3d-render
    python style_gate.py set live_action --narrative narration
    python style_gate.py reset                      清除确认（换画风前用）
    python style_gate.py require [--expect 3d_manhua]   门禁查询（未过则退出码 4）
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import pathlib
import sys

GATE_VERSION = 1
PLAN_NAME = "style-plan.json"
EXIT_WAIT_CONFIRM = 4   # 与 drama.py / model_gate.py 一致：4 = 等待用户确认

# ---------------------------------------------------------------------------
# 四维配置（tracks / narratives / looks）。本文件只读它们做汇总，不复制规格。
# ---------------------------------------------------------------------------
_CFG_DIR = pathlib.Path(__file__).resolve().parents[3] / "configs"


def _load_json(name: str) -> dict:
    try:
        return json.loads((_CFG_DIR / name).read_text(encoding="utf-8-sig"))
    except Exception:                                          # noqa: BLE001
        return {}


try:
    import drama_profile as _P      # 单一档案 drama.json（同目录）
except Exception:                                              # noqa: BLE001
    _P = None


# ---------------------------------------------------------------------------
# 四维之「形态」：tracks.json 只放形态规格（时长/资产/首帧/拓扑/交付）
# 四维之「叙事」：narratives.json 只放叙事口径（旁白配额/时间窗）
# 视觉（look）在 looks.json，通道在 model-plan / capability 卡 —— 互不绑定。
# ---------------------------------------------------------------------------
_TRACKS_CFG = _load_json("tracks.json")
_NARR_CFG = _load_json("narratives.json")
_LOOKS_CFG = _load_json("looks.json")

ORDER = tuple(_TRACKS_CFG.get("order") or ("3d_manhua", "2d_animation", "live_action"))
NARRATIVE_ORDER = tuple(_NARR_CFG.get("order") or ("dialogue", "narration"))
DEFAULT_NARRATIVE = str(_NARR_CFG.get("default") or "dialogue")

# STYLES 是 tracks.json 的**运行时视图**：形态字段原样带过来，
# 再把「默认叙事模式（对白驱动）」的配额并进去 —— 这样旧调用方
# 读 `spec["narration_max_chars"]` 的老代码不用改。
STYLES = {}
for _k, _t in (_TRACKS_CFG.get("tracks") or {}).items():
    _item = dict(_t)
    _narr = ((_NARR_CFG.get("modes") or {}).get(DEFAULT_NARRATIVE) or {})
    _item["narration_max_chars"] = (_narr.get("narration_max_chars") or {}).get(_k) or {}
    _item["reserve"] = (_narr.get("reserve") or {}).get(_k) or {}
    # sub_modes 只放**渲染流**，不再混入题材风格
    _item["sub_modes"] = {kk: vv.get("label", kk) for kk, vv in (_item.get("render_styles") or {}).items()}
    _item["default_sub_mode"] = _item.get("default_render_style")
    _item["source_skill"] = ""
    STYLES[_k] = _item


def narrative_spec(mode: str, track: str) -> dict:
    """取某叙事模式在某形态下的配额（旁白字数 / 时间窗）。"""
    m = ((_NARR_CFG.get("modes") or {}).get(mode) or {})
    out = {k: m.get(k) for k in ("label", "desc", "narration_per_ep_max",
                                 "narration_sec_max", "dialogue_lines_per_60s_min")}
    out["narration_max_chars"] = (m.get("narration_max_chars") or {}).get(track) or {}
    out["reserve"] = (m.get("reserve") or {}).get(track) or {}
    return out


def merge_spec(track: str, narrative: str = DEFAULT_NARRATIVE) -> dict:
    """形态 + 叙事 → 一份完整规格。style-plan 的 `spec` 就是它。"""
    t = STYLES[track]
    spec = {k: t.get(k) for k in ("shot_duration", "anchor_reset_cadence", "assets",
                                  "first_frame_required", "angle_match_required",
                                  "storyboard_topology", "delivery_stop")}
    spec.update(narrative_spec(narrative, track))
    return spec


def looks_lib() -> dict:
    """视觉风格库 → {id: {name, prompt, tags, recommended_for}}。"""
    return {str(x.get("id")): x for x in (_LOOKS_CFG.get("looks") or []) if isinstance(x, dict)}


def compose_style_prompt(look_id: str, track: str, render_style: str | None) -> str:
    """look 的 prompt ｜ 该轨渲染流的 prompt。真人轨没有渲染流，只用 look。"""
    look = looks_lib().get(look_id or "") or {}
    parts = [str(look.get("prompt") or "").strip()]
    rs = ((STYLES.get(track, {}).get("render_styles") or {}).get(render_style or "") or {})
    if rs.get("prompt"):
        parts.append(str(rs["prompt"]).strip())
    return ", ".join([x for x in parts if x])


def style_lib() -> dict:
    """兼容旧调用：返回**全部轨道的渲染流**（并集），不再是题材风格库。

    题材风格请用 `looks_lib()`。两者分别是「轨道内的渲染手法」与「跨轨的视觉题材」，
    以前它们混在一个 sub_modes 字典里，是「画风库和 3D/2D/真人模式串到一起」的根因。
    """
    out = {}
    for track in ORDER:
        for kk, vv in ((STYLES.get(track, {}).get("render_styles") or {})).items():
            if kk not in out:
                out[kk] = {"name": vv.get("label", kk), "prompt": vv.get("prompt", ""),
                           "track": track}
    return out


# ---------------------------------------------------------------------------
def _harden_stdio() -> None:
    try:
        enc = "utf-8"
        if sys.stdout.isatty() and os.name == "nt":
            import ctypes
            cp = ctypes.windll.kernel32.GetConsoleOutputCP()
            if cp:
                enc = "cp%d" % cp
        for s in (sys.stdout, sys.stderr):
            try:
                s.reconfigure(encoding=enc, errors="replace")   # type: ignore[union-attr]
            except Exception:                                     # noqa: BLE001
                pass
    except Exception:                                             # noqa: BLE001
        pass


def _resolve_ws(explicit=None) -> pathlib.Path:
    if explicit:
        p = pathlib.Path(explicit).expanduser()
        if p.is_dir():
            return p.resolve()
        sys.exit("[FAIL] --workspace 指向的目录不存在：%s" % p)
    env = (os.environ.get("SOLODRAMA_WORKSPACE") or os.environ.get("DRAMA_WORKSPACE"))
    if env:
        p = pathlib.Path(env).expanduser()
        if p.is_dir():
            return p.resolve()
        sys.exit("[FAIL] 环境变量 SOLODRAMA_WORKSPACE 指向的目录不存在：%s" % env)
    sys.exit("[FAIL] 找不到工作区。请用 --workspace 或环境变量 SOLODRAMA_WORKSPACE 指定。")


def plan_path(ws: pathlib.Path) -> pathlib.Path:
    return ws / PLAN_NAME


def _now() -> str:
    return _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def load_plan(ws: pathlib.Path) -> dict:
    p = plan_path(ws)
    if not p.is_file():
        return {"gate_version": GATE_VERSION, "style": None, "history": []}
    try:
        d = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {"gate_version": GATE_VERSION, "style": None, "history": []}
    d.setdefault("history", [])
    d.setdefault("gate_version", GATE_VERSION)
    return d


def save_plan(ws: pathlib.Path, plan: dict) -> pathlib.Path:
    p = plan_path(ws)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
def gate_state(ws: pathlib.Path) -> dict:
    # ★ 2026-11-01：drama.json 优先。它是四维的单一真源；style-plan 只在过渡期兜底。
    if _P is not None:
        d = _P.load(ws)
        if d is not None:
            f = d.get("format") or {}
            if f.get("track") and (d.get("confirmed") or {}).get("format_at"):
                return {"confirmed": True, "choice": f.get("track"), "sub_mode": None,
                        "look": f.get("look"), "narrative": f.get("narrative") or "dialogue",
                        "reason": "", "source": "drama.json"}
    plan = load_plan(ws)
    st = plan.get("style") or {}
    if st.get("choice") and st.get("confirmed"):
        return {"confirmed": True, "choice": st["choice"],
                "sub_mode": st.get("sub_mode"), "look": st.get("look"),
                "narrative": st.get("narrative"), "reason": ""}
    return {"confirmed": False, "choice": None, "sub_mode": None,
            "reason": "本项目尚未确认画风（任务开始前必须确认）"}


def require(ws: pathlib.Path, expect: str | None = None) -> tuple:
    """门禁判定。返回 (是否放行, 提示语)。"""
    st = gate_state(ws)
    if not st["confirmed"]:
        return False, st["reason"]
    if expect and st["choice"] != expect:
        return False, ("本项目已确认画风为「%s」，但本次按「%s」执行。\n"
                       "        如确需换画风，请先 `drama.py style reset` 再重确认 —— 画风决定资产/时长/提示词规格，"
                       "中途更换会导致已产出素材全部作废。"
                       % (STYLES[st["choice"]]["label"], STYLES.get(expect, {}).get("label", expect)))
    s = STYLES[st["choice"]]
    sub = ("，渲染流 %s" % st["sub_mode"]) if st.get("sub_mode") else ""
    look = ("，look %s" % st["look"]) if st.get("look") else "（未指定 look）"
    return True, "已确认画风：%s（%s%s%s）" % (s["label"], st["choice"], sub, look)


def render_menu(indent: str = "    ") -> str:
    lines = []
    for i, k in enumerate(ORDER, 1):
        s = STYLES[k]
        lines.append("%s%d) %-24s %s" % (indent, i, s["label"], k))
        lines.append("%s    %s" % (indent, s["desc"]))
        lines.append("%s    规格：单镜 %g-%g 秒｜旁白上限 %d/%d/%d 字｜资产 角色主卡×1%s｜场景主卡×1%s｜交付到 %s"
                     % (indent, s["shot_duration"]["min"], s["shot_duration"]["max"],
                        s["narration_max_chars"]["normal"], s["narration_max_chars"]["emotion"],
                        s["narration_max_chars"]["monologue"],
                        "+三视图×1" if s["assets"]["character_3view"] else "",
                        "+辅卡×1" if s["assets"]["scene_aux"] else "",
                        s["delivery_stop"]))
        if s["sub_modes"]:
            lines.append("%s    子模式：%s" % (indent, " / ".join(
                "%s=%s" % (v, kk) for kk, v in s["sub_modes"].items())))
    return "\n".join(lines)


def render_request(ws: pathlib.Path) -> str:
    return ("=" * 74 + "\n"
            "【前置条件】任务开始前必须确认画风（本项目：%s）\n" % ws +
            "=" * 74 + "\n"
            "画风决定资产规格 / 单镜时长 / 旁白字数上限 / H3 提示词模板 / 交付终点，\n"
            "**不可事后更换**（换了等于已产出素材全部作废）。请三选一：\n\n" +
            render_menu() + "\n\n"
            "确认方式（任选其一）：\n"
            "  drama.py style --ask\n"
            "  drama.py style set 3d_manhua --sub-mode guoman-3d-render\n"
            "  drama.py style set 2d_animation --sub-mode guoman-webtoon\n"
            "  drama.py style set live_action\n")


# ---------------------------------------------------------------------------
def cmd_list(a) -> int:
    print("【形态 track】—— 决定资产规格 / 单镜时长 / 分镜拓扑 / 交付")
    print(render_menu())
    print()
    print("【视觉 look】—— 纯 prompt，可跨轨使用（%d 条）" % len(looks_lib()))
    for lid, look in looks_lib().items():
        tags = "、".join(look.get("tags") or [])
        rec = ("（推荐轨：%s）" % "/".join(look.get("recommended_for") or [])) if look.get("recommended_for") else ""
        print("   %-20s %-10s %s%s" % (lid, look.get("name") or "", tags, rec))
    print()
    print("【叙事 narrative】—— 决定旁白配额与台词密度")
    for m in NARRATIVE_ORDER:
        md = (_NARR_CFG.get("modes") or {}).get(m) or {}
        print("   %-10s %s" % (m, md.get("label") or ""))
        print("              旁白/集 ≤%s 条，≤%s 秒；台词密度 ≥%s 句/60s"
              % (md.get("narration_per_ep_max"), md.get("narration_sec_max"),
                 md.get("dialogue_lines_per_60s_min")))
    return 0


def cmd_status(a) -> int:
    ws = _resolve_ws(getattr(a, "workspace", None))
    plan = load_plan(ws)
    st = gate_state(ws)
    print("=" * 74)
    print("画风确认单（前置条件门禁）")
    print("=" * 74)
    print("工作区    : %s" % ws)
    print("确认单    : %s%s" % (plan_path(ws), "" if plan_path(ws).is_file() else "（尚未创建）"))
    if st["confirmed"]:
        s = STYLES[st["choice"]]
        print("画风      : [已确认] %s（%s）" % (s["label"], st["choice"]))
        if st.get("sub_mode"):
            print("子模式    : %s（%s）" % (st["sub_mode"], s["sub_modes"].get(st["sub_mode"], "?")))
        _ln = str((plan.get("style") or {}).get("look_name") or
                  (looks_lib().get(st.get("look") or "") or {}).get("name") or "")
        _nl = str((plan.get("style") or {}).get("narrative_label") or
                  ((_NARR_CFG.get("modes") or {}).get(st.get("narrative") or DEFAULT_NARRATIVE) or {}).get("label") or "")
        print("视觉 look   : %s%s" % (st.get("look") or "（未指定）", ("｜" + _ln) if _ln else ""))
        print("叙事模式    : %s%s" % (st.get("narrative") or DEFAULT_NARRATIVE, ("｜" + _nl) if _nl else ""))
        print("visual_style_lock : %s" % s["visual_style_lock"])
        print("单镜时长  : %g-%g 秒（动作/快切 %g-%g）"
              % (s["shot_duration"]["min"], s["shot_duration"]["max"],
                 s["shot_duration"]["action_min"], s["shot_duration"]["action_max"]))
        print("旁白上限  : %d / %d / %d 字（普通/情绪/大段）"
              % (s["narration_max_chars"]["normal"], s["narration_max_chars"]["emotion"],
                 s["narration_max_chars"]["monologue"]))
        print("交付终点  : %s" % s["delivery_stop"])
        print("确认时间  : %s" % ((plan.get("style") or {}).get("confirmed_at") or "-"))
        if _P is not None:
            _d = _P.load(ws)
            print("四维档案  : %s" % (_P.fmt_line(_d) if _d else "（drama.json 尚未生成，用 drama.py profile migrate 建立）"))
    else:
        print("画风      : [未确认] 任务开始前必须确认")
    if getattr(a, "json", False):
        print()
        print(json.dumps({"workspace": str(ws), "plan": plan}, ensure_ascii=False, indent=2))
    return 0


def _do_set(ws: pathlib.Path, choice: str, sub_mode: str | None, source: str = "cli",
            look: str | None = None, narrative: str | None = None) -> int:
    if choice not in STYLES:
        print("[FAIL] 未知画风：%s（应为 %s）" % (choice, "|".join(ORDER)))
        return 2
    s = STYLES[choice]
    subs = s["sub_modes"]
    if subs:
        sub_mode = sub_mode or s.get("default_sub_mode") or next(iter(subs), None)
        if sub_mode not in subs:
            print("[FAIL] 未知渲染流：%s（%s 可选 %s）" % (sub_mode, choice, "|".join(subs)))
            return 2
    else:
        if sub_mode:
            print("[WARN] %s 无渲染流，忽略 --sub-mode %s" % (choice, sub_mode))
        sub_mode = None

    plan = load_plan(ws)
    prev = plan.get("style") or {}

    # 视觉 look：显式给 > 沿用上一次 > 空（允许不指定，但会在状态里提示）
    look = (look or "").strip() or (prev.get("look") or "")
    if look and look not in looks_lib():
        print("[FAIL] 未知 look：%s（可选 %s）" % (look, "|".join(looks_lib())))
        return 2
    # 叙事模式：显式给 > 沿用上一次 > 默认对白驱动
    narrative = (narrative or "").strip() or (prev.get("narrative") or DEFAULT_NARRATIVE)
    if narrative not in NARRATIVE_ORDER:
        print("[FAIL] 未知叙事模式：%s（可选 %s）" % (narrative, "|".join(NARRATIVE_ORDER)))
        return 2

    plan["style"] = {
        "choice": choice,
        "label": s["label"],
        "sub_mode": sub_mode,
        "look": look,
        "look_name": (looks_lib().get(look) or {}).get("name", ""),
        "narrative": narrative,
        "narrative_label": ((_NARR_CFG.get("modes") or {}).get(narrative) or {}).get("label", ""),
        "visual_style_lock": s["visual_style_lock"],
        "style_prompt": compose_style_prompt(look, choice, sub_mode),
        "style_name": "%s%s" % ((looks_lib().get(look) or {}).get("name", "") or "（未指定 look）",
                                (" / " + s["sub_modes"].get(sub_mode, "")) if sub_mode else ""),
        "source_skill": s.get("source_skill", ""),
        "confirmed": True,
        "confirmed_at": _now(),
        "confirmed_by": source,
        "spec": merge_spec(choice, narrative),
    }
    if prev.get("choice"):
        plan.setdefault("history", []).append({"at": _now(), "from": prev.get("choice"), "to": choice})
    p = save_plan(ws, plan)
    # ★ 双写：drama.json 是四维真源，style-plan 保留给还没改过来的脚本读
    if _P is not None:
        _d = _P.effective(ws)
        _d.setdefault("format", {}).update({"track": choice, "look": look, "narrative": narrative})
        _d.setdefault("confirmed", {})["format_at"] = plan["style"]["confirmed_at"]
        _P.save(ws, _d)
    print("[OK] 已确认画风 = %s（%s%s）" % (s["label"], choice,
                                            "，子模式 %s" % sub_mode if sub_mode else ""))
    print("     确认单：%s" % p)
    print("     规格已锁：单镜 %g-%g 秒｜旁白上限 %d/%d/%d 字｜资产 角色%s｜场景%s｜交付到 %s"
          % (s["shot_duration"]["min"], s["shot_duration"]["max"],
             s["narration_max_chars"]["normal"], s["narration_max_chars"]["emotion"],
             s["narration_max_chars"]["monologue"],
             "主卡+三视图" if s["assets"]["character_3view"] else "主卡",
             "主卡+辅卡" if s["assets"]["scene_aux"] else "主卡",
             s["delivery_stop"]))
    if s["storyboard_topology"] == "three_panel_per_clip":
        print("     [强制] 分镜拓扑 = 1 视频片段 → 1 张三格时间分镜图")
    return 0


def cmd_set(a) -> int:
    ws = _resolve_ws(getattr(a, "workspace", None))
    return _do_set(ws, a.choice, getattr(a, "sub_mode", None),
                   look=getattr(a, "look", None), narrative=getattr(a, "narrative", None))


def cmd_reset(a) -> int:
    ws = _resolve_ws(getattr(a, "workspace", None))
    plan = load_plan(ws)
    prev = plan.pop("style", None)
    if prev:
        plan.setdefault("history", []).append({"at": _now(), "from": prev.get("choice"), "to": None})
        save_plan(ws, plan)
        print("[OK] 已清除画风确认（原为 %s）；下次执行会重新要求确认" % prev.get("choice"))
    else:
        print("[OK] 画风本就未确认，无需清除")
    return 0


def cmd_ask(a) -> int:
    ws = _resolve_ws(getattr(a, "workspace", None))
    if not sys.stdin.isatty():
        print(render_request(ws))
        print("[提示] 当前非交互式终端（无 TTY），请用 `drama.py style set <choice>` 记录确认。")
        return EXIT_WAIT_CONFIRM
    print("=" * 74)
    print("【前置条件】确认本项目画风（工作区：%s）" % ws)
    print("=" * 74)
    print(render_menu())
    while True:
        raw = input("请输入序号 1-%d（q 退出）：" % len(ORDER)).strip()
        if raw.lower() in ("q", "quit", "exit"):
            print("[取消] 未记录任何确认。")
            return EXIT_WAIT_CONFIRM
        if raw.isdigit() and 1 <= int(raw) <= len(ORDER):
            choice = ORDER[int(raw) - 1]
            sub = None
            subs = STYLES[choice]["sub_modes"]
            if subs:
                keys = list(subs)
                print("  子模式：")
                for i, k in enumerate(keys, 1):
                    print("    %d) %s（%s）" % (i, subs[k], k))
                while True:
                    r2 = input("  请输入子模式序号 1-%d（回车取默认 %s）："
                               % (len(keys), STYLES[choice]["default_sub_mode"])).strip()
                    if not r2:
                        sub = STYLES[choice]["default_sub_mode"]
                        break
                    if r2.isdigit() and 1 <= int(r2) <= len(keys):
                        sub = keys[int(r2) - 1]
                        break
                    print("  输入无效，请重试。")
            ok = input("确认选用「%s」？（y/N）：" % STYLES[choice]["label"]).strip().lower()
            if ok in ("y", "yes"):
                return _do_set(ws, choice, sub, source="interactive")
            print("已取消本次选择，请重新输入。")
            continue
        print("输入无效，请重试。")


def cmd_require(a) -> int:
    ws = _resolve_ws(getattr(a, "workspace", None))
    ok, msg = require(ws, expect=getattr(a, "expect", None))
    if ok:
        print("[OK] %s" % msg)
        return 0
    print(render_request(ws))
    print("[BLOCK] %s" % msg)
    return EXIT_WAIT_CONFIRM


def main() -> int:
    _harden_stdio()
    ap = argparse.ArgumentParser(description="画风库「任务开始前确认」门禁（形态 / 视觉 / 叙事）")
    ap.add_argument("--workspace", default=None, help="工作区（默认 SOLODRAMA_WORKSPACE）")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("list", help="打印可选画风清单")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("status", help="查看当前确认状态（只读）")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("set", help="记录确认：set <track> [--look ID] [--sub-mode 渲染流] [--narrative dialogue|narration]")
    p.add_argument("choice", choices=list(ORDER))
    p.add_argument("--sub-mode", dest="sub_mode", default=None,
                   help="该轨的渲染流（3D/2D 才有；真人轨忽略）")
    p.add_argument("--look", default=None,
                   help="视觉 look（configs/looks.json 里的 id）。与 track 无关，可跨轨使用")
    p.add_argument("--narrative", default=None, choices=list(NARRATIVE_ORDER),
                   help="叙事模式：dialogue（默认，对白驱动）｜narration（半解说）")
    p.set_defaults(fn=cmd_set)

    p = sub.add_parser("reset", help="清除确认（换画风前用）")
    p.set_defaults(fn=cmd_reset)

    p = sub.add_parser("ask", help="交互式引导确认（需 TTY）")
    p.set_defaults(fn=cmd_ask)

    p = sub.add_parser("require", help="门禁查询（未过则退出码 4；供 drama.py 调用）")
    p.add_argument("--expect", default=None, choices=list(ORDER),
                   help="本次实际要用的画风；与确认不符则拦下")
    p.set_defaults(fn=cmd_require)

    a = ap.parse_args()
    if not getattr(a, "fn", None):
        return cmd_status(a)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
