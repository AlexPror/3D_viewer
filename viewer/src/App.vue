<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, shallowRef, watch } from 'vue'
import * as Y from 'yjs'
import { Awareness, encodeAwarenessUpdate, applyAwarenessUpdate } from 'y-protocols/awareness'
import { logger } from './lib/logger'
import { findSidecarFileForPdf } from './lib/pdfMarkup'
import { jsPDF } from 'jspdf'
import autoTable from 'jspdf-autotable'
import type { ViewMode, MeasureSnapMode, MeasureType } from './components/ViewerToolbar.vue'
import Viewer3D from './components/Viewer3D.vue'
import ViewerToolbar from './components/ViewerToolbar.vue'
import PdfViewer from './components/PdfViewer.vue'
import LogPanel from './components/LogPanel.vue'
import ScreenshotEditorModal from './components/ScreenshotEditorModal.vue'
import ReportScreenshotsModal from './components/ReportScreenshotsModal.vue'
import ScreenshotFlyToBasket from './components/ScreenshotFlyToBasket.vue'
import CollabRoleIcon from './components/CollabRoleIcon.vue'
import CollaborativeEditor from './components/CollaborativeEditor.vue'
import YandexDiskTree from './components/YandexDiskTree.vue'
import type { DiskNode } from './components/YandexDiskTree.vue'

const viewMode = ref<ViewMode>('split')
const viewerRef = ref<InstanceType<typeof Viewer3D> | null>(null)
const assemblyProjectFileInputRef = ref<HTMLInputElement | null>(null)
const pdfViewerRef = ref<InstanceType<typeof PdfViewer> | null>(null)
const pdfFile = ref<{
  url: string
  name: string
  markupSidecarBytes?: ArrayBuffer | null
} | null>(null)
interface ReportScreenshotItem {
  id: string
  type: '2d' | '3d'
  dataUrl: string
  /** для 2d: имя файла PDF */
  pdfFileName?: string
  /** для 2d: номер страницы скриншота */
  pageNumber?: number
  /** для 2d: шифр альбома на момент снимка (поле «Название проекта» или с 1-го листа) */
  albumCode?: string
  /** для 2d: номер модуля на момент снимка */
  moduleNumber?: string
}
const screenshotImageUrl = ref<string | null>(null)
const screenshotSuggestedFileName = ref<string | null>(null)
const showScreenshotModal = ref(false)
const screenshotSourceType = ref<'2d' | '3d'>('2d')
const editingScreenshotId = ref<string | null>(null)
const reportScreenshots = ref<ReportScreenshotItem[]>([])
const showReportGallery = ref(false)
const reportBasketPulse = ref(false)
const toolbarRef = ref<InstanceType<typeof ViewerToolbar> | null>(null)
type ScreenshotFlyAnim = {
  src: string
  fromX: number
  fromY: number
  toX: number
  toY: number
}
const screenshotFlyAnim = ref<ScreenshotFlyAnim | null>(null)
const reportProjectName = ref('')
const reportModuleNumber = ref('')
const reportSheetNumber = ref('')
const reportAuthor = ref('')
/** Номер страницы PDF в момент создания 2D-скриншота (берём из вьюера при открытии захвата) */
const savedPdfPageForNextScreenshot = ref(1)

interface FirstSheetData {
  organization?: string
  sroCertificate?: string
  associationOrObject?: string
  address?: string
  documentType?: string
  section?: string
  projectCode?: string
  director?: string
  cityYear?: string
  sheetNumber?: string
}
const firstSheetData = ref<FirstSheetData>({})

function parseFirstSheetText(text: string): FirstSheetData {
  const t = text.replace(/\s+/g, ' ').trim()
  const out: FirstSheetData = {}
  const projectCodeMatch = t.match(/\d{2,4}-\d{2,4}-КП-Р-[^\s]+/)
  if (projectCodeMatch) {
    out.projectCode = projectCodeMatch[0].trim()
  }
  const orgMatch = t.match(/ООО\s*"[^"]+"/)
  if (orgMatch) out.organization = orgMatch[0].trim()
  const sroMatch = t.match(/Свидетельство\s+СРО-П-\d+-\d+/)
  if (sroMatch) out.sroCertificate = sroMatch[0].trim()
  else {
    const sroShort = t.match(/СРО-П-\d+-\d+/)
    if (sroShort) out.sroCertificate = sroShort[0].trim()
  }
  const addrMatch = t.match(/по адресу:\s*[^.]+?(?=РАБОЧАЯ|$)/)
  if (addrMatch) out.address = addrMatch[0].trim().replace(/\s+/g, ' ')
  const docTypeMatch = t.match(/РАБОЧАЯ\s+ДОКУМЕНТАЦИЯ/)
  if (docTypeMatch) out.documentType = docTypeMatch[0].trim()
  const directorMatch = t.match(/Генеральный директор[^.]+?(?=г\.|$)/)
  if (directorMatch) out.director = directorMatch[0].trim().replace(/\s+/g, ' ')
  const cityYearMatch = t.match(/г\.\s*[^.]*?\d{4}\s*г/)
  if (cityYearMatch) out.cityYear = cityYearMatch[0].trim().replace(/\s+/g, ' ')
  const sheetMatch = t.match(/(?:листа?|страниц[аы]?)\s*[:\s]*(\d+)/i)
  if (sheetMatch) out.sheetNumber = sheetMatch[1].trim()
  const lines = text.split(/\n/).map((s) => s.trim()).filter(Boolean)
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    if (/Устройство\s+навесной|Раздел\s+/.test(line) && !out.section) {
      out.section = line.replace(/\s+/g, ' ')
      break
    }
    if (out.documentType && i > 0 && !out.section && !/^\d{2,4}-\d{2,4}-КП/.test(line) && line.length > 5) {
      out.section = line.replace(/\s+/g, ' ')
      break
    }
  }
  if (!out.section && out.documentType) {
    const afterDoc = text.split(/РАБОЧАЯ\s+ДОКУМЕНТАЦИЯ/i)[1]
    if (afterDoc) {
      const firstLine = afterDoc.split(/\n/).map((s) => s.trim()).find((s) => s.length > 3 && !/^\d{2,4}-\d{2,4}-КП/.test(s))
      if (firstLine) out.section = firstLine.replace(/\s+/g, ' ').slice(0, 120)
    }
  }
  const beforeAddress = text.split(/по адресу:/i)[0]
  if (beforeAddress && !out.associationOrObject) {
    const prevLine = beforeAddress.split(/\n/).filter((s) => s.trim().length > 10).pop()
    if (prevLine) out.associationOrObject = prevLine.trim().replace(/\s+/g, ' ').slice(0, 150)
  }
  return out
}

async function refreshFirstSheetData() {
  const text = await pdfViewerRef.value?.getPageTextContent?.(1)
  if (!text) {
    firstSheetData.value = {}
    return
  }
  const parsed = parseFirstSheetText(text)
  firstSheetData.value = parsed
  if (parsed.projectCode) reportProjectName.value = parsed.projectCode
  if (parsed.sheetNumber) reportSheetNumber.value = parsed.sheetNumber
  logger.info('App', 'Данные первого листа обновлены')
  logger.info('App', `Первый лист (сырой текст, до 500 символов): ${JSON.stringify(text.slice(0, 500))}`)
  logger.info('App', `Первый лист (распарсено): ${JSON.stringify(parsed)}`)
}

function nextScreenshotId() {
  return `scr_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`
}
const sectionMode = ref(false)
const sectionActive = ref(false)
const sectionOffset = ref(0)
const measureMode = ref(false)
const measureSnapMode = ref<MeasureSnapMode>('intersection')
const measureType = ref<MeasureType>('distance')
const isDraggingFile = ref(false)
const collabApiBase = ref((import.meta.env.VITE_COLLAB_API_BASE as string | undefined) || 'http://localhost:8000')

function collabFetchErrorMessage(e: unknown): string {
  const msg = e instanceof Error ? e.message : String(e)
  if (e instanceof TypeError || /failed to fetch|network|connection refused/i.test(msg)) {
    return `Сервер чата не запущен (${collabApiBase.value}). В папке server: python -m uvicorn main:app --reload --port 8000`
  }
  return msg || 'ошибка сети'
}
const collabToken = ref(localStorage.getItem('collabToken') || '')
const collabUser = ref<{ id: string; email: string; displayName: string } | null>(null)
const collabEmail = ref('')
const collabPassword = ref('')
const collabDisplayName = ref('')
const collabProjects = ref<any[]>([])
const collabProjectId = ref('')
const collabChannels = ref<any[]>([])
const collabChannelId = ref('')
const collabMessages = ref<any[]>([])
const collabMessageText = ref('')
const collabNewProjectName = ref('')
const collabNewChannelName = ref('')
const collabInviteEmail = ref('')
/** Участники выбранного проекта (GET /api/projects/.../members) */
const collabMembers = ref<
  Array<{ id: string; email: string; displayName: string; role: string; joinedAt?: string }>
>([])
const collabMembersLoading = ref(false)

type CollabMemberRole = 'gip' | 'chief_designer' | 'designer' | 'installer' | 'assembler' | 'client'

const COLLAB_ROLE_LABELS: Record<CollabMemberRole, string> = {
  gip: 'ГИП (главный инженер проекта)',
  chief_designer: 'Главный конструктор',
  designer: 'Конструктор',
  installer: 'Монтажник',
  assembler: 'Сборщик',
  client: 'Клиент',
}

/** Порядок в легенде и единые цвета аватаров / подсветки */
const COLLAB_ROLE_ORDER: CollabMemberRole[] = [
  'gip',
  'chief_designer',
  'designer',
  'installer',
  'assembler',
  'client',
]

const COLLAB_ROLE_SHORT: Record<CollabMemberRole, string> = {
  gip: 'ГИП',
  chief_designer: 'Гл. конструктор',
  designer: 'Конструктор',
  installer: 'Монтажник',
  assembler: 'Сборщик',
  client: 'Клиент',
}

const COLLAB_ROLE_AVATAR: Record<CollabMemberRole, { bg: string; ring: string }> = {
  gip: {
    bg: 'linear-gradient(145deg, hsl(268 58% 44%) 0%, hsl(285 48% 34%) 100%)',
    ring: 'hsl(268 85% 68%)',
  },
  chief_designer: {
    bg: 'linear-gradient(145deg, hsl(188 52% 40%) 0%, hsl(195 45% 30%) 100%)',
    ring: 'hsl(188 80% 58%)',
  },
  designer: {
    bg: 'linear-gradient(145deg, hsl(214 58% 42%) 0%, hsl(225 50% 32%) 100%)',
    ring: 'hsl(214 85% 62%)',
  },
  installer: {
    bg: 'linear-gradient(145deg, hsl(32 72% 42%) 0%, hsl(22 65% 34%) 100%)',
    ring: 'hsl(38 95% 58%)',
  },
  assembler: {
    bg: 'linear-gradient(145deg, hsl(152 48% 36%) 0%, hsl(168 42% 28%) 100%)',
    ring: 'hsl(152 72% 52%)',
  },
  client: {
    bg: 'linear-gradient(145deg, hsl(220 14% 42%) 0%, hsl(228 12% 30%) 100%)',
    ring: 'hsl(220 35% 62%)',
  },
}

function collabRoleLabel(role: string | undefined): string {
  if (!role) return ''
  return COLLAB_ROLE_LABELS[role as CollabMemberRole] ?? role
}

function isCollabMemberRole(r: string): r is CollabMemberRole {
  return Object.prototype.hasOwnProperty.call(COLLAB_ROLE_LABELS, r)
}

const collabInviteRole = ref<CollabMemberRole>('designer')
const collabAuthMode = ref<'login' | 'register'>('login')
const collabBusy = ref(false)
const collabStatus = ref('')

/** Правая колонка: чат, совместные заметки (CRDT), Телемост */
const rightWorkAreaTab = ref<'chat' | 'notes' | 'telemost'>('chat')
/** Телемост: ссылка выдаётся сервером (одна комната на проект), без ручного ввода */
const telemostLoading = ref(false)
const telemostJoinUrl = ref('')
const telemostNeedsOAuth = ref(false)
const telemostHint = ref('')

/** Этап 2: связки PDF ↔ 3D по проекту (реестр + автоподбор по именам вложений чата) */
const collabAssetPairs = ref<Array<Record<string, unknown>>>([])
const collabAssetPairsLoading = ref(false)
const collabAssetSuggestions = ref<Array<Record<string, unknown>>>([])
const collabSuggestLoading = ref(false)

/** Яндекс.Диск: публичная папка (ссылка) или OAuth (весь диск) — дерево с ленивой подгрузкой */
const diskTreeTab = ref<'pdf' | '3d'>('pdf')
const workspaceMode = ref<'engineering' | 'production'>('engineering')
const yandexDiskMode = ref<'none' | 'public' | 'oauth'>('none')
const yandexDiskConnected = ref(false)
const yandexDiskStatus = ref('Диск не подключен')
const yandexDiskUrlInput = ref('')
const yandexDiskRootNodes = ref<DiskNode[]>([])

async function yadiskFetch(path: string, init?: RequestInit): Promise<Response> {
  return fetch(`${collabApiBase.value}${path}`, {
    credentials: 'include',
    ...init,
    headers: {
      ...(init?.body && !(init.headers instanceof Headers) ? { 'Content-Type': 'application/json' } : {}),
      ...((init?.headers as Record<string, string> | undefined) || {}),
    },
  })
}

function diskNodeFromApi(raw: Record<string, unknown>): DiskNode {
  const t = raw.type === 'dir' ? 'dir' : 'file'
  return {
    type: t,
    name: String(raw.name || ''),
    path: String(raw.path || ''),
    href: (raw.href as string) || null,
    mime_type: (raw.mime_type as string) || null,
    size: typeof raw.size === 'number' ? raw.size : null,
    children: undefined,
    expanded: false,
    loaded: false,
    loading: false,
  }
}

async function loadYandexPublicRoot() {
  const publicUrl = yandexDiskUrlInput.value.trim()
  if (!publicUrl) {
    yandexDiskStatus.value = 'Введите URL публичной папки или файла'
    return
  }
  if (!/^https?:\/\//i.test(publicUrl)) {
    yandexDiskStatus.value = 'URL должен начинаться с http:// или https://'
    return
  }
  yandexDiskStatus.value = 'Загрузка списка (публичная ссылка)…'
  const res = await yadiskFetch('/api/yadisk/public/list', {
    method: 'POST',
    body: JSON.stringify({ public_url: publicUrl, path: '', limit: 500, offset: 0 }),
  })
  if (!res.ok) {
    const t = await res.text()
    yandexDiskStatus.value = `Ошибка API: ${res.status} ${t.slice(0, 200)}`
    return
  }
  const data = (await res.json()) as { items?: Record<string, unknown>[] }
  const items = (data.items || []).map((x) => diskNodeFromApi(x))
  yandexDiskRootNodes.value = items
  yandexDiskMode.value = 'public'
  yandexDiskConnected.value = true
  yandexDiskStatus.value = `Публичная папка: в корне ${items.length} элемент(ов)`
}

async function loadYandexPrivateRoot() {
  yandexDiskStatus.value = 'Загрузка корня диска (OAuth)…'
  const res = await yadiskFetch(`/api/yadisk/private/list?path=${encodeURIComponent('disk:/')}&limit=500&offset=0`)
  if (!res.ok) {
    const t = await res.text()
    yandexDiskStatus.value = `Ошибка API: ${res.status} ${t.slice(0, 200)}`
    yandexDiskRootNodes.value = []
    return
  }
  const data = (await res.json()) as { items?: Record<string, unknown>[] }
  const items = (data.items || []).map((x) => diskNodeFromApi(x))
  yandexDiskRootNodes.value = items
  yandexDiskMode.value = 'oauth'
  yandexDiskConnected.value = true
  yandexDiskStatus.value = `OAuth: в корне диска ${items.length} элемент(ов)`
}

async function loadYandexDiskChildren(node: DiskNode) {
  if (node.type !== 'dir' || node.loading || node.loaded) return
  node.loading = true
  try {
    let res: Response
    if (yandexDiskMode.value === 'public') {
      const publicUrl = yandexDiskUrlInput.value.trim()
      const subPath = node.path.trim()
      res = await yadiskFetch('/api/yadisk/public/list', {
        method: 'POST',
        body: JSON.stringify({
          public_url: publicUrl,
          path: subPath,
          limit: 500,
          offset: 0,
        }),
      })
    } else {
      res = await yadiskFetch(
        `/api/yadisk/private/list?path=${encodeURIComponent(node.path)}&limit=500&offset=0`
      )
    }
    if (!res.ok) {
      const t = await res.text()
      yandexDiskStatus.value = `Ошибка вложенной папки: ${res.status} ${t.slice(0, 160)}`
      node.children = []
      node.loaded = true
      return
    }
    const data = (await res.json()) as { items?: Record<string, unknown>[] }
    node.children = (data.items || []).map((x) => diskNodeFromApi(x))
    node.loaded = true
  } finally {
    node.loading = false
  }
}

async function onYandexDiskToggleDir(node: DiskNode) {
  if (node.type !== 'dir') return
  if (!node.expanded) {
    if (!node.loaded) await loadYandexDiskChildren(node)
    node.expanded = true
  } else {
    node.expanded = false
  }
}

async function startYandexOAuth() {
  yandexDiskStatus.value = 'Получение ссылки на Яндекс OAuth…'
  const res = await yadiskFetch('/api/yadisk/oauth/url')
  if (!res.ok) {
    const t = await res.text()
    yandexDiskStatus.value = `OAuth недоступен: ${res.status} ${t.slice(0, 240)}`
    return
  }
  const data = (await res.json()) as { authorize_url?: string }
  const url = data.authorize_url
  if (!url) {
    yandexDiskStatus.value = 'Сервер не вернул authorize_url'
    return
  }
  window.open(url, '_blank', 'noopener,noreferrer')
  yandexDiskStatus.value =
    'В открывшейся вкладке войдите в Яндекс; после «Разрешить» дерево подгрузится на этой странице.'
}

async function finishYandexOAuthFromRedirect() {
  yandexDiskMode.value = 'oauth'
  yandexDiskConnected.value = true
  await loadYandexPrivateRoot()
}

async function checkYandexOAuthSession() {
  try {
    const res = await yadiskFetch('/api/yadisk/oauth/status')
    if (!res.ok) return
    const data = (await res.json()) as { connected?: boolean }
    if (data.connected) {
      yandexDiskMode.value = 'oauth'
      yandexDiskConnected.value = true
      if (!yandexDiskRootNodes.value.length) await loadYandexPrivateRoot()
      else yandexDiskStatus.value = 'Яндекс.Диск (OAuth) подключён'
    }
  } catch {
    /* ignore */
  }
}

async function refreshYandexDisk() {
  if (!yandexDiskConnected.value) {
    yandexDiskStatus.value = 'Сначала загрузите публичную папку или войдите через Яндекс'
    return
  }
  if (yandexDiskMode.value === 'public') await loadYandexPublicRoot()
  else if (yandexDiskMode.value === 'oauth') await loadYandexPrivateRoot()
  else yandexDiskStatus.value = 'Нет активного режима'
}

async function disconnectYandexDisk() {
  if (yandexDiskMode.value === 'oauth') {
    try {
      await yadiskFetch('/api/yadisk/oauth/logout', { method: 'POST' })
    } catch {
      /* noop */
    }
  }
  yandexDiskConnected.value = false
  yandexDiskMode.value = 'none'
  yandexDiskRootNodes.value = []
  yandexDiskStatus.value = 'Подключение сброшено'
}

function openYandexDiskUrl() {
  const url = yandexDiskUrlInput.value.trim()
  if (!url) {
    yandexDiskStatus.value = 'Введите URL публичной папки/файла'
    return
  }
  if (!/^https?:\/\//i.test(url)) {
    yandexDiskStatus.value = 'URL должен начинаться с http:// или https://'
    return
  }
  yandexDiskStatus.value = `URL принят: ${url}`
  window.open(url, '_blank', 'noopener,noreferrer')
}

function getFileExt(name: string): string {
  const dot = name.lastIndexOf('.')
  if (dot <= 0 || dot === name.length - 1) return ''
  return name.slice(dot + 1).toLowerCase()
}

function isPdfTreeFile(file: { name: string }): boolean {
  const ext = getFileExt(file.name)
  return ext === 'pdf' || ext === 'dwg' || ext === 'dxf' || ext === 'frw'
}

function isModelTreeFile(file: { name: string }): boolean {
  const ext = getFileExt(file.name)
  return ext === 'glb' || ext === 'gltf' || ext === 'stl' || ext === 'step' || ext === 'stp' || ext === 'iges' || ext === 'igs' || ext === 'm3d' || ext === 'a3d'
}

const MODEL_SOURCE_EXTS = new Set(['step', 'stp', 'igs', 'iges', 'stl'])

function fileStem(name: string): string {
  const dot = name.lastIndexOf('.')
  return (dot > 0 ? name.slice(0, dot) : name).toLowerCase()
}

function findDiskNodeContext(
  nodes: DiskNode[],
  targetPath: string,
): { siblings: DiskNode[] } | null {
  for (const n of nodes) {
    if (n.path === targetPath) return { siblings: nodes }
    if (n.children?.length) {
      const inner = findDiskNodeContext(n.children, targetPath)
      if (inner) return inner
    }
  }
  return null
}

async function listDiskFolderFiles(folderPath: string): Promise<DiskNode[]> {
  if (!folderPath.trim() || !yandexDiskConnected.value) return []
  let res: Response
  if (yandexDiskMode.value === 'public') {
    const publicUrl = yandexDiskUrlInput.value.trim()
    if (!publicUrl) return []
    res = await yadiskFetch('/api/yadisk/public/list', {
      method: 'POST',
      body: JSON.stringify({
        public_url: publicUrl,
        path: folderPath.trim(),
        limit: 500,
        offset: 0,
      }),
    })
  } else if (yandexDiskMode.value === 'oauth') {
    res = await yadiskFetch(
      `/api/yadisk/private/list?path=${encodeURIComponent(folderPath.trim())}&limit=500&offset=0`,
    )
  } else {
    return []
  }
  if (!res.ok) return []
  const data = (await res.json()) as { items?: Record<string, unknown>[] }
  return (data.items || []).map((x) => diskNodeFromApi(x))
}

function diskParentPath(filePath: string): string {
  const p = filePath.trim()
  const slash = p.lastIndexOf('/')
  if (slash <= 0) return ''
  return p.slice(0, slash)
}

async function diskSiblingsForFile(node: DiskNode): Promise<DiskNode[]> {
  const ctx = findDiskNodeContext(yandexDiskRootNodes.value, node.path)
  const fromTree = ctx?.siblings ?? []
  if (fromTree.some((s) => s.path !== node.path && s.type === 'file')) return fromTree
  const parentPath = diskParentPath(node.path)
  if (!parentPath) return fromTree
  const listed = await listDiskFolderFiles(parentPath)
  return listed.length ? listed : fromTree
}

/** Этап 6: при наличии готового GLB с тем же именем не конвертируем STEP в браузере. */
async function resolveModelDiskNode(
  node: DiskNode,
): Promise<{ node: DiskNode; viaGlbSibling: boolean }> {
  const ext = getFileExt(node.name)
  if (!MODEL_SOURCE_EXTS.has(ext)) return { node, viaGlbSibling: false }
  const siblings = await diskSiblingsForFile(node)
  const stem = fileStem(node.name)
  const glb = siblings.find(
    (s) =>
      s.type === 'file' &&
      (getFileExt(s.name) === 'glb' || getFileExt(s.name) === 'gltf') &&
      fileStem(s.name) === stem,
  )
  if (glb) return { node: glb, viaGlbSibling: true }
  return { node, viaGlbSibling: false }
}

async function fetchDiskFileBlob(node: DiskNode): Promise<Blob> {
  if (!yandexDiskConnected.value) throw new Error('Диск не подключён')
  if (!node.path?.trim()) throw new Error('Нет пути к файлу на Диске')
  let res: Response
  if (yandexDiskMode.value === 'public') {
    const publicUrl = yandexDiskUrlInput.value.trim()
    if (!publicUrl) throw new Error('Нет URL публичной папки')
    res = await yadiskFetch('/api/yadisk/public/download', {
      method: 'POST',
      body: JSON.stringify({ public_url: publicUrl, path: node.path.trim() }),
    })
  } else if (yandexDiskMode.value === 'oauth') {
    res = await yadiskFetch(
      `/api/yadisk/private/download?path=${encodeURIComponent(node.path.trim())}`,
    )
  } else {
    throw new Error('Нет активного режима Диска')
  }
  if (!res.ok) {
    const t = await res.text()
    throw new Error(`${res.status} ${t.slice(0, 200)}`)
  }
  return res.blob()
}

async function openDiskTreeFile(node: DiskNode) {
  if (node.type !== 'file' || !node.name) return
  if (!(await confirmWorkspaceDiscard())) return
  yandexDiskStatus.value = `Загрузка ${node.name}…`
  try {
    if (diskTreeTab.value === 'pdf' && isPdfTreeFile(node)) {
      const blob = await fetchDiskFileBlob(node)
      const ext = getFileExt(node.name)
      const mime =
        ext === 'pdf' ? 'application/pdf' : blob.type || 'application/octet-stream'
      const file = new File([blob], node.name, { type: mime })
      if (pdfFile.value?.url) URL.revokeObjectURL(pdfFile.value.url)
      pdfFile.value = { url: URL.createObjectURL(file), name: file.name }
      if (viewMode.value === '3d' || viewMode.value === 'log') viewMode.value = 'split'
      logger.info('App', `PDF с Диска: ${node.name}`)
      yandexDiskStatus.value = `Открыт PDF: ${node.name}`
      return
    }
    if (diskTreeTab.value === '3d' && isModelTreeFile(node)) {
      const { node: target, viaGlbSibling } = await resolveModelDiskNode(node)
      const blob = await fetchDiskFileBlob(target)
      const file = new File([blob], target.name, {
        type: blob.type || 'application/octet-stream',
      })
      if (viewMode.value === '2d' || viewMode.value === 'log') viewMode.value = 'split'
      await viewerRef.value?.loadModelFile?.(file)
      const note = viaGlbSibling ? ` (GLB вместо ${node.name})` : ''
      logger.info('App', `3D с Диска: ${target.name}${note}`)
      yandexDiskStatus.value = `Открыта модель: ${target.name}${note}`
      return
    }
    yandexDiskStatus.value = 'Формат файла не поддерживается для этой вкладки'
  } catch (e) {
    const msg = e instanceof Error ? e.message : 'Ошибка загрузки'
    yandexDiskStatus.value = msg
    logger.error('App', `Диск: ${node.name}`, e)
  }
}

function collectPdfProductionLinks(
  nodes: DiskNode[],
  parentFolder: string
): Array<{ id: string; title: string; folder: string; href: string }> {
  const out: Array<{ id: string; title: string; folder: string; href: string }> = []
  for (const n of nodes) {
    if (n.type === 'dir') {
      const folderLabel = n.name || 'Папка'
      if (n.children?.length) {
        out.push(...collectPdfProductionLinks(n.children, folderLabel))
      }
    } else if (isPdfTreeFile(n)) {
      out.push({
        id: n.path || n.name,
        title: n.name,
        folder: parentFolder,
        href: n.href || '#',
      })
    }
  }
  return out
}

const productionLinks = computed(() => {
  if (!yandexDiskConnected.value || !yandexDiskRootNodes.value.length) return []
  return collectPdfProductionLinks(yandexDiskRootNodes.value, 'Корень')
})

const WORKSPACE_LS_SIDEBAR = 'workspace.sidebarWidthPx'
const WORKSPACE_LS_RIGHT = 'workspace.rightPanelWidthPx'
const WORKSPACE_LS_CENTER_PDF = 'workspace.centerPdfWidthPx'
const WORKSPACE_LS_DISK_COLLAPSED = 'workspace.diskPanelCollapsed'
const WORKSPACE_LS_CHAT_COLLAPSED = 'workspace.chatPanelCollapsed'
const COLLAPSED_PANEL_PX = 36
const WORKSPACE_SPLITTER_PX = 5
const PANEL_NUDGE_STEP_PX = 28

const sidebarWidth = ref(248)
const rightPanelWidth = ref(380)
const diskPanelCollapsed = ref(false)
const chatPanelCollapsed = ref(false)
let sidebarWidthBeforeCollapse = 248
let rightPanelWidthBeforeCollapse = 380

/** Ширина левой колонки (диск + сплиттер) в flex workspace */
const effectiveLeftRailWidth = computed(() =>
  diskPanelCollapsed.value
    ? COLLAPSED_PANEL_PX
    : sidebarWidth.value + WORKSPACE_SPLITTER_PX,
)
/** Ширина правой колонки (сплиттер + чат) в flex workspace */
const effectiveRightRailWidth = computed(() =>
  chatPanelCollapsed.value
    ? COLLAPSED_PANEL_PX
    : rightPanelWidth.value + WORKSPACE_SPLITTER_PX,
)

function persistWorkspaceLayout() {
  try {
    localStorage.setItem(WORKSPACE_LS_SIDEBAR, String(sidebarWidth.value))
    localStorage.setItem(WORKSPACE_LS_RIGHT, String(rightPanelWidth.value))
    localStorage.setItem(WORKSPACE_LS_DISK_COLLAPSED, diskPanelCollapsed.value ? '1' : '0')
    localStorage.setItem(WORKSPACE_LS_CHAT_COLLAPSED, chatPanelCollapsed.value ? '1' : '0')
  } catch {
    /* noop */
  }
}

function toggleDiskPanel() {
  if (diskPanelCollapsed.value) {
    diskPanelCollapsed.value = false
    sidebarWidth.value = clampWorkspaceWidth(sidebarWidthBeforeCollapse, 160, 480)
  } else {
    sidebarWidthBeforeCollapse = sidebarWidth.value
    diskPanelCollapsed.value = true
  }
  persistWorkspaceLayout()
}

function toggleChatPanel() {
  if (chatPanelCollapsed.value) {
    chatPanelCollapsed.value = false
    rightPanelWidth.value = clampWorkspaceWidth(rightPanelWidthBeforeCollapse, 260, 720)
  } else {
    rightPanelWidthBeforeCollapse = rightPanelWidth.value
    chatPanelCollapsed.value = true
  }
  persistWorkspaceLayout()
}

function nudgeDiskPanelWidth(delta: number) {
  if (diskPanelCollapsed.value) {
    if (delta > 0) toggleDiskPanel()
    return
  }
  sidebarWidth.value = clampWorkspaceWidth(sidebarWidth.value + delta, 160, 480)
  persistWorkspaceLayout()
}

function nudgeChatPanelWidth(delta: number) {
  if (chatPanelCollapsed.value) {
    if (delta > 0) toggleChatPanel()
    return
  }
  rightPanelWidth.value = clampWorkspaceWidth(rightPanelWidth.value + delta, 260, 720)
  persistWorkspaceLayout()
}
/** Ширина панели PDF в режиме «Разделение» (2D | 3D), px */
const centerPdfWidth = ref(440)

function clampWorkspaceWidth(w: number, min: number, max: number): number {
  if (!Number.isFinite(w)) return min
  return Math.min(max, Math.max(min, Math.round(w)))
}

let workspaceSplitterDrag: { kind: 'left' | 'right'; startX: number; sw: number; rw: number } | null = null

function onWorkspaceSplitterDown(kind: 'left' | 'right', e: MouseEvent) {
  if (kind === 'left' && diskPanelCollapsed.value) return
  if (kind === 'right' && chatPanelCollapsed.value) return
  e.preventDefault()
  workspaceSplitterDrag = {
    kind,
    startX: e.clientX,
    sw: sidebarWidth.value,
    rw: rightPanelWidth.value,
  }
  document.body.classList.add('workspace-resizing')
  window.addEventListener('mousemove', onWorkspaceSplitterMove)
  window.addEventListener('mouseup', onWorkspaceSplitterUp)
}

function onWorkspaceSplitterMove(e: MouseEvent) {
  if (!workspaceSplitterDrag) return
  const dx = e.clientX - workspaceSplitterDrag.startX
  if (workspaceSplitterDrag.kind === 'left') {
    sidebarWidth.value = clampWorkspaceWidth(workspaceSplitterDrag.sw + dx, 160, 480)
  } else {
    /* Граница между центром и чатом: движение вправо уменьшает чат (центр забирает место) */
    rightPanelWidth.value = clampWorkspaceWidth(workspaceSplitterDrag.rw - dx, 260, 720)
  }
}

function onWorkspaceSplitterUp() {
  workspaceSplitterDrag = null
  document.body.classList.remove('workspace-resizing')
  window.removeEventListener('mousemove', onWorkspaceSplitterMove)
  window.removeEventListener('mouseup', onWorkspaceSplitterUp)
  persistWorkspaceLayout()
}

let centerSplitterDrag: { startX: number; startW: number } | null = null

const workspaceContentRef = ref<HTMLElement | null>(null)

function onCenterSplitterDown(e: MouseEvent) {
  e.preventDefault()
  centerSplitterDrag = { startX: e.clientX, startW: centerPdfWidth.value }
  document.body.classList.add('workspace-resizing')
  window.addEventListener('mousemove', onCenterSplitterMove)
  window.addEventListener('mouseup', onCenterSplitterUp)
}

function onCenterSplitterMove(e: MouseEvent) {
  if (!centerSplitterDrag) return
  const dx = e.clientX - centerSplitterDrag.startX
  const total = workspaceContentRef.value?.getBoundingClientRect().width ?? 800
  const maxPdf = Math.max(200, total - 240)
  centerPdfWidth.value = clampWorkspaceWidth(centerSplitterDrag.startW + dx, 160, maxPdf)
}

function onCenterSplitterUp() {
  centerSplitterDrag = null
  document.body.classList.remove('workspace-resizing')
  window.removeEventListener('mousemove', onCenterSplitterMove)
  window.removeEventListener('mouseup', onCenterSplitterUp)
  try {
    localStorage.setItem(WORKSPACE_LS_CENTER_PDF, String(centerPdfWidth.value))
  } catch {
    /* noop */
  }
}

function uint8ToBase64(u8: Uint8Array): string {
  let b = ''
  for (let i = 0; i < u8.length; i++) b += String.fromCharCode(u8[i])
  return btoa(b)
}

function base64ToUint8(b64: string): Uint8Array {
  const bin = atob(b64)
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out
}

function collabAwarenessUserColor(clientId: number): string {
  const h = (clientId * 37) % 360
  return `hsl(${h} 58% 52%)`
}

const collabNotesDoc = shallowRef<Y.Doc | null>(null)
const collabNotesAwareness = shallowRef<Awareness | null>(null)

async function collabLoadTelemost() {
  telemostHint.value = ''
  if (!collabToken.value || !collabProjectId.value) {
    telemostJoinUrl.value = ''
    telemostNeedsOAuth.value = false
    return
  }
  telemostLoading.value = true
  try {
    const res = await collabAuthFetch(`/api/projects/${collabProjectId.value}/telemost`)
    let data: Record<string, unknown> = {}
    try {
      data = (await res.json()) as Record<string, unknown>
    } catch {
      data = {}
    }
    if (!res.ok) {
      telemostJoinUrl.value = ''
      telemostNeedsOAuth.value = false
      const d = data.detail
      telemostHint.value =
        typeof d === 'string' ? d : `Ошибка ${res.status}`
      return
    }
    if (data.needsOAuth === true || data.ok === false) {
      telemostNeedsOAuth.value = true
      telemostJoinUrl.value = ''
      telemostHint.value = typeof data.message === 'string' ? data.message : ''
      return
    }
    telemostNeedsOAuth.value = false
    telemostJoinUrl.value = typeof data.joinUrl === 'string' ? data.joinUrl : ''
  } catch (e) {
    telemostJoinUrl.value = ''
    telemostNeedsOAuth.value = false
    telemostHint.value = e instanceof Error ? e.message : 'Ошибка'
  } finally {
    telemostLoading.value = false
  }
}

const telemostCallBanner = ref<{ title: string; joinUrl: string } | null>(null)

type TelemostExtraRoom = { id: string; title: string; joinUrl: string; createdAt: string }
const telemostExtraRooms = ref<TelemostExtraRoom[]>([])

function telemostRoomsStorageKey(): string | null {
  return collabProjectId.value ? `deskreview.telemostRooms.${collabProjectId.value}` : null
}

function loadTelemostExtraRooms() {
  const key = telemostRoomsStorageKey()
  if (!key) {
    telemostExtraRooms.value = []
    return
  }
  try {
    const raw = localStorage.getItem(key)
    telemostExtraRooms.value = raw ? (JSON.parse(raw) as TelemostExtraRoom[]) : []
  } catch {
    telemostExtraRooms.value = []
  }
}

async function postTelemostLinkToChat(link: string, label: string) {
  const ch = collabChannelId.value
  const pid = collabProjectId.value
  if (!ch || !pid) return
  try {
    await collabAuthFetch(`/api/projects/${pid}/channels/${ch}/messages`, {
      method: 'POST',
      body: JSON.stringify({ body: `${label}: ${link}` }),
    })
  } catch {
    /* WS / баннер — запасной путь */
  }
}

function openTelemostUrl(joinUrl: string) {
  if (!joinUrl) return
  window.open(joinUrl, '_blank', 'noopener,noreferrer')
}

function broadcastTelemostJoin(joinUrl: string, title: string) {
  if (collabWs?.readyState === WebSocket.OPEN) {
    collabWs.send(JSON.stringify({ type: 'telemost.join', joinUrl, title }))
  }
}
const saveActionToast = ref('')
const pdfMarkupDirty = ref(false)
const model3dRemarksDirty = ref(false)

function dismissTelemostBanner() {
  telemostCallBanner.value = null
}

function showSaveToast(message: string) {
  saveActionToast.value = message
  window.setTimeout(() => {
    if (saveActionToast.value === message) saveActionToast.value = ''
  }, 2800)
}

const activeFocusContext = computed<'pdf' | '3d'>(() => {
  if (viewMode.value === '2d') return 'pdf'
  if (viewMode.value === '3d') return '3d'
  return pdfFile.value ? 'pdf' : '3d'
})

async function telemostJoinFromMenu() {
  if (!collabToken.value || !collabProjectId.value) {
    window.alert('Войдите в чат и выберите проект.')
    return
  }
  rightWorkAreaTab.value = 'telemost'
  await collabLoadTelemost()
  if (telemostJoinUrl.value) {
    const joinUrl = telemostJoinUrl.value
    const proj = collabProjects.value.find((p: { id: string }) => p.id === collabProjectId.value) as
      | { name?: string; title?: string }
      | undefined
    const title = proj?.name?.trim() || proj?.title?.trim() || 'Звонок проекта'
    openTelemostUrl(joinUrl)
    broadcastTelemostJoin(joinUrl, title)
    await postTelemostLinkToChat(joinUrl, 'Звонок Телемост')
  } else if (telemostHint.value) {
    window.alert(telemostHint.value)
  }
}

async function telemostCreateMeetingFromMenu() {
  const title = window.prompt('Название встречи (подгруппа):', 'Встреча команды')
  if (!title?.trim()) return
  if (!collabProjectId.value) {
    window.alert('Выберите проект в чате.')
    return
  }
  await collabLoadTelemost()
  const joinUrl = telemostJoinUrl.value || ''
  const key = telemostRoomsStorageKey()
  if (key) {
    try {
      const rooms = [...telemostExtraRooms.value]
      rooms.unshift({
        id: `room_${Date.now()}`,
        title: title.trim(),
        joinUrl,
        createdAt: new Date().toISOString(),
      })
      localStorage.setItem(key, JSON.stringify(rooms.slice(0, 20)))
      loadTelemostExtraRooms()
    } catch {
      /* noop */
    }
  }
  if (joinUrl) {
    broadcastTelemostJoin(joinUrl, title.trim())
    await postTelemostLinkToChat(joinUrl, title.trim())
  }
  telemostCallBanner.value = joinUrl ? { title: title.trim(), joinUrl } : null
  rightWorkAreaTab.value = 'telemost'
}

async function onWorkspaceSave() {
  if (activeFocusContext.value === 'pdf' && pdfFile.value) {
    const r = await pdfViewerRef.value?.exportPdfWithRemarks?.()
    if (r?.ok && r.fileName) {
      const msg =
        r.mode === 'flattened'
          ? `PDF с пометками на листе: ${r.fileName}`
          : `Замечания проекта: ${r.fileName} и файл слоя`
      showSaveToast(msg)
    }
    else if (r?.ok === false) showSaveToast('Не удалось экспортировать PDF')
    else showSaveToast('Откройте PDF и добавьте пометки')
    return
  }
  if (viewerRef.value) {
    const r = await viewerRef.value.saveModel3dRemarksToFile?.()
    if (r?.ok && r.fileName) showSaveToast(`Замечания 3D: ${r.fileName}`)
    else if (r?.ok === false) showSaveToast('Откройте 3D-модель в сцене')
    else showSaveToast('Нет замечаний 3D для сохранения')
    return
  }
  showSaveToast('3D: нет активной модели')
}

async function onWorkspaceSaveAs() {
  await onWorkspaceSave()
}

function onPdfMarkupDirty(dirty: boolean) {
  pdfMarkupDirty.value = dirty
}

function onModel3dRemarksDirty(dirty: boolean) {
  model3dRemarksDirty.value = dirty
}

async function confirmWorkspaceDiscard(): Promise<boolean> {
  if (pdfFile.value && pdfMarkupDirty.value) {
    const ok = (await pdfViewerRef.value?.confirmDiscardMarkupAsync?.()) ?? true
    if (!ok) return false
  }
  if (model3dRemarksDirty.value) {
    const ok = (await viewerRef.value?.confirmDiscardModel3dRemarksAsync?.()) ?? true
    if (!ok) return false
  }
  return true
}

function confirmPdfMarkupDiscard(): boolean {
  return pdfViewerRef.value?.confirmDiscardMarkup?.() ?? true
}

function onBeforeUnload(ev: BeforeUnloadEvent) {
  if (pdfMarkupDirty.value || model3dRemarksDirty.value) {
    ev.preventDefault()
    ev.returnValue = ''
  }
}

function onWorkspaceUndo() {
  if (activeFocusContext.value === 'pdf' && pdfFile.value) {
    if (pdfViewerRef.value?.undoMarkup?.()) {
      showSaveToast('Отменено (PDF)')
      return
    }
    showSaveToast('Нечего отменять в PDF')
    return
  }
  if (viewerRef.value?.undoLastAction?.()) {
    showSaveToast('Отменено (3D)')
    return
  }
  showSaveToast('Нечего отменять')
}

function onShowLogs() {
  viewMode.value = 'log'
}

function onExportReportEmail() {
  window.alert('Отправка скриншот-отчёта по почте — в разработке.')
}

async function onExportReportChat() {
  if (reportScreenshots.value.length === 0) {
    window.alert('Добавьте скриншоты в «Скриншот-отчёт» → «Все скриншоты».')
    return
  }
  for (const item of reportScreenshots.value) {
    await sendScreenshotToChat(item)
  }
}

function onWorkspaceKeydown(e: KeyboardEvent) {
  const tag = (e.target as HTMLElement)?.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (e.target as HTMLElement)?.isContentEditable) return
  if (e.ctrlKey && e.key === 's') {
    e.preventDefault()
    void onWorkspaceSave()
  } else if (e.ctrlKey && e.key === 'z') {
    e.preventDefault()
    onWorkspaceUndo()
  } else if (e.key === 'Escape') {
    if (pdfViewerRef.value?.cancelMarkupAction?.()) {
      e.preventDefault()
      return
    }
    viewerRef.value?.cancelActiveTool?.()
  }
}

watch(rightWorkAreaTab, (t) => {
  if (t === 'telemost') void collabLoadTelemost()
})

watch(
  () => [collabUser.value?.displayName, collabUser.value?.email] as const,
  () => {
    const a = collabNotesAwareness.value
    if (!a) return
    const name = collabUser.value?.displayName?.trim() || collabUser.value?.email || 'Участник'
    a.setLocalStateField('user', {
      name,
      color: collabAwarenessUserColor(a.clientID),
    })
  }
)

/** Процент загрузки файла на 📎 (null — не идёт загрузка) */
const collabAttachPct = ref<number | null>(null)
const collabSendingText = ref(false)
/** Сдвигается раз в минуту — подписи «Сегодня» / «Вчера» и разделители дат обновляются после полуночи */
const collabDateTick = ref(0)
let collabDayTimer: ReturnType<typeof setInterval> | null = null
let collabWs: WebSocket | null = null
/** Ложим Yjs-трафик только после ws.connected (или при legacy-подключении сразу после открытия с тем же сервером). */
let collabWsYjsEnabled = false

const MONTHS_RU_SHORT = [
  'янв',
  'фев',
  'мар',
  'апр',
  'мая',
  'июн',
  'июл',
  'авг',
  'сен',
  'окт',
  'ноя',
  'дек',
]

function startOfLocalDay(d: Date): Date {
  const x = new Date(d)
  x.setHours(0, 0, 0, 0)
  return x
}

function parseMessageIso(iso: string | undefined): Date | null {
  if (!iso) return null
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? null : d
}

function dayKeyLocal(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function formatDaySeparatorLabel(d: Date): string {
  collabDateTick.value
  const today = startOfLocalDay(new Date())
  const yesterday = new Date(today)
  yesterday.setDate(yesterday.getDate() - 1)
  const t = startOfLocalDay(d)
  if (t.getTime() === today.getTime()) return 'Сегодня'
  if (t.getTime() === yesterday.getTime()) return 'Вчера'
  return `${d.getDate()} ${MONTHS_RU_SHORT[d.getMonth()]} ${d.getFullYear()}`
}

function formatMessageTime(iso: string | undefined): string {
  const d = parseMessageIso(iso)
  if (!d) return ''
  return d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

function collabMessageAuthorLabel(m: Record<string, unknown>): string {
  const self = collabUser.value
  const aid = String(m.author_id ?? '')
  if (self?.id && aid && self.id === aid) {
    const n = self.displayName?.trim()
    if (n) return n
    const e = self.email?.trim()
    if (e) return e
  }
  const a = m.author as Record<string, unknown> | undefined
  const pick = (v: unknown) => (typeof v === 'string' && v.trim() ? v.trim() : '')
  const name =
    pick(a?.displayName) ||
    pick(a?.display_name) ||
    pick(m.authorDisplayName) ||
    pick(m.author_display_name) ||
    pick(a?.email) ||
    pick(m.authorEmail) ||
    pick(m.author_email)
  if (name) return name
  return 'Участник'
}

function collabAuthorIdForMessage(m: Record<string, unknown>): string {
  return String(m.author_id ?? (m.author as { id?: string } | undefined)?.id ?? '')
}

const collabCurrentProjectRole = computed((): CollabMemberRole | null => {
  const p = collabProjects.value.find((x: { id: string }) => x.id === collabProjectId.value)
  const r = p?.role
  return typeof r === 'string' && r in COLLAB_ROLE_LABELS ? (r as CollabMemberRole) : null
})

/** Совпадает с server/main._role_can_manage_members */
const collabCanManageMembers = computed(() => {
  const r = collabCurrentProjectRole.value
  return r === 'gip' || r === 'chief_designer' || r === 'designer'
})

function collabRoleFromMessage(m: Record<string, unknown>): CollabMemberRole | null {
  const pick =
    (typeof m.authorProjectRole === 'string' && m.authorProjectRole) ||
    (typeof (m.author as Record<string, unknown> | undefined)?.projectRole === 'string' &&
      String((m.author as Record<string, unknown>).projectRole)) ||
    (typeof (m.author as Record<string, unknown> | undefined)?.project_role === 'string' &&
      String((m.author as Record<string, unknown>).project_role)) ||
    ''
  if (pick && pick in COLLAB_ROLE_LABELS) return pick as CollabMemberRole
  const self = collabUser.value
  const aid = String(m.author_id ?? '')
  if (self?.id && aid && self.id === aid && collabCurrentProjectRole.value) {
    return collabCurrentProjectRole.value
  }
  return null
}

function collabMessageRow(m: Record<string, unknown>): {
  author: string
  role: CollabMemberRole | null
  roleShort: string
  avatar: { initials: string; bg: string; ring: string }
} {
  const author = collabMessageAuthorLabel(m)
  const id = collabAuthorIdForMessage(m) || author || 'x'
  const role = collabRoleFromMessage(m)
  let initials = '?'
  const trimmed = author.replace(/\s+/g, ' ').trim()
  if (trimmed && trimmed !== 'Участник') {
    const parts = trimmed.split(/\s+/).filter(Boolean)
    if (parts.length >= 2) {
      const a = parts[0][0]
      const b = parts[parts.length - 1][0]
      if (a && b) initials = (a + b).toUpperCase()
    } else {
      initials = trimmed.slice(0, 2).toUpperCase()
    }
  } else {
    const hexish = id.replace(/-/g, '').slice(0, 2)
    initials = hexish.length >= 2 ? hexish.toUpperCase() : '?'
  }
  if (role && COLLAB_ROLE_AVATAR[role]) {
    const a = COLLAB_ROLE_AVATAR[role]
    return {
      author,
      role,
      roleShort: COLLAB_ROLE_SHORT[role],
      avatar: { initials, bg: a.bg, ring: a.ring },
    }
  }
  let h = 0
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) | 0
  const hue = Math.abs(h) % 360
  const fall = `hsl(${hue} 46% 36%)`
  return {
    author,
    role: null,
    roleShort: '',
    avatar: { initials, bg: fall, ring: `hsl(${hue} 55% 55%)` },
  }
}

type CollabTimelineItem =
  | { type: 'sep'; key: string; label: string }
  | {
      type: 'msg'
      key: string
      message: Record<string, unknown>
      row: {
        author: string
        role: CollabMemberRole | null
        roleShort: string
        avatar: { initials: string; bg: string; ring: string }
      }
    }

function buildCollabTimeline(messages: typeof collabMessages.value): CollabTimelineItem[] {
  collabDateTick.value
  void collabUser.value?.id
  void collabCurrentProjectRole.value
  const items: CollabTimelineItem[] = []
  let lastDay: string | null = null
  for (const m of messages) {
    const d = parseMessageIso(m.created_at as string | undefined)
    if (d) {
      const dk = dayKeyLocal(d)
      if (dk !== lastDay) {
        lastDay = dk
        items.push({ type: 'sep', key: `sep-${dk}`, label: formatDaySeparatorLabel(d) })
      }
    }
    const msg = m as Record<string, unknown>
    items.push({ type: 'msg', key: String(m.id), message: msg, row: collabMessageRow(msg) })
  }
  return items
}

const collabChatTimeline = computed(() => buildCollabTimeline(collabMessages.value))

const MODEL_EXTENSIONS = ['stl', 'step', 'stp', 'igs', 'iges', 'glb', 'gltf']

let pdfInput: HTMLInputElement | null = null

async function openLocalPdfFile(file: File, siblings?: Iterable<File>) {
  if (!(await confirmWorkspaceDiscard())) return
  logger.info('App', `PDF открыт: ${file.name}`)
  if (pdfFile.value?.url) URL.revokeObjectURL(pdfFile.value.url)
  let markupSidecarBytes: ArrayBuffer | null = null
  const sidecar = siblings ? findSidecarFileForPdf(siblings, file.name) : undefined
  if (sidecar) {
    markupSidecarBytes = await sidecar.arrayBuffer()
    logger.info('App', `Слой замечаний подхвачен: ${sidecar.name}`)
  }
  pdfFile.value = { url: URL.createObjectURL(file), name: file.name, markupSidecarBytes }
}

function onDragOver(e: DragEvent) {
  if (!e.dataTransfer?.types.includes('Files')) return
  e.preventDefault()
  e.dataTransfer.dropEffect = 'copy'
  isDraggingFile.value = true
}

function onDragLeave() {
  isDraggingFile.value = false
}

async function onDrop(e: DragEvent) {
  isDraggingFile.value = false
  if (!e.dataTransfer?.types.includes('Files')) return
  e.preventDefault()
  const dropped = e.dataTransfer.files
  if (!dropped?.length) return
  const pdf = Array.from(dropped).find(
    (f) => (f.name.split('.').pop() || '').toLowerCase() === 'pdf',
  )
  if (pdf) {
    await openLocalPdfFile(pdf, dropped)
    return
  }
  const first = dropped[0]
  if (!first) return
  const ext = (first.name.split('.').pop() || '').toLowerCase()
  if (MODEL_EXTENSIONS.includes(ext)) {
    if (!(await confirmWorkspaceDiscard())) return
    if (viewMode.value === '2d' || viewMode.value === 'log') viewMode.value = 'split'
    const modelFiles = Array.from(e.dataTransfer.files || [])
      .filter((f) => MODEL_EXTENSIONS.includes((f.name.split('.').pop() || '').toLowerCase()))
      .slice(0, 5)
    if (modelFiles.length) {
      if ((e.dataTransfer.files?.length ?? 0) > 5) {
        logger.warn('App', `Сброшено ${e.dataTransfer.files!.length} файлов, загружаем 5`)
        alert('Загружаем первые 5 файлов для стабильной работы.')
      }
      logger.info('App', `3D файлы сброшены: ${modelFiles.map((f) => f.name).join(', ')}`)
      for (const f of modelFiles) {
        try {
          await viewerRef.value?.loadModelFile?.(f)
        } catch (e) {
          logger.error('App', `Ошибка загрузки ${f.name}`, e)
        }
      }
    }
    return
  }
  alert('Поддерживаются PDF и 3D (STL, STEP, IGES, GLB)')
}

function onOpenPdf() {
  if (!pdfInput) {
    pdfInput = document.createElement('input')
    pdfInput.type = 'file'
    pdfInput.multiple = true
    pdfInput.accept = '.pdf,application/pdf,.json,application/json'
    pdfInput.onchange = () => {
      const picked = pdfInput?.files
      if (!picked?.length) {
        if (pdfInput) pdfInput.value = ''
        return
      }
      const pdf = Array.from(picked).find(
        (f) => (f.name.split('.').pop() || '').toLowerCase() === 'pdf',
      )
      if (pdf) void openLocalPdfFile(pdf, picked)
      if (pdfInput) pdfInput.value = ''
    }
  }
  pdfInput.click()
}

async function onViewModeChange(mode: ViewMode) {
  viewMode.value = mode
  logger.info('App', `Режим вида: ${mode}`)
  await nextTick()
  requestAnimationFrame(() => {
    viewerRef.value?.resizeViewport?.()
    requestAnimationFrame(() => viewerRef.value?.resizeViewport?.())
  })
}

function onOpenFile() {
  logger.info('App', 'Открыть 3D модель (диалог)')
  viewerRef.value?.openFileDialog()
}

function onOpenSettings() {
  viewerRef.value?.openSettingsModal?.()
}

function onResetView() {
  logger.info('App', 'Вид 3D сброшен')
  viewerRef.value?.resetView?.()
}

function onExportGlb() {
  viewerRef.value?.exportGlb?.()
}

function onExportStl() {
  viewerRef.value?.exportStl?.()
}

const REPORT_LABELS_CYR = {
  drawing: 'Чертеж (PDF)',
  model: '3D модель',
  measurements: 'Измерения',
  length: 'Длина',
  mm: 'мм',
  noMeasurements: 'Измерения не проведены',
}
const REPORT_LABELS_LATIN = {
  drawing: 'Drawing (PDF)',
  model: '3D model',
  measurements: 'Measurements',
  length: 'Length',
  mm: 'mm',
  noMeasurements: 'No measurements',
}

const REPORT_HEADER_LOGO_URL = `${import.meta.env.BASE_URL}icons/BATaHuPPWB1rtuq7abGe.jpg`
const REPORT_HEADER_LOGO_HEIGHT_MM = 10

async function loadReportHeaderLogo(doc: jsPDF): Promise<{ dataUrl: string; w: number; h: number } | null> {
  try {
    const res = await fetch(REPORT_HEADER_LOGO_URL)
    if (!res.ok) return null
    const blob = await res.blob()
    const dataUrl = await new Promise<string>((resolve, reject) => {
      const r = new FileReader()
      r.onload = () => resolve(r.result as string)
      r.onerror = reject
      r.readAsDataURL(blob)
    })
    const img = new Image()
    await new Promise<void>((resolve, reject) => {
      img.onload = () => resolve()
      img.onerror = reject
      img.src = dataUrl
    })
    const aspect = img.width / img.height
    const h = REPORT_HEADER_LOGO_HEIGHT_MM
    const w = Math.min(h * aspect, doc.getPageWidth() - 30)
    return { dataUrl, w, h }
  } catch {
    return null
  }
}

async function loadCyrillicFont(doc: jsPDF): Promise<boolean> {
  // Локальный шрифт из public/fonts (без зависимости от CDN, избегаем 403)
  const url = `${import.meta.env.BASE_URL}fonts/NotoSans-Regular.ttf`
  try {
    const res = await fetch(url)
    if (!res.ok) {
      logger.warn('App', `Кириллический шрифт: fetch не OK, status=${res.status}`)
      return false
    }
    const buf = await res.arrayBuffer()
    const bytes = new Uint8Array(buf)
    logger.info('App', `Кириллический шрифт: загружено ${bytes.length} байт`)
    let binary = ''
    for (let i = 0; i < bytes.length; i++) {
      binary += String.fromCharCode(bytes[i])
    }
    const base64 = btoa(binary)
    doc.addFileToVFS('NotoSansCyrillic.ttf', base64)
    doc.addFont('NotoSansCyrillic.ttf', 'NotoSans', 'normal', 'Identity-H')
    doc.setFont('NotoSans', 'normal')
    logger.info('App', 'Кириллический шрифт: NotoSans зарегистрирован, encoding=Identity-H')
    return true
  } catch (e) {
    logger.error('App', 'Кириллический шрифт: ошибка загрузки/регистрации', e)
    return false
  }
}

async function onExportReport() {
  const doc = new jsPDF({ orientation: 'portrait', unit: 'mm', format: 'a4' })
  const hasCyrillic = await loadCyrillicFont(doc)
  logger.info('App', `Отчёт: кириллический шрифт загружен=${hasCyrillic}`)
  const REPORT_LABELS = hasCyrillic ? REPORT_LABELS_CYR : REPORT_LABELS_LATIN
  const headerLogo = await loadReportHeaderLogo(doc)

  await refreshFirstSheetData()
  const sheet = firstSheetData.value
  logger.info('App', `Отчёт: данные для заголовка (firstSheetData)=${JSON.stringify(sheet)}`)
  logger.info('App', `Отчёт: автор=${reportAuthor.value}, 3D модель=${viewerRef.value?.getLoadedFileName?.() ?? ''}`)

  const margin = 15
  const maxImgH = 160
  let y = margin
  const lineH = 7
  const reportDate = new Date().toISOString().slice(0, 10)
  const pageW = doc.getPageWidth()
  const maxTextW = pageW - margin * 2

  const modelName = viewerRef.value?.getLoadedFileName?.() ?? ''
  if (hasCyrillic) doc.setFont('NotoSans', 'normal')
  const headerRows: [string, string][] = [
    ['Организация', (sheet.organization ?? '').trim()],
    ['Свидетельство СРО', (sheet.sroCertificate ?? '').trim()],
    ['Объект', (sheet.associationOrObject ?? '').trim()],
    ['Адрес', (sheet.address ?? '').trim()],
    ['Тип документа', (sheet.documentType ?? '').trim()],
    ['Раздел', (sheet.section ?? '').trim()],
    ['Шифр проекта', (sheet.projectCode ?? reportProjectName.value).trim()],
    ['Город, год', (sheet.cityYear ?? '').trim()],
    ['Дата отчёта', reportDate],
    ['Автор замечаний', reportAuthor.value.trim()],
    ['Название 3D модели', modelName.trim()],
    ['Название КМД', (pdfFile.value?.name ?? '').trim()],
  ]
  const tableBody = headerRows.map(([label, value], i) => [String(i + 1), label, value || ''])
  const colNoWidth = 14
  const colFieldWidth = 42
  autoTable(doc, {
    head: [['№', 'Поле', 'Значение']],
    body: tableBody,
    startY: y,
    margin: { left: margin, right: margin },
    tableWidth: maxTextW,
    theme: 'grid',
    ...(hasCyrillic
      ? {
          styles: { font: 'NotoSans' },
          willDrawCell: () => {
            doc.setFont('NotoSans', 'normal')
          },
        }
      : {}),
    headStyles: {
      fillColor: [100, 100, 100],
      textColor: [255, 255, 255],
      fontSize: 11,
      fontStyle: 'bold',
      cellPadding: 4,
      ...(hasCyrillic ? { font: 'NotoSans' } : {}),
    },
    bodyStyles: {
      fontSize: 10,
      cellPadding: 4,
      ...(hasCyrillic ? { font: 'NotoSans' } : {}),
    },
    columnStyles: {
      0: { cellWidth: colNoWidth, overflow: 'ellipsize' },
      1: { cellWidth: colFieldWidth },
      2: { cellWidth: maxTextW - colNoWidth - colFieldWidth },
    },
  })
  y = (doc as { lastAutoTable?: { finalY: number } }).lastAutoTable?.finalY ?? y
  y += lineH

  const addImage = (dataUrl: string, titleLines: string[]) => {
    return new Promise<void>((resolve, reject) => {
      const img = new Image()
      img.onload = () => {
        const isLandscape = img.width > img.height
        const pageW = doc.getPageWidth()
        const pageH = doc.getPageHeight()
        const imgW = pageW - margin * 2
        const scale = Math.min(imgW / img.width, maxImgH / img.height)
        const w = img.width * scale
        const h = img.height * scale
        const titleH = titleLines.length * lineH

        const drawTitleBlock = (startY: number) => {
          doc.setFontSize(10)
          let yy = startY
          for (const line of titleLines) {
            if (line) {
              doc.text(line, margin, yy)
              yy += lineH
            }
          }
          return yy
        }

        if (isLandscape && w > pageH - margin * 2) {
          doc.addPage('a4', 'landscape')
          const landW = doc.getPageWidth()
          const landH = doc.getPageHeight()
          const landScale = Math.min((landW - margin * 2) / img.width, (landH - margin * 2 - 20) / img.height)
          const lw = img.width * landScale
          const lh = img.height * landScale
          const ty = drawTitleBlock(margin)
          doc.addImage(dataUrl, 'PNG', margin, ty + 2, lw, lh)
          doc.addPage('a4', 'portrait')
          y = margin
        } else {
          if (y + titleH > pageH - maxImgH - 30) {
            doc.addPage()
            y = margin
          }
          const ty = drawTitleBlock(y)
          y = ty + 2
          doc.addImage(dataUrl, 'PNG', margin, y, w, h)
          y += h + lineH
        }
        resolve()
      }
      img.onerror = reject
      img.src = dataUrl
    })
  }

  try {
    if (reportScreenshots.value.length > 0) {
      logger.info('App', `Отчёт: ${reportScreenshots.value.length} скриншотов из панели`)
      for (let i = 0; i < reportScreenshots.value.length; i++) {
        const item = reportScreenshots.value[i]
        let titleLines: string[]
        if (item.type === '2d') {
          titleLines = [
            item.pdfFileName || REPORT_LABELS.drawing,
            `Страница: ${item.pageNumber ?? '—'}`,
            `Автор замечания: ${reportAuthor.value || '—'}`,
          ]
        } else {
          titleLines = [`${REPORT_LABELS.model} (${i + 1})`, modelName].filter(Boolean)
        }
        await addImage(item.dataUrl, titleLines)
      }
    } else {
      if (pdfFile.value && pdfViewerRef.value) {
        const pdfImg = await pdfViewerRef.value.getCurrentPageImageUrlAsync?.()
        if (pdfImg) {
          logger.info('App', `Отчёт: чертёж — страница PDF, длина=${pdfImg.length}`)
          const pageNum = pdfViewerRef.value?.getScreenshotPage?.() ?? 1
          await addImage(pdfImg, [
            pdfFile.value.name,
            `Страница: ${pageNum}`,
            `Автор замечания: ${reportAuthor.value || '—'}`,
          ])
        }
      }
      if (viewerRef.value) {
        const threeImg = await viewerRef.value.takeScreenshot()
        if (threeImg) {
          logger.info('App', `Отчёт: 3D модель — скриншот, длина=${threeImg.length}`)
          await addImage(threeImg, [REPORT_LABELS.model, modelName].filter(Boolean))
        }
      }
    }

    const pageH = doc.getPageHeight()
    if (y > pageH - 40) {
      doc.addPage()
      y = margin
    }
    if (hasCyrillic) doc.setFont('NotoSans', 'normal')
    doc.setFontSize(12)
    const MEASURE_LABELS = REPORT_LABELS_CYR
    doc.text(MEASURE_LABELS.measurements, margin, y)
    y += lineH + 2
    doc.setFontSize(10)
    const report = viewerRef.value?.getMeasurementReport?.()
    if (report) {
      doc.text(`${MEASURE_LABELS.length}: ${report.length.toFixed(2)} ${MEASURE_LABELS.mm}`, margin, y)
      y += lineH
      doc.text(
        `ΔX: ${report.dx.toFixed(2)} ${MEASURE_LABELS.mm}  ΔY: ${report.dy.toFixed(2)} ${MEASURE_LABELS.mm}  ΔZ: ${report.dz.toFixed(2)} ${MEASURE_LABELS.mm}`,
        margin,
        y
      )
    } else {
      doc.text(MEASURE_LABELS.noMeasurements, margin, y)
    }
    const totalPages = doc.getNumberOfPages()
    for (let i = 1; i <= totalPages; i++) {
      doc.setPage(i)
      if (headerLogo) {
        doc.addImage(headerLogo.dataUrl, 'JPEG', margin, 5, headerLogo.w, headerLogo.h)
      }
      if (hasCyrillic) doc.setFont('NotoSans', 'normal')
      doc.setFontSize(9)
      doc.text(`Страница ${i} из ${totalPages}`, pageW / 2, pageH - 10, { align: 'center' })
    }
    const projectNameForFile = sanitizeFileName(firstSheetData.value.projectCode || reportProjectName.value) || 'отчет'
    doc.save(`Отчет_${projectNameForFile}_${reportDate}.pdf`)
  } catch (e) {
    console.error('Export report:', e)
    alert('Не удалось сформировать отчёт')
  }
}

function onSectionMode() {
  sectionMode.value = !sectionMode.value
  viewerRef.value?.setSectionMode?.(sectionMode.value)
}

function onFixSection() {
  sectionMode.value = false
  viewerRef.value?.setSectionMode?.(false)
}

function onClearSection() {
  sectionMode.value = false
  sectionActive.value = false
  viewerRef.value?.clearSection?.()
}

function onSectionActive() {
  sectionActive.value = true
  sectionOffset.value = 0
}

function onSectionInactive() {
  sectionActive.value = false
}

function onSectionOffsetChanged(value: number) {
  sectionOffset.value = value
}

function onSectionOffset(value: number) {
  sectionOffset.value = value
  viewerRef.value?.setSectionOffset?.(value)
}

function onMeasureSnapMode(mode: MeasureSnapMode) {
  measureSnapMode.value = mode
  viewerRef.value?.setMeasureSnapMode?.(mode)
}

function onMeasure() {
  logger.info('App', `onMeasure вызван, measureMode до переключения: ${measureMode.value}`)
  measureMode.value = !measureMode.value
  logger.info('App', `measureMode после переключения: ${measureMode.value} → передаём в 3D setMeasureMode`)
  viewerRef.value?.setMeasureMode?.(measureMode.value)
}

function onMeasureTypeUpdate(type: MeasureType) {
  measureType.value = type
  viewerRef.value?.setMeasureType?.(type)
}

function onClearMeasurements() {
  logger.info('App', 'onClearMeasurements вызван')
  viewerRef.value?.clearMeasurements?.()
  pdfViewerRef.value?.clearMeasurements?.()
}

function onSaveAssemblyProject() {
  viewerRef.value?.saveAssemblyProjectJson?.()
}

function onOpenAssemblyProject() {
  assemblyProjectFileInputRef.value?.click()
}

function onAssemblyProjectFile(ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    try {
      const json = JSON.parse(reader.result as string)
      const apply = viewerRef.value?.applyAssemblyProjectJson
      if (!apply) return
      const res = apply(json)
      if (!res.ok) {
        alert(res.message)
        logger.warn('App', `Проект сборки: ${res.message}`)
      }
    } catch (e) {
      logger.error('App', 'Проект сборки: ошибка разбора JSON', e)
      alert('Не удалось разобрать файл (ожидается JSON проекта сборки).')
    }
  }
  reader.readAsText(file, 'utf-8')
}

async function onScreenshot3D() {
  logger.info('App', `Скриншот 3D: viewerRef=${!!viewerRef.value}, takeScreenshot=${!!viewerRef.value?.takeScreenshot}`)
  const url = await viewerRef.value?.takeScreenshot()
  if (url) {
    logger.info('App', `Скриншот 3D: получено изображение, длина=${url.length}`)
    screenshotSourceType.value = '3d'
    screenshotImageUrl.value = url
    screenshotSuggestedFileName.value = viewerRef.value?.getLoadedFileName?.() ?? null
    showScreenshotModal.value = true
  } else {
    logger.warn('App', 'Скриншот 3D: пустой результат (модель не загружена?)')
  }
}

/** Прямой рендер страницы PDF в изображение (как 3D takeScreenshot), без захвата экрана ОС */
function openReportGallery() {
  showReportGallery.value = true
}

function triggerScreenshotFlyAnimation(dataUrl: string) {
  const rect = toolbarRef.value?.getReportBadgeRect?.()
  if (!rect) return
  screenshotFlyAnim.value = {
    src: dataUrl,
    fromX: window.innerWidth / 2,
    fromY: window.innerHeight / 2,
    toX: rect.left + rect.width / 2,
    toY: rect.top + rect.height / 2,
  }
}

function onScreenshotFlyDone() {
  screenshotFlyAnim.value = null
  reportBasketPulse.value = true
  window.setTimeout(() => {
    reportBasketPulse.value = false
  }, 600)
}

function downloadScreenshotItem(item: ReportScreenshotItem) {
  const a = document.createElement('a')
  a.href = item.dataUrl
  a.download =
    item.type === '2d'
      ? build2dScreenshotFileName(item)
      : `3d-скриншот-${item.id.slice(-8)}.png`
  a.click()
}

function onScreenshotReorder(fromIndex: number, toIndex: number) {
  const arr = [...reportScreenshots.value]
  if (fromIndex < 0 || fromIndex >= arr.length || toIndex < 0 || toIndex >= arr.length) return
  const [item] = arr.splice(fromIndex, 1)
  arr.splice(toIndex, 0, item)
  reportScreenshots.value = arr
  logger.info('App', `Скриншот перемещён с ${fromIndex + 1} на ${toIndex + 1}`)
}

async function onScreenshot2d() {
  const pv = pdfViewerRef.value
  if (!pdfFile.value || !pv?.getCurrentPageImageUrlAsync) {
    alert('Откройте PDF и дождитесь загрузки страницы.')
    return
  }
  const pageNum = pv.getScreenshotPage?.() ?? 1
  const url = await pv.getCurrentPageImageUrlAsync(pageNum)
  if (!url) {
    alert('Не удалось подготовить скриншот страницы. Проверьте номер страницы и попробуйте снова.')
    return
  }
  screenshotSourceType.value = '2d'
  savedPdfPageForNextScreenshot.value = pageNum
  screenshotImageUrl.value = url
  screenshotSuggestedFileName.value = build2dScreenshotFileName({
    id: '',
    type: '2d',
    dataUrl: '',
    pageNumber: pageNum,
    albumCode: resolveAlbumCodeSnapshot(),
    moduleNumber: reportModuleNumber.value.trim(),
  })
  showScreenshotModal.value = true
  logger.info('App', `Скриншот 2D: стр. ${pageNum}, dataURL длина=${url.length}`)
}

function onScreenshotEditorClose(dataUrl: string | null) {
  if (dataUrl) {
    const type = screenshotSourceType.value
    if (editingScreenshotId.value) {
      const item = reportScreenshots.value.find((s) => s.id === editingScreenshotId.value)
      if (item) {
        item.dataUrl = dataUrl
        logger.info('App', `Редактор скриншота: скриншот "${item.id}" обновлён для отчёта`)
      }
    } else {
      const item: ReportScreenshotItem = {
        id: nextScreenshotId(),
        type,
        dataUrl,
      }
      if (type === '2d') {
        item.pdfFileName = pdfFile.value?.name ?? ''
        item.pageNumber =
          pdfViewerRef.value?.getScreenshotPage?.() ??
          savedPdfPageForNextScreenshot.value ??
          1
        item.albumCode = resolveAlbumCodeSnapshot()
        item.moduleNumber = reportModuleNumber.value.trim()
      }
      reportScreenshots.value.push(item)
      logger.info('App', `Редактор скриншота: добавлен ${type === '2d' ? '2D' : '3D'} скриншот в отчёт (всего ${reportScreenshots.value.length})`)
      void nextTick(() => triggerScreenshotFlyAnimation(dataUrl))
    }
  }
  editingScreenshotId.value = null
  showScreenshotModal.value = false
  screenshotImageUrl.value = null
  screenshotSuggestedFileName.value = null
}

function onScreenshotEditorFinalImage(dataUrl: string) {
  if (editingScreenshotId.value) {
    const item = reportScreenshots.value.find((s) => s.id === editingScreenshotId.value)
    if (item) {
      item.dataUrl = dataUrl
      logger.info('App', 'Редактор скриншота: сохранение на ПК — скриншот в панели обновлён')
    }
  }
  /* при новом скриншоте добавление в панель происходит при закрытии редактора */
}

function openEditorForScreenshot(item: ReportScreenshotItem) {
  showReportGallery.value = false
  editingScreenshotId.value = item.id
  screenshotSourceType.value = item.type
  screenshotImageUrl.value = item.dataUrl
  screenshotSuggestedFileName.value =
    item.type === '2d' ? build2dScreenshotFileName(item) : '3d-скриншот'
  showScreenshotModal.value = true
}

function removeScreenshotFromReport(item: ReportScreenshotItem) {
  reportScreenshots.value = reportScreenshots.value.filter((s) => s.id !== item.id)
  logger.info('App', `Скриншот удалён из отчёта, осталось ${reportScreenshots.value.length}`)
}

function moveScreenshotUp(index: number) {
  if (index <= 0) return
  const arr = [...reportScreenshots.value]
  ;[arr[index - 1], arr[index]] = [arr[index], arr[index - 1]]
  reportScreenshots.value = arr
}

function moveScreenshotDown(index: number) {
  const arr = reportScreenshots.value
  if (index >= arr.length - 1) return
  const next = [...arr]
  ;[next[index], next[index + 1]] = [next[index + 1], next[index]]
  reportScreenshots.value = next
}

async function fillProjectNameFromFirstSheet() {
  await refreshFirstSheetData()
}

function sanitizeFileName(s: string): string {
  return s.replace(/[<>:"/\\|?*\x00-\x1f]/g, '_').trim() || 'проект'
}

function resolveAlbumCodeSnapshot(): string {
  return reportProjectName.value.trim() || firstSheetData.value.projectCode?.trim() || ''
}

/** Имя файла 2D: шифр альбома + номер модуля + номер страницы PDF */
function build2dScreenshotFileName(item: ReportScreenshotItem): string {
  const rawCode = item.albumCode?.trim() || resolveAlbumCodeSnapshot()
  const rawMod = (item.moduleNumber ?? reportModuleNumber.value).trim()
  const page = item.pageNumber ?? 1
  const code = sanitizeFileName(rawCode) || 'альбом'
  const mod = sanitizeFileName(rawMod) || 'м0'
  const base = `${code}_M${mod}_стр${page}`
  const limited = base.length > 160 ? base.slice(0, 160) : base
  return `${limited}.png`
}

function collabAuthHeaders() {
  return collabToken.value ? { Authorization: `Bearer ${collabToken.value}` } : {}
}

function collabAuthFetch(path: string, init?: RequestInit) {
  const headers = new Headers(init?.headers || {})
  if (collabToken.value) headers.set('Authorization', `Bearer ${collabToken.value}`)
  if (!headers.has('Content-Type') && init?.body && !(init.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }
  return fetch(`${collabApiBase.value}${path}`, { ...(init || {}), headers })
}

async function collabErrorText(res: Response): Promise<string> {
  const msg = await res.text()
  try {
    const j = JSON.parse(msg) as { detail?: unknown }
    if (j.detail != null) return typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
  } catch {
    /* оставить сырой текст */
  }
  return msg
}

function filenameFromContentDisposition(cd: string | null, fallback: string): string {
  if (!cd) return fallback
  const m = /filename\*=(?:UTF-8'')?([^;\n]+)|filename="([^"]+)"/i.exec(cd)
  const raw = (m?.[1] || m?.[2] || '').trim().replace(/^UTF-8''/i, '')
  try {
    return decodeURIComponent(raw.replace(/^"|"$/g, '')) || fallback
  } catch {
    return raw.replace(/^"|"$/g, '') || fallback
  }
}

async function collabLoadAssetPairs() {
  if (!collabToken.value || !collabProjectId.value) {
    collabAssetPairs.value = []
    return
  }
  collabAssetPairsLoading.value = true
  try {
    const res = await collabAuthFetch(`/api/projects/${collabProjectId.value}/asset-pairs`)
    if (!res.ok) return
    const data = await res.json()
    collabAssetPairs.value = data.pairs || []
  } finally {
    collabAssetPairsLoading.value = false
  }
}

async function collabLoadSuggestions() {
  if (!collabToken.value || !collabProjectId.value) {
    collabAssetSuggestions.value = []
    return
  }
  collabSuggestLoading.value = true
  try {
    const res = await collabAuthFetch(`/api/projects/${collabProjectId.value}/asset-pairs/suggestions`)
    if (!res.ok) return
    const data = await res.json()
    collabAssetSuggestions.value = data.suggestions || []
  } finally {
    collabSuggestLoading.value = false
  }
}

async function collabAddSuggestedPair(s: Record<string, unknown>) {
  if (!collabProjectId.value) return
  const res = await collabAuthFetch(`/api/projects/${collabProjectId.value}/asset-pairs`, {
    method: 'POST',
    body: JSON.stringify({
      pdfAttachmentId: s.pdfAttachmentId,
      modelAttachmentId: s.modelAttachmentId,
      pdfStem: s.pdfStem,
      modelStem: s.modelStem,
    }),
  })
  if (!res.ok) throw new Error(await collabErrorText(res))
}

async function collabAddOneSuggestedPair(s: Record<string, unknown>) {
  collabBusy.value = true
  collabStatus.value = ''
  try {
    await collabAddSuggestedPair(s)
    await collabLoadAssetPairs()
    await collabLoadSuggestions()
    collabStatus.value = 'Связка добавлена'
  } catch (e) {
    collabStatus.value = e instanceof Error ? e.message : 'Ошибка'
  } finally {
    collabBusy.value = false
  }
}

async function collabAddAllSuggestedPairs() {
  const list = [...collabAssetSuggestions.value]
  if (!collabProjectId.value || list.length === 0) return
  collabBusy.value = true
  collabStatus.value = ''
  try {
    for (const s of list) {
      await collabAddSuggestedPair(s)
    }
    await collabLoadAssetPairs()
    await collabLoadSuggestions()
    collabStatus.value = `Добавлено связок: ${list.length}`
  } catch (e) {
    collabStatus.value = e instanceof Error ? e.message : 'Ошибка'
    await collabLoadAssetPairs()
    await collabLoadSuggestions()
  } finally {
    collabBusy.value = false
  }
}

async function collabDeleteAssetPair(pairId: string) {
  if (!collabProjectId.value) return
  collabBusy.value = true
  try {
    const res = await collabAuthFetch(`/api/projects/${collabProjectId.value}/asset-pairs/${pairId}`, {
      method: 'DELETE',
    })
    if (!res.ok) {
      collabStatus.value = await collabErrorText(res)
      return
    }
    await collabLoadAssetPairs()
    await collabLoadSuggestions()
  } finally {
    collabBusy.value = false
  }
}

async function collabOpenAssetPair(p: Record<string, unknown>) {
  const pid = collabProjectId.value
  if (!pid) return
  if (!(await confirmWorkspaceDiscard())) return
  const pdfAid = String(p.pdfAttachmentId ?? p.pdf_attachment_id ?? '').trim()
  const modelAid = String(p.modelAttachmentId ?? p.model_attachment_id ?? '').trim()
  collabBusy.value = true
  collabStatus.value = ''
  try {
    viewMode.value = 'split'
    if (pdfAid) {
      const res = await collabAuthFetch(`/api/projects/${pid}/attachments/${pdfAid}`)
      if (!res.ok) throw new Error(await collabErrorText(res))
      const blob = await res.blob()
      const fn = filenameFromContentDisposition(
        res.headers.get('Content-Disposition'),
        `${String(p.pdfStem ?? 'drawing')}.pdf`
      )
      const file = new File([blob], fn, { type: blob.type || 'application/pdf' })
      if (pdfFile.value?.url) URL.revokeObjectURL(pdfFile.value.url)
      pdfFile.value = { url: URL.createObjectURL(file), name: file.name }
    }
    if (modelAid && viewerRef.value) {
      const res = await collabAuthFetch(`/api/projects/${pid}/attachments/${modelAid}`)
      if (!res.ok) throw new Error(await collabErrorText(res))
      const blob = await res.blob()
      const fn = filenameFromContentDisposition(
        res.headers.get('Content-Disposition'),
        `${String(p.modelStem ?? 'model')}.glb`
      )
      const file = new File([blob], fn, { type: blob.type || 'application/octet-stream' })
      await viewerRef.value.loadModelFile(file)
    }
    if (!pdfAid && !modelAid) {
      collabStatus.value =
        'У связки нет вложений из чата — загрузите PDF и 3D в канал, затем добавьте связку по подсказке.'
      return
    }
    collabStatus.value = 'Пара загружена (режим «Разделение»)'
  } catch (e) {
    collabStatus.value = e instanceof Error ? e.message : 'Ошибка открытия пары'
  } finally {
    collabBusy.value = false
  }
}

function collabIsMemberSelf(m: { id: string }): boolean {
  const uid = collabUser.value?.id
  return Boolean(uid && uid === m.id)
}

function collabCanEditOtherMemberRole(m: { id: string }): boolean {
  return collabCanManageMembers.value && !collabIsMemberSelf(m)
}

function collabCanRemoveOtherMember(m: { id: string; role: string }): boolean {
  if (!collabCanManageMembers.value || collabIsMemberSelf(m)) return false
  if (m.role === 'gip' && collabCurrentProjectRole.value !== 'gip') return false
  return true
}

async function collabSetMemberRole(targetId: string, role: CollabMemberRole) {
  if (!collabProjectId.value) return
  const cur = collabMembers.value.find((x) => x.id === targetId)
  if (cur && cur.role === role) return
  collabBusy.value = true
  collabStatus.value = ''
  try {
    const res = await collabAuthFetch(`/api/projects/${collabProjectId.value}/members/${targetId}`, {
      method: 'PATCH',
      body: JSON.stringify({ role }),
    })
    if (!res.ok) throw new Error(await collabErrorText(res))
    await collabLoadMembers()
    collabStatus.value = 'Роль участника обновлена'
  } catch (e) {
    collabStatus.value = `Роль: ${e instanceof Error ? e.message : 'ошибка'}`
    await collabLoadMembers()
  } finally {
    collabBusy.value = false
  }
}

function onCollabMemberRoleChange(m: { id: string; role: string }, ev: Event) {
  const v = (ev.target as HTMLSelectElement).value
  if (!isCollabMemberRole(v)) return
  void collabSetMemberRole(m.id, v)
}

async function collabLeaveProject() {
  const uid = collabUser.value?.id
  if (!collabProjectId.value || !uid) return
  if (!confirm('Покинуть этот проект?')) return
  collabBusy.value = true
  collabStatus.value = ''
  const leftId = collabProjectId.value
  try {
    const res = await collabAuthFetch(`/api/projects/${leftId}/members/${uid}`, { method: 'DELETE' })
    if (!res.ok) throw new Error(await collabErrorText(res))
    await collabLoadProjects()
    if (!collabProjects.value.some((p: { id: string }) => p.id === leftId)) {
      collabProjectId.value = collabProjects.value[0]?.id ?? ''
      collabChannelId.value = ''
      collabMessages.value = []
      if (collabProjectId.value) {
        await collabLoadChannels()
        await collabLoadMessages()
        await collabLoadMembers()
        collabConnectWs()
      } else {
        collabChannels.value = []
        collabMembers.value = []
        collabDisconnectWs()
      }
    } else {
      await collabLoadMembers()
    }
    collabStatus.value = 'Вы вышли из проекта'
  } catch (e) {
    collabStatus.value = `Выход: ${e instanceof Error ? e.message : 'ошибка'}`
  } finally {
    collabBusy.value = false
  }
}

async function collabKickMember(targetId: string) {
  if (!collabProjectId.value || collabIsMemberSelf({ id: targetId })) return
  if (!confirm('Исключить участника из проекта?')) return
  collabBusy.value = true
  collabStatus.value = ''
  try {
    const res = await collabAuthFetch(`/api/projects/${collabProjectId.value}/members/${targetId}`, {
      method: 'DELETE',
    })
    if (!res.ok) throw new Error(await collabErrorText(res))
    await collabLoadMembers()
    collabStatus.value = 'Участник исключён'
  } catch (e) {
    collabStatus.value = `Исключение: ${e instanceof Error ? e.message : 'ошибка'}`
    await collabLoadMembers()
  } finally {
    collabBusy.value = false
  }
}

function xhrPostFormData(
  fullUrl: string,
  formData: FormData,
  onUploadProgress: (percent: number) => void
): Promise<{ ok: boolean; status: number; text: () => Promise<string> }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', fullUrl)
    if (collabToken.value) xhr.setRequestHeader('Authorization', `Bearer ${collabToken.value}`)
    xhr.upload.onprogress = (ev) => {
      if (ev.lengthComputable && ev.total > 0) {
        onUploadProgress(Math.min(100, Math.round((ev.loaded / ev.total) * 100)))
      }
    }
    xhr.onload = () => {
      const body = xhr.responseText ?? ''
      resolve({
        ok: xhr.status >= 200 && xhr.status < 300,
        status: xhr.status,
        text: async () => body,
      })
    }
    xhr.onerror = () => reject(new Error('Сеть: не удалось загрузить файл'))
    xhr.send(formData)
  })
}

async function collabDownloadAttachment(att: { id: string; file_name?: string | null; fileName?: string | null }) {
  if (!collabProjectId.value || !collabToken.value) {
    collabStatus.value = 'Войдите в чат, чтобы скачать файл'
    return
  }
  try {
    const path = `/api/projects/${collabProjectId.value}/attachments/${att.id}`
    const res = await collabAuthFetch(path)
    if (!res.ok) throw new Error(await res.text())
    const blob = await res.blob()
    const raw = att.file_name || att.fileName || 'attachment'
    const name = String(raw).replace(/[<>:"/\\|?*\x00-\x1f]/g, '_').trim() || 'attachment'
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = name
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    collabStatus.value = `Скачивание: ${e instanceof Error ? e.message : 'ошибка'}`
  }
}

function collabAttachmentDisplayName(
  att: { file_name?: string | null; fileName?: string | null },
  messageBody?: string
): string {
  const fromApi = att.file_name || att.fileName
  if (typeof fromApi === 'string' && fromApi.trim()) return fromApi.trim()
  const m = messageBody?.match(/^Вложение:\s*(.+)$/i)
  if (m?.[1]?.trim()) return m[1].trim()
  return 'Файл'
}

/** Текст сообщения в ленте: без дубля «Вложение: имя», если имя уже есть во вложениях */
function collabMessageBodyForDisplay(m: { body?: unknown; attachments?: unknown }) {
  const body = typeof m.body === 'string' ? m.body.trim() : ''
  const atts = m.attachments
  if (!body || !Array.isArray(atts) || atts.length !== 1) return body
  const name = collabAttachmentDisplayName(atts[0] as { file_name?: string; fileName?: string }, body)
  const dup = new RegExp(`^Вложение:\\s*${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*$`, 'i')
  if (dup.test(body)) return ''
  return body
}

async function collabOpenAttachmentPreview(att: { id: string; file_name?: string | null; fileName?: string | null }) {
  if (!collabProjectId.value || !collabToken.value) {
    collabStatus.value = 'Войдите в чат'
    return
  }
  try {
    const path = `/api/projects/${collabProjectId.value}/attachments/${att.id}`
    const res = await collabAuthFetch(path)
    if (!res.ok) throw new Error(await res.text())
    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    window.open(url, '_blank', 'noopener,noreferrer')
    setTimeout(() => URL.revokeObjectURL(url), 120_000)
  } catch (e) {
    collabStatus.value = `Открытие файла: ${e instanceof Error ? e.message : 'ошибка'}`
  }
}

async function collabLoadMe() {
  if (!collabToken.value) return
  const res = await collabAuthFetch('/api/me')
  if (!res.ok) throw new Error('auth failed')
  const data = await res.json()
  collabUser.value = data.user
}

async function collabLoadProjects() {
  const res = await collabAuthFetch('/api/projects')
  if (!res.ok) throw new Error(await res.text())
  const data = await res.json()
  collabProjects.value = data.projects || []
  if (!collabProjectId.value && collabProjects.value.length > 0) {
    collabProjectId.value = collabProjects.value[0].id
  }
}

async function collabLoadChannels() {
  if (!collabProjectId.value) return
  const res = await collabAuthFetch(`/api/projects/${collabProjectId.value}/channels`)
  if (!res.ok) throw new Error(await res.text())
  const data = await res.json()
  collabChannels.value = data.channels || []
  if (!collabChannelId.value && collabChannels.value.length > 0) {
    collabChannelId.value = collabChannels.value[0].id
  }
}

async function collabLoadMessages() {
  if (!collabProjectId.value || !collabChannelId.value) return
  const res = await collabAuthFetch(`/api/projects/${collabProjectId.value}/channels/${collabChannelId.value}/messages?limit=100`)
  if (!res.ok) throw new Error(await res.text())
  const data = await res.json()
  collabMessages.value = data.messages || []
}

function collabDisconnectWs() {
  collabWsYjsEnabled = false
  if (collabNotesAwareness.value && collabWs?.readyState === WebSocket.OPEN) {
    try {
      collabNotesAwareness.value.setLocalState(null)
    } catch {
      /* noop */
    }
  }
  if (collabWs) {
    collabWs.close()
    collabWs = null
  }
  if (collabNotesAwareness.value) {
    collabNotesAwareness.value = null
  }
  if (collabNotesDoc.value) {
    try {
      collabNotesDoc.value.destroy()
    } catch {
      /* noop */
    }
    collabNotesDoc.value = null
  }
}

function collabConnectWs() {
  collabDisconnectWs()
  if (!collabToken.value || !collabProjectId.value) return

  collabWsYjsEnabled = false

  const doc = new Y.Doc()
  collabNotesDoc.value = doc

  const awareness = new Awareness(doc)
  collabNotesAwareness.value = awareness
  {
    const name = collabUser.value?.displayName?.trim() || collabUser.value?.email || 'Участник'
    awareness.setLocalStateField('user', {
      name,
      color: collabAwarenessUserColor(awareness.clientID),
    })
  }

  doc.on('update', (update: Uint8Array, origin: unknown) => {
    if (origin === 'remote' || origin === 'sync') return
    if (!collabWsYjsEnabled || !collabWs || collabWs.readyState !== WebSocket.OPEN) return
    collabWs.send(JSON.stringify({ type: 'yjs.update', update: uint8ToBase64(update) }))
  })

  awareness.on('update', ({ added, updated, removed }, origin: unknown) => {
    if (origin === 'remote') return
    if (!collabWsYjsEnabled || !collabWs || collabWs.readyState !== WebSocket.OPEN) return
    const changed = Array.from(new Set([...added, ...updated, ...removed]))
    if (changed.length === 0) return
    const u = encodeAwarenessUpdate(awareness, changed)
    collabWs.send(JSON.stringify({ type: 'yjs.awareness', update: uint8ToBase64(u) }))
  })

  const wsBase = collabApiBase.value.replace(/^http/, 'ws')
  collabWs = new WebSocket(`${wsBase}/api/projects/${collabProjectId.value}/ws`)
  collabWs.onopen = () => {
    const t = collabToken.value
    if (collabWs && collabWs.readyState === WebSocket.OPEN && t) {
      collabWs.send(JSON.stringify({ type: 'ws.auth', token: t }))
    }
  }
  collabWs.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data)
      if (msg.type === 'ws.connected') {
        collabWsYjsEnabled = true
      }
      if (msg.type === 'yjs.sync' && collabNotesDoc.value && Array.isArray(msg.updates)) {
        for (const u of msg.updates as string[]) {
          Y.applyUpdate(collabNotesDoc.value, base64ToUint8(u), 'sync')
        }
        return
      }
      if (msg.type === 'yjs.update' && collabNotesDoc.value && typeof msg.update === 'string') {
        Y.applyUpdate(collabNotesDoc.value, base64ToUint8(msg.update), 'remote')
        return
      }
      if (msg.type === 'yjs.awareness' && collabNotesAwareness.value && typeof msg.update === 'string') {
        applyAwarenessUpdate(collabNotesAwareness.value, base64ToUint8(msg.update), 'remote')
        return
      }
      if (msg.type === 'telemost.join' && typeof msg.joinUrl === 'string' && msg.joinUrl) {
        const title = typeof msg.title === 'string' && msg.title.trim() ? msg.title.trim() : 'Звонок проекта'
        telemostCallBanner.value = { title, joinUrl: msg.joinUrl }
        return
      }
      if (msg.type === 'chat.message.created' && msg.channelId === collabChannelId.value) {
        let incoming = msg.message as Record<string, unknown>
        const u = collabUser.value
        const aid = String(incoming.author_id ?? '')
        if (u?.id && aid && u.id === aid && !incoming.author) {
          const proj = collabProjects.value.find((x: { id: string }) => x.id === collabProjectId.value)
          const myRole = typeof proj?.role === 'string' && proj.role in COLLAB_ROLE_LABELS ? proj.role : undefined
          incoming = {
            ...incoming,
            author: { id: u.id, email: u.email, displayName: u.displayName, display_name: u.displayName },
            authorDisplayName: u.displayName,
            authorEmail: u.email,
            ...(myRole ? { authorProjectRole: myRole } : {}),
          }
        }
        collabMessages.value.push(incoming)
      }
    } catch {
      // noop
    }
  }
}

async function collabBootstrap() {
  await collabLoadMe()
  await collabLoadProjects()
  await collabLoadChannels()
  await collabLoadMessages()
  await collabLoadMembers()
  collabConnectWs()
  await collabLoadAssetPairs()
  await collabLoadSuggestions()
}

async function collabLoadMembers() {
  if (!collabToken.value || !collabProjectId.value) {
    collabMembers.value = []
    return
  }
  collabMembersLoading.value = true
  try {
    const res = await collabAuthFetch(`/api/projects/${collabProjectId.value}/members`)
    if (!res.ok) {
      collabMembers.value = []
      return
    }
    const data = await res.json()
    collabMembers.value = data.members || []
  } finally {
    collabMembersLoading.value = false
  }
}

async function collabSubmitAuth() {
  collabBusy.value = true
  collabStatus.value = ''
  try {
    const path = collabAuthMode.value === 'login' ? '/api/auth/login' : '/api/auth/register'
    const payload: Record<string, string> = {
      email: collabEmail.value.trim(),
      password: collabPassword.value,
    }
    if (collabAuthMode.value === 'register') payload.display_name = collabDisplayName.value.trim() || 'User'
    const res = await fetch(`${collabApiBase.value}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!res.ok) throw new Error(await res.text())
    const data = await res.json()
    collabToken.value = data.token || ''
    localStorage.setItem('collabToken', collabToken.value)
    await collabBootstrap()
    collabStatus.value = 'Подключено'
  } catch (e) {
    collabStatus.value = collabFetchErrorMessage(e)
  } finally {
    collabBusy.value = false
  }
}

async function collabSendMessage() {
  const body = collabMessageText.value.trim()
  if (!collabProjectId.value || !collabChannelId.value) {
    collabStatus.value = 'Выберите проект и канал'
    return
  }
  if (!body) return
  collabBusy.value = true
  collabSendingText.value = true
  try {
    const res = await collabAuthFetch(`/api/projects/${collabProjectId.value}/channels/${collabChannelId.value}/messages`, {
      method: 'POST',
      body: JSON.stringify({ body }),
    })
    if (!res.ok) throw new Error(await res.text())
    collabMessageText.value = ''
  } catch (e) {
    collabStatus.value = `Ошибка отправки: ${e instanceof Error ? e.message : 'send'}`
  } finally {
    collabSendingText.value = false
    collabBusy.value = false
  }
}

function onCollabComposerKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    if (!collabBusy.value && !collabSendingText.value) collabSendMessage()
  }
}

async function collabAttachFile() {
  if (!collabProjectId.value || !collabChannelId.value) {
    collabStatus.value = 'Сначала выберите проект и канал'
    return
  }
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = '.png,.jpg,.jpeg,.webp,.gif,.bmp,.tif,.tiff,.pdf,.xls,.xlsx,.xlsm,.csv,.dwg,.dxf,.cdw,.spw,.m3d,.a3d,.frw,.rvt,.rfa,.step,.stp,.iges,.igs,.stl,.glb,.gltf'
  input.onchange = async () => {
    const file = input.files?.[0]
    if (!file) return
    collabBusy.value = true
    collabAttachPct.value = 0
    collabStatus.value = ''
    try {
      const fd = new FormData()
      fd.append('file', file, file.name)
      fd.append('source', 'chat')
      fd.append('context_json', JSON.stringify({ origin: 'chat-compose' }))
      const uploadUrl = `${collabApiBase.value}/api/projects/${collabProjectId.value}/attachments/upload`
      const up = await xhrPostFormData(uploadUrl, fd, (p) => {
        collabAttachPct.value = p
      })
      const upText = await up.text()
      if (!up.ok) throw new Error(upText)
      const upData = JSON.parse(upText) as { attachment?: { id: string } }
      const attachmentId = upData?.attachment?.id
      if (!attachmentId) throw new Error('attachment id missing')
      collabAttachPct.value = null
      collabStatus.value = 'Отправка сообщения…'
      const body = collabMessageText.value.trim() || `Вложение: ${file.name}`
      const msg = await collabAuthFetch(`/api/projects/${collabProjectId.value}/channels/${collabChannelId.value}/messages`, {
        method: 'POST',
        body: JSON.stringify({
          body,
          attachmentIds: [attachmentId],
        }),
      })
      if (!msg.ok) throw new Error(await msg.text())
      collabMessageText.value = ''
      collabStatus.value = `Файл отправлен: ${file.name}`
    } catch (e) {
      collabStatus.value = `Ошибка вложения: ${e instanceof Error ? e.message : 'upload'}`
    } finally {
      collabBusy.value = false
      collabAttachPct.value = null
    }
  }
  input.click()
}

async function onCollabProjectChange() {
  collabChannelId.value = ''
  collabMessages.value = []
  await collabLoadChannels()
  await collabLoadMessages()
  await collabLoadMembers()
  collabConnectWs()
  await collabLoadTelemost()
  loadTelemostExtraRooms()
  await collabLoadAssetPairs()
  await collabLoadSuggestions()
}

async function onCollabChannelChange() {
  await collabLoadMessages()
}

async function collabCreateProject() {
  const name = collabNewProjectName.value.trim()
  if (!name) {
    collabStatus.value = 'Введите название проекта'
    return
  }
  collabBusy.value = true
  collabStatus.value = ''
  try {
    const res = await collabAuthFetch('/api/projects', {
      method: 'POST',
      body: JSON.stringify({ name }),
    })
    if (!res.ok) throw new Error(await res.text())
    const data = await res.json()
    const proj = data.project
    if (!proj?.id) throw new Error('Ответ без id проекта')
    await collabLoadProjects()
    collabProjectId.value = String(proj.id)
    collabNewProjectName.value = ''
    collabChannelId.value = ''
    collabMessages.value = []
    await collabLoadChannels()
    if (!collabChannelId.value && collabChannels.value.length > 0) {
      collabChannelId.value = collabChannels.value[0].id
    }
    await collabLoadMessages()
    await collabLoadMembers()
    collabConnectWs()
    await collabLoadTelemost()
    await collabLoadAssetPairs()
    await collabLoadSuggestions()
    collabStatus.value = `Проект создан. Сразу доступен канал «Общий» (если не переименован).`
  } catch (e) {
    collabStatus.value = `Ошибка создания проекта: ${e instanceof Error ? e.message : 'create'}`
  } finally {
    collabBusy.value = false
  }
}

async function collabCreateChannel() {
  if (!collabProjectId.value) {
    collabStatus.value = 'Сначала выберите или создайте проект'
    return
  }
  const name = collabNewChannelName.value.trim()
  if (!name) {
    collabStatus.value = 'Введите название канала'
    return
  }
  collabBusy.value = true
  collabStatus.value = ''
  try {
    const res = await collabAuthFetch(`/api/projects/${collabProjectId.value}/channels`, {
      method: 'POST',
      body: JSON.stringify({ name, kind: 'general' }),
    })
    if (!res.ok) throw new Error(await res.text())
    const data = await res.json()
    const ch = data.channel
    await collabLoadChannels()
    if (ch?.id) collabChannelId.value = String(ch.id)
    await collabLoadMessages()
    collabNewChannelName.value = ''
    collabStatus.value = `Канал «${name}» создан`
  } catch (e) {
    collabStatus.value = `Ошибка канала: ${e instanceof Error ? e.message : 'create'}`
  } finally {
    collabBusy.value = false
  }
}

async function collabInviteMember() {
  if (!collabProjectId.value) {
    collabStatus.value = 'Выберите проект'
    return
  }
  const email = collabInviteEmail.value.trim().toLowerCase()
  if (!email || !email.includes('@')) {
    collabStatus.value = 'Укажите email участника'
    return
  }
  collabBusy.value = true
  collabStatus.value = ''
  try {
    const res = await collabAuthFetch(`/api/projects/${collabProjectId.value}/members`, {
      method: 'POST',
      body: JSON.stringify({ email, role: collabInviteRole.value }),
    })
    if (!res.ok) throw new Error(await collabErrorText(res))
    collabInviteEmail.value = ''
    collabStatus.value = `Добавлено: ${email} (${collabInviteRole.value})`
    await collabLoadMembers()
  } catch (e) {
    collabStatus.value = `Приглашение: ${e instanceof Error ? e.message : 'ошибка'}`
  } finally {
    collabBusy.value = false
  }
}

function collabLogout() {
  collabDisconnectWs()
  collabToken.value = ''
  collabUser.value = null
  collabProjects.value = []
  collabProjectId.value = ''
  collabChannels.value = []
  collabChannelId.value = ''
  collabMessages.value = []
  collabMembers.value = []
  collabAssetPairs.value = []
  collabAssetSuggestions.value = []
  localStorage.removeItem('collabToken')
}

function dataUrlToBlob(dataUrl: string): Blob {
  const [meta, base64] = dataUrl.split(',', 2)
  const mimeMatch = /data:([^;]+)/.exec(meta)
  const mime = mimeMatch ? mimeMatch[1] : 'image/png'
  const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0))
  return new Blob([bytes], { type: mime })
}

async function sendScreenshotToChat(item: ReportScreenshotItem): Promise<boolean> {
  if (!collabProjectId.value || !collabChannelId.value) {
    collabStatus.value = 'Сначала выберите проект и канал'
    return false
  }
  collabBusy.value = true
  try {
    const blob = dataUrlToBlob(item.dataUrl)
    const fd = new FormData()
    const uploadName =
      item.type === '2d' ? build2dScreenshotFileName(item) : `${item.type}-${item.id}.png`
    fd.append('file', blob, uploadName)
    fd.append('source', item.type === '2d' ? 'pdf' : 'viewer3d')
    fd.append(
      'context_json',
      JSON.stringify({
        screenshotType: item.type,
        pdfFileName: item.pdfFileName || null,
        pageNumber: item.pageNumber || null,
      })
    )
    const up = await collabAuthFetch(`/api/projects/${collabProjectId.value}/attachments/upload`, {
      method: 'POST',
      body: fd,
    })
    if (!up.ok) throw new Error(await up.text())
    const upData = await up.json()
    const attachmentId = upData?.attachment?.id
    const text = item.type === '2d'
      ? `Скриншот 2D${item.pageNumber ? `, стр. ${item.pageNumber}` : ''}`
      : 'Скриншот 3D'
    const msg = await collabAuthFetch(`/api/projects/${collabProjectId.value}/channels/${collabChannelId.value}/messages`, {
      method: 'POST',
      body: JSON.stringify({
        body: text,
        attachmentIds: attachmentId ? [attachmentId] : [],
      }),
    })
    if (!msg.ok) throw new Error(await msg.text())
    collabStatus.value = 'Скриншот отправлен в чат'
    return true
  } catch (e) {
    collabStatus.value = `Ошибка отправки скриншота: ${e instanceof Error ? e.message : 'upload'}`
    return false
  } finally {
    collabBusy.value = false
  }
}

async function onScreenshotEditorSendToChat(dataUrl: string) {
  const type = screenshotSourceType.value
  const item: ReportScreenshotItem = {
    id: nextScreenshotId(),
    type,
    dataUrl,
    pdfFileName: type === '2d' ? pdfFile.value?.name ?? '' : undefined,
    pageNumber:
      type === '2d'
        ? pdfViewerRef.value?.getScreenshotPage?.() ?? savedPdfPageForNextScreenshot.value ?? 1
        : undefined,
    albumCode: type === '2d' ? resolveAlbumCodeSnapshot() : undefined,
    moduleNumber: type === '2d' ? reportModuleNumber.value.trim() : undefined,
  }
  const ok = await sendScreenshotToChat(item)
  if (ok) {
    editingScreenshotId.value = null
    showScreenshotModal.value = false
    screenshotImageUrl.value = null
    screenshotSuggestedFileName.value = null
  }
}

function closeScreenshotModal() {
  showScreenshotModal.value = false
  screenshotImageUrl.value = null
  screenshotSuggestedFileName.value = null
}

const showPdfPanel = () => viewMode.value === '2d' || viewMode.value === 'split'
const show3dPanel = () => viewMode.value === '3d' || viewMode.value === 'split'
const showLogPanel = () => viewMode.value === 'log'

onMounted(() => {
  try {
    const sw = localStorage.getItem(WORKSPACE_LS_SIDEBAR)
    const rw = localStorage.getItem(WORKSPACE_LS_RIGHT)
    const cw = localStorage.getItem(WORKSPACE_LS_CENTER_PDF)
    if (sw) {
      sidebarWidth.value = clampWorkspaceWidth(Number(sw), 160, 480)
      sidebarWidthBeforeCollapse = sidebarWidth.value
    }
    if (rw) {
      rightPanelWidth.value = clampWorkspaceWidth(Number(rw), 260, 720)
      rightPanelWidthBeforeCollapse = rightPanelWidth.value
    }
    if (cw) centerPdfWidth.value = clampWorkspaceWidth(Number(cw), 160, 1200)
    const diskCol = localStorage.getItem(WORKSPACE_LS_DISK_COLLAPSED)
    const chatCol = localStorage.getItem(WORKSPACE_LS_CHAT_COLLAPSED)
    if (diskCol === '1') diskPanelCollapsed.value = true
    if (chatCol === '1') chatPanelCollapsed.value = true
  } catch {
    /* noop */
  }
  window.addEventListener('dragover', onDragOver)
  window.addEventListener('drop', onDrop)
  window.addEventListener('dragleave', onDragLeave)
  collabDayTimer = setInterval(() => {
    collabDateTick.value++
  }, 60_000)
  if (collabToken.value) {
    collabBootstrap().catch((e) => {
      collabStatus.value = collabFetchErrorMessage(e)
      collabToken.value = ''
      localStorage.removeItem('collabToken')
    })
  }
  const ys = new URLSearchParams(window.location.search)
  const yErr = ys.get('yadisk_err')
  const yOk = ys.get('yadisk_oauth')
  if (yErr || yOk) {
    const u = new URL(window.location.href)
    u.searchParams.delete('yadisk_err')
    u.searchParams.delete('yadisk_oauth')
    const qs = u.searchParams.toString()
    window.history.replaceState({}, '', `${u.pathname}${qs ? `?${qs}` : ''}${u.hash}`)
  }
  if (yErr) {
    try {
      yandexDiskStatus.value = `OAuth: ${decodeURIComponent(yErr)}`
    } catch {
      yandexDiskStatus.value = `OAuth: ${yErr}`
    }
  } else if (yOk === '1') {
    void finishYandexOAuthFromRedirect()
  }
  void checkYandexOAuthSession()
  window.addEventListener('keydown', onWorkspaceKeydown)
  window.addEventListener('beforeunload', onBeforeUnload)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onWorkspaceKeydown)
  window.removeEventListener('beforeunload', onBeforeUnload)
  window.removeEventListener('dragover', onDragOver)
  window.removeEventListener('drop', onDrop)
  window.removeEventListener('dragleave', onDragLeave)
  if (collabDayTimer != null) {
    clearInterval(collabDayTimer)
    collabDayTimer = null
  }
  collabDisconnectWs()
})
</script>

<template>
  <div class="app" :class="{ 'is-dragging-file': isDraggingFile }">
    <div v-if="isDraggingFile" class="drop-overlay">Отпустите файл (PDF или 3D)</div>
    <input
      ref="assemblyProjectFileInputRef"
      type="file"
      accept=".json,application/json"
      class="sr-only"
      aria-hidden="true"
      tabindex="-1"
      style="position: absolute; width: 0; height: 0; opacity: 0; pointer-events: none"
      @change="onAssemblyProjectFile"
    />
    <ViewerToolbar
      ref="toolbarRef"
      :view-mode="viewMode"
      :workspace-mode="workspaceMode"
      :report-screenshot-count="reportScreenshots.length"
      :report-basket-pulse="reportBasketPulse"
      @update:view-mode="onViewModeChange"
      @update:workspace-mode="workspaceMode = $event"
      @open-pdf="onOpenPdf"
      @open-file="onOpenFile"
      @open-report-gallery="openReportGallery"
      @export-report="onExportReport"
      @export-report-email="onExportReportEmail"
      @export-report-chat="onExportReportChat"
      @save-assembly-project="onSaveAssemblyProject"
      @open-assembly-project="onOpenAssemblyProject"
      @save-pdf="onWorkspaceSave"
      @save-pdf-as="onWorkspaceSaveAs"
      @save-3d="onWorkspaceSave"
      @save-3d-as="onWorkspaceSaveAs"
      @show-logs="onShowLogs"
      @telemost-join-project="telemostJoinFromMenu"
      @telemost-create-meeting="telemostCreateMeetingFromMenu"
      @open-settings="onOpenSettings"
    />
    <div v-if="telemostCallBanner" class="telemost-call-banner" role="status">
      <span>Звонок: {{ telemostCallBanner.title }}</span>
      <a
        v-if="telemostCallBanner.joinUrl"
        class="telemost-call-banner-link"
        :href="telemostCallBanner.joinUrl"
        target="_blank"
        rel="noopener noreferrer"
      >
        Подключиться
      </a>
      <button type="button" class="telemost-call-banner-dismiss" @click="dismissTelemostBanner">×</button>
    </div>
    <div v-if="saveActionToast" class="workspace-save-toast">{{ saveActionToast }}</div>
    <div v-if="workspaceMode === 'engineering'" class="workspace">
      <div
        class="workspace-side-rail workspace-side-rail--left"
        :style="{
          flex: `0 0 ${effectiveLeftRailWidth}px`,
          width: `${effectiveLeftRailWidth}px`,
          minWidth: `${effectiveLeftRailWidth}px`,
          maxWidth: `${effectiveLeftRailWidth}px`,
        }"
      >
      <aside
        class="ide-sidebar ide-sidebar--disk"
        :class="{ 'ide-sidebar--collapsed': diskPanelCollapsed }"
        aria-label="Файлы проекта на Яндекс.Диске"
      >
        <div class="ide-sidebar-header">
          <template v-if="!diskPanelCollapsed">
            <span class="ide-sidebar-title">Яндекс.Диск</span>
            <span class="ide-sidebar-pill">API</span>
          </template>
          <div class="ide-panel-head-actions">
            <div v-if="!diskPanelCollapsed" class="ide-panel-width-controls" title="Ширина панели">
              <button
                type="button"
                class="ide-panel-width-btn"
                title="Уже"
                @click="nudgeDiskPanelWidth(-PANEL_NUDGE_STEP_PX)"
              >
                ‹
              </button>
              <button
                type="button"
                class="ide-panel-width-btn"
                title="Шире"
                @click="nudgeDiskPanelWidth(PANEL_NUDGE_STEP_PX)"
              >
                ›
              </button>
            </div>
            <button
              type="button"
              class="ide-panel-collapse-btn"
              :title="diskPanelCollapsed ? 'Развернуть панель диска' : 'Свернуть панель диска'"
              @click="toggleDiskPanel"
            >
              {{ diskPanelCollapsed ? '⟩' : '⟨' }}
            </button>
          </div>
        </div>
        <template v-if="!diskPanelCollapsed">
        <div class="ide-disk-actions">
          <div class="ide-disk-row ide-disk-row--wrap">
            <button
              type="button"
              class="ide-disk-btn ide-disk-btn-primary"
              :disabled="!yandexDiskUrlInput.trim()"
              @click="loadYandexPublicTree"
            >
              Публичная
            </button>
            <button type="button" class="ide-disk-btn ide-disk-btn-primary" @click="startYandexOAuth">OAuth</button>
            <template v-if="yandexDiskConnected">
              <button type="button" class="ide-disk-btn" @click="refreshYandexDisk">Обновить</button>
              <button type="button" class="ide-disk-btn ide-disk-btn-danger" @click="disconnectYandexDisk">Сбросить</button>
            </template>
          </div>
          <div class="ide-disk-row">
            <input v-model="yandexDiskUrlInput" type="url" class="ide-disk-url-input" placeholder="Публичная ссылка на папку" />
            <button type="button" class="ide-disk-btn" @click="openYandexDiskUrl">В браузере</button>
          </div>
          <div class="ide-disk-status">{{ yandexDiskStatus }}</div>
          <p v-if="yandexDiskMode === 'oauth'" class="ide-disk-hint-mini">Полный доступ к диску (OAuth). Ссылка нужна только для режима «Публичная».</p>
        </div>
        <div class="ide-tree-tabs" role="tablist" aria-label="Деревья файлов">
          <button
            type="button"
            class="ide-tree-tab"
            :class="{ 'is-active': diskTreeTab === 'pdf' }"
            role="tab"
            :aria-selected="diskTreeTab === 'pdf'"
            @click="diskTreeTab = 'pdf'"
          >
            Дерево PDF
          </button>
          <button
            type="button"
            class="ide-tree-tab"
            :class="{ 'is-active': diskTreeTab === '3d' }"
            role="tab"
            :aria-selected="diskTreeTab === '3d'"
            @click="diskTreeTab = '3d'"
          >
            Дерево 3D
          </button>
        </div>
        <div class="ide-tree" role="tree">
          <div v-if="!yandexDiskRootNodes.length" class="ide-tree-empty">
            Укажите публичную ссылку и нажмите «Публичная», либо «OAuth» для всего диска.
          </div>
          <YandexDiskTree
            v-else
            :nodes="yandexDiskRootNodes"
            :tab="diskTreeTab"
            :show-file="diskTreeTab === 'pdf' ? isPdfTreeFile : isModelTreeFile"
            @toggle-dir="onYandexDiskToggleDir($event)"
            @open-file="openDiskTreeFile"
          />
        </div>
        <p class="ide-sidebar-hint">
          Клик по файлу открывает его во вьювере. Для STEP/IGES в той же папке ищется готовый GLB с тем же именем.
        </p>
        </template>
        <button
          v-else
          type="button"
          class="ide-sidebar-collapsed-label"
          title="Развернуть Яндекс.Диск"
          @click="toggleDiskPanel"
        >
          Диск
        </button>
      </aside>
      <div
        v-show="!diskPanelCollapsed"
        class="workspace-splitter workspace-splitter--in-rail"
        title="Перетащите для изменения ширины"
        @mousedown.prevent="onWorkspaceSplitterDown('left', $event)"
      />
      </div>
      <div ref="workspaceContentRef" class="content" :class="'mode-' + viewMode">
        <div
          v-show="showPdfPanel()"
          class="panel pdf-panel"
          :style="
            viewMode === 'split'
              ? {
                  flex: `0 0 ${centerPdfWidth}px`,
                  width: `${centerPdfWidth}px`,
                  maxWidth: '85%',
                }
              : undefined
          "
        >
        <div class="pdf-panel-header">
          <span class="pdf-panel-title">2D PDF</span>
          <div class="pdf-panel-actions">
            <button type="button" class="pdf-panel-btn pdf-panel-btn-open" title="Выбрать PDF на диске" @click="onOpenPdf">
              Открыть PDF
            </button>
            <button type="button" class="pdf-panel-btn" :disabled="!pdfFile" @click="onScreenshot2d">Скриншот 2D</button>
          </div>
        </div>
        <PdfViewer
          v-if="pdfFile"
          ref="pdfViewerRef"
          :pdf-url="pdfFile.url"
          :pdf-name="pdfFile.name"
          :markup-sidecar-bytes="pdfFile.markupSidecarBytes ?? null"
          @open-pdf="onOpenPdf"
          @markup-dirty="onPdfMarkupDirty"
        />
        <div v-else class="panel-placeholder panel-placeholder--pdf">
          <span>Меню «Файл» → «Открыть 2D PDF», дерево Яндекс.Диска или перетащите PDF сюда</span>
        </div>
        </div>
        <div
          v-if="viewMode === 'split'"
          class="workspace-splitter workspace-splitter--2d3d"
          title="Соотношение панелей 2D и 3D"
          @mousedown.prevent="onCenterSplitterDown"
        />
        <div
          v-show="show3dPanel()"
          class="panel viewer-panel"
          :style="viewMode === 'split' ? { flex: '1 1 auto', minWidth: '180px', minHeight: 0 } : undefined"
        >
        <Viewer3D
          ref="viewerRef"
          :section-mode="sectionMode"
          :section-active="sectionActive"
          :section-offset="sectionOffset"
          :measure-mode="measureMode"
          :measure-snap-mode="measureSnapMode"
          :measure-type="measureType"
          @section-active="onSectionActive"
          @section-inactive="onSectionInactive"
          @section-offset-changed="onSectionOffsetChanged"
          @section-mode="onSectionMode"
          @fix-section="onFixSection"
          @clear-section="onClearSection"
          @update:section-offset="onSectionOffset"
          @measure="onMeasure"
          @update:measure-snap-mode="onMeasureSnapMode"
          @update:measure-type="onMeasureTypeUpdate"
          @clear-measurements="onClearMeasurements"
          @export-glb="onExportGlb"
          @export-stl="onExportStl"
          @screenshot-3d="onScreenshot3D"
          @remarks-dirty="onModel3dRemarksDirty"
        />
        </div>
        <div v-show="showLogPanel()" class="panel log-panel-wrap">
        <LogPanel />
        </div>
      </div>
      <div
        class="workspace-side-rail workspace-side-rail--right"
        :style="{
          flex: `0 0 ${effectiveRightRailWidth}px`,
          width: `${effectiveRightRailWidth}px`,
          minWidth: `${effectiveRightRailWidth}px`,
          maxWidth: `${effectiveRightRailWidth}px`,
        }"
      >
      <div
        v-show="!chatPanelCollapsed"
        class="workspace-splitter workspace-splitter--in-rail"
        title="Перетащите для изменения ширины"
        @mousedown.prevent="onWorkspaceSplitterDown('right', $event)"
      />
      <aside
        class="collab-panel"
        :class="{ 'collab-panel--collapsed': chatPanelCollapsed }"
      >
        <div class="collab-panel-head">
          <div class="ide-panel-head-actions ide-panel-head-actions--chat">
            <button
              type="button"
              class="ide-panel-collapse-btn ide-panel-collapse-btn--chat"
              :title="chatPanelCollapsed ? 'Развернуть чат' : 'Свернуть чат'"
              @click="toggleChatPanel"
            >
              {{ chatPanelCollapsed ? '⟨' : '⟩' }}
            </button>
            <div v-if="!chatPanelCollapsed" class="ide-panel-width-controls" title="Ширина панели">
              <button
                type="button"
                class="ide-panel-width-btn"
                title="Уже"
                @click="nudgeChatPanelWidth(-PANEL_NUDGE_STEP_PX)"
              >
                ‹
              </button>
              <button
                type="button"
                class="ide-panel-width-btn"
                title="Шире"
                @click="nudgeChatPanelWidth(PANEL_NUDGE_STEP_PX)"
              >
                ›
              </button>
            </div>
          </div>
          <div v-if="!chatPanelCollapsed" class="collab-work-tabs" role="tablist">
            <button
              type="button"
              class="collab-work-tab"
              role="tab"
              :aria-selected="rightWorkAreaTab === 'chat'"
              :class="{ 'is-active': rightWorkAreaTab === 'chat' }"
              @click="rightWorkAreaTab = 'chat'"
            >
              Чат
            </button>
            <button
              type="button"
              class="collab-work-tab"
              role="tab"
              :aria-selected="rightWorkAreaTab === 'notes'"
              :class="{ 'is-active': rightWorkAreaTab === 'notes' }"
              @click="rightWorkAreaTab = 'notes'"
            >
              Заметки
            </button>
            <button
              type="button"
              class="collab-work-tab"
              role="tab"
              :aria-selected="rightWorkAreaTab === 'telemost'"
              :class="{ 'is-active': rightWorkAreaTab === 'telemost' }"
              @click="rightWorkAreaTab = 'telemost'"
            >
              Телемост
            </button>
          </div>
          <button v-if="collabToken && !chatPanelCollapsed" type="button" class="collab-btn collab-btn--compact" @click="collabLogout">Выйти</button>
        </div>
        <button
          v-if="chatPanelCollapsed"
          type="button"
          class="ide-sidebar-collapsed-label ide-sidebar-collapsed-label--chat"
          title="Развернуть чат"
          @click="toggleChatPanel"
        >
          Чат
        </button>
        <template v-else>
        <div v-show="rightWorkAreaTab === 'telemost'" class="collab-telemost">
          <p class="collab-hint collab-hint--tight">
            Главный звонок проекта — одна комната на проект (меню «Телемост» → «Присоединиться»). Отдельные встречи — для подгрупп. Нужен OAuth Телемоста на сервере.
          </p>
          <div v-if="telemostLoading" class="collab-telemost-placeholder">Получение ссылки…</div>
          <div v-else-if="telemostNeedsOAuth" class="collab-telemost-oauth">{{ telemostHint }}</div>
          <div v-else-if="telemostHint && !telemostJoinUrl" class="collab-telemost-oauth">{{ telemostHint }}</div>
          <template v-else-if="telemostJoinUrl">
            <a
              class="collab-btn collab-btn-primary collab-telemost-open"
              :href="telemostJoinUrl"
              target="_blank"
              rel="noopener noreferrer"
            >
              Подключиться к звонку проекта
            </a>
            <button type="button" class="collab-btn collab-telemost-secondary" :disabled="telemostLoading" @click="collabLoadTelemost">
              Обновить
            </button>
          </template>
          <div v-else class="collab-telemost-placeholder">Войдите в чат и выберите проект.</div>
          <div v-if="telemostExtraRooms.length" class="collab-telemost-rooms">
            <div class="collab-telemost-rooms-title">Дополнительные встречи</div>
            <div v-for="room in telemostExtraRooms" :key="room.id" class="collab-telemost-room-row">
              <span class="collab-telemost-room-title">{{ room.title }}</span>
              <div class="collab-telemost-room-actions">
                <button type="button" class="collab-btn collab-btn--compact" :disabled="!room.joinUrl" @click="openTelemostUrl(room.joinUrl)">
                  Войти
                </button>
                <button
                  type="button"
                  class="collab-btn collab-btn--compact"
                  :disabled="!room.joinUrl"
                  @click="postTelemostLinkToChat(room.joinUrl, room.title)"
                >
                  В чат
                </button>
              </div>
            </div>
          </div>
        </div>
        <div v-show="rightWorkAreaTab === 'notes'" class="collab-notes-wrap">
          <p class="collab-hint collab-hint--tight">
            Совместное редактирование (Yjs CRDT): текст и курсоры синхронизируются по WebSocket внутри проекта. Откройте ту же вкладку на другом ПК — изменения сливаются без конфликтов.
          </p>
          <CollaborativeEditor
            v-if="collabNotesDoc && collabNotesAwareness"
            :y-doc="collabNotesDoc"
            :awareness="collabNotesAwareness"
          />
          <div v-else class="collab-notes-placeholder">Войдите в чат и выберите проект — подключится общий документ.</div>
        </div>
        <div v-show="rightWorkAreaTab === 'chat'" class="collab-chat-area">
        <div v-if="!collabToken" class="collab-auth">
          <div class="collab-auth-tabs">
            <button type="button" class="collab-btn" :class="{ active: collabAuthMode === 'login' }" @click="collabAuthMode = 'login'">Вход</button>
            <button type="button" class="collab-btn" :class="{ active: collabAuthMode === 'register' }" @click="collabAuthMode = 'register'">Регистрация</button>
          </div>
          <input v-model="collabEmail" type="email" class="collab-input" placeholder="email" />
          <input v-model="collabPassword" type="password" class="collab-input" placeholder="password" />
          <input v-if="collabAuthMode === 'register'" v-model="collabDisplayName" type="text" class="collab-input" placeholder="display name" />
          <button type="button" class="collab-btn collab-btn-primary" :disabled="collabBusy" @click="collabSubmitAuth">Подключиться</button>
        </div>
        <div v-else class="collab-body">
          <div class="collab-user-row">
            <span
              v-if="collabCurrentProjectRole"
              class="collab-user-role-badge"
              :style="{
                background: COLLAB_ROLE_AVATAR[collabCurrentProjectRole].bg,
                boxShadow: `0 0 0 2px ${COLLAB_ROLE_AVATAR[collabCurrentProjectRole].ring}`,
              }"
              :title="collabRoleLabel(collabCurrentProjectRole)"
            >
              <CollabRoleIcon :role="collabCurrentProjectRole" :size="13" class="collab-user-role-icon" />
            </span>
            <div class="collab-user">{{ collabUser?.displayName || collabUser?.email }}</div>
          </div>
          <label class="collab-field-label">Проект</label>
          <select v-model="collabProjectId" class="collab-input" @change="onCollabProjectChange">
            <option value="" disabled>{{ collabProjects.length ? 'Выберите проект' : 'Нет проектов — создайте ниже' }}</option>
            <option v-for="p in collabProjects" :key="p.id" :value="p.id">
              {{ p.name }}<template v-if="p.role"> — {{ collabRoleLabel(String(p.role)) }}</template>
            </option>
          </select>
          <div class="collab-create-row">
            <input
              v-model="collabNewProjectName"
              type="text"
              class="collab-input collab-input-grow"
              placeholder="Название нового проекта"
              @keydown.enter.prevent="collabCreateProject"
            />
            <button type="button" class="collab-btn collab-btn-primary" :disabled="collabBusy" @click="collabCreateProject">Создать</button>
          </div>
          <label class="collab-field-label">Канал</label>
          <select v-model="collabChannelId" class="collab-input" @change="onCollabChannelChange">
            <option value="" disabled>{{ collabChannels.length ? 'Выберите канал' : 'Нет каналов — создайте или откройте проект' }}</option>
            <option v-for="c in collabChannels" :key="c.id" :value="c.id">{{ c.name }}</option>
          </select>
          <div class="collab-create-row">
            <input
              v-model="collabNewChannelName"
              type="text"
              class="collab-input collab-input-grow"
              placeholder="Новый канал (не для роли «Клиент»)"
              @keydown.enter.prevent="collabCreateChannel"
            />
            <button type="button" class="collab-btn collab-btn-primary" :disabled="collabBusy || !collabProjectId" @click="collabCreateChannel">Создать</button>
          </div>
          <p class="collab-hint">При создании проекта на сервере автоматически добавляется канал «Общий».</p>
          <label class="collab-field-label">Участники проекта</label>
          <input
            v-model="collabInviteEmail"
            type="email"
            class="collab-input"
            placeholder="Email (уже зарегистрированного пользователя)"
            autocomplete="email"
            @keydown.enter.prevent="collabInviteMember"
          />
          <div class="collab-create-row">
            <select v-model="collabInviteRole" class="collab-input collab-input-grow collab-role-select">
              <option value="gip">{{ COLLAB_ROLE_LABELS.gip }}</option>
              <option value="chief_designer">{{ COLLAB_ROLE_LABELS.chief_designer }}</option>
              <option value="designer">{{ COLLAB_ROLE_LABELS.designer }}</option>
              <option value="installer">{{ COLLAB_ROLE_LABELS.installer }}</option>
              <option value="assembler">{{ COLLAB_ROLE_LABELS.assembler }}</option>
              <option value="client">{{ COLLAB_ROLE_LABELS.client }}</option>
            </select>
            <button type="button" class="collab-btn collab-btn-primary" :disabled="collabBusy || !collabProjectId" @click="collabInviteMember">Добавить</button>
          </div>
          <p class="collab-hint">
            Приглашать могут ГИП, главный конструктор и конструктор. Пользователь должен быть зарегистрирован на этом сервере. Роль «ГИП» может назначить только текущий ГИП. У роли «Клиент» нет записи в чат и загрузки файлов.
          </p>
          <label class="collab-field-label">Состав проекта</label>
          <div v-if="collabMembersLoading" class="collab-hint">Загрузка списка…</div>
          <ul v-else-if="collabMembers.length" class="collab-member-list">
            <li v-for="m in collabMembers" :key="m.id" class="collab-member-row">
              <span
                v-if="isCollabMemberRole(m.role)"
                class="collab-member-avatar"
                :style="{
                  background: COLLAB_ROLE_AVATAR[m.role].bg,
                  boxShadow: `0 0 0 2px ${COLLAB_ROLE_AVATAR[m.role].ring}`,
                }"
              >
                <CollabRoleIcon :role="m.role" :size="11" class="collab-user-role-icon" />
              </span>
              <span v-else class="collab-member-avatar collab-member-avatar-fallback">{{
                (m.displayName || m.email || '?').slice(0, 2)
              }}</span>
              <div class="collab-member-info">
                <span class="collab-member-name">{{ m.displayName || m.email }}</span>
                <select
                  v-if="collabCanEditOtherMemberRole(m)"
                  class="collab-input collab-member-role-select"
                  :value="m.role"
                  :disabled="collabBusy"
                  @change="onCollabMemberRoleChange(m, $event)"
                >
                  <option
                    v-for="rid in COLLAB_ROLE_ORDER"
                    :key="rid"
                    :value="rid"
                    :disabled="rid === 'gip' && collabCurrentProjectRole !== 'gip'"
                  >
                    {{ COLLAB_ROLE_SHORT[rid] }}
                  </option>
                </select>
                <span v-else class="collab-member-role-tag">{{ collabRoleLabel(m.role) }}</span>
              </div>
              <div class="collab-member-actions">
                <button
                  v-if="collabIsMemberSelf(m)"
                  type="button"
                  class="collab-btn collab-member-btn"
                  :disabled="collabBusy"
                  @click="collabLeaveProject"
                >
                  Покинуть
                </button>
                <button
                  v-else-if="collabCanRemoveOtherMember(m)"
                  type="button"
                  class="collab-btn collab-member-btn"
                  :disabled="collabBusy"
                  @click="collabKickMember(m.id)"
                >
                  Исключить
                </button>
              </div>
            </li>
          </ul>
          <div class="collab-role-legend" aria-label="Цвета и значки ролей">
            <div v-for="rid in COLLAB_ROLE_ORDER" :key="rid" class="collab-role-chip">
              <span
                class="collab-role-chip-dot"
                :style="{
                  background: COLLAB_ROLE_AVATAR[rid].bg,
                  boxShadow: `0 0 0 2px ${COLLAB_ROLE_AVATAR[rid].ring}`,
                }"
              >
                <CollabRoleIcon :role="rid" :size="11" class="collab-role-chip-svg" />
              </span>
              <span>{{ COLLAB_ROLE_SHORT[rid] }}</span>
            </div>
          </div>
          <label class="collab-field-label">Связки PDF ↔ 3D</label>
          <p class="collab-hint">
            Вложения из чата с одинаковым именем файла (без расширения), например узел.pdf и узел.glb, можно связать и открыть разом.
          </p>
          <div class="collab-asset-actions">
            <button
              type="button"
              class="collab-btn collab-btn-primary"
              :disabled="collabBusy || !collabProjectId || collabSuggestLoading"
              @click="collabLoadSuggestions"
            >
              Найти по именам вложений
            </button>
            <button
              type="button"
              class="collab-btn"
              :disabled="collabBusy || collabAssetSuggestions.length === 0"
              @click="collabAddAllSuggestedPairs"
            >
              Добавить все
            </button>
          </div>
          <div v-if="collabSuggestLoading" class="collab-hint">Поиск пар…</div>
          <ul v-else-if="collabAssetSuggestions.length" class="collab-asset-suggest-list">
            <li v-for="(s, i) in collabAssetSuggestions" :key="`sug-${i}`" class="collab-asset-suggest-row">
              <span class="collab-asset-suggest-label"
                >{{ s.pdfFileName || s.pdfStem }} ↔ {{ s.modelFileName || s.modelStem }}</span
              >
              <button type="button" class="collab-btn collab-asset-suggest-add" :disabled="collabBusy" @click="collabAddOneSuggestedPair(s)">
                +
              </button>
            </li>
          </ul>
          <div v-if="collabAssetPairsLoading" class="collab-hint">Загрузка реестра…</div>
          <ul v-else-if="collabAssetPairs.length" class="collab-asset-pair-list">
            <li v-for="ap in collabAssetPairs" :key="String(ap.id)" class="collab-asset-pair-row">
              <div class="collab-asset-pair-meta">
                <span class="collab-asset-pair-stem">{{ ap.pdfStem }} ↔ {{ ap.modelStem }}</span>
              </div>
              <div class="collab-asset-pair-actions">
                <button
                  type="button"
                  class="collab-btn collab-btn-primary collab-asset-open"
                  :disabled="collabBusy"
                  @click="collabOpenAssetPair(ap)"
                >
                  Открыть пару
                </button>
                <button type="button" class="collab-btn" :disabled="collabBusy" @click="collabDeleteAssetPair(String(ap.id))">
                  Удалить
                </button>
              </div>
            </li>
          </ul>
          <div v-else class="collab-hint">Реестр пуст — добавьте связки по подсказке или после загрузки файлов в канал.</div>
          <div class="collab-messages">
            <template v-for="item in collabChatTimeline" :key="item.key">
              <div v-if="item.type === 'sep'" class="collab-day-sep">
                <span class="collab-day-sep-line" aria-hidden="true" />
                <span class="collab-day-sep-label">{{ item.label }}</span>
                <span class="collab-day-sep-line" aria-hidden="true" />
              </div>
              <div v-else class="collab-msg">
                <div class="collab-msg-head">
                  <div
                    class="collab-avatar"
                    :class="{ 'collab-avatar--role': item.row.role }"
                    :style="{
                      background: item.row.avatar.bg,
                      boxShadow: `0 0 0 2px ${item.row.avatar.ring}, 0 3px 12px rgba(0, 0, 0, 0.38)`,
                    }"
                    :title="item.row.role ? collabRoleLabel(item.row.role) : undefined"
                    aria-hidden="true"
                  >
                    <CollabRoleIcon
                      v-if="item.row.role"
                      :role="item.row.role"
                      :size="13"
                      class="collab-avatar-icon"
                    />
                    <template v-else>{{ item.row.avatar.initials }}</template>
                  </div>
                  <div class="collab-msg-meta">
                    <span class="collab-msg-author">{{ item.row.author }}</span>
                    <span
                      v-if="item.row.roleShort"
                      class="collab-msg-role-pill"
                      :style="{
                        borderColor: item.row.avatar.ring,
                        color: item.row.avatar.ring,
                      }"
                      >{{ item.row.roleShort }}</span>
                    <span class="collab-msg-dot" aria-hidden="true">·</span>
                    <time class="collab-msg-time" :datetime="String(item.message.created_at ?? '')">{{
                      formatMessageTime(item.message.created_at as string)
                    }}</time>
                  </div>
                </div>
                <div v-if="collabMessageBodyForDisplay(item.message)" class="collab-msg-body">
                  {{ collabMessageBodyForDisplay(item.message) }}
                </div>
                <div
                  v-for="a in (item.message.attachments || [])"
                  :key="String((a as { id?: string }).id)"
                  class="collab-attach-block"
                >
                  <div
                    class="collab-attach-name"
                    :title="collabAttachmentDisplayName(a as { id: string; file_name?: string; fileName?: string }, String(item.message.body ?? ''))"
                  >
                    {{
                      collabAttachmentDisplayName(
                        a as { id: string; file_name?: string; fileName?: string },
                        String(item.message.body ?? '')
                      )
                    }}
                  </div>
                  <div class="collab-attach-actions">
                    <button
                      type="button"
                      class="collab-attach-action collab-action-open"
                      @click="collabOpenAttachmentPreview(a as { id: string; file_name?: string; fileName?: string })"
                    >
                      Открыть
                    </button>
                    <button
                      type="button"
                      class="collab-attach-action collab-action-save"
                      @click="collabDownloadAttachment(a as { id: string; file_name?: string; fileName?: string })"
                    >
                      Скачать
                    </button>
                  </div>
                </div>
              </div>
            </template>
          </div>
          <div class="collab-compose">
            <textarea
              v-model="collabMessageText"
              class="collab-input collab-textarea"
              placeholder="Сообщение... (Enter — отправить, Shift+Enter — новая строка)"
              @keydown="onCollabComposerKeydown"
            />
            <div class="collab-attach-btn-wrap" title="Прикрепить файл (Excel, PDF, CAD, KOMPAS, Revit, изображения)">
              <div v-if="collabAttachPct !== null" class="collab-attach-pct-ring" aria-live="polite">{{ collabAttachPct }}%</div>
              <button
                type="button"
                class="collab-btn collab-attach-trigger"
                :disabled="collabBusy"
                :class="{ 'is-uploading': collabAttachPct !== null }"
                @click="collabAttachFile"
              >
                📎
              </button>
            </div>
            <button type="button" class="collab-btn collab-btn-primary collab-send-btn" :disabled="collabBusy" @click="collabSendMessage">
              <span v-if="collabSendingText" class="collab-sending-dot" aria-hidden="true" />
              <span>{{ collabSendingText ? 'Отпр…' : 'Отпр.' }}</span>
            </button>
          </div>
        </div>
        </div>
        <div v-if="collabStatus" class="collab-status">{{ collabStatus }}</div>
        </template>
      </aside>
      </div>
    </div>
    <div v-else class="production-mode">
      <div class="production-card">
        <h2 class="production-title">QR-страница для монтажа и производства</h2>
        <p class="production-hint">
          По QR открывается облегченная мобильная страница с ссылками на чертежи из проекта. 3D подключается только по необходимости.
        </p>
        <div class="production-qr-placeholder">
          <span class="production-qr-code">QR</span>
          <div class="production-qr-text">
            <div>Ссылка страницы модуля:</div>
            <code>https://viewer.example/m/project-001/module-m1</code>
          </div>
        </div>
      </div>
      <div class="production-card">
        <h3 class="production-title production-title-small">Ссылки на чертежи (из дерева PDF)</h3>
        <ul v-if="productionLinks.length" class="production-links">
          <li v-for="link in productionLinks" :key="link.id" class="production-link-row">
            <span class="production-link-title">{{ link.title }}</span>
            <span class="production-link-folder">{{ link.folder }}</span>
            <a :href="link.href" class="production-link-open" target="_blank" rel="noopener noreferrer">Открыть</a>
          </li>
        </ul>
        <div v-else class="production-empty">В дереве PDF пока нет файлов для публикации.</div>
      </div>
    </div>
    <ScreenshotEditorModal
      v-if="showScreenshotModal && screenshotImageUrl"
      :image-url="screenshotImageUrl!"
      :suggested-file-name="screenshotSuggestedFileName"
      :chat-send-enabled="!!collabToken && !!collabProjectId && !!collabChannelId"
      @close="onScreenshotEditorClose"
      @final-image="onScreenshotEditorFinalImage"
      @send-to-chat="onScreenshotEditorSendToChat"
    />
    <ReportScreenshotsModal
      :open="showReportGallery"
      :screenshots="reportScreenshots"
      :project-name="reportProjectName"
      :module-number="reportModuleNumber"
      :sheet-number="reportSheetNumber"
      :author="reportAuthor"
      @close="showReportGallery = false"
      @update:project-name="reportProjectName = $event"
      @update:module-number="reportModuleNumber = $event"
      @update:sheet-number="reportSheetNumber = $event"
      @update:author="reportAuthor = $event"
      @edit="openEditorForScreenshot"
      @remove="removeScreenshotFromReport"
      @move-up="moveScreenshotUp"
      @move-down="moveScreenshotDown"
      @reorder="onScreenshotReorder"
      @send-chat="sendScreenshotToChat"
      @download="downloadScreenshotItem"
      @export-pdf="onExportReport"
      @export-email="onExportReportEmail"
      @export-chat="onExportReportChat"
      @fill-first-sheet="fillProjectNameFromFirstSheet"
    />
    <ScreenshotFlyToBasket
      v-if="screenshotFlyAnim"
      :src="screenshotFlyAnim.src"
      :from-x="screenshotFlyAnim.fromX"
      :from-y="screenshotFlyAnim.fromY"
      :to-x="screenshotFlyAnim.toX"
      :to-y="screenshotFlyAnim.toY"
      @done="onScreenshotFlyDone"
    />
  </div>
</template>

<style scoped>
.app {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
  position: relative;
}
.app.is-dragging-file {
  outline: 3px dashed #646cff;
  outline-offset: -3px;
}
.drop-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.2rem;
  color: #fff;
  pointer-events: none;
  z-index: 500;
}
.content {
  flex: 1 1 auto;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: row;
  align-items: stretch;
}
.workspace {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: row;
  align-items: stretch;
  overflow: hidden;
}
.ide-sidebar {
  display: flex;
  flex-direction: column;
  min-height: 0;
  align-self: stretch;
  background: #141920;
  border-right: 1px solid #2f3d56;
}
.ide-sidebar--disk {
  min-width: 160px;
  max-width: 480px;
}
.ide-sidebar--collapsed {
  min-width: 0;
  max-width: none;
}
.ide-panel-collapse-btn {
  flex-shrink: 0;
  width: 26px;
  height: 26px;
  padding: 0;
  font-size: 0.85rem;
  line-height: 1;
  border: 1px solid #3d4d68;
  border-radius: 4px;
  background: #252f42;
  color: #c8d6ee;
  cursor: pointer;
}
.ide-panel-collapse-btn:hover {
  background: #395f96;
  border-color: #5d83c7;
}
.ide-panel-collapse-btn--chat {
  margin-right: 0.35rem;
}
.ide-sidebar-collapsed-label {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  writing-mode: vertical-rl;
  text-orientation: mixed;
  font-size: 0.68rem;
  letter-spacing: 0.08em;
  color: #8ea4c7;
  padding: 0.5rem 0;
  user-select: none;
  border: none;
  background: transparent;
  cursor: pointer;
  width: 100%;
}
.ide-sidebar-collapsed-label:hover {
  color: #c5d8f5;
  background: rgba(255, 255, 255, 0.04);
}
.ide-sidebar-collapsed-label--chat {
  transform: rotate(180deg);
}
.workspace-side-rail {
  display: flex;
  flex-direction: row;
  flex-shrink: 0;
  min-height: 0;
  align-self: stretch;
  overflow: hidden;
}
.workspace-side-rail--left .ide-sidebar {
  flex: 1 1 0;
  min-width: 0;
  width: auto;
  max-width: none;
}
.workspace-side-rail--right .collab-panel {
  flex: 1 1 0;
  min-width: 0;
  width: auto;
  max-width: none;
}
.workspace-splitter--in-rail {
  flex: 0 0 5px;
  width: 5px;
  min-width: 5px;
  margin: 0;
}
.ide-panel-head-actions {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  flex-shrink: 0;
  margin-left: auto;
}
.ide-panel-head-actions--chat {
  margin-left: 0;
  margin-right: auto;
}
.ide-panel-width-controls {
  display: flex;
  align-items: center;
  gap: 0.12rem;
}
.ide-panel-width-btn {
  width: 22px;
  height: 22px;
  padding: 0;
  font-size: 0.9rem;
  line-height: 1;
  border: 1px solid #3d4d68;
  border-radius: 4px;
  background: #252f42;
  color: #c8d6ee;
  cursor: pointer;
}
.ide-panel-width-btn:hover {
  background: #395f96;
  border-color: #5d83c7;
}
.telemost-call-banner {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  padding: 0.4rem 0.85rem;
  background: rgba(50, 90, 60, 0.55);
  border-bottom: 1px solid rgba(100, 160, 110, 0.45);
  font-size: 0.82rem;
  color: #d8f0dc;
}
.telemost-call-banner-link {
  color: #9ee8b0;
  font-weight: 600;
}
.telemost-call-banner-dismiss {
  margin-left: auto;
  border: none;
  background: transparent;
  color: #c8e8cc;
  font-size: 1.1rem;
  cursor: pointer;
  padding: 0 0.35rem;
}
.workspace-save-toast {
  position: fixed;
  bottom: 1.25rem;
  left: 50%;
  transform: translateX(-50%);
  z-index: 5000;
  padding: 0.55rem 1rem;
  border-radius: 8px;
  background: rgba(30, 40, 58, 0.95);
  border: 1px solid #4a6fc7;
  color: #e8eef8;
  font-size: 0.82rem;
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.4);
  pointer-events: none;
}
.ide-sidebar-header {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.35rem;
  padding: 0.42rem 0.5rem;
  border-bottom: 1px solid #2a3548;
}
.ide-disk-actions {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  padding: 0.45rem;
  border-bottom: 1px solid #2a3548;
  background: rgba(0, 0, 0, 0.18);
}
.ide-disk-row {
  display: flex;
  gap: 0.35rem;
}
.ide-disk-row--wrap {
  flex-wrap: wrap;
}
.ide-disk-hint-mini {
  margin: 0;
  font-size: 0.62rem;
  line-height: 1.35;
  color: #6d849e;
}
.ide-disk-btn {
  border: 1px solid #3f516d;
  background: #2a384f;
  color: #d7e3f6;
  font-size: 0.7rem;
  padding: 0.22rem 0.45rem;
  border-radius: 4px;
  cursor: pointer;
}
.ide-disk-btn:hover {
  background: #354968;
}
.ide-disk-btn-primary {
  background: #3f5f97;
  border-color: #5c80c1;
}
.ide-disk-btn-danger {
  background: #6c3a44;
  border-color: #8d4d5a;
}
.ide-disk-url-input {
  flex: 1;
  min-width: 0;
  border: 1px solid #3f516d;
  background: #1d2737;
  color: #d7e3f6;
  border-radius: 4px;
  padding: 0.22rem 0.42rem;
  font-size: 0.7rem;
}
.ide-disk-status {
  font-size: 0.66rem;
  color: #8ea4c7;
}
.ide-sidebar-title {
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: #9eb4d8;
}
.ide-sidebar-pill {
  font-size: 0.58rem;
  padding: 0.12rem 0.38rem;
  border-radius: 3px;
  background: #252f42;
  color: #7a8faa;
}
.ide-tree-tabs {
  display: flex;
  gap: 0.25rem;
  padding: 0.35rem 0.45rem;
  border-bottom: 1px solid #2a3548;
}
.ide-tree-tab {
  border: 1px solid #324865;
  background: #202b3d;
  color: #a9bad6;
  font-size: 0.68rem;
  line-height: 1.1;
  padding: 0.22rem 0.45rem;
  border-radius: 4px;
  cursor: pointer;
}
.ide-tree-tab.is-active {
  background: #395f96;
  border-color: #5d83c7;
  color: #f0f5ff;
}
.ide-tree {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 0.28rem 0;
}
.ide-tree-empty {
  padding: 0.5rem 0.65rem;
  font-size: 0.68rem;
  line-height: 1.35;
  color: #7a8faa;
}
.ide-tree-folder {
  margin-bottom: 0.06rem;
}
.ide-tree-row {
  display: flex;
  align-items: center;
  gap: 0.22rem;
  width: 100%;
  text-align: left;
  border: none;
  background: transparent;
  font: inherit;
  font-size: 0.72rem;
  color: #c8d6ee;
  padding: 0.14rem 0.4rem;
  border-radius: 3px;
}
.ide-tree-row--folder {
  cursor: pointer;
}
.ide-tree-row--folder:hover {
  background: rgba(255, 255, 255, 0.06);
}
.ide-tree-row--file {
  cursor: default;
  color: #a8b8d4;
}
.ide-tree-chevron {
  width: 0.78rem;
  flex-shrink: 0;
  font-size: 0.58rem;
  color: #6a7f9e;
}
.ide-tree-chevron--spacer {
  visibility: hidden;
}
.ide-tree-icon {
  flex-shrink: 0;
}
.ide-tree-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ide-tree-children {
  margin-left: 0.2rem;
  padding: 0.05rem 0 0.1rem 0.35rem;
  border-left: 1px solid #2a3a52;
}
.ide-sidebar-hint {
  flex-shrink: 0;
  margin: 0;
  padding: 0.4rem 0.5rem 0.45rem;
  font-size: 0.62rem;
  line-height: 1.35;
  color: #5f7394;
  border-top: 1px solid #2a3548;
  background: rgba(0, 0, 0, 0.12);
}
.production-mode {
  flex: 1;
  overflow: auto;
  padding: 0.8rem;
  display: grid;
  gap: 0.8rem;
  grid-template-columns: minmax(320px, 1fr);
  background: #111622;
}
.production-card {
  border: 1px solid #33445f;
  border-radius: 8px;
  background: #1a2334;
  padding: 0.8rem;
}
.production-title {
  margin: 0 0 0.45rem;
  font-size: 1rem;
  color: #d9e7ff;
}
.production-title-small {
  font-size: 0.9rem;
}
.production-hint {
  margin: 0 0 0.6rem;
  color: #9ab0d3;
  font-size: 0.78rem;
}
.production-qr-placeholder {
  display: flex;
  align-items: center;
  gap: 0.8rem;
  border: 1px dashed #4d6389;
  background: rgba(10, 16, 26, 0.42);
  border-radius: 6px;
  padding: 0.6rem;
}
.production-qr-code {
  width: 72px;
  height: 72px;
  border-radius: 8px;
  background: linear-gradient(135deg, #e3ebff 0%, #b8c8ea 100%);
  color: #23324a;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.production-qr-text {
  color: #b5c5df;
  font-size: 0.76rem;
}
.production-links {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  gap: 0.42rem;
}
.production-link-row {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) auto auto;
  gap: 0.5rem;
  align-items: center;
  border: 1px solid #2e405d;
  border-radius: 6px;
  padding: 0.42rem 0.5rem;
  background: rgba(17, 24, 38, 0.6);
}
.production-link-title {
  color: #d2def2;
  font-size: 0.78rem;
}
.production-link-folder {
  color: #7f97bc;
  font-size: 0.7rem;
}
.production-link-open {
  color: #8fb1ff;
  font-size: 0.74rem;
  text-decoration: none;
}
.production-link-open:hover {
  text-decoration: underline;
}
.production-empty {
  color: #7f94b6;
  font-size: 0.76rem;
}
.collab-panel {
  min-width: 260px;
  max-width: 720px;
  flex-shrink: 0;
  min-height: 0;
  align-self: stretch;
  border-left: 1px solid #3a4a6a;
  background: #1a1f2b;
  display: flex;
  flex-direction: column;
  padding: 0.5rem;
  gap: 0.4rem;
  overflow: hidden;
}
.collab-panel.collab-panel--collapsed {
  min-width: 0;
  max-width: none;
  width: 100%;
  padding: 0.15rem 0.05rem;
  gap: 0.15rem;
}
.collab-panel.collab-panel--collapsed .collab-panel-head {
  flex-direction: column;
  align-items: center;
  justify-content: flex-start;
  padding: 0.2rem 0.1rem;
  gap: 0.25rem;
  width: 100%;
}
.collab-panel.collab-panel--collapsed .ide-panel-collapse-btn--chat {
  margin-right: 0;
}
.collab-panel.collab-panel--collapsed .ide-sidebar-collapsed-label--chat {
  flex: 1;
  min-height: 0;
  padding: 0.35rem 0;
}
.workspace-splitter {
  flex: 0 0 5px;
  margin: 0 -1px;
  cursor: col-resize;
  background: transparent;
  z-index: 4;
  align-self: stretch;
}
.workspace-splitter:hover {
  background: rgba(100, 140, 220, 0.35);
}
.collab-notes-wrap {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  overflow: hidden;
}
.collab-notes-placeholder {
  flex: 1;
  min-height: 80px;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 0.6rem;
  font-size: 0.76rem;
  color: #7a8faa;
  border: 1px dashed #3d4e68;
  border-radius: 6px;
}
.collab-panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.4rem;
  flex-shrink: 0;
}
.collab-work-tabs {
  display: flex;
  flex: 1;
  min-width: 0;
  gap: 0.2rem;
}
.collab-work-tab {
  flex: 1;
  border: 1px solid #3d4e6a;
  background: #232b3b;
  color: #9eb0d0;
  border-radius: 4px;
  padding: 0.32rem 0.45rem;
  font-size: 0.74rem;
  font-weight: 600;
  cursor: pointer;
}
.collab-work-tab.is-active {
  background: #2d3f62;
  color: #eaf0ff;
  border-color: #5169a0;
}
.collab-work-tab:hover:not(.is-active) {
  background: #283248;
}
.collab-btn--compact {
  height: 28px;
  padding: 0 8px;
  flex-shrink: 0;
}
.collab-chat-area {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.collab-telemost {
  flex: 1;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
  padding-top: 0.1rem;
}
.collab-hint--tight {
  margin: 0;
}
.collab-telemost-open {
  text-align: center;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 30px;
}
.collab-telemost-placeholder {
  font-size: 0.72rem;
  color: #6a7f9e;
  padding: 0.55rem;
  border: 1px dashed #3a4a62;
  border-radius: 6px;
  text-align: center;
}
.collab-telemost-oauth {
  font-size: 0.72rem;
  line-height: 1.4;
  color: #b8c8e4;
  padding: 0.55rem 0.45rem;
  border-radius: 6px;
  background: rgba(0, 0, 0, 0.22);
  border: 1px solid #4a5f78;
}
.collab-telemost-secondary {
  margin-top: 0.35rem;
  width: 100%;
}
.collab-telemost-rooms {
  margin-top: 0.65rem;
  padding-top: 0.5rem;
  border-top: 1px solid #3d4f66;
}
.collab-telemost-rooms-title {
  font-size: 0.78rem;
  color: #9eb0c8;
  margin-bottom: 0.35rem;
}
.collab-telemost-room-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.35rem;
  margin-bottom: 0.3rem;
  font-size: 0.82rem;
}
.collab-telemost-room-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.collab-telemost-room-actions {
  display: flex;
  gap: 0.25rem;
  flex-shrink: 0;
}
.collab-auth,
.collab-body {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  min-height: 0;
  flex: 1;
  overflow: hidden;
}
.collab-auth-tabs {
  display: flex;
  gap: 0.3rem;
}
.collab-btn {
  border: 1px solid #516487;
  background: #2c3a54;
  color: #e8efff;
  border-radius: 4px;
  height: 28px;
  padding: 0 8px;
  cursor: pointer;
}
.collab-btn.active,
.collab-btn-primary {
  background: #4a6fc7;
  border-color: #5d82db;
}
.collab-input {
  width: 100%;
  height: 30px;
  border: 1px solid #4a5f7a;
  background: #233049;
  color: #e7efff;
  border-radius: 4px;
  padding: 0 8px;
}
.collab-user-row {
  display: flex;
  align-items: center;
  gap: 0.45rem;
}
.collab-user-role-badge {
  flex-shrink: 0;
  width: 1.2rem;
  height: 1.2rem;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.collab-user-role-icon,
.collab-role-chip-svg,
.collab-avatar-icon {
  color: rgba(255, 255, 255, 0.96);
}
.collab-user {
  color: #9fb6dc;
  font-size: 0.8rem;
}
.collab-member-list {
  list-style: none;
  margin: 0 0 0.45rem;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.28rem;
  max-height: 9.5rem;
  overflow-y: auto;
}
.collab-member-row {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.72rem;
  color: #b0c4e8;
}
.collab-member-role-select {
  margin-top: 0.12rem;
  max-width: 100%;
  height: 26px;
  font-size: 0.64rem;
  padding: 0 6px;
}
.collab-member-actions {
  display: flex;
  flex-shrink: 0;
  align-items: flex-start;
  gap: 0.25rem;
}
.collab-member-btn {
  height: 26px;
  font-size: 0.65rem;
  padding: 0 6px;
  white-space: nowrap;
}
.collab-member-avatar {
  flex-shrink: 0;
  width: 1.15rem;
  height: 1.15rem;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 0.55rem;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.92);
}
.collab-member-avatar-fallback {
  background: #3d4a62;
  box-shadow: 0 0 0 1px #5a6b88;
}
.collab-member-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  gap: 0.06rem;
}
.collab-member-name {
  color: #d2dff5;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.collab-member-role-tag {
  font-size: 0.62rem;
  color: #7a92b8;
  line-height: 1.2;
}
.collab-role-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem 0.55rem;
  align-items: center;
  margin: 0.1rem 0 0.45rem;
  padding: 0.35rem 0.4rem;
  border-radius: 5px;
  background: rgba(0, 0, 0, 0.2);
  border: 1px solid #2f4566;
}
.collab-asset-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  align-items: center;
  margin-bottom: 0.35rem;
}
.collab-asset-suggest-list,
.collab-asset-pair-list {
  list-style: none;
  margin: 0 0 0.45rem;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.28rem;
  max-height: 9rem;
  overflow: auto;
}
.collab-asset-suggest-row,
.collab-asset-pair-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.45rem;
  padding: 0.28rem 0.4rem;
  border-radius: 5px;
  background: rgba(0, 0, 0, 0.18);
  border: 1px solid #2a4060;
  font-size: 0.72rem;
}
.collab-asset-suggest-label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #b8c8e0;
}
.collab-asset-suggest-add {
  flex-shrink: 0;
  min-width: 2rem;
  padding: 0.12rem 0.35rem;
  font-weight: 700;
}
.collab-asset-pair-meta {
  min-width: 0;
  flex: 1;
}
.collab-asset-pair-stem {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #c5d4ee;
}
.collab-asset-pair-actions {
  display: flex;
  flex-shrink: 0;
  gap: 0.28rem;
  align-items: center;
}
.collab-asset-open {
  white-space: nowrap;
}
.collab-role-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.28rem;
  font-size: 0.61rem;
  color: #93a8cc;
  white-space: nowrap;
}
.collab-role-chip-dot {
  flex-shrink: 0;
  width: 1rem;
  height: 1rem;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.collab-msg-role-pill {
  font-size: 0.58rem;
  font-weight: 600;
  padding: 0.05rem 0.28rem;
  border-radius: 4px;
  border: 1px solid;
  background: rgba(255, 255, 255, 0.04);
  max-width: 8.5rem;
  overflow: hidden;
  text-overflow: ellipsis;
}
.collab-field-label {
  font-size: 0.72rem;
  color: #7a91b8;
  margin-top: 0.15rem;
}
.collab-create-row {
  display: flex;
  gap: 0.3rem;
  align-items: center;
}
.collab-input-grow {
  flex: 1;
  min-width: 0;
}
.collab-hint {
  font-size: 0.68rem;
  color: #6a7f9e;
  margin: 0 0 0.2rem;
  line-height: 1.35;
}
.collab-role-select {
  cursor: pointer;
}
.collab-body > :not(.collab-messages) {
  flex-shrink: 0;
}
.collab-messages {
  flex: 1;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  border: 1px solid #334666;
  border-radius: 6px;
  padding: 0.35rem;
  background: #192336;
}
.collab-msg {
  border: 1px solid #324a72;
  border-radius: 5px;
  padding: 0.28rem 0.35rem;
  background: #233149;
}
.collab-msg-head {
  display: flex;
  align-items: flex-start;
  gap: 0.45rem;
  margin-bottom: 0.25rem;
}
.collab-avatar {
  flex-shrink: 0;
  width: 1.65rem;
  height: 1.65rem;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.62rem;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.95);
  letter-spacing: -0.02em;
}
.collab-avatar--role .collab-avatar-icon {
  margin-top: 1px;
}
.collab-msg-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.25rem 0.35rem;
  font-size: 0.68rem;
  color: #9eb4d8;
  flex: 1;
  min-width: 0;
}
.collab-msg-author {
  color: #c5d7f5;
  font-weight: 600;
}
.collab-msg-dot {
  color: #6a7a9a;
  user-select: none;
}
.collab-msg-time {
  color: #8a9bb5;
  font-variant-numeric: tabular-nums;
}
.collab-day-sep {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin: 0.55rem 0 0.4rem;
}
.collab-day-sep-line {
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, transparent, #4a5f7a 15%, #4a5f7a 85%, transparent);
  min-width: 0;
}
.collab-day-sep-label {
  font-size: 0.68rem;
  font-weight: 600;
  color: #8fa3c4;
  text-transform: capitalize;
  white-space: nowrap;
}
.collab-msg-body {
  color: #edf3ff;
  font-size: 0.78rem;
}
.collab-attach-btn-wrap {
  position: relative;
  flex-shrink: 0;
  align-self: flex-end;
}
.collab-attach-pct-ring {
  position: absolute;
  z-index: 2;
  right: -2px;
  bottom: 22px;
  min-width: 2.1rem;
  padding: 2px 5px;
  font-size: 0.62rem;
  font-weight: 700;
  line-height: 1.1;
  background: rgba(20, 32, 56, 0.95);
  border: 1px solid #5a7fd7;
  border-radius: 5px;
  color: #e8f0ff;
  pointer-events: none;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.35);
}
.collab-attach-trigger.is-uploading {
  opacity: 0.88;
}
.collab-send-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
}
.collab-sending-dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #b8d4ff;
  animation: collab-send-pulse 0.9s ease-in-out infinite;
}
@keyframes collab-send-pulse {
  50% {
    opacity: 0.35;
  }
}
.collab-attach-block {
  margin-top: 0.35rem;
  padding: 0.35rem 0.4rem;
  border-radius: 6px;
  background: rgba(0, 0, 0, 0.2);
  border: 1px solid #3a5280;
}
.collab-attach-name {
  font-size: 0.78rem;
  color: #e4ecff;
  word-break: break-all;
  margin-bottom: 0.35rem;
  line-height: 1.3;
}
.collab-attach-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  align-items: center;
}
.collab-attach-action {
  font-size: 0.72rem;
  padding: 0.25rem 0.5rem;
  border-radius: 4px;
  cursor: pointer;
  border: 1px solid #516897;
  background: #2c3d5c;
  color: #dbe8ff;
}
.collab-attach-action:hover {
  background: #3a5280;
  border-color: #5a7fc7;
}
.collab-action-open {
  border-color: #4a7a9e;
}
.collab-action-save {
  border-color: #5a8060;
  background: #2a4a38;
}
.collab-action-save:hover {
  background: #346648;
}
.collab-compose {
  display: flex;
  gap: 0.3rem;
  align-items: flex-end;
}
.collab-textarea {
  min-height: 56px;
  max-height: 140px;
  resize: vertical;
  padding: 6px 8px;
  line-height: 1.35;
}
.collab-status {
  color: #aac0e6;
  font-size: 0.72rem;
  flex-shrink: 0;
}
/* В режиме split ширины 2D/3D задаются инлайн (centerPdfWidth) + сплиттер между панелями */
.content.mode-split .pdf-panel,
.content.mode-split .viewer-panel {
  min-height: 0;
}
.content.mode-2d {
  flex: 1;
  min-height: 0;
  min-width: 0;
}
.content.mode-2d .pdf-panel {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.content.mode-3d {
  flex: 1;
  min-height: 0;
  min-width: 0;
}
.content.mode-3d .viewer-panel {
  flex: 1 1 auto;
  width: 100%;
  min-width: 0;
  min-height: 0;
  align-self: stretch;
  display: flex;
  flex-direction: column;
}
.panel.pdf-panel {
  background: #1a2228;
}
.content.mode-log {
  flex: 1;
  min-height: 0;
  min-width: 0;
}
.content.mode-log .log-panel-wrap {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.content.mode-log .pdf-panel,
.content.mode-log .viewer-panel {
  display: none;
}
.panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  position: relative;
}
.panel-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #888;
  font-size: 0.95rem;
}
.panel-placeholder--pdf {
  flex-direction: column;
  gap: 0.55rem;
}
.pdf-panel-header {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 0.5rem;
  flex-wrap: wrap;
  padding: 0.4rem 0.6rem;
  background: #1a1a1a;
  border-bottom: 1px solid #333;
}
.pdf-panel-title {
  color: #fff;
  font-size: 0.82rem;
  font-weight: 600;
}
.pdf-panel-actions {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  flex-wrap: wrap;
}
.pdf-panel-btn {
  border: 1px solid rgba(255, 255, 255, 0.15);
  background: rgba(80, 110, 150, 0.5);
  color: #e0e0e0;
  border-radius: 4px;
  padding: 0.3rem 0.55rem;
  font-size: 0.82rem;
  cursor: pointer;
}
.pdf-panel-btn:hover {
  background: rgba(100, 130, 180, 0.6);
}
.pdf-panel-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.viewer-panel {
  position: relative;
}
:global(body.workspace-resizing) {
  cursor: col-resize !important;
  user-select: none;
}
</style>
