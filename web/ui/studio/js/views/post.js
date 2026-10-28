/* 后期制作：按集汇总母版/放大/字幕 + 成片播放 + GPU 动作（拼接 / 放大 / 烧字幕）
   G6 停点：字幕必须由用户明确选择「要 / 不要」，不默认烧。 */
import { api, mediaUrl } from '../api.js';
import { esc, icon, badge, dot, toast, stamp, openModal, paintIcons } from '../ui.js';
import { runAction } from '../action.js';

let curEp = '';

export async function render(ctx) {
  const eps = await api.episodes(ctx.ws);
  const list = eps.items || [];
  if (!curEp || !list.some((e) => e.ep === curEp)) curEp = (list[0] || {}).ep || '';
  const e = list.find((x) => x.ep === curEp) || null;

  const epList = list.map((x) => (
    '<button class="nav-item' + (x.ep === curEp ? ' active' : '') + '" data-ep="' + esc(x.ep) + '"'
    + ' style="height:34px;border-left-width:2px">' + dot(x.state)
    + '<span class="nav-text mono">' + esc(x.ep) + '</span>'
    + (x.subbed ? '<span class="nav-badge">字</span>' : '') + '</button>'
  )).join('') || '<div class="dim small" style="padding:10px">还没有集</div>';

  const steps = e ? [
    { n: 1, t: '拼接母版', ok: !!e.master, file: e.master, hint: '逐段合并 + 帧数校验' },
    { n: 2, t: '高清放大', ok: !!e.upscaled, file: e.upscaled, hint: '1080x1920（Topaz 独占 GPU）' },
    { n: 3, t: '字幕', ok: !!e.subbed, file: e.subbed, hint: 'G6：不问你就不烧' },
    { n: 4, t: 'BGM 混音', ok: !!e.mix, file: e.mix, hint: '配乐脚本未纳入白名单（未接入）' }
  ] : [];

  const stepsHtml = steps.map((s) => (
    '<div class="clitem"><span class="mk ' + (s.ok ? 'ok' : 'off') + '">'
    + (s.ok ? icon('check', 12) : s.n) + '</span>'
    + '<div class="body"><div class="ttl"><span>' + esc(s.t) + '</span>'
    + (s.ok ? badge('ok', '已完成') : badge('muted', s.n === 4 ? '未接入' : '未生成')) + '</div>'
    + '<div class="desc">' + esc(s.hint) + (s.file ? ' · <span class="mono">' + esc(s.file) + '</span>' : '') + '</div></div>'
    + '<div>' + (s.n === 3 && e.upscaled && !e.subbed
      ? '<button class="btn quiet sm" data-ask-sub="1">要不要字幕</button>' : '') + '</div></div>'
  )).join('');

  const playable = e && (e.subbed || e.upscaled || e.master);

  const html = ''
    + '<div class="page-head"><div>'
    + '<div class="crumb"><b>项目管理</b><span class="sep">/</span><b>'
    + esc(ctx.project ? (ctx.project.title || ctx.project.path) : ctx.ws) + '</b></div>'
    + '<h1 class="page-title">后期制作</h1>'
    + '<div class="page-sub">产物按真实文件名判定（<span class="mono">_master</span> / '
    + '<span class="mono">_master_WxH</span> / <span class="mono">_subbed</span> / <span class="mono">_mix</span>）</div></div>'
    + '<div class="page-actions"><span class="badge outline" title="GPU 为独占资源">GPU 独占</span></div></div>'

    + '<div class="grid" style="grid-template-columns:110px minmax(0,1fr);gap:16px;align-items:start">'
    + '<section class="card"><div class="card-h"><h3>集</h3></div><div class="card-b" style="padding:6px">'
    + epList + '</div></section>'

    + '<div class="stack">'
    + '<section class="card"><div class="card-h"><h3>' + esc(curEp || '未选择集') + ' 收尾</h3>'
    + '<span class="card-sub">中断需整集重跑</span><span class="spacer"></span>'
    + (e ? (e.state === 'done' ? badge('ok', '镜头已出完') : badge('warn', '还有镜头未完成')) : '')
    + '</div><div class="card-b" style="padding-top:4px">'
    + (stepsHtml || '<div class="empty"><div class="empty-t">还没有可收尾的集</div></div>')
    + '</div>'
    + '<div class="card-foot">' + stamp('07-成片/subs/&lt;ep&gt;/ · 6 秒缓存') + '</div></section>'

    + '<div class="grid g2">'
    + '<section class="card"><div class="card-h"><h3>成片预览</h3>'
    + (playable ? badge('live', '可播放') : badge('muted', '无产物')) + '</div><div class="card-b">'
    + (playable
      ? '<div class="video-box"><video controls preload="metadata" src="'
        + esc(mediaUrl(ctx.ws, playable)) + '"></video></div>'
        + '<div class="tiny dim mono" style="margin-top:8px">' + esc(playable) + '</div>'
      : '<div class="placeholder"><div class="ph-icon">' + icon('film', 22) + '</div>'
        + '这一集还没有母版/成片，先跑「拼接母版」</div>')
    + '</div></section>'

    + '<section class="card"><div class="card-h"><h3>执行</h3><span class="card-sub">本地 GPU · 不花钱</span></div>'
    + '<div class="card-b">'
    + '<div class="row-gap">'
    + '<button class="btn quiet" data-run="media.master">' + icon('film', 14) + ' 只拼母版（快速核对节奏）</button>'
    + '<button class="btn quiet" data-run="media.assemble">' + icon('cpu', 14) + ' 拼接 + 高清放大（8–10 分钟/集）</button>'
    + '<button class="btn quiet" data-run="media.render">' + icon('upload', 14) + ' 烧字幕（G6 停点后）</button>'
    + '</div>'
    + '<div class="alert info" style="margin-top:12px"><span class="nav-ico">' + icon('alert', 14) + '</span>'
    + '<div>这三个动作会占用本机 GPU 并写入工作区；开始前会弹确认，显示影响范围。'
    + 'BGM 混音尚未接入（<span class="mono">bgm.py</span> 不在白名单）。</div></div>'
    + '</div></section></div></div></div>';

  return {
    html,
    mount: (root) => {
      root.querySelectorAll('[data-ep]').forEach((b) => {
        b.onclick = () => { curEp = b.dataset.ep; ctx.refresh(); };
      });
      root.querySelectorAll('[data-run]').forEach((b) => {
        b.onclick = () => {
          if (!curEp) { toast('先选一集', 'warn'); return; }
          const spec = b.dataset.run;
          const label = spec === 'media.master' ? '只拼母版'
            : spec === 'media.assemble' ? '拼接 + 高清放大' : '烧字幕';
          confirmGpu(ctx, label, spec, curEp);
        };
      });
      const ask = root.querySelector('[data-ask-sub]');
      if (ask) ask.onclick = () => askSubtitle(ctx);
      paintIcons(root);
    }
  };
}

function confirmGpu(ctx, label, spec, ep) {
  openModal({
    title: label + ' · ' + ep,
    icon: 'cpu',
    html: '<div class="cost-line"><span class="k">动作</span><span class="v mono">' + esc(spec) + '</span></div>'
      + '<div class="cost-line"><span class="k">费用</span><span class="v">¥0（占用本机 GPU）</span></div>'
      + '<div class="cost-line"><span class="k">影响</span><span class="v">写入 07-成片/subs/' + esc(ep) + '/</span></div>'
      + '<div class="alert warn" style="margin-top:12px"><span class="nav-ico">' + icon('alert', 14) + '</span>'
      + '<div>期间 GPU 被独占（放大/字幕不能并行）；中断需整集重跑。'
      + '作业在服务端执行，可以离开本页。</div></div>',
    foot: '<span class="spacer"></span><button class="btn quiet" data-close="modal">取消</button>'
      + '<button class="btn primary" id="okGpu">开始</button>',
    mount: () => {
      document.getElementById('okGpu').onclick = () => {
        document.getElementById('modal').classList.remove('on');
        runAction(ctx, {
          specId: spec,
          title: label + ' · ' + ep,
          params: spec === 'media.render' ? { ep, burn: true } : { ep },
          onDone: () => ctx.refresh()
        });
      };
    }
  });
}

function askSubtitle(ctx) {
  openModal({
    title: '这一集要不要加字幕？',
    icon: 'alert',
    html: '<div class="small">引擎在放大完成后会停在这里等你决定（G6 停点）。</div>'
      + '<div class="alert info" style="margin-top:12px"><span class="nav-ico">' + icon('alert', 14) + '</span>'
      + '<div>选「不要」只交付无字幕母版，不会事后自动补；选「要」会烧录字幕（占用 GPU）。</div></div>',
    foot: '<span class="spacer"></span><button class="btn quiet" id="noSub">不要字幕</button>'
      + '<button class="btn primary" id="yesSub">要字幕</button>',
    mount: () => {
      document.getElementById('noSub').onclick = () => {
        document.getElementById('modal').classList.remove('on');
        toast('已记录：只交付无字幕母版');
      };
      document.getElementById('yesSub').onclick = () => {
        document.getElementById('modal').classList.remove('on');
        confirmGpu(ctx, '烧字幕', 'media.render', curEp);
      };
    }
  });
}
