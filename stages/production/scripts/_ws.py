# -*- coding: utf-8 -*-
"""_ws.py —— 工作区解析（把短剧生产脚本从「写死一个项目」变成「可移植」）

为什么要它（2026-09-20 封装 Skill 时发现的老问题）：
    同一批脚本里，工作区定位方式**三种混用**，复制到别处就跑不动：
      * `drama.py` / `gen_char_assets.py` / `gen_scene_assets.py` / `cost_report.py`
        —— 把 `<某个具体项目路径>` **硬编码**进去（本仓库已改为 repo 相对/环境变量）
      * `cost_ledger.py` / `episode_preflight.py` / `wire_*.py` / `_qa_subtitle_frame.py`
        —— 用 `__file__.parent.parent` 推断（只在「脚本住在 <项目>/scripts/ 下」时成立）
      * `subtitle.py` / `prepare_refs.py` —— 已经有 `--workspace`
    结果：脚本一旦离开这个项目目录就报「找不到 data/shots.json」之类的怪错。

解析优先级（高 → 低）：
    1. 函数参数 `explicit`（命令行 `--workspace` 传进来的值）
    2. 环境变量 `SOLODRAMA_WORKSPACE`（旧名 `DRAMA_WORKSPACE` 仍兼容）  ← 换项目/从 Skill 调用时用这个
    3. 脚本位置推断：`<项目>/scripts/xxx.py` ⇒ `<项目>`
    4. 报错并给出**可照抄的修法**（不静默猜路径）

用法：
    from _ws import WS          # 拿到 pathlib.Path
    from _ws import resolve     # 需要自己控制优先级时用
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 分阶段目录真源（stages/_layout.py）：本文件只做「解析工作区」，目录映射一律问它
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
try:
    import _layout as L  # noqa: E402
except Exception:  # noqa: BLE001  （极端情况下退化为旧布局，不阻塞主流程）
    L = None

# 判定「这个目录就是短剧工作区」的标志物
MARKERS = (
    Path("layout.json"),
    Path("model-plan.json"),
    Path("video-pipeline") / "data" / "shots.json",
    Path("video-pipeline") / "data",
)

# ★ 2026-10-13 项目改名为 SoloDrama：环境变量新名 SOLODRAMA_* 优先，旧名 DRAMA_* 继续兼容（过渡期）。
ENV_NAME = "SOLODRAMA_WORKSPACE"
ENV_LEGACY = "DRAMA_WORKSPACE"
ENV_NAMES = (ENV_NAME, ENV_LEGACY)


def env_workspace():
    """读工作区环境变量：`SOLODRAMA_WORKSPACE` 优先，回退旧名 `DRAMA_WORKSPACE`。"""
    for n in ENV_NAMES:
        v = os.environ.get(n)
        if v:
            return v
    return None

_HINT = (
    "[FAIL] 找不到短剧工作区。\n"
    "       请用下面任一方式指定（从高到低）：\n"
    "         ① 命令行加 --workspace \"<项目根目录>\"\n"
    "         ② 设环境变量：$env:{env} = \"<项目根目录>\"   （PowerShell）\n"
    "                      set {env}=<项目根目录>          （cmd）\n"
    "         ③ 或把脚本放在 <项目根>/scripts/ 下运行\n"
    "       工作区的标志物是 {mark}。"
).format(env=ENV_NAME, mark=str(MARKERS[0]))


def _looks_like_workspace(p: Path) -> bool:
    return any((p / m).exists() for m in MARKERS)


def resolve(explicit=None) -> Path:
    """按优先级解析工作区；解析不到直接退出并给出可照抄的修法。

    ★ 2026-10-20（反馈 P1-3 同类）：环境变量指向的目录**不存在**时不再直接退出，而是
      在 stderr 警告后继续走后面的优先级。原因：`--workspace` 常由脚本在 import 之后
      才解析，而 `WS = resolve()` 发生在 import 期 —— 一条过期的环境变量会让**显式**
      `--workspace` 也一起失效（实测：test_migrate_assets 13 例全红）。
      真的都解析不到时，仍然统一走 ④ 的提示退出（不会静默猜路径）。
    """
    # ① 命令行显式指定
    if explicit:
        p = Path(explicit).expanduser()
        if p.is_dir():
            return p.resolve()
        sys.exit("[FAIL] --workspace 指向的目录不存在：%s" % p)
    # ② 环境变量
    env = env_workspace()
    if env:
        p = Path(env).expanduser()
        if p.is_dir():
            return p.resolve()
        print("[WARN] 环境变量 %s 指向的目录不存在，已忽略：%s" % (ENV_NAME, p), file=sys.stderr)
    # ③ 脚本位置推断：<项目>/scripts/xxx.py
    cand = Path(__file__).resolve().parent.parent
    if _looks_like_workspace(cand):
        return cand
    # ④ 不猜，报错
    sys.exit(_HINT)


def resolve_lenient(explicit=None):
    """与 resolve 相同，但**不退出**：解析不到返回 None。

    给「只读、即使没有工作区也能跑」的脚本用（例如 rh_doctor 的双 Key 体检）。
    """
    if explicit:
        p = Path(explicit).expanduser()
        return p.resolve() if p.is_dir() else None
    env = env_workspace()
    if env:
        p = Path(env).expanduser()
        if p.is_dir():
            return p.resolve()
    cand = Path(__file__).resolve().parent.parent
    return cand if _looks_like_workspace(cand) else None


# 绝大多数脚本直接用这个
WS: Path = resolve()

# 引擎技术目录（config.*.json / ledger / logs）。新布局下仍叫 video-pipeline，
# 但 data/ 与 output/ 可能已被 layout.json 指到阶段目录 —— 所以**不要**用它拼 data/output。
VP: Path = (L.engine_root(WS) if L else WS / "video-pipeline")

# ★ 2026-10-16：出片引擎的输入/输出目录一律用这两个（分阶段目录真源）
DATA: Path = (L.data_dir(WS) if L else VP / "data")
OUT: Path = (L.out_dir(WS) if L else VP / "output")

# ★ 2026-10-19：**资产**（人物/场景/道具）出图产物与参考图原图的落点 = `04-资产/`
#   此前资产被打到 `<OUT>/assets/`（= 07-成片/assets），用户找不到。
#   ⚠ 迁移期：老项目若旧位置已有图而新位置为空，`L.assets_dir()` 会返回旧位置（零迁移兼容）。
ASSETS: Path = (L.assets_dir(WS) if L else VP / "output" / "assets")
ASSETS_NOTE: str = (L.assets_dir_note(WS) if L else "")

# 台账与日志仍在引擎目录下（不随阶段目录迁移）
LEDGER: Path = VP / "ledger"
LOGS: Path = VP / "logs"


def layout() -> dict:
    """当前工作区的分阶段目录映射（缺 layout.json 时为旧布局）。"""
    return L.load(WS) if L else {"_fallback": True, "stages": {}}


def stage(key: str) -> Path:
    """取某阶段目录（新布局）；旧布局下抛出可读错误。"""
    if not L:
        raise RuntimeError("stages/_layout.py 不可用，无法解析阶段目录")
    return L.stage_dir(WS, key)


# ★ 2026-10-16：函数式解析（**必须用这两个**，不要在导入期固化 DATA/OUT）
#   原因：`DATA` / `OUT` 是在 import 期用环境变量/位置推断算出来的常量。
#   对接受 `--workspace` 的脚本（convert_storyboard / ingest_check / script_timing_check 等），
#   必须按**参数里的工作区**重新解析，否则 `--workspace` 会被静默忽略 —— 这是本轮实测抓到的真缺陷。
def data_dir(ws=None) -> Path:
    """按指定工作区解析出片引擎输入目录（None = 用模块级 WS）。"""
    w = Path(ws).expanduser().resolve() if ws else WS
    return L.data_dir(w) if L else (w / "video-pipeline" / "data")


def out_dir(ws=None) -> Path:
    """按指定工作区解析出片引擎输出根。"""
    w = Path(ws).expanduser().resolve() if ws else WS
    return L.out_dir(w) if L else (w / "video-pipeline" / "output")


def assets_dir(ws=None) -> Path:
    """按指定工作区解析**资产落点**（人物/场景/道具出图产物 + 参考图原图）。

    新布局 = `<ws>/04-资产/`；旧项目未迁移时自动沿用 `<out>/assets/`（零迁移兼容）。
    """
    w = Path(ws).expanduser().resolve() if ws else WS
    return L.assets_dir(w) if L else (w / "video-pipeline" / "output" / "assets")


def release_dir(ws=None) -> Path:
    """按指定工作区解析**发布版成片目录**（`09-发行/剧集/`，文件名为 `EpisodeNN.mp4`）。"""
    w = Path(ws).expanduser().resolve() if ws else WS
    return L.release_episode_dir(w) if L else (w / "09-发行" / "剧集")


# ★ 2026-10-20（反馈 P0-3）：剧名唯一真源。
#   此前 cost_ledger.py 里写死 `DRAMA_DEFAULT = '七大姑催婚'`，于是**任何**项目跑
#   `drama.py cost` 都会产出「成本台账_七大姑催婚.xlsx」——交付物里混进无关剧名。
#   规则：brief.json（创作层契约）→ project.json（工作区元数据）→ 工作区目录名。
#   不猜正文、不读 md，只认结构化字段。
_NAME_KEYS = ("title", "剧名", "drama", "name", "slug")


def drama_name(ws=None) -> str:
    """从工作区推导剧名（取不到则用目录名，绝不返回空串）。"""
    w = Path(ws).expanduser().resolve() if ws else WS
    for fname in ("brief.json", "project.json"):
        p = w / fname
        if not p.is_file():
            continue
        try:
            import json as _json
            d = _json.loads(p.read_text(encoding="utf-8-sig"))
        except Exception:                                          # noqa: BLE001
            continue
        if not isinstance(d, dict):
            continue
        for k in _NAME_KEYS:
            v = str(d.get(k) or "").strip()
            if v:
                return v
    return w.name or "未命名项目"

