#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""drama.py —— 短剧生产线的零思考入口（把已跑通的重复动作固化成命令）

为什么有这个脚本
----------------
《七大姑催婚》量产阶段每次要重复的动作，之前都靠「翻文档 + 现场拼命令 + 逐个读脚本」，
token 全花在重复探索上。这里把它们固化成**稳定命令**：
每个命令都自带闸门（默认不花钱）、自带进度、跑完只吐**一份紧凑战报**，
人和 agent 都只需要读一份摘要，不必再读脚本源码或长日志。

命令一览（`python scripts/drama.py guide` 也会打印同样内容）
-----------------------------------------------------------
    next|do|nodes|graph|skip                ★七环节 23 节点调度（唯一编排）：看下一步 / 执行 / 全状态 /
                                          节点图 / 显式跳过（须给理由）
    init       --title ... --episodes N   ★建项目骨架（9 目录 + 6 模板，不写内容）
    style      list|status|set|reset|ask|require  ★画风库：形态 track × 视觉 look × 叙事 narrative
    bgm        library|plan|check|mix      ★配乐：库 → 铺排计划 → 混音（在字幕烧录前接）
    status     [--json]                  全盘状态面板：数据/参考图/资产缺口/批次/台账（零网络）
    models     [list|status|set|reset|ask]  ★前置条件：首次生图/出片前确认模型
                                          （本地 ComfyUI 一条通道；确认单写 model-plan.json）
    preflight                            一次性体检：Key 分级 + 引擎 doctor + check + 预演（全免费）
    assets     [--engine local|rh] [...] 缺失资产出图（默认本地 ComfyUI ￥0 且干跑）
                                          local=本机出图（不花钱，占 GPU）
                                          ★首次 --submit 前会先查模型选择门禁
    refs       [--apply]                 参考图瘦身（6000px 超 H3 上限 5760 必须做）
    video plan [--limit N] [--only ids]  出片计划与成本预估（免费，不提交）
    video run  --yes [...]               真跑出片（★计费；--yes 是闸门；★首次前会先查模型选择门禁）
    video status [BATCH]                 某批次进度（读 summary.json）
    report     [--latest|--batch ID]     战报：批次汇总 + 台账聚合 + 成本
    balance                              两把 Key 的余额（只读，不计费）
    cost [--checkpoint] [--balance] [--json]  成本台账：单次任务 + 全剧累计（markdown / JSON）
    guide                                打印这份速查

全局参数
--------
    --workspace <dir>   指定工作区（放在子命令**前后都行**：`drama.py --workspace X status`
                        与 `drama.py status --workspace X` 等价）。不给则依次读
                        SOLODRAMA_WORKSPACE / DRAMA_WORKSPACE 环境变量。

设计约定（照用户偏好来的）
--------------------------
* **默认不花钱**：所有会提交任务的命令都要显式 `--submit` / `--yes`，否则只干跑。
* **模型先确认**：每个项目**首次生图 / 首次出片**前必须先确认模型选择（本地 ComfyUI /
  只剩本地 ComfyUI）；确认单落 `<工作区>/model-plan.json`，未确认即停（退出码 4）。
* **进度可见**：子进程输出实时落日志文件，同时打印进度行；失败才回显日志尾部。
* **战报优先**：成功路径只打印几行摘要 + 产物绝对路径；不贴长日志。
* **机密不进文件**：Key 只从环境变量/用户级环境变量读，永不写盘、永不打印全文。
* **留痕自动化**：产物清单、引擎台账、批次 summary 都由脚本落盘，不需要手工登记。
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import time


# ---------------------------------------------------------------------------
#   这里不是「删掉调用点」，而是把出站通道收窄到本机/内网。任何试图连
#   某次合并里被悄悄加回来的 httpx 调用。细则见 stages/_netguard.py。
# ---------------------------------------------------------------------------
def _boot_netguard() -> None:
    import pathlib as _pl
    import sys as _sys
    for _p in _pl.Path(__file__).resolve().parents[:5]:
        for _cand in ((_p / "_netguard.py"), (_p / "stages" / "_netguard.py")):
            if _cand.is_file():
                if str(_cand.parent) not in _sys.path:
                    _sys.path.insert(0, str(_cand.parent))
                try:
                    import importlib as _il
                    _il.import_module("_netguard").install()
                except Exception:        # noqa: BLE001 —— 守卫自身异常不能拖垮主流程
                    pass
                return


_boot_netguard()




# ---------------------------------------------------------------------------
# ★ 早期分派：`init` 必须在任何依赖工作区的 import 之前切走
# ---------------------------------------------------------------------------
# `init` 的职责是「把工作区建出来」，此刻工作区当然不存在。而本模块下面马上就
# `_preset_workspace_from_argv()` + `import _ws`，两者都要求工作区已存在。
# 试图在本进程里「降级放行」会一路漏（WS/VP/DATA/OUT/LOG_DIR… 逐个 None 检查），
# 所以干脆在这里就交给 `init_project`，主流程一行都不走。
if 'init' in sys.argv[1:]:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    try:
        import init_project as _IP                              # noqa: E402
    except ImportError as _e:                                   # 缺文件是真错，别假装
        print('[FAIL] 找不到 init_project.py：%s' % _e)
        raise SystemExit(2)
    raise SystemExit(_IP.main([a for a in sys.argv[1:] if a != 'init']))


# ---------------------------------------------------------------------------
# ★ 全局 --workspace（反馈 P1-3）：必须在 `import _ws` **之前**生效
# ---------------------------------------------------------------------------
# 为什么不能只加个 argparse 参数：`_ws.WS` 是**导入期常量**（`WS = resolve()`），
# argparse 解析发生在导入之后 —— 参数加得再漂亮，工作区也早就定死了。
# 所以这里先手动扫一遍 argv，把显式工作区写进环境变量，再导入 _ws。
def _preset_workspace_from_argv(argv) -> bool:
    val = None
    for i, tok in enumerate(argv):
        if tok == '--workspace' and i + 1 < len(argv):
            val = argv[i + 1]
        elif tok.startswith('--workspace='):
            val = tok.split('=', 1)[1]
        if val is not None:
            break
    if val is None:
        return False
    p = pathlib.Path(val).expanduser()
    if not p.is_dir():
        # ★ 例外：`init` 的职责就是「让这个目录存在」，此处不能拦。
        #   否则「新建项目」永远要先手工 mkdir，等于把 init 的意义抵消掉。
        if 'init' in argv:
            os.environ['SOLODRAMA_WORKSPACE'] = str(p.resolve())
            return True
        print('[FAIL] --workspace 指向的目录不存在：%s' % p)
        raise SystemExit(2)
    os.environ['SOLODRAMA_WORKSPACE'] = str(p.resolve())
    return True


_WORKSPACE_FROM_CLI = _preset_workspace_from_argv(sys.argv[1:])

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
try:
    import _ws as _WSMOD  # noqa: E402  ★ 工作区解析 + 分阶段目录真源（见 scripts/_ws.py、stages/_layout.py）
    _WS = _WSMOD.WS
except SystemExit as _e:
    # ★ 2026-10-20：`--help` 不该要求工作区。`_ws` 在导入期就要解析工作区，
    #   没有合法工作区时会 SystemExit —— 那会让「想先看看有哪些命令」的人直接吃一个红。
    #   其它情况仍然原样抛出（缺工作区是真错，不该假装能跑）。
    # ★ 2026-11-01：`init` 同理 —— 它的职责是「把工作区建出来」，此刻当然还没有。
    #   这里降级成 `_WS = None`，`cmd_init_project` 走子进程，不碰这个进程里的工作区。
    if any(a in ('-h', '--help') for a in sys.argv[1:]):
        print('短剧生产线的零思考入口（默认不花钱）\n')
        print('用法: drama.py <命令> [...]  （init 之外都需要先指定工作区）')
        print('  全局参数: --workspace <DIR>   也可设环境变量 SOLODRAMA_WORKSPACE\n')
        print('命令: init / next / do / nodes / graph / skip /')
        print('      status / preflight / assets [--engine local] / refs /')
        print('      models / style / video {plan|run|resume-download|status} /')
        print('      report / balance / cost / guide')
        print('\n例：drama.py init --workspace "D:/剧/新剧" --title "剧名"')
        print('    drama.py --workspace "D:/剧/某剧" status')
        raise SystemExit(0)
    raise

WS = _WS
VP = _WSMOD.VP        # 引擎技术目录（config.*.json / ledger / logs）
DATA = _WSMOD.DATA    # 出片引擎输入目录（新布局 = 06-提示词；旧布局 = video-pipeline/data）
OUT = _WSMOD.OUT      # 出片引擎输出根（新布局 = 07-成片；旧布局 = video-pipeline/output）
# ★ 2026-10-10 修复：收编进本仓库后，生产脚本不再住在 <工作区>/scripts/，而是**与本文件同目录**
#   （`stages/production/scripts/`）。原先的 `WS / 'scripts'` 是上游项目布局的残留，
#   会让 gen_assets_local / ingest_check / subtitle 等子脚本全部找不到。
#   如需复刻旧布局，用环境变量 SOLODRAMA_SCRIPTS_DIR（旧名 DRAMA_SCRIPTS_DIR 仍兼容）覆盖。
SCRIPTS = pathlib.Path(os.environ.get('SOLODRAMA_SCRIPTS_DIR')
                       or os.environ.get('DRAMA_SCRIPTS_DIR')
                       or pathlib.Path(__file__).resolve().parent)
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[3]   # .../SoloDrama
# ★ 2026-11-04：`SKILL` / `RUN_PY` / `CHECK_BILLING` 三个常量已删 —— 它们指向
#   本地出片的入口是 stages/video/comfyui/comfy_batch_video.py。
COMFY_VIDEO_PY = _PROJECT_ROOT / 'stages' / 'video' / 'comfyui' / 'comfy_local_video.py'
MODEL_GATE_PY = SCRIPTS / 'model_gate.py'      # ★ 首次生图/出片前的模型选择门禁
LOG_DIR = OUT / 'logs'

SCENE_USD_PER_IMAGE = 0.01   # 实测：场景图扣美元钱包 $0.01/张 ≈ ￥0.07
USD_CNY = 7.0


# ---------------------------------------------------------------------------
# 环境：进程环境里没有的 Key，从「用户级环境变量」补（agent 的 shell 常拿不到）
# ---------------------------------------------------------------------------
def _harden_stdio() -> None:
    """控制台编码加固（中文 Windows GBK ↔ 管道 UTF-8）——实现统一在 `_util.harden_stdio()`。"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _util import harden_stdio
    harden_stdio()

def hydrate_env() -> None:
    # ★ 进程环境里缺的，从「用户级环境变量」补（agent 的 shell 常拿不到）。
    #   SOLODRAMA_ASSET_MD 是「资产提示词 md」真源，**本地通道也要用**。
    want = ('SOLODRAMA_ASSET_MD', 'DRAMA_ASSET_MD')
    os.environ.setdefault('PYTHONUTF8', '1')
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    os.environ['VIDEO_PIPELINE_WORKSPACE'] = str(VP)
    # ★ 2026-10-10：把已解析出的工作区**下传给子进程**。子脚本（gen_assets_local /
    #   ingest_check / time_report …）都靠 `_ws.resolve()` 定位工作区，而它们自己无法从
    #   脚本位置推断出来（脚本住在仓库里，不在工作区里）—— 不传就会全部报「找不到短剧工作区」。
    #   ★ 两个名字都下发：子脚本读新名，外部工具/用户脚本若仍读旧名也不会失灵。
    os.environ.setdefault('SOLODRAMA_WORKSPACE', str(WS))
    os.environ.setdefault('DRAMA_WORKSPACE', str(WS))
    missing = [n for n in want if not os.environ.get(n)]
    if not missing or os.name != 'nt':
        return
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as k:
            for n in missing:
                try:
                    v, _ = winreg.QueryValueEx(k, n)
                except FileNotFoundError:
                    continue
                if v:
                    os.environ[n] = str(v)
    except Exception:                                          # noqa: BLE001
        pass


def read_json(p: pathlib.Path, default=None):
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return default


def mask(v: str) -> str:
    v = (v or '').strip()
    return '(未设置)' if not v else (v[:6] + '****' + v[-4:] if len(v) > 10 else '****')


def has(key: str) -> str:
    return '有' if os.environ.get(key) else '缺'


# ---------------------------------------------------------------------------
# 子进程执行：实时进度 + 落日志；失败才回显尾部
# ---------------------------------------------------------------------------
def run_cmd(cmd: list, log_name: str, quiet_ok: bool = True) -> tuple:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = LOG_DIR / ('%s_%s.log' % (log_name, time.strftime('%Y%m%d_%H%M%S')))
    print('  $ %s' % ' '.join(str(c) for c in cmd[1:]))
    print('  日志: %s' % log)
    t0 = time.time()
    with open(log, 'w', encoding='utf-8', errors='replace') as fh:
        proc = subprocess.Popen([str(c) for c in cmd], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True,
                                encoding='utf-8', errors='replace', bufsize=1,
                                cwd=str(WS))
        tail = []
        for line in proc.stdout:                                # type: ignore[union-attr]
            fh.write(line)
            fh.flush()
            tail.append(line.rstrip('\n'))
            if len(tail) > 40:
                tail.pop(0)
            if not quiet_ok:
                print('  | ' + line.rstrip('\n'))
        rc = proc.wait()
    dt = round(time.time() - t0, 1)
    if rc != 0:
        print('  [失败] 退出码 %s（耗时 %.1fs），日志尾部：' % (rc, dt))
        for line in tail[-18:]:
            print('  | ' + line)
        # ★ 2026-10-20（反馈 P1-4）：依赖没装时原始报错是 `ModuleNotFoundError: httpx`，
        #   看起来像配置错/代码错。这里直接把「装什么」喊出来。
        if any('ModuleNotFoundError' in ln for ln in tail):
            print('  [依赖缺失] 引擎依赖未安装。在本仓库根目录执行：')
            print('    %s -m pip install -r requirements.txt' % sys.executable)
    return rc, log, dt


# ---------------------------------------------------------------------------
# 状态面板
# ---------------------------------------------------------------------------
def _img_size(p: pathlib.Path):
    try:
        from PIL import Image
        with Image.open(p) as im:
            return im.size
    except Exception:                                          # noqa: BLE001
        return (0, 0)


def collect_status() -> dict:
    shots = read_json(data_f('shots.json'), []) or []
    prompts = read_json(data_f('h3_prompts.json'), {}) or {}
    chars = read_json(data_f('characters.json'), {}) or {}
    assets_cfg = read_json(VP / 'config.assets.json', {}) or {}
    char_man = read_json(DATA / 'char_assets_manifest.json', {}) or {}
    scene_man = read_json(DATA / 'scene_assets_manifest.json', {}) or {}
    local = read_json(VP / 'config.local.json', {}) or {}

    # 参考图
    refs = []
    for k, v in chars.items():
        if k.startswith('_'):
            continue
        p = pathlib.Path(v)
        if not p.is_absolute():
            p = DATA / p
        w, h = _img_size(p) if p.is_file() else (0, 0)
        refs.append({'key': k, 'file': p.name, 'exists': p.is_file(),
                     'size': [w, h], 'h3_over_limit': max(w, h) > 5760})

    # 资产缺口：以「资产提示词 md 的节号」为准（与 gen_char_assets/gen_scene_assets 同一口径），
    # 不用 config.assets.json 里那套补充清单 C 号（两套编号不可混用，见人物资产文档）。
    char_prompts = read_json(DATA / 'char_prompts.json', {}) or {}
    scene_prompts = read_json(DATA / 'scene_prompts.json', {}) or {}
    gen_chars = {str(it.get('name')) for it in char_man.get('items', [])}
    gen_seqs = {it.get('section') for it in char_man.get('items', [])}
    gen_scene_seqs = {it.get('section') for it in scene_man.get('items', [])}

    #   避免同一个角色本地出过了、面板还在喊缺口（通道信息保留在各自 manifest 里）。
    comfy_man = read_json(DATA / 'comfyui_assets_manifest.json', {}) or {}
    comfy_items = [it for it in comfy_man.get('items', []) if it.get('files')]
    loc_chars = {it.get('section') for it in comfy_items if it.get('kind') == 'char'}
    loc_scenes = {it.get('section') for it in comfy_items if it.get('kind') == 'scene'}
    gen_chars |= {str(it.get('name')) for it in comfy_items if it.get('kind') == 'char'}
    gen_seqs |= loc_chars
    gen_scene_seqs |= loc_scenes

    miss_chars = []
    for c in char_prompts.get('characters', []):
        if c.get('have_image') or c.get('section') in gen_seqs:
            continue
        miss_chars.append('%d %s' % (c.get('section'), c.get('name')))
    miss_scenes = []
    for s in scene_prompts.get('scenes', []):
        if s.get('have_image') or s.get('section') in gen_scene_seqs:
            continue
        miss_scenes.append('%d %s' % (s.get('section'), s.get('name')))
    miss = assets_cfg.get('missing_assets', {}) or {}

    # 视频批次
    batches = []
    out_root = OUT
    if out_root.is_dir():
        for d in sorted(out_root.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if not d.is_dir():
                continue
            s = read_json(d / 'summary.json')
            if s:
                batches.append({'batch': d.name, 'totals': s.get('totals', {}),
                                'usage': s.get('usage', {}),
                                'elapsed': s.get('elapsed_seconds'),
                                'fuse': s.get('fuse', {})})

    # 台账聚合（★ 2026-11-04：口径从「花了多少币」改为「占了多少 GPU 时间」）
    # 本机出片零费用，唯一稀缺资源是时间。所以这里不再读 consumeCoins /
    # thirdPartyConsumeMoney（那两个字段只有平台任务才有），改为累加 wall_elapsed_s。
    led = {'files': 0, 'success': 0, 'failed': 0, 'wall_sec': 0.0}
    lr = VP / 'ledger' / 'runs'
    if lr.is_dir():
        for f in lr.glob('*.json'):
            d = read_json(f, {}) or {}
            for a in d.get('attempts', []):
                if a.get('status') == 'SUCCESS':
                    led['success'] += 1
                elif a.get('status') == 'FAILED':
                    led['failed'] += 1
                try:
                    led['wall_sec'] += float(a.get('elapsed') or a.get('wall_elapsed_s') or 0)
                except (TypeError, ValueError):
                    pass
        led['files'] = len(list(lr.glob('*.json')))

    # 节点映射就绪度（G2）
    h3n = (local.get('h3') or {}).get('nodes') or {}
    slots = (h3n.get('char_ref') or {}).get('slots') or []

    return {
        'data': {'shots': len(shots), 'prompts': len(prompts)},
        'refs': refs,
        # ★ 2026-10-20（反馈 P1-5）：场景计数此前误用 `gen_seqs`（**人物**节号集合），
        #   于是「场景资产：已生成 N 个」实际显示的是人物数（10），与本地出图面板的
        #   场景 13 张自相矛盾。这里改用场景自己的集合 `gen_scene_seqs`。
        'assets': {'char_generated': sorted(gen_chars), 'scene_generated': sorted(gen_scene_seqs),
                   'missing_characters': miss_chars, 'missing_scenes': miss_scenes,
                   'local_generated': len(comfy_items), 'local_chars': len(loc_chars),
                   'local_scenes': len(loc_scenes)},
        'h3': {'kind': (local.get('h3') or {}).get('kind'),
               'id': (local.get('h3') or {}).get('id'),
               'prompt_node': bool((h3n.get('prompt') or {}).get('nodeId')),
               'ref_slots': len([s for s in slots if s.get('nodeId')]),
               'ratio_node': bool((h3n.get('ratio') or {}).get('nodeId')),
               'duration_node': bool((h3n.get('duration') or {}).get('nodeId')),
               'ready': bool((h3n.get('prompt') or {}).get('nodeId') and slots)},
        'batches': batches[:5],
        'ledger': led,
        # 2026-11-04：原来这里报的是 RH Key 有没有配。现在没有平台 Key 这回事了，
        # 换成「出口守卫是否生效」—— 这才是此刻真正该盯的运行时状态。
        'netguard': _netguard_state(),
    }


def _selected_shots(limit=None, only=None) -> list:
    shots = read_json(data_f('shots.json'), []) or []
    if only:
        want = {o.strip() for o in only if o and o.strip()}
        shots = [s for s in shots if s.get('shot_id') in want]
    if limit:
        shots = shots[:limit]
    return shots


def _durations(shots) -> list:
    prompts = read_json(data_f('h3_prompts.json'), {}) or {}
    out = []
    for s in shots:
        e = prompts.get(s.get('shot_id')) or {}
        d = e.get('duration') if isinstance(e, dict) else None
        try:
            out.append(float(d))
        except (TypeError, ValueError):
            out.append(12.0)
    return out


def cmd_init_project(args) -> int:
    """转发到 `init_project.py`（子进程）。

    ★ 为什么不用 import：本模块在文件顶部 `_preset_workspace_from_argv()` +
      `import _ws` 就要求工作区**已存在**。而 init 的职责正是「让它存在」——
      在本进程里调用必然先死在 import 上。子进程是这里唯一干净的隔离方式。
    """
    import subprocess
    here = pathlib.Path(__file__).resolve().parent
    cmd = [sys.executable, str(here / "init_project.py")]
    ws = getattr(args, "workspace", None)
    if not ws:
        print("[FAIL] init 必须显式给 --workspace（新建项目的路径，可以还不存在）")
        return 2
    cmd += ["--workspace", str(ws)]
    for k in ("title", "platform", "episodes", "ep_seconds", "track", "look",
              "narrative", "aspect", "world", "region",
              "image_engine", "video_engine"):
        v = getattr(args, k, None)
        if v not in (None, ""):
            cmd += ["--" + k.replace("_", "-"), str(v)]
    if getattr(args, "force", False):
        cmd.append("--force")
    if getattr(args, "dry_run", False):
        cmd.append("--dry-run")
    return subprocess.run(cmd, cwd=str(here.parents[2])).returncode


def _nodes_mod():
    """延迟导入：`nodes.py` 依赖 `_layout`，导入期就会解析工作区。"""
    import nodes as _N
    return _N


def _ws_argv(args) -> list:
    """`--workspace` 只在真的给了时才转发。

    ★ 这里的坑：`_add_ws_arg` 的默认值是 `None`，直接 `str(None)` 会传成字面量
      "None"，nodes.py 于是把它当成一个叫 None 的目录，报
      `D:\\编程\\SoloDrama\\None\\03-剧本\\blueprint.md`。
      实际生效点在 `_preset_workspace_from_argv()`，转发层不该再造一次。
    """
    v = getattr(args, "workspace", None)
    return ["--workspace", str(v)] if v else []


def cmd_next_node(args) -> int:
    argv = ["next"]
    if getattr(args, 'ep', ''):
        argv += ['--ep', args.ep]
    if getattr(args, 'json', False):
        argv.append('--json')
    return _nodes_mod().main(argv + _ws_argv(args))


def cmd_do_node(args) -> int:
    argv = ["do", args.node] + _ws_argv(args)
    if getattr(args, 'ep', ''):
        argv += ['--ep', args.ep]
    if getattr(args, 'dry_run', False):
        argv.append('--dry-run')
    if getattr(args, 'yes', False):
        argv.append('--yes')
    return _nodes_mod().main(argv)


def cmd_nodes_status(args) -> int:
    argv = ["status"] + _ws_argv(args)
    if getattr(args, 'ep', ''):
        argv += ['--ep', args.ep]
    if getattr(args, 'json', False):
        argv.append('--json')
    return _nodes_mod().main(argv)


def cmd_nodes_graph(args) -> int:
    argv = ["graph"] + (['--json'] if getattr(args, 'json', False) else [])
    return _nodes_mod().main(argv)


def cmd_skip_node(args) -> int:
    return _nodes_mod().main(["skip", args.node, "--reason", args.reason]
                             + _ws_argv(args))


PER_EP_FILES = ("shots.json", "h3_prompts.json", "boards.json",
                 "characters.json", "scenes.json")


def data_f(name: str):
    """数据文件路径：优先 `<DATA>/<name>`，再找各集子目录里最新的一份。

    ★ 2026-11-01：data 起按集分目录（`data/ep01/shots.json`）；2026-11-02 起由
      `stages/import/pack_import.py` 从制作包生成同一结构。
      本文件里十几处 `DATA / "shots.json"` 于是全部读空，`drama status` 显示「没有分镜」，
      而文件就在 `data/ep01/` 里 —— 症状像「数据丢了」，其实是读错了目录。
    """
    p = DATA / name
    if p.is_file() or not DATA.is_dir():
        return p
    hits = [q for q in DATA.glob("*/%s" % name) if q.is_file()]
    return max(hits, key=lambda q: q.stat().st_mtime) if hits else p


def cmd_status(args) -> int:
    st = collect_status()
    if args.json:
        print(json.dumps(st, ensure_ascii=False, indent=2))
        return 0
    d, a, h3, led = st['data'], st['assets'], st['h3'], st['ledger']
    print('=' * 74)
    print('短剧生产线状态面板')
    print('=' * 74)
    print('数据        : 分镜 %d 段 | H3 提示词 %d 条' % (d['shots'], d['prompts']))
    ok = [r for r in st['refs'] if r['exists']]
    over = [r for r in st['refs'] if r['h3_over_limit']]
    print('参考图      : %d/%d 张在位%s' % (
        len(ok), len(st['refs']),
        '；★ %d 张长边 >5760px 超 H3 上限，需跑 refs' % len(over) if over else '；尺寸均在上限内'))
    print('H3 映射     : kind=%s id=%s | 提示词节点=%s 参考槽位=%d 画幅=%s 时长=%s -> %s'
          % (h3['kind'], h3['id'], '有' if h3['prompt_node'] else '缺', h3['ref_slots'],
             '有' if h3['ratio_node'] else '缺', '有' if h3['duration_node'] else '缺',
             'G2 就绪' if h3['ready'] else 'G2 未就绪'))
    print('人物资产    : 已生成 %d 个 | 缺口 %d 个 %s'
          % (len(a['char_generated']), len(a['missing_characters']),
             ('（%s）' % '、'.join(a['missing_characters'][:6]) + ('…' if len(a['missing_characters']) > 6 else '')) if a['missing_characters'] else ''))
    print('场景资产    : 已生成 %d 个 | 缺口 %d 个 %s'
          % (len(a['scene_generated']), len(a['missing_scenes']),
             ('（%s）' % '、'.join(a['missing_scenes'][:5]) + ('…' if len(a['missing_scenes']) > 5 else '')) if a['missing_scenes'] else ''))
    if a.get('local_generated'):
        print('本地出图    : %d 项（人物 %d / 场景 %d）— 本地 ComfyUI 通道，￥0 成本'
              % (a['local_generated'], a['local_chars'], a['local_scenes']))
    ng = st.get('netguard') or {}
    print('出口守卫    : %s%s'
          % ('已启用（只许本机/内网）' if ng.get('installed') else '[未启用] 立即检查 stages/_netguard.py',
             '  ★ 已放宽远端（RH 仍禁止）' if ng.get('allow_remote') else
             ('  ' + ng['error'] if ng.get('error') else '')))
    print('台账        : %d 个任务文件 | 成功 %d / 失败 %d | 累计占用 %.1f 分钟'
          % (led['files'], led['success'], led['failed'], led['wall_sec'] / 60.0))
    if st['batches']:
        for b in st['batches']:
            t = b['totals'] or {}
            empty = not t.get('success') and not t.get('failed')
            print('批次 %-16s: 总 %s 成功 %s 失败 %s 跳过 %s 待跑 %s%s%s'
                  % (b['batch'], t.get('total'), t.get('success'), t.get('failed'),
                     t.get('skipped'), t.get('pending'),
                     '  ★熔断' if (b['fuse'] or {}).get('blown') else '',
                     '  （预演/空批次）' if empty else ''))
    else:
        print('批次        : 还没有跑过出片批次')
    print('-' * 74)
    print('下一步提示  : 缺参考图尺寸 → `refs --apply`；缺资产 → `assets`（干跑）；'
          '出片 → `video plan` 看成本')
    return 0


# ---------------------------------------------------------------------------
# preflight：一把过体检（全免费）
# ---------------------------------------------------------------------------
def _is_noise(detail: str) -> bool:
    """本线只用 --video-only，图片工作流(banana)未配置属于**已知噪音**，不该当成失败。

    实测：医生的 FAIL 有两条都属这一类 —— `provider_id`（detail 写「图片模型 [banana] id = (未填写)」）
    与 `nodes`（detail 写 image_providers[...]）。所以两类关键词都要认。
    """
    s = str(detail)
    return any(k in s for k in ('image_providers', 'banana', '图片模型'))


# ★ 2026-10-20（反馈 P1-4）：preflight 的**第一步**必须是依赖自检。
#   此前直接跑 rh_doctor / doctor，缺 httpx 时第一屏就是 `ModuleNotFoundError: httpx`，
#   新机器上极易被误判成「配置错」。这里先自检，缺什么直接把安装命令给出来。
_REQUIRED_MODULES = (
    ('PIL', '本地出图的参考图裁剪与尺寸（引擎 assets）'),
    ('PIL', '九宫格裁剪与图片尺寸（引擎 pipeline）'),
)


def _netguard_state() -> dict:
    """出口守卫当前状态（给 status 看）。

    为什么状态面板要有这一项：本仓库唯一的硬约束就是「不许调平台 API」，
    而它生效与否是**运行期**的事 —— 装没装、有没有被 SOLODRAMA_ALLOW_REMOTE 放宽，
    光看代码看不出来。放在 status 第一屏，出问题时一眼就知道该查哪里。
    """
    st = {'installed': False, 'allow_remote': False, 'error': ''}
    try:
        import _netguard as ng          # 同目录 / stages 根，drama 已把它塞进 sys.path
        st['installed'] = bool(getattr(ng, '_installed', False))
        st['allow_remote'] = bool(ng._allow_remote())
    except Exception as exc:            # noqa: BLE001
        st['error'] = '%s: %s' % (type(exc).__name__, exc)
    return st


def check_dependencies() -> list:
    """返回 [(模块, 用途, 是否可用), ...]（纯离线，不联网）。"""
    import importlib.util
    out = []
    for mod, why in _REQUIRED_MODULES:
        try:
            ok = importlib.util.find_spec(mod) is not None
        except (ImportError, ValueError):
            ok = False
        out.append((mod, why, ok))
    return out


def _print_dep_report(rows) -> bool:
    bad = [r for r in rows if not r[2]]
    for mod, why, ok in rows:
        print('  %-6s %s  %s' % (mod, '[OK]' if ok else '[NG] 未安装', why))
    if bad:
        print('  ★ 缺 %d 项运行依赖，后面几步必然崩（不是配置错）。安装：' % len(bad))
        print('    %s -m pip install -r %s' % (sys.executable, _PROJECT_ROOT / 'requirements.txt'))
    return not bad


def cmd_preflight(args) -> int:
    """一次过体检：依赖 → 出口守卫 → 数据契约 → ComfyUI。

    ★ 2026-11-04 重写：四步全部只依赖本仓库现存的东西，且每一步都能给出「怎么修」。
    """
    verdict = []

    print('【0/4】运行依赖自检（不联网）')
    if not _print_dep_report(check_dependencies()):
        verdict.append(('运行依赖', False, '装完依赖再体检'))
        return _preflight_report(verdict)
    verdict.append(('运行依赖', True, ''))

    print('\n【1/4】网络出口守卫（用户强制命令：禁止任何平台 API 调用）')
    ng_ok, ng_note = _preflight_netguard()
    verdict.append(('出口守卫', ng_ok, ng_note))

    print('\n【2/4】数据契约（制作包导入的产品）')
    dc_ok, dc_note = _preflight_data()
    verdict.append(('数据契约', dc_ok, dc_note))

    print('\n【3/4】本机 ComfyUI（出图与出片共用的唯一通道）')
    cf_ok, cf_note = _preflight_comfy()
    verdict.append(('ComfyUI', cf_ok, cf_note))

    return _preflight_report(verdict)


def _preflight_report(verdict) -> int:
    print('\n' + '=' * 74)
    print('体检结论')
    print('=' * 74)
    for name, ok, extra in verdict:
        print('  %-12s %s %s' % (name, '[OK] 通过' if ok else '[NG] 需处理', extra))
    print('  日志目录：%s' % LOG_DIR)
    return 0 if all(v[1] for v in verdict) else 1


def _preflight_netguard() -> tuple:
    """核对出口守卫：装上了没有、黑名单是否真的拦得住。"""
    try:
        import _netguard as ng
    except Exception as exc:                     # noqa: BLE001
        print('  [NG] 找不到 stages/_netguard.py：%s' % exc)
        return False, '守卫缺失'
    rows = ng.selfcheck()
    bad = [r for r in rows if not r[1]]
    for name, ok, detail in rows:
        print('  %s %-22s %s' % ('[OK] ' if ok else '[NG] ', name, detail))
    if bad:
        return False, '%d 条判定不符' % len(bad)
    return True, '仅本机+内网；RH 全域拒绝'


def _preflight_data() -> tuple:
    """逐集跑入厂门禁（ingest_check），把它的结论汇总成一条。

    为什么是子进程而不是 import：`ingest_check` 只暴露 `main()`，它的口径
    （退出码 + stdout）本来就是给人看的。在这里复刻一份判断逻辑，
    迟早会和它分叉 —— 而「两个门禁说法不一样」比没有门禁更耗人。
    """
    d = DATA
    eps = [x for x in d.iterdir() if x.is_dir() and (x / 'shots.json').is_file()] if d.is_dir() else []
    if not eps:
        print('  [--] 还没有导入任何一集（%s 下无 shots.json）' % d)
        print('       先跑：drama pack import --pack <制作包目录> --apply')
        # 没导入不算失败：preflight 对「刚建好的空项目」也要能跑。
        return True, '尚未导入（正常，若刚建项目）'
    print('  已导入 %d 集：%s' % (len(eps), '、'.join(sorted(x.name for x in eps)[:8])))
    bad = 0
    for x in sorted(eps):
        rc, _, _ = run_cmd([sys.executable, str(SCRIPTS / 'ingest_check.py'), '--ep', x.name],
                           'preflight_ingest_%s' % x.name)
        if rc != 0:
            bad += 1
            print('  [NG] %s 未通过入厂门禁（详见日志）' % x.name)
    if bad:
        return False, '%d 集未过门禁' % bad
    return True, '%d 集通过入厂门禁' % len(eps)


def _preflight_comfy() -> tuple:
    """ComfyUI 在线 + 出片工作流可提交。没启动算 WARN（出片时会自动拉起）。"""
    import urllib.request as _ur
    base = (os.environ.get('COMFYUI_URL') or 'http://127.0.0.1:8188').rstrip('/')
    try:
        with _ur.urlopen(base + '/system_stats', timeout=5) as r:
            stats = json.loads(r.read().decode('utf-8', 'replace'))
        dev = (stats.get('devices') or [{}])[0]
        print('  [OK] %s 在线（%s · 空闲 %.1fG）'
              % (base, dev.get('name') or '?', (dev.get('vram_free') or 0) / 1024 ** 3))
    except Exception as exc:                       # noqa: BLE001
        print('  [--] %s 未启动（%s）' % (base, type(exc).__name__))
        print('       出图/出片时会自动拉起后台实例；也可以先开 ComfyUI 桌面版。')
        return True, '未启动（会自动拉起）'
    if not COMFY_VIDEO_PY.is_file():
        print('  [NG] 找不到出片客户端 %s' % COMFY_VIDEO_PY)
        return False, '客户端缺失'
    rc, _, _ = run_cmd([sys.executable, str(COMFY_VIDEO_PY), '--check'], 'preflight_comfy', quiet_ok=False)
    if rc != 0:
        return False, '出片工作流体检未通过（见上）'
    return True, '在线，出片工作流可提交'


# ---------------------------------------------------------------------------
# models：首次生图 / 出片前的「模型选择」门禁（前置条件）
# ---------------------------------------------------------------------------
def _model_gate(kind: str, expected_engine=None) -> int:
    """查门禁。返回 0 = 放行；4 = 等待用户确认（★关卡停点）；2 = 其它问题。

    规则（详见 stages/production/scripts/model_gate.py）：
      * 每个项目在**首次生图 / 首次出片**前，必须先确认模型选择；
      * 确认单落在 <工作区>/model-plan.json（不进仓库）；
      * 确认了 A 却跑 B（如确认本地却用 --engine rh）→ 同样拦下，防账实不符。
    """
    import model_gate
    ok, msg = model_gate.require(WS, kind, expected_engine=expected_engine)
    if ok:
        print('  [门禁] %s' % msg)
        return 0
    print(model_gate.render_confirm_request(kind, WS))
    print('[门禁] %s' % msg)
    return model_gate.EXIT_WAIT_CONFIRM


def cmd_models(args) -> int:
    """转发给 model_gate.py（status / list / set / reset / ask / require）。"""
    cmd = [sys.executable, MODEL_GATE_PY, '--workspace', str(WS)]
    if getattr(args, 'models_cmd', None) == 'list':
        cmd.append('list')
    elif getattr(args, 'models_cmd', None) == 'set':
        cmd += ['set'] + list(args.pairs or [])
        if getattr(args, 'detail', None):
            cmd += ['--detail', args.detail]
        for flag in ('comfy_url', 'comfy_workflow'):
            v = getattr(args, flag, None)
            if v:
                cmd += ['--' + flag.replace('_', '-'), str(v)]
    elif getattr(args, 'models_cmd', None) == 'reset':
        cmd += ['reset', args.kind]
    elif getattr(args, 'models_cmd', None) == 'ask':
        cmd += ['ask', args.kind]
    else:                                    # 默认 status
        cmd.append('status')
        if getattr(args, 'json', False):
            cmd.append('--json')
    return run_cmd(cmd, 'models', quiet_ok=False)[0]


def cmd_pack(args) -> int:
    """制作包：导入（校验 + 写 data/）、预配置落地。

    三个动作对应新分支的三件事：
      * `pack import` —— 把创作 Skill 的产物变成引擎能吃的 data/（唯一入口）
      * `pack preset` —— 把出图/出片/放大通道一次性落到工作区
      * `pack check`  —— 只校验制作包，不写任何文件（给上游 Skill 自查用）
    """
    sub = getattr(args, 'pack_cmd', None) or 'import'
    if sub == 'preset':
        cmd = [sys.executable, str(IMPORT_PY / 'preset_apply.py')]
        if getattr(args, 'list', False):
            cmd += ['--list']
        if getattr(args, 'preset', None):
            cmd += ['--preset', args.preset]
        if getattr(args, 'apply', False):
            cmd += ['--apply']
        if getattr(args, 'json', False):
            cmd += ['--json']
        if getattr(args, 'workspace', None):
            cmd += ['--workspace', args.workspace]
        return run_cmd(cmd, 'pack_preset', quiet_ok=False)[0]

    pack = _pack_dir(args)
    if not pack:
        print('[FAIL] 找不到制作包：给 --pack "<目录>"，或把它放到 <工作区>/pack/ 下')
        return 2
    cmd = [sys.executable, str(IMPORT_PY / 'pack_import.py'), '--pack', pack]
    if getattr(args, 'ep', None):
        cmd += ['--ep', args.ep]
    if getattr(args, 'prune', False):
        cmd += ['--prune']
    if sub == 'import' and getattr(args, 'apply', False):
        cmd += ['--apply']
    if getattr(args, 'json', False):
        cmd += ['--json']
    if getattr(args, 'workspace', None):
        cmd += ['--workspace', args.workspace]
    title = {'import': '制作包导入', 'check': '制作包校验（只读）'}.get(sub, sub)
    print('【%s】%s' % (title, pack))
    return run_cmd(cmd, 'pack_' + sub, quiet_ok=False)[0]


def _pack_dir(args) -> str | None:
    """解析制作包目录：显式 `--pack` > `<ws>/pack`（存在才算）。

    为什么默认 `<ws>/pack`：新分支的输入契约就放在那里（见 docs/pack/PACK-SPEC.md），
    导入器、出图、预配置都按这个位置找。让用户每次手打一遍路径，等于把这个约定
    降级成「口头约定」—— 迟早有人放到别处，然后报「找不到 pack.json」。
    """
    p = getattr(args, "pack", None)
    if p:
        # 必须转绝对：`run_cmd` 的 cwd 是工作区，相对路径会被解析到工作区下去，
        # 报「制作包目录不存在」而实际它就在仓库里。
        return str(pathlib.Path(p).expanduser().resolve())
    ws = getattr(args, "workspace", None) or os.environ.get("SOLODRAMA_WORKSPACE") \
        or os.environ.get("DRAMA_WORKSPACE") or ""
    if not ws:
        return None
    cand = pathlib.Path(ws).expanduser().resolve() / "pack"
    return str(cand) if (cand / "pack.json").is_file() else None


def cmd_assets_local(args) -> int:
    """本地 ComfyUI 通道（￥0 成本）。默认干跑；--submit 才真的出图（不花钱，占 GPU）。"""
    if getattr(args, 'check', False):
        print('【本地 ComfyUI 体检】（只读 /system_stats，不出图）')
        rc, _, _ = run_cmd([sys.executable, LOCAL_ASSETS_PY, '--check'], 'assets_local_check',
                           quiet_ok=False)
        return rc
    if args.submit:                       # ★ 首次生图前：模型选择门禁
        rc = _model_gate('image', expected_engine='local')
        if rc:
            return rc
    cmd = [sys.executable, LOCAL_ASSETS_PY]
    pack = _pack_dir(args)
    if pack:
        cmd += ['--pack', pack]
    if args.kind and args.kind != 'all':
        cmd += ['--kind', args.kind]
    if args.only:
        cmd += ['--only', args.only]
    if args.force:
        cmd += ['--force']
    if args.submit:
        cmd += ['--submit']
    print('【资产出图 · 本地 ComfyUI】%s（￥0 成本；先出一张确认风格再批量）'
          % ('★真实出图' if args.submit else '干跑，不占 GPU'))
    rc, _, _ = run_cmd(cmd, 'assets_local', quiet_ok=False)
    return rc


def cmd_assets(args) -> int:
    """资产出图 —— **只有本地 ComfyUI 一条通道**。

    ★ 2026-11-04：只有本地一条通道。传 `--engine wf|rh` 会明确报错，
      而不是静默回落到本地 —— 后者会让人以为「切了通道」，其实一直在跑本机。
    """
    eng = getattr(args, 'engine', 'local')
    if eng != 'local':
        print('[FAIL] 只剩本地通道：--engine=%s 已不可用' % eng)
        return 2
    return cmd_assets_local(args)


def _latest_batch() -> str:
    out_root = OUT
    best, best_t = None, 0.0
    if out_root.is_dir():
        for d in out_root.iterdir():
            if d.is_dir() and (d / 'summary.json').is_file():
                t = (d / 'summary.json').stat().st_mtime
                if t > best_t:
                    best, best_t = d.name, t
    return best or ''


def cmd_video_plan(args) -> int:
    """出片计划：**时间口径**（不提交任何任务）。

    2026-11-04 起成本口径从「钱」改为「时间」：本机出片零费用，唯一的稀缺资源是 GPU 时间。
    所以这张表回答的是「这一集要占多久、时间花在哪一阶段」，而不是「要花多少币」。
    """
    import time_model as TM

    only = args.only.split(',') if args.only else None
    shots = _selected_shots(args.limit, only)
    durs = _durations(shots) or []
    n = len(shots) or 1
    avg = (sum(durs) / len(durs)) if durs else 6.0
    # 本集参考图张数：把每镜的 cast 求并集（同一张图在多个镜里出现只算一次）
    keys = set()
    for s in shots:
        for k in (s.get("cast") or []) + list(s.get("character_refs") or []) + list(s.get("scene_refs") or []):
            keys.add(str(k))
    n_img = len(keys) or n

    p = TM.load_params(WS)
    ep = TM.estimate_episode(n, avg, n_img, params=p)

    print('出片计划（时间口径，不提交任何任务）')
    print('-' * 74)
    print('  将提交      : %d 段（平均 %.1fs/段）' % (n, avg))
    print('  参考图      : %d 张（本集）' % n_img)
    print('  硬件        : %s' % (ep.get('hardware') or '本机'))
    print('-' * 74)
    for ph in ep['phases']:
        print('  %-10s %-14s %s' % (ph['label'], ph['human'], ph['detail']))
    print('-' * 74)
    print('  合计        : %s ｜ 瓶颈：%s' % (ep['total_human'], ep['bottleneck']))
    if ep['confidence'] != TM.CONF_MEASURED:
        print()
        print('  [注意] 系数是经验值，尚未在本机实测。首次真跑后校准一次，这张表就准了：')
        print('    python stages/production/scripts/time_model.py --calibrate --workspace "%s"' % WS)
    if args.limit:
        print()
        print('  本次只跑前 %d 段（--limit），时间为其中一部分。' % args.limit)
    print()
    print('  真实跑（占 GPU，不花钱）：')
    print('    python stages/production/scripts/drama.py video run --ep %s --yes%s'
          % (getattr(args, 'ep', None) or 'ep01',
             (' --only ' + args.only) if args.only else ''))
    print('  先小样更稳（1 段）：')
    print('    python stages/production/scripts/drama.py video run --ep %s --limit 1 --yes'
          % (getattr(args, 'ep', None) or 'ep01'))
    if getattr(args, 'json', False):
        import json as _json
        print()
        print(_json.dumps(ep, ensure_ascii=False, indent=2))
    return 0


def cmd_video_local(args) -> int:
    """本地 ComfyUI 批量出片（￥0，占 GPU）。

    单卡并发只能是 1；产物落 `07-成片/<ep>/<shot>/final.mp4`，
    后续 video.audit / 剪辑读的是同一个落点。
    """
    ep = getattr(args, 'ep', None) or 'ep01'
    if not args.yes:
        print('[闸门] 这会真的占本机 GPU 出片（不花钱，但电脑会忙）。确认后加 --yes：')
        print('       drama video run --engine local --ep %s --yes' % ep)
        cmd = [sys.executable, str(COMFY_BATCH_PY), '--ep', ep]
        if args.limit:
            cmd += ['--limit', str(args.limit)]
        if args.only:
            cmd += ['--only', args.only]
        return run_cmd(cmd, 'video_local_dry', quiet_ok=False)[0]

    rc = _model_gate('video', expected_engine='local')
    if rc:
        return rc
    cmd = [sys.executable, str(COMFY_BATCH_PY), '--ep', ep, '--submit']
    if args.limit:
        cmd += ['--limit', str(args.limit)]
    if args.only:
        cmd += ['--only', args.only]
    if getattr(args, 'force', False):
        cmd += ['--force']
    if getattr(args, 'timeout_min', None):
        cmd += ['--timeout-min', str(args.timeout_min)]
    from _lock import single_instance
    try:
        with single_instance('video_run', WS):
            rc, log, dt = run_cmd(cmd, 'video_local', quiet_ok=False)
    except SystemExit:
        print('（已由单例锁拦下，未提交任何任务）')
        raise
    print('\n本地出片退出码 %s（耗时 %.1fs）；日志：%s' % (rc, dt, log))
    if rc == 3:
        print('★ 退出码 3 = 批次有缺口（不是失败）。直接重跑同一条命令即可补缺，')
        print('  不要改提示词 —— 缺的那几镜通常只是显存不足或 ComfyUI 队列被打断。')
    return rc


def cmd_video_run(args) -> int:
    """出片。**只有本地 ComfyUI 一条通道**。

    保留 `--engine` 参数只是为了让旧命令不被 argparse 拒绝；传 `workflow` 会明确报错，
    而不是悄悄回落到本地 —— 「以为切换了通道，其实没切」比报错危险得多。
    """
    eng = getattr(args, 'engine', None) or 'local'
    if eng != 'local':
        print('[FAIL] 只剩本地通道：--engine=%s 已不可用' % eng)
        print('       直接跑：drama video run --ep ep01 --yes')
        return 2
    return cmd_video_local(args)


def cmd_video_status(args) -> int:
    batch = args.batch or _latest_batch()
    if not batch:
        print('还没有任何批次（output/<批次>/summary.json 不存在）')
        return 1
    s = read_json(OUT / batch / 'summary.json', {}) or {}
    t = s.get('totals', {}) or {}
    u = s.get('usage', {}) or {}
    fuse = s.get('fuse', {}) or {}
    print('=' * 74)
    print('批次 %s' % batch)
    print('=' * 74)
    print('战报   : 总 %s | 成功 %s | 失败 %s | 跳过 %s | 待跑 %s | 用时 %ss'
          % (t.get('total'), t.get('success'), t.get('failed'), t.get('skipped'),
             t.get('pending'), s.get('elapsed_seconds')))
    print('花费   : %s' % json.dumps(u, ensure_ascii=False))
    if fuse.get('blown'):
        print('★熔断  : %s' % fuse.get('reason'))
    shots = s.get('shots') or []
    # ★ 只把真失败列进「失败清单」：PENDING/待跑不是失败（预演批次里全是 PENDING，别吓人）
    bad = [x for x in shots
           if any(k in str(x.get('video_status') or '').upper() for k in ('FAIL', 'CANCEL', 'ERROR'))]
    if not t.get('success') and not t.get('failed'):
        print('说明   : 这是预演/空批次（没有成功也没有失败），101 段都还没真跑。')
    if bad:
        print('失败清单：')
        for x in bad[:20]:
            print('  %-16s %-9s %s' % (x.get('shot_id'), x.get('video_status'),
                                       str(x.get('error'))[:70]))
    d = OUT / batch
    finals = list(d.glob('*/final.mp4'))
    print('产物   : %s（final.mp4 %d 个）' % (d, len(finals)))
    if finals:
        print('         例：%s' % finals[0])
    return 0


def cmd_refs(args) -> int:
    # ★ 2026-11-02：`prepare_refs.py` 的默认工作区是**脚本所在目录**的 video-pipeline/，
    #   不是 cwd。不显式传 --workspace 时，它永远去 `<仓库>/stages/production/video-pipeline/`
    #   找 data/，于是「参考图瘦身」对任何项目都报「找不到工作区 data/」—— 功能等于废的。
    cmd = [sys.executable, SCRIPTS / 'prepare_refs.py', '--workspace', str(WS)]
    if args.apply:
        cmd += ['--apply']
    if args.write_config:
        cmd += ['--write-config']
    print('参考图瘦身（6000px 超 H3 上限 5760）：%s' % ('★真写盘' if args.apply else '只体检，不写盘'))
    rc, _, _ = run_cmd(cmd, 'refs', quiet_ok=False)
    if not args.apply:
        print('\n确认无误后：python scripts/drama.py refs --apply --write-config')
    return rc


GUIDE = """短剧生产线 · 速查（python stages/production/scripts/drama.py <命令>）
════════════════════════════════════════════════════════════════════════
全部在本机跑（本地 ComfyUI）：出图 ￥0、出片 ￥0、不需要任何平台 Key。
唯一的成本是**时间** —— 预估看 `time plan`，实测看 `time report`。

★主链     pack import        导入制作包 → data/ 契约（默认干跑，--apply 落盘）
         pack preset        应用预配置（出图/出片/放大通道一次性写三处）
         assets             批量出资产图（本地 ComfyUI；--submit 才真跑）
         video plan         这一集会跑多久（时间分解，不提交任何任务）
         video run --ep ep01 --yes   批量出片（本地，占 GPU）
         nodes / next       接下来跑哪个节点（12 节点状态机）
看状态   status             全盘面板：数据/参考图/资产缺口/批次（零网络，先跑这个）
时间     time plan          预估：单集 / 整季要跑多久（--episodes 30 看整季）
         time report        实测：已经跑了多久，按集 / 按阶段 / 逐镜
         time plan --calibrate   用实测反推系数，之后预估就准了
★资产     refs               参考图瘦身（出片前把原图裁到可用尺寸）
         models             通道确认单（只剩本地；首次出图/出片前需确认一次）
环境     preflight          一次过体检：依赖 / ComfyUI / 工作区 / 资产缺口
         guide              打印本页
子命令透传 bgm                配乐库与混音（library / plan / mix / credits）

常用一条线：
  1) drama pack preset --preset local-comfyui-all --apply
  2) drama pack import --pack <制作包目录> --apply
  3) drama assets --submit                  # 出资产图（￥0，占 GPU）
  4) drama pack import --apply              # 回填参考表（出完图必须重跑一次）
  5) drama video plan --ep ep01             # 先看时间，再决定要不要跑
  6) drama video run --ep ep01 --yes
  7) 之后按 drama next 走：拼接 → 放大 → 字幕 → 发布版

时间量级（RTX 4060 8G，默认系数）：
  一集 8 镜 × 6 秒 ≈ 2.5 小时，其中出片占 78%
  30 集 ≈ 76 小时（单卡并发只能是 1）
  ★ 首次真跑后执行 `drama time plan --calibrate`，这些数字会换成本机实测值。
"""


def cmd_time(args) -> int:
    """耗时台账：已经花了多久（实测），替代已删除的 cost_ledger。"""
    cmd = [sys.executable, str(SCRIPTS / 'time_report.py'), '--workspace', str(WS)]
    if getattr(args, 'ep', None):
        cmd += ['--ep', args.ep]
    if getattr(args, 'per_shot', False):
        cmd += ['--per-shot']
    if getattr(args, 'json', False):
        cmd += ['--json']
    print('【耗时台账】成本口径 = 时间（本机 GPU 时间）')
    rc, _, _ = run_cmd(cmd, 'time_report', quiet_ok=False)
    return rc


def cmd_time_plan(args) -> int:
    """耗时预估：这一集/这一季要跑多久（不跑任何任务）。"""
    cmd = [sys.executable, str(SCRIPTS / 'time_model.py'), '--workspace', str(WS)]
    for flag, key in (('--episodes', 'episodes'), ('--shots', 'shots'),
                      ('--shot-seconds', 'shot_seconds'), ('--images', 'images')):
        v = getattr(args, key, None)
        if v:
            cmd += [flag, str(v)]
    if getattr(args, 'upscale', False):
        cmd += ['--upscale']
    if getattr(args, 'calibrate', False):
        cmd += ['--calibrate']
    if getattr(args, 'json', False):
        cmd += ['--json']
    rc, _, _ = run_cmd(cmd, 'time_model', quiet_ok=False)
    return rc


def cmd_guide(args) -> int:
    print(GUIDE)
    return 0


# ---------------------------------------------------------------------------
# setup / workflow / pipeline（★ 2026-10-21：开工前置条件 · 标准流程 · 流水线模式）
#   三者都是**独立脚本**（各自是单一真源），这里只做薄转发：
#     * workflow.py      —— 11 环节标准流程（产物判据 + 顺序门禁）
#     * pipeline.py      —— 流水线模式（预算上限 + 预计完工 + 一次跑完）
#   透传用 REMAINDER：以后给这些脚本加参数，不必回来改 drama.py。
# ---------------------------------------------------------------------------
def _strip_ws(tokens) -> list:
    """去掉透传参数里混进来的 `--workspace X`（工作区由顶层统一解析）。"""
    out, skip = [], False
    for t in tokens:
        if skip:
            skip = False
            continue
        if t == '--workspace':
            skip = True
            continue
        if t.startswith('--workspace='):
            continue
        out.append(t)
    return out


def cmd_forward(args) -> int:
    script = args._forward_script
    rest = _strip_ws([str(x) for x in (getattr(args, 'rest', None) or [])])
    cmd = [sys.executable, SCRIPTS / script, '--workspace', str(WS)] + rest
    print('【%s】' % args._forward_title)
    return run_cmd(cmd, script.split('.')[0], quiet_ok=False)[0]


def _add_ws_arg(p) -> None:
    """全局 --workspace（反馈 P1-3）：放在子命令前后都接受。

    真正的生效点在文件顶部 `_preset_workspace_from_argv()`（导入 _ws 之前）；
    这里注册参数只是为了 argparse 不报 `unrecognized arguments`。
    """
    p.add_argument('--workspace', default=None, metavar='DIR',
                   help='工作区根目录（也可用环境变量 SOLODRAMA_WORKSPACE）')


def main() -> int:
    _harden_stdio()
    hydrate_env()
    ap = argparse.ArgumentParser(
        description='短剧生产线的零思考入口（默认不花钱）',
        epilog='全局参数：--workspace <DIR> 指定工作区（也可设环境变量 SOLODRAMA_WORKSPACE）')
    _add_ws_arg(ap)
    sub = ap.add_subparsers(dest='cmd')

    # ---------------- 七环节 23 节点（调度器的唯一入口） ----------------
    # ---------------- 新建项目（必须最先可用：此时项目还不存在） ----------------
    p = sub.add_parser('init', help='建七环节空项目（结构 + 模板，不写内容）',
                       epilog='可加 --title/--platform/--episodes/--track/--look 等；'
                              '重跑安全，加 --force 才覆盖已有模板。')
    p.add_argument('--title', default='未命名短剧')
    p.add_argument('--platform', default='')
    p.add_argument('--episodes', default=30, type=int)
    p.add_argument('--ep-seconds', dest='ep_seconds', default=60, type=int)
    p.add_argument('--track', default='')
    p.add_argument('--look', default='')
    p.add_argument('--narrative', default='dialogue', choices=['dialogue', 'narration'])
    p.add_argument('--aspect', default='9:16')
    p.add_argument('--world', default='')
    p.add_argument('--region', default='east_asian',
                   choices=['east_asian', 'western', 'south_asian', 'latin'])
    # ★ 2026-11-04：引擎只剩本地 ComfyUI（出图与出片同一个 ComfyUI）。
    #   本仓库已不允许任何 RH 调用，这个默认值必须跟着消失。
    p.add_argument('--image-engine', dest='image_engine', default='local_comfyui',
                   choices=['local_comfyui'])
    p.add_argument('--video-engine', dest='video_engine', default='local_comfyui',
                   choices=['local_comfyui'])
    p.add_argument('--force', action='store_true')
    p.add_argument('--dry-run', action='store_true')
    _add_ws_arg(p)
    p.set_defaults(fn=cmd_init_project)

    p = sub.add_parser('next', help='打印下一步该做什么（只读磁盘，不执行）')
    p.add_argument('--ep', default='')
    p.add_argument('--json', action='store_true')
    _add_ws_arg(p)
    p.set_defaults(fn=cmd_next_node)

    p = sub.add_parser('do', help='执行一个节点（重复执行结果相同）：drama do <node> --ep ep01')
    p.add_argument('node')
    p.add_argument('--ep', default='')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--yes', action='store_true', help='出片计费节点必须显式确认')
    _add_ws_arg(p)
    p.set_defaults(fn=cmd_do_node)

    p = sub.add_parser('nodes', help='五环节 12 节点全状态')
    p.add_argument('--ep', default='')
    p.add_argument('--json', action='store_true')
    _add_ws_arg(p)
    p.set_defaults(fn=cmd_nodes_status)

    p = sub.add_parser('graph', help='打印节点图与回流白名单')
    p.add_argument('--json', action='store_true')
    _add_ws_arg(p)
    p.set_defaults(fn=cmd_nodes_graph)

    p = sub.add_parser('skip', help='显式跳过一个节点（必须给理由）')
    p.add_argument('node')
    p.add_argument('--reason', required=True)
    _add_ws_arg(p)
    p.set_defaults(fn=cmd_skip_node)

    p = sub.add_parser('status', help='全盘状态面板')
    p.add_argument('--json', action='store_true')
    _add_ws_arg(p)
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser('preflight', help='一次过体检（免费）')
    _add_ws_arg(p)
    p.set_defaults(fn=cmd_preflight)

    # ---------------- 制作包（新分支的唯一输入入口） ----------------
    p = sub.add_parser('pack', help='制作包：导入 → data/ 契约 ｜ 预配置落地')
    _add_ws_arg(p)
    pk = p.add_subparsers(dest='pack_cmd')

    q = pk.add_parser('import', help='导入制作包（默认干跑，--apply 落盘）')
    _add_ws_arg(q)
    q.add_argument('--pack', default=None, help='制作包目录（默认 <工作区>/pack）')
    q.add_argument('--ep', default=None, help='只导这一集（ep01 / 1）')
    q.add_argument('--apply', action='store_true', help='真写（默认干跑）')
    q.add_argument('--prune', action='store_true', help='删除本集 data 里不在本次输出里的 *.json')
    q.add_argument('--json', action='store_true', help='机器可读输出')
    q.set_defaults(fn=cmd_pack)

    q = pk.add_parser('check', help='只校验制作包，不写任何文件')
    _add_ws_arg(q)
    q.add_argument('--pack', default=None, help='制作包目录（默认 <工作区>/pack）')
    q.add_argument('--ep', default=None)
    q.add_argument('--json', action='store_true')
    q.set_defaults(fn=cmd_pack)

    q = pk.add_parser('preset', help='把项目预配置（出图/出片/放大通道）落到工作区')
    _add_ws_arg(q)
    q.add_argument('--preset', default='local-comfyui-all', help='预配置卡 id（默认 local-comfyui-all：全本地 ￥0）')
    q.add_argument('--list', action='store_true', help='列出可用预配置卡')
    q.add_argument('--apply', action='store_true', help='真写（默认干跑）')
    q.add_argument('--json', action='store_true')
    q.set_defaults(fn=cmd_pack)

    p = sub.add_parser('assets', help='缺失资产出图（默认本地 ComfyUI ￥0，干跑）')
    _add_ws_arg(p)
    p.add_argument('--pack', default=None, help='制作包目录（默认 <工作区>/pack）')
    p.add_argument('--engine', choices=('local',), default='local',
                   help='出图通道：只剩 local（本机 ComfyUI，￥0）')
    p.add_argument('--submit', action='store_true',
                   help='真的出图（占 GPU，不花钱）')
    p.add_argument('--kind', choices=('all', 'char', 'scene', 'prop'), default='all',
                   help='只做某一类（prop 仅本地通道支持）')
    p.add_argument('--only', default=None, help='只做这些（名字或序号 / 资产 id，逗号分隔）')
    p.add_argument('--force', action='store_true', help='已生成的也重跑（本地不花钱，只是费时间）')
    p.add_argument('--check', action='store_true', help='仅 local：体检 ComfyUI 是否在线，不出图')
    p.set_defaults(fn=cmd_assets)

    p = sub.add_parser('refs', help='参考图瘦身')
    _add_ws_arg(p)
    p.add_argument('--apply', action='store_true', help='真的写盘')
    p.add_argument('--write-config', action='store_true', help='顺带把 characters.json 指到新目录')
    p.set_defaults(fn=cmd_refs)

    # ★ 模型选择门禁（前置条件）：首次生图 / 首次出片前必须先确认「依托哪条通道」
    p = sub.add_parser('models', help='首次生图/出片前确认通道：本地 ComfyUI')
    _add_ws_arg(p)
    ms = p.add_subparsers(dest='models_cmd')
    q = ms.add_parser('list', help='打印可选通道清单（含各自必需的执行依据）')
    _add_ws_arg(q)
    q.set_defaults(fn=cmd_models)
    q = ms.add_parser('status', help='查看当前确认状态与执行依据是否齐备（只读）')
    _add_ws_arg(q)
    q.add_argument('--json', action='store_true')
    q.set_defaults(fn=cmd_models)
    q = ms.add_parser('set', help='记录确认：set image=local_comfyui [video=local_comfyui]')
    _add_ws_arg(q)
    q.add_argument('pairs', nargs='+', metavar='kind=choice')
    q.add_argument('--detail', default=None)
    q.add_argument('--comfy-url', dest='comfy_url', default=None, help='ComfyUI 服务地址')
    q.add_argument('--comfy-workflow', dest='comfy_workflow', default=None,
                   help='ComfyUI 工作流 API 文件路径（「导出（API）」得到的 json）')
    # ★ 2026-11-04：--app-url / --app-id / --workflow-id 已删 —— 它们只对应
    q.set_defaults(fn=cmd_models)
    q = ms.add_parser('reset', help='清除某类确认（换通道前用）')
    _add_ws_arg(q)
    q.add_argument('kind', choices=('image', 'video'))
    q.set_defaults(fn=cmd_models)
    q = ms.add_parser('ask', help='交互式引导确认（需 TTY）')
    _add_ws_arg(q)
    q.add_argument('kind', nargs='?', default='image', choices=('image', 'video'))
    q.set_defaults(fn=cmd_models)
    p.set_defaults(fn=cmd_models, models_cmd=None)

    # ★ 画风库门禁（前置条件）：开工前先确认形态（3D 漫剧 / 2D 动画 / 真人）+ 视觉 look + 叙事
    pv = sub.add_parser('video', help='出片')
    _add_ws_arg(pv)
    vs = pv.add_subparsers(dest='vcmd')
    q = vs.add_parser('plan', help='出片计划与耗时预估（不提交任何任务）')
    _add_ws_arg(q)
    q.add_argument('--limit', type=int)
    q.add_argument('--only')
    q.add_argument('--ep', default=None, help='集号（ep01）')
    q.add_argument('--json', action='store_true')
    q.set_defaults(fn=cmd_video_plan)
    q = vs.add_parser('run', help='真跑出片（本地 ￥0；需 --yes）')
    _add_ws_arg(q)
    q.add_argument('--engine', choices=('local',), default='local',
                   help='出片通道：只剩 local（本机 ComfyUI，￥0）')
    q.add_argument('--ep', default=None, help='集号（local 通道必填；ep01 / 1）')
    q.add_argument('--force', action='store_true', help='local：已有产物也重跑')
    q.add_argument('--timeout-min', dest='timeout_min', type=float, default=None,
                   help='local：单镜轮询超时（分钟，默认 20）')
    q.add_argument('--yes', action='store_true', help='确认执行闸门（计费通道同时是计费闸门）')
    q.add_argument('--limit', type=int)
    q.add_argument('--only')
    q.add_argument('--resume', metavar='BATCH_ID')
    q.set_defaults(fn=cmd_video_run)
    q = vs.add_parser('status', help='批次进度')
    _add_ws_arg(q)
    q.add_argument('batch', nargs='?', default=None)
    q.set_defaults(fn=cmd_video_status)

    # ★ 2026-11-04：成本口径改为**时间**。`report` / `balance` / `cost` 三个命令删掉：
    p = sub.add_parser('time', help='耗时：预计跑多久（plan）/ 已经跑了多久（report）')
    _add_ws_arg(p)
    ts = p.add_subparsers(dest='tcmd')

    q = ts.add_parser('plan', help='预计耗时：单集/整季（不跑任何任务）')
    _add_ws_arg(q)
    q.add_argument('--episodes', type=int, default=1, help='算几集（默认 1）')
    q.add_argument('--shots', type=int, default=8, help='每集镜头数（默认 8）')
    q.add_argument('--shot-seconds', dest='shot_seconds', type=float, default=6.0)
    q.add_argument('--images', type=int, default=12, help='每集资产图张数')
    q.add_argument('--upscale', action='store_true', help='计入本地超分耗时')
    q.add_argument('--calibrate', action='store_true',
                   help='用台账实测反推系数并写进 <工作区>/time-model.json')
    q.add_argument('--json', action='store_true')
    q.set_defaults(fn=cmd_time_plan)

    q = ts.add_parser('report', help='耗时台账：按集 / 按阶段 / 逐镜')
    _add_ws_arg(q)
    q.add_argument('--ep', default=None, help='只看这一集（ep01）')
    q.add_argument('--per-shot', dest='per_shot', action='store_true', help='逐镜明细')
    q.add_argument('--json', action='store_true')
    q.set_defaults(fn=cmd_time)

    p.set_defaults(fn=cmd_time)

    p = sub.add_parser('guide', help='打印速查')
    _add_ws_arg(p)
    p.set_defaults(fn=cmd_guide)

    # ★ 2026-10-21：开工前置条件 · 标准流程 · 流水线模式（薄转发，参数全透传）
    # ★ 2026-11-01：setup / workflow / pipeline 三条转发已删（能力清单 S2 / S6）。
    #   它们对应的是「11 环节 + 九项确认」的旧编排；现行编排是 nodes.py 的 23 节点。
    for name, script, title, brief in (
        ('bgm', 'bgm.py', 'BGM 库与混音（配乐）',
         'library / plan --ep epNN --apply / check / mix / credits'),
    ):
        p = sub.add_parser(name, help='%s —— %s' % (title, brief))
        _add_ws_arg(p)
        p.add_argument('rest', nargs=argparse.REMAINDER,
                       help='透传给 %s（例：%s）' % (script, brief))
        p.set_defaults(fn=cmd_forward, _forward_script=script, _forward_title=title)

    args = ap.parse_args()
    if not getattr(args, 'fn', None):
        print(GUIDE)
        return 0
    return args.fn(args)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('\n已中断。出片用 --resume 续跑；资产脚本已完成的不会重跑。')
        sys.exit(130)
