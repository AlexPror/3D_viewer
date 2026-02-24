<script setup lang="ts">
const emit = defineEmits<{
  'open-file': []
  'screenshot': []
  'reset-view': []
}>()
</script>

<template>
  <header class="toolbar">
    <span class="title">3D Viewer</span>
    <div class="actions">
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
