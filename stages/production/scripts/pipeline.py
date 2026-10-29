#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""pipeline.py —— 流水线模式（一次确认，跑完整部剧）

用户要的是什么（2026-10-21 明确）
--------------------------------
「开启流水线模式 → 用户确认前置条件之后，设置预算上限 → 后面的流程一趟水全部跑完，
无需用户再做任何确认。**先告诉用户预计完工时间**，然后在用户确认后，一次性完成整部剧
的制作，直至交付可以发布的 1080p 剧集和发行资料。」

所以本模块只做三件事，其余一律不管：
  1. **开工预告**（`plan`）：前置条件 7 项是否齐 → 预计完工时间 → 预计花费 → 余量。
     这是「先告诉用户」那一步，本身不花钱、不改任何产物。
  2. **无人值守推进**（`run --yes`）：按 11 环节顺序跑；`auto` 环节直接调既有脚本，
     `agent` 环节（调研/剧本/资产设计/提示词/发行物料）停下来把「作业单」打给 Agent，
     由 Agent 在同一轮里补齐后 `mark` 推进 —— 全程不再问用户。
  3. **预算熔断**：每个计费环节**之前**核对「已花 + 本环节预估」，超上限立即停（退出码 3），
     绝不「跑到一半才发现钱不够」。

为什么 agent 环节不能全自动
--------------------------
调研结论、剧本正文、资产设计、H3 提示词、封面文案**都是内容生产**，仓库里没有、也不该有
「凭空生成内容」的脚本（提示词写死等于把整部剧做成模板）。把它们标成 `agent` 不是妥协，
而是把「谁负责什么」写清楚：引擎负责**判据与门禁**，Agent 负责**内容**。

退出码
------
    0  本次推进完成（或全剧已交付）
    3  预算熔断（已花 + 预估 > 上限）
    4  停在需要 Agent 产出内容的环节（作业单已打印）
    其它  子脚本真实失败（日志里有原因）

命令
----
    python pipeline.py plan [--json]                 开工预告（免费）
    python pipeline.py run --yes [--from S4] [--to S11]   无人值守推进（★计费）
    python pipeline.py mark S3 --note "..."          登记 agent 环节完成
    python pipeline.py status [--json]               进度 + 已花/余量
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))          # stages/（为了 import _layout）

import workflow as WF                            # noqa: E402
import project_setup as PS                       # noqa: E402
import _layout as L                              # noqa: E402

EXIT_OK = 0
EXIT_BUDGET = 3          # 预算熔断（与「熔断 = 3」的既有口径一致）
EXIT_NEED_AGENT = 4      # 关卡停点：等 Agent 产出内容
STATE_NAME = "pipeline-state.json"
CNY_PER_RH = 0.0025


def _vp(ws: pathlib.Path) -> pathlib.Path:
    """引擎技术目录（不 import _ws：那会在导入期强制要求工作区）。"""
    try:
        return L.engine_root(pathlib.Path(ws))
    except Exception:                                            # noqa: BLE001
        return pathlib.Path(ws) / "video-pipeline"


def _release_dir(ws: pathlib.Path) -> pathlib.Path:
    try:
        return L.release_episode_dir(pathlib.Path(ws))
    except Exception:                                            # noqa: BLE001
        return pathlib.Path(ws) / "09-发行" / "剧集"


# ---------------------------------------------------------------------------
def _now() -> _dt.datetime:
    return _dt.datetime.now().astimezone().replace(microsecond=0)


def _iso(t: _dt.datetime = None) -> str:
    return (t or _now()).isoformat()


# ---------------------------------------------------------------------------
# 花费核对（只作闸门；真实消耗以平台 usage 为准）
# ---------------------------------------------------------------------------
def spent_coins(ws: pathlib.Path) -> dict:
    """从引擎台账累加已花 RH币。

    口径：`<video-pipeline>/ledger/runs/*.json` 的 `attempts[].usage.consumeCoins`。
    失败任务不计费（平台口径），所以只累加 SUCCESS。
    ★ 若某些用量未入台账（例如工作流侧直连），本值会偏低 —— 因此它只用于**熔断闸门**，
      不作为成本报表（报表请用 `drama.py cost`）。
    """
    ws = pathlib.Path(ws)
    vp = _vp(ws)
    total, files, bad = 0.0, 0, 0
    lr = vp / "ledger" / "runs"
    if lr.is_dir():
        for f in lr.glob("*.json"):
            files += 1
            try:
                d = json.loads(f.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError, ValueError):
                bad += 1
                continue
            for a in d.get("attempts") or []:
                if str(a.get("status") or "").upper() != "SUCCESS":
                    continue
                u = a.get("usage") or {}
                try:
                    total += float(u.get("consumeCoins") or 0)
                except (TypeError, ValueError):
                    pass
    return {"coins": round(total, 1), "ledger_files": files, "bad_files": bad,
            "source": str(lr), "note": "只累加 SUCCESS；失败任务平台不计费"}


# ---------------------------------------------------------------------------
# 进度与预估
# ---------------------------------------------------------------------------
def _state_path(ws: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(ws) / STATE_NAME


def load_state(ws: pathlib.Path) -> dict:
    p = _state_path(ws)
    if p.is_file():
        try:
            d = json.loads(p.read_text(encoding="utf-8-sig"))
            if isinstance(d, dict):
                d.setdefault("runs", [])
                return d
        except (OSError, json.JSONDecodeError, ValueError):
            pass
    return {"runs": []}


def save_state(ws: pathlib.Path, d: dict) -> pathlib.Path:
    p = _state_path(ws)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8", newline="")
    return p


def forecast(ws: pathlib.Path) -> dict:
    """开工预告：前置条件 + 环节分工 + 预计耗时 + 预计花费 + 余量。"""
    ws = pathlib.Path(ws)
    setup = PS.collect(ws)
    ev = WF.evaluate(ws)
    sp = spent_coins(ws)

    dv = setup["derived"]
    est_total = dv.get("est_total_coins")
    cap = (setup["items"]["pipeline"] or {}).get("budget_cap_coins")
    remaining = [r for r in ev["stages"] if not r["done"]]
    agent_steps = [r["id"] + " " + r["name"] for r in remaining if r["kind"] == "agent"]
    auto_steps = [r["id"] + " " + r["name"] for r in remaining if r["kind"] == "auto"]

    # 剩余工期的粗略折算：自动环节按集数线性，内容环节按经验值（每环节 20–40 分钟由 Agent 完成）
    eps = int(setup["items"]["episodes"].get("count") or 0)
    minutes_video = 11.0 * eps
    minutes_post = 4.0 * eps
    minutes_assets = 6.0 if any(r["id"] == "S4" for r in remaining) else 0.0
    minutes_agent = 30.0 * len([r for r in remaining if r["kind"] == "agent"])
    total_minutes = (minutes_video * (1 if any(r["id"] == "S6" for r in remaining) else 0)
                     + minutes_post * (1 if any(r["id"] in ("S8", "S9", "S10", "S11") for r in remaining) else 0)
                     + minutes_assets + minutes_agent)
    eta = _now() + _dt.timedelta(minutes=total_minutes) if total_minutes else None

    return {
        "setup_ok": setup["ok"],
        "setup_missing": setup["missing"],
        "pipeline_enabled": (setup["items"]["pipeline"] or {}).get("enabled"),
        "budget_cap_coins": cap,
        "budget_cap_cny": (setup["items"]["pipeline"] or {}).get("budget_cap_cny"),
        "spent_coins": sp["coins"],
        "spent_source": sp["source"],
        "est_total_coins": est_total,
        "est_total_cny": dv.get("est_cny"),
        "est_remaining_coins": max(0, (est_total or 0) - sp["coins"]) if est_total else None,
        "budget_headroom_coins": (cap - sp["coins"]) if cap else None,
        "episodes": eps,
        "shots": ev["ctx"]["shots"],
        "workflow_ref": (setup["items"]["workflow_api"] or {}).get("ref"),
        "workflow_site": (setup["items"]["workflow_api"] or {}).get("site"),
        "account_alias": (setup["items"]["account"] or {}).get("alias"),
        "account_fingerprint": (setup["items"]["account"] or {}).get("fingerprint"),
        "coins_per_shot": dv.get("coins_per_shot"),
        "eta_minutes": round(total_minutes) or None,
        "machine_minutes": round(minutes_video + minutes_post + minutes_assets) or None,
        "agent_minutes": round(minutes_agent) or None,
        "eta_at": _iso(eta) if eta else None,
        "current": ev["current"],
        "agent_steps": agent_steps,
        "auto_steps": auto_steps,
        "complete": ev["complete"],
    }


def render_plan(f: dict, ws: pathlib.Path) -> str:
    L = ["=" * 74, "流水线开工预告（这一步不花钱、不改产物）", "=" * 74]
    ok = f["setup_ok"]
    L.append("前置条件    : %s" % ("7/7 已确认" if ok else
                                   "未齐 —— 缺 %s" % "、".join(PS.ITEM_LABELS[k] for k in f["setup_missing"])))
    if not ok:
        L.append("             先补：%s" % PS.FIX_HINTS.get(f["setup_missing"][0], ""))
    pipe = f["pipeline_enabled"]
    L.append("流水线模式  : %s" % ("开（确认后不再逐步问）" if pipe else
                                   ("关（逐环节确认）" if pipe is False else "未确认")))
    L.append("规模        : %s 集 × 约 %s 镜/集" % (f["episodes"] or "?", f["shots"] or "?"))
    L.append("工作流 API  : %s%s" % (f.get("workflow_ref") or "无需",
                                    "（%s）" % f["workflow_site"] if f.get("workflow_site") else ""))
    L.append("账号        : %s%s" % (f.get("account_alias") or "无需",
                                    "（%s）" % f["account_fingerprint"]
                                    if f.get("account_fingerprint") else ""))
    L.append("-" * 74)
    L.append("剩余环节    : 自动 %d 个 %s" % (len(f["auto_steps"]),
                                             "、".join(s.split()[0] for s in f["auto_steps"]) or "—"))
    L.append("              内容 %d 个 %s" % (len(f["agent_steps"]),
                                             "、".join(s.split()[0] for s in f["agent_steps"]) or "—"))
    L.append("              （内容环节由 Agent 产出，不需要你逐环节确认）")
    L.append("-" * 74)
    if f["eta_at"]:
        L.append("预计完工    : %s（约 %.1f 小时 = 机时 %.1f 小时 + 内容制作 %.1f 小时）"
                 % (f["eta_at"].replace("T", " ")[:16], f["eta_minutes"] / 60.0,
                    (f["machine_minutes"] or 0) / 60.0, (f["agent_minutes"] or 0) / 60.0))
    else:
        L.append("预计完工    : 已全部完成或规模未确认")
    if f["est_total_coins"]:
        L.append("预计花费    : %s RH币 ≈ ￥%s（单段 %s 币 × %s 集）"
                 % (f["est_total_coins"], f["est_total_cny"], f["coins_per_shot"], f["episodes"]))
    L.append("已花        : %s RH币（台账口径：%s）" % (f["spent_coins"], f["spent_source"]))
    if f["budget_cap_coins"]:
        L.append("预算上限    : %s RH币 ≈ ￥%s（余量 %s 币）"
                 % (f["budget_cap_coins"], f["budget_cap_cny"], f["budget_headroom_coins"]))
        over = (f["est_remaining_coins"] or 0) > (f["budget_headroom_coins"] or 0)
        L.append("风险        : %s" % ("★ 预计花费 > 余量，建议提高上限或缩小范围"
                                       if over else "预计花费在余量内"))
    else:
        L.append("预算上限    : 未设置（流水线模式必须设：--budget-coins）")
    L.append("=" * 74)
    if ok and f["pipeline_enabled"] and f["budget_cap_coins"]:
        L.append("确认无误后一次跑到底：")
        L.append("  python stages/production/scripts/pipeline.py --workspace \"%s\" run --yes" % ws)
    else:
        L.append("还差条件，先补齐 setup（drama.py setup show 看缺什么）")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# 自动环节的执行器
# ---------------------------------------------------------------------------
def _py() -> str:
    return sys.executable


def _run(cmd: list, ws: pathlib.Path) -> tuple:
    print("  $ %s" % " ".join(str(c) for c in cmd[1:]))
    p = subprocess.run([str(c) for c in cmd], cwd=str(ws), text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode


def _episode_list(ws: pathlib.Path, setup: dict) -> list:
    n = int((setup["items"]["episodes"] or {}).get("count") or 0)
    if n:
        return ["ep%02d" % i for i in range(1, n + 1)]
    eps = sorted(p.stem for p in (WF._stage_dir(ws, "script")).glob("ep_*.md"))  # noqa: SLF001
    return eps


def _exec_assets(ws: pathlib.Path, setup: dict) -> int:
    engine = (setup["items"]["image_model"] or {}).get("engine_arg") or "local"
    return _run([_py(), str(HERE / "drama.py"), "--workspace", str(ws),
                 "assets", "--engine", engine, "--submit"], ws)


def _exec_video(ws: pathlib.Path, setup: dict) -> int:
    vo = setup["items"]["video_options"] or {}
    conc = int(vo.get("concurrency") or 2)
    # 先小样（1 段）再全量：小样失败时不会把 30 集的钱一次打光
    rc = _run([_py(), str(HERE / "drama.py"), "--workspace", str(ws),
               "video", "run", "--yes", "--limit", "1", "--concurrency", str(conc)], ws)
    if rc:
        print("  [STOP] 小样失败（退出码 %s），不进入全量 —— 先按日志排障" % rc)
        return rc
    return _run([_py(), str(HERE / "drama.py"), "--workspace", str(ws),
                 "video", "run", "--yes", "--concurrency", str(conc)], ws)


def _exec_post(ws: pathlib.Path, setup: dict, stage: str) -> int:
    sub = HERE.parents[1] / "subtitle" / "scripts" / "subtitle.py"
    if not sub.is_file():
        print("  [FAIL] 找不到字幕/拼接脚本：%s" % sub)
        return 2
    stage_map = {"S8": "master", "S9": "upscale", "S10": "ass"}
    st = stage_map[stage]
    rc_all = 0
    for ep in _episode_list(ws, setup):
        rc = _run([_py(), str(sub), "--workspace", str(ws), "--ep", ep, "--stage", st], ws)
        if rc:
            rc_all = rc
            print("  [WARN] %s %s 失败（退出码 %s），继续下一集" % (ep, st, rc))
    if stage == "S10" and rc_all == 0:
        for ep in _episode_list(ws, setup):
            rc = _run([_py(), str(sub), "--workspace", str(ws), "--ep", ep, "--stage", "render"], ws)
            if rc:
                rc_all = rc
                print("  [WARN] %s render 失败（退出码 %s）" % (ep, rc))
    return rc_all


def _exec_release_materials(ws: pathlib.Path, setup: dict) -> int:
    """S7 发行物料：机器只能做门禁与提醒，物料本身由 Agent 产出。"""
    rc = _run([_py(), str(HERE / "release_check.py"), "--workspace", str(ws),
               "--material-only"], ws)
    return rc


def _exec_finalize(ws: pathlib.Path, setup: dict) -> int:
    """S11 收尾：**先画面体检，再导出，最后物料验收**。

    ★ 2026-10-30：体检必须在导出【之前】。此前是「先 `release_export` 再 `release_check`」，
      而 `release_export` 只校验命名；于是「SAR 59:60 的硬凑版」和「无字幕放大母版」
      都能先落进 `09-发行/剧集/`，等平台驳回再回滚 —— 发行目录里的文件一旦被上传就收不回来。
      现在 `compliance_media_check --from-source` 查的是**待发布的 `_subbed` 成片**，
      不合格直接返回 2，一个字节都不会写进发行目录。
      `--sheet` 顺手把 12 帧拼图落到 `08-合规/抽帧/`，C4 品牌项的人审成本压到 3 秒/集。
    """
    gate = HERE / "compliance_media_check.py"
    if gate.is_file():
        rc = _run([_py(), str(gate), "--workspace", str(ws), "--all", "--from-source", "--sheet"], ws)
        if rc:
            print("  [BLOCK] 画面侧门禁未通过（规格/黑边/字幕），已中止导出。")
            print("          修法见上；确认只是预览可手工跑 release_export.py --no-media-check")
            return rc
    else:
        print("  [WARN] 未找到 compliance_media_check.py，画面侧门禁跳过")

    rc = _run([_py(), str(HERE / "release_export.py"), "--workspace", str(ws),
               "--all", "--apply"], ws)
    if rc:
        return rc
    return _run([_py(), str(HERE / "release_check.py"), "--workspace", str(ws)], ws)


EXECUTORS = {
    "S4": _exec_assets,
    "S6": _exec_video,
    "S11": _exec_finalize,
}
POST_STAGES = ("S8", "S9", "S10")


# ---------------------------------------------------------------------------
# 作业单（agent 环节）
# ---------------------------------------------------------------------------
def render_agent_brief(st: dict) -> str:
    L = ["=" * 74, "【流水线停点】%s %s —— 需要产出内容（不问你，问 Agent）"
         % (st["id"], st["name"]), "=" * 74]
    L.append("要做什么：%s" % st["what"])
    L.append("硬约束  ：%s" % st["note"])
    L.append("")
    L.append("产物判据（全部满足才算完成）：")
    for p in st["probes"]:
        L.append("  - %-16s 需要 ≥%d（当前 %d）  %s"
                 % (p["label"], p["need"], p["found"], p["dir"]))
    L.append("")
    if st["commands"]:
        L.append("标准命令 / 参考：")
        for c in st["commands"]:
            L.append("  %s" % c)
    L.append("")
    L.append("完成后推进：")
    L.append("  python pipeline.py --workspace <ws> mark %s --note \"一句话说明\"" % st["id"])
    L.append("=" * 74)
    return "\n".join(L)


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------
def cmd_run(a) -> int:
    ws = _resolve_ws(a.workspace)
    if not a.yes:
        f = forecast(ws)
        print(render_plan(f, ws))
        print("\n[闸门] 这是真实执行（含计费环节）。确认无误后加 --yes 重跑。")
        return 2

    # 硬前置：7 项 + 流水线开启 + 预算上限
    ok, msg = PS.require(ws)
    if not ok:
        print("[BLOCK] 前置条件未齐，不许开工（退出码 %d）：\n%s" % (PS.EXIT_WAIT_CONFIRM, msg))
        return PS.EXIT_WAIT_CONFIRM
    setup = PS.collect(ws)
    pipe = setup["items"]["pipeline"] or {}
    if not pipe.get("enabled"):
        print("[BLOCK] 未开启流水线模式（setup set --pipeline on）。"
              "逐环节执行请直接用 drama.py 各命令。")
        return PS.EXIT_WAIT_CONFIRM
    cap = pipe.get("budget_cap_coins")
    if not cap:
        print("[BLOCK] 流水线模式必须设预算上限（setup set --budget-coins N）")
        return EXIT_BUDGET

    state = load_state(ws)
    started = _iso()
    start_id = a.__dict__.get("from_stage") or None
    end_id = a.__dict__.get("to_stage") or "S11"
    print("=" * 74)
    print("流水线模式启动：%s → %s" % (start_id or "当前位置", end_id))
    print("预算上限 %s RH币 ≈ ￥%s；已花 %s RH币"
          % (cap, pipe.get("budget_cap_cny"), spent_coins(ws)["coins"]))
    print("=" * 74)

    started_any = False
    for st in WF.STAGES:
        sid = st["id"]
        if start_id and WF.STAGE_IDS.index(sid) < WF.STAGE_IDS.index(start_id):
            continue
        if WF.STAGE_IDS.index(sid) > WF.STAGE_IDS.index(end_id):
            break
        # 逐环节重算（上一个环节刚产出，判据可能已满足）
        ev = WF.evaluate(ws)
        row = next(r for r in ev["stages"] if r["id"] == sid)
        if row["done"]:
            print("\n[skip] %s %s 已完成" % (sid, st["name"]))
            continue

        if st["kind"] != "auto":
            print("\n" + render_agent_brief(row))
            print("[停点] 已推进到 %s；Agent 补齐后 mark 即可继续。" % sid)
            state["runs"].append({"at": started, "stage": sid, "result": "need_agent",
                                  "ended": _iso()})
            save_state(ws, state)
            return EXIT_NEED_AGENT

        # 账号一致性闸门（★ 2026-10-21）：流水线一跑几小时，中途被人换了 Key
        #   就会「前半段算 A 账号、后半段算 B 账号」。每个计费环节前比对指纹，不一致立刻停。
        if st.get("billing") or sid in ("S4", "S6", "S7", "S11"):
            _acct = PS.collect(ws)["items"].get("account") or {}
            if _acct.get("required") and not _acct.get("ok"):
                print("\n[BLOCK] 账号 API Key 校验未过（退出码 %d）：%s"
                      % (EXIT_NEED_AGENT, "；".join(str(x) for x in _acct.get("missing") or [])))
                print("        重新确认：drama.py setup set --account \"<别名>\"")
                state["runs"].append({"at": started, "stage": sid,
                                      "result": "account_mismatch", "ended": _iso()})
                save_state(ws, state)
                return EXIT_NEED_AGENT

        # 预算闸门（计费环节前）
        sp = spent_coins(ws)["coins"]
        if sp >= cap:
            print("\n[BUDGET] 已花 %.1f RH币 ≥ 上限 %s，停止（退出码 %d）。"
                  % (sp, cap, EXIT_BUDGET))
            state["runs"].append({"at": started, "stage": sid, "result": "budget_stop",
                                  "spent": sp, "cap": cap, "ended": _iso()})
            save_state(ws, state)
            return EXIT_BUDGET

        print("\n[run ] %s %s（%s）" % (sid, st["name"], st["what"]))
        started_any = True
        if sid in EXECUTORS:
            rc = EXECUTORS[sid](ws, setup)
        elif sid in POST_STAGES:
            rc = _exec_post(ws, setup, sid)
        elif sid == "S7":
            rc = _exec_release_materials(ws, setup)
        else:
            print("  [FAIL] 没有执行器：%s" % sid)
            rc = 2

        # 执行后复核判据
        row2 = next(r for r in WF.evaluate(ws)["stages"] if r["id"] == sid)
        state["runs"].append({"at": started, "stage": sid, "rc": rc,
                              "done_after": row2["done"], "ended": _iso()})
        save_state(ws, state)
        if rc:
            print("\n[STOP] %s 退出码 %s；修好后 `run --from %s` 续跑（已完成的会跳过）"
                  % (sid, rc, sid))
            return rc
        if not row2["done"]:
            print("\n[STOP] %s 跑完但产物判据未满足：%s"
                  % (sid, "、".join("%s %d/%d" % (p["label"], p["found"], p["need"])
                                    for p in row2["probes"] if not p["ok"])))
            return 2

    ev = WF.evaluate(ws)
    print("\n" + WF.render_status(ev))
    if ev["complete"]:
        rel = _release_dir(ws)
        print("\n[完成] 发布版剧集：%s" % rel)
        for f in sorted(rel.glob("Episode*.mp4"))[:5]:
            print("  %s" % f.name)
    else:
        print("\n[提示] 还有环节未完成（可选环节见上），继续：pipeline.py run --yes")
    save_state(ws, state)
    return EXIT_OK if ev["complete"] or started_any else EXIT_OK


def cmd_plan(a) -> int:
    ws = _resolve_ws(a.workspace)
    f = forecast(ws)
    if a.json:
        print(json.dumps(f, ensure_ascii=False, indent=2))
    else:
        print(render_plan(f, ws))
    return 0


def cmd_status(a) -> int:
    ws = _resolve_ws(a.workspace)
    f = forecast(ws)
    ev = WF.evaluate(ws)
    if a.json:
        print(json.dumps({"forecast": f, "workflow": ev}, ensure_ascii=False, indent=2))
        return 0
    print(WF.render_status(ev))
    print("已花        : %s RH币 / 上限 %s" % (f["spent_coins"], f["budget_cap_coins"] or "未设"))
    if f["eta_at"]:
        print("预计完工    : %s" % f["eta_at"].replace("T", " ")[:16])
    return 0


def cmd_mark(a) -> int:
    ws = _resolve_ws(a.workspace)
    ns = argparse.Namespace(workspace=str(ws), stage=a.stage, note=a.note)
    return WF.cmd_done(ns)


def _resolve_ws(explicit) -> pathlib.Path:
    if explicit:
        p = pathlib.Path(explicit).expanduser()
        if p.is_dir():
            return p.resolve()
    import os
    env = os.environ.get("SOLODRAMA_WORKSPACE") or os.environ.get("DRAMA_WORKSPACE")
    if env:
        p = pathlib.Path(env).expanduser()
        if p.is_dir():
            return p.resolve()
    sys.exit("[FAIL] 找不到短剧工作区：给 --workspace 或设 SOLODRAMA_WORKSPACE")


def main() -> int:
    ap = argparse.ArgumentParser(description="流水线模式（一次确认，跑完整部剧）")
    ap.add_argument("--workspace", default=None)
    sub = ap.add_subparsers(dest="cmd")

    for name in ("plan", "status"):
        q = sub.add_parser(name)
        q.add_argument("--workspace", default=argparse.SUPPRESS)
        q.add_argument("--json", action="store_true")

    q = sub.add_parser("run")
    q.add_argument("--workspace", default=argparse.SUPPRESS)
    q.add_argument("--yes", action="store_true", help="确认执行（含 ★计费 环节）")
    q.add_argument("--from", dest="from_stage", default=None, choices=WF.STAGE_IDS)
    q.add_argument("--to", dest="to_stage", default=None, choices=WF.STAGE_IDS)

    q = sub.add_parser("mark")
    q.add_argument("--workspace", default=argparse.SUPPRESS)
    q.add_argument("stage", choices=WF.STAGE_IDS)
    q.add_argument("--note", default=None)

    a = ap.parse_args()
    fn = {"plan": cmd_plan, "status": cmd_status, "run": cmd_run, "mark": cmd_mark}.get(a.cmd)
    if not fn:
        print(render_plan(forecast(_resolve_ws(a.workspace)), _resolve_ws(a.workspace)))
        return 0
    return fn(a)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已中断。流水线支持 --from <环节> 续跑；出片请用 drama.py video run --resume。")
        sys.exit(130)
