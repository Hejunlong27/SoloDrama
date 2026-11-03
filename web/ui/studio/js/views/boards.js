/* ============================================================
   boards.js —— 分镜图（独立一环）

   为什么从「资产」里单拎出来
   ------------------------
   分镜图不是资产图：资产图是**身份锚**（这张脸/这个场景长什么样），
   分镜图是**构图锚**（这一镜的机位、光位、人物位置）。两者提示词来源不同、
   失败原因不同、重跑代价也不同（一张 9:16 首帧 vs 一张角色主卡）。
   混在资产页里，出问题时人会先去重跑角色卡 —— 方向错了。

   工作流（与天虫那套实操一致）
   --------------------------
   导演手册写 `board` 字段 → 制作包导入 → `06-提示词/<ep>/boards.json`
   → 本页「出分镜图」→ `04-资产/boards/<ep>/<shot_id>.png` → 出片时当第 1 张参考图。
   所以这一页只做一件事：**看图、看缺哪几镜、重跑**。
   ============================================================ */
import { api, mediaUrl } from '../api.js';
import { esc, icon, badge, toast, openDrawer, emptyBox } from '../ui.js';
import { runAction } from '../action.js';

let epSel = '';
let onlyMissing = false;

export async function render(ctx) {
  const d = await api.canvasSeries(ctx.ws);
  const rows = (d.rows || []).filter((r) => r.counts && r.counts.total);
  if (!epSel || !rows.some((r) => r.ep === epSel)) {
    epSel = (rows.find((r) => r.counts.board < r.counts.total) || rows[0] || {}).ep || '';
  }
  const row = rows.find((r) => r.ep === epSel) || null;

  if (!rows.length) {
    return {
      html: '<div class="page-head"><div><h1 class="page-title">分镜</h1>'
        + '<div class="page-sub">每镜一张 9:16 首帧，出片时当第一张参考图。</div></div></div>'
        + '<div class="card"><div class="card-b">'
        + emptyBox('还没有制作包，所以没有分镜可出',
          '分镜图读的是 06-提示词/<集>/boards.json（制作包导入时生成）。先去「创作」把导演手册写完、导入制作包。')
        + '<div class="row" style="justify-content:center">'
        + '<button class="btn primary" data-go="create">' + icon('spark', 14) + ' 去创作</button>'
        + '<button class="btn quiet" data-go="graph">' + icon('canvas', 14) + ' 看画布</button></div>'
        + '</div></div>',
      mount: (root) => bindGo(root, ctx)
    };
  }

  const cells = (row.shots || []).filter((c) => !onlyMissing || c.state !== 'done' || !c.board);
  const miss = (row.shots || []).filter((c) => !c.board).length;
  const done = row.counts.total - miss;

  const grid = cells.map((c) => {
    const has = !!c.board;
    return '<figure class="bd-card" data-shot="' + esc(c.shot_id) + '" title="' + esc(c.shot_id) + '">'
      + '<div class="bd-ph">' + (has
        ? '<img src="' + esc(mediaUrl(ctx.ws, c.board)) + '" alt="' + esc(c.shot_id) + '" loading="lazy">'
        : '<span class="bd-miss">' + icon('image', 20) + '<b>缺这一镜</b></span>')
      + '</div>'
      + '<figcaption><span class="mono">' + esc(c.shot_id) + '</span>'
      + '<span class="tiny dim">' + esc(c.dur ? c.dur + 's' : '') + '</span></figcaption>'
      + '</figure>';
  }).join('');

  const html = ''
    + '<div class="page-head"><div>'
    + '<div class="crumb"><b>当前项目</b><span class="sep">/</span><b>'
    + esc(ctx.project ? (ctx.project.title || ctx.project.path) : ctx.ws) + '</b></div>'
    + '<h1 class="page-title">分镜</h1>'
    + '<div class="page-sub">每镜一张 9:16 首帧，落在 <span class="mono">04-资产/boards/'
    + esc(epSel) + '/</span>。出片时它占第 1 张参考位，是构图锚不是身份锚。</div></div>'
    + '<div class="page-actions">'
    + '<select class="select" id="bdEp" style="width:104px">'
    + rows.map((r) => '<option value="' + esc(r.ep) + '"' + (r.ep === epSel ? ' selected' : '') + '>'
      + esc(r.ep) + '</option>').join('') + '</select>'
    + '<button class="btn quiet" id="bdMissing">' + icon('alert', 14) + ' 只看缺图</button>'
    + '<button class="btn primary" id="bdRun">' + icon('play', 14) + ' 出分镜图</button>'
    + '</div></div>'

    + '<div class="row" style="flex-wrap:wrap;gap:8px;margin-bottom:14px">'
    + '<span class="chip">' + esc(epSel) + ' · ' + row.counts.total + ' 镜</span>'
    + '<span class="chip' + (done === row.counts.total ? ' on' : '') + '">已出 ' + done + '</span>'
    + (miss ? '<span class="chip" style="color:var(--accent);border-color:var(--accent-line)">缺 ' + miss + '</span>' : '')
    + (row.duration ? '<span class="chip">总时长 ' + row.duration + 's</span>' : '')
    + '<span class="spacer"></span>'
    + (miss ? badge('warn', '有 ' + miss + ' 镜没有分镜图，出片会缺构图锚') : badge('ok', '这一集齐了'))
    + '</div>'

    + '<div class="card"><div class="card-h"><h3>分镜图</h3>'
    + '<span class="card-sub">点一张看大图与它的提示词</span><span class="spacer"></span>'
    + '<span class="tiny dim">缺图时按钮会跳过缺 board 提示词的镜，并列出是哪几镜</span></div>'
    + '<div class="card-b"><div class="bd-grid">'
    + (grid || '<div class="empty"><div class="empty-t">没有要显示的分镜图</div>'
      + '<div class="empty-h">换一集，或关掉「只看缺图」。</div></div>')
    + '</div></div>'
    + '<div class="card-foot"><span class="tiny dim">来源 '
    + '<span class="mono">06-提示词/' + esc(epSel) + '/boards.json</span></span>'
    + '<span class="spacer"></span>'
    + '<button class="btn quiet sm" data-go="assets">资产图</button>'
    + '<button class="btn quiet sm" data-go="storyboard">去出片</button>'
    + '</div></div>';

  return {
    html,
    mount: (root) => {
      bindGo(root, ctx);
      const sel = root.querySelector('#bdEp');
      if (sel) sel.onchange = () => { epSel = sel.value; ctx.refresh(); };
      const om = root.querySelector('#bdMissing');
      if (om) {
        om.classList.toggle('on', onlyMissing);
        om.onclick = () => { onlyMissing = !onlyMissing; ctx.refresh(); };
      }
      const run = root.querySelector('#bdRun');
      if (run) {
        run.onclick = () => runAction(ctx, {
          specId: 'board.frame',
          title: '出分镜图 · ' + epSel,
          params: { ep: epSel },
          onDone: () => setTimeout(() => ctx.refresh(), 1200)
        });
      }
      root.querySelectorAll('.bd-card').forEach((f) => {
        f.onclick = () => peek(ctx, epSel, f.dataset.shot);
      });
    }
  };
}

function bindGo(root, ctx) {
  root.querySelectorAll('[data-go]').forEach((b) => {
    b.onclick = () => ctx.navigate(b.dataset.go);
  });
}

async function peek(ctx, ep, shotId) {
  openDrawer({
    title: ep + ' · ' + shotId,
    html: '<div class="skeleton" style="height:200px"></div>',
    foot: '<span class="spacer"></span><button class="btn quiet" data-close="drawer">关闭</button>'
  });
  let d;
  try { d = await api.canvasShot(ctx.ws, ep, shotId); } catch (e) { d = { ok: false, detail: e.detail || e.message }; }
  const body = document.getElementById('drawerBody');
  if (!body || !document.getElementById('drawer').classList.contains('on')) return;
  if (!d || !d.ok) {
    body.innerHTML = '<div class="alert bad"><span class="nav-ico">' + icon('alert', 14) + '</span><div>'
      + esc((d && (d.detail || d.reason)) || '读不到这一镜') + '</div></div>';
    return;
  }
  body.innerHTML = '<div class="stack">'
    + '<div class="mtile">' + (d.board.rel
      ? '<img class="cv-board" src="' + esc(mediaUrl(ctx.ws, d.board.rel)) + '" alt="分镜图">'
      : '<div class="mtile-ph tall">' + icon('image', 22) + '<span>没有分镜图</span></div>')
    + '<div class="mtile-cap mono"><span>' + esc(d.board.rel || '未生成') + '</span></div></div>'
    + '<div class="row">' + badge('muted', d.prompt.duration ? d.prompt.duration + ' 秒' : '时长未知')
    + badge('muted', d.ratio || '')
    + badge(d.video.rel ? 'ok' : 'outline', d.video.rel ? '已出片' : '未出片') + '</div>'
    + '<div><div class="tiny dim" style="margin-bottom:6px">分镜图提示词（构图锚）</div>'
    + (d.board.prompt
      ? '<pre class="log" style="max-height:220px">' + esc(d.board.prompt) + '</pre>'
      : '<div class="alert warn"><span class="nav-ico">' + icon('alert', 14) + '</span><div>'
        + '这一镜没有 board 提示词（boards.json 里没有它）。出分镜图时会跳过并列出。</div></div>')
    + '</div></div>';
}
