/* 任务中心：作业列表 / 日志（SSE）/ 取消 / 安全重试
   状态语义与退出码对齐：0 成功 · 2 门禁 · 3 熔断 · 4 待确认 · 130 中断 */
import { api, streamJob } from '../api.js';
import { esc, icon, badge, dot, dt, openDrawer, openModal, confirmCost, toast, stamp, emptyBox, paintIcons } from '../ui.js';

const TABS = [
  { key: 'all', label: '全部' },
  { key: 'running', label: '运行中' },
  { key: 'confirm', label: '待确认' },
  { key: 'done', label: '已完成' },
  { key: 'failed', label: '失败' }
];

let tab = 'all';

const STATE = {
  queued: ['todo', '排队中'],
  running: ['doing', '执行中'],
  done: ['done', '已完成'],
  gate: ['fail', '门禁未过'],
  fuse: ['fail', '已熔断'],
  confirm: ['confirm', '待确认'],
  interrupted: ['fail', '已中断'],
  failed: ['fail', '失败'],
  canceled: ['todo', '已取消']
};

function stOf(j) { return STATE[j.status] || ['todo', j.status || '未知']; }

function group(items) {
  return {
    all: items,
    running: items.filter((j) => ['running', 'queued'].indexOf(j.status) >= 0),
    confirm: items.filter((j) => j.status === 'confirm'),
    done: items.filter((j) => j.status === 'done'),
    failed: items.filter((j) => ['failed', 'gate', 'fuse', 'interrupted', 'canceled'].indexOf(j.status) >= 0)
  };
}

export async function render(ctx) {
  const d = await api.jobs(ctx.ws, 60);
  const items = d.items || [];
  const g = group(items);
  const list = g[tab] || items;

  const rows = list.map((j) => {
    const [s, txt] = stOf(j);
    return '<tr class="clickable" data-job="' + esc(j.id) + '">'
      + '<td style="width:22px">' + dot(s) + '</td>'
      + '<td><div>' + esc(j.title) + '</div><div class="row-sub">' + esc(txt)
      + (j.estimate ? ' · ' + esc(j.estimate) : '') + '</div></td>'
      + '<td class="small muted">' + esc(String(j.ws || '').split(/[\\/]/).pop() || '—') + '</td>'
      + '<td class="mono small dim">' + esc(dt(j.started_at || j.created_at)) + '</td>'
      + '<td class="num">' + (j.exit_code === null || j.exit_code === undefined ? '—' : j.exit_code) + '</td>'
      + '<td class="right">' + actButtons(j) + '</td></tr>';
  }).join('') || '<tr><td colspan="6">' + emptyBox('这个分类下没有任务',
    '作业在服务端执行，刷新浏览器不会丢；失败与待确认会分别归类。') + '</td></tr>';

  const html = ''
    + '<div class="page-head"><div><h1 class="page-title">任务中心</h1>'
    + '<div class="page-sub">' + items.length + ' 条作业记录 · 数据来自服务端作业库（sqlite）</div></div>'
    + '<div class="page-actions"><button class="btn quiet" id="btnJobsRefresh">'
    + icon('refresh', 14) + ' 刷新</button></div></div>'

    + '<div class="tabs">'
    + TABS.map((t) => '<button class="tab' + (tab === t.key ? ' active' : '') + '" data-tab="' + t.key + '">'
      + t.label + '<span class="count">' + (g[t.key] || []).length + '</span></button>').join('')
    + '<span class="spacer"></span><span class="tiny dim">退出码 0 成功 · 2 门禁 · 3 熔断 · 4 待确认 · 130 中断</span>'
    + '</div>'

    + '<section class="card"><div class="card-b tight"><div class="table-wrap">'
    + '<table class="tb"><thead><tr><th></th><th>任务</th><th style="width:120px">项目</th>'
    + '<th style="width:110px">开始</th><th class="num" style="width:56px">退出</th><th style="width:190px"></th>'
    + '</tr></thead><tbody>' + rows + '</tbody></table></div></div>'
    + '<div class="card-foot">' + stamp('作业库 · 实时') + '<span class="spacer"></span>'
    + '<span class="tiny dim">「待确认」既不是成功也不是失败：引擎在等你决定（例如要不要花钱）</span></div></section>';

  return {
    html,
    mount: (root) => {
      root.querySelectorAll('[data-tab]').forEach((b) => {
        b.onclick = () => { tab = b.dataset.tab; ctx.refresh(); };
      });
      const rf = root.querySelector('#btnJobsRefresh');
      if (rf) rf.onclick = () => ctx.refresh();
      root.querySelectorAll('[data-job]').forEach((tr) => {
        tr.onclick = (e) => { if (!e.target.closest('button')) openJob(ctx, tr.dataset.job); };
      });
      root.querySelectorAll('[data-log]').forEach((b) => {
        b.onclick = (e) => { e.stopPropagation(); openJob(ctx, b.dataset.log); };
      });
      root.querySelectorAll('[data-cancel]').forEach((b) => {
        b.onclick = (e) => { e.stopPropagation(); cancelJob(ctx, b.dataset.cancel); };
      });
      root.querySelectorAll('[data-retry]').forEach((b) => {
        b.onclick = (e) => { e.stopPropagation(); retryJob(ctx, items.find((j) => j.id === b.dataset.retry)); };
      });
      paintIcons(root);
    }
  };
}

function actButtons(j) {
  const out = ['<button class="btn quiet sm" data-log="' + esc(j.id) + '">日志</button>'];
  if (['running', 'queued'].indexOf(j.status) >= 0) {
    out.push('<button class="btn danger sm" data-cancel="' + esc(j.id) + '">取消</button>');
  } else if (j.status === 'confirm') {
    out.push('<button class="btn primary sm" data-log="' + esc(j.id) + '">去确认</button>');
  } else if (['failed', 'gate', 'interrupted'].indexOf(j.status) >= 0) {
    out.push('<button class="btn quiet sm" data-retry="' + esc(j.id) + '">重试</button>');
  } else if (j.status === 'fuse') {
    out.push('<button class="btn sm" disabled title="熔断后禁止重试，先排障">重试</button>');
  }
  return out.join(' ');
}

async function openJob(ctx, id) {
  let d;
  try { d = await api.job(id); } catch (e) { toast('读不到作业：' + (e.detail || e.message), 'bad'); return; }
  const j = d.job || {};
  const [s, txt] = stOf(j);
  const events = d.events || [];
  const logLines = events.filter((e) => e.kind === 'log' || e.kind === 'system' || e.kind === 'end')
    .map((e) => '<div class="ln"><span class="no">' + e.seq + '</span><span class="'
      + (String(e.text).indexOf('[FAIL]') >= 0 || String(e.text).indexOf('[WARN]') >= 0 ? 'w' : '') + '">'
      + esc(e.text) + '</span></div>').join('');

  const foot = ['<button class="btn quiet" id="jobCopy" title="生成给 AI 助手的诊断文本">'
    + icon('copy', 14) + ' 复制诊断</button><span class="spacer"></span>',
  ['running', 'queued'].indexOf(j.status) >= 0
    ? '<button class="btn danger" id="jobCancel">取消任务</button>' : '',
  ['failed', 'gate', 'interrupted'].indexOf(j.status) >= 0
    ? '<button class="btn quiet" id="jobRetry">安全重试</button>' : '',
  '<button class="btn quiet" data-close="drawer">关闭</button>'].join('');

  openDrawer({
    title: '任务 · ' + (j.title || id),
    html: '<div class="row" style="margin-bottom:12px">'
      + '<span class="state ' + s + '">' + dot(s) + esc(txt) + '</span>'
      + (j.billing === 'paid' ? badge('warn', '计费') : '')
      + '<span class="spacer"></span><span class="mono small dim">' + esc(j.id) + '</span></div>'
      + (d.friendly ? '<div class="alert ' + (d.friendly.level === 'ok' ? 'ok'
        : d.friendly.level === 'stop' ? 'bad' : 'warn') + '" style="margin-bottom:12px">'
        + '<span class="nav-ico">' + icon('alert', 14) + '</span><div><b>' + esc(d.friendly.title) + '</b>'
        + (d.friendly.detail ? '<br><span class="small">' + esc(d.friendly.detail) + '</span>' : '')
        + '</div></div>' : '')
      + '<dl class="kv" style="margin-bottom:12px">'
      + '<dt>动作</dt><dd class="mono">' + esc(j.spec_id || '—') + '</dd>'
      + '<dt>项目</dt><dd class="mono">' + esc(j.ws || '—') + '</dd>'
      + '<dt>预估费用</dt><dd>' + esc(j.estimate || '—') + '</dd>'
      + '<dt>开始 / 耗时</dt><dd class="mono">' + esc(dt(j.started_at || j.created_at))
      + ' · ' + esc(String(d.elapsed_sec || 0) + 's') + '</dd>'
      + '<dt>实际命令</dt><dd class="mono">' + esc(j.argv_display || '—') + '</dd></dl>'
      + '<div class="card-h" style="padding:0 0 6px;border:0"><h3>日志</h3>'
      + '<span class="card-sub">已打码 · 密钥不出后端</span>'
      + (j.status === 'running' ? '<span class="spacer"></span><span class="badge live">实时</span>' : '')
      + '</div>'
      + '<pre class="log" id="jobLog">' + (logLines || '（还没有输出）') + '</pre>',
    foot,
    mount: (root) => {
      const logBox = root.querySelector('#jobLog');
      logBox.scrollTop = logBox.scrollHeight;
      const before = events.length ? events[events.length - 1].seq : 0;
      const cancel = root.querySelector('#jobCancel');
      if (cancel) cancel.onclick = () => cancelJob(ctx, id, true);
      const retry = root.querySelector('#jobRetry');
      if (retry) retry.onclick = () => retryJob(ctx, j);
      const copy = root.querySelector('#jobCopy');
      if (copy) copy.onclick = async () => {
        const text = ['【SoloDrama Studio 诊断】', '动作：' + (j.spec_id || ''), '项目：' + (j.ws || ''),
          '状态：' + (j.status || ''), '退出码：' + (j.exit_code === null ? '—' : j.exit_code),
          '', '日志尾部：', logBox.textContent.slice(-2000)].join('\n');
        try { await navigator.clipboard.writeText(text); toast('已复制诊断文本'); }
        catch (e) { toast('复制失败（浏览器限制）', 'warn'); }
      };
      if (j.status === 'running') {
        const close = streamJob(id, before, {
          onEvent: (ev) => {
            if (ev.kind === 'closed') { close(); return; }
            const div = document.createElement('div');
            div.className = 'ln';
            div.innerHTML = '<span class="no">' + ev.seq + '</span><span class="'
              + (String(ev.text).indexOf('[FAIL]') >= 0 ? 'e' : String(ev.text).indexOf('[WARN]') >= 0 ? 'w' : '')
              + '">' + esc(ev.text) + '</span>';
            logBox.appendChild(div);
            logBox.scrollTop = logBox.scrollHeight;
          }
        });
        const onClosed = () => { close(); window.removeEventListener('studio:drawer-closed', onClosed); };
        window.addEventListener('studio:drawer-closed', onClosed);
      }
    }
  });
}

function cancelJob(ctx, id, fromDrawer) {
  openModal({
    title: '取消任务',
    icon: 'alert',
    tone: 'bad',
    html: '<div class="small">将终止该任务的子进程树。已完成的产物保留，未完成的段可以之后续跑。</div>'
      + '<div class="alert info" style="margin-top:12px"><span class="nav-ico">' + icon('alert', 14) + '</span>'
      + '<div>取消不产生额外费用；已提交到云端并成功的段仍按平台用量计费。</div></div>',
    foot: '<span class="spacer"></span><button class="btn quiet" data-close="modal">返回</button>'
      + '<button class="btn danger" id="okCancel">确认取消</button>',
    mount: () => {
      document.getElementById('okCancel').onclick = async () => {
        try {
          await api.cancelJob(id);
          document.getElementById('modal').classList.remove('on');
          toast('已请求取消', 'warn');
          if (fromDrawer) { const b = document.querySelector('[data-close="drawer"]'); if (b) b.click(); }
          ctx.refresh();
        } catch (e) { toast('取消失败：' + (e.detail || e.message), 'bad'); }
      };
    }
  });
}

function retryJob(ctx, job) {
  if (!job) return;
  if (job.status === 'fuse') { toast('熔断的任务不允许重试，请先排障', 'bad'); return; }
  const params = job.values || {};
  const isPaid = job.billing === 'paid';
  const run = (extra) => {
    import('../action.js').then((m) => {
      m.runAction(ctx, {
        specId: job.spec_id,
        params,
        title: '重试 · ' + (job.title || job.spec_id),
        confirm: extra,
        onDone: () => ctx.refresh()
      });
    });
  };
  if (isPaid) {
    confirmCost({
      title: '重试计费任务',
      lines: [
        ['动作', job.spec_id],
        ['参数', JSON.stringify(params).slice(0, 80)],
        ['续跑', params.resume ? ('批次 ' + params.resume + '（不重提已成功段）') : '未带批次（等于新批次，会重复提交）']
      ],
      note: '计费任务重试必须带批次号；本页面沿用原参数提交，请确认参数里的批次号是否正确。',
      total: job.estimate || '以平台用量为准',
      onOk: () => run({ ack: true })
    });
  } else {
    run({});
  }
}
