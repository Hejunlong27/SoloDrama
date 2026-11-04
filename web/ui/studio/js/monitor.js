/* ============================================================
   monitor.js —— 显存 / 内存 / 磁盘 占用监控

   为什么是「条」而不是数字
   ----------------------
   这三个数字是**判断能不能开工**的依据：显存不够就别排队出片，内存见底就别开第二个
   ComfyUI，磁盘满了先清 07-成片。—— 但绝对数字要换算半天，条能在一秒内回答
   「现在能不能压活」。所以顶栏放条，点击看详情。

   口径（与 backend monitor.py 一致）
   --------------------------------
   * **GiB**（/1024³），和资源管理器、任务管理器对得上。
   * **内存长期 70–85% 是正常的**：Windows 会主动用满内存做缓存，这不是要爆。
     真正危险的是可用量接近 0（开始换页）。所以内存的黄色阈值放到 85%、红色 94%，
     比显卡宽松 —— 用同一套阈值会让用户天天看着黄条焦虑，然后学会无视它。
   * **磁盘看的是「工作区所在盘」**：只看 C: 没意义，成片落在 D:，卡住的永远是 D:。

   轮询纪律
   -------
   * 3 秒一次，页面隐藏时暂停（切到别的窗口不该还在 fork 子进程）。
   * 失败不 toast：监控条是背景信息，网络抖一下就弹窗比不显示更烦。顶栏显示「—」，
     悬停能看到原因。
   ============================================================ */
import { api } from './api.js';
import { esc, icon } from './ui.js';
import { createFloat } from './float.js';
import { S } from './store.js';

const POLL = 3000;
const KEEP = 40;               /* 40 点 × 3s = 最近 2 分钟 */

/* 分档阈值按「这一项真的危险在哪」定，不统一：
   显存是独占资源，过 90% 下一次出片直接 OOM；
   磁盘是容量资源，百分比之外还要看剩余绝对值（浮窗里两个都写）。 */
const TH = { vram: [75, 90], mem: [85, 94], disk: [80, 92] };

const hist = { vram: [], mem: [], disk: [] };
let timer = 0;
let last = null;
let win = null;

function level(k, pct) {
  const [w, b] = TH[k] || [80, 92];
  const v = Math.round((pct || 0) * 100);
  return v >= b ? 'bad' : v >= w ? 'warn' : '';
}

function pc(pct) { return Math.round((pct || 0) * 100); }

/* 一位小数：`0.0` 在后端是 float，JSON 过来变成 0，直接拼会显示成「0 / 8 GB」，
   和旁边「443.6 / 585.9 GB」不一致 */
function g1(v) { return Number(v || 0).toFixed(1); }

function push(k, pct) {
  const a = hist[k];
  a.push(Math.max(0, Math.min(1, pct || 0)));
  while (a.length > KEEP) a.shift();
}

/* ---------- 顶栏三条 ---------- */
const ITEMS = [
  { k: 'vram', label: '显存' },
  { k: 'mem', label: '内存' },
  { k: 'disk', label: '磁盘' }
];

function shell() {
  return ITEMS.map((it) => '<button class="mon-i" data-mon="' + it.k + '" type="button">'
    + '<span class="mon-l">' + it.label + '</span>'
    + '<span class="mon-bar"><i></i></span>'
    + '<span class="mon-v">—</span></button>').join('');
}

function paintBar(el, key, pct, title) {
  const i = el.querySelector('.mon-bar > i');
  const v = el.querySelector('.mon-v');
  const n = pc(pct);
  i.style.width = n + '%';
  v.textContent = n + '%';
  el.classList.remove('warn', 'bad');
  const lv = level(key, pct);
  if (lv) el.classList.add(lv);
  el.title = title;
}

function paint(d) {
  if (!d || !d.ok) return;
  const box = document.getElementById('monitor');
  if (!box) return;

  const g = d.gpu || {};
  const m = d.mem || {};
  const dk = (d.disk || [])[0] || {};

  const eG = box.querySelector('[data-mon="vram"]');
  const eM = box.querySelector('[data-mon="mem"]');
  const eD = box.querySelector('[data-mon="disk"]');

  if (g.ok) {
    push('vram', g.pct);
    paintBar(eG, 'vram', g.pct,
      '显存 ' + g1(g.used_gib) + ' / ' + g1(g.total_gib) + ' GB'
      + '　GPU 利用率 ' + g.util + '%　' + g.temp + '°C\n' + (g.name || ''));
  } else {
    eG.classList.add('na');
    eG.querySelector('.mon-v').textContent = '—';
    eG.querySelector('.mon-bar > i').style.width = '0%';
    eG.title = '显存读不到：' + (g.reason || '未知原因');
  }

  if (m.ok) {
    push('mem', m.pct);
    paintBar(eM, 'mem', m.pct,
      '内存 ' + g1(m.used_gib) + ' / ' + g1(m.total_gib) + ' GB（可用 ' + g1(m.avail_gib) + ' GB）'
      + '\n长期 70–85% 是正常的：Windows 会用空闲内存做缓存');
  } else {
    eM.classList.add('na');
    eM.querySelector('.mon-v').textContent = '—';
    eM.title = '内存读不到：' + (m.reason || '未知原因');
  }

  if (dk.ok) {
    push('disk', dk.pct);
    paintBar(eD, 'disk', dk.pct,
      (dk.label || '') + ' ' + (dk.mount || '') + '　' + g1(dk.used_gib) + ' / ' + g1(dk.total_gib)
      + ' GB（剩 ' + g1(dk.free_gib) + ' GB）');
    eD.querySelector('.mon-l').textContent = String(dk.mount || '').replace(/\\$/, '') || '磁盘';
  } else {
    eD.classList.add('na');
    eD.querySelector('.mon-v').textContent = '—';
    eD.title = '磁盘读不到：' + (dk.reason || '还没选项目');
  }

  last = d;
  if (win && win.isOpen()) paintWin(d);
}

async function tick() {
  try {
    const d = await api.monitor(S.ws || '');
    paint(d);
  } catch (e) {
    /* 静默：监控是背景信息，抖一下就弹窗比不显示更烦 */
  }
}

function start() {
  stop();
  timer = setInterval(tick, POLL);
}

function stop() {
  if (timer) { clearInterval(timer); timer = 0; }
}

/* ---------- 详情浮窗 ---------- */
function spark(key) {
  /* ★ 颜色用 class，不用内联 var()。踩过两次：
       1) 写成属性 `stroke="var(--ok)"` —— presentation attribute 里 var() 不生效，
          线退成黑色，在 #0d0f12 上等于没画；
       2) 改成 `pl.style.stroke = 'var(--accent)'` —— CSSOM 解析不了 var()，
          整条声明被丢弃，颜色还停在初始值。
     只有 class + 样式表里的 `stroke: var(--x)` 是稳的。 */
  return '<svg class="mn-spark" viewBox="0 0 100 26" preserveAspectRatio="none" aria-hidden="true">'
    + '<polyline class="mn-line ok" data-spark="' + key + '" fill="none" stroke-width="1.4"'
    + ' stroke-linejoin="round" stroke-linecap="round"'
    + ' vector-effect="non-scaling-stroke" points=""></polyline></svg>';
}

function winHtml() {
  return '<div class="mn">'
    + '<div class="mn-note">'
    + '<span class="nav-ico">' + icon('cpu', 13) + '</span>'
    + '<span>3 秒刷新 · 最近 2 分钟曲线 · 数据来自 nvidia-smi / 系统 API</span></div>'

    + '<section class="mn-sec" data-sec="vram">'
    + '<div class="mn-h"><b>显存</b><span class="mn-s" data-gpu-name></span>'
    + '<span class="spacer"></span><b class="mn-p">—</b></div>'
    + '<div class="mn-bar"><i></i></div>'
    + '<div class="mn-f"><span data-vram-num>—</span><span data-vram-meta></span></div>'
    + spark('vram')
    + '</section>'

    + '<section class="mn-sec" data-sec="mem">'
    + '<div class="mn-h"><b>内存</b><span class="mn-s">物理内存</span>'
    + '<span class="spacer"></span><b class="mn-p">—</b></div>'
    + '<div class="mn-bar"><i></i></div>'
    + '<div class="mn-f"><span data-mem-num>—</span><span data-mem-meta></span></div>'
    + spark('mem')
    + '</section>'

    + '<div data-disk-list></div>'

    + '<div class="mn-tip">内存长期 70–85% 是正常的（系统会用空闲内存做缓存）；'
    + '真正要留意的是<b>可用量接近 0</b>。显存过 90% 时下一次出片会 OOM，'
    + '出片前建议先关掉别的占卡程序。</div>'
    + '</div>';
}

function setSec(body, key, pct, numText, rightText) {
  const sec = body.querySelector('[data-sec="' + key + '"]');
  if (!sec) return;
  const n = pc(pct);
  sec.querySelector('.mn-p').textContent = n + '%';
  sec.querySelector('.mn-bar > i').style.width = n + '%';
  sec.querySelector('.mn-bar > i').style.background =
    n >= TH[key][1] ? '#d65c5c' : n >= TH[key][0] ? 'var(--accent)' : 'var(--ok)';
  /* 字段名按 key 走（vram-num / vram-meta / mem-num / mem-meta）。
     原来显存段写的是 gpu-num，按 `data-vram-num` 找不到 → 那一行永远是「—」，
     而条和百分比都是对的，所以很容易漏过去。 */
  const a = sec.querySelector('[data-' + key + '-num]');
  if (a) a.textContent = numText;
  const b = sec.querySelector('[data-' + key + '-meta]');
  if (b) b.textContent = rightText;
}

function drawSpark(body, key, tone) {
  const pl = body.querySelector('[data-spark="' + key + '"]');
  if (!pl) return;
  pl.setAttribute('class', 'mn-line ' + (tone || 'ok'));
  const a = hist[key];
  if (a.length < 2) { pl.setAttribute('points', ''); return; }
  /* 左对齐：第 1 个点在 x=0，往右长。右侧空白 = 这一段还没记满（KEEP 点 = 2 分钟）。
     右对齐（最新点固定在右边）在时间语义上更标准，但刚打开时整条线只有右上角一小截，
     看起来像「坏了」。宁可留白让人看出「正在记录」。 */
  const step = 100 / (KEEP - 1);
  const pts = [];
  a.forEach((v, i) => {
    const x = i * step;
    const y = 24 - v * 22;                    /* viewBox 高 26：上下各留 2px，0% 不会压在边框上 */
    pts.push(x.toFixed(1) + ',' + y.toFixed(1));
  });
  pl.setAttribute('points', pts.join(' '));
}

function paintWin(d) {
  const body = win && win.body;
  if (!body || !d || !d.ok) return;

  const g = d.gpu || {};
  const m = d.mem || {};
  if (g.ok) {
    body.querySelector('[data-gpu-name]').textContent = g.name || '';
    setSec(body, 'vram', g.pct,
      g1(g.used_gib) + ' / ' + g1(g.total_gib) + ' GB',
      'GPU ' + g.util + '% · ' + g.temp + '°C');
    drawSpark(body, 'vram', level('vram', g.pct) || 'ok');
  } else {
    body.querySelector('[data-gpu-name]').textContent = g.reason || '';
    body.querySelector('[data-sec="vram"] .mn-p').textContent = '—';
    body.querySelector('[data-vram-num]').textContent = '读不到';
  }

  if (m.ok) {
    setSec(body, 'mem', m.pct,
      g1(m.used_gib) + ' / ' + g1(m.total_gib) + ' GB',
      '可用 ' + g1(m.avail_gib) + ' GB');
    drawSpark(body, 'mem', level('mem', m.pct) || 'ok');
  } else {
    body.querySelector('[data-sec="mem"] .mn-p').textContent = '—';
    body.querySelector('[data-mem-num]').textContent = m.reason || '读不到';
  }

  const list = body.querySelector('[data-disk-list]');
  const rows = (d.disk || []).map((x) => {
    if (!x.ok) {
      return '<section class="mn-sec"><div class="mn-h"><b>磁盘</b>'
        + '<span class="mn-s">' + esc(x.mount || '') + '</span></div>'
        + '<div class="mn-f"><span>' + esc(x.reason || '读不到') + '</span></div></section>';
    }
    const n = pc(x.pct);
    return '<section class="mn-sec">'
      + '<div class="mn-h"><b>' + esc(x.label || '磁盘') + '</b>'
      + '<span class="mn-s mono">' + esc(x.mount || '') + '</span>'
      + '<span class="spacer"></span><b class="mn-p">' + n + '%</b></div>'
      + '<div class="mn-bar"><i style="width:' + n + '%;background:'
      + (n >= TH.disk[1] ? '#d65c5c' : n >= TH.disk[0] ? 'var(--accent)' : 'var(--ok)')
      + '"></i></div>'
      + '<div class="mn-f"><span>' + g1(x.used_gib) + ' / ' + g1(x.total_gib) + ' GB</span>'
      + '<span>剩 ' + g1(x.free_gib) + ' GB</span></div></section>';
  }).join('');
  if (list) list.innerHTML = rows;
}

export function openMonitor() {
  if (!win) {
    win = createFloat({
      id: 'monitor',
      title: '资源监视',
      icon: 'cpu',
      width: 420,
      height: 440,
      minW: 340,
      minH: 300,
      bodyHtml: winHtml(),
      mount: (body) => { if (last) paintWin(last); }
    });
  }
  win.open();
  if (last) paintWin(last);
  return win;
}

/* ---------- 启动 ---------- */
export function initMonitor() {
  const box = document.getElementById('monitor');
  if (!box) return;
  box.innerHTML = shell();
  box.querySelectorAll('[data-mon]').forEach((b) => {
    b.onclick = () => openMonitor();
  });
  tick();
  start();
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) stop();
    else { tick(); start(); }
  });
  /* 切项目后磁盘要跟着换：只认工作区所在盘，不认 C: */
  window.addEventListener('sd:ws-changed', () => { tick(); });
}
