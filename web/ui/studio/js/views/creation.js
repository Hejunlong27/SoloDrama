/* 创作中心：S1–S5 的真实完成度（引擎 probes）+ 免费校验 + AI 剧本正文闭环
   两条纪律：
     1. 完成度只看引擎判据（workflow.py status 的 probes），不靠勾选；
     2. AI 正文走「草稿 → 人工编辑 → 确认落盘」：生成阶段绝不碰 03-剧本/ep_NN.md。 */
import { api } from '../api.js';
import { esc, icon, badge, dot, stamp, openDrawer, closeDrawer, closeModal, paintIcons, toast, confirmCost, kv } from '../ui.js';
import { runAction } from '../action.js';

const ACTIONS = [
  { spec: 'market.check', title: '市场覆盖度检查', hint: '近 2 个月 / 多市场 / 西语市场', params: {} },
  { spec: 'topic.score', title: '七维评分', hint: '合规≤3 一票否决；独特性≤3 封顶 74.9', params: {} },
  { spec: 'script.lint', title: 'FFS 结构自检', hint: '四件套 / 钩子不重复 / 反转改变力量对比', params: {} },
  { spec: 'timing.check', title: '台词时长审计', hint: '30 秒单元 60–90 字，上限 100 字', params: { unit: 30 } },
  { spec: 'script.continuity', title: '五锚连续性门禁', hint: '剧本↔分镜↔提示词的台词指纹', params: {} }
];

const STAGE_IDS = ['S1', 'S2', 'S3', 'S4', 'S5'];

export async function render(ctx) {
  const [wf, gates, drafts, purposes] = await Promise.all([
    api.workflow(ctx.ws).catch((e) => ({ stages: [], reason: e.detail || e.message })),
    api.scriptGates(ctx.ws).catch((e) => ({ ok: false, items: [], reason: e.detail || e.message })),
    api.drafts(ctx.ws).catch(() => ({ items: [] })),
    api.llmPurposes().catch(() => ({ items: [] }))
  ]);
  const gen = (purposes.items || []).find((p) => p.id === 'script.generate') || {};

  const stages = (wf.stages || []).filter((s) => STAGE_IDS.indexOf(s.id) >= 0);
  const cards = stages.map((s) => {
    const miss = (s.probes || []).filter((p) => !p.ok);
    return '<section class="card" style="margin-bottom:12px">'
      + '<div class="card-h">' + dot(s.done ? 'done' : 'todo')
      + '<h3>' + esc(s.id + ' ' + s.name) + '</h3>'
      + (s.optional ? badge('outline', '可选') : '')
      + '<span class="spacer"></span>'
      + (s.done ? badge('ok', '已完成') : badge('warn', '未完成')) + '</div>'
      + '<div class="card-b">'
      + '<div class="small muted" style="margin-bottom:8px">' + esc(s.what || '') + '</div>'
      + (s.probes || []).map((p) => '<div class="row" style="padding:3px 0">'
        + '<i class="dot ' + (p.ok ? 'done' : 'fail') + '"></i>'
        + '<span class="small">' + esc(p.label) + '</span>'
        + '<span class="spacer"></span><span class="mono tiny dim">' + esc(p.found) + ' / ' + esc(p.need) + '</span>'
        + '</div>').join('')
      + (miss.length ? '<div class="alert warn" style="margin-top:8px"><span class="nav-ico">' + icon('alert', 14)
        + '</span><div>还差 ' + miss.length + ' 项判据；补齐后本环节自动转为完成（不靠勾选）。</div></div>'
        : '')
      + (s.note ? '<div class="tiny dim" style="margin-top:8px">' + esc(s.note) + '</div>' : '')
      + '</div></section>';
  }).join('') || '<div class="card"><div class="empty"><div class="empty-t">未取到流程状态</div>'
    + '<div class="empty-h">' + esc(wf.reason === 'script_missing' ? '引擎脚本缺失或解释器不可用。'
      : '可能是工作区缺少 layout.json。') + '</div></div></div>';

  const html = ''
    + '<div class="page-head"><div>'
    + '<div class="crumb"><b>项目管理</b><span class="sep">/</span><b>'
    + esc(ctx.project ? (ctx.project.title || ctx.project.path) : ctx.ws) + '</b></div>'
    + '<h1 class="page-title">创作中心</h1>'
    + '<div class="page-sub">S1 调研 → S2 剧本 → S3 资产设计；完成度来自产物判据</div></div>'
    + '<div class="page-actions"><button class="btn quiet" id="btnWfRefresh">'
    + icon('refresh', 14) + ' 重新读取</button></div></div>'

    + aiPanel(ctx, gates, gen, drafts.items || [])

    + '<div class="grid g21">'
    + '<div>' + cards + '</div>'
    + '<div class="stack">'
    + '<section class="card"><div class="card-h"><h3>免费校验</h3>'
    + '<span class="card-sub">只读，不产生费用</span></div><div class="card-b">'
    + ACTIONS.map((a) => '<div style="padding:8px 0;border-bottom:1px solid var(--line)">'
      + '<div class="row"><div class="flex1"><div class="small">' + esc(a.title) + '</div>'
      + '<div class="tiny dim">' + esc(a.hint) + '</div></div>'
      + '<button class="btn quiet sm" data-spec="' + esc(a.spec) + '">运行</button></div></div>').join('')
    + '<div class="tiny dim" style="margin-top:10px">结果以「退出码 + 文本输出」呈现：'
    + '这些脚本没有 <span class="mono">--json</span>，所以不假装有结构化结论。</div>'
    + '</div></section>'

    + '<section class="card"><div class="card-h"><h3>数据来源</h3></div><div class="card-b">'
    + stamp('workflow.py status --json · 5 秒缓存') + '</div></section>'
    + '</div></div>';

  return {
    html,
    mount: (root) => {
      paintIcons(root);
      const rf = root.querySelector('#btnWfRefresh');
      if (rf) rf.onclick = () => ctx.refresh();
      root.querySelectorAll('[data-spec]').forEach((b) => {
        b.onclick = () => {
          const a = ACTIONS.find((x) => x.spec === b.dataset.spec);
          runAction(ctx, { specId: a.spec, title: a.title, params: a.params, onDone: () => ctx.refresh() });
        };
      });
      mountAi(ctx, root, gates, gen);
    }
  };
}

/* ---------- AI 剧本正文 ---------- */
function aiPanel(ctx, gates, gen, drafts) {
  const items = (gates.items || []).map((it) => '<div class="row" style="padding:3px 0">'
    + '<i class="dot ' + (it.ok ? 'done' : 'fail') + '"></i>'
    + '<span class="small">' + esc(it.label) + '</span>'
    + '<span class="spacer"></span><span class="tiny dim">' + esc(it.detail || '') + '</span></div>').join('');

  const bound = gen.ready
    ? badge('ok', (gen.provider_name || '') + ' / ' + (gen.model || ''))
    : badge('warn', gen.bound ? '提供商已停用' : '未绑定提供商');

  const epOpts = [];
  const n = gates.ep_count || 0;
  for (let i = 1; i <= n; i += 1) {
    epOpts.push('<option value="' + i + '">EP' + String(i).padStart(2, '0') + '</option>');
  }

  const draftRows = drafts.slice(0, 6).map((d) => (
    '<div class="row" style="padding:6px 0;border-top:1px solid var(--line)">'
    + '<span class="mono small">EP' + String(d.ep).padStart(2, '0') + '</span>'
    + (d.status === 'confirmed' ? badge('ok', '已落盘') : badge('outline', '草稿'))
    + '<span class="tiny dim">' + esc(d.shots) + ' 镜 · ' + esc(d.model || '') + '</span>'
    + '<span class="spacer"></span>'
    + '<button class="btn quiet sm" data-draft="' + esc(d.id) + '">打开</button></div>'
  )).join('');

  return '<section class="card" style="margin-bottom:14px">'
    + '<div class="card-h">' + icon('spark', 16) + '<h3>AI 剧本正文</h3>'
    + '<span class="card-sub">真实调用统一网关 · 草稿先落 draft，确认后才写 03-剧本/</span>'
    + '<span class="spacer"></span>' + bound + '</div>'
    + '<div class="card-b">'
    + items
    + (gates.blocking ? '<div class="alert warn" style="margin-top:8px"><span class="nav-ico">' + icon('alert', 14)
      + '</span><div>诊断卡未确认：<b>可以生成草稿，但不允许落盘</b>。'
      + '先跑 <span class="mono">script_rewrite.py diagnose --check → --confirm</span>。</div></div>' : '')
    + (gates.ok ? '' : '<div class="alert bad" style="margin-top:8px"><span class="nav-ico">' + icon('alert', 14)
      + '</span><div>前置不齐（见上），生成会被引擎口径拦下。</div></div>')

    + '<div class="row gap8" style="margin-top:12px;flex-wrap:wrap">'
    + '<select class="select" id="genEp" style="width:120px">' + (epOpts.join('') || '<option value="">无集数</option>') + '</select>'
    + '<button class="btn quiet" id="btnPreview">预览提示词</button>'
    + '<button class="btn primary" id="btnGen"' + (gen.ready ? '' : ' disabled') + '>'
    + icon('spark', 14) + ' 生成草稿</button>'
    + (gen.ready ? '' : '<span class="tiny dim">先在「AI 模型中心 → 用途路由」把「剧本正文生成」绑定到提供商</span>')
    + '</div>'

    + (draftRows ? '<div style="margin-top:12px"><div class="tiny dim" style="margin-bottom:2px">最近草稿</div>'
      + draftRows + '</div>' : '')

    + '</div><div class="card-foot">' + stamp('core/llm · 模板来自 stages/creation/prompts/s3-script-rewrite.md')
    + '</div></section>';
}

function mountAi(ctx, root, gates, gen) {
  const sel = root.querySelector('#genEp');
  const btnGen = root.querySelector('#btnGen');
  const btnPrev = root.querySelector('#btnPreview');

  const reload = () => ctx.refresh();

  root.querySelectorAll('[data-draft]').forEach((b) => {
    b.onclick = () => openDraft(ctx, b.dataset.draft, reload);
  });

  if (btnPrev) {
    btnPrev.onclick = async () => {
      const ep = Number((sel && sel.value) || 0);
      if (!ep) { toast('先选一集', 'warn'); return; }
      btnPrev.disabled = true;
      try {
        const c = await api.scriptContext(ctx.ws, ep);
        const pv = await api.llmPreview({ purpose: 'script.generate', variables: variablesOf(c) });
        openDrawer({
          title: '提示词预览 · EP' + String(ep).padStart(2, '0'),
          html: '<div class="stack">'
            + kv([['模板', pv.template_id, true], ['指纹', pv.template_sha, true],
              ['要求能力', (pv.requires || []).join('、') || '无'],
              ['长度', pv.system_chars + ' + ' + pv.user_chars + ' 字符']])
            + '<div class="tiny dim">system（仓库原文）</div>'
            + '<pre class="log" style="max-height:34vh;white-space:pre-wrap">' + esc(pv.system) + '</pre>'
            + '<div class="tiny dim">user（本次输入 + 输出契约）</div>'
            + '<pre class="log" style="max-height:34vh;white-space:pre-wrap">' + esc(pv.user) + '</pre>'
            + '<div class="alert info"><span class="nav-ico">' + icon('alert', 14) + '</span><div>'
            + '这一步<b>只渲染，不调用模型</b>，不产生费用。</div></div></div>',
          foot: '<span class="spacer"></span><button class="btn quiet" data-close="drawer">关闭</button>',
          mount: (r) => paintIcons(r)
        });
      } catch (e) {
        toast('预览失败：' + (e.detail || e.message), 'bad');
      } finally {
        btnPrev.disabled = false;
      }
    };
  }

  if (btnGen) {
    btnGen.onclick = () => {
      const ep = Number((sel && sel.value) || 0);
      if (!ep) { toast('先选一集', 'warn'); return; }
      confirmCost({
        title: '生成剧本正文（会产生真实调用）',
        lines: [
          ['动作', 'EP' + String(ep).padStart(2, '0') + ' 单集正文'],
          ['模型', (gen.provider_name || '—') + ' / ' + (gen.model || '—')],
          ['产物', '只写草稿，不碰 03-剧本/'],
          ['费用', '由供应商结算，本页不预估']
        ],
        note: '生成结果会先存成草稿，自检与 Schema 校验通过后才可确认落盘。费用以供应商账单为准。',
        onOk: async () => {
          btnGen.disabled = true;
          btnGen.innerHTML = '<span class="spinner"></span>生成中（可能 30–120 秒）';
          try {
            const res = await api.scriptGenerate(ctx.ws, { ep, confirm: true });
            if (!res.ok) {
              const e = res.error || {};
              toast('生成失败（' + (e.kind || '未知') + '）：' + (e.message || ''), 'bad');
              return;
            }
            toast('草稿已生成');
            openDraft(ctx, res.draft.id, reload);
            reload();
          } catch (err) {
            const d = err.detail;
            toast('生成失败：' + (typeof d === 'string' ? d : (d && d.message) || err.message), 'bad');
          } finally {
            btnGen.disabled = false;
            btnGen.innerHTML = icon('spark', 14) + ' 生成草稿';
          }
        }
      });
    };
  }
}

/* 与 core/llm/drafts.py::generate 的变量拼装保持一致（否则预览与真实调用不同源） */
function variablesOf(c) {
  const h = c.header || [];
  return {
    blueprint_row: c.blueprint_row || {},
    style_lock: c.style_lock || '',
    char_header: h[4] || '',
    scene_header: h[5] || '',
    ep_seconds: c.ep_seconds,
    shot_count: c.shot_count
  };
}

async function openDraft(ctx, did, reload) {
  let d;
  try {
    d = (await api.draft(ctx.ws, did)).draft;
  } catch (e) {
    toast('读取草稿失败：' + (e.detail || e.message), 'bad');
    return;
  }
  const checks = (d.checks || []).map((c) => '<div class="row" style="padding:2px 0">'
    + '<i class="dot ' + (c.ok ? 'done' : 'fail') + '"></i>'
    + '<span class="small">' + esc(c.text) + '</span></div>').join('');
  const warns = (d.warnings || []).map((w) => '<div class="tiny dim">· ' + esc(w) + '</div>').join('');
  const confirmed = d.status === 'confirmed';

  openDrawer({
    title: '草稿 · EP' + String(d.ep).padStart(2, '0'),
    html: '<div class="stack">'
      + (d.simulated ? '<div class="alert warn"><span class="nav-ico">' + icon('alert', 14)
        + '</span><div><b>这是离线演练草稿</b>：由 Mock 通道生成，<b>没有经过真实模型</b>。'
        + '默认不允许写入正式剧本；确实要演练落盘，请勾选下方确认项。</div></div>' : '')
      + kv([
        ['状态', confirmed ? '已落盘' : '草稿'],
        ['生成方式', d.simulated ? '离线演练（Mock，未调用模型）' : '真实模型调用'],
        ['模型', (d.provider_name || '') + ' / ' + (d.model || ''), true],
        ['用量', (d.usage && (d.usage.input_tokens || 0) + ' 入 / ' + (d.usage.output_tokens || 0) + ' 出') || '—'],
        ['金额', (d.cost && d.cost.usd != null) ? ('$' + d.cost.usd) : '未知（供应商未返回）'],
        ['落点', d.target || '', true]
      ])
      + (checks ? '<div>' + checks + '</div>' : '')
      + (warns ? '<div class="alert info"><span class="nav-ico">' + icon('alert', 14) + '</span><div>' + warns + '</div></div>' : '')
      + '<div class="tiny dim">正文（可直接编辑，改完点「保存修改」；确认落盘只对已保存的内容生效）</div>'
      + '<textarea class="textarea" id="draftMd" rows="18" style="font-family:var(--font-mono);font-size:var(--fs-12)"'
      + (confirmed ? ' readonly' : '') + '>' + esc(d.md || '') + '</textarea>'
      + (confirmed ? '<div class="alert warn"><span class="nav-ico">' + icon('alert', 14) + '</span><div>'
        + '该草稿已落盘，不能再改。要重写请重新生成一份新草稿。</div></div>' : '')
      + '</div>',
    foot: '<span class="spacer"></span>'
      + (confirmed ? '' : '<button class="btn quiet" id="dSave">保存修改</button>'
        + (d.simulated
          ? '<label class="chk" style="margin:0 10px"><input type="checkbox" id="dSim">'
            + '<span>我明白这是演练稿</span></label>'
          : '')
        + '<label class="chk" style="margin:0 10px"><input type="checkbox" id="dOver"><span>覆盖已有剧本</span></label>'
        + '<button class="btn primary" id="dConfirm"' + (d.simulated ? ' disabled' : '') + '>确认落盘</button>')
      + '<button class="btn quiet" data-close="drawer">关闭</button>',
    mount: (r) => {
      paintIcons(r);
      const sv = r.querySelector('#dSave');
      if (sv) {
        sv.onclick = async () => {
          const md = r.querySelector('#draftMd').value;
          sv.disabled = true;
          try {
            await api.draftSave(ctx.ws, did, { md });
            toast('已保存草稿修改');
            if (reload) reload();
          } catch (e) {
            toast('保存失败：' + (e.detail || e.message), 'bad');
          } finally { sv.disabled = false; }
        };
      }
      const sim = r.querySelector('#dSim');
      const cf = r.querySelector('#dConfirm');
      if (sim && cf) sim.onchange = () => { cf.disabled = !sim.checked; };
      if (cf) {
        cf.onclick = async () => {
          const over = r.querySelector('#dOver').checked;
          const simulated = !!(r.querySelector('#dSim') && r.querySelector('#dSim').checked);
          cf.disabled = true;
          cf.innerHTML = '<span class="spinner"></span>写入中';
          try {
            const res = await api.draftConfirm(ctx.ws, did,
              { confirm: true, overwrite: over, allow_simulated: simulated });
            toast((res.simulated ? '演练稿已写入 ' : '已写入 ')
              + (res.target || '').split(/[\\/]/).pop()
              + (res.backup ? '（旧版已备份）' : ''));
            closeDrawer();
            if (reload) reload();
          } catch (e) {
            const d2 = e.detail;
            const msg = typeof d2 === 'string' ? d2 : (d2 && d2.message) || e.message;
            toast('落盘失败：' + msg, 'bad');
            if (String(msg).indexOf('覆盖') >= 0) r.querySelector('#dOver').checked = false;
          } finally {
            cf.disabled = false;
            cf.textContent = '确认落盘';
          }
        };
      }
    }
  });
}
