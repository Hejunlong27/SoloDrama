/* ============================================================
   graph.js —— 节点画布（可拖、可缩放、可连线）

   一张图，两种模式
   ----------------
   流水线模式：节点按依赖自动排成左→右的列，实线就是引擎依赖（带锁）。
   精细化模式：拖到任意位置、自己加连线，表达「我习惯这样走」。

   两条铁律（写在界面上，不只写在注释里）
   --------------------------------------
   1. **实线不可删**：它是引擎强制依赖（没有分镜图就出片 = 白烧 GPU）。
      要表达别的顺序请加虚线；执行顺序仍以引擎为准。
   2. **状态只认磁盘**：节点上的 13/13 是磁盘上的产物，不是「跑过没」。
      门禁没通过但产物齐的节点会显示成完成 + 一个琥珀小点（判据未过），
      因为真实项目常常是人工跑出来的，没有 `_done/*.json` 标记。

   为什么用 DOM 而不是 canvas 2D
   -----------------------------
   节点里要能直接放按钮、进度条、tooltip；canvas 2D 得自己实现命中测试与文字换行。
   一屏 < 60 个节点，DOM + transform 完全够用（与 `docs/CANVAS-PLAN.md` 的选型一致）。
   ============================================================ */
import { api } from '../api.js';
import {
  esc, icon, badge, toast, openDrawer, openModal, closeModal, dt
} from '../ui.js';
import { runAction } from '../action.js';

const NW = 214;          /* 节点宽 */
const NH = 96;           /* 节点高 */
const MIN_S = 0.35;
const MAX_S = 2.0;

let G = null;            /* 服务端返回的图 */
let view = { x: 40, y: 40, scale: 1 };
let epSel = '';
let saveTimer = 0;
let pending = {};        /* 待保存的坐标 */
let drag = null;
let wired = false;       /* 事件是否已绑（重渲染后不需要重绑） */

/* ---------- 坐标换算 ---------- */
function toWorld(host, clientX, clientY) {
  const r = host.getBoundingClientRect();
  return {
    x: (clientX - r.left - view.x) / view.scale,
    y: (clientY - r.top - view.y) / view.scale
  };
}

function applyView() {
  const w = document.getElementById('gnWorld');
  if (w) w.style.transform = 'translate(' + view.x + 'px,' + view.y + 'px) scale(' + view.scale + ')';
  const host = document.getElementById('gnHost');
  if (host) {
    host.style.backgroundPosition = view.x + 'px ' + view.y + 'px';
    host.style.backgroundSize = (24 * view.scale) + 'px ' + (24 * view.scale) + 'px';
  }
  const z = document.getElementById('gnZoom');
  if (z) z.textContent = Math.round(view.scale * 100) + '%';
  drawEdges();
}

function nodeOf(id) {
  return (G.nodes || []).find((n) => n.id === id);
}

/* ---------- 连线 ---------- */
function portOut(n) { return { x: n.x + NW, y: n.y + NH / 2 }; }
function portIn(n) { return { x: n.x, y: n.y + NH / 2 }; }

function pathOf(a, b) {
  const dx = Math.max(36, Math.abs(b.x - a.x) * 0.45);
  return 'M' + a.x + ',' + a.y + ' C' + (a.x + dx) + ',' + a.y + ' '
    + (b.x - dx) + ',' + b.y + ' ' + b.x + ',' + b.y;
}

function drawEdges() {
  const svg = document.getElementById('gnEdges');
  if (!svg || !G) return;
  let html = '';
  (G.edges || []).forEach((e, i) => {
    const a = nodeOf(e.from);
    const b = nodeOf(e.to);
    if (!a || !b) return;
    html += '<path class="gn-e ' + (e.kind === 'user' ? 'user' : 'dep') + '" d="'
      + pathOf(portOut(a), portIn(b)) + '" data-edge="' + i + '"></path>';
  });
  /* 正在拖出来的那条线 */
  if (drag && drag.type === 'edge' && drag.cur) {
    const a = nodeOf(drag.from);
    if (a) html += '<path class="gn-e temp" d="' + pathOf(portOut(a), drag.cur) + '"></path>';
  }
  svg.innerHTML = html;
  svg.querySelectorAll('[data-edge]').forEach((p) => {
    p.onclick = () => {
      const e = (G.edges || [])[Number(p.dataset.edge)];
      if (!e) return;
      askRemoveEdge(e);
    };
  });
}

function askRemoveEdge(e) {
  const a = nodeOf(e.from);
  const b = nodeOf(e.to);
  const name = (a ? a.title : e.from) + ' → ' + (b ? b.title : e.to);
  if (e.kind !== 'user') {
    openModal({
      title: '这条线不能删',
      icon: 'lock',
      html: '<div class="alert info"><span class="nav-ico">' + icon('alert', 14) + '</span><div>'
        + '<b>' + esc(name) + '</b> 是引擎的强制依赖。<br>没有上游产物就跑下游，'
        + '结果是白烧 GPU（出片一次几十分钟）。<br><br>'
        + '要表达「我习惯这样走」，请从节点右侧圆点拖一条<b>虚线</b>出来 —— '
        + '虚线只表达编排意图，不会改变执行顺序。</div></div>',
      foot: '<span class="spacer"></span><button class="btn quiet" data-close="modal">知道了</button>'
    });
    return;
  }
  openModal({
    title: '删掉这条编排线',
    icon: 'alert',
    html: '<div class="cost-line"><span class="k">连线</span><span class="v">' + esc(name) + '</span></div>'
      + '<div class="tiny dim" style="margin-top:8px">只删视觉上的编排关系，不动任何文件与执行顺序。</div>',
    foot: '<span class="spacer"></span><button class="btn quiet" data-close="modal">取消</button>'
      + '<button class="btn primary" id="gnDelEdge">删除</button>',
    mount: (m) => {
      m.querySelector('#gnDelEdge').onclick = async () => {
        try {
          await api.graphEdge({ ws: window.__gnWs, from: e.from, to: e.to, action: 'remove' });
          closeModal();
          await reload();
        } catch (err) { toast('删除失败：' + (err.detail || err.message), 'bad'); }
      };
    }
  });
}

/* ---------- 节点内容 ---------- */
function nodeHtml(n) {
  const tone = n.state === 'done' ? 'done' : n.state === 'doing' ? 'doing' : 'todo';
  const p = n.progress;
  const pct = p && p.total ? Math.round(p.done / p.total * 100) : 0;
  const right = p ? (p.done + '/' + p.total) : (n.state === 'done' ? '已完成' : '');
  const warn = n.state === 'done' && n.gate_ok === false;
  return '<div class="gn ' + tone + ' k-' + esc(n.kind) + '" data-id="' + esc(n.id) + '"'
    + ' style="transform:translate(' + n.x + 'px,' + n.y + 'px)"'
    + ' title="' + esc((n.title || n.id) + (n.note ? '\n' + n.note : '')) + '">'
    + '<div class="gn-h"><i class="dot ' + tone + '"></i><span class="gn-t">' + esc(n.title) + '</span>'
    + (warn ? '<i class="gn-warn" title="' + esc(n.note || '判据未通过') + '"></i>' : '')
    + '<span class="spacer"></span>'
    + (n.cmd || n.create_stage
      ? '<button class="gn-run" data-run="' + esc(n.id) + '" title="运行这一步">' + icon('play', 12) + '</button>'
      : '')
    + '</div>'
    + '<div class="gn-s">' + esc(n.hint || n.detail || '') + '</div>'
    + '<div class="gn-f"><span class="mono tiny">' + esc(right) + '</span>'
    + (n.ep ? '<span class="gn-tag">按集</span>' : '')
    + '</div>'
    + '<div class="gn-bar"><i style="width:' + pct + '%"></i></div>'
    + '<span class="gn-port in" data-port="in" data-node="' + esc(n.id) + '"></span>'
    + '<span class="gn-port out" data-port="out" data-node="' + esc(n.id) + '"></span>'
    + '</div>';
}

/* ---------- 页面 ---------- */
export async function render(ctx) {
  window.__gnWs = ctx.ws;
  const [d, series] = await Promise.all([
    api.graph(ctx.ws, epSel),
    api.canvasSeries(ctx.ws).catch(() => ({ rows: [] }))
  ]);
  G = d;
  if (!epSel) epSel = d.ep;
  view = {
    x: Number((d.view || {}).x) || 40,
    y: Number((d.view || {}).y) || 40,
    scale: Number((d.view || {}).scale) || 1
  };
  const eps = (series.rows || []).filter((r) => r.counts && r.counts.total).map((r) => r.ep);
  const c = d.counts || {};

  const legend = '<span class="gn-lg"><i class="gn-line dep"></i>引擎依赖（不可删）</span>'
    + '<span class="gn-lg"><i class="gn-line user"></i>编排意图（可删）</span>'
    + '<span class="gn-lg"><i class="gn-dot done"></i>产物齐</span>'
    + '<span class="gn-lg"><i class="gn-dot todo"></i>未开始</span>'
    + '<span class="gn-lg"><i class="gn-warn"></i>判据未过</span>';

  const html = ''
    + '<div class="page-head"><div>'
    + '<div class="crumb"><b>当前项目</b><span class="sep">/</span><b>'
    + esc(ctx.project ? (ctx.project.title || ctx.project.path) : ctx.ws) + '</b></div>'
    + '<h1 class="page-title">画布</h1>'
    + '<div class="page-sub">拖动节点摆位置 · 滚轮缩放 · 从右侧圆点拖到左侧圆点连线。'
    + '状态只认磁盘产物，不看「跑过没」。</div></div>'
    + '<div class="page-actions">'
    + (eps.length ? '<select class="select" id="gnEp" style="width:104px">'
      + eps.map((e) => '<option value="' + esc(e) + '"' + (e === d.ep ? ' selected' : '') + '>'
        + esc(e) + '</option>').join('') + '</select>' : '')
    + '<div class="seg" id="gnMode">'
    + '<button class="active" data-mode="graph">节点画布</button>'
    + '<button data-mode="grid">全季网格</button></div>'
    + '<button class="btn quiet" id="gnFit">' + icon('search', 14) + ' 适应窗口</button>'
    + '<button class="btn quiet" id="gnReset">' + icon('refresh', 14) + ' 自动排布</button>'
    + '</div></div>'

    + '<div class="row gn-stats">'
    + '<span class="chip">节点 ' + c.total + '</span>'
    + '<span class="chip' + (c.done === c.total ? ' on' : '') + '">产物齐 ' + c.done + '</span>'
    + '<span class="chip">未开始 ' + c.todo + '</span>'
    + '<span class="chip">连线 ' + (d.edges || []).length + '</span>'
    + '<span class="spacer"></span>' + legend + '</div>'

    + '<div class="card"><div class="gn-wrap">'
    + '<div class="gn-host" id="gnHost">'
    + '<div class="gn-world" id="gnWorld">'
    + '<svg class="gn-edges" id="gnEdges"></svg>'
    + (d.nodes || []).map(nodeHtml).join('')
    + '</div></div>'
    + '<div class="gn-zoom"><button class="btn quiet sm" id="gnZoomOut">−</button>'
    + '<span id="gnZoom" class="mono tiny">100%</span>'
    + '<button class="btn quiet sm" id="gnZoomIn">+</button></div>'
    + '<div class="gn-hint">拖背景平移 · 滚轮缩放 · 点节点看详情 · 点虚线删除</div>'
    + '</div><div class="card-foot">'
    + '<span class="tiny dim">' + esc(d.note || '') + '</span><span class="spacer"></span>'
    + '<button class="btn ghost sm" id="gnToPipe">按顺序连跑（流水线）</button>'
    + '</div></div>';

  return {
    html,
    mount: (root) => { mount(root, ctx, d, eps); }
  };
}

function mount(root, ctx, d, eps) {
  const host = root.querySelector('#gnHost');
  applyView();
  bindOnce(root, ctx);

  /* 节点单击 → 详情（拖拽超过 3px 不算点击） */
  root.querySelectorAll('.gn').forEach((el) => {
    el.addEventListener('pointerdown', (ev) => onNodeDown(ev, el, host));
    el.addEventListener('click', (ev) => {
      if (el.dataset.moved === '1') { el.dataset.moved = ''; return; }
      if (ev.target.closest('.gn-run') || ev.target.closest('.gn-port')) return;
      openNode(ctx, el.dataset.id);
    });
  });
  root.querySelectorAll('[data-run]').forEach((b) => {
    b.onclick = (ev) => {
      ev.stopPropagation();
      runNode(ctx, b.dataset.run);
    };
  });
  root.querySelectorAll('.gn-port.out').forEach((p) => {
    p.addEventListener('pointerdown', (ev) => {
      ev.stopPropagation();
      drag = { type: 'edge', from: p.dataset.node, cur: null };
      host.setPointerCapture(ev.pointerId);
    });
  });

  const epSelEl = root.querySelector('#gnEp');
  if (epSelEl) epSelEl.onchange = () => { epSel = epSelEl.value; ctx.refresh(); };

  root.querySelectorAll('[data-mode]').forEach((b) => {
    b.onclick = () => {
      if (b.dataset.mode === 'grid') { ctx.navigate('canvas'); return; }
    };
  });
  const fit = root.querySelector('#gnFit');
  if (fit) fit.onclick = () => fitView(host);
  const reset = root.querySelector('#gnReset');
  if (reset) {
    reset.onclick = async () => {
      try {
        await api.graphReset(ctx.ws);
        toast('已恢复自动排布');
        ctx.refresh();
      } catch (e) { toast('重置失败：' + (e.detail || e.message), 'bad'); }
    };
  }
  const zin = root.querySelector('#gnZoomIn');
  if (zin) zin.onclick = () => zoomBy(1.2, host);
  const zout = root.querySelector('#gnZoomOut');
  if (zout) zout.onclick = () => zoomBy(1 / 1.2, host);
  const pipe = root.querySelector('#gnToPipe');
  if (pipe) pipe.onclick = () => ctx.navigate('pipeline');

  drawEdges();
  if (d.counts && d.counts.total) fitView(host, true);
}

/* 只绑一次：视图会被 ctx.refresh 重建，但 host 是新元素，事件跟着新元素走 */
function bindOnce(root, ctx) {
  const host = root.querySelector('#gnHost');
  if (!host) return;

  host.addEventListener('pointerdown', (ev) => {
    if (ev.target.closest('.gn')) return;
    drag = { type: 'pan', sx: ev.clientX, sy: ev.clientY, ox: view.x, oy: view.y };
    host.setPointerCapture(ev.pointerId);
    host.classList.add('grabbing');
  });

  host.addEventListener('pointermove', (ev) => {
    if (!drag) return;
    if (drag.type === 'pan') {
      view.x = drag.ox + (ev.clientX - drag.sx);
      view.y = drag.oy + (ev.clientY - drag.sy);
      applyView();
      return;
    }
    if (drag.type === 'node') {
      const w = toWorld(host, ev.clientX, ev.clientY);
      const nx = Math.round(w.x - drag.dx);
      const ny = Math.round(w.y - drag.dy);
      if (Math.abs(nx - drag.x0) > 3 || Math.abs(ny - drag.y0) > 3) drag.el.dataset.moved = '1';
      drag.el.style.transform = 'translate(' + nx + 'px,' + ny + 'px)';
      drag.x = nx;
      drag.y = ny;
      overlayEdges(drag.id, nx, ny);
      return;
    }
    if (drag.type === 'edge') {
      drag.cur = toWorld(host, ev.clientX, ev.clientY);
      drawEdges();
    }
  });

  const finish = async (ev) => {
    if (!drag) return;
    const d0 = drag;
    drag = null;
    host.classList.remove('grabbing');
    if (d0.type === 'node') {
      const n = nodeOf(d0.id);
      if (n) { n.x = d0.x; n.y = d0.y; }
      pending[d0.id] = { x: d0.x, y: d0.y };
      scheduleSave(ctx);
    }
    if (d0.type === 'edge') {
      drawEdges();
      const el = document.elementFromPoint(ev.clientX, ev.clientY);
      const port = el && el.closest ? el.closest('.gn-port.in') : null;
      if (port && port.dataset.node && port.dataset.node !== d0.from) {
        try {
          const r = await api.graphEdge({ ws: ctx.ws, from: d0.from, to: port.dataset.node, action: 'add' });
          if (!r.ok) toast(r.detail || '这条线加不上', 'warn');
          await reload(ctx);
        } catch (err) { toast('连线失败：' + (err.detail || err.message), 'bad'); }
      }
    }
    if (d0.type === 'pan') scheduleSave(ctx, true);
  };
  host.addEventListener('pointerup', finish);
  host.addEventListener('pointercancel', () => { drag = null; host.classList.remove('grabbing'); });

  host.addEventListener('wheel', (ev) => {
    ev.preventDefault();
    const r = host.getBoundingClientRect();
    const mx = ev.clientX - r.left;
    const my = ev.clientY - r.top;
    const k = ev.deltaY < 0 ? 1.12 : 1 / 1.12;
    const next = Math.min(MAX_S, Math.max(MIN_S, view.scale * k));
    if (next === view.scale) return;
    /* 以光标为锚点缩放：位置 = 光标 - (光标 - 旧位置) * 比例 */
    view.x = mx - (mx - view.x) * (next / view.scale);
    view.y = my - (my - view.y) * (next / view.scale);
    view.scale = next;
    applyView();
    scheduleSave(ctx, true);
  }, { passive: false });
}

function onNodeDown(ev, el, host) {
  if (ev.target.closest('.gn-port') || ev.target.closest('.gn-run')) return;
  const id = el.dataset.id;
  const n = nodeOf(id);
  if (!n) return;
  const w = toWorld(host, ev.clientX, ev.clientY);
  drag = { type: 'node', id, el, dx: w.x - n.x, dy: w.y - n.y, x0: n.x, y0: n.y, x: n.x, y: n.y };
  host.setPointerCapture(ev.pointerId);
  el.classList.add('dragging');
  el.dataset.moved = '';
  setTimeout(() => el.classList.remove('dragging'), 400);
}

/* 拖节点时只重画与它相关的线，整层重绘会闪 */
function overlayEdges(id, x, y) {
  const svg = document.getElementById('gnEdges');
  if (!svg) return;
  svg.querySelectorAll('path.gn-e').forEach((p, i) => {
    const e = (G.edges || [])[Number(p.dataset.edge)];
    if (!e || (e.from !== id && e.to !== id)) return;
    const a = nodeOf(e.from);
    const b = nodeOf(e.to);
    if (!a || !b) return;
    const pa = e.from === id ? { x: x + NW, y: y + NH / 2 } : portOut(a);
    const pb = e.to === id ? { x: x, y: y + NH / 2 } : portIn(b);
    p.setAttribute('d', pathOf(pa, pb));
  });
}

function scheduleSave(ctx, now) {
  clearTimeout(saveTimer);
  const go = async () => {
    const pos = pending;
    pending = {};
    if (!Object.keys(pos).length) return;
    try {
      await api.graphLayout({ ws: ctx.ws, pos, view: { x: view.x, y: view.y, scale: view.scale } });
    } catch (e) { /* 保存失败不打断操作，下次拖动会再存 */ }
  };
  saveTimer = setTimeout(go, now ? 120 : 700);
}

async function reload(ctx) {
  try {
    const d = await api.graph(ctx.ws, epSel);
    G = d;
    const root = document.getElementById('view');
    const host = root.querySelector('#gnHost');
    if (!host) return;
    /* 只换世界层，不重建整页（否则视口位置会跳） */
    const world = root.querySelector('#gnWorld');
    world.querySelectorAll('.gn').forEach((el) => el.remove());
    world.insertAdjacentHTML('beforeend', (d.nodes || []).map(nodeHtml).join(''));
    root.querySelectorAll('.gn').forEach((el) => {
      el.addEventListener('pointerdown', (ev) => onNodeDown(ev, el, host));
      el.addEventListener('click', (ev) => {
        if (el.dataset.moved === '1') { el.dataset.moved = ''; return; }
        if (ev.target.closest('.gn-run') || ev.target.closest('.gn-port')) return;
        openNode(ctx, el.dataset.id);
      });
    });
    root.querySelectorAll('[data-run]').forEach((b) => {
      b.onclick = (ev) => { ev.stopPropagation(); runNode(ctx, b.dataset.run); };
    });
    root.querySelectorAll('.gn-port.out').forEach((p) => {
      p.addEventListener('pointerdown', (ev) => {
        ev.stopPropagation();
        drag = { type: 'edge', from: p.dataset.node, cur: null };
        host.setPointerCapture(ev.pointerId);
      });
    });
    drawEdges();
  } catch (e) { toast('刷新画布失败：' + (e.detail || e.message), 'bad'); }
}

function fitView(host, silent) {
  if (!G || !G.nodes || !G.nodes.length) return;
  const w = host.clientWidth || 900;
  const h = host.clientHeight || 520;
  const xs = G.nodes.map((n) => n.x);
  const ys = G.nodes.map((n) => n.y);
  const minX = Math.min(...xs) - 20;
  const minY = Math.min(...ys) - 20;
  const maxX = Math.max(...xs) + NW + 20;
  const maxY = Math.max(...ys) + NH + 20;
  const s = Math.min(1.1, Math.min(w / (maxX - minX), h / (maxY - minY)));
  view.scale = Math.max(MIN_S, Math.min(MAX_S, s));
  view.x = Math.round((w - (maxX - minX) * view.scale) / 2 - minX * view.scale);
  view.y = Math.round((h - (maxY - minY) * view.scale) / 2 - minY * view.scale);
  applyView();
  if (!silent) scheduleSave({ ws: window.__gnWs }, true);
}

function zoomBy(k, host) {
  const w = host.clientWidth || 900;
  const h = host.clientHeight || 520;
  const next = Math.min(MAX_S, Math.max(MIN_S, view.scale * k));
  view.x = w / 2 - (w / 2 - view.x) * (next / view.scale);
  view.y = h / 2 - (h / 2 - view.y) * (next / view.scale);
  view.scale = next;
  applyView();
  scheduleSave({ ws: window.__gnWs }, true);
}

/* ---------- 节点详情 / 运行 ---------- */
function openNode(ctx, id) {
  const n = nodeOf(id);
  if (!n) return;
  const p = n.progress;
  const meta = [];
  if (n.state === 'done') meta.push(badge('ok', '产物齐'));
  else if (n.gate_ok) meta.push(badge('ok', '判据通过'));
  else meta.push(badge('outline', '未开始'));
  if (n.gate) meta.push(badge(n.gate === 'passed' ? 'ok' : 'muted', '判据 ' + n.gate));
  if (n.ep) meta.push(badge('muted', '按集'));

  const kv = '<dl class="kv">'
    + '<dt>节点</dt><dd class="mono">' + esc(n.id) + '</dd>'
    + '<dt>环节</dt><dd>' + esc(n.stage || '—') + '</dd>'
    + '<dt>产物</dt><dd class="mono">' + esc(n.output || '—') + '</dd>'
    + '<dt>进度</dt><dd>' + esc(p ? (p.done + ' / ' + p.total) : '未统计') + '</dd>'
    + '<dt>入口</dt><dd class="mono">' + esc(n.cmd || n.create_stage || '—') + '</dd>'
    + '</dl>';

  const upstream = (G.edges || []).filter((e) => e.to === id).map((e) => nodeOf(e.from)).filter(Boolean);
  const downstream = (G.edges || []).filter((e) => e.from === id).map((e) => nodeOf(e.to)).filter(Boolean);
  const links = (arr, cls) => arr.length
    ? '<div class="row" style="flex-wrap:wrap;gap:6px">' + arr.map((x) =>
      '<span class="chip ' + cls + '">' + esc(x.title) + '</span>').join('') + '</div>'
    : '<span class="tiny dim">无</span>';

  openDrawer({
    title: n.title + '（' + n.id + '）',
    html: '<div class="stack">'
      + '<div class="row" style="flex-wrap:wrap">' + meta.join('') + '</div>'
      + (n.note ? '<div class="alert warn"><span class="nav-ico">' + icon('alert', 14) + '</span><div>'
        + esc(n.note) + '</div></div>' : '')
      + '<div><div class="tiny dim" style="margin-bottom:6px">这一步做什么</div>'
      + '<div class="small">' + esc(n.hint || '—') + '</div></div>'
      + (n.detail ? '<div class="log" style="max-height:120px">' + esc(n.detail) + '</div>' : '')
      + kv
      + '<div><div class="tiny dim" style="margin-bottom:6px">上游（必须先有）</div>' + links(upstream, '') + '</div>'
      + '<div><div class="tiny dim" style="margin-bottom:6px">下游（会用到它）</div>' + links(downstream, '') + '</div>'
      + '</div>',
    foot: '<span class="spacer"></span>'
      + '<button class="btn quiet" data-close="drawer">关闭</button>'
      + (n.cmd || n.create_stage
        ? '<button class="btn primary" id="gnRun2">' + icon('play', 14) + ' 运行这一步</button>'
        : ''),
    mount: (m) => {
      const b = m.querySelector('#gnRun2');
      if (b) b.onclick = () => { runNode(ctx, id); };
    }
  });
}

function runNode(ctx, id) {
  const n = nodeOf(id);
  if (!n) return;
  if (n.create_stage) {
    /* 创作侧是「调模型」，不是引擎命令：按钮跳到创作页，那里有完整的前置校验 */
    toast('创作类节点在「创作」页运行（它要带上下文与画风锁）', 'warn');
    ctx.navigate('create');
    return;
  }
  if (!n.cmd) return;
  runAction(ctx, {
    specId: n.cmd,
    title: n.title + '（' + n.id + '）',
    params: n.ep ? { ep: G.ep } : {},
    onDone: () => setTimeout(() => reload(ctx), 1200)
  });
}
