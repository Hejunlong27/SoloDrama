/* ============================================================
   api.js —— 后端访问的唯一出口
   纪律：
     * 不拼任何 Shell / 路径；只调用既有 HTTP 接口；
     * 所有失败都被归一成 {ok:false, status, detail}，页面不用 try/catch 满天飞；
     * 401/403 单独标记，页面要能区分「没权限」与「业务失败」。
   ============================================================ */

export class ApiError extends Error {
  constructor(message, status, detail) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

function qs(params) {
  const p = new URLSearchParams();
  Object.keys(params || {}).forEach((k) => {
    const v = params[k];
    if (v === undefined || v === null || v === '') return;
    p.set(k, v);
  });
  return p.toString();
}

export const q = qs;

async function request(path, opts) {
  const o = opts || {};
  const init = { method: o.method || 'GET', headers: {} };
  if (o.body !== undefined) {
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(o.body);
  }
  let res;
  try {
    res = await fetch(path, init);
  } catch (err) {
    throw new ApiError('无法连接本地控制台（服务可能已停止）', 0, String(err));
  }
  const text = await res.text();
  let data = null;
  if (text) {
    try { data = JSON.parse(text); } catch (e) { data = null; }
  }
  if (!res.ok) {
    const detail = (data && (data.detail || data.message)) || text.slice(0, 300) || res.statusText;
    throw new ApiError(
      res.status === 401 ? '缺少访问令牌' : res.status === 403 ? '访问被拒绝' : '请求失败（' + res.status + '）',
      res.status, typeof detail === 'string' ? detail : JSON.stringify(detail)
    );
  }
  return data;
}

export const get = (path, params) => request(path + (params ? '?' + qs(params) : ''));
export const post = (path, body, params) => request(path + (params ? '?' + qs(params) : ''), { method: 'POST', body: body || {} });
export const del = (path, params) => request(path + (params ? '?' + qs(params) : ''), { method: 'DELETE' });

/* ---- 具体接口（与 web/app.py 的路径一一对应，改后端时同步这里）---- */
export const api = {
  health: () => get('/api/health'),
  workspaces: () => get('/api/workspaces'),
  discover: (refresh) => get('/api/workspaces/discover', { refresh: refresh ? 1 : 0 }),
  setCurrent: (ws) => post('/api/workspaces/current', { path: ws }),
  createProject: (body) => post('/api/projects/create', body),
  register: (ws, title) => post('/api/workspaces', { path: ws, title }),
  prune: () => post('/api/workspaces/prune', {}),

  generators: (ws) => get('/api/generators', { ws }),
  setRhWorkflow: (body) => post('/api/generators/rh', body),

  capabilities: () => get('/api/studio/capabilities'),
  overview: (ws) => get('/api/studio/overview', { ws }),
  workflow: (ws) => get('/api/studio/workflow', { ws }),
  setup: (ws) => get('/api/studio/setup', { ws }),
  shots: (ws, ep) => get('/api/studio/shots', { ws, ep }),
  episodes: (ws) => get('/api/studio/episodes', { ws }),
  cost: (ws) => get('/api/studio/cost', { ws }),
  env: () => get('/api/studio/env'),
  refresh: (ws) => post('/api/studio/refresh', {}, { ws }),

  artifacts: (ws, dir) => get('/api/artifacts', { ws, dir }),
  fileText: (ws, rel) => get('/api/file', { ws, rel }),
  mediaInfo: (ws, rel) => get('/api/studio/media-info', { ws, rel }),
  prompt: (ws, shot) => get('/api/studio/prompt', { ws, shot }),
  assetMd: (ws) => get('/api/studio/asset-md', { ws }),
  loose: (ws) => get('/api/artifacts/loose', { ws }),
  connections: () => get('/api/connections'),
  saveConnection: (kind, body) => post('/api/connections/' + encodeURIComponent(kind), body),
  testConnection: (kind) => post('/api/connections/' + encodeURIComponent(kind) + '/test', {}),

  jobs: (ws, limit) => get('/api/jobs', { ws, limit: limit || 50 }),
  job: (id) => get('/api/jobs/' + encodeURIComponent(id)),
  cancelJob: (id) => post('/api/jobs/' + encodeURIComponent(id) + '/cancel'),
  locks: () => get('/api/locks'),
  audit: (limit) => get('/api/audit', { limit: limit || 50 }),

  commands: (ws) => get('/api/commands', { ws }),
  run: (body) => post('/api/run', body),
  help: (ws, topic) => post('/api/help', { ws, topic }),

  /* ---- LLM 服务层（AI 模型中心）---- */
  llmMeta: () => get('/api/llm/meta'),
  llmProviders: () => get('/api/llm/providers'),
  llmSaveProvider: (body) => post('/api/llm/providers', body),
  llmDeleteProvider: (pid) => del('/api/llm/providers/' + encodeURIComponent(pid)),
  llmTestProvider: (pid, deep, confirm) => post('/api/llm/providers/' + encodeURIComponent(pid) + '/test',
    {}, { deep: deep ? 1 : 0, confirm: confirm ? 1 : 0 }),
  llmPurposes: () => get('/api/llm/purposes'),
  llmSavePurpose: (pid, body) => post('/api/llm/purposes/' + encodeURIComponent(pid), body),
  llmTemplates: () => get('/api/llm/templates'),
  llmTemplate: (tid) => get('/api/llm/templates/' + encodeURIComponent(tid)),
  llmPreview: (body) => post('/api/llm/preview', body),
  llmComplete: (body) => post('/api/llm/complete', body),
  llmUsage: (limit, purpose) => get('/api/llm/usage', { limit: limit || 100, purpose }),

  /* ---- 创作闭环：剧本草稿 ---- */
  scriptGates: (ws) => get('/api/studio/script/gates', { ws }),
  scriptContext: (ws, ep) => get('/api/studio/script/context', { ws, ep }),
  drafts: (ws) => get('/api/studio/drafts', { ws }),
  draft: (ws, id) => get('/api/studio/drafts/' + encodeURIComponent(id), { ws }),
  draftSave: (ws, id, body) => post('/api/studio/drafts/' + encodeURIComponent(id) + '/save', body, { ws }),
  draftConfirm: (ws, id, body) => post('/api/studio/drafts/' + encodeURIComponent(id) + '/confirm', body, { ws }),
  scriptGenerate: (ws, body) => post('/api/studio/script/generate', body, { ws })
};

export function mediaUrl(ws, rel) {
  return '/media?' + qs({ ws, rel });
}

/** SSE 订阅（作业日志）。返回 close()。 */
export function streamJob(id, after, handlers) {
  const h = handlers || {};
  const es = new EventSource('/api/jobs/' + encodeURIComponent(id) + '/stream?after=' + (after || 0));
  es.onmessage = (ev) => {
    let d = null;
    try { d = JSON.parse(ev.data); } catch (e) { return; }
    if (h.onEvent) h.onEvent(d);
  };
  es.onerror = () => { if (h.onError) h.onError(); };
  return () => es.close();
}
