/* SoloDrama 使用端界面 —— 面向「做短剧的人」
 * 原则：不出现命令、参数、退出码、门禁代号、批次号、平台点数、工作区路径。
 *       用户只看到：这部剧现在怎么样、今天该做什么、花多少钱、有什么需要他决定。
 *       技术人员要看的原始细节，一律折叠在「详细记录」里，且默认收起。 */
'use strict';

const S = { ws: null, home: null, tasks: [], task: null, help: '', es: null, jobId: null };

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const show = (el, yes) => el.classList.toggle('hidden', !yes);

async function api(path, opts) {
  const r = await fetch(path, Object.assign({ headers: { 'Content-Type': 'application/json' } }, opts || {}));
  const t = await r.text();
  let d = null; try { d = t ? JSON.parse(t) : null; } catch (e) { d = { raw: t }; }
  if (!r.ok) { const e = new Error('请求失败'); e.status = r.status; e.data = d; throw e; }
  return d;
}

/* ---------------- 顶部：我的短剧 ---------------- */
async function init() {
  const reg = await api('/api/workspaces');
  const sel = $('dramaSelect');
  sel.innerHTML = '';
  const items = reg.items.filter((i) => i.exists);
  items.forEach((it) => {
    const o = document.createElement('option');
    o.value = it.path;
    const badge = it.images ? `（已生成 ${it.images} 张图 · 约 ¥${(it.yuan || 0).toFixed(2)}）` : '（还没有产出）';
    o.textContent = it.title + ' ' + badge;
    sel.appendChild(o);
  });
  S.items = items;
  S.ws = reg.current && items.some((i) => i.path === reg.current)
    ? reg.current : (items[0] ? items[0].path : null);
  if (S.ws) sel.value = S.ws;
  if (!items.length) { $('welcome').classList.remove('hidden'); show($('dramaBody'), false); return; }
  await loadHome();
}

$('dramaSelect').onchange = async () => {
  S.ws = $('dramaSelect').value;
  await api('/api/workspaces/current', { method: 'POST', body: JSON.stringify({ path: S.ws }) });
  await loadHome();
};

$('btnNewDrama').onclick = () => { $('welcome').classList.remove('hidden'); show($('dramaBody'), false); openTask('start_drama'); };
$('btnRefresh').onclick = () => loadHome();
$('btnFindDrama').onclick = async () => {
  const p = prompt('把你的短剧文件夹路径粘贴进来：');
  if (!p) return;
  try { const reg = await api('/api/workspaces', { method: 'POST', body: JSON.stringify({ path: p }) }); S.ws = reg.current; await init(); }
  catch (e) { alert('这个文件夹不像是一部短剧的文件夹，请确认后再试。'); }
};

/* ---------------- 首页 ---------------- */
async function loadHome() {
  if (!S.ws) return;
  show($('welcome'), false);
  show($('dramaBody'), true);
  skeletons();
  let d;
  try { d = await api('/api/home?ws=' + encodeURIComponent(S.ws)); }
  catch (e) { show($('dramaBody'), false); $('welcome').classList.remove('hidden'); return; }
  S.home = d;
  S.tasks = (await api('/api/tasks?ws=' + encodeURIComponent(S.ws))).items;
  renderHero(); renderStages(); renderTodos(); renderSpend(); renderEpisodes(); renderGlossary();
  $('helloTitle').textContent = d.drama.name;
  $('helloSub').textContent = '画风：' + d.drama.style_text + ' · ' + d.drama.machine_text;
}

/* 加载态：先给骨架，避免白屏跳动 */
function skeletons() {
  $('heroTitle').innerHTML = '<span class="skeleton skeleton-line" style="display:block;width:52%;height:22px"></span>';
  $('heroWhy').innerHTML = '<span class="skeleton skeleton-line w-60" style="display:block"></span>';
  $('heroHow').innerHTML = '<span class="skeleton skeleton-line w-40" style="display:block"></span>';
  $('heroAside').innerHTML = '<div class="skeleton skeleton-line"></div><div class="skeleton skeleton-line w-60"></div>';
  $('userStages').innerHTML = Array.from({ length: 6 }).map(() =>
    '<div class="ustage"><div class="skeleton skeleton-line" style="width:24px;height:24px;border-radius:50%"></div>'
    + '<div class="skeleton skeleton-line w-60"></div></div>').join('');
}

function renderHero() {
  const t = S.home.next_task || {};
  S.task = t;
  const stageName = { idea: '定题材', script: '写剧本', cast: '定形象', storyboard: '画分镜', shoot: '出画面', deliver: '审片发布' };
  const s = S.home.spent || {};
  $('heroStage').textContent = '现在轮到：' + (stageName[t.stage] || '开始');
  $('heroTitle').textContent = t.title || '—';
  $('heroWhy').textContent = t.why || '';
  $('heroHow').textContent = t.how || '';
  $('heroAfter').textContent = t.after ? '做完之后：' + t.after : '';
  $('heroCost').innerHTML = t.needs_confirm || t.cost_hint
    ? '<span class="cost-note">' + esc(t.cost_hint || '这一步可能会花钱，开始前会告诉你要多少') + '</span>'
    : '<span class="muted">这一步不花钱</span>';
  $('btnDoTask').textContent = t.title ? '开始：' + t.title : '开始';
  $('btnDoTask').onclick = () => openTask(t.id);

  const d = S.home.drama || {};
  $('heroAside').innerHTML = `
    <div class="hero-aside-row"><span class="muted">剧名</span><b>${esc(d.name || '—')}</b></div>
    <div class="hero-aside-row"><span class="muted">画风</span><b>${esc(d.style_text || '—')}</b></div>
    <div class="hero-aside-row"><span class="muted">已花</span><b>${esc(s.text || '¥0')}</b></div>
    <div class="hero-aside-row"><span class="muted">做好镜头</span><b>${s.shots_done || 0} 个</b></div>`;
  $('heroSetting').textContent = '';
}

function renderStages() {
  const ss = S.home.stages || [];
  const done = ss.filter((s) => s.state === 'done').length;
  $('userStages').innerHTML = ss.map((s, i) => `
    <div class="ustage ${s.state}">
      <div class="ustage-dot">${s.state === 'done' ? '✓' : i + 1}</div>
      <div class="ustage-name">${esc(s.name)}</div>
      <div class="ustage-text">${esc(s.state_text)}</div>
      <div class="ustage-hint muted">${esc(s.hint)}</div>
    </div>`).join('');
  $('progressNote').textContent = `（${done}/${ss.length} 步已完成）`;
}

function renderTodos() {
  const ps = S.home.problems || [];
  $('todoCount').textContent = String(ps.length);
  $('todoList').innerHTML = ps.length ? ps.map((p) => `
    <div class="todo ${p.kind}">
      <div class="todo-title">${esc(p.title)}</div>
      <div class="muted small">${esc(p.detail)}</div>
      ${p.kind === 'switch'
      ? `<button class="btn btn-mini btn-primary" data-switch="${esc(p.path)}">切到那部剧</button>`
      : (p.task ? `<button class="btn btn-mini" data-task="${esc(p.task)}">去处理</button>`
        : '<span class="muted small">（属于技术配置，可交给维护者）</span>')}
    </div>`).join('') : '<p class="muted">现在没有需要你操心的事，按上面的按钮往下做就行。</p>';
  $('todoList').querySelectorAll('[data-task]').forEach((b) => { b.onclick = () => openTask(b.dataset.task); });
  $('todoList').querySelectorAll('[data-switch]').forEach((b) => {
    b.onclick = async () => {
      S.ws = b.dataset.switch;
      await api('/api/workspaces/current', { method: 'POST', body: JSON.stringify({ path: S.ws }) });
      await init();
      $('dramaSelect').value = S.ws;
    };
  });
}

function renderSpend() {
  const s = S.home.spent || {};
  const lines = s.lines || [];
  $('spendBox').innerHTML = `
    <div class="spend-big">${esc(s.text || '¥0')}</div>
    <div class="muted small">${esc(s.note || '按平台实际用量统计')}</div>
    ${s.ledger_incomplete ? '<div class="notice-warn small">这笔钱已经花出去了，只是系统的账单明细还没收录，所以这里按云端生成记录先算给你看。</div>' : ''}
    <hr class="hr">
    ${lines.length ? lines.map((l) => `<div class="kv"><span class="muted">${esc(l.label)}</span><b>${esc(l.value)}</b></div>`).join('')
    : '<div class="muted">还没有开始做东西。等第一步完成，这里会显示做出来的成果和花费。</div>'}
    ${s.updated_text ? `<div class="muted small" style="margin-top:8px">最近产出：${esc(s.updated_text)}</div>` : ''}`;
}

function renderEpisodes() {
  const eps = S.home.episodes || [];
  if (!eps.length) {
    $('episodeList').innerHTML = '<p class="muted">还没有开始做画面。等剧本和角色形象定好之后，就可以做第一集了。</p>';
    return;
  }
  $('episodeList').innerHTML = `<table><thead><tr><th style="width:70px">集</th>
      <th style="width:180px">画面</th><th style="width:150px">状态</th><th></th></tr></thead><tbody>` +
    eps.map((e) => {
      const pct = e.total ? Math.round((e.ok / e.total) * 100) : 0;
      const cls = e.fail ? 'is-fail' : (e.ok === e.total ? 'is-done' : '');
      return `<tr><td><b>${esc(e.ep)}</b></td>
      <td><div class="ep-bar ${cls}"><div style="width:${pct}%"></div></div>
        <div class="muted small">${e.ok}/${e.total} 个镜头</div></td>
      <td><span class="chip ${e.state}">${esc(e.state_text)}</span></td>
      <td>${e.fail ? '<button class="btn btn-mini" data-task="make_episode">重做失败的镜头</button>' : ''}</td></tr>`;
    }).join('') + '</tbody></table>';
  $('episodeList').querySelectorAll('[data-task]').forEach((b) => { b.onclick = () => openTask(b.dataset.task); });
}

async function renderGlossary() {
  if ($('glossaryBox').dataset.loaded) return;
  const d = await api('/api/glossary');
  $('glossaryBox').innerHTML = '<dl>' + d.items.map((i) => `<dt>${esc(i.term)}</dt><dd>${esc(i.meaning)}</dd>`).join('') + '</dl>';
  $('glossaryBox').dataset.loaded = '1';
}

/* ---------------- 弹窗 ---------------- */
function openModal(title) {
  $('tmTitle').textContent = title;
  $('tmBody').innerHTML = '';
  $('tmFoot').innerHTML = '';
  $('taskModal').classList.remove('hidden');
}
function closeModal() {
  if (S.es) { S.es.close(); S.es = null; }
  $('taskModal').classList.add('hidden');
}
$('tmClose').onclick = closeModal;

function foot(html) { $('tmFoot').innerHTML = html; }

/* ---------------- 任务分发 ---------------- */
async function openTask(tid) {
  const t = (S.tasks || []).find((x) => x.id === tid) || S.home?.next_task;
  if (!t) return;
  S.task = t;
  const ui = t.ui || {};
  if (ui.kind === 'choice') return uiChoice(t);
  if (ui.kind === 'dual_choice') return uiDual(t);
  if (ui.kind === 'prompt') return uiPrompt(t);
  if (ui.kind === 'sequence') return uiSequence(t);
  if (ui.kind === 'plan_then_run') return uiPlanRun(t);
  if (ui.kind === 'questions') return uiQuestions(t);
  if (ui.kind === 'form') return uiForm(t);
  openModal(t.title); $('tmBody').innerHTML = '<p class="muted">这个任务暂时只能在高级工具里完成。</p>';
}

function uiChoice(t) {
  const ui = t.ui;
  openModal(t.title);
  $('tmBody').innerHTML = `<p class="muted">${esc(t.why)}</p>` +
    '<div class="optlist">' + ui.options.map((o) => `
      <label class="opt ${o.recommend ? 'opt-rec' : ''}">
        <input type="radio" name="choice" value="${esc(o.value)}" ${o.recommend ? 'checked' : ''}>
        <div><div class="opt-title">${esc(o.title)} ${o.recommend ? '<span class="chip done">推荐</span>' : ''}</div>
        <div class="muted small">${esc(o.desc)}</div></div>
      </label>`).join('') + '</div>' +
    '<p class="muted small">画风定下来之后尽量不要改：改了的话，已经做好的角色形象和画面都得重做。</p>';
  foot(`<button class="btn btn-ghost" data-preview="1">先看看长什么样</button>
        <button class="btn btn-primary" data-ok="1">就用这个画风</button>`);
  $('tmFoot').querySelector('[data-ok]').onclick = () => {
    const v = document.querySelector('input[name=choice]:checked').value;
    runSpec(ui.spec, { [ui.field]: v }, { title: '正在设置画风' });
  };
  $('tmFoot').querySelector('[data-preview]').onclick = () => {
    runSpec(ui.preview_spec, {}, { title: '三种画风的样子' });
  };
}

function uiDual(t) {
  const ui = t.ui;
  openModal(t.title);
  $('tmBody').innerHTML = `<p class="muted">${esc(t.why)}</p>` + ui.groups.map((g) => `
    <div class="group">
      <div class="group-h">${esc(g.label)}</div>
      ${g.options.map((o, i) => `<label class="opt ${o.recommend ? 'opt-rec' : ''}">
        <input type="radio" name="${esc(g.key)}" value="${esc(o.value)}" ${o.recommend || (!g.options.some((x) => x.recommend) && i === 0) ? 'checked' : ''}>
        <div><div class="opt-title">${esc(o.title)}</div><div class="muted small">${esc(o.desc)}</div></div>
      </label>`).join('')}
    </div>`).join('');
  foot('<button class="btn btn-primary" data-ok="1">就这样</button>');
  $('tmFoot').querySelector('[data-ok]').onclick = () => {
    const pairs = ui.groups.map((g) => g.key + '=' + document.querySelector(`input[name="${g.key}"]:checked`).value).join(' ');
    runSpec(ui.spec, { pairs }, { title: '正在记录你的选择' });
  };
}

async function uiPrompt(t) {
  openModal(t.title);
  $('tmBody').innerHTML = `<p>${esc(t.ui.note || '')}</p><p class="muted small">正在准备…</p>`;
  try {
    const d = await api('/api/help', { method: 'POST', body: JSON.stringify({ ws: S.ws, topic: t.ui.topic || t.title }) });
    $('tmBody').innerHTML = `<p>${esc(t.ui.note || '')}</p><pre class="prompt">${esc(d.prompt)}</pre>`;
    foot('<button class="btn btn-primary" data-copy="1">复制这段话</button><span class="muted small">复制后回到 AI 助手对话框粘贴发送即可</span>');
    $('tmFoot').querySelector('[data-copy]').onclick = async () => {
      await navigator.clipboard.writeText(d.prompt);
      $('tmFoot').querySelector('[data-copy]').textContent = '已复制 ✓';
    };
  } catch (e) { $('tmBody').innerHTML = '<p class="muted">暂时取不到内容，请稍后再试。</p>'; }
}

function uiSequence(t) {
  openModal(t.title);
  $('tmBody').innerHTML = `<p class="muted">${esc(t.why)}</p>` + (t.ui.steps || []).map((s, i) => `
    <div class="steprow">
      <button class="btn ${i === 0 ? 'btn-primary' : ''}" data-step="${i}">${esc(s.label)}</button>
      <span class="muted small">${s.confirm ? '会花钱，开始前先告诉你金额' : (s.optional ? '可以跳过' : '不花钱')}</span>
    </div>`).join('');
  foot('<span class="muted small">按顺序来就行；中途可以关掉这个窗口，已经做好的部分不会丢。</span>');
  $('tmBody').querySelectorAll('[data-step]').forEach((b) => {
    b.onclick = () => {
      const s = t.ui.steps[+b.dataset.step];
      runSpec(s.spec, s.params || {}, { confirm: !!s.confirm, title: s.label });
    };
  });
}

function uiPlanRun(t) {
  const ui = t.ui;
  openModal(t.title);
  $('tmBody').innerHTML = `<p class="muted">${esc(t.why)}</p>
    <p>先让电脑算一算这一集要花多少钱（这一步不花钱），算完你看到金额再决定要不要开始。</p>`;
  foot(`<button class="btn" data-plan="1">${esc(ui.free_label || '先算一下要花多少钱')}</button>
        <button class="btn btn-primary" data-run="1" disabled>开始生成（先算钱）</button>`);
  $('tmFoot').querySelector('[data-plan]').onclick = async () => {
    $('tmBody').insertAdjacentHTML('beforeend', '<p class="muted small" id="planWait">正在计算…</p>');
    const r = await doRun(ui.plan_spec, {});
    renderFriendly(r, ui.confirm_title || '预计花费');
    $('tmFoot').querySelector('[data-run]').disabled = false;
    $('tmFoot').querySelector('[data-run]').textContent = '开始生成画面';
  };
  $('tmFoot').querySelector('[data-run]').onclick = () => {
    runSpec(ui.run_spec, ui.params || {}, { confirm: true, title: '生成这一集的画面' });
  };
}

function uiQuestions(t) {
  const ui = t.ui;
  openModal(t.title);
  $('tmBody').innerHTML = `<p class="muted">请如实回答。全部选「没有」才能发布；如果某一项有，系统会告诉你怎么改。</p>` +
    (ui.fields || []).map((f) => `<div class="field"><label>${esc(f.label)}</label>
      <input class="input" data-field="${esc(f.key)}" placeholder="${esc(f.placeholder || '')}"></div>`).join('') +
    (ui.questions || []).map((q) => `<div class="q">
      <div>${esc(q.text)}</div>
      <label class="opt"><input type="radio" name="${esc(q.key)}" value="no" checked><div>没有</div></label>
      <label class="opt"><input type="radio" name="${esc(q.key)}" value="yes"><div>有</div></label>
    </div>`).join('');
  foot('<button class="btn btn-primary" data-ok="1">检查这一集</button>');
  $('tmFoot').querySelector('[data-ok]').onclick = () => {
    const params = {};
    (ui.fields || []).forEach((f) => { params[f.key] = ($('tmBody').querySelector(`[data-field="${f.key}"]`).value || '').trim(); });
    (ui.questions || []).forEach((q) => { params[q.key] = document.querySelector(`input[name="${q.key}"]:checked`).value; });
    if (!params.ep) { alert('请填写要检查哪一集（例如 ep01）'); return; }
    runSpec(ui.spec, params, { title: '发布前检查' });
  };
}

function uiForm(t) {
  const ui = t.ui;
  openModal(t.title);
  $('tmBody').innerHTML = `<p class="muted">${esc(t.why)}</p>` + (ui.fields || []).map((f) => `
    <div class="field"><label>${esc(f.label)}${f.required ? ' *' : ''}</label>
      <input class="input" data-field="${esc(f.key)}" type="${f.kind === 'int' ? 'number' : 'text'}"
        value="${f.default != null ? f.default : ''}" placeholder="${esc(f.placeholder || '')}"></div>`).join('');
  foot('<button class="btn btn-primary" data-ok="1">建立这部剧</button>');
  $('tmFoot').querySelector('[data-ok]').onclick = () => {
    const p = {};
    (ui.fields || []).forEach((f) => { p[f.key] = ($('tmBody').querySelector(`[data-field="${f.key}"]`).value || '').trim(); });
    const miss = (ui.fields || []).filter((f) => f.required && !p[f.key]);
    if (miss.length) { alert('还需要填写：' + miss.map((m) => m.label).join('、')); return; }
    runSpec(ui.spec, p, { title: '正在建立这部剧' });
  };
}

/* ---------------- 执行 ---------------- */
async function doRun(specId, params, confirmPayload) {
  try {
    return await api('/api/run', { method: 'POST', body: JSON.stringify({ ws: S.ws, spec_id: specId, params, confirm: confirmPayload || {} }) });
  } catch (e) {
    if (e.status === 428) return { needConfirm: true, detail: (e.data && e.data.detail) || {} };
    if (e.status === 422) {
      const errs = (e.data && e.data.detail && e.data.detail.errors) || ['填写的内容有点问题'];
      return { friendly: { level: 'fix', title: '填写的内容还有点问题', detail: errs.join('；') } };
    }
    return { friendly: { level: 'error', title: '暂时没能开始', detail: '请稍后再试，或把问题交给 AI 助手。' } };
  }
}

async function runSpec(specId, params, opts) {
  opts = opts || {};
  openModal(opts.title || '正在处理');
  $('tmBody').innerHTML = '<p class="spinner">正在准备…</p>';
  foot('');

  // 需要花钱：先问用户（用金额与人话，不显示命令）
  if (opts.confirm) {
    $('tmBody').innerHTML = `<p>这一步要花钱，确认后就开始。</p>
      <div class="ask-box">${esc(specId === 'video.run' ? '把这一集的镜头交给云端生成，按实际用量扣费。' : '这一步会产生费用，开始前请确认。')}</div>
      <p class="muted small">如果你不确定要花多少，可以先去「先算一下要花多少钱」。</p>`;
    foot('<button class="btn btn-ghost" id="askNo">先不开始</button><button class="btn btn-primary" id="askYes">我确认，开始</button>');
    $('askNo').onclick = () => closeModal();
    $('askYes').onclick = () => { runSpec(specId, params, { title: opts.title }); };
    return;
  }

  const r = await doRun(specId, params);
  if (r.needConfirm) { renderFriendly({ friendly: { level: 'ask', title: '需要你确认', detail: r.detail.reason || '' } }); return; }
  if (r.mode === 'job') { watchJob(r.job.id, opts.title); return; }
  renderFriendly(r);
}

function renderFriendly(r, titleOverride) {
  const f = r.friendly || { level: 'ok', title: '完成了', detail: '' };
  const cls = { ok: 'done', ask: 'amber', fix: 'amber', stop: 'blocked', error: 'blocked' }[f.level] || '';
  $('tmTitle').textContent = titleOverride || $('tmTitle').textContent;
  $('tmBody').innerHTML = `<div class="friendly"><span class="chip ${cls}">${esc(f.title)}</span>
      ${f.detail ? `<div class="muted" style="margin-top:6px">${esc(f.detail)}</div>` : ''}</div>` +
    (r.stdout ? `<details class="raw"><summary>详细记录（给维护者看的）</summary><pre class="log">${esc(r.stdout)}</pre></details>` : '');
  foot('<button class="btn" onclick="location.reload()">回到首页看最新进度</button>');
}

function watchJob(jobId, title) {
  S.jobId = jobId;
  $('tmTitle').textContent = title || '正在做';
  $('tmBody').innerHTML = `<div class="doing"><div class="spinner-dot"></div>
    <div>正在做，请稍等…<div class="muted small" id="doingTime"></div></div></div>
    <p class="muted small">你可以关掉这个窗口去忙别的，进度不会丢。</p>
    <details class="raw"><summary>详细记录（给维护者看的）</summary><pre class="log" id="doingLog"></pre></details>`;
  let n = 0;
  const t0 = Date.now();
  const timer = setInterval(() => {
    $('doingTime').textContent = '已经做了 ' + Math.floor((Date.now() - t0) / 1000) + ' 秒';
  }, 1000);
  if (S.es) S.es.close();
  const es = new EventSource('/api/jobs/' + encodeURIComponent(jobId) + '/stream?after=0');
  S.es = es;
  es.onmessage = async (m) => {
    let d; try { d = JSON.parse(m.data); } catch (e) { return; }
    if (d.kind === 'log') { n++; const pre = $('doingLog'); if (pre) { pre.textContent += d.text + '\n'; pre.scrollTop = pre.scrollHeight; } }
    if (d.kind === 'closed') {
      es.close(); clearInterval(timer);
      const j = await api('/api/jobs/' + encodeURIComponent(jobId));
      const f = j.friendly || { level: 'ok', title: '完成了', detail: '' };
      const cls = { ok: 'done', ask: 'amber', fix: 'amber', stop: 'blocked', error: 'blocked' }[f.level] || '';
      $('tmBody').innerHTML = `<div class="friendly"><span class="chip ${cls}">${esc(f.title)}</span>
        ${f.detail ? `<div class="muted" style="margin-top:6px">${esc(f.detail)}</div>` : ''}</div>
        <p class="muted small">用时约 ${j.elapsed_sec || 0} 秒，共 ${n} 条进度信息。</p>
        <details class="raw"><summary>详细记录（给维护者看的）</summary><pre class="log">${esc($('doingLog') ? $('doingLog').textContent : '')}</pre></details>`;
      foot('<button class="btn btn-primary" onclick="location.reload()">回首页看最新进度</button>');
    }
  };
  es.onerror = () => { es.close(); clearInterval(timer); };
}

/* ---------------- 求助 ---------------- */
$('btnHelp').onclick = async () => {
  const topic = $('helpTopic').value.trim();
  $('helpHint').textContent = '正在整理…';
  try {
    const d = await api('/api/help', { method: 'POST', body: JSON.stringify({ ws: S.ws, topic }) });
    S.help = d.prompt;
    $('helpPrompt').textContent = d.prompt;
    $('helpPrompt').classList.remove('hidden');
    $('btnCopyHelp').disabled = false;
    $('helpHint').textContent = '把上面的话整段复制，发给 AI 助手就行。';
  } catch (e) { $('helpHint').textContent = '暂时没能生成，请稍后再试。'; }
};
$('btnCopyHelp').onclick = async () => {
  await navigator.clipboard.writeText(S.help);
  $('helpHint').textContent = '已复制 ✓';
};

init();
