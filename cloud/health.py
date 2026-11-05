"""cloud/health.py —— 云端 ComfyUI 的「就绪三查」：版本 / 节点 / 模型

为什么云端比本机更需要这一层
----------------------------
本机缺模型，你能立刻想起来「昨天删过」；云端缺模型，症状是提交即 400，
而 ComfyUI 的报错只说 `node type missing` —— 看起来像节点没装，其实是**文件名差一个字符**。
镜像里的模型是别人下载后打进包的，`convrot` / `int8` / `pruned` 这些后缀最容易漏。

所以判据必须是**三查齐全**，并且把「缺什么」点名到文件：

| 检查 | 接口 | 判据 |
|---|---|---|
| 版本 | `GET /system_stats` | ComfyUI ≥ 0.42.1（`convrot` 量化格式的最低要求） |
| 节点 | `GET /object_info` | 工作流引用的 class_type 全部存在 |
| 模型 | 同上，读 Loader 的 `enum` | 工作流里写死的文件名在枚举内 |

额外送一项**必需输入**（复用本机 `check()` 的口径）：节点类与模型都齐，但连线缺了口，
一样是提交即 400。换别人导出的工作流时这是最高频的坑。

为什么不复用 `comfy_local_video.check()` 直接打印
------------------------------------------------
`check()` 的职责是「给人看 + 返回码」，它把 `COMFY` 固定在导入期。而 `wait_ready()` 需要
**结构化结果**（要判断「再等一轮」还是「判失败」），且必须能对任意 base_url 探活。
所以这里复用它的**纯函数**（工作流/映射/修补），自己出结论。
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time

# 版本下限：`convrot` 量化格式从 0.42.1 起支持。低版本加载该格式会直接失败。
MIN_COMFY_VERSION = "0.42.1"


def _ver_tuple(v: str) -> tuple:
    out = []
    for part in str(v or "").replace("-", ".").split("."):
        num = "".join(ch for ch in part if ch.isdigit())
        if num == "":
            break
        out.append(int(num))
    return tuple(out)


def _load_video_mod():
    """按路径加载 `comfy_local_video`（复用它的工作流/映射纯函数）。"""
    here = pathlib.Path(__file__).resolve().parent
    cand = here.parent / "stages" / "video" / "comfyui" / "comfy_local_video.py"
    if not cand.is_file():
        return None
    for p in (cand.parent, cand.parent.parent.parent):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    try:
        import importlib.util as ilu
        spec = ilu.spec_from_file_location("comfy_local_video", cand)
        mod = ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)          # type: ignore[union-attr]
        return mod
    except Exception:                         # noqa: BLE001 —— 体检不该因导入失败而崩
        return None


def _get(base: str, path: str, *, timeout: float = 60, retries: int = 2):
    """对**指定** base_url 发 GET（不读 COMFYUI_URL，便于一次探多台）。"""
    here = pathlib.Path(__file__).resolve().parent
    if str(here.parent / "stages") not in sys.path:
        sys.path.insert(0, str(here.parent / "stages"))
    import _comfy_http as Q
    raw = Q.request(base.rstrip("/") + path, timeout=timeout, retries=retries, tag=path)
    return json.loads(raw.decode("utf-8")) if raw else {}


def probe(base_url: str, workflow_path: str = "", map_path: str = None, *,
          timeout: float = 60) -> dict:
    """就绪三查。**从不抛异常** —— 调用方（`wait_ready` / CLI）需要的是结论，不是栈。

    返回：
        {ok, version, version_ok, gpu, vram_free_gb,
         nodes_missing[], models_missing[], inputs_missing[], map_bad[],
         error, base_url, checked_at}
    """
    res = {"ok": False, "version": "", "version_ok": None, "gpu": "", "vram_free_gb": 0.0,
           "nodes_missing": [], "models_missing": [], "inputs_missing": [], "map_bad": [],
           "error": "", "base_url": base_url, "checked_at": time.time()}
    base = (base_url or "").rstrip("/")

    # —— ① 版本与 GPU ——
    try:
        st = _get(base, "/system_stats", timeout=min(timeout, 20), retries=1)
    except Exception as exc:                                  # noqa: BLE001
        res["error"] = "%s: %s" % (type(exc).__name__, str(exc).splitlines()[0][:200])
        return res
    sysinfo = st.get("system") or {}
    dev = (st.get("devices") or [{}])[0]
    res["version"] = str(sysinfo.get("comfyui_version") or "")
    res["gpu"] = str(dev.get("name") or "")
    try:
        res["vram_free_gb"] = round(float(dev.get("vram_free") or 0) / (1024 ** 3), 1)
    except (TypeError, ValueError):
        pass
    vt, mt = _ver_tuple(res["version"]), _ver_tuple(MIN_COMFY_VERSION)
    # 版本读不出来（部分镜像裁剪了 build 信息）时给 None = 「未验证」，不判失败。
    res["version_ok"] = None if not vt else (vt >= mt)

    # —— ②③ 节点与模型（一次 /object_info 全拿，比逐类查快一个数量级）——
    try:
        oi = _get(base, "/object_info", timeout=timeout, retries=1)
    except Exception as exc:                                  # noqa: BLE001
        res["error"] = "读 /object_info 失败：%s" % str(exc).splitlines()[0][:200]
        return res

    V = _load_video_mod()
    if V is None or not workflow_path:
        # 没有工作流就给「服务级」结论：版本 + GPU 可用即视为通了。
        # 这不是放水 —— 不指定工作流时确实无从判断节点/模型。
        res["ok"] = bool(res["version_ok"] is not False)
        return res

    try:
        wf = V.load_workflow(workflow_path)
        m, _src = V.load_map(workflow_path, map_path or "")
        wf = V.apply_map_patches(json.loads(json.dumps(wf)), m)
    except Exception as exc:                                  # noqa: BLE001
        res["error"] = "读工作流失败：%s: %s" % (type(exc).__name__, str(exc)[:200])
        return res

    classes = {str(v.get("class_type")) for v in wf.values() if isinstance(v, dict)}
    res["nodes_missing"] = sorted(c for c in classes if c and c not in oi)

    # 模型：Loader 节点的文件名必须出现在该节点的 enum 里
    for nid, node in (wf or {}).items():
        if not isinstance(node, dict):
            continue
        cls = node.get("class_type")
        field = (V.MODEL_NODES or {}).get(cls)
        if not field:
            continue
        want = (node.get("inputs") or {}).get(field)
        if not want:
            continue
        try:
            have = oi[cls]["input"]["required"][field][0]
        except (KeyError, IndexError, TypeError):
            have = []
        if want not in have:
            res["models_missing"].append("#%s %s = %s" % (nid, cls, want))

    # 必需输入（连线缺口的提前判据）
    if getattr(V, "missing_required_inputs", None):
        try:
            for nid, cls, fields in V.missing_required_inputs(wf, oi):
                res["inputs_missing"].append("#%s %s 缺 %s" % (nid, cls, "、".join(fields)))
        except Exception:                                     # noqa: BLE001
            pass

    # 映射指向不存在的节点（映射写错是另一种 400）
    # ★ 只在**确实有映射文件**时校验：`load_map()` 找不到 sidecar 会回落到视频侧的内置默认，
    #   拿它去校验图像工作流必然「images -> #24 不存在」—— 那是假阳性，会把可用判成不可用。
    sidecar = ""
    try:
        sidecar = V.sidecar_for(workflow_path) or ""
    except Exception:                                         # noqa: BLE001
        sidecar = ""
    res["map_checked"] = bool(map_path) or bool(sidecar and os.path.isfile(sidecar))
    if not res["map_checked"]:
        # 没有映射文件 → 跳过映射校验，但保留「用内置默认」这一事实
        res["ok"] = (not res["nodes_missing"] and not res["models_missing"]
                     and not res["inputs_missing"] and res["version_ok"] is not False)
        return res

    # ★ 只报「用户真写了、但节点不存在」的项。
    keys = getattr(V, "MAP_KEYS", None) or tuple((getattr(V, "MAP_ROLES", {}) or {}).keys())
    try:
        inherited = V._builtin_map() or {}
    except Exception:                                         # noqa: BLE001
        inherited = {}
    for role in keys:
        raw = m.get(role)
        for nid in (raw if isinstance(raw, list) else [raw]):
            sid = str(nid or "").strip()
            if not sid or sid in wf:
                continue
            if sid == str(inherited.get(role) or ""):
                continue          # 继承来的默认值，不是用户写错
            res["map_bad"].append("%s -> #%s" % (role, nid))

    res["ok"] = (not res["nodes_missing"] and not res["models_missing"]
                 and not res["inputs_missing"] and not res["map_bad"]
                 and res["version_ok"] is not False)
    return res


def render(res: dict, indent: str = "  ") -> str:
    """把 probe 结果渲染成能直接贴进对话的几行（CLI 与 wait_ready 共用）。"""
    lines = []
    head = "%sComfyUI %s" % (indent, res.get("base_url") or "")
    ver = res.get("version") or "未知"
    tag = {True: "OK", False: "低于 %s" % MIN_COMFY_VERSION, None: "未验证"}[res.get("version_ok")]
    lines.append("%s：v%s（%s）· %s · 空闲 %.1fG"
                 % (head, ver, tag, res.get("gpu") or "GPU 未知", res.get("vram_free_gb") or 0))
    if res.get("error"):
        lines.append("%s[FAIL] %s" % (indent, res["error"]))
        return "\n".join(lines)
    for key, label in (("nodes_missing", "缺节点类"), ("models_missing", "缺模型文件"),
                       ("inputs_missing", "缺必需输入"), ("map_bad", "映射错误")):
        items = res.get(key) or []
        if items:
            lines.append("%s[FAIL] %s %d 项：" % (indent, label, len(items)))
            for it in items[:12]:
                lines.append("%s   - %s" % (indent, it))
    if res.get("ok"):
        lines.append("%s[OK] 三项齐全，可以提交" % indent)
    return "\n".join(lines)
