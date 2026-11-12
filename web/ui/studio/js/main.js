/* ============================================================
   main.js —— 应用外壳：路由 / 侧栏 / 顶栏 / 视图装载
   视图按路由**动态加载**（每个页面一个模块），避免单文件膨胀，也让单页故障不影响外壳。
   ============================================================ */
import { api, clearCache } from './api.js';
import { esc, icon, paintIcons, errorCard, openDrawer, closeDrawer, closeModal, skeleton, toast } from './ui.js';
import { toggleAgent, agentOpen, restoreAgent, syncAgent, openAgent } from './agent-panel.js';
import { initMonitor, openMonitor } from './monitor.js';
import { initTheme, cycle, storedMode, LABEL as THEME_LABEL } from './theme.js';
import {
  S, loadProjects, loadCaps, loadHealth, loadRunning, project as currentProject,
  setWs, initialWs, initialCollapsed, setCollapsed, loadProjects as reloadProjects
} from './store.js';

/* ---------- 侧栏：五个工作空间 ----------
   ★ 2026-11-10（2.0 Phase 3）重排：15 项平铺 → 5 个工作空间 + 4 个全局入口。

   为什么是「工作空间」而不是「更多分组」：
   旧结构把 11 个项目内页面平铺在一级导航里（分镜 / 视频 / 剪辑 / 发行各占一位），
   用户看到的是「功能清单」，不是「我现在在哪条产线上」。按影视制作的真实组织方式
   收成五块：写（创意）→ 造（视觉资产）→ 拍（分镜与拍摄）→ 交（后期与发行）→ 管（制作控制）。

   为什么不把 members 全部展开：
   展开就等于又回到 15 项平铺。默认只显示工作空间名，**当前所在的这一块**才展开成员；
   切换段落的主力入口是内容区顶部的页签条（renderWsbar），侧栏负责「我现在在哪个空间」。

   'system' 故意留在全局：它管的是模型 / 通道 / 环境，属于「这台机器能不能干活」，
   跟有没有打开项目无关。放进项目工作空间会在「还没选项目」时整块变灰，用户配不了模型。 */
const WORKSPACES = [
  {
    key: 'create', label: '创意工作室', ico: 'spark', home: 'create',
    members: [{ key: 'create', label: '创作' }, { key: 'skills', label: '题材模板' }]
  },
  {
    key: 'assets', label: '视觉资产', ico: 'image', home: 'assets',
    members: [{ key: 'assets', label: '资产库' }]
  },
  {
    key: 'shots', label: '分镜与拍摄', ico: 'board', home: 'boards',
    members: [
      { key: 'boards', label: '分镜图' },
      { key: 'storyboard', label: '出片' },
      { key: 'canvas', label: '镜号画布' },
      { key: 'graph', label: '关系图' }
    ]
  },
  {
    key: 'deliver', label: '后期与发行', ico: 'scissors', home: 'post',
    members: [{ key: 'post', label: '后期' }, { key: 'release', label: '发行' }]
  },
  {
    key: 'control', label: '制作控制', ico: 'cpu', home: 'overview',
    members: [
      { key: 'overview', label: '项目驾驶舱' },
      { key: 'pipeline', label: '调度' },
      { key: 'cost', label: '用时与成本' },
      { key: 'generators', label: '生成器' }
    ]
  }
];

const GLOBAL_NAV = [
  { key: 'workbench', label: '工作台', ico: 'workbench' },
  { key: 'tasks', label: '任务中心', ico: 'list' },
  { key: 'system', label: '系统中心', ico: 'cpu' },
  { key: 'settings', label: '系统设置', ico: 'settings' },
  /* 助手是浮窗，不是一页：点它在当前页就地开/关。放在全局组末尾 —
     它服务于「哪一页都不想点」的场景，藏在项目里反而找不到。 */
  { key: 'agent', label: '助手', ico: 'spark', float: true }
];

/* 路由 → 所属工作空间（用于侧栏高亮与页签条） */
const ROUTE_WS = (() => {
  const m = {};
  WORKSPACES.forEach((w) => w.members.forEach((it) => { m[it.key] = w.key; }));
  return m;
})();

/* 需要先选项目才可用的路由。模型/通道/环境不在此列：它们跟项目无关。 */
const PROJECT_ROUTES = ['agent', 'overview', 'graph', 'canvas', 'create', 'skills', 'assets',
  'boards', 'storyboard', 'post', 'release', 'cost', 'pipeline', 'generators'];

const VIEWS = {
  workbench: () => import('./views/workbench.js'),
  projects: () => import('./views/projects.js'),
  create: () => import('./views/create.js'),
  skills: () => import('./views/skills.js'),
  agent: () => import('./views/agent.js'),
  graph: () => import('./views/graph.js'),
  canvas: () => import('./views/canvas.js'),
  boards: () => import('./views/boards.js'),
  system: () => import('./views/system.js'),
  overview: () => import('./views/overview.js'),
  pipeline: () => import('./views/pipeline.js'),
  assets: () => import('./views/assets.js'),
  storyboard: () => import('./views/storyboard.js'),
  post: () => import('./views/post.js'),
  release: () => import('./views/release.js'),
  tasks: () => import('./views/tasks.js'),
  cost: () => import('./views/cost.js'),
  models: () => import('./views/models.js'),
  generators: () => import('./views/generators.js'),
  connections: () => import('./views/connections.js'),
  health: () => import('./views/health.js'),
  settings: () => import('./views/settings.js')
};

let renderSeq = 0;

/* ---------- 顶部进度条 ----------
   只在「真的慢」时出现：200ms 内渲染完就不闪。快请求闪一下比没有更烦。 */
let barTimer = 0;
let barShown = false;

function loadStart() {
  const bar = document.getElementById('loadbar');
  if (!bar) return;
  barShown = false;
  bar.classList.remove('done', 'on');
  clearTimeout(barTimer);
  barTimer = setTimeout(() => {
    barShown = true;
    bar.classList.add('on');
  }, 200);
}

function loadEnd() {
  const bar = document.getElementById('loadbar');
  clearTimeout(barTimer);
  if (!bar || !barShown) return;
  bar.classList.remove('on');
  bar.classList.add('done');
  setTimeout(() => bar.classList.remove('done'), 420);
  barShown = false;
}

/* ---------- 预取 ----------
   首屏画完、浏览器空闲时，把「一定会用到但很贵」的几项先取回来
   （workflow / setup 背后各是一次 Python 子进程，0.5s 起）。
   只取 4 个、且都在 idle 阶段，不会和首屏抢带宽。 */
let prefetched = '';

function prefetch(ws) {
  if (!ws || prefetched === ws) return;
  prefetched = ws;
  const warm = () => {
    api.workflow(ws).catch(() => {});
    api.setup(ws).catch(() => {});
    api.capabilities().catch(() => {});
  };
  if (window.requestIdleCallback) window.requestIdleCallback(warm, { timeout: 2500 });
  else setTimeout(warm, 800);
}

/* ---------- 鼠标流动 ----------
   指针在主按钮上移动时，把坐标写进 CSS 变量，由 ::after 的径向高光跟随。
   只对 .btn.primary 生效：高频小按钮上做跟随会让人手忙，也白耗性能。 */
function bindPointerFlow() {
  document.addEventListener('pointermove', (e) => {
    const t = e.target;
    const b = t && t.closest ? t.closest('.btn.primary') : null;
    if (!b) return;
    const r = b.getBoundingClientRect();
    if (!r.width || !r.height) return;
    b.style.setProperty('--mx', ((e.clientX - r.left) / r.width * 100).toFixed(1) + '%');
    b.style.setProperty('--my', ((e.clientY - r.top) / r.height * 100).toFixed(1) + '%');
  }, { passive: true });
}

function parseRoute() {
  const h = (location.hash || '#/workbench').replace(/^#\/?/, '');
  const key = (h.split('?')[0] || 'workbench').split('/')[0];
  return VIEWS[key] ? key : 'workbench';
}

function navigate(key) {
  if (location.hash === '#/' + key) { render(); return; }
  location.hash = '#/' + key;
  render();
}

function ctx() {
  return {
    ws: S.ws,
    project: currentProject(),
    caps: S.caps,
    readonly: S.readonly,
    navigate,
    refresh: () => render(true)
  };
}

/* ---------- 外壳渲染 ---------- */
function navItem(it, route) {
  /* 浮窗类入口（助手）的高亮看窗口开没开 —— 它可以在任何页面上开着。 */
  const active = it.float ? (agentOpen() || it.key === route) : (it.key === route);
  let badge = '';
  if (it.key === 'tasks' && S.running > 0) badge = '<span class="nav-badge warn">' + S.running + '</span>';
  return '<button class="nav-item' + (active ? ' active' : '') + '"'
    + ' data-nav="' + it.key + '"' + (it.float ? ' data-float="1"' : '')
    + (it.float ? ' title="打开/收起助手浮窗（不切页）"' : '') + '>'
    + '<span class="nav-ico">' + icon(it.ico, 16) + '</span>'
    + '<span class="nav-text">' + esc(it.label) + '</span>' + badge + '</button>';
}

function renderNav(route) {
  const box = document.getElementById('nav');
  const wsOf = ROUTE_WS[route] || '';

  const globals = GLOBAL_NAV.map((it) => navItem(it, route)).join('');

  /* 工作空间：当前所在的那一块才展开成员。
     全部展开 = 又回到 15 项平铺；全不展开 = 用户只能靠页签条找路，
     侧栏会退化成「五个不知道里面有什么的按钮」。 */
  const workspaces = WORKSPACES.map((w) => {
    const disabled = !S.ws;
    const on = wsOf === w.key;
    const head = '<button class="nav-item nav-ws' + (on ? ' active' : '') + (disabled ? ' disabled' : '') + '"'
      + ' data-wsopen="' + w.key + '"' + (disabled ? ' disabled title="先打开一个项目"' : '')
      + ' title="' + esc(w.label) + '">'
      + '<span class="nav-ico">' + icon(w.ico, 16) + '</span>'
      + '<span class="nav-text">' + esc(w.label) + '</span></button>';
    const subs = on
      ? '<div class="nav-sub">' + w.members.map((m) =>
        '<button class="nav-subitem' + (m.key === route ? ' active' : '') + '" data-nav="' + m.key + '">'
        + esc(m.label) + '</button>').join('') + '</div>'
      : '';
    return head + subs;
  }).join('');

  const hint = S.ws ? '' : '<div class="nav-label" style="letter-spacing:0;text-transform:none">先打开一个项目</div>';
  box.innerHTML = '<div class="nav-group"><div class="nav-label">全局</div>' + globals + '</div>'
    + '<div class="nav-group"><div class="nav-label">项目 · 五个工作空间</div>' + workspaces + hint + '</div>';

  box.querySelectorAll('[data-nav]').forEach((b) => {
    b.onclick = () => {
      if (b.disabled) return;
      if (b.dataset.float) { toggleAgent(); return; }   /* 就地开/关，不 navigate */
      navigate(b.dataset.nav);
    };
  });
  box.querySelectorAll('[data-wsopen]').forEach((b) => {
    b.onclick = () => {
      if (b.disabled) return;
      const w = WORKSPACES.find((x) => x.key === b.dataset.wsopen);
      if (w) navigate(w.home);
    };
  });
}

/* 工作空间页签条：内容区顶部，回答「这一块里还有哪几步」。
   侧栏负责「我属于哪个空间」，页签负责「在这个空间里横向移动」——
   两件事分开，才能既不多一层导航，也不逼用户回侧栏找第二条。 */
function renderWsbar(route) {
  const bar = document.getElementById('wsbar');
  if (!bar) return;
  const w = WORKSPACES.find((x) => x.key === ROUTE_WS[route]);
  if (!w || !S.ws) { bar.innerHTML = ''; bar.classList.add('hide'); return; }
  bar.classList.remove('hide');
  bar.innerHTML = '<div class="ws-name"><span class="nav-ico">' + icon(w.ico, 14) + '</span>'
    + esc(w.label) + '</div>'
    + '<div class="ws-tabs">' + w.members.map((m) =>
      '<button class="ws-tab' + (m.key === route ? ' active' : '') + '" data-wsgo="' + m.key + '">'
      + esc(m.label) + '</button>').join('') + '</div>'
    + '<span class="spacer"></span>'
    + '<button class="ws-link" data-wsgo="system" title="模型 / 通道 / 环境（机器级，与项目无关）">模型·通道·环境</button>';
  bar.querySelectorAll('[data-wsgo]').forEach((b) => {
    b.onclick = () => navigate(b.dataset.wsgo);
  });
}

function renderTop() {
  const p = currentProject();
  document.getElementById('projName').textContent = p ? p.title || p.path : (S.ws ? S.ws : '未选择项目');
  document.getElementById('projMeta').textContent = p
    ? (((Number(p.images) || 0) + (Number(p.loose) || 0)) ? ((Number(p.images) || 0) + (Number(p.loose) || 0)) + ' 张图' : '')
      + (p.yuan ? ' · ' + (p.yuan < 100 ? '¥' + p.yuan.toFixed(2) : '¥' + Math.round(p.yuan)) : '')
    : '';
  const d = document.getElementById('projDot');
  d.className = 'dot proj-dot ' + (p ? (p.has_output ? 'done' : 'todo') : 'todo');

  const h = S.health;
  const eng = document.getElementById('engineBadge');
  if (h && h.python) {
    const name = String(h.python).split(/[\\/]/).pop();
    eng.textContent = name;
    eng.title = h.python;
  } else {
    eng.textContent = '引擎未知';
  }
  document.getElementById('roBadge').classList.toggle('hide', !S.readonly);

  const health = document.getElementById('health');
  if (!h) { health.innerHTML = ''; return; }
  const locks = h.locks && h.locks.summary ? h.locks.summary : {};
  health.innerHTML = '<span class="health-item"><i class="dot done"></i>服务在线</span>'
    + '<span class="health-item" title="GPU 资源令牌（放大/字幕独占）"><i class="dot '
    + (locks.gpu && locks.gpu.split('/')[0] !== '0' ? 'doing' : 'todo') + '"></i>GPU ' + esc(locks.gpu || '—') + '</span>';
  // ★ 2026-11-04：原来这里还有一条「RH 并发令牌」。本机只有一个 GPU，没有第二组槽位。
}

/* ---------- 视图装载 ---------- */
async function render(force) {
  const seq = ++renderSeq;
  const route = parseRoute();
  const view = document.getElementById('view');
  const prevRoute = view.dataset.route || '';

  /* 强制刷新 = 用户点了刷新按钮，必须绕过缓存拿真数据；
     普通切页则走 api.js 的短缓存（12s 内不重复起子进程）。 */
  if (force) clearCache();

  if (PROJECT_ROUTES.indexOf(route) >= 0 && !S.ws) {
    endLoad();
    view.innerHTML = noProject(route);
    bindNoProject(view);
    renderNav(route);
    renderWsbar(route);
    renderTop();
    syncAgent();
    return;
  }

  view.innerHTML = skeleton(3);
  renderNav(route);
  renderWsbar(route);
  loadStart();

  let mod;
  try {
    mod = await VIEWS[route]();
    const out = await mod.render(ctx());
    if (seq !== renderSeq) return;                  /* 快速切页时丢弃旧结果 */
    view.innerHTML = out.html;
    paintIcons(view);
    if (out.mount) out.mount(view, ctx());
    view.scrollTop = 0;
    /* 只在「换了模块」时播入场：同页刷新再滑一次会像卡了一下 */
    view.dataset.route = route;
    if (prevRoute !== route) {
      view.classList.remove('view-in');
      void view.offsetWidth;                        /* 强制重排，让动画能重播 */
      view.classList.add('view-in');
    }
  } catch (err) {
    if (seq !== renderSeq) return;
    console.error('[studio]', route, err);
    view.innerHTML = errorCard(err, '重新加载');
    const btn = view.querySelector('[data-retry]');
    if (btn) btn.onclick = () => render(true);
  } finally {
    if (seq === renderSeq) loadEnd();
  }
  renderTop();
  syncAgent();      /* 切项目后浮窗标题跟着变；换项目时对话会被清掉（见 agent-panel） */
}

function noProject(route) {
  return '<div class="page-head"><div><h1 class="page-title">还没有选择项目</h1>'
    + '<div class="page-sub">这一页需要先打开一部剧。项目清单来自本机扫描，不会修改任何文件。</div></div></div>'
    + '<div class="card"><div class="card-b">'
    + '<div class="row"><button class="btn primary" id="pickProject">选择项目</button>'
    + '<button class="btn quiet" data-nav-go="projects">去项目管理</button></div>'
    + '<div class="alert info" style="margin-top:14px"><span class="nav-ico">' + icon('alert', 14) + '</span>'
    + '<div>当前路由：' + esc(route) + '。选择项目后会自动回到这一页。</div></div>'
    + '</div></div>';
}

function bindNoProject(view) {
  const open = () => openProjectPicker(() => render());
  const a = view.querySelector('#pickProject');
  if (a) a.onclick = open;
  const b = view.querySelector('[data-nav-go]');
  if (b) b.onclick = () => navigate(b.dataset.navGo);
}

/* ---------- 项目切换器 ---------- */
export function openProjectPicker(after) {
  const rows = S.projects.map((p) => {
    const on = p.path === S.ws;
    return '<button class="nav-item' + (on ? ' active' : '') + '" data-pick="' + esc(p.path) + '"'
      + ' style="height:auto;padding:10px;border-left-width:2px">'
      + '<i class="dot ' + (p.has_output ? 'done' : 'todo') + '" style="margin-top:4px"></i>'
      + '<span class="nav-text" style="white-space:normal"><span>' + esc(p.title || p.path) + '</span><br>'
      + '<span class="tiny dim mono">' + esc(p.path) + '</span></span></button>';
  }).join('') || '<div class="empty"><div class="empty-t">还没有登记任何项目</div>'
    + '<div class="empty-h">可以扫描本机常见目录，或手动登记一个已有的剧项目目录。</div></div>';

  openDrawer({
    title: '切换项目',
    html: '<div class="search" style="margin-bottom:10px"><span class="nav-ico">' + icon('search', 14) + '</span>'
      + '<input class="input" id="pickFilter" placeholder="按名称或路径筛选"></div>'
      + '<div class="row-gap" id="pickList">' + rows + '</div>'
      + '<div class="row" style="margin-top:14px"><button class="btn quiet" id="btnDiscover">扫描本机项目</button>'
      + '<button class="btn quiet" id="btnRegister">登记已有目录</button></div>',
    foot: '<span class="spacer"></span><button class="btn quiet" data-close="drawer">关闭</button>',
    mount: (root) => {
      const filter = root.querySelector('#pickFilter');
      filter.oninput = () => {
        const kw = filter.value.trim().toLowerCase();
        root.querySelectorAll('[data-pick]').forEach((b) => {
          b.style.display = (!kw || b.dataset.pick.toLowerCase().indexOf(kw) >= 0) ? '' : 'none';
        });
      };
      root.querySelectorAll('[data-pick]').forEach((b) => {
        b.onclick = () => {
          setWs(b.dataset.pick, { pushUrl: true });
          closeDrawer();
          toast('已切换到 ' + b.dataset.pick.split(/[\\/]/).pop());
          if (after) after(); else render(true);
        };
      });
      root.querySelector('#btnDiscover').onclick = async () => {
        const btn = root.querySelector('#btnDiscover');
        btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>扫描中';
        try {
          const d = await api.discover(true);
          const known = S.projects.map((p) => p.path.toLowerCase());
          const fresh = (d.items || []).filter((it) => known.indexOf(String(it.path).toLowerCase()) < 0);
          if (!fresh.length) { toast('没有发现新的项目（已扫描 ' + (d.roots || []).join('、') + '）', 'warn'); return; }
          for (const it of fresh) {
            try { await api.register(it.path, it.name); } catch (e) { /* 单个失败不阻塞 */ }
          }
          await reloadProjects();
          toast('已登记 ' + fresh.length + ' 个新项目');
          closeDrawer(); render(true);
        } catch (err) {
          toast('扫描失败：' + (err.detail || err.message), 'bad');
        } finally {
          btn.disabled = false; btn.textContent = '扫描本机项目';
        }
      };
      root.querySelector('#btnRegister').onclick = () => {
        const p = window.prompt('输入剧项目目录的完整路径（必须已存在）：', '');
        if (!p) return;
        api.register(p.trim(), '').then(async () => {
          await reloadProjects();
          toast('已登记');
          closeDrawer(); render(true);
        }).catch((e) => toast('登记失败：' + (e.detail || e.message), 'bad'));
      };
      paintIcons(root);
    }
  });
}

/* ---------- 启动 ---------- */
async function boot() {
  setCollapsed(initialCollapsed());
  document.getElementById('shell').classList.toggle('shell-collapsed', S.collapsed);

  document.getElementById('btnCollapse').onclick = () => {
    setCollapsed(!S.collapsed);
    document.getElementById('shell').classList.toggle('shell-collapsed', S.collapsed);
  };

  /* 主题：首帧已由 <head> 内联脚本定下（防闪白），这里只接管三态循环与按钮文案。
     三态而不是两态：不给「跟随系统」这一档，用系统主题的人每次开机都要手动点一次。 */
  initTheme();
  const themeBtn = document.getElementById('btnTheme');
  if (themeBtn) {
    const paintTheme = () => {
      const m = storedMode();
      themeBtn.textContent = THEME_LABEL[m] || '跟随系统';
      themeBtn.title = '主题：跟随系统 → 深色 → 浅色（当前：' + themeBtn.textContent + '）';
    };
    paintTheme();
    themeBtn.onclick = () => { cycle(); paintTheme(); };
  }
  document.getElementById('projSwitch').onclick = () => openProjectPicker();
  document.getElementById('btnRefresh').onclick = async () => {
    const btn = document.getElementById('btnRefresh');
    btn.disabled = true;
    try {
      await api.refresh(S.ws);
      await loadHealth();
      await loadProjects();
      await loadRunning();
      render(true);
      toast('已重新读取');
    } catch (e) {
      toast('刷新失败：' + (e.detail || e.message), 'bad');
    } finally { btn.disabled = false; }
  };
  document.getElementById('scrim').onclick = () => { closeModal(); closeDrawer(); };
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { closeModal(); closeDrawer(); }
  });
  document.querySelectorAll('[data-close]').forEach((b) => {
    b.onclick = () => (b.dataset.close === 'drawer' ? closeDrawer() : closeModal());
  });
  window.addEventListener('hashchange', () => render());
  bindPointerFlow();

  setWs(initialWs(), { pushUrl: true });
  paintIcons(document);

  try {
    /* 首屏三项互不依赖（caps / 项目清单 / 服务健康）→ 并行，别串成 3 个 RTT。
       running 依赖 projects 定出的 S.ws，所以留在后面。 */
    await Promise.all([loadCaps(), loadProjects(), loadHealth()]);
    await loadRunning();
  } catch (err) {
    document.getElementById('view').innerHTML = errorCard(err, '重新连接');
    const b = document.querySelector('[data-retry]');
    if (b) b.onclick = () => location.reload();
    return;
  }
  initMonitor();          /* 顶栏资源条：先画出来，别等首个接口回来 */
  if (!location.hash) location.hash = '#/workbench';
  render().then(() => {
    prefetch(S.ws);
    /* 上次关浏览器时浮窗是开着的 → 还开着。人主动关掉时记为关，不自作聪明。
       必须等 render() 之后：浮窗按内容区矩形定位，view 还没铺开时会量到整屏。
       `?agent=1` 可强制打开（分享「画布 + 助手」这种组合视图时用）。 */
    const want = new URLSearchParams(location.search).get('agent');
    if (want === '1') openAgent();
    else restoreAgent();
    /* `?monitor=1` 直接摊开资源监视：排查「跑不动」时不必先点一下 */
    if (new URLSearchParams(location.search).get('monitor') === '1') openMonitor();
  });
}

boot();
