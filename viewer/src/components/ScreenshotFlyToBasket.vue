<script setup lang="ts">
import { onMounted, ref } from 'vue'

const props = defineProps<{
  src: string
  fromX: number
  fromY: number
  toX: number
  toY: number
}>()

const emit = defineEmits<{
  done: []
}>()

const THUMB_W = 72
const THUMB_H = 54

const style = ref({
  transform: `translate(${props.fromX - THUMB_W / 2}px, ${props.fromY - THUMB_H / 2}px) scale(1)`,
  opacity: '1',
})

onMounted(() => {
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      style.value = {
        transform: `translate(${props.toX - THUMB_W / 2}px, ${props.toY - THUMB_H / 2}px) scale(0.35)`,
        opacity: '0.92',
      }
    })
  })
  window.setTimeout(() => emit('done'), 680)
})
</script>

<template>
  <div class="screenshot-fly" :style="style" aria-hidden="true">
    <img :src="src" alt="" class="screenshot-fly-img" />
  </div>
</template>

<style scoped>
.screenshot-fly {
  position: fixed;
  top: 0;
  left: 0;
  z-index: 12000;
  width: 72px;
  height: 54px;
  pointer-events: none;
  transition:
    transform 0.62s cubic-bezier(0.22, 0.61, 0.36, 1),
    opacity 0.62s ease;
  will-change: transform, opacity;
}
.screenshot-fly-img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  border-radius: 6px;
  border: 2px solid rgba(255, 173, 91, 0.95);
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.45);
  background: #1a1a1a;
}
</style>
