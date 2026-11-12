/* 调度：13 节点受控推进。
   状态只来自引擎的产物判据，执行只走 Runner 子进程；本页不猜状态、不改判据。 */
import { api } from '../api.js';
import { esc, icon, badge, toast, openModal, closeModal } from '../ui.js';

const STATE_TONE = {
  passed: 'ok', skipped: 'outline', absent: 'warn', stale: 'warn',
  failed: 'bad', blocked: 'bad'
};
const STATE_TEXT = {
  passed: '已通过', skipped: '可选跳过', absent: '未开始', stale: '已过期',
  failed: '判据不过', blocked: '上游阻塞'
};
const NODE_LABEL = {
  'import.pack': '导入制作包', 'asset.render': '资产渲染', 'import.bind': '绑定导入',
  'board.frame': '分镜图', 'import.gate': '入门口禁', 'video.resolve': '出片解析',
  'video.batch': '批量出片', 'video.audit': '出片审计', 'edit.master': '母版拼接',
  'edit.upscale': '高清放大', 'edit.subtitle': '字幕烧录', 'edit.draft': '剪映草稿',
  'edit.release': '发布导出'
};

function nextText(d) {
  if (!d || !d.next) return '全部节点已通过';
  return d.next.id + ' · ' + (NODE_LABEL[d.next.id] || d.next.state);
}

function nodeRow(n, next) {
  const tone = STATE_TONE[n.state] || 'outline';
  const isNext = next && next.id === n.id;
  return '<tr' + (isNext ? ' data-next="1"' : '') + '>'
    + '<td class="mono">' + esc(n.id) + '</td>'
    + '<td>' + esc(NODE_LABEL[n.id] || n.id)
    + '<div class="tiny dim">' + esc(n.stage || '') + '</div></td>'
    + '<td>' + badge(tone, STATE_TEXT[n.state] || n.state) + '</td>'
    + '<td class="small dim">' + esc(n.detail || '') + '</td>'
    + '<td class="tiny dim mono">' + esc(n.output || '') + '</td>'
    + '</tr>';
}

function journalRows(items) {
  return (items || []).slice().reverse().map((e) => {
    const what = e.event === 'node_start' ? ('开始 ' + (e.node || ''))
      : e.event === 'node_end' ? ((e.node || '') + ' · rc=' + (e.rc == null ? '—' : e.rc))
      : e.event === 'run_start' ? ('开始运行' + (e.dry_run ? '（干跑）' : '（真实执行）'))
      : e.event === 'run_end' ? ('结束 · ' + (e.stopped || '') + ' · rc=' + (e.rc == null ? '—' : e.rc))
      : (e.event || '事件');
    return '<div class="row gap8" style="padding:5px 0;border-bottom:1px solid var(--line)">'
      + '<span class="mono tiny dim" style="width:150px">' + esc(e.run_id || '—') + '</span>'
      + '<span class="small flex1">' + esc(what) + '</span>'
      + '<span class="tiny dim">' + esc(e.dry_run ? '干跑' : '') + '</span>'
      + '</div>';
  }).join('');
}

export async function render(ctx) {
  let status = null;
  let episodes = [];
  let error = '';
  try {
    const eps = await api.episodes(ctx.ws).catch(() => ({ items: [] }));
    episodes = eps.items || [];
    const selected = (episodes[0] && episodes[0].ep) || 'ep01';
    status = await api.schedulerStatus(ctx.ws, selected, 50);
  } catch (e) {
    error = String((e && (e.detail || e.message)) || e);
  }
  const firstEp = (episodes[0] && episodes[0].ep) || 'ep01';
  const next = status && status.next;
  const counts = (status && status.counts) || {};
  const html = '<div class="page-head"><div><h1 class="page-title">调度</h1>'
    + '<div class="page-sub">13 节点按磁盘产物判据推进；能自动的自动跑，判据不过就停。</div></div>'
    + '<div class="page-actions"><button class="btn quiet" id="sRefresh">' + icon('refresh', 14)
    + ' 刷新状态</button></div></div>'
    + (error ? '<div class="alert bad"><span class="nav-ico">' + icon('alert', 14)
      + '</span><div>' + esc(error) + '</div></div>' : '')
    + '<section class="card" style="margin-bottom:14px"><div class="card-b">'
    + '<div class="row gap8" style="flex-wrap:wrap;align-items:center">'
    + '<span class="small">集号</span><input class="input mono" id="sEp" value="'
    + esc(firstEp) + '" style="width:110px" list="sEpList">'
    + '<datalist id="sEpList">' + episodes.map((e) => '<option value="' + esc(e.ep) + '"></option>').join('') + '</datalist>'
    + '<span class="small">最多推进</span><input class="input mono" id="sMax" value="6" style="width:70px">'
    + '<span class="small">步</span><span class="spacer"></span>'
    + '<button class="btn ghost" id="sDry">' + icon('play', 14) + ' 干跑下一步</button>'
    + '<button class="btn primary" id="sApply">' + icon('play', 14) + ' 真实执行</button>'
    + '</div></div></section>'
    + (status ? '<div class="row gap8" style="margin-bottom:12px;flex-wrap:wrap">'
      + badge('ok', '已通过 ' + (counts.passed || 0))
      + badge('warn', '缺失/过期 ' + ((counts.absent || 0) + (counts.stale || 0)))
      + badge('bad', '阻塞/失败 ' + ((counts.blocked || 0) + (counts.failed || 0)))
      + badge('outline', '可选跳过 ' + (counts.skipped || 0))
      + '<span class="spacer"></span><span class="small">下一步：<b>' + esc(nextText(status)) + '</b></span>'
      + '</div>'
      + '<section class="card" style="margin-bottom:14px"><div class="card-h"><h3>13 节点</h3>'
      + '<span class="card-sub">' + esc(status.workspace || ctx.ws) + ' · ' + esc(status.ep || '') + '</span></div>'
      + '<div class="card-b tight"><div class="table-wrap"><table class="tb"><thead><tr>'
      + '<th style="width:18%">节点 id</th><th style="width:16%">名称</th><th style="width:12%">状态</th>'
      + '<th>判据说明</th><th style="width:22%">产物</th></tr></thead><tbody>'
      + (status.nodes || []).map((n) => nodeRow(n, next)).join('')
      + '</tbody></table></div></div></section>'
      + '<div class="alert info" style="margin-bottom:14px"><span class="nav-ico">' + icon('alert', 14)
      + '</span><div><b>下一步：</b>' + esc(nextText(status))
      + (next ? '<br>' + esc(next.detail || '') : '')
      + '<br>退出码 2 = 判据不过，是正常门禁结果，不是程序崩溃；调度器会停下，不会跳步。</div></div>'
      : '<div class="alert warn"><span class="nav-ico">' + icon('alert', 14)
        + '</span><div>暂时拿不到节点状态，请先看上方错误。</div></div>')
    + '<section class="card"><div class="card-h"><h3>运行轨迹</h3>'
    + '<span class="card-sub">只追加 journal；重启后从磁盘状态继续</span></div>'
    + '<div class="card-b">' + (journalRows(status && status.journal) || '<div class="tiny dim">还没有调度记录</div>')
    + '</div></section>'
    + '<div class="alert info" style="margin-top:16px"><span class="nav-ico">' + icon('alert', 14)
    + '</span><div>干跑只打印将执行的命令，不写产物。真实执行会写盘；推进到 <span class="mono">board.frame</span> 或 '
    + '<span class="mono">video.batch</span> 时，Runner 还会要求单独确认 GPU / 平台计费风险。</div></div>';

  return {
    html,
    mount: (root) => {
      const ep = () => String((root.querySelector('#sEp') || {}).value || 'ep01').trim();
      const maxSteps = () => Math.max(1, Number((root.querySelector('#sMax') || {}).value) || 1);
      const enqueue = async (apply, yes) => {
        const confirm = apply ? { ack: true, gpu: !!yes } : {};
        try {
          const res = await api.schedulerRun({
            ws: ctx.ws,
            params: { ep: ep(), max_steps: maxSteps(), apply: !!apply, yes: !!yes },
            confirm
          });
          toast('已入队调度作业，去任务中心查看进度', 'ok');
          if (res && res.job) ctx.navigate('tasks');
        } catch (e) {
          toast('入队失败：' + ((e && (e.detail || e.message)) || e), 'bad');
        }
      };
      const refresh = root.querySelector('#sRefresh');
      if (refresh) refresh.onclick = () => ctx.refresh();
      const dry = root.querySelector('#sDry');
      if (dry) dry.onclick = () => enqueue(false, false);
      const apply = root.querySelector('#sApply');
      if (apply) apply.onclick = () => {
        openModal({
          title: '真实执行调度',
          icon: 'alert',
          tone: 'bad',
          html: '<div class="small">将真实执行下一步（最多 ' + esc(String(maxSteps())) + ' 步），可能写盘并覆盖该节点产物。</div>'
            + '<label class="chk" style="margin-top:14px"><input type="checkbox" id="sAck">'
            + '<span>我确认已看过干跑结果，并允许调度器写盘。</span></label>'
            + '<label class="chk" style="margin-top:10px"><input type="checkbox" id="sGpu">'
            + '<span>如果推进到 board.frame / video.batch，允许真实生成（可能占 GPU 或产生平台费用）。</span></label>',
          foot: '<span class="spacer"></span><button class="btn quiet" data-close="modal">取消</button>'
            + '<button class="btn primary" id="sGo" disabled>确认执行</button>',
          mount: () => {
            const ack = root.ownerDocument.getElementById('sAck');
            const gpu = root.ownerDocument.getElementById('sGpu');
            const go = root.ownerDocument.getElementById('sGo');
            const sync = () => { go.disabled = !ack.checked; };
            ack.onchange = sync;
            go.onclick = async () => {
              closeModal();
              await enqueue(true, !!gpu.checked);
            };
          }
        });
      };
    }
  };
}