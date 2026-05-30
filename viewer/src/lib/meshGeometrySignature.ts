import * as THREE from 'three'
import { normalizePartLabel } from './partTree'

/** Допуск сравнения размеров и площади (мм / мм²), относительный. */
const DIM_REL_EPS = 0.002
const AREA_REL_EPS = 0.003

export interface MeshGeometrySignature {
  /** Стабильный ключ для группировки экземпляров одной детали. */
  key: string
  vertexCount: number
  triangleCount: number
  /** Отсортированные размеры габарита в локальной СК меша, мм. */
  dimsMm: [number, number, number]
  surfaceAreaMm2: number
}

function roundMm(v: number, decimals = 1): number {
  const p = 10 ** decimals
  return Math.round(v * p) / p
}

/** Площадь поверхности (инвариант к перемещению/повороту в локальной геометрии). */
export function computeMeshSurfaceAreaMm2(geometry: THREE.BufferGeometry): number {
  const pos = geometry.attributes.position
  if (!pos) return 0
  const index = geometry.index
  const triCount = index ? index.count / 3 : pos.count / 3
  if (triCount < 1) return 0
  const a = new THREE.Vector3()
  const b = new THREE.Vector3()
  const c = new THREE.Vector3()
  const cb = new THREE.Vector3()
  let area = 0
  for (let t = 0; t < triCount; t++) {
    const i0 = index ? index.getX(t * 3) : t * 3
    const i1 = index ? index.getX(t * 3 + 1) : t * 3 + 1
    const i2 = index ? index.getX(t * 3 + 2) : t * 3 + 2
    a.fromBufferAttribute(pos, i0)
    b.fromBufferAttribute(pos, i1)
    c.fromBufferAttribute(pos, i2)
    cb.subVectors(b, a)
    const ac = c.clone().sub(a)
    area += cb.cross(ac).length() * 0.5
  }
  return area
}

function bboxDimsSortedMm(geometry: THREE.BufferGeometry): [number, number, number] {
  if (!geometry.boundingBox) geometry.computeBoundingBox()
  const box = geometry.boundingBox
  if (!box || box.isEmpty()) return [0, 0, 0]
  const sx = Math.max(0, box.max.x - box.min.x)
  const sy = Math.max(0, box.max.y - box.min.y)
  const sz = Math.max(0, box.max.z - box.min.z)
  const sorted = [sx, sy, sz].sort((x, y) => x - y)
  return [roundMm(sorted[0]), roundMm(sorted[1]), roundMm(sorted[2])]
}

/**
 * Отпечаток геометрии меша в локальной СК (одинаковые детали в разных местах сборки → один key).
 */
export function computeMeshGeometrySignature(mesh: THREE.Mesh): MeshGeometrySignature {
  const cached = mesh.userData?.geometrySigKey as string | undefined
  if (cached && mesh.userData?.geometrySigDims) {
    return mesh.userData.geometrySig as MeshGeometrySignature
  }
  const geometry = mesh.geometry
  const vertexCount = geometry.attributes.position?.count ?? 0
  const triangleCount = geometry.index ? geometry.index.count / 3 : Math.floor(vertexCount / 3)
  const dimsMm = bboxDimsSortedMm(geometry)
  const surfaceAreaMm2 = roundMm(computeMeshSurfaceAreaMm2(geometry), 2)
  const key = [
    `v${vertexCount}`,
    `t${triangleCount}`,
    `d${dimsMm[0]}_${dimsMm[1]}_${dimsMm[2]}`,
    `a${surfaceAreaMm2}`,
  ].join('|')
  const sig: MeshGeometrySignature = {
    key,
    vertexCount,
    triangleCount,
    dimsMm,
    surfaceAreaMm2,
  }
  mesh.userData = { ...mesh.userData, geometrySigKey: key, geometrySig: sig }
  return sig
}

export function geometrySignaturesMatch(a: MeshGeometrySignature, b: MeshGeometrySignature): boolean {
  if (a.key === b.key) return true
  if (a.vertexCount !== b.vertexCount || a.triangleCount !== b.triangleCount) return false
  for (let i = 0; i < 3; i++) {
    const da = a.dimsMm[i]
    const db = b.dimsMm[i]
    const ref = Math.max(da, db, 1e-6)
    if (Math.abs(da - db) / ref > DIM_REL_EPS) return false
  }
  const refA = Math.max(a.surfaceAreaMm2, 1e-6)
  return Math.abs(a.surfaceAreaMm2 - b.surfaceAreaMm2) / refA <= AREA_REL_EPS
}

/**
 * Ключ группы экземпляров: partId → имя из модели → геометрия (последний resort).
 * Имя важнее геометрии: фрагменты одной закладной с разными мешами остаются в одной группе.
 */
const GENERIC_NODE_NAME = /^(mesh|node|object|group|scene|solid\d*|body\d*)$/i

function labelKeyFromHint(labelHint: string): string | null {
  const norm = normalizePartLabel(labelHint)
  if (!norm || GENERIC_NODE_NAME.test(norm)) return null
  return `lbl:${norm.toLowerCase()}`
}

export function meshPartGroupKey(mesh: THREE.Mesh, labelHint: string): string {
  const partId = String(mesh.userData?.partId ?? '').trim()
  if (partId) return `pid:${partId}`
  const fromHint = labelKeyFromHint(labelHint)
  if (fromHint) return fromHint
  let p: THREE.Object3D | null = mesh.parent
  while (p) {
    const fromParent = labelKeyFromHint(String(p.name || ''))
    if (fromParent) return fromParent
    p = p.parent
  }
  return `geo:${computeMeshGeometrySignature(mesh).key}`
}

/** @deprecated Используйте meshPartGroupKey */
export function meshGeometryGroupKey(mesh: THREE.Mesh): string {
  const name = String(mesh.userData?.partName ?? mesh.name ?? '')
  return meshPartGroupKey(mesh, name)
}

export interface GeometryGroupLabelVote {
  labels: string[]
}

/** Подпись строки дерева для группы экземпляров. */
export function pickGeometryGroupLabel(votes: GeometryGroupLabelVote): string {
  const counts = new Map<string, number>()
  for (const raw of votes.labels) {
    const n = String(raw || '').trim()
    if (!n) continue
    counts.set(n, (counts.get(n) ?? 0) + 1)
  }
  if (counts.size === 0) return 'Деталь'
  let best = ''
  let max = 0
  let total = 0
  counts.forEach((c, l) => {
    total += c
    if (c > max) {
      max = c
      best = l
    }
  })
  return best
}
