# -*- coding: utf-8 -*-
"""capabilities.py —— 能力卡：把「已验证的通道参数」固化成数据，不再每次 probe/试跑

    python capabilities.py list
    python capabilities.py show rh.h3.multiref.v1
    python capabilities.py check                 # 离线自检（默认，<3 秒，不花钱）
    python capabilities.py check --online        # 额外做联网可达性检查

为什么要它：换一次通道就 `--probe` 一次、试跑一次、再手工 export 五个环境变量 ——
这些参数是稳定的，测一次写下来就够了。写进卡里之后，出片前只验「卡还在不在、节点还在不在」，
不验「跑一遍看看」。

检查分两级：
  离线（默认）  卡自身完整性 + 工作流文件存在 + 节点映射指向的 nodeId 在工作流里存在
                + Topaz 的 exe / 权重目录存在。全是文件系统操作，不联网。
  联网（--online）额外：ComfyUI /system_stats、RH 站点与 Key 指纹。
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]   # stages/production/scripts/x.py → 仓库根
CAP_DIR = ROOT / "configs" / "capabilities"


def _load_all() -> list:
    out = []
    for p in sorted(CAP_DIR.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8-sig"))
        except Exception as exc:                               # noqa: BLE001
            out.append({"id": p.stem, "_error": "%s: %s" % (type(exc).__name__, exc)})
            continue
        d["_file"] = str(p)
        out.append(d)
    return out


def _by_id(cid: str):
    for d in _load_all():
        if d.get("id") == cid:
            return d
    return None


# ---------------------------------------------------------------------------
def _check_comfy(cap: dict, online: bool) -> list:
    """本地 ComfyUI 通道：工作流文件 + 节点存在性（+ 在线时节点类/必需输入）。"""
    res = []
    for role, rel in (cap.get("workflows") or {}).items():
        p = ROOT / str(rel)
        res.append((bool(p.is_file()), "工作流 %s：%s" % (role, "存在" if p.is_file() else "缺失 " + str(p))))
    nodes = cap.get("nodes") or {}
    t2i = ROOT / str((cap.get("workflows") or {}).get("t2i") or "")
    if t2i.is_file():
        try:
            wf = json.loads(t2i.read_text(encoding="utf-8-sig"))
        except Exception:                                      # noqa: BLE001
            wf = {}
        miss = [k for k in ("prompt", "prefix", "seed", "aspect", "latent")
                if str(nodes.get(k)) not in wf]
        res.append((not miss, "文生图节点映射：%s" % ("齐全" if not miss else "工作流里找不到 " + "、".join(miss))))
    if not online:
        return res
    try:
        import urllib.request
        # ★ 地址不能写死 8188：连接中心/环境变量改过端口或指向云端之后，
        #   能力卡会一直报「不可达」而实际能跑 —— 卡片一旦说错就没人再看它。
        base = (os.environ.get("COMFYUI_URL") or os.environ.get("COMFY_URL")
                or "http://127.0.0.1:8188").rstrip("/")
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        raw = op.open(base + "/system_stats", timeout=4).read()
        st = json.loads(raw.decode("utf-8"))
        ver = (st.get("system") or {}).get("comfyui_version")
        res.append((True, "ComfyUI 可达（%s · %s）" % (ver, base)))
    except Exception as exc:                                   # noqa: BLE001
        res.append((False, "ComfyUI 不可达（%s）—— 出图会失败，先确认服务地址与启动状态" % type(exc).__name__))
    return res


def _rh_runtime_site() -> tuple:
    """→ (运行时站点, 来源, 被忽略的旧环境变量值)。

    必须问**引擎自己**，不能自己再算一遍：站点解析规则只该有一份实现，否则
    「卡说要 .cn、体检说运行时是 .cn、真跑却是 .ai」这种三方不一致会永远修不完。
    实现统一放在 `_site.py`（能力卡 / 体检 / 向导共用）。
    """
    try:
        from _site import runtime_site
        return runtime_site()
    except Exception as exc:                                   # noqa: BLE001
        # 不拿环境变量兜底：站点真源已经不在环境变量里，兜回它等于重新引入假一致。
        return ("", "_site 导入失败（%s）" % type(exc).__name__, "")


def _node_ready(v) -> bool:
    """节点映射是否可用：**平铺写法**（nodeId）与**分段写法**（slots）都认。

    为什么两种都要认：出片改成「分镜图 + 角色 + 场景」后，`char_ref` 从一个 nodeId
    变成一组槽位（283/284/285）。旧校验只读 `nodeId`，于是一张分段写法的卡
    会被判成「缺 char_ref」；反过来，如果只认 slots，老卡又会全红。
    两种都认，才不会出现「卡改了但校验没跟上」这种假绿/假红。
    """
    v = v or {}
    if str(v.get("nodeId") or "").strip():
        return True
    slots = v.get("slots") or []
    return bool(slots) and all(str((s or {}).get("nodeId") or "").strip() for s in slots)


def _check_rh(cap: dict, online: bool) -> list:
    res = []
    wid = str(cap.get("workflow_id") or "").strip()
    res.append((bool(wid), "workflow_id = %s" % (wid or "（空）")))
    nodes = cap.get("nodes") or {}
    # ★ 2026-11-01：要查哪些节点由**卡自己声明**，不再写死视频卡的五个键。
    #   写死的后果：新增的放大卡（只有 video_in/短边/长边）会被判「缺 prompt、缺 duration」，
    #   一张完好的卡永远红 —— 假红比假绿更浪费人，因为真的坏掉时没人再看它。
    #   ⚠ `[]` 是「显式声明不需要必填节点」，不能被 `or` 兜成默认值（空列表是 falsy）。
    if "required_nodes" in cap:
        need = tuple(cap.get("required_nodes") or ())
    else:
        need = ("prompt", "duration", "board_ref", "char_ref", "scene_ref")
    if need:
        miss = [k for k in need if not _node_ready(nodes.get(k))]
        res.append((not miss, "节点映射：%s" % ("齐全（含分镜图槽）" if not miss
                                                else "缺 " + "、".join(miss))))
    else:
        miss = [k for k in nodes if not _node_ready(nodes.get(k))]
        res.append((not miss, "节点映射：%d 项%s"
                    % (len(nodes), "" if not miss else "，缺 " + "、".join(miss))))
    slot = cap.get("slots") or {}
    if slot:
        declared = slot.get("declared") or []
        total = int(slot.get("total") or 0)
        roles = slot.get("roles") or {}
        ok_slots = total >= 1 and bool(declared)
        detail = "槽位：%d 个（声明 %d 个）" % (total, len(declared))
        if roles:
            detail += "；分段 " + "、".join("%s×%d" % (k, len(v or [])) for k, v in roles.items())
        res.append((ok_slots, detail))
        if roles and total and sum(len(v or []) for v in roles.values()) != total:
            res.append((False, "槽位分段之和 %d ≠ total %d —— 有槽位没分段，会退化成「顶灰」"
                        % (sum(len(v or []) for v in roles.values()), total)))
    site = str(cap.get("site") or "").strip()
    # ★ 2026-11-01：比的必须是「运行时真正会用的站点」，不是裸环境变量。
    #   以前拿 os.environ["RUNNINGHUB_BASE_URL"] 比，而那个值可能是**进程启动快照**：
    #   用户级变量早改成 .cn，当前终端还是 .ai，于是报「不一致」——
    #   但引擎再怎么跑也不会用那个值（真源是 configs/channels.json），
    #   这条「不一致」于是变成纯噪音，还把人往「换 Key」上引。
    runtime_site, src, ignored = _rh_runtime_site()
    if site and runtime_site:
        ok = site.rstrip("/") == runtime_site.rstrip("/")
        res.append((ok, "站点：卡=%s ｜ 运行时=%s（%s）%s"
                    % (site.rstrip("/"), runtime_site.rstrip("/"), src,
                       "" if ok else "  ← 不一致，key 可能对不上站")))
        if ignored:
            # 不判失败：它不参与任何请求，但要说出来，否则「改了变量没生效」永远查不到。
            res.append((True, "环境变量 RUNNINGHUB_BASE_URL=%s 已过期，被忽略（真源是 channels.json，"
                              "要改请用 configure.py set-site）" % ignored))
    if not online:
        return res
    key = os.environ.get("RUNNINGHUB_API_KEY") or ""
    res.append((bool(key), "API Key：%s" % ("已设置" if key else "未设置（只能走本地通道）")))
    if wid and key:
        try:
            import urllib.request
            req = urllib.request.Request(
                f"{(runtime_site or site).rstrip('/')}/openapi/v2/run/workflow/{wid}",
                data=json.dumps({"nodeInfoList": []}).encode(), method="POST",
                headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
            op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            op.open(req, timeout=8).read()
            res.append((True, "工作流接口可达"))
        except Exception as exc:                               # noqa: BLE001
            res.append((False, "工作流接口探测失败（%s）—— 可能只是参数校验，需人工确认"
                        % type(exc).__name__))
    return res


def _check_topaz(cap: dict, online: bool) -> list:
    res = []
    p = cap.get("paths") or {}
    exe = pathlib.Path(str(p.get("install_dir") or "")) / "Topaz Video AI.exe"
    alt = pathlib.Path(str(p.get("install_dir") or ""))
    ok_install = exe.is_file() or alt.is_dir()
    res.append((ok_install, "安装目录：%s" % (p.get("install_dir") or "（空）")))
    md = pathlib.Path(str(p.get("model_data_dir") or ""))
    n = len(list(md.glob("*.tz3"))) if md.is_dir() else 0
    res.append((n > 0, "权重目录：%s（%d 个 .tz3）" % (md or "（空）", n)))
    res.append((str(cap.get("model") or "") in ("iris-2",), "模型：%s（iris-3 无权重）" % cap.get("model")))
    return res


CHECKERS = {"local_comfyui": _check_comfy, "runninghub": _check_rh, "topaz": _check_topaz}


def cmd_list(a) -> int:
    caps = _load_all()
    if not caps:
        print("（%s 下没有能力卡）" % CAP_DIR)
        return 0
    print("%-26s %-14s %-14s %s" % ("id", "stage", "engine", "label"))
    for d in caps:
        print("%-26s %-14s %-14s %s" % (d.get("id"), d.get("stage"), d.get("engine"), d.get("label") or ""))
    return 0


def cmd_show(a) -> int:
    d = _by_id(a.id)
    if not d:
        print("[FAIL] 没有这张卡：%s（用 list 看全部）" % a.id)
        return 2
    print(json.dumps(d, ensure_ascii=False, indent=2))
    return 0


def cmd_check(a) -> int:
    caps = _load_all()
    if a.id:
        caps = [c for c in caps if c.get("id") == a.id]
        if not caps:
            print("[FAIL] 没有这张卡：%s" % a.id)
            return 2
    bad = 0
    for cap in caps:
        print("=" * 74)
        print("%s ｜ %s" % (cap.get("id"), cap.get("label") or ""))
        print("=" * 74)
        if cap.get("_error"):
            print("  [FAIL] 卡片解析失败：%s" % cap["_error"])
            bad += 1
            continue
        fn = CHECKERS.get(str(cap.get("engine") or ""))
        if fn is None:
            print("  [WARN] 未知 engine=%s，跳过专项检查" % cap.get("engine"))
            continue
        for ok, msg in fn(cap, a.online):
            print("  [%s] %s" % ("OK" if ok else "FAIL", msg))
            if not ok:
                bad += 1
    print()
    if bad:
        print("★ %d 项未通过 —— 该通道暂不可用（不是「跑一遍试试」，是判据没满足）" % bad)
        return 2
    print("全部通过%s" % ("（含联网检查）" if a.online else "（离线）"))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="能力卡：已验证的通道参数")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list", help="列出全部能力卡")
    p.set_defaults(fn=cmd_list)
    p = sub.add_parser("show", help="打印一张卡的完整内容")
    p.add_argument("id")
    p.set_defaults(fn=cmd_show)
    p = sub.add_parser("check", help="自检（默认离线）")
    p.add_argument("id", nargs="?", default=None)
    p.add_argument("--online", action="store_true", help="额外做联网可达性检查")
    p.set_defaults(fn=cmd_check)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                          # noqa: BLE001
        pass
    raise SystemExit(main())
