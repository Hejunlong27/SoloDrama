/* ============================================================
   AI 模型中心：提供商 / 用途路由 / 提示词模板 / 调用记录
   纪律：
     * 这里只管「配置与观测」，不在这里跑创作——创作在创作中心；
     * Key 只进不出：表单里只有「新 Key」输入框，读回来永远只有打码状态；
     * 连接测试默认只读模型列表（0 费用）；「最小生成测试」要单独勾选并二次确认。
   ============================================================ */
import { api } from '../api.js';
import { S } from '../store.js';
import {
  esc, icon, badge, dt, toast, openDrawer, closeDrawer, closeModal, openModal,
  paintIcons, stamp, emptyBox, kv, confirmCost, skeleton
} from '../ui.js';

const TABS = [
  { key: 'providers', label: '提供商' },
  { key: 'purposes', label: '用途路由' },
  { key: 'templates', label: '提示词模板' },
  { key: 'usage', label: '调用记录' }
];

/* 页签放在 URL 里（#/models?tab=purposes）：刷新、后退、分享链接都不会丢当前页签 */
function currentTab() {
  const m = String(location.hash || '').match(/[?&]tab=([a-z]+)/);
  const k = m ? m[1] : 'providers';
  return TABS.some((t) => t.key === k) ? k : 'providers';
}

export async function render(ctx) {
  const tab = currentTab();
  const [meta, provs, purposes, tpls] = await Promise.all([
    api.llmMeta().catch((e) => ({ error: e })),
    api.llmProviders().catch((e) => ({ error: e, items: [] })),
    api.llmPurposes().catch(() => ({ items: [] })),
    api.llmTemplates().catch(() => ({ items: [] }))
  ]);
  if (meta.error) {
    return {
      html: '<div class="page-head"><div><h1 class="page-title">AI 模型中心</h1></div></div>'
        + '<div class="card"><div class="card-b"><div class="alert bad"><span class="nav-ico">'
        + icon('alert', 14) + '</span><div>读取 LLM 配置失败：' + esc(meta.error.detail || meta.error.message)
        + '</div></div></div></div>'
    };
  }

  const providers = provs.items || [];
  const plist = purposes.items || [];
  const ready = plist.filter((p) => p.ready).length;

  const tabsHtml = '<div class="tabs" id="llmTabs">' + TABS.map((t) => (
    '<button class="tab' + (t.key === tab ? ' active' : '') + '" data-tab="' + t.key + '">'
    + esc(t.label)
    + (t.key === 'providers' ? '<span class="count">' + providers.length + '</span>' : '')
    + (t.key === 'purposes' ? '<span class="count">' + ready + '/' + plist.length + '</span>' : '')
    + '</button>'
  )).join('') + '</div>';

  const body = tab === 'providers' ? providersTab(providers, meta)
    : tab === 'purposes' ? purposesTab(plist, providers)
      : tab === 'templates' ? templatesTab(tpls.items || [])
        : '<div id="usageBox"><div class="card"><div class="card-b">' + skeleton(1) + '</div></div></div>';

  const html = ''
    + '<div class="page-head"><div>'
    + '<h1 class="page-title">AI 模型中心</h1>'
    + '<div class="page-sub">统一网关：OpenAI 兼容 / 本地 Ollama；Key 只存后端，接口只回打码状态</div></div>'
    + '<div class="page-actions">'
    + (tab === 'providers' ? '<button class="btn primary" id="btnNewProv">' + icon('plus', 14) + ' 新建提供商</button>' : '')
    + '<button class="btn quiet" id="btnLlmRefresh">' + icon('refresh', 14) + ' 重新读取</button>'
    + '</div></div>'

    + '<div class="grid g4" style="margin-bottom:14px">'
    + kpi('已配置提供商', String(providers.length), providers.length ? '可用 ' + providers.filter((p) => p.enabled).length + ' 个' : '还没有配置')
    + kpi('已绑定用途', ready + ' / ' + plist.length, ready ? '可直接调用' : '先绑定提供商')
    + kpi('提示词模板', String((tpls.items || []).length), '来自仓库 stages/creation/prompts')
    + kpi('调用存储', '本机', (meta.store_dir || '').split(/[\\/]/).slice(-2).join('/'))
    + '</div>'

    + (S.readonly ? '<div class="alert warn" style="margin-bottom:12px"><span class="nav-ico">' + icon('lock', 14)
      + '</span><div>当前是<b>只读模式</b>（SOLODRAMA_CONSOLE_READONLY=1）：可以查看，不能新建/修改/测试。</div></div>' : '')
    + (meta.provider_count === 0 ? '<div class="alert info" style="margin-bottom:12px"><span class="nav-ico">'
      + icon('alert', 14) + '</span><div>还没有任何模型配置。点「新建提供商」——本地 Ollama 不需要云端 Key；'
      + '云端可填 OpenAI / DeepSeek / 任意 <span class="mono">/chat/completions</span> 兼容端点。</div></div>' : '')

    + tabsHtml
    + body
    + '<div class="card" style="margin-top:14px"><div class="card-foot">'
    + stamp('web/var/llm/config.json · 调用记录 web/var/llm/usage.jsonl')
    + '</div></div>';

  return {
    html,
    mount: (root) => {
      paintIcons(root);
      root.querySelectorAll('[data-tab]').forEach((b) => {
        b.onclick = () => {
          if (b.dataset.tab === tab) return;
          location.hash = '#/models?tab=' + b.dataset.tab;
        };
      });
      const rf = root.querySelector('#btnLlmRefresh');
      if (rf) rf.onclick = () => ctx.refresh();

      const np = root.querySelector('#btnNewProv');
      if (np) np.onclick = () => openProviderForm(ctx, meta, null);

      root.querySelectorAll('[data-test]').forEach((b) => {
        b.onclick = () => testProvider(ctx, b.dataset.test, b);
      });
      root.querySelectorAll('[data-edit]').forEach((b) => {
        b.onclick = () => {
          const p = providers.find((x) => x.id === b.dataset.edit);
          openProviderForm(ctx, meta, p);
        };
      });
      root.querySelectorAll('[data-toggle]').forEach((b) => {
        b.onclick = () => toggleProvider(ctx, providers.find((x) => x.id === b.dataset.toggle));
      });
      root.querySelectorAll('[data-remove]').forEach((b) => {
        b.onclick = () => removeProvider(ctx, b.dataset.remove);
      });

      root.querySelectorAll('[data-preset]').forEach((b) => {
        b.onclick = () => {
          const pre = (meta.presets || []).find((x) => x.id === b.dataset.preset);
          openProviderForm(ctx, meta, pre ? Object.assign({}, pre, { id: '' }) : null);
        };
      });

      root.querySelectorAll('[data-psave]').forEach((b) => {
        b.onclick = () => savePurpose(ctx, root, b.dataset.psave);
      });
      root.querySelectorAll('[data-pbest]').forEach((b) => {
        b.onclick = () => savePurpose(ctx, root, b.dataset.pbest, true);
      });
      root.querySelectorAll('[data-view-tpl]').forEach((b) => {
        b.onclick = () => viewTemplate(b.dataset.viewTpl);
      });

      if (tab === 'usage') loadUsage(root);
    }
  };
}

function kpi(k, v, note) {
  return '<div class="kpi"><div class="kpi-k">' + esc(k) + '</div><div class="kpi-v">' + esc(v) + '</div>'
    + '<div class="kpi-n">' + esc(note || '') + '</div></div>';
}

/* ---------- 提供商 ---------- */
function providersTab(providers, meta) {
  if (!providers.length) {
    const presets = (meta.presets || []).map((p) => (
      '<button class="btn quiet" data-preset="' + esc(p.id) + '">' + esc(p.name) + '</button>'
    )).join('');
    return '<div class="card"><div class="card-b">'
      + emptyBox('还没有配置任何模型端点',
        '提供商就是「协议 + 地址 + 模型」。Key 只写后端，不会出现在页面或日志里。',
        '<div class="row" style="margin-top:12px;justify-content:center">' + presets + '</div>'
        + '<div class="tiny dim" style="margin-top:10px;text-align:center">'
        + '预置只是表单初值，保存后才会真正生效</div>')
      + '</div></div>';
  }
  const cards = providers.map((p) => {
    const kt = p.key_source === 'env' ? badge('info', '环境变量 ' + (p.env_var || ''))
      : p.key_source === 'file' ? badge('ok', '本机已保存 ' + p.key_hint)
        : badge('muted', '无 Key' + (p.local ? '（本地服务）' : ''));
    const lt = p.last_test
      ? '<span class="tiny ' + (p.last_test.ok ? 'muted' : 'dim') + '">上次测试：'
        + (p.last_test.ok ? '通过' : '失败 · ' + esc(p.last_test.kind || ''))
        + ' · ' + esc(dt(p.last_test.at)) + '</span>'
      : '<span class="tiny dim">还没测试过</span>';
    const caps = (p.capabilities || []).map((c) => badge('outline', c)).join(' ');
    return '<section class="card" style="margin-bottom:12px">'
      + '<div class="card-h">' + '<i class="dot ' + (p.enabled ? 'done' : 'todo') + '"></i>'
      + '<h3>' + esc(p.name) + '</h3>'
      + badge('outline', p.kind_text || p.kind)
      + (p.kind === 'mock' ? badge('warn', '演练通道', '不调用任何模型，输出带 simulated 标记，不能写进正式剧本') : '')
      + (p.enabled ? '' : badge('muted', '已停用'))
      + '<span class="spacer"></span>'
      + '<button class="btn quiet sm" data-test="' + esc(p.id) + '">测试连接</button>'
      + '<button class="btn quiet sm" data-edit="' + esc(p.id) + '">编辑</button>'
      + '<button class="btn quiet sm" data-toggle="' + esc(p.id) + '">' + (p.enabled ? '停用' : '启用') + '</button>'
      + '<button class="btn quiet sm" data-remove="' + esc(p.id) + '">删除</button>'
      + '</div>'
      + '<div class="card-b">'
      + kv([
        ['端点', p.base_url || '—', true],
        ['默认模型', p.default_model || '—', true],
        ['可选模型', (p.models || []).join('、') || '—', true],
        ['超时 / 重试', (p.timeout_s || 60) + ' 秒 / ' + (p.max_retries || 0) + ' 次'],
        ['本地服务', p.local ? '是（允许内网地址）' : '否']
      ])
      + '<div class="row gap8" style="margin-top:10px;flex-wrap:wrap">' + kt + caps + '</div>'
      + '<div style="margin-top:8px">' + lt + '</div>'
      + '</div></section>';
  }).join('');

  return '<div>' + cards
    + '<div class="alert info"><span class="nav-ico">' + icon('lock', 14) + '</span><div>'
    + 'Key 的读取顺序：<b>环境变量</b>（推荐，进程外管理）→ <b>本机保险箱</b>'
    + '<span class="mono"> web/var/llm/keys.json</span>。两种方式都不会把明文返回给浏览器。</div></div></div>';
}

function openProviderForm(ctx, meta, prov) {
  const isNew = !prov || !prov.id;
  const p = prov || {};
  const kinds = Object.keys(meta.kinds || {}).map((k) => (
    '<option value="' + esc(k) + '"' + (p.kind === k || (!p.kind && k === 'openai') ? ' selected' : '') + '>'
    + esc(meta.kinds[k]) + '</option>'
  )).join('');
  const caps = Object.keys(meta.capabilities || {}).map((c) => (
    '<label class="chk" title="' + esc(meta.capabilities[c]) + '"><input type="checkbox" value="' + esc(c) + '"'
    + ((p.capabilities || ['json']).indexOf(c) >= 0 ? ' checked' : '') + '><span>' + esc(c) + '</span></label>'
  )).join('');

  openDrawer({
    title: isNew ? '新建提供商' : '编辑：' + (p.name || p.id),
    html: ''
      + '<div class="stack">'
      + field('ident', '标识（留空自动生成）', '<input class="input" id="fId" value="'
        + esc(p.id || '') + '"' + (isNew ? '' : ' readonly') + ' placeholder="如 deepseek">')
      + field('name', '显示名称', '<input class="input" id="fName" value="' + esc(p.name || '') + '" placeholder="如 DeepSeek">')
      + field('kind', '协议', '<select class="select" id="fKind">' + kinds + '</select>')
      + field('url', 'Base URL',
        '<input class="input" id="fUrl" value="' + esc(p.base_url || '') + '" placeholder="https://api.deepseek.com/v1">')
      + field('model', '默认模型 ID', '<input class="input" id="fModel" value="'
        + esc(p.default_model || '') + '" placeholder="deepseek-chat">')
      + field('models', '可选模型（每行一个）',
        '<textarea class="textarea" id="fModels" rows="3">' + esc((p.models || []).join('\n')) + '</textarea>')
      + field('caps', '模型能力', '<div class="row gap8" style="flex-wrap:wrap">' + caps + '</div>')
      + field('key', 'API Key', '<input class="input" id="fKey" type="password" autocomplete="new-password" placeholder="'
        + (isNew ? '可留空（稍后用环境变量）' : (p.has_key ? '已有 Key（' + p.key_hint + '），留空表示不修改' : '未设置'))
        + '"><div class="tiny dim" style="margin-top:4px">只写后端；前端永远读不回来。'
        + (p.has_key ? ' 勾选下面「清除已保存的 Key」可删除。' : '') + '</div>'
        + (p.has_key ? '<label class="chk" style="margin-top:6px"><input type="checkbox" id="fClearKey">'
          + '<span>清除已保存的 Key</span></label>' : ''))
      + field('env', '环境变量名（可选）', '<input class="input" id="fEnv" value="' + esc(p.env_var || '')
        + '" placeholder="如 DEEPSEEK_API_KEY">')
      + '<div class="grid g2">'
      + field('timeout', '超时（秒）', '<input class="input" id="fTmo" type="number" min="5" max="600" value="'
        + esc(String(p.timeout_s || 60)) + '">')
      + field('retries', '重试次数（仅网络/超时/限流）', '<input class="input" id="fRetry" type="number" min="0" max="3" value="'
        + esc(String(p.max_retries == null ? 1 : p.max_retries)) + '">')
      + '</div>'
      + '<label class="chk"><input type="checkbox" id="fLocal"' + (p.local ? ' checked' : '') + '>'
      + '<span>这是本地服务（允许 127.0.0.1 / 内网地址；不需要云端 Key）</span></label>'
      + '<label class="chk"><input type="checkbox" id="fProxy"'
      + ((p.trust_env === false || (p.local && p.trust_env == null)) ? '' : ' checked') + '>'
      + '<span>走系统代理（HTTP_PROXY / HTTPS_PROXY）—— 本机需要代理才能出网时勾选</span></label>'
      + '<label class="chk"><input type="checkbox" id="fEnabled"' + (p.enabled === false ? '' : ' checked') + '>'
      + '<span>启用</span></label>'
      + '<div class="alert info"><span class="nav-ico">' + icon('alert', 14) + '</span><div>'
      + '保存时会校验地址：只允许 http/https，且不带用户名口令；云元数据地址一律拒绝。</div></div>'
      + '</div>',
    foot: '<span class="spacer"></span>'
      + '<button class="btn quiet" data-close="drawer">取消</button>'
      + '<button class="btn primary" id="fSave">保存</button>',
    mount: (root) => {
      paintIcons(root);
      const loc = root.querySelector('#fLocal');
      const prx = root.querySelector('#fProxy');
      if (loc && prx) {
        loc.onchange = () => { if (loc.checked) prx.checked = false; };
      }
      const save = root.querySelector('#fSave');
      save.onclick = async () => {
        const capsSel = [].map.call(root.querySelectorAll('.chk input[type=checkbox][value]'), (c) => c)
          .filter((c) => c.checked).map((c) => c.value);
        const body = {
          id: (root.querySelector('#fId').value || '').trim(),
          name: (root.querySelector('#fName').value || '').trim(),
          kind: root.querySelector('#fKind').value,
          base_url: (root.querySelector('#fUrl').value || '').trim(),
          default_model: (root.querySelector('#fModel').value || '').trim(),
          models: (root.querySelector('#fModels').value || '').split('\n'),
          capabilities: capsSel,
          env_var: (root.querySelector('#fEnv').value || '').trim(),
          timeout_s: root.querySelector('#fTmo').value,
          max_retries: root.querySelector('#fRetry').value,
          local: root.querySelector('#fLocal').checked,
          trust_env: root.querySelector('#fProxy').checked,
          enabled: root.querySelector('#fEnabled').checked,
          ws: ctx.ws
        };
        const k = root.querySelector('#fKey').value;
        if (k) body.api_key = k;
        if (root.querySelector('#fClearKey') && root.querySelector('#fClearKey').checked) body.clear_key = true;

        save.disabled = true;
        save.innerHTML = '<span class="spinner"></span>保存中';
        try {
          await api.llmSaveProvider(body);
          closeDrawer();
          toast('已保存');
          ctx.refresh();
        } catch (e) {
          const d = e.detail || e.message;
          toast('保存失败：' + (typeof d === 'string' ? d : (d && d.message) || '参数不合法'), 'bad');
        } finally {
          save.disabled = false;
          save.textContent = '保存';
        }
      };
    }
  });
}

function field(id, label, inner) {
  return '<div class="field"><label class="tiny dim" for="f' + esc(id) + '">' + esc(label) + '</label>'
    + inner + '</div>';
}

async function testProvider(ctx, pid, btn) {
  btn.disabled = true;
  const old = btn.textContent;
  btn.innerHTML = '<span class="spinner"></span>测试中';
  try {
    const r = await api.llmTestProvider(pid, false, false);
    if (r.ok) {
      toast('连接正常：' + (r.model_count != null ? r.model_count + ' 个模型' : r.sample || ''), 'ok');
    } else {
      toast('连接失败（' + (r.kind || '未知') + '）：' + (r.message || ''), 'bad');
    }
    ctx.refresh();
  } catch (e) {
    const d = e.detail;
    if (e.status === 428) {
      openModal({
        title: '需要确认',
        html: '<div class="small">' + esc((d && d.reason) || '该操作需要确认') + '</div>',
        foot: '<span class="spacer"></span><button class="btn quiet" data-close="modal">取消</button>'
          + '<button class="btn primary" id="deepOk">继续</button>',
        mount: (m) => {
          m.querySelector('#deepOk').onclick = () => { closeModal(); deepTest(pid, ctx); };
        }
      });
    } else {
      toast('测试失败：' + (typeof d === 'string' ? d : (d && d.message) || e.message), 'bad');
    }
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}

function deepTest(pid, ctx) {
  confirmCost({
    title: '最小生成测试（会产生真实调用）',
    lines: [['动作', '向该端点发一次 1 token 级生成'], ['费用', '由供应商结算，本页不预估']],
    note: '这一步会真的调用模型。只想验证地址与鉴权时，用「测试连接」就够了（只读模型列表，0 费用）。',
    onOk: async () => {
      try {
        const r = await api.llmTestProvider(pid, true, true);
        toast(r.ok ? '生成测试通过' : '生成测试失败：' + (r.message || ''), r.ok ? 'ok' : 'bad');
        ctx.refresh();
      } catch (e) {
        toast('测试失败：' + (e.detail || e.message), 'bad');
      }
    }
  });
}

async function toggleProvider(ctx, p) {
  if (!p) return;
  try {
    await api.llmSaveProvider({ id: p.id, name: p.name, kind: p.kind, base_url: p.base_url,
      default_model: p.default_model, models: p.models, capabilities: p.capabilities,
      env_var: p.env_var, timeout_s: p.timeout_s, max_retries: p.max_retries,
      local: p.local, enabled: !p.enabled, ws: ctx.ws });
    toast(p.enabled ? '已停用' : '已启用');
    ctx.refresh();
  } catch (e) {
    toast('操作失败：' + (e.detail || e.message), 'bad');
  }
}

function removeProvider(ctx, pid) {
  openModal({
    title: '删除提供商',
    icon: 'alert',
    tone: 'bad',
    html: '<div class="small">删除后：<b>该提供商的 Key 会被清除</b>，引用它的用途会解除绑定。'
      + '已经产生的调用记录不会删除。</div>',
    foot: '<span class="spacer"></span><button class="btn quiet" data-close="modal">取消</button>'
      + '<button class="btn primary" id="delOk">删除</button>',
    mount: (m) => {
      m.querySelector('#delOk').onclick = async () => {
        closeModal();
        try { await api.llmDeleteProvider(pid); toast('已删除'); ctx.refresh(); }
        catch (e) { toast('删除失败：' + (e.detail || e.message), 'bad'); }
      };
    }
  });
}

/* ---------- 用途路由 ---------- */
function purposesTab(purposes, providers) {
  if (!purposes.length) return '<div class="card"><div class="card-b">' + emptyBox('没有用途定义', '') + '</div></div>';
  const opts = (sel) => '<option value="">（未绑定）</option>' + providers.map((p) => (
    '<option value="' + esc(p.id) + '"' + (sel === p.id ? ' selected' : '') + '>'
    + esc(p.name) + (p.enabled ? '' : '（停用）') + '</option>'
  )).join('');

  const rows = purposes.map((p) => {
    const prov = providers.find((x) => x.id === p.provider_id);
    const models = (prov && (prov.models || []).length ? prov.models : [p.model]).filter(Boolean);
    const mopts = models.map((m) => '<option value="' + esc(m) + '"'
      + (m === p.model ? ' selected' : '') + '>' + esc(m) + '</option>').join('');
    return '<tr data-row="' + esc(p.id) + '">'
      + '<td><div class="small">' + esc(p.label) + '</div>'
      + '<div class="tiny dim mono">' + esc(p.id) + '</div></td>'
      + '<td class="small muted">' + esc(p.hint || '') + '<div class="tiny dim">需要：'
      + esc((p.requires || []).join('、') || '无特殊能力') + '</div></td>'
      + '<td><select class="select" data-pprov="' + esc(p.id) + '">' + opts(p.provider_id) + '</select></td>'
      + '<td><select class="select" data-pmodel="' + esc(p.id) + '">'
      + (mopts || '<option value="">—</option>') + '</select></td>'
      + '<td>' + (p.ready ? badge('ok', '就绪') : (p.bound ? badge('warn', '提供商已停用') : badge('muted', '未绑定')))
      + '</td>'
      + '<td><button class="btn quiet sm" data-psave="' + esc(p.id) + '">保存</button>'
      + (prov && prov.default_model && p.model !== prov.default_model
        ? ' <button class="btn quiet sm" data-pbest="' + esc(p.id) + '" title="改用默认模型">用默认</button>' : '')
      + '</td></tr>';
  }).join('');

  return '<section class="card"><div class="card-h"><h3>用途路由</h3>'
    + '<span class="card-sub">不同用途可以用不同模型；能力不满足时网关会拒发请求</span></div>'
    + '<div class="card-b tight"><div class="table-wrap"><table class="tb"><thead><tr>'
    + '<th style="width:200px">用途</th><th>说明</th><th style="width:180px">提供商</th>'
    + '<th style="width:170px">模型</th><th style="width:90px">状态</th><th style="width:120px"></th>'
    + '</tr></thead><tbody>' + rows + '</tbody></table></div></div>'
    + '<div class="card-foot"><span class="tiny dim">绑定后即可在「创作中心」用该用途生成剧本正文；'
    + '未绑定时接口会明确报「还没有绑定提供商」，不会静默失败。</span></div></section>';
}

async function savePurpose(ctx, root, pid, useDefault) {
  const provSel = root.querySelector('[data-pprov="' + pid + '"]');
  const modelSel = root.querySelector('[data-pmodel="' + pid + '"]');
  const body = { provider_id: provSel ? provSel.value : '' };
  if (!useDefault && modelSel && modelSel.value) body.model = modelSel.value;
  if (useDefault) body.model = '';
  try {
    await api.llmSavePurpose(pid, body);
    toast('已保存路由');
    ctx.refresh();
  } catch (e) {
    const d = e.detail;
    toast('保存失败：' + (typeof d === 'string' ? d : (d && d.message) || e.message), 'bad');
  }
}

/* ---------- 模板 ---------- */
function templatesTab(items) {
  if (!items.length) return '<div class="card"><div class="card-b">' + emptyBox('没有模板', '') + '</div></div>';
  const rows = items.map((t) => (
    '<tr><td><div class="small">' + esc(t.title) + '</div>'
    + '<div class="tiny dim mono">' + esc(t.id) + '</div></td>'
    + '<td class="mono small">' + esc(t.purpose) + '</td>'
    + '<td>' + badge('outline', t.version) + '</td>'
    + '<td class="mono small">' + esc(t.schema_id || '（无 Schema）') + '</td>'
    + '<td class="tiny dim">' + esc((t.vars || []).join('、')) + '</td>'
    + '<td class="mono tiny dim">' + esc(t.body_sha || '—') + '</td>'
    + '<td><button class="btn quiet sm" data-view-tpl="' + esc(t.id) + '">查看正文</button></td></tr>'
  )).join('');
  return '<section class="card"><div class="card-h"><h3>提示词模板</h3>'
    + '<span class="card-sub">正文直接来自仓库 stages/creation/prompts，本页不另写一套</span></div>'
    + '<div class="card-b tight"><div class="table-wrap"><table class="tb"><thead><tr>'
    + '<th style="width:230px">模板</th><th>用途</th><th style="width:70px">版本</th>'
    + '<th style="width:170px">输出 Schema</th><th style="width:230px">输入变量</th>'
    + '<th style="width:120px">指纹</th><th style="width:110px"></th>'
    + '</tr></thead><tbody>' + rows + '</tbody></table></div></div>'
    + '<div class="card-foot"><span class="tiny dim">指纹变化说明仓库里的提示词被改过——'
    + '改动会立刻影响生成结果，改前先跑离线测试。</span></div></section>';
}

async function viewTemplate(tid) {
  try {
    const t = await api.llmTemplate(tid);
    openDrawer({
      title: t.title + ' · ' + t.version,
      html: '<div class="stack">'
        + kv([['用途', t.purpose || '—', true], ['文件', t.file || '—', true],
          ['输出', t.schema_id || '无 Schema（人工复核）'], ['指纹', t.body_sha, true]])
        + '<div class="tiny dim">' + esc(t.body_lines) + ' 行 · 输入变量：' + esc((t.vars || []).join('、')) + '</div>'
        + '<pre class="log" style="max-height:60vh;white-space:pre-wrap">' + esc(t.body || '') + '</pre>'
        + '</div>',
      foot: '<span class="spacer"></span><button class="btn quiet" data-close="drawer">关闭</button>',
      mount: (root) => paintIcons(root)
    });
  } catch (e) {
    toast('读取模板失败：' + (e.detail || e.message), 'bad');
  }
}

/* ---------- 调用记录 ---------- */
async function loadUsage(root) {
  const box = root.querySelector('#usageBox');
  if (!box) return;
  try {
    const d = await api.llmUsage(100);
    const s = d.summary || {};
    const rows = (d.items || []).map((r) => {
      const u = r.usage || {};
      const c = r.cost || {};
      const money = (c.usd == null) ? '<span class="dim">未知</span>' : ('$' + c.usd);
      return '<tr>'
        + '<td class="mono tiny dim" style="width:120px">' + esc(dt(r.at)) + '</td>'
        + '<td class="mono small">' + esc(r.purpose || '—') + '</td>'
        + '<td class="small muted">' + esc(r.provider_name || r.provider || '—')
        + '<div class="tiny dim mono">' + esc(r.model || '') + '</div></td>'
        + '<td>' + (r.ok ? badge('ok', '成功') : badge('bad', esc(r.error_kind || '失败')))
        + (r.simulated ? ' ' + badge('muted', '演练') : '') + '</td>'
        + '<td class="num">' + esc(u.input_tokens == null ? '—' : u.input_tokens) + '</td>'
        + '<td class="num">' + esc(u.output_tokens == null ? '—' : u.output_tokens) + '</td>'
        + '<td class="num">' + money + '</td>'
        + '<td class="num">' + esc(r.elapsed_ms == null ? '—' : (r.elapsed_ms + 'ms')) + '</td>'
        + '<td class="tiny dim">' + esc(r.error || '') + '</td>'
        + '</tr>';
    }).join('') || '<tr><td colspan="9"><div class="empty"><div class="empty-t">还没有调用记录</div>'
      + '<div class="empty-h">在「创作中心」生成一次剧本正文后，这里会出现用量。</div></div></td></tr>';

    box.innerHTML = '<section class="card"><div class="card-h"><h3>调用记录</h3>'
      + '<span class="card-sub">共 ' + esc(s.calls || 0) + ' 次 · 成功 ' + esc(s.ok || 0)
      + ' · 失败 ' + esc(s.failed || 0) + '</span></div>'
      + '<div class="card-b">'
      + '<div class="row gap12" style="flex-wrap:wrap;margin-bottom:10px">'
      + '<span class="chip">输入 ' + esc(s.input_tokens || 0) + ' tokens</span>'
      + '<span class="chip">输出 ' + esc(s.output_tokens || 0) + ' tokens</span>'
      + '<span class="chip">金额：' + (s.cost_usd_known == null ? '未知'
        : ('$' + s.cost_usd_known + '（' + esc(s.cost_records) + ' 条有账单）')) + '</span>'
      + '</div>'
      + '<div class="alert info" style="margin-bottom:10px"><span class="nav-ico">' + icon('alert', 14)
      + '</span><div><!-- costNote -->'
      + '金额只认供应商返回的 usage：<b>没返回就是「未知」，不按 token 单价估算</b>。'
      + '提示词与生成正文不落日志，只存指纹与长度。</div></div>'
      + '<div class="table-wrap"><table class="tb"><thead><tr>'
      + '<th>时间</th><th>用途</th><th>提供商 / 模型</th><th style="width:80px">结果</th>'
      + '<th class="num" style="width:70px">入</th><th class="num" style="width:70px">出</th>'
      + '<th class="num" style="width:80px">金额</th><th class="num" style="width:80px">耗时</th>'
      + '<th style="width:180px">错误</th>'
      + '</tr></thead><tbody>' + rows + '</tbody></table></div></div>'
      + '<div class="card-foot">' + stamp('web/var/llm/usage.jsonl · 最近 100 条') + '</div></section>';
  } catch (e) {
    box.innerHTML = '<div class="card"><div class="card-b"><div class="alert bad"><span class="nav-ico">'
      + icon('alert', 14) + '</span><div>读取用量失败：' + esc(e.detail || e.message) + '</div></div></div></div>';
  }
}
