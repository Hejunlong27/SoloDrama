/* ============================================================
   store.js —— 全局状态（当前项目 / 项目清单 / 能力表 / 只读）
   唯一真源是 URL 上的 ?ws= 与后端返回，localStorage 只做「上次用过」的兜底。
   ============================================================ */
import { api } from './api.js';

export const S = {
  ws: '',
  projects: [],
  caps: {},
  readonly: false,
  collapsed: false,
  health: null,
  running: 0,
  loadingProjects: false
};

export function normPath(p) {
  return String(p || '').replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase();
}

export function samePath(a, b) {
  return normPath(a) === normPath(b);
}

export function wsFromUrl() {
  try {
    return new URLSearchParams(location.search).get('ws') || '';
  } catch (e) {
    return '';
  }
}

export function setWs(ws, opts) {
  S.ws = ws || '';
  try {
    if (S.ws) localStorage.setItem('studio.ws', S.ws);
    else localStorage.removeItem('studio.ws');
  } catch (e) { /* 隐私模式下忽略 */ }
  if (opts && opts.pushUrl) {
    const u = new URL(location.href);
    if (S.ws) u.searchParams.set('ws', S.ws); else u.searchParams.delete('ws');
    history.replaceState(null, '', u.toString());
  }
}

export function project() {
  return S.projects.find((p) => samePath(p.path, S.ws)) || null;
}

export function initialWs() {
  const fromUrl = wsFromUrl();
  if (fromUrl) return fromUrl;
  try {
    const saved = localStorage.getItem('studio.ws');
    if (saved) return saved;
  } catch (e) { /* ignore */ }
  return '';
}

export async function loadProjects() {
  S.loadingProjects = true;
  try {
    const d = await api.workspaces();
    S.projects = (d.items || []).filter((it) => it.exists);
    /* ★ 用 URL 显式指定的工作区必须被尊重：哪怕它还没登记。
       否则深链/书签会被静默改成「上次用过的项目」，用户以为看的是 A 却发现是 B。 */
    const explicit = wsFromUrl();
    if (S.ws && explicit && samePath(explicit, S.ws)) return S.projects;
    if (!S.ws || !S.projects.some((p) => samePath(p.path, S.ws))) {
      const cur = d.current || (S.projects[0] && S.projects[0].path) || '';
      if (cur) setWs(cur);
    }
    return S.projects;
  } finally {
    S.loadingProjects = false;
  }
}

export async function loadCaps() {
  if (S.caps && S.caps.items) return S.caps;
  const d = await api.capabilities();
  S.caps = d || { items: {} };
  S.readonly = !!d.readonly;
  return S.caps;
}

export function cap(key) {
  return (S.caps.items || {})[key] || { ok: false, reason: '未知能力' };
}

export async function loadHealth() {
  try {
    S.health = await api.health();
    S.readonly = !!(S.health && S.health.readonly);
  } catch (e) {
    S.health = null;
  }
  return S.health;
}

export async function loadRunning() {
  try {
    const d = await api.jobs(S.ws, 20);
    const items = d.items || [];
    S.running = items.filter((j) => j.status === 'running' || j.status === 'queued').length;
  } catch (e) {
    S.running = 0;
  }
  return S.running;
}

export function setCollapsed(v) {
  S.collapsed = !!v;
  try { localStorage.setItem('studio.collapsed', S.collapsed ? '1' : '0'); } catch (e) { /* ignore */ }
}

export function initialCollapsed() {
  try {
    if (localStorage.getItem('studio.collapsed') === '1') return true;
  } catch (e) { /* ignore */ }
  return window.innerWidth <= 1024;
}
