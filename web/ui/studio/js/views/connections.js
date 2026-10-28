/* ============================================================
   连接中心 —— 三类外部通道（大模型 / 本地 ComfyUI / RunningHub）
   纪律：
     * Key 只进不出：输入框是 password，读回来只有「672…6653（32 位）」；
     * 测试一律只读：查账户、查节点表、读 system_stats，都不产生任务、不花钱；
     * 每个失败必须给「下一步」，不能只显示一个红点。
   ============================================================ */
import { api } from '../api.js';
import { esc, icon, badge, toast, dt, ago, kv, openModal, closeModal, paintIcons } from '../ui.js';

function field(id, label, inner, help) {
  return '<div class="field"><label class="tiny dim" for="' + esc(id) + '">' + esc(label) + '</label>'
    + inner + (help ? '<div class="help">' + esc(help) + '</div>' : '') + '</div>';
}

function tone(it) {
  if (it.last_ok === true) return 'done';
  if (it.last_ok === false) return 'fail';
  return 'todo';
}

function toneText(it) {
  if (it.last_ok === true) return '已连接';
  if (it.last_ok === false) return '有问题';
  return it.has_key || it.kind === 'comfyui' ? '待验证' : '未配置';
}

/* ---------- 三张卡 ---------- */
function cardLlm(it) {
  const provs = it.providers || [];
  return '<section class="card" id="card-llm"><div class="card-h">'
    + '<span class="state ' + tone(it) + '"><i class="dot ' + tone(it) + '"></i>' + esc(toneText(it)) + '</span>'
    + '<h3>大模型</h3><span class="card-sub">剧本 / 分镜 / 文案的生成能力</span>'
    + '<span class="spacer"></span>' + badge('info', '按 token 计费') + '</div>'
    + '<div class="card-b">'
    + '<div class="small muted" style="margin-bottom:12px">' + esc(it.doc) + '</div>'
    + kv([
      /* 只放名字：把「（模型 · 缺 Key · 已停用）」全塞进一行会折成两行半，
         模型名正好被拆在换行处（出现「mock / -episode」这种断词）。 */
      ['提供商', (provs.length ? provs.map((p) => esc(p.name || p.id)
        + (p.enabled === false ? '（停用）' : (p.has_key ? '' : '（缺 Key）'))).join('；') : '还没有'), false],
      ['在用模型', (provs.filter((p) => p.enabled !== false).length
        ? esc(provs.filter((p) => p.enabled !== false)[0].model || '未填') : '—')],
      ['接入方式', 'OpenAI 兼容 / Ollama（地址 + Key + 模型名）'],
      ['最近验证', it.last_test ? dt(it.last_test) : '从未验证']
    ])
    + (it.last_detail ? '<div class="alert ' + (it.last_ok ? 'info' : 'warn') + '" style="margin-top:12px">'
      + '<span class="nav-ico">' + icon(it.last_ok ? 'check' : 'alert', 14) + '</span><div>'
      + esc(it.last_detail) + (it.last_next ? '<br><span class="tiny dim">下一步：' + esc(it.last_next) + '</span>' : '')
      + '</div></div>' : '')
    + '</div><div class="card-foot"><span class="tiny dim">模型在这里只做「有没有」，'
    + '具体哪个用途用哪个模型去 <b>AI 模型中心 → 用途路由</b>。</span>'
    + '<span class="spacer"></span><button class="btn quiet" data-go="models">'
    + icon('external', 13) + ' 去 AI 模型中心</button></div></section>';
}

function cardComfy(it) {
  const f = it.fields || {};
  return '<section class="card" id="card-comfyui"><div class="card-h">'
    + '<span class="state ' + tone(it) + '"><i class="dot ' + tone(it) + '"></i>' + esc(toneText(it)) + '</span>'
    + '<h3>本地出图 · ComfyUI</h3><span class="card-sub">角色 / 场景 / 道具图</span>'
    + '<span class="spacer"></span>' + badge('ok', '￥0 · 占 GPU') + '</div>'
    + '<div class="card-b">'
    + '<div class="small muted" style="margin-bottom:12px">' + esc(it.doc) + '</div>'
    + field('cUrl', '服务地址', '<input class="input" id="cUrl" value="' + esc(f.base_url || '')
      + '" placeholder="http://127.0.0.1:8188" spellcheck="false">')
    + '<div class="row" style="gap:8px;margin-top:4px">'
    + '<button class="btn primary" id="cSave">保存</button>'
    + '<button class="btn quiet" id="cTest">测试连接</button>'
    + '<span class="tiny dim" style="margin-left:auto">'
    + (it.last_test ? esc(ago(it.last_test)) + '前验证' : '还没验证过') + '</span></div>'
    + '<div id="cResult" style="margin-top:10px">' + resultBox(it) + '</div>'
    + '</div><div class="card-foot"><span class="tiny dim">保存后出图器会自动用这个地址（不需要你设环境变量），'
    + '所有出图脚本自动生效——不需要你在终端设环境变量。</span></div></section>';
}

function cardRh(it) {
  const f = it.fields || {};
  const isApp = String(f.kind || 'workflow').indexOf('app') >= 0;
  return '<section class="card" id="card-runninghub"><div class="card-h">'
    + '<span class="state ' + tone(it) + '"><i class="dot ' + tone(it) + '"></i>' + esc(toneText(it)) + '</span>'
    + '<h3>云端出片 · RunningHub</h3><span class="card-sub">分镜视频 / AI 应用</span>'
    + '<span class="spacer"></span>' + badge('warn', '★ 按次计费') + '</div>'
    + '<div class="card-b">'
    + '<div class="small muted" style="margin-bottom:12px">' + esc(it.doc) + '</div>'
    + field('rSite', '站点（Key 与站点必须同区）',
      '<select class="select" id="rSite">'
      + '<option value="https://www.runninghub.ai"' + (/\.ai$/.test(f.base_url || '') ? ' selected' : '') + '>runninghub.ai（海外）</option>'
      + '<option value="https://www.runninghub.cn"' + (/\.cn$/.test(f.base_url || '') ? ' selected' : '') + '>runninghub.cn（国内）</option>'
      + '</select>')
    + field('rKind', '调用方式',
      '<select class="select" id="rKind">'
      + '<option value="workflow"' + (!isApp ? ' selected' : '') + '>工作流（workflowId）</option>'
      + '<option value="ai-app"' + (isApp ? ' selected' : '') + '>AI 应用（webappId）</option>'
      + '</select>')
    + field('rTarget', isApp ? 'AI 应用 ID' : '工作流 ID',
      '<input class="input" id="rTarget" value="' + esc(isApp ? (f.ai_app_id || '') : (f.workflow_id || ''))
      + '" placeholder="' + (isApp ? '从 AI 应用页面 URL 取 webappId' : 'RunningHub 工作流 ID') + '" spellcheck="false">')
    + field('rKey', 'API Key',
      '<input class="input" id="rKey" type="password" autocomplete="off" spellcheck="false" placeholder="'
      + esc(it.has_key ? '已保存 ' + it.key_hint + '，留空不改' : '粘贴 API Key') + '">',
      it.has_key ? '当前来源：' + ({ file: '连接中心保存的', env: '进程环境变量', registry: 'Windows 用户变量' }[it.key_source] || '未知')
        + '。留空保存不会清掉它。' : 'Key 只存本机 web/var/，接口不回显明文。')
    + '<div class="row" style="gap:8px;margin-top:4px">'
    + '<button class="btn primary" id="rSave">保存</button>'
    + '<button class="btn quiet" id="rTest">测试连接</button>'
    + (it.has_key ? '<button class="btn quiet" id="rClear" style="margin-left:auto">清除本机 Key</button>' : '')
    + '</div>'
    + '<div id="rResult" style="margin-top:10px">' + resultBox(it) + '</div>'
    + '</div><div class="card-foot"><span class="tiny dim">测试只查账户余额与节点表，'
    + '<b>不会提交任何任务</b>。真正出片在「分镜与视频」，那里有计费确认单。</span></div></section>';
}

function resultBox(it) {
  if (!it.last_test && !it.last_detail) {
    return '<div class="tiny dim">还没有测试过。点「测试连接」做一次只读探测（5 秒内返回）。</div>';
  }
  const good = it.last_ok === true;
  return '<div class="alert ' + (good ? 'info' : 'bad') + '">'
    + '<span class="nav-ico">' + icon(good ? 'check' : 'alert', 14) + '</span><div>'
    + esc(it.last_detail || '—')
    + (it.last_next ? '<div class="tiny" style="margin-top:4px;opacity:.8">下一步：' + esc(it.last_next) + '</div>' : '')
    + '</div></div>';
}

function header(ov) {
  const okN = (ov.items || []).filter((i) => i.last_ok === true).length;
  return '<div class="page-head"><div>'
    + '<div class="crumb"><b>全局</b><span class="sep">/</span><b>连接中心</b></div>'
    + '<h1 class="page-title">连接中心</h1>'
    + '<div class="page-sub">这台机器能用的外部能力。配置一次，所有项目共用；不配也能用，只是对应环节会停在「未接通」。</div></div>'
    + '<div class="page-actions">'
    + (okN === 3 ? badge('ok', '三路全通') : badge(okN ? 'warn' : 'bad', okN + ' / 3 可用'))
    + '<button class="btn quiet" id="testAll">' + icon('refresh', 14) + ' 全部测试</button>'
    + '</div></div>';
}

export async function render(ctx) {
  let ov;
  try {
    ov = await api.connections();
  } catch (e) {
    return {
      html: '<div class="page-head"><div><h1 class="page-title">连接中心</h1></div></div>'
        + '<div class="card"><div class="card-b"><div class="alert bad">'
        + '<span class="nav-ico">' + icon('alert', 14) + '</span><div>读取连接配置失败：'
        + esc(e.detail || e.message) + '</div></div></div></div>'
    };
  }

  const byKind = {};
  (ov.items || []).forEach((i) => { byKind[i.kind] = i; });
  const llm = byKind.llm || { fields: {}, doc: '' };
  const comfy = byKind.comfyui || { fields: {}, doc: '' };
  const rh = byKind.runninghub || { fields: {}, doc: '' };

  const html = header(ov)
    + '<div class="grid g2" style="align-items:start">'
    + cardLlm(llm) + cardComfy(comfy) + cardRh(rh)
    + '<section class="card"><div class="card-h"><h3>注入关系</h3>'
    + '<span class="card-sub">界面填一次，子进程自动带上</span></div><div class="card-b">'
    + kv([
      /* 不写环境变量名：界面对用户只讲「会发生什么」。
         变量名属于实现细节，写出来只会让人以为要自己去设。 */
      ['出图地址', '出图任务启动时自动带上'],
      ['RH Key', '出片任务自动带上，不回显'],
      ['RH 站点', '与 Key 一起带上'],
      ['大模型', '走内部网关，子进程不接触 Key']
    ])
    + '<div class="alert info" style="margin-top:12px"><span class="nav-ico">' + icon('lock', 14) + '</span><div>'
    + '配置文件在 <span class="mono">' + esc(ov.store || 'web/var/connections.json') + '</span>，'
    + '已被 gitignore；密钥单独一份、权限 0600、接口只回指纹。'
    + '</div></div></div></section></div>';

  return {
    html,
    mount: (root) => {
      paintIcons(root);
      root.querySelectorAll('[data-go]').forEach((b) => {
        b.onclick = () => { if (ctx && ctx.navigate) ctx.navigate(b.dataset.go); };
      });
      mountComfy(ctx, root);
      mountRh(ctx, root);
      const all = root.querySelector('#testAll');
      if (all) all.onclick = async () => {
        all.disabled = true;
        const old = all.textContent;
        all.innerHTML = '<span class="spinner"></span>测试中';
        try {
          for (const k of ['llm', 'comfyui', 'runninghub']) {
            try { await api.testConnection(k); } catch (e) { /* 单个失败不影响其余 */ }
          }
          toast('测试完成');
          ctx.refresh();
        } finally {
          all.disabled = false;
          all.textContent = old;
        }
      };
    }
  };
}

function mountComfy(ctx, root) {
  const save = root.querySelector('#cSave');
  const test = root.querySelector('#cTest');
  if (save) save.onclick = async () => {
    save.disabled = true;
    try {
      await api.saveConnection('comfyui', { base_url: (root.querySelector('#cUrl') || {}).value || '' });
      toast('已保存 ComfyUI 地址');
      ctx.refresh();
    } catch (e) { toast('保存失败：' + (e.detail || e.message), 'bad'); }
    finally { save.disabled = false; }
  };
  if (test) test.onclick = async () => {
    test.disabled = true;
    test.innerHTML = '<span class="spinner"></span>测试中';
    const box = root.querySelector('#cResult');
    try {
      const r = await api.testConnection('comfyui');
      if (box) box.innerHTML = '<div class="alert ' + (r.ok ? 'info' : 'bad') + '">'
        + '<span class="nav-ico">' + icon(r.ok ? 'check' : 'alert', 14) + '</span><div>'
        + esc(r.detail || '') + (r.next ? '<div class="tiny" style="margin-top:4px;opacity:.8">下一步：'
          + esc(r.next) + '</div>' : '') + '</div></div>';
      toast(r.ok ? 'ComfyUI 在线' : '测试失败', r.ok ? 'ok' : 'bad');
      if (r.ok) setTimeout(() => ctx.refresh(), 900);
    } catch (e) { toast('测试失败：' + (e.detail || e.message), 'bad'); }
    finally { test.disabled = false; test.textContent = '测试连接'; }
  };
}

function mountRh(ctx, root) {
  const kindSel = root.querySelector('#rKind');
  if (kindSel) kindSel.onchange = () => ctx.refresh();

  const collect = () => {
    const isApp = String((root.querySelector('#rKind') || {}).value || '').indexOf('app') >= 0;
    const target = (root.querySelector('#rTarget') || {}).value || '';
    return {
      base_url: (root.querySelector('#rSite') || {}).value || '',
      kind: isApp ? 'ai-app' : 'workflow',
      workflow_id: isApp ? '' : target,
      ai_app_id: isApp ? target : ''
    };
  };

  const save = root.querySelector('#rSave');
  if (save) save.onclick = async () => {
    save.disabled = true;
    try {
      const body = collect();
      const keyEl = root.querySelector('#rKey');
      if (keyEl && keyEl.value.trim()) body.api_key = keyEl.value.trim();
      await api.saveConnection('runninghub', body);
      toast('已保存 RunningHub 配置');
      ctx.refresh();
    } catch (e) { toast('保存失败：' + (e.detail || e.message), 'bad'); }
    finally { save.disabled = false; }
  };

  const test = root.querySelector('#rTest');
  if (test) test.onclick = async () => {
    test.disabled = true;
    test.innerHTML = '<span class="spinner"></span>测试中';
    const box = root.querySelector('#rResult');
    try {
      const r = await api.testConnection('runninghub');
      if (box) box.innerHTML = '<div class="alert ' + (r.ok ? 'info' : 'bad') + '">'
        + '<span class="nav-ico">' + icon(r.ok ? 'check' : 'alert', 14) + '</span><div>'
        + esc(r.detail || '') + (r.next ? '<div class="tiny" style="margin-top:4px;opacity:.8">下一步：'
          + esc(r.next) + '</div>' : '') + '</div></div>';
      toast(r.ok ? 'RunningHub 可用' : '测试失败', r.ok ? 'ok' : 'bad');
    } catch (e) { toast('测试失败：' + (e.detail || e.message), 'bad'); }
    finally { test.disabled = false; test.textContent = '测试连接'; }
  };

  const clear = root.querySelector('#rClear');
  if (clear) clear.onclick = () => {
    openModal({
      title: '清除本机保存的 Key？',
      icon: 'lock',
      html: '<div class="small">只会删除 <span class="mono">web/var/connections.keys.json</span> 里这一条。'
        + '如果你在 Windows 用户变量或进程环境里也设了 Key，那些不受影响，仍会被识别。</div>',
      foot: '<span class="spacer"></span><button class="btn quiet" data-close="modal">取消</button>'
        + '<button class="btn primary" id="kClear">清除</button>',
      mount: (m) => {
        m.querySelector('#kClear').onclick = async () => {
          try {
            await api.saveConnection('runninghub', { api_key: '' });
            closeModal();
            toast('已清除本机 Key');
            ctx.refresh();
          } catch (e) { toast('清除失败：' + (e.detail || e.message), 'bad'); }
        };
      }
    });
  };
}
