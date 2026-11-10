/* 项目驾驶舱：5 环节 / 13 节点（引擎判据）+ 下一步 + 门禁 + 集列表 + 产物目录 */
import { api } from '../api.js';
import { S } from '../store.js';
import {
  esc, icon, badge, dot, stateEl, money, coins, dt, ago, stamp, kv, openDrawer, toast, paintIcons
} from '../ui.js';

/* 集号放在 URL 上（`?ep=ep03`），不塞模块变量：
   刷新、分享链接、后退都要能回到「我看的是第 3 集」。
   空值 = 不指定，交给引擎按 ep01 评估（它自己的口径，这里不替它改）。 */
function epParam() {
  try { return (new URLSearchParams(location.search).get('ep') || '').trim(); } catch (e) { return ''; }
}

export async function render(ctx) {
  const ov = await api.overview(ctx.ws);
  const epSel = epParam();
  /* 指定了集才多起一次子进程：`/api/studio/overview` 已经跑过一次 workflow（按默认集），
     只在用户真的切换集时才值得再跑一次。 */
  const wf = epSel
    ? (await api.workflow(ctx.ws, epSel))
    : (ov.workflow || { ok: false, stages: [], reason: 'no_data' });
  const setup = ov.setup || { items: [], ready: false };
  const counts = ov.counts || {};
  const spend = ov.spend || {};

  /* ---------- 阶段矩阵：5 环节 × 13 节点 ----------
     数据来自 `drama nodes --json`：nodes[] 每条带 id / stage / state / detail，
     stages[] 带 id / name / why。两处都是引擎真值，前端不另写一套阶段模型。

     为什么不给节点编中文名：引擎里节点只有 id（`video.batch` 这种），中文名只存在于
     「环节」一级。前端自造一份映射，引擎改 id 时 UI 会继续显示旧名字 —— 那是最难查的一类漂移。
     节点 id 本身就是 CLI 里能看到的名字，专业用户读得懂。 */
  const nodes = wf.nodes || [];
  const stageDefs = wf.stages || [];
  const STAGE_ROUTE = { import: 'boards', asset: 'assets', board: 'boards', video: 'storyboard', edit: 'post' };
  const NODE_BAD = ['failed', 'blocked', 'stale'];
  const byStage = {};
  nodes.forEach((n) => { (byStage[n.stage || '?'] = byStage[n.stage || '?'] || []).push(n); });
  const stageDone = (list) => list.filter((n) => n.state === 'passed' || n.state === 'skipped').length;
  const firstBad = nodes.find((n) => NODE_BAD.indexOf(n.state) >= 0) || null;
  const nextNode = nodes.find((n) => n.state !== 'passed' && n.state !== 'skipped') || null;

  const nodeGrid = stageDefs.map((sd) => {
    const list = byStage[sd.id] || [];
    const dn = stageDone(list);
    const tone = !list.length ? 'absent'
      : dn === list.length ? 'passed'
        : (list.some((n) => NODE_BAD.indexOf(n.state) >= 0) ? (list.some((n) => n.state === 'failed') ? 'failed' : 'blocked') : 'doing');
    return '<div class="sd-nstage">'
      + '<button class="sd-nstage-h" data-go="' + esc(STAGE_ROUTE[sd.id] || 'overview') + '" title="'
      + esc(sd.name + (sd.why ? ' —— ' + sd.why : '')) + '">'
      + '<span class="sd-nstage-name"><i class="dot ' + (tone === 'passed' ? 'done' : tone === 'doing' ? 'doing' : tone === 'failed' ? 'fail' : 'todo') + '"></i>'
      + esc(sd.name) + '</span>'
      + '<span class="sd-nstage-n mono">' + dn + '/' + list.length + '</span></button>'
      + '<div class="sd-nodes">'
      + (list.length ? list.map((n) => '<span class="sd-node" data-state="' + esc(n.state) + '" title="'
        + esc(n.id + ' · ' + (n.detail || n.state)) + '">' + esc(n.id) + '</span>').join('')
        : '<span class="sd-node" data-state="absent">无节点</span>')
      + '</div></div>';
  }).join('');

  const gateRows = [];
  gateRows.push(['G-0 开工前置', setup.ready ? '九项齐备' : (setup.missing || []).length + ' 项未过',
    setup.ready ? 'ok' : 'warn']);
  gateRows.push(['G-1 画风', ov.style && ov.style.confirmed ? (ov.style.label || ov.style.choice) : '未确认',
    ov.style && ov.style.confirmed ? 'ok' : 'bad']);
  gateRows.push(['G0 出图通道', ov.models && ov.models.image && ov.models.image.confirmed
    ? (ov.models.image.label || ov.models.image.choice) : '未确认',
    ov.models && ov.models.image && ov.models.image.confirmed ? 'ok' : 'bad']);
  gateRows.push(['G0 出片通道', ov.models && ov.models.video && ov.models.video.confirmed
    ? (ov.models.video.label || ov.models.video.choice) : '未确认',
    ov.models && ov.models.video && ov.models.video.confirmed ? 'ok' : 'bad']);
  gateRows.push(['G2 出片就绪', ov.h3 && ov.h3.ready ? '工作流映射齐备' : '节点映射或槽位缺失',
    ov.h3 && ov.h3.ready ? 'ok' : 'warn']);
  if ((ov.refs_over || []).length) {
    gateRows.push(['参考图尺寸', ov.refs_over.length + ' 张超 H3 上限 5760px', 'bad']);
  }

  const gateHtml = gateRows.map(([k, v, tone]) => (
    '<div class="clitem"><span class="mk ' + (tone === 'ok' ? 'ok' : tone === 'bad' ? 'bad' : 'warn')
    + '">' + icon(tone === 'ok' ? 'check' : 'alert', 12) + '</span>'
    + '<div class="body"><div class="ttl"><span>' + esc(k) + '</span>'
    + badge(tone === 'ok' ? 'ok' : tone === 'bad' ? 'bad' : 'warn',
      tone === 'ok' ? '通过' : tone === 'bad' ? '未通过' : '待补')
    + '</div><div class="desc">' + esc(v) + '</div></div></div>'
  )).join('');

  const eps = ov.episodes || [];
  /* 下拉里只放「真实存在的集」（来自集列表）+ 一个「不指定」。
     不按计划集数生成空集：点进去会看到一个凭空造出来的 ep09，比没有更糟。 */
  const epOptions = ['<option value="">默认（引擎按 ep01 评估）</option>']
    .concat(eps.map((e) => '<option value="' + esc(e.ep) + '"'
      + (epSel && epSel.toLowerCase() === String(e.ep).toLowerCase() ? ' selected' : '') + '>'
      + esc(e.ep) + (e.total ? '（' + e.total + ' 镜）' : '') + '</option>'))
    .join('');
  const epRows = eps.map((e) => (
    '<tr><td class="mono">' + esc(e.ep) + '</td>'
    + '<td class="num">' + e.total + '</td>'
    + '<td class="num" style="color:' + (e.ok === e.total && e.total ? 'var(--ok)' : 'inherit') + '">' + e.ok + '</td>'
    + '<td class="num" style="color:' + (e.fail ? 'var(--danger)' : 'inherit') + '">' + (e.fail || '—') + '</td>'
    + '<td>' + stateEl(e.state, e.state_text) + '</td>'
    + '<td>' + (e.master ? badge('ok', '母版') : '<span class="dim">—</span>') + '</td>'
    + '<td>' + (e.upscaled ? badge('ok', '放大') : '<span class="dim">—</span>') + '</td>'
    + '<td>' + (e.subbed ? badge('ok', '字幕') : '<span class="dim">—</span>') + '</td>'
    + '<td class="mono small">' + (e.release ? esc(e.release) : '<span class="dim">—</span>') + '</td>'
    + '<td class="right"><button class="btn quiet sm" data-ep="' + esc(e.ep) + '">详情</button></td></tr>'
  )).join('') || '<tr><td colspan="10"><div class="empty"><div class="empty-t">还没有出片记录</div>'
    + '<div class="empty-h">出片后会在这里按集汇总（来源：<span class="mono">07-成片/&lt;批次&gt;/summary.json</span>）。</div>'
    + '<button class="btn quiet" data-go="storyboard">去分镜与视频</button></div></td></tr>';

  // 集数/秒数取引擎数据（blueprint.json → drama.json），不取展示文案 ——
  // 原来去 setup.items 找 `detail.seconds`，而 detail 现在是一句「集数：4」，
  // 于是页面显示「4 集 · ? 秒」。
  const meta = ov.ep_meta || {};
  const epCount = meta.total || eps.length || '—';
  const epSec = meta.seconds || '—';

  /* 判据 vs 产物：只报「有成片但下一个节点是 absent」这一种，别的组合不猜。 */
  const conflict = (nextNode && nextNode.state === 'absent'
    && eps.some((e) => e.master || e.release))
    ? { node: nextNode.id, detail: nextNode.detail || '产物不存在',
        eps: eps.filter((e) => e.master || e.release).length }
    : null;

  const adapterWarn = [];
  if (!wf.ok) {
    adapterWarn.push('流程状态未取到（reason=' + esc(wf.reason || '?') + '）：可能工作区缺少 layout.json 或引擎解释器不可用。');
  }
  if (!setup.items.length) adapterWarn.push('开工前置未取到：工作区里没有可读的 drama.json（用 drama init 建项目）。');

  const html = ''
    + '<div class="page-head"><div>'
    + '<div class="crumb"><b>项目管理</b><span class="sep">/</span><b>' + esc(ctx.project ? (ctx.project.title || ctx.project.path) : ctx.ws) + '</b></div>'
    + '<h1 class="page-title sd-display">' + esc(ctx.project ? (ctx.project.title || ctx.project.path) : ctx.ws) + '</h1>'
    + '<div class="page-sub">项目驾驶舱 · ' + esc(ctx.ws) + '</div></div>'
    + '<div class="page-actions">'
    + '<button class="btn quiet" data-go="storyboard">' + icon('film', 14) + ' 分镜与视频</button>'
    + '<button class="btn quiet" id="btnRefreshOv">' + icon('refresh', 14) + ' 重新读取</button>'
    + '</div></div>'

    + (adapterWarn.length ? '<div class="alert warn" style="margin-bottom:14px"><span class="nav-ico">'
      + icon('alert', 14) + '</span><div>' + adapterWarn.map(esc).join('<br>') + '</div></div>' : '')

    + '<section class="card" style="margin-bottom:16px">'
    + '<div class="card-h"><h3>生产阶段</h3>'
    + '<span class="card-sub">' + stageDefs.length + ' 环节 · ' + nodes.length + ' 节点 · '
    + (epSel ? '按 ' + esc(epSel) + ' 评估' : '未指定单集，按 ep01 评估') + '</span>'
    + '<span class="spacer"></span>'
    + '<select class="sd-epsel" id="epSel" title="切换按哪一集评估节点状态">' + epOptions + '</select>'
    + (firstBad ? badge('bad', '有阻塞') : wf.current ? badge('live', '当前 ' + wf.current) : badge('ok', '全部完成'))
    + '</div><div class="card-b">'
    + (nodes.length ? '<div class="sd-nodegrid">' + nodeGrid + '</div>' : '<div class="dim small">无阶段数据</div>')

    /* 「下一步」是这一页唯一的主张：说清是哪一步、为什么卡住、点了会花什么。 */
    + (nextNode
      ? '<div class="sd-next">'
        + '<div class="sd-next-k">下一步</div>'
        + '<div class="sd-next-main"><span class="mono">' + esc(nextNode.id) + '</span>'
        + (nextNode.state === 'blocked' || nextNode.state === 'failed' || nextNode.state === 'stale'
          ? ' <span class="badge bad">' + esc(nextNode.state) + '</span>' : '')
        + ((nextNode.id || '').indexOf('video.') === 0 ? ' <span class="badge warn">计费节点</span>' : '')
        + '</div>'
        + '<div class="sd-next-why">' + esc(nextNode.detail || '产物不存在，需要执行该节点。') + '</div>'
        + '<button class="btn primary" data-go="' + esc(STAGE_ROUTE[nextNode.stage] || 'overview') + '">去处理</button>'
        + '</div>'
      : '<div class="sd-next"><div class="sd-next-k">下一步</div>'
        + '<div class="sd-next-main">全部节点已通过</div>'
        + '<div class="sd-next-why">可以进入发行导出：发布版唯一出口是 <span class="mono">release_export.py --all --apply</span>。</div>'
        + '<button class="btn primary" data-go="release">去发行</button></div>')

    /* 判据与产物打架：引擎按「产物文件」判，集列表按「成片目录」读。
       两者不一致时最容易被误读成「系统坏了」，所以原文摆出来 —— 也说明引擎的行为是「不跳过」。 */
    + (conflict
      ? '<div class="alert warn" style="margin-top:12px"><span class="nav-ico">' + icon('alert', 14) + '</span>'
        + '<div><b>判据与产物不一致</b>：<span class="mono">07-成片</span> 里已有 ' + conflict.eps
        + ' 集的母版，但节点 <span class="mono">' + esc(conflict.node) + '</span> 的产物文件缺失（'
        + esc(conflict.detail) + '）。<br>引擎以判据文件为准，<b>不会</b>因为成片存在而跳过该节点 —— '
        + '要让它过，需要补齐这个产物文件或按引擎口径重跑该节点。</div></div>'
      : '')

    + '<div class="alert info" style="margin-top:12px"><span class="nav-ico">' + icon('alert', 14) + '</span>'
    + '<div>节点状态来自引擎的产物判据（<span class="mono">drama nodes --json</span>），不靠手动勾选。'
    + '被上游挡住时会写明「上游未通过：X」—— 那句话原文展示，不改写成「前置条件未满足」。'
    + '<br>判据读的是契约层（<span class="mono">data/&lt;ep&gt;/</span>），<b>不是</b>成片目录；'
    + '如果切换集后状态完全一样，先看这个项目的契约层建了没有。</div></div>'
    + '</div></section>'

    + '<div class="grid g12" style="margin-bottom:16px">'
    + '<section class="card"><div class="card-h"><h3>基本信息</h3></div><div class="card-b">'
    + kv([
      ['路径', ctx.ws, true],
      ['计划集数 / 单集秒数', epCount + ' 集 · ' + epSec + ' 秒'],
      ['镜头 / 提示词', (counts.shots || 0) + ' 镜 · ' + (counts.prompts || 0) + ' 条'],
      ['画风', (ov.style && (ov.style.label || ov.style.choice)) || '未确认'],
      ['图片', (counts.images && (counts.images.total + ' 张（角色 ' + counts.images.characters + ' / 场景 '
        + counts.images.scenes + '）' + (counts.images.loose ? ' · 另有 ' + counts.images.loose + ' 张散图' : ''))) || '0 张'],
      ['成片 / 母版', (counts.clips || 0) + ' 段 · ' + (counts.renders || 0) + ' 集'],
      ['最近批次', ov.latest_batch || '—', true]
    ])
    + '<div style="margin-top:12px">' + stamp('工作区文件 + 引擎 JSON · ' + ago(ov.updated_at)) + '</div>'
    + '</div></section>'

    + '<section class="card"><div class="card-h"><h3>门禁状态</h3><span class="card-sub">未过的门会挡住后续动作</span></div>'
    + '<div class="card-b" style="padding-top:4px">' + gateHtml + '</div>'
    + '<div class="card-foot">' + stamp('setup / style / models / status 四路 JSON') + '</div></section>'
    + '</div>'

    + '<section class="card" style="margin-bottom:16px">'
    + '<div class="card-h"><h3>集列表</h3><span class="card-sub">' + eps.length + ' 集有出片记录</span>'
    + '<span class="spacer"></span><span class="tiny dim">跨批次按镜头去重</span></div>'
    + '<div class="card-b tight"><div class="table-wrap"><table class="tb"><thead><tr>'
    + '<th style="width:72px">集号</th><th class="num" style="width:56px">镜头</th><th class="num" style="width:64px">已出片</th>'
    + '<th class="num" style="width:56px">失败</th><th style="width:88px">状态</th>'
    + '<th style="width:64px">母版</th><th style="width:64px">放大</th><th style="width:64px">字幕</th>'
    + '<th style="width:120px">发布版</th><th></th></tr></thead><tbody>' + epRows + '</tbody></table></div></div>'
    + '<div class="card-foot">' + stamp('07-成片/<批次>/summary.json + 09-发行/剧集/ · 6 秒缓存') + '</div></section>'

    + '<section class="card"><div class="card-h"><h3>产物目录</h3><span class="card-sub">只读浏览；点击查看文件清单</span>'
    + '<span class="spacer"></span><span class="badge outline">媒体可预览</span></div>'
    + '<div class="card-b"><div class="row" style="flex-wrap:wrap">'
    + ['01-调研', '02-选题', '03-剧本', '04-资产', '05-分镜', '06-提示词', '07-成片', '08-合规', '09-发行']
      .map((d) => '<button class="chip" data-dir="' + d + '">' + icon('folder', 12) + ' ' + d + '</button>').join('')
    + '</div><div class="tiny dim" style="margin-top:10px">'
    + '目录浏览走本地白名单（只允许工作区内路径、只服务媒体与文本），不会把任意路径暴露给浏览器。</div>'
    + '</div></section>';

  return {
    html,
    mount: (root) => {
      root.querySelectorAll('[data-go]').forEach((b) => { b.onclick = () => ctx.navigate(b.dataset.go); });
      const rf = root.querySelector('#btnRefreshOv');
      if (rf) rf.onclick = () => ctx.refresh();
      const sel = root.querySelector('#epSel');
      if (sel) sel.onchange = () => {
        const u = new URL(location.href);
        if (sel.value) u.searchParams.set('ep', sel.value); else u.searchParams.delete('ep');
        history.replaceState(null, '', u.toString());
        ctx.refresh();
      };
      root.querySelectorAll('[data-ep]').forEach((b) => {
        b.onclick = () => {
          const e = eps.find((x) => x.ep === b.dataset.ep);
          if (!e) return;
          const lines = [
            ['镜头', e.ok + ' / ' + e.total + ' 完成' + (e.fail ? '，失败 ' + e.fail : '')],
            ['母版', e.master || '未生成'],
            ['放大', e.upscaled || '未生成'],
            ['字幕', e.subbed || '未生成'],
            ['发布版', e.release || '未生成']
          ];
          openDrawer({
            title: e.ep + ' · 集详情',
            html: '<dl class="kv">' + lines.map(([k, v]) => '<dt>' + esc(k) + '</dt><dd class="mono">'
              + esc(v) + '</dd>').join('') + '</dl>'
              + (e.subbed ? '<div class="video-box" style="margin-top:14px"><video controls preload="metadata" src="'
                + esc('/media?ws=' + encodeURIComponent(ctx.ws) + '&rel=' + encodeURIComponent(e.subbed)) + '"></video></div>'
                : '<div class="placeholder" style="margin-top:14px"><div class="ph-icon">' + icon('film', 22) + '</div>'
                + '这一集还没有可播放的成片</div>'),
            foot: '<span class="spacer"></span><button class="btn quiet" data-close="drawer">关闭</button>'
          });
        };
      });
      root.querySelectorAll('[data-dir]').forEach((b) => {
        b.onclick = () => openDir(ctx, b.dataset.dir);
      });
    }
  };
}

export async function openDir(ctx, dir) {
  let d;
  try { d = await api.artifacts(ctx.ws, dir); } catch (e) { toast('目录不可访问：' + (e.detail || e.message), 'bad'); return; }
  const items = d.items || [];
  const rows = items.map((it) => {
    if (it.dir) {
      return '<tr class="clickable" data-sub="' + esc(it.rel) + '"><td>' + icon('folder', 12) + ' ' + esc(it.name)
        + '</td><td class="dim small">目录</td><td class="num dim">—</td><td></td></tr>';
    }
    return '<tr><td>' + esc(it.name) + '</td>'
      + '<td class="small dim">' + esc(it.kind) + '</td>'
      + '<td class="num">' + (it.bytes ? (it.bytes / 1024).toFixed(0) + ' KB' : '—') + '</td>'
      + '<td class="right">' + (it.servable
        ? '<a class="btn quiet sm" href="' + esc(it.url) + '" target="_blank" rel="noopener">打开</a>' : '') + '</td></tr>';
  }).join('') || '<tr><td colspan="4"><div class="empty"><div class="empty-t">目录为空</div></div></td></tr>';

  openDrawer({
    title: '目录 · ' + (d.dir || '工作区根'),
    html: '<div class="table-wrap"><table class="tb"><thead><tr><th>名称</th><th style="width:80px">类型</th>'
      + '<th class="num" style="width:88px">大小</th><th style="width:76px"></th></tr></thead><tbody>'
      + rows + '</tbody></table></div>'
      + (d.truncated ? '<div class="alert warn" style="margin-top:10px"><span class="nav-ico">' + icon('alert', 14)
        + '</span><div>条目超过 ' + d.limit + ' 个，已截断。</div></div>' : '')
      + '<div class="tiny dim" style="margin-top:10px">只显示媒体（mp4/webm/png/jpg/webp/wav/mp3）与文本（md/txt/ass/srt/vtt）。</div>',
    foot: '<span class="spacer"></span><button class="btn quiet" data-close="drawer">关闭</button>',
    mount: (root) => {
      root.querySelectorAll('[data-sub]').forEach((tr) => {
        tr.onclick = () => openDir(ctx, tr.dataset.sub);
      });
      paintIcons(root);
    }
  });
}
