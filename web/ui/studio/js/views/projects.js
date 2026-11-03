/* 全部项目：独立路由（深链 / 书签用）。导航里已并入「工作台」，
   这里只保留一份薄壳，内容与工作台里那块「项目」完全一致。 */
import { projectList } from './project-list.js';

export async function render(ctx) {
  const body = await projectList(ctx);
  return {
    html: '<div class="page-head"><div><h1 class="page-title">全部项目</h1>'
      + '<div class="page-sub">与工作台里的项目清单是<b>同一份实现</b>：排序、搜索、新建、扫描都在这一个地方。</div></div></div>'
      + '<div style="margin-top:-4px"></div>'
      + body.html,
    mount: (root) => body.mount(root)
  };
}
