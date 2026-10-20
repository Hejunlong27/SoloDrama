#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""test_script_design.py —— ④ 剧本改写「四段法」离线测试（零网络、零计费、零第三方依赖）

覆盖 2026-10-20 新增的三段能力：
  ① diagnose   A/B/C 诊断卡（预填不覆盖 / 必填校验 / 确认门禁）
  ② review     第二轮结构审查（注水·重复冲突·主角被动·反转不改格局·句库残留·题材必检升级）
  ③ audience   第四轮观众视角审稿（七问完整性 / 集号引用 / Q7 三条带改法）
  ④ 门禁       build --emit 在诊断未确认时返回退出码 4

用法：python test_script_design.py     （全绿退出码 0）
"""
from __future__ import annotations

import contextlib
import io
import json
import pathlib
import shutil
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))          # stages/creation/scripts
sys.path.insert(0, str(HERE))                 # tests

import _common as C  # noqa: E402
import script_rewrite as SR  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(cond), detail))


def _quiet(fn, *a, **kw):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn(*a, **kw)
    return rc, buf.getvalue()


def _wj(p, obj):
    pathlib.Path(p).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(p).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8", newline="")


CARD = {
    "rank": 1, "title": "她把股权带回了葬礼", "title_es": "Ella volvio con las acciones",
    "logline": "被扫地出门的创始人之女，在丈夫的葬礼上拿回公司",
    "conflict": "继母与丈夫家族合谋夺走公司，女主以专利为底牌反击",
    "genre_direction": "女频逆袭 · 复仇",
    "audience_profile": {"platform": "ReelShort", "market": "es-LATAM"},
    "differentiation_selling_points": ["专利战而非家斗"],
}


def mk_ws(tag: str) -> pathlib.Path:
    ws = pathlib.Path(tempfile.mkdtemp(prefix="s3design_%s_" % tag))
    _wj(C.pdir(ws, C.POSITIONING), {"selected": [CARD]})
    _wj(C.pdir(ws, C.BRIEF), {"slug": "demo", "title": CARD["title"],
                              "platform": "ReelShort", "ep_total": 12, "ep_seconds": 70})
    return ws


def fill_diag(ws):
    p = C.pdir(ws, C.DIAGNOSIS)
    d = json.loads(p.read_text(encoding="utf-8"))
    d["A_diagnosis"].update({
        "core_hook": "葬礼当天，被扫地出门的创始人之女拿着父亲留下的专利证书走进灵堂",
        "audience_emotion": "被至亲合谋夺走一切、还被当众说成废物时的憋屈与愤怒",
        "protagonist": {"desire": "拿回父亲公司的控股权与母亲留下的老宅",
                        "obstacle": "继母联合丈夫家族，用伪造的遗嘱把她清出局",
                        "cost_if_lose": "失去父亲毕生专利的署名权，母亲的老宅被抵押拍卖",
                        "counter_space": "父亲把核心专利的原始登记文件给了她，只有她知道证据在哪"},
        "power_gaps": ["身份差：众人以为她是弃女，实为唯一专利权利人"],
        "audience_expectation": "看她把伪造的遗嘱当众拆穿，让继母在同一个灵堂里低头",
        "hook_slots": {"opening": "灵堂门口被拦下，保安当众扯掉她的孝布",
                       "mid_climax": "股东会上她放出专利原始件，冻结继母表决权",
                       "ep_tail": "继母接起电话，说「那个人回来了」"},
        "risks": ["中段容易变成董事会开会，缺少当众羞辱的场面"],
        "unique_selling_point": "用专利战代替常规家斗，反击靠文件与时间线而非眼泪",
    })
    d["B_strategy"]["keep"] = [{"item": "灵堂当众受辱的开场", "why": "全剧情绪最集中的羞辱场景"}]
    d["B_strategy"]["changes"] = [{"type": "cut", "item": "前两章的童年回忆",
                                   "why": "铺垫式开场会丢掉前三集留存，回忆拆碎塞进冲突里说"}]
    d["C_mainline"].update({
        "start": "创始人之女在丈夫葬礼上被继母当众赶出家门，身无分文",
        "goal": "拿回父亲公司的控股权，并证明遗嘱是伪造的",
        "cost_or_change": "她拿回公司，但必须公开父亲当年的商业污点",
        "key_events": ["灵堂被赶出门", "发现专利原始登记件", "股东会冻结表决权",
                       "曝光伪造遗嘱的经办人"],
        "one_paragraph": ("被扫地出门的创始人之女在丈夫葬礼上被继母当众羞辱，只带走了父亲留下的一只旧公文包。"
                          "她从包里发现核心专利的原始登记文件，开始一级一级往上打：先在灵堂拆穿伪造遗嘱的"
                          "时间漏洞，再在股东会上冻结继母的表决权，最后把公司夺回。代价是她必须公开父亲当年"
                          "的商业污点，赢下公司却失去母亲的理解。"),
    })
    _wj(p, d)


GOOD_EPS = [
    ("灵堂门口保安当众扯掉她的孝布", "继母宣读伪造遗嘱，当场把她清出公司",
     "她亮出父亲公证过的专利登记编号，要求核验", "继母撕碎复印件，说原件三年前就烧了", "压抑"),
    ("她在殡仪馆储物间翻父亲的旧公文包", "丈夫家族冻结她的银行卡，逼她签放弃继承",
     "她设局让财务把冻结令的签发时间念出来", "财务低声说，签发人是她丈夫的弟弟", "压"),
    ("她带着公证处回执走进股东会", "继母以董事身份宣布她无表决权",
     "她当众拆穿表决权剥夺程序违法，会议被迫中止", "叔父递来纸条：老宅明天拍卖", "小爽"),
    ("拍卖行门口她拦住举牌人", "继母安排人抬价，逼她当场出局",
     "她亮出老宅抵押合同上的伪造签名，要求报警", "警察到场，继母突然叫出她的小名", "悬"),
    ("警局里她盯着抵押合同的日期", "继母反告她伪造证据，要求拘留",
     "她拿出银行流水的原始凭证，时间线指向继母", "继母的律师说，还有第三份遗嘱", "小爽"),
    ("她在父亲书房夹层找到第三份遗嘱", "叔父劝她别查，说会毁掉父亲名声",
     "她夺回被叔父拿走的遗嘱原件，当场封存", "遗嘱指定的见证人，是她母亲的旧友", "悬"),
    ("她去找母亲的旧友，对方闭门不见", "继母放出消息说她精神有问题，董事会要求体检",
     "她设局让体检报告在董事会上被当众宣读", "报告末尾多出一项她没做过的检查", "小爽"),
    ("她追查那份多出来的检查记录", "医院说记录被调走，经办人请假失联",
     "她亮出调阅日志，锁定调走记录的是丈夫的弟弟", "弟弟承认，但说他是替母亲做的", "悬"),
    ("股东会前一天，她被堵在地下车库", "继母用她母亲的病历要挟她退出",
     "她当众播放录音，把要挟变成证据", "录音里出现父亲的声音，说的不是遗嘱内容", "大爽"),
    ("她反复听那段录音，找到第二层音轨", "董事会临时改期，想趁她不在表决",
     "她设局让会议全程直播，观众成了见证者", "弹幕里有人认出父亲的声音不是本人", "小爽"),
    ("她带着音轨鉴定报告进会场", "继母抢先宣布表决结果，宣布她出局",
     "她当场播放鉴定结论，冻结全部表决票", "鉴定人补充：录音录制于父亲去世之后", "大爽"),
    ("她站在灵堂同一位置，手里是公证原件", "继母最后一次用母女关系求她收手",
     "她当众拆穿伪造遗嘱的全部经办环节，拿回控股权", "她转身对母亲说，爸的污点我替你公开", "燃"),
]


def mk_bp(ws, eps=None):
    eps = eps or GOOD_EPS
    rows = []
    for i, (co, cc, rv, hk, em) in enumerate(eps, 1):
        rows.append({
            "ep": i, "act": SR._act_of(i, len(eps)), "retention_role": "拉新攻坚",
            "cold_open": co, "core_conflict": cc, "reversal": rv,
            "hook_type": SR.HOOK_TYPES[(i - 1) % len(SR.HOOK_TYPES)], "hook": hk,
            "emotion": em, "boom": "mid" if i % 4 == 0 else "none",
            "beat_note": "常规推进", "from_outline": True,
        })
    _wj(C.pdir(ws, C.BLUEPRINT), {
        "generated_at": C.now_iso(), "title": CARD["title"], "total_ep": len(rows),
        "platform": "ReelShort", "style_lock": "x", "episodes": rows,
        "positioning_digest": {"genre_direction": CARD["genre_direction"]},
    })
    return rows


# ---------------------------------------------------------------------------
def test_profiles() -> None:
    p = SR.match_profile("女频逆袭 · 复仇")
    check("profile 匹配复仇逆袭", (p or {}).get("id") == "revenge", str((p or {}).get("id")))
    check("profile 匹配甜宠", (SR.match_profile("先婚后爱甜宠") or {}).get("id") == "sweet")
    check("profile 匹配悬疑", (SR.match_profile("失踪案悬疑推理") or {}).get("id") == "suspense")
    check("profile 匹配家庭伦理", (SR.match_profile("婆媳家庭伦理") or {}).get("id") == "family")
    check("profile 未命中返回 None", SR.match_profile("完全不相关的文本") is None)
    check("profile 四类齐全", len(SR.load_profiles()) >= 4)


def test_text_utils() -> None:
    check("_norm 去标点", SR._norm("她，走了！") == "她走了")
    check("_jac 同句为 1", SR._jac("她拿回股份", "她拿回股份") == 1.0)
    check("_jac 无关为 0", SR._jac("灵堂受辱", "股东会表决") < 0.2)
    # 「她的」属功能词，共享它不能当作因果关联证据
    check("_shared 剔除功能词", SR._shared("她的东西", "她的东西") == len(SR._grams("她的东西")) - 1,
          "shared=%d" % SR._shared("她的东西", "她的东西"))
    check("_shared 实义词可命中", SR._shared("她撕碎复印件", "她亮出原件并核验复印件") >= 1)


def test_diagnose() -> None:
    ws = mk_ws("diag")
    rc, out = _quiet(SR.diag_init, ws)
    p = C.pdir(ws, C.DIAGNOSIS)
    check("diagnose 生成诊断卡", rc == 0 and p.is_file(), out[-60:])
    d = json.loads(p.read_text(encoding="utf-8"))
    check("预填带入剧名", d.get("title") == CARD["title"])
    check("预填不带判断型字段", d["A_diagnosis"]["core_hook"] == "")
    check("预填识别题材侧重", d.get("genre_profile") == "revenge", str(d.get("genre_profile")))
    check("诊断卡 md 同步生成", C.pdir(ws, C.DIAGNOSIS_MD).is_file())

    rc, _ = _quiet(SR.diag_check, ws)
    check("空诊断卡校验不通过（退出码 2）", rc == 2, "rc=%d" % rc)
    rc, _ = _quiet(SR.diag_check, ws, True)
    check("空诊断卡不能 confirm", rc == 2, "rc=%d" % rc)

    # 补缺不覆盖
    d["A_diagnosis"]["core_hook"] = "已人工填写的一句核心卖点描述文字"
    _wj(p, d)
    _quiet(SR.diag_init, ws)
    d2 = json.loads(p.read_text(encoding="utf-8"))
    check("重复 init 不覆盖已填内容", d2["A_diagnosis"]["core_hook"].startswith("已人工填写"))

    fill_diag(ws)
    rc, out = _quiet(SR.diag_check, ws, True)
    check("填满后可 confirm", rc == 0, out[-80:])
    d3 = json.loads(p.read_text(encoding="utf-8"))
    check("confirm 写入 structure_confirmed", d3.get("structure_confirmed") is True)
    check("confirm 记录时间戳", bool(d3.get("confirmed_at")))

    # 缺 why 的改动应被拦
    bad = json.loads(p.read_text(encoding="utf-8"))
    bad["B_strategy"]["changes"] = [{"type": "cut", "item": "回忆", "why": "太慢"}]
    errs, _ = SR.validate_diagnosis(bad, SR.profile_by_id("revenge"))
    check("改动缺戏剧目的被拦", any("戏剧目的" in e for e in errs), str(errs[:2]))
    # 非法 type
    bad["B_strategy"]["changes"] = [{"type": "delete", "item": "回忆",
                                     "why": "铺垫式开场会丢掉前三集留存"}]
    errs, _ = SR.validate_diagnosis(bad, SR.profile_by_id("revenge"))
    check("改动 type 非法被拦", any("type=" in e for e in errs), str(errs[:2]))
    # risks 写「无」只告警
    bad["B_strategy"]["changes"] = [{"type": "cut", "item": "回忆",
                                     "why": "铺垫式开场会丢掉前三集留存"}]
    bad["A_diagnosis"]["risks"] = ["无"]
    errs, warns = SR.validate_diagnosis(bad, SR.profile_by_id("revenge"))
    check("风险写「无」不阻塞但告警", not any("risks" in e for e in errs)
          and any("无风险自评" in w for w in warns))
    shutil.rmtree(ws, ignore_errors=True)


def test_build_gate() -> None:
    ws = mk_ws("gate")
    mk_bp(ws)
    _quiet(SR.diag_init, ws)
    rc, out = _quiet(SR.build, ws, 1, 8, True, False)
    check("诊断未确认时写正文被拦（退出码 4）", rc == 4, out[-90:])
    fill_diag(ws)
    _quiet(SR.diag_check, ws, True)
    rc, out = _quiet(SR.build, ws, 1, 8, True, False)
    check("诊断确认后可写正文", rc == 0, out[-60:])
    check("正文骨架已落盘", C.pdir(ws, "script/ep_01.md").is_file())
    shutil.rmtree(ws, ignore_errors=True)


def test_review_good() -> None:
    ws = mk_ws("good")
    mk_bp(ws)
    rc, out = _quiet(SR.review, ws, None, True)
    check("差异化大纲通过结构审查", rc == 0, out[-200:])
    check("审查报告落盘", C.pdir(ws, C.STRUCTURE_REVIEW).is_file())
    shutil.rmtree(ws, ignore_errors=True)


def test_review_watered() -> None:
    ws = mk_ws("water")
    # 12 集全是同一句冲突、同样被动反转 → 注水 + 主角被动
    eps = [("她在家门口站着", "继母当众羞辱她，抢走她的包", "她被赶出家门，只能住在旅馆",
            "继母说要她好看", "压抑")] * 12
    mk_bp(ws, eps)
    rc, out = _quiet(SR.review, ws)
    check("注水大纲被拦（退出码 2）", rc == 2, out[-120:])
    check("检出冲突重复", "冲突是否在推进" in out and "[FAIL]" in out)
    check("检出主角零主动", "主角是否主动" in out)
    check("检出情绪机械轮转或同质", "情绪" in out)
    shutil.rmtree(ws, ignore_errors=True)


def test_review_must_check_upgrade() -> None:
    ws = mk_ws("must")
    # 12 集里只有 2 集主动（17% < 30% → WARN），复仇题材把它列为必检 → 应升为 FAIL
    eps = []
    for i in range(1, 13):
        if i in (5, 10):
            eps.append(("她把证据拍在桌上", "继母否认伪造", "她亮出鉴定报告和录音",
                        "继母第一次沉默", "大爽"))
        else:
            eps.append(("她坐在公司门口等", "继母当面羞辱她并叫保安", "她被架出去，只能在雨里等",
                        "玻璃门在她面前关上", "压抑"))
    mk_bp(ws, eps)
    rc, out = _quiet(SR.review, ws, "revenge")
    check("必检项把 WARN 升为 FAIL", rc == 2 and "必检项" in out, out[-200:])
    shutil.rmtree(ws, ignore_errors=True)


def test_review_residue() -> None:
    ws = mk_ws("residue")
    # 句库原样 + 情绪轮转 → 应报句库残留，且把「表面 OK」降级为待复核
    rows = []
    for i in range(1, 13):
        rows.append({"ep": i, "act": SR._act_of(i, 12), "retention_role": "拉新攻坚",
                     "cold_open": SR.COLD_OPEN_BANK["拉新攻坚"][(i - 1) % 3],
                     "core_conflict": "%s：%s" % (SR.CONFLICT_BANK["起"][0], "主线对抗"),
                     "reversal": "看似劣势实为伏笔",
                     "hook_type": SR.HOOK_TYPES[(i - 1) % 7],
                     "hook": "揭出主角身世/血脉的一角，但未说全（主线钩子）",
                     "emotion": SR.EMOTION_CYCLE[(i - 1) % 8], "boom": "none",
                     "beat_note": "常规推进"})
    _wj(C.pdir(ws, C.BLUEPRINT), {"title": CARD["title"], "total_ep": 12, "episodes": rows,
                                  "positioning_digest": {"genre_direction": "复仇"}})
    rc, out = _quiet(SR.review, ws)
    check("检出句库残留", "句库" in out, out[-120:])
    check("残留时把 OK 降级为人工复核", "需人工复核" in out)
    check("残留或重复导致不通过", rc == 2, "rc=%d" % rc)
    shutil.rmtree(ws, ignore_errors=True)


def test_audience() -> None:
    ws = mk_ws("aud")
    mk_bp(ws)
    rc, _ = _quiet(SR.audience, ws)
    check("audience 生成模板", rc == 0 and C.pdir(ws, C.AUDIENCE_REVIEW).is_file())
    rc, out = _quiet(SR.audience, ws, True, False)
    check("空审稿不通过（退出码 2）", rc == 2, "rc=%d" % rc)
    check("空审稿报 Q1 未答", "Q1" in out)

    body = "\n".join(
        ["# 观众视角审稿", "",
         "## Q1 观众最可能在哪一段失去兴趣？为什么？", "",
         "EP06 到 EP08 连续三集都在追一份文件，主角始终在解释文件被谁拿走，观众看到的是流程而不是对抗，"
         "现场也没有对手，情绪落空，若不放一场当众对峙，观众会在 EP07 弃剧。", "",
         "## Q2 哪个情节最值得期待？是否出现得太晚？", "",
         "最值得期待的是 EP11 股东会上当众播放音轨鉴定并冻结表决票，但它出现在第 11 集，前 10 集只有零散证据，"
         "观众要等太久才能看到一次真正的翻盘，建议把录音提前到 EP05 收尾。", "",
         "## Q3 哪个冲突看起来像作者刻意安排，而不是人物自然选择？", "",
         "EP04 拍卖行抬价那场是刻意安排，继母本可以不露面就让拍卖流拍，却偏要到场加价并被警察带走，"
         "行为动机不足，应改成她派律师到场、自己躲在车里，主角把传票贴到车窗上。", "",
         "## Q4 哪个反转缺乏铺垫，或删掉也不影响故事？", "",
         "EP08 弟弟承认替母亲做事缺乏铺垫，前七集没有给过他犹豫或愧疚的细节，删掉也不影响主线，"
         "因为 EP09 的录音已经把矛头指向继母，建议在 EP03 递纸条时就埋下动摇的伏笔。", "",
         "## Q5 哪个爽点/虐点/情感回报不够充分？", "",
         "EP12 拿回控股权不够充分，她只是宣读鉴定结论，没有让继母在同一批见证者面前亲口承认伪造，"
         "观众等了十二集，需要继母当众失语、叔父倒戈、母亲开口三个反应镜头。", "",
         "## Q6 观众看完每集后，有什么具体理由继续追？", "",
         "每集结尾都留了一个具体物件或身份的悬念，观众追的是这个东西到底在哪、是谁做的，而不是抽象的命运感。", "",
         "## Q7 当前最需要优先修改的三个问题是什么？", "",
         "1. EP06-EP08 —— 问题：三集都在追文件没有当众对抗。改法：把 EP07 的体检自证改成在董事会上当众宣读。",
         "2. EP11 —— 问题：最大的翻盘来得太晚。改法：把音轨发现前移到 EP05 收尾。",
         "3. EP12 —— 问题：爽点缺反应镜头。改法：补继母失语、叔父倒戈、母亲开口三个反应。", ""])
    p = C.pdir(ws, C.AUDIENCE_REVIEW)
    p.write_text(body, encoding="utf-8", newline="")
    rc, out = _quiet(SR.audience, ws, True, False)
    check("完整审稿通过", rc == 0, out[-120:])

    # Q7 少一条
    p.write_text(body.replace("3. EP12 —— 问题：爽点缺反应镜头。改法：补继母失语、叔父倒戈、母亲开口三个反应。\n", ""),
                 encoding="utf-8", newline="")
    rc, out = _quiet(SR.audience, ws, True, False)
    check("Q7 不足 3 条被拦", rc == 2 and "恰好 3 条" in out, out[-100:])

    # 笼统评价（无集号）
    vague = body.replace("EP06 到 EP08", "中段").replace("EP11", "后面").replace("EP04", "中间") \
                .replace("EP08", "某集").replace("EP12", "结尾").replace("EP07", "那集") \
                .replace("EP09", "后面").replace("EP03", "前面").replace("EP05", "中段")
    p.write_text(vague, encoding="utf-8", newline="")
    rc, out = _quiet(SR.audience, ws, True, False)
    check("笼统评价（缺集号）被拦", rc == 2, out[-120:])
    shutil.rmtree(ws, ignore_errors=True)


def test_outline_emotion_column() -> None:
    p = pathlib.Path(tempfile.mkdtemp(prefix="s3outline_")) / "outline.md"
    p.write_text("EP01 | 灵堂被扯掉孝布 | 继母宣读伪造遗嘱 | 她亮出专利登记编号 | 说原件三年前烧了 | 压抑\n"
                 "EP02 | 她翻父亲的公文包 | 家族冻结她的卡 | 她设局让财务念出签发时间 | 签发人是弟弟 | 悬\n",
                 encoding="utf-8", newline="")
    rows, warns = SR.parse_outline(p)
    check("拆解表解析两集", len(rows) == 2 and not warns, str(warns))
    check("第 5 列写入 emotion", rows.get(1, {}).get("emotion") == "压抑", str(rows.get(1)))
    check("第 4 列写 hook", rows.get(2, {}).get("hook") == "签发人是弟弟", str(rows.get(2)))
    shutil.rmtree(p.parent, ignore_errors=True)


def main() -> int:
    for fn in (test_profiles, test_text_utils, test_diagnose, test_build_gate,
               test_review_good, test_review_watered, test_review_must_check_upgrade,
               test_review_residue, test_audience, test_outline_emotion_column):
        try:
            fn()
        except Exception as e:                                    # noqa: BLE001
            check("%s 抛异常" % fn.__name__, False, repr(e))
    ok = sum(1 for _, c, _ in RESULTS if c)
    for name, cond, detail in RESULTS:
        if not cond:
            print("[FAIL] %s%s" % (name, ("｜" + detail) if detail else ""))
    print("\n%s  %d/%d 通过" % ("[OK]" if ok == len(RESULTS) else "[NG]", ok, len(RESULTS)))
    return 0 if ok == len(RESULTS) else 1


if __name__ == "__main__":
    C.harden_stdio()
    sys.exit(main())
