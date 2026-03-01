<script setup lang="ts">
import { ref, watch, onUnmounted } from 'vue'
import * as pdfjsLib from 'pdfjs-dist'
import { logger } from '../lib/logger'

pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.mjs',
  import.meta.url
).href

const props = defineProps<{
  pdfUrl: string
  pdfName?: string
}>()

const loading = ref(false)
const error = ref<string | null>(null)
const totalPages = ref(0)
const screenshotPage = ref(1)

let pdfDoc: pdfjsLib.PDFDocumentProxy | null = null

const SCREENSHOT_SCALE = 2
const MAX_CANVAS_DIM = 4096

watch(
  () => props.pdfUrl,
  async (url) => {
    if (!url) {
      pdfDoc = null
      totalPages.value = 0
      screenshotPage.value = 1
      return
    }
    logger.info('PdfViewer', `Загрузка PDF для скриншота: ${props.pdfName || url}`)
    loading.value = true
    error.value = null
    try {
      const loadingTask = pdfjsLib.getDocument({ url })
      pdfDoc = await loadingTask.promise
      totalPages.value = pdfDoc.numPages
      screenshotPage.value = 1
      logger.info('PdfViewer', `PDF загружен: ${pdfDoc.numPages} стр. (iframe + скриншот)`)
    } catch (e) {
      logger.error('PdfViewer', 'Ошибка загрузки PDF', e)
      error.value = e instanceof Error ? e.message : 'Ошибка загрузки PDF'
      pdfDoc = null
      totalPages.value = 0
    } finally {
      loading.value = false
    }
  },
  { immediate: true }
)

async function getCurrentPageImageUrlAsync(pageNum?: number): Promise<string> {
  const page = pageNum ?? screenshotPage.value
  logger.info('PdfViewer', `getCurrentPageImageUrlAsync: page=${page}, pdfDoc=${!!pdfDoc}, totalPages=${totalPages.value}`)
  if (!pdfDoc || page < 1 || page > totalPages.value) {
    logger.warn('PdfViewer', `getCurrentPageImageUrlAsync: выход без рендера (нет документа или неверная страница)`)
    return ''
  }
  try {
    const p = await pdfDoc.getPage(page)
    const viewport = p.getViewport({ scale: SCREENSHOT_SCALE })
    let w = Math.ceil(viewport.width)
    let h = Math.ceil(viewport.height)
    if (w > MAX_CANVAS_DIM || h > MAX_CANVAS_DIM) {
      const scale = Math.min(MAX_CANVAS_DIM / w, MAX_CANVAS_DIM / h)
      w = Math.ceil(w * scale)
      h = Math.ceil(h * scale)
    }
    const finalViewport = p.getViewport({
      scale: (viewport.scale * w) / viewport.width,
    })
    const canvas = document.createElement('canvas')
    canvas.width = w
    canvas.height = h
    const ctx = canvas.getContext('2d')
    if (!ctx) {
      logger.warn('PdfViewer', 'getCurrentPageImageUrlAsync: не удалось получить 2D контекст')
      return ''
    }
    await p.render({
      canvasContext: ctx,
      viewport: finalViewport,
    }).promise
    const dataUrl = canvas.toDataURL('image/png') || ''
    logger.info('PdfViewer', `getCurrentPageImageUrlAsync: страница ${page} отрендерена ${w}×${h}, dataURL длина=${dataUrl.length}`)
    return dataUrl
  } catch (e) {
    logger.error('PdfViewer', 'getCurrentPageImageUrlAsync: ошибка рендера страницы', e)
    return ''
  }
}

function clearMeasurements() {
  /* измерения в PDF отключены */
}

onUnmounted(() => {
  pdfDoc = null
})

defineExpose({
  getCurrentPageImageUrlAsync,
  get screenshotPage() {
    return screenshotPage.value
  },
  get totalPages() {
    return totalPages.value
  },
  clearMeasurements,
})
</script>

<template>
  <div class="pdf-viewer">
    <div v-if="loading" class="pdf-loading">Загрузка PDF…</div>
    <div v-else-if="error" class="pdf-error">{{ error }}</div>
    <template v-else>
      <div class="pdf-toolbar">
        <label class="pdf-screenshot-label">
          Страница для скриншота:
          <select v-model.number="screenshotPage" class="pdf-page-select">
            <option v-for="n in totalPages" :key="n" :value="n">{{ n }}</option>
          </select>
          <span class="pdf-total-pages">из {{ totalPages }}</span>
        </label>
      </div>
      <div class="pdf-iframe-wrap">
        <iframe
          v-if="pdfUrl"
          :src="pdfUrl"
          class="pdf-iframe"
          title="Просмотр PDF"
        />
        <div v-else class="pdf-placeholder">Нет PDF</div>
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
  gap: 0.5rem;
  padding: 0.5rem;
  background: #252525;
  border-bottom: 1px solid #333;
}
.pdf-screenshot-label {
  font-size: 0.9rem;
  color: #ccc;
  display: flex;
  align-items: center;
  gap: 0.35rem;
}
.pdf-page-select {
  padding: 0.25rem 0.5rem;
  font-size: 0.9rem;
  background: #333;
  color: #eee;
  border: 1px solid #444;
  border-radius: 4px;
  cursor: pointer;
}
.pdf-total-pages {
  color: #888;
  font-size: 0.85rem;
}
.pdf-iframe-wrap {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  display: flex;
}
.pdf-iframe {
  flex: 1;
  width: 100%;
  height: 100%;
  border: none;
  background: #fff;
}
.pdf-placeholder {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #666;
  font-size: 0.95rem;
}
</style>
