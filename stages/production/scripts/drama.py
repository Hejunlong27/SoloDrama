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
    setup      show|ask|set|require|accounts  ★开工前置 9 项：画风 / 集数 / 每集时长 / 生图模型 /
                                          视频模型与功能选项 / **工作流 API** / **账号 API Key** /
                                          分辨率 / 是否流水线（落 project-setup.json；未齐退出码 4）
    workflow   list|status|next|check|done|skip  ★标准作业 11 环节（产物判据 + 顺序门禁）
    pipeline   plan|run --yes|mark|status  ★流水线模式：一次确认 → 预算上限 → 跑完整部剧
    status     [--json]                  全盘状态面板：数据/参考图/资产缺口/批次/台账（零网络）
    models     [list|status|set|reset|ask]  ★前置条件：首次生图/出片前确认模型
                                          （本地 ComfyUI / RunningHub / 闭源模型 三选一，写 model-plan.json）
    preflight                            一次性体检：Key 分级 + 引擎 doctor + check + 预演（全免费）
    assets     [--engine local|rh] [...] 缺失资产出图（默认本地 ComfyUI ￥0 且干跑）
                                          local=本机出图（不花钱，占 GPU）；rh=RunningHub 云端（★计费）
                                          ★首次 --submit 前会先查模型选择门禁
    refs       [--apply]                 参考图瘦身（6000px 超 H3 上限 5760 必须做）
    video plan [--limit N] [--only ids]  出片计划与成本预估（免费，不提交）
    video run  --yes [...]               真跑出片（★计费；--yes 是闸门；★首次前会先查模型选择门禁）
    video status [BATCH]                 某批次进度（读 summary.json）
    report     [--latest|--batch ID]     战报：批次汇总 + 台账聚合 + 成本
    balance                              两把 Key 的余额（只读，不计费）
    cost [--checkpoint] [--balance] [--json]  成本台账：单次任务 + 全剧累计（三池表格）
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
    if any(a in ('-h', '--help') for a in sys.argv[1:]):
        print('短剧生产线的零思考入口（默认不花钱）\n')
        print('用法: drama.py <命令> [...]  （下面这些命令都需要先指定工作区）')
        print('  全局参数: --workspace <DIR>   也可设环境变量 SOLODRAMA_WORKSPACE\n')
        print('命令: setup {show|ask|set|require} / workflow {list|status|check} /')
        print('      pipeline {plan|run|mark|status} / status / preflight / assets / refs /')
        print('      models / style / halfcheck / video {plan|run|resume-download|status} /')
        print('      report / balance / cost / guide')
        print('\n例：drama.py --workspace "D:/剧/某剧" status')
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
RUN_PY = SKILL / 'scripts' / 'run.py'
CHECK_BILLING = SKILL / 'scripts' / 'check_billing.py'
MODEL_GATE_PY = SCRIPTS / 'model_gate.py'      # ★ 首次生图/出片前的模型选择门禁
LOG_DIR = OUT / 'logs'

CNY_PER_RH = 0.0025          # 1 RH币 ≈ ¥0.0025（用户 2026-09-18）；★ 2026-09-19 用户另给 RH币↔USD：
                             # 1 美元 = 2746 RH币（1 RH币 ≈ $0.0003642）。两者隐含 USD/CNY ≈ 6.865，该汇率未确认。
CHAR_RH_PER_IMAGE = 27       # 实测：人物定妆图 27 RH币/张
SCENE_USD_PER_IMAGE = 0.01   # 实测：场景图扣美元钱包 $0.01/张 ≈ ￥0.07
USD_CNY = 7.0


# ---------------------------------------------------------------------------
# 环境：进程环境里没有的 Key，从「用户级环境变量」补（agent 的 shell 常拿不到）
# ---------------------------------------------------------------------------
def _harden_stdio() -> None:
    """★ 中文 Windows 控制台是 GBK(cp936)，而管道/重定向通常按 UTF-8 读 —— 两种情况要求相反：

    * **在控制台里跑（双击 .bat）**：必须用控制台自己的代码页，否则中文全乱码；
    * **被管道/文件捕获（agent、日志）**：必须 UTF-8，否则读出来是乱码。

    所以按 `isatty()` 分流，并且一律把 errors 放宽成 replace（防 GBK 装不下的字符直接抛异常）。
    第二层保险：正文不使用 GBK 装不下的符号（用 [OK]/[NG]/-> 代替）。
    """
    try:
        enc = 'utf-8'
        if sys.stdout.isatty() and os.name == 'nt':
            import ctypes
            cp = ctypes.windll.kernel32.GetConsoleOutputCP()
            if cp:
                enc = 'cp%d' % cp
        for s in (sys.stdout, sys.stderr):
            try:
                s.reconfigure(encoding=enc, errors='replace')   # type: ignore[union-attr]
            except Exception:                                    # noqa: BLE001
                pass
    except Exception:                                            # noqa: BLE001
        pass


def hydrate_env() -> None:
    # ★ 进程环境里缺的，从「用户级环境变量」补（agent 的 shell 常拿不到）：
    #   前三个是云端通道用的 Key；SOLODRAMA_ASSET_MD 是「资产提示词 md」真源，**本地通道也要用**。
    #   ★ 2026-10-13 改名过渡：新旧两个名字都参与补全，子脚本按「新名优先、旧名回退」读取。
    want = ('RUNNINGHUB_API_KEY', 'RUNNINGHUB_ENT_API_KEY', 'RUNNINGHUB_BASE_URL',
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
    shots = read_json(DATA / 'shots.json', []) or []
    prompts = read_json(DATA / 'h3_prompts.json', {}) or {}
    chars = read_json(DATA / 'characters.json', {}) or {}
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
    shots = read_json(DATA / 'shots.json', []) or []
    if only:
        want = {o.strip() for o in only if o and o.strip()}
        shots = [s for s in shots if s.get('shot_id') in want]
    if limit:
        shots = shots[:limit]
    return shots


def _durations(shots) -> list:
    prompts = read_json(DATA / 'h3_prompts.json', {}) or {}
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
    try:
        import project_setup as _PS
        _vo = (_PS.collect(WS)["items"].get("video_options") or {})
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
    verdict = []

    print('【0/4】运行依赖自检（不联网）')
    if not _print_dep_report(check_dependencies()):
        verdict.append(('运行依赖', False, '装完依赖再体检'))
        print('\n' + '=' * 74)
        print('体检结论')
        print('=' * 74)
        for name, ok, extra in verdict:
            print('  %-12s %s %s' % (name, '[OK] 通过' if ok else '[NG] 需处理', extra))
        return 1
    verdict.append(('运行依赖', True, ''))

    print('\n【1/4】RunningHub Key 分级（只读，不计费）')
    rc1, _, _ = run_cmd([sys.executable, SCRIPTS / 'rh_doctor.py', '--check', 'model'],
                        'preflight_rhdoctor', quiet_ok=False)
    verdict.append(('Key 分级路由', rc1 == 0, ''))

    print('\n【2/4】引擎环境体检（不联网）')
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

    print('\n【3/4】必填配置检查')
    # ★ 必须带 --video-only：本线只跑 --video-only，图片工作流(banana)确实不需要。
    #   不带的话引擎会拿「图片工作流未配置」判失败，而这里以前**只取 rc 不进 verdict**，
    #   于是体检永远显示全绿、真实出片却被配置闸门挡下（2026-09-19 实测踩到）。
    rc3, _, _ = run_cmd([sys.executable, RUN_PY, 'check', '--video-only'], 'preflight_check')
    verdict.append(('必填配置', rc3 == 0, '图片工作流不参与 --video-only 校验'))

    print('\n【4/4】预演（零网络请求，不提交任何任务）')
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
    """转发给 style_gate.py（画风三轨门禁：status / list / set / reset / ask / require）。"""
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


def cmd_halfcheck(args) -> int:
    """转发给 half_narrated_check.py（半解说结构三类硬校验）。"""
    HC_PY = SCRIPTS / 'half_narrated_check.py'
    cmd = [sys.executable, HC_PY, '--workspace', str(WS)]
    if getattr(args, 'which', None):
        cmd.append(args.which)
    return run_cmd(cmd, 'halfcheck', quiet_ok=False)[0]


# ---------------------------------------------------------------------------
# assets：缺失资产出图（默认本地 ComfyUI ￥0；可选 RunningHub 云端计费）
# ---------------------------------------------------------------------------
LOCAL_ASSETS_PY = SCRIPTS / 'gen_assets_local.py'


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
    if getattr(args, 'engine', 'local') == 'local':
        return cmd_assets_local(args)

    if args.submit:                       # ★ 首次生图前：模型选择门禁（云端通道）
        rc = _model_gate('image', expected_engine='rh')
        if rc:
            return rc
    kinds = [args.kind] if args.kind != 'all' else ['char', 'scene']
    total_rc = 0
    if 'char' in kinds:
        cmd = [sys.executable, SCRIPTS / 'gen_char_assets.py']
        if args.only:
            cmd += ['--only', args.only]
        if args.submit:
            cmd += ['--submit']
        if args.force:
            cmd += ['--force']
        print('【人物定妆图】%s（27 RH币/张）'
              % ('★真实提交' if args.submit else '干跑，不花钱'))
        rc, _, _ = run_cmd(cmd, 'assets_char', quiet_ok=False)
        total_rc |= rc
        if rc and args.submit:
            print('人物这一路失败，按「先止损」原则不再继续场景。修好再用 --kind scene 单独跑。')
            return rc
    if 'scene' in kinds:
        cmd = [sys.executable, SCRIPTS / 'gen_scene_assets.py']
        if args.only:
            cmd += ['--only', args.only]
        if args.submit:
            cmd += ['--submit']
        if args.force:
            cmd += ['--force']
        print('\n【场景空镜】%s（$0.01/张 ≈ ￥0.07）'
              % ('★真实提交' if args.submit else '干跑，不花钱'))
        rc, _, _ = run_cmd(cmd, 'assets_scene', quiet_ok=False)
        total_rc |= rc
    print('\n产物清单：%s' % (DATA / 'char_assets_manifest.json'))
    print('          %s' % (DATA / 'scene_assets_manifest.json'))
    return total_rc


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


def cmd_video_plan(args) -> int:
    est = estimate_video(args.limit, args.only.split(',') if args.only else None,
                         tier=getattr(args, 'tier', 'consumer'),
                         calibrate=getattr(args, 'calibrate', False))
    print('出片计划（免费，不提交任何任务）')
    print('-' * 74)
    print('  将提交      : %d 段' % est['segments'])
    print('  Key tier    : %s' % est['tier_label'])
    print('  两段式预估  : 固定 %s + 变动 %s = %s%s ≈ ￥%.2f'
          % (est['fixed_total'], est['variable_total'],
             est['coins'], ' RH币', est['cny']))
    print('  GPU 秒口径  : %.0f 运行秒 × 0.205 ≈ %d RH币'
          % (est['gpu_seconds'], round(est['gpu_model_coins'])))
    print('  参数来源    : %s' % est['_params_source'])
    _a = est.get('assumptions') or {}
    if _a:
        print('  计算量口径  : %s 步 / %s MP（相对基准 ×%.2f；沿用开工确认单）'
              % (_a['steps'], _a['megapixels'], _a['work_scale']))
    cal = est.get('_calibrate')
    if cal:
        ev = cal.get('evidence') or {}
        if cal.get('fitted'):
            print('  自校准      : %s（样本 %s：币 %s / 钱包 %s / 运行秒 %s）'
                  % (json.dumps(cal['fitted'], ensure_ascii=False),
                     ev.get('samples'), ev.get('coin_fit_samples', 0),
                     ev.get('money_fit_samples', 0), ev.get('gpu_ratio_samples', 0)))
        else:
            print('  自校准      : 历史台账样本不足（需 ≥3 条带 usage 的记录），本次沿用默认参数')
    print('  口径说明    : %s' % est['_caveat'])
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
    print('  续跑同一批次（不重复扣费）：python scripts/drama.py video run --yes --resume <批次>')
    print('  用历史台账校准单价：python scripts/drama.py video plan --calibrate --save-calibration')
    if getattr(args, 'save_calibration', False):
        if cal and cal.get('fitted'):
            import cost_model as CM
            p = CM.write_params(WS, cal['params'])
            print('  [OK] 已把校准结果写入 %s（下次预估自动使用）' % p)
        else:
            print('  [WARN] 样本不足，未写 cost-model.json（不臆造单价）')
    return 0


def cmd_video_run(args) -> int:
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
    print('★ 开始真实出片：%d 段，预估 %d RH币 ≈ ￥%.2f（%s；以 usage 为准）'
          % (est['segments'], est['coins'], est['cny'], est['tier_label']))
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
    print('\n完整成本报表（含本地 agent token，DSH 账本）：')
    print('  python scripts/cost_report.py')
    return 0


def cmd_balance(args) -> int:
    rc, log, _ = run_cmd([sys.executable, SCRIPTS / 'rh_doctor.py', '--live'], 'balance')
    return rc


def cmd_refs(args) -> int:
    cmd = [sys.executable, SCRIPTS / 'prepare_refs.py']
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
看状态   status              全盘面板：数据/参考图/资产缺口/批次/台账（零网络，先跑这个）
模型     models              ★前置条件：首次生图/出片前必须确认模型（本地/云端/闭源三选一）
         models --ask        交互式引导确认（生图；换 video 传 models ask video）
         models list         可选清单：本地ComfyUI(￥0) / RunningHub(★计费) / 闭源模型(★计费)
         models set image=local_comfyui video=runninghub    记录确认（可一次两条）
         models reset video  换模型：先清除再重确认
体检     preflight           一次过 Key 分级 + 引擎 doctor + check + 预演（全免费）
资产     assets              缺资产就出图：默认**本地 ComfyUI ￥0**，干跑
         assets --engine local --submit            本机出图（不花钱，占 GPU；先出一张看风格）
         assets --engine local --check             体检 ComfyUI 是否在线（不出图）
         assets --engine local --only char_01      只出某个资产（断点续跑默认跳过已出图）
         assets --engine rh --submit --kind char   云端计费通道（人物 27 RH币/张，场景 $0.01/张）
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
成本   ：资产 本地 ComfyUI ￥0 / 云端人物 17-27 RH币/张 / 场景 $0.01/张 | 视频 78-209 RH币/段
通道   ：assets --engine local（本地，￥0，默认）| rh（云端，★计费）
口径   ：消耗只认平台按任务返回的 usage —— **不用余额差值倒推消耗**
日志   ：video-pipeline/output/logs/   台账：video-pipeline/ledger/runs/
成本表 ：docs/成本台账.md（由 cost 命令生成）
"""


def cmd_cost(args) -> int:
    """成本台账：转发给 cost_ledger.py（单次任务 + 全剧累计 + 三池表格 + Excel）。

    ★ 口径：消耗只取平台按任务返回的 usage；**不用余额差值倒推消耗**（用户 2026-09-19 明确）。
    ★ 默认同时产出 Excel（docs\\成本台账_<剧名>.xlsx）与 markdown（docs\\成本台账.md）。
    """
    cmd = [sys.executable, SCRIPTS / 'cost_ledger.py']
    for flag, on in (('--checkpoint', args.checkpoint), ('--json', args.json),
                     ('--balance', args.balance), ('--no-write', args.no_write)):
        if on:
            cmd.append(flag)
    if not args.no_xlsx:
        cmd.append('--xlsx')
    if args.xlsx_only:
        cmd.append('--no-md')
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
#     * project_setup.py —— 开工前置 7 项（画风/集数/时长/生图/视频/分辨率/流水线）
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

    p = sub.add_parser('status', help='全盘状态面板')
    p.add_argument('--json', action='store_true')
    _add_ws_arg(p)
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser('preflight', help='一次过体检（免费）')
    _add_ws_arg(p)
    p.set_defaults(fn=cmd_preflight)

    p = sub.add_parser('assets', help='缺失资产出图（默认本地 ComfyUI ￥0，干跑）')
    _add_ws_arg(p)
    p.add_argument('--engine', choices=('local', 'rh'), default='local',
                   help='出图通道：local=本地 ComfyUI（￥0，默认）；rh=RunningHub 云端（★计费）')
    p.add_argument('--submit', action='store_true',
                   help='真的出图：local 占 GPU 不花钱；rh ★计费（人物 27 RH币/张，场景 $0.01/张）')
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
    q = ms.add_parser('set', help='记录确认：set image=local_comfyui [video=runninghub]')
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

    # ★ 画风三轨门禁（前置条件）：任务开始前必须先确认画风（3D 漫剧 / 2D 动画 / 真人）
    p = sub.add_parser('style', help='画风三轨确认：3d_manhua / 2d_animation / live_action')
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

    # ★ 半解说结构校验（旁白时间窗 / 资产规格 / 首帧锚点）
    p = sub.add_parser('halfcheck', help='半解说结构三类硬校验（读 05-分镜/storyboard.json）')
    _add_ws_arg(p)
    p.add_argument('which', nargs='?', default='all', choices=('all', 'windows', 'assets', 'anchors'))
    p.set_defaults(fn=cmd_halfcheck)

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
    q = vs.add_parser('run', help='真跑出片（★计费，需 --yes）')
    _add_ws_arg(q)
    q.add_argument('--yes', action='store_true', help='确认计费闸门')
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

    p = sub.add_parser('cost', help='成本台账：单次任务 + 全剧累计（Excel + markdown）')
    _add_ws_arg(p)
    p.add_argument('--checkpoint', action='store_true',
                   help='★ 收工结账：打印台账 + 记基线（下次即可看单次增量与 token 归属）')
    p.add_argument('--json', action='store_true', help='机器可读')
    p.add_argument('--balance', action='store_true',
                   help='附带只读余额（仅判断够不够跑，不参与消耗统计）')
    p.add_argument('--md', default=None, help='markdown 输出路径（默认 docs\\成本台账.md）')
    p.add_argument('--no-write', action='store_true', help='只打印，不写任何文件')
    p.add_argument('--no-xlsx', action='store_true', help='不生成 Excel（默认生成）')
    p.add_argument('--xlsx-only', action='store_true', help='只出 Excel，不出 markdown')
    p.add_argument('--drama', default=None, help='短剧名（决定 Excel 文件名与表标题）')
    p.set_defaults(fn=cmd_cost)

    p = sub.add_parser('guide', help='打印速查')
    _add_ws_arg(p)
    p.set_defaults(fn=cmd_guide)

    # ★ 2026-10-21：开工前置条件 · 标准流程 · 流水线模式（薄转发，参数全透传）
    for name, script, title, brief in (
        ('setup', 'project_setup.py', '开工前置条件（9 项）',
         'show / ask / set / require / accounts'),
        ('workflow', 'workflow.py', '标准作业流程（11 环节）',
         'list / status / next / check / done / skip'),
        ('pipeline', 'pipeline.py', '流水线模式（一次确认跑完整部剧）',
         'plan / run --yes / mark / status'),
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
