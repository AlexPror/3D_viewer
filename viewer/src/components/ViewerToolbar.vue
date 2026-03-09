<script setup lang="ts">
export type ViewMode = '2d' | '3d' | 'split' | 'log'
export type MeasureSnapMode = 'intersection' | 'vertex' | 'face' | 'edge'
export type MeasureType = 'distance' | 'radius' | 'diameter' | 'arc' | 'hole-center-distance'

defineProps<{
  viewMode: ViewMode
}>()

const emit = defineEmits<{
  'update:viewMode': [value: ViewMode]
  'open-pdf': []
  'open-file': []
  'export-report': []
}>()
</script>

<template>
  <header class="toolbar">
    <span class="title">3D Viewer</span>
    <div class="tool-groups">
      <div class="group group-file">
        <button type="button" class="group-btn" @click="emit('open-pdf')">Открыть 2D PDF</button>
        <button type="button" class="group-btn" @click="emit('open-file')">Открыть 3D модель</button>
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
            Совм.
          </button>
          <button
            type="button"
            class="mode-btn"
            :class="{ active: viewMode === 'log' }"
            @click="emit('update:viewMode', 'log')"
            title="Панель логов"
          >
            Лог
          </button>
        </div>
        <button type="button" class="group-btn" @click="emit('export-report')">Отчёт из скриншотов</button>
      </div>
    </div>
  </header>
</template>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 0.5rem 1rem;
  background: #1a1a1a;
  border-bottom: 1px solid #333;
  flex-shrink: 0;
  min-width: 100%;
  width: 100%;
  flex-wrap: wrap;
}
.title {
  font-weight: 600;
  color: #fff;
  flex-shrink: 0;
}
.tool-groups {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  align-items: center;
  flex: 1;
  min-width: 0;
}
.group {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.25rem 0.5rem;
  border-radius: 6px;
}
.group-file {
  background: rgba(70, 90, 120, 0.35);
  border: 1px solid rgba(100, 130, 180, 0.5);
}
.group-section {
  background: rgba(60, 100, 80, 0.35);
  border: 1px solid rgba(80, 160, 120, 0.5);
}
.group-measure {
  background: rgba(100, 80, 120, 0.35);
  border: 1px solid rgba(140, 100, 180, 0.5);
}
.group-export {
  background: rgba(120, 90, 50, 0.35);
  border: 1px solid rgba(180, 140, 80, 0.5);
}
.group-label {
  font-size: 0.7rem;
  color: #999;
  text-transform: uppercase;
  margin-right: 0.2rem;
}
.group-btn,
.mode-btn {
  padding: 0.3rem 0.55rem;
  font-size: 0.82rem;
  border-radius: 4px;
  cursor: pointer;
  border: 1px solid rgba(255, 255, 255, 0.15);
  color: #e0e0e0;
}
.group-file .group-btn,
.group-file .mode-btn {
  background: rgba(80, 110, 150, 0.5);
}
.group-file .group-btn:hover,
.group-file .mode-btn:hover {
  background: rgba(100, 130, 180, 0.6);
}
.group-file .mode-btn.active {
  background: #4a6fc7;
  border-color: #5a7fd7;
}
.group-section .group-btn {
  background: rgba(60, 120, 90, 0.5);
}
.group-section .group-btn:hover {
  background: rgba(80, 150, 110, 0.6);
}
.group-section .group-btn.active {
  background: #2d8a5e;
  border-color: #3d9a6e;
}
.btn-fix-section {
  width: 2rem;
  padding: 0.3rem;
  font-size: 1.1rem;
  font-weight: bold;
  color: #0a0;
  background: rgba(40, 120, 60, 0.6);
  border: 1px solid #2d8a5e;
  border-radius: 4px;
  cursor: pointer;
}
.btn-fix-section:hover {
  background: rgba(60, 160, 80, 0.7);
  color: #0f0;
}
.btn-clear-section {
  width: 2rem;
  padding: 0.3rem;
  font-size: 1.1rem;
  font-weight: bold;
  color: #c00;
  background: rgba(120, 40, 40, 0.6);
  border: 1px solid #a03030;
  border-radius: 4px;
  cursor: pointer;
}
.btn-clear-section:hover {
  background: rgba(160, 50, 50, 0.7);
  color: #f00;
}
.group-measure .group-btn {
  background: rgba(100, 70, 130, 0.5);
}
.group-measure .group-btn:hover {
  background: rgba(130, 90, 160, 0.6);
}
.group-measure .group-btn.active {
  background: #6b4a8a;
  border-color: #7b5a9a;
}
.group-export .group-btn {
  background: rgba(140, 110, 60, 0.5);
}
.group-export .group-btn:hover {
  background: rgba(170, 130, 80, 0.6);
}
.view-mode {
  display: flex;
  gap: 0.2rem;
}
.offset-input {
  width: 4rem;
  padding: 0.25rem 0.35rem;
  font-size: 0.8rem;
  background: rgba(0, 0, 0, 0.3);
  color: #e0e0e0;
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 4px;
}
.offset-slider {
  width: 5rem;
  vertical-align: middle;
}
.measure-type-select,
.snap-select {
  padding: 0.25rem 0.4rem;
  font-size: 0.78rem;
  background: rgba(0, 0, 0, 0.3);
  color: #e0e0e0;
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 4px;
  cursor: pointer;
}
</style>
