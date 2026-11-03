/* ============================================================
   float.js —— 可拖动 / 可缩放的浮动窗口

   为什么需要它
   ------------
   助手是「边看边问」的工具：问「第 3 镜为什么没出片」，眼睛得同时看着分镜页。
   做成整页，就必须在两页之间来回切，切一次丢一次上下文。

   四条实现纪律（都是踩过或者差点踩的）
   ----------------------------------
   1. **窗口只建一次，关闭只是 display:none**。输入框里的草稿、滚到一半的位置都还在。
      整页版每次 render 都重建 DOM —— 这正是「整页」和「浮窗」的真实差别，不是外观。
   2. **位置尺寸落 localStorage，但每次打开都重新夹进视口**。换显示器、改窗口大小之后，
      存下来的坐标可能已经把标题栏丢到屏幕外，那时既拖不动也关不掉。
   3. **最大化对齐内容区，不是整屏**。左侧导航不该被盖住 —— 盖住之后想切页得先关窗口，
      等于逼人二选一，而浮窗的意义恰恰是「两个都要看」。
   4. **拖动与缩放都用 window 上的 pointermove**，不用 setPointerCapture：
      指针移出手柄/标题栏时 capture 在部分浏览器上会丢事件，窗口就「粘」在指针上。
   ============================================================ */
import { esc, icon } from './ui.js';

const REG = {};
const K_STATE = (id) => 'studio.float.' + id;
const K_OPEN = (id) => 'studio.float.' + id + '.open';
const EDGE = 132;          /* 至少露这么多标题栏，保证还能拖回来 */

function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

/* 可用区域 = 内容区（#view）的矩形，不是整个视口。
   这样「最大化」不会盖住左侧导航，也不会跑到顶栏下面。 */
function vp() {
  const v = document.getElementById('view');
  const r = v ? v.getBoundingClientRect() : null;
  if (r && r.width > 320 && r.height > 240) return { x: r.left, y: r.top, w: r.width, h: r.height };
  return { x: 0, y: 0, w: window.innerWidth, h: window.innerHeight };
}

function load(id) {
  try { return JSON.parse(localStorage.getItem(K_STATE(id)) || '{}') || {}; } catch (e) { return {}; }
}

function save(id, st) {
  try { localStorage.setItem(K_STATE(id), JSON.stringify(st)); } catch (e) { /* 隐私模式忽略 */ }
}

function remember(id, on) {
  try { localStorage.setItem(K_OPEN(id), on ? '1' : '0'); } catch (e) { /* ignore */ }
}

export function wasOpen(id) {
  try { return localStorage.getItem(K_OPEN(id)) === '1'; } catch (e) { return false; }
}

export function isOpen(id) {
  const w = REG[id];
  return !!w && w.isOpen();
}

/* ---------------------------------------------------------------------------
   createFloat(opts)
     id      必填，唯一
     title   标题栏文字
     icon    图标名（见 ui.js ICONS）
     bodyHtml / mount(bodyEl)  内容
     width/height/minW/minH    首次尺寸与下限
     onChange(open)            开关回调（用来同步导航高亮等）
   --------------------------------------------------------------------------- */
export function createFloat(o) {
  const id = o.id;
  if (REG[id]) return REG[id];

  const minW = o.minW || 340;
  const minH = o.minH || 300;

  let st = load(id);
  let maxed = false;
  let prev = null;

  const el = document.createElement('div');
  el.className = 'fw hide';
  el.dataset.fw = id;
  el.innerHTML =
    '<div class="fw-h" data-fw-drag>'
    + '<span class="fw-ic">' + icon(o.icon || 'spark', 14) + '</span>'
    + '<span class="fw-t">' + esc(o.title || '') + '</span>'
    + '<span class="fw-sub" data-fw-sub></span>'
    + '<span class="spacer"></span>'
    + '<button class="fw-b" data-fw-max title="铺满内容区（双击标题栏同效）">' + icon('square', 13) + '</button>'
    + '<button class="fw-b" data-fw-close title="关闭（对话记录与草稿都还在）">' + icon('close', 13) + '</button>'
    + '</div>'
    + '<div class="fw-body" data-fw-body></div>'
    + ['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw']
      .map((d) => '<i class="fw-rz" data-rz="' + d + '"></i>').join('');
  document.body.appendChild(el);

  const body = el.querySelector('[data-fw-body]');
  const sub = el.querySelector('[data-fw-sub]');
  const btnMax = el.querySelector('[data-fw-max]');
  body.innerHTML = o.bodyHtml || '';
  if (o.mount) o.mount(body);

  /* ---------- 定位 ---------- */
  function apply() {
    const b = vp();
    let w = clamp(Number(st.w) || o.width || 540, minW, Math.max(minW, b.w - 8));
    let h = clamp(Number(st.h) || o.height || 720, minH, Math.max(minH, b.h - 8));
    let x = Number(st.x);
    let y = Number(st.y);
    if (!isFinite(x) || !isFinite(y)) {          /* 首次：贴内容区右下角 */
      x = b.x + b.w - w - 16;
      y = b.y + b.h - h - 16;
    }
    x = clamp(x, b.x - (w - EDGE), b.x + b.w - EDGE);
    y = clamp(y, b.y, b.y + b.h - 44);
    st = { x: x, y: y, w: w, h: h };
    el.style.left = Math.round(x) + 'px';
    el.style.top = Math.round(y) + 'px';
    el.style.width = Math.round(w) + 'px';
    el.style.height = Math.round(h) + 'px';
  }

  function readBack() {
    const r = el.getBoundingClientRect();
    st = { x: r.left, y: r.top, w: r.width, h: r.height };
  }

  /* ---------- 拖动 ---------- */
  const head = el.querySelector('[data-fw-drag]');
  head.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    if (e.target.closest('button')) return;
    if (maxed) return;                           /* 最大化时拖动无意义，先还原 */
    const b = vp();
    const r = el.getBoundingClientRect();
    const sx = e.clientX;
    const sy = e.clientY;
    el.classList.add('drag');
    const move = (ev) => {
      const nx = clamp(r.left + ev.clientX - sx, b.x - (r.width - EDGE), b.x + b.w - EDGE);
      const ny = clamp(r.top + ev.clientY - sy, b.y, b.y + b.h - 44);
      el.style.left = Math.round(nx) + 'px';
      el.style.top = Math.round(ny) + 'px';
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      el.classList.remove('drag');
      readBack();
      save(id, st);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up, { once: true });
    e.preventDefault();
  });

  head.addEventListener('dblclick', (e) => {
    if (e.target.closest('button')) return;
    toggleMax();
  });

  /* ---------- 缩放（八向） ---------- */
  el.querySelectorAll('[data-rz]').forEach((h) => {
    h.addEventListener('pointerdown', (e) => {
      if (e.button !== 0 || maxed) return;
      const dir = h.dataset.rz;
      const b = vp();
      const r = el.getBoundingClientRect();
      const sx = e.clientX;
      const sy = e.clientY;
      el.classList.add('drag');
      const move = (ev) => {
        const dx = ev.clientX - sx;
        const dy = ev.clientY - sy;
        let { left, top, width, height } = r;
        if (dir.indexOf('e') >= 0) width = r.width + dx;
        if (dir.indexOf('s') >= 0) height = r.height + dy;
        if (dir.indexOf('w') >= 0) { width = r.width - dx; left = r.left + dx; }
        if (dir.indexOf('n') >= 0) { height = r.height - dy; top = r.top + dy; }
        /* 最小尺寸：从左上方向缩到下限时，边要顶住而不是继续跑 */
        if (width < minW) { if (dir.indexOf('w') >= 0) left = r.left + r.width - minW; width = minW; }
        if (height < minH) { if (dir.indexOf('n') >= 0) top = r.top + r.height - minH; height = minH; }
        /* 不许超出内容区右/下边（左边留出 EDGE 的宽容，方便贴边） */
        const maxW = b.x + b.w - left;
        const maxH = b.y + b.h - top;
        width = Math.min(width, Math.max(minW, maxW));
        height = Math.min(height, Math.max(minH, maxH));
        el.style.left = Math.round(left) + 'px';
        el.style.top = Math.round(top) + 'px';
        el.style.width = Math.round(width) + 'px';
        el.style.height = Math.round(height) + 'px';
      };
      const up = () => {
        window.removeEventListener('pointermove', move);
        el.classList.remove('drag');
        readBack();
        save(id, st);
      };
      window.addEventListener('pointermove', move);
      window.addEventListener('pointerup', up, { once: true });
      e.preventDefault();
      e.stopPropagation();
    });
  });

  /* ---------- 最大化 ---------- */
  function toggleMax() {
    maxed = !maxed;
    el.classList.toggle('max', maxed);
    btnMax.innerHTML = icon(maxed ? 'restore' : 'square', 13);
    btnMax.title = maxed ? '还原（双击标题栏同效）' : '铺满内容区（双击标题栏同效）';
    if (maxed) {
      readBack();
      prev = { x: st.x, y: st.y, w: st.w, h: st.h };
      const b = vp();
      st = { x: b.x, y: b.y, w: b.w, h: b.h };
      el.style.left = Math.round(b.x) + 'px';
      el.style.top = Math.round(b.y) + 'px';
      el.style.width = Math.round(b.w) + 'px';
      el.style.height = Math.round(b.h) + 'px';
    } else if (prev) {
      st = prev;
      prev = null;
      apply();
    }
  }

  /* ---------- 开关 ---------- */
  const api = {
    id: id,
    el: el,
    body: body,
    isOpen: () => !el.classList.contains('hide'),
    isMax: () => maxed,
    setSub: (t) => { sub.textContent = t || ''; },
    open: () => {
      if (!el.classList.contains('hide')) { api.focus(); return api; }
      el.classList.remove('hide');
      maxed = false;
      el.classList.remove('max');
      btnMax.innerHTML = icon('square', 13);
      apply();
      remember(id, true);
      if (o.onChange) o.onChange(true);
      api.focus();
      return api;
    },
    close: () => {
      if (el.classList.contains('hide')) return api;
      el.classList.add('hide');
      remember(id, false);
      if (o.onChange) o.onChange(false);
      return api;
    },
    toggle: () => (api.isOpen() ? api.close() : api.open()),
    max: toggleMax,
    focus: () => {
      el.classList.add('hot');
      setTimeout(() => el.classList.remove('hot'), 420);
    }
  };

  el.querySelector('[data-fw-close]').onclick = () => api.close();
  btnMax.onclick = () => toggleMax();

  /* ESC 只在焦点确实在这个窗口里时生效：全局 ESC 归抽屉/弹窗，抢了会很难用 */
  el.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { api.close(); }
  });

  /* 视口变化后重新夹一遍：从外接屏拔掉、浏览器窗口缩小，都可能把窗口留在屏幕外 */
  let rzTimer = 0;
  window.addEventListener('resize', () => {
    if (!api.isOpen()) return;
    clearTimeout(rzTimer);
    rzTimer = setTimeout(() => {
      if (!maxed) readBack();
      apply();
      if (maxed) {                        /* 最大化状态跟着内容区走 */
        const b = vp();
        st = { x: b.x, y: b.y, w: b.w, h: b.h };
        apply();
      }
      save(id, st);
    }, 120);
  });

  REG[id] = api;
  return api;
}
