import { type RemarkStatus, normalizeRemarkStatus } from './remarkStatus'
import {
  type Model3dAnchor3d,
  type Model3dScreenImage,
  type Model3dScreenLayer,
  ensureScreenLayer,
} from './model3dScreenLayer'

export type { Model3dAnchor3d, Model3dScreenImage, Model3dScreenLayer } from './model3dScreenLayer'

export const MODEL3D_REMARKS_FORMAT_VERSION = 1

export type Model3dCommentStatus = RemarkStatus

export type Model3dViewState = {
  camera: {
    position: [number, number, number]
    target: [number, number, number]
    up: [number, number, number]
    fov: number
  }
  hiddenModelIds: string[]
}

export type Model3dComment = {
  id: string
  parentId: string | null
  title: string
  description: string
  status: Model3dCommentStatus
  createdAt: string
  viewState: Model3dViewState
  anchor3d?: Model3dAnchor3d | null
  screenLayer?: Model3dScreenLayer
  images?: Model3dScreenImage[]
}

export type Model3dRemarksDocument = {
  modelKey: string
  modelFileName: string
  comments: Model3dComment[]
  updatedAt?: string
}

export type Model3dRemarksFile = {
  formatVersion: number
  producer: 'DeskReview'
  remarks: Model3dRemarksDocument
  savedAt: string
}

const DB_NAME = 'deskreview-3d-remarks'
const DB_VERSION = 1
const STORE = 'documents'

export function modelRemarksDocumentKey(modelFileName: string): string {
  return `name:${modelFileName.trim()}`
}

export function formatModel3dRemarksFileName(modelFileName: string): string {
  const base = modelFileName.replace(/\.(glb|gltf|stl|step|stp|iges|igs)$/i, '').trim() || 'model'
  const now = new Date()
  const dd = String(now.getDate()).padStart(2, '0')
  const mm = String(now.getMonth() + 1).padStart(2, '0')
  const yyyy = now.getFullYear()
  const hh = String(now.getHours()).padStart(2, '0')
  const min = String(now.getMinutes()).padStart(2, '0')
  return `${base}_замечания_3d_${dd}.${mm}.${yyyy}_${hh}-${min}.json`
}

export function newModel3dCommentId(): string {
  return `c_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

export function createEmptyModel3dRemarks(modelFileName: string): Model3dRemarksDocument {
  const name = modelFileName.trim() || 'model.glb'
  return {
    modelKey: modelRemarksDocumentKey(name),
    modelFileName: name,
    comments: [],
    updatedAt: new Date().toISOString(),
  }
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION)
    req.onerror = () => reject(req.error)
    req.onsuccess = () => resolve(req.result)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE, { keyPath: 'modelKey' })
      }
    }
  })
}

export function cloneModel3dRemarks(doc: Model3dRemarksDocument): Model3dRemarksDocument {
  return JSON.parse(JSON.stringify(doc)) as Model3dRemarksDocument
}

function normalizeAnchor3d(raw: Model3dAnchor3d | null | undefined): Model3dAnchor3d | undefined {
  if (!raw?.modelId) return undefined
  const pl = raw.pointLocal
  const nl = raw.normalLocal
  if (!pl || !nl) return undefined
  return {
    modelId: String(raw.modelId),
    pointLocal: { x: Number(pl.x) || 0, y: Number(pl.y) || 0, z: Number(pl.z) || 0 },
    normalLocal: { x: Number(nl.x) || 0, y: Number(nl.y) || 1, z: Number(nl.z) || 0 },
  }
}

function normalizeScreenImages(raw: Model3dScreenImage[] | undefined): Model3dScreenImage[] {
  if (!Array.isArray(raw)) return []
  return raw
    .filter((img) => img && (img.dataUrl || img.file))
    .map((img) => ({
      id: img.id || `img_${Math.random().toString(36).slice(2, 8)}`,
      file: img.file,
      dataUrl: img.dataUrl,
      x: Math.max(0, Math.min(1, Number(img.x) || 0)),
      y: Math.max(0, Math.min(1, Number(img.y) || 0)),
      w: Math.max(0.02, Math.min(1, Number(img.w) || 0.2)),
      h: Math.max(0.02, Math.min(1, Number(img.h) || 0.2)),
    }))
}

export function normalizeModel3dComment(raw: Model3dComment): Model3dComment {
  return {
    ...raw,
    status: normalizeRemarkStatus(raw.status),
    description: typeof raw.description === 'string' ? raw.description : '',
    title: typeof raw.title === 'string' && raw.title.trim() ? raw.title.trim() : 'Замечание',
    anchor3d: normalizeAnchor3d(raw.anchor3d ?? undefined) ?? undefined,
    screenLayer: ensureScreenLayer(raw.screenLayer),
    images: normalizeScreenImages(raw.images),
  }
}

export function normalizeModel3dRemarksDocument(doc: Model3dRemarksDocument): Model3dRemarksDocument {
  return {
    ...doc,
    comments: (doc.comments ?? []).map(normalizeModel3dComment),
  }
}

export async function loadModel3dRemarks(modelKey: string): Promise<Model3dRemarksDocument | null> {
  try {
    const db = await openDb()
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE, 'readonly')
      const req = tx.objectStore(STORE).get(modelKey)
      req.onsuccess = () => {
        db.close()
        const raw = req.result as Model3dRemarksDocument | undefined
        resolve(raw ? cloneModel3dRemarks(raw) : null)
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

export async function saveModel3dRemarks(doc: Model3dRemarksDocument): Promise<void> {
  const payload = cloneModel3dRemarks({ ...doc, updatedAt: new Date().toISOString() })
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

export function buildModel3dRemarksFile(doc: Model3dRemarksDocument): Model3dRemarksFile {
  return {
    formatVersion: MODEL3D_REMARKS_FORMAT_VERSION,
    producer: 'DeskReview',
    remarks: cloneModel3dRemarks(doc),
    savedAt: new Date().toISOString(),
  }
}

export function encodeModel3dRemarksFile(file: Model3dRemarksFile): Uint8Array {
  return new TextEncoder().encode(JSON.stringify(file, null, 2))
}

export function parseModel3dRemarksBytes(bytes: ArrayBuffer | Uint8Array): Model3dRemarksFile | null {
  try {
    const u8 = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes)
    const raw = JSON.parse(new TextDecoder().decode(u8)) as Model3dRemarksFile
    if (raw?.formatVersion !== MODEL3D_REMARKS_FORMAT_VERSION || raw.producer !== 'DeskReview') return null
    if (!raw.remarks?.comments || !Array.isArray(raw.remarks.comments)) return null
    return {
      formatVersion: MODEL3D_REMARKS_FORMAT_VERSION,
      producer: 'DeskReview',
      remarks: normalizeModel3dRemarksDocument(cloneModel3dRemarks(raw.remarks)),
      savedAt: raw.savedAt ?? raw.remarks.updatedAt ?? '',
    }
  } catch {
    return null
  }
}

export function downloadJsonBlob(bytes: Uint8Array, fileName: string): void {
  const blob = new Blob([new Uint8Array(bytes)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = fileName
  a.click()
  URL.revokeObjectURL(url)
}
