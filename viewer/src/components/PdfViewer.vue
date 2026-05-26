<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import * as pdfjsLib from 'pdfjs-dist'
import { logger } from '../lib/logger'
import {
  type PdfMarkupDocument,
  type PdfMarkupShape,
  type PdfMarkupTool,
  type PdfMarkupPoint,
  cloneMarkupDocument,
  getShapeHandles,
  hitTestShapeBody,
  syncPolylineBbox,
  isTwoPointShape,
  createEmptyMarkupDocument,
  DEFAULT_MARKUP_STYLE,
  downloadBlob,
  exportPdfWithMarkup,
  encodeMarkupSidecar,
  fetchMarkupSidecarForPdf,
  loadMarkupDocument,
  markupDocumentKey,
  parseMarkupSidecarBytes,
  type PdfMarkupSidecarFile,
  saveMarkupDocument,
  type PdfMarkupExportMode,
  newShapeId,
  pageShapes,
  pagesWithMarkup,
  shapeLabel,
  shapeRemarkStatus,
  ensureMarkupRemarkMeta,
  defaultRemarkMeta,
  type PdfMarkupDrawStyle,
} from '../lib/pdfMarkup'
import {
  type RemarkStatus,
  type RemarkStatusFilter,
  REMARK_STATUS_OPTIONS,
  remarkStatusLabel,
  remarkStatusCssClass,
} from '../lib/remarkStatus'

pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.mjs',
  import.meta.url
).href

const props = defineProps<{
  pdfUrl: string
  pdfName?: string
  /** Слой замечаний, переданный вместе с PDF (drop / выбор файлов) */
  markupSidecarBytes?: ArrayBuffer | null
}>()

const emit = defineEmits<{
  'open-pdf': []
  'markup-dirty': [dirty: boolean]
}>()

type PdfLeftTab = 'document' | 'remarks'
const pdfLeftTab = ref<PdfLeftTab>('document')

const markupDoc = ref<PdfMarkupDocument | null>(null)
const markupDirty = ref(false)
const markupTool = ref<PdfMarkupTool>('arrow')
const markupColor = ref('#cc0000')
const selectedShapeId = ref<string | null>(null)
const remarkStatusFilter = ref<RemarkStatusFilter>('all')
const markupExporting = ref(false)
const markupVisible = ref(localStorage.getItem('deskreview.showMarkup') !== '0')
const markupHairline = ref(localStorage.getItem('deskreview.pdfHairline') === '1')
const markupStrokeRel = ref(DEFAULT_MARKUP_STYLE.strokeRel)
const markupArrowRel = ref(DEFAULT_MARKUP_STYLE.arrowRel)
const markupFontRel = ref(DEFAULT_MARKUP_STYLE.fontRel)
const markupStyle = computed<PdfMarkupDrawStyle>(() => ({
  strokeRel: markupStrokeRel.value,
  arrowRel: markupArrowRel.value,
  fontRel: markupFontRel.value,
}))
let markupDirtyBaseline = '{}'
let markupAutosaveTimer: ReturnType<typeof setInterval> | null = null
let markupSaveDebounce: ReturnType<typeof setTimeout> | null = null
const markupUndoStack = ref<string[]>([])
const MARKUP_UNDO_MAX = 50
let markupUndoApplying = false

const isDrawingMarkup = ref(false)
const markupDrawStart = ref<{ x: number; y: number } | null>(null)
const markupDraftShape = ref<PdfMarkupShape | null>(null)

const remarksPagesList = computed(() => {
  if (!markupDoc.value) return []
  const pages = new Set<number>([screenshotPage.value, ...pagesWithMarkup(markupDoc.value)])
  return [...pages].sort((a, b) => a - b)
})

const currentPageShapes = computed(() => {
  if (!markupDoc.value) return []
  return pageShapes(markupDoc.value, screenshotPage.value)
})

const vectorPageShapes = computed(() =>
  currentPageShapes.value.filter((s) => s.type !== 'text'),
)

const filteredPageShapes = computed(() => {
  const shapes = currentPageShapes.value
  if (remarkStatusFilter.value === 'all') return shapes
  return shapes.filter((s) => shapeRemarkStatus(s) === remarkStatusFilter.value)
})

const selectedMarkupShape = computed(() => {
  if (!selectedShapeId.value) return null
  return currentPageShapes.value.find((s) => s.id === selectedShapeId.value) ?? null
})

const textPageShapes = computed(() =>
  currentPageShapes.value.filter((s): s is Extract<PdfMarkupShape, { type: 'text' }> => s.type === 'text'),
)

const selectedShapeHandles = computed(() => {
  if (!selectedShapeId.value) return [] as PdfMarkupPoint[]
  const sh = currentPageShapes.value.find((s) => s.id === selectedShapeId.value)
  if (!sh || sh.type === 'text') return []
  return getShapeHandles(sh)
})

/** Рамка выделения (нормализованные координаты 0…1) */
const selectedShapeSelectionRect = computed(() => {
  if (!selectedShapeId.value) return null
  const sh = currentPageShapes.value.find((s) => s.id === selectedShapeId.value)
  if (!sh || sh.type === 'text') return null
  const padX = pxToNormX(6)
  const padY = pxToNormY(6)
  let x1 = sh.x1
  let y1 = sh.y1
  let x2 = sh.x2
  let y2 = sh.y2
  if (sh.type === 'polyline' && sh.points.length > 0) {
    x1 = sh.x1
    y1 = sh.y1
    x2 = sh.x2
    y2 = sh.y2
  }
  let left = Math.min(x1, x2) - padX
  let top = Math.min(y1, y2) - padY
  let width = Math.abs(x2 - x1) + padX * 2
  let height = Math.abs(y2 - y1) + padY * 2
  const minW = pxToNormX(10)
  const minH = pxToNormY(10)
  if (width < minW) {
    const cx = (x1 + x2) / 2
    left = cx - minW / 2
    width = minW
  }
  if (height < minH) {
    const cy = (y1 + y2) / 2
    top = cy - minH / 2
    height = minH
  }
  return { x: left, y: top, width, height }
})

const polylinePreviewPoints = computed(() => {
  const pts = [...polylineDraft.value]
  if (polylineHover.value) pts.push(polylineHover.value)
  if (pts.length < 2) return ''
  return polylineSvgPoints(pts)
})

const pendingNewText = ref<{ x: number; y: number } | null>(null)
const pendingTextEnd = ref<{ x2: number; y2: number } | null>(null)
const editingText = ref('')
const isDraggingText = ref(false)
const polylineDraft = ref<PdfMarkupPoint[]>([])
const polylineHover = ref<PdfMarkupPoint | null>(null)
const markupEdit = ref<{
  pointerX: number
  pointerY: number
  handleIndex: number | null
  x1: number
  y1: number
  x2: number
  y2: number
  points?: PdfMarkupPoint[]
} | null>(null)
const isResizingText = ref(false)
const textResizeStart = ref<{
  pointerX: number
  pointerY: number
  x2: number
  y2: number
} | null>(null)
const textDragStart = ref<{
  pointerX: number
  pointerY: number
  x1: number
  y1: number
  x2: number
  y2: number
} | null>(null)
const HANDLE_HIT_R = 0.014

const DEFAULT_TEXT_W = 0.28
const DEFAULT_TEXT_H = 0.08

function syncMarkupDirtyFlag() {
  const dirty = JSON.stringify(markupDoc.value?.pages ?? {}) !== markupDirtyBaseline
  markupDirty.value = dirty
  emit('markup-dirty', dirty)
}

function markMarkupChanged() {
  syncMarkupDirtyFlag()
  scheduleMarkupAutosave()
}

function resetMarkupUndo() {
  markupUndoStack.value = []
}

function pushMarkupUndo() {
  if (markupUndoApplying || !markupDoc.value) return
  markupUndoStack.value.push(JSON.stringify(markupDoc.value.pages))
  if (markupUndoStack.value.length > MARKUP_UNDO_MAX) {
    markupUndoStack.value = markupUndoStack.value.slice(-MARKUP_UNDO_MAX)
  }
}

function undoMarkup(): boolean {
  if (!markupDoc.value || markupUndoStack.value.length === 0) return false
  markupUndoApplying = true
  const prev = markupUndoStack.value.pop()!
  markupDoc.value.pages = JSON.parse(prev) as PdfMarkupDocument['pages']
  clearMarkupSelection()
  polylineDraft.value = []
  polylineHover.value = null
  isDrawingMarkup.value = false
  markupDraftShape.value = null
  cancelTextOverlay()
  markupUndoApplying = false
  markMarkupChanged()
  return true
}

function scheduleMarkupAutosave() {
  if (markupSaveDebounce) clearTimeout(markupSaveDebounce)
  markupSaveDebounce = setTimeout(() => {
    markupSaveDebounce = null
    void persistMarkupDraft(true)
  }, 800)
}

function applyMarkupStyleFromSidecar(style?: PdfMarkupDrawStyle) {
  if (!style) return
  markupStrokeRel.value = style.strokeRel
  markupArrowRel.value = style.arrowRel
  markupFontRel.value = style.fontRel
}

function pickNewerMarkup(
  idb: PdfMarkupDocument | null,
  embedded: PdfMarkupDocument | null,
  key: string,
): PdfMarkupDocument {
  if (!embedded) return idb ?? createEmptyMarkupDocument(key)
  if (!idb) return { ...embedded, documentKey: key }
  const idbTs = Date.parse(idb.updatedAt ?? '') || 0
  const embTs = Date.parse(embedded.updatedAt ?? '') || 0
  if (embTs >= idbTs) return { ...embedded, documentKey: key }
  return idb
}

function mergeMarkupSidecar(sidecar: PdfMarkupSidecarFile, source: string) {
  if (!markupDoc.value) return
  const key = markupDocumentKey(props.pdfUrl, props.pdfName)
  markupDoc.value = pickNewerMarkup(markupDoc.value, sidecar.markup, key)
  ensureMarkupRemarkMeta(markupDoc.value)
  applyMarkupStyleFromSidecar(sidecar.style)
  markMarkupChanged()
  logger.info('PdfViewer', `Слой замечаний применён (${source})`)
}

async function tryAutoLoadMarkupSidecar() {
  if (props.markupSidecarBytes?.byteLength) {
    const sidecar = parseMarkupSidecarBytes(props.markupSidecarBytes)
    if (sidecar) mergeMarkupSidecar(sidecar, 'файл рядом с PDF')
    return
  }
  const remote = await fetchMarkupSidecarForPdf(props.pdfUrl, props.pdfName)
  if (remote) mergeMarkupSidecar(remote, 'URL рядом с PDF')
}

async function initMarkupForCurrentDocument() {
  if (!props.pdfUrl) {
    markupDoc.value = null
    markupDirty.value = false
    markupDirtyBaseline = '{}'
    resetMarkupUndo()
    emit('markup-dirty', false)
    return
  }
  const key = markupDocumentKey(props.pdfUrl, props.pdfName)
  const loaded = await loadMarkupDocument(key)
  markupDoc.value = loaded ?? createEmptyMarkupDocument(key)
  ensureMarkupRemarkMeta(markupDoc.value)
  resetMarkupUndo()
  await tryAutoLoadMarkupSidecar()
  if (markupDoc.value) ensureMarkupRemarkMeta(markupDoc.value)
  markupDirtyBaseline = JSON.stringify(markupDoc.value.pages)
  markupDirty.value = false
  emit('markup-dirty', false)
}

function toggleMarkupVisible() {
  markupVisible.value = !markupVisible.value
  localStorage.setItem('deskreview.showMarkup', markupVisible.value ? '1' : '0')
}

async function persistMarkupDraft(silent = false): Promise<boolean> {
  if (!markupDoc.value) return true
  try {
    await saveMarkupDocument(cloneMarkupDocument(markupDoc.value))
    markupDirtyBaseline = JSON.stringify(markupDoc.value.pages)
    markupDirty.value = false
    emit('markup-dirty', false)
    if (!silent) logger.info('PdfViewer', 'Черновик разметки сохранён в IndexedDB')
    return true
  } catch (e) {
    logger.error('PdfViewer', 'Ошибка сохранения разметки', e)
    return false
  }
}

function textBoxStyle(shape: PdfMarkupShape): Record<string, string> {
  const x1 = Math.min(shape.x1, shape.x2)
  const y1 = Math.min(shape.y1, shape.y2)
  const x2 = Math.max(shape.x1, shape.x2)
  const y2 = Math.max(shape.y1, shape.y2)
  const fontRel = shape.type === 'text' ? (shape.fontSize ?? markupFontRel.value) : markupFontRel.value
  const fontPx = Math.max(10, fontRel * pageBaseHeight.value)
  const color = shape.type === 'text' ? (shape.color ?? '#cc0000') : '#cc0000'
  return {
    left: `${x1 * 100}%`,
    top: `${y1 * 100}%`,
    width: `${(x2 - x1) * 100}%`,
    height: `${(y2 - y1) * 100}%`,
    fontSize: `${fontPx}px`,
    color,
  }
}

function pendingTextBoxStyle(): Record<string, string> {
  if (!pendingNewText.value) return {}
  const x = pendingNewText.value.x
  const y = pendingNewText.value.y
  const x2 = pendingTextEnd.value?.x2 ?? x + DEFAULT_TEXT_W
  const y2 = pendingTextEnd.value?.y2 ?? y + DEFAULT_TEXT_H
  const x1 = Math.min(x, x2)
  const y1 = Math.min(y, y2)
  return {
    left: `${x1 * 100}%`,
    top: `${y1 * 100}%`,
    width: `${Math.abs(x2 - x1) * 100}%`,
    height: `${Math.abs(y2 - y1) * 100}%`,
  }
}

function normPosFromEvent(ev: MouseEvent, allowOutside = false): { x: number; y: number } | null {
  const layer = pageLayerRef.value
  if (!layer || pageBaseWidth.value <= 0 || pageBaseHeight.value <= 0) return null
  const r = layer.getBoundingClientRect()
  const x = (ev.clientX - r.left) / r.width
  const y = (ev.clientY - r.top) / r.height
  if (!allowOutside && (x < 0 || x > 1 || y < 0 || y > 1)) return null
  return { x: clamp(x, 0, 1), y: clamp(y, 0, 1) }
}

function hitTestMarkupShape(x: number, y: number): string | null {
  if (!markupDoc.value) return null
  const shapes = pageShapes(markupDoc.value, screenshotPage.value)
  for (let i = shapes.length - 1; i >= 0; i--) {
    if (hitTestShapeBody(shapes[i], x, y)) return shapes[i].id
  }
  return null
}

function hitTestShapeHandleIndex(shape: PdfMarkupShape, x: number, y: number): number | null {
  const handles = getShapeHandles(shape)
  for (let i = 0; i < handles.length; i += 1) {
    const h = handles[i]
    if (Math.hypot(x - h.x, y - h.y) <= HANDLE_HIT_R) return i
  }
  return null
}

function polylineSvgPoints(points: PdfMarkupPoint[]): string {
  return points.map((p) => `${p.x},${p.y}`).join(' ')
}

function isDragDrawTool(tool: PdfMarkupTool): boolean {
  return tool === 'arrow' || tool === 'line' || tool === 'rect' || tool === 'ellipse'
}

function finishPolylineDraft() {
  if (!markupDoc.value || polylineDraft.value.length < 2) {
    polylineDraft.value = []
    polylineHover.value = null
    return
  }
  const points = polylineDraft.value.map((p) => ({ ...p }))
  const shape: PdfMarkupShape = {
    ...defaultRemarkMeta(),
    id: newShapeId(),
    type: 'polyline',
    points,
    x1: 0,
    y1: 0,
    x2: 0,
    y2: 0,
    color: markupColor.value,
    strokeRel: markupStrokeRel.value,
  }
  syncPolylineBbox(shape)
  pushMarkupUndo()
  pageShapes(markupDoc.value, screenshotPage.value).push(shape)
  selectedShapeId.value = shape.id
  markMarkupChanged()
  polylineDraft.value = []
  polylineHover.value = null
  markupTool.value = 'select'
}

function beginMarkupEdit(
  shape: PdfMarkupShape,
  handleIndex: number | null,
  ev: MouseEvent,
) {
  pushMarkupUndo()
  markupEdit.value = {
    pointerX: ev.clientX,
    pointerY: ev.clientY,
    handleIndex,
    x1: shape.x1,
    y1: shape.y1,
    x2: shape.x2,
    y2: shape.y2,
    points: shape.type === 'polyline' ? shape.points.map((p) => ({ ...p })) : undefined,
  }
}

function focusTextEditor(selector: string) {
  nextTick(() => {
    const el = document.querySelector(selector) as HTMLTextAreaElement | null
    el?.focus()
  })
}

function cancelTextOverlay() {
  pendingNewText.value = null
  pendingTextEnd.value = null
  editingText.value = ''
}

function commitTextOverlay() {
  if (!markupDoc.value || !pendingNewText.value) return
  const text = editingText.value.trim()
  if (!text) {
    cancelTextOverlay()
    return
  }
  const { x, y } = pendingNewText.value
  const x2 = pendingTextEnd.value?.x2 ?? Math.min(1, x + DEFAULT_TEXT_W)
  const y2 = pendingTextEnd.value?.y2 ?? Math.min(1, y + DEFAULT_TEXT_H)
  pushMarkupUndo()
  const shape: PdfMarkupShape = {
    ...defaultRemarkMeta(),
    id: newShapeId(),
    type: 'text',
    x1: Math.min(x, x2),
    y1: Math.min(y, y2),
    x2: Math.max(x, x2),
    y2: Math.max(y, y2),
    text,
    fontSize: markupFontRel.value,
    color: markupColor.value,
  }
  pageShapes(markupDoc.value, screenshotPage.value).push(shape)
  selectedShapeId.value = shape.id
  markMarkupChanged()
  cancelTextOverlay()
  markupTool.value = 'select'
}

function closeTextOverlay() {
  commitTextOverlay()
}

function onTextResizeDown(ev: MouseEvent, shape: Extract<PdfMarkupShape, { type: 'text' }>) {
  if (ev.button !== 0) return
  ev.preventDefault()
  ev.stopPropagation()
  selectedShapeId.value = shape.id
  pushMarkupUndo()
  isResizingText.value = true
  textResizeStart.value = {
    pointerX: ev.clientX,
    pointerY: ev.clientY,
    x2: shape.x2,
    y2: shape.y2,
  }
}

function onPendingTextResizeDown(ev: MouseEvent) {
  if (!pendingNewText.value || ev.button !== 0) return
  ev.preventDefault()
  ev.stopPropagation()
  isResizingText.value = true
  const x2 = pendingTextEnd.value?.x2 ?? Math.min(1, pendingNewText.value.x + DEFAULT_TEXT_W)
  const y2 = pendingTextEnd.value?.y2 ?? Math.min(1, pendingNewText.value.y + DEFAULT_TEXT_H)
  textResizeStart.value = { pointerX: ev.clientX, pointerY: ev.clientY, x2, y2 }
}

function onTextBoxMouseDown(ev: MouseEvent, shape: Extract<PdfMarkupShape, { type: 'text' }>) {
  if (pdfLeftTab.value !== 'remarks' || ev.button !== 0) return
  if ((ev.target as HTMLElement).closest('.pdf-markup-resize-handle')) return
  ev.preventDefault()
  ev.stopPropagation()
  cancelTextOverlay()
  selectedShapeId.value = shape.id
  editingText.value = shape.text
  if (markupTool.value === 'select') {
    pushMarkupUndo()
    isDraggingText.value = true
    textDragStart.value = {
      pointerX: ev.clientX,
      pointerY: ev.clientY,
      x1: shape.x1,
      y1: shape.y1,
      x2: shape.x2,
      y2: shape.y2,
    }
  } else {
    focusTextEditor(`.pdf-markup-text-box[data-shape-id="${shape.id}"] textarea`)
  }
}

function onTextBoxDblClick(ev: MouseEvent, shape: Extract<PdfMarkupShape, { type: 'text' }>) {
  ev.stopPropagation()
  pushMarkupUndo()
  selectedShapeId.value = shape.id
  editingText.value = shape.text
}

function onTextEditorInput(shape: Extract<PdfMarkupShape, { type: 'text' }>) {
  shape.text = editingText.value
  shape.fontSize = markupFontRel.value
  markMarkupChanged()
}

function onTextEditorBlur(shape: Extract<PdfMarkupShape, { type: 'text' }>) {
  if (skipNextTextBlur) return
  const text = editingText.value.trim()
  if (text) {
    shape.text = text
    shape.fontSize = markupFontRel.value
    markMarkupChanged()
  } else {
    editingText.value = shape.text
  }
  selectedShapeId.value = null
}

function onNewTextBlur() {
  if (editingText.value.trim()) commitTextOverlay()
  else cancelTextOverlay()
}

let skipNextTextBlur = false

function onTextEscape() {
  skipNextTextBlur = true
  handleMarkupEscape()
  nextTick(() => {
    skipNextTextBlur = false
  })
}

function clearMarkupSelection() {
  selectedShapeId.value = null
  markupEdit.value = null
  editingText.value = ''
}

function onMarkupMouseDown(ev: MouseEvent) {
  if (pdfLeftTab.value !== 'remarks' || ev.button !== 0) return
  if ((ev.target as HTMLElement).closest('.pdf-markup-text-box')) return
  ev.preventDefault()
  ev.stopPropagation()
  const pos = normPosFromEvent(ev)
  if (!pos || !markupDoc.value) return

  const hit = hitTestMarkupShape(pos.x, pos.y)

  if (pendingNewText.value) {
    if (editingText.value.trim()) commitTextOverlay()
    else cancelTextOverlay()
    if (hit) return
  }

  if (markupTool.value === 'select' || markupTool.value === 'text') {
    const tryIds = [selectedShapeId.value, hit].filter((id): id is string => !!id)
    for (const id of tryIds) {
      const sh = currentPageShapes.value.find((s) => s.id === id)
      if (!sh || sh.type === 'text') continue
      const hi = hitTestShapeHandleIndex(sh, pos.x, pos.y)
      if (hi !== null && markupTool.value === 'select') {
        selectedShapeId.value = id
        beginMarkupEdit(sh, hi, ev)
        return
      }
    }
    if (hit) {
      const sh = currentPageShapes.value.find((s) => s.id === hit)
      selectedShapeId.value = hit
      if (sh?.type === 'text') {
        editingText.value = sh.text
        if (markupTool.value === 'text') {
          focusTextEditor(`.pdf-markup-text-box[data-shape-id="${hit}"] textarea`)
        }
      } else if (markupTool.value === 'select' && sh) {
        beginMarkupEdit(sh, null, ev)
      }
      return
    }
    if (markupTool.value === 'select') {
      clearMarkupSelection()
      return
    }
  }

  if (markupTool.value === 'polyline') {
    if (ev.detail >= 2) {
      finishPolylineDraft()
      return
    }
    if (polylineDraft.value.length === 0) pushMarkupUndo()
    polylineDraft.value.push({ x: pos.x, y: pos.y })
    selectedShapeId.value = null
    return
  }

  if (markupTool.value === 'text') {
    pendingNewText.value = { x: pos.x, y: pos.y }
    pendingTextEnd.value = {
      x2: Math.min(1, pos.x + DEFAULT_TEXT_W),
      y2: Math.min(1, pos.y + DEFAULT_TEXT_H),
    }
    editingText.value = ''
    selectedShapeId.value = null
    focusTextEditor('.pdf-markup-text-editor--new textarea')
    return
  }

  if (!isDragDrawTool(markupTool.value)) return

  pushMarkupUndo()
  selectedShapeId.value = null
  isDrawingMarkup.value = true
  markupDrawStart.value = pos
  markupDraftShape.value = {
    ...defaultRemarkMeta(),
    id: newShapeId(),
    type: markupTool.value as 'arrow' | 'line' | 'rect' | 'ellipse',
    x1: pos.x,
    y1: pos.y,
    x2: pos.x,
    y2: pos.y,
    color: markupColor.value,
    strokeRel: markupStrokeRel.value,
    arrowRel: markupArrowRel.value,
  }
}

function onMarkupMouseMove(ev: MouseEvent) {
  if (polylineDraft.value.length > 0 && markupTool.value === 'polyline') {
    const pos = normPosFromEvent(ev, true)
    polylineHover.value = pos
  }
  if (!isDrawingMarkup.value || !markupDrawStart.value || !markupDraftShape.value) return
  const pos = normPosFromEvent(ev, true)
  if (!pos) return
  markupDraftShape.value = {
    ...markupDraftShape.value,
    x2: pos.x,
    y2: pos.y,
  }
}

function onMarkupMouseUp(ev: MouseEvent) {
  if (!isDrawingMarkup.value || !markupDraftShape.value || !markupDoc.value) {
    isDrawingMarkup.value = false
    return
  }
  const pos = normPosFromEvent(ev, true)
  const draft = markupDraftShape.value
  isDrawingMarkup.value = false
  markupDrawStart.value = null
  markupDraftShape.value = null
  const dx = Math.abs(draft.x2 - draft.x1)
  const dy = Math.abs(draft.y2 - draft.y1)
  if (dx < 0.005 && dy < 0.005) {
    return
  }
  pageShapes(markupDoc.value, screenshotPage.value).push({ ...draft, x2: pos?.x ?? draft.x2, y2: pos?.y ?? draft.y2 })
  /* undo снимок уже сделан в mousedown */
  selectedShapeId.value = draft.id
  markMarkupChanged()
  markupTool.value = 'select'
}

function deleteSelectedMarkupShape() {
  if (!markupDoc.value || !selectedShapeId.value) return
  pushMarkupUndo()
  const shapes = pageShapes(markupDoc.value, screenshotPage.value)
  const idx = shapes.findIndex((s) => s.id === selectedShapeId.value)
  if (idx >= 0) {
    shapes.splice(idx, 1)
    selectedShapeId.value = null
    markMarkupChanged()
  }
}

/** Esc: отмена черновика, сброс инструмента в ◇, снятие выделения */
function handleMarkupEscape() {
  if (isResizingText.value) {
    isResizingText.value = false
    textResizeStart.value = null
  }
  if (isDrawingMarkup.value || markupDraftShape.value) {
    isDrawingMarkup.value = false
    markupDrawStart.value = null
    markupDraftShape.value = null
  }
  if (pendingNewText.value) {
    cancelTextOverlay()
  }
  if (isDraggingText.value) {
    isDraggingText.value = false
    textDragStart.value = null
  }
  if (markupEdit.value) {
    markupEdit.value = null
  }
  if (polylineDraft.value.length > 0) {
    polylineDraft.value = []
    polylineHover.value = null
  }
  if (selectedShapeId.value && !pendingNewText.value) {
    const sh = currentPageShapes.value.find((s) => s.id === selectedShapeId.value)
    if (sh?.type === 'text') {
      editingText.value = sh.text
    }
  }
  markupTool.value = 'select'
  clearMarkupSelection()
}

function cancelMarkupAction(): boolean {
  const hadTool = markupTool.value !== 'select'
  const hadSelection = !!selectedShapeId.value
  const hadDraft =
    isDrawingMarkup.value ||
    !!markupDraftShape.value ||
    !!pendingNewText.value ||
    polylineDraft.value.length > 0 ||
    !!markupEdit.value ||
    isDraggingText.value ||
    isResizingText.value
  handleMarkupEscape()
  return hadTool || hadSelection || hadDraft
}

function onMarkupEscape(ev: KeyboardEvent) {
  if (ev.key !== 'Escape') return
  if (pdfLeftTab.value !== 'remarks') return
  const active = document.activeElement
  if (active?.tagName === 'TEXTAREA') {
    skipNextTextBlur = true
    nextTick(() => {
      skipNextTextBlur = false
    })
  }
  handleMarkupEscape()
  ev.preventDefault()
  ev.stopImmediatePropagation()
}

function onMarkupKeydown(ev: KeyboardEvent) {
  if (ev.key === 'Escape') {
    onMarkupEscape(ev)
    return
  }
  if (pdfLeftTab.value !== 'remarks') return
  if (ev.key === 'Enter' && markupTool.value === 'polyline' && polylineDraft.value.length >= 2) {
    ev.preventDefault()
    finishPolylineDraft()
    return
  }
  if (ev.key === 'Delete' || ev.key === 'Backspace') {
    const tag = (ev.target as HTMLElement)?.tagName
    if (tag === 'INPUT' || tag === 'TEXTAREA') return
    ev.preventDefault()
    deleteSelectedMarkupShape()
  }
}

function onMarkupMouseMoveGlobal(ev: MouseEvent) {
  if (isResizingText.value && textResizeStart.value) {
    const layer = pageLayerRef.value
    if (!layer) return
    const r = layer.getBoundingClientRect()
    const dx = (ev.clientX - textResizeStart.value.pointerX) / r.width
    const dy = (ev.clientY - textResizeStart.value.pointerY) / r.height
    const minSize = 0.02
    if (pendingNewText.value) {
      const x1 = pendingNewText.value.x
      const y1 = pendingNewText.value.y
      const nx2 = clamp(textResizeStart.value.x2 + dx, x1 + minSize, 1)
      const ny2 = clamp(textResizeStart.value.y2 + dy, y1 + minSize, 1)
      pendingTextEnd.value = { x2: nx2, y2: ny2 }
      textResizeStart.value = { ...textResizeStart.value, x2: nx2, y2: ny2 }
      return
    }
    const shape = currentPageShapes.value.find((s) => s.id === selectedShapeId.value)
    if (shape?.type === 'text') {
      const x1 = Math.min(shape.x1, shape.x2)
      const y1 = Math.min(shape.y1, shape.y2)
      shape.x2 = clamp(textResizeStart.value.x2 + dx, x1 + minSize, 1)
      shape.y2 = clamp(textResizeStart.value.y2 + dy, y1 + minSize, 1)
      markMarkupChanged()
    }
    return
  }
  if (markupEdit.value && markupDoc.value && selectedShapeId.value) {
    const layer = pageLayerRef.value
    if (!layer) return
    const r = layer.getBoundingClientRect()
    const dx = (ev.clientX - markupEdit.value.pointerX) / r.width
    const dy = (ev.clientY - markupEdit.value.pointerY) / r.height
    const shape = currentPageShapes.value.find((s) => s.id === selectedShapeId.value)
    const edit = markupEdit.value
    if (!shape || shape.type === 'text') return
    if (edit.handleIndex === null) {
      if (shape.type === 'polyline' && edit.points) {
        shape.points = edit.points.map((p) => ({
          x: clamp(p.x + dx, 0, 1),
          y: clamp(p.y + dy, 0, 1),
        }))
        syncPolylineBbox(shape)
      } else if (isTwoPointShape(shape)) {
        shape.x1 = clamp(edit.x1 + dx, 0, 1)
        shape.y1 = clamp(edit.y1 + dy, 0, 1)
        shape.x2 = clamp(edit.x2 + dx, 0, 1)
        shape.y2 = clamp(edit.y2 + dy, 0, 1)
      }
    } else {
      const pos = normPosFromEvent(ev, true)
      if (!pos) return
      if (shape.type === 'polyline') {
        shape.points[edit.handleIndex] = { x: pos.x, y: pos.y }
        syncPolylineBbox(shape)
      } else if (edit.handleIndex === 0) {
        shape.x1 = pos.x
        shape.y1 = pos.y
      } else {
        shape.x2 = pos.x
        shape.y2 = pos.y
      }
    }
    markMarkupChanged()
    return
  }
  if (!isDraggingText.value || !textDragStart.value || !markupDoc.value || !selectedShapeId.value) return
  const layer = pageLayerRef.value
  if (!layer) return
  const r = layer.getBoundingClientRect()
  const dx = (ev.clientX - textDragStart.value.pointerX) / r.width
  const dy = (ev.clientY - textDragStart.value.pointerY) / r.height
  const shape = currentPageShapes.value.find((s) => s.id === selectedShapeId.value)
  if (shape?.type !== 'text') return
  const w = Math.abs(textDragStart.value.x2 - textDragStart.value.x1)
  const h = Math.abs(textDragStart.value.y2 - textDragStart.value.y1)
  shape.x1 = clamp(textDragStart.value.x1 + dx, 0, 1 - w)
  shape.y1 = clamp(textDragStart.value.y1 + dy, 0, 1 - h)
  shape.x2 = shape.x1 + w
  shape.y2 = shape.y1 + h
  markMarkupChanged()
}

function onMarkupMouseUpGlobal() {
  if (isResizingText.value) {
    isResizingText.value = false
    textResizeStart.value = null
  }
  if (isDraggingText.value) {
    isDraggingText.value = false
    textDragStart.value = null
  }
  if (markupEdit.value) {
    markupEdit.value = null
  }
}

async function exportPdfWithRemarks(
  mode: PdfMarkupExportMode = 'layered',
): Promise<{ ok: boolean; fileName?: string; mode?: PdfMarkupExportMode }> {
  if (!props.pdfUrl || !markupDoc.value) return { ok: false }
  markupExporting.value = true
  try {
    const res = await fetch(props.pdfUrl)
    const buf = await res.arrayBuffer()
    const { bytes, fileName, mode: savedMode, sidecar, sidecarFileName } = await exportPdfWithMarkup(
      buf,
      cloneMarkupDocument(markupDoc.value),
      props.pdfName || 'document.pdf',
      markupStyle.value,
      { mode },
    )
    downloadBlob(bytes, fileName)
    if (savedMode === 'layered' && sidecar && sidecarFileName) {
      downloadBlob(encodeMarkupSidecar(sidecar), sidecarFileName)
      const docKey = markupDocumentKey(props.pdfUrl, props.pdfName)
      await saveMarkupDocument({ ...cloneMarkupDocument(markupDoc.value), documentKey: docKey })
    }
    await persistMarkupDraft(true)
    return { ok: true, fileName, mode: savedMode }
  } catch (e) {
    logger.error('PdfViewer', 'Экспорт PDF с замечаниями', e)
    window.alert(e instanceof Error ? e.message : 'Ошибка экспорта PDF')
    return { ok: false }
  } finally {
    markupExporting.value = false
  }
}

function confirmDiscardMarkup(): boolean {
  if (!markupDirty.value) return true
  return window.confirm('Есть несохранённые пометки на PDF. Продолжить без экспорта? Черновик останется в IndexedDB.')
}

async function confirmDiscardMarkupAsync(): Promise<boolean> {
  if (!markupDirty.value) return true
  const saveFirst = window.confirm(
    'Есть несохранённые пометки на PDF.\n\nOK — сохранить замечания проекта (PDF + JSON)\nОтмена — другое действие',
  )
  if (saveFirst) {
    const r = await exportPdfWithRemarks('layered')
    return !!r.ok
  }
  const discard = window.confirm('Продолжить без сохранения на диск? Черновик останется в браузере.')
  return discard
}

function selectRemarkShape(shapeId: string) {
  selectedShapeId.value = shapeId
  const sh = currentPageShapes.value.find((s) => s.id === shapeId)
  if (sh?.type === 'text') editingText.value = sh.text
}

function updateSelectedRemarkStatus(status: RemarkStatus) {
  const sh = selectedMarkupShape.value
  if (!sh) return
  sh.remarkStatus = status
  markMarkupChanged()
}

function updateSelectedRemarkNote(note: string) {
  const sh = selectedMarkupShape.value
  if (!sh) return
  sh.remarkNote = note
  markMarkupChanged()
}

const SELECTION_STROKE = '#3b82f6'
const SELECTION_HANDLE_FILL = '#b8cce8'
const SELECTION_HANDLE_STROKE = '#1e3a8a'

/** Пиксели → доля ширины/высоты страницы (оверлей растянут по листу) */
function pxToNormX(px: number): number {
  return px / Math.max(pageCssWidth.value, 1)
}

function pxToNormY(px: number): number {
  return px / Math.max(pageCssHeight.value, 1)
}

/** Масштаб страницы (оверлей внутри слоя с transform: scale(zoom)). */
function markupZoomScale(): number {
  return Math.max(zoom.value, 0.15)
}

/** Делитель толщины: при «тонких линиях» дополнительно ~1/zoom на экране. */
function markupStrokeZoomDivisor(): number {
  const z = markupZoomScale()
  return markupHairline.value ? z * z : z
}

function onMarkupHairlineChange() {
  localStorage.setItem('deskreview.pdfHairline', markupHairline.value ? '1' : '0')
}

/** ~1.25px на экране — контур выделения */
function svgSelectionStrokeWidth(): number {
  return pxToNormX(1.25) / markupStrokeZoomDivisor()
}

/** Штрихи фиксированной длины на экране */
function svgSelectionDashArray(): string {
  const z = markupStrokeZoomDivisor()
  const dash = pxToNormX(6) / z
  const gap = pxToNormX(4) / z
  return `${dash} ${gap}`
}

/** Круглые узлы на экране (ellipse в норм. координатах) */
function svgHandleRadii(): { rx: number; ry: number } {
  const z = markupStrokeZoomDivisor()
  const rPx = 4.5
  return { rx: pxToNormX(rPx) / z, ry: pxToNormY(rPx) / z }
}

function svgHandleStrokeWidth(): number {
  return pxToNormX(1.5) / markupStrokeZoomDivisor()
}

/** Толщина в viewBox 0…1: компенсация scale(zoom) на слое страницы */
function svgStrokeWidth(shape?: PdfMarkupShape): number {
  const rel =
    shape && shape.type !== 'text' && shape.strokeRel != null ? shape.strokeRel : markupStrokeRel.value
  const div = markupStrokeZoomDivisor()
  return Math.max(0.00012 / div, rel / div)
}

function svgArrowHeadRel(shape?: PdfMarkupShape): number {
  const rel =
    shape && shape.type !== 'text' && shape.arrowRel != null ? shape.arrowRel : markupArrowRel.value
  const div = markupStrokeZoomDivisor()
  return Math.max(0.004 / div, rel / div)
}

/** Точки наконечника стрелки в нормализованных координатах (viewBox 0…1) */
function arrowHeadPoints(x1: number, y1: number, x2: number, y2: number, headRel: number): string {
  const angle = Math.atan2(y2 - y1, x2 - x1)
  const head = headRel
  const p1x = x2 - head * Math.cos(angle - Math.PI / 6)
  const p1y = y2 - head * Math.sin(angle - Math.PI / 6)
  const p2x = x2 - head * Math.cos(angle + Math.PI / 6)
  const p2y = y2 - head * Math.sin(angle + Math.PI / 6)
  return `${x2},${y2} ${p1x},${p1y} ${p2x},${p2y}`
}

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

const MAX_CANVAS_DIM = 8192
/** Масштаб рендера страницы для скриншота/отчёта (выше = чётче, до 4×). */
function pdfScreenshotScale(): number {
  const dpr = typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1
  return Math.min(4, Math.max(2.5, dpr * 2))
}
const MIN_ZOOM = 0.1
const MAX_ZOOM = 64
const TILE_CSS_SIZE_MAX = 1024
const TILE_CSS_SIZE_MIN = 256
const TILE_OVERSCAN = 1
const MAX_DEVICE_PIXEL_RATIO = 3
const MAX_CACHE_TILES = 200
const MAX_CONCURRENT_RENDERS = 4

const loading = ref(false)
const error = ref<string | null>(null)
const totalPages = ref(0)
const screenshotPage = ref(1)
const zoom = ref(1)
const visibleTiles = ref<TileSpec[]>([])
const pageBaseWidth = ref(0)
const pageBaseHeight = ref(0)
/** Размер прокручиваемой области (базовый размер × zoom) */
const pageCssWidth = ref(0)
const pageCssHeight = ref(0)
const pageThumbnails = ref<Array<{ page: number; dataUrl: string }>>([])
const thumbsLoading = ref(false)

const pdfViewerRootRef = ref<HTMLDivElement | null>(null)
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
  return Math.round(scale * 32) / 32
}

/** Размер тайла в базовых px: при большом zoom — меньше тайл, выше чёткость в пределах лимита canvas */
function getTileCssSize(): number {
  const z = Math.max(zoom.value, 0.25)
  const dpr = effectiveDevicePixelRatio()
  const maxByCanvas = Math.floor(MAX_CANVAS_DIM / (z * dpr * 1.05))
  return clamp(maxByCanvas, TILE_CSS_SIZE_MIN, TILE_CSS_SIZE_MAX)
}

function tileRenderMetrics(cssLeft: number, cssTop: number, cssWidth: number, cssHeight: number) {
  const dpr = effectiveDevicePixelRatio()
  const z = zoom.value
  const targetW = cssWidth * z * dpr
  const targetH = cssHeight * z * dpr
  const shrink = Math.min(1, MAX_CANVAS_DIM / Math.max(targetW, targetH, 1))
  const renderScale = z * dpr * shrink
  return {
    pixelWidth: Math.max(1, Math.ceil(targetW * shrink)),
    pixelHeight: Math.max(1, Math.ceil(targetH * shrink)),
    pixelLeft: Math.floor(cssLeft * renderScale),
    pixelTop: Math.floor(cssTop * renderScale),
    renderScale,
  }
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
  if (domCanvas.width !== cached.canvas.width || domCanvas.height !== cached.canvas.height) {
    domCanvas.width = cached.canvas.width
    domCanvas.height = cached.canvas.height
  }
  const ctx = domCanvas.getContext('2d')
  if (!ctx) return
  ctx.clearRect(0, 0, domCanvas.width, domCanvas.height)
  ctx.imageSmoothingEnabled = true
  ctx.imageSmoothingQuality = 'high'
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
  const metrics = tileRenderMetrics(spec.cssLeft, spec.cssTop, spec.cssWidth, spec.cssHeight)
  const viewport = currentPageProxy.getViewport({ scale: metrics.renderScale })
  const offscreen = document.createElement('canvas')
  offscreen.width = metrics.pixelWidth
  offscreen.height = metrics.pixelHeight
  const context = offscreen.getContext('2d', { alpha: false })
  if (!context) return
  context.imageSmoothingEnabled = true
  context.imageSmoothingQuality = 'high'
  const renderTask = currentPageProxy.render({
    canvasContext: context,
    viewport,
    transform: [1, 0, 0, 1, -metrics.pixelLeft, -metrics.pixelTop],
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
  if (!viewport || !currentPageProxy || pageBaseWidth.value <= 0 || pageBaseHeight.value <= 0) {
    visibleTiles.value = []
    return
  }
  const dpr = effectiveDevicePixelRatio()
  const bucket = zoomBucket(zoom.value)
  const tileSize = getTileCssSize()
  const z = Math.max(zoom.value, 0.01)
  const scrollLeftBase = viewport.scrollLeft / z
  const scrollTopBase = viewport.scrollTop / z
  const viewWidthBase = viewport.clientWidth / z
  const viewHeightBase = viewport.clientHeight / z
  const startX = Math.max(0, Math.floor(scrollLeftBase / tileSize) - TILE_OVERSCAN)
  const startY = Math.max(0, Math.floor(scrollTopBase / tileSize) - TILE_OVERSCAN)
  const endX = Math.max(
    startX,
    Math.ceil((scrollLeftBase + viewWidthBase) / tileSize) + TILE_OVERSCAN
  )
  const endY = Math.max(
    startY,
    Math.ceil((scrollTopBase + viewHeightBase) / tileSize) + TILE_OVERSCAN
  )
  const nextTiles: TileSpec[] = []
  for (let ty = startY; ty <= endY; ty += 1) {
    const cssTop = ty * tileSize
    if (cssTop >= pageBaseHeight.value) continue
    const cssHeight = Math.min(tileSize, pageBaseHeight.value - cssTop)
    for (let tx = startX; tx <= endX; tx += 1) {
      const cssLeft = tx * tileSize
      if (cssLeft >= pageBaseWidth.value) continue
      const cssWidth = Math.min(tileSize, pageBaseWidth.value - cssLeft)
      const metrics = tileRenderMetrics(cssLeft, cssTop, cssWidth, cssHeight)
      const pixelLeft = metrics.pixelLeft
      const pixelTop = metrics.pixelTop
      const pixelWidth = metrics.pixelWidth
      const pixelHeight = metrics.pixelHeight
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
  pageBaseWidth.value = currentPageWidth
  pageBaseHeight.value = currentPageHeight
  screenshotPage.value = target
  updatePageCssSize()
  tileCache.clear()
  await nextTick()
  scheduleTilesUpdate()
}

function updatePageCssSize() {
  pageCssWidth.value = pageBaseWidth.value * zoom.value
  pageCssHeight.value = pageBaseHeight.value * zoom.value
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
  tileCache.clear()
  cancelAllRenders()
  renderQueue.length = 0
  scheduleTilesUpdate()
  nextTick(() => {
    viewport.scrollLeft = clamp(modelX * z - anchorX, 0, Math.max(0, viewport.scrollWidth - viewport.clientWidth))
    viewport.scrollTop = clamp(modelY * z - anchorY, 0, Math.max(0, viewport.scrollHeight - viewport.clientHeight))
    scheduleTilesUpdate()
  })
}

function onViewportWheel(ev: WheelEvent) {
  if (!currentPageProxy) return
  // Без Ctrl — обычная прокрутка чертежа; Ctrl/жест pinch — масштаб (как в браузере/Компасе)
  if (!ev.ctrlKey && !ev.metaKey) return
  ev.preventDefault()
  ev.stopImmediatePropagation()
  let dy = ev.deltaY
  if (ev.deltaMode === WheelEvent.DOM_DELTA_LINE) dy *= 18
  else if (ev.deltaMode === WheelEvent.DOM_DELTA_PAGE) {
    dy *= viewportRef.value?.clientHeight ?? 800
  }
  const factor = Math.exp(-dy * 0.0015)
  applyZoom(zoom.value * factor, ev.clientX, ev.clientY)
}

function setZoomPreset(value: number) {
  applyZoom(value)
}

function onPanMouseDown(ev: MouseEvent) {
  if (ev.button !== 1 && ev.button !== 2) return
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
    pageBaseWidth.value = 0
    pageBaseHeight.value = 0
    pageCssWidth.value = 0
    pageCssHeight.value = 0
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
    await initMarkupForCurrentDocument()
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
      try {
        await page.render({ canvasContext: ctx, viewport }).promise
      } catch (e) {
        const name = (e as { name?: string })?.name
        if (name === 'RenderingCancelledException') continue
        throw e
      }
      next.push({ page: p, dataUrl: canvas.toDataURL('image/png') })
      // progressive update so sidebar appears quickly
      pageThumbnails.value = [...next]
    }
  } catch (e) {
    if (localGen !== thumbsGeneration) return
    const name = (e as { name?: string })?.name
    if (name === 'RenderingCancelledException') return
    logger.warn('PdfViewer', 'Не удалось отрендерить миниатюры страниц', e)
  } finally {
    if (localGen === thumbsGeneration) thumbsLoading.value = false
  }
}

watch(
  () => props.pdfUrl,
  async (url, prev) => {
    if (url && url === prev && pdfDoc) return
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

watch(
  () => props.pdfName,
  async () => {
    if (pdfDoc) await initMarkupForCurrentDocument()
  },
)

watch(
  () => props.markupSidecarBytes,
  async (bytes, prev) => {
    if (!pdfDoc || !markupDoc.value || bytes === prev) return
    if (!bytes?.byteLength) return
    const sidecar = parseMarkupSidecarBytes(bytes)
    if (sidecar) mergeMarkupSidecar(sidecar, 'файл рядом с PDF')
  },
)

watch(markupTool, (tool, prev) => {
  if (prev === 'polyline' && tool !== 'polyline' && polylineDraft.value.length > 0) {
    polylineDraft.value = []
    polylineHover.value = null
  }
})

async function getCurrentPageImageUrlAsync(pageNum?: number): Promise<string> {
  const page = pageNum ?? screenshotPage.value
  logger.info('PdfViewer', `getCurrentPageImageUrlAsync: page=${page}, pdfDoc=${!!pdfDoc}, totalPages=${totalPages.value}`)
  if (!pdfDoc || page < 1 || page > totalPages.value) {
    logger.warn('PdfViewer', 'getCurrentPageImageUrlAsync: выход без рендера (нет документа или неверная страница)')
    return ''
  }
  try {
    const p = await pdfDoc.getPage(page)
    const viewport = p.getViewport({ scale: pdfScreenshotScale() })
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

let pdfEscapeHandler: ((ev: KeyboardEvent) => void) | null = null

onMounted(() => {
  window.addEventListener('mousemove', onPanMouseMove)
  window.addEventListener('mouseup', onPanMouseUp)
  window.addEventListener('mouseup', onMarkupMouseUp)
  window.addEventListener('mouseup', onMarkupMouseUpGlobal)
  window.addEventListener('mousemove', onMarkupMouseMove)
  window.addEventListener('mousemove', onMarkupMouseMoveGlobal)
  window.addEventListener('keydown', onMarkupKeydown, true)
  pdfEscapeHandler = (ev: KeyboardEvent) => onMarkupEscape(ev)
  window.addEventListener('keydown', pdfEscapeHandler, true)
  markupAutosaveTimer = setInterval(() => {
    if (markupDirty.value) void persistMarkupDraft(true)
  }, 30_000)
  nextTick(() => {
    const vp = viewportRef.value
    if (vp) {
      resizeObserver = new ResizeObserver(() => scheduleTilesUpdate())
      resizeObserver.observe(vp)
    }
  })
})

onUnmounted(() => {
  if (markupAutosaveTimer) clearInterval(markupAutosaveTimer)
  if (markupSaveDebounce) clearTimeout(markupSaveDebounce)
  thumbsGeneration += 1
  cancelAllRenders()
  if (loadingTask) loadingTask.destroy()
  if (updateTilesRaf) cancelAnimationFrame(updateTilesRaf)
  if (pdfEscapeHandler) {
    window.removeEventListener('keydown', pdfEscapeHandler, true)
    pdfEscapeHandler = null
  }
  resizeObserver?.disconnect()
  window.removeEventListener('mousemove', onPanMouseMove)
  window.removeEventListener('mouseup', onPanMouseUp)
  window.removeEventListener('mouseup', onMarkupMouseUp)
  window.removeEventListener('mouseup', onMarkupMouseUpGlobal)
  window.removeEventListener('mousemove', onMarkupMouseMove)
  window.removeEventListener('mousemove', onMarkupMouseMoveGlobal)
  window.removeEventListener('keydown', onMarkupKeydown, true)
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
  get isMarkupDirty() {
    return markupDirty.value
  },
  confirmDiscardMarkup,
  confirmDiscardMarkupAsync,
  persistMarkupDraft,
  exportPdfWithRemarks,
  cancelMarkupAction,
  undoMarkup,
})
</script>

<template>
  <div ref="pdfViewerRootRef" class="pdf-viewer">
    <div v-if="loading" class="pdf-loading">Загрузка PDF…</div>
    <div v-else-if="error" class="pdf-error">{{ error }}</div>
    <template v-else>
      <div class="pdf-toolbar">
        <button type="button" class="pdf-open-file-btn" title="Выбрать другой PDF" @click="emit('open-pdf')">
          Открыть PDF
        </button>
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
          <label
            class="pdf-hairline-toggle"
            title="При увеличении масштаба линии разметки остаются тонкими (≈1/zoom²)"
          >
            <input v-model="markupHairline" type="checkbox" @change="onMarkupHairlineChange" />
            Тонкие линии
          </label>
          <span class="pdf-zoom-hint" title="Прокрутка — сдвиг чертежа; Ctrl+колёсико — масштаб; СКМ или ПКМ — перетаскивание">Ctrl+колёсико</span>
        </div>
        <button
          type="button"
          class="pdf-markup-toggle-btn"
          :class="{ off: !markupVisible }"
          :title="markupVisible ? 'Скрыть пометки на экране (данные уже загружены)' : 'Показать загруженные пометки'"
          @click="toggleMarkupVisible"
        >
          {{ markupVisible ? 'Пометки вкл' : 'Пометки выкл' }}
        </button>
        <button
          type="button"
          class="pdf-markup-export-btn"
          :disabled="!pdfUrl || markupExporting"
          title="Чертёж (PDF) и слой замечаний (JSON) для работы в DeskReview: правка, скрытие пометок, повторное открытие пары файлов."
          @click="exportPdfWithRemarks('layered')"
        >
          {{ markupExporting ? 'Сохранение…' : 'Сохранить замечания проекта' }}
        </button>
        <button
          type="button"
          class="pdf-markup-export-btn pdf-markup-export-btn--flat"
          :disabled="!pdfUrl || markupExporting"
          title="Один PDF: пометки нарисованы в листе. Для Acrobat, почты и печати; слой в DeskReview потом не редактируется."
          @click="exportPdfWithRemarks('flattened')"
        >
          {{ markupExporting ? 'Сохранение…' : 'Сохранить с замечаниями' }}
        </button>
        <span v-if="markupDirty" class="pdf-markup-dirty-pill" title="Есть несохранённые изменения (черновик в браузере)">●</span>
      </div>
      <div class="pdf-content">
        <aside class="pdf-left-sidebar">
          <div class="pdf-left-tabs" role="tablist" aria-label="Панель PDF">
            <button type="button" class="pdf-left-tab" role="tab" :class="{ active: pdfLeftTab === 'document' }" @click="pdfLeftTab = 'document'">Документ</button>
            <button type="button" class="pdf-left-tab" role="tab" :class="{ active: pdfLeftTab === 'remarks' }" @click="pdfLeftTab = 'remarks'">Замечания</button>
          </div>
          <div v-show="pdfLeftTab === 'document'" class="pdf-left-pane pdf-thumbs">
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
          </div>
          <div v-show="pdfLeftTab === 'remarks'" class="pdf-left-pane pdf-remarks-panel">
            <p class="pdf-remarks-hint">
              Линия / полилиния (Enter — закончить). В режиме ◇ — тянуть узлы и тело фигуры.
              <strong>Сохранить замечания проекта</strong> (Ctrl+S) — PDF + слой для правки.
              <strong>Сохранить с замечаниями</strong> — один PDF для просмотра вне DeskReview.
              «Пометки выкл» — только скрыть на экране.
            </p>
            <div class="pdf-markup-tools">
              <button type="button" class="pdf-markup-tool" :class="{ active: markupTool === 'arrow' }" title="Стрелка" @click="markupTool = 'arrow'">↗</button>
              <button type="button" class="pdf-markup-tool" :class="{ active: markupTool === 'line' }" title="Прямая линия" @click="markupTool = 'line'">／</button>
              <button type="button" class="pdf-markup-tool" :class="{ active: markupTool === 'polyline' }" title="Полилиния: клики — узлы, Enter — завершить" @click="markupTool = 'polyline'">⌇</button>
              <button type="button" class="pdf-markup-tool" :class="{ active: markupTool === 'rect' }" title="Рамка" @click="markupTool = 'rect'">▭</button>
              <button type="button" class="pdf-markup-tool" :class="{ active: markupTool === 'ellipse' }" @click="markupTool = 'ellipse'">○</button>
              <button type="button" class="pdf-markup-tool" :class="{ active: markupTool === 'text' }" @click="markupTool = 'text'">T</button>
              <button type="button" class="pdf-markup-tool" :class="{ active: markupTool === 'select' }" title="Выбор и перемещение" @click="markupTool = 'select'">◇</button>
              <input v-model="markupColor" type="color" class="pdf-markup-color" title="Цвет" />
            </div>
            <div class="pdf-markup-dim-row">
              <label title="Толщина линий">Линия ‰</label>
              <input v-model.number="markupStrokeRel" type="number" min="0.0005" max="0.02" step="0.0005" />
              <label title="Стрелка">Стрелка ‰</label>
              <input v-model.number="markupArrowRel" type="number" min="0.004" max="0.04" step="0.001" />
            </div>
            <div class="pdf-markup-dim-row">
              <label title="Шрифт">Шрифт ‰</label>
              <input v-model.number="markupFontRel" type="number" min="0.01" max="0.06" step="0.001" />
            </div>
            <p class="pdf-remarks-hint pdf-remarks-hint--mini">◇: узлы — размер/направление. Esc — сброс инструмента и снятие выделения. Полилиния — Enter.</p>
            <div class="pdf-remarks-pages">
              <div class="pdf-remarks-pages-title">Страницы с пометками</div>
              <button
                v-for="p in remarksPagesList"
                :key="`rm-p-${p}`"
                type="button"
                class="pdf-remarks-page-btn"
                :class="{ active: screenshotPage === p }"
                @click="screenshotPage = p"
              >
                стр. {{ p }}
                <span v-if="markupDoc && (markupDoc.pages[String(p)]?.length ?? 0) > 0" class="pdf-remarks-page-count">
                  ({{ markupDoc.pages[String(p)]?.length }})
                </span>
              </button>
            </div>
            <div class="pdf-remarks-filter-row">
              <label class="pdf-remarks-filter-label">Статус</label>
              <select v-model="remarkStatusFilter" class="pdf-remarks-filter-select">
                <option value="all">Все</option>
                <option v-for="opt in REMARK_STATUS_OPTIONS" :key="opt.value" :value="opt.value">
                  {{ opt.label }}
                </option>
              </select>
            </div>
            <div class="pdf-remarks-tree-title">Пометки на стр. {{ screenshotPage }}</div>
            <div v-if="currentPageShapes.length === 0" class="pdf-remarks-empty">Нет пометок на этой странице.</div>
            <div v-else-if="filteredPageShapes.length === 0" class="pdf-remarks-empty">Нет пометок с выбранным статусом.</div>
            <button
              v-for="(shape, idx) in filteredPageShapes"
              :key="shape.id"
              type="button"
              class="pdf-remarks-shape-row"
              :class="{ active: selectedShapeId === shape.id }"
              @click="selectRemarkShape(shape.id)"
            >
              <span class="pdf-remark-status-pill" :class="remarkStatusCssClass(shapeRemarkStatus(shape))">
                {{ remarkStatusLabel(shapeRemarkStatus(shape)) }}
              </span>
              <span class="pdf-remarks-shape-label">{{ shapeLabel(shape, idx) }}</span>
            </button>
            <div v-if="selectedMarkupShape" class="pdf-remark-detail">
              <label class="pdf-remark-detail-label">Статус</label>
              <select
                class="pdf-remarks-filter-select"
                :value="shapeRemarkStatus(selectedMarkupShape)"
                @change="updateSelectedRemarkStatus(($event.target as HTMLSelectElement).value as RemarkStatus)"
              >
                <option v-for="opt in REMARK_STATUS_OPTIONS" :key="opt.value" :value="opt.value">
                  {{ opt.label }}
                </option>
              </select>
              <label class="pdf-remark-detail-label">Описание</label>
              <textarea
                class="pdf-remark-detail-note"
                :value="selectedMarkupShape.remarkNote ?? ''"
                rows="3"
                placeholder="Текст замечания для согласования…"
                @input="updateSelectedRemarkNote(($event.target as HTMLTextAreaElement).value)"
              />
            </div>
            <button
              v-if="selectedShapeId"
              type="button"
              class="pdf-remarks-delete-btn"
              @click="deleteSelectedMarkupShape"
            >
              Удалить выбранное (Del)
            </button>
          </div>
        </aside>
        <div
          ref="viewportRef"
          class="pdf-viewport"
          @scroll="onViewportScroll"
          @wheel.capture="onViewportWheel"
          @mousedown="onPanMouseDown"
          @contextmenu.prevent
        >
          <div
            class="pdf-page-wrap"
            :style="{ width: `${pageCssWidth}px`, height: `${pageCssHeight}px` }"
          >
          <div
            ref="pageLayerRef"
            class="pdf-page-layer"
            :style="{
              width: `${pageBaseWidth}px`,
              height: `${pageBaseHeight}px`,
              transform: `scale(${zoom})`,
            }"
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
            <svg
              v-if="markupDoc && markupVisible && (pdfLeftTab === 'remarks' || vectorPageShapes.length > 0 || markupDraftShape)"
              class="pdf-markup-overlay"
              viewBox="0 0 1 1"
              preserveAspectRatio="none"
              :style="{
                pointerEvents: pdfLeftTab === 'remarks' ? 'auto' : 'none',
              }"
              @mousedown="onMarkupMouseDown"
            >
              <template v-for="shape in vectorPageShapes" :key="shape.id">
                <g v-if="shape.type === 'arrow'">
                  <line
                    :x1="shape.x1"
                    :y1="shape.y1"
                    :x2="shape.x2"
                    :y2="shape.y2"
                    :stroke="shape.color ?? '#cc0000'"
                    :stroke-width="svgStrokeWidth(shape)"
                  />
                  <polygon
                    :points="arrowHeadPoints(shape.x1, shape.y1, shape.x2, shape.y2, svgArrowHeadRel(shape))"
                    :fill="shape.color ?? '#cc0000'"
                  />
                </g>
                <line
                  v-else-if="shape.type === 'line'"
                  :x1="shape.x1"
                  :y1="shape.y1"
                  :x2="shape.x2"
                  :y2="shape.y2"
                  :stroke="shape.color ?? '#cc0000'"
                  :stroke-width="svgStrokeWidth(shape)"
                />
                <polyline
                  v-else-if="shape.type === 'polyline'"
                  :points="polylineSvgPoints(shape.points)"
                  fill="none"
                  :stroke="shape.color ?? '#cc0000'"
                  :stroke-width="svgStrokeWidth(shape)"
                />
                <rect
                  v-else-if="shape.type === 'rect'"
                  :x="Math.min(shape.x1, shape.x2)"
                  :y="Math.min(shape.y1, shape.y2)"
                  :width="Math.abs(shape.x2 - shape.x1)"
                  :height="Math.abs(shape.y2 - shape.y1)"
                  fill="none"
                  :stroke="shape.color ?? '#cc0000'"
                  :stroke-width="svgStrokeWidth(shape)"
                />
                <ellipse
                  v-else-if="shape.type === 'ellipse'"
                  :cx="(shape.x1 + shape.x2) / 2"
                  :cy="(shape.y1 + shape.y2) / 2"
                  :rx="Math.abs(shape.x2 - shape.x1) / 2"
                  :ry="Math.abs(shape.y2 - shape.y1) / 2"
                  fill="none"
                  :stroke="shape.color ?? '#cc0000'"
                  :stroke-width="svgStrokeWidth(shape)"
                />
              </template>
              <rect
                v-if="pdfLeftTab === 'remarks' && markupVisible && selectedShapeSelectionRect"
                class="pdf-markup-selection-box"
                :x="selectedShapeSelectionRect.x"
                :y="selectedShapeSelectionRect.y"
                :width="selectedShapeSelectionRect.width"
                :height="selectedShapeSelectionRect.height"
                fill="none"
                :stroke="SELECTION_STROKE"
                :stroke-width="svgSelectionStrokeWidth()"
                :stroke-dasharray="svgSelectionDashArray()"
                stroke-linecap="round"
                vector-effect="non-scaling-stroke"
                pointer-events="none"
              />
              <g
                v-if="pdfLeftTab === 'remarks' && markupVisible && selectedShapeHandles.length > 0"
                class="pdf-markup-handles"
              >
                <ellipse
                  v-for="(h, hi) in selectedShapeHandles"
                  :key="`handle-${selectedShapeId}-${hi}`"
                  :cx="h.x"
                  :cy="h.y"
                  :rx="svgHandleRadii().rx"
                  :ry="svgHandleRadii().ry"
                  :fill="SELECTION_HANDLE_FILL"
                  :stroke="SELECTION_HANDLE_STROKE"
                  :stroke-width="svgHandleStrokeWidth()"
                  vector-effect="non-scaling-stroke"
                />
              </g>
              <polyline
                v-if="polylinePreviewPoints"
                :points="polylinePreviewPoints"
                fill="none"
                stroke="#cc0000"
                :stroke-width="svgStrokeWidth()"
                :stroke-dasharray="svgSelectionDashArray()"
                stroke-linecap="round"
              />
              <template v-if="markupDraftShape && markupDraftShape.type !== 'text'">
                <g v-if="markupDraftShape.type === 'arrow'">
                  <line
                    :x1="markupDraftShape.x1"
                    :y1="markupDraftShape.y1"
                    :x2="markupDraftShape.x2"
                    :y2="markupDraftShape.y2"
                    :stroke="markupDraftShape.color ?? '#cc0000'"
                    :stroke-width="svgStrokeWidth(markupDraftShape)"
                  />
                  <polygon
                    :points="arrowHeadPoints(
                      markupDraftShape.x1,
                      markupDraftShape.y1,
                      markupDraftShape.x2,
                      markupDraftShape.y2,
                      svgArrowHeadRel(markupDraftShape),
                    )"
                    :fill="markupDraftShape.color ?? '#cc0000'"
                  />
                </g>
                <line
                  v-else-if="markupDraftShape.type === 'line'"
                  :x1="markupDraftShape.x1"
                  :y1="markupDraftShape.y1"
                  :x2="markupDraftShape.x2"
                  :y2="markupDraftShape.y2"
                  :stroke="markupDraftShape.color ?? '#cc0000'"
                  :stroke-width="svgStrokeWidth(markupDraftShape)"
                />
                <rect
                  v-else-if="markupDraftShape.type === 'rect'"
                  :x="Math.min(markupDraftShape.x1, markupDraftShape.x2)"
                  :y="Math.min(markupDraftShape.y1, markupDraftShape.y2)"
                  :width="Math.abs(markupDraftShape.x2 - markupDraftShape.x1)"
                  :height="Math.abs(markupDraftShape.y2 - markupDraftShape.y1)"
                  fill="none"
                  :stroke="markupDraftShape.color ?? '#cc0000'"
                  :stroke-width="svgStrokeWidth(markupDraftShape)"
                />
                <ellipse
                  v-else-if="markupDraftShape.type === 'ellipse'"
                  :cx="(markupDraftShape.x1 + markupDraftShape.x2) / 2"
                  :cy="(markupDraftShape.y1 + markupDraftShape.y2) / 2"
                  :rx="Math.abs(markupDraftShape.x2 - markupDraftShape.x1) / 2"
                  :ry="Math.abs(markupDraftShape.y2 - markupDraftShape.y1) / 2"
                  fill="none"
                  :stroke="markupDraftShape.color ?? '#cc0000'"
                  :stroke-width="svgStrokeWidth(markupDraftShape)"
                />
              </template>
            </svg>
            <div
              v-for="shape in textPageShapes"
              v-show="markupVisible"
              :key="`txt-${shape.id}`"
              class="pdf-markup-text-box"
              :data-shape-id="shape.id"
              :class="{ 'is-selected': selectedShapeId === shape.id && pdfLeftTab === 'remarks' }"
              :style="textBoxStyle(shape)"
              @mousedown="onTextBoxMouseDown($event, shape)"
              @dblclick="onTextBoxDblClick($event, shape)"
            >
              <div v-if="selectedShapeId !== shape.id || pdfLeftTab !== 'remarks'" class="pdf-markup-text-view">{{ shape.text }}</div>
              <textarea
                v-else
                v-model="editingText"
                class="pdf-markup-text-editor"
                @input="onTextEditorInput(shape)"
                @blur="onTextEditorBlur(shape)"
                @keydown.escape.stop.prevent="onTextEscape"
              />
              <div
                v-if="pdfLeftTab === 'remarks' && selectedShapeId === shape.id"
                class="pdf-markup-resize-handle"
                title="Изменить размер блока"
                @mousedown="onTextResizeDown($event, shape)"
              />
            </div>
            <div
              v-if="pendingNewText && pdfLeftTab === 'remarks' && markupVisible"
              class="pdf-markup-text-box pdf-markup-text-editor--new"
              :style="pendingTextBoxStyle()"
              @mousedown.stop
            >
              <textarea
                v-model="editingText"
                class="pdf-markup-text-editor"
                placeholder="Текст замечания…"
                @keydown.enter.exact.prevent="commitTextOverlay"
                @keydown.escape.stop.prevent="onTextEscape"
                @blur="onNewTextBlur"
              />
              <div
                class="pdf-markup-resize-handle"
                title="Размер блока"
                @mousedown="onPendingTextResizeDown"
              />
            </div>
          </div>
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
  flex-wrap: wrap;
  gap: 0.75rem;
  padding: 0.5rem 0.75rem;
  background: #252525;
  border-bottom: 1px solid #333;
}
.pdf-open-file-btn {
  padding: 0.3rem 0.65rem;
  font-size: 0.82rem;
  border-radius: 4px;
  border: 1px solid #3d5a8a;
  background: #2a3d5a;
  color: #c8d8f0;
  cursor: pointer;
  white-space: nowrap;
}
.pdf-open-file-btn:hover {
  background: #355070;
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
.pdf-hairline-toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  margin-left: 0.25rem;
  font-size: 0.72rem;
  color: #aab9d8;
  cursor: pointer;
  user-select: none;
  white-space: nowrap;
}
.pdf-hairline-toggle input {
  margin: 0;
  cursor: pointer;
}
.pdf-zoom-hint {
  margin-left: 0.35rem;
  font-size: 0.68rem;
  color: #7a8aa8;
  white-space: nowrap;
}
.pdf-viewport {
  position: relative;
  flex: 1;
  min-height: 0;
  overflow: auto;
  background: #2a2a2a;
  cursor: grab;
}
.pdf-viewport:active {
  cursor: grabbing;
}
.pdf-content {
  display: flex;
  flex: 1;
  min-height: 0;
}
.pdf-left-sidebar {
  flex-shrink: 0;
  width: clamp(116px, 12vw, 170px);
  min-width: 108px;
  border-right: 1px solid #333;
  background: #232a31;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.pdf-left-tabs {
  display: flex;
  flex-shrink: 0;
  border-bottom: 1px solid #333;
}
.pdf-left-tab {
  flex: 1;
  padding: 0.35rem 0.25rem;
  font-size: 0.68rem;
  border: none;
  background: #2a323c;
  color: #9eb0c8;
  cursor: pointer;
}
.pdf-left-tab.active {
  background: #395f96;
  color: #f0f5ff;
}
.pdf-left-pane {
  flex: 1;
  min-height: 0;
  overflow: auto;
}
.pdf-thumbs {
  padding: 0.45rem;
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}
.pdf-remarks-stub {
  padding: 0.5rem;
  font-size: 0.72rem;
  color: #9eb0c8;
}
.pdf-remarks-hint {
  margin: 0 0 0.5rem;
  line-height: 1.35;
}
.pdf-remarks-empty {
  color: #6f8098;
  font-style: italic;
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
.pdf-page-wrap {
  position: relative;
  margin: 0 auto;
  flex-shrink: 0;
}
.pdf-page-layer {
  position: relative;
  transform-origin: 0 0;
  background: #fff;
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.3);
}
.pdf-markup-overlay {
  position: absolute;
  left: 0;
  top: 0;
  width: 100%;
  height: 100%;
  z-index: 20;
  cursor: crosshair;
  pointer-events: auto;
}
.pdf-markup-text-box {
  position: absolute;
  z-index: 25;
  box-sizing: border-box;
  border: none;
  background: transparent;
  cursor: move;
  overflow: visible;
  min-width: 24px;
  min-height: 16px;
}
.pdf-markup-text-box.is-selected {
  outline: 1.5px dashed #3b82f6;
  outline-offset: 2px;
  border-radius: 2px;
}
.pdf-markup-text-view {
  padding: 2px 4px;
  font-size: inherit;
  font-weight: 600;
  color: #cc0000;
  white-space: pre-wrap;
  word-break: break-word;
  pointer-events: none;
  line-height: 1.25;
  text-shadow:
    0 0 2px #fff,
    0 0 4px #fff,
    1px 1px 0 #fff;
}
.pdf-markup-text-editor {
  width: 100%;
  height: 100%;
  box-sizing: border-box;
  border: none;
  resize: none;
  background: transparent;
  color: #cc0000;
  font: 600 13px sans-serif;
  padding: 2px 4px;
  line-height: 1.25;
  outline: none;
  text-shadow:
    0 0 2px #fff,
    0 0 4px #fff;
}
.pdf-markup-resize-handle {
  position: absolute;
  right: -5px;
  bottom: -5px;
  width: 9px;
  height: 9px;
  background: #b8cce8;
  border: 1.5px solid #1e3a8a;
  border-radius: 50%;
  box-shadow: 0 0 0 1px rgba(30, 58, 138, 0.45), 0 1px 2px rgba(15, 23, 42, 0.35);
  cursor: nwse-resize;
  z-index: 2;
}
.pdf-markup-handles ellipse {
  filter: drop-shadow(0 0 2px rgba(30, 58, 138, 0.55));
}
.pdf-markup-selection-box {
  opacity: 0.95;
}
.pdf-markup-dim-row {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.2rem 0.35rem;
  align-items: center;
  font-size: 0.68rem;
  color: #9eb0c8;
}
.pdf-markup-dim-row input {
  width: 100%;
  padding: 0.2rem 0.3rem;
  font-size: 0.72rem;
  border: 1px solid #3f4f66;
  border-radius: 3px;
  background: #1a2228;
  color: #e0e8f0;
}
.pdf-remarks-hint--mini {
  margin-top: 0.15rem;
  font-size: 0.62rem;
  opacity: 0.85;
}
.pdf-markup-toggle-btn {
  padding: 0.3rem 0.5rem;
  font-size: 0.72rem;
  border-radius: 4px;
  border: 1px solid #4a6a4a;
  background: #2a3d2a;
  color: #b8e0b8;
  cursor: pointer;
}
.pdf-markup-toggle-btn.off {
  border-color: #555;
  background: #333;
  color: #aaa;
}
.pdf-markup-toggle-btn:hover {
  filter: brightness(1.08);
}
.pdf-markup-export-btn {
  padding: 0.3rem 0.5rem;
  font-size: 0.72rem;
  white-space: nowrap;
  border-radius: 4px;
  border: 1px solid #6d8a4a;
  background: #3a5238;
  color: #d8f0d0;
  cursor: pointer;
}
.pdf-markup-export-btn--flat {
  border-color: #6a5040;
  background: #3d3028;
  color: #e8d0c0;
}
.pdf-markup-export-btn:hover:not(:disabled) {
  background: #4a6a48;
}
.pdf-markup-export-btn--flat:hover:not(:disabled) {
  background: #4d3a30;
}
.pdf-markup-export-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.pdf-markup-dirty-pill {
  color: #ffb35b;
  font-size: 1.1rem;
  line-height: 1;
}
.pdf-remarks-panel {
  padding: 0.45rem;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}
.pdf-markup-tools {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  align-items: center;
}
.pdf-markup-tool {
  width: 28px;
  height: 28px;
  padding: 0;
  border: 1px solid #3f4f66;
  border-radius: 4px;
  background: #2d3642;
  color: #dce8f8;
  cursor: pointer;
  font-size: 0.85rem;
}
.pdf-markup-tool.active {
  background: #395f96;
  border-color: #6d8fd0;
}
.pdf-markup-color {
  width: 28px;
  height: 28px;
  padding: 0;
  border: none;
  background: transparent;
  cursor: pointer;
}
.pdf-remarks-pages-title,
.pdf-remarks-tree-title {
  font-size: 0.68rem;
  color: #8ea2c2;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.pdf-remarks-page-btn {
  display: block;
  width: 100%;
  text-align: left;
  padding: 0.25rem 0.35rem;
  margin-bottom: 0.15rem;
  font-size: 0.72rem;
  border: 1px solid #3f4f66;
  border-radius: 4px;
  background: #2a323c;
  color: #c7d6ee;
  cursor: pointer;
}
.pdf-remarks-page-btn.active {
  background: #395f96;
  border-color: #6d8fd0;
}
.pdf-remarks-page-count {
  color: #9eb0c8;
}
.pdf-remarks-filter-row {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  margin-bottom: 0.2rem;
}
.pdf-remarks-filter-label,
.pdf-remark-detail-label {
  font-size: 0.68rem;
  color: #8ea2c2;
}
.pdf-remarks-filter-select {
  flex: 1;
  font-size: 0.72rem;
  padding: 0.2rem 0.3rem;
  border: 1px solid #3f4f66;
  border-radius: 4px;
  background: #2a323c;
  color: #c7d6ee;
}
.pdf-remark-detail {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  margin-top: 0.35rem;
  padding-top: 0.35rem;
  border-top: 1px solid #3f4f66;
}
.pdf-remark-detail-note {
  width: 100%;
  box-sizing: border-box;
  font-size: 0.72rem;
  padding: 0.3rem;
  border: 1px solid #3f4f66;
  border-radius: 4px;
  background: #252d38;
  color: #dce8f8;
  resize: vertical;
  min-height: 3.5rem;
}
.pdf-remarks-shape-row {
  display: flex;
  align-items: flex-start;
  gap: 0.3rem;
  width: 100%;
  text-align: left;
  padding: 0.28rem 0.35rem;
  font-size: 0.72rem;
  border: none;
  border-radius: 3px;
  background: transparent;
  color: #c7d6ee;
  cursor: pointer;
}
.pdf-remarks-shape-label {
  flex: 1;
  min-width: 0;
}
.remark-status-pill,
.pdf-remark-status-pill {
  flex-shrink: 0;
  font-size: 0.58rem;
  padding: 0.1rem 0.28rem;
  border-radius: 3px;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.remark-status--open {
  background: rgba(59, 130, 246, 0.25);
  color: #93c5fd;
}
.remark-status--answered {
  background: rgba(234, 179, 8, 0.22);
  color: #fde68a;
}
.remark-status--accepted {
  background: rgba(34, 197, 94, 0.22);
  color: #86efac;
}
.remark-status--rejected {
  background: rgba(239, 68, 68, 0.22);
  color: #fca5a5;
}
.pdf-remarks-shape-row:hover,
.pdf-remarks-shape-row.active {
  background: rgba(74, 111, 199, 0.35);
}
.pdf-remarks-delete-btn {
  margin-top: 0.25rem;
  padding: 0.3rem;
  font-size: 0.7rem;
  border: 1px solid #8a4040;
  border-radius: 4px;
  background: #3d2828;
  color: #f0c8c8;
  cursor: pointer;
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
