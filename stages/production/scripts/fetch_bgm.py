#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""fetch_bgm.py —— 从 Wikimedia Commons 拉一批可商用 BGM 进共享库（库可再生）

为什么需要它
------------
`stages/production/assets/bgm/` 里**只有清单没有音频**（音频 2–8MB/首、且授权凭证不宜随
开源仓库再分发，见该目录 README 与 `.gitignore`）。所以 clone 下来库是空的。
本脚本用 Commons 的开放 API 按情绪检索、过滤、下载、统一转 mp3，并写回清单 ——
**清单 + 本脚本 = 可复现的库**，不必依赖某台机器上的手工收集。

选曲纪律（都是实测踩出来的）
----------------------------
* 只要 `CC0 / 公有领域 / CC BY`：`CC BY-SA` 有传染性、`NC` 不可商用、`ND` 不能混音改编 —— 一律排除。
* 排除「访谈/讲座/广播」类录音（Commons 里混着大量这类文件，时长动辄 30 分钟）。
* 排除地域/时代风格（西部、凯尔特、中世纪、爵士、圣诞…）：短剧是现代都市/家庭/悬疑题材，
  BGM 只负责铺情绪，**不能负责叙事**，否则会把观众拉出剧情。
* 时长取 40–300 秒（够铺 1–3 集，循环点也自然）。
* `bpm` 一律留空：**必须人工听着填**（剪接点对齐用），工具不猜。

用法
----
    python fetch_bgm.py                        # 只看候选（不下载）
    python fetch_bgm.py --apply                # 下载 + 转 mp3 + 写清单
    python fetch_bgm.py --apply --per-mood 3   # 每个情绪要 3 首
    python fetch_bgm.py --apply --dest "<工作区>/04-资产/bgm"   # 放进项目库

注意：抓下来的曲目多为 **CC BY**，可商用但**必须署名**。
`bgm.py credits --ep epNN` 会直接生成可粘进发布文案的署名段。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
import urllib.parse
import urllib.request

OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))
UA = "SoloDrama/0.7 (https://github.com/Hejunlong27/SoloDrama; bgm-library builder)"
API = "https://commons.wikimedia.org/w/api.php"
DEST_DEFAULT = pathlib.Path(__file__).resolve().parents[1] / "assets" / "bgm"

# 情绪 → 检索式（作者名 + 情绪词：这批作者在 Commons 上有系统性上传，比纯情绪词准得多）
QUERIES = {
    "tension": ["Kevin MacLeod impending", "dark tension drone", "Sascha Ende tension"],
    "suspense": ["Kevin MacLeod suspense", "creepy ambient suspense", "mystery suspense ambient"],
    "revenge": ["Kevin MacLeod dark epic", "dramatic trailer tension", "Cj Aist epic"],
    "warm": ["Scott Buckley piano", "sentimental warm piano", "gentle ambient strings"],
    "sad": ["Kevin MacLeod sad piano", "melancholy piano emotional", "touching moments"],
    "epic": ["Sascha Ende epic", "Rafael Krux epic", "cinematic epic orchestral"],
}
BAD_WORDS = ("interview", "lecture", "lezing", "gesprek", "conversation", "podcast",
             "speech", "newsreel", "radio", "spoken", "audiobook", "episode")
# 这些风格会把观众拉出剧情
BAN_WORDS = ("western", "bazaar", "celtic", "medieval", "renaissance", "jazz", "funk",
             "ragtime", "foxtrot", "march", "anthem", "waltz", "tango", "christmas",
             "halloween", "kids", "comedy", "ukulele", "banjo", "accordion", "chiptune",
             "8-bit", "polka", "salsa", "bossa", "country", "bluegrass", "thaxted",
             "alien", "sci-fi", "scifi", "space", "cyber", "robot", "war", "battle")
GOOD_WORDS = ("tension", "suspense", "dark", "ambient", "drone", "pad", "piano", "string",
              "emotional", "melancholy", "epic", "cinematic", "dramatic", "sad", "crisis",
              "heartwarming", "touching", "impending", "rise", "trailer", "atmosphere",
              "sombre", "somber", "grief", "loss", "hope", "gentle", "soft", "slow",
              "warm", "sentimental", "tender", "family", "uplifting")
GAIN_BY_MOOD = {"tension": -22, "suspense": -23, "revenge": -20,
                "warm": -21, "sad": -24, "epic": -19}
ALLOWED_MIME = ("audio/mpeg", "audio/ogg", "application/ogg", "audio/wav", "audio/x-wav")


# ---------------------------------------------------------------------------
def get(params):
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with OP.open(req, timeout=35) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _clean(v):
    return re.sub(r"<[^>]+>", "", str(v or "")).strip()


def search(term, limit=12):
    d = get({"action": "query", "list": "search", "srsearch": "filetype:audio " + term,
             "srnamespace": 6, "srlimit": limit, "format": "json"})
    return [x["title"] for x in ((d.get("query") or {}).get("search") or [])]


def info(titles):
    out = []
    for i in range(0, len(titles), 10):
        d = get({"action": "query", "titles": "|".join(titles[i:i + 10]),
                 "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "format": "json"})
        for page in ((d.get("query") or {}).get("pages") or {}).values():
            ii = (page.get("imageinfo") or [{}])[0]
            em = ii.get("extmetadata") or {}
            out.append({"title": page.get("title") or "", "url": ii.get("url") or "",
                        "desc_url": ii.get("descriptionurl") or "",
                        "mime": ii.get("mime") or "", "size": ii.get("size") or 0,
                        "duration": float(ii.get("duration") or 0),
                        "license": _clean((em.get("LicenseShortName") or {}).get("value")),
                        "artist": _clean((em.get("Artist") or {}).get("value")).splitlines()[0]
                        if em.get("Artist") else "",
                        "desc": _clean((em.get("ImageDescription") or {}).get("value"))})
    return out


def usable(r):
    lic = (r["license"] or "").upper().replace(" ", "")
    if not ("CC0" in lic or "PUBLICDOMAIN" in lic or "CCBY" in lic):
        return False
    if "SA" in lic or "NC" in lic or "ND" in lic:
        return False
    if not (40 <= r["duration"] <= 300):
        return False
    if r["size"] > 14 * 1024 * 1024:
        return False
    if r["mime"] not in ALLOWED_MIME:
        return False
    blob = (r["title"] + " " + r["desc"]).lower()
    return not any(w in blob for w in BAD_WORDS + BAN_WORDS)


def score(r):
    blob = (r["title"] + " " + r["desc"]).lower()
    return sum(3 for w in GOOD_WORDS if w in blob)


def slug(t):
    s = re.sub(r"^File:", "", t)
    s = re.sub(r"\.(mp3|ogg|oga|wav|flac|m4a|opus)$", "", s, flags=re.I)
    s = re.sub(r"\(ISRC[^)]*\)", "", s)
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()
    return s[:34] or "track"


def license_fields(r):
    """→ (license 枚举, license_note, attribution, license_name)"""
    lic = r["license"] or ""
    up = lic.upper()
    artist = re.sub(r"\s*\(\d+\)\s*$", "", (r["artist"] or "Unknown")).strip() or "Unknown"
    title = re.sub(r"\.(mp3|ogg|oga|wav|opus)$", "", r["title"].replace("File:", ""), flags=re.I)
    title = re.sub(r"\s*\(ISRC [^)]*\)", "", title)
    title = re.sub(r"^(Rafael Krux|Scott Buckley|Kevin MacLeod|Sascha Ende)\s*-\s*", "", title).strip()
    name = re.sub(r"\s+us$", "", lic).strip() or "CC BY 4.0"
    attr = "%s — “%s”（%s，via Wikimedia Commons）" % (artist, title, name)
    page = r["desc_url"] or ("https://commons.wikimedia.org/wiki/" +
                             urllib.parse.quote(r["title"].replace(" ", "_")))
    if "CC0" in up or "PUBLIC DOMAIN" in up:
        return ("cc0", "CC0 / 公有领域：可商用、无需署名。来源：%s" % page, attr, name)
    return ("licensed",
            "%s：可商用，**发行时必须署名**（发布文案或片尾）：%s。来源：%s" % (name, attr, page),
            attr, name)


def download(url, out):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with OP.open(req, timeout=180) as r:
        data = r.read()
    out.write_bytes(data)
    return len(data)


def to_mp3(src, dst):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-i", str(src),
                        "-vn", "-c:a", "libmp3lame", "-b:a", "128k", "-ar", "44100",
                        "-ac", "2", str(dst)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode == 0, (r.stderr or "")[-300:]


def probe_duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    try:
        return round(float((r.stdout or "0").strip()), 2)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="从 Wikimedia Commons 拉可商用 BGM")
    ap.add_argument("--apply", action="store_true", help="真下载（默认只看候选）")
    ap.add_argument("--per-mood", dest="per_mood", type=int, default=2, help="每个情绪几首")
    ap.add_argument("--dest", default=str(DEST_DEFAULT), help="目标目录（默认引擎共享库）")
    ap.add_argument("--mood", action="append", default=None,
                    help="只处理指定情绪，可多次；默认全部")
    a = ap.parse_args()

    dest = pathlib.Path(a.dest).expanduser().resolve()
    moods = a.mood or list(QUERIES)
    picked, seen = {}, set()
    for mood in moods:
        pool = []
        for q in QUERIES.get(mood, []):
            try:
                for r in info(search(q, 12)):
                    if r["title"] in seen or not usable(r):
                        continue
                    seen.add(r["title"])
                    pool.append(r)
            except Exception as e:                                # noqa: BLE001
                print("  [WARN] 搜索失败 %r：%s" % (q, e))
        pool.sort(key=lambda x: (-score(x), abs(x["duration"] - 110), x["size"]))
        picked[mood] = pool[:a.per_mood]
        print("[%s] 候选 %d → 选 %d" % (mood, len(pool), len(picked[mood])))
        for r in picked[mood]:
            print("   - %-56s %6.1fs %5.2fMB %s"
                  % (r["title"][:56], r["duration"], r["size"] / 1048576, r["license"]))

    if not a.apply:
        print("\n（干跑：加 --apply 下载并写清单）")
        return 0

    dest.mkdir(parents=True, exist_ok=True)
    lib_path = dest / "bgm-library.json"
    existing = {"tracks": []}
    if lib_path.is_file():
        try:
            existing = json.loads(lib_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError, ValueError):
            existing = {"tracks": []}
    have = {str(t.get("id")) for t in (existing.get("tracks") or [])}

    tracks, tmp = [], dest / "_tmp"
    tmp.mkdir(exist_ok=True)
    for mood, rows in picked.items():
        for i, r in enumerate(rows, 1):
            tid = "%s_%02d_%s" % (mood, i, slug(r["title"])[:24])
            if tid in have:
                print("  [跳过] 已在清单里：%s" % tid)
                continue
            ext = "ogg" if "ogg" in r["mime"] else "mp3"
            raw = tmp / ("%s_%02d.%s" % (mood, i, ext))
            out = dest / (tid + ".mp3")
            try:
                n = download(r["url"], raw)
            except Exception as e:                                # noqa: BLE001
                print("  [FAIL] 下载 %s：%s" % (r["title"], e))
                continue
            ok, err = to_mp3(raw, out)
            if not ok:
                print("  [FAIL] 转码 %s：%s" % (r["title"], err))
                continue
            lic, note, attr, name = license_fields(r)
            tracks.append({"id": tid, "file": out.name, "moods": [mood],
                           "bpm": None, "duration": probe_duration(out), "loop": True,
                           "license": lic, "artist": r["artist"] or "Unknown",
                           "title": re.sub(r"\.(mp3|ogg|oga|opus)$", "", r["title"][5:],
                                           flags=re.I),
                           "license_name": name, "source": r["title"].replace("File:", ""),
                           "source_url": r["desc_url"], "attribution": attr,
                           "license_note": note, "gain_db": GAIN_BY_MOOD.get(mood, -22)})
            print("  [OK] %-44s %6.1fs %5.2fMB ← %s"
                  % (out.name, probe_duration(out) or 0, n / 1048576, r["license"]))

    for f in tmp.glob("*"):
        f.unlink()
    try:
        tmp.rmdir()
    except OSError:
        pass
    if not tracks:
        print("\n（没有新增曲目）")
        return 0
    merged = list(existing.get("tracks") or []) + tracks
    existing["tracks"] = sorted(merged, key=lambda t: str(t.get("id")))
    existing.setdefault("version", 1)
    existing["_note"] = ("音频文件不进 git（见 .gitignore），本清单由 fetch_bgm.py 生成；"
                         "bpm 留空需人工填。署名：bgm.py credits --ep epNN")
    lib_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8", newline="")
    print("\n[OK] 新增 %d 首 → %s（清单共 %d 条）"
          % (len(tracks), lib_path, len(existing["tracks"])))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
