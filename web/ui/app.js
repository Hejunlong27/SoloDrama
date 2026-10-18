/* SoloDrama 控制台前端 —— 原生 JS + EventSource（离线优先，零外部资源）
 * 设计原则：前端只做展示与「发起」，一切判断在后端与引擎；不接收任何密钥。 */
'use strict';

const state = {
  ws: null,
  catalog: [], groups: [], filterGroup: '', filterText: '',
  selected: null, values: {},
  jobs: [], activeJob: null, es: null, health: null, readonly: false,
};

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

async function api(path, opts) {
  const res = await fetch(path, Object.assign({ headers: { 'Content-Type': 'application/json' } }, opts || {}));
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (e) { data = { raw: text }; }
  if (!res.ok) {
    const err = new Error((data && (data.detail && (data.detail.reason || JSON.stringify(data.detail)) || data.raw)) || res.statusText);
    err.status = res.status; err.data = data;
    throw err;
  }
  return data;
}

/* ---------------- 顶部：工作区 ---------------- */
async function loadWorkspaces() {
  const reg = await api('/api/workspaces');
  const sel = $('wsSelect');
  sel.innerHTML = '';
  if (!reg.items.length) {
    sel.innerHTML = '<option value="">（未登记工作区）</option>';
  }
  reg.items.forEach((it) => {
    const o = document.createElement('option');
    o.value = it.path;
    o.textContent = (it.exists ? '' : '[缺失] ') + it.title + '  —  ' + it.path;
    sel.appendChild(o);
  });
  state.ws = reg.current || (reg.items[0] && reg.items[0].path) || null;
  if (state.ws) sel.value = state.ws;
  return state.ws;
}

/* ---------------- 总览 ---------------- */
function chip(text, cls, title) {
  return `<span class="chip ${cls || ''}" title="${esc(title || '')}">${esc(text)}</span>`;
}

function fmtPct(a, b) { return b ? Math.round((a / b) * 100) : 0; }

async function loadOverview() {
  if (!state.ws) { $('ovEmpty').classList.remove('hidden'); $('ovBody').classList.add('hidden'); return; }
  $('ovEmpty').classList.add('hidden'); $('ovBody').classList.remove('hidden');
  let d;
  try { d = await api('/api/overview?ws=' + encodeURIComponent(state.ws)); }
  catch (e) { $('ovEmpty').classList.remove('hidden'); $('ovEmpty').textContent = '总览加载失败：' + e.message; return; }

  const rounds = d.pipeline || [];
  const done = rounds.filter((r) => r.state === 'done').length;
  $('ovProgressBar').style.width = fmtPct(done, rounds.length) + '%';
  $('ovProgress').textContent = `${done} / ${rounds.length} 环节已完成`;
  const cur = rounds.find((r) => r.state === 'blocked') || rounds.find((r) => r.state !== 'done');
  $('ovCurrent').textContent = cur ? `当前卡点：环节 ${cur.no} ${cur.title} ${cur.detail ? '— ' + cur.detail : ''}` : '链路已跑完';

  const g = (d.gates && d.gates.style) || {}, m = (d.gates && d.gates.models) || {};
  const mImage = m.image || {}, mVideo = m.video || {};
  $('ovGates').innerHTML = [
    `<div>画风（G-1）：${g.confirmed ? chip('已确认', 'done') : chip('未确认 · 退出码 4', 'blocked')} <span class="muted small">${esc(g.label || '')}</span></div>`,
    `<div style="margin-top:6px">出图通道（G0）：${mImage.confirmed ? chip('已确认', 'done') : chip('未确认', 'blocked')} <span class="muted small">${esc(mImage.choice || '')}</span></div>`,
    `<div style="margin-top:6px">出片通道（G0）：${mVideo.confirmed ? chip('已确认', 'done') : chip('未确认', 'blocked')} <span class="muted small">${esc(mVideo.choice || '')}${mVideo.detail && mVideo.detail.workflow_id ? ' · wf ' + esc(mVideo.detail.workflow_id) : ''}</span></div>`,
    `<div style="margin-top:6px" class="muted small">执行依据：${mVideo.evidence_ok === false ? chip('缺失 ' + (mVideo.missing_evidence || []).join('/'), 'blocked') : '齐备'}</div>`,
  ].join('');

  const st = d.status || {};
  const data = st.data || {}, assets = st.assets || {}, led = st.ledger || {}, h3 = st.h3 || {};
  const batches = st.batches || [];
  const tot = batches.reduce((n, b) => n + ((b.totals || {}).total || 0), 0);
  const ok = batches.reduce((n, b) => n + ((b.totals || {}).success || 0), 0);
  const fail = batches.reduce((n, b) => n + ((b.totals || {}).failed || 0), 0);
  $('ovStats').innerHTML = `
    <div>片段 / 提示词：<b>${data.shots || 0}</b> / <b>${data.prompts || 0}</b></div>
    <div>参考图：<b>${(st.refs || []).length}</b> 张（超限 ${(st.refs || []).filter((r) => r.h3_over_limit).length}）</div>
    <div>缺资产：人物 <b>${(assets.missing_characters || []).length}</b> · 场景 <b>${(assets.missing_scenes || []).length}</b></div>
    <div>批次：<b>${batches.length}</b>（段 ${tot}：成功 ${ok} / 失败 ${fail}）</div>
    <div>台账：<b>${led.files || 0}</b> 份 · 消耗 <b>${(led.rh_coins || 0).toFixed ? led.rh_coins.toFixed(0) : led.rh_coins}</b> RH币</div>
    <div>H3 工作流：${h3.ready ? chip('就绪', 'done') : chip('G2 未就绪', 'blocked')} <span class="muted small">${esc(h3.kind || '')} ${esc(h3.id || '')}</span></div>`;

  const nexts = d.next_actions || [];
  $('ovNext').innerHTML = nexts.length
    ? '<ul style="margin:0;padding-left:18px">' + nexts.map((n) => `<li>${esc(n.text)}</li>`).join('') + '</ul>'
    : '<span class="muted">暂无待办提示。</span>';

  const wk = d.workspace || {};
  $('ovLayout').innerHTML = `
    <div class="mono small">布局：${wk.is_new_layout ? '新布局（分阶段编号目录）' : '旧布局（向后兼容）'} · 引擎根：${esc(wk.engine_root || '')}</div>
    <div class="mono small">输入目录：${esc(wk.data_dir || '')}</div>
    <div class="mono small">输出目录：${esc(wk.out_dir || '')}</div>
    <div style="margin-top:8px">${(wk.stages || []).map((s) => chip(`${s.dir}${s.exists ? ' · ' + s.files : ' · 缺'}`, s.exists ? (s.files ? 'done' : 'todo') : 'todo')).join(' ')}</div>`;
}

/* ---------------- 流水线 ---------------- */
async function loadPipeline() {
  if (!state.ws) return;
  let d;
  try { d = await api('/api/pipeline?ws=' + encodeURIComponent(state.ws)); } catch (e) { return; }
  const rounds = d.rounds || [];
  $('plTable').innerHTML = `<table><thead><tr><th style="width:70px">环节</th><th>名称</th>
    <th style="width:110px">状态</th><th>证据 / 说明</th><th style="width:100px">操作</th></tr></thead><tbody>` +
    rounds.map((r) => `<tr><td class="mono">${esc(r.no)}</td><td>${esc(r.title)}</td>
      <td>${chip({ done: '已完成', doing: '进行中', blocked: '受阻', todo: '未开始' }[r.state] || r.state, r.state)}</td>
      <td class="muted small">${esc(r.detail || '')}</td>
      <td><button class="btn btn-mini" data-round="${esc(r.no)}">看命令</button></td></tr>`).join('') +
    '</tbody></table>';
  $('plTable').querySelectorAll('button[data-round]').forEach((b) => {
    b.onclick = () => showRoundCommands(b.dataset.round);
  });
}

function showRoundCommands(round) {
  const items = state.catalog.filter((c) => (c.group || '').startsWith(round + ' '));
  $('plCmdsRound').textContent = '（环节 ' + round + '）';
  if (!items.length) { $('plCmds').innerHTML = '<span class="muted">该环节无独立命令（由会话内技能完成）。</span>'; return; }
  $('plCmds').innerHTML = '<table><thead><tr><th>命令</th><th>说明</th><th style="width:90px">计费</th><th style="width:90px">门禁</th><th style="width:80px"></th></tr></thead><tbody>' +
    items.map((c) => `<tr><td class="mono small">${esc(c.id)}<div>${esc(c.title)}</div></td>
      <td class="muted small">${esc(c.help || '')}</td><td>${esc(c.billing_label)}</td>
      <td>${c.gate ? chip(c.gate, 'amber') : '<span class="muted">—</span>'}</td>
      <td><button class="btn btn-mini" data-cmd="${esc(c.id)}">打开</button></td></tr>`).join('') + '</tbody></table>';
  $('plCmds').querySelectorAll('button[data-cmd]').forEach((b) => {
    b.onclick = () => { switchTab('panel'); selectCmd(b.dataset.cmd); };
  });
}

/* ---------------- 命令面板 ---------------- */
async function loadCommands() {
  const d = await api('/api/commands' + (state.ws ? '?ws=' + encodeURIComponent(state.ws) : ''));
  state.catalog = d.items || [];
  state.groups = d.groups || [];
  state.readonly = !!d.readonly;
  $('roBadge').classList.toggle('hidden', !d.readonly);
  renderGroups(); renderCmdList();
}

function renderGroups() {
  $('cmdGroups').innerHTML = ['<span class="chip' + (state.filterGroup ? '' : ' done') + '" data-g="">全部</span>']
    .concat(state.groups.map((g) => `<span class="chip ${state.filterGroup === g ? 'done' : ''}" data-g="${esc(g)}">${esc(g)}</span>`))
    .join('');
  $('cmdGroups').querySelectorAll('.chip').forEach((el) => {
    el.onclick = () => { state.filterGroup = el.dataset.g; renderGroups(); renderCmdList(); };
  });
}

function renderCmdList() {
  const kw = state.filterText.trim().toLowerCase();
  const items = state.catalog.filter((c) =>
    (!state.filterGroup || c.group === state.filterGroup) &&
    (!kw || [c.id, c.title, c.help, c.group, c.gate || ''].join(' ').toLowerCase().includes(kw)));
  $('cmdList').innerHTML = items.map((c) => `<li data-cmd="${esc(c.id)}" class="${state.selected && state.selected.id === c.id ? 'active' : ''}">
      <div>${esc(c.title)} ${c.gate ? chip(c.gate, 'amber') : ''} ${c.billing === 'paid' ? chip('★计费', 'blocked') : ''}</div>
      <div class="cmd-id mono">${esc(c.group)} · ${esc(c.id)}</div></li>`).join('');
  $('cmdList').querySelectorAll('li').forEach((el) => {
    el.onclick = () => selectCmd(el.dataset.cmd);
  });
}

function selectCmd(id) {
  const cmd = state.catalog.find((c) => c.id === id);
  if (!cmd) return;
  state.selected = cmd;
  state.values = {};
  (cmd.params || []).forEach((p) => { if (p.default !== null && p.default !== undefined) state.values[p.key] = p.default; });
  $('cmdTitle').textContent = cmd.title + '  ·  ' + cmd.id;
  $('cmdMeta').innerHTML = [
    chip(cmd.group, 'info'),
    chip(cmd.billing_label, cmd.billing === 'paid' ? 'blocked' : (cmd.billing === 'free' ? 'done' : 'amber')),
    cmd.gate ? chip('门禁 ' + cmd.gate, 'amber') : '',
    cmd.danger === 2 ? chip('危险操作', 'blocked') : (cmd.danger === 1 ? chip('会写盘', 'amber') : chip('只读', 'done')),
    cmd.mode === 'job' ? chip('作业化执行', 'info') : chip('即时返回', ''),
    cmd.resources && cmd.resources.length ? chip('占用 ' + cmd.resources.join('/'), 'amber') : '',
  ].join(' ');
  renderCmdForm(cmd); renderCmdList();
}

function renderCmdForm(cmd) {
  const f = $('cmdForm');
  if (!cmd.params.length) { f.innerHTML = '<div class="muted">本命令无需参数。</div>'; }
  else {
    f.innerHTML = cmd.params.map((p) => {
      const v = state.values[p.key];
      if (p.kind === 'bool') {
        return `<div class="row"><label>${esc(p.label)}</label><div class="ctl">
          <input type="checkbox" data-key="${esc(p.key)}" ${v ? 'checked' : ''}>
          <span class="hint">${esc(p.help || '')}</span></div></div>`;
      }
      if (p.kind === 'enum') {
        return `<div class="row"><label>${esc(p.label)}${p.required ? ' *' : ''}</label><div class="ctl">
          <select data-key="${esc(p.key)}">${p.choices.map((c) => `<option value="${esc(c)}" ${String(v) === String(c) ? 'selected' : ''}>${esc(c)}</option>`).join('')}</select>
          <div class="hint">${esc(p.help || '')}</div></div></div>`;
      }
      const type = p.kind === 'int' ? 'number' : 'text';
      return `<div class="row"><label>${esc(p.label)}${p.required ? ' *' : ''}</label><div class="ctl">
        <input type="${type}" data-key="${esc(p.key)}" value="${esc(v == null ? '' : v)}" placeholder="${esc(p.placeholder || '')}">
        <div class="hint">${esc(p.help || '')}</div></div></div>`;
    }).join('');
  }
  f.querySelectorAll('[data-key]').forEach((el) => {
    const handler = () => {
      const k = el.dataset.key;
      state.values[k] = el.type === 'checkbox' ? el.checked : el.value;
      updateArgv();
    };
    el.addEventListener(el.type === 'checkbox' || el.tagName === 'SELECT' ? 'change' : 'input', handler);
  });
  updateArgv();
}

function updateArgv() {
  const cmd = state.selected;
  if (!cmd) return;
  const preview = (cmd.argv_preview || '');
  $('cmdArgv').textContent = 'python ' + preview.replace(/"[^"]*"?\s*$/, '').trim() + ' ' + buildTail(cmd);
  $('cmdHint').textContent = cmd.mode === 'job' ? '将以作业方式执行（可在「作业」页看实时日志）' : '即时返回结果';
  const prompt = cmd.agent_prompt || '';
  $('cmdPrompt').textContent = withValues(prompt);
  $('btnRun').disabled = false;
}

function buildTail(cmd) {
  const parts = [];
  (cmd.params || []).forEach((p) => {
    const v = state.values[p.key];
    if (p.kind === 'bool') { if (v) parts.push('--' + p.key.replace(/_/g, '-')); return; }
    if (v === '' || v == null) return;
  });
  return parts.join(' ');
}

/* Agent 提示词里的命令按当前参数替换（前端仅做展示，真实 argv 由后端构造） */
function withValues(prompt) {
  const cmd = state.selected;
  if (!cmd) return prompt;
  return prompt;
}

async function runSelected() {
  const cmd = state.selected;
  if (!cmd) return;
  if (!state.ws) { alert('请先选择工作区'); return; }
  const go = async (confirmPayload) => {
    $('cmdResult').classList.remove('hidden');
    $('cmdResult').innerHTML = '<span class="muted">执行中…</span>';
    try {
      const r = await api('/api/run', {
        method: 'POST',
        body: JSON.stringify({ ws: state.ws, spec_id: cmd.id, params: state.values, confirm: confirmPayload || {} }),
      });
      if (r.mode === 'job') {
        $('cmdResult').innerHTML = `<div>已入队：<b>${esc(r.job.id)}</b>（${esc(r.job.title)}）</div>
          <div class="muted small">到「作业」页可看实时日志；退出码 4 表示等待你确认。</div>`;
        loadJobs();
      } else {
        const cls = r.rc === 0 ? 'done' : (r.rc === 2 || r.rc === 4 ? 'amber' : 'blocked');
        $('cmdResult').innerHTML = `<div>${chip('退出码 ' + r.rc + ' · ' + r.exit.text, cls)} <span class="muted small">用时 ${r.elapsed}s</span></div>
          <pre>${esc(r.stdout || '(无输出)')}</pre>`;
      }
    } catch (e) {
      if (e.status === 428 && e.data && e.data.detail && e.data.detail.need_confirm) {
        askConfirm(e.data.detail, cmd);
        $('cmdResult').innerHTML = '<span class="muted">等待你在弹窗中确认。</span>';
        return;
      }
      $('cmdResult').innerHTML = `<div class="chip blocked">失败</div><pre>${esc(e.message)}</pre>`;
    }
  };
  if (cmd.billing === 'paid' || cmd.danger === 2) {
    askConfirm({ reason: cmd.billing === 'paid' ? '本命令★计费，需确认' : '本命令会写盘/覆盖产物', argv_preview: cmd.argv_preview }, cmd, go);
  } else { go({}); }
}

/* ---------------- 确认弹窗 ---------------- */
let confirmCb = null;
function askConfirm(detail, cmd, cb) {
  confirmCb = cb;
  $('confirmTitle').textContent = '确认执行：' + (cmd ? cmd.title : '');
  const needBatch = detail.expect_batch ? `<div style="margin-top:8px">续跑批次号（必须与参数一致）：<b>${esc(detail.expect_batch)}</b>
    <div style="margin-top:6px"><input id="confirmBatch" class="input" placeholder="粘贴批次号以二次确认"></div></div>` : '';
  $('confirmBody').innerHTML = `<div>${esc(detail.reason || '')}</div>
    <div class="argv" style="margin-top:8px">${esc(cmd ? 'python ' + cmd.argv_preview : '')}</div>
    <div class="muted small">执行记录将写入审计表（时间 / 命令 / 退出码）。</div>${needBatch}`;
  $('confirmModal').classList.remove('hidden');
}
$('confirmCancel').onclick = () => { $('confirmModal').classList.add('hidden'); confirmCb = null; };
$('confirmOk').onclick = () => {
  $('confirmModal').classList.add('hidden');
  const cb = confirmCb; confirmCb = null;
  const batchEl = $('confirmBatch');
  if (batchEl && !batchEl.value.trim()) { alert('请粘贴批次号以完成二次确认'); return; }
  if (cb) cb({ ack: true, batch: batchEl ? batchEl.value.trim() : '', at: new Date().toISOString() });
};

/* ---------------- 作业 ---------------- */
async function loadJobs() {
  const d = await api('/api/jobs' + (state.ws ? '?ws=' + encodeURIComponent(state.ws) : ''));
  state.jobs = d.items || [];
  updateLocks(d.locks);
  $('jobList').innerHTML = state.jobs.length ? ('<table><thead><tr><th>作业</th><th>命令</th><th>状态</th><th>退出码</th><th>耗时</th><th></th></tr></thead><tbody>' +
    state.jobs.map((j) => {
      const dur = j.started_at ? ((j.ended_at || (Date.now() / 1000)) - j.started_at) : 0;
      const cls = j.status === 'done' ? 'done' : (j.status === 'running' ? 'doing' : (j.status === 'queued' ? 'todo' : 'blocked'));
      return `<tr class="clickable" data-job="${esc(j.id)}">
        <td class="mono small">${esc(j.id)}</td>
        <td>${esc(j.title)}<div class="cmd-id mono">${esc(j.spec_id)}</div></td>
        <td>${chip(j.status, cls)}</td>
        <td>${j.exit_code === null || j.exit_code === undefined ? '<span class="muted">—</span>' : esc(j.exit_code) + (j.exit ? ' ' + esc(j.exit.text) : '')}</td>
        <td class="mono small">${dur ? dur.toFixed(0) + 's' : ''}</td>
        <td><button class="btn btn-mini" data-log="${esc(j.id)}">日志</button></td></tr>`;
    }).join('') + '</tbody></table>') : '<span class="muted">暂无作业。</span>';
  $('jobList').querySelectorAll('[data-log]').forEach((b) => { b.onclick = (e) => { e.stopPropagation(); openJob(b.dataset.log); }; });
  $('jobList').querySelectorAll('tr[data-job]').forEach((tr) => { tr.onclick = () => openJob(tr.dataset.job); });
}

function updateLocks(l) {
  if (!l) return;
  $('locksBadge').textContent = `GPU ${l.summary.gpu} · RH ${l.summary.rh}`;
}

async function openJob(id) {
  state.activeJob = id;
  const d = await api('/api/jobs/' + encodeURIComponent(id));
  $('jobDetailCard').classList.remove('hidden');
  const j = d.job;
  $('jobDetailTitle').textContent = '作业 ' + j.id + ' · ' + j.title;
  $('jobDetailMeta').innerHTML = [
    chip(j.status, j.status === 'done' ? 'done' : (j.status === 'running' ? 'doing' : 'blocked')),
    j.exit ? chip('退出码 ' + j.exit.code + ' · ' + j.exit.text, j.exit.kind === 'ok' ? 'done' : 'blocked') : '',
    chip(j.billing_label || j.billing, 'info'),
    j.gate ? chip('门禁 ' + j.gate, 'amber') : '',
    j.resources && j.resources.length ? chip('占用 ' + j.resources.join('/'), 'amber') : '',
  ].join(' ');
  $('jobLog').textContent = (d.events || []).map((e) => e.text).join('\n');
  subscribeJob(id, (d.events && d.events.length) ? d.events[d.events.length - 1].seq : 0);
}

function subscribeJob(id, after) {
  if (state.es) { state.es.close(); state.es = null; }
  const es = new EventSource('/api/jobs/' + encodeURIComponent(id) + '/stream?after=' + (after || 0));
  state.es = es;
  es.onmessage = (m) => {
    let d; try { d = JSON.parse(m.data); } catch (e) { return; }
    if (d.kind === 'closed') { es.close(); loadJobs(); return; }
    const pre = $('jobLog');
    pre.textContent += (pre.textContent ? '\n' : '') + d.text;
    pre.scrollTop = pre.scrollHeight;
  };
  es.onerror = () => { es.close(); };
}

$('btnJobCancel').onclick = async () => {
  if (!state.activeJob) return;
  if (!confirm('确认取消该作业？子进程树会被终止；已提交的云端任务请用续跑命令处理。')) return;
  await api('/api/jobs/' + encodeURIComponent(state.activeJob) + '/cancel', { method: 'POST' });
  loadJobs();
};

/* ---------------- 诊断 ---------------- */
async function loadHealth() {
  state.health = await api('/api/health');
  const h = state.health;
  $('diagEnv').innerHTML = `
    <div class="mono small">仓库：${esc(h.repo)}</div>
    <div class="mono small">引擎解释器：${esc(h.python)}</div>
    <div class="mono small">只读模式：${h.readonly ? '开' : '关'} · 资源锁：GPU ${esc(h.locks.summary.gpu)} / RH ${esc(h.locks.summary.rh)}</div>
    <div class="mono small">锁明细：${Object.entries(h.locks.used).map(([k, v]) => esc(k) + '→' + esc(String(v).slice(0, 18))).join(' · ') || '全部空闲'}</div>`;
  updateLocks(h.locks);
}

async function loadAudit() {
  const d = await api('/api/audit?limit=50');
  const items = d.items || [];
  $('diagAudit').innerHTML = items.length ? ('<table><thead><tr><th>时间</th><th>命令</th><th>退出码</th><th>备注</th></tr></thead><tbody>' +
    items.map((a) => `<tr><td class="mono small">${new Date(a.ts * 1000).toLocaleString()}</td>
      <td class="mono small">${esc(a.spec_id)}</td><td>${esc(a.exit_code)}</td><td class="muted small">${esc(a.note || a.estimate || '')}</td></tr>`).join('') +
    '</tbody></table>') : '<span class="muted">尚无记录。</span>';
}

/* ---------------- 交互绑定 ---------------- */
function switchTab(name) {
  document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('active', t.dataset.tab === name));
  document.querySelectorAll('.tabpane').forEach((p) => p.classList.toggle('active', p.id === 'tab-' + name));
  if (name === 'jobs') loadJobs();
  if (name === 'diag') { loadHealth(); loadAudit(); }
}
document.querySelectorAll('.tab').forEach((t) => { t.onclick = () => switchTab(t.dataset.tab); });

$('wsSelect').onchange = async () => {
  state.ws = $('wsSelect').value;
  await api('/api/workspaces/current', { method: 'POST', body: JSON.stringify({ path: state.ws }) });
  refreshAll();
};

$('btnAddWs').onclick = async () => {
  const p = prompt('输入剧项目工作区路径（含 layout.json / model-plan.json / video-pipeline）：');
  if (!p) return;
  try {
    const reg = await api('/api/workspaces', { method: 'POST', body: JSON.stringify({ path: p }) });
    state.ws = reg.current; await loadWorkspaces(); refreshAll();
  } catch (e) { alert('登记失败：' + e.message); }
};

$('btnRefresh').onclick = () => refreshAll();
$('btnJobsRefresh').onclick = () => loadJobs();
$('cmdSearch').oninput = (e) => { state.filterText = e.target.value; renderCmdList(); };
$('btnRun').onclick = () => runSelected();
$('btnCopyPrompt').onclick = async () => {
  try { await navigator.clipboard.writeText($('cmdPrompt').textContent); $('btnCopyPrompt').textContent = '已复制'; setTimeout(() => { $('btnCopyPrompt').textContent = '复制'; }, 1200); }
  catch (e) { alert('复制失败，请手动选择文本。'); }
};

async function refreshAll() {
  if (!state.ws) { await loadWorkspaces(); }
  await Promise.all([loadOverview(), loadPipeline(), loadCommands(), loadJobs()]);
  if ($('tab-diag').classList.contains('active')) { loadHealth(); loadAudit(); }
}

(async function init() {
  await loadWorkspaces();
  await refreshAll();
  setInterval(() => { if ($('tab-jobs').classList.contains('active')) loadJobs(); }, 5000);
})();
