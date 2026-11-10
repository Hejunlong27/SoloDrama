/* ============================================================
   theme.js —— 主题解析与切换（深色 Midnight Studio / 浅色 Warm Paper）
   ------------------------------------------------------------
   为什么主题要单独一个模块：
   1) 它是"工作模式"不是"外观偏好"—— 看片/分镜用深色，写剧本/填表用浅色；
   2) 首帧必须已经是对的主题，否则会闪一下白（深色用户尤其刺眼）；
   3) 三态（auto/dark/light）比两态多一个"跟随系统"，但少一个"用户每次都要重设"。

   首帧防闪白靠 index.html <head> 里的内联脚本（CSS 之前执行）。
   本模块只负责：读记忆 → 解析 → 写 data-theme → 提供切换与订阅。
   ============================================================ */

const KEY = 'sd-theme';
const MODES = ['auto', 'dark', 'light'];
const META = {
  dark: '#101216',
  light: '#F4F2ED'
};

let media = null;

/* `?theme=dark|light` 临时强制（不写记忆）。
   用途：截图取证、投屏演示、给客户看指定主题 —— 与 main.js 的 `?agent=1` / `?monitor=1` 同一路数。 */
export function urlOverride() {
  try {
    const v = new URLSearchParams(location.search).get('theme');
    return (v === 'dark' || v === 'light') ? v : '';
  } catch (e) {
    return '';
  }
}

export function storedMode() {
  const forced = urlOverride();
  if (forced) return forced;
  try {
    const v = localStorage.getItem(KEY);
    return MODES.indexOf(v) >= 0 ? v : 'auto';
  } catch (e) {
    return 'auto';           /* 隐私模式下 localStorage 会抛异常，不能因此白屏 */
  }
}

export function prefersLight() {
  if (!media && window.matchMedia) media = window.matchMedia('(prefers-color-scheme: light)');
  return !!(media && media.matches);
}

export function resolvedTheme(mode) {
  const m = mode || storedMode();
  if (m === 'dark' || m === 'light') return m;
  return prefersLight() ? 'light' : 'dark';
}

export function currentTheme() {
  return document.documentElement.getAttribute('data-theme') || resolvedTheme();
}

export function apply(mode) {
  const m = MODES.indexOf(mode) >= 0 ? mode : 'auto';
  const t = resolvedTheme(m);
  document.documentElement.setAttribute('data-theme', t);
  document.documentElement.setAttribute('data-theme-mode', m);
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', META[t]);
  /* URL 强制态只影响本次渲染，不写记忆 —— 否则用户演示完一次，自己的偏好就被改掉了 */
  if (!urlOverride()) {
    try { localStorage.setItem(KEY, m); } catch (e) { /* 存不了就只影响下次启动 */ }
  }
  document.dispatchEvent(new CustomEvent('sd:theme', { detail: { mode: m, theme: t } }));
  return t;
}

export function cycle() {
  const order = ['auto', 'dark', 'light'];
  const now = storedMode();
  return apply(order[(order.indexOf(now) + 1) % order.length]);
}

export const LABEL = {
  auto: '跟随系统',
  dark: '深色',
  light: '浅色'
};

/* 跟随系统时，系统切换要实时生效（否则用户改了系统外观，页面不动，会以为坏了） */
export function initTheme() {
  const mode = storedMode();
  apply(mode);
  if (!media && window.matchMedia) media = window.matchMedia('(prefers-color-scheme: light)');
  if (media) {
    const onChange = () => { if (storedMode() === 'auto') apply('auto'); };
    if (media.addEventListener) media.addEventListener('change', onChange);
    else if (media.addListener) media.addListener(onChange);
  }
  return mode;
}
