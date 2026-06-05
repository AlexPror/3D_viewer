<script setup lang="ts">
export type ReportScreenshotItem = {
  id: string
  type: '2d' | '3d'
  dataUrl: string
  pdfFileName?: string
  pageNumber?: number
  albumCode?: string
  moduleNumber?: string
}

const props = defineProps<{
  open: boolean
  screenshots: ReportScreenshotItem[]
  projectName: string
  moduleNumber: string
  sheetNumber: string
  author: string
}>()

const emit = defineEmits<{
  close: []
  'update:projectName': [value: string]
  'update:moduleNumber': [value: string]
  'update:sheetNumber': [value: string]
  'update:author': [value: string]
  edit: [item: ReportScreenshotItem]
  remove: [item: ReportScreenshotItem]
  'move-up': [index: number]
  'move-down': [index: number]
  reorder: [fromIndex: number, toIndex: number]
  'send-chat': [item: ReportScreenshotItem]
  download: [item: ReportScreenshotItem]
  'export-pdf': []
  'export-email': []
  'export-chat': []
  'fill-first-sheet': []
}>()

function onScreenshotDragStart(e: DragEvent, index: number) {
  if (!e.dataTransfer) return
  e.dataTransfer.effectAllowed = 'move'
  e.dataTransfer.setData('text/plain', String(index))
}

function onScreenshotDragOver(e: DragEvent) {
  e.preventDefault()
  if (e.dataTransfer) e.dataTransfer.dropEffect = 'move'
}

function onScreenshotDrop(e: DragEvent, toIndex: number) {
  e.preventDefault()
  if (!e.dataTransfer) return
  const fromIndex = Number(e.dataTransfer.getData('text/plain'))
  if (Number.isNaN(fromIndex) || fromIndex === toIndex) return
  emit('reorder', fromIndex, toIndex)
}

function screenshotLabel(item: ReportScreenshotItem): string {
  if (item.type === '3d') return '3D'
  const page = item.pageNumber ?? '?'
  return `2D · стр. ${page}`
}
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="report-modal-overlay" @click.self="emit('close')">
      <div class="report-modal" role="dialog" aria-labelledby="report-modal-title" aria-modal="true">
        <header class="report-modal-header">
          <div class="report-modal-heading">
            <h2 id="report-modal-title">Скриншот-отчёт</h2>
            <span v-if="screenshots.length" class="report-modal-count">{{ screenshots.length }}</span>
          </div>
          <button type="button" class="report-modal-close" title="Закрыть" @click="emit('close')">×</button>
        </header>

        <section class="report-modal-params" aria-label="Параметры отчёта">
          <label class="report-modal-label">Шифр альбома:</label>
          <input
            :value="projectName"
            type="text"
            class="report-modal-input"
            placeholder="10-23-КП-Р-НВФ1.1"
            @input="emit('update:projectName', ($event.target as HTMLInputElement).value)"
          />
          <button type="button" class="report-modal-btn report-modal-btn--ghost" title="Взять с первого листа PDF" @click="emit('fill-first-sheet')">
            С 1-го листа
          </button>
          <label class="report-modal-label">Номер модуля:</label>
          <input
            :value="moduleNumber"
            type="text"
            class="report-modal-input"
            placeholder="например 3 или М1"
            @input="emit('update:moduleNumber', ($event.target as HTMLInputElement).value)"
          />
          <label class="report-modal-label">Номер листа:</label>
          <input
            :value="sheetNumber"
            type="text"
            class="report-modal-input report-modal-input--short"
            placeholder="1"
            @input="emit('update:sheetNumber', ($event.target as HTMLInputElement).value)"
          />
          <label class="report-modal-label">Автор замечаний:</label>
          <input
            :value="author"
            type="text"
            class="report-modal-input report-modal-input--wide"
            placeholder="Фамилия Имя"
            @input="emit('update:author', ($event.target as HTMLInputElement).value)"
          />
        </section>

        <div v-if="screenshots.length === 0" class="report-modal-empty">
          Сделайте скриншот кнопками «Скриншот 2D» или «Скриншот 3D» на панелях чертежа и 3D. После редактора снимок попадёт сюда — отсюда можно собрать PDF-отчёт.
        </div>
        <div v-else class="report-modal-grid">
          <article
            v-for="(item, index) in screenshots"
            :key="item.id"
            class="report-modal-card"
            draggable="true"
            @dragstart="onScreenshotDragStart($event, index)"
            @dragover="onScreenshotDragOver"
            @drop="onScreenshotDrop($event, index)"
          >
            <button type="button" class="report-modal-card-preview" @click="emit('edit', item)">
              <img :src="item.dataUrl" :alt="item.type" class="report-modal-thumb" draggable="false" />
              <span class="report-modal-type">{{ screenshotLabel(item) }}</span>
            </button>
            <div class="report-modal-card-actions">
              <button type="button" class="report-modal-icon-btn" title="Выше в отчёте" :disabled="index === 0" @click="emit('move-up', index)">↑</button>
              <button
                type="button"
                class="report-modal-icon-btn"
                title="Ниже в отчёте"
                :disabled="index === screenshots.length - 1"
                @click="emit('move-down', index)"
              >
                ↓
              </button>
              <button type="button" class="report-modal-icon-btn" title="Редактировать" @click="emit('edit', item)">✎</button>
              <button type="button" class="report-modal-icon-btn" title="Сохранить на ПК" @click="emit('download', item)">↓</button>
              <button type="button" class="report-modal-icon-btn report-modal-icon-btn--chat" title="В чат" @click="emit('send-chat', item)">Чат</button>
              <button type="button" class="report-modal-icon-btn report-modal-icon-btn--remove" title="Удалить" @click="emit('remove', item)">×</button>
            </div>
          </article>
        </div>

        <footer class="report-modal-footer">
          <button type="button" class="report-modal-btn report-modal-btn--primary" @click="emit('export-pdf')">
            Экспорт отчёта в PDF…
          </button>
          <button type="button" class="report-modal-btn" @click="emit('export-email')">Отправить по почте…</button>
          <button type="button" class="report-modal-btn" @click="emit('export-chat')">Отправить отчёт в чат</button>
          <button type="button" class="report-modal-btn report-modal-btn--ghost" @click="emit('close')">Закрыть</button>
        </footer>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.report-modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 11000;
  background: rgba(8, 12, 22, 0.72);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem;
}
.report-modal {
  width: min(920px, 100%);
  max-height: min(90vh, 820px);
  display: flex;
  flex-direction: column;
  background: #1e2433;
  border: 1px solid #3a4a6a;
  border-radius: 10px;
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.45);
  overflow: hidden;
}
.report-modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid #3a4a6a;
  background: #252b38;
}
.report-modal-heading {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.report-modal-heading h2 {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 600;
  color: #f0c878;
}
.report-modal-count {
  min-width: 1.35rem;
  height: 1.35rem;
  padding: 0 6px;
  border-radius: 999px;
  background: #e85d04;
  color: #fff;
  font-size: 0.75rem;
  font-weight: 700;
  line-height: 1.35rem;
  text-align: center;
}
.report-modal-close {
  width: 2rem;
  height: 2rem;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: #c8d4e8;
  font-size: 1.35rem;
  line-height: 1;
  cursor: pointer;
}
.report-modal-close:hover {
  background: rgba(255, 255, 255, 0.08);
}
.report-modal-params {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem 0.6rem;
  padding: 0.65rem 1rem;
  border-bottom: 1px solid #2f3d55;
}
.report-modal-label {
  font-size: 0.8rem;
  color: #8a9bb5;
  white-space: nowrap;
}
.report-modal-input {
  width: 10rem;
  max-width: 140px;
  padding: 0.3rem 0.45rem;
  font-size: 0.85rem;
  background: #2d3a52;
  border: 1px solid #4a5f7a;
  border-radius: 4px;
  color: #e0e8f0;
}
.report-modal-input--short {
  max-width: 64px;
}
.report-modal-input--wide {
  max-width: 180px;
}
.report-modal-empty {
  padding: 1.25rem 1rem;
  font-size: 0.88rem;
  color: #8a9bb5;
  line-height: 1.45;
}
.report-modal-grid {
  flex: 1;
  min-height: 0;
  overflow: auto;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(148px, 1fr));
  gap: 0.75rem;
  padding: 0.85rem 1rem;
}
.report-modal-card {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  background: #252525;
  border: 1px solid #3a4a6a;
  border-radius: 8px;
  padding: 0.35rem;
  cursor: grab;
  user-select: none;
}
.report-modal-card:active {
  cursor: grabbing;
}
.report-modal-card-preview {
  position: relative;
  padding: 0;
  border: none;
  background: transparent;
  cursor: pointer;
  border-radius: 6px;
  overflow: hidden;
}
.report-modal-thumb {
  display: block;
  width: 100%;
  aspect-ratio: 4 / 3;
  object-fit: contain;
  background: #1a1a1a;
}
.report-modal-type {
  position: absolute;
  top: 4px;
  left: 4px;
  font-size: 0.68rem;
  color: #fff;
  background: rgba(0, 0, 0, 0.65);
  padding: 2px 6px;
  border-radius: 4px;
}
.report-modal-card-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 3px;
  justify-content: center;
}
.report-modal-icon-btn {
  min-width: 26px;
  height: 26px;
  padding: 0 5px;
  font-size: 0.78rem;
  border: none;
  border-radius: 4px;
  background: rgba(74, 111, 199, 0.9);
  color: #fff;
  cursor: pointer;
}
.report-modal-icon-btn:hover:not(:disabled) {
  background: #4a6fc7;
}
.report-modal-icon-btn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}
.report-modal-icon-btn--chat {
  font-size: 0.68rem;
}
.report-modal-icon-btn--remove {
  background: rgba(180, 60, 60, 0.92);
}
.report-modal-footer {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  padding: 0.75rem 1rem;
  border-top: 1px solid #3a4a6a;
  background: #252b38;
}
.report-modal-btn {
  padding: 0.42rem 0.75rem;
  font-size: 0.84rem;
  border-radius: 6px;
  border: 1px solid #4a5f7a;
  background: #3d4a62;
  color: #e0e8f0;
  cursor: pointer;
}
.report-modal-btn:hover {
  background: #4a6fc7;
  border-color: #5a7fd7;
}
.report-modal-btn--primary {
  background: #4a6fc7;
  border-color: #5a7fd7;
  font-weight: 600;
}
.report-modal-btn--primary:hover {
  background: #5a7fd7;
}
.report-modal-btn--ghost {
  background: transparent;
}
</style>
