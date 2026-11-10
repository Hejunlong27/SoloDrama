/* 资产中心：缺口（引擎判定）+ 参考图超限 + 资产图片预览（工作区白名单）+ 真实出图
   出图走引擎既有的两条通道：
     本地 ComfyUI  ￥0，占 GPU                     → assets.local   --submit
     云端 ComfyUI  ★按主机时长                    → assets.cloud   --submit
     RH 工作流     ★按张结算                      → assets.rh_wf
   前置：引擎的 gen_assets_local.py **只认环境变量 SOLODRAMA_ASSET_MD**，
   所以这里必须先选「资产提示词 md」，由后端注入（浏览器永远不拼命令）。 */
import { api, mediaUrl } from '../api.js';
import { esc, icon, badge, stamp, toast, openDrawer, closeDrawer, openModal, closeModal, paintIcons } from '../ui.js';
import { runAction, doRun } from '../action.js';
import { S } from '../store.js';

/* ★ 2026-11-10 用户裁决：资产只有三类素材 —— 角色 / 场景 / 道具。
   「参考图」与「散图」不再是一级分类，原因不是嫌多，而是**它们在语义上不成立**：

     · `06-提示词/refs_h3` 是 `prepare_refs.py` 生成的**瘦身副本**
       （长边缩到 ≤2048、转 JPEG，只为绕开 H3 的 5760px 上限），
       原图在 `04-资产/*`。把派生文件做成并列分类，等于让用户在两处看到同一张图，
       而且改原图不会让副本自动更新 —— 迟早对不上。
     · 「散图」是**没归位的图**：它不该是一个类别，而是一个待办（把图放进对应目录）。

   所以两者降级为「诊断」：仍然能看（否则用户的图会"消失"），但不再是主分类，
   也不参与缺口与出图判定。归位之后它们自然会变空。 */
const TABS = [
  { key: 'characters', label: '角色', dir: '04-资产/characters' },
  { key: 'scenes', label: '场景', dir: '04-资产/scenes' },
  { key: 'props', label: '道具', dir: '04-资产/props' }
];

/* 诊断视图：不在主分类里，从右侧「诊断」按钮进入。
   保留理由只有一个 —— 不给入口的话，根目录那几十张图在界面上等于不存在。 */
const DIAG = [
  { key: 'refs', label: '参考图副本', dir: '06-提示词/refs_h3',
    hint: '出片用的瘦身副本（长边 ≤2048 / JPEG），原图在角色·场景·道具里' },
  { key: 'loose', label: '未归位图片', dir: '', loose: true,
    hint: '不在这三个目录里的图。把它们放进对应目录后就会出现在主分类' }
];

/* 页签放在 URL 里（#/assets?tab=loose）：刷新、后退、分享链接都不丢当前页签。
   与 AI 模型中心保持同一套写法，避免「这页记得住、那页记不住」。 */
function currentTab() {
  const m = String(location.hash || '').match(/[?&]tab=([a-z]+)/);
  const k = m ? m[1] : 'characters';
  return (TABS.concat(DIAG)).some((t) => t.key === k) ? k : 'characters';
}

function tabDef(key) {
  return TABS.concat(DIAG).find((t) => t.key === key) || TABS[0];
}

/* ---------- 角色档案 ----------
   一个角色一个框（用户 2026-11-10 定的形态）。框内结构：

     ┌ P01  Elena Vargas            主形象 VIEW · 5/5 变体 ┐
     │ ┌─────────────────────────────────────────────────┐ │
     │ │            主形象 / 当前变体 大图                 │ │  ← 框内可滚动
     │ │                                                 │ │
     │ └─────────────────────────────────────────────────┘ │
     │ [主形象] [三视图] [造型A] [造型B] [造型C] [表情]     │  ← 文字选变体
     └─────────────────────────────────────────────────────┘

   为什么这样做（相对上一版全部缩略图平铺）：
   · 一屏里能看清「这个人长什么样」，而不是先看一堆 118px 的小图；
   · 变体用**文字**选，因为 code（LOOK-B）就是出片参考图的 key，文字本来就要读；
     缩略图只做辅助，不再承担识别职责；
   · 一个角色占一个框，扫视时是「数人头」而不是「数图」。

   数据仍然全部来自 `/api/studio/characters`（派生视图，不落盘）。 */
function charRoster(roster) {
  const items = (roster && roster.items) || [];
  const layers = (roster && roster.layers) || [];
  const layerLabel = {};
  const layerHint = {};
  layers.forEach((l) => { layerLabel[l.key] = l.label; layerHint[l.key] = l.hint; });

  if (!items.length) {
    return '<section class="card sd-roster-wrap"><div class="card-h"><h3>角色</h3>'
      + '<span class="card-sub">一个角色一个框 · 主形象 + 各套变体</span></div>'
      + '<div class="card-b"><div class="empty" style="padding:40px 16px">'
      + '<div class="empty-t">还没有角色</div>'
      + '<div class="empty-h"><span class="mono">00-创作/02-资产库.md</span> 里没有角色，'
      + '<span class="mono">04-资产/characters/</span> 下也没有 <span class="mono">P01_…png</span>。'
      + '</div></div></div></section>';
  }

  const card = (c) => {
    const master = c.master || null;
    /* 变体 tab：主形象永远排第一并单独标出来，其余按层别顺序。
       没图的变体也列（灰掉），因为它是个「待出图」的待办，藏起来就没人记得。 */
    const tabs = c.variants.map((v, i) => ({ v, i }));
    tabs.sort((a, b) => {
      const am = master && a.v.code === master.code ? -1 : 0;
      const bm = master && b.v.code === master.code ? -1 : 0;
      if (am !== bm) return am - bm;
      const ao = layers.findIndex((l) => l.key === a.v.layer);
      const bo = layers.findIndex((l) => l.key === b.v.layer);
      return (ao < 0 ? 99 : ao) - (bo < 0 ? 99 : bo) || a.v.code.localeCompare(b.v.code);
    });

    const tabHtml = tabs.map(({ v }, i) => {
      const isMaster = master && v.code === master.code;
      const cls = 'sd-ctab' + (isMaster ? ' master' : '') + (v.count ? '' : ' empty');
      const title = (layerLabel[v.layer] || v.layer) + (v.label ? ' · ' + v.label : '')
        + (v.count ? '' : '（待出图）');
      return '<button class="' + cls + '" data-cid="' + esc(c.id) + '" data-cv="' + esc(v.code) + '"'
        + (i === 0 ? ' data-first="1"' : '')
        + ' title="' + esc(title) + '">'
        + (isMaster ? '<i class="sd-ctab-star">★</i>' : '')
        + '<span class="sd-ctab-code mono">' + esc(v.code) + '</span>'
        + '<span class="sd-ctab-lb">' + esc(layerLabel[v.layer] || v.layer) + '</span>'
        + '</button>';
    }).join('');

    return '<div class="sd-ccard" data-card="' + esc(c.id) + '">'
      + '<div class="sd-ccard-h">'
      + '<span class="sd-ccard-id mono">' + esc(c.id) + '</span>'
      + '<span class="sd-ccard-name">' + esc(c.name) + '</span>'
      + (master ? badge('ok', '主形象 ' + master.code) : badge('warn', '尚无主形象'))
      + '<span class="spacer"></span>'
      + '<span class="sd-ccard-stat"><b>' + c.variants_done + '</b>/' + c.variants_total + ' 变体</span>'
      + '<span class="sd-ccard-stat"><b>' + c.images_total + '</b> 图</span>'
      + '</div>'
      + (c.role || c.anchor
        ? '<div class="sd-ccard-sub">'
          + (c.role ? '<span>' + esc(c.role) + '</span>' : '')
          + (c.anchor ? '<span class="sd-ccard-anchor">锚点 ' + esc(c.anchor) + '</span>' : '')
          + '</div>'
        : '')
      + '<div class="sd-cstage" data-stage="' + esc(c.id) + '"></div>'
      + '<div class="sd-ctabs">' + tabHtml + '</div>'
      + '</div>';
  };

  return '<section class="card sd-roster-wrap">'
    + '<div class="card-h"><h3>角色</h3>'
    + '<span class="card-sub">' + items.length + ' 个角色 · 主形象 + 各套变体</span>'
    + '<span class="spacer"></span>'
    + (roster.no_master
      ? '<span class="badge warn">' + roster.no_master + ' 个尚无主形象</span>' : '')
    + '<button class="btn quiet" id="btnViewSheet"'
    + ' title="把三视图/表情提示词统一成 16:9 三视图 + 表情四宫格">按规范改写身份卡…</button>'
    + '</div>'
    + '<div class="card-b sd-roster">' + items.map(card).join('') + '</div>'
    + '<div class="card-foot"><span class="tiny dim">'
    + '★ 主形象＝这个角色的基准图；各套造型是它的派生。变体 code（如 '
    + '<span class="mono">LOOK-B</span>）就是出片时的参考图 key</span></div></section>';
}

/* 把某个变体渲染进角色框的图片区。点 tab 时只换这一块，不重绘整页。 */
/* 重出成功后要让浏览器重新取图。
   `/media` 带 `Cache-Control: private, max-age=60` + ETag(mtime-size)，
   60 秒内不会重新请求 —— 于是「重出了但看起来没变」，用户会以为失败了。
   只 bust 刚重出的那一张，不整页刷（整页刷会让所有图重新下载）。 */
const BUSTED = {};

function renderVariantStage(stageEl, c, v) {
  if (!stageEl || !v) return;
  const imgs = v.urls || [];
  const head = '<div class="sd-cstage-bar">'
    + '<span class="mono">' + esc(c.id + '@' + v.code) + '</span>'
    + '<span class="sd-cstage-lb">' + esc(v.label || v.code) + '</span>'
    + '<span class="spacer"></span>'
    + (v.prompt ? '<button class="btn quiet sm" data-act="prompt">看提示词</button>' : '')
    /* 重出：单变体重新生成。这条走的是引擎的 `--only <key> --force`，
       不是「删了再整批跑」—— 整批会连带重出别的角色，既慢又可能更差。 */
    + '<button class="btn quiet sm" data-act="regen"'
    + ' title="只重出这一张（旧图会先备份到 _bak/）">重出这一张</button>'
    + '<span class="tiny dim">' + imgs.length + ' 张</span>'
    + '</div>';

  if (!imgs.length) {
    stageEl.innerHTML = head + '<div class="sd-cstage-body"><div class="empty" style="padding:36px 16px">'
      + '<div class="empty-t">这个变体还没有出图</div>'
      + '<div class="empty-h">提示词已在，跑右上角「出图…」就会产出。</div></div></div>';
    return;
  }
  /* 多张时横向滚动（框内可滑动）；单张时居中。
     ★ 不要按 code 猜横竖：`VIEW` 在新规范里是 16:9，但**存量项目是 9:16 竖图**
       （1088×1920，三视图纵向堆叠）。按 code 判横图会把竖图拉满宽度、
       高度炸到两千多像素，结果只看得见人物头顶。
       横竖交给浏览器：`max-height` + `width:auto` 对两种比例都成立。 */
  stageEl.innerHTML = head + '<div class="sd-cstage-body'
    + (imgs.length > 1 ? ' multi' : '') + '">'
    + imgs.map((u, i) => {
      const bt = BUSTED[c.id + '@' + v.code];
      const src = bt ? (u + (u.indexOf('?') >= 0 ? '&' : '?') + 'v=' + bt) : u;
      return '<a class="sd-cshot" href="' + esc(src) + '" target="_blank" rel="noopener"'
        + ' data-i="' + i + '"><img loading="lazy" alt="" src="' + esc(src) + '"></a>';
    }).join('')
    + '</div>';
}

/* ---------- 单变体重出 ----------
   走的是引擎本来就有的能力：`assets.local/cloud --only <key> --force`。
   不是「删掉文件再整批跑」—— 整批会连带重出别的角色，既慢又可能让好的图变差。

   三条纪律，缺一条就会变成「点了没反应」或「花了钱不知道」：
     1. **通道不由界面选**：读 `/api/studio/image-channel`（真源是 model-plan.json）。
        界面自定默认值 → 与确认单不一致 → 引擎门禁 4 → 用户只看到没反应。
     2. **必须 force**：不带 force 引擎会 `--skip-existing` 跳过已有产物，点了等于没做。
     3. **必须 backup**：comfy_client 是直接覆盖，没有旧版。「重出更差」时得能退回。
        （RH 工作流通道不经过本地落盘，`backup=false` 时在界面上说明。）
*/
async function regenVariant(ctx, root, c, v) {
  const key = c.id + '@' + v.code;
  if (S.readonly) { toast('只读模式：不能提交出图任务', 'warn'); return; }

  let ch;
  try {
    ch = await api.imageChannel(ctx.ws);
  } catch (e) {
    toast('读通道失败：' + (e.detail || e.message), 'bad');
    return;
  }

  /* RH 工作流的 --only 是老 md 口径（`char_01`），不是 `P01@LOOK-B`。
     传过去会「找不到资产」或更糟地匹配到别的。与其猜，不如说清为什么不给做。 */
  if (ch.spec === 'assets.rh_wf') {
    openModal({
      title: '这一条通道不支持单张重出',
      icon: 'alert',
      html: '<div class="alert warn"><span class="nav-ico">' + icon('alert', 14) + '</span>'
        + '<div>当前项目在模型确认单里选的是 <b>RunningHub 工作流</b>。'
        + '它的 <span class="mono">--only</span> 按 <span class="mono">char_01</span> 这类老口径取资产，'
        + '不接受 <span class="mono">' + esc(key) + '</span> 这种变体 key。<br>'
        + '要在这一张上重出，先把图像通道切到本地或云端 ComfyUI（模型确认单），再回来点。</div></div>',
      foot: '<span class="spacer"></span><button class="btn quiet" data-close="modal">知道了</button>'
    });
    return;
  }

  const has = (v.urls || []).length;
  const paid = !!ch.paid;
  /* 这个变体只存在于 md、包里没有 —— `--only` 会在包里找不到而失败（rc=2）。
     与其让人点了看一句「找不到资产 id」，不如在这里说清原因。 */
  const inPack = !(c.drift && (c.drift.md_only || []).indexOf(v.code) >= 0);
  const line = (k, val) => '<div class="cost-line"><span class="k">' + k + '</span>'
    + '<span class="v">' + val + '</span></div>';

  openModal({
    title: '重出 ' + key,
    icon: 'image',
    html: '<div class="small" style="margin-bottom:10px">只重新生成这一张，其他变体不动。</div>'
      + line('目标', '<span class="mono">' + esc(key) + '</span>')
      + line('通道', esc(ch.label || ch.spec) + (paid ? ' <b class="sd-bad">★计费</b>' : ' <span class="tiny dim">￥0</span>'))
      + (ch.url ? line('地址', '<span class="mono tiny">' + esc(ch.url) + '</span>') : '')
      + (paid && ch.cost ? line('计费口径', esc(ch.cost)) : '')
      + line('现有图', has ? (has + ' 张会被覆盖') : '还没有图（首次出图）')
      + line('旧图处理', ch.backup
        ? '先备份到 <span class="mono">_bak/</span>，不满意可找回'
        : '<b class="sd-bad">这一条通道不备份旧图</b>')
      + (!inPack
        ? '<div class="alert bad" style="margin-top:10px"><span class="nav-ico">' + icon('alert', 14)
          + '</span><div><b>制作包里没有 <span class="mono">' + esc(key) + '</span> 这个变体</b>'
          + '（包里只有 <span class="mono">' + esc(((c.drift && c.drift.pack_only) || []).join(' / ') || '—')
          + '</span>）。引擎的 <span class="mono">--only</span> 在包里查不到就会中止，重出一定失败。<br>'
          + '先跑一次导入重建制作包（把 <span class="mono">02-资产库.md</span> 的新变体同步进 pack），'
          + '再回来重出。</div></div>' : '')
      + (ch.fake_cloud
        ? '<div class="alert bad" style="margin-top:10px"><span class="nav-ico">' + icon('alert', 14)
          + '</span><div>确认单选的是云端，但地址指回本机 —— 引擎会直接拦（假云端）。'
          + '先在模型确认单里改对地址。</div></div>' : '')
      + (!ch.confirmed
        ? '<div class="alert warn" style="margin-top:10px"><span class="nav-ico">' + icon('alert', 14)
          + '</span><div>模型确认单里这一类还没确认。首次提交可能被门禁拦下（需先确认通道）。</div></div>'
        : '')
      + (paid
        ? '<div class="alert warn" style="margin-top:10px"><span class="nav-ico">' + icon('alert', 14)
          + '</span><div>这是<b>计费通道</b>。单张重出会重新占用实例时长；'
          + '真实金额以云平台账单为准，这里不给估算。</div></div>'
        : '<div class="alert info" style="margin-top:10px"><span class="nav-ico">' + icon('cpu', 14)
          + '</span><div>本机 GPU 出图，不产生平台费用；但会占用几分钟，期间别的出图任务会排队。</div></div>'),
    foot: '<span class="spacer"></span><button class="btn quiet" data-close="modal">取消</button>'
      + '<button class="btn primary" id="rgGo"' + (inPack ? '' : ' disabled') + '>'
      + (paid ? '确认计费并重出' : '开始重出') + '</button>',
    mount: (m) => {
      const go = m.querySelector('#rgGo');
      if (!go) return;
      go.onclick = () => {
        if (!inPack) { toast('制作包里没有这个变体，先重建制作包', 'bad'); return; }
        if (ch.fake_cloud) { toast('假云端：先改确认单地址', 'bad'); return; }
        go.disabled = true;
        go.innerHTML = '<span class="spinner"></span> 提交中';
        doRun(ctx, {
          specId: ch.spec,
          title: '重出 ' + key,
          params: {
            only: key,
            force: true,        // 不带这个会被 --skip-existing 跳过，等于什么都没做
            submit: true,
            backup: !!ch.backup
          },
          confirm: { ack: true },
          onDone: (res) => {
            if (!res) return;
            if (res.mode === 'job' && res.job) {
              pollRegen(ctx, res.job, key, 0);
              return;
            }
            if (res.rc === 0) afterRegen(ctx, key);
          }
        });
      };
    }
  });
}

/* 作业跑完再让这张图重新加载。
   出图是 mode=job（几分钟），不能在提交瞬间就刷新 —— 那时文件还没写。 */
function pollRegen(ctx, job, key, tries) {
  const id = job.id || job.job_id || job;
  if (tries > 120) {                    // 3s × 120 ≈ 6 分钟
    toast('重出任务仍在跑，去任务中心看进度（' + key + '）', 'warn');
    return;
  }
  setTimeout(async () => {
    let r;
    try { r = await api.job(id); }
    catch (e) { pollRegen(ctx, job, key, tries + 1); return; }
    const j = (r && r.job) || {};
    if (j.status === 'queued' || j.status === 'running') { pollRegen(ctx, job, key, tries + 1); return; }
    if (j.exit_code === 0) {
      afterRegen(ctx, key);
      return;
    }
    const why = (r.friendly && (r.friendly.title || r.friendly.summary)) || ('退出码 ' + j.exit_code);
    toast('重出失败：' + why, 'bad');
  }, 3000);
}

function afterRegen(ctx, key) {
  /* `/media` 是 `max-age=60` + ETag(mtime-size)。不 bust 的话，60 秒内浏览器
     仍显示旧图 —— 用户会认为「重出没生效」。只 bust 这一张，不动别的。 */
  BUSTED[key] = Date.now();
  toast('已重出：' + key, 'ok');
  if (ctx.refresh) ctx.refresh();
}

export async function render(ctx) {
  const tab = currentTab();
  /* 散图清单**总是取**（不只是切到散图页签时）：
     KPI 上要能写「另有 N 张未归档」，否则用户看到「角色资产 0」会以为图丢了。 */
  const [ov, dirData, md, looseAll] = await Promise.all([
    api.overview(ctx.ws).catch((e) => ({ ok: false, error: e.detail || e.message })),
    tabDef(tab).loose
      ? Promise.resolve({ items: [], groups: [] })
      : api.artifacts(ctx.ws, tabDef(tab).dir)
        .catch((e) => ({ ok: false, error: e.detail || e.message, items: [] })),
    api.assetMd(ctx.ws).catch(() => ({ items: [], suggested: '', note: '' })),
    api.loose(ctx.ws).catch(() => ({ items: [], groups: [] }))
  ]);
  /* 角色档案：把 P01 的 VIEW / LOOK-A..E / EXP 归成一张卡。
     单独取、失败不阻断本页 —— 档案是派生的，读不到时图片网格照常可用。 */
  const roster = await api.characters(ctx.ws).catch(() => ({ items: [], layers: [] }));

  const a = (ov && ov.assets) || {};
  const refsOver = (ov && ov.refs_over) || [];
  const dirDataFinal = tab === 'loose' ? looseAll : dirData;
  const looseN = (looseAll.items || []).length;
  const items = (dirDataFinal.items || []).filter((it) => !it.dir && it.kind === 'image');

  const tiles = items.map((it) => (
    '<div class="mtile" data-img="' + esc(it.rel) + '" data-name="' + esc(it.name) + '" style="cursor:pointer">'
    + '<img class="frame" loading="lazy" alt="" src="' + esc(it.url || mediaUrl(ctx.ws, it.rel)) + '">'
    + '<div class="mtile-cap"><span class="mono">' + esc(it.name) + '</span></div></div>'
  )).join('') || '<div class="placeholder" style="grid-column:1/-1">'
    + '<div class="ph-icon">' + icon('image', 22) + '</div>'
    + (tab === 'loose'
      ? '标准目录之外没有散图（根目录与一层子目录都看过了）'
      : ('这个目录里还没有图片（或目录不存在：<span class="mono">'
        + esc(tabDef(tab).dir || '') + '</span>）'))
    + '<div class="tiny dim" style="margin-top:8px">'
    + (tab === 'loose'
      ? '把图移到 <span class="mono">04-资产/characters|scenes|props</span> 就会出现在对应分页里。'
      : '用右上角「出图…」生成（本地 ￥0）。')
    + '</div></div>';

  const missChars = (a.missing_characters || []).slice(0, 24);
  const missScenes = (a.missing_scenes || []).slice(0, 24);
  const mdOk = !!(md && md.suggested);

  const html = ''
    + '<div class="page-head"><div>'
    + '<div class="crumb"><b>项目管理</b><span class="sep">/</span><b>'
    + esc(ctx.project ? (ctx.project.title || ctx.project.path) : ctx.ws) + '</b></div>'
    + '<h1 class="page-title">资产</h1>'
    + '<div class="page-sub">缺口由引擎按资产卡节号判定；图片直接读工作区（不复制、不转码）</div></div>'
    + '<div class="page-actions">'
    + '<button class="btn quiet" id="btnAssetCheck">' + icon('cpu', 14) + ' 出图器体检</button>'
    + '<button class="btn quiet" id="btnRefsCheck">' + icon('alert', 14) + ' 参考图体检</button>'
    + '<button class="btn quiet" id="btnRefsShrink">' + icon('download', 14) + ' 瘦身参考图…</button>'
    + '<button class="btn primary" id="btnGen">' + icon('spark', 14) + ' 出图…</button>'
    + '</div></div>'

    + (refsOver.length ? '<div class="alert warn" style="margin-bottom:14px"><span class="nav-ico">'
      + icon('alert', 14) + '</span><div><b>' + refsOver.length + ' 张参考图长边超过 5760px</b>'
      + '（平台会丢弃并导致画面错位）。瘦身会写盘（自动备份），点右上角'
      + '「瘦身参考图…」确认后执行。</div></div>' : '')

    /* 只有**没有制作包**时这条才成立：引擎优先读 <ws>/pack，
       有包就不看 SOLODRAMA_ASSET_MD。一上来就喊「缺 md」会让有包的项目以为出不了图。 */
    + ((!mdOk && !roster.pack_exists)
      ? '<div class="alert warn" style="margin-bottom:14px"><span class="nav-ico">'
        + icon('alert', 14) + '</span><div><b>没找到「资产提示词 md」，也没有制作包</b>，出图会被引擎拒绝'
        + '（它会报「未设置 SOLODRAMA_ASSET_MD」）。先把资产提示词 md 放进 '
        + '<span class="mono">04-资产/</span>，或跑导入生成 <span class="mono">pack/</span> 后再刷新本页。'
        + '<div class="tiny dim" style="margin-top:4px">' + esc((md && md.note) || '') + '</div></div></div>' : '')

    /* md 与 pack 的变体对不上：界面显示的提示词来自 md，出图只认 pack。
       点「重出」会用另一份提示词，或直接报「找不到资产 id」—— 必须提前说。 */
    + ((roster.drift || []).length
      ? '<div class="alert warn" style="margin-bottom:14px"><span class="nav-ico">'
        + icon('alert', 14) + '</span><div><b>' + roster.drift.length
        + ' 个角色的变体在「资产库 md」和「制作包」里不一致</b>（'
        + esc(roster.drift.join(' / ')) + '）。'
        + '本页的提示词读 <span class="mono">' + esc(roster.source_md || '') + '</span>，'
        + '而出图只认 <span class="mono">' + esc(roster.source_pack || 'pack/') + '</span>。<br>'
        + '这时点「重出这一张」会用包里的旧提示词，或直接报「找不到资产 id」。'
        + '先跑一次导入重建制作包，两边就一致了。</div></div>' : '')

    + '<div class="grid g4" style="margin-bottom:16px">'
    + '<div class="kpi"><div class="kpi-k">角色资产</div><div class="kpi-v">' + (a.char_generated || 0) + '</div>'
    + '<div class="kpi-n">缺口 ' + missChars.length + ' 个'
    + ((!a.char_generated && looseN) ? ' · <span class="dim">另有 ' + looseN + ' 张未归档（见散图）</span>' : '')
    + '</div></div>'
    + '<div class="kpi"><div class="kpi-k">场景资产</div><div class="kpi-v">' + (a.scene_generated || 0) + '</div>'
    + '<div class="kpi-n">缺口 ' + missScenes.length + ' 个</div></div>'
    + '<div class="kpi"><div class="kpi-k">本地出图产物</div><div class="kpi-v">' + (a.local_generated || 0) + '</div>'
    + '<div class="kpi-n">￥0 · 占 GPU</div></div>'
    + '</div>'

    + '<div class="tabs">'
    + TABS.map((t) => '<button class="tab' + (tab === t.key ? ' active' : '') + '" data-tab="' + t.key + '">'
      + t.label + '</button>').join('')
    + '<span class="spacer"></span>'
    /* 诊断不当分类：只有存在内容时才出现，避免「页签永远在那但永远空」 */
    + (looseN || tabDef(tab).key === 'refs' || tabDef(tab).key === 'loose'
      ? DIAG.map((t) => '<button class="tab sd-tab-diag' + (tab === t.key ? ' active' : '')
        + '" data-tab="' + t.key + '" title="' + esc(t.hint) + '">' + t.label + '</button>').join('')
      : '')
    + '<span class="tiny dim mono">'
    + (tab === 'loose'
      ? (items.length
        ? esc(items.length + ' 张 · ' + (dirDataFinal.groups || [])
          .map((g) => g.where.replace('（根目录）', '根目录') + ' ' + g.count).join(' · ') + (dirDataFinal.truncated ? ' · 仅显示前 ' + dirDataFinal.limit : ''))
        : '根目录 + 一层子目录（只读）')
      : esc(tabDef(tab).dir || '')) + '</span>'
    + '</div>'

    + (tab === 'characters' ? charRoster(roster) : '')

    + '<section class="card" style="margin-bottom:16px"><div class="card-b">'
    + '<div class="tile-grid">' + tiles + '</div></div>'
    + '<div class="card-foot">' + stamp('工作区目录清单 · 图片经 /media 直出（支持 Range）') + '</div></section>'

    + '<div class="grid g2">'
    + '<section class="card"><div class="card-h"><h3>角色缺口</h3><span class="card-sub">引擎判定</span></div>'
    + '<div class="card-b">' + (missChars.length
      ? missChars.map((n) => '<span class="chip" style="margin:0 6px 6px 0">' + esc(n) + '</span>').join('')
      : '<div class="dim small">没有缺口</div>') + '</div></section>'
    + '<section class="card"><div class="card-h"><h3>场景缺口</h3><span class="card-sub">引擎判定</span></div>'
    + '<div class="card-b">' + (missScenes.length
      ? missScenes.map((n) => '<span class="chip" style="margin:0 6px 6px 0">' + esc(n) + '</span>').join('')
      : '<div class="dim small">没有缺口</div>') + '</div></section>'
    + '</div>'

    + '<section class="card" style="margin-top:16px"><div class="card-h"><h3>出图前置与边界</h3>'
    + '<span class="card-sub">哪些由网页管，哪些必须你去处理</span></div>'
    + '<div class="card-b">'
    + '<div class="clitem"><span class="mk ' + (mdOk ? 'ok' : 'warn') + '">' + icon(mdOk ? 'check' : 'alert', 12)
    + '</span><div class="body"><div class="ttl"><span>资产提示词 md</span>'
    + (mdOk ? badge('ok', '已找到') : badge('warn', '缺失')) + '</div>'
    + '<div class="desc">' + (mdOk ? '<span class="mono">' + esc((md.items.find(
      (x) => x.path === md.suggested) || {}).rel || md.suggested) + '</span>'
      : '放到 <span class="mono">04-资产/</span> 或 <span class="mono">04-资产/design/</span>') + '</div></div></div>'
    + '<div class="clitem"><span class="mk warn">' + icon('cpu', 12) + '</span><div class="body">'
    + '<div class="ttl"><span>本地 ComfyUI</span>' + badge('outline', '￥0 · 占 GPU') + '</div>'
    + '<div class="desc">地址取「连接中心」（默认 127.0.0.1:8188）。先点「出图能力预检」——'
    + '它会核在线 + 节点类 + 模型文件，省掉「每张图各失败一次」。</div></div></div>'
    + '<div class="clitem"><span class="mk off">' + icon('close', 12) + '</span><div class="body">'
    + '<div class="ttl"><span>在线改提示词 / 参考图瘦身写盘</span>' + badge('muted', '未开放') + '</div>'
    + '<div class="desc">提示词改动请改 md 后重新出图；瘦身命令 <span class="mono">refs.apply</span> 会写盘，'
    + '本页只做体检。</div></div></div>'
    + '</div></section>';

  return {
    html,
    mount: (root) => {
      paintIcons(root);

      /* ---- 角色框：点文字 tab 换图（只换图片区，不重绘整页）---- */
      const flat = {};
      (roster.items || []).forEach((c) => {
        (c.variants || []).forEach((v) => { flat[c.id + '@' + v.code] = { c, v }; });
      });

      const showPrompt = (c, v) => {
        openModal({
          title: c.id + ' · ' + c.name + ' · ' + v.code,
          icon: 'image',
          html: '<div class="tiny dim" style="margin-bottom:10px">参考图 key：'
            + '<span class="mono">' + esc(c.id + '@' + v.code) + '</span>'
            + '（出片时按这个 key 取图）· 层别：' + esc(v.layer) + '</div>'
            + '<pre class="sd-md-code" style="max-height:44vh;overflow:auto;white-space:pre-wrap">'
            + esc(v.prompt) + '</pre>',
          foot: '<span class="spacer"></span>'
            + '<button class="btn quiet" id="cvCopy">' + icon('copy', 12) + ' 复制提示词</button>'
            + '<button class="btn quiet" data-close="modal">关闭</button>',
          mount: (m) => {
            const cp = m.querySelector('#cvCopy');
            if (cp) cp.onclick = async () => {
              try { await navigator.clipboard.writeText(v.prompt); toast('已复制提示词'); }
              catch (e) { toast('复制失败（浏览器限制）', 'warn'); }
            };
          }
        });
      };

      /* 初始：每个角色框先渲染「主形象」（没有主形象时渲染第一个有图的变体） */
      root.querySelectorAll('[data-card]').forEach((box) => {
        const cid = box.dataset.card;
        const c = (roster.items || []).find((x) => x.id === cid);
        if (!c) return;
        const stage = box.querySelector('[data-stage]');
        const first = (c.master && c.master.code)
          || (c.variants.find((v) => v.count) || {}).code;
        const v = (c.variants || []).find((x) => x.code === first) || c.variants[0];
        if (!v) return;
        renderVariantStage(stage, c, v);
        box.querySelectorAll('.sd-ctab').forEach((t) => {
          t.classList.toggle('on', t.dataset.cv === v.code);
        });
      });

      /* 点 tab：换图 + 换高亮。不刷新整页 —— 换一个变体就重绘整页，
         长列表会跳回顶部，那正是「查看」最忌讳的。 */
      root.querySelectorAll('.sd-ctab').forEach((t) => {
        t.onclick = () => {
          const cid = t.dataset.cid;
          const c = (roster.items || []).find((x) => x.id === cid);
          const v = c && (c.variants || []).find((x) => x.code === t.dataset.cv);
          if (!c || !v) return;
          const box = t.closest('[data-card]');
          const stage = box && box.querySelector('[data-stage]');
          renderVariantStage(stage, c, v);
          box.querySelectorAll('.sd-ctab').forEach((x) => x.classList.toggle('on', x === t));
        };
      });

      /* 图片区里的「看提示词」 */
      root.addEventListener('click', (ev) => {
        const b = ev.target.closest('[data-act]');
        if (!b || !b.dataset.act) return;
        const box = b.closest('[data-card]');
        const on = box && box.querySelector('.sd-ctab.on');
        if (!on) return;
        const hit = flat[on.dataset.cid + '@' + on.dataset.cv];
        if (!hit) return;
        if (b.dataset.act === 'prompt') showPrompt(hit.c, hit.v);
        else if (b.dataset.act === 'regen') regenVariant(ctx, root, hit.c, hit.v);
      });

      root.querySelectorAll('[data-tab]').forEach((b) => {
        b.onclick = () => {
          if (b.dataset.tab === tab) return;
          location.hash = '#/assets?tab=' + b.dataset.tab;
        };
      });
      root.querySelectorAll('[data-img]').forEach((el) => {
        el.onclick = () => {
          const url = mediaUrl(ctx.ws, el.dataset.img);
          openDrawer({
            title: el.dataset.name,
            html: '<div class="video-box"><img class="frame" alt="" src="' + esc(url) + '"></div>'
              + '<dl class="kv" style="margin-top:12px"><dt>相对路径</dt><dd class="mono">'
              + esc(el.dataset.img) + '</dd></dl>'
              + '<div class="tiny dim" style="margin-top:10px">图片为原始产物，未做缩略与转码。</div>',
            foot: '<span class="spacer"></span>'
              + '<a class="btn quiet" target="_blank" rel="noopener" href="' + esc(url) + '">新窗口打开</a>'
              + '<button class="btn quiet" data-close="drawer">关闭</button>',
            mount: (r) => paintIcons(r)
          });
        };
      });
      const chk = root.querySelector('#btnAssetCheck');
      if (chk) chk.onclick = () => runAction(ctx, {
        specId: 'assets.check',
        title: '出图器体检（ComfyUI 是否在线）',
        // 体检脚本也要求 SOLODRAMA_ASSET_MD：不传会误报成「ComfyUI 没开」
        params: { asset_md: (md && md.suggested) || '' }
      });
      const refs = root.querySelector('#btnRefsCheck');
      if (refs) refs.onclick = () => runAction(ctx, { specId: 'refs.report', title: '参考图体检（只读）' });

      // 参考图瘦身：超 H3 上限（5760px）的会被平台丢弃并导致画面错位。
      // 默认只体检；写盘要勾确认（会先备份再用新图替换）。
      const shrink = root.querySelector('#btnRefsShrink');
      if (shrink) shrink.onclick = () => openModal({
        title: '参考图瘦身',
        icon: 'download',
        html: '<div class="small">把长边超过 <b>5760px</b> 的参考图压到可上传范围'
          + '（默认长边 2048、JPEG q92），否则平台会直接丢弃、画面错位。</div>'
          + '<div class="cost-line" style="margin-top:8px"><span class="k">写盘</span>'
          + '<span class="v">覆盖/新增 <span class="mono">04-资产/refs*</span> 下的文件，会先备份</span></div>'
          + '<div class="cost-line"><span class="k">费用</span><span class="v">￥0（本机处理）</span></div>'
          + '<label class="chk" style="margin-top:10px"><input type="checkbox" id="rsCfg">'
          + '<span>同时把 characters.json 指到新目录（会先备份）</span></label>'
          + '<label class="chk" style="margin-top:6px"><input type="checkbox" id="rsOk">'
          + '<span>我确认要写盘（覆盖现有参考图）</span></label>'
          + '<div class="alert info" style="margin-top:10px"><span class="nav-ico">' + icon('alert', 14)
          + '</span><div>建议先点「只体检」看一眼：哪些越界、压缩后多少 KB，再决定写不写。</div></div>',
        foot: '<span class="spacer"></span><button class="btn quiet" data-close="modal">取消</button>'
          + '<button class="btn quiet" id="rsDry">只体检</button>'
          + '<button class="btn primary" id="rsGo" disabled>瘦身并写盘</button>',
        mount: (m) => {
          const ok = m.querySelector('#rsOk');
          const go = m.querySelector('#rsGo');
          ok.onchange = () => { go.disabled = !ok.checked; };
          m.querySelector('#rsDry').onclick = () => {
            m.querySelector('#modal').classList.remove('on');
            runAction(ctx, { specId: 'refs.apply', title: '参考图瘦身 · 只体检',
                             params: { apply: false } });
          };
          go.onclick = () => {
            const cfg = !!(m.querySelector('#rsCfg') || {}).checked;
            m.querySelector('#modal').classList.remove('on');
            runAction(ctx, {
              specId: 'refs.apply', title: '参考图瘦身 · 写盘',
              params: { apply: true, write_config: cfg },
              onDone: () => setTimeout(() => ctx.refresh(), 1200)
            });
          };
        }
      });
      const gen = root.querySelector('#btnGen');
      if (gen) gen.onclick = () => openGenPanel(ctx, md);
    }
  };
}

/* ---------- 出图面板 ---------- */
function openGenPanel(ctx, md) {
  const cands = (md && md.items) || [];
  const mdOpts = (cands.length
    ? cands.map((c) => '<option value="' + esc(c.path) + '"'
      + (c.path === (md.suggested || '') ? ' selected' : '') + '>' + esc(c.rel) + '</option>').join('')
    : '<option value="">（没找到，请先在 04-资产/ 放一份提示词 md）</option>');

  openDrawer({
    title: '资产出图',
    html: '<div class="stack">'
      + '<div class="field"><label class="tiny dim">通道</label>'
      + '<div class="row-gap">'
      + '<label class="chk"><input type="radio" name="gEng" value="local" checked>'
      + '<span>本地 ComfyUI（￥0，占 GPU 数分钟）</span></label>'
      + '<label class="chk"><input type="radio" name="gEng" value="cloud">'
      + '<span>云端 ComfyUI 镜像（<b>★计费</b>，按主机时长）</span></label>'
      + '<label class="chk"><input type="radio" name="gEng" value="rh">'
      + '<span>云端 RunningHub（<b>★计费</b>，按张结算）</span></label>'
      + '</div></div>'

      + '<div class="field"><label class="tiny dim">资产提示词 md（引擎只认环境变量 SOLODRAMA_ASSET_MD）</label>'
      + '<select class="select" id="gMd">' + mdOpts + '</select>'
      + '<div class="tiny dim" style="margin-top:4px">' + esc((md && md.note) || '') + '</div></div>'

      + '<div class="grid g2">'
      + '<div class="field"><label class="tiny dim">类型</label>'
      + '<select class="select" id="gKind"><option value="all">全部</option>'
      + '<option value="char">只人物</option><option value="scene">只场景</option>'
      + '<option value="prop">只道具（仅本地）</option></select></div>'
      + '<div class="field"><label class="tiny dim">只做这些（可空）</label>'
      + '<input class="input" id="gOnly" placeholder="char_01,char_02"></div></div>'

      + '<label class="chk"><input type="checkbox" id="gForce">'
      + '<span>已生成的也重跑（会重复占 GPU）</span></label>'

      + '<div class="alert info"><span class="nav-ico">' + icon('alert', 14) + '</span><div>'
      + '三条通道都是<b>后台作业</b>：提交后到「任务中心」看实时日志。'
      + '本机通道先点「出图能力预检」——它会核在线/节点/模型，能省掉「每张图各失败一次」。</div></div>'
      + '</div>',
    foot: '<span class="spacer"></span>'
      + '<button class="btn quiet" data-close="drawer">取消</button>'
      + '<button class="btn quiet" id="gDry">干跑（不占 GPU）</button>'
      + '<button class="btn primary" id="gRun">开始出图</button>',
    mount: (root) => {
      paintIcons(root);
      const val = (sel) => {
        const el = root.querySelector(sel);
        return el ? el.value : '';
      };
      const checked = (sel) => {
        const el = root.querySelector(sel);
        return !!(el && el.checked);
      };
      // 两条通道：本地是默认，云端要显式选（选了才知道会花钱）。
      const engine = () => {
        const r = root.querySelector('input[name="gEng"]:checked');
        return r ? r.value : 'local';
      };
      // ★ 三条通道对应三个**不同命令**。此前只有「rh 或 其他」两分支，
      //   于是云端镜像根本选不出来 —— 界面能看到通道页说「云端可用」，这里却跑不了。
      const SPEC_OF = { local: 'assets.local', cloud: 'assets.cloud', rh: 'assets.rh_wf' };
      const TITLE_OF = { local: '本地出图', cloud: '云端镜像出图', rh: '云端工作流出图' };
      // 资产提示词：本地走环境变量（asset_md），云端走 CLI 参数（md）。两个键都给，
      // 多出来的会被命令校验忽略。
      const params = (submit) => {
        const md = val('#gMd');
        return {
          kind: val('#gKind') || 'all',
          only: (val('#gOnly') || '').trim(),
          force: checked('#gForce'),
          submit,
          md,
          asset_md: md
        };
      };

      root.querySelector('#gDry').onclick = () => {
        const p = params(false);
        closeDrawer();
        const eng = engine();
        doRun(ctx, {
          specId: SPEC_OF[eng] || 'assets.local',
          title: TITLE_OF[eng] + ' · 干跑（列出清单，不提交）',
          params: p,
          onDone: () => setTimeout(() => ctx.refresh(), 1200)
        });
      };

      root.querySelector('#gRun').onclick = () => {
        const p = params(true);
        const eng = engine();
        if (!p.asset_md) {
          toast('先选「资产提示词 md」，否则引擎会报未设置 SOLODRAMA_ASSET_MD', 'bad');
          return;
        }
        if (eng === 'local') {
          openModal({
            title: '本地出图（占 GPU）',
            icon: 'cpu',
            html: '<div class="small">会调用本机 ComfyUI 出图，<b>不花钱但占 GPU</b>（通常几分钟）。'
              + '<div class="tiny dim" style="margin-top:8px">类型：' + esc(p.kind)
              + (p.only ? ' · 只做 ' + esc(p.only) : '') + '</div>'
              + (p.force ? '<div class="tiny dim">已生成的会重跑</div>' : '') + '</div>'
              + '<div class="alert info" style="margin-top:10px"><span class="nav-ico">' + icon('alert', 14)
              + '</span><div>前提：ComfyUI 已启动（地址取「连接中心」，不再写死 8188）。'
              + '开跑前会自动做生成能力预检。</div></div>',
            foot: '<span class="spacer"></span><button class="btn quiet" data-close="modal">取消</button>'
              + '<button class="btn primary" id="gOk">开始</button>',
            mount: (m) => {
              m.querySelector('#gOk').onclick = () => {
                closeModal(); closeDrawer();
                doRun(ctx, {
                  specId: 'assets.local', title: '本地出图（真跑）', params: p,
                  onDone: () => setTimeout(() => ctx.refresh(), 1500)
                });
              };
            }
          });
        } else if (eng === 'cloud') {
          // ★ 云端镜像：计费口径与 RH 完全不同 —— 是按**主机时长**，不是按张。
          //   写成「按张结算」会让人以为「少出几张就少花钱」，其实机器开着就在烧。
          closeDrawer();
          runAction(ctx, {
            specId: 'assets.cloud',
            title: '云端镜像出图（★按主机时长）',
            params: p,
            costTitle: '云端镜像出图（按主机时长计费）',
            cost: {
              lines: [
                ['通道', '云端 ComfyUI 镜像（自建/租用实例）'],
                ['类型', p.kind + (p.only ? ' · 只做 ' + p.only : '')],
                ['计费', '按实例开机时长结算（以云平台账单为准），与出几张无关'],
                ['合计', '出图时长 × 平台单价（以账单为准）；地址取模型确认单，缺地址会直接停']
              ],
              note: '跑完请确认实例已停（任务默认自动停，只停自己开的）；台账可在「成本」页看。'
            },
            onDone: () => setTimeout(() => ctx.refresh(), 1500)
          });
        } else {
          // ★ RH 通道：先看计费单，不直接跑。这里不是唠叨 ——
          //   资产图一次几十张，单价乘以张数就是真金白银。
          closeDrawer();
          runAction(ctx, {
            specId: 'assets.rh_wf',
            title: '云端工作流出图（★计费）',
            params: p,
            costTitle: '云端出图（按张计费）',
            cost: {
              lines: [
                ['通道', 'RunningHub 云端'],
                ['类型', p.kind + (p.only ? ' · 只做 ' + p.only : '')],
                ['计费', '按张结算（RunningHub 工作流），以平台实际用量为准'],
                ['合计', '张数 × 平台单价（以账单为准）；干跑会先给出清单']
              ],
              note: '提交后不可撤回；已生成的资产若勾了「重跑」会重复计费。'
            },
            onDone: () => setTimeout(() => ctx.refresh(), 1500)
          });
        }
      };
    }
  });
}
