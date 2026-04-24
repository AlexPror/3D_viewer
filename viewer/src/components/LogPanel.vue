<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { logger } from '../lib/logger'
import type { LogLevel } from '../lib/logger'

const logText = ref('')
const logMode = ref<'full' | 'normal' | 'quiet'>(
  logger.getMinLevel() === 'debug'
    ? 'full'
    : logger.getMinLevel() === 'warn'
      ? 'quiet'
      : 'normal'
)
let unbind: (() => void) | null = null

function appendLine(line: string) {
  logText.value += (logText.value ? '\n' : '') + line
}

function loadInitial() {
  const entries = logger.getEntries()
  logText.value = entries
    .map((e) => `${e.time} | ${e.level.toUpperCase().padEnd(8, ' ')} | ${e.name} | ${e.message}`)
    .join('\n')
}

function saveLog() {
  const text = logger.getText()
  if (!text.trim()) {
    alert('В логе нет данных для сохранения.')
    return
  }
  const date = new Date()
  const stamp = date.toISOString().slice(0, 19).replace(/[-:T]/g, '-').replace(/\..*/, '')
  const name = `3d_viewer_${stamp}.log`
  const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  URL.revokeObjectURL(url)
}

function clearLog() {
  logger.clear()
  logText.value = ''
}

function onChangeLogMode() {
  const map: Record<'full' | 'normal' | 'quiet', LogLevel> = {
    full: 'debug',
    normal: 'info',
    quiet: 'warn',
  }
  logger.setMinLevel(map[logMode.value])
}

onMounted(() => {
  loadInitial()
  logger.setUiCallback(appendLine)
  unbind = () => logger.setUiCallback(null)
})

onUnmounted(() => {
  unbind?.()
})
</script>

<template>
  <div class="log-panel">
    <div class="log-toolbar">
      <label class="log-mode-label">Режим:</label>
      <select v-model="logMode" class="log-mode-select" @change="onChangeLogMode">
        <option value="full">Полный</option>
        <option value="normal">Обычный</option>
        <option value="quiet">Тихий</option>
      </select>
      <button type="button" class="log-btn" @click="saveLog">Сохранить лог</button>
      <button type="button" class="log-btn log-btn-clear" @click="clearLog">Очистить</button>
    </div>
    <textarea
      class="log-view"
      readonly
      :value="logText"
      placeholder="Логи загрузки и выполнения появятся здесь…"
      spellcheck="false"
    />
  </div>
</template>

<style scoped>
.log-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: #1e1e1e;
}
.log-toolbar {
  flex-shrink: 0;
  padding: 0.35rem 0.5rem;
  background: #252525;
  border-bottom: 1px solid #333;
  display: flex;
  gap: 0.5rem;
}
.log-mode-label {
  color: #d5dce8;
  font-size: 0.82rem;
  align-self: center;
}
.log-mode-select {
  padding: 0.25rem 0.45rem;
  background: #1f2b3f;
  color: #e7edf7;
  border: 1px solid #4a5f7a;
  border-radius: 4px;
  font-size: 0.82rem;
}
.log-btn {
  padding: 0.3rem 0.6rem;
  font-size: 0.85rem;
  background: rgba(70, 90, 120, 0.5);
  color: #e0e0e0;
  border: 1px solid rgba(100, 130, 180, 0.5);
  border-radius: 4px;
  cursor: pointer;
}
.log-btn:hover {
  background: rgba(100, 130, 180, 0.6);
}
.log-btn-clear {
  background: rgba(100, 60, 60, 0.5);
  border-color: rgba(140, 80, 80, 0.5);
}
.log-btn-clear:hover {
  background: rgba(140, 80, 80, 0.6);
}
.log-view {
  flex: 1;
  min-height: 0;
  margin: 0;
  padding: 0.5rem 0.75rem;
  font-family: Consolas, 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.4;
  color: #d4d4d4;
  background: #1e1e1e;
  border: none;
  resize: none;
  white-space: pre;
  overflow-wrap: normal;
  overflow-x: auto;
}
.log-view::placeholder {
  color: #666;
}
</style>
