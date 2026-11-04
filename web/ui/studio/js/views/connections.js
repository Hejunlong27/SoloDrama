/* ============================================================
   连接中心 —— 两类外部通道（大模型 / 本地 ComfyUI）
   纪律：
     * Key 只进不出：输入框是 password，读回来只有「672…6653（32 位）」；
     * 测试一律只读：查账户、查节点表、读 system_stats，都不产生任务、不花钱；
     * 每个失败必须给「下一步」，不能只显示一个红点。
   ============================================================ */
import { api } from '../api.js';
import { esc, icon, badge, toast, dt, ago, kv, openModal, closeModal, paintIcons } from '../ui.js';

function field(id, label, inner, help) {
  return '<div class="field"><label class="tiny dim" for="' + esc(id) + '">' + esc(label) + '</label>'
    + inner + (help ? '<div class="help">' + esc(help) + '</div>' : '') + '</div>';
}

function tone(it) {
  if (it.last_ok === true) return 'done';
  if (it.last_ok === false) return 'fail';
  return 'todo';
}

function toneText(it) {
  if (it.last_ok === true) return '已连接';
  if (it.last_ok === false) return '有问题';
  return it.has_key || it.kind === 'comfyui' ? '待验证' : '未配置';
}

/* ---------- 三张卡 ---------- */
function cardLlm(it) {
  const provs = it.providers || [];
  return '<section class="card" id="card-llm"><div class="card-h">'
    + '<span class="state ' + tone(it) + '"><i class="dot ' + tone(it) + '"></i>' + esc(toneText(it)) + '</span>'
    + '<h3>大模型</h3><span class="card-sub">剧本 / 分镜 / 文案的生成能力</span>'
    + '<span class="spacer"></span>' + badge('info', '按 token 计费') + '</div>'
    + '<div class="card-b">'
    + '<div class="small muted" style="margin-bottom:12px">' + esc(it.doc) + '</div>'
    + kv([
      /* 只放名字：把「（模型 · 缺 Key · 已停用）」全塞进一行会折成两行半，
         模型名正好被拆在换行处（出现「mock / -episode」这种断词）。 */
      ['提供商', (provs.length ? provs.map((p) => esc(p.name || p.id)
        + (p.enabled === false ? '（停用）' : (p.has_key ? '' : '（缺 Key）'))).join('；') : '还没有'), false],
      ['在用模型', (provs.filter((p) => p.enabled !== false).length
        ? esc(provs.filter((p) => p.enabled !== false)[0].model || '未填') : '—')],
      ['接入方式', 'OpenAI 兼容 / Ollama（地址 + Key + 模型名）'],
      ['最近验证', it.last_test ? dt(it.last_test) : '从未验证']
    ])
    + (it.last_detail ? '<div class="alert ' + (it.last_ok ? 'info' : 'warn') + '" style="margin-top:12px">'
      + '<span class="nav-ico">' + icon(it.last_ok ? 'check' : 'alert', 14) + '</span><div>'
      + esc(it.last_detail) + (it.last_next ? '<br><span class="tiny dim">下一步：' + esc(it.last_next) + '</span>' : '')
      + '</div></div>' : '')
    + '</div><div class="card-foot"><span class="tiny dim">模型在这里只做「有没有」，'
    + '具体哪个用途用哪个模型去 <b>AI 模型中心 → 用途路由</b>。</span>'
    + '<span class="spacer"></span><button class="btn quiet" data-go="models">'
    + icon('external', 13) + ' 去 AI 模型中心</button></div></section>';
}

/* ---------- 本地 ComfyUI 的「在线状态 + 启动/停止」 ----------
   为什么要显示这些：出图前它会自动拉起后台实例（真源 comfy_boot.py），
   用户需要知道「现在是谁在跑、是不是我开的、要等多久」，否则点了没反应会被当成坏了。 */
function liveHtml(s) {
  if (!s) return '<div class="tiny dim">读不到本机服务状态。</div>';
  const t = s.task || {};
  const starting = t.state === 'starting';
  const on = !!s.online;
  const tone = starting ? 'info' : (on ? 'info' : (s.can_start ? 'warn' : 'bad'));
  let head;
  if (starting) {
    head = '正在启动 ComfyUI… <b>' + (t.elapsed || 0) + 's</b>'
      + '<div class="tiny" style="margin-top:4px;opacity:.8">'
      + esc((t.lines && t.lines.length ? t.lines[t.lines.length - 1] : '') || '正在拉起后台实例')
      + '</div>';
  } else if (on) {
    /* ★ 2026-11-04：把「好不好用」也报出来。
       只写「在线」不够 —— 8G 卡在跑长任务时 /system_stats 会变慢，
       延迟突然从 20ms 涨到 800ms 就是「它快撑不住了」的早期信号。 */
    const pr = s.probe || {};
    const q = s.queue || {};
    const bits = [];
    if (pr.latency_ms != null) bits.push('延迟 ' + pr.latency_ms + 'ms');
    if (q.ok) bits.push('队列 ' + (q.running_count || 0) + ' 跑 / ' + (q.pending_count || 0) + ' 等');
    if (pr.vram_free_gb != null) bits.push('空闲 ' + pr.vram_free_gb + 'G');
    head = esc(s.detail || 'ComfyUI 在线')
      + (bits.length ? '<div class="tiny mono" style="margin-top:4px;opacity:.85">' + esc(bits.join('　·　')) + '</div>' : '')
      + (s.owned ? '<div class="tiny" style="margin-top:4px;opacity:.8">这个实例由 Studio 启动'
        + (s.started_iso ? '（' + esc(s.started_iso) + '）' : '') + '</div>'
        : '<div class="tiny" style="margin-top:4px;opacity:.8">正在复用你已打开的实例，不会另起一个</div>');
  } else {
    head = esc(s.detail || '未在线')
      + (s.can_start
        ? '<div class="tiny" style="margin-top:4px;opacity:.8">出图时会自动拉起后台实例（约 30–90 秒），不需要先开桌面版</div>'
        : '<div class="tiny" style="margin-top:4px;opacity:.8">这台机器上没找到可启动的安装：可先用桌面版启动一次，或填下面的安装路径</div>');
  }
  const btns = starting
    ? '<button class="btn quiet sm" disabled><span class="spinner"></span> 启动中</button>'
    : (on
      ? ('<button class="btn quiet sm" id="cFresh">' + icon('refresh', 12) + ' 重新检测</button>'
        + (s.queue && (s.queue.running_count || 0) > 0
          ? '<button class="btn quiet sm" id="cFree" title="释放显存（会中断当前任务）">' + icon('cpu', 12) + ' 释放显存</button>'
          : '')
        + (s.owned
          ? '<button class="btn quiet sm" id="cStop">' + icon('close', 12) + ' 停止</button>'
          : ''))
      : (s.can_start ? '<button class="btn quiet sm" id="cStart">' + icon('play', 12) + ' 现在启动</button>' : ''));
  return '<div class="alert ' + tone + '"><span class="nav-ico">'
    + icon(on || starting ? 'check' : 'alert', 14) + '</span><div style="flex:1">' + head + '</div>'
    + '<div class="row" style="gap:6px;align-items:center">' + btns + '</div></div>';
}

function cardComfy(it, cs) {
  const f = it.fields || {};
  const auto = f.autostart !== false;
  return '<section class="card" id="card-comfyui"><div class="card-h">'
    + '<span class="state ' + tone(it) + '"><i class="dot ' + tone(it) + '"></i>' + esc(toneText(it)) + '</span>'
    + '<h3>本地出图 · ComfyUI</h3><span class="card-sub">角色 / 场景 / 道具图</span>'
    + '<span class="spacer"></span>' + badge('ok', '￥0 · 占 GPU') + '</div>'
    + '<div class="card-b">'
    + '<div class="small muted" style="margin-bottom:12px">' + esc(it.doc) + '</div>'
    + field('cUrl', '服务地址', '<input class="input" id="cUrl" value="' + esc(f.base_url || '')
      + '" placeholder="http://127.0.0.1:8188" spellcheck="false">')
    + '<div class="row" style="gap:8px;margin-top:4px">'
    + '<button class="btn primary" id="cSave">保存</button>'
    + '<button class="btn quiet" id="cTest">测试连接</button>'
    + '<span class="tiny dim" style="margin-left:auto">'
    + (it.last_test ? esc(ago(it.last_test)) + '前验证' : '还没验证过') + '</span></div>'
    + '<label class="row gap8" style="margin-top:12px;cursor:pointer;align-items:flex-start">'
    + '<input type="checkbox" id="cAuto"' + (auto ? ' checked' : '') + ' style="margin-top:3px">'
    + '<span class="small">没启动时自动拉起后台实例<span class="tiny dim">（无窗口；关掉就等于恢复「先开桌面版」）</span></span></label>'
    + '<div id="cLive" style="margin-top:12px">' + liveHtml(cs) + '</div>'
    /* 有实时状态时不再重复显示「上次测试结果」—— 两块说的是同一件事，数字还会打架
       （一块是刚探的显存，一块是 20 分钟前存的）。点「测试连接」时才把它显示出来。 */
    + '<div id="cResult" style="margin-top:10px' + (cs ? ';display:none' : '') + '">'
    + (cs ? '' : resultBox(it)) + '</div>'
    + '</div><div class="card-foot"><span class="tiny dim">保存后出图器会自动用这个地址（不需要你设环境变量）。'
    + '已在线就复用，不会出现两个实例抢同一张显卡。</span></div></section>';
}

function resultBox(it) {
  if (!it.last_test && !it.last_detail) {
    return '<div class="tiny dim">还没有测试过。点「测试连接」做一次只读探测（5 秒内返回）。</div>';
  }
  const good = it.last_ok === true;
  return '<div class="alert ' + (good ? 'info' : 'bad') + '">'
    + '<span class="nav-ico">' + icon(good ? 'check' : 'alert', 14) + '</span><div>'
    + esc(it.last_detail || '—')
    + (it.last_next ? '<div class="tiny" style="margin-top:4px;opacity:.8">下一步：' + esc(it.last_next) + '</div>' : '')
    + '</div></div>';
}

function header(ov) {
  const okN = (ov.items || []).filter((i) => i.last_ok === true).length;
  return '<div class="page-head"><div>'
    + '<div class="crumb"><b>全局</b><span class="sep">/</span><b>连接中心</b></div>'
    + '<h1 class="page-title">连接中心</h1>'
    + '<div class="page-sub">这台机器能用的外部能力。配置一次，所有项目共用；不配也能用，只是对应环节会停在「未接通」。</div></div>'
    + '<div class="page-actions">'
    + (okN === 3 ? badge('ok', '三路全通') : badge(okN ? 'warn' : 'bad', okN + ' / 3 可用'))
    + '<button class="btn quiet" id="testAll">' + icon('refresh', 14) + ' 全部测试</button>'
    + '</div></div>';
}

async function renderChannels(ctx) {
  let ov;
  try {
    ov = await api.connections();
  } catch (e) {
    return {
      html: '<div class="page-head"><div><h1 class="page-title">连接中心</h1></div></div>'
        + '<div class="card"><div class="card-b"><div class="alert bad">'
        + '<span class="nav-ico">' + icon('alert', 14) + '</span><div>读取连接配置失败：'
        + esc(e.detail || e.message) + '</div></div></div></div>'
    };
  }

  const byKind = {};
  (ov.items || []).forEach((i) => { byKind[i.kind] = i; });
  const llm = byKind.llm || { fields: {}, doc: '' };
  const comfy = byKind.comfyui || { fields: {}, doc: '' };
  /* 本机服务实时状态（在线 / 谁启动的 / 正在启动的进度）。读不到就退化成静态说明，不挡页面。 */
  const cs = await api.comfyStatus().catch(() => null);

  const html = header(ov)
    + '<div class="grid g2" style="align-items:start">'
    + cardLlm(llm) + cardComfy(comfy, cs)
    + '<section class="card"><div class="card-h"><h3>注入关系</h3>'
    + '<span class="card-sub">界面填一次，子进程自动带上</span></div><div class="card-b">'
    + kv([
      /* 不写环境变量名：界面对用户只讲「会发生什么」。
         变量名属于实现细节，写出来只会让人以为要自己去设。 */
      ['出图地址', '出图任务启动时自动带上'],
      ['RH Key', '出片任务自动带上，不回显'],
      // ★ 2026-11-01：引擎从 2026-10-29 起不再读平台站点变量，真源是
      //   configs/channels.json。原来这里写「与 Key 一起带上」，等于承诺了一个不生效的东西。
      ['RH 站点', '由 configs/channels.json 决定（上方已显示实际值）'],
      ['大模型', '走内部网关，子进程不接触 Key']
    ])
    + '<div class="alert info" style="margin-top:12px"><span class="nav-ico">' + icon('lock', 14) + '</span><div>'
    + '配置文件在 <span class="mono">' + esc(ov.store || 'web/var/connections.json') + '</span>，'
    + '已被 gitignore；密钥单独一份、权限 0600、接口只回指纹。'
    + '</div></div></div></section></div>';

  return {
    html,
    mount: (root) => {
      paintIcons(root);
      root.querySelectorAll('[data-go]').forEach((b) => {
        b.onclick = () => { if (ctx && ctx.navigate) ctx.navigate(b.dataset.go); };
      });
      mountComfy(ctx, root);
      const all = root.querySelector('#testAll');
      if (all) all.onclick = async () => {
        all.disabled = true;
        const old = all.textContent;
        all.innerHTML = '<span class="spinner"></span>测试中';
        try {
          for (const k of ['llm', 'comfyui']) {
            try { await api.testConnection(k); } catch (e) { /* 单个失败不影响其余 */ }
          }
          toast('测试完成');
          ctx.refresh();
        } finally {
          all.disabled = false;
          all.textContent = old;
        }
      };
    }
  };
}

function mountComfy(ctx, root) {
  const save = root.querySelector('#cSave');
  const test = root.querySelector('#cTest');
  /* 启动是异步的（冷启动 30–90 秒）：轮询状态，直到 task 不再是 starting。
     ★ 上限 240 次 ≈ 6 分钟，够慢机器；超了就停，别把浏览器拖死。 */
  const poll = (n) => {
    n = n || 0;
    setTimeout(async () => {
      if (!document.body.contains(root)) return;
      let s = null;
      try { s = await api.comfyStatus(); } catch (e) { /* 网络抖一下，下一轮再试 */ }
      if (s) paintLive(s);
      const st = s && s.task ? s.task.state : '';
      if (st === 'starting' && n < 240) poll(n + 1);
      else if (n > 0) ctx.refresh();
    }, n === 0 ? 900 : 1600);
  };
  const paintLive = (s) => {
    const box = root.querySelector('#cLive');
    if (!box) return;
    box.innerHTML = liveHtml(s);
    paintIcons(box);
    bindLive(ctx, root, poll);
  };
  bindLive(ctx, root, poll);
  if (save) save.onclick = async () => {
    save.disabled = true;
    try {
      await api.saveConnection('comfyui', {
        base_url: (root.querySelector('#cUrl') || {}).value || '',
        autostart: !!(root.querySelector('#cAuto') || {}).checked
      });
      toast('已保存 ComfyUI 配置');
      ctx.refresh();
    } catch (e) { toast('保存失败：' + (e.detail || e.message), 'bad'); }
    finally { save.disabled = false; }
  };
  if (test) test.onclick = async () => {
    test.disabled = true;
    test.innerHTML = '<span class="spinner"></span>测试中';
    const box = root.querySelector('#cResult');
    try {
      const r = await api.testConnection('comfyui');
      if (box) {
        box.style.display = 'block';
        box.innerHTML = '<div class="alert ' + (r.ok ? 'info' : 'bad') + '">'
          + '<span class="nav-ico">' + icon(r.ok ? 'check' : 'alert', 14) + '</span><div>'
          + esc(r.detail || '') + (r.next ? '<div class="tiny" style="margin-top:4px;opacity:.8">下一步：'
            + esc(r.next) + '</div>' : '') + '</div></div>';
      }
      toast(r.ok ? 'ComfyUI 在线' : '测试失败', r.ok ? 'ok' : 'bad');
      if (r.ok) setTimeout(() => ctx.refresh(), 900);
    } catch (e) { toast('测试失败：' + (e.detail || e.message), 'bad'); }
    finally { test.disabled = false; test.textContent = '测试连接'; }
  };
  /* 页面打开时如果正在启动（比如从别的页切回来），接着看进度 */
  api.comfyStatus().then((s) => {
    if (s && s.task && s.task.state === 'starting') poll(1);
  }).catch(() => {});
}

/* 绑定「现在启动 / 停止」两个按钮（每次重绘都要重绑：它们是新 DOM） */
function bindLive(ctx, root, poll) {
  const start = root.querySelector('#cStart');
  if (start) start.onclick = async () => {
    start.disabled = true;
    start.innerHTML = '<span class="spinner"></span> 启动中';
    try {
      const r = await api.startComfy();
      if (!r.ok) {
        toast(r.detail || '无法启动', 'bad');
        const s = await api.comfyStatus().catch(() => null);
        const box = root.querySelector('#cLive');
        if (s && box) { box.innerHTML = liveHtml(s); paintIcons(box); bindLive(ctx, root, poll); }
        return;
      }
      toast('正在启动，通常 30–90 秒');
      poll(1);
    } catch (e) {
      toast('启动失败：' + (e.detail || e.message), 'bad');
      start.disabled = false;
    }
  };
  const stop = root.querySelector('#cStop');
  if (stop) stop.onclick = async () => {
    stop.disabled = true;
    try {
      const r = await api.stopComfy();
      toast(r.ok ? (r.detail || '已停止') : (r.detail || '停止失败'), r.ok ? 'ok' : 'bad');
    } catch (e) { toast('停止失败：' + (e.detail || e.message), 'bad'); }
    ctx.refresh();
  };

  /* ★ 2026-11-04：两个新动作。
     「重新检测」绕开 3 秒缓存 —— 用户点了按钮就该看到此刻的真实状态，
     而不是 2 秒前的缓存值（那会让人以为按钮没生效）。
     「释放显存」只在队列里有任务时出现：8G 卡换工作流前调一次，能避免
     「明明没任务却 OOM」—— 模型还占着显存，ComfyUI 自己不会主动退。 */
  const fresh = root.querySelector('#cFresh');
  if (fresh) fresh.onclick = async () => {
    fresh.disabled = true;
    const old = fresh.innerHTML;
    fresh.innerHTML = '<span class="spinner"></span> 检测中';
    try {
      const s = await api.comfyStatus(true);
      const box = root.querySelector('#cLive');
      if (s && box) { box.innerHTML = liveHtml(s); paintIcons(box); bindLive(ctx, root, poll); }
      toast(s && s.online ? '在线 · ' + (s.latency_ms == null ? '' : s.latency_ms + 'ms') : '仍不在线', s && s.online ? 'ok' : 'bad');
    } catch (e) {
      toast('检测失败：' + (e.detail || e.message), 'bad');
    } finally {
      // 重绘后节点已换新，这里只兜底恢复（节点若被替换，改的是旧节点，无害）
      fresh.innerHTML = old;
      fresh.disabled = false;
    }
  };
  const freeB = root.querySelector('#cFree');
  if (freeB) freeB.onclick = async () => {
    if (!confirm('释放显存会中断 ComfyUI 当前正在跑的任务。确定？')) return;
    freeB.disabled = true;
    try {
      const r = await api.comfyFree();
      toast(r.ok ? (r.detail || '已请求释放') : (r.reason || '失败'), r.ok ? 'ok' : 'bad');
    } catch (e) { toast('释放失败：' + (e.detail || e.message), 'bad'); }
    finally { freeB.disabled = false; }
  };
}

/* ============================================================
   页签分发：连接中心 = 通道配置 + 生成通道 + 出片工作流
   为什么合到一页：这三块回答的是同一个问题「我把东西接上了吗、接的是哪一份」。
   分成两个顶级菜单时，用户要在两个页面之间对着看，还容易出现「这边显示可用、
   那边说没配置」的口径差（因为各自探测的时机不同）。
   ============================================================ */
const TABS = [
  { key: 'channels', label: '通道配置', sub: '大模型 / ComfyUI' },
  { key: 'generators', label: '生成通道', sub: '图像与视频各条通道的真实状态' },
  { key: 'workflows', label: '出片工作流', sub: '改参数 / 改映射 / 校验 / 回滚' }
];

function tabBar(active) {
  return '<div class="tabs">' + TABS.map((t) => {
    const on = t.key === active;
    return '<button class="tab' + (on ? ' active' : '') + '" data-ctab="' + t.key + '">'
      + esc(t.label) + '</button>';
  }).join('') + '</div>';
}

function pageHead(active) {
  const t = TABS.find((x) => x.key === active) || TABS[0];
  return '<div class="page-head"><div><h1 class="page-title">连接中心</h1>'
    + '<div class="page-sub">' + esc(t.label) + ' · ' + esc(t.sub) + '</div></div>'
    + '</div>' + tabBar(active);
}

function bindTabs(root) {
  root.querySelectorAll('[data-ctab]').forEach((b) => {
    b.onclick = () => { location.hash = '#/connections?tab=' + b.dataset.ctab; };
  });
}

/* ---------- 出片工作流：上传 / 切换 / 看端口 / 改参数 / 改映射 / 校验 / 回滚 ---------- */
function wfCard(it) {
  /* 为什么是卡片而不是表格：Studio 常在窄面板里用（浏览器侧栏、分屏）。
     表格的操作列在最右边，窄屏会被裁掉 —— 用户看到的是一份「没有按钮」的清单，
     然后以为功能没做。卡片让按钮跟在内容后面自然换行，多窄都能点到。 */
  const acts = [];
  if (!it.current) acts.push('<button class="btn quiet sm" data-wf-use="' + esc(it.id) + '">设为当前</button>');
  else acts.push(badge('ok', '当前使用'));
  acts.push('<button class="btn quiet sm" data-wf-edit="' + esc(it.id) + '">改参数</button>');
  acts.push('<button class="btn quiet sm" data-wf-map="' + esc(it.id) + '">改映射</button>');
  acts.push('<button class="btn quiet sm" data-wf-more="' + esc(it.id) + '">更多</button>');
  return '<div class="wf-card" style="border:1px solid var(--line,#2a2f3a);border-radius:8px;'
    + 'padding:10px 12px;margin-bottom:8px">'
    + '<div class="row gap8" style="align-items:center;flex-wrap:wrap">'
    + '<b>' + esc(it.name) + '</b>'
    + (it.builtin ? badge('outline', '内置 · 只读') : '')
    + badge(it.has_map ? 'ok' : 'warn', it.has_map ? '有映射' : '缺映射')
    + '<span class="tiny dim">' + (it.node_count || 0) + ' 节点 · ' + (it.capacity || 0) + ' 张参考图</span>'
    + '</div>'
    + '<div class="row-sub mono tiny dim" style="margin:4px 0 8px;word-break:break-all">'
    + esc(it.path) + '</div>'
    + '<div class="row" style="gap:6px;flex-wrap:wrap">' + acts.join('') + '</div></div>';
}

async function workflowsPanel(ctx) {
  const [d, cs] = await Promise.all([
    api.comfyWorkflows().catch((e) => ({ error: String((e && e.detail) || e) })),
    api.comfyStatus().catch(() => null)
  ]);
  if (d.error) return { html: pageHead('workflows') + '<div class="alert bad">读不到工作流：' + esc(d.error) + '</div>', mount: bindTabs };
  const items = d.items || [];
  const pr = (cs && cs.probe) || {};
  const q = (cs && cs.queue) || {};
  const online = !!(cs && cs.online);
  const live = online
    ? '<span class="dot ok"></span>在线 v' + esc(pr.version || '?')
      + '　延迟 ' + (pr.latency_ms == null ? '—' : pr.latency_ms + 'ms')
      + '　队列 ' + (q.running_count || 0) + ' 跑 / ' + (q.pending_count || 0) + ' 等'
      + '　空闲 ' + (pr.vram_free_gb == null ? '—' : pr.vram_free_gb + 'G')
    : '<span class="dot bad"></span>未在线 —— 改参数照常可用，但「校验」只能做静态检查';

  const html = pageHead('workflows')
    + '<div class="alert ' + (online ? 'info' : 'warn') + '" style="margin-bottom:14px">'
    + '<span class="nav-ico">' + icon(online ? 'cpu' : 'alert', 14) + '</span><div style="flex:1">'
    + '<div class="small mono">' + live + '</div>'
    + '<div class="tiny dim" style="margin-top:4px">'
    + '改的是<b>参数与映射</b>，不是节点图：步数 / cfg / 尺寸 / 帧数 / 种子 / 模型文件，'
    + '以及「哪个节点收提示词、哪几个收参考图」。拖节点加节点请回 ComfyUI 画布，'
    + '改完用「导出（API）」再传上来。</div>'
    + '</div><button class="btn quiet sm" id="wfRefresh">' + icon('refresh', 12) + ' 刷新状态</button></div>'

    + '<section class="card" style="margin-bottom:14px"><div class="card-h"><h3>现有工作流</h3>'
    + '<span class="card-sub">' + items.length + ' 份 · 上传件存 <span class="mono">web/var/comfy/workflows/</span></span></div>'
    + '<div class="card-b">'
    + (items.map(wfCard).join('') || '<div class="dim small">还没有工作流</div>')
    + '</div>'
    + '<div class="card-foot"><span class="tiny dim">「改参数 / 改映射」对内置那份是禁用的 —— '
    + '内置是仓库文件，改了下次更新就没了。先「复制」再改副本。</span></div></section>'

    + '<section class="card"><div class="card-h"><h3>上传 / 粘贴新工作流</h3>'
    + '<span class="card-sub">必须是 ComfyUI「导出 API 格式」的 JSON</span></div>'
    + '<div class="card-b"><div class="grid g2" style="align-items:start">'
    + '<div class="field"><label class="tiny dim">名称（决定文件名）</label>'
    + '<input class="input" id="wfName" placeholder="h3-4step-v2"></div>'
    + '<div class="field"><label class="tiny dim">从文件读入</label>'
    + '<input class="input" id="wfFile" type="file" accept=".json,application/json"></div></div>'
    + '<div class="field"><label class="tiny dim">或直接粘贴 JSON</label>'
    + '<textarea class="textarea" id="wfJson" rows="7" placeholder=\'{"1": {"class_type": "...", "inputs": {}}}\'></textarea></div>'
    + '<div class="row"><button class="btn primary" id="wfSave">' + icon('check', 14) + ' 校验并保存</button>'
    + '<span class="tiny dim">校验不过不会留半成品；保存后回到上面的表里「设为当前」</span></div>'
    + '<div id="wfOut" style="margin-top:10px"></div></div></section>';

  return {
    html,
    mount: (root) => {
      bindTabs(root);
      const out = root.querySelector('#wfOut');
      const rf = root.querySelector('#wfRefresh');
      if (rf) rf.onclick = () => ctx.refresh();

      root.querySelectorAll('[data-wf-use]').forEach((b) => {
        b.onclick = async () => {
          try { await api.setComfyWorkflow(b.dataset.wfUse); toast('已切换，出片默认用它'); ctx.refresh(); }
          catch (e) { toast('切换失败：' + ((e.detail) || e.message), 'bad'); }
        };
      });
      root.querySelectorAll('[data-wf-edit]').forEach((b) => {
        b.onclick = () => openParams(ctx, b.dataset.wfEdit).catch((e) => toast(String(e.message || e), 'bad'));
      });
      root.querySelectorAll('[data-wf-map]').forEach((b) => {
        b.onclick = () => openMap(ctx, b.dataset.wfMap).catch((e) => toast(String(e.message || e), 'bad'));
      });
      /* 「⋯」= 低频动作：校验 / 端口 / 复制 / 备份。用一个弹窗收纳，
         顺便把「这些是什么」写清 —— 三个裸按钮比一句解释更容易被误点。 */
      root.querySelectorAll('[data-wf-more]').forEach((b) => {
        b.onclick = () => {
          const id = b.dataset.wfMore;
          openModal({
            title: '更多 · ' + id,
            icon: 'layers',
            html: '<div class="small muted" style="margin-bottom:10px">这三个都是只读或不改工作流的动作。</div>'
              + '<div class="col" style="display:grid;gap:8px">'
              + '<button class="btn quiet" data-m="check">校验 —— 节点类、模型文件、必需输入</button>'
              + '<button class="btn quiet" data-m="ports">端口 —— 这份工作流能接几张参考图</button>'
              + '<button class="btn quiet" data-m="dup">复制副本 —— 内置只读，改之前先复制</button>'
              + '<button class="btn quiet" data-m="bak">备份与回滚</button></div>',
            foot: '<span class="spacer"></span><button class="btn quiet" data-close="modal">关闭</button>',
            mount: (m) => {
              m.querySelectorAll('[data-m]').forEach((x) => {
                x.onclick = async () => {
                  const what = x.dataset.m;
                  closeModal();
                  try {
                    if (what === 'check') return await openValidate(ctx, id);
                    if (what === 'bak') return await openBackups(ctx, id);
                    if (what === 'ports') return await showPorts(id);
                    const name = prompt('副本名称（决定文件名）', id + '-copy');
                    if (name === null) return;
                    const r = await api.wfDuplicate(id, name);
                    toast(r.detail || '已复制');
                    ctx.refresh();
                  } catch (e) { toast('操作失败：' + ((e.detail) || e.message), 'bad'); }
                };
              });
            }
          });
        };
      });

      const showPorts = async (id) => {
        {
          try {
            const it = await api.comfyWorkflow(id);
            const rows = (it.ports || []).map((p) => '<tr><td class="mono">' + esc(p.node) + '</td>'
              + '<td class="mono small">' + esc(p.class_type) + '</td><td class="mono small">' + esc(p.field) + '</td>'
              + '<td>' + badge('info', esc(p.role)) + '</td>'
              + '<td class="mono tiny dim">' + esc(String(p.value).slice(0, 40)) + '</td></tr>').join('');
            openModal({
              title: '端口 · ' + (it.name || it.id),
              icon: 'cpu',
              html: '<div class="alert info"><span class="nav-ico">' + icon('alert', 14) + '</span><div>'
                + '参考图容量 <b>' + (it.capacity || 0) + ' 张</b>；出片时会按实际张数自动关掉多余槽位。</div></div>'
                + '<div class="table-wrap" style="max-height:460px;overflow:auto"><table class="tb"><thead><tr>'
                + '<th>节点</th><th>类型</th><th>字段</th><th>角色</th><th>当前值</th></tr></thead><tbody>'
                + (rows || '<tr><td colspan="5" class="dim">没识别到端口</td></tr>') + '</tbody></table></div>',
              foot: '<span class="spacer"></span><button class="btn quiet" data-close="modal">关闭</button>'
            });
          } catch (e) { toast('读端口失败：' + ((e.detail) || e.message), 'bad'); }
        }
      };

      const fileEl = root.querySelector('#wfFile');
      const jsonEl = root.querySelector('#wfJson');
      const nameEl = root.querySelector('#wfName');
      if (fileEl) {
        fileEl.onchange = () => {
          const f = fileEl.files && fileEl.files[0];
          if (!f) return;
          const rd = new FileReader();
          rd.onload = () => { jsonEl.value = String(rd.result || ''); if (!nameEl.value) nameEl.value = f.name.replace(/\.json$/i, ''); };
          rd.readAsText(f);
        };
      }
      const btn = root.querySelector('#wfSave');
      btn.onclick = async () => {
        btn.disabled = true;
        try {
          const r = await api.saveComfyWorkflow({ name: nameEl.value || 'workflow', json: jsonEl.value });
          out.innerHTML = '<div class="alert ok"><span class="nav-ico">' + icon('check', 14) + '</span><div>'
            + '已保存 <b>' + esc(r.id) + '</b>：' + r.node_count + ' 个节点，参考图容量 <b>' + r.capacity + '</b>。'
            + '<div class="tiny dim" style="margin-top:4px">自动映射：' + esc(JSON.stringify(r.map))
            + (r.missing_roles && r.missing_roles.length
              ? '<br>缺角色：' + esc(r.missing_roles.join('、')) + '（用「改映射」补上）' : '')
            + '</div></div></div>';
          toast('工作流已保存');
          ctx.refresh();
        } catch (e) {
          out.innerHTML = '<div class="alert bad"><span class="nav-ico">' + icon('alert', 14) + '</span><div>'
            + esc(typeof e.detail === 'string' ? e.detail : (e.detail && e.detail.message) || e.message) + '</div></div>';
        } finally { btn.disabled = false; }
      };
    }
  };
}

/* ---------- 改参数 ---------- */
async function openParams(ctx, id) {
  const d = await api.wfParams(id);
  const editable = (d.items || []).filter((x) => x.editable);
  const blocked = (d.items || []).filter((x) => !x.editable);

  /* 两列而不是三列：Studio 常在窄面板里跑，第三列（原因）会被裁掉 ——
     而「为什么改不了」正是这个弹窗存在的理由，被裁掉等于白做。
     原因并进第一列的第二行，多窄都看得到。 */
  const rowHtml = (it) => {
    const title = it.label + (it.role ? ' · ' + it.role : '');
    if (!it.editable) {
      const why = it.blocked_by === 'link' ? '由上游连线决定'
        : it.blocked_by === 'map' ? '被映射覆盖'
        : it.blocked_by === 'builtin' ? '内置只读' : '';
      return '<tr class="dim"><td><div>' + esc(title) + ' '
        + '<span class="badge muted">' + esc(why) + '</span></div>'
        + '<div class="row-sub mono">节点 ' + esc(it.node) + ' · ' + esc(it.class_type || '') + '</div>'
        + (it.reason ? '<div class="tiny dim" style="margin-top:2px;word-break:break-word">'
          + esc(it.reason) + '</div>' : '') + '</td>'
        + '<td class="mono tiny" style="vertical-align:top">'
        + (it.type === 'link' ? '← ' + esc(it.upstream) : esc(String(it.value))) + '</td></tr>';
    }
    const v = it.value == null ? '' : String(it.value);
    const input = it.type === 'int' || it.type === 'float'
      ? '<input class="input mono" data-p="' + esc(it.node) + '|' + esc(it.field) + '" value="' + esc(v)
        + '" inputmode="decimal" style="max-width:160px">'
      : '<input class="input mono" data-p="' + esc(it.node) + '|' + esc(it.field) + '" value="' + esc(v)
        + '" spellcheck="false" style="max-width:100%">';
    const rng = (it.min != null && it.max != null)
      ? '<div class="tiny dim">范围 ' + it.min + ' – ' + it.max + '</div>' : '';
    return '<tr><td><div>' + esc(title) + ' <span class="tiny dim">' + esc(it.type) + '</span></div>'
      + '<div class="row-sub mono">节点 ' + esc(it.node) + ' · ' + esc(it.class_type || '') + '</div></td>'
      + '<td>' + input + rng + '</td></tr>';
  };

  const html = '<div class="alert ' + (d.builtin ? 'warn' : 'info') + '" style="margin-bottom:12px">'
    + '<span class="nav-ico">' + icon('alert', 14) + '</span><div>'
    + (d.builtin
      ? '这是<b>内置工作流</b>，只读。要改先回列表点「复制」生成副本，再改副本。'
      : '改完立刻生效：下一次出片/出图就用新值。写盘前会留一份 <span class="mono">.bak_时间戳</span> 备份。')
    + '</div></div>'
    /* 不用 tab：这两个区块不是「二选一」，而是「先看能改的，再看为什么别的改不了」。
       做成 tab 会有两个问题 —— 第二个 tab 隐藏着最重要的一句话（改了没用），
       而且 tab 看起来可点、点不动（它只是 span），比不做还糟。 */
    + '<div class="row" style="margin:2px 0 8px;align-items:baseline;gap:8px">'
    + '<b class="small">可调 ' + editable.length + ' 项</b>'
    + '<span class="tiny dim">改完立刻生效，写盘前自动备份</span></div>'

    + (editable.length
      ? '<div class="table-wrap" style="max-height:340px;overflow:auto"><table class="tb"><thead><tr>'
        + '<th>参数</th><th style="width:42%">当前值</th></tr></thead><tbody>'
        + editable.map(rowHtml).join('') + '</tbody></table></div>'
      : '<div class="empty"><div class="empty-t">没有可改的参数</div>'
        + '<div class="empty-h">' + (d.builtin ? '内置工作流只读，先复制副本。' : '这份工作流里没有识别到可调参数。') + '</div></div>')

    + (blocked.length
      ? '<div class="row" style="margin:14px 0 6px;align-items:baseline;gap:8px">'
        + '<b class="small">改不了 ' + blocked.length + ' 项</b>'
        + '<span class="tiny dim">提前说清，比让你改完发现没用要好</span></div>'
        + '<div class="table-wrap" style="max-height:240px;overflow:auto"><table class="tb"><thead><tr>'
        + '<th>参数 / 为什么改不了</th><th style="width:34%">值</th></tr></thead><tbody>'
        + blocked.map(rowHtml).join('') + '</tbody></table></div>'
      : '');

  openModal({
    title: '参数 · ' + id,
    icon: 'settings',
    html,
    foot: '<span class="spacer"></span>'
      + '<button class="btn quiet" data-close="modal">关闭</button>'
      + (d.builtin ? '' : '<button class="btn primary" id="pSave">保存</button>'),
    mount: (m) => {
      const save = m.querySelector('#pSave');
      if (!save) return;
      save.onclick = async () => {
        const changes = [];
        m.querySelectorAll('[data-p]').forEach((el) => {
          const [node, field] = el.dataset.p.split('|');
          const it = (d.items || []).find((x) => x.node === node && x.field === field);
          if (!it || String(it.value) === String(el.value)) return;
          changes.push({ node, field, value: el.value });
        });
        if (!changes.length) { toast('没有改动'); return; }
        save.disabled = true;
        try {
          const r = await api.wfSetParams(id, changes);
          if (!r.ok) {
            toast((r.detail || '未写入') + '：' + (r.rejected || []).map((x) => x.why).join('；'), 'bad');
          } else {
            toast(r.detail || '已保存');
            closeModal();
            ctx.refresh();
          }
        } catch (e) {
          toast('保存失败：' + ((e.detail) || e.message), 'bad');
        } finally { save.disabled = false; }
      };
    }
  });
}

/* ---------- 改映射 ---------- */
async function openMap(ctx, id) {
  const d = await api.wfMap(id);
  const it = await api.comfyWorkflow(id).catch(() => ({ ports: [] }));
  const ports = it.ports || [];
  const roles = ['prompt', 'images', 'seconds', 'steps', 'seed', 'aspect', 'prefix', 'duration'];
  const LABEL = { prompt: '提示词写进哪个节点', images: '参考图铺到哪几个节点（逗号分隔）',
    seconds: '时长（秒）', steps: '步数', seed: '种子', aspect: '画幅', prefix: '输出文件名前缀',
    duration: '时长节点' };
  const cur = d.map || {};

  const row = (role) => {
    const val = cur[role];
    const shown = Array.isArray(val) ? val.join(',') : (val == null ? '' : String(val));
    const hint = ports.filter((p) => p.role === role).map((p) => p.node).join(',');
    return '<tr><td><div>' + esc(LABEL[role] || role) + '</div>'
      + '<div class="row-sub mono">' + esc(role) + '</div></td>'
      + '<td><input class="input mono" data-role="' + esc(role) + '" value="' + esc(shown)
      + '" placeholder="' + esc(hint || '节点 id') + '" spellcheck="false"></td>'
      + '<td class="tiny dim">' + (hint ? '自动识别：' + esc(hint) : '没识别到，手工填') + '</td></tr>';
  };

  openModal({
    title: '映射 · ' + id,
    icon: 'layers',
    html: '<div class="alert ' + (d.source.indexOf('保存') === 0 ? 'info' : 'warn') + '" style="margin-bottom:12px">'
      + '<span class="nav-ico">' + icon('alert', 14) + '</span><div>' + esc(d.note || '')
      + '<div class="tiny dim" style="margin-top:4px">当前来源：' + esc(d.source) + '</div>'
      + (d.missing_roles && d.missing_roles.length
        ? '<div class="tiny" style="margin-top:4px">缺角色：' + esc(d.missing_roles.join('、')) + '</div>' : '')
      + '</div></div>'
      + '<div class="table-wrap" style="max-height:400px;overflow:auto"><table class="tb"><thead><tr>'
      + '<th style="width:40%">角色</th><th style="width:32%">节点 id</th><th>说明</th></tr></thead><tbody>'
      + roles.map(row).join('') + '</tbody></table></div>',
    foot: '<span class="spacer"></span><button class="btn quiet" data-close="modal">关闭</button>'
      + '<button class="btn primary" id="mSave">保存</button>',
    mount: (m) => {
      m.querySelector('#mSave').onclick = async () => {
        const map = {};
        m.querySelectorAll('[data-role]').forEach((el) => {
          const v = String(el.value || '').trim();
          if (!v) return;
          map[el.dataset.role] = el.dataset.role === 'images'
            ? v.split(',').map((s) => s.trim()).filter(Boolean) : v;
        });
        try {
          const r = await api.wfSetMap(id, map);
          if (!r.ok) {
            toast('未写入：' + (r.rejected || []).map((x) => x.why + (x.value ? '(' + x.value + ')' : '')).join('；'), 'bad');
            return;
          }
          toast(r.detail || '映射已保存');
          closeModal();
          ctx.refresh();
        } catch (e) { toast('保存失败：' + ((e.detail) || e.message), 'bad'); }
      };
    }
  });
}

/* ---------- 校验 ---------- */
async function openValidate(ctx, id) {
  toast('正在校验（会读 ComfyUI 的节点表）…');
  const v = await api.wfValidate(id);
  const ok = v.ok;
  const list = (arr, cls) => (arr || []).map((s) => '<div class="small" style="margin:4px 0">'
    + '<span class="badge ' + cls + '">' + (cls === 'bad' ? '必须修' : '注意') + '</span> ' + esc(s) + '</div>').join('');
  openModal({
    title: '校验 · ' + id,
    icon: ok ? 'check' : 'alert',
    html: '<div class="alert ' + (ok ? 'ok' : 'bad') + '"><span class="nav-ico">'
      + icon(ok ? 'check' : 'alert', 14) + '</span><div>'
      + (ok ? '这份工作流现在可以提交' : '这份工作流提交会失败')
      + (v.online ? '' : '（ComfyUI 没连上，只做了静态检查）')
      + '<div class="tiny" style="margin-top:4px">节点 ' + (v.node_count || 0)
      + ' 个 · 参考图容量 ' + (v.capacity || 0) + ' 张'
      + (v.has_map ? ' · 已带映射' : ' · 无映射') + '</div></div></div>'
      + list(v.errors, 'bad') + list(v.warns, 'warn')
      + (ok && !(v.warns || []).length ? '<div class="small muted">没有发现问题。</div>' : ''),
    foot: '<span class="spacer"></span><button class="btn quiet" data-close="modal">关闭</button>'
      + (v.ok ? '' : '<button class="btn quiet" id="vBak">看备份</button>'),
    mount: (m) => {
      const b = m.querySelector('#vBak');
      if (b) b.onclick = () => { closeModal(); openBackups(ctx, id).catch((e) => toast(String(e.message || e), 'bad')); };
    }
  });
}

/* ---------- 备份与回滚 ---------- */
async function openBackups(ctx, id) {
  const d = await api.wfBackups(id);
  const rows = (d.items || []).map((b) => '<tr><td class="mono tiny">' + esc(b.file) + '</td>'
    + '<td class="small">' + esc(b.when || '') + '</td>'
    + '<td class="num tiny">' + Math.round((b.size || 0) / 1024) + ' KB</td>'
    + '<td class="right"><button class="btn quiet sm" data-bak="' + esc(b.file) + '">回到这一版</button></td></tr>').join('');
  openModal({
    title: '备份 · ' + id,
    icon: 'layers',
    html: (rows
      ? '<div class="small muted" style="margin-bottom:8px">每次改参数/改映射前都会自动留一份。回滚本身也会先备份当前版本，所以回滚也能反悔。</div>'
        + '<div class="table-wrap" style="max-height:420px;overflow:auto"><table class="tb"><thead><tr>'
        + '<th>文件</th><th style="width:150px">时间</th><th class="num" style="width:80px">大小</th>'
        + '<th class="right" style="width:110px"></th></tr></thead><tbody>' + rows + '</tbody></table></div>'
      : '<div class="empty"><div class="empty-t">还没有备份</div>'
        + '<div class="empty-h">改过一次参数或映射之后，这里就会出现可回滚的版本。</div></div>'),
    foot: '<span class="spacer"></span><button class="btn quiet" data-close="modal">关闭</button>',
    mount: (m) => {
      m.querySelectorAll('[data-bak]').forEach((b) => {
        b.onclick = async () => {
          if (!confirm('回到 ' + b.dataset.bak + '？当前版本会先备份。')) return;
          try {
            const r = await api.wfRestore(id, b.dataset.bak);
            toast(r.detail || '已回滚');
            closeModal();
            ctx.refresh();
          } catch (e) { toast('回滚失败：' + ((e.detail) || e.message), 'bad'); }
        };
      });
    }
  });
}

export async function render(ctx) {
  const m = String(location.hash || '').match(/[?&]tab=([a-z]+)/);
  const tab = (m && m[1]) || 'channels';
  if (tab === 'workflows') return workflowsPanel(ctx);
  if (tab === 'generators') {
    const g = await import('./generators.js');
    const out = await g.render(ctx, { embedded: true });
    return {
      html: pageHead('generators') + out.html,
      mount: (root) => { bindTabs(root); if (out.mount) out.mount(root); }
    };
  }
  const base = await renderChannels(ctx);
  /* 通道页的 html 前面加上页头与页签（renderChannels 自己那份 page-head 换成带页签的） */
  const idx = base.html.indexOf('</div></div>');
  const rest = idx >= 0 ? base.html.slice(idx + '</div></div>'.length) : base.html;
  return {
    html: pageHead('channels') + rest,
    mount: (root) => { bindTabs(root); if (base.mount) base.mount(root); }
  };
}
