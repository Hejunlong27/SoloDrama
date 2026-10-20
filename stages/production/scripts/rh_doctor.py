#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""rh_doctor.py —— RunningHub 双 Key 体检与能力路由（默认零网络、零计费）

为什么需要它
------------
RunningHub 的 API Key 分三类，且**不同 API 类型接受的 Key 类型不同**。
官方《开始》文档原文（https://www.runninghub.cn/runninghub-api-doc-cn/doc-8287334）：

    API 类型        | 可使用的 API Key
    ----------------|-----------------------------------------------
    模型 API        | 企业级-共享
    LLM API         | 企业级-共享
    AI 应用 API     | 消费级-会员、企业级-共享、企业级-独占
    工作流 API      | 消费级-会员、企业级-共享、企业级-独占

    「注意：模型 API 和 LLM API 仅支持企业级-共享 API Key 调用。」

推论（重要，直接影响设计）：
  * 「工作流 / AI 应用」用消费级 Key 就行，**不该白耗企业级的按量余额**；
  * 「闭源模型 / LLM」**只能用企业级-共享 Key**，消费级 Key 一定失败；
  * 企业级-共享在能力上是消费级的**超集**（四类都能调），
    所以留两把 Key 的理由是**计费路由**（会员权益 vs 按量钱包），不是能力，而是省钱。

本脚本做两件事，且**只做只读调用，绝不提交任何任务**：
  1) 打码显示每把 Key 的类型与余额（/uc/openapi/accountStatus，官方 released 接口）；
  2) 按官方能力矩阵做**提交前预检**：给定「想调什么 API + 用哪把 Key」，直接判 OK / 阻断。

安全约定：
  * 默认**不联网**，只打印「将要调用什么」，等你确认；
  * 加 --live 才真发请求，且只发下面这两个**不产生任务、不计费**的只读接口；
  * Key 一律打码，永不落日志、永不回显全文。

用法：
  python rh_doctor.py                      # 只打印计划（零网络）
  python rh_doctor.py --live               # 真体检（只读，不计费）
  python rh_doctor.py --check model        # 只做预检：模型 API 该用哪把 Key
  python rh_doctor.py --check workflow --key consumer
  python rh_doctor.py --matrix             # 多账号：site × tier × 是否就位（零网络）
  python rh_doctor.py --matrix --live      # 多账号：逐把做只读探针，确认它属于哪个站点
  python rh_doctor.py --probe-readonly     # 只读探针（等价于 --matrix --live）

★ 铁律（2026-10-20 反馈 P0-2）：**禁止用 /run 接口做连通性/归属探测**。
  `POST /openapi/v2/run/workflow/{id}` 不是幂等接口 —— workflowId 只要格式上像样，
  平台就会真的建任务并排队执行。2026-10-19 实测因此产生了一个真实任务
  （taskId 2112006454897758210，随后 FAILED、usage=null，属侥幸未计费）。
  需要探针时一律用本文件的 `probe_readonly()`（查询接口 + 故意不存在的 taskId）。

退出码：0 通过 / 1 预检阻断 / 2 环境或网络错误
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = os.getenv("RUNNINGHUB_BASE_URL", "https://www.runninghub.cn")
TIMEOUT = 30.0

# --- 官方能力矩阵（单一真源；改这里就等于改路由规则）---------------------
# tier 取值：consumer=消费级-会员 / ent_shared=企业级-共享 / ent_exclusive=企业级-独占
CAPABILITY: dict[str, set[str]] = {
    "workflow":  {"consumer", "ent_shared", "ent_exclusive"},
    "ai-app":    {"consumer", "ent_shared", "ent_exclusive"},
    "model":     {"ent_shared"},
    "llm":       {"ent_shared"},
}

API_LABEL = {
    "workflow": "工作流 API",
    "ai-app":   "AI 应用 API",
    "model":    "模型 API（闭源模型）",
    "llm":      "LLM API",
}

TIER_LABEL = {
    "consumer":      "消费级-会员",
    "ent_shared":    "企业级-共享",
    "ent_exclusive": "企业级-独占",
}

# 环境变量名 -> 我们内部的 tier 假设（拿不准的由 apiType 实测结果修正）
KEY_ENV = {
    "consumer":   "RUNNINGHUB_API_KEY",
    "ent_shared": "RUNNINGHUB_ENT_API_KEY",
}

# apiType 实测值 -> tier。官方文档只给了 NORMAL 这一例，其余靠 --live 实测补。
# 认不出来的值一律如实打印原文，不猜。
APITYPE_TO_TIER = {
    "NORMAL": "consumer",
    # 2026-09-18 实测补：企业级-共享 Key 的 apiType 实测值是 SHARED
    # （该 Key 随后成功调用了模型 API，反证 tier 判定正确）
    "SHARED": "ent_shared",
}


def mask(key: str) -> str:
    k = (key or "").strip()
    if not k:
        return "(未设置)"
    if len(k) <= 10:
        return k[:2] + "****"
    return f"{k[:6]}****{k[-4:]}  (len={len(k)})"


def post(path: str, body: dict, key: str, base: str | None = None) -> tuple[int, dict | None, str]:
    """极简 stdlib POST。返回 (http_status, json_or_None, raw_text)。"""
    root = (base or BASE_URL).rstrip("/")
    req = urllib.request.Request(
        root + path,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Host": root.split("//")[-1].split("/")[0],
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", "replace")
            try:
                return resp.status, json.loads(raw), raw
            except json.JSONDecodeError:
                return resp.status, None, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw), raw
        except json.JSONDecodeError:
            return e.code, None, raw
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return 0, None, f"{type(e).__name__}: {e}"


# --------------------------------------------------------------------------
# 能力路由预检 —— 本脚本的核心：把官方表格变成代码，提交前就拦住
# --------------------------------------------------------------------------
def preflight(api_type: str, tier: str) -> tuple[bool, str]:
    allowed = CAPABILITY.get(api_type)
    if allowed is None:
        return False, f"未知的 API 类型 '{api_type}'（可选：{'/'.join(CAPABILITY)}）"
    if tier in allowed:
        return True, f"{API_LABEL[api_type]} 可以走「{TIER_LABEL[tier]}」Key。"
    ok_tiers = "、".join(TIER_LABEL[t] for t in ("consumer", "ent_shared", "ent_exclusive")
                        if t in allowed)
    return False, (f"阻断：{API_LABEL[api_type]} **不接受**「{TIER_LABEL[tier]}」Key。"
                   f"只能用：{ok_tiers}。")


def load_keys(key_file: Path | None) -> dict[str, str]:
    """环境变量优先；可选从 json 文件补（该文件不应提交）。"""
    keys = {tier: os.getenv(env, "").strip() for tier, env in KEY_ENV.items()}
    if key_file and key_file.is_file():
        try:
            data = json.loads(key_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"[WARN] 读不了 {key_file}: {e}")
            data = {}
        for tier in ("consumer", "ent_shared"):
            # 允许写 "consumer" / "RUNNINGHUB_API_KEY" 两种键名
            v = data.get(tier) or data.get(KEY_ENV[tier]) or ""
            if v and not keys[tier]:
                keys[tier] = str(v).strip()
    return keys


def print_matrix() -> None:
    print("官方能力矩阵（来源：RunningHub《开始》文档）")
    print("-" * 74)
    print(f"{'API 类型':<22}{'消费级-会员':>12}{'企业级-共享':>14}{'企业级-独占':>14}")
    print("-" * 74)
    for api in ("workflow", "ai-app", "model", "llm"):
        row = [("是" if t in CAPABILITY[api] else "否") for t in
               ("consumer", "ent_shared", "ent_exclusive")]
        print(f"{API_LABEL[api]:<22}{row[0]:>12}{row[1]:>14}{row[2]:>14}")
    print("-" * 74)
    print("⇒ 工作流 / AI 应用：消费级即可，别白耗企业级按量余额")
    print("⇒ 闭源模型 / LLM：只有企业级-共享可用，消费级一定失败")
    print()


# --------------------------------------------------------------------------
# ★ 只读探针（反馈 P0-2）
# --------------------------------------------------------------------------
# 背景：2026-10-19 为判断「哪把 Key 能用哪个站点」，对
#   POST /openapi/v2/run/workflow/1   发探测请求 —— 该接口**不是幂等的**，
#   于是真的建了任务并排队执行（taskId 2112006454897758210，随后 FAILED）。
#   换一把余额充足、prompt 合法的 Key，这就是**真实扣费**。
#
# 铁律：连通性/归属探测**只允许**用查询类接口（本函数），禁止用 /run 或任何 create 接口。
READONLY_PROBE_PATH = "/openapi/v2/query"
READONLY_PROBE_BODY = {"taskId": "0"}     # 不存在的 taskId：查询类接口只会「查不到」
INVALID_KEY_HINTS = ("api key不存在", "apikey不存在", "api key 不存在", "invalid api key",
                     "key不存在", "key 不存在", "unauthorized")
TASK_MISSING_HINTS = ("任务不存在", "task not exist", "not found", "不存在", "无此任务")


def probe_readonly(base: str, key: str) -> dict:
    """只读探针：用查询接口判断「这把 Key 在这个站点是否被承认」。

    返回 {"verdict": "ok"|"bad_key"|"route_missing"|"network"|"unknown", "detail": str}

    判据（不猜）：
      * HTTP 200 且 code==0            -> ok（查询成功，只是查不到 taskId=0）
      * 业务 msg 命中 INVALID_KEY_HINTS -> bad_key（该站点不认这把 Key）
      * 业务 msg 命中 TASK_MISSING_HINTS / code 1001/1007 -> ok（Key 有效，只是任务不存在）
      * HTTP 404 / code 1001 且提示 URL 不存在 -> route_missing（站点没有 v2 路由）
      * 其它 -> unknown（如实回显原文，人工判断）
    """
    status, payload, raw = post(READONLY_PROBE_PATH, dict(READONLY_PROBE_BODY), key, base=base)
    if status == 0:
        return {"verdict": "network", "detail": raw}
    if payload is None:
        return {"verdict": "route_missing" if status in (404, 405) else "unknown",
                "detail": "HTTP %s: %s" % (status, raw[:160])}
    code = payload.get("code")
    msg = str(payload.get("msg") or payload.get("message") or payload.get("error") or "")
    low = msg.lower()
    text = "code=%s msg=%s" % (code, msg[:120])
    if code in (0, "0"):
        return {"verdict": "ok", "detail": text}
    if any(h in low for h in INVALID_KEY_HINTS):
        return {"verdict": "bad_key", "detail": text}
    if any(h in low for h in TASK_MISSING_HINTS) or str(code) in ("1001", "1007"):
        return {"verdict": "ok", "detail": text}
    if status in (404, 405):
        return {"verdict": "route_missing", "detail": text}
    return {"verdict": "unknown", "detail": text}


# --------------------------------------------------------------------------
# ★ 多账号 × 双站点 × 双 tier 的 Key 清单（反馈 P1-6）
# --------------------------------------------------------------------------
# 现状：KEY_ENV 只有两个固定变量名，无法表达「3 个账号 × 2 个站点」。
# 实测（2026-10-19）：账号1/2 的消费级 Key 只能用于 .ai 站，账号3 的只能用于 .cn 站；
# 同一把 Key 拿到另一站上传直接报「API Key 不存在」。于是 3 个账号实际只跑得动 1–2 个。
#
# 清单文件（<工作区>/keys.json）格式（两种都认）：
#   {"keys": [{"account": "账号1", "site": "https://www.runninghub.ai",
#              "tier": "consumer", "env": "RH_KEY_A1_AI"}, ...]}
#   或顶层直接是数组 [{...}, ...]
# `env` 只写**环境变量名**；Key 本身仍从环境变量读，清单里不落明文。
KEYS_FILENAME = "keys.json"
SITE_LABEL = {
    "https://www.runninghub.cn": "ZH(.cn)",
    "https://www.runninghub.ai": "AI(.ai)",
}


def load_key_entries(path: Path | None) -> list[dict]:
    """读多账号 Key 清单；文件不存在返回空列表。"""
    if not path or not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"[WARN] 读不了 Key 清单 {path}: {e}")
        return []
    items = data.get("keys") if isinstance(data, dict) else data
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        env = str(it.get("env") or it.get("key_env") or "").strip()
        tier = str(it.get("tier") or "consumer").strip()
        site = str(it.get("site") or it.get("base_url") or BASE_URL).strip().rstrip("/")
        if tier not in TIER_LABEL:
            print(f"[WARN] Key 清单里 tier='{tier}' 不认识（应为 consumer/ent_shared/ent_exclusive），已跳过")
            continue
        if not env:
            print("[WARN] Key 清单里缺少 env 字段（应写环境变量名），已跳过一条")
            continue
        out.append({"account": str(it.get("account") or env),
                    "site": site, "tier": tier, "env": env,
                    "key": os.getenv(env, "").strip()})
    return out


def cmd_matrix(entries: list[dict], live: bool) -> int:
    """打印 site × tier × 可用性矩阵。默认只看「环境变量是否就位」，加 --live 才真探。"""
    if not entries:
        print("没有多账号 Key 清单。")
        print("  建一个 %s（只写环境变量名，不写明文 Key）：" % KEYS_FILENAME)
        print("  {")
        print('    "keys": [')
        print('      {"account": "账号1", "site": "https://www.runninghub.ai", '
              '"tier": "consumer", "env": "RH_KEY_A1_AI"},')
        print('      {"account": "账号3", "site": "https://www.runninghub.cn", '
              '"tier": "consumer", "env": "RH_KEY_A3_CN"}')
        print("    ]")
        print("  }")
        return 0
    print("Key 矩阵（site × tier × 可用性）")
    print("-" * 82)
    print(f"{'账号':<12}{'站点':<12}{'tier':<14}{'Key':<20}{'只读探针'}")
    print("-" * 82)
    problems = 0
    buckets: dict[tuple, int] = {}
    for e in entries:
        site_label = SITE_LABEL.get(e["site"], e["site"])
        probe = "-（未联网）"
        if not e["key"]:
            probe = "[缺] 环境变量 %s 未设置" % e["env"]
            problems += 1
        elif live:
            r = probe_readonly(e["site"], e["key"])
            v = r["verdict"]
            probe = {"ok": "[OK] Key 在本站有效",
                     "bad_key": "[NG] 本站不认这把 Key（换站点或换 Key）",
                     "route_missing": "[NG] 站点无 v2 查询路由",
                     "network": "[NG] 连不上：%s" % r["detail"][:40],
                     "unknown": "[?] %s" % r["detail"][:60]}[v]
            if v != "ok":
                problems += 1
            else:
                buckets[(e["site"], e["tier"])] = buckets.get((e["site"], e["tier"]), 0) + 1
        print(f"{e['account'][:11]:<12}{site_label[:11]:<12}{TIER_LABEL[e['tier']]:<14}"
              f"{mask(e['key'])[:19]:<20}{probe}")
    print("-" * 82)
    if live:
        print("可用于并发的（site, tier）组合：")
        if not buckets:
            print("  （无 —— 先修上面 [NG] 的项）")
        for (site, tier), n in sorted(buckets.items()):
            print("  %s / %s：%d 把可用" % (SITE_LABEL.get(site, site), TIER_LABEL[tier], n))
        print("  提示：引擎当前一次只用一个 Key；要真正吃到多账号并发，")
        print("        需要把可用 Key 逐条分配给 worker（见 references/runninghub-contract.md §多账号）。")
    else:
        print("只读探针未执行（加 --live 才联网）。探针只用查询接口，**不会建任务、不会扣费**。")
    return 1 if problems and live else 0


def _default_keys_path(workspace: str | None) -> Path | None:
    """定位多账号 Key 清单：显式 --workspace > 环境变量 > 当前目录。"""
    ws = workspace or os.getenv("SOLODRAMA_WORKSPACE") or os.getenv("DRAMA_WORKSPACE")
    if ws:
        return Path(ws).expanduser() / KEYS_FILENAME
    return Path.cwd() / KEYS_FILENAME


def main() -> int:
    ap = argparse.ArgumentParser(description="RunningHub 双 Key 体检（默认零网络）")
    ap.add_argument("--live", action="store_true", help="真发只读请求；不给则只打印计划")
    ap.add_argument("--key-file", default=None, help="可选 json：含 consumer/ent_shared 两把 Key，"
                                                     "或 {keys:[{account,site,tier,env}]} 多账号清单")
    ap.add_argument("--workspace", default=None,
                    help="工作区（默认读环境变量；用于定位 <工作区>/keys.json）")
    ap.add_argument("--check", choices=tuple(CAPABILITY), default=None,
                    help="只做提交前预检，不联网")
    ap.add_argument("--key", choices=("consumer", "ent_shared", "ent_exclusive"), default=None,
                    help="配合 --check 指定 Key 类型")
    ap.add_argument("--matrix", action="store_true",
                    help="打印「站点 × tier × 可用性」矩阵（读 <工作区>/keys.json；加 --live 才真探）")
    ap.add_argument("--probe-readonly", dest="probe_readonly", action="store_true",
                    help="只读探针：判断每把 Key 属于哪个站点（只用查询接口，不建任务、不扣费）")
    args = ap.parse_args()

    print("=" * 74)
    print("RunningHub Key 体检 / 能力路由")
    print("=" * 74)
    print("★ 铁律：连通性探测**只能用查询接口**。禁止用 POST /openapi/v2/run/... 做探测 ——")
    print("  该接口会真的建任务并排队执行（2026-10-19 实测踩到，非幂等）。")
    print()

    # ---- 多账号矩阵 / 只读探针（反馈 P1-6 / P0-2）------------------------
    if args.matrix or args.probe_readonly:
        kp = (Path(args.key_file).resolve() if args.key_file
              else _default_keys_path(args.workspace))
        entries = load_key_entries(kp)
        if kp:
            print("Key 清单：%s%s" % (kp, "" if kp.is_file() else "（不存在，按空处理）"))
            print()
        return cmd_matrix(entries, live=bool(args.live or args.probe_readonly))

    # ---- 纯离线预检模式 -------------------------------------------------
    if args.check:
        print_matrix()
        if not args.key:
            print(f"你想调「{API_LABEL[args.check]}」，可选 Key 类型：")
            for t in ("consumer", "ent_shared", "ent_exclusive"):
                ok, why = preflight(args.check, t)
                print(f"  [{'OK  ' if ok else 'BLOCK'}] {TIER_LABEL[t]:<12} {why}")
            return 0
        ok, why = preflight(args.check, args.key)
        print(f"[{'OK' if ok else 'BLOCK'}] {why}")
        return 0 if ok else 1

    key_file = Path(args.key_file).resolve() if args.key_file else None
    keys = load_keys(key_file)
    print_matrix()

    print("Key 来源")
    print("-" * 74)
    for tier in ("consumer", "ent_shared"):
        env = KEY_ENV[tier]
        src = f"env {env}" if os.getenv(env) else ("key-file" if keys[tier] else "未提供")
        print(f"  {TIER_LABEL[tier]:<12} {mask(keys[tier]):<34} [{src}]")
    print()

    # ---- 零网络：只说明将调用什么 ---------------------------------------
    if not args.live:
        print("计划模式（未联网）—— 加 --live 才真发请求")
        print("-" * 74)
        print("将要调用的接口（均为只读，不提交任务、不计费）：")
        print(f"  POST {BASE_URL}/uc/openapi/accountStatus")
        print("       → 返回 apiType(Key 类型) / remainCoins(RH币) / remainMoney(钱包) / currency")
        print("  每把已提供的 Key 各调一次。")
        print()
        print("不会调用：/task/openapi/create、/task/openapi/ai-app/run、任何 /openapi/v2/{模型} 任务接口")
        print("⇒ 本次体检无论成败，都不会产生费用。")
        return 0

    # ---- 联网体检 -------------------------------------------------------
    print("实时体检（只读）")
    print("-" * 74)
    problems = 0
    observed: dict[str, str] = {}

    for tier in ("consumer", "ent_shared"):
        key = keys.get(tier) or ""
        assume = TIER_LABEL[tier]
        if not key:
            print(f"{assume:<12} 跳过（未提供）")
            continue

        status, payload, raw = post("/uc/openapi/accountStatus", {"apikey": key}, key)
        if status == 0:
            print(f"{assume:<12} [FAIL] 连不上：{raw}")
            problems += 1
            continue
        if payload is None:
            print(f"{assume:<12} [FAIL] HTTP {status} 非 JSON：{raw[:160]}")
            problems += 1
            continue

        code = payload.get("code")
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        if code not in (0, "0", None):
            print(f"{assume:<12} [FAIL] code={code} msg={payload.get('msg')!r}"
                  f"  原始：{json.dumps(payload, ensure_ascii=False)[:200]}")
            problems += 1
            continue

        api_type = str(data.get("apiType", "") or "")
        actual = APITYPE_TO_TIER.get(api_type.upper(), "")
        actual_label = TIER_LABEL.get(actual, f"未知({api_type})")
        observed[tier] = actual

        print(f"{assume:<12} [OK] apiType={api_type or '(空)'} → 实测类型 {actual_label}"
              f" | RH币={data.get('remainCoins')} 钱包={data.get('remainMoney')}"
              f" {data.get('currency') or ''} | 在跑任务={data.get('currentTaskCounts')}")
        if actual and actual != tier:
            print(f"{'':<12} [WARN] 与预期不符：你把「{TIER_LABEL[actual]}」Key 放在了 "
                  f"{KEY_ENV[tier]} 里，建议换到 {KEY_ENV.get(actual, '?')}")
        elif not actual:
            print(f"{'':<12} [WARN] apiType='{api_type}' 不在已知映射里，"
                  f"请把原文反馈给我，我好补进 APITYPE_TO_TIER（不猜）")

    print()
    print("结论（按官方能力矩阵）")
    print("-" * 74)
    have = {t: bool(keys.get(t)) for t in ("consumer", "ent_shared")}
    for api in ("workflow", "ai-app", "model", "llm"):
        usable = [TIER_LABEL[t] for t in ("consumer", "ent_shared") if have[t] and t in CAPABILITY[api]]
        if usable:
            print(f"  {API_LABEL[api]:<22} 可用（{'/'.join(usable)}）")
        else:
            need = "、".join(TIER_LABEL[t] for t in ("consumer", "ent_shared", "ent_exclusive")
                             if t in CAPABILITY[api])
            print(f"  {API_LABEL[api]:<22} [阻断] 缺可用 Key，需要：{need}")

    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
