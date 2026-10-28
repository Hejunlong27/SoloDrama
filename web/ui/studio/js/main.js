/* ============================================================
   main.js —— 应用外壳：路由 / 侧栏 / 顶栏 / 视图装载
   视图按路由**动态加载**（每个页面一个模块），避免单文件膨胀，也让单页故障不影响外壳。
   ============================================================ */
import { api } from './api.js';
import { esc, icon, paintIcons, errorCard, openDrawer, closeDrawer, closeModal, skeleton, toast } from './ui.js';
import {
  S, loadProjects, loadCaps, loadHealth, loadRunning, project as currentProject,
  setWs, initialWs, initialCollapsed, setCollapsed, loadProjects as reloadProjects
} from './store.js';

const NAV = [
  {
    label: '全局', items: [
      { key: 'workbench', label: '工作台', ico: 'workbench' },
      { key: 'projects', label: '项目管理', ico: 'folder' },
      { key: 'tasks', label: '任务中心', ico: 'list' },
      { key: 'cost', label: '成本中心', ico: 'coins' },
      { key: 'models', label: 'AI 模型中心', ico: 'cpu' },
      { key: 'generators', label: '生成通道', ico: 'spark' },
      { key: 'connections', label: '连接中心', ico: 'plug' },
      { key: 'health', label: '环境体检', ico: 'check' }
    ]
  },
  {
    label: '当前项目', project: true, items: [
      { key: 'overview', label: '项目详情', ico: 'layers' },
      { key: 'pipeline', label: '流水线', ico: 'terminal' },
      { key: 'creation', label: '创作中心', ico: 'spark' },
      { key: 'assets', label: '资产中心', ico: 'image' },
      { key: 'storyboard', label: '分镜与视频', ico: 'film' },
      { key: 'post', label: '后期制作', ico: 'scissors' },
      { key: 'release', label: '发行中心', ico: 'upload' }
    ]
  },
  { label: '系统', items: [{ key: 'settings', label: '系统设置', ico: 'settings' }] }
];

const PROJECT_ROUTES = ['overview', 'pipeline', 'creation', 'assets', 'storyboard', 'post', 'release'];

const VIEWS = {
  workbench: () => import('./views/workbench.js'),
  projects: () => import('./views/projects.js'),
  overview: () => import('./views/overview.js'),
  pipeline: () => import('./views/pipeline.js'),
  creation: () => import('./views/creation.js'),
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
function renderNav(route) {
  const box = document.getElementById('nav');
  box.innerHTML = NAV.map((g) => {
    const disabled = g.project && !S.ws;
    const items = g.items.map((it) => {
      const active = it.key === route;
      let badge = '';
      if (it.key === 'tasks' && S.running > 0) badge = '<span class="nav-badge warn">' + S.running + '</span>';
      return '<button class="nav-item' + (active ? ' active' : '') + (disabled ? ' disabled' : '') + '"'
        + ' data-nav="' + it.key + '"' + (disabled ? ' disabled title="先打开一个项目"' : '') + '>'
        + '<span class="nav-ico">' + icon(it.ico, 16) + '</span>'
        + '<span class="nav-text">' + esc(it.label) + '</span>' + badge + '</button>';
    }).join('');
    const hint = disabled ? '<div class="nav-label" style="letter-spacing:0;text-transform:none">先打开一个项目</div>' : '';
    return '<div class="nav-group"><div class="nav-label">' + esc(g.label) + '</div>' + items + hint + '</div>';
  }).join('');
  box.querySelectorAll('[data-nav]').forEach((b) => {
    b.onclick = () => { if (!b.disabled) navigate(b.dataset.nav); };
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
    + (locks.gpu && locks.gpu.split('/')[0] !== '0' ? 'doing' : 'todo') + '"></i>GPU ' + esc(locks.gpu || '—') + '</span>'
    + '<span class="health-item" title="RunningHub 并发令牌"><i class="dot '
    + (locks.rh && locks.rh.split('/')[0] !== '0' ? 'doing' : 'todo') + '"></i>RH ' + esc(locks.rh || '—') + '</span>';
}

/* ---------- 视图装载 ---------- */
async function render(force) {
  const seq = ++renderSeq;
  const route = parseRoute();
  const view = document.getElementById('view');

  if (PROJECT_ROUTES.indexOf(route) >= 0 && !S.ws) {
    view.innerHTML = noProject(route);
    bindNoProject(view);
    renderNav(route);
    renderTop();
    return;
  }

  view.innerHTML = skeleton(3);
  renderNav(route);

  let mod;
  try {
    mod = await VIEWS[route]();
    const out = await mod.render(ctx());
    if (seq !== renderSeq) return;                  /* 快速切页时丢弃旧结果 */
    view.innerHTML = out.html;
    paintIcons(view);
    if (out.mount) out.mount(view, ctx());
    view.scrollTop = 0;
  } catch (err) {
    if (seq !== renderSeq) return;
    console.error('[studio]', route, err);
    view.innerHTML = errorCard(err, '重新加载');
    const btn = view.querySelector('[data-retry]');
    if (btn) btn.onclick = () => render(true);
  }
  if (force) { /* 强制刷新时不改缓存，仅重绘 */ }
  renderTop();
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

  setWs(initialWs(), { pushUrl: true });
  paintIcons(document);

  try {
    await loadCaps();
    await loadProjects();
    await loadHealth();
    await loadRunning();
  } catch (err) {
    document.getElementById('view').innerHTML = errorCard(err, '重新连接');
    const b = document.querySelector('[data-retry]');
    if (b) b.onclick = () => location.reload();
    return;
  }
  if (!location.hash) location.hash = '#/workbench';
  render();
}

boot();
