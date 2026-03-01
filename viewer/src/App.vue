<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { logger } from './lib/logger'
import { jsPDF } from 'jspdf'
import type { ViewMode, MeasureSnapMode, MeasureType } from './components/ViewerToolbar.vue'
import Viewer3D from './components/Viewer3D.vue'
import ViewerToolbar from './components/ViewerToolbar.vue'
import PdfViewer from './components/PdfViewer.vue'
import LogPanel from './components/LogPanel.vue'
import ScreenshotEditorModal from './components/ScreenshotEditorModal.vue'

const viewMode = ref<ViewMode>('split')
const viewerRef = ref<InstanceType<typeof Viewer3D> | null>(null)
const pdfViewerRef = ref<InstanceType<typeof PdfViewer> | null>(null)
const pdfFile = ref<{ url: string; name: string } | null>(null)
const screenshotImageUrl = ref<string | null>(null)
const screenshotSuggestedFileName = ref<string | null>(null)
const showScreenshotModal = ref(false)
const showScreenshotChoice = ref(false)
const sectionMode = ref(false)
const sectionActive = ref(false)
const sectionOffset = ref(0)
const measureMode = ref(false)
const measureSnapMode = ref<MeasureSnapMode>('intersection')
const measureType = ref<MeasureType>('distance')
const isDraggingFile = ref(false)

const MODEL_EXTENSIONS = ['stl', 'step', 'stp', 'igs', 'iges', 'glb', 'gltf']

let pdfInput: HTMLInputElement | null = null

function onDragOver(e: DragEvent) {
  if (!e.dataTransfer?.types.includes('Files')) return
  e.preventDefault()
  e.dataTransfer.dropEffect = 'copy'
  isDraggingFile.value = true
}

function onDragLeave() {
  isDraggingFile.value = false
}

function onDrop(e: DragEvent) {
  isDraggingFile.value = false
  if (!e.dataTransfer?.types.includes('Files')) return
  e.preventDefault()
  const file = e.dataTransfer.files?.[0]
  if (!file) return
  const ext = (file.name.split('.').pop() || '').toLowerCase()
  if (ext === 'pdf') {
    logger.info('App', `PDF открыт: ${file.name}`)
    if (pdfFile.value?.url) URL.revokeObjectURL(pdfFile.value.url)
    pdfFile.value = { url: URL.createObjectURL(file), name: file.name }
    return
  }
  if (MODEL_EXTENSIONS.includes(ext)) {
    logger.info('App', `3D файл сброшен: ${file.name}`)
    if (viewMode.value === '2d' || viewMode.value === 'log') viewMode.value = 'split'
    setTimeout(() => viewerRef.value?.loadModelFile?.(file), 0)
    return
  }
  alert('Поддерживаются PDF и 3D (STL, STEP, IGES, GLB)')
}

function onOpenPdf() {
  if (!pdfInput) {
    pdfInput = document.createElement('input')
    pdfInput.type = 'file'
    pdfInput.accept = '.pdf'
    pdfInput.onchange = () => {
      const file = pdfInput?.files?.[0]
      if (file) {
        logger.info('App', `PDF выбран: ${file.name}`)
        if (pdfFile.value?.url) URL.revokeObjectURL(pdfFile.value.url)
        pdfFile.value = { url: URL.createObjectURL(file), name: file.name }
      }
      if (pdfInput) pdfInput.value = ''
    }
  }
  pdfInput.click()
}

function onViewModeChange(mode: ViewMode) {
  viewMode.value = mode
  logger.info('App', `Режим вида: ${mode}`)
}

function onOpenFile() {
  logger.info('App', 'Открыть 3D модель (диалог)')
  viewerRef.value?.openFileDialog()
}

function onResetView() {
  logger.info('App', 'Вид 3D сброшен')
  viewerRef.value?.resetView?.()
}

function onExportGlb() {
  viewerRef.value?.exportGlb?.()
}

function onExportStl() {
  viewerRef.value?.exportStl?.()
}

const REPORT_LABELS_CYR = {
  drawing: 'Чертеж (PDF)',
  model: '3D модель',
  measurements: 'Измерения',
  length: 'Длина',
  mm: 'мм',
  noMeasurements: 'Измерения не проведены',
}
const REPORT_LABELS_LATIN = {
  drawing: 'Drawing (PDF)',
  model: '3D model',
  measurements: 'Measurements',
  length: 'Length',
  mm: 'mm',
  noMeasurements: 'No measurements',
}

async function loadCyrillicFont(doc: jsPDF): Promise<boolean> {
  const url = 'https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/notosans/NotoSans-Regular.ttf'
  try {
    const res = await fetch(url)
    if (!res.ok) return false
    const buf = await res.arrayBuffer()
    const bytes = new Uint8Array(buf)
    let binary = ''
    for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i])
    const base64 = btoa(binary)
    doc.addFileToVFS('NotoSansCyrillic.ttf', base64)
    doc.addFont('NotoSansCyrillic.ttf', 'NotoSans', 'normal')
    doc.setFont('NotoSans', 'normal')
    return true
  } catch {
    return false
  }
}

async function onExportReport() {
  const doc = new jsPDF({ orientation: 'portrait', unit: 'mm', format: 'a4' })
  const hasCyrillic = await loadCyrillicFont(doc)
  const REPORT_LABELS = hasCyrillic ? REPORT_LABELS_CYR : REPORT_LABELS_LATIN

  const margin = 15
  const maxImgH = 160
  let y = margin
  const lineH = 7

  const addImage = (dataUrl: string, title: string) => {
    return new Promise<void>((resolve, reject) => {
      const img = new Image()
      img.onload = () => {
        const isLandscape = img.width > img.height
        const pageW = doc.getPageWidth()
        const pageH = doc.getPageHeight()
        const imgW = pageW - margin * 2
        const scale = Math.min(imgW / img.width, maxImgH / img.height)
        const w = img.width * scale
        const h = img.height * scale

        if (isLandscape && w > pageH - margin * 2) {
          doc.addPage('a4', 'landscape')
          const landW = doc.getPageWidth()
          const landH = doc.getPageHeight()
          const landScale = Math.min((landW - margin * 2) / img.width, (landH - margin * 2 - 20) / img.height)
          const lw = img.width * landScale
          const lh = img.height * landScale
          doc.setFontSize(11)
          doc.text(title, margin, margin)
          doc.addImage(dataUrl, 'PNG', margin, margin + lineH, lw, lh)
          doc.addPage('a4', 'portrait')
          y = margin
        } else {
          if (y > pageH - maxImgH - 30) {
            doc.addPage()
            y = margin
          }
          doc.setFontSize(11)
          doc.text(title, margin, y)
          y += lineH
          doc.addImage(dataUrl, 'PNG', margin, y, w, h)
          y += h + lineH
        }
        resolve()
      }
      img.onerror = reject
      img.src = dataUrl
    })
  }

  try {
    if (pdfFile.value && pdfViewerRef.value) {
      const pdfImg = await pdfViewerRef.value.getCurrentPageImageUrlAsync?.()
      if (pdfImg) await addImage(pdfImg, REPORT_LABELS.drawing)
    }
    if (viewerRef.value) {
      const threeImg = await viewerRef.value.takeScreenshot()
      if (threeImg) await addImage(threeImg, REPORT_LABELS.model)
    }

    const pageH = doc.getPageHeight()
    if (y > pageH - 40) {
      doc.addPage()
      y = margin
    }
    doc.setFontSize(12)
    doc.text(REPORT_LABELS.measurements, margin, y)
    y += lineH + 2
    doc.setFontSize(10)
    const report = viewerRef.value?.getMeasurementReport?.()
    if (report) {
      if ('triangle' in report && report.triangle) {
        doc.text(
          `${REPORT_LABELS.length}: ${report.lengths[0].toFixed(2)} ${REPORT_LABELS.mm}  |  ${report.lengths[1].toFixed(2)} ${REPORT_LABELS.mm}  |  ${report.lengths[2].toFixed(2)} ${REPORT_LABELS.mm}`,
          margin,
          y
        )
      } else {
        doc.text(`${REPORT_LABELS.length}: ${report.length.toFixed(2)} ${REPORT_LABELS.mm}`, margin, y)
        y += lineH
        doc.text(
          `ΔX: ${report.dx.toFixed(2)} ${REPORT_LABELS.mm}  ΔY: ${report.dy.toFixed(2)} ${REPORT_LABELS.mm}  ΔZ: ${report.dz.toFixed(2)} ${REPORT_LABELS.mm}`,
          margin,
          y
        )
      }
    } else {
      doc.text(REPORT_LABELS.noMeasurements, margin, y)
    }
    const name = viewerRef.value?.getLoadedFileName?.() || pdfFile.value?.name || 'report'
    const base = name.replace(/\.[^.]+$/, '') || 'report'
    const date = new Date().toISOString().slice(0, 10)
    doc.save(`Отчет_${base}_${date}.pdf`)
  } catch (e) {
    console.error('Export report:', e)
    alert('Не удалось сформировать отчёт')
  }
}

function onSectionMode() {
  sectionMode.value = !sectionMode.value
  viewerRef.value?.setSectionMode?.(sectionMode.value)
}

function onFixSection() {
  sectionMode.value = false
  viewerRef.value?.setSectionMode?.(false)
}

function onClearSection() {
  sectionMode.value = false
  sectionActive.value = false
  viewerRef.value?.clearSection?.()
}

function onSectionActive() {
  sectionActive.value = true
  sectionOffset.value = 0
}

function onSectionInactive() {
  sectionActive.value = false
}

function onSectionOffsetChanged(value: number) {
  sectionOffset.value = value
}

function onSectionOffset(value: number) {
  sectionOffset.value = value
  viewerRef.value?.setSectionOffset?.(value)
}

function onMeasureSnapMode(mode: MeasureSnapMode) {
  measureSnapMode.value = mode
  viewerRef.value?.setMeasureSnapMode?.(mode)
}

function onMeasure() {
  logger.info('App', `onMeasure вызван, measureMode до переключения: ${measureMode.value}`)
  measureMode.value = !measureMode.value
  logger.info('App', `measureMode после переключения: ${measureMode.value} → передаём в 3D setMeasureMode`)
  viewerRef.value?.setMeasureMode?.(measureMode.value)
}

function onMeasureTypeUpdate(type: MeasureType) {
  measureType.value = type
  viewerRef.value?.setMeasureType?.(type)
}

function onClearMeasurements() {
  logger.info('App', 'onClearMeasurements вызван')
  viewerRef.value?.clearMeasurements?.()
  pdfViewerRef.value?.clearMeasurements?.()
}

function onScreenshotClick() {
  showScreenshotChoice.value = true
}

function closeScreenshotChoice() {
  showScreenshotChoice.value = false
}

async function onScreenshot2D() {
  closeScreenshotChoice()
  logger.info('App', `Скриншот 2D: pdfViewerRef=${!!pdfViewerRef.value}, pdfFile=${!!pdfFile.value}, getCurrentPageImageUrlAsync=${!!pdfViewerRef.value?.getCurrentPageImageUrlAsync}`)
  const url = await pdfViewerRef.value?.getCurrentPageImageUrlAsync?.()
  if (url) {
    logger.info('App', `Скриншот 2D: получено изображение, длина dataURL=${url.length}`)
    screenshotImageUrl.value = url
    screenshotSuggestedFileName.value = pdfFile.value?.name?.replace(/\.pdf$/i, '') ?? null
    showScreenshotModal.value = true
  } else {
    logger.warn('App', 'Скриншот 2D: пустой результат (нет PDF или ошибка рендера), см. логи PdfViewer')
    alert('Откройте PDF и дождитесь загрузки. Выберите страницу для скриншота в панели над просмотрщиком.')
  }
}

async function onScreenshot3D() {
  closeScreenshotChoice()
  logger.info('App', `Скриншот 3D: viewerRef=${!!viewerRef.value}, takeScreenshot=${!!viewerRef.value?.takeScreenshot}`)
  const url = await viewerRef.value?.takeScreenshot()
  if (url) {
    logger.info('App', `Скриншот 3D: получено изображение, длина=${url.length}`)
    screenshotImageUrl.value = url
    screenshotSuggestedFileName.value = viewerRef.value?.getLoadedFileName?.() ?? null
    showScreenshotModal.value = true
  } else {
    logger.warn('App', 'Скриншот 3D: пустой результат (модель не загружена?)')
  }
}

async function onScreenshotTab() {
  closeScreenshotChoice()
  logger.info('App', `Скриншот вкладки: getDisplayMedia=${!!navigator.mediaDevices?.getDisplayMedia}`)
  if (!navigator.mediaDevices?.getDisplayMedia) {
    logger.warn('App', 'Скриншот вкладки: API недоступен (нужен HTTPS и современный браузер)')
    alert('Захват вкладки недоступен. Используйте современный браузер и HTTPS.')
    return
  }
  try {
    const stream = await navigator.mediaDevices.getDisplayMedia({
      video: { displaySurface: 'browser' },
      audio: false,
    })
    logger.info('App', 'Скриншот вкладки: поток получен')
    const video = document.createElement('video')
    video.muted = true
    video.playsInline = true
    video.srcObject = stream
    const CAPTURE_WAIT_MS = 5000
    const pollStepMs = 100
    const waitForFrame = async (): Promise<{ w: number; h: number }> => {
      await video.play()
      const deadline = Date.now() + CAPTURE_WAIT_MS
      while (video.videoWidth === 0 || video.videoHeight === 0) {
        if (Date.now() >= deadline) throw new Error('timeout')
        await new Promise((r) => setTimeout(r, pollStepMs))
      }
      await new Promise((r) => requestAnimationFrame(r))
      return { w: video.videoWidth, h: video.videoHeight }
    }
    let w: number
    let h: number
    try {
      const size = await Promise.race([
        waitForFrame(),
        new Promise<never>((_, reject) =>
          setTimeout(() => reject(new Error('timeout')), CAPTURE_WAIT_MS + 500)
        ),
      ])
      w = size.w
      h = size.h
    } catch (err) {
      stream.getTracks().forEach((t) => t.stop())
      logger.warn('App', 'Скриншот вкладки: не удалось получить кадр за 5 с')
      alert('Не удалось получить кадр. Попробуйте снова или выберите вкладку явно.')
      return
    }
    logger.info('App', `Скриншот вкладки: видео размер ${w}×${h}`)
    const dpr = window.devicePixelRatio || 1
    const iframeEl = document.querySelector('.pdf-iframe') as HTMLElement | null
    let drawW = w
    let drawH = h
    let sx = 0
    let sy = 0
    let sw = w
    let sh = h
    if (iframeEl) {
      const rect = iframeEl.getBoundingClientRect()
      sx = Math.round(rect.left * dpr)
      sy = Math.round(rect.top * dpr)
      sw = Math.round(rect.width * dpr)
      sh = Math.round(rect.height * dpr)
      sx = Math.max(0, Math.min(sx, w - 1))
      sy = Math.max(0, Math.min(sy, h - 1))
      sw = Math.min(sw, w - sx)
      sh = Math.min(sh, h - sy)
      if (sw > 0 && sh > 0) {
        drawW = sw
        drawH = sh
        logger.info('App', `Скриншот вкладки: обрезка по iframe ${drawW}×${drawH}`)
      } else {
        sx = 0
        sy = 0
        sw = w
        sh = h
      }
    }
    const canvas = document.createElement('canvas')
    canvas.width = drawW
    canvas.height = drawH
    const ctx = canvas.getContext('2d')
    if (!ctx) {
      logger.warn('App', 'Скриншот вкладки: не удалось получить 2D контекст canvas')
      stream.getTracks().forEach((t) => t.stop())
      return
    }
    ctx.drawImage(video, sx, sy, sw, sh, 0, 0, drawW, drawH)
    const url = canvas.toDataURL('image/png')
    stream.getTracks().forEach((t) => t.stop())
    screenshotImageUrl.value = url
    screenshotSuggestedFileName.value = `вкладка-${new Date().toISOString().slice(0, 10)}`
    showScreenshotModal.value = true
    logger.info('App', `Скриншот вида вкладки получен, dataURL длина=${url.length}`)
  } catch (e) {
    if (e instanceof Error && e.name === 'NotAllowedError') {
      logger.info('App', 'Скриншот вкладки: пользователь отменил выбор источника')
    } else {
      logger.error('App', 'Скриншот вкладки: ошибка захвата', e)
      alert('Не удалось захватить вид. Убедитесь, что используется HTTPS.')
    }
  }
}

function closeScreenshotModal() {
  showScreenshotModal.value = false
  screenshotImageUrl.value = null
  screenshotSuggestedFileName.value = null
}

const showPdfPanel = () => viewMode.value === '2d' || viewMode.value === 'split'
const show3dPanel = () => viewMode.value === '3d' || viewMode.value === 'split'
const showLogPanel = () => viewMode.value === 'log'

onMounted(() => {
  window.addEventListener('dragover', onDragOver)
  window.addEventListener('drop', onDrop)
  window.addEventListener('dragleave', onDragLeave)
})

onUnmounted(() => {
  window.removeEventListener('dragover', onDragOver)
  window.removeEventListener('drop', onDrop)
  window.removeEventListener('dragleave', onDragLeave)
})
</script>

<template>
  <div class="app" :class="{ 'is-dragging-file': isDraggingFile }">
    <div v-if="isDraggingFile" class="drop-overlay">Отпустите файл (PDF или 3D)</div>
    <ViewerToolbar
      :view-mode="viewMode"
      :section-mode="sectionMode"
      :section-active="sectionActive"
      :section-offset="sectionOffset"
      :measure-mode="measureMode"
      :measure-snap-mode="measureSnapMode"
      :measure-type="measureType"
      @update:view-mode="onViewModeChange"
      @open-pdf="onOpenPdf"
      @open-file="onOpenFile"
      @reset-view="onResetView"
      @screenshot="onScreenshotClick"
      @section-mode="onSectionMode"
      @fix-section="onFixSection"
      @clear-section="onClearSection"
      @update:section-offset="onSectionOffset"
      @measure="onMeasure"
      @update:measure-snap-mode="onMeasureSnapMode"
      @update:measure-type="onMeasureTypeUpdate"
      @clear-measurements="onClearMeasurements"
      @export-glb="onExportGlb"
      @export-stl="onExportStl"
      @export-report="onExportReport"
    />
    <div class="content" :class="'mode-' + viewMode">
      <div v-show="showPdfPanel()" class="panel pdf-panel">
        <PdfViewer
          v-if="pdfFile"
          ref="pdfViewerRef"
          :pdf-url="pdfFile.url"
          :pdf-name="pdfFile.name"
        />
        <div v-else class="panel-placeholder">Выберите PDF (чертежи, спецификация)</div>
      </div>
      <div v-show="show3dPanel()" class="panel viewer-panel">
        <Viewer3D
        ref="viewerRef"
        @section-active="onSectionActive"
        @section-inactive="onSectionInactive"
        @section-offset-changed="onSectionOffsetChanged"
      />
      </div>
      <div v-show="showLogPanel()" class="panel log-panel-wrap">
        <LogPanel />
      </div>
    </div>
    <div v-if="showScreenshotChoice" class="screenshot-choice-overlay" @click.self="closeScreenshotChoice">
      <div class="screenshot-choice">
        <p class="screenshot-choice-title">Скриншот</p>
        <button type="button" class="screenshot-choice-btn" @click="onScreenshot2D">Скриншот 2D (PDF, страница из списка)</button>
        <button type="button" class="screenshot-choice-btn" @click="onScreenshotTab">Скриншот вида вкладки</button>
        <button type="button" class="screenshot-choice-btn" @click="onScreenshot3D">Скриншот 3D модели</button>
        <p class="screenshot-choice-hint">«Вид вкладки» — то, что сейчас на экране (текущая страница PDF и масштаб)</p>
        <button type="button" class="screenshot-choice-cancel" @click="closeScreenshotChoice">Отмена</button>
      </div>
    </div>
    <ScreenshotEditorModal
      v-if="showScreenshotModal && screenshotImageUrl"
      :image-url="screenshotImageUrl!"
      :suggested-file-name="screenshotSuggestedFileName"
      @close="closeScreenshotModal"
    />
  </div>
</template>

<style scoped>
.app {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
  position: relative;
}
.app.is-dragging-file {
  outline: 3px dashed #646cff;
  outline-offset: -3px;
}
.drop-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.2rem;
  color: #fff;
  pointer-events: none;
  z-index: 500;
}
.content {
  flex: 1;
  min-height: 0;
  display: flex;
}
.content.mode-split .panel {
  flex: 1;
  min-width: 0;
}
.content.mode-split .pdf-panel {
  flex: 0 0 50%;
}
.content.mode-split .viewer-panel {
  flex: 0 0 50%;
}
.content.mode-2d .pdf-panel {
  flex: 1;
  min-width: 0;
}
.content.mode-3d .viewer-panel {
  flex: 1;
  min-width: 0;
}
.content.mode-log .log-panel-wrap {
  flex: 1;
  min-width: 0;
}
.content.mode-log .pdf-panel,
.content.mode-log .viewer-panel {
  display: none;
}
.panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  position: relative;
}
.panel-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #888;
  font-size: 0.95rem;
}
.viewer-panel {
  position: relative;
}
.screenshot-choice-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.screenshot-choice {
  background: #252525;
  border: 1px solid #444;
  border-radius: 8px;
  padding: 1rem 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  min-width: 220px;
}
.screenshot-choice-title {
  margin: 0 0 0.25rem 0;
  font-size: 1rem;
  color: #e0e0e0;
}
.screenshot-choice-hint {
  margin: 0.35rem 0 0 0;
  font-size: 0.8rem;
  color: #888;
  max-width: 280px;
}
.screenshot-choice-btn {
  padding: 0.5rem 0.75rem;
  font-size: 0.9rem;
  background: #333;
  color: #e0e0e0;
  border: 1px solid #555;
  border-radius: 4px;
  cursor: pointer;
}
.screenshot-choice-btn:hover {
  background: #646cff;
  border-color: #646cff;
}
.screenshot-choice-cancel {
  padding: 0.35rem;
  font-size: 0.85rem;
  background: transparent;
  color: #888;
  border: none;
  cursor: pointer;
  margin-top: 0.25rem;
}
.screenshot-choice-cancel:hover {
  color: #ccc;
}
</style>
