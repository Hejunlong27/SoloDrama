/* 发行中心：发布版剧集（真实文件）+ G9 资料齐全度（只读）+ 发行目录清单 */
import { api, mediaUrl } from '../api.js';
import { esc, icon, badge, dot, stamp, openDrawer, toast, emptyBox } from '../ui.js';

export async function render(ctx) {
  const [eps, relDir, g9] = await Promise.all([
    api.episodes(ctx.ws).catch(() => ({ items: [] })),
    api.artifacts(ctx.ws, '09-发行').catch((e) => ({ items: [], error: e.detail || e.message })),
    api.releaseStatus(ctx.ws).catch((e) => ({ ok: false, reason: e.detail || e.message }))
  ]);

  // G9：ok / ready_for_export / blocked（release_check.py --json --no-write，纯只读）
  const g9ok = g9 && g9.ok && g9.verdict === 'ok';
  const g9Fails = (g9 && g9.fails) || [];
  const g9Warns = (g9 && g9.warns) || [];
  const g9tone = g9ok ? 'ok' : (g9 && g9.verdict ? 'warn' : 'muted');
  const g9text = g9ok ? 'G9 通过'
    : (g9 && g9.verdict === 'ready_for_export' ? 'G9 待导出'
    : (g9Fails.length ? 'G9 缺 ' + g9Fails.length + ' 项' : (g9 && g9.reason ? 'G9 读不到' : 'G9 未检查')));

  const list = (eps.items || []).filter((e) => e.release);
  const rows = list.map((e) => (
    '<tr><td class="mono">' + esc(e.ep) + '</td>'
    + '<td class="mono">' + esc(e.release) + '</td>'
    + '<td>' + badge('ok', '命名合规') + '</td>'
    + '<td class="right"><button class="btn quiet sm" data-play="' + esc(e.release) + '">播放</button></td></tr>'
  )).join('') || '<tr><td colspan="4">' + emptyBox('还没有发布版成片',
    '发布版由 release_export.py 从母版导出（EpisodeNN.mp4），本版未开放网页端导出。') + '</td></tr>';

  const dirItems = (relDir.items || []);
  const files = dirItems.filter((it) => !it.dir).slice(0, 40);

  const html = ''
    + '<div class="page-head"><div>'
    + '<div class="crumb"><b>项目管理</b><span class="sep">/</span><b>'
    + esc(ctx.project ? (ctx.project.title || ctx.project.path) : ctx.ws) + '</b></div>'
    + '<h1 class="page-title">发行中心</h1>'
    + '<div class="page-sub">发布版命名必须 <span class="mono">EpisodeNN.mp4</span>，落 '
    + '<span class="mono">09-发行/剧集/</span></div></div>'
    + '<div class="page-actions"><span class="badge ' + g9tone + '" title="'
    + esc(g9 && g9.verdict_cn ? g9.verdict_cn : 'release_check.py --json --no-write（只读）') + '">'
    + esc(g9text) + '</span></div></div>'

    + '<div class="grid g12" style="margin-bottom:16px">'
    + '<section class="card"><div class="card-h"><h3>发布版剧集</h3>'
    + '<span class="card-sub">' + list.length + ' 个文件</span></div>'
    + '<div class="card-b tight"><div class="table-wrap"><table class="tb"><thead><tr>'
    + '<th style="width:76px">集号</th><th>文件</th><th style="width:110px">检查</th><th style="width:80px"></th>'
    + '</tr></thead><tbody>' + rows + '</tbody></table></div></div>'
    + '<div class="card-foot">' + stamp('09-发行/剧集/ 目录实有文件 · 6 秒缓存') + '</div></section>'

    + '<section class="card"><div class="card-h"><h3>发行目录</h3>'
    + '<span class="card-sub">' + (relDir.dir === '' ? '工作区根' : '09-发行') + '</span>'
    + '<span class="spacer"></span><button class="btn ghost sm" id="btnBrowseRel">浏览</button></div>'
    + '<div class="card-b">'
    + (files.length ? files.map((f) => '<div class="row" style="padding:4px 0">'
      + '<span class="mono small" style="flex:1;overflow:hidden;text-overflow:ellipsis">' + esc(f.name) + '</span>'
      + '<span class="tiny dim">' + esc(f.kind) + '</span></div>').join('')
      : '<div class="dim small">' + (relDir.error ? '目录不可读：' + esc(relDir.error) : '目录为空') + '</div>')
    + '</div></section></div>'

    + '<div class="grid g3">'
    + '<section class="card"><div class="card-h"><h3>资料齐备度（G9）</h3>'
    + '<span class="spacer"></span>' + badge(g9tone, g9text) + '</div>'
    + '<div class="card-b">'
    + (g9Fails.length
      ? '<div class="small muted" style="margin-bottom:6px">还缺 '
        + g9Fails.length + ' 项（点开看全部）</div>'
        + g9Fails.slice(0, 6).map((x) => '<div class="row" style="padding:3px 0">'
          + '<span class="dot bad"></span><span class="small" style="flex:1">'
          + esc(x) + '</span></div>').join('')
        + (g9Fails.length > 6 ? '<div class="tiny dim">…等共 ' + g9Fails.length + ' 项</div>' : '')
        + '<div style="margin-top:8px"><button class="btn ghost sm" id="btnG9All">看全部缺项</button></div>'
      : (g9ok ? '<div class="small">机器校验已通过，剩下的是人工项（见发行清单）。</div>'
        : '<div class="small muted">' + esc((g9 && (g9.reason || g9.verdict_cn)) || '还没算') + '</div>'))
    + (g9Warns.length ? '<div class="tiny dim" style="margin-top:6px">另有 '
      + g9Warns.length + ' 条提醒</div>' : '')
    + '</div>'
    + '<div class="card-foot">' + stamp('release_check.py --json --no-write · 只读，不写 manifest · 20 秒缓存') + '</div></section>'
    + card('封面', g9 && (g9.found || {}).covers && (g9.found.covers || []).length ? 'ok' : 'muted',
      g9 && (g9.found || {}).covers && (g9.found.covers || []).length
        ? ((g9.found.covers || []).join(' / ') + ' 已备') : '缺封面',
      '封面档位固定 cover_9x16.png / cover_3x4.png，由封面出图流程直出（带字）。'
      + '现有文件在右侧「发行目录」中可见。')
    + card('导出发布版', 'muted', '命令行',
      'release_export.py --all --apply 才写 09-发行/剧集/EpisodeNN.mp4；默认干跑。'
      + '网页端暂不代跑（防误写盘），命令可在「流水线」页复制。')
    + '</div>';

  return {
    html,
    mount: (root) => {
      root.querySelectorAll('[data-play]').forEach((b) => {
        b.onclick = () => {
          const rel = '09-发行/剧集/' + b.dataset.play;
          openDrawer({
            title: b.dataset.play,
            html: '<div class="video-box"><video controls autoplay preload="metadata" src="'
              + esc(mediaUrl(ctx.ws, rel)) + '"></video></div>'
              + '<div class="tiny dim mono" style="margin-top:8px">' + esc(rel) + '</div>',
            foot: '<span class="spacer"></span><a class="btn quiet" target="_blank" rel="noopener" href="'
              + esc(mediaUrl(ctx.ws, rel)) + '">新窗口</a>'
              + '<button class="btn quiet" data-close="drawer">关闭</button>'
          });
        };
      });
      const g = root.querySelector('#btnG9All');
      if (g) g.onclick = () => {
        openDrawer({
          title: 'G9 还缺什么',
          html: '<div class="small muted" style="margin-bottom:8px">'
            + esc(g9.verdict_cn || '') + '</div>'
            + g9Fails.map((x, i) => '<div class="row" style="padding:4px 0;border-bottom:1px solid var(--line)">'
              + '<span class="mono tiny dim" style="width:28px">' + (i + 1) + '</span>'
              + '<span class="small" style="flex:1">' + esc(x) + '</span></div>').join('')
            + (g9Warns.length ? '<div class="ttl" style="margin-top:10px">提醒</div>'
              + g9Warns.map((x) => '<div class="small dim">· ' + esc(x) + '</div>').join('') : ''),
          foot: '<span class="spacer"></span><button class="btn quiet" data-close="drawer">关闭</button>'
        });
      };
      const b = root.querySelector('#btnBrowseRel');
      if (b) b.onclick = async () => {
        try {
          const d = await api.artifacts(ctx.ws, '09-发行');
          openDrawer({
            title: '09-发行',
            html: '<div class="table-wrap"><table class="tb"><thead><tr><th>名称</th><th style="width:80px">类型</th>'
              + '<th class="num" style="width:88px">大小</th><th style="width:70px"></th></tr></thead><tbody>'
              + (d.items || []).map((it) => '<tr><td>' + (it.dir ? icon('folder', 12) + ' ' : '') + esc(it.name) + '</td>'
                + '<td class="small dim">' + esc(it.kind) + '</td>'
                + '<td class="num">' + (it.bytes ? Math.round(it.bytes / 1024) + ' KB' : '—') + '</td>'
                + '<td class="right">' + (it.servable ? '<a class="btn quiet sm" target="_blank" rel="noopener" href="'
                  + esc(it.url) + '">打开</a>' : '') + '</td></tr>').join('')
              + '</tbody></table></div>',
            foot: '<span class="spacer"></span><button class="btn quiet" data-close="drawer">关闭</button>'
          });
        } catch (e) { toast('目录不可访问：' + (e.detail || e.message), 'bad'); }
      };
    }
  };
}

function card(title, tone, statusText, desc) {
  return '<section class="card"><div class="card-h"><h3>' + esc(title) + '</h3>'
    + '<span class="spacer"></span>' + badge(tone, statusText) + '</div>'
    + '<div class="card-b"><div class="small muted">' + esc(desc) + '</div></div></section>';
}
