/* ============================================================
   agent-panel.js —— 制片助手（浮窗形态）

   和「点按钮」的关系
   -----------------
   按钮是**确定性**的：知道要跑什么，点它就行。
   助手是**探索性**的：不知道下一步该做什么（缺什么？该先出图还是先改剧本？），
   或者不想一页页点。它读状态、调工具、汇报，人只说「继续」。

   为什么是浮窗而不是整页
   ---------------------
   它的用法是「边看边问」：问「第 3 镜为什么没出片」，眼睛得同时看着分镜页。
   整页版每次切页都重建 DOM、丢掉滚动位置和没发出去的草稿；浮窗只建一次。

   三条纪律（和 backend agent.py 一致）
   ----------------------------------
   1. 工具是白名单：没有 shell、没有任意路径写；06-提示词 契约它碰不到。
   2. 占 GPU 的命令要人点头（「允许占用 GPU」开关），**默认关，且不持久化**。
   3. 调用云端模型要人点头：每次发送先确认，并说明一次请求最多 12 步。
   4. 每一步都摊开给人看，不藏黑箱 —— 出问题时要能指着某一步说「这里错了」。
   ============================================================ */
import { api } from './api.js';
import { esc, icon, badge, confirmCost, toast, paintIcons } from './ui.js';
import { createFloat, wasOpen } from './float.js';
import { S, project as currentProject } from './store.js';

const STARTERS = [
  '把这部片从灵感到成片推进到底：先看状态，缺什么补什么，每步做完告诉我',
  '现在卡在哪一步？下一步该做什么，直接帮我做掉',
  '把第 1 集的分镜图补齐，缺哪几镜列给我',
  '帮我检查剧本和分镜的连续性，有问题直接改'
];

/* ---------- 对话状态（模块级 = 关窗口不丢） ---------- */
let MSG = [];            /* [{role, content, steps?}] */
let busy = false;
let wsKey = '';
let auto = readPref('sd.agent.auto', false);
/* ★ 占 GPU 的授权**不持久化**：上次开着、这次刷新后还开着，等于人没再确认就烧卡。
   这是本项目唯一会造成真实损失的操作，宁可每次多问一句。 */
let allowGpu = false;

let ui = null;           /* { log, ta, meta, btn, bar, auto, gpu } */
let getCtxFn = () => ({ ws: S.ws, project: currentProject() });

function readPref(k, dft) {
  try { return localStorage.getItem(k) === '1'; } catch (e) { return dft; }
}

function writePref(k, v) {
  try { localStorage.setItem(k, v ? '1' : '0'); } catch (e) { /* ignore */ }
}

/* ---------- 渲染片段 ---------- */
function bubble(m) {
  const me = m.role === 'user';
  return '<div class="ag-row ' + (me ? 'me' : 'ai') + '">'
    + '<div class="ag-b' + (me ? ' me' : '') + '">' + esc(m.content) + '</div></div>';
}

function stepLine(s) {
  const r = s.result || {};
  const ok = r.ok !== false;
  const tone = ok ? 'done' : (r.need_confirm ? 'confirm' : 'fail');
  const detail = ok
    ? (r.detail || (r.mode === 'job' ? '已入队 ' + r.job : '') || (r.status ? '状态 ' + r.status : '完成'))
    : (r.detail || '失败');
  return '<div class="ag-step">'
    + '<div class="row" style="gap:8px;align-items:baseline">'
    + '<i class="dot ' + tone + '"></i>'
    + '<span class="mono tiny">' + s.n + '. ' + esc(s.tool) + '</span>'
    + (s.ms ? '<span class="tiny dim">' + s.ms + 'ms</span>' : '')
    + '<span class="spacer"></span>'
    + (ok ? '' : badge('warn', r.need_confirm ? '待确认' : '失败'))
    + '</div>'
    + (s.args && Object.keys(s.args).length
      ? '<div class="tiny dim mono" style="margin-left:14px">' + esc(JSON.stringify(s.args).slice(0, 160)) + '</div>'
      : '')
    + '<div class="tiny" style="margin-left:14px;color:' + (ok ? 'var(--txt-2)' : 'var(--warning, var(--accent))') + '">'
    + esc(String(detail).slice(0, 220)) + '</div>'
    + ((r.tail && !ok) ? '<pre class="log" style="margin-left:14px;max-height:110px;font-size:10px">'
      + esc(r.tail.slice(-600)) + '</pre>' : '')
    + '</div>';
}

function chatHtml() {
  if (!MSG.length) {
    return '<div class="ag-empty">'
      + '<div class="ag-empty-t">跟它说要做的事，它自己去读状态、调工具</div>'
      + '<div class="ag-empty-h">比如「把这一集从剧本推到出片」，或者「看一下现在卡在哪」。'
      + '它只能调白名单里的工具：不写 06-提示词 契约、不花站外的钱、占 GPU 前会先问你。</div>'
      + '<div class="ag-starters">' + STARTERS.map((s, i) =>
        '<button class="ag-chip" data-starter="' + i + '">' + esc(s) + '</button>').join('') + '</div>'
      + '</div>';
  }
  return MSG.map((m) => bubble(m)
    + ((m.steps && m.steps.length)
      ? '<div class="ag-trace">' + m.steps.map(stepLine).join('') + '</div>' : '')
  ).join('');
}

/* ---------- 面板 DOM ---------- */
function bodyHtml() {
  return '<div class="ag-fbar">'
    + '<button class="chip' + (auto ? ' on' : '') + '" id="agAuto" '
    + 'title="每步不再等你确认（写盘仍会备份）">自动继续</button>'
    + '<button class="chip' + (allowGpu ? ' on' : '') + '" id="agGpu" '
    + 'title="允许它提交占 GPU 的命令（出图/出片）。每次打开都重置为关">允许占用 GPU</button>'
    + '<span class="spacer"></span>'
    + '<button class="btn quiet sm" id="agClear" title="清空对话（不动任何文件）">新对话</button>'
    + '</div>'
    + '<div class="ag-log" id="agLog">' + chatHtml() + '</div>'
    + '<div class="ag-input">'
    + '<textarea class="textarea" id="agText" rows="2" '
    + 'placeholder="说你要什么（Ctrl+Enter 发送）"></textarea>'
    + '<div class="col" style="gap:6px;align-items:stretch">'
    + '<button class="btn primary" id="agSend">' + icon('play', 14) + ' 发送</button>'
    + '<span class="tiny dim" id="agMeta" style="text-align:center"></span></div>'
    + '</div>';
}

function scroll() {
  if (ui && ui.log) ui.log.scrollTop = ui.log.scrollHeight;
}

function headSub() {
  if (!S.ws) return '未选择项目';
  const p = currentProject();
  return (p ? (p.title || p.path.split(/[\\/]/).pop()) : S.ws.split(/[\\/]/).pop())
    + (busy ? ' · 思考中' : '');
}

/* ---------- 发送 ---------- */
async function send(text, confirmed) {
  const ctx = getCtxFn();
  const t = String(text || '').trim();
  if (!t || busy || !ui) return;

  /* 换项目后还带着上一部的对话历史，模型会拿旧上下文答新项目 —— 直接清掉更诚实 */
  if (wsKey !== (ctx.ws || '')) {
    MSG = [];
    wsKey = ctx.ws || '';
  }
  if (!ctx.ws) { toast('先打开一个项目，助手才有东西可读', 'warn'); return; }
  if (!confirmed) {
    confirmCost({
      title: '确认调用制片助手模型',
      lines: [
        ['项目', ctx.ws],
        ['自动继续', auto ? '开（最多 12 步）' : '关（遇确认点即停）'],
        ['GPU 命令', allowGpu ? '已授权' : '未授权（会先询问）']
      ],
      total: '按供应商实际 usage 结算',
      note: '助手一次请求最多调用模型 12 步。云端模型可能产生真实费用；供应商未返回金额时保持未知，不按 token 猜价。',
      onOk: () => send(t, true)
    });
    return;
  }

  busy = true;
  ui.ta.value = '';
  MSG.push({ role: 'user', content: t });
  ui.log.innerHTML = chatHtml() + '<div class="ag-row ai"><div class="ag-b">'
    + '<span class="spinner"></span> 正在读状态并决定下一步…</div></div>';
  scroll();
  ui.btn.disabled = true;
  ui.meta.textContent = '思考中';
  if (floatApi) floatApi.setSub(headSub());

  try {
    const r = await api.agentChat({
      ws: ctx.ws,
      /* 只发 role/content：steps 是本地展示用的，回传给模型等于让它以为自己说过那些话 */
      messages: MSG.map((m) => ({ role: m.role, content: m.content })),
      auto: auto, allow_gpu: allowGpu, confirm: true
    });
    MSG.push({
      role: 'assistant',
      content: r.reply || (r.ok ? '（没有回复）' : '出错了'),
      steps: r.steps || []
    });
    ui.meta.textContent = [r.elapsed ? r.elapsed + 's' : '',
      r.usage && r.usage.total_tokens ? r.usage.total_tokens + ' tok' : '']
      .filter(Boolean).join(' · ');
    if (!r.ok && r.error) toast('模型侧出错：' + r.error, 'bad');
  } catch (e) {
    MSG.push({ role: 'assistant', content: '请求失败：' + (e.detail || e.message) });
    toast('失败：' + (e.detail || e.message), 'bad');
  } finally {
    busy = false;
    ui.btn.disabled = false;
    ui.log.innerHTML = chatHtml();
    scroll();
    if (floatApi) floatApi.setSub(headSub());
  }
}

/* ---------- 挂载 ---------- */
function mount(body) {
  ui = {
    log: body.querySelector('#agLog'),
    ta: body.querySelector('#agText'),
    meta: body.querySelector('#agMeta'),
    btn: body.querySelector('#agSend'),
    auto: body.querySelector('#agAuto'),
    gpu: body.querySelector('#agGpu')
  };
  paintIcons(body);
  scroll();

  body.querySelectorAll('[data-starter]').forEach((b) => {
    b.onclick = () => { ui.ta.value = STARTERS[Number(b.dataset.starter)]; ui.ta.focus(); };
  });

  ui.auto.onclick = () => {
    auto = !auto;
    writePref('sd.agent.auto', auto);
    ui.auto.classList.toggle('on', auto);
    toast(auto ? '自动继续：开（不再每步确认）' : '自动继续：关（每步等你点头）');
  };

  ui.gpu.onclick = () => {
    allowGpu = !allowGpu;
    ui.gpu.classList.toggle('on', allowGpu);
    toast(allowGpu ? '已允许占用 GPU（出图/出片会直接提交）' : '已禁止占 GPU，出片前会先问你',
      allowGpu ? 'warn' : 'ok');
  };

  body.querySelector('#agClear').onclick = () => {
    MSG = [];
    ui.log.innerHTML = chatHtml();
    bindStarters(body);
    ui.meta.textContent = '';
  };

  ui.btn.onclick = () => send(ui.ta.value);
  ui.ta.onkeydown = (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); ui.btn.click(); }
  };
}

function bindStarters(body) {
  body.querySelectorAll('[data-starter]').forEach((b) => {
    b.onclick = () => { ui.ta.value = STARTERS[Number(b.dataset.starter)]; ui.ta.focus(); };
  });
}

/* ---------- 对外：单例浮窗 ---------- */
let floatApi = null;

export function getAgent(getCtx) {
  if (getCtx) getCtxFn = getCtx;
  if (floatApi) return floatApi;
  floatApi = createFloat({
    id: 'agent',
    title: '制片助手',
    icon: 'spark',
    /* 520×660：默认别占掉半个画布。用户要更大，拖右下角就行 ——
       一上来铺满，第一眼做的动作一定是「先把它缩小」。 */
    width: 520,
    height: 660,
    minW: 360,
    minH: 320,
    bodyHtml: bodyHtml(),
    mount: mount,
    onChange: (open) => {
      if (open) {
        wsKey = (getCtxFn().ws || '');
        floatApi.setSub(headSub());
        if (ui && ui.ta) setTimeout(() => ui.ta.focus(), 60);
      }
      const nav = document.querySelector('[data-nav="agent"]');
      if (nav) nav.classList.toggle('active', open);
      document.body.classList.toggle('agent-open', open);
    }
  });
  floatApi.setSub(headSub());
  return floatApi;
}

export function openAgent(getCtx) {
  const f = getAgent(getCtx);
  f.open();
  return f;
}

export function toggleAgent(getCtx) {
  const f = getAgent(getCtx);
  if (f.isOpen()) f.close(); else f.open();
  return f;
}

export function agentOpen() {
  return !!floatApi && floatApi.isOpen();
}

/* 启动时恢复：上次是开着的那就还开着（人主动关掉时记为关，不会自作聪明） */
export function restoreAgent(getCtx) {
  if (wasOpen('agent')) openAgent(getCtx);
}

/* 页面重渲染 / 切项目后调用。换项目必须清空对话：
   带着上一部的上下文去问新项目，模型会用旧事实回答新问题，比不回答更糟。 */
export function syncAgent() {
  if (!floatApi || !floatApi.isOpen()) return;
  const ws = S.ws || '';
  if (wsKey && ws !== wsKey) {
    MSG = [];
    wsKey = ws;
    if (ui) {
      ui.log.innerHTML = chatHtml();
      bindStarters(floatApi.body);
      ui.meta.textContent = '';
    }
  }
  if (!wsKey) wsKey = ws;
  floatApi.setSub(headSub());
}
