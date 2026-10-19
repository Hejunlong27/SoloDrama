# -*- coding: utf-8 -*-
"""`character_design.py` 离线测试 —— **零网络、零计费、零第三方依赖**。

覆盖四层：
* **A 词库**：条目齐全 / id 唯一 / 色相槽间隔 / 词库自身不含评价性美颜词
* **B 分配**：确定性 / 不撞脸 / 主角最小距离 / 锚点唯一 / 发型不重复 / 色相与明度 / 性别与年龄适配
* **C 提示词**：三件套段位 / 反默认注入 / 净化器三项自检 0 / 模板向后兼容
* **D 集成**：`资产提示词_角色段.md` 能被 `asset_md.py` 与 `gen_char_assets.py` 的解析口径吃下
* **E 校验**：`check` 六条硬规则能抓出注入的撞脸 / 重锚 / 美颜词；`audit` 能抓出老项目重复

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


def roster(n=6, region="east_asian", world="当代韩国首尔·财阀高中"):
    """造一份 n 人名册：主演 + 配角 + 群演，覆盖不同性别/年龄/阵营/人群桶。"""
    people = [
        {"name": "楚湘", "gender": "f", "age": 18, "tier": "lead", "identity": "转校生",
         "faction": "外来者", "persona": ["野性", "不驯"]},
        {"name": "申雅莱", "gender": "f", "age": 18, "tier": "support", "identity": "财阀大小姐",
         "faction": "财阀", "persona": ["心机", "傲慢"]},
        {"name": "具承贤", "gender": "m", "age": 19, "tier": "support", "identity": "财阀太子爷",
         "faction": "财阀", "persona": ["疏离", "病弱"]},
        {"name": "教导主任", "gender": "m", "age": 52, "tier": "minor", "identity": "教导主任",
         "faction": "学校", "persona": ["强势", "势利"]},
        {"name": "朴婶", "gender": "f", "age": 61, "tier": "minor", "identity": "食堂保姆",
         "faction": "市井", "persona": ["市井", "嘴碎"]},
        {"name": "金室长", "gender": "m", "age": 34, "tier": "support", "identity": "理事长秘书",
         "faction": "财阀", "persona": ["冷面", "执行"]},
    ]
    return {"world": world, "region": region, "seed": "test", "characters": people[:n]}


# =========================================================================== A 词库
@reg("A", "A01 词库条数与 id 唯一")
def _():
    for name, lib in (("骨相", CD.FACE_GEOM), ("发型", CD.HAIR), ("面料", CD.FABRIC),
                      ("色签名", CD.PALETTE), ("识别锚", CD.ANCHOR), ("体态", CD.POSTURE)):
        ids = [x["id"] for x in lib]
        A_(len(ids) == len(set(ids)), "%s id 重复" % name)
    A_(len(CD.FACE_GEOM) >= 12, "骨相档案不足 12 种")
    A_(len(CD.ANCHOR) >= 20, "识别锚不足 20 个")
    A_(len(CD.PERSONA) >= 8, "人群桶不足 8 类")
    return "%d/%d/%d/%d/%d/%d" % (len(CD.FACE_GEOM), len(CD.HAIR), len(CD.FABRIC),
                                  len(CD.PALETTE), len(CD.ANCHOR), len(CD.POSTURE))


@reg("A", "A02 骨相七槽齐全且非空")
def _():
    for f in CD.FACE_GEOM:
        for k in CD.SLOTS:
            A_(f["slots"].get(k), "%s 缺槽 %s" % (f["id"], k))
        A_(len(f["detail"]) >= 40, "%s 骨相描述过短" % f["id"])
    return "%d 条 × 7 槽" % len(CD.FACE_GEOM)


@reg("A", "A03 色相槽：有彩色相邻间隔 ≥ 30°")
def _():
    chroma = sorted((p for p in CD.PALETTE if p["s"] >= CD.NEUTRAL_S), key=lambda x: x["h"])
    gaps = [CD._hue_gap(chroma[i]["h"], chroma[(i + 1) % len(chroma)]["h"]) for i in range(len(chroma))]
    A_(min(gaps) >= 30, "最小间隔 %.1f° < 30°（%s）" % (min(gaps), [p["name"] for p in chroma]))
    return "最小 %.0f°" % min(gaps)


@reg("A", "A04 词库与人群桶不含评价性美颜词（R6 自洽）")
def _():
    blob = json.dumps([CD.FACE_GEOM, CD.HAIR, CD.FABRIC, CD.PERSONA], ensure_ascii=False)
    hit = [w for w in CD.BANNED_WORDS if w in blob]
    A_(not hit, "词库自带美颜词：%s" % hit)
    return "0 命中"


# =========================================================================== B 分配
@reg("B", "B01 确定性：同名册两次设计完全一致")
def _():
    a = CD.design(roster())
    b = CD.design(roster())
    A_(json.dumps(a, ensure_ascii=False, sort_keys=True) ==
       json.dumps(b, ensure_ascii=False, sort_keys=True), "两次结果不一致")
    return "字节一致"


@reg("B", "B02 六人骨相档案互不相同")
def _():
    b = CD.design(roster())
    ids = [c["face"]["id"] for c in b["characters"]]
    A_(len(ids) == len(set(ids)), "骨相重复：%s" % ids)
    return "、".join(ids)


@reg("B", "B03 主角 vs 其他角色面部距离 ≥ 0.625")
def _():
    b = CD.design(roster())
    bad = [p for p in b["_matrix"]["pairs"]
           if ("楚湘" in (p["a"], p["b"])) and p["face_distance"] < 0.625]
    A_(not bad, "主角距离不足：%s" % bad)
    return "min %.2f" % min(p["face_distance"] for p in b["_matrix"]["pairs"] if "楚湘" in (p["a"], p["b"]))


@reg("B", "B04 识别锚全局唯一")
def _():
    b = CD.design(roster())
    ids = [c["anchor"]["id"] for c in b["characters"]]
    A_(len(ids) == len(set(ids)), "锚重复：%s" % ids)
    return "%d 个锚各不同" % len(ids)


@reg("B", "B05 主演/配演发型不重复")
def _():
    b = CD.design(roster(5))
    main = [(c["hair"]["id"], c["name"]) for c in b["characters"] if c["tier"] in ("lead", "support")]
    ids = [x[0] for x in main]
    A_(len(ids) == len(set(ids)), "主演发型重复：%s" % main)
    return "、".join(x[0] for x in main)


@reg("B", "B06 跨阵营色相间隔 ≥ 30°；同阵营明度差 ≥ 0.10")
def _():
    b = CD.design(roster())
    for p in b["_matrix"]["pairs"]:
        if p["same_faction"]:
            continue
        A_(p["hue_gap"] >= 30, "%s↔%s 色相 %.0f°" % (p["a"], p["b"], p["hue_gap"]))
    same = [p for p in b["_matrix"]["pairs"] if p["same_faction"]]
    A_(same, "样本里应当有同阵营对照（财阀 3 人）")
    for p in same:
        A_(p["light_gap"] >= 0.10, "%s↔%s 同阵营明度差 %.2f" % (p["a"], p["b"], p["light_gap"]))
    return "跨阵营 min %.0f° / 同阵营 %d 对" % (
        min(p["hue_gap"] for p in b["_matrix"]["pairs"] if not p["same_faction"]), len(same))


@reg("B", "B07 性别适配：男角色不出现裙装与尖头高跟")
def _():
    b = CD.design(roster())
    bad = []
    for c in b["characters"]:
        if c["gender"] != "m":
            continue
        for w in ("裙", "尖头低跟", "高跟"):
            if w in c["garment"]:
                bad.append((c["name"], w))
    A_(not bad, "男角色穿了不该穿的：%s" % bad)
    return "ok"


@reg("B", "B08 年龄适配：皮肤纹理按年龄段分层，不全写「细腻无瑕」")
def _():
    b = CD.design(roster())
    young = next(c for c in b["characters"] if c["name"] == "楚湘")["skin"]
    old = next(c for c in b["characters"] if c["name"] == "朴婶")["skin"]
    A_(young != old, "18 岁与 61 岁皮肤描述相同")
    A_("无瑕" not in young + old, "出现「无瑕」式默认皮肤")
    A_("皱纹" in old or "松弛" in old, "老年角色缺年龄纹理")
    return "分层正确"


@reg("B", "B09 体态按人群桶取值（掌控者不驼背）")
def _():
    b = CD.design(roster())
    boss = next(c for c in b["characters"] if c["name"] == "教导主任")
    A_(boss["posture"]["id"] in CD.PERSONA[boss["persona_bucket"]]["postures"],
       "体态 %s 不在人群桶候选里" % boss["posture"]["id"])
    return "%s → %s" % (boss["persona"], boss["posture"]["id"])


@reg("B", "B10 单角色名册不崩（无对照项时给兜底文案）")
def _():
    b = CD.design(roster(1))
    A_("仅此一名主要角色" in b["characters"][0]["contrast"], "单角色缺兜底差异文案")
    return "ok"


@reg("B", "B11 族裔改口：东亚骨相里不出现「眼窝中等深 / 鹰钩鼻」")
def _():
    b = CD.design(roster())
    for c in b["characters"]:
        d = c["face"]["detail"]
        for w in ("眼窝中等深", "眼窝深", "鹰钩"):
            A_(w not in d, "%s 残留族裔冲突措辞：%s" % (c["name"], w))
    return "0 冲突"


# =========================================================================== C 提示词
@reg("C", "C01 设定板含识别锚 / 差异对照 / 色签名，且不再用统一灰调纪律")
def _():
    b = CD.design(roster())
    c = b["characters"][0]
    p = CD.board_prompt(c, CD.to_fields(c, ""), b["world"])
    for seg in ("【唯一识别锚", "【与同剧其他角色的差异", "【色彩纪律】本角色色签名",
                "三视图", "【禁止项】"):
        A_(seg in p, "缺段位 %s" % seg)
    A_("低明度高级灰打底" not in p, "仍回落到统一灰调纪律（同质化根因）")
    A_(c["anchor"]["text"][:6] in p, "识别锚没进提示词")
    return "%d 字" % len(p)


@reg("C", "C02 主卡 / 定妆照含识别锚与反默认")
def _():
    b = CD.design(roster())
    c = b["characters"][2]
    f = CD.to_fields(c, "")
    for p in (CD.maincard_prompt(c, f, b["world"]), CD.headshot_prompt(c, f, b["world"])):
        A_("【唯一识别锚" in p, "缺识别锚段")
        A_("排除标准网红脸" in p, "缺反默认")
        A_("只有这一个角色" in p or "单一角色" in p, "缺单人约束")
    return "ok"


@reg("C", "C03 三件套提示词过净化器三项自检（0/0/0）")
def _():
    b = CD.design(roster())
    d = tempfile.mkdtemp(prefix="cd_check_")
    sub = os.path.join(d, "char")
    os.makedirs(sub, exist_ok=True)
    try:
        for i, c in enumerate(b["characters"], 1):
            f = CD.to_fields(c, "")
            for v, p in (("board", CD.board_prompt(c, f, b["world"])),
                         ("main", CD.maincard_prompt(c, f, b["world"])),
                         ("head", CD.headshot_prompt(c, f, b["world"]))):
                with open(os.path.join(sub, "%02d_%s.txt" % (i, v)), "w",
                          encoding="utf-8", newline="") as fh:
                    fh.write(p)
        r = S.self_check(d)
        A_(not any(r.get(k) for k in ("meta", "unbalanced", "empty_seg")),
           "自检不通过：%s" % r)
        return str(r)
    finally:
        shutil.rmtree(d, ignore_errors=True)


@reg("C", "C04 build_char 向后兼容：design=None 时行为不变")
def _():
    it = {"kind": "char", "id": "CH01", "title": "测试", "raw": "",
          "fields": {"风格": "写实", "形象定位": "一名中年男性", "面部特征": "国字脸",
                     "表情": "平静", "服装细节": "灰色西装"}}
    t = T.build_char(it)
    for seg in ("【主视觉大全身立绘】", "【面部特征】", "【禁止项】"):
        A_(seg in t, "缺段位 %s" % seg)
    A_("【唯一识别锚" not in t, "无 design 时不应出现差异化段位")
    A_("低明度高级灰打底" in t, "无 design 时应保留旧色彩纪律")
    return "%d 字" % len(t)


@reg("C", "C05 世界设定生效（名册 world 进入提示词，不再硬编码当代都市）")
def _():
    b = CD.design(roster(world="1920 年代上海·纱厂"))
    c = b["characters"][0]
    p = CD.board_prompt(c, CD.to_fields(c, ""), b["world"])
    A_("1920 年代上海·纱厂" in p, "world 未生效")
    A_("当代中国都市题材" not in p, "仍带硬编码题材")
    return "ok"


# =========================================================================== D 集成
@reg("D", "D01 资产提示词 md 能被 asset_md.py 解析出全部角色")
def _():
    b = CD.design(roster())
    d = tempfile.mkdtemp(prefix="cd_md_")
    try:
        CD.emit(b, __import__("pathlib").Path(d))
        md = os.path.join(d, "资产提示词_角色段.md")
        entries = A.parse_md(__import__("pathlib").Path(md), ("char",))
        A_(len(entries) == len(b["characters"]),
           "解析到 %d 个角色，应为 %d" % (len(entries), len(b["characters"])))
        A_(entries[0]["variants"][0]["prompt"].startswith("一张"), "提示词未进代码块")
        return "%d 节" % len(entries)
    finally:
        shutil.rmtree(d, ignore_errors=True)


@reg("D", "D02 落盘产物齐全且全为 LF（无 CR）")
def _():
    b = CD.design(roster())
    d = tempfile.mkdtemp(prefix="cd_lf_")
    try:
        res = CD.emit(b, __import__("pathlib").Path(d))
        need = ("character-bible.json", "角色差异化矩阵.md", "资产提示词_角色段.md")
        for n in need:
            A_(os.path.isfile(os.path.join(d, n)), "缺产物 %s" % n)
        A_(len(res["files"]) == 3 + 3 * len(b["characters"]), "产物数量不对：%d" % len(res["files"]))
        crlf = []
        for root, _, files in os.walk(d):
            for f in files:
                with open(os.path.join(root, f), "rb") as fh:
                    if b"\r\n" in fh.read():
                        crlf.append(f)
        A_(not crlf, "存在 CRLF：%s" % crlf)
        return "%d 个文件全 LF" % len(res["files"])
    finally:
        shutil.rmtree(d, ignore_errors=True)


# =========================================================================== E 校验与体检
@reg("E", "E01 正常圣经通过六条硬规则")
def _():
    b = CD.design(roster())
    issues = CD.check_rules(b)
    hard = [x for x in issues if x[0] == "hard"]
    A_(not hard, "不该有硬失败：%s" % hard)
    return "%d warn" % len(issues)


@reg("E", "E02 注入撞脸 → R1/R2 报硬失败")
def _():
    b = CD.design(roster())
    a, c = b["characters"][0], b["characters"][1]
    c["face"] = dict(c["face"], slots=dict(a["face"]["slots"]))
    b["_matrix"] = CD.matrix(b)
    codes = [x[1] for x in CD.check_rules(b) if x[0] == "hard"]
    A_("R1" in codes, "未报 R1：%s" % codes)
    A_("R2" in codes, "主角撞脸未报 R2：%s" % codes)
    return "捕获 %s" % sorted(set(codes))


@reg("E", "E03 注入重复识别锚 → R4；注入美颜词 → R6")
def _():
    b = CD.design(roster())
    b["characters"][2]["anchor"] = dict(b["characters"][0]["anchor"])
    b["characters"][3]["garment"] += "整体俊美、面容精致。"
    codes = [x[1] for x in CD.check_rules(b) if x[0] == "hard"]
    A_("R4" in codes, "未报 R4：%s" % codes)
    A_("R6" in codes, "未报 R6：%s" % codes)
    return "捕获 R4/R6"


@reg("E", "E04 check 子命令退出码：通过 0 / 不过 2")
def _():
    b = CD.design(roster())
    d = tempfile.mkdtemp(prefix="cd_exit_")
    try:
        p = os.path.join(d, "bible.json")
        with open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write(json.dumps(b, ensure_ascii=False))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc_ok = CD.main(["check", "--bible", p])
        b["characters"][1]["face"] = dict(b["characters"][0]["face"])
        b["_matrix"] = CD.matrix(b)
        with open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write(json.dumps(b, ensure_ascii=False))
        with contextlib.redirect_stdout(buf):
            rc_bad = CD.main(["check", "--bible", p])
        A_(rc_ok == 0, "通过时应 0，实际 %d" % rc_ok)
        A_(rc_bad == 2, "不过时应 2，实际 %d" % rc_bad)
        return "0 / 2"
    finally:
        shutil.rmtree(d, ignore_errors=True)


@reg("E", "E05 audit 能抓出「同一张脸写三遍」的老项目")
def _():
    md = """# 一、角色资产库

## 1. 甲（女主）

```
一位年轻女性，标准鹅蛋脸，黑色长直发，柳叶眉，杏眼，深棕色瞳孔，身穿白色连衣裙。
```

## 2. 乙（女配）

```
一位年轻女性，鹅蛋脸，黑色长直发，柳叶眉，杏眼，深棕色瞳孔，身穿白色衬衫。
```

## 3. 丙（反派）

```
一位女性，鹅蛋脸，黑色长直发，柳叶眉，杏眼，深棕色瞳孔，身穿黑色西装。
```

# 二、场景资产
"""
    d = tempfile.mkdtemp(prefix="cd_audit_")
    try:
        p = os.path.join(d, "资产提示词.md")
        with open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write(md)
        rep = CD.audit_md(__import__("pathlib").Path(p))
        A_(len(rep["characters"]) == 3, "只解析到 %d 个角色" % len(rep["characters"]))
        A_(len(rep["conflicts"]) >= 2, "未报冲突对：%s" % rep["conflicts"])
        A_(len(rep["no_anchor"]) == 3, "三人均无识别锚，应全部报出")
        top = max(rep["conflicts"], key=lambda x: x["score"])
        A_(top["score"] >= 4, "冲突分过低：%s" % top)
        return "冲突 %d 组 / 缺锚 %d 人" % (len(rep["conflicts"]), len(rep["no_anchor"]))
    finally:
        shutil.rmtree(d, ignore_errors=True)


@reg("E", "E06 audit 对「有锚且各不相同」的样本不误报")
def _():
    md = """# 一、角色资产库

## 1. 甲

```
方脸，齐耳短发，剑眉，细长眼，左眼角下方一颗泪痣，藏青色西装。
```

## 2. 乙

```
圆脸，高马尾，平眉，圆眼，右眉尾一道旧疤，米白色连衣裙。
```

# 二、场景资产
"""
    d = tempfile.mkdtemp(prefix="cd_audit2_")
    try:
        p = os.path.join(d, "资产提示词.md")
        with open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write(md)
        rep = CD.audit_md(__import__("pathlib").Path(p))
        A_(not rep["conflicts"], "不该报冲突：%s" % rep["conflicts"])
        A_(not rep["no_anchor"], "不该报缺锚：%s" % rep["no_anchor"])
        return "0 误报"
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
