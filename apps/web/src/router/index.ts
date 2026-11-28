import { createRouter, createWebHashHistory } from "vue-router";
import { useHelloStore } from "@/stores/hello";
import { useWorkspaceStore } from "@/stores/workspace";
import { settings } from "@/stores/settings";
import { actualPlatform } from "@/lib/platform";
import { publicWeb } from "@/stores/multiTenant";
import { adminRoute } from "@/pages/multiTenant/router";
const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: "/",
      redirect: () => {
        if (publicWeb.value) return "/home";
        if (actualPlatform.isLocalDesktop) {
          const launcher = settings.value.launcher && typeof settings.value.launcher === "object" && !Array.isArray(settings.value.launcher)
            ? settings.value.launcher as Record<string, unknown> : {};
          if (launcher.launcherOnboarded !== true && settings.value.helloCompleted !== true) return "/launcher";
          if (launcher.autoOpenWorkspace === false) return "/launcher";
        }
        return "/hello";
      },
    },
    {
      path: "/launcher",
      beforeEnter: () => actualPlatform.isLocalDesktop || { path: "/home", replace: true },
      component: () => import("@/pages/launcher/index.vue"),
    },
    {
      path: "/cloudCompute",
      beforeEnter: () => actualPlatform.isDesktop || { path: "/home", replace: true },
      component: () => import("@/components/settings/panels/cloudCompute/index.vue"),
    },
    {
      path: "/hello",
      beforeEnter: async () => publicWeb.value || await useHelloStore().load() ? { path: "/home", replace: true } : true,
      component: () => import("@/pages/hello/index.vue"),
    },
    {
      path: "/home",
      component: () => import("@/pages/home/index.vue"),
    },
    {
      path: "/canvas",
      redirect: "/workspace",
    },
    {
      path: "/workspace",
      beforeEnter: () => publicWeb.value && !useWorkspaceStore().project ? { path: "/home", replace: true } : true,
      component: () => import("@/pages/workspace/index.vue"),
    },
    adminRoute,
  ],
});
export default router;
