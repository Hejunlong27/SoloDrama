#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""gen_assets_rh_workflow.py —— 用 RunningHub【工作流】通道生成资产图（人物设定卡 / 场景空镜）

为什么需要这个脚本
------------------
`drama.py assets --engine wf` 走的就是本脚本（`local` 走本地 ComfyUI）。
它吃的是「自建 ComfyUI 工作流」，而不是平台上的 AI 应用 —— 本项目用户明确要求：
**生图必须用附件里的「Qwen image2.1 角色设定卡」工作流**。工作流通道的提交契约是
`POST /task/openapi/create` + `nodeInfoList`，节点映射取
`<工作区>/video-pipeline/config.local.json` 的 `image_providers[<active>]`
（本项目只映射 prompt + ratio 两个节点 —— 该工作流是纯文生图，无参考图输入）。

产物口径与既有云端通道**完全一致**（这样 `wire_new_assets.py` 能直接接上）：
  * 图落到 `output/assets/characters/<key>_<名字>.png`、`output/assets/scenes/...`
  * 清单写到 `data/char_assets_manifest.json` / `data/scene_assets_manifest.json`
    （`items[].key` + `items[].files[]`，`files[0].role = "asset"`）

计费纪律
--------
默认 **dry-run**，只打印将提交的内容；**必须显式 --submit 才真的提交（会计费）**。
中断后用 `--resume-task <taskId>` 只轮询、不重复提交（不重复扣费）。
已生成且产物仍在 -> 默认跳过；重跑用 `--force`（会重复计费）。

用法
----
python gen_assets_rh_workflow.py --workspace <工作区> --md <资产提示词.md> [--md <另一个.md>] --list
python gen_assets_rh_workflow.py --workspace <工作区> --md ... --md ...             # 干跑
python gen_assets_rh_workflow.py --workspace <工作区> --md ... --md ... --submit    # ★计费
"""
from __future__ import annotations

import os as _os_guard
# ★ 平台通道专用脚本：运行本文件 = 显式选择 RunningHub。这里自己开闸，
#   否则出口守卫会把「用户主动跑 RH」也拦掉（见 stages/_netguard.py::allow_platform）。
_os_guard.environ.setdefault("SOLODRAMA_ALLOW_RH", "1")


import argparse
import asyncio
import hashlib
import json
import os
import pathlib
import re
import sys
import time

# ---------------------------------------------------------------------------
# 0) 先补环境：config.py 在 import 期就读 Key / 工作区，顺序不能动
# ---------------------------------------------------------------------------
os.environ.setdefault('PYTHONUTF8', '1')
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')

# 站点不在这张表里：它已不是环境变量（真源 configs/channels.json），
# 补进去只会把死值重新灌进子进程。
_ENV_WANT = ('RUNNINGHUB_API_KEY', 'RUNNINGHUB_API_KEY_2', 'RUNNINGHUB_ENT_API_KEY',
             'SOLODRAMA_WORKSPACE', 'DRAMA_WORKSPACE')


def _hydrate_env() -> None:
    """进程环境里缺的，从「用户级环境变量」补（agent 的 shell 常拿不到）。"""
    if os.name != 'nt':
        return
    missing = [n for n in _ENV_WANT if not os.environ.get(n)]
    if not missing:
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
    except Exception:                                            # noqa: BLE001
        pass


def _prescan_workspace() -> None:
    """在 import 期把 --workspace 下沉到环境变量，让 _ws / config 都能看见。"""
    argv = sys.argv
    for i, a in enumerate(argv):
        if a == '--workspace' and i + 1 < len(argv):
            os.environ['SOLODRAMA_WORKSPACE'] = argv[i + 1]
            os.environ['DRAMA_WORKSPACE'] = argv[i + 1]
        elif a.startswith('--workspace='):
            os.environ['SOLODRAMA_WORKSPACE'] = a.split('=', 1)[1]
            os.environ['DRAMA_WORKSPACE'] = a.split('=', 1)[1]


_hydrate_env()
_prescan_workspace()

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[3]
ENGINE = pathlib.Path(os.environ.get('AI_VIDEO_PIPELINE_SKILL')
                      or _PROJECT_ROOT / 'stages' / 'video' / 'workflow') / 'scripts' / 'engine'
sys.path.insert(0, str(ENGINE))
sys.path.append(str(pathlib.Path(__file__).resolve().parent))

from _ws import WS, DATA, ASSETS as ASSETS_ROOT                      # noqa: E402

VP = WS / 'video-pipeline'
os.environ['VIDEO_PIPELINE_WORKSPACE'] = str(VP)

import config as C                                                   # noqa: E402
# ★ 配置分层：本脚本不经引擎 main.py，覆盖层要自己套（否则 image_providers 的
#   id / nodes 全是引擎默认空值，表现为「ID 未填」——这是实测踩到的坑）。
C.apply_overlay(VP / C.OVERLAY_FILENAME)

from runninghub_client import RunningHubClient, RunningHubError      # noqa: E402
from run_ledger import RunLedger                                     # noqa: E402
# ★ 2026-10-19：资产落 04-资产/{characters,scenes,props}（原 07-成片/assets，用户找不到）
OUT_DIRS = {'char': ASSETS_ROOT / 'characters',
            'scene': ASSETS_ROOT / 'scenes',
            'prop': ASSETS_ROOT / 'props'}
MANIFESTS = {'char': DATA / 'char_assets_manifest.json',
             'scene': DATA / 'scene_assets_manifest.json',
             'prop': DATA / 'prop_assets_manifest.json'}
KIND_CN = {'char': '角色资产库', 'scene': '场景资产', 'prop': '道具资产'}
BATCH_ID = 'assets_wf_' + time.strftime('%Y%m%d_%H%M%S')

SEC_RE = re.compile(r'^##\s+(\d+)\.\s*(.+?)\s*$', re.M)
H1_RE = re.compile(r'^#\s+(.+?)\s*$', re.M)
FENCE_RE = re.compile(r'```(.*?)```', re.S)
BOLD_RE = re.compile(r'\*\*(.+?)\*\*')

TERMINAL_OK = {'SUCCESS'}
TERMINAL_BAD = {'FAILED', 'FAIL', 'CANCEL', 'CANCELLED', 'ERROR'}


def sanitize(name: str) -> str:
    s = re.sub(r'[/\\:*?"<>|]', '_', name).strip()
    return re.sub(r'_+', '_', s).strip('_') or 'unnamed'


# ---------------------------------------------------------------------------
# 解析资产提示词 md
# ---------------------------------------------------------------------------
def kind_of_header(head: str) -> str | None:
    for kind, cn in KIND_CN.items():
        if cn in head:
            return kind
    return None


def parse_md(path: pathlib.Path, default_kind: str | None) -> list:
    """解析一份资产提示词 md：`# 二、场景资产` 切 kind，`## N. 名字` + ``` 块 = 一条提示词。"""
    text = path.read_text(encoding='utf-8')
    marks = [(m.start(), m.end(), kind_of_header(m.group(1))) for m in H1_RE.finditer(text)]
    marks = [(s, e, k) for (s, e, k) in marks if k]
    items: list = []
    if not marks:
        if not default_kind:
            raise SystemExit('[FAIL] %s 里找不到「# 一、角色资产库 / # 二、场景资产」这类章节标题；'
                             '用 --default-kind char|scene 指定' % path.name)
        blocks = [(0, len(text), default_kind)]
    else:
        blocks = []
        for i, (s, e, k) in enumerate(marks):
            nxt = marks[i + 1][0] if i + 1 < len(marks) else len(text)
            blocks.append((e, nxt, k))
    for start, end, kind in blocks:
        body = text[start:end]
        ms = list(SEC_RE.finditer(body))
        for i, m in enumerate(ms):
            no = int(m.group(1))
            title = m.group(2)
            seg = body[m.end(): ms[i + 1].start() if i + 1 < len(ms) else len(body)]
            variants = []
            cursor = 0
            for fm in FENCE_RE.finditer(seg):
                head = seg[cursor:fm.start()]
                cursor = fm.end()
                label = (BOLD_RE.findall(head) or ['基础造型'])[-1].strip()
                variants.append({'label': label, 'prompt': fm.group(1).strip()})
            name = re.split(r'[（(]', title)[0].strip()
            items.append({'kind': kind, 'section': no, 'title': title,
                          'name': name, 'key': '%s_%02d' % (kind, no),
                          'source': str(path), 'variants': variants})
    return items


def load_manifest(kind: str) -> dict:
    p = MANIFESTS[kind]
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            pass
    return {'_note': '资产图产物清单（gen_assets_rh_workflow.py 自动维护）', 'items': []}


def save_manifest(kind: str, man: dict) -> None:
    p = MANIFESTS[kind]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding='utf-8')


def upsert(man: dict, rec: dict) -> None:
    items = man.setdefault('items', [])
    for i, it in enumerate(items):
        if it.get('key') == rec.get('key'):
            items[i] = {**it, **rec}
            break
    else:
        items.append(rec)
    items.sort(key=lambda x: (x.get('kind') or '', x.get('section') or 0))


def _size(p: pathlib.Path) -> tuple:
    try:
        from PIL import Image
        with Image.open(p) as im:
            return im.size
    except Exception:                                            # noqa: BLE001
        return (0, 0)


# ---------------------------------------------------------------------------
# 提交
# ---------------------------------------------------------------------------
def workflow_id_for(prov: dict, mode: str) -> str:
    """按模式取工作流 ID。

    ★ 文生图与图生图是**两个不同的工作流**（图生图多一个 LoadImage 输入节点），
      绝不能用同一个 id 硬套：拿 t2i 工作流去传参考图，平台要么忽略参考图
      （出来还是纯文生图，白花钱），要么直接报节点不存在。
      配置口径：`id` = 文生图；`id_i2i` = 图生图（也兼容 `i2i.id`）。
    """
    if mode == 'i2i':
        return str(prov.get('id_i2i') or (prov.get('i2i') or {}).get('id') or '').strip()
    return str(prov.get('id') or '').strip()


def provider_or_die(mode: str = 't2i'):
    name = C.resolve_image_provider()
    prov = (C.IMAGE_PROVIDERS or {}).get(name) or {}
    if not prov:
        raise SystemExit('[FAIL] config.local.json 里没有 image_providers["%s"]' % name)
    wid = workflow_id_for(prov, mode)
    if not wid:
        key = 'id_i2i' if mode == 'i2i' else 'id'
        raise SystemExit('[FAIL] %s 工作流 ID 未填：config.local.json 的 '
                         'image_providers["%s"].%s（kind=%s）\n'
                         '       工作流 ID 需先在该工作流页面运行一次，平台才会生成 API 快照。'
                         % ('图生图' if mode == 'i2i' else '文生图', name, key,
                            prov.get('kind', 'workflow')))
    if not (prov.get('nodes') or {}).get('prompt', {}).get('nodeId'):
        raise SystemExit('[FAIL] image_providers["%s"].nodes.prompt.nodeId 未配' % name)
    if mode == 'i2i' and not (prov.get('nodes') or {}).get('image', {}).get('nodeId'):
        raise SystemExit('[FAIL] 图生图缺参考图节点：image_providers["%s"].nodes.image.nodeId 未配\n'
                         '       图生图工作流里必须有一个「加载图像」节点，把上传得到的文件名喂给它。'
                         % name)
    return name, prov


def build_nodes(prov: dict, prompt: str, ratio: str, mode: str = 't2i',
                image_name: str = '') -> list:
    nodes = prov.get('nodes') or {}
    pairs = []
    n = nodes.get('prompt')
    if n and n.get('nodeId'):
        pairs.append((n['nodeId'], n.get('fieldName') or 'value', prompt))
    n = nodes.get('ratio')
    if n and n.get('nodeId') and ratio:
        vm = n.get('value_map')
        val = vm.get(ratio, ratio) if isinstance(vm, dict) else ratio
        pairs.append((n['nodeId'], n.get('fieldName') or 'aspect_ratio', val))
    # 图生图：把平台上传后拿到的文件名喂给「加载图像」节点
    n = nodes.get('image')
    if mode == 'i2i' and n and n.get('nodeId') and image_name:
        pairs.append((n['nodeId'], n.get('fieldName') or 'image', image_name))
    return RunningHubClient.build_node_list(pairs)


def base_url() -> str:
    """站点：项目覆盖层 > 仓库真源（`configs/channels.json`）。

    ★ 2026-11-01：删掉「先读 RUNNINGHUB_BASE_URL」这条分支。它是死变量，
      但原本排在最前 —— 于是「用户改了用户级变量没重开终端」会让这里静默用旧站，
      而报错长得像 Key 不对。实现统一在 `_site.project_site()`。
    """
    from _site import project_site
    return project_site(VP)


def main() -> int:
    ap = argparse.ArgumentParser(description='RunningHub 工作流通道生成资产图（默认 dry-run）')
    ap.add_argument('--workspace', default=None, help='短剧工作区（默认取环境变量/位置推断）')
    ap.add_argument('--md', action='append', default=[], help='资产提示词 md（可多次；如角色一份、场景一份）')
    ap.add_argument('--default-kind', choices=('char', 'scene', 'prop'), default=None,
                    help='md 里没有「# 一、角色资产库」这类章节标题时的兜底分类')
    ap.add_argument('--only', default=None, help='只做这些（key / 名字 / 节号，逗号分隔）')
    ap.add_argument('--ratio', default='16:9', help='画幅裸值，默认 16:9（会按 config 的 value_map 映射）')
    ap.add_argument('--mode', choices=('t2i', 'i2i'), default='t2i',
                    help='t2i=文生图（纯提示词）｜i2i=图生图（必须先 --ref 给参考图，走另一套工作流）')
    ap.add_argument('--ref', action='append', default=[],
                    help='参考图路径（i2i 必填；多次给则取第一张上传）')
    ap.add_argument('--list', action='store_true', help='只列出解析到的资产与缺口，不提交')
    ap.add_argument('--force', action='store_true', help='已生成过的也重跑（会重复计费）')
    ap.add_argument('--submit', action='store_true', help='★ 真的提交（每张计费一次）')
    ap.add_argument('--resume-task', default=None, help='只轮询这个 taskId（不重复提交，不重复扣费）')
    ap.add_argument('--timeout-min', type=float, default=15.0, help='单张轮询超时（分钟），默认 15')
    args = ap.parse_args()

    if not args.md:
        raise SystemExit('[FAIL] 至少要给一份 --md（资产提示词 md）')
    items: list = []
    for m in args.md:
        p = pathlib.Path(m)
        if not p.is_file():
            raise SystemExit('[FAIL] 资产提示词 md 不存在: %s' % p)
        items.extend(parse_md(p, args.default_kind))
    if not items:
        raise SystemExit('[FAIL] 没解析到任何资产（检查 md 的 `## N. 名字` 与 ``` 提示词块）')

    if args.only:
        want = {x.strip() for x in args.only.split(',') if x.strip()}
        keep = [it for it in items if it['key'] in want or it['name'] in want
                or str(it['section']) in want]
        missing = want - {it['key'] for it in keep} - {it['name'] for it in keep} - \
            {str(it['section']) for it in keep}
        if missing:
            raise SystemExit('[FAIL] 找不到资产: %s' % ', '.join(sorted(missing)))
        items = keep

    if args.list:
        try:
            _n, _p = provider_or_die(args.mode)
            print('模式: %s ｜ 工作流 ID: %s' % (args.mode, workflow_id_for(_p, args.mode)))
        except SystemExit as _e:
            print('[WARN] %s' % _e)
        print('%-10s %-6s %-30s %-8s %s' % ('key', 'kind', '名字', '提示词', '已生成'))
        print('-' * 88)
        for it in items:
            man = load_manifest(it['kind'])
            gen = any(o.get('key') == it['key'] and (o.get('files') or [])
                      for o in man.get('items', []))
            print('%-10s %-6s %-30s %-8s %s' % (it['key'], it['kind'], it['name'],
                                                '%d 条' % len(it['variants']),
                                                '是' if gen else '—'))
        print()
        print('合计 %d 个资产；清单目录：%s' % (len(items), DATA))
        return 0

    if not C.RUNNINGHUB_API_KEY:
        print('[FAIL] 未设置 RUNNINGHUB_API_KEY（start/agent shell 拿不到用户级变量时，'
              '请通过 drama.py 调用或先 setx）')
        return 2
    return asyncio.run(generate(items, args.ratio, args.submit, args.timeout_min,
                                args.resume_task, args.force, args.mode, args.ref))


if __name__ == '__main__':
    sys.exit(main())
