import { OPS } from 'pdfjs-dist'

export type PdfSegmentLine = {
  type: 'line'
  x1: number
  y1: number
  x2: number
  y2: number
}

export type PdfSegmentCurve = {
  type: 'curve'
  x0: number
  y0: number
  x1: number
  y1: number
  x2: number
  y2: number
  x3: number
  y3: number
}

export type PdfSegmentCircle = {
  type: 'circle'
  cx: number
  cy: number
  r: number
}

export type PdfSegment = PdfSegmentLine | PdfSegmentCurve | PdfSegmentCircle

export interface PDFOperatorList {
  fnArray: number[]
  argsArray: unknown[][]
}

/**
 * Parse PDF page operator list into line/curve/circle segments (PDF coordinates, origin bottom-left).
 */
export function parsePdfOperatorList(opList: PDFOperatorList): PdfSegment[] {
  const segments: PdfSegment[] = []
  let x = 0,
    y = 0
  let pathStartX = 0,
    pathStartY = 0
  const { fnArray, argsArray } = opList

  for (let i = 0; i < fnArray.length; i++) {
    const fn = fnArray[i]
    const args = argsArray[i] as number[]

    switch (fn) {
      case OPS.moveTo:
        if (args && args.length >= 2) {
          x = args[0]
          y = args[1]
          pathStartX = x
          pathStartY = y
        }
        break
      case OPS.lineTo:
        if (args && args.length >= 2) {
          segments.push({ type: 'line', x1: x, y1: y, x2: args[0], y2: args[1] })
          x = args[0]
          y = args[1]
        }
        break
      case OPS.curveTo:
        if (args && args.length >= 6) {
          segments.push({
            type: 'curve',
            x0: x,
            y0: y,
            x1: args[0],
            y1: args[1],
            x2: args[2],
            y2: args[3],
            x3: args[4],
            y3: args[5],
          })
          x = args[4]
          y = args[5]
        }
        break
      case OPS.curveTo2:
        if (args && args.length >= 4) {
          const x2 = args[2]
          const y2 = args[3]
          segments.push({
            type: 'curve',
            x0: x,
            y0: y,
            x1: x,
            y1: y,
            x2: x2,
            y2: y2,
            x3: x2,
            y3: y2,
          })
          x = x2
          y = y2
        }
        break
      case OPS.curveTo3:
        if (args && args.length >= 4) {
          const x3 = args[2]
          const y3 = args[3]
          segments.push({
            type: 'curve',
            x0: x,
            y0: y,
            x1: args[0],
            y1: args[1],
            x2: x3,
            y2: y3,
            x3,
            y3,
          })
          x = x3
          y = y3
        }
        break
      case OPS.closePath:
        if (Math.abs(x - pathStartX) > 1e-6 || Math.abs(y - pathStartY) > 1e-6) {
          segments.push({
            type: 'line',
            x1: x,
            y1: y,
            x2: pathStartX,
            y2: pathStartY,
          })
          x = pathStartX
          y = pathStartY
        }
        break
      case OPS.rectangle:
        if (args && args.length >= 4) {
          const [rx, ry, w, h] = args
          segments.push({ type: 'line', x1: rx, y1: ry, x2: rx + w, y2: ry })
          segments.push({ type: 'line', x1: rx + w, y1: ry, x2: rx + w, y2: ry + h })
          segments.push({ type: 'line', x1: rx + w, y1: ry + h, x2: rx, y2: ry + h })
          segments.push({ type: 'line', x1: rx, y1: ry + h, x2: rx, y2: ry })
          x = rx
          y = ry
        }
        break
      default:
        break
    }
  }

  const withCircles = tryDetectCircles(segments)
  return withCircles
}

const CIRCLE_ARC_TOL = 0.02
const MIN_CIRCLE_R = 0.5
const MAX_CIRCLE_R = 1e4

function tryDetectCircles(segments: PdfSegment[]): PdfSegment[] {
  const result: PdfSegment[] = []
  let i = 0
  while (i < segments.length) {
    const seg = segments[i]
    if (seg.type !== 'curve') {
      result.push(seg)
      i++
      continue
    }
    const run = collectConsecutiveCurves(segments, i)
    if (run.length >= 2 && run.length <= 8) {
      const c = tryCurvesToCircle(run)
      if (c) {
        result.push(c)
        i += run.length
        continue
      }
    }
    result.push(seg)
    i++
  }
  return result
}

function collectConsecutiveCurves(segments: PdfSegment[], start: number): PdfSegmentCurve[] {
  const run: PdfSegmentCurve[] = []
  for (let j = start; j < segments.length && segments[j].type === 'curve'; j++) {
    run.push(segments[j] as PdfSegmentCurve)
  }
  return run
}

function tryCurvesToCircle(curves: PdfSegmentCurve[]): PdfSegmentCircle | null {
  let cx = 0,
    cy = 0,
    n = 0
  for (const c of curves) {
    cx += c.x0 + c.x3
    cy += c.y0 + c.y3
    n += 2
  }
  cx /= n
  cy /= n
  let rSum = 0
  let rCount = 0
  for (const c of curves) {
    const r0 = Math.hypot(c.x0 - cx, c.y0 - cy)
    const r3 = Math.hypot(c.x3 - cx, c.y3 - cy)
    rSum += r0 + r3
    rCount += 2
  }
  const r = rSum / rCount
  if (r < MIN_CIRCLE_R || r > MAX_CIRCLE_R) return null
  for (const c of curves) {
    const r0 = Math.hypot(c.x0 - cx, c.y0 - cy)
    const r3 = Math.hypot(c.x3 - cx, c.y3 - cy)
    if (Math.abs(r0 - r) / r > CIRCLE_ARC_TOL || Math.abs(r3 - r) / r > CIRCLE_ARC_TOL) return null
  }
  return { type: 'circle', cx, cy, r }
}

function nearestPointOnSegment(
  px: number,
  py: number,
  x1: number,
  y1: number,
  x2: number,
  y2: number
): { x: number; y: number; distSq: number } {
  const dx = x2 - x1
  const dy = y2 - y1
  const lenSq = dx * dx + dy * dy
  if (lenSq < 1e-12) return { x: x1, y: y1, distSq: (px - x1) ** 2 + (py - y1) ** 2 }
  let t = ((px - x1) * dx + (py - y1) * dy) / lenSq
  t = Math.max(0, Math.min(1, t))
  const qx = x1 + t * dx
  const qy = y1 + t * dy
  return { x: qx, y: qy, distSq: (px - qx) ** 2 + (py - qy) ** 2 }
}

function sampleCurve(seg: PdfSegmentCurve, n: number): { x: number; y: number }[] {
  const out: { x: number; y: number }[] = []
  for (let i = 0; i <= n; i++) {
    const t = i / n
    const mt = 1 - t
    const x =
      mt * mt * mt * seg.x0 +
      3 * mt * mt * t * seg.x1 +
      3 * mt * t * t * seg.x2 +
      t * t * t * seg.x3
    const y =
      mt * mt * mt * seg.y0 +
      3 * mt * mt * t * seg.y1 +
      3 * mt * t * t * seg.y2 +
      t * t * t * seg.y3
    out.push({ x, y })
  }
  return out
}

function nearestOnCurve(px: number, py: number, seg: PdfSegmentCurve): { x: number; y: number; distSq: number } {
  const samples = sampleCurve(seg, 24)
  let best = { x: seg.x0, y: seg.y0, distSq: (px - seg.x0) ** 2 + (py - seg.y0) ** 2 }
  for (const p of samples) {
    const d = (px - p.x) ** 2 + (py - p.y) ** 2
    if (d < best.distSq) best = { x: p.x, y: p.y, distSq: d }
  }
  return best
}

export function hitTestSegment(
  pdfX: number,
  pdfY: number,
  segment: PdfSegment,
  tolerancePdf: number
): { hit: boolean; snapX: number; snapY: number; distSq: number } {
  const tolSq = tolerancePdf * tolerancePdf
  if (segment.type === 'line') {
    const r = nearestPointOnSegment(pdfX, pdfY, segment.x1, segment.y1, segment.x2, segment.y2)
    return { hit: r.distSq <= tolSq, snapX: r.x, snapY: r.y, distSq: r.distSq }
  }
  if (segment.type === 'curve') {
    const r = nearestOnCurve(pdfX, pdfY, segment)
    return { hit: r.distSq <= tolSq, snapX: r.x, snapY: r.y, distSq: r.distSq }
  }
  if (segment.type === 'circle') {
    const d = Math.hypot(pdfX - segment.cx, pdfY - segment.cy)
    const distToCircle = Math.abs(d - segment.r)
    const distToCenter = Math.abs(d)
    const distSq = Math.min(distToCircle * distToCircle, distToCenter * distToCenter)
    const hit = distToCircle <= tolerancePdf || (d <= segment.r && distToCenter <= tolerancePdf * 2)
    let snapX: number, snapY: number
    if (d < segment.r * 0.5) {
      snapX = segment.cx
      snapY = segment.cy
    } else {
      const angle = Math.atan2(pdfY - segment.cy, pdfX - segment.cx)
      snapX = segment.cx + segment.r * Math.cos(angle)
      snapY = segment.cy + segment.r * Math.sin(angle)
    }
    return { hit, snapX, snapY, distSq: distToCircle * distToCircle }
  }
  return { hit: false, snapX: pdfX, snapY: pdfY, distSq: Infinity }
}

export function findClosestSegment(
  pdfX: number,
  pdfY: number,
  segments: PdfSegment[],
  tolerancePdf: number
): { segment: PdfSegment; index: number; snapX: number; snapY: number } | null {
  let best: { segment: PdfSegment; index: number; snapX: number; snapY: number; distSq: number } | null = null
  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i]
    const r = hitTestSegment(pdfX, pdfY, seg, tolerancePdf)
    if (r.hit && (best === null || r.distSq < best.distSq)) {
      best = { segment: seg, index: i, snapX: r.snapX, snapY: r.snapY, distSq: r.distSq }
    }
  }
  if (!best) return null
  return { segment: best.segment, index: best.index, snapX: best.snapX, snapY: best.snapY }
}
