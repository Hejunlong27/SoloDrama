/* 用时（原「时间中心 / 成本中心」）：本仓库出图出片全在本机，唯一的成本是 GPU 时间。
   ★ 2026-11-04：从全局导航移进项目（它是项目属性）；全局耗时汇总在工作台首屏。
   ★ 2026-11-04：整页口径从「钱」换成「时间」。
   为什么必须换：平台费用恒为 0，一个永远显示 ¥0 的页面不只是没用 ——
   它会让人以为「计费没接上」，然后去排查一个不存在的问题。
   这里回答的是真问题：这一集占了几小时、哪一步最吃时间、整季还要几天。 */
import { api } from '../api.js';
import { esc, icon, badge, dt, stamp, emptyBox } from '../ui.js';

const OK = ['SUCCESS', 'SUCCEEDED', 'OK'];

function dur(sec) {
  const s = Math.round(Number(sec) || 0);
  if (s < 60) return s + ' 秒';
  const m = Math.floor(s / 60);
  if (m < 60) return s % 60 < 30 ? m + ' 分' : m + ' 分 ' + (s % 60) + ' 秒';
  const h = Math.floor(m / 60);
  return (m % 60) ? h + ' 小时 ' + (m % 60) + ' 分' : h + ' 小时';
}

export async function render(ctx) {
  const [d, llmData] = await Promise.all([
    api.cost(ctx.ws),
    api.llmUsage(100).catch((e) => ({ error: e, items: [], summary: {} }))
  ]);
  const ledger = d.ledger || { sec: 0, attempts: 0, success: 0, failed: 0 };
  const rows = d.rows || [];
  const byStage = d.by_stage || [];
  const byEp = d.by_episode || [];
  const est = d.estimate || {};
  const sum = est.summary || {};
  const avg = d.avg_shot || { sec: 0, human: '—', sample: 0 };
  const llm = llmData || {};
  const llmSummary = llm.summary || {};
  const llmItems = llm.items || [];
  const llmKnown = Number(llmSummary.cost_records || 0);
  const llmUnknown = Number(llmSummary.cost_unknown_records || 0);

  const maxStage = Math.max.apply(null, byStage.map((s) => s.sec).concat([1]));
  const srcTone = d.source === 'ledger' ? 'ok' : d.source === 'none' ? 'outline' : 'warn';

  const stageBars = byStage.map((s) => (
    '<div class="bar-row"><span class="muted">' + esc(s.stage || '其他') + '</span>'
    + '<span class="bar-track"><i class="bar-fill" style="width:'
    + Math.max(2, Math.round(s.sec / maxStage * 100)) + '%"></i></span>'
    + '<span class="right mono">' + esc(s.human || dur(s.sec)) + '</span></div>'
  )).join('') || '<div class="dim small">台账里还没有成功记录 —— 跑过一集之后这里才有分解。</div>';

  const epRows = byEp.map((e) => (
    '<tr><td class="mono">' + esc(e.ep || '—') + '</td>'
    + '<td class="num">' + esc(e.human || dur(e.sec)) + '</td>'
    + '<td class="num mono dim">' + Math.round(e.sec) + ' 秒</td></tr>'
  )).join('') || '<tr><td colspan="3"><div class="empty"><div class="empty-t">还没有按集记录</div>'
    + '<div class="empty-h">台账里每条 attempt 带 episode 字段时才会有这一列。</div></div></td></tr>';

  const detailRows = rows.slice(0, 120).map((r) => {
    const ok = OK.indexOf(r.status) >= 0;
    return '<tr><td class="mono small dim">' + esc(dt(r.at)) + '</td>'
      + '<td class="mono small">' + esc(r.episode || '—') + '</td>'
      + '<td class="small muted">' + esc(r.stage || '—') + '</td>'
      + '<td class="mono small">' + esc(r.shot_id || '—') + '</td>'
      + '<td>' + (ok ? badge('ok', '成功') : badge('bad', esc(r.status || '失败'))) + '</td>'
      + '<td class="num">' + (ok ? esc(dur(r.sec)) : '<span class="dim">未产出</span>') + '</td>'
      + '<td class="mono small dim">' + esc(String(r.task_id || '').slice(0, 12)) + '</td></tr>';
  }).join('') || '<tr><td colspan="7">' + emptyBox('台账为空', '出片或出图之后，这里会逐条列出每次实际占用。') + '</td></tr>';

  const llmRows = llmItems.map((r) => {
    const u = r.usage || {};
    const cost = r.cost || {};
    const known = typeof cost.usd === 'number';
    const bill = known
      ? badge('ok', '已知') + ' <span class="mono small">$' + esc(cost.usd) + '</span>'
      : badge('outline', '未知') + ' <span class="tiny dim">按量计费</span>';
    return '<tr><td class="mono tiny dim">' + esc(dt(r.at)) + '</td>'
      + '<td class="mono tiny">' + esc((r.project || '未归属').split(/[\\/]/).pop()) + '</td>'
      + '<td class="small">' + esc(r.purpose || '—') + '</td>'
      + '<td class="small muted">' + esc(r.provider_name || r.provider || '—')
      + '<div class="tiny dim mono">' + esc(r.actual_model || r.model || '') + '</div></td>'
      + '<td class="num tiny">' + esc(u.input_tokens == null ? '—' : u.input_tokens) + '</td>'
      + '<td class="num tiny">' + esc(u.output_tokens == null ? '—' : u.output_tokens) + '</td>'
      + '<td>' + bill + '</td></tr>';
  }).join('') || '<tr><td colspan="7">' + emptyBox('还没有 LLM 调用',
    '创作中心或制片助手调用模型后，这里会显示 token 与供应商账单状态。') + '</td></tr>';

  const llmError = llm.error
    ? '<div class="alert bad"><span class="nav-ico">' + icon('alert', 14) + '</span><div>读取 LLM 用量失败：'
      + esc(llm.error.detail || llm.error.message) + '</div></div>'
    : '';
  const llmCostText = llmSummary.cost_usd_known == null
    ? '未知（供应商未返回金额）'
    : ('$' + esc(llmSummary.cost_usd_known) + '（' + esc(llmKnown) + ' 条已知）');
  const llmStatus = llmSummary.cost_status === 'known' ? badge('ok', '全部已知')
    : llmSummary.cost_status === 'mixed' ? badge('warn', '部分已知')
      : llmSummary.cost_status === 'none' ? badge('outline', '暂无记录')
        : badge('outline', '按量计费');

  /* 置信度必须显眼：经验系数和实测值长得一样，但可信度差一个数量级 */
  const confTone = est.confidence === 'measured' ? 'ok' : 'warn';
  const confText = est.confidence === 'measured' ? '已用实测校准' : '经验系数';

  const html = ''
    + '<div class="page-head"><div><h1 class="page-title">用时</h1>'
    + '<div class="page-sub">默认通道跑在本机，费用 ￥0 —— 这时该看的是时间；'
    + '显式选了平台通道（RunningHub）才会计费，那部分单独一块列出来。</div></div>'
    + '<div class="page-actions">' + badge(srcTone, d.source === 'ledger' ? '来自耗时台账'
      : d.source === 'none' ? '还没跑过' : '部分数据') + '</div></div>'

    + '<div class="grid g4" style="margin-bottom:16px">'
    + '<div class="kpi"><div class="kpi-k">累计占用</div><div class="kpi-v">'
    + esc(ledger.human || dur(ledger.sec)) + '</div>'
    + '<div class="kpi-n mono">台账 ' + esc(rows.length) + ' 条尝试</div></div>'
    + '<div class="kpi"><div class="kpi-k">平均每镜</div><div class="kpi-v">'
    + esc(avg.human || '—') + '</div>'
    + '<div class="kpi-n">样本 ' + esc(avg.sample || 0) + ' 次</div></div>'
    + '<div class="kpi"><div class="kpi-k">单集预计</div><div class="kpi-v">'
    + esc(sum.episode_human || '—') + '</div>'
    + '<div class="kpi-n">瓶颈：' + esc(sum.bottleneck || '—') + '</div></div>'
    + '<div class="kpi"><div class="kpi-k">' + esc(sum.episodes || 30) + ' 集预计</div><div class="kpi-v">'
    + esc(sum.season_human || '—') + '</div>'
    + '<div class="kpi-n">单卡并发 1，不做并行</div></div>'
    + '</div>'

    // ★ 只有真花过钱才出现。纯本机跑时 coins 恒为 0，显示一块 ¥0 只会让人
    //   怀疑「计费是不是没接上」，然后去查一个不存在的问题。
    + ((Number(ledger.coins) || 0) > 0
      ? '<section class="card" style="margin-bottom:16px">'
        + '<div class="card-h"><h3>平台花费</h3>'
        + '<span class="card-sub">来自台账里逐次尝试的 usage</span>'
        + '<span class="spacer"></span>' + badge('warn', '★ 计费通道') + '</div>'
        + '<div class="card-b"><div class="grid g3">'
        + '<div class="kpi"><div class="kpi-k">RH 币</div><div class="kpi-v">'
        + esc(ledger.coins) + '</div><div class="kpi-n">按平台 usage 累计</div></div>'
        + '<div class="kpi"><div class="kpi-k">美元钱包</div><div class="kpi-v">'
        + esc(ledger.usd) + '</div><div class="kpi-n">部分通道按美元结算</div></div>'
        + '<div class="kpi"><div class="kpi-k">折人民币</div><div class="kpi-v">'
        + '￥' + esc(ledger.cny) + '</div><div class="kpi-n">按台账汇率折算，仅供参考</div></div>'
        + '</div></div>'
        + '<div class="card-foot">要省钱：把通道切回本机（出图出片的默认就是它），'
        + '或只对跑糊的那一镜单独重跑。</div></section>'
      : '')

    + '<section class="card" style="margin-bottom:16px">'
    + '<div class="card-h"><h3>LLM 调用</h3>'
    + '<span class="card-sub">全机器用量；历史记录可能尚未关联项目</span>'
    + '<span class="spacer"></span>' + llmStatus + '</div>'
    + '<div class="card-b">' + llmError
    + '<div class="row gap12" style="flex-wrap:wrap;margin-bottom:10px">'
    + '<span class="chip">' + esc(llmSummary.calls || 0) + ' 次调用</span>'
    + '<span class="chip">输入 ' + esc(llmSummary.input_tokens || 0) + ' tokens</span>'
    + '<span class="chip">输出 ' + esc(llmSummary.output_tokens || 0) + ' tokens</span>'
    + '<span class="chip">金额：' + llmCostText + '</span>'
    + '<span class="chip">未知 ' + esc(llmUnknown) + ' 条</span></div>'
    + '<div class="alert info" style="margin-bottom:10px"><span class="nav-ico">' + icon('alert', 14) + '</span><div>'
    + esc(llmSummary.cost_note || '金额只认供应商返回的 usage；未知不会显示成 ¥0，也不按 token 猜价。')
    + ' LLM 花费请以供应商后台账单为准。</div></div>'
    + '<div class="table-wrap"><table class="tb"><thead><tr>'
    + '<th style="width:96px">时间</th><th style="width:100px">项目</th><th>用途</th>'
    + '<th>提供商 / 模型</th><th class="num" style="width:64px">入</th>'
    + '<th class="num" style="width:64px">出</th><th style="width:130px">计费</th>'
    + '</tr></thead><tbody>' + llmRows + '</tbody></table></div></div>'
    + '<div class="card-foot">' + stamp('web/var/llm/usage.jsonl · 最近 100 条 · 已知/未知不合并') + '</div></section>'

    + '<div class="grid g21" style="margin-bottom:16px">'
    + '<section class="card"><div class="card-h"><h3>时间花在哪一步</h3>'
    + '<span class="card-sub">台账 stage 字段</span></div>'
    + '<div class="card-b">' + stageBars
    + '<div class="tiny dim" style="margin-top:8px">本仓库所有阶段都在本机执行，所以每一段都会出现在这里。'
    + '出片通常占七成以上 —— 缩短它的唯一办法是少重跑，不是加并发。</div></div>'
    + '<div class="card-foot">' + stamp((d.source_text || '本机耗时台账') + ' · 20 秒缓存') + '</div></section>'

    + '<section class="card"><div class="card-h"><h3>按集</h3></div>'
    + '<div class="card-b tight"><div class="table-wrap"><table class="tb"><thead><tr>'
    + '<th>集</th><th class="num">占用</th><th class="num">秒</th></tr></thead><tbody>' + epRows
    + '</tbody></table></div></div></section></div>'

    + '<section class="card"><div class="card-h"><h3>逐次明细</h3>'
    + '<span class="card-sub">每次尝试的实际占用（失败不产出画面，所以不计入平均值）</span>'
    + '<span class="spacer"></span>'
    + badge(confTone, confText) + '</div>'
    + '<div class="card-b tight"><div class="table-wrap" style="max-height:520px"><table class="tb"><thead><tr>'
    + '<th style="width:96px">时间</th><th style="width:72px">集</th><th style="width:110px">阶段</th>'
    + '<th>镜头</th><th style="width:80px">状态</th><th class="num" style="width:90px">占用</th>'
    + '<th style="width:104px">任务号</th>'
    + '</tr></thead><tbody>' + detailRows + '</tbody></table></div></div>'
    + '<div class="card-foot"><span class="nav-ico">' + icon('alert', 14) + '</span>'
    + '<span class="tiny muted">' + esc(est.basis || '预估依据未知') + '。'
    + '预估口径说明：' + esc(est.confidence === 'measured' ? '已用本机实测反推，可信。'
      : '尚未实测，误差可能较大（首次真跑后用 drama time plan --calibrate 校准）。') + '</span></div></section>';

  return { html };
}
