#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""verify_llm_loop.py —— 端到端验证「LLM 创作闭环」（默认离线、零费用）

它跑的不是演示代码，而是和浏览器完全相同的业务路径：
    配置提供商 → 连接测试 → 绑定用途 → 预览提示词 → 生成 → Schema 校验
    → 草稿保存 → 人工编辑 → 确认落盘 → **引擎自己的 lint 验收**

默认用内置「离线演练（Mock）」通道：只替换网络那一段，下游全部真实执行。
最后一步真的调用 `stages/creation/scripts/script_rewrite.py lint`，
所以「产物是正式可用的」这件事由引擎判定，不由本脚本自说自话。

用法：
    python web/tools/verify_llm_loop.py                       # 临时工作区，跑完不删（-k 保留）
    python web/tools/verify_llm_loop.py -k                    # 跑完保留临时工作区以便查看
    python web/tools/verify_llm_loop.py --ep 2                # 指定集号
    python web/tools/verify_llm_loop.py --provider 你的id --confirm-cost
                                                              # 用已配置的**真实**模型（会真花钱，需显式确认）

退出码：0 全通 / 1 有失败 / 2 参数或前置不满足
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
REPO = WEB.parent
sys.path.insert(0, str(WEB))

from core import runner  # noqa: E402
from core.llm import drafts, gateway, store  # noqa: E402
from core.llm.errors import LLMError  # noqa: E402

FAILS = []
STEPS = []


def ok(cond, msg, extra=""):
    STEPS.append((bool(cond), msg, extra))
    if not cond:
        FAILS.append(msg)
        print("   [NG] %s %s" % (msg, extra))
    else:
        print("   [OK] %s %s" % (msg, extra))
    return bool(cond)


def head(n, title):
    print("\n%s\n步骤 %d · %s\n%s" % ("=" * 66, n, title, "=" * 66))


# ---------------------------------------------------------------------------
def make_fixture(ws: Path, ep: int = 1, total: int = 3) -> None:
    (ws / "creation" / "03-script").mkdir(parents=True, exist_ok=True)
    bp = {
        "title": "失忆的总裁，把我当成他妻子",
        "total_ep": total, "ep_seconds": 60, "platform": "ReelShort",
        "style_lock": "photorealistic live-action cinematography, natural skin texture",
        "episodes": [
            {"ep": i, "act": "起" if i == 1 else "承",
             "cold_open": "客人把汤泼在她围裙上，骂她端盘子的",
             "core_conflict": "卡米拉 vs 闹事客人 vs 她要保住的工作",
             "reversal": "男人当众叫她妻子，经理立刻改口称她 señora",
             "hook_type": "身份悬念", "hook": "门外一辆黑色轿车停下，车窗降下一半"}
            for i in range(1, total + 1)
        ],
    }
    (ws / "creation" / "03-script" / "blueprint.json").write_text(
        json.dumps(bp, ensure_ascii=False, indent=2), encoding="utf-8", newline="")
    (ws / "creation" / "03-script" / "diagnosis.json").write_text(
        json.dumps({"structure_confirmed": True, "confirmed_at": "verify"}, ensure_ascii=False),
        encoding="utf-8", newline="")
    (ws / "bible").mkdir(exist_ok=True)
    (ws / "bible" / "world-bible.json").write_text(json.dumps({
        "characters": [
            {"code": "CAMILA", "name": "卡米拉", "visual_anchor": "方圆过渡、略方、转角柔和", "palette": "#365F63"},
            {"code": "ADRIAN", "name": "阿德里安", "visual_anchor": "长椭圆、窄而内收", "palette": "#7B3C32"},
        ],
        "scenes": [{"code": "DINER", "desc": "海边小餐馆,深夜,黄铜吊灯"},
                   {"code": "STREET", "desc": "餐馆外的雨夜街道,湿沥青"}],
    }, ensure_ascii=False), encoding="utf-8", newline="")


def run_engine_lint(ws: Path, ep: int):
    """用引擎自己的 lint 验收产物（这是「正式产物」的判定者）。"""
    script = REPO / "stages" / "creation" / "scripts" / "script_rewrite.py"
    if not script.is_file():
        return None
    argv = [str(_engine_python()), str(script), "lint", "--ep", str(ep)]
    res = runner.run_stream(argv, ws=str(ws), timeout=120)
    return {"rc": res["rc"], "text": "\n".join(res["lines"]), "argv": argv}


def _engine_python():
    sys.path.insert(0, str(WEB))
    from core import paths  # noqa: PLC0415
    return paths.engine_python()


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="验证 LLM 创作闭环（默认离线演练）")
    ap.add_argument("--ep", type=int, default=1)
    ap.add_argument("--provider", default="", help="已配置的提供商 id；默认用内置 Mock")
    ap.add_argument("--confirm-cost", action="store_true", help="用真实提供商时必填（会产生费用）")
    ap.add_argument("-k", "--keep", action="store_true", help="保留临时工作区")
    ap.add_argument("--llm-dir", default="", help="LLM 配置目录（默认临时，不影响你现有配置）")
    a = ap.parse_args()

    ep = max(1, int(a.ep))
    real = bool(a.provider)
    if real and not a.confirm_cost:
        print("[STOP] 用真实提供商会发起付费调用；确认后加 --confirm-cost 重跑。")
        return 2

    t0 = time.time()
    tmp = Path(tempfile.mkdtemp(prefix="verify-loop-"))
    llm_dir = Path(a.llm_dir) if a.llm_dir else (tmp / "llm")
    store.use_dir(llm_dir)
    ws = tmp / "剧项目"
    ws.mkdir(parents=True)
    make_fixture(ws, ep=ep)

    print("=" * 66)
    print("SoloDrama · LLM 创作闭环验证")
    print("=" * 66)
    print("工作区    : %s" % ws)
    print("LLM 配置  : %s" % llm_dir)
    print("通道      : %s" % ("真实提供商 %s" % a.provider if real else "离线演练（Mock，零费用）"))

    gw = gateway.get_gateway()

    # ---------------------------------------------------------------- 1
    head(1, "配置提供商")
    if real:
        prov = store.get_provider(a.provider)
        ok(True, "复用已配置提供商", "· %s（%s）" % (prov["name"], prov["kind"]))
        pid = a.provider
    else:
        prov = store.upsert_provider({
            "id": "verify-mock", "name": "离线演练（Mock）", "kind": "mock",
            "default_model": "mock-episode", "models": ["mock-episode"],
            "capabilities": ["json"], "timeout_s": 30, "max_retries": 0, "enabled": True,
        })
        pid = "verify-mock"
        ok(prov["base_url"] == "mock://local", "演练通道地址固定", "· %s" % prov["base_url"])
        ok(prov["has_key"] is False, "演练通道不需要 Key")
    ok("api_key" not in prov, "对外结构不含明文 Key")

    # ---------------------------------------------------------------- 2
    head(2, "连接测试（不产生生成费用）")
    t = gw.test_provider(pid)
    ok(t.get("ok") is True, "连接测试通过", "· mode=%s" % t.get("mode"))
    if t.get("note"):
        print("       %s" % t["note"])

    # ---------------------------------------------------------------- 3
    head(3, "绑定业务用途")
    p = store.set_purpose("script.generate", {"provider_id": pid})
    ok(p.get("bound") is True and p.get("ready") is True, "「剧本正文生成」已就绪",
       "· %s / %s" % (p.get("provider_name"), p.get("model")))

    # ---------------------------------------------------------------- 4
    head(4, "读取前置并预览提示词")
    g = drafts.gates(ws)
    ok(g["ok"] is True, "G-0 相关前置齐备", "· %d 集 · %d 秒档" % (g["ep_count"], g["ep_seconds"]))
    ctx = drafts.context(ws, ep)
    ok(bool(ctx["header"]) and len(ctx["header"]) == 6, "HEADER 六字段", "· %s" % ctx["header_source"])
    pv = gw.preview("script.generate", {
        "blueprint_row": ctx["blueprint_row"], "style_lock": ctx["style_lock"],
        "char_header": ctx["header"][4], "scene_header": ctx["header"][5],
        "ep_seconds": ctx["ep_seconds"], "shot_count": ctx["shot_count"],
    })
    ok(pv["system_chars"] > 2000, "system 段来自仓库提示词原文", "· %d 字符" % pv["system_chars"])
    ok('"shots"' in pv["user"], "user 段内嵌输出 Schema")
    print("       模板 %s · 指纹 %s" % (pv["template_id"], pv["template_sha"]))

    # ---------------------------------------------------------------- 5
    head(5, "生成草稿（真实走 网关 → 解析 → Schema → 口径复核）")
    out = drafts.generate(ws, ep, gateway=gw, provider_id=pid)
    if not ok(out.get("ok") is True, "生成成功", "· %s" % (out.get("error") or "")):
        _finish(tmp, a.keep)
        return 1
    d = out["draft"]
    ok(d["status"] == "draft", "产物状态是草稿（不是正式文件）")
    ok(not Path(ctx["target"]).exists(), "生成阶段没有碰 03-剧本/ep_NN.md")
    ok(len(d["data"]["shots"]) == out["context"]["shot_count"], "镜头数符合本剧口径",
       "· %d 镜" % len(d["data"]["shots"]))
    total = sum(int(s["dur"]) for s in d["data"]["shots"])
    ok(ctx["shot_bounds"][0] <= len(d["data"]["shots"]) <= ctx["shot_bounds"][1],
       "镜数在 %d-%d 之间" % tuple(ctx["shot_bounds"]))
    ok(True, "总时长 %d 秒" % total)
    print("       草稿 %s · simulated=%s" % (d["id"], d.get("simulated")))

    # ---------------------------------------------------------------- 6
    head(6, "人工编辑（模拟用户改写第一镜的动作）")
    old_action = d["data"]["shots"][0]["action"]
    new_action = "人工改写：她把汤碗按回桌上，指节发白，眼睛盯着门口那个湿透的人"
    edited = d["md"].replace(old_action, new_action, 1)
    ok(new_action in edited, "改写已落到草稿文本", "· 替换 1 处")
    upd = drafts.update_draft(ws, d["id"], {"md": edited})
    ok(new_action in upd["draft"]["md"], "编辑已保存到草稿")

    # ---------------------------------------------------------------- 7
    head(7, "确认落盘（正式产物）")
    # ★ 演练门禁必须**两种通道都验**：旧写法只覆盖 Mock 路径，一旦用真实提供商跑
    #   （也就是真正要证明「接通了真模型」的那一次），这条断言必然报 NG，把 25/26 拖成「失败」。
    #   现在：无论哪条通道，都额外造一个 simulated=true 的草稿去撞门禁，确认它没被削弱。
    probe_id = "gateprobe"
    probe_path = drafts.draft_dir(str(ws)) / ("%s.json" % probe_id)
    probe_path.parent.mkdir(parents=True, exist_ok=True)
    probe_path.write_text(json.dumps({
        "id": probe_id, "ep": 1, "simulated": True, "status": "draft",
        "target": str(ws / "script" / "ep_01.md"), "md": "# TITLE: 门禁探针\n\nDUR: 8\n",
    }, ensure_ascii=False), encoding="utf-8")
    try:
        drafts.confirm(ws, probe_id)
        ok(False, "演练草稿未加 allow_simulated 时**必须**被拒绝")
    except LLMError as exc:
        ok("演练" in exc.text, "演练草稿默认禁止写入正式剧本", "· 两种通道都验")

    if real:
        # 真实通道：草稿不是演练产物，直接落盘（不需要 allow_simulated）
        res = drafts.confirm(ws, d["id"])
        ok(res.get("ok") is True, "真实模型草稿可直接落盘（无需 allow_simulated）")
        ok(d.get("simulated") is not True, "真实通道草稿标记为非演练")
    else:
        res = drafts.confirm(ws, d["id"], allow_simulated=True)
    target = Path(res["target"])
    ok(res.get("ok") is True and target.is_file(), "落盘成功", "· %s" % target.name)
    text = target.read_text(encoding="utf-8")
    ok(new_action in text, "落盘内容包含人工修改")
    ok("\r\n" not in text, "换行是 LF")
    ok("[SC-01]" in text and "DUR:" in text, "是 FFS 格式（含镜头块与 DUR）")

    # ---------------------------------------------------------------- 8
    head(8, "引擎验收（script_rewrite.py lint）—— 由引擎判定是否可用")
    lint = run_engine_lint(ws, ep)
    if lint is None:
        ok(False, "找不到引擎 lint 脚本，无法验收")
    else:
        ok(lint["rc"] == 0, "引擎 lint 退出码为 0", "· rc=%d" % lint["rc"])
        tail = [ln for ln in lint["text"].splitlines() if ln.strip()][-8:]
        for ln in tail:
            print("       | %s" % ln)

    # ---------------------------------------------------------------- 9
    head(9, "用量与成本口径")
    u = store.usage(limit=5)
    row = (u["items"] or [{}])[0]
    ok(row.get("ok") is True, "用量已记录")
    ok(row.get("cost", {}).get("usd") is None, "金额为「未知」（未按 token 单价编造）")
    ok("simulated" in row, "用量里标注了是否演练", "· simulated=%s" % row.get("simulated"))
    ok(row.get("prompt_sha") and not row.get("prompt"), "只存提示词指纹，不存正文")

    # ---------------------------------------------------------------- 10
    head(10, "产物预览")
    lines = text.splitlines()
    for ln in lines[:14]:
        print("   | %s" % ln)
    print("   | ...（共 %d 行）" % len(lines))

    _finish(tmp, a.keep)
    print("\n" + "-" * 66)
    passed = sum(1 for s in STEPS if s[0])
    print("结果：%d/%d 项通过，耗时 %.2fs" % (passed, len(STEPS), time.time() - t0))
    if FAILS:
        print("[NG] 失败项：")
        for f in FAILS:
            print("   - %s" % f)
        return 1
    print("[OK] LLM 创作闭环验证通过（配置 → 测试 → 调用 → 校验 → 草稿 → 确认 → 引擎 lint）")
    return 0


def _finish(tmp: Path, keep: bool) -> None:
    if keep:
        print("\n临时目录已保留：%s" % tmp)
        return
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
