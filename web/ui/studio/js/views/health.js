/* 环境体检：把「缺什么 / 能不能一键修 / 修完到底过没过」摆在一页上。
   数据来自 /api/health/checks（现算，不读缓存）；修复走 /api/health/fix（服务端白名单）。

   为什么不像别的页面那样直接给个「全部修复」大红按钮：
   能安全自动化的只有三类（装 Python 包 / 建 Studio 运行时目录 / 清掉指向空文件的配置），
   其余要么需要 UAC（winget 装 ffmpeg）、要么是外部 GUI 进程（ComfyUI）、
   要么只能人来给（Key）。把这三类混进「一键全修」里，结果就是转两圈然后什么也没变。 */
import { api } from '../api.js';
import { S } from '../store.js';
import { esc, icon, badge, toast, openModal, closeModal } from '../ui.js';

const TONE = { fail: 'bad', warn: 'warn', ok: 'ok' };
const TEXT = { fail: '缺失', warn: '可选未装', ok: '就绪' };

const CMDS = {};        // id -> 命令（只用于显示/复制，执行由后端按 id 现算）

function statusOf(it) {
  return it.ok ? 'ok' : (it.required ? 'fail' : 'warn');
}

function action(it) {
  const fx = it.fix || {};
  if (it.ok) return '<span class="tiny dim">已就绪</span>';
  if (fx.auto) {
    return '<button class="btn primary sm" data-fix="' + esc(it.id) + '">'
      + icon('spark', 12) + ' 一键修复</button>';
  }
  if (fx.kind === 'page' && fx.page) {
    return '<button class="btn quiet sm" data-go="' + esc(fx.page) + '">去填写</button>';
  }
  if (fx.cmd) {
    return '<button class="btn quiet sm" data-copy="' + esc(it.id) + '">'
      + icon('copy', 12) + ' 复制命令</button>';
  }
  return '<span class="tiny dim">—</span>';
}

function row(it) {
  const st = statusOf(it);
  const fx = it.fix || {};
  const note = it.ok ? '' : (fx.note || '');
  return '<tr>'
    + '<td><div class="row gap8"><span>' + esc(it.name) + '</span>'
    + (it.required ? '' : badge('outline', '可选')) + '</div>'
    + '<div class="row-sub mono">' + esc(it.id) + '</div></td>'
    + '<td>' + badge(TONE[st], TEXT[st]) + '</td>'
    + '<td class="small dim" style="max-width:520px">' + esc(it.detail || '')
    + (note ? '<div class="tiny dim" style="margin-top:4px">' + esc(note) + '</div>' : '')
    + (it.ok || !fx.cmd ? '' : '<pre class="log" style="margin-top:6px;max-height:76px">' + esc(fx.cmd) + '</pre>')
    + '</td>'
    + '<td class="right">' + action(it) + '</td></tr>';
}

function groupCard(name, rows) {
  const bad = rows.filter((r) => !r.ok).length;
  return '<section class="card" style="margin-bottom:14px">'
    + '<div class="card-h"><h3>' + esc(name) + '</h3>'
    + '<span class="card-sub">' + (bad ? bad + ' / ' + rows.length + ' 待处理' : rows.length + ' 项全部就绪')
    + '</span></div>'
    + '<div class="card-b tight"><div class="table-wrap"><table class="tb"><thead><tr>'
    + '<th style="width:30%">检查项</th><th style="width:10%">状态</th>'
    + '<th>详情</th><th class="right" style="width:14%">操作</th>'
    + '</tr></thead><tbody>' + rows.map(row).join('') + '</tbody></table></div></div></section>';
}

function histTable(items) {
  if (!items.length) {
    return '<div class="empty"><div class="empty-t">还没有修复记录</div>'
      + '<div class="empty-h">点上面的「一键修复」后，这里会留下「改了什么、复检过没过」。</div></div>';
  }
  return '<div class="table-wrap"><table class="tb"><thead><tr>'
    + '<th style="width:16%">时间</th><th style="width:26%">项目</th><th style="width:12%">动作</th>'
    + '<th style="width:12%">复检</th><th>命令</th></tr></thead><tbody>'
    + items.map((h) => '<tr><td class="mono tiny">' + esc(String(h.at || '').replace('T', ' ')) + '</td>'
      + '<td>' + esc(h.name || h.id || '') + '</td>'
      + '<td class="small dim">' + esc(h.kind || '') + '</td>'
      + '<td>' + badge(h.verified ? 'ok' : 'bad', h.verified ? '已通过' : '未通过') + '</td>'
      + '<td class="mono tiny dim" style="max-width:420px">' + esc(h.cmd || '—') + '</td></tr>').join('')
    + '</tbody></table></div>';
}

function doFix(id, item, ctx) {
  const fx = item.fix || {};
  openModal({
    title: '正在修复：' + item.name,
    icon: 'spark',
    html: '<div class="stack">'
      + '<div class="small dim">将执行（服务端按 id 现算，不接受页面传来的命令）：</div>'
      + '<pre class="log" id="fixCmd" style="max-height:96px">' + esc(fx.cmd || '创建目录 / 清理失效配置') + '</pre>'
      + '<div class="alert info" id="fixHint"><span class="nav-ico">' + icon('clock', 14) + '</span>'
      + '<div>正在执行，最长 5 分钟（下载依赖时取决于网速）。完成后会自动复检这一项，'
      + '不靠「命令退出码 0」就说成功。</div></div>'
      + '<div id="fixOut"></div></div>',
    foot: '<span class="spacer"></span><button class="btn quiet" id="fixClose">关闭</button>',
    mount: () => {
      document.getElementById('fixClose').onclick = closeModal;
      api.healthFix({ id: id, ws: S.ws || '' }).then((r) => {
        const hint = document.getElementById('fixHint');
        if (hint) hint.style.display = 'none';
        const out = document.getElementById('fixOut');
        if (!out) return;
        const lines = (r.lines || []).slice(-14).join('\n');
        out.innerHTML = '<div class="alert ' + (r.ok ? 'ok' : 'bad') + '"><span class="nav-ico">'
          + icon(r.ok ? 'check' : 'alert', 14) + '</span><div>'
          + (r.ok ? '已修好，并且复检通过。' : (r.detail || '修复未完成，看下面的输出。'))
          + (r.verified ? '（耗时 ' + r.elapsed + 's）' : '') + '</div></div>'
          + (lines ? '<pre class="log" style="max-height:220px">' + esc(lines) + '</pre>' : '');
        toast(r.ok ? item.name + ' 已就绪' : item.name + ' 仍未通过', r.ok ? 'ok' : 'bad');
        if (r.ok) ctx.refresh();
      }).catch((e) => {
        const out = document.getElementById('fixOut');
        if (out) {
          out.innerHTML = '<div class="alert bad"><span class="nav-ico">' + icon('alert', 14) + '</span><div>'
            + esc((e && e.detail) || (e && e.message) || String(e)) + '</div></div>';
        }
      });
    }
  });
}

export async function render(ctx) {
  const [d, h] = await Promise.all([
    api.healthChecks(ctx.ws).catch((e) => ({ error: (e && e.detail) || String(e) })),
    api.healthFixes(8).catch(() => ({ items: [] }))
  ]);
  if (d.error) {
    return {
      html: '<div class="page-head"><div><h1 class="page-title">环境体检</h1></div></div>'
        + '<div class="alert bad"><span class="nav-ico">' + icon('alert', 14) + '</span><div>'
        + '体检没跑起来：' + esc(d.error) + '</div></div>',
      mount: () => {}
    };
  }

  const items = d.items || [];
  const c = d.counts || {};
  const groups = [];
  items.forEach((it) => {
    let g = groups.find((x) => x.name === it.group);
    if (!g) { g = { name: it.group, rows: [] }; groups.push(g); }
    g.rows.push(it);
  });

  const overall = d.ok
    ? '<div class="alert ok"><span class="nav-ico">' + icon('check', 14) + '</span><div>'
      + '<b>必需项全部就绪</b>，可以开工。'
      + (c.warn ? '另有 ' + c.warn + ' 项可选未装（不影响主链路）。' : '') + '</div></div>'
    : '<div class="alert bad"><span class="nav-ico">' + icon('alert', 14) + '</span><div>'
      + '<b>' + c.fail + ' 项必需条件未满足</b>'
      + (c.auto_fixable ? '，其中 <b>' + c.auto_fixable + ' 项可以一键修复</b>' : '，需要你手动装')
      + '。修好再往下走 —— 否则会在中途（出片 / 字幕 / 封面）才报错，而且报错信息通常指错方向。</div></div>';

  const html = ''
    + '<div class="page-head"><div><h1 class="page-title">环境体检</h1>'
    + '<div class="page-sub">' + c.total + ' 项检查 · 缺失 ' + c.fail + ' · 可选未装 ' + c.warn
    + ' · 可一键修复 ' + (c.auto_fixable || 0) + ' · 用时 ' + (d.elapsed || 0) + 's</div></div>'
    + '<div class="page-actions">'
    + '<button class="btn quiet" id="btnRecheck">' + icon('refresh', 14) + ' 重新体检</button>'
    + '</div></div>'

    + overall
    + '<div class="alert info" style="margin:12px 0 14px"><span class="nav-ico">' + icon('terminal', 14) + '</span><div>'
    + '引擎解释器：<span class="mono">' + esc((d.interpreters || {}).engine || '—') + '</span><br>'
    + '服务解释器：<span class="mono">' + esc((d.interpreters || {}).server || '—') + '</span>'
    + '<div class="tiny dim" style="margin-top:4px">最常见的坑不是「没装依赖」，而是<b>装给了另一个解释器</b>。'
    + '本页所有安装动作都只作用于上面这个<b>引擎解释器</b>。</div></div></div>'

    + groups.map((g) => groupCard(g.name, g.rows)).join('')

    + '<section class="card" style="margin-top:16px"><div class="card-h"><h3>修复记录</h3>'
    + '<span class="card-sub">每次修复都会留痕（web/var/health-fixes.jsonl）</span></div>'
    + '<div class="card-b tight">' + histTable((h.items || [])) + '</div></section>';

  return {
    html,
    mount: (root) => {
      items.forEach((it) => {
        if (it.fix && it.fix.cmd) CMDS[it.id] = it.fix.cmd;
      });
      const re = root.querySelector('#btnRecheck');
      if (re) re.onclick = () => ctx.refresh();

      root.querySelectorAll('[data-fix]').forEach((b) => {
        b.onclick = () => {
          const it = items.find((x) => x.id === b.dataset.fix);
          if (it) doFix(it.id, it, ctx);
        };
      });
      root.querySelectorAll('[data-go]').forEach((b) => {
        b.onclick = () => { location.hash = b.dataset.go; };
      });
      root.querySelectorAll('[data-copy]').forEach((b) => {
        b.onclick = () => {
          const txt = CMDS[b.dataset.copy] || '';
          const done = () => toast('命令已复制，粘到终端执行');
          if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(txt).then(done).catch(() => toast('复制失败，请手动选中文本', 'bad'));
          } else {
            toast('当前浏览器不支持剪贴板，请手动选中', 'bad');
          }
        };
      });
    }
  };
}
