<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'

export type ViewMode = '2d' | '3d' | 'split' | 'log'
export type MeasureSnapMode = 'intersection' | 'vertex' | 'face' | 'edge'
export type MeasureType = 'distance' | 'radius' | 'diameter' | 'arc' | 'hole-center-distance' | 'cad-linear'

withDefaults(
  defineProps<{
    viewMode: ViewMode
    workspaceMode: 'engineering' | 'production'
    reportScreenshotCount?: number
    reportBasketPulse?: boolean
  }>(),
  {
    reportScreenshotCount: 0,
    reportBasketPulse: false,
  },
)

const emit = defineEmits<{
  'update:viewMode': [value: ViewMode]
  'update:workspaceMode': [value: 'engineering' | 'production']
  'open-pdf': []
  'open-file': []
  'export-report': []
  'open-report-gallery': []
  'save-assembly-project': []
  'open-assembly-project': []
  'save-pdf': []
  'save-pdf-as': []
  'save-3d': []
  'save-3d-as': []
  'show-logs': []
  'export-report-email': []
  'export-report-chat': []
  'telemost-join-project': []
  'telemost-create-meeting': []
  'open-settings': []
}>()

type MenuId = 'file' | 'mode' | 'logs' | 'report' | 'telemost' | null
const openMenu = ref<MenuId>(null)
const reportMenuTriggerRef = ref<HTMLButtonElement | null>(null)

defineExpose({
  getReportBadgeRect: (): DOMRect | null => reportMenuTriggerRef.value?.getBoundingClientRect() ?? null,
})

function setMenu(id: MenuId) {
  openMenu.value = openMenu.value === id ? null : id
}

function closeMenus() {
  openMenu.value = null
}

function run(fn: () => void) {
  fn()
  closeMenus()
}

function onDocumentClick(ev: MouseEvent) {
  const t = ev.target as Node
  if (!(t instanceof Element)) return
  if (t.closest('.toolbar-menu-wrap')) return
  closeMenus()
}

onMounted(() => document.addEventListener('click', onDocumentClick))
onUnmounted(() => document.removeEventListener('click', onDocumentClick))
</script>

<template>
  <header class="toolbar">
    <div class="toolbar-row">
      <div class="toolbar-brand">
        <span class="title">DeskReview</span>
      </div>

      <nav class="toolbar-menus" aria-label="Главное меню">
        <div class="toolbar-menu-wrap">
          <button
            type="button"
            class="toolbar-menu-trigger"
            :class="{ 'is-open': openMenu === 'file' }"
            aria-haspopup="true"
            :aria-expanded="openMenu === 'file'"
            @click.stop="setMenu('file')"
          >
            Файл
          </button>
          <div v-show="openMenu === 'file'" class="toolbar-menu-dropdown" role="menu">
            <button type="button" class="toolbar-menu-item" role="menuitem" @click="run(() => emit('open-pdf'))">
              Открыть 2D PDF…
            </button>
            <button type="button" class="toolbar-menu-item" role="menuitem" @click="run(() => emit('open-file'))">
              Открыть 3D модель…
            </button>
            <div class="toolbar-menu-divider" />
            <button type="button" class="toolbar-menu-item" role="menuitem" @click="run(() => emit('save-pdf'))">
              Сохранить замечания проекта (Ctrl+S)
            </button>
            <button type="button" class="toolbar-menu-item" role="menuitem" @click="run(() => emit('save-pdf-as'))">
              Сохранить замечания проекта…
            </button>
            <button type="button" class="toolbar-menu-item" role="menuitem" @click="run(() => emit('save-3d'))">
              Сохранить 3D
            </button>
            <button type="button" class="toolbar-menu-item" role="menuitem" @click="run(() => emit('save-3d-as'))">
              Сохранить 3D как…
            </button>
            <div class="toolbar-menu-divider" />
            <button type="button" class="toolbar-menu-item" role="menuitem" @click="run(() => emit('save-assembly-project'))">
              Сохранить проект сборки…
            </button>
            <button type="button" class="toolbar-menu-item" role="menuitem" @click="run(() => emit('open-assembly-project'))">
              Открыть проект сборки…
            </button>
            <div class="toolbar-menu-divider" />
            <button type="button" class="toolbar-menu-item" role="menuitem" @click="run(() => emit('open-settings'))">
              Настройки…
            </button>
          </div>
        </div>

        <div class="toolbar-menu-wrap">
          <button
            type="button"
            class="toolbar-menu-trigger"
            :class="{ 'is-open': openMenu === 'mode' }"
            aria-haspopup="true"
            :aria-expanded="openMenu === 'mode'"
            @click.stop="setMenu('mode')"
          >
            Режим
          </button>
          <div v-show="openMenu === 'mode'" class="toolbar-menu-dropdown toolbar-menu-dropdown--wide" role="menu">
            <div class="toolbar-menu-group-label">Интерфейс</div>
            <button
              type="button"
              class="toolbar-menu-item"
              role="menuitem"
              :class="{ 'is-checked': workspaceMode === 'engineering' }"
              @click="run(() => emit('update:workspaceMode', 'engineering'))"
            >
              Инженерный
            </button>
            <button
              type="button"
              class="toolbar-menu-item"
              role="menuitem"
              :class="{ 'is-checked': workspaceMode === 'production' }"
              @click="run(() => emit('update:workspaceMode', 'production'))"
            >
              Производство (QR)
            </button>
            <div class="toolbar-menu-divider" />
            <div class="toolbar-menu-group-label">Макет экрана</div>
            <button
              type="button"
              class="toolbar-menu-item"
              role="menuitem"
              :class="{ 'is-checked': viewMode === '2d' }"
              @click="run(() => emit('update:viewMode', '2d'))"
            >
              Только 2D PDF
            </button>
            <button
              type="button"
              class="toolbar-menu-item"
              role="menuitem"
              :class="{ 'is-checked': viewMode === '3d' }"
              @click="run(() => emit('update:viewMode', '3d'))"
            >
              Только 3D
            </button>
            <button
              type="button"
              class="toolbar-menu-item"
              role="menuitem"
              :class="{ 'is-checked': viewMode === 'split' }"
              @click="run(() => emit('update:viewMode', 'split'))"
            >
              Совмещённый (2D + 3D)
            </button>
          </div>
        </div>

        <div class="toolbar-menu-wrap">
          <button
            type="button"
            class="toolbar-menu-trigger"
            :class="{ 'is-open': openMenu === 'logs' }"
            aria-haspopup="true"
            :aria-expanded="openMenu === 'logs'"
            @click.stop="run(() => emit('show-logs'))"
          >
            Логи
          </button>
        </div>

        <div class="toolbar-menu-wrap">
          <button
            ref="reportMenuTriggerRef"
            type="button"
            class="toolbar-menu-trigger toolbar-menu-trigger--report"
            :class="{ 'is-open': openMenu === 'report' }"
            aria-haspopup="true"
            :aria-expanded="openMenu === 'report'"
            @click.stop="setMenu('report')"
          >
            Скриншот-отчёт
            <span
              v-if="reportScreenshotCount > 0"
              class="toolbar-menu-badge"
              :class="{ 'toolbar-menu-badge--pulse': reportBasketPulse }"
            >
              {{ reportScreenshotCount > 99 ? '99+' : reportScreenshotCount }}
            </span>
          </button>
          <div v-show="openMenu === 'report'" class="toolbar-menu-dropdown" role="menu">
            <button type="button" class="toolbar-menu-item toolbar-menu-item--basket" role="menuitem" @click="run(() => emit('open-report-gallery'))">
              <span>Все скриншоты</span>
              <span v-if="reportScreenshotCount > 0" class="toolbar-menu-item-badge">{{ reportScreenshotCount }}</span>
            </button>
            <div class="toolbar-menu-separator" role="separator" />
            <button type="button" class="toolbar-menu-item" role="menuitem" @click="run(() => emit('export-report'))">
              Экспорт скриншот-отчёта в PDF…
            </button>
            <button type="button" class="toolbar-menu-item" role="menuitem" @click="run(() => emit('export-report-email'))">
              Отправить скриншот-отчёт по почте…
            </button>
            <button type="button" class="toolbar-menu-item" role="menuitem" @click="run(() => emit('export-report-chat'))">
              Отправить скриншот-отчёт в чат
            </button>
          </div>
        </div>

        <div class="toolbar-menu-wrap">
          <button
            type="button"
            class="toolbar-menu-trigger toolbar-menu-trigger--telemost"
            :class="{ 'is-open': openMenu === 'telemost' }"
            aria-haspopup="true"
            :aria-expanded="openMenu === 'telemost'"
            @click.stop="setMenu('telemost')"
          >
            Телемост
          </button>
          <div v-show="openMenu === 'telemost'" class="toolbar-menu-dropdown" role="menu">
            <button type="button" class="toolbar-menu-item" role="menuitem" @click="run(() => emit('telemost-join-project'))">
              Присоединиться к звонку проекта
            </button>
            <button type="button" class="toolbar-menu-item" role="menuitem" @click="run(() => emit('telemost-create-meeting'))">
              Создать отдельную встречу…
            </button>
          </div>
        </div>
      </nav>
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
.toolbar-brand {
  flex-shrink: 0;
}
.title {
  font-weight: 700;
  color: #f0c878;
  font-size: 1.05rem;
  letter-spacing: 0.02em;
}
.toolbar-menus {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem;
  flex: 1;
  min-width: 0;
}
.toolbar-menu-wrap {
  position: relative;
}
.toolbar-menu-trigger {
  padding: 0.38rem 0.7rem;
  font-size: 0.84rem;
  border-radius: 6px;
  cursor: pointer;
  border: 1px solid rgba(100, 130, 180, 0.55);
  background: rgba(70, 95, 135, 0.55);
  color: #e8eef8;
}
.toolbar-menu-trigger:hover,
.toolbar-menu-trigger.is-open {
  background: rgba(90, 115, 165, 0.75);
  border-color: rgba(130, 160, 210, 0.75);
}
.toolbar-menu-trigger--telemost {
  border-color: rgba(120, 160, 120, 0.55);
  background: rgba(60, 95, 70, 0.5);
}
.toolbar-menu-trigger--report {
  position: relative;
}
.toolbar-menu-badge {
  position: absolute;
  top: -7px;
  right: -7px;
  min-width: 1.15rem;
  height: 1.15rem;
  padding: 0 4px;
  border-radius: 999px;
  background: #e85d04;
  color: #fff;
  font-size: 0.68rem;
  font-weight: 700;
  line-height: 1.15rem;
  text-align: center;
  pointer-events: none;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.35);
}
.toolbar-menu-badge--pulse {
  animation: report-badge-pulse 0.55s ease;
}
@keyframes report-badge-pulse {
  0%,
  100% {
    transform: scale(1);
  }
  50% {
    transform: scale(1.28);
  }
}
.toolbar-menu-item--basket {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  font-weight: 600;
}
.toolbar-menu-item-badge {
  min-width: 1.25rem;
  height: 1.25rem;
  padding: 0 6px;
  border-radius: 999px;
  background: #e85d04;
  color: #fff;
  font-size: 0.72rem;
  font-weight: 700;
  line-height: 1.25rem;
  text-align: center;
}
.toolbar-menu-separator {
  height: 1px;
  margin: 0.25rem 0.5rem;
  background: rgba(120, 140, 170, 0.35);
}
.toolbar-menu-dropdown {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  min-width: 16rem;
  padding: 0.35rem 0;
  background: #252b38;
  border: 1px solid #3d4d68;
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
  z-index: 300;
}
.toolbar-menu-dropdown--wide {
  min-width: 14rem;
}
.toolbar-menu-group-label {
  padding: 0.25rem 0.85rem 0.15rem;
  font-size: 0.62rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #7a8aa5;
}
.toolbar-menu-item {
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
.toolbar-menu-item:hover:not(:disabled) {
  background: rgba(74, 111, 199, 0.45);
}
.toolbar-menu-item.is-checked {
  color: #9ec4ff;
  font-weight: 600;
}
.toolbar-menu-item:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.toolbar-menu-divider {
  height: 1px;
  margin: 0.3rem 0;
  background: rgba(255, 255, 255, 0.08);
}
</style>
