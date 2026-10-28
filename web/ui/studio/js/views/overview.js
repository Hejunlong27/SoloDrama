/* 项目详情：流程 S1–S11（引擎判据）+ G-0/G-1/G0/G2 + 集列表 + 产物目录 */
import { api } from '../api.js';
import { S } from '../store.js';
import {
  esc, icon, badge, dot, stateEl, money, coins, dt, ago, stamp, kv, openDrawer, toast, paintIcons
} from '../ui.js';

const STAGE_HINT = {
  S1: '调研', S2: '剧本', S3: '资产设计', S4: '资产生成', S5: '视频提示词',
  S6: '视频生成', S7: '发行资料', S8: '拼接', S9: '放大', S10: '字幕', S11: '定稿'
};

export async function render(ctx) {
  const ov = await api.overview(ctx.ws);
  const wf = ov.workflow || { ok: false, stages: [], reason: 'no_data' };
  const setup = ov.setup || { items: [], ready: false };
  const counts = ov.counts || {};
  const spend = ov.spend || {};

  const rail = (wf.stages || []).map((s) => {
    const cls = s.state === 'done' ? ' done' : s.state === 'current' ? ' current' : '';
    const title = s.id + ' ' + s.name + (s.optional ? '（可选）' : '')
      + '\n' + (s.probes || []).map((p) => (p.ok ? '✓ ' : '✗ ') + p.label + ' ' + p.found + '/' + p.need).join('\n');
    return '<div class="rail-step' + cls + '" title="' + esc(title) + '">'
      + '<span class="rail-n">' + esc(s.id) + '</span><span class="rail-t">' + esc(s.name) + '</span></div>';
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

  const epItem = (setup.items || []).find((i) => i.key === 'episodes') || {};
  const epCount = (wf.ctx && wf.ctx.episodes) || (epItem.detail && epItem.detail.count) || eps.length || '?';
  const epSec = (epItem.detail && epItem.detail.seconds) || '?';

  const adapterWarn = [];
  if (!wf.ok) {
    adapterWarn.push('流程状态未取到（reason=' + esc(wf.reason || '?') + '）：可能工作区缺少 layout.json 或引擎解释器不可用。');
  }
  if (!setup.items.length) adapterWarn.push('开工前置（G-0）未取到：project_setup.py 未返回 JSON。');

  const html = ''
    + '<div class="page-head"><div>'
    + '<div class="crumb"><b>项目管理</b><span class="sep">/</span><b>' + esc(ctx.project ? (ctx.project.title || ctx.project.path) : ctx.ws) + '</b></div>'
    + '<h1 class="page-title">项目详情</h1>'
    + '<div class="page-sub">' + esc(ctx.ws) + '</div></div>'
    + '<div class="page-actions">'
    + '<button class="btn quiet" data-go="storyboard">' + icon('film', 14) + ' 分镜与视频</button>'
    + '<button class="btn quiet" id="btnRefreshOv">' + icon('refresh', 14) + ' 重新读取</button>'
    + '</div></div>'

    + (adapterWarn.length ? '<div class="alert warn" style="margin-bottom:14px"><span class="nav-ico">'
      + icon('alert', 14) + '</span><div>' + adapterWarn.map(esc).join('<br>') + '</div></div>' : '')

    + '<section class="card" style="margin-bottom:16px">'
    + '<div class="card-h"><h3>生产阶段</h3><span class="card-sub">S1–S11 顺序不可跳（G10）</span>'
    + '<span class="spacer"></span>'
    + (wf.current ? badge('live', '当前 ' + wf.current) : badge('ok', '全部完成'))
    + '</div><div class="card-b">'
    + (rail || '<div class="dim small">无阶段数据</div>')
    + '<div class="alert info" style="margin-top:12px"><span class="nav-ico">' + icon('alert', 14) + '</span>'
    + '<div>阶段完成度来自引擎的产物判据（<span class="mono">workflow.py status --json</span> 的 probes），'
    + '不靠手动勾选。进入下一环节前会先校验前置（未过 = 退出码 4）。</div></div>'
    + '</div></section>'

    + '<div class="grid g12" style="margin-bottom:16px">'
    + '<section class="card"><div class="card-h"><h3>基本信息</h3></div><div class="card-b">'
    + kv([
      ['路径', ctx.ws, true],
      ['集数 / 单集秒数', epCount + ' 集 · ' + epSec + ' 秒'],
      ['镜头 / 提示词', (counts.shots || 0) + ' 镜 · ' + (counts.prompts || 0) + ' 条'],
      ['画风', (ov.style && (ov.style.label || ov.style.choice)) || '未确认'],
      ['图片', (counts.images && (counts.images.total + ' 张（角色 ' + counts.images.characters + ' / 场景 '
        + counts.images.scenes + '）')) || '0 张'],
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
