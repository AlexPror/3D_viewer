<script setup lang="ts">
export type ViewMode = '2d' | '3d' | 'split'
export type MeasureSnapMode = 'intersection' | 'vertex' | 'face' | 'edge'

const SECTION_OFFSET_MIN = -2000
const SECTION_OFFSET_MAX = 2000
const SECTION_OFFSET_STEP = 10

defineProps<{
  viewMode: ViewMode
  sectionMode?: boolean
  sectionActive?: boolean
  sectionOffset?: number
  measureMode?: boolean
  measureSnapMode?: MeasureSnapMode
}>()

const emit = defineEmits<{
  'update:viewMode': [value: ViewMode]
  'open-pdf': []
  'open-file': []
  'reset-view': []
  'screenshot': []
  'section-mode': []
  'fix-section': []
  'clear-section': []
  'update:sectionOffset': [value: number]
  'measure': []
  'update:measureSnapMode': [value: MeasureSnapMode]
  'clear-measurements': []
  'export-glb': []
  'export-stl': []
}>()

function clampOffset(v: number) {
  return Math.min(SECTION_OFFSET_MAX, Math.max(SECTION_OFFSET_MIN, v))
}

function onOffsetInput(ev: Event) {
  const val = parseFloat((ev.target as HTMLInputElement).value)
  if (Number.isFinite(val)) emit('update:sectionOffset', clampOffset(val))
}

function onOffsetWheel(ev: WheelEvent, current: number) {
  ev.preventDefault()
  const delta = ev.deltaY > 0 ? -SECTION_OFFSET_STEP : SECTION_OFFSET_STEP
  emit('update:sectionOffset', clampOffset(current + delta))
}
</script>

<template>
  <header class="toolbar">
    <span class="title">3D Viewer</span>
    <div class="tool-groups">
      <div class="group group-file">
        <span class="group-label">Файл и вид</span>
        <button type="button" class="group-btn" @click="emit('open-pdf')">Открыть 2D PDF</button>
        <button type="button" class="group-btn" @click="emit('open-file')">Открыть 3D модель</button>
        <button type="button" class="group-btn" @click="emit('reset-view')">Вид по умолчанию</button>
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
        </div>
      </div>
      <div class="group group-section">
        <span class="group-label">Сечение</span>
        <button
          type="button"
          class="group-btn"
          :class="{ active: sectionMode }"
          @click="emit('section-mode')"
          title="Клик по модели задаёт плоскость сечения"
        >
          Сечение
        </button>
        <button
          type="button"
          class="btn-fix-section"
          title="Зафиксировать сечение (скриншот, измерение)"
          @click="emit('fix-section')"
        >
          ✓
        </button>
        <button
          type="button"
          class="btn-clear-section"
          title="Снять сечение"
          @click="emit('clear-section')"
        >
          ✕
        </button>
        <template v-if="sectionActive">
          <input
            type="number"
            class="offset-input"
            :min="SECTION_OFFSET_MIN"
            :max="SECTION_OFFSET_MAX"
            :step="SECTION_OFFSET_STEP"
            :value="sectionOffset ?? 0"
            @input="onOffsetInput"
            @wheel.prevent="onOffsetWheel($event, sectionOffset ?? 0)"
          />
          <input
            type="range"
            class="offset-slider"
            :min="SECTION_OFFSET_MIN"
            :max="SECTION_OFFSET_MAX"
            :step="SECTION_OFFSET_STEP"
            :value="sectionOffset ?? 0"
            @input="onOffsetInput"
          />
        </template>
      </div>
      <div class="group group-measure">
        <span class="group-label">Измерение</span>
        <button
          type="button"
          class="group-btn"
          :class="{ active: measureMode }"
          @click="emit('measure')"
        >
          Измерение
        </button>
        <button type="button" class="group-btn" @click="emit('clear-measurements')">Очистить</button>
        <select
          class="snap-select"
          :value="measureSnapMode ?? 'intersection'"
          @change="emit('update:measureSnapMode', ($event.target as HTMLSelectElement).value as MeasureSnapMode)"
        >
          <option value="intersection">Точка пересечения</option>
          <option value="vertex">Вершина</option>
          <option value="face">Центр грани</option>
          <option value="edge">Ребро</option>
        </select>
      </div>
      <div class="group group-export">
        <span class="group-label">Экспорт</span>
        <button type="button" class="group-btn" @click="emit('screenshot')">Скриншот</button>
        <button type="button" class="group-btn" @click="emit('export-glb')">Экспорт GLB</button>
        <button type="button" class="group-btn" @click="emit('export-stl')">Экспорт STL</button>
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
