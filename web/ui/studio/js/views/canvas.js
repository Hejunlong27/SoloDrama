/* ============================================================
   canvas.js —— 剧集画布（P1，只读）
   横向 = 镜号，纵向 = 集号；一格 = 一镜。点一格看这一镜的四段链。

   为什么是表格而不是自由节点画布：
     一集 60 秒最多十来个镜头，一整季 30 集 —— 结构是**规整的行列**，
     不是任意拓扑。用 table 就能拿到「左侧集号列 + 顶部镜号行」双向吸顶，
     而自由画布要自己实现命中测试、文字换行和滚动同步，换来的只是「能拖歪」。
     镜头画布（四段链）才是需要空间感的地方，那是 P1 之后的事。

   为什么只读：先让人判断「这个空间结构对不对」。改结构比改交互便宜十倍。
   ============================================================ */
import { api, mediaUrl } from '../api.js';
import { esc, icon, badge, toast, openDrawer, bytes } from '../ui.js';

/* 模块级状态：切页回来还保持筛选（否则每次都要重选「只看缺口」） */
let filter = 'all';        // all | gap | done
let hideEmpty = false;

const STATE_CN = { done: '已出片', board: '有分镜图', todo: '待出片' };

function pct(v) {
  return Math.round((Number(v) || 0) * 100) + '%';
}

function num(v) {
  const n = Number(v) || 0;
  return n.toLocaleString('zh-CN');
}

/* ---------- 空态 ----------
   这不是「加载失败」，是「还没有制作包」。所以要把真源路径写出来，
   否则人会去翻 04-资产 找格子，而格子根本不在那儿。 */
function emptyView(ctx, data) {
  const s = data.sources || {};
  const total = (data.totals || {}).expected_ep || 0;
  const html = `
    <div class="page-head"><div>
      <div class="crumb"><b>项目管理</b><span class="sep">/</span><b>${esc(ctx.project ? (ctx.project.title || ctx.project.path) : ctx.ws)}</b></div>
      <h1 class="page-title">剧集画布</h1>
      <div class="page-sub">横向镜号 · 纵向集号 · 一格一镜。格子的状态只认磁盘上的文件。</div>
    </div></div>
    <div class="card"><div class="card-b">
      <div class="empty">
        <div class="empty-t">这个项目还没有可画的格子</div>
        <div class="empty-h">
          格子的真源是 <span class="mono">06-提示词/&lt;集&gt;/shots.json</span> ——
          制作包导入时由 <span class="mono">pack_import</span> 写成。现在这个文件不存在，
          所以一镜也画不出来${total ? '（目标是 ' + total + ' 集）' : ''}。
        </div>
        <div class="row" style="justify-content:center">
          <button class="btn primary" data-go="create">${icon('spark', 14)} 去创作页</button>
          <button class="btn quiet" data-go="skills">${icon('layers', 14)} 看 Skill 中心</button>
          <button class="btn quiet" data-go="storyboard">${icon('film', 14)} 镜头与出片</button>
        </div>
      </div>
      <div class="alert info" style="margin-top:6px"><span class="nav-ico">${icon('alert', 14)}</span><div>
        <b>已经扫过这三处</b><br>
        <span class="small mono">数据 ${esc(s.data || '—')}</span><br>
        <span class="small mono">分镜图 ${esc(s.boards || '—')}</span><br>
        <span class="small mono">成片 ${esc(s.out || '—')}</span>
      </div></div>
    </div></div>`;
  return {
    html,
    mount: (root) => {
      root.querySelectorAll('[data-go]').forEach((b) => {
        b.onclick = () => ctx.navigate(b.dataset.go);
      });
    }
  };
}

/* ---------- 一格 ---------- */
function cellHtml(row, i) {
  const c = row.shots[i];
  if (!c) return '<td class="cv-na"></td>';
  const bits = ['第 ' + c.n + ' 镜', c.shot_id, STATE_CN[c.state] || c.state];
  if (c.dur) bits.push(c.dur + ' 秒');
  if (c.cast) bits.push(c.cast + ' 张参考图');
  return '<td class="cv-td"><button class="cv-cell ' + c.state + '"'
    + ' data-ep="' + esc(row.ep) + '" data-shot="' + esc(c.shot_id) + '"'
    + ' title="' + esc(bits.join(' · ')) + '" aria-label="' + esc(bits.join(' · ')) + '"></button></td>';
}

/* ---------- 一行 ---------- */
function rowHtml(row, axis) {
  const c = row.counts || { total: 0, done: 0, board: 0, todo: 0 };
  const done = c.done || 0;
  const total = c.total || 0;
  const state = !total ? 'na' : (done === total ? 'done' : (done ? 'doing' : 'todo'));
  const barW = total ? Math.round(done / total * 100) : 0;
  let cells = '';
  for (let i = 0; i < axis; i += 1) cells += cellHtml(row, i);
  const tags = (row.release ? badge('ok', '已发行', row.release) : '')
    + (row.subs ? badge('live', '已出母版') : '')
    + (row.no_pack && total ? badge('muted', '无制作包', '这一集的镜头顺序不是 shots.json 给的') : '');
  return '<tr data-row="1" data-total="' + total + '" data-done="' + done + '"'
    + ' data-state="' + state + '">'
    + '<th class="cv-ep ' + state + '" title="' + esc(row.ep + (row.duration ? ' · 共 ' + row.duration + ' 秒' : '')) + '">'
    + '<span class="cv-ep-n mono">' + esc(row.ep) + '</span>'
    + '<span class="cv-ep-p mono">' + (total ? done + '/' + total : '—') + '</span>'
    + '<i class="cv-ep-bar" style="width:' + barW + '%"></i>'
    + '</th>'
    + cells
    + '<td class="cv-tags">' + tags + '</td>'
    + '</tr>';
}

export async function render(ctx) {
  const data = await api.canvasSeries(ctx.ws);
  const t = data.totals || {};
  if (!t.shots) return emptyView(ctx, data);

  const axis = data.axis || 0;
  const rows = data.rows || [];
  const cols = data.col_counts || [];
  const full = t.done === t.shots && t.shots > 0;

  const head = [];
  for (let i = 0; i < axis; i += 1) {
    head.push('<th class="cv-col" title="第 ' + (i + 1) + ' 镜">' + (i + 1) + '</th>');
  }
  // 缺口行放在表头下面、正文上面：一季 30 行时它在最底部就永远看不见，
  // 而「卡在哪一镜」正是这张图最该一眼回答的问题。
  const foot = cols.map((c, i) => {
    const miss = (c.board || 0) + (c.todo || 0);
    return '<td class="cv-foot' + (miss ? '' : ' zero') + '" title="第 ' + (i + 1) + ' 镜：'
      + miss + ' 集未出片">' + (miss || '·') + '</td>';
  }).join('');

  const html = `
    <div class="page-head"><div>
      <div class="crumb"><b>项目管理</b><span class="sep">/</span><b>${esc(ctx.project ? (ctx.project.title || ctx.project.path) : ctx.ws)}</b></div>
      <h1 class="page-title">剧集画布</h1>
      <div class="page-sub">横向镜号 · 纵向集号 · 一格一镜。状态只认磁盘：
        <span class="mono">07-成片</span> 的段文件 / <span class="mono">04-资产/boards</span> 的分镜图。</div>
    </div>
    <div class="page-actions">
      <div class="seg" id="cvFilter">
        <button data-f="all" class="${filter === 'all' ? 'active' : ''}">全部 ${rows.length}</button>
        <button data-f="gap" class="${filter === 'gap' ? 'active' : ''}">有缺口 ${rows.filter((r) => r.counts.total && r.counts.done < r.counts.total).length}</button>
        <button data-f="done" class="${filter === 'done' ? 'active' : ''}">已完成 ${rows.filter((r) => r.counts.total && r.counts.done === r.counts.total).length}</button>
      </div>
      <button class="btn quiet" id="cvRefresh">${icon('refresh', 14)} 重新扫描</button>
    </div></div>

    <div class="row cv-stats">
      <span class="chip">集 ${num(t.episodes)}<span class="dim"> / ${num(t.rows)}</span></span>
      <span class="chip">镜 ${num(t.shots)}</span>
      <span class="chip${full ? ' on' : ''}">已出片 ${num(t.done)}<span class="dim"> · ${pct(t.percent)}</span></span>
      <span class="chip">有分镜图 ${num(t.board)}</span>
      <span class="chip">待出片 ${num(t.todo)}</span>
      <span class="chip">已发行 ${num(t.released)}</span>
      <span class="spacer"></span>
      <span class="cv-legend">
        <i class="cv-key done"></i>已出片
        <i class="cv-key board"></i>有分镜图
        <i class="cv-key todo"></i>待出片
        <i class="cv-key na"></i>无此镜
      </span>
    </div>

    <div class="card"><div class="card-h">
      <h3>全季</h3>
      <span class="card-sub">点了看四段链</span>
      <span class="spacer"></span>
      <button class="chip${hideEmpty ? ' on' : ''}" id="cvHideEmpty">隐藏无制作包的集</button>
    </div>
    <div class="cv-scroll" id="cvScroll">
      <table class="cv-tb">
        <thead><tr>
          <th class="cv-corner">集 / 镜</th>
          ${head.join('')}
          <th class="cv-tags-h">状态</th>
        </tr>
        <tr class="cv-gap">
          <th class="cv-corner cv-gap-h">未出片</th>
          ${foot}
          <td class="cv-tags"></td>
        </tr></thead>
        <tbody>${rows.map((r) => rowHtml(r, axis)).join('')}</tbody>
      </table>
    </div>
    <div class="card-foot">
      <span class="stamp"><i class="dot todo"></i>${num(t.with_pack)} 集有制作包${t.expected_ep ? ' · 目标 ' + num(t.expected_ep) + ' 集' : ''}</span>
      <span class="spacer"></span>
      <span class="tiny dim">只读 · 画布不写磁盘</span>
    </div></div>`;

  return {
    html,
    mount: (root) => {
      const applyFilter = () => {
        let shown = 0;
        root.querySelectorAll('[data-row]').forEach((tr) => {
          const total = Number(tr.dataset.total);
          const done = Number(tr.dataset.done);
          let show = true;
          if (hideEmpty && total === 0) show = false;
          if (filter === 'gap') show = show && total > 0 && done < total;
          if (filter === 'done') show = show && total > 0 && done === total;
          tr.classList.toggle('hide', !show);
          if (show) shown += 1;
        });
        const h = root.querySelector('#cvHideEmpty');
        if (h) h.classList.toggle('on', hideEmpty);
        const s = root.querySelector('.cv-scroll');
        if (s) s.classList.toggle('is-empty', shown === 0);
      };

      root.querySelectorAll('#cvFilter [data-f]').forEach((b) => {
        b.onclick = () => {
          filter = b.dataset.f;
          root.querySelectorAll('#cvFilter [data-f]').forEach((x) => x.classList.toggle('active', x === b));
          applyFilter();
        };
      });
      const he = root.querySelector('#cvHideEmpty');
      if (he) he.onclick = () => { hideEmpty = !hideEmpty; applyFilter(); };
      const rf = root.querySelector('#cvRefresh');
      if (rf) rf.onclick = () => ctx.refresh();

      root.querySelectorAll('.cv-cell').forEach((b) => {
        b.onclick = () => openShot(ctx, b.dataset.ep, b.dataset.shot);
      });
      applyFilter();
    }
  };
}

/* ---------- 单镜抽屉：四段链 ---------- */
function chainHtml(d) {
  const steps = [
    { k: '参考图', v: (d.cast || []).length ? (d.cast.length + ' 张') : '无', on: !!(d.cast || []).length },
    { k: '提示词', v: d.prompt && d.prompt.text ? (d.prompt.text.length + ' 字') : '缺', on: !!(d.prompt && d.prompt.text) },
    { k: '生成参数', v: d.prompt && d.prompt.duration ? (d.prompt.duration + ' 秒') : '缺', on: !!(d.prompt && d.prompt.duration) },
    { k: '产物', v: d.video && d.video.rel ? 'final.mp4' : (d.board && d.board.rel ? '仅分镜图' : '无'), on: !!(d.video && d.video.rel) }
  ];
  return '<div class="cv-chain">' + steps.map((s) => (
    '<div class="cv-node' + (s.on ? ' on' : '') + '">'
    + '<span class="k">' + esc(s.k) + '</span><span class="v">' + esc(s.v) + '</span></div>'
  )).join('<i class="cv-arr">' + icon('chevron', 12) + '</i>') + '</div>';
}

function castHtml(cast, ws) {
  if (!cast || !cast.length) {
    return '<div class="alert info"><span class="nav-ico">' + icon('alert', 14) + '</span>'
      + '<div>这一镜没有登记参考图（<span class="mono">cast</span> 为空）。</div></div>';
  }
  return '<div class="cv-cast">' + cast.map((c) => (
    '<figure class="cv-cast-i" title="' + esc(c.key) + '">'
    + (c.rel ? '<img src="' + esc(mediaUrl(ws, c.rel)) + '" alt="' + esc(c.key) + '" loading="lazy">'
      : '<div class="cv-cast-ph">' + icon('image', 14) + '</div>')
    + '<figcaption class="mono">' + esc(c.key) + '</figcaption></figure>'
  )).join('') + '</div>';
}

async function openShot(ctx, ep, shotId) {
  openDrawer({
    title: ep + ' · ' + shotId,
    html: '<div class="stack">'
      + '<div class="skeleton" style="height:16px;width:40%"></div>'
      + '<div class="skeleton" style="height:120px"></div>'
      + '<div class="skeleton" style="height:12px;width:70%"></div></div>',
    foot: '<span class="spacer"></span><button class="btn quiet" data-close="drawer">关闭</button>'
  });
  let d;
  try {
    d = await api.canvasShot(ctx.ws, ep, shotId);
  } catch (err) {
    d = { ok: false, detail: err.detail || err.message };
  }
  const body = document.getElementById('drawerBody');
  if (!body || !document.getElementById('drawer').classList.contains('on')) return;
  if (!d || !d.ok) {
    body.innerHTML = '<div class="alert bad"><span class="nav-ico">' + icon('alert', 14) + '</span><div>'
      + esc((d && (d.detail || d.reason)) || '读不到这一镜') + '</div></div>';
    return;
  }

  const meta = [];
  if (d.prompt && d.prompt.duration) meta.push(badge('muted', d.prompt.duration + ' 秒'));
  if (d.ratio) meta.push(badge('muted', d.ratio));
  if (d.n) meta.push(badge('muted', '第 ' + d.n + ' 镜'));
  if (d.video && d.video.rel) meta.push(badge('ok', '已出片'));
  else if (d.board && d.board.rel) meta.push(badge('live', '仅有分镜图'));
  else meta.push(badge('outline', '未出图'));

  const media = '<div class="cv-media">'
    + '<div class="mtile">'
    + (d.board && d.board.rel
      ? '<a href="' + esc(mediaUrl(ctx.ws, d.board.rel)) + '" target="_blank" rel="noopener">'
        + '<img class="cv-board" src="' + esc(mediaUrl(ctx.ws, d.board.rel)) + '" alt="分镜图"></a>'
      : '<div class="mtile-ph tall">' + icon('image', 22) + '<span>没有分镜图</span></div>')
    + '<div class="mtile-cap mono"><span>' + esc(d.board && d.board.rel ? d.board.rel : '04-资产/boards/' + ep) + '</span></div>'
    + '</div>'
    + '<div class="mtile">'
    + (d.video && d.video.rel
      ? '<div class="video-box"><video controls preload="metadata" src="'
        + esc(mediaUrl(ctx.ws, d.video.rel)) + '"></video></div>'
      : '<div class="mtile-ph tall">' + icon('film', 22) + '<span>还没有成片段</span></div>')
    + '<div class="mtile-cap mono"><span>' + esc(d.video && d.video.rel ? d.video.rel : 'final.mp4 未落盘') + '</span></div>'
    + '</div></div>';

  const kv = '<dl class="kv">'
    + '<dt>镜号</dt><dd class="mono">' + esc(d.shot_id) + '</dd>'
    + '<dt>画幅</dt><dd class="mono">' + esc(d.ratio || '—') + '</dd>'
    + '<dt>参考图</dt><dd>' + esc(d.cast.length + ' 张 · ' + (d.cast.map((c) => c.key).join(' ') || '—')) + '</dd>'
    + '<dt>分镜图 key</dt><dd class="mono">' + esc(d.board_ref || '—') + '</dd>'
    + '<dt>成片大小</dt><dd class="mono">' + esc(d.video && d.video.bytes ? bytes(d.video.bytes) : '—') + '</dd>'
    + '<dt>数据目录</dt><dd class="mono small">' + esc(d.files) + '</dd>'
    + '</dl>';

  const prompt = (d.prompt && d.prompt.text)
    ? '<pre class="log" style="max-height:240px">' + esc(d.prompt.text) + '</pre>'
      + '<div class="row" style="margin-top:8px"><button class="btn quiet sm" id="cvCopy">'
      + icon('copy', 12) + ' 复制提示词</button>'
      + '<span class="tiny dim">只读：提示词由制作包给定，改它要回制作包</span></div>'
    : '<div class="alert warn"><span class="nav-ico">' + icon('alert', 14) + '</span><div>'
      + '这一镜没有提示词（<span class="mono">h3_prompts.json</span> 里没有这条）。</div></div>';

  body.innerHTML = '<div class="stack">'
    + '<div class="row" style="flex-wrap:wrap">' + meta.join('') + '</div>'
    + chainHtml(d)
    + media
    + kv
    + '<div><div class="card-h" style="padding:0 0 6px;border:0"><h3>参考图</h3>'
    + '<span class="card-sub">顺序 = 提示词里的 {{Mixed n}} 图号，不能单独换</span></div>'
    + castHtml(d.cast, ctx.ws) + '</div>'
    + '<div><div class="card-h" style="padding:0 0 6px;border:0"><h3>提示词</h3>'
    + '<span class="card-sub">六段式</span></div>' + prompt + '</div>'
    + '</div>';

  const cp = body.querySelector('#cvCopy');
  if (cp) {
    cp.onclick = async () => {
      try { await navigator.clipboard.writeText(d.prompt.text); toast('已复制'); }
      catch (e) { toast('复制失败（浏览器限制）', 'warn'); }
    };
  }
}
