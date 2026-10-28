/* 系统设置：环境 / 开工前置 / 通道 / 能力清单 / 安全说明。
   写操作只允许「重新检查」——配置修改一律回终端（避免绕过 G0 执行依据校验）。 */
import { api } from '../api.js';
import { S, loadHealth } from '../store.js';
import { esc, icon, badge, kv, dt, toast, paintIcons, openModal, stamp, stateEl } from '../ui.js';

export async function render(ctx) {
  const [env, setup, h] = await Promise.all([
    api.env().catch((e) => ({ ok: false, reason: e.detail || e.message })),
    ctx.ws ? api.setup(ctx.ws).catch((e) => ({ ok: false, reason: e.detail || e.message }))
      : Promise.resolve({ ok: false, items: [], reason: 'no_workspace' }),
    api.health().catch(() => null)
  ]);
  const caps = (S.caps && S.caps.items) || {};

  const envRows = (env && env.ok && env.data && (env.data.items || env.data.checks))
    ? (env.data.items || env.data.checks)
    : null;
  const envHtml = envRows
    ? envRows.map((it) => {
      const ok = it.ok !== false && it.status !== 'fail';
      return '<div class="row" style="padding:5px 0"><span class="state ' + (ok ? 'done' : 'fail') + '">'
        + '<i class="dot ' + (ok ? 'done' : 'fail') + '"></i>' + esc(it.name || it.key || '—') + '</span>'
        + '<span class="tiny dim mono">' + esc(String(it.detail || it.version || it.value || '')) + '</span></div>';
    }).join('')
    : (env && env.ok
      ? '<pre class="log" style="max-height:180px">' + esc(JSON.stringify(env.data, null, 2).slice(0, 3000)) + '</pre>'
      : '<div class="alert warn"><span class="nav-ico">' + icon('alert', 14) + '</span><div>环境自检未取到结构化结果'
        + '（' + esc((env && env.reason) || '未知') + '）。可点下方「重新检查」，或到开发者视图跑 <span class="mono">env.check</span>。</div></div>');

  const setupItems = (setup.items || []);
  const setupHtml = setupItems.length
    ? setupItems.map((it) => '<div class="clitem"><span class="mk ' + (it.ok ? 'ok' : 'warn') + '">'
      + icon(it.ok ? 'check' : 'alert', 12) + '</span><div class="body"><div class="ttl">'
      + '<span class="mono small">' + esc(it.key) + '</span>' + badge(it.ok ? 'ok' : 'warn', it.ok ? '已确认' : '待确认')
      + '</div><div class="desc">' + esc(it.label || '') + (it.missing && it.missing.length
        ? ' · 缺：' + esc(it.missing.join('、')) : '') + '</div></div></div>').join('')
    : '<div class="alert info"><span class="nav-ico">' + icon('alert', 14) + '</span><div>'
      + (ctx.ws ? '未取到 G-0 九项：' + esc(setup.reason || 'project_setup.py 未返回 JSON')
        : '先选择项目，再看开工前置。') + '</div></div>';

  const capabilityKeys = Object.keys(caps);
  const capRows = capabilityKeys.map((k) => {
    const c = caps[k] || {};
    return '<tr><td class="mono small">' + esc(k) + '</td>'
      + '<td>' + (c.ok ? badge('ok', '已接入') : badge('muted', '未接入')) + '</td>'
      + '<td class="small muted">' + esc(c.ok ? (c.source || '') : (c.reason || '')) + '</td></tr>';
  }).join('');

  const html = ''
    + '<div class="page-head"><div><h1 class="page-title">系统设置</h1>'
    + '<div class="page-sub">只读为主：通道与工作流配置请在终端修改（避免绕过门禁）。'
    + '缺依赖 / 目录不可写这类问题去「环境体检」一键修</div></div>'
    + '<div class="page-actions"><button class="btn quiet" id="btnEnvCheck">'
    + icon('refresh', 14) + ' 重新检查</button></div></div>'

    + '<div class="grid g12" style="margin-bottom:16px">'
    + '<section class="card"><div class="card-h"><h3>环境</h3>'
    + '<span class="card-sub">零网络 · 缺一即停</span></div>'
    + '<div class="card-b">' + envHtml + '</div>'
    + '<div class="card-foot"><div class="row" style="justify-content:space-between;align-items:center">'
    + stamp('tools/env_check.py --json · 30 秒缓存')
    + '<button class="btn quiet sm" id="btnHealth">' + icon('check', 12)
    + ' 环境体检 / 一键修复</button></div></div></section>'

    + '<section class="card"><div class="card-h"><h3>控制台</h3></div><div class="card-b">'
    + kv([
      ['服务', (h && h.ok ? '在线' : '未知')],
      ['引擎解释器', (h && h.python) || '—', true],
      ['仓库', (h && h.repo) || '—', true],
      ['默认工作区', S.ws || '未选择', true],
      ['只读模式', S.readonly ? '开启（拒绝一切写操作）' : '关闭'],
      ['并发锁', h && h.locks ? ('GPU ' + (h.locks.summary.gpu) + ' · RH ' + (h.locks.summary.rh)) : '—', true]
    ])
    + '<div class="alert info" style="margin-top:12px"><span class="nav-ico">' + icon('lock', 14) + '</span><div>'
    + '本服务默认只监听 <span class="mono">127.0.0.1</span>，并校验 Host 与写请求来源；'
    + '局域网访问必须显式配置 <span class="mono">SOLODRAMA_CONSOLE_TOKEN</span>。'
    + '浏览器永远拿不到 API Key（日志与接口统一打码）。</div></div>'
    + '</div></section></div>'

    + '<section class="card" style="margin-bottom:16px"><div class="card-h"><h3>开工前置（G-0 九项）</h3>'
    + '<span class="card-sub">缺一项，计费动作会被引擎拦下（退出码 4）</span>'
    + '<span class="spacer"></span>' + (setup.ready ? badge('ok', '齐备') : badge('warn', '有缺项')) + '</div>'
    + '<div class="card-b" style="padding-top:4px">' + setupHtml + '</div>'
    + '<div class="card-foot">' + stamp('project_setup.py show --json · 10 秒缓存') + '</div></section>'

    + '<section class="card" style="margin-bottom:16px"><div class="card-h"><h3>能力清单</h3>'
    + '<span class="card-sub">哪些是真的接了、哪些没接以及为什么</span></div>'
    + '<div class="card-b tight"><div class="table-wrap"><table class="tb"><thead><tr>'
    + '<th style="width:200px">能力</th><th style="width:96px">状态</th><th>来源 / 原因</th>'
    + '</tr></thead><tbody>' + (capRows || '<tr><td colspan="3" class="dim small">未取到能力表</td></tr>')
    + '</tbody></table></div></div>'
    + '<div class="card-foot"><span class="tiny dim">能力表由后端 <span class="mono">/api/studio/capabilities</span> 提供，'
    + '前端不硬编码「已实现」。</span></div></section>'

    + '<section class="card"><div class="card-h"><h3>审计（最近 20 条）</h3>'
    + '<span class="card-sub">谁在何时执行了什么、退出码多少</span></div>'
    + '<div class="card-b tight" id="auditBox"><div class="card-b"><div class="skeleton" style="height:12px"></div></div></div>'
    + '</section>';

  return {
    html,
    mount: (root) => {
      const b = root.querySelector('#btnEnvCheck');
      if (b) b.onclick = async () => {
        b.disabled = true;
        try { await api.refresh(S.ws); await loadHealth(); toast('已重新检查'); ctx.refresh(); }
        catch (e) { toast('检查失败：' + (e.detail || e.message), 'bad'); }
        finally { b.disabled = false; }
      };
      const hb = root.querySelector('#btnHealth');
      if (hb) hb.onclick = () => { location.hash = '#/health'; };
      paintIcons(root);
      loadAudit(root);
    }
  };
}

async function loadAudit(root) {
  const box = root.querySelector('#auditBox');
  if (!box) return;
  try {
    const d = await api.audit(20);
    const rows = (d.items || []).map((a) => (
      '<tr><td class="mono small dim" style="width:100px">' + esc(dt(a.ts)) + '</td>'
      + '<td class="mono small">' + esc(a.spec_id || '—') + '</td>'
      + '<td class="num" style="width:56px">' + esc(a.exit_code === null ? '—' : a.exit_code) + '</td>'
      + '<td class="small muted">' + esc(a.estimate || '') + '</td>'
      + '<td class="mono small dim" style="width:120px">' + esc(String(a.ws || '').split(/[\\/]/).pop() || '—') + '</td></tr>'
    )).join('') || '<tr><td colspan="5"><div class="empty"><div class="empty-t">还没有审计记录</div></div></td></tr>';
    box.innerHTML = '<div class="table-wrap"><table class="tb"><thead><tr>'
      + '<th>时间</th><th>动作</th><th class="num">退出</th><th>预估</th><th>项目</th>'
      + '</tr></thead><tbody>' + rows + '</tbody></table></div>';
  } catch (e) {
    box.innerHTML = '<div class="card-b"><div class="alert bad"><span class="nav-ico">' + icon('alert', 14)
      + '</span><div>审计读取失败：' + esc(e.detail || e.message) + '</div></div></div>';
  }
}
