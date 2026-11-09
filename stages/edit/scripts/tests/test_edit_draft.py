# -*- coding: utf-8 -*-
"""剪映工程生成器自测（离线、零网络、零计费）。

跑法：
    python stages/edit/scripts/tests/test_edit_draft.py

它证明六件事（每一条都对应一个真实会踩的坑）：

1. **亚秒精度没被吃掉**：`pyJianYingDraft.trange(0.2, 1.6)` 会得到 `0 → 2` 秒，
   所以本模块一律用 `Timerange(µs, µs)`。这里断言 0.2s 的起点进到草稿里还是 200000µs。
2. **字幕跟着封面片头走**：母版有 0.8s 封面时，字幕整体后移 800000µs；
   没有封面时不偏移。偏移错 = 工程与成片差 0.8 秒，送审时「对不上」比没工程更糟。
3. **自检真的会拦**：手改 `target_timerange`、或删掉源素材，
   `verify()` 必须判 `pass=False` —— 否则「生成成功」只是一句话。
4. **素材断链可发现**：`draft_content.json` 存绝对路径，源文件挪走就必须报出来。
5. **清单可用于外部核对**：`draft_manifest.json` 里每段素材都有 sha256 与字节数。
6. **字幕侧的封面偏移**：`subtitle.write_ass(offset_s=…)` 写出的 ASS 行时间同步后移，
   保证「母版 / ASS / 工程」三者同一个时间轴。

依赖：ffmpeg（造测试素材）、pyJianYingDraft（写草稿）。缺任一项时相关用例 SKIP，
不算失败 —— 但会在汇总里点出来，避免「全绿」的假象。
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
SCRIPTS = HERE.parent                          # stages/edit/scripts
REPO = SCRIPTS.parents[2]                      # 仓库根
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(REPO / "stages" / "subtitle" / "scripts"))

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))


def skip(name, why):
    RESULTS.append((name, None, why))


def _has(cmd):
    return shutil.which(cmd) is not None


def _has_draft_lib():
    try:
        import pyJianYingDraft  # noqa: F401
        return True
    except ImportError:
        return False


FFMPEG = _has("ffmpeg") and _has("ffprobe")
HAS_LIB = _has_draft_lib()


# ---------------------------------------------------------------- 夹具
def _mk_media(path: pathlib.Path, color: str, dur: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "lavfi", "-i", "color=c=%s:s=1080x1920:d=%s" % (color, dur),
         "-f", "lavfi", "-i", "sine=f=300:d=%s" % dur,
         "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-shortest", str(path)],
        check=True, capture_output=True)


def build_ws(root: pathlib.Path, *, cover: bool = True, cues: bool = True,
             bgm: bool = False) -> pathlib.Path:
    """造一个最小可用工作区：2 镜（2.0s / 1.5s）+ 可选封面 + cues + 可选 BGM。"""
    ws = root / "ws"
    (ws / "06-提示词" / "ep01").mkdir(parents=True)
    (ws / "07-成片" / "subs" / "ep01").mkdir(parents=True)
    (ws / "09-发行" / "封面").mkdir(parents=True)
    (ws / "video-pipeline").mkdir(parents=True)
    (ws / "layout.json").write_text(json.dumps({
        "layout_version": 1, "engine_root": "video-pipeline",
        "data_rel": "../06-提示词", "out_rel": "../07-成片",
        "assets_rel": "../04-资产"}, ensure_ascii=False), encoding="utf-8")
    (ws / "06-提示词" / "ep01" / "shots.json").write_text(json.dumps(
        [{"shot_id": "shot_001", "duration": 2.0},
         {"shot_id": "shot_002", "duration": 1.5}], ensure_ascii=False), encoding="utf-8")
    _mk_media(ws / "07-成片" / "ep01" / "b0001" / "shot_001" / "final.mp4", "red", 2.0)
    _mk_media(ws / "07-成片" / "ep01" / "b0001" / "shot_002" / "final.mp4", "blue", 1.5)
    if cover:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                        "-i", "color=c=green:s=1080x1920:d=1", "-frames:v", "1",
                        str(ws / "09-发行" / "封面" / "cover_9x16.png")],
                       check=True, capture_output=True)
    if cues:
        (ws / "07-成片" / "subs" / "ep01" / "cues.json").write_text(json.dumps([
            {"shot_id": "shot_001", "start": 0.2, "end": 1.4,
             "text": "前半句台词", "lines": ["前半句台词"], "source": "ctc-sequential"},
            {"shot_id": "shot_002", "start": 2.1, "end": 2.9,
             "text": "后半句台词", "lines": ["后半句台词"], "source": "ctc-sequential"},
        ], ensure_ascii=False), encoding="utf-8")
    if bgm:
        lib = ws / "04-资产" / "bgm"
        lib.mkdir(parents=True, exist_ok=True)
        # 必须是**纯音频**容器：pyJianYingDraft 的 AudioMaterial 会拒绝带视频轨的文件
        # （实测拿 mp4 改名成 .m4a 会抛 "音频素材不应包含视频轨道"）
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                        "-i", "sine=f=220:d=5", "-c:a", "aac", "-vn",
                        str(lib / "t1.m4a")], check=True, capture_output=True)
        (lib / "bgm-library.json").write_text(json.dumps(
            {"version": 1, "tracks": [{"id": "tension_low_01", "file": "t1.m4a",
                                       "license": "licensed", "gain_db": -22}]},
            ensure_ascii=False), encoding="utf-8")
        (ws / "07-成片" / "subs" / "ep01" / "ep01_bgm-plan.json").write_text(json.dumps({
            "ep": "ep01", "total_s": 4.3, "voice": "h3",
            "segments": [{"track": "tension_low_01", "start": 0.0, "end": 4.3,
                          "gain_db": -22, "note": "整集铺底"}],
        }, ensure_ascii=False), encoding="utf-8")
    return ws


def run_cli(ws, *args):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run([sys.executable, str(SCRIPTS / "edit_draft.py"),
                        "--workspace", str(ws)] + list(args),
                       capture_output=True, text=True, encoding="utf-8", env=env)
    return p.returncode, p.stdout, p.stderr


# ---------------------------------------------------------------- 纯函数
def case_timeline_purity():
    """build_timeline 是纯函数：不碰第三方库、不用 trange，亚秒不丢。"""
    import edit_draft as E
    tl = E.build_timeline({
        "cover_path": "/x/cover.png", "cover_s": 0.8,
        "clips": [{"index": 1, "shot_id": "shot_001", "path": "/x/a.mp4", "dur_s": 2.0},
                  {"index": 2, "shot_id": "shot_002", "path": "/x/b.mp4", "dur_s": 1.5}],
        "cues": [{"start": 0.2, "end": 1.44, "text": "甲", "lines": ["甲"],
                  "shot_id": "shot_001", "source": "ctc-sequential"}],
        "bgm_items": [], "bgm_msg": "", "cover_msg": "", "ep": "ep01",
    }, {"canvas": {"width": 1080, "height": 1920}})
    check("亚秒起点未被截断（0.2s → 200000µs + 片头）",
          tl["text"][0]["start_us"] == 1_000_000, str(tl["text"][0]))
    check("亚秒时长未被截断（1.24s → 1240000µs）",
          tl["text"][0]["dur_us"] == 1_240_000, str(tl["text"][0]["dur_us"]))
    check("视频段起点累计正确",
          [c["start_us"] for c in tl["video"]] == [0, 800_000, 2_800_000],
          str([c["start_us"] for c in tl["video"]]))
    check("总时长 = 片头 + 两段",
          tl["total_us"] == 4_300_000, str(tl["total_us"]))
    check("字幕偏移量 = 封面时长", tl["cue_offset_us"] == 800_000, str(tl["cue_offset_us"]))

    tl2 = E.build_timeline({
        "cover_path": "", "cover_s": 0.0,
        "clips": [{"index": 1, "shot_id": "shot_001", "path": "/x/a.mp4", "dur_s": 2.0}],
        "cues": [{"start": 0.2, "end": 1.0, "text": "乙", "lines": ["乙"],
                  "shot_id": "shot_001", "source": "ctc-sequential"}],
        "bgm_items": [], "bgm_msg": "", "cover_msg": "", "ep": "ep01",
    }, {"canvas": {"width": 1080, "height": 1920}})
    check("无封面时字幕不偏移", tl2["text"][0]["start_us"] == 200_000,
          str(tl2["text"][0]))


def case_volume():
    import edit_draft as E
    check("-22dB → 线性 0.0794", abs(E._volume_of(-22) - 0.0794) < 0.001,
          str(E._volume_of(-22)))
    check("0dB → 1.0", E._volume_of(0) == 1.0, str(E._volume_of(0)))
    check("+6dB 被 ceil 到 1.0", E._volume_of(6, 1.0) == 1.0, str(E._volume_of(6, 1.0)))


def case_empty_cues_refused(tmp: pathlib.Path):
    if not FFMPEG:
        skip("空 cues 被拒绝", "无 ffmpeg")
        return
    ws = build_ws(tmp / "empty_cues", cover=False, cues=False)
    rc, out, err = run_cli(ws, "--ep", "ep01")
    check("空 cues 被拒绝（退出码 3）", rc == 3, "rc=%s err=%s" % (rc, err[-300:]))
    check("拒绝理由点名先跑字幕渲染", "subtitle.py --stage render" in err, err[-300:])


def case_no_shots_refused(tmp: pathlib.Path):
    """一段成片都没有时必须拒绝生成 —— 空工程不能顶 `pass` 混过去。

    实跑踩过：工作区只搬了 `07-成片`（没有 `shots.json`）⇒ 段列表为空，
    却造出「视频 0 段 / 字幕 9 条」的草稿并报「自检通过」。
    """
    if not FFMPEG:
        skip("没有画面时拒绝生成", "无 ffmpeg")
        return
    ws = build_ws(tmp / "noshots", cover=False, cues=True)
    for p in (ws / "07-成片" / "ep01").rglob("final.mp4"):
        p.unlink()
    rc, out, err = run_cli(ws, "--ep", "ep01")
    check("没有画面时拒绝生成（退出码 3）", rc == 3, "rc=%s err=%s" % (rc, err[-300:]))
    check("拒绝时不落草稿目录", not (ws / "07-成片" / "ep01" / "_draft").exists())
    check("拒绝理由点名 shots.json 与 video.batch",
          "shots.json" in err and "video.batch" in err, err[-300:])
    rc2, _o2, _e2 = run_cli(ws, "--ep", "ep01", "--dry-run")
    check("dry-run 也不放过空工程", rc2 == 3, "rc=%s" % rc2)


def case_missing_shot_fails_verdict(tmp: pathlib.Path):
    """缺镜：草稿照落（人要看得见缺在哪），但结论必须不合格。

    否则一份 19/20 镜的工程会顶着 `pass` 送到平台，等于自证素材不全。
    """
    if not (FFMPEG and HAS_LIB):
        skip("缺镜时判不合格", "缺 ffmpeg 或 pyJianYingDraft")
        return
    ws = build_ws(tmp / "miss")
    (ws / "06-提示词" / "ep01" / "shots.json").write_text(json.dumps(
        [{"shot_id": "shot_001", "duration": 2.0},
         {"shot_id": "shot_002", "duration": 1.5},
         {"shot_id": "shot_003", "duration": 1.0}], ensure_ascii=False), encoding="utf-8")
    rc, out, err = run_cli(ws, "--ep", "ep01")
    man_p = ws / "07-成片" / "ep01" / "_draft" / "draft_manifest.json"
    man = json.loads(man_p.read_text(encoding="utf-8")) if man_p.is_file() else {}
    fails = ((man.get("verdict") or {}).get("fails") or [])
    check("缺镜：草稿仍然落盘", man_p.is_file())
    check("缺镜：退出码 2（不合格）", rc == 2, "rc=%s" % rc)
    check("缺镜：verdict 判不合格", not (man.get("verdict") or {}).get("pass"), fails)
    check("缺镜：失败理由点名缺哪镜", any("shot_003" in f for f in fails), fails)
    check("缺镜：stderr 提前警告", "shot_003" in err, err[-300:])


def case_end_to_end(tmp: pathlib.Path):
    if not (FFMPEG and HAS_LIB):
        skip("端到端生成 + 自检", "缺 ffmpeg 或 pyJianYingDraft")
        return
    ws = build_ws(tmp / "e2e")
    rc, out, err = run_cli(ws, "--ep", "ep01")
    check("端到端生成成功（退出码 0）", rc == 0, "rc=%s err=%s" % (rc, err[-400:]))
    ddir = ws / "07-成片" / "ep01" / "_draft" / "ep01_剪映工程"
    js_path = ddir / "draft_content.json"
    check("草稿落盘", js_path.is_file(), str(ddir))
    if not js_path.is_file():
        return
    js = json.loads(js_path.read_text(encoding="utf-8"))
    check("画布 1080x1920", js["canvas_config"]["width"] == 1080
          and js["canvas_config"]["height"] == 1920, str(js["canvas_config"]))
    tracks = {t["type"]: t for t in js["tracks"]}
    check("三条轨齐全（video/text/audio 中 audio 可缺）",
          "video" in tracks and "text" in tracks, str(list(tracks)))
    vseg = sorted(tracks["video"]["segments"],
                  key=lambda s: s["target_timerange"]["start"])
    check("视频段 3 个（封面+2 镜）", len(vseg) == 3, str(len(vseg)))
    check("封面占 0–800000µs",
          vseg[0]["target_timerange"] == {"start": 0, "duration": 800_000},
          str(vseg[0]["target_timerange"]))
    tseg = sorted(tracks["text"]["segments"],
                  key=lambda s: s["target_timerange"]["start"])
    check("字幕起点已加封面偏移（0.2s → 1.0s）",
          tseg[0]["target_timerange"]["start"] == 1_000_000,
          str(tseg[0]["target_timerange"]))
    check("字幕落点 transform.y = -0.2（0.6H）",
          abs(tseg[0]["clip"]["transform"]["y"] + 0.2) < 1e-6,
          str(tseg[0]["clip"]["transform"]))

    man = json.loads((ws / "07-成片" / "ep01" / "_draft" / "draft_manifest.json")
                     .read_text(encoding="utf-8"))
    check("清单记 3 段视频素材", len(man["tracks"]["video"]) == 3,
          str(len(man["tracks"]["video"])))
    check("清单每段素材有 sha256",
          all(len(v.get("sha256") or "") == 64 for v in man["tracks"]["video"]),
          str([v.get("sha256", "")[:8] for v in man["tracks"]["video"]]))
    check("清单记封面偏移", man["cue_offset_us"] == 800_000, str(man["cue_offset_us"]))
    check("自检结论落在清单里", man["verdict"]["pass"] is True, str(man["verdict"]))


def _not_black(jpg: pathlib.Path) -> bool:
    try:
        from PIL import Image
        im = Image.open(jpg).convert("L")
        px = list(im.getdata())
        return (sum(px) / max(1, len(px))) > 8
    except Exception:                     # noqa: BLE001  没装 Pillow 就不判，别让环境问题伪装成缺陷
        return True


def case_meta_for_jianying_home(tmp: pathlib.Path):
    """首页的「时长 + 缩略图」只读 `draft_meta_info.json` —— 不补就是 00:00 + 黑块。

    本机实测（剪映专业版 10.8.0.14162）：这份元信息写成**明文 JSON** 剪映照样读得进去
    （补上 tm_duration/draft_cover 后，首页卡片立刻从「00:00 + 黑块」变成「00:03 + 真实画面」）。
    这条用例守的是「送审时对方在首页看到的是不是一份像样的工程」。
    """
    if not (FFMPEG and HAS_LIB):
        skip("首页元信息（时长 + 缩略图）", "缺 ffmpeg 或 pyJianYingDraft")
        return
    ws = build_ws(tmp / "meta")
    rc, out, err = run_cli(ws, "--ep", "ep01")
    ddir = ws / "07-成片" / "ep01" / "_draft" / "ep01_剪映工程"
    check("元信息用例：生成成功", rc == 0, "rc=%s err=%s" % (rc, err[-300:]))
    mp = ddir / "draft_meta_info.json"
    if not mp.is_file():
        check("draft_meta_info.json 存在", False, str(mp))
        return
    meta = json.loads(mp.read_text(encoding="utf-8"))
    # 封面 0.8s + 2.0s + 1.5s = 4.3s
    check("meta 时长 = 时间轴总时长（4.3s）", meta.get("tm_duration") == 4_300_000,
          str(meta.get("tm_duration")))
    check("meta 草稿名正确", meta.get("draft_name") == "ep01_剪映工程",
          str(meta.get("draft_name")))
    cvp_s = meta.get("draft_cover") or ""
    cvp = pathlib.Path(cvp_s)
    check("meta 缩略图指向真实文件", bool(cvp_s) and cvp.is_file(), cvp_s or "（空）")
    if cvp.is_file():
        check("缩略图不是纯黑（抽的是画面中段，不是淡入黑场）", _not_black(cvp), str(cvp))
    check("自检结论里点了元信息", "草稿首页元信息" in out, out[-160:])


def case_meta_tamper_detected(tmp: pathlib.Path):
    """首页时长被改成 0 时必须判不合格 —— 否则「生成成功」只是一句话。"""
    if not (FFMPEG and HAS_LIB):
        skip("自检抓到首页时长被改", "缺 ffmpeg 或 pyJianYingDraft")
        return
    import edit_draft as E
    ws = build_ws(tmp / "metatamper")
    rc, _out, err = run_cli(ws, "--ep", "ep01")
    ddir = ws / "07-成片" / "ep01" / "_draft" / "ep01_剪映工程"
    mp = ddir / "draft_meta_info.json"
    if rc != 0 or not mp.is_file():
        check("篡改用例：生成成功", False, "rc=%s err=%s" % (rc, err[-200:]))
        return
    meta = json.loads(mp.read_text(encoding="utf-8"))
    meta["tm_duration"] = 0                       # 模拟首页显示 00:00
    mp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    cfg = E.load_edit_config(ws)
    tl = E.build_timeline(E.collect(ws, "ep01"), cfg)
    v = E.verify(ddir, tl, cfg)
    check("首页时长为 0 时自检判不合格", v["pass"] is False, str(v.get("fails")))
    check("失败原因点名 tm_duration",
          any("tm_duration" in f for f in (v.get("fails") or [])), str(v.get("fails")))


def case_no_draft_cover(tmp: pathlib.Path):
    """`--no-draft-cover` 只是不画缩略图，不许把自检搞成不过。"""
    if not (FFMPEG and HAS_LIB):
        skip("--no-draft-cover", "缺 ffmpeg 或 pyJianYingDraft")
        return
    ws = build_ws(tmp / "nocover")
    rc, _out, err = run_cli(ws, "--ep", "ep01", "--no-draft-cover")
    ddir = ws / "07-成片" / "ep01" / "_draft" / "ep01_剪映工程"
    check("--no-draft-cover：不生成 draft_cover.jpg",
          not (ddir / "draft_cover.jpg").is_file(), str(ddir))
    meta = json.loads((ddir / "draft_meta_info.json").read_text(encoding="utf-8"))
    check("--no-draft-cover：meta 的 draft_cover 为空", meta.get("draft_cover") == "",
          str(meta.get("draft_cover")))
    check("--no-draft-cover：自检仍通过", rc == 0, "rc=%s err=%s" % (rc, err[-300:]))


def case_detect_jianying_root(tmp: pathlib.Path):
    """草稿根目录要按 `draft_root_path` 众数取，不能信 `root_path`。

    本机实测的坑：35 条草稿全在 `D:\\Program Files (x86)\\JianyingPro Drafts`，
    而索引里的 `root_path` 还写着 C 盘默认位置 —— 照它生成，剪映首页根本看不见。
    """
    import edit_draft as E
    root = tmp / "jydetect"
    a = root / "D_drive_drafts"
    b = root / "C_default_drafts"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    idx = root / "root_meta_info.json"
    idx.write_text(json.dumps({
        "root_path": str(b).replace("\\", "/"),        # 默认位置，不算数
        "all_draft_store": [
            {"draft_name": "x", "draft_root_path": str(a)},
            {"draft_name": "y", "draft_root_path": str(a)},
            {"draft_name": "z", "draft_root_path": str(b)},
        ]}, ensure_ascii=False), encoding="utf-8")
    got, why = E.detect_jianying_root(idx)
    check("探测取 draft_root_path 众数而非 root_path", got == a, "%s <- %s" % (got, why))

    idx.write_text(json.dumps({"root_path": str(b).replace("\\", "/"),
                               "all_draft_store": []}, ensure_ascii=False), encoding="utf-8")
    got2, why2 = E.detect_jianying_root(idx)
    check("一条草稿都没有时退回 root_path", got2 == b, "%s <- %s" % (got2, why2))

    got3, why3 = E.detect_jianying_root(root / "nope.json")
    check("索引缺失时返回 None 并说明原因", got3 is None and "没找到" in why3, why3)


def case_verify_catches_tamper(tmp: pathlib.Path):
    if not (FFMPEG and HAS_LIB):
        skip("自检能抓到篡改", "缺 ffmpeg 或 pyJianYingDraft")
        return
    import edit_draft as E
    ws = build_ws(tmp / "tamper")
    rc, _o, err = run_cli(ws, "--ep", "ep01")
    if rc != 0:
        skip("自检能抓到篡改", "前置生成失败：%s" % err[-200:])
        return
    ddir = ws / "07-成片" / "ep01" / "_draft" / "ep01_剪映工程"
    js_path = ddir / "draft_content.json"
    js = json.loads(js_path.read_text(encoding="utf-8"))
    # 篡改 1：把第二段视频往后推 0.5s（模拟手工拖动后未重建）
    vt = [t for t in js["tracks"] if t["type"] == "video"][0]
    vt["segments"][1]["target_timerange"]["start"] += 500_000
    js_path.write_text(json.dumps(js, ensure_ascii=False), encoding="utf-8")

    data, edit_cfg, tl = E.plan(ws, "ep01", _Opts())
    v = E.verify(ddir, tl, edit_cfg)
    check("自检抓到片段起点被改", not v["pass"] and any("起点" in f for f in v["fails"]),
          str(v["fails"])[:300])

    # 篡改 2：删掉一个源素材 → 断链
    js = json.loads(js_path.read_text(encoding="utf-8"))
    for t in js["tracks"]:
        if t["type"] == "video":
            t["segments"][1]["target_timerange"]["start"] -= 500_000
    js_path.write_text(json.dumps(js, ensure_ascii=False), encoding="utf-8")
    victim = ws / "07-成片" / "ep01" / "b0001" / "shot_002" / "final.mp4"
    victim.unlink()
    v2 = E.verify(ddir, tl, edit_cfg)
    check("自检抓到素材断链", not v2["pass"] and any("断链" in f for f in v2["fails"]),
          str(v2["fails"])[:300])


class _Opts:
    """CLI 参数的最小替身（`plan()` 只读这几个字段）。"""
    no_cover = False
    no_bgm = False
    allow_empty_subtitles = False
    canvas = None
    fps = None


def case_copy_media(tmp: pathlib.Path):
    if not (FFMPEG and HAS_LIB):
        skip("--copy-media 让工程可搬走", "缺 ffmpeg 或 pyJianYingDraft")
        return
    ws = build_ws(tmp / "copymedia")
    rc, _o, err = run_cli(ws, "--ep", "ep01", "--copy-media")
    if rc != 0:
        skip("--copy-media 让工程可搬走", "前置生成失败：%s" % err[-200:])
        return
    ddir = ws / "07-成片" / "ep01" / "_draft" / "ep01_剪映工程"
    js = json.loads((ddir / "draft_content.json").read_text(encoding="utf-8"))
    paths = [m["path"] for m in js["materials"]["videos"]] + \
            [m["path"] for m in js["materials"].get("audios") or []]
    check("素材已拷进草稿目录",
          paths and all(str(ddir) in p for p in paths), str(paths[:2]))
    check("拷贝后文件确实存在", all(pathlib.Path(p).is_file() for p in paths),
          str([p for p in paths if not pathlib.Path(p).is_file()][:2]))


def case_bgm(tmp: pathlib.Path):
    if not (FFMPEG and HAS_LIB):
        skip("BGM 轨（含 dB→线性换算）", "缺 ffmpeg 或 pyJianYingDraft")
        return
    ws = build_ws(tmp / "bgm", bgm=True)
    rc, out, err = run_cli(ws, "--ep", "ep01")
    if rc != 0:
        check("BGM 工程生成成功", False, (out + err)[-400:])
        return
    ddir = ws / "07-成片" / "ep01" / "_draft" / "ep01_剪映工程"
    js = json.loads((ddir / "draft_content.json").read_text(encoding="utf-8"))
    at = [t for t in js["tracks"] if t["type"] == "audio"]
    check("BGM 轨存在", bool(at), str([t["type"] for t in js["tracks"]]))
    if at:
        seg = at[0]["segments"][0]
        check("BGM 段铺满计划区间（0–4.3s）",
              seg["target_timerange"]["start"] == 0
              and seg["target_timerange"]["duration"] == 4_300_000,
              str(seg["target_timerange"]))
        v = seg.get("volume", seg.get("last_nonzero_volume"))
        check("BGM 音量按 -22dB 换算（≈0.079）",
              v is not None and abs(float(v) - 0.0794) < 0.002, str(v))


def case_dry_run_writes_nothing(tmp: pathlib.Path):
    if not FFMPEG:
        skip("dry-run 不写盘", "无 ffmpeg")
        return
    ws = build_ws(tmp / "dry")
    rc, out, err = run_cli(ws, "--ep", "ep01", "--dry-run")
    check("dry-run 退出码 0", rc == 0, "rc=%s err=%s" % (rc, err[-200:]))
    check("dry-run 打印时间轴", "剪映工程时间轴" in out, out[:200])
    check("dry-run 没有落草稿",
          not (ws / "07-成片" / "ep01" / "_draft").exists(),
          str(ws / "07-成片" / "ep01"))


def case_ass_offset():
    """字幕侧：write_ass(offset_s) 必须把每条 Dialogue 时间同步后移。"""
    import subtitle as S
    cfg = S.load_config(str(REPO))
    cues = [{"shot_id": "shot_001", "start": 0.2, "end": 1.4,
             "text": "测试一句", "lines": ["测试一句"], "source": "test"}]
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="sd_ass_"))
    try:
        a0 = tmp / "a0.ass"
        a1 = tmp / "a1.ass"
        S.write_ass(cues, cfg, str(a0), canvas=(1080, 1920), offset_s=0.0)
        S.write_ass(cues, cfg, str(a1), canvas=(1080, 1920), offset_s=0.8)
        l0 = [x for x in a0.read_text(encoding="utf-8").splitlines() if x.startswith("Dialogue")]
        l1 = [x for x in a1.read_text(encoding="utf-8").splitlines() if x.startswith("Dialogue")]
        check("ASS 无偏移时起点 0:00:00.20", ",0:00:00.20," in l0[0], l0[0][:40])
        check("ASS 偏移 0.8s 后起点 0:00:01.00", ",0:00:01.00," in l1[0], l1[0][:40])
        check("ASS 偏移后时长不变（1.20s）", "0:00:02.20" in l1[0], l1[0][:60])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="sd_edit_"))
    try:
        case_timeline_purity()
        case_volume()
        if FFMPEG:
            case_empty_cues_refused(tmp)
            case_no_shots_refused(tmp)
            case_missing_shot_fails_verdict(tmp)
            case_end_to_end(tmp)
            case_meta_for_jianying_home(tmp)
            case_meta_tamper_detected(tmp)
            case_no_draft_cover(tmp)
            case_detect_jianying_root(tmp)
            case_verify_catches_tamper(tmp)
            case_copy_media(tmp)
            case_bgm(tmp)
            case_dry_run_writes_nothing(tmp)
        else:
            for n in ("空 cues 被拒绝", "没有画面时拒绝生成", "缺镜时判不合格",
                      "端到端生成 + 自检", "首页元信息（时长 + 缩略图）",
                      "自检抓到首页时长被改", "--no-draft-cover",
                      "草稿根目录探测（draft_root_path 众数）",
                      "自检能抓到篡改",
                      "--copy-media 让工程可搬走", "BGM 轨（含 dB→线性换算）",
                      "dry-run 不写盘"):
                skip(n, "无 ffmpeg")
        case_ass_offset()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("=" * 64)
    print("edit_draft（剪映工程）离线测试")
    print("=" * 64)
    n_fail = n_skip = 0
    for name, ok, detail in RESULTS:
        if ok is None:
            print("  [SKIP] %s  <- %s" % (name, detail))
            n_skip += 1
            continue
        print("  %s %s%s" % ("[OK]  " if ok else "[FAIL]", name,
                             "" if ok else "  <- %s" % detail))
        n_fail += 0 if ok else 1
    print("-" * 64)
    print("共 %d 例，通过 %d，失败 %d，跳过 %d"
          % (len(RESULTS), len(RESULTS) - n_fail - n_skip, n_fail, n_skip))
    if not HAS_LIB:
        print("  ⚠ 未安装 pyJianYingDraft（pip install -r requirements-edit.txt）"
              " ⇒ 写草稿相关用例被跳过，本次结论**不能**证明工程可用")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
