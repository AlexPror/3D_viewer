<script setup lang="ts">
import { ref, watch, onMounted, onUnmounted, computed } from 'vue'

const props = defineProps<{
  imageUrl: string
  suggestedFileName?: string | null
}>()

const emit = defineEmits<{
  close: []
}>()

const canvasRef = ref<HTMLCanvasElement | null>(null)
const tool = ref<'arrow' | 'rect' | 'ellipse' | 'text'>('arrow')
const isDrawing = ref(false)
const startX = ref(0)
const startY = ref(0)
type ShapeItem =
  | { type: string; x1: number; y1: number; x2: number; y2: number; color?: string }
  | { type: 'text'; x1: number; y1: number; x2: number; y2: number; text: string; fontSize?: number; color?: string }
const shapes = ref<ShapeItem[]>([])
const currentStrokeColor = ref('#ff0000')
const currentTextColor = ref('#cc0000')
const currentFontSize = ref(16)

const textFontSizeModel = computed({
  get: () => {
    if (selectedTextIndex.value != null) {
      const s = shapes.value[selectedTextIndex.value]
      if (s?.type === 'text' && s.fontSize != null) return s.fontSize
    }
    return currentFontSize.value
  },
  set: (v: number) => {
    if (selectedTextIndex.value != null) {
      const s = shapes.value[selectedTextIndex.value]
      if (s?.type === 'text') (s as { fontSize?: number }).fontSize = v
      redraw()
    } else currentFontSize.value = v
  },
})
const textColorModel = computed({
  get: () => {
    if (selectedTextIndex.value != null) {
      const s = shapes.value[selectedTextIndex.value]
      if (s?.type === 'text' && s.color) return s.color
    }
    return currentTextColor.value
  },
  set: (v: string) => {
    if (selectedTextIndex.value != null) {
      const s = shapes.value[selectedTextIndex.value]
      if (s?.type === 'text') (s as { color?: string }).color = v
      redraw()
    } else currentTextColor.value = v
  },
})

const canvasWrapRef = ref<HTMLDivElement | null>(null)
const selectedTextIndex = ref<number | null>(null)
const pendingNewText = ref<{ x: number; y: number } | null>(null)
const editingText = ref('')
const canvasWidth = ref(0)
const canvasHeight = ref(0)
const isDraggingText = ref(false)
const dragStart = ref<{ canvasX: number; canvasY: number; x1: number; y1: number; x2: number; y2: number } | null>(null)

const DEFAULT_TEXT_W = 200
const DEFAULT_TEXT_H = 60

const overlayVisible = computed(() => selectedTextIndex.value !== null || pendingNewText.value !== null)

const overlayBoxStyle = computed(() => {
  if (selectedTextIndex.value !== null) {
    const s = shapes.value[selectedTextIndex.value]
    if (s?.type === 'text') {
      const x = Math.min(s.x1, s.x2)
      const y = Math.min(s.y1, s.y2)
      const w = Math.max(20, Math.abs(s.x2 - s.x1))
      const h = Math.max(20, Math.abs(s.y2 - s.y1))
      return { left: x + 'px', top: y + 'px', width: w + 'px', height: h + 'px' }
    }
  }
  if (pendingNewText.value) {
    return {
      left: pendingNewText.value.x + 'px',
      top: pendingNewText.value.y + 'px',
      width: DEFAULT_TEXT_W + 'px',
      height: DEFAULT_TEXT_H + 'px',
    }
  }
  return { left: '0px', top: '0px', width: '0px', height: '0px' }
})

let img: HTMLImageElement | null = null
let ctx: CanvasRenderingContext2D | null = null

function loadImage() {
  if (!canvasRef.value || !props.imageUrl) return
  img = new Image()
  img.crossOrigin = 'anonymous'
  img.onload = () => {
    if (!canvasRef.value || !img) return
    canvasRef.value.width = img.width
    canvasRef.value.height = img.height
    canvasWidth.value = img.width
    canvasHeight.value = img.height
    ctx = canvasRef.value.getContext('2d')
    redraw()
  }
  img.src = props.imageUrl
}

function redraw() {
  if (!canvasRef.value || !ctx || !img) return
  ctx.clearRect(0, 0, canvasRef.value.width, canvasRef.value.height)
  ctx.drawImage(img, 0, 0)
  shapes.value.forEach((s) => {
    if (s.type === 'text') {
      const x = Math.min(s.x1, s.x2)
      const y = Math.min(s.y1, s.y2)
      const w = Math.abs(s.x2 - s.x1)
      const h = Math.abs(s.y2 - s.y1)
      if (w < 4 || h < 4) return
      const fontSize = s.fontSize ?? 16
      const textColor = s.color ?? '#cc0000'
      ctx!.save()
      ctx!.beginPath()
      ctx!.rect(x, y, w, h)
      ctx!.clip()
      const padding = 6
      const innerX = x + padding
      const lineHeight = Math.max(18, fontSize + 4)
      let innerY = y + padding + lineHeight - 4
      const maxW = w - padding * 2
      ctx!.font = `${Math.min(fontSize, Math.floor(h / 2))}px sans-serif`
      ctx!.fillStyle = textColor
      ctx!.strokeStyle = '#fff'
      ctx!.lineWidth = 1
      const words = s.text.split(/\s+/)
      let line = ''
      for (const word of words) {
        const test = line ? line + ' ' + word : word
        const m = ctx!.measureText(test)
        if (m.width > maxW && line) {
          ctx!.strokeText(line, innerX, innerY)
          ctx!.fillText(line, innerX, innerY)
          innerY += lineHeight
          line = word
        } else {
          line = test
        }
      }
      if (line) {
        ctx!.strokeText(line, innerX, innerY)
        ctx!.fillText(line, innerX, innerY)
      }
      ctx!.restore()
      return
    }
    const strokeColor = (s as { color?: string }).color ?? '#ff0000'
    ctx!.strokeStyle = strokeColor
    ctx!.lineWidth = 2
    if (s.type === 'arrow') {
      drawArrow(ctx!, s.x1, s.y1, s.x2, s.y2, strokeColor)
    } else if (s.type === 'rect') {
      ctx!.strokeRect(s.x1, s.y1, s.x2 - s.x1, s.y2 - s.y1)
    } else if (s.type === 'ellipse') {
      const cx = (s.x1 + s.x2) / 2
      const cy = (s.y1 + s.y2) / 2
      const rx = Math.abs(s.x2 - s.x1) / 2
      const ry = Math.abs(s.y2 - s.y1) / 2
      ctx!.beginPath()
      ctx!.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2)
      ctx!.stroke()
    }
  })
}

function drawArrow(
  ctx: CanvasRenderingContext2D,
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  color: string = '#ff0000'
) {
  ctx.beginPath()
  ctx.moveTo(x1, y1)
  ctx.lineTo(x2, y2)
  ctx.stroke()
  const angle = Math.atan2(y2 - y1, x2 - x1)
  const headLen = 12
  ctx.beginPath()
  ctx.moveTo(x2, y2)
  ctx.lineTo(x2 - headLen * Math.cos(angle - Math.PI / 6), y2 - headLen * Math.sin(angle - Math.PI / 6))
  ctx.lineTo(x2 - headLen * Math.cos(angle + Math.PI / 6), y2 - headLen * Math.sin(angle + Math.PI / 6))
  ctx.closePath()
  ctx.fillStyle = color
  ctx.fill()
  ctx.stroke()
}

function getMousePos(e: MouseEvent) {
  if (!canvasRef.value) return { x: 0, y: 0 }
  const r = canvasRef.value.getBoundingClientRect()
  const scaleX = canvasRef.value.width / r.width
  const scaleY = canvasRef.value.height / r.height
  return {
    x: (e.clientX - r.left) * scaleX,
    y: (e.clientY - r.top) * scaleY,
  }
}

function hitTestText(pos: { x: number; y: number }): number | null {
  for (let i = shapes.value.length - 1; i >= 0; i--) {
    const s = shapes.value[i]
    if (s.type !== 'text') continue
    const x = Math.min(s.x1, s.x2)
    const y = Math.min(s.y1, s.y2)
    const w = Math.abs(s.x2 - s.x1)
    const h = Math.abs(s.y2 - s.y1)
    if (pos.x >= x && pos.x <= x + w && pos.y >= y && pos.y <= y + h) return i
  }
  return null
}

function commitTextOverlay() {
  if (pendingNewText.value) {
    const { x, y } = pendingNewText.value
    const text = editingText.value.trim()
    if (text) {
      shapes.value.push({
        type: 'text',
        x1: x,
        y1: y,
        x2: x + DEFAULT_TEXT_W,
        y2: y + DEFAULT_TEXT_H,
        text,
        fontSize: currentFontSize.value,
        color: currentTextColor.value,
      })
      selectedTextIndex.value = shapes.value.length - 1
      pendingNewText.value = null
    } else {
      pendingNewText.value = null
    }
  } else if (selectedTextIndex.value !== null) {
    const s = shapes.value[selectedTextIndex.value]
    if (s?.type === 'text') s.text = editingText.value
  }
  redraw()
}

function closeTextOverlay() {
  commitTextOverlay()
  selectedTextIndex.value = null
  pendingNewText.value = null
}

function deleteSelectedText() {
  if (selectedTextIndex.value === null) return
  shapes.value.splice(selectedTextIndex.value, 1)
  selectedTextIndex.value = null
  pendingNewText.value = null
  redraw()
}

function onDragHandleMouseDown(e: MouseEvent) {
  e.preventDefault()
  e.stopPropagation()
  if (selectedTextIndex.value === null) return
  const pos = getMousePos(e)
  const s = shapes.value[selectedTextIndex.value]
  if (s?.type !== 'text') return
  isDraggingText.value = true
  dragStart.value = {
    canvasX: pos.x,
    canvasY: pos.y,
    x1: s.x1,
    y1: s.y1,
    x2: s.x2,
    y2: s.y2,
  }
}

function onOverlayMouseDown(e: MouseEvent) {
  if ((e.target as HTMLElement).tagName === 'TEXTAREA' || (e.target as HTMLElement).tagName === 'INPUT') return
  if ((e.target as HTMLElement).closest('.text-drag-handle') || (e.target as HTMLElement).closest('button')) return
  if (selectedTextIndex.value === null) return
  const pos = getMousePos(e)
  const s = shapes.value[selectedTextIndex.value]
  if (s?.type !== 'text') return
  e.preventDefault()
  e.stopPropagation()
  isDraggingText.value = true
  dragStart.value = {
    canvasX: pos.x,
    canvasY: pos.y,
    x1: s.x1,
    y1: s.y1,
    x2: s.x2,
    y2: s.y2,
  }
}

function onDocumentMouseMove(e: MouseEvent) {
  if (!isDraggingText.value || dragStart.value === null || selectedTextIndex.value === null) return
  const pos = getMousePos(e)
  const dx = pos.x - dragStart.value.canvasX
  const dy = pos.y - dragStart.value.canvasY
  const s = shapes.value[selectedTextIndex.value]
  if (s?.type === 'text') {
    s.x1 = dragStart.value.x1 + dx
    s.y1 = dragStart.value.y1 + dy
    s.x2 = dragStart.value.x2 + dx
    s.y2 = dragStart.value.y2 + dy
    dragStart.value = { ...dragStart.value, canvasX: pos.x, canvasY: pos.y, x1: s.x1, y1: s.y1, x2: s.x2, y2: s.y2 }
  }
  redraw()
}

function onDocumentMouseUp() {
  if (isDraggingText.value) {
    isDraggingText.value = false
    dragStart.value = null
  }
}

function onMouseDown(e: MouseEvent) {
  if (!ctx || !canvasRef.value) return
  const pos = getMousePos(e)
  startX.value = pos.x
  startY.value = pos.y
  if (tool.value === 'text') {
    closeTextOverlay()
    const hit = hitTestText(pos)
    if (hit !== null) {
      selectedTextIndex.value = hit
      editingText.value = (shapes.value[hit] as { type: 'text'; text: string }).text
      pendingNewText.value = null
    } else {
      pendingNewText.value = { x: pos.x, y: pos.y }
      editingText.value = ''
      selectedTextIndex.value = null
    }
    redraw()
    return
  }
  isDrawing.value = true
}

function onMouseMove(e: MouseEvent) {
  if (!isDrawing.value || !ctx) return
  const pos = getMousePos(e)
  redraw()
  ctx.strokeStyle = currentStrokeColor.value
  ctx.lineWidth = 2
  if (tool.value === 'arrow') drawArrow(ctx, startX.value, startY.value, pos.x, pos.y, currentStrokeColor.value)
  else if (tool.value === 'rect') ctx.strokeRect(startX.value, startY.value, pos.x - startX.value, pos.y - startY.value)
  else if (tool.value === 'ellipse') {
    const cx = (startX.value + pos.x) / 2
    const cy = (startY.value + pos.y) / 2
    const rx = Math.abs(pos.x - startX.value) / 2
    const ry = Math.abs(pos.y - startY.value) / 2
    ctx.beginPath()
    ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2)
    ctx.stroke()
  }
}

function onMouseUp(e: MouseEvent) {
  if (!isDrawing.value) return
  const pos = getMousePos(e)
  const dx = Math.abs(pos.x - startX.value)
  const dy = Math.abs(pos.y - startY.value)
  if ((dx > 3 || dy > 3) && (tool.value === 'arrow' || tool.value === 'rect' || tool.value === 'ellipse')) {
    shapes.value.push({
      type: tool.value,
      x1: startX.value,
      y1: startY.value,
      x2: pos.x,
      y2: pos.y,
      color: currentStrokeColor.value,
    })
  }
  isDrawing.value = false
  redraw()
}

function saveToFile() {
  if (!canvasRef.value) return
  const a = document.createElement('a')
  a.href = canvasRef.value.toDataURL('image/png')
  const baseName = props.suggestedFileName?.replace(/\.[^.]+$/, '') ?? ''
  const safe = baseName ? baseName.replace(/[<>:"/\\|?*\x00-\x1f]/g, '_').trim() || undefined : undefined
  a.download = safe ? `${safe}.png` : `screenshot-${Date.now()}.png`
  a.click()
}

function sendToChat() {
  alert('Отправка в чат — заглушка. Здесь будет интеграция с чатом проекта.')
}

watch(editingText, () => {
  if (selectedTextIndex.value !== null) {
    const s = shapes.value[selectedTextIndex.value]
    if (s?.type === 'text') s.text = editingText.value
    redraw()
  }
})

watch([selectedTextIndex, pendingNewText], () => {
  if (selectedTextIndex.value !== null) {
    const s = shapes.value[selectedTextIndex.value]
    editingText.value = s?.type === 'text' ? s.text : ''
  } else if (pendingNewText.value !== null) {
    editingText.value = ''
  }
})

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Delete' || e.key === 'Backspace') {
    if (selectedTextIndex.value !== null && document.activeElement?.tagName !== 'TEXTAREA') {
      deleteSelectedText()
      e.preventDefault()
    }
  }
}

onMounted(() => {
  loadImage()
  document.addEventListener('mousemove', onDocumentMouseMove)
  document.addEventListener('mouseup', onDocumentMouseUp)
  document.addEventListener('keydown', onKeydown)
})
onUnmounted(() => {
  document.removeEventListener('mousemove', onDocumentMouseMove)
  document.removeEventListener('mouseup', onDocumentMouseUp)
  document.removeEventListener('keydown', onKeydown)
})
watch(() => props.imageUrl, () => loadImage())
</script>

<template>
  <div class="modal-overlay" @click.self="emit('close')">
    <div class="modal">
      <div class="modal-header">
        <span>Редактор скриншота</span>
        <button type="button" class="btn-close" @click="emit('close')">×</button>
      </div>
      <div class="toolbar">
        <button type="button" :class="{ active: tool === 'arrow' }" @click="tool = 'arrow'">Стрелка</button>
        <button type="button" :class="{ active: tool === 'rect' }" @click="tool = 'rect'">Прямоугольник</button>
        <button type="button" :class="{ active: tool === 'ellipse' }" @click="tool = 'ellipse'">Эллипс</button>
        <button type="button" :class="{ active: tool === 'text' }" @click="tool = 'text'">Текст</button>
        <template v-if="tool === 'text'">
          <label class="toolbar-label">Шрифт:</label>
          <input v-model.number="textFontSizeModel" type="number" min="8" max="72" class="toolbar-input-num" />
          <label class="toolbar-label">Цвет:</label>
          <input v-model="textColorModel" type="color" class="toolbar-input-color" />
        </template>
        <template v-else>
          <label class="toolbar-label">Цвет:</label>
          <input v-model="currentStrokeColor" type="color" class="toolbar-input-color" />
        </template>
        <button type="button" @click="saveToFile">Сохранить на ПК</button>
        <button type="button" @click="sendToChat">Отправить в чат</button>
      </div>
      <div v-if="tool === 'text'" class="text-hint">Кликните на изображение — откроется блок. Перетащите за полоску «Перетащить» или за край блока. Удалить: кнопка или Delete.</div>
      <div class="canvas-wrap">
        <div
          ref="canvasWrapRef"
          class="canvas-container"
          :style="{ width: canvasWidth + 'px', minHeight: canvasHeight + 'px' }"
        >
          <canvas
            ref="canvasRef"
            class="editor-canvas"
            :width="canvasWidth"
            :height="canvasHeight"
            @mousedown="onMouseDown"
            @mousemove="onMouseMove"
            @mouseup="onMouseUp"
            @mouseleave="isDrawing = false"
          />
          <div
            v-if="overlayVisible"
            class="text-overlay"
            @mousedown="onOverlayMouseDown"
          >
            <div class="text-editor-box" :style="overlayBoxStyle">
              <div class="text-drag-handle" @mousedown="onDragHandleMouseDown">⋮⋮ Перетащить</div>
              <textarea
                v-model="editingText"
                rows="3"
                placeholder="Введите текст..."
                class="text-area-inline"
                @blur="commitTextOverlay"
              />
              <button v-if="selectedTextIndex !== null" type="button" class="btn-delete-text" @click="deleteSelectedText">Удалить</button>
              <button v-else type="button" class="btn-cancel-text" @click="pendingNewText = null; selectedTextIndex = null">Отмена</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.modal {
  background: #252525;
  border-radius: 8px;
  max-width: 95vw;
  max-height: 95vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.5rem 1rem;
  border-bottom: 1px solid #444;
}
.btn-close {
  background: none;
  border: none;
  color: #aaa;
  font-size: 1.5rem;
  cursor: pointer;
  padding: 0 0.5rem;
}
.btn-close:hover {
  color: #fff;
}
.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  padding: 0.5rem;
  border-bottom: 1px solid #444;
}
.toolbar button {
  padding: 0.35rem 0.6rem;
  font-size: 0.85rem;
  background: #333;
  color: #e0e0e0;
  border: 1px solid #555;
  border-radius: 4px;
  cursor: pointer;
}
.toolbar button:hover {
  background: #444;
}
.toolbar button.active {
  background: #646cff;
  border-color: #646cff;
}
.toolbar-label {
  font-size: 0.85rem;
  color: #aaa;
  margin-left: 0.5rem;
}
.toolbar-input-num {
  width: 3rem;
  padding: 0.2rem 0.3rem;
  font-size: 0.85rem;
  background: #333;
  color: #eee;
  border: 1px solid #555;
  border-radius: 4px;
}
.toolbar-input-color {
  width: 2rem;
  height: 1.6rem;
  padding: 0;
  border: 1px solid #555;
  border-radius: 4px;
  cursor: pointer;
  background: #333;
}
.text-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.4rem 0.5rem;
  background: #2a2a2a;
  border-bottom: 1px solid #444;
}
.text-label {
  font-size: 0.85rem;
  color: #ccc;
  white-space: nowrap;
}
.text-input {
  flex: 1;
  min-width: 0;
  padding: 0.35rem 0.5rem;
  font-size: 0.9rem;
  background: #1a1a1a;
  color: #eee;
  border: 1px solid #555;
  border-radius: 4px;
}
.text-input::placeholder {
  color: #888;
}
.text-hint {
  font-size: 0.8rem;
  color: #999;
  padding: 0.3rem 0.5rem;
  border-bottom: 1px solid #333;
}
.canvas-wrap {
  overflow: auto;
  padding: 0.5rem;
  max-height: 70vh;
}
.canvas-container {
  position: relative;
  display: inline-block;
}
.editor-canvas {
  display: block;
  width: 100%;
  height: 100%;
  cursor: crosshair;
}
.text-overlay {
  position: absolute;
  inset: 0;
  pointer-events: none;
}
.text-overlay .text-editor-box {
  pointer-events: auto;
}
.text-editor-box {
  position: absolute;
  border: none;
  background: transparent;
  display: flex;
  flex-direction: column;
  padding: 0;
  cursor: move;
  min-width: 80px;
  min-height: 40px;
}
.text-area-inline {
  flex: 1;
  min-height: 36px;
  resize: none;
  border: none;
  padding: 4px;
  font-size: 14px;
  font-family: sans-serif;
  background: transparent;
  outline: none;
  cursor: text;
}
.btn-delete-text {
  align-self: flex-end;
  padding: 2px 8px;
  font-size: 12px;
  margin-top: 2px;
  cursor: pointer;
  background: #c00;
  color: #fff;
  border: none;
  border-radius: 3px;
}
.btn-delete-text:hover {
  background: #e00;
}
.btn-cancel-text {
  align-self: flex-end;
  padding: 2px 8px;
  font-size: 12px;
  margin-top: 2px;
  cursor: pointer;
  background: #555;
  color: #fff;
  border: none;
  border-radius: 3px;
}
.btn-cancel-text:hover {
  background: #666;
}
.text-drag-handle {
  padding: 2px 6px;
  font-size: 11px;
  color: #666;
  cursor: move;
  user-select: none;
  background: rgba(0, 0, 0, 0.06);
  border-bottom: 1px solid rgba(0, 0, 0, 0.1);
}
.text-drag-handle:hover {
  background: rgba(0, 0, 0, 0.1);
  color: #333;
}
</style>
