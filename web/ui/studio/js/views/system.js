/* ============================================================
   system.js —— 系统中心（AI 模型 / 连接 / 环境 三个子模块）

   为什么合并（2026-11-04 用户要求）
   -------------------------------
   这三件事回答的是同一个问题：**这台机器现在能不能干活**。
   分成三页时，用户配完模型不知道要去哪体检；体检红了又找不到连接配置。
   合并成一个入口、三个页签，顺序就按「先配模型 → 再连通道 → 最后体检」排。

   为什么要加「一键下载 / 一键更新」
   -------------------------------
   普通用户不该为了跑起来去敲 pip / git。两个按钮分别对应：
     · 一键下载：把缺的依赖、目录、失效配置、本机 ComfyUI 补齐（每项修完都复检）
     · 一键更新：拉代码（只 fast-forward）+ 补依赖 + 复检
   两个都**如实报告**每一步：失败时给的不是「失败了」，而是「哪一步、什么输出、下一步做什么」。
   ============================================================ */
import { api } from '../api.js';
import { esc, icon, toast, badge, skeleton, paintIcons } from '../ui.js';

const TABS = [
  { id: 'models', label: 'AI 模型', hint: '提供商 / 用途路由 / 模板' },
  { id: 'connections', label: '连接', hint: 'ComfyUI / 本地通道 / 探测' },
  { id: 'health', label: '环境', hint: '体检 / 一键修复 / 下载与更新' }
];

let active = 'models';
let busy = '';           /* download | update | '' */

async function modOf(id) {
  if (id === 'models') return import('./models.js');
  if (id === 'connections') return import('./connections.js');
  return import('./health.js');
}

export async function render(ctx) {
  const tab = TABS.find((t) => t.id === active) || TABS[0];
  const html = ''
    + '<div class="page-head"><div>'
    + '<h1 class="page-title">系统中心</h1>'
    + '<div class="page-sub">模型、通道、环境三件事放在一处：先配模型 → 再连通道 → 最后体检。'
    + '这一页的所有操作都不产生费用。</div></div>'
    + '<div class="page-actions">'
    + '<button class="btn quiet" id="sysDownload">' + icon('download', 14) + ' 一键下载</button>'
    + '<button class="btn" id="sysUpdate">' + icon('refresh', 14) + ' 一键更新</button>'
    + '</div></div>'

    + '<div class="tabs" id="sysTabs">'
    + TABS.map((t) => '<button class="tab' + (t.id === tab.id ? ' active' : '') + '" data-tab="' + t.id
      + '" title="' + esc(t.hint) + '">'
      + esc(t.label) + '</button>').join('')
    + '</div>'

    + '<div id="sysBoot"></div>'
    + '<div id="sysHost">' + skeleton(2) + '</div>';

  return {
    html,
    mount: (root) => {
      root.querySelectorAll('[data-tab]').forEach((b) => {
        b.onclick = () => {
          if (active === b.dataset.tab) return;
          active = b.dataset.tab;
          root.querySelectorAll('[data-tab]').forEach((x) => x.classList.toggle('active', x === b));
          loadTab(root, ctx);
        };
      });
      const dl = root.querySelector('#sysDownload');
      if (dl) dl.onclick = () => runBoot(ctx, root, 'download');
      const up = root.querySelector('#sysUpdate');
      if (up) up.onclick = () => runBoot(ctx, root, 'update');
      loadTab(root, ctx);
      loadBootStatus(root);
    }
  };
}

async function loadTab(root, ctx) {
  const host = root.querySelector('#sysHost');
  if (!host) return;
  host.innerHTML = skeleton(2);
  try {
    const mod = await modOf(active);
    const out = await mod.render(ctx);
    if (!host.isConnected) return;
    host.innerHTML = out.html;
    paintIcons(host);
    if (out.mount) out.mount(host, ctx);
  } catch (err) {
    host.innerHTML = '<div class="alert bad"><span class="nav-ico">' + icon('alert', 14) + '</span><div>'
      + esc((err && (err.detail || err.message)) || '这一页没打开') + '</div></div>';
  }
}

/* ---------- 版本与依赖现状 ---------- */
async function loadBootStatus(root) {
  const box = root.querySelector('#sysBoot');
  if (!box) return;
  let st = null;
  try { st = await api.systemStatus(); } catch (e) { st = null; }
  if (!st || !st.ok) { box.innerHTML = ''; return; }
  const bad = (st.health && st.health.auto) || [];
  const manual = (st.health && st.health.manual) || [];
  box.innerHTML = '<div class="card" style="margin-bottom:14px"><div class="card-b" style="padding:12px 16px">'
    + '<div class="row" style="flex-wrap:wrap;gap:10px">'
    + '<span class="chip mono">' + esc(st.commit || '非 git 安装') + '</span>'
    + (st.branch ? '<span class="chip">分支 ' + esc(st.branch) + '</span>' : '')
    + (st.dirty ? badge('warn', '有本地改动', (st.dirty_files || []).join('\n')) : badge('ok', '工作区干净'))
    + '<span class="spacer"></span>'
    + (bad.length ? badge('warn', bad.length + ' 项可自动修') : badge('ok', '依赖齐'))
    + (manual.length ? badge('muted', manual.length + ' 项需人工') : '')
    + '</div>'
    + '<div class="tiny dim" style="margin-top:8px">引擎解释器 <span class="mono">'
    + esc(st.python) + '</span>　·　更新只做 <span class="mono">git pull --ff-only</span>，'
    + '不会丢本地改动。</div>'
    + '</div></div>';
}

/* ---------- 一键下载 / 一键更新 ---------- */
async function runBoot(ctx, root, kind) {
  if (busy) { toast('上一个动作还在跑', 'warn'); return; }
  busy = kind;
  const host = root.querySelector('#sysHost');
  const box = root.querySelector('#sysBoot');
  const title = kind === 'download' ? '一键下载（补齐依赖与环境）' : '一键更新（拉代码 + 补依赖 + 复检）';
  if (box) {
    box.innerHTML = '<div class="card" style="margin-bottom:14px"><div class="card-b" style="padding:14px 16px">'
      + '<div class="row"><span class="spinner"></span><b>' + esc(title) + '</b>'
      + '<span class="spacer"></span><span class="tiny dim">正在跑，可能要几分钟；期间其它页面可以正常用</span></div>'
      + '<div class="tiny dim" style="margin-top:8px">pip 装包与 git 拉取都是真实网络操作，'
      + '失败会原样把输出贴出来，不会假装成功。</div></div></div>';
  }
  try {
    const r = kind === 'download' ? await api.systemDownload(ctx.ws) : await api.systemUpdate(ctx.ws);
    renderResult(root, r, kind);
    toast(r.ok ? (kind === 'download' ? '环境已补齐' : '已更新') : '跑完了，但有没过的项', r.ok ? 'ok' : 'warn');
    await loadBootStatus(root);
    if (host && active === 'health') loadTab(root, ctx);
  } catch (err) {
    const msg = (err && (err.detail || err.message)) || '未知错误';
    if (box) {
      box.innerHTML = '<div class="alert bad"><span class="nav-ico">' + icon('alert', 14) + '</span><div>'
        + '<b>没有跑完</b><br><span class="small">' + esc(String(msg).slice(0, 800)) + '</span></div></div>';
    }
  } finally {
    busy = '';
  }
}

function renderResult(root, r, kind) {
  const box = root.querySelector('#sysBoot');
  if (!box || !r) return;
  const steps = (r.steps || []).map((s) => {
    const ok = s.ok !== false;
    return '<div style="padding:8px 0;border-bottom:1px solid var(--line)">'
      + '<div class="row gap8"><i class="dot ' + (ok ? 'done' : 'fail') + '"></i>'
      + '<span class="small flex1">' + esc(s.name || s.id || '') + '</span>'
      + (s.verified === true ? badge('ok', '复检通过') : s.verified === false ? badge('warn', '复检未过') : '')
      + (s.action ? '<span class="tiny dim">' + esc(s.action) + '</span>' : '')
      + '</div>'
      + ((s.lines || []).length
        ? '<pre class="log" style="margin-top:6px;max-height:120px">' + esc((s.lines || []).join('\n')) + '</pre>'
        : '')
      + '</div>';
  }).join('');
  const left = (r.left || []).length
    ? '<div class="alert warn" style="margin-top:10px"><span class="nav-ico">' + icon('alert', 14) + '</span><div>'
      + '还剩 ' + r.left.length + ' 项没过：' + esc(r.left.slice(0, 8).join('、'))
      + '<br><span class="small">有些项只能人工处理（填 Key、装外部程序），「环境」页签里逐项写了原因。</span></div></div>'
    : '';
  box.innerHTML = '<div class="card" style="margin-bottom:14px"><div class="card-h">'
    + '<h3>' + esc(kind === 'download' ? '一键下载结果' : '一键更新结果') + '</h3>'
    + '<span class="card-sub">' + esc(r.detail || '') + '</span>'
    + '<span class="spacer"></span>'
    + badge(r.ok ? 'ok' : 'warn', r.ok ? '通过' : '有未过项')
    + '</div><div class="card-b" style="max-height:340px;overflow:auto">'
    + (steps || '<div class="tiny dim">没有需要处理的项。</div>') + left
    + '</div></div>';
}
