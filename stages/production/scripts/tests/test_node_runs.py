# -*- coding: utf-8 -*-
"""节点执行体（`run` 字段）的静态自检 —— **零网络、零计费、零执行**。

为什么需要它
------------
`nodes.py` 的 23 个节点里，`run` 写的是「计划执行什么」。2026-11-01 之前，剪辑那 5 个
节点的 `run` 是**想当然写下的**，三种错法同时存在：

  1. `stages/subtitle/scripts/upscale.py` —— 这个文件不存在（放大是 `subtitle.py` 的
     一个 stage，靠 provider 决定走 Topaz 还是 RH）。
  2. `stages/subtitle/scripts/bgm.py` —— 实际在 `stages/production/scripts/` 下。
  3. `bgm.py mix` / `release_export.py` —— **默认干跑**，不带 `--apply` 就永远不落盘。

三种错都不会抛异常：节点只会「一直过不去」，而报错说的是「找不到 `*_bgm.mp4`」——
看起来像数据缺失，人就会去查素材、查 ffmpeg，唯独不会去查 `run` 里少了一个开关。

这份测试把「路径与开关」变成判据，挡在提交前。它不执行任何脚本，只做静态核对：
文件在不在、脚本有没有 `--apply` 门闸、`--all` 有没有越界到别的集。

```bash
python stages/production/scripts/tests/test_node_runs.py
```
"""
import os
import pathlib
import shutil
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
SCRIPTS = HERE.parent


def _repo_root() -> pathlib.Path:
    """向上找带 `stages/_layout.py` 的仓库根。

    ★ 不数 `parents[N]`：这个仓库里数错一层已经发生六次，每次都表现为
      「文件不存在 / 仓库根定位失败」，而人第一反应是去查数据。
    """
    for up in HERE.parents[:7]:
        if (up / "stages" / "_layout.py").is_file():
            return up
    raise SystemExit("仓库根定位失败：从 %s 向上 7 层都没找到 stages/_layout.py" % HERE)


ROOT = _repo_root()
FIXTURE = HERE / "fixtures" / "mini_drama"

_TMP = pathlib.Path(tempfile.mkdtemp(prefix="sd_runs_"))
_WS = _TMP / "mini_drama"
shutil.copytree(FIXTURE, _WS)
os.environ["SOLODRAMA_WORKSPACE"] = str(_WS)
sys.path.insert(0, str(SCRIPTS))

import nodes as N                                               # noqa: E402

CASES = []


def reg(group: str, name: str):
    def deco(fn):
        CASES.append((group, name, fn))
        return fn
    return deco


def A_(cond, msg):
    if not cond:
        raise AssertionError(msg)


def _script_of(run: str) -> str:
    """从 `python <script> ...` 里取出脚本路径（相对仓库根）。"""
    parts = str(run).split()
    return parts[1] if len(parts) > 1 else ""


def _is_declared(run: str) -> bool:
    """`（手写…` / `（内置判据…` —— 显式声明「没有外部命令」。"""
    return str(run).strip().startswith("（")


def _apply_gated(script_text: str, run: str) -> bool:
    """脚本是否「默认干跑、必须显式 --apply」，而命令却没带。

    单独抽成函数是为了让 R06 能反过来验证它 —— 一个永远返回 False 的检测器
    会让 R03 永远通过，那种绿比红更有害。
    """
    gated = '"--apply"' in script_text and "store_true" in script_text
    return bool(gated and "--apply" not in str(run))


@reg("R", "R01 每个节点都有 run，且形态合法（python 命令 / 显式声明）")
def _():
    miss = [n["id"] for n in N.NODES if not str(n.get("run") or "").strip()]
    A_(not miss, "这些节点没有 run：%s" % "、".join(miss))
    bad = [n["id"] for n in N.NODES
           if not _is_declared(n["run"]) and not str(n["run"]).startswith("python ")]
    A_(not bad, "run 既不是 python 命令也没声明为人工/内置：%s" % "、".join(bad))
    return "%d 个节点全部有执行体或显式声明" % len(N.NODES)


@reg("R", "R02 python 命令指向的脚本必须真实存在")
def _():
    bad = []
    for n in N.NODES:
        run = str(n.get("run") or "")
        if not run.startswith("python "):
            continue
        s = _script_of(run)
        if not s or not (ROOT / s).is_file():
            bad.append("%s → %s" % (n["id"], s or "(空)"))
    A_(not bad, "以下 run 指向不存在的脚本（旧事故：upscale.py 根本不存在）：\n  " + "\n  ".join(bad))
    return "全部指向真实文件"


@reg("R", "R03 目标脚本有 --apply 门闸时，run 必须带 --apply")
def _():
    bad = []
    for n in N.NODES:
        run = str(n.get("run") or "")
        if not run.startswith("python "):
            continue
        src = (ROOT / _script_of(run))
        try:
            text = src.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # 脚本里有 `--apply` 且是 store_true（默认干跑）→ 命令不带它等于永远空转
        if _apply_gated(text, run):
            bad.append("%s → %s（脚本默认干跑）" % (n["id"], _script_of(run)))
    A_(not bad, "以下节点会永远空转（脚本默认干跑、命令没带 --apply）：\n  " + "\n  ".join(bad))
    return "无空转节点"


@reg("R", "R04 ep 级节点不许用 --all（会把别的集一起跑）")
def _():
    bad = [n["id"] for n in N.NODES
           if n.get("ep") and "--all" in str(n.get("run") or "")]
    A_(not bad, "ep 级节点用了 --all：%s" % "、".join(bad))
    return "ep 级节点均按集执行"


@reg("R", "R05 cmd: 检查器能解析到脚本")
def _():
    bad = []
    for n in N.NODES:
        spec = str(n.get("check") or "")
        if not spec.startswith("cmd:"):
            continue
        name = spec[4:].split()[0]
        # 与 `_run_checker_cmd` 同一套候选：HERE 内的裸名 + 各环节 scripts
        cand = [SCRIPTS / name,
                ROOT / "tools" / name,
                ROOT / "stages" / "assets" / "scripts" / name,
                ROOT / "stages" / "creation" / "scripts" / name,
                ROOT / "stages" / "subtitle" / "scripts" / name]
        if not any(c.is_file() for c in cand):
            bad.append("%s → %s" % (n["id"], name))
    A_(not bad, "检查器解析不到：\n  " + "\n  ".join(bad))
    return "全部可解析"


@reg("R", "R06 检测器自测：正反两个方向都要能判出来")
def _():
    src_gated = 'ap.add_argument("--apply", action="store_true", help="真写（默认干跑）")'
    src_plain = 'ap.add_argument("--stage", default="all")'
    # 反例：脚本有门闸、命令没带 → 必须判「空转」
    A_(_apply_gated(src_gated, "python x.py mix"), "漏判了空转")
    # 正例：命令带了 → 不算
    A_(not _apply_gated(src_gated, "python x.py mix --apply"), "误判了已带开关的命令")
    # 正例：脚本没有门闸（subtitle.py 这种直接执行的）→ 不算
    A_(not _apply_gated(src_plain, "python x.py --stage master"), "把没有门闸的脚本判成空转")
    # 路径解析
    A_(_script_of("python stages/a/b.py --x 1") == "stages/a/b.py", "脚本路径切分错")
    A_(_is_declared("（手写）"), "手写声明没认出来")
    A_(not _is_declared("python x.py"), "把 python 命令误认成声明")
    return "检测器正反例均正确"


def main() -> int:
    only = sys.argv[1].upper().lstrip("-") if len(sys.argv) > 1 else ""
    ok = fail = 0
    for group, name, fn in CASES:
        if only and not name.upper().startswith(only):
            continue
        try:
            note = fn()
            ok += 1
            print("[PASS] %s%s" % (name, ("　—— " + note) if note else ""))
        except AssertionError as exc:
            fail += 1
            print("[FAIL] %s\n       %s" % (name, str(exc).replace("\n", "\n       ")))
        except Exception as exc:                                # noqa: BLE001
            fail += 1
            print("[ERR ] %s\n       %s: %s" % (name, type(exc).__name__, exc))
    print("=" * 74)
    print("合计 %d 例 ｜ 通过 %d ｜ 失败 %d" % (ok + fail, ok, fail))
    shutil.rmtree(_TMP, ignore_errors=True)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
