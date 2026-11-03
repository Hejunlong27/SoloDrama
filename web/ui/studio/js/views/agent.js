/* ============================================================
   agent.js —— 制片助手（对话驱动整条产线）

   和「点按钮」的关系
   -----------------
   按钮是**确定性**的：知道要跑什么，点它就行。
   助手是**探索性**的：不知道下一步该做什么（缺什么？该先出图还是先改剧本？），
   或者不想一页页点。它读状态、调工具、汇报，人只说「继续」。

   三条纪律（和 backend agent.py 一致）
   ----------------------------------
   1. 工具是白名单：没有 shell、没有任意路径写；06-提示词 契约它碰不到。
   2. 占 GPU 的命令要人点头（「允许占用 GPU」开关），默认关。
   3. 每一步都摊开给人看（右侧轨迹），不藏黑箱 —— 出问题时要能指着某一步说「这里错了」。
   ============================================================ */
import { api } from '../api.js';
import { esc, icon, badge, toast, paintIcons } from '../ui.js';

const STARTERS = [
  '把这部片从灵感到成片推进到底：先看状态，缺什么补什么，每步做完告诉我',
  '现在卡在哪一步？下一步该做什么，直接帮我做掉',
  '把第 1 集的分镜图补齐，缺哪几镜列给我',
  '帮我检查剧本和分镜的连续性，有问题直接改'
];

let MSG = [];            /* 对话历史（只放 user/assistant，工具轨迹单独存） */
let STEPS = [];          /* 最近一轮的工具轨迹 */
let busy = false;
let auto = false;        /* 自动继续（不每步确认） */
let allowGpu = false;    /* 允许占 GPU */
let wsKey = '';

function reset(ws) {
  if (wsKey === ws) return;
  wsKey = ws;
  MSG = [];
  STEPS = [];
}

function bubble(m, i) {
  const me = m.role === 'user';
  return '<div class="ag-row ' + (me ? 'me' : 'ai') + '">'
    + '<div class="ag-b' + (me ? ' me' : '') + '">' + esc(m.content) + '</div></div>';
}

function stepLine(s) {
  const r = s.result || {};
  const ok = r.ok !== false;
  const tone = ok ? 'done' : (r.need_confirm ? 'confirm' : 'fail');
  const detail = ok
    ? (r.detail || (r.mode === 'job' ? '已入队 ' + r.job : '') || (r.status ? '状态 ' + r.status : '完成'))
    : (r.detail || '失败');
  return '<div class="ag-step">'
    + '<div class="row" style="gap:8px;align-items:baseline">'
    + '<i class="dot ' + tone + '"></i>'
    + '<span class="mono tiny">' + s.n + '. ' + esc(s.tool) + '</span>'
    + (s.ms ? '<span class="tiny dim">' + s.ms + 'ms</span>' : '')
    + '<span class="spacer"></span>'
    + (ok ? '' : badge('warn', r.need_confirm ? '待确认' : '失败'))
    + '</div>'
    + (s.args && Object.keys(s.args).length
      ? '<div class="tiny dim mono" style="margin-left:14px">' + esc(JSON.stringify(s.args).slice(0, 160)) + '</div>'
      : '')
    + '<div class="tiny" style="margin-left:14px;color:' + (ok ? 'var(--txt-2)' : 'var(--warning, var(--accent))') + '">'
    + esc(String(detail).slice(0, 220)) + '</div>'
    + ((r.tail && !ok) ? '<pre class="log" style="margin-left:14px;max-height:110px;font-size:10px">'
      + esc(r.tail.slice(-600)) + '</pre>' : '')
    + '</div>';
}

function chatHtml() {
  if (!MSG.length) {
    return '<div class="ag-empty">'
      + '<div class="ag-empty-t">跟它说要做的事，它自己去读状态、调工具</div>'
      + '<div class="ag-empty-h">比如「把这一集从剧本推到出片」，或者「看一下现在卡在哪」。'
      + '它只能调白名单里的工具：不写 06-提示词 契约、不花站外的钱、占 GPU 前会先问你。</div>'
      + '<div class="ag-starters">' + STARTERS.map((s, i) =>
        '<button class="ag-chip" data-starter="' + i + '">' + esc(s) + '</button>').join('') + '</div>'
      + '</div>';
  }
  let out = '';
  MSG.forEach((m, i) => {
    out += bubble(m, i);
    /* 最后一条助手消息后面挂这一轮的工具轨迹 */
    if (m.role === 'assistant' && i === MSG.length - 1 && STEPS.length) {
      out += '<div class="ag-trace">' + STEPS.map(stepLine).join('') + '</div>';
    }
  });
  return out;
}

export async function render(ctx) {
  reset(ctx.ws);
  const html = ''
    + '<div class="page-head"><div>'
    + '<div class="crumb"><b>当前项目</b><span class="sep">/</span><b>'
    + esc(ctx.project ? (ctx.project.title || ctx.project.path) : ctx.ws) + '</b></div>'
    + '<h1 class="page-title">助手</h1>'
    + '<div class="page-sub">用对话把整条产线走完：它读状态、调引擎、汇报。'
    + '工具是白名单，占 GPU 前会先问你。</div></div>'
    + '<div class="page-actions">'
    + '<button class="chip' + (auto ? ' on' : '') + '" id="agAuto" title="每步不再等你确认（写盘仍会备份）">自动继续</button>'
    + '<button class="chip' + (allowGpu ? ' on' : '') + '" id="agGpu" title="允许它提交占 GPU 的命令（出图/出片）">允许占用 GPU</button>'
    + '<button class="btn quiet" id="agClear">' + icon('refresh', 14) + ' 新对话</button>'
    + '</div></div>'

    + '<div class="ag-wrap">'
    + '<div class="card ag-chat"><div class="card-b ag-log" id="agLog">' + chatHtml() + '</div>'
    + '<div class="ag-input"><textarea class="textarea" id="agText" rows="3" '
    + 'placeholder="说你要什么（Ctrl+Enter 发送）。例：把第 1 集从分镜图推到出片"></textarea>'
    + '<div class="col" style="gap:6px;align-items:stretch">'
    + '<button class="btn primary" id="agSend">' + icon('play', 14) + ' 发送</button>'
    + '<span class="tiny dim" id="agMeta" style="text-align:center"></span></div></div>'
    + '</div>'

    + '<div class="card ag-side"><div class="card-h"><h3>能力边界</h3>'
    + '<span class="card-sub">它能做什么、不能做什么</span></div><div class="card-b">'
    + '<div class="clist">'
    + '<div class="clitem"><span class="mk ok">' + icon('check', 12) + '</span><div class="body">'
    + '<div class="ttl">能读</div><div class="desc">项目状态、创作层全部 md、每集镜头/分镜图/段/母版进度</div></div></div>'
    + '<div class="clitem"><span class="mk ok">' + icon('check', 12) + '</span><div class="body">'
    + '<div class="ttl">能写</div><div class="desc">企划 / 资产库 / 剧本 / 导演手册（旧版自动备份）。'
    + '改稿要么你明确要求，要么它先说清改什么</div></div></div>'
    + '<div class="clitem"><span class="mk ok">' + icon('check', 12) + '</span><div class="body">'
    + '<div class="ttl">能跑</div><div class="desc">引擎白名单命令（导入/出图/分镜图/出片/剪辑/发行）。'
    + '占 GPU 的要你打开上面的开关</div></div></div>'
    + '<div class="clitem"><span class="mk off">' + icon('lock', 12) + '</span><div class="body">'
    + '<div class="ttl">不能做</div><div class="desc">改 <span class="mono">06-提示词/</span> 契约、'
    + '执行任意 shell、花站外的钱、删项目</div></div></div>'
    + '</div>'
    + '<div class="alert info" style="margin-top:10px"><span class="nav-ico">' + icon('alert', 14) + '</span>'
    + '<div class="tiny">它和你点按钮跑的是同一条命令、同一套校验。区别只是「谁来点」。</div></div>'
    + '</div></div></div>';

  return {
    html,
    mount: (root) => {
      paintIcons(root);
      const log = root.querySelector('#agLog');
      const ta = root.querySelector('#agText');
      const meta = root.querySelector('#agMeta');
      const btn = root.querySelector('#agSend');

      const scroll = () => { log.scrollTop = log.scrollHeight; };
      scroll();

      root.querySelectorAll('[data-starter]').forEach((b) => {
        b.onclick = () => { ta.value = STARTERS[Number(b.dataset.starter)]; ta.focus(); };
      });
      const a = root.querySelector('#agAuto');
      a.onclick = () => { auto = !auto; a.classList.toggle('on', auto); toast(auto ? '自动继续：开' : '自动继续：关'); };
      const g = root.querySelector('#agGpu');
      g.onclick = () => {
        allowGpu = !allowGpu;
        g.classList.toggle('on', allowGpu);
        toast(allowGpu ? '已允许占用 GPU（出图/出片会直接提交）' : '已禁止占 GPU，出片前会先问你', allowGpu ? 'warn' : 'ok');
      };
      root.querySelector('#agClear').onclick = () => {
        MSG = []; STEPS = [];
        ctx.refresh();
      };

      const send = async (text) => {
        const t = String(text || '').trim();
        if (!t || busy) return;
        busy = true;
        MSG.push({ role: 'user', content: t });
        log.innerHTML = chatHtml() + '<div class="ag-row ai"><div class="ag-b"><span class="spinner"></span>'
          + ' 正在读状态并决定下一步…</div></div>';
        scroll();
        btn.disabled = true;
        meta.textContent = '思考中';
        try {
          const r = await api.agentChat({
            ws: ctx.ws, messages: MSG, auto, allow_gpu: allowGpu
          });
          STEPS = r.steps || [];
          MSG.push({ role: 'assistant', content: r.reply || (r.ok ? '（没有回复）' : '出错了') });
          meta.textContent = [r.model || '', (r.elapsed || 0) + 's',
            r.usage && r.usage.total_tokens ? r.usage.total_tokens + ' tok' : '']
            .filter(Boolean).join(' · ');
          if (!r.ok && r.error) toast('模型侧出错：' + r.error, 'bad');
        } catch (e) {
          MSG.push({ role: 'assistant', content: '请求失败：' + (e.detail || e.message) });
          toast('失败：' + (e.detail || e.message), 'bad');
        } finally {
          busy = false;
          btn.disabled = false;
          log.innerHTML = chatHtml();
          scroll();
        }
      };

      btn.onclick = () => { const v = ta.value; ta.value = ''; send(v); };
      ta.onkeydown = (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); btn.click(); }
      };
      if (!MSG.length) ta.focus();
    }
  };
}
