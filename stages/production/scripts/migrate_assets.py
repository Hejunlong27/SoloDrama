#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""migrate_assets.py —— 把资产从旧位置迁到 `04-资产/`（2026-10-19 新增）

背景（用户 2026-10-19 原话）
----------------------------
> 「你的文件放的位置很乱，让人找不到，比如人物资产、场景资产，你没有放在『04资产』里面，
>   而是放在了『07-成片 asset』里面。」

成因：资产出图产物由生成器写在 `<out_dir>/assets/`，而 `out_dir` 指向 `07-成片`
（或旧项目的 `video-pipeline/output`）。所以「人物/场景资产」跑到了「成片」阶段目录下。

本脚本做一次**可审计、可回退**的搬迁：

    旧：`<out_dir>/assets/{characters,scenes,props,refs}/…`（= 07-成片/assets 或 video-pipeline/output/assets）
    新：`<ws>/04-资产/{characters,scenes,props,refs}/…`

同时

* 改写 `data/*_assets_manifest.json` 里 `items[].files[].file` 的**绝对路径**；
* 补齐 `layout.json` 的 `assets_rel` 与 `config.local.json` 的 `assets_dir`；
* 默认**先备份**（复制到 `<engine_root>/output/_assets_backup_<ts>/`）再搬；
* **默认干跑**：不加 `--apply` 一行都不动。

用法
----
    python migrate_assets.py --workspace "<工作区>"              # 干跑，打印搬迁清单
    python migrate_assets.py --workspace "<工作区>" --apply      # 真搬（先备份）
    python migrate_assets.py --workspace "<工作区>" --apply --no-backup
    python migrate_assets.py --workspace "<工作区>" --apply --copy   # 复制而不移动（保留旧位置）

退出码：0 = 成功/无待迁移；2 = 有冲突或校验失败。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _ws import WS as _WS_DEFAULT, DATA as _DATA_DEFAULT                 # noqa: E402
import _layout as L                                                      # noqa: E402

SUBS = ("characters", "scenes", "props", "refs")
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")
MANIFEST_NAMES = ("char_assets_manifest.json", "scene_assets_manifest.json",
                  "prop_assets_manifest.json", "comfyui_assets_manifest.json")


def target_root(ws: Path) -> Path:
    """迁移目标：`<ws>/04-资产`（以 layout.json 的 stages.assets 为准）。"""
    lay = L.load(ws)
    if lay.get("_fallback"):
        raise SystemExit("[FAIL] 该工作区没有 layout.json（旧布局）⇒ 先跑 "
                         "`creation.py scaffold` 或手工建 layout.json 再迁移。")
    return ws / lay["stages"].get("assets", "04-资产")


def collect(legacy: Path) -> list[dict]:
    """列出待迁移文件（保持相对结构）。"""
    out = []
    if not legacy.is_dir():
        return out
    for f in sorted(legacy.rglob("*")):
        if not f.is_file():
            continue
        if f.suffix.lower() not in IMG_EXT:
            continue                                  # 只搬资产图；json/txt 之类的清单不搬
        out.append({"src": f, "rel": f.relative_to(legacy).as_posix()})
    return out


def _rewrite_json(path: Path, old_prefix: str, new_prefix: str, apply: bool) -> int:
    """把 JSON 里以 `old_prefix` 开头的字符串路径改写为 `new_prefix`，返回改写条数。

    ⚠ 必须**按解析后的字符串值改写**，不能对原始文本做替换 ——
    JSON 里 Windows 路径写作 `C:\\a\\b`（双反斜杠），用单反斜杠前缀去 `str.replace`
    匹配不到（实测踩过：改写条数恒为 0，路径仍然指向旧位置）。
    同时统一按 `/` 比较，兼容 `/` 与 `\\` 两种写法。
    """
    if not path.is_file():
        return 0
    try:
        obj = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, ValueError):
        return 0
    old_n = old_prefix.replace("\\", "/").rstrip("/")
    n = 0

    def walk(o):
        nonlocal n
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        if isinstance(o, list):
            return [walk(x) for x in o]
        if isinstance(o, str):
            s = o.replace("\\", "/")
            if s.startswith(old_n):
                n += 1
                return new_prefix.replace("\\", "/").rstrip("/") + o[len(o) - (len(s) - len(old_n)):]
        return o

    new = walk(obj)
    if n and apply:
        path.with_name(path.name + ".bak_" + datetime.now().strftime("%Y%m%d_%H%M%S")).write_text(
            path.read_text(encoding="utf-8-sig"), encoding="utf-8", newline="\n")
        path.write_text(json.dumps(new, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8", newline="\n")
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description="把资产迁到 04-资产（默认干跑）")
    ap.add_argument("--workspace", default=None)
    ap.add_argument("--apply", action="store_true", help="真搬（默认只打印计划）")
    ap.add_argument("--copy", action="store_true", help="复制而不移动（旧位置保留）")
    ap.add_argument("--no-backup", action="store_true", help="跳过备份（不推荐）")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    ws = Path(a.workspace).expanduser().resolve() if a.workspace else _WS_DEFAULT
    legacy = L.legacy_assets_dir(ws)
    dst_root = target_root(ws)
    data = L.data_dir(ws)

    plans = collect(legacy)
    conflicts, moves = [], []
    for p in plans:
        dst = dst_root / p["rel"]
        (conflicts if dst.exists() else moves).append({**p, "dst": dst})

    # JSON 里的绝对路径改写（命中数）
    n_ref = 0
    for name in MANIFEST_NAMES:
        n_ref += _rewrite_json(data / name, str(legacy), str(dst_root), apply=False)

    info = {
        "workspace": str(ws), "legacy": str(legacy), "target": str(dst_root),
        "files": len(plans), "to_move": len(moves), "conflicts": [str(c["dst"]) for c in conflicts],
        "json_refs": n_ref, "apply": a.apply, "copy": a.copy,
    }

    if not a.json:
        print("=" * 74)
        print("资产迁移 旧位置 → 04-资产 %s" % ("· 真搬" if a.apply else "· 干跑"))
        print("=" * 74)
        print("  旧位置 : %s" % legacy)
        print("  新位置 : %s" % dst_root)
        print("  待迁移 : %d 个图片文件" % len(plans))
        for m in moves[:60]:
            print("    %-58s → %s" % (m["rel"], m["dst"].relative_to(ws).as_posix()))
        if len(moves) > 60:
            print("    …（其余 %d 个同上）" % (len(moves) - 60))
        print("  清单引用 : %d 处绝对路径待改写（%s）" % (n_ref, ", ".join(MANIFEST_NAMES)))
        for c in conflicts:
            print("  [WARN] 目标已存在，跳过：%s" % c)
        if not plans:
            print("  [OK] 旧位置没有资产图，无需迁移。")

    if conflicts and not a.json:
        print("  [WARN] 有 %d 个同名文件已在新位置，将保持不动（不覆盖）。" % len(conflicts))

    if not a.apply:
        if not a.json:
            print("\n[OK] 干跑完成。确认无误后加 --apply 真搬（默认先备份）。")
        else:
            print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0

    # ---------------- 真搬 ----------------
    backup = None
    if not a.no_backup:
        backup = L.engine_root(ws) / "output" / ("_assets_backup_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
        backup.mkdir(parents=True, exist_ok=True)
        for p in plans:
            b = backup / p["rel"]
            b.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p["src"], b)
        print("  备份 : %s（%d 个文件）" % (backup, len(plans)))

    moved, failed = 0, []
    for m in moves:
        try:
            m["dst"].parent.mkdir(parents=True, exist_ok=True)
            if a.copy:
                shutil.copy2(m["src"], m["dst"])
            else:
                shutil.move(str(m["src"]), str(m["dst"]))
            moved += 1
        except OSError as e:                                                   # noqa: BLE001
            failed.append("%s: %s" % (m["rel"], e))

    # 改写清单里的绝对路径
    for name in MANIFEST_NAMES:
        _rewrite_json(data / name, str(legacy), str(dst_root), apply=True)

    # 补齐 layout.json / config.local.json 的声明（让 assets_dir() 不再走回退）
    lay_p = ws / L.LAYOUT_FILE
    if lay_p.is_file():
        lay = json.loads(lay_p.read_text(encoding="utf-8-sig"))
        if not lay.get("assets_rel"):
            lay["assets_rel"] = "../%s" % L.STAGE_DIRS["assets"]
            lay_p.write_text(json.dumps(lay, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8", newline="\n")
            print("  [OK] layout.json 补 assets_rel = ../%s" % L.STAGE_DIRS["assets"])
    L._patch_local_cfg(L.engine_root(ws), {"assets_dir": "../%s" % L.STAGE_DIRS["assets"]})

    for sub in SUBS:
        (dst_root / sub).mkdir(parents=True, exist_ok=True)

    # 校验
    left = [p["rel"] for p in plans if (legacy / p["rel"]).is_file() and not a.copy]
    still_ref = sum(1 for name in MANIFEST_NAMES
                    if _rewrite_json(data / name, str(legacy), str(dst_root), apply=False))

    print("\n  已迁移 : %d / %d" % (moved, len(moves)))
    print("  assets_dir() 现在指向 : %s" % L.assets_dir(ws))
    if failed:
        for x in failed:
            print("  [FAIL] %s" % x)
    if left:
        print("  [FAIL] 旧位置仍残留 %d 个文件（示例 %s）" % (len(left), left[:3]))
    if still_ref:
        print("  [FAIL] 仍有 %d 个清单文件引用旧路径" % still_ref)

    ok = not (failed or left or still_ref)
    print("\n%s" % ("[OK] 资产迁移完成，位置统一到 04-资产。" if ok else
                    "[BLOCK] 迁移未完全成功，请按上面的 [FAIL] 逐条处理（备份在 %s）。" % backup))
    if a.json:
        info.update({"moved": moved, "failed": failed, "left": left, "still_ref": still_ref,
                     "backup": str(backup) if backup else None, "verdict": "ok" if ok else "blocked"})
        print(json.dumps(info, ensure_ascii=False, indent=2))
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
