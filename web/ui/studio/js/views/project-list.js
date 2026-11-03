/* ============================================================
   project-list.js —— 项目清单（工作台与「全部项目」共用一份）

   为什么抽出来
   -----------
   「工作台」和「项目管理」本来是两个页面，但内容重叠 80%：
   两个都在列同一批剧，只是一个多了 KPI、一个多了工具栏。分成两页的直接后果是
   「在工作台看不到搜索、在项目管理看不到待办」，人得记住去哪个页面找什么。
   现在只有一份实现，工作台把它当一块内容嵌进去。

   新建项目 = 建档 + 预配置（画风 / 分辨率 / 集数 / **创作模板**）。
   模板在建档时一次装进项目，因为此时的语境最完整；隔天再回来选，人多半不记得想用哪套。
   ============================================================ */
import { api } from '../api.js';
import { S, setWs, loadProjects } from '../store.js';
import {
  esc, icon, money, badge, openModal, openDrawer, paintIcons, toast, emptyBox
} from '../ui.js';

let sortKey = 'recent';

function normSort(list) {
  const arr = list.slice();
  if (sortKey === 'cost') arr.sort((a, b) => (b.yuan || 0) - (a.yuan || 0));
  else if (sortKey === 'images') arr.sort((a, b) => imgTotal(b) - imgTotal(a));
  else if (sortKey === 'name') arr.sort((a, b) => String(a.title || a.path).localeCompare(String(b.title || b.path), 'zh'));
  else arr.sort((a, b) => imgTotal(b) - imgTotal(a) || String(b.updated_text).localeCompare(String(a.updated_text)));
  return arr;
}

/* 金额：0 与「没有记录」是两件事。台账读不到时显示「—」，
   避免把「不知道花了多少」伪装成「花了 0 元」。 */
function yuanText(v) {
  const n = Number(v);
  if (!n) return '<span title="台账里没有这个项目的消耗记录，不代表花费为 0">—</span>';
  return money(n);
}

/* 图片总数 = 已归档资产 + 散图（与资产页「散图」同源） */
function imgTotal(p) {
  return (Number(p.images) || 0) + (Number(p.loose) || 0);
}

function imgTitle(p) {
  const std = Number(p.images) || 0;
  const loose = Number(p.loose) || 0;
  if (!loose) return std + ' 张已归档资产';
  return std + ' 张已归档 + ' + loose + ' 张散图（未归档，见资产页「散图」）';
}

export async function projectList(ctx) {
  const d = await api.workspaces();
  const all = (d.items || []).filter((p) => p.exists);
  const list = normSort(all);
  const stale = (d.stale || []).filter(Boolean);
  const current = all.some((p) => p.path === d.current) ? d.current : (S.ws || '');

  const cards = list.map((p) => {
    const on = p.path === current;
    return '<div class="card" data-pick="' + esc(p.path) + '" style="cursor:pointer;'
      + (on ? 'border-color:var(--accent-line)' : '') + '">'
      + '<div class="mtile-ph" title="' + esc(imgTitle(p)) + '">' + icon('film', 26)
      + '<span>' + (p.has_output ? imgTotal(p) + ' 张图' : '暂无产出') + '</span>'
      + '<span class="mtile-tag">' + badge(p.has_output ? 'ok' : 'outline', p.has_output ? '有产出' : '未开工') + '</span>'
      + '</div>'
      + '<div class="card-b">'
      + '<div class="row"><span class="flex1" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'
      + esc(p.title || p.path) + '</span>' + (on ? badge('warn', '当前') : '') + '</div>'
      + '<div class="tiny dim mono" style="margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'
      + esc(p.path) + '</div>'
      + '<div class="row" style="margin-top:8px"><span class="mono small">' + yuanText(p.yuan) + '</span>'
      + '<span class="spacer"></span><span class="tiny dim">' + esc(p.updated_text || '—') + '</span></div>'
      + '</div></div>';
  }).join('');

  const rows = list.map((p) => (
    '<tr class="clickable" data-pick="' + esc(p.path) + '">'
    + '<td><div>' + esc(p.title || p.path) + (p.path === current ? ' ' + badge('warn', '当前') : '') + '</div>'
    + '<div class="row-sub mono">' + esc(p.path) + '</div></td>'
    + '<td class="num">' + imgTotal(p) + '</td>'
    + '<td class="num">' + yuanText(p.yuan) + '</td>'
    + '<td class="small dim">' + esc(p.updated_text || '—') + '</td>'
    + '<td class="right"><button class="btn quiet sm" data-pick="' + esc(p.path) + '">打开</button></td></tr>'
  )).join('');

  const staleBar = stale.length
    ? '<div class="alert warn" style="margin-bottom:14px"><span class="nav-ico">' + icon('alert', 14) + '</span>'
      + '<div class="flex1">有 ' + stale.length + ' 个登记目录已经不存在（<span class="mono">'
      + esc(stale.slice(0, 3).join('、')) + (stale.length > 3 ? ' 等' : '') + '</span>）</div>'
      + '<button class="btn quiet sm" id="btnPrune">从清单里移除</button></div>'
    : '';

  const html = ''
    + staleBar
    + '<div class="row" style="margin-bottom:12px;flex-wrap:wrap">'
    + '<div class="search" style="width:260px"><span class="nav-ico">' + icon('search', 14) + '</span>'
    + '<input class="input" id="kw" placeholder="搜索剧名或路径…"></div>'
    + '<select class="select" id="sort" style="width:144px">'
    + ['recent|最近活动', 'cost|花费从高到低', 'images|图片数量', 'name|名称']
      .map((x) => { const [v, t] = x.split('|'); return '<option value="' + v + '"'
        + (sortKey === v ? ' selected' : '') + '>' + t + '</option>'; }).join('')
    + '</select>'
    + '<div class="seg" id="viewSeg">'
    + '<button class="active" data-view="card">卡片</button><button data-view="table">表格</button></div>'
    + '<span class="spacer"></span>'
    + '<span class="tiny dim" id="countHint">共 ' + list.length + ' 个</span>'
    + '<button class="btn quiet sm" id="btnScan">' + icon('search', 14) + ' 扫描本机</button>'
    + '<button class="btn quiet sm" id="btnReg">' + icon('folder', 14) + ' 登记目录</button>'
    + '<button class="btn primary sm" id="btnNew">' + icon('plus', 14) + ' 新建项目</button>'
    + '</div>'
    + '<div class="tile-grid" id="cardView">'
    + (cards || '<div class="placeholder">' + emptyBox('还没有项目', '点上面的「扫描本机」或「登记目录」。') + '</div>')
    + '</div>'
    + '<section class="card" id="tableView" style="display:none"><div class="card-b tight">'
    + '<div class="table-wrap"><table class="tb"><thead><tr>'
    + '<th style="width:46%">剧名 / 路径</th><th class="num">图片</th><th class="num">花费</th>'
    + '<th>更新</th><th></th></tr></thead><tbody>' + rows + '</tbody></table></div></div></section>';

  return {
    html,
    mount: (root) => {
      const kw = root.querySelector('#kw');
      const cardView = root.querySelector('#cardView');
      const tableView = root.querySelector('#tableView');
      const countHint = root.querySelector('#countHint');

      const applyFilter = () => {
        const q = kw.value.trim().toLowerCase();
        let n = 0;
        root.querySelectorAll('[data-pick]').forEach((el) => {
          if (el.tagName === 'TR') return;
          const txt = (el.textContent || '').toLowerCase();
          const hit = !q || txt.indexOf(q) >= 0;
          el.style.display = hit ? '' : 'none';
          if (hit) n += 1;
        });
        countHint.textContent = '共 ' + n + ' 个';
      };
      kw.oninput = applyFilter;

      const sortEl = root.querySelector('#sort');
      if (sortEl) sortEl.onchange = (e) => { sortKey = e.target.value; ctx.refresh(); };

      root.querySelectorAll('[data-pick]').forEach((el) => {
        el.onclick = async (e) => {
          e.stopPropagation();
          const path = el.dataset.pick;
          setWs(path, { pushUrl: true });
          try { await api.setCurrent(path); } catch (err) { /* 注册表写失败不阻塞浏览 */ }
          toast('已打开 ' + path.split(/[\\/]/).pop());
          ctx.navigate('overview');
        };
      });

      const pruneBtn = root.querySelector('#btnPrune');
      if (pruneBtn) {
        pruneBtn.onclick = async () => {
          pruneBtn.disabled = true;
          try {
            const r = await api.prune();
            await loadProjects();
            toast(r.removed && r.removed.length ? '已移除 ' + r.removed.length + ' 个失效目录' : '没有需要清理的');
            ctx.refresh();
          } catch (err) {
            pruneBtn.disabled = false;
            toast('清理失败：' + (err && err.message ? err.message : err), 'bad');
          }
        };
      }

      root.querySelector('#btnReg').onclick = () => registerModal(ctx);
      root.querySelector('#btnScan').onclick = () => scanDrawer(ctx);
      root.querySelector('#btnNew').onclick = () => newProjectModal(ctx);

      root.querySelectorAll('[data-view]').forEach((b) => {
        b.onclick = () => {
          root.querySelectorAll('[data-view]').forEach((x) => x.classList.toggle('active', x === b));
          const isCard = b.dataset.view === 'card';
          cardView.style.display = isCard ? '' : 'none';
          tableView.style.display = isCard ? 'none' : '';
        };
      });
      paintIcons(root);
    }
  };
}

/* ---------- 登记已有目录 ---------- */
function registerModal(ctx) {
  openModal({
    title: '登记已有项目目录',
    html: '<div class="field"><label>目录完整路径（必须已存在）</label>'
      + '<input class="input mono" id="regPath" placeholder="D:\\\\剧本\\\\我的新短剧">'
      + '<div class="help">登记只写入控制台的项目清单，不动目录内容。</div></div>',
    foot: '<span class="spacer"></span><button class="btn quiet" data-close="modal">取消</button>'
      + '<button class="btn primary" id="regOk">登记</button>',
    mount: () => {
      const input = document.getElementById('regPath');
      input.focus();
      document.getElementById('regOk').onclick = async () => {
        const v = input.value.trim();
        if (!v) { toast('请填写路径', 'warn'); return; }
        try {
          await api.register(v, '');
          await loadProjects();
          document.getElementById('modal').classList.remove('on');
          toast('已登记');
          ctx.refresh();
        } catch (err) {
          toast('登记失败：' + (err.detail || err.message), 'bad');
        }
      };
    }
  });
}

/* ---------- 扫描本机 ---------- */
async function scanDrawer(ctx) {
  const d = await api.discover(true).catch((e) => {
    toast('扫描失败：' + (e.detail || e.message), 'bad');
    return null;
  });
  if (!d) return;
  const known = (S.projects || []).map((p) => String(p.path).toLowerCase());
  const fresh = (d.items || []).filter((it) => known.indexOf(String(it.path).toLowerCase()) < 0);
  const rows = fresh.map((it) => (
    '<div class="row" style="padding:8px 0;border-bottom:1px solid var(--line)">'
    + '<div class="flex1"><div class="small">' + esc(it.name) + '</div>'
    + '<div class="tiny dim mono" style="overflow:hidden;text-overflow:ellipsis">' + esc(it.path) + '</div>'
    + '<div class="tiny dim">' + ((Number(it.images) || 0) + (Number(it.loose) || 0)) + ' 张图 · '
    + yuanText(it.yuan) + ' · ' + esc(it.updated_text || '') + '</div></div>'
    + '<button class="btn quiet sm" data-add="' + esc(it.path) + '">登记</button></div>'
  )).join('') || '<div class="empty"><div class="empty-t">没有发现新项目</div>'
    + '<div class="empty-h">已扫描：' + esc((d.roots || []).join('、')) + '</div></div>';

  openDrawer({
    title: '扫描结果（' + fresh.length + ' 个新候选）',
    html: rows + '<div class="alert info" style="margin-top:12px"><span class="nav-ico">' + icon('alert', 14)
      + '</span><div>扫描只读：目录结构 + 图片数 + 台账摘要，不执行任何引擎脚本。</div></div>',
    foot: '<span class="spacer"></span><button class="btn quiet" data-close="drawer">关闭</button>',
    mount: (root) => {
      root.querySelectorAll('[data-add]').forEach((b) => {
        b.onclick = async () => {
          b.disabled = true;
          try {
            await api.register(b.dataset.add, '');
            await loadProjects();
            toast('已登记');
            ctx.refresh();
          } catch (e) {
            b.disabled = false;
            toast('登记失败：' + (e.detail || e.message), 'bad');
          }
        };
      });
    }
  });
}

/* ---------- 新建项目（含项目预配置：画风 / 分辨率 / 创作模板） ---------- */
async function newProjectModal(ctx) {
  let cat = { tracks: [], styles: [], presets: {} };
  let presets = { items: [] };
  try { cat = await api.styles(); } catch (e) { /* 画风目录读不到也要能建项目 */ }
  try { presets = await api.skillPresets(); } catch (e) { /* 模板读不到不阻塞建档 */ }
  const styles = cat.styles || [];
  const aspects = (cat.presets && cat.presets.aspect) || [{ id: '9:16', label: '竖屏 9:16' }];
  const resos = (cat.presets && cat.presets.resolution) || [{ id: '1080x1920', label: '1080×1920' }];
  const roots = [];
  (S.projects || []).forEach((p) => {
    const parent = String(p.path || '').replace(/[\\/][^\\/]+$/, '');
    if (parent && roots.indexOf(parent) < 0) roots.push(parent);
  });

  const styleOpts = styles.length
    ? styles.map((s) => '<option value="' + esc(s.id) + '" data-track="' + esc(s.track) + '">'
      + esc(s.name) + '（' + esc((s.tags || []).join(' · ')) + '）</option>').join('')
    : '<option value="">（画风目录读不到，可先建项目后补）</option>';

  const tpl = (presets.items || []);
  const tplList = tpl.length
    ? tpl.map((t) => '<label class="sk-chip" data-tpl="' + esc(t.id) + '">'
      + '<input type="checkbox" value="' + esc(t.id) + '">'
      + '<span class="sk-n">' + esc(t.title || t.id) + '</span>'
      + '<span class="sk-o">' + esc(t.origin || '') + '</span></label>').join('')
    : '<div class="tiny dim">没找到模板库。可以直接建项目，稍后到「创作模板」页上传或装载。</div>';

  openModal({
    title: '新建剧项目',
    icon: 'plus',
    html: '<div class="stack">'
      + '<div class="alert info"><span class="nav-ico">' + icon('alert', 14) + '</span><div>'
      + '会调用引擎的 <span class="mono">creation.py scaffold</span> 建 9 个阶段目录 + layout.json，'
      + '写入画风、交付分辨率，并把选中的<b>创作模板</b>装进项目。<b>画风建完再改要重新确认（G-1 门禁）</b>。</div></div>'

      + '<div class="field"><label class="tiny dim">放在哪个根目录下</label>'
      + '<select class="select" id="pRoot"><option value="">（手动填下面的完整路径）</option>'
      + roots.map((r) => '<option value="' + esc(r) + '">' + esc(r) + '</option>').join('')
      + '</select>'
      + '<div class="tiny dim" style="margin-top:4px">候选来自你已有项目的上级目录；'
      + '浏览器无法直接选系统文件夹。</div></div>'

      + '<div class="field"><label class="tiny dim">目标目录（绝对路径）</label>'
      + '<input class="input" id="pTarget" placeholder="D:/剧本/我的新剧">'
      + '<div class="tiny dim" style="margin-top:4px">不存在会自动创建；已存在且非空会被拒绝。</div></div>'
      + '<div class="grid g2">'
      + '<div class="field"><label class="tiny dim">剧名</label>'
      + '<input class="input" id="pTitle" placeholder="我的新剧"></div>'
      + '<div class="field"><label class="tiny dim">短标识（小写字母/数字/连字符）</label>'
      + '<input class="input" id="pSlug" placeholder="my-new-drama"></div></div>'

      + '<div class="grid g2">'
      + '<div class="field"><label class="tiny dim">目标平台</label>'
      + '<select class="select" id="pPlatform"><option>ReelShort</option><option>DramaBox</option>'
      + '<option>TikTok</option><option>其他</option></select></div>'
      + '<div class="field"><label class="tiny dim">集数 / 单集秒数</label>'
      + '<div class="row gap8"><input class="input" id="pEp" type="number" min="1" max="200" value="30" style="width:90px">'
      + '<select class="select" id="pSec" style="width:110px"><option value="60">60 秒</option>'
      + '<option value="70">70 秒</option><option value="90">90 秒</option></select></div></div></div>'

      + '<div class="grid g2">'
      + '<div class="field"><label class="tiny dim">画面尺寸</label>'
      + '<select class="select" id="pAspect">'
      + aspects.map((a) => '<option value="' + esc(a.id) + '">' + esc(a.label) + '</option>').join('')
      + '</select></div>'
      + '<div class="field"><label class="tiny dim">分辨率</label>'
      + '<select class="select" id="pRes"></select></div></div>'

      + '<div class="field"><label class="tiny dim">画风（决定生产规格，不只是看起来像什么）</label>'
      + '<select class="select" id="pStyle">' + styleOpts + '</select>'
      + '<div class="tiny dim" id="pStyleHint" style="margin-top:5px"></div></div>'

      + '<div class="field"><label class="tiny dim">创作模板（项目预配置，可多选，最多 6 个）</label>'
      + '<div class="sk-list" id="pSkills">' + tplList + '</div>'
      + '<div class="tiny dim" style="margin-top:5px">模板定叙事套路；<b>画风仍由上面选的画风锁决定</b>。'
      + '上传自己的模板：创作模板页 →「上传」。</div></div>'

      + '<div id="pResult"></div></div>',
    foot: '<span class="spacer"></span><button class="btn quiet" data-close="modal">取消</button>'
      + '<button class="btn primary" id="pCreate">创建</button>',
    mount: (m) => {
      paintIcons(m);
      const $ = (id) => m.querySelector('#' + id);
      const aspectEl = $('pAspect');
      const resEl = $('pRes');
      const styleEl = $('pStyle');

      const fillRes = () => {
        const a = aspectEl.value;
        const pool = resos.filter((r) => !r.aspect || r.aspect === a);
        resEl.innerHTML = (pool.length ? pool : resos)
          .map((r) => '<option value="' + esc(r.id) + '">' + esc(r.label) + '</option>').join('');
      };
      const paintStyle = () => {
        const it = styles.find((s) => s.id === styleEl.value) || {};
        const track = (cat.tracks || []).find((t) => t.id === it.track) || {};
        const spec = track.spec || {};
        const sd = spec.shot_duration || {};
        $('pStyleHint').innerHTML = it.id
          ? esc((it.prompt || '').slice(0, 90)) + '…<br>'
            + '轨道 <b>' + esc(track.label || it.track) + '</b>：单镜 '
            + esc((sd.min || '?') + '-' + (sd.max || '?') + ' 秒') + '，交付到 '
            + esc(spec.delivery_stop || '—')
          : '';
      };
      aspectEl.onchange = fillRes;
      styleEl.onchange = paintStyle;
      fillRes();
      paintStyle();

      /* 模板多选：最多 6 个（超过 6 份正文会让提示词自己打架，也让上下文变贵） */
      const boxes = () => Array.from(m.querySelectorAll('#pSkills input[type=checkbox]'));
      boxes().forEach((b) => {
        b.onchange = () => {
          const on = boxes().filter((x) => x.checked);
          if (on.length > 6) {
            b.checked = false;
            toast('最多选 6 个模板；多份模板的叙事要求会互相打架', 'warn');
          }
          boxes().forEach((x) => {
            const lab = x.closest('.sk-chip');
            if (lab) lab.classList.toggle('on', x.checked);
          });
        };
      });

      $('pRoot').onchange = () => {
        const root = $('pRoot').value;
        const t = $('pTarget');
        if (root && (!t.value.trim() || t.value.indexOf(root) === 0)) {
          t.value = root.replace(/[\\/]+$/, '') + '/';
          t.focus();
        }
      };
      $('pTitle').oninput = () => {
        const slugEl = $('pSlug');
        if (slugEl.dataset.touched) return;
        const t = $('pTitle').value.trim().toLowerCase();
        if (/^[a-z0-9 _-]+$/.test(t)) slugEl.value = t.replace(/[ _]+/g, '-').replace(/^-+|-+$/g, '');
      };
      $('pSlug').oninput = () => { $('pSlug').dataset.touched = '1'; };

      const btn = m.querySelector('#pCreate');
      btn.onclick = async () => {
        const target = ($('pTarget').value || '').trim();
        const slug = ($('pSlug').value || '').trim().toLowerCase();
        const title = ($('pTitle').value || '').trim();
        const box = $('pResult');
        if (!/^[A-Za-z]:[\/]/.test(target) && target.charAt(0) !== '/') {
          box.innerHTML = '<div class="alert bad"><span class="nav-ico">' + icon('alert', 14)
            + '</span><div>目标目录必须是绝对路径（如 D:/剧本/我的新剧）</div></div>';
          return;
        }
        if (!/^[a-z0-9][a-z0-9_-]{1,40}$/.test(slug)) {
          box.innerHTML = '<div class="alert bad"><span class="nav-ico">' + icon('alert', 14)
            + '</span><div>短标识只允许小写字母/数字/连字符，2-40 位</div></div>';
          return;
        }
        if (!title) {
          box.innerHTML = '<div class="alert bad"><span class="nav-ico">' + icon('alert', 14)
            + '</span><div>请填剧名</div></div>';
          return;
        }
        const picked = styles.find((s) => s.id === styleEl.value) || {};
        const skills = boxes().filter((x) => x.checked).map((x) => x.value);
        btn.disabled = true;
        btn.innerHTML = '<span class="spinner"></span>创建中';
        box.innerHTML = '';
        try {
          const r = await api.createProject({
            target, slug, title,
            platform: $('pPlatform').value,
            ep: Number($('pEp').value),
            sec: Number($('pSec').value),
            resolution: resEl.value || '',
            aspect: aspectEl.value || '9:16',
            style: styleEl.value || '',
            track: picked.track || '',
            skills
          });
          if (r.ok) {
            const prof = r.profile || {};
            const sk = r.skills || {};
            const warn = (prof.warnings || []).length
              ? '<div class="alert warn" style="margin-top:8px"><span class="nav-ico">' + icon('alert', 14)
                + '</span><div>' + esc((prof.warnings || []).join('；')) + '</div></div>' : '';
            box.innerHTML = '<div class="alert ok"><span class="nav-ico">' + icon('check', 14)
              + '</span><div>已创建并登记：<span class="mono">' + esc(r.target) + '</span>'
              + '<div class="tiny dim" style="margin-top:4px">'
              + (prof.style ? '画风 ' + esc(prof.style.id) + '（' + esc(prof.style.track) + '）' : '画风未设')
              + ' · ' + (prof.resolution ? esc(prof.resolution) : '分辨率未设')
              + ' · 模板 ' + esc(String((sk.installed || []).length)) + ' 份'
              + ' · 耗时 ' + esc(r.elapsed) + ' 秒</div></div></div>' + warn;
            toast('项目已创建');
            await loadProjects();
            import('../store.js').then((sm) => sm.setWs(r.target, { pushUrl: true }));
            setTimeout(() => { closeModalSafe(); ctx.navigate('overview'); }, 1400);
          } else {
            box.innerHTML = '<div class="alert bad"><span class="nav-ico">' + icon('alert', 14)
              + '</span><div>创建失败（退出码 ' + esc(r.rc) + '）：'
              + esc((r.friendly && r.friendly.text) || '见下方输出') + '</div></div>'
              + '<pre class="log" style="max-height:200px">' + esc((r.stdout || '').slice(-2000)) + '</pre>';
          }
        } catch (e) {
          const dd = e.detail;
          box.innerHTML = '<div class="alert bad"><span class="nav-ico">' + icon('alert', 14) + '</span><div>'
            + esc(typeof dd === 'string' ? dd : (dd && dd.message) || e.message) + '</div></div>';
        } finally {
          btn.disabled = false;
          btn.textContent = '创建';
        }
      };
    }
  });
}

function closeModalSafe() {
  const m = document.getElementById('modal');
  if (m) { m.classList.remove('on'); m.setAttribute('aria-hidden', 'true'); }
}
