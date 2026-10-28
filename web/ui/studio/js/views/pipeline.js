/* 流水线：把 11 个环节串成一条线，按顺序推进。
   两种模式：逐步确认（每步停下）/ 连跑（预算内自动放行，遇人工或超预算停）。
   数据来自 /api/pipeline（只读计划），执行走 /api/pipeline/run。 */
import { api } from '../api.js';
import { esc, icon, badge, toast } from '../ui.js';

const ACT_TONE = { auto: 'ok', ask: 'warn', blocked: 'bad', manual: 'outline' };
const ACT_TEXT = { auto: '可自动', ask: '需确认', blocked: '被前置挡住', manual: '需人工' };
const ST_TEXT = { done: '已完成', current: '进行中', todo: '未开始' };

function stageRow(s) {
  const tone = ACT_TONE[s.action] || 'outline';
  const blk = (s.blocked || []).length
    ? '<div class="tiny dim" style="margin-top:3px">缺：' + esc(s.blocked.slice(0, 3).join('、')) + '</div>' : '';
  return '<tr>'
    + '<td class="mono">' + esc(s.id) + '</td>'
    + '<td><div class="row gap8"><span>' + esc(s.name) + '</span>'
    + badge(ST_TEXT[s.state] === '已完成' ? 'ok' : 'outline', ST_TEXT[s.state] || s.state) + '</div></td>'
    + '<td>' + badge(tone, ACT_TEXT[s.action] || s.action)
    + '<div class="tiny dim" style="margin-top:3px">' + esc(s.action_text || '') + '</div></td>'
    + '<td class="small dim" style="max-width:420px">' + esc(s.detail || '') + blk + '</td>'
    + '<td class="right mono tiny dim">' + esc(s.cmd || '—') + '</td>'
    + '</tr>';
}

export async function render(ctx) {
  const state = { budget: 100, auto: true, until: '', last: null };
  const d = await api.pipeline(ctx.ws, state.budget).catch((e) => ({ error: String(e && e.message || e) }));

  const html = ''
    + '<div class="page-head"><div><h1 class="page-title">流水线</h1>'
    + '<div class="page-sub">按环节顺序推进：能自动的自动跑，需要人或超预算的停下来告诉你原因</div></div>'
    + '<div class="page-actions"><button class="btn quiet" id="btnPlan">' + icon('refresh', 14) + ' 重新算计划</button>'
    + '<button class="btn primary" id="btnRun">' + icon('play', 14) + ' 开始运行</button></div></div>'

    + '<div class="card" style="margin-bottom:14px"><div class="card-b" style="padding:12px 16px">'
    + '<div class="row gap8" style="flex-wrap:wrap;align-items:center">'
    + '<span class="small">模式</span>'
    + '<label class="row gap8" style="cursor:pointer"><input type="radio" name="pmode" value="step"> 逐步确认</label>'
    + '<label class="row gap8" style="cursor:pointer"><input type="radio" name="pmode" value="auto" checked> 连跑（流水线）</label>'
    + '<span class="spacer"></span>'
    + '<span class="small">预算（RH币，只对计费环节生效）</span>'
    + '<input class="input mono" id="pBudget" value="' + state.budget + '" style="width:110px">'
    + '<span class="tiny dim">估不出金额的计费环节会停下来问你，不猜</span>'
    + '</div></div></div>'

    + (d.error
      ? '<div class="alert bad"><span class="nav-ico">' + icon('alert', 14) + '</span><div>'
        + esc(d.error) + '</div></div>'
      : '<div class="row gap8" style="margin-bottom:12px;flex-wrap:wrap">'
        + badge('ok', '可自动 ' + ((d.counts || {}).auto || 0))
        + badge('warn', '需确认 ' + ((d.counts || {}).ask || 0))
        + badge('bad', '被挡 ' + ((d.counts || {}).blocked || 0))
        + badge('outline', '需人工 ' + ((d.counts || {}).manual || 0))
        + '<span class="spacer"></span><span class="tiny dim">预计花费 ' + (d.est_total || 0) + ' / 预算 '
        + (d.budget || 0) + ' RH币</span></div>'
        + '<section class="card"><div class="card-b tight"><div class="table-wrap">'
        + '<table class="tb"><thead><tr><th style="width:6%">环节</th><th style="width:16%">名称</th>'
        + '<th style="width:13%">动作</th><th>说明</th><th class="right">命令</th></tr></thead><tbody>'
        + (d.stages || []).map(stageRow).join('')
        + '</tbody></table></div></div></section>')

    + '<div id="runOut" style="margin-top:16px"></div>'

    + '<div class="alert info" style="margin-top:16px"><span class="nav-ico">' + icon('alert', 14) + '</span><div>'
    + '「连跑」只推进 <b>可自动</b> 的环节：前置未齐（引擎 probes 未过）、需要人工判断、'
    + '或计费金额估不出来的，都会停下来并写明原因。一次运行默认最多 6 步，防跑飞。'
    + '</div></div>';

  return {
    html,
    mount: (root) => {
      const budgetEl = root.querySelector('#pBudget');
      const out = root.querySelector('#runOut');
      const paint = (r) => {
        if (!r) return;
        const rows = (r.ran || []).map((x) => '<div class="row gap8" style="padding:6px 0;border-bottom:1px solid var(--line)">'
          + badge(x.rc === 0 || x.rc === null ? 'ok' : 'bad', x.id)
          + '<span class="small flex1">' + esc(x.cmd) + (x.dry_run ? '（演练）' : '')
          + (x.elapsed ? ' · ' + x.elapsed + 's' : '') + '</span>'
          + '<span class="mono tiny dim">' + esc(x.argv || '') + '</span></div>').join('');
        const skip = (r.skipped || []).map((x) => '<div class="tiny dim" style="padding:4px 0">'
          + esc(x.id) + ' 跳过：' + esc(x.why) + '</div>').join('');
        out.innerHTML = '<section class="card"><div class="card-h"><h3>本次运行</h3>'
          + '<span class="card-sub">' + (r.dry_run ? '演练（未执行命令）' : '已执行') + '</span></div>'
          + '<div class="card-b">' + (rows || '<div class="tiny dim">没有可自动执行的环节</div>')
          + (skip ? '<div style="margin-top:10px">' + skip + '</div>' : '') + '</div></section>';
      };
      root.querySelector('#btnPlan').onclick = async () => {
        try { await ctx.refresh(); toast('已重新计算'); } catch (e) { /* ignore */ }
      };
      root.querySelector('#btnRun').onclick = async () => {
        const auto = (root.querySelector('input[name="pmode"]:checked') || {}).value === 'auto';
        const budget = Number(budgetEl.value) || 0;
        const btn = root.querySelector('#btnRun');
        btn.disabled = true;
        try {
          const r = await api.pipelineRun({
            ws: ctx.ws, budget, dry_run: false,
            max_steps: auto ? 6 : 1
          });
          paint(r);
          toast(r.ok ? (auto ? '连跑完成' : '已跑 1 步') : '中途停下，原因见下方', r.ok ? 'ok' : 'warn');
        } catch (e) {
          toast('运行失败：' + (e && e.message ? e.message : e), 'bad');
        } finally {
          btn.disabled = false;
        }
      };
    }
  };
}
