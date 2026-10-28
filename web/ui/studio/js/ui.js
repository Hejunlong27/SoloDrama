/* ============================================================
   ui.js —— 通用组件与格式化（无框架，纯 DOM）
   纪律：图标一律内联 SVG（不用 emoji/CDN）；浮层同一时刻只开一层。
   ============================================================ */

/* ---------- 图标 ---------- */
const ICONS = {
  workbench: 'M3 3h7v7H3zM14 3h7v4h-7zM14 10h7v11h-7zM3 13h7v8H3z',
  folder: 'M3 6a2 2 0 012-2h4l2 2h8a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2z',
  list: 'M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01',
  coins: 'M12 3c4.97 0 9 1.79 9 4s-4.03 4-9 4-9-1.79-9-4 4.03-4 9-4zM3 7v10c0 2.21 4.03 4 9 4s9-1.79 9-4V7',
  settings: 'M12 15a3 3 0 100-6 3 3 0 000 6zM4 12H2M22 12h-2M12 4V2M12 22v-2M5.6 5.6L4.2 4.2M19.8 19.8l-1.4-1.4M18.4 5.6l1.4-1.4M4.2 19.8l1.4-1.4',
  layers: 'M12 3l9 5-9 5-9-5zM3 13l9 5 9-5',
  spark: 'M12 3l2.2 5.8L20 11l-5.8 2.2L12 19l-2.2-5.8L4 11l5.8-2.2z',
  image: 'M3 4h18v16H3zM8.5 10a1.5 1.5 0 100-3 1.5 1.5 0 000 3zM21 16l-5-5-6 6',
  film: 'M3 4h18v16H3zM7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4',
  scissors: 'M6 3l12 12M6 21L18 9M9 6a3 3 0 11-6 0 3 3 0 016 0zM9 18a3 3 0 11-6 0 3 3 0 016 0z',
  upload: 'M12 21V9M7 13l5-5 5 5M4 3h16',
  close: 'M6 6l12 12M18 6L6 18',
  chevron: 'M6 9l6 6 6-6',
  refresh: 'M21 12a9 9 0 11-3-6.7M21 3v6h-6',
  alert: 'M12 9v5M12 17.5h.01M10.3 4.2L2.6 17.8A2 2 0 004.3 21h15.4a2 2 0 001.7-3.2L13.7 4.2a2 2 0 00-3.4 0z',
  check: 'M4 12.5l5 5L20 6.5',
  play: 'M6 4l14 8-14 8z',
  search: 'M11 19a8 8 0 100-16 8 8 0 000 16zM21 21l-4.6-4.6',
  terminal: 'M4 5h16v14H4zM8 10l2 2-2 2M13 14h4',
  cpu: 'M6 6h12v12H6zM10 10h4v4h-4zM9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3',
  clock: 'M12 21a9 9 0 100-18 9 9 0 000 18zM12 7v5l3 2',
  lock: 'M5 11h14v10H5zM8 11V7a4 4 0 018 0v4',
  copy: 'M9 9h10v10H9zM5 15V5h10',
  download: 'M12 3v12M7 11l5 5 5-5M4 21h16',
  collapse: 'M4 4h16v16H4zM9 4v16M15 9l-3 3 3 3',
  play2: 'M8 5l11 7-11 7z',
  plus: 'M12 5v14M5 12h14',
  external: 'M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 01-1 1H5a1 1 0 01-1-1V7a1 1 0 011-1h5',
  plug: 'M9 3v6M15 3v6M7 9h10v3a5 5 0 01-10 0zM12 17v4'
};

export function icon(name, size) {
  const d = ICONS[name] || ICONS.alert;
  const s = size || 16;
  return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 24 24" fill="none" stroke="currentColor"'
    + ' stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="' + d + '"/></svg>';
}

export function paintIcons(root) {
  (root || document).querySelectorAll('[data-ico]').forEach((el) => {
    if (el.dataset.painted) return;
    el.innerHTML = icon(el.dataset.ico, el.dataset.size ? Number(el.dataset.size) : 16);
    el.dataset.painted = '1';
  });
}

/* ---------- 转义与格式化 ---------- */
export function esc(s) {
  return String(s === undefined || s === null ? '' : s).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

const COIN_TO_CNY = 0.0025;   /* 1 RH 点 ≈ ¥0.0025（引擎与旧控制台同一口径） */
export const RATE = { coinToCny: COIN_TO_CNY, usdToCny: 7.2 };

export function money(v) {
  const n = Number(v);
  if (!isFinite(n)) return '—';
  if (n === 0) return '¥0';
  if (n < 100) return '¥' + n.toFixed(2);
  return '¥' + Math.round(n).toLocaleString('zh-CN');
}

export function coins(v) {
  const n = Number(v);
  if (!isFinite(n)) return '—';
  return n.toLocaleString('zh-CN', { maximumFractionDigits: 1 });
}

export function bytes(v) {
  const n = Number(v);
  if (!isFinite(n) || n <= 0) return '—';
  if (n < 1024) return n + ' B';
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
  if (n < 1024 * 1024 * 1024) return (n / 1048576).toFixed(1) + ' MB';
  return (n / 1073741824).toFixed(2) + ' GB';
}

export function dt(v) {
  if (!v) return '—';
  if (typeof v === 'number') {
    const d = new Date(v * 1000);
    return pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  }
  const s = String(v).replace('T', ' ');
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})[ ]?(\d{2}:\d{2})?/);
  return m ? (m[2] + '-' + m[3] + (m[4] ? ' ' + m[4] : '')) : String(v);
}

function pad(n) { return (n < 10 ? '0' : '') + n; }

export function ago(ts) {
  if (!ts) return '—';
  const s = Math.max(0, Math.floor(Date.now() / 1000 - Number(ts)));
  if (s < 60) return s + ' 秒前';
  if (s < 3600) return Math.floor(s / 60) + ' 分钟前';
  if (s < 86400) return Math.floor(s / 3600) + ' 小时前';
  return Math.floor(s / 86400) + ' 天前';
}

/* ---------- 状态 ---------- */
const STATE_TEXT = {
  done: '已完成', doing: '进行中', fail: '失败', todo: '未开始', confirm: '待确认', gate: '需修复'
};

export function stateText(s) { return STATE_TEXT[s] || s || '—'; }

export function stateEl(state, text) {
  const cls = ['done', 'doing', 'fail', 'todo', 'confirm'].indexOf(state) >= 0 ? state : 'todo';
  const dot = state === 'gate' ? 'fail' : cls;
  return '<span class="state ' + cls + '"><i class="dot ' + dot + '"></i>' + esc(text || stateText(state)) + '</span>';
}

export function dot(state) {
  const cls = ['done', 'doing', 'fail', 'todo', 'confirm'].indexOf(state) >= 0 ? state : 'todo';
  return '<i class="dot ' + cls + '"></i>';
}

export function badge(tone, text, title) {
  const t = tone || 'muted';
  return '<span class="badge ' + t + '"' + (title ? ' title="' + esc(title) + '"' : '') + '>' + esc(text) + '</span>';
}

/* ---------- Toast ---------- */
export function toast(text, tone) {
  const box = document.getElementById('toasts');
  const el = document.createElement('div');
  el.className = 'toast ' + (tone || 'ok');
  el.innerHTML = '<span class="nav-ico">' + icon(tone === 'bad' ? 'alert' : tone === 'warn' ? 'alert' : 'check', 14) + '</span>'
    + '<span>' + esc(text) + '</span>';
  box.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; setTimeout(() => el.remove(), 220); }, 3600);
}

/* ---------- 浮层 ---------- */
const scrim = () => document.getElementById('scrim');

export function closeDrawer() {
  const d = document.getElementById('drawer');
  const was = d.classList.contains('on');
  d.classList.remove('on');
  d.setAttribute('aria-hidden', 'true');
  if (!document.getElementById('modal').classList.contains('on')) scrim().classList.remove('on');
  /* 让订阅 SSE 的页面有机会断开连接（否则关掉抽屉后仍在收事件） */
  if (was) window.dispatchEvent(new CustomEvent('studio:drawer-closed'));
}

export function openDrawer(opts) {
  const d = document.getElementById('drawer');
  document.getElementById('drawerTitle').textContent = opts.title || '详情';
  document.getElementById('drawerBody').innerHTML = opts.html || '';
  document.getElementById('drawerFoot').innerHTML = opts.foot || '';
  paintIcons(d);
  d.classList.add('on');
  d.setAttribute('aria-hidden', 'false');
  scrim().classList.add('on');
  document.getElementById('drawerBody').scrollTop = 0;
  if (opts.mount) opts.mount(d);
  return d;
}

export function closeModal() {
  const m = document.getElementById('modal');
  m.classList.remove('on');
  m.setAttribute('aria-hidden', 'true');
  if (!document.getElementById('drawer').classList.contains('on')) scrim().classList.remove('on');
}

export function openModal(opts) {
  const m = document.getElementById('modal');
  document.getElementById('modalTitle').textContent = opts.title || '确认';
  document.getElementById('modalIcon').innerHTML = icon(opts.icon || 'alert', 18);
  document.getElementById('modalIcon').style.color = opts.tone === 'bad' ? 'var(--danger)'
    : opts.tone === 'ok' ? 'var(--ok)' : 'var(--accent)';
  document.getElementById('modalBody').innerHTML = opts.html || '';
  document.getElementById('modalFoot').innerHTML = opts.foot || '';
  paintIcons(m);
  m.classList.add('on');
  m.setAttribute('aria-hidden', 'false');
  scrim().classList.add('on');
  if (opts.mount) opts.mount(m);
  return m;
}

/* 计费确认单：必须先勾选「确认会产生费用」才能继续（沿用旧控制台的门禁语义） */
export function confirmCost(opts) {
  const lines = (opts.lines || []).map(([k, v]) => (
    '<div class="cost-line"><span class="k">' + esc(k) + '</span><span class="v">' + esc(v) + '</span></div>'
  )).join('');
  openModal({
    title: opts.title || '确认会产生费用',
    icon: 'alert',
    html: lines
      + (opts.total ? '<div class="cost-line total"><span class="k">预估合计</span><span class="v">'
        + esc(opts.total) + '</span></div>' : '')
      + (opts.note ? '<div class="alert warn" style="margin-top:12px"><span class="nav-ico">' + icon('alert', 14)
        + '</span><div>' + esc(opts.note) + '</div></div>' : '')
      + '<label class="chk" style="margin-top:14px"><input type="checkbox" id="costAck">'
      + '<span>我确认这会产生<b>真实费用</b>；重跑已成功的部分会重复扣费，续跑不会。</span></label>',
    foot: '<span class="spacer"></span>'
      + '<button class="btn quiet" data-close="modal">取消</button>'
      + '<button class="btn primary" id="costOk" disabled>确认并开始</button>',
    mount: () => {
      const ack = document.getElementById('costAck');
      const ok = document.getElementById('costOk');
      ack.onchange = () => { ok.disabled = !ack.checked; };
      ok.onclick = () => { closeModal(); opts.onOk(); };
    }
  });
}

/* ---------- 骨架 / 错误 ---------- */
export function skeleton(blocks) {
  const n = blocks || 4;
  let out = '<div class="stack">';
  out += '<div class="skeleton" style="width:220px;height:20px"></div>';
  out += '<div class="grid g4">';
  for (let i = 0; i < 4; i += 1) {
    out += '<div class="kpi"><div class="skeleton" style="width:60px;height:10px"></div>'
      + '<div class="skeleton" style="width:110px;height:22px;margin-top:10px"></div></div>';
  }
  out += '</div>';
  for (let i = 0; i < n; i += 1) {
    out += '<div class="card"><div class="card-b">';
    for (let j = 0; j < 4; j += 1) {
      out += '<div class="skeleton" style="height:12px;margin-bottom:10px;width:'
        + (72 + ((i * 7 + j * 11) % 26)) + '%"></div>';
    }
    out += '</div></div>';
  }
  return out + '</div>';
}

export function errorCard(err, retryLabel) {
  const status = err && err.status;
  const title = status === 403 ? '访问被拒绝' : status === 401 ? '需要访问令牌' : '这一步没有成功';
  return '<div class="card"><div class="card-b">'
    + '<div class="alert bad"><span class="nav-ico">' + icon('alert', 14) + '</span><div>'
    + '<b>' + esc(title) + '</b><br><span class="small">'
    + esc((err && (err.detail || err.message)) || '未知错误') + '</span></div></div>'
    + '<div class="row" style="margin-top:12px">'
    + '<button class="btn quiet" data-retry="1">' + esc(retryLabel || '重试') + '</button>'
    + '<a class="btn ghost" href="../advanced.html" target="_blank" rel="noopener">打开开发者视图</a>'
    + '</div></div></div>';
}

/* ---------- 小部件 ---------- */
export function stamp(text) {
  return '<span class="stamp"><i class="dot todo"></i>' + esc(text) + '</span>';
}

export function kv(rows) {
  return '<dl class="kv">' + rows.map((r) => (
    '<dt>' + esc(r[0]) + '</dt><dd' + (r[2] ? ' class="mono"' : '') + '>' + esc(r[1]) + '</dd>'
  )).join('') + '</dl>';
}

export function emptyBox(title, hint, actionHtml) {
  return '<div class="empty"><div class="empty-t">' + esc(title) + '</div>'
    + (hint ? '<div class="empty-h">' + esc(hint) + '</div>' : '')
    + (actionHtml || '') + '</div>';
}
