"""cloud/cli.py —— `python -m cloud <up|attach|status|down|probe|cost|doctor>`

命令面刻意小：云端只解决四件事 —— 建、等、停、记账。多一个命令就多一处
「以为它会帮你做决定」的误会。

    python -m cloud doctor                先自检（Token / 端点 / 守卫 / scp）
    python -m cloud attach --url <COMFY>  接管一台已在跑的服务（拓扑 A/B，最省事）
    python -m cloud up --name 盲婚        建实例 → 等就绪 → 打印可直接用的环境变量
    python -m cloud probe                 就绪三查（版本 / 节点 / 模型）
    python -m cloud down                  停实例（**停止计费**，跑完务必执行）
    python -m cloud pull --ep 01          把远端已生成的产物拉回本地（停机前）
    python -m cloud cost                  今日与累计成本

★ 所有命令都先 `hydrate_env()`：settings.json 里配的地址/受信域名会补进环境变量，
  子进程（出片脚本）才能看到同一台机器。
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from urllib.parse import urlsplit

from . import config as CFG
from . import health as HEALTH
from . import ledger as LEDGER
from .provisioner import CloudNotConfigured, CostGuard, Instance, Provisioner


def _shell_set(key: str, value: str) -> str:
    """按当前平台给一行可直接粘贴的赋值语句。"""
    if os.name == "nt":
        return "set %s=%s" % (key, value)
    return "export %s=%s" % (key, value)


def _kv(inst: Instance) -> dict:
    return {"id": inst.id, "name": inst.name, "state": inst.state,
            "http_url": inst.http_url, "ssh": "%s:%s" % (inst.ssh_host or "-", inst.ssh_port)}


def cmd_doctor(a) -> int:
    """自检：每一行都给「现在能不能用」与「不能就怎么办」。"""
    CFG.hydrate_env()
    cfg = CFG.effective()
    prob = []

    tok = CFG.token()
    prob.append(("API Token（%s）" % cfg["cloud"].get("token_env", "XGY_TOKEN"),
                 bool(tok), CFG.mask(tok) + ("" if tok else "  → 设环境变量，不要写进 settings.json")))
    eps = {k: v for k, v in (cfg["cloud"].get("endpoints") or {}).items() if str(v).strip()}
    need = ("create", "list", "stop")
    miss = [k for k in need if k not in eps]
    prob.append(("上游端点（create/list/stop）", not miss,
                 "已配 %d 个" % len(eps) if not miss else "缺 %s → 核对 API Playground 后填 settings.json"
                 % "、".join(miss)))

    hosts = cfg["comfyui"].get("trusted_hosts") or []
    if isinstance(hosts, str):
        hosts = [h.strip() for h in hosts.split(",") if h.strip()]
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "stages"))
    import _netguard as NG
    NG.reset_trusted()
    api_host = urlsplit(str(cfg["cloud"].get("api_base") or "")).hostname or ""
    api_ok = bool(api_host) and NG.would_allow(api_host)
    prob.append(("守卫放行 API 主机", api_ok,
                 api_host + ("" if api_ok else "  → 加进 comfyui.trusted_hosts 或 SOLODRAMA_TRUSTED_HOSTS")))
    inst_ok = NG.would_allow("probe-8188.container.x-gpu.com")
    prob.append(("守卫放行实例域名", inst_ok,
                 "*.container.x-gpu.com" if inst_ok else "→ comfyui.trusted_hosts 里加 *.container.x-gpu.com"))

    from . import transport as TR
    prob.append(("scp / ssh 可用", TR.has_ssh(), "用于搬制作包与成片" if TR.has_ssh() else TR.ssh_hint()))

    print("=" * 72)
    print("云端接入自检")
    print("=" * 72)
    bad = 0
    for name, ok, detail in prob:
        print("  %s %-26s %s" % ("[OK] " if ok else "[NG] ", name, detail))
        bad += 0 if ok else 1
    print("-" * 72)
    print("  ComfyUI 地址（当前有效）：%s" % cfg["comfyui"]["base_url"])
    print("  成本上限：%.1f 小时/日 ｜ 今日已用 %.2f 小时"
          % (float(cfg["cloud"].get("max_hours_per_day") or 0), LEDGER.day_hours(a.workspace)))
    print("\n%s" % ("自检通过。下一步：python -m cloud attach --url <地址> 或 python -m cloud up"
                   if not bad else "还有 %d 项要处理；纯 HTTP 拓扑（拓扑 C）可以不管 scp 那一项。" % bad))
    return 0 if not bad else 1


def cmd_attach(a) -> int:
    CFG.hydrate_env()
    cfg = CFG.effective()
    url = a.url or cfg["comfyui"]["base_url"]
    prov = Provisioner(cfg, ws=a.workspace)
    inst = prov.attach(url, name=a.name or "manual")
    print("已接管：%s（%s）" % (inst.http_url, inst.name))
    _print_next(inst)
    return 0


def cmd_up(a) -> int:
    CFG.hydrate_env()
    cfg = CFG.effective()
    prov = Provisioner(cfg, ws=a.workspace)
    try:
        inst = prov.create(a.name or "", image_id=a.image_id or "", gpu=a.gpu or "",
                           reuse=not a.force_new)
    except CostGuard as exc:
        print("[拒绝] %s" % exc)
        return 3
    except CloudNotConfigured as exc:
        print("[待配置] %s" % exc)
        print("\n  不想等端点核对：直接用 attach 接管手动启动的实例——")
        print("    python -m cloud attach --url https://<实例ID>-8188.container.x-gpu.com")
        return 4
    if not a.no_wait:
        wf = a.workflow or _default_workflow()
        ok = prov.wait_ready(inst, a.ready_min or None, workflow_path=wf)
        if not ok:
            return 5
    _print_next(inst)
    return 0


def cmd_status(a) -> int:
    CFG.hydrate_env()
    cfg = CFG.effective()
    prov = Provisioner(cfg, ws=a.workspace)
    rows = prov.state.load()
    if not rows:
        print("本地没有实例记录（%s）" % prov.state.path)
    else:
        print("=" * 72)
        print("本地记录（同一工作区的实例）")
        print("=" * 72)
        for iid, r in rows.items():
            print("  %-22s %-8s %-28s 建于 %s"
                  % (iid, r.get("state") or "?", r.get("http_url") or "-",
                     (r.get("started_at") and _ts(r.get("started_at"))) or "-"))
    url = a.url or cfg["comfyui"]["base_url"]
    res = HEALTH.probe(url, a.workflow or _default_workflow())
    print()
    print(HEALTH.render(res))
    print("\n今日已用 %.2f 小时，成本 %s"
          % (LEDGER.day_hours(a.workspace),
             ("￥%.2f" % LEDGER.day_cost(a.workspace)) if LEDGER.day_cost(a.workspace) else "未定价/0"))
    return 0 if res["ok"] else 1


def _ts(v) -> str:
    import datetime as dt
    try:
        return dt.datetime.fromtimestamp(float(v)).astimezone().strftime("%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return "-"


def cmd_down(a) -> int:
    CFG.hydrate_env()
    cfg = CFG.effective()
    prov = Provisioner(cfg, ws=a.workspace)
    rows = prov.state.load()
    targets = []
    if a.instance:
        targets = [a.instance]
    elif a.all:
        targets = [k for k, v in rows.items() if str(v.get("state") or "") != "stopped"]
    else:
        # 默认：只停「我建的、还没停」的最后一台 —— 猜错停错都能重开，但漏停会一直烧钱
        alive = [k for k, v in rows.items() if str(v.get("state") or "") != "stopped"]
        targets = alive[-1:] if alive else []
    if not targets:
        print("没有需要停的实例（本地记录为空或都已是 stopped）。")
        print("  如果控制台里确实有一台在跑，用 --instance <ID> 指定，或去控制台手动停。")
        return 0
    rc = 0
    for iid in targets:
        inst = prov.instance_from_state(iid, rows)
        try:
            prov.stop(inst, note=a.note or "CLI 停机")
        except CloudNotConfigured as exc:
            print("[待配置] %s" % exc)
            print("  → 现在就去控制台点「关机」，然后回来补记账：python -m cloud cost")
            rc = 4
        except Exception as exc:                             # noqa: BLE001
            print("[FAIL] 停 %s 失败：%s" % (iid, str(exc).splitlines()[0][:160]))
            rc = 1
    return rc


def cmd_reap(a) -> int:
    """回收「开着但很久没动」的实例 —— 忘停的自动兜底。"""
    CFG.hydrate_env()
    cfg = CFG.effective()
    prov = Provisioner(cfg, ws=a.workspace)
    idle = a.idle_min if a.idle_min is not None else float(
        cfg["cloud"].get("auto_stop_after_idle_min") or 15)
    print("空闲阈值：%.0f 分钟（settings.cloud.auto_stop_after_idle_min）%s"
          % (idle, "｜干跑，不停机" if a.dry_run else ""))
    rows = prov.reap(idle, dry=a.dry_run)
    if not rows:
        print("没有需要回收的实例。")
        return 0
    for r in rows:
        if r["action"] == "would_stop":
            print("  [将停] %-22s 已空闲 %.0f 分钟" % (r["id"], r["idle_min"]))
        elif r["action"] == "stopped":
            print("  [已停] %-22s 空闲 %.0f 分钟 → 计费停止" % (r["id"], r["idle_min"]))
        else:
            print("  [FAIL] %-22s %s" % (r["id"], r.get("error") or ""))
    return 0 if all(r["action"] != "failed" for r in rows) else 1


def cmd_probe(a) -> int:
    CFG.hydrate_env()
    cfg = CFG.effective()
    url = a.url or cfg["comfyui"]["base_url"]
    res = HEALTH.probe(url, a.workflow or _default_workflow())
    print(HEALTH.render(res, indent=""))
    if a.json:
        print(json.dumps({k: v for k, v in res.items() if k != "checked_at"},
                         ensure_ascii=False, indent=2))
    return 0 if res["ok"] else 1


def cmd_pull(a) -> int:
    """把远端已生成的产物拉回本地。

    ★ 为什么这条命令必须存在：`/history` 是**内存态**，实例重启即清空；
      output 目录随实例销毁一起没。所以「拉回」是一次性的时间窗 ——
      停机之后才想拉，往往已经来不及（只能重跑再花一次钱）。
    """
    from . import pull as PULL

    CFG.hydrate_env()
    cfg = CFG.effective()
    ws = a.workspace or os.environ.get("SOLODRAMA_WORKSPACE") or ""
    url = a.url or cfg["comfyui"]["base_url"]
    if not ws and not a.out:
        print("[FAIL] 需要 --workspace（剧目录）或 --out（只下到一个目录）")
        return 2
    res = PULL.pull(ws, ep=a.ep, url=url, out_dir=a.out, history=a.history,
                    force=a.force, dry_run=a.dry_run,
                    filename=a.file, subfolder=a.subfolder)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res.get("ok") else 1
    print(PULL.format_result(res))
    return 0 if res.get("ok") else 1


def cmd_cost(a) -> int:
    s = LEDGER.summary(a.workspace)
    if a.json:
        print(json.dumps(s, ensure_ascii=False, indent=2))
        return 0
    print("=" * 72)
    print("云端成本台账：%s" % s["path"])
    print("=" * 72)
    print("  记录条数    ：%d" % s["rows"])
    print("  累计 GPU    ：%.2f 小时" % s["hours"])
    print("  累计成本    ：%s" % (("￥%.2f" % s["cost"]) if s["cost"] else "未定价（单价待核对）"))
    print("  今日 GPU    ：%.2f 小时 ｜ %s"
          % (s["today_hours"], ("￥%.2f" % s["today_cost"]) if s["today_cost"] else "未定价"))
    if s["unpriced_rows"]:
        print("  ⚠ %d 条记录没有单价（cloud.price_per_hour=0）—— 时长是真的，金额未计"
              % s["unpriced_rows"])
    for r in LEDGER.read_all(a.workspace)[-8:]:
        print("    %s  %-10s %5.2fh  %s  %s"
              % (str(r.get("at"))[:16], str(r.get("instance"))[:10], float(r.get("hours") or 0),
                 ("￥%.2f" % float(r.get("cost") or 0)) if r.get("priced") else "  --  ",
                 str(r.get("note") or "")[:40]))
    return 0


def _default_workflow() -> str:
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    cand = root / "stages" / "video" / "comfyui" / "workflow_h3_minimax_canvas.json"
    return str(cand) if cand.is_file() else ""


def _print_next(inst: Instance) -> None:
    url = inst.http_url or ""
    print()
    print("=" * 72)
    print("下一步（复制粘贴即可）")
    print("=" * 72)
    if url:
        print("  %s" % _shell_set("COMFYUI_URL", url))
    print("  %s" % _shell_set("SOLODRAMA_TRUSTED_HOSTS", "*.container.x-gpu.com"))
    print("  python -m cloud probe        ← 就绪三查（版本 / 节点 / 模型）")
    print("  drama models set video=cloud_comfyui --comfy-url %s" % (url or "<地址>"))
    print("  drama video run --engine cloud --ep 01 --yes")
    print("  python -m cloud down         ← ★ 跑完必须停，计费按主机时长走")
    print()


def build_parser() -> argparse.ArgumentParser:
    # 公共参数用 parents 挂到每个子命令上：`--workspace` 写在子命令前后都要能识别，
    # 否则「命令写在前面」的人会吃一个 argparse 报错（这类摩擦会让人干脆不记账）。
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--workspace", default=None, help="工作区（台账与实例记录落在这里）")

    p = argparse.ArgumentParser(prog="python -m cloud", description="云端 ComfyUI 镜像编排")
    sub = p.add_subparsers(dest="cmd")

    q = sub.add_parser("doctor", parents=[common], help="自检：Token / 端点 / 守卫 / scp")
    q.set_defaults(fn=cmd_doctor)

    q = sub.add_parser("attach", parents=[common], help="接管一台已在跑的服务（不建实例）")
    q.add_argument("--url", default="", help="ComfyUI 地址（默认取 settings/环境变量）")
    q.add_argument("--name", default="manual")
    q.set_defaults(fn=cmd_attach)

    q = sub.add_parser("up", parents=[common], help="建实例 → 等就绪")
    q.add_argument("--name", default="", help="实例名（幂等键：同名在跑则复用）")
    q.add_argument("--image-id", dest="image_id", default="")
    q.add_argument("--gpu", default="")
    q.add_argument("--force-new", dest="force_new", action="store_true",
                   help="跳过同名复用（会重复计费，慎用）")
    q.add_argument("--no-wait", dest="no_wait", action="store_true")
    q.add_argument("--ready-min", dest="ready_min", type=float, default=0.0)
    q.add_argument("--workflow", default="")
    q.set_defaults(fn=cmd_up)

    q = sub.add_parser("status", parents=[common], help="状态 + 就绪三查")
    q.add_argument("--url", default="")
    q.add_argument("--workflow", default="")
    q.set_defaults(fn=cmd_status)

    q = sub.add_parser("down", parents=[common], help="停实例（停止 GPU 计费）")
    q.add_argument("--instance", default="", help="实例 ID（默认：最后一台未停的）")
    q.add_argument("--all", action="store_true", help="停掉本地记录里所有未停实例")
    q.add_argument("--note", default="")
    q.set_defaults(fn=cmd_down)

    q = sub.add_parser("reap", parents=[common], help="回收空闲实例（忘停的兜底）")
    q.add_argument("--idle-min", dest="idle_min", type=float, default=None,
                   help="空闲多少分钟算闲置（默认取 settings 的 auto_stop_after_idle_min）")
    q.add_argument("--dry-run", dest="dry_run", action="store_true", help="只列出，不停机")
    q.set_defaults(fn=cmd_reap)

    q = sub.add_parser("probe", parents=[common], help="就绪三查（可对任意地址）")
    q.add_argument("--url", default="")
    q.add_argument("--workflow", default="")
    q.add_argument("--json", action="store_true")
    q.set_defaults(fn=cmd_probe)

    q = sub.add_parser("pull", parents=[common],
                       help="把远端已生成的产物拉回本地（停机前）")
    q.add_argument("--url", default="")
    q.add_argument("--ep", default="", help="集号（ep01）；给了才能按镜号归位")
    q.add_argument("--out", default="", help="只下到这个目录（不归位）")
    q.add_argument("--history", type=int, default=200, help="扫最近多少个任务（默认 200）")
    q.add_argument("--file", default="", help="只拉这一个文件名（history 清空后的兜底）")
    q.add_argument("--subfolder", default="")
    q.add_argument("--force", action="store_true", help="已存在也覆盖")
    q.add_argument("--dry-run", action="store_true", help="只列会下什么，不写盘")
    q.add_argument("--json", action="store_true")
    q.set_defaults(fn=cmd_pull)

    q = sub.add_parser("cost", parents=[common], help="成本台账")
    q.add_argument("--json", action="store_true")
    q.set_defaults(fn=cmd_cost)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if not getattr(args, "fn", None):
        build_parser().print_help()
        return 0
    try:
        return int(args.fn(args))
    except CloudNotConfigured as exc:
        print("[待配置] %s" % exc)
        return 4
    except CostGuard as exc:
        print("[护栏] %s" % exc)
        return 3
    except KeyboardInterrupt:
        print("\n（已中断。★ 如果实例还开着：python -m cloud down）")
        return 130


__all__ = ["main", "build_parser"]
