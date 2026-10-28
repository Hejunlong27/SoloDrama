/* 资产中心：缺口（引擎判定）+ 参考图超限 + 资产图片预览（工作区白名单）+ 真实出图
   出图走引擎既有的两条通道：
     本地 ComfyUI  ￥0，占 GPU（需 8188 在线）      → assets.local  --submit
     云端 RunningHub ★计费（人物约 27 点/张）        → assets.rh     --submit
   前置：引擎的 gen_assets_local.py **只认环境变量 SOLODRAMA_ASSET_MD**，
   所以这里必须先选「资产提示词 md」，由后端注入（浏览器永远不拼命令）。 */
import { api, mediaUrl } from '../api.js';
import { esc, icon, badge, stamp, toast, openDrawer, closeDrawer, openModal, closeModal, paintIcons } from '../ui.js';
import { runAction, doRun } from '../action.js';

const TABS = [
  { key: 'characters', label: '角色', dir: '04-资产/characters' },
  { key: 'scenes', label: '场景', dir: '04-资产/scenes' },
  { key: 'props', label: '道具', dir: '04-资产/props' },
  { key: 'refs', label: '参考图', dir: '06-提示词/refs_h3' },
  /* 散图：真实项目的图常在根目录，只看 04-资产/ 会显示「空」。
     这里只读扫描（不移动文件），给用户一个「我的图都在这」的落点。 */
  { key: 'loose', label: '散图', dir: '', loose: true }
];

/* 页签放在 URL 里（#/assets?tab=loose）：刷新、后退、分享链接都不丢当前页签。
   与 AI 模型中心保持同一套写法，避免「这页记得住、那页记不住」。 */
function currentTab() {
  const m = String(location.hash || '').match(/[?&]tab=([a-z]+)/);
  const k = m ? m[1] : 'characters';
  return TABS.some((t) => t.key === k) ? k : 'characters';
}

export async function render(ctx) {
  const tab = currentTab();
  /* 散图清单**总是取**（不只是切到散图页签时）：
     KPI 上要能写「另有 N 张未归档」，否则用户看到「角色资产 0」会以为图丢了。 */
  const [ov, dirData, md, looseAll] = await Promise.all([
    api.overview(ctx.ws).catch((e) => ({ ok: false, error: e.detail || e.message })),
    (TABS.find((t) => t.key === tab) || TABS[0]).loose
      ? Promise.resolve({ items: [], groups: [] })
      : api.artifacts(ctx.ws, (TABS.find((t) => t.key === tab) || TABS[0]).dir)
        .catch((e) => ({ ok: false, error: e.detail || e.message, items: [] })),
    api.assetMd(ctx.ws).catch(() => ({ items: [], suggested: '', note: '' })),
    api.loose(ctx.ws).catch(() => ({ items: [], groups: [] }))
  ]);

  const a = (ov && ov.assets) || {};
  const refsOver = (ov && ov.refs_over) || [];
  const dirDataFinal = tab === 'loose' ? looseAll : dirData;
  const looseN = (looseAll.items || []).length;
  const items = (dirDataFinal.items || []).filter((it) => !it.dir && it.kind === 'image');

  const tiles = items.map((it) => (
    '<div class="mtile" data-img="' + esc(it.rel) + '" data-name="' + esc(it.name) + '" style="cursor:pointer">'
    + '<img class="frame" loading="lazy" alt="" src="' + esc(it.url || mediaUrl(ctx.ws, it.rel)) + '">'
    + '<div class="mtile-cap"><span class="mono">' + esc(it.name) + '</span></div></div>'
  )).join('') || '<div class="placeholder" style="grid-column:1/-1">'
    + '<div class="ph-icon">' + icon('image', 22) + '</div>'
    + (tab === 'loose'
      ? '标准目录之外没有散图（根目录与一层子目录都看过了）'
      : ('这个目录里还没有图片（或目录不存在：<span class="mono">'
        + esc((TABS.find((t) => t.key === tab) || {}).dir) + '</span>）'))
    + '<div class="tiny dim" style="margin-top:8px">'
    + (tab === 'loose'
      ? '把图移到 <span class="mono">04-资产/characters|scenes|props</span> 就会出现在对应分页里。'
      : '用右上角「出图…」生成（本地￥0 / 云端计费）。')
    + '</div></div>';

  const missChars = (a.missing_characters || []).slice(0, 24);
  const missScenes = (a.missing_scenes || []).slice(0, 24);
  const mdOk = !!(md && md.suggested);

  const html = ''
    + '<div class="page-head"><div>'
    + '<div class="crumb"><b>项目管理</b><span class="sep">/</span><b>'
    + esc(ctx.project ? (ctx.project.title || ctx.project.path) : ctx.ws) + '</b></div>'
    + '<h1 class="page-title">资产中心</h1>'
    + '<div class="page-sub">缺口由引擎按资产卡节号判定；图片直接读工作区（不复制、不转码）</div></div>'
    + '<div class="page-actions">'
    + '<button class="btn quiet" id="btnAssetCheck">' + icon('cpu', 14) + ' 出图器体检</button>'
    + '<button class="btn quiet" id="btnRefsCheck">' + icon('alert', 14) + ' 参考图体检</button>'
    + '<button class="btn primary" id="btnGen">' + icon('spark', 14) + ' 出图…</button>'
    + '</div></div>'

    + (refsOver.length ? '<div class="alert warn" style="margin-bottom:14px"><span class="nav-ico">'
      + icon('alert', 14) + '</span><div><b>' + refsOver.length + ' 张参考图长边超过 5760px</b>'
      + '（平台会丢弃并导致画面错位）。瘦身会写盘，需在确认后执行：'
      + '<span class="mono">refs.apply</span></div></div>' : '')

    + (!mdOk ? '<div class="alert warn" style="margin-bottom:14px"><span class="nav-ico">'
      + icon('alert', 14) + '</span><div><b>没找到「资产提示词 md」</b>，出图会被引擎拒绝'
      + '（它会报「未设置 SOLODRAMA_ASSET_MD」）。把提示词 md 放到 '
      + '<span class="mono">04-资产/</span> 或 <span class="mono">04-资产/design/</span> 后刷新本页。'
      + '<div class="tiny dim" style="margin-top:4px">' + esc((md && md.note) || '') + '</div></div></div>' : '')

    + '<div class="grid g4" style="margin-bottom:16px">'
    + '<div class="kpi"><div class="kpi-k">角色资产</div><div class="kpi-v">' + (a.char_generated || 0) + '</div>'
    + '<div class="kpi-n">缺口 ' + missChars.length + ' 个'
    + ((!a.char_generated && looseN) ? ' · <span class="dim">另有 ' + looseN + ' 张未归档（见散图）</span>' : '')
    + '</div></div>'
    + '<div class="kpi"><div class="kpi-k">场景资产</div><div class="kpi-v">' + (a.scene_generated || 0) + '</div>'
    + '<div class="kpi-n">缺口 ' + missScenes.length + ' 个</div></div>'
    + '<div class="kpi"><div class="kpi-k">本地出图产物</div><div class="kpi-v">' + (a.local_generated || 0) + '</div>'
    + '<div class="kpi-n">￥0 · 占 GPU</div></div>'
    + '</div>'

    + '<div class="tabs">'
    + TABS.map((t) => '<button class="tab' + (tab === t.key ? ' active' : '') + '" data-tab="' + t.key + '">'
      + t.label + '</button>').join('')
    + '<span class="spacer"></span><span class="tiny dim mono">'
    + (tab === 'loose'
      ? (items.length
        ? esc(items.length + ' 张 · ' + (dirDataFinal.groups || [])
          .map((g) => g.where.replace('（根目录）', '根目录') + ' ' + g.count).join(' · ') + (dirDataFinal.truncated ? ' · 仅显示前 ' + dirDataFinal.limit : ''))
        : '根目录 + 一层子目录（只读）')
      : esc((TABS.find((t) => t.key === tab) || {}).dir || '')) + '</span>'
    + '</div>'

    + '<section class="card" style="margin-bottom:16px"><div class="card-b">'
    + '<div class="tile-grid">' + tiles + '</div></div>'
    + '<div class="card-foot">' + stamp('工作区目录清单 · 图片经 /media 直出（支持 Range）') + '</div></section>'

    + '<div class="grid g2">'
    + '<section class="card"><div class="card-h"><h3>角色缺口</h3><span class="card-sub">引擎判定</span></div>'
    + '<div class="card-b">' + (missChars.length
      ? missChars.map((n) => '<span class="chip" style="margin:0 6px 6px 0">' + esc(n) + '</span>').join('')
      : '<div class="dim small">没有缺口</div>') + '</div></section>'
    + '<section class="card"><div class="card-h"><h3>场景缺口</h3><span class="card-sub">引擎判定</span></div>'
    + '<div class="card-b">' + (missScenes.length
      ? missScenes.map((n) => '<span class="chip" style="margin:0 6px 6px 0">' + esc(n) + '</span>').join('')
      : '<div class="dim small">没有缺口</div>') + '</div></section>'
    + '</div>'

    + '<section class="card" style="margin-top:16px"><div class="card-h"><h3>出图前置与边界</h3>'
    + '<span class="card-sub">哪些由网页管，哪些必须你去处理</span></div>'
    + '<div class="card-b">'
    + '<div class="clitem"><span class="mk ' + (mdOk ? 'ok' : 'warn') + '">' + icon(mdOk ? 'check' : 'alert', 12)
    + '</span><div class="body"><div class="ttl"><span>资产提示词 md</span>'
    + (mdOk ? badge('ok', '已找到') : badge('warn', '缺失')) + '</div>'
    + '<div class="desc">' + (mdOk ? '<span class="mono">' + esc((md.items.find(
      (x) => x.path === md.suggested) || {}).rel || md.suggested) + '</span>'
      : '放到 <span class="mono">04-资产/</span> 或 <span class="mono">04-资产/design/</span>') + '</div></div></div>'
    + '<div class="clitem"><span class="mk warn">' + icon('cpu', 12) + '</span><div class="body">'
    + '<div class="ttl"><span>本地 ComfyUI</span>' + badge('outline', '￥0 · 占 GPU') + '</div>'
    + '<div class="desc">需要在 8188 端口运行。先点「出图器体检」确认在线，否则会排到队才失败。</div></div></div>'
    + '<div class="clitem"><span class="mk warn">' + icon('coins', 12) + '</span><div class="body">'
    + '<div class="ttl"><span>云端 RunningHub</span>' + badge('warn', '★计费') + '</div>'
    + '<div class="desc">人物约 27 点/张、场景约 $0.01/张，按平台实际用量结算；提交前必须勾选确认。</div></div></div>'
    + '<div class="clitem"><span class="mk off">' + icon('close', 12) + '</span><div class="body">'
    + '<div class="ttl"><span>在线改提示词 / 参考图瘦身写盘</span>' + badge('muted', '未开放') + '</div>'
    + '<div class="desc">提示词改动请改 md 后重新出图；瘦身命令 <span class="mono">refs.apply</span> 会写盘，'
    + '本页只做体检。</div></div></div>'
    + '</div></section>';

  return {
    html,
    mount: (root) => {
      paintIcons(root);
      root.querySelectorAll('[data-tab]').forEach((b) => {
        b.onclick = () => {
          if (b.dataset.tab === tab) return;
          location.hash = '#/assets?tab=' + b.dataset.tab;
        };
      });
      root.querySelectorAll('[data-img]').forEach((el) => {
        el.onclick = () => {
          const url = mediaUrl(ctx.ws, el.dataset.img);
          openDrawer({
            title: el.dataset.name,
            html: '<div class="video-box"><img class="frame" alt="" src="' + esc(url) + '"></div>'
              + '<dl class="kv" style="margin-top:12px"><dt>相对路径</dt><dd class="mono">'
              + esc(el.dataset.img) + '</dd></dl>'
              + '<div class="tiny dim" style="margin-top:10px">图片为原始产物，未做缩略与转码。</div>',
            foot: '<span class="spacer"></span>'
              + '<a class="btn quiet" target="_blank" rel="noopener" href="' + esc(url) + '">新窗口打开</a>'
              + '<button class="btn quiet" data-close="drawer">关闭</button>',
            mount: (r) => paintIcons(r)
          });
        };
      });
      const chk = root.querySelector('#btnAssetCheck');
      if (chk) chk.onclick = () => runAction(ctx, {
        specId: 'assets.check',
        title: '出图器体检（ComfyUI 是否在线）',
        // 体检脚本也要求 SOLODRAMA_ASSET_MD：不传会误报成「ComfyUI 没开」
        params: { asset_md: (md && md.suggested) || '' }
      });
      const refs = root.querySelector('#btnRefsCheck');
      if (refs) refs.onclick = () => runAction(ctx, { specId: 'refs.report', title: '参考图体检（只读）' });
      const gen = root.querySelector('#btnGen');
      if (gen) gen.onclick = () => openGenPanel(ctx, md);
    }
  };
}

/* ---------- 出图面板 ---------- */
function openGenPanel(ctx, md) {
  const cands = (md && md.items) || [];
  const mdOpts = (cands.length
    ? cands.map((c) => '<option value="' + esc(c.path) + '"'
      + (c.path === (md.suggested || '') ? ' selected' : '') + '>' + esc(c.rel) + '</option>').join('')
    : '<option value="">（没找到，请先在 04-资产/ 放一份提示词 md）</option>');

  openDrawer({
    title: '资产出图',
    html: '<div class="stack">'
      + '<div class="field"><label class="tiny dim">通道</label>'
      + '<div class="row-gap">'
      + '<label class="chk"><input type="radio" name="gEng" value="local" checked>'
      + '<span>本地 ComfyUI（￥0，占 GPU 数分钟）</span></label>'
      + '<label class="chk"><input type="radio" name="gEng" value="rh">'
      + '<span>云端 RunningHub（<b>★计费</b>，按张结算）</span></label>'
      + '</div></div>'

      + '<div class="field"><label class="tiny dim">资产提示词 md（引擎只认环境变量 SOLODRAMA_ASSET_MD）</label>'
      + '<select class="select" id="gMd">' + mdOpts + '</select>'
      + '<div class="tiny dim" style="margin-top:4px">' + esc((md && md.note) || '') + '</div></div>'

      + '<div class="grid g2">'
      + '<div class="field"><label class="tiny dim">类型</label>'
      + '<select class="select" id="gKind"><option value="all">全部</option>'
      + '<option value="char">只人物</option><option value="scene">只场景</option>'
      + '<option value="prop">只道具（仅本地）</option></select></div>'
      + '<div class="field"><label class="tiny dim">只做这些（可空）</label>'
      + '<input class="input" id="gOnly" placeholder="char_01,char_02"></div></div>'

      + '<label class="chk"><input type="checkbox" id="gForce">'
      + '<span>已生成的也重跑（云端会重复计费）</span></label>'

      + '<div class="alert info"><span class="nav-ico">' + icon('alert', 14) + '</span><div>'
      + '两条通道都是<b>后台作业</b>：提交后到「任务中心」看实时日志。'
      + '本地通道先点「出图器体检」确认 8188 在线，能省掉一轮排队失败。</div></div>'
      + '</div>',
    foot: '<span class="spacer"></span>'
      + '<button class="btn quiet" data-close="drawer">取消</button>'
      + '<button class="btn quiet" id="gDry">干跑（不占 GPU）</button>'
      + '<button class="btn primary" id="gRun">开始出图</button>',
    mount: (root) => {
      paintIcons(root);
      const val = (sel) => {
        const el = root.querySelector(sel);
        return el ? el.value : '';
      };
      const checked = (sel) => {
        const el = root.querySelector(sel);
        return !!(el && el.checked);
      };
      const engine = () => {
        const r = root.querySelector('input[name="gEng"]:checked');
        return r ? r.value : 'local';
      };
      const params = (submit) => ({
        kind: val('#gKind') || 'all',
        only: (val('#gOnly') || '').trim(),
        force: checked('#gForce'),
        submit,
        asset_md: val('#gMd')
      });

      root.querySelector('#gDry').onclick = () => {
        const p = params(false);
        closeDrawer();
        doRun(ctx, {
          specId: engine() === 'rh' ? 'assets.rh' : 'assets.local',
          title: (engine() === 'rh' ? '云端出图' : '本地出图') + ' · 干跑（列出清单与单价，不提交）',
          params: p,
          onDone: () => setTimeout(() => ctx.refresh(), 1200)
        });
      };

      root.querySelector('#gRun').onclick = () => {
        const p = params(true);
        const eng = engine();
        if (!p.asset_md) {
          toast('先选「资产提示词 md」，否则引擎会报未设置 SOLODRAMA_ASSET_MD', 'bad');
          return;
        }
        if (eng === 'local') {
          openModal({
            title: '本地出图（占 GPU）',
            icon: 'cpu',
            html: '<div class="small">会调用本机 ComfyUI 出图，<b>不花钱但占 GPU</b>（通常几分钟）。'
              + '<div class="tiny dim" style="margin-top:8px">类型：' + esc(p.kind)
              + (p.only ? ' · 只做 ' + esc(p.only) : '') + '</div>'
              + (p.force ? '<div class="tiny dim">已生成的会重跑</div>' : '') + '</div>'
              + '<div class="alert info" style="margin-top:10px"><span class="nav-ico">' + icon('alert', 14)
              + '</span><div>前提：ComfyUI 在 <span class="mono">127.0.0.1:8188</span> 运行。</div></div>',
            foot: '<span class="spacer"></span><button class="btn quiet" data-close="modal">取消</button>'
              + '<button class="btn primary" id="gOk">开始</button>',
            mount: (m) => {
              m.querySelector('#gOk').onclick = () => {
                closeModal(); closeDrawer();
                doRun(ctx, {
                  specId: 'assets.local', title: '本地出图（真跑）', params: p,
                  onDone: () => setTimeout(() => ctx.refresh(), 1500)
                });
              };
            }
          });
        } else {
          closeDrawer();
          runAction(ctx, {
            specId: 'assets.rh',
            title: '云端出图（★计费）',
            params: p,
            costTitle: '云端出图（按张计费）',
            cost: {
              lines: [
                ['通道', 'RunningHub 云端'],
                ['类型', p.kind + (p.only ? ' · 只做 ' + p.only : '')],
                ['单价参考', '人物约 27 点/张 · 场景约 $0.01/张'],
                ['合计', '按张数 × 单价，以平台实际用量结算']
              ],
              note: '提交后不可撤回；已生成的资产若勾了「重跑」会重复计费。'
            },
            onDone: () => setTimeout(() => ctx.refresh(), 1500)
          });
        }
      };
    }
  });
}
