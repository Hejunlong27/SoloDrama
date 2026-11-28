<template>
  <button
    class="agentPet"
    :class="{ active, dragging }"
    type="button"
    :style="{ left: `${position.x}px`, top: `${position.y}px` }"
    :aria-label="active ? '收起 AI 对话' : '打开 AI 对话'"
    :aria-pressed="active"
    @pointerdown="startDrag"
    @pointermove="moveDrag"
    @pointerup="stopDrag"
    @pointercancel="stopDrag"
    @click="toggle">
    <span class="antenna"><i /></span>
    <span class="petEar left" /><span class="petEar right" />
    <span class="petFace"><i class="eye left" /><i class="eye right" /><i class="mouth" /></span>
    <span class="petBadge">AI</span>
  </button>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, reactive, ref } from "vue";

const props = defineProps<{ active: boolean }>();
const emit = defineEmits<{ toggle: [] }>();
const storageKey = "solodrama.agentPetPosition";
const position = reactive({ x: 0, y: 0 });
const dragging = ref(false);
let drag: { pointerId: number; startX: number; startY: number; x: number; y: number; moved: boolean } | undefined;
function clampPosition(x: number, y: number) {
  position.x = Math.max(8, Math.min(window.innerWidth - 76, x));
  position.y = Math.max(8, Math.min(window.innerHeight - 76, y));
}
function restore() {
  try {
    const value = JSON.parse(localStorage.getItem(storageKey) ?? "");
    if (Number.isFinite(value.x) && Number.isFinite(value.y)) return clampPosition(value.x, value.y);
  } catch { /* ACT: 首次使用时显示在右下角。 */ }
  clampPosition(window.innerWidth - 96, window.innerHeight - 150);
}
function startDrag(event: PointerEvent) {
  if (event.button !== 0) return;
  drag = { pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, x: position.x, y: position.y, moved: false };
  dragging.value = true;
  (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
}
function moveDrag(event: PointerEvent) {
  if (!drag || drag.pointerId !== event.pointerId) return;
  const dx = event.clientX - drag.startX;
  const dy = event.clientY - drag.startY;
  if (Math.abs(dx) + Math.abs(dy) > 5) drag.moved = true;
  clampPosition(drag.x + dx, drag.y + dy);
}
function stopDrag(event: PointerEvent) {
  if (!drag || drag.pointerId !== event.pointerId) return;
  const moved = drag.moved;
  drag = undefined;
  dragging.value = false;
  if (moved) localStorage.setItem(storageKey, JSON.stringify(position));
}
function toggle() {
  if (dragging.value || drag?.moved) return;
  emit("toggle");
}
function onResize() { clampPosition(position.x, position.y); localStorage.setItem(storageKey, JSON.stringify(position)); }
onMounted(() => { restore(); window.addEventListener("resize", onResize); });
onBeforeUnmount(() => window.removeEventListener("resize", onResize));
</script>

<style scoped lang="scss">
.agentPet { position: fixed; z-index: 80; width: 64px; height: 64px; padding: 0; border: 0; border-radius: 24px; background: transparent; cursor: grab; touch-action: none; &.dragging { cursor: grabbing; }.active { filter: drop-shadow(0 0 12px color-mix(in srgb, var(--el-color-primary) 55%, transparent)); } }
.antenna { position: absolute; left: 30px; top: 0; width: 4px; height: 12px; border-radius: 4px; background: #d8e8d7; i { position: absolute; left: -3px; top: -7px; width: 10px; height: 10px; border-radius: 50%; background: #b7ed57; box-shadow: 0 0 10px #b7ed57; } }
.petEar { position: absolute; top: 16px; width: 18px; height: 24px; border: 2px solid #d8e8d7; background: #101116; transform: rotate(25deg); border-radius: 10px 4px 14px 4px; &.left { left: 7px; }.right { right: 7px; transform: rotate(-25deg); border-radius: 4px 10px 4px 14px; } }
.petFace { position: absolute; inset: 20px 5px 4px; display: block; border: 2px solid #d8e8d7; border-radius: 40% 40% 46% 46%; background: linear-gradient(160deg, #f4f5ef, #cfd8ce); box-shadow: inset 0 -8px 12px #6b7e7130; animation: petFloat 3.2s ease-in-out infinite; }.dragging .petFace { animation: none; }.eye { position: absolute; top: 17px; width: 8px; height: 11px; border-radius: 50%; background: #18201b; &.left { left: 14px; }.right { right: 14px; } }.mouth { position: absolute; left: 50%; top: 31px; width: 8px; height: 4px; border-right: 2px solid #18201b; border-bottom: 2px solid #18201b; border-radius: 0 0 6px; transform: translateX(-50%) rotate(45deg); }.petBadge { position: absolute; right: -2px; bottom: -2px; display: grid; width: 22px; height: 22px; place-items: center; border-radius: 50%; color: #092016; background: #b7ed57; font-size: 9px; font-weight: 800; box-shadow: 0 4px 10px #0006; }
@keyframes petFloat { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-6px); } }
@media (prefers-reduced-motion: reduce) { .petFace { animation: none; } }
</style>