/* 分镜与拍摄：三栏工作台
     左 = 镜头列表（集号 / 关键词 / 状态筛选，单行一个镜头）
     中 = 画布（产物预览）+ 这一镜的运行元数据 + 续跑入口
     右 = 提示词（**整段**可编辑、可一键复制；结构只做只读概览）

   ★ 提示词为什么不拆成逐段输入框（2026-11-10 用户定）
     真实用法是把整段贴出去试。拆成六个框之后，每次测试都要自己拼回去，
     复制多一步、粘回去还要对段头 —— 结构可见的收益远小于这个成本。
     所以：一个 textarea 装完整原文（含段头），结构用只读 chip 概览 + 引擎 lint 表达。
     校验一点没减：保存前照样跑 H3 规则，结构/标签级错误默认拒写。

   ★ 三栏各自的滚动条互不影响，但外层 .content 仍可滚（高度用 vh 估算 + min-height 兜底）。 */
import { api, mediaUrl } from '../api.js';
import { esc, icon, badge, dot, stateEl, dt, stamp, toast, openModal } from '../ui.js';
import { runAction } from '../action.js';
import { S } from '../store.js';

const FILTERS = [
  { key: 'all', label: '全部' },
  { key: 'done', label: '已完成' },
  { key: 'fail', label: '失败' },
  { key: 'todo', label: '未跑' }
];

let filter = 'all';
let epFilter = '';
let selected = '';
let keyword = '';

function statusOf(s) {
  const st = (s.status || '').toUpperCase();
  if (st === 'SUCCESS' || st === 'SUCCEEDED' || st === 'OK') return 'done';
  if (st) return 'fail';
  return 'todo';
}

/* 状态点：done/fail/todo 三态。doing 这里用不上（summary 只有最终态），
   正在跑的任务在「任务中心」，不在这里假装实时。 */
function dotOf(st) {
  return st === 'done' ? 'done' : st === 'fail' ? 'fail' : 'todo';
}

function kvRow(k, v, mono) {
  return '<span class="sd-kv-k">' + esc(k) + '</span>'
    + '<span class="sd-kv-v' + (mono ? ' mono' : '') + '" title="' + esc(v || '—') + '">'
    + esc(v || '—') + '</span>';
}

/* 复制：clipboard 在非安全上下文（http + 非 localhost）会被拒，
   所以留一条 execCommand 兜底 —— 否则「复制」按钮在局域网访问时是死的。 */
async function copyText(t) {
  try {
    await navigator.clipboard.writeText(t);
    return true;
  } catch (e) {
    try {
      const ta = document.createElement('textarea');
      ta.value = t;
      ta.style.position = 'fixed';
      ta.style.opacity = '0';
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand('copy');
      ta.remove();
      return ok;
    } catch (e2) {
      return false;
    }
  }
}

export async function render(ctx) {
  const data = await api.shots(ctx.ws, epFilter);
  const all = data.items || [];
  const eps = (data.episodes || []).map((e) => e.ep);

  const counted = { all: all.length, done: 0, fail: 0, todo: 0 };
  all.forEach((s) => { counted[statusOf(s)] += 1; });

  const list = all.filter((s) => {
    if (filter !== 'all' && statusOf(s) !== filter) return false;
    if (keyword && s.shot_id.toLowerCase().indexOf(keyword) < 0) return false;
    return true;
  });

  if (!selected || !all.some((s) => s.shot_id === selected)) {
    selected = (list[0] || all[0] || {}).shot_id || '';
  }
  const sel = all.find((s) => s.shot_id === selected) || null;

  /* 上一镜 / 下一镜按**当前筛选后的顺序**走：筛了「失败」就该在失败之间跳，
     而不是跳到被筛掉的镜头上去。 */
  const idx = list.findIndex((s) => s.shot_id === selected);
  const prev = idx > 0 ? list[idx - 1] : null;
  const next = idx >= 0 ? list[idx + 1] : null;
  const navBtn = (dir, target) => '<button class="btn ghost icon sd-navbtn' + (dir < 0 ? ' prev' : '')
    + '" data-navdir="' + dir + '"'
    + (target ? ' title="' + esc(target.shot_id) + '"' : ' disabled')
    + '>' + icon('chevron', 14) + '</button>';

  const rows = list.map((s) => {
    const st = statusOf(s);
    return '<button class="sd-row' + (s.shot_id === selected ? ' on' : '')
      + '" data-shot="' + esc(s.shot_id) + '" title="' + esc(s.shot_id) + '">'
      + dot(dotOf(st))
      + '<span class="sd-row-id mono">' + esc(s.shot_id) + '</span>'
      + (s.rel ? '<span class="sd-row-mark" title="有成片">' + icon('film', 12) + '</span>'
        : st === 'fail' ? '<span class="sd-row-mark bad" title="失败">' + icon('alert', 12) + '</span>' : '')
      + '</button>';
  }).join('') || '<div class="empty" style="padding:24px 12px"><div class="empty-t">没有符合条件的镜头</div>'
    + '<div class="empty-h">换个筛选条件，或先跑一次出片。</div></div>';

  /* ---------- 中栏：画布 ---------- */
  const stage = sel
    ? (sel.rel
      ? '<video class="sd-video" controls preload="metadata" src="' + esc(mediaUrl(ctx.ws, sel.rel)) + '"></video>'
      : '<div class="sd-blank">' + icon('film', 30)
        + '<div class="small">' + (statusOf(sel) === 'fail' ? '这一镜没有产物' : '还没有生成') + '</div>'
        + '<div class="mono tiny dim">' + esc(sel.rel || 'final.mp4 未落盘') + '</div></div>')
    : '<div class="sd-blank">' + icon('board', 30)
      + '<div class="small">左边选一个镜头</div>'
      + '<div class="tiny dim">这里会显示该镜的成片；还没出片就是空画面。</div></div>';

  const meta = sel
    ? '<div class="sd-stage-meta">'
      + kvRow('状态', ({ done: '已完成', fail: '失败', todo: '未跑' })[statusOf(sel)] || statusOf(sel))
      + kvRow('批次', sel.batch || '—', true)
      + kvRow('任务号', sel.task_id || '—', true)
      + kvRow('文件', sel.rel || '—', true)
      + '</div>'
      + (sel.error
        ? '<div class="card-b" style="padding:0 12px 12px"><div class="alert bad" style="margin:0">'
          + '<span class="nav-ico">' + icon('alert', 14) + '</span><div><b>失败原因</b><br>'
          + '<span class="small">' + esc(String(sel.error).slice(0, 400)) + '</span></div></div></div>'
        : '')
    : '';

  /* ---------- 组装 ---------- */
  const html = ''
    + '<div class="page-head"><div>'
    + '<div class="crumb"><b>分镜与拍摄</b><span class="sep">/</span><b>'
    + esc(ctx.project ? (ctx.project.title || ctx.project.path) : ctx.ws) + '</b></div>'
    + '<h1 class="page-title">分镜与出片</h1>'
    + '<div class="page-sub">逐镜状态来自 <span class="mono">07-成片/&lt;批次&gt;/summary.json</span>'
    + '（跨批次按镜头去重）· 最近批次 <span class="mono">' + esc(data.latest_batch || '无') + '</span></div></div>'
    + '<div class="page-actions">'
    + '<button class="btn quiet" id="btnCheckG10">' + icon('check', 14) + ' 集级前置体检（G10）</button>'
    + '<button class="btn quiet" id="btnIngest">' + icon('alert', 14) + ' 入门口禁</button>'
    + '<button class="btn" id="btnPlan">' + icon('coins', 14) + ' 出片计划（免费）</button>'
    + '</div></div>'

    // ★ 2026-11-02：这里原来读 `summary.json` 的 totals.success/failed/pending，
    //   而引擎写的是 `{total, ok, fail}` —— 于是三块 chip 恒为 0，而下面的筛选条是对的
    //   （筛选条用的是逐镜去重后的 counted）。统一用 counted：跨批次去重后才是真实状态。
    + (counted.all
      ? '<div class="row" style="margin-bottom:12px;flex-wrap:wrap">'
        + '<span class="chip">镜头 ' + counted.all + '</span>'
        + '<span class="chip">成功 ' + counted.done + '</span>'
        + '<span class="chip"' + (counted.fail ? ' style="color:var(--danger)"' : '') + '>失败 ' + counted.fail + '</span>'
        + '<span class="chip">未跑 ' + counted.todo + '</span>'
        + '<span class="spacer"></span>'
        + (data.batches && data.batches[0] && data.batches[0].fuse && data.batches[0].fuse.blown
          ? badge('bad', '最近批次已熔断', data.batches[0].fuse.reason) : '')
        + '</div>'
      : '')

    + '<div class="sd-shot3">'

    /* ---- 左：镜头列表 ---- */
    + '<section class="card sd-col sd-col-list">'
    + '<div class="card-h"><h3>镜头</h3>'
    + '<span class="card-sub">' + list.length + '/' + all.length + '</span>'
    + '<span class="spacer"></span>'
    + '<select class="select" id="shotEp" title="按集筛选">'
    + '<option value="">全部集</option>'
    + eps.map((e) => '<option value="' + esc(e) + '"' + (e === epFilter ? ' selected' : '') + '>'
      + esc(e) + '</option>').join('')
    + '</select></div>'
    + '<div class="sd-list-tools">'
    + '<div class="search"><span class="nav-ico">' + icon('search', 14) + '</span>'
    + '<input class="input" id="shotKw" placeholder="搜镜头号" value="' + esc(keyword) + '"></div>'
    + '<div class="sd-filters">'
    + FILTERS.map((f) => '<button class="chip' + (filter === f.key ? ' on' : '') + '" data-filter="' + f.key + '">'
      + f.label + ' ' + counted[f.key] + '</button>').join('')
    + '</div></div>'
    + '<div class="sd-list-scroll">' + rows + '</div>'
    + '<div class="card-foot"><span class="tiny dim">' + (data.updated_at ? dt(data.updated_at) : '无批次')
    + '</span></div>'
    + '</section>'

    /* ---- 中：画布 ---- */
    + '<section class="card sd-col sd-col-stage">'
    + '<div class="card-h"><h3 class="mono">' + esc(selected || '未选择镜头') + '</h3>'
    + (sel ? stateEl(statusOf(sel), ({ done: '已完成', fail: '失败', todo: '未跑' })[statusOf(sel)]) : '')
    + '<span class="spacer"></span>'
    + navBtn(-1, prev) + navBtn(1, next) + '</div>'
    + '<div class="sd-stage">' + stage + '</div>'
    + meta
    + '<div class="card-foot">'
    + (sel && statusOf(sel) === 'fail'
      ? '<button class="btn quiet sm" data-retry="' + esc(sel.shot_id) + '">续跑这一镜</button>'
      : '<span class="tiny dim">' + (sel && sel.rel ? '成片已落盘，可直接预览' : '产物落盘后这里可直接播放') + '</span>')
    + '</div>'
    + '</section>'

    /* ---- 右：提示词 ---- */
    + '<section class="card sd-col sd-col-side">'
    + '<div class="card-h"><h3>提示词</h3>'
    + '<span class="card-sub" id="promptSub">整段编辑 · 可复制</span>'
    + '<span class="spacer"></span>'
    + '<button class="btn ghost icon" id="btnCopyTop" title="复制完整提示词">' + icon('copy', 14) + '</button>'
    + '</div>'
    + '<div class="sd-side-body" id="promptBox">'
    + '<div class="skeleton" style="height:12px;margin-bottom:8px"></div>'
    + '<div class="skeleton" style="height:12px;width:80%"></div></div>'
    + '</section>'

    + '</div>';

  return {
    html,
    mount: (root) => {
      root.querySelectorAll('[data-filter]').forEach((b) => {
        b.onclick = () => { filter = b.dataset.filter; ctx.refresh(); };
      });
      root.querySelectorAll('[data-shot]').forEach((b) => {
        b.onclick = (e) => { e.stopPropagation(); selected = b.dataset.shot; ctx.refresh(); };
      });
      root.querySelectorAll('[data-navdir]').forEach((b) => {
        b.onclick = () => {
          const t = Number(b.dataset.navdir) < 0 ? prev : next;
          if (!t) return;
          selected = t.shot_id;
          ctx.refresh();
        };
      });
      const epSel = root.querySelector('#shotEp');
      if (epSel) epSel.onchange = () => { epFilter = epSel.value; selected = ''; ctx.refresh(); };
      const kw = root.querySelector('#shotKw');
      if (kw) {
        let t = null;
        kw.oninput = () => {
          clearTimeout(t);
          t = setTimeout(() => { keyword = kw.value.trim(); ctx.refresh(); }, 300);
        };
      }
      root.querySelectorAll('[data-retry]').forEach((b) => {
        b.onclick = (e) => {
          e.stopPropagation();
          const s = all.find((x) => x.shot_id === b.dataset.retry);
          if (!s) return;
          openModal({
            title: '续跑这一镜',
            icon: 'alert',
            html: '<div class="cost-line"><span class="k">镜头</span><span class="v mono">' + esc(s.shot_id) + '</span></div>'
              + '<div class="cost-line"><span class="k">批次</span><span class="v mono">' + esc(s.batch || '—') + '</span></div>'
              + '<div class="cost-line"><span class="k">动作</span><span class="v">复用批次续跑，不重提已成功段</span></div>'
              + '<div class="cost-line"><span class="k">费用</span><span class="v">￥0（本机 ComfyUI，只占 GPU 时间）</span></div>'
              + '<label class="chk" style="margin-top:10px"><input type="checkbox" id="rsYes">'
              + '<span>我确认要重新生成这一段（占用本机 GPU，不产生平台费用）</span></label>'
              + '<div class="alert warn" style="margin-top:10px"><span class="nav-ico">' + icon('alert', 14)
              + '</span><div>续跑会在本机重新生成失败的那一段；已成功的段不会重做。'
              + '单镜约占 GPU 数分钟，期间其它出图/出片任务要排队。</div></div>',
            foot: '<span class="spacer"></span><button class="btn quiet" data-close="modal">取消</button>'
              + '<button class="btn primary" id="rsGo" disabled>续跑这一段</button>',
            mount: (m) => {
              const ck = m.querySelector('#rsYes');
              const go = m.querySelector('#rsGo');
              ck.onchange = () => { go.disabled = !ck.checked; };
              go.onclick = () => {
                m.querySelector('#modal').classList.remove('on');
                runAction(ctx, {
                  specId: 'video.resume',
                  title: '续跑 · ' + (s.raw || s.shot_id),
                  // `--only` 要的是磁盘上的原始段名（`shot_001`），不是展示用的 ep01_shot_001
                  params: { resume: s.batch || '', only: s.raw || s.shot_id, yes: true },
                  onDone: () => setTimeout(() => ctx.refresh(), 1500)
                });
              };
            }
          });
        };
      });
      const plan = root.querySelector('#btnPlan');
      if (plan) {
        plan.onclick = () => runAction(ctx, {
          specId: 'video.plan', title: '出片计划（不提交、不花钱）', params: epFilter ? { only: epFilter } : {}
        });
      }
      const g10 = root.querySelector('#btnCheckG10');
      if (g10) {
        // ★ 2026-11-01：原来调 `workflow.check --stage S6` —— 那条命令随 workflow.py 一起删了。
        //   现在用集级前置体检（`episode_preflight.py`），查的是「这一集能不能出片」。
        g10.onclick = () => {
          if (!epFilter) { toast('先在左侧选一个集号，再跑前置体检', 'warn'); return; }
          runAction(ctx, {
            specId: 'episode.preflight', title: '集级前置体检（G10）· ' + epFilter,
            params: { eps: epFilter }
          });
        };
      }
      const ing = root.querySelector('#btnIngest');
      if (ing) {
        ing.onclick = () => {
          if (!epFilter) { toast('先在左侧选一个集号，再跑入门口禁', 'warn'); return; }
          runAction(ctx, { specId: 'ingest.check', title: '入门口禁（' + epFilter + '）', params: { ep: epFilter } });
        };
      }
      const cpTop = root.querySelector('#btnCopyTop');
      if (cpTop) {
        cpTop.onclick = async () => {
          const ta = root.querySelector('#rawPrompt');
          if (!ta) { toast('还没读到提示词', 'warn'); return; }
          const ok = await copyText(ta.value);
          toast(ok ? '已复制完整提示词（' + ta.value.length + ' 字符）' : '复制失败（浏览器限制）', ok ? 'ok' : 'warn');
        };
      }
      if (sel) loadPrompt(root, ctx, sel.shot_id);
    }
  };
}

/* 段名中文对照：**只是显示用**。键来自接口的 `section_order`（引擎的 SECTIONS），
   表里没有的段落会直接显示原键名 —— 不做「猜一个中文名」这种会写错语义的事。 */
const SEC_CN = {
  subject_definitions: '主体定义',
  summary: '任务类型',
  retention_analysis: '保留与迁移',
  detailed_description: '动作与镜头',
  overall_soundscape: '环境声',
  non_diegetic_music: '非画内音乐'
};

/* 校验清单：默认只占一行摘要，点开看详情。
   为什么收起：右栏同时要装提示词编辑区和问题清单，而问题清单动辄三四条长句。
   全展开时编辑区只剩四五行 —— 提示词才是这一栏的主体，不能让它给诊断信息让位。
   摘要是常驻的：阻断条数、首条编码、缺几段都在，不需要点开也知道有问题。
   例外：保存被拦时自动展开（那时用户需要看到全部原因和「仍然保存」的出口）。 */
function lintPanel(res, opts) {
  const o = opts || {};
  const nb = (res.blocking || []).length;
  const nw = (res.warnings || []).length;
  const nh = (res.inline_hints || []).length;
  const nm = res.structured ? (res.missing || []).length : 0;
  if (!nb && !nw && !nh && !nm && !o.extra) return '';

  const parts = [];
  if (nm) parts.push('缺 ' + nm + ' 段');
  if (nb) parts.push(nb + ' 条会阻断出片');
  if (nw) parts.push(nw + ' 条建议');
  if (nh) parts.push(nh + ' 条写法提示');
  const tone = (nb || nm) ? 'bad' : 'warn';

  const body = (o.extra || '')
    + (nm ? '<div class="alert warn" style="margin-top:8px"><span class="nav-ico">' + icon('alert', 14)
      + '</span><div class="tiny">缺段：<span class="mono">' + esc((res.missing || []).join(' / '))
      + '</span></div></div>' : '')
    + lintBlock('结构 / 标签问题（会阻断出片）', res.blocking, 'bad')
    + lintBlock('质量建议', res.warnings, 'warn')
    + (nh
      ? '<div class="alert warn" style="margin-top:8px"><span class="nav-ico">' + icon('alert', 14)
        + '</span><div class="tiny">' + (res.inline_hints || []).map((h) => esc(h[1])).join('<br>') + '</div></div>'
      : '');

  const open = !!o.open;
  return '<button class="sd-lintbar ' + tone + '" id="btnLint" aria-expanded="' + (open ? 'true' : 'false') + '">'
    + icon('alert', 13)
    + '<span class="sd-linttxt">' + esc(parts.join(' · ')) + '</span>'
    + '<span class="sd-lintmore">' + (open ? '收起' : '展开') + '</span></button>'
    + '<div class="sd-lintbody' + (open ? '' : ' hide') + '" id="lintBody">' + body + '</div>';
}

function bindLint(lin) {
  const b = lin.querySelector('#btnLint');
  const body = lin.querySelector('#lintBody');
  if (!b || !body) return;
  b.onclick = () => {
    const open = !body.classList.toggle('hide');
    b.setAttribute('aria-expanded', open ? 'true' : 'false');
    const more = b.querySelector('.sd-lintmore');
    if (more) more.textContent = open ? '收起' : '展开';
  };
}

function lintBlock(title, rows, tone) {
  if (!rows || !rows.length) return '';
  return '<div class="alert ' + tone + '" style="margin-top:8px"><span class="nav-ico">'
    + icon('alert', 14) + '</span><div><b>' + esc(title) + '</b><br>'
    + rows.map((r) => '<span class="mono">' + esc(r[1] || '') + '</span> ' + esc(r[2] || r[1] || ''))
      .join('<br>') + '</div></div>';
}

/* 提示词面板：**整段**编辑。
   六段式与旧格式走同一个界面 —— 显示的就是文件里的完整原文（含段头），
   结构信息只做只读 chip 概览。保存一律走 `text` 通道，落盘内容与眼前一致。 */
async function loadPrompt(root, ctx, shot) {
  const box = root.querySelector('#promptBox');
  const sub = root.querySelector('#promptSub');
  if (!box) return;
  box.innerHTML = '<div class="skeleton" style="height:12px;margin-bottom:8px"></div>'
    + '<div class="skeleton" style="height:60px"></div>';

  let res;
  try {
    res = await api.prompt(ctx.ws, shot, epFilter);
  } catch (e) {
    box.innerHTML = '<div class="alert bad"><span class="nav-ico">' + icon('alert', 14)
      + '</span><div>提示词读取失败：' + esc(e.detail || e.message) + '</div></div>';
    return;
  }

  /* 同一镜号在每一集都有：没选集时必须让人选，不能替他挑第一份 */
  if (res && res.reason === 'ambiguous') {
    const cands = (res.candidates || []).slice(0, 12);
    box.innerHTML = '<div class="alert warn"><span class="nav-ico">' + icon('alert', 14) + '</span>'
      + '<div><b>' + esc(res.shot) + '</b> 在 ' + (res.candidates || []).length + ' 集里都存在。'
      + '先在左侧选一个集号，再读提示词 —— 猜一份会把别的集的词改掉。</div>'
      + '<div class="row" style="margin-top:8px;flex-wrap:wrap">'
      + cands.map((e) => '<button class="chip" data-pick-ep="' + esc(e) + '">' + esc(e) + '</button>').join('')
      + '</div></div>';
    box.querySelectorAll('[data-pick-ep]').forEach((b) => {
      b.onclick = () => {
        epFilter = b.dataset.pickEp;
        const sel = root.querySelector('#shotEp');
        if (sel) sel.value = epFilter;
        loadPrompt(root, ctx, shot);
      };
    });
    return;
  }

  if (!res || !res.ok) {
    const why = res && res.reason === 'no_prompts'
      ? '这个工作区没有找到 <ep>/h3_prompts.json（提示词还没生成）。'
      : (res && res.reason === 'no_such_ep' ? '没有这一集：' + esc((res.candidates || []).join(' / '))
        : '这一镜没有提示词记录（' + esc((res && (res.reason || 'unknown')) || 'unknown') + '）。');
    box.innerHTML = '<div class="alert info"><span class="nav-ico">' + icon('alert', 14)
      + '</span><div>' + why + '</div></div>';
    return;
  }

  /* 显示 `normalized`：保存写回的也是它（引擎在 save 时会再归一一次）。
     显示原文、保存归一后的内容 — 那才是「看到 A 存成 B」，这里直接显示 B。 */
  const full = res.normalized || res.prompt || '';
  const normChanged = String(res.prompt || '') !== full;
  const order = (res.section_order && res.section_order.length) ? res.section_order : Object.keys(res.sections || {});
  const secs = res.sections || {};

  if (sub) sub.textContent = res.structured ? '六段式 · 整段可复制' : '旧格式 · 整段可复制';

  const badges = [];
  if (res.duration) badges.push(badge('muted', res.duration + ' 秒'));
  if (res.ratio) badges.push(badge('muted', res.ratio));
  if (res.voice) badges.push(badge('muted', '音轨 ' + res.voice));
  if (res.ep) badges.push(badge('outline', res.ep));
  badges.push(badge('outline', full.length + ' 字符'));

  /* 结构概览：只读。缺段的标红 —— 这是「拆开」唯一真正有价值的信息，
     用一行 chip 就能给，不必把编辑区切成六块。 */
  const secChips = order.map((k) => {
    const n = String(secs[k] || '').trim().length;
    return '<span class="sd-pchip' + (n ? '' : ' bad') + '" title="' + esc(SEC_CN[k] || k) + '">'
      + esc(k) + '<b>' + (n ? n : '缺') + '</b></span>';
  }).join('');

  box.innerHTML = '<div class="sd-p-meta">' + badges.join('')
    + '<span class="spacer"></span>'
    + '<span class="tiny dim mono" title="' + esc(res.rel || '') + '">' + esc(res.rel || '') + '</span></div>'

    + '<div class="sd-p-secs">' + (res.structured ? secChips : '<span class="tiny dim">非六段式，无结构概览</span>')
    + '</div>'

    + (normChanged
      ? '<div class="alert info" style="margin:0"><span class="nav-ico">' + icon('alert', 14) + '</span>'
        + '<div class="tiny">已按 H3 规则机械归一：<span class="mono">{{Picture n}}</span> → '
        + '<span class="mono">&lt;Picture n&gt;</span>、删掉「上传顺序：」脚手架行、压缩连续空行。'
        + '下面显示的就是将保存的内容。</div></div>'
      : '')

    + '<textarea id="rawPrompt" class="sd-p-text" spellcheck="false">' + esc(full) + '</textarea>'
    + '<div class="sd-p-lint" id="promptLin"></div>'
    + '<div class="sd-p-foot">'
    + '<button class="btn primary sm" id="btnSavePrompt"' + (S.readonly ? ' disabled' : '') + '>保存</button>'
    + '<button class="btn quiet sm" id="btnCopyPrompt">' + icon('copy', 12) + ' 复制全文</button>'
    + '<span class="spacer"></span><span class="tiny dim" id="promptState">'
    + (S.readonly ? '只读模式' : '未修改') + '</span></div>';

  const ta = box.querySelector('#rawPrompt');
  const lin = box.querySelector('#promptLin');
  const state = box.querySelector('#promptState');
  const btn = box.querySelector('#btnSavePrompt');
  let dirty = false;

  /* 初次就把已有问题摆出来（不等到点保存才说）；默认只占一行摘要 */
  lin.innerHTML = lintPanel(res);
  bindLint(lin);

  ta.oninput = () => {
    dirty = true;
    if (state) state.textContent = '已修改（未保存）';
    if (btn) btn.disabled = false;
    const m = box.querySelector('.sd-p-meta .badge:last-child');
    if (m) m.textContent = ta.value.length + ' 字符';
  };

  const cp = box.querySelector('#btnCopyPrompt');
  if (cp) cp.onclick = async () => {
    const ok = await copyText(ta.value);
    toast(ok ? '已复制（' + ta.value.length + ' 字符）' : '复制失败（浏览器限制）', ok ? 'ok' : 'warn');
  };

  if (btn) btn.onclick = async () => {
    if (!dirty) { toast('没有改动', 'warn'); return; }
    btn.disabled = true;
    const old = btn.textContent;
    btn.innerHTML = '<span class="spinner"></span> 保存中';
    const payload = { ws: ctx.ws, shot: res.shot || shot, ep: res.ep || epFilter || '', text: ta.value };

    const done = (r) => {
      if (r && r.ok) {
        dirty = false;
        /* `changed:false` = 归一后与磁盘一致，引擎直接返回、没写盘也没备份。
           这时候说「已保存」是骗人的：文件根本没被动过。 */
        const noop = r.changed === false;
        if (state) {
          state.textContent = noop ? '未变更（归一后与磁盘一致）'
            : '已保存' + (r.backup ? ' · 备份 ' + String(r.backup).split(/[\\/]/).pop() : '');
        }
        btn.textContent = noop ? '未变更' : '已保存';
        btn.disabled = true;
        toast(noop ? '内容没有实际变更，未写盘' : '已写入 ' + (r.rel || '') + (r.summary ? ' · ' + r.summary : ''));
        if (!noop && ctx.refresh) setTimeout(() => ctx.refresh(), 900);
        return;
      }
      btn.textContent = old;
      btn.disabled = false;
      if (r && r.reason === 'blocked_by_lint') {
        /* 被拦时自动展开：这一刻用户需要看到全部原因，也需要那个「仍然保存」的出口 */
        lin.innerHTML = lintPanel(
          { blocking: r.blocking || [], structured: res.structured, missing: res.missing },
          {
            open: true,
            extra: '<div class="row" style="margin-top:8px;flex-wrap:wrap"><button class="btn quiet sm" id="btnForce">'
              + '我知道，仍然保存</button><span class="tiny dim">存进去的提示词会在出片时喂错参考图</span></div>'
          }
        );
        bindLint(lin);
        const f = lin.querySelector('#btnForce');
        if (f) f.onclick = async () => {
          f.disabled = true;
          try { done(await api.savePrompt(Object.assign({}, payload, { force: true }))); }
          catch (e) { toast('强制保存失败：' + (e.detail || e.message), 'bad'); f.disabled = false; }
        };
        return;
      }
      toast('保存失败：' + ((r && (r.reason || r.text_tail)) || '未知'), 'bad');
      lin.innerHTML = lintBlock('保存失败', [[0, r && r.reason, r && r.text_tail]], 'bad');
    };

    try { done(await api.savePrompt(payload)); }
    catch (e) {
      btn.textContent = old;
      btn.disabled = false;
      const code = e && e.status;
      toast(code === 423 ? '只读模式：写操作被拒绝' : '保存失败：' + (e.detail || e.message), 'bad');
    }
  };
}
