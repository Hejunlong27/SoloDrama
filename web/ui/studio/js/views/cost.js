/* 成本中心：只认平台 usage（ledger attempts）。任务级精确金额不可得，页面明说。 */
import { api } from '../api.js';
import { esc, icon, badge, money, coins, dt, stamp, emptyBox, RATE } from '../ui.js';

export async function render(ctx) {
  const d = await api.cost(ctx.ws);
  /* LLM 用量独立统计：与图片/视频的点数不是一套计价，绝不合并成一个「总花费」 */
  const llm = await api.llmUsage(50).catch(() => null);
  const ledger = d.ledger || { coins: 0, usd: 0, cny: 0, attempts: 0 };
  const rows = d.rows || [];
  const byStage = d.by_stage || [];
  const byEp = d.by_episode || [];
  const maxStage = Math.max.apply(null, byStage.map((s) => s.coins).concat([1]));

  const now = new Date();
  const ym = now.getFullYear() + '-' + ('0' + (now.getMonth() + 1)).slice(-2);
  let monthCoins = 0;
  rows.forEach((r) => { if (String(r.at).indexOf(ym) === 0) monthCoins += r.coins; });

  const okRows = rows.filter((r) => ['SUCCESS', 'SUCCEEDED', 'OK'].indexOf(r.status) >= 0);
  const unit = okRows.length ? (ledger.coins / okRows.length) : 0;
  const srcTone = d.source === 'ledger' ? 'ok' : d.source === 'none' ? 'outline' : 'warn';

  const stageBars = byStage.map((s) => (
    '<div class="bar-row"><span class="muted">' + esc(s.stage || '其他') + '</span>'
    + '<span class="bar-track"><i class="bar-fill" style="width:' + Math.round(s.coins / maxStage * 100) + '%"></i></span>'
    + '<span class="right mono">' + money(s.coins * RATE.coinToCny) + '</span></div>'
  )).join('') || '<div class="dim small">台账里还没有成功计费记录</div>';

  const epRows = byEp.map((e) => (
    '<tr><td class="mono">' + esc(e.ep || '—') + '</td>'
    + '<td class="num">' + coins(e.coins) + '</td>'
    + '<td class="num">' + money(e.coins * RATE.coinToCny) + '</td></tr>'
  )).join('') || '<tr><td colspan="3"><div class="empty"><div class="empty-t">还没有按集记录</div>'
    + '<div class="empty-h">台账里每条 attempt 带 episode 字段时才会有这一列。</div></div></td></tr>';

  const detailRows = rows.slice(0, 120).map((r) => {
    const ok = ['SUCCESS', 'SUCCEEDED', 'OK'].indexOf(r.status) >= 0;
    return '<tr><td class="mono small dim">' + esc(dt(r.at)) + '</td>'
      + '<td class="mono small">' + esc(r.episode || '—') + '</td>'
      + '<td class="small muted">' + esc(r.stage || '—') + '</td>'
      + '<td class="mono small">' + esc(r.shot_id || '—') + '</td>'
      + '<td>' + (ok ? badge('ok', '成功') : badge('bad', esc(r.status || '失败'))) + '</td>'
      + '<td class="num">' + (ok ? coins(r.coins) : '<span class="dim">不计费</span>') + '</td>'
      + '<td class="num">' + (ok ? money(r.coins * RATE.coinToCny) : '—') + '</td>'
      + '<td class="mono small dim">' + esc(String(r.task_id || '').slice(0, 12)) + '</td></tr>';
  }).join('') || '<tr><td colspan="8">' + emptyBox('台账为空', '出片或云端出图后，这里会逐条列出平台用量。') + '</td></tr>';

  const html = ''
    + '<div class="page-head"><div><h1 class="page-title">成本中心</h1>'
    + '<div class="page-sub">口径：只认平台 <span class="mono">usage</span>；失败任务不计费；'
    + '1 点 ≈ ¥' + RATE.coinToCny + '</div></div>'
    + '<div class="page-actions">' + badge(srcTone, d.source === 'ledger' ? '来自台账'
      : d.source === 'none' ? '暂无数据' : '部分来自生成记录') + '</div></div>'

    + '<div class="grid g4" style="margin-bottom:16px">'
    + '<div class="kpi"><div class="kpi-k">累计消耗</div><div class="kpi-v">' + money(ledger.cny) + '</div>'
    + '<div class="kpi-n mono">' + coins(ledger.coins) + ' 点</div></div>'
    + '<div class="kpi"><div class="kpi-k">本月</div><div class="kpi-v">' + money(monthCoins * RATE.coinToCny) + '</div>'
    + '<div class="kpi-n mono">' + coins(monthCoins) + ' 点</div></div>'
    + '<div class="kpi"><div class="kpi-k">成功计费次数</div><div class="kpi-v">' + ledger.attempts + '</div>'
    + '<div class="kpi-n">台账共 ' + rows.length + ' 条尝试</div></div>'
    + '<div class="kpi"><div class="kpi-k">平均单价 / 次</div><div class="kpi-v">'
    + money(unit * RATE.coinToCny) + '</div><div class="kpi-n mono">' + coins(Math.round(unit)) + ' 点</div></div>'
    + '</div>'

    + '<div class="grid g21" style="margin-bottom:16px">'
    + '<section class="card"><div class="card-h"><h3>按阶段拆分</h3><span class="card-sub">台账 stage 字段</span></div>'
    + '<div class="card-b">' + stageBars
    + '<div class="tiny dim" style="margin-top:8px">本地出图不产生费用（占 GPU 与电费），因此不会出现在这里，'
    + '而不是隐藏。</div></div>'
    + '<div class="card-foot">' + stamp((d.source_text || '平台用量台账') + ' · 20 秒缓存') + '</div></section>'

    + '<section class="card"><div class="card-h"><h3>按集拆分</h3></div>'
    + '<div class="card-b tight"><div class="table-wrap"><table class="tb"><thead><tr>'
    + '<th>集</th><th class="num">点数</th><th class="num">金额</th></tr></thead><tbody>' + epRows
    + '</tbody></table></div></div></section></div>'

    + '<section class="card"><div class="card-h"><h3>用量明细</h3>'
    + '<span class="card-sub">逐次尝试（含失败，失败不计费）</span><span class="spacer"></span>'
    + '<span class="badge muted" title="引擎的 audit 只存预估文本，没有实际金额">任务级金额不可得</span></div>'
    + '<div class="card-b tight"><div class="table-wrap" style="max-height:520px"><table class="tb"><thead><tr>'
    + '<th style="width:96px">时间</th><th style="width:72px">集</th><th style="width:110px">阶段</th>'
    + '<th>镜头</th><th style="width:80px">状态</th><th class="num" style="width:80px">点数</th>'
    + '<th class="num" style="width:88px">金额</th><th style="width:104px">任务号</th>'
    + '</tr></thead><tbody>' + detailRows + '</tbody></table></div></div>'
    + '<div class="card-foot"><span class="nav-ico">' + icon('alert', 14) + '</span>'
    + '<span class="tiny muted">台账优先；云端资产用量在 inventory 里单独统计（'
    + esc(String((d.assets_usage || {}).coins || 0)) + ' 点），不重复计入总额。'
    + '美元钱包按 1 美元 ≈ ¥' + RATE.usdToCny + ' 估算。</span></div></section>';

    + llmSection(llm);

  return { html };
}

/* ---------- LLM 用量（独立计价，不与 RH 点数混算） ---------- */
function llmSection(llm) {
  if (!llm) {
    return '<section class="card" style="margin-top:16px"><div class="card-h"><h3>LLM 用量</h3></div>'
      + '<div class="card-b"><div class="alert info"><span class="nav-ico">' + icon('alert', 14) + '</span><div>'
      + '未取到 LLM 用量（web/var/llm/usage.jsonl）。在「AI 模型中心」配置并调用后才会产生记录。</div></div>'
      + '</div></section>';
  }
  const s = llm.summary || {};
  const items = llm.items || [];
  const rows = items.slice(0, 12).map((r) => {
    const u = r.usage || {};
    const c = r.cost || {};
    return '<tr><td class="mono tiny dim">' + esc(dt(r.at)) + '</td>'
      + '<td class="mono small">' + esc(r.purpose || '—') + '</td>'
      + '<td class="small muted">' + esc(r.provider_name || r.provider || '—') + '</td>'
      + '<td>' + (r.ok ? badge('ok', '成功') : badge('bad', r.error_kind || '失败'))
      + (r.simulated ? ' ' + badge('muted', '演练') : '') + '</td>'
      + '<td class="num">' + esc(u.input_tokens == null ? '—' : u.input_tokens) + '</td>'
      + '<td class="num">' + esc(u.output_tokens == null ? '—' : u.output_tokens) + '</td>'
      + '<td class="num">' + (c.usd == null ? '<span class="dim">未知</span>' : ('$' + c.usd)) + '</td>'
      + '</tr>';
  }).join('') || '<tr><td colspan="7"><div class="empty"><div class="empty-t">还没有 LLM 调用</div>'
    + '<div class="empty-h">在「创作中心」生成一次剧本正文后会出现在这里。</div></div></td></tr>';

  return '<section class="card" style="margin-top:16px"><div class="card-h"><h3>LLM 用量</h3>'
    + '<span class="card-sub">' + esc(s.calls || 0) + ' 次 · 成功 ' + esc(s.ok || 0)
    + ' · 失败 ' + esc(s.failed || 0) + '</span><span class="spacer"></span>'
    + '<span class="badge outline" title="LLM 按供应商账单结算，不折算成 RH 点数">与点数分开计价</span></div>'
    + '<div class="card-b tight"><div class="table-wrap"><table class="tb"><thead><tr>'
    + '<th style="width:110px">时间</th><th>用途</th><th style="width:140px">提供商</th>'
    + '<th style="width:80px">结果</th><th class="num" style="width:76px">入</th>'
    + '<th class="num" style="width:76px">出</th><th class="num" style="width:86px">金额</th>'
    + '</tr></thead><tbody>' + rows + '</tbody></table></div></div>'
    + '<div class="card-foot"><span class="tiny muted">金额只认供应商返回的 usage：'
    + (s.cost_records ? ('已有 ' + esc(s.cost_records) + ' 条带金额记录')
      : '当前全部未知，<b>不按 token 单价估算</b>') + '。'
    + '提示词与正文不落日志，只存指纹与长度。</span></div></section>';
}
