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
                                          （本地 ComfyUI / RunningHub / 闭源模型 三选一，写 model-plan.json）
    preflight                            一次性体检：生成通道 + Key 分级 + 引擎 doctor + check + 预演（全免费）
    assets     [--engine local|rh] [...] 缺失资产出图（默认本地 ComfyUI ￥0 且干跑）
                                          local=本机出图（不花钱，占 GPU）；rh=RunningHub 云端（★计费）
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
  RunningHub / 闭源模型）；确认单落 `<工作区>/model-plan.json`，未确认即停（退出码 4）。
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
# ★ 网络出口守卫：默认只许打本机。
#   这里不是「删掉调用点」，而是把出站通道收窄 —— 任何试图连 runninghub.* 的
#   代码都会在 DNS 解析那一步抛 RemoteForbidden，包括未来某次合并里被悄悄
#   加回来的 httpx 调用。平台通道要显式开闸（见 _GUARD.allow_platform()）。
#   细则见 stages/_netguard.py。
# ---------------------------------------------------------------------------
def _boot_netguard():
    import pathlib as _pl
    import sys as _sys
    for _p in _pl.Path(__file__).resolve().parents[:5]:
        for _cand in ((_p / "_netguard.py"), (_p / "stages" / "_netguard.py")):
            if _cand.is_file():
                if str(_cand.parent) not in _sys.path:
                    _sys.path.insert(0, str(_cand.parent))
                try:
                    import importlib as _il
                    _mod = _il.import_module("_netguard")
                    _mod.install()
                    return _mod
                except Exception:        # noqa: BLE001 —— 守卫自身异常不能拖垮主流程
                    return None
    return None


_GUARD = _boot_netguard()


def _allow_platform_egress() -> None:
    """显式开闸：只在确实要走平台通道的代码路径里调用。

    ★ 开闸位置就是「意图声明」。本地通道不调它 —— 于是「默认不出网」
      不靠配置约定，而靠这条代码路径根本不经过这里。
    """
    if _GUARD is not None:
        try:
            _GUARD.allow_platform()
            return
        except Exception:            # noqa: BLE001
            pass
    import os as _os
    _os.environ["SOLODRAMA_ALLOW_RH"] = "1"



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
        print('      status / preflight / assets [--engine local|wf] / refs /')
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
#   会让 rh_doctor / cost_ledger / gen_char_assets / gen_scene_assets / gen_assets_local 全部找不到。
#   如需复刻旧布局，用环境变量 SOLODRAMA_SCRIPTS_DIR（旧名 DRAMA_SCRIPTS_DIR 仍兼容）覆盖。
SCRIPTS = pathlib.Path(os.environ.get('SOLODRAMA_SCRIPTS_DIR')
                       or os.environ.get('DRAMA_SCRIPTS_DIR')
                       or pathlib.Path(__file__).resolve().parent)
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[3]   # .../SoloDrama
SKILL = pathlib.Path(os.environ.get('AI_VIDEO_PIPELINE_SKILL')
                     or _PROJECT_ROOT / 'stages' / 'video' / 'workflow')
RUN_PY = SKILL / 'scripts' / 'run.py'                    # RH 通道入口（显式 --engine workflow）
CHECK_BILLING = SKILL / 'scripts' / 'check_billing.py'
# 本地通道入口。★ 这两个常量曾经在删 RH 时被一并删掉，`video run` 一调就 NameError ——
#   结果是「本地出片」这条默认路径其实从未被真正执行过。两条通道各自有入口，别混。
COMFY_VIDEO_PY = _PROJECT_ROOT / 'stages' / 'video' / 'comfyui' / 'comfy_local_video.py'
COMFY_BATCH_PY = _PROJECT_ROOT / 'stages' / 'video' / 'comfyui' / 'comfy_batch_video.py'
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
    # ★ 进程环境里缺的，从「用户级环境变量」补（agent 的 shell 常拿不到）：
    #   前三个是云端通道用的 Key；SOLODRAMA_ASSET_MD 是「资产提示词 md」真源，**本地通道也要用**。
    #   ★ 2026-10-13 改名过渡：新旧两个名字都参与补全，子脚本按「新名优先、旧名回退」读取。
    # ★ 2026-11-01：`RUNNINGHUB_BASE_URL` 已从这张表移除 —— 站点真源是
    #   `configs/channels.json`，再把死变量补进子进程环境只会让「哪来的 .ai」重新出现。
    want = ('RUNNINGHUB_API_KEY', 'RUNNINGHUB_ENT_API_KEY',
            'SOLODRAMA_ASSET_MD', 'DRAMA_ASSET_MD')
    os.environ.setdefault('PYTHONUTF8', '1')
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    os.environ['VIDEO_PIPELINE_WORKSPACE'] = str(VP)
    # ★ 2026-10-10：把已解析出的工作区**下传给子进程**。子脚本（gen_*_assets / cost_ledger /
    #   rh_doctor / gen_assets_local …）都靠 `_ws.resolve()` 定位工作区，而它们自己无法从
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

    # ★ 资产是资产，不分通道：本地 ComfyUI 出图（￥0）与云端计费出图**一并**计入「已生成」，
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

    # 台账聚合
    led = {'files': 0, 'success': 0, 'failed': 0, 'rh_coins': 0.0, 'wallet_usd': 0.0}
    lr = VP / 'ledger' / 'runs'
    if lr.is_dir():
        for f in lr.glob('*.json'):
            d = read_json(f, {}) or {}
            for a in d.get('attempts', []):
                led['files'] += 0
                if a.get('status') == 'SUCCESS':
                    led['success'] += 1
                elif a.get('status') == 'FAILED':
                    led['failed'] += 1
                u = a.get('usage') or {}
                try:
                    led['rh_coins'] += float(u.get('consumeCoins') or 0)
                except (TypeError, ValueError):
                    pass
                try:
                    led['wallet_usd'] += float(u.get('thirdPartyConsumeMoney') or 0)
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
        'keys': {'consumer': has('RUNNINGHUB_API_KEY'), 'enterprise': has('RUNNINGHUB_ENT_API_KEY')},
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


def estimate_video(limit=None, only=None, tier='consumer', calibrate=False) -> dict:
    """成本预估（反馈 P2-1 / P2-6 / P2-7）。

    口径真源：`cost_model.py`。给出**两套**可比的预估，不再用按帧的构造性拟合：
      * 两段式（固定 + 每秒）—— 与平台实际计费结构一致；
      * GPU 运行秒式 —— 解释「5 秒与 8 秒差价很小」（冷启动占大头）。
    真实消耗始终只认平台 `usage`；本函数只用于闸门判断。
    """
    import cost_model as CM

    shots = _selected_shots(limit, only)
    params = CM.load_params(WS)
    calib = None
    if calibrate:
        calib = CM.calibrate(CM.iter_ledger_records(WS), params)
        params = calib['params']
    # ★ 2026-10-21（反馈 11.1）：把开工确认单里的「步数 / 像素」喂进成本模型 ——
    #   段价不再写死一个数，才能回答「提分辨率还是提步数更贵」。
    steps = mp = None
    # ★ 2026-11-01：不再 import project_setup（已删）。直接读它留在项目里的确认单文件 ——
    #   老项目仍有 `project-setup.json`，新项目没有就走默认值，不影响估算。
    try:
        _ps = json.loads((WS / "project-setup.json").read_text(encoding="utf-8-sig"))
        _vo = (_ps.get("video_options") or {})
        steps, mp = _vo.get("steps"), _vo.get("megapixels")
    except Exception:                                          # noqa: BLE001
        pass
    est = CM.estimate(_durations(shots), tier=tier, params=params, steps=steps, megapixels=mp)
    est['_calibrate'] = calib
    est['_params_source'] = ('%s' % (WS / 'cost-model.json')
                             if (WS / 'cost-model.json').is_file() else '内置实测默认值')
    est['_caveat'] = ('预估仅作闸门参考；真实消耗以平台 usage 为准'
                      '（不用余额差值倒推）。`--calibrate` 可用历史台账自校准。')
    return est


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
    print('Key         : 消费级-%s 企业级-%s' % (st['keys']['consumer'], st['keys']['enterprise']))
    print('台账        : %d 个任务文件 | 成功 %d / 失败 %d | 累计 %d RH币 + $%.2f 钱包'
          % (led['files'], led['success'], led['failed'], round(led['rh_coins']), led['wallet_usd']))
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
    ('httpx', '云端提交/轮询（引擎 runninghub_client）'),
    ('PIL', '九宫格裁剪与图片尺寸（引擎 pipeline）'),
)


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
    """一次过体检：依赖 → **生成通道** → RH → 引擎 → 配置 → 预演（全免费）。

    ★ 2026-11-05：加了【生成通道】这一段。此前 preflight 只看 RunningHub，
      于是「本地 ComfyUI 缺一个 LoRA」「云端少两个插件」这类最可能发生的问题
      在体检里全绿 —— 人以为能跑，批量开跑后每镜各失败一次。
      判据不在这里重写：调用 `gen_preflight`（它再调 `cloud/health`），只有一份标准。

    `--only` 可选段：deps / gen / rh / engine / config / dryrun（逗号分隔，默认 all）。
    """
    only = (getattr(args, 'only', None) or 'all').strip()
    want = (lambda k: only == 'all' or k in [x.strip() for x in only.split(',')])
    verdict = []

    if want('deps'):
        print('【0/6】运行依赖自检（不联网）')
        if not _print_dep_report(check_dependencies()):
            verdict.append(('运行依赖', False, '装完依赖再体检'))
            print('\n' + '=' * 74)
            print('体检结论')
            print('=' * 74)
            for name, ok, extra in verdict:
                print('  %-12s %s %s' % (name, '[OK] 通过' if ok else '[NG] 需处理', extra))
            return 1
        verdict.append(('运行依赖', True, ''))

    if want('gen'):
        print('\n【1/6】生成通道（图像 / 视频 × 本地 / 云端 ComfyUI；只读，不计费）')
        # 依赖没过就别继续：缺 httpx/Pillow 时预检自己也会误报
        try:
            import gen_preflight as GP
            for kind in ('image', 'video'):
                res = GP.check(kind, None, WS, timeout=30)
                print(GP.render(res, indent='  '))
                if res['status'] == 'unsupported':
                    # 闭源模型：人工产出后落盘，引擎不提交 —— 不算「不可用」，但要说清
                    print('    （闭源模型通道：引擎不提交，人工产出后落盘）')
                    continue
                verdict.append(('生成·%s' % ('图像' if kind == 'image' else '视频'),
                                res['ok'], GP.STATUS_CN.get(res['status'], res['status'])))
        except Exception as exc:                       # noqa: BLE001
            print('  [FAIL] 预检自身没跑起来：%s: %s' % (type(exc).__name__, exc))
            verdict.append(('生成通道', False, '预检异常'))

    if want('rh'):
        print('\n【2/6】RunningHub Key 分级（只读，不计费）')
        rc1, _, _ = run_cmd([sys.executable, SCRIPTS / 'rh_doctor.py', '--check', 'model'],
                            'preflight_rhdoctor', quiet_ok=False)
        verdict.append(('Key 分级路由', rc1 == 0, ''))

    if want('engine'):
        print('\n【3/6】引擎环境体检（不联网）')
        rc2, log2, _ = run_cmd([sys.executable, RUN_PY, 'doctor', '--json'], 'preflight_doctor')
        real_fail, noise = [], 0
        try:
            doc = json.loads(pathlib.Path(log2).read_text(encoding='utf-8', errors='replace'))
            for c in doc.get('checks', []):
                if c.get('level') in ('FAIL', 'WARN'):
                    if _is_noise(c.get('detail')):
                        noise += 1
                    else:
                        real_fail.append(c)
        except (OSError, json.JSONDecodeError):
            real_fail = [{'id': 'doctor', 'detail': '无法解析 doctor --json（请看日志）'}]
        if noise:
            print('  （%d 项属 image_providers 未配置 —— 本线只用 --video-only，已知噪音，忽略）' % noise)
        if real_fail:
            print('  ★真正需要处理的 %d 项：' % len(real_fail))
            for c in real_fail:
                print('    - %s: %s' % (c.get('id'), str(c.get('detail'))[:110]))
        verdict.append(('引擎体检', not real_fail, '%d 项真问题' % len(real_fail) if real_fail else ''))

    if want('config'):
        print('\n【4/6】必填配置检查')
        # ★ 必须带 --video-only：本线只跑 --video-only，图片工作流(banana)确实不需要。
        #   不带的话引擎会拿「图片工作流未配置」判失败，而这里以前**只取 rc 不进 verdict**，
        #   于是体检永远显示全绿、真实出片却被配置闸门挡下（2026-09-19 实测踩到）。
        rc3, _, _ = run_cmd([sys.executable, RUN_PY, 'check', '--video-only'], 'preflight_check')
        verdict.append(('必填配置', rc3 == 0, '图片工作流不参与 --video-only 校验'))

    if want('dryrun'):
        print('\n【5/6】预演（零网络请求，不提交任何任务）')
        rc4, _, _ = run_cmd([sys.executable, RUN_PY, '--video-only', '--dry-run', '--strict'],
                            'preflight_dryrun')
        verdict.append(('引擎预演', rc4 == 0, ''))

    print('\n' + '=' * 74)
    print('体检结论')
    print('=' * 74)
    for name, ok, extra in verdict:
        print('  %-12s %s %s' % (name, '[OK] 通过' if ok else '[NG] 需处理', extra))
    print('  日志目录：%s' % LOG_DIR)
    return 0 if all(v[1] for v in verdict) else 1


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
        # ★ 执行依据（ComfyUI 工作流 API 文件 / 云端地址 / RH 应用地址）透传
        for flag in ('comfy_url', 'comfy_workflow', 'app_url', 'app_id', 'workflow_id'):
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


def cmd_style(args) -> int:
    """转发给 style_gate.py（画风库门禁：形态 track / 视觉 look / 叙事 narrative）。"""
    STYLE_GATE_PY = SCRIPTS / 'style_gate.py'
    cmd = [sys.executable, STYLE_GATE_PY, '--workspace', str(WS)]
    c = getattr(args, 'style_cmd', None)
    if c == 'list':
        cmd.append('list')
    elif c == 'set':
        cmd += ['set', args.choice]
        if getattr(args, 'sub_mode', None):
            cmd += ['--sub-mode', args.sub_mode]
    elif c == 'reset':
        cmd.append('reset')
    elif c == 'ask':
        cmd.append('ask')
    elif c == 'require':
        cmd.append('require')
    else:                                    # 默认 status
        cmd.append('status')
        if getattr(args, 'json', False):
            cmd.append('--json')
    return run_cmd(cmd, 'style', quiet_ok=False)[0]


# ---------------------------------------------------------------------------
# assets：缺失资产出图（默认本地 ComfyUI ￥0；可选 RunningHub 云端计费）
# ---------------------------------------------------------------------------
LOCAL_ASSETS_PY = SCRIPTS / 'gen_assets_local.py'
IMPORT_PY = _PROJECT_ROOT / 'stages' / 'import'    # ★ 制作包导入层（pack_import / preset_apply）
COMFY_BATCH_PY = _PROJECT_ROOT / 'stages' / 'video' / 'comfyui' / 'comfy_batch_video.py'


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
    """ComfyUI 出图（本机 ￥0 / 云端镜像 ★计费）。默认干跑；--submit 才真的出图。

    ★ 2026-11-05：补上云端路由。此前 `model_gate` 里 `image=cloud_comfyui` 是**能确认、
      不能执行**的状态 —— 没有 `--engine cloud`，`--engine local` 又会被门禁以
      「确认云端却用 local」拦下，等于这条通道是死的。视频侧 11-04 就补了 cloud 分支，
      图像侧一直没补，是不对称。
    """
    engine = (getattr(args, 'engine', 'local') or 'local')
    cloud = (engine == 'cloud')
    label = '云端 ComfyUI 镜像' if cloud else '本地 ComfyUI'

    if getattr(args, 'check', False):
        if cloud:
            import gen_preflight as GP
            res = GP.check('image', 'cloud', WS, timeout=30)
            print(GP.render(res, indent=''))
            return 0 if res['ok'] else 1
        print('【本地 ComfyUI 体检】（只读 /system_stats，不出图）')
        rc, _, _ = run_cmd([sys.executable, LOCAL_ASSETS_PY, '--check'], 'assets_local_check',
                           quiet_ok=False)
        return rc
    if args.submit:                       # ★ 首次生图前：模型选择门禁（按确认的通道比对）
        rc = _model_gate('image', expected_engine=engine)
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
    if cloud:
        import gen_preflight as GP
        target = GP.resolve('image', WS)
        url = str(target['url'] or '').rstrip('/')
        if _is_loopback_url(url):
            print('[FAIL] 选了 --engine cloud，但图像确认单里的地址是本机：%s' % url)
            print('       先确认云端地址：drama models set image=cloud_comfyui --comfy-url <地址>')
            return 2
        print('  通道    ：%s · %s（依据：%s）' % (label, url, target.get('url_via', '')))
        if not _cloud_url_ready(url):
            return 2
        cmd += ['--comfy-url', url]
    print('【资产出图 · %s】%s（%s；先出一张确认风格再批量）'
          % (label, '★真实出图' if args.submit else '干跑，不占 GPU',
             '★计费' if cloud else '￥0 成本'))
    rc, _, _ = run_cmd(cmd, 'assets_local', quiet_ok=False)
    return rc


def cmd_assets(args) -> int:
    """资产出图 —— **只留本地 ComfyUI 一条通道**。

    ★ 2026-11-01：删掉旧的 `--engine rh`（走 `gen_char_assets.py` / `gen_scene_assets.py` 两个
      RunningHub **AI 应用**脚本）。理由：引擎配置里已没有 AI 应用通道（`IMAGE_PROVIDERS`
      只有 `rh_t2i` 工作流），那两个脚本只是同一件事的两个人肉特例，且各自复制了一套
      manifest/清洗/站点逻辑。现在只剩两条**真通道**：
        · local —— 本地 ComfyUI（￥0）
        · wf    —— RunningHub 工作流（★计费；旧的 `rh` 仍作为别名可用）
    """
    if getattr(args, 'engine', 'local') in ('wf', 'rh'):
        return cmd_assets_wf(args)
    return cmd_assets_local(args)


def cmd_assets_wf(args) -> int:
    """云端「工作流」出图（★计费）：转发 gen_assets_rh_workflow.py。"""
    if args.submit:                       # ★ 首次生图前：模型选择门禁（云端通道）
        rc = _model_gate('image', expected_engine='rh')
        if rc:
            return rc
    cmd = [sys.executable, SCRIPTS / 'gen_assets_rh_workflow.py']
    if args.kind and args.kind != 'all':
        cmd += ['--kind', args.kind]
    if args.only:
        cmd += ['--only', args.only]
    if getattr(args, 'ratio', None):
        cmd += ['--ratio', args.ratio]
    if getattr(args, 'mode', None):
        cmd += ['--mode', args.mode]
    for r in (getattr(args, 'ref', None) or []):
        cmd += ['--ref', r]
    if args.force:
        cmd += ['--force']
    if args.submit:
        cmd += ['--submit']
    print('【资产出图 · RunningHub 工作流】%s（按张计费）'
          % ('★真实提交' if args.submit else '干跑，不花钱'))
    rc, _, _ = run_cmd(cmd, 'assets_rh_wf', quiet_ok=False)
    return rc


# ---------------------------------------------------------------------------
# video：计划 / 出片 / 批次进度
# ---------------------------------------------------------------------------
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


def _cost_lines(segments: int, ws=None) -> list:
    """按**真实跑出来的数据**给费用参考。

    为什么不再给预估
    ----------------
    `cost_model` 的内置参数（27 币/任务 + 1 币/秒）是 2026-10-19 在一个特定 Key 档位上
    拟合的；真实项目 307 条台账的中位数是 **45 币/段、6.07 币/秒**（7s 段 138–146 币），
    比内置参数高约 4 倍。继续展示那个预估值，等于给一个已知会错的数字配上小数位。
    所以这里只报台账里的事实；没有事实就说没有。

    预估本身没有删除：它仍在 `estimate_video()` 里供**预算闸门**使用（拦超支），
    只是不再出现在「我要花多少钱」这个位置。
    """
    import cost_model as CM
    o = CM.observed(ws or WS, last=40)
    if not o["samples"]:
        return ['  费用参考    : 本机台账暂无计费记录 —— 跑完第一段后，这里显示真实消耗',
                '  结算方式    : 以平台 usage 为准，跑完自动写台账（不做预估）']
    lo, hi = o["coin_range"]
    per = o["coins_per_shot"]
    lines = ['  实测参考    : 最近 %d 段真实消耗，中位 %.0f 币/段（区间 %.0f–%.0f）'
             % (o["samples"], per, lo, hi),
             '  本批约      : %d 段 × %.0f 币 ≈ %.0f RH币（按实测推算，不是拟合预估）'
             % (segments, per, per * segments),
             '  数据来源    : %s' % o["basis"]]
    if o.get("coins_per_second"):
        lines.append('  单位成本    : %.2f 币/秒 ｜ 中位时长 %.0fs/段'
                     % (o["coins_per_second"], o.get("shot_seconds_median") or 0))
    return lines


def cmd_video_plan(args) -> int:
    est = estimate_video(args.limit, args.only.split(',') if args.only else None,
                         tier=getattr(args, 'tier', 'consumer'),
                         calibrate=getattr(args, 'calibrate', False))
    print('出片计划（免费，不提交任何任务）')
    print('-' * 74)
    print('  将提交      : %d 段' % est['segments'])
    print('  Key tier    : %s' % est['tier_label'])
    for line in _cost_lines(est['segments']):
        print(line)
    only = ['--only', args.only] if args.only else []
    lim = ['--limit', str(args.limit)] if args.limit else []
    print('\n  真实跑（★计费）：')
    print('    python scripts/drama.py video run --yes %s %s'
          % (' '.join(lim), ' '.join(only)))
    print('\n  先小样更稳（1 段）：')
    print('    python scripts/drama.py video run --yes --limit 1')
    print('\n  更精确的「将提交 N / 跳过 M」口径（引擎自带；本线走 --video-only，'
          '所以「图片」那部分不会真的发生）：')
    run_cmd([sys.executable, CHECK_BILLING, '--workspace', VP] + lim + only,
            'video_check_billing', quiet_ok=False)
    # ★ 2026-11-06（复盘 B3）：这句原来不分通道地教用户 `--resume <批次>`，
    #   而批次号只对 RunningHub 有意义 —— 本机/云端的续跑就是重跑同一条命令。
    print('  中断后继续：重跑同一条命令即可（已有产物会跳过，不重复扣费）')
    print('  平台通道（RunningHub）另可用：video run --engine workflow --yes --resume <批次>')
    print('  用历史台账校准单价：python scripts/drama.py video plan --calibrate --save-calibration')
    if getattr(args, 'save_calibration', False):
        # ★ 2026-11-06 修：这里原来读一个从未赋值的局部变量 `cal`，
        #   于是 `video plan --calibrate --save-calibration`（它自己的 help 和 VERSIONS 都写着
        #   这条命令）一走就 NameError。校准结果其实挂在 `est['_calibrate']` 上。
        cal = est.get('_calibrate')
        if not getattr(args, 'calibrate', False):
            print('  [WARN] 没有实际校准：--save-calibration 只是「把算好的参数写盘」，'
                  '要和 --calibrate 一起用。')
        elif cal and cal.get('fitted'):
            import cost_model as CM
            p = CM.write_params(WS, cal['params'])
            print('  [OK] 已把校准结果写入 %s（下次预估自动使用）' % p)
        else:
            print('  [WARN] 样本不足，未写 cost-model.json（不臆造单价）')
    return 0


def _video_wf_default(cloud: bool = False) -> str:
    """视频默认工作流的绝对路径（真源 `stages/video/comfyui/workflow_defaults.py`）。

    本机 = `workflow_h3_minimax_canvas.json`（6 参考槽 + fl2v turbo 8step）；
    云端 = `workflow_h3_pika_8g.json`（pika 极速版：2 参考槽 + lcm + SigmaShift）。

    为什么绕一句 `gen_preflight.default_workflow()` 而不是在这里拼路径：
    预检、界面通道页、执行器必须认**同一份**文件，否则就是「核 A 跑 B」。
    """
    import gen_preflight as _GP
    return str(_GP.default_workflow('video', cloud=cloud))


def cmd_video_local(args) -> int:
    """ComfyUI 批量出片（本机 ￥0 / 云端镜像 ★计费）。

    与 RH 通道的区别只有四处：不传 --concurrency（单实例并发只能是 1）、
    不需要 RunningHub Key、产物落同一个 `07-成片/<ep>/<shot>/final.mp4`、
    **云端还要认受信域名**（见下）。
    后续 video.audit / 剪辑读的是同一个落点，所以三条通道可以混用：
    哪一镜本地跑糊了，可以单独用云端重跑那一镜。

    ★ 2026-11-05 云端接入：local 与 cloud 走**同一个执行器**
      （`comfy_local_video.py`），差别只在 `COMFYUI_URL` 与实际耗时结构。
      所以这里不是复制一条命令，而是把「确认单里的地址」注入环境变量后交给同一段代码。

    ★ 2026-11-05 任务级启停：`--engine cloud` 默认 `--cloud-lifecycle auto` ——
      要跑才开（复用/开机/新建/借），跑完就关（只关自己开的）。见 `cloud/session.py`。
    """
    ep = getattr(args, 'ep', None) or 'ep01'
    engine = (getattr(args, 'engine', None) or 'local')
    cloud = (engine == 'cloud')
    label = '云端 ComfyUI 镜像' if cloud else '本机 ComfyUI'
    lifecycle = ((getattr(args, 'cloud_lifecycle', None) or 'auto') if cloud else 'off')

    # ★ 2026-11-06（复盘 B3）：这两个参数原本被**静默吞掉** —— 它们只有 RunningHub 那条链在
    #   用（批次号 / 并发数是 RH 引擎的概念），而 `video plan` 的结尾文案还在教用户
    #   `video run --yes --resume <批次>`，在默认（local）通道上那句话是假的。
    #   现在按「能不能兑现」分开处理，不再假装接受：
    #     · --resume   → 语义等价（本机/云端的续跑就是重跑，已有产物会跳过），接受并说清
    #     · --concurrency > 1 → ComfyUI 单实例只能串行，兑现不了 → 直接拒绝
    conc = getattr(args, 'concurrency', None)
    if conc not in (None, 1):
        print('[FAIL] --concurrency %s 在本机/云端 ComfyUI 上兑现不了：单实例只能串行出片。' % conc)
        print('       要并发请走 RunningHub 通道（--engine workflow），它按 lane 提交。')
        print('       本机/云端想去掉这个参数即可 —— 默认就是逐镜串行。')
        return 2
    if getattr(args, 'resume', None):
        print('  [提示] --resume %s 已忽略：本机/云端的续跑 = 重跑同一条命令。' % args.resume)
        print('         不加 --force 时已有产物会跳过，不会重复提交、也不会重复计费。')

    url = ''
    if cloud:
        url = _resolve_cloud_url(args)
        if getattr(args, 'comfy_url', None) and _is_loopback_url(str(args.comfy_url)):
            print('[FAIL] --comfy-url 给的是本机地址：%s' % args.comfy_url)
            print('       选了 --engine cloud 就要给云端地址（否则是账实不符：以为在云端、实际吃本机）')
            return 2
        print('  通道    ：%s · %s' % (label, url or '（由 cloud.endpoints 自动创建）'))
        print('  生命周期：%s' % _lifecycle_label(lifecycle))

    if not args.yes:
        # 干跑**不建实例、不开机** —— 那会白烧几分钟 GPU 才让你看一份计划。
        print('[闸门] 这会真的%s出片（%s）。确认后加 --yes：'
              % ('占用云端 GPU、按主机时长计费' if cloud else '占本机 GPU（不花钱，但电脑会忙）',
                 label))
        print('       drama video run --engine %s --ep %s --yes' % (engine, ep))
        cmd = [sys.executable, str(COMFY_BATCH_PY), '--ep', ep]
        if cloud and url:
            cmd += ['--comfy-url', url]    # 干跑也要显示真实目标，否则头部打印的是本机
        # ★ 干跑必须展示**将要提交的那一份**：漏传 --workflow 时，计划里打印的是默认 canvas，
        #   而真跑会提交你指定的替代工作流 —— 这正是「核 A 跑 B」，只是方向反过来
        #   （2026-11-05 WebUI 实测抓到：干跑显示 canvas，预检也按 canvas 判缺件）。
        if getattr(args, 'workflow', ''):
            cmd += ['--workflow', str(args.workflow)]
        if getattr(args, 'map', ''):
            cmd += ['--map', str(args.map)]
        if args.limit:
            cmd += ['--limit', str(args.limit)]
        if args.only:
            cmd += ['--only', args.only]
        return run_cmd(cmd, 'video_local_dry', quiet_ok=False)[0]

    rc = _model_gate('video', expected_engine='cloud' if cloud else 'local')
    if rc:
        return rc

    # ★ 工作流也要按确认单解析：视频确认单里记的 `comfy_workflow` 此前**不生效**
    #   （只有预检和界面看得到），于是「确认了 A 工作流、实际跑 B」。
    #   放在分派之前算，cloud / local / lifecycle off 三条路都用同一份依据。
    import gen_preflight as GP
    target = GP.resolve('video', WS)
    wf_from_plan = target['workflow'] if target.get('workflow_via') == '模型确认单' else ''
    if wf_from_plan:
        print('  工作流  ：%s（依据：模型确认单）' % wf_from_plan)

    if cloud and lifecycle != 'off':
        # ★ 2026-11-06：确认单没指定工作流时，云端用**云端默认**（pika 极速版）。
        #   不能让它落回执行器的 DEFAULT_WORKFLOW —— 那是本机那份 canvas。
        return _run_cloud_task(args, ep, url, lifecycle, label,
                               wf_from_plan or _video_wf_default(cloud=True))

    if cloud:
        # lifecycle=off：只用给定地址，不管启停（调试/临时验证用）
        if not url:
            print('[FAIL] --cloud-lifecycle off 必须显式给 --comfy-url（不做任何启停就不该替你猜地址）')
            return 2
        if not _cloud_url_ready(url):
            return 2
    if not cloud:
        # 本机也要显式解析一次：`COMFYUI_URL` 是 image/video 共用的全局变量，
        # 长驻进程里可能残留上一次云端任务的地址。确认单（按类）优先，其次环境变量。
        url = str(target['url'] or '').rstrip('/')
        print('  通道    ：%s · %s（依据：%s）' % (label, url, target.get('url_via', '')))
    rc, log, dt = _run_batch(args, ep, url,
                             wf_from_plan or (_video_wf_default(cloud=True) if cloud else ''))
    print('\n%s出片退出码 %s（耗时 %.1fs）；日志：%s' % (label, rc, dt, log))
    if rc == 3:
        print('★ 退出码 3 = 批次有缺口（不是失败）。直接重跑同一条命令即可补缺，')
        print('  不要改提示词 —— 缺的那几镜通常只是显存不足或 ComfyUI 队列被打断。')
    return rc


def _lifecycle_label(lifecycle: str) -> str:
    return {'auto': 'auto（要跑才开，跑完就关；只关自己开的）',
            'keep': 'keep（跑完保留实例，★ 继续计费）',
            'off': 'off（不启停，只用给定地址）'}.get(lifecycle, lifecycle)


def _resolve_cloud_url(args) -> str:
    """云端地址：命令行 > 确认单 > 环境变量。返回 '' = 没有可用地址（交给 lifecycle 去建）。

    ★ local 分支不走这里：避免「确认了云端、detail 里留着旧地址，本地出片被悄悄改成打远端」。
    """
    import model_gate as MG
    applied = MG.apply_env(WS, 'video')
    if applied:
        print('  [依据] 已从确认单注入：%s' % '、'.join('%s=%s' % kv for kv in applied.items()))
    if getattr(args, 'comfy_url', None):
        os.environ['COMFYUI_URL'] = str(args.comfy_url)      # 显式参数优先于确认单
    u = (os.environ.get('COMFYUI_URL') or '').rstrip('/')
    return '' if _is_loopback_url(u) else u


def _run_batch(args, ep, comfy_url: str, workflow: str = ''):
    """把批次交给 `comfy_batch_video.py`（含单例锁）。返回 (rc, log, 耗时)。

    `workflow` 为空的含义是「让批次用默认/环境变量」，不是「用仓库默认」——
    两种情况必须分开：前者的依据可能来自 `COMFYUI_VIDEO_WORKFLOW`。
    """
    cmd = [sys.executable, str(COMFY_BATCH_PY), '--ep', ep, '--submit']
    if comfy_url:
        cmd += ['--comfy-url', comfy_url]   # 双保险：子进程不依赖父进程环境残留
    wf = workflow or str(getattr(args, 'workflow', '') or '')
    if wf:
        cmd += ['--workflow', wf]
    if getattr(args, 'map', ''):
        cmd += ['--map', str(args.map)]
    if args.limit:
        cmd += ['--limit', str(args.limit)]
    if args.only:
        cmd += ['--only', args.only]
    if getattr(args, 'force', False):
        cmd += ['--force']
    if getattr(args, 'timeout_min', None):
        cmd += ['--timeout-min', str(args.timeout_min)]
    if getattr(args, 'mp', None):
        cmd += ['--mp', str(args.mp)]
    if getattr(args, 'aspect', None):
        cmd += ['--aspect', str(args.aspect)]
    from _lock import single_instance
    try:
        with single_instance('video_run', WS):
            return run_cmd(cmd, 'video_local', quiet_ok=False)
    except SystemExit:
        print('（已由单例锁拦下，未提交任何任务）')
        raise


def _pull_back(url: str, ep: str, history: int = 60) -> dict:
    """停机前的最后一次回传（只补缺口，不重下已有）。

    ★ 为什么必须在 `with lease:` **之内**调用：产物在实例的 `ComfyUI/output/`，
      `--cloud-lifecycle auto` 一旦退出 with 就停机；非 retain 的实例连磁盘一起没。
      停机之后再想拉，只剩「重跑一遍再花一次钱」。
    ★ 它不是主路径：正常情况每镜跑完已经落盘（`comfy_local_video.download`）。
      这里兜的是「任务成功、下载失败」这种最难查的缺口。
    """
    try:
        from cloud import pull as PULL
    except Exception as exc:                                 # noqa: BLE001
        print('  [回传] 模块不可用（跳过）：%s' % str(exc).splitlines()[0][:120])
        return {"ok": False}
    try:
        res = PULL.pull(WS, ep=ep, url=url, history=history)
    except Exception as exc:                                 # noqa: BLE001
        print('  [回传] 失败（不影响停机判定）：%s' % str(exc).splitlines()[0][:160])
        return {"ok": False}

    got = res.get("downloaded") or []
    if got or res.get("failed"):
        for line in PULL.format_result(res).splitlines():
            print('  ' + line)
    else:
        print('  [回传] 远端 %d 个产物，本地均已存在' % res.get("found", 0))
    if not res.get("ok"):
        print('  [回传] 有 %d 个没拉下来 —— 实例即将停机，这些必须先补'
              % len(res.get("failed") or []))
        print('         处理：python -m cloud pull --workspace "%s" --ep %s --file <文件名>'
              % (WS, ep))
        print('         （先别停机：把 --cloud-lifecycle keep 用上，或手工在控制台续租）')

    gap = PULL.local_gaps(WS, ep)
    if gap.get("missing"):
        print('  [缺口] %s 仍有 %d 镜没有成片：%s'
              % (ep, len(gap["missing"]), '、'.join(gap["missing"][:8])))
        print('         重跑同一条命令即补（已完成的会自动跳过）')
    return res


def _batch_segments(ep) -> int:
    """读批次记录里成功出片的镜数（写进台账用）。读不到就 0，不影响流程。"""
    try:
        import json as _json
        p = OUT / ep / '_batch_local.json'
        d = _json.loads(p.read_text(encoding='utf-8'))
        return int(((d.get('totals') or {}).get('success')) or 0)
    except Exception:                                     # noqa: BLE001
        return 0


def _run_cloud_task(args, ep, url: str, lifecycle: str, label: str, workflow: str = '') -> int:
    """★ 任务级启停：租一台镜像 → 出片 → 归还（异常也归还）。

    钱的逻辑就在这几行：机器是**这次任务开着**的，就没有理由在任务结束后继续开着。
    借来的机器不动 —— 替别人关机是另一种事故（见 cloud/session.py 的三条语义）。
    """
    if str(_PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(_PROJECT_ROOT))
    from cloud import config as CCFG
    from cloud.session import CloudNotReady, Lease

    CCFG.hydrate_env()                     # settings.json 里的地址/受信域名补进环境
    cfg = CCFG.effective()
    # ★ 2026-11-06：原来是写死的 canvas —— 云端默认换版后这里会「预检核 pika、租机器按 canvas」。
    wf = workflow or _video_wf_default(cloud=True)
    lease = Lease(cfg, ws=WS, name=getattr(args, 'cloud_name', '') or '', url=url,
                  keep=(lifecycle == 'keep'), workflow=wf)
    try:
        with lease:
            u = lease.http_url
            print('  实例    ：%s' % u)
            if not _guard_ok(u):
                return 2                   # 退出 with 会照常停机
            rc, log, dt = _run_batch(args, ep, u, workflow)
            _pull_back(u, ep)              # ★ 必须在 with 内：退出就停机，文件随之消失
            lease.usage(episodes=1, segments=_batch_segments(ep))
    except CloudNotReady as exc:
        print('[FAIL] %s' % exc)
        return 2
    except (OSError, RuntimeError) as exc:                # noqa: BLE001
        print('[FAIL] 云端任务异常：%s' % str(exc).splitlines()[0][:200])
        return 2
    print('\n%s出片退出码 %s（耗时 %.1fs）；日志：%s' % (label, rc, dt, log))
    if rc == 3:
        print('★ 退出码 3 = 批次有缺口（不是失败）。直接重跑同一条命令即可补缺。')
    print('  实例已按 lifecycle=%s 收尾；对账：python -m cloud cost' % lifecycle)
    return rc


def _is_loopback_url(url: str) -> bool:
    import urllib.parse as _up
    h = (_up.urlsplit(str(url or '')).hostname or '').strip().lower()
    return h in ('127.0.0.1', 'localhost', '::1', '0.0.0.0', '')


def _guard_ok(url: str) -> bool:
    """守卫认不认这个域名（不探活）。"""
    import urllib.parse as _up
    host = (_up.urlsplit(str(url or '')).hostname or '').lower()
    if not host:
        print('[FAIL] 云端地址认不出主机：%r' % url)
        return False
    import _netguard as NG
    if NG.would_allow(host):
        return True
    print('[FAIL] 网络出口守卫不认识 %s。云端出片必须**逐条点名**远端主机：' % host)
    parts = host.split('.')
    print('       set SOLODRAMA_TRUSTED_HOSTS=*.%s' % '.'.join(parts[-3:]))
    print('       （也可以写完整域名；不要用 SOLODRAMA_ALLOW_REMOTE=1 图省事，那会放开整个互联网）')
    return False


def _cloud_url_ready(url: str) -> bool:
    """云端地址的两道前置：守卫认不认这个域名、服务通不通。返回 False 时已打印原因。"""
    if not _guard_ok(url):
        return False
    import _comfy_http as _Q
    p = _Q.probe(timeout=8)
    if not p.get('online'):
        print('[FAIL] 云端 ComfyUI 连不上：%s' % url)
        print('       %s' % str(p.get('error') or '').replace('\n', '\n       '))
        print('       · 实例没启动 → python -m cloud up ／ 控制台点启动')
        print('       · 端口不对 → 核对 --comfy-url（镜像通常映射到 8188）')
        return False
    print('  [就绪] ComfyUI v%s · %s · 显存 %.1f/%.1fG · %dms'
          % (p.get('version') or '?', p.get('device') or '?', p.get('vram_free_gb') or 0,
             p.get('vram_total_gb') or 0, p.get('latency_ms') or 0))
    return True


def cmd_video_run(args) -> int:
    # ★ 2026-11-04：出片默认走本地（￥0）。`--engine workflow` 显式切回 RunningHub。
    #   默认值改本地不是「省钱优先」，而是这条链现在的定位：创作在 Skill、执行在引擎，
    #   执行层不该默认产生平台费用。要算钱的通道必须被显式选中。
    # ★ 2026-11-05：`--engine cloud`（云端 ComfyUI 镜像）与 local 走**同一个执行器**，
    #   差别只在 COMFYUI_URL 与超时档位，所以同一条分支。注意它**不开 RH 平台闸** ——
    #   云端镜像走的是「受信远端」这条独立口子（SOLODRAMA_TRUSTED_HOSTS）。
    if (getattr(args, 'engine', None) or 'local') in ('local', 'cloud'):
        return cmd_video_local(args)
    # ★ 走到这里 = 用户显式选了平台通道。开闸放在分派之后、任何网络动作之前：
    #   本地通道在上面就 return 了，永远不会经过这行 —— 「默认不出网」是结构性的，
    #   不是靠某个默认值恰好没被改。
    _allow_platform_egress()
    if not args.yes:
        print('[闸门] 这会真实提交任务并计费。确认无误后加 --yes 重跑：')
        print('       python scripts/drama.py video run --yes%s%s'
              % (' --limit %d' % args.limit if args.limit else '',
                 ' --only %s' % args.only if args.only else ''))
        cmd_video_plan(argparse.Namespace(limit=args.limit, only=args.only))
        return 2
    rc = _model_gate('video', expected_engine='workflow')   # ★ 首次出片前：模型选择门禁
    if rc:
        return rc
    est = estimate_video(args.limit, args.only.split(',') if args.only else None,
                         tier=getattr(args, 'tier', 'consumer'))
    print('★ 开始真实出片：%d 段。费用以平台 usage 为准，跑完自动写台账。' % est['segments'])
    for line in _cost_lines(est['segments']):
        print(line)
    cmd = [sys.executable, RUN_PY, '--video-only']
    if args.resume:
        cmd += ['--resume', args.resume]
    if args.limit:
        cmd += ['--limit', str(args.limit)]
    if args.only:
        cmd += ['--only', args.only]
    if args.concurrency:
        cmd += ['--concurrency', str(args.concurrency)]
    # ★ 2026-10-20（反馈 P2-14）：单例锁。实测「同一脚本被启动两次 → 两条 lane 变四条 →
    #   同一镜重复生成，浪费约 2400 币」。这里在**提交任何任务之前**拦住。
    from _lock import single_instance
    try:
        with single_instance('video_run', WS):
            rc, log, dt = run_cmd(cmd, 'video_run', quiet_ok=False)
    except SystemExit:
        print('（已由单例锁拦下，未提交任何任务、未产生费用）')
        raise
    print('\n引擎退出码 %s（耗时 %.1fs）；日志：%s' % (rc, dt, log))
    batch = args.resume or _latest_batch()
    if batch:
        cmd_video_status(argparse.Namespace(batch=batch))
        print('\n单条重跑（不重复扣费）：python scripts/drama.py video run --yes --resume %s --only <shot_id>'
              % batch)
    return rc


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


def cmd_video_resume_download(args) -> int:
    """补下载「任务已成功但产物没落盘」的段（反馈 P1-7）。

    引擎在下载失败时会写 `<批次>/pending_download.json`（含 taskId + 直链），
    这里转调引擎的 `--resume-download`：只重下、不重新提交，因此**不会再扣一次费**。
    """
    cmd = [sys.executable, RUN_PY, '--resume-download']
    if getattr(args, 'batch', None):
        cmd += [args.batch]
    print('【补下载】读 pending_download.json，只重下不重提（不重复计费）')
    rc, log, dt = run_cmd(cmd, 'video_resume_download', quiet_ok=False)
    print('引擎退出码 %s（耗时 %.1fs）；日志：%s' % (rc, dt, log))
    return rc


# ---------------------------------------------------------------------------
# report / balance / refs / guide
# ---------------------------------------------------------------------------
def cmd_report(args) -> int:
    batch = args.batch or _latest_batch()
    if batch:
        cmd_video_status(argparse.Namespace(batch=batch))
        print()
    print('RunningHub 任务台账（自动记录，失败也记）')
    print('-' * 74)
    lr = VP / 'ledger' / 'runs'
    rows = []
    if lr.is_dir():
        for f in sorted(lr.glob('*.json')):
            d = read_json(f, {}) or {}
            for a in d.get('attempts', []):
                rows.append((d.get('shot_id'), a.get('status'), a.get('usage') or {},
                             a.get('artifact'), a.get('error')))
    if not rows:
        print('（台账为空）')
    else:
        for sid, status, u, art, err in rows[-40:]:
            cost = u.get('consumeCoins') and ('%s RH币' % u['consumeCoins']) or \
                   (u.get('thirdPartyConsumeMoney') and ('$%s' % u['thirdPartyConsumeMoney'])) or '—'
            print('  %-12s %-8s %-12s %s' % (sid, status, cost,
                                             (art or err or '')[:60].replace('\n', ' ')))
        print('\n合计：%d 条 attempt' % len(rows))
    print('\n完整成本报表：drama cost --json（或 cost_ledger.py --json）')
    return 0


def cmd_balance(args) -> int:
    rc, log, _ = run_cmd([sys.executable, SCRIPTS / 'rh_doctor.py', '--live'], 'balance')
    return rc


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


GUIDE = """短剧生产线 · 速查（python scripts/drama.py <命令>）
════════════════════════════════════════════════════════════════════════
★开工     setup               前置 7 项：画风/集数/每集时长/生图模型/视频模型+功能选项/分辨率/流水线
         setup set --style live_action --episodes 30 --ep-seconds 60 \\
             --image-model local_comfyui --video-model runninghub \\
             --workflow-id <id> --site https://www.runninghub.ai --account "主账号A" \\
             --resolution 1080x1920 --pipeline on --budget-coins 9000
         setup accounts      列出可用账号（只显示指纹，Key 本体不落盘）
         setup require       九项不齐 → 退出码 4（不许开工）
★流程     workflow            11 环节表：调研→剧本→资产设计→资产生成→视频提示词→视频生成
                             →发行资料→拼接→放大→字幕→定稿（顺序不可调）
         workflow status     进度 + 当前应做哪一环
         workflow check --stage S6   前置环节未完成 → 退出码 4
★流水线   pipeline plan       开工预告：预计完工时间 + 预计花费 + 预算余量（不花钱）
         pipeline run --yes  一次跑到底（预算熔断 → 退出码 3；等 Agent 产出 → 4）
         pipeline mark S3    登记内容环节完成
★配乐     bgm library         看库（--scan 用 ffprobe 补时长；共享库已预置 12 首 CC BY）
         bgm plan --ep ep01 --apply    生成铺排计划（情绪→增益/淡入淡出→ducking；相邻集自动不重复）
         bgm mix --ep ep01 --apply     混音（视频直通只重编码音频；S10 会自动接）
         bgm credits --ep ep01         出署名段（CC BY 必须署名，粘进发布文案）
看状态   status              全盘面板：数据/参考图/资产缺口/批次/台账（零网络，先跑这个）
模型     models              ★前置条件：首次生图/出片前必须确认模型（本地/云端/闭源三选一）
         models --ask        交互式引导确认（生图；换 video 传 models ask video）
         models list         可选清单：本地ComfyUI(￥0) / RunningHub(★计费) / 闭源模型(★计费)
         models set image=local_comfyui video=local_comfyui  记录确认（可一次两条）
         models reset video  换模型：先清除再重确认
体检     preflight           一次过 生成通道 + Key 分级 + 引擎 doctor + check + 预演（全免费）
资产     assets              缺资产就出图：默认**本地 ComfyUI ￥0**，干跑
         assets --engine local --submit            本机出图（不花钱，占 GPU；先出一张看风格）
         assets --engine local --check             体检 ComfyUI 是否在线（不出图）
         assets --engine local --only char_01      只出某个资产（断点续跑默认跳过已出图）
         assets --engine rh --submit --kind char   云端计费通道（★计费，按平台 usage 结算）
参考图   refs                瘦身体检；refs --apply --write-config 才写盘+改配置
出片     video plan          计划与成本预估（免费）；带 --limit/--only 可缩小范围
         video run --yes     真跑出片（★计费）；--limit 1 先出小样
         video status [批次] 某批次进度与失败清单
         video run --yes --resume <批次> --only <shot_id>   单条重跑（不重复扣费）
战报     report              批次汇总 + 台账（含每笔消耗与产物路径）
余额     balance             两把 Key 的余额（只读，不计费）
成本台账 cost                单次任务 + 全剧累计（RH币/美元钱包/token 三池表格）
         cost --checkpoint   ★ 收工结账：打印台账 + 记基线，下次即可看「单次任务增量」
════════════════════════════════════════════════════════════════════════
铁律：默认不花钱（要 --submit / --yes）；中断后一律用 --resume 续跑，不重新提交。
成本   ：本地通道 ￥0；计费通道按平台 usage 结算，累计见 `drama cost`（不预估价）
通道   ：assets --engine local（本地，￥0，默认）| rh（云端，★计费）
口径   ：消耗只认平台按任务返回的 usage —— **不用余额差值倒推消耗**
日志   ：video-pipeline/output/logs/   台账：video-pipeline/ledger/runs/
成本表 ：docs/成本台账.md（由 cost 命令生成）
"""


def cmd_cost(args) -> int:
    """成本台账：转发给 cost_ledger.py（单次任务 + 全剧累计 + 三池表格）。

    ★ 口径：消耗只取平台按任务返回的 usage；**不用余额差值倒推消耗**（用户 2026-09-19 明确）。
    ★ 2026-11-01：Excel 导出已删（能力清单 L8），只产 markdown / JSON。
    """
    cmd = [sys.executable, SCRIPTS / 'cost_ledger.py']
    for flag, on in (('--checkpoint', args.checkpoint), ('--json', args.json),
                     ('--balance', args.balance), ('--no-write', args.no_write)):
        if on:
            cmd.append(flag)
    if args.md:
        cmd += ['--md', args.md]
    # ★ 2026-10-20（反馈 P0-3）：剧名默认从工作区推导（brief.json → project.json → 目录名），
    #   不再让 cost_ledger 里的 `DRAMA_DEFAULT` 决定交付物文件名。
    drama_name = args.drama or _WSMOD.drama_name(WS)
    cmd += ['--drama', drama_name]
    print('【成本台账】单次任务 + 全剧累计（口径：只认平台 usage，不用余额倒推）')
    print('           剧名：%s%s' % (drama_name, '' if args.drama else '（由工作区推导；可用 --drama 覆盖）'))
    rc, _, _ = run_cmd(cmd, 'cost_ledger', quiet_ok=False)
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


def _add_cost_tier_args(q) -> None:
    q.add_argument('--tier', choices=('consumer', 'ent_shared'), default='consumer',
                   help='按哪类 Key 的计价公式预估（consumer=消费级会员；ent_shared=企业级共享）')


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
    # ★ 默认本地：RH 通道能力保留，但新项目一建出来不该指向付费/出网通道。
    p.add_argument('--image-engine', dest='image_engine', default='local_comfyui',
                   choices=['local_comfyui', 'runninghub'])
    p.add_argument('--video-engine', dest='video_engine', default='local_comfyui',
                   choices=['local_comfyui', 'runninghub'])
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

    p = sub.add_parser('nodes', help='七环节 23 节点全状态')
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

    p = sub.add_parser('preflight', help='一次过体检（免费）：依赖→生成通道→RH→引擎→配置→预演')
    _add_ws_arg(p)
    p.add_argument('--only', default='all',
                   help='只跑某几段：deps,gen,rh,engine,config,dryrun（逗号分隔，默认 all）')
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
    p.add_argument('--engine', choices=('local', 'cloud', 'wf', 'rh'), default='local',
                   help='出图通道：local=本地 ComfyUI（￥0，默认）｜wf=RunningHub 工作流（★计费）'
                        '｜rh 是 wf 的旧别名')
    p.add_argument('--ratio', default=None, help='仅 wf：画幅裸值，如 9:16')
    p.add_argument('--mode', choices=('t2i', 'i2i'), default=None,
                   help='仅 wf：t2i=文生图｜i2i=图生图（必须给 --ref）')
    p.add_argument('--ref', action='append', default=[],
                   help='仅 wf：参考图路径（i2i 必填，可多次）')
    p.add_argument('--submit', action='store_true',
                   help='真的出图：local 占 GPU 不花钱；wf ★计费（按张）')
    p.add_argument('--kind', choices=('all', 'char', 'scene', 'prop'), default='all',
                   help='只做某一类（prop 仅本地通道支持）')
    p.add_argument('--only', default=None, help='只做这些（名字或序号 / 资产 id，逗号分隔）')
    p.add_argument('--force', action='store_true', help='已生成的也重跑（rh 通道会重复计费）')
    p.add_argument('--check', action='store_true', help='仅 local：体检 ComfyUI 是否在线，不出图')
    p.set_defaults(fn=cmd_assets)

    p = sub.add_parser('refs', help='参考图瘦身')
    _add_ws_arg(p)
    p.add_argument('--apply', action='store_true', help='真的写盘')
    p.add_argument('--write-config', action='store_true', help='顺带把 characters.json 指到新目录')
    p.set_defaults(fn=cmd_refs)

    # ★ 模型选择门禁（前置条件）：首次生图 / 首次出片前必须先确认「依托哪条通道」
    p = sub.add_parser('models', help='首次生图/出片前确认通道：本地ComfyUI / 云端ComfyUI / RH AI应用 / 闭源模型')
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
    q.add_argument('--comfy-url', dest='comfy_url', default=None, help='ComfyUI 服务地址（本地/云端）')
    q.add_argument('--comfy-workflow', dest='comfy_workflow', default=None,
                   help='ComfyUI 工作流 API 文件路径（「导出（API）」得到的 json）')
    q.add_argument('--app-url', dest='app_url', default=None, help='RunningHub AI 应用地址')
    q.add_argument('--app-id', dest='app_id', default=None, help='RunningHub AI 应用 ID（webappId）')
    q.add_argument('--workflow-id', dest='workflow_id', default=None, help='RunningHub 工作流 ID')
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
    p = sub.add_parser('style', help='画风库确认：track（3d_manhua/2d_animation/live_action）+ look + narrative')
    _add_ws_arg(p)
    ss = p.add_subparsers(dest='style_cmd')
    q = ss.add_parser('list', help='打印可选画风清单（含各自规格）')
    _add_ws_arg(q)
    q.set_defaults(fn=cmd_style)
    q = ss.add_parser('status', help='查看当前画风确认状态（只读）')
    _add_ws_arg(q)
    q.add_argument('--json', action='store_true')
    q.set_defaults(fn=cmd_style)
    q = ss.add_parser('set', help='记录确认：set 3d_manhua|2d_animation|live_action [--sub-mode ...]')
    _add_ws_arg(q)
    q.add_argument('choice', choices=('3d_manhua', '2d_animation', 'live_action'))
    q.add_argument('--sub-mode', dest='sub_mode', default=None)
    q.set_defaults(fn=cmd_style)
    q = ss.add_parser('reset', help='清除画风确认（换画风前用；已产出素材会作废）')
    _add_ws_arg(q)
    q.set_defaults(fn=cmd_style)
    q = ss.add_parser('ask', help='交互式引导确认（需 TTY）')
    _add_ws_arg(q)
    q.set_defaults(fn=cmd_style)
    q = ss.add_parser('require', help='门禁查询（未过则退出码 4；供上游脚本调用）')
    _add_ws_arg(q)
    q.set_defaults(fn=cmd_style)
    p.set_defaults(fn=cmd_style, style_cmd=None)


    pv = sub.add_parser('video', help='出片')
    _add_ws_arg(pv)
    vs = pv.add_subparsers(dest='vcmd')
    q = vs.add_parser('plan', help='计划与成本预估（免费）')
    _add_ws_arg(q)
    q.add_argument('--limit', type=int)
    q.add_argument('--only')
    _add_cost_tier_args(q)
    q.add_argument('--calibrate', action='store_true',
                   help='用历史台账（真实 usage）拟合单价，而不是用内置默认值')
    q.add_argument('--save-calibration', dest='save_calibration', action='store_true',
                   help='把校准结果写入 <工作区>/cost-model.json（样本不足则不写）')
    q.set_defaults(fn=cmd_video_plan)
    q = vs.add_parser('run', help='真跑出片（本地 ￥0 / 云端 ★计费；都需 --yes）')
    _add_ws_arg(q)
    q.add_argument('--engine', choices=('local', 'cloud', 'workflow'), default='local',
                   help='出片通道：local=本机 ComfyUI（￥0，默认）｜cloud=云端 ComfyUI 镜像（★计费/自建）｜workflow=RunningHub（★计费）')
    q.add_argument('--ep', default=None, help='集号（local/cloud 通道必填；ep01 / 1）')
    q.add_argument('--force', action='store_true', help='local/cloud：已有产物也重跑')
    q.add_argument('--comfy-url', dest='comfy_url', default=None,
                   help='local/cloud：ComfyUI 地址（云端镜像如 https://<实例>-8188.container.x-gpu.com）')
    q.add_argument('--cloud-lifecycle', dest='cloud_lifecycle',
                   choices=('auto', 'keep', 'off'), default='auto',
                   help='cloud：auto=要跑才开/跑完就关（默认）｜keep=跑完保留（★继续计费）｜off=不启停')
    q.add_argument('--cloud-name', dest='cloud_name', default='',
                   help='cloud：实例名（幂等键：同名在跑则复用；空=按时间自动命名）')
    q.add_argument('--workflow', default='',
                   help='出片工作流（默认取确认单 → 环境变量 → 仓库默认 canvas）；'
                        '本机只有 4 步模型时可给 workflow_h3_local.json')
    q.add_argument('--map', default='', help='节点映射（默认读同名 sidecar）')
    q.add_argument('--timeout-min', dest='timeout_min', type=float, default=None,
                   help='local/cloud：单镜轮询超时（分钟；不给=按链路自动，远端 30 / 本地 20）')
    q.add_argument('--yes', action='store_true', help='确认执行闸门（计费通道同时是计费闸门）')
    q.add_argument('--mp', type=float, default=None,
                   help='local：目标兆像素；8G 卡跑 100+ 帧建议 ≤0.3（0.25 约 384x672）')
    q.add_argument('--aspect', default=None,
                   help='local：画幅，如 "9:16 (Portrait Widescreen)"')
    q.add_argument('--limit', type=int)
    q.add_argument('--only')
    q.add_argument('--resume', metavar='BATCH_ID')
    q.add_argument('--concurrency', type=int)
    _add_cost_tier_args(q)
    q.set_defaults(fn=cmd_video_run)
    q = vs.add_parser('resume-download', help='补下载：任务已成功但产物没落盘（不重复计费）')
    _add_ws_arg(q)
    q.add_argument('batch', nargs='?', default=None, help='批次 ID；默认扫描全部批次')
    q.set_defaults(fn=cmd_video_resume_download)
    q = vs.add_parser('status', help='批次进度')
    _add_ws_arg(q)
    q.add_argument('batch', nargs='?', default=None)
    q.set_defaults(fn=cmd_video_status)

    p = sub.add_parser('report', help='战报')
    _add_ws_arg(p)
    p.add_argument('--batch', default=None)
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser('balance', help='Key 余额（只读）')
    _add_ws_arg(p)
    p.set_defaults(fn=cmd_balance)

    p = sub.add_parser('cost', help='成本台账：单次任务 + 全剧累计（markdown / JSON）')
    _add_ws_arg(p)
    p.add_argument('--checkpoint', action='store_true',
                   help='★ 收工结账：打印台账 + 记基线（下次即可看单次增量与 token 归属）')
    p.add_argument('--json', action='store_true', help='机器可读')
    p.add_argument('--balance', action='store_true',
                   help='附带只读余额（仅判断够不够跑，不参与消耗统计）')
    p.add_argument('--md', default=None, help='markdown 输出路径（默认 docs\\成本台账.md）')
    p.add_argument('--no-write', action='store_true', help='只打印，不写任何文件')
    p.add_argument('--drama', default=None, help='短剧名（决定报表文件名与表标题）')
    p.set_defaults(fn=cmd_cost)

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
