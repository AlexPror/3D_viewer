<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
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

interface TileSpec {
  key: string
  tx: number
  ty: number
  cssLeft: number
  cssTop: number
  cssWidth: number
  cssHeight: number
  pixelLeft: number
  pixelTop: number
  pixelWidth: number
  pixelHeight: number
}

interface TileCacheEntry {
  canvas: HTMLCanvasElement
  lastUsedAt: number
}

const SCREENSHOT_SCALE = 2
const MAX_CANVAS_DIM = 4096
const MIN_ZOOM = 0.1
const MAX_ZOOM = 64
const TILE_CSS_SIZE = 1024
const TILE_OVERSCAN = 1
const MAX_DEVICE_PIXEL_RATIO = 2
const MAX_CACHE_TILES = 180
const MAX_CONCURRENT_RENDERS = 3

const loading = ref(false)
const error = ref<string | null>(null)
const totalPages = ref(0)
const screenshotPage = ref(1)
const zoom = ref(1)
const visibleTiles = ref<TileSpec[]>([])
const pageCssWidth = ref(0)
const pageCssHeight = ref(0)
const pageThumbnails = ref<Array<{ page: number; dataUrl: string }>>([])
const thumbsLoading = ref(false)

const viewportRef = ref<HTMLDivElement | null>(null)
const pageLayerRef = ref<HTMLDivElement | null>(null)

const zoomPercent = computed(() => `${Math.round(zoom.value * 100)}%`)

let pdfDoc: pdfjsLib.PDFDocumentProxy | null = null
let currentPageProxy: pdfjsLib.PDFPageProxy | null = null
let currentPageWidth = 0
let currentPageHeight = 0
let generation = 0
let updateTilesRaf = 0
let loadingTask: pdfjsLib.PDFDocumentLoadingTask | null = null
let resizeObserver: ResizeObserver | null = null
let thumbsGeneration = 0

const tileCanvasRefs = new Map<string, HTMLCanvasElement>()
const tileCache = new Map<string, TileCacheEntry>()
const renderQueue: TileSpec[] = []
const runningRenderTasks = new Map<string, pdfjsLib.RenderTask>()

let isPanning = false
let panStartX = 0
let panStartY = 0
let panScrollLeft = 0
let panScrollTop = 0

function clamp(v: number, min: number, max: number) {
  return Math.min(max, Math.max(min, v))
}

function effectiveDevicePixelRatio() {
  return Math.min(window.devicePixelRatio || 1, MAX_DEVICE_PIXEL_RATIO)
}

function tileKey(page: number, zoomBucket: number, dpr: number, tx: number, ty: number) {
  return `${page}:${zoomBucket}:${dpr}:${tx}:${ty}`
}

function zoomBucket(scale: number) {
  return Math.round((Math.log2(scale) || 0) * 4) / 4
}

function cancelAllRenders() {
  runningRenderTasks.forEach((task) => {
    try {
      task.cancel()
    } catch {
      // noop
    }
  })
  runningRenderTasks.clear()
  renderQueue.length = 0
}

function resetTileState() {
  cancelAllRenders()
  tileCache.clear()
  tileCanvasRefs.clear()
  visibleTiles.value = []
}

function markTileUsage(key: string) {
  const cached = tileCache.get(key)
  if (!cached) return
  cached.lastUsedAt = performance.now()
}

function trimCache() {
  if (tileCache.size <= MAX_CACHE_TILES) return
  const protectedKeys = new Set(visibleTiles.value.map((t) => t.key))
  const entries = [...tileCache.entries()]
    .filter(([key]) => !protectedKeys.has(key))
    .sort((a, b) => a[1].lastUsedAt - b[1].lastUsedAt)
  const toDelete = tileCache.size - MAX_CACHE_TILES
  for (let i = 0; i < Math.min(toDelete, entries.length); i += 1) {
    tileCache.delete(entries[i][0])
  }
}

function paintTileToDom(spec: TileSpec) {
  const domCanvas = tileCanvasRefs.get(spec.key)
  const cached = tileCache.get(spec.key)
  if (!domCanvas || !cached) return
  const ctx = domCanvas.getContext('2d')
  if (!ctx) return
  ctx.clearRect(0, 0, domCanvas.width, domCanvas.height)
  ctx.drawImage(cached.canvas, 0, 0)
}

function paintVisibleTiles() {
  visibleTiles.value.forEach((tile) => paintTileToDom(tile))
}

function enqueueVisibleTiles() {
  const queued = new Set(renderQueue.map((t) => t.key))
  for (const tile of visibleTiles.value) {
    if (tileCache.has(tile.key) || runningRenderTasks.has(tile.key) || queued.has(tile.key)) {
      markTileUsage(tile.key)
      continue
    }
    renderQueue.push(tile)
    queued.add(tile.key)
  }
  processRenderQueue()
}

async function renderTile(spec: TileSpec, localGeneration: number) {
  if (!currentPageProxy) return
  const dpr = effectiveDevicePixelRatio()
  const renderScale = zoom.value * dpr
  const viewport = currentPageProxy.getViewport({ scale: renderScale })
  const offscreen = document.createElement('canvas')
  offscreen.width = spec.pixelWidth
  offscreen.height = spec.pixelHeight
  const context = offscreen.getContext('2d', { alpha: false })
  if (!context) return
  const renderTask = currentPageProxy.render({
    canvasContext: context,
    viewport,
    transform: [1, 0, 0, 1, -spec.pixelLeft, -spec.pixelTop],
  })
  runningRenderTasks.set(spec.key, renderTask)
  try {
    await renderTask.promise
    if (localGeneration !== generation) return
    tileCache.set(spec.key, { canvas: offscreen, lastUsedAt: performance.now() })
    trimCache()
    paintTileToDom(spec)
  } catch (e) {
    const maybeError = e as { name?: string }
    if (maybeError?.name !== 'RenderingCancelledException') {
      logger.warn('PdfViewer', `Ошибка рендера тайла ${spec.key}`)
    }
  } finally {
    runningRenderTasks.delete(spec.key)
    processRenderQueue()
  }
}

function processRenderQueue() {
  if (!currentPageProxy) return
  while (runningRenderTasks.size < MAX_CONCURRENT_RENDERS && renderQueue.length > 0) {
    const spec = renderQueue.shift()
    if (!spec) break
    if (tileCache.has(spec.key) || runningRenderTasks.has(spec.key)) continue
    void renderTile(spec, generation)
  }
}

function computeVisibleTiles() {
  const viewport = viewportRef.value
  if (!viewport || !currentPageProxy || pageCssWidth.value <= 0 || pageCssHeight.value <= 0) {
    visibleTiles.value = []
    return
  }
  const dpr = effectiveDevicePixelRatio()
  const bucket = zoomBucket(zoom.value)
  const startX = Math.max(0, Math.floor(viewport.scrollLeft / TILE_CSS_SIZE) - TILE_OVERSCAN)
  const startY = Math.max(0, Math.floor(viewport.scrollTop / TILE_CSS_SIZE) - TILE_OVERSCAN)
  const endX = Math.max(
    startX,
    Math.ceil((viewport.scrollLeft + viewport.clientWidth) / TILE_CSS_SIZE) + TILE_OVERSCAN
  )
  const endY = Math.max(
    startY,
    Math.ceil((viewport.scrollTop + viewport.clientHeight) / TILE_CSS_SIZE) + TILE_OVERSCAN
  )
  const nextTiles: TileSpec[] = []
  for (let ty = startY; ty <= endY; ty += 1) {
    const cssTop = ty * TILE_CSS_SIZE
    if (cssTop >= pageCssHeight.value) continue
    const cssHeight = Math.min(TILE_CSS_SIZE, pageCssHeight.value - cssTop)
    for (let tx = startX; tx <= endX; tx += 1) {
      const cssLeft = tx * TILE_CSS_SIZE
      if (cssLeft >= pageCssWidth.value) continue
      const cssWidth = Math.min(TILE_CSS_SIZE, pageCssWidth.value - cssLeft)
      const pixelLeft = Math.floor(cssLeft * dpr)
      const pixelTop = Math.floor(cssTop * dpr)
      const pixelWidth = Math.max(1, Math.ceil(cssWidth * dpr))
      const pixelHeight = Math.max(1, Math.ceil(cssHeight * dpr))
      nextTiles.push({
        key: tileKey(screenshotPage.value, bucket, dpr, tx, ty),
        tx,
        ty,
        cssLeft,
        cssTop,
        cssWidth,
        cssHeight,
        pixelLeft,
        pixelTop,
        pixelWidth,
        pixelHeight,
      })
    }
  }
  visibleTiles.value = nextTiles
  paintVisibleTiles()
  enqueueVisibleTiles()
}

function scheduleTilesUpdate() {
  if (updateTilesRaf) cancelAnimationFrame(updateTilesRaf)
  updateTilesRaf = requestAnimationFrame(() => {
    updateTilesRaf = 0
    computeVisibleTiles()
  })
}

async function loadPage(pageNum: number) {
  if (!pdfDoc) return
  const target = clamp(pageNum, 1, totalPages.value)
  generation += 1
  cancelAllRenders()
  currentPageProxy = await pdfDoc.getPage(target)
  const baseViewport = currentPageProxy.getViewport({ scale: 1 })
  currentPageWidth = baseViewport.width
  currentPageHeight = baseViewport.height
  screenshotPage.value = target
  pageCssWidth.value = currentPageWidth * zoom.value
  pageCssHeight.value = currentPageHeight * zoom.value
  tileCache.clear()
  await nextTick()
  scheduleTilesUpdate()
}

function updatePageCssSize() {
  pageCssWidth.value = currentPageWidth * zoom.value
  pageCssHeight.value = currentPageHeight * zoom.value
}

function onViewportScroll() {
  scheduleTilesUpdate()
}

function onTileCanvasRef(key: string, el: Element | null) {
  if (el instanceof HTMLCanvasElement) {
    tileCanvasRefs.set(key, el)
    const spec = visibleTiles.value.find((t) => t.key === key)
    if (spec) paintTileToDom(spec)
  } else {
    tileCanvasRefs.delete(key)
  }
}

function applyZoom(nextZoom: number, cursorClientX?: number, cursorClientY?: number) {
  const viewport = viewportRef.value
  if (!viewport || !currentPageProxy) return
  const prevZoom = zoom.value
  const z = clamp(nextZoom, MIN_ZOOM, MAX_ZOOM)
  if (Math.abs(z - prevZoom) < 1e-6) return
  const rect = viewport.getBoundingClientRect()
  const anchorX = cursorClientX !== undefined ? cursorClientX - rect.left : viewport.clientWidth / 2
  const anchorY = cursorClientY !== undefined ? cursorClientY - rect.top : viewport.clientHeight / 2
  const modelX = (viewport.scrollLeft + anchorX) / prevZoom
  const modelY = (viewport.scrollTop + anchorY) / prevZoom
  zoom.value = z
  updatePageCssSize()
  generation += 1
  cancelAllRenders()
  renderQueue.length = 0
  scheduleTilesUpdate()
  nextTick(() => {
    viewport.scrollLeft = modelX * z - anchorX
    viewport.scrollTop = modelY * z - anchorY
    scheduleTilesUpdate()
  })
}

function onViewportWheel(ev: WheelEvent) {
  if (!currentPageProxy) return
  ev.preventDefault()
  const factor = Math.exp(-ev.deltaY * 0.0015)
  applyZoom(zoom.value * factor, ev.clientX, ev.clientY)
}

function setZoomPreset(value: number) {
  applyZoom(value)
}

function onPanMouseDown(ev: MouseEvent) {
  if (ev.button !== 1) return
  const viewport = viewportRef.value
  if (!viewport) return
  ev.preventDefault()
  isPanning = true
  panStartX = ev.clientX
  panStartY = ev.clientY
  panScrollLeft = viewport.scrollLeft
  panScrollTop = viewport.scrollTop
}

function onPanMouseMove(ev: MouseEvent) {
  if (!isPanning) return
  const viewport = viewportRef.value
  if (!viewport) return
  const dx = ev.clientX - panStartX
  const dy = ev.clientY - panStartY
  viewport.scrollLeft = panScrollLeft - dx
  viewport.scrollTop = panScrollTop - dy
  scheduleTilesUpdate()
}

function onPanMouseUp() {
  isPanning = false
}

async function loadDocument(url: string) {
  if (!url) {
    pdfDoc = null
    currentPageProxy = null
    totalPages.value = 0
    screenshotPage.value = 1
    error.value = null
    resetTileState()
    pageThumbnails.value = []
    thumbsLoading.value = false
    return
  }
  logger.info('PdfViewer', `Загрузка PDF: ${props.pdfName || url}`)
  loading.value = true
  error.value = null
  try {
    if (loadingTask) {
      loadingTask.destroy()
      loadingTask = null
    }
    generation += 1
    cancelAllRenders()
    loadingTask = pdfjsLib.getDocument({ url })
    pdfDoc = await loadingTask.promise
    totalPages.value = pdfDoc.numPages
    zoom.value = 1
    await loadPage(1)
    void renderPageThumbnails()
    logger.info('PdfViewer', `PDF загружен: ${pdfDoc.numPages} стр.`)
  } catch (e) {
    logger.error('PdfViewer', 'Ошибка загрузки PDF', e)
    error.value = e instanceof Error ? e.message : 'Ошибка загрузки PDF'
    pdfDoc = null
    currentPageProxy = null
    totalPages.value = 0
    resetTileState()
    pageThumbnails.value = []
    thumbsLoading.value = false
  } finally {
    loading.value = false
  }
}

async function renderPageThumbnails() {
  if (!pdfDoc || totalPages.value <= 0) {
    pageThumbnails.value = []
    return
  }
  const localGen = ++thumbsGeneration
  thumbsLoading.value = true
  const next: Array<{ page: number; dataUrl: string }> = []
  try {
    for (let p = 1; p <= totalPages.value; p += 1) {
      if (!pdfDoc || localGen !== thumbsGeneration) return
      const page = await pdfDoc.getPage(p)
      const base = page.getViewport({ scale: 1 })
      const targetWidth = 150
      const scale = targetWidth / Math.max(1, base.width)
      const viewport = page.getViewport({ scale })
      const canvas = document.createElement('canvas')
      canvas.width = Math.max(1, Math.floor(viewport.width))
      canvas.height = Math.max(1, Math.floor(viewport.height))
      const ctx = canvas.getContext('2d')
      if (!ctx) continue
      await page.render({ canvasContext: ctx, viewport }).promise
      next.push({ page: p, dataUrl: canvas.toDataURL('image/png') })
      // progressive update so sidebar appears quickly
      pageThumbnails.value = [...next]
    }
  } catch (e) {
    logger.warn('PdfViewer', 'Не удалось отрендерить миниатюры страниц', e)
  } finally {
    if (localGen === thumbsGeneration) thumbsLoading.value = false
  }
}

watch(
  () => props.pdfUrl,
  async (url) => {
    await loadDocument(url)
  },
  { immediate: true }
)

watch(
  () => screenshotPage.value,
  async (page) => {
    if (!pdfDoc) return
    if (page < 1 || page > totalPages.value) return
    if (currentPageProxy?.pageNumber === page) return
    await loadPage(page)
  }
)

async function getCurrentPageImageUrlAsync(pageNum?: number): Promise<string> {
  const page = pageNum ?? screenshotPage.value
  logger.info('PdfViewer', `getCurrentPageImageUrlAsync: page=${page}, pdfDoc=${!!pdfDoc}, totalPages=${totalPages.value}`)
  if (!pdfDoc || page < 1 || page > totalPages.value) {
    logger.warn('PdfViewer', 'getCurrentPageImageUrlAsync: выход без рендера (нет документа или неверная страница)')
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
    logger.info('PdfViewer', `getCurrentPageImageUrlAsync: страница ${page} отрендерена ${w}x${h}`)
    return dataUrl
  } catch (e) {
    logger.error('PdfViewer', 'getCurrentPageImageUrlAsync: ошибка рендера страницы', e)
    return ''
  }
}

async function getPageTextContent(pageNum: number): Promise<string> {
  if (!pdfDoc || pageNum < 1 || pageNum > totalPages.value) return ''
  try {
    const p = await pdfDoc.getPage(pageNum)
    const content = await p.getTextContent()
    const parts: string[] = []
    let lastY: number | null = null
    for (const item of content.items) {
      const t = 'transform' in item && Array.isArray(item.transform) ? item.transform : []
      const y = t[5] ?? 0
      if (lastY !== null && Math.abs(y - lastY) > 2) parts.push('\n')
      lastY = y
      parts.push('str' in item ? (item as { str: string }).str : '')
    }
    return parts.join(' ').replace(/\n /g, '\n').trim()
  } catch (e) {
    logger.error('PdfViewer', 'getPageTextContent: ошибка', e)
    return ''
  }
}

function clearMeasurements() {
  /* измерения в PDF отключены */
}

function getScreenshotPage(): number {
  return screenshotPage.value
}

const emit = defineEmits<{
  'screenshot-2d': []
}>()

onMounted(() => {
  window.addEventListener('mousemove', onPanMouseMove)
  window.addEventListener('mouseup', onPanMouseUp)
  if (viewportRef.value) {
    resizeObserver = new ResizeObserver(() => scheduleTilesUpdate())
    resizeObserver.observe(viewportRef.value)
  }
})

onUnmounted(() => {
  thumbsGeneration += 1
  cancelAllRenders()
  if (loadingTask) loadingTask.destroy()
  if (updateTilesRaf) cancelAnimationFrame(updateTilesRaf)
  resizeObserver?.disconnect()
  window.removeEventListener('mousemove', onPanMouseMove)
  window.removeEventListener('mouseup', onPanMouseUp)
  tileCache.clear()
  tileCanvasRefs.clear()
  pdfDoc = null
  currentPageProxy = null
})

defineExpose({
  getCurrentPageImageUrlAsync,
  getPageTextContent,
  getScreenshotPage,
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
        <span class="pdf-toolbar-title">2D PDF</span>
        <label class="pdf-screenshot-label">
          Страница:
          <select v-model.number="screenshotPage" class="pdf-page-select">
            <option v-for="n in totalPages" :key="n" :value="n">{{ n }}</option>
          </select>
          <span class="pdf-total-pages">из {{ totalPages }}</span>
        </label>
        <div class="pdf-zoom-controls">
          <button type="button" class="pdf-zoom-btn" title="Уменьшить" @click="setZoomPreset(zoom / 1.2)">-</button>
          <span class="pdf-zoom-value">{{ zoomPercent }}</span>
          <button type="button" class="pdf-zoom-btn" title="Увеличить" @click="setZoomPreset(zoom * 1.2)">+</button>
          <button type="button" class="pdf-zoom-btn" title="100%" @click="setZoomPreset(1)">100%</button>
          <button type="button" class="pdf-zoom-btn" title="6400%" @click="setZoomPreset(64)">6400%</button>
        </div>
        <button
          type="button"
          class="pdf-screenshot-btn"
          title="Текущая страница PDF → редактор (как скриншот 3D, без захвата экрана Windows)"
          @click="emit('screenshot-2d')"
        >
          Скриншот 2D
        </button>
      </div>
      <div class="pdf-content">
        <aside class="pdf-thumbs">
          <div class="pdf-thumbs-title">Страницы</div>
          <div v-if="thumbsLoading && pageThumbnails.length === 0" class="pdf-thumbs-loading">Подготовка миниатюр...</div>
          <button
            v-for="item in pageThumbnails"
            :key="`thumb-${item.page}`"
            type="button"
            class="pdf-thumb-item"
            :class="{ active: screenshotPage === item.page }"
            @click="screenshotPage = item.page"
          >
            <img :src="item.dataUrl" :alt="`Стр. ${item.page}`" class="pdf-thumb-img" />
            <span class="pdf-thumb-label">{{ item.page }}</span>
          </button>
        </aside>
        <div
          ref="viewportRef"
          class="pdf-viewport"
          @scroll="onViewportScroll"
          @wheel="onViewportWheel"
          @mousedown="onPanMouseDown"
        >
          <div
            ref="pageLayerRef"
            class="pdf-page-layer"
            :style="{ width: `${pageCssWidth}px`, height: `${pageCssHeight}px` }"
          >
            <canvas
              v-for="tile in visibleTiles"
              :key="tile.key"
              :ref="(el) => onTileCanvasRef(tile.key, el)"
              class="pdf-tile-canvas"
              :width="tile.pixelWidth"
              :height="tile.pixelHeight"
              :style="{
                left: `${tile.cssLeft}px`,
                top: `${tile.cssTop}px`,
                width: `${tile.cssWidth}px`,
                height: `${tile.cssHeight}px`,
              }"
            />
          </div>
          <div v-if="!pdfUrl" class="pdf-placeholder">Нет PDF</div>
        </div>
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
  background: #1a2228;
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
  gap: 0.75rem;
  padding: 0.5rem 0.75rem;
  background: #252525;
  border-bottom: 1px solid #333;
}
.pdf-toolbar-title {
  font-weight: 600;
  color: #fff;
}
.pdf-screenshot-btn {
  margin-left: auto;
  padding: 0.3rem 0.55rem;
  font-size: 0.82rem;
  border-radius: 4px;
  cursor: pointer;
  border: 1px solid rgba(255, 255, 255, 0.15);
  color: #e0e0e0;
  background: rgba(80, 110, 150, 0.5);
}
.pdf-screenshot-btn:hover {
  background: rgba(100, 130, 180, 0.6);
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
.pdf-zoom-controls {
  display: flex;
  align-items: center;
  gap: 0.25rem;
}
.pdf-zoom-btn {
  padding: 0.25rem 0.5rem;
  font-size: 0.78rem;
  border-radius: 4px;
  border: 1px solid #4d4d4d;
  background: #313131;
  color: #ddd;
  cursor: pointer;
}
.pdf-zoom-btn:hover {
  background: #3b3b3b;
}
.pdf-zoom-value {
  min-width: 3.4rem;
  text-align: center;
  color: #aab9d8;
  font-size: 0.82rem;
}
.pdf-viewport {
  position: relative;
  flex: 1;
  min-height: 0;
  overflow: auto;
  background: #2a2a2a;
  cursor: default;
}
.pdf-content {
  display: flex;
  flex: 1;
  min-height: 0;
}
.pdf-thumbs {
  width: clamp(116px, 12vw, 170px);
  min-width: 108px;
  border-right: 1px solid #333;
  background: #232a31;
  padding: 0.45rem;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}
.pdf-thumbs-title {
  color: #c6d2e6;
  font-size: 0.78rem;
}
.pdf-thumbs-loading {
  color: #8ea2c2;
  font-size: 0.72rem;
}
.pdf-thumb-item {
  border: 1px solid #3f4f66;
  background: #2d3642;
  border-radius: 6px;
  padding: 4px;
  cursor: pointer;
  display: grid;
  gap: 4px;
}
.pdf-thumb-item.active {
  border-color: #6d8fd0;
  box-shadow: inset 0 0 0 1px rgba(109, 143, 208, 0.35);
}
.pdf-thumb-img {
  width: 100%;
  display: block;
  background: #fff;
}
.pdf-thumb-label {
  font-size: 0.72rem;
  color: #c7d6ee;
  text-align: center;
}
.pdf-page-layer {
  position: relative;
  margin: 0 auto;
  background: #fff;
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.3);
}
.pdf-tile-canvas {
  position: absolute;
  display: block;
  image-rendering: auto;
}
.pdf-placeholder {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #666;
  font-size: 0.95rem;
  pointer-events: none;
}
</style>
