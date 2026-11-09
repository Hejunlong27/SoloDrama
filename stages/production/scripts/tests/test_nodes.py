# -*- coding: utf-8 -*-
"""`nodes.py` 离线测试 —— **零网络、零计费、零第三方依赖**。

为什么要有它
------------
13 节点状态机是整条链的调度真源。验收不能靠「真跑一部剧」——那等于用
「我做出一部短剧」证明「引擎没坏」，两件事不是一回事。

> ⚠ **2026-11-06 重写**：旧版按 23 节点 / 七环节写；重构后节点表缩成
> **5 环节 13 节点**（引擎只从导入开始，创作层已移出），旧用例 12/25 全红。
> 现在按当前 `NODES` 表重写。**节点增删时这份测试应当跟着红**，那是它对的地方。

分组：
* **A 表结构**：节点数 / 环节归属 / 字段齐 / next 链 / 回流白名单 / 判据可识别
* **B 状态推导**：absent / blocked / passed / stale / skipped，只读磁盘
* **C 判据**：imported / boards / assets / five 的正反例
* **D 调度**：next 语义、面板结构、stuck/escalate、回流白名单
* **E 命令拼装**：干跑与真跑共用同一份 argv

```bash
python stages/production/scripts/tests/test_nodes.py            # 全部
python stages/production/scripts/tests/test_nodes.py --group B  # 只跑某组
```
"""
import argparse
import json
import os
import pathlib
import shutil
import struct
import sys
import tempfile
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
FIXTURE = pathlib.Path(HERE) / "fixtures" / "mini_drama"

_TMP_ROOT = None


def _bootstrap():
    """`_ws` 在 import 期就解析工作区 → 先把环境变量指到夹具副本。"""
    global _TMP_ROOT
    _TMP_ROOT = pathlib.Path(tempfile.mkdtemp(prefix="sd_nodes_"))
    dst = _TMP_ROOT / "mini_drama"
    shutil.copytree(FIXTURE, dst)
    os.environ["SOLODRAMA_WORKSPACE"] = str(dst)
    sys.path.insert(0, SCRIPTS)
    sys.path.insert(0, str(pathlib.Path(SCRIPTS).parents[1]))
    return dst


WS = _bootstrap()
import nodes as N                                                  # noqa: E402

CASES = []


def reg(group, name):
    def deco(fn):
        CASES.append((group, name, fn))
        return fn
    return deco


def A_(cond, msg=""):
    if not cond:
        raise AssertionError(msg or "断言失败")


def png(path: pathlib.Path, w: int = 8, h: int = 8, rgb=(120, 120, 120)):
    """写一个合法 PNG（不依赖 Pillow）。"""
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    blob = (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b""))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(blob)


def fresh(ep: str = "ep01") -> "N.Ctx":
    d = pathlib.Path(tempfile.mkdtemp(prefix="sd_case_")) / "mini_drama"
    shutil.copytree(WS, d)
    return N.Ctx(d, ep)


def state_of(ctx, node_id: str) -> str:
    return N.node_state(ctx, N.NODE_BY_ID[node_id])["state"]


def put_data(ctx, shots: int = 2):
    """造出导入产物三件（判据 `imported` 只看这三样）。"""
    d = ctx.data / (ctx.ep or "ep01")
    d.mkdir(parents=True, exist_ok=True)
    (d / "shots.json").write_text(json.dumps(
        [{"id": "shot_%03d" % i, "duration": 5} for i in range(1, shots + 1)],
        ensure_ascii=False), encoding="utf-8")
    (d / "boards.json").write_text("[]", encoding="utf-8")
    (d / "h3_prompts.json").write_text("{}", encoding="utf-8")
    return d


# =========================================================================== A 表结构
@reg("A", "A01 13 节点 / 5 环节，顺序与环节归属自洽")
def _():
    A_(len(N.NODES) == 13, "节点数 %d ≠ 13" % len(N.NODES))
    A_(len(N.STAGES) == 5, "环节数 %d ≠ 5" % len(N.STAGES))
    stage_ids = {s["id"] for s in N.STAGES}
    for n in N.NODES:
        A_(n["stage"] in stage_ids, "%s 的 stage=%s 不在环节表里" % (n["id"], n["stage"]))
    # 每个环节至少一个节点
    for sid in stage_ids:
        A_(any(n["stage"] == sid for n in N.NODES), "环节 %s 没有任何节点" % sid)
    # ★ 这里**不能**要求环节连续：`import` 是有意穿插的 ——
    #   import.pack（进场）→ asset.render（出图）→ import.bind（回填参考表）→ board.frame
    #   → import.gate（导入门禁）。出图前后各要导一次，插在中间是对的。
    #   能锁的是「环节首次出现的顺序 == STAGES 的声明顺序」。
    first = []
    for n in N.NODES:
        if n["stage"] not in first:
            first.append(n["stage"])
    A_(first == [s["id"] for s in N.STAGES],
       "环节首次出现顺序与 STAGES 不一致：%s vs %s" % (first, [s["id"] for s in N.STAGES]))
    return "%d 节点 / %d 环节（import 穿插 %d 次）" % (
        len(N.NODES), len(N.STAGES), sum(1 for n in N.NODES if n["stage"] == "import"))


@reg("A", "A02 每个节点字段齐全，且 id 唯一")
def _():
    ids = [n["id"] for n in N.NODES]
    A_(len(ids) == len(set(ids)), "节点 id 重复")
    need = ("id", "stage", "trigger", "reads", "output", "check", "next", "run", "reflow")
    for n in N.NODES:
        for k in need:
            A_(k in n, "%s 缺字段 %s" % (n["id"], k))
        A_(str(n["trigger"]).startswith("drama do "), "%s 触发命令不规范：%s" % (n["id"], n["trigger"]))
        A_(str(n["output"]).strip(), "%s 没有产物落点" % n["id"])
    tail = [n["id"] for n in N.NODES if not n["next"]]
    A_(tail == ["edit.release"], "空 next 的节点应只有 edit.release，实际：%s" % tail)
    return "%d 个 id 唯一 / 字段齐" % len(ids)


@reg("A", "A03 next 链：指向存在、不自指、能走到终点且覆盖全表")
def _():
    for n in N.NODES:
        if not n["next"]:
            continue
        A_(n["next"] in N.NODE_BY_ID, "%s.next=%s 不存在" % (n["id"], n["next"]))
        A_(n["next"] != n["id"], "%s.next 指向自己" % n["id"])
    seen, cur, hop = [], N.NODES[0]["id"], 0
    while cur and hop < 50:
        A_(cur not in seen, "next 链成环：%s" % cur)
        seen.append(cur)
        cur = (N.NODE_BY_ID[cur].get("next") or "")
        hop += 1
    A_(len(seen) == len(N.NODES), "next 链只走到 %d/%d 个节点" % (len(seen), len(N.NODES)))
    A_(seen[-1] == "edit.release", "终点应是 edit.release，实际 %s" % seen[-1])
    return "%d 跳走完全表" % hop


@reg("A", "A04 回流白名单：只允许声明过的边，且只能往回")
def _():
    idx = {nid: i for i, nid in enumerate(N.ORDER)}
    for a, b in N.REFLOW_EDGES:
        A_(a in N.NODE_BY_ID and b in N.NODE_BY_ID, "回流边 %s→%s 有不存在的节点" % (a, b))
        A_(idx[b] < idx[a], "%s → %s：回流只能往回" % (a, b))
        A_(b in (N.NODE_BY_ID[a].get("reflow") or []), "%s 的 reflow 表里没声明 %s" % (a, b))
    A_(len(N.REFLOW_EDGES) >= 8, "回流边只有 %d 条，太少" % len(N.REFLOW_EDGES))
    return "%d 条，全部向回" % len(N.REFLOW_EDGES)


@reg("A", "A05 判据表达式都能被识别（不是错到永远不过）")
def _():
    ctx = fresh()
    unknown = []
    for n in N.NODES:
        _ok, detail = N.check_node(ctx, n)
        if str(detail).startswith("未知判据"):
            unknown.append((n["id"], n["check"]))
    A_(not unknown, "有未知判据：%s" % unknown)
    return "%d 个判据全部可判" % len(N.NODES)


# =========================================================================== B 状态推导
@reg("B", "B01 空骨架：首节点没开工，下游全部 blocked")
def _():
    ctx = fresh()
    st = state_of(ctx, "import.pack")
    A_(st in ("absent", "failed"), "首节点应 absent/failed，实际 %s" % st)
    A_(state_of(ctx, "asset.render") == "blocked",
       "下游应 blocked，实际 %s" % state_of(ctx, "asset.render"))
    return "import.pack=%s / asset.render=blocked" % st


@reg("B", "B02 blocked 的理由要写清是上游问题")
def _():
    ctx = fresh()
    detail = N.node_state(ctx, N.NODE_BY_ID["asset.render"])["detail"]
    A_("上游未通过" in detail, "blocked 理由太含糊：%s" % detail)
    return detail[:48]


@reg("B", "B03 补齐导入三件 → import.pack 通过，next 指向资产")
def _():
    ctx = fresh()
    put_data(ctx, shots=2)
    st = state_of(ctx, "import.pack")
    A_(st == "passed", "三件齐应通过，实际 %s（%s）" % (
        st, N.node_state(ctx, N.NODE_BY_ID["import.pack"])["detail"]))
    nx = N.next_node(ctx)
    A_(nx and nx["node"]["id"] == "asset.render",
       "next 应指向 asset.render，实际 %s" % (nx["node"]["id"] if nx else None))
    return "passed / next=asset.render"


@reg("B", "B04 stale 先于 passed：上游比产物新就必须重跑")
def _():
    ctx = fresh()
    d = put_data(ctx)
    png(ctx.ws / "04-资产" / "characters" / "char_01.png")
    refs = ctx.ws / "04-资产" / "refs.json"
    refs.write_text(json.dumps(
        {"characters": {"char_01": "04-资产/characters/char_01.png"}},
        ensure_ascii=False), encoding="utf-8")

    now = time.time()
    # 资产产物「旧」、导入产物「新」→ 资产必须报 stale（判定阈值是 1 秒）
    os.utime(refs, (now - 600, now - 600))
    for f in d.glob("*.json"):
        os.utime(f, (now, now))
    st = state_of(ctx, "asset.render")
    A_(st == "stale", "上游更新后应报 stale，实际 %s（%s）" % (
        st, N.node_state(ctx, N.NODE_BY_ID["asset.render"])["detail"]))
    # 刷新资产产物 mtime（等价于「重新确认过」）→ 回到 passed
    os.utime(refs, (now + 60, now + 60))
    A_(state_of(ctx, "asset.render") == "passed",
       "刷新后应 passed，实际 %s" % state_of(ctx, "asset.render"))
    return "stale → 刷新 → passed"


@reg("B", "B05 skip 记成 skipped，理由可追溯")
def _():
    ctx = fresh()
    rc = N.main(["skip", "board.frame", "--reason", "本剧不用分镜图",
                 "--workspace", str(ctx.ws)])
    A_(rc == 0, "skip 应返回 0，实际 %d" % rc)
    rec = json.loads((ctx.ws / ".drama" / "_skip" / "board.frame.json").read_text(encoding="utf-8"))
    A_(rec.get("reason") == "本剧不用分镜图", "理由没落盘：%s" % rec)
    st = N.node_state(ctx, N.NODE_BY_ID["board.frame"])
    A_(st["state"] == "skipped", "skip 后应为 skipped，实际 %s" % st["state"])
    return "skipped + 理由可追溯"


# =========================================================================== C 判据正反例
@reg("C", "C01 imported：缺件点名；补齐报镜数")
def _():
    ctx = fresh()
    ok, detail = N.check_node(ctx, N.NODE_BY_ID["import.pack"])
    A_(not ok, "空 data 不该通过")
    for name in ("shots.json", "boards.json", "h3_prompts.json"):
        A_(name in detail, "报错没点名 %s：%s" % (name, detail))
    put_data(ctx, shots=3)
    ok, detail = N.check_node(ctx, N.NODE_BY_ID["import.pack"])
    A_(ok and "3 镜" in detail, "补齐后应报 3 镜，实际 %s" % detail)
    return detail


@reg("C", "C02 boards：张数不足要卡，补足才过")
def _():
    ctx = fresh()
    put_data(ctx, shots=2)
    bd = ctx.ws / "04-资产" / "boards" / "ep01"
    png(bd / "shot_001.png")
    ok, detail = N.check_node(ctx, N.NODE_BY_ID["board.frame"])
    A_(not ok, "1 张对 2 镜应不过，实际 %s" % detail)
    png(bd / "shot_002.png")
    ok, detail = N.check_node(ctx, N.NODE_BY_ID["board.frame"])
    A_(ok, "补到 2 张应通过，实际 %s" % detail)
    return detail


@reg("C", "C03 assets：空 refs 不过；有图过；缺图点名")
def _():
    ctx = fresh()
    ok, detail = N.check_node(ctx, N.NODE_BY_ID["asset.render"])
    A_(not ok, "空 refs 不该通过：%s" % detail)
    png(ctx.ws / "04-资产" / "scenes" / "scene_01.png")
    refs = ctx.ws / "04-资产" / "refs.json"
    refs.write_text(json.dumps({"scenes": {"scene_01": "04-资产/scenes/scene_01.png"}},
                               ensure_ascii=False), encoding="utf-8")
    ok, detail = N.check_node(ctx, N.NODE_BY_ID["asset.render"])
    A_(ok, "登记且图存在应通过，实际 %s" % detail)
    refs.write_text(json.dumps({"scenes": {"scene_01": "04-资产/scenes/不存在.png"}},
                               ensure_ascii=False), encoding="utf-8")
    ok, detail = N.check_node(ctx, N.NODE_BY_ID["asset.render"])
    A_(not ok and "scene_01" in detail, "缺图要点名，实际 %s" % detail)
    return "空不过 / 有图过 / 缺图点名"


@reg("C", "C04 five：参考表未回填时不算齐")
def _():
    ctx = fresh()
    put_data(ctx, shots=2)
    ok, detail = N.check_node(ctx, N.NODE_BY_ID["import.bind"])
    A_(not ok, "characters/scenes 没回填不该通过")
    A_("characters.json" in detail, "报错没点名 characters.json：%s" % detail)
    d = ctx.data / "ep01"
    (d / "characters.json").write_text("{}", encoding="utf-8")
    (d / "scenes.json").write_text("{}", encoding="utf-8")
    ok, detail = N.check_node(ctx, N.NODE_BY_ID["import.bind"])
    A_(ok, "补两表后应通过，实际 %s" % detail)
    return detail


@reg("C", "C05 draft：只认生成器自检结论，不认目录存在")
def _():
    ctx = fresh()
    node = N.NODE_BY_ID["edit.draft"]
    ok, detail = N.check_node(ctx, node)
    A_(not ok, "没有清单不该通过")
    A_("edit_draft" in detail or "draft_manifest" in detail, "报错没指向生成器：%s" % detail)

    base = ctx.out / "ep01" / "_draft"
    base.mkdir(parents=True, exist_ok=True)
    man = base / "draft_manifest.json"
    man.write_text(json.dumps({"verdict": {"pass": False,
                                           "fails": ["字幕起点 500000 µs ≠ 预期 1000000 µs"]}},
                              ensure_ascii=False), encoding="utf-8")
    ok, detail = N.check_node(ctx, node)
    A_(not ok, "verdict.pass=False 不该通过（目录在也不行）")
    A_("字幕起点" in detail, "失败理由没透出：%s" % detail)

    man.write_text(json.dumps({
        "draft_dir": "%s/ep01_剪映工程" % base,
        "total_duration_s": 4.3,
        "verdict": {"pass": True, "fails": [],
                    "counts": {"video": 3, "text": 2, "audio": 0, "materials": 3}}},
        ensure_ascii=False), encoding="utf-8")
    ok, detail = N.check_node(ctx, node)
    A_(ok, "自检通过后应放行，实际 %s" % detail)
    A_("4.3s" in detail, "详情没带总时长：%s" % detail)
    return detail


# =========================================================================== D 调度
@reg("D", "D01 next 跳过已通过项，指向第一个没过的")
def _():
    ctx = fresh()
    put_data(ctx)
    nx = N.next_node(ctx)
    A_(nx and nx["node"]["id"] == "asset.render", "next 应跳过 import.pack，实际 %s"
       % (nx["node"]["id"] if nx else None))
    N.main(["skip", "asset.render", "--reason", "复用上一部剧的资产", "--workspace", str(ctx.ws)])
    nx = N.next_node(ctx)
    A_(nx and nx["node"]["id"] == "import.bind", "跳过资产后 next 应到 import.bind，实际 %s"
       % (nx["node"]["id"] if nx else None))
    return "import.pack 通过 / 资产跳过后 → import.bind"


@reg("D", "D02 面板结构稳定：13 行、状态合法、counts 自洽")
def _():
    ctx = fresh()
    ev = N.evaluate(ctx)
    for k in ("ws", "ep", "nodes", "counts"):
        A_(k in ev, "缺字段 %s" % k)
    A_(len(ev["nodes"]) == 13, "节点数不对：%d" % len(ev["nodes"]))
    A_(sum(ev["counts"].values()) == 13, "counts 合计应 13")
    for r in ev["nodes"]:
        A_({"id", "state", "detail"} <= set(r), "节点行缺字段：%s" % r)
        A_(r["state"] in ("passed", "failed", "absent", "stale", "skipped", "blocked"),
            "非法状态 %s" % r["state"])
    txt = N.render_status(ev)
    A_("五环节 13 节点" in txt, "状态面板标题丢了环节/节点数")
    graph = N.render_graph()
    for n in N.NODES:
        A_(n["id"] in graph, "流程图里没有 %s" % n["id"])
    return "13 节点 / counts 自洽 / 面板与流程图覆盖全表"


@reg("D", "D03 同一失败方案第二次判 stuck；换方案可继续")
def _():
    ctx = fresh()
    payload = {"fix": "调低 steps"}
    r1 = N.record_attempt(ctx, "video.batch", payload, False, "片段 3 缺音轨")
    A_(r1["verdict"] == "retry", "第一次应 retry，实际 %s" % r1["verdict"])
    r2 = N.record_attempt(ctx, "video.batch", payload, False, "片段 3 缺音轨")
    A_(r2["verdict"] == "stuck", "同方案再失败应 stuck，实际 %s" % r2["verdict"])
    A_(r2["variant_hash"] == r1["variant_hash"], "两次 hash 应相同")
    r3 = N.record_attempt(ctx, "video.batch", {"fix": "换工作流"}, False, "还是不行")
    A_(r3["verdict"] == "retry", "换了方案应重新计数，实际 %s" % r3["verdict"])
    return "retry → stuck → 换方案 retry"


@reg("D", "D04 L1 预算 3 次，第 4 次升级")
def _():
    ctx = fresh()
    vs = [N.record_attempt(ctx, "video.batch", {"v": i}, False, "no")["verdict"] for i in range(1, 5)]
    A_(vs[:3] == ["retry"] * 3, "前三次应 retry：%s" % vs)
    A_(vs[3] == "escalate", "第四次应 escalate：%s" % vs)
    return "retry×3 → escalate"


@reg("D", "D05 回流只走白名单：命中给目标，未命中给 None")
def _():
    ctx = fresh()
    A_(N.reflow_target(ctx, "board.frame") == "import.bind", "board.frame 应能回 import.bind")
    A_(N.reflow_target(ctx, "edit.release") == "edit.subtitle", "edit.release 应能回 edit.subtitle")
    A_(N.reflow_target(ctx, "import.pack") is None, "import.pack 没有上游，不该有回流目标")
    return "命中两支 / 未命中返回 None"


# =========================================================================== E 命令拼装
@reg("E", "E01 干跑与真跑同一份 argv：{ws} 已展开、带 workspace 与 ep")
def _():
    ctx = fresh()
    args = N._build_args(ctx, N.NODE_BY_ID["import.pack"])
    A_(args[0] in ("python", "python3"), "首项应是解释器，实际 %s" % args[0])
    A_(not any("{" in a for a in args), "占位符没展开：%s" % args)
    A_(str(ctx.ws) in " ".join(args), "argv 里没有工作区路径：%s" % args)
    A_("pack_import.py" in " ".join(args), "没指向 pack_import.py：%s" % args)
    A_("--ep" in args and "ep01" in args, "带集号的节点应补 --ep ep01：%s" % args)
    return " ".join(args[-4:])


@reg("E", "E02 不带集号的节点不硬塞 --ep")
def _():
    ctx = fresh()
    args = N._build_args(ctx, N.NODE_BY_ID["asset.render"])
    A_("--ep" not in args, "非集节点不该带 --ep：%s" % args)
    A_("--workspace" in args, "缺 --workspace：%s" % args)
    return "asset.render 只带 --workspace"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", default="")
    args = ap.parse_args()
    groups = [args.group.upper()] if args.group else ["A", "B", "C", "D", "E"]
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
        if _TMP_ROOT and _TMP_ROOT.is_dir():
            shutil.rmtree(_TMP_ROOT, ignore_errors=True)
    print("=" * 84)
    print("合计 %d 例 ｜ 通过 %d ｜ 失败 %d" % (passed + failed, passed, failed))
    print("=" * 84)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
