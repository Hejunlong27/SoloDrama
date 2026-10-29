/* 助手（对话模式）：用一句话问状态，或让它带你去某页 / 跑某一步。

   边界很清楚：
     * 后端只返回「回答 + 一个提案」，**不执行任何东西**；
     * 跳页由前端直接做（无副作用）；
     * 跑命令必须过确认弹窗，而且走的是流水线的 `only=`（自带前置检查与预算裁决）。 */
import { api } from './api.js';
import { esc, icon, openDrawer, closeDrawer, openModal, toast } from './ui.js';

const HISTORY = [];          // 只留最近几轮，够模型理解上下文即可

function bubble(role, text) {
  return '<div class="chat-row ' + (role === 'user' ? 'me' : 'ai') + '">'
    + '<div class="chat-bubble">' + esc(text).replace(/\n/g, '<br>') + '</div></div>';
}

/* 引导候选：点一下就等于把这句话说出去 —— 用户不用想「我该怎么问」 */
function chipsHTML(list) {
  const arr = (list || []).filter(Boolean).slice(0, 3);
  return arr.map((t) => '<button class="chat-chip" data-say="' + esc(t) + '">'
    + esc(t) + '</button>').join('');
}

/* 动作条：模型提案 + 状态推导的「去 XX」。
   两条来源分开画：前者是模型建议（可能没有），后者由服务端按卡点算，永远不会缺。 */
function actionBar(a, goto) {
  const out = [];
  if (a && a.type === 'navigate') {
    out.push('<div class="chat-act"><button class="btn primary sm" data-act="go" data-route="'
      + esc(a.route) + '" data-label="' + esc(a.label || a.route) + '">' + icon('external', 12) + ' 带我去' + esc(a.label || a.route)
      + '</button>' + (a.why ? '<span class="tiny dim">' + esc(a.why) + '</span>' : '') + '</div>');
  } else if (a && a.type === 'run') {
    out.push('<div class="chat-act"><button class="btn primary sm" data-act="run" data-stage="'
      + esc(a.stage || '') + '" data-cmd="' + esc(a.command || '') + '">'
      + icon('play', 12) + ' 执行 ' + esc(a.label || a.stage || a.command) + '</button>'
      + '<span class="tiny dim">' + esc(a.why || '会先让你确认') + '</span></div>');
  }
  const dup = a && a.type === 'navigate' && a.route === (goto || {}).route;
  if (goto && goto.route && !dup) {
    out.push('<div class="chat-act"><button class="btn quiet sm" data-act="go" data-route="'
      + esc(goto.route) + '" data-label="' + esc(goto.label || goto.route) + '">' + icon('external', 12) + ' 去' + esc(goto.label || goto.route)
      + '</button><span class="tiny dim">' + esc(goto.why || '当前该去这里') + '</span></div>');
  }
  return out.join('');
}

export function openAssistant(ctx) {
  const drawer = openDrawer({
    title: '助手 · 对话控制',
    html: '<div class="chat-wrap">'
      + '<div class="chat-hint alert info" id="chatHint"><span class="nav-ico">' + icon('spark', 14)
      + '</span><div>我能读状态、能带路、能跑免费的那几步；花钱和写盘的动作一定先问你。</div></div>'
      + '<div class="chat-log" id="chatLog">'
      + bubble('ai', '正在看当前状态…')
      + '</div>'
      + '<div class="chat-chips" id="chatChips"></div>'
      + '<div class="chat-input"><textarea class="textarea" id="chatText" rows="2" '
      + 'placeholder="例如：现在卡在哪一步？（Enter 发送，Shift+Enter 换行）"></textarea>'
      + '<button class="btn primary" id="chatSend">' + icon('play', 14) + ' 发送</button></div></div>',
    foot: '<span class="tiny dim" id="chatModel">模型：读取中…</span>'
      + '<span class="spacer"></span><button class="btn quiet" data-close="drawer">关闭</button>'
  });

  const log = drawer.querySelector('#chatLog');
  const text = drawer.querySelector('#chatText');
  const send = drawer.querySelector('#chatSend');
  const hint = drawer.querySelector('#chatHint div');
  const chips = drawer.querySelector('#chatChips');
  const modelLine = drawer.querySelector('#chatModel');
  const first = log.firstElementChild;

  const push = (html) => { log.insertAdjacentHTML('beforeend', html); log.scrollTop = log.scrollHeight; };
  const setChips = (list) => {
    const arr = (list || []).filter(Boolean).slice(0, 3);
    chips.innerHTML = chipsHTML(arr);
    chips.classList.toggle('on', arr.length > 0);
  };

  /* 开口第一屏走服务端的 welcome：按当前状态给引导语 + 可点的下一步 —— 不花钱 */
  api.assistantWelcome(ctx.ws).then((w) => {
    if (!w) return;
    if (first) {
      const b = first.querySelector('.chat-bubble');
      if (b) b.innerHTML = esc(w.greeting || '').replace(/\n/g, '<br>');
    }
    if (w.tips && w.tips.length) hint.innerHTML = w.tips.map((t) => esc(t)).join('<br>');
    setChips(w.suggestions);
    modelLine.textContent = '模型：' + (w.model || '未接模型');
  }).catch(() => {
    if (first) first.remove();
    setChips(['现在卡在哪一步？', '我的环境有什么问题？']);
  });

  chips.addEventListener('click', (e) => {
    const b = e.target.closest('[data-say]');
    if (!b || send.disabled) return;
    text.value = b.getAttribute('data-say') || '';
    ask();
  });

  const runStage = (stage, cmd) => {
    if (!stage) {
      closeDrawer();
      location.hash = '#/pipeline';
      toast('这条命令不在流水线的可自动清单里，去流水线页面看');
      return;
    }
    openModal({
      title: '执行 ' + stage + '？',
      icon: 'play',
      html: '<div class="stack"><div class="small">即将执行流水线的 <b>' + esc(stage) + '</b>'
        + '（命令 <span class="mono">' + esc(cmd) + '</span>）。</div>'
        + '<div class="alert info"><span class="nav-ico">' + icon('alert', 14) + '</span><div>'
        + '前置没齐会停下并说明；计费环节若估不出金额也会停下问你 —— 不会偷偷花钱。</div></div></div>',
      foot: '<span class="spacer"></span><button class="btn quiet" data-close="modal">取消</button>'
        + '<button class="btn primary" id="aiRun">确认执行</button>',
      mount: () => {
        document.getElementById('aiRun').onclick = async () => {
          const b = document.getElementById('aiRun');
          b.disabled = true;
          try {
            const r = await api.pipelineRun({ ws: ctx.ws, budget: 0, dry_run: false,
              only: stage, max_steps: 1 });
            toast(r.ok ? stage + ' 已执行' : stage + ' 中途停下，去流水线看原因', r.ok ? 'ok' : 'warn');
            if (r.ok) ctx.refresh();
          } catch (e) {
            toast('执行失败：' + ((e.detail) || e.message), 'bad');
          } finally {
            b.disabled = false;
            closeDrawer();
            location.hash = '#/pipeline';
          }
        };
      }
    });
  };

  log.addEventListener('click', (e) => {
    const b = e.target.closest('[data-act]');
    if (!b) return;
    if (b.dataset.act === 'go') {
      const label = b.getAttribute('data-label') || b.dataset.route;
      closeDrawer();
      location.hash = '#/' + b.dataset.route;
      toast('已到' + label);
    } else if (b.dataset.act === 'run') {
      runStage(b.dataset.stage, b.dataset.cmd);
    }
  });

  const ask = async () => {
    const msg = (text.value || '').trim();
    if (!msg) return;
    push(bubble('user', msg));
    text.value = '';
    setChips([]);                       // 旧的引导先收起，免得和新回答对不上
    send.disabled = true;
    push('<div class="chat-row ai"><div class="chat-bubble dim">思考中…</div></div>');
    const pending = log.lastElementChild;
    try {
      const r = await api.assistantChat({ ws: ctx.ws, message: msg, history: HISTORY.slice(-8) });
      HISTORY.push({ role: 'user', text: msg });
      HISTORY.push({ role: 'assistant', text: r.reply || '' });
      pending.remove();
      push(bubble('ai', r.reply || '（没有回复）'));
      if (r.simulated) {
        push('<div class="chat-row ai"><div class="tiny dim">⚠ 这是离线演练（Mock）的回答，'
          + '不是真模型。去「AI 模型中心」确认提供商已接通。</div></div>');
      }
      const bar = actionBar(r.action, r.goto);
      if (bar) push(bar);
      setChips(r.suggestions);          // 接着问什么，由这次回答给出
    } catch (e) {
      pending.remove();
      push(bubble('ai', '出错了：' + (typeof e.detail === 'string' ? e.detail : (e.detail && e.detail.message) || e.message)));
      setChips(['现在卡在哪一步？', '我的环境有什么问题？']);
    } finally {
      send.disabled = false;
      text.focus();
    }
  };

  send.onclick = ask;
  text.onkeydown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask(); }
  };
  setTimeout(() => text.focus(), 60);
}
