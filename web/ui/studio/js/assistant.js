/* 助手（对话模式）：用一句话问状态，或让它带你去某页 / 跑某一步。

   边界很清楚：
     * 后端只返回「回答 + 一个提案」，**不执行任何东西**；
     * 跳页由前端直接做（无副作用）；
     * 跑命令必须过确认弹窗，而且走的是流水线的 `only=`（自带前置检查与预算裁决）。 */
import { api } from './api.js';
import { S } from './store.js';
import { esc, icon, openDrawer, closeDrawer, openModal, toast } from './ui.js';

const HISTORY = [];          // 只留最近几轮，够模型理解上下文即可

function bubble(role, text) {
  return '<div class="chat-row ' + (role === 'user' ? 'me' : 'ai') + '">'
    + '<div class="chat-bubble">' + esc(text).replace(/\n/g, '<br>') + '</div></div>';
}

function actionBar(a) {
  if (!a || a.type === 'none') return '';
  if (a.type === 'navigate') {
    return '<div class="chat-act"><button class="btn primary sm" data-act="go" data-route="'
      + esc(a.route) + '">' + icon('external', 12) + ' 带我去 ' + esc(a.route) + '</button>'
      + (a.why ? '<span class="tiny dim">' + esc(a.why) + '</span>' : '') + '</div>';
  }
  if (a.type === 'run') {
    return '<div class="chat-act"><button class="btn primary sm" data-act="run" data-stage="'
      + esc(a.stage || '') + '" data-cmd="' + esc(a.command || '') + '">'
      + icon('play', 12) + ' 执行 ' + esc(a.stage || a.command) + '</button>'
      + '<span class="tiny dim">' + esc(a.why || '会先让你确认') + '</span></div>';
  }
  return '';
}

export function openAssistant(ctx) {
  const drawer = openDrawer({
    title: '助手 · 对话控制',
    html: '<div class="chat-wrap">'
      + '<div class="chat-hint alert info" id="chatHint"><span class="nav-ico">' + icon('spark', 14)
      + '</span><div>可以直接问「现在到哪一步了」「还缺什么」，也可以说「带我看看资产」「跑一下转分镜」。'
      + '写盘和计费的动作我一定先问你。</div></div>'
      + '<div class="chat-log" id="chatLog">'
      + bubble('ai', '我是这个工作台的助手。当前项目：' + (S.ws ? S.ws.split(/[\\/]/).pop() : '未选择')
        + '。想看什么、想做什么，直接说。')
      + '</div>'
      + '<div class="chat-input"><textarea class="textarea" id="chatText" rows="2" '
      + 'placeholder="例如：现在卡在哪一步？（Enter 发送，Shift+Enter 换行）"></textarea>'
      + '<button class="btn primary" id="chatSend">' + icon('play', 14) + ' 发送</button></div></div>',
    foot: '<span class="tiny dim">模型：DeepSeek（走内部网关，Key 不落到浏览器）</span>'
      + '<span class="spacer"></span><button class="btn quiet" data-close="drawer">关闭</button>'
  });

  const log = drawer.querySelector('#chatLog');
  const text = drawer.querySelector('#chatText');
  const send = drawer.querySelector('#chatSend');

  const push = (html) => { log.insertAdjacentHTML('beforeend', html); log.scrollTop = log.scrollHeight; };

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
      closeDrawer();
      location.hash = '#/' + b.dataset.route;
    } else if (b.dataset.act === 'run') {
      runStage(b.dataset.stage, b.dataset.cmd);
    }
  });

  const ask = async () => {
    const msg = (text.value || '').trim();
    if (!msg) return;
    push(bubble('user', msg));
    text.value = '';
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
      const bar = actionBar(r.action);
      if (bar) push(bar);
    } catch (e) {
      pending.remove();
      push(bubble('ai', '出错了：' + (typeof e.detail === 'string' ? e.detail : (e.detail && e.detail.message) || e.message)));
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
