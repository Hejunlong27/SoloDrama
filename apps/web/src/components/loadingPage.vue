<template>
  <teleport to="body">
    <div v-if="visible" class="loadingPage" role="status" aria-label="正在加载项目">
      <div class="logoWrap" :class="{ drawn, filling }" aria-hidden="true">
        <div class="logoOutline" @animationend="finishDrawing">
          <div ref="logoElement" class="logoPulse" v-html="logoSvg" />
        </div>
        <img class="logoFill" :src="logoUrl" alt="" @animationend="finishFilling" />
      </div>
    </div>
  </teleport>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import logoRaw from "@solodrama/assets/logo.svg?raw";
import logoUrl from "@solodrama/assets/logo.svg";

const props = defineProps<{ active: boolean }>();
const visible = defineModel<boolean>("visible", { default: false });
const drawn = defineModel<boolean>("drawn", { default: false });
const logoDocument = new DOMParser().parseFromString(logoRaw, "image/svg+xml");
// ACT: 仅拆分当前 Logo 的绝对 M 轮廓；相对路径需解析命令，填充始终复用原图。
for (const [index, path] of [...logoDocument.querySelectorAll("path")].entries()) {
  const contours = path.getAttribute("d")!.match(/M[^M]*/g)!;
  path.replaceWith(...contours.map(contour => {
    const outline = path.cloneNode(false) as SVGPathElement;
    outline.setAttribute("d", contour);
    outline.setAttribute("pathLength", "1");
    outline.setAttribute("data-part", String(index));
    return outline;
  }));
}
const logoSvg = new XMLSerializer().serializeToString(logoDocument.documentElement);
const logoElement = ref<HTMLElement>();
const filling = ref(false);
const motionPreference = window.matchMedia("(prefers-reduced-motion: reduce)");
const reducedMotion = ref(motionPreference.matches);

function updateMotionPreference(event: MediaQueryListEvent) {
  reducedMotion.value = event.matches;
}
motionPreference.addEventListener("change", updateMotionPreference);
onBeforeUnmount(() => motionPreference.removeEventListener("change", updateMotionPreference));

watch([() => props.active, reducedMotion], ([active, reducedMotion]) => {
  if (active) {
    if (!visible.value) {
      drawn.value = false;
      visible.value = true;
    }
    filling.value = false;
  }
  if (reducedMotion) {
    drawn.value = true;
    if (!active) visible.value = false;
  } else if (!active && drawn.value && visible.value) {
    filling.value = true;
  }
}, { immediate: true });

function finishDrawing(event: AnimationEvent) {
  if (event.target !== logoElement.value?.querySelector("path:last-of-type")) return;
  drawn.value = true;
  if (!props.active) filling.value = true;
}

function finishFilling() {
  if (!props.active) visible.value = false;
}
</script>

<style lang="scss" scoped>
.loadingPage {
  position: fixed;
  inset: 0;
  z-index: 1100;
  background: var(--el-bg-color);

  .logoWrap {
    position: absolute;
    top: 50dvh;
    left: 50vw;
    width: 96px;
    aspect-ratio: 1;
    transform: translate(-50%, -50%);

    .logoOutline {
      width: 100%;
      line-height: 0;
      will-change: opacity;

      :deep(svg) { display: block; width: 100%; height: auto; overflow: visible; }
      :deep(path) {
        stroke: #000;
        stroke-width: 14;
        stroke-linecap: round;
        stroke-linejoin: round;
        fill: none;
        stroke-dasharray: 1;
        stroke-dashoffset: 1;
        animation: logoDraw 0.65s linear both;
      }
      :deep(path[data-part="1"]) { animation-delay: 0.08s; }
    }

    .logoFill {
      position: absolute;
      inset: 0;
      display: block;
      width: 100%;
      height: 100%;
      opacity: 0;
      will-change: opacity;
    }

    &.drawn .logoOutline :deep(path) { animation: none; stroke-dashoffset: 0; }
    &.drawn .logoPulse { animation: logoPulse 0.9s ease-in-out infinite; will-change: opacity; }
    &.filling {
      .logoOutline { animation: logoOutlineOut 0.25s ease both; }
      .logoPulse { animation-play-state: paused; }
      .logoFill { animation: logoFill 0.25s ease both; }
    }

    @media (prefers-reduced-motion: reduce) {
      .logoOutline { opacity: 0; }
      .logoOutline :deep(path) { animation: none; }
      &.drawn .logoPulse { animation: none; }
      .logoFill { opacity: 1; }
    }
  }
}

@keyframes logoDraw {
  from { stroke-dashoffset: 1; }
  to { stroke-dashoffset: 0; }
}

@keyframes logoFill {
  0% { opacity: 0; }
  70%, 100% { opacity: 1; }
}

@keyframes logoOutlineOut {
  0% { opacity: 1; }
  70%, 100% { opacity: 0; }
}

@keyframes logoPulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.45; }
}
</style>
