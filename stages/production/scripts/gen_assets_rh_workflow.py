#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""gen_assets_rh_workflow.py —— 用 RunningHub【工作流】通道生成资产图（人物设定卡 / 场景空镜）

为什么需要这个脚本
------------------
`drama.py assets --engine rh` 走的是另外两条通道：
  * 人物 -> `gen_char_assets.py`  （RunningHub **AI 应用**，需要 RH_CHAR_APP_ID）
  * 场景 -> `gen_scene_assets.py` （RunningHub **模型 API**，需要企业级 Key）
两条都吃不到「自建 ComfyUI 工作流」。而本项目用户明确要求：**生图必须用附件里的
「Qwen image2.1 角色设定卡」工作流**。工作流通道的提交契约是
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

_ENV_WANT = ('RUNNINGHUB_API_KEY', 'RUNNINGHUB_API_KEY_2', 'RUNNINGHUB_ENT_API_KEY',
             'RUNNINGHUB_BASE_URL', 'SOLODRAMA_WORKSPACE', 'DRAMA_WORKSPACE')


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

from _ws import WS, DATA, OUT as OUT_ROOT                            # noqa: E402

VP = WS / 'video-pipeline'
os.environ['VIDEO_PIPELINE_WORKSPACE'] = str(VP)

import config as C                                                   # noqa: E402
# ★ 配置分层：本脚本不经引擎 main.py，覆盖层要自己套（否则 image_providers 的
#   id / nodes 全是引擎默认空值，表现为「ID 未填」——这是实测踩到的坑）。
C.apply_overlay(VP / C.OVERLAY_FILENAME)

from runninghub_client import RunningHubClient, RunningHubError      # noqa: E402
from run_ledger import RunLedger                                     # noqa: E402
OUT_DIRS = {'char': OUT_ROOT / 'assets' / 'characters',
            'scene': OUT_ROOT / 'assets' / 'scenes',
            'prop': OUT_ROOT / 'assets' / 'props'}
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
def provider_or_die():
    name = C.ACTIVE_IMAGE_PROVIDER
    prov = (C.IMAGE_PROVIDERS or {}).get(name) or {}
    if not prov:
        raise SystemExit('[FAIL] config.local.json 里没有 image_providers["%s"]' % name)
    if not str(prov.get('id') or '').strip():
        raise SystemExit('[FAIL] 生图工作流 ID 未填：config.local.json 的 '
                         'image_providers["%s"].id（kind=%s）\n'
                         '       本项目的「Qwen image2.1 角色设定卡」工作流 ID 需先在该工作流页面'
                         '运行一次，平台才会生成 API 快照。' % (name, prov.get('kind', 'workflow')))
    if not (prov.get('nodes') or {}).get('prompt', {}).get('nodeId'):
        raise SystemExit('[FAIL] image_providers["%s"].nodes.prompt.nodeId 未配' % name)
    return name, prov


def build_nodes(prov: dict, prompt: str, ratio: str) -> list:
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
    return RunningHubClient.build_node_list(pairs)


def base_url() -> str:
    env = os.getenv('RUNNINGHUB_BASE_URL')
    if env:
        return env.rstrip('/')
    try:
        local = json.loads((VP / 'config.local.json').read_text(encoding='utf-8'))
        if local.get('runninghub_base_url'):
            return str(local['runninghub_base_url']).rstrip('/')
    except (OSError, json.JSONDecodeError):
        pass
    return C.RH_BASE_URL.rstrip('/')


async def generate(sel: list, ratio: str, submit: bool, timeout_min: float,
                   resume_task: str | None, force: bool) -> int:
    pname, prov = provider_or_die()
    kind0 = (prov.get('kind') or 'workflow').lower()
    ledger = RunLedger(VP, cny_per_rh_coin=C.RH_CNY_PER_COIN)

    print('站点        : %s' % base_url())
    print('生图通道    : image_providers["%s"]  kind=%s  id=%s' % (pname, kind0, prov.get('id')))
    print('画幅        : %s' % ratio)
    print()

    rc = 0
    ok = fail = skip = 0
    async with RunningHubClient(C.RUNNINGHUB_API_KEY, base_url(), C.HTTP_TIMEOUT) as client:
        for it in sel:
            kind, key, no, name = it['kind'], it['key'], it['section'], it['name']
            var = it['variants'][0] if it['variants'] else None
            if not var:
                print('[SKIP] %s %s：md 里没有提示词代码块' % (key, name))
                continue
            prompt = var['prompt']
            out_dir = OUT_DIRS[kind]
            out_dir.mkdir(parents=True, exist_ok=True)
            out = out_dir / ('%s_%s.png' % (key, sanitize(name)))

            man = load_manifest(kind)
            done = None
            for old in man.get('items', []):
                if old.get('key') == key:
                    fs = [f.get('file') if isinstance(f, dict) else f for f in (old.get('files') or [])]
                    if any(f and pathlib.Path(f).is_file() for f in fs):
                        done = fs[0]
                    break

            print('=' * 84)
            print('%s  %s   （第 %d 节 · %s）' % (key, name, no, it['title']))
            print('  提示词长度: %d 字' % len(prompt))
            print('  提示词摘要: %s…' % prompt[:70].replace('\n', ' '))
            print('  目标文件  : %s' % out)
            if done and not force and not resume_task:
                print('[SKIP] 已生成过（%s）。要重跑请加 --force。' % pathlib.Path(done).name)
                skip += 1
                continue

            node_list = build_nodes(prov, prompt, ratio)
            snap = WS / 'docs' / ('asset-wf-nodeinfo-%s.json' % key)
            snap.parent.mkdir(parents=True, exist_ok=True)
            snap.write_text(json.dumps({
                'provider': pname, 'kind': kind0, 'id': prov.get('id'), 'key': key,
                'section': no, 'name': name, 'nodeInfoList': node_list,
            }, ensure_ascii=False, indent=2), encoding='utf-8')

            if not submit and not resume_task:
                print('  ★ DRY-RUN：未提交，未计费。加 --submit 才真的生成。')
                continue

            t0 = time.time()
            task_id = resume_task
            if not task_id:
                try:
                    task_id = await client.create_task(kind0, prov.get('id'), node_list,
                                                       prov.get('instance_type'))
                except RunningHubError as e:
                    print('  [FAIL] 提交失败: %s' % e.short)
                    ledger.record(batch_id=BATCH_ID, shot_id=key, stage='image', status='FAILED',
                                  route='workflow', kind=kind0, target_id=prov.get('id'),
                                  error=str(e.short))
                    fail += 1
                    rc = rc or 1
                    continue
                print('  taskId = %s' % task_id)
                ledger.record(batch_id=BATCH_ID, shot_id=key, stage='image', status='RUNNING',
                              route='workflow', kind=kind0, target_id=prov.get('id'),
                              task_id=task_id, extra={'name': name, 'prompt_sha256':
                                                      hashlib.sha256(prompt.encode()).hexdigest()[:16]})

            try:
                res = await client.poll_until_done(task_id, timeout_min=timeout_min,
                                                   interval=C.POLL_INTERVAL)
            except RunningHubError as e:
                print('  [超时/异常] %s' % e.short)
                print('  只轮询不重扣：--resume-task %s' % task_id)
                fail += 1
                rc = rc or 2
                continue

            status = res.get('status')
            usage = res.get('usage') or {}
            urls = [r.get('url') for r in (res.get('results') or []) if r.get('url')]
            if status not in TERMINAL_OK or not urls:
                print('  [FAILED] status=%s %s' % (status, json.dumps(res.get('raw') or {},
                                                                     ensure_ascii=False)[:400]))
                ledger.record(batch_id=BATCH_ID, shot_id=key, stage='image', status='FAILED',
                              route='workflow', kind=kind0, target_id=prov.get('id'),
                              task_id=task_id, usage=usage,
                              wall_elapsed_s=round(time.time() - t0, 1),
                              error=json.dumps(res.get('raw') or {}, ensure_ascii=False)[:200])
                fail += 1
                rc = rc or 1
                continue

            saved = []
            for i, url in enumerate(urls):
                sfx = pathlib.Path(url.split('?')[0]).suffix.lower()
                if sfx not in ('.png', '.jpg', '.jpeg', '.webp'):
                    sfx = '.png'
                tmp = out.with_name('%s__r%d%s' % (out.stem, i + 1, sfx))
                try:
                    await client.download(url, str(tmp))
                    saved.append(tmp)
                except RunningHubError as e:
                    print('  [WARN] 下载失败: %s' % e.short)
            if not saved:
                print('  [FAILED] 任务成功但一张图都没落盘')
                fail += 1
                rc = rc or 1
                continue

            saved.sort(key=lambda p: _size(p)[0] * _size(p)[1], reverse=True)
            finals = []
            for k, p in enumerate(saved):
                dest = out if k == 0 else out.with_name('%s_r%d%s' % (out.stem, k + 1, p.suffix))
                if p != dest:
                    if dest.exists():
                        dest.unlink()
                    p.replace(dest)
                w, h = _size(dest)
                finals.append({'file': str(dest), 'role': 'asset' if k == 0 else 'extra',
                               'width': w, 'height': h,
                               'mb': round(dest.stat().st_size / 1024 / 1024, 2)})
                print('      已保存: %s  (%sx%s)' % (dest, w, h))

            wall = round(time.time() - t0, 1)
            print('  [SUCCESS] 墙钟 %.1fs | usage=%s' % (wall, json.dumps(usage, ensure_ascii=False)))
            man = load_manifest(kind)
            upsert(man, {'kind': kind, 'key': key, 'section': no, 'name': name,
                         'title': it['title'], 'ratio': ratio, 'files': finals,
                         'task_id': task_id, 'usage': usage,
                         'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest()[:16],
                         'created_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
                         '_note': 'files[0].role=asset 为资产图；其余为同次调用的附带产物'})
            save_manifest(kind, man)
            ledger.record(batch_id=BATCH_ID, shot_id=key, stage='image', status='SUCCESS',
                          route='workflow', kind=kind0, target_id=prov.get('id'),
                          task_id=task_id, usage=usage, wall_elapsed_s=wall,
                          out_bytes=sum(pathlib.Path(f['file']).stat().st_size for f in finals) or None,
                          artifact=';'.join(f['file'] for f in finals) or None,
                          output_url=urls[0], extra={'name': name, 'ratio': ratio})
            ok += 1

    print()
    print('本轮完成：成功 %d / 失败 %d / 跳过 %d（共选中 %d 个资产）' % (ok, fail, skip, len(sel)))
    if ok and submit:
        print('下一步：python stages/production/scripts/wire_new_assets.py --apply   # 瘦身 + 接进 characters.json')
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(description='RunningHub 工作流通道生成资产图（默认 dry-run）')
    ap.add_argument('--workspace', default=None, help='短剧工作区（默认取环境变量/位置推断）')
    ap.add_argument('--md', action='append', default=[], help='资产提示词 md（可多次；如角色一份、场景一份）')
    ap.add_argument('--default-kind', choices=('char', 'scene', 'prop'), default=None,
                    help='md 里没有「# 一、角色资产库」这类章节标题时的兜底分类')
    ap.add_argument('--only', default=None, help='只做这些（key / 名字 / 节号，逗号分隔）')
    ap.add_argument('--ratio', default='16:9', help='画幅裸值，默认 16:9（会按 config 的 value_map 映射）')
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
                                args.resume_task, args.force))


if __name__ == '__main__':
    sys.exit(main())
