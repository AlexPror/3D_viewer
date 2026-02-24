<script setup lang="ts">
import { ref } from 'vue'
import type { ViewMode } from './components/ViewerToolbar.vue'
import Viewer3D from './components/Viewer3D.vue'
import ViewerToolbar from './components/ViewerToolbar.vue'
import PdfViewer from './components/PdfViewer.vue'
import ScreenshotEditorModal from './components/ScreenshotEditorModal.vue'

const viewMode = ref<ViewMode>('split')
const viewerRef = ref<InstanceType<typeof Viewer3D> | null>(null)
const pdfFile = ref<{ url: string; name: string } | null>(null)
const screenshotImageUrl = ref<string | null>(null)
const screenshotSuggestedFileName = ref<string | null>(null)
const showScreenshotModal = ref(false)

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

async function onScreenshot() {
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
      @update:view-mode="viewMode = $event"
      @open-pdf="onOpenPdf"
      @open-file="onOpenFile"
      @reset-view="onResetView"
      @screenshot="onScreenshot"
    />
    <div class="content" :class="'mode-' + viewMode">
      <div v-show="showPdfPanel()" class="panel pdf-panel">
        <PdfViewer v-if="pdfFile" :pdf-url="pdfFile.url" :pdf-name="pdfFile.name" />
        <div v-else class="panel-placeholder">Выберите PDF (чертежи, спецификация)</div>
      </div>
      <div v-show="show3dPanel()" class="panel viewer-panel">
        <Viewer3D ref="viewerRef" />
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
</style>
