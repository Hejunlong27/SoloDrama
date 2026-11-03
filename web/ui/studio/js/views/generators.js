/* 生成通道：图像 / 视频 各条通道的真实状态（全部在本机 ComfyUI）
   数据来自 /api/generators —— 只读台账，不提交任务、不产生费用。
   为什么单独一页：文生图与图生图是**两套工作流**，混在一起看就会出现
   「传了参考图却出纯文生图」这种花钱买错东西的情况。 */
import { api } from '../api.js';
import { S } from '../store.js';
import { esc, icon, badge, toast, openModal } from '../ui.js';

const ST_TONE = { ready: 'ok', config: 'warn', offline: 'warn', missing: 'bad', unsupported: 'outline', no_ws: 'outline' };

function row(it) {
  const tone = ST_TONE[it.status] || 'outline';
  const missing = (it.missing || []).length
    ? '<div class="tiny dim" style="margin-top:4px">缺：' + esc(it.missing.slice(0, 3).join('；'))
      + ((it.missing || []).length > 3 ? ' 等 ' + it.missing.length + ' 项' : '') + '</div>'
    : '';
  return '<tr>'
    + '<td><div class="row gap8"><span>' + esc(it.label) + '</span>'
    + badge(it.billing === 'free' ? 'ok' : 'warn', it.cost_text) + '</div>'
    + '<div class="row-sub">' + esc(it.model_text || '') + '</div></td>'
    + '<td><div class="small">' + esc(it.engine_text) + '</div>'
    + '<div class="row-sub mono">' + esc(it.mode_text) + '</div></td>'
    + '<td>' + badge(tone, it.status_text)
    + '<div class="tiny dim" style="margin-top:4px;max-width:420px">' + esc(it.detail || '') + '</div>'
    + missing + '</td>'
    + '<td class="small dim" style="max-width:260px">' + esc(it.next || '—') + '</td>'
    + '<td class="right mono tiny dim">' + esc(it.command || '—') + '</td>'
    + '</tr>';
}

function section(kind, title, sub, items) {
  const body = items.map(row).join('');
  return '<section class="card" style="margin-bottom:16px">'
    + '<div class="card-h"><h3>' + esc(title) + '</h3>'
    + '<span class="card-sub">' + esc(sub) + '</span></div>'
    + '<div class="card-b tight"><div class="table-wrap"><table class="tb"><thead><tr>'
    + '<th style="width:30%">通道 / 模型</th><th style="width:12%">引擎 · 模式</th>'
    + '<th style="width:28%">状态</th><th>下一步</th><th class="right">命令</th>'
    + '</tr></thead><tbody>' + body + '</tbody></table></div></div></section>';
}

export async function render(ctx, opts) {
  const embedded = !!(opts && opts.embedded);
  const d = await api.generators(ctx.ws).catch((e) => ({ error: String(e && e.message || e) }));
  if (d.error) {
    return {
      html: '<div class="page-head"><div><h1 class="page-title">生成通道</h1></div></div>'
        + '<div class="alert bad"><span class="nav-ico">' + icon('alert', 14) + '</span>'
        + '<div>读不到通道状态：' + esc(d.error) + '</div></div>',
      mount: () => {}
    };
  }
  const items = d.items || [];
  const imgs = items.filter((x) => x.kind === 'image');
  const vids = items.filter((x) => x.kind === 'video');
  const c = d.counts || {};
  const comfy = d.comfy || {};

  const acts = '<button class="btn quiet" id="btnReload">' + icon('refresh', 14) + ' 重新探测</button>';
  const summary = '图像 ' + ((c.image || {}).ready || 0) + '/' + ((c.image || {}).total || 0)
    + ' 可用 · 视频 ' + ((c.video || {}).ready || 0) + '/' + ((c.video || {}).total || 0)
    + ' 可用 · 出图与出片都在本机，￥0（占 GPU 时间）';
  /* 嵌入到连接中心时不再画页头（否则一个页面两个大标题），只留一行工具按钮 */
  const html = ''
    + (embedded
      ? '<div class="row" style="justify-content:flex-end;gap:8px;margin-bottom:10px">' + acts + '</div>'
      : '<div class="page-head"><div><h1 class="page-title">生成通道</h1>'
        + '<div class="page-sub">' + summary + '</div></div>'
        + '<div class="page-actions">' + acts + '</div></div>')

    + '<div class="alert ' + (comfy.online ? 'info' : 'warn') + '" style="margin-bottom:14px">'
    + '<span class="nav-ico">' + icon('cpu', 14) + '</span><div>'
    + (comfy.online
      ? '本地 ComfyUI 在线（v' + esc(comfy.version || '?') + ' · 空闲 ' + (comfy.vram_free_gb || 0) + 'G）。'
        + '文生图走 Qwen-Image，图生视频走 MiniMax H3。'
      : '本地 ComfyUI 未启动：' + esc(comfy.reason || '') + '。启动后点右上角「重新探测」。')
    + '</div></div>'

    + section('image', '图像模型', '文生图 / 图生图 是两套工作流，分别登记', imgs)
    + section('video', '视频模型', '本地 MiniMax H3 图生视频', vids)

    + '<div class="alert info"><span class="nav-ico">' + icon('alert', 14) + '</span><div>'
    + '「状态」来自真实探测：核对 ComfyUI 在线 + 工作流节点类 + 模型文件齐全。'
    + '不联网、不提交任务、不产生任何费用。</div></div>';

  return {
    html,
    mount: (root) => {
      const b = root.querySelector('#btnReload');
      if (b) {
        b.onclick = async () => {
          b.disabled = true;
          try { await ctx.refresh(); toast('已重新探测'); } catch (e) { b.disabled = false; }
        };
      }
    }
  };
}
