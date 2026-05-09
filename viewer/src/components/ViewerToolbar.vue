<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'

export type ViewMode = '2d' | '3d' | 'split' | 'log'
export type MeasureSnapMode = 'intersection' | 'vertex' | 'face' | 'edge'
export type MeasureType = 'distance' | 'radius' | 'diameter' | 'arc' | 'hole-center-distance'

defineProps<{
  viewMode: ViewMode
  workspaceMode: 'engineering' | 'production'
}>()

const emit = defineEmits<{
  'update:viewMode': [value: ViewMode]
  'update:workspaceMode': [value: 'engineering' | 'production']
  'open-pdf': []
  'open-file': []
  'export-report': []
}>()

const fileMenuOpen = ref(false)
const fileMenuRef = ref<HTMLElement | null>(null)

function closeFileMenu() {
  fileMenuOpen.value = false
}

function onOpenPdf() {
  emit('open-pdf')
  closeFileMenu()
}

function onOpenFile() {
  emit('open-file')
  closeFileMenu()
}

function onExportReport() {
  emit('export-report')
  closeFileMenu()
}

function onDocumentClick(ev: MouseEvent) {
  const el = fileMenuRef.value
  if (!el || fileMenuOpen.value === false) return
  if (!el.contains(ev.target as Node)) closeFileMenu()
}

onMounted(() => document.addEventListener('click', onDocumentClick))
onUnmounted(() => document.removeEventListener('click', onDocumentClick))
</script>

<template>
  <header class="toolbar">
    <div class="toolbar-row">
      <div class="toolbar-left">
        <span class="title">3D Viewer</span>
        <div class="workspace-switch" role="tablist" aria-label="Режим интерфейса">
          <button
            type="button"
            class="workspace-switch-btn"
            :class="{ 'is-active': workspaceMode === 'engineering' }"
            role="tab"
            :aria-selected="workspaceMode === 'engineering'"
            @click="emit('update:workspaceMode', 'engineering')"
          >
            Инженерный
          </button>
          <button
            type="button"
            class="workspace-switch-btn"
            :class="{ 'is-active': workspaceMode === 'production' }"
            role="tab"
            :aria-selected="workspaceMode === 'production'"
            @click="emit('update:workspaceMode', 'production')"
          >
            Производство (QR)
          </button>
        </div>
      </div>

      <div class="toolbar-center">
        <div ref="fileMenuRef" class="file-menu-wrap">
          <button
            type="button"
            class="file-menu-trigger"
            :class="{ 'is-open': fileMenuOpen }"
            aria-haspopup="true"
            :aria-expanded="fileMenuOpen"
            @click.stop="fileMenuOpen = !fileMenuOpen"
          >
            <svg class="ico" viewBox="0 0 24 24" aria-hidden="true">
              <path
                fill="currentColor"
                d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zm4 18H6V4h7v5h5v11z"
              />
            </svg>
            Файл
          </button>
          <div v-show="fileMenuOpen" class="file-menu-dropdown" role="menu">
            <button type="button" class="file-menu-item" role="menuitem" @click="onOpenPdf">
              Открыть 2D PDF…
            </button>
            <button type="button" class="file-menu-item" role="menuitem" @click="onOpenFile">
              Открыть 3D модель…
            </button>
            <div class="file-menu-divider" />
            <button type="button" class="file-menu-item file-menu-item--soon" disabled title="В разработке">
              Сохранить проект сборки…
            </button>
            <button type="button" class="file-menu-item file-menu-item--soon" disabled title="В разработке">
              Открыть проект сборки…
            </button>
            <div class="file-menu-divider" />
            <button type="button" class="file-menu-item" role="menuitem" @click="onExportReport">
              Отчёт PDF из скриншотов…
            </button>
          </div>
        </div>

        <span class="toolbar-label">Экран</span>
        <div class="layout-modes" role="tablist" aria-label="Макет области просмотра">
          <button
            type="button"
            class="layout-btn"
            :class="{ active: viewMode === '2d' }"
            role="tab"
            :aria-selected="viewMode === '2d'"
            title="Только чертёж PDF"
            @click="emit('update:viewMode', '2d')"
          >
            <svg class="layout-ico" viewBox="0 0 24 24" aria-hidden="true">
              <path
                fill="currentColor"
                d="M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zm4 18H6V4h7v5h5v11zm-3-8H9v2h6v-2zm0-4H9v2h6V8z"
              />
            </svg>
            <span class="layout-text">2D</span>
          </button>
          <button
            type="button"
            class="layout-btn"
            :class="{ active: viewMode === '3d' }"
            role="tab"
            :aria-selected="viewMode === '3d'"
            title="Только 3D"
            @click="emit('update:viewMode', '3d')"
          >
            <svg class="layout-ico" viewBox="0 0 24 24" aria-hidden="true">
              <path
                fill="currentColor"
                d="M12 2l10 5v10l-10 5L2 17V7l10-5zm0 2.18L4.47 8.5 12 12.82 19.53 8.5 12 4.18zM4 9.72v6.56l7 3.5v-7.04l-7-4.02zm16 0l-7 4.02v7.04l7-3.5V9.72z"
              />
            </svg>
            <span class="layout-text">3D</span>
          </button>
          <button
            type="button"
            class="layout-btn"
            :class="{ active: viewMode === 'split' }"
            role="tab"
            :aria-selected="viewMode === 'split'"
            title="Чертёж и модель рядом"
            @click="emit('update:viewMode', 'split')"
          >
            <svg class="layout-ico" viewBox="0 0 24 24" aria-hidden="true">
              <path fill="currentColor" d="M4 4h8v16H4V4zm8 0h8v7h-8V4zm0 9h8v7h-8v-7z" />
            </svg>
            <span class="layout-text">Совмещ.</span>
          </button>
          <button
            type="button"
            class="layout-btn"
            :class="{ active: viewMode === 'log' }"
            role="tab"
            :aria-selected="viewMode === 'log'"
            title="Панель логов"
            @click="emit('update:viewMode', 'log')"
          >
            <svg class="layout-ico" viewBox="0 0 24 24" aria-hidden="true">
              <path
                fill="currentColor"
                d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-7 14H7v-2h5v2zm5-4H7v-2h10v2zm0-4H7V7h10v2z"
              />
            </svg>
            <span class="layout-text">Лог</span>
          </button>
        </div>

        <button type="button" class="toolbar-report-btn" title="Собрать PDF из скриншотов 2D/3D" @click="emit('export-report')">
          <svg class="ico" viewBox="0 0 24 24" aria-hidden="true">
            <path
              fill="currentColor"
              d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-9 14l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"
            />
          </svg>
          Отчёт
        </button>
      </div>
    </div>
  </header>
</template>

<style scoped>
.toolbar {
  display: flex;
  flex-direction: column;
  background: #1a1a1a;
  border-bottom: 1px solid #333;
  flex-shrink: 0;
  width: 100%;
  min-width: 0;
}
.toolbar-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.65rem 1rem;
  padding: 0.45rem 0.85rem;
}
.toolbar-left {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.65rem 1rem;
  min-width: 0;
}
.title {
  font-weight: 600;
  color: #fff;
  flex-shrink: 0;
  font-size: 1rem;
}
.workspace-switch {
  display: flex;
  gap: 0.35rem;
  flex-wrap: wrap;
}
.workspace-switch-btn {
  border: 1px solid #3a4a6a;
  background: #253247;
  color: #b5c7e4;
  font-size: 0.72rem;
  padding: 0.28rem 0.6rem;
  border-radius: 4px;
  cursor: pointer;
}
.workspace-switch-btn.is-active {
  background: #3f5f97;
  color: #eef3ff;
  border-color: #5c80c1;
}
.toolbar-center {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem 0.65rem;
  flex: 1;
  min-width: 0;
}
.toolbar-label {
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: #7a8aa5;
  margin-right: -0.15rem;
}

.file-menu-wrap {
  position: relative;
}
.file-menu-trigger {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.38rem 0.65rem;
  font-size: 0.85rem;
  border-radius: 6px;
  cursor: pointer;
  border: 1px solid rgba(100, 130, 180, 0.55);
  background: rgba(70, 95, 135, 0.55);
  color: #e8eef8;
}
.file-menu-trigger:hover,
.file-menu-trigger.is-open {
  background: rgba(90, 115, 165, 0.75);
  border-color: rgba(130, 160, 210, 0.75);
}
.file-menu-trigger .ico {
  width: 1.1rem;
  height: 1.1rem;
  opacity: 0.95;
}
.file-menu-dropdown {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  min-width: 15rem;
  padding: 0.35rem 0;
  background: #252b38;
  border: 1px solid #3d4d68;
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
  z-index: 200;
}
.file-menu-item {
  display: block;
  width: 100%;
  text-align: left;
  padding: 0.45rem 0.85rem;
  font-size: 0.82rem;
  border: none;
  background: transparent;
  color: #e0e8f0;
  cursor: pointer;
}
.file-menu-item:hover:not(:disabled) {
  background: rgba(74, 111, 199, 0.45);
}
.file-menu-item:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.file-menu-item--soon {
  color: #8a96a8;
}
.file-menu-divider {
  height: 1px;
  margin: 0.3rem 0;
  background: rgba(255, 255, 255, 0.08);
}

.layout-modes {
  display: flex;
  gap: 0.25rem;
  flex-wrap: wrap;
  align-items: center;
}
.layout-btn {
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.12rem;
  min-width: 3.35rem;
  padding: 0.35rem 0.45rem 0.3rem;
  border-radius: 8px;
  cursor: pointer;
  border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(55, 75, 110, 0.45);
  color: #c8d4ec;
}
.layout-btn:hover {
  background: rgba(70, 95, 140, 0.55);
}
.layout-btn.active {
  background: #4a6fc7;
  border-color: #6b8fd8;
  color: #fff;
}
.layout-ico {
  width: 1.35rem;
  height: 1.35rem;
  opacity: 0.95;
}
.layout-text {
  font-size: 0.68rem;
  font-weight: 600;
  line-height: 1;
}

.toolbar-report-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  margin-left: auto;
  padding: 0.38rem 0.65rem;
  font-size: 0.82rem;
  border-radius: 6px;
  cursor: pointer;
  border: 1px solid rgba(160, 130, 70, 0.55);
  background: rgba(110, 85, 45, 0.45);
  color: #f0e6d4;
}
.toolbar-report-btn:hover {
  background: rgba(140, 110, 55, 0.55);
}
.toolbar-report-btn .ico {
  width: 1.05rem;
  height: 1.05rem;
}

@media (max-width: 900px) {
  .toolbar-report-btn {
    margin-left: 0;
  }
}
</style>
