<script setup lang="ts">
import { ref } from 'vue'
import type { ViewMode, MeasureSnapMode } from './components/ViewerToolbar.vue'
import Viewer3D from './components/Viewer3D.vue'
import ViewerToolbar from './components/ViewerToolbar.vue'
import PdfViewer from './components/PdfViewer.vue'
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

let pdfInput: HTMLInputElement | null = null

function onOpenPdf() {
  if (!pdfInput) {
    pdfInput = document.createElement('input')
    pdfInput.type = 'file'
    pdfInput.accept = '.pdf'
    pdfInput.onchange = () => {
      const file = pdfInput?.files?.[0]
      if (file) {
        if (pdfFile.value?.url) URL.revokeObjectURL(pdfFile.value.url)
        pdfFile.value = { url: URL.createObjectURL(file), name: file.name }
      }
      if (pdfInput) pdfInput.value = ''
    }
  }
  pdfInput.click()
}

function onOpenFile() {
  viewerRef.value?.openFileDialog()
}

function onResetView() {
  viewerRef.value?.resetView?.()
}

function onExportGlb() {
  viewerRef.value?.exportGlb?.()
}

function onExportStl() {
  viewerRef.value?.exportStl?.()
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
  measureMode.value = !measureMode.value
  viewerRef.value?.setMeasureMode?.(measureMode.value)
}

function onClearMeasurements() {
  viewerRef.value?.clearMeasurements?.()
}

function onScreenshotClick() {
  showScreenshotChoice.value = true
}

function closeScreenshotChoice() {
  showScreenshotChoice.value = false
}

async function onScreenshot2D() {
  closeScreenshotChoice()
  const url = pdfViewerRef.value?.getCurrentPageImageUrl?.()
  if (url) {
    screenshotImageUrl.value = url
    screenshotSuggestedFileName.value = pdfFile.value?.name?.replace(/\.pdf$/i, '') ?? null
    showScreenshotModal.value = true
  } else {
    alert('Откройте PDF и дождитесь загрузки страницы')
  }
}

async function onScreenshot3D() {
  closeScreenshotChoice()
  const url = await viewerRef.value?.takeScreenshot()
  if (url) {
    screenshotImageUrl.value = url
    screenshotSuggestedFileName.value = viewerRef.value?.getLoadedFileName?.() ?? null
    showScreenshotModal.value = true
  }
}

function closeScreenshotModal() {
  showScreenshotModal.value = false
  screenshotImageUrl.value = null
  screenshotSuggestedFileName.value = null
}

const showPdfPanel = () => viewMode.value === '2d' || viewMode.value === 'split'
const show3dPanel = () => viewMode.value === '3d' || viewMode.value === 'split'
</script>

<template>
  <div class="app">
    <ViewerToolbar
      :view-mode="viewMode"
      :section-mode="sectionMode"
      :section-active="sectionActive"
      :section-offset="sectionOffset"
      :measure-mode="measureMode"
      :measure-snap-mode="measureSnapMode"
      @update:view-mode="viewMode = $event"
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
      @clear-measurements="onClearMeasurements"
      @export-glb="onExportGlb"
      @export-stl="onExportStl"
    />
    <div class="content" :class="'mode-' + viewMode">
      <div v-show="showPdfPanel()" class="panel pdf-panel">
        <PdfViewer v-if="pdfFile" ref="pdfViewerRef" :pdf-url="pdfFile.url" :pdf-name="pdfFile.name" />
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
    </div>
    <div v-if="showScreenshotChoice" class="screenshot-choice-overlay" @click.self="closeScreenshotChoice">
      <div class="screenshot-choice">
        <p class="screenshot-choice-title">Скриншот</p>
        <button type="button" class="screenshot-choice-btn" @click="onScreenshot2D">Скриншот 2D (PDF)</button>
        <button type="button" class="screenshot-choice-btn" @click="onScreenshot3D">Скриншот 3D модели</button>
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
