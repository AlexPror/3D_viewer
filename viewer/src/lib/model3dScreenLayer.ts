export type ScreenLayerPoint = { x: number; y: number }

export type ScreenLayerTool =
  | 'select'
  | 'arrow'
  | 'line'
  | 'polyline'
  | 'rect'
  | 'ellipse'
  | 'text'

export type ScreenLayerVectorShape = {
  id: string
  type: 'arrow' | 'line' | 'rect' | 'ellipse'
  x1: number
  y1: number
  x2: number
  y2: number
  color?: string
  strokeRel?: number
  arrowRel?: number
}

export type ScreenLayerPolylineShape = {
  id: string
  type: 'polyline'
  points: ScreenLayerPoint[]
  x1: number
  y1: number
  x2: number
  y2: number
  color?: string
  strokeRel?: number
}

export type ScreenLayerTextShape = {
  id: string
  type: 'text'
  x1: number
  y1: number
  x2: number
  y2: number
  text: string
  fontRel?: number
  color?: string
}

export type ScreenLayerShape = ScreenLayerVectorShape | ScreenLayerPolylineShape | ScreenLayerTextShape

export type Model3dScreenImage = {
  id: string
  file?: string
  dataUrl?: string
  x: number
  y: number
  w: number
  h: number
}

export type Model3dScreenLayer = {
  shapes: ScreenLayerShape[]
}

export type Model3dAnchor3d = {
  modelId: string
  pointLocal: { x: number; y: number; z: number }
  normalLocal: { x: number; y: number; z: number }
}

export const DEFAULT_SCREEN_LAYER_STYLE = {
  /** Доля высоты viewport (viewBox 0…1), без non-scaling-stroke ≈ несколько px на экране */
  strokeRel: 0.004,
  arrowRel: 0.018,
  fontRel: 0.024,
}

export const SCREEN_LAYER_HANDLE_HIT_R = 0.014

export function newScreenLayerShapeId(): string {
  return `s_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

export function newScreenLayerImageId(): string {
  return `img_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

export function ensureScreenLayer(layer?: Model3dScreenLayer | null): Model3dScreenLayer {
  return { shapes: Array.isArray(layer?.shapes) ? [...layer!.shapes] : [] }
}

export function clamp01(v: number): number {
  return Math.max(0, Math.min(1, v))
}

export function isTwoPointScreenShape(
  shape: ScreenLayerShape,
): shape is ScreenLayerVectorShape {
  return shape.type === 'arrow' || shape.type === 'line' || shape.type === 'rect' || shape.type === 'ellipse'
}

export function isDragDrawScreenTool(t: ScreenLayerTool): boolean {
  return t === 'arrow' || t === 'line' || t === 'rect' || t === 'ellipse'
}

export function getScreenShapeHandles(shape: ScreenLayerShape): ScreenLayerPoint[] {
  if (shape.type === 'polyline') return shape.points
  if (shape.type === 'text') return []
  return [
    { x: shape.x1, y: shape.y1 },
    { x: shape.x2, y: shape.y2 },
  ]
}

export function syncScreenPolylineBbox(shape: ScreenLayerPolylineShape): void {
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

export function hitTestScreenShapeBody(shape: ScreenLayerShape, x: number, y: number, slop = 0.02): boolean {
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

export function hitTestScreenShapes(shapes: ScreenLayerShape[], x: number, y: number): string | null {
  for (let i = shapes.length - 1; i >= 0; i--) {
    if (hitTestScreenShapeBody(shapes[i], x, y)) return shapes[i].id
  }
  return null
}

export function hitTestScreenShapeHandleIndex(shape: ScreenLayerShape, x: number, y: number): number | null {
  const handles = getScreenShapeHandles(shape)
  for (let i = 0; i < handles.length; i += 1) {
    const h = handles[i]
    if (Math.hypot(x - h.x, y - h.y) <= SCREEN_LAYER_HANDLE_HIT_R) return i
  }
  return null
}

export function hitTestScreenImage(img: Model3dScreenImage, x: number, y: number, slop = 0.01): boolean {
  return x >= img.x - slop && x <= img.x + img.w + slop && y >= img.y - slop && y <= img.y + img.h + slop
}

export function svgNormStrokeWidth(shape?: ScreenLayerShape, strokeRel = DEFAULT_SCREEN_LAYER_STYLE.strokeRel): number {
  if (shape?.type === 'text') return strokeRel
  const rel =
    shape && 'strokeRel' in shape && shape.strokeRel != null ? shape.strokeRel : strokeRel
  return Math.max(0.002, rel)
}

export function svgNormArrowHeadRel(shape?: ScreenLayerShape, arrowRel = DEFAULT_SCREEN_LAYER_STYLE.arrowRel): number {
  const rel =
    shape && isTwoPointScreenShape(shape) && shape.arrowRel != null ? shape.arrowRel : arrowRel
  return Math.max(0.006, rel)
}

export function arrowHeadPointsNorm(
  x1: number,
  y1: number,
  x2: number,
  y2: number,
  headRel: number,
): string {
  const angle = Math.atan2(y2 - y1, x2 - x1)
  const head = headRel
  const p1x = x2 - head * Math.cos(angle - Math.PI / 6)
  const p1y = y2 - head * Math.sin(angle - Math.PI / 6)
  const p2x = x2 - head * Math.cos(angle + Math.PI / 6)
  const p2y = y2 - head * Math.sin(angle + Math.PI / 6)
  return `${x2},${y2} ${p1x},${p1y} ${p2x},${p2y}`
}

export function polylineSvgPoints(points: ScreenLayerPoint[]): string {
  return points.map((p) => `${p.x},${p.y}`).join(' ')
}

export function viewDirectionAngleDeg(
  aPos: [number, number, number],
  aTarget: [number, number, number],
  bPos: [number, number, number],
  bTarget: [number, number, number],
): number {
  const ax = aPos[0] - aTarget[0]
  const ay = aPos[1] - aTarget[1]
  const az = aPos[2] - aTarget[2]
  const bx = bPos[0] - bTarget[0]
  const by = bPos[1] - bTarget[1]
  const bz = bPos[2] - bTarget[2]
  const al = Math.hypot(ax, ay, az) || 1
  const bl = Math.hypot(bx, by, bz) || 1
  const dot = (ax * bx + ay * by + az * bz) / (al * bl)
  return (Math.acos(Math.max(-1, Math.min(1, dot))) * 180) / Math.PI
}

export const SCREEN_LAYER_VIEW_ANGLE_THRESHOLD_DEG = 9
