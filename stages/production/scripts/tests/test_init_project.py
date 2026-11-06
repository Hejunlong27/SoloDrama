# -*- coding: utf-8 -*-
"""`init_project.py` 离线测试 —— 零网络、零计费。

它守的是「新项目开箱可用」：
结构缺一个目录、模板漏一个字段，后面每个环节都会踩一次。

覆盖：
* **A 结构**：9 个阶段目录 / layout.json / config.local.json 回填 / 资产子目录
* **B 模板**：6 个模板文件 / drama.json 四维 / 名册可被 plan 吃下
* **C 幂等**：重跑不覆盖 / --force 覆盖 / 干跑不写盘
* **D 与调度器对齐**：骨架必须被 `nodes.py` 判成「未完成」，不能假装已完成

```bash
python tests/test_init_project.py
```
"""
import argparse
import json
import os
import pathlib
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
# SCRIPTS=stages/production/scripts → parents[0]=stages/production, [1]=stages, [2]=仓库根
ROOT = pathlib.Path(SCRIPTS).parents[2]
assert (ROOT / "stages" / "_layout.py").is_file(), "仓库根定位失败：%s" % ROOT

# init 不依赖 _ws（它要在工作区还不存在时就能跑），所以这里不用设环境变量
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, str(ROOT / "stages"))

import init_project as IP                                       # noqa: E402
import _layout as L                                              # noqa: E402

CASES = []
_TMP = pathlib.Path(tempfile.mkdtemp(prefix="sd_init_"))


def reg(group, name):
    def deco(fn):
        CASES.append((group, name, fn))
        return fn
    return deco


def A_(cond, msg=""):
    if not cond:
        raise AssertionError(msg or "断言失败")


def fresh(name: str = "", **kw) -> pathlib.Path:
    ws = _TMP / (name or ("p%d" % len(list(_TMP.iterdir()))))
    if ws.exists():
        shutil.rmtree(ws)
    args = ["--workspace", str(ws), "--title", kw.pop("title", "测试剧")]
    for k, v in kw.items():
        args += ["--" + k.replace("_", "-"), str(v)]
    rc = IP.main(args)
    A_(rc == 0, "init 返回 %d" % rc)
    return ws


# =========================================================================== A 结构
@reg("A", "A01 9 个阶段目录齐全，且每个都有 README")
def _():
    ws = fresh()
    lay = json.loads((ws / "layout.json").read_text(encoding="utf-8"))
    A_(lay.get("layout_version") == L.LAYOUT_VERSION, "layout_version 不对")
    A_(set(lay["stages"]) == set(L.STAGE_DIRS), "阶段集合与 _layout 不一致")
    miss = [d for d in lay["stages"].values() if not (ws / d).is_dir()]
    A_(not miss, "缺目录：%s" % miss)
    no_readme = [d for d in lay["stages"].values() if not (ws / d / "README.md").is_file()]
    A_(not no_readme, "缺 README：%s" % no_readme)
    return "%d 个阶段目录" % len(lay["stages"])


@reg("A", "A02 config.local.json 回填 data/out/assets 三个覆盖键")
def _():
    ws = fresh()
    cfg = json.loads((ws / "video-pipeline" / "config.local.json").read_text(encoding="utf-8"))
    for k in ("data_dir", "out_dir", "assets_dir"):
        A_(cfg.get(k), "缺 %s" % k)
        A_(cfg[k].startswith("../"), "%s 应是相对 engine_root 的路径：%s" % (k, cfg[k]))
    # 关键：布局真源能解析出与之一致的目录
    A_(L.data_dir(ws).is_dir(), "data_dir 解析后不存在：%s" % L.data_dir(ws))
    A_(L.assets_dir(ws).is_dir(), "assets_dir 解析后不存在：%s" % L.assets_dir(ws))
    return "3 键齐 / 解析一致"


@reg("A", "A03 资产子目录（characters / scenes / props）建好")
def _():
    ws = fresh()
    adir = L.assets_dir(ws)
    for sub in ("characters", "scenes", "props"):
        A_((adir / sub).is_dir(), "缺 %s" % sub)
    return "3 个子目录"


# =========================================================================== B 模板
@reg("B", "B01 6 个模板文件齐全")
def _():
    ws = fresh()
    need = ["drama.json", "04-资产/design/roster.json", "04-资产/refs.json",
            "03-剧本/blueprint.md", "03-剧本/ep_01.md", "05-分镜/ep01_storyboard.md"]
    miss = [n for n in need if not (ws / n).is_file()]
    A_(not miss, "缺模板：%s" % miss)
    return "%d 个" % len(need)


@reg("B", "B02 drama.json 四维正确落盘")
def _():
    ws = fresh(title="四维测试", track="2d_animation", look="ink-wash-2d",
               narrative="dialogue", aspect="9:16", episodes=12, ep_seconds=90)
    d = json.loads((ws / "drama.json").read_text(encoding="utf-8"))
    f = d["format"]
    A_(f["track"] == "2d_animation", "track 不对：%s" % f["track"])
    A_(f["look"] == "ink-wash-2d", "look 不对：%s" % f["look"])
    A_(f["narrative"] == "dialogue", "narrative 不对")
    A_(f["aspect"] == "9:16", "aspect 不对")
    A_(d["episodes"]["count"] == 12 and d["episodes"]["seconds"] == 90,
        "集数/时长不对：%s" % d["episodes"])
    return "track/look/narrative/aspect 全对"


@reg("B", "B03 名册模板结构完整（不再是死数据）")
def _():
    """原用例 import 了已删除的 character_design —— 2026-11 重构后改测模板自身结构。

    名册现在只是**写给人和 LLM 的模板**，没有脚本消费它；能校验的是：
    两个占位角色、必备字段齐、tier 分级正确。
    """
    ws = fresh()
    roster = json.loads((ws / "04-资产" / "design" / "roster.json").read_text(encoding="utf-8"))
    chars = roster.get("characters") or []
    A_(len(chars) == 2, "应有 2 个占位角色，实际 %d" % len(chars))
    for c in chars:
        for k in ("name", "code", "tier", "identity"):
            A_(c.get(k), "角色缺字段 %s：%s" % (k, c))
    A_(sorted(c["tier"] for c in chars) == ["lead", "support"], "tier 分级不对")
    note = json.dumps(roster, ensure_ascii=False)
    A_("character_design" not in note or "移除" in note,
       "名册注释还在引导调用已删除的 character_design.py")
    return "2 角色 / 字段齐 / tier 正确"


@reg("B", "B04 三个内容模板都带 STATUS: DRAFT 标记")
def _():
    ws = fresh()
    for rel in ("03-剧本/blueprint.md", "03-剧本/ep_01.md", "05-分镜/ep01_storyboard.md"):
        t = (ws / rel).read_text(encoding="utf-8")
        A_("STATUS: DRAFT" in t, "%s 缺 DRAFT 标记" % rel)
    return "3 个模板都是 DRAFT"


@reg("B", "B05 refs.json 是空结构（不预置假 key）")
def _():
    ws = fresh()
    d = json.loads((ws / "04-资产" / "refs.json").read_text(encoding="utf-8"))
    for k in ("characters", "scenes", "props"):
        A_(k in d, "缺 %s" % k)
        A_(d[k] == {}, "%s 应是空的，实际 %s" % (k, d[k]))
    return "3 个空表"


# =========================================================================== C 幂等
@reg("C", "C01 重跑不覆盖已有模板（幂等）")
def _():
    ws = fresh()
    p = ws / "03-剧本" / "ep_01.md"
    p.write_text(p.read_text(encoding="utf-8") + "\n我的内容\n", encoding="utf-8")
    rc = IP.main(["--workspace", str(ws), "--title", "另一个标题"])
    A_(rc == 0, "重跑返回 %d" % rc)
    A_("我的内容" in p.read_text(encoding="utf-8"), "重跑覆盖了已有内容")
    return "内容保住"


@reg("C", "C02 --force 才覆盖")
def _():
    ws = fresh()
    p = ws / "03-剧本" / "ep_01.md"
    p.write_text("被改过的内容\n", encoding="utf-8")
    IP.main(["--workspace", str(ws), "--force"])
    t = p.read_text(encoding="utf-8")
    A_("被改过的内容" not in t, "--force 没覆盖")
    A_("STATUS: DRAFT" in t, "--force 后应是模板")
    return "覆盖生效"


@reg("C", "C03 干跑不写盘")
def _():
    ws = _TMP / "dryrun_only"
    if ws.exists():
        shutil.rmtree(ws)
    rc = IP.main(["--workspace", str(ws), "--dry-run"])
    A_(rc == 0, "干跑返回 %d" % rc)
    A_(not ws.exists(), "干跑不该建目录")
    return "未落盘"


@reg("C", "C04 缺 --workspace 时拒绝（不猜路径）")
def _():
    try:
        IP.main(["--title", "x"])
    except SystemExit as e:
        return "exit %s" % e.code
    raise AssertionError("缺 --workspace 竟然没报错")


# =========================================================================== D 与调度器对齐
@reg("D", "D01 新骨架判「没开工」：首节点 import.pack 缺料，next 停在它上面")
def _():
    """原用例断言 `script.blueprint` —— 该节点已在 2026-11 重构中移除（引擎从导入开始）。

    现在能断言的是：空骨架下第一个节点判 failed，且 next 指向它。
    """
    ws = fresh()
    os.environ["SOLODRAMA_WORKSPACE"] = str(ws)
    for m in [k for k in list(sys.modules) if k in ("_ws", "_layout", "nodes")]:
        sys.modules.pop(m, None)
    sys.path.insert(0, SCRIPTS)
    sys.path.insert(0, str(ROOT / "stages"))
    import nodes as N                                           # noqa: E402
    ctx = N.Ctx(ws, "ep01")

    st = N.node_state(ctx, N.NODE_BY_ID["import.pack"])
    # 空骨架下产物根本不存在 → 判据给的是 absent（不是 failed）。两者都算「没开工」。
    A_(st["state"] in ("absent", "failed"),
       "空骨架应判 absent/failed，实际 %s（%s）" % (st["state"], st.get("detail")))
    nx = N.next_node(ctx)
    A_(nx and nx["node"]["id"] == "import.pack",
        "next 应停在 import.pack，实际 %s" % (nx["node"]["id"] if nx else None))
    return "absent / next=import.pack"


@reg("D", "D02 判据必须点名缺哪个文件（不是只给一个 false）")
def _():
    """可诊断性：报错要说清缺什么。旧版只测「蓝图通过」，节点没了就改成测报错质量。"""
    ws = fresh()
    os.environ["SOLODRAMA_WORKSPACE"] = str(ws)
    sys.path.insert(0, SCRIPTS)
    sys.path.insert(0, str(ROOT / "stages"))
    import nodes as N                                           # noqa: E402
    ctx = N.Ctx(ws, "ep01")
    ok, detail = N.check_node(ctx, N.NODE_BY_ID["import.pack"])
    A_(not ok, "空骨架不该判通过")
    A_("shots.json" in detail, "报错没点名缺件：%s" % detail)
    return detail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", default="")
    args = ap.parse_args()
    groups = [args.group.upper()] if args.group else ["A", "B", "C", "D"]
    passed = failed = 0
    try:
        for g in groups:
            sel = [c for c in CASES if c[0] == g]
            if not sel:
                continue
            print("【%s 组】%d 例" % (g, len(sel)))
            print("=" * 84)
            for _, name, fn in sel:
                try:
                    note = fn() or ""
                    print("  [PASS] %-52s %s" % (name, note))
                    passed += 1
                except AssertionError as e:
                    print("  [FAIL] %-52s %s" % (name, e))
                    failed += 1
                except Exception as e:                          # noqa: BLE001
                    print("  [ERR ] %-52s %s: %s" % (name, type(e).__name__, e))
                    failed += 1
            print()
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)
    print("=" * 84)
    print("合计 %d 例 ｜ 通过 %d ｜ 失败 %d" % (passed + failed, passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
