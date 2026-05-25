<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import {
  type ScreenLayerShape,
  type ScreenLayerTool,
  type ScreenLayerPoint,
  type Model3dScreenImage,
  DEFAULT_SCREEN_LAYER_STYLE,
  newScreenLayerShapeId,
  svgNormStrokeWidth,
  svgNormArrowHeadRel,
  arrowHeadPointsNorm,
  polylineSvgPoints,
  isDragDrawScreenTool,
  isTwoPointScreenShape,
  hitTestScreenShapes,
  hitTestScreenShapeHandleIndex,
  hitTestScreenImage,
  getScreenShapeHandles,
  syncScreenPolylineBbox,
  clamp01,
} from '../lib/model3dScreenLayer'

const props = defineProps<{
  shapes: ScreenLayerShape[]
  images: Model3dScreenImage[]
  tool: ScreenLayerTool
  color: string
  visible: boolean
  editable: boolean
  selectedShapeId: string | null
  selectedImageId: string | null
}>()

const emit = defineEmits<{
  'update:shapes': [shapes: ScreenLayerShape[]]
  'update:images': [images: Model3dScreenImage[]]
  'update:selectedShapeId': [id: string | null]
  'update:selectedImageId': [id: string | null]
  'update:tool': [tool: ScreenLayerTool]
  change: []
}>()

const overlayRef = ref<HTMLDivElement | null>(null)
const draftShape = ref<ScreenLayerShape | null>(null)
const isDrawing = ref(false)
const polylineDraft = ref<ScreenLayerPoint[]>([])
const polylineHover = ref<ScreenLayerPoint | null>(null)
const editingText = ref('')
const pendingNewText = ref<{ x: number; y: number } | null>(null)
const pendingTextEnd = ref<{ x2: number; y2: number } | null>(null)
const shapeEdit = ref<{
  pointerX: number
  pointerY: number
  handleIndex: number | null
  x1: number
  y1: number
  x2: number
  y2: number
  points?: ScreenLayerPoint[]
} | null>(null)
const isDraggingText = ref(false)
const textDragStart = ref<{
  pointerX: number
  pointerY: number
  x1: number
  y1: number
  x2: number
  y2: number
} | null>(null)
const isResizingText = ref(false)
const textResizeStart = ref<{ pointerX: number; pointerY: number; x2: number; y2: number } | null>(null)
const imageDragStart = ref<{
  imageId: string
  pointerX: number
  pointerY: number
  x: number
  y: number
  w: number
  h: number
} | null>(null)
const imageResizeStart = ref<{
  imageId: string
  pointerX: number
  pointerY: number
  x: number
  y: number
  w: number
  h: number
} | null>(null)

const DEFAULT_TEXT_W = 0.22
const DEFAULT_TEXT_H = 0.08
const SELECTION_STROKE = '#3b82f6'
const SELECTION_HANDLE_FILL = '#b8cce8'
const SELECTION_HANDLE_STROKE = '#1e3a8a'

const needsDrawCapture = computed(
  () =>
    props.editable &&
    (isDragDrawScreenTool(props.tool) || props.tool === 'polyline' || props.tool === 'text'),
)

const vectorShapes = computed(() => props.shapes.filter((s) => s.type !== 'text'))
const textShapes = computed(() => props.shapes.filter((s): s is Extract<ScreenLayerShape, { type: 'text' }> => s.type === 'text'))

const selectedShape = computed(() => props.shapes.find((s) => s.id === props.selectedShapeId) ?? null)

const selectedShapeHandles = computed(() => {
  const sh = selectedShape.value
  if (!sh || sh.type === 'text') return [] as ScreenLayerPoint[]
  return getScreenShapeHandles(sh)
})

const selectedShapeSelectionRect = computed(() => {
  const sh = selectedShape.value
  if (!sh || sh.type === 'text') return null
  const pad = 0.008
  let x1 = sh.x1
  let y1 = sh.y1
  let x2 = sh.x2
  let y2 = sh.y2
  let left = Math.min(x1, x2) - pad
  let top = Math.min(y1, y2) - pad
  let width = Math.abs(x2 - x1) + pad * 2
  let height = Math.abs(y2 - y1) + pad * 2
  const minW = 0.02
  const minH = 0.02
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

function normFromEvent(ev: MouseEvent, allowOutside = false): ScreenLayerPoint | null {
  const el = overlayRef.value
  if (!el) return null
  const r = el.getBoundingClientRect()
  if (r.width < 2 || r.height < 2) return null
  const x = (ev.clientX - r.left) / r.width
  const y = (ev.clientY - r.top) / r.height
  if (!allowOutside && (x < 0 || x > 1 || y < 0 || y > 1)) return null
  return { x: clamp01(x), y: clamp01(y) }
}

function emitShapes(next: ScreenLayerShape[]) {
  emit('update:shapes', next)
  emit('change')
}

function emitImages(next: Model3dScreenImage[]) {
  emit('update:images', next)
  emit('change')
}

function cloneShapes(): ScreenLayerShape[] {
  return JSON.parse(JSON.stringify(props.shapes)) as ScreenLayerShape[]
}

function updateShape(mutator: (shapes: ScreenLayerShape[]) => void) {
  const next = cloneShapes()
  mutator(next)
  emitShapes(next)
}

function hitTestImage(x: number, y: number): string | null {
  for (let i = props.images.length - 1; i >= 0; i--) {
    if (hitTestScreenImage(props.images[i], x, y)) return props.images[i].id
  }
  return null
}

function beginShapeEdit(shape: ScreenLayerShape, handleIndex: number | null, ev: MouseEvent) {
  shapeEdit.value = {
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

function finishPolylineDraft() {
  if (polylineDraft.value.length < 2) {
    polylineDraft.value = []
    polylineHover.value = null
    return
  }
  const points = polylineDraft.value.map((p) => ({ ...p }))
  const shape: ScreenLayerPolylineShape = {
    id: newScreenLayerShapeId(),
    type: 'polyline',
    points,
    x1: 0,
    y1: 0,
    x2: 0,
    y2: 0,
    color: props.color,
    strokeRel: DEFAULT_SCREEN_LAYER_STYLE.strokeRel,
  }
  syncScreenPolylineBbox(shape)
  emitShapes([...props.shapes, shape])
  emit('update:selectedShapeId', shape.id)
  emit('update:tool', 'select')
  polylineDraft.value = []
  polylineHover.value = null
}

type ScreenLayerPolylineShape = Extract<ScreenLayerShape, { type: 'polyline' }>

function onPointerDown(ev: MouseEvent) {
  if (!props.editable || !props.visible || ev.button !== 0) return
  const pos = normFromEvent(ev)
  if (!pos) return

  const onImageHandle = (ev.target as HTMLElement).closest('[data-handle="resize"]')
  const imgHit = hitTestImage(pos.x, pos.y)
  if (imgHit && (props.tool === 'select' || onImageHandle)) {
    emit('update:selectedImageId', imgHit)
    emit('update:selectedShapeId', null)
    const img = props.images.find((i) => i.id === imgHit)
    if (!img) return
    if (onImageHandle) {
      imageResizeStart.value = {
        imageId: imgHit,
        pointerX: ev.clientX,
        pointerY: ev.clientY,
        x: img.x,
        y: img.y,
        w: img.w,
        h: img.h,
      }
    } else {
      imageDragStart.value = {
        imageId: imgHit,
        pointerX: ev.clientX,
        pointerY: ev.clientY,
        x: img.x,
        y: img.y,
        w: img.w,
        h: img.h,
      }
    }
    ev.preventDefault()
    ev.stopPropagation()
    return
  }

  if ((ev.target as HTMLElement).closest('.model3d-screen-layer-text')) return

  emit('update:selectedImageId', null)

  const shapeHit = hitTestScreenShapes(props.shapes, pos.x, pos.y)

  if (pendingNewText.value) {
    if (editingText.value.trim()) commitTextOverlay()
    else cancelTextOverlay()
    if (shapeHit) return
  }

  if (props.tool === 'select' || props.tool === 'text') {
    const tryIds = [props.selectedShapeId, shapeHit].filter((id): id is string => !!id)
    for (const id of tryIds) {
      const sh = props.shapes.find((s) => s.id === id)
      if (!sh || sh.type === 'text') continue
      const hi = hitTestScreenShapeHandleIndex(sh, pos.x, pos.y)
      if (hi !== null && props.tool === 'select') {
        emit('update:selectedShapeId', id)
        emit('update:selectedImageId', null)
        beginShapeEdit(sh, hi, ev)
        ev.preventDefault()
        ev.stopPropagation()
        return
      }
    }
    if (shapeHit) {
      const sh = props.shapes.find((s) => s.id === shapeHit)
      emit('update:selectedShapeId', shapeHit)
      emit('update:selectedImageId', null)
      if (sh?.type === 'text') {
        editingText.value = sh.text
        if (props.tool === 'text') focusTextEditor(`[data-shape-id="${shapeHit}"] textarea`)
      } else if (props.tool === 'select' && sh) {
        beginShapeEdit(sh, null, ev)
      }
      ev.preventDefault()
      ev.stopPropagation()
      return
    }
    if (props.tool === 'select') {
      emit('update:selectedShapeId', null)
      emit('update:selectedImageId', null)
      return
    }
  }

  if (props.tool === 'polyline') {
    if (ev.detail >= 2) {
      finishPolylineDraft()
      return
    }
    polylineDraft.value.push({ x: pos.x, y: pos.y })
    emit('update:selectedShapeId', null)
    ev.preventDefault()
    ev.stopPropagation()
    return
  }

  if (props.tool === 'text') {
    pendingNewText.value = { x: pos.x, y: pos.y }
    pendingTextEnd.value = {
      x2: Math.min(1, pos.x + DEFAULT_TEXT_W),
      y2: Math.min(1, pos.y + DEFAULT_TEXT_H),
    }
    editingText.value = ''
    emit('update:selectedShapeId', null)
    focusTextEditor('.model3d-screen-layer-text--new textarea')
    ev.preventDefault()
    ev.stopPropagation()
    return
  }

  if (!isDragDrawScreenTool(props.tool)) return

  isDrawing.value = true
  draftShape.value = {
    id: newScreenLayerShapeId(),
    type: props.tool,
    x1: pos.x,
    y1: pos.y,
    x2: pos.x,
    y2: pos.y,
    color: props.color,
    strokeRel: DEFAULT_SCREEN_LAYER_STYLE.strokeRel,
    arrowRel: DEFAULT_SCREEN_LAYER_STYLE.arrowRel,
  }
  ev.preventDefault()
  ev.stopPropagation()
}

function onPointerMove(ev: MouseEvent) {
  if (imageResizeStart.value) {
    const el = overlayRef.value
    if (!el) return
    const r = el.getBoundingClientRect()
    const dx = (ev.clientX - imageResizeStart.value.pointerX) / r.width
    const dy = (ev.clientY - imageResizeStart.value.pointerY) / r.height
    const start = imageResizeStart.value
    const id = start.imageId
    const next = props.images.map((img) => {
      if (img.id !== id) return img
      return {
        ...img,
        w: clamp01(start.w + dx),
        h: clamp01(start.h + dy),
      }
    })
    emitImages(next)
    return
  }
  if (imageDragStart.value) {
    const el = overlayRef.value
    if (!el) return
    const r = el.getBoundingClientRect()
    const dx = (ev.clientX - imageDragStart.value.pointerX) / r.width
    const dy = (ev.clientY - imageDragStart.value.pointerY) / r.height
    const start = imageDragStart.value
    const id = start.imageId
    const next = props.images.map((img) => {
      if (img.id !== id) return img
      const nw = img.w
      const nh = img.h
      return {
        ...img,
        x: clamp(start.x + dx, 0, 1 - nw),
        y: clamp(start.y + dy, 0, 1 - nh),
      }
    })
    emitImages(next)
    return
  }

  if (polylineDraft.value.length > 0 && props.tool === 'polyline') {
    polylineHover.value = normFromEvent(ev, true)
  }

  if (shapeEdit.value && props.selectedShapeId) {
    const el = overlayRef.value
    if (!el) return
    const r = el.getBoundingClientRect()
    const dx = (ev.clientX - shapeEdit.value.pointerX) / r.width
    const dy = (ev.clientY - shapeEdit.value.pointerY) / r.height
    updateShape((shapes) => {
      const shape = shapes.find((s) => s.id === props.selectedShapeId)
      const edit = shapeEdit.value
      if (!shape || !edit || shape.type === 'text') return
      if (edit.handleIndex === null) {
        if (shape.type === 'polyline' && edit.points) {
          shape.points = edit.points.map((p) => ({
            x: clamp01(p.x + dx),
            y: clamp01(p.y + dy),
          }))
          syncScreenPolylineBbox(shape)
        } else if (isTwoPointScreenShape(shape)) {
          shape.x1 = clamp01(edit.x1 + dx)
          shape.y1 = clamp01(edit.y1 + dy)
          shape.x2 = clamp01(edit.x2 + dx)
          shape.y2 = clamp01(edit.y2 + dy)
        }
      } else {
        const pos = normFromEvent(ev, true)
        if (!pos) return
        if (shape.type === 'polyline') {
          shape.points[edit.handleIndex] = { x: pos.x, y: pos.y }
          syncScreenPolylineBbox(shape)
        } else if (edit.handleIndex === 0) {
          shape.x1 = pos.x
          shape.y1 = pos.y
        } else {
          shape.x2 = pos.x
          shape.y2 = pos.y
        }
      }
    })
    return
  }

  if (isDraggingText.value && textDragStart.value && props.selectedShapeId) {
    const el = overlayRef.value
    if (!el) return
    const r = el.getBoundingClientRect()
    const dx = (ev.clientX - textDragStart.value.pointerX) / r.width
    const dy = (ev.clientY - textDragStart.value.pointerY) / r.height
    updateShape((shapes) => {
      const shape = shapes.find((s) => s.id === props.selectedShapeId)
      if (shape?.type !== 'text') return
      const w = Math.abs(textDragStart.value!.x2 - textDragStart.value!.x1)
      const h = Math.abs(textDragStart.value!.y2 - textDragStart.value!.y1)
      shape.x1 = clamp01(textDragStart.value!.x1 + dx)
      shape.y1 = clamp01(textDragStart.value!.y1 + dy)
      shape.x2 = shape.x1 + w
      shape.y2 = shape.y1 + h
    })
    return
  }

  if (isResizingText.value && textResizeStart.value) {
    const el = overlayRef.value
    if (!el) return
    const r = el.getBoundingClientRect()
    const dx = (ev.clientX - textResizeStart.value.pointerX) / r.width
    const dy = (ev.clientY - textResizeStart.value.pointerY) / r.height
    const minSize = 0.02
    if (pendingNewText.value) {
      const nx2 = clamp01(textResizeStart.value.x2 + dx)
      const ny2 = clamp01(textResizeStart.value.y2 + dy)
      pendingTextEnd.value = { x2: nx2, y2: ny2 }
      textResizeStart.value = { ...textResizeStart.value, x2: nx2, y2: ny2 }
      return
    }
    updateShape((shapes) => {
      const shape = shapes.find((s) => s.id === props.selectedShapeId)
      if (shape?.type !== 'text') return
      const x1 = Math.min(shape.x1, shape.x2)
      const y1 = Math.min(shape.y1, shape.y2)
      shape.x2 = clamp(textResizeStart.value!.x2 + dx, x1 + minSize, 1)
      shape.y2 = clamp(textResizeStart.value!.y2 + dy, y1 + minSize, 1)
    })
    return
  }

  if (!isDrawing.value || !draftShape.value) return
  const pos = normFromEvent(ev, true)
  if (!pos || !draftShape.value) return
  draftShape.value = { ...draftShape.value, x2: pos.x, y2: pos.y }
}

function clamp(v: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, v))
}

function onPointerUp() {
  imageDragStart.value = null
  imageResizeStart.value = null
  shapeEdit.value = null
  isDraggingText.value = false
  textDragStart.value = null
  isResizingText.value = false
  textResizeStart.value = null

  if (!isDrawing.value || !draftShape.value) return
  const draft = draftShape.value
  isDrawing.value = false
  draftShape.value = null
  const dx = Math.abs(draft.x2 - draft.x1)
  const dy = Math.abs(draft.y2 - draft.y1)
  if (dx < 0.004 && dy < 0.004) return
  if (!isTwoPointScreenShape(draft)) return
  emitShapes([...props.shapes, { ...draft }])
  emit('update:selectedShapeId', draft.id)
  emit('update:selectedImageId', null)
  emit('update:tool', 'select')
}

function onImageWheel(ev: WheelEvent, img: Model3dScreenImage) {
  if (!props.editable) return
  emit('update:selectedImageId', img.id)
  emit('update:selectedShapeId', null)
  const el = overlayRef.value
  if (!el) return
  const factor = ev.deltaY < 0 ? 1.08 : 0.92
  const cx = img.x + img.w / 2
  const cy = img.y + img.h / 2
  const nw = clamp01(img.w * factor)
  const nh = clamp01(img.h * factor)
  const next = props.images.map((i) =>
    i.id === img.id
      ? {
          ...i,
          x: clamp01(cx - nw / 2),
          y: clamp01(cy - nh / 2),
          w: nw,
          h: nh,
        }
      : i,
  )
  emitImages(next)
  ev.preventDefault()
  ev.stopPropagation()
}

function commitTextOverlay() {
  const text = editingText.value.trim()
  if (!text || !pendingNewText.value) {
    pendingNewText.value = null
    pendingTextEnd.value = null
    return
  }
  const { x, y } = pendingNewText.value
  const x2 = pendingTextEnd.value?.x2 ?? Math.min(1, x + DEFAULT_TEXT_W)
  const y2 = pendingTextEnd.value?.y2 ?? Math.min(1, y + DEFAULT_TEXT_H)
  const shape: ScreenLayerShape = {
    id: newScreenLayerShapeId(),
    type: 'text',
    x1: Math.min(x, x2),
    y1: Math.min(y, y2),
    x2: Math.max(x, x2),
    y2: Math.max(y, y2),
    text,
    fontRel: DEFAULT_SCREEN_LAYER_STYLE.fontRel,
    color: props.color,
  }
  emitShapes([...props.shapes, shape])
  emit('update:selectedShapeId', shape.id)
  emit('update:tool', 'select')
  pendingNewText.value = null
  pendingTextEnd.value = null
  editingText.value = ''
}

function cancelTextOverlay() {
  pendingNewText.value = null
  pendingTextEnd.value = null
  editingText.value = ''
}

function focusTextEditor(selector: string) {
  nextTick(() => {
    const el = document.querySelector(selector) as HTMLTextAreaElement | null
    el?.focus()
  })
}

function onTextBoxMouseDown(ev: MouseEvent, shape: Extract<ScreenLayerShape, { type: 'text' }>) {
  if (!props.editable || ev.button !== 0) return
  if ((ev.target as HTMLElement).closest('.screen-layer-resize-handle')) return
  ev.preventDefault()
  ev.stopPropagation()
  cancelTextOverlay()
  emit('update:selectedShapeId', shape.id)
  emit('update:selectedImageId', null)
  editingText.value = shape.text
  if (props.tool === 'select') {
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
    focusTextEditor(`[data-shape-id="${shape.id}"] textarea`)
  }
}

function onTextResizeDown(ev: MouseEvent) {
  if (!props.editable) return
  ev.preventDefault()
  ev.stopPropagation()
  isResizingText.value = true
  const x2 = pendingTextEnd.value?.x2 ?? pendingNewText.value!.x + DEFAULT_TEXT_W
  const y2 = pendingTextEnd.value?.y2 ?? pendingNewText.value!.y + DEFAULT_TEXT_H
  textResizeStart.value = { pointerX: ev.clientX, pointerY: ev.clientY, x2, y2 }
}

function textBoxStyle(shape: Extract<ScreenLayerShape, { type: 'text' }>) {
  return {
    left: `${Math.min(shape.x1, shape.x2) * 100}%`,
    top: `${Math.min(shape.y1, shape.y2) * 100}%`,
    width: `${Math.abs(shape.x2 - shape.x1) * 100}%`,
    height: `${Math.abs(shape.y2 - shape.y1) * 100}%`,
    fontSize: `${(shape.fontRel ?? DEFAULT_SCREEN_LAYER_STYLE.fontRel) * 100}cqh`,
    color: shape.color ?? props.color,
  }
}

function imageStyle(img: Model3dScreenImage) {
  return {
    left: `${img.x * 100}%`,
    top: `${img.y * 100}%`,
    width: `${img.w * 100}%`,
    height: `${img.h * 100}%`,
  }
}

function handleStyle(h: ScreenLayerPoint) {
  return { left: `${h.x * 100}%`, top: `${h.y * 100}%` }
}

function deleteSelected() {
  if (props.selectedImageId) {
    emitImages(props.images.filter((i) => i.id !== props.selectedImageId))
    emit('update:selectedImageId', null)
    return
  }
  if (!props.selectedShapeId) return
  emitShapes(props.shapes.filter((s) => s.id !== props.selectedShapeId))
  emit('update:selectedShapeId', null)
}

function handleEscape() {
  if (isDrawing.value) {
    isDrawing.value = false
    draftShape.value = null
  }
  if (pendingNewText.value) cancelTextOverlay()
  if (polylineDraft.value.length) {
    polylineDraft.value = []
    polylineHover.value = null
  }
  shapeEdit.value = null
  emit('update:selectedShapeId', null)
  emit('update:selectedImageId', null)
  emit('update:tool', 'select')
}

function onKeydown(ev: KeyboardEvent) {
  if (!props.visible || !props.editable) return
  if (ev.key === 'Escape') {
    handleEscape()
    ev.preventDefault()
    return
  }
  if (ev.key === 'Enter' && props.tool === 'polyline' && polylineDraft.value.length >= 2) {
    ev.preventDefault()
    finishPolylineDraft()
    return
  }
  if (ev.key === 'Delete' || ev.key === 'Backspace') {
    const tag = (ev.target as HTMLElement)?.tagName
    if (tag === 'INPUT' || tag === 'TEXTAREA') return
    if (props.selectedShapeId || props.selectedImageId) {
      ev.preventDefault()
      deleteSelected()
    }
  }
}

defineExpose({ deleteSelected, handleEscape })

watch(
  () => props.tool,
  () => {
    polylineDraft.value = []
    polylineHover.value = null
    draftShape.value = null
    isDrawing.value = false
  },
)

onMounted(() => {
  window.addEventListener('mousemove', onPointerMove)
  window.addEventListener('mouseup', onPointerUp)
  window.addEventListener('keydown', onKeydown, true)
})

onUnmounted(() => {
  window.removeEventListener('mousemove', onPointerMove)
  window.removeEventListener('mouseup', onPointerUp)
  window.removeEventListener('keydown', onKeydown, true)
})
</script>

<template>
  <div
    v-show="visible"
    ref="overlayRef"
    class="model3d-screen-layer"
    :class="{ 'has-draw-capture': needsDrawCapture }"
  >
    <div
      v-if="needsDrawCapture"
      class="model3d-screen-draw-capture"
      @mousedown="onPointerDown"
    />
    <svg class="model3d-screen-layer-svg" viewBox="0 0 1 1" preserveAspectRatio="none">
      <template v-for="shape in vectorShapes" :key="shape.id">
        <g
          class="screen-layer-shape-hit"
          :class="{ 'is-selected': selectedShapeId === shape.id }"
          :style="{ pointerEvents: tool === 'select' ? 'visibleStroke' : 'none' }"
          @mousedown="tool === 'select' ? onPointerDown($event) : undefined"
        >
          <g v-if="shape.type === 'arrow'">
            <line
              :x1="shape.x1"
              :y1="shape.y1"
              :x2="shape.x2"
              :y2="shape.y2"
              :stroke="shape.color ?? color"
              :stroke-width="svgNormStrokeWidth(shape)"
              stroke-linecap="round"
            />
            <polygon
              :points="arrowHeadPointsNorm(shape.x1, shape.y1, shape.x2, shape.y2, svgNormArrowHeadRel(shape))"
              :fill="shape.color ?? color"
              pointer-events="none"
            />
          </g>
          <line
            v-else-if="shape.type === 'line'"
            :x1="shape.x1"
            :y1="shape.y1"
            :x2="shape.x2"
            :y2="shape.y2"
            :stroke="shape.color ?? color"
            :stroke-width="svgNormStrokeWidth(shape)"
            stroke-linecap="round"
          />
          <rect
            v-else-if="shape.type === 'rect'"
            :x="Math.min(shape.x1, shape.x2)"
            :y="Math.min(shape.y1, shape.y2)"
            :width="Math.abs(shape.x2 - shape.x1)"
            :height="Math.abs(shape.y2 - shape.y1)"
            fill="none"
            :stroke="shape.color ?? color"
            :stroke-width="svgNormStrokeWidth(shape)"
          />
          <ellipse
            v-else-if="shape.type === 'ellipse'"
            :cx="(shape.x1 + shape.x2) / 2"
            :cy="(shape.y1 + shape.y2) / 2"
            :rx="Math.abs(shape.x2 - shape.x1) / 2"
            :ry="Math.abs(shape.y2 - shape.y1) / 2"
            fill="none"
            :stroke="shape.color ?? color"
            :stroke-width="svgNormStrokeWidth(shape)"
          />
          <polyline
            v-else-if="shape.type === 'polyline'"
            :points="polylineSvgPoints(shape.points)"
            fill="none"
            :stroke="shape.color ?? color"
            :stroke-width="svgNormStrokeWidth(shape)"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </g>
      </template>
      <polyline
        v-if="polylinePreviewPoints"
        :points="polylinePreviewPoints"
        fill="none"
        :stroke="color"
        :stroke-width="svgNormStrokeWidth()"
        stroke-dasharray="0.012 0.01"
        stroke-linecap="round"
        pointer-events="none"
      />
      <template v-if="draftShape && isTwoPointScreenShape(draftShape)">
        <g v-if="draftShape.type === 'arrow'" pointer-events="none">
          <line
            :x1="draftShape.x1"
            :y1="draftShape.y1"
            :x2="draftShape.x2"
            :y2="draftShape.y2"
            :stroke="draftShape.color ?? color"
            :stroke-width="svgNormStrokeWidth(draftShape)"
            stroke-linecap="round"
          />
          <polygon
            :points="
              arrowHeadPointsNorm(
                draftShape.x1,
                draftShape.y1,
                draftShape.x2,
                draftShape.y2,
                svgNormArrowHeadRel(draftShape),
              )
            "
            :fill="draftShape.color ?? color"
          />
        </g>
        <line
          v-else-if="draftShape.type === 'line'"
          :x1="draftShape.x1"
          :y1="draftShape.y1"
          :x2="draftShape.x2"
          :y2="draftShape.y2"
          :stroke="draftShape.color ?? color"
          :stroke-width="svgNormStrokeWidth(draftShape)"
          stroke-linecap="round"
          pointer-events="none"
        />
        <rect
          v-else-if="draftShape.type === 'rect'"
          :x="Math.min(draftShape.x1, draftShape.x2)"
          :y="Math.min(draftShape.y1, draftShape.y2)"
          :width="Math.abs(draftShape.x2 - draftShape.x1)"
          :height="Math.abs(draftShape.y2 - draftShape.y1)"
          fill="none"
          :stroke="draftShape.color ?? color"
          :stroke-width="svgNormStrokeWidth(draftShape)"
          pointer-events="none"
        />
        <ellipse
          v-else-if="draftShape.type === 'ellipse'"
          :cx="(draftShape.x1 + draftShape.x2) / 2"
          :cy="(draftShape.y1 + draftShape.y2) / 2"
          :rx="Math.abs(draftShape.x2 - draftShape.x1) / 2"
          :ry="Math.abs(draftShape.y2 - draftShape.y1) / 2"
          fill="none"
          :stroke="draftShape.color ?? color"
          :stroke-width="svgNormStrokeWidth(draftShape)"
          pointer-events="none"
        />
      </template>
      <rect
        v-if="selectedShapeSelectionRect"
        class="model3d-screen-selection-box"
        :x="selectedShapeSelectionRect.x"
        :y="selectedShapeSelectionRect.y"
        :width="selectedShapeSelectionRect.width"
        :height="selectedShapeSelectionRect.height"
        fill="none"
        :stroke="SELECTION_STROKE"
        stroke-width="0.005"
        stroke-dasharray="0.015 0.01"
        pointer-events="none"
      />
    </svg>
    <button
      v-for="(h, hi) in selectedShapeHandles"
      v-show="tool === 'select'"
      :key="`h-${selectedShapeId}-${hi}`"
      type="button"
      class="screen-layer-handle"
      :style="handleStyle(h)"
      @mousedown.stop="onPointerDown"
    />
    <div
      v-for="img in images"
      v-show="img.dataUrl"
      :key="img.id"
      class="model3d-screen-layer-image-wrap"
      :class="{ 'is-selected': selectedImageId === img.id }"
      :style="imageStyle(img)"
      @mousedown="onPointerDown"
      @wheel="onImageWheel($event, img)"
    >
      <img class="model3d-screen-layer-image" :src="img.dataUrl" alt="" draggable="false" />
      <button
        v-if="selectedImageId === img.id && editable"
        type="button"
        class="screen-layer-resize-handle"
        data-handle="resize"
        title="Тянуть для размера; колёсико — зум"
        @mousedown.stop="onPointerDown"
      />
    </div>
    <div
      v-for="shape in textShapes"
      :key="shape.id"
      class="model3d-screen-layer-text"
      :class="{ 'is-selected': selectedShapeId === shape.id }"
      :style="textBoxStyle(shape)"
      :data-shape-id="shape.id"
      @mousedown="onTextBoxMouseDown($event, shape)"
    >
      <div v-if="selectedShapeId !== shape.id || !editable" class="model3d-screen-layer-text-view">{{ shape.text }}</div>
      <textarea
        v-else
        v-model="editingText"
        class="model3d-screen-layer-text-editor"
        @blur="updateShape((arr) => { const s = arr.find((x) => x.id === shape.id); if (s?.type === 'text') s.text = editingText })"
      />
      <button
        v-if="(selectedShapeId === shape.id || pendingNewText) && editable"
        type="button"
        class="screen-layer-resize-handle"
        title="Размер"
        @mousedown.stop="onTextResizeDown"
      />
    </div>
    <div
      v-if="pendingNewText"
      class="model3d-screen-layer-text model3d-screen-layer-text--new"
      :style="{
        left: `${pendingNewText.x * 100}%`,
        top: `${pendingNewText.y * 100}%`,
        width: `${(pendingTextEnd ? Math.abs(pendingTextEnd.x2 - pendingNewText.x) : DEFAULT_TEXT_W) * 100}%`,
        height: `${(pendingTextEnd ? Math.abs(pendingTextEnd.y2 - pendingNewText.y) : DEFAULT_TEXT_H) * 100}%`,
      }"
      @mousedown.stop
    >
      <textarea
        v-model="editingText"
        class="model3d-screen-layer-text-editor"
        placeholder="Текст…"
        @keydown.enter.ctrl.prevent="commitTextOverlay"
        @blur="commitTextOverlay"
      />
      <button type="button" class="screen-layer-resize-handle" @mousedown.stop="onTextResizeDown" />
    </div>
  </div>
</template>

<style scoped>
.model3d-screen-layer {
  position: absolute;
  inset: 0;
  pointer-events: none;
  container-type: size;
  z-index: 4;
}
.model3d-screen-draw-capture {
  position: absolute;
  inset: 0;
  pointer-events: auto;
  cursor: crosshair;
  z-index: 4;
}
.model3d-screen-layer-svg {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 2;
}
.screen-layer-shape-hit {
  cursor: pointer;
}
.screen-layer-shape-hit.is-selected {
  cursor: move;
}
.model3d-screen-selection-box {
  pointer-events: none;
}
.screen-layer-handle {
  position: absolute;
  width: 12px;
  height: 12px;
  margin: -6px 0 0 -6px;
  border-radius: 50%;
  border: 1px solid #1e3a8a;
  background: #b8cce8;
  padding: 0;
  pointer-events: auto;
  cursor: nwse-resize;
  z-index: 6;
}
.model3d-screen-layer-image-wrap {
  position: absolute;
  pointer-events: auto;
  box-sizing: border-box;
  border: 1px solid transparent;
  z-index: 5;
  cursor: grab;
}
.model3d-screen-layer-image-wrap:active {
  cursor: grabbing;
}
.model3d-screen-layer-image-wrap.is-selected {
  border-color: rgba(59, 130, 246, 0.85);
  box-shadow: 0 0 0 1px rgba(59, 130, 246, 0.4);
}
.model3d-screen-layer-image {
  width: 100%;
  height: 100%;
  object-fit: contain;
  pointer-events: none;
  display: block;
}
.screen-layer-resize-handle {
  position: absolute;
  right: -5px;
  bottom: -5px;
  width: 14px;
  height: 14px;
  padding: 0;
  border: 1px solid #1e3a8a;
  background: #b8cce8;
  border-radius: 2px;
  cursor: nwse-resize;
  pointer-events: auto;
  z-index: 2;
}
.model3d-screen-layer-text {
  position: absolute;
  box-sizing: border-box;
  overflow: hidden;
  pointer-events: auto;
  border: 1px dashed transparent;
  z-index: 5;
}
.model3d-screen-layer-text.is-selected {
  border-color: rgba(59, 130, 246, 0.7);
}
.model3d-screen-layer-text-view {
  padding: 2px 4px;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.25;
  pointer-events: none;
}
.model3d-screen-layer-text-editor {
  width: 100%;
  height: 100%;
  resize: none;
  border: none;
  background: rgba(255, 255, 255, 0.92);
  color: inherit;
  font: inherit;
  padding: 4px;
  box-sizing: border-box;
}
</style>
