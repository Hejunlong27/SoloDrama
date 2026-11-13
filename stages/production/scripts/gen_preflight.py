#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""gen_preflight.py —— 生成能力预检：批量开跑前，一次性把「能不能出」查清楚

为什么要有这个文件
------------------
到 2026-11-05，生成能力有三条通道、两个阶段（图像 / 视频），一共六种组合：

    图像：本地 ComfyUI ｜ 云端 ComfyUI ｜ RunningHub 工作流
    视频：本地 ComfyUI ｜ 云端 ComfyUI ｜ RunningHub 工作流（含 AI 应用）

但「开跑前检查」此前是**散的**：

  * `drama assets --check`        只查本地在线 + 出图工作流，且要人记得手动跑；
  * `comfy_batch_video --submit`  **什么都不查**，直接进循环 —— 模型缺一个就每镜失败一次；
  * `drama preflight`            只看 RunningHub（Key 分级 / 引擎 doctor / --video-only 预演）；
  * `cloud probe`                只服务云端那一条，且没有接进任何批量入口。

后果不是崩，而是**批量白跑**：一集 8 镜，每镜先花几十秒上传参考图、再等 400，
40 分钟后拿到「8 项无产物」，而真正原因只是云端少一个 `.safetensors`。

本文件的定位：**批量入口开跑前的唯一判据**。输入「哪一种、哪条通道」，输出结构化结论：

    {"ok": False, "status": "missing",
     "checks": [{"id": "models", "ok": False, "detail": "缺 2 个模型文件 …"}],
     "next": "补齐后重跑同一命令"}

四项检查（缺一不可）
--------------------
1. **守卫**：这个主机名允许出网吗（云端域名若没点名，会在这里就被拦，别等到提交）；
2. **在线**：`/system_stats` 通不通；
3. **版本**：≥ 0.42.1（`convrot` 量化格式的最低要求）；
4. **节点 / 模型 / 必需输入**：工作流引用的 class_type 与 Loader 文件名是否都在。

★ 口径真源是 `cloud/health.py`：本文件只负责**选工作流、选地址、分类型**，
  判据本身不重复实现 —— 两份判据迟早会分叉，那时人会先信错的那份。

用法
----
    python gen_preflight.py --workspace <ws>                 # 图像+视频，按确认单选通道
    python gen_preflight.py --workspace <ws> --kind video --engine cloud
    python gen_preflight.py --workspace <ws> --json          # 给上层脚本/界面吃

退出码：0 全部可用 / 1 有不可用项 / 2 参数问题
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import urllib.parse

ROOT = pathlib.Path(__file__).resolve().parents[3]        # 仓库根
STAGES = ROOT / "stages"

# 默认工作流（与执行器同源：`comfy_local_video.py` 的 DEFAULT_WORKFLOW /
# `comfy_client.py` 的默认出图工作流）。换工作流仍走「确认单 detail」或环境变量。
#
# ★ 2026-11-06：视频默认值**分通道** —— 本机 canvas、云端 pika 极速版。
#   下面的字面量只是「`workflow_defaults.py` 读不到时」的兜底；正常路径走 `_default_wf()`。
DEFAULT_WF = {
    # ★ 2026-11-06：与 `comfy_client.DEFAULT_WORKFLOW` / 预配置卡同源（turbo 融合版）。
    #   旧值是 `workflow_qwen_image21.json`，与执行器不是同一张图。
    "image": STAGES / "assets" / "comfyui" / "workflow_qwen21_t2i_hq.json",
    "video": STAGES / "video" / "comfyui" / "workflow_h3_minimax_audio.json",
}
DEFAULT_WF_CLOUD = {
    "video": STAGES / "video" / "comfyui" / "workflow_h3_minimax_audio.json",
}


def default_workflow(kind: str, *, cloud: bool = False) -> pathlib.Path:
    """这一类的仓库默认工作流。视频按通道分，图像不分。

    真源是 `stages/video/comfyui/workflow_defaults.py`（执行器/界面/预检共用一份）。
    读不到就退上面的字面量 —— 预检不该因为一个 import 失败就整个跑不了。
    """
    if kind == "video":
        try:
            _add_paths()
            import workflow_defaults as _WD                       # noqa: PLC0415
            return pathlib.Path(_WD.video_path(cloud))
        except Exception:                                         # noqa: BLE001
            return pathlib.Path((DEFAULT_WF_CLOUD if cloud else DEFAULT_WF)["video"])
    return pathlib.Path(DEFAULT_WF[kind])
KIND_CN = {"image": "图像", "video": "视频"}
ENGINE_CN = {"local": "本地 ComfyUI", "cloud": "云端 ComfyUI", "rh": "RunningHub 工作流"}

STATUS_CN = {
    "ready": "可用",
    "blocked": "被守卫拦下",
    "offline": "连不上",
    "version": "版本过低",
    "missing": "缺文件",
    "config": "待配置",
    "unsupported": "不支持",
}


def _add_paths() -> None:
    for p in (ROOT, STAGES):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    # model_gate / _netguard 在各自目录，按需进入
    for p in (STAGES / "production" / "scripts", STAGES / "video" / "comfyui"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))


def plan_detail(ws, kind: str) -> dict:
    """读模型确认单里这一类的 detail（读不到就空 dict）。

    读的是**文件**而不是 import model_gate：预检要能在任何目录当脚本跑，
    且不该因为 model_gate 的 import 期副作用（stdio 加固）污染输出。
    """
    if not ws:
        return {}
    p = pathlib.Path(ws) / "model-plan.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    det = (((d.get("models") or {}).get(kind) or {}).get("detail") or {})
    return det if isinstance(det, dict) else {}


def plan_choice(ws, kind: str) -> str:
    if not ws:
        return ""
    try:
        d = json.loads((pathlib.Path(ws) / "model-plan.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return ""
    return str(((d.get("models") or {}).get(kind) or {}).get("choice") or "")


def _abs_wf(kind: str, workflow: str) -> str:
    """把「只给文件名」的工作流解析成绝对路径。

    ★ 执行器（`comfy_local_video.load_workflow`）早就这么做了，预检没做 ——
      于是 `--workflow workflow_h3_local.json` 能跑，预检却报「缺工作流文件」，
      两边对同一件事有两种答案（2026-11-05 实测抓到）。
    """
    wf = str(workflow or "").strip()
    if not wf:
        return ""
    pth = pathlib.Path(wf).expanduser()
    if pth.is_file():
        return str(pth)
    if not pth.is_absolute():
        cand = pathlib.Path(DEFAULT_WF[kind]).parent / pth.name
        if cand.is_file():
            return str(cand)
    return str(pth)


def _resolve_with(kind: str, url: str, url_via: str, workflow: str, wf_via: str, det: dict) -> dict:
    """显式参数生效时的组装：**另一个维度仍按原优先级**补齐。

    只覆盖一半（例如只给 workflow 不给 url）时，另一半不能变成空 —— 那会让预检
    「地址为空 → 判不通过」，而真实提交是有地址的。所以两边各自独立解析。
    """
    if not workflow:
        workflow = str(det.get("comfy_workflow") or "").strip()
        wf_via = "模型确认单"
        if not (workflow and pathlib.Path(workflow).expanduser().is_file()):
            workflow = os.environ.get("COMFYUI_VIDEO_WORKFLOW" if kind == "video"
                                      else "COMFYUI_WORKFLOW") or ""
            wf_via = "环境变量"
            if not (workflow and pathlib.Path(workflow).expanduser().is_file()):
                workflow, wf_via = str(DEFAULT_WF[kind]), "仓库默认"
    if not url:
        base = str(det.get("comfy_url") or "").strip()
        if base:
            url, url_via = base, "模型确认单"
        else:
            url = (os.environ.get("COMFYUI_URL") or os.environ.get("COMFY_URL") or "").strip()
            url_via = "环境变量 COMFYUI_URL"
            if not url:
                url, url_via = "http://127.0.0.1:8188", "内置默认"
    return {"url": str(url).rstrip("/"), "url_via": url_via,
            "workflow": _abs_wf(kind, workflow), "workflow_via": wf_via}


def resolve(kind: str, ws=None, *, workflow: str = "", url: str = "") -> dict:
    """这一类的**实际**地址与工作流从哪来。优先级：显式参数 > 确认单 > 环境变量 > settings > 默认。

    ★ `workflow` / `url` 是「这一次就要用这个」的覆盖（命令行 `--workflow` / `--comfy-url`）。
      不加这个口子的后果是**反方向的「核 A 跑 B」**：批量出片用 `--workflow 替代版` 提交，
      而预检仍按确认单里的默认版核 → 报「缺文件」并拦下，替代方案等于走不通
      （2026-11-05 实测踩到：workflow_h3_local.json 能跑，却被 canvas 的缺件拦死）。

    与执行期同一套口径（`model_gate.apply_env` 就是 setdefault 到环境变量）：
    预检说「打 A」，执行就一定是 A —— 否则预检全绿、真跑打错机器，比没有预检更糟。
    """
    _add_paths()
    det = plan_detail(ws, kind)
    if url:
        return _resolve_with(kind, str(url).rstrip("/"), "命令行 --comfy-url",
                             workflow, "命令行 --workflow", det)
    url = str(det.get("comfy_url") or "").strip()
    via = "模型确认单"
    if not url:
        url = (os.environ.get("COMFYUI_URL") or os.environ.get("COMFY_URL") or "").strip()
        via = "环境变量 COMFYUI_URL"
    if not url:
        try:
            from cloud import config as C          # noqa: PLC0415
            url = str((C.effective().get("comfyui") or {}).get("base_url") or "")
            via = "configs/settings.json"
        except Exception:                          # noqa: BLE001
            url, via = "", ""
    if not url:
        url, via = "http://127.0.0.1:8188", "内置默认"

    if workflow:
        return _resolve_with(kind, url, via, workflow, "命令行 --workflow", det)
    wf = str(det.get("comfy_workflow") or "").strip()
    if wf and pathlib.Path(wf).expanduser().is_file():
        wf_via = "模型确认单"
    else:
        wf = os.environ.get("COMFYUI_VIDEO_WORKFLOW" if kind == "video" else "COMFYUI_WORKFLOW") or ""
        wf_via = "环境变量"
        if not (wf and pathlib.Path(wf).expanduser().is_file()):
            # ★ 视频的仓库默认**按通道分**：本机 canvas / 云端 pika。用地址判通道，
            #   与 `_engine_of()` 同一口径 —— 否则预检核的是本机那份，真跑提交的是云端那份。
            wf, wf_via = str(default_workflow(kind, cloud=not _is_loopback(url))), "仓库默认"
    return {"url": url.rstrip("/"), "url_via": via,
            "workflow": _abs_wf(kind, wf), "workflow_via": wf_via}


def _engine_of(kind: str, ws) -> str:
    """按确认单推断通道；没确认就按地址是否本机判断（与执行期一致）。"""
    c = plan_choice(ws, kind)
    if c in ("local_comfyui", "cloud_comfyui"):
        return "local" if c == "local_comfyui" else "cloud"
    if c.startswith("runninghub"):
        return "rh"
    if c == "closed_source":
        return "closed"
    r = resolve(kind, ws)
    return "local" if _is_loopback(r["url"]) else "cloud"


def _is_loopback(url: str) -> bool:
    h = (urllib.parse.urlsplit(str(url or "")).hostname or "").strip().lower()
    return h in ("127.0.0.1", "localhost", "::1", "0.0.0.0", "")


def alternatives(kind: str, url: str, *, exclude=()) -> list:
    """同目录下**本机就能跑**的其它工作流。

    为什么值得多花一次 `/object_info`：缺模型时最有用的一句话不是「缺 3 个文件」，
    而是「你机器上这份能跑」。换工作流是秒级动作，下载 3 个模型可能是一小时。
    只在主工作流判失败时才调用，不进入正常路径。
    """
    _add_paths()
    import cloud.health as HEALTH                 # noqa: PLC0415
    V = HEALTH._load_video_mod()
    if V is None:
        return []
    try:
        oi = HEALTH._get(url, "/object_info", timeout=90, retries=1)
    except Exception:                             # noqa: BLE001
        return []
    base_dir = pathlib.Path(DEFAULT_WF[kind]).parent
    skip = {str(pathlib.Path(x).resolve()) for x in exclude if x}
    out = []
    for cand in sorted(base_dir.glob("workflow_*.json")):
        if cand.name.endswith(".map.json"):
            continue
        if str(cand.resolve()) in skip:
            continue
        try:
            wf = V.load_workflow(str(cand))
            m, _src = V.load_map(str(cand), "")
            wf = V.apply_map_patches(json.loads(json.dumps(wf)), m)
        except Exception:                         # noqa: BLE001
            continue
        miss = 0
        for nid, node in wf.items():
            if not isinstance(node, dict):
                continue
            cls = str(node.get("class_type"))
            if cls not in oi:
                miss += 1
                continue
            field = (getattr(V, "MODEL_NODES", {}) or {}).get(cls)
            if not field:
                continue
            want = (node.get("inputs") or {}).get(field)
            try:
                have = oi[cls]["input"]["required"][field][0] or []
            except (KeyError, IndexError, TypeError):
                have = []
            if want and want not in have:
                miss += 1
        if miss == 0:
            out.append({"name": cand.name, "path": str(cand)})
    return out


def _c(idn: str, label: str, ok: bool, detail: str = "") -> dict:
    return {"id": idn, "label": label, "ok": bool(ok), "detail": detail}


def check(kind: str, engine: str | None = None, ws=None, *, timeout: float = 20.0,
          workflow: str = "", url: str = "") -> dict:
    """一条通道的预检结论。**从不抛异常** —— 调用方要的是「能不能跑 + 为什么」。

    `workflow` / `url`：本次实际要用的（命令行覆盖）。核的必须是**将要提交的那一份**。
    """
    kind = "video" if str(kind).startswith("v") else "image"
    engine = engine or _engine_of(kind, ws)
    r = resolve(kind, ws, workflow=workflow, url=url)
    base = {"kind": kind, "engine": engine, "url": r["url"], "workflow": r["workflow"],
            "url_via": r["url_via"], "workflow_via": r["workflow_via"],
            "checks": [], "next": "", "status": "ready", "ok": False}

    if engine == "closed":
        return dict(base, status="unsupported", next="闭源模型走人工落盘，不经引擎提交",
                    checks=[_c("channel", "通道", False, "closed_source：人工产出后落盘")])
    if engine == "rh":
        # RH 的判据在 rh_doctor / 引擎 doctor 里（Key 分级、工作流 ID），不在这里重写。
        _add_paths()
        ok = False
        detail = "RH 通道请用 `drama preflight` 的 RH 段或 `rh_doctor --check model`"
        try:
            import rh_doctor                      # noqa: PLC0415
            fn = getattr(rh_doctor, "check_models", None) or getattr(rh_doctor, "check", None)
            if callable(fn):
                res = fn() if fn.__code__.co_argcount == 0 else fn("model")
                ok = bool(res.get("ok")) if isinstance(res, dict) else bool(res)
                detail = (res.get("detail") if isinstance(res, dict) else "") or detail
        except Exception as exc:                  # noqa: BLE001
            detail = "无法调用 rh_doctor（%s）" % type(exc).__name__
        return dict(base, ok=ok, status="ready" if ok else "config",
                    checks=[_c("rh", "RunningHub Key 与工作流", ok, detail)],
                    next="" if ok else "按 rh_doctor 的提示处理")

    # ★ 拼凑方案的常见配错：通道选了 cloud，地址却还是本机。
    #   不拦的后果是「以为在云端跑、实际吃本机 GPU」—— 账实不符里最贵的一种。
    if engine == "cloud" and _is_loopback(r["url"]):
        base["checks"].append(_c("target", "通道与地址一致", False,
                                 "通道=cloud 但地址是本机：%s（来源：%s）" % (r["url"], r["url_via"])))
        base["status"] = "config"
        base["next"] = ("确认一次云端地址：drama models set %s=cloud_comfyui --comfy-url <实例地址>"
                        % kind)
        return base

    # —— 以下是 ComfyUI 两类通道（local / cloud）——
    _add_paths()
    import _netguard as NG                        # noqa: PLC0415
    import cloud.health as HEALTH                 # noqa: PLC0415

    # ① 工作流文件
    wf_p = pathlib.Path(r["workflow"])
    base["checks"].append(_c("workflow", "工作流文件", wf_p.is_file(),
                             "%s（%s）" % (wf_p.name if wf_p.is_file() else "缺：%s" % wf_p,
                                          r["workflow_via"])))
    # ② 守卫：云端域名没点名就该在这里被拦，别等到提交才吃 RemoteForbidden
    host = (urllib.parse.urlsplit(r["url"]).hostname or "").lower()
    allowed = NG.would_allow(host)
    base["checks"].append(_c("guard", "出网守卫", allowed,
                             ("本机/内网" if _is_loopback(r["url"]) else
                              ("已点名" if allowed else
                               "未点名：设 SOLODRAMA_TRUSTED_HOSTS=*.%s"
                               % ".".join(host.split(".")[-3:])))))
    if not allowed or not wf_p.is_file():
        base["status"] = "blocked" if not allowed else "missing"
        base["next"] = ("把 %s 写进 SOLODRAMA_TRUSTED_HOSTS" % host) if not allowed \
            else "补工作流文件或改确认单的 comfy_workflow"
        return base

    # ③④⑤⑥ 在线 / 版本 / 节点模型 / 必需输入：判据全在 cloud.health.probe（不重写）
    res = HEALTH.probe(r["url"], r["workflow"], timeout=timeout)
    if res.get("error"):
        base["checks"].append(_c("online", "ComfyUI 在线", False, res["error"]))
        base["status"], base["next"] = "offline", (
            "本机：启动 ComfyUI｜云端：确认实例已开机且 8188 端口映射正确")
        return base
    base["checks"].append(_c("online", "ComfyUI 在线", True,
                             "v%s · %s · 空闲 %.1fG"
                             % (res.get("version") or "?", res.get("gpu") or "GPU?",
                                res.get("vram_free_gb") or 0)))
    base["checks"].append(_c("version", "ComfyUI 版本 ≥ %s" % HEALTH.MIN_COMFY_VERSION,
                             res.get("version_ok") is not False,
                             res.get("version") or "未知"))
    miss_n, miss_m = res.get("nodes_missing") or [], res.get("models_missing") or []
    base["checks"].append(_c("nodes", "节点类齐全", not miss_n,
                             "缺：%s" % "、".join(miss_n[:4]) if miss_n else "全部可用"))
    base["checks"].append(_c("models", "模型文件齐全", not miss_m,
                             "缺：%s" % "、".join(miss_m[:3]) if miss_m else "逐项核对通过"))
    if res.get("inputs_missing"):
        base["checks"].append(_c("inputs", "必需输入齐全", False,
                                 "；".join(res["inputs_missing"][:3])))
    if res.get("map_bad"):
        base["checks"].append(_c("map", "节点映射有效", False, "；".join(res["map_bad"][:3])))

    bad = [c for c in base["checks"] if not c["ok"]]
    base["ok"] = not bad
    if bad:
        ids = {c["id"] for c in bad}
        base["status"] = ("version" if "version" in ids else
                          "missing" if ids & {"nodes", "models", "inputs", "map", "workflow"} else
                          "offline")
        base["next"] = ("补齐缺失的模型/插件（云端见 docs/云端接入进度.md §3.2 交接清单）"
                        if base["status"] == "missing" else "按上面失败项逐条处理")
        if base["status"] == "missing":
            alts = alternatives(kind, r["url"], exclude=(r["workflow"],))
            if alts:
                base["alternatives"] = alts
                base["next"] = ("本机可用的替代工作流：%s（--workflow 指定，或改确认单）"
                                % "、".join(a["name"] for a in alts[:3]))
    return base


def render(res: dict, indent: str = "  ") -> str:
    """一行结论 + 逐项明细。CLI 与 drama preflight 共用同一套文案。"""
    head = "%s%s · %s ｜ %s" % (indent, KIND_CN[res["kind"]], res["engine"],
                               res["url"])
    lines = [head, "%s  %s：%s" % (indent, "[OK] 可用" if res["ok"] else "[NG] 不可用",
                                   STATUS_CN.get(res["status"], res["status"]))]
    for c in res["checks"]:
        if c["ok"]:
            continue                      # 只打印失败项：全绿时给一行结论就够
        lines.append("%s   - %s：%s" % (indent, c["label"], c["detail"]))
    if not res["ok"] and res.get("next"):
        lines.append("%s   下一步：%s" % (indent, res["next"]))
    return "\n".join(lines)


def run_all(ws=None, kinds=("image", "video"), engine: str | None = None) -> list:
    return [check(k, engine, ws) for k in kinds]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="生成能力预检（本地 / 云端 / RH，只读、不计费）")
    ap.add_argument("--workspace", default=None)
    ap.add_argument("--kind", choices=("image", "video", "both"), default="both")
    ap.add_argument("--engine", choices=("local", "cloud", "rh"), default=None,
                    help="不给 = 按模型确认单推断")
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--workflow", default="", help="核这一份工作流（默认按确认单 → 环境变量 → 仓库默认）")
    ap.add_argument("--url", default="", help="核这个地址（默认按确认单 → 环境变量 → settings）")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    ws = a.workspace or os.environ.get("SOLODRAMA_WORKSPACE") or os.environ.get("DRAMA_WORKSPACE")
    kinds = ("image", "video") if a.kind == "both" else (a.kind,)
    # 显式 --workflow/--url 只对**单一 kind** 有意义（两类的模型与工作流文件不同），
    # 传 both 时忽略并提示，而不是「拿视频工作流去核图像」。
    if (a.workflow or a.url) and len(kinds) > 1:
        print("[i] --workflow / --url 只在 --kind image|video 时生效（当前 both，已忽略）")
        a.workflow = a.url = ""
    rows = [check(k, a.engine, ws, timeout=a.timeout, workflow=a.workflow, url=a.url)
            for k in kinds]

    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        print("=" * 74)
        print("生成能力预检%s" % ("（工作区：%s）" % ws if ws else "（未指定工作区：只查默认地址）"))
        print("=" * 74)
        for r in rows:
            print(render(r))
            print()
        bad = [r for r in rows if not r["ok"]]
        print("-" * 74)
        print("结论：%d/%d 可用" % (len(rows) - len(bad), len(rows)))
    return 0 if all(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
