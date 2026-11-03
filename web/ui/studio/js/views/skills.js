/* Skill 中心 —— 把磁盘上的创作模板变成「本项目正在用哪一套」
   为什么单独一页：模板有 20+ 份，散在磁盘上。之前要靠人记得路径、粘进对话框，
   中间没有任何登记 —— 换人接手就不知道这部片用的是哪套题材套路。
   这里只做三件事：看见、装载、看它到底写了什么。装载=复制+登记，不执行任何代码。 */
import { api } from '../api.js';
import { esc, icon, badge, toast, openModal, paintIcons } from '../ui.js';

const CARD = 'border:1px solid var(--line);border-radius:var(--r-lg);background:var(--bg-card);'
  + 'padding:12px 14px';

function head(d, n) {
  return '<div class="page-head"><div><h1 class="page-title">创作模板</h1>'
    + '<div class="page-sub">题材套路、阶段划分、人物关系由它定；'
    + '<b style="color:var(--create)">画风仍由本项目的 style_lock 决定</b>。'
    + '模板是纯 Markdown（给模型看的说明），装载 = 复制 + 登记，不执行任何代码。</div></div>'
    + '<div class="page-actions">' + badge('outline', '可用 ' + (d.count || 0) + ' 份')
    + (n ? ' ' + badge('ok', '本项目已装 ' + n + ' 份') : '')
    + '<button class="btn quiet" id="btnUpload">' + icon('upload', 14) + ' 上传模板</button>'
    + '</div></div>';
}

function card(it, installedSet) {
  const on = installedSet.has(it.id);
  return '<div style="' + CARD + ';display:flex;flex-direction:column;gap:8px">'
    + '<div class="row" style="align-items:baseline;gap:8px">'
    + '<b style="font-size:var(--fs-13)">' + esc(it.title) + '</b>'
    + (on ? badge('ok', '已装载') : '')
    + (it.origin ? badge(it.bundled ? 'muted' : 'live', it.origin) : '') + '</div>'
    + '<div class="mono tiny dim">' + esc(it.id) + ' · ' + it.chars + ' 字</div>'
    + '<div class="tiny" style="color:var(--txt-2);line-height:1.5;flex:1">'
    + esc((it.desc || '').slice(0, 110)) + ((it.desc || '').length > 110 ? '…' : '') + '</div>'
    + '<div class="row" style="gap:6px;margin-top:2px">'
    + '<button class="btn primary sm" data-install="' + esc(it.id) + '"' + (on ? ' disabled' : '') + '>'
    + (on ? '已装载' : '装载到本项目') + '</button>'
    + '<button class="btn quiet sm" data-view="' + esc(it.id) + '">看全文</button>'
    + '</div></div>';
}

export async function render(ctx) {
  if (!ctx.ws) {
    return { html: head({ count: 0 }, 0)
      + '<div class="alert warn"><span class="nav-ico">' + icon('alert', 14) + '</span>'
      + '<div>先在左上角选一个项目 —— Skill 是「按项目装载」的。</div></div>', mount: () => {} };
  }
  const [d, inst] = await Promise.all([
    api.skills().catch((e) => ({ error: String((e && e.detail) || e), items: [] })),
    api.skillsInstalled(ctx.ws).catch(() => ({ items: [] }))
  ]);
  if (d.error) {
    return { html: head(d, 0) + '<div class="alert bad">读不到 Skill：' + esc(d.error) + '</div>', mount: () => {} };
  }
  const items = d.items || [];
  const mine = inst.items || [];
  const mineSet = new Set(mine.map((x) => x.id));

  const installedBlock = mine.length
    ? '<section class="card" style="margin-bottom:16px"><div class="card-h"><h3>本项目在用</h3>'
      + '<span class="card-sub">生成时会把它的正文一起给模型</span></div><div class="card-b" style="display:grid;gap:8px">'
      + mine.map((x) => '<div class="row" style="gap:10px;align-items:center;padding:8px 10px;'
        + 'border:1px solid var(--create-line);border-radius:var(--r-md);background:var(--create-tint)">'
        + '<div style="flex:1"><div><b>' + esc(x.title || x.id) + '</b> '
        + (x.file_exists ? '' : badge('bad', '文件丢失')) + '</div>'
        + '<div class="tiny dim">' + esc(x.installed_at || '') + ' 装载 · sha ' + esc(x.sha || '') + '</div></div>'
        + '<button class="btn quiet sm" data-uninstall="' + esc(x.id) + '">移除</button></div>').join('')
      + '</div><div class="card-foot"><span class="tiny dim">'
      + esc(inst.dir || '') + '　·　装载只是复制 + 登记，不执行任何代码</span></div></section>'
    : '<section class="card" style="margin-bottom:16px"><div class="card-b">'
      + '<div class="empty"><div class="empty-t">还没装载任何题材模板</div>'
      + '<div class="empty-h">下面挑一个题材装载。装载后「创作」页才能生成企划案。</div></div></div></section>';

  const html = head(d, mine.length)
    + installedBlock
    + '<div class="row" style="margin:0 0 10px;gap:8px;align-items:center">'
    + '<b class="small">全部模板</b>'
    + '<input class="input" id="skFilter" placeholder="搜题材 / id" spellcheck="false" style="max-width:260px;margin-left:auto">'
    + '</div>'
    + '<div id="skGrid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:10px">'
    + items.map((it) => card(it, mineSet)).join('') + '</div>'
    + '<div class="tiny dim" style="margin-top:16px">'
    + '来源：' + (d.sources || []).map((s) => '<span class="mono">' + esc(s.path) + '</span>（' + s.count + ' 份）').join('　·　')
    + '<br>要加别的目录：改 <span class="mono">configs/skills-sources.json</span>，或设环境变量 '
    + '<span class="mono">SOLODRAMA_SKILLS_DIR</span>。</div>';

  return {
    html,
    mount: (root) => {
      paintIcons(root);
      const up = root.querySelector('#btnUpload');
      if (up) up.onclick = () => uploadModal(ctx);
      const grid = root.querySelector('#skGrid');
      const filter = root.querySelector('#skFilter');
      if (filter) {
        filter.oninput = () => {
          const q = filter.value.trim().toLowerCase();
          grid.querySelectorAll('[data-install]').forEach((b) => {
            const box = b.closest('div[style]');
            const hit = !q || box.textContent.toLowerCase().indexOf(q) >= 0;
            box.style.display = hit ? '' : 'none';
          });
        };
      }
      root.querySelectorAll('[data-install]').forEach((b) => {
        b.onclick = async () => {
          b.disabled = true;
          try {
            const r = await api.skillInstall(ctx.ws, b.dataset.install);
            toast(r.detail || '已装载', 'ok');
            ctx.refresh();
          } catch (e) {
            toast('装载失败：' + ((e.detail) || e.message), 'bad');
            b.disabled = false;
          }
        };
      });
      root.querySelectorAll('[data-uninstall]').forEach((b) => {
        b.onclick = async () => {
          if (!confirm('移除这个模板？文件会从项目里删掉（原始模板不受影响）。')) return;
          try {
            const r = await api.skillUninstall(ctx.ws, b.dataset.uninstall);
            toast(r.detail || '已移除');
            ctx.refresh();
          } catch (e) { toast('移除失败：' + ((e.detail) || e.message), 'bad'); }
        };
      });
      root.querySelectorAll('[data-view]').forEach((b) => {
        b.onclick = async () => {
          try {
            const it = await api.skillDetail(b.dataset.view);
            openModal({
              title: it.title + ' · ' + it.id,
              icon: 'spark',
              html: '<div class="tiny dim" style="margin-bottom:8px">' + esc(it.desc || '') + '</div>'
                + '<pre class="mono" style="white-space:pre-wrap;font-size:var(--fs-11);line-height:1.6;'
                + 'max-height:min(62vh,560px);overflow:auto;background:var(--bg-inset);'
                + 'border:1px solid var(--line);border-radius:var(--r-md);padding:12px">'
                + esc(it.body || '') + '</pre>',
              foot: '<span class="spacer"></span>'
                + '<button class="btn quiet" data-close="modal">关闭</button>'
            });
          } catch (e) { toast('读取失败：' + ((e.detail) || e.message), 'bad'); }
        };
      });
    }
  };
}

/* ---------- 上传自己的模板 ----------
   两种入口都要能用：选文件（多数人是下载/整理好的 .md）与直接粘贴（多数人从别处复制）。
   校验只做最低限度：有 frontmatter、有 name、有正文。其余交给模型自己读 ——
   这不是代码，不需要「沙箱」，但也不能让一个空文件伪装成模板装进项目。 */
function uploadModal(ctx) {
  openModal({
    title: '上传创作模板',
    icon: 'upload',
    html: '<div class="stack">'
      + '<div class="alert info"><span class="nav-ico">' + icon('alert', 14) + '</span><div>'
      + '模板是给模型看的 Markdown 说明，<b>不会被执行</b>。文件开头必须有：<br>'
      + '<span class="mono tiny">---</span><br><span class="mono tiny">name: my-template</span><br>'
      + '<span class="mono tiny">description: 一句话说明它适合什么题材</span><br>'
      + '<span class="mono tiny">---</span><br>后面跟正文（越具体越好：阶段划分、每批字数、禁止项）。</div></div>'
      + '<div class="field"><label class="tiny dim">从文件读入（.md / .txt）</label>'
      + '<input type="file" id="upFile" accept=".md,.markdown,.txt" class="input" style="padding:6px">'
      + '<div class="help">选文件只是把内容填进下面的输入框，点「上传」才会写盘。</div></div>'
      + '<div class="field"><label class="tiny dim">或直接粘贴</label>'
      + '<textarea class="textarea mono" id="upText" rows="12" spellcheck="false" '
      + 'style="font-size:var(--fs-11);line-height:1.6" placeholder="---&#10;name: my-template&#10;description: ...&#10;---&#10;&#10;# 我的模板"></textarea></div>'
      + '<label class="chk"><input type="checkbox" id="upOver">'
      + '<span>同名模板已存在时覆盖（会替换 web/var/skills-user/&lt;id&gt;/SKILL.md）</span></label>'
      + '<div id="upResult"></div></div>',
    foot: '<span class="spacer"></span><button class="btn quiet" data-close="modal">取消</button>'
      + '<button class="btn primary" id="upOk">上传</button>',
    mount: (m) => {
      const file = m.querySelector('#upFile');
      const text = m.querySelector('#upText');
      file.onchange = () => {
        const f = file.files && file.files[0];
        if (!f) return;
        const r = new FileReader();
        r.onload = () => { text.value = String(r.result || ''); };
        r.onerror = () => { m.querySelector('#upResult').innerHTML =
          '<div class="alert bad"><span class="nav-ico">' + icon('alert', 14) + '</span><div>读不了这个文件</div></div>'; };
        r.readAsText(f, 'utf-8');
      };
      m.querySelector('#upOk').onclick = async () => {
        const btn = m.querySelector('#upOk');
        const box = m.querySelector('#upResult');
        const fname = (file.files && file.files[0] && file.files[0].name) || '';
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner"></span>上传中';
        try {
          const r = await api.skillUpload(text.value, fname, m.querySelector('#upOver').checked);
          if (r.ok) {
            box.innerHTML = '<div class="alert ok"><span class="nav-ico">' + icon('check', 14) + '</span><div>'
              + esc(r.detail || '已上传') + '</div></div>';
            toast('模板已加入库');
            setTimeout(() => { ctx.refresh(); }, 900);
          } else {
            box.innerHTML = '<div class="alert bad"><span class="nav-ico">' + icon('alert', 14) + '</span><div>'
              + esc(r.detail || '上传失败') + '</div></div>';
          }
        } catch (e) {
          box.innerHTML = '<div class="alert bad"><span class="nav-ico">' + icon('alert', 14) + '</span><div>'
            + esc(e.detail || e.message) + '</div></div>';
        } finally {
          btn.disabled = false;
          btn.textContent = '上传';
        }
      };
    }
  });
}
