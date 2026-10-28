/* ============================================================
   action.js —— 统一的「执行一个引擎动作」入口
   所有页面都走这里，保证四件事一致：
     1) 只读模式拦截；2) 计费先出确认单；3) 执行中有 loading；4) 结果统一翻译退出码。
   注：真正执行的是后端 /api/run（白名单 + 作业队列），浏览器从不拼命令。
   ============================================================ */
import { api } from './api.js';
import { confirmCost, esc, icon, openModal, toast } from './ui.js';

const EXIT = {
  0: { tone: 'ok', label: '成功' },
  1: { tone: 'bad', label: '执行出错' },
  2: { tone: 'warn', label: '门禁未过（要修）' },
  3: { tone: 'bad', label: '已熔断（保护费用）' },
  4: { tone: 'warn', label: '等待你确认' },
  130: { tone: 'warn', label: '被中断' }
};

function resultHtml(res) {
  if (res.mode === 'job') {
    const j = res.job || {};
    return '<div class="alert live" style="margin-bottom:12px"><span class="nav-ico">' + icon('clock', 14)
      + '</span><div>已加入作业队列：<b>' + esc(j.title || '') + '</b>'
      + '<br><span class="small">作业在服务端执行，离开本页也不会中断；到「任务中心」看实时日志。</span></div></div>'
      + '<div class="row"><button class="btn primary" id="actGoTasks">去任务中心</button></div>';
  }
  const rc = res.rc;
  const meta = EXIT[rc] || { tone: 'bad', label: '未知退出码 ' + rc };
  const f = res.friendly || {};
  const out = (res.stdout || '').split('\n').slice(-200).join('\n');
  return '<div class="row gap8" style="margin-bottom:10px">'
    + '<span class="badge ' + (meta.tone === 'ok' ? 'ok' : meta.tone === 'bad' ? 'bad' : 'warn') + '">'
    + esc(meta.label) + '</span>'
    + '<span class="mono small dim">退出码 ' + esc(String(rc)) + ' · ' + esc((res.elapsed || 0) + 's') + '</span>'
    + '</div>'
    + (f.title ? '<div class="alert ' + (f.level === 'ok' ? 'ok' : f.level === 'stop' ? 'bad' : 'warn')
      + '" style="margin-bottom:10px"><span class="nav-ico">' + icon('alert', 14) + '</span><div>'
      + esc(f.title) + (f.detail ? '<br><span class="small">' + esc(f.detail) + '</span>' : '') + '</div></div>' : '')
    + '<div class="card-h" style="padding:0 0 6px;border:0"><h3>输出</h3>'
    + '<span class="card-sub">原样文本，仅用于排障</span></div>'
    + '<pre class="log">' + esc(out || '（没有输出）') + '</pre>';
}

export async function doRun(ctx, opts) {
  openModal({
    title: opts.title || '执行中',
    icon: 'clock',
    html: '<div class="row"><span class="spinner"></span><span class="small muted">正在调用引擎，请稍候…</span></div>'
      + '<div class="tiny dim" style="margin-top:10px">动作：<span class="mono">' + esc(opts.specId) + '</span></div>',
    foot: ''
  });
  let res;
  try {
    res = await api.run({
      ws: ctx.ws,
      spec_id: opts.specId,
      params: opts.params || {},
      confirm: opts.confirm || {},
      note: opts.note || 'studio'
    });
  } catch (err) {
    const detail = err.detail || err.message || '';
    let extra = '';
    if (err.status === 428) extra = '<div class="alert warn" style="margin-top:10px"><span class="nav-ico">'
      + icon('alert', 14) + '</span><div>这次动作需要显式确认（引擎门禁）。</div></div>';
    if (err.status === 422) extra = '<div class="alert bad" style="margin-top:10px"><span class="nav-ico">'
      + icon('alert', 14) + '</span><div>参数不合规，已在服务端拦下。</div></div>';
    openModal({
      title: '没有执行',
      icon: 'alert',
      tone: 'bad',
      html: extra + '<pre class="log">' + esc(typeof detail === 'string' ? detail : JSON.stringify(detail, null, 2)) + '</pre>',
      foot: '<span class="spacer"></span><button class="btn quiet" data-close="modal">关闭</button>'
    });
    return null;
  }

  openModal({
    title: opts.title || '执行结果',
    icon: 'check',
    tone: (res.rc === 0 || res.mode === 'job') ? 'ok' : 'warn',
    html: resultHtml(res),
    foot: '<span class="spacer"></span><button class="btn quiet" data-close="modal">关闭</button>',
    mount: () => {
      const go = document.getElementById('actGoTasks');
      if (go) go.onclick = () => { document.getElementById('modal').classList.remove('on'); ctx.navigate('tasks'); };
    }
  });
  if (opts.onDone) opts.onDone(res);
  return res;
}

/** 带计费确认的执行（沿用旧控制台门禁：确认后才带 ack 提交）。 */
export function runAction(ctx, opts) {
  if (ctx.readonly) { toast('只读模式下不能执行写操作', 'warn'); return null; }
  if (opts.cost) {
    return confirmCost({
      title: opts.costTitle || opts.title || '确认会产生费用',
      lines: opts.cost.lines,
      total: opts.cost.total,
      note: opts.cost.note,
      onOk: () => doRun(ctx, Object.assign({}, opts, { confirm: Object.assign({ ack: true }, opts.confirm || {}) }))
    });
  }
  return doRun(ctx, opts);
}
