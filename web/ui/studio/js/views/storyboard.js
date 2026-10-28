/* 分镜与视频：逐镜状态（引擎 summary.json）+ 产物预览（/media）+ 出片计划（免费）
   ★ 这是本版的核心路径：看得见每个镜头到哪一步、能不能播、下一批要花多少。 */
import { api, mediaUrl } from '../api.js';
import { esc, icon, badge, dot, stateEl, dt, stamp, toast, openDrawer, openModal } from '../ui.js';
import { runAction } from '../action.js';

const FILTERS = [
  { key: 'all', label: '全部' },
  { key: 'done', label: '已完成' },
  { key: 'fail', label: '失败' },
  { key: 'todo', label: '未跑' }
];

let filter = 'all';
let epFilter = '';
let selected = '';
let keyword = '';

function statusOf(s) {
  const st = (s.status || '').toUpperCase();
  if (st === 'SUCCESS' || st === 'SUCCEEDED' || st === 'OK') return 'done';
  if (st) return 'fail';
  return 'todo';
}

export async function render(ctx) {
  const data = await api.shots(ctx.ws, epFilter);
  const all = data.items || [];
  const eps = (data.episodes || []).map((e) => e.ep);
  const totals = data.totals || {};

  const counted = { all: all.length, done: 0, fail: 0, todo: 0 };
  all.forEach((s) => { counted[statusOf(s)] += 1; });

  const list = all.filter((s) => {
    if (filter !== 'all' && statusOf(s) !== filter) return false;
    if (keyword && s.shot_id.toLowerCase().indexOf(keyword) < 0) return false;
    return true;
  });

  if (!selected || !all.some((s) => s.shot_id === selected)) {
    selected = (list[0] || all[0] || {}).shot_id || '';
  }
  const sel = all.find((s) => s.shot_id === selected) || null;

  const rows = list.map((s) => {
    const st = statusOf(s);
    return '<tr class="clickable' + (s.shot_id === selected ? ' sel' : '') + '" data-shot="' + esc(s.shot_id) + '">'
      + '<td class="mono">' + esc(s.shot_id) + '</td>'
      + '<td>' + stateEl(st, st === 'done' ? '已完成' : st === 'fail' ? '失败' : '未跑') + '</td>'
      + '<td class="mono small dim">' + esc(s.batch || '—') + '</td>'
      + '<td>' + (s.rel ? badge('ok', 'final.mp4') : (st === 'fail' ? badge('bad', '缺失') : '<span class="dim">—</span>')) + '</td>'
      + '<td class="right">' + (st === 'fail'
        ? '<button class="btn quiet sm" data-retry="' + esc(s.shot_id) + '">续跑</button>'
        : '<button class="btn quiet sm" data-shot="' + esc(s.shot_id) + '">查看</button>') + '</td></tr>';
  }).join('') || '<tr><td colspan="5"><div class="empty"><div class="empty-t">没有符合条件的镜头</div>'
    + '<div class="empty-h">换个筛选条件，或先跑一次出片。</div></div></td></tr>';

  const promptBox = '<div id="promptBox"><div class="skeleton" style="height:12px;margin-bottom:8px"></div>'
    + '<div class="skeleton" style="height:12px;width:80%"></div></div>';

  const html = ''
    + '<div class="page-head"><div>'
    + '<div class="crumb"><b>项目管理</b><span class="sep">/</span><b>'
    + esc(ctx.project ? (ctx.project.title || ctx.project.path) : ctx.ws) + '</b></div>'
    + '<h1 class="page-title">分镜与视频</h1>'
    + '<div class="page-sub">逐镜状态来自 <span class="mono">07-成片/&lt;批次&gt;/summary.json</span>'
    + '（跨批次按镜头去重）· 最近批次 <span class="mono">' + esc(data.latest_batch || '无') + '</span></div></div>'
    + '<div class="page-actions">'
    + '<button class="btn quiet" id="btnCheckG10">' + icon('check', 14) + ' 校验前置（G10）</button>'
    + '<button class="btn quiet" id="btnIngest">' + icon('alert', 14) + ' 入门口禁</button>'
    + '<button class="btn" id="btnPlan">' + icon('coins', 14) + ' 出片计划（免费）</button>'
    + '</div></div>'

    + (totals.total
      ? '<div class="row" style="margin-bottom:12px;flex-wrap:wrap">'
        + '<span class="chip">镜头 ' + totals.total + '</span>'
        + '<span class="chip">成功 ' + (totals.success || 0) + '</span>'
        + '<span class="chip"' + (totals.failed ? ' style="color:var(--danger);border-color:rgba(217,105,94,.35)"' : '')
        + '>失败 ' + (totals.failed || 0) + '</span>'
        + '<span class="chip">未跑 ' + (totals.pending || 0) + '</span>'
        + '<span class="spacer"></span>'
        + (data.batches && data.batches[0] && data.batches[0].fuse && data.batches[0].fuse.blown
          ? badge('bad', '最近批次已熔断', data.batches[0].fuse.reason) : '')
        + '</div>'
      : '')

    + '<div class="grid g21">'
    + '<section class="card"><div class="card-h"><h3>镜头</h3>'
    + '<span class="card-sub">' + list.length + ' / ' + all.length + '</span><span class="spacer"></span>'
    + '<div class="search" style="width:170px"><span class="nav-ico">' + icon('search', 14) + '</span>'
    + '<input class="input" id="shotKw" placeholder="搜镜头号" value="' + esc(keyword) + '"></div>'
    + '<select class="select" id="shotEp" style="width:110px"><option value="">全部集</option>'
    + eps.map((e) => '<option value="' + esc(e) + '"' + (e === epFilter ? ' selected' : '') + '>' + esc(e) + '</option>').join('')
    + '</select></div>'
    + '<div class="card-b" style="padding-bottom:8px">'
    + '<div class="row" style="margin-bottom:8px;flex-wrap:wrap">'
    + FILTERS.map((f) => '<button class="chip' + (filter === f.key ? ' on' : '') + '" data-filter="' + f.key + '">'
      + f.label + ' ' + counted[f.key] + '</button>').join('')
    + '</div></div>'
    + '<div class="card-b tight" style="max-height:520px;overflow:auto"><div class="table-wrap">'
    + '<table class="tb"><thead><tr><th style="width:110px">镜头</th><th style="width:96px">状态</th>'
    + '<th style="width:130px">批次</th><th style="width:100px">产物</th><th></th></tr></thead>'
    + '<tbody>' + rows + '</tbody></table></div></div>'
    + '<div class="card-foot">' + stamp('summary.json · ' + (data.updated_at ? dt(data.updated_at) : '无批次')) + '</div>'
    + '</section>'

    + '<section class="card"><div class="card-h"><h3>' + esc(selected || '未选择镜头') + '</h3>'
    + '<span class="spacer"></span>' + (sel ? stateEl(statusOf(sel)) : '') + '</div>'
    + '<div class="card-b">'
    + (sel
      ? (sel.rel
        ? '<div class="video-box" style="margin-bottom:12px"><video controls preload="metadata" src="'
          + esc(mediaUrl(ctx.ws, sel.rel)) + '"></video></div>'
        : '<div class="mtile" style="margin-bottom:12px"><div class="mtile-ph tall">' + icon('film', 26)
          + '<span>' + (statusOf(sel) === 'fail' ? '这一镜没有产物' : '还没有生成') + '</span></div>'
          + '<div class="mtile-cap mono">' + esc(sel.rel || 'final.mp4 未落盘') + '</div></div>')
      + (sel.error ? '<div class="alert bad" style="margin-bottom:12px"><span class="nav-ico">' + icon('alert', 14)
        + '</span><div><b>失败原因</b><br><span class="small">' + esc(String(sel.error).slice(0, 300))
        + '</span></div></div>' : '')
      + '<dl class="kv" style="margin-bottom:12px">'
      + '<dt>批次</dt><dd class="mono">' + esc(sel.batch || '—') + '</dd>'
      + '<dt>任务号</dt><dd class="mono">' + esc(sel.task_id || '—') + '</dd>'
      + '<dt>文件</dt><dd class="mono">' + esc(sel.rel || '—') + '</dd></dl>'
      + '<div class="card-h" style="padding:0 0 6px;border:0"><h3>提示词</h3>'
      + '<span class="card-sub">六段式（来自 06-提示词）</span></div>' + promptBox
      : '<div class="empty"><div class="empty-t">左侧选一个镜头</div>'
      + '<div class="empty-h">这里会显示该镜的产物、失败原因与提示词原文。</div></div>')
    + '</div></section></div>';

  return {
    html,
    mount: (root) => {
      root.querySelectorAll('[data-filter]').forEach((b) => {
        b.onclick = () => { filter = b.dataset.filter; ctx.refresh(); };
      });
      root.querySelectorAll('[data-shot]').forEach((b) => {
        b.onclick = (e) => { e.stopPropagation(); selected = b.dataset.shot; ctx.refresh(); };
      });
      const epSel = root.querySelector('#shotEp');
      if (epSel) epSel.onchange = () => { epFilter = epSel.value; selected = ''; ctx.refresh(); };
      const kw = root.querySelector('#shotKw');
      if (kw) {
        let t = null;
        kw.oninput = () => {
          clearTimeout(t);
          t = setTimeout(() => { keyword = kw.value.trim(); ctx.refresh(); }, 300);
        };
      }
      root.querySelectorAll('[data-retry]').forEach((b) => {
        b.onclick = (e) => {
          e.stopPropagation();
          const s = all.find((x) => x.shot_id === b.dataset.retry);
          if (!s) return;
          openModal({
            title: '续跑这一镜',
            icon: 'alert',
            html: '<div class="cost-line"><span class="k">镜头</span><span class="v mono">' + esc(s.shot_id) + '</span></div>'
              + '<div class="cost-line"><span class="k">批次</span><span class="v mono">' + esc(s.batch || '—') + '（只读）</span></div>'
              + '<div class="cost-line"><span class="k">动作</span><span class="v">复用批次续跑，不重提已成功段</span></div>'
              + '<div class="alert warn" style="margin-top:12px"><span class="nav-ico">' + icon('alert', 14)
              + '</span><div>续跑仍会向云端提交失败的那一段，按平台用量计费（约 31–34 点/段）。'
              + '本版**尚未开放**网页端续跑：请到「任务中心」用原批次续跑，或用命令面板执行。</div></div>',
            foot: '<span class="spacer"></span><button class="btn quiet" data-close="modal">知道了</button>'
          });
        };
      });
      const plan = root.querySelector('#btnPlan');
      if (plan) {
        plan.onclick = () => runAction(ctx, {
          specId: 'video.plan', title: '出片计划（不提交、不花钱）', params: epFilter ? { only: epFilter } : {}
        });
      }
      const g10 = root.querySelector('#btnCheckG10');
      if (g10) {
        g10.onclick = () => runAction(ctx, {
          specId: 'workflow.check', title: '前置环节校验（G10）', params: { stage: 'S6' }
        });
      }
      const ing = root.querySelector('#btnIngest');
      if (ing) {
        ing.onclick = () => {
          if (!epFilter) { toast('先在右侧选一个集号，再跑入门口禁', 'warn'); return; }
          runAction(ctx, { specId: 'ingest.check', title: '入门口禁（' + epFilter + '）', params: { ep: epFilter } });
        };
      }
      if (sel) loadPrompt(root, ctx, sel.shot_id);
    }
  };
}

async function loadPrompt(root, ctx, shot) {
  const box = root.querySelector('#promptBox');
  if (!box) return;
  try {
    const res = await api.prompt(ctx.ws, shot).catch(() => ({ ok: false, reason: 'error' }));
    if (!res || !res.ok) {
      box.innerHTML = '<div class="alert info"><span class="nav-ico">' + icon('alert', 14) + '</span>'
        + '<div>' + (res && res.reason === 'no_prompts' ? '工作区还没有 h3_prompts.json（提示词未生成）。'
          : '这一镜没有提示词记录。') + '</div></div>';
      return;
    }
    const meta = [];
    if (res.duration) meta.push(res.duration + ' 秒');
    if (res.ratio) meta.push(res.ratio);
    if (res.voice) meta.push('音轨 ' + res.voice);
    box.innerHTML = (meta.length ? '<div class="row" style="margin-bottom:8px">'
      + meta.map((m) => badge('muted', m)).join('') + '</div>' : '')
      + '<pre class="log" style="max-height:260px">' + esc(res.prompt) + '</pre>'
      + '<div class="row" style="margin-top:8px"><button class="btn quiet sm" id="btnCopyPrompt">'
      + icon('copy', 12) + ' 复制提示词</button>'
      + '<span class="tiny dim">只读：提示词由分镜阶段产出，网页不提供编辑</span></div>';
    const cp = box.querySelector('#btnCopyPrompt');
    if (cp) cp.onclick = async () => {
      try { await navigator.clipboard.writeText(res.prompt); toast('已复制'); }
      catch (e) { toast('复制失败（浏览器限制）', 'warn'); }
    };
  } catch (e) {
    box.innerHTML = '<div class="alert bad"><span class="nav-ico">' + icon('alert', 14)
      + '</span><div>提示词读取失败：' + esc(e.detail || e.message) + '</div></div>';
  }
}
