/* 创意工作室 —— 三栏创作工作台
     左 = 文档树（灵感 / 企划案 / 资产库 / 分集剧本 / 导演手册 × N 集）
     中 = 编辑器（Markdown 原文 ⇄ 只读预览）
     右 = 上下文（下一步 / 生成参数 / 制作包 / 模板与画风）

   ★ 数据契约（不许改）
     创作产物只有四类，全部落 `00-创作/`：
       01-企划案.md / 02-资产库.md / 03-分集剧本.md / 04-导演手册/第NN集.md
     灵感不在这四类里 —— 它是 `brief.json`（一句话 + 市场 + 集数），
     是整条链的起点，也是唯一需要人「说一句话」的地方。
     这份清单来自 `web/core/creation.py::STAGES`，前端不另立文档类型。

   ★ 为什么不做成「阶段卡片 + 弹窗编辑」
     原来的形态是四张卡片，点「查看/修改」弹一个模态框。问题有两个：
     一是长篇文本在模态框里改，视野只有半屏；二是导演手册 30 集在弹窗里被拼成
     一整篇（`read()` 用 `---` 拼接），改第 7 集会误改第 8 集。
     三栏 + 单文件编辑解决的就是这两件事。

   ★ 为什么预览要自己写渲染
     项目没有 Markdown 依赖（不引外部 CDN 是纪律）。但企划案的立项卡是表格、
     导演手册靠 `##` 分节，纯文本看不清结构。所以写一个**受限子集**渲染：
     标题 / 表格 / 列表 / 引用 / 分隔线 / 粗体 / 行内码 / 代码块。
     先整段 esc 再处理标记 —— 不支持的内联 HTML 一律原样显示，不会被执行。
     它不是「另一套格式」：编辑区永远是 Markdown 原文，预览只是显示层。 */
import { api } from '../api.js';
import { runAction } from '../action.js';
import { esc, icon, badge, dot, toast, openModal, closeModal } from '../ui.js';
import { S } from '../store.js';

/* 每个产物用哪个用途生成、缺什么就不能点。
   这是**界面门禁**（不是引擎判据）：缺企划案就去生成资产库，模型只会瞎编。 */
const GEN = {
  plan: { purpose: 'create.plan', needs: ['skill'] },
  assets: { purpose: 'create.assets', needs: ['skill', 'plan'] },
  script: { purpose: 'create.script', needs: ['skill', 'plan'] },
  director: { purpose: 'create.director', needs: ['skill', 'assets'] }
};

/* 模板分批的产物：必须支持追加，否则每次生成只留最后一批。 */
const BATCHED = { assets: true, script: true, director: true };

const DIRECTOR = 'director';

let selDoc = '';        // 'idea' | 'plan' | 'assets' | 'script' | 'director/第01集.md'
let viewMode = 'view';  // 'edit' | 'view' —— 默认预览：进来先看稿，改的时候再切
let dirty = false;

/* ---------- 受限 Markdown 渲染 ---------- */
function inlineMd(s) {
  return esc(s)
    .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
    .replace(/`([^`]+)`/g, '<code>$1</code>');
}

function mdToHtml(src) {
  const lines = String(src || '').replace(/\r\n?/g, '\n').split('\n');
  const out = [];
  let list = '';
  let i = 0;
  const closeList = () => { if (list) { out.push('</' + list + '>'); list = ''; } };

  while (i < lines.length) {
    const ln = lines[i];

    /* 代码块：围栏之间原样保留（不解析里面的标记），创作稿里常见镜头表 */
    if (/^\s*```/.test(ln)) {
      closeList();
      i += 1;
      const buf = [];
      while (i < lines.length && !/^\s*```/.test(lines[i])) { buf.push(lines[i]); i += 1; }
      i += 1;
      out.push('<pre class="sd-md-code">' + esc(buf.join('\n')) + '</pre>');
      continue;
    }

    /* 表格：当前行是 | 开头，且下一行是 |---|---| 分隔行 */
    if (/^\s*\|/.test(ln) && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1] || '')) {
      closeList();
      const cells = (row) => row.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
      const head = cells(ln);
      i += 2;
      const rows = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) { rows.push(cells(lines[i])); i += 1; }
      out.push('<div class="sd-md-tw"><table><thead><tr>'
        + head.map((h) => '<th>' + inlineMd(h) + '</th>').join('')
        + '</tr></thead><tbody>'
        + rows.map((r) => '<tr>' + r.map((c) => '<td>' + inlineMd(c) + '</td>').join('') + '</tr>').join('')
        + '</tbody></table></div>');
      continue;
    }

    const h = /^(#{1,4})\s+(.*)$/.exec(ln);
    if (h) {
      closeList();
      const lv = h[1].length;
      out.push('<h' + lv + '>' + inlineMd(h[2]) + '</h' + lv + '>');
      i += 1;
      continue;
    }

    if (/^\s*([-*_])\1{2,}\s*$/.test(ln)) { closeList(); out.push('<hr>'); i += 1; continue; }

    const q = /^>\s?(.*)$/.exec(ln);
    if (q) {
      closeList();
      const buf = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) { buf.push(lines[i].replace(/^>\s?/, '')); i += 1; }
      out.push('<blockquote>' + inlineMd(buf.join(' ')) + '</blockquote>');
      continue;
    }

    const ul = /^\s*[-*+]\s+(.*)$/.exec(ln);
    const ol = /^\s*\d+[.)]\s+(.*)$/.exec(ln);
    if (ul || ol) {
      const want = ul ? 'ul' : 'ol';
      if (list !== want) { closeList(); out.push('<' + want + '>'); list = want; }
      out.push('<li>' + inlineMd((ul || ol)[1]) + '</li>');
      i += 1;
      continue;
    }

    if (!ln.trim()) { closeList(); i += 1; continue; }

    /* 段落：连续行合并，行内换行保留成 <br>（中文稿常靠硬换行断句） */
    closeList();
    const buf = [];
    while (i < lines.length && lines[i].trim()
      && !/^(#{1,4})\s/.test(lines[i]) && !/^\s*\|/.test(lines[i])
      && !/^\s*[-*+]\s/.test(lines[i]) && !/^\s*\d+[.)]\s/.test(lines[i])
      && !/^>/.test(lines[i]) && !/^\s*```/.test(lines[i])) {
      buf.push(lines[i]);
      i += 1;
    }
    out.push('<p>' + buf.map((x) => inlineMd(x)).join('<br>') + '</p>');
  }
  closeList();
  return out.join('\n');
}

/* ---------- 行级 diff ----------
   先裁掉公共前后缀，中间再做 LCS：改一个字通常只涉及一两行，裁完规模从「全文²」降到「改动²」。
   不做字符级 diff —— 创作稿的改动多是整句改写，行级已经够用，字符级会让人盯着一堆碎高亮。 */
function lcsOps(a, b) {
  const n = a.length;
  const m = b.length;
  if (!n) return b.map((t) => ({ t: 'add', text: t }));
  if (!m) return a.map((t) => ({ t: 'del', text: t }));
  /* 4M 单元 = 8MB(Uint16)。超过就退化成整体替换并提示 ——
     宁可说清「差异过大，只标整段」也不要卡住浏览器。 */
  if (n * m > 4e6) {
    return a.map((t) => ({ t: 'del', text: t })).concat(b.map((t) => ({ t: 'add', text: t })));
  }
  const w = m + 1;
  const dp = new Uint16Array((n + 1) * w);
  for (let i = n - 1; i >= 0; i -= 1) {
    const row = i * w;
    const next = (i + 1) * w;
    for (let j = m - 1; j >= 0; j -= 1) {
      dp[row + j] = a[i] === b[j]
        ? dp[next + j + 1] + 1
        : Math.max(dp[next + j], dp[row + j + 1]);
    }
  }
  const out = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) { out.push({ t: 'eq', text: a[i] }); i += 1; j += 1; }
    else if (dp[(i + 1) * w + j] >= dp[i * w + j + 1]) { out.push({ t: 'del', text: a[i] }); i += 1; }
    else { out.push({ t: 'add', text: b[j] }); j += 1; }
  }
  while (i < n) { out.push({ t: 'del', text: a[i] }); i += 1; }
  while (j < m) { out.push({ t: 'add', text: b[j] }); j += 1; }
  return out;
}

/* → [{t:'eq'|'del'|'add', a:行号|null, b:行号|null, text}] */
function diffRows(aText, bText) {
  const A = String(aText || '').split('\n');
  const B = String(bText || '').split('\n');
  let p = 0;
  while (p < A.length && p < B.length && A[p] === B[p]) p += 1;
  let sfx = 0;
  while (sfx < A.length - p && sfx < B.length - p
    && A[A.length - 1 - sfx] === B[B.length - 1 - sfx]) sfx += 1;

  const out = [];
  for (let i = 0; i < p; i += 1) out.push({ t: 'eq', a: i + 1, b: i + 1, text: A[i] });

  let ai = p;
  let bi = p;
  lcsOps(A.slice(p, A.length - sfx), B.slice(p, B.length - sfx)).forEach((op) => {
    if (op.t === 'eq') { out.push({ t: 'eq', a: ai + 1, b: bi + 1, text: op.text }); ai += 1; bi += 1; }
    else if (op.t === 'del') { out.push({ t: 'del', a: ai + 1, b: null, text: op.text }); ai += 1; }
    else { out.push({ t: 'add', a: null, b: bi + 1, text: op.text }); bi += 1; }
  });
  for (let i = 0; i < sfx; i += 1) {
    out.push({ t: 'eq', a: A.length - sfx + i + 1, b: B.length - sfx + i + 1, text: A[A.length - sfx + i] });
  }
  return out;
}

function vdColumns(rows) {
  const L = [];
  const R = [];
  rows.forEach((r) => {
    if (r.t === 'eq') {
      L.push({ cls: '', ln: r.a, tx: r.text });
      R.push({ cls: '', ln: r.b, tx: r.text });
    } else if (r.t === 'del') {
      L.push({ cls: 'del', ln: r.a, tx: r.text });
      R.push({ cls: 'gap', ln: '', tx: '' });
    } else {
      L.push({ cls: 'gap', ln: '', tx: '' });
      R.push({ cls: 'add', ln: r.b, tx: r.text });
    }
  });
  const col = (arr) => arr.map((x) => '<div class="sd-vd-line ' + x.cls + '">'
    + '<span class="sd-vd-ln">' + (x.ln || '') + '</span>'
    + '<span class="sd-vd-tx">' + esc(x.tx) + '</span></div>').join('');
  return { left: col(L), right: col(R) };
}

/* ---------- 文档模型 ---------- */
function docsOf(st) {
  const out = [{
    key: 'idea', label: '灵感', kind: 'idea',
    state: st.idea.state, chars: (st.idea.idea || '').length
  }];
  (st.stages || []).forEach((s) => {
    out.push({ key: s.id, label: s.label, kind: s.id, state: s.state,
      chars: s.chars || 0, batch: s.batch, batchTotal: s.batch_total,
      files: s.files || [], desc: s.desc,
      /* ★ 有文件的导演手册是**容器**，不是一篇文档。
         允许点它去编辑，等于把 30 集拼接文本（实测 598K 字符）塞进一个 textarea；
         而保存时 `write()` 拿不到 name 就会回落到「第01集.md」，把前 598K 覆盖成第 1 集。
         所以只在它还没有文件时才允许选中（那时是空态 + 生成入口）。 */
      container: s.id === DIRECTOR && (s.files || []).length > 0 });
    if (s.id === DIRECTOR) {
      (s.files || []).forEach((f) => {
        out.push({ key: DIRECTOR + '/' + f.name, label: f.name.replace(/\.md$/, ''),
          kind: 'file', parent: DIRECTOR, name: f.name, state: 'done',
          chars: f.chars || 0, batch: f.batch, batchTotal: f.batch_total });
      });
    }
  });
  return out;
}

/* 当前文档放在 URL 上（`?doc=director/第05集.md`）：
   否则改完第 5 集一刷新就跳回第 1 集，人得重新找一遍。与驾驶舱的 `?ep=` 同一套做法。 */
function docParam() {
  try { return (new URLSearchParams(location.search).get('doc') || '').trim(); } catch (e) { return ''; }
}

function pickDefault(docs, st) {
  const fromUrl = docParam();
  if (fromUrl && docs.some((d) => d.key === fromUrl && !d.container)) return fromUrl;
  if (selDoc && docs.some((d) => d.key === selDoc && !d.container)) return selDoc;
  const empty = (st.stages || []).find((s) => s.state !== 'done');
  if (empty) return empty.id;
  const f = docs.find((d) => d.kind === 'file');
  return f ? f.key : 'plan';
}

/* ---------- 树 ---------- */
function treeHtml(docs, sel) {
  const row = (d, isChild) => {
    const on = d.key === sel;
    const tone = d.state === 'done' ? 'done' : d.state === 'draft' ? 'doing' : 'todo';
    return '<button class="sd-docitem' + (on ? ' on' : '') + (isChild ? ' child' : '')
      + '" data-doc="' + esc(d.key) + '" title="' + esc(d.desc || d.label) + '">'
      + (isChild ? '' : dot(tone))
      + '<span class="sd-docname">' + esc(d.label) + '</span>'
      + '<span class="sd-docmeta mono">' + (d.chars ? fmtChars(d.chars) : '空') + '</span></button>';
  };
  /* 导演手册是唯一的「多文件」产物：它的每一集作为子项紧跟在主项后面。
     按顺序拼而不是事后正则插入 —— 后者一旦结构调整（比如多一个多文件产物）就静默插错位置。 */
  const files = docs.filter((d) => d.kind === 'file');
  return docs.filter((d) => d.kind !== 'file').map((d) => {
    if (!d.container) return row(d, false);
    /* 容器头不是按钮：它没有「一篇完整文档」可编辑，只有每一集。
       给个不可点的标题 + 集数，比给个点了会出错的东西强。 */
    return '<div class="sd-docgroup-h">' + dot('done')
      + '<span class="sd-docname">' + esc(d.label) + '</span>'
      + '<span class="sd-docmeta mono">' + files.length + ' 集</span></div>'
      + '<div class="sd-docgroup">' + files.map((f) => row(f, true)).join('') + '</div>';
  }).join('');
}

function fmtChars(n) {
  const v = Number(n) || 0;
  return v >= 1000 ? (v / 1000).toFixed(1).replace(/\.0$/, '') + 'k 字' : v + ' 字';
}

/* ---------- 生成参数 ---------- */
function epFromFile(name) {
  const m = /第\s*(\d+)\s*集/.exec(name || '');
  return m ? '第' + m[1] + '集' : '第01集';
}

function paramRows(stage, docs, sel) {
  if (stage === 'script') {
    return '<label class="sd-fld"><span>写哪几集</span>'
      + '<input class="input mono" id="gpEpRange" value="1-3" placeholder="1-3"></label>';
  }
  if (stage === 'director') {
    const cur = docs.find((d) => d.key === sel && d.kind === 'file');
    const ep = epFromFile(cur ? cur.name : '');
    return '<label class="sd-fld"><span>拆哪一集</span>'
      + '<input class="input mono" id="gpEp" value="' + esc(ep) + '" placeholder="第01集"></label>'
      + '<label class="sd-fld"><span>每批镜数</span>'
      + '<input class="input mono" id="gpShots" value="5" inputmode="numeric"></label>'
      + '<div class="sd-note">同一集的下一批请用「继续写」—— 覆盖会只剩最后一批。</div>';
  }
  return '';
}

/* ---------- 编辑器 ---------- */
/* 页头只放「这是哪份文档」：标题 + 两条关键徽标。
   按钮全部下沉到工具条 —— 1240px 下中栏只有 ~400px，页头里塞四个控件会换行成两排，
   第二排的「保存」会跑到最左边，看起来像另一个东西。 */
function edHead(doc) {
  const meta = [];
  if (doc.chars) meta.push(fmtChars(doc.chars));
  if (doc.batch) meta.push('第 ' + doc.batch + (doc.batchTotal ? '/' + doc.batchTotal : '') + ' 批');
  if (doc.state === 'done') meta.push('已落盘');
  if (S.readonly) meta.push('只读模式');
  return '<div class="card-h sd-edhead">'
    + '<h3>' + esc(doc.label) + '</h3>'
    + meta.map((m) => badge('muted', m)).join('')
    + '</div>';
}

/* 把文档正文塞进编辑器。`text` 为空时给一份「这里该写什么」的空态，
   而不是一个巨大的空白文本框 —— 空白框会让人以为坏了。 */
function renderDoc(root, doc, text, extra) {
  const ed = root.querySelector('#edBox');
  if (!ed) return;
  const empty = !String(text || '').trim();
  ed.innerHTML = '<div class="sd-edtools">'
    + '<span class="sd-edpath mono">' + esc((extra && extra.path) || '') + '</span>'
    + '<span class="tiny dim sd-edstat" id="edStat"></span>'
    + '<div class="sd-seg" role="group" aria-label="视图">'
    + '<button class="sd-segbtn' + (viewMode === 'edit' ? ' on' : '') + '" data-mode="edit">编辑</button>'
    + '<button class="sd-segbtn' + (viewMode === 'view' ? ' on' : '') + '" data-mode="view">预览</button>'
    + '</div>'
    + '<button class="btn quiet sm" id="edCopy" title="复制 Markdown 原文">' + icon('copy', 12) + '</button>'
    /* 灵感存在 brief.json，`save_idea` 不写备份 —— 那里没有版本可看，所以不给按钮 */
    + (doc.kind === 'idea'
      ? ''
      : '<button class="btn quiet sm" id="edVers" title="历史版本与对比">' + icon('clock', 12) + '</button>')
    + '<button class="btn primary sm" id="edSave"' + (S.readonly ? ' disabled' : '') + '>保存</button>'
    + '</div>'
    /* 灵感的「集数 / 单集秒数」属于 brief.json，不是正文的一部分；
       原来的卡片有这两个输入，改成三栏后不能把它们丢了 —— 少了就没法改集数。 */
    + ((extra && extra.formHtml) || '')
    + (empty
      ? '<div class="sd-edempty"><div class="small">这份还没有内容</div>'
        + '<div class="tiny dim">' + esc(doc.desc || '在右侧点「生成」，或直接在这里写。')
        + '</div></div>'
      : '')
    + '<textarea id="edText" class="sd-edtext' + (viewMode === 'view' ? ' hide' : '')
    + '" spellcheck="false">' + esc(text || '') + '</textarea>'
    + '<div id="edView" class="sd-md' + (viewMode === 'view' ? '' : ' hide') + '">'
    + mdToHtml(text || '') + '</div>';

  const ta = ed.querySelector('#edText');
  const view = ed.querySelector('#edView');
  const stat = ed.querySelector('#edStat');
  const save = root.querySelector('#edSave');
  dirty = false;
  if (save) { save.disabled = true; save.textContent = '保存'; }   // 无改动时不可点

  const refreshStat = () => {
    const v = ta ? ta.value : '';
    if (stat) stat.textContent = v.length + ' 字符 · ' + (v.split('\n').length) + ' 行';
  };
  refreshStat();

  const mark = () => {
    dirty = true;
    if (save && !S.readonly) { save.disabled = false; save.textContent = '保存'; }
    refreshStat();
  };

  if (ta) {
    ta.oninput = () => {
      mark();
      /* 预览不实时跟着打字刷新（长文渲染会拖慢输入），切到预览时再渲染 */
      if (view && !view.classList.contains('hide')) view.innerHTML = mdToHtml(ta.value);
    };
  }
  if (view) view.innerHTML = mdToHtml(text || '');
}

/* 编辑器内的控件必须**渲染之后再绑定**。
   ★ 这里踩过一个坑（2026-11-03 同类问题在这页重演）：
     工具条（保存 / 复制 / 版本 / 编辑预览切换）是 `renderDoc()` 用 innerHTML 生成的，
     而 `renderDoc` 在 `loadDoc()` 里异步执行 —— 比 `mount()` 晚。
     如果在 mount 里 `querySelector('#edSave')`，拿到的是 null，按钮**永远没有处理函数**：
     页面看起来完全正常，点下去毫无反应，控制台也没有报错。 */
function bindEditor(root, ctx, doc, st) {
  const ta = root.querySelector('#edText');
  const vw = root.querySelector('#edView');
  const saveBtn = root.querySelector('#edSave');

  root.querySelectorAll('[data-mode]').forEach((b) => {
    b.onclick = () => {
      viewMode = b.dataset.mode;
      root.querySelectorAll('[data-mode]').forEach((x) => {
        x.classList.toggle('on', x.dataset.mode === viewMode);
      });
      if (ta) ta.classList.toggle('hide', viewMode === 'view');
      if (vw) {
        vw.classList.toggle('hide', viewMode !== 'view');
        if (viewMode === 'view' && ta) vw.innerHTML = mdToHtml(ta.value);
      }
    };
  });

  if (saveBtn) {
    saveBtn.onclick = async () => {
      if (!ta) return;
      const text = ta.value;
      if (!text.trim()) { toast('内容为空，不保存（空文件会让状态显示已完成）', 'bad'); return; }
      const old = saveBtn.textContent;
      saveBtn.disabled = true;
      saveBtn.innerHTML = '<span class="spinner"></span> 保存中';
      try {
        const body = { ws: ctx.ws, text };
        if (doc.kind === 'idea') {
          const epsEl = root.querySelector('#ciEps');
          const secEl = root.querySelector('#ciSec');
          body.idea = text;
          body.ep_total = Number((epsEl && epsEl.value) || st.idea.ep_total) || 0;
          body.ep_seconds = Number((secEl && secEl.value) || st.idea.ep_seconds) || 0;
          await api.createIdea(body);
          toast('灵感已保存', 'ok');
        } else if (doc.kind === 'file') {
          body.stage = DIRECTOR;
          body.name = doc.name;
          const r = await api.createWrite(body);
          toast(r.detail || '已保存', 'ok');
        } else {
          body.stage = doc.kind;
          const r = await api.createWrite(body);
          toast(r.detail || '已保存', 'ok');
        }
        dirty = false;
        saveBtn.textContent = '已保存';
        saveBtn.disabled = true;
        setTimeout(() => ctx.refresh(), 500);
      } catch (e) {
        saveBtn.disabled = false;
        saveBtn.textContent = old;
        const code = e && e.status;
        toast(code === 423 ? '只读模式：写操作被拒绝'
          : '保存失败：' + (e.detail || e.message), 'bad');
      }
    };
  }

  const cp = root.querySelector('#edCopy');
  if (cp) cp.onclick = async () => {
    if (!ta) { toast('还没读到内容', 'warn'); return; }
    try {
      await navigator.clipboard.writeText(ta.value);
      toast('已复制 Markdown 原文');
    } catch (e) { toast('复制失败（浏览器限制）', 'warn'); }
  };

  const vBtn = root.querySelector('#edVers');
  if (vBtn) vBtn.onclick = () => openVersions(ctx, doc);
}

async function loadDoc(root, ctx, st, key) {
  const docs = docsOf(st);
  const doc = docs.find((d) => d.key === key) || docs[0];
  const ed = root.querySelector('#edBox');
  if (ed) {
    ed.innerHTML = '<div class="skeleton" style="height:14px;width:40%;margin-bottom:10px"></div>'
      + '<div class="skeleton" style="height:60%"></div>';
  }

  if (doc.container) {
    const first = docs.find((d) => d.kind === 'file');
    if (first) { selDoc = first.key; return loadDoc(root, ctx, st, first.key); }
  }
  if (doc.kind === 'idea') {
    const form = '<div class="sd-edtools sd-ideafields">'
      + '<label class="sd-fld"><span>集数</span>'
      + '<input class="input mono" id="ciEps" value="' + (st.idea.ep_total || 30)
      + '" inputmode="numeric"></label>'
      + '<label class="sd-fld"><span>单集秒数</span>'
      + '<input class="input mono" id="ciSec" value="' + (st.idea.ep_seconds || 60)
      + '" inputmode="numeric"></label>'
      + '<span class="tiny dim">生成企划案时按这两个数写「集数与时长」</span></div>';
    renderDoc(root, doc, st.idea.idea || '', { path: 'brief.json', formHtml: form });
    bindEditor(root, ctx, doc, st);
    return;
  }
  let text = '';
  let pathText = '';
  try {
    const d = await api.createRead(ctx.ws, doc.kind === 'file' ? DIRECTOR : doc.kind);
    if (doc.kind === 'file') {
      const hit = (d.items || []).find((x) => x.name === doc.name);
      text = hit ? hit.text : '';
      /* 目录名要用后端算出来的（`00-创作/04-导演手册`）。写死成代码常量 DIRECTOR
         会显示成 `00-创作/director/第01集.md` —— 真实项目里根本没有这个目录，
         用户照着路径去找会扑空。 */
      const dStage = (st.stages || []).find((x) => x.id === DIRECTOR) || {};
      pathText = (dStage.path || '00-创作') + '/' + doc.name;
    } else {
      text = d.text || '';
      const s = (st.stages || []).find((x) => x.id === doc.kind) || {};
      pathText = s.path || '';
    }
  } catch (e) {
    if (ed) {
      ed.innerHTML = '<div class="alert bad"><span class="nav-ico">' + icon('alert', 14)
        + '</span><div>读取失败：' + esc(e.detail || e.message) + '</div></div>';
    }
    return;
  }
  renderDoc(root, doc, text, { path: pathText });
  bindEditor(root, ctx, doc, st);
}

/* ---------- 生成 ---------- */
async function doGenerate(root, ctx, st, stage, append) {
  const g = GEN[stage];
  if (!g) return;
  const extra = {};
  if (stage === 'script') {
    const el = root.querySelector('#gpEpRange');
    extra.episodes_range = (el && el.value.trim()) || '1-3';
  }
  if (stage === 'director') {
    const epEl = root.querySelector('#gpEp');
    const ep = ((epEl && epEl.value) || '第01集').trim();
    const shotsEl = root.querySelector('#gpShots');
    extra.shots_per_batch = Number((shotsEl && shotsEl.value) || 5) || 5;
    try {
      const rd = await api.createRead(ctx.ws, 'script');
      const t = String(rd.text || '');
      const at = t.indexOf('## ' + ep);
      extra.script_ep = at >= 0 ? t.slice(at, at + 12000) : t.slice(0, 12000);
      if (!String(extra.script_ep).trim()) {
        toast('剧本还是空的：先生成「分集剧本」', 'bad');
        return null;
      }
    } catch (e) {
      toast('读剧本失败：' + (e.detail || e.message), 'bad');
      return null;
    }
  }
  const r = await api.createGenerate({
    ws: ctx.ws, purpose: g.purpose, stage, append: !!append, ...extra
  });
  return r;
}

/* ---------- 版本对照 ---------- */
async function openVersions(ctx, doc) {
  const stage = doc.kind === 'file' ? DIRECTOR : doc.kind;
  const name = doc.kind === 'file' ? doc.name : '';

  let list;
  try {
    list = await api.createVersions(ctx.ws, stage, name);
  } catch (e) {
    toast('读版本失败：' + (e.detail || e.message), 'bad');
    return;
  }
  const items = list.items || [];
  const backups = items.filter((x) => !x.current);

  if (!backups.length) {
    openModal({
      title: '还没有历史版本',
      icon: 'clock',
      html: '<div class="alert info"><span class="nav-ico">' + icon('alert', 14) + '</span>'
        + '<div>每次保存覆盖前会自动留一份 <span class="mono">.bak_&lt;时间戳&gt;.md</span>，'
        + '所以这里要「改过之后再保存一次」才有东西可比。<br>'
        + '当前文件：<span class="mono">' + esc(list.rel || '') + '</span></div></div>',
      foot: '<span class="spacer"></span><button class="btn quiet" data-close="modal">关闭</button>'
    });
    return;
  }

  /* 左边必须是**磁盘上的当前内容**，不能是编辑器里未保存的草稿：
     草稿会随打字变化，而备份是固定的，比出来的差异没人看得懂。 */
  let curText = '';
  try {
    curText = (await api.createVersion(ctx.ws, stage, name, '')).text || '';
  } catch (e) {
    toast('读当前版本失败：' + (e.detail || e.message), 'bad');
    return;
  }

  let pick = backups[0].file;
  let bakText = '';

  const m = openModal({
    title: '历史版本 · ' + doc.label,
    icon: 'clock',
    html: '<div id="vdBox"></div>',
    foot: '<span class="tiny dim" id="vdHint"></span><span class="spacer"></span>'
      + '<button class="btn quiet" data-close="modal">关闭</button>'
      + '<button class="btn primary" id="vdRestore"' + (S.readonly ? ' disabled' : '') + '>恢复到这个版本</button>',
    mount: () => {}
  });
  /* 560px 放不下左右对照；closeModal 会把这个类摘掉（见 ui.js） */
  m.classList.add('modal-wide');

  const box = m.querySelector('#vdBox');
  const hint = m.querySelector('#vdHint');
  const restore = m.querySelector('#vdRestore');

  const paint = async () => {
    box.innerHTML = '<div class="skeleton" style="height:16px;width:40%;margin-bottom:10px"></div>'
      + '<div class="skeleton" style="height:180px"></div>';
    try {
      bakText = (await api.createVersion(ctx.ws, stage, name, pick)).text || '';
    } catch (e) {
      box.innerHTML = '<div class="alert bad">读取失败：' + esc(e.detail || e.message) + '</div>';
      return;
    }
    const rows = diffRows(curText, bakText);
    const nAdd = rows.filter((r) => r.t === 'add').length;
    const nDel = rows.filter((r) => r.t === 'del').length;
    const cols = vdColumns(rows);
    const b = backups.find((x) => x.file === pick) || {};
    const opt = backups.map((x) => '<option value="' + esc(x.file) + '"'
      + (x.file === pick ? ' selected' : '') + '>' + esc(x.when || '?')
      + ' · ' + x.chars + ' 字</option>').join('');

    box.innerHTML = '<div class="sd-vd-bar">'
      + '<span class="tiny dim">对比</span>'
      + '<select class="select" id="vdPick" style="width:230px">' + opt + '</select>'
      + '<span class="sd-vd-stat"><b class="add">+' + nAdd + '</b> <b class="del">−' + nDel + '</b></span>'
      + '<span class="spacer"></span>'
      + '<span class="tiny dim mono">' + esc(list.name || '') + '</span></div>'
      + '<div class="sd-vd-cols">'
      + '<div class="sd-vd-col"><div class="sd-vd-h"><span>当前（磁盘）</span>'
      + '<span class="mono">' + curText.length + ' 字符</span></div>'
      + '<div class="sd-vd-body" id="vdL">' + cols.left + '</div></div>'
      + '<div class="sd-vd-col"><div class="sd-vd-h"><span>备份 ' + esc(b.when || '') + '</span>'
      + '<span class="mono">' + bakText.length + ' 字符</span></div>'
      + '<div class="sd-vd-body" id="vdR">' + cols.right + '</div></div>'
      + '</div>';

    if (hint) hint.textContent = '备份＝每次保存前的自动快照；恢复会先把当前内容再备份一份';

    const sel = box.querySelector('#vdPick');
    if (sel) sel.onchange = () => { pick = sel.value; paint(); };

    /* 两列纵向同步：看完左边一行再找右边，是这里最常做的动作 */
    const L = box.querySelector('#vdL');
    const R = box.querySelector('#vdR');
    if (L && R) {
      const bind = (src, dst) => {
        let lock = false;
        src.onscroll = () => {
          if (lock) return;
          lock = true;
          dst.scrollTop = src.scrollTop;
          requestAnimationFrame(() => { lock = false; });
        };
      };
      bind(L, R);
      bind(R, L);
    }
  };

  if (restore) restore.onclick = async () => {
    const b = backups.find((x) => x.file === pick) || {};
    const ok = window.confirm('恢复到 ' + (b.when || b.file) + ' 的内容？\n\n'
      + '当前内容会先自动备份成 .bak_<时间戳>.md，所以这一步可撤回。');
    if (!ok) return;
    restore.disabled = true;
    const old = restore.textContent;
    restore.innerHTML = '<span class="spinner"></span> 恢复中';
    try {
      await api.createWrite({ ws: ctx.ws, stage, name, text: bakText });
      toast('已恢复到 ' + (b.when || '该版本'), 'ok');
      closeModal();
      ctx.refresh();
    } catch (e) {
      restore.disabled = false;
      restore.textContent = old;
      toast('恢复失败：' + (e.detail || e.message), 'bad');
    }
  };

  paint();
}

/* ---------- 页面 ---------- */
export async function render(ctx) {
  if (!ctx.ws) {
    return {
      html: '<div class="page-head"><div><h1 class="page-title">创意工作室</h1></div></div>'
        + '<div class="alert warn"><span class="nav-ico">' + icon('alert', 14) + '</span>'
        + '<div>先在左上角选一个项目。</div></div>',
      mount: () => {}
    };
  }

  const [st, inst] = await Promise.all([
    api.createState(ctx.ws).catch((e) => ({ error: String((e && e.detail) || e) })),
    api.skillsInstalled(ctx.ws).catch(() => ({ items: [] }))
  ]);
  if (st.error) {
    return {
      html: '<div class="page-head"><div><h1 class="page-title">创意工作室</h1></div></div>'
        + '<div class="alert bad">读不到创作状态：' + esc(st.error) + '</div>',
      mount: () => {}
    };
  }
  st.skills = inst.items || [];

  const docs = docsOf(st);
  selDoc = pickDefault(docs, st);
  const cur = docs.find((d) => d.key === selDoc) || docs[0];
  const stageOfCur = cur.kind === 'file' ? DIRECTOR : cur.kind;
  const next = st.next || {};
  const sk = st.skills;
  const styleLock = st.idea.style_lock || '';

  /* ---- 右栏：下一步 ---- */
  const nextCard = '<div class="sd-next">'
    + '<div class="sd-next-k">下一步</div>'
    + '<div class="sd-next-main">' + esc(next.label || '—') + '</div>'
    + '<div class="sd-next-why">' + esc(next.why || '') + '</div></div>';

  /* ---- 右栏：生成 ---- */
  const g = GEN[stageOfCur] || null;
  const doneOf = (id) => ((st.stages || []).find((x) => x.id === id) || {}).state === 'done';
  const missing = g ? (g.needs || []).filter((n) => {
    if (n === 'skill') return !sk.length;
    if (n === 'plan') return !doneOf('plan');
    if (n === 'assets') return !doneOf('assets');
    if (n === 'script') return !doneOf('script');
    return false;
  }) : [];
  const can = g && !missing.length;
  const curDone = cur.state === 'done';

  const genCard = g
    ? '<section class="card sd-cwcard"><div class="card-h"><h3>生成</h3>'
      + '<span class="card-sub">' + esc(cur.label) + '</span></div><div class="card-b">'
      + paramRows(stageOfCur, docs, selDoc)
      + '<div class="row" style="gap:6px;flex-wrap:wrap">'
      + '<button class="btn primary sm" id="btnGen"' + (can && !S.readonly ? '' : ' disabled') + '>'
      + (curDone ? '重新生成' : '生成') + '</button>'
      + (curDone && BATCHED[stageOfCur]
        ? '<button class="btn quiet sm" id="btnGenCont"' + (S.readonly ? ' disabled' : '') + '>继续写下一批</button>'
        : '')
      + '</div>'
      + (missing.length
        ? '<div class="sd-note">还缺：' + esc(missing.map((m) => (
          m === 'skill' ? '题材模板' : m === 'plan' ? '企划案' : m === 'assets' ? '资产库' : '剧本'
        )).join(' / ')) + '</div>'
        : '<div class="sd-note">走「' + esc(
          sk[0] ? (sk[0].title || sk[0].id) : '已装载模板') + '」的叙事结构 + 本项目画风锁。</div>')
      + '</div></section>'
    : '<section class="card sd-cwcard"><div class="card-h"><h3>生成</h3></div><div class="card-b">'
      + '<div class="sd-note">「灵感」是你要说的一句话，不是模型生成的。'
      + '填好它，下一步才是让模型写企划案。</div></div></section>';

  /* ---- 右栏：制作包 ---- */
  const packDone = st.pack.state === 'done';
  const packCard = '<section class="card sd-cwcard"><div class="card-h"><h3>制作包</h3>'
    + (packDone ? badge('ok', st.pack.episodes.length + ' 集') : badge('outline', '未导入'))
    + '</div><div class="card-b">'
    + '<div class="sd-note">' + (packDone
      ? '引擎读 <span class="mono">' + esc(st.pack.dir) + '</span>。改了导演手册要再导一次，否则改动不生效。'
      : '引擎读 JSON 契约，不读 Markdown。这一步把导演手册转成 <span class="mono">'
        + esc(st.pack.dir) + '</span>。') + '</div>'
    + '<div class="row" style="gap:6px;margin-top:8px;flex-wrap:wrap">'
    + '<button class="btn' + (packDone ? ' quiet' : ' primary') + ' sm" id="cvPack">'
    + (packDone ? '重新导入' : '转制作包') + '</button>'
    + (packDone ? '<button class="btn quiet sm" data-go="boards">去分镜</button>' : '')
    + '</div></div></section>';

  /* ---- 右栏：上下文（模板 / 画风 / 引擎） ---- */
  const ctxCard = '<section class="card sd-cwcard"><div class="card-h"><h3>上下文</h3>'
    + '<span class="card-sub">模型会看到什么</span></div><div class="card-b sd-kvlist">'
    + '<div class="sd-kvrow"><span class="sd-kv-k">题材模板</span><span class="sd-kv-v">'
    + (sk.length ? esc(sk[0].title || sk[0].id) : '<span class="sd-bad">未装载</span>') + '</span></div>'
    + '<div class="sd-kvrow"><span class="sd-kv-k">画风锁</span><span class="sd-kv-v">'
    + (styleLock ? esc(styleLock.slice(0, 60)) + (styleLock.length > 60 ? '…' : '')
      : '<span class="sd-bad">项目未定画风</span>') + '</span></div>'
    + '<div class="sd-kvrow"><span class="sd-kv-k">引擎产物</span><span class="sd-kv-v mono">'
    + '人物 ' + st.engine.characters + ' · 场景 ' + st.engine.scenes
    + ' · 道具 ' + st.engine.props + ' · 分镜图 ' + st.engine.boards + '</span></div>'
    + '</div><div class="card-foot">'
    + '<button class="btn ghost sm" data-go="skills">换模板</button>'
    + '<span class="spacer"></span>'
    + '<button class="btn ghost sm" id="cvPrompt">看模型指令</button>'
    + '</div></section>';

  const html = ''
    + '<div class="page-head"><div>'
    + '<div class="crumb"><b>创意工作室</b><span class="sep">/</span><b>'
    + esc(ctx.project ? (ctx.project.title || ctx.project.path) : ctx.ws) + '</b></div>'
    + '<h1 class="page-title">创作</h1>'
    + '<div class="page-sub">灵感 → 企划案 → 资产库 → 剧本 → 导演手册。产物落 '
    + '<span class="mono">' + esc(st.dir) + '/</span>，引擎只读制作包 —— 两边永远不抢同一个文件。</div></div>'
    + '<div class="page-actions">'
    + badge(st.progress.done === st.progress.total ? 'ok' : 'outline',
      '完成 ' + st.progress.done + '/' + st.progress.total)
    + (packDone ? ' ' + badge('ok', '已导入 ' + st.pack.episodes.length + ' 集') : '')
    + '</div></div>'

    + '<div class="sd-cw3">'

    /* 左：文档树 */
    + '<section class="card sd-col sd-col-docs">'
    + '<div class="card-h"><h3>文档</h3>'
    + '<span class="card-sub">' + st.progress.done + '/' + st.progress.total + '</span></div>'
    + '<div class="sd-docscroll">' + treeHtml(docs, selDoc) + '</div>'
    + '<div class="card-foot"><span class="tiny dim">4 类产物 · 灵感在 brief.json</span></div>'
    + '</section>'

    /* 中：编辑器 */
    + '<section class="card sd-col sd-col-ed">'
    + edHead(cur)
    + '<div class="sd-edbox" id="edBox"></div>'
    + '</section>'

    /* 右：上下文 */
    + '<div class="sd-col sd-col-ctx">' + nextCard + genCard + packCard + ctxCard + '</div>'

    + '</div>';

  return {
    html,
    mount: (root) => {
      const go = (k) => { if (ctx.navigate) ctx.navigate(k); };
      root.querySelectorAll('[data-go]').forEach((b) => { b.onclick = () => go(b.dataset.go); });

      const beforeLeave = () => {
        if (!dirty) return true;
        return window.confirm('当前文档有未保存的修改，切换会丢掉。继续？');
      };

      /* 树：切换文档。不整页刷新 —— 编辑长文时刷新会丢滚动位置与光标。 */
      root.querySelectorAll('[data-doc]').forEach((b) => {
        b.onclick = async () => {
          if (b.dataset.doc === selDoc) return;
          if (!beforeLeave()) return;
          selDoc = b.dataset.doc;
          root.querySelectorAll('[data-doc]').forEach((x) => {
            x.classList.toggle('on', x.dataset.doc === selDoc);
          });
          /* 记进 URL：刷新 / 分享 / 后退都能回到同一份文档 */
          try {
            const u = new URL(location.href);
            u.searchParams.set('doc', selDoc);
            history.replaceState(null, '', u.toString());
          } catch (e) { /* file:// 下可能不允许，忽略 */ }
          /* 工具栏、生成参数都要跟着换，整页重绘最省事；代价是编辑区滚动复位 */
          ctx.refresh();
        };
      });

      /* 生成 */
      const bindGen = (sel, append) => {
        const b = root.querySelector(sel);
        if (!b) return;
        b.onclick = async () => {
          const old = b.innerHTML;
          b.disabled = true;
          b.innerHTML = '<span class="spinner"></span> 生成中';
          try {
            const r = await doGenerate(root, ctx, st, stageOfCur, append);
            if (!r) { b.disabled = false; b.innerHTML = old; return; }
            const prov = String(r.provider || '');
            if (/Mock|演练/i.test(prov)) {
              toast((r.detail || '已生成') + '（离线演练，非真实创作：到「AI 模型中心」配模型后重生成）', 'warn');
            } else {
              toast(r.detail || '已生成', 'ok');
            }
            dirty = false;
            ctx.refresh();
          } catch (e) {
            const msg = (typeof e.detail === 'string' ? e.detail
              : (e.detail && e.detail.message) || e.message) || '生成失败';
            openModal({
              title: '生成失败',
              icon: 'alert',
              html: '<div class="alert bad"><span class="nav-ico">' + icon('alert', 14) + '</span>'
                + '<div style="white-space:pre-wrap">' + esc(String(msg).slice(0, 900)) + '</div></div>'
                + '<div class="tiny dim">常见原因：没配大模型（去「AI 模型中心」）、'
                + '远端被出口守卫拦（启动加 <span class="mono">SOLODRAMA_ALLOW_REMOTE=1</span>）、'
                + '<span class="mono">max_tokens</span> 太小导致返回为空。</div>',
              foot: '<span class="spacer"></span><button class="btn quiet" data-close="modal">关闭</button>'
            });
            b.disabled = false;
            b.innerHTML = old;
          }
        };
      };
      bindGen('#btnGen', false);
      bindGen('#btnGenCont', true);

      /* 转制作包 */
      const packBtn = root.querySelector('#cvPack');
      if (packBtn) packBtn.onclick = async () => {
        packBtn.disabled = true;
        const old = packBtn.textContent;
        packBtn.innerHTML = '<span class="spinner"></span> 导入中';
        try {
          await runAction(ctx, {
            specId: 'pack.import', title: '转制作包（引擎契约）', params: {},
            onDone: () => setTimeout(() => ctx.refresh(), 1200)
          });
        } finally {
          packBtn.disabled = false;
          packBtn.textContent = old;
        }
      };

      /* 模型将收到的指令 */
      const pv = root.querySelector('#cvPrompt');
      if (pv) pv.onclick = async () => {
        try {
          const d = await api.skillPrompt(ctx.ws);
          openModal({
            title: '模型将收到的指令（' + d.chars + ' 字）',
            icon: 'terminal',
            html: '<div class="tiny dim" style="margin-bottom:8px">这就是实际发出去的内容：'
              + '已装载的 Skill 正文 + 本项目画风锁 + 输出要求。</div>'
              + '<pre class="mono" style="white-space:pre-wrap;font-size:var(--fs-11);line-height:1.55;'
              + 'max-height:min(62vh,560px);overflow:auto;background:var(--sd-inset);'
              + 'border:1px solid var(--sd-line);border-radius:var(--sd-radius-md);padding:12px">'
              + esc(d.text) + '</pre>',
            foot: '<span class="spacer"></span><button class="btn quiet" data-close="modal">关闭</button>'
          });
        } catch (e) { toast('读不到：' + (e.detail || e.message), 'bad'); }
      };

      loadDoc(root, ctx, st, selDoc);
    }
  };
}
