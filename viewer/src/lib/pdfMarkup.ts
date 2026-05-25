import { PDFDocument, rgb, type PDFPage } from 'pdf-lib'
import { type RemarkStatus, normalizeRemarkStatus } from './remarkStatus'

export type PdfMarkupTool =
  | 'arrow'
  | 'line'
  | 'polyline'
  | 'rect'
  | 'ellipse'
  | 'text'
  | 'select'

export type PdfMarkupPoint = { x: number; y: number }

export interface PdfMarkupDrawStyle {
  /** Толщина линии, доля высоты страницы (0.0005–0.02) */
  strokeRel: number
  /** Размер наконечника стрелки, доля высоты страницы */
  arrowRel: number
  /** Размер шрифта текста, доля высоты страницы */
  fontRel: number
}

export const DEFAULT_MARKUP_STYLE: PdfMarkupDrawStyle = {
  strokeRel: 0.002,
  arrowRel: 0.012,
  fontRel: 0.022,
}

type PdfMarkupRemarkMeta = {
  remarkStatus?: RemarkStatus
  remarkNote?: string
  createdAt?: string
}

type PdfMarkupVectorBase = PdfMarkupRemarkMeta & {
  id: string
  x1: number
  y1: number
  x2: number
  y2: number
  color?: string
  strokeRel?: number
  arrowRel?: number
}

export type PdfMarkupShape =
  | (PdfMarkupVectorBase & { type: 'arrow' })
  | (PdfMarkupVectorBase & { type: 'line' })
  | (PdfMarkupVectorBase & { type: 'rect' })
  | (PdfMarkupVectorBase & { type: 'ellipse' })
  | (PdfMarkupVectorBase & { type: 'polyline'; points: PdfMarkupPoint[] })
  | (PdfMarkupRemarkMeta & {
      id: string
      type: 'text'
      x1: number
      y1: number
      x2: number
      y2: number
      text: string
      fontSize?: number
      color?: string
    })

export interface PdfMarkupDocument {
  documentKey: string
  pages: Record<string, PdfMarkupShape[]>
  updatedAt?: string
}

/** Вложение в PDF: слой замечаний, который можно снять в DeskReview */
export const MARKUP_ATTACHMENT_NAME = 'deskreview-markup.json'
const MARKUP_FORMAT_VERSION = 1

export type PdfMarkupExportMode = 'layered' | 'flattened'

export interface ExportPdfMarkupOptions {
  /** layered — чистый чертёж + JSON во вложении; flattened — пометки запечены в страницу */
  mode?: PdfMarkupExportMode
}

export interface PdfMarkupSidecarFile {
  formatVersion: number
  producer: 'DeskReview'
  markup: PdfMarkupDocument
  style?: PdfMarkupDrawStyle
  savedAt: string
}

const DB_NAME = 'deskreview-pdf-markup'
const DB_VERSION = 1
const STORE = 'documents'

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION)
    req.onerror = () => reject(req.error)
    req.onsuccess = () => resolve(req.result)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE, { keyPath: 'documentKey' })
      }
    }
  })
}

/** Сериализуемый объект без Vue Proxy — для IndexedDB */
export function cloneMarkupDocument(doc: PdfMarkupDocument): PdfMarkupDocument {
  return JSON.parse(JSON.stringify(doc)) as PdfMarkupDocument
}

export function createEmptyMarkupDocument(documentKey: string): PdfMarkupDocument {
  return { documentKey, pages: {}, updatedAt: new Date().toISOString() }
}

export async function loadMarkupDocument(documentKey: string): Promise<PdfMarkupDocument | null> {
  try {
    const db = await openDb()
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, 'readonly')
      const req = tx.objectStore(STORE).get(documentKey)
      req.onsuccess = () => {
        db.close()
        const raw = req.result as PdfMarkupDocument | undefined
        resolve(raw ? cloneMarkupDocument(raw) : null)
      }
      req.onerror = () => {
        db.close()
        reject(req.error)
      }
    })
  } catch {
    return null
  }
}

export async function saveMarkupDocument(doc: PdfMarkupDocument): Promise<void> {
  const payload = cloneMarkupDocument({ ...doc, updatedAt: new Date().toISOString() })
  const db = await openDb()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite')
    tx.objectStore(STORE).put(payload)
    tx.oncomplete = () => {
      db.close()
      resolve()
    }
    tx.onerror = () => {
      db.close()
      reject(tx.error)
    }
  })
}

export function markupDocumentKey(url: string, name?: string): string {
  if (name?.trim()) return `name:${name.trim()}`
  return `url:${url}`
}

export function newShapeId(): string {
  return `s_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

export function pageShapes(doc: PdfMarkupDocument, page: number): PdfMarkupShape[] {
  const key = String(page)
  if (!doc.pages[key]) doc.pages[key] = []
  return doc.pages[key]
}

export function pagesWithMarkup(doc: PdfMarkupDocument): number[] {
  return Object.entries(doc.pages)
    .filter(([, shapes]) => shapes.length > 0)
    .map(([p]) => Number(p))
    .filter((n) => Number.isFinite(n) && n >= 1)
    .sort((a, b) => a - b)
}

export function shapeRemarkStatus(shape: PdfMarkupShape): RemarkStatus {
  return normalizeRemarkStatus(shape.remarkStatus)
}

export function ensureMarkupRemarkMeta(doc: PdfMarkupDocument): void {
  const fallbackTs = doc.updatedAt ?? new Date().toISOString()
  for (const shapes of Object.values(doc.pages)) {
    if (!shapes) continue
    for (const sh of shapes) {
      sh.remarkStatus = normalizeRemarkStatus(sh.remarkStatus)
      if (!sh.createdAt) sh.createdAt = fallbackTs
    }
  }
}

export function defaultRemarkMeta(): PdfMarkupRemarkMeta {
  return { remarkStatus: 'open', remarkNote: '', createdAt: new Date().toISOString() }
}

export function shapeLabel(shape: PdfMarkupShape, index: number): string {
  if (shape.type === 'text') {
    const t = shape.text.trim().slice(0, 24)
    return t ? `Текст: ${t}` : `Текст #${index + 1}`
  }
  const names: Record<string, string> = {
    arrow: 'Стрелка',
    line: 'Линия',
    polyline: 'Полилиния',
    rect: 'Рамка',
    ellipse: 'Овал',
  }
  return `${names[shape.type] ?? shape.type} #${index + 1}`
}

export function isTwoPointShape(
  shape: PdfMarkupShape,
): shape is PdfMarkupShape & { type: 'arrow' | 'line' | 'rect' | 'ellipse' } {
  return shape.type === 'arrow' || shape.type === 'line' || shape.type === 'rect' || shape.type === 'ellipse'
}

export function getShapeHandles(shape: PdfMarkupShape): PdfMarkupPoint[] {
  if (shape.type === 'polyline') return shape.points
  if (shape.type === 'text') return []
  return [
    { x: shape.x1, y: shape.y1 },
    { x: shape.x2, y: shape.y2 },
  ]
}

export function syncPolylineBbox(shape: Extract<PdfMarkupShape, { type: 'polyline' }>): void {
  if (!shape.points.length) return
  let minX = shape.points[0].x
  let minY = shape.points[0].y
  let maxX = minX
  let maxY = minY
  for (const p of shape.points) {
    minX = Math.min(minX, p.x)
    minY = Math.min(minY, p.y)
    maxX = Math.max(maxX, p.x)
    maxY = Math.max(maxY, p.y)
  }
  shape.x1 = minX
  shape.y1 = minY
  shape.x2 = maxX
  shape.y2 = maxY
}

export function distToSegmentNorm(
  px: number,
  py: number,
  x1: number,
  y1: number,
  x2: number,
  y2: number,
): number {
  const dx = x2 - x1
  const dy = y2 - y1
  const len2 = dx * dx + dy * dy
  if (len2 < 1e-12) return Math.hypot(px - x1, py - y1)
  let t = ((px - x1) * dx + (py - y1) * dy) / len2
  t = Math.min(1, Math.max(0, t))
  return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))
}

export function hitTestShapeBody(shape: PdfMarkupShape, x: number, y: number, slop = 0.02): boolean {
  if (shape.type === 'text') {
    const x1 = Math.min(shape.x1, shape.x2)
    const y1 = Math.min(shape.y1, shape.y2)
    const x2 = Math.max(shape.x1, shape.x2)
    const y2 = Math.max(shape.y1, shape.y2)
    return x >= x1 && x <= x2 && y >= y1 && y <= y2
  }
  if (shape.type === 'polyline') {
    const pts = shape.points
    for (let i = 0; i < pts.length - 1; i += 1) {
      if (distToSegmentNorm(x, y, pts[i].x, pts[i].y, pts[i + 1].x, pts[i + 1].y) <= slop) return true
    }
    return false
  }
  if (shape.type === 'arrow' || shape.type === 'line') {
    return distToSegmentNorm(x, y, shape.x1, shape.y1, shape.x2, shape.y2) <= slop
  }
  const x1 = Math.min(shape.x1, shape.x2) - slop
  const y1 = Math.min(shape.y1, shape.y2) - slop
  const x2 = Math.max(shape.x1, shape.x2) + slop
  const y2 = Math.max(shape.y1, shape.y2) + slop
  return x >= x1 && x <= x2 && y >= y1 && y <= y2
}

function parseColor(hex: string | undefined): { r: number; g: number; b: number } {
  const h = (hex ?? '#cc0000').replace('#', '')
  if (h.length === 6) {
    return {
      r: parseInt(h.slice(0, 2), 16) / 255,
      g: parseInt(h.slice(2, 4), 16) / 255,
      b: parseInt(h.slice(4, 6), 16) / 255,
    }
  }
  return { r: 0.8, g: 0, b: 0 }
}

function resolveStyle(shape: PdfMarkupShape, fallback: PdfMarkupDrawStyle): PdfMarkupDrawStyle {
  if (shape.type === 'text') {
    return {
      ...fallback,
      fontRel: shape.fontSize ?? fallback.fontRel,
    }
  }
  return {
    strokeRel: shape.strokeRel ?? fallback.strokeRel,
    arrowRel: shape.arrowRel ?? fallback.arrowRel,
    fontRel: fallback.fontRel,
  }
}

function toPageCoords(
  shape: PdfMarkupShape,
  pageWidth: number,
  pageHeight: number,
): { x1: number; y1: number; x2: number; y2: number } {
  return {
    x1: shape.x1 * pageWidth,
    y1: (1 - shape.y1) * pageHeight,
    x2: shape.x2 * pageWidth,
    y2: (1 - shape.y2) * pageHeight,
  }
}

/** Canvas/SVG overlay: y top-down 0…1 */
export function drawShapeOnCanvas(
  ctx: CanvasRenderingContext2D,
  shape: PdfMarkupShape,
  width: number,
  height: number,
  style: PdfMarkupDrawStyle = DEFAULT_MARKUP_STYLE,
): void {
  const st = resolveStyle(shape, style)
  const x1 = shape.x1 * width
  const y1 = shape.y1 * height
  const x2 = shape.x2 * width
  const y2 = shape.y2 * height
  const color = shape.color ?? '#cc0000'

  if (shape.type === 'text') {
    const x = Math.min(x1, x2)
    const y = Math.min(y1, y2)
    const w = Math.abs(x2 - x1)
    const h = Math.abs(y2 - y1)
    if (w < 4 || h < 4) return
    const fontSize = st.fontRel * height
    ctx.save()
    ctx.beginPath()
    ctx.rect(x, y, w, h)
    ctx.clip()
    ctx.font = `600 ${Math.max(10, fontSize)}px sans-serif`
    ctx.fillStyle = color
    ctx.strokeStyle = '#fff'
    ctx.lineWidth = 1
    const padding = 4
    const lines = shape.text.split('\n')
    let ly = y + padding + fontSize
    for (const line of lines) {
      ctx.strokeText(line, x + padding, ly)
      ctx.fillText(line, x + padding, ly)
      ly += fontSize * 1.25
      if (ly > y + h) break
    }
    ctx.restore()
    return
  }

  ctx.strokeStyle = color
  ctx.fillStyle = color
  ctx.lineWidth = Math.max(1, height * st.strokeRel)

  if (shape.type === 'arrow') {
    drawArrowCanvas(ctx, x1, y1, x2, y2, color, height * st.arrowRel)
  } else if (shape.type === 'line') {
    ctx.beginPath()
    ctx.moveTo(x1, y1)
    ctx.lineTo(x2, y2)
    ctx.stroke()
  } else if (shape.type === 'polyline') {
    const pts = shape.points
    if (pts.length < 2) return
    ctx.beginPath()
    ctx.moveTo(pts[0].x * width, pts[0].y * height)
    for (let i = 1; i < pts.length; i += 1) {
      ctx.lineTo(pts[i].x * width, pts[i].y * height)
    }
    ctx.stroke()
  } else if (shape.type === 'rect') {
    ctx.strokeRect(x1, y1, x2 - x1, y2 - y1)
  } else if (shape.type === 'ellipse') {
    const cx = (x1 + x2) / 2
    const cy = (y1 + y2) / 2
    const rx = Math.abs(x2 - x1) / 2
    const ry = Math.abs(y2 - y1) / 2
    ctx.beginPath()
    ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2)
    ctx.stroke()
  }
}

function drawArrowCanvas(
  ctx: CanvasRenderingContext2D,
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  color: string,
  headLen: number,
): void {
  ctx.beginPath()
  ctx.moveTo(x1, y1)
  ctx.lineTo(x2, y2)
  ctx.stroke()
  const angle = Math.atan2(y2 - y1, x2 - x1)
  ctx.beginPath()
  ctx.moveTo(x2, y2)
  ctx.lineTo(x2 - headLen * Math.cos(angle - Math.PI / 6), y2 - headLen * Math.sin(angle - Math.PI / 6))
  ctx.lineTo(x2 - headLen * Math.cos(angle + Math.PI / 6), y2 - headLen * Math.sin(angle + Math.PI / 6))
  ctx.closePath()
  ctx.fillStyle = color
  ctx.fill()
}

/** Масштаб растра для вставки в PDF (~200–300 dpi относительно пунктов) */
function exportRasterScale(boxWidthPt: number, boxHeightPt: number): number {
  const minDim = Math.max(4, Math.min(boxWidthPt, boxHeightPt))
  return Math.min(12, Math.max(6, Math.ceil(280 / minDim)))
}

function renderTextBlockCanvas(
  shape: Extract<PdfMarkupShape, { type: 'text' }>,
  boxWidthPt: number,
  boxHeightPt: number,
  pageHeightPt: number,
  style: PdfMarkupDrawStyle,
  scale: number,
): HTMLCanvasElement {
  const pixelW = boxWidthPt * scale
  const pixelH = boxHeightPt * scale
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(16, Math.ceil(pixelW))
  canvas.height = Math.max(16, Math.ceil(pixelH))
  const ctx = canvas.getContext('2d')!
  const fontRel = shape.fontSize ?? style.fontRel
  const fontSize = Math.max(14, fontRel * pageHeightPt * scale)
  ctx.font = `600 ${fontSize}px sans-serif`
  ctx.fillStyle = shape.color ?? '#cc0000'
  ctx.strokeStyle = '#ffffff'
  ctx.lineWidth = Math.max(1.5, fontSize * 0.08)
  ctx.lineJoin = 'round'
  const padding = Math.max(6, fontSize * 0.2)
  const lines = shape.text.split('\n')
  let ly = padding + fontSize * 0.85
  for (const line of lines) {
    ctx.strokeText(line, padding, ly)
    ctx.fillText(line, padding, ly)
    ly += fontSize * 1.25
    if (ly > canvas.height) break
  }
  return canvas
}

function renderArrowBlockCanvas(
  shape: Extract<PdfMarkupShape, { type: 'arrow' }>,
  pageWidth: number,
  pageHeight: number,
  style: PdfMarkupDrawStyle,
  scale: number,
): { canvas: HTMLCanvasElement; minX: number; minY: number; width: number; height: number } {
  const st = resolveStyle(shape, style)
  const { x1, y1, x2, y2 } = toPageCoords(shape, pageWidth, pageHeight)
  const head = Math.max(4, pageHeight * st.arrowRel)
  const angle = Math.atan2(y2 - y1, x2 - x1)
  const p1 = {
    x: x2 - head * Math.cos(angle - Math.PI / 6),
    y: y2 - head * Math.sin(angle - Math.PI / 6),
  }
  const p2 = {
    x: x2 - head * Math.cos(angle + Math.PI / 6),
    y: y2 - head * Math.sin(angle + Math.PI / 6),
  }
  const pad = head * 1.2
  const minX = Math.min(x1, x2, p1.x, p2.x) - pad
  const maxX = Math.max(x1, x2, p1.x, p2.x) + pad
  const minY = Math.min(y1, y2, p1.y, p2.y) - pad
  const maxY = Math.max(y1, y2, p1.y, p2.y) + pad
  const bw = Math.max(8, maxX - minX)
  const bh = Math.max(8, maxY - minY)
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(8, Math.ceil(bw * scale))
  canvas.height = Math.max(8, Math.ceil(bh * scale))
  const ctx = canvas.getContext('2d')!
  const toCx = (x: number) => (x - minX) * scale
  const toCy = (y: number) => (maxY - y) * scale
  const color = shape.color ?? '#cc0000'
  ctx.strokeStyle = color
  ctx.fillStyle = color
  ctx.lineWidth = Math.max(1.5, pageHeight * st.strokeRel * scale)
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  drawArrowCanvas(ctx, toCx(x1), toCy(y1), toCx(x2), toCy(y2), color, head * scale)
  return { canvas, minX, minY, width: bw, height: bh }
}

async function drawTextShapeOnPdfPage(
  pdfDoc: PDFDocument,
  page: PDFPage,
  shape: Extract<PdfMarkupShape, { type: 'text' }>,
  pageWidth: number,
  pageHeight: number,
  style: PdfMarkupDrawStyle,
): Promise<void> {
  const { x1, y1, x2, y2 } = toPageCoords(shape, pageWidth, pageHeight)
  const left = Math.min(x1, x2)
  const bottom = Math.min(y1, y2)
  const w = Math.abs(x2 - x1)
  const h = Math.abs(y2 - y1)
  if (w < 2 || h < 2) return
  const scale = exportRasterScale(w, h)
  const textCanvas = renderTextBlockCanvas(shape, w, h, pageHeight, style, scale)
  const png = textCanvas.toDataURL('image/png')
  const img = await pdfDoc.embedPng(png)
  page.drawImage(img, {
    x: left,
    y: bottom,
    width: w,
    height: h,
  })
}

async function drawShapeOnPdfPage(
  pdfDoc: PDFDocument,
  page: PDFPage,
  shape: PdfMarkupShape,
  pageWidth: number,
  pageHeight: number,
  style: PdfMarkupDrawStyle,
): Promise<void> {
  if (shape.type === 'text') {
    await drawTextShapeOnPdfPage(pdfDoc, page, shape, pageWidth, pageHeight, style)
    return
  }

  const st = resolveStyle(shape, style)
  const { r, g, b } = parseColor(shape.color)
  const color = rgb(r, g, b)
  const thickness = Math.max(0.5, pageHeight * st.strokeRel)

  if (shape.type === 'arrow') {
    const { x1, y1, x2, y2 } = toPageCoords(shape, pageWidth, pageHeight)
    const scale = exportRasterScale(
      Math.abs(x2 - x1) || pageWidth * 0.05,
      Math.abs(y2 - y1) || pageHeight * 0.05,
    )
    const { canvas, minX, minY, width, height } = renderArrowBlockCanvas(
      shape,
      pageWidth,
      pageHeight,
      style,
      scale,
    )
    const png = canvas.toDataURL('image/png')
    const img = await pdfDoc.embedPng(png)
    page.drawImage(img, { x: minX, y: minY, width, height })
    return
  }

  if (shape.type === 'line' || shape.type === 'polyline') {
    const pts =
      shape.type === 'line'
        ? [
            { x: shape.x1, y: shape.y1 },
            { x: shape.x2, y: shape.y2 },
          ]
        : shape.points
    for (let i = 0; i < pts.length - 1; i += 1) {
      const a = pts[i]
      const b = pts[i + 1]
      page.drawLine({
        start: { x: a.x * pageWidth, y: (1 - a.y) * pageHeight },
        end: { x: b.x * pageWidth, y: (1 - b.y) * pageHeight },
        thickness,
        color,
      })
    }
    return
  }

  const { x1, y1, x2, y2 } = toPageCoords(shape, pageWidth, pageHeight)

  if (shape.type === 'rect') {
    const left = Math.min(x1, x2)
    const bottom = Math.min(y1, y2)
    page.drawRectangle({
      x: left,
      y: bottom,
      width: Math.abs(x2 - x1),
      height: Math.abs(y2 - y1),
      borderColor: color,
      borderWidth: thickness,
    })
    return
  }

  if (shape.type === 'ellipse') {
    const cx = (x1 + x2) / 2
    const cy = (y1 + y2) / 2
    const rx = Math.abs(x2 - x1) / 2
    const ry = Math.abs(y2 - y1) / 2
    page.drawEllipse({
      x: cx - rx,
      y: cy - ry,
      xScale: rx,
      yScale: ry,
      borderColor: color,
      borderWidth: thickness,
    })
    return
  }
}

export function formatRemarksExportFileName(
  sourceName: string,
  mode: PdfMarkupExportMode = 'layered',
): string {
  const base = sourceName.replace(/\.pdf$/i, '').trim() || 'document'
  const now = new Date()
  const dd = String(now.getDate()).padStart(2, '0')
  const mm = String(now.getMonth() + 1).padStart(2, '0')
  const yyyy = now.getFullYear()
  const hh = String(now.getHours()).padStart(2, '0')
  const min = String(now.getMinutes()).padStart(2, '0')
  const stamp = `${dd}.${mm}.${yyyy}_${hh}-${min}`
  if (mode === 'flattened') {
    return `${base}_замечания_запечённые_${stamp}.pdf`
  }
  return `${base}_с_замечаниями_${stamp}.pdf`
}

export function buildMarkupSidecar(
  markup: PdfMarkupDocument,
  style: PdfMarkupDrawStyle = DEFAULT_MARKUP_STYLE,
): PdfMarkupSidecarFile {
  return {
    formatVersion: MARKUP_FORMAT_VERSION,
    producer: 'DeskReview',
    markup: cloneMarkupDocument({ ...markup, updatedAt: new Date().toISOString() }),
    style,
    savedAt: new Date().toISOString(),
  }
}

export function encodeMarkupSidecar(sidecar: PdfMarkupSidecarFile): Uint8Array {
  return new TextEncoder().encode(JSON.stringify(sidecar))
}

function parseMarkupSidecarJson(text: string): PdfMarkupSidecarFile | null {
  try {
    const raw = JSON.parse(text) as PdfMarkupSidecarFile
    if (raw?.formatVersion !== MARKUP_FORMAT_VERSION || raw.producer !== 'DeskReview') return null
    if (!raw.markup?.pages || typeof raw.markup.pages !== 'object') return null
    return {
      formatVersion: MARKUP_FORMAT_VERSION,
      producer: 'DeskReview',
      markup: cloneMarkupDocument(raw.markup),
      style: raw.style,
      savedAt: raw.savedAt ?? raw.markup.updatedAt ?? '',
    }
  } catch {
    return null
  }
}

export function formatMarkupSidecarFileName(pdfFileName: string): string {
  return pdfFileName.replace(/\.pdf$/i, '.deskreview-markup.json')
}

const EXPORT_PDF_SUFFIX_RE =
  /_(?:с_замечаниями|замечания_запечённые)_\d{2}\.\d{2}\.\d{4}_\d{2}-\d{2}$/i

/** Имена JSON-слоя, которые могут соответствовать этому PDF */
export function markupSidecarCandidateNames(pdfFileName: string): string[] {
  const names = new Set<string>()
  names.add(formatMarkupSidecarFileName(pdfFileName))
  const base = pdfFileName.replace(/\.pdf$/i, '').trim()
  if (!base) return [...names]
  const plain = base.replace(EXPORT_PDF_SUFFIX_RE, '').trim()
  if (plain && plain !== base) {
    names.add(formatMarkupSidecarFileName(`${plain}.pdf`))
  }
  return [...names]
}

export function resolveSidecarUrlForPdf(pdfUrl: string, sidecarFileName: string): string | null {
  try {
    const u = new URL(pdfUrl, window.location.href)
    const parts = u.pathname.split('/')
    parts[parts.length - 1] = encodeURIComponent(sidecarFileName)
    u.pathname = parts.join('/')
    return u.href
  } catch {
    return null
  }
}

/** Найти .deskreview-markup.json рядом с PDF в том же drop / диалоге выбора файлов */
export function findSidecarFileForPdf(
  files: Iterable<File>,
  pdfFileName: string,
): File | undefined {
  const want = new Set(markupSidecarCandidateNames(pdfFileName).map((n) => n.toLowerCase()))
  for (const f of files) {
    if (want.has(f.name.toLowerCase())) return f
  }
  const pdfBase = pdfFileName.replace(/\.pdf$/i, '').toLowerCase()
  const plainBase = pdfBase.replace(EXPORT_PDF_SUFFIX_RE, '')
  for (const f of files) {
    const n = f.name.toLowerCase()
    if (!n.endsWith('.deskreview-markup.json')) continue
    const stem = n.replace(/\.deskreview-markup\.json$/i, '')
    if (stem === pdfBase || stem === plainBase || stem.startsWith(`${plainBase}_`)) return f
  }
  return undefined
}

/** Прочитать слой из отдельного JSON (пара к PDF при экспорте layered) */
export function parseMarkupSidecarBytes(bytes: ArrayBuffer | Uint8Array): PdfMarkupSidecarFile | null {
  const u8 = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes)
  return parseMarkupSidecarJson(new TextDecoder().decode(u8))
}

/** Подгрузить слой с того же URL, что и PDF (только http/https) */
export async function fetchMarkupSidecarForPdf(
  pdfUrl: string,
  pdfFileName?: string,
): Promise<PdfMarkupSidecarFile | null> {
  if (!pdfUrl || pdfUrl.startsWith('blob:') || pdfUrl.startsWith('data:')) return null
  const label = pdfFileName?.trim() || ''
  const names = label ? markupSidecarCandidateNames(label) : [MARKUP_ATTACHMENT_NAME]
  for (const name of names) {
    const sidecarUrl = resolveSidecarUrlForPdf(pdfUrl, name)
    if (!sidecarUrl) continue
    try {
      const res = await fetch(sidecarUrl, { credentials: 'same-origin' })
      if (!res.ok) continue
      const parsed = parseMarkupSidecarBytes(await res.arrayBuffer())
      if (parsed) return parsed
    } catch {
      /* следующий кандидат */
    }
  }
  return null
}

export async function exportPdfWithMarkup(
  pdfBytes: ArrayBuffer,
  markup: PdfMarkupDocument,
  sourceFileName: string,
  style: PdfMarkupDrawStyle = DEFAULT_MARKUP_STYLE,
  options: ExportPdfMarkupOptions = {},
): Promise<{
  bytes: Uint8Array
  fileName: string
  mode: PdfMarkupExportMode
  sidecar?: PdfMarkupSidecarFile
  sidecarFileName?: string
}> {
  const mode = options.mode ?? 'layered'
  const plain = cloneMarkupDocument(markup)
  const fileName = formatRemarksExportFileName(sourceFileName, mode)

  if (mode === 'layered') {
    const sidecar = buildMarkupSidecar(plain, style)
    return {
      bytes: new Uint8Array(pdfBytes),
      fileName,
      mode,
      sidecar,
      sidecarFileName: formatMarkupSidecarFileName(sourceFileName),
    }
  }

  const pdfDoc = await PDFDocument.load(pdfBytes)
  const pages = pdfDoc.getPages()
  for (const [pageStr, shapes] of Object.entries(plain.pages)) {
    if (!shapes?.length) continue
    const pageNum = Number(pageStr)
    if (!Number.isFinite(pageNum) || pageNum < 1 || pageNum > pages.length) continue
    const page = pages[pageNum - 1]
    const { width, height } = page.getSize()
    for (const shape of shapes) {
      await drawShapeOnPdfPage(pdfDoc, page, shape, width, height, style)
    }
  }
  const bytes = await pdfDoc.save()
  return { bytes, fileName, mode }
}

export function downloadBlob(bytes: Uint8Array, fileName: string): void {
  const blob = new Blob([new Uint8Array(bytes)], { type: 'application/pdf' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = fileName
  a.click()
  URL.revokeObjectURL(url)
}
