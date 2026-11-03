/* ============================================================
   workbench.js —— 工作台（全局唯一入口）

   ★ 2026-11-04 合并（用户要求）：原来「工作台」和「项目管理」是两页，
     内容重叠 80%（同一批项目、同一份注册表）。分成两页的实际后果是：
     在工作台找不到搜索/新建，在项目管理看不到待办。
     现在一页装三块：**这台机器在干什么（待办/运行中/通道）**、
     **有哪些剧（项目清单）**、**时间花在哪（全局 GPU 时长）**。

   成本口径：本项目全本机出图出片，平台费用恒为 0 —— 一屏「¥0」不是信息。
   所以这里只报**时间**：总共占了多少 GPU、哪几部最费、哪个环节最吃时间。
   ============================================================ */
import { api } from '../api.js';
import { S, loadRunning } from '../store.js';
import { esc, icon, dot, stamp, toast } from '../ui.js';
import { projectList } from './project-list.js';

function kpi(label, value, note, tone) {
  return '<div class="kpi"><div class="kpi-k">' + esc(label) + '</div>'
    + '<div class="kpi-v"' + (tone ? ' style="color:' + tone + '"' : '') + '>' + value + '</div>'
    + (note ? '<div class="kpi-n">' + note + '</div>' : '') + '</div>';
}

export async function render(ctx) {
  const [jobs, wf, conn, timing, list] = await Promise.all([
    api.jobs(ctx.ws, 20).catch(() => ({ items: [] })),
    ctx.ws ? api.workflow(ctx.ws).catch(() => null) : Promise.resolve(null),
    api.connections().catch(() => null),
    api.timeGlobal(ctx.ws).catch(() => null),
    projectList(ctx)
  ]);
  const projects = (S.projects || []);
  const running = (jobs.items || []).filter((j) => j.status === 'running' || j.status === 'queued');
  const waiting = (jobs.items || []).filter((j) => j.status === 'confirm');
  const failed = (jobs.items || []).filter((j) => ['failed', 'gate', 'fuse', 'interrupted'].indexOf(j.status) >= 0);

  /* ---- 待处理 ---- */
  const problems = [];
  if (wf && wf.ok && wf.current) {
    const st = (wf.stages || []).find((s) => s.id === wf.current);
    if (st) {
      const miss = (st.probes || []).filter((p) => !p.ok);
      problems.push({
        tone: 'warn',
        title: '《' + (ctx.project ? ctx.project.title || ctx.project.path : '当前项目') + '》下一步：' + st.id + ' ' + st.name,
        detail: miss.length ? '缺：' + miss.map((m) => m.label + ' ' + m.found + '/' + m.need).join('、') : (st.what || ''),
        route: 'graph'
      });
    }
  }
  if (failed.length) {
    problems.push({
      tone: 'bad', title: failed.length + ' 个任务失败或中断',
      detail: failed.slice(0, 3).map((j) => j.title).join('；'), route: 'tasks'
    });
  }
  if (waiting.length) {
    problems.push({
      tone: 'warn', title: waiting.length + ' 个任务在等你确认',
      detail: '引擎停在「等待确认」状态，不会自己继续。', route: 'tasks'
    });
  }
  const connItems = (conn && conn.items) || [];
  const connMissing = connItems.filter((i) => i.last_ok !== true).map((i) => i.label);
  if (connItems.length && connMissing.length) {
    problems.push({
      tone: 'warn',
      title: '外部通道未接通（' + (connItems.length - connMissing.length) + '/' + connItems.length + '）',
      detail: '缺：' + connMissing.join('、') + '。这些环节会停在「未接通」，不影响已完成的工序。',
      route: 'system'
    });
  }
  if (!problems.length) {
    problems.push({ tone: 'ok', title: '没有需要你处理的事', detail: '所有任务都已结束；下一步在画布或项目详情里看。', route: 'graph' });
  }

  /* ---- 全局时间 ---- */
  const t = (timing && timing.totals) || {};
  const tops = ((timing && timing.projects) || []).slice(0, 5);
  const maxSec = tops.length ? Math.max(...tops.map((p) => p.sec)) : 1;
  const stageRows = ((timing && timing.by_stage) || []).slice(0, 6);
  const stageMax = stageRows.length ? Math.max(...stageRows.map((s) => s.sec)) : 1;

  const timeCard = '<section class="card"><div class="card-h"><h3>全局时间</h3>'
    + '<span class="card-sub">本机出图出片，费用恒为 0；真正稀缺的是 GPU 时间</span>'
    + '<span class="spacer"></span><span class="tiny dim">' + esc((timing && timing.source) || '') + '</span></div>'
    + '<div class="card-b">'
    + '<div class="row" style="gap:18px;flex-wrap:wrap;margin-bottom:12px">'
    + '<div><div class="kpi-k">累计占用</div><div class="kpi-v" style="font-size:var(--fs-20)">'
    + esc((t.human || '0 分')) + '</div></div>'
    + '<div><div class="kpi-k">成功段数</div><div class="kpi-v" style="font-size:var(--fs-20)">'
    + esc(String(t.success || 0)) + '</div></div>'
    + '<div><div class="kpi-k">平均每段</div><div class="kpi-v" style="font-size:var(--fs-20)">'
    + esc(t.avg_shot_sec ? t.avg_shot_sec + 's' : '—') + '</div></div>'
    + '<div><div class="kpi-k">失败尝试</div><div class="kpi-v" style="font-size:var(--fs-20)">'
    + esc(String(t.failed || 0)) + '</div></div></div>'
    + (tops.length
      ? '<div class="tiny dim" style="margin-bottom:6px">最费时间的项目</div>'
        + tops.map((p) => '<div class="bar-row" style="grid-template-columns:minmax(0,1fr) 1fr 76px">'
          + '<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + esc(p.title) + '</span>'
          + '<span class="bar-track"><i class="bar-fill" style="width:'
          + Math.max(2, Math.round(p.sec / maxSec * 100)) + '%"></i></span>'
          + '<span class="mono right">' + esc(p.human) + '</span></div>').join('')
      : '<div class="empty"><div class="empty-t">还没有可统计的耗时</div>'
        + '<div class="empty-h">跑过一次出图或出片之后，这里会出现按项目与环节的分解。</div></div>')
    + (stageRows.length
      ? '<div class="tiny dim" style="margin:12px 0 6px">时间花在哪个环节</div>'
        + stageRows.map((s) => '<div class="bar-row" style="grid-template-columns:96px 1fr 76px">'
          + '<span class="mono">' + esc(s.stage) + '</span>'
          + '<span class="bar-track"><i class="bar-fill" style="width:'
          + Math.max(2, Math.round(s.sec / stageMax * 100)) + '%"></i></span>'
          + '<span class="mono right">' + esc(s.human) + '</span></div>').join('')
      : '')
    + '</div></section>';

  const html = ''
    + '<div class="page-head"><div><h1 class="page-title">工作台</h1>'
    + '<div class="page-sub">本机已登记 ' + projects.length + ' 部剧 · '
    + '项目清单、待办、时间账都在这页（不再分「项目管理」）</div></div>'
    + '<div class="page-actions">'
    + '<button class="btn quiet" id="btnRefreshWb">' + icon('refresh', 14) + ' 刷新</button>'
    + '<button class="btn primary" id="btnNewWb">' + icon('plus', 14) + ' 新建项目</button>'
    + '</div></div>'

    + '<div class="grid g4" style="margin-bottom:16px">'
    + kpi('已登记项目', String(projects.length),
      projects.filter((p) => p.has_output).length + ' 部有产出')
    + kpi('运行中任务', String(running.length), running.length ? '任务中心看实时日志' : '当前没有排队任务')
    + kpi('累计 GPU 时间', esc(t.human || '—'), esc(t.success ? t.success + ' 段成功' : '台账暂无记录'))
    + kpi('环境', S.health ? '在线' : '未知',
      S.health ? '引擎 ' + esc(String(S.health.python || '').split(/[\\/]/).pop()) : '未取到 /api/health',
      S.health ? 'var(--ok)' : 'var(--accent)')
    + '</div>'

    + '<div class="grid g21" style="margin-bottom:16px">'
    + '<section class="card"><div class="card-h"><h3>待处理</h3>'
    + '<span class="badge ' + (problems[0].tone === 'ok' ? 'ok' : 'warn') + '">' + problems.length + '</span>'
    + '<span class="spacer"></span><button class="btn ghost sm" data-go="tasks">任务中心</button></div>'
    + '<div class="card-b">'
    + problems.map((p) => '<div style="padding:9px 0;border-bottom:1px solid var(--line)">'
      + '<div class="row gap8">'
      + '<span class="nav-ico" style="color:'
      + (p.tone === 'bad' ? 'var(--danger)' : p.tone === 'ok' ? 'var(--ok)' : 'var(--accent)')
      + ';margin-top:2px">' + icon('alert', 14) + '</span>'
      + '<div class="flex1"><div class="small">' + esc(p.title) + '</div>'
      + '<div class="tiny dim">' + esc(p.detail) + '</div></div>'
      + '<button class="btn quiet sm" data-go="' + esc(p.route) + '">查看</button>'
      + '</div></div>').join('')
    + '</div></section>'

    + '<section class="card"><div class="card-h"><h3>正在运行</h3>'
    + '<span class="card-sub">服务端执行，刷新浏览器不受影响</span></div><div class="card-b">'
    + (running.length ? running.map((j) => '<div style="margin-bottom:12px">'
      + '<div class="row gap8" style="margin-bottom:6px">' + dot('doing')
      + '<span class="small">' + esc(j.title) + '</span><span class="spacer"></span>'
      + '<span class="mono tiny dim">' + esc(j.spec_id || '') + '</span></div>'
      + '<div class="progress"><i style="width:8%"></i></div>'
      + '<div class="row" style="margin-top:5px"><span class="tiny dim">' + esc(j.estimate || '') + '</span>'
      + '<span class="spacer"></span><button class="btn ghost sm" data-go="tasks">查看日志</button></div></div>').join('')
      : '<div class="empty"><div class="empty-t">当前没有运行中的任务</div>'
      + '<div class="empty-h">出片、放大、字幕这类长任务会出现在这里。</div></div>')
    + '</div></section></div>'

    + timeCard

    + '<section class="card" style="margin-top:16px"><div class="card-h"><h3>项目</h3>'
    + '<span class="card-sub">点卡片打开；新建时选创作模板</span>'
    + '<span class="spacer"></span><button class="btn ghost sm" data-go="projects">单独打开</button></div>'
    + '<div class="card-b"><div id="wbProjects">' + list.html + '</div></div>'
    + '<div class="card-foot">' + stamp('注册表 + 台账 · 扫描结果缓存 90 秒') + '</div></section>';

  return {
    html,
    mount: (root) => {
      list.mount(root);
      root.querySelectorAll('[data-go]').forEach((b) => {
        b.onclick = () => ctx.navigate(b.dataset.go);
      });
      const rf = root.querySelector('#btnRefreshWb');
      if (rf) {
        rf.onclick = async () => {
          rf.disabled = true;
          try {
            await api.refresh(ctx.ws);
            await loadRunning();
            ctx.refresh();
            toast('已重新读取');
          } catch (e) { toast('刷新失败：' + (e.detail || e.message), 'bad'); }
          finally { rf.disabled = false; }
        };
      }
      const nw = root.querySelector('#btnNewWb');
      if (nw) nw.onclick = () => {
        const btn = root.querySelector('#btnNew');
        if (btn) { btn.click(); return; }
        ctx.navigate('projects');
      };
    }
  };
}
