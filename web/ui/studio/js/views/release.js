/* 发行中心：发布版剧集（真实文件）+ G9 资料齐全度（只读）+ 发行目录清单 */
import { api, mediaUrl } from '../api.js';
import { esc, icon, badge, dot, stamp, openDrawer, toast, emptyBox, openModal } from '../ui.js';
import { runAction } from '../action.js';

export async function render(ctx) {
  const [eps, relDir, g9, ex] = await Promise.all([
    api.episodes(ctx.ws).catch(() => ({ items: [] })),
    api.artifacts(ctx.ws, '09-发行').catch((e) => ({ items: [], error: e.detail || e.message })),
    api.releaseStatus(ctx.ws).catch((e) => ({ ok: false, reason: e.detail || e.message })),
    // 干跑预览：只算不写（不带 --apply）。plans = 会导出什么，fails = 被哪些门禁拦下。
    api.releaseExportPreview(ctx.ws).catch((e) => ({ ok: false, reason: e.detail || e.message }))
  ]);
  const exPlans = (ex && ex.plans) || [];
  const exFails = (ex && ex.fails) || [];
  const exWarns = (ex && ex.warns) || [];

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
    + '<section class="card"><div class="card-h"><h3>导出发布版</h3>'
    + '<span class="spacer"></span>'
    + (exPlans.length ? badge('ok', '可导出 ' + exPlans.length + ' 集')
      : badge('warn', exFails.length ? '被拦 ' + exFails.length + ' 项' : '没有可导出的集'))
    + '</div><div class="card-b">'
    + '<div class="small muted">落点 <span class="mono">'
    + esc((ex && ex.dst_dir) || '09-发行/剧集') + '</span>，命名严格 '
    + '<span class="mono">EpisodeNN.mp4</span>；同名文件会被覆盖（覆盖前请确认已定稿）。</div>'
    + (exPlans.length
      ? '<div style="margin-top:8px">' + exPlans.slice(0, 6).map((p) => '<div class="row" style="padding:3px 0">'
        + '<span class="mono small" style="width:120px">' + esc(p.dst || '') + '</span>'
        + '<span class="tiny dim" style="flex:1;overflow:hidden;text-overflow:ellipsis">'
        + esc((p.src || '').split(/[\\/]/).pop() || '') + '</span></div>').join('')
        + (exPlans.length > 6 ? '<div class="tiny dim">…等共 ' + exPlans.length + ' 集</div>' : '')
        + '</div>'
      : '')
    + (exFails.length
      ? '<div class="alert warn" style="margin-top:8px"><span class="nav-ico">' + icon('alert', 14) + '</span>'
        + '<div><b>出口门禁拦下 ' + exFails.length + ' 项</b>，导出会被拒：<br>'
        + exFails.slice(0, 3).map((x) => '· ' + esc(String(x).slice(0, 160))).join('<br>')
        + (exFails.length > 3 ? '<br>…' : '') + '</div></div>'
      : '')
    + (exFails.some((x) => /SAR|规格|分辨率/.test(String(x)))
      ? '<div class="small" style="margin-top:6px">规格类问题：去「后期制作」重跑 '
        + '<b>③ 字幕生成与烧录</b> —— 烧字幕那步会做 crop-to-fill 归一化（SAR 1:1），'
        + '回来再点「重新干跑」。</div>'
      : '')
    + (exWarns.length ? '<div class="tiny dim" style="margin-top:6px">另有 ' + exWarns.length + ' 条提醒</div>' : '')
    + '<div class="row" style="gap:8px;margin-top:12px;flex-wrap:wrap">'
    + '<button class="btn quiet" id="btnExPreview">' + icon('refresh', 14) + ' 重新干跑</button>'
    + '<button class="btn primary" id="btnExApply"' + (exPlans.length ? '' : ' disabled')
    + '>' + icon('upload', 14) + ' 导出到 09-发行</button>'
    + (exFails.length ? '<button class="btn quiet" id="btnExAllFails">看全部拦截原因</button>' : '')
    + '</div>'
    + '<div class="card-foot">' + stamp('release_export.py --all --json（干跑）· 20 秒缓存 · 写盘要二次确认') + '</div>'
    + '</div></section>'
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
      // ---- 导出发布版 ----
      const ex1 = root.querySelector('#btnExPreview');
      if (ex1) ex1.onclick = () => ctx.refresh();

      const exAll = root.querySelector('#btnExAllFails');
      if (exAll) exAll.onclick = () => openDrawer({
        title: '导出被拦下的原因',
        html: '<div class="small muted" style="margin-bottom:8px">每条都对应一个必须解决的规格/内容问题；'
          + '改完重跑「重新干跑」。</div>'
          + exFails.map((x, i) => '<div class="row" style="padding:6px 0;border-bottom:1px solid var(--line)">'
            + '<span class="mono tiny dim" style="width:26px">' + (i + 1) + '</span>'
            + '<span class="small" style="flex:1">' + esc(String(x)) + '</span></div>').join(''),
        foot: '<span class="spacer"></span><button class="btn quiet" data-close="drawer">关闭</button>'
      });

      const exBtn = root.querySelector('#btnExApply');
      if (exBtn) exBtn.onclick = () => {
        const n = exPlans.length;
        openModal({
          title: '导出 ' + n + ' 集到 09-发行/剧集',
          icon: 'upload',
          html: '<div class="small">会写入 <b>' + n + ' 个</b> <span class="mono">EpisodeNN.mp4</span>，'
            + '同名文件<b>直接覆盖</b>（不做备份）。</div>'
            + '<div class="cost-line" style="margin-top:8px"><span class="k">落点</span><span class="v mono">'
            + esc((ex && ex.dst_dir) || '09-发行/剧集') + '</span></div>'
            + '<div class="cost-line"><span class="k">来源</span><span class="v mono small">'
            + esc(((ex && ex.src_dirs) || []).map((x) => x.split(/[\\/]/).pop()).join(' / ')) + '</span></div>'
            + '<div class="cost-line"><span class="k">费用</span><span class="v">￥0（本地复制，可勾硬链接省空间）</span></div>'
            + '<label class="chk" style="margin-top:10px"><input type="checkbox" id="exLink">'
            + '<span>用硬链接代替复制（同盘才可用，省空间）</span></label>'
            + '<div class="alert info" style="margin-top:10px"><span class="nav-ico">' + esc(icon('alert', 14))
            + '</span><div>导出前会再跑一次出口门禁（规格 + 硬字幕）；不过的不写。</div></div>',
          foot: '<span class="spacer"></span><button class="btn quiet" data-close="modal">取消</button>'
            + '<button class="btn primary" id="exGo">确认导出</button>',
          mount: (m) => {
            m.querySelector('#exGo').onclick = () => {
              const link = !!(m.querySelector('#exLink') || {}).checked;
              m.querySelector('#modal').classList.remove('on');
              runAction(ctx, {
                specId: 'release.export',
                title: '导出发布版 · ' + n + ' 集',
                params: { all: true, apply: true, link, target: '1080x1920' },
                onDone: () => setTimeout(() => ctx.refresh(), 1200)
              });
            };
          }
        });
      };

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
