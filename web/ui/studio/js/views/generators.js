/* 生成通道：图像 / 视频 各条通道的真实状态（本地 ComfyUI ｜ RunningHub 工作流）
   数据来自 /api/generators —— 只读台账，不提交任务、不产生费用。
   为什么单独一页：文生图与图生图是**两套工作流**，混在一起看就会出现
   「传了参考图却出纯文生图」这种花钱买错东西的情况。 */
import { api } from '../api.js';
import { S } from '../store.js';
import { esc, icon, badge, dt, emptyBox, toast, openModal } from '../ui.js';

const ST_TONE = { ready: 'ok', config: 'warn', offline: 'warn', missing: 'bad', unsupported: 'outline', no_ws: 'outline' };
const TASK_TONE = { planned: 'outline', estimated: 'warn', queued: 'warn', running: 'warn',
  succeeded: 'ok', failed: 'bad', canceled: 'outline', unknown: 'outline' };

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
    + '<td class="small dim" style="max-width:260px">' + esc(it.next || '—')
    + (it.endpoint
      ? '<div class="tiny dim mono" style="margin-top:4px">' + esc(it.endpoint)
        + (it.endpoint_via ? ' <span class="dim">（' + esc(it.endpoint_via) + '）</span>' : '')
        + '</div>' : '')
    + '</td>'
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
    + '<th style="width:28%">状态</th><th>下一步 / 实际地址</th><th class="right">命令</th>'
    + '</tr></thead><tbody>' + body + '</tbody></table></div></div></section>';

}

function money(value) {
  if (!value || typeof value.amount !== 'number') return '<span class="dim">未知</span>';
  return '<span class="mono">' + esc(value.amount) + ' ' + esc(value.currency || '') + '</span>';
}

function paramField(key, spec) {
  const label = '<label>' + esc(spec.label || key) + '</label>';
  if (spec.type === 'enum') {
    const opts = (spec.values || []).map((v) =>
      '<option value="' + esc(v) + '"' + (String(v) === String(spec.default) ? ' selected' : '') + '>'
      + esc(v) + '</option>').join('');
    return '<div class="field" data-pfield="' + esc(key) + '">' + label
      + '<select class="select" data-param="' + esc(key) + '">' + opts + '</select>'
      + (spec.note ? '<div class="help">' + esc(spec.note) + '</div>' : '') + '</div>';
  }
  if (spec.type === 'integer') {
    return '<div class="field" data-pfield="' + esc(key) + '">' + label
      + '<input class="input mono" type="number" data-param="' + esc(key) + '" value="'
      + esc(spec.default) + '" min="' + esc(spec.min) + '" max="' + esc(spec.max) + '">'
      + '<div class="help">范围 ' + esc(spec.min) + '–' + esc(spec.max)
      + (spec.unit ? ' ' + esc(spec.unit) : '') + '</div></div>';
  }
  if (spec.type === 'boolean') {
    return '<label class="chk" style="margin:8px 0"><input type="checkbox" data-param="' + esc(key) + '"'
      + (spec.default ? ' checked' : '') + '><span>' + esc(spec.label || key) + '</span></label>'
      + (spec.note ? '<div class="help">' + esc(spec.note) + '</div>' : '');
  }
  return '';
}

function catalogCard(catalog) {
  if (!catalog || !catalog.length) return '';
  const cards = catalog.map((m) => {
    const fields = Object.entries(m.parameters || {}).map(([k, v]) => paramField(k, v)).join('');
    const ref = m.kind === 'image'
      ? '<label class="chk" style="margin:8px 0"><input type="checkbox" data-ref="1">'
        + '<span>本次带参考图（GIF/SVG 校验用）</span></label>' : '';
    return '<div class="card" data-model-card="' + esc(m.id) + '" style="margin-bottom:12px">'
      + '<div class="card-h"><h3>' + esc(m.label || m.id) + '</h3>'
      + badge('outline', m.kind === 'image' ? '图像' : '视频')
      + '<span class="spacer"></span><span class="mono tiny dim">' + esc(m.id) + '</span></div>'
      + '<div class="card-b">' + fields + ref
      + '<div class="row" style="margin-top:10px"><button class="btn quiet sm" data-param-check="'
      + esc(m.id) + '">校验参数</button><span class="tiny dim">只校验，不提交任务、不产生费用。</span></div>'
      + '<pre class="log" data-param-out="' + esc(m.id) + '" style="display:none;margin-top:10px;max-height:220px"></pre>'
      + '</div></div>';
  }).join('');
  return '<section class="card" style="margin-bottom:16px"><div class="card-h"><h3>API 模型参数</h3>'
    + '<span class="card-sub">参数定义来自 configs/generation-models.json；模型各不相同</span></div>'
    + '<div class="card-b">' + cards + '</div>'
    + '<div class="card-foot">视频的时长和分辨率是标准参数；Muse 当前只开放 720p，时长 2–10 秒。</div></section>';
}

function tasksCard(tasks, error) {
  const rows = (tasks || []).map((t) => {
    const tone = TASK_TONE[t.status] || 'outline';
    return '<tr><td class="mono tiny">' + esc(t.id) + '</td>'
      + '<td><span class="small">' + esc(t.model) + '</span><div class="row-sub mono">'
      + esc(t.kind || '') + '</div></td>'
      + '<td>' + badge(tone, t.status || 'unknown') + '</td>'
      + '<td class="mono tiny dim">' + esc(String(t.remote_task_id || '—').slice(0, 24)) + '</td>'
      + '<td>' + money(t.estimate) + '</td><td>' + money(t.provider_usage_cost) + '</td><td>' + money(t.settled_cost) + '</td>'
      + '<td class="tiny dim">' + esc(dt(t.updated_at)) + '</td></tr>';
  }).join('') || '<tr><td colspan="9">' + emptyBox('还没有媒体任务',
    '报价、提交和轮询记录会落在 .drama/media/。') + '</td></tr>';
  return '<section class="card" style="margin-bottom:16px"><div class="card-h"><h3>媒体任务</h3>'
    + '<span class="card-sub">本地任务记录与远端 task ID；供应商 usage 为暂报，后台实结需对账</span></div>'
    + '<div class="card-b">' + (error ? '<div class="alert bad">' + esc(error) + '</div>' : '')
    + '<div class="table-wrap"><table class="tb"><thead><tr><th>本地 ID</th><th>模型</th>'
    + '<th>状态</th><th>远端 task ID</th><th>预估价</th><th>供应商暂报</th><th>后台实结</th><th>更新时间</th>'
    + '</tr></thead><tbody>' + rows + '</tbody></table></div></div></section>';
}

export async function render(ctx, opts) {
  const embedded = !!(opts && opts.embedded);
  const [d, taskData] = await Promise.all([
    api.generators(ctx.ws).catch((e) => ({ error: String(e && e.message || e) })),
    api.mediaTasks(ctx.ws, 100).catch((e) => ({ error: String(e && e.message || e), items: [] }))
  ]);
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
  const board = d.board_channel || { choice: '', engine: 'local', label: '本地 ComfyUI（￥0）' };
  const catalog = d.model_catalog || [];
  const taskItems = taskData.items || [];

  const acts = '<button class="btn quiet" id="btnReload">' + icon('refresh', 14) + ' 重新探测</button>'
    + '<button class="btn quiet" id="btnRhCfg">' + icon('settings', 14) + ' 配置云端工作流</button>';
  const summary = '图像 ' + ((c.image || {}).ready || 0) + '/' + ((c.image || {}).total || 0)
    + ' 可用 · 视频 ' + ((c.video || {}).ready || 0) + '/' + ((c.video || {}).total || 0)
    + ' 可用 · 分镜图：' + (board.label || board.choice || '本地 ComfyUI')
    + ' ｜ 本机 ￥0 ｜ 云端镜像按主机时长 ｜ 云端工作流按点数';
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

    + '<div class="alert ' + (board.paid ? 'warn' : 'info') + '" style="margin-bottom:14px">'
    + '<span class="nav-ico">' + icon('image', 14) + '</span><div>分镜图下游生图通道：<b>'
    + esc(board.label || board.choice || '本地 ComfyUI') + '</b>'
    + (board.fallback_local ? '（尚未确认 board，安全回落本地 ￥0）' : '')
    + (board.paid ? ' · ★ 计费，执行前需确认' : ' · 本机处理') + '</div></div>'

    + section('image', '图像模型', '文生图 / 图生图 是两套工作流，分别登记', imgs)
    + section('video', '视频模型', '本地 H3 图生视频 ｜ 云端 H3 工作流出片', vids)
    + catalogCard(catalog)
    + tasksCard(taskItems, taskData.error)

    + '<div class="alert info"><span class="nav-ico">' + icon('alert', 14) + '</span><div>'
    + '「状态」来自真实探测：ComfyUI 通道（本机 / 云端镜像）核对**服务在线 + 工作流节点类 + 模型文件**，'
    + '云端还会打印实例地址与来源；RunningHub 通道核对项目 '
    + '<span class="mono">video-pipeline/config.local.json</span> 里的工作流 ID 与节点映射。'
    + '换项目后这里会跟着变。云端行只在**模型确认单确实选了云端**时出现。</div></div>';

  return {
    html,
    mount: (root) => {
      const cfgBtn = root.querySelector('#btnRhCfg');
      if (cfgBtn) {
        cfgBtn.onclick = () => {
          const cur = (items.find((x) => x.id === 'image.rh.t2i') || {});
          openModal({
            title: '配置 RunningHub 工作流出图',
            html: '<div class="field"><label>文生图工作流 ID</label>'
              + '<input class="input mono" id="rhT2i" placeholder="在 RH 工作流页面运行一次后生成的 API 快照 ID">'
              + '<div class="help">纯提示词出图用这条。</div></div>'
              + '<div class="field"><label>图生图工作流 ID（可留空）</label>'
              + '<input class="input mono" id="rhI2i">'
              + '<div class="help">★ 图生图是**另一套**工作流：必须带一个「加载图像」节点，否则参考图不会被用上。</div></div>'
              + '<div class="field"><label>提示词节点 id</label>'
              + '<input class="input mono" id="rhPNode" placeholder="例如 6"></div>'
              + '<div class="field"><label>「加载图像」节点 id（填了图生图才需要）</label>'
              + '<input class="input mono" id="rhINode" placeholder="例如 12"></div>'
              + '<div class="help">只改本项目的 image_providers，其余配置原样保留；写前自动备份。</div>',
            foot: '<span class="spacer"></span><button class="btn quiet" data-close="modal">取消</button>'
              + '<button class="btn primary" id="rhOk">写入配置</button>',
            mount: () => {
              document.getElementById('rhOk').onclick = async () => {
                const body = {
                  ws: ctx.ws,
                  t2i_id: document.getElementById('rhT2i').value.trim(),
                  i2i_id: document.getElementById('rhI2i').value.trim(),
                  prompt_node: document.getElementById('rhPNode').value.trim(),
                  image_node: document.getElementById('rhINode').value.trim()
                };
                try {
                  const r = await api.setRhWorkflow(body);
                  document.getElementById('modal').classList.remove('on');
                  toast('已写入 ' + (r.provider || '') + '（已备份原配置）');
                  ctx.refresh();
                } catch (e) {
                  toast('写入失败：' + (e && e.message ? e.message : e), 'bad');
                }
              };
            }
          });
        };
      }

      root.querySelectorAll('[data-param-check]').forEach((btn) => {
        btn.onclick = async () => {
          const model = btn.dataset.paramCheck;
          const card = root.querySelector('[data-model-card="' + model + '"]');
          const params = {};
          card.querySelectorAll('[data-param]').forEach((el) => {
            params[el.dataset.param] = el.type === 'checkbox' ? el.checked : el.value;
          });
          const out = card.querySelector('[data-param-out]');
          btn.disabled = true;
          try {
            const r = await api.generationParams({
              model,
              params,
              has_references: !!(card.querySelector('[data-ref]') || {}).checked
            });
            out.style.display = 'block';
            out.textContent = JSON.stringify(r.api || r, null, 2);
            toast('参数通过模型约束校验');
          } catch (e) {
            out.style.display = 'block';
            out.textContent = String(e.detail || e.message || e);
            toast('参数校验失败', 'bad');
          } finally {
            btn.disabled = false;
          }
        };
      });

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
