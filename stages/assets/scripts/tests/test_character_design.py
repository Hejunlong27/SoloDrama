# -*- coding: utf-8 -*-
"""`character_design.py` 离线测试 —— **零网络、零计费、零第三方依赖**。

V2（3 项签名）之后覆盖五层：

* **A 词库**：条目齐全 / id 唯一 / 色相槽间隔 / 旧表已删 / 词库自身不含美颜词
* **B 分配**：确定性 / seed 派生 / 锚唯一 / 发型不撞 / 色相与明度 / overrides 优先 / 三项齐全
* **C 提示词**：三件套段位 / 真人卡版式 / 锚可见度分级 / 净化器 0 / 模板向后兼容 / 英文服装段
* **D 集成**：资产提示词 md 能被 `asset_md.py` 吃下 / 落盘齐全 / 卡长收敛
* **E 校验**：四条规则能抓出注入的色相撞 / 重锚 / 美颜词；`audit` 能抓出老项目重复

```bash
python tests/test_character_design.py            # 全部
python tests/test_character_design.py --group B  # 只跑某组
```
"""
import argparse
import contextlib
import io
import json
import os
import pathlib
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
sys.path.insert(0, SCRIPTS)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import character_design as CD      # noqa: E402
import prompt_templates as T       # noqa: E402
import sanitize as S               # noqa: E402
import asset_md as A               # noqa: E402

CASES = []


def reg(group, name):
    def deco(fn):
        CASES.append((group, name, fn))
        return fn
    return deco


def A_(cond, msg=""):
    if not cond:
        raise AssertionError(msg or "断言失败")


def roster(n=6, region="east_asian", world="当代韩国首尔·财阀高中", seed="test"):
    """造一份 n 人名册：主演 + 配角 + 群演，覆盖不同性别/年龄/阵营。"""
    people = [
        {"name": "楚湘", "gender": "f", "age": 18, "tier": "lead", "identity": "转校生",
         "faction": "外来者", "code": "CHU"},
        {"name": "申雅莱", "gender": "f", "age": 18, "tier": "support", "identity": "财阀大小姐",
         "faction": "财阀", "code": "SHIN"},
        {"name": "具承贤", "gender": "m", "age": 19, "tier": "support", "identity": "财阀太子爷",
         "faction": "财阀", "code": "GU"},
        {"name": "教导主任", "gender": "m", "age": 52, "tier": "minor", "identity": "教导主任",
         "faction": "学校", "code": "DEAN"},
        {"name": "朴婶", "gender": "f", "age": 61, "tier": "minor", "identity": "食堂保姆",
         "faction": "市井", "code": "PARK"},
        {"name": "金室长", "gender": "m", "age": 34, "tier": "support", "identity": "理事长秘书",
         "faction": "财阀", "code": "KIM"},
    ]
    return {"world": world, "region": region, "seed": seed, "characters": people[:n]}


# =========================================================================== A 词库
@reg("A", "A01 词库条数与 id 唯一")
def _():
    for name, lib in (("发型", CD.HAIR), ("色签名", CD.PALETTE), ("识别锚", CD.ANCHOR)):
        ids = [x["id"] for x in lib]
        A_(len(ids) == len(set(ids)), "%s id 重复" % name)
    A_(len(CD.HAIR) >= 12, "发型不足 12 种")
    A_(len(CD.ANCHOR) >= 12, "识别锚不足 12 个")
    A_(len(CD.PALETTE) >= 10, "色签名不足 10 种")
    return "%d 发型 / %d 色 / %d 锚" % (len(CD.HAIR), len(CD.PALETTE), len(CD.ANCHOR))


@reg("A", "A02 七维骨相那套表已彻底删除")
def _():
    # 这四张表是 2026-11-01 砍掉的：骨相 7 槽 / 体态 / 人群桶 / 织物轮转。
    # 留着任何一张，说明「7 维」的残骸还能被别的代码 import 到，等于没拆干净。
    for attr in ("FACE_GEOM", "SLOTS", "POSTURE", "PERSONA", "FABRIC",
                 "WEALTH_TIERS", "_bucket", "_face_distance"):
        A_(not hasattr(CD, attr), "已删的 %s 仍然存在" % attr)
    return "8 个符号全部不存在"


@reg("A", "A03 色相槽：有彩色相邻间隔 ≥ 30°")
def _():
    chroma = sorted((p for p in CD.PALETTE if p["s"] >= CD.NEUTRAL_S), key=lambda x: x["h"])
    gaps = [CD._hue_gap(chroma[i]["h"], chroma[(i + 1) % len(chroma)]["h"]) for i in range(len(chroma))]
    A_(min(gaps) >= 30, "最小间隔 %.1f° < 30°（%s）" % (min(gaps), [p["name"] for p in chroma]))
    return "最小 %.0f°" % min(gaps)


@reg("A", "A04 发型覆盖两性与各年龄段")
def _():
    for g in ("f", "m"):
        pool = [h for h in CD.HAIR if h["gender"] == g]
        A_(len(pool) >= 5, "%s 的发型不足 5 种" % g)
    for age in (18, 34, 52, 61):
        pool = [h for h in CD.HAIR if h["age"][0] <= age <= h["age"][1]]
        A_(pool, "%d 岁没有可用发型" % age)
    return "女 %d / 男 %d 种" % (len([h for h in CD.HAIR if h["gender"] == "f"]),
                                len([h for h in CD.HAIR if h["gender"] == "m"]))


@reg("A", "A05 SKIN 覆盖 0–200 岁无空洞")
def _():
    for age in (0, 22, 23, 32, 33, 45, 46, 60, 61, 90, 200):
        A_(CD._skin(age), "%d 岁没有皮肤描述" % age)
    return "%d 档" % len(CD.SKIN)


@reg("A", "A06 词库本身不含评价性美颜词")
def _():
    blob = json.dumps({"hair": CD.HAIR, "anchor": CD.ANCHOR, "skin": CD.SKIN,
                       "tmpl": {"|".join(str(x) for x in k): v for k, v in CD.GARMENT_TMPL.items()},
                       "accent": CD.ACCENT_CN},
                      ensure_ascii=False)
    hit = [w for w in CD.BANNED_WORDS if w in blob]
    A_(not hit, "词库含美颜词：%s" % hit)
    return "0 命中（禁词 %d 条）" % len(CD.BANNED_WORDS)


# =========================================================================== B 分配
@reg("B", "B01 确定性：同输入同输出")
def _():
    a = CD.design(roster())
    b = CD.design(roster())
    A_(json.dumps(a, ensure_ascii=False) == json.dumps(b, ensure_ascii=False), "两次结果不同")
    return "逐字节相同"


@reg("B", "B02 无 seed 时按名册内容派生，两部剧必不相同")
def _():
    r1 = roster(seed="")
    r2 = roster(seed="")
    r2["world"] = "当代美国中西部·医院并购"
    r2["characters"][0]["name"] = "Eleanor"
    b1, b2 = CD.design(r1), CD.design(r2)
    A_(b1["seed"].startswith("auto-"), "未派生 seed：%s" % b1["seed"])
    A_(b1["seed"] != b2["seed"], "两部剧拿到同一个 seed")
    return "%s ≠ %s" % (b1["seed"], b2["seed"])


@reg("B", "B03 识别锚全局唯一或显式不设")
def _():
    b = CD.design(roster())
    ids = [(c.get("anchor") or {}).get("id") for c in b["characters"]]
    real = [x for x in ids if x]
    A_(len(real) == len(set(real)), "锚重复：%s" % real)
    # 显式 none 必须得到空锚，且不生成句子
    r = roster()
    r["characters"][0]["overrides"] = {"anchor": "none"}
    b2 = CD.design(r)
    c0 = b2["characters"][0]
    A_(not (c0.get("anchor") or {}).get("text"), "写 none 却仍分配了锚")
    A_(not CD.to_fields(c0)["识别锚"], "空锚仍生成了句子")
    return "%d 人 %d 个锚，空锚可用" % (len(b["characters"]), len(real))


@reg("B", "B04 主演发型不与其他人重复（自动分配时）")
def _():
    b = CD.design(roster())
    leads = [c for c in b["characters"] if c["tier"] == "lead"]
    A_(leads, "没有主演")
    for ld in leads:
        clash = [c["name"] for c in b["characters"]
                 if c is not ld and c["hair"]["id"] == ld["hair"]["id"]]
        A_(not clash, "主演 %s 与 %s 撞发型（%s）" % (ld["name"], clash, ld["hair"]["name"]))
    return "主演 %d 人全部唯一" % len(leads)


@reg("B", "B05 不同阵营色相间隔 ≥ 30°")
def _():
    b = CD.design(roster())
    pairs = b["_matrix"]["pairs"]
    bad = [p for p in pairs if not p["same_faction"] and p["hue_gap"] < 30]
    A_(not bad, "色相过近：%s" % [(p["a"], p["b"], p["hue_gap"]) for p in bad])
    return "跨阵营 %d 对全部 ≥30°" % len([p for p in pairs if not p["same_faction"]])


@reg("B", "B06 同阵营：色名可同，但 hex 与明度必须分开")
def _():
    b = CD.design(roster())
    by = {}
    for c in b["characters"]:
        by.setdefault(c["faction"], []).append(c)
    checked = 0
    for fac, members in by.items():
        if len(members) < 2:
            continue
        hexes = [m["color"]["hex"] for m in members]
        A_(len(hexes) == len(set(hexes)), "%s 阵营 hex 全同：%s" % (fac, hexes))
        ls = [m["color"]["l"] for m in members]
        A_(len(ls) == len(set(ls)) or len(ls) > 5, "%s 阵营明度全同：%s" % (fac, ls))
        checked += 1
    A_(checked >= 1, "没有可校验的多成员阵营")
    return "%d 个阵营内部已分层" % checked


@reg("B", "B07 overrides 优先，且未知发型不被丢弃")
def _():
    r = roster()
    r["characters"][0]["overrides"] = {"hair": "齐耳内扣短发", "expression": "咬着牙笑"}
    b = CD.design(r)
    c = b["characters"][0]
    A_(c["hair"]["name"] == "齐耳内扣短发", "没听 overrides.hair：%s" % c["hair"]["name"])
    A_("咬着牙" in c["expression"], "没听 overrides.expression：%s" % c["expression"])
    # 名册写了个表里没有的发型：要原样保留（写死的是作者的意图，不是我们的词库）
    r2 = roster()
    r2["characters"][1]["overrides"] = {"hair": "脏辫"}
    b2 = CD.design(r2)
    A_(b2["characters"][1]["hair"]["name"] == "脏辫", "表外发型被丢弃")
    return "hair/expression/表外值 三处生效"


@reg("B", "B08 三项签名齐全，且不含已删的维度")
def _():
    b = CD.design(roster())
    banned = ("face", "posture", "persona", "persona_bucket", "fabric", "face_short")
    for c in b["characters"]:
        for k in ("code", "name", "age", "gender", "identity", "faction", "region"):
            A_(k in c, "%s 缺身份项 %s" % (c["name"], k))
        for k in ("color", "hair", "garment", "garment_en"):
            A_(c.get(k), "%s 缺造型项 %s" % (c["name"], k))
        A_("anchor" in c, "%s 缺 anchor 键（可为空但不能没有）" % c["name"])
        hit = [k for k in banned if k in c]
        A_(not hit, "%s 仍带已删维度：%s" % (c["name"], hit))
    A_(b["lib_version"].startswith("2."), "lib_version 未升级：%s" % b["lib_version"])
    return "3 项齐全 / 已删维度 0 残留"


# =========================================================================== C 提示词
@reg("C", "C01 三件套段位齐全（3D 轨）")
def _():
    b = CD.design(roster())
    f = CD.to_fields(b["characters"][0], b["style_anchor"])
    for k in ("形象定位", "发型", "皮肤质感", "表情", "服装细节", "服装细节EN",
              "识别锚", "差异对照", "反默认"):
        A_(k in f, "缺字段 %s" % k)
    for fn in (CD.board_prompt, CD.maincard_prompt, CD.headshot_prompt):
        txt = fn(b["characters"][0], f, b["world"], b["style_anchor"])
        A_(len(txt) >= 200, "%s 过短（%d 字）" % (fn.__name__, len(txt)))
    return "9 字段 / 3 版式"


@reg("C", "C02 真人卡是 16:9 且不再写骨相七槽")
def _():
    b = CD.design(roster())
    c = b["characters"][0]
    f = CD.to_fields(c, b["style_anchor"])
    txt = CD.live_card_prompt(c, f, b["world"], b["style_anchor"])
    A_("16:9" in txt, "真人卡没写 16:9")
    A_("三视图" in txt, "真人卡缺三视图版式")
    A_("【骨相与五官】" not in txt, "真人卡仍在写骨相七槽")
    for slot in CD.__dict__.get("SLOTS", ()):
        A_(slot not in txt, "真人卡出现骨相槽位「%s」" % slot)
    return "%d 字 / 无骨相段" % len(txt)


@reg("C", "C03 锚可见度按类型分级（饰 vs 疤）")
def _():
    b = CD.design(roster())
    c = dict(b["characters"][0])
    c["anchor"] = {"id": "A04", "name": "素银印章戒", "text": "左手中指一枚素银印章戒", "kind": "饰"}
    s_loud = CD._anchor_sentence(c, "左手中指一枚素银印章戒")
    A_("必须清晰可见" in s_loud, "饰物类锚没要求清晰可见")
    c["anchor"] = {"id": "A02", "name": "眉尾旧疤", "text": "右眉尾一道浅白旧疤", "kind": "疤"}
    s_soft = CD._anchor_sentence(c, "右眉尾一道浅白旧疤")
    A_("按它本身的尺寸与淡度" in s_soft, "疤痕类锚没要求按原样呈现")
    A_("必须清晰可见" not in s_soft, "疤痕类锚仍写「必须清晰可见」——会把浅疤放大成伤")
    # 空锚 → 整段省略
    A_(CD._anchor_sentence(c, "") == "", "空锚没被省略")
    return "饰=显 / 疤=淡 / 空=省略"


@reg("C", "C04 净化器三项自检 0")
def _():
    b = CD.design(roster())
    for c in b["characters"]:
        f = CD.to_fields(c, b["style_anchor"])
        txt = CD.maincard_prompt(c, f, b["world"])
        res = S.check_all(txt) if hasattr(S, "check_all") else {"hit": []}
        A_(not res.get("hit"), "%s 命中净化器：%s" % (c["name"], res.get("hit")))
    return "%d 人 0 命中" % len(b["characters"])


@reg("C", "C05 build_char 向后兼容：design=None 时行为不变")
def _():
    item = {"kind": "char", "id": "CH01", "title": "测试", "fields": {"形象": "x"}, "raw": ""}
    a = T.build_char(item)
    b = T.build_char(item, design=None)
    A_(a == b, "design=None 改变了输出")
    A_(len(a) > 50, "输出过短")
    return "%d 字" % len(a)


@reg("C", "C06 英文服装段必填且不含中文")
def _():
    b = CD.design(roster())
    for c in b["characters"]:
        en = c.get("garment_en") or ""
        A_(en, "%s 缺 garment_en" % c["name"])
        A_(not re.search(r"[\u4e00-\u9fff]", en), "%s 的 garment_en 含中文：%s" % (c["name"], en))
        A_(len(en) >= 30, "%s 的 garment_en 过短" % c["name"])
    return "%d 人全 ASCII" % len(b["characters"])


# =========================================================================== D 集成
@reg("D", "D01 资产提示词 md 能被 asset_md.py 解析出全部角色")
def _():
    b = CD.design(roster())
    d = tempfile.mkdtemp(prefix="cd_d1_")
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            CD.emit(b, pathlib.Path(d))
        md = pathlib.Path(d) / "资产提示词_角色段.md"
        A_(md.is_file(), "没写出资产提示词 md")
        text = md.read_text(encoding="utf-8")
        secs = re.findall(r"^## \d+\. (.+?)（", text, re.M)
        A_(len(secs) == len(b["characters"]), "解析出 %d 节，应为 %d" % (len(secs), len(b["characters"])))
        parsed = A.parse(text) if hasattr(A, "parse") else None
        A_(parsed is None or len(parsed) >= len(b["characters"]), "asset_md.parse 解析不全")
        return "%d 节" % len(secs)
    finally:
        shutil.rmtree(d, ignore_errors=True)


@reg("D", "D02 落盘产物齐全且全为 LF（无 CR）")
def _():
    b = CD.design(roster())
    d = tempfile.mkdtemp(prefix="cd_d2_")
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            res = CD.emit(b, pathlib.Path(d), card_style="live_action")
        need = ("character-bible.json", "角色差异化矩阵.md", "资产提示词_角色段.md")
        for n in need:
            A_((pathlib.Path(d) / n).is_file(), "缺 %s" % n)
        files = [p for p in pathlib.Path(d).rglob("*") if p.is_file()]
        A_(len(files) >= 6, "文件数过少：%d" % len(files))
        for p in files:
            raw = p.read_bytes()
            A_(b"\r" not in raw, "%s 含 CRLF" % p.name)
        return "%d 个文件全 LF" % len(files)
    finally:
        shutil.rmtree(d, ignore_errors=True)


@reg("D", "D03 卡长收敛：单人卡 ≤ 1600 字（旧版 2000+）")
def _():
    b = CD.design(roster())
    worst = 0
    for c in b["characters"]:
        f = CD.to_fields(c, b["style_anchor"])
        for fn in (CD.board_prompt, CD.maincard_prompt, CD.live_card_prompt):
            n = len(fn(c, f, b["world"], b["style_anchor"]))
            worst = max(worst, n)
    A_(worst <= 1600, "最长一张卡 %d 字，超过 1600" % worst)
    return "最长 %d 字" % worst


# =========================================================================== E 校验
@reg("E", "E01 正常圣经通过四条规则")
def _():
    b = CD.design(roster())
    issues = CD.check_rules(b)
    A_(not [x for x in issues if x[0] == "hard"], "正常名册报了硬失败：%s" % issues)
    return "%d warn" % len(issues)


@reg("E", "E02 注入色相撞 → R1 报硬失败")
def _():
    b = CD.design(roster())
    # 把两个不同阵营的角色强行改成同色相
    a, c = b["characters"][0], b["characters"][1]
    A_(a["faction"] != c["faction"], "取样两人恰好同阵营，换一组")
    c["faction"] = "另一个阵营"
    c["color"] = dict(a["color"])
    b["_matrix"] = CD.matrix(b)
    hit = [x for x in CD.check_rules(b) if x[1] == "R1"]
    A_(hit, "色相撞了却没报 R1")
    return hit[0][2][:40]


@reg("E", "E03 注入重复锚 + 美颜词 → R2/R4")
def _():
    b = CD.design(roster())
    b["characters"][1]["anchor"] = dict(b["characters"][0]["anchor"])
    b["characters"][2]["expression"] = "绝美的面容，气质出众"
    b["_matrix"] = CD.matrix(b)
    codes = {x[1] for x in CD.check_rules(b)}
    A_("R2" in codes, "重锚没报 R2：%s" % codes)
    A_("R4" in codes, "美颜词没报 R4：%s" % codes)
    return "R2 + R4"


@reg("E", "E04 check 子命令退出码：通过 0 / 不过 2")
def _():
    b = CD.design(roster())
    d = tempfile.mkdtemp(prefix="cd_e4_")
    try:
        ok = pathlib.Path(d) / "ok.json"
        ok.write_text(json.dumps(b, ensure_ascii=False), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            code_ok = CD.main(["check", "--bible", str(ok)])
        A_(code_ok == 0, "正常圣经退出码 %d ≠ 0" % code_ok)

        b["characters"][1]["anchor"] = dict(b["characters"][0]["anchor"])
        b["_matrix"] = CD.matrix(b)
        bad = pathlib.Path(d) / "bad.json"
        bad.write_text(json.dumps(b, ensure_ascii=False), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            code_bad = CD.main(["check", "--bible", str(bad)])
        A_(code_bad == 2, "不过的圣经退出码 %d ≠ 2" % code_bad)
        return "0 / 2"
    finally:
        shutil.rmtree(d, ignore_errors=True)


@reg("E", "E05 audit 抓出「同一张脸写三遍」且不误报")
def _():
    d = tempfile.mkdtemp(prefix="cd_e5_")
    try:
        p = pathlib.Path(d) / "资产提示词.md"
        p.write_text("""# 一、角色资产库

## 1. 甲
黑色短发，柳叶眉，杏眼，穿黑色西装。
## 2. 乙
黑色短发，柳叶眉，杏眼，穿黑色西装。
## 3. 丙
黑色短发，柳叶眉，杏眼，穿黑色西装。
""", encoding="utf-8")
        rep = CD.audit_md(p)
        A_(rep["conflicts"], "三个一样的角色没报冲突")
        A_(len(rep["no_anchor"]) == 3, "缺锚计数不对：%s" % rep["no_anchor"])

        p2 = pathlib.Path(d) / "好.md"
        p2.write_text("""# 一、角色资产库

## 1. 甲
高蓬松马尾，剑眉，丹凤眼，穿朱砂色西装，左眼角下方一颗泪痣。
## 2. 乙
低盘髻，平眉，圆眼，穿松柏墨绿长裙，右手腕一圈编织绳，左手虎口一处烫伤旧痕。
""", encoding="utf-8")
        rep2 = CD.audit_md(p2)
        A_(not rep2["conflicts"], "不该报冲突：%s" % rep2["conflicts"])
        A_(not rep2["no_anchor"], "不该报缺锚：%s" % rep2["no_anchor"])
        return "冲突 3 组 / 误报 0"
    finally:
        shutil.rmtree(d, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", default="")
    args = ap.parse_args()
    groups = [args.group.upper()] if args.group else ["A", "B", "C", "D", "E"]
    passed = failed = 0
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
            except Exception as e:                      # noqa: BLE001
                print("  [ERR ] %-52s %s: %s" % (name, type(e).__name__, e))
                failed += 1
        print()
    print("=" * 84)
    print("合计 %d 例 ｜ 通过 %d ｜ 失败 %d" % (passed + failed, passed, failed))
    print("=" * 84)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
