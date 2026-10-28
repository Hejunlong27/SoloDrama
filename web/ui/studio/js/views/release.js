/* 发行中心：发布版剧集（真实文件）+ 发行目录清单 + 明确标注未接入的 G9/导出 */
import { api, mediaUrl } from '../api.js';
import { esc, icon, badge, dot, stamp, openDrawer, toast, emptyBox } from '../ui.js';

export async function render(ctx) {
  const [eps, relDir] = await Promise.all([
    api.episodes(ctx.ws).catch(() => ({ items: [] })),
    api.artifacts(ctx.ws, '09-发行').catch((e) => ({ items: [], error: e.detail || e.message }))
  ]);

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
    + '<div class="page-actions"><span class="badge muted" title="G9 发行检查与导出尚未接入">G9 未接入</span></div></div>'

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
    + card('资料齐备度（G9）', 'muted', '未接入',
      'release_check.py 会写 09-发行/release-manifest.json（属写操作），本版不把它当只读接口。'
      + '下一批接入时会作为「显式动作」提供，并展示 fails / warns / verdict。')
    + card('封面', 'muted', '未接入',
      '封面主路径是 cover_prompt.py（AI 直出带字），尚未纳入命令白名单。'
      + '工作区里已有的封面会在「发行目录」中可见。')
    + card('导出发布版', 'muted', '未接入',
      'release_export.py 默认干跑、--apply 才写盘。需先补白名单与二次确认，再开放网页端。')
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
