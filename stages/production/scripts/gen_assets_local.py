#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""gen_assets_local.py —— 用**本地 ComfyUI**生成短剧资产图（人物/场景/道具），￥0 成本

与另两条资产通道的关系
----------------------
| 通道 | 脚本 | 引擎 | 成本 |
|---|---|---|---|
| **本地 ComfyUI**（本脚本） | `gen_assets_local.py` | `stages/assets/comfyui/comfy_client.py` | **￥0**（只花本机电与时间） |
| 云端 ComfyUI | 同脚本 | `COMFYUI_URL` 指向云端 | 云主机费用 |
| RunningHub 工作流 | `gen_assets_rh_workflow.py` | RH nodeInfoList | 按张计费 |

两条**通道**，由 `drama.py assets --engine {local,wf}` 切换（默认 local）。
★ 2026-11-01：原来的「RH AI 应用」两个脚本（`gen_char_assets` / `gen_scene_assets`）已删 ——
引擎侧没有对应 provider，且与工作流通道做的是同一件事。

本脚本做什么（薄桥，不做重活）
------------------------------
1. 读 `SOLODRAMA_ASSET_MD` 指向的「资产提示词 md」（**与云端两脚本同一真源**）；
2. 调 `stages/assets/scripts/asset_md.py` 转成 ComfyUI 清单 `comfyui_manifest.json`；
3. 调 `stages/assets/comfyui/comfy_client.py` 出图到 `<工作区>/video-pipeline/output/assets/`；
4. 汇总产物写 `comfyui_assets_manifest.json`，并按**统一台账口径**补记 `ledger/runs/`（route=local、消耗为 0）。

计费纪律（本通道没有计费，但闸门照旧）
--------------------------------------
默认 **dry-run**：只打印将生成的清单，不调用 ComfyUI。必须显式 `--submit` 才真的出图。
理由不是省钱（本地不花钱），而是**别在没确认风格时批量跑掉十几分钟 GPU**。

依赖纪律：纯标准库 + `asset_md` + `run_ledger`（后者亦为纯标准库）。
**不需要 httpx、不需要 `RUNNINGHUB_*` 任何 Key。**
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[3]      # .../SoloDrama
ENGINE = _PROJECT_ROOT / 'stages' / 'video' / 'workflow' / 'scripts' / 'engine'
COMFY_DIR = _PROJECT_ROOT / 'stages' / 'assets' / 'comfyui'
COMFY_PY = COMFY_DIR / 'comfy_client.py'
ASSETS_SCRIPTS = _PROJECT_ROOT / 'stages' / 'assets' / 'scripts'

sys.path.insert(0, str(ENGINE))            # run_ledger（纯标准库）
sys.path.append(str(ASSETS_SCRIPTS))       # asset_md（纯标准库）
sys.path.append(str(pathlib.Path(__file__).resolve().parent))   # _ws
os.environ.setdefault('PYTHONUTF8', '1')

from run_ledger import RunLedger            # noqa: E402
import asset_md as AM                       # noqa: E402
from _ws import WS, DATA, ASSETS as ASSETS_ROOT    # noqa: E402  ★ 分阶段目录真源

try:                                        # Windows 控制台 GBK → UTF-8
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')    # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')    # type: ignore[union-attr]
except Exception:                                                 # noqa: BLE001
    pass

def _apply_model_plan_env() -> dict:
    """★ 2026-10-19（用户选 A）：把 model-plan.json 里的执行依据回灌成 COMFYUI_* 环境变量。

    为什么需要：`comfy_client.py` 只认环境变量（COMFYUI_WORKFLOW / COMFYUI_NODE_*），
    而「用户确认的是哪个工作流」只记在 model-plan.json 里。两边不连线时，换工作流会**静默
    回落仓库默认工作流**，随后报 `KeyError: '<节点id>'`（看起来像模型没装），排查成本极高。
    这里把确认单当作唯一真源：工作流路径、服务地址、节点映射都从确认单读，读不到才回落环境变量。

    detail 里可选 `comfy_nodes` 对象：{"prompt": "488", "prefix": "487", "aspect": "13", "latent": "474", "seed": "10"}
    """
    applied = {}
    mp = WS / 'model-plan.json'
    if not mp.is_file():
        return applied
    try:
        d = json.loads(mp.read_text(encoding='utf-8'))
    except Exception:                                            # noqa: BLE001
        return applied
    node = (((d.get('models') or {}).get('image') or {}))
    det = node.get('detail') or {}
    wf = det.get('comfy_workflow') or ''
    if wf and pathlib.Path(wf).is_file():
        os.environ.setdefault('COMFYUI_WORKFLOW', wf)
        applied['COMFYUI_WORKFLOW'] = wf
    # ★ 2026-11-05（按类隔离）：这里必须**覆盖**而不是 setdefault。
    #   背景：`COMFYUI_URL` 是 image/video 共用的全局变量。一旦进程里已有别的值
    #   （上一步云端出片留下的、或 settings 里配的云端地址），setdefault 会让
    #   「图像接本地、视频接云端」这条拼凑方案失效 —— 图像会**静默打到云端**。
    #   确认单是按类记的，它对这一类就是最终依据；覆盖并打印来源，才可解释。
    url = det.get('comfy_url') or ''
    if url:
        old = os.environ.get('COMFYUI_URL')
        os.environ['COMFYUI_URL'] = url
        applied['COMFYUI_URL'] = url if not old or old == url else '%s（原 %s）' % (url, old)
    for k, v in (det.get('comfy_nodes') or {}).items():
        env = 'COMFYUI_NODE_' + str(k).upper()
        os.environ.setdefault(env, str(v))
        applied[env] = str(v)
    return applied


VP = WS / 'video-pipeline'   # 引擎技术目录
# ★ 2026-11-02（分支 feat/pack-engine）：资产提示词的真源不再只有「一份 md」。
#   新分支的输入是制作包（`<ws>/pack/assets/*.json`），`--pack` 直接吃它；
#   `SOLODRAMA_ASSET_MD` 保留给老项目和手工 md 通道。两者都缺时在 main() 里报错，
#   而不是在 import 期 sys.exit —— 否则 `--pack` 这条路连 --help 都走不到。
_MD_ENV = ((os.environ.get('SOLODRAMA_ASSET_MD') or os.environ.get('DRAMA_ASSET_MD')) or '').strip()
ASSET_MD = pathlib.Path(_MD_ENV) if _MD_ENV else None

MANIFEST = DATA / 'comfyui_manifest.json'
PROD_MANIFEST = DATA / 'comfyui_assets_manifest.json'
OUT_DIR = ASSETS_ROOT        # ★ 2026-10-19：落 04-资产/{characters,scenes,props}（原 07-成片/assets）
BATCH_ID = 'local_assets_' + time.strftime('%Y%m%d_%H%M%S')

SUBDIR = {'char': 'characters', 'scene': 'scenes', 'prop': 'props'}
KIND_CN = {'char': '人物', 'scene': '场景', 'prop': '道具'}
EXTS = ('.png', '.jpg', '.jpeg', '.webp')
KIND_SHORT = {'character': 'char', 'scene': 'scene', 'prop': 'prop'}


def assets_from_pack(pack_dir: pathlib.Path) -> list:
    """制作包 → 出图清单（与 `asset_md.to_assets()` 同结构，便于复用同一条出图链）。

    关键在 `prefix`：它是**产物文件名的主干**，也是 `_scan_outputs` 回扫时的唯一依据。
    做成 `<ID>_<name>_<code>` 之后，`pack_import.py` 的 `_pick_image` 才能把
    `P01_何暖_LOOK-A.png` 反查回 `P01 / LOOK-A` —— 两边靠这条命名约定闭合。
    """
    import sys as _sys
    _imp = _PROJECT_ROOT / 'stages' / 'import'
    if str(_imp) not in _sys.path:
        _sys.path.insert(0, str(_imp))
    import pack_spec as S                                    # noqa: PLC0415

    pack, assets, _eps, rep = S.load_pack(pack_dir)
    if not rep.ok:
        print('[FAIL] 制作包校验不过，不进入出图：')
        print(rep.render())
        raise SystemExit(2)

    out = []
    for kind in S.ASSET_KINDS:
        bucket = assets.get(kind) or {}
        for aid, item in bucket.items():
            for v in item['variants']:
                code = v['code']
                # 层别：模板的资产卡是「三视图 / 造型 / 表情 / 状态」多层，
                # 出图顺序要先三视图（定一致性）再造型（换衣服），否则同一角色每套造型都像新人。
                vkind = str(v.get('kind') or S.guess_variant_kind(code, v.get('label') or ''))
                base = code.lower() in S.BASE_CODES
                prefix = '%s_%s' % (aid, item['name'])
                if not base:
                    prefix += '_%s' % code
                out.append({
                    'id': S.variant_key(aid, code),
                    'kind': KIND_SHORT[kind],
                    'name': item['name'],
                    'role': item.get('role') or '',
                    'section': int(''.join(ch for ch in aid if ch.isdigit()) or 0),
                    'variant': code,
                    'vkind': vkind,
                    'prefix': prefix,
                    'prompt': v['prompt'],
                    'aspect': v.get('aspect') or '',
                    'post_only': item.get('post_only', False),
                })
    vk_order = {'turnaround': 0, 'base': 1, 'look': 2, 'state': 3, 'expression': 4}
    out.sort(key=lambda a: (AM.KINDS.index(a['kind']), a['section'],
                            vk_order.get(a.get('vkind') or 'base', 9), a['id']))
    return out


def _size(p: pathlib.Path) -> tuple:
    """读图片像素尺寸；Pillow 不在或读不出来则返回 (0, 0)，不阻断流程。"""
    try:
        from PIL import Image
        with Image.open(p) as im:
            return im.size
    except Exception:                                            # noqa: BLE001
        return (0, 0)


def _scan_outputs(assets: list) -> list:
    """出图后扫描产物目录，按资产 id 归集实际落盘文件。"""
    items = []
    for a in assets:
        d = OUT_DIR / SUBDIR.get(a['kind'], '')
        files = []
        if d.is_dir():
            for f in sorted(d.iterdir()):
                if f.suffix.lower() in EXTS and (f.name.startswith(a['prefix'] + '_')
                                                 or f.stem == a['prefix']):
                    w, h = _size(f)
                    files.append({'file': str(f), 'role': 'asset',
                                  'width': w, 'height': h,
                                  'mb': round(f.stat().st_size / 1024 / 1024, 2)})
        items.append({
            'section': a['section'], 'name': a['name'], 'key': a['id'], 'kind': a['kind'],
            'variant': a.get('variant', ''), 'channel': 'comfyui-local',
            'prompt_sha256': hashlib.sha256(a['prompt'].encode('utf-8')).hexdigest()[:16],
            'files': files, 'usage': {}, 'billed': False,
            'created_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
            '_note': '本地 ComfyUI 出图产物（￥0）；files[0] 为资产图',
        })
    return items


def _item_key(it: dict) -> tuple:
    return (str(it.get('kind') or ''), str(it.get('key') or ''), str(it.get('variant') or ''))


def _write_prod_manifest(items: list, manifest: dict) -> None:
    """写产物清单：**按条目合并**，不是整份覆盖。

    ★ 2026-11-05 实测抓到：工具自己建议「先只出一张看风格」（`--only D01`），
      而这里原来是整份覆盖 —— 出完一张，清单里就只剩一张，项目状态从「24 张」掉成「1 项」，
      其余 23 个已存在的产物在台账里消失（文件还在，但记录没了）。
      清单是**累计事实**，不是本次运行日志；本次运行日志另有 `ledger/runs/`。
    """
    PROD_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    merged, order = {}, []
    old = {}
    if PROD_MANIFEST.is_file():
        try:
            old = json.loads(PROD_MANIFEST.read_text(encoding='utf-8-sig')) or {}
        except (OSError, json.JSONDecodeError):
            old = {}
    for it in (old.get('items') or []):
        if isinstance(it, dict) and it.get('key') is not None:
            k = _item_key(it)
            merged[k] = it
            order.append(k)
    for it in items:
        k = _item_key(it)
        if k not in merged:
            order.append(k)
        merged[k] = it                      # 本次结果覆盖同一条（可能重跑过）
    final = [merged[k] for k in order]
    ok = [it for it in final if it.get('files')]
    PROD_MANIFEST.write_text(json.dumps({
        '_note': '本地 ComfyUI 通道产物清单（本工具自动维护，**按条目累计**）；与云端 char_/scene_assets_manifest.json 并列',
        '_source': str(ASSET_MD or '(制作包)'),
        '_manifest': str(MANIFEST),
        'channel': 'comfyui-local',
        'produced_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'totals': {'items': len(final), 'produced': len(ok), 'cost_cny': 0.0},
        'items': final,
    }, ensure_ascii=False, indent=2), encoding='utf-8')


def _ensure_comfy(wait_s: int = 120) -> bool:
    """确保本机 ComfyUI 在线；没启动就按需拉一个后台实例（`--no-boot` 可关）。

    为什么放在这一层，而不是塞进 comfy_client.py：客户端要能在「别人已经起好服务」
    的环境里单独跑（云端地址、远程机器），不该擅自在本机拉进程。这里是「出图编排」，
    知道自己在做什么，也该为用户把「先开桌面版」这道手工步骤消掉。

    真源在 `stages/assets/comfyui/comfy_boot.py`：它只对 loopback 生效，已有实例一律复用。
    """
    url = (os.environ.get('COMFYUI_URL') or 'http://127.0.0.1:8188').strip()
    try:
        if str(COMFY_DIR) not in sys.path:
            sys.path.insert(0, str(COMFY_DIR))
        import comfy_boot as boot                       # noqa: PLC0415
    except Exception as e:                              # noqa: BLE001
        print('  [WARN] 读不到自动启动模块（%s），按「服务已就绪」继续' % type(e).__name__)
        return True
    print('  ComfyUI: %s' % url)
    r = boot.ensure(url, wait_s=wait_s, log=lambda m: print('  ' + m))
    print('  [%s] %s' % ('OK' if r.get('ok') else 'FAIL', r.get('detail') or r.get('reason') or ''))
    if not r.get('ok') and r.get('next'):
        print('  下一步：%s' % r['next'])
    return bool(r.get('ok'))


def cmd_check() -> int:
    print('【本地 ComfyUI 体检】%s' % COMFY_PY)
    if not _ensure_comfy():
        return 1
    rc = subprocess.call([sys.executable, str(COMFY_PY), '--check'])
    if rc == 0:
        print('  [OK] ComfyUI 在线，可以出图（命令：drama.py assets --engine local --submit）')
    else:
        print('  [FAIL] ComfyUI 未就绪。可先跑 --check 看启动日志，或设 COMFYUI_URL 指向已有服务。')
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(
        description='本地 ComfyUI 资产出图（￥0；默认 dry-run，需 --submit 才真跑）')
    ap.add_argument('--kind', default='char,scene,prop',
                    help='生成哪些类型：char,scene,prop（逗号分隔），默认全部')
    ap.add_argument('--only', default=None, help='只生成这些资产 id（逗号分隔），如 char_01,scene_02')
    ap.add_argument('--pack', default=None,
                    help='制作包目录（含 pack.json）；给了它就不用 SOLODRAMA_ASSET_MD')
    ap.add_argument('--variant', default='基础造型', help='人物取哪个变体（关键字），默认「基础造型」')
    ap.add_argument('--all-variants', action='store_true', help='每个变体各出一张')
    ap.add_argument('--aspect', default='', help='强制全部资产用这个画幅（覆盖各类型默认）')
    ap.add_argument('--aspect-char', default=None)
    ap.add_argument('--aspect-scene', default=None)
    ap.add_argument('--aspect-prop', default=None)
    ap.add_argument('--style-lock', default='', help='统一风格串，会拼进每条提示词')
    ap.add_argument('--submit', action='store_true', help='★ 真的调用 ComfyUI 出图（不花钱，但会占 GPU）')
    ap.add_argument('--force', action='store_true', help='已出图的重跑（默认跳过已有产物，断点续跑）')
    ap.add_argument('--check', action='store_true', help='只体检 ComfyUI 是否在线，然后退出')
    ap.add_argument('--no-boot', action='store_true',
                    help='不自动启动 ComfyUI（默认没启动就拉一个后台实例）')
    ap.add_argument('--skip-check', dest='skip_check', action='store_true',
                    help='真跑前跳过生成能力预检（★ 不建议：缺模型会让每张图各失败一次）')
    ap.add_argument('--comfy-url', dest='comfy_url', default='',
                    help='ComfyUI 地址（云端镜像如 https://<实例>-8188.container.x-gpu.com）；'
                         '不给 = 用确认单 / COMFYUI_URL')
    args = ap.parse_args()
    if args.no_boot:
        # 一个开关管三层：本脚本的 ensure()、以及它 spawn 出去的 comfy_client 子进程
        os.environ['SOLODRAMA_COMFY_AUTOSTART'] = '0'

    applied = _apply_model_plan_env()
    if applied:
        print('[i] 执行依据取自 model-plan.json：%s' % '；'.join('%s=%s' % (k, v) for k, v in applied.items()))
    if args.comfy_url:
        # 显式参数最高：它是「这一次就想打这里」，覆盖确认单是可解释的
        os.environ['COMFYUI_URL'] = args.comfy_url.strip().rstrip('/')
        print('[i] --comfy-url 覆盖为：%s' % os.environ['COMFYUI_URL'])

    if args.check:
        return cmd_check()

    kinds = tuple(k.strip() for k in args.kind.split(',') if k.strip())
    unknown = [k for k in kinds if k not in AM.KINDS]
    if unknown:
        print('[FAIL] 未知类型：%s（可选 %s）' % (', '.join(unknown), '/'.join(AM.KINDS)))
        return 2

    # ★ 2026-11-02：两条输入通道 —— 制作包（新）或资产提示词 md（老）。
    #   优先级：`--pack` > `SOLODRAMA_ASSET_MD`。都没给才是错误。
    aspects = dict(AM.ASPECT_DEFAULT)
    for k in AM.KINDS:
        v = getattr(args, 'aspect_%s' % k)
        if v:
            aspects[k] = v
    if args.aspect:
        aspects = {k: args.aspect for k in AM.KINDS}

    if args.pack:
        src = pathlib.Path(args.pack).expanduser().resolve()
        if not src.is_dir():
            print('[FAIL] --pack 指向的目录不存在：%s' % src)
            return 2
        assets = [a for a in assets_from_pack(src) if a['kind'] in kinds]
        # 制作包里的每个变体都是剧本要用的图，不做 --variant 筛选；
        # 画幅也以包内为准（`aspect` 只在包内没写时生效）。
        for a in assets:
            if not a.get('aspect') or args.aspect:
                a['aspect'] = aspects.get(a['kind']) or a.get('aspect') or ''
        source_label = str(src)
        source_path = src / 'pack.json'
        if not assets:
            print('[FAIL] 制作包里没有 kind ∈ %s 的资产' % '/'.join(kinds))
            return 1
    else:
        if not ASSET_MD:
            print('[FAIL] 没有资产来源：给 --pack "<制作包目录>"，'
                  '或设环境变量 SOLODRAMA_ASSET_MD 指向「资产提示词 md」。')
            return 2
        entries = AM.parse_md(ASSET_MD, kinds)
        if not entries:
            print('[FAIL] 在 %s 里没解析到任何资产节（章节标题需为「一、角色资产库」等，节内含 ``` 提示词块）。'
                  % ASSET_MD.name)
            return 2
        assets = AM.to_assets(entries, args.variant, args.all_variants, aspects)
        source_label = str(ASSET_MD)
        source_path = ASSET_MD

    if args.only:
        want = {x.strip() for x in args.only.split(',') if x.strip()}
        assets = [a for a in assets if a['id'] in want]
        missing = want - {a['id'] for a in assets}
        if missing:
            print('[FAIL] 找不到资产 id：%s' % ', '.join(sorted(missing)))
            return 2
    if not assets:
        print('[FAIL] 没有选中任何资产')
        return 1

    manifest = AM.build_manifest(source_path, assets, args.style_lock, args.aspect)
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')

    print('=' * 84)
    print('本地 ComfyUI 资产出图（￥0 成本）')
    print('=' * 84)
    print('提示词真源: %s' % source_label)
    print('清单      : %s' % MANIFEST)
    print('输出目录  : %s' % OUT_DIR)
    print('资产数    : %d（%s）'
          % (len(assets), '、'.join('%s %d' % (KIND_CN[k], sum(1 for a in assets if a['kind'] == k))
                                   for k in AM.KINDS if any(a['kind'] == k for a in assets))))
    print('成本      : ￥0（本机 GPU 出图，不产生任何平台费用）')
    print('-' * 84)
    for a in assets:
        print('  %-18s %-4s %-14s %-22s %-11s %s'
              % (a['id'], KIND_CN[a['kind']], a['name'], a['aspect'] or '—',
                 a.get('vkind') or 'base', a['prompt'][:22] + '…'))

    if not args.submit:
        print()
        print('★ DRY-RUN：未调用 ComfyUI，未占用 GPU。')
        print('  确认清单无误后加 --submit 出图：')
        print('    python stages/production/scripts/drama.py assets --engine local --submit')
        print('  建议先只出一张看风格：加 --only %s' % assets[0]['id'])
        return 0

    cmd = [sys.executable, str(COMFY_PY), '--spec', str(MANIFEST), '--out', str(OUT_DIR)]
    if not args.force:
        cmd.append('--skip-existing')
    print()
    # ★ 出图前先确保服务在线（没启动就拉一个后台实例）。不做这一步的后果：
    #   每张图都要等一次连接超时，最后报「N 项无产物」，而真实原因只是一行「没启动」。
    if not _ensure_comfy():
        print('[FAIL] ComfyUI 没起来，本次不提交（避免每张图都空跑一次超时）')
        return 2
    # ★ 2026-11-05：在线 ≠ 能出图。缺一个节点类或一个模型，每张图都会各失败一次，
    #   而报错只有一句 node type missing。预检只有一份判据（cloud/health），这里只调用。
    if not args.skip_check:
        try:
            import gen_preflight as GP          # 同目录
            pre = GP.check('image', 'local', WS, timeout=30)
            print(GP.render(pre, indent='  '))
            if not pre['ok']:
                print('[FAIL] 生成能力预检未通过，本次不提交（加 --skip-check 可强制尝试）')
                return 2
        except Exception as exc:                # noqa: BLE001 —— 预检自身故障不该拦住出图
            print('  [WARN] 预检没跑起来（%s: %s），继续提交' % (type(exc).__name__, exc))
    print('  $ %s' % ' '.join(cmd[1:]))
    t0 = time.time()
    rc = subprocess.call(cmd)
    wall = round(time.time() - t0, 1)

    items = _scan_outputs(assets)
    _write_prod_manifest(items, manifest)
    produced = [it for it in items if it['files']]

    ledger = RunLedger(VP, enabled=True)
    for it in items:
        got = bool(it['files'])
        nbytes = sum(pathlib.Path(f['file']).stat().st_size for f in it['files']) or None
        ledger.record(batch_id=BATCH_ID, shot_id=it['key'], stage='image',
                      status='SUCCESS' if got else 'FAILED',
                      route='local', kind='comfyui', target_id='comfyui',
                      usage={}, wall_elapsed_s=None if got else wall,
                      out_bytes=nbytes,
                      artifact=';'.join(f['file'] for f in it['files']) or None,
                      error=None if got else 'no output produced',
                      extra={'channel': 'comfyui-local', 'name': it['name'],
                             'variant': it.get('variant', ''), 'billed': False,
                             'prompt_sha256': it['prompt_sha256']})

    print()
    print('=' * 84)
    print('完成：出图 %d / 共 %d（墙钟 %.1fs，费用 ￥0）' % (len(produced), len(items), wall))
    print('产物清单：%s' % PROD_MANIFEST)
    print('台账    ：%s' % (VP / 'ledger' / 'runs'))
    if len(produced) < len(items):
        print('★ 有 %d 项无产物（ComfyUI 未启动 / 节点报错 / 显存不足）。'
              '修好后重跑同一条命令即可断点续跑。' % (len(items) - len(produced)))
    return 0 if rc == 0 else rc


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('\n已中断。重跑同一命令即可断点续跑（默认跳过已有产物）。')
        sys.exit(130)
