/* ============================================================
   agent.js —— 助手（整页入口）

   ★ 2026-11-04：助手已改成**浮窗**（见 js/agent-panel.js + js/float.js）。
     这一页不再承载对话本身，只做两件事：
       1. 深链入口 `#/agent` 的落地页 —— 直接把人引到浮窗，别让人以为功能没了；
       2. 摊开「它能做什么、不能做什么」，这些话放在浮窗里太占地方。

   为什么整页版不再保留一份对话
   --------------------------
   两份 DOM 共享一份状态，发一句话只有一边会更新，另一边的历史是假的。
   真要做，得写同步层 —— 而这一页的用途只是「第一次知道有这个功能」，
   不值得为它背一套双向绑定。
   ============================================================ */
import { esc, icon, paintIcons } from '../ui.js';
import { openAgent } from '../agent-panel.js';
import { S, project as currentProject } from '../store.js';

export async function render(ctx) {
  const p = currentProject();
  const name = p ? (p.title || p.path) : (S.ws || '未选择项目');

  const html = ''
    + '<div class="page-head"><div>'
    + '<div class="crumb"><b>当前项目</b><span class="sep">/</span><b>' + esc(name) + '</b></div>'
    + '<h1 class="page-title">助手</h1>'
    + '<div class="page-sub">用对话把整条产线走完：它读状态、调引擎、汇报。'
    + '工具是白名单，占 GPU 前会先问你。</div></div>'
    + '<div class="page-actions">'
    + '<button class="btn primary" id="agOpen">' + icon('spark', 14) + ' 打开助手窗口</button>'
    + '</div></div>'

    + '<div class="ag-intro">'
    + '<div class="card"><div class="card-b ag-intro-b">'
    + '<div class="ag-intro-ico">' + icon('spark', 22) + '</div>'
    + '<div>'
    + '<div class="ag-intro-t">助手现在是一个浮窗</div>'
    + '<div class="ag-intro-d">拖标题栏移动，拖边角改大小，双击标题栏铺满内容区。'
    + '这样你可以左边看着画布或分镜页，右边直接问它 —— 关掉窗口对话和没发出去的草稿都还在，'
    + '下次点左侧「助手」就接着聊。</div>'
    + '<div class="row" style="gap:8px;margin-top:12px;flex-wrap:wrap">'
    + '<button class="btn primary" id="agOpen2">' + icon('spark', 14) + ' 现在打开</button>'
    + '<button class="btn quiet" data-go="graph">' + icon('canvas', 14) + ' 去画布试试</button>'
    + '<button class="btn quiet" data-go="boards">' + icon('board', 14) + ' 去分镜试试</button>'
    + '</div></div></div></div>'

    + '<div class="card"><div class="card-h"><h3>它能做什么、不能做什么</h3>'
    + '<span class="card-sub">工具是白名单，不是「什么都能干」</span></div><div class="card-b">'
    + '<div class="clist">'
    + '<div class="clitem"><span class="mk ok">' + icon('check', 12) + '</span><div class="body">'
    + '<div class="ttl">能读</div><div class="desc">项目状态、创作层全部 md、每集镜头/分镜图/段/母版进度，'
    + '以及 ComfyUI 是否在线</div></div></div>'
    + '<div class="clitem"><span class="mk ok">' + icon('check', 12) + '</span><div class="body">'
    + '<div class="ttl">能写</div><div class="desc">企划 / 资产库 / 剧本 / 导演手册（旧版自动备份）。'
    + '改稿要么你明确要求，要么它先说清改什么</div></div></div>'
    + '<div class="clitem"><span class="mk ok">' + icon('check', 12) + '</span><div class="body">'
    + '<div class="ttl">能跑</div><div class="desc">引擎白名单命令（导入 / 出图 / 分镜图 / 出片 / 剪辑 / 发行）。'
    + '占 GPU 的要你打开浮窗里的开关</div></div></div>'
    + '<div class="clitem"><span class="mk off">' + icon('lock', 12) + '</span><div class="body">'
    + '<div class="ttl">不能做</div><div class="desc">改 <span class="mono">06-提示词/</span> 契约、'
    + '执行任意 shell、花站外的钱、删项目</div></div></div>'
    + '</div>'
    + '<div class="alert info" style="margin-top:12px"><span class="nav-ico">' + icon('alert', 14) + '</span>'
    + '<div class="tiny">它和你点按钮跑的是同一条命令、同一套校验。区别只是「谁来点」。</div></div>'
    + '</div></div>'

    + '<div class="card"><div class="card-h"><h3>可以这样开口</h3>'
    + '<span class="card-sub">说目标，不用说步骤</span></div><div class="card-b">'
    + '<div class="ag-say">'
    + ['把这部片从灵感到成片推进到底，缺什么补什么，每步做完告诉我',
      '现在卡在哪一步？下一步该做什么，直接帮我做掉',
      '把第 1 集的分镜图补齐，缺哪几镜列给我',
      '帮我检查剧本和分镜的连续性，有问题直接改']
      .map((s) => '<div class="ag-say-i"><span class="mono tiny dim">›</span><span>' + esc(s) + '</span></div>')
      .join('')
    + '</div></div></div>'
    + '</div>';

  return {
    html,
    mount: (root) => {
      paintIcons(root);
      const open = () => openAgent();
      ['#agOpen', '#agOpen2'].forEach((sel) => {
        const b = root.querySelector(sel);
        if (b) b.onclick = open;
      });
      root.querySelectorAll('[data-go]').forEach((b) => {
        b.onclick = () => ctx.navigate(b.dataset.go);
      });
    }
  };
}
