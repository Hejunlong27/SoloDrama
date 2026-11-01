# -*- coding: utf-8 -*-
"""migrate_profile.py —— 把三份旧确认单迁进单一档案 `drama.json`

    python migrate_profile.py --workspace <ws>            # 干跑，打印将写入的内容
    python migrate_profile.py --workspace <ws> --apply    # 真写；旧文件改名 .legacy
    python migrate_profile.py --workspace <ws> --apply --keep-legacy   # 真写但不动旧文件

为什么需要它：整改前「画风 / 通道 / 集数时长」散在 style-plan / model-plan /
project-setup 三份里，四维无法整体回答。迁移只做**可判定的映射**，不猜：
映射不出来的字段留空，由人在 drama.json 里补，绝不替用户编。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import drama_profile as P                                     # noqa: E402


def _mask(d: dict) -> dict:
    """回显时把明显的密钥类字段打码（档案里本来就不该有 Key，防御性）。"""
    out = json.loads(json.dumps(d))
    for k in list(out):
        if "key" in k.lower() or "token" in k.lower():
            out[k] = "***"
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="迁移到单一档案 drama.json")
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--apply", action="store_true", help="真写（默认只干跑）")
    ap.add_argument("--keep-legacy", action="store_true",
                    help="保留旧文件（默认改名为 *.legacy，只读留档）")
    ap.add_argument("--force", action="store_true", help="已存在 drama.json 时覆盖")
    a = ap.parse_args()

    ws = pathlib.Path(a.workspace).expanduser().resolve()
    if not ws.is_dir():
        print("[FAIL] 工作区不存在：%s" % ws)
        return 2

    if P.path_of(ws).exists() and not a.force:
        print("[SKIP] 已有 %s；要覆盖请加 --force" % P.path_of(ws))
        print("      当前：%s" % P.fmt_line(P.load(ws) or {}))
        return 0

    d = P.from_legacy(ws)
    print("=" * 74)
    print("迁移结果（干跑）" if not a.apply else "迁移结果（已写入）")
    print("=" * 74)
    print("工作区 : %s" % ws)
    print("旧文件 : %s" % ", ".join(
        n for n in (P.LEGACY_STYLE, P.LEGACY_MODELS, P.LEGACY_SETUP) if (ws / n).is_file()))
    print("摘要   : %s" % P.fmt_line(d))
    print()
    print(json.dumps(_mask(d), ensure_ascii=False, indent=2))

    missing = []
    if not d["format"]["track"]:
        missing.append("format.track（旧 style-plan 里没有 choice）")
    if not d["format"]["look"]:
        missing.append("format.look（旧档案只存了渲染流，没有题材 look）")
    if not d["episodes"]["count"]:
        missing.append("episodes.count")
    if not d["channel"]["image"]["engine"]:
        missing.append("channel.image.engine（旧 model-plan 里没有图片通道选择）")
    if not d["channel"]["video"]["engine"]:
        missing.append("channel.video.engine（旧三份里都没有视频通道；首次 video.resolve 会写入）")
    if missing:
        print()
        print("[需要人工补] 以下字段映射不出来，请在 drama.json 里补：")
        for m in missing:
            print("   - %s" % m)

    if not a.apply:
        print()
        print("★ 干跑结束。确认无误后加 --apply 真写。")
        return 0

    p = P.save(ws, d)
    print()
    print("[OK] 已写入 %s" % p)
    if not a.keep_legacy:
        for n in (P.LEGACY_STYLE, P.LEGACY_MODELS, P.LEGACY_SETUP):
            f = ws / n
            if f.is_file():
                dst = f.with_suffix(f.suffix + ".legacy")
                if dst.exists():
                    dst.unlink()
                f.rename(dst)
                print("     旧文件 → %s" % dst.name)
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                          # noqa: BLE001
        pass
    raise SystemExit(main())
