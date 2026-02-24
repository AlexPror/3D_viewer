<script setup lang="ts">
export type ViewMode = '2d' | '3d' | 'split'

defineProps<{
  viewMode: ViewMode
}>()

const emit = defineEmits<{
  'update:viewMode': [value: ViewMode]
  'open-pdf': []
  'open-file': []
  'reset-view': []
  'screenshot': []
}>()
</script>

<template>
  <header class="toolbar">
    <span class="title">3D Viewer</span>
    <div class="view-mode">
      <button
        type="button"
        class="mode-btn"
        :class="{ active: viewMode === '2d' }"
        @click="emit('update:viewMode', '2d')"
      >
        2D
      </button>
      <button
        type="button"
        class="mode-btn"
        :class="{ active: viewMode === '3d' }"
        @click="emit('update:viewMode', '3d')"
      >
        3D
      </button>
      <button
        type="button"
        class="mode-btn"
        :class="{ active: viewMode === 'split' }"
        @click="emit('update:viewMode', 'split')"
      >
        Совместный просмотр
      </button>
    </div>
    <div class="actions">
      <button type="button" @click="emit('open-pdf')">Открыть PDF</button>
      <button type="button" @click="emit('open-file')">Открыть файл</button>
      <button type="button" @click="emit('reset-view')">Вид по умолчанию</button>
      <button type="button" @click="emit('screenshot')">Скриншот</button>
    </div>
  </header>
</template>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.5rem 1rem;
  background: #1a1a1a;
  border-bottom: 1px solid #333;
  flex-shrink: 0;
}
.title {
  font-weight: 600;
  color: #fff;
}
.view-mode {
  display: flex;
  gap: 0.25rem;
}
.mode-btn {
  padding: 0.35rem 0.6rem;
  font-size: 0.85rem;
  background: #2a2a2a;
  color: #aaa;
  border: 1px solid #444;
  border-radius: 4px;
  cursor: pointer;
}
.mode-btn:hover {
  background: #333;
  color: #e0e0e0;
}
.mode-btn.active {
  background: #646cff;
  color: #fff;
  border-color: #646cff;
}
.actions {
  display: flex;
  gap: 0.5rem;
}
.actions button {
  padding: 0.4rem 0.8rem;
  font-size: 0.9rem;
  background: #2a2a2a;
  color: #e0e0e0;
  border: 1px solid #444;
  border-radius: 4px;
  cursor: pointer;
}
.actions button:hover {
  background: #333;
  border-color: #646cff;
}
</style>
