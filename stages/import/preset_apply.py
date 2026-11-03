#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""preset_apply.py —— 把「项目预配置卡」落到工作区（出图/出片/放大三条通道）

为什么有它
----------
新分支把创作移出引擎后，剩下一堆**执行参数**：出图走本地还是云端、出片用哪个工作流、
并发多少、放大到多大。这些参数散落在三处（`model-plan.json`、`config.local.json`、
`config.upscale.json`），逐条手改既慢又容易只改一半 —— 典型症状是「确认单写着本地、
实际跑的是云端」，账对不上时已经出了几十张图。

预配置卡把这三处收成一份 JSON，一条命令落盘，并**回读校验**。

用法
----
    python stages/import/preset_apply.py --list
    python stages/import/preset_apply.py --preset local-comfyui-rh --workspace "D:/剧/x"            # 干跑
    python stages/import/preset_apply.py --preset local-comfyui-rh --workspace "D:/剧/x" --apply    # 真写

落盘目标（都在工作区内）
-----------------------
    <ws>/layout.json                                缺失则先建骨架（_layout.scaffold）
    <ws>/model-plan.json                            通道确认单（image / video）
    <ws>/video-pipeline/config.local.json           concurrency 等执行覆盖
    <ws>/video-pipeline/config.upscale.json         放大后端与目标尺寸

幂等：重复执行结果相同；已存在的无关键一律保留。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "stages"))
sys.path.insert(0, str(ROOT / "stages" / "production" / "scripts"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # type: ignore[union-attr]
except Exception:                                            # noqa: BLE001
    pass

PRESET_DIR = ROOT / "configs" / "presets"


def load_preset(name: str) -> dict:
    p = PRESET_DIR / (name if name.endswith(".json") else name + ".json")
    if not p.is_file():
        raise SystemExit("[FAIL] 预配置卡不存在：%s（可选：%s）"
                         % (p, ", ".join(x.stem for x in PRESET_DIR.glob("*.json"))))
    return json.loads(p.read_text(encoding="utf-8-sig"))


def list_presets() -> int:
    print("%-22s %s" % ("ID", "说明"))
    print("-" * 78)
    for p in sorted(PRESET_DIR.glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8-sig"))
        print("%-22s %s" % (p.stem, d.get("label") or ""))
        v = d.get("video") or {}
        u = d.get("upscale") or {}
        print("%-22s 出图=%s ｜ 出片=%s/%s ｜ 并发=%s ｜ 放大=%s/%s"
              % ("", (d.get("image") or {}).get("engine"),
                 v.get("engine"), v.get("workflow_id"),
                 v.get("concurrency"), u.get("backend"), u.get("workflow_id")))
    return 0


def _merge_json(p: pathlib.Path, patch: dict, apply: bool) -> dict:
    cur = {}
    if p.is_file():
        try:
            cur = json.loads(p.read_text(encoding="utf-8-sig")) or {}
        except (OSError, json.JSONDecodeError, ValueError):
            cur = {}
    if not isinstance(cur, dict):
        cur = {}
    cur.update(patch)
    if apply:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cur, ensure_ascii=False, indent=2) + "\n",
                     encoding="utf-8", newline="")
    return cur


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="项目预配置卡 → 工作区（出图/出片/放大）")
    ap.add_argument("--list", action="store_true", help="列出可用预配置卡")
    ap.add_argument("--preset", default="local-comfyui-all")
    ap.add_argument("--workspace", default=None)
    ap.add_argument("--apply", action="store_true", help="真写（默认干跑）")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    if a.list:
        return list_presets()

    preset = load_preset(a.preset)
    ws_raw = a.workspace or ""
    if not ws_raw:
        import os
        ws_raw = os.environ.get("SOLODRAMA_WORKSPACE") or os.environ.get("DRAMA_WORKSPACE") or ""
    if not ws_raw:
        print("[FAIL] 需要 --workspace（或 SOLODRAMA_WORKSPACE）")
        return 2
    ws = pathlib.Path(ws_raw).expanduser().resolve()
    if not ws.is_dir():
        print("[FAIL] 工作区不存在：%s" % ws)
        return 2

    import _layout as L                                    # noqa: E402
    import model_gate as M                                 # noqa: E402

    plan: list = []

    # ① 目录骨架（缺 layout.json 才建；已有项目不动）
    if not (ws / L.LAYOUT_FILE).is_file():
        r = L.scaffold(ws)
        plan.append(("建目录骨架", str(ws), "新建" if a.apply else "将新建"))
        _ = r

    # ② 通道确认单：走 model_gate 的唯一入口，保证 confirmed/evidence 口径一致
    img = preset.get("image") or {}
    vid = preset.get("video") or {}
    detail_img = {}
    if img.get("comfy_url"):
        detail_img["comfy_url"] = img["comfy_url"]
    wf = (img.get("workflows") or {}).get("t2i")
    if wf:
        detail_img["comfy_workflow"] = str((ROOT / wf).resolve())
    detail_vid = {}
    if vid.get("workflow_id"):
        detail_vid["workflow_id"] = str(vid["workflow_id"])

    plan.append(("确认出图通道", "%s（%s）" % (img.get("choice"), img.get("capability")),
                 "已写入" if a.apply else "将写入"))
    plan.append(("确认出片通道", "%s / %s" % (vid.get("choice"), vid.get("workflow_id")),
                 "已写入" if a.apply else "将写入"))
    if a.apply:
        # _do_set 自带「同一 kind 重设会写 history」的行为，幂等
        rc1 = M._do_set(ws, "image", img.get("choice") or "local_comfyui", detail_img, source="preset")
        rc2 = M._do_set(ws, "video", vid.get("choice") or "local_comfyui", detail_vid, source="preset")
        if rc1 != 0 or rc2 != 0:
            print("[WARN] 通道确认单写入有告警（退出码 %s / %s），请检查 model-plan.json"
                  % (rc1, rc2))

    # ③ 引擎覆盖层：并发
    er = L.engine_root(ws)
    local = er / "config.local.json"
    patch = {}
    if vid.get("concurrency"):
        patch["concurrency"] = int(vid["concurrency"])
    if patch:
        _merge_json(local, patch, a.apply)
        plan.append(("引擎并发", "concurrency=%d" % patch["concurrency"],
                     "已写入 %s" % local if a.apply else "将写入"))

    # ④ 放大配置
    up = preset.get("upscale") or {}
    ucfg = er / "config.upscale.json"
    if up:
        cur = {}
        if ucfg.is_file():
            try:
                cur = json.loads(ucfg.read_text(encoding="utf-8-sig")) or {}
            except (OSError, json.JSONDecodeError, ValueError):
                cur = {}
        # 以引擎默认配置为底，再叠加预设（避免只写三个键、其余全空）
        base = _default_upscale()
        base.update({k: v for k, v in cur.items() if k in base})
        base["backend"] = up.get("backend") or base.get("backend")
        base["enabled"] = True
        if isinstance(up.get("target"), dict):
            base["target"] = {**base.get("target", {}), **up["target"]}
        if up.get("workflow_id"):
            base.setdefault("rh", {})
            base["rh"] = {**base.get("rh", {}), "workflow_id": str(up["workflow_id"])}
        if a.apply:
            ucfg.parent.mkdir(parents=True, exist_ok=True)
            ucfg.write_text(json.dumps(base, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8", newline="")
        tgt = base.get("target") or {}
        plan.append(("放大后端", "%s → %sx%s"
                     % (base.get("backend"), tgt.get("width"), tgt.get("height")),
                     "已写入 %s" % ucfg if a.apply else "将写入"))

    # ⑤ 回读校验
    ok = True
    if a.apply:
        p = M.load_plan(ws)
        for kind, want in (("image", img.get("choice")), ("video", vid.get("choice"))):
            got = ((p.get("models") or {}).get(kind) or {}).get("choice")
            if got != want:
                print("[FAIL] 回读不一致：%s 期望 %s，实际 %s" % (kind, want, got))
                ok = False
        if patch:
            try:
                cfg = json.loads(local.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError, ValueError):
                cfg = {}
            if int(cfg.get("concurrency") or 0) != int(patch["concurrency"]):
                print("[FAIL] 回读不一致：concurrency")
                ok = False

    print("=" * 78)
    print("预配置 %s%s：%s" % (preset.get("id"), "（干跑）" if not a.apply else "", preset.get("label")))
    print("=" * 78)
    print("  工作区：%s" % ws)
    print("-" * 78)
    for name, value, state in plan:
        print("  %-14s %-46s %s" % (name, value, state))
    print("-" * 78)
    d = preset.get("delivery") or {}
    if d:
        print("  画风锁：%s ｜ 集数 %s ｜ 单集 %ss ｜ 交付 %sx%s@%sfps"
              % (preset.get("style_lock"), d.get("episode_count"), d.get("target_duration"),
                 d.get("width"), d.get("height"), d.get("fps")))
    if not a.apply:
        print()
        print("干跑结束。加 --apply 落盘。")
    elif ok:
        print()
        print("[OK] 预配置已生效。下一步：导入制作包 → 出资产图 → 出分镜图 → 出片 → 剪辑。")
    if a.json:
        print(json.dumps({"ok": ok, "applied": bool(a.apply), "workspace": str(ws),
                          "plan": [{"item": n, "value": v, "state": s} for n, v, s in plan]},
                         ensure_ascii=False, indent=2))
    return 0 if ok else 3


def _default_upscale() -> dict:
    """读 upscale.py 的 DEFAULT_CONFIG（唯一真源），避免这里手抄一份会漂的默认值。"""
    p = ROOT / "stages" / "subtitle" / "scripts" / "upscale.py"
    import importlib.util
    spec = importlib.util.spec_from_file_location("_upscale_mod", p)
    mod = importlib.util.module_from_spec(spec)
    old = sys.argv
    sys.argv = [str(p), "--help"]
    try:
        spec.loader.exec_module(mod)                       # type: ignore[union-attr]
    except SystemExit:
        pass
    finally:
        sys.argv = old
    return json.loads(json.dumps(getattr(mod, "DEFAULT_CONFIG", {}) or {}))


if __name__ == "__main__":
    sys.exit(main())
