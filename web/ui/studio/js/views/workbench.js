/* 工作台：全局视图（不依赖当前项目也可用） */
import { api } from '../api.js';
import { S, loadRunning } from '../store.js';
import { esc, icon, stateEl, dot, money, badge, stamp, emptyBox, toast, ago } from '../ui.js';

function kpi(label, value, note) {
  return '<div class="kpi"><div class="kpi-k">' + esc(label) + '</div>'
    + '<div class="kpi-v">' + value + '</div>'
    + (note ? '<div class="kpi-n">' + note + '</div>' : '') + '</div>';
}

export async function render(ctx) {
  const [wsList, jobs, wf, setup, llmProv, llmPurp, conn] = await Promise.all([
    api.workspaces().catch(() => ({ items: [] })),
    api.jobs(ctx.ws, 20).catch(() => ({ items: [] })),
    ctx.ws ? api.workflow(ctx.ws).catch(() => null) : Promise.resolve(null),
    ctx.ws ? api.setup(ctx.ws).catch(() => null) : Promise.resolve(null),
    api.llmProviders().catch(() => ({ items: [] })),
    api.llmPurposes().catch(() => ({ items: [] })),
    api.connections().catch(() => null)
  ]);
  const providers = llmProv.items || [];
  const purposes = llmPurp.items || [];

  const projects = (wsList.items || []).filter((p) => p.exists);
  const withOutput = projects.filter((p) => p.has_output);
  const running = (jobs.items || []).filter((j) => j.status === 'running' || j.status === 'queued');
  const waiting = (jobs.items || []).filter((j) => j.status === 'confirm');
  const failed = (jobs.items || []).filter((j) => ['failed', 'gate', 'fuse', 'interrupted'].indexOf(j.status) >= 0);
  const totalYuan = projects.reduce((a, p) => a + (Number(p.yuan) || 0), 0);

  const problems = [];
  if (wf && wf.ok && wf.current) {
    const st = (wf.stages || []).find((s) => s.id === wf.current);
    if (st) {
      const miss = (st.probes || []).filter((p) => !p.ok);
      problems.push({
        tone: 'warn',
        title: '《' + (ctx.project ? ctx.project.title || ctx.project.path : '当前项目') + '》下一步：' + st.id + ' ' + st.name,
        detail: miss.length ? '缺：' + miss.map((m) => m.label + ' ' + m.found + '/' + m.need).join('、') : (st.what || ''),
        route: 'overview'
      });
    }
  }
  if (failed.length) {
    problems.push({
      tone: 'bad',
      title: failed.length + ' 个任务失败或中断',
      detail: failed.slice(0, 3).map((j) => j.title).join('；'),
      route: 'tasks'
    });
  }
  if (waiting.length) {
    problems.push({
      tone: 'warn',
      title: waiting.length + ' 个任务在等你确认',
      detail: '引擎停在「等待确认」状态（例如要不要花钱），不会自己继续。',
      route: 'tasks'
    });
  }
  const overRefs = projects.filter((p) => false);   /* 参考图超限是项目级信息，见项目详情 */

  /* 连接状态进「待处理」：通道没接通时，用户点任何出图/出片都会失败，
     与其等他撞墙，不如在工作台就把「缺哪一路」摆出来。 */
  const connItems = (conn && conn.items) || [];
  const connOk = connItems.filter((i) => i.last_ok === true).length;
  const connMissing = connItems.filter((i) => i.last_ok !== true).map((i) => i.label);
  if (connItems.length && connMissing.length) {
    problems.push({
      tone: 'warn',
      title: '外部通道未接通（' + connOk + '/' + connItems.length + '）',
      detail: '缺：' + connMissing.join('、') + '。这些环节会停在「未接通」，不影响已完成的工序。',
      route: 'connections'
    });
  }
  if (!problems.length) {
    problems.push({ tone: 'ok', title: '没有需要你处理的事', detail: '所有任务都已结束；下一步在项目详情里看阶段。', route: 'projects' });
  }

  const rows = projects.map((p) => (
    '<tr class="clickable" data-open="' + esc(p.path) + '">'
    + '<td><div class="row gap8">' + dot(p.has_output ? 'done' : 'todo')
    + '<span>' + esc(p.title || p.path) + '</span></div>'
    + '<div class="row-sub mono">' + esc(p.path) + '</div></td>'
    + '<td class="num">' + (p.images || 0) + '</td>'
    + '<td class="num">' + (p.yuan ? money(p.yuan) : '—') + '</td>'
    + '<td class="small dim">' + esc(p.updated_text || '—') + '</td>'
    + '<td class="right"><button class="btn quiet sm" data-open="' + esc(p.path) + '">打开</button></td></tr>'
  )).join('');

  const html = ''
    + '<div class="page-head"><div><h1 class="page-title">工作台</h1>'
    + '<div class="page-sub">本机已登记 ' + projects.length + ' 部剧 · 数据来自本地注册表与作业库</div></div>'
    + '<div class="page-actions">'
    + '<button class="btn quiet" id="btnDiscoverWb">' + icon('search', 14) + ' 扫描本机项目</button>'
    + '<button class="btn primary" data-go="projects">' + icon('plus', 14) + ' 登记 / 新建</button>'
    + '</div></div>'

    + '<div class="grid g4" style="margin-bottom:16px">'
    + kpi('已登记项目', String(projects.length), withOutput.length + ' 部有产出')
    + kpi('运行中任务', String(running.length), running.length ? '可在任务中心查看日志' : '当前没有排队任务')
    + kpi('累计花费', totalYuan ? money(totalYuan) : '—',
      totalYuan ? '<span class="mono">按注入台账汇总</span>'
        : '<span class="mono">台账无可读记录（不是 0 花费）</span>')
    + kpi('环境', S.health ? '在线' : '未知', S.health ? '引擎 ' + esc(String(S.health.python || '').split(/[\\/]/).pop()) : '未取到 /api/health')
    + '</div>'

    + '<div class="grid g21" style="margin-bottom:16px">'
    + '<section class="card"><div class="card-h"><h3>项目</h3><span class="card-sub">按产出与最近活动排序</span>'
    + '<span class="spacer"></span><button class="btn ghost sm" data-go="projects">全部</button></div>'
    + '<div class="card-b tight"><div class="table-wrap"><table class="tb"><thead><tr>'
    + '<th style="width:44%">剧名 / 路径</th><th class="num" style="width:88px">图片</th>'
    + '<th class="num" style="width:100px">花费</th><th style="width:110px">更新</th><th></th>'
    + '</tr></thead><tbody>' + (rows || '<tr><td colspan="5">' + emptyBox('还没有项目', '扫描本机目录或登记一个已有的剧项目目录。') + '</td></tr>')
    + '</tbody></table></div></div>'
    + '<div class="card-foot">' + stamp('本地项目注册表 · 扫描结果缓存 90 秒') + '</div></section>'

    + '<section class="card"><div class="card-h"><h3>待处理</h3><span class="badge ' + (problems[0].tone === 'ok' ? 'ok' : 'warn') + '">'
    + problems.length + '</span></div><div class="card-b">'
    + problems.map((p) => '<div style="padding:9px 0;border-bottom:1px solid var(--line)">'
      + '<div class="row gap8">'
      + '<span class="nav-ico" style="color:'
      + (p.tone === 'bad' ? 'var(--danger)' : p.tone === 'ok' ? 'var(--ok)' : 'var(--accent)')
      + ';margin-top:2px">' + icon('alert', 14) + '</span>'
      + '<div class="flex1"><div class="small">' + esc(p.title) + '</div>'
      + '<div class="tiny dim">' + esc(p.detail) + '</div></div>'
      + '<button class="btn quiet sm" data-go="' + esc(p.route) + '">查看</button>'
      + '</div></div>').join('')
    + '</div></section></div>'

    + '<section class="card"><div class="card-h"><h3>正在运行</h3>'
    + '<span class="card-sub">作业在服务端执行，刷新浏览器不受影响</span>'
    + '<span class="spacer"></span><button class="btn ghost sm" data-go="tasks">任务中心</button></div>'
    + '<div class="card-b">'
    + (running.length ? running.map((j) => '<div style="margin-bottom:12px">'
      + '<div class="row gap8" style="margin-bottom:6px">' + dot('doing')
      + '<span class="small">' + esc(j.title) + '</span><span class="spacer"></span>'
      + '<span class="mono tiny dim">' + esc(j.spec_id || '') + '</span></div>'
      + '<div class="progress"><i style="width:8%"></i></div>'
      + '<div class="row" style="margin-top:5px"><span class="tiny dim">' + esc(j.estimate || '') + '</span>'
      + '<span class="spacer"></span><button class="btn ghost sm" data-go="tasks">查看日志</button></div></div>').join('')
      : '<div class="empty"><div class="empty-t">当前没有运行中的任务</div>'
      + '<div class="empty-h">出片、放大、字幕这类长任务会出现在这里。</div>'
      + '<button class="btn quiet" data-go="tasks">打开任务中心</button></div>')
    + '</div></section>'

    + channelCard(ctx, setup, providers, purposes, conn)
    + (overRefs.length ? '' : '');

  return {
    html,
    mount: (root) => {
      root.querySelectorAll('[data-go]').forEach((b) => {
        b.onclick = () => ctx.navigate(b.dataset.go);
      });
      root.querySelectorAll('[data-open]').forEach((b) => {
        b.onclick = (e) => {
          e.stopPropagation();
          const p = projects.find((x) => x.path === b.dataset.open);
          if (!p) return;
          import('../store.js').then((m) => {
            m.setWs(p.path, { pushUrl: true });
            ctx.navigate('overview');
            ctx.refresh();
          });
        };
      });
      /* 检测走「连接中心」同一条只读探测（读 system_stats，0 费用）。
         以前这里跑 diag.comfy 拿原始日志，和工作台的接入状态是两套口径：
         同一个 ComfyUI，卡片说「未确认」、抽屉说「在线」，用户没法判断。
         现在只有一条链路，结果直接写进后端（last_test / last_detail），刷新即显示。 */
      root.querySelectorAll('[data-probe]').forEach((b) => {
        b.onclick = async () => {
          const kind = b.dataset.probe;
          b.disabled = true;
          b.innerHTML = '<span class="spinner"></span>';
          try {
            const r = await api.testConnection(kind);
            toast(r.ok ? '已连接：' + (r.detail || '') : ((r.detail || '探测失败') + (r.next ? ' · ' + r.next : '')),
              r.ok ? 'ok' : 'bad');
            ctx.refresh();
          } catch (e) {
            toast('探测失败：' + (e.detail || e.message), 'bad');
            b.disabled = false;
            b.textContent = '检测';
          }
        };
      });

      const d = root.querySelector('#btnDiscoverWb');
      if (d) d.onclick = async () => {
        d.disabled = true; d.innerHTML = '<span class="spinner"></span> 扫描中';
        try {
          const res = await api.discover(true);
          toast('扫描完成：发现 ' + (res.items || []).length + ' 个候选（已登记的不重复）');
          await loadRunning();
          ctx.refresh();
        } catch (e) {
          toast('扫描失败：' + (e.detail || e.message), 'bad');
        } finally { d.disabled = false; d.innerHTML = icon('search', 14) + ' 扫描本机项目'; }
      };
    }
  };
}

/* ---------- 接入状态（LLM / 本地出图 / 云端出片） ----------
   只报「配置状态 + 已做过的检测结果」，不在打开页面时主动联网探测：
   探测要有明确触发（点「检测」跑 diag.comfy，0 费用；RunningHub 的真实请求需 --live，控制台不自动发）。 */
function channelCard(ctx, setup, providers, purposes, conn) {
  /* 口径统一：机器级通道（大模型 / 本地出图 / 云端出片）只认「连接中心」，
     项目级要求（工作流 API）才认 G-0。以前两套各算一套，会出现
     「连接中心显示已连接、工作台显示未确认」的自相矛盾，用户不知道该信哪个。 */
  const items = (setup && setup.items) || [];
  const wfApi = items.find((x) => x.key === 'workflow_api') || {};
  const byKind = {};
  ((conn && conn.items) || []).forEach((i) => { byKind[i.kind] = i; });

  const on = (providers || []).filter((p) => p.enabled !== false);
  const ready = (purposes || []).filter((p) => p.ready).length;
  const llmExtra = on.length
    ? (on.length + ' 个提供商 · ' + ready + '/' + (purposes || []).length + ' 用途就绪')
    : ((providers || []).length ? '已配置但全部停用' : '还没有配置任何模型端点');

  const row = (tone, name, text, action) => '<div class="row" style="padding:7px 0;border-bottom:1px solid var(--line)">'
    + '<i class="dot ' + tone + '"></i><span class="small" style="width:88px;flex:none">' + esc(name) + '</span>'
    + '<span class="tiny muted flex1">' + text + '</span>'
    + (action || '') + '</div>';

  /* 机器级通道：三态分明。未探测 ≠ 不可用，所以文案不能写成「失败」。 */
  const chan = (kind, name, fallback, action) => {
    const it = byKind[kind] || {};
    const ok = it.last_ok === true;
    const bad = it.last_ok === false;
    const tone = ok ? 'done' : bad ? 'fail' : 'todo';
    let text;
    if (ok) {
      text = esc(it.last_detail || '已连接')
        + (it.last_test ? ' <span class="dim">· ' + esc(ago(it.last_test)) + '前</span>' : '');
    } else if (bad) {
      text = esc(it.last_detail || '探测失败')
        + (it.last_next ? ' <span class="dim">· ' + esc(it.last_next) + '</span>' : '');
    } else {
      text = esc(fallback) + ' <span class="dim">· 未探测，去连接中心点一次测试</span>';
    }
    return row(tone, name, text, action);
  };

  return '<section class="card" style="margin-bottom:16px"><div class="card-h"><h3>接入状态</h3>'
    + '<span class="card-sub">机器级通道看「连接中心」，项目级要求看 G-0</span>'
    + '<span class="spacer"></span><button class="btn ghost sm" data-go="connections">连接中心</button></div>'
    + '<div class="card-b">'
    + chan('llm', '大模型', llmExtra,
      '<button class="btn quiet sm" data-go="' + (on.length ? 'connections' : 'models') + '">'
      + (on.length ? '连接中心' : '去配置') + '</button>')
    + chan('comfyui', '本地出图', 'ComfyUI 未验证', '<button class="btn quiet sm" data-probe="comfyui">检测</button>')
    + chan('runninghub', '云端出片', 'RunningHub 未验证', '<button class="btn quiet sm" data-go="connections">连接中心</button>')
    + (ctx.ws
      ? row(wfApi.ok ? 'done' : 'todo', '工作流 API',
        esc((wfApi.detail && wfApi.detail.ref) || '未确认（项目级要求）'),
        '<button class="btn quiet sm" data-go="settings">系统设置</button>')
      : row('todo', '工作流 API', '未选项目 <span class="dim">· 工作流 ID 是项目级配置</span>',
        '<button class="btn quiet sm" data-go="projects">选项目</button>'))
    + '</div>'
    + '<div class="card-foot"><span class="tiny dim">探测一律只读：ComfyUI 读 system_stats，'
    + 'RunningHub 查账户余额，都不产生任务、不花钱。真实出片才会计费。</span></div></section>';
}
