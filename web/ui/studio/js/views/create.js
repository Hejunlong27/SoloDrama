/* 创作 —— 灵感进，产物出。
   为什么它是一个独立页面而不是散在各个角落：
   引擎只做执行，创作靠 Skill + 模型。但「创作到哪一步了」之前只能靠翻文件夹。
   这里把五段摆成一条线：灵感 → 企划案 → 资产库 → 剧本 → 导演手册 → 制作包。
   每一段都能看见状态、都能点、都能改；做完的段会变实心，下一步永远只有一条。

   画风纪律：Skill 定叙事套路，style_lock 定画风。这条在页面上写死，不靠人记。 */
import { api } from '../api.js';
import { esc, icon, badge, toast, openModal, closeModal, paintIcons } from '../ui.js';

const PIPE = [
  { id: 'idea', label: '灵感' },
  { id: 'plan', label: '企划案' },
  { id: 'assets', label: '资产库' },
  { id: 'script', label: '剧本' },
  { id: 'director', label: '导演手册' },
  { id: 'pack', label: '制作包' },
  { id: 'run', label: '出片' }
];

// 每个产物用哪个用途生成、缺什么就不能点
const GEN = {
  plan: { purpose: 'create.plan', needs: ['skill'], hint: '一句话灵感 + 已装载模板 + 画风' },
  assets: { purpose: 'create.assets', needs: ['skill', 'plan'], hint: '需要先有企划案' },
  script: { purpose: 'create.script', needs: ['skill', 'plan'], hint: '需要先有企划案' },
  director: { purpose: 'create.director', needs: ['skill', 'assets'], hint: '需要资产库 + 某一集剧本' }
};

function pipeBar(st, next) {
  const done = {};
  done.idea = st.idea.state === 'done';
  (st.stages || []).forEach((s) => { done[s.id] = s.state === 'done'; });
  done.pack = st.pack.state === 'done';
  done.run = (st.engine.characters + st.engine.scenes + st.engine.boards) > 0;
  const cur = next && next.stage ? next.stage : '';
  return '<div class="row" style="gap:0;align-items:center;flex-wrap:wrap;margin:2px 0 18px">'
    + PIPE.map((p, i) => {
      const on = done[p.id];
      const isCur = p.id === cur;
      const col = isCur ? 'var(--create)' : (on ? 'var(--ok)' : 'var(--line-strong)');
      const bg = isCur ? 'var(--create-tint)' : (on ? 'var(--ok-tint)' : 'transparent');
      return (i ? '<span style="width:14px;height:1px;background:var(--line-strong)"></span>' : '')
        + '<span style="display:inline-flex;align-items:center;gap:6px;padding:5px 10px;'
        + 'border:1px solid ' + col + ';background:' + bg + ';border-radius:999px;'
        + 'font-size:var(--fs-11);color:' + (on || isCur ? 'var(--txt)' : 'var(--txt-3)') + '">'
        + '<i class="dot" style="background:' + col + ';width:6px;height:6px;border-radius:50%"></i>'
        + esc(p.label) + '</span>';
    }).join('') + '</div>';
}

function stageCard(s, ctx, st) {
  const ok = s.state === 'done';
  const g = GEN[s.id] || {};
  const doneOf = (id) => ((st.stages || []).find((x) => x.id === id) || {}).state === 'done';
  const missing = (g.needs || []).filter((n) => {
    if (n === 'skill') return !(st.skills && st.skills.length);
    if (n === 'plan') return !doneOf('plan');
    if (n === 'assets') return !doneOf('assets');
    if (n === 'script') return !doneOf('script');
    return false;
  });
  const can = !missing.length;
  const files = s.files || [];
  return '<div style="border:1px solid ' + (ok ? 'var(--line-strong)' : 'var(--line)') + ';'
    + 'border-left:2px solid ' + (ok ? 'var(--ok)' : 'var(--create-line)') + ';'
    + 'border-radius:var(--r-lg);background:var(--bg-card);padding:12px 14px;margin-bottom:10px">'
    + '<div class="row" style="align-items:baseline;gap:8px;flex-wrap:wrap">'
    + '<b>' + esc(s.label) + '</b>'
    + (ok ? badge('ok', '已完成 ' + (s.chars || 0) + ' 字') : badge('outline', '空'))
    + '<span class="tiny dim" style="flex:1;min-width:180px">' + esc(s.desc) + '</span></div>'
    + '<div class="mono tiny dim" style="margin:6px 0 10px;word-break:break-all">' + esc(s.path)
    + (files.length ? '　（' + files.length + ' 个文件）' : '') + '</div>'
    + '<div class="row" style="gap:6px;flex-wrap:wrap">'
    + '<button class="btn primary sm" data-gen="' + s.id + '"' + (can ? '' : ' disabled title="' + esc(g.hint || '') + '"') + '>'
    + (ok ? '重新生成' : '生成') + '</button>'
    + (ok ? '<button class="btn quiet sm" data-edit="' + s.id + '">查看 / 修改</button>' : '')
    + (!can ? '<span class="tiny dim">' + esc(g.hint || '') + '</span>' : '')
    + '</div></div>';
}

function ideaCard(st) {
  const i = st.idea;
  return '<div style="border:1px solid var(--create-line);border-left:2px solid var(--create);'
    + 'border-radius:var(--r-lg);background:var(--create-tint);padding:12px 14px;margin-bottom:16px">'
    + '<div class="row" style="align-items:baseline;gap:8px">'
    + '<b>灵感</b>'
    + (i.state === 'done' ? badge('ok', '已填') : badge('outline', '还没写'))
    + '<span class="tiny dim">一句话就够 —— 不要写大纲，大纲是下一步的事</span></div>'
    + '<div class="field" style="margin-top:10px">'
    + '<textarea class="textarea" id="ciIdea" rows="3" placeholder="例：一通打错的电话，对面是那个刚买下她公司的男人">'
    + esc(i.idea || '') + '</textarea></div>'
    + '<div class="row" style="gap:8px;margin-top:8px;flex-wrap:wrap">'
    + '<label class="tiny dim">集数<input class="input mono" id="ciEps" value="' + (i.ep_total || 30)
    + '" style="width:76px;margin-left:6px" inputmode="numeric"></label>'
    + '<label class="tiny dim">单集秒数<input class="input mono" id="ciSec" value="' + (i.ep_seconds || 60)
    + '" style="width:76px;margin-left:6px" inputmode="numeric"></label>'
    + '<button class="btn primary sm" id="ciSave" style="margin-left:auto">保存灵感</button></div>'
    + (i.title ? '<div class="tiny dim" style="margin-top:8px">当前：' + esc(i.title)
      + (i.platform ? ' · ' + esc(i.platform) : '') + ' · ' + (i.ep_total || 0) + ' 集</div>' : '')
    + '</div>';
}

export async function render(ctx) {
  if (!ctx.ws) {
    return { html: '<div class="page-head"><div><h1 class="page-title">创作</h1></div></div>'
      + '<div class="alert warn"><span class="nav-ico">' + icon('alert', 14) + '</span>'
      + '<div>先在左上角选一个项目。</div></div>', mount: () => {} };
  }
  const [st, inst] = await Promise.all([
    api.createState(ctx.ws).catch((e) => ({ error: String((e && e.detail) || e) })),
    api.skillsInstalled(ctx.ws).catch(() => ({ items: [] }))
  ]);
  if (st.error) {
    return { html: '<div class="page-head"><div><h1 class="page-title">创作</h1></div></div>'
      + '<div class="alert bad">读不到创作状态：' + esc(st.error) + '</div>', mount: () => {} };
  }
  st.skills = inst.items || [];

  const next = st.next || {};
  const sk = st.skills;

  const sideSkill = sk.length
    ? '<div style="border:1px solid var(--create-line);border-radius:var(--r-md);background:var(--create-tint);padding:10px 12px">'
      + '<div class="row" style="gap:6px;align-items:baseline"><b class="small">' + esc(sk[0].title || sk[0].id) + '</b></div>'
      + '<div class="tiny dim" style="margin-top:4px">题材套路、阶段划分由它定</div>'
      + '<div class="row" style="gap:6px;margin-top:8px"><button class="btn quiet sm" data-go="skills">换一个</button></div></div>'
    : '<div style="border:1px dashed var(--create-line);border-radius:var(--r-md);padding:12px;text-align:center">'
      + '<div class="small" style="color:var(--create)">还没装载题材模板</div>'
      + '<div class="tiny dim" style="margin:6px 0 10px">没有模板就没有叙事结构，模型只能瞎编</div>'
      + '<button class="btn primary sm" data-go="skills">去 Skill 中心</button></div>';

  const styleLock = st.idea.style_lock || '';
  const sideStyle = '<div style="border:1px solid var(--line);border-radius:var(--r-md);padding:10px 12px;margin-top:10px">'
    + '<div class="small"><b>画风锁</b> <span class="tiny dim">由项目定，不由 Skill 定</span></div>'
    + (styleLock
      ? '<div class="tiny mono dim" style="margin-top:6px;line-height:1.5;max-height:90px;overflow:hidden">'
        + esc(styleLock) + '…</div>'
      : '<div class="tiny" style="color:var(--danger);margin-top:6px">项目还没定画风：先去「系统设置」选一个，'
        + '否则生成的内容没有风格约束</div>')
    + '</div>';

  const sideNext = '<div style="border:1px solid var(--line);border-radius:var(--r-md);padding:10px 12px;margin-top:10px">'
    + '<div class="small"><b>下一步</b></div>'
    + '<div style="color:var(--create);margin:6px 0 2px;font-size:var(--fs-13)">' + esc(next.label || '—') + '</div>'
    + '<div class="tiny dim" style="line-height:1.5">' + esc(next.why || '') + '</div></div>';

  const engine = st.engine;
  const sideEngine = '<div style="border:1px solid var(--line);border-radius:var(--r-md);padding:10px 12px;margin-top:10px">'
    + '<div class="small"><b>引擎产物</b></div>'
    + '<div class="tiny dim" style="margin-top:6px;line-height:1.7">'
    + '人物图 ' + engine.characters + ' · 场景图 ' + engine.scenes + ' · 道具 ' + engine.props
    + '<br>分镜图 ' + engine.boards + '（' + esc(engine.dir) + '）</div>'
    + '<button class="btn quiet sm" data-go="assets" style="margin-top:8px">去资产中心</button></div>';

  const html = '<div class="page-head"><div><h1 class="page-title">创作</h1>'
    + '<div class="page-sub">灵感 → 企划案 → 资产库 → 剧本 → 导演手册。'
    + '产物落 <span class="mono">' + esc(st.dir) + '/</span>，引擎只读制作包 —— 两边永远不抢同一个文件。</div></div>'
    + '<div class="page-actions">' + badge('outline', '完成 ' + st.progress.done + '/' + st.progress.total)
    + (st.pack.state === 'done' ? ' ' + badge('ok', '已导入 ' + st.pack.episodes.length + ' 集') : '')
    + '</div></div>'

    + pipeBar(st, next)
    + '<div class="grid g21">'
    + '<div>' + ideaCard(st)
    + (st.stages || []).map((s) => stageCard(s, ctx, st)).join('')
    + '</div>'
    + '<div>' + sideSkill + sideStyle + sideNext + sideEngine
    + '<div style="margin-top:10px"><button class="btn quiet sm" id="cvPrompt" style="width:100%">'
    + '看模型将收到的指令</button></div>'
    + '<div class="tiny dim" style="margin-top:10px;line-height:1.6">'
    + esc(st.note || '') + '</div></div></div>';

  return {
    html,
    mount: (root) => {
      paintIcons(root);
      const go = (k) => { if (ctx.navigate) ctx.navigate(k); };

      root.querySelectorAll('[data-go]').forEach((b) => { b.onclick = () => go(b.dataset.go); });

      const ideaEl = root.querySelector('#ciIdea');
      const saveIdea = async () => {
        const body = {
          ws: ctx.ws, idea: (ideaEl || {}).value || '',
          ep_total: Number((root.querySelector('#ciEps') || {}).value) || 0,
          ep_seconds: Number((root.querySelector('#ciSec') || {}).value) || 0
        };
        if (!body.idea.trim()) { toast('先写一句话灵感', 'bad'); return; }
        try {
          await api.createIdea(body);
          toast('灵感已保存', 'ok');
          ctx.refresh();
        } catch (e) { toast('保存失败：' + ((e.detail) || e.message), 'bad'); }
      };
      const sb = root.querySelector('#ciSave');
      if (sb) sb.onclick = saveIdea;

      /* 生成：同步等模型（30–60 秒）。按钮进 loading，页面不锁 —— 期间还能看别的。 */
      root.querySelectorAll('[data-gen]').forEach((b) => {
        b.onclick = async () => {
          const stage = b.dataset.gen;
          const g = GEN[stage] || {};
          const old = b.innerHTML;
          b.disabled = true;
          b.innerHTML = '<span class="spinner"></span> 生成中';
          const extra = {};
          if (stage === 'script') {
            const r = prompt('要写哪几集？（例：1-3）', '1-3');
            if (r === null) { b.disabled = false; b.innerHTML = old; return; }
            extra.episodes_range = r;
          }
          if (stage === 'director') {
            const ep = prompt('要拆哪一集？（例：第01集）', '第01集');
            if (ep === null) { b.disabled = false; b.innerHTML = old; return; }
            try {
              const rd = await api.createRead(ctx.ws, 'script');
              const t = String(rd.text || '');
              const at = t.indexOf('## ' + ep);
              extra.script_ep = at >= 0 ? t.slice(at, at + 12000) : t.slice(0, 12000);
              if (!extra.script_ep.trim()) {
                toast('剧本还是空的：先生成「分集剧本」', 'bad');
                b.disabled = false; b.innerHTML = old; return;
              }
            } catch (e) {
              toast('读剧本失败：' + ((e.detail) || e.message), 'bad');
              b.disabled = false; b.innerHTML = old; return;
            }
          }
          try {
            const r = await api.createGenerate({ ws: ctx.ws, purpose: g.purpose, stage, ...extra });
            /* mock 产出的是一份**演练样例**，不是真内容。不说清的话，用户会拿着
               「演练片名」去问为什么片名是假的 —— 而真正原因是模型还没配。 */
            const prov = String(r.provider || '');
            if (/Mock|演练/i.test(prov)) {
              toast((r.detail || '已生成') + '（离线演练，非真实创作：到「AI 模型中心」配模型后重生成）', 'warn');
            } else {
              toast(r.detail || '已生成', 'ok');
            }
            ctx.refresh();
          } catch (e) {
            const msg = (typeof e.detail === 'string' ? e.detail : (e.detail && e.detail.message) || e.message) || '生成失败';
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
      });

      /* 查看 / 修改：人和模型共写同一个文件，所以要能改、改完能存。 */
      root.querySelectorAll('[data-edit]').forEach((b) => {
        b.onclick = async () => {
          const stage = b.dataset.edit;
          try {
            const d = await api.createRead(ctx.ws, stage);
            openModal({
              title: '编辑 · ' + stage,
              icon: 'edit',
              html: '<div class="tiny dim" style="margin-bottom:8px">改完点保存。旧版会自动备份成 '
                + '<span class="mono">.bak_时间戳</span>，改坏了能回滚。</div>'
                + '<textarea class="textarea mono" id="edText" rows="20" '
                + 'style="font-size:var(--fs-11);line-height:1.6;min-height:min(58vh,520px)">'
                + esc(d.text || '') + '</textarea>',
              foot: '<span class="spacer"></span><button class="btn quiet" data-close="modal">取消</button>'
                + '<button class="btn primary" id="edSave">保存</button>',
              mount: (m) => {
                m.querySelector('#edSave').onclick = async () => {
                  const text = m.querySelector('#edText').value;
                  try {
                    const r = await api.createWrite({ ws: ctx.ws, stage, text });
                    toast(r.detail || '已保存', 'ok');
                    closeModal();
                    ctx.refresh();
                  } catch (e) { toast('保存失败：' + ((e.detail) || e.message), 'bad'); }
                };
              }
            });
          } catch (e) { toast('读取失败：' + ((e.detail) || e.message), 'bad'); }
        };
      });

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
              + 'max-height:min(62vh,560px);overflow:auto;background:var(--bg-inset);'
              + 'border:1px solid var(--line);border-radius:var(--r-md);padding:12px">'
              + esc(d.text) + '</pre>',
            foot: '<span class="spacer"></span><button class="btn quiet" data-close="modal">关闭</button>'
          });
        } catch (e) { toast('读不到：' + ((e.detail) || e.message), 'bad'); }
      };
    }
  };
}
