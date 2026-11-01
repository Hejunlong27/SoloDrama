# -*- coding: utf-8 -*-
"""`nodes.py` 离线测试 —— **零网络、零计费、零第三方依赖**。

为什么要有它
------------
23 节点状态机是整条链的调度真源。它此前**没有任何测试**，验收只能靠「真跑一部剧」——
那等于用「我做出一部短剧」来证明「引擎没坏」，两件事根本不是一回事：
剧做出来可能是我手工补了内容，引擎照样有 bug；剧做不出来又分不清是谁的问题。

这份测试用 `fixtures/mini_drama`（1 集 2 镜的最小项目）让引擎**自己证明自己**：

* **A 节点表**：23 节点 / 七环节 / 六字段齐 / 回流白名单 / 判据可判
* **B 状态推导**：absent / passed / blocked / skipped / stale 的判定，只读磁盘
* **C 判据**：ffs / board / five / script / assets 的正反例
* **D Loop**：variant_hash 防抖、L1 预算、L2 回流白名单
* **E 执行**：内置判据节点可跑、marker 落盘、可选节点不阻塞

```bash
python tests/test_nodes.py            # 全部
python tests/test_nodes.py --group B  # 只跑某组
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
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
FIXTURE = pathlib.Path(HERE) / "fixtures" / "mini_drama"

# `_ws` 在 import 期就解析工作区，找不到会 SystemExit ——
# 所以在 import nodes 之前先把环境变量指到夹具的临时副本。
_TMP_ROOT = None


def _bootstrap():
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
    """写一个合法的极简 PNG（不依赖 Pillow）。"""
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
    """每次拿一份新的夹具副本，互不干扰。"""
    d = pathlib.Path(tempfile.mkdtemp(prefix="sd_case_")) / "mini_drama"
    shutil.copytree(WS, d)
    return N.Ctx(d, ep)


def state_of(ctx, node_id: str) -> str:
    return N.node_state(ctx, N.NODE_BY_ID[node_id])["state"]


# =========================================================================== A 节点表
@reg("A", "A01 23 节点 / 七环节，顺序与环节归属自洽")
def _():
    A_(len(N.NODES) == 23, "节点数 %d ≠ 23" % len(N.NODES))
    A_(len(N.STAGES) == 7, "环节数 %d ≠ 7" % len(N.STAGES))
    stage_ids = {s["id"] for s in N.STAGES}
    for n in N.NODES:
        A_(n["stage"] in stage_ids, "%s 的 stage=%s 不在环节表里" % (n["id"], n["stage"]))
    # 每个环节至少一个节点，且相邻节点的 stage 不来回跳（拓扑要能顺着读）
    seen, last = [], None
    for n in N.NODES:
        if n["stage"] != last:
            A_(n["stage"] not in seen, "环节 %s 在顺序里出现了两次（拓扑分段了）" % n["stage"])
            seen.append(n["stage"])
            last = n["stage"]
    A_(len(seen) == 7, "顺序里只出现 %d 个环节" % len(seen))
    return "%d 节点 / %d 环节" % (len(N.NODES), len(N.STAGES))


@reg("A", "A02 每个节点六字段齐全，且 id 唯一")
def _():
    ids = [n["id"] for n in N.NODES]
    A_(len(ids) == len(set(ids)), "节点 id 重复")
    for n in N.NODES:
        for k in ("id", "stage", "trigger", "reads", "output", "check", "next", "run"):
            A_(k in n, "%s 缺字段 %s" % (n["id"], k))
        A_(str(n["trigger"]).startswith("drama do "), "%s 的触发命令不规范：%s" % (n["id"], n["trigger"]))
        A_(str(n["output"]).strip(), "%s 没有产物落点" % n["id"])
    # 只有最后一个节点允许 next 为空
    tail = [n["id"] for n in N.NODES if not n["next"]]
    A_(tail == ["edit.release"], "空 next 的节点应只有 edit.release，实际：%s" % tail)
    return "%d 个 id 唯一 / 字段齐" % len(ids)


@reg("A", "A03 next 必须指向存在的节点，且不会指回自己")
def _():
    for n in N.NODES:
        if not n["next"]:
            continue
        A_(n["next"] in N.NODE_BY_ID, "%s.next=%s 不存在" % (n["id"], n["next"]))
        A_(n["next"] != n["id"], "%s.next 指向自己" % n["id"])
    return "全部 next 有效"


@reg("A", "A04 回流边白名单：只允许表里声明过的边，且都是向前的上游")
def _():
    idx = {nid: i for i, nid in enumerate(N.ORDER)}
    for a, b in N.REFLOW_EDGES:
        A_(b in N.NODE_BY_ID, "回流目标 %s 不存在" % b)
        A_(idx[b] < idx[a], "%s → %s：回流只能往回，不能往前" % (a, b))
        A_(b in (N.NODE_BY_ID[a].get("reflow") or []), "%s 的 reflow 表里没有 %s" % (a, b))
    A_(len(N.REFLOW_EDGES) >= 15, "回流边只有 %d 条，太少了" % len(N.REFLOW_EDGES))
    return "%d 条，全部向前回退" % len(N.REFLOW_EDGES)


@reg("A", "A05 判据表达式都能被 check_node 识别（不是错到永远不过）")
def _():
    ctx = fresh()
    unknown = []
    for n in N.NODES:
        ok, detail = N.check_node(ctx, n)
        if str(detail).startswith("未知判据"):
            unknown.append((n["id"], n["check"]))
    A_(not unknown, "有未知判据：%s" % unknown)
    return "%d 个判据全部可判" % len(N.NODES)


# =========================================================================== B 状态推导
@reg("B", "B01 夹具就绪时：剧本/资产通过，分镜图与出片卡住")
def _():
    ctx = fresh()
    A_(state_of(ctx, "script.blueprint") == "passed", "蓝图应通过")
    A_(state_of(ctx, "script.episode") == "passed", "剧本应通过（ep_01.md）")
    A_(state_of(ctx, "asset.roster") == "passed", "名册应通过")
    # 分镜图还没出（夹具里是空目录）
    st = state_of(ctx, "board.frame")
    A_(st in ("blocked", "failed", "absent"), "分镜图未出时应卡住，实际 %s" % st)
    return "剧本/资产 passed，分镜图 %s" % st


@reg("B", "B02 缺上游 → blocked，且 blocked 会向下游传播")
def _():
    ctx = fresh()
    A_(state_of(ctx, "video.batch") == "blocked", "出片应被上游阻塞")
    st = N.node_state(ctx, N.NODE_BY_ID["video.batch"])["detail"]
    A_("上游未通过" in st, "blocked 的理由要写清上游：%s" % st)
    return st[:40]


@reg("B", "B03 可选节点缺席 → skipped，且不阻塞下游")
def _():
    ctx = fresh()
    # 命题卡（positioning.json）夹具里故意没给 → optional，应 skipped
    A_(state_of(ctx, "research.topic") == "skipped", "可选节点缺席应 skipped")
    # 关键：它不该让 script.blueprint 变 blocked
    A_(state_of(ctx, "script.blueprint") == "passed", "可选节点缺席不该阻塞剧本")
    return "research.topic skipped，剧本仍 passed"


@reg("B", "B04 stale 先于 passed：上游新过产物就必须重跑")
def _():
    import time
    ctx = fresh()
    # 夹具里分镜 md 与剧本几乎同时创建 → 一开始 board.script 是 passed
    A_(state_of(ctx, "board.script") in ("passed", "blocked"),
        "初始状态异常：%s" % state_of(ctx, "board.script"))

    # ★ 2026-11-01：script.dialogue 插在 script.gate 之后，它是 asset.roster 的上游。
    #   不先过它，asset.prompt 会被判 blocked（而不是 stale），这条用例就测不到 stale。
    # 必须带 --ep：该节点的产物是 marker（_done/script.dialogue.<ep>.json），
    # 不带 ep 会写到 `script.dialogue.json`，与 ctx.ep=ep01 的查询路径对不上 —— 看起来像「没通过」。
    N.main(["do", "script.dialogue", "--ep", "ep01", "--workspace", str(ctx.ws)])
    A_(state_of(ctx, "script.dialogue") == "passed",
        "夹具剧本应通过台词复核，实际 %s" % state_of(ctx, "script.dialogue"))

    # 生成 bible（asset.prompt 是 board.script 的上游）。
    # ★ 2026-11-01：A1/A2 改为会话/技能产出后，`do asset.prompt` 只会回 TODO。
    #   测试里用「会话会做的事」代替：直接调骨架生成器落 bible，再看节点是否认。
    import subprocess
    r = subprocess.run([sys.executable, str(pathlib.Path(SCRIPTS).parents[1] / "assets" / "scripts" / "character_design.py"),
                        "plan", "--roster", str(ctx.ws / "04-资产" / "design" / "roster.json"),
                        "--out", str(ctx.ws / "04-资产" / "design")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    A_(r.returncode == 0, "骨架生成失败：%s" % (r.stderr or r.stdout)[-300:])
    A_(state_of(ctx, "asset.prompt") == "passed", "bible 生成后 asset.prompt 应通过")

    # ★ 关键断言：bible 刚生成、分镜 md 还是旧的 → board.script 必须报 stale。
    #   旧实现是「判据通过就 passed」，于是改完资产、分镜 md 一个字没动也照样 passed，
    #   拿上一版的分镜去出图，肉眼根本查不出来。
    st = state_of(ctx, "board.script")
    A_(st == "stale", "上游（bible）比分镜 md 新时应报 stale，实际 %s" % st)

    # 刷新分镜 md 的 mtime（等价于「人重新确认过」）→ 应回到 passed
    now = time.time()
    os.utime(ctx.ws / "05-分镜" / "ep01_storyboard.md", (now, now))
    A_(state_of(ctx, "board.script") == "passed", "刷新 mtime 后应回到 passed")
    return "stale → 刷新 → passed"


@reg("B", "B05 skip 命令把它记成 skipped，可追溯理由")
def _():
    ctx = fresh()
    rc = N.main(["skip", "board.frame", "--reason", "本剧不用分镜图",
                 "--workspace", str(ctx.ws)])
    A_(rc == 0, "skip 应返回 0，实际 %d" % rc)
    A_(state_of(ctx, "board.frame") == "skipped", "skip 后应为 skipped")
    rec = json.loads((ctx.ws / ".drama" / "_skip" / "board.frame.json").read_text(encoding="utf-8"))
    A_(rec.get("reason") == "本剧不用分镜图", "理由没落盘")
    return "skipped + 理由可追溯"


# =========================================================================== C 判据
@reg("C", "C01 ffs：夹具剧本通过；DUR 越界必不过")
def _():
    ctx = fresh()
    ok, detail = N.check_node(ctx, N.NODE_BY_ID["script.gate"])
    A_(ok, "夹具剧本应通过 ffs：%s" % detail)
    # 把 DUR 改成 20 秒（越界）
    f = ctx.ws / "03-剧本" / "ep_01.md"
    t = f.read_text(encoding="utf-8").replace("DUR: 6", "DUR: 20")
    f.write_text(t, encoding="utf-8", newline="")
    ok2, d2 = N.check_node(ctx, N.NODE_BY_ID["script.gate"])
    A_(not ok2, "DUR=20 应判不过")
    A_("越界" in d2, "理由要说明越界：%s" % d2)
    return detail[:40]


@reg("C", "C02 board：5 字段齐全才过，缺一个就点名")
def _():
    ctx = fresh()
    ok, detail = N.check_node(ctx, N.NODE_BY_ID["board.script"])
    A_(ok, "夹具分镜应通过：%s" % detail)
    f = ctx.ws / "05-分镜" / "ep01_storyboard.md"
    t = f.read_text(encoding="utf-8")
    # 删掉 shot_002 的 ratio 行
    t = t.replace("- duration: 5\n- ratio: 9:16\n- refs: char_ava, char_ben",
                  "- duration: 5\n- refs: char_ava, char_ben", 1)
    f.write_text(t, encoding="utf-8", newline="")
    ok2, d2 = N.check_node(ctx, N.NODE_BY_ID["board.script"])
    A_(not ok2, "缺 ratio 应判不过")
    A_("shot_002 缺 ratio" in d2, "应点名缺哪一镜哪个字段：%s" % d2)
    return detail


@reg("C", "C03 five：五文件缺一不过，齐了报镜数")
def _():
    ctx = fresh()
    d = ctx.data / "ep01"
    d.mkdir(parents=True, exist_ok=True)
    for n in ("shots.json", "boards.json", "h3_prompts.json", "characters.json"):
        (d / n).write_text("{}", encoding="utf-8")
    ok, detail = N.check_node(ctx, N.NODE_BY_ID["prompt.assemble"])
    A_(not ok, "缺 scenes.json 应判不过")
    A_("scenes.json" in detail, "应点名缺哪个：%s" % detail)
    (d / "scenes.json").write_text("{}", encoding="utf-8")
    ok2, d2 = N.check_node(ctx, N.NODE_BY_ID["prompt.assemble"])
    A_(ok2, "补齐后应通过：%s" % d2)
    return d2


@reg("C", "C04 boards：张数少于镜数不过（缺镜会被静默放过）")
def _():
    ctx = fresh()
    # 先造 shots.json（2 镜）
    d = ctx.data / "ep01"
    d.mkdir(parents=True, exist_ok=True)
    (d / "shots.json").write_text(json.dumps([
        {"shot_id": "shot_001"}, {"shot_id": "shot_002"}]), encoding="utf-8")
    bdir = ctx.ws / "04-资产" / "boards" / "ep01"
    png(bdir / "shot_001.png")
    ok, detail = N.check_node(ctx, N.NODE_BY_ID["board.frame"])
    A_(not ok, "只有 1 张图、2 个镜，应判不过")
    A_("1 / 镜数 2" in detail, "要报出比例：%s" % detail)
    png(bdir / "shot_002.png")
    ok2, d2 = N.check_node(ctx, N.NODE_BY_ID["board.frame"])
    A_(ok2, "补齐应通过：%s" % d2)
    return d2


@reg("C", "C05 assets：refs.json 的图缺一个就点名")
def _():
    ctx = fresh()
    rj = ctx.ws / "04-资产" / "refs.json"
    d = json.loads(rj.read_text(encoding="utf-8"))
    for rel in d["characters"].values():
        png(ctx.ws / "04-资产" / rel)
    ok, detail = N.check_node(ctx, N.NODE_BY_ID["asset.render"])
    A_(not ok, "场景图还没造，应判不过")
    A_("scene_room" in detail, "应点名缺哪张：%s" % detail)
    for rel in d["scenes"].values():
        png(ctx.ws / "04-资产" / rel)
    ok2, d2 = N.check_node(ctx, N.NODE_BY_ID["asset.render"])
    A_(ok2, "补齐应通过：%s" % d2)
    return d2


# =========================================================================== D Loop
@reg("D", "D01 variant_hash：同一方案重复失败判 stuck，不浪费第三次")
def _():
    ctx = fresh()
    payload = {"cmd": "same", "ep": "ep01"}
    r1 = N.record_attempt(ctx, "board.frame", payload, False, "still failing")
    A_(r1["verdict"] == "retry", "第一次应 retry，实际 %s" % r1["verdict"])
    r2 = N.record_attempt(ctx, "board.frame", payload, False, "still failing")
    A_(r2["verdict"] == "stuck", "同一方案第二次应 stuck，实际 %s" % r2["verdict"])
    A_(r2["variant_hash"] == r1["variant_hash"], "两次 hash 应相同")
    return "retry → stuck"


@reg("D", "D02 换一个变量后可以继续，不会立刻 stuck")
def _():
    ctx = fresh()
    N.record_attempt(ctx, "board.frame", {"cmd": "a"}, False, "no")
    N.record_attempt(ctx, "board.frame", {"cmd": "a"}, False, "no")
    r = N.record_attempt(ctx, "board.frame", {"cmd": "b", "megapixels": 0.5}, False, "no")
    A_(r["verdict"] == "retry", "换了变量应 retry，实际 %s" % r["verdict"])
    return "变了变量就重新计数"


@reg("D", "D03 L1 预算 3 次，第 4 次升级（escalate）")
def _():
    ctx = fresh()
    verdicts = [N.record_attempt(ctx, "board.frame", {"cmd": "v%d" % i}, False, "no")["verdict"]
                for i in range(1, 5)]
    A_(verdicts[:3] == ["retry"] * 3, "前三次应 retry：%s" % verdicts)
    A_(verdicts[3] == "escalate", "第四次应 escalate：%s" % verdicts)
    return "retry×3 → escalate"


@reg("D", "D04 通过时 verdict=ok，不再升级")
def _():
    ctx = fresh()
    r = N.record_attempt(ctx, "board.frame", {"cmd": "x"}, True, "fine")
    A_(r["verdict"] == "ok", "通过应 ok，实际 %s" % r["verdict"])
    return "ok"


@reg("D", "D05 L2 回流：白名单内的上游才有目标，白名单外返回 None")
def _():
    ctx = fresh()
    # 分镜图的上游是分镜 md（不是 prompt 环节）—— 拓扑修过一次，这里锁住
    A_(N.reflow_target(ctx, "board.frame") == "board.script",
        "board.frame 应能回 board.script")
    A_(N.reflow_target(ctx, "edit.release") == "edit.subtitle",
        "edit.release 应能回 edit.subtitle")
    # research.market 没有回流边
    A_(N.reflow_target(ctx, "research.market") is None,
        "research.market 不该有回流目标")
    return "白名单命中 / 未命中都正确"


# =========================================================================== E 执行
@reg("E", "E01 内置判据节点（script.gate）可直接跑通并写 marker")
def _():
    ctx = fresh()
    rc = N.main(["do", "script.gate", "--ep", "ep01", "--workspace", str(ctx.ws)])
    A_(rc == 0, "script.gate 应返回 0，实际 %d" % rc)
    mk = ctx.marker("script.gate")
    A_(mk.is_file(), "marker 没写：%s" % mk)
    rec = json.loads(mk.read_text(encoding="utf-8"))
    A_(rec.get("node") == "script.gate", "marker 内容不对")
    A_(state_of(ctx, "script.gate") == "passed", "写完 marker 应为 passed")
    return "marker + passed"


@reg("E", "E02 出片节点没有 --yes 时拒绝执行（计费闸门）")
def _():
    ctx = fresh()
    rc = N.main(["do", "video.batch", "--ep", "ep01", "--workspace", str(ctx.ws)])
    A_(rc != 0, "没有 --yes 不该返回 0")
    return "exit %d（闸门生效）" % rc


@reg("E", "E03 手写类节点：产物在=通过，产物不在=TODO（不假装能自动做）")
def _():
    ctx = fresh()
    # 夹具里 roster.json 在 → 算完成（do 的语义是「确保这个节点通过」，幂等）
    rc1 = N.main(["do", "asset.roster", "--workspace", str(ctx.ws)])
    A_(rc1 == 0, "产物已在应返回 0，实际 %d" % rc1)
    A_(state_of(ctx, "asset.roster") == "passed", "应记 passed")
    # 删掉产物 → 必须返回 TODO，而不是「判据不过」或「假装做完了」
    (ctx.ws / "04-资产" / "design" / "roster.json").unlink()
    rc2 = N.main(["do", "asset.roster", "--workspace", str(ctx.ws)])
    A_(rc2 == N.EXIT_TODO, "产物不在应返回 EXIT_TODO(6)，实际 %d" % rc2)
    return "0 / EXIT_TODO 两态都正确"


@reg("E", "E04 next 的语义：跳过所有已通过节点，指向第一个非通过项")
def _():
    ctx = fresh()
    nx = N.next_node(ctx)
    A_(nx is not None, "夹具未完成，不该返回 None")
    # 不硬编码节点名 —— 那会把「夹具内容」写死进测试。
    # 断言的是**语义**：它给的那个节点，状态必须是「非通过」，且它之前的都通过/跳过。
    idx = N.ORDER.index(nx["node"]["id"])
    for nid in N.ORDER[:idx]:
        st = state_of(ctx, nid)
        A_(st in ("passed", "skipped"), "next 跳过了未通过的 %s（%s）" % (nid, st))
    A_(state_of(ctx, nx["node"]["id"]) not in ("passed", "skipped"),
        "next 指向的 %s 其实已通过" % nx["node"]["id"])
    # 全部 skip 之后应 DONE
    for n in N.NODES:
        N.main(["skip", n["id"], "--reason", "fixture done", "--workspace", str(ctx.ws)])
    A_(N.next_node(ctx) is None, "全部跳过后 next 应返回 None")
    return "next=%s，语义正确；全跳过 → DONE" % nx["node"]["id"]


@reg("E", "E05 status --json 结构稳定（给前端/脚本吃）")
def _():
    ctx = fresh()
    ev = N.evaluate(ctx)
    for k in ("ws", "ep", "nodes", "counts"):
        A_(k in ev, "缺字段 %s" % k)
    A_(len(ev["nodes"]) == 23, "节点数不对")
    A_(sum(ev["counts"].values()) == 23, "counts 合计应 23")
    for r in ev["nodes"]:
        A_({"id", "state", "detail"} <= set(r), "节点行缺字段：%s" % r)
        A_(r["state"] in ("passed", "failed", "absent", "stale", "skipped", "blocked"),
            "非法状态 %s" % r["state"])
    return "%d 节点 / counts 自洽" % len(ev["nodes"])


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
