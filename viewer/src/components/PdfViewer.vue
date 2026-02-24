<script setup lang="ts">
import { ref, watch, onUnmounted, nextTick } from 'vue'
import * as pdfjsLib from 'pdfjs-dist'

pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.mjs',
  import.meta.url
).href

const props = defineProps<{
  pdfUrl: string
  pdfName?: string
}>()

const canvasRef = ref<HTMLCanvasElement | null>(null)
const currentPage = ref(1)
const totalPages = ref(0)
const loading = ref(false)
const error = ref<string | null>(null)

let pdfDoc: pdfjsLib.PDFDocumentProxy | null = null

const LOG = '[PdfViewer]'

async function loadPdf() {
  if (!props.pdfUrl) {
    console.log(LOG, 'loadPdf skip: no pdfUrl')
    return
  }
  console.log(LOG, 'loadPdf start', props.pdfUrl)
  loading.value = true
  error.value = null
  try {
    const loadingTask = pdfjsLib.getDocument({ url: props.pdfUrl })
    pdfDoc = await loadingTask.promise
    totalPages.value = pdfDoc.numPages
    currentPage.value = 1
    console.log(LOG, 'doc loaded, pages:', pdfDoc.numPages)
  } catch (e) {
    console.error(LOG, 'loadPdf error', e)
    error.value = e instanceof Error ? e.message : 'Ошибка загрузки PDF'
  } finally {
    loading.value = false
    console.log(LOG, 'finally: loading=false, nextTick')
    await nextTick()
    if (totalPages.value > 0) {
      console.log(LOG, 'calling renderPage(1), canvasRef:', !!canvasRef.value)
      await renderPage(1)
      console.log(LOG, 'renderPage(1) done')
    }
  }
}

async function renderPage(num: number) {
  console.log(LOG, 'renderPage', num, 'pdfDoc:', !!pdfDoc, 'canvasRef:', !!canvasRef.value)
  if (!pdfDoc || !canvasRef.value) {
    console.warn(LOG, 'renderPage early return: no doc or canvas')
    return
  }
  const page = await pdfDoc.getPage(num)
  const ctx = canvasRef.value.getContext('2d')
  if (!ctx) {
    console.warn(LOG, 'renderPage: no 2d context')
    return
  }
  const scale = window.devicePixelRatio || 1
  const viewport = page.getViewport({ scale })
  canvasRef.value.width = viewport.width
  canvasRef.value.height = viewport.height
  canvasRef.value.style.width = viewport.width / scale + 'px'
  canvasRef.value.style.height = viewport.height / scale + 'px'
  console.log(LOG, 'renderPage', num, 'drawing viewport', viewport.width, 'x', viewport.height)
  await page.render({
    canvasContext: ctx,
    viewport,
  }).promise
  console.log(LOG, 'renderPage', num, 'done')
}

function prevPage() {
  console.log(LOG, 'prevPage', currentPage.value)
  if (currentPage.value <= 1) return
  currentPage.value--
  renderPage(currentPage.value)
}

function nextPage() {
  console.log(LOG, 'nextPage', currentPage.value)
  if (currentPage.value >= totalPages.value) return
  currentPage.value++
  renderPage(currentPage.value)
}

watch(
  () => props.pdfUrl,
  (url) => {
    console.log(LOG, 'watch pdfUrl', url)
    if (url) loadPdf()
    else {
      pdfDoc = null
      totalPages.value = 0
      currentPage.value = 1
    }
  },
  { immediate: true }
)

onUnmounted(() => {
  pdfDoc = null
})
</script>

<template>
  <div class="pdf-viewer">
    <div v-if="loading" class="pdf-loading">Загрузка PDF…</div>
    <div v-else-if="error" class="pdf-error">{{ error }}</div>
    <template v-else-if="totalPages > 0">
      <div class="pdf-toolbar">
        <button type="button" :disabled="currentPage <= 1" @click="prevPage">← Назад</button>
        <span class="page-info">{{ currentPage }} / {{ totalPages }}</span>
        <button type="button" :disabled="currentPage >= totalPages" @click="nextPage">Вперёд →</button>
      </div>
      <div class="pdf-canvas-wrap">
        <canvas ref="canvasRef" class="pdf-canvas" />
      </div>
    </template>
  </div>
</template>

<style scoped>
.pdf-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: #1a1a1a;
}
.pdf-loading,
.pdf-error {
  padding: 1rem;
  color: #aaa;
  text-align: center;
}
.pdf-error {
  color: #e57373;
}
.pdf-toolbar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  padding: 0.5rem;
  background: #252525;
  border-bottom: 1px solid #333;
}
.page-info {
  font-size: 0.9rem;
  color: #ccc;
}
.pdf-canvas-wrap {
  flex: 1;
  min-height: 0;
  overflow: auto;
  display: flex;
  justify-content: center;
  padding: 1rem;
}
.pdf-canvas {
  max-width: 100%;
  height: auto;
  background: #fff;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
}
</style>
