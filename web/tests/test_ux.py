#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_ux.py —— 用户语言层契约测试（离线、零网络、零计费）

这是「使用端 ≠ 开发者端」这条产品纪律的机器守卫：
  * 用户端所有文案里**不得出现**命令、参数、退出码、门禁代号、批次号、平台点数、工作区路径；
  * 每个用户任务引用的引擎动作都必须真实存在；
  * 15 个引擎环节必须能被完整归并到 6 个用户阶段（不漏环节）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
if str(WEB) not in sys.path:
    sys.path.insert(0, str(WEB))

from core import commands as CMD  # noqa: E402
from core import ux  # noqa: E402

FAILS = []

# 禁止出现在用户界面文案里的开发者词汇
FORBIDDEN = ["argv", "退出码", "门禁", "工作区", "RH币", "批次号", "G0", "G-1", "G5", "G7", "G8",
             "--yes", "--submit", "--resume", "drama.py", "workspace", "作业 id", "spec_id", "sqlite"]


def check(cond, msg):
    if not cond:
        FAILS.append(msg)
        print("  [NG] %s" % msg)
    return cond


# ---------------------------------------------------------------------------
# 机器选项 ↔ 引擎选项的**逐字对齐**（2026-11-06 用户实测反馈的直接产物）
# ---------------------------------------------------------------------------
def _engine_options() -> dict:
    """`model_gate.MODEL_OPTIONS` —— 通道清单的唯一真源。"""
    eng = WEB.parent / "stages" / "production" / "scripts"
    if str(eng) not in sys.path:
        sys.path.insert(0, str(eng))
    import model_gate  # noqa: PLC0415
    return model_gate.MODEL_OPTIONS


def _check_dual(t) -> None:
    """双选组（「用哪台机器做画面」）的四条硬约束。

    起因：2026-11-06 实测「新建项目后什么都没选，就默认变成 RunningHub」。
    根因是这个界面层自己写了一份通道清单，值与引擎不一致（`runninghub` vs
    `runninghub_workflow`、`closed_model` vs `closed_source`），
    而且视频组的第一项就是带 `recommend` 的 RunningHub。四条一起钉住：

    1. 每个 value 必须在 `MODEL_OPTIONS[kind]` 里 —— 否则点下去报「未知选项」；
    2. **不能有必填执行依据** —— 这一步只提交确认单，收不了工作流/地址；
    3. 带 `paid` 的选项不得带 `recommend` —— 花钱的默认值必须用户亲手点；
    4. 两类都必须有本机（免费）选项 —— 否则等于强迫用户走计费通道。
    """
    eng = _engine_options()
    for g in t.ui.get("groups") or []:
        kind = g["key"]
        opts = eng.get(kind) or []
        ids = [o["id"] for o in opts]
        vals = [o["value"] for o in g["options"]]
        for o in g["options"]:
            check(o["value"] in ids,
                  "机器选项 %s（%s）不是引擎的通道 id；可选 %s" % (o["value"], kind, ids))
            eng_opt = next((x for x in opts if x["id"] == o["value"]), {}) or {}
            check(not (eng_opt.get("requires") or []),
                  "机器选项 %s 需要执行依据 %s，这个界面收不了 —— 应让用户去「模型中心」"
                  % (o["value"], eng_opt.get("requires")))
            check(not (o.get("recommend") and o.get("paid")),
                  "机器选项 %s 既标了推荐又标了要花钱 —— 计费通道不得预选" % o["value"])
        check("local_comfyui" in vals, "%s 组缺少「本机（免费）」选项" % kind)
        check(len(set(vals)) == len(vals), "%s 组的选项值有重复" % kind)


def test_no_price_estimate_in_user_text():
    """用户端不得出现**任何**单价或预估金额（2026-11-06 用户明确要求）。

    为什么连「¥数字」都禁：内置单价已低报约 4 倍，任何预估价都会被当成预算依据。
    正确口径是「按平台实际用量结算」，跑完按台账报实测。
    """
    print("[7] 用户文案不得出现单价或预估金额")
    bad_pat = re.compile(r"(币\s*/\s*(段|秒|张|次)|\d+\s*币/|￥\s*\d+(\.\d+)?\s*/\s*时|约\s*¥?\s*\d+\s*元)")
    free_ok = re.compile(r"￥0")
    for txt in _user_texts():
        if free_ok.search(txt):          # 「￥0（免费）」是事实陈述，不是报价
            txt = free_ok.sub("", txt)
        m = bad_pat.search(txt)
        if m:
            check(False, "用户文案出现单价/预估金额「%s」：%s" % (m.group(0), txt[:60]))


def _user_texts():
    """所有会显示给用户的文案。"""
    out = []
    for t, m in ux.GLOSSARY:
        out += [t, m]
    for s in ux.USER_STAGES:
        out += [s["name"], s["hint"]]
    out += list(ux.STATE_TEXT.values())
    for t in ux.TASKS:
        d = t.as_dict()
        out += [d["title"], d["why"], d["how"], d["cost_hint"] or "", d["after"] or ""]
        ui = d["ui"]
        if ui.get("note"):
            out.append(ui["note"])
        if ui.get("confirm_title"):
            out.append(ui["confirm_title"])
        if ui.get("free_label"):
            out.append(ui["free_label"])
        for k in ("options",):
            for o in ui.get(k) or []:
                out += [o["title"], o["desc"]]
        for g in ui.get("groups") or []:
            out += [g["label"]]
            for o in g["options"]:
                out += [o["title"], o["desc"]]
        for s in ui.get("steps") or []:
            out.append(s.get("label") or "")
        for f in ui.get("fields") or []:
            out += [f["label"], f.get("placeholder") or ""]
        for q in ui.get("questions") or []:
            out.append(q["text"])
    return [x for x in out if x]


def test_no_developer_vocabulary():
    print("[1] 用户文案不得出现开发者词汇")
    for txt in _user_texts():
        for bad in FORBIDDEN:
            if bad in txt:
                check(False, "用户文案出现「%s」：%s" % (bad, txt[:60]))


def test_stages_cover_all_rounds():
    print("[2] 15 环节必须被 6 个用户阶段完整覆盖")
    from core import reader  # noqa: PLC0415
    covered = set()
    for s in ux.USER_STAGES:
        covered |= set(s["rounds"])
    all_rounds = {r[0] for r in reader.ROUNDS}
    missing = all_rounds - covered - {"-1", "0", "12"}   # -1/0 是前置设置，12 归入审片阶段由任务覆盖
    check(not missing, "以下环节没有被任何用户阶段覆盖：%s" % sorted(missing))
    check(len(ux.USER_STAGES) == 6, "用户阶段数应为 6，实际 %d" % len(ux.USER_STAGES))


def test_tasks_reference_real_specs():
    print("[3] 用户任务的引擎动作必须真实存在")
    check(len(ux.TASKS) >= 8, "任务数过少")
    ids = [t.id for t in ux.TASKS]
    check(len(ids) == len(set(ids)), "任务 id 重复")
    for t in ux.TASKS:
        for sid in t.spec_ids:
            check(CMD.get(sid) is not None, "任务 %s 引用了不存在的动作：%s" % (t.id, sid))
        for sid in ux._ui_specs(t):
            check(CMD.get(sid) is not None, "任务 %s 的界面引用了不存在的动作：%s" % (t.id, sid))
        ui = t.ui
        check(ui.get("kind") in ("choice", "dual_choice", "prompt", "sequence",
                                 "plan_then_run", "questions", "form"),
              "任务 %s 的界面类型未知：%s" % (t.id, ui.get("kind")))
        if ui.get("kind") == "choice":
            spec = CMD.get(ui["spec"])
            p = [x for x in spec.params if x.key == ui["field"]]
            check(bool(p), "任务 %s 的选项字段在命令里不存在" % t.id)
            if p:
                for o in ui["options"]:
                    check(o["value"] in (p[0].choices or []),
                          "任务 %s 的选项 %s 不是引擎允许的取值" % (t.id, o["value"]))
        if ui.get("kind") == "plan_then_run":
            check(CMD.get(ui["plan_spec"]).billing == CMD.FREE, "「先算钱」那一步必须是免费的")
            # 「开始生成」必须标出**资源代价**：本机跑是 GPU（￥0 但占卡），平台通道是 PAID。
            # 2026-11-06：原来只认 PAID，而 video.run 早已是「本机 GPU 出片」——
            # 这条断言把默认通道锁死在计费通道上，是本轮「默认变成 RunningHub」的同类问题。
            check(CMD.get(ui["run_spec"]).billing in (CMD.PAID, CMD.GPU),
                  "「开始生成」那一步必须标出资源代价（计费 或 占 GPU）")
        if ui.get("kind") == "dual_choice":
            _check_dual(t)
        if ui.get("kind") == "questions":
            spec = CMD.get(ui["spec"])
            for q in ui["questions"]:
                check(any(x.key == q["key"] for x in spec.params),
                      "合规问题 %s 在命令参数里不存在" % q["key"])


def test_money_and_state():
    print("[4] 金额与状态措辞")
    check(ux.yuan(0) == "¥0", "零金额格式异常")
    check(ux.yuan(0.36) == "¥0.36", "小额金额格式异常：%s" % ux.yuan(0.36))
    check(ux.yuan(1234.5) == "¥1235", "大额金额应取整：%s" % ux.yuan(1234.5))
    check(ux.coins_to_yuan(145) == "¥0.36", "点数换算异常：%s" % ux.coins_to_yuan(145))
    for k, v in ux.STATE_TEXT.items():
        check(bool(v), "状态 %s 无人话措辞" % k)
        check(k not in v, "状态措辞里不应出现工程词：%s" % v)


def test_friendly_error():
    print("[5] 失败提示必须是人话且不泄露退出码")
    for code in (0, 2, 3, 4, 130, 1, 99):
        f = ux.friendly_error(code, "工作流运行失败")
        check(f["level"] in ("ok", "ask", "fix", "stop", "error"), "未知级别：%s" % f["level"])
        check(str(code) not in f["title"], "标题里出现退出码数字：%s" % f["title"])
        for bad in ("退出码", "exit code"):
            check(bad not in f["detail"], "说明里出现工程词")
    check(ux.friendly_error(4)["level"] == "ask", "退出码 4（等待确认）应翻译为「需要你确认」")
    check(ux.friendly_error(3)["level"] == "stop", "熔断应翻译为「已停下来保护你的钱」")
    check("ComfyUI" in ux.friendly_error(1, "本机 ComfyUI 未启动")["title"] or
          "画图工具" in ux.friendly_error(1, "本机 ComfyUI 未启动")["title"],
          "本机画图工具未开时应给出可懂提示")

    # ★ 2026-11-05 实测抓到：预检报「缺一个 LoRA」时被翻成「画图工具连不上」，
    #   人于是去重启 ComfyUI，而真正要做的是下一个模型文件。两件事必须分开。
    miss = ("视频 · local ｜ http://127.0.0.1:8188\n[NG] 不可用：缺文件\n"
            " - 模型文件齐全：缺：#145 LoraLoaderModelOnly = minimax_h3_8step.safetensors")
    down = ("连不上 ComfyUI http://127.0.0.1:8188（probe）\n"
            "  原因：<urlopen error [WinError 10061] 由于目标计算机积极拒绝，无法连接。>")
    check(ux.friendly_error(1, miss)["title"] != ux.friendly_error(1, down)["title"],
          "「缺模型文件」与「服务连不上」必须是两条不同的提示")
    check("缺" in ux.friendly_error(1, miss)["title"], "缺件时应说「缺文件」，而不是「连不上」")


def test_help_prompt():
    print("[6] 求助提示词")
    p = ux.help_prompt("<ws>", "第 3 集有几个镜头一直失败")["prompt"]
    check("第 3 集有几个镜头一直失败" in p, "未带上用户的问题")
    check("大白话" in p, "未要求用大白话解释")
    check("确认" in p, "未要求先确认再继续")
    for bad in ("第 -1 步", "第 0 步", "环节", "退出码", "argv"):
        check(bad not in p, "求助提示词暴露了内部说法「%s」" % bad)


def test_no_failures():
    """把 `check()` 收集到的问题变成 **pytest 也能看见**的失败。

    为什么需要这一条：`check()` 只打印不抛出（为了脚本模式下一次报全）。
    后果是 `python web/tests/test_ux.py` 会红，而 `pytest web/tests` 一直把它当绿的 ——
    这套契约就这样静默失效了，2026-11-06 才发现（「默认 RunningHub」「report.batch 已删
    但任务还在引用」三条同时挂着）。定义在文件最后，靠执行顺序读累积结果。
    """
    assert not FAILS, "用户语言层契约有 %d 项未通过：\n%s" % (len(FAILS), "\n".join(FAILS))


if __name__ == "__main__":
    for fn in (test_no_developer_vocabulary, test_stages_cover_all_rounds,
               test_tasks_reference_real_specs, test_money_and_state,
               test_friendly_error, test_help_prompt,
               test_no_price_estimate_in_user_text):
        fn()
    print("-" * 60)
    if FAILS:
        print("[FAIL] %d 项未通过" % len(FAILS))
        sys.exit(1)
    print("[OK] 用户语言层契约全部通过")
